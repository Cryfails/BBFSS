# r50c_leaf-fade: the cut-out analysis of r50b_leaf-matcher learns where the game's per-instance
# fade comes from, so that the nine camera pass foliage, hair and cloth pixel shaders that r50b
# called "1 factors of the nonzero term ignored (computed)" are repeatable with the draw's
# constants, and the log says that their shadow rule leaves the fade out (as the game's sun
# shadow pass, which has no fade). Nothing else: no picture change, no GPU resource, no change to
# any ray. Off by default, as r50: BB_RT_CARD_ALPHA_LOG=1 (read once) turns it on.
# check|apply|revert (revert restores byte for byte). On top of r50b as <tree> has it on
# 2026-11-15 (with r57). The tree: the one the environment variable R50C_ROOT names; without it
# the current directory when that is the root of a source tree, else <tree>/. Nothing is
# changed in place: every new text is written beside its target and moved over it, and a failure
# puts back what was already moved. Files keep their line ends (CRLF or LF, as each file has them).
# Every edit is an anchored text found exactly once (apply: the old text; revert: the new one).
#
# WHY. The game's fade is a float of a storage buffer that the shader declares as float typed
# (r50_spv: a float-only view, indexed by the instance id the vertex shader passes in the
# per-vertex input at location 0, .w truncated). The translator emits a typed buffer load
# (LoadBufferFormatF32), and LowerBufferFormatToRaw (before the analysis, recompiler.cpp) makes it
# LoadBufferF32x4, takes its lanes apart and builds them again: CompositeConstructF32x4 of the
# lanes, then ApplySwizzle's CompositeShuffleF32x4(CompositeConstruct(0, 1, 0, 0), vector, swizzle).
# ConstantPropagation folds neither (only CompositeExtract of a construct and U32 constructs), so
# the fade reaches the test as CompositeExtract(CompositeShuffle(...), 3). r50b looked for a buffer
# load only at the factor itself: through the shuffle it saw "computed", which RepeatableWithConstants
# refuses. r50b's test built the fade as LoadBufferU32, which is why it passed. Reproduced in
# scratch with the real LowerBufferFormatToRaw and ConstantPropagation: kinds 8 (computed), not
# repeatable, as in the game log.
#
# WHAT (shader_recompiler/ir/passes/cutout_analysis_pass.cpp):
#  FactorKind follows one lane of the factor back through bit casts, CompositeExtract,
#     CompositeConstruct and CompositeShuffle (ThroughComposites, at most 16 steps). A buffer load
#     found that way is "a buffer load" where its address holds one value across a triangle
#     (PerVertexAddress); else "computed" (a fade that differs per pixel cannot be left out). The
#     address may read immediates, user data, constant and buffer dwords, per-vertex and flat
#     inputs (Info::fs_interpolation), and an interpolation by hand of a per-vertex input only
#     where it goes straight into a float to integer conversion (the game's uint(instance id)).
#     Refused: a smooth, no-perspective, centroid or sample input; barycentrics anywhere else;
#     FragCoord; a sample; a division or reciprocal; a phi; lane, quad and wave values; shared
#     memory and atomics; the time; undefined values. ASSUMED: the vertex shader writes the same
#     per-vertex value to a triangle's three vertices (the pixel shader cannot show it).
#     An immediate 0 or one not finite is "computed": a 0 discards every pixel, so the term
#     cannot be left out. A finite nonzero immediate (through a swizzle) is no factor. Dwords from
#     memory are "dwords/computed": a per-draw value the record does not keep, 0 on a draw would
#     hide it, so the record is not repeatable. A whole vector that is not a load: computed.
#  The shader line says "left out (...; repeatable, fade left out)" for a repeatable record,
#     "ignored (...; not repeatable)" where the factors are an input or computed, and "ignored
#     (...)" for a record refused for another reason. The constants line says "fade left out (N
#     factors of the nonzero term: ...)". The totals line adds "(r50c: of the W repeatable with
#     the draw's constants, A leave nothing out, B leave the fade out: ...)"; the cards' line per
#     class "(r50c: N with the fade left out)", and once "(r50c) each shader once: N with
#     constants read from memory, D draws: ..." (each shader counted once, for the share of
#     CPU-written draws; the classes count a shader in each class it was seen in).
#  tests/test_rt_card_alpha.cpp: the fade as the translator leaves it (LoadBufferFormat, typed,
#     Format32_32_32_32 Float, index enabled) run through the real LowerBufferFormatToRaw and
#     ConstantPropagation before the analysis, in the four game variants; the negatives: the
#     factor the texture alpha itself, a factor sampled from another texture, an address read at
#     FragCoord, pos.x / pos.w, a texel, a smooth uv.x * 64 or pos.x * 100, a no-perspective
#     input, barycentrics alone, the instance id interpolated by hand and scaled, a flat input
#     over its w, a phi, a quad broadcast, the instance id input smooth; a factor that is
#     FragCoord, an immediate 0 or +inf, a dword from memory; kept: a flat input, one vertex's
#     instance id; the constant 1 lane of a swizzle (no factor), an immediate 2 (the alpha's own
#     scale, as r50b), the line of a record refused for its coordinates, the counts.
# KNOB OFF: nothing new runs (the pass runs only under CutoutAnalysisOn(), recompiler.cpp, r50).
# KNOB ON: a factor's walk is at most 16 composite steps and one bounded walk of a load's address
#     (MaxVisits); at compile time only.
# LOG (no new line; the r50 and r50b lines keep their tags):
#   Cut-out pixel shader <hash> (r50): match (...), 1 factors of the nonzero term left out (a buffer load; repeatable, fade left out)
#   Cut-out constants <hash> (r50b): ..., fade left out (1 factors of the nonzero term: a buffer load), stored channel a, ...
#   totals: ... (r50b: ...) (r50c: of the W repeatable with the draw's constants, A leave nothing
#     out, B leave the fade out: ...)
#   cards, per class: [mix; R repeatable, W with constants (r50c: F with the fade left out); ...]
#     and before the shaders not matched: (r50c) each shader once: N with constants read from
#     memory, D draws: a CPU-written, b in place, c GPU-written, d unreadable, e another permutation
# NOT CHANGED: info.h (the record keeps its seven dwords, CutoutDwords, and ignored_kinds),
# cutout_analysis.h, vk_rasterizer_effects.cpp (the draw-time line reads what it read: the fade is
# never read), recompiler.cpp, CMakeLists.txt; anything a ray, a pass or a picture uses; the
# lines r54_leaf-stage2 anchors on in cutout_analysis_pass.cpp; the files of other rounds, the
# drawn look's and the volumetric/fog files.
# NOT DONE: the fade's value is not recorded (a per-instance float indexed by a varying is not a
# per-draw dword). A fully faded instance (fade 0: 765450df writes A * fade as its alpha, so the
# instance is hidden) would cast a leaf shadow in a rule that leaves the fade out; how often the
# fade is 0 is not counted. The camera reference cb20 + 0.5 * cb21 is printed for the first draw
# of each shader only (one material per shader), not its range over all draws.
# TEST: BB_RT_CARD_ALPHA_LOG=1, walk among plants with ray traced shadows on; the nine camera
# shaders' lines end "left out (a buffer load; repeatable, fade left out)"; the cards' line has
# plants, no skeleton and kept whole all "with constants" (r50c: all with the fade left out).

import os
import sys

ROOT = os.environ.get("R50C_ROOT")
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
TESTS = E + "tests/"

TMP = ".r50ctmp"  # a new text waits under this name beside its target (main)

# Another round's files, the drawn look's and the volumetric/fog files: this one must not touch them.
FOREIGN = ("point_shadow_ray.comp", "lamp_shadow_tune.h", "vk_point_shadow.h", "vk_point_shadow.cpp",
           "test_lamp_shadow_tune.cpp", "test_rt_shadows.cpp", "renderer-performance-0.9.43.md",
           "info.h", "cutout_analysis.h", "vk_rasterizer_effects.cpp", "rt_card_uv.h")


def foreign(path):
    name = path.rsplit("/", 1)[-1]
    return name in FOREIGN or name.startswith(("vk_drawn_look.", "paint_", "drawn_")) or \
        "volumetric" in name or "fog" in name


