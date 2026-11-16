# r89n_twigs-visible: FEATURE fix of the tree twigs' amount (BB_WIND_TWIGS_CAP=1 path only, so only with BB_WIND_TWIGS on and
# BB_WIND_TWIGS_TREES / the tree words). On top of r89m_twigs-no-tear (build 60..65) and r89l, r89k ... r86l. No new file, no new knob.
#
# THE OWNER (2026-11-16 06:40): "I don't notice any movement with the twigs in the video." Earlier: "I think if the small branches on
# the trees moved slightly due to wind that would look great"; "The sway on the trees either should be removed or very subtle unless
# it's strong wind. The foliage moving should not wave but move in the direction of the wind and it should be not as fast unless the
# wind is really blowing"; "The wave should just be very subtle".
# THE FAULT (4K clip twigs_b60.mp4, graveyard, looking up, 4 m/s and 1.5 m/s): r89m's soft cap (w / (1 + |w| / 0.28), at most 15 cm in
# theory) held the move down for good: the tree words' raw weight is gain 0.3 x BB_WIND_TWIGS x the mesh rule x the size factor x
# the trees route's ramp byte x BB_WIND_TWIGS_TREES_GAIN 0.5, about 0.05 to 0.3 at a limb piece; the cap turned that into 0.04 to 0.14,
# and the push rule's along move is bend D (0.12 m at 4 m/s) x (TwigRest 0.05 + TwigPush 2.5 F^2): 0.6 cm steady, 31 cm at the crest of
# a full front. So a typical tip moved 0.1 x 31 cm = 3 cm at a gust crest and 0.1 x 0.6 cm = 0.06 cm between gusts: under 2 px at
# 10 m in 4K, and the proof's mean 1-2 cm was mostly the x5.
#
# FIX (three constants; the shaders get the same arithmetic, operation for operation; the knob BB_WIND_TWIGS stays the gain and stays
# LIVE (set:BB_WIND_TWIGS=0.5 / 1 / 2 in a slot job, no restart), its default stays 1 and now gives a visible move):
#  (a) BbWindSway::TwigBoost 6 (new): the capped weight is y = w / (1 / TwigBoost + |w| / TwigCap) in place of w / (1 + |w| / TwigCap):
#      y is about 6 w for a small w and tends to TwigCap; the slope at 0 is 6 (was 1), the slope falls with w and the largest slope
#      anywhere is 6, so a branch still bends as one (the soft cap is kept: nothing can exceed TwigCap and the weight is smooth).
#      Same operation count in the shaders (the constant 1.0 of the denominator is 1 / TwigBoost): no new ALU operation.
#  (b) TwigCap 0.28 -> 1.3: at the strongest wind a tip's move is y x (bend 0.12 m x (TwigRest + TwigPush) = 0.324 m at a full front) =
#      up to 42 cm; typical limb pieces (raw w 0.05 / 0.15 / 0.3 / 0.6) give y 0.24 / 0.53 / 0.76 / 0.95 and so 8 / 17 / 25 / 31 cm at
#      a gust crest at 4 m/s (BB_WIND_SWAY 1); the hard bound by the limits (MaxAlong 0.4, MaxCross 0.15, MaxLeaf 0.08) is 70 cm.
#      TwigCapProofMul 2 -> 1 (the proof knob's x5 would otherwise reach 1 m; the proof is a TOOL and keeps its x5 under the same cap).
#  (c) TwigRest 0.05 -> 0.2: the steady lean between gusts (a quarter of the lean of a front's crest instead of a twentieth): about 2 cm
#      at 4 m/s for y 0.9; the gust fronts push to 2.7 D and the twigs spring back, mean of the moving part about 10 cm at 4 m/s.
#  AT 1.5 m/s the bend is 0.12 x (1.5 / 4)^2 = 1.7 cm: a gust crest at y 0.53 gives 2.4 cm, the steady part 0.2 cm: almost still, as the
#  owner wants. TRUNKS AND THICK LIMBS stay still: the mesh rule's weight (r89d) is 0 near the box's centre line and low in the mesh.
#  NO TEAR: y is smooth in w, w smooth in world position (r89m's reading), the slope of y is at most 6 and where w is large (above 0.5)
#  the slope is under 1.4 (flat), so neighbouring vertices move together; the move is held by TwigCap 1.3 x the limits. The tear of
#  build 58 was 1.8 m of move; this is at most 42 cm (70 cm hard bound). NOT verified in the game: how the raw weight of the real limb
#  pieces reads (the 0.05-0.6 above is the formula's, not measured): the live knob BB_WIND_TWIGS (0.5 / 1 / 2 / 4) is there to scale it.
#
# COST: none new. The shaders (lifter VertexSway, recompiler EmitVertexSway) change two constants (the denominator's 1.0 and the
# TwigRest of the push rule); the C++ twin is the same formula. OFF: the twigs off (default of the whole group; BB_WIND_TWIGS_TREES
# default 0 too) emit nothing: BinaryOffset is 0 then and no shader, pipeline key or cache version differs; this patch adds the
# BoostAdd 16000 to the shader binary version with the twigs on (any cap setting, since the TwigRest differs): no cached shader of
# build 65 is reused. BB_WIND_TWIGS_CAP=0 keeps the uncapped weight (no boost; r89l's move) for an A/B after a restart.
#
# SHARED LINES TOUCHED: bbport_wind_sway.h (TwigCap line, TwigSoftCap's return line, TwigRest line); bbport_wind_twigs.h (FixAdd line,
# BinaryOffset line, KnownVersion's two lines, CapOnceText); lift_stage.cpp and emit_spirv_special.cpp: the one denominator line each
# of r89m's soft_tree lambda. No pick line, no hang line, no sway-word line, no vk_rasterizer file.
#
# NOT TESTED in the game. Use: python -I -X utf8 r89n_twigs-visible.py check | apply | revert (root from R89N_ROOT, else <tree>).
# Files keep their line ends. Originals are kept in r89n_backup/ next to this script. No new file.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89n_backup")
ROOT = os.environ.get("R89N_ROOT") or "<tree>"
G = "engine/gpu/"
SWAY = G + "shim/bbport_wind_sway.h"
TWIGS = G + "shim/bbport_wind_twigs.h"
LIFT = G + "shim/lifter/lift_stage.cpp"
EMIT = G + "shadps4/shader_recompiler/backend/spirv/emit_spirv_special.cpp"
TEST = "engine/tests/test_wind_trees.cpp"
README = "README.md"

