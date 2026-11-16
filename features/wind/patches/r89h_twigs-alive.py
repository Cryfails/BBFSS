# r89h_twigs-alive: FEATURE fix on top of r89d, r89e, r89f and r89g (wind work), with TOOL additions to r89g's proof
# knob. One new knob, only with BB_WIND=1, the twigs on (BB_WIND_TWIGS above 0) and the fit rule on (BB_WIND_TWIGS_FIT=1):
#   BB_WIND_TWIGS_PUSH   (FEATURE; 0 = r89g's rule exactly, 1 = the push rule, default 1)
# Wind off, twigs off, FIT=0 and PUSH=0 leave every shader and every code path as r89g had them (see OFF).
#
# THE OWNER: "I think if the small branches on the trees moved slightly due to wind that would look great"; "The foliage
# moving should not wave but move in the direction of the wind and it should be not as fast unless the wind is really
# blowing"; "The wave should just be very subtle".
# THE REPORT OF BUILD 45: the shader moves the vertices (proof line: verdict OK), but pictures 0.25 s apart, even the x5
# proof pair, show no branch edge moving; only a faint steady lean shows against the knob off.
#
# WHAT THE NUMBERS SAY (r89h_twin.py, a Python twin of the shaders' math on r89g's unit-test limb: 12 m over the camera,
# 4 m/s, gust factor 1): r89g's along rule (g D (LeanRest + E), E the front envelope 0..2) already moves that limb
# between 1.3 and 11.3 cm with a change of 2.9 cm (mean) and 10.1 cm (largest) over 0.5 s. So the SHAPE of r89g's rule
# is not near-constant in the model; the model cannot say what hides the motion in the game. Two readings of the build-45
# log, from code and log only (no game run for this patch):
#  1. "shader counted 575040 vertices (0.01 of draws x vertices)": 600 draws of the 156641-vertex stream ran the sway
#     code for 958 vertices a draw, all over 3 m above the camera. The stream is a stand's buffer and a draw takes a
#     part of it: the vertices that move are a few hundred a frame, not the tree in the picture. The proof line now says
#     "vertices run per draw".
#  2. At 1280 x 720 one pixel is 1-2 cm at 20 m: a 3 cm change in 0.25 s is under a pixel in a slot window and over
#     five pixels at 4K. The proof line now says the change in cm.
# THE FIX (BB_WIND_TWIGS_PUSH=1, default). For a twig vertex (the share tau x lean x twig weight x ramp of the move) the
# along-wind move is a PUSH that gust fronts bring and release, not a steady lean with a swing on it:
#       along = g (D (TwigRest + TwigPush F^2) + TwigFlutter SA E sin a1),   F = E / EnvScale (0 .. 1)
#       g the gust factor, D the lean's bend at this wind speed (BendMax (v / 4 m/s)^2 x BB_WIND_SWAY: 0.12 m at 4 m/s,
#       0.017 m at 1.5 m/s, 0.001 m at 0.4 m/s), SA the lean's wave (0.15 D), E the front envelope the plants already use
#       (three waves 9, 13 and 17 m long, carried downwind by the wind: a front passes a point every 2.3 s at 4 m/s and
#       every 6 s at 1.5 m/s; each wave's sine is skewed: in fast, back slowly), clamped to the view's MaxAlong.
#   TwigRest 0.05 (r89g: 0.25 D is the steady lean: 5 times smaller now), TwigPush 2.5, TwigFlutter 0.5 (the very subtle
#   wave: half of r89g's). F squared makes the gusts peaks with calms between them (mean F^2 is a third of the peak).
#   Everything else of the twig weight stays as r89g made it (smoothstep 3-9 m over the camera x 0.6 x the size factor
#   x BB_WIND_TWIGS): the numbers (cm, gust factor 1, BB_WIND_TWIGS 1, steady / peak) at a tip hc m over the camera:
#       4 m/s:   8 m 0.17 / 8.5     20 m 0.40 / 20.2     38 m 0.72 / 36.7
#       3 m/s:   8 m 0.09 / 4.8     20 m 0.22 / 11.4     38 m 0.41 / 20.7
#       1.5 m/s: 8 m 0.02 / 1.2     20 m 0.06 / 2.8      38 m 0.10 / 5.2
#       0.4 m/s: nothing (0.1 / 0.2 / 0.4 cm peak)
#   (the mean of the moving part is about a third of the peak). The base weight of plants is untouched; a mesh with the
#   tree word and tau above 0 is the only one whose share of the move takes the new along rule.
# In the shaders the rule is ONE extra term: the twig share x (the push along - the ripple's along) x the wind
# direction added to the ripple's displacement (the shaders already have the front envelope E, g, a1, the bend and the
# wave words). BbWindSway::TwigAlong / RippleAlong / Displace are this in C++ (unit tests, the Python twin).
#
# THE PROOF LINE (TOOL, BB_WIND_TWIGS_PROOF=1, with the push rule): time motion. The lifter's shader evaluates the push
# a second time with the front phases of LagFrames (15) frames ago, which the CPU writes into three words of the sway
# buffer (BbWindTwigs::ProofLagStep, once per frame at the first view's fill; the swing term sin a1 and the gust factor
# are taken as now) and counts per base slot, over the twig vertices (share above 0, finite, lag valid): the number,
# the sum of |change| in mm (a u32), the largest change (m) and the largest change of the front share F. The line:
#   "time motion over 15 frames: N twig vertices, V vertices run per draw, change mean X cm, largest Y cm, front
#   share changed by up to Z (moving | STILL | no twig vertex counted ...)"; the real motion, not the x5 of the proof.
#   Not a per-vertex difference of two real frames (the shader keeps no state): a difference of the same rule at two
#   times, at one camera. After 15 frames of the same camera and wind a still picture with a "moving" line means the
#   picture is the problem (pixels), a "STILL" line means the phases do not advance on the GPU.
#
# OFF. PUSH=0 (or the twigs, FIT or BB_WIND off): PushOn() is false (read once; PUSH needs FIT); every new shader line is
# inside `if (BbWindTwigs::PushOn())`, so the SPIR-V is byte for byte r89g's, the shader cache version offset has no
# +40 and no sway buffer byte is added; the CPU adds one static-bool test per view fill (the lag step, proof only).
# COST ON: per sway vertex of a tall mesh with the tree rule one more clamp, a few multiplies and one sine (a1's), in
# the push block (about 20 ALU ops a vertex, on the few hundred to thousands of twig vertices a frame; not measurable);
# memory 0 (the proof knob adds 8208 + 16 bytes of the sway buffer for the change words and the lag words; the CPU
# adds a 16-entry ring of 3 floats).
#
# Files: edits only: bbport_wind_sway.h (constants, TwigAlong, RippleAlong, TwigIn.push, Displace), bbport_wind_twigs.h
# (knob, PushOn, version offset, lag/change words, texts, the proof counters' reading and line), emit_spirv_special.cpp
# and lift_stage.cpp (the push term; in the lifter the change counters), vk_rasterizer_effects.cpp (the lag step, the
# push report line, the once line), tests/test_wind_sway.cpp (a block and three r89g lines), README.md (a row). No new
# file, no shader source, no CMake change.
# Order: after r89g (and r89f, r112g; the tree has them); revert this one first. Compatible with r112i's hang code
# (it touches the hang block; the anchors here are the ripple's rippled/ddx/ddz lines and the proof's keep(13, g) line).
#
# Use: python -I -X utf8 r89h_twigs-alive.py check | apply | revert (root from R89H_ROOT, else <tree>).
# Files keep their line ends. Originals are kept in r89h_backup/ next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89h_backup")
ROOT = os.environ.get("R89H_ROOT") or "<tree>"
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
S_CONST_OLD = "static_assert(FitLo < FitHi && FitShare > 0.0f && FitShare <= 1.0f && FitEye >= 0.0f);\n"
S_CONST_NEW = S_CONST_OLD + r'''
// bbport (r89h_twigs-alive): with BB_WIND_TWIGS_PUSH (default 1, needs the fit rule) the along-wind move of a twig
// (the share tau x lean x twig weight x ramp of a vertex's move) is a push that gust fronts bring and release:
//   along = g (D (TwigRest + TwigPush F^2) + TwigFlutter SA E sin a1),  F = E / EnvScale (0..1),
// D the ripple's bend (RippleAt + 12), SA its along wave (RippleAt + 9), E the front envelope (Envelope), g the gust
// factor, held to the view's MaxAlong. A small steady lean (TwigRest of D), a push of up to TwigPush D in a full front
// (F^2: gusts are peaks with calms between), half of the lean's very subtle wave on top. BbWindTwigs::PushOn().
inline constexpr float TwigRest = 0.05f, TwigPush = 2.5f, TwigFlutter = 0.5f;
static_assert(TwigRest >= 0.0f && TwigPush > 0.0f && TwigFlutter >= 0.0f && TwigRest + TwigPush <= 4.0f);

/// The twig push rule's along-wind move (m, before the share) of a vertex: `g` the gust factor, `env` the front
/// envelope at the vertex (Envelope), `a1` the swing phase. The shaders do the same, operation for operation.
[[nodiscard]] inline float TwigAlong(const float* view, float g, float env, float a1) {
    const float* p = view + RippleAt;
    const float front = env * (1.0f / EnvScale);
    return std::clamp(g * (p[12] * (TwigRest + TwigPush * (front * front)) + TwigFlutter * p[9] * env * std::sin(a1)),
                      -view[WindE], view[WindE]);
}

/// The ripple's own along-wind move (m, before the weight) of a vertex, as RippleOr computes it (the move the push
/// rule replaces for a twig's share).
[[nodiscard]] inline float RippleAlong(const float* view, float g, float env, float a1) {
    const float* p = view + RippleAt;
    return std::clamp(g * (p[8] + p[12] * (env - 1.0f) + p[9] * env * std::sin(a1)), -view[WindE], view[WindE]);
}
'''
S_IN_OLD = "    bool fit = false;   ///< bbport (r89g_twigs-proof): BB_WIND_TWIGS_FIT (FitWeight in place of TwigWeight)\n"
S_IN_NEW = (S_IN_OLD +
            "    bool push = false;  ///< bbport (r89h_twigs-alive): BB_WIND_TWIGS_PUSH (TwigAlong for the twig's share)\n")
