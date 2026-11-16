// SPDX-License-Identifier: GPL-2.0-or-later
// bbport (r50_leaf-stage1, r50b_leaf-matcher, r50c_leaf-fade): the cut-out analysis
// (cutout_analysis.h) on fragment programs built as the translator and the passes before it
// leave them (r50c: some through the recompiler's own LowerBufferFormatToRaw and
// ConstantPropagationPass).
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <limits>
#include "common/object_pool.h"
#include "shader_recompiler/ir/basic_block.h"
#include "shader_recompiler/ir/ir_emitter.h"
#include "shader_recompiler/ir/passes/cutout_analysis.h"
#include "shader_recompiler/ir/passes/ir_passes.h"
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
    // (r50c) Alpha: the texture's alpha itself; Screen: FragCoord.x; Zero, Two, Inf: an
    // immediate 0, 2 or +inf; ConstantLane: .w of a swizzle that puts the constant 1 there (a
    // V#'s dst_sel 1); Dword: cb3[30], a dword from memory
    enum class Fade : u8 {
        Buffer,
        Input,
        Computed,
        Alpha,
        Screen,
        Zero,
        Two,
        Inf,
        ConstantLane,
        Dword
    };
    Fade fade_kind = Fade::Buffer; ///< the fade a buffer load, an input, saturate(an input), ...
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
    // (r50c) the fade as the game's 9 camera pass shaders have it (r50_spv: a float storage
    // buffer read at ((7 + 13 * instance) * 4 + 3)): .w of a typed load of a 32_32_32_32 float
    // buffer, which AnalyzeLowered lowers with the recompiler's LowerBufferFormatToRaw
    bool fade_typed = false;
    // (r50c repair) the rows of the reviews: SmoothUv uint(uv.x * 64), ClipPos uint(pos.x * 100)
    // (both smooth), NoPersp uint(Extra.x) of a no-perspective input, Bary
    // uint(BaryCoordSmooth.x * 16), HandScaled uint(the instance id interpolated by hand * 64),
    // FlatRecip uint(Extra.x * (1 / Extra.w)) of a flat input, Phi a phi of two rows, Quad a quad
    // broadcast of the row; kept: Flat uint(Extra.x) of a flat input, Vertex1 uint(the instance
    // id of vertex 1) (GetAttribute(Instance, 3, 1))
    enum class FadeAt : u8 {
        Instance,
        FragCoord,
        Divide,
        Texel,
        SmoothUv,
        ClipPos,
        NoPersp,
        Bary,
        HandScaled,
        FlatRecip,
        Phi,
        Quad,
        Flat,
        Vertex1
    };
    FadeAt fade_at = FadeAt::Instance; ///< the typed load's row: from the instance id input,
                                       ///< FragCoord.x, pos.x / pos.w, a texel of image 2, ...
    bool instance_smooth = false; ///< (r50c repair) the Info says the instance id input is smooth
};

