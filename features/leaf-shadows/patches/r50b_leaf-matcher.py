# r50b_leaf-matcher: the cut-out analysis of r50_leaf-stage1 widened to the game's own alpha test
# (the leaf stage 1 verdict's matcher changes E1..E7), so that the foliage, hair and cloth pixel
# shaders that r50 called "several textures" or "alpha with a varying" match, and the log says
# which memory dwords their test and coordinates read and what those hold at a draw. Nothing
# else: no picture change, no GPU resource, no change to any ray. Off by default, as r50:
# BB_RT_CARD_ALPHA_LOG=1 (read once) turns it on.
# check|apply|revert (revert restores byte for byte). On top of r50 as <tree> has it on
# 2026-11-15. The tree: the one the environment variable R50B_ROOT names; without it the current
# directory when that is the root of a source tree, else <tree>/. Nothing is changed in
# place: every new text is written beside its target and moved over it, and a failure puts back
# what was already moved. Files keep their line ends (CRLF or LF, as each file has them).
#
# WHY. r50's log (r50_game_log.txt) matched none of the plants' and hair's camera pass pixel
# shaders. The decompiled shaders (r50_spv) share one test: discard where
#   cb[20] > cb[21] * (D.w - 0.5) + A  or  A * fade == 0,   A = T.w * vertex colour.w,
# T sampled at uv * cb[0,1] + cb[2,3], D (the camera pass only) a screen space noise sampled at
# 0.25 * cb[4|5] * (+-0.5 * pos.xy / pos.w + 0.5), fade a per-instance float of a storage buffer.
# The sun shadow pass form (92852ef3, 9ce84451) is cb[21] * -0.5 with no D. A ray at a card's
# hit can repeat the sun form, alpha >= cb[20] + 0.5 * cb[21], with the draw's constants.
#
# WHAT (shader_recompiler/ir/passes/cutout_analysis_pass.cpp, cutout_analysis.h, info.h):
#  E1 a dither: a channel of a second sample that enters the compare only linearly, times an
#     immediate or one dword (k * (D.c + c0)), sampled at a screen position (u the x and v the y
#     of one input over its own w: FPRecip32 of the w times x or y, or FPDiv32 by it, the input
#     read with GetAttribute or interpolated by hand, as 1c3953c6's pervertexEXT position is; or
#     u and v FragCoord's x and y), times immediates or dwords, whose T# at the compile, where the
#     draw's user data hold it, is at most 64x64, is taken as 0 (the sun pass form); recorded
#     (dither, its image, channel, coefficient, T# size). A second main term that reads it makes
#     several textures; a nonzero term that reads it is refused. One that would be a dither but
#     for where it is sampled or its size: "several textures (dither not a screen space noise)".
#  E2 the reference up to two dwords: ref + ref_scale * d1 + ref2_scale * d2 (ref2_*).
#  E3 the alpha times one input component, once (alpha_input, alpha_comp; 0xff none), the input
#     smooth: GetAttribute(ParamN, c) only where Info::fs_interpolation is smooth (not a
#     per-vertex read, which is vertex 0's value, nor flat or no-perspective), the manual
#     interpolation only with perspective barycentrics.
#  E4 a term P == 0 kept when false (or P != 0 kept when true), P the alpha or a product of it
#     with factors that read no texture: nonzero, the ignored factors counted and recorded by
#     kind (ignored_factor_terms, ignored_kinds: a buffer load, dwords, an input, computed).
#  E5 a coordinate scale or offset that is exactly one dword is recorded (uv_kind, uv_buffer,
#     uv_scale_dword, uv_offset_dword; 0xffff an immediate), else uv_unrecorded; r50's
#     Repeatable() is RepeatableFromRecord(), and RepeatableWithConstants() is matched with every
#     memory value one recorded dword, no texel offset, no computed layer, no other discard term
#     and no ignored nonzero factor that is an input or computed.
#  Saturate and clamp(0, 1), which r50 passed as if they were not there: folded on an immediate;
#     over a texel side with no input factor, as its outermost operation, only where the other
#     side is an immediate the clamp does not change the test for; else "other (clamped)" (in
#     coordinates: computed).
#  E6 every compile's Info gets the result (as r50 did), with the pixel shader inputs it saw
#     (num_inputs, a bit per default and per flat input); a draw gets permutation 0's Info, so
#     a draw whose regs.ps_inputs differ is counted as another permutation and nothing is read
#     (CutoutSamePermutation). FindCutout(pgm_hash) gives the first compile's record to a draw
#     whose Info has none (a cached program), used only when its images.size() and
#     buffers.size() equal the record's (image_count, buffer_count).
#  E7 the draw-time part (vk_rasterizer_effects.cpp, EffectsCaptureDraw, after r50's
#     pixel_shader): every draw of a record with RepeatableWithConstants() is counted by its
#     dwords: user data and flat user data from the Info; a constant buffer's from its V# when
#     the shader does not write it, the V# valid, inside the buffer and a GPU mapping
#     (ClampRangeSize) and the dword in no region the GPU wrote (IsRegionGpuModified, as r17:
#     such a dword is NOT read, and counted GPU-written, or in place where IsInPlace holds). The
#     first draw of a pgm_hash prints the values, the vertex shader outputs of the uv and the
#     alpha factor's input (regs.ps_inputs), the stored channel of the draw's T# and the
#     dither's T# size. The cards' line counts per class the matched, those whose every draw had
#     CPU-written constants, those with no memory constants, and the draws by state; the shader
#     line names the matched form; an unmatched "several textures" line counts its samples (at
#     an input, screen space, computed).
#  tests/test_rt_card_alpha.cpp: r50's tests (Repeatable() renamed; alpha * colour now matches)
#     and the game's forms built with IREmitter as the translator leaves them (V_MAD as
#     FPAdd(FPMul), V_RCP as FPRecip, the manual interpolation, the buffer load), the refused
#     shapes next to them (the reviews' probes among them), the permutation check, the draw-time
#     line and the cards' counts.
# KNOB OFF: nothing new runs. The pass runs only under CutoutAnalysisOn() (recompiler.cpp, r50);
# the draw-time part costs one test of a static bool read once per draw captured for ray tracing.
# KNOB ON: the draw-time part takes the analysis' mutex once per draw of a matched shader (twice
# for a cached program's Info: FindCutout), held for a hash map lookup; compile threads take it
# once per compile.
# LOG (new lines tagged r50b; the shader, totals and cards lines keep r50's tag):
#   Cut-out pixel shader <hash> (r50): match (dithered, x an input, nonzero), image 0 sampler 1, .w*in2.w (vs out 4) >= cb3[20]+0.5*cb3[21], dither -1*cb3[21]*image1.w taken as 0, uv in1.xy (vs out 3) *cb1[0,1]+cb1[2,3], 1 factors of the nonzero term ignored (a buffer load)
#   Cut-out constants <hash> (r50b): uv (in1.xy*(2,4)+(0.5,0.25), vs out 3), ref 0.3 + 0.5*0.2 = 0.4, camera dither -0.2*image1.w (4x4) (taken as 0), alpha factor in2.w (vs out 4), stored channel a, CPU-written
#   totals: ... (r50b: D dithered, V times an input, Z with a nonzero term, T with a reference of
#     two dwords; W repeatable with the draw's constants, N not, for ...)
#   cards, per class: [mix; R repeatable, W with constants; N match, M with CPU-written constants
#     on every draw, K with no memory constants; D draws: a CPU-written, b in place, c
#     GPU-written, d unreadable, e another permutation]
# NOT CHANGED: anything a ray, a pass or a picture uses; the cache's format; recompiler.cpp,
# vk_pipeline_serialization.cpp, vk_pipeline_cache.cpp, vk_rt_shadow.*, CMakeLists.txt (r50's
# lines serve as they are); the files of the r52 round (point_shadow_ray.comp, lamp_shadow_tune.h,
# vk_point_shadow.h/.cpp, test_lamp_shadow_tune.cpp, test_rt_shadows.cpp,
# docs/renderer-performance-0.9.43.md), the drawn look's and the volumetric/fog files.
# engine/build.sh: not registered, a deviation from the verdict and rule 2 (the test needs the
# recompiler's IR sources, fmt, magic_enum from the CMake build tree, which -Werror fails on in
# upstream headers, and link stubs that tests/test_gpu_runtime_stubs.cpp does not have).
# NOT DONE: a later permutation's own record is not what a draw reads (its draws are only
# counted); the dither and fade are not repeated by anything (a ray would use the sun form); no
# ray reads any of this.
# TEST: BB_RT_CARD_ALPHA_LOG=1, BB_GUEST_IN_PLACE unset, walk among plants with ray traced
# shadows on; read the cards' line (plants >= 3 of 4 and hair/cloth >= 3 of 5 with constants,
# static >= 1 of 2; CPU-written on every draw for >= 90 % of those with memory constants, and
# >= 90 % of the draws CPU-written) and the "(r50b)" constants lines; a run with the knob unset
# prints no "(r50" line.

import os
import sys

ROOT = os.environ.get("R50B_ROOT")
if not ROOT:
    ROOT = os.getcwd() if os.path.isfile("engine/gpu/shadps4/shader_recompiler/recompiler.cpp") \
        else "<tree>/"
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
SR = G + "shadps4/shader_recompiler/"
P = SR + "ir/passes/"
R = G + "shadps4/video_core/renderer_vulkan/"
TESTS = E + "tests/"

TMP = ".r50btmp"  # a new text waits under this name beside its target (main)

# Another round's files (r52 is being applied to them), the drawn look's and the volumetric/fog
# files: this one must not touch them.
FOREIGN = ("point_shadow_ray.comp", "lamp_shadow_tune.h", "vk_point_shadow.h", "vk_point_shadow.cpp",
           "test_lamp_shadow_tune.cpp", "test_rt_shadows.cpp", "renderer-performance-0.9.43.md")


def foreign(path):
    name = path.rsplit("/", 1)[-1]
    return name in FOREIGN or name.startswith(("vk_drawn_look.", "paint_", "drawn_")) or \
        "volumetric" in name or "fog" in name


