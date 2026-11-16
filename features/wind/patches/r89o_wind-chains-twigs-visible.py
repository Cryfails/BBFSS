# r89o_wind-chains-twigs-visible: FEATURE fix inside the tree twigs (BB_WIND_TWIGS_TREES=1 path only; BB_WIND_TWIGS above 0).
# On top of r89n_twigs-visible (build 67..72). Two owner complaints (build 72 at 4K, 2026-11-16):
#   (A) "The chains on these coffins moves with the wind." (the chained coffin by an iron fence, graveyard)
#   (B) "I can't see the tree branches or twigs moving at all." (4 m/s and above)
#
# (A) CHAINS (and grilles, hooks, other metal props) MUST STAY STILL. What the data says (the owner's run log, 48650 lines):
#   with BB_WIND_TWIGS_TREES=1 every draw of a pipeline with the sway bit that is not a skinned plant (a static cut-out, a draw with a
#   small bone palette or a palette the GPU writes) goes through Rasterizer::WindTreesDraw: its vertices are read once and
#   BbWindTrees::ShapeOf decides by PROPORTIONS only (scale free: the log's own words are "model units are not metres: the draws'
#   models run from 0.01 to 27 units tall"): a thin base and a wider upper half is a tree; a refused shape that is not a slab and not a
#   box shell is a LIMB PIECE (r89k) when the draw is opaque. A chain, a grille bar or a prop with a thin base and a wider top passes
#   that test, and then the world-box judge (BbWindTwigs::SmallWhy) is LOOSE for the trees route (a mesh drawn once for each
#   instance has the union of all its places as its box; the 30 m box-many refusal is off with TREES): a chain model that is drawn at
#   every coffin gets the union box of the graveyard, which is tall and wide enough, so every chain instance is taken as a tree and
#   moved by the twig rule (and since r89n by up to 42 cm). The log's mesh lines show such small things taken: 'LIMB PIECE (model
#   height 2.48, trunk radius 0.406, crown radius 0.589, 7757 vertices)' (a 2.5 m tall thing, 1.2 m wide: a chain or a bar) and
#   'TREE-SHAPED (model height 3.37 / 3.48 ...)' next to the real trees (8.0 to 27.5) and real limb pieces (7.25 to 75).
#   RULE (the owner asks "find what separates them from weeds in the data"): a tree is at least ModelMin model units tall (default 3.0:
#   the smallest tree-shaped mesh of the log is 3.37, and the trunks and limbs the owner sees move are 7 or more), a limb piece at
#   least ModelMin + LimbExtra (4.0; the real limb pieces of the log are 7.25 or more, the chain-like one is 2.48). Read once from
#   BB_WIND_TWIGS_MIN_MODEL (0 turns the rule off: the old behaviour for the A/B twin). It is a test of the draw's own model, made in
#   WindTreesDraw after the verdict is cached: a float compare per candidate draw, nothing new is read from memory.
#   NOT PROVEN: that the owner's chains are taken by this route. The other candidate is the plant rule (LonePlant: a skinned cut-out
#   no sun shadow pass draws): if the chains still move with BB_WIND_TWIGS_MIN_MODEL at its default, they are skinned cut-outs and
#   the 'Wind twigs trees (r89o)' line (draws refused as small) tells it by staying 0 where the chains are. The slot job r89o-gy-nogate
#   (rule off) against r89o-gy-live (rule on) at the same camera is the A/B.
#
# (B) TWIGS VISIBLE. The log (build 72) shows the route taking tens of thousands of draws per 600 frames outdoors (up to 138600), and none
#   indoors or under cover (r117), so the words exist; the move was too small to see. r89n's numbers rested on guessed raw weights
#   (0.05 to 0.6 at a limb piece) that were never measured. Three constants, no new shader operation:
#   - BB_WIND_TWIGS_TREES_GAIN default 0.5 -> 1.0 (CPU only: the share of the sway word's ramp byte the trees route keeps; r89l halved
#     the move to stop the tearing of build 58, which r89m's soft cap has made impossible): every raw weight doubles;
#   - TwigBoost 6 -> 10 (the slope of the soft cap at 0: a small weight is multiplied by 10 instead of 6) and TwigCap 1.3 -> 1.5: the
#     soft cap y = w / (1 / 10 + w / 1.5). Raw weights after the gain 0.1 / 0.3 / 0.6 / 1.2 give y 0.60 / 1.00 / 1.20 / 1.33: at a gust
#     crest at 4 m/s (D 0.12 m x (TwigRest 0.2 + TwigPush 2.5) = 0.324 m) 19 / 32 / 39 / 43 cm, the largest 49 cm, the steady lean
#     between fronts 1.4 to 3 cm; at 1.5 m/s everything is 7 times less (3 to 6 cm at a crest: almost still); the hard bound by the
#     limits is 81 cm. Slow, broad and downwind (the push rule's fronts every 2.2 s at 4 m/s): no flutter was added, TwigRest and the
#     flutter stay (the test of PushTipAt needs the steady part under a tenth of the peak, TwigRest 0.2 keeps 7%).
#   - TREES AND LIMBS STAY STILL AT THE TRUNK: the mesh rule's weight (r89d) is 0 near the centre line; nothing changes there.
#   The owner's rules hold: 'The sway on the trees either should be removed or very subtle unless it's strong wind' (1.5 m/s is almost
#   still; 4 m/s is the strong wind), 'move in the direction of the wind', 'The wave should just be very subtle'.
#   NOT VERIFIED in the game: how the raw weight of the real limb pieces reads (the 0.1 to 1.2 above is the formula's); the live knob
#   BB_WIND_TWIGS (0.5 / 1 / 2 / 4, slot job set:/unset:) scales it, BB_WIND_TWIGS_TREES_GAIN / BB_WIND_TWIGS_MIN_MODEL are read once.
#
# SHADERS: TwigCap and TwigBoost are constants of the lifter's VertexSway and the recompiler's EmitVertexSway (r89n: CF(1.0f / W::TwigBoost),
#   f(1.0f / cap)): no line of either file changes, the numbers come from the header. The binary version BoostAdd 16000 -> 20000: no
#   cached shader of build 72 is reused (20000 differs from r89n's 16000 and from r89n + CapAdd 28000; 24000 / 32000 never collide).
# OFF: BB_WIND_TWIGS_TREES is 0 by default and then BbWindTrees::On() is false: WindTreesDraw is never called, the new line is never
#   printed. With the twigs off (BB_WIND_TWIGS 0 or unset) BinaryOffset is 0 as before: no shader, pipeline key or cache version differs.
# COST: none new on the GPU (same operations). CPU: one float compare per candidate draw in WindTreesDraw (and one counter); the periodic
#   line is one snprintf per 600 frames. Memory: one u64 in Stats.
# README: one new row (BB_WIND_TWIGS_MIN_MODEL), the CAP and GAIN rows' numbers. Log: 'Wind twigs trees (r89o)' every 600 frames with the
#   twigs trees route on (it is also the once-line: the existing OnceText has no room, its test caps it at 720 characters).
#
# STACKING: r89n_twigs-visible's own check/revert refuse after this (its text checks name TwigCap = 1.3f, BoostAdd = 16000, README row);
#   revert this script first. Use: python -I -X utf8 r89o_wind-chains-twigs-visible.py check | apply | revert (root from R89O_ROOT, else
#   <tree>). Files keep their line ends. Originals are kept in r89o_backup/ next to this script. No new file.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89o_backup")
ROOT = os.environ.get("R89O_ROOT") or "<tree>"
G = "engine/gpu/"
SWAY = G + "shim/bbport_wind_sway.h"
TWIGS = G + "shim/bbport_wind_twigs.h"
TREES = G + "shim/bbport_wind_trees.h"
EFFECTS = G + "shadps4/video_core/renderer_vulkan/vk_rasterizer_effects.cpp"
TEST = "engine/tests/test_wind_trees.cpp"
README = "README.md"

