# r89k_twigs-opaque-word: FEATURE fix (BB_WIND_TWIGS_LIMBS, default 1 but only with BB_WIND_TWIGS_TREES=1, which stays 0) +
# TOOL fixes of r89j's pixel pick (BB_WIND_TWIGS_PICK*). On top of r89j (build 55), r89i, r89h, r89g.
#
# THE OWNER: "I think if the small branches on the trees moved slightly due to wind that would look great"; "The wave
# should just be very subtle".
# BUILD 55 (r89j, read from b55_s1.log): the rule counted 37200 of 269400 candidate draws as tree-shaped (61 meshes of 6.6
# to 27.5 m), 0 indoors; but the pick named, for the left tree, opaque GPU-palette draws (vs:ps c829ee58:dbb222eb, 154 and
# 149 of 504 G-buffer draws; 7620368b:8aba0ecd, draw 198) whose own shape verdict is "no-spread" / "stout" (refused by
# the shape rule, "twig book: no entry"): the visible bare-tree branches are pieces of a tree (a draw of 2043 or 35898
# indices of a stream of 90094 vertices), not whole tree-shaped meshes, so they never got a sway word; the 26 meshes that
# did get one (candidate TREE lines, 27 draws a frame) are other, mostly distant, draws. No proof stain, no branch motion.
# The pick missed the right tree, the trunk, the cathedral and the ground (all x >= 650; both x <= 480 pixels hit).
#
# FEATURE (needs BB_WIND_TWIGS_TREES=1; BB_WIND_TWIGS_LIMBS=0 gives r89j back, default 1): a draw the shape rule refuses
# is tried as a LIMB PIECE of a tree when ALL of these hold: the pipeline's pixel shader does not discard (an opaque
# draw: bark and branches; the leaf cards keep their own rule), the camera is outdoors (r117's field, as for trees), at
# least 64 vertices were read (the draw has 120+), its smallest bounding-box extent is at least 0.08 of its largest (not
# a slab, a pole, a column) and at most BB_WIND_TWIGS_LIMB_BOXY (0.10) of its vertices lie within 0.01 of an extent from a
# face of its bounding box (a wall, a facade or a building is a shell: most of its vertices lie on a face; a tree's
# branches fill the box thinly: about 1 percent in the twin's branchy mesh, 100 percent for a shell). Such a draw is a
# mesh of its own exactly like a tree-shaped one (its vertex range is its sway slot key) and goes to the GPU's world box
# judge (BbWindTwigs::SmallWhy, loose: height and stillness only, over 68 frames) with ONE change: a limb piece must be at
# least LimbMinH = 3 m tall in the world, not 4 (the lean's tree weight starts at 2 m: BbWindSway::TreeLo). The mesh rule
# (height in the mesh x distance from the mesh's centre line) puts the weight on the outer upper part of the piece.
# A refused piece costs a lookup (its slot goes back at once). The shaders, pipeline keys and cache versions do not change.
#
# TOOL (BB_WIND_TWIGS_PICK, goes to the test-tools branch): (1) the patch is 5 x 5 pixels (was 3 x 3); (2) a pixel that no
# depth-writing draw covers says how many draws had samples there ("(N of them had samples ...)") and names the last
# draw with samples although it wrote no depth ("under:" line); (3) a note line per pixel and frame: the frame, the
# camera (the ray traced scene's), the picture and the patch, how many G-buffer scissors met the patch and how many did
# not (all not = the patch lies outside every draw's scissor: a coordinate mismatch, not an empty pixel); (4)
# BB_WIND_TWIGS_PICK_REPEAT=N (default 0): the sweep starts again every N frames (at least 2 frames x pixels), so a pick
# lost to a transient (a camera move in the first seconds) is tried again.
#
# OFF (default): BB_WIND_TWIGS_TREES=0 keeps TreesWanted() false: WindTreesDraw is never called, LimbOn() is false, the new
# member is never read; BB_WIND_TWIGS_PICK unset keeps PickOn() false: the new counters are never written. No shader, no
# pipeline key, no cache version changes in any state. Judging cost with TREES=1 (estimate, not measured): per new draw
# range one more pass over <= 4096 sampled vertices (one bounding box, one face count: about 0.05 ms once, held 3600
# frames); limb pieces that pass are measured by the GPU for 68 frames (the sway code runs for their vertices with ramp 0:
# atomic min/max of 6 keys a vertex; at most 96 meshes at once with the trees: BbWindTwigs::SmallLiveMax) and then either
# sway (the sway code, a few ALU ops a vertex) or go back to a lookup. Memory: a few bytes a mesh in the 4096-mesh book.
#
# SHARED LINES TOUCHED (two lanes of this wave edit the sway files): only r89j's own lines. vk_rasterizer_effects.cpp: the
# WindTreesDraw call in WindSwayWord (one argument added), WindTreesDraw itself, WindTreesPickFrameEnd (r89j's), two lines of
# WindTwigWord's `if (small)` head (one line added), nothing of the hang code. vk_rasterizer.h: the WindTreesDraw
# declaration and r89j's member block. vk_rasterizer.cpp: r89j's pick scissor block. bbport_wind_twigs.h: SmallWhy (a
# default parameter), Entry (one member), Judge (one argument). README.md: r89j's two rows and three new rows before
# the BB_WIND_TWIGS_CENSUS row.
#
# NOT TESTED in the game: whether the limb rule takes the pieces of the left and right trees and not the cathedral facade
# (the jobs say), whether the weights of a piece are visible (tip move 4.5 cm at 4 m/s for a piece of 6 m, scaled by
# height/6 m up to 7), whether the proof tint exists on these pipelines (the tint is in lifter shaders only; a recompiler
# vertex stage moves x5 without it), and why the pick missed (the new note line says).
#
# Use: python -I -X utf8 r89k_twigs-opaque-word.py check | apply | revert (root from R89K_ROOT, else <tree>).
# Files keep their line ends. Originals are kept in r89k_backup/ next to this script. No new file.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89k_backup")
ROOT = os.environ.get("R89K_ROOT") or "<tree>"
G = "engine/gpu/"
R = G + "shadps4/video_core/renderer_vulkan/"
TWIGS = G + "shim/bbport_wind_twigs.h"
TREES = G + "shim/bbport_wind_trees.h"
RASTH = R + "vk_rasterizer.h"
RAST = R + "vk_rasterizer.cpp"
EFFECTS = R + "vk_rasterizer_effects.cpp"
TEST = "engine/tests/test_wind_trees.cpp"
README = "README.md"

NEW_FILES = {}

# ---------------------------------------------------------------- bbport_wind_twigs.h
TW_CONST_OLD = "inline constexpr float SmallMinH = 4.0f, SmallMaxH = TreeMax;\n"
TW_CONST_NEW = TW_CONST_OLD + (
    "/// bbport (r89k_twigs-opaque-word): a limb piece of a tree (BbWindTrees::LimbOf) must be at least this tall in the world\n"
    "/// (the lean's tree weight starts at W::TreeLo)\n"
    "inline constexpr float LimbMinH = 3.0f;\n")

TW_WHY_OLD = ("[[nodiscard]] inline const char* SmallWhy(const Measure& m, float moved, std::uint32_t per_frame,\n"
              "                                          bool loose) {\n")
TW_WHY_NEW = ("[[nodiscard]] inline const char* SmallWhy(const Measure& m, float moved, std::uint32_t per_frame,\n"
              "                                          bool loose, float min_height = SmallMinH) {\n")

TW_SHORT_OLD = ("    if (h < SmallMinH) {\n"
                "        return \"short\";\n")
TW_SHORT_NEW = ("    if (h < min_height) { // bbport (r89k_twigs-opaque-word): LimbMinH for a limb piece\n"
                "        return \"short\";\n")

TW_ENTRY_OLD = "    bool small = false, loose = false, logged = false;\n"
TW_ENTRY_NEW = TW_ENTRY_OLD + "    bool limb = false;                     ///< bbport (r89k_twigs-opaque-word): a limb piece (BbWindTrees::LimbOf)\n"