# Whole files this round replaces: (the r50 text, the r50b text), compared with LF line ends.
REPLACED = {
    P + "cutout_analysis.h": (r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r50_leaf-stage1): the cut-out analysis, stage 1 of the ray traced foliage shadows. It
// reads from a pixel shader's IR which texture channel its discard compares with which reference,
// and at which input the texture is sampled (Info::Cutout). It changes nothing in the shader.
#pragma once

#include <string>
#include "shader_recompiler/info.h"

namespace Shader::IR {
struct Program;
}

namespace Shader::Optimization {

/// BB_RT_CARD_ALPHA_LOG=1 (read once): pixel shaders are analysed as they compile, and the cache
/// warm-up leaves the discarding ones to compile in play. Otherwise off, and none of this runs.
[[nodiscard]] bool CutoutAnalysisOn();

/// What the discards of a fragment program test (no knob, no log).
[[nodiscard]] Info::Cutout AnalyzeCutout(const IR::Program& program, const RuntimeInfo& runtime_info);

/// The log line of a pixel shader's info.cutout (under 200 characters).
[[nodiscard]] std::string CutoutLine(const Info& info, const RuntimeInfo& runtime_info);

/// AnalyzeCutout into program.info.cutout; a log line for a pixel shader not seen before.
void CutoutAnalysisPass(IR::Program& program, const RuntimeInfo& runtime_info);

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

/// The two 600-frame lines (empty while nothing is to be said, or the knob is off).
[[nodiscard]] std::string CutoutSummaryText();
[[nodiscard]] std::string CutoutCardsText();

/// With the knob on, both lines on stdout (every 600 frames, RtShadow::OnFrameEnd).
void PrintCutoutSummary();

} // namespace Shader::Optimization
""", r"""// SPDX-License-Identifier: GPL-3.0-or-later
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

/// BB_RT_CARD_ALPHA_LOG=1 (read once): pixel shaders are analysed as they compile, and the cache
/// warm-up leaves the discarding ones to compile in play. Otherwise off, and none of this runs.
[[nodiscard]] bool CutoutAnalysisOn();

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
"""),
    P + "cutout_analysis_pass.cpp": (r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r50_leaf-stage1): the cut-out analysis (cutout_analysis.h). It runs after
// CollectShaderInfoPass, on the program as it goes to SPIR-V, and reads:
//  - the discards: DiscardCond(LogicalNot(exec)) of an export with vm (export.cpp), where exec is
//    the LogicalAnd of the v_cmpx compares (vector_alu.cpp) or of the s_andn2 masks folded into
//    LogicalAnd/LogicalNot (InverseBallotEliminationPass); several discards, phis whose operands
//    agree, and the clip distance discards of InjectClipDistanceAttributes (left out);
//  - where each discard sits in the structured program (syntax_list): every branch over it, and
//    every branch an early return left behind, must be one the alpha test decides (an exec scope
//    of the v_cmpx, an execz skip: its condition made of the discard's own terms), else the test
//    does not hold on every way through (a uniform switch, a discard in an if); an unconditional
//    Discard is a kill only where every pixel reaching it fails a term (the execz kill block);
//  - the terms that keep the pixel: their conjunction, each a float compare (ordered or not);
//  - each side of the compare as one variable times a factor plus an offset, through FPAdd,
//    FPSub, FPMul, FPFma, FPNeg, FPSaturate, FPClamp(0, 1), bit casts and V_MUL_LEGACY's zero
//    select (only that select: its condition the product's own factors equal to zero): the
//    variable a channel of ImageSampleImplicitLod/ExplicitLod/ImageGradient, the constants
//    immediates or one dword of user data, of the flat user data (ReadConst) or of a constant
//    buffer (ReadConstBuffer at an immediate dword). "alpha - ref >= 0" is "alpha >= ref";
//  - the sample's coordinates the same way, the variable an input: GetAttribute(ParamN, c), or
//    GCN's two manual interpolation steps that HardwareInterpolationPass left in place.
// Every walk is bounded (depth, and a count of the instructions it visits) and remembers what it
// evaluated, so an expression that reuses a value costs once.

#include "shader_recompiler/ir/passes/cutout_analysis.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <optional>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "shader_recompiler/ir/basic_block.h"
#include "shader_recompiler/ir/program.h"

namespace Shader::Optimization {
namespace {

using Cutout = Info::Cutout;
using Verdict = Cutout::Verdict;
using Detail = Cutout::Detail;
using Op = Cutout::Op;
using Ref = Cutout::Ref;
using Layer = Cutout::Layer;

constexpr u32 MaxDepth = 32;
constexpr size_t MaxVisits = 4096;

bool Is(const IR::Inst* inst, IR::Opcode opcode) {
    return inst && inst->GetOpcode() == opcode;
}

bool ImmF32(const IR::Value& value, f32 x) {
    return value.IsImmediate() && value.Type() == IR::Type::F32 && value.F32() == x;
}

/// a + b * (one dword in memory, read as a float); kind Immediate when b is 0.
struct Scalar {
    f32 a = 0.0f;
    f32 b = 0.0f;
    Ref kind = Ref::Immediate;
    u8 buffer = 0;
    u16 dword = 0;
};

Scalar Plain(Scalar x) {
    if (x.b == 0.0f) {
        x = {.a = x.a};
    }
    return x;
}

Scalar Neg(Scalar x) {
    x.a = -x.a;
    x.b = -x.b;
    return Plain(x);
}

enum class Var : u8 { None, Texel, Input };

/// variable * scale + offset. Texel: `index` is the channel of `sample`; Input: the parameter,
/// `comp` its component.
struct Linear {
    Var var = Var::None;
    const IR::Inst* sample = nullptr;
    u32 index = 0;
    u32 comp = 0;
    Scalar scale{.a = 1.0f};
    Scalar offset{};
};

/// V_MUL_LEGACY_F32 (vector_alu.cpp): Select(FPEqual(a, 0) || FPEqual(b, 0), 0, a * b), with the
/// compare of an immediate factor folded away: the product, 0 where a factor is 0. Any other
/// zeroing select (V_CNDMASK_B32 of a fade, a flag, a distance) is not one.
bool LegacyProduct(const IR::Inst& select) {
    const IR::Inst* mul = select.Arg(2).TryInst();
    if (!Is(mul, IR::Opcode::FPMul32)) {
        return false;
    }
    std::array<bool, 2> covered{};
    std::vector<IR::Value> stack{select.Arg(0)};
    while (!stack.empty()) {
        const IR::Value value = stack.back();
        stack.pop_back();
        if (value.IsImmediate()) {
            if (value.Type() == IR::Type::U1 && !value.U1()) {
                continue; // a leaf folded to false
            }
            return false;
        }
        const IR::Inst* inst = value.Inst();
        if (Is(inst, IR::Opcode::LogicalOr)) {
            if (stack.size() > 4) {
                return false;
            }
            stack.push_back(inst->Arg(0));
            stack.push_back(inst->Arg(1));
            continue;
        }
        if (!Is(inst, IR::Opcode::FPOrdEqual32) && !Is(inst, IR::Opcode::FPUnordEqual32)) {
            return false;
        }
        const IR::Value other = ImmF32(inst->Arg(1), 0.0f)   ? inst->Arg(0)
                                : ImmF32(inst->Arg(0), 0.0f) ? inst->Arg(1)
                                                             : IR::Value{};
        bool factor = false;
        for (u32 i = 0; i < 2; ++i) {
            if (!other.IsEmpty() && mul->Arg(i) == other) {
                covered[i] = true;
                factor = true;
            }
        }
        if (!factor) {
            return false;
        }
    }
    for (u32 i = 0; i < 2; ++i) {
        const IR::Value factor = mul->Arg(i);
        if (!covered[i] && !(factor.IsImmediate() && factor.Type() == IR::Type::F32 &&
                             factor.F32() != 0.0f)) {
            return false;
        }
    }
    return true;
}

class Walker {
public:
    explicit Walker(bool uv_) : uv{uv_} {}

    Detail why = Detail::None;

    std::optional<Linear> Eval(const IR::Value& value, u32 depth) {
        if (value.IsImmediate()) {
            if (value.Type() == IR::Type::F32) {
                return Linear{.offset = {.a = value.F32()}};
            }
            if (value.Type() == IR::Type::U32) {
                return Linear{.offset = {.a = std::bit_cast<f32>(value.U32())}};
            }
            return Fail(Detail::Computed);
        }
        if (depth > MaxDepth) {
            return Fail(Computed());
        }
        const IR::Inst* inst = value.Inst();
        if (const auto known = memo.find(inst); known != memo.end()) {
            return known->second;
        }
        if (++visits > MaxVisits) {
            return Fail(Computed());
        }
        const std::optional<Linear> result = Visit(*inst, depth);
        memo.emplace(inst, result);
        return result;
    }

private:
    bool uv;
    size_t visits = 0;
    std::unordered_map<const IR::Inst*, std::optional<Linear>> memo;

    std::optional<Linear> Visit(const IR::Inst& inst, u32 depth) {
        switch (inst.GetOpcode()) {
        case IR::Opcode::BitCastF32U32:
        case IR::Opcode::BitCastU32F32:
        case IR::Opcode::FPSaturate32:
            return Eval(inst.Arg(0), depth + 1);
        case IR::Opcode::FPClamp32:
            if (ImmF32(inst.Arg(1), 0.0f) && ImmF32(inst.Arg(2), 1.0f)) {
                return Eval(inst.Arg(0), depth + 1);
            }
            return Fail(Computed());
        case IR::Opcode::SelectF32:
            if (ImmF32(inst.Arg(1), 0.0f) && LegacyProduct(inst)) {
                return Eval(inst.Arg(2), depth + 1);
            }
            return Fail(Computed());
        case IR::Opcode::GetUserData:
            return Named(Ref::UserData, 0, u32(inst.Arg(0).ScalarReg()));
        case IR::Opcode::ReadConst:
            if (inst.Flags<u32>() != 0) {
                return Named(Ref::FlatUserData, 0, inst.Flags<u32>());
            }
            return Fail(Detail::RefComputed);
        case IR::Opcode::ReadConstBuffer:
            if (inst.Arg(0).IsImmediate() && inst.Arg(1).IsImmediate()) {
                return Named(Ref::ConstBuffer, inst.Arg(0).U32(), inst.Arg(1).U32());
            }
            return Fail(Detail::RefComputed);
        case IR::Opcode::CompositeExtractF32x4:
            return Channel(inst);
        case IR::Opcode::GetAttribute: {
            const IR::Attribute attr = inst.Arg(0).Attribute();
            if (IR::IsParam(attr) && inst.Arg(2).U32() == 0) {
                return Linear{.var = Var::Input,
                              .index = u32(attr) - u32(IR::Attribute::Param0),
                              .comp = inst.Arg(1).U32()};
            }
            return Fail(Computed());
        }
        case IR::Opcode::FPNeg32: {
            auto x = Eval(inst.Arg(0), depth + 1);
            if (x) {
                x->scale = Neg(x->scale);
                x->offset = Neg(x->offset);
            }
            return x;
        }
        case IR::Opcode::FPAdd32:
        case IR::Opcode::FPSub32: {
            const auto x = Eval(inst.Arg(0), depth + 1);
            if (!x) {
                return std::nullopt;
            }
            auto y = Eval(inst.Arg(1), depth + 1);
            if (!y) {
                return std::nullopt;
            }
            if (inst.GetOpcode() == IR::Opcode::FPSub32) {
                y->scale = Neg(y->scale);
                y->offset = Neg(y->offset);
            }
            return Sum(*x, *y);
        }
        case IR::Opcode::FPMul32: {
            const auto x = Eval(inst.Arg(0), depth + 1);
            if (!x) {
                return std::nullopt;
            }
            const auto y = Eval(inst.Arg(1), depth + 1);
            if (!y) {
                return std::nullopt;
            }
            return Product(*x, *y);
        }
        case IR::Opcode::FPFma32: {
            if (auto input = Interpolated(inst)) {
                return input;
            }
            const auto x = Eval(inst.Arg(0), depth + 1);
            if (!x) {
                return std::nullopt;
            }
            const auto y = Eval(inst.Arg(1), depth + 1);
            if (!y) {
                return std::nullopt;
            }
            const auto product = Product(*x, *y);
            if (!product) {
                return std::nullopt;
            }
            const auto z = Eval(inst.Arg(2), depth + 1);
            if (!z) {
                return std::nullopt;
            }
            return Sum(*product, *z);
        }
        case IR::Opcode::Phi:
            return Fail(Detail::ControlFlow);
        default:
            return Fail(Computed());
        }
    }

    std::nullopt_t Fail(Detail detail) {
        if (why == Detail::None) {
            why = detail;
        }
        return std::nullopt;
    }

    Detail Computed() const {
        return uv ? Detail::UvComputed : Detail::Computed;
    }

    static Linear Named(Ref kind, u32 buffer, u32 dword) {
        return Linear{.offset = {.b = 1.0f, .kind = kind, .buffer = u8(buffer), .dword = u16(dword)}};
    }

    std::optional<Linear> Channel(const IR::Inst& extract) {
        const IR::Inst* sample = extract.Arg(0).TryInst();
        if (!sample || !extract.Arg(1).IsImmediate()) {
            return Fail(Computed());
        }
        switch (sample->GetOpcode()) {
        case IR::Opcode::ImageSampleImplicitLod:
        case IR::Opcode::ImageSampleExplicitLod:
        case IR::Opcode::ImageGradient:
            return Linear{.var = Var::Texel, .sample = sample, .index = extract.Arg(1).U32()};
        case IR::Opcode::ImageSampleDrefImplicitLod:
        case IR::Opcode::ImageSampleDrefExplicitLod:
        case IR::Opcode::ImageGather:
        case IR::Opcode::ImageGatherDref:
        case IR::Opcode::ImageRead:
            return Fail(Detail::SampleKind);
        default:
            return Fail(Computed());
        }
    }

    /// GCN's two interpolation steps on one component of an input, P0 + I (P1 - P0) +
    /// J (P2 - P0) (vector_interpolation.cpp), where HardwareInterpolationPass kept them.
    static std::optional<Linear> Interpolated(const IR::Inst& fma2) {
        const IR::Inst* sub2 = fma2.Arg(0).TryInst();
        const IR::Inst* j = fma2.Arg(1).TryInst();
        const IR::Inst* fma1 = fma2.Arg(2).TryInst();
        if (!Is(sub2, IR::Opcode::FPSub32) || !Is(j, IR::Opcode::GetAttribute) ||
            !Is(fma1, IR::Opcode::FPFma32)) {
            return std::nullopt;
        }
        const IR::Inst* sub1 = fma1->Arg(0).TryInst();
        const IR::Inst* i = fma1->Arg(1).TryInst();
        const IR::Inst* p0 = fma1->Arg(2).TryInst();
        if (!Is(sub1, IR::Opcode::FPSub32) || !Is(i, IR::Opcode::GetAttribute) ||
            !Is(p0, IR::Opcode::GetAttribute)) {
            return std::nullopt;
        }
        const IR::Attribute param = p0->Arg(0).Attribute();
        const u32 comp = p0->Arg(1).U32();
        const auto read = [&](const IR::Value& value, u32 index) {
            const IR::Inst* r = value.TryInst();
            return Is(r, IR::Opcode::GetAttribute) && r->Arg(0).Attribute() == param &&
                   r->Arg(1).U32() == comp && r->Arg(2).U32() == index;
        };
        const IR::Attribute bary = i->Arg(0).Attribute();
        if (!IR::IsParam(param) || p0->Arg(2).U32() != 0 || !read(sub1->Arg(0), 1) ||
            !read(sub1->Arg(1), 0) || !read(sub2->Arg(0), 2) || !read(sub2->Arg(1), 0) ||
            IR::IsParam(bary) || j->Arg(0).Attribute() != bary || i->Arg(1).U32() != 0 ||
            j->Arg(1).U32() != 1) {
            return std::nullopt;
        }
        return Linear{.var = Var::Input, .index = u32(param) - u32(IR::Attribute::Param0),
                      .comp = comp};
    }

    /// Two variables in one sum or product.
    Detail Mixed(const Linear& x, const Linear& y, bool product) const {
        if (uv) {
            return Detail::UvComputed;
        }
        if (x.var == Var::Texel && y.var == Var::Texel) {
            return x.sample == y.sample ? Detail::TwoChannels : Detail::SeveralTextures;
        }
        if (x.var == Var::Input && y.var == Var::Input) {
            return Detail::VaryingRef; // a value made of varyings (the alpha has no part in it)
        }
        // alpha * varying is a factor; alpha + varying moves the reference by the varying
        return product ? Detail::VaryingFactor : Detail::VaryingRef;
    }

    std::optional<Scalar> Add(const Scalar& x, const Scalar& y) {
        if (x.b != 0.0f && y.b != 0.0f &&
            (x.kind != y.kind || x.buffer != y.buffer || x.dword != y.dword)) {
            return Fail(Detail::TwoConstants);
        }
        Scalar r = x.b != 0.0f ? x : y;
        r.a = x.a + y.a;
        r.b = x.b + y.b;
        return Plain(r);
    }

    std::optional<Scalar> Mul(const Scalar& x, const Scalar& y) {
        if (x.b != 0.0f && y.b != 0.0f) {
            return Fail(Detail::TwoConstants);
        }
        Scalar r = x.b != 0.0f ? x : y;
        r.a = x.a * y.a;
        r.b = x.a * y.b + x.b * y.a;
        return Plain(r);
    }

    std::optional<Linear> Sum(const Linear& x, const Linear& y) {
        if (x.var != Var::None && y.var != Var::None) {
            return Fail(Mixed(x, y, false));
        }
        Linear r = x.var != Var::None ? x : y;
        const auto offset = Add(x.offset, y.offset);
        if (!offset) {
            return std::nullopt;
        }
        r.offset = *offset;
        return r;
    }

    std::optional<Linear> Product(const Linear& x, const Linear& y) {
        if (x.var != Var::None && y.var != Var::None) {
            return Fail(Mixed(x, y, true));
        }
        Linear r = x.var != Var::None ? x : y;
        const Scalar& factor = x.var != Var::None ? y.offset : x.offset;
        const auto scale = Mul(r.scale, factor);
        const auto offset = Mul(r.offset, factor);
        if (!scale || !offset) {
            return std::nullopt;
        }
        r.scale = *scale;
        r.offset = *offset;
        return r;
    }
};

/// The pixel is kept only where `value` is `keep_when`.
struct Term {
    IR::Value value;
    bool keep_when;
};

bool SameTerm(const Term& x, const Term& y) {
    return x.value == y.value && x.keep_when == y.keep_when;
}

using Seen = std::unordered_set<std::uintptr_t>;

/// The terms that all hold exactly where `value` is `keep_when` (for a discard condition
/// `keep_when` false: the terms that keep the pixel); a value it does not take apart is a term
/// itself. A term that always holds adds nothing; one that never holds is a branch's discard.
void Terms(const IR::Value& value, bool keep_when, std::vector<Term>& out, Detail& why, u32 depth,
           Seen& seen) {
    if (value.IsImmediate()) {
        if (value.Type() == IR::Type::U1 && value.U1() != keep_when && why == Detail::None) {
            why = Detail::BranchDiscard;
        }
        return;
    }
    const IR::Inst* inst = value.Inst();
    if (!seen.insert(reinterpret_cast<std::uintptr_t>(inst) | (keep_when ? 1u : 0u)).second) {
        return; // walked already
    }
    if (depth < MaxDepth && seen.size() < MaxVisits) {
        switch (inst->GetOpcode()) {
        case IR::Opcode::ConditionRef:
            return Terms(inst->Arg(0), keep_when, out, why, depth + 1, seen);
        case IR::Opcode::LogicalNot:
            return Terms(inst->Arg(0), !keep_when, out, why, depth + 1, seen);
        case IR::Opcode::LogicalAnd:
        case IR::Opcode::LogicalOr:
            if (keep_when == (inst->GetOpcode() == IR::Opcode::LogicalAnd)) {
                Terms(inst->Arg(0), keep_when, out, why, depth + 1, seen);
                Terms(inst->Arg(1), keep_when, out, why, depth + 1, seen);
                return;
            }
            break;
        case IR::Opcode::Phi: {
            // One value on every way in (the phi itself aside): that value.
            IR::Value same{};
            bool one = true;
            for (size_t arg = 0; arg < inst->NumArgs(); ++arg) {
                const IR::Value in = inst->Arg(arg);
                if (in.TryInst() == inst) {
                    continue;
                }
                one = one && (same.IsEmpty() || same == in);
                same = in;
            }
            if (one && !same.IsEmpty()) {
                return Terms(same, keep_when, out, why, depth + 1, seen);
            }
            break;
        }
        default:
            break;
        }
    }
    const Term term{value, keep_when};
    if (std::ranges::none_of(out, [&](const Term& t) { return SameTerm(t, term); })) {
        out.push_back(term);
    }
}

bool IsSample(IR::Opcode opcode) {
    switch (opcode) {
    case IR::Opcode::ImageSampleRaw:
    case IR::Opcode::ImageSampleImplicitLod:
    case IR::Opcode::ImageSampleExplicitLod:
    case IR::Opcode::ImageSampleDrefImplicitLod:
    case IR::Opcode::ImageSampleDrefExplicitLod:
    case IR::Opcode::ImageGather:
    case IR::Opcode::ImageGatherDref:
    case IR::Opcode::ImageGradient:
    case IR::Opcode::ImageRead:
        return true;
    default:
        return false;
    }
}

/// Whether `value` reads a texture; the image reads whose results feed it go to `samples` (not
/// followed further back, through their coordinates). A walk cut short counts as a read of its
/// own (nullptr).
bool Samples(const IR::Value& value, std::vector<const IR::Inst*>& samples) {
    std::vector<const IR::Inst*> stack;
    std::unordered_set<const IR::Inst*> seen;
    bool found = false;
    if (const IR::Inst* inst = value.TryInst()) {
        stack.push_back(inst);
    }
    while (!stack.empty()) {
        const IR::Inst* inst = stack.back();
        stack.pop_back();
        if (!seen.insert(inst).second) {
            continue;
        }
        if (seen.size() > MaxVisits) {
            samples.push_back(nullptr); // too far to follow: taken for a texture's
            return true;
        }
        if (IsSample(inst->GetOpcode())) {
            samples.push_back(inst);
            found = true;
            continue;
        }
        for (size_t arg = 0; arg < inst->NumArgs(); ++arg) {
            if (const IR::Inst* in = inst->Arg(arg).TryInst()) {
                stack.push_back(in);
            }
        }
    }
    return found;
}

/// A phi in the logic of a term (LogicalNot/And/Or): an exec value that depends on the way in.
bool ReachesPhi(const IR::Value& value) {
    std::vector<const IR::Inst*> stack;
    std::unordered_set<const IR::Inst*> seen;
    if (const IR::Inst* inst = value.TryInst()) {
        stack.push_back(inst);
    }
    while (!stack.empty() && seen.size() < MaxVisits) {
        const IR::Inst* inst = stack.back();
        stack.pop_back();
        if (!seen.insert(inst).second) {
            continue;
        }
        switch (inst->GetOpcode()) {
        case IR::Opcode::Phi:
            return true;
        case IR::Opcode::LogicalNot:
        case IR::Opcode::LogicalAnd:
        case IR::Opcode::LogicalOr:
        case IR::Opcode::ConditionRef:
            for (size_t arg = 0; arg < inst->NumArgs(); ++arg) {
                if (const IR::Inst* in = inst->Arg(arg).TryInst()) {
                    stack.push_back(in);
                }
            }
            break;
        default:
            break;
        }
    }
    return false;
}

std::optional<Op> CompareOp(IR::Opcode opcode) {
    switch (opcode) {
    case IR::Opcode::FPOrdLessThan32:
    case IR::Opcode::FPUnordLessThan32:
        return Op::Less;
    case IR::Opcode::FPOrdLessThanEqual32:
    case IR::Opcode::FPUnordLessThanEqual32:
        return Op::LessEqual;
    case IR::Opcode::FPOrdGreaterThan32:
    case IR::Opcode::FPUnordGreaterThan32:
        return Op::Greater;
    case IR::Opcode::FPOrdGreaterThanEqual32:
    case IR::Opcode::FPUnordGreaterThanEqual32:
        return Op::GreaterEqual;
    case IR::Opcode::FPOrdEqual32:
    case IR::Opcode::FPUnordEqual32:
        return Op::Equal;
    case IR::Opcode::FPOrdNotEqual32:
    case IR::Opcode::FPUnordNotEqual32:
        return Op::NotEqual;
    default:
        return std::nullopt;
    }
}

/// a < b as b > a.
Op Mirror(Op op) {
    switch (op) {
    case Op::Less:
        return Op::Greater;
    case Op::LessEqual:
        return Op::GreaterEqual;
    case Op::Greater:
        return Op::Less;
    case Op::GreaterEqual:
        return Op::LessEqual;
    default:
        return op;
    }
}

/// not (a < b) as a >= b (NaN aside).
Op Invert(Op op) {
    switch (op) {
    case Op::Less:
        return Op::GreaterEqual;
    case Op::LessEqual:
        return Op::Greater;
    case Op::Greater:
        return Op::LessEqual;
    case Op::GreaterEqual:
        return Op::Less;
    case Op::Equal:
        return Op::NotEqual;
    default:
        return Op::Equal;
    }
}

struct Test {
    Op op;
    Linear alpha;
    Scalar ref;
};

/// A term as "channel <op> reference".
std::optional<Test> Compare(const Term& term, Detail& why) {
    const IR::Inst* inst = term.value.TryInst();
    const std::optional<Op> op = inst ? CompareOp(inst->GetOpcode()) : std::nullopt;
    if (!op) {
        why = ReachesPhi(term.value) ? Detail::ControlFlow
              : Is(inst, IR::Opcode::LogicalAnd) || Is(inst, IR::Opcode::LogicalOr)
                  ? Detail::Disjunction
                  : Detail::NotCompare;
        return std::nullopt;
    }
    Walker walker{false};
    auto lhs = walker.Eval(inst->Arg(0), 0);
    auto rhs = lhs ? walker.Eval(inst->Arg(1), 0) : std::nullopt;
    if (!lhs || !rhs) {
        why = walker.why;
        return std::nullopt;
    }
    Test test{.op = *op, .alpha = {}, .ref = {}};
    if (rhs->var == Var::Texel) {
        std::swap(lhs, rhs);
        test.op = Mirror(test.op);
    }
    if (lhs->var != Var::Texel || rhs->var != Var::None) {
        why = rhs->var == Var::Texel
                  ? (rhs->sample == lhs->sample ? Detail::TwoChannels : Detail::SeveralTextures)
              : rhs->var == Var::Input ? Detail::VaryingRef
                                       : Detail::Computed;
        return std::nullopt;
    }
    // channel * s + o1 <op> o2: channel <op> (o2 - o1) / s, mirrored for a negative s.
    const f32 s = lhs->scale.a;
    if (lhs->scale.b != 0.0f || s == 0.0f) {
        why = Detail::ConstantScale;
        return std::nullopt;
    }
    const Scalar o1 = Neg(lhs->offset), o2 = rhs->offset;
    if (o1.b != 0.0f && o2.b != 0.0f &&
        (o1.kind != o2.kind || o1.buffer != o2.buffer || o1.dword != o2.dword)) {
        why = Detail::TwoConstants;
        return std::nullopt;
    }
    test.ref = o1.b != 0.0f ? o1 : o2;
    test.ref.a = (o1.a + o2.a) / s;
    test.ref.b = (o1.b + o2.b) / s;
    test.ref = Plain(test.ref);
    test.op = s < 0.0f ? Mirror(test.op) : test.op;
    test.op = term.keep_when ? test.op : Invert(test.op);
    test.alpha = *lhs;
    return test;
}

/// A DiscardCond of InjectClipDistanceAttributes: input `num_inputs - 1` below zero.
bool ClipDiscard(const IR::Inst& discard, const RuntimeInfo& runtime_info) {
    const auto& fs = runtime_info.hw.fs;
    const IR::Inst* cmp = discard.Arg(0).TryInst();
    if (!fs.clip_distance_emulation || fs.num_inputs == 0 ||
        !Is(cmp, IR::Opcode::FPOrdLessThan32) || !cmp->Arg(1).IsImmediate()) {
        return false;
    }
    const IR::Inst* read = cmp->Arg(0).TryInst();
    return Is(read, IR::Opcode::GetAttribute) &&
           read->Arg(0).Attribute() == IR::Attribute::Param0 + (fs.num_inputs - 1);
}

/// What the lanes at a point of the structured program all have: `cond` is `holds` (an If's
/// condition inside its body, false after an If whose body returned).
struct PathCond {
    IR::Value cond;
    bool holds;
};

/// A discard (inst) or an early return (inst nullptr), with the conditions on the way to it.
struct Site {
    const IR::Inst* inst;
    std::vector<PathCond> path;
    u32 loops;
};

/// The discards and returns in the order of the syntax list. Without one (a program built by
/// hand), the blocks as they are, all on the top level.
std::vector<Site> Sites(const IR::Program& program, const RuntimeInfo& runtime_info) {
    std::vector<Site> sites;
    const auto block_sites = [&](const IR::Block& block, const std::vector<PathCond>& path,
                                 u32 loops) {
        for (const IR::Inst& inst : block.Instructions()) {
            if (inst.GetOpcode() == IR::Opcode::Discard ||
                (inst.GetOpcode() == IR::Opcode::DiscardCond && !ClipDiscard(inst, runtime_info))) {
                sites.push_back({&inst, path, loops});
            }
        }
    };
    if (program.syntax_list.empty()) {
        for (const IR::Block* block : program.blocks) {
            block_sites(*block, {}, 0);
        }
        return sites;
    }
    using Type = IR::AbstractSyntaxNode::Type;
    struct Scope {
        IR::Value cond;
        size_t path_size;
        u32 loops;
        bool returned;
    };
    std::vector<Scope> scopes;
    std::vector<PathCond> path;
    u32 loops = 0;
    for (const IR::AbstractSyntaxNode& node : program.syntax_list) {
        switch (node.type) {
        case Type::Block:
            block_sites(*node.data.block, path, loops);
            break;
        case Type::If:
            scopes.push_back({node.data.if_node.cond, path.size(), loops, false});
            path.push_back({node.data.if_node.cond, true});
            break;
        case Type::EndIf:
            if (!scopes.empty()) {
                const Scope scope = scopes.back();
                scopes.pop_back();
                path.resize(scope.path_size);
                if (scope.returned) {
                    path.push_back({scope.cond, false}); // the rest of the parent's body
                }
            }
            break;
        case Type::Loop:
            ++loops;
            break;
        case Type::Repeat:
            loops -= loops != 0 ? 1 : 0;
            break;
        case Type::Return:
            if (!scopes.empty() && scopes.back().loops == loops) {
                scopes.back().returned = true;
            }
            sites.push_back({nullptr, path, loops});
            break;
        default:
            break;
        }
    }
    return sites;
}

Cutout Result(Verdict verdict, Detail detail) {
    return Cutout{.verdict = verdict, .detail = detail};
}

/// The T# of the alpha's image as the compiling draw's user data hold it: the stored channel the
/// view lane reads (the view applies dst_sel) and the format.
void ReadTsharp(const Info& info, Cutout& c) {
    if (c.image >= info.images.size()) {
        return;
    }
    const ImageResource& resource = info.images[c.image];
    const auto& fetch = resource.sharp_fetch;
    const auto flat = info.FlatUserData();
    // the dwords ImageResource::Fetch reads (4 of an r128 T#), each known and inside the buffer
    const size_t dwords = resource.is_r128 ? 4 : fetch.offsets.size();
    u8 mask = fetch.load_mask;
    for (size_t i = 0; i < dwords; ++i) {
        const auto offset = fetch.offsets[i];
        if (offset == UNKNOWN_LOCATION || ((mask & 1) != 0 && offset >= flat.size())) {
            return;
        }
        mask >>= 1;
    }
    AmdGpu::Image image{};
    if (!resource.Fetch(flat.data(), &image) || !image.Valid()) {
        return;
    }
    c.stored = u8(image.DstSelect().array[c.channel & 3]);
    c.data_format = u8(image.data_format);
}

constexpr std::array VerdictNames = {"not analysed",          "match",
                                     "no discard",            "no: not from a texture",
                                     "no: uv not an input",   "no: several textures",
                                     "no: other"};
constexpr std::array VerdictShort = {"not analysed", "match",           "no discard", "not a texture",
                                     "uv not an input", "several textures", "other"};
constexpr std::array DetailNames = {
    "",                    "discard in a branch",  "through a phi or a branch",
    "an OR of tests",      "not a float compare",  "alpha with a varying",
    "ref is a varying",    "scaled from memory",   "two memory values",
    "dynamic address",     "depth/gather/load",    "computed",
    "two alpha tests",     "several textures",     "uv computed",
    "u and v two inputs",  "two channels"};
static_assert(VerdictNames.size() == size_t(Verdict::Other) + 1);
static_assert(VerdictShort.size() == VerdictNames.size());
static_assert(DetailNames.size() == size_t(Detail::Count));
constexpr std::array OpNames = {"<", "<=", ">", ">=", "==", "!="};
constexpr std::array ClassNames = {
    "plants (left out of lamp rays: a skeleton, no sun shadow pass draw)",
    "left out, no skeleton", "left out, a skeleton", "kept whole: a skeleton (hair, cloth, characters)",
    "kept whole, other"};
constexpr std::array ClassShort = {"plant", "no skeleton", "skeleton, left out",
                                   "skeleton, kept", "kept"};
static_assert(ClassNames.size() == size_t(CutoutCardClass::Count));
static_assert(ClassShort.size() == ClassNames.size());

char Swizzle(u8 stored) {
    switch (stored) {
    case 0:
        return '0';
    case 1:
        return '1';
    case 4:
        return 'r';
    case 5:
        return 'g';
    case 6:
        return 'b';
    case 7:
        return 'a';
    default:
        return '?';
    }
}

struct Counts {
    u32 analysed = 0;
    u32 at_last_line = 0;
    std::array<u32, VerdictNames.size()> verdicts{};
    std::array<u32, DetailNames.size()> details{};
    u32 channel_w = 0;
    u32 ref_immediate = 0;
    u32 uv_plain = 0;
    u32 with_terms = 0;
    u32 with_kills = 0;
    u32 not_repeatable = 0;
    u32 uv_memory = 0;
    u32 layer_other = 0;
    u32 texel_offset = 0;
};

/// A pixel shader of the scene's cut-out instances: the classes it was seen in (bit per
/// CutoutCardClass) by camera pass and sun shadow pass draws.
struct CardShader {
    u8 camera = 0;
    u8 sun = 0;
};

std::mutex counts_mutex;
Counts counts;
std::unordered_map<u64, Cutout> analysed_shaders;
std::unordered_map<u64, CardShader> card_shaders;
std::atomic<u32> cache_refusals{0};

void Append(std::string& text, const char* format, ...) {
    char part[512];
    va_list args;
    va_start(args, format);
    const int n = std::vsnprintf(part, sizeof(part), format, args);
    va_end(args);
    if (n > 0) {
        text.append(part, std::min(size_t(n), sizeof(part) - 1));
    }
}

} // namespace

bool CutoutAnalysisOn() {
    static const bool on = [] {
        const char* env = std::getenv("BB_RT_CARD_ALPHA_LOG");
        return env && std::strcmp(env, "1") == 0;
    }();
    return on;
}

Info::Cutout AnalyzeCutout(const IR::Program& program, const RuntimeInfo& runtime_info) {
    if (program.info.sw_stage != SwStage::Fragment) {
        return {};
    }
    const std::vector<Site> sites = Sites(program, runtime_info);
    std::vector<Term> terms;
    Detail why = Detail::None;
    Seen seen;
    size_t last_discard = 0;
    bool discards = false;
    for (size_t i = 0; i < sites.size(); ++i) {
        if (!sites[i].inst) {
            continue;
        }
        discards = true;
        last_discard = i;
        if (sites[i].inst->GetOpcode() == IR::Opcode::DiscardCond) {
            Terms(sites[i].inst->Arg(0), false, terms, why, 0, seen);
        }
    }
    if (!discards) {
        return Result(Verdict::NoDiscard, Detail::None);
    }
    // A branch the alpha test decides: the lanes it leaves out (cond not `holds`) fail a term of
    // the discards, so they die anyway (exec scope, execz skip). Kill: every lane with cond
    // `holds` fails a term (a non-empty set of them).
    const auto within = [&](const IR::Value& cond, bool holds, bool nonempty) {
        std::vector<Term> part;
        Detail local = Detail::None;
        Seen local_seen;
        Terms(cond, holds, part, local, 0, local_seen);
        return local == Detail::None && (!nonempty || !part.empty()) &&
               std::ranges::all_of(part, [&](const Term& t) {
                   return std::ranges::any_of(terms, [&](const Term& u) { return SameTerm(t, u); });
               });
    };
    const auto decided = [&](const PathCond& p) { return within(p.cond, p.holds, false); };
    const auto kill = [&](const PathCond& p) { return within(p.cond, !p.holds, true); };
    u32 kills = 0;
    for (size_t i = 0; i < sites.size() && why == Detail::None; ++i) {
        const Site& site = sites[i];
        if (!site.inst) {
            // an early return: discards after it are not reached by the lanes it takes out
            if (i < last_discard && (site.loops != 0 || !std::ranges::all_of(site.path, decided))) {
                why = Detail::ControlFlow;
            }
        } else if (site.inst->GetOpcode() == IR::Opcode::DiscardCond) {
            if (site.loops != 0 || !std::ranges::all_of(site.path, decided)) {
                why = Detail::ControlFlow;
            }
        } else if (site.loops == 0 && std::ranges::any_of(site.path, kill)) {
            ++kills;
        } else {
            why = Detail::BranchDiscard;
        }
    }
    if (why != Detail::None) {
        return Result(Verdict::Other, why);
    }
    std::vector<const Term*> texture_terms;
    std::vector<const IR::Inst*> samples;
    for (const Term& term : terms) {
        if (Samples(term.value, samples)) {
            texture_terms.push_back(&term);
        }
    }
    const u32 other_terms = u32(terms.size() - texture_terms.size());
    if (texture_terms.empty()) {
        return Result(Verdict::NotTexture, Detail::None);
    }
    std::ranges::sort(samples);
    samples.erase(std::ranges::unique(samples).begin(), samples.end());
    if (texture_terms.size() > 1) {
        // Several samples (a second texture's dither or noise term too): several textures. All
        // on one sample: the first term that is no alpha test says why, else two alpha tests.
        if (samples.size() > 1) {
            return Result(Verdict::SeveralTextures, Detail::None);
        }
        for (const Term* term : texture_terms) {
            Detail detail = Detail::None;
            if (!Compare(*term, detail)) {
                return Result(Verdict::Other, detail);
            }
        }
        return Result(Verdict::Other, Detail::TwoTests);
    }
    const auto test = Compare(*texture_terms[0], why);
    if (!test) {
        return why == Detail::SeveralTextures ? Result(Verdict::SeveralTextures, Detail::None)
                                              : Result(Verdict::Other, why);
    }
    const IR::Inst& sample = *test->alpha.sample;
    if (!sample.Arg(0).IsImmediate()) {
        return Result(Verdict::Other, Detail::SampleKind);
    }
    Cutout c{
        .verdict = Verdict::Matched,
        .op = test->op,
        .ref_kind = test->ref.kind,
        .image = u8(sample.Arg(0).U32() & 0xffff),
        .sampler = u8(sample.Arg(0).U32() >> 16),
        .channel = u8(test->alpha.index),
        .ref_buffer = test->ref.buffer,
        .ref_dword = test->ref.dword,
        .ref = test->ref.a,
        .ref_scale = test->ref.b,
        .other_terms = u8(std::min(other_terms, 255u)),
        .kill_blocks = u8(std::min(kills, 255u)),
        .texel_offset = sample.Flags<IR::TextureInstInfo>().has_offset != 0,
    };
    ReadTsharp(program.info, c);
    // The coordinates: (u, v) or (u, v, layer) of the sample, each an input's component.
    const IR::Inst* body = sample.Arg(1).TryInst();
    const bool layered = Is(body, IR::Opcode::CompositeConstructF32x3);
    if (!Is(body, IR::Opcode::CompositeConstructF32x2) && !layered) {
        c.verdict = Verdict::UvNotInput;
        c.detail = Detail::UvComputed;
        return c;
    }
    Walker walker{true};
    const auto u = walker.Eval(body->Arg(0), 0);
    const auto v = walker.Eval(body->Arg(1), 0);
    if (!u || !v || u->var != Var::Input || v->var != Var::Input || u->index != v->index) {
        c.verdict = Verdict::UvNotInput;
        c.detail = walker.why != Detail::None                     ? walker.why
                   : u && v && u->var == v->var && u->var == Var::Input ? Detail::UvTwoInputs
                                                                       : Detail::UvComputed;
        return c;
    }
    c.input = u8(u->index);
    c.comp_u = u8(u->comp);
    c.comp_v = u8(v->comp);
    c.uv_by_constant =
        u->scale.b != 0.0f || u->offset.b != 0.0f || v->scale.b != 0.0f || v->offset.b != 0.0f;
    c.uv_scale = {u->scale.a, v->scale.a};
    c.uv_offset = {u->offset.a, v->offset.a};
    if (layered) {
        Walker layer_walker{true};
        const auto w = layer_walker.Eval(body->Arg(2), 0);
        if (w && w->var == Var::None && w->offset.b == 0.0f) {
            c.layer = Layer::Immediate;
            c.layer_value = w->offset.a;
        } else {
            c.layer = Layer::Other;
        }
    }
    return c;
}

std::string CutoutLine(const Info& info, const RuntimeInfo& runtime_info) {
    const Cutout& c = info.cutout;
    char line[200];
    int n = std::snprintf(line, sizeof(line), "Cut-out pixel shader %016llx (r50): %s",
                          static_cast<unsigned long long>(info.pgm_hash),
                          VerdictNames[size_t(c.verdict)]);
    const auto put = [&](const char* format, auto... args) {
        if (n >= 0 && size_t(n) < sizeof(line)) {
            n += std::snprintf(line + n, sizeof(line) - n, format, args...);
        }
    };
    if (c.detail != Detail::None) {
        put(" (%s)", DetailNames[size_t(c.detail)]);
    }
    if (c.verdict == Verdict::Matched || c.verdict == Verdict::UvNotInput) {
        const char* xyzw = "xyzw";
        put(", image %u", c.image);
        const bool flat = c.image < info.images.size() &&
                          info.images[c.image].sharp_fetch.offsets[0] != UNKNOWN_LOCATION;
        if (flat || c.stored != 0xff) {
            put("%s", " (");
            if (flat) {
                put("T# flat %u%s", info.images[c.image].sharp_fetch.offsets[0],
                    c.stored != 0xff ? "; " : "");
            }
            if (c.stored != 0xff) {
                put(".%c reads %c, format %u", xyzw[c.channel & 3], Swizzle(c.stored),
                    c.data_format);
            }
            put("%s", ")");
        }
        put(" sampler %u, .%c %s ", c.sampler, xyzw[c.channel & 3], OpNames[size_t(c.op)]);
        if (c.ref_kind == Ref::Immediate) {
            put("%.4g", double(c.ref));
        } else {
            if (c.ref != 0.0f || c.ref_scale != 1.0f) {
                put("%.4g%+.4g*", double(c.ref), double(c.ref_scale));
            }
            if (c.ref_kind == Ref::UserData) {
                put("s%u", c.ref_dword);
            } else if (c.ref_kind == Ref::FlatUserData) {
                put("flat%u", c.ref_dword);
            } else {
                put("cb%u[%u]", c.ref_buffer, c.ref_dword);
            }
        }
        if (c.verdict == Verdict::Matched) {
            put(", uv in%u.%c%c", c.input, xyzw[c.comp_u & 3], xyzw[c.comp_v & 3]);
            const auto& fs = runtime_info.hw.fs;
            if (c.input < fs.num_inputs) {
                put(" (vs out %u)", fs.inputs[c.input].param_index);
            }
            if (c.uv_scale != std::array{1.0f, 1.0f} || c.uv_offset != std::array{0.0f, 0.0f}) {
                put(" *(%.3g,%.3g)+(%.3g,%.3g)", double(c.uv_scale[0]), double(c.uv_scale[1]),
                    double(c.uv_offset[0]), double(c.uv_offset[1]));
            }
            if (c.uv_by_constant) {
                put(" %s", "+memory");
            }
            if (c.layer == Layer::Immediate) {
                put(" layer %.3g", double(c.layer_value));
            } else if (c.layer == Layer::Other) {
                put(" %s", "layer computed");
            }
            if (c.texel_offset) {
                put(" %s", "+texel offset");
            }
        }
    }
    if (c.other_terms != 0) {
        put(", %u other terms", c.other_terms);
    }
    if (c.kill_blocks != 0) {
        put(", %u kill branches", c.kill_blocks);
    }
    return std::string(line, std::min(size_t(std::max(n, 0)), sizeof(line) - 1));
}

void CutoutAnalysisPass(IR::Program& program, const RuntimeInfo& runtime_info) {
    Info& info = program.info;
    info.cutout = AnalyzeCutout(program, runtime_info);
    std::scoped_lock lock{counts_mutex};
    if (!analysed_shaders.emplace(info.pgm_hash, info.cutout).second) {
        return;
    }
    const Cutout& c = info.cutout;
    ++counts.analysed;
    ++counts.verdicts[size_t(c.verdict)];
    ++counts.details[size_t(c.detail)];
    if (c.verdict == Verdict::Matched) {
        counts.channel_w += c.channel == 3 ? 1 : 0;
        counts.ref_immediate += c.ref_kind == Ref::Immediate ? 1 : 0;
        counts.uv_plain += !c.uv_by_constant && c.uv_scale == std::array{1.0f, 1.0f} &&
                                   c.uv_offset == std::array{0.0f, 0.0f}
                               ? 1
                               : 0;
        counts.with_terms += c.other_terms != 0 ? 1 : 0;
        counts.with_kills += c.kill_blocks != 0 ? 1 : 0;
        counts.not_repeatable += c.Repeatable() ? 0 : 1;
        counts.uv_memory += c.uv_by_constant ? 1 : 0;
        counts.layer_other += c.layer == Layer::Other ? 1 : 0;
        counts.texel_offset += c.texel_offset ? 1 : 0;
    }
    std::printf("%s\n", CutoutLine(info, runtime_info).c_str());
}

void NoteCutoutCacheRefusal() {
    cache_refusals.fetch_add(1, std::memory_order_relaxed);
}

void NoteCutoutCard(u64 camera_ps, u64 sun_ps, CutoutCardClass card_class) {
    const u8 bit = u8(1u << u32(card_class));
    std::scoped_lock lock{counts_mutex};
    if (camera_ps != 0) {
        card_shaders[camera_ps].camera |= bit;
    }
    if (sun_ps != 0) {
        card_shaders[sun_ps].sun |= bit;
    }
}

std::string CutoutSummaryText() {
    std::string text;
    if (!CutoutAnalysisOn()) {
        return text;
    }
    std::scoped_lock lock{counts_mutex};
    if (counts.analysed == 0) {
        return text;
    }
    const auto& v = counts.verdicts;
    const u32 discarding = counts.analysed - v[size_t(Verdict::NoDiscard)];
    Append(text,
           "Ray tracing cut-out shaders (r50, BB_RT_CARD_ALPHA_LOG=1): %u pixel shaders compiled in "
           "play and analysed (%u since the last line; %u discarding cache records were left to "
           "compile in play, pixel shaders without a discard taken from the cache are not "
           "counted), %u without a discard; of the %u that discard %u match the alpha test",
           counts.analysed, counts.analysed - counts.at_last_line,
           cache_refusals.load(std::memory_order_relaxed), v[size_t(Verdict::NoDiscard)],
           discarding, v[size_t(Verdict::Matched)]);
    Append(text,
           " (%u on view channel w, %u with an immediate reference, %u sampled at an input as it "
           "is, %u with other terms beside it, %u with a kill branch; %u not repeatable from the "
           "record alone: %u a coordinate scale or offset from memory, %u a computed layer, %u a "
           "texel offset)",
           counts.channel_w, counts.ref_immediate, counts.uv_plain, counts.with_terms,
           counts.with_kills, counts.not_repeatable, counts.uv_memory, counts.layer_other,
           counts.texel_offset);
    Append(text,
           "; not matched: %u not from a texture, %u coordinates not an input, %u several "
           "textures, %u other; why:",
           v[size_t(Verdict::NotTexture)], v[size_t(Verdict::UvNotInput)],
           v[size_t(Verdict::SeveralTextures)], v[size_t(Verdict::Other)]);
    bool any = false;
    for (size_t d = 1; d < DetailNames.size(); ++d) {
        if (counts.details[d] != 0) {
            Append(text, "%s %s %u", any ? "," : "", DetailNames[d], counts.details[d]);
            any = true;
        }
    }
    if (!any) {
        text += " none";
    }
    counts.at_last_line = counts.analysed;
    return text;
}

std::string CutoutCardsText() {
    std::string text;
    if (!CutoutAnalysisOn()) {
        return text;
    }
    std::scoped_lock lock{counts_mutex};
    if (card_shaders.empty()) {
        return text;
    }
    Append(text,
           "Ray tracing cut-out cards' pixel shaders (r50, BB_RT_CARD_ALPHA_LOG=1): the distinct "
           "pixel shaders of the scene's cut-out instances so far, by the r46 rule's class (a "
           "shader counts in each class it was seen in)");
    const size_t classes = size_t(CutoutCardClass::Count);
    std::vector<std::pair<u64, u8>> unmatched; // camera pass, by class (plants first)
    for (const bool sun : {false, true}) {
        Append(text, "; %s:", sun ? "sun shadow pass draws that sample a texture"
                                  : "camera pass draws that discard");
        for (size_t k = 0; k < classes; ++k) {
            std::array<u32, VerdictNames.size()> mix{};
            u32 total = 0, repeatable = 0;
            for (const auto& [hash, shader] : card_shaders) {
                if (((sun ? shader.sun : shader.camera) & (1u << k)) == 0) {
                    continue;
                }
                const auto found = analysed_shaders.find(hash);
                const Cutout c = found != analysed_shaders.end() ? found->second : Cutout{};
                ++total;
                ++mix[size_t(c.verdict)];
                repeatable += c.Repeatable() ? 1 : 0;
                if (!sun && c.verdict != Verdict::Matched && unmatched.size() < 64) {
                    unmatched.push_back({hash, u8(k)});
                }
            }
            Append(text, "%s %s %u", k ? "," : "", ClassNames[k], total);
            if (total == 0) {
                continue;
            }
            text += " [";
            bool first = true;
            for (size_t verdict = 0; verdict < mix.size(); ++verdict) {
                if (mix[verdict] != 0) {
                    Append(text, "%s%u %s", first ? "" : ", ", mix[verdict], VerdictShort[verdict]);
                    first = false;
                }
            }
            Append(text, "; %u repeatable]", repeatable);
        }
    }
    std::ranges::sort(unmatched, [](const auto& x, const auto& y) {
        return x.second != y.second ? x.second < y.second : x.first < y.first;
    });
    if (!unmatched.empty()) {
        text += "; camera pass shaders not matched:";
        for (size_t i = 0; i < unmatched.size() && i < 8; ++i) {
            const auto found = analysed_shaders.find(unmatched[i].first);
            const Cutout c = found != analysed_shaders.end() ? found->second : Cutout{};
            Append(text, " %016llx (%s; %s%s%s)",
                   static_cast<unsigned long long>(unmatched[i].first),
                   ClassShort[unmatched[i].second],
                   VerdictShort[size_t(c.verdict)], c.detail != Detail::None ? ": " : "",
                   DetailNames[size_t(c.detail)]);
        }
    }
    return text;
}

void PrintCutoutSummary() {
    if (!CutoutAnalysisOn()) {
        return;
    }
    for (const std::string& text : {CutoutSummaryText(), CutoutCardsText()}) {
        if (!text.empty()) {
            std::printf("%s\n", text.c_str());
        }
    }
}

} // namespace Shader::Optimization
""", r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r50_leaf-stage1, r50b_leaf-matcher): the cut-out analysis (cutout_analysis.h). It runs
// after CollectShaderInfoPass, on the program as it goes to SPIR-V, and reads:
//  - the discards: DiscardCond(LogicalNot(exec)) of an export with vm (export.cpp), where exec is
//    the LogicalAnd of the v_cmpx compares (vector_alu.cpp) or of the s_andn2 masks folded into
//    LogicalAnd/LogicalNot (InverseBallotEliminationPass); several discards, phis whose operands
//    agree, and the clip distance discards of InjectClipDistanceAttributes (left out);
//  - where each discard sits in the structured program (syntax_list): every branch over it, and
//    every branch an early return left behind, must be one the alpha test decides (an exec scope
//    of the v_cmpx, an execz skip: its condition made of the discard's own terms), else the test
//    does not hold on every way through (a uniform switch, a discard in an if); an unconditional
//    Discard is a kill only where every pixel reaching it fails a term (the execz kill block);
//  - the terms that keep the pixel: their conjunction, each a float compare (ordered or not);
//  - each side of the compare as one variable times a factor plus an offset, through FPAdd,
//    FPSub, FPMul, FPFma, FPNeg, bit casts and V_MUL_LEGACY's zero select (only that select: its
//    condition the product's own factors equal to zero): the variable a channel of
//    ImageSampleImplicitLod/ExplicitLod/ImageGradient, the constants immediates or (r50b) up to
//    two dwords of user data, of the flat user data (ReadConst) or of a constant buffer
//    (ReadConstBuffer at an immediate dword: V_MAD/V_MAC are FPAdd(FPMul), the V#'s alignment
//    offset is added only when SPIR-V is emitted). "alpha - ref >= 0" is "alpha >= ref";
//  - FPSaturate and FPClamp(0, 1) (r50b, narrowed): of an immediate, folded; as the outermost
//    operation of the texel side (the channel times immediates plus constants, no input factor),
//    passed only where the compare's other side is an immediate r for which the clamp does not
//    change the test (r in (0, 1] for >= and <, [0, 1) for > and <=, (0, 1) for == and !=);
//    anything else: "clamped" (coordinates: computed);
//  - (r50b) the alpha times one input component, once (an input read as GetAttribute(ParamN, c)
//    whose interpolation is smooth, or the manual interpolation below);
//  - (r50b) a dither: a channel of a second sample, added to the compare only linearly (times an
//    immediate or one dword), sampled at a screen position: u the x and v the y of one input
//    over its own w (FPRecip32 of the w times the x or y, or FPDiv32 by it; GetAttribute or
//    interpolated by hand), or u and v FragCoord's x and y, times immediates or dwords; a T# of
//    the sample that the compiling draw's user data hold must be at most 64x64. Its channel is
//    taken as 0, the game's sun shadow pass form. A second main term that reads it makes two
//    main terms (several textures); a nonzero term that reads it is refused (NonzeroFactors);
//  - (r50b) a term that keeps the pixel only where a product is not 0 (P == 0 kept when false),
//    one factor the alpha itself, the others reading no texture (ignored and recorded by kind:
//    a buffer load such as the game's per-instance fade, dwords, an input, computed);
//  - the sample's coordinates the same way, the variable an input: GetAttribute(ParamN, c) of a
//    smooth input (r50b: not a per-vertex read, which is vertex 0's value, nor a flat or
//    no-perspective one), or GCN's two manual interpolation steps that HardwareInterpolationPass
//    left in place (FPFma(P2 - P0, J, FPFma(P1 - P0, I, P0)) with I and J
//    GetAttribute(BaryCoordSmooth*, 0 and 1); no-perspective barycentrics only for a dither's
//    screen position); (r50b) a scale or offset that is one named dword is recorded.
// Every Walker is bounded (depth 32, 4096 instructions visited) and remembers what it evaluated,
// so an expression that reuses a value costs once. NonzeroFactors has no memo: it recurses at
// most 8 products deep with a new bounded Walker per level (at most 511 walks per nonzero term).

#include "shader_recompiler/ir/passes/cutout_analysis.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <numeric>
#include <optional>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "shader_recompiler/ir/basic_block.h"
#include "shader_recompiler/ir/program.h"

namespace Shader::Optimization {
namespace {

using Cutout = Info::Cutout;
using Verdict = Cutout::Verdict;
using Detail = Cutout::Detail;
using Op = Cutout::Op;
using Ref = Cutout::Ref;
using Layer = Cutout::Layer;

constexpr u32 MaxDepth = 32;
constexpr size_t MaxVisits = 4096;

bool Is(const IR::Inst* inst, IR::Opcode opcode) {
    return inst && inst->GetOpcode() == opcode;
}

bool ImmF32(const IR::Value& value, f32 x) {
    return value.IsImmediate() && value.Type() == IR::Type::F32 && value.F32() == x;
}

/// a + b * d + b2 * d2: an immediate plus up to two dwords in memory, each read as a float (r50b:
/// two; r50 had one). A slot whose coefficient is 0 is unused (kind Immediate), and the second is
/// used only beside the first.
struct Scalar {
    f32 a = 0.0f;
    f32 b = 0.0f;
    Ref kind = Ref::Immediate;
    u8 buffer = 0;
    u16 dword = 0;
    f32 b2 = 0.0f;
    Ref kind2 = Ref::Immediate;
    u8 buffer2 = 0;
    u16 dword2 = 0;

    bool Memory() const {
        return b != 0.0f || b2 != 0.0f;
    }
    bool Zero() const {
        return a == 0.0f && !Memory();
    }
};

Scalar Plain(Scalar x) {
    if (x.b2 == 0.0f) {
        x.kind2 = Ref::Immediate;
        x.buffer2 = 0;
        x.dword2 = 0;
    }
    if (x.b == 0.0f) {
        x.b = x.b2;
        x.kind = x.kind2;
        x.buffer = x.buffer2;
        x.dword = x.dword2;
        x.b2 = 0.0f;
        x.kind2 = Ref::Immediate;
        x.buffer2 = 0;
        x.dword2 = 0;
    }
    if (x.b == 0.0f) {
        x.kind = Ref::Immediate;
        x.buffer = 0;
        x.dword = 0;
    }
    return x;
}

Scalar Neg(Scalar x) {
    x.a = -x.a;
    x.b = -x.b;
    x.b2 = -x.b2;
    return Plain(x);
}

/// x / s (s not 0).
Scalar Divide(Scalar x, f32 s) {
    x.a /= s;
    x.b /= s;
    x.b2 /= s;
    return Plain(x);
}

/// x + y, or none with more than two distinct dwords.
std::optional<Scalar> AddScalars(Scalar x, const Scalar& y) {
    x.a += y.a;
    const auto put = [&x](f32 b, Ref kind, u8 buffer, u16 dword) {
        if (b == 0.0f) {
            return true;
        }
        if (x.b != 0.0f && x.kind == kind && x.buffer == buffer && x.dword == dword) {
            x.b += b;
            return true;
        }
        if (x.b2 != 0.0f && x.kind2 == kind && x.buffer2 == buffer && x.dword2 == dword) {
            x.b2 += b;
            return true;
        }
        if (x.b == 0.0f) {
            x.b = b;
            x.kind = kind;
            x.buffer = buffer;
            x.dword = dword;
            return true;
        }
        if (x.b2 == 0.0f) {
            x.b2 = b;
            x.kind2 = kind;
            x.buffer2 = buffer;
            x.dword2 = dword;
            return true;
        }
        return false;
    };
    if (!put(y.b, y.kind, y.buffer, y.dword) || !put(y.b2, y.kind2, y.buffer2, y.dword2)) {
        return std::nullopt;
    }
    return Plain(x);
}

/// x * y, or none when both read memory.
std::optional<Scalar> MulScalars(const Scalar& x, const Scalar& y) {
    if (x.Memory() && y.Memory()) {
        return std::nullopt;
    }
    const Scalar& named = x.Memory() ? x : y;
    const f32 k = x.Memory() ? y.a : x.a;
    Scalar r = named;
    r.a = x.a * y.a;
    r.b = named.b * k;
    r.b2 = named.b2 * k;
    return Plain(r);
}

/// Texel: a channel of an image sample; Input: an input component; InvW, Screen (r50b, the
/// dither's coordinates only): 1 / an input's w, and an input's x or y times that (or FragCoord's
/// x or y, index FragCoordIndex).
enum class Var : u8 { None, Texel, Input, InvW, Screen };

constexpr u32 FragCoordIndex = 0xff;

/// variable * scale + offset (+ dither * a channel of dither_sample, r50b). Texel: `index` is the
/// channel of `sample`; Input, InvW, Screen: the parameter, `comp` its component.
struct Linear {
    Var var = Var::None;
    const IR::Inst* sample = nullptr;
    u32 index = 0;
    u32 comp = 0;
    Scalar scale{.a = 1.0f};
    Scalar offset{};
    /// (r50b) Texel: times this input's component
    bool factor = false;
    u32 factor_input = 0;
    u32 factor_comp = 0;
    /// (r50b) plus dither * channel dither_index of dither_sample (none: nullptr)
    Scalar dither{};
    const IR::Inst* dither_sample = nullptr;
    u32 dither_index = 0;
    /// (r50b) Texel: under a saturate or clamp(0, 1) as its outermost operation (Compare checks
    /// that the clamp does not change the test)
    bool clamped = false;
};

/// V_MUL_LEGACY_F32 (vector_alu.cpp): Select(FPEqual(a, 0) || FPEqual(b, 0), 0, a * b), with the
/// compare of an immediate factor folded away: the product, 0 where a factor is 0. Any other
/// zeroing select (V_CNDMASK_B32 of a fade, a flag, a distance) is not one.
bool LegacyProduct(const IR::Inst& select) {
    const IR::Inst* mul = select.Arg(2).TryInst();
    if (!Is(mul, IR::Opcode::FPMul32)) {
        return false;
    }
    std::array<bool, 2> covered{};
    std::vector<IR::Value> stack{select.Arg(0)};
    while (!stack.empty()) {
        const IR::Value value = stack.back();
        stack.pop_back();
        if (value.IsImmediate()) {
            if (value.Type() == IR::Type::U1 && !value.U1()) {
                continue; // a leaf folded to false
            }
            return false;
        }
        const IR::Inst* inst = value.Inst();
        if (Is(inst, IR::Opcode::LogicalOr)) {
            if (stack.size() > 4) {
                return false;
            }
            stack.push_back(inst->Arg(0));
            stack.push_back(inst->Arg(1));
            continue;
        }
        if (!Is(inst, IR::Opcode::FPOrdEqual32) && !Is(inst, IR::Opcode::FPUnordEqual32)) {
            return false;
        }
        const IR::Value other = ImmF32(inst->Arg(1), 0.0f)   ? inst->Arg(0)
                                : ImmF32(inst->Arg(0), 0.0f) ? inst->Arg(1)
                                                             : IR::Value{};
        bool factor = false;
        for (u32 i = 0; i < 2; ++i) {
            if (!other.IsEmpty() && mul->Arg(i) == other) {
                covered[i] = true;
                factor = true;
            }
        }
        if (!factor) {
            return false;
        }
    }
    for (u32 i = 0; i < 2; ++i) {
        const IR::Value factor = mul->Arg(i);
        if (!covered[i] && !(factor.IsImmediate() && factor.Type() == IR::Type::F32 &&
                             factor.F32() != 0.0f)) {
            return false;
        }
    }
    return true;
}

using Samples_ = std::vector<const IR::Inst*>;

/// Test: a side of the alpha test (the dither samples taken as dithers); Uv: a sample's
/// coordinate; Screen (r50b): a coordinate as one input's perspective divide.
enum class Mode : u8 { Test, Uv, Screen };

class Walker {
public:
    /// info: the program's (fs_interpolation: how each input is interpolated); null for none.
    explicit Walker(Mode mode_, const Info* info_, const Samples_* dithers_ = nullptr)
        : mode{mode_}, info{info_}, dithers{dithers_} {}

