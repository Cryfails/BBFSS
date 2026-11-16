# r89p_twigs-really-move: FEATURE fix (the trees route's camera gate, BB_WIND_TWIGS_TREES=1 path only) + TOOL (BB_WIND_FREEZE, a
# frozen full gust front for the A/B that shows whether moved vertices reach the pixels; goes to the test-tools branch) + two log lines.
# On top of r89o_wind-chains-twigs-visible (build 73). CPU side only: no shader, pipeline key or cache version changes in any state.
#
# THE OWNER (build 72, 4K): "I can't see the tree branches or twigs moving at all." The b73 slot twins (r89o-gy-live / r89o-gy-nogate) show
# the same branch pixels on_a / on_c / off_a. WHAT THE LOGS SAY (numbers read from b73_s6.log (live), b73_s2.log (nogate), b60_s1.log,
# owner_b72_run1.log (222 report windows of 600 frames), 26 logs in all):
#
#  1. THE DRAWS ARE TAKEN, THE WORDS ARE WRITTEN, THE SHADERS MOVE THE VERTICES (so it is not the recompiler/lifter, not the pipeline key,
#     not the cache version): b73_s6, graveyard, 600 frames: 36600 candidate draws taken as trees (61 a frame = the 61 tree-shaped meshes
#     of the book), 0 indoors, 1200 refused as too small (r89o); of them 16200 draws (27 a frame) got a tree word from the world judge
#     (r89e line: "draws 36600 seen, 16200 tree, 20400 refused"), 10 'lone' tree meshes by the plant rule. The b58/b60 proof lines (offset
#     counters of the lifter's shader, the only builds that had them) say the lifted shaders of vs 7620368b, 9da6aacb, 6a833138 and c829ee58
#     moved vertices in the G-buffer pass: 852M G-buffer vertex runs, mean 2.07 cm, over 10 cm 71M, largest 23 cm at x5 under the cap
#     (b58 uncapped: largest 894 cm, the torn tree). So a weight and a move exist where a word exists.
#  2. NO WORD AT ALL ON THE WOOD IN THE b73 JOBS (the visible branches are LIMB PIECES: r89k's header, the pick of build 55: draws of 2043
#     and 35898 indices whose own shape verdict is no-spread / stout): the line 'taken (tree-shaped or limb piece, r89k: N limb)':
#         b57..b72 logs and the owner's run (26 logs, none with BB_WIND_GAME): N from 24905 to 69000 limb draws in 600 frames
#             (b60_s1 61675 of 98495 taken; owner_b72_run1 up to 69000 of 138600; limb meshes in the twig book 96-226, 62-134 judged trees)
#         b73_s6 (r89o-gy-live): 0 of 36600; limb meshes in the twig book 0; b73_s2 (nogate, size rule OFF): 232..600 limb of 37800;
#             b73_s3 (dark interior): 0. The same 114 limb pieces are judged in both builds (identical LIMB PIECE lines, 16 of 16), the
#             candidate draws are the same 269400 a window, the refusals grew by what the limb draws were (231600 against 167315).
#     So in the b73 pictures NO opaque wood draw has a sway word: only the 27 tree draws a frame the book accepted (mostly distant, r89k)
#     move; the near overhead branches are limb pieces. The pictures can show nothing whatever the amount is. The only difference between
#     the b73 jobs and every log that has limbs is the job env BB_WIND_GAME=1 (r122) and the ten patches since b72; NO code path from
#     either to WindTreesDraw's limb test (`!mesh->tree && mesh->limb && opaque && LimbOn()`) was found by reading, so the MECHANISM IS NOT
#     PROVEN (the test cannot be told apart: pixel shader discards = not opaque, or mesh->limb lost). Two new counters tell it in the next
#     run (below). The new jobs run WITHOUT BB_WIND_GAME (the owner's own run had none: no 'Wind game' line in owner_b72_run1.log).
#  3. THE CAMERA GATE SWITCHES THE WHOLE GRAVEYARD OFF UNDER CANOPY (a real cause for the owner, proven by his log): the trees route
#     refuses every tree-shaped draw while the camera's open wind share (r117: 1 - the field at the camera) is under OpenMin 0.5. Owner
#     run, windows with candidates, by the shelter line's 'at the camera' value: cam under 0.2 (open air): 50 of 50 windows took trees;
#     0.2-0.5: 26 of 26; 0.5 and over: 22 of 146 (a real interior reads 0.95-1.0, the library, the cathedral). The stretch of windows
#     72-90 of the log reads 'at the camera 0.52-0.53, overhead cover 0.49' with 99600 candidate draws, 39000 of them tree-shaped refused
#     as indoors, 0 taken, for at least 7 windows in a row (4200 frames): the graveyard seen from under or beside the canopy (the same 65
#     tree draws a frame the open windows take; cam 0.46-0.47 right before and after: 51000 taken). A camera under a tree reads the
#     tree's own canopy as a roof; the trees are the one thing that must keep swaying there. The per-vertex shelter factor (1 - At, r117)
#     still takes the wind away from a vertex in a real lee, so the camera-wide switch is only needed for true interiors (0.95-1.0).
#  4. THE AMOUNT (b72, what the owner ran: gain 0.5, boost 6, cap 1.3): the b60 proof lines give the raw weight of a limb vertex as
#     gain 0.3 x ramp x R, R = twig weight x size factor, median 0.3-0.5, largest 2.7 (largest weight 1.638 at gain 1.2 x ramp 0.5). b72:
#     y = w / (1/6 + w/1.3) = 0.25-0.35 for the median vertex, so 7-10 cm at a gust crest at 4 m/s (D 0.12 m x (0.2 + 2.5) x g) and
#     about 1 cm between fronts: a few px at 4K for a fraction of the time. b73 (gain 1, boost 10, cap 1.5): y 0.67 at the median R
#     0.4: 22 cm at a crest (r89o's 19-43 cm), but only when the gust phase is at a crest: the b73 captures were 0.3 s apart (the fronts
#     pass every 2.2 s at 4 m/s, F^2 is high a quarter of the time): ALL THREE shots can fall between fronts (steady lean 2-3 cm).
#     NOT CHANGED here: the constants stay r89o's until the freeze A/B below says the wood moves in the pictures.
#  5. THE OPAQUE SKINNED COPIES (the second candidate, NOT proven): the pick of build 58 names, at (250,300) and (1100,250), rows 47 and 51
#     'vs 6a833138 ps bb10e440 ... opaque, SKINNED, sway bit no, sway word no' with the SAME stream (28588 vertices, 33642 indices from 51184)
#     as row 49 (9da6aacb, GPU palette, sway word YES): one tree mesh drawn by two pipelines, the skinned one never carries the sway bit
#     (BB_WIND_TWIGS_REACH=1). The owner's log counts those draws: 'Wind twigs (r89d) ... draws: opaque N' 10800-19200 a window (18-32
#     a frame); b73 logs 0-4 (see 2: the b73 route is different). The job r89p-gy-reach2 puts BB_WIND_TWIGS_REACH=2 into the same freeze A/B.
#
# FEATURE FIX (BB_WIND_TWIGS_OPEN_MIN, read once; default 0.2; the trees route only): the route's camera gate is 'open share under
# OpenMin' with OpenMin 0.2 (was the constant 0.5): sheltered up to 0.8 still sways (a camera under a canopy, in an arch, beside a wall:
# the owner's 0.52-0.53 windows), a real interior (0.95-1.0 sheltered, open 0.0-0.05) stays off. 0 = never gated, 1 = never taken.
# NOT a new test of the interior: the dark-interior job r89p-di must still show 0 taken and 'indoors' above 0.
#
# TOOL (BB_WIND_FREEZE, goes to the test-tools branch; live with the test tools' knobs: set:BB_WIND_FREEZE=1 / 0, else the environment
# read at each new view): the wind's view words of every view (the CPU writes them: no shader differs) are frozen at a FULL gust front
# at the camera: the gust table 1.0 everywhere, the fronts' wave scale 0 (all in step) with each front's phase solved so its skewed
# sine is exactly 1 (a + LeanSkew sin a = pi/2; n = 1 gives E = EnvScale), the swing and leaf phases 0. Every plant, tree and twig then
# leans downwind by (weight x the push rule's full-front along: D x (TwigRest + TwigPush) x 1) and STANDS STILL: no time, no gust phase to
# miss. At 4 m/s that is 0.324 m x y (about 21 cm for the median limb vertex, up to 49 cm), 17 to 30 px at 8 m in the slot window (1280x720
# picture). A picture with it on and the same camera with BB_WIND_TWIGS=0 (a live knob, the twigs' gain 0: branches at rest) differ by
# the twig move EXACTLY where the visible branches have words; where they do not differ the branch draw has no word or no sway code.
# That separates the two open causes (no word: log counters; a word but the pixels do not move: the draw that paints the pixel is another).
#
# TWO LOG LINES (trees route on, every 600 frames, next to r89o's 'Wind twigs trees (r89o ...)' line):
#   'Wind twigs trees (r89p, BB_WIND_TWIGS_OPEN_MIN=0.20): ... N draws refused as indoors ..., M limb-shaped draws refused because the pixel
#    shader discards, K taken (L of them limb pieces)': M above 0 with the limb count 0 says the b73 limb loss is has_discard; M 0 with
#    limbs 0 says mesh->limb was lost (the book).
#   'Wind freeze (r89p, TOOL ...)' once, the first time a view is frozen.
#
# OFF / COST. BB_WIND_TWIGS_TREES is 0 by default: WindTreesDraw is never called, the gate is never read, the new counters never move,
# the new line is never printed. BB_WIND_FREEZE is off by default: the hook is one test of a live-knob bool per NEW VIEW (one a frame) and
# nothing is written. CPU: one float compare as before (OpenMin() is a static read once). GPU and memory: none (no shader, no buffer; two
# u64 in Stats). Shader cache versions and pipeline keys: unchanged (nothing of r89o's numbers is touched).
#
# Files: bbport_wind_trees.h (OpenMin knob, two Stats counters, FreezeView, FreezeEnv, two text functions), vk_rasterizer_effects.cpp
# (the gate's read, one counter, the freeze knob function and its hook next to the view's memcpy, the report line), engine/tests/
# test_wind_trees.cpp (one block), README.md (one row edited, two rows added). No new file.
# STACKING: after r89o_wind-chains-twigs-visible (its anchors are the lines of that patch); r89o's own check refuses while this is applied
# only if the r89o lines it checks change (they do not): revert this script first anyway.
# Use: python -I -X utf8 r89p_twigs-really-move.py check | apply | revert (root from R89P_ROOT, else <tree>). Files keep their line
# ends. Originals are kept in r89p_backup/ next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89p_backup")
ROOT = os.environ.get("R89P_ROOT") or "<tree>"
G = "engine/gpu/"
TREES = G + "shim/bbport_wind_trees.h"
EFFECTS = G + "shadps4/video_core/renderer_vulkan/vk_rasterizer_effects.cpp"
TEST = "engine/tests/test_wind_trees.cpp"
README = "README.md"

