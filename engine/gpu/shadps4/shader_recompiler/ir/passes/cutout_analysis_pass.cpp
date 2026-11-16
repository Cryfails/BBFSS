// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r50_leaf-stage1, r50b_leaf-matcher, r50c_leaf-fade): the cut-out analysis
// (cutout_analysis.h). It runs after CollectShaderInfoPass, on the program as it goes to SPIR-V,
// and reads:
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
//    a buffer load such as the game's per-instance fade, dwords, an input, computed); (r50c) a
//    buffer load also through the lanes LowerBufferFormatToRaw rebuilds a typed load with (the
//    game's fade is one), and only where its address holds one value across a triangle
//    (PerVertexAddress); dwords from memory are taken as computed, and a finite nonzero
//    immediate is no factor (FactorKind);
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
#include "video_core/renderer_vulkan/rt_card_uv.h" // bbport (r54_leaf-stage2): ReadCardAlpha

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

/// (r50c) The lanes of a vector type (0: not a vector of 32-bit lanes).
u32 Lanes(IR::Type type) {
    switch (type) {
    case IR::Type::U32x2:
    case IR::Type::F32x2:
        return 2;
    case IR::Type::U32x3:
    case IR::Type::F32x3:
        return 3;
    case IR::Type::U32x4:
    case IR::Type::F32x4:
        return 4;
    default:
        return 0;
    }
}

/// (r50c) What one lane of a value comes from: followed back through bit casts, a composite
/// extract (the lane), a composite construct (its argument for the lane) and a composite shuffle
/// (the vector and lane its index picks; both vectors have Lanes() lanes, the second's indexed
/// after the first's). LowerBufferFormatToRaw turns a typed load (buffer_load_format_*,
/// tbuffer_load_*) into LoadBufferF32xN, its lanes extracted, built again and shuffled by the
/// swizzle (reinterpret.h ApplySwizzle), and ConstantPropagation folds no float construct or
/// shuffle: the game's per-instance fade reaches the analysis as Extract(Shuffle(constants,
/// Construct(Extract(LoadBufferF32x4, 0..3))), 3), which r50b took for computed. `vector`: the
/// value reached is a vector and `lane` the lane of it meant. At most 16 steps.
struct LaneSource {
    IR::Value value;
    bool vector = false;
    u32 lane = 0;
};

LaneSource ThroughComposites(IR::Value value) {
    LaneSource at{.value = value};
    for (u32 step = 0; step < 16; ++step) {
        const IR::Inst* inst = at.value.IsImmediate() ? nullptr : at.value.TryInst();
        if (!inst) {
            break;
        }
        switch (inst->GetOpcode()) {
        case IR::Opcode::BitCastF32U32:
        case IR::Opcode::BitCastU32F32:
            if (at.vector) {
                return at;
            }
            at.value = inst->Arg(0);
            continue;
        case IR::Opcode::CompositeExtractU32x2:
        case IR::Opcode::CompositeExtractU32x3:
        case IR::Opcode::CompositeExtractU32x4:
        case IR::Opcode::CompositeExtractF32x2:
        case IR::Opcode::CompositeExtractF32x3:
        case IR::Opcode::CompositeExtractF32x4:
            if (at.vector || !inst->Arg(1).IsImmediate()) {
                return at;
            }
            at = {.value = inst->Arg(0), .vector = true, .lane = inst->Arg(1).U32()};
            continue;
        case IR::Opcode::CompositeConstructU32x2:
        case IR::Opcode::CompositeConstructU32x3:
        case IR::Opcode::CompositeConstructU32x4:
        case IR::Opcode::CompositeConstructF32x2:
        case IR::Opcode::CompositeConstructF32x3:
        case IR::Opcode::CompositeConstructF32x4:
            if (!at.vector || at.lane >= inst->NumArgs()) {
                return at;
            }
            at = {.value = inst->Arg(at.lane)};
            continue;
        case IR::Opcode::CompositeShuffleU32x2:
        case IR::Opcode::CompositeShuffleU32x3:
        case IR::Opcode::CompositeShuffleU32x4:
        case IR::Opcode::CompositeShuffleF32x2:
        case IR::Opcode::CompositeShuffleF32x3:
        case IR::Opcode::CompositeShuffleF32x4: {
            const u32 lanes = Lanes(inst->Arg(0).Type());
            if (!at.vector || 2 + at.lane >= inst->NumArgs() ||
                !inst->Arg(2 + at.lane).IsImmediate() || lanes == 0) {
                return at;
            }
            const u32 pick = inst->Arg(2 + at.lane).U32();
            if (pick >= 2 * lanes) {
                return at;
            }
            at = {.value = inst->Arg(pick < lanes ? 0 : 1),
                  .vector = true,
                  .lane = pick < lanes ? pick : pick - lanes};
            continue;
        }
        default:
            return at;
        }
    }
    return at;
}

