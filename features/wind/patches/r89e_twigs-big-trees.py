# r89e_twigs-big-trees: FEATURE fix on top of r89d_tree-twigs (wind work). Same knobs as r89d: off unless
# BB_WIND=1 with the plant sway's lean; BB_WIND_TWIGS=0 gives r89c's trees; this patch adds the knob
# BB_WIND_TWIGS_SMALL (0 off = r89d as it is, 1 the rule below (default), 2 measure and log only, 3 the loose
# rule) and costs nothing with BB_WIND_TWIGS_SMALL=0 (no new path runs: every new CPU path starts with the once
# read ReachSmall(), no SPIR-V changes at all).
#
# THE OWNER: "I think if the small branches on the trees moved slighty due to wind that would look great." and
# "The sway on the trees either should be removed or very subtle unless it's strong wind" (twigs stir, trunks
# and limbs still).
# THE EVIDENCE (4K run, graveyard, strong wind 4 m/s, BB_WIND_TWIGS=3, REACH=2, camera on the big bare trees):
# "trees taken 6 (meshes: 6 lone, 0 sun; tallest 171.4/10.2/6.1 m), skipped 47400 by reason (draws:
# small-skeleton 42000, opaque 0, no-sun 5400)"; frame-to-frame motion identical with twigs 0, 1, 3: the big
# trees do not move. Rule (3) of r89d leaves every cut-out draw that is not Kind::Skinned out ("small-skeleton":
# a draw with a small bone palette or none, Kind::Other or Kind::GpuPalette), and the big bare trees are such
# draws. The 171.4 m "tallest" is a mesh whose world box spans levels (see INSTANCES below), not a tree.
#
# WHAT THIS PATCH DOES.
# 1. Candidates. Rasterizer's Motion block (vk_rasterizer.cpp) now hands a draw of a pipeline with the Sway bit
#    (a cut-out pixel shader) of Kind::Other (a static draw: no skinned palette, no GPU-written palette) to
#    WindSwayWord(pipeline, palette) (palette: whether it read a small bone palette), as the Skinned draws are.
#    WindSwayWord takes them only through the new WindTwigSmall (never as a plant, never as a hanging thing):
#      first sight of a position stream (per address and size), cheap checks from numbers the CPU has:
#        vertices = stream bytes / stride in [120, 250000] (else "verts-few" / "verts-many", refused for good);
#      at most SmallLiveMax (96) streams being measured at the same time (the others wait: counted
#      "deferred"), so the 512 plant slots are not eaten by walls;
#      the stream gets a base slot and a sway word with TreeBit and a ramp of 0 (the shaders offer its world
#      box keys; nothing moves) and r89d's Book judges it: first read 8 frames after the slot was taken, second
#      60 frames later (the GPU's keys of base, crown, x and z extent).
# 2. The verdict (BbWindTwigs::SmallWhy, a pure function the unit test runs). A small-skeleton stream is a TREE
#    when, at the second read: its box and heights moved at most 0.3 m since the first (still); its height h is 4
#    to 40 m (over 40 m: a mesh that spans levels, never a tree: also for the r89d sun-drawn rule now: TreeMax
#    60 -> 40); its larger horizontal width is at most 80 m, at most 1.8 h and at least 0.2 h (a wall or fence is
#    wide, a pole or lamp post is slim); its smaller horizontal width is at least 0.30 of the larger (a wall or
#    a fence line is thin; a tree's box is about square); and at most SmallInstMax (2) draws of the stream came
#    in one frame (a stream drawn at many places has a world box that spans them: its weights would be wrong
#    and it is no single tree). Else it is refused with its reason ("moved", "short", "tall", "box", "wide",
#    "slim", "thin", "instanced", "no-keys") and its slot is FREED at once (BbWindSway::Slots::Release), and
#    the stream never costs more than a map lookup per draw. "Cut-out alpha test": every candidate has it (the
#    pipeline has the Sway bit only when its pixel shader discards), bare branch cards are alpha tested, a plain
#    wall is not, so opaque walls are never candidates at all.
#    TREE: its word gets the ramp of r89d (1 s) and the shaders' twig weight (outer, upper branches stir, trunk
#    and big limbs still: r89d's rule, unchanged).
# 3. NUMBERS FIRST. Per candidate mesh one log line when it is judged (at most 64 lines) or refused by the
#    cheap check (at most 24): "Wind twigs (r89e) candidate TREE|refused: height H m, box X x Z m (box/height
#    R, thin T), verts V, far F, palette P, vs <hash> ps <hash>, draws N per frame M, why <reason>". "far" is
#    the share of 2048 sampled vertices farther than half the largest radius from the longest local axis, read
#    from the stream's memory if it is a float vector (-1: not read; the position's offset in the stride is
#    taken as 0): LOG ONLY, the rule does not use it. Every 600 frames a second line "Wind twigs (r89e,
#    BB_WIND_TWIGS_SMALL=N): small-skeleton cut-outs: meshes T tree, J judging; draws S seen, T tree, J
#    judging, R refused ... deferred D; over 40 m: M meshes (tallest ... m)". BB_WIND_TWIGS_SMALL=2 measures
#    and logs and takes nothing (nothing moves, only the keys are kept); 3 drops the shape and instance checks
#    (height 4-40 m, still, vertices) to see motion at all. grep "^Wind twigs" in the slot's session.log.
# 4. Over 40 m. The census no longer counts a mesh over 40 m among the trees (the 171.4 m "tallest"): the
#    second line counts them. A lone (bush rule) mesh that large still gets the plant sway's weights (the Book
#    never judged it): not changed here, the line shows how many there are.
# 5. The strength. BB_WIND_TWIGS stays 1 (TwigRatio 0.30). Twig tip at 1.5 m/s 0.6 cm steady and 1.3 cm at the
#    crest of a gust front, at 4 m/s 4.5 cm and 9.2 cm (r89d's numbers, BbWindTwigs::TipAt). At 4K output, 90 deg
#    horizontal field of view: 1 px = 1.04 cm at 20 m, 2.1 cm at 40 m: 4 m/s 4.3 / 8.8 px (20 m) or 2.2 / 4.4 px
#    (40 m) lean / gust crest, a few pixels in a still pair taken at random phases; 1.5 m/s 0.6 / 1.3 px (20 m),
#    nearly nothing. With a 60 deg field of view the pixel size is 0.64 of that (more pixels): the live knob
#    set:BB_WIND_TWIGS=0.6 is there if the owner finds it too much.
#
# INSTANCES (the limit). The GPU keeps ONE world box per position stream: a tree mesh the game draws at several
# places (one stream, several model matrices) has a box spanning them all (a 171 m tall "mesh" is such a
# stream), and the per-vertex twig weight reads the box's centre line. So such a stream is refused
# ("instanced", or by its shape), and its trees stay still: the safe failure. If the log then shows the big
# trees refused as "instanced" with draws per frame of 2 or more, the next step is a per-draw box (the draw's
# model matrix from the capture) or the vertex's local position in the shaders: not done here, not guessed.
#
# OFF. BB_WIND_TWIGS_SMALL=0, BB_WIND unset, BB_WIND_TWIGS=0 or BB_WIND_SWAY_STYLE=wave: ReachSmall() is false: the
# Motion block's ternary takes r89d's old branch (WindTwigSkip), the new functions are not called, no new
# memory is touched (the Book's info map is empty), the shaders and the pipeline cache keys are as before
# (this patch changes no shader text, no CMake or build.sh file: host and recompiled shader builds are byte for
# byte as without it).
# COST ON: per static cut-out draw a stream lookup (one hash map find, about 50 ns: 70 draws a frame in the
# graveyard run) and, for streams being measured (up to 96, about 70 frames each), the sway word's loads and
# the box keys' atomic minimums of r89d; the far share reads at most 2048 vertices once per stream (a few
# microseconds); the 600-frame census of at most 512 slots as before; memory: the Book's two maps (at most 4096
# entries, about 200 KB), no GPU memory.
#
# Files: edits only: bbport_wind_twigs.h (knob, rule, info, text), bbport_wind_sway.h (Slots::Release),
# vk_rasterizer_effects.cpp (WindSwayWord's small candidates, WindTwigSmall, WindTwigSmallVerdict, the report and
# once lines), vk_rasterizer.h (declarations), vk_rasterizer.cpp (the Motion block's one ternary branch),
# tests/test_wind_sway.cpp (a block), README.md (a row and one sentence).
# Order: after r89d (and everything on top of it in the tree); revert this one first.
#
# Use: python -I -X utf8 r89e_twigs-big-trees.py check | apply | revert (root from R89E_ROOT, else <tree>).
# Files keep their line ends. Originals are kept in r89e_backup/ next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89e_backup")
ROOT = os.environ.get("R89E_ROOT") or "<tree>"
G = "engine/gpu/"
R = G + "shadps4/video_core/renderer_vulkan/"
HEADER = G + "shim/bbport_wind_sway.h"
NEWH = G + "shim/bbport_wind_twigs.h"
EFFECTS = R + "vk_rasterizer_effects.cpp"
RASH = R + "vk_rasterizer.h"
RASC = R + "vk_rasterizer.cpp"
TEST = "engine/tests/test_wind_sway.cpp"
README = "README.md"

