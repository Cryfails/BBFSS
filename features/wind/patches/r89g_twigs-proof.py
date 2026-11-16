# r89g_twigs-proof: FEATURE fix on top of r89d_tree-twigs, r89e_twigs-big-trees and r89f_twigs-scale (wind work), with a
# TOOL proof knob. Two knobs, both only with BB_WIND=1 and the twigs on (BB_WIND_TWIGS above 0):
#   BB_WIND_TWIGS_FIT    (FEATURE; 0 = r89f's rule exactly, 1 = the fit rule, default 1)
#   BB_WIND_TWIGS_PROOF  (TOOL, test aid; 0 off (default), 1 on)
# Wind off, twigs off, FIT=0 and PROOF=0 leave every shader and every code path as r89f had them (see OFF).
#
# THE OWNER: "I think if the small branches on the trees moved slightly due to wind that would look great";
# "The wave should just be very subtle".
# THE EVIDENCE (build 41, 4K clip graveyard-blood, 4 m/s, weather off): the log says the static tree mesh was taken
# ("candidate TREE: height 37.3 m, box 45.0 x 39.0 m, verts 156641, palette 1, vs 6a833138", "600 tree draws with
# size-scaled tips ... 27.9 cm lean, 57.0 cm gust front at 4.00 m/s"), yet frame differences show only snow.
#
# WHAT THE EVIDENCE ALREADY SHOWS (read from the tree, the log and the shader cache; no game was run for this patch):
#  1. The shader HAS the twig code and it RUNS for this mesh. The cache holds exactly one sway variant of vertex
#     shader 6a833138 (..._18.spv, lifter output, 6 OpAtomicUMin: base, crown and the four box keys), it stores
#     gl_Position AFTER the game's own store (so nothing overwrites the displacement), and the mesh's box keys were
#     filled (the candidate line reads them): only this code writes them. So "variant not patched", "pipeline built
#     before judging" and "position overwritten" are out.
#  2. The same stream is judged THREE times in one run with the SAME box and a CHANGING height: "height 4.3 m, box
#     43.3 x 36.9 m (refused: wide)", "height 37.3 m, box 45.0 x 39.0 m (TREE)", "height 42.4 m, box 45.5 x 39.5 m
#     (refused: tall)", one draw a frame, 156641 vertices each time. A tree does not grow 38 m in a minute: the stream
#     is not one tree. It holds a stand whose pieces come and go (the vertex shader reads a small bone palette:
#     "palette 1": per-tree placement), so the GPU's box keys (lowest/highest y, x, z of every vertex ever run) and
#     with them the "height" and the "box centre line" are of a union nobody sees.
#  3. r89d's twig weight is a SHAPE in that union: wr = smoothstep(0.35^2..0.85^2; r^2 / half^2) (r from the box's
#     centre line, half = 22.5 m) times wh = smoothstep(0.30..0.70; h / mesh) (h above the union's lowest point, mesh
#     37.3 m): non-zero only for a vertex more than 7.9 m from the stand's centre line AND more than 11.2 m above the
#     union's lowest point; full only beyond 19 m and above 26 m. The limbs in the 4K frame (a big tree, close) lie
#     at 3-15 m from the camera and 3-12 m up: weight 0 for nearly all of them, whatever the size factor of r89f
#     multiplies (0 x 6.2 = 0). The shader MATH is not the problem (plants swayed 4800 draws in the same run).
# This is a hypothesis with the log and the shader behind it; the PROOF knob below measures it in the game, and
# its lines say which of the other breaks it would be if it is not this one.
#
# THE FIX (BB_WIND_TWIGS_FIT=1, default). The twig weight of a tall mesh (tau above 0, as before) no longer comes
# from the mesh's box keys. It is a rule of the VERTEX's own height above the camera, hc = wy - the camera's y
# (known per vertex, nothing measured, nothing to go wrong when a stream holds a stand):
#       wt = Gain x FitShare x smoothstep(FitLo, FitHi; hc) x clamp((hc + FitEye) / SizeRefH, 1, SizeMax)
#       FitLo 3 m, FitHi 9 m, FitShare 0.6, FitEye 2 m (the camera is about 2 m above the player's ground; the last
#       factor is r89f's size factor of BB_WIND_TWIGS_SIZE, taken at the estimated height above the ground, and
#       absent with BB_WIND_TWIGS_SIZE=0), Gain = BB_WIND_TWIGS x TwigRatio (the view's RippleD.z, as before).
# Everything the owner asked for stays: only what is high up moves (nothing below 3 m over the camera: trunks'
# feet, the ground, walls); slowly, downwind (the lean's displacement, gust fronts and the very subtle wave of
# r89c/r89b ride on the same weight and scale together); a gust front travels through the crown. What changes: the
# upper trunk moves with the crown (as in a real tree: its tip bends), the weight no longer separates "outer
# twigs" from "limbs" by shape (the shape cannot be told in a stand), the lever arm grows with height. Numbers at a
# tip hc over the camera (bush lean 32 cm at 4 m/s, 4.4 cm at 1.5 m/s, gust front about 2x): hc 8 m: weight 0.28:
# 9 cm lean at 4 m/s, 1.2 cm at 1.5; hc 20 m: weight 0.66: 21 cm lean, 2.9 cm at 1.5 m/s (computed, not measured).
# Costs of the rule: a camera far above the trees (free camera over the graveyard) leaves them still; a tree on
# high ground (a hill) moves from lower on its trunk; BB_WIND_TWIGS_FIT=0 gives r89f's shape rule back.
#
# THE PROOF KNOB (BB_WIND_TWIGS_PROOF=1, TOOL: test aid, goes to the test-tools branch, not to the feature branch).
# Shaders (the lifter's, the path this mesh takes; the recompiler fallback only gets the x5):
#   - a tree word's displacement is multiplied by 5 (ProofGain);
#   - every output attribute of a vertex with a twig weight is pulled toward (1, 1, 0) by min(1, weight / gain): the
#     game's own outputs of this shader are normals and UV pairs (no colour attribute), so the tint shows as a
#     stained twig, not a clean yellow; the counters are the proof, the tint is for the eye;
#   - 16 counters per base slot in the sway buffer (words ProofAt.. behind the box keys; 114752 bytes in all): vertices
#     run, finite, of a tall mesh (tau > 0), twig weight above a tenth of the gain by the OLD (box) rule, by the FIT
#     rule and as used, moved over 1 cm, over FitLo m above the camera; the largest move (m), the largest weight,
#     the highest vertex over the camera, and the gain, lean flag, ramp, along-displacement and gust factor the
#     shader READ from its view words (so a wrong uniform shows up here, not in the CPU's copy).
# CPU: per twig-taken stream the draws since the last line, the draws whose pipeline key has the sway bit and the
# number of distinct pipelines (up to 4); every 600 frames one "Wind twigs proof (r89g): slot S: ..." line per tree
# mesh (at most 6) with a VERDICT naming the break the numbers point at: no vertex counted (the twig code did not
# run: another pipeline, or the recompiler's shader), not finite, tau 0, ramp 0, gain 0, lean 0, weight 0, move under
# 1 mm, or OK; the counters are cleared after each line. A once line says what the knob does.
# What each candidate break of the task looks like in the line: shader variant not patched / cached pipeline: verts
# 0 (ratio 0.00) with pipelines >= 1; palette write over the offset: the position store is last in the lifter's code
# (seen in the cache), so it cannot be; weight 0 from a flat mesh: "weight 0" with fit_w also 0, or old_w 0 and
# fit_w above 0 (this patch's hypothesis); wind uniform 0: gain/lean/ramp/along read 0; depth prepass moved but not
# colour pass or the reverse: both pass families draw through pipelines with the sway bit or not (the draw count
# "on pipelines with the sway bit" against "draws" says it).
#
# OFF. BB_WIND_TWIGS_FIT=0 and BB_WIND_TWIGS_PROOF=0 (or BB_WIND off, BB_WIND_TWIGS=0): FitOn() and ProofOn() are false
# (read once); every new shader line is inside `if (BbWindTwigs::FitOn())` or `if (BbWindTwigs::ProofOn())`, so the SPIR-V
# is byte for byte r89f's, the shader cache version offset stays 2100 and no sway buffer byte is added; the CPU adds
# one static-bool test per twig-taken draw (the proof note) and per report. With FIT=1 alone (the default) the
# shaders differ from r89f's in the twig weight only (cache version 2110).
# COST ON (FIT=1): per twig vertex one smoothstep (a clamp, 4 multiplies) in place of the box rule's divisions and two
# smoothsteps: not measurable; no memory, no CPU work per draw. PROOF=1: 11 atomic operations and 5 stores a twig
# vertex (the 156641-vertex mesh: about 1.7 M atomics a frame on a few addresses: a measurable cost, which is why it
# is a tool; no cost figure is meant), 114752 bytes of the sway buffer, a read of 16 words per tree mesh every 600 frames.
#
# Files: edits only: bbport_wind_sway.h (constants, FitWeight, TwigIn.fit, Displace), bbport_wind_twigs.h (knobs, version
# offsets, buffer size, counters, texts), emit_spirv_special.cpp and lift_stage.cpp (the fit rule, the x5, in the lifter
# the counters and the tint), vk_rasterizer_effects.cpp (the draw note, the proof lines, the once lines),
# tests/test_wind_sway.cpp (a block), README.md (two rows). No new file, no shader source, no CMake change.
# Order: after r89f and r112g (the tree has both); revert this one first. Compatible with r112g (the hang block's
# lines are not touched; the anchors are r89f's twig lines and the end of the sway block).
#
# Use: python -I -X utf8 r89g_twigs-proof.py check | apply | revert (root from R89G_ROOT, else <tree>).
# Files keep their line ends. Originals are kept in r89g_backup/ next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89g_backup")
ROOT = os.environ.get("R89G_ROOT") or "<tree>"
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
S_CONST_OLD = "static_assert(SizeRefH > 0.0f && SizeMax >= 1.0f);\n"
S_CONST_NEW = S_CONST_OLD + r'''
// bbport (r89g_twigs-proof): with BB_WIND_TWIGS_FIT (default 1) the twig weight is not a shape in the mesh's box
// (the GPU's box keys of a stream that holds many trees, or whose pieces come and go, measured 4 m, 37 m and 42 m
// of "height" in one run: the fractions of that put the weight on no visible vertex) but a rule of the vertex's own
// height above the camera, hc = wy - the camera's y: smoothstep(FitLo, FitHi; hc) x FitShare, x the size factor at
// hc + FitEye (the camera is about FitEye above the ground where the player stands). BbWindTwigs::FitOn().
inline constexpr float FitLo = 3.0f, FitHi = 9.0f, FitShare = 0.6f, FitEye = 2.0f; ///< m, m, a share, m
inline constexpr float FitInv = 1.0f / (FitHi - FitLo);
static_assert(FitLo < FitHi && FitShare > 0.0f && FitShare <= 1.0f && FitEye >= 0.0f);
'''
S_IN_OLD = "    bool sized = false; ///< bbport (r89f_twigs-scale): BB_WIND_TWIGS_SIZE (the weight x SizeFactor)\n"
S_IN_NEW = (S_IN_OLD +
            "    bool fit = false;   ///< bbport (r89g_twigs-proof): BB_WIND_TWIGS_FIT (FitWeight in place of TwigWeight)\n")