S_DD_OLD = "    const float ddx = moved[0], ddz = moved[1];\n"
S_DD_NEW = (
    "    float ddx = moved[0], ddz = moved[1];\n"
    "    // bbport (r89h_twigs-alive): the twig's share of the move (tau x lean x twig weight x ramp) takes the push rule's\n"
    "    // along in place of the ripple's (only with the ripple, the flag word above 0)\n"
    "    if (twig != nullptr && twig->push && 0.0f < view[RippleD + 3]) {\n"
    "        const float env = Envelope(view, s, q);\n"
    "        const float twig_share = tau * lean * wt_use * ramp;\n"
    "        const float extra = twig_share * (TwigAlong(view, g, env, a1) - RippleAlong(view, g, env, a1));\n"
    "        ddx += extra * dx;\n"
    "        ddz += extra * dz;\n"
    "    }\n")

# ---------------------------------------------------------------- bbport_wind_twigs.h
N_ADD_OLD = "inline constexpr std::uint32_t FitAdd = 10, ProofAdd = 20;\n"
N_ADD_NEW = (N_ADD_OLD + r'''/// bbport (r89h_twigs-alive): added as well with BB_WIND_TWIGS_PUSH (the along rule differs; the sums of the four
/// optional offsets 10, 20, 40 and 100 stay apart from each other and from r112's hang version).
inline constexpr std::uint32_t PushAdd = 40;
''')
N_BYTES_OLD = "inline constexpr std::uint32_t ProofBytes = ProofEnd * 4;\n"
N_BYTES_NEW = (N_BYTES_OLD + r'''/// bbport (r89h_twigs-alive, TOOL): with the proof knob and the push rule every base slot has ChangeSlotWords more
/// counters behind the proof counters (words from the start of the sway region's buffer): 0 the largest change of
/// the push (m, float bits) between now and LagFrames frames ago, 1 the sum of the changes (mm, u32), 2 the twig
/// vertices counted, 3 the largest change of the front share F (float bits); then LagWords words the CPU writes
/// once a frame: the front phases of LagFrames frames ago (3 floats) and a flag (1.0 valid, 0.0 not yet).
inline constexpr std::uint32_t ChangeSlotWords = 4;
inline constexpr std::uint32_t ChangeAt = ProofEnd;
inline constexpr std::uint32_t ChangeWords = W::BaseSlots * ChangeSlotWords;
inline constexpr std::uint32_t LagAt = ChangeAt + ChangeWords, LagWords = 4;
inline constexpr std::uint32_t LagEnd = LagAt + LagWords;
inline constexpr std::uint32_t LagFrames = 15;
static_assert(ChangeAt % 4 == 0 && LagAt % 4 == 0 && ChangeSlotWords % 4 == 0 && LagWords == 4,
              "the lag words are one aligned vec4");
''')
N_KNOB_OLD = "    bool proof = false; ///< bbport (r89g, TOOL): BB_WIND_TWIGS_PROOF=1\n};\n"
N_KNOB_NEW = ("    bool proof = false; ///< bbport (r89g, TOOL): BB_WIND_TWIGS_PROOF=1\n"
              "    int push = 1;  ///< bbport (r89h): BB_WIND_TWIGS_PUSH 0 r89g's along rule, 1 the push rule\n"
              "};\n")
N_SIG_OLD = "                                    const char* fit = nullptr, const char* proof = nullptr) {\n"
N_SIG_NEW = ("                                    const char* fit = nullptr, const char* proof = nullptr,\n"
             "                                    const char* push = nullptr) {\n")
N_PARSE_OLD = "    k.proof = W::ParseNumber(proof, 0.0f) >= 0.5f;       // (TOOL) 1 only when asked\n"
N_PARSE_NEW = (N_PARSE_OLD +
               "    k.push = W::ParseNumber(push, 1.0f) >= 0.5f ? 1 : 0; // bbport (r89h_twigs-alive): 0 or 1, unreadable 1\n")
N_ONCE_OLD = '                                       std::getenv("BB_WIND_TWIGS_PROOF"));\n'
N_ONCE_NEW = ('                                       std::getenv("BB_WIND_TWIGS_PROOF"),\n'
              '                                       std::getenv("BB_WIND_TWIGS_PUSH"));\n')
