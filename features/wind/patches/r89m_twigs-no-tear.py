# r89m_twigs-no-tear: FEATURE fix of the tree twigs (BB_WIND_TWIGS_CAP, default 1, only with BB_WIND_TWIGS on) + TOOL part (the
# proof's yellow stain is dropped, the proof's own cap). On top of r89l_twigs-palette-move (build 58), r89k, r89j ... r86l (build 59).
#
# THE OWNER: "I think if the small branches on the trees moved slightly due to wind that would look great"; "The wave should just
# be very subtle"; foliage moves downwind, slowly unless the wind is strong; never at the cost of looks.
# THE FAULT (build 58, the lead's own look at _rd_tear.jpg): the offset now reaches the pixels, but in the x5 proof captures the
# bare tree is TORN: branch pieces float off as flat dark shards and crosses; the log said mean 9.77 cm, max 894.32 cm (real max
# 178.86 cm at gain 1).
#
# WHAT THE CODE SAYS (reading, not running; the suspects of the task, one by one):
#  1. NOT a per-vertex attribute, bone row or local frame: all three sway emitters (lift_stage.cpp VertexSway, the recompiler's
#     EmitVertexSway, BbWindSway::Displace) compute the weight from the vertex's CLIP position AFTER the palette transform (rx, rz,
#     wy are the inverse view-projection of it) and from the slot's keys, add the move in world space (Forward rows) and store it
#     back to the clip position. The weight is a smooth function of world position (smoothstep of the box radius x smoothstep of
#     the height in the mesh x the size factor): neighbouring vertices of one piece get the same weight up to that function's
#     slope. Nothing is added in bone-local space.
#  2. THE REAL FAULT IS THE SIZE AND THE SLOPE. The weight is gain x wr x wh x SizeFactor (h / 6 m, up to 7) and the offset
#     is weight x along (along is held to 0.4 m): 7 x 0.4 x ... = up to 2.8 m, 1.79 m measured at gain 1. wr rises from 0 at the
#     trunk to 1 over about half a box radius: so a branch piece out at the box's edge moves a metre or two while its trunk end
#     (wr 0) stays: the piece floats off its trunk and a triangle whose vertices sit on both sides of the slope is sheared apart.
#     A mesh holding several trees (a 58 m box was seen) has its centre line, its lowest point and so h and the size factor
#     meaningless for most of its vertices.
#
# FIX (needs BB_WIND_TWIGS on; BB_WIND_TWIGS_CAP=0 gives r89l's move back for a same-build A/B after a restart):
#  (a) A SOFT CAP of a tree word's weight w (TreeBit words only; bushes, hair, hanging things are untouched): w / (1 + |w| / cap),
#      cap 0.28 (BbWindSway::TwigCap). It is smooth, rises like w for a small w (0.05 gives 0.043) and never passes the cap; its slope is
#      never above 1 and falls to (cap / (cap + w))^2 at a large w: where r89l's weight was big (the tips of tall pieces) the move is flat,
#      so neighbouring vertices there move together and a branch bends, it does not split. The offset cannot be above
#      cap x (|(along, cross)| 0.427 m + the leaf flutter 0.113 m) = 15.1 cm at the strongest wind (MaxAlong), and it falls with the
#      wind because along does (less in a light wind). The cap is applied to the sway word's weight w (the sway and ripple moves)
#      and to the push rule's share (the twigs' extra term), in the lifter's shader, the recompiler's shader and the C++ twin
#      (BbWindSway::Displace, TwigIn::cap).
#  (b) A MESH WHOSE BOX IS LARGER THAN ONE TREE IS REFUSED (BbWindTwigs::OneTreeBox 30 m, reason 'box-many' in SmallWhy: after the
#      shape checks, never in the loose rule BB_WIND_TWIGS_SMALL=3): the candidate line says 'refused ... box-many', the refusal
#      counts are in the existing candidate report lines. (review: entry.loose is also set by BB_WIND_TWIGS_TREES and by
#      palette streams (WindTwigWord), so (b) does NOT act in the r89m jobs, which run TREES=1; the cap (a) is the fix there.)
#  (c) THE PROOF NO LONGER STAINS. The game's outputs of its tree shader are normals and UV pairs, the lit image never read the
#      yellow (build 58: no stain in any picture), so the lifter's tint block is removed. The proof is the x5 of the move under its OWN
#      cap (2 x the cap: at most about 30 cm), a large but smooth bend; the proof's counters (and the r89l offset line) stay.
#
# COST: with BB_WIND_TWIGS on, a sway shader has 5 more ALU operations a vertex (an abs, a multiply-add, a divide, a select, the
# TreeBit test is shared with the weight's); the tint's 2 loads and stores per output attribute are gone (proof only).
# OFF: with BB_WIND_TWIGS off (the default of the whole group) the emitters' twig_on is false and nothing of this is emitted: no
# shader, pipeline key or cache version differs (BinaryOffset is 0 then). With the twigs on, FixAdd 4000 and (cap on) CapAdd 8000 join
# the shader binary version, so no cached shader of build 58 is reused.
#
# SHARED LINES TOUCHED (the hang lane and the glass lane draft in parallel): lift_stage.cpp: two blocks right after the twigs' own proof
# multiplications (the lines that multiply w and share_used by ProofGain) and the twigs' tint block (removed); emit_spirv_special.cpp:
# the same two places; bbport_wind_sway.h: the constants after TwigHalfFloor, TwigIn::cap, and the two lines that make w and
# twig_share in Displace; vk_rasterizer_effects.cpp: one print block next to the FitOnceText call. No pick line, no hang line, no
# sway-word line.
#
# NOT TESTED in the game. Use: python -I -X utf8 r89m_twigs-no-tear.py check | apply | revert (root from R89M_ROOT, else <tree>).
# Files keep their line ends. Originals are kept in r89m_backup/ next to this script. No new file.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89m_backup")
ROOT = os.environ.get("R89M_ROOT") or "<tree>"
G = "engine/gpu/"
R = G + "shadps4/video_core/renderer_vulkan/"
SWAY = G + "shim/bbport_wind_sway.h"
TWIGS = G + "shim/bbport_wind_twigs.h"
LIFT = G + "shim/lifter/lift_stage.cpp"
EMIT = G + "shadps4/shader_recompiler/backend/spirv/emit_spirv_special.cpp"
EFFECTS = R + "vk_rasterizer_effects.cpp"
TEST = "engine/tests/test_wind_trees.cpp"
README = "README.md"