# ---------------------------------------------------------------- bbport_wind_trees.h
TR1_OLD = ("inline constexpr float OpenMin = 0.5f;" + " " * 19 +
           "///< the camera's open wind share needed (r117's field)\n")
TR1_NEW = ('''/// bbport (r89p_twigs-really-move): the camera's open wind share (r117's field: 1 - the shelter at the camera) the trees route needs.
/// It was the constant 0.5: a camera under a canopy or beside a wall reads 0.47 to 0.53 and switched every tree off (the owner's run: windows
/// with 39000 tree-shaped draws refused as indoors and none taken, at the camera 0.52-0.53, overhead cover 0.49); a real interior reads
/// 0.95 to 1.0 sheltered. BB_WIND_TWIGS_OPEN_MIN, read once, default OpenMinDefault; 0 never gates, 1 never takes. The per-vertex shelter
/// factor (r117) still takes the wind away from a vertex in a lee.
inline constexpr float OpenMinDefault = 0.2f;

[[nodiscard]] inline float OpenMin() {
    static const float v = std::clamp(W::ParseNumber(std::getenv("BB_WIND_TWIGS_OPEN_MIN"), OpenMinDefault), 0.0f, 1.0f);
    return v;
}
''')

TR2_OLD = "                  static_cast<double>(SpreadMin), static_cast<double>(OpenMin));\n"
TR2_NEW = "                  static_cast<double>(SpreadMin), static_cast<double>(OpenMin()));\n"

