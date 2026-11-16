# r89f_twigs-scale: FEATURE fix on top of r89d_tree-twigs and r89e_twigs-big-trees (wind work). New knob
# BB_WIND_TWIGS_SIZE (0 off = r89e exactly, 1 on (default)); it only has an effect with BB_WIND=1 and the twigs on
# (BB_WIND_TWIGS above 0), so wind off, twigs off and BB_WIND_TWIGS_SIZE=0 all leave everything as it was.
#
# THE OWNER: "I think if the small branches on the trees moved slightly due to wind that would look great";
# "The sway on the trees either should be removed or very subtle unless it's strong wind"; "The wave should just
# be very subtle".
# THE EVIDENCE (build 38, 4K clip at 4 m/s, camera on the big graveyard trees, r89e takes the mesh "candidate
# TREE: height 37.3 m, box 45.0 x 39.0 m, verts 156641"): "tip move at 4.00 m/s: 4.5 cm lean, 9.2 cm gust front"; the
# crop diff of the 3-frame pair 0.22 with the twigs against 0.27 without, of the 120-frame pair 1.29 against 0.88:
# no visible motion. A 4.5 cm tip move on a 37 m tree 15-30 m from the camera is under a pixel (1 px = 1.04 cm at
# 20 m at 4K, 90 deg horizontal field of view).
#
# THE CAUSE. The twig weight (BbWindSway::TwigWeight, r89d) is a SHAPE rule: 0 at the trunk and the low parts, 1 at
# the outer upper branches. What the weight multiplies is the lean's bend, in metres, of a BUSH at that wind speed
# (LeanAt: D = BendMax x (v / MaxSpeed)^2 and held to MaxAlong 0.4 m before the weight): a tip moves TwigRatio 0.30
# x BB_WIND_TWIGS of that, whatever the tree's size. That is right for a 6 m tree and nothing for a 37 m one.
#
# THE FIX. The twig weight is multiplied by a SIZE FACTOR from the vertex's own height h above its mesh's lowest
# point (the lever arm: the same wind bends a tall tree's tip by more metres):
#       size = clamp(h / SizeRefH, 1, SizeMax),   SizeRefH = 6 m, SizeMax = 7
# (BbWindSway::SizeFactor; the shaders and BbWindSway::Displace do the same: one clamp and one multiply of the
# twig weight, nothing else changes). The weight's own rule (radius from the box centre line, height in the mesh:
# trunks and big limbs still, only outer upper branches move, a gust front travelling through the crown, the very
# subtle wave of r89c/r89b all ride on the same displacement and scale together: the wave stays the same share of
# the lean) is not touched. Using the VERTEX's height (not the mesh's) means each tip of a mesh that holds
# several trees of different heights is scaled by its own height above the mesh's base.
#
# NUMBERS (tip move, cm, lean / crest of a gust front; the first pair is r89e's TipAt, the rest x size):
#   at 4 m/s:   6 m 4.5/9.2   12 m 9.0/18.4   20 m 15.0/30.7   37 m 27.8/56.7   (the held ceiling: 0.30 x 7 x 0.4 m = 84 cm)
#   at 1.5 m/s: 6 m 0.6/1.3   12 m 1.2/2.6    20 m 2.0/4.3     37 m 3.7/8.0
#   at 0.4 m/s (calm, weather wind): the bend goes with the speed squared: 37 m 0.3/0.6 cm: nothing.
# At 4K, 90 deg field of view the 37 m tree's tip lean at 4 m/s is 27 px at 20 m and 13 px at 40 m (14 and 7 px
# for the 12 m one at 2x less size); at 1.5 m/s 3.6 px (20 m), under 2 px at 40 m: calm stays calm. Those are
# computed from the formulas (and the log prints the same from TipAt), not measured in the game.
#
# THE STAND QUESTION (asked by the lead): does a mesh holding many trees get "distance from its own trunk"?
# NO, and this patch does not add it: the shaders know a vertex's world position and its mesh's box keys, not the
# mesh's local layout, so the radius in the twig weight is from the BOX CENTRE LINE of the mesh. Candidate TREE
# "box 45.0 x 39.0 m, height 37.3 m, 156641 vertices" is one mesh; if it is ONE giant tree (box/height 1.2, a 156k
# vertex tree) the rule is right; if it is a stand of trees, the trunks of the tall outer trees (radius above 0.35
# of the half width, height above 0.3 x 37.3 = 11 m) get the outer-upper weight too and lean with their tips, and
# short trees of the stand (under 11 m, h / mesh under 0.3) stay still. What this patch does for stands: the size
# factor is per VERTEX height, so a short tree's tips are not scaled by the tall tree's height; the log line of the
# candidate ("far" = share of vertices far from the longest axis) says which case it is. A per-tree trunk map
# (CPU reading of the position stream plus the model matrix, or a GPU grid of per-cell keys) is the next step if
# the game shows trunks moving; it is not drafted here.
#
# OFF. BB_WIND_TWIGS_SIZE=0, BB_WIND unset, BB_WIND_TWIGS=0 or BB_WIND_SWAY_STYLE=wave: SizeOn() is false (read once);
# the shader emitters' new lines are inside `if (BbWindTwigs::SizeOn())`, so the SPIR-V is byte for byte as r89e's
# and the shader binary version offset stays 2000 (BinaryOffset); the CPU adds no code path (the new once and
# report lines are under SizeOn()). With it on the sway shaders carry the version offset 2000 + 100.
# COST ON: per vertex of a swayed twig draw (inside the sway branch) one clamp and two multiplies: nothing
# measurable; no memory, no new GPU resource, no CPU work per draw; a log line every 600 frames.
#
# Files: edits only: bbport_wind_sway.h (constants, SizeFactor, TwigWeight, TwigIn, Displace), bbport_wind_twigs.h (knob,
# SizeOn, version offset, TipSized, two texts), emit_spirv_special.cpp and lift_stage.cpp (the twig line),
# vk_rasterizer_effects.cpp (two log hooks), tests/test_wind_sway.cpp (a block), README.md (a row).
# Order: after r89e (and everything on top of it in the tree); revert this one first.
#
# Use: python -I -X utf8 r89f_twigs-scale.py check | apply | revert (root from R89F_ROOT, else <tree>).
# Files keep their line ends. Originals are kept in r89f_backup/ next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89f_backup")
ROOT = os.environ.get("R89F_ROOT") or "<tree>"
G = "engine/gpu/"
R = G + "shadps4/video_core/renderer_vulkan/"
HEADER = G + "shim/bbport_wind_sway.h"
NEWH = G + "shim/bbport_wind_twigs.h"
EFFECTS = R + "vk_rasterizer_effects.cpp"
EMIT = G + "shadps4/shader_recompiler/backend/spirv/emit_spirv_special.cpp"
LIFT = G + "shim/lifter/lift_stage.cpp"
TEST = "engine/tests/test_wind_sway.cpp"
README = "README.md"