# ---------------------------------------------------------------- bbport_wind_twigs.h
N_CONST_OLD = "inline constexpr float TreeMin = 3.0f, TreeMax = 60.0f, BoxMax = 80.0f, StillTol = 0.3f;\n"
N_CONST_NEW = r'''inline constexpr float TreeMin = 3.0f, TreeMax = 40.0f, BoxMax = 80.0f, StillTol = 0.3f;
/// bbport (r89e_twigs-big-trees): the rule for static cut-out meshes (Kind::Other with a cut-out pixel
/// shader: the big bare trees): height SmallMinH to SmallMaxH, larger horizontal box width between
/// SmallAspectLo and SmallAspectHi of the height, smaller width at least SmallThin of the larger, at
/// most SmallInstMax draws of the stream in a frame; its vertex count between SmallMinVerts and
/// SmallMaxVerts; at most SmallLiveMax streams measured at once; FarShare samples SmallSample vertices;
/// the log's lines: SmallLogJudged for judged streams, SmallLogRefused for the cheap check's refusals.
inline constexpr float SmallMinH = 4.0f, SmallMaxH = TreeMax;
inline constexpr float SmallAspectLo = 0.20f, SmallAspectHi = 1.8f, SmallThin = 0.30f;
inline constexpr std::uint32_t SmallMinVerts = 120, SmallMaxVerts = 250000, SmallInstMax = 2;
inline constexpr std::uint32_t SmallLiveMax = 96, SmallSample = 2048;
inline constexpr std::uint32_t SmallLogJudged = 64, SmallLogRefused = 24;
'''
N_KNOB_OLD = "    int reach = 1;\n};\n"
N_KNOB_NEW = ("    int reach = 1;\n"
              "    int small = 1; ///< bbport (r89e): BB_WIND_TWIGS_SMALL 0 off, 1 the rule, 2 log only, 3 loose\n"
              "};\n")
N_PARSE_OLD = ("[[nodiscard]] inline Knob ParseKnob(const char* twigs, const char* reach, bool sway_on, bool lean) {\n"
               "    Knob k;\n"
               "    k.twigs = ParseTwigs(twigs);\n")
N_PARSE_NEW = ("[[nodiscard]] inline Knob ParseKnob(const char* twigs, const char* reach, bool sway_on, bool lean,\n"
               "                                    const char* small = nullptr) {\n"
               "    Knob k;\n"
               "    k.twigs = ParseTwigs(twigs);\n"
               "    {   // bbport (r89e_twigs-big-trees): BB_WIND_TWIGS_SMALL 0-3, unset or unreadable 1\n"
               "        const float s = W::ParseNumber(small, 1.0f);\n"
               "        k.small = s >= 2.5f ? 3 : (s >= 1.5f ? 2 : (s >= 0.5f ? 1 : 0));\n"
               "    }\n")
N_ONCE_OLD = ("                                       W::KnobOnce().on, W::LeanKnobOnce().lean);\n"
              "    return knob;\n")
N_ONCE_NEW = ("                                       W::KnobOnce().on, W::LeanKnobOnce().lean,\n"
              "                                       std::getenv(\"BB_WIND_TWIGS_SMALL\"));\n"
              "    return knob;\n")
N_REACH_OLD = ("[[nodiscard]] inline bool ReachOpaque() {\n"
               "    return KnobOnce().on && KnobOnce().reach >= 2;\n"
               "}\n")
N_REACH_NEW = N_REACH_OLD + r'''
/// bbport (r89e_twigs-big-trees): whether static cut-out draws are candidates (BB_WIND_TWIGS_SMALL above 0).
[[nodiscard]] inline bool ReachSmall() {
    return KnobOnce().on && KnobOnce().small >= 1;
}

/// BB_WIND_TWIGS_SMALL=2: the candidates are measured and logged, none is taken.
[[nodiscard]] inline bool SmallLogOnly() {
    return KnobOnce().small == 2;
}

/// BB_WIND_TWIGS_SMALL=3: the shape and instance checks are dropped (height, still and vertices stay).
[[nodiscard]] inline bool SmallLoose() {
    return KnobOnce().small >= 3;
}
'''
N_ENTRY_OLD = ("    bool ramping = false;                  ///< a tree's ramp has begun\n"
               "    double tree_since = 0.0;               ///< wind time of its first word as a tree\n"
               "};\n")
N_ENTRY_NEW = ("    bool ramping = false;                  ///< a tree's ramp has begun\n"
               "    double tree_since = 0.0;               ///< wind time of its first word as a tree\n"
               "    // bbport (r89e_twigs-big-trees): a static cut-out candidate (SmallWhy judges it)\n"
               "    bool small = false, loose = false, logged = false;\n"
               "    std::uint32_t per_frame = 0;           ///< most draws of its stream in one frame so far\n"
               "    const char* why = nullptr;             ///< the reason it is no tree (a string literal)\n"
               "    Measure last;                          ///< its measure at the verdict (not ok: none)\n"
               "};\n")
