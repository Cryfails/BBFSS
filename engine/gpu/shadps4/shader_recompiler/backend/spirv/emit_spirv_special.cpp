// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include "shader_recompiler/backend/spirv/emit_spirv_instructions.h"
#include "shader_recompiler/backend/spirv/spirv_emit_context.h"
#include "shader_recompiler/ir/debug_print.h"
#include "shader_recompiler/ir/microinstruction.h"

namespace Shader::Backend::SPIRV {

void EmitPrologue(EmitContext& ctx) {
    if (ctx.hw_stage == HwStage::Fragment) {
        ctx.DefineAmdPerVertexAttribs();
    }
    if (ctx.info.loads.Get(IR::Attribute::WorkgroupIndex)) {
        ctx.DefineWorkgroupIndex();
    }
    ctx.DefineBufferProperties();
}

void ConvertDepthMode(EmitContext& ctx) {
    const Id type{ctx.F32[1]};
    const Id position{ctx.OpLoad(ctx.F32[4], ctx.output_position)};
    const Id z{ctx.OpCompositeExtract(type, position, 2u)};
    const Id w{ctx.OpCompositeExtract(type, position, 3u)};
    const Id screen_depth{ctx.OpFMul(type, ctx.OpFAdd(type, z, w), ctx.Constant(type, 0.5f))};
    const Id vector{ctx.OpCompositeInsert(ctx.F32[4], screen_depth, position, 2u)};
    ctx.OpStore(ctx.output_position, vector);
}

void ConvertPositionToClipSpace(EmitContext& ctx) {
    ASSERT_MSG(!ctx.info.stores.GetAny(IR::Attribute::ViewportIndex),
               "Multi-viewport with shader clip space conversion not yet implemented.");

    const Id type{ctx.F32[1]};
    Id position{ctx.OpLoad(ctx.F32[4], ctx.output_position)};
    const Id x{ctx.OpCompositeExtract(type, position, 0u)};
    const Id y{ctx.OpCompositeExtract(type, position, 1u)};
    const Id z{ctx.OpCompositeExtract(type, position, 2u)};
    const Id w{ctx.OpCompositeExtract(type, position, 3u)};
    const Id xoffset_ptr{ctx.OpAccessChain(ctx.TypePointer(spv::StorageClass::PushConstant, type),
                                           ctx.push_data_block,
                                           ctx.ConstU32(PushData::XOffsetIndex))};
    const Id xoffset{ctx.OpLoad(type, xoffset_ptr)};
    const Id yoffset_ptr{ctx.OpAccessChain(ctx.TypePointer(spv::StorageClass::PushConstant, type),
                                           ctx.push_data_block,
                                           ctx.ConstU32(PushData::YOffsetIndex))};
    const Id yoffset{ctx.OpLoad(type, yoffset_ptr)};
    const Id xscale_ptr{ctx.OpAccessChain(ctx.TypePointer(spv::StorageClass::PushConstant, type),
                                          ctx.push_data_block,
                                          ctx.ConstU32(PushData::XScaleIndex))};
    const Id xscale{ctx.OpLoad(type, xscale_ptr)};
    const Id yscale_ptr{ctx.OpAccessChain(ctx.TypePointer(spv::StorageClass::PushConstant, type),
                                          ctx.push_data_block,
                                          ctx.ConstU32(PushData::YScaleIndex))};
    const Id yscale{ctx.OpLoad(type, yscale_ptr)};
    const Id vport_w =
        ctx.Constant(type, float(std::min<u32>(ctx.profile.max_viewport_width / 2, 8_KB)));
    const Id wnd_x = ctx.OpFAdd(type, ctx.OpFMul(type, x, xscale), xoffset);
    const Id ndc_x = ctx.OpFSub(type, ctx.OpFDiv(type, wnd_x, vport_w), ctx.Constant(type, 1.f));
    const Id vport_h =
        ctx.Constant(type, float(std::min<u32>(ctx.profile.max_viewport_height / 2, 8_KB)));
    const Id wnd_y = ctx.OpFAdd(type, ctx.OpFMul(type, y, yscale), yoffset);
    const Id ndc_y = ctx.OpFSub(type, ctx.OpFDiv(type, wnd_y, vport_h), ctx.Constant(type, 1.f));
    const Id vector{ctx.OpCompositeConstruct(ctx.F32[4], std::array<Id, 4>({ndc_x, ndc_y, z, w}))};
    ctx.OpStore(ctx.output_position, vector);
}

// bbport: object motion vectors (runtime_info.h, MotionVectors). The vertex shader stores its
// clip position for this frame and loads the one of the previous frame (same draw, same
// vertex), both by buffer device address. Disabled accesses are branched around: a shared
// scratch element would race between all the inactive vertex invocations.
static void EmitVertexMotion(EmitContext& ctx) {
    const Id u32_type = ctx.U32[1];
    const Id position = ctx.OpLoad(ctx.F32[4], ctx.output_position);
    const Id param_ptr = ctx.OpAccessChain(ctx.TypePointer(spv::StorageClass::PushConstant, u32_type),
                                           ctx.push_data_block,
                                           ctx.ConstU32(PushData::MotionParamIndex));
    Id param_index = ctx.OpLoad(u32_type, param_ptr);
    if (MotionVectors::Kind(ctx.runtime_info.hw.vs.motion_vectors) == MotionVectors::VertexBoth) {
        param_index = ctx.OpBitwiseAnd(u32_type, param_index, ctx.ConstU32(0xffffU));
    }
    param_index = ctx.OpSelect(u32_type,
                               ctx.OpULessThan(ctx.U1[1], param_index, ctx.ConstU32(MotionVectors::ParamsCapacity)),
                               param_index, ctx.u32_zero_value);
    // Load process-local addresses through a descriptor, never SPIR-V constants. Physical
    // addressing keeps the existing history capacity (larger than the minimum SSBO range).
    const auto load_address = [&](u32 member) {
        const Id pointer = ctx.TypePointer(spv::StorageClass::Uniform, ctx.U64);
        return ctx.OpLoad(ctx.U64, ctx.OpAccessChain(pointer, ctx.motion_addresses,
                                                    ctx.ConstU32(member)));
    };
    const Id params_address = load_address(0);
    const Id positions_address = load_address(1);
    const auto address = [&](Id base, Id index, u32 stride) {
        return ctx.OpIAdd(ctx.U64, base,
                          ctx.OpIMul(ctx.U64, ctx.OpUConvert(ctx.U64, index),
                                     ctx.Constant(ctx.U64, u64(stride))));
    };
    const Id u32x4_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, ctx.U32[4]);
    const Id f32x4_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, ctx.F32[4]);
    const Id params = ctx.OpLoad(
        ctx.U32[4],
        ctx.OpConvertUToPtr(u32x4_ptr, address(params_address, param_index, 32)),
        spv::MemoryAccessMask::Aligned, 16u);
    const Id store_base = ctx.OpCompositeExtract(u32_type, params, 0u);
    const Id load_base = ctx.OpCompositeExtract(u32_type, params, 1u);
    const Id vertices = ctx.OpCompositeExtract(u32_type, params, 2u);
    const Id flags = ctx.OpCompositeExtract(u32_type, params, 3u);
    const Id offsets = ctx.OpLoad(
        ctx.U32[4], ctx.OpConvertUToPtr(u32x4_ptr,
            ctx.OpIAdd(ctx.U64, address(params_address, param_index, 32),
                       ctx.Constant(ctx.U64, u64{16}))),
        spv::MemoryAccessMask::Aligned, 16u);
    const Id first_vertex = ctx.OpCompositeExtract(u32_type, offsets, 0u);
    const Id first_instance = ctx.OpCompositeExtract(u32_type, offsets, 1u);
    const Id instances = ctx.OpCompositeExtract(u32_type, offsets, 2u);
    const Id vertex = ctx.OpISub(u32_type, ctx.OpLoad(u32_type, ctx.vertex_index), first_vertex);
    const Id instance = ctx.OpISub(u32_type, ctx.OpLoad(u32_type, ctx.instance_id), first_instance);
    const Id bool_type = ctx.U1[1];
    const Id in_range = ctx.OpLogicalAnd(bool_type, ctx.OpULessThan(bool_type, vertex, vertices),
                                         ctx.OpULessThan(bool_type, instance, instances));
    const Id slot = ctx.OpIAdd(u32_type, vertex, ctx.OpIMul(u32_type, instance, vertices));
    const auto flag = [&](u32 bit) {
        return ctx.OpLogicalAnd(
            bool_type, in_range,
            ctx.OpINotEqual(bool_type, ctx.OpBitwiseAnd(u32_type, flags, ctx.ConstU32(bit)),
                            ctx.u32_zero_value));
    };
    const Id do_store = flag(MotionVectors::FlagStore);
    const Id do_load = flag(MotionVectors::FlagLoad);
    const Id store_label = ctx.OpLabel();
    const Id store_merge = ctx.OpLabel();
    ctx.OpSelectionMerge(store_merge, spv::SelectionControlMask::MaskNone);
    ctx.OpBranchConditional(do_store, store_label, store_merge);
    ctx.AddLabel(store_label);
    const Id store_address = address(positions_address,
                                     ctx.OpIAdd(u32_type, store_base, slot), 16);
    // Indexed draws may invoke the same vertex more than once. Atomic component stores
    // avoid write/write races; all these invocations produce the same clip position.
    const Id scalar_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, u32_type);
    const Id scope = ctx.ConstU32(static_cast<u32>(spv::Scope::Device));
    for (u32 i = 0; i < 4; ++i) {
        const Id ptr = ctx.OpConvertUToPtr(scalar_ptr,
            ctx.OpIAdd(ctx.U64, store_address, ctx.Constant(ctx.U64, u64(i * 4))));
        const Id bits = ctx.OpBitcast(u32_type, ctx.OpCompositeExtract(ctx.F32[1], position, i));
        ctx.OpAtomicExchange(u32_type, ptr, scope, ctx.u32_zero_value, bits);
    }
    ctx.OpBranch(store_merge);
    ctx.AddLabel(store_merge);

    const Id load_label = ctx.OpLabel();
    const Id load_merge = ctx.OpLabel();
    ctx.OpSelectionMerge(load_merge, spv::SelectionControlMask::MaskNone);
    ctx.OpBranchConditional(do_load, load_label, load_merge);
    ctx.AddLabel(load_label);
    const Id loaded = ctx.OpLoad(
        ctx.F32[4], ctx.OpConvertUToPtr(f32x4_ptr, address(positions_address,
            ctx.OpIAdd(u32_type, load_base, slot), 16)), spv::MemoryAccessMask::Aligned, 16u);
    ctx.OpBranch(load_merge);
    ctx.AddLabel(load_merge);
    Id previous = ctx.OpPhi(ctx.F32[4], position, store_merge, loaded, load_label);
    const Id valid = ctx.OpSelect(ctx.F32[1], do_load, ctx.Constant(ctx.F32[1], 1.0f),
                                  ctx.Constant(ctx.F32[1], 0.0f));
    previous = ctx.OpCompositeInsert(ctx.F32[4], valid, previous, 2u);
    ctx.OpStore(ctx.motion_out_cur, position);
    ctx.OpStore(ctx.motion_out_prev, previous);
}