/// (r50c) The buffer the game's fade is read from (binding 2 in r50_spv/dbeccd9c.glsl).
constexpr u32 FadeBuffer = 2;
/// (r50c repair) An input only the fade's row reads; AnalyzeLowered gives it the interpolation
/// the row's form needs (no-perspective or flat).
constexpr IR::Attribute Extra = IR::Attribute::Param0 + 5;

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
        } else if (f.fade_kind == GameForm::Fade::Alpha) {
            fade = tw;
        } else if (f.fade_kind == GameForm::Fade::Screen) {
            fade = ir.GetAttribute(IR::Attribute::FragCoord, 0);
        } else if (f.fade_kind == GameForm::Fade::Zero || f.fade_kind == GameForm::Fade::Two) {
            fade = ir.Imm32(f.fade_kind == GameForm::Fade::Zero ? 0.0f : 2.0f);
        } else if (f.fade_kind == GameForm::Fade::Inf) {
            fade = ir.Imm32(std::numeric_limits<f32>::infinity());
        } else if (f.fade_kind == GameForm::Fade::Dword) {
            fade = Cb(ir, 3, 30);
        } else if (f.fade_kind == GameForm::Fade::ConstantLane) {
            // a swizzle (0, 1, 0, 0 are lanes 0-3 of the first vector) whose .w is the 1
            const IR::Value load = ir.LoadBufferF32(4, ir.Imm32(FadeBuffer), address, {});
            const IR::Value constants = ir.CompositeConstruct(ir.Imm32(0.0f), ir.Imm32(1.0f),
                                                              ir.Imm32(0.0f), ir.Imm32(0.0f));
            fade = IR::F32{
                ir.CompositeExtract(ir.CompositeShuffle(constants, load, 4, 5, 6, 1), 3)};
        } else if (f.fade_typed) {
            IR::U32 index{address};
            if (f.fade_at == GameForm::FadeAt::FragCoord) {
                index = ir.ConvertFToU(32, ir.GetAttribute(IR::Attribute::FragCoord, 0));
            } else if (f.fade_at == GameForm::FadeAt::Divide) {
                index = ir.ConvertFToU(32, ir.FPDiv(ir.GetAttribute(Position, 0),
                                                    ir.GetAttribute(Position, 3)));
            } else if (f.fade_at == GameForm::FadeAt::Texel) {
                index = ir.ConvertFToU(32, IR::F32{ir.CompositeExtract(
                                               Sample(ir, 2, ir.GetAttribute(Uv, 0),
                                                      ir.GetAttribute(Uv, 1)),
                                               0)});
            } else if (f.fade_at == GameForm::FadeAt::SmoothUv) {
                index = ir.ConvertFToU(32, ir.FPMul(ir.GetAttribute(Uv, 0), ir.Imm32(64.0f)));
            } else if (f.fade_at == GameForm::FadeAt::ClipPos) {
                index = ir.ConvertFToU(32, ir.FPMul(pos(0), ir.Imm32(100.0f)));
            } else if (f.fade_at == GameForm::FadeAt::NoPersp ||
                       f.fade_at == GameForm::FadeAt::Flat) {
                index = ir.ConvertFToU(32, ir.GetAttribute(Extra, 0));
            } else if (f.fade_at == GameForm::FadeAt::Bary) {
                index = ir.ConvertFToU(
                    32, ir.FPMul(ir.GetAttribute(IR::Attribute::BaryCoordSmooth, 0),
                                 ir.Imm32(16.0f)));
            } else if (f.fade_at == GameForm::FadeAt::HandScaled) {
                index =
                    ir.ConvertFToU(32, ir.FPMul(Interpolated(ir, Instance, 3), ir.Imm32(64.0f)));
            } else if (f.fade_at == GameForm::FadeAt::FlatRecip) {
                index = ir.ConvertFToU(32, ir.FPMul(ir.GetAttribute(Extra, 0),
                                                    ir.FPRecip(ir.GetAttribute(Extra, 3))));
            } else if (f.fade_at == GameForm::FadeAt::Phi) {
                // two ways in (the block its own predecessor: only the operands matter here),
                // put at the block's end, where the emitter appends
                const IR::U32 next = ir.IAdd(index, ir.Imm32(1u));
                IR::Block* const block = next.Inst()->GetParent();
                IR::Inst* const phi =
                    &*block->PrependNewInst(block->end(), IR::Opcode::Phi, {}, u32(IR::Type::U32));
                phi->AddPhiOperand(block, index);
                phi->AddPhiOperand(block, next);
                index = IR::U32{IR::Value{phi}};
            } else if (f.fade_at == GameForm::FadeAt::Quad) {
                index = ir.QuadBroadcast(index, ir.Imm32(0u));
            } else if (f.fade_at == GameForm::FadeAt::Vertex1) {
                index = ir.ConvertFToU(32, ir.GetAttribute(Instance, 3, 1));
            }
            // buffer_load_format_xyzw at dword (index + 7) * 4 (the patched address), .w taken
            IR::BufferInstInfo typed{};
            typed.index_enable.Assign(1);
            typed.typed.Assign(1);
            typed.inst_data_fmt.Assign(AmdGpu::DataFormat::Format32_32_32_32);
            typed.inst_num_fmt.Assign(AmdGpu::NumberFormat::Float);
            const IR::U32 dword = ir.IMul(ir.IAdd(index, ir.Imm32(7u)), ir.Imm32(4u));
            fade = IR::F32{
                ir.CompositeExtract(ir.LoadBufferFormat(ir.Imm32(FadeBuffer), dword, typed), 3)};
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
                   "*cb1[0,1]+cb1[2,3], 1 factors of the nonzero term left out (a buffer load; "
                   "repeatable, fade left out)");
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
    assert(line.find("1 factors of the nonzero term ignored (an input; not repeatable)") !=
           std::string::npos);
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