# SmallWhy before the Verdict enum
N_VERDICT_OLD = "enum class Verdict : std::uint8_t { Waiting, Tree, NotTree };\n"
N_VERDICT_NEW = r'''/// bbport (r89e_twigs-big-trees): why a static cut-out mesh measuring `m` is no tree (a string literal),
/// nullptr when it is one. `moved`: how far its box and heights moved between the two reads (m);
/// `per_frame`: the most draws of its stream in one frame; `loose`: BB_WIND_TWIGS_SMALL=3 (no shape or
/// instance check). Pure: engine/tests/test_wind_sway.cpp runs it.
[[nodiscard]] inline const char* SmallWhy(const Measure& m, float moved, std::uint32_t per_frame,
                                          bool loose) {
    const float h = m.crown - m.base;
    const float wx = m.x_hi - m.x_lo, wz = m.z_hi - m.z_lo;
    const float wmax = std::max(wx, wz), wmin = std::min(wx, wz);
    if (!(h > 0.0f) || !(wmax >= 0.0f) || !(wmin >= 0.0f)) {
        return "height";
    }
    if (!(moved <= StillTol)) {
        return "moved";
    }
    if (h < SmallMinH) {
        return "short";
    }
    if (h > SmallMaxH) {
        return "tall";
    }
    if (loose) {
        return nullptr;
    }
    if (wmax > BoxMax) {
        return "box";
    }
    if (per_frame > SmallInstMax) {
        return "instanced";
    }
    if (wmax > SmallAspectHi * h) {
        return "wide";
    }
    if (wmax < SmallAspectLo * h) {
        return "slim";
    }
    if (wmin < SmallThin * wmax) {
        return "thin";
    }
    return nullptr;
}

/// The cheap check on a new stream's vertex count: nullptr, "verts-few" or "verts-many".
[[nodiscard]] inline const char* SmallPrefilter(std::uint32_t verts) {
    return verts < SmallMinVerts ? "verts-few" : (verts > SmallMaxVerts ? "verts-many" : nullptr);
}

/// What the CPU read of a static cut-out stream at its first sight (for the log; far_share is not used
/// by the rule).
struct SmallInfo {
    std::uint32_t verts = 0;
    float far_share = -1.0f;            ///< see FarShare (-1: not read)
    std::uint64_t vs = 0, ps = 0;       ///< the vertex and pixel shaders' hashes
    bool palette = false;               ///< it read a small bone palette
    std::uint64_t draws = 0;            ///< draws seen
    std::uint64_t frame = 0;            ///< the frame `frame_draws` counts
    std::uint32_t frame_draws = 0, max_per_frame = 0;
};

''' + N_VERDICT_OLD
N_BOOK_OLD = "class Book {\npublic:\n"
N_BOOK_NEW = "class Book {\npublic:\n" + r'''    /// bbport (r89e_twigs-big-trees): the stream's info (nullptr: none), set or replaced, and the stream
    /// refused by a cheap check (an entry with the verdict NotTree and no slot).
    [[nodiscard]] SmallInfo* FindInfo(std::uint64_t stream) {
        const auto found = infos.find(stream);
        return found == infos.end() ? nullptr : &found->second;
    }

    SmallInfo& SetInfo(std::uint64_t stream, const SmallInfo& info) {
        if (infos.size() >= BookMost && infos.find(stream) == infos.end()) {
            infos.clear();
        }
        return infos[stream] = info;
    }

    Entry& Refuse(std::uint64_t stream, std::uint32_t size, std::uint64_t frame, const char* why) {
        Entry& e = Touch(stream, size, 0xffffffffu, true, frame);
        e.small = true;
        e.verdict = Verdict::NotTree;
        e.why = why;
        return e;
    }

    /// How many candidates are being measured (a slot, no verdict, drawn within the last 2 frames);
    /// counted once a frame.
    [[nodiscard]] std::uint32_t LiveSmall(std::uint64_t frame) {
        if (live_frame != frame) {
            live_frame = frame;
            live = 0;
            for (const auto& item : entries) {
                const Entry& e = item.second;
                live += e.small && e.verdict == Verdict::Waiting && e.slot != 0xffffffffu &&
                                e.seen + 2 >= frame
                            ? 1u
                            : 0u;
            }
        }
        return live;
    }

'''
N_PRIV_OLD = "    std::unordered_map<std::uint64_t, Entry> entries;\n};\n"
N_PRIV_NEW = ("    std::unordered_map<std::uint64_t, Entry> entries;\n"
              "    std::unordered_map<std::uint64_t, SmallInfo> infos; // bbport (r89e_twigs-big-trees)\n"
              "    std::uint64_t live_frame = ~std::uint64_t(0);\n"
              "    std::uint32_t live = 0;\n"
              "};\n")
N_GIVEUP_OLD = ("        if (frame >= e.first + GiveUpFrames) {\n"
                "            e.verdict = Verdict::NotTree;\n"
                "        }\n")
N_GIVEUP_NEW = ("        if (frame >= e.first + GiveUpFrames) {\n"
                "            e.verdict = Verdict::NotTree;\n"
                "            e.why = \"no-keys\"; // bbport (r89e_twigs-big-trees)\n"
                "        }\n")
N_JUDGE_OLD = ("    e.height = m.crown - m.base;\n"
               "    const bool sane = e.height <= TreeMax")
N_JUDGE_NEW = ("    e.height = m.crown - m.base;\n"
               "    e.last = m;\n"
               "    if (e.small) { // bbport (r89e_twigs-big-trees): a static cut-out candidate\n"
               "        e.why = SmallWhy(m, Moved(e.snap, m), e.per_frame, e.loose);\n"
               "        e.verdict = e.why == nullptr ? Verdict::Tree : Verdict::NotTree;\n"
               "        return e.verdict;\n"
               "    }\n"
               "    const bool sane = e.height <= TreeMax")
N_STATS_OLD = ("    std::uint64_t opaque = 0;     ///< skinned draws of pipelines without a cut-out (no sway code)\n"
               "};\n")
N_STATS_NEW = ("    std::uint64_t opaque = 0;     ///< skinned draws of pipelines without a cut-out (no sway code)\n"
               "    // bbport (r89e_twigs-big-trees): static cut-out candidates: draws seen, given a tree's word,\n"
               "    // still judged (ramp 0), refused, left waiting for a free measuring place; meshes the cheap\n"
               "    // check refused\n"
               "    std::uint64_t small_seen = 0, small_tree = 0, small_judging = 0, small_refused = 0,\n"
               "                  small_deferred = 0, small_pre = 0;\n"
               "};\n")
N_CENSUS_OLD = ("    std::uint32_t lone = 0, sun = 0, sun_not = 0;\n"
                "    std::array<float, TallestShown> tallest{};\n")
N_CENSUS_NEW = ("    std::uint32_t lone = 0, sun = 0, sun_not = 0;\n"
                "    std::array<float, TallestShown> tallest{};\n"
                "    // bbport (r89e_twigs-big-trees): static cut-out trees, those still judged, and meshes over\n"
                "    // SmallMaxH (not trees) with the tallest\n"
                "    std::uint32_t small = 0, small_wait = 0, huge = 0;\n"
                "    float huge_top = 0.0f;\n\n"
                "    void Huge(float height) {\n"
                "        ++huge;\n"
                "        huge_top = std::max(huge_top, height);\n"
                "    }\n")
