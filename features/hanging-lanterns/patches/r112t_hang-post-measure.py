# r112t_hang-post-measure (FEATURE fix, behind BB_WIND_HANG=1 and BB_WIND_HANG_POST, no new knob): the lamp post's keys come from the ray traced
# scene's box of the post, not from the GPU's union of every place the stream is drawn at. On top of r112s_hang-bracket-move and everything through
# build 68.
#
# WHY THE MEASURE "READ ZEROS" (read from b68_s1.log, b68_s2.log, the r112s code and the scene box code; nothing was run)
#  - It did not read zeros. 'base y 0.00, top y 0.00, 0.00 m tall' is the DEFAULT of the line's variables: PostLineText copies the first stream's
#    base and top only `if (e.judged && e.fits)`, and the line says '1 judged, 0 swinging': the one judgement (8 frames after the slot was taken:
#    '16 measuring' = 2 draws a frame x 8) found the keys' span OUT of 0.15-10 m, and Measure keeps an unfit verdict for good (r112's rule:
#    `if (!e.fits) return {}`): the other 5252 draws got 'no word' ('keys span over 10 m or under 0.15 m'). The line never printed what was read.
#  - The span is over 10 m, not under 0.15 m. The slot's keys (r89's base key, r112's top key) are atomic minima over EVERY vertex of EVERY draw of the
#    stream, so they span the UNION of the places the post mesh is drawn at: the sun shadow passes draw the lamp posts all over the graveyard, at
#    grounds about 9-10 m apart (r112k, same log family: lanterns whose scene box is 0.41 and 0.89 m tall have keys of 9.38 and 9.87 m; their posts
#    stand at the same places), and a post is 5.66 m on top of that. r112s's own job text predicted it ('a union over 10 m shows no word').
#  - Raising the limit would not help: the shaders weigh a vertex by its depth below the slot's TOP key, so with a union only the post at the
#    highest ground would lean.
#
# THE FIX (FEATURE; same knob as r112s: BB_WIND_HANG_POST)
#  - The ray traced scene lists a world box for every mesh entry (RtShadow::WindHangFindBoxes: one entry per mesh key, i.e. per post; the survey's
#    hang_find_boxes, refreshed every 60 frames). WindPostWord takes the boxes of its own stream (BbWindHang::PickPost): the one whose centre is
#    nearest the camera horizontally (boxes within 0.75 m of each other in distance are one place: the camera pass capture's box 'c' wins over the
#    still bounds 's' over the sun VSM's 'v'). Its lowest and highest y are the post's base and top.
#  - The CPU writes them into the slot's base key and top key (BbWindSway::HeightKey / BbWindHang::TopKey) when the slot is new, the keys are not yet
#    written or the box changed (a store of two words into the mapped words, as the slot reset does; no read of GPU memory, no GPU measure window).
#  - The shaders (lifter and recompiler) offer NO key for a word with PostBit: the base key's offer and the top key's offer get an extra
#    `(word & PostBit) == 0` (only with BB_WIND_HANG and the post rule on, like the r112s block). So the GPU can no longer widen the keys.
#  - The ramp starts when the post first has keys (or a new slot): the 8 measuring frames are gone. Height out of 0.15-10 m, or no box of the stream
#    in the scene (no ray tracing, not seen for 120 frames): no word, counted.
#  - The weight (r112s's PostT: 1 in the top 20 percent of the post, 0 from 65 percent down) now works from the post's own height. Posts of the
#    stream other than the nearest are weighed by that post's top: one on lower ground gets weight 0 at its lantern (it stands still), one on higher
#    ground leans as a whole piece (3-8 cm at its foot, hidden in grass and stone); the nearest, the one the owner looks at, is right.
#
# LOGS (FEATURE: once-lines and counters; session.log)
#  - once, when the stream is first drawn: 'Wind sway hang post vertices (r112t_hang-post-measure): the stream holds N vertices (stride S, B bytes);
#    the first three, as floats: v0 (...) v1 (...) v2 (...); the box of floats 0-2 over all of them: x a..b (c m), y ...' (the vertex format: does a
#    float3 position at offset 0 give the 5.7 m?). 'cannot be read' when the stream is not mapped.
#  - periodic, after r112s's line: 'Wind sway hang post (r112t, keys from the scene's box): D draws with no box, W key writes; last pick: N boxes of
#    the stream, nearest X m, base y, top y, H m tall (...)'. r112s's own line now shows the real base and top ('swinging' 1) once a post fits.
#
# SHARED LINES TOUCHED
#  lift_stage.cpp, emit_spirv_special.cpp: the base key's offer statement (const -> not const, plus a block) and the top key's offer (one name).
#  vk_rasterizer.h: the WindPostWord declaration (the stride parameter). vk_rasterizer_effects.cpp: WindPostWord (head, body), its call, the periodic
#  line (one more printf). bbport_wind_hang.h: PostBinaryAdd 50000 -> 52000 (the SPIR-V changed: a new cache version), PostPick/PickPost, Item/book
#  members, two text functions, the once text, `#include <cstring>`. test_wind_hang.cpp: one block, one string. README.md: the row (two places).
#
# COST WHEN OFF: nothing changes when BB_WIND_HANG is unset (the new shader lines sit in `if (hang_on && PostOn())`, WindPostWord is called only for a
# post draw, which needs BB_WIND_HANG): shaders byte-identical to build 68. With BB_WIND_HANG=1 and POST=0: the old shaders of r112r (the new lines
# need PostOn()). ON: 3 ALU ops per vertex of the sway shaders for the key offers (and, compare, logical-and, twice reuses the first); CPU: a loop over
# the scene's boxes once a frame per post stream (cached), two word stores when the box changes; one read of the stream's vertices once (the log).
#
# Use: python -I -X utf8 r112t_hang-post-measure.py check | apply | revert
# Root: R112T_ROOT, else <tree>. Line ends kept. apply backs the originals up in r112t_backup next to this script; revert takes out exactly what
# apply put in. Needs r112s (and everything before it) applied.
import os, re, sys

