// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include "shader_recompiler/backend/spirv/emit_spirv_instructions.h"
#include "shader_recompiler/backend/spirv/spirv_emit_context.h"
#include "shader_recompiler/ir/debug_print.h"
#include "shader_recompiler/ir/microinstruction.h"
#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)
#include "bbport_wind_shelter.h" // bbport (r117_wind-shelter)
#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)
#include "bbport_wind_twigs.h" // bbport (r89d_tree-twigs)

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
// stores the same values, as the position store above does. This is the recompiler's capture,
// used only where the lifter declines one or is off (r62c_leaf-stage3-fix: the lifter's
// VertexCapture stores the same values; this one made broken BLAS input, r62d).
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
    // bbport (r62b_leaf-stage3-followups): a fourth value, another component of the alpha
    // factor's output (MotionVectors::CaptureUvOther: .y where the factor is .x, else .x; unset
    // without a factor, or past the output's components). Only the log reads it: it tells a
    // vertex alpha of 1 from a component that is 1 for another reason.
    const Id other_comp =
        ctx.OpSelect(u32_type, ctx.OpIEqual(bool_type, alpha_comp, ctx.u32_zero_value),
                     ctx.ConstU32(1u), ctx.u32_zero_value);
    const Id other = ctx.OpSelect(
        f32_type, has_alpha, ctx.OpVectorExtractDynamic(f32_type, alpha_vector, other_comp), unset);
    const Id index = ctx.OpIAdd(u32_type, ctx.OpISub(u32_type, uv_word, ctx.ConstU32(1u)), slot);
    const Id base = ctx.OpIAdd(
        ctx.U64, ring_address,
        ctx.OpIMul(ctx.U64, ctx.OpUConvert(ctx.U64, index),
                   ctx.Constant(ctx.U64, u64(MotionVectors::CaptureUvStride))));
    const Id f32_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, f32_type);
    const std::array<Id, 4> values{u, v, a, other}; // (r62b) CaptureUvStride: 16 bytes
    static_assert(MotionVectors::CaptureUvStride == 16 && MotionVectors::CaptureUvOther(0) == 1 &&
                  MotionVectors::CaptureUvOther(3) == 0);
    for (u32 k = 0; k < 4; ++k) {
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

// bbport (r89_wind-foliage-sway): with MotionVectors::Sway (BB_WIND=1 and BB_WIND_SWAY above 0;
// a motion pipeline whose pixel shader discards) a draw whose motion param word 7 has
// BbWindSway::WordOn set is a plant (Rasterizer::WindSwayWord): its clip position is moved by the
// wind before the motion store and the capture read it, and the vertex offers its world height
// to its mesh's base slot (an atomic minimum, only when lower). bbport_wind_sway.h holds the rule
// and its layout; BbWindSway::Displace is this code in C++ and the lifter's VertexSway the same
// in the lifter. Every other draw (word 7 is 0) branches around it. No local variable: the
// results are stored inside the branch.
static void EmitVertexSway(EmitContext& ctx) {
    namespace W = BbWindSway;
    const Id u32_type = ctx.U32[1];
    const Id f32_type = ctx.F32[1];
    const Id bool_type = ctx.U1[1];
    const Id param_ptr = ctx.OpAccessChain(ctx.TypePointer(spv::StorageClass::PushConstant, u32_type),
                                           ctx.push_data_block,
                                           ctx.ConstU32(PushData::MotionParamIndex));
    Id param_index = ctx.OpLoad(u32_type, param_ptr);
    if (MotionVectors::Kind(ctx.runtime_info.hw.vs.motion_vectors) == MotionVectors::VertexBoth) {
        param_index = ctx.OpBitwiseAnd(u32_type, param_index, ctx.ConstU32(0xffffU));
    }
    param_index = ctx.OpSelect(u32_type,
                               ctx.OpULessThan(bool_type, param_index,
                                               ctx.ConstU32(MotionVectors::ParamsCapacity)),
                               param_index, ctx.u32_zero_value);
    const Id params_address = ctx.OpLoad(
        ctx.U64, ctx.OpAccessChain(ctx.TypePointer(spv::StorageClass::Uniform, ctx.U64),
                                   ctx.motion_addresses, ctx.ConstU32(0u)));
    const Id u32x4_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, ctx.U32[4]);
    const Id f32x4_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, ctx.F32[4]);
    const Id u32_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, u32_type);
    const Id f32_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, f32_type);
    const auto at = [&](Id base, u64 bytes) {
        return ctx.OpIAdd(ctx.U64, base, ctx.Constant(ctx.U64, bytes));
    };
    const auto scaled = [&](Id base, Id index, u64 stride) {
        return ctx.OpIAdd(ctx.U64, base,
                          ctx.OpIMul(ctx.U64, ctx.OpUConvert(ctx.U64, index),
                                     ctx.Constant(ctx.U64, stride)));
    };
    const Id offsets = ctx.OpLoad(
        ctx.U32[4],
        ctx.OpConvertUToPtr(u32x4_ptr, at(scaled(params_address, param_index, 32u), 16u)),
        spv::MemoryAccessMask::Aligned, 16u);
    const Id word = ctx.OpCompositeExtract(u32_type, offsets, 3u);
    const Id on = ctx.OpINotEqual(bool_type, ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(W::WordOn)),
                                  ctx.u32_zero_value);
    const Id sway_label = ctx.OpLabel();
    const Id sway_merge = ctx.OpLabel();
    ctx.OpSelectionMerge(sway_merge, spv::SelectionControlMask::MaskNone);
    ctx.OpBranchConditional(on, sway_label, sway_merge);
    ctx.AddLabel(sway_label);
    const auto field = [&](u32 offset, u32 count) {
        return ctx.OpBitFieldUExtract(u32_type, word, ctx.ConstU32(offset), ctx.ConstU32(count));
    };
    const auto f = [&](float value) { return ctx.Constant(f32_type, value); };
    const Id region = at(params_address, u64(MotionVectors::ParamsCapacity) * 32u);
    const Id view_index = ctx.OpIAdd(u32_type, ctx.OpIMul(u32_type, field(0u, 2u), ctx.ConstU32(W::Views)),
                                     field(2u, 1u));
    const Id view = scaled(region, view_index, u64(W::ViewWords) * 4u);
    const Id base_ptr = ctx.OpConvertUToPtr(u32_ptr, scaled(at(region, u64(W::BaseAt) * 4u),
                                                            field(3u, 10u), 4u));
    const Id ramp = ctx.OpFMul(f32_type, ctx.OpConvertUToF(f32_type, field(16u, 8u)), f(1.0f / 255.0f));
    const auto row = [&](u32 word_at) {
        return ctx.OpLoad(ctx.F32[4], ctx.OpConvertUToPtr(f32x4_ptr, at(view, u64(word_at) * 4u)),
                          spv::MemoryAccessMask::Aligned, 16u);
    };
    const auto comp = [&](Id vec, u32 i) { return ctx.OpCompositeExtract(f32_type, vec, i); };
    const auto add = [&](Id a, Id b) { return ctx.OpFAdd(f32_type, a, b); };
    const auto sub = [&](Id a, Id b) { return ctx.OpFSub(f32_type, a, b); };
    const auto mul = [&](Id a, Id b) { return ctx.OpFMul(f32_type, a, b); };
    const auto wrap = [&](Id a) {
        return sub(a, mul(f(W::TwoPi), ctx.OpFloor(f32_type, add(mul(a, f(W::InvTwoPi)), f(0.5f)))));
    };
    const Id position = ctx.OpLoad(ctx.F32[4], ctx.output_position);
    const Id wind_a = row(W::WindA);
    // x and z relative to the camera; y in the world (plus the camera's height, WindA.z)
    const Id rx = ctx.OpDot(f32_type, row(W::ToWorldAt), position);
    const Id wy = add(ctx.OpDot(f32_type, row(W::ToWorldAt + 4), position), comp(wind_a, 2u));
    const Id rz = ctx.OpDot(f32_type, row(W::ToWorldAt + 8), position);
    const Id wind_b = row(W::WindB);
    const Id wind_c = row(W::WindC);
    const Id wind_d = row(W::WindD);
    const Id wind_e = row(W::WindE);
    const Id stored = ctx.OpLoad(u32_type, base_ptr, spv::MemoryAccessMask::Aligned, 4u);
    // bbport (r89c_wind-lean): the mesh's crown key (W::CrownAt: its highest world y so far)
    const Id crown_ptr = ctx.OpConvertUToPtr(u32_ptr, scaled(at(region, u64(W::CrownAt) * 4u),
                                                             field(3u, 10u), 4u));
    const Id crown = ctx.OpLoad(u32_type, crown_ptr, spv::MemoryAccessMask::Aligned, 4u);
    // bbport (r89d_tree-twigs): with BB_WIND_TWIGS on (read once; such sway code has its own shader
    // cache version) the mesh's box keys (BbWindTwigs::TwigAt: lowest x, highest x, lowest z, highest
    // z, four words a base slot): loaded here, offered to below. Off: nothing is emitted.
    const bool twig_on = BbWindTwigs::On();
    Id twig_addr{}, tk_x0{}, tk_x1{}, tk_z0{}, tk_z1{};
    const auto twig_word = [&](u64 bytes) {
        return ctx.OpConvertUToPtr(u32_ptr, at(twig_addr, bytes));
    };
    if (twig_on) {
        twig_addr = scaled(at(region, u64(BbWindTwigs::TwigAt) * 4u), field(3u, 10u), 16u);
        const auto twig_key = [&](u64 bytes) {
            return ctx.OpLoad(u32_type, twig_word(bytes), spv::MemoryAccessMask::Aligned, 4u);
        };
        tk_x0 = twig_key(0u);
        tk_x1 = twig_key(4u);
        tk_z0 = twig_key(8u);
        tk_z1 = twig_key(12u);
    }
    const Id h = sub(wy, sub(ctx.OpBitcast(f32_type, stored), f(W::HeightBias)));
    const Id zero = f(0.0f);
    const Id fin = ctx.OpFOrdLessThan(
        bool_type,
        add(add(ctx.OpFAbs(f32_type, h), ctx.OpFAbs(f32_type, rx)), ctx.OpFAbs(f32_type, rz)),
        f(W::FiniteMost));
    const Id t = ctx.OpFClamp(f32_type, mul(h, comp(wind_d, 0u)), zero, f(1.0f));
    // bbport (r89c_wind-lean): with the lean (RippleD.y 1) a tall mesh takes the tree weight
    // (BbWindSway::Displace)
    const Id lean_d = row(W::RippleD);
    const Id lean = comp(lean_d, 1u);
    const Id mesh = sub(sub(f(W::HeightBias), ctx.OpBitcast(f32_type, crown)),
                        sub(ctx.OpBitcast(f32_type, stored), f(W::HeightBias)));
    const Id tc =
        ctx.OpFClamp(f32_type, mul(sub(mesh, f(W::TreeLo)), f(W::TreeInv)), zero, f(1.0f));
    const Id tau = mul(mul(tc, tc), sub(f(3.0f), mul(f(2.0f), tc)));
    const Id tk = ctx.OpFClamp(
        f32_type,
        mul(sub(ctx.OpFDiv(f32_type, h, ctx.OpFMax(f32_type, mesh, f(W::MeshFloor))),
                f(W::CrownLow)),
            f(W::CrownInv)),
        zero, f(1.0f));
    const Id wt = mul(comp(lean_d, 2u), mul(mul(tk, tk), sub(f(3.0f), mul(f(2.0f), tk))));
    const Id wb = mul(mul(t, t), sub(f(3.0f), mul(f(2.0f), t)));
    // bbport (r89d_tree-twigs): with the twigs a tall mesh (tau above 0) takes the twig weight
    // (BbWindSway::TwigWeight: the vertex's distance from the box's centre line and its height in the
    // mesh) in place of the top half's, and a word with TreeBit has no bush weight (BbWindSway::Displace)
    Id wt_use = wt, wb_use = wb;
    if (twig_on) {
        const auto smooth01 = [&](Id x, float lo, float inv) {
            const Id c = ctx.OpFClamp(f32_type, mul(sub(x, f(lo)), f(inv)), zero, f(1.0f));
            return mul(mul(c, c), sub(f(3.0f), mul(f(2.0f), c)));
        };
        const auto key_lo = [&](Id key) { return sub(ctx.OpBitcast(f32_type, key), f(W::HeightBias)); };
        const auto key_hi = [&](Id key) { return sub(f(W::HeightBias), ctx.OpBitcast(f32_type, key)); };
        const Id x_lo = key_lo(tk_x0);
        const Id x_hi = key_hi(tk_x1);
        const Id z_lo = key_lo(tk_z0);
        const Id z_hi = key_hi(tk_z1);
        const Id ex = sub(add(comp(wind_e, 2u), rx), mul(f(0.5f), add(x_lo, x_hi)));
        const Id ez = sub(add(comp(wind_e, 3u), rz), mul(f(0.5f), add(z_lo, z_hi)));
        const Id half_w = ctx.OpFMax(
            f32_type, mul(f(0.5f), ctx.OpFMax(f32_type, sub(x_hi, x_lo), sub(z_hi, z_lo))),
            f(W::TwigHalfFloor));
        const Id r2 = ctx.OpFDiv(f32_type, add(mul(ex, ex), mul(ez, ez)), mul(half_w, half_w));
        const Id wr = smooth01(r2, W::TwigRad2Lo, W::TwigRad2Inv);
        const Id wh = smooth01(ctx.OpFDiv(f32_type, h, ctx.OpFMax(f32_type, mesh, f(W::MeshFloor))),
                             W::TwigHeightLo, W::TwigHeightInv);
        Id twig = mul(comp(lean_d, 2u), mul(wr, wh));
        if (BbWindTwigs::SizeOn()) { // bbport (r89f_twigs-scale): x clamp(h / SizeRefH, 1, SizeMax)
            twig = mul(twig, ctx.OpFClamp(f32_type, mul(h, f(W::SizeInv)), f(1.0f), f(W::SizeMax)));
        }
        if (BbWindTwigs::FitOn()) { // bbport (r89g_twigs-proof): BbWindSway::FitWeight, the vertex's height over the camera
            const Id fit_h = sub(wy, comp(wind_a, 2u));
            Id fit = mul(comp(lean_d, 2u), mul(f(W::FitShare), smooth01(fit_h, W::FitLo, W::FitInv)));
            if (BbWindTwigs::SizeOn()) {
                fit = mul(fit, ctx.OpFClamp(f32_type, mul(add(fit_h, f(W::FitEye)), f(W::SizeInv)), f(1.0f),
                                            f(W::SizeMax)));
            }
            twig = fit;
        }
        wt_use = ctx.OpSelect(f32_type, ctx.OpFOrdGreaterThan(bool_type, tau, zero), twig, zero);
        wb_use = ctx.OpSelect(f32_type,
                              ctx.OpINotEqual(bool_type,
                                              ctx.OpBitwiseAnd(u32_type, word,
                                                               ctx.ConstU32(BbWindTwigs::TreeBit)),
                                              ctx.u32_zero_value),
                              zero, wb);
    }
    Id w = mul(add(wb_use, mul(mul(tau, lean), sub(wt_use, wb_use))), ramp);
    if (BbWindTwigs::ProofOn()) { // bbport (r89g_twigs-proof, TOOL): a tree word's move x ProofGain
        w = ctx.OpSelect(f32_type,
                         ctx.OpINotEqual(bool_type,
                                         ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(BbWindTwigs::TreeBit)),
                                         ctx.u32_zero_value),
                         mul(w, f(BbWindTwigs::ProofGain)), w);
    }
    // bbport (r89m_twigs-no-tear): the soft cap of a tree word's weight (BbWindSway::TwigSoftCap: w / (1 + |w| / cap), the proof's x5 has
    // twice the cap), here and on the push rule's share below; as the lifter's VertexSway. Off: nothing emitted.
    const bool twig_cap = twig_on && BbWindTwigs::CapOn();
    const auto soft_tree = [&](Id x) {
        const float cap = BbWindTwigs::ProofOn() ? W::TwigCap * W::TwigCapProofMul : W::TwigCap;
        // bbport (r89n_twigs-visible): w / (1 / TwigBoost + |w| / cap), BbWindSway::TwigSoftCap
        const Id capped = ctx.OpFDiv(f32_type, x, add(f(1.0f / W::TwigBoost), mul(ctx.OpFAbs(f32_type, x), f(1.0f / cap))));
        return ctx.OpSelect(f32_type,
                            ctx.OpINotEqual(bool_type,
                                            ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(BbWindTwigs::TreeBit)),
                                            ctx.u32_zero_value),
                            capped, x);
    };
    if (twig_cap) {
        w = soft_tree(w);
    }
    const Id dx = comp(wind_a, 0u);
    const Id dz = comp(wind_a, 1u);
    const Id s = add(mul(rx, dx), mul(rz, dz));
    const Id q = sub(mul(rz, dx), mul(rx, dz));
    const Id u = ctx.OpFClamp(f32_type, sub(comp(wind_d, 1u), mul(s, comp(wind_c, 3u))), zero,
                              comp(wind_d, 2u));
    const Id i = ctx.OpUMin(u32_type, ctx.OpConvertFToU(u32_type, ctx.OpFloor(f32_type, u)),
                            ctx.ConstU32(W::GustSamples - 2u));
    const Id frac = sub(u, ctx.OpConvertUToF(f32_type, i));
    const Id table = scaled(at(view, u64(W::TableAt) * 4u), i, 4u);
    const Id g0 = ctx.OpLoad(f32_type, ctx.OpConvertUToPtr(f32_ptr, table),
                             spv::MemoryAccessMask::Aligned, 4u);
    const Id g1 = ctx.OpLoad(f32_type, ctx.OpConvertUToPtr(f32_ptr, at(table, 4u)),
                             spv::MemoryAccessMask::Aligned, 4u);
    const Id g = add(g0, mul(sub(g1, g0), frac));
    const Id a1 = wrap(add(sub(comp(wind_b, 3u), mul(comp(wind_c, 0u), s)), mul(comp(wind_c, 1u), q)));
    const Id a2 = wrap(sub(sub(comp(wind_c, 2u), mul(comp(wind_d, 3u), s)), mul(comp(wind_c, 1u), q)));
    const Id max_along = comp(wind_e, 0u);
    const Id max_cross = comp(wind_e, 1u);
    const Id along = ctx.OpFClamp(
        f32_type, mul(g, add(comp(wind_b, 0u), mul(comp(wind_b, 1u), ctx.OpSin(f32_type, a1)))),
        ctx.OpFNegate(f32_type, max_along), max_along);
    const Id cross = ctx.OpFClamp(f32_type, mul(g, mul(comp(wind_b, 2u), ctx.OpSin(f32_type, a2))),
                                  ctx.OpFNegate(f32_type, max_cross), max_cross);
    const Id ddx_one =
        ctx.OpSelect(f32_type, fin, mul(w, sub(mul(dx, along), mul(dz, cross))), zero);
    const Id ddz_one =
        ctx.OpSelect(f32_type, fin, mul(w, add(mul(dz, along), mul(dx, cross))), zero);
    // bbport (r89b_wind-sway-ripple): the ripple (bbport_wind_sway.h: BbWindSway::RippleOr and
    // Envelope are this code in C++, operation for operation). Its flag word (RippleD's w) 0, as
    // FillView leaves it with BB_WIND_SWAY_RIPPLE=0, selects the two lines above (r89's motion).
    // With the ripple FillRipple has written r89's swing phases and gust table, so a1, a2 and g
    // above serve both.
    const Id rip_a = row(W::RippleA);
    const Id rip_b = row(W::RippleB);
    const Id rip_c = row(W::RippleC);
    const Id rip_d = row(W::RippleD);
    const Id ry = ctx.OpDot(f32_type, row(W::ToWorldAt + 4), position);
    const Id se = mul(s, comp(rip_b, 3u));
    const Id qe = mul(q, comp(rip_b, 3u));
    // bbport (r89c_wind-lean): each front's sine skewed by RippleD.y x LeanSkew (BbWindSway::Envelope)
    const Id skew = mul(lean, f(W::LeanSkew));
    const auto front = [&](Id phase, float ka, float kb) {
        const Id p = wrap(add(add(phase, mul(f(ka), se)), mul(f(kb), qe)));
        return ctx.OpSin(f32_type, add(p, mul(skew, ctx.OpSin(f32_type, p))));
    };
    const Id n = mul(add(add(front(comp(rip_a, 2u), W::Env1S, W::Env1Q),
                             front(comp(rip_a, 3u), W::Env2S, W::Env2Q)),
                         front(comp(rip_b, 0u), W::Env3S, W::Env3Q)),
                     f(1.0f / 3.0f));
    const Id tt = ctx.OpFClamp(f32_type, mul(sub(n, f(W::EnvLo)), f(W::EnvInv)), zero, f(1.0f));
    const Id env = mul(mul(mul(tt, tt), sub(f(3.0f), mul(f(2.0f), tt))), f(W::EnvScale));
    const auto leaf_wave = [&](Id phase, float kx, float ky, float kz) {
        return ctx.OpSin(
            f32_type, wrap(add(add(add(phase, mul(f(kx), rx)), mul(f(ky), ry)), mul(f(kz), rz))));
    };
    const Id b1 = leaf_wave(comp(rip_b, 1u), W::Leaf1X, W::Leaf1Y, W::Leaf1Z);
    const Id b2 = leaf_wave(comp(rip_b, 2u), W::Leaf2X, W::Leaf2Y, W::Leaf2Z);
    const Id r_along = ctx.OpFClamp(
        f32_type,
        mul(g, add(add(comp(rip_c, 0u), mul(comp(rip_d, 0u), sub(env, f(1.0f)))),
                   mul(mul(comp(rip_c, 1u), env), ctx.OpSin(f32_type, a1)))),
        ctx.OpFNegate(f32_type, max_along), max_along);
    const Id r_cross =
        ctx.OpFClamp(f32_type, mul(g, mul(mul(comp(rip_c, 2u), env), ctx.OpSin(f32_type, a2))),
                     ctx.OpFNegate(f32_type, max_cross), max_cross);
    const Id leaf =
        mul(g, mul(comp(rip_c, 3u), add(f(W::LeafCalm), mul(f(1.0f - W::LeafCalm), env))));
    const Id la = ctx.OpFClamp(f32_type, mul(leaf, b1), f(-W::MaxLeaf), f(W::MaxLeaf));
    const Id lc = ctx.OpFClamp(f32_type, mul(leaf, b2), f(-W::MaxLeaf), f(W::MaxLeaf));
    const Id wf = mul(w, t);
    const Id ddx_rip = ctx.OpSelect(f32_type, fin,
                                    add(mul(w, sub(mul(dx, r_along), mul(dz, r_cross))),
                                        mul(wf, sub(mul(dx, la), mul(dz, lc)))),
                                    zero);
    const Id ddz_rip = ctx.OpSelect(f32_type, fin,
                                    add(mul(w, add(mul(dz, r_along), mul(dx, r_cross))),
                                        mul(wf, add(mul(dz, la), mul(dx, lc)))),
                                    zero);
    // bbport (r89h_twigs-alive): with BB_WIND_TWIGS_PUSH (read once; such sway code has its own shader cache version)
    // the twig's share of the move (tau x lean x twig weight x ramp) takes the push rule's along (BbWindSway::TwigAlong)
    // in place of the ripple's: one extra term, share x (push along - r_along) x the wind's direction. Off: nothing.
    Id ddx_use = ddx_rip, ddz_use = ddz_rip;
    if (BbWindTwigs::PushOn()) {
        const Id front_share = mul(env, f(1.0f / W::EnvScale));
        const Id push_along = ctx.OpFClamp(
            f32_type,
            mul(g, add(mul(comp(rip_d, 0u),
                           add(f(W::TwigRest), mul(f(W::TwigPush), mul(front_share, front_share)))),
                       mul(mul(mul(f(W::TwigFlutter), comp(rip_c, 1u)), env), ctx.OpSin(f32_type, a1)))),
            ctx.OpFNegate(f32_type, max_along), max_along);
        Id twig_share = mul(mul(mul(tau, lean), wt_use), ramp);
        if (BbWindTwigs::ProofOn()) { // the proof knob's x5 of a tree word's move
            twig_share = ctx.OpSelect(
                f32_type,
                ctx.OpINotEqual(bool_type,
                                ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(BbWindTwigs::TreeBit)),
                                ctx.u32_zero_value),
                mul(twig_share, f(BbWindTwigs::ProofGain)), twig_share);
        }
        if (twig_cap) { // bbport (r89m_twigs-no-tear): the same cap on the push rule's share
            twig_share = soft_tree(twig_share);
        }
        const Id extra = mul(twig_share, sub(push_along, r_along));
        ddx_use = ctx.OpSelect(f32_type, fin, add(ddx_rip, mul(extra, dx)), zero);
        ddz_use = ctx.OpSelect(f32_type, fin, add(ddz_rip, mul(extra, dz)), zero);
    }
    const Id rippled = ctx.OpFOrdLessThan(bool_type, zero, comp(rip_d, 3u));
    const Id ddx = ctx.OpSelect(f32_type, rippled, ddx_use, ddx_one);
    const Id ddz = ctx.OpSelect(f32_type, rippled, ddz_use, ddz_one);
    // bbport (r112_wind-more-things): with BB_WIND_HANG=1 (read once; such sway code has its own
    // shader cache version) a word with BbWindHang::HangBit is a hanging thing's: in place of the
    // plant sway above it is pushed downwind only, d = w P (dx, dz), w the smoothstep of
    // (top - y - HangStill) / (HangFull - HangStill) times the ramp, P its view's push table at the
    // vertex (BbWindHang::HangDisplace is this code in C++). Off: nothing of it is emitted.
    const bool hang_on = BbWindHang::KnobOnce().on;
    Id hang{}, top_ptr{}, stored_top{};
    Id ddx_all = ddx, ddz_all = ddz;
    if (hang_on) {
        namespace H = BbWindHang;
        hang = ctx.OpINotEqual(bool_type,
                               ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(H::HangBit)),
                               ctx.u32_zero_value);
        top_ptr = ctx.OpConvertUToPtr(u32_ptr, scaled(at(region, u64(H::TopAt) * 4u),
                                                      field(3u, 10u), 4u));
        stored_top = ctx.OpLoad(u32_type, top_ptr, spv::MemoryAccessMask::Aligned, 4u);
        const Id hh = sub(sub(f(W::HeightBias), wy), ctx.OpBitcast(f32_type, stored_top));
        const Id hfin = ctx.OpFOrdLessThan(
            bool_type,
            add(add(ctx.OpFAbs(f32_type, hh), ctx.OpFAbs(f32_type, rx)), ctx.OpFAbs(f32_type, rz)),
            f(W::FiniteMost));
        // bbport (r112g_hang-judge-settles): a mesh shorter than HangFull scales its still top, its
        // full distance and its push by its height over HangFull (BbWindHang::HangScale; its height
        // from the slot's top and base keys; 1 for a tall one: nothing changes for it)
        const Id ext = sub(sub(f(W::HeightBias), ctx.OpBitcast(f32_type, stored_top)),
                           sub(ctx.OpBitcast(f32_type, stored), f(W::HeightBias)));
        const Id sc = ctx.OpFClamp(f32_type, mul(ext, f(1.0f / H::HangFull)), f(H::HangScaleMin),
                                   f(1.0f));
        Id ht = ctx.OpFClamp(
            f32_type,
            mul(sub(hh, mul(sc, f(H::HangStill))), ctx.OpFDiv(f32_type, f(H::HangInv), sc)), zero,
            f(1.0f));
        if (H::PostOn()) { // bbport (r112s_hang-bracket-move): a post's word (PostBit): the weight is 1 in the top part of the mesh, 0 from 65 percent down (BbWindHang::PostT)
            const Id post = ctx.OpINotEqual(bool_type, ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(H::PostBit)),
                                            ctx.u32_zero_value);
            const Id post_height = ctx.OpFMax(f32_type, ext, f(H::PostExtMin));
            const Id post_below = ctx.OpFDiv(f32_type, hh, post_height);
            const Id ht_post = ctx.OpFClamp(f32_type, mul(sub(f(H::PostBelow), post_below), f(1.0f / H::PostSpan)), zero,
                                            f(1.0f));
            ht = ctx.OpSelect(f32_type, post, ht_post, ht);
        }
        const Id hw = mul(mul(mul(mul(ht, ht), sub(f(3.0f), mul(f(2.0f), ht))), ramp), sc);
        const Id push = scaled(
            at(region, u64(H::PushAt) * 4u),
            ctx.OpIAdd(u32_type, ctx.OpIMul(u32_type, view_index, ctx.ConstU32(W::GustSamples)), i),
            4u);
        const Id p0 = ctx.OpLoad(f32_type, ctx.OpConvertUToPtr(f32_ptr, push),
                                 spv::MemoryAccessMask::Aligned, 4u);
        const Id p1 = ctx.OpLoad(f32_type, ctx.OpConvertUToPtr(f32_ptr, at(push, 4u)),
                                 spv::MemoryAccessMask::Aligned, 4u);
        const Id a =
            mul(hw, ctx.OpFClamp(f32_type, add(p0, mul(sub(p1, p0), frac)), zero, max_along));
        ddx_all = ctx.OpSelect(f32_type, hang, ctx.OpSelect(f32_type, hfin, mul(a, dx), zero), ddx);
        ddz_all = ctx.OpSelect(f32_type, hang, ctx.OpSelect(f32_type, hfin, mul(a, dz), zero), ddz);
    }
    const Id d =
        ctx.OpCompositeConstruct(ctx.F32[4], std::array<Id, 4>{ddx_all, zero, ddz_all, zero});
    std::array<Id, 4> moved{};
    for (u32 r = 0; r < 4; ++r) {
        moved[r] = add(comp(position, r), ctx.OpDot(f32_type, row(W::ForwardAt + r * 4u), d));
    }
    // bbport (r89c_wind-lean): with the lean a plant's tip dips as it bends (a stem keeps its
    // length): d^2 / (2 h), held to MaxAlong (BbWindSway::Displace); 0 without the lean and for a
    // hanging thing (r112's HangBit)
    const Id dip = ctx.OpFMin(
        f32_type,
        ctx.OpFDiv(f32_type, mul(f(0.5f), add(mul(ddx, ddx), mul(ddz, ddz))),
                   ctx.OpFMax(f32_type, h, f(W::DipFloor))),
        max_along);
    Id ddy = ctx.OpSelect(
        f32_type, ctx.OpLogicalAnd(bool_type, fin, ctx.OpFOrdLessThan(bool_type, zero, lean)),
        ctx.OpFNegate(f32_type, dip), zero);
    if (hang_on) {
        ddy = ctx.OpSelect(f32_type, hang, zero, ddy);
    }
    for (u32 r = 0; r < 4; ++r) {
        moved[r] = add(moved[r], mul(comp(row(W::ForwardAt + r * 4u), 1u), ddy));
    }
    // bbport (r117_wind-shelter): with BB_WIND_SHELTER on (read once; such sway code has its own
    // shader cache version) the displacement of every sway vertex (a plant, a hanging thing:
    // whichever motion rule ran above) is multiplied by the wind shelter field's factor 1 - At at
    // the vertex's world point: moved = position + (moved - position) (1 - At). BbWindShelter::At
    // is this code in C++, operation for operation (the field: bbport_wind_shelter.h, its words in
    // the sway region at BlockWord; world x and z: the camera's (WindE.z, .w) plus the vertex's
    // offset from it). The loads are indexed inside the field (clamped) and the value is zeroed
    // outside it, before the marker is written and beyond the vertical band. Off: nothing is
    // emitted (the SPIR-V is as before).
    if (BbWindShelter::KnobOnce().on) {
        namespace S = BbWindShelter;
        const Id block = at(region, u64(S::BlockWord) * 4u);
        const auto shelter_word = [&](u64 word) {
            return ctx.OpLoad(f32_type, ctx.OpConvertUToPtr(f32_ptr, at(block, word * 4u)),
                              spv::MemoryAccessMask::Aligned, 4u);
        };
        const auto both = [&](Id a, Id b) { return ctx.OpLogicalAnd(bool_type, a, b); };
        const Id marker = shelter_word(0u);
        const Id inv_cell = shelter_word(3u);
        const Id fx = sub(mul(sub(add(comp(wind_e, 2u), rx), shelter_word(1u)), inv_cell), f(0.5f));
        const Id fz = sub(mul(sub(add(comp(wind_e, 3u), rz), shelter_word(2u)), inv_cell), f(0.5f));
        const Id x0 = ctx.OpFloor(f32_type, fx);
        const Id z0 = ctx.OpFloor(f32_type, fz);
        const Id last = f(float(S::N) - 1.0f);
        const Id inside = both(both(both(ctx.OpFOrdGreaterThan(bool_type, marker, f(0.5f)),
                                         ctx.OpFOrdGreaterThanEqual(bool_type, x0, zero)),
                                    both(ctx.OpFOrdGreaterThanEqual(bool_type, z0, zero),
                                         ctx.OpFOrdLessThan(bool_type, x0, last))),
                               ctx.OpFOrdLessThan(bool_type, z0, last));
        // (review: the index is x0, z0 only inside the field, else 0: a vertex whose position is
        // not finite makes x0 NaN, which FClamp does not clamp everywhere, and a NaN index through
        // the buffer's address would read out of bounds)
        const Id x0c = ctx.OpSelect(f32_type, inside, x0, zero);
        const Id z0c = ctx.OpSelect(f32_type, inside, z0, zero);
        const Id index =
            ctx.OpIAdd(u32_type,
                       ctx.OpIMul(u32_type, ctx.OpConvertFToU(u32_type, z0c), ctx.ConstU32(S::N)),
                       ctx.OpConvertFToU(u32_type, x0c));
        const Id cell = scaled(at(block, u64(S::HeaderWords) * 4u), index, 4u);
        const auto cell_word = [&](u64 bytes) {
            return ctx.OpLoad(f32_type, ctx.OpConvertUToPtr(f32_ptr, at(cell, bytes)),
                              spv::MemoryAccessMask::Aligned, 4u);
        };
        const Id ca = cell_word(0u);
        const Id cb = cell_word(4u);
        const Id cc = cell_word(u64(S::N) * 4u);
        const Id cd = cell_word(u64(S::N) * 4u + 4u);
        const auto lerp = [&](Id a, Id b, Id t) { return add(a, mul(sub(b, a), t)); };
        const Id tx = sub(fx, x0);
        const Id tz = sub(fz, z0);
        const Id value = lerp(lerp(ca, cb, tx), lerp(cc, cd, tx), tz);
        const Id level = ctx.OpFClamp(
            f32_type,
            mul(sub(shelter_word(7u), ctx.OpFAbs(f32_type, sub(wy, shelter_word(5u)))),
                f(1.0f / S::BandSoft)),
            zero, f(1.0f));
        const Id taken =
            ctx.OpSelect(f32_type, inside, mul(mul(value, level), shelter_word(6u)), zero);
        const Id factor = sub(f(1.0f), taken);
        for (u32 r = 0; r < 4; ++r) {
            const Id from = comp(position, r);
            moved[r] = add(from, mul(sub(moved[r], from), factor));
        }
    }
    ctx.OpStore(ctx.output_position, ctx.OpCompositeConstruct(ctx.F32[4], moved));
    const Id key = ctx.OpBitcast(u32_type, ctx.OpFMax(f32_type, add(wy, f(W::HeightBias)), zero));
    Id offer = ctx.OpLogicalAnd(
        bool_type, ctx.OpFOrdLessThan(bool_type, ctx.OpFAbs(f32_type, wy), f(W::FiniteMost)),
        ctx.OpULessThan(bool_type, key, stored));
    Id post_none{};
    if (hang_on && BbWindHang::PostOn()) { // bbport (r112t_hang-post-measure): a post's word (PostBit) offers no key: the CPU writes its slot's keys from the scene's box
        post_none = ctx.OpIEqual(bool_type, ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(BbWindHang::PostBit)), ctx.u32_zero_value);
        offer = ctx.OpLogicalAnd(bool_type, offer, post_none);
    }
    const Id offer_label = ctx.OpLabel();
    const Id offer_merge = ctx.OpLabel();
    ctx.OpSelectionMerge(offer_merge, spv::SelectionControlMask::MaskNone);
    ctx.OpBranchConditional(offer, offer_label, offer_merge);
    ctx.AddLabel(offer_label);
    ctx.OpAtomicUMin(u32_type, base_ptr, ctx.ConstU32(static_cast<u32>(spv::Scope::Device)),
                     ctx.u32_zero_value, key);
    ctx.OpBranch(offer_merge);
    ctx.AddLabel(offer_merge);
    if (hang_on) { // bbport (r112_wind-more-things): a hanging thing also offers its top: the key
        // of HeightBias - y to its slot at BbWindHang::TopAt (an atomic minimum, only when lower)
        const Id key_top =
            ctx.OpBitcast(u32_type, ctx.OpFMax(f32_type, sub(f(W::HeightBias), wy), zero));
        const Id hang_offers = BbWindHang::PostOn() ? ctx.OpLogicalAnd(bool_type, hang, post_none) : hang; // bbport (r112t_hang-post-measure)
        const Id offer_top = ctx.OpLogicalAnd(
            bool_type, hang_offers,
            ctx.OpLogicalAnd(
                bool_type,
                ctx.OpFOrdLessThan(bool_type, ctx.OpFAbs(f32_type, wy), f(W::FiniteMost)),
                ctx.OpULessThan(bool_type, key_top, stored_top)));
        const Id top_label = ctx.OpLabel();
        const Id top_merge = ctx.OpLabel();
        ctx.OpSelectionMerge(top_merge, spv::SelectionControlMask::MaskNone);
        ctx.OpBranchConditional(offer_top, top_label, top_merge);
        ctx.AddLabel(top_label);
        ctx.OpAtomicUMin(u32_type, top_ptr, ctx.ConstU32(static_cast<u32>(spv::Scope::Device)),
                         ctx.u32_zero_value, key_top);
        ctx.OpBranch(top_merge);
        ctx.AddLabel(top_merge);
    }
    if (hang_on && BbWindHang::ProofOn()) { // bbport (r112r_hang-bracket-judge, TOOL): the proof's tint, as the lifter's: every float output
        // of a vertex with the hang bit (whatever its ramp) moves BbWindHang::ProofShare toward cyan (0, 1, 1)
        const Id tint_share = ctx.OpSelect(f32_type, hang, f(BbWindHang::ProofShare), zero);
        for (u32 p = 0; p < IR::NumParams; ++p) {
            const auto& output = ctx.output_params[p];
            if (!Sirit::ValidId(output.id) || output.is_integer || output.is_array ||
                output.id.value == ctx.clip_distances.value || output.num_components < 1 || output.num_components > 4) {
                continue;
            }
            const u32 n = output.num_components;
            const Id loaded = ctx.OpLoad(ctx.F32[n], output.id);
            std::array<Id, 4> parts{};
            for (u32 c = 0; c < n; ++c) {
                const Id value = n == 1 ? loaded : ctx.OpCompositeExtract(f32_type, loaded, c);
                parts[c] = c == 3u ? value : add(value, mul(sub(f(c == 0u ? 0.0f : 1.0f), value), tint_share));
            }
            Id tinted = parts[0];
            if (n == 2) {
                tinted = ctx.OpCompositeConstruct(ctx.F32[2], parts[0], parts[1]);
            } else if (n == 3) {
                tinted = ctx.OpCompositeConstruct(ctx.F32[3], parts[0], parts[1], parts[2]);
            } else if (n == 4) {
                tinted = ctx.OpCompositeConstruct(ctx.F32[4], parts[0], parts[1], parts[2], parts[3]);
            }
            ctx.OpStore(output.id, tinted);
        }
    }
    // bbport (r89c_wind-lean): the vertex offers its world y to its mesh's crown key (CrownKey:
    // the key of HeightBias - y, an atomic minimum, only when lower)
    const Id crown_key =
        ctx.OpBitcast(u32_type, ctx.OpFMax(f32_type, sub(f(W::HeightBias), wy), zero));
    const Id offer_crown = ctx.OpLogicalAnd(
        bool_type, ctx.OpFOrdLessThan(bool_type, ctx.OpFAbs(f32_type, wy), f(W::FiniteMost)),
        ctx.OpULessThan(bool_type, crown_key, crown));
    const Id crown_label = ctx.OpLabel();
    const Id crown_merge = ctx.OpLabel();
    ctx.OpSelectionMerge(crown_merge, spv::SelectionControlMask::MaskNone);
    ctx.OpBranchConditional(offer_crown, crown_label, crown_merge);
    ctx.AddLabel(crown_label);
    ctx.OpAtomicUMin(u32_type, crown_ptr, ctx.ConstU32(static_cast<u32>(spv::Scope::Device)),
                     ctx.u32_zero_value, crown_key);
    ctx.OpBranch(crown_merge);
    ctx.AddLabel(crown_merge);
    if (twig_on) { // bbport (r89d_tree-twigs): the vertex offers its world x and z to the box keys
        const Id ax = add(comp(wind_e, 2u), rx);
        const Id az = add(comp(wind_e, 3u), rz);
        const auto offer_key = [&](Id value) {
            return ctx.OpBitcast(u32_type, ctx.OpFMax(f32_type, value, zero));
        };
        const Id k_x0 = offer_key(add(ax, f(W::HeightBias)));
        const Id k_x1 = offer_key(sub(f(W::HeightBias), ax));
        const Id k_z0 = offer_key(add(az, f(W::HeightBias)));
        const Id k_z1 = offer_key(sub(f(W::HeightBias), az));
        const auto lower = [&](Id key, Id stored_key) {
            return ctx.OpULessThan(bool_type, key, stored_key);
        };
        const auto either = [&](Id a, Id b) { return ctx.OpLogicalOr(bool_type, a, b); };
        const Id offer_twig = ctx.OpLogicalAnd(
            bool_type, fin,
            either(either(lower(k_x0, tk_x0), lower(k_x1, tk_x1)),
                   either(lower(k_z0, tk_z0), lower(k_z1, tk_z1))));
        const Id twig_label = ctx.OpLabel();
        const Id twig_merge = ctx.OpLabel();
        ctx.OpSelectionMerge(twig_merge, spv::SelectionControlMask::MaskNone);
        ctx.OpBranchConditional(offer_twig, twig_label, twig_merge);
        ctx.AddLabel(twig_label);
        const std::array<Id, 4> offered{k_x0, k_x1, k_z0, k_z1};
        for (u32 k = 0; k < 4; ++k) {
            ctx.OpAtomicUMin(u32_type, twig_word(u64(k) * 4u),
                             ctx.ConstU32(static_cast<u32>(spv::Scope::Device)), ctx.u32_zero_value,
                             offered[k]);
        }
        ctx.OpBranch(twig_merge);
        ctx.AddLabel(twig_merge);
    }
    ctx.OpBranch(sway_merge);
    ctx.AddLabel(sway_merge);
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
    // bbport (r89_wind-foliage-sway): first, so the motion store and the capture take the
    // swayed position (not with the clip space conversion: that position is not clip space yet)
    if (Sirit::ValidId(ctx.motion_out_cur) && ctx.VertexMotion() &&
        (ctx.runtime_info.hw.vs.motion_vectors & MotionVectors::Sway) != 0 &&
        !ctx.runtime_info.hw.vs.clip_disable) {
        EmitVertexSway(ctx);
    }
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