N_END_OLD = "} // namespace BbWindTwigs\n"
N_END_NEW = r'''// bbport (r89e_twigs-big-trees): the far share and the log's texts of the static cut-out candidates.

/// The share (0-1) of up to SmallSample vertices, sampled evenly from `count` float vectors `stride`
/// bytes apart starting at `data`, that lie farther than half the largest radius from the mesh's longest
/// local axis (a trunk and a few limbs: low; a wall or a flat card: high). -1 when it cannot be told
/// (fewer than 8 vertices, a stride under 12, a vertex that is not a number). Log only.
[[nodiscard]] inline float FarShare(const unsigned char* data, std::uint32_t stride, std::uint32_t count) {
    if (data == nullptr || stride < 12 || count < 8) {
        return -1.0f;
    }
    const std::uint32_t n = std::min(count, SmallSample);
    const auto fetch = [&](std::uint32_t i, std::array<float, 3>& v) {
        std::memcpy(v.data(), data + (std::uint64_t(i) * count / n) * stride, 12);
        return std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]);
    };
    std::array<float, 3> lo{1e30f, 1e30f, 1e30f}, hi{-1e30f, -1e30f, -1e30f}, v{};
    std::uint32_t good = 0;
    for (std::uint32_t i = 0; i < n; ++i) {
        if (!fetch(i, v)) {
            continue;
        }
        ++good;
        for (int c = 0; c < 3; ++c) {
            lo[c] = std::min(lo[c], v[c]);
            hi[c] = std::max(hi[c], v[c]);
        }
    }
    if (good < 8) {
        return -1.0f;
    }
    int up = 0;
    for (int c = 1; c < 3; ++c) {
        up = hi[c] - lo[c] > hi[up] - lo[up] ? c : up;
    }
    const int a = (up + 1) % 3, b = (up + 2) % 3;
    const float ca = 0.5f * (lo[a] + hi[a]), cb = 0.5f * (lo[b] + hi[b]);
    float rmax = 0.0f;
    for (std::uint32_t i = 0; i < n; ++i) {
        if (fetch(i, v)) {
            rmax = std::max(rmax, std::hypot(v[a] - ca, v[b] - cb));
        }
    }
    if (!(rmax > 1e-6f)) {
        return -1.0f;
    }
    std::uint32_t far_count = 0;
    for (std::uint32_t i = 0; i < n; ++i) {
        if (fetch(i, v) && std::hypot(v[a] - ca, v[b] - cb) > 0.5f * rmax) {
            ++far_count;
        }
    }
    return float(far_count) / float(good);
}

/// One candidate's line when it is judged or refused by the cheap check (under 300 characters):
/// "Wind twigs (r89e) candidate TREE: height ... m, box X x Z m (box/height R, thin T), verts V, far F,
/// palette P, vs H ps H, draws N per frame M, why ...". `info` may be null.
inline void SmallLine(const Entry& e, const SmallInfo* info, char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    const Measure& m = e.last;
    const float h = m.crown - m.base, wx = m.x_hi - m.x_lo, wz = m.z_hi - m.z_lo;
    const float wmax = std::max(wx, wz), wmin = std::min(wx, wz);
    char shape[96];
    if (m.ok && h > 0.0f && wmax > 0.0f) {
        std::snprintf(shape, sizeof(shape), "height %.1f m, box %.1f x %.1f m (box/height %.2f, thin %.2f)",
                      double(h), double(wx), double(wz), double(wmax / h), double(wmin / wmax));
    } else {
        std::snprintf(shape, sizeof(shape), "not measured");
    }
    std::snprintf(out, size,
                  "Wind twigs (r89e) candidate %s: %s, verts %u, far %.2f, palette %d, vs %08x ps %08x, "
                  "draws %llu per frame %u, why %s",
                  e.verdict == Verdict::Tree ? "TREE" : "refused", shape, info ? info->verts : 0u,
                  double(info ? info->far_share : -1.0f), info && info->palette ? 1 : 0,
                  info ? static_cast<unsigned>(info->vs & 0xffffffffu) : 0u,
                  info ? static_cast<unsigned>(info->ps & 0xffffffffu) : 0u, n(info ? info->draws : 0),
                  info ? info->max_per_frame : 0u, e.why != nullptr ? e.why : "-");
}

/// The once line of the static cut-out candidates (BB_WIND_TWIGS_SMALL above 0), under 300 characters.
inline void SmallOnceText(const Knob& k, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs (r89e, BB_WIND_TWIGS_SMALL=%d): static cut-outs of %.0f-%.0f m (box/height "
                  "%.2f-%.1f, thin %.2f, at most %u draws a frame, %u+ vertices) are judged by their "
                  "world box for %u frames and stir if still; %s",
                  k.small, double(SmallMinH), double(SmallMaxH), double(SmallAspectLo), double(SmallAspectHi),
                  double(SmallThin), SmallInstMax, SmallMinVerts, unsigned(JudgeFrames + StillFrames),
                  k.small == 2 ? "log only, none taken" : (k.small >= 3 ? "loose rule" : "default rule"));
}

/// The line every W::ReportFrames frames for the candidates (under 300 characters).
inline void SmallReportText(const Census& census, const Stats& st, const Knob& k, char* out,
                            std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(out, size,
                  "Wind twigs (r89e, BB_WIND_TWIGS_SMALL=%d): small-skeleton cut-outs: meshes %u tree, %u "
                  "judging; draws %llu seen, %llu tree, %llu judging, %llu refused (%llu meshes by the cheap "
                  "check), %llu deferred; over %.0f m: %u meshes (tallest %.1f m)",
                  k.small, census.small, census.small_wait, n(st.small_seen), n(st.small_tree),
                  n(st.small_judging), n(st.small_refused), n(st.small_pre), n(st.small_deferred),
                  double(SmallMaxH), census.huge, double(census.huge_top));
}

} // namespace BbWindTwigs
'''

# ---------------------------------------------------------------- bbport_wind_sway.h
H_REL_OLD = ("    /// bbport (r89d_tree-twigs): fn(slot, stream, size) for each slot drawn within the last\n"
             "    /// ReuseFrames frames.\n")
H_REL_NEW = ("    /// bbport (r89e_twigs-big-trees): gives a stream's slot back (a static cut-out judged not a\n"
             "    /// tree). The slot rests ReuseFrames frames like any slot no longer drawn (frames still in\n"
             "    /// flight write the old stream's keys; FrameSlots < ReuseFrames), then another stream may\n"
             "    /// take it and reset its keys.\n"
             "    void Release(std::uint64_t stream) {\n"
             "        const auto found = by_stream.find(stream);\n"
             "        if (found == by_stream.end()) {\n"
             "            return;\n"
             "        }\n"
             "        slots[found->second].released = true;\n"
             "        by_stream.erase(found);\n"
             "    }\n\n") + H_REL_OLD
# bbport (r89e review): a released slot keeps its old stream until reused; the reuse erases the
# old stream's map entry only when it still points at this slot (as before for every other slot).
H_TAKE_OLD = ("        if (slots[best].stream != 0) {\n"
              "            by_stream.erase(slots[best].stream);\n"
              "        }\n")
H_TAKE_NEW = ("        if (slots[best].stream != 0) {\n"
              "            const auto old = by_stream.find(slots[best].stream); // bbport (r89e): Release\n"
              "            if (old != by_stream.end() && old->second == best) {\n"
              "                by_stream.erase(old);\n"
              "            }\n"
              "        }\n")
H_SLOT_OLD = ("        double time = 0.0;\n"
              "    };\n")
H_SLOT_NEW = ("        double time = 0.0;\n"
              "        bool released = false; ///< bbport (r89e_twigs-big-trees): given back by Release\n"
              "    };\n")

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
E_SIG_OLD = "u32 Rasterizer::WindSwayWord(const GraphicsPipeline* pipeline) {\n"
E_SIG_NEW = "u32 Rasterizer::WindSwayWord(const GraphicsPipeline* pipeline, int small_palette) {\n"
E_FETCH_OLD = ("    u64 positions = 0;\n"
               "    u32 positions_size = 0;\n"
               "    if (fetch) {\n"
               "        for (const auto& attribute : fetch->attributes) {\n"
               "            if (attribute.semantic == 0) {\n"
               "                const auto stream = attribute.GetSharp(vs);\n"
               "                positions = stream.base_address;\n"
               "                positions_size = stream.GetSize();\n"
               "                break;\n")
E_FETCH_NEW = ("    u64 positions = 0;\n"
               "    u32 positions_size = 0;\n"
               "    u32 positions_stride = 0;     // bbport (r89e_twigs-big-trees): for the static cut-outs\n"
               "    bool positions_floats = false; // (float vectors: FarShare reads them for the log)\n"
               "    if (fetch) {\n"
               "        for (const auto& attribute : fetch->attributes) {\n"
               "            if (attribute.semantic == 0) {\n"
               "                const auto stream = attribute.GetSharp(vs);\n"
               "                positions = stream.base_address;\n"
               "                positions_size = stream.GetSize();\n"
               "                positions_stride = stream.GetStride();\n"
               "                positions_floats = (stream.GetDataFmt() == AmdGpu::DataFormat::Format32_32_32 ||\n"
               "                                    stream.GetDataFmt() == AmdGpu::DataFormat::Format32_32_32_32) &&\n"
               "                                   stream.GetNumberFmt() == AmdGpu::NumberFormat::Float;\n"
               "                break;\n")
E_TREE_OLD = ("    const bool plant = rt_shadow->LonePlant(positions, positions_size);\n"
              "    // bbport (r89d_tree-twigs): or a sun-drawn skinned stream that measures as a tree (WindTwigTree)\n"
              "    const bool tree = !plant && WindTwigTree(positions, positions_size);\n"
              "    hang_judge = false; // bbport (r112f_hang-gpu-judge): WindHangVerdict sets it for a candidate\n"
              "    bool hang = !plant && !tree && WindHangVerdict(pipeline, positions, positions_size);\n")