S_FIT_OLD = "/// What a vertex knows of its mesh's box: the four keys (HeightKey of the lowest x, CrownKey of the\n"
S_FIT_NEW = r'''/// bbport (r89g_twigs-proof): the twig weight of BB_WIND_TWIGS_FIT for a vertex `hc` m above the camera (before
/// the lean's gust and front): Gain x FitShare x smoothstep(FitLo, FitHi; hc), x the size factor at hc + FitEye
/// when `sized`. The shaders do the same, operation for operation (hc = wy - the camera's y).
[[nodiscard]] inline float FitWeight(const float* view, float hc, bool sized = false) {
    const float weight = view[RippleD + 2] * (FitShare * Smooth01(hc, FitLo, FitInv));
    return sized ? weight * SizeFactor(hc + FitEye) : weight;
}

''' + S_FIT_OLD
S_CALL_OLD = ("        wt_use = tau > 0.0f ? TwigWeight(view, view[WindE + 2] + rx, view[WindE + 3] + rz, h, mesh,\n"
              "                                         twig->keys, twig->sized)\n"
              "                            : 0.0f;\n")
S_CALL_NEW = ("        wt_use = tau > 0.0f\n"
              "                     ? (twig->fit ? FitWeight(view, wy - view[WindA + 2], twig->sized) // bbport (r89g)\n"
              "                                  : TwigWeight(view, view[WindE + 2] + rx, view[WindE + 3] + rz, h, mesh,\n"
              "                                               twig->keys, twig->sized))\n"
              "                     : 0.0f;\n")

# ---------------------------------------------------------------- bbport_wind_twigs.h
N_ADD_OLD = "inline constexpr std::uint32_t SizeAdd = 100;\n"
N_ADD_NEW = (N_ADD_OLD + r'''/// bbport (r89g_twigs-proof): added as well with BB_WIND_TWIGS_FIT (the weight rule differs) and with
/// BB_WIND_TWIGS_PROOF (the lifter's shader counts and tints). Their sums with BinaryAdd and SizeAdd stay
/// apart from r112's hang version (the sway and hang versions differ by 11, these are multiples of 10).
inline constexpr std::uint32_t FitAdd = 10, ProofAdd = 20;
/// bbport (r89g_twigs-proof, TOOL): with BB_WIND_TWIGS_PROOF=1 every base slot has ProofSlotWords counters
/// behind the box keys (words from the start of the sway region's buffer): 0 vertices run, 1 finite, 2 of a tall
/// mesh (tau above 0), 3 old (box) rule weight above a tenth of the gain, 4 fit rule weight above it, 5 the weight
/// in use above it, 6 moved over 1 cm, 7 largest move (m, float bits), 8 gain, 9 lean flag, 10 ramp, 11 along
/// (m), 12 highest hc (m), 13 gust factor, 14 largest weight, 15 vertices over FitLo m above the camera.
inline constexpr std::uint32_t ProofSlotWords = 16;
inline constexpr std::uint32_t ProofAt = TwigEnd;
inline constexpr std::uint32_t ProofWords = W::BaseSlots * ProofSlotWords;
inline constexpr std::uint32_t ProofEnd = ProofAt + ProofWords;
inline constexpr std::uint32_t ProofBytes = ProofEnd * 4;
inline constexpr float ProofGain = 5.0f;       ///< a tree word's move is multiplied by this with the proof knob
inline constexpr std::uint32_t ProofLines = 6; ///< tree meshes named in one report
static_assert(ProofAt % 4 == 0 && ProofSlotWords % 4 == 0, "the counters are 16-byte aligned");
''')
N_KNOB_OLD = "    int size = 1;  ///< bbport (r89f): BB_WIND_TWIGS_SIZE 0 off, 1 the size factor\n};\n"
N_KNOB_NEW = ("    int size = 1;  ///< bbport (r89f): BB_WIND_TWIGS_SIZE 0 off, 1 the size factor\n"
              "    int fit = 1;   ///< bbport (r89g): BB_WIND_TWIGS_FIT 0 the box shape rule, 1 the fit rule\n"
              "    bool proof = false; ///< bbport (r89g, TOOL): BB_WIND_TWIGS_PROOF=1\n"
              "};\n")
