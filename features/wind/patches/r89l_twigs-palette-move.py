# r89l_twigs-palette-move: FEATURE (BB_WIND_TWIGS_TREES_GAIN, default 0.5, only with BB_WIND_TWIGS_TREES=1 which stays 0) +
# TOOL (the pick's scaling to the raster, the G-buffer pass bit and the offset counters of BB_WIND_TWIGS_PROOF, the shader
# path note). On top of r89k_twigs-opaque-word (build 57), r89j, r89i, r89h, r89g.
#
# THE OWNER: "I think if the small branches on the trees moved slightly due to wind that would look great"; "The wave
# should just be very subtle"; foliage moves downwind, slowly unless the wind is strong.
# BUILD 57 (read from b57_s3.log and the pictures, no game): 99600 tree draws taken in 600 frames, 62 trees judged, the
# proof counters read 12.9M vertices counted and 5.0M moved over 1 cm (these include the proof's x5), the picks read
# 'sway word YES'; but no stain on any branch and no branch motion in the pictures (the close up_a / up_b pictures too,
# with 4-6 m overhead branches and x5).
#
# WHAT THE CODE SAYS (reading, not running):
# 1. THE PICK READ THE WRONG PIXELS. The log says 'Scene resolution: raster 640x360, game targets 1280x720'. The pick's patch is
#    made for the game targets (RenderSize 1280x720: 'render 1180,60') but the G-buffer's scissors are in RASTER pixels (the
#    game's scissor x target_scale + target_offset, Rasterizer::DrawScissor): a patch at x >= 640 or y >= 360 lies outside every
#    scissor ('met 0, did not 504': all five x >= 650 pixels), and the ones that did meet read the pixel at HALF the
#    coordinates (pixel 480,140 of build 57 is the picture's 960,280: the right tree; 300,95 is the picture's 600,190).
# 2. THE OFFSET COUNTERS CANNOT SAY WHICH PASS RAN. The lifter's proof counters (r89g) count vertex runs of the slot, whatever
#    pass drew them (one draw a frame per slot: 600 draws, 600 frames). Whether the lifter or the recompiler made the shader
#    of a taken draw, and whether the counted runs are the G-buffer's, is not in any log.
#
# FEATURE (needs BB_WIND_TWIGS_TREES=1, default 0): BB_WIND_TWIGS_TREES_GAIN (read once; 0 to 1, default 0.5) scales the ramp
# byte of the sway word of every draw the trees route took (tree-shaped or limb piece): the move of the thin outer branches
# is gain x what r89k gave (a 6 m piece: tip 2.3 cm in the lean, 4.6 cm at the gust front at 4 m/s; at most about 8 cm for the
# tallest pieces at 3 m/s): 'a few cm at 4 m/s, slow, very subtle', zero at the trunk (the weight rule is unchanged: distance
# from the mesh's centre line x height in the mesh). 1 gives r89k's move back; 0 stops it (ramp 0). A CPU-side change of a
# word, no shader differs.
#
# TOOL (BB_WIND_TWIGS_PICK, BB_WIND_TWIGS_PROOF; goes to the test-tools branch):
#  (a) the pick's patch is scaled from the game targets to the raster by the rasterizer's own scale and offset
#      (BbWindTrees::PickRectRaster; a patch of 5x5 raster pixels around the scaled pixel), and one line says the picture, game
#      target and raster sizes and the scale ('Wind twigs pick (r89l): pick pixels are read in a 1280x720 picture ...').
#  (b) with the proof knob a tree word of a G-buffer draw also has BbWindTwigs::PassBit (bit 24: free); the lifter's shader
#      adds 7 counters a vertex run to one of two sets of the slot's OffsetAt words, the G-buffer's (the word's PassBit) or the
#      other passes': vertices counted, the sum of the move in mm, over 1 mm, 1 cm, 5 cm, 10 cm, the largest move.
#  (c) every 600 frames, with the proof lines: 'Wind twigs offset (r89l, TOOL): twig offset in palette path: N draws (G in the
#      G-buffer), M meshes, mean m cm, max m cm ...' for every tree mesh (not only the first six) with a bone palette, the
#      same for the static ones, the G-buffer's vertex runs apart from the other passes', and for each vertex shader of the
#      palette meshes whether it was made by the lifter ('lifted': the counters and the tint run) or the recompiler
#      ('RECOMPILED (no counters, no tint)'; vk_pipeline_cache notes it). The numbers include the proof's x5.
#  The shader cache version of the proof shaders gets +400 (BbWindTwigs::OffsetAdd).
#
# OFF (default): BB_WIND_TWIGS_TREES=0 keeps the trees route off (TREES_GAIN is read only in WindTwigWord when
# BbWindTrees::On()); BB_WIND_TWIGS_PROOF and BB_WIND_TWIGS_PICK unset keep every tool line false: PassBit is never set, the lifter
# emits nothing new, the buffer is not larger, the shader path note is not made (one test of a static bool). No shader, pipeline
# key or cache version changes in any state without the proof knob.
#
# SHARED LINES TOUCHED. THE PICK (the glass lane r86l_glint-pick-glass uses it too): vk_rasterizer.cpp: r89j's/r89k's pick scissor
# block (the six lines that read trees_pick_rect, now read the scaled patch; the meet/apart counters are untouched);
# vk_rasterizer_effects.cpp: ONE line in WindTreesPickFrameEnd (trees_pick_game = r;); vk_rasterizer.h: ONE member next to
# trees_pick_meet; bbport_wind_trees.h: new functions (PickRectRaster, PickRasterText) before PickDraw, PickRect is NOT changed.
# Twigs only: WindSwayWord (the tree return and the TwigProofNote call), WindTwigWord (one return), the proof report block;
# vk_pipeline_cache.cpp (three lines around the lifter call); lift_stage.cpp (one block after keep(13, g)). The hang lane's
# functions and the sway shaders are not touched.
#
# NOT TESTED in the game. Use: python -I -X utf8 r89l_twigs-palette-move.py check | apply | revert (root from R89L_ROOT, else
# <tree>). Files keep their line ends. Originals are kept in r89l_backup/ next to this script. No new file.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89l_backup")
ROOT = os.environ.get("R89L_ROOT") or "<tree>"
G = "engine/gpu/"
R = G + "shadps4/video_core/renderer_vulkan/"
TWIGS = G + "shim/bbport_wind_twigs.h"
TREES = G + "shim/bbport_wind_trees.h"
LIFT = G + "shim/lifter/lift_stage.cpp"
RASTH = R + "vk_rasterizer.h"
RAST = R + "vk_rasterizer.cpp"
EFFECTS = R + "vk_rasterizer_effects.cpp"
CACHE = R + "vk_pipeline_cache.cpp"
TEST = "engine/tests/test_wind_trees.cpp"
README = "README.md"