# ---------------------------------------------------------------- bbport_wind_sway.h
S_CONST_OLD = "inline constexpr float TwigHalfFloor = 0.5f; ///< m\n"
S_CONST_NEW = S_CONST_OLD + r'''// bbport (r89f_twigs-scale): with BB_WIND_TWIGS_SIZE the twig weight is multiplied by the vertex's height
// above its mesh's lowest point over SizeRefH, held to 1 .. SizeMax (the lever arm: the lean's bend is a
// bush's, in metres, so a tall tree's tips need a larger move to show). Not applied: BbWindTwigs::SizeOn().
inline constexpr float SizeRefH = 6.0f, SizeMax = 7.0f; ///< m, and a factor
inline constexpr float SizeInv = 1.0f / SizeRefH;
static_assert(SizeRefH > 0.0f && SizeMax >= 1.0f);

/// The size factor of a vertex `h` m above its mesh's lowest point (the shaders' clamp).
[[nodiscard]] inline float SizeFactor(float h) {
    return std::clamp(h * SizeInv, 1.0f, SizeMax);
}
'''
S_IN_OLD = "    bool tree_only = false;\n};\n"
S_IN_NEW = ("    bool tree_only = false;\n"
            "    bool sized = false; ///< bbport (r89f_twigs-scale): BB_WIND_TWIGS_SIZE (the weight x SizeFactor)\n"
            "};\n")
