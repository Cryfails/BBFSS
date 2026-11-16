# r112s_hang-bracket-move (FEATURE, behind BB_WIND_HANG=1; sub-knob BB_WIND_HANG_POST, default on inside BB_WIND_HANG, 0 = r112r): the bracket
# lanterns' POSTS get a hang word and lean. On top of r112r_hang-bracket-judge and everything through build 66.
#
# THE FIRST BROKEN LINK (read from b66_s4.log, b66_s5.log, the pictures and the code; nothing was run)
#  - The visible lantern is not drawn by a stream a hang rule can take. The glass pick at 1677,990 (1920x1080) = 1118,660 of the 1280x720 picture
#    (the lantern's cage) lists ONE G-buffer draw: vs:ps 9da6aacb:bb10e440, GPU palette, 25296 indices (first 0), position stream of 13642 vertices
#    stride 32, mesh key 4e981431bac0b245, scene box 1.1 x 5.7 x 2.2 m, 10796 vertices. The left lantern (503,983) is the SAME stream (13642 vertices,
#    25296 indices from 0) drawn x3 as vs:ps 6a833138:bb10e440. A 5.7 m tall, 2.2 m wide mesh of 10796 vertices: a lamp POST with the lantern on its
#    bracket (in proof_a the pole rises above the lantern by ~4 lantern heights and goes on under the picture's edge). The route lines list it as
#    '0x114ef28c50 scene 5.66 m tall 2.15 m wide 10796 verts, judge none dev 0 mm, book none (why 0, box 0)': never judged, never a candidate. The
#    twig rules (r89e/r89j) call it a TREE ('candidate TREE: height 5.7 m, box 1.1 x 2.2 m, verts 13642, vs 9da6aacb ps bb10e440') and it gets a TREE
#    word, whose weight is a rule of the vertex's height over the CAMERA (3 to 9 m): the lantern is 3-4 m over the hunter's head, so about 0.
#  - r112i's static candidates are 0.15-2.0 m tall and r112's skinned ones at most 4 m: a 5.7 m post can never be a hang candidate, and the hang
#    rule (top 0.3 m still, full from 1.2 m below the top) would push the foot of a post, not its lantern, if it were.
#  - The 1398 words the pick's line counts for 9da6aacb:bb10e440 (frames 466-1165) are other streams of the pair (the cut-outs E and F of r112i's
#    survey, 8.8 m up a tree 57 m away); 7620368b:8aba0ecd is a tree (box 12 x 26 m), no hang word, not the lantern. e859b6d9 is not it either.
#  - So the answers to the three questions: (1) the delivered word IS read by that shader variant (the hunter's, the trees' and E/F's words reach the
#    lifted shader: tinted in b66_s5, hidden with PROOF_HIDE), (2) the GPU-palette path's offset is applied to the CLIP position after the skinning
#    (moved = position + ForwardAt . d), so no bone space cancels it, (3) yes: the pushed 1398 of 220000 draws are other streams, the visible lantern
#    is never one of them. hide_a (every draw with a hang word hidden) leaves the lantern in the picture: it has NO hang word.
#
# THE FIX (FEATURE, BB_WIND_HANG_POST)
#  - A draw whose position stream holds 13642 vertices (size / stride; BB_WIND_HANG_POST=<n>[:<n>...] names others, at most 8; unset or 1 = 13642; 0
#    = off) is a post lantern's: WindSwayWord gives it, in place of plant / tree / hang rules, a hang word with PostBit (bit 15): ramp 0 while the
#    GPU fills the slot's keys (r112's Measure, JudgeFrames), then the ramp that Measure gives times BB_WIND_HANG_STATIC_GAIN (live; default 0.2) and
#    the live BB_WIND_HANG_PUSH switch. Its keys' span (the union of the places the stream is drawn at) must be 0.15-10 m, else it gets no word.
#  - Both emitters (the lifter's and the recompiler's EmitVertexSway) replace the hanging thing's weight for a word with PostBit: t = clamp((0.65 -
#    depth below the slot's top key / keys' height) / 0.45, 0, 1): 1 within the top 20 percent of the mesh, 0 from 65 percent down (BbWindHang::PostT,
#    the C++ twin), then the same smoothstep x ramp x scale and the same push table, direction and clip-space move as every hanging thing: the upper
#    part of the post moves as one piece downwind, its foot stays. With gain 0.2 and BB_WIND_SWAY 3 at 4 m/s the top moves up to about 9 cm in a
#    full gust (the lantern, 1.5-2 m under the top, 0.7-0.9 of it: 3-8 cm), at 1.5 m/s about 1 cm.
#  - The proof: a post word has HangBit, so the unconditional tint of r112r (lifter and recompiler) tints the post cyan, and PROOF_HIDE hides it.
#  - The shaders differ only with BB_WIND_HANG=1 and POST on (the emitters read PostOn() once, as they read hang_on): the shader binary version gets
#    +50000 (PostBinaryAdd, serialization SwayOr), StripProofVersion strips it for the load tests; with BB_WIND_HANG unset nothing is emitted
#    and the SPIR-V of every shader is byte-identical to build 66 (by construction: every new line sits in `if (hang_on)` / `PostOn()`).
#
# SHARED LINES TOUCHED
#  vk_rasterizer.h: one declaration after WindHangProofDraw, one member after hang_proof_hide (both r112r's lines).
#  vk_rasterizer_effects.cpp: WindSwayWord: `post` before the trees' early return, `!post` in six conditions, one return line before the trees' proof
#   note; a new member function before WindTwigTree; one once-line block before r112e's once line; one periodic line before r112b's probe report.
#  lift_stage.cpp, emit_spirv_special.cpp: the `ht` line(s) of the hang block (one line / four lines replaced).
#  vk_pipeline_serialization.cpp: one line in SwayOr.
#  bbport_wind_hang.h: constants, knob, PostT, PostWord, PostBook, texts. tests/test_wind_hang.cpp: one block. README.md: one row.
#
# COST WHEN OFF: BB_WIND_HANG unset: PostOn() is a static bool (false); WindSwayWord reads it once a call; nothing in a shader. BB_WIND_HANG=1 with
# BB_WIND_HANG_POST=0: as r112r (shaders recompiled once under the old version; same SPIR-V as r112r). ON: 8 ALU ops (and, compare, max, divide,
# sub, mul, clamp, select) per vertex of every sway shader built with hang (not only the post's); CPU: a division and a compare of ints per sway draw
# call; Measure and a table fill per post draw (the fill once per view and frame, as every hang draw). Memory: PostBook at most 64 items of 96 bytes.
#
# Use: python -I -X utf8 r112s_hang-bracket-move.py check | apply | revert
# Root: R112S_ROOT, else <tree>. Line ends kept. apply backs the originals up in r112s_backup next to this script; revert takes out exactly what
# apply put in. Needs r112r (and everything before it) applied.
import os, re, sys