# ---------------------------------------------------------------- bbport_wind_twigs.h
TW_INC_OLD = "#include <cstring>\n#include <unordered_map>\n#include <utility>\n"
TW_INC_NEW = "#include <cstring>\n#include <mutex> // bbport (r89l_twigs-palette-move)\n#include <unordered_map>\n#include <utility>\n"

TW_PASS_OLD = "inline constexpr std::uint32_t TreeBit = 1u << 14;\n"
TW_PASS_NEW = TW_PASS_OLD + (
    "/// bbport (r89l_twigs-palette-move, TOOL): with BB_WIND_TWIGS_PROOF a tree word of a G-buffer draw also has this bit (free:\n"
    "/// PackWord's ramp ends at bit 23): the lifter's offset counters (OffsetAt) then tell the G-buffer's vertex runs from the\n"
    "/// other passes'.\n"
    "inline constexpr std::uint32_t PassBit = 1u << 24;\n")

TW_LAG_OLD = "inline constexpr std::uint32_t LagEnd = LagAt + LagWords;\n"
TW_LAG_NEW = TW_LAG_OLD + (
    "/// bbport (r89l_twigs-palette-move, TOOL): with the proof knob every base slot has OffsetSlotWords more counters behind the\n"
    "/// lag words (words from the start of the sway region's buffer): OffsetSets sets of OffsetSetWords words, set 1 the vertex\n"
    "/// runs of draws whose word has PassBit (the G-buffer's), set 0 every other pass's. A set: 0 vertices counted, 1 the sum of\n"
    "/// their move (mm, u32), 2 moved over 1 mm, 3 over 1 cm, 4 over 5 cm, 5 over 10 cm, 6 the largest move (m, float bits), 7 spare.\n"
    "/// OffsetAdd is added to the sway shader binary version with the proof knob (the lifter's shader differs).\n"
    "inline constexpr std::uint32_t OffsetSets = 2, OffsetSetWords = 8;\n"
    "inline constexpr std::uint32_t OffsetSlotWords = OffsetSets * OffsetSetWords;\n"
    "inline constexpr std::uint32_t OffsetAt = LagEnd;\n"
    "inline constexpr std::uint32_t OffsetWords = W::BaseSlots * OffsetSlotWords;\n"
    "inline constexpr std::uint32_t OffsetEnd = OffsetAt + OffsetWords;\n"
    "inline constexpr std::uint32_t OffsetAdd = 400;\n"
    "static_assert(OffsetAt % 4 == 0 && OffsetSetWords % 4 == 0 && OffsetSets == 2, \"the offset sets are 16-byte aligned\");\n"
    "static_assert((W::PackWord(3, 1, 1023, 255) & PassBit) == 0 && (PassBit & W::WordOn) == 0 && PassBit != (1u << 13) &&\n"
    "                  PassBit != TreeBit,\n"
    "              \"PassBit lies outside PackWord's fields and is neither r112's HangBit nor TreeBit\");\n")

TW_BUF_OLD = "ProofOn() ? LagEnd * 4 : TwigBytes) // bbport (r89g_twigs-proof, r89h)"
TW_BUF_NEW = "ProofOn() ? OffsetEnd * 4 : TwigBytes) // bbport (r89g_twigs-proof, r89h, r89l)"

TW_INIT_OLD = ("        if (ProofOn()) { // bbport (r89g_twigs-proof, TOOL): the counters at 0\n"
               "            for (std::uint32_t i = 0; i < ProofWords; ++i) {\n"
               "                sway_words[ProofAt + i] = 0;\n"
               "            }\n"
               "        }\n")
TW_INIT_NEW = TW_INIT_OLD + (
    "        if (ProofOn()) { // bbport (r89l_twigs-palette-move, TOOL): the offset counters at 0\n"
    "            for (std::uint32_t i = 0; i < OffsetWords; ++i) {\n"
    "                sway_words[OffsetAt + i] = 0;\n"
    "            }\n"
    "        }\n")

TW_RESET_OLD = ("            for (std::uint32_t i = 0; i < ProofSlotWords; ++i) {\n"
                "                words[ProofAt + slot * ProofSlotWords + i] = 0;\n"
                "            }\n"
                "        }\n")
TW_RESET_NEW = TW_RESET_OLD + (
    "        if (ProofOn()) { // bbport (r89l_twigs-palette-move, TOOL): the slot's offset counters at 0\n"
    "            for (std::uint32_t i = 0; i < OffsetSlotWords; ++i) {\n"
    "                words[OffsetAt + slot * OffsetSlotWords + i] = 0;\n"
    "            }\n"
    "        }\n")

TW_BIN_OLD = "(ProofOn() ? ProofAdd : 0u) + (PushOn() ? PushAdd : 0u) // bbport (r89h)"
TW_BIN_NEW = "(ProofOn() ? ProofAdd + OffsetAdd : 0u) + (PushOn() ? PushAdd : 0u) // bbport (r89h, r89l)"

TW_KNOWN_OLD = "            if (version == sway + a + b || version == hang + a + b) {\n"
TW_KNOWN_NEW = ("            // bbport (r89l_twigs-palette-move): and the offset counters' OffsetAdd (the proof knob's shaders)\n"
                "            if (version == sway + a + b || version == hang + a + b || version == sway + a + b + OffsetAdd ||\n"
                "                version == hang + a + b + OffsetAdd) {\n")

