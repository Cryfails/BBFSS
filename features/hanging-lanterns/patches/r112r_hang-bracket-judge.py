# r112r_hang-bracket-judge (FEATURE fix BB_WIND_HANG_BOX_NOPAL + TOOL parts: the proof tint on every hang bit and in the recompiler too,
# BB_WIND_HANG_PROOF_HIDE, the tinted-draw lines and the pick's cross-reference; all behind BB_WIND_HANG=1, off with it): on top of
# r112q_hang-bracket-route and everything through build 65. Lane of wave 55; the other lane (r120c) touches test camera code only.
#
# WHAT b65 SHOWED (b65_reports.txt, b65_s4.log, b65_s5.log) AND WHAT THE CODE SAYS (read, nothing run)
#  - Route line of vs:ps e859b6d9:e21e283a (s4): 'streams: 0x1146fdbb90 no scene box, judge none dev 0 mm, book moving (why 1, box 0)' for both its
#    streams, 'FIRST BREAK: a standing verdict holds the stream as moving'. The census line of the same run says '35 refused streams ... gpu 22+0,
#    unmapped 0+0, short 0+0, pivot 10+0, content moved 1+0 ... 33 judged, 2 turned away': the 33 + 2 are all the refused streams, and the two
#    turned away are in NONE of the five kinds the line counts. They are the two e859b6d9 streams: WindHangVerdict reads only a palette of Skeleton
#    size (stride 16, 13 to 341 bones: Motion::ClassifyBuffer); a bracket lantern's palette is a SMALL one (a few bones), so no palette is found,
#    palette_size is 0, BbWindHangStill::Book::Judge says Never / Why::NoPalette (bones 0) and BbWindHangGpu::BoxJudgeable answers false for
#    e->bones == 0 (r112p: 'never a palette with no bones or none bound'). So r112p's box judge never sees them: no judge, why 1 (unread), box 0,
#    and BB_WIND_HANG_BOX_RETRY (r112q) has nothing to retry because it only re-judges streams that were box-judged (Entry::box_only).
#    FIX (FEATURE, BB_WIND_HANG_BOX_NOPAL, default on, 0 = r112q): a stream refused for having NO skeleton-size palette (Kind::NoPal) goes to the
#    box judge as well (BoxJudgeable's new argument), at most NopalMost = 48 such streams (Census::NopalRoom: the judge's table and the sway slots
#    stay free), pushed like every box-judged stream (one-bone stand-in, r112h's NEAR rule keeps the hunter's gear off, the indoor rule decides
#    after the judge, a real mover is refused by the box: 20 mm / 250 mm as before). The census line now counts three more kinds (no palette,
#    character, other) so that the next log PROVES which kind the lantern's streams are.
#  - With FORCE=all e859b6d9 got 'forced 238 ... delivered 100%' and no cyan and no lean; but the route lines of windows 3 and 4 say that NO
#    draw of e859b6d9 reached the Motion block after the camera looked up: the visible lantern (about 1117,677 of 1280x720) is drawn by another
#    vertex shader, and the hunter (vs c77a0097 etc., forced 1458 words in the proof job) did not turn cyan either although his words were
#    delivered to lifted shaders. So the proof's tint is not a proof: it needs a ramp above 0 at the vertex and a lifted shader; nothing says
#    it ran. The twig pick named only trees, with the picture's pixels: its three 'under' rows are the draws that PASSED the depth test there
#    (3 of 328 G-buffer draws, all trees): the lantern at those pixels in the pick's frame may differ from the stills' (the pick came 60 s later).
#    FIX (TOOL): (a) the tint is UNCONDITIONAL on the hang bit (lifter: `pushed = hang`, no ramp rule) and is now also in the RECOMPILER's
#    EmitVertexSway (it had none: 'RECOMPILED (no counters, no tint)'), share 0.5 (was 0.4), on every float output of the vertex shader; the
#    proof's binary version add becomes 200000 so the b65 proof shaders are not loaded; (b) every Motion block draw is counted by its pair of
#    shaders in a TintBook that is never cleared (draws, draws whose hang word reached the motion parameter = the draws that are tinted, kinds,
#    ramp above 0, hidden, first and last frame): lines 'Wind sway hang proof (r112r)' every 600 frames with BB_WIND_HANG_FIND=1; (c) the glass
#    pick (r86l: BB_GLASS_PICK names EVERY draw that passed the depth test at its pixels, G-buffer and forward) gets one line under each shown row:
#    'Wind sway hang route (r112r): pick pixel x,y vs:ps a:b: N Motion block draws of this pair, W with a hang word delivered ...' so one log
#    line names the pair that draws the lantern and says whether its draws are tinted; (d) BB_WIND_HANG_PROOF_HIDE=1 (live: set:/unset:) leaves
#    every draw whose hang word reached the motion parameter OUT of the picture (the existing effect_skip_draw route): a lantern that vanishes
#    is drawn by a pair that gets the word, whatever the shaders do with it; nothing hides with the proof off.
#
# SHARED LINES TOUCHED (the lane r120c touches the test camera code only: none of these)
#  vk_rasterizer.h: one declaration after WindHangRouteReport, two members before hang_route.
#  vk_rasterizer.cpp: ONE block before r112h's no_param line in the Motion block (the pair's note, the hide flag), ONE line changed at
#   `effect_skip_draw = false;` before `if (effects_wanted)` (it takes the hide flag).
#  vk_rasterizer_effects.cpp: WindHangVerdict (BoxJudgeable's last argument), new functions before the route report, the report (one block before
#   hang_route.Clear()), GlassPickGroup (one block after the shown row's line).
#  lift_stage.cpp: the tint's condition (one line). emit_spirv_special.cpp: the tint block in EmitVertexSway after the hang top offer.
#  bbport_wind_hang.h: ProofShare 0.5, ProofBinaryAdd 200000. bbport_wind_hang_gpu.h: BoxJudgeable, NopalOn, Census (NopalRoom, counter, line).
#  bbport_wind_hang_route.h: TintBook. tests: test_wind_hang_route.cpp, test_wind_hang_gpu.cpp (cases added, the add's static_assert).
#  README.md: 2 rows and the proof row's sentence.
#
# COST WHEN OFF: every new line is behind BB_WIND_HANG (read once), BB_WIND_HANG_PROOF / BB_WIND_HANG_FIND (static bools) or BB_WIND_HANG_BOX_NOPAL
# (a static bool, read in the one place a stream was refused). No SPIR-V change without BB_WIND_HANG_PROOF=1 (the tint is inside `hang_on &&
# ProofOn()`), so a build with the knobs off is byte-identical: ProofShare and ProofBinaryAdd are read only with the proof on.
# Memory: the TintBook is at most 384 pairs of 80 bytes (30 KB), only with the proof or the route lines on. GPU: a tint is a load, 3 mix steps and a
# store a float output per vertex (proof only); the nopal route adds at most 48 streams to the box judge's table (r112f: a few hundred bytes each).
#
# Use: python -I -X utf8 r112r_hang-bracket-judge.py check | apply | revert
# Root: R112R_ROOT, else <tree>. Line ends kept. apply backs the originals up in r112r_backup next to this script; revert takes out
# exactly what apply put in. Needs r112q (and everything before it) applied.
import os, re, sys

