# r62m_cutout-name-blocker: TOOL (test aid; marked TOOL: it goes to the test tools branch with r62l's TOOL part, not to a feature
# branch) that NAMES what blocks the lamp light of the lit and shadowed pixels of the cut-out lamp shadows (r62k/r62l), on top of
# r62l (build 47). Only in the CARDS builds of the lamp pass (BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1); with the knobs off nothing
# of it exists (no CARDS pipeline, no counters buffer: CardLampsLine returns at once without card_set_layout). No new knob: it is a
# part of the r62k/r62l lit patch counters, which already run only on the counted pixels (one pixel in 64 of one pass in 16).
#
# Why (build 47, r62l): the split view shows a clear checkerboard of ~15 % darker tiles on the dream house's left bookshelf near the
# lantern: 1147 px lit and shadowed, 0 % on a card, 0 % with the blocker within 10 cm, mean blocker 1.4 m: REAL lamp shadows of
# some cut-out between the lantern and the shelf, but WHICH cut-out (the lantern's own cage, its hook, a chain, a plant, the shelf's
# tracery) nobody could say. The sewer do-nothing place read 192 such pixels with 0 % on a card and 0 strict drops (it should read 0).
#
# What this patch does (CARDS builds only):
#  1. The blocker book: of the lit-and-shadowed counted pixels (cardLit's "lit && top_card"), the card instance that blocked the ray
#     to the strongest lamp is entered in a small table in the counters buffer (12 entries, linear probing on the card slot, all
#     atomics): the pixels, the bounding box of the blocking hits (view space, cm), the sum of the hit-to-lamp and hit-to-surface
#     distances, and how many of those hits the GAME's own rule would keep too (a plain re-read at the hit's barycentrics and level:
#     0 % there means the lamp rule's thicker texel made the blocker). rt_cards.glsl cardTraceShadow remembers the slot, the primitive,
#     the barycentrics and the level of the hit it keeps (card_kept_*); point_shadow_ray.comp ray() turns them into the hit's view
#     space place and main copies them with top_card (blockerTop).
#  2. The host names the slots: RtShadow::CardBlockerOf(slot) finds the entry that carries the slot as its instance custom index and
#     gives its mesh+shader key, its card pixel shader hash and pass, rule (op, reference, layer), triangles, vertices, skinned,
#     dynamic, instance, and the world box (the sun VSM's, else the still check's bounds) with its centre in view space. The window
#     line of r62k/r62l is followed by 'Foliage lamp shadows (r62m) blocker book <w>:' and, for the four cards with the most pixels,
#     two lines each: '... blocker <w> #n: <px> (<share> %), game keeps <%>, hit-lamp <m>, hit-surface <m> (<where>), slot ... key ...
#     ps ... tris, verts, size' and '... #n where: hits right/up/ahead ranges, box centre in view, world box, rule'. <where> says
#     'lamp-side' (the hits lie within 0.3 m of the lamp: its own cage, hook or chain), 'surface-side' (within 10 cm of the surface:
#     the surface's own neighbourhood) or 'between'.
#  The window is the same as r62k's lit line (every change of the live knobs file and once after 240 frames); counts since the last
#  window (the boxes are since the start).
#
# Files: rt_card_layers_layout.h (book layout), rt_cards.glsl (card_kept_*), point_shadow_ray.comp, vk_point_shadow.cpp (buffer sizes,
# the lines), vk_rt_shadow.h / vk_rt_shadow.cpp (CardBlockerOf), README.md (a sentence in the SPLIT row). No new file, no CMake change.
# Revert r62m before r62l.
# Cost: off 0. On: per lit-and-shadowed counted pixel (a few hundred in a counted pass): up to 12 atomicCompSwap probes, 9 atomics and one
# layer read: far under 0.01 ms. Memory: the counters buffer 288 -> 872 bytes, two buffers.
# Not compiled here (no clang++); the C++ spots are named in the hand-off.
#
# Use: python -I -X utf8 r62m_cutout-name-blocker.py check | apply | revert
# Root: R62M_CUTOUT_NAME_BLOCKER_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in r62m_backup.
import os, sys