    Detail why = Detail::None;

    std::optional<Linear> Eval(const IR::Value& value, u32 depth) {
        if (value.IsImmediate()) {
            if (value.Type() == IR::Type::F32) {
                return Linear{.offset = {.a = value.F32()}};
            }
            if (value.Type() == IR::Type::U32) {
                return Linear{.offset = {.a = std::bit_cast<f32>(value.U32())}};
            }
            return Fail(Detail::Computed);
        }
        if (depth > MaxDepth) {
            return Fail(Computed());
        }
        const IR::Inst* inst = value.Inst();
        if (const auto known = memo.find(inst); known != memo.end()) {
            return known->second;
        }
        if (++visits > MaxVisits) {
            return Fail(Computed());
        }
        const std::optional<Linear> result = Visit(*inst, depth);
        memo.emplace(inst, result);
        return result;
    }

    /// GCN's two interpolation steps on one component of an input, P0 + I (P1 - P0) +
    /// J (P2 - P0) (vector_interpolation.cpp), where HardwareInterpolationPass kept them. (r50b) I
    /// and J perspective-correct barycentrics (BaryCoordSmooth, its centroid or sample form); in
    /// Screen mode also the no-perspective ones (a dither's position, taken as 0 anyway).
    std::optional<Linear> Interpolated(const IR::Inst& fma2) const {
        const IR::Inst* sub2 = fma2.Arg(0).TryInst();
        const IR::Inst* j = fma2.Arg(1).TryInst();
        const IR::Inst* fma1 = fma2.Arg(2).TryInst();
        if (!Is(sub2, IR::Opcode::FPSub32) || !Is(j, IR::Opcode::GetAttribute) ||
            !Is(fma1, IR::Opcode::FPFma32)) {
            return std::nullopt;
        }
        const IR::Inst* sub1 = fma1->Arg(0).TryInst();
        const IR::Inst* i = fma1->Arg(1).TryInst();
        const IR::Inst* p0 = fma1->Arg(2).TryInst();
        if (!Is(sub1, IR::Opcode::FPSub32) || !Is(i, IR::Opcode::GetAttribute) ||
            !Is(p0, IR::Opcode::GetAttribute)) {
            return std::nullopt;
        }
        const IR::Attribute param = p0->Arg(0).Attribute();
        const u32 comp = p0->Arg(1).U32();
        const auto read = [&](const IR::Value& value, u32 index) {
            const IR::Inst* r = value.TryInst();
            return Is(r, IR::Opcode::GetAttribute) && r->Arg(0).Attribute() == param &&
                   r->Arg(1).U32() == comp && r->Arg(2).U32() == index;
        };
        const IR::Attribute bary = i->Arg(0).Attribute();
        const bool smooth = bary == IR::Attribute::BaryCoordSmooth ||
                            bary == IR::Attribute::BaryCoordSmoothCentroid ||
                            bary == IR::Attribute::BaryCoordSmoothSample;
        const bool linear = bary == IR::Attribute::BaryCoordNoPersp ||
                            bary == IR::Attribute::BaryCoordNoPerspCentroid ||
                            bary == IR::Attribute::BaryCoordNoPerspSample;
        if (!IR::IsParam(param) || p0->Arg(2).U32() != 0 || !read(sub1->Arg(0), 1) ||
            !read(sub1->Arg(1), 0) || !read(sub2->Arg(0), 2) || !read(sub2->Arg(1), 0) ||
            !(smooth || (linear && mode == Mode::Screen)) || j->Arg(0).Attribute() != bary ||
            i->Arg(1).U32() != 0 || j->Arg(1).U32() != 1) {
            return std::nullopt;
        }
        return Linear{.var = Var::Input, .index = u32(param) - u32(IR::Attribute::Param0),
                      .comp = comp};
    }

private:
    Mode mode;
    const Info* info;
    const Samples_* dithers;
    size_t visits = 0;
    std::unordered_map<const IR::Inst*, std::optional<Linear>> memo;

    /// (r50b) Whether GetAttribute(ParamN, c) (vertex index 0) is the input's value at the pixel:
    /// not for a per-vertex input (vertex 0's value, V_INTERP_MOV_F32 with barycentrics) nor a
    /// flat one; no-perspective only for a dither's position (Screen mode). An Info without the
    /// interpolation recorded (None, a program built by hand) is taken as smooth.
    bool AtPixel(u32 param) const {
        if (!info || param >= info->fs_interpolation.size()) {
            return true;
        }
        switch (info->fs_interpolation[param].primary) {
        case Qualifier::None:
        case Qualifier::Smooth:
            return true;
        case Qualifier::NoPerspective:
            return mode == Mode::Screen;
        default:
            return false;
        }
    }

    std::optional<Linear> Visit(const IR::Inst& inst, u32 depth) {
        switch (inst.GetOpcode()) {
        case IR::Opcode::BitCastF32U32:
        case IR::Opcode::BitCastU32F32:
            return Eval(inst.Arg(0), depth + 1);
        case IR::Opcode::FPSaturate32:
            return Clamped(Eval(inst.Arg(0), depth + 1));
        case IR::Opcode::FPClamp32:
            if (ImmF32(inst.Arg(1), 0.0f) && ImmF32(inst.Arg(2), 1.0f)) {
                return Clamped(Eval(inst.Arg(0), depth + 1));
            }
            return Fail(Computed());
        case IR::Opcode::SelectF32:
            if (ImmF32(inst.Arg(1), 0.0f) && LegacyProduct(inst)) {
                return Eval(inst.Arg(2), depth + 1);
            }
            return Fail(Computed());
        case IR::Opcode::GetUserData:
            return Named(Ref::UserData, 0, u32(inst.Arg(0).ScalarReg()));
        case IR::Opcode::ReadConst:
            if (inst.Flags<u32>() != 0) {
                return Named(Ref::FlatUserData, 0, inst.Flags<u32>());
            }
            return Fail(Detail::RefComputed);
        case IR::Opcode::ReadConstBuffer:
            if (inst.Arg(0).IsImmediate() && inst.Arg(1).IsImmediate()) {
                return Named(Ref::ConstBuffer, inst.Arg(0).U32(), inst.Arg(1).U32());
            }
            return Fail(Detail::RefComputed);
        case IR::Opcode::CompositeExtractF32x4:
            return Channel(inst);
        case IR::Opcode::GetAttribute: {
            const IR::Attribute attr = inst.Arg(0).Attribute();
            const u32 comp = inst.Arg(1).U32();
            if (IR::IsParam(attr) && inst.Arg(2).U32() == 0 &&
                AtPixel(u32(attr) - u32(IR::Attribute::Param0))) {
                return Linear{.var = Var::Input,
                              .index = u32(attr) - u32(IR::Attribute::Param0),
                              .comp = comp};
            }
            if (attr == IR::Attribute::FragCoord && mode == Mode::Screen && comp < 2) {
                // (r50b) the pixel's own position: a screen position as it is
                return Linear{.var = Var::Screen, .index = FragCoordIndex, .comp = comp};
            }
            return Fail(Computed());
        }
        case IR::Opcode::FPNeg32: {
            auto x = Eval(inst.Arg(0), depth + 1);
            if (x && x->clamped) {
                return ClampInside();
            }
            if (x) {
                x->scale = Neg(x->scale);
                x->offset = Neg(x->offset);
                x->dither = Neg(x->dither);
            }
            return x;
        }
        case IR::Opcode::FPAdd32:
        case IR::Opcode::FPSub32: {
            const auto x = Eval(inst.Arg(0), depth + 1);
            if (!x) {
                return std::nullopt;
            }
            auto y = Eval(inst.Arg(1), depth + 1);
            if (!y) {
                return std::nullopt;
            }
            if (inst.GetOpcode() == IR::Opcode::FPSub32) {
                y->scale = Neg(y->scale);
                y->offset = Neg(y->offset);
                y->dither = Neg(y->dither);
            }
            return Sum(*x, *y);
        }
        case IR::Opcode::FPMul32: {
            const auto x = Eval(inst.Arg(0), depth + 1);
            if (!x) {
                return std::nullopt;
            }
            const auto y = Eval(inst.Arg(1), depth + 1);
            if (!y) {
                return std::nullopt;
            }
            return Product(*x, *y);
        }
        case IR::Opcode::FPFma32: {
            if (auto input = Interpolated(inst)) {
                return input;
            }
            const auto x = Eval(inst.Arg(0), depth + 1);
            if (!x) {
                return std::nullopt;
            }
            const auto y = Eval(inst.Arg(1), depth + 1);
            if (!y) {
                return std::nullopt;
            }
            const auto product = Product(*x, *y);
            if (!product) {
                return std::nullopt;
            }
            const auto z = Eval(inst.Arg(2), depth + 1);
            if (!z) {
                return std::nullopt;
            }
            return Sum(*product, *z);
        }
        case IR::Opcode::FPRecip32: {
            // (r50b) V_RCP_F32 of an input's w: the dither's perspective divide
            if (mode != Mode::Screen) {
                return Fail(Computed());
            }
            const auto w = Eval(inst.Arg(0), depth + 1);
            if (!w || !PlainInput(*w) || w->comp != 3) {
                return Fail(Computed());
            }
            return Linear{.var = Var::InvW, .index = w->index, .comp = 3};
        }
        case IR::Opcode::FPDiv32: {
            if (mode != Mode::Screen) {
                return Fail(Computed());
            }
            const auto x = Eval(inst.Arg(0), depth + 1);
            const auto w = x ? Eval(inst.Arg(1), depth + 1) : std::nullopt;
            if (!x || !w || !PlainInput(*w) || w->comp != 3 || x->var != Var::Input ||
                x->index != w->index || x->comp > 1 || !x->offset.Zero()) {
                return Fail(Computed());
            }
            return Linear{.var = Var::Screen, .index = x->index, .comp = x->comp, .scale = x->scale};
        }
        case IR::Opcode::Phi:
            return Fail(Detail::ControlFlow);
        default:
            return Fail(Computed());
        }
    }

    std::nullopt_t Fail(Detail detail) {
        if (why == Detail::None) {
            why = detail;
        }
        return std::nullopt;
    }

    Detail Computed() const {
        return mode != Mode::Test ? Detail::UvComputed : Detail::Computed;
    }

    static bool PlainInput(const Linear& x) {
        return x.var == Var::Input && !x.scale.Memory() && x.scale.a == 1.0f && x.offset.Zero();
    }

    /// (r50b) Saturate and clamp(0, 1): an immediate is clamped; in Screen mode (a dither's
    /// coordinates, taken as 0) passed; in Test mode passed only over a texel side with no input
    /// factor, marked clamped (Compare checks the reference, Sum and Product refuse it); a dither
    /// through one is not linear; anything else changes what the walk would record.
    std::optional<Linear> Clamped(std::optional<Linear> x) {
        if (!x) {
            return std::nullopt;
        }
        if (x->dither_sample) {
            return Fail(Detail::SeveralTextures);
        }
        if (x->var == Var::None && !x->offset.Memory()) {
            x->offset.a = std::clamp(x->offset.a, 0.0f, 1.0f);
            return x;
        }
        if (mode == Mode::Screen) {
            return x;
        }
        if (mode == Mode::Test && x->var == Var::Texel && !x->factor) {
            x->clamped = true;
            return x;
        }
        return Fail(mode == Mode::Test ? Detail::Clamped : Detail::UvComputed);
    }

    /// (r50b) A clamped side combined with anything: the clamp no longer the outermost operation.
    std::optional<Linear> ClampInside() {
        return Fail(mode == Mode::Test ? Detail::Clamped : Detail::UvComputed);
    }

    static Linear Named(Ref kind, u32 buffer, u32 dword) {
        return Linear{.offset = {.b = 1.0f, .kind = kind, .buffer = u8(buffer), .dword = u16(dword)}};
    }

    std::optional<Linear> Channel(const IR::Inst& extract) {
        const IR::Inst* sample = extract.Arg(0).TryInst();
        if (!sample || !extract.Arg(1).IsImmediate()) {
            return Fail(Computed());
        }
        switch (sample->GetOpcode()) {
        case IR::Opcode::ImageSampleImplicitLod:
        case IR::Opcode::ImageSampleExplicitLod:
        case IR::Opcode::ImageGradient:
            if (dithers && std::ranges::find(*dithers, sample) != dithers->end()) {
                return Linear{.dither = {.a = 1.0f},
                              .dither_sample = sample,
                              .dither_index = extract.Arg(1).U32()};
            }
            return Linear{.var = Var::Texel, .sample = sample, .index = extract.Arg(1).U32()};
        case IR::Opcode::ImageSampleDrefImplicitLod:
        case IR::Opcode::ImageSampleDrefExplicitLod:
        case IR::Opcode::ImageGather:
        case IR::Opcode::ImageGatherDref:
        case IR::Opcode::ImageRead:
            return Fail(Detail::SampleKind);
        default:
            return Fail(Computed());
        }
    }

    /// Two variables in one sum or product.
    Detail Mixed(const Linear& x, const Linear& y, bool product) const {
        if (mode != Mode::Test) {
            return Detail::UvComputed;
        }
        if (x.var == Var::Texel && y.var == Var::Texel) {
            return x.sample == y.sample ? Detail::TwoChannels : Detail::SeveralTextures;
        }
        if (x.var == Var::Input && y.var == Var::Input) {
            return Detail::VaryingRef; // a value made of varyings (the alpha has no part in it)
        }
        // alpha * varying is a factor; alpha + varying moves the reference by the varying
        return product ? Detail::VaryingFactor : Detail::VaryingRef;
    }

    std::optional<Scalar> Add(const Scalar& x, const Scalar& y) {
        const auto r = AddScalars(x, y);
        if (!r) {
            return Fail(Detail::TwoConstants);
        }
        return r;
    }

    std::optional<Scalar> Mul(const Scalar& x, const Scalar& y) {
        const auto r = MulScalars(x, y);
        if (!r) {
            return Fail(Detail::TwoConstants);
        }
        return r;
    }

    std::optional<Linear> Sum(const Linear& x, const Linear& y) {
        if (x.clamped || y.clamped) {
            return ClampInside();
        }
        if (x.var != Var::None && y.var != Var::None) {
            return Fail(Mixed(x, y, false));
        }
        if (x.dither_sample && y.dither_sample &&
            (x.dither_sample != y.dither_sample || x.dither_index != y.dither_index)) {
            return Fail(Detail::SeveralTextures); // two noises
        }
        Linear r = x.var != Var::None ? x : y;
        const auto offset = Add(x.offset, y.offset);
        const auto dither = offset ? Add(x.dither, y.dither) : std::nullopt;
        if (!offset || !dither) {
            return std::nullopt;
        }
        r.offset = *offset;
        r.dither = *dither;
        const Linear& d = x.dither_sample ? x : y;
        r.dither_sample = d.dither_sample;
        r.dither_index = d.dither_index;
        return r;
    }

    std::optional<Linear> Product(const Linear& x, const Linear& y) {
        if (x.clamped || y.clamped) {
            return ClampInside();
        }
        const bool cx = x.var == Var::None && !x.dither_sample;
        const bool cy = y.var == Var::None && !y.dither_sample;
        if (!cx && !cy) {
            if (x.dither_sample || y.dither_sample) {
                return Fail(Detail::SeveralTextures); // a dither not taken linearly
            }
            if (auto r = VariableProduct(x, y)) {
                return r;
            }
            if (why != Detail::None) {
                return std::nullopt;
            }
            return Fail(Mixed(x, y, true));
        }
        Linear r = cx ? y : x;
        const Scalar& factor = cx ? x.offset : y.offset;
        const auto scale = Mul(r.scale, factor);
        const auto offset = scale ? Mul(r.offset, factor) : std::nullopt;
        const auto dither = offset ? Mul(r.dither, factor) : std::nullopt;
        if (!scale || !offset || !dither) {
            return std::nullopt;
        }
        r.scale = *scale;
        r.offset = *offset;
        r.dither = *dither;
        return r;
    }