N_ON_OLD = "[[nodiscard]] inline bool ProofOn() {\n    return KnobOnce().on && KnobOnce().proof;\n}\n"
N_ON_NEW = (N_ON_OLD + r'''
/// bbport (r89h_twigs-alive): whether knob `k` asks for the push rule (the twigs on, the fit rule on, PUSH above 0).
[[nodiscard]] inline bool PushWanted(const Knob& k) {
    return k.on && k.fit >= 1 && k.push >= 1;
}

/// bbport (r89h_twigs-alive): whether the twigs' along-wind move is the push rule (BB_WIND_TWIGS_PUSH above 0 with the
/// fit rule). Read once with the shaders (BinaryOffset).
[[nodiscard]] inline bool PushOn() {
    return PushWanted(KnobOnce());
}
''')
N_BUF_OLD = "    return On() ? std::max(region_bytes, ProofOn() ? ProofBytes : TwigBytes) // bbport (r89g_twigs-proof)\n"
N_BUF_NEW = ("    return On() ? std::max(region_bytes, ProofOn() ? LagEnd * 4 : TwigBytes) // bbport (r89g_twigs-proof, r89h)\n")
N_INIT_OLD = "        if (ProofOn()) { // bbport (r89g_twigs-proof, TOOL): the counters at 0\n"
N_INIT_NEW = (
    "        if (ProofOn()) { // bbport (r89h_twigs-alive, TOOL): the change counters and the lag words at 0\n"
    "            for (std::uint32_t i = 0; i < ChangeWords + LagWords; ++i) {\n"
    "                sway_words[ChangeAt + i] = 0;\n"
    "            }\n"
    "        }\n" + N_INIT_OLD)
N_RESET_OLD = "        if (ProofOn()) { // bbport (r89g_twigs-proof, TOOL): the slot's counters at 0\n"
N_RESET_NEW = (
    "        if (ProofOn()) { // bbport (r89h_twigs-alive, TOOL): the slot's change counters at 0\n"
    "            for (std::uint32_t i = 0; i < ChangeSlotWords; ++i) {\n"
    "                words[ChangeAt + slot * ChangeSlotWords + i] = 0;\n"
    "            }\n"
    "        }\n" + N_RESET_OLD)
N_OFF_OLD = "                      (ProofOn() ? ProofAdd : 0u)\n"
N_OFF_NEW = "                      (ProofOn() ? ProofAdd : 0u) + (PushOn() ? PushAdd : 0u) // bbport (r89h)\n"
N_KNOWN_OLD = ("        for (const std::uint32_t b :\n"
               "             {0u, BinaryAdd, BinaryAdd + SizeAdd, BinaryAdd + FitAdd, BinaryAdd + ProofAdd,\n"
               "              BinaryAdd + SizeAdd + FitAdd, BinaryAdd + SizeAdd + ProofAdd, BinaryAdd + FitAdd + ProofAdd,\n"
               "              BinaryAdd + SizeAdd + FitAdd + ProofAdd}) { // bbport (r89f, r89g)\n")
N_KNOWN_NEW = (
    "        for (std::uint32_t m = 0; m <= 16; ++m) { // bbport (r89f, r89g, r89h): 0, then BinaryAdd with each subset\n"
    "            const std::uint32_t k = m == 0 ? 0u : m - 1u; // of the four optional offsets (size, fit, proof, push)\n"
    "            const std::uint32_t b = m == 0 ? 0u\n"
    "                                           : BinaryAdd + ((k & 1u) != 0 ? SizeAdd : 0u) +\n"
    "                                                 ((k & 2u) != 0 ? FitAdd : 0u) + ((k & 4u) != 0 ? ProofAdd : 0u) +\n"
    "                                                 ((k & 8u) != 0 ? PushAdd : 0u);\n")
N_STRUCT_OLD = ("    float move_max = 0.0f, gain = 0.0f, lean = 0.0f, ramp = 0.0f, along = 0.0f, gust = 0.0f, hc_max = 0.0f,\n"
                "          w_max = 0.0f;\n};\n")
N_STRUCT_NEW = ("    float move_max = 0.0f, gain = 0.0f, lean = 0.0f, ramp = 0.0f, along = 0.0f, gust = 0.0f, hc_max = 0.0f,\n"
                "          w_max = 0.0f;\n"
                "    // bbport (r89h_twigs-alive, TOOL): the push's change over LagFrames frames (ChangeAt words)\n"
                "    std::uint32_t change_sum = 0, change_n = 0; ///< mm summed, twig vertices counted\n"
                "    float change_max = 0.0f, front_max = 0.0f;  ///< m, a share of the front (0-1)\n"
                "};\n")
N_READ_OLD = "    c.high = number(15);\n    return c;\n"
N_READ_NEW = (
    "    c.high = number(15);\n"
    "    // bbport (r89h_twigs-alive, TOOL): the push's change counters (4 words of this slot behind the proof's)\n"
    "    const volatile std::uint32_t* const ch = words + ChangeAt + slot * ChangeSlotWords;\n"
    "    const std::uint32_t change_bits = ch[0], front_bits = ch[3];\n"
    "    std::memcpy(&c.change_max, &change_bits, sizeof(float));\n"
    "    std::memcpy(&c.front_max, &front_bits, sizeof(float));\n"
    "    c.change_sum = ch[1];\n"
    "    c.change_n = ch[2];\n"
    "    return c;\n")
N_CLEAR_OLD = ("    volatile std::uint32_t* const v = words + ProofAt + slot * ProofSlotWords;\n"
               "    for (std::uint32_t k = 0; k < ProofSlotWords; ++k) {\n"
               "        v[k] = 0;\n"
               "    }\n"
               "}\n")
N_CLEAR_NEW = (
    "    volatile std::uint32_t* const v = words + ProofAt + slot * ProofSlotWords;\n"
    "    for (std::uint32_t k = 0; k < ProofSlotWords; ++k) {\n"
    "        v[k] = 0;\n"
    "    }\n"
    "    volatile std::uint32_t* const ch = words + ChangeAt + slot * ChangeSlotWords; // bbport (r89h_twigs-alive)\n"
    "    for (std::uint32_t k = 0; k < ChangeSlotWords; ++k) {\n"
    "        ch[k] = 0;\n"
    "    }\n"
    "}\n"
    "\n"
    "/// bbport (r89h_twigs-alive, TOOL): what the change counters say of the push's time motion (a string literal).\n"
    "[[nodiscard]] inline const char* ChangeVerdict(const ProofCounts& c) {\n"
    "    if (c.change_n == 0) {\n"
    "        return \"no twig vertex counted with a lag (push off, the lag words not valid yet, or no twig share)\";\n"
    "    }\n"
    "    if (!(c.change_max >= 0.001f)) {\n"
    "        return \"STILL: the push changes by under 1 mm over the lag (the phases do not advance on the GPU, or no wind)\";\n"
    "    }\n"
    "    return \"moving\";\n"
    "}\n")
N_LINE_OLD = ('                  "%.0f m), largest weight %.3f, largest move %.1f cm; verdict: %s",\n'
              "                  slot, n(draws), n(patched), pipelines, verts_each, c.verts, ratio, c.fin, c.tall, c.old_w, c.fit_w,\n"
              "                  c.used_w, c.moved, double(c.gain), double(c.lean), double(c.ramp), double(c.along), double(c.gust),\n"
              "                  double(c.hc_max), c.high, double(W::FitLo), double(c.w_max), double(c.move_max * 100.0f),\n"
              "                  ProofVerdict(c));\n")
N_LINE_NEW = (
    '                  "%.0f m), largest weight %.3f, largest move %.1f cm; time motion over %u frames: %u twig vertices, "\n'
    '                  "%.0f vertices run per draw, change mean %.2f cm, largest %.2f cm, front share changed by up to "\n'
    '                  "%.2f (%s)%s; verdict: %s",\n'
    "                  slot, n(draws), n(patched), pipelines, verts_each, c.verts, ratio, c.fin, c.tall, c.old_w, c.fit_w,\n"
    "                  c.used_w, c.moved, double(c.gain), double(c.lean), double(c.ramp), double(c.along), double(c.gust),\n"
    "                  double(c.hc_max), c.high, double(W::FitLo), double(c.w_max), double(c.move_max * 100.0f),\n"
    "                  unsigned(LagFrames), c.change_n, draws > 0 ? double(c.verts) / double(draws) : 0.0,\n"
    "                  c.change_n > 0 ? double(c.change_sum) / double(c.change_n) * 0.1 : 0.0,\n"
    "                  double(c.change_max * 100.0f), double(c.front_max), ChangeVerdict(c),\n"
    '                  c.change_sum > 4000000000u ? " [sum may have wrapped]" : "", ProofVerdict(c));\n')