// bbport (r54_leaf-stage2): with the card UVs (MotionVectors::CaptureUv, BB_RT_CARD_ALPHA=1) a
// capture whose param names a place in the ring (word 1, the ring index + 1; 0: none) also
// stores per vertex what a cut-out pixel shader samples its alpha at and multiplies it by: two
// components of one output (u, v) and one of another (the alpha factor, 1.0 without one), which
// word 7 names (Vulkan::PackCardSelector: bits 0-4 the uv output, 5-6 and 7-8 its components,
// 9-13 the alpha factor's output, 14-15 its component, 16 an alpha factor at all, 31 set). The
// outputs are the ones this shader wrote, read back before the epilogue's other work; an output
// that is an integer, an array or the emulated clip distances is left out of the choice. Where
// the selector names an output this shader does not have or that is left out, or a component
// past the output's own
// ones, the value stored is MotionVectors::CaptureUvUnset (a NaN, CARD_UV_RING_UNSET), never a
// 0: the expand pass then marks the triangle not finite. (With clip distance emulation the
// clip distances may take a real output's slot, spirv_emit_context.cpp; that output then reads
// as not finite too.) No local variable may be declared here (past the function's first block):
// the choice is a chain of selects. Indexed draws may run a vertex more than once; every run
// stores the same values, as the position store above does. This is the recompiler's capture:
// a capture vertex shader with CaptureUv is never replaced by the lifter's (CompileModule).
static void EmitCardUvStore(EmitContext& ctx, Id ring_address, Id params, Id offsets, Id slot) {
    const Id u32_type = ctx.U32[1];
    const Id f32_type = ctx.F32[1];
    const Id bool_type = ctx.U1[1];
    const Id uv_word = ctx.OpCompositeExtract(u32_type, params, 1u);
    const Id selector = ctx.OpCompositeExtract(u32_type, offsets, 3u);
    const Id wanted = ctx.OpLogicalAnd(
        bool_type, ctx.OpINotEqual(bool_type, uv_word, ctx.u32_zero_value),
        ctx.OpINotEqual(bool_type, ctx.OpBitwiseAnd(u32_type, selector, ctx.ConstU32(0x80000000u)),
                        ctx.u32_zero_value));
    const Id uv_label = ctx.OpLabel();
    const Id uv_merge = ctx.OpLabel();
    ctx.OpSelectionMerge(uv_merge, spv::SelectionControlMask::MaskNone);
    ctx.OpBranchConditional(wanted, uv_label, uv_merge);
    ctx.AddLabel(uv_label);
    const auto field = [&](u32 offset, u32 count) {
        return ctx.OpBitFieldUExtract(u32_type, selector, ctx.ConstU32(offset), ctx.ConstU32(count));
    };
    const Id uv_out = field(0u, 5u);
    const Id comp_u = field(5u, 2u);
    const Id comp_v = field(7u, 2u);
    const Id alpha_out = field(9u, 5u);
    const Id alpha_comp = field(14u, 2u);
    const Id has_alpha = ctx.OpINotEqual(bool_type, field(16u, 1u), ctx.u32_zero_value);
    const Id one = ctx.Constant(f32_type, 1.0f);
    const Id unset = ctx.OpBitcast(f32_type, ctx.ConstU32(MotionVectors::CaptureUvUnset));
    const Id unset4 =
        ctx.OpCompositeConstruct(ctx.F32[4], std::array<Id, 4>{unset, unset, unset, unset});
    Id uv_vector = unset4;
    Id alpha_vector = unset4;
    for (u32 i = 0; i < IR::NumParams; ++i) {
        const auto& output = ctx.output_params[i];
        if (!Sirit::ValidId(output.id) || output.is_integer || output.is_array ||
            output.id.value == ctx.clip_distances.value || output.num_components < 1 ||
            output.num_components > 4) {
            continue;
        }
        const u32 n = output.num_components;
        const Id loaded = ctx.OpLoad(ctx.F32[n], output.id);
        Id vector = loaded;
        if (n != 4) {
            std::array<Id, 4> parts{unset, unset, unset, unset};
            for (u32 c = 0; c < n; ++c) {
                parts[c] = n == 1 ? loaded : ctx.OpCompositeExtract(f32_type, loaded, c);
            }
            vector = ctx.OpCompositeConstruct(ctx.F32[4], parts);
        }
        uv_vector = ctx.OpSelect(ctx.F32[4], ctx.OpIEqual(bool_type, uv_out, ctx.ConstU32(i)), vector,
                                 uv_vector);
        alpha_vector = ctx.OpSelect(ctx.F32[4], ctx.OpIEqual(bool_type, alpha_out, ctx.ConstU32(i)),
                                    vector, alpha_vector);
    }
    const Id u = ctx.OpVectorExtractDynamic(f32_type, uv_vector, comp_u);
    const Id v = ctx.OpVectorExtractDynamic(f32_type, uv_vector, comp_v);
    const Id a = ctx.OpSelect(f32_type, has_alpha,
                              ctx.OpVectorExtractDynamic(f32_type, alpha_vector, alpha_comp), one);
    const Id index = ctx.OpIAdd(u32_type, ctx.OpISub(u32_type, uv_word, ctx.ConstU32(1u)), slot);
    const Id base = ctx.OpIAdd(
        ctx.U64, ring_address,
        ctx.OpIMul(ctx.U64, ctx.OpUConvert(ctx.U64, index),
                   ctx.Constant(ctx.U64, u64(MotionVectors::CaptureUvStride))));
    const Id f32_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, f32_type);
    const std::array<Id, 3> values{u, v, a};
    for (u32 k = 0; k < 3; ++k) {
        const Id ptr = ctx.OpConvertUToPtr(
            f32_ptr, ctx.OpIAdd(ctx.U64, base, ctx.Constant(ctx.U64, u64(k * 4))));
        ctx.OpStore(ptr, values[k], spv::MemoryAccessMask::Aligned, 4u);
    }
    ctx.OpBranch(uv_merge);
    ctx.AddLabel(uv_merge);
}