    /// (r50b) Test: texel * an input component, once (E3). Screen: an input's x or y times 1 / its
    /// w (E1). Otherwise none, why untouched.
    std::optional<Linear> VariableProduct(const Linear& x, const Linear& y) {
        const auto pick = [&](Var var) -> const Linear* {
            return x.var == var ? &x : y.var == var ? &y : nullptr;
        };
        const Linear* input = pick(Var::Input);
        if (mode == Mode::Test) {
            const Linear* texel = pick(Var::Texel);
            if (!texel || !input || texel->factor || !texel->offset.Zero() ||
                !input->offset.Zero()) {
                return std::nullopt;
            }
            const auto scale = Mul(texel->scale, input->scale);
            if (!scale) {
                return std::nullopt;
            }
            Linear r = *texel;
            r.scale = *scale;
            r.factor = true;
            r.factor_input = input->index;
            r.factor_comp = input->comp;
            return r;
        }
        if (mode == Mode::Screen) {
            const Linear* w = pick(Var::InvW);
            if (!w || !input || input->index != w->index || input->comp > 1 ||
                !input->offset.Zero() || !w->offset.Zero()) {
                return std::nullopt;
            }
            const auto scale = Mul(input->scale, w->scale);
            if (!scale) {
                return std::nullopt;
            }
            return Linear{.var = Var::Screen, .index = input->index, .comp = input->comp,
                          .scale = *scale};
        }
        return std::nullopt;
    }
};

/// The pixel is kept only where `value` is `keep_when`.
struct Term {
    IR::Value value;
    bool keep_when;
};

bool SameTerm(const Term& x, const Term& y) {
    return x.value == y.value && x.keep_when == y.keep_when;
}

using Seen = std::unordered_set<std::uintptr_t>;

/// The terms that all hold exactly where `value` is `keep_when` (for a discard condition
/// `keep_when` false: the terms that keep the pixel); a value it does not take apart is a term
/// itself. A term that always holds adds nothing; one that never holds is a branch's discard.
void Terms(const IR::Value& value, bool keep_when, std::vector<Term>& out, Detail& why, u32 depth,
           Seen& seen) {
    if (value.IsImmediate()) {
        if (value.Type() == IR::Type::U1 && value.U1() != keep_when && why == Detail::None) {
            why = Detail::BranchDiscard;
        }
        return;
    }
    const IR::Inst* inst = value.Inst();
    if (!seen.insert(reinterpret_cast<std::uintptr_t>(inst) | (keep_when ? 1u : 0u)).second) {
        return; // walked already
    }
    if (depth < MaxDepth && seen.size() < MaxVisits) {
        switch (inst->GetOpcode()) {
        case IR::Opcode::ConditionRef:
            return Terms(inst->Arg(0), keep_when, out, why, depth + 1, seen);
        case IR::Opcode::LogicalNot:
            return Terms(inst->Arg(0), !keep_when, out, why, depth + 1, seen);
        case IR::Opcode::LogicalAnd:
        case IR::Opcode::LogicalOr:
            if (keep_when == (inst->GetOpcode() == IR::Opcode::LogicalAnd)) {
                Terms(inst->Arg(0), keep_when, out, why, depth + 1, seen);
                Terms(inst->Arg(1), keep_when, out, why, depth + 1, seen);
                return;
            }
            break;
        case IR::Opcode::Phi: {
            // One value on every way in (the phi itself aside): that value.
            IR::Value same{};
            bool one = true;
            for (size_t arg = 0; arg < inst->NumArgs(); ++arg) {
                const IR::Value in = inst->Arg(arg);
                if (in.TryInst() == inst) {
                    continue;
                }
                one = one && (same.IsEmpty() || same == in);
                same = in;
            }
            if (one && !same.IsEmpty()) {
                return Terms(same, keep_when, out, why, depth + 1, seen);
            }
            break;
        }
        default:
            break;
        }
    }
    const Term term{value, keep_when};
    if (std::ranges::none_of(out, [&](const Term& t) { return SameTerm(t, term); })) {
        out.push_back(term);
    }
}

bool IsSample(IR::Opcode opcode) {
    switch (opcode) {
    case IR::Opcode::ImageSampleRaw:
    case IR::Opcode::ImageSampleImplicitLod:
    case IR::Opcode::ImageSampleExplicitLod:
    case IR::Opcode::ImageSampleDrefImplicitLod:
    case IR::Opcode::ImageSampleDrefExplicitLod:
    case IR::Opcode::ImageGather:
    case IR::Opcode::ImageGatherDref:
    case IR::Opcode::ImageGradient:
    case IR::Opcode::ImageRead:
        return true;
    default:
        return false;
    }
}

/// Whether `value` reads a texture; the image reads whose results feed it go to `samples` (not
/// followed further back, through their coordinates). A walk cut short counts as a read of its
/// own (nullptr). Buffer loads (LoadBuffer*, a per-instance fade) are not texture reads.
bool Samples(const IR::Value& value, std::vector<const IR::Inst*>& samples) {
    std::vector<const IR::Inst*> stack;
    std::unordered_set<const IR::Inst*> seen;
    bool found = false;
    if (const IR::Inst* inst = value.TryInst()) {
        stack.push_back(inst);
    }
    while (!stack.empty()) {
        const IR::Inst* inst = stack.back();
        stack.pop_back();
        if (!seen.insert(inst).second) {
            continue;
        }
        if (seen.size() > MaxVisits) {
            samples.push_back(nullptr); // too far to follow: taken for a texture's
            return true;
        }
        if (IsSample(inst->GetOpcode())) {
            samples.push_back(inst);
            found = true;
            continue;
        }
        for (size_t arg = 0; arg < inst->NumArgs(); ++arg) {
            if (const IR::Inst* in = inst->Arg(arg).TryInst()) {
                stack.push_back(in);
            }
        }
    }
    return found;
}

/// A phi in the logic of a term (LogicalNot/And/Or): an exec value that depends on the way in.
bool ReachesPhi(const IR::Value& value) {
    std::vector<const IR::Inst*> stack;
    std::unordered_set<const IR::Inst*> seen;
    if (const IR::Inst* inst = value.TryInst()) {
        stack.push_back(inst);
    }
    while (!stack.empty() && seen.size() < MaxVisits) {
        const IR::Inst* inst = stack.back();
        stack.pop_back();
        if (!seen.insert(inst).second) {
            continue;
        }
        switch (inst->GetOpcode()) {
        case IR::Opcode::Phi:
            return true;
        case IR::Opcode::LogicalNot:
        case IR::Opcode::LogicalAnd:
        case IR::Opcode::LogicalOr:
        case IR::Opcode::ConditionRef:
            for (size_t arg = 0; arg < inst->NumArgs(); ++arg) {
                if (const IR::Inst* in = inst->Arg(arg).TryInst()) {
                    stack.push_back(in);
                }
            }
            break;
        default:
            break;
        }
    }
    return false;
}

std::optional<Op> CompareOp(IR::Opcode opcode) {
    switch (opcode) {
    case IR::Opcode::FPOrdLessThan32:
    case IR::Opcode::FPUnordLessThan32:
        return Op::Less;
    case IR::Opcode::FPOrdLessThanEqual32:
    case IR::Opcode::FPUnordLessThanEqual32:
        return Op::LessEqual;
    case IR::Opcode::FPOrdGreaterThan32:
    case IR::Opcode::FPUnordGreaterThan32:
        return Op::Greater;
    case IR::Opcode::FPOrdGreaterThanEqual32:
    case IR::Opcode::FPUnordGreaterThanEqual32:
        return Op::GreaterEqual;
    case IR::Opcode::FPOrdEqual32:
    case IR::Opcode::FPUnordEqual32:
        return Op::Equal;
    case IR::Opcode::FPOrdNotEqual32:
    case IR::Opcode::FPUnordNotEqual32:
        return Op::NotEqual;
    default:
        return std::nullopt;
    }
}

/// a < b as b > a.
Op Mirror(Op op) {
    switch (op) {
    case Op::Less:
        return Op::Greater;
    case Op::LessEqual:
        return Op::GreaterEqual;
    case Op::Greater:
        return Op::Less;
    case Op::GreaterEqual:
        return Op::LessEqual;
    default:
        return op;
    }
}

/// not (a < b) as a >= b (NaN aside).
Op Invert(Op op) {
    switch (op) {
    case Op::Less:
        return Op::GreaterEqual;
    case Op::LessEqual:
        return Op::Greater;
    case Op::Greater:
        return Op::LessEqual;
    case Op::GreaterEqual:
        return Op::Less;
    case Op::Equal:
        return Op::NotEqual;
    default:
        return Op::Equal;
    }
}

struct Test {
    Op op;
    Linear alpha;
    Scalar ref;
    /// (r50b) the dither's coefficient in the reference (nullptr sample: none)
    Scalar dither{};
    const IR::Inst* dither_sample = nullptr;
    u32 dither_index = 0;
};

/// A term as "channel <op> reference"; with `dithers`, a channel of one of those samples added
/// linearly is a dither (r50b).
/// (r50b) Whether "clamp(x, 0, 1) <op> r" is "x <op> r" for every x.
bool ClampKeeps(Op op, f32 r) {
    switch (op) {
    case Op::GreaterEqual:
    case Op::Less:
        return r > 0.0f && r <= 1.0f;
    case Op::Greater:
    case Op::LessEqual:
        return r >= 0.0f && r < 1.0f;
    default:
        return r > 0.0f && r < 1.0f;
    }
}

std::optional<Test> Compare(const Term& term, const Info* info, const Samples_& dithers,
                            Detail& why) {
    const IR::Inst* inst = term.value.TryInst();
    const std::optional<Op> op = inst ? CompareOp(inst->GetOpcode()) : std::nullopt;
    if (!op) {
        why = ReachesPhi(term.value) ? Detail::ControlFlow
              : Is(inst, IR::Opcode::LogicalAnd) || Is(inst, IR::Opcode::LogicalOr)
                  ? Detail::Disjunction
                  : Detail::NotCompare;
        return std::nullopt;
    }
    Walker walker{Mode::Test, info, &dithers};
    auto lhs = walker.Eval(inst->Arg(0), 0);
    auto rhs = lhs ? walker.Eval(inst->Arg(1), 0) : std::nullopt;
    if (lhs && rhs && lhs->var != Var::Texel && rhs->var != Var::Texel &&
        (lhs->dither_sample || rhs->dither_sample) && !dithers.empty()) {
        // a screen space texture is the test's only one: its alpha, as r50 reads it
        return Compare(term, info, {}, why);
    }
    if (!lhs || !rhs) {
        why = walker.why;
        return std::nullopt;
    }
    Test test{.op = *op, .alpha = {}, .ref = {}};
    if (rhs->var == Var::Texel) {
        std::swap(lhs, rhs);
        test.op = Mirror(test.op);
    }
    if (lhs->var != Var::Texel || rhs->var != Var::None) {
        why = rhs->var == Var::Texel
                  ? (rhs->sample == lhs->sample ? Detail::TwoChannels : Detail::SeveralTextures)
              : rhs->var == Var::Input ? Detail::VaryingRef
                                       : Detail::Computed;
        return std::nullopt;
    }
    // (r50b) clamp(texel side) <op> r: only an immediate r for which the clamp changes nothing
    if (lhs->clamped && (rhs->offset.Memory() || rhs->dither_sample || lhs->dither_sample ||
                         !ClampKeeps(test.op, rhs->offset.a))) {
        why = Detail::Clamped;
        return std::nullopt;
    }
    // channel * s + o1 + k1 D <op> o2 + k2 D: channel <op> (o2 - o1 + (k2 - k1) D) / s, mirrored
    // for a negative s.
    const f32 s = lhs->scale.a;
    if (lhs->scale.Memory() || s == 0.0f) {
        why = Detail::ConstantScale;
        return std::nullopt;
    }
    const auto ref = AddScalars(rhs->offset, Neg(lhs->offset));
    if (!ref) {
        why = Detail::TwoConstants;
        return std::nullopt;
    }
    test.ref = Divide(*ref, s);
    if (lhs->dither_sample && rhs->dither_sample &&
        (lhs->dither_sample != rhs->dither_sample || lhs->dither_index != rhs->dither_index)) {
        why = Detail::SeveralTextures;
        return std::nullopt;
    }
    const Linear& noisy = lhs->dither_sample ? *lhs : *rhs;
    if (noisy.dither_sample) {
        const auto k = AddScalars(rhs->dither, Neg(lhs->dither));
        // E1 (a): an immediate or one named dword
        if (!k || k->b2 != 0.0f || (k->a != 0.0f && k->b != 0.0f)) {
            why = Detail::SeveralTextures;
            return std::nullopt;
        }
        if (!k->Zero()) {
            test.dither = Divide(*k, s);
            test.dither_sample = noisy.dither_sample;
            test.dither_index = noisy.dither_index;
        }
    }
    test.op = s < 0.0f ? Mirror(test.op) : test.op;
    test.op = term.keep_when ? test.op : Invert(test.op);
    test.alpha = *lhs;
    return test;
}

/// The T# of an image as the compiling draw's user data hold it, if every dword
/// ImageResource::Fetch reads is known and inside the flat user data (4 of an r128 T#).
std::optional<AmdGpu::Image> CompileTsharp(const Info& info, u32 index) {
    if (index >= info.images.size()) {
        return std::nullopt;
    }
    const ImageResource& resource = info.images[index];
    const auto& fetch = resource.sharp_fetch;
    const auto flat = info.FlatUserData();
    const size_t dwords = resource.is_r128 ? 4 : fetch.offsets.size();
    u8 mask = fetch.load_mask;
    for (size_t i = 0; i < dwords; ++i) {
        const auto offset = fetch.offsets[i];
        if (offset == UNKNOWN_LOCATION || ((mask & 1) != 0 && offset >= flat.size())) {
            return std::nullopt;
        }
        mask >>= 1;
    }
    AmdGpu::Image image{};
    if (!resource.Fetch(flat.data(), &image) || !image.Valid()) {
        return std::nullopt;
    }
    return image;
}

/// (r50b) A dither's T# is a small noise: at most this many texels a side.
constexpr u32 DitherMaxSize = 64;

/// (r50b E1 b) A sample at a screen position: u the x and v the y of one input over its own w
/// (FPRecip32 of the w times x or y, or FPDiv32 by it), or u and v FragCoord's x and y, each
/// times immediates or dwords plus constants; and its T#, where the compiling draw's user data
/// hold it, at most DitherMaxSize a side (a screen space noise, not a projected mask).
bool ScreenSpace(const IR::Inst& sample, const Info* info) {
    switch (sample.GetOpcode()) {
    case IR::Opcode::ImageSampleImplicitLod:
    case IR::Opcode::ImageSampleExplicitLod:
    case IR::Opcode::ImageGradient:
        break;
    default:
        return false;
    }
    const IR::Inst* body = sample.Arg(1).TryInst();
    if (!Is(body, IR::Opcode::CompositeConstructF32x2)) {
        return false;
    }
    Walker walker{Mode::Screen, info};
    const auto u = walker.Eval(body->Arg(0), 0);
    const auto v = u ? walker.Eval(body->Arg(1), 0) : std::nullopt;
    if (!u || !v || u->var != Var::Screen || v->var != Var::Screen || u->index != v->index ||
        u->comp != 0 || v->comp != 1) {
        return false;
    }
    if (info && sample.Arg(0).IsImmediate()) {
        if (const auto image = CompileTsharp(*info, sample.Arg(0).U32() & 0xffff)) {
            return image->width + 1 <= DitherMaxSize && image->height + 1 <= DitherMaxSize;
        }
    }
    return true;
}

/// (r50b) A sample at an input as the r50 UV rule reads it.
bool AtInput(const IR::Inst& sample, const Info* info) {
    const IR::Inst* body = sample.Arg(1).TryInst();
    if (!Is(body, IR::Opcode::CompositeConstructF32x2) &&
        !Is(body, IR::Opcode::CompositeConstructF32x3)) {
        return false;
    }
    Walker walker{Mode::Uv, info};
    const auto u = walker.Eval(body->Arg(0), 0);
    const auto v = u ? walker.Eval(body->Arg(1), 0) : std::nullopt;
    return u && v && u->var == Var::Input && v->var == Var::Input && u->index == v->index;
}

/// (r50b E4) A term that keeps the pixel only where P is not 0 (P == 0 kept when false, or
/// P != 0 kept when true): P, else none.
std::optional<IR::Value> NonzeroSide(const Term& term) {
    const IR::Inst* inst = term.value.TryInst();
    const bool equal = Is(inst, IR::Opcode::FPOrdEqual32) || Is(inst, IR::Opcode::FPUnordEqual32);
    const bool not_equal =
        Is(inst, IR::Opcode::FPOrdNotEqual32) || Is(inst, IR::Opcode::FPUnordNotEqual32);
    if (!(equal && !term.keep_when) && !(not_equal && term.keep_when)) {
        return std::nullopt;
    }
    if (ImmF32(inst->Arg(1), 0.0f)) {
        return inst->Arg(0);
    }
    if (ImmF32(inst->Arg(0), 0.0f)) {
        return inst->Arg(1);
    }
    return std::nullopt;
}

/// (r50b E4) What an ignored factor of a nonzero term is (Cutout::Ignored*): a buffer load
/// (through bit casts and a composite extract of a vector load), an immediate or dwords, an input
/// component, or anything else.
u8 FactorKind(const IR::Value& value, const Info* info) {
    const IR::Inst* inst = value.TryInst();
    while (inst && (Is(inst, IR::Opcode::BitCastF32U32) || Is(inst, IR::Opcode::BitCastU32F32) ||
                    Is(inst, IR::Opcode::CompositeExtractU32x2) ||
                    Is(inst, IR::Opcode::CompositeExtractU32x3) ||
                    Is(inst, IR::Opcode::CompositeExtractU32x4) ||
                    Is(inst, IR::Opcode::CompositeExtractF32x2) ||
                    Is(inst, IR::Opcode::CompositeExtractF32x3) ||
                    Is(inst, IR::Opcode::CompositeExtractF32x4))) {
        inst = inst->Arg(0).TryInst();
    }
    if (inst) {
        switch (inst->GetOpcode()) {
        case IR::Opcode::LoadBufferU32:
        case IR::Opcode::LoadBufferU32x2:
        case IR::Opcode::LoadBufferU32x3:
        case IR::Opcode::LoadBufferU32x4:
        case IR::Opcode::LoadBufferF32:
        case IR::Opcode::LoadBufferF32x2:
        case IR::Opcode::LoadBufferF32x3:
        case IR::Opcode::LoadBufferF32x4:
        case IR::Opcode::LoadBufferFormatF32:
            return Cutout::IgnoredBuffer;
        default:
            break;
        }
    }
    Walker walker{Mode::Test, info};
    const auto x = walker.Eval(value, 0);
    if (x && x->var == Var::None && !x->dither_sample) {
        return Cutout::IgnoredDword;
    }
    if (x && x->var == Var::Input) {
        return Cutout::IgnoredInput;
    }
    return Cutout::IgnoredComputed;
}

/// (r50b E4) A nonzero term's product: how many factors beside the alpha, and their kinds.
struct Factors {
    u32 count = 0;
    u8 kinds = 0;
};

/// (r50b E4) P is the alpha (its sample, channel and factor input; an immediate nonzero scale, no
/// offset, no clamp), or a product with a factor that is, the other factors reading no texture
/// (Samples): those factors; else none. Recursion at most 8 products deep, a Walker per level.
std::optional<Factors> NonzeroFactors(const IR::Value& p, const Linear& alpha, const Info* info,
                                      const Samples_& dithers, u32 depth) {
    Walker walker{Mode::Test, info, &dithers};
    if (const auto x = walker.Eval(p, 0);
        x && x->var == Var::Texel && x->sample == alpha.sample && x->index == alpha.index &&
        x->factor == alpha.factor &&
        (!x->factor || (x->factor_input == alpha.factor_input && x->factor_comp == alpha.factor_comp)) &&
        !x->dither_sample && !x->clamped && !x->scale.Memory() && x->scale.a != 0.0f &&
        x->offset.Zero()) {
        return Factors{};
    }
    const IR::Inst* inst = p.IsImmediate() ? nullptr : p.TryInst();
    if (Is(inst, IR::Opcode::SelectF32) && ImmF32(inst->Arg(1), 0.0f) && LegacyProduct(*inst)) {
        inst = inst->Arg(2).TryInst(); // V_MUL_LEGACY_F32
    }
    if (depth >= 8 || !Is(inst, IR::Opcode::FPMul32)) {
        return std::nullopt;
    }
    for (u32 i = 0; i < 2; ++i) {
        std::vector<const IR::Inst*> read;
        if (Samples(inst->Arg(1 - i), read)) {
            continue;
        }
        if (auto n = NonzeroFactors(inst->Arg(i), alpha, info, dithers, depth + 1)) {
            ++n->count;
            n->kinds |= FactorKind(inst->Arg(1 - i), info);
            return n;
        }
    }
    return std::nullopt;
}

/// A DiscardCond of InjectClipDistanceAttributes: input `num_inputs - 1` below zero.
bool ClipDiscard(const IR::Inst& discard, const RuntimeInfo& runtime_info) {
    const auto& fs = runtime_info.hw.fs;
    const IR::Inst* cmp = discard.Arg(0).TryInst();
    if (!fs.clip_distance_emulation || fs.num_inputs == 0 ||
        !Is(cmp, IR::Opcode::FPOrdLessThan32) || !cmp->Arg(1).IsImmediate()) {
        return false;
    }
    const IR::Inst* read = cmp->Arg(0).TryInst();
    return Is(read, IR::Opcode::GetAttribute) &&
           read->Arg(0).Attribute() == IR::Attribute::Param0 + (fs.num_inputs - 1);
}

/// What the lanes at a point of the structured program all have: `cond` is `holds` (an If's
/// condition inside its body, false after an If whose body returned).
struct PathCond {
    IR::Value cond;
    bool holds;
};

/// A discard (inst) or an early return (inst nullptr), with the conditions on the way to it.
struct Site {
    const IR::Inst* inst;
    std::vector<PathCond> path;
    u32 loops;
};

/// The discards and returns in the order of the syntax list. Without one (a program built by
/// hand), the blocks as they are, all on the top level.
std::vector<Site> Sites(const IR::Program& program, const RuntimeInfo& runtime_info) {
    std::vector<Site> sites;
    const auto block_sites = [&](const IR::Block& block, const std::vector<PathCond>& path,
                                 u32 loops) {
        for (const IR::Inst& inst : block.Instructions()) {
            if (inst.GetOpcode() == IR::Opcode::Discard ||
                (inst.GetOpcode() == IR::Opcode::DiscardCond && !ClipDiscard(inst, runtime_info))) {
                sites.push_back({&inst, path, loops});
            }
        }
    };
    if (program.syntax_list.empty()) {
        for (const IR::Block* block : program.blocks) {
            block_sites(*block, {}, 0);
        }
        return sites;
    }
    using Type = IR::AbstractSyntaxNode::Type;
    struct Scope {
        IR::Value cond;
        size_t path_size;
        u32 loops;
        bool returned;
    };
    std::vector<Scope> scopes;
    std::vector<PathCond> path;
    u32 loops = 0;
    for (const IR::AbstractSyntaxNode& node : program.syntax_list) {
        switch (node.type) {
        case Type::Block:
            block_sites(*node.data.block, path, loops);
            break;
        case Type::If:
            scopes.push_back({node.data.if_node.cond, path.size(), loops, false});
            path.push_back({node.data.if_node.cond, true});
            break;
        case Type::EndIf:
            if (!scopes.empty()) {
                const Scope scope = scopes.back();
                scopes.pop_back();
                path.resize(scope.path_size);
                if (scope.returned) {
                    path.push_back({scope.cond, false}); // the rest of the parent's body
                }
            }
            break;
        case Type::Loop:
            ++loops;
            break;
        case Type::Repeat:
            loops -= loops != 0 ? 1 : 0;
            break;
        case Type::Return:
            if (!scopes.empty() && scopes.back().loops == loops) {
                scopes.back().returned = true;
            }
            sites.push_back({nullptr, path, loops});
            break;
        default:
            break;
        }
    }
    return sites;
}

Cutout Result(Verdict verdict, Detail detail) {
    return Cutout{.verdict = verdict, .detail = detail};
}

/// The T# of the alpha's image as the compiling draw's user data hold it: the stored channel the
/// view lane reads (the view applies dst_sel) and the format.
void ReadTsharp(const Info& info, Cutout& c) {
    if (const auto image = CompileTsharp(info, c.image)) {
        c.stored = u8(image->DstSelect().array[c.channel & 3]);
        c.data_format = u8(image->data_format);
    }
    if (c.dither) {
        if (const auto image = CompileTsharp(info, c.dither_image)) {
            c.dither_width = u16(image->width + 1);
            c.dither_height = u16(image->height + 1);
        }
    }
}

/// (r50b E5) A coordinate's scale or offset in the record: an immediate (NoDword) or exactly one
/// named dword, all of one kind and buffer; anything else leaves uv_unrecorded.
void RecordUv(Cutout& c, const Scalar& x, u16& dword, bool& first) {
    dword = Cutout::NoDword;
    if (!x.Memory()) {
        return;
    }
    if (x.b2 != 0.0f || x.b != 1.0f || x.a != 0.0f) {
        c.uv_unrecorded = true;
        return;
    }
    if (first) {
        c.uv_kind = x.kind;
        c.uv_buffer = x.buffer;
        first = false;
    } else if (c.uv_kind != x.kind || c.uv_buffer != x.buffer) {
        c.uv_unrecorded = true;
        return;
    }
    dword = x.dword;
}

/// The record of a matched alpha test.
Cutout Record(const IR::Program& program, const Test& test, u32 other_terms, u32 kills,
              bool nonzero, const Factors& ignored) {
    const IR::Inst& sample = *test.alpha.sample;
    if (!sample.Arg(0).IsImmediate() ||
        (test.dither_sample && !test.dither_sample->Arg(0).IsImmediate())) {
        return Result(Verdict::Other, Detail::SampleKind);
    }
    Cutout c{
        .verdict = Verdict::Matched,
        .op = test.op,
        .ref_kind = test.ref.kind,
        .image = u8(sample.Arg(0).U32() & 0xffff),
        .sampler = u8(sample.Arg(0).U32() >> 16),
        .channel = u8(test.alpha.index),
        .ref_buffer = test.ref.buffer,
        .ref_dword = test.ref.dword,
        .ref = test.ref.a,
        .ref_scale = test.ref.b,
        .ref2_kind = test.ref.kind2,
        .ref2_buffer = test.ref.buffer2,
        .ref2_dword = test.ref.dword2,
        .ref2_scale = test.ref.b2,
        .other_terms = u8(std::min(other_terms, 255u)),
        .kill_blocks = u8(std::min(kills, 255u)),
        .texel_offset = sample.Flags<IR::TextureInstInfo>().has_offset != 0,
        .nonzero = nonzero,
        .ignored_factor_terms = u8(std::min(ignored.count, 255u)),
        .ignored_kinds = ignored.kinds,
    };
    if (test.alpha.factor) {
        c.alpha_input = u8(test.alpha.factor_input);
        c.alpha_comp = u8(test.alpha.factor_comp);
    }
    if (test.dither_sample) {
        c.dither = true;
        c.dither_image = u8(test.dither_sample->Arg(0).U32() & 0xffff);
        c.dither_channel = u8(test.dither_index);
        if (test.dither.b != 0.0f) {
            c.dither_kind = test.dither.kind;
            c.dither_buffer = test.dither.buffer;
            c.dither_dword = test.dither.dword;
            c.dither_scale = test.dither.b;
        } else {
            c.dither_scale = test.dither.a;
        }
    }
    ReadTsharp(program.info, c);
    // The coordinates: (u, v) or (u, v, layer) of the sample, each an input's component.
    const IR::Inst* body = sample.Arg(1).TryInst();
    const bool layered = Is(body, IR::Opcode::CompositeConstructF32x3);
    if (!Is(body, IR::Opcode::CompositeConstructF32x2) && !layered) {
        c.verdict = Verdict::UvNotInput;
        c.detail = Detail::UvComputed;
        return c;
    }
    Walker walker{Mode::Uv, &program.info};
    const auto u = walker.Eval(body->Arg(0), 0);
    const auto v = walker.Eval(body->Arg(1), 0);
    if (!u || !v || u->var != Var::Input || v->var != Var::Input || u->index != v->index) {
        c.verdict = Verdict::UvNotInput;
        c.detail = walker.why != Detail::None                     ? walker.why
                   : u && v && u->var == v->var && u->var == Var::Input ? Detail::UvTwoInputs
                                                                       : Detail::UvComputed;
        return c;
    }
    c.input = u8(u->index);
    c.comp_u = u8(u->comp);
    c.comp_v = u8(v->comp);
    c.uv_by_constant =
        u->scale.Memory() || u->offset.Memory() || v->scale.Memory() || v->offset.Memory();
    c.uv_scale = {u->scale.a, v->scale.a};
    c.uv_offset = {u->offset.a, v->offset.a};
    bool first = true;
    RecordUv(c, u->scale, c.uv_scale_dword[0], first);
    RecordUv(c, v->scale, c.uv_scale_dword[1], first);
    RecordUv(c, u->offset, c.uv_offset_dword[0], first);
    RecordUv(c, v->offset, c.uv_offset_dword[1], first);
    if (layered) {
        Walker layer_walker{Mode::Uv, &program.info};
        const auto w = layer_walker.Eval(body->Arg(2), 0);
        if (w && w->var == Var::None && !w->offset.Memory()) {
            c.layer = Layer::Immediate;
            c.layer_value = w->offset.a;
        } else {
            c.layer = Layer::Other;
        }
    }
    return c;
}

/// The terms that read a texture, each with the samples it reads (sorted, once each).
struct TextureTerm {
    const Term* term;
    std::vector<const IR::Inst*> samples;
};

Cutout Analyze(const IR::Program& program, const RuntimeInfo& runtime_info) {
    const std::vector<Site> sites = Sites(program, runtime_info);
    std::vector<Term> terms;
    Detail why = Detail::None;
    Seen seen;
    size_t last_discard = 0;
    bool discards = false;
    for (size_t i = 0; i < sites.size(); ++i) {
        if (!sites[i].inst) {
            continue;
        }
        discards = true;
        last_discard = i;
        if (sites[i].inst->GetOpcode() == IR::Opcode::DiscardCond) {
            Terms(sites[i].inst->Arg(0), false, terms, why, 0, seen);
        }
    }
    if (!discards) {
        return Result(Verdict::NoDiscard, Detail::None);
    }
    // A branch the alpha test decides: the lanes it leaves out (cond not `holds`) fail a term of
    // the discards, so they die anyway (exec scope, execz skip). Kill: every lane with cond
    // `holds` fails a term (a non-empty set of them).
    const auto within = [&](const IR::Value& cond, bool holds, bool nonempty) {
        std::vector<Term> part;
        Detail local = Detail::None;
        Seen local_seen;
        Terms(cond, holds, part, local, 0, local_seen);
        return local == Detail::None && (!nonempty || !part.empty()) &&
               std::ranges::all_of(part, [&](const Term& t) {
                   return std::ranges::any_of(terms, [&](const Term& u) { return SameTerm(t, u); });
               });
    };
    const auto decided = [&](const PathCond& p) { return within(p.cond, p.holds, false); };
    const auto kill = [&](const PathCond& p) { return within(p.cond, !p.holds, true); };
    u32 kills = 0;
    for (size_t i = 0; i < sites.size() && why == Detail::None; ++i) {
        const Site& site = sites[i];
        if (!site.inst) {
            // an early return: discards after it are not reached by the lanes it takes out
            if (i < last_discard && (site.loops != 0 || !std::ranges::all_of(site.path, decided))) {
                why = Detail::ControlFlow;
            }
        } else if (site.inst->GetOpcode() == IR::Opcode::DiscardCond) {
            if (site.loops != 0 || !std::ranges::all_of(site.path, decided)) {
                why = Detail::ControlFlow;
            }
        } else if (site.loops == 0 && std::ranges::any_of(site.path, kill)) {
            ++kills;
        } else {
            why = Detail::BranchDiscard;
        }
    }
    if (why != Detail::None) {
        return Result(Verdict::Other, why);
    }
    std::vector<TextureTerm> texture_terms;
    std::vector<const IR::Inst*> samples;
    for (const Term& term : terms) {
        std::vector<const IR::Inst*> own;
        if (Samples(term.value, own)) {
            std::ranges::sort(own);
            own.erase(std::ranges::unique(own).begin(), own.end());
            samples.insert(samples.end(), own.begin(), own.end());
            texture_terms.push_back({&term, std::move(own)});
        }
    }
    const u32 other_terms = u32(terms.size() - texture_terms.size());
    if (texture_terms.empty()) {
        return Result(Verdict::NotTexture, Detail::None);
    }
    std::ranges::sort(samples);
    samples.erase(std::ranges::unique(samples).begin(), samples.end());
    const Info* info = &program.info;
    // (r50b E1 b) the samples a dither may be: at a screen position, a small T#
    Samples_ screen;
    for (const IR::Inst* sample : samples) {
        if (sample && ScreenSpace(*sample, info)) {
            screen.push_back(sample);
        }
    }
    // Several textures: which samples, by where they are sampled (r50b E7).
    const auto several = [&](Detail detail) {
        Cutout r = Result(Verdict::SeveralTextures, detail);
        u32 at_input = 0;
        for (const IR::Inst* sample : samples) {
            at_input += sample && AtInput(*sample, info) ? 1 : 0;
        }
        r.sample_count = u8(std::min<size_t>(samples.size(), 255));
        r.samples_input = u8(std::min(at_input, 255u));
        r.samples_screen = u8(std::min<size_t>(screen.size(), 255));
        return r;
    };
    // (r50b E4) the main test, and the terms that only keep a nonzero alpha
    std::vector<const TextureTerm*> mains, zeros;
    for (const TextureTerm& t : texture_terms) {
        (NonzeroSide(*t.term) ? zeros : mains).push_back(&t);
    }
    if (mains.empty()) {
        mains.swap(zeros); // "alpha != 0" alone: an alpha test as r50 reads it
    }
    if (mains.size() == 1) {
        const TextureTerm& main = *mains[0];
        Detail why_test = Detail::None;
        const auto test = Compare(*main.term, info, screen, why_test);
        if (!test) {
            if (why_test != Detail::SeveralTextures) {
                return Result(Verdict::Other, why_test);
            }
            // (r50b E1) a second texture that would be a dither but for where it is sampled
            for (const IR::Inst* sample : main.samples) {
                if (!sample || std::ranges::find(screen, sample) != screen.end()) {
                    continue;
                }
                Samples_ relaxed = screen;
                relaxed.push_back(sample);
                Detail ignored_why = Detail::None;
                const auto t = Compare(*main.term, info, relaxed, ignored_why);
                if (t && t->dither_sample == sample) {
                    return several(Detail::DitherNotScreen);
                }
            }
            return several(Detail::None);
        }
        // (r50b E1 c) the dither feeds no other term: a second main term reading it made two
        // main terms (several textures below), and a nonzero term reading it is refused here
        // (NonzeroFactors: the dither is no alpha, and a factor that reads it reads a texture).
        bool rest = false;
        Factors ignored;
        for (const TextureTerm* zero : zeros) {
            const auto n = NonzeroFactors(*NonzeroSide(*zero->term), test->alpha, info, screen, 0);
            if (!n) {
                rest = true;
                break;
            }
            ignored.count += n->count;
            ignored.kinds |= n->kinds;
        }
        if (!rest) {
            return Record(program, *test, other_terms, kills, !zeros.empty(), ignored);
        }
    }
    // Several terms read textures. Several samples (a second texture's noise term too): several
    // textures. All on one sample: the first term that is no alpha test says why, else two alpha
    // tests.
    if (samples.size() > 1) {
        return several(Detail::None);
    }
    for (const TextureTerm& t : texture_terms) {
        Detail detail = Detail::None;
        if (!Compare(*t.term, info, {}, detail)) {
            return Result(Verdict::Other, detail);
        }
    }
    return Result(Verdict::Other, Detail::TwoTests);
}

constexpr std::array VerdictNames = {"not analysed",          "match",
                                     "no discard",            "no: not from a texture",
                                     "no: uv not an input",   "no: several textures",
                                     "no: other"};
constexpr std::array VerdictShort = {"not analysed", "match",           "no discard", "not a texture",
                                     "uv not an input", "several textures", "other"};
constexpr std::array DetailNames = {
    "",                    "discard in a branch",  "through a phi or a branch",
    "an OR of tests",      "not a float compare",  "alpha with a varying",
    "ref is a varying",    "scaled from memory",   "two memory values",
    "dynamic address",     "depth/gather/load",    "computed",
    "two alpha tests",     "several textures",     "uv computed",
    "u and v two inputs",  "two channels",         "dither not a screen space noise",
    "clamped"};
static_assert(VerdictNames.size() == size_t(Verdict::Other) + 1);
static_assert(VerdictShort.size() == VerdictNames.size());
static_assert(DetailNames.size() == size_t(Detail::Count));
constexpr std::array OpNames = {"<", "<=", ">", ">=", "==", "!="};
constexpr std::array ClassNames = {
    "plants (left out of lamp rays: a skeleton, no sun shadow pass draw)",
    "left out, no skeleton", "left out, a skeleton", "kept whole: a skeleton (hair, cloth, characters)",
    "kept whole, other"};
constexpr std::array ClassShort = {"plant", "no skeleton", "skeleton, left out",
                                   "skeleton, kept", "kept"};
static_assert(ClassNames.size() == size_t(CutoutCardClass::Count));
static_assert(ClassShort.size() == ClassNames.size());
constexpr std::array ConstantsNames = {"CPU-written", "in place (a GPU write pending)",
                                       "GPU-written", "unreadable", "another permutation"};
constexpr std::array ConstantsShort = {"CPU-written", "in place", "GPU-written", "unreadable",
                                       "another permutation"};
static_assert(ConstantsNames.size() == size_t(CutoutConstants::OtherPermutation) + 1);
static_assert(ConstantsShort.size() == ConstantsNames.size());

char Swizzle(u8 stored) {
    switch (stored) {
    case 0:
        return '0';
    case 1:
        return '1';
    case 4:
        return 'r';
    case 5:
        return 'g';
    case 6:
        return 'b';
    case 7:
        return 'a';
    default:
        return '?';
    }
}

constexpr const char* Xyzw = "xyzw";

void Append(std::string& text, const char* format, ...) {
    char part[512];
    va_list args;
    va_start(args, format);
    const int n = std::vsnprintf(part, sizeof(part), format, args);
    va_end(args);
    if (n > 0) {
        text.append(part, std::min(size_t(n), sizeof(part) - 1));
    }
}

/// s4, flat9, cb1[20].
std::string DwordName(Ref kind, u8 buffer, u16 dword) {
    std::string text;
    if (kind == Ref::UserData) {
        Append(text, "s%u", dword);
    } else if (kind == Ref::FlatUserData) {
        Append(text, "flat%u", dword);
    } else if (kind == Ref::ConstBuffer) {
        Append(text, "cb%u[%u]", buffer, dword);
    }
    return text;
}

/// a + s1 * d1 + s2 * d2 as "cb1[20]+0.5*cb1[21]" (r50: "0.5", "cb2[12]", "0.1+2*s4").
std::string RefText(const Cutout& c) {
    std::string text;
    if (c.ref_kind == Ref::Immediate) {
        Append(text, "%.4g", double(c.ref));
        return text;
    }
    if (c.ref != 0.0f) {
        Append(text, "%.4g", double(c.ref));
    }
    const auto put = [&](f32 scale, Ref kind, u8 buffer, u16 dword) {
        const std::string name = DwordName(kind, buffer, dword);
        if (scale == 1.0f) {
            Append(text, "%s%s", text.empty() ? "" : "+", name.c_str());
        } else {
            Append(text, text.empty() ? "%.4g*%s" : "%+.4g*%s", double(scale), name.c_str());
        }
    };
    put(c.ref_scale, c.ref_kind, c.ref_buffer, c.ref_dword);
    if (c.ref2_kind != Ref::Immediate) {
        put(c.ref2_scale, c.ref2_kind, c.ref2_buffer, c.ref2_dword);
    }
    return text;
}

/// A coordinate scale or offset pair: "(2,2)", "cb2[0,1]", "(cb2[0],1)".
std::string PairText(const Cutout& c, const std::array<f32, 2>& value,
                     const std::array<u16, 2>& dword) {
    std::string text;
    if (dword[0] != Cutout::NoDword && dword[1] != Cutout::NoDword &&
        c.uv_kind == Ref::ConstBuffer) {
        Append(text, "cb%u[%u,%u]", c.uv_buffer, dword[0], dword[1]);
        return text;
    }
    text += "(";
    for (u32 i = 0; i < 2; ++i) {
        if (dword[i] != Cutout::NoDword) {
            text += DwordName(c.uv_kind, c.uv_buffer, dword[i]);
        } else {
            Append(text, "%.3g", double(value[i]));
        }
        text += i == 0 ? "," : ")";
    }
    return text;
}

struct Counts {
    u32 analysed = 0;
    u32 at_last_line = 0;
    std::array<u32, VerdictNames.size()> verdicts{};
    std::array<u32, DetailNames.size()> details{};
    u32 channel_w = 0;
    u32 ref_immediate = 0;
    u32 uv_plain = 0;
    u32 with_terms = 0;
    u32 with_kills = 0;
    u32 not_repeatable = 0;
    u32 uv_memory = 0;
    u32 layer_other = 0;
    u32 texel_offset = 0;
    // r50b
    u32 dithered = 0;
    u32 vertex_alpha = 0;
    u32 nonzero = 0;
    u32 two_dwords = 0;
    u32 with_constants = 0;
    u32 uv_unrecorded = 0;
    u32 ignored_varying = 0; ///< an ignored nonzero factor that is an input or computed
};

/// (r50b) The ignored factors' kinds: "a buffer load", "dwords/an input", ...
std::string KindsText(u8 kinds) {
    std::string text;
    constexpr std::array<std::pair<u8, const char*>, 4> names = {{
        {Cutout::IgnoredBuffer, "a buffer load"},
        {Cutout::IgnoredDword, "dwords"},
        {Cutout::IgnoredInput, "an input"},
        {Cutout::IgnoredComputed, "computed"},
    }};
    for (const auto& [bit, name] : names) {
        if ((kinds & bit) != 0) {
            text += text.empty() ? "" : "/";
            text += name;
        }
    }
    return text;
}

/// (r50b) The draws of a record's pixel shader by CutoutConstants, and the worst state of those
/// whose dwords were looked at (not OtherPermutation).
struct ConstantsSeen {
    std::array<u32, size_t(CutoutConstants::OtherPermutation) + 1> draws{};
    CutoutConstants worst = CutoutConstants::CpuWritten;
    bool printed = false;
};

/// A pixel shader of the scene's cut-out instances: the classes it was seen in (bit per
/// CutoutCardClass) by camera pass and sun shadow pass draws.
struct CardShader {
    u8 camera = 0;
    u8 sun = 0;
};

std::mutex counts_mutex;
Counts counts;
std::unordered_map<u64, Cutout> analysed_shaders;
std::unordered_map<u64, CardShader> card_shaders;
std::unordered_map<u64, ConstantsSeen> constants_seen; // r50b: the draws' constants
std::atomic<u32> cache_refusals{0};

} // namespace

bool CutoutAnalysisOn() {
    static const bool on = [] {
        const char* env = std::getenv("BB_RT_CARD_ALPHA_LOG");
        return env && std::strcmp(env, "1") == 0;
    }();
    return on;
}

Info::Cutout AnalyzeCutout(const IR::Program& program, const RuntimeInfo& runtime_info) {
    if (program.info.sw_stage != SwStage::Fragment) {
        return {};
    }
    Cutout c = Analyze(program, runtime_info);
    // (r50b E6) what a record found by pgm_hash must match
    c.image_count = u8(std::min<size_t>(program.info.images.size(), 255));
    c.buffer_count = u8(std::min<size_t>(program.info.buffers.size(), 255));
    const auto& fs = runtime_info.hw.fs;
    c.num_inputs = u8(std::min<u32>(fs.num_inputs, 32));
    for (u32 i = 0; i < c.num_inputs; ++i) {
        c.input_default_mask |= fs.inputs[i].is_default ? 1u << i : 0u;
        c.input_flat_mask |= fs.inputs[i].is_flat ? 1u << i : 0u;
    }
    return c;
}

bool CutoutSamePermutation(const Info::Cutout& c, u32 num_inputs, u32 default_mask,
                           u32 flat_mask) {
    const u32 used = c.num_inputs >= 32 ? ~0u : (1u << c.num_inputs) - 1;
    return num_inputs == c.num_inputs && (default_mask & used) == c.input_default_mask &&
           (flat_mask & used) == c.input_flat_mask;
}

std::string CutoutLine(const Info& info, const RuntimeInfo& runtime_info) {
    const Cutout& c = info.cutout;
    char line[512];
    int n = std::snprintf(line, sizeof(line), "Cut-out pixel shader %016llx (r50): %s",
                          static_cast<unsigned long long>(info.pgm_hash),
                          VerdictNames[size_t(c.verdict)]);
    const auto put = [&](const char* format, auto... args) {
        if (n >= 0 && size_t(n) < sizeof(line)) {
            n += std::snprintf(line + n, sizeof(line) - n, format, args...);
        }
    };
    if (c.detail != Detail::None) {
        put(" (%s)", DetailNames[size_t(c.detail)]);
    }
    if (c.verdict == Verdict::Matched && (c.dither || c.alpha_input != Cutout::NoInput || c.nonzero)) {
        // (r50b) the widened forms
        const char* sep = " (";
        if (c.dither) {
            put("%sdithered", sep);
            sep = ", ";
        }
        if (c.alpha_input != Cutout::NoInput) {
            put("%sx an input", sep);
            sep = ", ";
        }
        if (c.nonzero) {
            put("%snonzero", sep);
        }
        put("%s", ")");
    }
    if (c.verdict == Verdict::Matched || c.verdict == Verdict::UvNotInput) {
        const auto& fs = runtime_info.hw.fs;
        put(", image %u", c.image);
        const bool flat = c.image < info.images.size() &&
                          info.images[c.image].sharp_fetch.offsets[0] != UNKNOWN_LOCATION;
        if (flat || c.stored != 0xff) {
            put("%s", " (");
            if (flat) {
                put("T# flat %u%s", info.images[c.image].sharp_fetch.offsets[0],
                    c.stored != 0xff ? "; " : "");
            }
            if (c.stored != 0xff) {
                put(".%c reads %c, format %u", Xyzw[c.channel & 3], Swizzle(c.stored),
                    c.data_format);
            }
            put("%s", ")");
        }
        put(" sampler %u, .%c", c.sampler, Xyzw[c.channel & 3]);
        if (c.alpha_input != Cutout::NoInput) {
            put("*in%u.%c", c.alpha_input, Xyzw[c.alpha_comp & 3]);
            if (c.alpha_input < fs.num_inputs) {
                put(" (vs out %u)", fs.inputs[c.alpha_input].param_index);
            }
        }
        put(" %s %s", OpNames[size_t(c.op)], RefText(c).c_str());
        if (c.dither) {
            const std::string k = c.dither_dword != Cutout::NoDword
                                      ? DwordName(c.dither_kind, c.dither_buffer, c.dither_dword)
                                      : std::string{"1"};
            put(", dither %+.4g*%s*image%u.%c", double(c.dither_scale), k.c_str(), c.dither_image,
                Xyzw[c.dither_channel & 3]);
            if (c.dither_width != 0) {
                put(" (%ux%u)", c.dither_width, c.dither_height);
            }
            put("%s", " taken as 0");
        }
        if (c.verdict == Verdict::Matched) {
            put(", uv in%u.%c%c", c.input, Xyzw[c.comp_u & 3], Xyzw[c.comp_v & 3]);
            if (c.input < fs.num_inputs) {
                put(" (vs out %u)", fs.inputs[c.input].param_index);
            }
            const bool scaled = c.uv_scale_dword != std::array{Cutout::NoDword, Cutout::NoDword} ||
                                c.uv_scale != std::array{1.0f, 1.0f};
            const bool offset = c.uv_offset_dword != std::array{Cutout::NoDword, Cutout::NoDword} ||
                                c.uv_offset != std::array{0.0f, 0.0f};
            if (scaled || offset) {
                put(" *%s+%s", PairText(c, c.uv_scale, c.uv_scale_dword).c_str(),
                    PairText(c, c.uv_offset, c.uv_offset_dword).c_str());
            }
            if (c.uv_unrecorded) {
                put(" %s", "+memory");
            }
            if (c.layer == Layer::Immediate) {
                put(" layer %.3g", double(c.layer_value));
            } else if (c.layer == Layer::Other) {
                put(" %s", "layer computed");
            }
            if (c.texel_offset) {
                put(" %s", "+texel offset");
            }
        }
    }
    if (c.verdict == Verdict::SeveralTextures && c.sample_count != 0) {
        put(", %u samples: %u at an input, %u screen space, %u computed", c.sample_count,
            c.samples_input, c.samples_screen,
            u32(std::max(0, int(c.sample_count) - int(c.samples_input) - int(c.samples_screen))));
    }
    if (c.other_terms != 0) {
        put(", %u other terms", c.other_terms);
    }
    if (c.ignored_factor_terms != 0) {
        put(", %u factors of the nonzero term ignored (%s)", c.ignored_factor_terms,
            KindsText(c.ignored_kinds).c_str());
    }
    if (c.kill_blocks != 0) {
        put(", %u kill branches", c.kill_blocks);
    }
    return std::string(line, std::min(size_t(std::max(n, 0)), sizeof(line) - 1));
}

void CutoutAnalysisPass(IR::Program& program, const RuntimeInfo& runtime_info) {
    Info& info = program.info;
    // Every compile's Info, so every permutation's (r50b E6); the map and the line: the first.
    info.cutout = AnalyzeCutout(program, runtime_info);
    std::scoped_lock lock{counts_mutex};
    if (!analysed_shaders.emplace(info.pgm_hash, info.cutout).second) {
        return;
    }
    const Cutout& c = info.cutout;
    ++counts.analysed;
    ++counts.verdicts[size_t(c.verdict)];
    ++counts.details[size_t(c.detail)];
    if (c.verdict == Verdict::Matched) {
        counts.channel_w += c.channel == 3 ? 1 : 0;
        counts.ref_immediate += c.ref_kind == Ref::Immediate ? 1 : 0;
        counts.uv_plain += !c.uv_by_constant && c.uv_scale == std::array{1.0f, 1.0f} &&
                                   c.uv_offset == std::array{0.0f, 0.0f}
                               ? 1
                               : 0;
        counts.with_terms += c.other_terms != 0 ? 1 : 0;
        counts.with_kills += c.kill_blocks != 0 ? 1 : 0;
        counts.not_repeatable += c.RepeatableFromRecord() ? 0 : 1;
        counts.uv_memory += c.uv_by_constant ? 1 : 0;
        counts.layer_other += c.layer == Layer::Other ? 1 : 0;
        counts.texel_offset += c.texel_offset ? 1 : 0;
        counts.dithered += c.dither ? 1 : 0;
        counts.vertex_alpha += c.alpha_input != Cutout::NoInput ? 1 : 0;
        counts.nonzero += c.nonzero ? 1 : 0;
        counts.two_dwords += c.ref2_kind != Ref::Immediate ? 1 : 0;
        counts.with_constants += c.RepeatableWithConstants() ? 1 : 0;
        counts.uv_unrecorded += c.uv_unrecorded ? 1 : 0;
        counts.ignored_varying +=
            (c.ignored_kinds & (Cutout::IgnoredInput | Cutout::IgnoredComputed)) != 0 ? 1 : 0;
    }
    std::printf("%s\n", CutoutLine(info, runtime_info).c_str());
}

const Info::Cutout* FindCutout(u64 pgm_hash) {
    std::scoped_lock lock{counts_mutex};
    const auto found = analysed_shaders.find(pgm_hash);
    return found != analysed_shaders.end() ? &found->second : nullptr;
}

void NoteCutoutCacheRefusal() {
    cache_refusals.fetch_add(1, std::memory_order_relaxed);
}

void NoteCutoutCard(u64 camera_ps, u64 sun_ps, CutoutCardClass card_class) {
    const u8 bit = u8(1u << u32(card_class));
    std::scoped_lock lock{counts_mutex};
    if (camera_ps != 0) {
        card_shaders[camera_ps].camera |= bit;
    }
    if (sun_ps != 0) {
        card_shaders[sun_ps].sun |= bit;
    }
}

std::array<CutoutDword, 7> CutoutDwords(const Info::Cutout& c) {
    std::array<CutoutDword, 7> dwords{};
    const auto uv = [&](u16 dword) {
        return dword != Cutout::NoDword ? CutoutDword{c.uv_kind, c.uv_buffer, dword} : CutoutDword{};
    };
    dwords[0] = uv(c.uv_scale_dword[0]);
    dwords[1] = uv(c.uv_scale_dword[1]);
    dwords[2] = uv(c.uv_offset_dword[0]);
    dwords[3] = uv(c.uv_offset_dword[1]);
    dwords[4] = {c.ref_kind, c.ref_buffer, c.ref_dword};
    dwords[5] = {c.ref2_kind, c.ref2_buffer, c.ref2_dword};
    if (c.dither && c.dither_dword != Cutout::NoDword) {
        dwords[6] = {c.dither_kind, c.dither_buffer, c.dither_dword};
    }
    return dwords;
}

std::string CutoutConstantsLine(u64 pgm_hash, const Info::Cutout& c,
                                const std::array<f32, 7>& values, int uv_vs_out, int alpha_vs_out,
                                u8 stored, CutoutConstants state, std::array<u32, 2> dither_size) {
    const auto vs_out = [](int out) {
        std::string text;
        if (out < 0) {
            text = "default value";
        } else {
            Append(text, "vs out %d%s", out & 0xff, (out & CutoutFlatInput) != 0 ? ", flat" : "");
        }
        return text;
    };
    const auto value = [&](u16 dword, f32 immediate, size_t slot) {
        return double(dword != Cutout::NoDword ? values[slot] : immediate);
    };
    std::string text;
    Append(text, "Cut-out constants %016llx (r50b): uv (in%u.%c%c*(%g,%g)+(%g,%g), %s)",
           static_cast<unsigned long long>(pgm_hash), c.input, Xyzw[c.comp_u & 3],
           Xyzw[c.comp_v & 3], value(c.uv_scale_dword[0], c.uv_scale[0], 0),
           value(c.uv_scale_dword[1], c.uv_scale[1], 1),
           value(c.uv_offset_dword[0], c.uv_offset[0], 2),
           value(c.uv_offset_dword[1], c.uv_offset[1], 3), vs_out(uv_vs_out).c_str());
    // reference = ref + ref_scale * d1 + ref2_scale * d2, the dither taken as 0
    f32 ref = c.ref;
    std::string parts;
    if (c.ref != 0.0f || c.ref_kind == Ref::Immediate) {
        Append(parts, "%g", double(c.ref));
    }
    const auto put = [&](Ref kind, f32 scale, f32 v) {
        if (kind == Ref::Immediate) {
            return;
        }
        ref += scale * v;
        if (scale == 1.0f) {
            Append(parts, "%s%g", parts.empty() ? "" : " + ", double(v));
        } else {
            Append(parts, "%s%g*%g", parts.empty() ? "" : " + ", double(scale), double(v));
        }
    };
    put(c.ref_kind, c.ref_scale, values[4]);
    put(c.ref2_kind, c.ref2_scale, values[5]);
    Append(text, ", ref %s = %g", parts.c_str(), double(ref));
    if (c.dither) {
        const f32 k = c.dither_scale * (c.dither_dword != Cutout::NoDword ? values[6] : 1.0f);
        Append(text, ", camera dither %g*image%u.%c", double(k), c.dither_image,
               Xyzw[c.dither_channel & 3]);
        if (dither_size[0] != 0) {
            Append(text, " (%ux%u)", dither_size[0], dither_size[1]);
        }
        text += " (taken as 0)";
    }
    if (c.alpha_input != Cutout::NoInput) {
        Append(text, ", alpha factor in%u.%c (%s)", c.alpha_input, Xyzw[c.alpha_comp & 3],
               vs_out(alpha_vs_out).c_str());
    } else {
        text += ", no alpha factor";
    }
    Append(text, ", stored channel %c, %s", Swizzle(stored), ConstantsNames[size_t(state)]);
    return text;
}

bool NoteCutoutConstants(u64 pgm_hash, CutoutConstants state) {
    std::scoped_lock lock{counts_mutex};
    ConstantsSeen& seen = constants_seen[pgm_hash];
    ++seen.draws[size_t(state)];
    if (state == CutoutConstants::OtherPermutation) {
        return false;
    }
    if (u8(state) > u8(seen.worst)) {
        seen.worst = state;
    }
    const bool first = !seen.printed;
    seen.printed = true;
    return first;
}

std::string CutoutSummaryText() {
    std::string text;
    if (!CutoutAnalysisOn()) {
        return text;
    }
    std::scoped_lock lock{counts_mutex};
    if (counts.analysed == 0) {
        return text;
    }
    const auto& v = counts.verdicts;
    const u32 discarding = counts.analysed - v[size_t(Verdict::NoDiscard)];
    Append(text,
           "Ray tracing cut-out shaders (r50, BB_RT_CARD_ALPHA_LOG=1): %u pixel shaders compiled in "
           "play and analysed (%u since the last line; %u discarding cache records were left to "
           "compile in play, pixel shaders without a discard taken from the cache are not "
           "counted), %u without a discard; of the %u that discard %u match the alpha test",
           counts.analysed, counts.analysed - counts.at_last_line,
           cache_refusals.load(std::memory_order_relaxed), v[size_t(Verdict::NoDiscard)],
           discarding, v[size_t(Verdict::Matched)]);
    Append(text,
           " (%u on view channel w, %u with an immediate reference, %u sampled at an input as it "
           "is, %u with other terms beside it, %u with a kill branch; %u not repeatable from the "
           "record alone: %u a coordinate scale or offset from memory, %u a computed layer, %u a "
           "texel offset)",
           counts.channel_w, counts.ref_immediate, counts.uv_plain, counts.with_terms,
           counts.with_kills, counts.not_repeatable, counts.uv_memory, counts.layer_other,
           counts.texel_offset);
    Append(text,
           " (r50b: %u dithered, %u times an input, %u with a nonzero term, %u with a reference of "
           "two dwords; %u repeatable with the draw's constants, %u not, for (a shader can count "
           "in several) %u a coordinate scale or offset the record cannot name, %u a computed "
           "layer, %u a texel offset, %u other terms, %u an ignored nonzero factor that is an "
           "input or computed)",
           counts.dithered, counts.vertex_alpha, counts.nonzero, counts.two_dwords,
           counts.with_constants, v[size_t(Verdict::Matched)] - counts.with_constants,
           counts.uv_unrecorded, counts.layer_other, counts.texel_offset, counts.with_terms,
           counts.ignored_varying);
    Append(text,
           "; not matched: %u not from a texture, %u coordinates not an input, %u several "
           "textures, %u other; why:",
           v[size_t(Verdict::NotTexture)], v[size_t(Verdict::UvNotInput)],
           v[size_t(Verdict::SeveralTextures)], v[size_t(Verdict::Other)]);
    bool any = false;
    for (size_t d = 1; d < DetailNames.size(); ++d) {
        if (counts.details[d] != 0) {
            Append(text, "%s %s %u", any ? "," : "", DetailNames[d], counts.details[d]);
            any = true;
        }
    }
    if (!any) {
        text += " none";
    }
    counts.at_last_line = counts.analysed;
    return text;
}

std::string CutoutCardsText() {
    std::string text;
    if (!CutoutAnalysisOn()) {
        return text;
    }
    std::scoped_lock lock{counts_mutex};
    if (card_shaders.empty()) {
        return text;
    }
    Append(text,
           "Ray tracing cut-out cards' pixel shaders (r50, BB_RT_CARD_ALPHA_LOG=1): the distinct "
           "pixel shaders of the scene's cut-out instances so far, by the r46 rule's class (a "
           "shader counts in each class it was seen in)");
    const size_t classes = size_t(CutoutCardClass::Count);
    std::vector<std::pair<u64, u8>> unmatched; // camera pass, by class (plants first)
    for (const bool sun : {false, true}) {
        Append(text, "; %s:", sun ? "sun shadow pass draws that sample a texture"
                                  : "camera pass draws that discard");
        for (size_t k = 0; k < classes; ++k) {
            std::array<u32, VerdictNames.size()> mix{};
            u32 total = 0, repeatable = 0, with_constants = 0, matched = 0, cpu = 0, no_memory = 0;
            std::array<u32, ConstantsNames.size()> draws{};
            for (const auto& [hash, shader] : card_shaders) {
                if (((sun ? shader.sun : shader.camera) & (1u << k)) == 0) {
                    continue;
                }
                const auto found = analysed_shaders.find(hash);
                const Cutout c = found != analysed_shaders.end() ? found->second : Cutout{};
                ++total;
                ++mix[size_t(c.verdict)];
                repeatable += c.RepeatableFromRecord() ? 1 : 0;
                matched += c.verdict == Verdict::Matched ? 1 : 0;
                if (!sun && c.verdict != Verdict::Matched && unmatched.size() < 64) {
                    unmatched.push_back({hash, u8(k)});
                }
                if (!c.RepeatableWithConstants()) {
                    continue;
                }
                ++with_constants;
                const auto dwords = CutoutDwords(c);
                if (std::ranges::all_of(dwords, [](const CutoutDword& d) {
                        return d.kind == Ref::Immediate;
                    })) {
                    ++no_memory; // nothing to read: not counted as CPU-written
                    continue;
                }
                const auto seen = constants_seen.find(hash);
                if (seen == constants_seen.end()) {
                    continue;
                }
                const auto& n = seen->second.draws;
                for (size_t s = 0; s < draws.size(); ++s) {
                    draws[s] += n[s];
                }
                // every draw whose dwords were looked at read them, none GPU-written
                cpu += seen->second.printed && seen->second.worst == CutoutConstants::CpuWritten ? 1
                                                                                                 : 0;
            }
            Append(text, "%s %s %u", k ? "," : "", ClassNames[k], total);
            if (total == 0) {
                continue;
            }
            text += " [";
            bool first = true;
            for (size_t verdict = 0; verdict < mix.size(); ++verdict) {
                if (mix[verdict] != 0) {
                    Append(text, "%s%u %s", first ? "" : ", ", mix[verdict], VerdictShort[verdict]);
                    first = false;
                }
            }
            Append(text,
                   "; %u repeatable, %u with constants; %u match, %u with CPU-written constants "
                   "on every draw, %u with no memory constants",
                   repeatable, with_constants, matched, cpu, no_memory);
            const u32 all = std::accumulate(draws.begin(), draws.end(), 0u);
            if (all != 0) {
                Append(text, "; %u draws:", all);
                for (size_t s = 0; s < draws.size(); ++s) {
                    Append(text, "%s %u %s", s ? "," : "", draws[s], ConstantsShort[s]);
                }
            }
            text += "]";
        }
    }
    std::ranges::sort(unmatched, [](const auto& x, const auto& y) {
        return x.second != y.second ? x.second < y.second : x.first < y.first;
    });
    if (!unmatched.empty()) {
        text += "; camera pass shaders not matched:";
        for (size_t i = 0; i < unmatched.size() && i < 8; ++i) {
            const auto found = analysed_shaders.find(unmatched[i].first);
            const Cutout c = found != analysed_shaders.end() ? found->second : Cutout{};
            Append(text, " %016llx (%s; %s%s%s)",
                   static_cast<unsigned long long>(unmatched[i].first),
                   ClassShort[unmatched[i].second],
                   VerdictShort[size_t(c.verdict)], c.detail != Detail::None ? ": " : "",
                   DetailNames[size_t(c.detail)]);
        }
    }
    return text;
}

void PrintCutoutSummary() {
    if (!CutoutAnalysisOn()) {
        return;
    }
    for (const std::string& text : {CutoutSummaryText(), CutoutCardsText()}) {
        if (!text.empty()) {
            std::printf("%s\n", text.c_str());
        }
    }
}

} // namespace Shader::Optimization
"""),
    TESTS + "test_rt_card_alpha.cpp": (r"""// SPDX-License-Identifier: GPL-2.0-or-later