TW_FUNCS_ANCHOR = "/// bbport (r89h_twigs-alive, TOOL): what the change counters say of the push's time motion (a string literal).\n"
TW_FUNCS_NEW = '''// bbport (r89l_twigs-palette-move, TOOL): the offset counters (OffsetAt: two sets of OffsetSetWords words a base slot, the
// G-buffer's, whose word has PassBit, and every other pass's), the note of which emitter made a vertex shader, and the line
// that names the twig offset in the palette path.

/// One set of the offset counters of a slot (see OffsetAt).
struct OffsetSet {
    std::uint32_t verts = 0, sum_mm = 0, over_1mm = 0, over_1cm = 0, over_5cm = 0, over_10cm = 0;
    float move_max = 0.0f; ///< m
};

struct OffsetCounts {
    std::array<OffsetSet, OffsetSets> pass{}; ///< 0 the other passes, 1 the G-buffer
};

/// The offset counters of `slot` (a volatile read: the GPU writes them; at report time). A slot out of range reads as all 0.
[[nodiscard]] inline OffsetCounts ReadOffset(const std::uint32_t* words, std::uint32_t slot) {
    OffsetCounts c;
    if (words == nullptr || slot >= W::BaseSlots) {
        return c;
    }
    for (std::uint32_t s = 0; s < OffsetSets; ++s) {
        const volatile std::uint32_t* const v = words + OffsetAt + slot * OffsetSlotWords + s * OffsetSetWords;
        OffsetSet& o = c.pass[s];
        o.verts = v[0];
        o.sum_mm = v[1];
        o.over_1mm = v[2];
        o.over_1cm = v[3];
        o.over_5cm = v[4];
        o.over_10cm = v[5];
        const std::uint32_t bits = v[6];
        std::memcpy(&o.move_max, &bits, sizeof(float));
    }
    return c;
}

/// The slot's offset counters back to 0 (after a report).
inline void ClearOffset(std::uint32_t* words, std::uint32_t slot) {
    if (words == nullptr || slot >= W::BaseSlots) {
        return;
    }
    volatile std::uint32_t* const v = words + OffsetAt + slot * OffsetSlotWords;
    for (std::uint32_t k = 0; k < OffsetSlotWords; ++k) {
        v[k] = 0;
    }
}

/// The sum over slots of one set.
struct OffsetSum {
    std::uint64_t verts = 0, sum_mm = 0, over_1mm = 0, over_1cm = 0, over_5cm = 0, over_10cm = 0;
    float move_max = 0.0f; ///< m
    void Add(const OffsetSet& s) {
        verts += s.verts;
        sum_mm += s.sum_mm;
        over_1mm += s.over_1mm;
        over_1cm += s.over_1cm;
        over_5cm += s.over_5cm;
        over_10cm += s.over_10cm;
        if (std::isfinite(s.move_max)) {
            move_max = std::max(move_max, s.move_max);
        }
    }
};

/// The tree meshes of one path (palette or static) in a report window: the CPU's draws and meshes, the GPU's counters by set,
/// and the vertex shaders (the low 32 bits of their hashes, at most VsMost) with the emitter that made them (ShaderPathOf).
struct OffsetTotals {
    static constexpr std::size_t VsMost = 6;
    std::uint64_t meshes = 0, draws = 0, gbuffer_draws = 0;
    std::array<OffsetSum, OffsetSets> pass{};
    std::array<std::uint32_t, VsMost> vs{};
    std::array<std::uint8_t, VsMost> vs_path{};
    std::size_t vs_n = 0;
    void Add(std::uint64_t slot_draws, std::uint64_t slot_gbuffer, const OffsetCounts& c, std::uint32_t vs_hash,
             std::uint8_t path) {
        ++meshes;
        draws += slot_draws;
        gbuffer_draws += slot_gbuffer;
        for (std::size_t s = 0; s < OffsetSets; ++s) {
            pass[s].Add(c.pass[s]);
        }
        if (vs_hash != 0) {
            bool known = false;
            for (std::size_t i = 0; i < vs_n; ++i) {
                known = known || vs[i] == vs_hash;
            }
            if (!known && vs_n < VsMost) {
                vs[vs_n] = vs_hash;
                vs_path[vs_n] = path;
                ++vs_n;
            }
        }
    }
};

/// Which emitter made the vertex shaders of a hash (the pipeline cache notes it when it compiles one): bit 0 the lifter, bit 1
/// the recompiler. Thread safe (shaders compile on several threads).
[[nodiscard]] inline std::mutex& PathMutex() {
    static std::mutex m;
    return m;
}

[[nodiscard]] inline std::unordered_map<std::uint64_t, std::uint8_t>& PathMap() {
    static std::unordered_map<std::uint64_t, std::uint8_t> map;
    return map;
}

inline void NoteShaderPath(std::uint64_t hash, bool lifted) {
    const std::lock_guard<std::mutex> lock(PathMutex());
    std::uint8_t& bits = PathMap()[hash];
    bits = static_cast<std::uint8_t>(bits | (lifted ? 1u : 2u));
}

[[nodiscard]] inline std::uint8_t ShaderPathOf(std::uint64_t hash) {
    const std::lock_guard<std::mutex> lock(PathMutex());
    const auto found = PathMap().find(hash);
    return found != PathMap().end() ? found->second : std::uint8_t{0};
}

[[nodiscard]] inline const char* PathName(std::uint8_t path) {
    switch (path) {
    case 1:
        return "lifted";
    case 2:
        return "RECOMPILED (no counters, no tint)";
    case 3:
        return "lifted and recompiled variants";
    default:
        return "path not noted (shader from the cache)";
    }
}

/// The once line of the offset counters (under 700 characters).
inline void OffsetOnceText(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs offset (r89l, TOOL, with BB_WIND_TWIGS_PROOF=1): every %u frames a line names the twig offset the "
                  "lifter's shaders counted for every tree mesh, the palette path (draws that read a small bone palette) and "
                  "the static one, the G-buffer's vertex runs (the word's PassBit, set for G-buffer draws only) apart from the "
                  "other passes', and whether each vertex shader of the palette meshes was made by the lifter or the "
                  "recompiler (which has no counters); %u counters a mesh slot (%u bytes of the sway buffer)",
                  unsigned(W::ReportFrames), OffsetSlotWords, OffsetWords * 4u);
}

/// The window's line (under 1400 characters): the twig offset in the palette path (draws, G-buffer draws, meshes, mean and
/// largest move of the counted vertex runs), the G-buffer's runs and the other passes' apart, the real offset (the proof's
/// x ProofGain taken out), the emitters of the palette meshes' vertex shaders and the static path in short.
inline void OffsetLine(const OffsetTotals& pal, const OffsetTotals& stat, char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    const auto mean_cm = [](std::uint64_t sum_mm, std::uint64_t verts) {
        return verts > 0 ? static_cast<double>(sum_mm) / static_cast<double>(verts) * 0.1 : 0.0;
    };
    const auto max_cm = [](const OffsetTotals& t) {
        return static_cast<double>(std::max(t.pass[0].move_max, t.pass[1].move_max)) * 100.0;
    };
    const auto all_mean = [&](const OffsetTotals& t) {
        return mean_cm(t.pass[0].sum_mm + t.pass[1].sum_mm, t.pass[0].verts + t.pass[1].verts);
    };
    char paths[320] = "";
    for (std::size_t i = 0; i < pal.vs_n; ++i) {
        const std::size_t used = std::strlen(paths);
        std::snprintf(paths + used, sizeof(paths) - used, "%svs %08x %s", i == 0 ? "" : ", ",
                      static_cast<unsigned>(pal.vs[i]), PathName(pal.vs_path[i]));
    }
    const double gain = static_cast<double>(ProofGain);
    std::snprintf(out, size,
                  "Wind twigs offset (r89l, TOOL): twig offset in palette path: %llu draws (%llu in the G-buffer), %llu meshes, "
                  "mean %.2f cm, max %.2f cm (with the proof's x%.0f; real mean %.2f cm, max %.2f cm); G-buffer vertex runs "
                  "%llu, mean %.2f cm, max %.2f cm, over 1 cm %llu, over 5 cm %llu, over 10 cm %llu; other passes' vertex runs "
                  "%llu, mean %.2f cm, max %.2f cm; shader paths: %s; static path: %llu draws (%llu in the G-buffer), %llu "
                  "meshes, mean %.2f cm, max %.2f cm, G-buffer vertex runs %llu",
                  n(pal.draws), n(pal.gbuffer_draws), n(pal.meshes), all_mean(pal), max_cm(pal), gain, all_mean(pal) / gain,
                  max_cm(pal) / gain, n(pal.pass[1].verts), mean_cm(pal.pass[1].sum_mm, pal.pass[1].verts),
                  static_cast<double>(pal.pass[1].move_max) * 100.0, n(pal.pass[1].over_1cm), n(pal.pass[1].over_5cm),
                  n(pal.pass[1].over_10cm), n(pal.pass[0].verts), mean_cm(pal.pass[0].sum_mm, pal.pass[0].verts),
                  static_cast<double>(pal.pass[0].move_max) * 100.0, pal.vs_n == 0 ? "none" : paths, n(stat.draws),
                  n(stat.gbuffer_draws), n(stat.meshes), all_mean(stat), max_cm(stat), n(stat.pass[1].verts));
}

''' + TW_FUNCS_ANCHOR