# ---------------------------------------------------------------- bbport_wind_sway.h
SW_CONST_OLD = "inline constexpr float TwigHalfFloor = 0.5f; ///< m\n"
SW_CONST_NEW = SW_CONST_OLD + '''/// bbport (r89m_twigs-no-tear): the soft cap of a tree word's weight w: w / (1 + |w| / cap). Smooth, about w for a small w, never above
/// cap, slope at most 1. TwigCap x (the largest along and cross 0.427 m + the largest leaf flutter 0.113 m) is the largest move
/// (15.1 cm at the strongest wind); the proof knob's x5 has TwigCapProofMul x the cap (at most about 30 cm). BbWindTwigs::CapOn().
inline constexpr float TwigCap = 0.28f, TwigCapProofMul = 2.0f;
static_assert(TwigCap > 0.0f && TwigCapProofMul >= 1.0f);

[[nodiscard]] inline float TwigSoftCap(float w, float cap = TwigCap) {
    return w / (1.0f + std::fabs(w) / cap);
}
'''

SW_IN_OLD = "    bool push = false;  ///< bbport (r89h_twigs-alive): BB_WIND_TWIGS_PUSH (TwigAlong for the twig's share)\n"
SW_IN_NEW = SW_IN_OLD + "    bool cap = false;   ///< bbport (r89m_twigs-no-tear): a tree-only word's weight and push share are soft capped (TwigSoftCap)\n"

SW_W_OLD = "    const float w = (wb_use + tau * lean * (wt_use - wb_use)) * ramp;\n"
SW_W_NEW = ("    float w = (wb_use + tau * lean * (wt_use - wb_use)) * ramp;\n"
            "    if (twig != nullptr && twig->cap && twig->tree_only) { // bbport (r89m_twigs-no-tear): the soft cap\n"
            "        w = TwigSoftCap(w);\n"
            "    }\n")