static void EmitVertexCapture(EmitContext& ctx) {
    const Id u32_type = ctx.U32[1];
    const Id position = ctx.OpLoad(ctx.F32[4], ctx.output_position);
    const Id param_ptr = ctx.OpAccessChain(ctx.TypePointer(spv::StorageClass::PushConstant, u32_type),
                                           ctx.push_data_block,
                                           ctx.ConstU32(PushData::MotionParamIndex));
    const bool both =
        MotionVectors::Kind(ctx.runtime_info.hw.vs.motion_vectors) == MotionVectors::VertexBoth;
    Id param_index = ctx.OpLoad(u32_type, param_ptr);
    if (both) {
        param_index = ctx.OpShiftRightLogical(u32_type, param_index, ctx.ConstU32(16U));
    }
    param_index = ctx.OpSelect(u32_type,
                               ctx.OpULessThan(ctx.U1[1], param_index, ctx.ConstU32(MotionVectors::CaptureParamsCapacity)),
                               param_index, ctx.u32_zero_value);
    const auto load_address = [&](u32 member) {
        const Id pointer = ctx.TypePointer(spv::StorageClass::Uniform, ctx.U64);
        return ctx.OpLoad(ctx.U64, ctx.OpAccessChain(pointer, ctx.motion_addresses,
                                                    ctx.ConstU32(member)));
    };
    const Id params_address = load_address(both ? 2 : 0);
    const Id positions_address = load_address(both ? 3 : 1);
    const auto address = [&](Id base, Id index, u32 stride) {
        return ctx.OpIAdd(ctx.U64, base,
                          ctx.OpIMul(ctx.U64, ctx.OpUConvert(ctx.U64, index),
                                     ctx.Constant(ctx.U64, u64(stride))));
    };
    const Id u32x4_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, ctx.U32[4]);
    const Id f32x4_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, ctx.F32[4]);
    const Id params = ctx.OpLoad(
        ctx.U32[4],
        ctx.OpConvertUToPtr(u32x4_ptr, address(params_address, param_index, 32)),
        spv::MemoryAccessMask::Aligned, 16u);
    const Id offsets = ctx.OpLoad(
        ctx.U32[4], ctx.OpConvertUToPtr(u32x4_ptr,
            ctx.OpIAdd(ctx.U64, address(params_address, param_index, 32),
                       ctx.Constant(ctx.U64, u64{16}))),
        spv::MemoryAccessMask::Aligned, 16u);
    const Id store_base = ctx.OpCompositeExtract(u32_type, params, 0u);
    const Id vertices = ctx.OpCompositeExtract(u32_type, params, 2u);
    const Id first_vertex = ctx.OpCompositeExtract(u32_type, offsets, 0u);
    const Id first_instance = ctx.OpCompositeExtract(u32_type, offsets, 1u);
    const Id instances = ctx.OpCompositeExtract(u32_type, offsets, 2u);
    const Id vertex = ctx.OpISub(u32_type, ctx.OpLoad(u32_type, ctx.vertex_index), first_vertex);
    const Id instance = ctx.OpISub(u32_type, ctx.OpLoad(u32_type, ctx.instance_id), first_instance);
    const Id bool_type = ctx.U1[1];
    const Id in_range = ctx.OpLogicalAnd(bool_type, ctx.OpULessThan(bool_type, vertex, vertices),
                                         ctx.OpULessThan(bool_type, instance, instances));
    const Id slot = ctx.OpIAdd(u32_type, vertex, ctx.OpIMul(u32_type, instance, vertices));
    const Id store_label = ctx.OpLabel();
    const Id store_merge = ctx.OpLabel();
    ctx.OpSelectionMerge(store_merge, spv::SelectionControlMask::MaskNone);
    ctx.OpBranchConditional(in_range, store_label, store_merge);
    ctx.AddLabel(store_label);
    ctx.OpStore(ctx.OpConvertUToPtr(f32x4_ptr, address(positions_address,
                                                       ctx.OpIAdd(u32_type, store_base, slot), 16)),
                position, spv::MemoryAccessMask::Aligned, 16u);
    // bbport (r54_leaf-stage2): and the card UVs (EmitCardUvStore), with CaptureUv only
    if ((ctx.runtime_info.hw.vs.motion_vectors & MotionVectors::CaptureUv) != 0) {
        EmitCardUvStore(ctx, load_address(both ? 4 : 2), params, offsets, slot);
    }
    ctx.OpBranch(store_merge);
    ctx.AddLabel(store_merge);
}