bool IsBufferLoad(IR::Opcode opcode) {
    switch (opcode) {
    case IR::Opcode::LoadBufferU32:
    case IR::Opcode::LoadBufferU32x2:
    case IR::Opcode::LoadBufferU32x3:
    case IR::Opcode::LoadBufferU32x4:
    case IR::Opcode::LoadBufferF32:
    case IR::Opcode::LoadBufferF32x2:
    case IR::Opcode::LoadBufferF32x3:
    case IR::Opcode::LoadBufferF32x4:
    case IR::Opcode::LoadBufferFormatF32:
        return true;
    default:
        return false;
    }
}

/// (r50c) The shared, buffer and image atomics (opcodes.inc lists each kind in one run).
bool IsAtomic(IR::Opcode op) {
    using O = IR::Opcode;
    return (op >= O::SharedAtomicIAdd32 && op <= O::SharedAtomicCmpSwap64) ||
           (op >= O::BufferAtomicIAdd32 && op <= O::BufferAtomicFCmpSwap32) ||
           (op >= O::ImageAtomicIAdd32 && op <= O::ImageAtomicCmpSwap32);
}

/// (r50c) Whether input `param` holds one value across a triangle: a per-vertex input (read as one
/// vertex's own value, GetAttribute(ParamN, c, vertex)) or a flat one. A smooth, no-perspective,
/// centroid or sample input varies per pixel, and so does one whose interpolation the Info does
/// not record (None, or no Info): refused.
bool TriangleConstantInput(u32 param, const Info* info) {
    if (!info || param >= info->fs_interpolation.size()) {
        return false;
    }
    const Qualifier q = info->fs_interpolation[param].primary;
    return q == Qualifier::PerVertex || q == Qualifier::Flat;
}

/// (r50c) Whether `value` is GCN's interpolation by hand (Walker::Interpolated, perspective
/// barycentrics) of a per-vertex input. ASSUMED, not provable from the pixel shader: the vertex
/// shader writes the same value to a triangle's three vertices (the game's instance id), so the
/// interpolation gives that value at every pixel (P0 + I * 0 + J * 0). A per-vertex value that
/// differs at the vertices (a normal, a position) would be a per-pixel value here.
bool HandInterpolatedPerVertex(const IR::Value& value, const Info* info) {
    const IR::Inst* fma = value.IsImmediate() ? nullptr : value.TryInst();
    if (!info || !Is(fma, IR::Opcode::FPFma32)) {
        return false;
    }
    const auto input = Walker{Mode::Test, info}.Interpolated(*fma);
    return input && input->index < info->fs_interpolation.size() &&
           info->fs_interpolation[input->index].primary == Qualifier::PerVertex;
}