ROOT = os.environ.get("R112S_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112s_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RH = RV + "vk_rasterizer.h"
EF = RV + "vk_rasterizer_effects.cpp"
SE = RV + "vk_pipeline_serialization.cpp"
SH = "engine/gpu/shim/"
HH = SH + "bbport_wind_hang.h"
LS = SH + "lifter/lift_stage.cpp"
ES = "engine/gpu/shadps4/shader_recompiler/backend/spirv/emit_spirv_special.cpp"
TH = "engine/tests/test_wind_hang.cpp"
RM = "README.md"

# ---- bbport_wind_hang.h ---------------------------------------------------------------------------------
# block 1: before StripProofVersion's comment (after ProofBinaryOffset): constants, knob, PostT; block 2: PostWord after HangOf; block 3: the book
H1A = r'''/// A saved version with the proof's add taken out (only while the proof is on and the version carries it).'''
H1AP = r'''// bbport (r112s_hang-bracket-move): the bracket lanterns' POSTS. b66 named the lantern's draw: a position stream of 13642 vertices (a mesh of
// 10796 vertices, 5.7 m tall, 2.2 m wide: a lamp post with the lantern on its bracket), a TREE of the twigs (a tree word, weighed by the
// vertex's height over the camera) and never a hang candidate (r112i: 0.15-2.0 m tall). BB_WIND_HANG_POST (read once; with BB_WIND_HANG=1:
// unset or `1` = on for streams of 13642 vertices, `0` = off, else the vertex counts of the posts' position streams separated by `:`, at most 8)
// gives such a stream a hang word with PostBit: its slot's keys fill (ramp 0), then it leans downwind like a hanging thing, but the shaders weigh
// the vertex by its depth below the slot's top key over the keys' height (PostT), not by its depth below the top alone: 1 in the top 20 percent
// of the mesh, 0 from 65 percent down, so the upper part of the post moves as one piece and its foot stays.
inline constexpr std::uint32_t PostBit = 1u << 15; ///< the sway word's bit for a post (free: PackWord ends at bit 12 and restarts at 16)
inline constexpr float PostBelow = 0.65f;          ///< depth below the top (share of the keys' height) where the weight is 0
inline constexpr float PostSpan = 0.45f;           ///< the weight is 1 at PostBelow - PostSpan (0.20) and above
inline constexpr float PostExtMin = 2.0f;          ///< m: the height the shaders divide by is at least this (a base key not filled yet)
inline constexpr float PostMaxExtent = 10.0f;      ///< m: the keys' span (the union of the places) above which a post gets no word
inline constexpr std::uint32_t PostBinaryAdd = 50000; ///< added to the sway shader binary version with the post rule (above every other sum, under the proof's)
inline constexpr std::uint32_t PostDefaultVerts = 13642;
inline constexpr std::size_t PostStreamsMost = 8;  ///< vertex counts BB_WIND_HANG_POST may name
inline constexpr std::size_t PostKept = 64;        ///< streams the book keeps at most

static_assert((W::PackWord(3, 1, 1023, 255) & PostBit) == 0 && (PostBit & W::WordOn) == 0 && PostBit != HangBit,
              "PostBit lies outside PackWord's fields and is not HangBit");
static_assert(PostBelow < 1.0f && PostBelow > PostSpan && PostSpan > 0.0f && PostExtMin > 0.0f && PostMaxExtent > MinExtent);
static_assert(PostBinaryAdd > 20000u && PostBinaryAdd < ProofBinaryAdd, "above every sway offset sum (about 15600), under the proof's add");

/// BB_WIND_HANG_POST parsed: `on` (not exactly `0`), the vertex counts of the posts' position streams (a list of numbers separated by anything
/// that is no digit; none, or exactly `1`: PostDefaultVerts).
struct PostKnob {
    bool on = false;
    std::array<std::uint32_t, PostStreamsMost> verts{};
    std::size_t count = 0;
};

[[nodiscard]] inline PostKnob ParsePost(const char* text) {
    PostKnob k;
    k.on = true;
    if (text != nullptr && text[0] == '0' && text[1] == 0) {
        k.on = false;
        return k;
    }
    if (text != nullptr && !(text[0] == '1' && text[1] == 0)) {
        std::uint64_t value = 0;
        bool digits = false;
        for (const char* p = text;; ++p) {
            if (*p >= '0' && *p <= '9') {
                value = std::min<std::uint64_t>(value * 10u + static_cast<std::uint64_t>(*p - '0'), 100000000u);
                digits = true;
                continue;
            }
            if (digits && value > 0 && k.count < PostStreamsMost) {
                k.verts[k.count++] = static_cast<std::uint32_t>(value);
            }
            value = 0;
            digits = false;
            if (*p == 0) {
                break;
            }
        }
    }
    if (k.count == 0) {
        k.verts[0] = PostDefaultVerts;
        k.count = 1;
    }
    return k;
}

/// Read once with the hang knob (it is on only with BB_WIND_HANG on): the emitters and the draws ask it.
[[nodiscard]] inline const PostKnob& PostOnce() {
    static const PostKnob knob = [] {
        PostKnob k = ParsePost(std::getenv("BB_WIND_HANG_POST"));
        k.on = k.on && KnobOnce().on;
        return k;
    }();
    return knob;
}

[[nodiscard]] inline bool PostOn() {
    return PostOnce().on;
}

/// Added to the sway shader binary version: 0 off (the shaders are as before), PostBinaryAdd with the post rule in them.
[[nodiscard]] inline std::uint32_t PostBinaryOffset() {
    return PostOn() ? PostBinaryAdd : 0u;
}

/// Is a position stream of `size` bytes and `stride` bytes a vertex a post's (its vertex count one the knob names)?
[[nodiscard]] inline bool PostMatchesIn(const PostKnob& knob, std::uint32_t size, std::uint32_t stride) {
    if (!knob.on || stride == 0) {
        return false;
    }
    const std::uint32_t verts = size / stride;
    for (std::size_t i = 0; i < knob.count; ++i) {
        if (knob.verts[i] == verts) {
            return true;
        }
    }
    return false;
}

[[nodiscard]] inline bool PostMatches(std::uint32_t size, std::uint32_t stride) {
    return PostMatchesIn(PostOnce(), size, stride);
}

/// The shaders' weight of a post's vertex before the smoothstep: `below_top` m under the slot's top key, `height` the keys' height (at least
/// PostExtMin; a number that is none gives PostExtMin): 1 within the top 20 percent, 0 from 65 percent down.
[[nodiscard]] inline float PostT(float below_top, float height) {
    const float e = height > PostExtMin ? height : PostExtMin;
    return std::clamp((PostBelow - below_top / e) * (1.0f / PostSpan), 0.0f, 1.0f);
}

'''
H2A = r'''/// The push's amplitude (m) at gust 1: BB_WIND_SWAY `scale` x PushFull x (speed / FullSpeed)^2;'''
H2AP = r'''/// bbport (r112s_hang-bracket-move): a post's sway word: a hanging thing's word with PostBit.
[[nodiscard]] constexpr std::uint32_t PostWord(std::uint32_t frame_slot, std::uint32_t view, std::uint32_t slot, std::uint32_t ramp) {
    return W::PackWord(frame_slot, view, slot, ramp) | HangBit | PostBit;
}

[[nodiscard]] constexpr bool PostOf(std::uint32_t word) {
    return (word & W::WordOn) != 0 && (word & HangBit) != 0 && (word & PostBit) != 0;
}

'''
H3A = r'''} // namespace BbWindHang'''
H3AP = r'''// ---- bbport (r112s_hang-bracket-move): the posts' book and lines ------------------------------------------------------------------------

/// The posts' streams (by position address) with what Measure keeps of their slots' keys, and the counts of the log line.
class PostBook {
public:
    struct Item {
        Entry entry;
        std::uint32_t size = 0;
        std::uint64_t seen = 0;
    };

    std::uint64_t draws = 0;     ///< post draws given a word or none
    std::uint64_t measuring = 0; ///< of them, a word with ramp 0 while the keys fill
    std::uint64_t pushed = 0;    ///< a word that moves it
    std::uint64_t unfit = 0;     ///< no word: the keys' span was out of 0.15 m to PostMaxExtent

    /// The stream's item (made at the first draw); another size at a known address is another mesh: what was known is forgotten.
    Item& Touch(std::uint64_t stream, std::uint32_t size, std::uint64_t frame) {
        if (items.size() >= PostKept && items.find(stream) == items.end()) {
            items.clear();
        }
        Item& item = items[stream];
        if (item.size != 0 && size != 0 && item.size != size) {
            item = Item{};
        }
        item.size = size;
        item.seen = frame;
        return item;
    }

    [[nodiscard]] const std::unordered_map<std::uint64_t, Item>& Items() const {
        return items;
    }

private:
    std::unordered_map<std::uint64_t, Item> items;
};

/// The periodic line (every ReportFrames frames, with r112's): `push` the push at the camera of the last table fill.
inline void PostLineText(const PostBook& book, float push, char* out, std::size_t size) {
    unsigned streams = 0, judged = 0, swing = 0;
    float base = 0.0f, top = 0.0f;
    for (const auto& item : book.Items()) {
        const Entry& e = item.second.entry;
        ++streams;
        if (e.judged) {
            ++judged;
            if (e.fits) {
                if (swing == 0) {
                    base = e.base;
                    top = e.top;
                }
                ++swing;
            }
        }
    }
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(out, size,
                  "Wind sway hang post (r112s, BB_WIND_HANG_POST): since the start %llu draws of %u streams: %llu measuring, %llu pushed, %llu with no word "
                  "(keys span over %.0f m or under %.2f m); %u judged, %u swinging (the first: base y %.2f, top y %.2f, %.2f m tall); push %.3f m",
                  n(book.draws), streams, n(book.measuring), n(book.pushed), n(book.unfit), double(PostMaxExtent), double(MinExtent), judged,
                  swing, double(base), double(top), double(top - base), double(push));
}

/// The once line (BB_WIND_HANG=1 and the post rule on).
inline void PostOnceText(char* out, std::size_t size) {
    char list[96] = {};
    std::size_t at = 0;
    const PostKnob& knob = PostOnce();
    for (std::size_t i = 0; i < knob.count && at + 16 < sizeof(list); ++i) {
        const unsigned verts = static_cast<unsigned>(knob.verts[i]);
        const int w = i == 0 ? std::snprintf(list + at, sizeof(list) - at, "%u", verts)
                             : std::snprintf(list + at, sizeof(list) - at, " or %u", verts);
        at += w > 0 ? static_cast<std::size_t>(w) : std::size_t{0};
    }
    std::snprintf(out, size,
                  "Wind sway hang post (r112s, BB_WIND_HANG_POST): on: a draw whose position stream holds %s vertices (the bracket lanterns' posts) "
                  "has its own hang word: the part of the post within the top %.0f percent of its height leans downwind in full, nothing moves "
                  "from %.0f percent down (as one piece: the lantern on its bracket leans, the foot stays); push as a hanging thing's, times "
                  "BB_WIND_HANG_STATIC_GAIN (live) and the live BB_WIND_HANG_PUSH; keys' span 0.15-%.0f m; its shaders have their own cache version "
                  "(+%u)",
                  list, 100.0 * double(PostBelow - PostSpan), 100.0 * double(PostBelow), double(PostMaxExtent),
                  static_cast<unsigned>(PostBinaryAdd));
}

} // namespace BbWindHang'''
H4A = r'''[[nodiscard]] inline std::uint32_t StripProofVersion(std::uint32_t version) {
    return ProofOn() && version >= ProofBinaryAdd ? version - ProofBinaryAdd : version;
}'''
H4N = r'''[[nodiscard]] inline std::uint32_t StripProofVersion(std::uint32_t version) {
    if (ProofOn() && version >= ProofBinaryAdd) {
        version -= ProofBinaryAdd;
    }
    // bbport (r112s_hang-bracket-move): and the post rule's add (50000, under the proof's 200000; every other sum is under 20000)
    return PostOn() && version >= PostBinaryAdd ? version - PostBinaryAdd : version;
}'''

# ---- lift_stage.cpp / emit_spirv_special.cpp ------------------------------------------------------------
L1 = r'''        const u32 ht = clamp_f(FMul(FSub(hh, FMul(sc, CF(H::HangStill))), Emit(O(spv::Op::OpFDiv), t_f32, Ty::F32, {CF(H::HangInv), sc})), zero, CF(1.0f));'''
L1N = r'''        u32 ht = clamp_f(FMul(FSub(hh, FMul(sc, CF(H::HangStill))), Emit(O(spv::Op::OpFDiv), t_f32, Ty::F32, {CF(H::HangInv), sc})), zero, CF(1.0f));
        if (H::PostOn()) { // bbport (r112s_hang-bracket-move): a post's word (PostBit): the weight is 1 in the top part of the mesh, 0 from 65 percent down (BbWindHang::PostT)
            const u32 post = ICmp(O(spv::Op::OpINotEqual), IOp(O(spv::Op::OpBitwiseAnd), word, CU(H::PostBit)), CU(0));
            const u32 post_height = Ext(GLSLstd450FMax, t_f32, Ty::F32, {ext, CF(H::PostExtMin)});
            const u32 post_below = Emit(O(spv::Op::OpFDiv), t_f32, Ty::F32, {hh, post_height});
            const u32 ht_post = clamp_f(FMul(FSub(CF(H::PostBelow), post_below), CF(1.0f / H::PostSpan)), zero, CF(1.0f));
            ht = Select(post, ht_post, ht);
        }'''
S1 = r'''        const Id ht = ctx.OpFClamp(
            f32_type,
            mul(sub(hh, mul(sc, f(H::HangStill))), ctx.OpFDiv(f32_type, f(H::HangInv), sc)), zero,
            f(1.0f));'''
S1N = r'''        Id ht = ctx.OpFClamp(
            f32_type,
            mul(sub(hh, mul(sc, f(H::HangStill))), ctx.OpFDiv(f32_type, f(H::HangInv), sc)), zero,
            f(1.0f));
        if (H::PostOn()) { // bbport (r112s_hang-bracket-move): a post's word (PostBit): the weight is 1 in the top part of the mesh, 0 from 65 percent down (BbWindHang::PostT)
            const Id post = ctx.OpINotEqual(bool_type, ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(H::PostBit)),
                                            ctx.u32_zero_value);
            const Id post_height = ctx.OpFMax(f32_type, ext, f(H::PostExtMin));
            const Id post_below = ctx.OpFDiv(f32_type, hh, post_height);
            const Id ht_post = ctx.OpFClamp(f32_type, mul(sub(f(H::PostBelow), post_below), f(1.0f / H::PostSpan)), zero,
                                            f(1.0f));
            ht = ctx.OpSelect(f32_type, post, ht_post, ht);
        }'''

# ---- vk_pipeline_serialization.cpp ----------------------------------------------------------------------
P1 = r'''BbWindHang::ProofBinaryOffset() // (r112q_hang-bracket-route: 100000 with BB_WIND_HANG_PROOF=1, its tint is in the SPIR-V)'''
P1P = r'''BbWindHang::PostBinaryOffset() + // (r112s_hang-bracket-move: 50000 with the post rule in the SPIR-V)
                     '''

# ---- vk_rasterizer.h ------------------------------------------------------------------------------------
V1 = r'''    bool WindHangProofDraw(const GraphicsPipeline* pipeline, char kind, u32 word, bool delivered); // bbport (r112r_hang-bracket-judge, TOOL)'''
V1N = r'''
    u32 WindPostWord(u32* words, u32 frame_slot, u32 view, u32 slot, bool reset, u64 positions, u32 positions_size, u64 frame,
                     const BbWind::Snapshot& now); // bbport (r112s_hang-bracket-move)'''
V2 = r'''    bool hang_proof_hide = false; // the Motion block's verdict for the draw in flight: leave it out (BB_WIND_HANG_PROOF_HIDE)'''
V2N = r'''
    BbWindHang::PostBook hang_post; // bbport (r112s_hang-bracket-move): the bracket lanterns' posts (BB_WIND_HANG_POST)'''

# ---- vk_rasterizer_effects.cpp --------------------------------------------------------------------------
E1 = r'''    if (small_palette >= 0 && !hang_static && BbWindTwigs::TreesWanted() &&'''
E1N = r'''    // bbport (r112s_hang-bracket-move): a draw of a post lantern's position stream (BB_WIND_HANG_POST) has its own word below (WindPostWord):
    // it is no plant, no tree of the twigs and no hanging thing of r112's judges
    const bool post = BbWindHang::PostOn() && BbWindHang::PostMatches(positions_size, positions_stride);
    if (small_palette >= 0 && !hang_static && !post && BbWindTwigs::TreesWanted() &&'''
E2 = r'''    const bool plant = small_palette < 0 && rt_shadow->LonePlant(positions, positions_size);'''
E2N = r'''    const bool plant = !post && small_palette < 0 && rt_shadow->LonePlant(positions, positions_size);'''
E3 = r'''    const bool tree = !plant && !hang_static && (small_palette >= 0 // (r112i: a static hanging mesh)'''
E3N = r'''    const bool tree = !plant && !post && !hang_static && (small_palette >= 0 // (r112i: a static hanging mesh)'''
E4 = r'''    bool hang = !plant && !tree && (small_palette < 0 || hang_static) && // (r89e: no static cut-out)'''
E4N = r'''    bool hang = !plant && !tree && !post && (small_palette < 0 || hang_static) && // (r89e: no static cut-out)'''
E5 = r'''    const bool force = !plant && !tree && !hang && !judge && small_palette < 0 &&'''
E5N = r'''    const bool force = !plant && !tree && !hang && !judge && !post && small_palette < 0 &&'''
E6 = r'''    if (!plant && !hang && !tree && !judge && !force) {'''
E6N = r'''    if (!plant && !hang && !tree && !judge && !force && !post) {'''
E7 = r'''    if (tree && BbWindTwigs::ProofOn()) { // bbport (r89g_twigs-proof, TOOL): which pipelines draw it'''
E7P = r'''    if (post) { // bbport (r112s_hang-bracket-move): a post lantern's word (the keys fill, then the lean)
        return WindPostWord(words, frame_slot, view, taken.slot, taken.reset, positions, positions_size, frame, snapshot);
    }
'''
E8 = r'''// bbport (r89d_tree-twigs): whether a skinned sway draw that is no plant may be a tree'''
E8P = r'''// bbport (r112s_hang-bracket-move): a post lantern's sway word (BB_WIND_HANG_POST) once its stream has its slot (`reset`: its keys were reset now):
// PostBit and HangBit with a ramp of 0 while the GPU fills the slot's base and top keys (Measure, as for a hanging thing), then, if the keys' span
// is 0.15 m to PostMaxExtent, the ramp: Measure's times BB_WIND_HANG_STATIC_GAIN (live, as a static lantern's) and the live BB_WIND_HANG_PUSH switch;
// out of height 0 (no word). The first pushed draw of a view in a frame fills the view's push table, as WindHangWord does. On the thread recording draws.
u32 Rasterizer::WindPostWord(u32* words, u32 frame_slot, u32 view, u32 slot, bool reset, u64 positions, u32 positions_size, u64 frame,
                             const BbWind::Snapshot& now) {
    BbWindHang::PostBook::Item& item = hang_post.Touch(positions, positions_size, frame);
    ++hang_post.draws;
    const BbWindHang::Measured m =
        BbWindHang::Measure(item.entry, reset, frame, words + BbWindSway::BaseAt + slot, words + BbWindHang::TopAt + slot, now.time,
                            BbWindHang::PostMaxExtent);
    if (m.measuring) {
        ++hang_post.measuring;
        return BbWindHang::PostWord(frame_slot, view, slot, 0);
    }
    if (!m.swing) {
        ++hang_post.unfit;
        return 0;
    }
    if (frame != hang_frame) {
        hang_frame = frame;
        hang_filled = {};
    }
    if (!hang_filled[view]) {
        const u32* const words_of_view = words + BbWindSway::ViewAt(frame_slot, view);
        const auto& knob = BbWindSway::KnobOnce();
        std::array<float, BbWindSway::GustSamples> table{};
        hang_push.Fill(now, std::bit_cast<float>(words_of_view[BbWindSway::WindE + 2]),
                       std::bit_cast<float>(words_of_view[BbWindSway::WindE + 3]), knob.gusts, knob.scale, table.data());
        std::memcpy(words + BbWindHang::PushAt + (frame_slot * BbWindSway::Views + view) * BbWindSway::GustSamples, table.data(),
                    sizeof(table));
        hang_filled[view] = true;
    }
    ++hang_post.pushed;
    const u32 ramp = WindHangLiveOn() ? m.ramp : 0u;
    return BbWindHang::PostWord(frame_slot, view, slot, BbWindHangFind::SameRamp(ramp, WindHangGainNow(), 1.0f, true));
}

'''
E9 = r'''    // bbport (r112e_hang-taken): its line once (BB_WIND_HANG on)'''
E9P = r'''    // bbport (r112s_hang-bracket-move): BB_WIND_HANG_POST's line once
    static bool hang_post_said = false;
    if (!hang_post_said && BbWindHang::PostOn()) {
        hang_post_said = true;
        char post_once[1024];
        BbWindHang::PostOnceText(post_once, sizeof(post_once));
        BbReport::Printf("%s\n", post_once);
    }
'''
E10 = r'''        if (BbWindHangProbe::On()) { // bbport (r112b_hang-probe, TOOL)'''
E10P = r'''        if (BbWindHang::PostOn()) { // bbport (r112s_hang-bracket-move): the posts' line
            char post_line[640];
            BbWindHang::PostLineText(hang_post, hang_push.Now(), post_line, sizeof(post_line));
            BbReport::Printf("%s\n", post_line);
        }
'''

# ---- tests ----------------------------------------------------------------------------------------------
T1 = r'''    if (failures != 0) {
        std::printf("wind-hang-test: %d FAILED\n", failures);'''
T1P = r'''    // bbport (r112s_hang-bracket-move): the bracket lanterns' posts
    {
        const H::PostKnob unset = H::ParsePost(nullptr);
        Expect(unset.on && unset.count == 1 && unset.verts[0] == 13642u, "post: unset = on, 13642 vertices");
        const H::PostKnob one = H::ParsePost("1");
        Expect(one.on && one.count == 1 && one.verts[0] == 13642u, "post: 1 = the default");
        Expect(!H::ParsePost("0").on, "post: 0 = off");
        const H::PostKnob list = H::ParsePost("20000:13642 77");
        Expect(list.on && list.count == 3 && list.verts[0] == 20000u && list.verts[1] == 13642u && list.verts[2] == 77u, "post: a list");
        const H::PostKnob junk = H::ParsePost("abc");
        Expect(junk.on && junk.count == 1 && junk.verts[0] == 13642u, "post: no number = the default");
        const H::PostKnob zero = H::ParsePost("0:5");
        Expect(zero.on && zero.count == 1 && zero.verts[0] == 5u, "post: a zero in a list is none (only exactly 0 is off)");
        const H::PostKnob many = H::ParsePost("1:2:3:4:5:6:7:8:9:10");
        Expect(many.count == H::PostStreamsMost && many.verts[7] == 8u, "post: at most 8 counts");
        Expect(H::ParsePost("999999999999999").verts[0] == 100000000u, "post: a huge number is held");
        Expect(H::PostMatchesIn(unset, 13642u * 32u, 32u) && !H::PostMatchesIn(unset, 13642u * 32u, 16u) && !H::PostMatchesIn(unset, 0, 0) &&
                   H::PostMatchesIn(unset, 13642u * 32u + 31u, 32u),
               "post: a stream matches by size / stride");
        Expect(!H::PostMatchesIn(H::ParsePost("0"), 13642u * 32u, 32u), "post: off matches nothing");
        Expect(H::PostBit == (1u << 15) && (H::PostBit & H::HangBit) == 0 && (H::PostBit & W::WordOn) == 0, "post: the bit is free");
        const std::uint32_t word = H::PostWord(2, 1, 77, 200);
        Expect(H::PostOf(word) && H::HangOf(word) && word == (H::HangWord(2, 1, 77, 200) | H::PostBit) && !H::PostOf(H::HangWord(2, 1, 77, 200)),
               "post: a post's word is a hang word with PostBit");
        // the shaders' weight: 1 in the top 20 percent, 0 from 65 percent down, 0.5 half way, a bad height = 2 m
        Expect(H::PostT(0.0f, 5.66f) == 1.0f && H::PostT(0.2f * 5.66f, 5.66f) >= 0.999f, "post: full at the top 20 percent");
        Expect(H::PostT(0.65f * 5.66f, 5.66f) < 1e-5f && H::PostT(0.9f * 5.66f, 5.66f) == 0.0f && H::PostT(5.66f, 5.66f) == 0.0f,
               "post: none from 65 percent down");
        Expect(std::fabs(H::PostT(0.425f * 5.66f, 5.66f) - 0.5f) < 1e-4f, "post: half way down the ramp");
        Expect(H::PostT(1.0f, std::nanf("")) == H::PostT(1.0f, 0.5f) && H::PostT(1.0f, 0.5f) == H::PostT(1.0f, H::PostExtMin),
               "post: a height under 2 m or not a number is 2 m");
        float last = 2.0f;
        bool steps = true;
        for (int k = 0; k <= 100; ++k) {
            const float t = H::PostT(5.66f * float(k) / 100.0f, 5.66f);
            steps = steps && t >= 0.0f && t <= 1.0f && t <= last + 1e-6f;
            last = t;
        }
        Expect(steps, "post: the weight falls from the top down and stays in 0-1");
        // the keys: a post of 5.66 m measures and swings, a union of 12 m gets no word
        const std::uint32_t base_key = std::bit_cast<std::uint32_t>(-42.0f + W::HeightBias);
        const std::uint32_t top_key = H::TopKey(-36.34f);
        H::Entry e;
        const H::Measured m0 = H::Measure(e, true, 100, &base_key, &top_key, 1.0, H::PostMaxExtent);
        Expect(m0.measuring && !m0.swing, "post: the keys are read after JudgeFrames");
        const H::Measured m1 = H::Measure(e, false, 100 + H::JudgeFrames, &base_key, &top_key, 1.0, H::PostMaxExtent);
        Expect(!m1.measuring && m1.swing && e.judged && e.fits && std::fabs((e.top - e.base) - 5.66f) < 0.01f, "post: 5.66 m fits");
        const std::uint32_t tall_top = H::TopKey(-30.0f);
        H::Entry tall_entry;
        (void)H::Measure(tall_entry, true, 100, &base_key, &tall_top, 1.0, H::PostMaxExtent);
        const H::Measured m2 = H::Measure(tall_entry, false, 100 + H::JudgeFrames, &base_key, &tall_top, 1.0, H::PostMaxExtent);
        Expect(!m2.measuring && !m2.swing && tall_entry.judged && !tall_entry.fits, "post: a 12 m span (the union of far places) gets no word");
        // the book
        H::PostBook book;
        H::PostBook::Item& a = book.Touch(0x1000, 436544u, 5);
        a.entry.judged = true;
        a.entry.fits = true;
        a.entry.base = -42.0f;
        a.entry.top = -36.34f;
        Expect(&book.Touch(0x1000, 436544u, 6) == &a && a.seen == 6, "post book: the same stream, the same item");
        (void)book.Touch(0x1000, 99u, 7);
        Expect(!book.Touch(0x1000, 99u, 7).entry.judged, "post book: another size at the address forgets it");
        for (std::uint64_t k = 0; k < H::PostKept + 5; ++k) {
            (void)book.Touch(0x2000 + k, 1u, 8);
        }
        Expect(book.Items().size() <= H::PostKept, "post book: bounded");
        H::PostBook shown;
        H::PostBook::Item& b = shown.Touch(0x3000, 436544u, 1);
        b.entry.judged = true;
        b.entry.fits = true;
        b.entry.base = -42.0f;
        b.entry.top = -36.34f;
        shown.draws = 10;
        shown.measuring = 3;
        shown.pushed = 6;
        shown.unfit = 1;
        char line[700];
        H::PostLineText(shown, 0.123f, line, sizeof(line));
        Expect(std::strstr(line, "Wind sway hang post (r112s, BB_WIND_HANG_POST): since the start 10 draws of 1 streams: 3 measuring, 6 pushed, 1 with no word") == line &&
                   std::strstr(line, "1 judged, 1 swinging (the first: base y -42.00, top y -36.34, 5.66 m tall); push 0.123 m") != nullptr,
               "post: the periodic line");
        char once[1100];
        H::PostOnceText(once, sizeof(once));
        Expect(std::strstr(once, "holds 13642 vertices") != nullptr && std::strstr(once, "top 20 percent") != nullptr &&
                   std::strstr(once, "from 65 percent down") != nullptr && std::strstr(once, "(+50000)") != nullptr,
               "post: the once line");
        Expect(H::StripProofVersion(22u + 2000u + 8000u) == 22u + 2000u + 8000u, "post: the strip leaves a version with neither add");
    }

    if (failures != 0) {
        std::printf("wind-hang-test: %d FAILED\n", failures);'''

# ---- README ---------------------------------------------------------------------------------------------
M1 = r'''| `BB_WIND_HANG_PROOF` | A TEST aid for `BB_WIND_HANG` (r112m;'''
M1P = r'''| `BB_WIND_HANG_POST` | Part of `BB_WIND_HANG=1` (r112s; read once; unset or `1` = on for position streams of 13642 vertices, exactly `0` = off (r112r), or the vertex counts of other posts' streams separated by `:`, at most 8; the log's once line says what is on). The bracket lanterns of the graveyard are not hanging meshes: the lantern is part of a lamp POST (one mesh, 5.7 m tall, 2.2 m wide, 10796 vertices, a position stream of 13642 vertices), which the twig rules took for a tree (a tree word that weighs by the vertex's height over the camera: about 0 at the lantern) and the hang rules never judged (they take things 0.15-4 m tall, and would push a post's foot). A draw of such a stream now gets a hang word with its own bit: the shaders weigh each vertex by its depth below the slot's top key over the keys' height (1 within the top 20 percent of the mesh, 0 from 65 percent down), so the upper part of the post, with its lantern, leans downwind as one piece and its foot stays. Push, direction, timing and the live `BB_WIND_HANG_STATIC_GAIN` (default 0.2) and `BB_WIND_HANG_PUSH` are a hanging thing's: the top moves up to about 9 cm in a full gust at 4 m/s with `BB_WIND_SWAY=3`, about 1 cm at 1.5 m/s. The keys' span (the union of the places the stream is drawn at) must be 0.15-10 m, else no word. The proof (`BB_WIND_HANG_PROOF`) tints it cyan. Sway shaders built with it have their own cache version (+50000). Costs nothing with `BB_WIND_HANG` unset; with it, 8 operations a vertex of the sway shaders. |
'''

EDITS = {
HH: [
('ins', H1A, H1AP, ""),
('ins', H2A, H2AP, ""),
('ins', H3A, H3AP[:-len(H3A)], ""),
('rep', H4A, "", H4N),
],
LS: [
('rep', L1, "", L1N),
],
ES: [
('rep', S1, "", S1N),
],
SE: [
('ins', P1, P1P, ""),
],
RH: [
('ins', V1, "", V1N),
('ins', V2, "", V2N),
],
EF: [
('rep', E1, "", E1N),
('rep', E2, "", E2N),
('rep', E3, "", E3N),
('rep', E4, "", E4N),
('rep', E5, "", E5N),
('rep', E6, "", E6N),
('ins', E7, E7P, ""),
('ins', E8, E8P, ""),
('ins', E9, E9P, ""),
('ins', E10, E10P, ""),
],
TH: [
('ins', T1, T1P[:-len(T1)], ""),
],
RM: [
('ins', M1, M1P, ""),
],
}

ORDER = (HH, LS, ES, SE, RH, EF, TH, RM)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def parts_of(ed):
    if ed[0] == "rep":
        return ed[1], [ed[3]], [ed[1]]
    return ed[1], [t for t in (ed[2], ed[3]) if t], []


def state_of(cur, eds, path):
    done = todo = 0
    for ed in eds:
        anchor, present, absent = parts_of(ed)
        if ed[0] == "rep":
            n_old, n_new = cur.count(anchor), cur.count(present[0])
            if n_new == 1 and n_old == 0:
                done += 1
            elif n_old == 1 and n_new == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times (wanted once), new text %d "
                                 "times: %r" % (path, n_old, n_new, anchor[:70]))
            continue
        na, counts = cur.count(anchor), [cur.count(t) for t in present]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s "
                             "times: %r" % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_edits(cur, eds):
    for ed in eds:
        if ed[0] == "rep":
            cur = cur.replace(ed[1], ed[3], 1)
        else:
            cur = cur.replace(ed[1], ed[2] + ed[1] + ed[3], 1)
    return cur