N_END_OLD = "} // namespace BbWindTwigs\n"
N_END_NEW = r'''// bbport (r89h_twigs-alive): the push rule's numbers and texts, and the proof knob's lag step.

/// A twig tip's move (m) by the push rule: steady (no front) and the peak (a full front), at a gust factor of 1.
struct PushTip {
    float steady = 0.0f, peak = 0.0f;
};

/// The push rule's tip at wind `speed` (m/s), BB_WIND_SWAY `scale`, BB_WIND_TWIGS `twigs`, `hc` m over the camera (the
/// fit weight, with the size factor when `sized`, times D (TwigRest, and TwigRest + TwigPush)).
[[nodiscard]] inline PushTip PushTipAt(float speed, float scale, float twigs, float hc, bool sized) {
    const W::LeanCurve c = W::LeanAt(speed, scale, 1.0f, false);
    const float weight = W::TwigRatio * twigs * (W::FitShare * W::Smooth01(hc, W::FitLo, W::FitInv)) *
                         (sized ? W::SizeFactor(hc + W::FitEye) : 1.0f);
    PushTip t;
    t.steady = weight * c.bend * W::TwigRest;
    t.peak = weight * c.bend * (W::TwigRest + W::TwigPush);
    return t;
}

/// "steady/peak (h m), ..." in cm for tips 8, 20 and 38 m over the camera (under 100 characters).
inline void PushTipsText(float speed, float scale, float twigs, bool sized, char* out, std::size_t size) {
    const float heights[3] = {8.0f, 20.0f, 38.0f};
    if (size == 0) {
        return;
    }
    out[0] = 0;
    for (int i = 0; i < 3; ++i) {
        const PushTip t = PushTipAt(speed, scale, twigs, heights[i], sized);
        const std::size_t used = std::strlen(out);
        std::snprintf(out + used, size - used, "%s%.2f/%.1f (%.0f m)", i == 0 ? "" : ", ", double(t.steady * 100.0f),
                      double(t.peak * 100.0f), double(heights[i]));
    }
}

/// The once line of BB_WIND_TWIGS_PUSH (under 560 characters).
inline void PushOnceText(const Knob& k, float scale, char* out, std::size_t size) {
    if (!PushWanted(k)) {
        std::snprintf(out, size,
                      "Wind twigs (r89h, BB_WIND_TWIGS_PUSH=%d): off (the push rule needs BB_WIND_TWIGS_FIT=1); the twigs "
                      "move by r89g's along rule",
                      k.push);
        return;
    }
    char slow[128], fast[128];
    PushTipsText(BbWind::DefaultSpeed, scale, k.twigs, k.size >= 1, slow, sizeof(slow));
    PushTipsText(BbWind::MaxSpeed, scale, k.twigs, k.size >= 1, fast, sizeof(fast));
    std::snprintf(out, size,
                  "Wind twigs (r89h, BB_WIND_TWIGS_PUSH=1): a twig is pushed downwind by gust fronts and settles back: "
                  "steady %.2f of the bend, push up to %.1f x the bend x the front share squared (fronts %.0f m apart, "
                  "carried by the wind: every %.1f s at 4 m/s, %.1f s at 1.5 m/s); steady/peak cm at 4 m/s: %s; at "
                  "1.5 m/s: %s",
                  double(W::TwigRest), double(W::TwigPush), double(W::EnvWavelength[0]),
                  double(W::EnvWavelength[0] / BbWind::MaxSpeed), double(W::EnvWavelength[0] / BbWind::DefaultSpeed), fast,
                  slow);
}

/// The line every W::ReportFrames frames (under 400 characters): the tree draws taken and the steady/peak tip moves
/// at this wind.
inline void PushReportText(const Stats& st, const BbWind::Snapshot& wind, const Knob& k, float scale, char* out,
                           std::size_t size) {
    const float speed = std::isfinite(wind.speed) ? std::max(wind.speed, 0.0f) : 0.0f;
    char tips[128];
    PushTipsText(speed, scale, k.twigs, k.size >= 1, tips, sizeof(tips));
    std::snprintf(out, size,
                  "Wind twigs (r89h, BB_WIND_TWIGS_PUSH=%d): %llu tree draws pushed by gust fronts; at %.2f m/s "
                  "steady/peak cm at 8/20/38 m over the camera: %s",
                  k.push, static_cast<unsigned long long>(st.tree_draws + st.small_tree), double(speed), tips);
}

/// bbport (r89h_twigs-alive, TOOL): once a frame (at the first view's fill) keeps the front phases of this fill and
/// writes the ones of LagFrames fills ago, and a validity flag, into the lag words (LagAt) the lifter's change counters
/// read. `view` is the filled view (its phases at RippleA + 2, RippleA + 3 and RippleB).
inline void ProofLagStep(std::uint32_t* words, const float* view) {
    static std::array<std::array<float, 3>, LagFrames + 1> ring{};
    static std::uint64_t count = 0;
    if (words == nullptr || view == nullptr) {
        return;
    }
    const std::array<float, 3> now = {view[W::RippleA + 2], view[W::RippleA + 3], view[W::RippleB]};
    const std::uint64_t at = count++;
    ring[at % ring.size()] = now;
    const bool valid = at >= LagFrames;
    const std::array<float, 3>& lag = valid ? ring[(at + 1) % ring.size()] : now;
    volatile std::uint32_t* const out = words + LagAt;
    for (std::uint32_t k = 0; k < 3; ++k) {
        std::uint32_t bits = 0;
        std::memcpy(&bits, &lag[k], sizeof(bits));
        out[k] = bits;
    }
    const float flag = valid ? 1.0f : 0.0f;
    std::uint32_t flag_bits = 0;
    std::memcpy(&flag_bits, &flag, sizeof(flag_bits));
    out[3] = flag_bits;
}

''' + N_END_OLD

# ---------------------------------------------------------------- the two shader emitters
E_OLD = ("    const Id rippled = ctx.OpFOrdLessThan(bool_type, zero, comp(rip_d, 3u));\n"
         "    const Id ddx = ctx.OpSelect(f32_type, rippled, ddx_rip, ddx_one);\n"
         "    const Id ddz = ctx.OpSelect(f32_type, rippled, ddz_rip, ddz_one);\n")