SW_SHARE_OLD = "        const float twig_share = tau * lean * wt_use * ramp;\n"
SW_SHARE_NEW = ("        float twig_share = tau * lean * wt_use * ramp;\n"
                "        if (twig->cap && twig->tree_only) { // bbport (r89m_twigs-no-tear): the same cap\n"
                "            twig_share = TwigSoftCap(twig_share);\n"
                "        }\n")

# ---------------------------------------------------------------- bbport_wind_twigs.h
TW_OFFSET_OLD = "inline constexpr std::uint32_t OffsetAdd = 400;\n"
TW_OFFSET_NEW = TW_OFFSET_OLD + (
    "/// bbport (r89m_twigs-no-tear): added to the shader binary version with the twigs on (the proof's tint is gone: the lifter's shader\n"
    "/// differs), and CapAdd as well with the cap on (BB_WIND_TWIGS_CAP, the sway shaders carry the soft cap).\n"
    "inline constexpr std::uint32_t FixAdd = 4000, CapAdd = 8000;\n")

TW_PROOF_OLD = "[[nodiscard]] inline bool ProofOn() {\n    return KnobOnce().on && KnobOnce().proof;\n}\n"
TW_PROOF_NEW = TW_PROOF_OLD + '''
/// bbport (r89m_twigs-no-tear): whether a tree word's weight is soft capped (BbWindSway::TwigSoftCap): BB_WIND_TWIGS_CAP (read once,
/// default 1; 0 gives r89l's move back) with the twigs on. Read once with the shaders (BinaryOffset).
[[nodiscard]] inline bool CapOn() {
    static const bool wanted = W::ParseNumber(std::getenv("BB_WIND_TWIGS_CAP"), 1.0f) >= 0.5f;
    return wanted && KnobOnce().on;
}
'''

TW_BIN_OLD = ("                      (ProofOn() ? ProofAdd + OffsetAdd : 0u) + (PushOn() ? PushAdd : 0u) // bbport (r89h, r89l)\n"
              "                : 0u;\n")
TW_BIN_NEW = ("                      (ProofOn() ? ProofAdd + OffsetAdd : 0u) + (PushOn() ? PushAdd : 0u) + // bbport (r89h, r89l)\n"
              "                      FixAdd + (CapOn() ? CapAdd : 0u)                                      // bbport (r89m)\n"
              "                : 0u;\n")

TW_KNOWN_OLD = ("            if (version == sway + a + b || version == hang + a + b || version == sway + a + b + OffsetAdd ||\n"
                "                version == hang + a + b + OffsetAdd) {\n"
                "                return true;\n"
                "            }\n")
TW_KNOWN_NEW = ("            // bbport (r89m_twigs-no-tear): and FixAdd, FixAdd + CapAdd (the twigs' shaders since r89m)\n"
                "            const std::uint32_t fixes[3] = {0u, FixAdd, FixAdd + CapAdd}; // (the fixes only with BinaryAdd: m above 0)\n"
                "            for (std::uint32_t ci = 0; ci < (m == 0 ? 1u : 3u); ++ci) {\n"
                "                const std::uint32_t c = fixes[ci];\n"
                "                if (version == sway + a + b + c || version == hang + a + b + c ||\n"
                "                    version == sway + a + b + c + OffsetAdd || version == hang + a + b + c + OffsetAdd) {\n"
                "                    return true;\n"
                "                }\n"
                "            }\n")

TW_BOX_OLD = "inline constexpr float SmallAspectLo = 0.20f, SmallAspectHi = 1.8f, SmallThin = 0.30f;\n"
TW_BOX_NEW = TW_BOX_OLD + (
    "/// bbport (r89m_twigs-no-tear): a mesh whose larger horizontal box side is over this is more than one tree: refused ('box-many').\n"
    "inline constexpr float OneTreeBox = 30.0f;\n")

TW_WHY_OLD = "    if (wmin < SmallThin * wmax) {\n        return \"thin\";\n    }\n    return nullptr;\n"
TW_WHY_NEW = ("    if (wmin < SmallThin * wmax) {\n        return \"thin\";\n    }\n"
              "    if (wmax > OneTreeBox) { // bbport (r89m_twigs-no-tear): a box of several trees (the shape rules above passed)\n"
              "        return \"box-many\";\n"
              "    }\n"
              "    return nullptr;\n")