N_SIG_OLD = "                                    const char* small = nullptr, const char* size = nullptr) {\n"
N_SIG_NEW = ("                                    const char* small = nullptr, const char* size = nullptr,\n"
             "                                    const char* fit = nullptr, const char* proof = nullptr) {\n")
N_PARSE_OLD = "    k.size = W::ParseNumber(size, 1.0f) >= 0.5f ? 1 : 0; // bbport (r89f_twigs-scale): 0 or 1, unreadable 1\n"
N_PARSE_NEW = (N_PARSE_OLD +
               "    k.fit = W::ParseNumber(fit, 1.0f) >= 0.5f ? 1 : 0;   // bbport (r89g_twigs-proof): 0 or 1, unreadable 1\n"
               "    k.proof = W::ParseNumber(proof, 0.0f) >= 0.5f;       // (TOOL) 1 only when asked\n")
N_ONCE_OLD = '                                       std::getenv("BB_WIND_TWIGS_SIZE"));\n'
N_ONCE_NEW = ('                                       std::getenv("BB_WIND_TWIGS_SIZE"),\n'
              '                                       std::getenv("BB_WIND_TWIGS_FIT"),\n'
              '                                       std::getenv("BB_WIND_TWIGS_PROOF"));\n')
N_ON_OLD = "[[nodiscard]] inline bool SizeOn() {\n    return KnobOnce().on && KnobOnce().size >= 1;\n}\n"
N_ON_NEW = (N_ON_OLD + r'''
/// bbport (r89g_twigs-proof): whether the twig weight is the fit rule (BB_WIND_TWIGS_FIT above 0, the twigs on).
/// Read once with the shaders (BinaryOffset).
[[nodiscard]] inline bool FitOn() {
    return KnobOnce().on && KnobOnce().fit >= 1;
}

/// bbport (r89g_twigs-proof, TOOL): whether the proof knob is on (BB_WIND_TWIGS_PROOF=1, the twigs on).
[[nodiscard]] inline bool ProofOn() {
    return KnobOnce().on && KnobOnce().proof;
}
''')
N_BUF_OLD = "    return On() ? std::max(region_bytes, TwigBytes) : region_bytes;\n"
N_BUF_NEW = ("    return On() ? std::max(region_bytes, ProofOn() ? ProofBytes : TwigBytes) // bbport (r89g_twigs-proof)\n"
             "                : region_bytes;\n")
N_INIT_OLD = "            sway_words[TwigAt + i] = W::ResetKey;\n        }\n"
N_INIT_NEW = (N_INIT_OLD +
              "        if (ProofOn()) { // bbport (r89g_twigs-proof, TOOL): the counters at 0\n"
              "            for (std::uint32_t i = 0; i < ProofWords; ++i) {\n"
              "                sway_words[ProofAt + i] = 0;\n"
              "            }\n"
              "        }\n")
N_RESET_OLD = "            words[TwigAt + slot * TwigSlotWords + i] = W::ResetKey;\n        }\n"
N_RESET_NEW = (N_RESET_OLD +
               "        if (ProofOn()) { // bbport (r89g_twigs-proof, TOOL): the slot's counters at 0\n"
               "            for (std::uint32_t i = 0; i < ProofSlotWords; ++i) {\n"
               "                words[ProofAt + slot * ProofSlotWords + i] = 0;\n"
               "            }\n"
               "        }\n")
N_OFF_OLD = "    return On() ? BinaryAdd + (SizeOn() ? SizeAdd : 0u) : 0u; // bbport (r89f_twigs-scale)\n"
N_OFF_NEW = ("    return On() ? BinaryAdd + (SizeOn() ? SizeAdd : 0u) + (FitOn() ? FitAdd : 0u) + // bbport (r89f, r89g)\n"
             "                      (ProofOn() ? ProofAdd : 0u)\n"
             "                : 0u;\n")
N_KNOWN_OLD = "        for (const std::uint32_t b : {0u, BinaryAdd, BinaryAdd + SizeAdd}) { // bbport (r89f)\n"
N_KNOWN_NEW = ("        for (const std::uint32_t b :\n"
               "             {0u, BinaryAdd, BinaryAdd + SizeAdd, BinaryAdd + FitAdd, BinaryAdd + ProofAdd,\n"
               "              BinaryAdd + SizeAdd + FitAdd, BinaryAdd + SizeAdd + ProofAdd, BinaryAdd + FitAdd + ProofAdd,\n"
               "              BinaryAdd + SizeAdd + FitAdd + ProofAdd}) { // bbport (r89f, r89g)\n")