# ---------------------------------------------------------------- bbport_wind_trees.h
TR_BOOK_OLD = "// ------------------------------------------------------------------------------------------- the book\n"
TR_GAIN_NEW = '''// ------------------------------------------------------------------------------------------- the trees' gain

/// bbport (r89l_twigs-palette-move): BB_WIND_TWIGS_TREES_GAIN (read once; 0 to 1, default TreesGainDefault): the share of the
/// move r89k gave that a draw of the trees route (tree-shaped or limb piece) keeps. 'A few cm at 4 m/s, very subtle.'
inline constexpr float TreesGainDefault = 0.5f;

[[nodiscard]] inline float TreesGain() {
    static const float gain = std::clamp(W::ParseNumber(std::getenv("BB_WIND_TWIGS_TREES_GAIN"), TreesGainDefault), 0.0f, 1.0f);
    return gain;
}

/// A sway word's ramp byte (0 to 255) times `gain` (0 to 1): 0 stays 0 (judging, no motion), a gain of 0 gives 0, any other
/// gain keeps at least 1 so a mesh that moves keeps moving.
[[nodiscard]] inline std::uint32_t GainRamp(std::uint32_t ramp, float gain) {
    if (ramp == 0u || !(gain > 0.0f)) {
        return 0u;
    }
    const float g = std::isfinite(gain) ? std::min(gain, 1.0f) : 1.0f;
    const long scaled = std::lround(static_cast<float>(std::min(ramp, 255u)) * g);
    return static_cast<std::uint32_t>(std::clamp(scaled, 1L, 255L));
}

''' + TR_BOOK_OLD

TR_PICKDRAW_OLD = "/// What the rasterizer knew of one G-buffer draw of a pick frame.\n"
TR_RASTER_NEW = '''/// bbport (r89l_twigs-palette-move): the pick's patch in RASTER pixels. PickRect makes the patch in game-target pixels (the
/// target size the game believes it draws to), but the G-buffer's scissors are in raster pixels (the game's scissor times the
/// rasterizer's target scale plus its offset: the scene may be drawn at half the size of the game's targets, as in the slot
/// windows). The patch is 2 * PickHalf + 1 raster pixels around the scaled centre pixel; its right and lower edges are not
/// cut (the scissor intersection does). w and h 0: no patch.
struct RasterRect {
    int x = 0, y = 0, w = 0, h = 0;
};

[[nodiscard]] inline RasterRect PickRectRaster(const Rect& r, float scale_x, float scale_y, float offset_x, float offset_y) {
    RasterRect o;
    if (r.w <= 0 || r.h <= 0 || !std::isfinite(scale_x) || !std::isfinite(scale_y) || !std::isfinite(offset_x) ||
        !std::isfinite(offset_y) || !(scale_x > 0.0f) || !(scale_y > 0.0f)) {
        return o;
    }
    const double fx = (static_cast<double>(r.cx) + 0.5) * static_cast<double>(scale_x) + static_cast<double>(offset_x);
    const double fy = (static_cast<double>(r.cy) + 0.5) * static_cast<double>(scale_y) + static_cast<double>(offset_y);
    const int cx = static_cast<int>(std::floor(std::clamp(fx, -1.0e6, 1.0e6)));
    const int cy = static_cast<int>(std::floor(std::clamp(fy, -1.0e6, 1.0e6)));
    o.x = std::max(cx - PickHalf, 0);
    o.y = std::max(cy - PickHalf, 0);
    o.w = cx + PickHalf + 1 - o.x;
    o.h = cy + PickHalf + 1 - o.y;
    if (o.w <= 0 || o.h <= 0) {
        o = RasterRect{};
    }
    return o;
}

/// The once line of the pick's scaling (under 400 characters): the picture the pixels are read from, the game targets, the
/// raster they are drawn at, and the first patch in raster pixels.
inline void PickRasterText(std::uint32_t out_w, std::uint32_t out_h, std::uint32_t game_w, std::uint32_t game_h, float scale_x,
                           float scale_y, float offset_x, float offset_y, int patch_x, int patch_y, int patch_w, int patch_h,
                           char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs pick (r89l): pick pixels are read in a %ux%u picture, scaled to the game targets %ux%u and then to "
                  "the raster %ux%u (target scale %.3f x %.3f, offset %.1f, %.1f); the G-buffer's scissors are in raster pixels; "
                  "the first patch is x %d y %d, %dx%d raster pixels",
                  out_w, out_h, game_w, game_h, static_cast<unsigned>(std::lround(static_cast<double>(game_w) * scale_x)),
                  static_cast<unsigned>(std::lround(static_cast<double>(game_h) * scale_y)), static_cast<double>(scale_x),
                  static_cast<double>(scale_y), static_cast<double>(offset_x), static_cast<double>(offset_y), patch_x, patch_y,
                  patch_w, patch_h);
}

''' + TR_PICKDRAW_OLD

# ---------------------------------------------------------------- vk_rasterizer.h
RH_OLD = "    mutable u32 trees_pick_meet = 0, trees_pick_apart = 0;\n"
RH_NEW = RH_OLD + "    BbWindTrees::Rect trees_pick_game{}; ///< bbport (r89l_twigs-palette-move): this frame's patch in game-target pixels\n"

