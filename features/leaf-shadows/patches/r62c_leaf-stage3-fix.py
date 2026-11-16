# r62c_leaf-stage3-fix: the fix of the BB_RT_CARD_ALPHA=1/2 slowdown (2-3 FPS instead of 95 at
# the save copy "lamp-test-spot"; "Lighting: point shadows" and "indirect light" 100s of ms).
#
# CAUSE (from the r62d diagnosis runs, S/r62d_run_0..6.txt, 2026-11-15): with BB_RT_CARD_ALPHA on,
# every capture pipeline got MotionVectors::CaptureUv, and a capture vertex shader with CaptureUv
# was always the RECOMPILER's (r54 kept it from the lifter so that its EmitCardUvStore could
# store the card UVs). Those recompiler capture vertex shaders store broken BLAS input for the
# camera-pass draws (corners not finite, edges up to 3.4e38 m), so lamp and bounce rays walk
# huge boxes. The r62d geometry check proves it: BB_RT_CARD_UV_DIAG=2 (no CaptureUv anywhere:
# the lifter's vertex shaders, as with the knob off) 93.8 FPS (knob off 93.5), 600 frames, 425M
# triangles checked, 0 not finite, 0 edges over 200 m; =1 (no UV capture at all, but the
# recompiler's vertex shaders) 1.0 FPS, in 143 frames 143950 corners not finite and 3.57M edges
# over 200 m (longest finite 3.4e38 m); =3 (fix A, the write-after-read barrier) 0.9 FPS, the
# same; =4/=5 (CaptureUv only where the pixel shader discards) 17.7/18.5 FPS, the bad builds are
# then ALL card entries of one vertex shader (9da6aacb, camera mask).
# Every named bad build has the camera mask (a motion + capture "VertexBoth" pipeline). The
# exact defect inside the recompiler's module is NOT known (its SPIR-V was decompiled and does
# the same as the lifter's except a plain 16-byte position store where the lifter stores the
# four components atomically); this patch does not depend on it: no capture vertex shader comes
# from the recompiler any more while the lifter is on.
#
# WHAT (only with BB_RT_CARD_ALPHA 1 or 2; the knob off is untouched, see KNOB OFF):
#  1. CaptureUv only on capture pipelines whose pixel shader discards (r62d's "fix B", now the
#     rule for BB_RT_CARD_UV_DIAG 0, 1, 3, 4 and 5; 2 still means never). The UVs are captured
#     only for such draws anyway (ResolveCardDraw needs has_discard): every other capture
#     pipeline has exactly the key and the lifter module of the knob off (cache hits, no extra
#     variants).
#  2. The lifter stores the card UVs (Lifter::Input::capture_uv, lift_stage.cpp VertexCapture):
#     the same values, places and selector as the recompiler's EmitCardUvStore (u, v, the alpha
#     factor; and the fourth value r62b adds when MotionVectors::CaptureUvStride is 16), the
#     ring's address as the address block's last member (as DefineMotionAddressBlock). So a
#     capture vertex shader with CaptureUv is the LIFTER's again (CompileModule asks the lifter
#     for it as for any other). If the lifter declines one (or is off), the recompiler's is used
#     as before and one line names it ("Ray tracing card UVs (r62c): the lifter declined ...").
#  No new knob: the behaviour is BB_RT_CARD_ALPHA's own (read once at start, as before). An A/B
#  knob for the recompiler's capture was left out on purpose: the cache keeps one SPIR-V a
#  (shader, permutation) whichever compiler made it, so such a knob would not switch modules
#  that are already cached. The A/B is r62d's BB_RT_CARD_UV_DIAG (1 against 2), already run.
#
# KNOB OFF (BB_RT_CARD_ALPHA unset or 0): no key or runtime info has CaptureUv, so
# Lifter::Input::capture_uv is false and the lifter emits exactly the SPIR-V of before (the new
# code sits under `if (uv)` / `if (in.capture_uv)`, the address block's type and decorations
# are the old ones); CompileModule takes the same branch as before (card_uv_capture false);
# CaptureUvWanted is false as before. Commands, keys and SPIR-V are as today. The GPU cache id
# changes (vk_pipeline_cache.cpp, cutout_analysis_pass.cpp, emit_spirv_special.cpp are hashed by
# build.sh): the first start recompiles the cache (bb-shader-lab), as after every such patch.
#
# COST. Knob off: none. Knob on: fewer pipeline variants than r54 (only cut-out capture
# pipelines differ from the knob off); a capture vertex shader with CaptureUv does, per vertex
# whose param names a ring place, 2 selects per written output (at most 32), 3 or 4 dynamic
# extracts and 3 or 4 4-byte stores - as the recompiler's did. Nothing new on the CPU per draw.
#
# APPLY: on top of <tree> as it is on 2026-11-15 after the r62d build (upstream 78c7449,
# r62, r61, r65, r64, r64b, r67, r68, r62d). r62d STAYS (this uses its CaptureUvWanted and
# FragmentDiscards, its warm-up rule for keys whose UVs follow the pixel shader, and its geometry
# check BB_RT_GEOMETRY_CHECK=1 for the game test). r62b and r63 apply on top unchanged (checked
# on a copy: r62c, r62b, r63 and every revert order byte exact; S/r62c_proof.sh).
#
# Use: cd <tree> && python -I -X utf8 r62c_leaf-stage3-fix.py check | apply | revert
# (the tree: R62C_ROOT, else the current directory). Every edit is an exact text found exactly
# once; revert gives the files back byte for byte. Line ends are kept (all touched files are
# CRLF). Nothing is written before every text of the mode is made; a failed write puts back what
# was already moved. apply keeps the originals in r62c_backup/ beside this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r62c_backup")
ROOT = (os.environ.get("R62C_ROOT") or os.getcwd()).replace("\\", "/").rstrip("/") + "/"
G = "engine/gpu/"
SR = G + "shadps4/shader_recompiler/"
P = SR + "ir/passes/"
VK = G + "shadps4/video_core/renderer_vulkan/"
LF = G + "shim/lifter/"
TMP = ".r62ctmp"