TW_PROOFTXT_OLD = ('                  "Wind twigs (r89g, BB_WIND_TWIGS_PROOF=1, TOOL): a tree word\'s move x%.0f; the vertex outputs of a "\n'
                   '                  "vertex with a twig weight pulled toward yellow by it (lifter shaders; the game\'s outputs are "\n'
                   '                  "normals and UV pairs, so a stained twig, not a clean yellow); %u counters a mesh slot (%u bytes of "\n')
TW_PROOFTXT_NEW = ('                  "Wind twigs (r89g, BB_WIND_TWIGS_PROOF=1, TOOL): a tree word\'s move x%.0f (its weight then soft capped "\n'
                   '                  "at twice the cap of r89m; the yellow tint is gone: the game\'s outputs are normals and UV pairs); "\n'
                   '                  "%u counters a mesh slot (%u bytes of "\n')

TW_LINE_OLD = '"mean %.2f cm, max %.2f cm (with the proof\'s x%.0f; real mean %.2f cm, max %.2f cm); G-buffer vertex runs "\n'
TW_LINE_NEW = '"mean %.2f cm, max %.2f cm (proof x%.0f, weight soft capped since r89m, so the columns divided by x5 read low: %.2f cm, %.2f cm); G-buffer vertex runs "\n'

TW_CAPTXT_ANCHOR = "/// bbport (r89h_twigs-alive, TOOL): what the change counters say of the push's time motion (a string literal).\n"
TW_CAPTXT_NEW = '''/// bbport (r89m_twigs-no-tear): the once line of the cap (under 560 characters).
inline void CapOnceText(char* out, std::size_t size) {
    const double real = static_cast<double>(W::TwigCap) *
                        (std::hypot(static_cast<double>(W::MaxAlong), static_cast<double>(W::MaxCross)) +
                         1.4143 * static_cast<double>(W::MaxLeaf)) * 100.0;
    if (CapOn()) {
        std::snprintf(out, size,
                      "Wind twigs cap (r89m, BB_WIND_TWIGS_CAP=1): a tree word's weight w is soft capped at %.2f (w / (1 + w / cap): "
                      "smooth, never above the cap), so no vertex of a tree moves more than about %.0f cm at the strongest wind "
                      "(%.0f cm in the proof's x%.0f), less in a lighter wind, and neighbouring vertices move together; "
                      "a strictly judged mesh whose box is over %.0f m is refused (box-many; not with TREES, palette or SMALL=3)",
                      static_cast<double>(W::TwigCap), real, real * static_cast<double>(W::TwigCapProofMul),
                      static_cast<double>(ProofGain), static_cast<double>(OneTreeBox));
    } else {
        std::snprintf(out, size,
                      "Wind twigs cap (r89m, BB_WIND_TWIGS_CAP=0): off, the weight of a tree word is not capped (r89l's move); "
                      "a strictly judged mesh whose box is over %.0f m is still refused (box-many; not with TREES, palette or SMALL=3)",
                      static_cast<double>(OneTreeBox));
    }
}

''' + TW_CAPTXT_ANCHOR

# ---------------------------------------------------------------- lift_stage.cpp
LF_W_OLD = "                   FMul(w, CF(BbWindTwigs::ProofGain)), w);\n    }\n"
LF_W_NEW = LF_W_OLD + '''    // bbport (r89m_twigs-no-tear): the soft cap of a tree word's weight (BbWindSway::TwigSoftCap: w / (1 + |w| / cap), the proof's x5
    // has twice the cap), here and on the push rule's share below; bushes and other words keep their weight. Off: nothing emitted.
    const bool twig_cap = twig_on && BbWindTwigs::CapOn();
    const auto soft_tree = [&](u32 x) {
        const float cap = BbWindTwigs::ProofOn() ? W::TwigCap * W::TwigCapProofMul : W::TwigCap;
        const u32 denom = FAdd(CF(1.0f), FMul(abs_f(x), CF(1.0f / cap)));
        const u32 capped = Emit(O(spv::Op::OpFDiv), t_f32, Ty::F32, {x, denom});
        return Select(ICmp(O(spv::Op::OpINotEqual), IOp(O(spv::Op::OpBitwiseAnd), word, CU(BbWindTwigs::TreeBit)), CU(0)), capped, x);
    };
    if (twig_cap) {
        w = soft_tree(w);
    }
'''