ROOT = os.environ.get("R112R_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112r_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RH = RV + "vk_rasterizer.h"
RC = RV + "vk_rasterizer.cpp"
EF = RV + "vk_rasterizer_effects.cpp"
SH = "engine/gpu/shim/"
HH = SH + "bbport_wind_hang.h"
HG = SH + "bbport_wind_hang_gpu.h"
HR = SH + "bbport_wind_hang_route.h"
LS = SH + "lifter/lift_stage.cpp"
ES = "engine/gpu/shadps4/shader_recompiler/backend/spirv/emit_spirv_special.cpp"
TR = "engine/tests/test_wind_hang_route.cpp"
TG = "engine/tests/test_wind_hang_gpu.cpp"
RM = "README.md"

# ---- bbport_wind_hang.h ---------------------------------------------------------------------------------
H1 = r'''inline constexpr float ProofShare = 0.4f;'''
H1N = r'''inline constexpr float ProofShare = 0.5f; // bbport (r112r_hang-bracket-judge): 0.4 in r112m; the recompiler's shaders tint too now'''
H2 = r'''inline constexpr std::uint32_t ProofBinaryAdd = 100000;'''
H2N = r'''inline constexpr std::uint32_t ProofBinaryAdd = 200000; // bbport (r112r_hang-bracket-judge): 100000 in r112q; the tint changed (every hang bit, the recompiler too): the b65 proof shaders are not loaded'''

# ---- bbport_wind_hang_gpu.h -----------------------------------------------------------------------------
G1 = r'''[[nodiscard]] inline bool BoxJudgeable(const S::Entry* e, S::Result cpu, unsigned cap, bool moved_ok = true) {
    if (e == nullptr || e->bones == 0 || e->bones > cap) {
        return false;
    }'''
G1N = r'''[[nodiscard]] inline bool BoxJudgeable(const S::Entry* e, S::Result cpu, unsigned cap, bool moved_ok = true, bool nopal_ok = false) {
    // bbport (r112r_hang-bracket-judge): a stream with NO skeleton-size palette (Kind::NoPal: bones 0, the bracket lanterns' small bone
    // palettes are none Motion::ClassifyBuffer takes for a skeleton) is box-judged when `nopal_ok`; r112p's "never a palette with no bones"
    // kept the lanterns away from the judge (b65: 'book moving (why 1, box 0)', 'judge none')
    if (nopal_ok && e != nullptr && cpu == S::Result::Never && KindOf(e, cpu) == Kind::NoPal && e->bones <= cap) {
        return true;
    }
    if (e == nullptr || e->bones == 0 || e->bones > cap) {
        return false;
    }'''
G2 = r'''/// bbport (r112q_hang-bracket-route): the writer watch hears more than'''
G2P = r'''/// bbport (r112r_hang-bracket-judge): BB_WIND_HANG_BOX_NOPAL: a skinned stream with no skeleton-size palette at all (the bracket lanterns: their
/// small bone palettes are no Skeleton role) goes to the GPU box judge like the unread palettes; `0` gives r112q's rule (turned away). At most
/// NopalMost such streams are judged (Census::NopalRoom): the judge's table and the sway slots stay free for the rest of the scene.
inline constexpr std::size_t NopalMost = 48;

[[nodiscard]] inline bool ParseNopal(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == 0);
}

[[nodiscard]] inline bool NopalOn() {
    static const bool on = ParseNopal(std::getenv("BB_WIND_HANG_BOX_NOPAL"));
    return on;
}

'''
G3A = r'''            old = item;'''
G3AP = r'''            nopal_boxed -= old.kind == Kind::NoPal && old.box ? 1u : 0u; // bbport (r112r_hang-bracket-judge)
            nopal_boxed += item.kind == Kind::NoPal && item.box ? 1u : 0u;
'''
G3B = r'''        items.emplace(item.stream, item);'''
G3BP = r'''        nopal_boxed += item.kind == Kind::NoPal && item.box ? 1u : 0u; // bbport (r112r_hang-bracket-judge)
'''
G3C = r'''    /// Streams of `kind` that went to the box judge (`box`) or were turned away (`!box`).'''
G3CP = r'''    /// bbport (r112r_hang-bracket-judge): may this stream be box-judged although it has no skeleton-size palette? Yes when the census holds it
    /// as box-judged already, or fewer than NopalMost such streams are and the census can hold this one (a stream the full census
    /// cannot note would not be counted, so the cap would not hold).
    [[nodiscard]] bool NopalRoom(std::uint64_t stream) const {
        const auto found = items.find(stream);
        if (found != items.end() && found->second.kind == Kind::NoPal && found->second.box) {
            return true;
        }
        return nopal_boxed < NopalMost && (found != items.end() || items.size() < CensusMost);
    }

'''
G3D = r'''    std::unordered_map<std::uint64_t, Item> items;'''
G3DP = r'''
    std::size_t nopal_boxed = 0; // bbport (r112r_hang-bracket-judge): streams of Kind::NoPal sent to the box judge'''
G3E = r'''        char head[512];'''
G3EN = r'''        char head[768];'''
G3F = r'''content moved %zu+%zu; box judge %s up to %u bones (V# "'''
G3FN = r'''content moved %zu+%zu, no palette %zu+%zu, character %zu+%zu, other %zu+%zu; box judge %s up to %u bones (V# "'''
G3G = r'''Count(Kind::Moved, false),
                      ModeName(mode)'''
G3GN = r'''Count(Kind::Moved, false),
                      Count(Kind::NoPal, true), Count(Kind::NoPal, false), Count(Kind::Character, true), Count(Kind::Character, false),
                      Count(Kind::Other, true), Count(Kind::Other, false), ModeName(mode)'''

# ---- bbport_wind_hang_route.h ---------------------------------------------------------------------------
R1 = r'''} // namespace BbWindHangRoute'''
R1P = r'''// ---- bbport (r112r_hang-bracket-judge, TOOL): which pairs of shaders got a hang word, the proof's tint --------------------------------

inline constexpr std::size_t SeenMost = 384;     ///< pairs of shaders kept (never cleared: the pick reads them a minute later)
inline constexpr std::size_t TintLinesMost = 10; ///< pairs a report names

/// What the Motion block did with the draws of one pair of shaders since the start.
struct Seen {
    std::uint64_t vs = 0, ps = 0;
    std::uint64_t draws = 0;              ///< Motion block draws of the pair
    std::uint64_t words = 0;              ///< of them, draws whose hang word reached the motion parameter: the draws the proof tints
    std::array<std::uint64_t, 3> kinds{}; ///< of those, skinned, GPU palette, static
    std::uint64_t pushed = 0;             ///< of those, a ramp above 0
    std::uint64_t hidden = 0;             ///< of those, left out of the picture (BB_WIND_HANG_PROOF_HIDE)
    std::uint64_t first = 0, last = 0;    ///< the frames of the first and of the last of those
};

/// BB_WIND_HANG_PROOF_HIDE (live): exactly 1.
[[nodiscard]] inline bool ParseHide(const char* text) {
    return text != nullptr && text[0] == '1' && text[1] == 0;
}

class TintBook {
public:
    std::uint64_t dropped = 0; ///< pairs not kept for want of room

    /// A Motion block draw of the pair (vs, ps) of `kind` ('S', 'P' or 'O') with the sway word `word`; `delivered` it reached the motion
    /// parameter, `hidden` the draw is left out of the picture. Only a delivered word with the hang bit counts as a word (the proof's
    /// shaders tint the vertices of such a word whatever its ramp).
    void Note(std::uint64_t vs, std::uint64_t ps, char kind, std::uint32_t word, bool delivered, bool hidden, std::uint64_t frame) {
        const std::uint64_t key = ((vs & 0xffffffffu) << 32) | (ps & 0xffffffffu);
        auto found = seen.find(key);
        if (found == seen.end()) {
            if (seen.size() >= SeenMost) {
                ++dropped;
                return;
            }
            found = seen.emplace(key, Seen{}).first;
            found->second.vs = vs;
            found->second.ps = ps;
        }
        Seen& s = found->second;
        ++s.draws;
        if (!delivered || word == 0 || (word & H::HangBit) == 0) {
            return;
        }
        if (s.words == 0) {
            s.first = frame;
        }
        ++s.words;
        s.last = frame;
        s.kinds[kind == 'S' ? 0u : (kind == 'P' ? 1u : 2u)] += 1u;
        s.pushed += BbWindSway::Unpack(word).ramp > 0 ? 1u : 0u;
        s.hidden += hidden ? 1u : 0u;
    }

    [[nodiscard]] const Seen* Find(std::uint64_t vs, std::uint64_t ps) const {
        const auto found = seen.find(((vs & 0xffffffffu) << 32) | (ps & 0xffffffffu));
        return found == seen.end() ? nullptr : &found->second;
    }

    [[nodiscard]] std::size_t Pairs() const {
        return seen.size();
    }

    /// The report: a header (pairs seen, pairs and draws that got a hang word) and one line for each of the `most` pairs with the most
    /// words (ties by vs:ps).
    [[nodiscard]] std::vector<std::string> Lines(std::size_t most) const {
        std::vector<std::string> out;
        std::vector<const Seen*> order;
        std::uint64_t draws = 0, words = 0;
        for (const auto& item : seen) {
            draws += item.second.draws;
            words += item.second.words;
            if (item.second.words > 0) {
                order.push_back(&item.second);
            }
        }
        std::sort(order.begin(), order.end(), [](const Seen* a, const Seen* b) {
            if (a->words != b->words) {
                return a->words > b->words;
            }
            return a->vs < b->vs || (a->vs == b->vs && a->ps < b->ps);
        });
        char head[560];
        std::snprintf(head, sizeof(head),
                      "Wind sway hang proof (r112r): since the start %zu pairs of shaders drew %llu Motion block draws, %zu pairs and %llu draws "
                      "with a hang word delivered to the motion parameter (BB_WIND_HANG_PROOF tints every vertex of such a draw, whatever its "
                      "ramp)%s%s",
                      seen.size(), static_cast<unsigned long long>(draws), order.size(), static_cast<unsigned long long>(words),
                      order.empty() ? ": NO draw got a hang word, nothing is tinted" : "; most draws first:",
                      dropped > 0 ? " (pairs dropped: the table was full)" : "");
        out.emplace_back(head);
        for (std::size_t i = 0; i < order.size() && i < most; ++i) {
            const Seen& s = *order[i];
            char one[400];
            std::snprintf(one, sizeof(one),
                          "Wind sway hang proof (r112r): tinted vs:ps %08x:%08x: %llu draws (skinned %llu, GPU palette %llu, static %llu), ramp "
                          "above 0 in %llu, hidden %llu, frames %llu to %llu, of %llu Motion block draws of the pair",
                          static_cast<unsigned>(s.vs & 0xffffffffu), static_cast<unsigned>(s.ps & 0xffffffffu),
                          static_cast<unsigned long long>(s.words), static_cast<unsigned long long>(s.kinds[0]),
                          static_cast<unsigned long long>(s.kinds[1]), static_cast<unsigned long long>(s.kinds[2]),
                          static_cast<unsigned long long>(s.pushed), static_cast<unsigned long long>(s.hidden),
                          static_cast<unsigned long long>(s.first), static_cast<unsigned long long>(s.last),
                          static_cast<unsigned long long>(s.draws));
            out.emplace_back(one);
        }
        return out;
    }

    /// The line under a glass pick row: what the pair of the draw that wrote the pixel got from the Motion block (`proof_on`: the proof's
    /// shaders tint those draws).
    [[nodiscard]] std::string PickText(int x, int y, std::uint32_t vs, std::uint32_t ps, bool proof_on) const {
        const Seen* const s = Find(vs, ps);
        char buf[700];
        if (s == nullptr) {
            std::snprintf(buf, sizeof(buf),
                          "Wind sway hang route (r112r): pick pixel %d,%d vs:ps %08x:%08x: no Motion block draw of this pair of shaders was seen "
                          "since the start: the draw that wrote the pixel does not go through the Motion block (no motion pipeline, or a pass it "
                          "is not asked in), so no hang word can reach it",
                          x, y, static_cast<unsigned>(vs), static_cast<unsigned>(ps));
        } else if (s->words == 0) {
            std::snprintf(buf, sizeof(buf),
                          "Wind sway hang route (r112r): pick pixel %d,%d vs:ps %08x:%08x: %llu Motion block draws of this pair, NONE with a hang "
                          "word delivered to the motion parameter (the route line of the pair says where its draws leave the chain); nothing "
                          "is tinted or hidden",
                          x, y, static_cast<unsigned>(vs), static_cast<unsigned>(ps), static_cast<unsigned long long>(s->draws));
        } else {
            std::snprintf(buf, sizeof(buf),
                          "Wind sway hang route (r112r): pick pixel %d,%d vs:ps %08x:%08x: %llu Motion block draws of this pair, %llu with a hang "
                          "word delivered (skinned %llu, GPU palette %llu, static %llu; ramp above 0 in %llu; hidden %llu; frames %llu to %llu): %s",
                          x, y, static_cast<unsigned>(vs), static_cast<unsigned>(ps), static_cast<unsigned long long>(s->draws),
                          static_cast<unsigned long long>(s->words), static_cast<unsigned long long>(s->kinds[0]),
                          static_cast<unsigned long long>(s->kinds[1]), static_cast<unsigned long long>(s->kinds[2]),
                          static_cast<unsigned long long>(s->pushed), static_cast<unsigned long long>(s->hidden),
                          static_cast<unsigned long long>(s->first), static_cast<unsigned long long>(s->last),
                          proof_on ? "the proof tints these draws: cyan on the pixel = this pair, no cyan = the tint does not run"
                                   : "BB_WIND_HANG_PROOF is off: nothing is tinted");
        }
        return std::string(buf);
    }

private:
    std::unordered_map<std::uint64_t, Seen> seen;
};

/// The once line of the proof (BB_WIND_HANG_PROOF=1): `share` ProofShare, `add` ProofBinaryAdd.
[[nodiscard]] inline std::string ProofOnceText(float share, std::uint32_t add) {
    char buf[1000];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang proof (r112r, TOOL): BB_WIND_HANG_PROOF=1: every vertex shader of a sway pipeline, lifted AND recompiled, tints all "
                  "its float outputs %.0f percent toward cyan for every vertex whose motion word has the hang bit, whatever its ramp (r112m tinted "
                  "only a ramp above 0 and the recompiler never); the draws whose hang word reached the motion parameter are counted by vs:ps "
                  "(lines every 600 frames with BB_WIND_HANG_FIND=1, and under each row of the glass pick, BB_GLASS_PICK); "
                  "BB_WIND_HANG_PROOF_HIDE=1 (live) leaves those draws out of the picture; the hang shaders have their own cache version (+%u), "
                  "so they are compiled again for this proof",
                  static_cast<double>(share) * 100.0, static_cast<unsigned>(add));
    return std::string(buf);
}

} // namespace BbWindHangRoute'''

# ---- vk_rasterizer.h ------------------------------------------------------------------------------------
V1 = r'''void WindHangRouteReport();'''
V1P = r'''
    bool WindHangProofDraw(const GraphicsPipeline* pipeline, char kind, u32 word, bool delivered); // bbport (r112r_hang-bracket-judge, TOOL)'''
V2 = r'''    BbWindHangRoute::Book hang_route;'''
V2P = r'''    BbWindHangRoute::TintBook hang_tint; // bbport (r112r_hang-bracket-judge, TOOL): the pairs' hang words since the start
    bool hang_proof_hide = false; // the Motion block's verdict for the draw in flight: leave it out (BB_WIND_HANG_PROOF_HIDE)
'''

# ---- vk_rasterizer.cpp ----------------------------------------------------------------------------------
C1 = r'''        if (sway != 0 && dc.push_data.motion_param == 0) { // bbport (r112h_hang-not-the-hunter)'''
C1P = r'''        if (BbWindHang::ProofOn() || BbWindHangRoute::On()) { // bbport (r112r_hang-bracket-judge, TOOL): the pair's hang words counted, the hide flag
            hang_proof_hide = WindHangProofDraw(pipeline,
                                                r34_kind == Motion::Kind::Skinned
                                                    ? 'S'
                                                    : (r34_kind == Motion::Kind::GpuPalette ? 'P' : 'O'),
                                                sway, dc.push_data.motion_param != 0);
        }
'''
C2 = r'''    effect_skip_draw = false;
    if (effects_wanted) {'''
C2N = r'''    effect_skip_draw = hang_proof_hide; // bbport (r112r_hang-bracket-judge, TOOL): BB_WIND_HANG_PROOF_HIDE leaves a hang-word draw out
    hang_proof_hide = false;
    if (effects_wanted) {'''

# ---- vk_rasterizer_effects.cpp --------------------------------------------------------------------------
E1 = r'''                            BbWindHangGpu::BoxJudgeable(palette_entry, content, BbWindHangGpu::BoxBones(),
                                                        BbWindHangGpu::ModeOnce() == BbWindHangGpu::Mode::All);'''
E1N = r'''                            BbWindHangGpu::BoxJudgeable(palette_entry, content, BbWindHangGpu::BoxBones(),
                                                        BbWindHangGpu::ModeOnce() == BbWindHangGpu::Mode::All,
                                                        // bbport (r112r_hang-bracket-judge): a stream with no skeleton-size palette (the lanterns')
                                                        BbWindHangGpu::NopalOn() && hang_gpu_census.NopalRoom(positions));'''
E2 = r'''// bbport (r112q_hang-bracket-route, TOOL): the window's route lines (BbWindHangRoute::Lines)'''
E2P = r'''// bbport (r112r_hang-bracket-judge, TOOL): BB_WIND_HANG_PROOF_HIDE=1 (live with the test tools' knobs, else read once): the proof leaves every
// draw whose hang word reached the motion parameter out of the picture; WindHangProofDraw says so for the draw in flight.
#if BB_WIND_TWIGS_LIVE
static bool HangHideParseLive(const char* text) {
    return BbWindHangRoute::ParseHide(text);
}

static bool WindHangHideNow() {
    static BbLiveKnobs::Knob<bool> knob{"BB_WIND_HANG_PROOF_HIDE", HangHideParseLive};
    return knob.Get();
}
#else
static bool WindHangHideNow() {
    static const bool hide = BbWindHangRoute::ParseHide(std::getenv("BB_WIND_HANG_PROOF_HIDE"));
    return hide;
}
#endif

// bbport (r112r_hang-bracket-judge, TOOL): a Motion block draw (only with BB_WIND_HANG_PROOF=1 or BB_WIND_HANG_FIND=1) counted by its pair of
// shaders (BbWindHangRoute::TintBook: the draws whose hang word reached the motion parameter are the draws the proof's shaders tint, and the glass
// pick's rows name them), and true when BB_WIND_HANG_PROOF_HIDE=1 and the proof is on and the draw's word reached the parameter: the caller leaves
// the draw out (effect_skip_draw). On the thread recording draws.
bool Rasterizer::WindHangProofDraw(const GraphicsPipeline* pipeline, char kind, u32 word, bool delivered) {
    static bool said = false;
    const bool proof = BbWindHang::ProofOn();
    if (!said) {
        said = true;
        if (proof) {
            BbReport::Printf("%s\n", BbWindHangRoute::ProofOnceText(BbWindHang::ProofShare, BbWindHang::ProofBinaryAdd).c_str());
        }
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto* const fragment = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    const bool hang_word = delivered && word != 0 && (word & BbWindHang::HangBit) != 0;
    const bool hide = proof && hang_word && WindHangHideNow();
    hang_tint.Note(vs.pgm_hash, fragment != nullptr ? fragment->pgm_hash : u64{0}, kind, word, delivered, hide, object_motion->Frame());
    return hide;
}

// bbport (r112q_hang-bracket-route, TOOL): the window's route lines (BbWindHangRoute::Lines)'''
E3 = r'''    hang_route.Clear();'''
E3P = r'''    if (BbWindHang::ProofOn()) { // bbport (r112r_hang-bracket-judge, TOOL): the pairs whose hang word reached the motion parameter (tinted), since the start
        for (const std::string& line : hang_tint.Lines(BbWindHangRoute::TintLinesMost)) {
            BbReport::Printf("%s\n", line.c_str());
        }
    }
'''
E4 = r'''            RtGlassPick::DrawLine(pt, n + 1, rows.size(), counts[i], d, views.data(), found, use, line, sizeof(line));
            std::printf("%s\n", line);'''
E4P = r'''
            if (BbWindHang::ProofOn() || BbWindHangRoute::On()) { // bbport (r112r_hang-bracket-judge, TOOL): what the Motion block did with this pair
                std::printf("%s\n", hang_tint.PickText(pt.x, pt.y, d.vs, d.ps, BbWindHang::ProofOn()).c_str());
            }'''

# ---- lift_stage.cpp / emit_spirv_special.cpp ------------------------------------------------------------
L1 = r'''        const u32 pushed = Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool, {hang, FCmp(O(spv::Op::OpFOrdGreaterThan), ramp, zero)});'''
L1N = r'''        const u32 pushed = hang; // bbport (r112r_hang-bracket-judge): every vertex with the hang bit, whatever its ramp (r112m: only a ramp above 0)'''
S1 = r'''    // bbport (r89c_wind-lean): the vertex offers its world y to its mesh's crown key (CrownKey:'''
S1P = r'''    if (hang_on && BbWindHang::ProofOn()) { // bbport (r112r_hang-bracket-judge, TOOL): the proof's tint, as the lifter's: every float output
        // of a vertex with the hang bit (whatever its ramp) moves BbWindHang::ProofShare toward cyan (0, 1, 1)
        const Id tint_share = ctx.OpSelect(f32_type, hang, f(BbWindHang::ProofShare), zero);
        for (u32 p = 0; p < IR::NumParams; ++p) {
            const auto& output = ctx.output_params[p];
            if (!Sirit::ValidId(output.id) || output.is_integer || output.is_array ||
                output.id.value == ctx.clip_distances.value || output.num_components < 1 || output.num_components > 4) {
                continue;
            }
            const u32 n = output.num_components;
            const Id loaded = ctx.OpLoad(ctx.F32[n], output.id);
            std::array<Id, 4> parts{};
            for (u32 c = 0; c < n; ++c) {
                const Id value = n == 1 ? loaded : ctx.OpCompositeExtract(f32_type, loaded, c);
                parts[c] = c == 3u ? value : add(value, mul(sub(f(c == 0u ? 0.0f : 1.0f), value), tint_share));
            }
            Id tinted = parts[0];
            if (n == 2) {
                tinted = ctx.OpCompositeConstruct(ctx.F32[2], parts[0], parts[1]);
            } else if (n == 3) {
                tinted = ctx.OpCompositeConstruct(ctx.F32[3], parts[0], parts[1], parts[2]);
            } else if (n == 4) {
                tinted = ctx.OpCompositeConstruct(ctx.F32[4], parts[0], parts[1], parts[2], parts[3]);
            }
            ctx.OpStore(output.id, tinted);
        }
    }
'''

# ---- tests ----------------------------------------------------------------------------------------------
T1 = r'''        static_assert(H::ProofBinaryAdd == 100000u, "the add is a number no sway version reaches");'''
T1N = r'''        static_assert(H::ProofBinaryAdd == 200000u, "the add is a number no sway version reaches (r112r: 200000, r112q: 100000)");'''
T2 = r'''    if (failures == 0) {
        std::printf("wind-hang-route-test: all passed\n");'''
T2P = r'''    // bbport (r112r_hang-bracket-judge): the pairs that got a hang word, the proof's lines
    {
        R::TintBook book;
        const std::uint32_t pushed_word = H::HangWord(0, 0, 5, 200);
        const std::uint32_t keys_word = H::HangWord(0, 0, 5, 0);
        book.Note(0xe859b6d9u, 0x1u, 'S', pushed_word, true, false, 100);
        book.Note(0xe859b6d9u, 0x1u, 'S', keys_word, true, false, 110);
        book.Note(0xe859b6d9u, 0x1u, 'S', pushed_word, false, false, 120); // the word was lost
        book.Note(0xe859b6d9u, 0x1u, 'S', 0, true, false, 130);            // no word
        book.Note(0x6a833138u, 0x2u, 'O', pushed_word, true, true, 140);
        book.Note(0x77u, 0x3u, 'P', 0, false, false, 150);
        const R::Seen* const lantern = book.Find(0xe859b6d9u, 0x1u);
        Expect(lantern != nullptr && lantern->draws == 4 && lantern->words == 2 && lantern->kinds[0] == 2 && lantern->pushed == 1 &&
                   lantern->hidden == 0 && lantern->first == 100 && lantern->last == 110,
               "tint: a delivered hang word counts, a ramp 0 counts as a word, a lost word and no word do not");
        const R::Seen* const hidden = book.Find(0x6a833138u, 0x2u);
        Expect(hidden != nullptr && hidden->words == 1 && hidden->kinds[2] == 1 && hidden->hidden == 1, "tint: a static draw, hidden");
        Expect(book.Find(0x77u, 0x3u) != nullptr && book.Find(0x77u, 0x3u)->words == 0 && book.Find(0x1234u, 0x1u) == nullptr && book.Pairs() == 3,
               "tint: a pair with no word is kept, an unknown pair is not there");
        Expect(book.Find(0xaaaa0000e859b6d9ull, 0xbbbb000000000001ull) != nullptr, "tint: pairs are keyed by the low 32 bits of the hashes");
        const std::vector<std::string> lines = book.Lines(R::TintLinesMost);
        Expect(lines.size() == 3 && Has(lines[0], "2 pairs and 3 draws with a hang word") && Has(lines[0], "most draws first") &&
                   Has(lines[1], "tinted vs:ps e859b6d9:00000001: 2 draws (skinned 2, GPU palette 0, static 0), ramp above 0 in 1, hidden 0, frames 100 to 110, of 4 Motion block draws") &&
                   Has(lines[2], "vs:ps 6a833138:00000002: 1 draws (skinned 0, GPU palette 0, static 1), ramp above 0 in 1, hidden 1"),
               "tint: the report's lines, most words first");
        Expect(book.Lines(1).size() == 2, "tint: at most `most` pair lines");
        const R::TintBook empty{};
        const std::vector<std::string> none = empty.Lines(R::TintLinesMost);
        Expect(none.size() == 1 && Has(none[0], "NO draw got a hang word, nothing is tinted"), "tint: an empty book says so");
        const std::string with = book.PickText(1117, 677, 0xe859b6d9u, 0x1u, true);
        Expect(Has(with, "pick pixel 1117,677 vs:ps e859b6d9:00000001: 4 Motion block draws of this pair, 2 with a hang word delivered") &&
                   Has(with, "the proof tints these draws") && !Has(with, "NONE"),
               "tint: the pick's line for a pair with words");
        Expect(Has(book.PickText(1, 2, 0xe859b6d9u, 0x1u, false), "BB_WIND_HANG_PROOF is off: nothing is tinted"), "tint: the pick's line with the proof off");
        Expect(Has(book.PickText(1, 2, 0x77u, 0x3u, true), "NONE with a hang word delivered") &&
                   Has(book.PickText(1, 2, 0x99u, 0x9u, true), "no Motion block draw of this pair of shaders was seen"),
               "tint: the pick's lines for a pair with no word and for an unknown pair");
        Expect(R::ParseHide("1") && !R::ParseHide(nullptr) && !R::ParseHide("") && !R::ParseHide("0") && !R::ParseHide("11"), "hide: exactly 1");
        const std::string once = R::ProofOnceText(H::ProofShare, H::ProofBinaryAdd);
        Expect(Has(once, "lifted AND recompiled") && Has(once, "50 percent") && Has(once, "(+200000)") && Has(once, "BB_WIND_HANG_PROOF_HIDE=1"),
               "tint: the once line");
        R::TintBook full;
        for (std::uint64_t i = 0; i < R::SeenMost + 5; ++i) {
            full.Note(i + 1, 1, 'S', 0, false, false, 1);
        }
        Expect(full.Pairs() == R::SeenMost && full.dropped == 5 && Has(full.Lines(1)[0], "pairs dropped"), "tint: the table is bounded");
    }
    if (failures == 0) {
        std::printf("wind-hang-route-test: all passed\n");'''
T3 = r'''    if (failures != 0) {
        std::printf("%d failures\n", failures);'''
T3P = r'''    // bbport (r112r_hang-bracket-judge): a stream with no skeleton-size palette goes to the box judge when asked
    {
        Expect(G::ParseNopal(nullptr) && G::ParseNopal("") && G::ParseNopal("1") && G::ParseNopal("00") && !G::ParseNopal("0"),
               "nopal: on unless exactly 0");
        const S::Entry bare = MakeEntry(0, S::Why::NoPalette);
        const S::Entry character = MakeEntry(120, S::Why::Character);
        const S::Entry gpu_palette = MakeEntry(84, S::Why::GpuWritten);
        Expect(!G::BoxJudgeable(&bare, S::Result::Never, 96) && !G::BoxJudgeable(&bare, S::Result::Never, 96, true, false),
               "nopal: turned away as before without the flag");
        Expect(G::BoxJudgeable(&bare, S::Result::Never, 96, true, true) && G::BoxJudgeable(&bare, S::Result::Never, 96, false, true),
               "nopal: judged by the box with the flag (also with moved_ok false: it was never read)");
        Expect(!G::BoxJudgeable(nullptr, S::Result::Never, 96, true, true) && !G::BoxJudgeable(&bare, S::Result::Same, 96, true, true) &&
                   !G::BoxJudgeable(&bare, S::Result::Moved, 96, true, true),
               "nopal: no entry, a still palette and a moved one are no nopal case");
        Expect(!G::BoxJudgeable(&character, S::Result::Never, 341, true, true) && G::BoxJudgeable(&gpu_palette, S::Result::Never, 96, true, true),
               "nopal: a character stays refused, the unread palettes are judged as before");
        G::Census census;
        for (std::uint64_t i = 1; i <= G::NopalMost; ++i) {
            Expect(census.NopalRoom(i), "nopal: room while fewer than the most are judged");
            census.Note(MakeItem(i, G::Kind::NoPal, true));
        }
        Expect(!census.NopalRoom(9999) && census.NopalRoom(3), "nopal: full: a new stream has no room, a judged one keeps it");
        census.Note(MakeItem(500, G::Kind::NoPal, false));
        Expect(!census.NopalRoom(500), "nopal: a turned-away stream does not count as judged and has no room when full");
        census.Note(MakeItem(1, G::Kind::NoPal, false)); // stream 1 changes to turned away: its place is free again
        Expect(census.NopalRoom(9999), "nopal: a place frees when a judged stream is turned away");
        census.Note(MakeItem(1, G::Kind::NoPal, true));
        Expect(!census.NopalRoom(9999), "nopal: and is taken again");
        G::Census crowded;
        for (std::uint64_t i = 1; i <= G::CensusMost; ++i) {
            crowded.Note(MakeItem(i, G::Kind::Gpu, false));
        }
        Expect(!crowded.NopalRoom(G::CensusMost + 1) && crowded.NopalRoom(1), "nopal: no room for a stream the full census cannot note");
        std::string line;
        Expect(census.TakeLine(G::Mode::All, 96, line) && Has(line, "no palette 48+1") && Has(line, "character 0+0") && Has(line, "other 0+0") &&
                   Has(line, "content moved 0+0"),
               "nopal: the census line counts the three new kinds");
        G::Census mixed;
        mixed.Note(MakeItem(7, G::Kind::Character, false));
        mixed.Note(MakeItem(8, G::Kind::Other, false));
        std::string mixed_line;
        Expect(mixed.TakeLine(G::Mode::All, 96, mixed_line) && Has(mixed_line, "character 0+1") && Has(mixed_line, "other 0+1") &&
                   Has(mixed_line, "no palette 0+0"),
               "nopal: character and other are counted turned away");
    }
    if (failures != 0) {
        std::printf("%d failures\n", failures);'''

# ---- README ---------------------------------------------------------------------------------------------
M1 = r'''| `BB_WIND_HANG_PROOF` | A TEST aid for `BB_WIND_HANG` (r112m;'''
M1P = r'''| `BB_WIND_HANG_BOX_NOPAL` | Part of `BB_WIND_HANG_BOXJUDGE` (r112r; read once; exactly `0` gives r112q's rule, anything else or unset is on). A skinned stream with NO skeleton-size palette (the bracket lanterns in the graveyard trees: their small bone palettes are not the stride-16 skeleton palette the palette test reads, so b65's route lines said `book moving (why 1, box 0)`, `judge none`) was turned away and never reached the GPU box judge, so `BB_WIND_HANG_BOX_RETRY` had nothing to retry. It is now box-judged like the unread palettes (at most 48 such streams), pushed when its world box stands still, and refused like any mover when the box grows; r112h's hunter, figure and indoor rules are unchanged. The census line counts the kinds `no palette`, `character` and `other` too. |
| `BB_WIND_HANG_PROOF_HIDE` | TOOL (r112r; test-tools branch; needs `BB_WIND_HANG=1` and `BB_WIND_HANG_PROOF=1`; live with `set:`/`unset:`; exactly `1` is on, off by default). Every draw whose hang word reached the motion parameter is left out of the picture (the way a draw is left out while its pipeline compiles): a lantern that vanishes is drawn by a pair of shaders that gets the word, whatever the shaders do with it. Nothing hides with the proof off. |
'''
M2 = r'''Every output attribute of a pushed hanging draw is tinted 40 % toward cyan, so that a picture shows which meshes are pushed (nothing is tinted with `BB_WIND_HANG_PUSH=0` live).'''
M2N = r'''Since r112r every float output of every vertex that has a hang word is tinted 50 % toward cyan, whatever its ramp, in the lifter's and in the recompiler's vertex shaders (the shaders are compiled again for the proof), so that a picture shows which meshes get a word; the draws whose word reached the motion parameter are counted by vertex and pixel shader (`Wind sway hang proof (r112r)` lines with `BB_WIND_HANG_FIND=1`, and a line under each row of the glass pick `BB_GLASS_PICK`).'''

EDITS = {
HH: [
('rep', H1, "", H1N),
('rep', H2, "", H2N),
],
HG: [
('rep', G1, "", G1N),
('ins', G2, G2P, ""),
('ins', G3A, G3AP, ""),
('ins', G3B, G3BP, ""),
('ins', G3C, G3CP, ""),
('ins', G3D, "", G3DP),
('rep', G3E, "", G3EN),
('rep', G3F, "", G3FN),
('rep', G3G, "", G3GN),
],
HR: [
('ins', R1, R1P[:-len(R1)], ""),
],
RH: [
('ins', V1, "", V1P),
('ins', V2, V2P, ""),
],
RC: [
('ins', C1, C1P, ""),
('rep', C2, "", C2N),
],
EF: [
('rep', E1, "", E1N),
('ins', E2, E2P[:-len(E2)], ""),
('ins', E3, E3P, ""),
('ins', E4, "", E4P),
],
LS: [
('rep', L1, "", L1N),
],
ES: [
('ins', S1, S1P, ""),
],
TR: [
('rep', T1, "", T1N),
('ins', T2, T2P[:-len(T2)], ""),
],
TG: [
('ins', T3, T3P[:-len(T3)], ""),
],
RM: [
('ins', M1, M1P, ""),
('rep', M2, "", M2N),
],
}

ORDER = (HH, HG, HR, RH, RC, EF, LS, ES, TR, TG, RM)


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


CPP = (HH, HG, HR, RH, RC, EF, LS, ES, TR, TG)


def text_checks(texts, olds):
    """The ties a compiler cannot check."""
    hh, hg, hr, rh, rc, ef, ls, es, tr, tg = (texts[p] for p in CPP)
    for path in CPP:
        if balance(texts[path]) != balance(olds[path]):
            raise SystemExit("text check: %s: braces, parens or brackets changed by %r" %
                             (path, tuple(a - b for a, b in zip(balance(texts[path]), balance(olds[path])))))
    for block in (G1N, G2P, G3AP, G3BP, G3CP, G3DP, G3EN, G3FN, G3GN, R1P, V1P, V2P, C1P, C2N, E1N, E2P, E3P, E4P, L1N, S1P, T1N, T2P, T3P, M1P, M2N):
        try:
            block.encode("ascii")
        except UnicodeEncodeError:
            raise SystemExit("text check: a non-ASCII character in an inserted block: %r" % block[:60])
        if "\t" in block:
            raise SystemExit("text check: a tab in an inserted block: %r" % block[:60])
    for block in (G2P, G3CP, R1P[:-len(R1)], C1P, E2P[:-len(E2)], E3P, S1P, T2P[:-len(T2)], T3P[:-len(T3)]):
        if balance(block) != (0, 0, 0):
            raise SystemExit("text check: an inserted block does not balance: %r %r" % (block[:60], balance(block)))
    # the knobs and the class members
    if hg.index("inline bool NopalOn()") > hg.index("class Census {") or hg.index("NopalMost = 48;") > hg.index("class Census {"):
        raise SystemExit("text check: NopalMost and NopalOn come before Census")
    if hg.count("nopal_boxed") != 5:
        raise SystemExit("text check: nopal_boxed is declared once and used four times (got %d)" % hg.count("nopal_boxed"))
    # BoxJudgeable: KindOf comes before it, the one call site passes five arguments
    if hg.index("inline Kind KindOf(") > hg.index("inline bool BoxJudgeable("):
        raise SystemExit("text check: KindOf comes before BoxJudgeable")
    if ef.count("BbWindHangGpu::NopalOn() && hang_gpu_census.NopalRoom(positions)") != 1:
        raise SystemExit("text check: the verdict's call")
    # route header: TintBook before the namespace's end, the helpers it uses are in the file
    for needle in ("class TintBook {", "inline std::string ProofOnceText(", "inline bool ParseHide(", "struct Seen {"):
        if needle not in hr:
            raise SystemExit("text check: %s missing in the route header" % needle)
    if hr.index("class Book {") > hr.index("class TintBook {") or hr.rindex("} // namespace BbWindHangRoute") < hr.index("ProofOnceText("):
        raise SystemExit("text check: the tint's place in the route header")
    # the rasterizer: declaration, members, the hook, the skip line, in order
    if rh.count("bool WindHangProofDraw(") != 1 or rh.count("BbWindHangRoute::TintBook hang_tint;") != 1 or rh.count("bool hang_proof_hide = false;") != 1:
        raise SystemExit("text check: rasterizer.h")
    hook = rc.index("hang_proof_hide = WindHangProofDraw(")
    if not (rc.index("WindHangRouteNote(pipeline,") < hook < rc.index("if (sway != 0 && dc.push_data.motion_param == 0) {")):
        raise SystemExit("text check: the Motion block's hook is between the route note and r112h's line")
    if rc.count("effect_skip_draw = hang_proof_hide;") != 1 or rc.count("hang_proof_hide = false;") != 1:
        raise SystemExit("text check: the skip line")
    if rc.index("effect_skip_draw = hang_proof_hide;") < hook:
        raise SystemExit("text check: the skip line comes after the hook (the same function, later)")
    # the effects file: the new function is a member, the live knob is defined before use, the report and the pick
    if not (ef.index("static bool WindHangHideNow()") < ef.index("bool Rasterizer::WindHangProofDraw(") < ef.index("void Rasterizer::WindHangRouteReport()")):
        raise SystemExit("text check: WindHangHideNow, WindHangProofDraw, WindHangRouteReport in this order")
    if ef.count("hang_tint.Lines(BbWindHangRoute::TintLinesMost)") != 1 or ef.count("hang_tint.PickText(pt.x, pt.y, d.vs, d.ps,") != 1:
        raise SystemExit("text check: the report and the pick lines")
    if not (ef.index("void Rasterizer::GlassPickGroup(") < ef.index("hang_tint.PickText(")):
        raise SystemExit("text check: the pick line is inside GlassPickGroup")
    # shaders: the lifter's tint takes the hang bit, the recompiler tints inside hang_on && ProofOn, after the top offer and before the crown key
    if ls.count("const u32 pushed = hang;") != 1 or "FCmp(O(spv::Op::OpFOrdGreaterThan), ramp, zero)});" in ls[ls.index("const u32 pushed = hang;") - 200:ls.index("const u32 pushed = hang;") + 400]:
        raise SystemExit("text check: the lifter's tint line")
    tint = es.index("if (hang_on && BbWindHang::ProofOn()) {")
    if not (es.index("ctx.AddLabel(top_merge);") < tint < es.index("the vertex offers its world y to its mesh's crown key")):
        raise SystemExit("text check: the recompiler's tint is between the top offer and the crown key")
    if es.count("BbWindHang::ProofOn()") != 1:
        raise SystemExit("text check: the recompiler reads the proof once")
    # the proof's version add is still used by the serialization and the test
    if hh.count("ProofBinaryAdd = 200000;") != 1 or hh.count("ProofShare = 0.5f;") != 1 or "ProofBinaryAdd == 200000u" not in tr:
        raise SystemExit("text check: the proof constants and the test's static_assert")
    # tests: the new blocks sit before the final verdict, inside main
    if tr.index("TintBook book;") > tr.index('std::printf("wind-hang-route-test: all passed\\n");') or tg.index("nopal: on unless exactly 0") > tg.index('std::printf("%d failures\\n", failures);'):
        raise SystemExit("text check: the tests' new blocks come before the verdicts")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112R_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == HR and "BbWindHangRoute" not in cur:
            raise SystemExit("REFUSED: r112q must be applied")
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
            tmp = full + ".r112rtmp"
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
        tmp = full + ".r112rtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


if __name__ == "__main__":
    main()