N_END_OLD = "} // namespace BbWindTwigs\n"
N_END_NEW = r'''// bbport (r89g_twigs-proof): the fit rule's once line, and the proof knob's counters, verdict and texts.

/// The once line of BB_WIND_TWIGS_FIT (under 520 characters).
inline void FitOnceText(const Knob& k, char* out, std::size_t size) {
    if (k.fit >= 1) {
        std::snprintf(out, size,
                      "Wind twigs (r89g, BB_WIND_TWIGS_FIT=1): a tall mesh's twig weight is a rule of the vertex's "
                      "height over the camera (smoothstep %.0f to %.0f m, x%.2f, x the size factor at height + %.0f m "
                      "when BB_WIND_TWIGS_SIZE is on), not a shape in the mesh's world box (the box of a stream that "
                      "holds many trees is not one tree's)",
                      double(W::FitLo), double(W::FitHi), double(W::FitShare), double(W::FitEye));
    } else {
        std::snprintf(out, size,
                      "Wind twigs (r89g, BB_WIND_TWIGS_FIT=0): the box shape rule of r89d (weight from the vertex's "
                      "place in the mesh's world box)");
    }
}

/// The once line of BB_WIND_TWIGS_PROOF (TOOL; under 520 characters).
inline void ProofOnceText(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs (r89g, BB_WIND_TWIGS_PROOF=1, TOOL): a tree word's move x%.0f; the vertex outputs of a "
                  "vertex with a twig weight pulled toward yellow by it (lifter shaders; the game's outputs are "
                  "normals and UV pairs, so a stained twig, not a clean yellow); %u counters a mesh slot (%u bytes of "
                  "the sway buffer); a 'Wind twigs proof (r89g)' line per tree mesh (at most %u) every %u frames "
                  "with a verdict",
                  double(ProofGain), ProofSlotWords, ProofBytes, ProofLines, unsigned(W::ReportFrames));
}

/// The GPU's counters of one base slot (see ProofSlotWords); the floats are as the shader stored them.
struct ProofCounts {
    std::uint32_t verts = 0, fin = 0, tall = 0, old_w = 0, fit_w = 0, used_w = 0, moved = 0, high = 0;
    float move_max = 0.0f, gain = 0.0f, lean = 0.0f, ramp = 0.0f, along = 0.0f, gust = 0.0f, hc_max = 0.0f,
          w_max = 0.0f;
};

/// The counters of `slot` read from the sway region's words (a volatile read: the GPU writes them; at most 16
/// words, at a report). A slot out of range reads as all 0.
[[nodiscard]] inline ProofCounts ReadProof(const std::uint32_t* words, std::uint32_t slot) {
    ProofCounts c;
    if (words == nullptr || slot >= W::BaseSlots) {
        return c;
    }
    const volatile std::uint32_t* const v = words + ProofAt + slot * ProofSlotWords;
    const auto number = [&](std::uint32_t k) { return std::uint32_t(v[k]); };
    const auto real = [&](std::uint32_t k) {
        const std::uint32_t bits = v[k];
        float f = 0.0f;
        std::memcpy(&f, &bits, sizeof(f));
        return f;
    };
    c.verts = number(0);
    c.fin = number(1);
    c.tall = number(2);
    c.old_w = number(3);
    c.fit_w = number(4);
    c.used_w = number(5);
    c.moved = number(6);
    c.move_max = real(7);
    c.gain = real(8);
    c.lean = real(9);
    c.ramp = real(10);
    c.along = real(11);
    c.hc_max = real(12);
    c.gust = real(13);
    c.w_max = real(14);
    c.high = number(15);
    return c;
}

/// The slot's counters back to 0 (after a report).
inline void ClearProof(std::uint32_t* words, std::uint32_t slot) {
    if (words == nullptr || slot >= W::BaseSlots) {
        return;
    }
    volatile std::uint32_t* const v = words + ProofAt + slot * ProofSlotWords;
    for (std::uint32_t k = 0; k < ProofSlotWords; ++k) {
        v[k] = 0;
    }
}

/// What the counters point at, the first break in the order the shader meets them (a string literal).
[[nodiscard]] inline const char* ProofVerdict(const ProofCounts& c) {
    if (c.verts == 0) {
        return "no vertex counted: the twig code of this mesh's shader did not run (a draw on a pipeline without "
               "it, or the recompiler's shader, which has no counters)";
    }
    if (c.fin < c.verts / 2) {
        return "most vertices are not finite: the world position rebuilt from the clip position is wrong";
    }
    if (c.tall == 0) {
        return "tau is 0: the mesh's height from its keys is under 2 m";
    }
    if (!(c.ramp > 0.0f)) {
        return "ramp 0: the sway word's ramp byte is 0";
    }
    if (!(c.gain > 0.0f)) {
        return "gain 0: the view's twig gain is 0";
    }
    if (!(c.lean > 0.0f)) {
        return "lean 0: the view's lean flag is 0";
    }
    if (c.used_w == 0) {
        return "weight 0: no vertex has a twig weight above a tenth of the gain (the rule puts it on no vertex)";
    }
    if (!(c.move_max >= 0.001f)) {
        return "weight above 0 but the move is under 1 mm: the wind's amplitude at these vertices is 0";
    }
    return "OK: the shader moves vertices (see the largest move)";
}

/// One mesh's proof line (under 760 characters): the CPU's draw counts (`draws` of the stream since the last
/// line, `patched` of them on pipelines with the sway bit, `pipelines` distinct ones, at most 4; `verts_each`
/// the stream's vertex count, 0 unknown), the GPU's counters and the verdict.
inline void ProofLine(const ProofCounts& c, std::uint32_t slot, std::uint64_t draws, std::uint64_t patched,
                      std::uint32_t pipelines, std::uint32_t verts_each, char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    const double expected = double(draws) * double(verts_each);
    const double ratio = expected > 0.0 ? double(c.verts) / expected : 0.0;
    std::snprintf(out, size,
                  "Wind twigs proof (r89g): slot %u: %llu draws (%llu on pipelines with the sway bit, %u pipelines) "
                  "x %u vertices; shader counted %u vertices (%.2f of draws x vertices), %u finite, %u of a tall mesh; "
                  "weight above a tenth of the gain: old rule %u, fit rule %u, in use %u; moved over 1 cm %u; read "
                  "gain %.3f lean %.1f ramp %.2f along %.3f m gust %.2f; highest %.1f m over the camera (%u over "
                  "%.0f m), largest weight %.3f, largest move %.1f cm; verdict: %s",
                  slot, n(draws), n(patched), pipelines, verts_each, c.verts, ratio, c.fin, c.tall, c.old_w, c.fit_w,
                  c.used_w, c.moved, double(c.gain), double(c.lean), double(c.ramp), double(c.along), double(c.gust),
                  double(c.hc_max), c.high, double(W::FitLo), double(c.w_max), double(c.move_max * 100.0f),
                  ProofVerdict(c));
}

''' + N_END_OLD

# ---------------------------------------------------------------- the two shader emitters
E_FIT_OLD = "        wt_use = ctx.OpSelect(f32_type, ctx.OpFOrdGreaterThan(bool_type, tau, zero), twig, zero);\n"
E_FIT_NEW = (
    "        if (BbWindTwigs::FitOn()) { // bbport (r89g_twigs-proof): BbWindSway::FitWeight, the vertex's height over the camera\n"
    "            const Id fit_h = sub(wy, comp(wind_a, 2u));\n"
    "            Id fit = mul(comp(lean_d, 2u), mul(f(W::FitShare), smooth01(fit_h, W::FitLo, W::FitInv)));\n"
    "            if (BbWindTwigs::SizeOn()) {\n"
    "                fit = mul(fit, ctx.OpFClamp(f32_type, mul(add(fit_h, f(W::FitEye)), f(W::SizeInv)), f(1.0f),\n"
    "                                            f(W::SizeMax)));\n"
    "            }\n"
    "            twig = fit;\n"
    "        }\n" + E_FIT_OLD)
E_W_OLD = "    const Id w = mul(add(wb_use, mul(mul(tau, lean), sub(wt_use, wb_use))), ramp);\n"
E_W_NEW = (
    "    Id w = mul(add(wb_use, mul(mul(tau, lean), sub(wt_use, wb_use))), ramp);\n"
    "    if (BbWindTwigs::ProofOn()) { // bbport (r89g_twigs-proof, TOOL): a tree word's move x ProofGain\n"
    "        w = ctx.OpSelect(f32_type,\n"
    "                         ctx.OpINotEqual(bool_type,\n"
    "                                         ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(BbWindTwigs::TreeBit)),\n"
    "                                         ctx.u32_zero_value),\n"
    "                         mul(w, f(BbWindTwigs::ProofGain)), w);\n"
    "    }\n")