// bbport (r50_leaf-stage1): the cut-out analysis (cutout_analysis.h) on fragment programs built
// as the translator and the passes before it leave them.
#include <cassert>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include "common/object_pool.h"
#include "shader_recompiler/ir/basic_block.h"
#include "shader_recompiler/ir/ir_emitter.h"
#include "shader_recompiler/ir/passes/cutout_analysis.h"
#include "shader_recompiler/ir/program.h"

using namespace Shader;
using Cutout = Info::Cutout;

namespace {

constexpr IR::Attribute Uv = IR::Attribute::Param0 + 1;

/// One fragment program; `body` emits its instructions and returns nothing.
template <typename Body>
Cutout Analyze(Body&& body, bool clip_emulation = false, std::string* line = nullptr) {
    Common::ObjectPool<IR::Inst> pool;
    IR::Block block(pool);
    IR::IREmitter ir(block);
    Info info{};
    info.sw_stage = SwStage::Fragment;
    info.pgm_hash = 0xfeedbeef;
    RuntimeInfo runtime_info{};
    runtime_info.Initialize(HwStage::Fragment, SwStage::Fragment);
    runtime_info.hw.fs.num_inputs = 2;
    runtime_info.hw.fs.inputs[1].param_index = 5;
    if (clip_emulation) {
        runtime_info.hw.fs.clip_distance_emulation = true;
        runtime_info.hw.fs.num_inputs = 3;
    }
    body(ir);
    IR::Program program(info);
    program.blocks.push_back(&block);
    info.cutout = Optimization::AnalyzeCutout(program, runtime_info);
    if (line) {
        *line = Optimization::CutoutLine(info, runtime_info);
    }
    return info.cutout;
}

IR::Value Sample(IR::IREmitter& ir, u32 image, const IR::F32& u, const IR::F32& v) {
    return ir.ImageSampleImplicitLod(ir.Imm32(image | 1u << 16), ir.CompositeConstruct(u, v),
                                     ir.Imm32(0.0f), IR::Value{}, {});
}

/// A structured fragment program as the structurizer leaves it (syntax_list): blocks, ifs and
/// returns, each block with its own emitter.
struct Flow {
    Common::ObjectPool<IR::Inst> pool;
    std::deque<IR::Block> blocks;
    std::deque<IR::IREmitter> emitters;
    IR::AbstractSyntaxList list;

    IR::IREmitter& Block() {
        IR::Block& block = blocks.emplace_back(pool);
        auto& node = list.emplace_back();
        node.type = IR::AbstractSyntaxNode::Type::Block;
        node.data.block = &block;
        return emitters.emplace_back(block);
    }
    void If(IR::IREmitter& header, const IR::U1& cond) {
        const IR::U1 ref = header.ConditionRef(cond);
        auto& node = list.emplace_back();
        node.type = IR::AbstractSyntaxNode::Type::If;
        node.data.if_node.cond = ref;
    }
    void EndIf() {
        list.emplace_back().type = IR::AbstractSyntaxNode::Type::EndIf;
    }
    void Return() {
        list.emplace_back().type = IR::AbstractSyntaxNode::Type::Return;
    }
    Cutout Analyze() {
        Info info{};
        info.sw_stage = SwStage::Fragment;
        RuntimeInfo runtime_info{};
        runtime_info.Initialize(HwStage::Fragment, SwStage::Fragment);
        runtime_info.hw.fs.num_inputs = 2;
        IR::Program program(info);
        program.syntax_list = list;
        for (IR::Block& block : blocks) {
            program.blocks.push_back(&block);
        }
        return Optimization::AnalyzeCutout(program, runtime_info);
    }
};

IR::F32 Alpha(IR::IREmitter& ir, u32 image = 0) {
    const IR::Value texel = Sample(ir, image, ir.GetAttribute(Uv, 0), ir.GetAttribute(Uv, 1));
    return IR::F32{ir.CompositeExtract(texel, 3)};
}

/// export.cpp's discard of a pixel whose exec bit the compares cleared.
void DiscardUnless(IR::IREmitter& ir, const IR::U1& keep) {
    ir.Discard(ir.LogicalNot(keep));
}

void CheckMatched() {
    // alpha >= 0.5
    std::string line;
    Cutout c = Analyze(
        [](IR::IREmitter& ir) {
            DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), ir.Imm32(0.5f)));
        },
        false, &line);
    assert(c.verdict == Cutout::Verdict::Matched && c.detail == Cutout::Detail::None);
    assert(c.op == Cutout::Op::GreaterEqual && c.ref_kind == Cutout::Ref::Immediate);
    assert(c.ref == 0.5f && c.channel == 3 && c.image == 0 && c.sampler == 1);
    assert(c.input == 1 && c.comp_u == 0 && c.comp_v == 1 && !c.uv_by_constant);
    assert(c.uv_scale[0] == 1.0f && c.uv_offset[1] == 0.0f && c.other_terms == 0);
    assert(line.size() < 200 && line.find("feedbeef") != std::string::npos);
    assert(line.find(".w >= 0.5, uv in1.xy (vs out 5)") != std::string::npos);

    // 0 <= alpha - s4, the clip form: alpha >= the user data dword
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 ref = ir.BitCast<IR::F32>(ir.GetUserData(IR::ScalarReg::S4));
        DiscardUnless(ir, ir.FPLessThanEqual(ir.Imm32(0.0f), ir.FPSub(Alpha(ir), ref)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.op == Cutout::Op::GreaterEqual);
    assert(c.ref_kind == Cutout::Ref::UserData && c.ref_dword == 4);
    assert(c.ref == 0.0f && c.ref_scale == 1.0f);

    // s_andn2 of exec with a fade: kept where the fade holds and not alpha < cb2[12]
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 ref = ir.BitCast<IR::F32>(
            ir.ReadConstBuffer(ir.Imm32(2u), ir.Imm32(12u), {}));
        const IR::U1 fade = ir.FPLessThan(ir.GetAttribute(IR::Attribute::Param0, 2), ir.Imm32(1.0f));
        const IR::U1 cut = ir.FPLessThan(Alpha(ir), ref);
        DiscardUnless(ir, ir.LogicalNot(ir.LogicalOr(ir.LogicalNot(fade), cut)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.op == Cutout::Op::GreaterEqual);
    assert(c.ref_kind == Cutout::Ref::ConstBuffer && c.ref_buffer == 2 && c.ref_dword == 12);
    assert(c.other_terms == 1);

    // saturate(alpha * 2 - 1) > 0: alpha > 0.5
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a = ir.FPSaturate(ir.FPFma(Alpha(ir), ir.Imm32(2.0f), ir.Imm32(-1.0f)));
        DiscardUnless(ir, ir.FPGreaterThan(a, ir.Imm32(0.0f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.op == Cutout::Op::Greater);
    assert(c.ref == 0.5f && c.ref_kind == Cutout::Ref::Immediate);

    // discarded where 0.3 >= -alpha: kept where alpha < -0.3
    c = Analyze([](IR::IREmitter& ir) {
        ir.Discard(ir.FPGreaterThanEqual(ir.Imm32(0.3f), ir.FPNeg(Alpha(ir))));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.op == Cutout::Op::Less);
    assert(c.ref == -0.3f);

    // a reference from the flat user data
    c = Analyze([](IR::IREmitter& ir) {
        const IR::U32 dword = ir.ReadConst(ir.Imm32(0u), ir.Imm32(0u));
        dword.Inst()->SetFlags<u32>(9);
        DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), ir.BitCast<IR::F32>(dword)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.ref_kind == Cutout::Ref::FlatUserData);
    assert(c.ref_dword == 9);

    // V_MUL_LEGACY_F32 of alpha and 2 (vector_alu.cpp), its compare of the immediate folded and
    // not: alpha * 2 >= 0.5
    for (const bool folded : {false, true}) {
        c = Analyze([folded](IR::IREmitter& ir) {
            const IR::F32 alpha = Alpha(ir);
            const IR::F32 two = ir.Imm32(2.0f);
            const IR::U1 zero = folded ? ir.FPEqual(alpha, ir.Imm32(0.0f))
                                       : ir.LogicalOr(ir.FPEqual(alpha, ir.Imm32(0.0f)),
                                                      ir.FPEqual(two, ir.Imm32(0.0f)));
            const IR::F32 a{ir.Select(zero, ir.Imm32(0.0f), ir.FPMul(alpha, two))};
            DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
        });
        assert(c.verdict == Cutout::Verdict::Matched && c.ref == 0.25f);
        assert(c.Repeatable() && c.kill_blocks == 0);
    }
}

void CheckCoordinates() {
    // uv * 2 + 0.25, one scale for both components
    Cutout c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 u = ir.FPFma(ir.GetAttribute(Uv, 0), ir.Imm32(2.0f), ir.Imm32(0.25f));
        const IR::F32 v = ir.FPMul(ir.GetAttribute(Uv, 1), ir.Imm32(2.0f));
        const IR::F32 a{ir.CompositeExtract(Sample(ir, 0, u, v), 3)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.input == 1);
    assert(c.uv_scale[0] == 2.0f && c.uv_scale[1] == 2.0f);
    assert(c.uv_offset[0] == 0.25f && c.uv_offset[1] == 0.0f && !c.uv_by_constant);

    // GCN's own interpolation (no hardware interpolation)
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 i = ir.GetAttribute(IR::Attribute::BaryCoordSmooth, 0);
        const IR::F32 j = ir.GetAttribute(IR::Attribute::BaryCoordSmooth, 1);
        const auto interpolate = [&](u32 comp) {
            const IR::F32 p0 = ir.GetAttribute(Uv, comp, 0);
            const IR::F32 p1 = ir.GetAttribute(Uv, comp, 1);
            const IR::F32 p2 = ir.GetAttribute(Uv, comp, 2);
            const IR::F32 p1_ = ir.FPFma(ir.FPSub(p1, p0), i, p0);
            return IR::F32{ir.FPFma(ir.FPSub(p2, p0), j, p1_)};
        };
        const IR::F32 a{ir.CompositeExtract(Sample(ir, 0, interpolate(0), interpolate(1)), 3)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.input == 1 && c.comp_v == 1);

    // a scroll by a user data dword
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 scroll = ir.BitCast<IR::F32>(ir.GetUserData(IR::ScalarReg::S5));
        const IR::F32 u = ir.FPAdd(ir.GetAttribute(Uv, 0), scroll);
        const IR::F32 a{ir.CompositeExtract(Sample(ir, 0, u, ir.GetAttribute(Uv, 1)), 3)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.uv_by_constant);

    // fract(uv): the alpha test kept, the coordinates not an input
    std::string line;
    c = Analyze(
        [](IR::IREmitter& ir) {
            const IR::F32 u = ir.FPFract(ir.GetAttribute(Uv, 0));
            const IR::F32 a{ir.CompositeExtract(Sample(ir, 0, u, ir.GetAttribute(Uv, 1)), 3)};
            DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
        },
        false, &line);
    assert(c.verdict == Cutout::Verdict::UvNotInput && c.detail == Cutout::Detail::UvComputed);
    assert(c.channel == 3 && c.ref == 0.5f);
    assert(line.find("uv not an input") != std::string::npos);

    // u and v from two inputs
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a{ir.CompositeExtract(
            Sample(ir, 0, ir.GetAttribute(Uv, 0), ir.GetAttribute(IR::Attribute::Param0, 1)), 3)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::UvNotInput && c.detail == Cutout::Detail::UvTwoInputs);

    // an array layer: an immediate one is part of the record, a computed one is not
    for (const bool varying : {false, true}) {
        c = Analyze([varying](IR::IREmitter& ir) {
            const IR::F32 layer =
                varying ? ir.GetAttribute(IR::Attribute::Param0, 0) : ir.Imm32(2.0f);
            const IR::Value texel = ir.ImageSampleImplicitLod(
                ir.Imm32(1u << 16),
                ir.CompositeConstruct(ir.GetAttribute(Uv, 0), ir.GetAttribute(Uv, 1), layer),
                ir.Imm32(0.0f), IR::Value{}, {});
            DiscardUnless(ir, ir.FPGreaterThanEqual(IR::F32{ir.CompositeExtract(texel, 3)},
                                                    ir.Imm32(0.5f)));
        });
        assert(c.verdict == Cutout::Verdict::Matched);
        assert(c.layer == (varying ? Cutout::Layer::Other : Cutout::Layer::Immediate));
        assert(c.Repeatable() == !varying && (varying || c.layer_value == 2.0f));
    }

    // a texel offset: matched, not repeatable from the record alone
    c = Analyze([](IR::IREmitter& ir) {
        IR::TextureInstInfo flags{};
        flags.has_offset.Assign(1);
        const IR::Value texel = ir.ImageSampleImplicitLod(
            ir.Imm32(1u << 16),
            ir.CompositeConstruct(ir.GetAttribute(Uv, 0), ir.GetAttribute(Uv, 1)), ir.Imm32(0.0f),
            ir.Imm32(0x0101u), flags);
        DiscardUnless(ir, ir.FPGreaterThanEqual(IR::F32{ir.CompositeExtract(texel, 3)},
                                                ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.texel_offset && !c.Repeatable());

    // a scroll from memory is matched but not repeatable from the record alone
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 scroll = ir.BitCast<IR::F32>(ir.GetUserData(IR::ScalarReg::S5));
        const IR::F32 a{ir.CompositeExtract(
            Sample(ir, 0, ir.FPAdd(ir.GetAttribute(Uv, 0), scroll), ir.GetAttribute(Uv, 1)), 3)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.uv_by_constant && !c.Repeatable());
}

void CheckControlFlow() {
    // the export in v_cmpx's exec scope: If(exec) { discard unless exec } (control_flow_graph.cpp)
    {
        Flow flow;
        IR::IREmitter& top = flow.Block();
        const IR::U1 keep = top.FPGreaterThanEqual(Alpha(top), top.Imm32(0.5f));
        flow.If(top, keep);
        DiscardUnless(flow.Block(), keep);
        flow.EndIf();
        flow.Block();
        flow.Return();
        const Cutout c = flow.Analyze();
        assert(c.verdict == Cutout::Verdict::Matched && c.kill_blocks == 0);
    }
    // the execz skip with its kill block: If(exec) { ...; discard unless exec; return }
    // s_mov_b64 exec, 0; exp null vm (a Discard); return
    {
        Flow flow;
        IR::IREmitter& top = flow.Block();
        const IR::U1 keep = top.FPGreaterThanEqual(Alpha(top), top.Imm32(0.5f));
        flow.If(top, keep);
        DiscardUnless(flow.Block(), keep);
        flow.Return();
        flow.EndIf();
        flow.Block().Discard();
        flow.Return();
        const Cutout c = flow.Analyze();
        assert(c.verdict == Cutout::Verdict::Matched && c.kill_blocks == 1);
    }
    // a uniform switch (s_cbranch_scc1 on a user data flag) to an opaque tail that returns: its
    // discard of exec = true is folded away, the alpha test holds on one way only
    {
        Flow flow;
        IR::IREmitter& top = flow.Block();
        const IR::U1 opaque = top.IEqual(top.GetUserData(IR::ScalarReg::S4), top.Imm32(0u));
        flow.If(top, opaque);
        flow.Block();
        flow.Return();
        flow.EndIf();
        IR::IREmitter& tail = flow.Block();
        DiscardUnless(tail, tail.FPGreaterThanEqual(Alpha(tail), tail.Imm32(0.5f)));
        flow.Return();
        const Cutout c = flow.Analyze();
        assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::ControlFlow);
    }
    // the same flag around the alpha tail
    {
        Flow flow;
        IR::IREmitter& top = flow.Block();
        const IR::U1 tested = top.INotEqual(top.GetUserData(IR::ScalarReg::S4), top.Imm32(0u));
        flow.If(top, tested);
        IR::IREmitter& body = flow.Block();
        DiscardUnless(body, body.FPGreaterThanEqual(Alpha(body), body.Imm32(0.5f)));
        flow.EndIf();
        flow.Block();
        flow.Return();
        const Cutout c = flow.Analyze();
        assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::ControlFlow);
    }
    // an unconditional discard in a branch the test does not decide
    {
        Flow flow;
        IR::IREmitter& top = flow.Block();
        const IR::U1 keep = top.FPGreaterThanEqual(Alpha(top), top.Imm32(0.5f));
        DiscardUnless(top, keep);
        flow.If(top, top.FPLessThan(top.GetAttribute(IR::Attribute::Param0, 0), top.Imm32(0.0f)));
        flow.Block().Discard();
        flow.EndIf();
        flow.Block();
        flow.Return();
        const Cutout c = flow.Analyze();
        assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::BranchDiscard);
    }
    // the v_cmpx skipped by a uniform branch: exec at the export a phi of true and the test
    {
        Flow flow;
        IR::IREmitter& top = flow.Block();
        const IR::U1 keep = top.FPGreaterThanEqual(Alpha(top), top.Imm32(0.5f));
        IR::IREmitter& tail = flow.Block();
        IR::Block& tail_block = flow.blocks.back();
        IR::Inst* phi = &*tail_block.PrependNewInst(tail_block.begin(), IR::Opcode::Phi, {});
        phi->SetFlags(IR::Type::U1);
        phi->AddPhiOperand(&flow.blocks.front(), keep);
        phi->AddPhiOperand(&tail_block, tail.Imm1(true));
        DiscardUnless(tail, IR::U1{IR::Value{phi}});
        flow.Return();
        const Cutout c = flow.Analyze();
        assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::ControlFlow);
    }
}

void CheckCost() {
    // x_{i+1} = x_i + x_i, 40 levels (deeper than the walk goes) and 26, and LogicalAnd(t, t) 24
    // levels (2^24 ways down without the memo): each value is walked once
    const auto start = std::chrono::steady_clock::now();
    Cutout c = Analyze([](IR::IREmitter& ir) {
        IR::F32 x = ir.GetAttribute(IR::Attribute::Param0, 0);
        for (u32 i = 0; i < 40; ++i) {
            x = ir.FPAdd(x, x);
        }
        DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), x));
    });
    assert(c.verdict == Cutout::Verdict::Other);
    c = Analyze([](IR::IREmitter& ir) {
        IR::F32 x = ir.GetAttribute(IR::Attribute::Param0, 0);
        for (u32 i = 0; i < 26; ++i) { // the review's case: 671 ms without the memo
            x = ir.FPAdd(x, x);
        }
        DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), x));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::VaryingRef);
    c = Analyze([](IR::IREmitter& ir) {
        IR::U1 keep = ir.FPGreaterThanEqual(Alpha(ir), ir.Imm32(0.5f));
        for (u32 i = 0; i < 24; ++i) { // within the depth the walk takes apart (32)
            keep = ir.LogicalAnd(keep, keep);
        }
        DiscardUnless(ir, keep);
    });
    assert(c.verdict == Cutout::Verdict::Matched);
    const double ms =
        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
    std::printf("rt-card-alpha-test: reused values analysed in %.2f ms\n", ms);
    assert(ms < 200.0);
}

void CheckNotMatched() {
    // no discard
    Cutout c = Analyze([](IR::IREmitter& ir) { (void)Alpha(ir); });
    assert(c.verdict == Cutout::Verdict::NoDiscard);

    // the clip distance emulation's discard alone
    c = Analyze(
        [](IR::IREmitter& ir) {
            ir.Discard(ir.FPLessThan(ir.GetAttribute(IR::Attribute::Param0 + 2, 0), ir.Imm32(0.0f)));
        },
        true);
    assert(c.verdict == Cutout::Verdict::NoDiscard);

    // ... and beside an alpha test
    c = Analyze(
        [](IR::IREmitter& ir) {
            ir.Discard(ir.FPLessThan(ir.GetAttribute(IR::Attribute::Param0 + 2, 0), ir.Imm32(0.0f)));
            DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), ir.Imm32(0.5f)));
        },
        true);
    assert(c.verdict == Cutout::Verdict::Matched && c.other_terms == 0);

    // a varying alone
    c = Analyze([](IR::IREmitter& ir) {
        DiscardUnless(ir, ir.FPGreaterThan(ir.GetAttribute(IR::Attribute::Param0, 3), ir.Imm32(0.0f)));
    });
    assert(c.verdict == Cutout::Verdict::NotTexture);

    // alpha times the vertex colour's
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a = ir.FPMul(Alpha(ir), ir.GetAttribute(IR::Attribute::Param0, 3));
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::VaryingFactor);

    // alpha compared with a varying
    c = Analyze([](IR::IREmitter& ir) {
        DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), ir.GetAttribute(IR::Attribute::Param0, 3)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::VaryingRef);

    // two textures' alphas in one test, and in two tests
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a = ir.FPMul(Alpha(ir, 0), Alpha(ir, 1));
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::SeveralTextures);
    c = Analyze([](IR::IREmitter& ir) {
        DiscardUnless(ir, ir.LogicalAnd(ir.FPGreaterThanEqual(Alpha(ir, 0), ir.Imm32(0.5f)),
                                        ir.FPGreaterThanEqual(Alpha(ir, 1), ir.Imm32(0.5f))));
    });
    assert(c.verdict == Cutout::Verdict::SeveralTextures);

    // an alpha test and a dither against a second texture's noise and a varying
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 noise{ir.CompositeExtract(
            Sample(ir, 1, ir.GetAttribute(Uv, 0), ir.GetAttribute(Uv, 1)), 0)};
        DiscardUnless(ir, ir.LogicalAnd(ir.FPGreaterThanEqual(Alpha(ir, 0), ir.Imm32(0.5f)),
                                        ir.FPLessThan(noise, ir.GetAttribute(IR::Attribute::Param0, 3))));
    });
    assert(c.verdict == Cutout::Verdict::SeveralTextures);

    // two channels of one sample
    c = Analyze([](IR::IREmitter& ir) {
        const IR::Value texel = Sample(ir, 0, ir.GetAttribute(Uv, 0), ir.GetAttribute(Uv, 1));
        const IR::F32 a = ir.FPMul(IR::F32{ir.CompositeExtract(texel, 0)},
                                   IR::F32{ir.CompositeExtract(texel, 3)});
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::TwoChannels);

    // alpha - fade >= 0 is alpha >= fade: a varying reference
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a = ir.FPSub(Alpha(ir), ir.GetAttribute(IR::Attribute::Param0, 3));
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.0f)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::VaryingRef);

    // V_CNDMASK_B32 of a fade: Select(fade, 0, alpha * 1.5) is no V_MUL_LEGACY
    c = Analyze([](IR::IREmitter& ir) {
        const IR::U1 fade = ir.FPGreaterThan(ir.GetAttribute(IR::Attribute::Param0, 2),
                                             ir.BitCast<IR::F32>(ir.GetUserData(IR::ScalarReg::S5)));
        const IR::F32 a{ir.Select(fade, ir.Imm32(0.0f), ir.FPMul(Alpha(ir), ir.Imm32(1.5f)))};
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::Computed);

    // either of two tests keeps the pixel
    c = Analyze([](IR::IREmitter& ir) {
        DiscardUnless(ir, ir.LogicalOr(ir.FPGreaterThanEqual(Alpha(ir), ir.Imm32(0.5f)),
                                       ir.FPLessThan(ir.GetAttribute(IR::Attribute::Param0, 3),
                                                     ir.Imm32(0.0f))));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::Disjunction);

    // an unconditional discard (in a branch)
    c = Analyze([](IR::IREmitter& ir) {
        (void)Alpha(ir);
        ir.Discard();
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::BranchDiscard);

    // the alpha scaled by a dword from memory
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 k = ir.BitCast<IR::F32>(ir.GetUserData(IR::ScalarReg::S6));
        DiscardUnless(ir, ir.FPGreaterThanEqual(ir.FPMul(Alpha(ir), k), ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::ConstantScale);
}

/// The alpha's T# as the compiling draw's flat user data hold it (8 dwords, and an r128 one of 4):
/// the view lane .w reads the stored red channel of a one-channel format.
void CheckTsharp() {
    for (const bool r128 : {false, true}) {
        Common::ObjectPool<IR::Inst> pool;
        IR::Block block(pool);
        IR::IREmitter ir(block);
        DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), ir.Imm32(0.5f)));
        Info info{};
        info.sw_stage = SwStage::Fragment;
        AmdGpu::Image tsharp{};
        tsharp.type = u64(AmdGpu::ImageType::Color2D);
        tsharp.dst_sel_w = u64(AmdGpu::CompSwizzle::Red);
        tsharp.data_format = 1;
        info.flattened_ud_buf.assign(16, 0u);
        std::memcpy(info.flattened_ud_buf.data() + 4, &tsharp, sizeof(tsharp));
        ImageResource image{};
        image.is_r128 = r128;
        image.sharp_fetch.offsets.fill(UNKNOWN_LOCATION);
        for (u32 i = 0; i < (r128 ? 4u : 8u); ++i) {
            image.sharp_fetch.offsets[i] = SharpLocation(4 + i);
            image.sharp_fetch.load_mask |= u8(1u << i);
        }
        info.images.push_back(image);
        RuntimeInfo runtime_info{};
        runtime_info.Initialize(HwStage::Fragment, SwStage::Fragment);
        runtime_info.hw.fs.num_inputs = 2;
        IR::Program program(info);
        program.blocks.push_back(&block);
        info.cutout = Optimization::AnalyzeCutout(program, runtime_info);
        const Cutout& c = info.cutout;
        assert(c.verdict == Cutout::Verdict::Matched && c.channel == 3);
        assert(c.stored == u8(AmdGpu::CompSwizzle::Red) && c.data_format == 1);
        const std::string line = Optimization::CutoutLine(info, runtime_info);
        assert(line.find("image 0 (T# flat 4; .w reads r, format 1) sampler 1") != std::string::npos);
    }
}