E_TREE_NEW = ("    // bbport (r89e_twigs-big-trees): small_palette 0 or 1: a static cut-out (Kind::Other) candidate for the\n"
              "    // twigs only (WindTwigSmall), never a plant or a hanging thing; -1: a skinned draw, as before\n"
              "    const bool plant = small_palette < 0 && rt_shadow->LonePlant(positions, positions_size);\n"
              "    // bbport (r89d_tree-twigs): or a sun-drawn skinned stream that measures as a tree (WindTwigTree)\n"
              "    const bool tree = !plant && (small_palette >= 0\n"
              "                                     ? WindTwigSmall(pipeline, positions, positions_size,\n"
              "                                                     positions_stride, positions_floats,\n"
              "                                                     small_palette != 0)\n"
              "                                     : WindTwigTree(positions, positions_size));\n"
              "    hang_judge = false; // bbport (r112f_hang-gpu-judge): WindHangVerdict sets it for a candidate\n"
              "    bool hang = !plant && !tree && small_palette < 0 && // (r89e: never a static cut-out)\n"
              "                WindHangVerdict(pipeline, positions, positions_size);\n")
E_WORD_OLD = ("        return WindTwigWord(words, frame_slot, view, taken, positions, positions_size, frame,\n"
              "                            snapshot.time);\n")
E_WORD_NEW = ("        return WindTwigWord(words, frame_slot, view, taken, positions, positions_size, frame,\n"
              "                            snapshot.time, small_palette >= 0);\n")
E_TWORD_OLD = (
    "u32 Rasterizer::WindTwigWord(u32* words, u32 frame_slot, u32 view,\n"
    "                             const BbWindSway::Slots::Taken& taken, u64 positions,\n"
    "                             u32 positions_size, u64 frame, double time) {\n"
    "    BbWindTwigs::Entry& entry =\n"
    "        twig_book.Touch(positions, positions_size, taken.slot, taken.reset, frame);\n"
    "    switch (BbWindTwigs::Judge(entry, words, frame)) {\n"
    "    case BbWindTwigs::Verdict::Tree:\n"
    "        ++twig_stats.tree_draws;\n"
    "        return BbWindTwigs::TreeWord(frame_slot, view, taken.slot,\n"
    "                                     BbWindTwigs::TreeRamp(entry, time, taken.ramp));\n"
    "    case BbWindTwigs::Verdict::NotTree:\n"
    "        ++twig_stats.not_tree;\n"
    "        return 0;\n"
    "    case BbWindTwigs::Verdict::Waiting:\n"
    "        break;\n"
    "    }\n"
    "    ++twig_stats.measuring;\n"
    "    return BbWindTwigs::TreeWord(frame_slot, view, taken.slot, 0);\n"
    "}\n")
E_TWORD_NEW = (
    "u32 Rasterizer::WindTwigWord(u32* words, u32 frame_slot, u32 view,\n"
    "                             const BbWindSway::Slots::Taken& taken, u64 positions,\n"
    "                             u32 positions_size, u64 frame, double time, bool small) {\n"
    "    BbWindTwigs::Entry& entry =\n"
    "        twig_book.Touch(positions, positions_size, taken.slot, taken.reset, frame);\n"
    "    if (small) { // bbport (r89e_twigs-big-trees): a static cut-out: its own judging and counts\n"
    "        entry.small = true;\n"
    "        entry.loose = BbWindTwigs::SmallLoose();\n"
    "        if (const BbWindTwigs::SmallInfo* const info = twig_book.FindInfo(positions)) {\n"
    "            entry.per_frame = info->max_per_frame;\n"
    "        }\n"
    "    }\n"
    "    const BbWindTwigs::Verdict verdict = BbWindTwigs::Judge(entry, words, frame);\n"
    "    if (small && verdict != BbWindTwigs::Verdict::Waiting) {\n"
    "        WindTwigSmallVerdict(entry, positions);\n"
    "    }\n"
    "    switch (verdict) {\n"
    "    case BbWindTwigs::Verdict::Tree:\n"
    "        if (small && BbWindTwigs::SmallLogOnly()) { // BB_WIND_TWIGS_SMALL=2: measured, none taken\n"
    "            ++twig_stats.small_judging;\n"
    "            return BbWindTwigs::TreeWord(frame_slot, view, taken.slot, 0);\n"
    "        }\n"
    "        if (small) {\n"
    "            ++twig_stats.small_tree;\n"
    "        } else {\n"
    "            ++twig_stats.tree_draws;\n"
    "        }\n"
    "        return BbWindTwigs::TreeWord(frame_slot, view, taken.slot,\n"
    "                                     BbWindTwigs::TreeRamp(entry, time, taken.ramp));\n"
    "    case BbWindTwigs::Verdict::NotTree:\n"
    "        if (small) { // its slot goes back at once; the stream costs a lookup from now on\n"
    "            ++twig_stats.small_refused;\n"
    "            sway_slots.Release(positions);\n"
    "        } else {\n"
    "            ++twig_stats.not_tree;\n"
    "        }\n"
    "        return 0;\n"
    "    case BbWindTwigs::Verdict::Waiting:\n"
    "        break;\n"
    "    }\n"
    "    if (small) {\n"
    "        ++twig_stats.small_judging;\n"
    "    } else {\n"
    "        ++twig_stats.measuring;\n"
    "    }\n"
    "    return BbWindTwigs::TreeWord(frame_slot, view, taken.slot, 0);\n"
    "}\n")
E_SKIP_ANCHOR = "// bbport (r89d_tree-twigs): the Motion block's draws that got no sway word because the sway cannot\n"
E_SMALL = r'''// bbport (r89e_twigs-big-trees): whether a static cut-out draw (Kind::Other, a pipeline with the Sway
// bit) may be a tree the twigs take (BB_WIND_TWIGS_SMALL above 0): a stream already judged not a tree,
// or refused by the cheap check, costs one map lookup; a new stream is checked by its vertex count
// (SmallPrefilter), read for the log (FarShare, shader hashes), and measured by the Book (the caller
// gives it a slot and a word of ramp 0) while fewer than SmallLiveMax streams are being measured.
// Counts the draws of a stream in a frame (SmallInstMax). On the thread recording draws.
bool Rasterizer::WindTwigSmall(const GraphicsPipeline* pipeline, u64 positions, u32 positions_size,
                               u32 stride, bool floats, bool palette) {
    if (!BbWindTwigs::ReachSmall() || positions == 0 || positions_size == 0 || stride == 0) {
        return false;
    }
    ++twig_stats.small_seen;
    const u64 frame = object_motion->Frame();
    const u32 verts = positions_size / stride;
    const BbWindTwigs::Entry* const entry = twig_book.Find(positions);
    if (entry != nullptr && entry->size == positions_size) {
        if (!entry->small) {
            return false; // a stream the sun-drawn rule keeps
        }
        if (entry->verdict == BbWindTwigs::Verdict::NotTree) {
            ++twig_stats.small_refused;
            return false;
        }
    }
    if (BbWindTwigs::SmallInfo* const known = twig_book.FindInfo(positions)) {
        if (known->verts == verts) {
            ++known->draws;
            if (known->frame != frame) {
                known->frame = frame;
                known->frame_draws = 0;
            }
            known->max_per_frame = std::max(known->max_per_frame, ++known->frame_draws);
            return true;
        }
    }
    if (twig_book.LiveSmall(frame) >= BbWindTwigs::SmallLiveMax) {
        ++twig_stats.small_deferred;
        return false;
    }
    BbWindTwigs::SmallInfo fresh;
    fresh.verts = verts;
    fresh.palette = palette;
    fresh.draws = 1;
    fresh.frame = frame;
    fresh.frame_draws = fresh.max_per_frame = 1;
    fresh.vs = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
    fresh.ps = FragmentHash(pipeline);
    const u64 bytes = u64(verts) * stride;
    if (floats && stride >= 12 && bytes != 0 && memory->IsValidGpuMapping(positions, 0) &&
        memory->ClampRangeSize(positions, bytes) == bytes) {
        fresh.far_share =
            BbWindTwigs::FarShare(reinterpret_cast<const unsigned char*>(positions), stride, verts);
    }
    twig_book.SetInfo(positions, fresh);
    if (const char* const why = BbWindTwigs::SmallPrefilter(verts)) {
        BbWindTwigs::Entry& refused = twig_book.Refuse(positions, positions_size, frame, why);
        ++twig_stats.small_pre;
        ++twig_stats.small_refused;
        WindTwigSmallVerdict(refused, positions);
        return false;
    }
    return true;
}

// bbport (r89e_twigs-big-trees): a candidate's verdict line, once per entry, at most SmallLogJudged
// lines for judged streams and SmallLogRefused for those the cheap check refused (no slot). On the
// thread recording draws.
void Rasterizer::WindTwigSmallVerdict(BbWindTwigs::Entry& entry, u64 positions) {
    static u32 judged_lines = 0, refused_lines = 0;
    if (entry.logged) {
        return;
    }
    entry.logged = true;
    const bool cheap = entry.slot == 0xffffffffu;
    u32& lines = cheap ? refused_lines : judged_lines;
    if (lines >= (cheap ? BbWindTwigs::SmallLogRefused : BbWindTwigs::SmallLogJudged)) {
        return;
    }
    ++lines;
    char text[384];
    BbWindTwigs::SmallLine(entry, twig_book.FindInfo(positions), text, sizeof(text));
    BbReport::Printf("%s\n", text);
}

'''
E_REPORT_OLD = ("        const float height = m.crown - m.base;\n"
                "        if (!m.ok || height < BbWindSway::TreeLo) {\n"
                "            return;\n"
                "        }\n"
                "        const BbWindTwigs::Entry* const entry = twig_book.Find(stream);\n"
                "        if (entry != nullptr && entry->verdict == BbWindTwigs::Verdict::Tree) {\n"
                "            ++census.sun;\n"
                "            census.Tall(height);\n"
                "        } else if (rt_shadow->LonePlant(stream, size)) {\n")