S_W_OLD = ("[[nodiscard]] inline float TwigWeight(const float* view, float ax, float az, float h, float mesh,\n"
           "                                      const std::array<std::uint32_t, 4>& keys) {\n")
S_W_NEW = ("[[nodiscard]] inline float TwigWeight(const float* view, float ax, float az, float h, float mesh,\n"
           "                                      const std::array<std::uint32_t, 4>& keys, bool sized = false) {\n")
S_RET_OLD = "    return view[RippleD + 2] * (wr * wh);\n"
S_RET_NEW = ("    const float weight = view[RippleD + 2] * (wr * wh);\n"
             "    return sized ? weight * SizeFactor(h) : weight; // bbport (r89f_twigs-scale)\n")
S_CALL_OLD = ("        wt_use = tau > 0.0f ? TwigWeight(view, view[WindE + 2] + rx, view[WindE + 3] + rz, h, mesh,\n"
              "                                         twig->keys)\n")
S_CALL_NEW = ("        wt_use = tau > 0.0f ? TwigWeight(view, view[WindE + 2] + rx, view[WindE + 3] + rz, h, mesh,\n"
              "                                         twig->keys, twig->sized)\n")

# ---------------------------------------------------------------- bbport_wind_twigs.h
N_ADD_OLD = "inline constexpr std::uint32_t BinaryAdd = 2000; ///< added to the sway shader binary version when on\n"
N_ADD_NEW = (N_ADD_OLD +
             "/// bbport (r89f_twigs-scale): added to the version as well with BB_WIND_TWIGS_SIZE (the shader differs).\n"
             "inline constexpr std::uint32_t SizeAdd = 100;\n")
N_KNOB_OLD = "    int small = 1; ///< bbport (r89e): BB_WIND_TWIGS_SMALL 0 off, 1 the rule, 2 log only, 3 loose\n};\n"
N_KNOB_NEW = ("    int small = 1; ///< bbport (r89e): BB_WIND_TWIGS_SMALL 0 off, 1 the rule, 2 log only, 3 loose\n"
              "    int size = 1;  ///< bbport (r89f): BB_WIND_TWIGS_SIZE 0 off, 1 the size factor\n"
              "};\n")
N_SIG_OLD = "                                    const char* small = nullptr) {\n"
N_SIG_NEW = "                                    const char* small = nullptr, const char* size = nullptr) {\n"
N_PARSE_OLD = "        k.small = s >= 2.5f ? 3 : (s >= 1.5f ? 2 : (s >= 0.5f ? 1 : 0));\n    }\n"
N_PARSE_NEW = (N_PARSE_OLD +
               "    k.size = W::ParseNumber(size, 1.0f) >= 0.5f ? 1 : 0; // bbport (r89f_twigs-scale): 0 or 1, unreadable 1\n")
N_ONCE_OLD = '                                       std::getenv("BB_WIND_TWIGS_SMALL"));\n'
N_ONCE_NEW = ('                                       std::getenv("BB_WIND_TWIGS_SMALL"),\n'
              '                                       std::getenv("BB_WIND_TWIGS_SIZE"));\n')