# ---------------------------------------------------------------- bbport_wind_sway.h
SW_CONST_OLD = ("inline constexpr float TwigCap = 0.28f, TwigCapProofMul = 2.0f;\n"
                "static_assert(TwigCap > 0.0f && TwigCapProofMul >= 1.0f);\n")
SW_CONST_NEW = ('''/// bbport (r89n_twigs-visible): r89m's cap kept the twigs under 3 cm. The weight is now boosted by TwigBoost and capped at TwigCap:
/// TwigSoftCap(w) = w / (1 / TwigBoost + |w| / TwigCap): about TwigBoost x w for a small w, tending to TwigCap, slope at most TwigBoost.
/// A limb piece's raw weight 0.05 / 0.15 / 0.3 / 0.6 gives 0.24 / 0.53 / 0.76 / 0.95, and with the push rule's gust crest (D 0.12 m at
/// 4 m/s x (TwigRest + TwigPush) = 0.324 m) 8 / 17 / 25 / 31 cm; at most TwigCap x 0.324 = 42 cm (70 cm by the limits' bound).
inline constexpr float TwigCap = 1.3f, TwigBoost = 6.0f, TwigCapProofMul = 1.0f;
static_assert(TwigCap > 0.0f && TwigBoost >= 1.0f && TwigCapProofMul >= 1.0f);
''')