E_REPORT_NEW = ("        const float height = m.crown - m.base;\n"
                "        if (!m.ok || height < BbWindSway::TreeLo) {\n"
                "            return;\n"
                "        }\n"
                "        if (height > BbWindTwigs::SmallMaxH) { // bbport (r89e): over 40 m: no tree\n"
                "            census.Huge(height);\n"
                "            return;\n"
                "        }\n"
                "        const BbWindTwigs::Entry* const entry = twig_book.Find(stream);\n"
                "        if (entry != nullptr && entry->small) { // bbport (r89e): a static cut-out candidate\n"
                "            if (entry->verdict == BbWindTwigs::Verdict::Tree) {\n"
                "                ++census.small;\n"
                "                census.Tall(height);\n"
                "            } else if (entry->verdict == BbWindTwigs::Verdict::Waiting) {\n"
                "                ++census.small_wait;\n"
                "            }\n"
                "        } else if (entry != nullptr && entry->verdict == BbWindTwigs::Verdict::Tree) {\n"
                "            ++census.sun;\n"
                "            census.Tall(height);\n"
                "        } else if (rt_shadow->LonePlant(stream, size)) {\n")
E_PRINT_OLD = ("    BbReport::Printf(\"%s\\n\", text);\n"
               "    twig_stats = {};\n")
E_PRINT_NEW = ("    BbReport::Printf(\"%s\\n\", text);\n"
               "    if (BbWindTwigs::ReachSmall()) { // bbport (r89e_twigs-big-trees): the candidates' line\n"
               "        char small_text[320];\n"
               "        BbWindTwigs::SmallReportText(census, twig_stats, BbWindTwigs::KnobOnce(), small_text,\n"
               "                                     sizeof(small_text));\n"
               "        BbReport::Printf(\"%s\\n\", small_text);\n"
               "    }\n"
               "    twig_stats = {};\n")
E_ONCE_OLD = "        BbReport::Printf(\"%s\\n\", twigs);\n"
E_ONCE_NEW = ("        BbReport::Printf(\"%s\\n\", twigs);\n"
              "        if (BbWindTwigs::ReachSmall()) { // bbport (r89e_twigs-big-trees)\n"
              "            char small_once[320];\n"
              "            BbWindTwigs::SmallOnceText(BbWindTwigs::KnobOnce(), small_once, sizeof(small_once));\n"
              "            BbReport::Printf(\"%s\\n\", small_once);\n"
              "        }\n")

# ---------------------------------------------------------------- vk_rasterizer.h / .cpp
RH_SWAY_OLD = "    u32 WindSwayWord(const GraphicsPipeline* pipeline);\n"
RH_SWAY_NEW = ("    /// bbport (r89e_twigs-big-trees): small_palette 0 or 1 for a static cut-out candidate of the twigs\n"
               "    /// (1: it read a small bone palette), -1 for a skinned draw\n"
               "    u32 WindSwayWord(const GraphicsPipeline* pipeline, int small_palette = -1);\n")
RH_TREE_OLD = "    bool WindTwigTree(u64 positions, u32 positions_size);\n"
RH_TREE_NEW = (RH_TREE_OLD +
               "    /// bbport (r89e_twigs-big-trees): static cut-out candidates (BB_WIND_TWIGS_SMALL)\n"
               "    bool WindTwigSmall(const GraphicsPipeline* pipeline, u64 positions, u32 positions_size,\n"
               "                       u32 stride, bool floats, bool palette);\n"
               "    void WindTwigSmallVerdict(BbWindTwigs::Entry& entry, u64 positions);\n")
RH_WORD_OLD = "                     u64 positions, u32 positions_size, u64 frame, double time);\n"
RH_WORD_NEW = "                     u64 positions, u32 positions_size, u64 frame, double time, bool small = false);\n"
RC_OLD = ("                ? WindSwayWord(pipeline)\n"
          "                // bbport (r89d_tree-twigs): 0, counting (twigs on) the draws the sway cannot reach\n")
RC_NEW = ("                ? WindSwayWord(pipeline)\n"
          "                // bbport (r89e_twigs-big-trees): a static cut-out (Kind::Other) is a candidate for the\n"
          "                // twigs (BB_WIND_TWIGS_SMALL); the palette flag says it read a small bone palette\n"
          "                : (r34_kind == Motion::Kind::Other && BbWindTwigs::ReachSmall() &&\n"
          "                   (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::Sway) != 0)\n"
          "                    ? WindSwayWord(pipeline, palette != 0 ? 1 : 0)\n"
          "                // bbport (r89d_tree-twigs): 0, counting (twigs on) the draws the sway cannot reach\n")