N_SIZEON_OLD = "[[nodiscard]] inline bool SmallLoose() {\n    return KnobOnce().small >= 3;\n}\n"
N_SIZEON_NEW = (N_SIZEON_OLD + r'''
/// bbport (r89f_twigs-scale): whether the twig weight carries the size factor (BB_WIND_TWIGS_SIZE above 0, the
/// twigs on). Read once with the shaders: the sway shaders then differ (BinaryOffset).
[[nodiscard]] inline bool SizeOn() {
    return KnobOnce().on && KnobOnce().size >= 1;
}
''')
N_OFF_OLD = "    return On() ? BinaryAdd : 0u;\n"
N_OFF_NEW = "    return On() ? BinaryAdd + (SizeOn() ? SizeAdd : 0u) : 0u; // bbport (r89f_twigs-scale)\n"
N_KNOWN_OLD = "        for (const std::uint32_t b : {0u, BinaryAdd}) {\n"
N_KNOWN_NEW = "        for (const std::uint32_t b : {0u, BinaryAdd, BinaryAdd + SizeAdd}) { // bbport (r89f)\n"
N_TEXT_OLD = "                  double(SmallMaxH), census.huge, double(census.huge_top));\n}\n"
N_TEXT_NEW = N_TEXT_OLD + r'''
// bbport (r89f_twigs-scale): the size-scaled tips' numbers and log texts.

/// A twig tip's move (TipAt) at wind `speed` on a tip `h` m above its mesh's lowest point: TipAt x
/// BbWindSway::SizeFactor(h) when `sized`.
[[nodiscard]] inline Tip TipSized(float speed, float scale, float wave, float twigs, float h, bool sized) {
    Tip t = TipAt(speed, scale, wave, twigs, false);
    const float k = sized ? W::SizeFactor(h) : 1.0f;
    t.lean *= k;
    t.front *= k;
    return t;
}

/// The once line of BB_WIND_TWIGS_SIZE (under 640 characters): the tip at 1.5 and 4 m/s at 6, 12, 20 and 37 m.
inline void SizeOnceText(const Knob& k, float scale, float wave, char* out, std::size_t capacity) {
    const float heights[4] = {W::SizeRefH, 12.0f, 20.0f, 37.0f};
    char at_slow[176], at_fast[176];
    at_slow[0] = 0;
    at_fast[0] = 0;
    for (int i = 0; i < 4; ++i) {
        const Tip a = TipSized(BbWind::DefaultSpeed, scale, wave, k.twigs, heights[i], k.size >= 1);
        const Tip b = TipSized(BbWind::MaxSpeed, scale, wave, k.twigs, heights[i], k.size >= 1);
        const std::size_t n_slow = std::strlen(at_slow), n_fast = std::strlen(at_fast);
        std::snprintf(at_slow + n_slow, sizeof(at_slow) - n_slow, "%s%.1f/%.1f (%.0f m)", i == 0 ? "" : ", ",
                      double(a.lean * 100.0f), double(a.front * 100.0f), double(heights[i]));
        std::snprintf(at_fast + n_fast, sizeof(at_fast) - n_fast, "%s%.1f/%.1f (%.0f m)", i == 0 ? "" : ", ",
                      double(b.lean * 100.0f), double(b.front * 100.0f), double(heights[i]));
    }
    std::snprintf(out, capacity,
                  "Wind twigs (r89f, BB_WIND_TWIGS_SIZE=%d): a twig tip moves x (its height above the mesh's "
                  "lowest point / %.0f m), 1 to %.0f; tip cm lean/gust front at 1.5 m/s: %s; at 4 m/s: %s",
                  k.size, double(W::SizeRefH), double(W::SizeMax), at_slow, at_fast);
}

/// The line every W::ReportFrames frames (under 320 characters): the tree draws taken (the sun-drawn and the
/// static cut-outs), the tallest tree and its tip's move at this wind.
inline void SizeReportText(const Census& census, const Stats& st, const BbWind::Snapshot& wind, const Knob& k,
                           float scale, float wave, char* out, std::size_t capacity) {
    const float speed = std::isfinite(wind.speed) ? std::max(wind.speed, 0.0f) : 0.0f;
    const float top = census.tallest[0];
    const Tip tip = TipSized(speed, scale, wave, k.twigs, top, k.size >= 1);
    std::snprintf(out, capacity,
                  "Wind twigs (r89f, BB_WIND_TWIGS_SIZE=%d): %llu tree draws with size-scaled tips; tallest %.1f m "
                  "(x%.2f): tip %.1f cm lean, %.1f cm gust front at %.2f m/s",
                  k.size, static_cast<unsigned long long>(st.tree_draws + st.small_tree), double(top),
                  double(W::SizeFactor(top)), double(tip.lean * 100.0f), double(tip.front * 100.0f),
                  double(speed));
}
'''

# ---------------------------------------------------------------- the two shader emitters
E_OLD = "        const Id twig = mul(comp(lean_d, 2u), mul(wr, wh));\n"
E_NEW = ("        Id twig = mul(comp(lean_d, 2u), mul(wr, wh));\n"
         "        if (BbWindTwigs::SizeOn()) { // bbport (r89f_twigs-scale): x clamp(h / SizeRefH, 1, SizeMax)\n"
         "            twig = mul(twig, ctx.OpFClamp(f32_type, mul(h, f(W::SizeInv)), f(1.0f), f(W::SizeMax)));\n"
         "        }\n")