LF_S_OLD = "                                FMul(push_share, CF(BbWindTwigs::ProofGain)), push_share);\n        }\n"
LF_S_NEW = LF_S_OLD + ("        if (twig_cap) { // bbport (r89m_twigs-no-tear): the same cap on the push rule's share\n"
                       "            share_used = soft_tree(share_used);\n"
                       "        }\n")

LF_TINT_OLD = '''        // the tint: every output attribute of a vertex with a twig weight toward (1, 1, 0) by weight / gain
        const u32 vis = clamp_f(Emit(O(spv::Op::OpFDiv), t_f32, Ty::F32, {wt_use, Ext(GLSLstd450FMax, t_f32, Ty::F32, {gain, CF(0.001f)})}), zero, CF(1.0f));
        for (u32 p = 0; p < u32(var_param_out.size()); ++p) {
            if (!var_param_out[p]) {
                continue;
            }
            const u32 attribute = Emit(O(spv::Op::OpLoad), t_v4f, Ty::V4F, {var_param_out[p]});
            const auto toward = [&](u32 index, float target) {
                const u32 c = Extract(t_f32, Ty::F32, attribute, index);
                return FAdd(c, FMul(FSub(CF(target), c), vis));
            };
            EmitVoid(O(spv::Op::OpStore), {var_param_out[p], ComponentsF({toward(0, 1.0f), toward(1, 1.0f), toward(2, 0.0f), Extract(t_f32, Ty::F32, attribute, 3)})});
        }
'''
LF_TINT_NEW = "        // bbport (r89m_twigs-no-tear): the proof's yellow tint of the vertex outputs is gone (the game's tree shader outputs are normals and UV pairs)\n"

# ---------------------------------------------------------------- emit_spirv_special.cpp
EM_W_OLD = "                         mul(w, f(BbWindTwigs::ProofGain)), w);\n    }\n"
EM_W_NEW = EM_W_OLD + '''    // bbport (r89m_twigs-no-tear): the soft cap of a tree word's weight (BbWindSway::TwigSoftCap: w / (1 + |w| / cap), the proof's x5 has
    // twice the cap), here and on the push rule's share below; as the lifter's VertexSway. Off: nothing emitted.
    const bool twig_cap = twig_on && BbWindTwigs::CapOn();
    const auto soft_tree = [&](Id x) {
        const float cap = BbWindTwigs::ProofOn() ? W::TwigCap * W::TwigCapProofMul : W::TwigCap;
        const Id capped = ctx.OpFDiv(f32_type, x, add(f(1.0f), mul(ctx.OpFAbs(f32_type, x), f(1.0f / cap))));
        return ctx.OpSelect(f32_type,
                            ctx.OpINotEqual(bool_type,
                                            ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(BbWindTwigs::TreeBit)),
                                            ctx.u32_zero_value),
                            capped, x);
    };
    if (twig_cap) {
        w = soft_tree(w);
    }
'''

EM_S_OLD = "                mul(twig_share, f(BbWindTwigs::ProofGain)), twig_share);\n        }\n"
EM_S_NEW = EM_S_OLD + ("        if (twig_cap) { // bbport (r89m_twigs-no-tear): the same cap on the push rule's share\n"
                       "            twig_share = soft_tree(twig_share);\n"
                       "        }\n")

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
EF_OLD = ("            BbWindTwigs::FitOnceText(BbWindTwigs::KnobOnce(), fit_once, sizeof(fit_once));\n"
          "            BbReport::Printf(\"%s\\n\", fit_once);\n")
EF_NEW = EF_OLD + ("            BbWindTwigs::CapOnceText(fit_once, sizeof(fit_once)); // bbport (r89m_twigs-no-tear)\n"
                   "            BbReport::Printf(\"%s\\n\", fit_once);\n")

# ---------------------------------------------------------------- tests/test_wind_trees.cpp
TE_OLD = ("        Expect(std::strstr(once, \"Wind twigs offset\") != nullptr && std::strlen(once) < 700, \"the once line\");\n"
          "    }\n")