TW_JUDGE_OLD = "        e.why = SmallWhy(m, Moved(e.snap, m), e.per_frame, e.loose);\n"
TW_JUDGE_NEW = "        e.why = SmallWhy(m, Moved(e.snap, m), e.per_frame, e.loose, e.limb ? LimbMinH : SmallMinH);\n"

TW_LINE_OLD = ('                  "Wind twigs (r89e) candidate %s: %s, verts %u, far %.2f, palette %d, vs %08x ps %08x, "\n'
               '                  "draws %llu per frame %u, why %s",\n'
               '                  e.verdict == Verdict::Tree ? "TREE" : "refused", shape, info ? info->verts : 0u,\n')
TW_LINE_NEW = ('                  "Wind twigs (r89e) candidate %s%s: %s, verts %u, far %.2f, palette %d, vs %08x ps %08x, "\n'
               '                  "draws %llu per frame %u, why %s",\n'
               '                  e.verdict == Verdict::Tree ? "TREE" : "refused", e.limb ? " (limb piece)" : "", shape,\n'
               '                  info ? info->verts : 0u,\n')

# ---------------------------------------------------------------- bbport_wind_trees.h
TR_CONST_OLD = "inline constexpr unsigned MeshLines = 12;                ///< verdict lines logged at most\n"
TR_CONST_NEW = TR_CONST_OLD + (
    "\n"
    "/// bbport (r89k_twigs-opaque-word): the limb rule (BB_WIND_TWIGS_LIMBS). An opaque draw the shape rule refuses may be a\n"
    "/// limb piece of a tree: at least LimbSamplesMin vertices read, its smallest bounding-box extent at least LimbFlatMin of\n"
    "/// its largest (not a slab, a pole or a column), and at most BB_WIND_TWIGS_LIMB_BOXY (default LimbBoxyDefault) of its\n"
    "/// vertices within LimbBand of an extent from a face of the box (a wall, a facade or a building is a shell: most of its\n"
    "/// vertices lie on a face). The world box then judges it (BbWindTwigs::SmallWhy, at least BbWindTwigs::LimbMinH tall).\n"
    "inline constexpr std::size_t LimbSamplesMin = 64;\n"
    "inline constexpr float LimbFlatMin = 0.08f;\n"
    "inline constexpr float LimbBand = 0.01f;\n"
    "inline constexpr float LimbBoxyDefault = 0.10f;\n"
    "inline constexpr unsigned LimbLines = 16;                ///< limb verdict lines logged at most\n")

TR_HALF_OLD = "inline constexpr int PickHalf = 1;                       ///< the patch is 2 * PickHalf + 1 pixels wide\n"
TR_HALF_NEW = "inline constexpr int PickHalf = 2;                       ///< the patch is 2 * PickHalf + 1 pixels wide (r89k: 5, was 3)\n"

TR_BOOK_OLD = "// ------------------------------------------------------------------------------------------- the book\n"
TR_LIMB_NEW = (
    "// ------------------------------------------------------------------------------------------- the limb rule\n"
    "\n"
    "/// bbport (r89k_twigs-opaque-word): BB_WIND_TWIGS_LIMBS (read once; default 1, 0 gives r89j back): whether a draw the\n"
    "/// shape rule refuses may still be taken as a limb piece of a tree. Needs BB_WIND_TWIGS_TREES.\n"
    "[[nodiscard]] inline bool LimbOn() {\n"
    "    static const bool on = T::TreesWanted() && W::ParseNumber(std::getenv(\"BB_WIND_TWIGS_LIMBS\"), 1.0f) >= 0.5f;\n"
    "    return on;\n"
    "}\n"
    "\n"
    "/// BB_WIND_TWIGS_LIMB_BOXY (read once; 0 to 1, default LimbBoxyDefault): the most vertices on a box face a limb piece has.\n"
    "[[nodiscard]] inline float LimbBoxyMax() {\n"
    "    static const float v = std::clamp(W::ParseNumber(std::getenv(\"BB_WIND_TWIGS_LIMB_BOXY\"), LimbBoxyDefault), 0.0f, 1.0f);\n"
    "    return v;\n"
    "}\n"
    "\n"
    "/// What the limb rule read of a draw's vertices.\n"
    "struct Limb {\n"
    "    bool ok = false;\n"
    "    float boxy = 0.0f;  ///< the share of the vertices within LimbBand of an extent from a face of the bounding box\n"
    "    float flat = 0.0f;  ///< the smallest extent over the largest\n"
    "    const char* why = \"few\"; ///< a string literal: \"few\", \"point\", \"flat\", \"boxy\"; nullptr when ok\n"
    "};\n"
    "\n"
    "/// Whether `count` vertices (x, y, z floats, finite) are a limb piece: see LimbSamplesMin and the constants. A scale-free\n"
    "/// rule (model units are not metres: the draws' models run from 0.01 to 27 units tall).\n"
    "[[nodiscard]] inline Limb LimbOf(const float* xyz, std::size_t count, float boxy_max = LimbBoxyDefault) {\n"
    "    Limb l;\n"
    "    if (xyz == nullptr || count < LimbSamplesMin) {\n"
    "        return l;\n"
    "    }\n"
    "    float lo[3] = {xyz[0], xyz[1], xyz[2]};\n"
    "    float hi[3] = {xyz[0], xyz[1], xyz[2]};\n"
    "    for (std::size_t i = 1; i < count; ++i) {\n"
    "        for (int a = 0; a < 3; ++a) {\n"
    "            lo[a] = std::min(lo[a], xyz[i * 3 + static_cast<std::size_t>(a)]);\n"
    "            hi[a] = std::max(hi[a], xyz[i * 3 + static_cast<std::size_t>(a)]);\n"
    "        }\n"
    "    }\n"
    "    const float ext[3] = {hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]};\n"
    "    const float ext_max = std::max({ext[0], ext[1], ext[2]});\n"
    "    const float ext_min = std::min({ext[0], ext[1], ext[2]});\n"
    "    if (!(ext_max > 0.0f) || !std::isfinite(ext_max)) {\n"
    "        l.why = \"point\";\n"
    "        return l;\n"
    "    }\n"
    "    l.flat = ext_min / ext_max;\n"
    "    if (!(l.flat >= LimbFlatMin)) {\n"
    "        l.why = \"flat\";\n"
    "        return l;\n"
    "    }\n"
    "    std::size_t on_face = 0;\n"
    "    for (std::size_t i = 0; i < count; ++i) {\n"
    "        bool face = false;\n"
    "        for (std::size_t a = 0; a < 3; ++a) {\n"
    "            const float v = xyz[i * 3 + a];\n"
    "            face = face || std::min(v - lo[a], hi[a] - v) <= LimbBand * ext[a];\n"
    "        }\n"
    "        on_face += face ? 1u : 0u;\n"
    "    }\n"
    "    l.boxy = static_cast<float>(on_face) / static_cast<float>(count);\n"
    "    if (!(l.boxy <= boxy_max)) {\n"
    "        l.why = \"boxy\";\n"
    "        return l;\n"
    "    }\n"
    "    l.ok = true;\n"
    "    l.why = nullptr;\n"
    "    return l;\n"
    "}\n"
    "\n") + TR_BOOK_OLD

TR_MESH_OLD = "    const char* why = \"unread\";       ///< a string literal: why it is no tree\n"
TR_MESH_NEW = TR_MESH_OLD + (
    "    bool limb = false;                ///< bbport (r89k_twigs-opaque-word): refused by shape, but a limb piece (LimbOf)\n"
    "    float boxy = 0.0f;                ///< the limb rule's share of vertices on a box face\n"
    "    const char* limb_why = \"\";        ///< a string literal: \"\" not tried, \"ok\", or why the limb rule refused\n")

TR_STATS_OLD = "    std::uint64_t new_meshes = 0, tree_meshes = 0, refused_meshes = 0;\n};\n"
TR_STATS_NEW = ("    std::uint64_t new_meshes = 0, tree_meshes = 0, refused_meshes = 0;\n"
                "    std::uint64_t limbs = 0;         ///< bbport (r89k): draws taken as limb pieces (counted in taken too)\n"
                "    std::uint64_t limb_new = 0, limb_refused = 0; ///< ranges judged limb pieces; refused by the limb rule too\n"
                "};\n")