L_OLD = "        const u32 twig = FMul(comp(lean_d, 2), FMul(wr, wh));\n"
L_NEW = ("        u32 twig = FMul(comp(lean_d, 2), FMul(wr, wh));\n"
         "        if (BbWindTwigs::SizeOn()) { // bbport (r89f_twigs-scale): as the recompiler's EmitVertexSway\n"
         "            twig = FMul(twig, clamp_f(FMul(h, CF(W::SizeInv)), CF(1.0f), CF(W::SizeMax)));\n"
         "        }\n")

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
F_REPORT_OLD = ('        BbReport::Printf("%s\\n", small_text);\n'
                "    }\n"
                "    twig_stats = {};\n")
F_REPORT_NEW = ('        BbReport::Printf("%s\\n", small_text);\n'
                "    }\n"
                "    if (BbWindTwigs::SizeOn()) { // bbport (r89f_twigs-scale): the size-scaled tips' line\n"
                "        char size_text[320];\n"
                "        BbWindTwigs::SizeReportText(census, twig_stats, wind.Get(), knob,\n"
                "                                    BbWindSway::KnobOnce().scale, BbWindSway::LeanKnobOnce().wave,\n"
                "                                    size_text, sizeof(size_text));\n"
                '        BbReport::Printf("%s\\n", size_text);\n'
                "    }\n"
                "    twig_stats = {};\n")
F_ONCE_OLD = ('            BbReport::Printf("%s\\n", small_once);\n'
              "        }\n")
F_ONCE_NEW = (F_ONCE_OLD +
              "        if (BbWindTwigs::SizeOn()) { // bbport (r89f_twigs-scale)\n"
              "            char size_once[640];\n"
              "            BbWindTwigs::SizeOnceText(BbWindTwigs::KnobOnce(), BbWindSway::KnobOnce().scale,\n"
              "                                      BbWindSway::LeanKnobOnce().wave, size_once,\n"
              "                                      sizeof(size_once));\n"
              '            BbReport::Printf("%s\\n", size_once);\n'
              "        }\n")

# ---------------------------------------------------------------- tests
T_ANCHOR = ('        Expect(std::strstr(line, "BB_WIND_TWIGS_SMALL=1") != nullptr && std::strlen(line) < 320, '
            '"SmallOnceText");\n    }\n\n')