/// The two 600-frame lines (the knob is set in main before anything reads it).
void CheckSummary() {
    Common::ObjectPool<IR::Inst> pool;
    IR::Block block(pool);
    IR::IREmitter ir(block);
    DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), ir.Imm32(0.5f)));
    Info info{};
    info.sw_stage = SwStage::Fragment;
    info.pgm_hash = 0x1234;
    RuntimeInfo runtime_info{};
    runtime_info.Initialize(HwStage::Fragment, SwStage::Fragment);
    runtime_info.hw.fs.num_inputs = 2;
    IR::Program program(info);
    program.blocks.push_back(&block);
    assert(Optimization::CutoutAnalysisOn());
    assert(Optimization::CutoutCardsText().empty());
    Optimization::CutoutAnalysisPass(program, runtime_info);
    Optimization::CutoutAnalysisPass(program, runtime_info); // the same pgm_hash: counted once
    Optimization::NoteCutoutCacheRefusal();
    Optimization::NoteCutoutCard(0x1234, 0, Optimization::CutoutCardClass::Plant);
    Optimization::NoteCutoutCard(0x5678, 0x1234, Optimization::CutoutCardClass::SkinnedKept);
    const std::string summary = Optimization::CutoutSummaryText();
    assert(summary.find("1 pixel shaders compiled in play and analysed (1 since the last line; 1 "
                        "discarding cache records") != std::string::npos);
    assert(summary.find("of the 1 that discard 1 match") != std::string::npos);
    assert(Optimization::CutoutSummaryText().find("(0 since the last line") != std::string::npos);
    const std::string cards = Optimization::CutoutCardsText();
    assert(cards.find("plants (left out of lamp rays: a skeleton, no sun shadow pass draw) 1 [1 "
                      "match; 1 repeatable]") != std::string::npos);
    assert(cards.find("kept whole: a skeleton (hair, cloth, characters) 1 [1 not analysed; 0 "
                      "repeatable]") != std::string::npos);
    assert(cards.find("0000000000005678 (skeleton, kept; not analysed)") != std::string::npos);
    std::printf("%s\n%s\n", summary.c_str(), cards.c_str());
}

} // namespace

int main() {
#ifdef _WIN32
    _putenv_s("BB_RT_CARD_ALPHA_LOG", "1");
#else
    setenv("BB_RT_CARD_ALPHA_LOG", "1", 1);
#endif
    CheckMatched();
    CheckCoordinates();
    CheckNotMatched();
    CheckControlFlow();
    CheckTsharp();
    CheckCost();
    CheckSummary();
    std::printf("rt-card-alpha-test: ok (alpha tests, coordinates, shaders not matched)\n");
    return 0;
}
""", r"""// SPDX-License-Identifier: GPL-2.0-or-later
// bbport (r50_leaf-stage1, r50b_leaf-matcher): the cut-out analysis (cutout_analysis.h) on
// fragment programs built as the translator and the passes before it leave them.
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include "common/object_pool.h"
#include "shader_recompiler/ir/basic_block.h"
#include "shader_recompiler/ir/ir_emitter.h"
#include "shader_recompiler/ir/passes/cutout_analysis.h"
#include "shader_recompiler/ir/program.h"

using namespace Shader;
using Cutout = Info::Cutout;

namespace {

constexpr IR::Attribute Uv = IR::Attribute::Param0 + 1;

/// One fragment program; `setup` may change its Info and RuntimeInfo before `body` emits its
/// instructions.
template <typename Setup, typename Body>
Cutout AnalyzeWith(Setup&& setup, Body&& body, std::string* line = nullptr) {
    Common::ObjectPool<IR::Inst> pool;
    IR::Block block(pool);
    IR::IREmitter ir(block);
    Info info{};
    info.sw_stage = SwStage::Fragment;
    info.pgm_hash = 0xfeedbeef;
    RuntimeInfo runtime_info{};
    runtime_info.Initialize(HwStage::Fragment, SwStage::Fragment);
    runtime_info.hw.fs.num_inputs = 2;
    runtime_info.hw.fs.inputs[1].param_index = 5;
    setup(info, runtime_info);
    body(ir);
    IR::Program program(info);
    program.blocks.push_back(&block);
    info.cutout = Optimization::AnalyzeCutout(program, runtime_info);
    if (line) {
        *line = Optimization::CutoutLine(info, runtime_info);
    }
    return info.cutout;
}

/// One fragment program; `body` emits its instructions and returns nothing.
template <typename Body>
Cutout Analyze(Body&& body, bool clip_emulation = false, std::string* line = nullptr) {
    return AnalyzeWith(
        [clip_emulation](Info&, RuntimeInfo& runtime_info) {
            if (clip_emulation) {
                runtime_info.hw.fs.clip_distance_emulation = true;
                runtime_info.hw.fs.num_inputs = 3;
            }
        },
        body, line);
}

IR::Value Sample(IR::IREmitter& ir, u32 image, const IR::F32& u, const IR::F32& v) {
    return ir.ImageSampleImplicitLod(ir.Imm32(image | 1u << 16), ir.CompositeConstruct(u, v),
                                     ir.Imm32(0.0f), IR::Value{}, {});
}

/// A structured fragment program as the structurizer leaves it (syntax_list): blocks, ifs and
/// returns, each block with its own emitter.
struct Flow {
    Common::ObjectPool<IR::Inst> pool;
    std::deque<IR::Block> blocks;
    std::deque<IR::IREmitter> emitters;
    IR::AbstractSyntaxList list;

    IR::IREmitter& Block() {
        IR::Block& block = blocks.emplace_back(pool);
        auto& node = list.emplace_back();
        node.type = IR::AbstractSyntaxNode::Type::Block;
        node.data.block = &block;
        return emitters.emplace_back(block);
    }
    void If(IR::IREmitter& header, const IR::U1& cond) {
        const IR::U1 ref = header.ConditionRef(cond);
        auto& node = list.emplace_back();
        node.type = IR::AbstractSyntaxNode::Type::If;
        node.data.if_node.cond = ref;
    }
    void EndIf() {
        list.emplace_back().type = IR::AbstractSyntaxNode::Type::EndIf;
    }
    void Return() {
        list.emplace_back().type = IR::AbstractSyntaxNode::Type::Return;
    }
    Cutout Analyze() {
        Info info{};
        info.sw_stage = SwStage::Fragment;
        RuntimeInfo runtime_info{};
        runtime_info.Initialize(HwStage::Fragment, SwStage::Fragment);
        runtime_info.hw.fs.num_inputs = 2;
        IR::Program program(info);
        program.syntax_list = list;
        for (IR::Block& block : blocks) {
            program.blocks.push_back(&block);
        }
        return Optimization::AnalyzeCutout(program, runtime_info);
    }
};

IR::F32 Alpha(IR::IREmitter& ir, u32 image = 0) {
    const IR::Value texel = Sample(ir, image, ir.GetAttribute(Uv, 0), ir.GetAttribute(Uv, 1));
    return IR::F32{ir.CompositeExtract(texel, 3)};
}

/// export.cpp's discard of a pixel whose exec bit the compares cleared.
void DiscardUnless(IR::IREmitter& ir, const IR::U1& keep) {
    ir.Discard(ir.LogicalNot(keep));
}

void CheckMatched() {
    // alpha >= 0.5
    std::string line;
    Cutout c = Analyze(
        [](IR::IREmitter& ir) {
            DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), ir.Imm32(0.5f)));
        },
        false, &line);
    assert(c.verdict == Cutout::Verdict::Matched && c.detail == Cutout::Detail::None);
    assert(c.op == Cutout::Op::GreaterEqual && c.ref_kind == Cutout::Ref::Immediate);
    assert(c.ref == 0.5f && c.channel == 3 && c.image == 0 && c.sampler == 1);
    assert(c.input == 1 && c.comp_u == 0 && c.comp_v == 1 && !c.uv_by_constant);
    assert(c.uv_scale[0] == 1.0f && c.uv_offset[1] == 0.0f && c.other_terms == 0);
    assert(line.size() < 200 && line.find("feedbeef") != std::string::npos);
    assert(line.find(".w >= 0.5, uv in1.xy (vs out 5)") != std::string::npos);

    // 0 <= alpha - s4, the clip form: alpha >= the user data dword
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 ref = ir.BitCast<IR::F32>(ir.GetUserData(IR::ScalarReg::S4));
        DiscardUnless(ir, ir.FPLessThanEqual(ir.Imm32(0.0f), ir.FPSub(Alpha(ir), ref)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.op == Cutout::Op::GreaterEqual);
    assert(c.ref_kind == Cutout::Ref::UserData && c.ref_dword == 4);
    assert(c.ref == 0.0f && c.ref_scale == 1.0f);

    // s_andn2 of exec with a fade: kept where the fade holds and not alpha < cb2[12]
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 ref = ir.BitCast<IR::F32>(
            ir.ReadConstBuffer(ir.Imm32(2u), ir.Imm32(12u), {}));
        const IR::U1 fade = ir.FPLessThan(ir.GetAttribute(IR::Attribute::Param0, 2), ir.Imm32(1.0f));
        const IR::U1 cut = ir.FPLessThan(Alpha(ir), ref);
        DiscardUnless(ir, ir.LogicalNot(ir.LogicalOr(ir.LogicalNot(fade), cut)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.op == Cutout::Op::GreaterEqual);
    assert(c.ref_kind == Cutout::Ref::ConstBuffer && c.ref_buffer == 2 && c.ref_dword == 12);
    assert(c.other_terms == 1);

    // saturate(alpha * 2 - 1) > 0: alpha > 0.5
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a = ir.FPSaturate(ir.FPFma(Alpha(ir), ir.Imm32(2.0f), ir.Imm32(-1.0f)));
        DiscardUnless(ir, ir.FPGreaterThan(a, ir.Imm32(0.0f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.op == Cutout::Op::Greater);
    assert(c.ref == 0.5f && c.ref_kind == Cutout::Ref::Immediate);

    // discarded where 0.3 >= -alpha: kept where alpha < -0.3
    c = Analyze([](IR::IREmitter& ir) {
        ir.Discard(ir.FPGreaterThanEqual(ir.Imm32(0.3f), ir.FPNeg(Alpha(ir))));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.op == Cutout::Op::Less);
    assert(c.ref == -0.3f);

    // a reference from the flat user data
    c = Analyze([](IR::IREmitter& ir) {
        const IR::U32 dword = ir.ReadConst(ir.Imm32(0u), ir.Imm32(0u));
        dword.Inst()->SetFlags<u32>(9);
        DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), ir.BitCast<IR::F32>(dword)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.ref_kind == Cutout::Ref::FlatUserData);
    assert(c.ref_dword == 9);

    // V_MUL_LEGACY_F32 of alpha and 2 (vector_alu.cpp), its compare of the immediate folded and
    // not: alpha * 2 >= 0.5
    for (const bool folded : {false, true}) {
        c = Analyze([folded](IR::IREmitter& ir) {
            const IR::F32 alpha = Alpha(ir);
            const IR::F32 two = ir.Imm32(2.0f);
            const IR::U1 zero = folded ? ir.FPEqual(alpha, ir.Imm32(0.0f))
                                       : ir.LogicalOr(ir.FPEqual(alpha, ir.Imm32(0.0f)),
                                                      ir.FPEqual(two, ir.Imm32(0.0f)));
            const IR::F32 a{ir.Select(zero, ir.Imm32(0.0f), ir.FPMul(alpha, two))};
            DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
        });
        assert(c.verdict == Cutout::Verdict::Matched && c.ref == 0.25f);
        assert(c.RepeatableFromRecord() && c.RepeatableWithConstants() && c.kill_blocks == 0);
    }
}

void CheckCoordinates() {
    // uv * 2 + 0.25, one scale for both components
    Cutout c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 u = ir.FPFma(ir.GetAttribute(Uv, 0), ir.Imm32(2.0f), ir.Imm32(0.25f));
        const IR::F32 v = ir.FPMul(ir.GetAttribute(Uv, 1), ir.Imm32(2.0f));
        const IR::F32 a{ir.CompositeExtract(Sample(ir, 0, u, v), 3)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.input == 1);
    assert(c.uv_scale[0] == 2.0f && c.uv_scale[1] == 2.0f);
    assert(c.uv_offset[0] == 0.25f && c.uv_offset[1] == 0.0f && !c.uv_by_constant);

    // GCN's own interpolation (no hardware interpolation)
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 i = ir.GetAttribute(IR::Attribute::BaryCoordSmooth, 0);
        const IR::F32 j = ir.GetAttribute(IR::Attribute::BaryCoordSmooth, 1);
        const auto interpolate = [&](u32 comp) {
            const IR::F32 p0 = ir.GetAttribute(Uv, comp, 0);
            const IR::F32 p1 = ir.GetAttribute(Uv, comp, 1);
            const IR::F32 p2 = ir.GetAttribute(Uv, comp, 2);
            const IR::F32 p1_ = ir.FPFma(ir.FPSub(p1, p0), i, p0);
            return IR::F32{ir.FPFma(ir.FPSub(p2, p0), j, p1_)};
        };
        const IR::F32 a{ir.CompositeExtract(Sample(ir, 0, interpolate(0), interpolate(1)), 3)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.input == 1 && c.comp_v == 1);

    // a scroll by a user data dword
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 scroll = ir.BitCast<IR::F32>(ir.GetUserData(IR::ScalarReg::S5));
        const IR::F32 u = ir.FPAdd(ir.GetAttribute(Uv, 0), scroll);
        const IR::F32 a{ir.CompositeExtract(Sample(ir, 0, u, ir.GetAttribute(Uv, 1)), 3)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.uv_by_constant);

    // fract(uv): the alpha test kept, the coordinates not an input
    std::string line;
    c = Analyze(
        [](IR::IREmitter& ir) {
            const IR::F32 u = ir.FPFract(ir.GetAttribute(Uv, 0));
            const IR::F32 a{ir.CompositeExtract(Sample(ir, 0, u, ir.GetAttribute(Uv, 1)), 3)};
            DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
        },
        false, &line);
    assert(c.verdict == Cutout::Verdict::UvNotInput && c.detail == Cutout::Detail::UvComputed);
    assert(c.channel == 3 && c.ref == 0.5f);
    assert(line.find("uv not an input") != std::string::npos);

    // u and v from two inputs
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a{ir.CompositeExtract(
            Sample(ir, 0, ir.GetAttribute(Uv, 0), ir.GetAttribute(IR::Attribute::Param0, 1)), 3)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::UvNotInput && c.detail == Cutout::Detail::UvTwoInputs);

    // an array layer: an immediate one is part of the record, a computed one is not
    for (const bool varying : {false, true}) {
        c = Analyze([varying](IR::IREmitter& ir) {
            const IR::F32 layer =
                varying ? ir.GetAttribute(IR::Attribute::Param0, 0) : ir.Imm32(2.0f);
            const IR::Value texel = ir.ImageSampleImplicitLod(
                ir.Imm32(1u << 16),
                ir.CompositeConstruct(ir.GetAttribute(Uv, 0), ir.GetAttribute(Uv, 1), layer),
                ir.Imm32(0.0f), IR::Value{}, {});
            DiscardUnless(ir, ir.FPGreaterThanEqual(IR::F32{ir.CompositeExtract(texel, 3)},
                                                    ir.Imm32(0.5f)));
        });
        assert(c.verdict == Cutout::Verdict::Matched);
        assert(c.layer == (varying ? Cutout::Layer::Other : Cutout::Layer::Immediate));
        assert(c.RepeatableFromRecord() == !varying && (varying || c.layer_value == 2.0f));
        assert(c.RepeatableWithConstants() == !varying);
    }

    // a texel offset: matched, not repeatable from the record alone
    c = Analyze([](IR::IREmitter& ir) {
        IR::TextureInstInfo flags{};
        flags.has_offset.Assign(1);
        const IR::Value texel = ir.ImageSampleImplicitLod(
            ir.Imm32(1u << 16),
            ir.CompositeConstruct(ir.GetAttribute(Uv, 0), ir.GetAttribute(Uv, 1)), ir.Imm32(0.0f),
            ir.Imm32(0x0101u), flags);
        DiscardUnless(ir, ir.FPGreaterThanEqual(IR::F32{ir.CompositeExtract(texel, 3)},
                                                ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.texel_offset && !c.RepeatableFromRecord());
    assert(!c.RepeatableWithConstants());

    // a scroll from memory is matched but not repeatable from the record alone; (r50b) the record
    // names its dword, so it is with the draw's constants
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 scroll = ir.BitCast<IR::F32>(ir.GetUserData(IR::ScalarReg::S5));
        const IR::F32 a{ir.CompositeExtract(
            Sample(ir, 0, ir.FPAdd(ir.GetAttribute(Uv, 0), scroll), ir.GetAttribute(Uv, 1)), 3)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.uv_by_constant && !c.RepeatableFromRecord());
    assert(c.RepeatableWithConstants() && !c.uv_unrecorded && c.uv_kind == Cutout::Ref::UserData);
    assert(c.uv_offset_dword[0] == 5 && c.uv_offset_dword[1] == Cutout::NoDword);
    assert(c.uv_scale_dword[0] == Cutout::NoDword && c.uv_scale_dword[1] == Cutout::NoDword);
}

void CheckControlFlow() {
    // the export in v_cmpx's exec scope: If(exec) { discard unless exec } (control_flow_graph.cpp)
    {
        Flow flow;
        IR::IREmitter& top = flow.Block();
        const IR::U1 keep = top.FPGreaterThanEqual(Alpha(top), top.Imm32(0.5f));
        flow.If(top, keep);
        DiscardUnless(flow.Block(), keep);
        flow.EndIf();
        flow.Block();
        flow.Return();
        const Cutout c = flow.Analyze();
        assert(c.verdict == Cutout::Verdict::Matched && c.kill_blocks == 0);
    }
    // the execz skip with its kill block: If(exec) { ...; discard unless exec; return }
    // s_mov_b64 exec, 0; exp null vm (a Discard); return
    {
        Flow flow;
        IR::IREmitter& top = flow.Block();
        const IR::U1 keep = top.FPGreaterThanEqual(Alpha(top), top.Imm32(0.5f));
        flow.If(top, keep);
        DiscardUnless(flow.Block(), keep);
        flow.Return();
        flow.EndIf();
        flow.Block().Discard();
        flow.Return();
        const Cutout c = flow.Analyze();
        assert(c.verdict == Cutout::Verdict::Matched && c.kill_blocks == 1);
    }
    // a uniform switch (s_cbranch_scc1 on a user data flag) to an opaque tail that returns: its
    // discard of exec = true is folded away, the alpha test holds on one way only
    {
        Flow flow;
        IR::IREmitter& top = flow.Block();
        const IR::U1 opaque = top.IEqual(top.GetUserData(IR::ScalarReg::S4), top.Imm32(0u));
        flow.If(top, opaque);
        flow.Block();
        flow.Return();
        flow.EndIf();
        IR::IREmitter& tail = flow.Block();
        DiscardUnless(tail, tail.FPGreaterThanEqual(Alpha(tail), tail.Imm32(0.5f)));
        flow.Return();
        const Cutout c = flow.Analyze();
        assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::ControlFlow);
    }
    // the same flag around the alpha tail
    {
        Flow flow;
        IR::IREmitter& top = flow.Block();
        const IR::U1 tested = top.INotEqual(top.GetUserData(IR::ScalarReg::S4), top.Imm32(0u));
        flow.If(top, tested);
        IR::IREmitter& body = flow.Block();
        DiscardUnless(body, body.FPGreaterThanEqual(Alpha(body), body.Imm32(0.5f)));
        flow.EndIf();
        flow.Block();
        flow.Return();
        const Cutout c = flow.Analyze();
        assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::ControlFlow);
    }
    // an unconditional discard in a branch the test does not decide
    {
        Flow flow;
        IR::IREmitter& top = flow.Block();
        const IR::U1 keep = top.FPGreaterThanEqual(Alpha(top), top.Imm32(0.5f));
        DiscardUnless(top, keep);
        flow.If(top, top.FPLessThan(top.GetAttribute(IR::Attribute::Param0, 0), top.Imm32(0.0f)));
        flow.Block().Discard();
        flow.EndIf();
        flow.Block();
        flow.Return();
        const Cutout c = flow.Analyze();
        assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::BranchDiscard);
    }
    // the v_cmpx skipped by a uniform branch: exec at the export a phi of true and the test
    {
        Flow flow;
        IR::IREmitter& top = flow.Block();
        const IR::U1 keep = top.FPGreaterThanEqual(Alpha(top), top.Imm32(0.5f));
        IR::IREmitter& tail = flow.Block();
        IR::Block& tail_block = flow.blocks.back();
        IR::Inst* phi = &*tail_block.PrependNewInst(tail_block.begin(), IR::Opcode::Phi, {});
        phi->SetFlags(IR::Type::U1);
        phi->AddPhiOperand(&flow.blocks.front(), keep);
        phi->AddPhiOperand(&tail_block, tail.Imm1(true));
        DiscardUnless(tail, IR::U1{IR::Value{phi}});
        flow.Return();
        const Cutout c = flow.Analyze();
        assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::ControlFlow);
    }
}

void CheckCost() {
    // x_{i+1} = x_i + x_i, 40 levels (deeper than the walk goes) and 26, and LogicalAnd(t, t) 24
    // levels (2^24 ways down without the memo): each value is walked once
    const auto start = std::chrono::steady_clock::now();
    Cutout c = Analyze([](IR::IREmitter& ir) {
        IR::F32 x = ir.GetAttribute(IR::Attribute::Param0, 0);
        for (u32 i = 0; i < 40; ++i) {
            x = ir.FPAdd(x, x);
        }
        DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), x));
    });
    assert(c.verdict == Cutout::Verdict::Other);
    c = Analyze([](IR::IREmitter& ir) {
        IR::F32 x = ir.GetAttribute(IR::Attribute::Param0, 0);
        for (u32 i = 0; i < 26; ++i) { // the review's case: 671 ms without the memo
            x = ir.FPAdd(x, x);
        }
        DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), x));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::VaryingRef);
    c = Analyze([](IR::IREmitter& ir) {
        IR::U1 keep = ir.FPGreaterThanEqual(Alpha(ir), ir.Imm32(0.5f));
        for (u32 i = 0; i < 24; ++i) { // within the depth the walk takes apart (32)
            keep = ir.LogicalAnd(keep, keep);
        }
        DiscardUnless(ir, keep);
    });
    assert(c.verdict == Cutout::Verdict::Matched);
    const double ms =
        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
    std::printf("rt-card-alpha-test: reused values analysed in %.2f ms\n", ms);
    assert(ms < 200.0);
}

void CheckNotMatched() {
    // no discard
    Cutout c = Analyze([](IR::IREmitter& ir) { (void)Alpha(ir); });
    assert(c.verdict == Cutout::Verdict::NoDiscard);

    // the clip distance emulation's discard alone
    c = Analyze(
        [](IR::IREmitter& ir) {
            ir.Discard(ir.FPLessThan(ir.GetAttribute(IR::Attribute::Param0 + 2, 0), ir.Imm32(0.0f)));
        },
        true);
    assert(c.verdict == Cutout::Verdict::NoDiscard);

    // ... and beside an alpha test
    c = Analyze(
        [](IR::IREmitter& ir) {
            ir.Discard(ir.FPLessThan(ir.GetAttribute(IR::Attribute::Param0 + 2, 0), ir.Imm32(0.0f)));
            DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), ir.Imm32(0.5f)));
        },
        true);
    assert(c.verdict == Cutout::Verdict::Matched && c.other_terms == 0);

    // a varying alone
    c = Analyze([](IR::IREmitter& ir) {
        DiscardUnless(ir, ir.FPGreaterThan(ir.GetAttribute(IR::Attribute::Param0, 3), ir.Imm32(0.0f)));
    });
    assert(c.verdict == Cutout::Verdict::NotTexture);

    // alpha times the vertex colour's: (r50b) accepted once, so twice is a varying factor
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a = ir.FPMul(Alpha(ir), ir.GetAttribute(IR::Attribute::Param0, 3));
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.alpha_input == 0 && c.alpha_comp == 3);
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a = ir.FPMul(ir.FPMul(Alpha(ir), ir.GetAttribute(IR::Attribute::Param0, 3)),
                                   ir.GetAttribute(IR::Attribute::Param0, 2));
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::VaryingFactor);
    // ... and alpha plus a varying, times another
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a = ir.FPMul(ir.FPAdd(Alpha(ir), ir.Imm32(0.25f)),
                                   ir.GetAttribute(IR::Attribute::Param0, 3));
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::VaryingFactor);

    // alpha compared with a varying
    c = Analyze([](IR::IREmitter& ir) {
        DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), ir.GetAttribute(IR::Attribute::Param0, 3)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::VaryingRef);

    // two textures' alphas in one test, and in two tests
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a = ir.FPMul(Alpha(ir, 0), Alpha(ir, 1));
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::SeveralTextures);
    c = Analyze([](IR::IREmitter& ir) {
        DiscardUnless(ir, ir.LogicalAnd(ir.FPGreaterThanEqual(Alpha(ir, 0), ir.Imm32(0.5f)),
                                        ir.FPGreaterThanEqual(Alpha(ir, 1), ir.Imm32(0.5f))));
    });
    assert(c.verdict == Cutout::Verdict::SeveralTextures);

    // an alpha test and a dither against a second texture's noise and a varying
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 noise{ir.CompositeExtract(
            Sample(ir, 1, ir.GetAttribute(Uv, 0), ir.GetAttribute(Uv, 1)), 0)};
        DiscardUnless(ir, ir.LogicalAnd(ir.FPGreaterThanEqual(Alpha(ir, 0), ir.Imm32(0.5f)),
                                        ir.FPLessThan(noise, ir.GetAttribute(IR::Attribute::Param0, 3))));
    });
    assert(c.verdict == Cutout::Verdict::SeveralTextures);

    // two channels of one sample
    c = Analyze([](IR::IREmitter& ir) {
        const IR::Value texel = Sample(ir, 0, ir.GetAttribute(Uv, 0), ir.GetAttribute(Uv, 1));
        const IR::F32 a = ir.FPMul(IR::F32{ir.CompositeExtract(texel, 0)},
                                   IR::F32{ir.CompositeExtract(texel, 3)});
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::TwoChannels);

    // alpha - fade >= 0 is alpha >= fade: a varying reference
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a = ir.FPSub(Alpha(ir), ir.GetAttribute(IR::Attribute::Param0, 3));
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.0f)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::VaryingRef);

    // V_CNDMASK_B32 of a fade: Select(fade, 0, alpha * 1.5) is no V_MUL_LEGACY
    c = Analyze([](IR::IREmitter& ir) {
        const IR::U1 fade = ir.FPGreaterThan(ir.GetAttribute(IR::Attribute::Param0, 2),
                                             ir.BitCast<IR::F32>(ir.GetUserData(IR::ScalarReg::S5)));
        const IR::F32 a{ir.Select(fade, ir.Imm32(0.0f), ir.FPMul(Alpha(ir), ir.Imm32(1.5f)))};
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::Computed);

    // either of two tests keeps the pixel
    c = Analyze([](IR::IREmitter& ir) {
        DiscardUnless(ir, ir.LogicalOr(ir.FPGreaterThanEqual(Alpha(ir), ir.Imm32(0.5f)),
                                       ir.FPLessThan(ir.GetAttribute(IR::Attribute::Param0, 3),
                                                     ir.Imm32(0.0f))));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::Disjunction);

    // an unconditional discard (in a branch)
    c = Analyze([](IR::IREmitter& ir) {
        (void)Alpha(ir);
        ir.Discard();
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::BranchDiscard);

    // the alpha scaled by a dword from memory
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 k = ir.BitCast<IR::F32>(ir.GetUserData(IR::ScalarReg::S6));
        DiscardUnless(ir, ir.FPGreaterThanEqual(ir.FPMul(Alpha(ir), k), ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::ConstantScale);
}

/// The alpha's T# as the compiling draw's flat user data hold it (8 dwords, and an r128 one of 4):
/// the view lane .w reads the stored red channel of a one-channel format.
void CheckTsharp() {
    for (const bool r128 : {false, true}) {
        Common::ObjectPool<IR::Inst> pool;
        IR::Block block(pool);
        IR::IREmitter ir(block);
        DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), ir.Imm32(0.5f)));
        Info info{};
        info.sw_stage = SwStage::Fragment;
        AmdGpu::Image tsharp{};
        tsharp.type = u64(AmdGpu::ImageType::Color2D);
        tsharp.dst_sel_w = u64(AmdGpu::CompSwizzle::Red);
        tsharp.data_format = 1;
        info.flattened_ud_buf.assign(16, 0u);
        std::memcpy(info.flattened_ud_buf.data() + 4, &tsharp, sizeof(tsharp));
        ImageResource image{};
        image.is_r128 = r128;
        image.sharp_fetch.offsets.fill(UNKNOWN_LOCATION);
        for (u32 i = 0; i < (r128 ? 4u : 8u); ++i) {
            image.sharp_fetch.offsets[i] = SharpLocation(4 + i);
            image.sharp_fetch.load_mask |= u8(1u << i);
        }
        info.images.push_back(image);
        RuntimeInfo runtime_info{};
        runtime_info.Initialize(HwStage::Fragment, SwStage::Fragment);
        runtime_info.hw.fs.num_inputs = 2;
        IR::Program program(info);
        program.blocks.push_back(&block);
        info.cutout = Optimization::AnalyzeCutout(program, runtime_info);
        const Cutout& c = info.cutout;
        assert(c.verdict == Cutout::Verdict::Matched && c.channel == 3);
        assert(c.stored == u8(AmdGpu::CompSwizzle::Red) && c.data_format == 1);
        const std::string line = Optimization::CutoutLine(info, runtime_info);
        assert(line.find("image 0 (T# flat 4; .w reads r, format 1) sampler 1") != std::string::npos);
    }
}

constexpr IR::Attribute Instance = IR::Attribute::Param0;
constexpr IR::Attribute Colour = IR::Attribute::Param0 + 2;
constexpr IR::Attribute Position = IR::Attribute::Param0 + 3;

/// The game's foliage, hair and cloth alpha test (r50_spv: dbeccd9c and the others), as the
/// translator leaves it: discarded where cb3[20] > cb3[21] * (D.w - 0.5) + A or A * fade == 0,
/// A = T.w * vertex colour.w, T at uv * cb1[0,1] + cb1[2,3] (V_MAD: FPAdd(FPMul)), D (the
/// camera pass's dither) at 0.25 * cb2[4|5] * (+-0.5 * pos.xy / pos.w + 0.5), the fade a buffer
/// load. The sun shadow pass form (92852ef3, 9ce84451): cb3[21] * -0.5, no D.
struct GameForm {
    bool dither = true;
    bool vertex_alpha = true;
    bool fade = true;
    bool manual_position = false; ///< pos interpolated by hand (pervertexEXT, 1c3953c6)
    bool manual_colour = true;    ///< the colour interpolated by hand (dbeccd9c)
    bool dither_at_uv = false;    ///< D at a plain input: not a dither
    bool dither_saturated = false;
    bool dither_tested = false;   ///< D in a second term too
    bool third_dword = false;     ///< + cb3[22] in the reference
    bool fade_textured = false;   ///< the fade a texture's
    bool uv_scaled_twice = false; ///< uv * (2 * cb1[0]): a scale the record cannot name
    bool colour_first = false;    ///< 6720ae0d: A = colour.w * T.w, D sampled before T,
                                  ///< fma(0.5, x * (1 / w), 0.5)
    // (r50b repair) shapes of the reviews
    enum class Fade : u8 { Buffer, Input, Computed };
    Fade fade_kind = Fade::Buffer; ///< the fade a buffer load, an input, saturate(an input)
    enum class DitherK : u8 { Dword, PlusImm, TwoDwords };
    DitherK dither_k = DitherK::Dword; ///< cb3[21], cb3[21] + 0.1, (cb3[21] + cb3[22]) (no -0.5)
    enum class Zero : u8 { Alpha, OtherChannel, OtherSample, Offset, Dither };
    Zero zero = Zero::Alpha;      ///< the nonzero term's P: A * fade, T.x * fade, S2.w * fade,
                                  ///< (A + 0.1) * fade, D.w
    bool fragcoord_dither = false; ///< D at FragCoord.xy * 0.25
    bool dither_z = false;        ///< D at (pos.z / pos.w, pos.z / pos.w)
    bool dither_swapped = false;  ///< D at (pos.y / pos.w, pos.x / pos.w)
    bool colour_vertex0 = false;  ///< the colour GetAttribute(colour, 3, 0) of a per-vertex input
    bool colour_nopersp = false;  ///< the colour interpolated by hand, no-perspective barycentrics
    u32 dither_tsharp = 0;        ///< the dither's T# in the flat user data, this size (0: none)
};