/// (r50c) Whether a buffer load's address holds one value across a triangle, so that a factor
/// read there is the same at every pixel the triangle covers. Why it matters: a factor left out
/// of the shadow rule must be one the rule can lose without a screen or uv pattern (a dissolve)
/// going with it. Allowed: any arithmetic over immediates, user data, constant and other buffer
/// dwords, inputs that are per vertex or flat (TriangleConstantInput), and an interpolation by
/// hand of a per-vertex input only where it goes straight into a float to integer conversion (an
/// index, as the game's: uint(interpolated instance id) * 13 + 7, row 7 of the instance's 13
/// vec4s; HandInterpolatedPerVertex, whose barycentrics are not walked). The conversion rule
/// narrows the assumption that the per-vertex value is one value per triangle: a position or uv
/// scaled before the conversion is refused. Refused: a texture read; FragCoord, a barycentric
/// read anywhere else, or any other non-input attribute; a smooth, no-perspective, centroid or
/// sample input; a divide or reciprocal (an input over its w is a screen position; kept as a
/// guard although no per-pixel input is left to divide); a lane or wave value (a neighbour's, the
/// wave's coverage, a quad broadcast); shared memory and atomics (what other pixels wrote); the
/// time; an undefined value; a phi (the way in); and a walk cut short (MaxVisits).
bool PerVertexAddress(const IR::Inst& load, const Info* info) {
    std::vector<const IR::Inst*> stack;
    std::unordered_set<const IR::Inst*> seen;
    for (size_t arg = 0; arg < load.NumArgs(); ++arg) {
        if (const IR::Inst* in = load.Arg(arg).TryInst()) {
            stack.push_back(in);
        }
    }
    while (!stack.empty()) {
        const IR::Inst* inst = stack.back();
        stack.pop_back();
        if (!seen.insert(inst).second) {
            continue;
        }
        if (seen.size() > MaxVisits || IsSample(inst->GetOpcode())) {
            return false;
        }
        switch (inst->GetOpcode()) {
        case IR::Opcode::Phi:
        case IR::Opcode::FPRecip32:
        case IR::Opcode::FPRecip64:
        case IR::Opcode::FPDiv32:
        case IR::Opcode::FPDiv64:
        case IR::Opcode::ImageQueryLod:
        case IR::Opcode::LaneId:
        case IR::Opcode::WarpId:
        case IR::Opcode::QuadBroadcast:
        case IR::Opcode::Shuffle:
        case IR::Opcode::ShuffleXor:
        case IR::Opcode::ReadFirstLane:
        case IR::Opcode::ReadLane:
        case IR::Opcode::WriteLane:
        case IR::Opcode::Ballot:
        case IR::Opcode::BallotFindLsb:
        case IR::Opcode::InverseBallot:
        case IR::Opcode::GroupAny:
        case IR::Opcode::GetExec:
        case IR::Opcode::GetVectorRegister:
        case IR::Opcode::LoadSharedU16:
        case IR::Opcode::LoadSharedU32:
        case IR::Opcode::LoadSharedU64:
        case IR::Opcode::DataAppend:
        case IR::Opcode::DataConsume:
        case IR::Opcode::Memtime:
        case IR::Opcode::UndefU1:
        case IR::Opcode::UndefU8:
        case IR::Opcode::UndefU16:
        case IR::Opcode::UndefU32:
        case IR::Opcode::UndefU32x2:
        case IR::Opcode::UndefU32x3:
        case IR::Opcode::UndefU32x4:
        case IR::Opcode::UndefF32:
        case IR::Opcode::UndefU64:
            return false;
        case IR::Opcode::ConvertU32F32:
        case IR::Opcode::ConvertS32F32:
            if (HandInterpolatedPerVertex(inst->Arg(0), info)) {
                continue; // an index: one value per triangle (assumed, see above)
            }
            break;
        case IR::Opcode::GetAttribute:
        case IR::Opcode::GetAttributeU32: {
            const IR::Attribute attr = inst->Arg(0).Attribute();
            if (!IR::IsParam(attr) ||
                !TriangleConstantInput(u32(attr) - u32(IR::Attribute::Param0), info)) {
                return false;
            }
            break;
        }
        default:
            // the atomics of every kind return what memory held, which other pixels change
            if (IsAtomic(inst->GetOpcode())) {
                return false;
            }
            break;
        }
        for (size_t arg = 0; arg < inst->NumArgs(); ++arg) {
            if (const IR::Inst* in = inst->Arg(arg).TryInst()) {
                stack.push_back(in);
            }
        }
    }
    return true;
}