T_BLOCK = r'''    // bbport (r89f_twigs-scale): the size factor, the sized twig weight and tip, the knob, the versions, the texts.
    {
        namespace T = BbWindTwigs;
        Expect(Near(SizeFactor(0.0f), 1.0, 1e-6) && Near(SizeFactor(3.0f), 1.0, 1e-6) &&
                   Near(SizeFactor(6.0f), 1.0, 1e-5) && Near(SizeFactor(12.0f), 2.0, 1e-5) &&
                   Near(SizeFactor(37.0f), 37.0 / 6.0, 1e-4) && Near(SizeFactor(60.0f), double(SizeMax), 1e-6) &&
                   Near(SizeFactor(-5.0f), 1.0, 1e-6),
               "SizeFactor: 1 up to 6 m, h / 6 m above, held to 7");
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const auto view = TwigViewOf(c, Wind(5.0, 225.0f, 1.5f), ripple, 1.0f);
        const float gain = view[RippleD + 2];
        const std::array<double, 3> mid = {10.0 - std::sin(0.3) * 7.0, 0.0, 20.0 - std::cos(0.3) * 7.0};
        const TreeBox giant = {0.5f, 37.5f, float(mid[0] - 20.0), float(mid[0] + 20.0), float(mid[2] - 20.0),
                               float(mid[2] + 20.0)};
        const TwigIn giant_in = TwigInOf(giant, false);
        const float plain = TwigWeight(view.data(), float(mid[0] + 19.0), float(mid[2]), 33.0f, 37.0f, giant_in.keys);
        const float sized =
            TwigWeight(view.data(), float(mid[0] + 19.0), float(mid[2]), 33.0f, 37.0f, giant_in.keys, true);
        Expect(std::fabs(plain - gain) < 1e-6 && Near(sized, double(gain) * SizeFactor(33.0f), 1e-5),
               "a 37 m tree's outer upper vertex: the gain, and x h / 6 m with the size factor");
        Expect(TwigWeight(view.data(), float(mid[0]), float(mid[2]), 33.0f, 37.0f, giant_in.keys, true) == 0.0f &&
                   TwigWeight(view.data(), float(mid[0] + 19.0), float(mid[2]), 2.0f, 37.0f, giant_in.keys, true) ==
                       0.0f,
               "the size factor keeps the trunk and the low parts still (weight 0 stays 0)");
        // the tip's move over 60 s of gusts: the same at 6 m, 5.4 times as far on the 37 m tree
        const auto peak_of = [&](const TreeBox& b, const std::array<double, 3>& p, float speed, bool use_size) {
            double peak = 0.0;
            Ripple wind_ripple;
            for (int i = 0; i < 600; ++i) {
                const auto v = TwigViewOf(c, Gusty(0.1 * i, 225.0f, speed, 0.5f), wind_ripple, 1.0f);
                const auto clip = ClipOf(c, p);
                const auto before = WorldOf(v.data(), clip);
                TwigIn in = TwigInOf(b, false);
                in.sized = use_size;
                const auto after = WorldOf(v.data(), Displace(v.data(), clip, HeightKey(b.base), 1.0f, nullptr,
                                                              CrownKey(b.crown), nullptr, &in));
                peak = std::max(peak, std::hypot(after[0] - before[0], after[2] - before[2]));
            }
            return peak;
        };
        const TreeBox small_tree = {0.5f, 6.5f, float(mid[0] - 2.5), float(mid[0] + 2.5), float(mid[2] - 2.5),
                                    float(mid[2] + 2.5)};
        const std::array<double, 3> small_tip = {mid[0] + 2.4, 5.5, mid[2]};
        const std::array<double, 3> giant_tip = {mid[0] + 19.0, 33.0, mid[2]};
        const double small_plain = peak_of(small_tree, small_tip, 4.0f, false);
        const double small_sized = peak_of(small_tree, small_tip, 4.0f, true);
        const double giant_plain = peak_of(giant, giant_tip, 4.0f, false);
        const double giant_sized = peak_of(giant, giant_tip, 4.0f, true);
        const double giant_slow = peak_of(giant, giant_tip, 1.5f, true);
        const double scale_of_giant = double(SizeFactor(32.5f));
        Expect(small_plain > 0.0 && Near(small_sized, small_plain, 1e-9),
               "a 6 m tree's tip (5 m up): the size factor is 1, the move is r89e's");
        Expect(giant_plain > 0.0 && giant_sized > giant_plain * scale_of_giant * 0.9 &&
                   giant_sized < giant_plain * scale_of_giant * 1.1,
               "a 37 m tree's tip (32.5 m up) moves SizeFactor times as far as without it");
        Expect(giant_sized > 0.12 && giant_sized < 0.9, "a 37 m tree's tip at 4 m/s: a few tens of cm");
        Expect(giant_slow > 0.01 && giant_slow < 0.2 && giant_slow < 0.5 * giant_sized,
               "the same tip at 1.5 m/s: a few cm, much less than at 4 m/s");
        // the knob and the versions
        Expect(T::ParseKnob(nullptr, nullptr, true, true).size == 1 &&
                   T::ParseKnob(nullptr, nullptr, true, true, nullptr, "0").size == 0 &&
                   T::ParseKnob(nullptr, nullptr, true, true, nullptr, "1").size == 1 &&
                   T::ParseKnob(nullptr, nullptr, true, true, nullptr, "x").size == 1,
               "BB_WIND_TWIGS_SIZE: 0 or 1, unset or unreadable 1");
        Expect(T::KnownVersion(2111, 11, 21, 1000) && T::KnownVersion(3121, 11, 21, 1000) &&
                   T::KnownVersion(2011, 11, 21, 1000) && !T::KnownVersion(2211, 11, 21, 1000) &&
                   !T::KnownVersion(111, 11, 21, 1000) && T::SizeAdd == 100,
               "the saved versions with the size offset are known; no other");
        // the tip numbers and the texts
        const T::Tip base_tip = T::TipAt(4.0f, 1.0f, 1.0f, 1.0f, false);
        const T::Tip big_tip = T::TipSized(4.0f, 1.0f, 1.0f, 1.0f, 37.0f, true);
        const T::Tip none_tip = T::TipSized(4.0f, 1.0f, 1.0f, 1.0f, 37.0f, false);
        Expect(Near(big_tip.lean, double(base_tip.lean) * 37.0 / 6.0, 1e-4) &&
                   Near(big_tip.front, double(base_tip.front) * 37.0 / 6.0, 1e-4) &&
                   none_tip.lean == base_tip.lean && none_tip.front == base_tip.front,
               "TipSized: TipAt x h / 6 m (37 m), TipAt when not sized");
        char line[704];
        T::SizeOnceText(T::ParseKnob(nullptr, nullptr, true, true), 1.0f, 1.0f, line, sizeof(line));
        Expect(std::strstr(line, "BB_WIND_TWIGS_SIZE=1") != nullptr && std::strstr(line, "(37 m)") != nullptr &&
                   std::strstr(line, "at 4 m/s:") != nullptr && std::strlen(line) < 600,
               "SizeOnceText");
        T::Census census;
        census.Tall(37.3f);
        T::Stats stats;
        stats.small_tree = 40;
        stats.tree_draws = 2;
        T::SizeReportText(census, stats, Wind(5.0, 225.0f, 4.0f), T::ParseKnob(nullptr, nullptr, true, true), 1.0f,
                          1.0f, line, sizeof(line));
        Expect(std::strstr(line, "42 tree draws") != nullptr && std::strstr(line, "tallest 37.3 m") != nullptr &&
                   std::strlen(line) < 320,
               "SizeReportText");
    }

'''
T_NEW = T_ANCHOR + T_BLOCK