# ---------------------------------------------------------------- tests
T_ANCHOR = "    // The slots in use.\n"
T_BLOCK = r'''    // bbport (r89e_twigs-big-trees): the static cut-out rule, the far share, the slot release, the knob.
    {
        namespace T = BbWindTwigs;
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
        const auto is = [](const char* got, const char* want) {
            return got != nullptr && std::strcmp(got, want) == 0;
        };
        Expect(T::SmallWhy(meas(0, 10, 0, 6, 0, 6), 0.0f, 1, false) == nullptr,
               "a still bare tree 10 m tall, 6 x 6 m, one draw a frame: a tree");
        Expect(T::SmallWhy(meas(0, 25, 0, 14, 0, 12), 0.1f, 2, false) == nullptr,
               "a 25 m tree with two draws a frame: a tree");
        Expect(is(T::SmallWhy(meas(0, 10, 0, 6, 0, 6), 0.5f, 1, false), "moved"), "a box that moved: no");
        Expect(is(T::SmallWhy(meas(0, 3, 0, 3, 0, 3), 0.0f, 1, false), "short"), "a 3 m fence post: short");
        Expect(is(T::SmallWhy(meas(0, 171.4f, 0, 60, 0, 60), 0.0f, 1, false), "tall"), "171 m: tall");
        Expect(is(T::SmallWhy(meas(0, 12, 0, 40, 0, 0.5f), 0.0f, 1, false), "wide"), "a long wall 12 m: wide");
        Expect(is(T::SmallWhy(meas(0, 6, 0, 5, 0, 0.4f), 0.0f, 1, false), "thin"), "a flat panel: thin");
        Expect(is(T::SmallWhy(meas(0, 12, 0, 1, 0, 1), 0.0f, 1, false), "slim"), "a lamp post: slim");
        Expect(is(T::SmallWhy(meas(0, 10, 0, 6, 0, 6), 0.0f, 3, false), "instanced"), "3 draws a frame: instanced");
        Expect(is(T::SmallWhy(meas(0, 10, 0, 100, 0, 6), 0.0f, 1, false), "box"), "a box over 80 m: box");
        Expect(T::SmallWhy(meas(0, 6, 0, 5, 0, 0.4f), 0.0f, 3, true) == nullptr &&
                   is(T::SmallWhy(meas(0, 3, 0, 5, 0, 5), 0.0f, 1, true), "short") &&
                   is(T::SmallWhy(meas(0, 60, 0, 5, 0, 5), 0.0f, 1, true), "tall") &&
                   is(T::SmallWhy(meas(0, 6, 0, 5, 0, 5), 0.9f, 1, true), "moved"),
               "the loose rule keeps the height and the still checks only");
        Expect(is(T::SmallPrefilter(60), "verts-few") && T::SmallPrefilter(120) == nullptr &&
                   is(T::SmallPrefilter(300000), "verts-many"),
               "SmallPrefilter");
        // the Book: Judge uses SmallWhy for a small entry; a refusal has no slot
        {
            std::vector<std::uint32_t> words(T::TwigEnd, 0u);
            words[BaseAt + 9] = HeightKey(0.5f);
            words[CrownAt + 9] = CrownKey(10.5f);
            words[T::TwigAt + 9 * 4 + 0] = HeightKey(20.0f);
            words[T::TwigAt + 9 * 4 + 1] = CrownKey(26.0f);
            words[T::TwigAt + 9 * 4 + 2] = HeightKey(40.0f);
            words[T::TwigAt + 9 * 4 + 3] = CrownKey(46.0f);
            T::Book book;
            T::Entry& e = book.Touch(0xb000, 4096, 9, true, 100);
            e.small = true;
            Expect(book.LiveSmall(100) == 1u, "LiveSmall counts the measured candidate");
            (void)T::Judge(e, words.data(), 108);
            Expect(T::Judge(e, words.data(), 168) == T::Verdict::Tree && e.why == nullptr && e.last.ok,
                   "a small candidate: still, 10 m, 6 x 6: a tree");
            T::Entry& r = book.Refuse(0xb100, 2048, 100, "verts-few");
            Expect(r.small && r.verdict == T::Verdict::NotTree && r.slot == 0xffffffffu &&
                       book.Find(0xb100) != nullptr,
                   "Refuse: an entry with no slot");
            T::SmallInfo info;
            info.verts = 5000;
            (void)book.SetInfo(0xb000, info);
            Expect(book.FindInfo(0xb000) != nullptr && book.FindInfo(0xb000)->verts == 5000 &&
                       book.FindInfo(0xdead) == nullptr,
                   "SetInfo and FindInfo");
        }
        // the far share: a trunk with a ring of limbs far from the axis (local y up)
        {
            std::vector<float> trunk;
            for (int i = 0; i < 300; ++i) { // near the axis, spread in height
                trunk.insert(trunk.end(), {0.05f * float(i % 3), float(i) * 0.03f, 0.05f * float(i % 2), 0.0f});
            }
            for (int i = 0; i < 100; ++i) { // limbs: 2 m out at the top
                const float a = float(i) * 0.0628f;
                trunk.insert(trunk.end(), {2.0f * std::cos(a), 8.0f + 0.01f * float(i), 2.0f * std::sin(a), 0.0f});
            }
            const float share = T::FarShare(reinterpret_cast<const unsigned char*>(trunk.data()), 16, 400);
            Expect(share > 0.2f && share < 0.3f, "FarShare: 100 of 400 vertices far from the axis");
            Expect(T::FarShare(nullptr, 16, 400) == -1.0f && T::FarShare(reinterpret_cast<const unsigned char*>(trunk.data()), 8, 400) == -1.0f &&
                       T::FarShare(reinterpret_cast<const unsigned char*>(trunk.data()), 16, 4) == -1.0f,
                   "FarShare: unreadable input gives -1");
        }
        // the knob: BB_WIND_TWIGS_SMALL 0 off, 1 the default, 2 log only, 3 loose
        Expect(T::ParseKnob(nullptr, nullptr, true, true).small == 1 &&
                   T::ParseKnob(nullptr, nullptr, true, true, "0").small == 0 &&
                   T::ParseKnob(nullptr, nullptr, true, true, "2").small == 2 &&
                   T::ParseKnob(nullptr, nullptr, true, true, "3").small == 3 &&
                   T::ParseKnob(nullptr, nullptr, true, true, "x").small == 1,
               "BB_WIND_TWIGS_SMALL: 0-3, unreadable 1");
        // the slot release: the slot rests (frames in flight still write its keys), the stream is gone
        {
            Slots slots;
            const auto a = slots.Take(0x1000, 64, 10, 0.0);
            slots.Release(0x1000);
            const auto b = slots.Take(0x2000, 64, 10, 0.0);
            const auto again = slots.Take(0x1000, 64, 11, 0.0);
            Expect(a.ok && b.ok && b.slot != a.slot && b.reset && again.ok && again.reset &&
                       again.slot != a.slot,
                   "Release: the slot rests, the stream is taken anew elsewhere");
            slots.Release(0x9999); // a stream with no slot: nothing
        }
        char line[400];
        T::Entry shown;
        shown.small = true;
        shown.verdict = T::Verdict::NotTree;
        shown.why = "wide";
        shown.last = meas(0, 12, 0, 40, 0, 0.5f);
        T::SmallInfo shown_info;
        shown_info.verts = 5400;
        shown_info.far_share = 0.62f;
        shown_info.palette = true;
        shown_info.draws = 120;
        shown_info.max_per_frame = 2;
        T::SmallLine(shown, &shown_info, line, sizeof(line));
        Expect(std::strstr(line, "candidate refused: height 12.0 m, box 40.0 x 0.5 m") != nullptr &&
                   std::strstr(line, "verts 5400, far 0.62, palette 1") != nullptr &&
                   std::strstr(line, "per frame 2, why wide") != nullptr && std::strlen(line) < 300,
               "SmallLine");
        T::Census census;
        census.small = 3;
        census.Huge(171.4f);
        T::Stats stats;
        stats.small_seen = 700;
        T::SmallReportText(census, stats, T::ParseKnob(nullptr, nullptr, true, true), line, sizeof(line));
        Expect(std::strstr(line, "meshes 3 tree, 0 judging; draws 700 seen") != nullptr &&
                   std::strstr(line, "over 40 m: 1 meshes (tallest 171.4 m)") != nullptr && std::strlen(line) < 320,
               "SmallReportText");
        T::SmallOnceText(T::ParseKnob(nullptr, nullptr, true, true), line, sizeof(line));
        Expect(std::strstr(line, "BB_WIND_TWIGS_SMALL=1") != nullptr && std::strlen(line) < 320, "SmallOnceText");
    }

''' + T_ANCHOR

# ---------------------------------------------------------------- README
README_SMALL_OLD = ("trees drawn with a small skeleton (2 to 39 bones) or with a palette are not reached (the line counts "
                    "them as `small-skeleton`)")
README_SMALL_NEW = ("static cut-out trees (no skinned palette, with or without a small skeleton) are reached by the rule of "
                    "`BB_WIND_TWIGS_SMALL`; a draw with a GPU-written palette is not (the line counts the draws left out as "
                    "`small-skeleton`); a mesh over 40 m is never a tree")
