# r50_leaf-stage1: stage 1 of the ray traced foliage shadows. An analysis of every pixel shader as
# it compiles that reads from its IR whether its discard is an alpha test (a texture channel
# compared with a constant or a value from memory) and where that texture is sampled, and logs
# what it finds, also for the pixel shaders of the ray tracing scene's cut-out cards by the r46
# rule's class (plants, hair/cloth/characters, ...). Nothing else: no picture change, no GPU
# resource, no change to any ray. Off by default; BB_RT_CARD_ALPHA_LOG=1 turns it on (read once).
# check|apply|revert (revert restores byte for byte). On top of r1..r48 as <tree> has them on
# 2026-11-14. The tree: the one the environment variable R50_ROOT names; without it the current
# directory when that is the root of a source tree, else <tree>/. Nothing is changed in
# place: every new text is written beside its target and moved over it, and a failure puts back
# what was already moved. Files keep their line ends (CRLF or LF, as each file has them); the three
# new files are written with CRLF.
#
# WHY. Lamp rays (point_shadow_ray.comp) cannot test a texture: the scene's bottom-level
# structures are opaque, so a cut-out card (a leaf, ivy, a weed) would throw a rectangle of
# shadow, and r46 leaves the cards out of lamp rays. Shadows of leaves need the ray to read the
# card's alpha at the hit. Before any of that, this round measures how many of the game's cut-out
# pixel shaders are a plain alpha test that a ray could repeat: which texture, which channel,
# which comparison against which reference, at which UV input; and how many of the plants' and
# the hair's and cloth's are.
#
# WHAT.
#  1. shader_recompiler/ir/passes/cutout_analysis.h and cutout_analysis_pass.cpp (new; the
#     recompiler's sources are globbed, so no CMake line): AnalyzeCutout reads the program after
#     all passes (after CollectShaderInfoPass, the IR SPIR-V is emitted from). The pattern:
#      - the discards: DiscardCond(c) (export.cpp's DiscardCond(LogicalNot(exec)), exec being the
#        v_cmpx compares LogicalAnd'ed, s_andn2 masks folded to LogicalAnd/LogicalNot);
#        InjectClipDistanceAttributes' DiscardCond(input num_inputs-1 < 0) is left out;
#      - where they sit (program.syntax_list): every If over a DiscardCond, and every If an early
#        Return leaves behind it (its condition false for the rest of the parent body), must be
#        decided by the test (its condition a conjunction of the discards' own terms: the v_cmpx
#        exec scope, the execz skip), else "other (through a phi or a branch)": a uniform switch
#        (s_cbranch_scc on a flag) between an alpha-tested and an opaque tail, a discard inside an
#        if, a discard in a loop, an early return before a later discard. An unconditional
#        Discard is a kill block (counted) where every lane reaching it fails a term (the execz
#        kill block, s_mov_b64 exec, 0 + exp vm), else "other (discard in a branch)";
#      - the terms that keep the pixel (their conjunction; a phi whose operands agree is followed);
#        those that read no texture are counted as other terms (fades, clip planes); exactly one
#        term must read a texture (several terms over several samples: several textures, also a
#        dither against a second texture; all over one sample: the first one that is no alpha
#        test says why, else two alpha tests);
#      - that term a float compare (FPOrd/FPUnord Less/LessEqual/Greater/GreaterEqual/Equal/
#        NotEqual 32), each side one variable times a factor plus an offset through FPAdd, FPSub,
#        FPMul, FPFma, FPNeg, FPSaturate, FPClamp(x, 0, 1), bit casts and V_MUL_LEGACY's zero
#        select (only that one: Select(FPEqual(a,0) || FPEqual(b,0), 0, a*b); a V_CNDMASK select
#        of a fade or a flag is "computed"); a term that is a phi, or logic over one, is "through a
#        phi or a branch"; the variable a channel of ImageSampleImplicitLod/ExplicitLod/
#        ImageGradient; the constants immediates or ONE dword: user data (GetUserData), flat user
#        data (ReadConst with its flat dword) or a constant buffer at an immediate dword
#        (ReadConstBuffer). So "alpha - s4 >= 0", "a >= cb2[12]", "saturate(2 a - 1) > 0" all come
#        out as "alpha <op> reference"; "alpha - varying >= 0" is "ref is a varying" as
#        "alpha >= varying" is, "alpha * varying" "alpha with a varying", two channels of one
#        sample "two channels";
#      - the sample's (u, v) the same way, the variable an input: GetAttribute(ParamN, c), or GCN's
#        two manual interpolation steps (P0 + I (P1 - P0) + J (P2 - P0)) where
#        HardwareInterpolationPass left them; an affine scale/offset by immediates is recorded, one
#        by a value from memory flagged; a third coordinate (array layer, 3D w) recorded as an
#        immediate or flagged computed; a texel offset flagged. Matched with one of the flags:
#        matched, but not repeatable from the record alone (counted apart);
#      - the T# of the alpha's image as the compiling draw's flat user data hold it: the stored
#        channel the view lane reads (the image view applies dst_sel, so `channel` is a view lane)
#        and the data format.
#     Every walk is bounded (depth 32 and 4096 instructions) and remembers what it evaluated
#     (an expression that reuses a value costs once).
#     Not matched, by class: no discard / not from a texture / UV not an input (the alpha test
#     itself is kept) / several textures / other, with the first reason found (detail).
#  2. info.h: Info::Cutout (verdict, detail, op, reference kind and dword, the reference as
#     ref + ref_scale * dword, image and sampler index, view channel, stored channel and format,
#     input and its components, the UV's scale/offset, layer, texel offset, other terms, kill
#     blocks; Repeatable()) and Info::cutout. Not in InfoPersistent, so the cache record
#     (Info::Serialize) does not change; filled only with the knob on.
#  3. recompiler.cpp: one branch after CollectShaderInfoPass runs the pass for fragment programs
#     when the knob is on.
#  4. vk_pipeline_serialization.cpp: with the knob on, a cached pixel shader that discards (the
#     SPIR-V scan's `discards`) is not taken from the cache at warm-up (like the gt7_checked rule,
#     counted) and compiles in play, so the analysis sees its IR. Knob off: unchanged.
#  5. The cut-out cards' pixel shaders: RtShadow::Draw::pixel_shader (vk_rt_shadow.h), filled in
#     EffectsCaptureDraw (vk_rasterizer_effects.cpp) from the pipeline's pixel shader; with the
#     knob on PrepareDraw keeps on the Entry the pixel shader of its camera pass draw that
#     discards (r46's card_camera) and of its sun shadow pass draw with a texture (card_shadow),
#     and PrepareScene notes them, once an entry and class, in the class the r46 rule gives the
#     entry (Shader::Optimization::CutoutCardClass): plants (left out of lamp rays, a skeleton, no
#     sun shadow pass draw: lone), left out without a skeleton, left out with one, kept whole with
#     a skeleton (hair, cloth, characters), kept whole otherwise. Knob off: one load of the hash
#     per captured draw and one cached bool test in PrepareDraw and in each scene record.
#  6. Log. A pixel shader's first analysis (one line per pgm_hash, under 200 characters):
#       Cut-out pixel shader 00000000feedbeef (r50): match, image 0 (T# flat 12; .w reads a, format 35) sampler 1, .w >= 0.5, uv in1.xy (vs out 5)
#     and every 600 frames in RtShadow::OnFrameEnd (beside r17's reset; only while ray tracing
#     captures), when the knob is on: the totals (when a shader was analysed)
#       Ray tracing cut-out shaders (r50, BB_RT_CARD_ALPHA_LOG=1): N pixel shaders compiled in
#       play and analysed (...; K discarding cache records were left to compile in play, ...), ...;
#       of the D that discard M match the alpha test (...; R not repeatable ...); not matched: ...
#     and the cut-out cards' (when an instance was noted)
#       Ray tracing cut-out cards' pixel shaders (r50, BB_RT_CARD_ALPHA_LOG=1): ...; camera pass
#       draws that discard: plants (...) P [verdict mix; repeatable], ...; sun shadow pass draws
#       that sample a texture: ...; camera pass shaders not matched: <hash> (class; why) ...
#  7. tests/test_rt_card_alpha.cpp, target rt-card-alpha-test (CMakeLists.txt, in front of
#     ui-composition-test, after motion-shader-test, away from lamp-shadow-tune-test's lines):
#     the alpha test shapes above, the UV shapes, each class of no match, the control flow shapes
#     on structured programs (exec scope, execz kill, uniform switch both ways, discard in a
#     branch, phi), the cost of reused values, and both 600-frame lines, on IR built with
#     IREmitter as the translator leaves it. No GPU.
# NOT CHANGED: anything a ray, a pass or a picture uses; the cache's format; the files of the r49
# draft (point_shadow_ray.comp, vk_point_shadow.cpp/.h, lamp_shadow_tune.h, test_lamp_shadow_tune.cpp,
# test_rt_shadows.cpp). The r51 draft also edits vk_rasterizer_effects.cpp and CMakeLists.txt, at
# other anchors (its include list, SunAtlasResolve, lamp-fog-lights-test): either can go first.
# NOT DONE: the result is lost for permutations after the first (GetProgram compiles them into a
# temporary Info; program->info and the draw-preparation copies keep the first's); the stored
# channel is the compiling draw's T#'s (another draw of the shader may bind another texture); the
# memory dwords of a coordinate scale/offset are flagged, not recorded; pixel shaders without a
# discard taken from the cache are not analysed (the sun pass's non-discarding ones then show as
# "not analysed"); with the knob on discarding pixel shaders compile in play every run (a stutter
# the first time each is drawn). Hair and cloth drawn with blending or alpha to coverage and no
# discard are not cut-outs to r46 and are not in the cards' line.
# VERIFIED: see the report of this round (check against <tree>; apply / revert / apply on
# a copy of the eight changed files; clang++ -fsyntax-only of the changed .cpp files with the
# engine's flags; rt-card-alpha-test built from the patched files and run).