# (old text, new text) pairs, LF line ends; each found exactly once where it is applied.
EDITS = {
    P + "cutout_analysis_pass.cpp": [
        ('// SPDX-License-Identifier: GPL-3.0-or-later\n'
         '// bbport (r50_leaf-stage1, r50b_leaf-matcher): the cut-out analysis (cutout_analysis.h). It runs\n'
         '// after CollectShaderInfoPass, on the program as it goes to SPIR-V, and reads:\n'
         '//  - the discards: DiscardCond(LogicalNot(exec)) of an export with vm (export.cpp), where exec is\n',
         '// SPDX-License-Identifier: GPL-3.0-or-later\n'
         '// bbport (r50_leaf-stage1, r50b_leaf-matcher, r50c_leaf-fade): the cut-out analysis\n'
         '// (cutout_analysis.h). It runs after CollectShaderInfoPass, on the program as it goes to SPIR-V,\n'
         '// and reads:\n'
         '//  - the discards: DiscardCond(LogicalNot(exec)) of an export with vm (export.cpp), where exec is\n'),
        ('//    one factor the alpha itself, the others reading no texture (ignored and recorded by kind:\n'
         "//    a buffer load such as the game's per-instance fade, dwords, an input, computed);\n"
         "//  - the sample's coordinates the same way, the variable an input: GetAttribute(ParamN, c) of a\n",
         '//    one factor the alpha itself, the others reading no texture (ignored and recorded by kind:\n'
         "//    a buffer load such as the game's per-instance fade, dwords, an input, computed); (r50c) a\n"
         '//    buffer load also through the lanes LowerBufferFormatToRaw rebuilds a typed load with (the\n'
         "//    game's fade is one), and only where its address holds one value across a triangle\n"
         '//    (PerVertexAddress); dwords from memory are taken as computed, and a finite nonzero\n'
         '//    immediate is no factor (FactorKind);\n'
         "//  - the sample's coordinates the same way, the variable an input: GetAttribute(ParamN, c) of a\n"),
        ('}\n'
         '\n'
         '/// (r50b E4) What an ignored factor of a nonzero term is (Cutout::Ignored*): a buffer load\n'
         '/// (through bit casts and a composite extract of a vector load), an immediate or dwords, an input\n'
         '/// component, or anything else.\n'
         'u8 FactorKind(const IR::Value& value, const Info* info) {\n'
         '    const IR::Inst* inst = value.TryInst();\n'
         '    while (inst && (Is(inst, IR::Opcode::BitCastF32U32) || Is(inst, IR::Opcode::BitCastU32F32) ||\n'
         '                    Is(inst, IR::Opcode::CompositeExtractU32x2) ||\n'
         '                    Is(inst, IR::Opcode::CompositeExtractU32x3) ||\n'
         '                    Is(inst, IR::Opcode::CompositeExtractU32x4) ||\n'
         '                    Is(inst, IR::Opcode::CompositeExtractF32x2) ||\n'
         '                    Is(inst, IR::Opcode::CompositeExtractF32x3) ||\n'
         '                    Is(inst, IR::Opcode::CompositeExtractF32x4))) {\n'
         '        inst = inst->Arg(0).TryInst();\n'
         '    }\n'
         '    if (inst) {\n'
         '        switch (inst->GetOpcode()) {\n'
         '        case IR::Opcode::LoadBufferU32:\n'
         '        case IR::Opcode::LoadBufferU32x2:\n'
         '        case IR::Opcode::LoadBufferU32x3:\n'
         '        case IR::Opcode::LoadBufferU32x4:\n'
         '        case IR::Opcode::LoadBufferF32:\n'
         '        case IR::Opcode::LoadBufferF32x2:\n'
         '        case IR::Opcode::LoadBufferF32x3:\n'
         '        case IR::Opcode::LoadBufferF32x4:\n'
         '        case IR::Opcode::LoadBufferFormatF32:\n'
         '            return Cutout::IgnoredBuffer;\n'
         '        default:\n'
         '            break;\n'
         '        }\n'
         '    }\n'
         '    Walker walker{Mode::Test, info};\n'
         '    const auto x = walker.Eval(value, 0);\n'
         '    if (x && x->var == Var::None && !x->dither_sample) {\n'
         '        return Cutout::IgnoredDword;\n'
         '    }\n'
         '    if (x && x->var == Var::Input) {\n',
         '}\n'
         '\n'
         '/// (r50c) The lanes of a vector type (0: not a vector of 32-bit lanes).\n'
         'u32 Lanes(IR::Type type) {\n'
         '    switch (type) {\n'
         '    case IR::Type::U32x2:\n'
         '    case IR::Type::F32x2:\n'
         '        return 2;\n'
         '    case IR::Type::U32x3:\n'
         '    case IR::Type::F32x3:\n'
         '        return 3;\n'
         '    case IR::Type::U32x4:\n'
         '    case IR::Type::F32x4:\n'
         '        return 4;\n'
         '    default:\n'
         '        return 0;\n'
         '    }\n'
         '}\n'
         '\n'
         '/// (r50c) What one lane of a value comes from: followed back through bit casts, a composite\n'
         '/// extract (the lane), a composite construct (its argument for the lane) and a composite shuffle\n'
         "/// (the vector and lane its index picks; both vectors have Lanes() lanes, the second's indexed\n"
         "/// after the first's). LowerBufferFormatToRaw turns a typed load (buffer_load_format_*,\n"
         '/// tbuffer_load_*) into LoadBufferF32xN, its lanes extracted, built again and shuffled by the\n'
         '/// swizzle (reinterpret.h ApplySwizzle), and ConstantPropagation folds no float construct or\n'
         "/// shuffle: the game's per-instance fade reaches the analysis as Extract(Shuffle(constants,\n"
         '/// Construct(Extract(LoadBufferF32x4, 0..3))), 3), which r50b took for computed. `vector`: the\n'
         '/// value reached is a vector and `lane` the lane of it meant. At most 16 steps.\n'
         'struct LaneSource {\n'
         '    IR::Value value;\n'
         '    bool vector = false;\n'
         '    u32 lane = 0;\n'
         '};\n'
         '\n'
         'LaneSource ThroughComposites(IR::Value value) {\n'
         '    LaneSource at{.value = value};\n'
         '    for (u32 step = 0; step < 16; ++step) {\n'
         '        const IR::Inst* inst = at.value.IsImmediate() ? nullptr : at.value.TryInst();\n'
         '        if (!inst) {\n'
         '            break;\n'
         '        }\n'
         '        switch (inst->GetOpcode()) {\n'
         '        case IR::Opcode::BitCastF32U32:\n'
         '        case IR::Opcode::BitCastU32F32:\n'
         '            if (at.vector) {\n'
         '                return at;\n'
         '            }\n'
         '            at.value = inst->Arg(0);\n'
         '            continue;\n'
         '        case IR::Opcode::CompositeExtractU32x2:\n'
         '        case IR::Opcode::CompositeExtractU32x3:\n'
         '        case IR::Opcode::CompositeExtractU32x4:\n'
         '        case IR::Opcode::CompositeExtractF32x2:\n'
         '        case IR::Opcode::CompositeExtractF32x3:\n'
         '        case IR::Opcode::CompositeExtractF32x4:\n'
         '            if (at.vector || !inst->Arg(1).IsImmediate()) {\n'
         '                return at;\n'
         '            }\n'
         '            at = {.value = inst->Arg(0), .vector = true, .lane = inst->Arg(1).U32()};\n'
         '            continue;\n'
         '        case IR::Opcode::CompositeConstructU32x2:\n'
         '        case IR::Opcode::CompositeConstructU32x3:\n'
         '        case IR::Opcode::CompositeConstructU32x4:\n'
         '        case IR::Opcode::CompositeConstructF32x2:\n'
         '        case IR::Opcode::CompositeConstructF32x3:\n'
         '        case IR::Opcode::CompositeConstructF32x4:\n'
         '            if (!at.vector || at.lane >= inst->NumArgs()) {\n'
         '                return at;\n'
         '            }\n'
         '            at = {.value = inst->Arg(at.lane)};\n'
         '            continue;\n'
         '        case IR::Opcode::CompositeShuffleU32x2:\n'
         '        case IR::Opcode::CompositeShuffleU32x3:\n'
         '        case IR::Opcode::CompositeShuffleU32x4:\n'
         '        case IR::Opcode::CompositeShuffleF32x2:\n'
         '        case IR::Opcode::CompositeShuffleF32x3:\n'
         '        case IR::Opcode::CompositeShuffleF32x4: {\n'
         '            const u32 lanes = Lanes(inst->Arg(0).Type());\n'
         '            if (!at.vector || 2 + at.lane >= inst->NumArgs() ||\n'
         '                !inst->Arg(2 + at.lane).IsImmediate() || lanes == 0) {\n'
         '                return at;\n'
         '            }\n'
         '            const u32 pick = inst->Arg(2 + at.lane).U32();\n'
         '            if (pick >= 2 * lanes) {\n'
         '                return at;\n'
         '            }\n'
         '            at = {.value = inst->Arg(pick < lanes ? 0 : 1),\n'
         '                  .vector = true,\n'
         '                  .lane = pick < lanes ? pick : pick - lanes};\n'
         '            continue;\n'
         '        }\n'
         '        default:\n'
         '            return at;\n'
         '        }\n'
         '    }\n'
         '    return at;\n'
         '}\n'
         '\n'
         'bool IsBufferLoad(IR::Opcode opcode) {\n'
         '    switch (opcode) {\n'
         '    case IR::Opcode::LoadBufferU32:\n'
         '    case IR::Opcode::LoadBufferU32x2:\n'
         '    case IR::Opcode::LoadBufferU32x3:\n'
         '    case IR::Opcode::LoadBufferU32x4:\n'
         '    case IR::Opcode::LoadBufferF32:\n'
         '    case IR::Opcode::LoadBufferF32x2:\n'
         '    case IR::Opcode::LoadBufferF32x3:\n'
         '    case IR::Opcode::LoadBufferF32x4:\n'
         '    case IR::Opcode::LoadBufferFormatF32:\n'
         '        return true;\n'
         '    default:\n'
         '        return false;\n'
         '    }\n'
         '}\n'
         '\n'
         '/// (r50c) The shared, buffer and image atomics (opcodes.inc lists each kind in one run).\n'
         'bool IsAtomic(IR::Opcode op) {\n'
         '    using O = IR::Opcode;\n'
         '    return (op >= O::SharedAtomicIAdd32 && op <= O::SharedAtomicCmpSwap64) ||\n'
         '           (op >= O::BufferAtomicIAdd32 && op <= O::BufferAtomicFCmpSwap32) ||\n'
         '           (op >= O::ImageAtomicIAdd32 && op <= O::ImageAtomicCmpSwap32);\n'
         '}\n'
         '\n'
         '/// (r50c) Whether input `param` holds one value across a triangle: a per-vertex input (read as one\n'
         "/// vertex's own value, GetAttribute(ParamN, c, vertex)) or a flat one. A smooth, no-perspective,\n"
         '/// centroid or sample input varies per pixel, and so does one whose interpolation the Info does\n'
         '/// not record (None, or no Info): refused.\n'
         'bool TriangleConstantInput(u32 param, const Info* info) {\n'
         '    if (!info || param >= info->fs_interpolation.size()) {\n'
         '        return false;\n'
         '    }\n'
         '    const Qualifier q = info->fs_interpolation[param].primary;\n'
         '    return q == Qualifier::PerVertex || q == Qualifier::Flat;\n'
         '}\n'
         '\n'
         "/// (r50c) Whether `value` is GCN's interpolation by hand (Walker::Interpolated, perspective\n"
         '/// barycentrics) of a per-vertex input. ASSUMED, not provable from the pixel shader: the vertex\n'
         "/// shader writes the same value to a triangle's three vertices (the game's instance id), so the\n"
         '/// interpolation gives that value at every pixel (P0 + I * 0 + J * 0). A per-vertex value that\n'
         '/// differs at the vertices (a normal, a position) would be a per-pixel value here.\n'
         'bool HandInterpolatedPerVertex(const IR::Value& value, const Info* info) {\n'
         '    const IR::Inst* fma = value.IsImmediate() ? nullptr : value.TryInst();\n'
         '    if (!info || !Is(fma, IR::Opcode::FPFma32)) {\n'
         '        return false;\n'
         '    }\n'
         '    const auto input = Walker{Mode::Test, info}.Interpolated(*fma);\n'
         '    return input && input->index < info->fs_interpolation.size() &&\n'
         '           info->fs_interpolation[input->index].primary == Qualifier::PerVertex;\n'
         '}\n'
         '\n'
         "/// (r50c) Whether a buffer load's address holds one value across a triangle, so that a factor\n"
         '/// read there is the same at every pixel the triangle covers. Why it matters: a factor left out\n'
         '/// of the shadow rule must be one the rule can lose without a screen or uv pattern (a dissolve)\n'
         '/// going with it. Allowed: any arithmetic over immediates, user data, constant and other buffer\n'
         '/// dwords, inputs that are per vertex or flat (TriangleConstantInput), and an interpolation by\n'
         '/// hand of a per-vertex input only where it goes straight into a float to integer conversion (an\n'
         "/// index, as the game's: uint(interpolated instance id) * 13 + 7, row 7 of the instance's 13\n"
         '/// vec4s; HandInterpolatedPerVertex, whose barycentrics are not walked). The conversion rule\n'
         '/// narrows the assumption that the per-vertex value is one value per triangle: a position or uv\n'
         '/// scaled before the conversion is refused. Refused: a texture read; FragCoord, a barycentric\n'
         '/// read anywhere else, or any other non-input attribute; a smooth, no-perspective, centroid or\n'
         '/// sample input; a divide or reciprocal (an input over its w is a screen position; kept as a\n'
         "/// guard although no per-pixel input is left to divide); a lane or wave value (a neighbour's, the\n"
         "/// wave's coverage, a quad broadcast); shared memory and atomics (what other pixels wrote); the\n"
         '/// time; an undefined value; a phi (the way in); and a walk cut short (MaxVisits).\n'
         'bool PerVertexAddress(const IR::Inst& load, const Info* info) {\n'
         '    std::vector<const IR::Inst*> stack;\n'
         '    std::unordered_set<const IR::Inst*> seen;\n'
         '    for (size_t arg = 0; arg < load.NumArgs(); ++arg) {\n'
         '        if (const IR::Inst* in = load.Arg(arg).TryInst()) {\n'
         '            stack.push_back(in);\n'
         '        }\n'
         '    }\n'
         '    while (!stack.empty()) {\n'
         '        const IR::Inst* inst = stack.back();\n'
         '        stack.pop_back();\n'
         '        if (!seen.insert(inst).second) {\n'
         '            continue;\n'
         '        }\n'
         '        if (seen.size() > MaxVisits || IsSample(inst->GetOpcode())) {\n'
         '            return false;\n'
         '        }\n'
         '        switch (inst->GetOpcode()) {\n'
         '        case IR::Opcode::Phi:\n'
         '        case IR::Opcode::FPRecip32:\n'
         '        case IR::Opcode::FPRecip64:\n'
         '        case IR::Opcode::FPDiv32:\n'
         '        case IR::Opcode::FPDiv64:\n'
         '        case IR::Opcode::ImageQueryLod:\n'
         '        case IR::Opcode::LaneId:\n'
         '        case IR::Opcode::WarpId:\n'
         '        case IR::Opcode::QuadBroadcast:\n'
         '        case IR::Opcode::Shuffle:\n'
         '        case IR::Opcode::ShuffleXor:\n'
         '        case IR::Opcode::ReadFirstLane:\n'
         '        case IR::Opcode::ReadLane:\n'
         '        case IR::Opcode::WriteLane:\n'
         '        case IR::Opcode::Ballot:\n'
         '        case IR::Opcode::BallotFindLsb:\n'
         '        case IR::Opcode::InverseBallot:\n'
         '        case IR::Opcode::GroupAny:\n'
         '        case IR::Opcode::GetExec:\n'
         '        case IR::Opcode::GetVectorRegister:\n'
         '        case IR::Opcode::LoadSharedU16:\n'
         '        case IR::Opcode::LoadSharedU32:\n'
         '        case IR::Opcode::LoadSharedU64:\n'
         '        case IR::Opcode::DataAppend:\n'
         '        case IR::Opcode::DataConsume:\n'
         '        case IR::Opcode::Memtime:\n'
         '        case IR::Opcode::UndefU1:\n'
         '        case IR::Opcode::UndefU8:\n'
         '        case IR::Opcode::UndefU16:\n'
         '        case IR::Opcode::UndefU32:\n'
         '        case IR::Opcode::UndefU32x2:\n'
         '        case IR::Opcode::UndefU32x3:\n'
         '        case IR::Opcode::UndefU32x4:\n'
         '        case IR::Opcode::UndefF32:\n'
         '        case IR::Opcode::UndefU64:\n'
         '            return false;\n'
         '        case IR::Opcode::ConvertU32F32:\n'
         '        case IR::Opcode::ConvertS32F32:\n'
         '            if (HandInterpolatedPerVertex(inst->Arg(0), info)) {\n'
         '                continue; // an index: one value per triangle (assumed, see above)\n'
         '            }\n'
         '            break;\n'
         '        case IR::Opcode::GetAttribute:\n'
         '        case IR::Opcode::GetAttributeU32: {\n'
         '            const IR::Attribute attr = inst->Arg(0).Attribute();\n'
         '            if (!IR::IsParam(attr) ||\n'
         '                !TriangleConstantInput(u32(attr) - u32(IR::Attribute::Param0), info)) {\n'
         '                return false;\n'
         '            }\n'
         '            break;\n'
         '        }\n'
         '        default:\n'
         '            // the atomics of every kind return what memory held, which other pixels change\n'
         '            if (IsAtomic(inst->GetOpcode())) {\n'
         '                return false;\n'
         '            }\n'
         '            break;\n'
         '        }\n'
         '        for (size_t arg = 0; arg < inst->NumArgs(); ++arg) {\n'
         '            if (const IR::Inst* in = inst->Arg(arg).TryInst()) {\n'
         '                stack.push_back(in);\n'
         '            }\n'
         '        }\n'
         '    }\n'
         '    return true;\n'
         '}\n'
         '\n'
         '/// (r50b E4) What an ignored factor of a nonzero term is (Cutout::Ignored*), 0 for none:\n'
         '///  - a buffer load (through bit casts and composites, ThroughComposites); r50c: only at an\n'
         '///    address that holds one value across a triangle (PerVertexAddress), else computed. The\n'
         "///    game's per-instance fade is one. It is left out of the shadow rule; where it is 0 the game\n"
         '///    hides the instance (765450df writes A * fade as its alpha) and the rule still casts its\n'
         '///    shadow. r50c does not count how often that is: the fade is a per-instance float of a\n'
         '///    storage buffer, not read here;\n'
         "///  - (r50c) a finite nonzero immediate, reached through composites (a swizzle's constant 1): no\n"
         "///    factor, 0 (it changes no pixel's test; r50b's Walker folds a direct one into the alpha);\n"
         '///  - an immediate 0 or one not finite (r50c): computed. 0 discards every pixel, so the term\n'
         '///    cannot be left out;\n'
         '///  - (r50c) dwords from memory: dwords and computed. A dword is a value of the draw, and the\n'
         '///    record does not keep where it is: a draw where it is 0 hides every pixel, and the rule\n'
         '///    cannot leave that out unread. So the record is not repeatable (RepeatableWithConstants);\n'
         '///  - an input component; anything else computed.\n'
         'u8 FactorKind(const IR::Value& value, const Info* info) {\n'
         '    const LaneSource source = ThroughComposites(value);\n'
         '    const IR::Inst* inst = source.value.IsImmediate() ? nullptr : source.value.TryInst();\n'
         '    if (inst && IsBufferLoad(inst->GetOpcode())) {\n'
         '        return PerVertexAddress(*inst, info) ? Cutout::IgnoredBuffer : Cutout::IgnoredComputed;\n'
         '    }\n'
         '    if (source.vector) {\n'
         '        return Cutout::IgnoredComputed; // a lane of a vector that is no load\n'
         '    }\n'
         '    Walker walker{Mode::Test, info};\n'
         '    const auto x = walker.Eval(source.value, 0);\n'
         '    if (x && x->var == Var::None && !x->dither_sample) {\n'
         '        if (x->offset.Memory()) {\n'
         '            return Cutout::IgnoredDword | Cutout::IgnoredComputed;\n'
         '        }\n'
         '        if (x->offset.a == 0.0f || !std::isfinite(x->offset.a)) {\n'
         '            return Cutout::IgnoredComputed;\n'
         '        }\n'
         '        return 0;\n'
         '    }\n'
         '    if (x && x->var == Var::Input) {\n'),
        ('        if (auto n = NonzeroFactors(inst->Arg(i), alpha, info, dithers, depth + 1)) {\n'
         '            ++n->count;\n'
         '            n->kinds |= FactorKind(inst->Arg(1 - i), info);\n'
         '            return n;\n',
         '        if (auto n = NonzeroFactors(inst->Arg(i), alpha, info, dithers, depth + 1)) {\n'
         '            // (r50c) a factor of kind 0 (a finite nonzero immediate) is no factor: not counted\n'
         '            const u8 kind = FactorKind(inst->Arg(1 - i), info);\n'
         '            n->count += kind != 0 ? 1 : 0;\n'
         '            n->kinds |= kind;\n'
         '            return n;\n'),
        ('    u32 ignored_varying = 0; ///< an ignored nonzero factor that is an input or computed\n'
         '};\n',
         '    u32 ignored_varying = 0; ///< an ignored nonzero factor that is an input or computed\n'
         '    // r50c\n'
         "    u32 fade_left_out = 0; ///< repeatable with the draw's constants, nonzero factors left out\n"
         '};\n'),
        ('    if (c.ignored_factor_terms != 0) {\n'
         '        put(", %u factors of the nonzero term ignored (%s)", c.ignored_factor_terms,\n'
         '            KindsText(c.ignored_kinds).c_str());\n'
         '    }\n',
         '    if (c.ignored_factor_terms != 0) {\n'
         '        // (r50c) a repeatable record says that its rule leaves them out (the shadow rule is the\n'
         '        // game\'s sun shadow pass form, which has no such factor); "not repeatable" only where\n'
         '        // the factors are the reason (an input or computed), not for a record refused otherwise\n'
         '        const bool left_out = c.RepeatableWithConstants();\n'
         '        const bool varying =\n'
         '            (c.ignored_kinds & (Cutout::IgnoredInput | Cutout::IgnoredComputed)) != 0;\n'
         '        put(", %u factors of the nonzero term %s (%s%s)", c.ignored_factor_terms,\n'
         '            left_out ? "left out" : "ignored", KindsText(c.ignored_kinds).c_str(),\n'
         '            left_out  ? "; repeatable, fade left out"\n'
         '            : varying ? "; not repeatable"\n'
         '                      : "");\n'
         '    }\n'),
        ('            (c.ignored_kinds & (Cutout::IgnoredInput | Cutout::IgnoredComputed)) != 0 ? 1 : 0;\n'
         '    }\n',
         '            (c.ignored_kinds & (Cutout::IgnoredInput | Cutout::IgnoredComputed)) != 0 ? 1 : 0;\n'
         '        counts.fade_left_out += c.RepeatableWithConstants() && c.ignored_factor_terms != 0 ? 1 : 0;\n'
         '    }\n'),
        ('    }\n'
         '    Append(text, ", stored channel %c, %s", Swizzle(stored), ConstantsNames[size_t(state)]);\n',
         '    }\n'
         '    if (c.ignored_factor_terms != 0) {\n'
         "        // (r50c) not read and not in the shadow rule (the game's sun shadow pass has none)\n"
         '        Append(text, ", fade left out (%u factors of the nonzero term: %s)", c.ignored_factor_terms,\n'
         '               KindsText(c.ignored_kinds).c_str());\n'
         '    }\n'
         '    Append(text, ", stored channel %c, %s", Swizzle(stored), ConstantsNames[size_t(state)]);\n'),
        ('           counts.ignored_varying);\n'
         '    Append(text,\n',
         '           counts.ignored_varying);\n'
         "    // (r50c) the shadow rule of a repeatable record is the game's sun shadow pass form: a\n"
         '    // nonzero factor that is a buffer load (the per-instance fade) is not in it\n'
         '    Append(text,\n'
         '           " (r50c: of the %u repeatable with the draw\'s constants, %u leave nothing out, %u leave "\n'
         '           "the fade out: factors of the nonzero term that are a buffer load, which the game\'s "\n'
         '           "sun shadow pass does not have)",\n'
         '           counts.with_constants, counts.with_constants - counts.fade_left_out,\n'
         '           counts.fade_left_out);\n'
         '    Append(text,\n'),
        ('            u32 total = 0, repeatable = 0, with_constants = 0, matched = 0, cpu = 0, no_memory = 0;\n'
         '            std::array<u32, ConstantsNames.size()> draws{};\n',
         '            u32 total = 0, repeatable = 0, with_constants = 0, matched = 0, cpu = 0, no_memory = 0;\n'
         '            u32 fade_left_out = 0; // (r50c) of with_constants\n'
         '            std::array<u32, ConstantsNames.size()> draws{};\n'),
        ('                ++with_constants;\n'
         '                const auto dwords = CutoutDwords(c);\n',
         '                ++with_constants;\n'
         '                fade_left_out += c.ignored_factor_terms != 0 ? 1 : 0;\n'
         '                const auto dwords = CutoutDwords(c);\n'),
        ('            Append(text,\n'
         '                   "; %u repeatable, %u with constants; %u match, %u with CPU-written constants "\n'
         '                   "on every draw, %u with no memory constants",\n'
         '                   repeatable, with_constants, matched, cpu, no_memory);\n'
         '            const u32 all = std::accumulate(draws.begin(), draws.end(), 0u);\n',
         '            Append(text,\n'
         '                   "; %u repeatable, %u with constants (r50c: %u with the fade left out); %u "\n'
         '                   "match, %u with CPU-written constants on every draw, %u with no memory "\n'
         '                   "constants",\n'
         '                   repeatable, with_constants, fade_left_out, matched, cpu, no_memory);\n'
         '            const u32 all = std::accumulate(draws.begin(), draws.end(), 0u);\n'),
        ('            text += "]";\n'
         '        }\n'
         '    }\n'
         '    std::ranges::sort(unmatched, [](const auto& x, const auto& y) {\n',
         '            text += "]";\n'
         '        }\n'
         '    }\n'
         "    // (r50c) every shader once, whatever its classes and passes: the classes' draws above count\n"
         '    // a shader in each class it was seen in, so they cannot be summed for the share of draws\n'
         '    // whose constants are CPU-written\n'
         '    u32 once = 0;\n'
         '    std::array<u32, ConstantsNames.size()> once_draws{};\n'
         '    for (const auto& [hash, shader] : card_shaders) {\n'
         '        const auto found = analysed_shaders.find(hash);\n'
         '        if (found == analysed_shaders.end() || !found->second.RepeatableWithConstants() ||\n'
         '            std::ranges::all_of(CutoutDwords(found->second),\n'
         '                                [](const CutoutDword& d) { return d.kind == Ref::Immediate; })) {\n'
         '            continue;\n'
         '        }\n'
         '        ++once;\n'
         '        if (const auto seen = constants_seen.find(hash); seen != constants_seen.end()) {\n'
         '            for (size_t s = 0; s < once_draws.size(); ++s) {\n'
         '                once_draws[s] += seen->second.draws[s];\n'
         '            }\n'
         '        }\n'
         '    }\n'
         '    Append(text, "; (r50c) each shader once: %u with constants read from memory, %u draws:", once,\n'
         '           std::accumulate(once_draws.begin(), once_draws.end(), 0u));\n'
         '    for (size_t s = 0; s < once_draws.size(); ++s) {\n'
         '        Append(text, "%s %u %s", s ? "," : "", once_draws[s], ConstantsShort[s]);\n'
         '    }\n'
         '    std::ranges::sort(unmatched, [](const auto& x, const auto& y) {\n'),
    ],
    TESTS + "test_rt_card_alpha.cpp": [
        ('// SPDX-License-Identifier: GPL-2.0-or-later\n'
         '// bbport (r50_leaf-stage1, r50b_leaf-matcher): the cut-out analysis (cutout_analysis.h) on\n'
         '// fragment programs built as the translator and the passes before it leave them.\n'
         '#include <cassert>\n',
         '// SPDX-License-Identifier: GPL-2.0-or-later\n'
         '// bbport (r50_leaf-stage1, r50b_leaf-matcher, r50c_leaf-fade): the cut-out analysis\n'
         '// (cutout_analysis.h) on fragment programs built as the translator and the passes before it\n'
         "// leave them (r50c: some through the recompiler's own LowerBufferFormatToRaw and\n"
         '// ConstantPropagationPass).\n'
         '#include <cassert>\n'),
        ('#include <deque>\n'
         '#include "common/object_pool.h"\n',
         '#include <deque>\n'
         '#include <limits>\n'
         '#include "common/object_pool.h"\n'),
        ('#include "shader_recompiler/ir/passes/cutout_analysis.h"\n'
         '#include "shader_recompiler/ir/program.h"\n',
         '#include "shader_recompiler/ir/passes/cutout_analysis.h"\n'
         '#include "shader_recompiler/ir/passes/ir_passes.h"\n'
         '#include "shader_recompiler/ir/program.h"\n'),
        ('    // (r50b repair) shapes of the reviews\n'
         '    enum class Fade : u8 { Buffer, Input, Computed };\n'
         '    Fade fade_kind = Fade::Buffer; ///< the fade a buffer load, an input, saturate(an input)\n'
         '    enum class DitherK : u8 { Dword, PlusImm, TwoDwords };\n',
         '    // (r50b repair) shapes of the reviews\n'
         "    // (r50c) Alpha: the texture's alpha itself; Screen: FragCoord.x; Zero, Two, Inf: an\n"
         '    // immediate 0, 2 or +inf; ConstantLane: .w of a swizzle that puts the constant 1 there (a\n'
         "    // V#'s dst_sel 1); Dword: cb3[30], a dword from memory\n"
         '    enum class Fade : u8 {\n'
         '        Buffer,\n'
         '        Input,\n'
         '        Computed,\n'
         '        Alpha,\n'
         '        Screen,\n'
         '        Zero,\n'
         '        Two,\n'
         '        Inf,\n'
         '        ConstantLane,\n'
         '        Dword\n'
         '    };\n'
         '    Fade fade_kind = Fade::Buffer; ///< the fade a buffer load, an input, saturate(an input), ...\n'
         '    enum class DitherK : u8 { Dword, PlusImm, TwoDwords };\n'),
        ('    bool colour_nopersp = false;  ///< the colour interpolated by hand, no-perspective barycentrics\n'
         "    u32 dither_tsharp = 0;        ///< the dither's T# in the flat user data, this size (0: none)\n"
         '};\n'
         '\n'
         'IR::F32 Cb(IR::IREmitter& ir, u32 buffer, u32 dword) {\n',
         '    bool colour_nopersp = false;  ///< the colour interpolated by hand, no-perspective barycentrics\n'
         "    u32 dither_tsharp = 0;        ///< the dither's T# in the flat user data, this size (0: none)\n"
         "    // (r50c) the fade as the game's 9 camera pass shaders have it (r50_spv: a float storage\n"
         '    // buffer read at ((7 + 13 * instance) * 4 + 3)): .w of a typed load of a 32_32_32_32 float\n'
         "    // buffer, which AnalyzeLowered lowers with the recompiler's LowerBufferFormatToRaw\n"
         '    bool fade_typed = false;\n'
         '    // (r50c repair) the rows of the reviews: SmoothUv uint(uv.x * 64), ClipPos uint(pos.x * 100)\n'
         '    // (both smooth), NoPersp uint(Extra.x) of a no-perspective input, Bary\n'
         '    // uint(BaryCoordSmooth.x * 16), HandScaled uint(the instance id interpolated by hand * 64),\n'
         '    // FlatRecip uint(Extra.x * (1 / Extra.w)) of a flat input, Phi a phi of two rows, Quad a quad\n'
         '    // broadcast of the row; kept: Flat uint(Extra.x) of a flat input, Vertex1 uint(the instance\n'
         '    // id of vertex 1) (GetAttribute(Instance, 3, 1))\n'
         '    enum class FadeAt : u8 {\n'
         '        Instance,\n'
         '        FragCoord,\n'
         '        Divide,\n'
         '        Texel,\n'
         '        SmoothUv,\n'
         '        ClipPos,\n'
         '        NoPersp,\n'
         '        Bary,\n'
         '        HandScaled,\n'
         '        FlatRecip,\n'
         '        Phi,\n'
         '        Quad,\n'
         '        Flat,\n'
         '        Vertex1\n'
         '    };\n'
         "    FadeAt fade_at = FadeAt::Instance; ///< the typed load's row: from the instance id input,\n"
         '                                       ///< FragCoord.x, pos.x / pos.w, a texel of image 2, ...\n'
         '    bool instance_smooth = false; ///< (r50c repair) the Info says the instance id input is smooth\n'
         '};\n'
         '\n'
         "/// (r50c) The buffer the game's fade is read from (binding 2 in r50_spv/dbeccd9c.glsl).\n"
         'constexpr u32 FadeBuffer = 2;\n'
         "/// (r50c repair) An input only the fade's row reads; AnalyzeLowered gives it the interpolation\n"
         "/// the row's form needs (no-perspective or flat).\n"
         'constexpr IR::Attribute Extra = IR::Attribute::Param0 + 5;\n'
         '\n'
         'IR::F32 Cb(IR::IREmitter& ir, u32 buffer, u32 dword) {\n'),
        ('            fade = ir.FPSaturate(ir.GetAttribute(Uv, 2));\n'
         '        }\n',
         '            fade = ir.FPSaturate(ir.GetAttribute(Uv, 2));\n'
         '        } else if (f.fade_kind == GameForm::Fade::Alpha) {\n'
         '            fade = tw;\n'
         '        } else if (f.fade_kind == GameForm::Fade::Screen) {\n'
         '            fade = ir.GetAttribute(IR::Attribute::FragCoord, 0);\n'
         '        } else if (f.fade_kind == GameForm::Fade::Zero || f.fade_kind == GameForm::Fade::Two) {\n'
         '            fade = ir.Imm32(f.fade_kind == GameForm::Fade::Zero ? 0.0f : 2.0f);\n'
         '        } else if (f.fade_kind == GameForm::Fade::Inf) {\n'
         '            fade = ir.Imm32(std::numeric_limits<f32>::infinity());\n'
         '        } else if (f.fade_kind == GameForm::Fade::Dword) {\n'
         '            fade = Cb(ir, 3, 30);\n'
         '        } else if (f.fade_kind == GameForm::Fade::ConstantLane) {\n'
         '            // a swizzle (0, 1, 0, 0 are lanes 0-3 of the first vector) whose .w is the 1\n'
         '            const IR::Value load = ir.LoadBufferF32(4, ir.Imm32(FadeBuffer), address, {});\n'
         '            const IR::Value constants = ir.CompositeConstruct(ir.Imm32(0.0f), ir.Imm32(1.0f),\n'
         '                                                              ir.Imm32(0.0f), ir.Imm32(0.0f));\n'
         '            fade = IR::F32{\n'
         '                ir.CompositeExtract(ir.CompositeShuffle(constants, load, 4, 5, 6, 1), 3)};\n'
         '        } else if (f.fade_typed) {\n'
         '            IR::U32 index{address};\n'
         '            if (f.fade_at == GameForm::FadeAt::FragCoord) {\n'
         '                index = ir.ConvertFToU(32, ir.GetAttribute(IR::Attribute::FragCoord, 0));\n'
         '            } else if (f.fade_at == GameForm::FadeAt::Divide) {\n'
         '                index = ir.ConvertFToU(32, ir.FPDiv(ir.GetAttribute(Position, 0),\n'
         '                                                    ir.GetAttribute(Position, 3)));\n'
         '            } else if (f.fade_at == GameForm::FadeAt::Texel) {\n'
         '                index = ir.ConvertFToU(32, IR::F32{ir.CompositeExtract(\n'
         '                                               Sample(ir, 2, ir.GetAttribute(Uv, 0),\n'
         '                                                      ir.GetAttribute(Uv, 1)),\n'
         '                                               0)});\n'
         '            } else if (f.fade_at == GameForm::FadeAt::SmoothUv) {\n'
         '                index = ir.ConvertFToU(32, ir.FPMul(ir.GetAttribute(Uv, 0), ir.Imm32(64.0f)));\n'
         '            } else if (f.fade_at == GameForm::FadeAt::ClipPos) {\n'
         '                index = ir.ConvertFToU(32, ir.FPMul(pos(0), ir.Imm32(100.0f)));\n'
         '            } else if (f.fade_at == GameForm::FadeAt::NoPersp ||\n'
         '                       f.fade_at == GameForm::FadeAt::Flat) {\n'
         '                index = ir.ConvertFToU(32, ir.GetAttribute(Extra, 0));\n'
         '            } else if (f.fade_at == GameForm::FadeAt::Bary) {\n'
         '                index = ir.ConvertFToU(\n'
         '                    32, ir.FPMul(ir.GetAttribute(IR::Attribute::BaryCoordSmooth, 0),\n'
         '                                 ir.Imm32(16.0f)));\n'
         '            } else if (f.fade_at == GameForm::FadeAt::HandScaled) {\n'
         '                index =\n'
         '                    ir.ConvertFToU(32, ir.FPMul(Interpolated(ir, Instance, 3), ir.Imm32(64.0f)));\n'
         '            } else if (f.fade_at == GameForm::FadeAt::FlatRecip) {\n'
         '                index = ir.ConvertFToU(32, ir.FPMul(ir.GetAttribute(Extra, 0),\n'
         '                                                    ir.FPRecip(ir.GetAttribute(Extra, 3))));\n'
         '            } else if (f.fade_at == GameForm::FadeAt::Phi) {\n'
         '                // two ways in (the block its own predecessor: only the operands matter here),\n'
         "                // put at the block's end, where the emitter appends\n"
         '                const IR::U32 next = ir.IAdd(index, ir.Imm32(1u));\n'
         '                IR::Block* const block = next.Inst()->GetParent();\n'
         '                IR::Inst* const phi =\n'
         '                    &*block->PrependNewInst(block->end(), IR::Opcode::Phi, {}, u32(IR::Type::U32));\n'
         '                phi->AddPhiOperand(block, index);\n'
         '                phi->AddPhiOperand(block, next);\n'
         '                index = IR::U32{IR::Value{phi}};\n'
         '            } else if (f.fade_at == GameForm::FadeAt::Quad) {\n'
         '                index = ir.QuadBroadcast(index, ir.Imm32(0u));\n'
         '            } else if (f.fade_at == GameForm::FadeAt::Vertex1) {\n'
         '                index = ir.ConvertFToU(32, ir.GetAttribute(Instance, 3, 1));\n'
         '            }\n'
         '            // buffer_load_format_xyzw at dword (index + 7) * 4 (the patched address), .w taken\n'
         '            IR::BufferInstInfo typed{};\n'
         '            typed.index_enable.Assign(1);\n'
         '            typed.typed.Assign(1);\n'
         '            typed.inst_data_fmt.Assign(AmdGpu::DataFormat::Format32_32_32_32);\n'
         '            typed.inst_num_fmt.Assign(AmdGpu::NumberFormat::Float);\n'
         '            const IR::U32 dword = ir.IMul(ir.IAdd(index, ir.Imm32(7u)), ir.Imm32(4u));\n'
         '            fade = IR::F32{\n'
         '                ir.CompositeExtract(ir.LoadBufferFormat(ir.Imm32(FadeBuffer), dword, typed), 3)};\n'
         '        }\n'),
        ('                   "dither -1*cb3[21]*image1.w taken as 0, uv in1.xy (vs out 3) "\n'
         '                   "*cb1[0,1]+cb1[2,3], 1 factors of the nonzero term ignored (a buffer load)");\n'
         '    // 1c3953c6: pos interpolated by hand too (pervertexEXT)\n',
         '                   "dither -1*cb3[21]*image1.w taken as 0, uv in1.xy (vs out 3) "\n'
         '                   "*cb1[0,1]+cb1[2,3], 1 factors of the nonzero term left out (a buffer load; "\n'
         '                   "repeatable, fade left out)");\n'
         '    // 1c3953c6: pos interpolated by hand too (pervertexEXT)\n'),
        ('    assert(!c.RepeatableWithConstants());\n'
         '    assert(line.find("1 factors of the nonzero term ignored (an input)") != std::string::npos);\n'
         '    c = AnalyzeGame({.fade_kind = Fade::Computed});\n',
         '    assert(!c.RepeatableWithConstants());\n'
         '    assert(line.find("1 factors of the nonzero term ignored (an input; not repeatable)") !=\n'
         '           std::string::npos);\n'
         '    c = AnalyzeGame({.fade_kind = Fade::Computed});\n'),
        ('    assert(c.RepeatableFromRecord() && !c.RepeatableWithConstants());\n'
         '}\n',
         '    assert(c.RepeatableFromRecord() && !c.RepeatableWithConstants());\n'
         '}\n'
         '\n'
         '/// (r50c) GameTest as the recompiler hands it to the analysis: after LowerBufferFormatToRaw (a\n'
         '/// typed load becomes LoadBufferF32x4, its lanes extracted, built again and shuffled by the\n'
         '/// swizzle) and ConstantPropagationPass, the two passes between the translator and the analysis\n'
         '/// that change how the fade reads (recompiler.cpp). pass: through CutoutAnalysisPass (the map,\n'
         '/// the counts, the line), else AnalyzeCutout.\n'
         'Cutout AnalyzeLowered(const GameForm& f, u64 pgm_hash, bool pass, std::string* line = nullptr) {\n'
         '    Common::ObjectPool<IR::Inst> pool;\n'
         '    IR::Block block(pool);\n'
         '    IR::IREmitter ir(block);\n'
         '    Info info{};\n'
         '    info.sw_stage = SwStage::Fragment;\n'
         '    info.pgm_hash = pgm_hash;\n'
         '    RuntimeInfo runtime_info{};\n'
         '    runtime_info.Initialize(HwStage::Fragment, SwStage::Fragment);\n'
         '    GameInfo(f, info, runtime_info);\n'
         "    info.buffers.resize(FadeBuffer + 1); // the lowering looks at its load's buffer resource\n"
         '    if (f.instance_smooth) {\n'
         '        info.fs_interpolation[u32(Instance) - u32(IR::Attribute::Param0)] = {Qualifier::Smooth,\n'
         '                                                                             Qualifier::None};\n'
         '    }\n'
         '    if (f.fade_at == GameForm::FadeAt::NoPersp) {\n'
         '        info.fs_interpolation[u32(Extra) - u32(IR::Attribute::Param0)] = {\n'
         '            Qualifier::NoPerspective, Qualifier::None};\n'
         '    } else if (f.fade_at == GameForm::FadeAt::Flat || f.fade_at == GameForm::FadeAt::FlatRecip) {\n'
         '        info.fs_interpolation[u32(Extra) - u32(IR::Attribute::Param0)] = {Qualifier::Flat,\n'
         '                                                                          Qualifier::None};\n'
         '    }\n'
         '    GameTest(ir, f);\n'
         '    IR::Program program(info);\n'
         '    program.blocks.push_back(&block);\n'
         '    program.post_order_blocks.push_back(&block);\n'
         '    Optimization::LowerBufferFormatToRaw(program);\n'
         '    Optimization::ConstantPropagationPass(program.post_order_blocks);\n'
         '    if (f.fade_typed) {\n'
         '        // the form the analysis must see: the typed load lowered, its shuffle not folded\n'
         '        u32 format = 0, loads = 0, shuffles = 0;\n'
         '        for (const IR::Inst& inst : block.Instructions()) {\n'
         '            format += inst.GetOpcode() == IR::Opcode::LoadBufferFormatF32 ? 1 : 0;\n'
         '            loads += inst.GetOpcode() == IR::Opcode::LoadBufferF32x4 ? 1 : 0;\n'
         '            shuffles += inst.GetOpcode() == IR::Opcode::CompositeShuffleF32x4 ? 1 : 0;\n'
         '        }\n'
         '        assert(format == 0 && loads == 1 && shuffles == 1);\n'
         '    }\n'
         '    if (pass) {\n'
         '        Optimization::CutoutAnalysisPass(program, runtime_info);\n'
         '    } else {\n'
         '        info.cutout = Optimization::AnalyzeCutout(program, runtime_info);\n'
         '    }\n'
         '    if (line) {\n'
         '        *line = Optimization::CutoutLine(info, runtime_info);\n'
         '    }\n'
         '    return info.cutout;\n'
         '}\n'
         '\n'
         "/// (r50c) The fade of the game's 9 camera pass pixel shaders (a89e01e9, 998b035e, dbeccd9c,\n"
         '/// 70bb42af, 1c3953c6, 0f54e5f9, 2140da2b, 765450df, 6720ae0d: one form, a per-instance float of\n'
         "/// a storage buffer read by a typed load), which r50b's log called computed, and the factors that\n"
         '/// must not be left out of the shadow rule.\n'
         'void CheckFadeForms() {\n'
         '    using Fade = GameForm::Fade;\n'
         '    using FadeAt = GameForm::FadeAt;\n'
         '    std::string line;\n'
         '    const std::string left_out =\n'
         '        ", 1 factors of the nonzero term left out (a buffer load; repeatable, fade left out)";\n'
         '    // the fade form on each of the alpha forms the 9 shaders have: the colour by hand\n'
         '    // (dbeccd9c), the position by hand too (1c3953c6), the colour by the hardware (0f54e5f9 and\n'
         '    // others), the colour first and D sampled first (6720ae0d)\n'
         '    for (const GameForm& f :\n'
         '         {GameForm{.fade_typed = true}, GameForm{.manual_position = true, .fade_typed = true},\n'
         '          GameForm{.manual_colour = false, .fade_typed = true},\n'
         '          GameForm{.manual_position = true, .colour_first = true, .fade_typed = true}}) {\n'
         '        const Cutout c = AnalyzeLowered(f, 0xdbeccd9c, false, &line);\n'
         "        CheckGameRecord(c, true, true, 1); // a buffer load, repeatable with the draw's constants\n"
         '        assert(line.find(left_out) != std::string::npos);\n'
         '    }\n'
         '    std::printf("%s\\n", line.c_str());\n'
         '    // the sun shadow pass forms are not changed by the lowering (no fade)\n'
         '    Cutout c = AnalyzeLowered({.dither = false, .fade = false}, 0x92852ef3, false);\n'
         '    CheckGameRecord(c, false, true, 0);\n'
         '\n'
         "    // the factor the texture's alpha itself (A * T.w): a second texture term, never left out\n"
         '    c = AnalyzeLowered({.fade_kind = Fade::Alpha}, 0x50c0, false);\n'
         '    assert(c.verdict != Cutout::Verdict::Matched && c.ignored_factor_terms == 0);\n'
         '    // ... sampled from another texture, or a typed load at a row a texel gives: several textures\n'
         '    c = AnalyzeLowered({.fade_textured = true}, 0x50c0, false);\n'
         '    assert(c.verdict == Cutout::Verdict::SeveralTextures);\n'
         '    c = AnalyzeLowered({.fade_typed = true, .fade_at = FadeAt::Texel}, 0x50c0, false);\n'
         '    assert(c.verdict == Cutout::Verdict::SeveralTextures);\n'
         "    // ... the pixel's position (FragCoord.x), or a typed load at a row that differs across a\n"
         "    // triangle (r50c repair: the reviews' rows): FragCoord.x, pos.x / pos.w, a smooth uv.x * 64\n"
         '    // or pos.x * 100, a no-perspective input, the barycentrics alone, the instance id\n'
         '    // interpolated by hand but scaled before the conversion, a flat input over its own w (the\n'
         '    // divide refused as a guard), a phi, a quad broadcast: matched, the factor computed, not\n'
         '    // repeatable, and the line says so\n'
         '    for (const FadeAt at : {FadeAt::FragCoord, FadeAt::Divide, FadeAt::SmoothUv, FadeAt::ClipPos,\n'
         '                            FadeAt::NoPersp, FadeAt::Bary, FadeAt::HandScaled, FadeAt::FlatRecip,\n'
         '                            FadeAt::Phi, FadeAt::Quad}) {\n'
         '        for (const bool manual : {false, true}) {\n'
         '            c = AnalyzeLowered({.manual_position = manual, .fade_typed = true, .fade_at = at},\n'
         '                               0x50c0, false, &line);\n'
         '            assert(c.verdict == Cutout::Verdict::Matched && c.nonzero);\n'
         '            assert(c.ignored_factor_terms == 1 && c.ignored_kinds == Cutout::IgnoredComputed);\n'
         '            assert(!c.RepeatableWithConstants());\n'
         '            assert(line.find(", 1 factors of the nonzero term ignored (computed; not "\n'
         '                             "repeatable)") != std::string::npos);\n'
         '        }\n'
         '    }\n'
         '    c = AnalyzeLowered({.fade_kind = Fade::Screen}, 0x50c0, false, &line);\n'
         '    assert(c.verdict == Cutout::Verdict::Matched && c.ignored_kinds == Cutout::IgnoredComputed);\n'
         '    assert(!c.RepeatableWithConstants());\n'
         '    // ... rows that hold one value across a triangle: a flat input, and the instance id of one\n'
         '    // vertex read as it is (a per-vertex input): a buffer load, left out\n'
         '    for (const FadeAt at : {FadeAt::Flat, FadeAt::Vertex1}) {\n'
         '        c = AnalyzeLowered({.fade_typed = true, .fade_at = at}, 0x50c0, false, &line);\n'
         '        CheckGameRecord(c, true, true, 1);\n'
         '        assert(line.find(left_out) != std::string::npos);\n'
         '    }\n'
         '    // ... the instance id interpolated by hand, but the input smooth (the Info says so): the\n'
         '    // interpolation is no per-vertex one, so the barycentrics are read: computed\n'
         '    c = AnalyzeLowered({.fade_typed = true, .instance_smooth = true}, 0x50c0, false);\n'
         '    assert(c.verdict == Cutout::Verdict::Matched && c.ignored_kinds == Cutout::IgnoredComputed);\n'
         '    // ... an immediate 0 (the term discards every pixel) or +inf: computed, not repeatable\n'
         '    for (const Fade kind : {Fade::Zero, Fade::Inf}) {\n'
         '        c = AnalyzeLowered({.fade_kind = kind}, 0x50c0, false);\n'
         '        assert(c.verdict == Cutout::Verdict::Matched && c.ignored_kinds == Cutout::IgnoredComputed);\n'
         '        assert(c.ignored_factor_terms == 1 && !c.RepeatableWithConstants());\n'
         '    }\n'
         '    // ... a dword from memory (cb3[30]): a value of the draw the record does not keep, where a\n'
         '    // 0 hides the draw: dwords and computed, not repeatable (r50c repair)\n'
         '    c = AnalyzeLowered({.fade_kind = Fade::Dword}, 0x50c0, false, &line);\n'
         '    assert(c.verdict == Cutout::Verdict::Matched && c.ignored_factor_terms == 1);\n'
         '    assert(c.ignored_kinds == (Cutout::IgnoredDword | Cutout::IgnoredComputed));\n'
         '    assert(!c.RepeatableWithConstants());\n'
         '    assert(line.find(", 1 factors of the nonzero term ignored (dwords/computed; not repeatable)") !=\n'
         '           std::string::npos);\n'
         "    // a swizzle's constant 1 in the lane (ThroughComposites into the shuffle's first vector): no\n"
         '    // factor (r50c repair: as a direct immediate), nothing left out\n'
         '    c = AnalyzeLowered({.fade_kind = Fade::ConstantLane}, 0x50c0, false, &line);\n'
         '    assert(c.verdict == Cutout::Verdict::Matched && c.nonzero);\n'
         '    assert(c.ignored_factor_terms == 0 && c.ignored_kinds == 0 && c.RepeatableWithConstants());\n'
         '    assert(line.find("factors of the nonzero term") == std::string::npos);\n'
         '    // a record refused for its coordinates, its fade a buffer load: the line blames no factor\n'
         '    c = AnalyzeLowered({.uv_scaled_twice = true, .fade_typed = true}, 0x50c0, false, &line);\n'
         '    assert(c.verdict == Cutout::Verdict::Matched && !c.RepeatableWithConstants());\n'
         '    assert(c.ignored_kinds == Cutout::IgnoredBuffer);\n'
         '    assert(line.ends_with(", 1 factors of the nonzero term ignored (a buffer load)"));\n'
         "    // an immediate 2 is the alpha's own scale (r50b): nothing to leave out\n"
         '    c = AnalyzeLowered({.fade_kind = Fade::Two}, 0x50c0, false);\n'
         '    assert(c.verdict == Cutout::Verdict::Matched && c.nonzero && c.ignored_factor_terms == 0);\n'
         '    assert(c.RepeatableWithConstants());\n'
         '}\n'
         '\n'
         '/// (r50c) The 600-frame lines count the records that leave the fade out (after CheckSummary:\n'
         '/// its records are in the counts, with constants 2 of which 1 leaves the fade out).\n'
         'void CheckFadeCounts() {\n'
         '    (void)AnalyzeLowered({.fade_typed = true}, 0x50c1, true);\n'
         '    (void)AnalyzeLowered({.fade_typed = true, .fade_at = GameForm::FadeAt::FragCoord}, 0x50c2,\n'
         '                         true);\n'
         '    Optimization::NoteCutoutCard(0x50c1, 0, Optimization::CutoutCardClass::Plant);\n'
         '    Optimization::NoteCutoutCard(0x50c2, 0, Optimization::CutoutCardClass::Plant);\n'
         '    const std::string totals = Optimization::CutoutSummaryText();\n'
         '    std::printf("%s\\n", totals.c_str());\n'
         '    assert(totals.find(" (r50c: of the 3 repeatable with the draw\'s constants, 1 leave nothing "\n'
         '                       "out, 2 leave the fade out:") != std::string::npos);\n'
         '    const std::string cards = Optimization::CutoutCardsText();\n'
         '    std::printf("%s\\n", cards.c_str());\n'
         '    assert(cards.find("plants (left out of lamp rays: a skeleton, no sun shadow pass draw) 3 [3 "\n'
         '                      "match; 1 repeatable, 2 with constants (r50c: 1 with the fade left out); "\n'
         '                      "3 match,") != std::string::npos);\n'
         '    // (r50c repair) the draws of every shader once: 0x4321 (5 draws) and 0x50c1 (none yet) read\n'
         '    // memory constants; 0x1234 has none, 0x50c2 is not repeatable\n'
         '    const std::string once = "; (r50c) each shader once: 2 with constants read from memory, 5 "\n'
         '                             "draws: 2 CPU-written, 1 in place, 1 GPU-written, 0 unreadable, 1 "\n'
         '                             "another permutation;";\n'
         '    assert(cards.find(once) != std::string::npos);\n'
         "    // 0x4321 seen as a plant too: the plants' class counts its 5 draws, each shader once does not\n"
         '    Optimization::NoteCutoutCard(0x4321, 0, Optimization::CutoutCardClass::Plant);\n'
         '    const std::string twice = Optimization::CutoutCardsText();\n'
         '    assert(twice.find("plants (left out of lamp rays: a skeleton, no sun shadow pass draw) 4 [") !=\n'
         '           std::string::npos);\n'
         '    assert(twice.find("with no memory constants; 5 draws: 2 CPU-written, 1 in place, 1 "\n'
         '                      "GPU-written, 0 unreadable, 1 another permutation], left out, no skeleton") !=\n'
         '           std::string::npos);\n'
         '    assert(twice.find(once) != std::string::npos);\n'
         '}\n'),
        ('                   "3), ref 0.3 + 0.5*0.2 = 0.4, camera dither -0.2*image1.w (4x4) (taken as 0), "\n'
         '                   "alpha factor in2.w (vs out 4, flat), stored channel a, CPU-written");\n'
         '    const Cutout sun = AnalyzeGame({.dither = false, .vertex_alpha = false, .fade = false});\n',
         '                   "3), ref 0.3 + 0.5*0.2 = 0.4, camera dither -0.2*image1.w (4x4) (taken as 0), "\n'
         '                   "alpha factor in2.w (vs out 4, flat), fade left out (1 factors of the nonzero "\n'
         '                   "term: a buffer load), stored channel a, CPU-written");\n'
         '    const Cutout sun = AnalyzeGame({.dither = false, .vertex_alpha = false, .fade = false});\n'),
        ('    assert(cards.find("plants (left out of lamp rays: a skeleton, no sun shadow pass draw) 1 [1 "\n'
         '                      "match; 1 repeatable, 1 with constants; 1 match, 0 with CPU-written "\n'
         '                      "constants on every draw, 1 with no memory constants]") != std::string::npos);\n'
         '    assert(cards.find("kept whole: a skeleton (hair, cloth, characters) 1 [1 not analysed; 0 "\n'
         '                      "repeatable, 0 with constants; 0 match, 0 with CPU-written constants on "\n'
         '                      "every draw, 0 with no memory constants]") != std::string::npos);\n'
         '    assert(cards.find("0000000000005678 (skeleton, kept; not analysed)") != std::string::npos);\n',
         '    assert(cards.find("plants (left out of lamp rays: a skeleton, no sun shadow pass draw) 1 [1 "\n'
         '                      "match; 1 repeatable, 1 with constants (r50c: 0 with the fade left out); 1 "\n'
         '                      "match, 0 with CPU-written constants on every draw, 1 with no memory "\n'
         '                      "constants]") != std::string::npos);\n'
         '    assert(cards.find("kept whole: a skeleton (hair, cloth, characters) 1 [1 not analysed; 0 "\n'
         '                      "repeatable, 0 with constants (r50c: 0 with the fade left out); 0 match, 0 "\n'
         '                      "with CPU-written constants on every draw, 0 with no memory constants]") !=\n'
         '           std::string::npos);\n'
         '    assert(cards.find("0000000000005678 (skeleton, kept; not analysed)") != std::string::npos);\n'),
        ('           std::string::npos);\n'
         '    const char* const no_draws = "left out, no skeleton 1 [1 match; 0 repeatable, 1 with "\n'
         '                                 "constants; 1 match, 0 with CPU-written constants on every draw, "\n'
         '                                 "0 with no memory constants]";\n'
         '    assert(Optimization::CutoutCardsText().find(no_draws) != std::string::npos);\n',
         '           std::string::npos);\n'
         "    // (r50c) the game's form (0x4321) leaves its fade out: counted so\n"
         '    assert(totals.find(" (r50c: of the 2 repeatable with the draw\'s constants, 1 leave nothing "\n'
         '                       "out, 1 leave the fade out: factors of the nonzero term that are a buffer "\n'
         '                       "load, which the game\'s sun shadow pass does not have)") !=\n'
         '           std::string::npos);\n'
         '    const char* const no_draws = "left out, no skeleton 1 [1 match; 0 repeatable, 1 with "\n'
         '                                 "constants (r50c: 1 with the fade left out); 1 match, 0 with "\n'
         '                                 "CPU-written constants on every draw, 0 with no memory constants]";\n'
         '    assert(Optimization::CutoutCardsText().find(no_draws) != std::string::npos);\n'),
        ('    assert(Optimization::CutoutCardsText().find(\n'
         '               "1 [1 match; 1 repeatable, 1 with constants; 1 match, 0 with CPU-written constants "\n'
         '               "on every draw, 1 with no memory constants]") != std::string::npos);\n'
         '\n',
         '    assert(Optimization::CutoutCardsText().find(\n'
         '               "1 [1 match; 1 repeatable, 1 with constants (r50c: 0 with the fade left out); 1 "\n'
         '               "match, 0 with CPU-written constants on every draw, 1 with no memory constants]") !=\n'
         '           std::string::npos);\n'
         '\n'),
        ('    std::string text = Optimization::CutoutCardsText();\n'
         '    assert(text.find("left out, no skeleton 1 [1 match; 0 repeatable, 1 with constants; 1 match, "\n'
         '                     "1 with CPU-written constants on every draw, 0 with no memory constants; 3 "\n'
         '                     "draws: 2 CPU-written, 0 in place, 0 GPU-written, 0 unreadable, 1 another "\n',
         '    std::string text = Optimization::CutoutCardsText();\n'
         '    assert(text.find("left out, no skeleton 1 [1 match; 0 repeatable, 1 with constants (r50c: 1 "\n'
         '                     "with the fade left out); 1 match, 1 with CPU-written constants on every "\n'
         '                     "draw, 0 with no memory constants; 3 "\n'
         '                     "draws: 2 CPU-written, 0 in place, 0 GPU-written, 0 unreadable, 1 another "\n'),
        ('    CheckGameForms();\n'
         '    CheckReviewProbes();\n',
         '    CheckGameForms();\n'
         '    CheckFadeForms();\n'
         '    CheckReviewProbes();\n'),
        ('    CheckSummary();\n'
         '    std::printf("rt-card-alpha-test: ok (alpha tests, coordinates, shaders not matched, the "\n'
         '                "game\'s forms, the reviews\' probes)\\n");\n'
         '    return 0;\n',
         '    CheckSummary();\n'
         '    CheckFadeCounts();\n'
         '    std::printf("rt-card-alpha-test: ok (alpha tests, coordinates, shaders not matched, the "\n'
         '                "game\'s forms, the reviews\' probes, the fade forms)\\n");\n'
         '    return 0;\n'),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text (looked at with LF line ends)."""
    texts = {path: text.replace("\r\n", "\n") for path, text in texts.items()}
    ok = True
    bs = chr(92)
    if any(foreign(p) for p in EDITS):
        print("this round would touch a file of another round, the drawn look or the fog")
        ok = False
    for path, text in texts.items():
        if any(ord(ch) > 126 or (ord(ch) < 32 and ch not in "\n\t") for ch in text):
            print("%s: not ASCII" % path)
            ok = False
    cpp = texts[P + "cutout_analysis_pass.cpp"]
    test = texts[TESTS + "test_rt_card_alpha.cpp"]
    # r54_leaf-stage2 anchors on these; each must stay there exactly once.
    for needle in ('#include "shader_recompiler/ir/program.h"\n',
                   "bool CutoutAnalysisOn() {\n    static const bool on = [] {\n"
                   "        const char* env = std::getenv(\"BB_RT_CARD_ALPHA_LOG\");\n"
                   "        return env && std::strcmp(env, \"1\") == 0;\n    }();\n    return on;\n}\n",
                   "    std::printf(\"%s" + bs + "n\", CutoutLine(info, runtime_info).c_str());\n}\n",
                   "void PrintCutoutSummary() {\n    if (!CutoutAnalysisOn()) {\n",
                   'std::getenv("BB_RT_CARD_ALPHA_LOG")'):
        if cpp.count(needle) != 1:
            print("cutout_analysis_pass.cpp: an anchor of r54 is not there once: %a" % needle[:60])
            ok = False
    # The r50 and r50b lines keep their tags; r50c adds no line of its own.
    if cpp.count('"Cut-out pixel shader %016llx (r50): %s"') != 1 or \
            cpp.count('"Ray tracing cut-out shaders (r50, BB_RT_CARD_ALPHA_LOG=1): ') != 1 or \
            cpp.count('"Ray tracing cut-out cards\' pixel shaders (r50, BB_RT_CARD_ALPHA_LOG=1): ') != 1 or \
            cpp.count('"Cut-out constants %016llx (r50b): ') != 1:
        print("cutout_analysis_pass.cpp: the log lines' tags are not r50's and r50b's")
        ok = False
    for needle, n in (("LaneSource ThroughComposites(IR::Value value) {", 1),
                      ("bool PerVertexAddress(const IR::Inst& load, const Info* info) {", 1),
                      ("bool IsBufferLoad(IR::Opcode opcode) {", 1),
                      ("    const LaneSource source = ThroughComposites(value);\n", 1),
                      ("return PerVertexAddress(*inst, info) ? Cutout::IgnoredBuffer : Cutout::IgnoredComputed;", 1),
                      ('left_out  ? "; repeatable, fade left out"', 1), ('varying ? "; not repeatable"', 1),
                      ('"; (r50c) each shader once: %u with constants read from memory, %u draws:"', 1),
                      ("            return Cutout::IgnoredDword | Cutout::IgnoredComputed;\n", 1),
                      ("            n->count += kind != 0 ? 1 : 0;\n", 1),
                      ('" (r50c: of the %u repeatable with the draw\'s constants, %u leave nothing out, %u leave "', 1),
                      ("(r50c: %u with the fade left out)", 1),
                      ('", fade left out (%u factors of the nonzero term: %s)"', 1),
                      ("counts.fade_left_out += c.RepeatableWithConstants() && c.ignored_factor_terms != 0 ? 1 : 0;", 1),
                      ("IR::Opcode::CompositeShuffleF32x4", 1), ("IR::Opcode::LoadBufferF32x4", 1)):
        if cpp.count(needle) != n:
            print("cutout_analysis_pass.cpp: %a is there %d times (want %d)" % (needle[:70], cpp.count(needle), n))
            ok = False
    # An address that differs across a triangle makes the load computed: the walk refuses an
    # input that is not per vertex or flat, barycentrics outside an interpolation by hand that goes
    # straight into a conversion, a division or reciprocal, a phi, a sample, lane values, atomics.
    walk = cpp[cpp.find("bool PerVertexAddress(const IR::Inst& load, const Info* info) {"):]
    walk = walk[:walk.find("\n}\n")]
    for needle in ("IR::Opcode::FPRecip32", "IR::Opcode::FPDiv32", "IR::Opcode::Phi", "IsSample(",
                   "IR::IsParam(", "TriangleConstantInput(", "HandInterpolatedPerVertex(",
                   "IR::Opcode::QuadBroadcast", "IR::Opcode::LoadSharedU32", "IsAtomic("):
        if needle not in walk:
            print("cutout_analysis_pass.cpp: PerVertexAddress does not look at %s" % needle)
            ok = False
    # The C escapes must have kept their backslash on the way into this script.
    if 'std::printf("%s' + bs + 'n", text.c_str());' not in cpp or \
            "the fade forms)" + bs + 'n");' not in test or \
            'analysed in %.2f ms' + bs + 'n", ms);' not in test:
        print("a C escape lost its backslash on the way into the script")
        ok = False
    for needle in ("void CheckFadeForms() {", "void CheckFadeCounts() {", "    CheckFadeForms();\n",
                   "    CheckFadeCounts();\n", "Optimization::LowerBufferFormatToRaw(program);",
                   "Optimization::ConstantPropagationPass(program.post_order_blocks);"):
        if test.count(needle) != 1:
            print("test_rt_card_alpha.cpp: %a is not there once" % needle)
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
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r50c_leaf-fade.py check|apply|revert   (the tree: R50C_ROOT, else the current "
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