TE_NEW = TE_OLD + '''
    // bbport (r89m_twigs-no-tear): the soft cap, the largest move, the one-tree box, the shader version.
    {
        namespace T = BbWindTwigs;
        namespace S = BbWindSway;
        Expect(S::TwigSoftCap(0.0f) == 0.0f && S::TwigSoftCap(-0.0f) == 0.0f, "the cap leaves 0 at 0");
        Expect(std::fabs(S::TwigSoftCap(0.05f) - 0.05f / (1.0f + 0.05f / S::TwigCap)) < 1.0e-7f && S::TwigSoftCap(0.05f) > 0.04f,
               "a small weight keeps most of itself");
        bool monotone = true, under_cap = true, slow = true, under_self = true;
        float previous = 0.0f;
        for (int i = 1; i <= 4000; ++i) {
            const float x = 0.005f * static_cast<float>(i);
            const float y = S::TwigSoftCap(x);
            monotone = monotone && y >= previous;
            under_cap = under_cap && y < S::TwigCap + 1.0e-6f;
            under_self = under_self && y <= x + 1.0e-6f;
            slow = slow && (y - previous) <= 0.005f + 1.0e-6f; // slope at most 1
            previous = y;
        }
        Expect(monotone && under_cap && under_self && slow, "the cap is monotone, below the cap and below w, slope at most 1");
        Expect(S::TwigSoftCap(4.5f) > 0.25f && S::TwigSoftCap(4.5f) < S::TwigCap && S::TwigSoftCap(1.0e9f) < S::TwigCap + 1.0e-6f,
               "r89l's weight of 4.5 now gives under the cap");
        const double most = static_cast<double>(S::TwigCap) *
                            (std::hypot(static_cast<double>(S::MaxAlong), static_cast<double>(S::MaxCross)) +
                             1.4143 * static_cast<double>(S::MaxLeaf));
        Expect(most > 0.10 && most < 0.16, "the largest move at the strongest wind is 10 to 16 cm");
        Expect(most * static_cast<double>(S::TwigCapProofMul) < 0.33, "the proof's largest move stays under 33 cm");
        S::TwigIn in;
        Expect(!in.cap, "the C++ twin's cap is off in a default TwigIn");

        const auto meas = [](float base, float crown, float x0, float x1, float z0, float z1) {
            T::Measure m;
            m.base = base;
            m.crown = crown;
            m.x_lo = x0;
            m.x_hi = x1;
            m.z_lo = z0;
            m.z_hi = z1;
            m.ok = true;
            return m;
        };
        const char* const many = T::SmallWhy(meas(0, 20, 0, 35, 0, 20), 0.0f, 1, false);
        Expect(many != nullptr && std::strcmp(many, "box-many") == 0, "a 35 x 20 m box of a 20 m mesh is several trees");
        Expect(T::SmallWhy(meas(0, 20, 0, 28, 0, 20), 0.0f, 1, false) == nullptr, "a 28 x 20 m box of a 20 m mesh is one tree");
        Expect(T::SmallWhy(meas(0, 20, 0, 35, 0, 20), 0.0f, 1, true) == nullptr, "the loose rule keeps no box rule");
        const char* const wide = T::SmallWhy(meas(0, 12, 0, 40, 0, 20), 0.0f, 1, false);
        Expect(wide != nullptr && std::strcmp(wide, "wide") == 0, "the shape reasons still come first");
        Expect(T::OneTreeBox == 30.0f && T::FixAdd == 4000u && T::CapAdd == 8000u, "the constants");
        Expect(T::KnownVersion(2011 + T::FixAdd, 11, 21, 1000) && T::KnownVersion(2011 + T::FixAdd + T::CapAdd, 11, 21, 1000) &&
                   T::KnownVersion(2011 + 20 + T::OffsetAdd + T::FixAdd + T::CapAdd, 11, 21, 1000) &&
                   T::KnownVersion(2011 + 20 + T::OffsetAdd, 11, 21, 1000) && !T::KnownVersion(2011 + 7, 11, 21, 1000) &&
                   !T::KnownVersion(2011 + T::CapAdd, 11, 21, 1000),
               "the shader versions with the fix and the cap are known, a stray one is not");
        char cap_text[640];
        T::CapOnceText(cap_text, sizeof(cap_text));
        Expect(std::strstr(cap_text, "Wind twigs cap") != nullptr && std::strstr(cap_text, "BB_WIND_TWIGS_CAP=") != nullptr && std::strlen(cap_text) < 560 &&
                   std::strstr(cap_text, "box-many") != nullptr,
               "the cap's once line");
    }
'''