TR_LINE_OLD = '''inline void LineText(const Stats& s, const Book& book, unsigned frames, char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(out, size,
                  "Wind twigs trees (r89j): in %u frames %llu candidate draws: %llu taken (tree-shaped), %llu refused "
                  "(shape), %llu indoors, %llu unread; %llu draw ranges judged (%llu tree-shaped, %llu not); book %zu "
                  "meshes, %zu tree-shaped",
                  frames, n(s.draws), n(s.taken), n(s.refused), n(s.indoors), n(s.unread), n(s.new_meshes),
                  n(s.tree_meshes), n(s.refused_meshes), book.Size(), book.Trees());
}
'''
TR_LINE_NEW = '''inline void LineText(const Stats& s, const Book& book, unsigned frames, unsigned limb_meshes, unsigned limb_trees,
                     char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(out, size,
                  "Wind twigs trees (r89j): in %u frames %llu candidate draws: %llu taken (tree-shaped or limb piece, r89k: "
                  "%llu limb), %llu refused (shape), %llu indoors, %llu unread; %llu draw ranges judged (%llu tree-shaped, "
                  "%llu not; %llu limb pieces, %llu refused by the limb rule too); book %zu meshes, %zu tree-shaped; limb "
                  "meshes in the twig book %u, judged trees by their world box %u",
                  frames, n(s.draws), n(s.taken), n(s.limbs), n(s.refused), n(s.indoors), n(s.unread), n(s.new_meshes),
                  n(s.tree_meshes), n(s.refused_meshes), n(s.limb_new), n(s.limb_refused), book.Size(), book.Trees(),
                  limb_meshes, limb_trees);
}
'''

TR_MESHTEXT_OLD = '''inline void MeshText(const Mesh& m, std::uint64_t key_stream, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs trees (r89j) mesh: stream %llx, vertex range at %llx, %u vertices: %s (model height "
                  "%.2f, trunk radius %.3f, crown radius %.3f, up axis %d%s%s)",
                  static_cast<unsigned long long>(key_stream), static_cast<unsigned long long>(m.addr), m.verts,
                  m.tree ? "TREE-SHAPED" : "refused", static_cast<double>(m.shape.height),
                  static_cast<double>(m.shape.trunk), static_cast<double>(m.shape.crown), m.shape.up,
                  m.tree ? "" : ", why ", m.tree ? "" : m.why);
}
'''
TR_MESHTEXT_NEW = '''inline void MeshText(const Mesh& m, std::uint64_t key_stream, char* out, std::size_t size) {
    char limb[96] = ""; // bbport (r89k_twigs-opaque-word): what the limb rule made of a shape refusal
    if (!m.tree && m.limb_why != nullptr && m.limb_why[0] != '\\0') {
        std::snprintf(limb, sizeof(limb), "; limb rule: %s, boxy %.3f", m.limb_why, static_cast<double>(m.boxy));
    }
    std::snprintf(out, size,
                  "Wind twigs trees (r89j) mesh: stream %llx, vertex range at %llx, %u vertices: %s (model height "
                  "%.2f, trunk radius %.3f, crown radius %.3f, up axis %d%s%s%s)",
                  static_cast<unsigned long long>(key_stream), static_cast<unsigned long long>(m.addr), m.verts,
                  m.tree ? "TREE-SHAPED" : (m.limb ? "LIMB PIECE" : "refused"), static_cast<double>(m.shape.height),
                  static_cast<double>(m.shape.trunk), static_cast<double>(m.shape.crown), m.shape.up,
                  m.tree ? "" : ", shape why ", m.tree ? "" : m.why, limb);
}
'''

TR_KNOB_OLD = "    std::uint64_t start = PickFrameDefault;\n};\n"
TR_KNOB_NEW = ("    std::uint64_t start = PickFrameDefault;\n"
               "    std::uint64_t repeat = 0; ///< bbport (r89k): the sweep starts again every this many frames (0: once)\n"
               "};\n")

TR_PARSE_SIG_OLD = "[[nodiscard]] inline PickKnob ParsePick(const char* list, const char* size, const char* frame) {\n"
TR_PARSE_SIG_NEW = ("[[nodiscard]] inline PickKnob ParsePick(const char* list, const char* size, const char* frame,\n"
                    "                                      const char* repeat = nullptr) {\n")

TR_PARSE_TAIL_OLD = ("    k.start = f >= 0.0f && f <= 1.0e7f ? static_cast<std::uint64_t>(f) : PickFrameDefault;\n"
                     "    return k;\n"
                     "}\n")
TR_PARSE_TAIL_NEW = ("    k.start = f >= 0.0f && f <= 1.0e7f ? static_cast<std::uint64_t>(f) : PickFrameDefault;\n"
                     "    // bbport (r89k_twigs-opaque-word): BB_WIND_TWIGS_PICK_REPEAT: at least a sweep long (PickFramesPerPoint x points)\n"
                     "    const float rep = W::ParseNumber(repeat, 0.0f);\n"
                     "    if (rep > 0.0f && rep <= 1.0e7f && static_cast<std::uint64_t>(rep) >= k.count * PickFramesPerPoint) {\n"
                     "        k.repeat = static_cast<std::uint64_t>(rep);\n"
                     "    }\n"
                     "    return k;\n"
                     "}\n")

TR_GETENV_OLD = "std::getenv(\"BB_WIND_TWIGS_PICK_FRAME\"));\n"
TR_GETENV_NEW = ("std::getenv(\"BB_WIND_TWIGS_PICK_FRAME\"),\n"
                 "                                           std::getenv(\"BB_WIND_TWIGS_PICK_REPEAT\"));\n")

TR_POINTAT_OLD = '''[[nodiscard]] inline int PointAt(std::uint64_t frame, std::uint64_t start, std::size_t count) {
    if (frame < start) {
        return -1;
    }
    const std::uint64_t k = (frame - start) / PickFramesPerPoint;
    return k < count ? static_cast<int>(k) : -1;
}
'''
TR_POINTAT_NEW = '''[[nodiscard]] inline int PointAt(std::uint64_t frame, std::uint64_t start, std::size_t count,
                                std::uint64_t repeat = 0) {
    if (frame < start) {
        return -1;
    }
    std::uint64_t d = frame - start;
    if (repeat != 0) { // bbport (r89k_twigs-opaque-word): the sweep starts again every `repeat` frames
        d %= repeat;
    }
    const std::uint64_t k = d / PickFramesPerPoint;
    return k < count ? static_cast<int>(k) : -1;
}
'''

TR_RESULT_OLD = "    std::size_t under_n = 0;         ///< earlier draws that passed as well (most recent first)\n};\n"
TR_RESULT_NEW = ("    std::size_t under_n = 0;         ///< earlier draws that passed as well (most recent first)\n"
                 "    bool any = false;                ///< bbport (r89k): some draw had samples (whether it wrote depth or not)\n"
                 "    std::size_t any_row = 0;         ///< the last draw with samples\n"
                 "};\n")

TR_WINNER_OLD = '''    for (std::size_t i = draws.size(); i-- > 0;) {
        if (counts[i] == 0) {
            continue;
        }
        ++r.passed;
        if (!r.found && draws[i].depth_write) {
'''
TR_WINNER_NEW = '''    for (std::size_t i = draws.size(); i-- > 0;) {
        if (counts[i] == 0) {
            continue;
        }
        ++r.passed;
        if (!r.any) { // bbport (r89k_twigs-opaque-word): the last draw with samples, for the fallback line
            r.any = true;
            r.any_row = i;
        }
        if (!r.found && draws[i].depth_write) {
'''