E_NEW = (
    "    // bbport (r89h_twigs-alive): with BB_WIND_TWIGS_PUSH (read once; such sway code has its own shader cache version)\n"
    "    // the twig's share of the move (tau x lean x twig weight x ramp) takes the push rule's along (BbWindSway::TwigAlong)\n"
    "    // in place of the ripple's: one extra term, share x (push along - r_along) x the wind's direction. Off: nothing.\n"
    "    Id ddx_use = ddx_rip, ddz_use = ddz_rip;\n"
    "    if (BbWindTwigs::PushOn()) {\n"
    "        const Id front_share = mul(env, f(1.0f / W::EnvScale));\n"
    "        const Id push_along = ctx.OpFClamp(\n"
    "            f32_type,\n"
    "            mul(g, add(mul(comp(rip_d, 0u),\n"
    "                           add(f(W::TwigRest), mul(f(W::TwigPush), mul(front_share, front_share)))),\n"
    "                       mul(mul(mul(f(W::TwigFlutter), comp(rip_c, 1u)), env), ctx.OpSin(f32_type, a1)))),\n"
    "            ctx.OpFNegate(f32_type, max_along), max_along);\n"
    "        Id twig_share = mul(mul(mul(tau, lean), wt_use), ramp);\n"
    "        if (BbWindTwigs::ProofOn()) { // the proof knob's x5 of a tree word's move\n"
    "            twig_share = ctx.OpSelect(\n"
    "                f32_type,\n"
    "                ctx.OpINotEqual(bool_type,\n"
    "                                ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(BbWindTwigs::TreeBit)),\n"
    "                                ctx.u32_zero_value),\n"
    "                mul(twig_share, f(BbWindTwigs::ProofGain)), twig_share);\n"
    "        }\n"
    "        const Id extra = mul(twig_share, sub(push_along, r_along));\n"
    "        ddx_use = ctx.OpSelect(f32_type, fin, add(ddx_rip, mul(extra, dx)), zero);\n"
    "        ddz_use = ctx.OpSelect(f32_type, fin, add(ddz_rip, mul(extra, dz)), zero);\n"
    "    }\n"
    "    const Id rippled = ctx.OpFOrdLessThan(bool_type, zero, comp(rip_d, 3u));\n"
    "    const Id ddx = ctx.OpSelect(f32_type, rippled, ddx_use, ddx_one);\n"
    "    const Id ddz = ctx.OpSelect(f32_type, rippled, ddz_use, ddz_one);\n")

L_OLD = ("    const u32 rippled = FCmp(O(spv::Op::OpFOrdLessThan), zero, comp(rip_d, 3));\n"
         "    const u32 ddx = Select(rippled, ddx_rip, ddx_one);\n"
         "    const u32 ddz = Select(rippled, ddz_rip, ddz_one);\n")
L_NEW = (
    "    // bbport (r89h_twigs-alive): the push rule's extra term, as the recompiler's EmitVertexSway (BbWindSway::TwigAlong,\n"
    "    // Displace in C++); push_along and push_share (the share before the proof's x5) serve the proof's change counters\n"
    "    u32 ddx_use = ddx_rip, ddz_use = ddz_rip;\n"
    "    u32 push_along = 0, push_share = 0;\n"
    "    if (BbWindTwigs::PushOn()) {\n"
    "        const u32 front_share = FMul(env, CF(1.0f / W::EnvScale));\n"
    "        push_along = clamp_f(FMul(g, FAdd(FMul(comp(rip_d, 0), FAdd(CF(W::TwigRest), FMul(CF(W::TwigPush), FMul(front_share, front_share)))),\n"
    "                                          FMul(FMul(FMul(CF(W::TwigFlutter), comp(rip_c, 1)), env), sin_f(a1)))),\n"
    "                             FNeg(max_along), max_along);\n"
    "        push_share = FMul(FMul(FMul(tau, lean), wt_use), ramp);\n"
    "        u32 share_used = push_share;\n"
    "        if (BbWindTwigs::ProofOn()) { // the proof knob's x5 of a tree word's move\n"
    "            share_used = Select(ICmp(O(spv::Op::OpINotEqual), IOp(O(spv::Op::OpBitwiseAnd), word, CU(BbWindTwigs::TreeBit)), CU(0)),\n"
    "                                FMul(push_share, CF(BbWindTwigs::ProofGain)), push_share);\n"
    "        }\n"
    "        const u32 extra = FMul(share_used, FSub(push_along, r_along));\n"
    "        ddx_use = Select(fin, FAdd(ddx_rip, FMul(extra, dx)), zero);\n"
    "        ddz_use = Select(fin, FAdd(ddz_rip, FMul(extra, dz)), zero);\n"
    "    }\n"
    "    const u32 rippled = FCmp(O(spv::Op::OpFOrdLessThan), zero, comp(rip_d, 3));\n"
    "    const u32 ddx = Select(rippled, ddx_use, ddx_one);\n"
    "    const u32 ddz = Select(rippled, ddz_use, ddz_one);\n")
L_KEEP_OLD = "        keep(13, g);\n"
L_KEEP_NEW = (
    L_KEEP_OLD +
    "        if (BbWindTwigs::PushOn()) { // bbport (r89h_twigs-alive, TOOL): the push's change since LagFrames frames ago\n"
    "            const u32 change_base = scaled(at(region, u64(P::ChangeAt) * 4u), field(3, 10), u64(P::ChangeSlotWords) * 4u);\n"
    "            const auto change_ptr = [&](u32 k) {\n"
    "                return Emit(O(spv::Op::OpConvertUToPtr), ptr_u32, Ty::None, {at(change_base, u64(k) * 4u)});\n"
    "            };\n"
    "            const auto change_add = [&](u32 k, u32 value) {\n"
    "                const u32 prev = Emit(O(spv::Op::OpAtomicIAdd), t_u32, Ty::U32, {change_ptr(k), device, CU(0), value});\n"
    "                nodes[m.NodeOf(prev)].effect = true;\n"
    "            };\n"
    "            const auto change_max = [&](u32 k, u32 value) { // an atomic maximum of a float of 0 or more\n"
    "                const u32 bits = Emit(O(spv::Op::OpBitcast), t_u32, Ty::U32, {Ext(GLSLstd450FMax, t_f32, Ty::F32, {value, zero})});\n"
    "                const u32 prev = Emit(O(spv::Op::OpAtomicUMax), t_u32, Ty::U32, {change_ptr(k), device, CU(0), bits});\n"
    "                nodes[m.NodeOf(prev)].effect = true;\n"
    "            };\n"
    "            const u32 lag_ptr = Emit(O(spv::Op::OpConvertUToPtr), ptr_v4f, Ty::None, {at(region, u64(P::LagAt) * 4u)});\n"
    "            const u32 lag = Emit(O(spv::Op::OpLoad), t_v4f, Ty::V4F, {lag_ptr, aligned, 16}, 6);\n"
    "            const u32 n_lag = FMul(FAdd(FAdd(front(comp(lag, 0), W::Env1S, W::Env1Q), front(comp(lag, 1), W::Env2S, W::Env2Q)),\n"
    "                                        front(comp(lag, 2), W::Env3S, W::Env3Q)), CF(1.0f / 3.0f));\n"
    "            const u32 tt_lag = clamp_f(FMul(FSub(n_lag, CF(W::EnvLo)), CF(W::EnvInv)), zero, CF(1.0f));\n"
    "            const u32 env_lag = FMul(FMul(FMul(tt_lag, tt_lag), FSub(CF(3.0f), FMul(CF(2.0f), tt_lag))), CF(W::EnvScale));\n"
    "            const u32 front_lag = FMul(env_lag, CF(1.0f / W::EnvScale));\n"
    "            const u32 along_lag = clamp_f(FMul(g, FAdd(FMul(comp(rip_d, 0), FAdd(CF(W::TwigRest), FMul(CF(W::TwigPush), FMul(front_lag, front_lag)))),\n"
    "                                                       FMul(FMul(FMul(CF(W::TwigFlutter), comp(rip_c, 1)), env_lag), sin_f(a1)))),\n"
    "                                          FNeg(max_along), max_along);\n"
    "            const auto both = [&](u32 a, u32 b) { return Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool, {a, b}); };\n"
    "            // (review: only view 0, whose front phases the CPU keeps: another view's camera anchors its phases elsewhere)\n"
    "            const u32 live = both(both(fin, ICmp(O(spv::Op::OpIEqual), field(2, 1), CU(0))), both(FCmp(O(spv::Op::OpFOrdGreaterThan), comp(lag, 3), CF(0.5f)),\n"
    "                                            FCmp(O(spv::Op::OpFOrdGreaterThan), push_share, CF(1.0e-6f))));\n"
    "            const u32 change = Select(live, FMul(push_share, abs_f(FSub(push_along, along_lag))), zero);\n"
    "            const u32 front_change = Select(live, FMul(abs_f(FSub(env, env_lag)), CF(0.5f)), zero);\n"
    "            change_max(0, change);\n"
    "            change_add(1, Emit(O(spv::Op::OpConvertFToU), t_u32, Ty::U32, {FMul(change, CF(1000.0f))}));\n"
    "            change_add(2, flag(live));\n"
    "            change_max(3, front_change);\n"
    "        }\n")

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
F_LAG_OLD = "        std::memcpy(words + BbWindSway::ViewAt(frame_slot, view), filled.data(), sizeof(filled));\n"
F_LAG_NEW = (F_LAG_OLD +
             "        if (view == 0 && BbWindTwigs::ProofOn() && BbWindTwigs::PushOn()) { // bbport (r89h_twigs-alive, TOOL)\n"
             "            BbWindTwigs::ProofLagStep(words, filled.data()); // the front phases of 15 frames ago, for the change counters\n"
             "        }\n")