IR::F32 Cb(IR::IREmitter& ir, u32 buffer, u32 dword) {
    return ir.BitCast<IR::F32>(ir.ReadConstBuffer(ir.Imm32(buffer), ir.Imm32(dword), {}));
}

IR::F32 Interpolated(IR::IREmitter& ir, IR::Attribute attr, u32 comp,
                     IR::Attribute bary = IR::Attribute::BaryCoordSmooth) {
    const IR::F32 i = ir.GetAttribute(bary, 0);
    const IR::F32 j = ir.GetAttribute(bary, 1);
    const IR::F32 p0 = ir.GetAttribute(attr, comp, 0);
    const IR::F32 p1 = ir.GetAttribute(attr, comp, 1);
    const IR::F32 p2 = ir.GetAttribute(attr, comp, 2);
    return IR::F32{ir.FPFma(ir.FPSub(p2, p0), j, IR::F32{ir.FPFma(ir.FPSub(p1, p0), i, p0)})};
}

void GameTest(IR::IREmitter& ir, const GameForm& f) {
    const auto pos = [&](u32 comp) {
        return f.manual_position ? Interpolated(ir, Position, comp) : ir.GetAttribute(Position, comp);
    };
    IR::F32 dw{};
    const auto dither = [&] {
        if (f.dither_at_uv) {
            return IR::F32{ir.CompositeExtract(
                Sample(ir, 1, ir.GetAttribute(Uv, 2), ir.GetAttribute(Uv, 3)), 3)};
        }
        if (f.fragcoord_dither) {
            const auto at = [&](u32 comp) {
                return IR::F32{ir.FPMul(ir.GetAttribute(IR::Attribute::FragCoord, comp),
                                        ir.Imm32(0.25f))};
            };
            return IR::F32{ir.CompositeExtract(Sample(ir, 1, at(0), at(1)), 3)};
        }
        const IR::F32 rcp{ir.FPRecip(pos(3))};
        const auto screen = [&](u32 comp, f32 half, u32 dword) {
            const IR::F32 d =
                f.colour_first
                    ? IR::F32{ir.FPFma(ir.Imm32(half), ir.FPMul(pos(comp), rcp), ir.Imm32(0.5f))}
                    : IR::F32{ir.FPFma(ir.FPMul(ir.Imm32(half), pos(comp)), rcp, ir.Imm32(0.5f))};
            return ir.FPMul(ir.Imm32(0.25f), ir.FPMul(Cb(ir, 2, dword), d));
        };
        const u32 cu = f.dither_z ? 2 : f.dither_swapped ? 1 : 0;
        const u32 cv = f.dither_z ? 2 : f.dither_swapped ? 0 : 1;
        return IR::F32{
            ir.CompositeExtract(Sample(ir, 1, screen(cu, 0.5f, 4), screen(cv, -0.5f, 5)), 3)};
    };
    if (f.dither && f.colour_first) {
        dw = dither();
    }
    const IR::F32 scale_u =
        f.uv_scaled_twice ? IR::F32{ir.FPMul(ir.Imm32(2.0f), Cb(ir, 1, 0))} : Cb(ir, 1, 0);
    const IR::F32 u = ir.FPAdd(ir.FPMul(ir.GetAttribute(Uv, 0), scale_u), Cb(ir, 1, 2));
    const IR::F32 v = ir.FPAdd(ir.FPMul(ir.GetAttribute(Uv, 1), Cb(ir, 1, 1)), Cb(ir, 1, 3));
    const IR::Value texel = Sample(ir, 0, u, v);
    const IR::F32 tw{ir.CompositeExtract(texel, 3)};
    IR::F32 a = tw;
    if (f.vertex_alpha) {
        const IR::F32 colour =
            f.colour_vertex0   ? ir.GetAttribute(Colour, 3, 0)
            : f.colour_nopersp ? Interpolated(ir, Colour, 3, IR::Attribute::BaryCoordNoPersp)
            : f.manual_colour  ? Interpolated(ir, Colour, 3)
                               : ir.GetAttribute(Colour, 3);
        a = f.colour_first ? ir.FPMul(colour, tw) : ir.FPMul(tw, colour);
    }
    if (f.dither && !f.colour_first) {
        dw = dither();
    }
    IR::F32 k = Cb(ir, 3, 21);
    if (f.dither_k == GameForm::DitherK::PlusImm) {
        k = ir.FPAdd(k, ir.Imm32(0.1f));
    } else if (f.dither_k == GameForm::DitherK::TwoDwords) {
        k = ir.FPAdd(k, Cb(ir, 3, 22));
    }
    IR::F32 moved = ir.FPMul(k, ir.Imm32(-0.5f));
    if (f.dither) {
        moved = f.dither_k == GameForm::DitherK::TwoDwords
                    ? IR::F32{ir.FPMul(k, dw)}
                    : IR::F32{ir.FPMul(k, ir.FPAdd(ir.Imm32(-0.5f), dw))};
    }
    if (f.dither_saturated) {
        moved = ir.FPMul(Cb(ir, 3, 21), ir.FPSaturate(ir.FPAdd(ir.Imm32(-0.5f), dw)));
    }
    if (f.third_dword) {
        moved = ir.FPAdd(moved, Cb(ir, 3, 22));
    }
    const IR::U1 cut = ir.FPGreaterThan(Cb(ir, 3, 20), ir.FPAdd(moved, a));
    IR::F32 p = a;
    switch (f.zero) {
    case GameForm::Zero::OtherChannel:
        p = IR::F32{ir.CompositeExtract(texel, 0)};
        break;
    case GameForm::Zero::OtherSample:
        p = IR::F32{ir.CompositeExtract(
            Sample(ir, 2, ir.GetAttribute(Uv, 0), ir.GetAttribute(Uv, 1)), 3)};
        break;
    case GameForm::Zero::Offset:
        p = ir.FPAdd(a, ir.Imm32(0.1f));
        break;
    case GameForm::Zero::Dither:
        p = dw;
        break;
    default:
        break;
    }
    if (f.fade && f.zero != GameForm::Zero::Dither) {
        const IR::Value address = ir.IMul(
            ir.ConvertFToU(32, Interpolated(ir, Instance, 3)), ir.Imm32(13u));
        IR::F32 fade = ir.BitCast<IR::F32>(IR::U32{ir.LoadBufferU32(1, ir.Imm32(4u), address, {})});
        if (f.fade_textured) {
            fade = IR::F32{ir.CompositeExtract(
                Sample(ir, 2, ir.GetAttribute(Uv, 0), ir.GetAttribute(Uv, 1)), 0)};
        } else if (f.fade_kind == GameForm::Fade::Input) {
            fade = ir.GetAttribute(Uv, 2);
        } else if (f.fade_kind == GameForm::Fade::Computed) {
            fade = ir.FPSaturate(ir.GetAttribute(Uv, 2));
        }
        p = ir.FPMul(p, fade);
    }
    IR::U1 discard = ir.LogicalOr(cut, ir.FPEqual(p, ir.Imm32(0.0f)));
    if (f.dither_tested) {
        discard = ir.LogicalOr(discard, ir.FPLessThan(dw, ir.Imm32(0.1f)));
    }
    DiscardUnless(ir, ir.LogicalNot(discard));
}

/// GameTest analysed with the game's inputs: instance id (vs out 2), uv (3), colour (4),
/// position (5).
/// The game's Info: how its inputs are interpolated as the translator and
/// HardwareInterpolationPass leave them (the uv smooth, the instance id per vertex, the colour
/// and position per vertex where interpolated by hand), and with f.dither_tsharp the dither's T#
/// (image 1) in the flat user data. The alpha's T# (image 0) is not known.
void GameInfo(const GameForm& f, Info& info, RuntimeInfo& runtime_info) {
    runtime_info.hw.fs.num_inputs = 4;
    for (u32 i = 0; i < 4; ++i) {
        runtime_info.hw.fs.inputs[i].param_index = u8(i + 2);
    }
    const auto put = [&info](IR::Attribute attr, Qualifier q) {
        info.fs_interpolation[u32(attr) - u32(IR::Attribute::Param0)] = {q, Qualifier::None};
    };
    put(Instance, Qualifier::PerVertex);
    put(Uv, Qualifier::Smooth);
    put(Colour, f.manual_colour || f.colour_vertex0 || f.colour_nopersp ? Qualifier::PerVertex
                                                                        : Qualifier::Smooth);
    put(Position, f.manual_position ? Qualifier::PerVertex : Qualifier::Smooth);
    if (f.dither_tsharp != 0) {
        ImageResource unknown{};
        unknown.sharp_fetch.offsets.fill(UNKNOWN_LOCATION);
        info.images.push_back(unknown);
        AmdGpu::Image tsharp{};
        tsharp.type = u64(AmdGpu::ImageType::Color2D);
        tsharp.width = f.dither_tsharp - 1;
        tsharp.height = f.dither_tsharp - 1;
        tsharp.dst_sel_w = u64(AmdGpu::CompSwizzle::Alpha);
        info.flattened_ud_buf.assign(16, 0u);
        std::memcpy(info.flattened_ud_buf.data() + 4, &tsharp, sizeof(tsharp));
        ImageResource dither{};
        dither.sharp_fetch.offsets.fill(UNKNOWN_LOCATION);
        for (u32 i = 0; i < 8; ++i) {
            dither.sharp_fetch.offsets[i] = SharpLocation(4 + i);
            dither.sharp_fetch.load_mask |= u8(1u << i);
        }
        info.images.push_back(dither);
    }
}

/// GameTest analysed with the game's inputs: instance id (vs out 2), uv (3), colour (4),
/// position (5).
Cutout AnalyzeGame(const GameForm& f, std::string* line = nullptr) {
    return AnalyzeWith(
        [&f](Info& info, RuntimeInfo& runtime_info) {
            info.pgm_hash = 0xdbeccd9c;
            GameInfo(f, info, runtime_info);
        },
        [&f](IR::IREmitter& ir) { GameTest(ir, f); }, line);
}

/// GameTest through CutoutAnalysisPass (the map, the counts and the per-shader line).
void PassGame(const GameForm& f, u64 pgm_hash) {
    Common::ObjectPool<IR::Inst> pool;
    IR::Block block(pool);
    IR::IREmitter ir(block);
    Info info{};
    info.sw_stage = SwStage::Fragment;
    info.pgm_hash = pgm_hash;
    RuntimeInfo runtime_info{};
    runtime_info.Initialize(HwStage::Fragment, SwStage::Fragment);
    GameInfo(f, info, runtime_info);
    GameTest(ir, f);
    IR::Program program(info);
    program.blocks.push_back(&block);
    Optimization::CutoutAnalysisPass(program, runtime_info);
}

/// The record of the game's test: alpha >= cb3[20] + 0.5 cb3[21] (- cb3[21] D), the uv's dwords.
void CheckGameRecord(const Cutout& c, bool dither, bool vertex_alpha, u32 ignored) {
    assert(c.verdict == Cutout::Verdict::Matched && c.detail == Cutout::Detail::None);
    assert(c.op == Cutout::Op::GreaterEqual && c.image == 0 && c.channel == 3 && c.ref == 0.0f);
    assert(c.ref_kind == Cutout::Ref::ConstBuffer && c.ref_buffer == 3 && c.ref_dword == 20);
    assert(c.ref_scale == 1.0f && c.ref2_kind == Cutout::Ref::ConstBuffer && c.ref2_buffer == 3);
    assert(c.ref2_dword == 21 && c.ref2_scale == 0.5f);
    assert(c.dither == dither);
    if (dither) {
        assert(c.dither_image == 1 && c.dither_channel == 3 && c.dither_scale == -1.0f);
        assert(c.dither_kind == Cutout::Ref::ConstBuffer && c.dither_buffer == 3);
        assert(c.dither_dword == 21);
    }
    assert(vertex_alpha ? c.alpha_input == 2 && c.alpha_comp == 3
                        : c.alpha_input == Cutout::NoInput);
    assert(c.nonzero && c.ignored_factor_terms == ignored && c.other_terms == 0);
    // (r50b repair) the game's ignored factor is its per-instance fade, a buffer load
    assert(c.ignored_kinds == (ignored != 0 ? Cutout::IgnoredBuffer : 0));
    assert(c.input == 1 && c.comp_u == 0 && c.comp_v == 1 && c.uv_by_constant && !c.uv_unrecorded);
    assert(c.uv_kind == Cutout::Ref::ConstBuffer && c.uv_buffer == 1);
    assert(c.uv_scale_dword == (std::array<u16, 2>{0, 1}));
    assert(c.uv_offset_dword == (std::array<u16, 2>{2, 3}));
    assert(c.uv_scale == (std::array{0.0f, 0.0f}) && c.uv_offset == (std::array{0.0f, 0.0f}));
    assert(c.num_inputs == 4 && c.input_default_mask == 0 && c.input_flat_mask == 0);
    assert(!c.RepeatableFromRecord() && c.RepeatableWithConstants());
}

/// (r50b E1-E5) the game's forms, and the shapes next to them that must stay refused.
void CheckGameForms() {
    using Fade = GameForm::Fade;
    using Zero = GameForm::Zero;
    std::string line;
    // dbeccd9c: the camera pass, dithered, the colour interpolated by hand, pos by the hardware
    Cutout c = AnalyzeGame({}, &line);
    CheckGameRecord(c, true, true, 1);
    std::printf("%s\n", line.c_str());
    assert(line.size() < 400);
    assert(line == "Cut-out pixel shader 00000000dbeccd9c (r50): match (dithered, x an input, "
                   "nonzero), image 0 sampler 1, .w*in2.w (vs out 4) >= cb3[20]+0.5*cb3[21], "
                   "dither -1*cb3[21]*image1.w taken as 0, uv in1.xy (vs out 3) "
                   "*cb1[0,1]+cb1[2,3], 1 factors of the nonzero term ignored (a buffer load)");
    // 1c3953c6: pos interpolated by hand too (pervertexEXT)
    c = AnalyzeGame({.manual_position = true});
    CheckGameRecord(c, true, true, 1);
    // 0f54e5f9 and the others: the colour by the hardware
    c = AnalyzeGame({.manual_colour = false});
    CheckGameRecord(c, true, true, 1);
    // 6720ae0d: colour.w * T.w, D sampled first, fma(0.5, x * (1 / w), 0.5), pos by hand
    c = AnalyzeGame({.manual_position = true, .colour_first = true});
    CheckGameRecord(c, true, true, 1);
    // 92852ef3: the sun shadow pass, cb3[21] * -0.5, no D, A == 0 alone
    c = AnalyzeGame({.dither = false, .fade = false}, &line);
    CheckGameRecord(c, false, true, 0);
    assert(line.find("match (x an input, nonzero)") != std::string::npos);
    // 9ce84451: no colour either
    c = AnalyzeGame({.dither = false, .vertex_alpha = false, .fade = false}, &line);
    CheckGameRecord(c, false, false, 0);
    assert(line.find("match (nonzero), image 0 sampler 1, .w >= cb3[20]+0.5*cb3[21], uv") !=
           std::string::npos);
    // the dither's T# known at the compile: a 4x4 noise matches, its size in the line
    c = AnalyzeGame({.dither_tsharp = 4}, &line);
    CheckGameRecord(c, true, true, 1);
    assert(c.dither_width == 4 && c.dither_height == 4 && c.image_count == 2);
    assert(line.find("dither -1*cb3[21]*image1.w (4x4) taken as 0") != std::string::npos);
    // (review 1, finding 10) a dither at FragCoord.xy, the usual form
    c = AnalyzeGame({.fragcoord_dither = true});
    CheckGameRecord(c, true, true, 1);

    // D at a plain input: a second texture as a dither would be, not screen space
    c = AnalyzeGame({.dither_at_uv = true}, &line);
    assert(c.verdict == Cutout::Verdict::SeveralTextures);
    assert(c.detail == Cutout::Detail::DitherNotScreen);
    assert(c.sample_count == 2 && c.samples_input == 2 && c.samples_screen == 0);
    assert(line.find("several textures (dither not a screen space noise), 2 samples: 2 at an "
                     "input, 0 screen space, 0 computed") != std::string::npos);
    // (review 1, finding 5) D at (z/w, z/w), at (y/w, x/w), and a 256x256 T#: not a screen noise
    for (const GameForm& f : {GameForm{.dither_z = true}, GameForm{.dither_swapped = true},
                              GameForm{.dither_tsharp = 256}}) {
        c = AnalyzeGame(f);
        assert(c.verdict == Cutout::Verdict::SeveralTextures);
        assert(c.detail == Cutout::Detail::DitherNotScreen && c.samples_screen == 0);
    }
    // ... a 64x64 one still is
    c = AnalyzeGame({.dither_tsharp = 64});
    CheckGameRecord(c, true, true, 1);
    // D through a saturate: not linear
    c = AnalyzeGame({.dither_saturated = true}, &line);
    assert(c.verdict == Cutout::Verdict::SeveralTextures && c.detail == Cutout::Detail::None);
    assert(c.sample_count == 2 && c.samples_input == 1 && c.samples_screen == 1);
    // (E1 c) D in a second main term: two main terms on two samples, several textures
    c = AnalyzeGame({.dither_tested = true});
    assert(c.verdict == Cutout::Verdict::SeveralTextures && c.detail == Cutout::Detail::None);
    // (E1 c) D in the nonzero term (D.w == 0): NonzeroFactors refuses it, several textures
    c = AnalyzeGame({.zero = Zero::Dither});
    assert(c.verdict == Cutout::Verdict::SeveralTextures && c.detail == Cutout::Detail::None);
    // (review 2, finding 3; E1 a) the dither's coefficient neither an immediate nor one dword
    c = AnalyzeGame({.dither_k = GameForm::DitherK::PlusImm});
    assert(c.verdict == Cutout::Verdict::SeveralTextures && c.detail == Cutout::Detail::None);
    c = AnalyzeGame({.dither_k = GameForm::DitherK::TwoDwords});
    assert(c.verdict == Cutout::Verdict::SeveralTextures && c.detail == Cutout::Detail::None);
    // three dwords in the reference
    c = AnalyzeGame({.third_dword = true});
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::TwoConstants);
    // the nonzero term's other factor reads a texture
    c = AnalyzeGame({.fade_textured = true});
    assert(c.verdict == Cutout::Verdict::SeveralTextures);
    // (review 2, finding 1; E4 leaf) the nonzero term on another channel, another sample, A + 0.1
    c = AnalyzeGame({.dither = false, .zero = Zero::OtherChannel});
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::Computed);
    c = AnalyzeGame({.zero = Zero::OtherChannel});
    assert(c.verdict == Cutout::Verdict::SeveralTextures);
    c = AnalyzeGame({.dither = false, .zero = Zero::OtherSample});
    assert(c.verdict == Cutout::Verdict::SeveralTextures);
    c = AnalyzeGame({.dither = false, .zero = Zero::Offset});
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::Computed);
    // (review 1, finding 7) a nonzero factor that is an input or computed: matched, recorded,
    // not repeatable with the draw's constants
    c = AnalyzeGame({.fade_kind = Fade::Input}, &line);
    assert(c.verdict == Cutout::Verdict::Matched && c.ignored_kinds == Cutout::IgnoredInput);
    assert(!c.RepeatableWithConstants());
    assert(line.find("1 factors of the nonzero term ignored (an input)") != std::string::npos);
    c = AnalyzeGame({.fade_kind = Fade::Computed});
    assert(c.verdict == Cutout::Verdict::Matched && c.ignored_kinds == Cutout::IgnoredComputed);
    assert(!c.RepeatableWithConstants());
    // (review 1, finding 3) the colour as vertex 0's value of a per-vertex input, or interpolated
    // without perspective: no input factor
    c = AnalyzeGame({.colour_vertex0 = true});
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::Computed);
    c = AnalyzeGame({.colour_nopersp = true});
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::Computed);
    // a coordinate scale of 2 * cb1[0]: matched, the record cannot name it
    c = AnalyzeGame({.uv_scaled_twice = true}, &line);
    assert(c.verdict == Cutout::Verdict::Matched && c.uv_by_constant && c.uv_unrecorded);
    assert(!c.RepeatableWithConstants() && c.uv_scale_dword[0] == Cutout::NoDword);
    assert(line.find(" +memory") != std::string::npos);

    // alpha != 0 alone: the r50 alpha test
    c = Analyze([](IR::IREmitter& ir) {
        DiscardUnless(ir, ir.LogicalNot(ir.FPEqual(Alpha(ir), ir.Imm32(0.0f))));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.op == Cutout::Op::NotEqual && !c.nonzero);
    // a screen space texture alone is the test's alpha (no dither)
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 rcp{ir.FPRecip(ir.GetAttribute(Position, 3))};
        const IR::F32 su = ir.FPMul(ir.GetAttribute(Position, 0), rcp);
        const IR::F32 sv = ir.FPMul(ir.GetAttribute(Position, 1), rcp);
        DiscardUnless(ir, ir.FPGreaterThanEqual(IR::F32{ir.CompositeExtract(Sample(ir, 0, su, sv), 3)},
                                                ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::UvNotInput && !c.dither);
    // a perspective divide by FPDiv32 is screen space too
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 w = ir.GetAttribute(Position, 3);
        const IR::F32 su{ir.FPDiv(ir.GetAttribute(Position, 0), w)};
        const IR::F32 sv{ir.FPDiv(ir.GetAttribute(Position, 1), w)};
        const IR::F32 d{ir.CompositeExtract(Sample(ir, 1, su, sv), 0)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(ir.FPAdd(Alpha(ir), d), ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.dither && c.dither_scale == -1.0f);
    assert(c.dither_dword == Cutout::NoDword && c.dither_channel == 0 && c.ref == 0.5f);
    // ... but not one input's x over another's w
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 w = ir.GetAttribute(Position, 3);
        const IR::F32 su{ir.FPDiv(ir.GetAttribute(Colour, 0), w)};
        const IR::F32 sv{ir.FPDiv(ir.GetAttribute(Colour, 1), w)};
        const IR::F32 d{ir.CompositeExtract(Sample(ir, 1, su, sv), 0)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(ir.FPAdd(Alpha(ir), d), ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::SeveralTextures && c.samples_screen == 0);
    // (review 2, finding 7 of review 1) a discard term beside the alpha test: matched, not
    // repeatable with the draw's constants
    c = Analyze([](IR::IREmitter& ir) {
        const IR::U1 fade = ir.FPLessThan(ir.GetAttribute(IR::Attribute::Param0, 2), ir.Imm32(1.0f));
        DiscardUnless(ir, ir.LogicalAnd(fade, ir.FPGreaterThanEqual(Alpha(ir), ir.Imm32(0.5f))));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.other_terms == 1);
    assert(c.RepeatableFromRecord() && !c.RepeatableWithConstants());
}

IR::F32 Tw(IR::IREmitter& ir) {
    return IR::F32{
        ir.CompositeExtract(Sample(ir, 0, ir.GetAttribute(Uv, 0), ir.GetAttribute(Uv, 1)), 3)};
}

/// (r50b repair) the first review's probes (r50b_rev/probe.cpp) and the clamps: shapes that
/// r50b matched with a record that loses part of the test, now refused.
void CheckReviewProbes() {
    const auto per_vertex_colour = [](Info& info, RuntimeInfo&) {
        info.fs_interpolation[u32(Colour) - u32(IR::Attribute::Param0)] = {Qualifier::PerVertex,
                                                                           Qualifier::None};
    };
    const auto none = [](Info&, RuntimeInfo&) {};
    // P1: alpha * saturate(colour.w) >= 0.5
    Cutout c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a = ir.FPMul(Tw(ir), ir.FPSaturate(ir.GetAttribute(Colour, 3)));
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::Clamped);
    // P2/P9: a mask at proj.xy / proj.w added linearly is a screen position in the IR; with its
    // T# known as 256x256 it is not taken as a dither (an unknown T# still is: not provable)
    const auto projected = [](IR::IREmitter& ir) {
        const IR::F32 rcp{ir.FPRecip(ir.GetAttribute(Position, 3))};
        const IR::F32 u{ir.FPMul(ir.GetAttribute(Position, 0), rcp)};
        const IR::F32 v{ir.FPMul(ir.GetAttribute(Position, 1), rcp)};
        const IR::F32 n{ir.CompositeExtract(Sample(ir, 1, u, v), 0)};
        const IR::F32 a = ir.FPAdd(Tw(ir), ir.FPMul(ir.Imm32(0.8f), ir.FPAdd(n, ir.Imm32(-0.5f))));
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    };
    c = AnalyzeWith(
        [](Info& info, RuntimeInfo& runtime_info) {
            GameInfo({.dither_tsharp = 256}, info, runtime_info);
        },
        projected);
    assert(c.verdict == Cutout::Verdict::SeveralTextures &&
           c.detail == Cutout::Detail::DitherNotScreen);
    c = AnalyzeWith(none, projected);
    assert(c.verdict == Cutout::Verdict::Matched && c.dither && c.dither_width == 0);
    // P3: (z/w, z/w)
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 rcp{ir.FPRecip(ir.GetAttribute(Position, 3))};
        const IR::F32 z{ir.FPMul(ir.GetAttribute(Position, 2), rcp)};
        const IR::F32 n{ir.CompositeExtract(Sample(ir, 1, z, z), 0)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(ir.FPAdd(Tw(ir), ir.FPMul(ir.Imm32(0.8f), n)),
                                                ir.Imm32(0.5f)));
    });
    assert(c.verdict == Cutout::Verdict::SeveralTextures &&
           c.detail == Cutout::Detail::DitherNotScreen);
    // P4: the nonzero term's other factor saturate(a varying): matched, not with constants
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a = Tw(ir);
        const IR::U1 cut = ir.FPLessThan(a, ir.Imm32(0.5f));
        const IR::F32 p = ir.FPMul(a, ir.FPSaturate(ir.GetAttribute(Position, 0)));
        DiscardUnless(ir, ir.LogicalNot(ir.LogicalOr(cut, ir.FPEqual(p, ir.Imm32(0.0f)))));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.nonzero);
    assert(c.ignored_kinds == Cutout::IgnoredComputed && !c.RepeatableWithConstants());
    // P5: vertex 0's colour of a per-vertex input (V_INTERP_MOV_F32 P0 with barycentrics)
    const auto vertex0 = [](IR::IREmitter& ir) {
        const IR::F32 a = ir.FPMul(Tw(ir), ir.GetAttribute(Colour, 3, 0));
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, ir.Imm32(0.5f)));
    };
    c = AnalyzeWith(per_vertex_colour, vertex0);
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::Computed);
    c = AnalyzeWith(none, vertex0); // the same read of a smooth input is its value
    assert(c.verdict == Cutout::Verdict::Matched && c.alpha_input == 2);
    // ... a flat or no-perspective one is not
    for (const Qualifier q : {Qualifier::Flat, Qualifier::NoPerspective}) {
        c = AnalyzeWith(
            [q](Info& info, RuntimeInfo&) {
                info.fs_interpolation[u32(Colour) - u32(IR::Attribute::Param0)] = {q,
                                                                                   Qualifier::None};
            },
            vertex0);
        assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::Computed);
    }
    // ... nor are coordinates read from a flat input
    c = AnalyzeWith(
        [](Info& info, RuntimeInfo&) {
            info.fs_interpolation[u32(Uv) - u32(IR::Attribute::Param0)] = {Qualifier::Flat,
                                                                           Qualifier::None};
        },
        [](IR::IREmitter& ir) { DiscardUnless(ir, ir.FPGreaterThanEqual(Tw(ir), ir.Imm32(0.5f))); });
    assert(c.verdict == Cutout::Verdict::UvNotInput && c.detail == Cutout::Detail::UvComputed);
    // P6: uv saturated after a memory affine
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 u = ir.FPSaturate(
            ir.FPAdd(ir.FPMul(ir.GetAttribute(Uv, 0), Cb(ir, 1, 0)), Cb(ir, 1, 2)));
        const IR::F32 v = ir.FPAdd(ir.FPMul(ir.GetAttribute(Uv, 1), Cb(ir, 1, 1)), Cb(ir, 1, 3));
        const IR::F32 a{ir.CompositeExtract(Sample(ir, 0, u, v), 3)};
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, Cb(ir, 3, 20)));
    });
    assert(c.verdict == Cutout::Verdict::UvNotInput && c.detail == Cutout::Detail::UvComputed);
    // P8: saturate(alpha * colour * 2) >= a reference from memory
    c = Analyze([](IR::IREmitter& ir) {
        const IR::F32 a = ir.FPSaturate(
            ir.FPMul(ir.FPMul(Tw(ir), ir.GetAttribute(Colour, 3)), ir.Imm32(2.0f)));
        DiscardUnless(ir, ir.FPGreaterThanEqual(a, Cb(ir, 3, 20)));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::Clamped);
    // clamps of a texel side alone: kept only where the clamp cannot change the test
    struct ClampCase {
        bool memory_ref;
        f32 ref;
        bool greater; ///< > (else >=)
        bool inside;  ///< the clamp under a further product
        bool negated; ///< -saturate(alpha) < ref
        bool matched;
    };
    for (const ClampCase k : {ClampCase{false, 1.0f, false, false, false, true},
                              ClampCase{false, 0.0f, true, false, false, true},
                              ClampCase{false, 0.0f, false, false, false, false},
                              ClampCase{false, 1.0f, true, false, false, false},
                              ClampCase{false, 1.5f, false, false, false, false},
                              ClampCase{true, 0.0f, false, false, false, false},
                              ClampCase{false, 0.5f, false, true, false, false},
                              ClampCase{false, 0.75f, false, true, false, false}, // sat + 0.25
                              ClampCase{false, 0.5f, false, false, true, false}}) {
        c = Analyze([k](IR::IREmitter& ir) {
            IR::F32 a = ir.FPSaturate(Tw(ir));
            if (k.inside) {
                a = ir.FPMul(a, ir.Imm32(2.0f));
            }
            if (k.inside && k.ref != 0.5f) {
                a = ir.FPAdd(IR::F32{ir.FPSaturate(Tw(ir))}, ir.Imm32(0.25f));
            }
            const IR::F32 ref = k.memory_ref ? Cb(ir, 3, 20) : ir.Imm32(k.ref);
            if (k.negated) {
                // -saturate(alpha) < 0.5: the clamp not outermost (0.5 is in its range)
                DiscardUnless(ir, ir.FPLessThan(ir.FPNeg(a), ref));
            } else {
                DiscardUnless(ir, k.greater ? ir.FPGreaterThan(a, ref) : ir.FPGreaterThanEqual(a, ref));
            }
        });
        assert(k.matched ? c.verdict == Cutout::Verdict::Matched
                         : c.verdict == Cutout::Verdict::Other &&
                               c.detail == Cutout::Detail::Clamped);
    }
    // a saturate of a dword as the reference is clamped too; of an immediate it is folded
    c = Analyze([](IR::IREmitter& ir) {
        DiscardUnless(ir, ir.FPGreaterThanEqual(Tw(ir), ir.FPSaturate(Cb(ir, 3, 20))));
    });
    assert(c.verdict == Cutout::Verdict::Other && c.detail == Cutout::Detail::Clamped);
    c = Analyze([](IR::IREmitter& ir) {
        DiscardUnless(ir, ir.FPGreaterThanEqual(Tw(ir), ir.FPClamp(ir.Imm32(1.5f), ir.Imm32(0.0f),
                                                                   ir.Imm32(1.0f))));
    });
    assert(c.verdict == Cutout::Verdict::Matched && c.ref == 1.0f);
}

/// (r50b E6) a draw is drawn by the record's permutation only with the same pixel shader inputs.
void CheckPermutation() {
    const Cutout c = AnalyzeGame({});
    assert(Optimization::CutoutSamePermutation(c, 4, 0, 0));
    assert(Optimization::CutoutSamePermutation(c, 4, 1u << 5, 1u << 7)); // inputs it has not
    assert(!Optimization::CutoutSamePermutation(c, 4, 1u << 2, 0));      // the colour a default
    assert(!Optimization::CutoutSamePermutation(c, 4, 0, 1u << 0));      // the instance id flat
    assert(!Optimization::CutoutSamePermutation(c, 3, 0, 0));
    // the record keeps what its compile saw
    const Cutout flat = AnalyzeWith(
        [](Info& info, RuntimeInfo& runtime_info) {
            GameInfo({}, info, runtime_info);
            runtime_info.hw.fs.inputs[0].is_flat = true;
            runtime_info.hw.fs.inputs[3].is_default = true;
        },
        [](IR::IREmitter& ir) { GameTest(ir, {}); });
    assert(flat.num_inputs == 4 && flat.input_flat_mask == 1u && flat.input_default_mask == 8u);
    assert(Optimization::CutoutSamePermutation(flat, 4, 8u, 1u));
    assert(!Optimization::CutoutSamePermutation(flat, 4, 0, 0));
}

/// (r50b E7) the draw-time line of the game's record.
void CheckConstantsLine() {
    const Cutout c = AnalyzeGame({});
    const auto dwords = Optimization::CutoutDwords(c);
    assert(dwords[0].kind == Cutout::Ref::ConstBuffer && dwords[0].buffer == 1 && dwords[0].dword == 0);
    assert(dwords[3].dword == 3 && dwords[4].buffer == 3 && dwords[4].dword == 20);
    assert(dwords[5].dword == 21 && dwords[6].dword == 21);
    const std::array<f32, 7> values{2.0f, 4.0f, 0.5f, 0.25f, 0.3f, 0.2f, 0.2f};
    const std::string line = Optimization::CutoutConstantsLine(
        0xdbeccd9c, c, values, 3, 4 | Optimization::CutoutFlatInput, 7,
        Optimization::CutoutConstants::CpuWritten, {4, 4});
    std::printf("%s\n", line.c_str());
    assert(line == "Cut-out constants 00000000dbeccd9c (r50b): uv (in1.xy*(2,4)+(0.5,0.25), vs out "
                   "3), ref 0.3 + 0.5*0.2 = 0.4, camera dither -0.2*image1.w (4x4) (taken as 0), "
                   "alpha factor in2.w (vs out 4, flat), stored channel a, CPU-written");
    const Cutout sun = AnalyzeGame({.dither = false, .vertex_alpha = false, .fade = false});
    std::array<f32, 7> unreadable{};
    unreadable.fill(std::nanf(""));
    const std::string none = Optimization::CutoutConstantsLine(
        0x9ce84451, sun, unreadable, -1, -1, 0xff, Optimization::CutoutConstants::GpuWritten,
        {0, 0});
    std::printf("%s\n", none.c_str());
    assert(none.find("uv (in1.xy*(nan,nan)+(nan,nan), default value), ref nan + 0.5*nan = nan, "
                     "no alpha factor, stored channel ?, GPU-written") != std::string::npos);
    const std::string in_place = Optimization::CutoutConstantsLine(
        0x9ce84451, sun, unreadable, 3, -1, 7, Optimization::CutoutConstants::InPlace, {0, 0});
    assert(in_place.find(", in place (a GPU write pending)") != std::string::npos);
}