TR_NONE_OLD = '''inline void PickNoneLine(const Point& pt, const Rect& rect, std::size_t total, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs pick (r89j): pixel %d,%d (render %d,%d): no G-buffer draw of %zu wrote depth there "
                  "(sky, or the patch missed)",
                  pt.x, pt.y, rect.cx, rect.cy, total);
}
'''
TR_NONE_NEW = '''inline void PickNoneLine(const Point& pt, const Rect& rect, std::size_t total, std::size_t passed, char* out,
                         std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs pick (r89j): pixel %d,%d (render %d,%d): no G-buffer draw of %zu wrote depth there "
                  "(%zu of them had samples at the patch: %s)",
                  pt.x, pt.y, rect.cx, rect.cy, total, passed,
                  passed == 0 ? "the patch drew nothing: sky, or the patch missed every draw"
                              : "none with depth write: a later pass wrote the depth");
}

/// bbport (r89k_twigs-opaque-word): the note line of a pick pixel: the frame, the camera, the picture and the patch, and
/// how many G-buffer scissors met the patch (`meet`) or did not (`apart`: all apart = the patch lies outside every draw's
/// scissor, a coordinate mismatch, not an empty pixel); `queried` draws had a query. `camera` three floats, or nullptr.
inline void PickNoteLine(const Point& pt, const Rect& rect, std::uint32_t out_w, std::uint32_t out_h, std::uint64_t frame,
                         bool camera_ok, const float* camera, std::uint32_t meet, std::uint32_t apart,
                         std::size_t queried, char* out, std::size_t size) {
    char cam[96] = "unread";
    if (camera_ok && camera != nullptr) {
        std::snprintf(cam, sizeof(cam), "%.1f %.1f %.1f", static_cast<double>(camera[0]), static_cast<double>(camera[1]),
                      static_cast<double>(camera[2]));
    }
    std::snprintf(out, size,
                  "Wind twigs pick (r89k): pixel %d,%d: frame %llu, camera %s, picture %ux%u, patch x %d..%d y %d..%d "
                  "(%dx%d, centre %d,%d), G-buffer scissors that met the patch %u, that did not %u, draws with a query %zu",
                  pt.x, pt.y, static_cast<unsigned long long>(frame), cam, out_w, out_h, rect.x, rect.x + rect.w - 1, rect.y,
                  rect.y + rect.h - 1, rect.w, rect.h, rect.cx, rect.cy, meet, apart, queried);
}
'''

TR_ONCE_OLD = '''inline void PickOnceText(const PickKnob& k, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs pick (r89j, TOOL, BB_WIND_TWIGS_PICK): %zu pixel(s) of a %ux%u picture, from frame %llu "
                  "on, %llu frames a pixel: those frames draw only a %dx%d patch of the G-buffer (the picture is "
                  "broken for them); an occlusion query a draw names the last draw that passed the depth test with "
                  "depth write there",
                  k.count, k.out_w, k.out_h, static_cast<unsigned long long>(k.start),
                  static_cast<unsigned long long>(PickFramesPerPoint), 2 * PickHalf + 1, 2 * PickHalf + 1);
}
'''
TR_ONCE_NEW = '''inline void PickOnceText(const PickKnob& k, char* out, std::size_t size) {
    char again[64] = "";
    if (k.repeat != 0) { // bbport (r89k_twigs-opaque-word)
        std::snprintf(again, sizeof(again), "; the sweep starts again every %llu frames", static_cast<unsigned long long>(k.repeat));
    }
    std::snprintf(out, size,
                  "Wind twigs pick (r89j, TOOL, BB_WIND_TWIGS_PICK): %zu pixel(s) of a %ux%u picture, from frame %llu "
                  "on, %llu frames a pixel: those frames draw only a %dx%d patch of the G-buffer (the picture is "
                  "broken for them); an occlusion query a draw names the last draw that passed the depth test with "
                  "depth write there%s",
                  k.count, k.out_w, k.out_h, static_cast<unsigned long long>(k.start),
                  static_cast<unsigned long long>(PickFramesPerPoint), 2 * PickHalf + 1, 2 * PickHalf + 1, again);
}
'''

# ---------------------------------------------------------------- vk_rasterizer.h
RH_DECL_OLD = "    bool WindTreesDraw(u64& positions, u32& positions_size, u32 stride, bool floats);\n"
RH_DECL_NEW = ("    /// bbport (r89k_twigs-opaque-word): `opaque` (the pixel shader does not discard): a draw the shape rule refuses may\n"
               "    /// then be taken as a limb piece of a tree (BbWindTrees::LimbOf; BB_WIND_TWIGS_LIMBS)\n"
               "    bool WindTreesDraw(u64& positions, u32& positions_size, u32 stride, bool floats, bool opaque);\n")

RH_LINES_OLD = "    unsigned trees_lines = 0;\n"
RH_LINES_NEW = (RH_LINES_OLD +
                "    bool trees_last_limb = false; ///< bbport (r89k_twigs-opaque-word): the draw WindTreesDraw took last is a limb piece\n")

RH_GROUP_OLD = "        u32 skipped = 0;\n        BbWindTrees::Rect rect{};\n"
RH_GROUP_NEW = ("        u32 skipped = 0;\n"
                "        u32 meet = 0, apart = 0; ///< bbport (r89k): G-buffer scissors that met / missed the patch\n"
                "        u64 frame = 0;           ///< the frame it was drawn in\n"
                "        bool cam_ok = false;\n"
                "        std::array<float, 3> cam{};\n"
                "        BbWindTrees::Rect rect{};\n")

RH_RECT_OLD = "    vk::Rect2D trees_pick_rect{};\n"
RH_RECT_NEW = (RH_RECT_OLD +
               "    /// bbport (r89k): scissors that met / missed this frame's patch; mutable: UpdateViewportScissorState is const\n"
               "    mutable u32 trees_pick_meet = 0, trees_pick_apart = 0;\n")

# ---------------------------------------------------------------- vk_rasterizer.cpp
RC_OLD = ("            scissor = vk::Rect2D{.offset = {x0, y0}, .extent = {u32(std::max(x1 - x0, 0)), u32(std::max(y1 - y0, 0))}};\n"
          "        }\n"
          "        scissors.push_back(scissor);\n")
RC_NEW = ("            scissor = vk::Rect2D{.offset = {x0, y0}, .extent = {u32(std::max(x1 - x0, 0)), u32(std::max(y1 - y0, 0))}};\n"
          "            // bbport (r89k_twigs-opaque-word): how many G-buffer scissors met the patch (the pick's note line)\n"
          "            if (scissor.extent.width != 0 && scissor.extent.height != 0) {\n"
          "                ++trees_pick_meet;\n"
          "            } else {\n"
          "                ++trees_pick_apart;\n"
          "            }\n"
          "        }\n"
          "        scissors.push_back(scissor);\n")

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
EF_CALL_OLD = ("    if (small_palette >= 0 && !hang_static && BbWindTwigs::TreesWanted() &&\n"
               "        !WindTreesDraw(positions, positions_size, positions_stride, positions_floats)) {\n"
               "        return 0;\n"
               "    }\n")
EF_CALL_NEW = ("    if (small_palette >= 0 && !hang_static && BbWindTwigs::TreesWanted() &&\n"
               "        !WindTreesDraw(positions, positions_size, positions_stride, positions_floats,\n"
               "                       // bbport (r89k_twigs-opaque-word): an opaque draw (no discard) may be a limb piece of a tree\n"
               "                       pipeline->GetStages()[u32(Shader::SwStage::Fragment)] != nullptr &&\n"
               "                           !pipeline->GetStages()[u32(Shader::SwStage::Fragment)]->has_discard)) {\n"
               "        return 0;\n"
               "    }\n")

EF_HEAD_OLD = ("bool Rasterizer::WindTreesDraw(u64& positions, u32& positions_size, u32 stride, bool floats) {\n"
               "    BbWindTrees::Stats& st = trees_stats;\n"
               "    ++st.draws;\n")
EF_HEAD_NEW = ("bool Rasterizer::WindTreesDraw(u64& positions, u32& positions_size, u32 stride, bool floats, bool opaque) {\n"
               "    BbWindTrees::Stats& st = trees_stats;\n"
               "    ++st.draws;\n"
               "    trees_last_limb = false; // bbport (r89k_twigs-opaque-word): set below for a limb piece\n")

EF_SHAPE_OLD = ("                fresh.shape = BbWindTrees::ShapeOf(samples.data(), samples.size() / 3);\n"
                "                fresh.tree = fresh.shape.tree;\n")