# ---------------------------------------------------------------- README
RM_ANCHOR = "| `BB_WIND_TWIGS_TREES_GAIN` |"
RM_NEW = ("| `BB_WIND_TWIGS_CAP` | Soft cap of a tree's twig weight (r89m; needs `BB_WIND_TWIGS` above 0): `1` (default) the weight w of a tree-only draw (sway word with the tree bit) is "
          "`w / (1 + w / 0.28)`: smooth, never above 0.28, slope at most 1, so no vertex of a tree moves more than about 15 cm at the strongest wind (`BB_WIND_SPEED=4`: "
          "the big weights of tall pieces, up to 1.8 m, tore the bare trees of build 58 apart: branch pieces floated off their trunk) and less in a lighter wind, and "
          "neighbouring vertices move together; applied to the weight and to the push rule's share in the lifter's shader, the recompiler's and the C++ twin; bushes, hair "
          "and hanging things keep their weight. Also: a mesh whose box is over 30 m is refused as several trees ('box-many' in the candidate line, not with "
          "`BB_WIND_TWIGS_SMALL=3`, `BB_WIND_TWIGS_TREES=1` or a palette stream: those are judged loose). `0` r89l's move back. Read once with the shaders (the shader version differs: no stale cache). Off with the twigs: nothing is emitted | `1` |\n"
          + RM_ANCHOR)

RM_PROOF_OLD = ("the vertex outputs of every vertex with a twig weight are pulled toward yellow by the weight (the game's own outputs of the tree shader are normals "
                "and UV pairs, so the tint shows as a stained twig, not a clean yellow), and the lifter's shader counts")
RM_PROOF_NEW = ("its weight is then soft capped at twice the cap of `BB_WIND_TWIGS_CAP` (at most about 30 cm; the yellow tint of r89g is gone since r89m: the game's tree shader outputs "
                "are normals and UV pairs and the stain never showed), and the lifter's shader counts")

EDITS = {
    SWAY: [(SW_CONST_OLD, SW_CONST_NEW), (SW_IN_OLD, SW_IN_NEW), (SW_W_OLD, SW_W_NEW), (SW_SHARE_OLD, SW_SHARE_NEW)],
    TWIGS: [(TW_OFFSET_OLD, TW_OFFSET_NEW), (TW_PROOF_OLD, TW_PROOF_NEW), (TW_BIN_OLD, TW_BIN_NEW), (TW_KNOWN_OLD, TW_KNOWN_NEW),
            (TW_BOX_OLD, TW_BOX_NEW), (TW_WHY_OLD, TW_WHY_NEW), (TW_PROOFTXT_OLD, TW_PROOFTXT_NEW), (TW_LINE_OLD, TW_LINE_NEW),
            (TW_CAPTXT_ANCHOR, TW_CAPTXT_NEW)],
    LIFT: [(LF_W_OLD, LF_W_NEW), (LF_S_OLD, LF_S_NEW), (LF_TINT_OLD, LF_TINT_NEW)],
    EMIT: [(EM_W_OLD, EM_W_NEW), (EM_S_OLD, EM_S_NEW)],
    EFFECTS: [(EF_OLD, EF_NEW)],
    TEST: [(TE_OLD, TE_NEW)],
    README: [(RM_ANCHOR, RM_NEW), (RM_PROOF_OLD, RM_PROOF_NEW)],
}