/// (r50c) GameTest as the recompiler hands it to the analysis: after LowerBufferFormatToRaw (a
/// typed load becomes LoadBufferF32x4, its lanes extracted, built again and shuffled by the
/// swizzle) and ConstantPropagationPass, the two passes between the translator and the analysis
/// that change how the fade reads (recompiler.cpp). pass: through CutoutAnalysisPass (the map,
/// the counts, the line), else AnalyzeCutout.
Cutout AnalyzeLowered(const GameForm& f, u64 pgm_hash, bool pass, std::string* line = nullptr) {
    Common::ObjectPool<IR::Inst> pool;
    IR::Block block(pool);
    IR::IREmitter ir(block);
    Info info{};
    info.sw_stage = SwStage::Fragment;
    info.pgm_hash = pgm_hash;
    RuntimeInfo runtime_info{};
    runtime_info.Initialize(HwStage::Fragment, SwStage::Fragment);
    GameInfo(f, info, runtime_info);
    info.buffers.resize(FadeBuffer + 1); // the lowering looks at its load's buffer resource
    if (f.instance_smooth) {
        info.fs_interpolation[u32(Instance) - u32(IR::Attribute::Param0)] = {Qualifier::Smooth,
                                                                             Qualifier::None};
    }
    if (f.fade_at == GameForm::FadeAt::NoPersp) {
        info.fs_interpolation[u32(Extra) - u32(IR::Attribute::Param0)] = {
            Qualifier::NoPerspective, Qualifier::None};
    } else if (f.fade_at == GameForm::FadeAt::Flat || f.fade_at == GameForm::FadeAt::FlatRecip) {
        info.fs_interpolation[u32(Extra) - u32(IR::Attribute::Param0)] = {Qualifier::Flat,
                                                                          Qualifier::None};
    }
    GameTest(ir, f);
    IR::Program program(info);
    program.blocks.push_back(&block);
    program.post_order_blocks.push_back(&block);
    Optimization::LowerBufferFormatToRaw(program);
    Optimization::ConstantPropagationPass(program.post_order_blocks);
    if (f.fade_typed) {
        // the form the analysis must see: the typed load lowered, its shuffle not folded
        u32 format = 0, loads = 0, shuffles = 0;
        for (const IR::Inst& inst : block.Instructions()) {
            format += inst.GetOpcode() == IR::Opcode::LoadBufferFormatF32 ? 1 : 0;
            loads += inst.GetOpcode() == IR::Opcode::LoadBufferF32x4 ? 1 : 0;
            shuffles += inst.GetOpcode() == IR::Opcode::CompositeShuffleF32x4 ? 1 : 0;
        }
        assert(format == 0 && loads == 1 && shuffles == 1);
    }
    if (pass) {
        Optimization::CutoutAnalysisPass(program, runtime_info);
    } else {
        info.cutout = Optimization::AnalyzeCutout(program, runtime_info);
    }
    if (line) {
        *line = Optimization::CutoutLine(info, runtime_info);
    }
    return info.cutout;
}