L_DECL_OLD = "    u32 wt_use = wt, wb_use = wb;\n"
L_DECL_NEW = L_DECL_OLD + "    u32 proof_old = 0, proof_fit = 0, proof_hc = 0; // bbport (r89g_twigs-proof)\n"
L_FIT_OLD = "        wt_use = Select(FCmp(O(spv::Op::OpFOrdGreaterThan), tau, zero), twig, zero);\n"
L_FIT_NEW = (
    "        if (BbWindTwigs::FitOn() || BbWindTwigs::ProofOn()) { // bbport (r89g_twigs-proof): the fit rule, as EmitVertexSway\n"
    "            const u32 fit_h = FSub(wy, comp(wind_a, 2));\n"
    "            u32 fit = FMul(comp(lean_d, 2), FMul(CF(W::FitShare), smooth01(fit_h, W::FitLo, W::FitInv)));\n"
    "            if (BbWindTwigs::SizeOn()) {\n"
    "                fit = FMul(fit, clamp_f(FMul(FAdd(fit_h, CF(W::FitEye)), CF(W::SizeInv)), CF(1.0f), CF(W::SizeMax)));\n"
    "            }\n"
    "            proof_old = twig;\n"
    "            proof_fit = fit;\n"
    "            proof_hc = fit_h;\n"
    "            if (BbWindTwigs::FitOn()) {\n"
    "                twig = fit;\n"
    "            }\n"
    "        }\n" + L_FIT_OLD)
L_W_OLD = "    const u32 w = FMul(FAdd(wb_use, FMul(FMul(tau, lean), FSub(wt_use, wb_use))), ramp);\n"
L_W_NEW = (
    "    u32 w = FMul(FAdd(wb_use, FMul(FMul(tau, lean), FSub(wt_use, wb_use))), ramp);\n"
    "    if (BbWindTwigs::ProofOn()) { // bbport (r89g_twigs-proof, TOOL): a tree word's move x ProofGain\n"
    "        w = Select(ICmp(O(spv::Op::OpINotEqual), IOp(O(spv::Op::OpBitwiseAnd), word, CU(BbWindTwigs::TreeBit)), CU(0)),\n"
    "                   FMul(w, CF(BbWindTwigs::ProofGain)), w);\n"
    "    }\n")
L_END_OLD = "    EmitVoid(O(spv::Op::OpBranch), {sway_merge});\n    Open(sway_merge);\n}\n"
L_END_NEW = r'''    if (BbWindTwigs::ProofOn()) { // bbport (r89g_twigs-proof, TOOL): the per-slot counters and the tint
        namespace P = BbWindTwigs;
        const u32 device = CU(u32(spv::Scope::Device));
        const u32 proof_base = scaled(at(region, u64(P::ProofAt) * 4u), field(3, 10), u64(P::ProofSlotWords) * 4u);
        const auto word_ptr = [&](u32 k) {
            return Emit(O(spv::Op::OpConvertUToPtr), ptr_u32, Ty::None, {at(proof_base, u64(k) * 4u)});
        };
        const auto flag = [&](u32 cond) { return Select(cond, CU(1), CU(0)); };
        const auto count = [&](u32 k, u32 value) { // an atomic add of 0 or 1 (or of 1)
            const u32 prev = Emit(O(spv::Op::OpAtomicIAdd), t_u32, Ty::U32, {word_ptr(k), device, CU(0), value});
            nodes[m.NodeOf(prev)].effect = true;
        };
        const auto biggest = [&](u32 k, u32 value) { // an atomic maximum of a float of 0 or more (its bits order)
            const u32 bits = Emit(O(spv::Op::OpBitcast), t_u32, Ty::U32, {Ext(GLSLstd450FMax, t_f32, Ty::F32, {value, zero})});
            const u32 prev = Emit(O(spv::Op::OpAtomicUMax), t_u32, Ty::U32, {word_ptr(k), device, CU(0), bits});
            nodes[m.NodeOf(prev)].effect = true;
        };
        const auto keep = [&](u32 k, u32 value) { // a plain store: every vertex of the slot writes the same value
            EmitVoid(O(spv::Op::OpStore), {word_ptr(k), Emit(O(spv::Op::OpBitcast), t_u32, Ty::U32, {value}), aligned, 4}, 12);
        };
        const u32 gain = comp(lean_d, 2);
        const u32 tenth = FMul(gain, CF(0.1f));
        const auto over = [&](u32 value) { return flag(FCmp(O(spv::Op::OpFOrdGreaterThan), value, tenth)); };
        const u32 move = Ext(GLSLstd450Sqrt, t_f32, Ty::F32, {FAdd(FMul(ddx_all, ddx_all), FMul(ddz_all, ddz_all))});
        count(0, CU(1));
        count(1, flag(fin));
        count(2, flag(FCmp(O(spv::Op::OpFOrdGreaterThan), tau, zero)));
        count(3, over(proof_old));
        count(4, over(proof_fit));
        count(5, over(wt_use));
        count(6, flag(FCmp(O(spv::Op::OpFOrdGreaterThan), move, CF(0.01f))));
        count(15, flag(FCmp(O(spv::Op::OpFOrdGreaterThan), proof_hc, CF(W::FitLo))));
        biggest(7, move);
        biggest(12, proof_hc);
        biggest(14, wt_use);
        keep(8, gain);
        keep(9, lean);
        keep(10, ramp);
        keep(11, along);
        keep(13, g);
        // the tint: every output attribute of a vertex with a twig weight toward (1, 1, 0) by weight / gain
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
    }
''' + L_END_OLD

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
F_NOTE_OLD = "// bbport (r89_wind-foliage-sway): the sway word (BbWindSway::PackWord) of a skinned draw of a\n"
F_NOTE_NEW = r'''// bbport (r89g_twigs-proof, TOOL): the draws of each twig-taken stream since the last proof lines: how many, how
// many on a pipeline whose key has the sway bit, on how many distinct pipelines (at most 4 are told apart).
struct TwigProofDraws {
    u64 draws = 0;
    u64 patched = 0;
    u32 pipelines = 0;
    std::array<const void*, 4> seen{};
};
static std::unordered_map<u64, TwigProofDraws> twig_proof_draws;

static void TwigProofNote(u64 stream, const GraphicsPipeline* pipeline) {
    TwigProofDraws& d = twig_proof_draws[stream];
    ++d.draws;
    d.patched += (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::Sway) != 0 ? 1 : 0;
    bool known = false;
    for (u32 i = 0; i < d.pipelines; ++i) {
        known = known || d.seen[i] == pipeline;
    }
    if (!known && d.pipelines < d.seen.size()) {
        d.seen[d.pipelines++] = pipeline;
    }
}

''' + F_NOTE_OLD
F_CALL_OLD = "    if (tree) { // bbport (r89d_tree-twigs): its word (WindTwigWord), counted in its line\n"
F_CALL_NEW = (
    "    if (tree && BbWindTwigs::ProofOn()) { // bbport (r89g_twigs-proof, TOOL): which pipelines draw it\n"
    "        TwigProofNote(positions, pipeline);\n"
    "    }\n" + F_CALL_OLD)
F_REPORT_OLD = ('        BbReport::Printf("%s\\n", size_text);\n'
                "    }\n"
                "    twig_stats = {};\n")