# ---------------------------------------------------------------- bbport_wind_sway.h
SW_OLD = "inline constexpr float TwigCap = 1.3f, TwigBoost = 6.0f, TwigCapProofMul = 1.0f;\n"
SW_NEW = ('''/// bbport (r89o_wind-chains-twigs-visible): TwigBoost 6 -> 10, TwigCap 1.3 -> 1.5 (the 4K clips of build 72 showed no twig motion). With the
/// trees' gain 1 (raw weights 0.1 / 0.3 / 0.6 / 1.2) y is 0.60 / 1.00 / 1.20 / 1.33: 19 / 32 / 39 / 43 cm at a gust crest at 4 m/s, at most
/// TwigCap x 0.324 = 49 cm (81 cm by the limits' bound); at 1.5 m/s 7 times less.
inline constexpr float TwigCap = 1.5f, TwigBoost = 10.0f, TwigCapProofMul = 1.0f;
''')

# ---------------------------------------------------------------- bbport_wind_twigs.h
TW_OLD = "inline constexpr std::uint32_t FixAdd = 4000, CapAdd = 8000, BoostAdd = 16000;\n"
TW_NEW = ('''/// bbport (r89o_wind-chains-twigs-visible): BoostAdd 16000 -> 20000 (the shaders' TwigBoost and TwigCap differ again: no cached shader of
/// build 72 is reused; 20000 and 28000 are not r89n's 16000 and 28000 of the cap on, and not r89m's 4000 and 12000).
inline constexpr std::uint32_t FixAdd = 4000, CapAdd = 8000, BoostAdd = 20000;
''')