TR3_OLD = "    std::uint64_t too_small = 0;     ///< bbport (r89o): tree-shaped or limb-piece draws refused as too small a model (SizeOk)\n"
TR3_NEW = (TR3_OLD +
           "    std::uint64_t limb_cutout = 0;   ///< bbport (r89p): limb piece by shape, refused because its pixel shader discards (not an opaque draw)\n")

TR4_OLD = "inline void MeshText(const Mesh& m, std::uint64_t key_stream, char* out, std::size_t size) {\n"
TR4_NEW = (r'''/// bbport (r89p_twigs-really-move): the gate and limb line, every ReportFrames frames with the trees route on.
inline void GateLineText(const Stats& s, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs trees (r89p, BB_WIND_TWIGS_OPEN_MIN=%.2f): in the last 600 frames %llu draws refused as indoors (the camera's "
                  "open wind share under that), %llu limb-shaped draws refused because their pixel shader discards, %llu taken (%llu of "
                  "them limb pieces)",
                  static_cast<double>(OpenMin()), static_cast<unsigned long long>(s.indoors),
                  static_cast<unsigned long long>(s.limb_cutout), static_cast<unsigned long long>(s.taken),
                  static_cast<unsigned long long>(s.limbs));
}

/// bbport (r89p_twigs-really-move, TOOL): BB_WIND_FREEZE (exactly "1" is on; read at each new view, live with the test tools' knobs when
/// the effects file has them). Without them: the environment.
[[nodiscard]] inline bool FreezeEnv() {
    const char* const text = std::getenv("BB_WIND_FREEZE");
    return text != nullptr && text[0] == '1' && text[1] == 0;
}

/// bbport (r89p_twigs-really-move, TOOL): the view words frozen at a full gust front: the gust table 1, the fronts' scale 0 (every point
/// at the same phase), each front's phase solved so that its skewed sine reads 1 (a + skew sin a = pi / 2, skew = the view's lean flag x
/// LeanSkew), so the envelope is EnvScale everywhere and for ever; the swing and leaf phases 0. `view` holds one view's ViewWords floats as
/// FillLean / FillRipple left them (the lean's flag at RippleAt + 13). No time and no gust remain in the move: it is the push rule's full
/// front, D x (TwigRest + TwigPush) x weight, downwind.
inline void FreezeView(float* view) {
    float* const p = view + W::RippleAt;
    const float skew = p[13] * W::LeanSkew;
    float a = 1.5707963f;
    for (int i = 0; i < 24; ++i) {
        a = 1.5707963f - skew * std::sin(a);
    }
    for (std::uint32_t i = 2; i <= 4; ++i) {
        p[i] = a;
    }
    p[0] = p[1] = p[5] = p[6] = 0.0f;
    p[7] = 0.0f;
    view[W::WindB + 3] = 0.0f;
    view[W::WindC + 2] = 0.0f;
    for (std::uint32_t i = 0; i < W::GustSamples; ++i) {
        view[W::TableAt + i] = 1.0f;
    }
}

inline void FreezeOnceText(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind freeze (r89p, TOOL, BB_WIND_FREEZE=1): every view's wind is frozen at a full gust front (gust table 1, fronts in "
                  "step at their crest, swing and leaf phases 0): plants, trees and twigs lean downwind by their full weight and stand "
                  "still; the same camera with BB_WIND_TWIGS=0 differs by the twig move only");
}

''' + TR4_OLD)

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
EF1_OLD = "    if (wind_shelter != nullptr && wind_shelter->CameraOpen() < BbWindTrees::OpenMin) {\n"
EF1_NEW = ("    // bbport (r89p_twigs-really-move): the gate is BB_WIND_TWIGS_OPEN_MIN (0.2; was the constant 0.5, which a canopy tripped)\n"
           "    if (wind_shelter != nullptr && wind_shelter->CameraOpen() < BbWindTrees::OpenMin()) {\n")