EF_SHAPE_NEW = (EF_SHAPE_OLD +
                "                // bbport (r89k_twigs-opaque-word): a shape the rule refuses may still be a limb piece of a tree\n"
                "                if (!fresh.tree && fresh.shape.up >= 0 && BbWindTrees::LimbOn()) {\n"
                "                    const BbWindTrees::Limb limb = BbWindTrees::LimbOf(samples.data(), samples.size() / 3,\n"
                "                                                                       BbWindTrees::LimbBoxyMax());\n"
                "                    fresh.limb = limb.ok;\n"
                "                    fresh.boxy = limb.boxy;\n"
                "                    fresh.limb_why = limb.ok ? \"ok\" : limb.why;\n"
                "                }\n")

EF_STATS_OLD = ("        ++st.new_meshes;\n"
                "        if (fresh.tree) {\n"
                "            ++st.tree_meshes;\n"
                "        } else {\n"
                "            ++st.refused_meshes;\n"
                "        }\n"
                "        mesh = &trees_book.Put(key, fresh);\n"
                "        static unsigned refused_lines = 0;\n"
                "        unsigned& lines = fresh.tree ? trees_lines : refused_lines;\n"
                "        if (lines < (fresh.tree ? BbWindTrees::MeshLines : BbWindTrees::MeshLines / 2)) {\n")
EF_STATS_NEW = ("        ++st.new_meshes;\n"
                "        if (fresh.tree) {\n"
                "            ++st.tree_meshes;\n"
                "        } else {\n"
                "            ++st.refused_meshes;\n"
                "            // bbport (r89k_twigs-opaque-word): ranges the limb rule took, and ranges it refused too\n"
                "            if (fresh.limb) {\n"
                "                ++st.limb_new;\n"
                "            } else if (fresh.limb_why[0] != '\\0') {\n"
                "                ++st.limb_refused;\n"
                "            }\n"
                "        }\n"
                "        mesh = &trees_book.Put(key, fresh);\n"
                "        static unsigned refused_lines = 0;\n"
                "        static unsigned limb_lines = 0;\n"
                "        unsigned& lines = fresh.tree ? trees_lines : (fresh.limb ? limb_lines : refused_lines);\n"
                "        const unsigned lines_most = fresh.tree ? BbWindTrees::MeshLines\n"
                "                                               : (fresh.limb ? BbWindTrees::LimbLines : BbWindTrees::MeshLines / 2);\n"
                "        if (lines < lines_most) {\n")

EF_TAIL_OLD = ("    if (!mesh->tree) {\n"
               "        ++st.refused;\n"
               "        return false;\n"
               "    }\n"
               "    if (wind_shelter != nullptr && wind_shelter->CameraOpen() < BbWindTrees::OpenMin) {\n"
               "        ++st.indoors;\n"
               "        return false;\n"
               "    }\n"
               "    positions = mesh->addr;\n"
               "    positions_size = mesh->size;\n"
               "    ++st.taken;\n"
               "    return true;\n"
               "}\n")
EF_TAIL_NEW = ("    // bbport (r89k_twigs-opaque-word): an opaque draw the shape rule refuses but the limb rule takes (a piece of a tree)\n"
               "    const bool limb = !mesh->tree && mesh->limb && opaque && BbWindTrees::LimbOn();\n"
               "    if (!mesh->tree && !limb) {\n"
               "        ++st.refused;\n"
               "        return false;\n"
               "    }\n"
               "    if (wind_shelter != nullptr && wind_shelter->CameraOpen() < BbWindTrees::OpenMin) {\n"
               "        ++st.indoors;\n"
               "        return false;\n"
               "    }\n"
               "    positions = mesh->addr;\n"
               "    positions_size = mesh->size;\n"
               "    ++st.taken;\n"
               "    if (limb) {\n"
               "        ++st.limbs;\n"
               "        trees_last_limb = true;\n"
               "    }\n"
               "    return true;\n"
               "}\n")

EF_WORD_OLD = ("        entry.small = true;\n"
               "        entry.loose = BbWindTwigs::SmallLoose();\n")
EF_WORD_NEW = (EF_WORD_OLD +
               "        entry.limb = BbWindTrees::On() && trees_last_limb; // bbport (r89k_twigs-opaque-word): judged from LimbMinH\n")

EF_LINE_OLD = ("    if (BbWindTrees::On() && ++trees_frames % BbWindSway::ReportFrames == 0) {\n"
               "        char text[704];\n"
               "        BbWindTrees::LineText(trees_stats, trees_book, BbWindSway::ReportFrames, text, sizeof(text));\n")
EF_LINE_NEW = ("    if (BbWindTrees::On() && ++trees_frames % BbWindSway::ReportFrames == 0) {\n"
               "        char text[704];\n"
               "        // bbport (r89k_twigs-opaque-word): the limb pieces in the twig book, and those its world box judged trees\n"
               "        unsigned limb_meshes = 0, limb_trees = 0;\n"
               "        twig_book.ForEach([&](std::uint64_t, const BbWindTwigs::Entry& e) {\n"
               "            limb_meshes += e.limb ? 1u : 0u;\n"
               "            limb_trees += e.limb && e.verdict == BbWindTwigs::Verdict::Tree ? 1u : 0u;\n"
               "        });\n"
               "        BbWindTrees::LineText(trees_stats, trees_book, BbWindSway::ReportFrames, limb_meshes, limb_trees, text,\n"
               "                              sizeof(text));\n")

EF_CLOSE_OLD = ("        if (g.used != 0) {\n"
                "            g.pending = true;\n"
                "            g.tick = scheduler.CurrentTick();\n")
EF_CLOSE_NEW = ("        if (g.used != 0) {\n"
                "            // bbport (r89k_twigs-opaque-word): the frame, the camera and how many scissors met the patch (the note line)\n"
                "            g.frame = object_motion->Frame();\n"
                "            g.meet = trees_pick_meet;\n"
                "            g.apart = trees_pick_apart;\n"
                "            WindHangFindRefresh(g.frame);\n"
                "            g.cam_ok = hang_find_boxes.camera_ok;\n"
                "            g.cam = hang_find_boxes.camera;\n"
                "            g.pending = true;\n"
                "            g.tick = scheduler.CurrentTick();\n")

EF_RESET_OLD = ("        trees_pick_rect_on = false;\n"
                "    }\n"
                "    for (u32 gi = 0; gi < BbWindTrees::PickGroups; ++gi) {\n")
EF_RESET_NEW = ("        trees_pick_rect_on = false;\n"
                "        trees_pick_meet = 0; // bbport (r89k_twigs-opaque-word)\n"
                "        trees_pick_apart = 0;\n"
                "    }\n"
                "    for (u32 gi = 0; gi < BbWindTrees::PickGroups; ++gi) {\n")

EF_NONE_OLD = ("            if (!res.found) {\n"
               "                BbWindTrees::PickNoneLine(pt, g.rect, g.draws.size(), text, sizeof(text));\n"
               "                BbReport::Printf(\"%s\\n\", text);\n"
               "            } else {\n")
EF_NONE_NEW = ("            if (!res.found) {\n"
               "                BbWindTrees::PickNoneLine(pt, g.rect, g.draws.size(), res.passed, text, sizeof(text));\n"
               "                BbReport::Printf(\"%s\\n\", text);\n"
               "                if (res.any) { // bbport (r89k_twigs-opaque-word): the last draw with samples, though it wrote no depth\n"
               "                    describe(res.any_row, res.passed, true);\n"
               "                }\n"
               "            } else {\n")

EF_NOTE_OLD = ("        if (g.skipped != 0) {\n"
               "            std::snprintf(text, sizeof(text),\n"
               "                          \"Wind twigs pick (r89j): NOTE pixel")
EF_NOTE_NEW = ("        if (result == vk::Result::eSuccess) { // bbport (r89k_twigs-opaque-word): which frame, camera and patch\n"
               "            BbWindTrees::PickNoteLine(pt, g.rect, knob.out_w, knob.out_h, g.frame, g.cam_ok, g.cam.data(), g.meet,\n"
               "                                      g.apart, g.draws.size(), text, sizeof(text));\n"
               "            BbReport::Printf(\"%s\\n\", text);\n"
               "        }\n" + EF_NOTE_OLD)

EF_BUDGET_OLD = ('    u32& lines = cheap ? refused_lines : judged_lines;\n'
                 '    if (lines >= (cheap ? BbWindTwigs::SmallLogRefused : BbWindTwigs::SmallLogJudged)) {\n')