EDITS = {
    # ------------------------------------------------------------------ the rule and the knob
    P + "cutout_analysis.h": [(r"""/// (r62d_card-uv-diag) Whether a capture pipeline's key and vertex shader get the card UVs
/// (MotionVectors::CaptureUv): CardAlphaOn(), except with BB_RT_CARD_UV_DIAG=2 (never) and 4 or
/// 5 (only when its pixel shader discards: `discards`). With 0, 1 and 3 it is CardAlphaOn().
[[nodiscard]] bool CaptureUvWanted(bool discards);
""", r"""/// (r62d_card-uv-diag, r62c_leaf-stage3-fix) Whether a capture pipeline's key and vertex shader
/// get the card UVs (MotionVectors::CaptureUv): CardAlphaOn() and its pixel shader discards
/// (`discards`; only such draws have their UVs captured, ResolveCardDraw), every other capture
/// pipeline is as with the knob off; never with BB_RT_CARD_UV_DIAG=2. (r62d: with 0, 1 and 3 it
/// was CardAlphaOn() alone, which gave every capture pipeline the recompiler's vertex shader.)
[[nodiscard]] bool CaptureUvWanted(bool discards);
""")],
    P + "cutout_analysis_pass.cpp": [(r"""bool CaptureUvWanted(bool discards) {
    const u32 diag = CardUvDiag();
    return CardAlphaOn() && diag != 2 && ((diag != 4 && diag != 5) || discards);
}
""", r"""bool CaptureUvWanted(bool discards) {
    // bbport (r62c_leaf-stage3-fix): the pixel shader must discard with every diag value (r62d's
    // 4 and 5 made the rule); 2 is still never
    const u32 diag = CardUvDiag();
    return CardAlphaOn() && diag != 2 && discards;
}
""")],
    # ------------------------------------------------------------------ CompileModule
    VK + "vk_pipeline_cache.cpp": [(r"""// bbport (r62d_card-uv-diag): whether the selection's pixel shader discards (bound before the
""", r"""// bbport (r62c_leaf-stage3-fix): a capture vertex shader with the card UVs that the lifter
// declined (or the lifter is off): the recompiler's is used, whose capture made the broken BLAS
// input of the BB_RT_CARD_ALPHA slowdown (r62d). Said for the first 16, then every 64th.
static void NoteCardUvRecompiled(u64 pgm_hash, const std::string& why) {
    static std::atomic<u32> count{0};
    const u32 n = count.fetch_add(1, std::memory_order_relaxed) + 1;
    if (n <= 16 || n % 64 == 0) {
        std::printf("Ray tracing card UVs (r62c): the lifter declined capture vertex shader "
                    "%016llx (%.120s): the recompiler's is used (its BLAS input may be broken); "
                    "%u so far\n",
                    static_cast<unsigned long long>(pgm_hash), why.c_str(), n);
    }
}

// bbport (r62d_card-uv-diag): whether the selection's pixel shader discards (bound before the
"""), (r"""    // bbport (r54_leaf-stage2): a capture vertex shader with the card UVs (CaptureUv,
    // BB_RT_CARD_ALPHA=1) keeps the recompiler's SPIR-V. Only its EmitVertexCapture stores the
    // UVs (EmitCardUvStore); the lifter's capture stores the positions alone, so its module
    // would leave the ring unwritten while the CPU names a place in it. With the knob off no
    // key has CaptureUv and the lifter is asked as before.
    const bool card_uv_capture =
        info.hw_stage == HwStage::Vertex &&
        (runtime_before.hw.vs.motion_vectors & Shader::MotionVectors::CaptureUv) != 0;
    if (Lifter::GetMode() != Lifter::Mode::Off && !EffectShaders::KeepRecompiled(info) &&
        !card_uv_capture) {
        auto lifted = Lifter::Lift(Lifter::MakeInput(info, runtime_before, profile, binding_before, code));
        if (lifted.ok() && lifted.uses_tone_curve == info.uses_tone_curve) {
            spv = std::move(lifted.spirv);
        } else {
            LOG_INFO(Render_Vulkan, "Lifter declined {:#x}: {}", info.pgm_hash, lifted.decline);
        }
    }
""", r"""    // bbport (r54_leaf-stage2, r62c_leaf-stage3-fix): a capture vertex shader with the card UVs
    // (CaptureUv, BB_RT_CARD_ALPHA on, a pixel shader that discards) is the lifter's too: its
    // VertexCapture stores the UVs as the recompiler's EmitCardUvStore does (r62c). r54 kept the
    // recompiler's here, and its capture made broken BLAS input (the BB_RT_CARD_ALPHA slowdown,
    // r62d). A declined one is said. With the knob off no key has CaptureUv and the lifter is
    // asked as before.
    const bool card_uv_capture =
        info.hw_stage == HwStage::Vertex &&
        (runtime_before.hw.vs.motion_vectors & Shader::MotionVectors::CaptureUv) != 0;
    if (Lifter::GetMode() != Lifter::Mode::Off && !EffectShaders::KeepRecompiled(info)) {
        auto lifted = Lifter::Lift(Lifter::MakeInput(info, runtime_before, profile, binding_before, code));
        if (lifted.ok() && lifted.uses_tone_curve == info.uses_tone_curve) {
            spv = std::move(lifted.spirv);
        } else {
            LOG_INFO(Render_Vulkan, "Lifter declined {:#x}: {}", info.pgm_hash, lifted.decline);
            if (card_uv_capture) { // bbport (r62c_leaf-stage3-fix)
                NoteCardUvRecompiled(info.pgm_hash, lifted.decline.empty()
                                                        ? std::string("tone curve")
                                                        : lifted.decline);
            }
        }
    } else if (card_uv_capture) { // bbport (r62c_leaf-stage3-fix)
        NoteCardUvRecompiled(info.pgm_hash, "lifter off");
    }
""")],
    # ------------------------------------------------------------------ the lifter
    LF + "lift.h": [(r"""    bool vertex_motion{};
    bool vertex_capture{};

""", r"""    bool vertex_motion{};
    bool vertex_capture{};
    // bbport (r62c_leaf-stage3-fix): the capture also stores the card UVs (MotionVectors::CaptureUv,
    // BB_RT_CARD_ALPHA on): capture_uv_stride bytes a vertex (12: u, v, the alpha factor; 16:
    // and another component of the factor's output, r62b), capture_uv_unset (a NaN's bits) for
    // a value the selector cannot name. The ring's address is the address block's last member.
    bool capture_uv{};
    u32 capture_uv_stride{};
    u32 capture_uv_unset{};

""")],
    LF + "bridge.cpp": [(r"""static_assert(CaptureParamsCapacity == Shader::MotionVectors::CaptureParamsCapacity);
""", r"""static_assert(CaptureParamsCapacity == Shader::MotionVectors::CaptureParamsCapacity);
// bbport (r62c_leaf-stage3-fix): the lifter's card UV store writes 3 or 4 floats a vertex
static_assert(Shader::MotionVectors::CaptureUvStride == 12 ||
              Shader::MotionVectors::CaptureUvStride == 16);
"""), (r"""        in.vertex_capture = (vs.motion_vectors & Shader::MotionVectors::VertexCapture) != 0;
    }
""", r"""        in.vertex_capture = (vs.motion_vectors & Shader::MotionVectors::VertexCapture) != 0;
        // bbport (r62c_leaf-stage3-fix): the card UVs, as the recompiler's EmitCardUvStore
        in.capture_uv =
            in.vertex_capture && (vs.motion_vectors & Shader::MotionVectors::CaptureUv) != 0;
        in.capture_uv_stride = Shader::MotionVectors::CaptureUvStride;
        in.capture_uv_unset = Shader::MotionVectors::CaptureUvUnset;
    }
""")],
    LF + "lift_stage.cpp": [(r"""        const bool both = in.vertex_motion && in.vertex_capture;
        const std::array<u32, 2> members{t_u64, t_u64};
        const std::array<u32, 4> both_members{t_u64, t_u64, t_u64, t_u64};
        const u32 block = both ? m.AddUniqueType(O(spv::Op::OpTypeStruct), both_members)
                               : m.AddUniqueType(O(spv::Op::OpTypeStruct), members);
        m.Decorate(block, u32(spv::Decoration::Block));
        m.MemberDecorate(block, 0, u32(spv::Decoration::Offset), 0);
        m.MemberDecorate(block, 1, u32(spv::Decoration::Offset), 8);
        if (both) {
            m.MemberDecorate(block, 2, u32(spv::Decoration::Offset), 16);
            m.MemberDecorate(block, 3, u32(spv::Decoration::Offset), 24);
        }
""", r"""        const bool both = in.vertex_motion && in.vertex_capture;
        const std::array<u32, 2> members{t_u64, t_u64};
        const std::array<u32, 4> both_members{t_u64, t_u64, t_u64, t_u64};
        // bbport (r62c_leaf-stage3-fix): with the card UVs one address more, the ring's, after
        // the others (as the recompiler's DefineMotionAddressBlock); without, as before
        const bool uv = in.vertex_capture && in.capture_uv;
        const std::array<u32, 5> uv_members{t_u64, t_u64, t_u64, t_u64, t_u64};
        const u32 block =
            uv ? m.AddUniqueType(O(spv::Op::OpTypeStruct),
                                 std::span<const u32>(uv_members.data(), both ? 5u : 3u))
            : both ? m.AddUniqueType(O(spv::Op::OpTypeStruct), both_members)
                   : m.AddUniqueType(O(spv::Op::OpTypeStruct), members);
        m.Decorate(block, u32(spv::Decoration::Block));
        m.MemberDecorate(block, 0, u32(spv::Decoration::Offset), 0);
        m.MemberDecorate(block, 1, u32(spv::Decoration::Offset), 8);
        if (both) {
            m.MemberDecorate(block, 2, u32(spv::Decoration::Offset), 16);
            m.MemberDecorate(block, 3, u32(spv::Decoration::Offset), 24);
        }
        if (uv) {
            m.MemberDecorate(block, both ? 4u : 2u, u32(spv::Decoration::Offset), both ? 32u : 16u);
        }
"""), (r"""        const u32 bits = Emit(O(spv::Op::OpBitcast), t_u32, Ty::U32, {Extract(t_f32, Ty::F32, position, i)});
        const u32 prev = Emit(O(spv::Op::OpAtomicExchange), t_u32, Ty::U32, {ptr, CU(u32(spv::Scope::Device)), CU(0), bits});
        nodes[m.NodeOf(prev)].effect = true;
    }
    EmitVoid(O(spv::Op::OpBranch), {store_merge});
    Open(store_merge);
}

void Lift_::FragmentMotion() {
""", r"""        const u32 bits = Emit(O(spv::Op::OpBitcast), t_u32, Ty::U32, {Extract(t_f32, Ty::F32, position, i)});
        const u32 prev = Emit(O(spv::Op::OpAtomicExchange), t_u32, Ty::U32, {ptr, CU(u32(spv::Scope::Device)), CU(0), bits});
        nodes[m.NodeOf(prev)].effect = true;
    }
    // bbport (r62c_leaf-stage3-fix): and the card UVs (CaptureUv, BB_RT_CARD_ALPHA on), as the
    // recompiler's EmitCardUvStore: where the param names a place in the ring (word 1, the ring
    // index + 1; 0: none) and its selector (word 7, Vulkan::PackCardSelector: bits 0-4 the uv
    // output, 5-6 and 7-8 its components, 9-13 the alpha factor's output, 14-15 its component,
    // 16 a factor at all, 31 set) is set, the two components of one output and the factor (1.0
    // without one) are stored at ring + (index - 1 + slot) * stride, and with a 16-byte stride
    // (r62b) another component of the factor's output: .y where the factor is .x, else .x
    // (MotionVectors::CaptureUvOther). An output this shader does not write reads as the unset
    // NaN, so the expand pass marks the triangle not finite, as with the recompiler's.
    if (in.capture_uv) {
        const u32 uv_word = Extract(t_u32, Ty::U32, params, 1);
        const u32 selector = Extract(t_u32, Ty::U32, offsets, 3);
        const u32 wanted = Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool,
                                {ICmp(O(spv::Op::OpINotEqual), uv_word, CU(0)),
                                 ICmp(O(spv::Op::OpINotEqual), IOp(O(spv::Op::OpBitwiseAnd), selector, CU(0x80000000u)), CU(0))});
        const u32 uv_label = m.NewId();
        const u32 uv_merge = m.NewId();
        EmitVoid(O(spv::Op::OpSelectionMerge), {uv_merge, 0}, 2);
        EmitVoid(O(spv::Op::OpBranchConditional), {wanted, uv_label, uv_merge});
        Open(uv_label);
        const auto field = [&](u32 offset, u32 count) {
            return Emit(O(spv::Op::OpBitFieldUExtract), t_u32, Ty::U32, {selector, CU(offset), CU(count)});
        };
        const auto dynamic = [&](u32 vec, u32 comp) {
            return Emit(O(spv::Op::OpVectorExtractDynamic), t_f32, Ty::F32, {vec, comp});
        };
        const u32 uv_out = field(0, 5);
        const u32 alpha_out = field(9, 5);
        const u32 alpha_comp = field(14, 2);
        const u32 has_alpha = ICmp(O(spv::Op::OpINotEqual), field(16, 1), CU(0));
        const u32 unset = m.Const(Ty::F32, t_f32, in.capture_uv_unset);
        u32 uv_vector = ComponentsF({unset, unset, unset, unset});
        u32 alpha_vector = uv_vector;
        for (u32 i = 0; i < u32(var_param_out.size()); ++i) {
            if (!var_param_out[i]) {
                continue;
            }
            const u32 loaded = Emit(O(spv::Op::OpLoad), t_v4f, Ty::V4F, {var_param_out[i]});
            uv_vector = Select(ICmp(O(spv::Op::OpIEqual), uv_out, CU(i)), loaded, uv_vector);
            alpha_vector = Select(ICmp(O(spv::Op::OpIEqual), alpha_out, CU(i)), loaded, alpha_vector);
        }
        std::array<u32, 4> values{dynamic(uv_vector, field(5, 2)), dynamic(uv_vector, field(7, 2)),
                                  Select(has_alpha, dynamic(alpha_vector, alpha_comp), CF(1.0f)), unset};
        const u32 count = in.capture_uv_stride >= 16 ? 4u : 3u;
        if (count == 4) {
            const u32 other_comp = Select(ICmp(O(spv::Op::OpIEqual), alpha_comp, CU(0)), CU(1), CU(0));
            values[3] = Select(has_alpha, dynamic(alpha_vector, other_comp), unset);
        }
        const u32 ring_index = IOp(O(spv::Op::OpIAdd), IOp(O(spv::Op::OpISub), uv_word, CU(1)), slot);
        const u32 ring_base = address(table(both ? 4u : 2u), ring_index, in.capture_uv_stride);
        const u32 ptr_float = PtrType(storage, t_f32);
        for (u32 k = 0; k < count; ++k) {
            const u32 ptr = Emit(O(spv::Op::OpConvertUToPtr), ptr_float, Ty::None, {iadd64(ring_base, c64(k * 4))});
            EmitVoid(O(spv::Op::OpStore), {ptr, values[k], aligned, 4}, 12);
        }
        EmitVoid(O(spv::Op::OpBranch), {uv_merge});
        Open(uv_merge);
    }
    EmitVoid(O(spv::Op::OpBranch), {store_merge});
    Open(store_merge);
}

void Lift_::FragmentMotion() {
""")],
    # ------------------------------------------------------------------ a comment that changed
    SR + "backend/spirv/emit_spirv_special.cpp": [(r"""// stores the same values, as the position store above does. This is the recompiler's capture:
// a capture vertex shader with CaptureUv is never replaced by the lifter's (CompileModule).
""", r"""// stores the same values, as the position store above does. This is the recompiler's capture,
// used only where the lifter declines one or is off (r62c_leaf-stage3-fix: the lifter's
// VertexCapture stores the same values; this one made broken BLAS input, r62d).
""")],
}