# ---------------------------------------------------------------- bbport_wind_trees.h
TR1_OLD = "inline constexpr std::uint64_t RecheckFrames = 3600;     ///< a verdict is made again after this many frames\n"
TR1_NEW = ('''/// bbport (r89o_wind-chains-twigs-visible): a tree must be at least ModelMin units tall in its OWN model, a limb piece LimbExtra more
/// (BB_WIND_TWIGS_MIN_MODEL, read once; default ModelMinDefault; 0 turns the rule off). The shape rule is scale free, and the trees route's
/// world judge is loose (the union box of an instanced mesh), so a chain, a grille bar or a prop with a thin base and a wider top was
/// taken as a tree and swayed (the owner's coffin chains). The log's smallest tree-shaped mesh is 3.37, its real limb pieces 7.25 and
/// more, its chain-like piece 2.48.
inline constexpr float ModelMinDefault = 3.0f, LimbExtra = 1.0f;

[[nodiscard]] inline float ModelMin() {
    static const float v = std::clamp(W::ParseNumber(std::getenv("BB_WIND_TWIGS_MIN_MODEL"), ModelMinDefault), 0.0f, 30.0f);
    return v;
}

/// Whether a mesh whose model is `model_height` units tall (Shape::height) is big enough to be a tree (or a limb piece).
[[nodiscard]] inline bool SizeOk(float model_height, bool limb) {
    const float m = ModelMin();
    return !(m > 0.0f) || model_height >= (limb ? m + LimbExtra : m);
}

''' + TR1_OLD)

TR2_OLD = "    std::uint64_t limbs = 0;         ///< bbport (r89k): draws taken as limb pieces (counted in taken too)\n"
TR2_NEW = (TR2_OLD +
           "    std::uint64_t too_small = 0;     ///< bbport (r89o): tree-shaped or limb-piece draws refused as too small a model (SizeOk)\n")

TR3_OLD = "inline void MeshText(const Mesh& m, std::uint64_t key_stream, char* out, std::size_t size) {\n"
TR3_NEW = (r'''/// bbport (r89o_wind-chains-twigs-visible): the size rule's line, every ReportFrames frames with the trees route on.
inline void SizeLineText(const Stats& s, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs trees (r89o, BB_WIND_TWIGS_MIN_MODEL=%.1f): %llu draws refused in the last 600 frames as too small to be a "
                  "tree (a model under %.1f units tall, a limb piece under %.1f: chains, grilles, hooks and props stay still)",
                  static_cast<double>(ModelMin()), static_cast<unsigned long long>(s.too_small), static_cast<double>(ModelMin()),
                  static_cast<double>(ModelMin() + LimbExtra));
}

''' + TR3_OLD)

TR4_OLD = "inline constexpr float TreesGainDefault = 0.5f;\n"
TR4_NEW = ('''/// bbport (r89o_wind-chains-twigs-visible): 0.5 -> 1.0 (the 4K clips of build 72 showed no twig motion; the soft cap holds the move now).
inline constexpr float TreesGainDefault = 1.0f;
''')

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
EF1_OLD = ("    if (wind_shelter != nullptr && wind_shelter->CameraOpen() < BbWindTrees::OpenMin) {\n"
           "        ++st.indoors;\n")
EF1_NEW = ('''    // bbport (r89o_wind-chains-twigs-visible): a chain, a grille bar or a prop whose model is small is no tree, however its proportions
    // read (BbWindTrees::SizeOk, BB_WIND_TWIGS_MIN_MODEL): it stays still
    if (!BbWindTrees::SizeOk(mesh->shape.height, limb)) {
        ++st.too_small;
        return false;
    }
''' + EF1_OLD)

EF2_OLD = ('        BbReport::Printf("%s\\n", text);\n'
           "        trees_stats = {};\n")
EF2_NEW = ('        BbReport::Printf("%s\\n", text);\n'
           "        BbWindTrees::SizeLineText(trees_stats, text, sizeof(text)); // bbport (r89o_wind-chains-twigs-visible)\n"
           '        BbReport::Printf("%s\\n", text);\n'
           "        trees_stats = {};\n")