F_REPORT_NEW = (
    '        BbReport::Printf("%s\\n", size_text);\n'
    "    }\n"
    "    if (BbWindTwigs::ProofOn()) { // bbport (r89g_twigs-proof, TOOL): a proof line per tree mesh, then the counters at 0\n"
    "        u32 lines = 0;\n"
    "        sway_slots.ForEachInUse(object_motion->Frame(), [&](u32 slot, u64 stream, u32) {\n"
    "            const BbWindTwigs::Entry* const entry = twig_book.Find(stream);\n"
    "            if (entry == nullptr || entry->verdict != BbWindTwigs::Verdict::Tree ||\n"
    "                lines >= BbWindTwigs::ProofLines) {\n"
    "                return;\n"
    "            }\n"
    "            ++lines;\n"
    "            const BbWindTwigs::SmallInfo* const info = twig_book.FindInfo(stream);\n"
    "            const auto found = twig_proof_draws.find(stream);\n"
    "            const TwigProofDraws seen = found != twig_proof_draws.end() ? found->second : TwigProofDraws{};\n"
    "            char proof_text[768];\n"
    "            BbWindTwigs::ProofLine(BbWindTwigs::ReadProof(words, slot), slot, seen.draws, seen.patched,\n"
    "                                   seen.pipelines, info != nullptr ? info->verts : 0u, proof_text,\n"
    "                                   sizeof(proof_text));\n"
    '            BbReport::Printf("%s\\n", proof_text);\n'
    "            BbWindTwigs::ClearProof(words, slot);\n"
    "        });\n"
    "        twig_proof_draws.clear();\n"
    "    }\n"
    "    twig_stats = {};\n")
F_ONCE_OLD = ('            BbReport::Printf("%s\\n", size_once);\n'
              "        }\n")
F_ONCE_NEW = (F_ONCE_OLD +
              "        if (BbWindTwigs::On()) { // bbport (r89g_twigs-proof): the fit rule's line, and the proof knob's\n"
              "            char fit_once[640];\n"
              "            BbWindTwigs::FitOnceText(BbWindTwigs::KnobOnce(), fit_once, sizeof(fit_once));\n"
              '            BbReport::Printf("%s\\n", fit_once);\n'
              "            if (BbWindTwigs::ProofOn()) {\n"
              "                BbWindTwigs::ProofOnceText(fit_once, sizeof(fit_once));\n"
              '                BbReport::Printf("%s\\n", fit_once);\n'
              "            }\n"
              "        }\n")

# ---------------------------------------------------------------- tests
T_ANCHOR = '               "SizeReportText");\n    }\n\n'
T_BLOCK = r'''    // bbport (r89g_twigs-proof): the fit weight and its place in Displace, the knobs, the versions, the proof
    // counters, the verdicts and the texts.
    {
        namespace T = BbWindTwigs;
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const auto view = TwigViewOf(c, Wind(5.0, 225.0f, 1.5f), ripple, 1.0f);
        const float gain = view[RippleD + 2];
        Expect(FitWeight(view.data(), -5.0f) == 0.0f && FitWeight(view.data(), 0.0f) == 0.0f &&
                   FitWeight(view.data(), FitLo) == 0.0f && FitWeight(view.data(), FitLo, true) == 0.0f,
               "FitWeight: 0 up to FitLo m over the camera");
        Expect(Near(FitWeight(view.data(), FitHi), double(gain) * double(FitShare), 1e-6) &&
                   Near(FitWeight(view.data(), 40.0f), double(gain) * double(FitShare), 1e-6),
               "FitWeight: the gain x FitShare from FitHi m up, unsized");
        Expect(Near(FitWeight(view.data(), FitHi, true),
                    double(gain) * double(FitShare) * double(SizeFactor(FitHi + FitEye)), 1e-6) &&
                   Near(FitWeight(view.data(), 20.0f, true),
                        double(gain) * double(FitShare) * double(SizeFactor(20.0f + FitEye)), 1e-6),
               "FitWeight sized: x the size factor at hc + FitEye");
        bool rises = true;
        float last_weight = 0.0f;
        for (int i = 0; i <= 80; ++i) {
            const float w = FitWeight(view.data(), 0.5f * float(i), true);
            rises = rises && w >= last_weight;
            last_weight = w;
        }
        Expect(rises, "FitWeight sized never steps down as the height rises");
        // the cause: a stream whose box is a stand's (45 x 39 m, 37 m) gives r89f's box rule no weight on its centre
        // line, 14 m up (12 m over the camera); the fit rule moves that vertex
        const std::array<double, 3> mid = {10.0 - std::sin(0.3) * 7.0, 0.0, 20.0 - std::cos(0.3) * 7.0};
        const TreeBox stand = {0.0f, 37.0f, float(mid[0] - 22.5), float(mid[0] + 22.5), float(mid[2] - 19.5),
                               float(mid[2] + 19.5)};
        const std::array<double, 3> limb = {mid[0], 14.0, mid[2]};
        const auto peak_of = [&](bool use_fit) {
            double peak = 0.0;
            Ripple wind_ripple;
            for (int i = 0; i < 600; ++i) {
                const auto v = TwigViewOf(c, Gusty(0.1 * i, 225.0f, 4.0f, 0.5f), wind_ripple, 1.0f);
                const auto clip = ClipOf(c, limb);
                const auto before = WorldOf(v.data(), clip);
                TwigIn in = TwigInOf(stand, true);
                in.sized = true;
                in.fit = use_fit;
                const auto after = WorldOf(v.data(), Displace(v.data(), clip, HeightKey(stand.base), 1.0f, nullptr,
                                                              CrownKey(stand.crown), nullptr, &in));
                peak = std::max(peak, std::hypot(after[0] - before[0], after[2] - before[2]));
            }
            return peak;
        };
        const double box_peak = peak_of(false);
        const double fit_peak = peak_of(true);
        Expect(box_peak < 1e-6, "the box rule leaves a vertex on a stand's centre line still (the break)");
        Expect(fit_peak > 0.02 && fit_peak < 1.0, "the fit rule moves it by a few cm to tens of cm at 4 m/s");
        // the knobs and the versions
        const T::Knob dflt = T::ParseKnob(nullptr, nullptr, true, true);
        const T::Knob asked = T::ParseKnob(nullptr, nullptr, true, true, nullptr, nullptr, "0", "1");
        const T::Knob junk = T::ParseKnob(nullptr, nullptr, true, true, nullptr, nullptr, "x", "x");
        Expect(dflt.fit == 1 && !dflt.proof && asked.fit == 0 && asked.proof && junk.fit == 1 && !junk.proof,
               "BB_WIND_TWIGS_FIT: 0 or 1, default 1; BB_WIND_TWIGS_PROOF: default off");
        Expect(T::KnownVersion(2131, 11, 21, 1000) && T::KnownVersion(2141, 11, 21, 1000) &&
                   T::KnownVersion(2121, 11, 21, 1000) && T::KnownVersion(2031, 11, 21, 1000) &&
                   T::KnownVersion(3141, 11, 21, 1000) && !T::KnownVersion(2201, 11, 21, 1000) &&
                   T::FitAdd == 10 && T::ProofAdd == 20,
               "the saved versions with the fit and proof offsets are known; no other");
        // the counters, the verdicts, the line
        std::vector<std::uint32_t> words(T::ProofEnd, 0u);
        const std::uint32_t slot = 5;
        std::uint32_t* const at = words.data() + T::ProofAt + slot * T::ProofSlotWords;
        const auto bits = [](float v) {
            std::uint32_t u = 0;
            std::memcpy(&u, &v, sizeof(u));
            return u;
        };
        at[0] = 100; at[1] = 100; at[2] = 100; at[3] = 0; at[4] = 60; at[5] = 60; at[6] = 40; at[15] = 70;
        at[7] = bits(0.123f); at[8] = bits(0.3f); at[9] = bits(1.0f); at[10] = bits(1.0f);
        at[11] = bits(0.2f); at[12] = bits(18.5f); at[13] = bits(0.9f); at[14] = bits(0.4f);
        const T::ProofCounts pc = T::ReadProof(words.data(), slot);
        Expect(pc.verts == 100 && pc.fin == 100 && pc.tall == 100 && pc.old_w == 0 && pc.fit_w == 60 &&
                   pc.used_w == 60 && pc.moved == 40 && pc.high == 70 && Near(pc.move_max, 0.123, 1e-6) &&
                   Near(pc.gain, 0.3, 1e-6) && Near(pc.lean, 1.0, 1e-6) && Near(pc.ramp, 1.0, 1e-6) &&
                   Near(pc.along, 0.2, 1e-6) && Near(pc.hc_max, 18.5, 1e-5) && Near(pc.gust, 0.9, 1e-6) &&
                   Near(pc.w_max, 0.4, 1e-6),
               "ReadProof reads the slot's 16 words");
        Expect(T::ReadProof(words.data(), slot + 1).verts == 0 && T::ReadProof(words.data(), BaseSlots).verts == 0 &&
                   T::ReadProof(nullptr, 0).verts == 0,
               "ReadProof: another slot, a slot out of range and no words read as 0");
        Expect(std::strstr(T::ProofVerdict(pc), "OK:") != nullptr, "ProofVerdict: counts that move read OK");
        const auto verdict_has = [&](const char* what, const auto& change) {
            T::ProofCounts k = pc;
            change(k);
            return std::strstr(T::ProofVerdict(k), what) != nullptr;
        };
        Expect(verdict_has("no vertex counted", [](T::ProofCounts& k) { k.verts = 0; }) &&
                   verdict_has("not finite", [](T::ProofCounts& k) { k.fin = 10; }) &&
                   verdict_has("tau is 0", [](T::ProofCounts& k) { k.tall = 0; }) &&
                   verdict_has("ramp 0", [](T::ProofCounts& k) { k.ramp = 0.0f; }) &&
                   verdict_has("gain 0", [](T::ProofCounts& k) { k.gain = 0.0f; }) &&
                   verdict_has("lean 0", [](T::ProofCounts& k) { k.lean = 0.0f; }) &&
                   verdict_has("weight 0", [](T::ProofCounts& k) { k.used_w = 0; }) &&
                   verdict_has("under 1 mm", [](T::ProofCounts& k) { k.move_max = 0.0001f; }),
               "ProofVerdict names the first break in the shader's order");
        char line[800];
        T::ProofLine(pc, slot, 600, 600, 1, 156641, line, sizeof(line));
        Expect(std::strstr(line, "slot 5:") != nullptr && std::strstr(line, "600 draws (600 on pipelines") != nullptr &&
                   std::strstr(line, "verdict: OK:") != nullptr && std::strlen(line) < 760,
               "ProofLine");
        T::ClearProof(words.data(), slot);
        Expect(T::ReadProof(words.data(), slot).verts == 0 && words[T::ProofAt + slot * T::ProofSlotWords + 7] == 0,
               "ClearProof");
        T::ClearProof(words.data(), BaseSlots);
        Expect(words[T::ProofEnd - 1] == 0 && T::ProofBytes == T::ProofEnd * 4 && T::ProofSlotWords == 16,
               "ClearProof out of range writes nothing; the counters' size");
        char once[640];
        T::FitOnceText(dflt, once, sizeof(once));
        Expect(std::strstr(once, "BB_WIND_TWIGS_FIT=1") != nullptr && std::strstr(once, "smoothstep 3 to 9 m") != nullptr &&
                   std::strlen(once) < 520,
               "FitOnceText");
        T::FitOnceText(asked, once, sizeof(once));
        Expect(std::strstr(once, "BB_WIND_TWIGS_FIT=0") != nullptr, "FitOnceText with FIT=0");
        T::ProofOnceText(once, sizeof(once));
        Expect(std::strstr(once, "BB_WIND_TWIGS_PROOF=1, TOOL") != nullptr && std::strlen(once) < 520, "ProofOnceText");
    }

'''
T_NEW = T_ANCHOR + T_BLOCK

