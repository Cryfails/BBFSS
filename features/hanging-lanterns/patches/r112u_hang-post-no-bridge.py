# r112u_hang-post-no-bridge (FEATURE fix inside BB_WIND_HANG_POST; new knob BB_WIND_HANG_POST_GUARD, default 1). On top of r112t_hang-post-measure
# (build 70) and everything before it.
#
# WHY (owner 08:10: "in the small game windows the bridge is moving in the wind above the graveyard"; b70_s1.log, b70_s2.log, the difference sheet _rd_bridge.jpg)
#  The b70 logs say: 'Wind sway hang post (r112s): 7684 draws of 1 streams ... 1 judged, 1 swinging (base y -41.04, top y -35.38, 5.66 m tall); push 0.331 m'
#  and 'r112t ... 1 boxes of the stream, picked (c) 10.7 m from the camera'. The post push (BB_WIND_HANG_POST, r112s/r112t) takes every draw of a position
#  stream of 13642 vertices for a lamp post, and the pick is the one box of that stream in the ray traced scene: 5.66 m tall, a thing that is (or is shared
#  with) the bridge: its arc edge moves 0.24-0.35 m in the pictures. The rule 'a stream of 13642 vertices is a lamp post' was a guess from two pick pixels.
#
# THE FIX (a guard in front of the post push; nothing else changes)
#  The post push may move ONLY a hanging lantern (or its bracket arm). WindPostWord now refuses a stream (never pushes it: no word, as a stream whose
#  box does not fit) when, of ALL its boxes in the ray traced scene (every instance of the mesh; hang_find_boxes, one per mesh key):
#   - any box is wider than 1.5 m in x or in z ('wide': a bridge, a wall, a building);
#   - any box is taller than 3 m ('tall': a post, a tower, a bridge's pier);
#   - the stream has more than 3 boxes and they differ (the extents differ by more than 0.3 m: 'shared', one stream drawn as several different things:
#     architecture);
#   - (only when a lamp list is given; the rasterizer has no always-on list of the lamps' light positions at this hook, so it passes none and the rule
#     is NOT applied in this build, said in the logs) the picked box's lower end is not within 1 m of a lamp light ('no lamp').
#  The push of a post that passes is capped at 0.12 m: the gain a post word is given is min(BB_WIND_HANG_STATIC_GAIN, 0.12 / MaxAlong) (MaxAlong 0.4 m is
#  the largest of the push table), so the largest move of the lantern's bottom is 0.12 m whatever the live gain.
#  A line per refused stream (once per stream and reason): 'Wind sway hang post guard (r112u_hang-post-no-bridge): stream 0x... REFUSED (why): N boxes,
#  the box that decides x a..b (w m), y c..d (h m), z e..f'; once 'on' with the limits; a counter line every 600 frames with the refusals by reason.
#  BB_WIND_HANG_POST_GUARD=0 gives r112t's rule back (read once; unset or anything else = on).
#  CONSEQUENCE, said plainly: the scene box of the lamp POST that r112s found is 5.66 m tall and 2.15 m wide (r112s), over both limits, so the guard
#  refuses that stream too: with the guard on, BB_WIND_HANG_POST moves nothing in the graveyard unless the stream's boxes are all lantern-sized. The
#  owner's rule (only a lantern or its arm) wins over the post lean; the box shape the log prints decides whether the limits need to change.
#
# COST WHEN OFF: nothing changes with BB_WIND_HANG unset (WindPostWord is called only for a post draw, which needs BB_WIND_HANG; no shader line is touched:
# SPIR-V and the shader cache version are as in build 70). ON: one loop over the scene's boxes once a frame per post stream (cached with the pick), a
# min() on the gain. Memory: a PostGuard (about 48 bytes) in each of at most 64 post items.
#
# SHARED LINES TOUCHED: bbport_wind_hang.h (a block before r112s's posts' book, two members in the book, one in its item), vk_rasterizer_effects.cpp
# (WindPostWord: one line after the pick, one block before the height fit, one changed return, one block of the periodic line), test_wind_hang.cpp
# (a block inside r112t's), README.md (one sentence, one row).
#
# REVIEW FIX: HM1, HM2, E1 were 'rep' (deleted PostBook::written, Item::pick_frame and 'item.pick_frame = frame;'); now inserted after them.
# Use: python -I -X utf8 r112u_hang-post-no-bridge.py check | apply | revert
# Root: R112U_ROOT, else <tree>. Line ends kept. apply backs the originals up in r112u_backup next to this script.
import os, re, sys