# ---------------------------------------------------------------- README
README_ANCHOR = "No GPU memory, no shader change; not measured | `1` |\n"
README_ROW_NEW = (README_ANCHOR +
                  "| `BB_WIND_TWIGS_SIZE` | Whether a twig tip's move grows with the tree's size (`BB_WIND_TWIGS` and "
                  "`BB_WIND_TWIGS_SMALL` rows; they set which branches move, this row how far): `0` the twigs move as "
                  "without this row (the shaders are as before), `1` (default) a vertex's twig weight is multiplied by "
                  "its height above its mesh's lowest point divided by 6 m, held to 1 to 7: a tip 6 m up moves as "
                  "before, one 37 m up 6.2 times as far (at 4 m/s a lean of 4.5 cm becomes 28 cm and a gust front's "
                  "9.2 cm 57 cm, at 1.5 m/s 0.6 cm becomes 3.7 cm, in a calm of 0.4 m/s under 1 cm: the bend still "
                  "goes with the speed squared, so a calm moves nothing). Trunks and big limbs stay still (the twig "
                  "weight's radius and height rule is not changed); a mesh holding several trees takes its radius from "
                  "the mesh's box centre line, not from each trunk (the vertex's height is its own, so a short tree's "
                  "tips are not scaled by a tall tree's). Read once with the shaders (their cache version is 2100 "
                  "with it, 2000 without). Log: once `Wind twigs (r89f, BB_WIND_TWIGS_SIZE=...)` with the tip "
                  "numbers at 6, 12, 20 and 37 m, and every 600 frames the count of size-scaled tree draws, the "
                  "tallest tree and its tip's move at the wind now. No GPU memory, no CPU work per draw; not "
                  "measured | `1` |\n")