# ---------------------------------------------------------------- README
README_ANCHOR = ("the tallest tree and its tip's move at the wind now. No GPU memory, no CPU work per draw; not measured "
                "| `1` |\n")
README_ROWS = (
    "| `BB_WIND_TWIGS_FIT` | How a tall mesh's twig weight is found (with the `BB_WIND_TWIGS`, `BB_WIND_TWIGS_SIZE` "
    "rows; r89g): `0` the box shape rule of r89d (weight from the vertex's place in the mesh's world box: the centre "
    "line and the low parts stay still), `1` (default) a rule of the vertex's own height above the camera: smoothstep "
    "from 3 m to 9 m, times 0.6, times the size factor of `BB_WIND_TWIGS_SIZE` taken at that height plus 2 m (the "
    "camera stands about 2 m above the ground). Why: the box keys of a stream that holds a stand, whose pieces come and "
    "go, measured 4, 37 and 42 m of height for the same 156641-vertex stream in one run, and the box rule's fractions "
    "of that put the weight on no visible vertex, so the big graveyard trees did not move at all. What it costs: the "
    "upper trunk moves with the crown (as a real tree's does), a camera high above the trees (the free camera) leaves "
    "them still, a tree on a hill moves from lower on its trunk. Read once with the shaders (cache version +10). Log: "
    "once `Wind twigs (r89g, BB_WIND_TWIGS_FIT=...)`. No GPU memory, one smoothstep a twig vertex; not measured "
    "| `1` |\n"
    "| `BB_WIND_TWIGS_PROOF` | TOOL (a test aid, r89g; goes to the test-tools branch): `1` a tree word's move is x5, "
    "the vertex outputs of every vertex with a twig weight are pulled toward yellow by the weight (the game's own "
    "outputs of the tree shader are normals and UV pairs, so the tint shows as a stained twig, not a clean yellow), and "
    "the lifter's shader counts per mesh slot: vertices run, finite, of a tall mesh, weight above a tenth of the gain "
    "by the box rule, the fit rule and the one in use, moved over 1 cm, the largest move and weight, the highest "
    "vertex over the camera, and the gain, lean flag, ramp, along and gust it read from its view words. Every 600 "
    "frames one `Wind twigs proof (r89g)` line per tree mesh (at most 6) with the draws, the pipelines with the sway "
    "bit, the counts and a verdict (no vertex counted, not finite, tau 0, ramp 0, gain 0, lean 0, weight 0, move under "
    "1 mm, or OK); the counters are cleared after each line. The recompiler's fallback shader counts nothing (the "
    "line then says no vertex counted). With it on: 11 atomic operations a twig vertex and 114752 bytes of the sway "
    "buffer; off: nothing is emitted | `0` |\n")