# ---------------------------------------------------------------- vk_rasterizer.cpp
RC_OLD = ("            const s32 x0 = std::max(scissor.offset.x, trees_pick_rect.offset.x);\n"
          "            const s32 y0 = std::max(scissor.offset.y, trees_pick_rect.offset.y);\n"
          "            const s32 x1 = std::min(scissor.offset.x + s32(scissor.extent.width),\n"
          "                                    trees_pick_rect.offset.x + s32(trees_pick_rect.extent.width));\n"
          "            const s32 y1 = std::min(scissor.offset.y + s32(scissor.extent.height),\n"
          "                                    trees_pick_rect.offset.y + s32(trees_pick_rect.extent.height));\n")
RC_NEW = (
    "            // bbport (r89l_twigs-palette-move): the scissors are in raster pixels (the game's scissor times the target scale\n"
    "            // plus its offset); the patch was made in game-target pixels: scale it the same way. Build 57 read the pixels\n"
    "            // unscaled at a raster of half the game targets: only a quarter of the picture could be picked, at half the\n"
    "            // coordinates.\n"
    "            const BbWindTrees::RasterRect pr = BbWindTrees::PickRectRaster(trees_pick_game, target_scale[0], target_scale[1],\n"
    "                                                                          target_offset[0], target_offset[1]);\n"
    "            static bool pick_scale_said = false;\n"
    "            if (!pick_scale_said && camera_motion != nullptr) {\n"
    "                pick_scale_said = true;\n"
    "                const auto game = camera_motion->RenderSize();\n"
    "                char pick_text[512];\n"
    "                BbWindTrees::PickRasterText(BbWindTrees::PickOnce().out_w, BbWindTrees::PickOnce().out_h, game[0], game[1],\n"
    "                                            target_scale[0], target_scale[1], target_offset[0], target_offset[1], pr.x, pr.y,\n"
    "                                            pr.w, pr.h, pick_text, sizeof(pick_text));\n"
    "                BbReport::Printf(\"%s\\n\", pick_text);\n"
    "            }\n"
    "            const s32 x0 = std::max(scissor.offset.x, pr.x);\n"
    "            const s32 y0 = std::max(scissor.offset.y, pr.y);\n"
    "            const s32 x1 = std::min(scissor.offset.x + s32(scissor.extent.width), pr.x + pr.w);\n"
    "            const s32 y1 = std::min(scissor.offset.y + s32(scissor.extent.height), pr.y + pr.h);\n")

# ---------------------------------------------------------------- vk_pipeline_cache.cpp
CA_A_OLD = "    if (Lifter::GetMode() != Lifter::Mode::Off && !EffectShaders::KeepRecompiled(info)) {\n"
CA_A_NEW = ("    bool bbport_lifted = false; // bbport (r89l_twigs-palette-move): which emitter made this shader (the offset line says)\n"
            + CA_A_OLD)
CA_B_OLD = "            spv = std::move(lifted.spirv);\n"
CA_B_NEW = CA_B_OLD + "            bbport_lifted = true;\n"
CA_C_OLD = "    DumpShader(spv, info.pgm_hash, info.hw_stage, perm_idx, \"spv\");\n"
CA_C_NEW = ("    if (BbWindTwigs::ProofOn() && info.hw_stage == HwStage::Vertex) { // bbport (r89l_twigs-palette-move, TOOL)\n"
            "        BbWindTwigs::NoteShaderPath(info.pgm_hash, bbport_lifted);\n"
            "    }\n" + CA_C_OLD)

# ---------------------------------------------------------------- lift_stage.cpp
LF_OLD = "        keep(13, g);\n"
LF_NEW = LF_OLD + '''        { // bbport (r89l_twigs-palette-move, TOOL): the offset counters: two sets a slot, the G-buffer's (PassBit in the word) and the rest
            const u32 offset_slot = scaled(at(region, u64(P::OffsetAt) * 4u), field(3, 10), u64(P::OffsetSlotWords) * 4u);
            const u32 offset_base = scaled(offset_slot, field(24, 1), u64(P::OffsetSetWords) * 4u);
            const auto offset_add = [&](u32 k, u32 value) {
                const u32 ptr = Emit(O(spv::Op::OpConvertUToPtr), ptr_u32, Ty::None, {at(offset_base, u64(k) * 4u)});
                const u32 prev = Emit(O(spv::Op::OpAtomicIAdd), t_u32, Ty::U32, {ptr, device, CU(0), value});
                nodes[m.NodeOf(prev)].effect = true;
            };
            const u32 move_mm = Emit(O(spv::Op::OpConvertFToU), t_u32, Ty::U32, {clamp_f(FMul(move, CF(1000.0f)), zero, CF(100000.0f))});
            offset_add(0, CU(1));
            offset_add(1, move_mm);
            offset_add(2, flag(FCmp(O(spv::Op::OpFOrdGreaterThan), move, CF(0.001f))));
            offset_add(3, flag(FCmp(O(spv::Op::OpFOrdGreaterThan), move, CF(0.01f))));
            offset_add(4, flag(FCmp(O(spv::Op::OpFOrdGreaterThan), move, CF(0.05f))));
            offset_add(5, flag(FCmp(O(spv::Op::OpFOrdGreaterThan), move, CF(0.10f))));
            const u32 move_bits = Emit(O(spv::Op::OpBitcast), t_u32, Ty::U32, {Ext(GLSLstd450FMax, t_f32, Ty::F32, {move, zero})});
            const u32 max_ptr = Emit(O(spv::Op::OpConvertUToPtr), ptr_u32, Ty::None, {at(offset_base, 24u)});
            const u32 prev_max = Emit(O(spv::Op::OpAtomicUMax), t_u32, Ty::U32, {max_ptr, device, CU(0), move_bits});
            nodes[m.NodeOf(prev_max)].effect = true;
        }
'''

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
EF_ST_OLD = "    u64 patched = 0;\n    u32 pipelines = 0;\n"
EF_ST_NEW = "    u64 patched = 0;\n    u64 gbuffer = 0; // bbport (r89l_twigs-palette-move): of the draws, those of the G-buffer pass\n    u32 pipelines = 0;\n"

EF_NOTE_OLD = ("static void TwigProofNote(u64 stream, const GraphicsPipeline* pipeline) {\n"
               "    TwigProofDraws& d = twig_proof_draws[stream];\n"
               "    ++d.draws;\n")
EF_NOTE_NEW = ("static void TwigProofNote(u64 stream, const GraphicsPipeline* pipeline, bool gbuffer) {\n"
               "    TwigProofDraws& d = twig_proof_draws[stream];\n"
               "    ++d.draws;\n"
               "    d.gbuffer += gbuffer ? 1 : 0; // bbport (r89l_twigs-palette-move)\n")

EF_CALL_OLD = "        TwigProofNote(positions, pipeline);\n"
EF_CALL_NEW = "        TwigProofNote(positions, pipeline, gbuffer_draw);\n"