EF2_OLD = ("    if (!mesh->tree && !limb) {\n"
           "        ++st.refused;\n"
           "        return false;\n"
           "    }\n")
EF2_NEW = ("    if (!mesh->tree && !limb) {\n"
           "        // bbport (r89p_twigs-really-move): a limb piece by shape, refused only because the draw is not opaque\n"
           "        st.limb_cutout += (mesh->limb && !opaque && BbWindTrees::LimbOn()) ? 1u : 0u;\n"
           "        ++st.refused;\n"
           "        return false;\n"
           "    }\n")

EF3_OLD = ("// bbport (r112k_hang-lantern-verdict, TOOL): BB_WIND_HANG_PUSH with the test tools' live knobs (r84): \"0\" gives\n")
EF3_NEW = ('''// bbport (r89p_twigs-really-move, TOOL): BB_WIND_FREEZE with the test tools' live knobs (r84): "1" freezes every new view's wind at a
// full gust front (BbWindTrees::FreezeView), anything else or no text leaves it as it is. Read at each new view. Without the tools'
// header: the environment.
#if BB_WIND_TWIGS_LIVE
static bool FreezeParseLive(const char* text) {
    return text != nullptr && text[0] == '1' && text[1] == 0;
}

static bool WindFreezeNow() {
    static BbLiveKnobs::Knob<bool> knob{"BB_WIND_FREEZE", FreezeParseLive};
    return knob.Get();
}
#else
static bool WindFreezeNow() {
    return BbWindTrees::FreezeEnv();
}
#endif

''' + EF3_OLD)