CHECKS = {
    SWAY: [("inline float TwigSoftCap(", 1), ("bool cap = false;", 1), ("w = TwigSoftCap(w);", 1), ("twig_share = TwigSoftCap(twig_share);", 1)],
    TWIGS: [("inline bool CapOn()", 1), ("inline void CapOnceText(", 1), ("return \"box-many\";", 1), ("FixAdd + (CapOn() ? CapAdd : 0u)", 1),
            ("inline constexpr float OneTreeBox = 30.0f;", 1), ("inline constexpr std::uint32_t FixAdd = 4000, CapAdd = 8000;", 1)],
    LIFT: [("w = soft_tree(w);", 1), ("share_used = soft_tree(share_used);", 1), ("toward(0, 1.0f), toward(1, 1.0f), toward(2, 0.0f)", 0),
           ("const u32 vis = ", 0)],
    EMIT: [("w = soft_tree(w);", 1), ("twig_share = soft_tree(twig_share);", 1)],
    EFFECTS: [("BbWindTwigs::CapOnceText(fit_once, sizeof(fit_once));", 1)],
    TEST: [("S::TwigSoftCap(0.0f)", 1), ("wind-trees-test: ok", 1)],
    README: [("| `BB_WIND_TWIGS_CAP` |", 1), ("| `BB_WIND_TWIGS_TREES_GAIN` |", 1), ("pulled toward yellow by the weight", 0)],
}

# Numbers written twice: the header's constants and the README text.
TIES = [("inline constexpr float TwigCap = 0.28f, TwigCapProofMul = 2.0f;", "| `BB_WIND_TWIGS_CAP`", "`w / (1 + w / 0.28)`"),
        ("inline constexpr float OneTreeBox = 30.0f;", "| `BB_WIND_TWIGS_CAP`", "over 30 m")]


def ties_src(texts, const):
    for path in (SWAY, TWIGS):
        if texts[path].count(const) == 1:
            return 1
    return 0


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, s, texts[path].count(s), n))
    for const, row_start, value in TIES:
        rows = "\n".join(l for l in texts[README].split("\n") if l.startswith(row_start))
        if ties_src(texts, const) != 1 or value not in rows:
            raise SystemExit("tie check: %r against the README row %r (%r)" % (const, row_start, value))
    for path, edits in EDITS.items():
        for old, new in edits:
            if "\r" in new:
                raise SystemExit("new text must have LF only in the script")
    for path, new in [(p, n) for p, es in EDITS.items() if p != README for _, n in es]:
        if not all(ord(c) < 128 for c in new):
            raise SystemExit("%s: new text must be ASCII" % path)
        if any(x in new for x in ("C:/", "G:/", "<user>", "Temp/claude")):
            raise SystemExit("a local path in the patch's text")
    allnew = "".join(n for p, es in EDITS.items() if p != README for _, n in es)
    for bad in ("float far ", "float far;", " far =", " far;", ".far,", ".far)", " near =", "float near", " small =", "float small",
                "float small;"):
        if bad in allnew.replace("bool small = false", "").replace("entry.small = true", ""):
            raise SystemExit("the name %r is a macro on some Windows headers" % bad)
    for path, edits in EDITS.items():
        if path == README:
            continue
        for old, new in edits:
            if new.count("{") - old.count("{") != new.count("}") - old.count("}") or \
               new.count("(") - old.count("(") != new.count(")") - old.count(")"):
                raise SystemExit("%s: an edit does not balance its braces or parentheses: %r" % (path, new.split("\n")[0][:70]))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R89M_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = todo = 0
        for old, new in edits:
            if cur.count(new) == 1:
                done += 1
            elif cur.count(old) == 1 and cur.count(new) == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once): %r"
                                 % (path, cur.count(old), old.split("\n")[0][:80]))
        if done == len(edits):
            state = "applied"
        elif todo == len(edits):
            state = "clean"
        else:
            raise SystemExit("%s: %d of %d edits applied" % (path, done, len(edits)))
        plan.append((path, edits, raw, eol, cur, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, edits, raw, eol, cur, _ in plan:
            for old, new in edits:
                if cur.count(old) != 1:
                    raise SystemExit("REFUSED %s: anchor not once after the edits before it: %r"
                                     % (path, old.split("\n")[0][:80]))
                cur = cur.replace(old, new)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, 0 new; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, edits, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, edits, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r89mtmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, edits, raw, eol, cur, _ in plan:
        for old, new in reversed(edits):
            if cur.count(new) != 1:
                raise SystemExit("%s: an edit's text is not there once; nothing written" % path)
            cur = cur.replace(new, old)
        for old, new in edits:
            if cur.count(old) != 1 or cur.count(new) != 0:
                raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, edits, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r89mtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