# Texts every patched file must hold (once), so a wrong replacement cannot pass check.
MUSTS = {
    P + "cutout_analysis.h": ["get the card UVs (MotionVectors::CaptureUv): CardAlphaOn() and its pixel shader discards"],
    P + "cutout_analysis_pass.cpp": ["return CardAlphaOn() && diag != 2 && discards;"],
    VK + "vk_pipeline_cache.cpp": ["static void NoteCardUvRecompiled(u64 pgm_hash, const std::string& why) {",
                                   "NoteCardUvRecompiled(info.pgm_hash, \"lifter off\");"],
    LF + "lift.h": ["bool capture_uv{};"],
    LF + "bridge.cpp": ["in.capture_uv_stride = Shader::MotionVectors::CaptureUvStride;"],
    LF + "lift_stage.cpp": ["const bool uv = in.vertex_capture && in.capture_uv;", "if (in.capture_uv) {",
                            "EmitVoid(O(spv::Op::OpStore), {ptr, values[k], aligned, 4}, 12);"],
    SR + "backend/spirv/emit_spirv_special.cpp": ["used only where the lifter declines one"],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def file_run(rel, mode):
    """One file's text after its edits in this mode (apply's for check), or (None, why)."""
    path = ROOT + rel
    if not os.path.isfile(path):
        return None, "no such file"
    raw = open(path, "rb").read()
    crlf, lf = raw.count(b"\r\n"), raw.count(b"\n")
    if crlf not in (0, lf):
        return None, "mixed line ends"
    nl = "\r\n" if crlf else "\n"
    t = raw.decode("utf-8")
    pairs = EDITS[rel]
    for old, new in (pairs if mode != "revert" else list(reversed(pairs))):
        a, b = (fix(old, nl), fix(new, nl)) if mode != "revert" else (fix(new, nl), fix(old, nl))
        n = t.count(a)
        if n != 1:
            return None, "anchor found %d times (want 1): %r" % (n, a[:100])
        t = t.replace(a, b)
    if mode != "revert":
        for needle in MUSTS.get(rel, []):
            if t.count(needle) != 1:
                return None, "patched text holds %r %d times" % (needle, t.count(needle))
    return t.encode("utf-8"), ""


def run(mode):
    out, whys = {}, []
    for rel in EDITS:
        t, why = file_run(rel, mode)
        if t is None:
            whys.append("%s%s: %s" % (ROOT, rel, why))
        else:
            out[rel] = t
    return (out, []) if not whys else (None, whys)


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r62c_leaf-stage3-fix.py check|apply|revert   (the tree: R62C_ROOT, else the "
              "current directory)")
        return 2
    if not os.path.isfile(ROOT + VK + "vk_pipeline_cache.cpp"):
        print("not a source tree: %s (set R62C_ROOT)" % ROOT)
        return 2
    out, whys = run("revert" if mode == "revert" else "apply")
    if out is None:
        if mode != "revert" and run("revert")[0] is not None:
            print("already applied in %s%s" % (ROOT, "" if mode == "check" else ": nothing written"))
            return 1
        if mode == "revert" and run("apply")[0] is not None:
            print("not applied in %s: nothing to revert" % ROOT)
            return 1
        print("neither applied nor clean in %s:" % ROOT)
        for w in whys:
            print("  " + w)
        return 1
    if mode == "check":
        print("anchors OK in %s (applies cleanly: %d files changed)" % (ROOT, len(EDITS)))
        return 0
    before = {rel: open(ROOT + rel, "rb").read() for rel in out}
    if mode == "apply":
        for rel, data in before.items():
            dst = os.path.join(BACKUP, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
    done = []
    try:
        for rel, data in out.items():
            with open(ROOT + rel + TMP, "wb") as f:
                f.write(data)
        for rel in out:
            os.replace(ROOT + rel + TMP, ROOT + rel)
            done.append(rel)
    except OSError as e:
        print("failed in %s (%s); putting back what was changed" % (ROOT, e))
        for rel in done:
            with open(ROOT + rel, "wb") as f:
                f.write(before[rel])
        for rel in out:
            if os.path.exists(ROOT + rel + TMP):
                os.remove(ROOT + rel + TMP)
        return 1
    print("%s in %s (%d files)" % ("applied" if mode == "apply" else "reverted", ROOT, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