/// The two 600-frame lines (the knob is set in main before anything reads it).
void CheckSummary() {
    Common::ObjectPool<IR::Inst> pool;
    IR::Block block(pool);
    IR::IREmitter ir(block);
    DiscardUnless(ir, ir.FPGreaterThanEqual(Alpha(ir), ir.Imm32(0.5f)));
    Info info{};
    info.sw_stage = SwStage::Fragment;
    info.pgm_hash = 0x1234;
    RuntimeInfo runtime_info{};
    runtime_info.Initialize(HwStage::Fragment, SwStage::Fragment);
    runtime_info.hw.fs.num_inputs = 2;
    IR::Program program(info);
    program.blocks.push_back(&block);
    assert(Optimization::CutoutAnalysisOn());
    assert(Optimization::CutoutCardsText().empty());
    Optimization::CutoutAnalysisPass(program, runtime_info);
    Optimization::CutoutAnalysisPass(program, runtime_info); // the same pgm_hash: counted once
    Optimization::NoteCutoutCacheRefusal();
    Optimization::NoteCutoutCard(0x1234, 0, Optimization::CutoutCardClass::Plant);
    Optimization::NoteCutoutCard(0x5678, 0x1234, Optimization::CutoutCardClass::SkinnedKept);
    const std::string summary = Optimization::CutoutSummaryText();
    assert(summary.find("1 pixel shaders compiled in play and analysed (1 since the last line; 1 "
                        "discarding cache records") != std::string::npos);
    assert(summary.find("of the 1 that discard 1 match") != std::string::npos);
    assert(Optimization::CutoutSummaryText().find("(0 since the last line") != std::string::npos);
    const std::string cards = Optimization::CutoutCardsText();
    // (r50b) the alpha >= 0.5 record names no memory dword: none to read, so not CPU-written
    assert(cards.find("plants (left out of lamp rays: a skeleton, no sun shadow pass draw) 1 [1 "
                      "match; 1 repeatable, 1 with constants; 1 match, 0 with CPU-written "
                      "constants on every draw, 1 with no memory constants]") != std::string::npos);
    assert(cards.find("kept whole: a skeleton (hair, cloth, characters) 1 [1 not analysed; 0 "
                      "repeatable, 0 with constants; 0 match, 0 with CPU-written constants on "
                      "every draw, 0 with no memory constants]") != std::string::npos);
    assert(cards.find("0000000000005678 (skeleton, kept; not analysed)") != std::string::npos);
    assert(summary.find("(r50b: 0 dithered, 0 times an input, 0 with a nonzero term, 0 with a "
                        "reference of two dwords; 1 repeatable with the draw's constants, 0 not, "
                        "for (a shader can count in several) 0 a coordinate scale or offset the "
                        "record cannot name, 0 a computed layer, 0 a texel offset, 0 other terms, "
                        "0 an ignored nonzero factor that is an input or computed)") !=
           std::string::npos);
    std::printf("%s\n%s\n", summary.c_str(), cards.c_str());

    // (r50b E6) the record by pgm_hash, for a cached program's Info
    const Cutout* found = Optimization::FindCutout(0x1234);
    assert(found && found->verdict == Cutout::Verdict::Matched && found->image_count == 0);
    assert(found->buffer_count == 0 && !Optimization::FindCutout(0x9999));

    // (r50b B4) the game's form (with constants) and one whose uv scale the record cannot name
    PassGame({}, 0x4321);
    PassGame({.uv_scaled_twice = true}, 0x4322);
    PassGame({.fade_kind = GameForm::Fade::Input}, 0x4323); // not with constants, for its fade
    Optimization::NoteCutoutCard(0x4321, 0, Optimization::CutoutCardClass::Static);
    const std::string totals = Optimization::CutoutSummaryText();
    std::printf("%s\n", totals.c_str());
    assert(totals.find("of the 4 that discard 4 match") != std::string::npos);
    assert(totals.find("(r50b: 3 dithered, 3 times an input, 3 with a nonzero term, 3 with a "
                       "reference of two dwords; 2 repeatable with the draw's constants, 2 not, "
                       "for (a shader can count in several) 1 a coordinate scale or offset the "
                       "record cannot name, 0 a computed layer, 0 a texel offset, 0 other terms, "
                       "1 an ignored nonzero factor that is an input or computed)") !=
           std::string::npos);
    const char* const no_draws = "left out, no skeleton 1 [1 match; 0 repeatable, 1 with "
                                 "constants; 1 match, 0 with CPU-written constants on every draw, "
                                 "0 with no memory constants]";
    assert(Optimization::CutoutCardsText().find(no_draws) != std::string::npos);
    // a draw of the record with no memory constants: nothing read, still not CPU-written
    assert(Optimization::NoteCutoutConstants(0x1234, Optimization::CutoutConstants::CpuWritten));
    assert(Optimization::CutoutCardsText().find(
               "1 [1 match; 1 repeatable, 1 with constants; 1 match, 0 with CPU-written constants "
               "on every draw, 1 with no memory constants]") != std::string::npos);

    // (r50b E7) every draw counted by its state; the first one not of another permutation prints
    using State = Optimization::CutoutConstants;
    assert(!Optimization::NoteCutoutConstants(0x4321, State::OtherPermutation));
    assert(Optimization::NoteCutoutConstants(0x4321, State::CpuWritten));
    assert(!Optimization::NoteCutoutConstants(0x4321, State::CpuWritten));
    std::string text = Optimization::CutoutCardsText();
    assert(text.find("left out, no skeleton 1 [1 match; 0 repeatable, 1 with constants; 1 match, "
                     "1 with CPU-written constants on every draw, 0 with no memory constants; 3 "
                     "draws: 2 CPU-written, 0 in place, 0 GPU-written, 0 unreadable, 1 another "
                     "permutation]") != std::string::npos);
    // one draw of it with a GPU-written dword: no longer CPU-written on every draw
    assert(!Optimization::NoteCutoutConstants(0x4321, State::GpuWritten));
    assert(!Optimization::NoteCutoutConstants(0x4321, State::InPlace));
    text = Optimization::CutoutCardsText();
    std::printf("%s\n", text.c_str());
    assert(text.find("1 match, 0 with CPU-written constants on every draw, 0 with no memory "
                     "constants; 5 draws: 2 CPU-written, 1 in place, 1 GPU-written, 0 unreadable, "
                     "1 another permutation]") != std::string::npos);
}

} // namespace

int main() {
#ifdef _WIN32
    _putenv_s("BB_RT_CARD_ALPHA_LOG", "1");
#else
    setenv("BB_RT_CARD_ALPHA_LOG", "1", 1);
#endif
    CheckMatched();
    CheckCoordinates();
    CheckNotMatched();
    CheckControlFlow();
    CheckTsharp();
    CheckCost();
    CheckGameForms();
    CheckReviewProbes();
    CheckPermutation();
    CheckConstantsLine();
    CheckSummary();
    std::printf("rt-card-alpha-test: ok (alpha tests, coordinates, shaders not matched, the "
                "game's forms, the reviews' probes)\n");
    return 0;
}
"""),
}

OLD_INFO_CUTOUT = r"""    /// bbport (r50_leaf-stage1): the alpha test of a pixel shader's discard, as the cut-out
    /// analysis read it (ir/passes/cutout_analysis.h). Filled only when the shader compiles with
    /// BB_RT_CARD_ALPHA_LOG=1; not in the cache record.
    struct Cutout {
        enum class Verdict : u8 {
            NotAnalysed,
            Matched,
            NoDiscard,
            NotTexture,     ///< no term of the discard reads a texture
            UvNotInput,     ///< the alpha test matched, its coordinates are not an input
            SeveralTextures,
            Other,
        };
        /// Why a test did not match (the first reason found).
        enum class Detail : u8 {
            None,
            BranchDiscard,   ///< a discard in a branch the alpha test does not decide
            ControlFlow,     ///< the test reaches a phi, or sits under a branch the test does not
                             ///< decide (a uniform switch, an early return, a loop)
            Disjunction,     ///< the discard is an OR of tests
            NotCompare,      ///< a term is not a float compare
            VaryingFactor,   ///< the alpha times a varying (vertex colour)
            VaryingRef,      ///< the alpha compared with (or offset by) a varying, or by a value
                             ///< made of varyings
            ConstantScale,   ///< the alpha scaled by a value from memory
            TwoConstants,    ///< two values from memory in one expression
            RefComputed,     ///< a value read from a dynamic address
            SampleKind,      ///< a depth compare, gather or texel load
            Computed,        ///< another operation on the way
            TwoTests,        ///< two terms of the discard test the same sample
            SeveralTextures,
            UvComputed,
            UvTwoInputs,     ///< u and v from two inputs
            TwoChannels,     ///< an alpha made of two channels of one sample
            Count,
        };
        enum class Op : u8 { Less, LessEqual, Greater, GreaterEqual, Equal, NotEqual };
        enum class Ref : u8 { Immediate, UserData, FlatUserData, ConstBuffer };
        /// The third coordinate (array layer, or w of a 3D image).
        enum class Layer : u8 { None, Immediate, Other };
        Verdict verdict{};
        Detail detail{};
        Op op{};         ///< the pixel is kept where alpha <op> reference
        Ref ref_kind{};  ///< where the dword of the reference is
        u8 image{};      ///< index in images of the alpha's texture
        u8 sampler{};    ///< index in samplers
        /// Component of the sample's result: a lane of the image VIEW, which applies the T#'s
        /// dst_sel (image_view.cpp), not the stored channel. `stored` is the stored channel that
        /// lane reads (AmdGpu::CompSwizzle: 0, 1, 4 r .. 7 a; 0xff not known) and `data_format`
        /// the T#'s format, both as the compiling draw's T# has them.
        u8 channel{};
        u8 stored = 0xff;
        u8 data_format{};
        u8 ref_buffer{}; ///< ConstBuffer: index in buffers
        u16 ref_dword{}; ///< UserData: the SGPR; FlatUserData, ConstBuffer: the dword
        f32 ref{};       ///< reference = ref + ref_scale * that dword (as a float)
        f32 ref_scale{};
        u8 input{};      ///< the coordinates' pixel shader input (ParamN)
        u8 comp_u{};
        u8 comp_v{};
        u8 other_terms{};      ///< terms of the discard beside the alpha test (fades, ...)
        u8 kill_blocks{};      ///< unconditional discards in branches only failing pixels reach
        bool uv_by_constant{}; ///< a scale or offset of the coordinates is read from memory
        bool texel_offset{};   ///< the sample has a texel offset
        Layer layer{};
        f32 layer_value{};     ///< Layer::Immediate: the layer
        std::array<f32, 2> uv_scale{1.0f, 1.0f}; ///< coordinate = input * scale + offset
        std::array<f32, 2> uv_offset{};          ///< (the immediate parts)

        /// Matched, and the record alone says how to repeat it: no coordinate scale or offset
        /// from memory, no computed layer, no texel offset.
        bool Repeatable() const {
            return verdict == Verdict::Matched && !uv_by_constant && !texel_offset &&
                   layer != Layer::Other;
        }
    };
    Cutout cutout{};
"""
INFO_CUTOUT = r"""    /// bbport (r50_leaf-stage1, r50b_leaf-matcher): the alpha test of a pixel shader's discard,
    /// as the cut-out analysis read it (ir/passes/cutout_analysis.h). Filled only when the shader
    /// compiles with BB_RT_CARD_ALPHA_LOG=1; not in the cache record.
    struct Cutout {
        enum class Verdict : u8 {
            NotAnalysed,
            Matched,
            NoDiscard,
            NotTexture,     ///< no term of the discard reads a texture
            UvNotInput,     ///< the alpha test matched, its coordinates are not an input
            SeveralTextures,
            Other,
        };
        /// Why a test did not match (the first reason found).
        enum class Detail : u8 {
            None,
            BranchDiscard,   ///< a discard in a branch the alpha test does not decide
            ControlFlow,     ///< the test reaches a phi, or sits under a branch the test does not
                             ///< decide (a uniform switch, an early return, a loop)
            Disjunction,     ///< the discard is an OR of tests
            NotCompare,      ///< a term is not a float compare
            VaryingFactor,   ///< the alpha times a varying beside the one accepted (r50b), or a
                             ///< varying times an alpha with an offset
            VaryingRef,      ///< the alpha compared with (or offset by) a varying, or by a value
                             ///< made of varyings
            ConstantScale,   ///< the alpha scaled by a value from memory
            TwoConstants,    ///< more than two values from memory in one sum, or a product of two
            RefComputed,     ///< a value read from a dynamic address
            SampleKind,      ///< a depth compare, gather or texel load
            Computed,        ///< another operation on the way
            TwoTests,        ///< two terms of the discard test the same sample
            SeveralTextures,
            UvComputed,
            UvTwoInputs,     ///< u and v from two inputs
            TwoChannels,     ///< an alpha made of two channels of one sample
            DitherNotScreen, ///< (r50b) a second texture enters the test as a dither would, but
                             ///< it is not sampled at a screen position (x of one input over
                             ///< its w as u, y over that w as v, or the pixel's FragCoord x, y),
                             ///< or its T# at the compile is larger than 64x64
            Clamped,         ///< (r50b) a saturate or clamp(0, 1) over anything but a texel
                             ///< side alone, or one whose reference is not an immediate inside
                             ///< the clamp's range (where the clamp changes the test)
            Count,
        };
        enum class Op : u8 { Less, LessEqual, Greater, GreaterEqual, Equal, NotEqual };
        enum class Ref : u8 { Immediate, UserData, FlatUserData, ConstBuffer };
        /// The third coordinate (array layer, or w of a 3D image).
        enum class Layer : u8 { None, Immediate, Other };
        /// A dword index of this record that names no dword (the value is an immediate).
        static constexpr u16 NoDword = 0xffff;
        /// alpha_input: no input factor on the alpha.
        static constexpr u8 NoInput = 0xff;
        /// ignored_kinds: what the ignored factors of the nonzero term are (bits).
        static constexpr u8 IgnoredBuffer = 1;   ///< a buffer load (LoadBuffer*: a fade)
        static constexpr u8 IgnoredDword = 2;    ///< an immediate or memory dwords
        static constexpr u8 IgnoredInput = 4;    ///< an input component
        static constexpr u8 IgnoredComputed = 8; ///< anything else
        Verdict verdict{};
        Detail detail{};
        Op op{};         ///< the pixel is kept where alpha <op> reference
        Ref ref_kind{};  ///< where the first dword of the reference is
        u8 image{};      ///< index in images of the alpha's texture
        u8 sampler{};    ///< index in samplers
        /// Component of the sample's result: a lane of the image VIEW, which applies the T#'s
        /// dst_sel (image_view.cpp), not the stored channel. `stored` is the stored channel that
        /// lane reads (AmdGpu::CompSwizzle: 0, 1, 4 r .. 7 a; 0xff not known) and `data_format`
        /// the T#'s format, both as the compiling draw's T# has them.
        u8 channel{};
        u8 stored = 0xff;
        u8 data_format{};
        u8 ref_buffer{}; ///< ConstBuffer: index in buffers
        u16 ref_dword{}; ///< UserData: the SGPR; FlatUserData, ConstBuffer: the dword
        /// reference = ref + ref_scale * (first dword) + ref2_scale * (second dword), each dword
        /// read as a float; in the camera pass also + dither_scale * (dither dword, or 1 for
        /// NoDword) * the dither texel (r50b), which this reference takes as 0 (the game's sun
        /// shadow pass form, so cb[20] + 0.5 * cb[21] for its material test)
        f32 ref{};
        f32 ref_scale{};
        Ref ref2_kind{};   ///< (r50b) the second dword of the reference (Immediate: none)
        u8 ref2_buffer{};
        u16 ref2_dword{};
        f32 ref2_scale{};
        u8 input{};      ///< the coordinates' pixel shader input (ParamN)
        u8 comp_u{};
        u8 comp_v{};
        /// (r50b) alpha = channel * this input's component (any smooth input: in the game's
        /// shaders a vertex colour's alpha, which nothing here checks), NoInput: the channel alone
        u8 alpha_input = NoInput;
        u8 alpha_comp{};
        u8 other_terms{};      ///< terms of the discard beside the alpha test (fades, ...)
        u8 kill_blocks{};      ///< unconditional discards in branches only failing pixels reach
        bool uv_by_constant{}; ///< a scale or offset of the coordinates is read from memory
        /// (r50b) one of them the record cannot name: not exactly one dword (a coefficient other
        /// than 1, a sum with an immediate, two dwords), or dwords of two buffers
        bool uv_unrecorded{};
        bool texel_offset{};   ///< the sample has a texel offset
        /// (r50b) the camera pass's dither: a second texture's channel the test adds linearly,
        /// sampled at one input's perspective divide (a screen space noise)
        bool dither{};
        /// (r50b) a term that keeps the pixel only where the alpha (times factors that read no
        /// texture, ignored here) is not 0
        bool nonzero{};
        u8 ignored_factor_terms{}; ///< (r50b) those factors (a per-instance fade, ...)
        u8 ignored_kinds{};        ///< (r50b) Ignored* bits: what they are
        Layer layer{};
        f32 layer_value{};     ///< Layer::Immediate: the layer
        std::array<f32, 2> uv_scale{1.0f, 1.0f}; ///< coordinate = input * scale + offset
        std::array<f32, 2> uv_offset{};          ///< (the immediate parts)
        /// (r50b) the memory dwords of the scale and offset (NoDword: the immediate above; a
        /// named one is exactly that dword, its immediate part 0), all of uv_kind in uv_buffer
        Ref uv_kind{};
        u8 uv_buffer{};
        std::array<u16, 2> uv_scale_dword{NoDword, NoDword};
        std::array<u16, 2> uv_offset_dword{NoDword, NoDword};
        /// (r50b) the dither: its image and view channel, and its coefficient in the reference
        /// (dither_scale * the dword of dither_kind, or dither_scale alone for NoDword)
        u8 dither_image{};
        u8 dither_channel{};
        Ref dither_kind{};
        u8 dither_buffer{};
        u16 dither_dword = NoDword;
        f32 dither_scale{};
        /// (r50b) the dither's T# size at the compile (0: not known)
        u16 dither_width{};
        u16 dither_height{};
        /// (r50b) the compiling program's images.size() and buffers.size(): a record found by
        /// pgm_hash (FindCutout) is used only for an Info with the same counts
        u8 image_count{};
        u8 buffer_count{};
        /// (r50b) the pixel shader inputs the analysis saw (RuntimeInfo, part of the permutation
        /// key): how many, and a bit per input that is a default value or flat shaded. A draw
        /// whose regs.ps_inputs differ is drawn by another permutation (CutoutSamePermutation).
        u8 num_inputs{};
        u32 input_default_mask{};
        u32 input_flat_mask{};
        /// (r50b) SeveralTextures: the samples the discard's terms read, and how many are sampled
        /// at an input (the r50 UV rule) and at one input's perspective divide (screen space);
        /// the rest are computed
        u8 sample_count{};
        u8 samples_input{};
        u8 samples_screen{};

        /// Matched, and the record alone says how to repeat it: no coordinate scale or offset
        /// from memory, no computed layer, no texel offset (r50's Repeatable()).
        bool RepeatableFromRecord() const {
            return verdict == Verdict::Matched && !uv_by_constant && !texel_offset &&
                   layer != Layer::Other;
        }
        /// (r50b) Matched, and repeatable once the draw's memory dwords the record names are
        /// read: no texel offset, no computed layer, every value from memory one named user
        /// data, flat user data or constant buffer dword (the reference's and the dither's
        /// always are; the coordinates' are when not uv_unrecorded), no discard term beside the
        /// alpha test (other_terms), and no ignored factor of the nonzero term that is an input
        /// or computed (a buffer load or a dword is ignored, as the game's sun shadow pass does).
        bool RepeatableWithConstants() const {
            return verdict == Verdict::Matched && !uv_unrecorded && !texel_offset &&
                   layer != Layer::Other && other_terms == 0 &&
                   (ignored_kinds & (IgnoredInput | IgnoredComputed)) == 0;
        }
    };
    Cutout cutout{};
"""
FX_HELPER = r"""namespace {
/// bbport (r50b_leaf-matcher): with BB_RT_CARD_ALPHA_LOG=1, every draw of a matched cut-out pixel
/// shader whose record holds RepeatableWithConstants() is counted by its memory dwords
/// (Shader::Optimization::CutoutConstants), and the first one of each pgm_hash prints the dwords'
/// values (the record's camera pass reference and coordinates, for a ray to repeat). A draw whose
/// pixel shader inputs are not the ones the record was analysed with is drawn by another
/// permutation: counted, nothing read. A dword is read only from the shader's own user data, or
/// from a guest constant buffer the shader does not write, at a valid V#, inside it and inside a
/// GPU mapping, in no region the GPU wrote (as the r17 hash below: such a page may be the GPU's
/// with BB_READBACKS=2, and a read fault here would wait for this thread; its CPU copy is stale
/// otherwise); one in such a region is not read (NaN), and marked GPU-written, or in place when
/// that range is bound in place (BB_GUEST_IN_PLACE: a write still pending).
void LogCutoutConstants(const AmdGpu::Regs& regs, const Shader::Info& ps,
                        Core::MemoryManager& memory, VideoCore::BufferCache& buffer_cache) {
    namespace Opt = Shader::Optimization;
    using Ref = Shader::Info::Cutout::Ref;
    using State = Opt::CutoutConstants;
    const Shader::Info::Cutout* cut = &ps.cutout;
    if (cut->verdict == Shader::Info::Cutout::Verdict::NotAnalysed) {
        // a program from the cache: the first compile's record
        cut = Opt::FindCutout(ps.pgm_hash);
        if (!cut || cut->image_count != ps.images.size() ||
            cut->buffer_count != ps.buffers.size()) {
            return;
        }
    }
    if (!cut->RepeatableWithConstants()) {
        return;
    }
    // (E6) the permutation: a draw gets permutation 0's Info (PipelineCache::GetProgram)
    u32 default_mask = 0, flat_mask = 0;
    for (u32 i = 0; i < regs.num_interp && i < 32 && i < regs.ps_inputs.size(); ++i) {
        default_mask |= regs.ps_inputs[i].use_default ? 1u << i : 0u;
        flat_mask |= regs.ps_inputs[i].flat_shade ? 1u << i : 0u;
    }
    if (!Opt::CutoutSamePermutation(*cut, regs.num_interp, default_mask, flat_mask)) {
        (void)Opt::NoteCutoutConstants(ps.pgm_hash, State::OtherPermutation);
        return;
    }
    const auto dwords = Opt::CutoutDwords(*cut);
    std::array<f32, 7> values{};
    values.fill(std::numeric_limits<f32>::quiet_NaN());
    State state = State::CpuWritten;
    const auto worse = [&state](State s) {
        state = u8(s) > u8(state) ? s : state;
    };
    const auto user_data = ps.UserData();
    const auto flat = ps.FlatUserData();
    for (size_t i = 0; i < dwords.size(); ++i) {
        const Opt::CutoutDword& d = dwords[i];
        if (d.kind == Ref::UserData || d.kind == Ref::FlatUserData) {
            const auto ud = d.kind == Ref::UserData ? user_data : flat;
            if (d.dword < ud.size()) {
                values[i] = std::bit_cast<f32>(ud[d.dword]);
            } else {
                worse(State::Unreadable);
            }
            continue;
        }
        if (d.kind != Ref::ConstBuffer) {
            continue;
        }
        if (d.buffer >= ps.buffers.size() || ps.buffers[d.buffer].IsSpecial()) {
            worse(State::Unreadable);
            continue;
        }
        if (ps.buffers[d.buffer].is_written) {
            worse(State::GpuWritten); // the shader's own writes
            continue;
        }
        const AmdGpu::Buffer sharp = ps.buffers[d.buffer].GetSharp(ps);
        const u64 offset = u64(d.dword) * 4;
        const VAddr address = sharp.base_address + offset;
        if (!sharp.Valid() || offset + 4 > sharp.GetSize() ||
            !memory.IsValidGpuMapping(address, 4) || memory.ClampRangeSize(address, 4) != 4) {
            worse(State::Unreadable);
            continue;
        }
        if (buffer_cache.IsRegionGpuModified(address, 4)) {
            worse(buffer_cache.IsInPlace(address, 4) ? State::InPlace : State::GpuWritten);
            continue; // not read
        }
        u32 raw = 0;
        std::memcpy(&raw, reinterpret_cast<const void*>(address), sizeof(raw));
        values[i] = std::bit_cast<f32>(raw);
    }
    if (!Opt::NoteCutoutConstants(ps.pgm_hash, state)) {
        return; // the line was printed for an earlier draw
    }
    const auto vs_out = [&regs](u32 input) {
        if (input >= regs.ps_inputs.size()) {
            return -1;
        }
        const AmdGpu::PsInputControl& control = regs.ps_inputs[input];
        if (control.use_default) {
            return -1;
        }
        return int(control.input_offset) | (control.flat_shade ? Opt::CutoutFlatInput : 0);
    };
    u8 stored = 0xff;
    if (cut->image < ps.images.size()) {
        const AmdGpu::Image image = ps.images[cut->image].GetSharp(ps);
        if (image.Valid()) {
            stored = u8(image.DstSelect().array[cut->channel & 3]);
        }
    }
    std::array<u32, 2> dither_size{};
    if (cut->dither && cut->dither_image < ps.images.size()) {
        const AmdGpu::Image image = ps.images[cut->dither_image].GetSharp(ps);
        if (image.Valid()) {
            dither_size = {u32(image.width) + 1, u32(image.height) + 1};
        }
    }
    const int alpha_vs_out =
        cut->alpha_input != Shader::Info::Cutout::NoInput ? vs_out(cut->alpha_input) : -1;
    const std::string line = Opt::CutoutConstantsLine(ps.pgm_hash, *cut, values,
                                                      vs_out(cut->input), alpha_vs_out, stored,
                                                      state, dither_size);
    std::printf("%s\n", line.c_str());
}
} // namespace

"""

EDITS = {
    SR + "info.h": [
        ("    std::array<Interpolation, IR::NumParams> fs_interpolation{};\n" + OLD_INFO_CUTOUT,
         "    std::array<Interpolation, IR::NumParams> fs_interpolation{};\n" + INFO_CUTOUT),
    ],
    R + "vk_rasterizer_effects.cpp": [
        ('#include "core/memory.h"\n'
         '#include "video_core/renderer_vulkan/vk_effect_shaders.h"\n',
         '#include "core/memory.h"\n'
         '#include "shader_recompiler/ir/passes/cutout_analysis.h" // bbport (r50b_leaf-matcher)\n'
         '#include "video_core/renderer_vulkan/vk_effect_shaders.h"\n'),
        ("void Rasterizer::EffectsCaptureDraw(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline,\n",
         FX_HELPER +
         "void Rasterizer::EffectsCaptureDraw(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline,\n"),
        ("        .pixel_shader = ps ? ps->pgm_hash : 0, // bbport (r50_leaf-stage1)\n"
         "    };\n",
         "        .pixel_shader = ps ? ps->pgm_hash : 0, // bbport (r50_leaf-stage1)\n"
         "    };\n"
         "    // bbport (r50b_leaf-matcher): with BB_RT_CARD_ALPHA_LOG=1, the memory constants of a\n"
         "    // matched cut-out pixel shader as this draw holds them (once per pgm_hash).\n"
         "    static const bool cutout_log = Shader::Optimization::CutoutAnalysisOn();\n"
         "    if (cutout_log && ps && ps->has_discard) {\n"
         "        LogCutoutConstants(regs, *ps, *memory, buffer_cache);\n"
         "    }\n"),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text (looked at with LF line ends)."""
    texts = {path: text.replace("\r\n", "\n") for path, text in texts.items()}
    ok = True
    if any(foreign(p) for p in list(EDITS) + list(REPLACED)):
        print("this round would touch a file of another round, the drawn look or the fog")
        ok = False
    info = texts[SR + "info.h"]
    persistent = info[:info.find("struct Info : InfoPersistent {")]
    if info.count("    struct Cutout {") != 1 or info.count("    Cutout cutout{};") != 1 or \
            "cutout" in persistent or "DitherNotScreen" in persistent or \
            info.count("bool RepeatableWithConstants() const {") != 1 or "bool Repeatable() const" in info:
        print("info.h: Info::Cutout (r50b) is not in Info once, out of InfoPersistent")
        ok = False
    cpp = texts[P + "cutout_analysis_pass.cpp"]
    h = texts[P + "cutout_analysis.h"]
    test = texts[TESTS + "test_rt_card_alpha.cpp"]
    for name, text in ((P + "cutout_analysis_pass.cpp", cpp), (TESTS + "test_rt_card_alpha.cpp", test)):
        if ".Repeatable()" in text or "->Repeatable()" in text:
            print("%s still calls r50's Repeatable()" % name)
            ok = False
    # The r50 lines keep their tag, the new one has r50b's.
    if cpp.count('"Cut-out pixel shader %016llx (r50): %s"') != 1 or \
            cpp.count('"Ray tracing cut-out shaders (r50, BB_RT_CARD_ALPHA_LOG=1): ') != 1 or \
            cpp.count('"Ray tracing cut-out cards\' pixel shaders (r50, BB_RT_CARD_ALPHA_LOG=1): ') != 1 or \
            cpp.count('"Cut-out constants %016llx (r50b): ') != 1:
        print("cutout_analysis_pass.cpp: the log lines' tags are not r50's (and r50b's for the new one)")
        ok = False
    if "static_assert(DetailNames.size() == size_t(Detail::Count));" not in cpp or \
            cpp.count('"dither not a screen space noise",') != 1 or cpp.count('"clamped"};') != 1 or \
            "static_assert(ConstantsNames.size() == size_t(CutoutConstants::OtherPermutation) + 1);" \
            not in cpp:
        print("cutout_analysis_pass.cpp: the detail and state names are not checked against their enums")
        ok = False
    for decl in ("const Info::Cutout* FindCutout(u64 pgm_hash)", "std::array<CutoutDword, 7> CutoutDwords(",
                 "std::string CutoutConstantsLine(",
                 "bool NoteCutoutConstants(u64 pgm_hash, CutoutConstants state)",
                 "bool CutoutSamePermutation(const Info::Cutout& c, u32 num_inputs, u32 default_mask,"):
        if decl not in h or decl not in cpp:
            print("cutout_analysis: %s is not declared and defined" % decl)
            ok = False
    if cpp.count("std::getenv(\"BB_RT_CARD_ALPHA_LOG\")") != 1 or \
            "if (!CutoutAnalysisOn()) {" not in cpp.split("std::string CutoutSummaryText() {")[1][:200]:
        print("cutout_analysis_pass.cpp: the knob is not read once, or the summary does not test it")
        ok = False
    fx = texts[R + "vk_rasterizer_effects.cpp"]
    helper = fx.find("void LogCutoutConstants(const AmdGpu::Regs& regs, const Shader::Info& ps,")
    capture = fx.find("void Rasterizer::EffectsCaptureDraw(")
    filled = fx.find(".pixel_shader = ps ? ps->pgm_hash : 0,")
    gate = fx.find("    static const bool cutout_log = Shader::Optimization::CutoutAnalysisOn();")
    call = fx.find("        LogCutoutConstants(regs, *ps, *memory, buffer_cache);")
    prepare = fx.find("const u32 param = rt_shadow->PrepareDraw(draw);")
    if fx.count("LogCutoutConstants(") != 2 or fx.count("cutout_log") != 2 or \
            not 0 <= helper < capture < filled < gate < call < prepare or \
            fx.count('#include "shader_recompiler/ir/passes/cutout_analysis.h"') != 1 or \
            "    if (cutout_log && ps && ps->has_discard) {\n" not in fx:
        print("vk_rasterizer_effects.cpp: the draw-time line is not defined before EffectsCaptureDraw "
              "and called once there, after the Draw, under the cached knob")
        ok = False
    for needle in ("buffer_cache.IsRegionGpuModified(address, 4)", "memory.ClampRangeSize(address, 4) != 4",
                   "!memory.IsValidGpuMapping(address, 4)", "ps.buffers[d.buffer].GetSharp(ps)",
                   "Opt::FindCutout(ps.pgm_hash)", "cut->image_count != ps.images.size()",
                   "buffer_cache.IsInPlace(address, 4)", "if (ps.buffers[d.buffer].is_written) {",
                   "Opt::CutoutSamePermutation(*cut, regs.num_interp, default_mask, flat_mask)",
                   "std::memcpy(&raw, reinterpret_cast<const void*>(address), sizeof(raw));"):
        if fx.count(needle) != 1:
            print("vk_rasterizer_effects.cpp: %s is not there once" % needle)
            ok = False
    # A dword in a region the GPU wrote is not read (the blocker of the first review).
    gpu = fx.find("        if (buffer_cache.IsRegionGpuModified(address, 4)) {\n")
    skip = fx.find("            continue; // not read\n        }\n        u32 raw = 0;\n", gpu) if gpu >= 0 else -1
    copy = fx.find("std::memcpy(&raw,")
    if gpu < 0 or skip < 0 or not gpu < skip < copy or fx[gpu:skip].count("\n") != 2:
        print("vk_rasterizer_effects.cpp: a dword the GPU wrote would be read")
        ok = False
    # The C escapes must have kept their backslash on the way into this script.
    bs = chr(92)
    if 'std::printf("%s' + bs + 'n", CutoutLine(info, runtime_info).c_str());' not in cpp or \
            'std::printf("%s' + bs + 'n", text.c_str());' not in cpp or \
            'std::printf("%s' + bs + 'n", line.c_str());' not in fx or \
            'analysed in %.2f ms' + bs + 'n", ms);' not in test or \
            "\"game's forms, the reviews' probes)" + bs + 'n");' not in test:
        print("a C escape lost its backslash on the way into the script")
        ok = False
    for name in ("FPRecip32", "FPDiv32", "FPOrdEqual32", "FPUnordEqual32", "ImageSampleImplicitLod",
                 "ReadConstBuffer", "DiscardCond"):
        if ("IR::Opcode::" + name) not in cpp:
            print("cutout_analysis_pass.cpp does not use IR::Opcode::%s" % name)
            ok = False
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts, or None with the reason printed."""
    out = {}
    for path, pairs in EDITS.items():
        if not os.path.isfile(path):
            if not quiet:
                print("no such file: %s" % path)
            return None
        t = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in t else "\n"
        for old, new in (pairs if mode != "revert" else reversed(pairs)):
            a, b = (fix(old, nl), fix(new, nl)) if mode != "revert" else (fix(new, nl), fix(old, nl))
            n = t.count(a)
            if n != 1:
                if not quiet:
                    print("anchor found %d times (want 1) in %s: %a" % (n, path, a[:90]))
                return None
            t = t.replace(a, b)
        out[path] = t
    for path, (old, new) in REPLACED.items():
        if not os.path.isfile(path):
            if not quiet:
                print("no such file: %s" % path)
            return None
        t = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in t else "\n"
        want, put = (old, new) if mode != "revert" else (new, old)
        if t.replace("\r\n", "\n") != fix(want, "\n"):
            if not quiet:
                print("%s is not as %s" % (path, "r50 left it" if mode != "revert" else "this script writes it"))
            return None
        out[path] = fix(put, nl)
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r50b_leaf-matcher.py check|apply|revert   (the tree: R50B_ROOT, else the current "
              "directory if it is a source tree's root, else <tree>/)")
        return 2
    out = run(mode, quiet=(mode == "check"))
    if out is None:
        if mode == "check":
            if run("revert", quiet=True) is not None:
                print("already applied (revert would restore the tree)")
            else:
                run("check")  # says which anchor
            return 1
        return 1
    if mode == "check":
        print("anchors OK (applies cleanly)")
        return 0
    # Nothing is changed in place: every new text goes to a file beside its target first, then
    # each is moved over its target (one rename a file). If a step fails, what was already moved
    # is put back from the texts read at the start, so the tree is never left half patched.
    before = {path: open(path, "rb").read() for path in out}
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path in out:
            os.replace(path + TMP, path)
            done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            with open(path, "wb") as f:
                f.write(before[path])
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