EF_BUDGET_NEW = ('    static u32 limb_lines = 0; // bbport (r89k_twigs-opaque-word): limb pieces have a budget of their own (128 lines)\n'
                 '    u32& lines = cheap ? refused_lines : (entry.limb ? limb_lines : judged_lines);\n'
                 '    if (lines >= (cheap ? BbWindTwigs::SmallLogRefused\n'
                 '                        : (entry.limb ? 2 * BbWindTwigs::SmallLogJudged : BbWindTwigs::SmallLogJudged))) {\n')

EF_POINT_OLD = "    const int point = BbWindTrees::PointAt(p.frame + 1, knob.start, knob.count);\n"
EF_POINT_NEW = "    const int point = BbWindTrees::PointAt(p.frame + 1, knob.start, knob.count, knob.repeat); // bbport (r89k)\n"

# ---------------------------------------------------------------- tests/test_wind_trees.cpp
TE_MAX_OLD = ("        s.draws = s.taken = s.refused = s.indoors = s.unread = s.new_meshes = s.tree_meshes = s.refused_meshes =\n"
              "            std::numeric_limits<std::uint64_t>::max();\n")
TE_MAX_NEW = ("        s.draws = s.taken = s.refused = s.indoors = s.unread = s.new_meshes = s.tree_meshes = s.refused_meshes =\n"
              "            s.limbs = s.limb_new = s.limb_refused = std::numeric_limits<std::uint64_t>::max();\n")
TE_LINE_OLD = "        B::LineText(s, book, 600, text, sizeof(text));\n"
TE_LINE_NEW = "        B::LineText(s, book, 600, 4000000000u, 4000000000u, text, sizeof(text));\n"

TE_POINT_OLD = '''               "two frames a point, then nothing");
'''
TE_POINT_NEW = '''               "two frames a point, then nothing");
        // bbport (r89k_twigs-opaque-word): the sweep starts again every `repeat` frames
        Expect(B::PointAt(906, 900, 3, 10) == -1 && B::PointAt(910, 900, 3, 10) == 0 && B::PointAt(912, 900, 3, 10) == 1 &&
                   B::PointAt(914, 900, 3, 10) == 2 && B::PointAt(917, 900, 3, 10) == -1 && B::PointAt(899, 900, 3, 10) == -1,
               "a repeating sweep");
        const B::PickKnob again = B::ParsePick("1,1;2,2;3,3", nullptr, nullptr, "40");
        Expect(again.repeat == 40, "the repeat knob");
        Expect(B::ParsePick("1,1;2,2;3,3", nullptr, nullptr, "5").repeat == 0, "a repeat shorter than the sweep is refused");
        Expect(B::ParsePick("1,1", nullptr, nullptr, nullptr).repeat == 0 && B::ParsePick("1,1", nullptr, nullptr, "soon").repeat == 0,
               "no repeat unless asked");
'''

TE_RECT_OLD = '''        Expect(r.cx == 640 && r.cy == 360 && r.x == 639 && r.y == 359 && r.w == 3 && r.h == 3, "the same size");
        const B::Rect half = B::PickRect(p, 1280, 720, 640, 360);
        Expect(half.cx == 320 && half.cy == 180 && half.w == 3, "a render target of half the size");
        const B::Rect corner = B::PickRect({0, 0}, 1280, 720, 1280, 720);
        Expect(corner.x == 0 && corner.y == 0 && corner.w == 2 && corner.h == 2, "the corner is cut");
        const B::Rect outside = B::PickRect({5000, 5000}, 1280, 720, 1280, 720);
        Expect(outside.cx == 1279 && outside.cy == 719 && outside.w == 2 && outside.h == 2, "outside: the last pixel");
'''
TE_RECT_NEW = '''        Expect(r.cx == 640 && r.cy == 360 && r.x == 638 && r.y == 358 && r.w == 5 && r.h == 5, "the same size (a 5x5 patch)");
        const B::Rect half = B::PickRect(p, 1280, 720, 640, 360);
        Expect(half.cx == 320 && half.cy == 180 && half.w == 5, "a render target of half the size");
        const B::Rect corner = B::PickRect({0, 0}, 1280, 720, 1280, 720);
        Expect(corner.x == 0 && corner.y == 0 && corner.w == 3 && corner.h == 3, "the corner is cut");
        const B::Rect outside = B::PickRect({5000, 5000}, 1280, 720, 1280, 720);
        Expect(outside.cx == 1279 && outside.cy == 719 && outside.w == 3 && outside.h == 3, "outside: the last pixel");
'''

TE_NONE_OLD = '''        B::PickNoneLine({1, 2}, B::PickRect({1, 2}, 1280, 720, 1280, 720), 12, text, sizeof(text));
        Expect(std::strstr(text, "no G-buffer draw of 12 wrote depth there") != nullptr, "the none line");
'''
TE_NONE_NEW = '''        B::PickNoneLine({1, 2}, B::PickRect({1, 2}, 1280, 720, 1280, 720), 12, 0, text, sizeof(text));
        Expect(std::strstr(text, "no G-buffer draw of 12 wrote depth there") != nullptr &&
                   std::strstr(text, " 0 of them had samples") != nullptr && std::strstr(text, "missed every draw") != nullptr,
               "the none line");
        B::PickNoneLine({1, 2}, B::PickRect({1, 2}, 1280, 720, 1280, 720), 12, 3, text, sizeof(text));
        Expect(std::strstr(text, " 3 of them had samples") != nullptr && std::strstr(text, "none with depth write") != nullptr,
               "the none line with samples");
        {
            const float cam[3] = {-51.3f, -39.0f, 71.3f};
            B::PickNoteLine({1180, 60}, B::PickRect({1180, 60}, 1280, 720, 1280, 720), 1280, 720, 600, true, cam, 400, 104,
                            504, text, sizeof(text));
            Expect(std::strstr(text, "pixel 1180,60: frame 600, camera -51.3 -39.0 71.3, picture 1280x720") != nullptr &&
                       std::strstr(text, "patch x 1178..1182 y 58..62 (5x5, centre 1180,60)") != nullptr &&
                       std::strstr(text, "met the patch 400, that did not 104, draws with a query 504") != nullptr,
                   "the note line");
            B::PickNoteLine({16384, 16384}, B::PickRect({10, 10}, 1280, 720, 1280, 720), 16384, 16384,
                            std::numeric_limits<std::uint64_t>::max(), false, nullptr,
                            std::numeric_limits<std::uint32_t>::max(), std::numeric_limits<std::uint32_t>::max(), 99999, text,
                            sizeof(text));
            Expect(std::strlen(text) < 700 && std::strstr(text, "camera unread") != nullptr, "the note line is short and says unread");
        }
'''