import os
import sys

ROOT = os.environ.get("R50_ROOT")
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

TMP = ".r50tmp"  # a new text waits under this name beside its target (main)

# The r49 draft's files (another round's): this one must not touch them.
FOREIGN = ("point_shadow_ray.comp", "vk_point_shadow.cpp", "vk_point_shadow.h", "lamp_shadow_tune.h",
           "test_lamp_shadow_tune.cpp", "test_rt_shadows.cpp")

# The three files this round adds (apply writes them with CRLF line ends, revert removes them if
# they are still as written here).
NEW_FILES = {
    P + "cutout_analysis.h": r"""// SPDX-License-Identifier: GPL-3.0-or-later
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
""",
    P + "cutout_analysis_pass.cpp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
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
""",
    TESTS + "test_rt_card_alpha.cpp": r"""// SPDX-License-Identifier: GPL-2.0-or-later
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
""",
}

INFO_CUTOUT = r"""    /// bbport (r50_leaf-stage1): the alpha test of a pixel shader's discard, as the cut-out
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

EDITS = {
    SR + "info.h": [
        ("    std::array<Interpolation, IR::NumParams> fs_interpolation{};\n"
         "\n"
         "    Info() = default;\n",
         "    std::array<Interpolation, IR::NumParams> fs_interpolation{};\n"
         + INFO_CUTOUT +
         "\n"
         "    Info() = default;\n"),
    ],
    SR + "recompiler.cpp": [
        ('#include "shader_recompiler/ir/passes/ir_passes.h"\n',
         '#include "shader_recompiler/ir/passes/cutout_analysis.h" // bbport (r50_leaf-stage1)\n'
         '#include "shader_recompiler/ir/passes/ir_passes.h"\n'),
        ("    Shader::Optimization::CollectShaderInfoPass(program, profile);\n",
         "    Shader::Optimization::CollectShaderInfoPass(program, profile);\n"
         "    // bbport (r50_leaf-stage1): what a pixel shader's discard tests, with\n"
         "    // BB_RT_CARD_ALPHA_LOG=1 only (ir/passes/cutout_analysis.h).\n"
         "    if (info.sw_stage == SwStage::Fragment && Shader::Optimization::CutoutAnalysisOn()) {\n"
         "        Shader::Optimization::CutoutAnalysisPass(program, runtime_info);\n"
         "    }\n"),
    ],
    R + "vk_pipeline_serialization.cpp": [
        ('#include "shader_recompiler/native/froyok_composite.h"\n',
         '#include "shader_recompiler/ir/passes/cutout_analysis.h" // bbport (r50_leaf-stage1)\n'
         '#include "shader_recompiler/native/froyok_composite.h"\n'),
        ("    auto it = program_cache.find(program->info.pgm_hash);\n",
         "    // bbport (r50_leaf-stage1): with BB_RT_CARD_ALPHA_LOG=1 a pixel shader that discards\n"
         "    // compiles again in play, so the cut-out analysis sees its IR.\n"
         "    if (discards && program->info.sw_stage == Shader::SwStage::Fragment &&\n"
         "        Shader::Optimization::CutoutAnalysisOn()) {\n"
         "        Shader::Optimization::NoteCutoutCacheRefusal();\n"
         "        return false;\n"
         "    }\n"
         "\n"
         "    auto it = program_cache.find(program->info.pgm_hash);\n"),
    ],
    R + "vk_rt_shadow.cpp": [
        ('#include "shader_recompiler/runtime_info.h"\n',
         '#include "shader_recompiler/ir/passes/cutout_analysis.h" // bbport (r50_leaf-stage1)\n'
         '#include "shader_recompiler/runtime_info.h"\n'),
        ("    if (frame % 600 == 0) {\n"
         "        r17_stats = {};\n"
         "    }\n",
         "    if (frame % 600 == 0) {\n"
         "        r17_stats = {};\n"
         "        // bbport (r50_leaf-stage1): the pixel shaders' cut-out analysis so far, and the\n"
         "        // cut-out cards' pixel shaders, with BB_RT_CARD_ALPHA_LOG=1.\n"
         "        Shader::Optimization::PrintCutoutSummary();\n"
         "    }\n"),
        # PrepareDraw: the pixel shaders that made the entry a cut-out (beside r46's flags).
        ("    entry.card_camera = entry.card_camera || (draw.camera_pass && draw.alpha);\n",
         "    entry.card_camera = entry.card_camera || (draw.camera_pass && draw.alpha);\n"
         "    // bbport (r50_leaf-stage1): with BB_RT_CARD_ALPHA_LOG=1, the pixel shaders that showed\n"
         "    // it a cut-out (the 600-frame line of the cut-out cards' pixel shaders)\n"
         "    if (draw.pixel_shader != 0 && Shader::Optimization::CutoutAnalysisOn()) {\n"
         "        if (draw.camera_pass && draw.alpha && entry.cut_camera_ps != draw.pixel_shader) {\n"
         "            entry.cut_camera_ps = draw.pixel_shader;\n"
         "            entry.cut_noted = 0;\n"
         "        }\n"
         "        if (draw.shadow_pass && draw.textured && entry.cut_sun_ps != draw.pixel_shader) {\n"
         "            entry.cut_sun_ps = draw.pixel_shader;\n"
         "            entry.cut_noted = 0;\n"
         "        }\n"
         "    }\n"),
        # PrepareScene: each such entry once per class the r46 rule gives it.
        ("        const bool card = LampCard(cards_old, card_level, entry->shadow_card, entry->dynamic,\n"
         "                                   entry->card_shadow, cutout, entry->skinned, lone);\n",
         "        const bool card = LampCard(cards_old, card_level, entry->shadow_card, entry->dynamic,\n"
         "                                   entry->card_shadow, cutout, entry->skinned, lone);\n"
         "        // bbport (r50_leaf-stage1): with BB_RT_CARD_ALPHA_LOG=1, the pixel shaders of the\n"
         "        // cut-outs by the class this rule gives them (each entry once a class)\n"
         "        if ((entry->cut_camera_ps | entry->cut_sun_ps) != 0 &&\n"
         "            Shader::Optimization::CutoutAnalysisOn()) {\n"
         "            using CardClass = Shader::Optimization::CutoutCardClass;\n"
         "            const CardClass card_class = card ? (!entry->skinned ? CardClass::Static\n"
         "                                                 : lone            ? CardClass::Plant\n"
         "                                                                   : CardClass::SkinnedOut)\n"
         "                                              : entry->skinned ? CardClass::SkinnedKept\n"
         "                                                               : CardClass::OtherKept;\n"
         "            const u8 bit = u8(1u << u32(card_class));\n"
         "            if ((entry->cut_noted & bit) == 0) {\n"
         "                entry->cut_noted |= bit;\n"
         "                Shader::Optimization::NoteCutoutCard(entry->cut_camera_ps, entry->cut_sun_ps,\n"
         "                                                     card_class);\n"
         "            }\n"
         "        }\n"),
    ],
    R + "vk_rt_shadow.h": [
        ("        u32 positions_size = 0;\n"
         "    };\n"
         "    u32 PrepareDraw(const Draw& draw);\n",
         "        u32 positions_size = 0;\n"
         "        // bbport (r50_leaf-stage1): the pixel shader's pgm_hash (0: none); read only with\n"
         "        // BB_RT_CARD_ALPHA_LOG=1 (the cut-out cards' pixel shaders, PrepareDraw)\n"
         "        u64 pixel_shader = 0;\n"
         "    };\n"
         "    u32 PrepareDraw(const Draw& draw);\n"),
        ("        bool skinned = false;\n"
         "        u32 card_gen = 0;\n",
         "        bool skinned = false;\n"
         "        u32 card_gen = 0;\n"
         "        // bbport (r50_leaf-stage1): with BB_RT_CARD_ALPHA_LOG=1, the pixel shaders of its last\n"
         "        // camera pass draw that discards and its last sun shadow pass draw with a texture,\n"
         "        // and the classes of the r46 rule PrepareScene noted them in (bit per\n"
         "        // Shader::Optimization::CutoutCardClass; cleared when either shader changes)\n"
         "        u64 cut_camera_ps = 0;\n"
         "        u64 cut_sun_ps = 0;\n"
         "        u8 cut_noted = 0;\n"),
    ],
    R + "vk_rasterizer_effects.cpp": [
        ("        .target = regs.depth_buffer.Height(),\n"
         "    };\n"
         "    if (fetch) {\n",
         "        .target = regs.depth_buffer.Height(),\n"
         "        .pixel_shader = ps ? ps->pgm_hash : 0, // bbport (r50_leaf-stage1)\n"
         "    };\n"
         "    if (fetch) {\n"),
    ],
    G + "CMakeLists.txt": [
        ("add_executable(ui-composition-test EXCLUDE_FROM_ALL ../tests/test_ui_composition.cpp)\n",
         "# bbport (r50_leaf-stage1): the cut-out analysis of pixel shaders (cutout_analysis.h).\n"
         "add_executable(rt-card-alpha-test EXCLUDE_FROM_ALL ../tests/test_rt_card_alpha.cpp ../tests/test_gpu_runtime_stubs.cpp)\n"
         "target_compile_options(rt-card-alpha-test PRIVATE -UNDEBUG)\n"
         "target_include_directories(rt-card-alpha-test PRIVATE shim shadps4 third_party/gcn/include)\n"
         "target_link_libraries(rt-card-alpha-test PRIVATE bbgpu)\n"
         "if (WIN32)\n"
         "    target_link_libraries(rt-card-alpha-test PRIVATE winmm ws2_32 psapi onecore)\n"
         "endif()\n"
         "add_executable(ui-composition-test EXCLUDE_FROM_ALL ../tests/test_ui_composition.cpp)\n"),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text."""
    ok = True
    if any(p.endswith(FOREIGN) for p in list(EDITS) + list(NEW_FILES)):
        print("this round would touch a file of the r49 draft")
        ok = False
    info = texts[SR + "info.h"]
    if info.count("    struct Cutout {") != 1 or info.count("    Cutout cutout{};") != 1 or \
            "cutout" in info[:info.find("struct Info : InfoPersistent {")]:
        print("info.h: Info::Cutout is not in Info once (and must stay out of InfoPersistent)")
        ok = False
    rec = texts[SR + "recompiler.cpp"]
    at = rec.find("Shader::Optimization::CutoutAnalysisPass(program, runtime_info);")
    if rec.count("CutoutAnalysisPass(") != 1 or \
            not rec.find("CollectShaderInfoPass(program, profile);") < at < rec.find("Shader::IR::DumpProgram(program, info);"):
        print("recompiler.cpp: the pass does not run once, after CollectShaderInfoPass")
        ok = False
    ser = texts[R + "vk_pipeline_serialization.cpp"]
    at = ser.find("        Shader::Optimization::CutoutAnalysisOn()) {")
    if ser.count("CutoutAnalysisOn()") != 1 or \
            not ser.find("discards |= opcode == 252u || opcode == 5380u;") < at < ser.find("auto it = program_cache.find(program->info.pgm_hash);"):
        print("vk_pipeline_serialization.cpp: the warm-up rule is not after the SPIR-V scan once")
        ok = False
    if ser.count("Shader::Optimization::NoteCutoutCacheRefusal();") != 1 or \
            not at < ser.find("Shader::Optimization::NoteCutoutCacheRefusal();") < ser.find("auto it = program_cache.find(program->info.pgm_hash);"):
        print("vk_pipeline_serialization.cpp: the warm-up refusals are not counted in the rule")
        ok = False
    scene = texts[R + "vk_rt_shadow.cpp"]
    at = scene.find("        Shader::Optimization::PrintCutoutSummary();")
    if scene.count("PrintCutoutSummary()") != 1 or not scene.find("        r17_stats = {};") < at:
        print("vk_rt_shadow.cpp: the 600-frame summary is not there once")
        ok = False
    # The shaders are taken at the draw beside r46's card flags and noted after the card rule.
    draw_at = scene.find("u32 RtShadow::PrepareDraw(const Draw& draw) {")
    taken = scene.find("            entry.cut_camera_ps = draw.pixel_shader;")
    noted = scene.find("                Shader::Optimization::NoteCutoutCard(entry->cut_camera_ps, entry->cut_sun_ps,")
    rule = scene.find("        const bool card = LampCard(cards_old, card_level, entry->shadow_card, entry->dynamic,")
    if scene.count("NoteCutoutCard(") != 1 or scene.count("entry.cut_camera_ps = draw.pixel_shader;") != 1 or \
            not draw_at < taken < scene.find("    if (entry.seen_frame == frame) {", taken) or not rule < noted:
        print("vk_rt_shadow.cpp: the cut-out cards' shaders are not taken in PrepareDraw and noted after LampCard")
        ok = False
    rh = texts[R + "vk_rt_shadow.h"]
    if rh.count("        u64 pixel_shader = 0;") != 1 or rh.count("        u64 cut_camera_ps = 0;") != 1 or \
            not rh.find("    struct Draw {") < rh.find("        u64 pixel_shader = 0;") < rh.find("    u32 PrepareDraw(const Draw& draw);") or \
            not rh.find("    struct Entry {") < rh.find("        u64 cut_camera_ps = 0;"):
        print("vk_rt_shadow.h: Draw::pixel_shader or the Entry's fields are not there once")
        ok = False
    fx = texts[R + "vk_rasterizer_effects.cpp"]
    if fx.count(".pixel_shader = ps ? ps->pgm_hash : 0,") != 1 or \
            not fx.find("    RtShadow::Draw draw{") < fx.find(".pixel_shader = ps ? ps->pgm_hash : 0,") < fx.find("const u32 param = rt_shadow->PrepareDraw(draw);"):
        print("vk_rasterizer_effects.cpp: Draw::pixel_shader is not filled once in EffectsCaptureDraw")
        ok = False
    cmake = texts[G + "CMakeLists.txt"]
    at = cmake.find("add_executable(rt-card-alpha-test EXCLUDE_FROM_ALL")
    if cmake.count("add_executable(rt-card-alpha-test ") != 1 or "lamp-shadow-tune-test" in cmake[at:cmake.find("add_executable(ui-composition-test")]:
        print("CMakeLists.txt: rt-card-alpha-test is not registered once, apart from lamp-shadow-tune-test")
        ok = False
    # The C escapes must have kept their backslash on the way into this script.
    bs = chr(92)
    cpp, test = NEW_FILES[P + "cutout_analysis_pass.cpp"], NEW_FILES[TESTS + "test_rt_card_alpha.cpp"]
    if 'std::printf("%s' + bs + 'n", CutoutLine(info, runtime_info).c_str());' not in cpp or \
            'std::printf("%s' + bs + 'n", text.c_str());' not in cpp or \
            'shaders not matched)' + bs + 'n");' not in test or \
            'analysed in %.2f ms' + bs + 'n", ms);' not in test:
        print("a C escape lost its backslash on the way into the script")
        ok = False
    for name in ("Discard", "DiscardCond", "ImageSampleImplicitLod", "ReadConstBuffer", "FPOrdGreaterThanEqual32",
                 "ConditionRef", "FPOrdEqual32"):
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
    for path, text in NEW_FILES.items():
        there = os.path.exists(path)
        if mode != "revert" and there:
            if not quiet:
                print("%s is there already" % path)
            return None
        if mode == "revert":
            # Removed only as this script wrote it.
            if not there or open(path, encoding="utf-8", newline="").read() != fix(text, "\r\n"):
                if not quiet:
                    print("%s is not there as this script writes it" % path)
                return None
        elif not os.path.isdir(os.path.dirname(path)):
            if not quiet:
                print("no such directory: %s" % os.path.dirname(path))
            return None
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r50_leaf-stage1.py check|apply|revert   (the tree: R50_ROOT, else the current "
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
    if mode == "apply":
        for path, text in NEW_FILES.items():
            out[path] = fix(text, "\r\n")
    before = {}
    for path in out:
        before[path] = open(path, "rb").read() if os.path.exists(path) else None
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path in out:
            os.replace(path + TMP, path)
            done.append(path)
        if mode == "revert":
            for path in NEW_FILES:
                before[path] = open(path, "rb").read()
                os.remove(path)
                done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            if before[path] is None:
                os.remove(path)
            else:
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