// Screen-space motion (previous minus current, pixels) through the viewport scale; z = valid.
static void EmitFragmentMotion(EmitContext& ctx) {
    const Id f32_type = ctx.F32[1];
    const Id current = ctx.OpLoad(ctx.F32[4], ctx.motion_in_cur);
    const Id previous = ctx.OpLoad(ctx.F32[4], ctx.motion_in_prev);
    const auto push = [&](u32 index) {
        return ctx.OpLoad(f32_type, ctx.OpAccessChain(ctx.TypePointer(spv::StorageClass::PushConstant,
                                                                 f32_type),
                                                 ctx.push_data_block, ctx.ConstU32(index)));
    };
    const Id xscale = push(PushData::XScaleIndex);
    const Id yscale = push(PushData::YScaleIndex);
    const auto ndc = [&](Id clip, u32 component) {
        return ctx.OpFDiv(f32_type, ctx.OpCompositeExtract(f32_type, clip, component),
                          ctx.OpCompositeExtract(f32_type, clip, 3u));
    };
    const Id dx = ctx.OpFMul(f32_type, ctx.OpFSub(f32_type, ndc(previous, 0u), ndc(current, 0u)), xscale);
    const Id dy = ctx.OpFMul(f32_type, ctx.OpFSub(f32_type, ndc(previous, 1u), ndc(current, 1u)), yscale);
    const Id zero = ctx.Constant(f32_type, 0.0f);
    const Id epsilon = ctx.Constant(f32_type, 1e-5f);
    const Id front = ctx.OpLogicalAnd(ctx.U1[1],
        ctx.OpFOrdGreaterThan(ctx.U1[1], ctx.OpCompositeExtract(f32_type, previous, 3u), epsilon),
        ctx.OpFOrdGreaterThan(ctx.U1[1], ctx.OpCompositeExtract(f32_type, current, 3u), epsilon));
    const Id valid = ctx.OpSelect(f32_type, front,
                                  ctx.OpCompositeExtract(f32_type, previous, 2u), zero);
    // Uninstrumented draws can overwrite the final scene depth after this pixel was
    // written. Preserve depth so the compose pass can reject an occluded vector.
    const Id depth = ctx.OpCompositeExtract(f32_type,
                                            ctx.OpLoad(ctx.F32[4], ctx.frag_coord), 2u);
    ctx.OpStore(ctx.motion_frag_out,
                ctx.OpCompositeConstruct(ctx.F32[4], std::array<Id, 4>{
                    ctx.OpSelect(f32_type, front, dx, zero),
                    ctx.OpSelect(f32_type, front, dy, zero), valid, depth}));
}