/// (r50b E4) What an ignored factor of a nonzero term is (Cutout::Ignored*), 0 for none:
///  - a buffer load (through bit casts and composites, ThroughComposites); r50c: only at an
///    address that holds one value across a triangle (PerVertexAddress), else computed. The
///    game's per-instance fade is one. It is left out of the shadow rule; where it is 0 the game
///    hides the instance (765450df writes A * fade as its alpha) and the rule still casts its
///    shadow. r50c does not count how often that is: the fade is a per-instance float of a
///    storage buffer, not read here;
///  - (r50c) a finite nonzero immediate, reached through composites (a swizzle's constant 1): no
///    factor, 0 (it changes no pixel's test; r50b's Walker folds a direct one into the alpha);
///  - an immediate 0 or one not finite (r50c): computed. 0 discards every pixel, so the term
///    cannot be left out;
///  - (r50c) dwords from memory: dwords and computed. A dword is a value of the draw, and the
///    record does not keep where it is: a draw where it is 0 hides every pixel, and the rule
///    cannot leave that out unread. So the record is not repeatable (RepeatableWithConstants);
///  - an input component; anything else computed.
u8 FactorKind(const IR::Value& value, const Info* info) {
    const LaneSource source = ThroughComposites(value);
    const IR::Inst* inst = source.value.IsImmediate() ? nullptr : source.value.TryInst();
    if (inst && IsBufferLoad(inst->GetOpcode())) {
        return PerVertexAddress(*inst, info) ? Cutout::IgnoredBuffer : Cutout::IgnoredComputed;
    }
    if (source.vector) {
        return Cutout::IgnoredComputed; // a lane of a vector that is no load
    }
    Walker walker{Mode::Test, info};
    const auto x = walker.Eval(source.value, 0);
    if (x && x->var == Var::None && !x->dither_sample) {
        if (x->offset.Memory()) {
            return Cutout::IgnoredDword | Cutout::IgnoredComputed;
        }
        if (x->offset.a == 0.0f || !std::isfinite(x->offset.a)) {
            return Cutout::IgnoredComputed;
        }
        return 0;
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
            // (r50c) a factor of kind 0 (a finite nonzero immediate) is no factor: not counted
            const u8 kind = FactorKind(inst->Arg(1 - i), info);
            n->count += kind != 0 ? 1 : 0;
            n->kinds |= kind;
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
    // r50c
    u32 fade_left_out = 0; ///< repeatable with the draw's constants, nonzero factors left out
    u32 restored = 0;      ///< (r62b) restored from a cache record's CUT1 part, not compiled
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

bool CutoutLogOn() {
    static const bool on = [] {
        const char* env = std::getenv("BB_RT_CARD_ALPHA_LOG");
        return env && std::strcmp(env, "1") == 0;
    }();
    return on;
}

u32 CardAlphaLevel() {
    static const u32 level = [] {
        const char* env = std::getenv("BB_RT_CARD_ALPHA");
        if (Vulkan::CardAlphaMisread(env)) {
            std::printf("Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=%.16s is not 0, 1 or 2: "
                        "off\n",
                        env);
        }
        return Vulkan::ReadCardAlpha(env);
    }();
    return level;
}

bool CardAlphaOn() {
    return CardAlphaLevel() >= Vulkan::CardAlphaUv; // (r62_leaf-stage3) 2: the UVs and the layers
}

// (r62d_card-uv-diag) BB_RT_CARD_UV_DIAG, read once
u32 CardUvDiag() {
    static const u32 diag = [] {
        const char* env = std::getenv("BB_RT_CARD_UV_DIAG");
        if (!env || env[0] == '\0') {
            return 0u;
        }
        if (env[1] == '\0' && env[0] >= '0' && env[0] <= '5') {
            return u32(env[0] - '0');
        }
        std::printf("Ray tracing card UV diagnosis (r62d): BB_RT_CARD_UV_DIAG=%.16s is not 0 to 5: "
                    "taken as 0\n",
                    env);
        return 0u;
    }();
    return diag;
}

bool CaptureUvWanted(bool discards) {
    // bbport (r62c_leaf-stage3-fix): the pixel shader must discard with every diag value (r62d's
    // 4 and 5 made the rule); 2 is still never
    const u32 diag = CardUvDiag();
    return CardAlphaOn() && diag != 2 && discards;
}

// (r54_leaf-stage2) the records are made for either: the log, or the card UVs a draw reads
bool CutoutAnalysisOn() {
    static const bool on = CutoutLogOn() || CardAlphaOn();
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
        // (r50c) a repeatable record says that its rule leaves them out (the shadow rule is the
        // game's sun shadow pass form, which has no such factor); "not repeatable" only where
        // the factors are the reason (an input or computed), not for a record refused otherwise
        const bool left_out = c.RepeatableWithConstants();
        const bool varying =
            (c.ignored_kinds & (Cutout::IgnoredInput | Cutout::IgnoredComputed)) != 0;
        put(", %u factors of the nonzero term %s (%s%s)", c.ignored_factor_terms,
            left_out ? "left out" : "ignored", KindsText(c.ignored_kinds).c_str(),
            left_out  ? "; repeatable, fade left out"
            : varying ? "; not repeatable"
                      : "");
    }
    if (c.kill_blocks != 0) {
        put(", %u kill branches", c.kill_blocks);
    }
    return std::string(line, std::min(size_t(std::max(n, 0)), sizeof(line) - 1));
}

// bbport (r62b_leaf-stage3-followups): what CutoutAnalysisPass does with an analysed record,
// and NoteCutoutRestored with one a cache record's CUT1 part restored (`restored`: counted
// apart, and its log line says so). The map and the line: the first record of a pgm_hash.
static void NoteCutoutRecord(const Info& info, const RuntimeInfo& runtime_info, bool restored) {
    std::scoped_lock lock{counts_mutex};
    if (!analysed_shaders.emplace(info.pgm_hash, info.cutout).second) {
        return;
    }
    const Cutout& c = info.cutout;
    ++counts.analysed;
    counts.restored += restored ? 1 : 0; // (r62b)
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
        counts.fade_left_out += c.RepeatableWithConstants() && c.ignored_factor_terms != 0 ? 1 : 0;
    }
    if (CutoutLogOn()) { // bbport (r54_leaf-stage2): not with BB_RT_CARD_ALPHA=1 alone
        std::printf("%s%s\n", CutoutLine(info, runtime_info).c_str(),
                    restored ? " (r62b: from the cache's CUT1 part, not compiled in play)" : "");
    }
}