EDITS = {
    HEADER: [(S_CONST_OLD, S_CONST_NEW), (S_IN_OLD, S_IN_NEW), (S_W_OLD, S_W_NEW), (S_RET_OLD, S_RET_NEW),
             (S_CALL_OLD, S_CALL_NEW)],
    NEWH: [(N_ADD_OLD, N_ADD_NEW), (N_KNOB_OLD, N_KNOB_NEW), (N_SIG_OLD, N_SIG_NEW), (N_PARSE_OLD, N_PARSE_NEW),
           (N_ONCE_OLD, N_ONCE_NEW), (N_SIZEON_OLD, N_SIZEON_NEW), (N_OFF_OLD, N_OFF_NEW),
           (N_KNOWN_OLD, N_KNOWN_NEW), (N_TEXT_OLD, N_TEXT_NEW)],
    EMIT: [(E_OLD, E_NEW)],
    LIFT: [(L_OLD, L_NEW)],
    EFFECTS: [(F_REPORT_OLD, F_REPORT_NEW), (F_ONCE_OLD, F_ONCE_NEW)],
    TEST: [(T_ANCHOR, T_NEW)],
    README: [(README_ANCHOR, README_ROW_NEW)],
}

CHECKS = {
    HEADER: [("inline float SizeFactor(float h)", 1), ("sized ? weight * SizeFactor(h) : weight;", 1),
             ("twig->keys, twig->sized)", 1), ("bool sized = false;", 1)],
    NEWH: [("inline bool SizeOn()", 1), ("inline Tip TipSized(", 1), ("inline void SizeOnceText(", 1),
           ("inline void SizeReportText(", 1), ('std::getenv("BB_WIND_TWIGS_SIZE")', 1), ("SizeAdd = 100;", 1),
           ("BinaryAdd + (SizeOn() ? SizeAdd : 0u)", 1)],
    EMIT: [("if (BbWindTwigs::SizeOn()) {", 1), ("f(W::SizeInv)", 1)],
    LIFT: [("if (BbWindTwigs::SizeOn()) {", 1), ("CF(W::SizeInv)", 1)],
    EFFECTS: [("BbWindTwigs::SizeReportText(", 1), ("BbWindTwigs::SizeOnceText(", 1)],
    TEST: [("TipSized(", 2), ("wind-sway-test: ok", 1)],
    README: [("| `BB_WIND_TWIGS_SIZE` |", 1), ("| `BB_WIND_TWIGS_SMALL` |", 1)],
}

ORDER = {
    NEWH: ["inline constexpr std::uint32_t SizeAdd", "int size = 1;", "inline bool SmallLoose()", "inline bool SizeOn()",
           "inline void SmallReportText(", "inline Tip TipSized(", "inline void SizeOnceText(", "inline void SizeReportText(",
           "} // namespace BbWindTwigs"],
    HEADER: ["inline constexpr float TwigHalfFloor", "inline float SizeFactor(", "struct TwigIn {", "inline float TwigWeight(",
             "inline std::array<float, 4> Displace("],
}

# Numbers written twice: the header's constants and the README row's text.
TIES = [(HEADER, "SizeRefH = 6.0f, SizeMax = 7.0f", "divided by 6 m, held to 1 to 7"),
        (NEWH, "SizeAdd = 100", "2100"),
        (NEWH, "BinaryAdd = 2000", "2000 without")]


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
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                raise SystemExit("order check: %s: %r not after the one before" % (path, s))
            at = i
    rows = "\n".join(l for l in texts[README].split("\n") if l.startswith("| `BB_WIND_TWIGS_SIZE"))
    for path, const, value in TIES:
        if texts[path].count(const) != 1 or value not in rows:
            raise SystemExit("tie check: %r against the README row (%r)" % (const, value))
    for edits in EDITS.values():
        for old, new in edits:
            if not all(ord(c) < 128 for c in new) or "\r" in new:
                raise SystemExit("new text must be ASCII with LF in the script")
            if any(x in new for x in ("C:/", "G:/", "<user>", "Temp/claude")):
                raise SystemExit("a local path in the patch's text")
    # a macro-named identifier (far, near) must not appear as a variable in the new C++ text
    for path in (NEWH, EFFECTS, HEADER):
        for bad in ("float far ", "float far;", " far =", " far;", ".far,", ".far)", " near =", "float near"):
            if bad in "".join(new for _, new in EDITS[path]):
                raise SystemExit("%s: the name %r is a macro on some Windows headers" % (path, bad))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R89F_ROOT)" % ROOT)
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
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
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
            tmp = full + ".r89ftmp"
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
        tmp = full + ".r89ftmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