ROOT = os.environ.get("R62M_CUTOUT_NAME_BLOCKER_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r62m_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
G = HS + "rt_cards.glsl"
S = HS + "point_shadow_ray.comp"
L = HS + "rt_card_layers_layout.h"
C = RV + "vk_point_shadow.cpp"
RH = RV + "vk_rt_shadow.h"
RC = RV + "vk_rt_shadow.cpp"
R = "README.md"
FILES = (G, S, L, C, RH, RC, R)

EDITS = {
L: [
("#define CARD_LAMP_COUNTERS 72 // (r62h: was 16; r62j: was 32 then 48; r62k: was 48 then 64; r62l: was 64)\n",
 r"""#define CARD_LAMP_COUNTERS 72 // (r62h: was 16; r62j: was 32 then 48; r62k: was 48 then 64; r62l: was 64)
// bbport (r62m_cutout-name-blocker) TOOL: the blocker book follows the counters (the counters buffer is CARD_LAMP_BUFFER_WORDS words
// long; the host differences only the first CARD_LAMP_COUNTERS): CARD_BOOK_ENTRIES entries of CARD_BOOK_WORDS words at CARD_LAMP_BOOK,
// one for each card slot that blocked the lamp ray of a lit and shadowed counted pixel (point_shadow_ray.comp bookAdd): word 0 the card
// slot (0: empty), 1 the pixels, 2-4 the hits' smallest x, y, z as 6400 minus (cm + 3200) in view space (atomicMax keeps them), 5-7 the
// largest, 8 the sum of the hit-to-lamp distances (cm, each at most 3000), 9 the sum of the hit-to-surface distances (cm), 10 the hits the
// game's own rule keeps too, 11 spare. Then the pixels whose blocker had no card slot and those that found the table full.
#define CARD_LAMP_BOOK 72
#define CARD_BOOK_ENTRIES 12
#define CARD_BOOK_WORDS 12
#define CARD_LAMP_BOOK_NO_SLOT 216
#define CARD_LAMP_BOOK_FULL 217
#define CARD_LAMP_BUFFER_WORDS 218
"""),
],
G: [
("uint card_strict_drops = 0u;\n",
 r"""uint card_strict_drops = 0u;
// bbport (r62m_cutout-name-blocker) TOOL: the hit a cardTraceShadow ray kept last: its card slot, BLAS primitive, barycentrics and the
// level it was read at (only meaningful when that ray ended CARD_RAY_KEPT; the lamp pass's blocker book names the slot)
uint card_kept_slot = 0u;
uint card_kept_prim = 0u;
vec2 card_kept_bary = vec2(0.0);
float card_kept_lod = 0.0;
"""),
("                r.how = CARD_RAY_KEPT;\n                block = true;\n",
 r"""                r.how = CARD_RAY_KEPT;
                block = true;
                card_kept_slot = hit_slot; // bbport (r62m_cutout-name-blocker) TOOL
                card_kept_prim = hit_primitive;
                card_kept_bary = hit_bary;
                card_kept_lod = lod;
"""),
],
S: [
("bool proof_quiet = false;\n",
 r"""bool proof_quiet = false;
// bbport (r62m_cutout-name-blocker) TOOL: the blocker book. ray_card_*: the card hit that stopped the last ray() (slot, BLAS primitive,
// barycentrics, level, place in view space; valid only when ray_card_kept); top_blk_*: the same for the ray to the pixel's strongest
// lamp (blockerTop copies them with top_card). bookAdd enters a lit and shadowed counted pixel's blocker in the book of the counters
// buffer (rt_card_layers_layout.h CARD_LAMP_BOOK): the card slot's entry gets the pixel, the hit's box, the hit-to-lamp and
// hit-to-surface distances, and whether the game's own rule keeps the texel there.
uint ray_card_slot = 0u;
uint ray_card_prim = 0u;
vec2 ray_card_bary = vec2(0.0);
float ray_card_lod = 0.0;
vec3 ray_card_at = vec3(0.0);
uint top_blk_slot = 0u;
uint top_blk_prim = 0u;
vec2 top_blk_bary = vec2(0.0);
float top_blk_lod = 0.0;
vec3 top_blk_at = vec3(0.0);
void blockerFromRay(vec3 hit_at) {
    ray_card_slot = card_kept_slot;
    ray_card_prim = card_kept_prim;
    ray_card_bary = card_kept_bary;
    ray_card_lod = card_kept_lod;
    ray_card_at = hit_at;
}
void blockerTop() {
    top_blk_slot = ray_card_slot;
    top_blk_prim = ray_card_prim;
    top_blk_bary = ray_card_bary;
    top_blk_lod = ray_card_lod;
    top_blk_at = ray_card_at;
}
void bookAdd(float lamp_m, float went_m) {
    const uint slot = top_blk_slot;
    if (slot == 0u) {
        atomicAdd(card_counts[CARD_LAMP_BOOK_NO_SLOT], 1u);
        return;
    }
    uint at = 0u;
    bool found = false;
    for (uint k = 0u; k < uint(CARD_BOOK_ENTRIES) && !found; ++k) {
        const uint entry = uint(CARD_LAMP_BOOK) + ((slot + k) % uint(CARD_BOOK_ENTRIES)) * uint(CARD_BOOK_WORDS);
        const uint was = atomicCompSwap(card_counts[entry], 0u, slot);
        if (was == 0u || was == slot) {
            at = entry;
            found = true;
        }
    }
    if (!found) {
        atomicAdd(card_counts[CARD_LAMP_BOOK_FULL], 1u);
        return;
    }
    const uvec3 cm = uvec3(clamp(top_blk_at * 100.0 + 3200.0, vec3(0.0), vec3(6400.0)));
    atomicAdd(card_counts[at + 1u], 1u);
    for (uint a = 0u; a < 3u; ++a) {
        atomicMax(card_counts[at + 2u + a], 6400u - cm[a]);
        atomicMax(card_counts[at + 5u + a], cm[a]);
    }
    atomicAdd(card_counts[at + 8u], uint(clamp(lamp_m, 0.0, 30.0) * 100.0));
    atomicAdd(card_counts[at + 9u], uint(clamp(went_m, 0.0, 30.0) * 100.0));
    // the game's own rule at the same hit and level (the ray's reference scale, dilation and wrap are reset: a plain read)
    if (cardTestLod(slot, top_blk_prim, top_blk_bary, top_blk_lod).status == CARD_KEPT) {
        atomicAdd(card_counts[at + 10u], 1u);
    }
}
"""),
("            if (went < 0.10) {\n                cardCount(CARD_LAMP_LIT_NEAR, 1u);\n            }\n",
 r"""            if (went < 0.10) {
                cardCount(CARD_LAMP_LIT_NEAR, 1u);
            }
            bookAdd(length(lamp_at - top_blk_at), went); // bbport (r62m_cutout-name-blocker) TOOL
"""),
("        ray_card_kept = card_hit.how == CARD_RAY_KEPT;\n",
 r"""        ray_card_kept = card_hit.how == CARD_RAY_KEPT;
        if (ray_card_kept && card_hit.t >= 0.0) { // bbport (r62m_cutout-name-blocker) TOOL
            blockerFromRay(origin + card_to / card_len * card_hit.t);
        }
"""),
("    ray_card_kept = hit.how == CARD_RAY_KEPT;\n",
 r"""    ray_card_kept = hit.how == CARD_RAY_KEPT;
    if (ray_card_kept && hit.t >= 0.0) { // bbport (r62m_cutout-name-blocker) TOOL
        blockerFromRay(origin + ray_to / ray_len * hit.t);
    }
"""),
("\n                            top_card = ray_card_kept; // bbport (r63_leaf-stage4)\n",
 "\n                            top_card = ray_card_kept; // bbport (r63_leaf-stage4)\n"
 "                            blockerTop(); // bbport (r62m_cutout-name-blocker) TOOL\n"),
("\n            top_card = ray_card_kept; // bbport (r63_leaf-stage4)\n",
 "\n            top_card = ray_card_kept; // bbport (r63_leaf-stage4)\n"
 "            blockerTop(); // bbport (r62m_cutout-name-blocker) TOOL\n"),
],
C: [
("static_assert(CARD_LAMP_LIT_NEAR == CARD_LAMP_LIT_SUM_DEPTH + 1 && CARD_LAMP_LIT_ON_CARD == CARD_LAMP_LIT_NEAR + 3 &&\n"
 "              CARD_LAMP_LIT_ON_CARD < CARD_LAMP_COUNTERS);\n",
 r"""static_assert(CARD_LAMP_LIT_NEAR == CARD_LAMP_LIT_SUM_DEPTH + 1 && CARD_LAMP_LIT_ON_CARD == CARD_LAMP_LIT_NEAR + 3 &&
              CARD_LAMP_LIT_ON_CARD < CARD_LAMP_COUNTERS);
// bbport (r62m_cutout-name-blocker) TOOL: the blocker book follows the counters in the buffer (rt_card_layers_layout.h)
static_assert(CARD_LAMP_BOOK == CARD_LAMP_COUNTERS && CARD_LAMP_BOOK_NO_SLOT == CARD_LAMP_BOOK + CARD_BOOK_ENTRIES * CARD_BOOK_WORDS &&
              CARD_LAMP_BOOK_FULL == CARD_LAMP_BOOK_NO_SLOT + 1 && CARD_LAMP_BUFFER_WORDS == CARD_LAMP_BOOK_FULL + 1);
"""),
("            instance, 0, CARD_LAMP_COUNTERS * sizeof(u32), VideoCore::MemoryType::DeviceLocal,\n",
 "            instance, 0, CARD_LAMP_BUFFER_WORDS * sizeof(u32), VideoCore::MemoryType::DeviceLocal, // bbport (r62m): the book too\n"),
("            instance, 0, CARD_LAMP_COUNTERS * sizeof(u32), VideoCore::MemoryType::HostCached,\n",
 "            instance, 0, CARD_LAMP_BUFFER_WORDS * sizeof(u32), VideoCore::MemoryType::HostCached,\n"),
("        if (card_readback->mapped_data.size() >= CARD_LAMP_COUNTERS * sizeof(u32)) {\n"
 "            std::memset(card_readback->mapped_data.data(), 0, CARD_LAMP_COUNTERS * sizeof(u32));\n",
 "        if (card_readback->mapped_data.size() >= CARD_LAMP_BUFFER_WORDS * sizeof(u32)) {\n"
 "            std::memset(card_readback->mapped_data.data(), 0, CARD_LAMP_BUFFER_WORDS * sizeof(u32));\n"),
("                    const vk::BufferCopy region{0, 0, CARD_LAMP_COUNTERS * sizeof(u32)};\n",
 "                    const vk::BufferCopy region{0, 0, CARD_LAMP_BUFFER_WORDS * sizeof(u32)}; // bbport (r62m): the book too\n"),
("// bbport (r62k_cutout-lit-fence): the window lines of the lit patch (point_shadow_ray.comp cardLit) and, with the proof view on, of what\n",
 r"""// bbport (r62m_cutout-name-blocker) TOOL: the blocker book's lines (point_shadow_ray.comp bookAdd; rt_card_layers_layout.h): the cards
// that blocked the lamp rays of the lit and shadowed pixels, with the most pixels first, each named by RtShadow::CardBlockerOf. `now` and
// `last` are the book's words as copied (the entries, then the pixels without a slot and with the table full); the pixels and the
// distances are since the last window, the hit boxes since the start. Two lines a card, at most four cards (a slot run keeps 300
// characters of a line).
using CardBook = std::array<u32, CARD_BOOK_ENTRIES * CARD_BOOK_WORDS + 2>;
static void CardBlockerLines(const CardBook& now, CardBook& last, const RtShadow& rt, const char* tag, double both) {
    struct Row {
        u32 at;
        u32 slot;
        double px, lamp_m, went_m, game;
    };
    std::array<Row, CARD_BOOK_ENTRIES> rows{};
    u32 used = 0;
    double total = 0.0;
    for (u32 i = 0; i < CARD_BOOK_ENTRIES; ++i) {
        const u32 at = i * CARD_BOOK_WORDS;
        const u32 slot = now[at];
        if (slot == 0) {
            continue;
        }
        const bool same = last[at] == slot;
        const auto diff = [&](u32 w) { return double(u32(now[at + w] - (same ? last[at + w] : 0u))); };
        const double px = diff(1);
        if (px > 0.0) {
            rows[used++] = Row{at, slot, px, diff(8) / px / 100.0, diff(9) / px / 100.0, diff(10)};
            total += px;
        }
    }
    const u32 no_slot = now[CARD_BOOK_ENTRIES * CARD_BOOK_WORDS] - last[CARD_BOOK_ENTRIES * CARD_BOOK_WORDS];
    const u32 full = now[CARD_BOOK_ENTRIES * CARD_BOOK_WORDS + 1] - last[CARD_BOOK_ENTRIES * CARD_BOOK_WORDS + 1];
    last = now;
    if (used == 0 && no_slot == 0 && full == 0) {
        return;
    }
    std::sort(rows.begin(), rows.begin() + used, [](const Row& a, const Row& b) { return a.px > b.px; });
    std::printf("Foliage lamp shadows (r62m) blocker book %s: %u cards named, %.0f counted px of %.0f lit+shadowed (no slot %u, table full %u)\n",
                tag, used, total, both, no_slot, full);
    for (u32 n = 0; n < used && n < 4; ++n) {
        const Row& row = rows[n];
        const RtShadow::CardBlockerInfo info = rt.CardBlockerOf(row.slot);
        const char* where = row.lamp_m < 0.3 ? "lamp-side" : row.went_m < 0.1 ? "surface-side" : "between";
        if (!info.found) {
            std::printf("Foliage lamp shadows (r62m) blocker %s #%u: %.0f px (%.0f %%), game keeps %.0f %%, hit-lamp %.2f m, hit-surface %.2f m (%s), "
                        "slot %u: no entry carries it any more\n",
                        tag, n + 1, row.px, 100.0 * row.px / std::max(total, 1.0), 100.0 * row.game / row.px, row.lamp_m, row.went_m,
                        where, row.slot);
        } else {
            std::printf("Foliage lamp shadows (r62m) blocker %s #%u: %.0f px (%.0f %%), game keeps %.0f %%, hit-lamp %.2f m, hit-surface %.2f m (%s), "
                        "slot %u key %016llx ps %016llx (%s pass), %u tris %u verts, %s%s%s, size %.2f x %.2f x %.2f m\n",
                        tag, n + 1, row.px, 100.0 * row.px / std::max(total, 1.0), 100.0 * row.game / row.px, row.lamp_m, row.went_m,
                        where, row.slot, static_cast<unsigned long long>(info.key), static_cast<unsigned long long>(info.ps),
                        info.camera_pass ? "camera" : "sun", info.triangles, info.vertices, info.skinned ? "skinned" : "static",
                        info.dynamic ? " moving" : "", info.instance ? " instance" : "", double(info.box[3] - info.box[0]),
                        double(info.box[4] - info.box[1]), double(info.box[5] - info.box[2]));
        }
        const auto lo = [&](u32 a) { return 32.0 - double(now[row.at + 2 + a]) / 100.0; };
        const auto hi = [&](u32 a) { return double(now[row.at + 5 + a]) / 100.0 - 32.0; };
        std::printf("Foliage lamp shadows (r62m) blocker %s #%u where: hits right %.1f..%.1f up %.1f..%.1f ahead %.1f..%.1f m; box centre in "
                    "view %.1f %.1f %.1f; world box %.1f %.1f %.1f to %.1f %.1f %.1f (%c); rule op %u ref %.3g layer %u\n",
                    tag, n + 1, lo(0), hi(0), lo(1), hi(1), lo(2), hi(2), double(info.centre_view[0]), double(info.centre_view[1]),
                    double(info.centre_view[2]), double(info.box[0]), double(info.box[1]), double(info.box[2]), double(info.box[3]),
                    double(info.box[4]), double(info.box[5]), info.box_src, info.op, double(info.reference), info.layer);
    }
}

// bbport (r62k_cutout-lit-fence): the window lines of the lit patch (point_shadow_ray.comp cardLit) and, with the proof view on, of what
"""),
("static void CardLitWindowLine(VideoCore::Buffer* readback) {\n",
 "static void CardLitWindowLine(VideoCore::Buffer* readback, const RtShadow& rt) { // bbport (r62m): rt names the blockers\n"),
("                share(d[CARD_LAMP_PROOF_FRONT_GAME_KEPT], d[CARD_LAMP_PROOF_FRONT_READS]), CardExtrasFromEnv().split);\n",
 r"""                share(d[CARD_LAMP_PROOF_FRONT_GAME_KEPT], d[CARD_LAMP_PROOF_FRONT_READS]), CardExtrasFromEnv().split);
    // bbport (r62m_cutout-name-blocker) TOOL: which cards blocked the lit and shadowed pixels
    static CardBook book_last{};
    CardBook book_now{};
    if (readback && readback->mapped_data.size() >= CARD_LAMP_BUFFER_WORDS * sizeof(u32)) {
        readback->Invalidate(CARD_LAMP_BOOK * sizeof(u32), sizeof(book_now));
        std::memcpy(book_now.data(), readback->mapped_data.data() + CARD_LAMP_BOOK * sizeof(u32), sizeof(book_now));
    }
    CardBlockerLines(book_now, book_last, rt, tag, both);
"""),
("        CardLitWindowLine(card_readback.get()); // bbport (r62k_cutout-lit-fence)\n",
 "        CardLitWindowLine(card_readback.get(), rt_shadow); // bbport (r62k_cutout-lit-fence; r62m: rt_shadow names the blockers)\n"),
],
RH: [
("    CardRowCounts TakeCardRowCounts() noexcept {\n        const CardRowCounts counts = card_row_counts;\n        card_row_counts = {};\n        return counts;\n    }\n",
 r"""    CardRowCounts TakeCardRowCounts() noexcept {
        const CardRowCounts counts = card_row_counts;
        card_row_counts = {};
        return counts;
    }
    // bbport (r62m_cutout-name-blocker, TOOL): what the card slot (an instance's custom index; the blocker book of the lamp pass)
    // belongs to: the entry's mesh+shader key (Entry::base), its card's pixel shader and pass, rule (op, reference, layer), size,
    // flags and world box (the sun VSM's, else the still check's bounds; box_src 'v', 's', 'c', '-' none), the box centre in view space.
    // found false: no entry carries the slot (any more). Scans `entries`: called a few times a test, from the lamp pass's window line.
    struct CardBlockerInfo {
        bool found = false;
        u64 key = 0, ps = 0, stream = 0;
        bool camera_pass = false, skinned = false, dynamic = false, instance = false;
        u32 triangles = 0, vertices = 0, op = 0, layer = 0;
        float reference = 0.0f;
        char box_src = '-';
        std::array<float, 6> box{};
        std::array<float, 3> centre_view{};
    };
    [[nodiscard]] CardBlockerInfo CardBlockerOf(u32 slot) const;
"""),
],
RC: [
("const char* RtShadow::CardClassNow(const Entry& entry) const noexcept {\n"
 "    return CardClassText(entry.skinned, entry.lone == LampLoneState::Lone,\n"
 "                         entry.lone == LampLoneState::Lone || entry.lone == LampLoneState::Sun);\n"
 "}\n",
 r"""const char* RtShadow::CardClassNow(const Entry& entry) const noexcept {
    return CardClassText(entry.skinned, entry.lone == LampLoneState::Lone,
                         entry.lone == LampLoneState::Lone || entry.lone == LampLoneState::Sun);
}

// bbport (r62m_cutout-name-blocker, TOOL): see the declaration.
RtShadow::CardBlockerInfo RtShadow::CardBlockerOf(u32 slot) const {
    CardBlockerInfo r;
    if (slot == 0) {
        return r;
    }
    for (const auto& item : entries) {
        const Entry* e = item.second.get();
        if (e == nullptr || !e->card_uv || CardCustomIndex(*e) != slot) {
            continue;
        }
        r.found = true;
        r.key = e->base;
        r.stream = e->stream;
        r.camera_pass = e->card_uv->uv.card.camera;
        r.ps = e->card_uv->uv.card.ps_hash;
        r.skinned = e->skinned;
        r.dynamic = e->dynamic;
        r.instance = e->instance;
        r.triangles = e->triangles;
        r.vertices = e->vertices;
        const u32 flags = e->card_uv->row[2];
        r.op = (flags >> CARD_ROW_OP_SHIFT) & 7u;
        r.layer = flags & u32(CARD_ROW_LAYER_MASK);
        r.reference = std::bit_cast<float>(e->card_uv->row[3]);
        if (e->has_box) {
            r.box = e->box;
            r.box_src = 'v';
        } else if (e->still_has_ref[1]) {
            r.box = e->still_ref[1];
            r.box_src = 's';
        } else if (e->still_has_ref[0]) {
            r.box = e->still_ref[0];
            r.box_src = 'c';
        }
        if (r.box_src != '-') {
            const auto view = camera_motion.CameraMatrices().view; // 3 rows of 4: view space = view * (world, 1)
            const std::array<float, 3> mid{0.5f * (r.box[0] + r.box[3]), 0.5f * (r.box[1] + r.box[4]),
                                           0.5f * (r.box[2] + r.box[5])};
            for (u32 i = 0; i < 3; ++i) {
                r.centre_view[i] = view[i * 4] * mid[0] + view[i * 4 + 1] * mid[1] + view[i * 4 + 2] * mid[2] + view[i * 4 + 3];
            }
        }
        break;
    }
    return r;
}
"""),
],
}

ROWS_OLD = "and how many have the blocker within 10 cm | `0` (off), `0` |"
ROWS_NEW = ("and how many have the blocker within 10 cm. (r62m) The same window then prints a blocker book: of the lit and shadowed pixels, the "
            "cards that blocked them, each named by its mesh key and pixel shader hash, size, and world box, with how far its hits lie from "
            "the lamp and from the surface and how often the game's own rule keeps the texel there too (`Foliage lamp shadows (r62m) "
            "blocker` lines) | `0` (off), `0` |")


def readme_edits(text):
    if text.count(ROWS_OLD) != 1 and text.count(ROWS_NEW) != 1:
        raise SystemExit("README.md: the BB_RT_CARD_LAMP_SPLIT row ending is there %d times, wanted 1 (r62l applied?)" % text.count(ROWS_OLD))
    return [(ROWS_OLD, ROWS_NEW)]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    return readme_edits(text) if path == R else EDITS[path]


def state_of(cur, eds, path):
    """'applied' or 'clean' for every edit, else refuse. A swap (new does not hold old) is applied when old is gone and
    new is there once; an insert (new holds old) when new is there once."""
    done = todo = 0
    for old, new in eds:
        n_old, n_new = cur.count(old), cur.count(new)
        holds = old in new
        if n_old == 1 and n_new == 0:
            todo += 1
        elif (holds and n_old == 1 and n_new == 1) or (not holds and n_old == 0 and n_new == 1):
            done += 1
        else:
            raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted once, none): %r"
                             % (path, n_old, n_new, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def inside_only(text, markers, flags, what):
    """Every line holding one of `markers` lies inside an #ifdef of `flags` (a set of names)."""
    stack = []
    for line in text.split("\n"):
        st = line.strip()
        if st.startswith("#ifdef") or st.startswith("#ifndef") or st.startswith("#if "):
            stack.append(st.startswith("#ifdef") and st.split()[1] in flags)
        elif st.startswith("#endif"):
            stack.pop()
        elif st.startswith("#else"):
            stack[-1] = False
        elif any(m in line for m in markers) and not any(stack):
            raise SystemExit("text check: %s: a line of r62m is outside its #ifdef: %r" % (what, line))


def text_checks(texts):
    g, s, l, c, rh, rc, r = (texts[p] for p in FILES)
    for want, n in (("blockerTop();", 2), ("blockerFromRay(", 3), ("bookAdd(", 2), ("void bookAdd(float lamp_m, float went_m) {", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    # every r62m line of the lamp shader lies in the CARDS builds
    inside_only(s, ("r62m", "blockerTop", "blockerFromRay", "bookAdd", "ray_card_slot", "top_blk_", "CARD_LAMP_BOOK", "CARD_BOOK_"),
                {"CARDS"}, S)
    inside_only(g, ("card_kept_",), {"CARD_TRACE_SHADOW"}, G)
    if g.count("card_kept_slot = hit_slot;") != 1:
        raise SystemExit("text check: rt_cards.glsl keeps the slot %d times" % g.count("card_kept_slot = hit_slot;"))
    for name in ("CARD_LAMP_BOOK 72", "CARD_BOOK_ENTRIES 12", "CARD_BOOK_WORDS 12", "CARD_LAMP_BOOK_NO_SLOT 216",
                 "CARD_LAMP_BOOK_FULL 217", "CARD_LAMP_BUFFER_WORDS 218"):
        if l.count("#define " + name + "\n") != 1:
            raise SystemExit("text check: %s lacks #define %s" % (L, name))
    if 72 + 12 * 12 != 216:
        raise SystemExit("text check: the book does not end at 216")
    if c.count("CARD_LAMP_COUNTERS * sizeof(u32)") != 0 or c.count("CARD_LAMP_BUFFER_WORDS * sizeof(u32)") != 6:
        raise SystemExit("text check: %s sizes: COUNTERS %d times, BUFFER_WORDS %d times" % (
            C, c.count("CARD_LAMP_COUNTERS * sizeof(u32)"), c.count("CARD_LAMP_BUFFER_WORDS * sizeof(u32)")))
    if c.count("static void CardLitWindowLine(VideoCore::Buffer* readback, const RtShadow& rt)") != 1 \
       or c.count("CardLitWindowLine(card_readback.get(), rt_shadow);") != 1 or c.count("CardBlockerLines(book_now, book_last, rt, tag, both);") != 1:
        raise SystemExit("text check: the window line wiring")
    if rh.count("[[nodiscard]] CardBlockerInfo CardBlockerOf(u32 slot) const;") != 1 or rc.count("RtShadow::CardBlockerInfo RtShadow::CardBlockerOf(u32 slot) const {") != 1:
        raise SystemExit("text check: CardBlockerOf")
    if r.count("(r62m) The same window then prints a blocker book") != 1:
        raise SystemExit("text check: README")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R62M_CUTOUT_NAME_BLOCKER_ROOT)" % ROOT)
    for path in FILES:  # apply writes nothing when a file is missing
        if not os.path.isfile(os.path.join(ROOT, path)):
            raise SystemExit("%s is missing" % path)
    plan = []
    for path in FILES:
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in eds:
                cur = cur.replace(old, new)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("REFUSED: already applied")
            sys.exit(1)
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r62mtmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for old, new in reversed(eds):
            cur = cur.replace(new, old, 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r62mtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