SW_RET_OLD = "    return w / (1.0f + std::fabs(w) / cap);\n"
SW_RET_NEW = "    return w / (1.0f / TwigBoost + std::fabs(w) / cap); // bbport (r89n_twigs-visible): boosted\n"

SW_REST_OLD = "inline constexpr float TwigRest = 0.05f, TwigPush = 2.5f, TwigFlutter = 0.5f;\n"
SW_REST_NEW = ("// bbport (r89n_twigs-visible): TwigRest 0.05 -> 0.2 (the steady lean between gusts: a twig's lean was 0.6 cm at 4 m/s, invisible)\n"
               "inline constexpr float TwigRest = 0.2f, TwigPush = 2.5f, TwigFlutter = 0.5f;\n")

# ---------------------------------------------------------------- bbport_wind_twigs.h
TW_FIX_OLD = "inline constexpr std::uint32_t FixAdd = 4000, CapAdd = 8000;\n"
TW_FIX_NEW = ("/// bbport (r89n_twigs-visible): BoostAdd is added with the twigs on, with the cap on or off (the shaders' boost, TwigCap and\n"
              "/// TwigRest differ from r89m's): no cached shader of build 65 is reused.\n"
              "inline constexpr std::uint32_t FixAdd = 4000, CapAdd = 8000, BoostAdd = 16000;\n")

TW_BIN_OLD = "FixAdd + (CapOn() ? CapAdd : 0u)"
TW_BIN_NEW = "FixAdd + BoostAdd + (CapOn() ? CapAdd : 0u)"

TW_KNOWN_OLD = ("            const std::uint32_t fixes[3] = {0u, FixAdd, FixAdd + CapAdd}; // (the fixes only with BinaryAdd: m above 0)\n"
                "            for (std::uint32_t ci = 0; ci < (m == 0 ? 1u : 3u); ++ci) {\n")
TW_KNOWN_NEW = ("            // bbport (r89n_twigs-visible): and FixAdd + BoostAdd, FixAdd + CapAdd + BoostAdd (the twigs' shaders since r89n)\n"
                "            const std::uint32_t fixes[5] = {0u, FixAdd, FixAdd + CapAdd, FixAdd + BoostAdd, FixAdd + CapAdd + BoostAdd};\n"
                "            for (std::uint32_t ci = 0; ci < (m == 0 ? 1u : 5u); ++ci) { // (the fixes only with BinaryAdd: m above 0)\n")

TW_CAPTXT_OLD = '''inline void CapOnceText(char* out, std::size_t size) {
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
'''
TW_CAPTXT_NEW = '''inline void CapOnceText(char* out, std::size_t size) {
    // bbport (r89n_twigs-visible): the hard bound by the limits, and a tip's move in a full gust front at the strongest wind
    const double real = static_cast<double>(W::TwigCap) *
                        (std::hypot(static_cast<double>(W::MaxAlong), static_cast<double>(W::MaxCross)) +
                         1.4143 * static_cast<double>(W::MaxLeaf)) * 100.0;
    const double crest = static_cast<double>(W::TwigCap) * static_cast<double>(W::BendMax) *
                         static_cast<double>(W::TwigRest + W::TwigPush) * 100.0;
    const double ratio = static_cast<double>(BbWind::MaxSpeed / BbWind::DefaultSpeed) *
                         static_cast<double>(BbWind::MaxSpeed / BbWind::DefaultSpeed);
    if (CapOn()) {
        std::snprintf(out, size,
                      "Wind twigs cap (r89n, BB_WIND_TWIGS_CAP=1): a tree word's weight w is boosted x%.0f and soft capped at %.2f "
                      "(w / (1 / %.0f + w / cap): smooth), so a twig tip moves up to about %.0f cm in a full gust front at 4 m/s "
                      "(BB_WIND_SWAY 1; hard bound %.0f cm), %.0f times less at 1.5 m/s, and neighbouring vertices move together; "
                      "a strictly judged mesh whose box is over %.0f m is refused (box-many; not with TREES, palette or SMALL=3)",
                      static_cast<double>(W::TwigBoost), static_cast<double>(W::TwigCap), static_cast<double>(W::TwigBoost), crest,
                      real, ratio, static_cast<double>(OneTreeBox));
    } else {
'''