README_NEW = README_ANCHOR + README_ROWS

EDITS = {
    HEADER: [(S_CONST_OLD, S_CONST_NEW), (S_IN_OLD, S_IN_NEW), (S_FIT_OLD, S_FIT_NEW), (S_CALL_OLD, S_CALL_NEW)],
    NEWH: [(N_ADD_OLD, N_ADD_NEW), (N_KNOB_OLD, N_KNOB_NEW), (N_SIG_OLD, N_SIG_NEW), (N_PARSE_OLD, N_PARSE_NEW),
           (N_ONCE_OLD, N_ONCE_NEW), (N_ON_OLD, N_ON_NEW), (N_BUF_OLD, N_BUF_NEW), (N_INIT_OLD, N_INIT_NEW),
           (N_RESET_OLD, N_RESET_NEW), (N_OFF_OLD, N_OFF_NEW), (N_KNOWN_OLD, N_KNOWN_NEW), (N_END_OLD, N_END_NEW)],
    EMIT: [(E_FIT_OLD, E_FIT_NEW), (E_W_OLD, E_W_NEW)],
    LIFT: [(L_DECL_OLD, L_DECL_NEW), (L_FIT_OLD, L_FIT_NEW), (L_W_OLD, L_W_NEW), (L_END_OLD, L_END_NEW)],
    EFFECTS: [(F_NOTE_OLD, F_NOTE_NEW), (F_CALL_OLD, F_CALL_NEW), (F_REPORT_OLD, F_REPORT_NEW),
              (F_ONCE_OLD, F_ONCE_NEW)],
    TEST: [(T_ANCHOR, T_NEW)],
    README: [(README_ANCHOR, README_NEW)],
}

CHECKS = {
    HEADER: [("inline float FitWeight(", 1), ("bool fit = false;", 1), ("twig->fit ? FitWeight(", 1),
             ("FitLo = 3.0f, FitHi = 9.0f, FitShare = 0.6f, FitEye = 2.0f;", 1)],
    NEWH: [("inline bool FitOn()", 1), ("inline bool ProofOn()", 1), ("inline ProofCounts ReadProof(", 1),
           ("inline void ClearProof(", 1), ("inline const char* ProofVerdict(", 1), ("inline void ProofLine(", 1),
           ("inline void FitOnceText(", 1), ("inline void ProofOnceText(", 1), ('std::getenv("BB_WIND_TWIGS_FIT")', 1),
           ('std::getenv("BB_WIND_TWIGS_PROOF")', 1), ("FitAdd = 10, ProofAdd = 20;", 1),
           ("(FitOn() ? FitAdd : 0u)", 1), ("ProofOn() ? ProofBytes : TwigBytes", 1)],
    EMIT: [("if (BbWindTwigs::FitOn()) {", 1), ("if (BbWindTwigs::ProofOn()) {", 1), ("W::FitInv", 1)],
    LIFT: [("BbWindTwigs::FitOn() || BbWindTwigs::ProofOn()", 1), ("if (BbWindTwigs::ProofOn()) {", 2),
           ("OpAtomicUMax", 1), ("OpAtomicIAdd", 1), ("W::FitInv", 1)],
    EFFECTS: [("TwigProofNote(positions, pipeline);", 1), ("BbWindTwigs::ProofLine(", 1), ("BbWindTwigs::FitOnceText(", 1),
              ("BbWindTwigs::ProofOnceText(", 1), ("struct TwigProofDraws {", 1)],
    TEST: [("FitWeight(", 9), ("wind-sway-test: ok", 1)],
    README: [("| `BB_WIND_TWIGS_FIT` |", 1), ("| `BB_WIND_TWIGS_PROOF` |", 1), ("| `BB_WIND_TWIGS_SIZE` |", 1)],
}

ORDER = {
    NEWH: ["inline constexpr std::uint32_t SizeAdd", "inline constexpr std::uint32_t FitAdd", "int size = 1;", "int fit = 1;",
           "inline bool SizeOn()", "inline bool FitOn()", "inline bool ProofOn()", "inline std::uint32_t BufferBytes(",
           "inline std::uint32_t BinaryOffset()", "inline void SizeReportText(", "inline void FitOnceText(",
           "inline void ProofOnceText(", "struct ProofCounts {", "inline ProofCounts ReadProof(", "inline void ClearProof(",
           "inline const char* ProofVerdict(", "inline void ProofLine(", "} // namespace BbWindTwigs"],
    HEADER: ["inline constexpr float TwigHalfFloor", "FitLo = 3.0f", "inline float SizeFactor(", "inline float Smooth01(",
             "inline float FitWeight(", "struct TwigIn {", "inline float TwigWeight(", "inline std::array<float, 4> Displace("],
}

# Numbers written twice: the header's constants and the README rows' text.
FIT_ROW = "| `BB_WIND_TWIGS_FIT`"
PROOF_ROW = "| `BB_WIND_TWIGS_PROOF`"
TIES = [(HEADER, "FitLo = 3.0f, FitHi = 9.0f, FitShare = 0.6f, FitEye = 2.0f", FIT_ROW, "from 3 m to 9 m, times 0.6"),
        (HEADER, "FitLo = 3.0f, FitHi = 9.0f, FitShare = 0.6f, FitEye = 2.0f", FIT_ROW, "that height plus 2 m"),
        (NEWH, "FitAdd = 10, ProofAdd = 20", FIT_ROW, "cache version +10"),
        (NEWH, "ProofSlotWords = 16", PROOF_ROW, "114752 bytes"),
        (NEWH, "TwigAt = 8208", PROOF_ROW, "114752 bytes")]


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
    for path, const, row_start, value in TIES:
        rows = "\n".join(l for l in texts[README].split("\n") if l.startswith(row_start))
        if texts[path].count(const) != 1 or value not in rows:
            raise SystemExit("tie check: %r against the README row %r (%r)" % (const, row_start, value))
    # the buffer size in the README row: ProofEnd * 4 from the header's own numbers
    two = 8208 + 1024 * 4  # TwigEnd
    if (two + 1024 * 16) * 4 != 114752:
        raise SystemExit("the README's byte count is not ProofBytes")
    for edits in EDITS.values():
        for old, new in edits:
            if not all(ord(c) < 128 for c in new) or "\r" in new:
                raise SystemExit("new text must be ASCII with LF in the script")
            if any(x in new for x in ("C:/", "G:/", "<user>", "Temp/claude")):
                raise SystemExit("a local path in the patch's text")
    # a macro-named identifier (far, near) must not appear as a variable in the new C++ text
    for path in (NEWH, EFFECTS, HEADER, LIFT, EMIT, TEST):
        for bad in ("float far ", "float far;", " far =", " far;", ".far,", ".far)", " near =", "float near"):
            if bad in "".join(new for _, new in EDITS[path]):
                raise SystemExit("%s: the name %r is a macro on some Windows headers" % (path, bad))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R89G_ROOT)" % ROOT)
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
            tmp = full + ".r89gtmp"
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
        tmp = full + ".r89gtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