TE_FIN_OLD = "    if (failures == 0) {\n        std::printf(\"wind-trees-test: ok\\n\");\n"
TE_FIN_NEW = '''    // bbport (r89k_twigs-opaque-word): the limb rule, the winner's fallback, the world box's height for a limb piece.
    {
        Rng r;
        // A branchy mesh: a trunk and 30 limbs from 3 to 6 m up (y up), each a line of vertices.
        std::vector<float> branchy;
        for (int i = 0; i < 60; ++i) {
            Push(branchy, 0.1f * (r.Next() - 0.5f), 6.0f * r.Next(), 0.1f * (r.Next() - 0.5f));
        }
        for (int b = 0; b < 30; ++b) {
            const float h0 = 3.0f + 3.0f * r.Next();
            const float a = 6.2831853f * r.Next();
            const float len = 2.0f + 4.0f * r.Next();
            for (int k = 0; k < 40; ++k) {
                const float t = len * r.Next();
                Push(branchy, 0.8f * std::cos(a) * t + 0.05f * (r.Next() - 0.5f), h0 + 0.5f * t + 0.05f * (r.Next() - 0.5f),
                     0.8f * std::sin(a) * t + 0.05f * (r.Next() - 0.5f));
            }
        }
        const B::Limb lb = B::LimbOf(branchy.data(), branchy.size() / 3);
        Expect(lb.ok && lb.why == nullptr && lb.boxy < 0.05f && lb.flat > 0.5f, "branches are a limb piece");
        // A building: a shell, every vertex on one of the six faces of a 10 x 8 x 6 box.
        std::vector<float> shell;
        for (int i = 0; i < 600; ++i) {
            const float u = r.Next(), w = r.Next();
            switch (i % 6) {
            case 0: Push(shell, 0.0f, 8.0f * u, 6.0f * w); break;
            case 1: Push(shell, 10.0f, 8.0f * u, 6.0f * w); break;
            case 2: Push(shell, 10.0f * u, 0.0f, 6.0f * w); break;
            case 3: Push(shell, 10.0f * u, 8.0f, 6.0f * w); break;
            case 4: Push(shell, 10.0f * u, 8.0f * w, 0.0f); break;
            default: Push(shell, 10.0f * u, 8.0f * w, 6.0f); break;
            }
        }
        const B::Limb ls = B::LimbOf(shell.data(), shell.size() / 3);
        Expect(!ls.ok && std::strcmp(ls.why, "boxy") == 0 && ls.boxy > 0.9f, "a shell is boxy");
        std::vector<float> slab; // a facade: 12 x 8 m, 0.1 m thick
        for (int i = 0; i < 600; ++i) {
            Push(slab, 12.0f * r.Next(), 8.0f * r.Next(), 0.1f * r.Next());
        }
        Expect(std::strcmp(B::LimbOf(slab.data(), slab.size() / 3).why, "flat") == 0, "a slab is flat");
        std::vector<float> post; // a pole: 0.4 x 10 x 0.4
        for (int i = 0; i < 600; ++i) {
            Push(post, 0.4f * r.Next(), 10.0f * r.Next(), 0.4f * r.Next());
        }
        Expect(std::strcmp(B::LimbOf(post.data(), post.size() / 3).why, "flat") == 0, "a pole is flat");
        Expect(std::strcmp(B::LimbOf(branchy.data(), 10).why, "few") == 0 && std::strcmp(B::LimbOf(nullptr, 100).why, "few") == 0,
               "few vertices");
        const std::vector<float> dot(300, 1.0f);
        Expect(std::strcmp(B::LimbOf(dot.data(), 100).why, "point") == 0, "all one point");
        const B::Limb strict = B::LimbOf(branchy.data(), branchy.size() / 3, 0.0f);
        Expect(strict.ok == (strict.boxy <= 0.0f), "a zero allowance refuses any vertex on a face");
        Expect(!B::LimbOn() && B::LimbBoxyMax() == B::LimbBoxyDefault, "limbs off without BB_WIND_TWIGS_TREES in the test's environment");

        // The world box: a limb piece may be 3 m tall, a tree 4 m.
        BbWindTwigs::Measure m;
        m.ok = true;
        m.base = 0.0f;
        m.crown = 3.5f;
        m.x_lo = 0.0f;
        m.x_hi = 2.0f;
        m.z_lo = 0.0f;
        m.z_hi = 2.0f;
        Expect(std::strcmp(BbWindTwigs::SmallWhy(m, 0.0f, 1, true), "short") == 0, "3.5 m is short for a tree");
        Expect(BbWindTwigs::SmallWhy(m, 0.0f, 1, true, BbWindTwigs::LimbMinH) == nullptr, "3.5 m is tall enough for a limb piece");
        m.crown = 2.5f;
        Expect(std::strcmp(BbWindTwigs::SmallWhy(m, 0.0f, 1, true, BbWindTwigs::LimbMinH), "short") == 0, "2.5 m is short for a limb piece");
        static_assert(BbWindTwigs::LimbMinH > BbWindSway::TreeLo && BbWindTwigs::LimbMinH < BbWindTwigs::SmallMinH,
                      "a limb piece is taller than the lean's tree weight starts and shorter than a tree");
        BbWindTwigs::Entry e;
        Expect(!e.limb, "an entry is no limb piece at first");

        // The winner's fallback: the last draw with samples although it wrote no depth.
        std::vector<B::PickDraw> draws(4);
        for (std::size_t i = 0; i < draws.size(); ++i) {
            draws[i].depth_write = i != 2;
        }
        const std::uint64_t only_no_depth[4] = {0, 0, 5, 0};
        const B::PickResult nw = B::PickWinner(draws, only_no_depth);
        Expect(!nw.found && nw.any && nw.any_row == 2 && nw.passed == 1, "no winner, the fallback names the draw with samples");
        const std::uint64_t mixed[4] = {2, 0, 7, 0};
        const B::PickResult mx = B::PickWinner(draws, mixed);
        Expect(mx.found && mx.row == 0 && mx.any && mx.any_row == 2 && mx.under_n == 0, "a winner and the last draw with samples");
        const std::uint64_t nothing[4] = {0, 0, 0, 0};
        Expect(!B::PickWinner(draws, nothing).any, "nothing passed: no fallback");

        // The log lines name limb pieces.
        char text[720];
        B::Mesh limb;
        limb.limb = true;
        limb.boxy = 0.012f;
        limb.limb_why = "ok";
        limb.why = "no-spread";
        limb.verts = 2043;
        B::MeshText(limb, 0x1087992290ull, text, sizeof(text));
        Expect(std::strstr(text, "LIMB PIECE") != nullptr && std::strstr(text, "shape why no-spread") != nullptr &&
                   std::strstr(text, "limb rule: ok, boxy 0.012") != nullptr,
               "the mesh line of a limb piece");
        B::Mesh refused;
        refused.why = "stout";
        refused.limb_why = "boxy";
        refused.boxy = 0.62f;
        B::MeshText(refused, 0x1087992290ull, text, sizeof(text));
        Expect(std::strstr(text, "refused") != nullptr && std::strstr(text, "limb rule: boxy, boxy 0.620") != nullptr,
               "the mesh line of a piece the limb rule refused");
        B::Mesh plain;
        plain.why = "no-spread";
        B::MeshText(plain, 1, text, sizeof(text));
        Expect(std::strstr(text, "limb rule") == nullptr, "no limb text when the limb rule was not tried");
    }

    if (failures == 0) {
        std::printf("wind-trees-test: ok\\n");
'''

# ---------------------------------------------------------------- README
README_ANCHOR = "| `BB_WIND_TWIGS_CENSUS` |"
README_NEW = (
    "| `BB_WIND_TWIGS_LIMBS` | Limb pieces of trees (r89k; needs `BB_WIND_TWIGS_TREES=1`, which is read first): `1` (default with the trees on) also takes an opaque draw (its pixel shader does not discard) that the shape rule refuses, as a piece of a tree: at least 64 sampled vertices, its smallest bounding-box extent at least 0.08 of its largest (not a slab, a pole or a column) and at most `BB_WIND_TWIGS_LIMB_BOXY` of its vertices within 0.01 of an extent from a face of its bounding box (a wall, a facade or a building is a shell with most vertices on a face; a tree's branches fill the box thinly). A taken piece is a mesh of its own like a tree-shaped draw and goes to the same world box judge (stillness over 68 frames), which asks it to be at least 3 m tall, not 4 m. `0` gives r89j's rule back. The pieces are the visible branches of the bare trees (the pick of build 55 named draws of 2043 and 35898 indices with the shape verdicts no-spread and stout). Read once. Log: the first 16 pieces as `Wind twigs trees (r89j) mesh: ... LIMB PIECE ...`, and the counter line every 600 frames (limb draws taken, ranges taken or refused, limb meshes judged trees by their world box). No shader, pipeline key or cache version differs | `1` |\n"
    "| `BB_WIND_TWIGS_LIMB_BOXY` | The most vertices of a limb piece (a share, 0 to 1) that may lie within 0.01 of an extent from a face of its bounding box (r89k; read once with `BB_WIND_TWIGS_LIMBS`). About 0.01 for a mesh of thin branches, 0.06 for a solid block, 1 for a shell | `0.10` |\n"
    "| `BB_WIND_TWIGS_PICK_REPEAT` | TOOL (r89k; goes to the test-tools branch; with `BB_WIND_TWIGS_PICK`): the sweep over the pixels starts again every this many frames (at least 2 frames a pixel x the number of pixels; a shorter value is ignored), so a pick lost to a camera move in the first seconds is tried again. Each repeat breaks the picture of its frames | `0` |\n"
    + README_ANCHOR)