/// (r50c) The fade of the game's 9 camera pass pixel shaders (a89e01e9, 998b035e, dbeccd9c,
/// 70bb42af, 1c3953c6, 0f54e5f9, 2140da2b, 765450df, 6720ae0d: one form, a per-instance float of
/// a storage buffer read by a typed load), which r50b's log called computed, and the factors that
/// must not be left out of the shadow rule.
void CheckFadeForms() {
    using Fade = GameForm::Fade;
    using FadeAt = GameForm::FadeAt;
    std::string line;
    const std::string left_out =
        ", 1 factors of the nonzero term left out (a buffer load; repeatable, fade left out)";
    // the fade form on each of the alpha forms the 9 shaders have: the colour by hand
    // (dbeccd9c), the position by hand too (1c3953c6), the colour by the hardware (0f54e5f9 and
    // others), the colour first and D sampled first (6720ae0d)
    for (const GameForm& f :
         {GameForm{.fade_typed = true}, GameForm{.manual_position = true, .fade_typed = true},
          GameForm{.manual_colour = false, .fade_typed = true},
          GameForm{.manual_position = true, .colour_first = true, .fade_typed = true}}) {
        const Cutout c = AnalyzeLowered(f, 0xdbeccd9c, false, &line);
        CheckGameRecord(c, true, true, 1); // a buffer load, repeatable with the draw's constants
        assert(line.find(left_out) != std::string::npos);
    }
    std::printf("%s\n", line.c_str());
    // the sun shadow pass forms are not changed by the lowering (no fade)
    Cutout c = AnalyzeLowered({.dither = false, .fade = false}, 0x92852ef3, false);
    CheckGameRecord(c, false, true, 0);

    // the factor the texture's alpha itself (A * T.w): a second texture term, never left out
    c = AnalyzeLowered({.fade_kind = Fade::Alpha}, 0x50c0, false);
    assert(c.verdict != Cutout::Verdict::Matched && c.ignored_factor_terms == 0);
    // ... sampled from another texture, or a typed load at a row a texel gives: several textures
    c = AnalyzeLowered({.fade_textured = true}, 0x50c0, false);
    assert(c.verdict == Cutout::Verdict::SeveralTextures);
    c = AnalyzeLowered({.fade_typed = true, .fade_at = FadeAt::Texel}, 0x50c0, false);
    assert(c.verdict == Cutout::Verdict::SeveralTextures);
    // ... the pixel's position (FragCoord.x), or a typed load at a row that differs across a
    // triangle (r50c repair: the reviews' rows): FragCoord.x, pos.x / pos.w, a smooth uv.x * 64
    // or pos.x * 100, a no-perspective input, the barycentrics alone, the instance id
    // interpolated by hand but scaled before the conversion, a flat input over its own w (the
    // divide refused as a guard), a phi, a quad broadcast: matched, the factor computed, not
    // repeatable, and the line says so
    for (const FadeAt at : {FadeAt::FragCoord, FadeAt::Divide, FadeAt::SmoothUv, FadeAt::ClipPos,
                            FadeAt::NoPersp, FadeAt::Bary, FadeAt::HandScaled, FadeAt::FlatRecip,
                            FadeAt::Phi, FadeAt::Quad}) {
        for (const bool manual : {false, true}) {
            c = AnalyzeLowered({.manual_position = manual, .fade_typed = true, .fade_at = at},
                               0x50c0, false, &line);
            assert(c.verdict == Cutout::Verdict::Matched && c.nonzero);
            assert(c.ignored_factor_terms == 1 && c.ignored_kinds == Cutout::IgnoredComputed);
            assert(!c.RepeatableWithConstants());
            assert(line.find(", 1 factors of the nonzero term ignored (computed; not "
                             "repeatable)") != std::string::npos);
        }
    }
    c = AnalyzeLowered({.fade_kind = Fade::Screen}, 0x50c0, false, &line);
    assert(c.verdict == Cutout::Verdict::Matched && c.ignored_kinds == Cutout::IgnoredComputed);
    assert(!c.RepeatableWithConstants());
    // ... rows that hold one value across a triangle: a flat input, and the instance id of one
    // vertex read as it is (a per-vertex input): a buffer load, left out
    for (const FadeAt at : {FadeAt::Flat, FadeAt::Vertex1}) {
        c = AnalyzeLowered({.fade_typed = true, .fade_at = at}, 0x50c0, false, &line);
        CheckGameRecord(c, true, true, 1);
        assert(line.find(left_out) != std::string::npos);
    }
    // ... the instance id interpolated by hand, but the input smooth (the Info says so): the
    // interpolation is no per-vertex one, so the barycentrics are read: computed
    c = AnalyzeLowered({.fade_typed = true, .instance_smooth = true}, 0x50c0, false);
    assert(c.verdict == Cutout::Verdict::Matched && c.ignored_kinds == Cutout::IgnoredComputed);
    // ... an immediate 0 (the term discards every pixel) or +inf: computed, not repeatable
    for (const Fade kind : {Fade::Zero, Fade::Inf}) {
        c = AnalyzeLowered({.fade_kind = kind}, 0x50c0, false);
        assert(c.verdict == Cutout::Verdict::Matched && c.ignored_kinds == Cutout::IgnoredComputed);
        assert(c.ignored_factor_terms == 1 && !c.RepeatableWithConstants());
    }
    // ... a dword from memory (cb3[30]): a value of the draw the record does not keep, where a
    // 0 hides the draw: dwords and computed, not repeatable (r50c repair)
    c = AnalyzeLowered({.fade_kind = Fade::Dword}, 0x50c0, false, &line);
    assert(c.verdict == Cutout::Verdict::Matched && c.ignored_factor_terms == 1);
    assert(c.ignored_kinds == (Cutout::IgnoredDword | Cutout::IgnoredComputed));
    assert(!c.RepeatableWithConstants());
    assert(line.find(", 1 factors of the nonzero term ignored (dwords/computed; not repeatable)") !=
           std::string::npos);
    // a swizzle's constant 1 in the lane (ThroughComposites into the shuffle's first vector): no
    // factor (r50c repair: as a direct immediate), nothing left out
    c = AnalyzeLowered({.fade_kind = Fade::ConstantLane}, 0x50c0, false, &line);
    assert(c.verdict == Cutout::Verdict::Matched && c.nonzero);
    assert(c.ignored_factor_terms == 0 && c.ignored_kinds == 0 && c.RepeatableWithConstants());
    assert(line.find("factors of the nonzero term") == std::string::npos);
    // a record refused for its coordinates, its fade a buffer load: the line blames no factor
    c = AnalyzeLowered({.uv_scaled_twice = true, .fade_typed = true}, 0x50c0, false, &line);
    assert(c.verdict == Cutout::Verdict::Matched && !c.RepeatableWithConstants());
    assert(c.ignored_kinds == Cutout::IgnoredBuffer);
    assert(line.ends_with(", 1 factors of the nonzero term ignored (a buffer load)"));
    // an immediate 2 is the alpha's own scale (r50b): nothing to leave out
    c = AnalyzeLowered({.fade_kind = Fade::Two}, 0x50c0, false);
    assert(c.verdict == Cutout::Verdict::Matched && c.nonzero && c.ignored_factor_terms == 0);
    assert(c.RepeatableWithConstants());
}