EF_WORD_OLD = ("    if (tree) { // bbport (r89d_tree-twigs): its word (WindTwigWord), counted in its line\n"
               "        return WindTwigWord(words, frame_slot, view, taken, positions, positions_size, frame,\n"
               "                            snapshot.time, small_palette >= 0);\n"
               "    }\n")
EF_WORD_NEW = ("    if (tree) { // bbport (r89d_tree-twigs): its word (WindTwigWord), counted in its line\n"
               "        const u32 tree_word = WindTwigWord(words, frame_slot, view, taken, positions, positions_size, frame,\n"
               "                                           snapshot.time, small_palette >= 0);\n"
               "        // bbport (r89l_twigs-palette-move, TOOL): with the proof knob a G-buffer draw's word has PassBit (the\n"
               "        // lifter's offset counters keep the G-buffer's vertex runs apart from the other passes')\n"
               "        return tree_word != 0 && gbuffer_draw && BbWindTwigs::ProofOn() ? (tree_word | BbWindTwigs::PassBit) : tree_word;\n"
               "    }\n")

EF_GAIN_OLD = ("        return BbWindTwigs::TreeWord(frame_slot, view, taken.slot,\n"
               "                                     BbWindTwigs::TreeRamp(entry, time, taken.ramp));\n")
EF_GAIN_NEW = ("        // bbport (r89l_twigs-palette-move): a draw of the trees route keeps BB_WIND_TWIGS_TREES_GAIN of its ramp byte\n"
               "        return BbWindTwigs::TreeWord(\n"
               "            frame_slot, view, taken.slot,\n"
               "            small && BbWindTrees::On()\n"
               "                ? BbWindTrees::GainRamp(BbWindTwigs::TreeRamp(entry, time, taken.ramp), BbWindTrees::TreesGain())\n"
               "                : BbWindTwigs::TreeRamp(entry, time, taken.ramp));\n")

EF_RECT_OLD = "            trees_pick_rect_on = true;\n"
EF_RECT_NEW = ("            trees_pick_game = r; // bbport (r89l_twigs-palette-move): game-target pixels; the scissor block scales them\n"
               + EF_RECT_OLD)

EF_LOOP_OLD = ("        u32 lines = 0;\n"
               "        sway_slots.ForEachInUse(object_motion->Frame(), [&](u32 slot, u64 stream, u32) {\n"
               "            const BbWindTwigs::Entry* const entry = twig_book.Find(stream);\n"
               "            if (entry == nullptr || entry->verdict != BbWindTwigs::Verdict::Tree ||\n"
               "                lines >= BbWindTwigs::ProofLines) {\n"
               "                return;\n"
               "            }\n"
               "            ++lines;\n")
EF_LOOP_NEW = (
    "        u32 lines = 0;\n"
    "        BbWindTwigs::OffsetTotals palette_total, static_total; // bbport (r89l_twigs-palette-move): every tree mesh counts\n"
    "        sway_slots.ForEachInUse(object_motion->Frame(), [&](u32 slot, u64 stream, u32) {\n"
    "            const BbWindTwigs::Entry* const entry = twig_book.Find(stream);\n"
    "            if (entry == nullptr || entry->verdict != BbWindTwigs::Verdict::Tree) {\n"
    "                return;\n"
    "            }\n"
    "            {\n"
    "                const BbWindTwigs::SmallInfo* const offset_info = twig_book.FindInfo(stream);\n"
    "                const auto offset_found = twig_proof_draws.find(stream);\n"
    "                const TwigProofDraws offset_draws =\n"
    "                    offset_found != twig_proof_draws.end() ? offset_found->second : TwigProofDraws{};\n"
    "                BbWindTwigs::OffsetTotals& total = offset_info != nullptr && offset_info->palette ? palette_total : static_total;\n"
    "                total.Add(offset_draws.draws, offset_draws.gbuffer, BbWindTwigs::ReadOffset(words, slot),\n"
    "                          offset_info != nullptr ? static_cast<std::uint32_t>(offset_info->vs & 0xffffffffu) : 0u,\n"
    "                          offset_info != nullptr ? BbWindTwigs::ShaderPathOf(offset_info->vs) : std::uint8_t{0});\n"
    "            }\n"
    "            BbWindTwigs::ClearOffset(words, slot);\n"
    "            if (lines >= BbWindTwigs::ProofLines) { // only the first ProofLines meshes have a line of their own\n"
    "                BbWindTwigs::ClearProof(words, slot);\n"
    "                return;\n"
    "            }\n"
    "            ++lines;\n")

EF_PRINT_OLD = "        twig_proof_draws.clear();\n"
EF_PRINT_NEW = (
    "        // bbport (r89l_twigs-palette-move, TOOL): the twig offset of every tree mesh of the window\n"
    "        static bool offset_said = false;\n"
    "        if (!offset_said) {\n"
    "            offset_said = true;\n"
    "            char offset_once[704];\n"
    "            BbWindTwigs::OffsetOnceText(offset_once, sizeof(offset_once));\n"
    "            BbReport::Printf(\"%s\\n\", offset_once);\n"
    "        }\n"
    "        char offset_text[1400];\n"
    "        BbWindTwigs::OffsetLine(palette_total, static_total, offset_text, sizeof(offset_text));\n"
    "        BbReport::Printf(\"%s\\n\", offset_text);\n" + EF_PRINT_OLD)

# ---------------------------------------------------------------- tests/test_wind_trees.cpp
TE_OLD = ("        Expect(std::strstr(text, \"limb rule\") == nullptr, \"no limb text when the limb rule was not tried\");\n"
          "    }\n")