ROOT = os.environ.get("R112T_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112t_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RH = RV + "vk_rasterizer.h"
EF = RV + "vk_rasterizer_effects.cpp"
SH = "engine/gpu/shim/"
HH = SH + "bbport_wind_hang.h"
LS = SH + "lifter/lift_stage.cpp"
ES = "engine/gpu/shadps4/shader_recompiler/backend/spirv/emit_spirv_special.cpp"
TH = "engine/tests/test_wind_hang.cpp"
RM = "README.md"

# ---- bbport_wind_hang.h ---------------------------------------------------------------------------------
HA = r'''inline constexpr std::uint32_t PostBinaryAdd = 50000;'''
HAN = r'''inline constexpr std::uint32_t PostBinaryAdd = 52000;'''
HB = r'''and the post rule's add (50000, under the proof's 200000; every other sum is under 20000)'''
HBN = r'''and the post rule's add (52000 since r112t, under the proof's 200000; every other sum is under 20000)'''

HI_ANCHOR = r'''#include <unordered_map>'''
HI_BEFORE = r'''#include <cstring>
'''

# the picks: before the posts' book
HP_ANCHOR = r'''// ---- bbport (r112s_hang-bracket-move): the posts' book and lines'''
HP_BEFORE = r'''// ---- bbport (r112t_hang-post-measure): a post's keys from the scene's box -------------------------------------------------------------------
// b68: the post's slot judged out of 0.15-10 m for good (no word for 5252 draws). The slot's keys are atomic minima over every vertex of every draw of
// the stream, so they span the UNION of the places the post is drawn at (the sun passes draw the posts all over the graveyard: 9-10 m of ground
// height before the post's own 5.7 m). The ray traced scene has a world box per mesh entry (one per post): the CPU takes the box of the post nearest
// the camera and writes its base and top into the slot's keys, and the shaders offer no key for a word with PostBit.
inline constexpr float PostPickTie = 0.75f; ///< m: boxes of a stream whose horizontal distances to the camera differ by less are one place

struct PostPick {
    bool found = false;
    bool camera = false;           ///< dist is a distance (else the first box of the best source won)
    std::uint32_t count = 0;       ///< boxes of the stream with a usable height
    float base = 0.0f, top = 0.0f; ///< the picked box's lowest and highest world y
    float dist = -1.0f;            ///< m, horizontal, the box's centre to the camera (-1: no camera)
    char src = '?';                ///< the picked box's source (c camera capture, s still bounds, v sun VSM box)
};

/// The box of the stream nearest `camera` (x, y, z world; null: none known): `boxes` any container of items with `stream`, `box` (least x, y, z,
/// greatest x, y, z, y up) and `src`. Among boxes within PostPickTie of the nearest distance the source decides: c, then s, then v.
template <class Boxes>
[[nodiscard]] inline PostPick PickPost(const Boxes& boxes, std::uint64_t stream, const float* camera) {
    PostPick pick;
    if (stream == 0) {
        return pick;
    }
    int best_rank = 3;
    for (const auto& b : boxes) {
        if (b.stream != stream) {
            continue;
        }
        bool usable = true; // every corner finite and in range: a NaN centre would make a distance no later box can beat
        for (const float c : b.box) {
            usable = usable && std::isfinite(c) && std::fabs(c) < 1.0e5f;
        }
        const float lo = b.box[1], hi = b.box[4];
        if (!(usable && hi > lo)) {
            continue;
        }
        ++pick.count;
        float dist = 0.0f;
        if (camera != nullptr) {
            const float cx = 0.5f * (b.box[0] + b.box[3]) - camera[0];
            const float cz = 0.5f * (b.box[2] + b.box[5]) - camera[2];
            dist = std::sqrt(cx * cx + cz * cz);
        }
        const int rank = b.src == 'c' ? 0 : (b.src == 's' ? 1 : 2);
        bool better = !pick.found;
        if (pick.found) {
            const bool nearer = dist < pick.dist - PostPickTie;
            const bool same = !nearer && dist <= pick.dist + PostPickTie;
            better = nearer || (same && rank < best_rank);
        }
        if (better) {
            pick.found = true;
            pick.camera = camera != nullptr;
            pick.base = lo;
            pick.top = hi;
            pick.dist = dist;
            pick.src = b.src;
            best_rank = rank;
        }
    }
    if (!pick.camera) {
        pick.dist = -1.0f;
    }
    return pick;
}

'''
# the item's members
HC = r'''        std::uint32_t size = 0;
        std::uint64_t seen = 0;
    };'''
HCN = r'''        std::uint32_t size = 0;
        std::uint64_t seen = 0;
        bool logged = false;        ///< bbport (r112t): the stream's vertices line was written
        bool keys_written = false;  ///< bbport (r112t): the slot's keys hold base_key and top_key
        std::uint32_t base_key = 0, top_key = 0;
        PostPick pick;              ///< bbport (r112t): the pick of pick_frame
        std::uint64_t pick_frame = ~0ull;
    };'''
HD = r'''    std::uint64_t unfit = 0;     ///< no word: the keys' span was out of 0.15 m to PostMaxExtent'''
HDP = r'''
    std::uint64_t no_box = 0;    ///< bbport (r112t): no word: no box of the stream in the ray traced scene
    std::uint64_t written = 0;   ///< bbport (r112t): times the CPU wrote the slot's keys from a box
    PostPick last;               ///< bbport (r112t): the last pick (a box that fits or not)'''
# the two text functions: before the once text
HT_ANCHOR = r'''/// The once line (BB_WIND_HANG=1 and the post rule on).'''
HT_BEFORE = r'''/// bbport (r112t_hang-post-measure): the second periodic line (the box the keys come from).
inline void PostBoxLineText(const PostBook& book, char* out, std::size_t size) {
    const PostPick& p = book.last;
    char where[160];
    if (p.found) {
        std::snprintf(where, sizeof(where), "%u boxes of the stream, picked (%c) %.1f m from the camera: base y %.2f, top y %.2f, %.2f m tall",
                      static_cast<unsigned>(p.count), p.src, double(p.dist), double(p.base), double(p.top), double(p.top - p.base));
    } else {
        std::snprintf(where, sizeof(where), "no box of the stream yet");
    }
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(out, size,
                  "Wind sway hang post (r112t, keys from the scene's box): %llu draws with no box of the stream in the ray traced scene, %llu out of "
                  "%.2f-%.0f m, %llu key writes; the last pick: %s; the shaders offer no key for a post word",
                  n(book.no_box), n(book.unfit), double(MinExtent), double(PostMaxExtent), n(book.written), where);
}

/// bbport (r112t_hang-post-measure): once, what the post's position stream holds: `data` its bytes (null: not readable), `size` bytes at `stride`:
/// the first three vertices' floats (up to 8) and the box of floats 0-2 over all vertices.
inline void PostVerticesText(const unsigned char* data, std::uint32_t size, std::uint32_t stride, char* out, std::size_t out_size) {
    if (data == nullptr || stride < 12 || size < stride) {
        std::snprintf(out, out_size,
                      "Wind sway hang post vertices (r112t_hang-post-measure): the stream cannot be read (%s, %u bytes, stride %u)",
                      data == nullptr ? "not mapped" : "too short or no float3 position", static_cast<unsigned>(size), static_cast<unsigned>(stride));
        return;
    }
    const std::uint32_t count = size / stride;
    const std::uint32_t floats = std::min<std::uint32_t>(8u, stride / 4u);
    float lo[3] = {1.0e30f, 1.0e30f, 1.0e30f};
    float hi[3] = {-1.0e30f, -1.0e30f, -1.0e30f};
    char first[3][160] = {};
    for (std::uint32_t v = 0; v < count; ++v) {
        float p[8] = {};
        std::memcpy(p, data + static_cast<std::size_t>(v) * stride, static_cast<std::size_t>(floats) * 4u);
        for (int k = 0; k < 3; ++k) {
            if (std::isfinite(p[k]) && std::fabs(p[k]) < 1.0e6f) {
                lo[k] = std::min(lo[k], p[k]);
                hi[k] = std::max(hi[k], p[k]);
            }
        }
        if (v < 3) {
            std::size_t at = 0;
            for (std::uint32_t f = 0; f < floats; ++f) {
                const int w = std::snprintf(first[v] + at, sizeof(first[v]) - at, f == 0 ? "%.2f" : ", %.2f", double(p[f]));
                at = std::min<std::size_t>(at + (w > 0 ? static_cast<std::size_t>(w) : std::size_t{0}), sizeof(first[v]) - 1);
            }
        }
    }
    std::snprintf(out, out_size,
                  "Wind sway hang post vertices (r112t_hang-post-measure): the stream holds %u vertices (stride %u, %u bytes); the first three, as "
                  "floats: v0 (%s) v1 (%s) v2 (%s); the box of floats 0-2 over all of them: x %.2f..%.2f (%.2f m), y %.2f..%.2f (%.2f m), "
                  "z %.2f..%.2f (%.2f m)",
                  static_cast<unsigned>(count), static_cast<unsigned>(stride), static_cast<unsigned>(size), first[0], first[1], first[2],
                  double(lo[0]), double(hi[0]), double(hi[0] - lo[0]), double(lo[1]), double(hi[1]), double(hi[1] - lo[1]), double(lo[2]),
                  double(hi[2]), double(hi[2] - lo[2]));
}

'''
HO = r'''keys' span 0.15-%.0f m; its shaders have their own cache version'''
HON = r'''its keys are the ray traced scene's box of the post nearest the camera (0.15-%.0f m tall); its shaders have their own cache version'''

# ---- lift_stage.cpp / emit_spirv_special.cpp ------------------------------------------------------------
L1 = r'''    const u32 offer = Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool,
                           {FCmp(O(spv::Op::OpFOrdLessThan), abs_f(wy), CF(W::FiniteMost)), ICmp(O(spv::Op::OpULessThan), key, stored)});'''
L1N = r'''    u32 offer = Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool,
                     {FCmp(O(spv::Op::OpFOrdLessThan), abs_f(wy), CF(W::FiniteMost)), ICmp(O(spv::Op::OpULessThan), key, stored)});
    u32 post_none = 0;
    if (hang_on && BbWindHang::PostOn()) { // bbport (r112t_hang-post-measure): a post's word (PostBit) offers no key: the CPU writes its slot's keys from the scene's box
        post_none = ICmp(O(spv::Op::OpIEqual), IOp(O(spv::Op::OpBitwiseAnd), word, CU(BbWindHang::PostBit)), CU(0));
        offer = Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool, {offer, post_none});
    }'''
L2 = r'''        const u32 offer_top = Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool,
                                   {hang, Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool,'''
L2N = r'''        const u32 hang_offers = BbWindHang::PostOn() ? Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool, {hang, post_none}) : hang; // bbport (r112t_hang-post-measure)
        const u32 offer_top = Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool,
                                   {hang_offers, Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool,'''
S1 = r'''    const Id offer = ctx.OpLogicalAnd(
        bool_type, ctx.OpFOrdLessThan(bool_type, ctx.OpFAbs(f32_type, wy), f(W::FiniteMost)),
        ctx.OpULessThan(bool_type, key, stored));'''
S1N = r'''    Id offer = ctx.OpLogicalAnd(
        bool_type, ctx.OpFOrdLessThan(bool_type, ctx.OpFAbs(f32_type, wy), f(W::FiniteMost)),
        ctx.OpULessThan(bool_type, key, stored));
    Id post_none{};
    if (hang_on && BbWindHang::PostOn()) { // bbport (r112t_hang-post-measure): a post's word (PostBit) offers no key: the CPU writes its slot's keys from the scene's box
        post_none = ctx.OpIEqual(bool_type, ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(BbWindHang::PostBit)), ctx.u32_zero_value);
        offer = ctx.OpLogicalAnd(bool_type, offer, post_none);
    }'''
S2 = r'''        const Id offer_top = ctx.OpLogicalAnd(
            bool_type, hang,'''
S2N = r'''        const Id hang_offers = BbWindHang::PostOn() ? ctx.OpLogicalAnd(bool_type, hang, post_none) : hang; // bbport (r112t_hang-post-measure)
        const Id offer_top = ctx.OpLogicalAnd(
            bool_type, hang_offers,'''

# ---- vk_rasterizer.h ------------------------------------------------------------------------------------
V1 = r'''    u32 WindPostWord(u32* words, u32 frame_slot, u32 view, u32 slot, bool reset, u64 positions, u32 positions_size, u64 frame,'''
V1N = r'''    u32 WindPostWord(u32* words, u32 frame_slot, u32 view, u32 slot, bool reset, u64 positions, u32 positions_size, u32 positions_stride, u64 frame,'''

# ---- vk_rasterizer_effects.cpp --------------------------------------------------------------------------
E1 = r'''        return WindPostWord(words, frame_slot, view, taken.slot, taken.reset, positions, positions_size, frame, snapshot);'''
E1N = r'''        return WindPostWord(words, frame_slot, view, taken.slot, taken.reset, positions, positions_size, positions_stride, frame, snapshot);'''
E2 = r'''u32 Rasterizer::WindPostWord(u32* words, u32 frame_slot, u32 view, u32 slot, bool reset, u64 positions, u32 positions_size, u64 frame,'''
E2N = r'''u32 Rasterizer::WindPostWord(u32* words, u32 frame_slot, u32 view, u32 slot, bool reset, u64 positions, u32 positions_size, u32 positions_stride, u64 frame,'''
E3 = r'''    const BbWindHang::Measured m =
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
'''
E3N = r'''    // bbport (r112t_hang-post-measure): the slot's keys were the union of every place the stream is drawn at (b68: over 10 m, no word for good):
    // the CPU writes the keys of the post nearest the camera from the ray traced scene's boxes instead (the shaders offer no key for a post word)
    if (!item.logged) { // the stream's first three vertices and its box of floats 0-2, once
        item.logged = true;
        const bool readable = positions_stride >= 12 && memory->IsValidGpuMapping(positions, 0) &&
                              memory->ClampRangeSize(positions, positions_size) == positions_size;
        char vertices_line[1024];
        BbWindHang::PostVerticesText(readable ? reinterpret_cast<const unsigned char*>(positions) : nullptr, positions_size, positions_stride,
                                     vertices_line, sizeof(vertices_line));
        BbReport::Printf("%s\n", vertices_line);
    }
    if (reset) {
        item.keys_written = false; // the slot is new: its keys were just reset
    }
    if (item.pick_frame != frame) { // the boxes change every 60 frames, the camera every frame: once a frame
        WindHangFindRefresh(frame);
        item.pick = BbWindHang::PickPost(hang_find_boxes.All(), positions, hang_find_boxes.camera_ok ? hang_find_boxes.camera.data() : nullptr);
        item.pick_frame = frame;
    }
    const BbWindHang::PostPick pick = item.pick;
    if (pick.found) {
        hang_post.last = pick;
    }
    if (!pick.found) {
        ++hang_post.no_box;
        return 0;
    }
    const float post_height = pick.top - pick.base;
    if (!(post_height >= BbWindHang::MinExtent && post_height <= BbWindHang::PostMaxExtent)) {
        ++hang_post.unfit;
        return 0;
    }
    BbWindHang::Entry& post_entry = item.entry;
    if (reset || !post_entry.judged || !post_entry.fits) { // the ramp starts with a new slot or the first box that fits
        post_entry.started = true;
        post_entry.judged = true;
        post_entry.fits = true;
        post_entry.since = now.time;
        post_entry.measure_from = frame;
    }
    post_entry.base = pick.base;
    post_entry.top = pick.top;
    const u32 post_base_key = BbWindSway::HeightKey(pick.base);
    const u32 post_top_key = BbWindHang::TopKey(pick.top);
    if (!item.keys_written || item.base_key != post_base_key || item.top_key != post_top_key) {
        words[BbWindSway::BaseAt + slot] = post_base_key; // two stores into the mapped words, as the slot's reset does
        words[BbWindHang::TopAt + slot] = post_top_key;
        item.base_key = post_base_key;
        item.top_key = post_top_key;
        item.keys_written = true;
        ++hang_post.written;
    }
    const BbWindHang::Measured m{false, true, BbWindSway::RampByte((now.time - post_entry.since) / BbWindSway::RampTime)};
'''
E4 = r'''BbReport::Printf("%s\n", post_line);'''
E4P = r'''
            char post_box_line[704]; // bbport (r112t_hang-post-measure): the box the keys come from
            BbWindHang::PostBoxLineText(hang_post, post_box_line, sizeof(post_box_line));
            BbReport::Printf("%s\n", post_box_line);'''

# ---- tests ----------------------------------------------------------------------------------------------
T1 = r'''        Expect(H::StripProofVersion(22u + 2000u + 8000u) == 22u + 2000u + 8000u, "post: the strip leaves a version with neither add");'''
T1P = r'''
        // bbport (r112t_hang-post-measure): the post's keys from the scene's boxes, the vertices line, the box line
        struct TestBox {
            std::uint64_t stream;
            std::array<float, 6> box;
            char src;
        };
        const std::vector<TestBox> test_boxes{
            {0x1000, {10.0f, -42.0f, 5.0f, 11.1f, -36.34f, 7.2f}, 'v'},   // a post on lower ground, 12 m away
            {0x1000, {-2.0f, -30.0f, 3.0f, -0.9f, -24.34f, 5.2f}, 'c'},   // the post near the camera, camera pass box
            {0x1000, {-2.0f, -30.01f, 3.0f, -0.9f, -24.34f, 5.2f}, 'v'},  // the same post by the sun's box
            {0x2000, {0.0f, 0.0f, 0.0f, 1.0f, 1.0f, 1.0f}, 'c'},          // another stream
            {0x1000, {std::nanf(""), 0.0f, 0.0f, 1.0f, 1.0f, 1.0f}, 'c'}, // not finite: skipped
            {0x1000, {0.0f, 5.0f, 0.0f, 1.0f, 5.0f, 1.0f}, 'c'},          // no height: skipped
        };
        const float test_camera[3] = {-2.5f, -26.0f, 0.0f};
        const H::PostPick near_pick = H::PickPost(test_boxes, 0x1000, test_camera);
        Expect(near_pick.found && near_pick.camera && near_pick.count == 3 && near_pick.src == 'c' && std::fabs(near_pick.base + 30.0f) < 1e-4f &&
                   std::fabs(near_pick.top + 24.34f) < 1e-4f && near_pick.dist > 3.9f && near_pick.dist < 4.6f,
               "post pick: the nearest post, the camera pass box wins within the tie");
        const H::PostPick no_camera = H::PickPost(test_boxes, 0x1000, nullptr);
        Expect(no_camera.found && !no_camera.camera && no_camera.dist < 0.0f && no_camera.src == 'c' && no_camera.count == 3,
               "post pick: no camera: the first box of the best source");
        Expect(!H::PickPost(test_boxes, 0x3000, test_camera).found && !H::PickPost(test_boxes, 0, test_camera).found &&
                   !H::PickPost(std::vector<TestBox>{}, 0x1000, test_camera).found,
               "post pick: no box, stream 0, no boxes: none");
        const float far_camera[3] = {11.0f, -40.0f, 6.0f};
        const H::PostPick far_pick = H::PickPost(test_boxes, 0x1000, far_camera);
        Expect(far_pick.found && far_pick.src == 'v' && std::fabs(far_pick.base + 42.0f) < 1e-4f, "post pick: from the other post the other box is nearest");
        // the keys the CPU writes read back as the box
        const std::uint32_t base_key = W::HeightKey(near_pick.base);
        const std::uint32_t top_key = H::TopKey(near_pick.top);
        Expect(std::fabs(W::KeyHeight(base_key) - near_pick.base) < 1e-3f && std::fabs(H::KeyTop(top_key) - near_pick.top) < 1e-3f &&
                   base_key != W::ResetKey && top_key != W::ResetKey,
               "post keys: written keys read back as the box");
        std::array<float, 8 * 5> raw{};
        const float ys[5] = {0.0f, 5.66f, 2.0f, 1.0f, 3.0f};
        for (int v = 0; v < 5; ++v) {
            raw[static_cast<std::size_t>(v) * 8 + 0] = static_cast<float>(v);
            raw[static_cast<std::size_t>(v) * 8 + 1] = ys[v];
            raw[static_cast<std::size_t>(v) * 8 + 2] = 0.5f * static_cast<float>(v);
            raw[static_cast<std::size_t>(v) * 8 + 3] = 1.0f;
        }
        char vertices_text[1024];
        H::PostVerticesText(reinterpret_cast<const unsigned char*>(raw.data()), static_cast<std::uint32_t>(sizeof(raw)), 32, vertices_text,
                            sizeof(vertices_text));
        Expect(std::strstr(vertices_text, "the stream holds 5 vertices (stride 32, 160 bytes)") != nullptr &&
                   std::strstr(vertices_text, "v0 (0.00, 0.00, 0.00, 1.00, 0.00, 0.00, 0.00, 0.00) v1 (1.00, 5.66, 0.50, 1.00") != nullptr &&
                   std::strstr(vertices_text, "x 0.00..4.00 (4.00 m), y 0.00..5.66 (5.66 m), z 0.00..2.00 (2.00 m)") != nullptr,
               "post vertices: the line");
        H::PostVerticesText(nullptr, 100, 32, vertices_text, sizeof(vertices_text));
        Expect(std::strstr(vertices_text, "cannot be read (not mapped, 100 bytes, stride 32)") != nullptr, "post vertices: not mapped");
        H::PostVerticesText(reinterpret_cast<const unsigned char*>(raw.data()), 8, 32, vertices_text, sizeof(vertices_text));
        Expect(std::strstr(vertices_text, "too short") != nullptr, "post vertices: too short");
        H::PostBook box_book;
        box_book.no_box = 4;
        box_book.unfit = 2;
        box_book.written = 3;
        char box_line[704];
        H::PostBoxLineText(box_book, box_line, sizeof(box_line));
        Expect(std::strstr(box_line, "no box of the stream yet") != nullptr && std::strstr(box_line, "4 draws with no box") != nullptr &&
                   std::strstr(box_line, "3 key writes") != nullptr,
               "post box line: no pick yet");
        box_book.last = near_pick;
        H::PostBoxLineText(box_book, box_line, sizeof(box_line));
        Expect(std::strstr(box_line, "3 boxes of the stream, picked (c)") != nullptr && std::strstr(box_line, "base y -30.00, top y -24.34, 5.66 m tall") != nullptr,
               "post box line: the pick");'''
T2 = r'''std::strstr(once, "(+50000)")'''
T2N = r'''std::strstr(once, "(+52000)")'''

# ---- README ---------------------------------------------------------------------------------------------
M1 = r'''The keys' span (the union of the places the stream is drawn at) must be 0.15-10 m, else no word.'''
M1N = r'''r112t: the post's slot keys are the ray traced scene's box of the post of that stream nearest the camera, written by the CPU (the first fix took the keys the GPU collects, the union of every place the stream is drawn at, over 10 m in the graveyard: no word at all; the shaders now offer no key for a post word); the box must be 0.15-10 m tall, else no word, and without ray tracing or a box of the stream no word either. A post farther from the camera than the nearest is weighed by the nearest one's top (lower ground: it stands still; higher ground: it leans as a whole piece, a few cm). The log has the stream's first three vertices once and a second line with the pick.'''
M2 = r'''have their own cache version (+50000).'''
M2N = r'''have their own cache version (+52000).'''

EDITS = {
HH: [
('rep', HA, "", HAN),
('rep', HB, "", HBN),
('ins', HI_ANCHOR, HI_BEFORE, ""),
('ins', HP_ANCHOR, HP_BEFORE, ""),
('rep', HC, "", HCN),
('ins', HD, "", HDP),
('ins', HT_ANCHOR, HT_BEFORE, ""),
('rep', HO, "", HON),
],
LS: [
('rep', L1, "", L1N),
('rep', L2, "", L2N),
],
ES: [
('rep', S1, "", S1N),
('rep', S2, "", S2N),
],
RH: [
('rep', V1, "", V1N),
],
EF: [
('rep', E1, "", E1N),
('rep', E2, "", E2N),
('rep', E3, "", E3N),
('ins', E4, "", E4P),
],
TH: [
('ins', T1, "", T1P),
('rep', T2, "", T2N),
],
RM: [
('rep', M1, "", M1N),
('rep', M2, "", M2N),
],
}

ORDER = (HH, LS, ES, RH, EF, TH, RM)


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


CPP = (HH, LS, ES, RH, EF, TH)


def text_checks(texts, olds):
    """The ties a compiler cannot check."""
    hh, ls, es, rh, ef, th = (texts[p] for p in CPP)
    for path in CPP:
        if balance(texts[path]) != balance(olds[path]):
            raise SystemExit("text check: %s: braces, parens or brackets changed by %r" %
                             (path, tuple(a - b for a, b in zip(balance(texts[path]), balance(olds[path])))))
    for block in (HP_BEFORE, HCN, HDP, HT_BEFORE, HON, L1N, L2N, S1N, S2N, V1N, E1N, E2N, E3N, E4P, T1P, M1N):
        try:
            block.encode("ascii")
        except UnicodeEncodeError:
            raise SystemExit("text check: a non-ASCII character in an inserted block: %r" % block[:60])
        if "\t" in block:
            raise SystemExit("text check: a tab in an inserted block: %r" % block[:60])
    for block in (HP_BEFORE, HT_BEFORE, E4P, T1P):
        if balance(block) != (0, 0, 0):
            raise SystemExit("text check: an inserted block does not balance: %r %r" % (block[:60], balance(block)))
    # the header: PostPick before the book, the text functions after PostBook and before the once text, cstring included, one version constant
    if not (hh.index("struct PostPick {") < hh.index("class PostBook {") < hh.index("inline void PostBoxLineText(") < hh.index("inline void PostOnceText(")):
        raise SystemExit("text check: header order (PostPick, PostBook, the two lines, the once text)")
    if hh.index("inline void PostVerticesText(") > hh.index("inline void PostOnceText("):
        raise SystemExit("text check: PostVerticesText before the once text")
    if hh.count("#include <cstring>") != 1 or hh.count("PostBinaryAdd = 52000;") != 1 or hh.count("PostBinaryAdd = 50000") != 0:
        raise SystemExit("text check: the include and the version constant")
    # shaders: the post_none block sits before the offer's branch, hang_offers uses it, both emitters, only inside the knob
    for text, offer_label, name in ((ls, "const u32 offer_label = m.NewId();", "lifter"), (es, "const Id offer_label = ctx.OpLabel();", "recompiler")):
        a, b, c = text.index("post_none"), text.index("PostBit)", text.index("post_none")), text.index(offer_label)
        if not (a < b < c):
            raise SystemExit("text check: %s: the post_none block is before the offer's branch" % name)
        if text.count("hang_offers") != 2 or text.count("post_none") != 4 or text.count("BbWindHang::PostBit") != 1:
            raise SystemExit("text check: %s: post_none %d, hang_offers %d, PostBit %d" % (name, text.count("post_none"), text.count("hang_offers"),
                                                                                           text.count("BbWindHang::PostBit")))
    # rasterizer: the declaration and the call and the definition agree, the stride is passed
    if rh.count("u32 positions_size, u32 positions_stride, u64 frame,") != 1:
        raise SystemExit("text check: rasterizer.h: WindPostWord has the stride")
    if ef.count("positions_size, positions_stride, frame, snapshot);") != 1 or ef.count("u32 positions_size, u32 positions_stride, u64 frame,") != 1:
        raise SystemExit("text check: effects: the call and the definition have the stride")
    if ef.count("BbWindHang::Measure(item.entry") != 0 or ef.count("hang_post.measuring") != 0:
        raise SystemExit("text check: effects: the post word no longer calls Measure (the measuring counter is no longer counted)")
    if not (ef.index("u32 Rasterizer::WindPostWord(") < ef.index("BbWindHang::PickPost(") < ef.index("const BbWindHang::Measured m{false, true,") < ef.index("++hang_post.pushed;")):
        raise SystemExit("text check: effects: the pick is before the word's ramp and the push table")
    if ef.count("BbWindHang::PostBoxLineText(") != 1 or ef.count("BbWindHang::PostVerticesText(") != 1:
        raise SystemExit("text check: effects: the log lines")
    # tests
    if th.index("post pick: the nearest post") > th.index('std::printf("wind-hang-test: %d FAILED\\n", failures);'):
        raise SystemExit("text check: the test block comes before the verdict")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112T_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == HH and "PostBit = 1u << 15" not in cur:
            raise SystemExit("REFUSED: r112s must be applied")
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
            tmp = full + ".r112ttmp"
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
        tmp = full + ".r112ttmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


if __name__ == "__main__":
    main()