README_ROW_ANCHOR = "The log line's `opaque` count says how many skinned draws `2` would add | `1` |\n"
README_ROW_NEW = (README_ROW_ANCHOR +
                  "| `BB_WIND_TWIGS_SMALL` | Which static cut-out meshes (a cut-out pixel shader, no skinned or GPU-written "
                  "palette: the big bare trees) the twigs may take (`BB_WIND_TWIGS` row): `0` none (as without this row), `1` "
                  "(default) those whose world box, measured by the GPU over 68 frames, is still (at most 0.3 m move), from 4 "
                  "to 40 m tall, whose larger horizontal width is 0.2 to 1.8 of the height and whose smaller is at least 0.30 "
                  "of the larger (not a wall, a fence or a pole), with at least 120 vertices and at most 2 draws a frame (a "
                  "stream drawn at many places has a box that spans them: refused as `instanced`); `2` measures and logs, "
                  "takes none; `3` keeps only the height, still and vertex checks. At most 96 streams are measured at once; a "
                  "stream judged not a tree gives its slot back and costs a map lookup per draw; a tree stirs as the `"
                  "BB_WIND_TWIGS` row says. Log: once `Wind twigs (r89e, BB_WIND_TWIGS_SMALL=...)`, a line per judged "
                  "candidate (`Wind twigs (r89e) candidate TREE|refused: height, box, verts, far, palette, vs, ps, why`, at most "
                  "64, and 24 for the cheap check's refusals) and every 600 frames the counts. Any other text is 1. No GPU "
                  "memory, no shader change; not measured | `1` |\n")

EDITS = {
    NEWH: [
        (N_CONST_OLD, N_CONST_NEW),
        (N_KNOB_OLD, N_KNOB_NEW),
        (N_PARSE_OLD, N_PARSE_NEW),
        (N_ONCE_OLD, N_ONCE_NEW),
        (N_REACH_OLD, N_REACH_NEW),
        (N_ENTRY_OLD, N_ENTRY_NEW),
        (N_VERDICT_OLD, N_VERDICT_NEW),
        (N_BOOK_OLD, N_BOOK_NEW),
        (N_PRIV_OLD, N_PRIV_NEW),
        (N_GIVEUP_OLD, N_GIVEUP_NEW),
        (N_JUDGE_OLD, N_JUDGE_NEW),
        (N_STATS_OLD, N_STATS_NEW),
        (N_CENSUS_OLD, N_CENSUS_NEW),
        (N_END_OLD, N_END_NEW),
    ],
    HEADER: [(H_REL_OLD, H_REL_NEW), (H_TAKE_OLD, H_TAKE_NEW), (H_SLOT_OLD, H_SLOT_NEW)],
    EFFECTS: [
        (E_SIG_OLD, E_SIG_NEW),
        (E_FETCH_OLD, E_FETCH_NEW),
        (E_TREE_OLD, E_TREE_NEW),
        (E_WORD_OLD, E_WORD_NEW),
        (E_TWORD_OLD, E_TWORD_NEW),
        (E_SKIP_ANCHOR, E_SMALL + E_SKIP_ANCHOR),
        (E_REPORT_OLD, E_REPORT_NEW),
        (E_PRINT_OLD, E_PRINT_NEW),
        (E_ONCE_OLD, E_ONCE_NEW),
    ],
    RASH: [(RH_SWAY_OLD, RH_SWAY_NEW), (RH_TREE_OLD, RH_TREE_NEW), (RH_WORD_OLD, RH_WORD_NEW)],
    RASC: [(RC_OLD, RC_NEW)],
    TEST: [(T_ANCHOR, T_BLOCK)],
    README: [(README_SMALL_OLD, README_SMALL_NEW), (README_ROW_ANCHOR, README_ROW_NEW)],
}

CHECKS = {
    NEWH: [("inline const char* SmallWhy(", 1), ("inline float FarShare(", 1), ("inline bool ReachSmall()", 1),
           ("TreeMax = 40.0f", 1), ("TreeMax = 60.0f", 0), ("if (e.small) {", 1), ("std::getenv(\"BB_WIND_TWIGS_SMALL\")", 1)],
    HEADER: [("void Release(std::uint64_t stream)", 1)],
    EFFECTS: [("bool Rasterizer::WindTwigSmall(", 1), ("void Rasterizer::WindTwigSmallVerdict(", 1),
              ("WindTwigSmall(pipeline, positions,", 1), ("sway_slots.Release(positions)", 1),
              ("BbWindTwigs::SmallReportText(", 1), ("BbWindTwigs::SmallOnceText(", 1), ("positions_stride = stream.GetStride();", 1)],
    RASH: [("bool WindTwigSmall(", 1), ("void WindTwigSmallVerdict(", 1), ("int small_palette = -1", 1), ("bool small = false", 1)],
    RASC: [("WindSwayWord(pipeline, palette != 0 ? 1 : 0)", 1), ("? WindSwayWord(pipeline)", 1), ("WindTwigSkip(", 1)],
    TEST: [("T::SmallWhy(", 14), ("wind-sway-test: ok", 1)],
    README: [("| `BB_WIND_TWIGS_SMALL` |", 1), ("| `BB_WIND_TWIGS_REACH` |", 1)],
}

ORDER = {
    NEWH: ["inline constexpr float TreeMin", "inline constexpr float SmallMinH", "int small = 1;", "inline bool ReachSmall()",
           "inline const char* SmallWhy(", "struct SmallInfo {", "const char* why = nullptr;", "class Book {",
           "SmallInfo* FindInfo(", "std::unordered_map<std::uint64_t, SmallInfo> infos;", "if (e.small) {",
           "std::uint32_t small = 0, small_wait = 0, huge = 0;", "inline float FarShare(", "inline void SmallLine(",
           "inline void SmallOnceText(", "inline void SmallReportText(", "} // namespace BbWindTwigs"],
    EFFECTS: ["u32 Rasterizer::WindSwayWord(", "positions_stride = stream.GetStride();", "small_palette < 0 && rt_shadow->LonePlant",
              "snapshot.time, small_palette >= 0", "u32 Rasterizer::WindTwigWord(", "bool Rasterizer::WindTwigSmall(",
              "void Rasterizer::WindTwigSmallVerdict(", "u32 Rasterizer::WindTwigSkip(", "void Rasterizer::WindTwigsReport()",
              "SmallReportText(", "SmallOnceText("],
}

# Numbers written twice: the header's constants and the README row's text.
TIES = [(NEWH, "SmallMinH = 4.0f, SmallMaxH = TreeMax", "from 4 to 40 m tall"),
        (NEWH, "TreeMax = 40.0f", "over 40 m is never a tree"),
        (NEWH, "SmallAspectLo = 0.20f, SmallAspectHi = 1.8f, SmallThin = 0.30f", "0.2 to 1.8 of the height"),
        (NEWH, "SmallThin = 0.30f", "at least 0.30"),
        (NEWH, "SmallMinVerts = 120", "at least 120 vertices"),
        (NEWH, "SmallInstMax = 2", "at most 2 draws a frame"),
        (NEWH, "SmallLiveMax = 96", "At most 96 streams"),
        (NEWH, "SmallLogJudged = 64, SmallLogRefused = 24", "at most 64, and 24"),
        (NEWH, "JudgeFrames = 8, StillFrames = 60", "over 68 frames")]


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
    rows = "\n".join(l for l in texts[README].split("\n") if l.startswith("| `BB_WIND_TWIGS"))
    for path, const, value in TIES:
        if texts[path].count(const) != 1 or value not in rows:
            raise SystemExit("tie check: %r against the README rows (%r)" % (const, value))
    for edits in EDITS.values():
        for old, new in edits:
            if not all(ord(c) < 128 for c in new) or "\r" in new:
                raise SystemExit("new text must be ASCII with LF in the script")
            if any(x in new for x in ("C:/", "G:/", "<user>", "Temp/claude")):
                raise SystemExit("a local path in the patch's text")
    # a macro-named identifier (far, near) must not appear as a variable in the new C++ text
    for path in (NEWH, EFFECTS):
        for bad in ("float far ", "float far;", " far =", " far;", ".far,", ".far)", " near =", "float near"):
            if bad in "".join(new for _, new in EDITS[path]):
                raise SystemExit("%s: the name %r is a macro on some Windows headers" % (path, bad))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R89E_ROOT)" % ROOT)
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
            tmp = full + ".r89etmp"
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
        tmp = full + ".r89etmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