# ---------------------------------------------------------------- tests/test_wind_trees.cpp
TE1_OLD = '''        Expect(B::TreesGainDefault == 0.5f && B::TreesGain() >= 0.0f && B::TreesGain() <= 1.0f, "the trees' gain is a share");
'''
TE1_NEW = '''        Expect(B::TreesGainDefault == 1.0f && B::TreesGain() >= 0.0f && B::TreesGain() <= 1.0f, "the trees' gain is a share");
        // bbport (r89o_wind-chains-twigs-visible): the size rule (BB_WIND_TWIGS_MIN_MODEL unset in the test's environment: 3 units)
        Expect(B::ModelMinDefault == 3.0f && B::LimbExtra == 1.0f && B::ModelMin() == 3.0f, "the size rule's constants");
        Expect(B::SizeOk(8.0f, false) && B::SizeOk(3.37f, false) && B::SizeOk(3.0f, false) && !B::SizeOk(2.48f, false) &&
                   !B::SizeOk(2.48f, true) && !B::SizeOk(3.5f, true) && B::SizeOk(4.0f, true) && B::SizeOk(7.25f, true) &&
                   !B::SizeOk(std::numeric_limits<float>::quiet_NaN(), false) && !B::SizeOk(0.0f, false),
               "a tree needs 3 model units, a limb piece 4: the chain-like piece of 2.48 is refused, the log's smallest tree (3.37) is kept");
        {
            B::Stats sz;
            sz.too_small = 123;
            char sz_text[320];
            B::SizeLineText(sz, sz_text, sizeof(sz_text));
            Expect(std::strstr(sz_text, "r89o") != nullptr && std::strstr(sz_text, "123") != nullptr && std::strlen(sz_text) < 300,
                   "the size rule's line");
        }
'''
TE2_OLD = '''        Expect(std::fabs(S::TwigSoftCap(0.15f) - 0.53f) < 0.02f && std::fabs(S::TwigSoftCap(0.6f) - 0.95f) < 0.02f,
               "a typical limb piece's raw weight 0.15 gives y 0.53, 0.6 gives 0.95");
'''
TE2_NEW = '''        // bbport (r89o_wind-chains-twigs-visible): TwigBoost 10, TwigCap 1.5
        Expect(std::fabs(S::TwigSoftCap(0.15f) - 0.75f) < 0.02f && std::fabs(S::TwigSoftCap(0.6f) - 1.20f) < 0.02f &&
                   std::fabs(S::TwigSoftCap(0.3f) - 1.00f) < 0.02f,
               "a typical limb piece's raw weight 0.15 gives y 0.75, 0.3 gives 1.0, 0.6 gives 1.2");
'''
TE3_OLD = '''        Expect(most > 0.60 && most < 0.80, "the hard bound of the largest move is 60 to 80 cm");
        Expect(most * static_cast<double>(S::TwigCapProofMul) < 0.80, "the proof's largest move stays under 80 cm");
'''
TE3_NEW = '''        Expect(most > 0.70 && most < 0.90, "the hard bound of the largest move is 70 to 90 cm");
        Expect(most * static_cast<double>(S::TwigCapProofMul) < 0.90, "the proof's largest move stays under 90 cm");
'''
TE4_OLD = "        Expect(T::BoostAdd == 16000u && "
TE4_NEW = "        Expect(T::BoostAdd == 20000u && "

# ---------------------------------------------------------------- README
RM1_OLD = ("is `w / (1 / 6 + w / 1.3)` (r89n: boosted x6, capped at 1.3; r89m's `w / (1 + w / 0.28)` left the twigs under 3 cm, invisible in the 4K clip): "
           "smooth, never above 1.3, so a twig tip moves 8 to 31 cm in a full gust front at 4 m/s for a raw weight of 0.05 to 0.6 and at most 42 cm "
           "(`BB_WIND_SWAY` 1; 70 cm by the limits), the steady lean between fronts about 2 cm, and about 7 times less at 1.5 m/s (a few cm: almost still);")
RM1_NEW = ("is `w / (1 / 10 + w / 1.5)` (r89o: boosted x10, capped at 1.5; r89n had x6 and 1.3, r89m's `w / (1 + w / 0.28)` left the twigs under 3 cm: invisible in the 4K clips): "
           "smooth, never above 1.5, so a twig tip moves 19 to 43 cm in a full gust front at 4 m/s for a raw weight of 0.1 to 1.2 (with `BB_WIND_TWIGS_TREES_GAIN` 1) and at most 49 cm "
           "(`BB_WIND_SWAY` 1; 81 cm by the limits), the steady lean between fronts 1.4 to 3 cm, and about 7 times less at 1.5 m/s (a few cm: almost still);")