# ---------------------------------------------------------------- lift_stage.cpp / emit_spirv_special.cpp
LF_OLD = "        const u32 denom = FAdd(CF(1.0f), FMul(abs_f(x), CF(1.0f / cap)));\n"
LF_NEW = ("        // bbport (r89n_twigs-visible): w / (1 / TwigBoost + |w| / cap), BbWindSway::TwigSoftCap\n"
          "        const u32 denom = FAdd(CF(1.0f / W::TwigBoost), FMul(abs_f(x), CF(1.0f / cap)));\n")

EM_OLD = "        const Id capped = ctx.OpFDiv(f32_type, x, add(f(1.0f), mul(ctx.OpFAbs(f32_type, x), f(1.0f / cap))));\n"
EM_NEW = ("        // bbport (r89n_twigs-visible): w / (1 / TwigBoost + |w| / cap), BbWindSway::TwigSoftCap\n"
          "        const Id capped = ctx.OpFDiv(f32_type, x, add(f(1.0f / W::TwigBoost), mul(ctx.OpFAbs(f32_type, x), f(1.0f / cap))));\n")

# ---------------------------------------------------------------- tests/test_wind_trees.cpp
TE1_OLD = '''        Expect(std::fabs(S::TwigSoftCap(0.05f) - 0.05f / (1.0f + 0.05f / S::TwigCap)) < 1.0e-7f && S::TwigSoftCap(0.05f) > 0.04f,
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
'''
TE1_NEW = '''        // bbport (r89n_twigs-visible): the boosted cap: w / (1 / TwigBoost + |w| / TwigCap)
        Expect(std::fabs(S::TwigSoftCap(0.05f) - 0.05f / (1.0f / S::TwigBoost + 0.05f / S::TwigCap)) < 1.0e-6f &&
                   S::TwigSoftCap(0.01f) > 0.04f && S::TwigSoftCap(0.05f) > 0.2f,
               "a small weight is boosted (about x6)");
        bool monotone = true, under_cap = true, slow = true;
        float previous = 0.0f;
        for (int i = 1; i <= 4000; ++i) {
            const float x = 0.005f * static_cast<float>(i);
            const float y = S::TwigSoftCap(x);
            monotone = monotone && y >= previous;
            under_cap = under_cap && y < S::TwigCap + 1.0e-6f;
            slow = slow && (y - previous) <= S::TwigBoost * 0.005f + 1.0e-6f; // slope at most TwigBoost
            previous = y;
        }
        Expect(monotone && under_cap && slow, "the cap is monotone, below the cap, slope at most TwigBoost");
        Expect(S::TwigSoftCap(4.5f) > 1.2f && S::TwigSoftCap(4.5f) < S::TwigCap && S::TwigSoftCap(1.0e9f) < S::TwigCap + 1.0e-6f,
               "r89l's weight of 4.5 gives under the cap");
        Expect(std::fabs(S::TwigSoftCap(0.15f) - 0.53f) < 0.02f && std::fabs(S::TwigSoftCap(0.6f) - 0.95f) < 0.02f,
               "a typical limb piece's raw weight 0.15 gives y 0.53, 0.6 gives 0.95");
        const double most = static_cast<double>(S::TwigCap) *
                            (std::hypot(static_cast<double>(S::MaxAlong), static_cast<double>(S::MaxCross)) +
                             1.4143 * static_cast<double>(S::MaxLeaf));
        Expect(most > 0.60 && most < 0.80, "the hard bound of the largest move is 60 to 80 cm");
        Expect(most * static_cast<double>(S::TwigCapProofMul) < 0.80, "the proof's largest move stays under 80 cm");
        // a tip in a full gust front at 4 m/s (bend D = BendMax at BB_WIND_SWAY 1, push rule: D x (TwigRest + TwigPush)): the
        // typical tip 17 cm, the largest 42 cm; at 1.5 m/s the bend is (1.5 / 4)^2 of that: a few cm
        const double crest4 = static_cast<double>(S::BendMax) * static_cast<double>(S::TwigRest + S::TwigPush);
        const double crest15 = crest4 * (1.5 / 4.0) * (1.5 / 4.0);
        Expect(static_cast<double>(S::TwigSoftCap(0.15f)) * crest4 > 0.10 && static_cast<double>(S::TwigSoftCap(0.15f)) * crest4 < 0.30 &&
                   static_cast<double>(S::TwigCap) * crest4 > 0.30 && static_cast<double>(S::TwigCap) * crest4 < 0.50,
               "a typical tip moves 10-30 cm in a full gust front at 4 m/s, the largest 30-50 cm");
        Expect(static_cast<double>(S::TwigCap) * crest15 < 0.07 && static_cast<double>(S::TwigSoftCap(0.15f)) * crest15 < 0.04 &&
                   static_cast<double>(S::TwigSoftCap(0.15f)) * static_cast<double>(S::BendMax) * (1.5 / 4.0) * (1.5 / 4.0) *
                           static_cast<double>(S::TwigRest) < 0.01,
               "at 1.5 m/s a tip moves under 4 cm in a gust front and under 1 cm between gusts: almost still");
'''

