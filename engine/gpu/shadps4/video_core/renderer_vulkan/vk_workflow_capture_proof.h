// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <span>
#include <cstring>
#include <spirv/unified1/spirv.hpp11>

#include "common/types.h"

namespace WorkflowCapture {
enum class Route : u8 {
    Unknown,
    AtomicPosition,
    AtomicPositionWarm,
    FallbackPosition,
    Uv,
    Sway,
    Dynamic,
    Scope,
};
inline bool Atomic(Route route) {
    return route == Route::AtomicPosition || route == Route::AtomicPositionWarm;
}

inline constexpr u32 WordLimit = 64 * 1024;
inline constexpr u32 ModuleLimit = 512;
inline constexpr u32 ScanWordLimit = 16 * 1024 * 1024;
inline constexpr u32 LifterGenerator = 0x00560001u;

// Called only for trusted lifter output or an exact-byte match to its private cold seal.
// The audited epilogues own all physical addresses when guest writes, UV and sway are absent.
// This walk rejects input and side-effect forms outside that known vertex path.
inline bool DeterministicLifter(std::span<const u32> code, bool also_motion) {
    using Op = spv::Op;
    if (code.size() < 5 || code.size() > WordLimit || code[0] != 0x07230203 ||
        code[2] != LifterGenerator || code[4] != 0) {
        return false;
    }
    u32 main_count = 0, exchanges = 0, scope = 0, semantics = 0;
    bool physical_addressing = false;
    for (size_t offset = 5; offset < code.size();) {
        const u32 words = code[offset] >> 16;
        if (!words || words > code.size() - offset) return false;
        const auto op = Op(code[offset] & 0xffff);
        const auto* operands = code.data() + offset + 1;
        if (op == Op::OpEntryPoint) {
            if (words < 5 || operands[0] != u32(spv::ExecutionModel::Vertex)) return false;
            ++main_count;
        } else if (op == Op::OpMemoryModel) {
            if (words != 3 || operands[0] != u32(spv::AddressingModel::PhysicalStorageBuffer64)) return false;
            physical_addressing = true;
        } else if (op == Op::OpExtInstImport) {
            constexpr char glsl[] = "GLSL.std.450";
            if (words != 2 + (sizeof(glsl) + 3) / 4 || std::memcmp(operands + 1, glsl, sizeof(glsl)) != 0)
                return false;
        } else if (op == Op::OpDecorate || op == Op::OpMemberDecorate) {
            const u32 at = op == Op::OpDecorate ? 1 : 2;
            if (words <= at + 1) return false;
            if (operands[at] == u32(spv::Decoration::BuiltIn)) {
                if (words <= at + 2) return false;
                switch (spv::BuiltIn(operands[at + 1])) {
                case spv::BuiltIn::Position:
                case spv::BuiltIn::PointSize:
                case spv::BuiltIn::ClipDistance:
                case spv::BuiltIn::CullDistance:
                case spv::BuiltIn::VertexIndex:
                case spv::BuiltIn::InstanceIndex:
                case spv::BuiltIn::BaseVertex:
                case spv::BuiltIn::BaseInstance:
                case spv::BuiltIn::DrawIndex:
                    break;
                default:
                    return false;
                }
            }
        } else if (op == Op::OpAtomicExchange) {
            if (words != 7 || (exchanges && (scope != operands[3] || semantics != operands[4]))) return false;
            scope = operands[3];
            semantics = operands[4];
            ++exchanges;
        } else if (op == Op::OpUndef || op == Op::OpImageWrite || op == Op::OpControlBarrier ||
                   op == Op::OpMemoryBarrier || op == Op::OpCopyMemory || op == Op::OpCopyMemorySized ||
                   (op == Op::OpStore && words != 3) ||
                   (op >= Op::OpAtomicLoad && op <= Op::OpAtomicXor) ||
                   op == Op::OpAtomicFlagTestAndSet || op == Op::OpAtomicFlagClear ||
                   (op >= Op::OpGroupAsyncCopy && op <= Op::OpGroupSMax) ||
                   op >= Op::OpGroupNonUniformElect) {
            return false;
        }
        offset += words;
    }
    if (!physical_addressing || main_count != 1 || exchanges != (also_motion ? 8u : 4u)) return false;
    bool device = false, none = false;
    for (size_t offset = 5; offset < code.size(); offset += code[offset] >> 16) {
        if ((code[offset] & 0xffff) == u32(Op::OpConstant) && (code[offset] >> 16) == 4) {
            device |= code[offset + 2] == scope && code[offset + 3] == u32(spv::Scope::Device);
            none |= code[offset + 2] == semantics && code[offset + 3] == 0;
        }
    }
    return device && none;
}
} // namespace WorkflowCapture