F_BUF_OLD = "            char proof_text[768];\n"
F_BUF_NEW = "            char proof_text[1024]; // bbport (r89h_twigs-alive): the line grew by the time motion\n"
F_REP_OLD = "    if (BbWindTwigs::ProofOn()) { // bbport (r89g_twigs-proof, TOOL): a proof line per tree mesh, then the counters at 0\n"
F_REP_NEW = (
    "    if (BbWindTwigs::PushOn()) { // bbport (r89h_twigs-alive): the push rule's line\n"
    "        char push_text[400];\n"
    "        BbWindTwigs::PushReportText(twig_stats, wind.Get(), knob, BbWindSway::KnobOnce().scale, push_text,\n"
    "                                    sizeof(push_text));\n"
    '        BbReport::Printf("%s\\n", push_text);\n'
    "    }\n" + F_REP_OLD)
F_ONCE_OLD = ("            if (BbWindTwigs::ProofOn()) {\n"
              "                BbWindTwigs::ProofOnceText(fit_once, sizeof(fit_once));\n"
              '                BbReport::Printf("%s\\n", fit_once);\n'
              "            }\n")
F_ONCE_NEW = (F_ONCE_OLD +
              "            BbWindTwigs::PushOnceText(BbWindTwigs::KnobOnce(), BbWindSway::KnobOnce().scale, fit_once,\n"
              "                                      sizeof(fit_once)); // bbport (r89h_twigs-alive)\n"
              '            BbReport::Printf("%s\\n", fit_once);\n')

# ---------------------------------------------------------------- tests
T_WORDS_OLD = "        std::vector<std::uint32_t> words(T::ProofEnd, 0u);\n"
T_WORDS_NEW = "        std::vector<std::uint32_t> words(T::LagEnd, 0u); // bbport (r89h): the change words are read too\n"
T_LINE_OLD = "        char line[800];\n"
T_LINE_NEW = "        char line[1100]; // bbport (r89h): the line grew by the time motion\n"
T_LEN_OLD = '                   std::strstr(line, "verdict: OK:") != nullptr && std::strlen(line) < 760,\n'
T_LEN_NEW = '                   std::strstr(line, "verdict: OK:") != nullptr && std::strlen(line) < 1000,\n'
T_ANCHOR = ('        Expect(std::strstr(once, "BB_WIND_TWIGS_PROOF=1, TOOL") != nullptr && std::strlen(once) < 520, "ProofOnceText");\n'
            "    }\n")