TE2_OLD = '        Expect(T::OneTreeBox == 30.0f && T::FixAdd == 4000u && T::CapAdd == 8000u, "the constants");\n'
TE2_NEW = (TE2_OLD +
           '        // bbport (r89n_twigs-visible): the shader versions since r89n carry BoostAdd (with the cap on or off)\n'
           '        Expect(T::BoostAdd == 16000u && T::KnownVersion(2011 + T::FixAdd + T::BoostAdd, 11, 21, 1000) &&\n'
           '                   T::KnownVersion(2011 + T::FixAdd + T::CapAdd + T::BoostAdd, 11, 21, 1000) &&\n'
           '                   T::KnownVersion(2011 + 20 + T::OffsetAdd + T::FixAdd + T::CapAdd + T::BoostAdd, 11, 21, 1000) &&\n'
           '                   !T::KnownVersion(2011 + T::BoostAdd, 11, 21, 1000) && !T::KnownVersion(2011 + T::CapAdd + T::BoostAdd, 11, 21, 1000),\n'
           '               "the shader versions with BoostAdd are known, a stray one is not");\n')

# ---------------------------------------------------------------- README
RM1_OLD = ("is `w / (1 + w / 0.28)`: smooth, never above 0.28, slope at most 1, so no vertex of a tree moves more than about 15 cm at the strongest wind (`BB_WIND_SPEED=4`: ")
RM1_NEW = ("is `w / (1 / 6 + w / 1.3)` (r89n: boosted x6, capped at 1.3; r89m's `w / (1 + w / 0.28)` left the twigs under 3 cm, invisible in the 4K clip): "
           "smooth, never above 1.3, so a twig tip moves 8 to 31 cm in a full gust front at 4 m/s for a raw weight of 0.05 to 0.6 and at most 42 cm "
           "(`BB_WIND_SWAY` 1; 70 cm by the limits), the steady lean between fronts about 2 cm, and about 7 times less at 1.5 m/s (a few cm: almost still); the amount follows `BB_WIND_TWIGS` "
           "(live with the test tools: `set:BB_WIND_TWIGS=0.5`, `1`, `2`, `4`; the cap holds it) (before r89m: ")