EF4_OLD = "        std::memcpy(words + BbWindSway::ViewAt(frame_slot, view), filled.data(), sizeof(filled));\n"
EF4_NEW = ('''        if (WindFreezeNow()) { // bbport (r89p_twigs-really-move, TOOL): the view's wind frozen at a full gust front
            BbWindTrees::FreezeView(filled.data());
            static bool freeze_said = false;
            if (!freeze_said) {
                freeze_said = true;
                char freeze_text[512];
                BbWindTrees::FreezeOnceText(freeze_text, sizeof(freeze_text));
                BbReport::Printf("%s\\n", freeze_text);
            }
        }
''' + EF4_OLD)

EF5_OLD = ("        BbWindTrees::SizeLineText(trees_stats, text, sizeof(text)); // bbport (r89o_wind-chains-twigs-visible)\n"
           '        BbReport::Printf("%s\\n", text);\n')
EF5_NEW = (EF5_OLD +
           "        BbWindTrees::GateLineText(trees_stats, text, sizeof(text)); // bbport (r89p_twigs-really-move)\n"
           '        BbReport::Printf("%s\\n", text);\n')

# ---------------------------------------------------------------- tests/test_wind_trees.cpp
TE1_OLD = ('\n    if (failures == 0) {\n'
           '        std::printf("wind-trees-test: ok\\n");\n')
TE1_NEW = ('''
    { // bbport (r89p_twigs-really-move): the open gate's default, the frozen view and the two text functions
        namespace SW = BbWindSway;
        Expect(B::OpenMinDefault == 0.2f && B::OpenMin() == 0.2f, "the trees route's open gate is 0.2 (BB_WIND_TWIGS_OPEN_MIN unset in the test)");
        std::vector<float> view(SW::ViewWords, 0.0f);
        float* const p = view.data() + SW::RippleAt;
        p[13] = 1.0f; // the lean's flag: the skew is on
        p[2] = 0.3f;
        p[3] = 1.9f;
        p[4] = -2.4f;
        p[7] = 0.42f;
        p[12] = 0.12f;
        for (std::uint32_t i = 0; i < SW::GustSamples; ++i) {
            view[SW::TableAt + i] = 0.2f + 0.01f * static_cast<float>(i);
        }
        B::FreezeView(view.data());
        const float at[5][2] = {{0.0f, 0.0f}, {50.0f, -20.0f}, {-7.0f, 13.0f}, {300.0f, 300.0f}, {-1.0f, 0.5f}};
        bool crest = true;
        for (const auto& sq : at) {
            crest = crest && std::fabs(SW::Envelope(view.data(), sq[0], sq[1]) - SW::EnvScale) < 1e-3f;
        }
        Expect(crest, "a frozen view is at the crest of a front (E = EnvScale) at every point");
        bool table = true;
        for (std::uint32_t i = 0; i < SW::GustSamples; ++i) {
            table = table && view[SW::TableAt + i] == 1.0f;
        }
        Expect(table && p[7] == 0.0f && p[0] == 0.0f && p[5] == 0.0f && view[SW::WindB + 3] == 0.0f && view[SW::WindC + 2] == 0.0f,
               "a frozen view: gust table 1, fronts in step, swing and leaf phases 0");
        B::Stats st;
        st.indoors = 39000;
        st.limb_cutout = 123;
        st.taken = 36600;
        st.limbs = 7;
        char gate[400];
        B::GateLineText(st, gate, sizeof(gate));
        Expect(std::strstr(gate, "r89p") != nullptr && std::strstr(gate, "39000") != nullptr && std::strstr(gate, "123") != nullptr &&
                   std::strlen(gate) < 360,
               "the gate's line");
        char once[600];
        B::FreezeOnceText(once, sizeof(once));
        Expect(std::strstr(once, "BB_WIND_FREEZE=1") != nullptr && std::strlen(once) < 520, "the freeze once line");
    }
''' + TE1_OLD)