void EmitEpilogue(EmitContext& ctx) {
    if (Sirit::ValidId(ctx.motion_out_cur)) {
        EmitVertexMotion(ctx);
    }
    if (ctx.VertexMotion() && (ctx.runtime_info.hw.vs.motion_vectors & MotionVectors::VertexCapture)) {
        EmitVertexCapture(ctx);
    }
    if (Sirit::ValidId(ctx.motion_frag_out)) {
        EmitFragmentMotion(ctx);
    }
    if (ctx.hw_stage == HwStage::Vertex &&
        ctx.runtime_info.hw.vs.emulate_depth_negative_one_to_one) {
        ConvertDepthMode(ctx);
    }
    if (ctx.hw_stage == HwStage::Vertex && ctx.runtime_info.hw.vs.clip_disable) {
        ConvertPositionToClipSpace(ctx);
    }
}

void EmitDiscard(EmitContext& ctx) {
    ctx.OpDemoteToHelperInvocationEXT();
}

void EmitDiscardCond(EmitContext& ctx, Id condition) {
    const Id kill_label{ctx.OpLabel()};
    const Id merge_label{ctx.OpLabel()};
    ctx.OpSelectionMerge(merge_label, spv::SelectionControlMask::MaskNone);
    ctx.OpBranchConditional(condition, kill_label, merge_label);
    ctx.AddLabel(kill_label);
    ctx.OpDemoteToHelperInvocationEXT();
    ctx.OpBranch(merge_label);
    ctx.AddLabel(merge_label);
}