TE_NEW = TE_OLD + '''
    // bbport (r89l_twigs-palette-move): the pick's patch in raster pixels, the trees' gain, the offset counters' texts.
    {
        const B::Rect game = B::PickRect({480, 140}, 1280, 720, 1280, 720);
        const B::RasterRect same = B::PickRectRaster(game, 1.0f, 1.0f, 0.0f, 0.0f);
        Expect(same.x == game.x && same.y == game.y && same.w == game.w && same.h == game.h, "scale 1: the patch is as it was");
        const B::RasterRect half = B::PickRectRaster(game, 0.5f, 0.5f, 0.0f, 0.0f);
        Expect(half.w == 5 && half.h == 5 && half.x == 240 - 2 && half.y == 70 - 2, "a half-size raster: a 5x5 patch at half the coordinates");
        const B::Rect east_pixel = B::PickRect({1180, 60}, 1280, 720, 1280, 720);
        const B::RasterRect right = B::PickRectRaster(east_pixel, 0.5f, 0.5f, 0.0f, 0.0f);
        Expect(right.x == 590 - 2 && right.y == 30 - 2 && right.x + right.w <= 640, "a right-hand pixel lies inside a 640 wide raster");
        const B::RasterRect shifted = B::PickRectRaster(game, 0.5f, 0.5f, 10.0f, 4.0f);
        Expect(shifted.x == half.x + 10 && shifted.y == half.y + 4, "the target offset is added");
        const B::RasterRect corner = B::PickRectRaster(B::PickRect({0, 0}, 1280, 720, 1280, 720), 0.5f, 0.5f, 0.0f, 0.0f);
        Expect(corner.x == 0 && corner.y == 0 && corner.w == 3 && corner.h == 3, "the corner is cut at 0");
        Expect(B::PickRectRaster(B::Rect{}, 0.5f, 0.5f, 0.0f, 0.0f).w == 0 && B::PickRectRaster(game, 0.0f, 0.5f, 0.0f, 0.0f).w == 0 &&
                   B::PickRectRaster(game, std::numeric_limits<float>::quiet_NaN(), 0.5f, 0.0f, 0.0f).w == 0,
               "no patch for an empty rect or a scale that is 0 or not a number");
        char text[512];
        B::PickRasterText(1280, 720, 1280, 720, 0.5f, 0.5f, 0.0f, 0.0f, half.x, half.y, half.w, half.h, text, sizeof(text));
        Expect(std::strstr(text, "1280x720 picture, scaled to the game targets 1280x720 and then to the raster 640x360") != nullptr &&
                   std::strstr(text, "target scale 0.500 x 0.500") != nullptr,
               "the scaling line");

        Expect(B::GainRamp(255, 0.5f) == 128 && B::GainRamp(255, 1.0f) == 255 && B::GainRamp(255, 0.0f) == 0 && B::GainRamp(0, 0.5f) == 0 &&
                   B::GainRamp(1, 0.1f) == 1 && B::GainRamp(100, 2.0f) == 100 &&
                   B::GainRamp(255, std::numeric_limits<float>::quiet_NaN()) == 0 && B::GainRamp(300, 1.0f) == 255,
               "the gain on a ramp byte");
        Expect(B::TreesGainDefault == 0.5f && B::TreesGain() >= 0.0f && B::TreesGain() <= 1.0f, "the trees' gain is a share");

        namespace T = BbWindTwigs;
        static_assert(T::OffsetSlotWords == 16 && T::OffsetEnd == T::OffsetAt + BbWindSway::BaseSlots * 16, "the offset block");
        Expect(T::PassBit == (1u << 24) && T::KnownVersion(2011 + 20 + T::OffsetAdd, 11, 21, 1000) &&
                   T::KnownVersion(2011 + T::OffsetAdd, 11, 21, 1000) && !T::KnownVersion(2011 + 250, 11, 21, 1000),
               "the offset shaders' version is known");
        std::vector<std::uint32_t> words(T::OffsetEnd, 0u);
        const std::uint32_t slot = 7;
        std::uint32_t* const at = words.data() + T::OffsetAt + slot * T::OffsetSlotWords;
        at[0] = 100;
        at[1] = 250;  // 25.0 cm in all over 100 runs: mean 0.25 cm... (mm)
        at[2] = 40;
        at[3] = 20;
        at[4] = 3;
        at[5] = 1;
        const float big = 0.12f;
        std::memcpy(&at[6], &big, sizeof(float));
        at[T::OffsetSetWords + 0] = 600;
        at[T::OffsetSetWords + 1] = 3000;
        at[T::OffsetSetWords + 2] = 500;
        at[T::OffsetSetWords + 3] = 300;
        at[T::OffsetSetWords + 4] = 40;
        at[T::OffsetSetWords + 5] = 9;
        const float big_gbuffer = 0.31f;
        std::memcpy(&at[T::OffsetSetWords + 6], &big_gbuffer, sizeof(float));
        const T::OffsetCounts counts = T::ReadOffset(words.data(), slot);
        Expect(counts.pass[0].verts == 100 && counts.pass[1].verts == 600 && counts.pass[1].over_5cm == 40 &&
                   std::fabs(counts.pass[1].move_max - 0.31f) < 1.0e-6f && std::fabs(counts.pass[0].move_max - 0.12f) < 1.0e-6f,
               "the offset counters are read by set");
        Expect(T::ReadOffset(words.data(), 5000).pass[1].verts == 0 && T::ReadOffset(nullptr, 1).pass[0].verts == 0,
               "a slot out of range or no words reads as 0");
        T::OffsetTotals pal;
        pal.Add(600, 590, counts, 0x7620368bu, 1);
        pal.Add(200, 0, counts, 0x7620368bu, 1);
        pal.Add(10, 10, T::OffsetCounts{}, 0x9da6aacbu, 2);
        Expect(pal.meshes == 3 && pal.draws == 810 && pal.gbuffer_draws == 600 && pal.vs_n == 2 && pal.pass[1].verts == 1200 &&
                   std::fabs(pal.pass[1].move_max - 0.31f) < 1.0e-6f,
               "the totals add meshes, draws, sets and name each vertex shader once");
        char line[1400];
        T::OffsetLine(pal, T::OffsetTotals{}, line, sizeof(line));
        Expect(std::strstr(line, "twig offset in palette path: 810 draws (600 in the G-buffer), 3 meshes, mean ") != nullptr &&
                   std::strstr(line, "max 31.00 cm") != nullptr && std::strstr(line, "vs 7620368b lifted") != nullptr &&
                   std::strstr(line, "vs 9da6aacb RECOMPILED (no counters, no tint)") != nullptr && std::strlen(line) < 1400,
               "the offset line names draws, mean, max and the shader paths");
        T::ClearOffset(words.data(), slot);
        Expect(T::ReadOffset(words.data(), slot).pass[1].verts == 0 && at[T::OffsetSetWords + 6] == 0, "the offset counters are cleared");
        T::NoteShaderPath(0x1234u, true);
        T::NoteShaderPath(0x1234u, false);
        T::NoteShaderPath(0x5678u, true);
        Expect(T::ShaderPathOf(0x1234u) == 3 && T::ShaderPathOf(0x5678u) == 1 && T::ShaderPathOf(0x9999u) == 0, "the shader path note");
        char once[704];
        T::OffsetOnceText(once, sizeof(once));
        Expect(std::strstr(once, "Wind twigs offset") != nullptr && std::strlen(once) < 700, "the once line");
    }
'''