# ---------------------------------------------------------------- README
RM1_OLD = "(open wind share at least 0.5 with `BB_WIND_SHELTER=1`)"
RM1_NEW = "(open wind share at least `BB_WIND_TWIGS_OPEN_MIN`, 0.2 since r89p, with `BB_WIND_SHELTER=1`)"
RM2_OLD = "Read once; CPU only, no shader differs | `3` |\n"
RM2_NEW = ("Read once; CPU only, no shader differs | `3` |\n"
           "| `BB_WIND_TWIGS_OPEN_MIN` | The camera's least open wind share for the trees route (r89p; needs `BB_WIND_TWIGS_TREES=1` and `BB_WIND_SHELTER`): "
           "r117's field says how much of the wind the shelter takes away at the camera; the route took no tree while the open share was under 0.5, "
           "and a camera under a canopy or beside a wall reads 0.47 to 0.53, which switched every tree of the graveyard off (the owner's log: "
           "39000 tree-shaped draws a window refused as indoors, none taken, for thousands of frames). The default is `0.2`: a camera sheltered "
           "up to 0.8 still sways the trees (a vertex in a lee still gets less wind, r117's per-vertex factor), a real interior (0.95 to 1.0 "
           "sheltered) stays still. `0` never gates, `1` never takes. Read once; CPU only. Log: the `Wind twigs trees (r89p ...)` line every "
           "600 frames (draws refused as indoors, limb-shaped draws refused because the pixel shader discards, draws taken) | `0.2` |\n"
           "| `BB_WIND_FREEZE` | TOOL (a test aid, r89p; goes to the test-tools branch; live with the test tools' knobs): `1` freezes the wind of every new "
           "view at a full gust front: the gust table 1, the fronts all in step at their crest, the swing and leaf phases 0 (CPU words only: no "
           "shader, pipeline key or cache version differs). Every plant, tree and twig then leans downwind by its full weight and stands still, "
           "so a picture with it and one at the same camera with `BB_WIND_TWIGS=0` differ by the twig move wherever a branch has a sway word, "
           "whatever the gust phase. Once line `Wind freeze (r89p, TOOL ...)` | off |\n")

EDITS = {
    TREES: [(TR1_OLD, TR1_NEW), (TR2_OLD, TR2_NEW), (TR3_OLD, TR3_NEW), (TR4_OLD, TR4_NEW)],
    EFFECTS: [(EF1_OLD, EF1_NEW), (EF2_OLD, EF2_NEW), (EF3_OLD, EF3_NEW), (EF4_OLD, EF4_NEW), (EF5_OLD, EF5_NEW)],
    TEST: [(TE1_OLD, TE1_NEW)],
    README: [(RM1_OLD, RM1_NEW), (RM2_OLD, RM2_NEW)],
}

CHECKS = {
    TREES: [("OpenMinDefault = 0.2f;", 1), ("float OpenMin() {", 1), ("static_cast<double>(OpenMin()));", 1), ("float OpenMin = 0.5f", 0),
            ("limb_cutout = 0;", 1), ("inline void FreezeView(float* view)", 1), ("inline void GateLineText(", 1),
            ("W::LeanSkew", 1), ("BB_WIND_TWIGS_OPEN_MIN", 3)],
    EFFECTS: [("BbWindTrees::OpenMin()", 1), ("BbWindTrees::OpenMin)", 0), ("WindFreezeNow()", 3), ("BbWindTrees::FreezeView(filled.data());", 1),
              ("st.limb_cutout += (mesh->limb && !opaque", 1), ("BbWindTrees::GateLineText(trees_stats", 1), ("BB_WIND_FREEZE", 2)],
    TEST: [("B::FreezeView(view.data());", 1), ("wind-trees-test: ok", 1)],
    README: [("| `BB_WIND_TWIGS_OPEN_MIN` |", 1), ("| `BB_WIND_FREEZE` |", 1), ("at least 0.5 with `BB_WIND_SHELTER=1`", 0)],
}

# Numbers written twice: the header's constant and the README row.
TIES = [("OpenMinDefault = 0.2f;", "| `BB_WIND_TWIGS_OPEN_MIN`", "| `0.2` |")]


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
        if texts[TREES].count(const) != 1 or value not in rows:
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
        raise SystemExit("%s is not a source tree root (set R89P_ROOT)" % ROOT)
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
            tmp = full + ".r89ptmp"
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
        tmp = full + ".r89ptmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