void EmitEmitVertex(EmitContext& ctx) {
    ctx.OpEmitVertex();
}

void EmitEmitPrimitive(EmitContext& ctx) {
    ctx.OpEndPrimitive();
}

void EmitEmitVertex(EmitContext& ctx, const IR::Value& stream) {
    UNREACHABLE_MSG("Geometry streams");
}

void EmitEndPrimitive(EmitContext& ctx, const IR::Value& stream) {
    UNREACHABLE_MSG("Geometry streams");
}

void EmitDebugPrint(EmitContext& ctx, IR::Inst* inst, Id fmt, Id arg0, Id arg1, Id arg2, Id arg3) {
    IR::DebugPrintFlags flags = inst->Flags<IR::DebugPrintFlags>();
    std::array<Id, IR::DEBUGPRINT_NUM_FORMAT_ARGS> fmt_args = {arg0, arg1, arg2, arg3};
    auto fmt_args_span = std::span<Id>(fmt_args.begin(), fmt_args.begin() + flags.num_args);
    ctx.OpDebugPrintf(fmt, fmt_args_span);
}

Id EmitMemtime(EmitContext& ctx) {
    if (ctx.profile.supports_shader_subgroup_clock) {
        return ctx.OpReadClockKHR(ctx.U64, ctx.ConstU32(std::to_underlying(spv::Scope::Subgroup)));
    } else {
        return ctx.Constant(ctx.U64, 1U);
    }
}

} // namespace Shader::Backend::SPIRV