def revert_edits(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "rep":
            cur = cur.replace(ed[3], ed[1], 1)
        else:
            for part in (ed[3], ed[2]):
                if part:
                    cur = cur.replace(part, "", 1)
    return cur


def balance(text):
    """(braces, parens, brackets) net of a C++ text without comments, strings and char literals."""
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', text)
    text = re.sub(r"'(?:\\.|[^'\\\n])'", "' '", text)
    return (text.count("{") - text.count("}"), text.count("(") - text.count(")"),
            text.count("[") - text.count("]"))


CPP = (HH, LS, ES, SE, RH, EF, TH)


def text_checks(texts, olds):
    """The ties a compiler cannot check."""
    hh, ls, es, se, rh, ef, th = (texts[p] for p in CPP)
    for path in CPP:
        if balance(texts[path]) != balance(olds[path]):
            raise SystemExit("text check: %s: braces, parens or brackets changed by %r" %
                             (path, tuple(a - b for a, b in zip(balance(texts[path]), balance(olds[path])))))
    for block in (H1AP, H2AP, H3AP, H4N, L1N, S1N, P1P, V1N, V2N, E1N, E2N, E3N, E4N, E5N, E6N, E7P, E8P, E9P, E10P, T1P, M1P):
        try:
            block.encode("ascii")
        except UnicodeEncodeError:
            raise SystemExit("text check: a non-ASCII character in an inserted block: %r" % block[:60])
        if "\t" in block:
            raise SystemExit("text check: a tab in an inserted block: %r" % block[:60])
    for block in (H1AP, H2AP, H3AP[:-len(H3A)], E7P, E8P, E9P, E10P, T1P[:-len(T1)]):
        if balance(block) != (0, 0, 0):
            raise SystemExit("text check: an inserted block does not balance: %r %r" % (block[:60], balance(block)))
    # the header: the knob and PostT come before StripProofVersion (it calls PostOn), PostWord after HangWord, the book after Entry and Measure
    if not (hh.index("inline bool PostOn()") < hh.index("inline std::uint32_t StripProofVersion(")):
        raise SystemExit("text check: PostOn comes before StripProofVersion")
    if not (hh.index("constexpr std::uint32_t HangWord(") < hh.index("constexpr std::uint32_t PostWord(")):
        raise SystemExit("text check: PostWord comes after HangWord")
    if not (hh.index("inline Measured Measure(") < hh.index("class PostBook {") < hh.rindex("} // namespace BbWindHang")):
        raise SystemExit("text check: PostBook comes after Measure and inside the namespace")
    if not (hh.index("inline constexpr std::uint32_t ProofBinaryAdd") < hh.index("inline constexpr std::uint32_t PostBinaryAdd")):
        raise SystemExit("text check: ProofBinaryAdd comes before PostBinaryAdd (a static_assert uses it)")
    if hh.count("PostBit = 1u << 15") != 1:
        raise SystemExit("text check: PostBit")
    # the emitters: the post block sits inside `if (hang_on)` right after ht and before hw
    for text, ht_old, hw, name in ((ls, "u32 ht = clamp_f(", "const u32 hw = FMul(", "lifter"), (es, "Id ht = ctx.OpFClamp(", "const Id hw = mul(", "recompiler")):
        a, b = text.index(ht_old), text.index("H::PostOn()")
        c = text.index(hw)
        if not (a < b < c):
            raise SystemExit("text check: %s: the post block is between ht and hw" % name)
        if text.count("H::PostOn()") != 1 or text.count("H::PostBit") != 1 or text.count("H::PostExtMin") != 1:
            raise SystemExit("text check: %s: the post block once" % name)
    if "hang_on = BbWindHang::KnobOnce().on" not in ls or "hang_on = BbWindHang::KnobOnce().on" not in es:
        raise SystemExit("text check: hang_on is read in both emitters")
    # serialization: the offset sits in the same expression as the proof's
    if se.count("BbWindHang::PostBinaryOffset() +") != 1 or se.index("BbWindHang::PostBinaryOffset()") > se.index("BbWindHang::ProofBinaryOffset()"):
        raise SystemExit("text check: serialization: the post offset is added before the proof's")
    # the rasterizer: declaration, member, the six conditions, the word's return, the function, the lines
    if rh.count("u32 WindPostWord(") != 1 or rh.count("BbWindHang::PostBook hang_post;") != 1:
        raise SystemExit("text check: rasterizer.h")
    if ef.count("!post") != 6 or ef.count("const bool post = BbWindHang::PostOn()") != 1:
        raise SystemExit("text check: effects: the post conditions (got %d)" % ef.count("!post"))
    if not (ef.index("const bool post = ") < ef.index("const bool plant = !post") < ef.index("const bool tree = !plant && !post")
            < ef.index("bool hang = !plant && !tree && !post") < ef.index("const bool force = ") < ef.index("if (post) { // bbport (r112s")):
        raise SystemExit("text check: effects: the post conditions are in order")
    wsw = ef.index("u32 Rasterizer::WindSwayWord(")
    if not (wsw < ef.index("const bool post = ") < ef.index("return WindPostWord(") < ef.index("u32 Rasterizer::WindPostWord(")):
        raise SystemExit("text check: effects: WindPostWord is called inside WindSwayWord and defined after it")
    if ef.index("u32 Rasterizer::WindPostWord(") > ef.index("bool Rasterizer::WindTwigTree("):
        raise SystemExit("text check: effects: WindPostWord comes before WindTwigTree")
    if ef.count("BbWindHang::PostLineText(hang_post") != 1 or ef.count("BbWindHang::PostOnceText(") != 1:
        raise SystemExit("text check: effects: the log lines")
    if not (ef.index("static bool WindHangLiveOn()") < ef.index("u32 Rasterizer::WindPostWord(")) or not (ef.index("static float WindHangGainNow()") < ef.index("u32 Rasterizer::WindPostWord(")):
        raise SystemExit("text check: effects: the live knobs are defined before WindPostWord")
    # tests
    if th.index("post: unset = on") > th.index('std::printf("wind-hang-test: %d FAILED\\n", failures);'):
        raise SystemExit("text check: the test block comes before the verdict")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112S_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == HH and "ProofBinaryAdd = 200000" not in cur:
            raise SystemExit("REFUSED: r112r must be applied")
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_edits(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    olds = {p[0]: p[4] for p in plan}
    if cmd == "check":
        if state == "applied":
            text_checks(olds, {p[0]: revert_edits(p[4], p[1]) for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts(), olds)
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts, olds)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r112stmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_edits(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r112stmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


if __name__ == "__main__":
    main()