T_BLOCK = r'''
    // bbport (r89h_twigs-alive): the push rule's along-wind move, its place in Displace, the knob, the versions, the
    // change counters and the lag step, the texts.
    {
        namespace T = BbWindTwigs;
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        // the rule's numbers on a view at 4 m/s (the bend is BendMax), gust factor 1
        Ripple shape_ripple;
        const auto sv = TwigViewOf(c, Gusty(5.0, 225.0f, 4.0f, 0.0f), shape_ripple, 1.0f, 1.0f, 0.0f);
        const double bend = double(sv[RippleAt + 12]);
        Expect(Near(bend, double(BendMax), 1e-6), "the view's bend at 4 m/s is BendMax");
        Expect(Near(TwigAlong(sv.data(), 1.0f, 0.0f, 0.0f), bend * double(TwigRest), 1e-6) &&
                   Near(TwigAlong(sv.data(), 1.0f, EnvScale, 0.0f), bend * double(TwigRest + TwigPush), 1e-5) &&
                   Near(TwigAlong(sv.data(), 1.0f, 1.0f, 0.0f), bend * double(TwigRest + 0.25f * TwigPush), 1e-6) &&
                   TwigAlong(sv.data(), 0.0f, 1.0f, 1.0f) == 0.0f,
               "TwigAlong: the rest with no front, rest + push in a full front, the squared share between, 0 with no gust");
        Expect(Near(RippleAlong(sv.data(), 1.0f, 1.0f, 0.0f), double(sv[RippleAt + 8]), 1e-6) &&
                   TwigAlong(sv.data(), 1.0f, 0.0f, 0.0f) < RippleAlong(sv.data(), 1.0f, 0.0f, 0.0f),
               "RippleAlong is the ripple's own (its rest at a front of 1); the push's steady part is smaller");
        // the time series of one limb 12 m over the camera in a 4 m/s wind (a gust factor of 1)
        const std::array<double, 3> mid = {10.0 - std::sin(0.3) * 7.0, 0.0, 20.0 - std::cos(0.3) * 7.0};
        const TreeBox stand = {0.0f, 37.0f, float(mid[0] - 22.5), float(mid[0] + 22.5), float(mid[2] - 19.5),
                               float(mid[2] + 19.5)};
        struct Range {
            double lo = 1.0e9, hi = 0.0;
        };
        const auto range_of = [&](bool push) {
            Range range;
            Ripple wind_ripple;
            const std::array<double, 3> limb = {mid[0], 14.0, mid[2]};
            for (int i = 0; i < 600; ++i) {
                const BbWind::Snapshot snap = Gusty(0.1 * i, 225.0f, 4.0f, 0.0f);
                const auto v = TwigViewOf(c, snap, wind_ripple, 1.0f, 1.0f, 0.0f);
                const auto clip = ClipOf(c, limb);
                const auto before = WorldOf(v.data(), clip);
                TwigIn in = TwigInOf(stand, true);
                in.sized = true;
                in.fit = true;
                in.push = push;
                const auto after = WorldOf(v.data(), Displace(v.data(), clip, HeightKey(stand.base), 1.0f, nullptr,
                                                              CrownKey(stand.crown), nullptr, &in));
                const std::array<double, 3> moved = {after[0] - before[0], after[1] - before[1], after[2] - before[2]};
                const double along = AlongOf(moved, snap);
                range.lo = std::min(range.lo, along);
                range.hi = std::max(range.hi, along);
            }
            return range;
        };
        const Range on = range_of(true);
        const Range off = range_of(false);
        Expect(on.hi > 0.03 && on.hi < 0.25, "the push rule: the largest along-wind move 12 m over the camera is 3-25 cm");
        Expect(on.lo < 0.15 * on.hi && on.hi - on.lo > 0.5 * on.hi,
               "the push rule: the steady part is small, the swing is over half the largest move");
        Expect(off.hi > 0.02, "push off: r89g's rule still moves the limb");
        {   // where the twig weight is 0 (1 m over the camera) the rule changes nothing, bit for bit
            const std::array<double, 3> low = {mid[0], 3.0, mid[2]};
            const auto clip = ClipOf(c, low);
            TwigIn with_push = TwigInOf(stand, true);
            with_push.sized = true;
            with_push.fit = true;
            with_push.push = true;
            TwigIn without = with_push;
            without.push = false;
            Expect(Displace(sv.data(), clip, HeightKey(stand.base), 1.0f, nullptr, CrownKey(stand.crown), nullptr,
                            &with_push) ==
                       Displace(sv.data(), clip, HeightKey(stand.base), 1.0f, nullptr, CrownKey(stand.crown), nullptr,
                                &without),
                   "the push rule changes nothing where the twig weight is 0");
        }
        // the knob and the versions
        const T::Knob dflt = T::ParseKnob(nullptr, nullptr, true, true);
        const T::Knob nopush = T::ParseKnob(nullptr, nullptr, true, true, nullptr, nullptr, nullptr, nullptr, "0");
        const T::Knob nofit = T::ParseKnob(nullptr, nullptr, true, true, nullptr, nullptr, "0", nullptr, nullptr);
        const T::Knob junk = T::ParseKnob(nullptr, nullptr, true, true, nullptr, nullptr, nullptr, nullptr, "x");
        Expect(dflt.push == 1 && nopush.push == 0 && junk.push == 1 && T::PushWanted(dflt) && !T::PushWanted(nopush) &&
                   !T::PushWanted(nofit) && !T::PushWanted(T::ParseKnob(nullptr, nullptr, false, true)),
               "BB_WIND_TWIGS_PUSH: 0 or 1, default 1; the rule needs the twigs and the fit rule");
        Expect(T::KnownVersion(2011 + 150, 11, 21, 1000) && T::KnownVersion(2011 + 170, 11, 21, 1000) &&
                   T::KnownVersion(2011 + 40, 11, 21, 1000) && !T::KnownVersion(2016, 11, 21, 1000) && T::PushAdd == 40,
               "the saved versions with the push offset are known; no other");
        // the change counters and the line
        std::vector<std::uint32_t> words(T::LagEnd, 0u);
        const std::uint32_t slot = 7;
        std::uint32_t* const ch = words.data() + T::ChangeAt + slot * T::ChangeSlotWords;
        const auto bits = [](float v) {
            std::uint32_t u = 0;
            std::memcpy(&u, &v, sizeof(u));
            return u;
        };
        ch[0] = bits(0.12f);
        ch[1] = 1500;
        ch[2] = 300;
        ch[3] = bits(0.4f);
        const T::ProofCounts pc = T::ReadProof(words.data(), slot);
        Expect(Near(pc.change_max, 0.12, 1e-6) && pc.change_sum == 1500 && pc.change_n == 300 &&
                   Near(pc.front_max, 0.4, 1e-6) && pc.verts == 0,
               "ReadProof reads the slot's change words");
        char line[1100];
        T::ProofLine(pc, slot, 600, 600, 1, 156641, line, sizeof(line));
        Expect(std::strstr(line, "time motion over 15 frames: 300 twig vertices") != nullptr &&
                   std::strstr(line, "change mean 0.50 cm, largest 12.00 cm") != nullptr &&
                   std::strstr(line, "(moving)") != nullptr && std::strlen(line) < 1000,
               "ProofLine says the time motion");
        Expect(std::strstr(T::ChangeVerdict(pc), "moving") != nullptr &&
                   std::strstr(T::ChangeVerdict(T::ProofCounts{}), "no twig vertex") != nullptr,
               "ChangeVerdict");
        T::ProofCounts still = pc;
        still.change_max = 0.0f;
        Expect(std::strstr(T::ChangeVerdict(still), "STILL") != nullptr, "ChangeVerdict: still");
        T::ClearProof(words.data(), slot);
        Expect(T::ReadProof(words.data(), slot).change_n == 0 && ch[1] == 0 && ch[0] == 0, "ClearProof clears the change words");
        // the lag step: 15 steps with the flag 0, then the phases of 15 steps ago and the flag 1
        std::vector<std::uint32_t> lag_words(T::LagEnd, 0u);
        std::array<float, ViewWords> pv{};
        const auto lag_of = [&](std::uint32_t k) {
            float f = 0.0f;
            std::memcpy(&f, &lag_words[T::LagAt + k], sizeof(f));
            return f;
        };
        bool lag_ok = true;
        for (int i = 0; i < 40; ++i) {
            pv[RippleA + 2] = float(i);
            pv[RippleA + 3] = float(i) + 0.25f;
            pv[RippleB] = float(i) + 0.5f;
            T::ProofLagStep(lag_words.data(), pv.data());
            const bool valid = i >= int(T::LagFrames);
            lag_ok = lag_ok && lag_of(3) == (valid ? 1.0f : 0.0f) &&
                     (!valid || (lag_of(0) == float(i - int(T::LagFrames)) &&
                                 lag_of(1) == float(i - int(T::LagFrames)) + 0.25f &&
                                 lag_of(2) == float(i - int(T::LagFrames)) + 0.5f));
        }
        Expect(lag_ok, "ProofLagStep: the flag is 0 for 15 steps, then the words hold the phases 15 steps ago");
        // the texts
        char text[640];
        T::PushOnceText(dflt, 1.0f, text, sizeof(text));
        Expect(std::strstr(text, "BB_WIND_TWIGS_PUSH=1") != nullptr && std::strstr(text, "steady/peak cm at 4 m/s") != nullptr &&
                   std::strlen(text) < 560,
               "PushOnceText");
        T::PushOnceText(nopush, 1.0f, text, sizeof(text));
        Expect(std::strstr(text, "BB_WIND_TWIGS_PUSH=0") != nullptr && std::strstr(text, "off") != nullptr, "PushOnceText off");
        T::Stats push_stats;
        push_stats.tree_draws = 42;
        T::PushReportText(push_stats, Wind(5.0, 225.0f, 4.0f), dflt, 1.0f, text, sizeof(text));
        Expect(std::strstr(text, "42 tree draws pushed") != nullptr && std::strstr(text, "at 4.00 m/s") != nullptr &&
                   std::strlen(text) < 400,
               "PushReportText");
        const T::PushTip slow_tip = T::PushTipAt(1.5f, 1.0f, 1.0f, 8.0f, true);
        const T::PushTip fast_tip = T::PushTipAt(4.0f, 1.0f, 1.0f, 8.0f, true);
        Expect(fast_tip.peak > 0.07f && fast_tip.peak < 0.10f && slow_tip.peak < 0.015f && fast_tip.steady < 0.1f * fast_tip.peak,
               "PushTipAt: 7-10 cm peak at 4 m/s at 8 m over the camera, under 1.5 cm at 1.5 m/s, the steady part small");
    }
'''
T_NEW = T_ANCHOR + T_BLOCK