RM_TREES_OLD = "A verdict is read from at most 262144 indices and 4096 vertices of the draw, kept 3600 frames,"
RM_TREES_NEW = ("A draw the shape rule refuses is still taken when it is a limb piece of a tree (`BB_WIND_TWIGS_LIMBS`, r89k: an opaque draw, "
                "not flat, not a shell of vertices on a bounding-box face; its world box must be at least 3 m tall, a tree-shaped draw's 4 m). "
                + RM_TREES_OLD)

RM_PICK_A_OLD = "the G-buffer draws only a 3x3 patch around the pixel (the picture of those frames is broken)"
RM_PICK_A_NEW = ("the G-buffer draws only a 5x5 patch around the pixel (the picture of those frames is broken; "
                 "`BB_WIND_TWIGS_PICK_REPEAT` starts the sweep again)")
RM_PICK_B_OLD = "and the twig book's verdict. Default off: one test of a static bool, two of a false member a draw"
RM_PICK_B_NEW = ("and the twig book's verdict; a pixel no depth-writing draw covers says how many draws had samples there and names the last of them "
                 "(`under:`), and a note line `Wind twigs pick (r89k): pixel x,y: frame ..., camera ...` gives the frame, the camera, the patch and how many "
                 "G-buffer scissors met the patch or did not. Default off: one test of a static bool, two of a false member a draw")

EDITS = {
    TWIGS: [(TW_CONST_OLD, TW_CONST_NEW), (TW_WHY_OLD, TW_WHY_NEW), (TW_SHORT_OLD, TW_SHORT_NEW), (TW_ENTRY_OLD, TW_ENTRY_NEW),
            (TW_JUDGE_OLD, TW_JUDGE_NEW), (TW_LINE_OLD, TW_LINE_NEW)],
    TREES: [(TR_CONST_OLD, TR_CONST_NEW), (TR_HALF_OLD, TR_HALF_NEW), (TR_BOOK_OLD, TR_LIMB_NEW), (TR_MESH_OLD, TR_MESH_NEW),
            (TR_STATS_OLD, TR_STATS_NEW), (TR_LINE_OLD, TR_LINE_NEW), (TR_MESHTEXT_OLD, TR_MESHTEXT_NEW),
            (TR_KNOB_OLD, TR_KNOB_NEW), (TR_PARSE_SIG_OLD, TR_PARSE_SIG_NEW), (TR_PARSE_TAIL_OLD, TR_PARSE_TAIL_NEW),
            (TR_GETENV_OLD, TR_GETENV_NEW), (TR_POINTAT_OLD, TR_POINTAT_NEW), (TR_RESULT_OLD, TR_RESULT_NEW),
            (TR_WINNER_OLD, TR_WINNER_NEW), (TR_NONE_OLD, TR_NONE_NEW), (TR_ONCE_OLD, TR_ONCE_NEW)],
    RASTH: [(RH_DECL_OLD, RH_DECL_NEW), (RH_LINES_OLD, RH_LINES_NEW), (RH_GROUP_OLD, RH_GROUP_NEW), (RH_RECT_OLD, RH_RECT_NEW)],
    RAST: [(RC_OLD, RC_NEW)],
    EFFECTS: [(EF_CALL_OLD, EF_CALL_NEW), (EF_HEAD_OLD, EF_HEAD_NEW), (EF_SHAPE_OLD, EF_SHAPE_NEW), (EF_STATS_OLD, EF_STATS_NEW),
              (EF_TAIL_OLD, EF_TAIL_NEW), (EF_WORD_OLD, EF_WORD_NEW), (EF_LINE_OLD, EF_LINE_NEW), (EF_CLOSE_OLD, EF_CLOSE_NEW),
              (EF_RESET_OLD, EF_RESET_NEW), (EF_NONE_OLD, EF_NONE_NEW), (EF_NOTE_OLD, EF_NOTE_NEW), (EF_POINT_OLD, EF_POINT_NEW),
              (EF_BUDGET_OLD, EF_BUDGET_NEW)],
    TEST: [(TE_MAX_OLD, TE_MAX_NEW), (TE_LINE_OLD, TE_LINE_NEW), (TE_POINT_OLD, TE_POINT_NEW), (TE_RECT_OLD, TE_RECT_NEW),
           (TE_NONE_OLD, TE_NONE_NEW), (TE_FIN_OLD, TE_FIN_NEW)],
    README: [(README_ANCHOR, README_NEW), (RM_TREES_OLD, RM_TREES_NEW), (RM_PICK_A_OLD, RM_PICK_A_NEW), (RM_PICK_B_OLD, RM_PICK_B_NEW)],
}

CHECKS = {
    TWIGS: [("inline constexpr float LimbMinH = 3.0f;", 1), ("float min_height = SmallMinH", 1), ("bool limb = false;", 1),
            ("e.limb ? LimbMinH : SmallMinH", 1)],
    TREES: [("inline bool LimbOn()", 1), ("inline Limb LimbOf(", 1), ("inline void PickNoteLine(", 1), ("std::uint64_t repeat = 0;", 1),
            ("inline constexpr int PickHalf = 2;", 1)],
    RASTH: [("bool WindTreesDraw(u64& positions, u32& positions_size, u32 stride, bool floats, bool opaque);", 1),
            ("bool trees_last_limb = false;", 1), ("mutable u32 trees_pick_meet = 0, trees_pick_apart = 0;", 1)],
    RAST: [("++trees_pick_meet;", 1), ("++trees_pick_apart;", 1)],
    EFFECTS: [("bool Rasterizer::WindTreesDraw(u64& positions, u32& positions_size, u32 stride, bool floats, bool opaque) {", 1),
              ("BbWindTrees::LimbOf(samples.data()", 1), ("trees_last_limb = true;", 1), ("entry.limb = BbWindTrees::On() && trees_last_limb;", 1),
              ("BbWindTrees::PickNoteLine(pt, g.rect", 1), ("knob.start, knob.count, knob.repeat", 1),
              ("BbWindTrees::PickNoneLine(pt, g.rect, g.draws.size(), res.passed", 1)],
    TEST: [("B::LimbOf(branchy.data()", 3), ("wind-trees-test: ok", 1)],
    README: [("| `BB_WIND_TWIGS_LIMBS` |", 1), ("| `BB_WIND_TWIGS_LIMB_BOXY` |", 1), ("| `BB_WIND_TWIGS_PICK_REPEAT` |", 1),
             ("| `BB_WIND_TWIGS_CENSUS` |", 1), ("5x5 patch around the pixel", 1)],
}

# Numbers written twice: the header's constants and the README rows' text.
LIMB_ROW = "| `BB_WIND_TWIGS_LIMBS`"
BOXY_ROW = "| `BB_WIND_TWIGS_LIMB_BOXY`"
TIES = [("inline constexpr std::size_t LimbSamplesMin = 64", LIMB_ROW, "at least 64 sampled vertices"),
        ("inline constexpr float LimbFlatMin = 0.08f", LIMB_ROW, "at least 0.08 of its largest"),
        ("inline constexpr float LimbBand = 0.01f", LIMB_ROW, "within 0.01 of an extent"),
        ("inline constexpr float LimbBoxyDefault = 0.10f", BOXY_ROW, "| `0.10` |"),
        ("inline constexpr unsigned LimbLines = 16", LIMB_ROW, "first 16 pieces")]
TIES_TWIGS = [("inline constexpr float LimbMinH = 3.0f;", LIMB_ROW, "at least 3 m tall, not 4 m")]


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
    for const, row_start, value in TIES_TWIGS:
        rows = "\n".join(l for l in texts[README].split("\n") if l.startswith(row_start))
        if texts[TWIGS].count(const) != 1 or value not in rows:
            raise SystemExit("tie check: %r against the README row %r (%r)" % (const, row_start, value))
    for edits in EDITS.values():
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
        raise SystemExit("%s is not a source tree root (set R89K_ROOT)" % ROOT)
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
            tmp = full + ".r89ktmp"
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
        tmp = full + ".r89ktmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