RM2_OLD = "bend x (0.05 + 2.5 x F squared)"
RM2_NEW = "bend x (0.2 + 2.5 x F squared; 0.05 before r89n)"
RM3_OLD = "the mean of the moving part is a third of the peak. Read once"
RM3_NEW = "the mean of the moving part is a third of the peak (since r89n the steady part is 4 times the steady cm named here, the peak 6% more). Read once"

EDITS = {
    SWAY: [(SW_CONST_OLD, SW_CONST_NEW), (SW_RET_OLD, SW_RET_NEW), (SW_REST_OLD, SW_REST_NEW)],
    TWIGS: [(TW_FIX_OLD, TW_FIX_NEW), (TW_BIN_OLD, TW_BIN_NEW), (TW_KNOWN_OLD, TW_KNOWN_NEW), (TW_CAPTXT_OLD, TW_CAPTXT_NEW)],
    LIFT: [(LF_OLD, LF_NEW)],
    EMIT: [(EM_OLD, EM_NEW)],
    TEST: [(TE1_OLD, TE1_NEW), (TE2_OLD, TE2_NEW)],
    README: [(RM1_OLD, RM1_NEW), (RM2_OLD, RM2_NEW), (RM3_OLD, RM3_NEW)],
}

CHECKS = {
    SWAY: [("TwigCap = 1.3f, TwigBoost = 6.0f, TwigCapProofMul = 1.0f;", 1), ("1.0f / TwigBoost + std::fabs(w) / cap", 1),
           ("TwigRest = 0.2f, TwigPush = 2.5f", 1), ("TwigCap = 0.28f", 0)],
    TWIGS: [("BoostAdd = 16000;", 1), ("FixAdd + BoostAdd + (CapOn() ? CapAdd : 0u)", 1), ("fixes[5]", 1), ("Wind twigs cap (r89n, BB_WIND_TWIGS_CAP=1)", 1),
            ("fixes[3]", 0)],
    LIFT: [("CF(1.0f / W::TwigBoost)", 1), ("FAdd(CF(1.0f), FMul(abs_f(x)", 0)],
    EMIT: [("f(1.0f / W::TwigBoost)", 1), ("add(f(1.0f), mul(ctx.OpFAbs(f32_type, x)", 0)],
    TEST: [("S::TwigBoost", 2), ("T::BoostAdd == 16000u", 1), ("wind-trees-test: ok", 1)],
    README: [("`w / (1 / 6 + w / 1.3)`", 1), ("0.05 before r89n", 1), ("`w / (1 + w / 0.28)`: smooth", 0)],
}

# Numbers written twice: the header's constants and the README text.
TIES = [("TwigCap = 1.3f, TwigBoost = 6.0f", "| `BB_WIND_TWIGS_CAP`", "`w / (1 / 6 + w / 1.3)`"),
        ("TwigRest = 0.2f", "| `BB_WIND_TWIGS_PUSH`", "(0.2 + 2.5 x F squared")]


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
        if (texts[SWAY].count(const) != 1) or value not in rows:
            raise SystemExit("tie check: %r against the README row %r (%r)" % (const, row_start, value))
    for path, new in [(p, n) for p, es in EDITS.items() if p != README for _, n in es]:
        if "\r" in new:
            raise SystemExit("new text must have LF only in the script")
        if not all(ord(c) < 128 for c in new):
            raise SystemExit("%s: new text must be ASCII" % path)
        if any(x in new for x in ("C:/", "G:/", "<user>", "Temp/claude")):
            raise SystemExit("a local path in the patch's text")
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
        raise SystemExit("%s is not a source tree root (set R89N_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = todo = 0
        for old, new in edits:
            if cur.count(new) == 1 and (old not in new or cur.count(old) == 1):
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
            tmp = full + ".r89ntmp"
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
            if cur.count(old) != 1 or (old not in new and cur.count(new) != 0):
                raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, edits, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r89ntmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