/// (r50c) The 600-frame lines count the records that leave the fade out (after CheckSummary:
/// its records are in the counts, with constants 2 of which 1 leaves the fade out).
void CheckFadeCounts() {
    (void)AnalyzeLowered({.fade_typed = true}, 0x50c1, true);
    (void)AnalyzeLowered({.fade_typed = true, .fade_at = GameForm::FadeAt::FragCoord}, 0x50c2,
                         true);
    Optimization::NoteCutoutCard(0x50c1, 0, Optimization::CutoutCardClass::Plant);
    Optimization::NoteCutoutCard(0x50c2, 0, Optimization::CutoutCardClass::Plant);
    const std::string totals = Optimization::CutoutSummaryText();
    std::printf("%s\n", totals.c_str());
    assert(totals.find(" (r50c: of the 3 repeatable with the draw's constants, 1 leave nothing "
                       "out, 2 leave the fade out:") != std::string::npos);
    const std::string cards = Optimization::CutoutCardsText();
    std::printf("%s\n", cards.c_str());
    assert(cards.find("plants (left out of lamp rays: a skeleton, no sun shadow pass draw) 3 [3 "
                      "match; 1 repeatable, 2 with constants (r50c: 1 with the fade left out); "
                      "3 match,") != std::string::npos);
    // (r50c repair) the draws of every shader once: 0x4321 (5 draws) and 0x50c1 (none yet) read
    // memory constants; 0x1234 has none, 0x50c2 is not repeatable
    const std::string once = "; (r50c) each shader once: 2 with constants read from memory, 5 "
                             "draws: 2 CPU-written, 1 in place, 1 GPU-written, 0 unreadable, 1 "
                             "another permutation;";
    assert(cards.find(once) != std::string::npos);
    // 0x4321 seen as a plant too: the plants' class counts its 5 draws, each shader once does not
    Optimization::NoteCutoutCard(0x4321, 0, Optimization::CutoutCardClass::Plant);
    const std::string twice = Optimization::CutoutCardsText();
    assert(twice.find("plants (left out of lamp rays: a skeleton, no sun shadow pass draw) 4 [") !=
           std::string::npos);
    assert(twice.find("with no memory constants; 5 draws: 2 CPU-written, 1 in place, 1 "
                      "GPU-written, 0 unreadable, 1 another permutation], left out, no skeleton") !=
           std::string::npos);
    assert(twice.find(once) != std::string::npos);

    // (r62b) a record a cache record's CUT1 part restored (NoteCutoutRestored) is kept and
    // counted as an analysed one and counted apart as restored; a second one of the same
    // pgm_hash is not counted again
    Info info{};
    info.sw_stage = SwStage::Fragment;
    info.pgm_hash = 0x62b1;
    info.cutout = *Optimization::FindCutout(0x1234);
    RuntimeInfo runtime_info{};
    runtime_info.Initialize(HwStage::Fragment, SwStage::Fragment);
    runtime_info.hw.fs.num_inputs = 2;
    Optimization::NoteCutoutRestored(info, runtime_info);
    Optimization::NoteCutoutRestored(info, runtime_info);
    const Cutout* restored = Optimization::FindCutout(0x62b1);
    assert(restored && restored->verdict == Cutout::Verdict::Matched);
    const std::string after = Optimization::CutoutSummaryText();
    std::printf("%s\n", after.c_str());
    assert(after.find("analysed (r62b: 1 of them restored from the cache's CUT1 parts instead, "
                      "not compiled) (1 since the last line;") != std::string::npos);
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
                   "alpha factor in2.w (vs out 4, flat), fade left out (1 factors of the nonzero "
                   "term: a buffer load), stored channel a, CPU-written");
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
    // (r62b) the restored records are named right after "analysed": none here
    assert(summary.find("1 pixel shaders compiled in play and analysed (r62b: 0 of them restored "
                        "from the cache's CUT1 parts instead, not compiled) (1 since the last "
                        "line; 1 discarding cache records") != std::string::npos);
    assert(summary.find("of the 1 that discard 1 match") != std::string::npos);
    assert(Optimization::CutoutSummaryText().find("(0 since the last line") != std::string::npos);
    const std::string cards = Optimization::CutoutCardsText();
    // (r50b) the alpha >= 0.5 record names no memory dword: none to read, so not CPU-written
    assert(cards.find("plants (left out of lamp rays: a skeleton, no sun shadow pass draw) 1 [1 "
                      "match; 1 repeatable, 1 with constants (r50c: 0 with the fade left out); 1 "
                      "match, 0 with CPU-written constants on every draw, 1 with no memory "
                      "constants]") != std::string::npos);
    assert(cards.find("kept whole: a skeleton (hair, cloth, characters) 1 [1 not analysed; 0 "
                      "repeatable, 0 with constants (r50c: 0 with the fade left out); 0 match, 0 "
                      "with CPU-written constants on every draw, 0 with no memory constants]") !=
           std::string::npos);
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
    // (r50c) the game's form (0x4321) leaves its fade out: counted so
    assert(totals.find(" (r50c: of the 2 repeatable with the draw's constants, 1 leave nothing "
                       "out, 1 leave the fade out: factors of the nonzero term that are a buffer "
                       "load, which the game's sun shadow pass does not have)") !=
           std::string::npos);
    const char* const no_draws = "left out, no skeleton 1 [1 match; 0 repeatable, 1 with "
                                 "constants (r50c: 1 with the fade left out); 1 match, 0 with "
                                 "CPU-written constants on every draw, 0 with no memory constants]";
    assert(Optimization::CutoutCardsText().find(no_draws) != std::string::npos);
    // a draw of the record with no memory constants: nothing read, still not CPU-written
    assert(Optimization::NoteCutoutConstants(0x1234, Optimization::CutoutConstants::CpuWritten));
    assert(Optimization::CutoutCardsText().find(
               "1 [1 match; 1 repeatable, 1 with constants (r50c: 0 with the fade left out); 1 "
               "match, 0 with CPU-written constants on every draw, 1 with no memory constants]") !=
           std::string::npos);

    // (r50b E7) every draw counted by its state; the first one not of another permutation prints
    using State = Optimization::CutoutConstants;
    assert(!Optimization::NoteCutoutConstants(0x4321, State::OtherPermutation));
    assert(Optimization::NoteCutoutConstants(0x4321, State::CpuWritten));
    assert(!Optimization::NoteCutoutConstants(0x4321, State::CpuWritten));
    std::string text = Optimization::CutoutCardsText();
    assert(text.find("left out, no skeleton 1 [1 match; 0 repeatable, 1 with constants (r50c: 1 "
                     "with the fade left out); 1 match, 1 with CPU-written constants on every "
                     "draw, 0 with no memory constants; 3 "
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
    _set_error_mode(_OUT_TO_STDERR); // (r62b repair) a failed assert prints, no message box
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
    CheckFadeForms();
    CheckReviewProbes();
    CheckPermutation();
    CheckConstantsLine();
    CheckSummary();
    CheckFadeCounts();
    std::printf("rt-card-alpha-test: ok (alpha tests, coordinates, shaders not matched, the "
                "game's forms, the reviews' probes, the fade forms)\n");
    return 0;
}