ROOT = os.environ.get("R112U_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112u_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
EF = RV + "vk_rasterizer_effects.cpp"
HH = "engine/gpu/shim/bbport_wind_hang.h"
TH = "engine/tests/test_wind_hang.cpp"
RM = "README.md"

# ---- bbport_wind_hang.h ---------------------------------------------------------------------------------
HG_ANCHOR = r'''// ---- bbport (r112s_hang-bracket-move): the posts' book and lines'''
HG_BEFORE = r'''// ---- bbport (r112u_hang-post-no-bridge): the post push moves a hanging lantern only -----------------------------------------------------------
// b70: the post rule (every stream of 13642 vertices is a lamp post) pushed a stream that is, or is shared with, the BRIDGE (5.66 m tall in the scene):
// its arc edge moved 0.24-0.35 m (the owner, 08:10). BB_WIND_HANG_POST_GUARD (default on, read once; exactly 0 = r112t's rule): a stream is refused
// (never pushed) when any of its boxes in the ray traced scene is wider than PostGuardWide in x or z or taller than PostGuardTall, when it has more
// than PostGuardSharedMost boxes that differ by more than PostGuardSharedTol (one stream drawn as several different things: architecture), or, when
// the caller has the lamps' light positions, when the picked box's lower end is not within PostGuardLamp of one. A post that passes is pushed at most
// PostGuardPush m.
inline constexpr float PostGuardWide = 1.5f;             ///< m: a box wider than this in x or z is no lantern
inline constexpr float PostGuardTall = 3.0f;             ///< m: a box taller than this is no lantern
inline constexpr std::uint32_t PostGuardSharedMost = 3;  ///< boxes of a stream above which they must all be alike
inline constexpr float PostGuardSharedTol = 0.3f;        ///< m: how much alike (width and height each)
inline constexpr float PostGuardLamp = 1.0f;             ///< m: the lamp light's largest distance from the box's lower end
inline constexpr float PostGuardPush = 0.12f;            ///< m: the largest push of a post that passes

enum class PostRefuse : std::uint8_t { None = 0, Wide, Tall, Shared, NoLamp };
inline constexpr std::size_t PostRefuseKinds = 5;

struct PostGuard {
    PostRefuse why = PostRefuse::None;
    std::array<float, 6> box{}; ///< the box that decided (the first of a shared stream)
    std::uint32_t count = 0;    ///< boxes of the stream in the scene (usable ones)
};

[[nodiscard]] inline bool ParsePostGuard(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == '\0');
}

/// Read once.
[[nodiscard]] inline bool PostGuardOn() {
    static const bool on = ParsePostGuard(std::getenv("BB_WIND_HANG_POST_GUARD"));
    return on;
}

/// The gain a post word gets: the live gain, held to PostGuardPush over the push table's largest value (MaxAlong); a number that is none gives 0.
[[nodiscard]] inline float PostGain(float gain) {
    const float cap = PostGuardPush / W::MaxAlong;
    return std::isnan(gain) ? 0.0f : std::min(gain, cap);
}

[[nodiscard]] inline const char* PostRefuseName(PostRefuse why) {
    switch (why) {
    case PostRefuse::Wide:
        return "a box wider than the limit";
    case PostRefuse::Tall:
        return "a box taller than the limit";
    case PostRefuse::Shared:
        return "a shared stream: many boxes that differ";
    case PostRefuse::NoLamp:
        return "no lamp light near the box's lower end";
    default:
        return "none";
    }
}

/// The verdict on `stream` over every box of it in `boxes` (items with `stream`, `box`: least x, y, z, greatest x, y, z, y up). `pick` is the box
/// PickPost chose; `lamps` x, y, z triples (`lamp_count` of them; none: the lamp rule is not applied).
template <class Boxes>
[[nodiscard]] inline PostGuard PostGuardCheck(const Boxes& boxes, std::uint64_t stream, const PostPick& pick, const float* lamps,
                                              std::size_t lamp_count) {
    PostGuard g;
    if (stream == 0) {
        return g;
    }
    float wmin = 1.0e30f, wmax = -1.0e30f, hmin = 1.0e30f, hmax = -1.0e30f;
    std::array<float, 6> first{}, picked{};
    bool have_pick = false;
    for (const auto& b : boxes) {
        if (b.stream != stream) {
            continue;
        }
        bool usable = true;
        for (const float c : b.box) {
            usable = usable && std::isfinite(c) && std::fabs(c) < 1.0e5f;
        }
        if (!(usable && b.box[4] > b.box[1])) {
            continue;
        }
        const float w = std::max(b.box[3] - b.box[0], b.box[5] - b.box[2]);
        const float h = b.box[4] - b.box[1];
        if (g.count == 0) {
            first = b.box;
        }
        ++g.count;
        if (g.why == PostRefuse::None && w > PostGuardWide) {
            g.why = PostRefuse::Wide;
            g.box = b.box;
        } else if (g.why == PostRefuse::None && h > PostGuardTall) {
            g.why = PostRefuse::Tall;
            g.box = b.box;
        }
        wmin = std::min(wmin, w);
        wmax = std::max(wmax, w);
        hmin = std::min(hmin, h);
        hmax = std::max(hmax, h);
        if (pick.found && b.box[1] == pick.base && b.box[4] == pick.top) {
            picked = b.box;
            have_pick = true;
        }
    }
    if (g.why == PostRefuse::None && g.count > PostGuardSharedMost && (wmax - wmin > PostGuardSharedTol || hmax - hmin > PostGuardSharedTol)) {
        g.why = PostRefuse::Shared;
        g.box = first;
    }
    if (g.why == PostRefuse::None && have_pick && lamps != nullptr && lamp_count > 0) {
        bool near_lamp = false;
        for (std::size_t i = 0; i < lamp_count && !near_lamp; ++i) {
            const float x = lamps[i * 3], y = lamps[i * 3 + 1], z = lamps[i * 3 + 2];
            const float dx = std::clamp(x, picked[0], picked[3]) - x; // the nearest point of the box's lower face
            const float dz = std::clamp(z, picked[2], picked[5]) - z;
            const float dy = picked[1] - y;
            near_lamp = dx * dx + dy * dy + dz * dz <= PostGuardLamp * PostGuardLamp;
        }
        if (!near_lamp) {
            g.why = PostRefuse::NoLamp;
            g.box = picked;
        }
    }
    return g;
}

/// The line per refused stream.
inline void PostGuardText(std::uint64_t stream, const PostGuard& g, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind sway hang post guard (r112u_hang-post-no-bridge): stream 0x%llx REFUSED (%s): %u boxes of it in the scene; the box that decides: "
                  "x %.2f..%.2f (%.2f m), y %.2f..%.2f (%.2f m), z %.2f..%.2f (%.2f m); it is never pushed",
                  static_cast<unsigned long long>(stream), PostRefuseName(g.why), static_cast<unsigned>(g.count), double(g.box[0]), double(g.box[3]),
                  double(g.box[3] - g.box[0]), double(g.box[1]), double(g.box[4]), double(g.box[4] - g.box[1]), double(g.box[2]), double(g.box[5]),
                  double(g.box[5] - g.box[2]));
}

/// The once line.
inline void PostGuardOnceText(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind sway hang post guard (r112u_hang-post-no-bridge, BB_WIND_HANG_POST_GUARD): on: a post stream is pushed only when none of its "
                  "scene boxes is wider than %.1f m or taller than %.1f m, it has at most %u boxes or they are alike within %.1f m, (with a lamp list: "
                  "the lamp light is within %.1f m of the box's lower end; this build gives no lamp list, so that rule is not applied); the push is "
                  "at most %.2f m (gain at most %.2f)",
                  double(PostGuardWide), double(PostGuardTall), static_cast<unsigned>(PostGuardSharedMost), double(PostGuardSharedTol),
                  double(PostGuardLamp), double(PostGuardPush), double(PostGuardPush / W::MaxAlong));
}

'''

HM1 = r'''    std::uint64_t written = 0;   ///< bbport (r112t): times the CPU wrote the slot's keys from a box
'''
HM1N = r'''    std::uint64_t refused = 0;         ///< bbport (r112u): post draws given no word by the guard
    std::uint64_t refused_streams = 0; ///< bbport (r112u): streams refused (once per stream and reason)
    std::array<std::uint64_t, PostRefuseKinds> by_reason{}; ///< bbport (r112u): refused draws by reason (index PostRefuse)
    bool guard_said = false;           ///< bbport (r112u): the once line was written
'''
HM2 = r'''        std::uint64_t pick_frame = ~0ull;
'''
HM2N = r'''        PostGuard guard;            ///< bbport (r112u): the guard's verdict of pick_frame
        PostRefuse refused = PostRefuse::None; ///< bbport (r112u): the reason the last refusal was logged for
'''

HL_ANCHOR = r'''/// bbport (r112t_hang-post-measure): the second periodic line (the box the keys come from).'''
HL_BEFORE = r'''/// bbport (r112u_hang-post-no-bridge): the third periodic line (the guard's counters).
inline void PostGuardLineText(const PostBook& book, char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    const auto at = [&](PostRefuse why) { return n(book.by_reason[static_cast<std::size_t>(why)]); };
    std::snprintf(out, size,
                  "Wind sway hang post guard (r112u): %llu post draws refused of %llu (%llu streams): wide %llu, tall %llu, shared %llu, no lamp %llu; "
                  "the push of a post is at most %.2f m (lamp rule: no lamp list in this build)",
                  n(book.refused), n(book.draws), n(book.refused_streams), at(PostRefuse::Wide), at(PostRefuse::Tall), at(PostRefuse::Shared),
                  at(PostRefuse::NoLamp), double(PostGuardPush));
}

'''

# ---- vk_rasterizer_effects.cpp ---------------------------------------------------------------------------
E1 = r'''        item.pick_frame = frame;
'''
E1N = r'''        item.guard = BbWindHang::PostGuardOn() ? BbWindHang::PostGuardCheck(hang_find_boxes.All(), positions, item.pick, nullptr, 0)
                                               : BbWindHang::PostGuard{}; // bbport (r112u_hang-post-no-bridge): no lamp list here, see the once line
'''
E2 = r'''    const float post_height = pick.top - pick.base;
'''
E2P = r'''    if (BbWindHang::PostGuardOn()) { // bbport (r112u_hang-post-no-bridge): only a hanging lantern is pushed, never the bridge or a post
        if (!hang_post.guard_said) {
            hang_post.guard_said = true;
            char guard_once[640];
            BbWindHang::PostGuardOnceText(guard_once, sizeof(guard_once));
            BbReport::Printf("%s\n", guard_once);
        }
        if (item.guard.why != BbWindHang::PostRefuse::None) {
            ++hang_post.refused;
            ++hang_post.by_reason[static_cast<std::size_t>(item.guard.why)];
            if (item.refused != item.guard.why) { // one line per stream and reason
                item.refused = item.guard.why;
                ++hang_post.refused_streams;
                char guard_line[640];
                BbWindHang::PostGuardText(positions, item.guard, guard_line, sizeof(guard_line));
                BbReport::Printf("%s\n", guard_line);
            }
            return 0;
        }
        item.refused = BbWindHang::PostRefuse::None;
    }
'''
E3 = r'''    return BbWindHang::PostWord(frame_slot, view, slot, BbWindHangFind::SameRamp(ramp, WindHangGainNow(), 1.0f, true));'''
E3N = r'''    const float post_gain = BbWindHang::PostGuardOn() ? BbWindHang::PostGain(WindHangGainNow()) : WindHangGainNow(); // bbport (r112u): a post moves 0.12 m at most
    return BbWindHang::PostWord(frame_slot, view, slot, BbWindHangFind::SameRamp(ramp, post_gain, 1.0f, true));'''
E4 = r'''            BbReport::Printf("%s\n", post_box_line);
'''
E4P = r'''            if (BbWindHang::PostGuardOn()) { // bbport (r112u_hang-post-no-bridge)
                char post_guard_line[640];
                BbWindHang::PostGuardLineText(hang_post, post_guard_line, sizeof(post_guard_line));
                BbReport::Printf("%s\n", post_guard_line);
            }
'''

# ---- test ------------------------------------------------------------------------------------------------
T1 = r'''               "post box line: the pick");
'''
T1P = r'''        // bbport (r112u_hang-post-no-bridge): the guard
        Expect(H::ParsePostGuard(nullptr) && H::ParsePostGuard("") && H::ParsePostGuard("1") && !H::ParsePostGuard("0") && H::ParsePostGuard("00"),
               "post guard: the knob is on unless exactly 0");
        Expect(std::fabs(H::PostGain(0.2f) - 0.2f) < 1e-6f && std::fabs(H::PostGain(1.0f) - 0.3f) < 1e-6f && H::PostGain(std::nanf("")) == 0.0f &&
                   std::fabs(H::PostGain(1.0f) * W::MaxAlong - H::PostGuardPush) < 1e-6f,
               "post guard: the gain is held so that the push is at most 0.12 m");
        const std::vector<TestBox> guard_boxes{
            {0x5000, {0.0f, -41.0f, 0.0f, 12.0f, -35.4f, 3.0f}, 'c'},  // a bridge: 12 m wide
            {0x5001, {0.0f, 0.0f, 0.0f, 1.0f, 3.5f, 1.0f}, 'c'},        // 1 m wide, 3.5 m tall
            {0x5002, {0.0f, 2.0f, 0.0f, 0.4f, 2.9f, 0.4f}, 'c'},        // a lantern
            {0x5003, {0.0f, 0.0f, 0.0f, 0.4f, 1.0f, 0.4f}, 'c'},        // four boxes that differ: architecture
            {0x5003, {5.0f, 0.0f, 0.0f, 5.4f, 1.5f, 0.4f}, 'c'},
            {0x5003, {9.0f, 0.0f, 0.0f, 9.4f, 1.2f, 0.4f}, 'c'},
            {0x5003, {13.0f, 0.0f, 0.0f, 13.4f, 1.0f, 0.4f}, 'c'},
            {0x5004, {0.0f, 2.0f, 0.0f, 0.4f, 2.9f, 0.4f}, 'c'},        // four lanterns alike
            {0x5004, {5.0f, 2.1f, 0.0f, 5.4f, 3.0f, 0.4f}, 'c'},
            {0x5004, {9.0f, 2.0f, 3.0f, 9.4f, 2.9f, 3.4f}, 'c'},
            {0x5004, {13.0f, 1.9f, 0.0f, 13.4f, 2.8f, 0.4f}, 'c'},
            {0x5005, {0.0f, 2.0f, 0.0f, 0.4f, 2.9f, 0.4f}, 'c'},        // three that differ: few enough
            {0x5005, {5.0f, 0.0f, 0.0f, 5.4f, 1.5f, 0.4f}, 'c'},
            {0x5005, {9.0f, 0.0f, 0.0f, 9.4f, 1.0f, 0.4f}, 'c'},
            {0x5006, {0.0f, 2.0f, 0.0f, 1.6f, 2.9f, 0.4f}, 'c'},        // 1.6 m wide
            {0x5006, {0.0f, 2.0f, 0.0f, 0.4f, 2.9f, 0.4f}, 'v'},
        };
        const auto guard_of = [&](std::uint64_t stream, const float* lamps, std::size_t lamp_count) {
            return H::PostGuardCheck(guard_boxes, stream, H::PickPost(guard_boxes, stream, nullptr), lamps, lamp_count);
        };
        const H::PostGuard bridge = guard_of(0x5000, nullptr, 0);
        Expect(bridge.why == H::PostRefuse::Wide && bridge.count == 1 && std::fabs(bridge.box[3] - 12.0f) < 1e-4f, "post guard: a 12 m wide box is refused as wide");
        Expect(guard_of(0x5001, nullptr, 0).why == H::PostRefuse::Tall, "post guard: a 3.5 m tall box is refused as tall");
        Expect(guard_of(0x5002, nullptr, 0).why == H::PostRefuse::None && guard_of(0x5002, nullptr, 0).count == 1, "post guard: a lantern passes");
        Expect(guard_of(0x5003, nullptr, 0).why == H::PostRefuse::Shared && guard_of(0x5003, nullptr, 0).count == 4,
               "post guard: four boxes that differ are a shared stream");
        Expect(guard_of(0x5004, nullptr, 0).why == H::PostRefuse::None && guard_of(0x5004, nullptr, 0).count == 4, "post guard: four alike boxes pass");
        Expect(guard_of(0x5005, nullptr, 0).why == H::PostRefuse::None, "post guard: three boxes that differ are not yet a shared stream");
        Expect(guard_of(0x5006, nullptr, 0).why == H::PostRefuse::Wide, "post guard: ANY box of the stream over the limit refuses it");
        Expect(guard_of(0x9999, nullptr, 0).why == H::PostRefuse::None && guard_of(0x9999, nullptr, 0).count == 0 &&
                   H::PostGuardCheck(guard_boxes, 0, H::PostPick{}, nullptr, 0).why == H::PostRefuse::None,
               "post guard: no box, stream 0: nothing to refuse");
        const float near_lamp[3] = {0.2f, 2.5f, 0.2f}, far_lamp[3] = {0.2f, 5.0f, 0.2f}, below_lamp[3] = {0.2f, 1.2f, 0.2f};
        Expect(guard_of(0x5002, near_lamp, 1).why == H::PostRefuse::None && guard_of(0x5002, below_lamp, 1).why == H::PostRefuse::None &&
                   guard_of(0x5002, far_lamp, 1).why == H::PostRefuse::NoLamp,
               "post guard: the lamp rule: a light within 1 m of the box's lower end passes, one 3 m above refuses, none given: not applied");
        Expect(guard_of(0x5000, near_lamp, 1).why == H::PostRefuse::Wide, "post guard: the size rule comes before the lamp rule");
        char guard_text[704];
        H::PostGuardText(0x5000, bridge, guard_text, sizeof(guard_text));
        Expect(std::strstr(guard_text, "stream 0x5000 REFUSED (a box wider than the limit): 1 boxes") != nullptr &&
                   std::strstr(guard_text, "x 0.00..12.00 (12.00 m)") != nullptr && std::strstr(guard_text, "never pushed") != nullptr,
               "post guard: the line per refused stream");
        H::PostGuardOnceText(guard_text, sizeof(guard_text));
        Expect(std::strstr(guard_text, "wider than 1.5 m or taller than 3.0 m") != nullptr && std::strstr(guard_text, "at most 0.12 m (gain at most 0.30)") != nullptr,
               "post guard: the once line");
        H::PostBook guard_book;
        guard_book.draws = 9;
        guard_book.refused = 5;
        guard_book.refused_streams = 2;
        guard_book.by_reason[static_cast<std::size_t>(H::PostRefuse::Wide)] = 4;
        guard_book.by_reason[static_cast<std::size_t>(H::PostRefuse::Tall)] = 1;
        H::PostGuardLineText(guard_book, guard_text, sizeof(guard_text));
        Expect(std::strstr(guard_text, "5 post draws refused of 9 (2 streams): wide 4, tall 1, shared 0, no lamp 0") != nullptr,
               "post guard: the counter line");
'''

# ---- README ----------------------------------------------------------------------------------------------
M1 = r'''Costs nothing with `BB_WIND_HANG` unset; with it, 8 operations a vertex of the sway shaders. |'''
M1N = r'''Costs nothing with `BB_WIND_HANG` unset; with it, 8 operations a vertex of the sway shaders. r112u: see `BB_WIND_HANG_POST_GUARD` (the post rule moved the bridge; now only a lantern-sized stream moves, 0.12 m at most). |
| `BB_WIND_HANG_POST_GUARD` | Part of `BB_WIND_HANG_POST` (r112u; read once; default on, exactly `0` = r112t's rule). The post push may move only a hanging lantern or its bracket arm: in the graveyard (build 70) it moved the BRIDGE (a stream of 13642 vertices with a 5.66 m tall scene box; its arc edge moved 0.24-0.35 m). A stream is refused (no word, never pushed) when ANY of its boxes in the ray traced scene is wider than 1.5 m in x or z or taller than 3 m, or when it has more than 3 boxes that differ by more than 0.3 m in width or height (one stream drawn as several different things: architecture); a lamp rule (the picked box's lower end within 1 m of a lamp light) is written and unit-tested but this build passes no lamp list, so it is not applied. A stream that passes is pushed at most 0.12 m (the gain is held to 0.12 / 0.4 of the push table's largest value). The lamp post's own scene box (5.66 m x 2.15 m) is over both size limits, so with the guard on the post does not lean and nothing moves unless a stream's boxes are all lantern-sized. Log: once `Wind sway hang post guard (r112u_hang-post-no-bridge, ...)`, one line per refused stream with its reason and box, and a counter line every 600 frames. Costs nothing with `BB_WIND_HANG` unset; with it one loop over the scene's boxes a frame per post stream | on |'''

EDITS = {
HH: [
('ins', HG_ANCHOR, HG_BEFORE, ""),
('ins', HM1, "", HM1N),
('ins', HM2, "", HM2N),
('ins', HL_ANCHOR, HL_BEFORE, ""),
],
EF: [
('ins', E1, "", E1N),
('ins', E2, E2P, ""),
('rep', E3, "", E3N),
('ins', E4, "", E4P),
],
TH: [
('ins', T1, "", T1P),
],
RM: [
('rep', M1, "", M1N),
],
}
# T1 anchors the END of the Expect call: the block goes after it (ins: before text, anchor, after text)

ORDER = (HH, EF, TH, RM)


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


CPP = (HH, EF, TH)


def text_checks(texts, olds):
    """The ties a compiler cannot check."""
    hh, ef, th = (texts[p] for p in CPP)
    for path in CPP:
        if balance(texts[path]) != balance(olds[path]):
            raise SystemExit("text check: %s: braces, parens or brackets changed by %r" %
                             (path, tuple(a - b for a, b in zip(balance(texts[path]), balance(olds[path])))))
    for block in (HG_BEFORE, HM1N, HM2N, HL_BEFORE, E1N, E2P, E3N, E4P, T1P, M1N):
        try:
            block.encode("ascii")
        except UnicodeEncodeError:
            raise SystemExit("text check: a non-ASCII character in an inserted block: %r" % block[:60])
        if "\t" in block:
            raise SystemExit("text check: a tab in an inserted block: %r" % block[:60])
    for block in (HG_BEFORE, HL_BEFORE, E2P, E4P, T1P):
        if balance(block) != (0, 0, 0):
            raise SystemExit("text check: an inserted block does not balance: %r %r" % (block[:60], balance(block)))
    # review fix: the three anchors the blocks go after must survive (a 'rep' had deleted written, pick_frame and its assignment)
    for keep, where in ((HM1, hh), (HM2, hh), (E1, ef)):
        if where.count(keep) != 1:
            raise SystemExit("text check: an anchor line was lost: %r" % keep[:60])
    # header order: PostPick, then the guard (uses PostPick), then the book (uses PostGuard, PostRefuse), the line after the book
    if not (hh.index("struct PostPick {") < hh.index("struct PostGuard {") < hh.index("class PostBook {") < hh.index("inline void PostGuardLineText(")
            < hh.index("inline void PostBoxLineText(") < hh.index("inline void PostOnceText(")):
        raise SystemExit("text check: header order (PostPick, PostGuard, PostBook, the guard line, the box line, the once text)")
    for name in ("PostGuardCheck(", "PostGuardText(", "PostGuardOnceText(", "PostGuardLineText(", "PostGain("):
        if hh.count("inline void " + name) + hh.count("inline PostGuard " + name) + hh.count("inline float " + name) == 0:
            raise SystemExit("text check: header lacks %s" % name)
    # rasterizer: guard computed with the pick (once a frame), used before the height fit, the gain held, the line printed
    if not (ef.index("u32 Rasterizer::WindPostWord(") < ef.index("item.guard = ") < ef.index("if (item.guard.why != BbWindHang::PostRefuse::None)")
            < ef.index("const float post_height = pick.top - pick.base;") < ef.index("BbWindHang::PostGain(WindHangGainNow())")):
        raise SystemExit("text check: effects: order of the guard in WindPostWord")
    if ef.count("BbWindHang::PostGuardLineText(") != 1 or ef.count("BbWindHang::PostGuardText(") != 1 or ef.count("BbWindHang::PostGuardOnceText(") != 1:
        raise SystemExit("text check: effects: the log lines")
    if th.index("post guard: the counter line") > th.index('std::printf("wind-hang-test: %d FAILED\\n", failures);'):
        raise SystemExit("text check: the test block comes before the verdict")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112U_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == HH and "PostPickTie" not in cur:
            raise SystemExit("REFUSED: r112t must be applied")
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
            tmp = full + ".r112utmp"
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
        tmp = full + ".r112utmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


if __name__ == "__main__":
    main()