RM2_OLD = ("`0.5` (default) is a few cm at 4 m/s (a 6 m piece: tip about 2.3 cm in the lean and 4.6 cm at the gust front, at most about 8 cm for the tallest pieces), "
           "slow and zero at the trunk (the weight rule is unchanged); `1` gives r89k's move back; `0` stops it. A change of the word on the CPU: no shader, "
           "pipeline key or cache version differs. Read once | `0.5` |\n")
RM2_NEW = ("`1` (default since r89o; `0.5` before, which the 4K clips showed as no motion at all) keeps the whole word: with the boosted cap a tip moves 19 to 43 cm at a gust crest "
           "at 4 m/s (the `BB_WIND_TWIGS_CAP` row), slow and zero at the trunk (the weight rule is unchanged); `0.5` gives half the raw weight, `0` stops it. "
           "A change of the word on the CPU: no shader, pipeline key or cache version differs. Read once | `1` |\n"
           "| `BB_WIND_TWIGS_MIN_MODEL` | The smallest thing the trees route takes (r89o; needs `BB_WIND_TWIGS_TREES=1`): a draw is a tree only when the model of its own "
           "vertices is at least this many units tall, a limb piece when it is one unit taller (model units are about metres for trees: the trees of a graveyard run from 3.4 to 27, "
           "their limb pieces from 7). The shape rule reads proportions only and the trees route's world judge is loose (the union box of an instanced mesh), so a chain, a grille bar "
           "or a prop with a thin base and a wider top was taken for a tree and swayed with the wind (the chains of the coffins); with this rule they stay still. "
           "`0` takes the old rule back (for an A/B). The `Wind twigs trees (r89o)` line counts the draws it refused every 600 frames. Read once; CPU only, no shader differs | `3` |\n")

EDITS = {
    SWAY: [(SW_OLD, SW_NEW)],
    TWIGS: [(TW_OLD, TW_NEW)],
    TREES: [(TR1_OLD, TR1_NEW), (TR2_OLD, TR2_NEW), (TR3_OLD, TR3_NEW), (TR4_OLD, TR4_NEW)],
    EFFECTS: [(EF1_OLD, EF1_NEW), (EF2_OLD, EF2_NEW)],
    TEST: [(TE1_OLD, TE1_NEW), (TE2_OLD, TE2_NEW), (TE3_OLD, TE3_NEW), (TE4_OLD, TE4_NEW)],
    README: [(RM1_OLD, RM1_NEW), (RM2_OLD, RM2_NEW)],
}

CHECKS = {
    SWAY: [("TwigCap = 1.5f, TwigBoost = 10.0f, TwigCapProofMul = 1.0f;", 1), ("TwigCap = 1.3f", 0), ("1.0f / TwigBoost + std::fabs(w) / cap", 1)],
    TWIGS: [("BoostAdd = 20000;", 1), ("BoostAdd = 16000;", 0), ("FixAdd + BoostAdd + (CapOn() ? CapAdd : 0u)", 1)],
    TREES: [("SizeOk(float model_height, bool limb)", 1), ("BB_WIND_TWIGS_MIN_MODEL", 3), ("too_small", 2), ("TreesGainDefault = 1.0f;", 1),
            ("SizeLineText(const Stats& s", 1)],
    EFFECTS: [("BbWindTrees::SizeOk(mesh->shape.height, limb)", 1), ("BbWindTrees::SizeLineText(trees_stats, text, sizeof(text));", 1)],
    TEST: [("T::BoostAdd == 20000u", 1), ("B::TreesGainDefault == 1.0f", 1), ("B::SizeOk(", 10), ("wind-trees-test: ok", 1)],
    README: [("`w / (1 / 10 + w / 1.5)`", 1), ("| `BB_WIND_TWIGS_MIN_MODEL` |", 1), ("`w / (1 / 6 + w / 1.3)`", 0)],
}

# Numbers written twice: the header's constants and the README text.
TIES = [("TwigCap = 1.5f, TwigBoost = 10.0f", "| `BB_WIND_TWIGS_CAP`", "`w / (1 / 10 + w / 1.5)`"),
        ("TreesGainDefault = 1.0f;", "| `BB_WIND_TWIGS_TREES_GAIN`", "`1` (default since r89o"),
        ("ModelMinDefault = 3.0f", "| `BB_WIND_TWIGS_MIN_MODEL`", "| `3` |")]


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
        src = texts[SWAY] if const.startswith("TwigCap") else (texts[TREES])
        if src.count(const) != 1 or value not in rows:
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
        raise SystemExit("%s is not a source tree root (set R89O_ROOT)" % ROOT)
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
            tmp = full + ".r89otmp"
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
        tmp = full + ".r89otmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