void CutoutAnalysisPass(IR::Program& program, const RuntimeInfo& runtime_info) {
    Info& info = program.info;
    // Every compile's Info, so every permutation's (r50b E6); the map and the line: the first.
    info.cutout = AnalyzeCutout(program, runtime_info);
    NoteCutoutRecord(info, runtime_info, false);
}

void NoteCutoutRestored(const Info& info, const RuntimeInfo& runtime_info) {
    NoteCutoutRecord(info, runtime_info, true);
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
    if (c.ignored_factor_terms != 0) {
        // (r50c) not read and not in the shadow rule (the game's sun shadow pass has none)
        Append(text, ", fade left out (%u factors of the nonzero term: %s)", c.ignored_factor_terms,
               KindsText(c.ignored_kinds).c_str());
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
           "play and analysed (r62b: %u of them restored from the cache's CUT1 parts instead, not "
           "compiled) (%u since the last line; %u discarding cache records were left to "
           "compile in play, pixel shaders without a discard taken from the cache are not "
           "counted), %u without a discard; of the %u that discard %u match the alpha test",
           counts.analysed, counts.restored, counts.analysed - counts.at_last_line,
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
    // (r50c) the shadow rule of a repeatable record is the game's sun shadow pass form: a
    // nonzero factor that is a buffer load (the per-instance fade) is not in it
    Append(text,
           " (r50c: of the %u repeatable with the draw's constants, %u leave nothing out, %u leave "
           "the fade out: factors of the nonzero term that are a buffer load, which the game's "
           "sun shadow pass does not have)",
           counts.with_constants, counts.with_constants - counts.fade_left_out,
           counts.fade_left_out);
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
            u32 fade_left_out = 0; // (r50c) of with_constants
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
                fade_left_out += c.ignored_factor_terms != 0 ? 1 : 0;
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
                   "; %u repeatable, %u with constants (r50c: %u with the fade left out); %u "
                   "match, %u with CPU-written constants on every draw, %u with no memory "
                   "constants",
                   repeatable, with_constants, fade_left_out, matched, cpu, no_memory);
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
    // (r50c) every shader once, whatever its classes and passes: the classes' draws above count
    // a shader in each class it was seen in, so they cannot be summed for the share of draws
    // whose constants are CPU-written
    u32 once = 0;
    std::array<u32, ConstantsNames.size()> once_draws{};
    for (const auto& [hash, shader] : card_shaders) {
        const auto found = analysed_shaders.find(hash);
        if (found == analysed_shaders.end() || !found->second.RepeatableWithConstants() ||
            std::ranges::all_of(CutoutDwords(found->second),
                                [](const CutoutDword& d) { return d.kind == Ref::Immediate; })) {
            continue;
        }
        ++once;
        if (const auto seen = constants_seen.find(hash); seen != constants_seen.end()) {
            for (size_t s = 0; s < once_draws.size(); ++s) {
                once_draws[s] += seen->second.draws[s];
            }
        }
    }
    Append(text, "; (r50c) each shader once: %u with constants read from memory, %u draws:", once,
           std::accumulate(once_draws.begin(), once_draws.end(), 0u));
    for (size_t s = 0; s < once_draws.size(); ++s) {
        Append(text, "%s %u %s", s ? "," : "", once_draws[s], ConstantsShort[s]);
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
    if (!CutoutLogOn()) { // bbport (r54_leaf-stage2)
        return;
    }
    for (const std::string& text : {CutoutSummaryText(), CutoutCardsText()}) {
        if (!text.empty()) {
            std::printf("%s\n", text.c_str());
        }
    }
}

} // namespace Shader::Optimization