# ---------------------------------------------------------------- README
README_ANCHOR = "114752 bytes of the sway buffer; off: nothing is emitted | `0` |\n"
README_NEW = README_ANCHOR + (
    "| `BB_WIND_TWIGS_PUSH` | How a twig moves along the wind (with the `BB_WIND_TWIGS`, `BB_WIND_TWIGS_FIT` rows; r89h): "
    "`0` r89g's rule (a steady lean of a quarter of the bend plus the front envelope, so a limb leans and swings), `1` "
    "(default, needs `BB_WIND_TWIGS_FIT=1`) a push: along = gust x (bend x (0.05 + 2.5 x F squared) + 0.5 x the lean's "
    "wave), F the gust front's share (0 in a calm, 1 in a full front): a small steady lean, gust fronts (9, 13 and 17 m "
    "long, carried downwind by the wind: one passes every 2.3 s at 4 m/s, every 6 s at 1.5 m/s) push the upper twigs "
    "downwind and let them settle back, the very subtle wave on top at half its size. The bend is 0.12 m x "
    "(speed / 4 m/s) squared x `BB_WIND_SWAY`, so (steady / peak cm at a tip 8 / 20 / 38 m over the camera, gust factor "
    "1): 4 m/s 0.17 / 8.5, 0.4 / 20, 0.7 / 37; 3 m/s 0.09 / 4.8, 0.2 / 11, 0.4 / 21; 1.5 m/s 0.02 / 1.2, 0.06 / 2.8, "
    "0.1 / 5.2; at 0.4 m/s under half a centimetre; the mean of the moving part is a third of the peak. Read once with "
    "the shaders (cache version +40). Log: once `Wind twigs (r89h, BB_WIND_TWIGS_PUSH=...)`, and a line every 600 frames "
    "with the tree draws pushed and the numbers at the wind now. With `BB_WIND_TWIGS_PROOF=1` the proof lines also say "
    "the time motion: the rule is evaluated again with the front phases of 15 frames ago (the CPU writes them once a "
    "frame), per mesh the twig vertices counted, the vertices run per draw, the mean and largest change in cm over the "
    "15 frames, the front share's largest change and `moving` or `STILL` (8208 + 16 more bytes of the sway buffer with "
    "the proof knob). Off: the shaders are r89g's byte for byte; on: about 20 ALU ops and one sine for a twig vertex; "
    "no memory; not measured | `1` |\n")

EDITS = {
    HEADER: [(S_CONST_OLD, S_CONST_NEW), (S_IN_OLD, S_IN_NEW), (S_DD_OLD, S_DD_NEW)],
    NEWH: [(N_ADD_OLD, N_ADD_NEW), (N_BYTES_OLD, N_BYTES_NEW), (N_KNOB_OLD, N_KNOB_NEW), (N_SIG_OLD, N_SIG_NEW),
           (N_PARSE_OLD, N_PARSE_NEW), (N_ONCE_OLD, N_ONCE_NEW), (N_ON_OLD, N_ON_NEW), (N_BUF_OLD, N_BUF_NEW),
           (N_INIT_OLD, N_INIT_NEW), (N_RESET_OLD, N_RESET_NEW), (N_OFF_OLD, N_OFF_NEW), (N_KNOWN_OLD, N_KNOWN_NEW),
           (N_STRUCT_OLD, N_STRUCT_NEW), (N_READ_OLD, N_READ_NEW), (N_CLEAR_OLD, N_CLEAR_NEW), (N_LINE_OLD, N_LINE_NEW),
           (N_END_OLD, N_END_NEW)],
    EMIT: [(E_OLD, E_NEW)],
    LIFT: [(L_OLD, L_NEW), (L_KEEP_OLD, L_KEEP_NEW)],
    EFFECTS: [(F_LAG_OLD, F_LAG_NEW), (F_BUF_OLD, F_BUF_NEW), (F_REP_OLD, F_REP_NEW), (F_ONCE_OLD, F_ONCE_NEW)],
    TEST: [(T_WORDS_OLD, T_WORDS_NEW), (T_LINE_OLD, T_LINE_NEW), (T_LEN_OLD, T_LEN_NEW), (T_ANCHOR, T_NEW)],
    README: [(README_ANCHOR, README_NEW)],
}

CHECKS = {
    HEADER: [("inline float TwigAlong(", 1), ("inline float RippleAlong(", 1), ("bool push = false;", 1),
             ("TwigRest = 0.05f, TwigPush = 2.5f, TwigFlutter = 0.5f;", 1), ("twig->push && 0.0f < view[RippleD + 3]", 1)],
    NEWH: [("inline bool PushOn()", 1), ("inline bool PushWanted(", 1), ("inline void ProofLagStep(", 1),
           ("inline void PushOnceText(", 1), ("inline void PushReportText(", 1), ("inline PushTip PushTipAt(", 1),
           ("inline const char* ChangeVerdict(", 1), ('std::getenv("BB_WIND_TWIGS_PUSH")', 1), ("PushAdd = 40;", 1),
           ("(PushOn() ? PushAdd : 0u)", 1), ("ProofOn() ? LagEnd * 4 : TwigBytes", 1), ("LagFrames = 15;", 1),
           ("time motion over %u frames", 1)],
    EMIT: [("if (BbWindTwigs::PushOn()) {", 1), ("W::TwigPush", 1), ("ddx_use", 3)],
    LIFT: [("if (BbWindTwigs::PushOn()) {", 2), ("if (BbWindTwigs::PushOn()) { // bbport (r89h_twigs-alive, TOOL)", 1),
           ("W::TwigPush", 2), ("OpAtomicIAdd", 2), ("P::LagAt", 1), ("ddx_use", 3)],
    EFFECTS: [("BbWindTwigs::ProofLagStep(words, filled.data());", 1), ("BbWindTwigs::PushReportText(", 1),
              ("BbWindTwigs::PushOnceText(", 1), ("char proof_text[1024];", 1)],
    TEST: [("T::ProofLagStep(lag_words.data(), pv.data());", 1), ("wind-sway-test: ok", 1), ("T::LagEnd", 3)],
    README: [("| `BB_WIND_TWIGS_PUSH` |", 1), ("| `BB_WIND_TWIGS_PROOF` |", 1), ("| `BB_WIND_TWIGS_FIT` |", 1)],
}

ORDER = {
    NEWH: ["inline constexpr std::uint32_t FitAdd", "inline constexpr std::uint32_t PushAdd", "inline constexpr std::uint32_t ProofBytes",
           "inline constexpr std::uint32_t ChangeSlotWords", "int push = 1;", "inline bool ProofOn()", "inline bool PushWanted(",
           "inline bool PushOn()", "inline std::uint32_t BufferBytes(", "inline std::uint32_t BinaryOffset()",
           "inline bool KnownVersion(", "struct ProofCounts {", "inline ProofCounts ReadProof(", "inline void ClearProof(",
           "inline const char* ChangeVerdict(", "inline const char* ProofVerdict(", "inline void ProofLine(",
           "inline PushTip PushTipAt(", "inline void PushOnceText(", "inline void ProofLagStep(", "} // namespace BbWindTwigs"],
    HEADER: ["inline constexpr float FitLo", "TwigRest = 0.05f", "inline float TwigAlong(", "inline float RippleAlong(",
             "inline float SizeFactor(", "inline float Smooth01(", "inline float FitWeight(", "struct TwigIn {",
             "inline std::array<float, 4> Displace("],
}

# Numbers written twice: the header's constants and the README row's text.
PUSH_ROW = "| `BB_WIND_TWIGS_PUSH`"
TIES = [(HEADER, "TwigRest = 0.05f, TwigPush = 2.5f, TwigFlutter = 0.5f", PUSH_ROW, "(0.05 + 2.5 x F squared) + 0.5 x"),
        (HEADER, "TwigRest = 0.05f, TwigPush = 2.5f, TwigFlutter = 0.5f", PUSH_ROW, "0.17 / 8.5"),
        (NEWH, "PushAdd = 40", PUSH_ROW, "cache version +40"),
        (NEWH, "LagFrames = 15", PUSH_ROW, "front phases of 15 frames ago"),
        (NEWH, "ChangeSlotWords = 4", PUSH_ROW, "8208 + 16 more bytes")]


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
    # the change and lag words: 512 slots x 4 words + 4 words after the 16-word proof counters: 8208 + 16 bytes
    if 512 * 4 * 4 != 8192 or 8192 + 16 != 8208:
        raise SystemExit("the README's byte count is not the change and lag words")
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
        raise SystemExit("%s is not a source tree root (set R89H_ROOT)" % ROOT)
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
            tmp = full + ".r89htmp"
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
        tmp = full + ".r89htmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