# ---------------------------------------------------------------- README
README_ANCHOR = "| `BB_WIND_TWIGS_CENSUS` |"
README_NEW = (
    "| `BB_WIND_TWIGS_TREES_GAIN` | How much of the twig move the trees route keeps (r89l; needs `BB_WIND_TWIGS_TREES=1`): a share from 0 to 1 of the sway word's ramp byte of every draw taken as a tree or a limb piece, so the thin outer branches move that share of what r89k gave: `0.5` (default) is a few cm at 4 m/s (a 6 m piece: tip about 2.3 cm in the lean and 4.6 cm at the gust front, at most about 8 cm for the tallest pieces), slow and zero at the trunk (the weight rule is unchanged); `1` gives r89k's move back; `0` stops it. A change of the word on the CPU: no shader, pipeline key or cache version differs. Read once | `0.5` |\n"
    + README_ANCHOR)

RM_PROOF_OLD = "With it on: 11 atomic operations a twig vertex and 114752 bytes of the sway buffer; off: nothing is emitted | `0` |"
RM_PROOF_NEW = ("With it on: 11 atomic operations a twig vertex and 114752 bytes of the sway buffer; off: nothing is emitted. r89l adds 7 atomic operations "
                "a twig vertex run and 65536 bytes: the move of every vertex run is counted in two sets of the slot (the G-buffer's, by the sway word's pass bit "
                "set for G-buffer draws only, and the other passes'): vertex runs, the sum of the move, over 1 mm, 1 cm, 5 cm, 10 cm and the largest move, and every "
                "600 frames a line `Wind twigs offset (r89l, TOOL): twig offset in palette path: N draws (G in the G-buffer), M meshes, mean m cm, max m cm ...` "
                "for every tree mesh (not only the first six) with a bone palette, the G-buffer's runs apart from the other passes', the shader path of each "
                "vertex shader (made by the lifter, or RECOMPILED: no counters, no tint) and the static path in short; the numbers include the x5 | `0` |")

RM_PICK_OLD = "`BB_WIND_TWIGS_PICK_SIZE=WxH` (default `1280x720`) is the picture the pixels are read from."
RM_PICK_NEW = ("`BB_WIND_TWIGS_PICK_SIZE=WxH` (default `1280x720`) is the picture the pixels are read from (r89l: scaled to the game targets and then to the "
               "raster by the rasterizer's own target scale and offset, as the G-buffer's scissors are, and one line `Wind twigs pick (r89l): pick pixels are read "
               "in a ... picture, scaled to the game targets ... and then to the raster ...` says the sizes; before r89l a raster smaller than the game targets "
               "read the pixels at half the coordinates and none at x >= 640).")

EDITS = {
    TWIGS: [(TW_INC_OLD, TW_INC_NEW), (TW_PASS_OLD, TW_PASS_NEW), (TW_LAG_OLD, TW_LAG_NEW), (TW_BUF_OLD, TW_BUF_NEW),
            (TW_INIT_OLD, TW_INIT_NEW), (TW_RESET_OLD, TW_RESET_NEW), (TW_BIN_OLD, TW_BIN_NEW), (TW_KNOWN_OLD, TW_KNOWN_NEW),
            (TW_FUNCS_ANCHOR, TW_FUNCS_NEW)],
    TREES: [(TR_BOOK_OLD, TR_GAIN_NEW), (TR_PICKDRAW_OLD, TR_RASTER_NEW)],
    LIFT: [(LF_OLD, LF_NEW)],
    RASTH: [(RH_OLD, RH_NEW)],
    RAST: [(RC_OLD, RC_NEW)],
    CACHE: [(CA_A_OLD, CA_A_NEW), (CA_B_OLD, CA_B_NEW), (CA_C_OLD, CA_C_NEW)],
    EFFECTS: [(EF_ST_OLD, EF_ST_NEW), (EF_NOTE_OLD, EF_NOTE_NEW), (EF_CALL_OLD, EF_CALL_NEW), (EF_WORD_OLD, EF_WORD_NEW),
              (EF_GAIN_OLD, EF_GAIN_NEW), (EF_RECT_OLD, EF_RECT_NEW), (EF_LOOP_OLD, EF_LOOP_NEW), (EF_PRINT_OLD, EF_PRINT_NEW)],
    TEST: [(TE_OLD, TE_NEW)],
    README: [(README_ANCHOR, README_NEW), (RM_PROOF_OLD, RM_PROOF_NEW), (RM_PICK_OLD, RM_PICK_NEW)],
}

CHECKS = {
    TWIGS: [("inline constexpr std::uint32_t PassBit = 1u << 24;", 1), ("inline constexpr std::uint32_t OffsetAdd = 400;", 1),
            ("inline void OffsetLine(", 1), ("inline void NoteShaderPath(", 1), ("OffsetEnd * 4 : TwigBytes", 1)],
    TREES: [("inline RasterRect PickRectRaster(", 1), ("inline float TreesGain()", 1), ("inline std::uint32_t GainRamp(", 1),
            ("inline constexpr float TreesGainDefault = 0.5f;", 1), ("inline constexpr int PickHalf = 2;", 1)],
    LIFT: [("offset_add(0, CU(1));", 1), ("P::OffsetSetWords", 1)],
    RASTH: [("BbWindTrees::Rect trees_pick_game{};", 1)],
    RAST: [("BbWindTrees::PickRectRaster(trees_pick_game", 1), ("++trees_pick_meet;", 1), ("++trees_pick_apart;", 1)],
    CACHE: [("BbWindTwigs::NoteShaderPath(info.pgm_hash, bbport_lifted);", 1), ("bbport_lifted = true;", 1)],
    EFFECTS: [("TwigProofNote(positions, pipeline, gbuffer_draw);", 1), ("BbWindTwigs::OffsetLine(palette_total, static_total", 1),
              ("BbWindTrees::GainRamp(BbWindTwigs::TreeRamp(entry, time, taken.ramp), BbWindTrees::TreesGain())", 1),
              ("trees_pick_game = r;", 1), ("tree_word | BbWindTwigs::PassBit", 1)],
    TEST: [("B::PickRectRaster(game", 5), ("wind-trees-test: ok", 1)],
    README: [("| `BB_WIND_TWIGS_TREES_GAIN` |", 1), ("| `BB_WIND_TWIGS_CENSUS` |", 1), ("65536 bytes", 1), ("(r89l: scaled to the game targets", 1)],
}

# Numbers written twice: the header's constants and the README text.
TIES = [("inline constexpr float TreesGainDefault = 0.5f;", "| `BB_WIND_TWIGS_TREES_GAIN`", "| `0.5` |")]


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
    if texts[TWIGS].count("OffsetSlotWords = OffsetSets * OffsetSetWords;") != 1 or "65536 bytes" not in texts[README]:
        raise SystemExit("tie check: the offset block's size (1024 slots x 16 words x 4 bytes = 65536) against the README")
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
        raise SystemExit("%s is not a source tree root (set R89L_ROOT)" % ROOT)
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
            tmp = full + ".r89ltmp"
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
        tmp = full + ".r89ltmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
