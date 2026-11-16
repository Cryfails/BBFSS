# r112l_hang-discard-lanterns: FEATURE fix on top of r112k_hang-lantern-verdict (r112j, r112i, r112h ... all applied
# in the tree), behind r112's own knob BB_WIND_HANG=1 (off by default). Six files edited, no new file, no shader change
# (bbport_wind_hang_find.h, test_wind_hang_find.cpp, vk_rasterizer.cpp, vk_rasterizer_effects.cpp, README.md; the
# declarations in vk_rasterizer.h are unchanged).
#
# THE EVIDENCE (b55: slot_b55_result.txt, b55_s5.log graveyard, b55_s2.log alley, b55_reports.txt)
#  - The 97f2d384 lantern streams A (1429 verts, 0.21 m) and B (2491 verts, 0.88 m, 1.45 m wide) read "route P bit 1 disc 1
#    ... asked 0 passed 0, book -" at every survey line of every job. "bit 1" = the pipeline carries the Sway bit (the
#    pipeline cache gives it to every pipeline whose pixel shader discards: SwayWanted, FragmentDiscards: the plant rule);
#    "disc 1" = ITS PIXEL SHADER DISCARDS (ps 0f54e5f9: a cut-out lantern with open bars or glass cut-outs).
#  - WHY "disc 1" STOPS THEM: the routing clause of the static path in vk_rasterizer.cpp (r112i, r112k) begins with
#    BbWindHangFind::Wanted(sway bit, fragment stage), and Wanted is WantedWith: static_on && sway_bit && !(fragment !=
#    nullptr && fragment->has_discard). r112i's header says why: "a cut-out is the twigs'" (a plant, which the twig and
#    plant rules take). So a lantern whose pixel shader discards is turned away by the first test of the clause, before
#    WindHangGpuStatic, before any verdict of the static book: "book -", "asked 0". The vs 9da6aacb meshes that WERE
#    taken (D, E: ps bb10e440 / e21e283a, disc 0) are the opaque ones. Nothing is wrong with the lanterns' kind (P, the
#    GPU palette, r112k's route) any more: r112k's route worked for the opaque draws (asked 3699, passed 3698 of D).
#  - THE 9.87 m MESH: the "r112 meshes: hang vs 9da6aacb 9.87 m (top y -29.6)" entry is NOT a 9.87 m mesh. r112k's line
#    "candidates measured: vs 6a833138 scene 0.89 m, keys 9.87 m (fits)" says what it is: the ray traced scene's box of that
#    stream is 0.89 m tall (stream E, 1338 verts, 2.51 m over the ground, 52.6 m away), and the keys of its slot span
#    9.87 m because the same mesh is drawn at several places of the graveyard at different heights (the keys are the least
#    and greatest world y of every draw of the stream: the union r112k allows up to 12 m). The shaders take the still top
#    and the scale from those keys (a union taller than 1.2 m: scale 1), and the push weight of a vertex from its distance
#    below the slot's top: every place lower than the highest one is pushed as a WHOLE by the full push (rigidly, a lantern
#    swinging on its hook), and only the highest place keeps its top 0.3 m still. So the "tall" thing is the union.
#  - THE AMPLITUDE: BB_WIND_SWAY 3 x PushFull 0.15 x (4/4)^2 = 0.45 m at gust 1, held to MaxAlong 0.4 m: "push 0.400 m";
#    a lantern moved as a whole by 0.4 m (b55 line: the bottom of a 0.9 m lantern 0.300 m at most) is 4 to 10 times what a
#    lantern in a light gale does. The owner's target: 3 to 10 cm at 4 m/s, less at 1.5 m/s, slow, downwind, settling back
#    (the push table's follower already rises in 0.4 s at 4 m/s and eases back in 1.6 s: slow and settling).
#
# WHAT THIS CHANGES
#  (1) THE CUT-OUT ROUTE (feature, BB_WIND_HANG_STATIC_CUT, default 1; 0 = r112k): vk_rasterizer.cpp's routing clause
#      uses BbWindHangFind::WantedCut (the sway bit and the static path as Wanted, and a pixel shader that discards passes
#      too, with the knob) and sends every draw of a discarding pipeline, of Kind::Other or Kind::GpuPalette, to
#      Rasterizer::WindHangGpuStatic like a GPU-palette draw: only when its position stream is a hanging candidate (the
#      book's standing verdict, or a verdict made now by the box, size and ground rules). A cut-out that is no candidate
#      is not touched: the clause is false and the plant, twig and tree arms below take it as before (r89e's static
#      cut-out rule, r89i's palette rule). WindHangGpuStatic tests CutOn() for such a draw (GpuOn() for an opaque one).
#      LOG: "Wind sway hang (r112l)" once says why disc 1 stopped them (Wanted) and what is done; the counters line says
#      "N draws asked, M of a candidate stream" for the cut-outs (Stats::cut_asked, cut_passed); the survey (TOOL grade,
#      BB_WIND_HANG_FIND=1) marks every discarding stream "[cut-out: offered]" (or "[cut-out: held back, CUT=0]").
#  (2) THE TALL RULE (BB_WIND_HANG_STATIC_TALL, default 2.5 m): a static candidate's keys may span the union limit
#      (BB_WIND_HANG_STATIC_UNION, 12 m) only when the mesh CLEARLY HANGS: its scene box is at most 1.5 m tall and its
#      bottom at least 2.0 m over the ground (the Entry's own height and above, from the verdict). Any other candidate
#      whose keys span more than the tall limit (held to r112's 4 m: min(MaxExtent, TALL)) is judged "does not fit" and
#      refused as r112 did. The graveyard lanterns (stream E 0.89 m scene box, 2.51 m up; D 0.94 m, 7.51 m up) are clear;
#      the log line "Wind sway hang (r112l): candidates by the span of their keys" says, per candidate, its span and
#      whether it was kept as clearly hanging or refused, with the scene height and height over the ground.
#  (3) THE PUSH (BB_WIND_HANG_STATIC_GAIN, default 0.2, 0 to 1): the ramp byte of a static candidate's hang word is
#      multiplied by the gain (WindHangWord: the ramp is the weight of the word in the shader; r112j's roof scale
#      multiplies on top, as before), so the push is 0.2 of the sway's: 0.45 m at gust 1 held to 0.4 m is 0.08 m at 4 m/s
#      BB_WIND_SWAY 3 (a lantern's bottom at most 0.08 m, 3.6 cm at BB_WIND_SWAY 1 and the mean gust), 0.013 m at 1.5 m/s
#      gust 1 (0.03 m at gust 1.5). Skinned hanging things (r112) keep their push. The same table, rise and release
#      times: slow, downwind, back. The log line "Wind sway hang (r112l)" prints the static push now and at most.
#  Shared lines touched (the twig lane works on the same sway files): NONE of the wind sway files. Only hang code:
#  vk_rasterizer.cpp's routing clause (r112i's, rewritten by r112k, now r112l), WindHangGpuStatic, WindHangWord (the two
#  lines r112k added: max_extent, the return), the report block of the hang line and the once-line.
#
# Off: BB_WIND_HANG unset: StaticOn() is false: WantedCut is false (as Wanted), CutOn()/GpuOn() false, no new path runs. The
# new report lines sit inside `if (BbWindHangFind::StaticOn())`, the once-line inside `BbWindHang::KnobOnce().on`. The gain
# and the tall rule are read only in WindHangWord (the hang path). BB_WIND_HANG_STATIC_CUT=0 gives r112k's routing and
# counters; GAIN=1 and TALL=40 the old push and union.
# Cost: a draw of a discarding sway pipeline of Kind::Other or GpuPalette (BB_WIND_HANG=1 only) does one fetch walk and
# one hash lookup (the standing verdict; the first draw of a new stream a verdict, as for any static stream): a few
# hundred such draws a frame in the graveyard, ~0.1 us each when the verdict stands; the report lines a few string
# builds every 600 frames. GPU: none added (the same pipelines and shaders). Memory: none.
#
# Use: python -I -X utf8 r112l_hang-discard-lanterns.py check | apply | revert
# Root: R112L_ROOT, else <tree>. CRLF kept. apply backs the originals up in r112l_backup next to this script;
# revert takes out exactly what apply put in. Needs r112k applied (the anchors are its texts).
import os, re, sys

ROOT = os.environ.get("R112L_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112l_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RE = RV + "vk_rasterizer_effects.cpp"
RC = RV + "vk_rasterizer.cpp"
NF = "engine/gpu/shim/bbport_wind_hang_find.h"
NT = "engine/tests/test_wind_hang_find.cpp"
RM = "README.md"

# ---- bbport_wind_hang_find.h -----------------------------------------------------------------------
F1 = r"""inline constexpr std::size_t LineCharsK = 480, RoutesMost = 4096;
"""
F1N = r"""inline constexpr std::size_t LineCharsK = 560, RoutesMost = 4096; // bbport (r112l): was 480 (the cut-out mark)
"""

F2 = r"""/// The survey is on: BB_WIND_HANG on and BB_WIND_HANG_FIND=1.
"""
F2P = r"""// bbport (r112l_hang-discard-lanterns): BB_WIND_HANG_STATIC_CUT (default on; exactly 0 = r112k): a draw of a pipeline whose
// pixel shader discards (a cut-out: the graveyard lanterns' ps 0f54e5f9 is one) goes to the static path like an opaque one,
// when its stream is a hanging candidate. r112i's Wanted refused every such pipeline before any verdict ("a cut-out is the
// twigs'"): the survey read "disc 1 ... asked 0, book -" for them.
[[nodiscard]] inline bool ParseCut(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == 0);
}

[[nodiscard]] inline bool CutKnob() {
    static const bool on = ParseCut(std::getenv("BB_WIND_HANG_STATIC_CUT"));
    return on;
}

/// The cut-out route is on: the static path is, and BB_WIND_HANG_STATIC_CUT is not 0.
[[nodiscard]] inline bool CutOn() {
    return StaticOn() && CutKnob();
}

/// A pixel shader (null: none) that discards.
template <class Stage>
[[nodiscard]] inline bool Cuts(const Stage* fragment) {
    return fragment != nullptr && fragment->has_discard;
}

/// Pure form of WantedCut: a pipeline with the Sway bit; one whose pixel shader discards only with the cut knob.
template <class Stage>
[[nodiscard]] inline bool WantedCutWith(bool static_on, bool cut_on, bool sway_bit, const Stage* fragment) {
    return static_on && sway_bit && (cut_on || !Cuts(fragment));
}

/// May a static draw of this pipeline carry a hang word (is the pipeline built for it)? As Wanted, and a cut-out too
/// with BB_WIND_HANG_STATIC_CUT (the caller then asks the static book about the stream before it takes the draw).
template <class Stage>
[[nodiscard]] inline bool WantedCut(bool sway_bit, const Stage* fragment) {
    return WantedCutWith(StaticOn(), CutKnob(), sway_bit, fragment);
}

// bbport (r112l): BB_WIND_HANG_STATIC_GAIN (0 to 1, default GainDefault): the share of the sway's push a static candidate gets
// (b55: 0.4 m on a lantern, far above a lantern's few cm); BB_WIND_HANG_STATIC_TALL (m, MinExtent to UnionMax, default
// TallDefault): the keys' span beyond which a static candidate must clearly hang (ClearlyHanging) to keep its union limit.
inline constexpr float GainDefault = 0.2f;
inline constexpr float TallDefault = 2.5f;
inline constexpr float ClearlyHeight = 1.5f; ///< m: a mesh that clearly hangs is at most this tall (scene box)
inline constexpr float ClearlyAbove = 2.0f;  ///< m: and its bottom is at least this far over the ground

[[nodiscard]] inline float ParseGain(const char* text) {
    return std::clamp(BbWindSway::ParseNumber(text, GainDefault), 0.0f, 1.0f);
}

[[nodiscard]] inline float GainKnob() {
    static const float gain = ParseGain(std::getenv("BB_WIND_HANG_STATIC_GAIN"));
    return gain;
}

[[nodiscard]] inline float ParseTall(const char* text) {
    return std::clamp(BbWindSway::ParseNumber(text, TallDefault), H::MinExtent, UnionMax);
}

[[nodiscard]] inline float TallKnob() {
    static const float tall = ParseTall(std::getenv("BB_WIND_HANG_STATIC_TALL"));
    return tall;
}

/// A hang word's ramp byte scaled by the static push gain (0 to 1).
[[nodiscard]] inline std::uint32_t GainRamp(std::uint32_t ramp, float gain) {
    return std::uint32_t(std::lround(float(ramp) * std::clamp(gain, 0.0f, 1.0f)));
}

"""

F3 = r"""    std::uint64_t gpu_passed = 0; ///< bbport (r112k): and those of a candidate stream (sent on to the static path)
"""
F3N = r"""    std::uint64_t cut_asked = 0;  ///< bbport (r112l): of those, draws of a pipeline whose pixel shader discards (cut-outs)
    std::uint64_t cut_passed = 0; ///< bbport (r112l): and those of a candidate stream
"""

F4 = r"""/// The survey: a header line and up to ListMost candidate lines (a mesh of the scene of
"""
F4P = r"""/// bbport (r112l_hang-discard-lanterns): a candidate that clearly hangs: a small mesh (its scene box at most ClearlyHeight
/// tall) that stands well clear of the ground (its bottom ClearlyAbove or more over it): the places a lantern hangs at.
[[nodiscard]] inline bool ClearlyHanging(const Entry& e) {
    return e.height <= ClearlyHeight && e.above >= ClearlyAbove;
}

/// The most the keys of a static candidate may span: the union limit for a mesh that clearly hangs (a mesh drawn at
/// several places spans the union of them), else the tall limit held to r112's MaxExtent.
[[nodiscard]] inline float SpanLimitWith(float union_m, float tall_m, const Entry& e) {
    return ClearlyHanging(e) ? union_m : std::min(H::MaxExtent, tall_m);
}

[[nodiscard]] inline float SpanLimit(const Entry& e) {
    return SpanLimitWith(UnionKnob(), TallKnob(), e);
}

/// The push of a static candidate now (m): the push table's value held to MaxAlong, times the gain.
[[nodiscard]] inline float StaticPush(const PushSource& p, float gain) {
    return p.now * std::clamp(gain, 0.0f, 1.0f);
}

/// The survey's mark of a stream whose pixel shader discards (nothing for another or no route).
[[nodiscard]] inline std::string CutNote(const Routes* routes, std::uint64_t stream, bool cut_on) {
    if (routes == nullptr) {
        return std::string();
    }
    const Route* const r = routes->Find(stream);
    if (r == nullptr || !r->discards) {
        return std::string();
    }
    return cut_on ? std::string(" [cut-out: offered]") : std::string(" [cut-out: held back, CUT=0]");
}

/// The once-line of r112l: why a discard stopped the lanterns, and what is done.
[[nodiscard]] inline std::string OnceTextL(bool cut, float gain, float tall_m) {
    char buf[1536];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112l): a pipeline whose pixel shader discards (a cut-out lantern or cage; r112i's "
                  "Wanted refused it before any verdict: the survey's 'disc 1' with 'asked 0, book -') is offered to the "
                  "static path like an opaque one and pushed when its stream is a candidate (BB_WIND_HANG_STATIC_CUT=%d); "
                  "a static candidate's push is %.2f of the sway's (BB_WIND_HANG_STATIC_GAIN): at most %.3f m (MaxAlong "
                  "x gain); keys that span more than %.1f m (BB_WIND_HANG_STATIC_TALL; r112's %.1f m at most) count only "
                  "for a mesh that clearly hangs (scene box at most %.1f m tall, %.1f m or more over the ground: the "
                  "union of the places a lantern is drawn at), any other is refused as too tall",
                  cut ? 1 : 0, double(gain), double(BbWindSway::MaxAlong * gain), double(tall_m), double(H::MaxExtent),
                  double(ClearlyHeight), double(ClearlyAbove));
    return std::string(buf);
}

/// The line of r112l every ReportFrames frames: the cut-out draws asked and passed, the static push gain and its size now.
[[nodiscard]] inline std::string CutLine(const Stats& s, bool cut, float gain, const PushSource& p) {
    char buf[1024];
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112l): cut-out streams (a pixel shader that discards; BB_WIND_HANG_STATIC_CUT=%d): "
                  "%llu draws asked, %llu of a candidate stream; static push gain %.2f (BB_WIND_HANG_STATIC_GAIN): a "
                  "static candidate is pushed %.3f m now (wind %s, %.2f m/s, gust %.2f), at most %.3f m (MaxAlong x gain), "
                  "its lowest part moving as a whole by that",
                  cut ? 1 : 0, n(s.cut_asked), n(s.cut_passed), double(gain), double(StaticPush(p, gain)),
                  p.wind_on ? "on" : "off", double(p.speed), double(p.gust),
                  double(BbWindSway::MaxAlong * std::clamp(gain, 0.0f, 1.0f)));
    return std::string(buf);
}

/// The candidates' keys: for each (the newest TakenMost) the span of its slot's keys, the limit it got and whether it was
/// kept as clearly hanging or refused as too tall, with the scene box's height and the height over the ground.
[[nodiscard]] inline std::string TallText(const StaticBook& book, H::Book& heights, float union_m, float tall_m) {
    std::string out = "Wind sway hang (r112l): candidates by the span of their keys:";
    char buf[220];
    for (const StaticBook::Taken& t : book.taken) {
        const H::Entry* const h = heights.Find(t.stream);
        const unsigned vs = static_cast<unsigned>(t.e.vs & 0xffffffffull);
        if (h == nullptr || !h->judged) {
            std::snprintf(buf, sizeof(buf), " vs %08x keys not read;", vs);
            out += buf;
            continue;
        }
        const float span = h->top - h->base;
        const float limit = SpanLimitWith(union_m, tall_m, t.e);
        const bool tall = span > std::min(H::MaxExtent, tall_m);
        const char* what = !tall                 ? "within the tall limit"
                           : span <= limit       ? "over it, kept: clearly hanging"
                           : ClearlyHanging(t.e) ? "refused: over the union limit"
                                                 : "refused: over it, not clearly hanging";
        std::snprintf(buf, sizeof(buf), " vs %08x keys %.2f m (%s; scene %.2f m, %.2f m up, limit %.1f m);", vs,
                      double(span), what, double(t.e.height), double(t.e.above), double(limit));
        out += buf;
    }
    if (book.taken.empty()) {
        out += " none";
    }
    if (out.size() > 700) {
        out.resize(697);
        out += "...";
    }
    return out;
}

"""

F5 = r"""        text += RouteText(routes, c.b->stream, c.focus);
"""
F5N = r"""        text += CutNote(routes, c.b->stream, CutKnob()); // bbport (r112l_hang-discard-lanterns)
"""

# ---- test_wind_hang_find.cpp -----------------------------------------------------------------------
T1 = r"""    // bbport (r112k_hang-lantern-verdict): skinned streams stay out, the route's tail, the focus, the knobs, the union
"""
T1P = r"""    // bbport (r112l_hang-discard-lanterns): cut-outs reach the static path, the static push gain, the tall rule
    {
        Expect(F::Cuts(&cut) && !F::Cuts(&solid) && !F::Cuts(static_cast<const Stage*>(nullptr)),
               "r112l: Cuts names a pixel shader that discards");
        Expect(F::WantedCutWith(true, true, true, &cut) && F::WantedCutWith(true, true, true, &solid) &&
                   !F::WantedCutWith(true, false, true, &cut) && F::WantedCutWith(true, false, true, &solid) &&
                   !F::WantedCutWith(true, true, false, &cut) && !F::WantedCutWith(false, true, true, &cut) &&
                   F::WantedCutWith(true, true, true, static_cast<const Stage*>(nullptr)),
               "r112l: a cut-out passes with the cut knob, an opaque one always; no Sway bit or no path: neither");
        Expect(F::ParseCut(nullptr) && F::ParseCut("1") && !F::ParseCut("0") && F::ParseCut("00") && F::ParseCut(""),
               "r112l: the cut knob is on unless exactly 0");
        Expect(F::ParseGain(nullptr) == F::GainDefault && F::ParseGain("0.5") == 0.5f && F::ParseGain("9") == 1.0f &&
                   F::ParseGain("-1") == 0.0f && F::ParseGain("x") == F::GainDefault,
               "r112l: the gain is held to 0..1");
        Expect(F::ParseTall(nullptr) == F::TallDefault && F::ParseTall("99") == F::UnionMax &&
                   F::ParseTall("0.01") == BbWindHang::MinExtent && F::ParseTall("x") == F::TallDefault &&
                   F::ParseTall("3") == 3.0f,
               "r112l: the tall limit is held to MinExtent..UnionMax");

        // the gain on a ramp byte
        Expect(F::GainRamp(255, 0.2f) == 51 && F::GainRamp(0, 0.2f) == 0 && F::GainRamp(255, 2.0f) == 255 &&
                   F::GainRamp(255, -1.0f) == 0 && F::GainRamp(100, 1.0f) == 100,
               "r112l: the gain scales the ramp byte");

        // the push at the strongest test wind: 3 to 10 cm at 4 m/s, less at 1.5 m/s
        const F::PushSource strong = F::PushSourceOf(true, 4.0f, 1.0f, 3.0f);
        const F::PushSource gale = F::PushSourceOf(true, 4.0f, 1.5f, 3.0f);
        const F::PushSource breeze = F::PushSourceOf(true, 1.5f, 1.0f, 3.0f);
        const F::PushSource breeze_gust = F::PushSourceOf(true, 1.5f, 1.5f, 3.0f);
        const float at_strong = F::StaticPush(strong, F::GainDefault);
        Expect(std::fabs(at_strong - 0.08f) < 1e-4f && std::fabs(F::StaticPush(gale, F::GainDefault) - 0.08f) < 1e-4f &&
                   at_strong >= 0.03f && at_strong <= 0.10f,
               "r112l: a static candidate is pushed 8 cm at 4 m/s, held by MaxAlong x gain also in the strongest gust");
        Expect(F::StaticPush(breeze, F::GainDefault) < 0.02f && F::StaticPush(breeze_gust, F::GainDefault) < 0.03f &&
                   F::StaticPush(breeze, F::GainDefault) < at_strong,
               "r112l: less at 1.5 m/s");
        Expect(F::StaticPush(strong, 1.0f) == strong.now && F::StaticPush(strong, 0.0f) == 0.0f &&
                   F::StaticPush(F::PushSourceOf(true, 0.0f, 1.0f, 3.0f), F::GainDefault) == 0.0f,
               "r112l: gain 1 is the old push, gain 0 and no wind none");

        // the tall rule: the b55 graveyard's candidates and a low one
        F::Entry e_graveyard; // stream E: 0.89 m scene box, 2.51 m over the ground
        e_graveyard.height = 0.89f;
        e_graveyard.above = 2.51f;
        F::Entry d_graveyard; // stream D: 0.94 m, 7.51 m up
        d_graveyard.height = 0.94f;
        d_graveyard.above = 7.51f;
        F::Entry low_place; // 1.2 m over the ground: a hook on a wall, a sign
        low_place.height = 0.9f;
        low_place.above = 1.2f;
        F::Entry big_place; // up to the 2 m the shape test allows
        big_place.height = 1.9f;
        big_place.above = 5.0f;
        Expect(F::ClearlyHanging(e_graveyard) && F::ClearlyHanging(d_graveyard) && !F::ClearlyHanging(low_place) &&
                   !F::ClearlyHanging(big_place),
               "r112l: a small mesh well over the ground clearly hangs");
        Expect(F::SpanLimitWith(12.0f, 2.5f, e_graveyard) == 12.0f && F::SpanLimitWith(12.0f, 2.5f, low_place) == 2.5f &&
                   F::SpanLimitWith(12.0f, 9.0f, low_place) == BbWindHang::MaxExtent &&
                   F::SpanLimitWith(12.0f, 2.5f, big_place) == 2.5f,
               "r112l: the union limit for a mesh that clearly hangs, the tall limit (held to 4 m) for the others");
        const std::uint32_t tall_base = BbWindSway::HeightKey(-39.48f);
        const std::uint32_t tall_top = BbWindHang::TopKey(-29.6f); // 9.88 m of keys: the union of the places of stream E
        const float lim_clear = F::SpanLimitWith(F::UnionDefault, F::TallDefault, e_graveyard);
        const float lim_low = F::SpanLimitWith(F::UnionDefault, F::TallDefault, low_place);
        BbWindHang::Entry kept;
        BbWindHang::Measure(kept, true, 100, &tall_base, &tall_top, 1.0, lim_clear);
        const BbWindHang::Measured kept_m =
            BbWindHang::Measure(kept, false, 100 + BbWindHang::JudgeFrames, &tall_base, &tall_top, 1.0, lim_clear);
        Expect(kept.judged && kept.fits && kept_m.swing && std::fabs(kept.top - kept.base - 9.88f) < 0.02f,
               "r112l: 9.88 m of keys of a clearly hanging lantern are the union of its places: kept");
        BbWindHang::Entry refused;
        BbWindHang::Measure(refused, true, 100, &tall_base, &tall_top, 1.0, lim_low);
        const BbWindHang::Measured refused_m =
            BbWindHang::Measure(refused, false, 100 + BbWindHang::JudgeFrames, &tall_base, &tall_top, 1.0, lim_low);
        Expect(refused.judged && !refused.fits && !refused_m.swing,
               "r112l: the same keys of a mesh that does not clearly hang: refused as too tall");

        // the lines
        BbWindHang::Book spans;
        spans.Note(7, 4096, 0, true, 100, 0x6a833138ull);
        spans.Note(8, 4096, 0, true, 100, 0x9da6aacbull);
        spans.Note(9, 4096, 0, true, 100, 0x63220f67ull);
        BbWindHang::Entry* const span_e = spans.Find(7);
        BbWindHang::Entry* const span_d = spans.Find(8);
        BbWindHang::Entry* const span_l = spans.Find(9);
        Expect(span_e != nullptr && span_d != nullptr && span_l != nullptr, "r112l: the test's book has its entries");
        if (span_e != nullptr && span_d != nullptr && span_l != nullptr) {
            const std::uint32_t d_base = BbWindSway::HeightKey(-34.78f);
            const std::uint32_t d_top = BbWindHang::TopKey(-33.84f);
            BbWindHang::Measure(*span_e, true, 100, &tall_base, &tall_top, 1.0, lim_clear);
            BbWindHang::Measure(*span_e, false, 100 + BbWindHang::JudgeFrames, &tall_base, &tall_top, 1.0, lim_clear);
            BbWindHang::Measure(*span_d, true, 100, &d_base, &d_top, 1.0, lim_clear);
            BbWindHang::Measure(*span_d, false, 100 + BbWindHang::JudgeFrames, &d_base, &d_top, 1.0, lim_clear);
            BbWindHang::Measure(*span_l, true, 100, &tall_base, &tall_top, 1.0, lim_low);
            BbWindHang::Measure(*span_l, false, 100 + BbWindHang::JudgeFrames, &tall_base, &tall_top, 1.0, lim_low);
            F::StaticBook shelf;
            F::Entry candidate = F::Evaluate(d, 4096, 500, 7, &lantern, ground_only, 100);
            candidate.vs = 0x6a833138ull;
            candidate.height = 0.89f;
            candidate.above = 2.51f;
            shelf.Set(7, candidate, 100);
            candidate.vs = 0x9da6aacbull;
            candidate.height = 0.94f;
            candidate.above = 7.51f;
            shelf.Set(8, candidate, 100);
            candidate.vs = 0x63220f67ull;
            candidate.height = 0.9f;
            candidate.above = 1.2f;
            shelf.Set(9, candidate, 100);
            const std::string tall_line = F::TallText(shelf, spans, F::UnionDefault, F::TallDefault);
            Expect(Has(tall_line, "vs 6a833138 keys 9.88 m (over it, kept: clearly hanging; scene 0.89 m, 2.51 m up, "
                                  "limit 12.0 m)") &&
                       Has(tall_line, "vs 9da6aacb keys 0.94 m (within the tall limit;") &&
                       Has(tall_line, "vs 63220f67 keys 9.88 m (refused: over it, not clearly hanging; scene 0.90 m, "
                                      "1.20 m up, limit 2.5 m)") &&
                       tall_line.size() <= 700,
                   "r112l: the keys' span line says kept, within and refused");
        }
        BbWindHang::Book unread;
        F::StaticBook none_taken;
        Expect(Has(F::TallText(none_taken, unread, F::UnionDefault, F::TallDefault), "none"), "r112l: no candidate");

        // the other lines and the survey's mark
        F::Stats cs;
        cs.gpu_asked = 300;
        cs.cut_asked = 120;
        cs.cut_passed = 40;
        const std::string cut_line = F::CutLine(cs, true, F::GainDefault, strong);
        Expect(Has(cut_line, "(r112l)") && Has(cut_line, "BB_WIND_HANG_STATIC_CUT=1") &&
                   Has(cut_line, "120 draws asked, 40 of a candidate stream") && Has(cut_line, "gain 0.20") &&
                   Has(cut_line, "pushed 0.080 m now") && Has(cut_line, "at most 0.080 m") &&
                   Has(F::CutLine(cs, false, 1.0f, breeze), "CUT=0"),
               "r112l: the counters line");
        const std::string once_l = F::OnceTextL(true, F::GainDefault, F::TallDefault);
        Expect(Has(once_l, "(r112l)") && Has(once_l, "'disc 1' with 'asked 0, book -'") &&
                   Has(once_l, "BB_WIND_HANG_STATIC_CUT=1") && Has(once_l, "0.20 of the sway's") &&
                   Has(once_l, "at most 0.080 m") && Has(once_l, "2.5 m (BB_WIND_HANG_STATIC_TALL") &&
                   Has(F::OnceTextL(false, 1.0f, 40.0f), "CUT=0"),
               "r112l: the once line");
        F::Routes cut_routes;
        cut_routes.Note(7, 'P', true, true, false, false, 1);
        cut_routes.Note(8, 'P', true, false, false, false, 1);
        Expect(F::CutNote(&cut_routes, 7, true) == " [cut-out: offered]" &&
                   Has(F::CutNote(&cut_routes, 7, false), "held back, CUT=0") && F::CutNote(&cut_routes, 8, true).empty() &&
                   F::CutNote(&cut_routes, 9, true).empty() && F::CutNote(nullptr, 7, true).empty(),
               "r112l: the survey marks a stream whose pixel shader discards");
        F::BoxSet cut_set;
        cut_set.Begin(0);
        cut_set.Add(Ground());
        F::Box cut_box = lantern;
        cut_box.stream = 7;
        cut_box.vertices = 777;
        cut_set.Add(cut_box);
        F::Draws cut_draws; // cam.vs is 0xabc
        cut_draws.Note(7, cam);
        F::StaticBook cut_book;
        const std::vector<std::string> cut_lines = F::SurveyLines(k, cut_set, cut_draws, cut_book, 10, &cut_routes);
        Expect(cut_lines.size() == 2 && Has(cut_lines[1], "route P bit 1 disc 1") &&
                   Has(cut_lines[1], "[cut-out: offered]") && cut_lines[1].size() <= F::LineCharsK,
               "r112l: the survey line of a cut-out stream carries the mark after its route");
    }

"""

# ---- vk_rasterizer.cpp ------------------------------------------------------------------------------
C1 = r"""                   BbWindHangFind::Wanted((pipeline->GetGraphicsKey().motion_vectors &
                                           Shader::MotionVectors::Sway) != 0,
                                          pipeline->GetStages()[u32(Shader::SwStage::Fragment)]) &&
                   // bbport (r112k_hang-lantern-verdict): a GPU-palette draw only when its stream is a hanging
                   // candidate (BB_WIND_HANG_STATIC_GPU); any other falls to the twig rule below as before
                   (r34_kind == Motion::Kind::Other || WindHangGpuStatic(pipeline)))
"""
C1N = r"""                   BbWindHangFind::WantedCut((pipeline->GetGraphicsKey().motion_vectors &
                                              Shader::MotionVectors::Sway) != 0,
                                             pipeline->GetStages()[u32(Shader::SwStage::Fragment)]) &&
                   // bbport (r112k_hang-lantern-verdict): a GPU-palette draw only when its stream is a hanging
                   // candidate (BB_WIND_HANG_STATIC_GPU); any other falls to the twig rule below as before
                   // bbport (r112l_hang-discard-lanterns): so does a draw of a pipeline whose pixel shader discards
                   // (a cut-out lantern or cage; WantedCut lets it through with BB_WIND_HANG_STATIC_CUT): only an
                   // opaque static draw (Kind::Other) goes on without that question
                   ((r34_kind == Motion::Kind::Other &&
                     !BbWindHangFind::Cuts(pipeline->GetStages()[u32(Shader::SwStage::Fragment)])) ||
                    WindHangGpuStatic(pipeline)))
"""

# ---- vk_rasterizer_effects.cpp ---------------------------------------------------------------------
E1 = r"""    if (!BbWindHangFind::GpuOn() || !BbWindHangStill::BoxAvailable() ||
"""
E1N = r"""    // bbport (r112l_hang-discard-lanterns): a pipeline whose pixel shader discards (a cut-out) is asked by its own knob
    // (BB_WIND_HANG_STATIC_CUT); r112k's GPU-palette knob (BB_WIND_HANG_STATIC_GPU) is for the opaque ones
    const bool cut = BbWindHangFind::Cuts(pipeline->GetStages()[u32(Shader::SwStage::Fragment)]);
    if (!(cut ? BbWindHangFind::CutOn() : BbWindHangFind::GpuOn()) || !BbWindHangStill::BoxAvailable() ||
"""
E2 = r"""    ++stats.gpu_asked;
"""
E2S = r"""    stats.cut_asked += cut ? 1u : 0u; // bbport (r112l_hang-discard-lanterns)
"""
E3 = r"""        ++stats.gpu_passed;
"""
E3S = r"""        stats.cut_passed += cut ? 1u : 0u; // bbport (r112l_hang-discard-lanterns)
"""
E4 = r"""    const float max_extent = placed != nullptr && placed->why == BbWindHangFind::Why::Ok
                                 ? BbWindHangFind::UnionKnob()
                                 : BbWindHang::MaxExtent;
"""
E4N = r"""    // bbport (r112l_hang-discard-lanterns): a keys' span beyond BB_WIND_HANG_STATIC_TALL is the union of the places of a
    // mesh that clearly hangs (SpanLimit: BB_WIND_HANG_STATIC_UNION); any other tall one is refused as r112 did
    const bool placed_ok = placed != nullptr && placed->why == BbWindHangFind::Why::Ok;
    const float max_extent = placed_ok ? BbWindHangFind::SpanLimit(*placed) : BbWindHang::MaxExtent;
"""
E5 = r"""    return BbWindHang::HangWord(frame_slot, view, slot, WindHangLiveOn() ? m.ramp : 0u);
"""
E5N = r"""    // bbport (r112l_hang-discard-lanterns): a static candidate's push is its ramp times BB_WIND_HANG_STATIC_GAIN (r112j's
    // roof scale multiplies on top; a skinned hanging thing keeps its push)
    const u32 hang_ramp = WindHangLiveOn() ? m.ramp : 0u;
    return BbWindHang::HangWord(frame_slot, view, slot,
                                placed_ok ? BbWindHangFind::GainRamp(hang_ramp, BbWindHangFind::GainKnob()) : hang_ramp);
"""
E6 = r"""            BbReport::Printf("%s\n",
                             BbWindHangFind::MeasureText(hang_static_book, hang_book).c_str());
"""
E6S = r"""            // bbport (r112l_hang-discard-lanterns): the cut-out draws, the static push, the keys' spans
            BbReport::Printf("%s\n", BbWindHangFind::CutLine(hang_find_stats, BbWindHangFind::CutOn(),
                                                              BbWindHangFind::GainKnob(), hang_source)
                                         .c_str());
            BbReport::Printf("%s\n", BbWindHangFind::TallText(hang_static_book, hang_book, BbWindHangFind::UnionKnob(),
                                                              BbWindHangFind::TallKnob())
                                         .c_str());
"""
E7 = r"""                                     .c_str()); // bbport (r112k_hang-lantern-verdict)
"""
E7S = r"""        BbReport::Printf("%s\n", BbWindHangFind::OnceTextL(BbWindHangFind::CutOn(), BbWindHangFind::GainKnob(),
                                                           BbWindHangFind::TallKnob())
                                     .c_str()); // bbport (r112l_hang-discard-lanterns)
"""

# ---- README.md -------------------------------------------------------------------------------------
R1 = r"""| `BB_WIND_HANG_FIND` |"""
R1P = r"""| `BB_WIND_HANG_STATIC_CUT` | Part of `BB_WIND_HANG_STATIC` (r112l; default on, exactly `0` gives r112k's routing). A draw of a pipeline whose pixel shader discards (a cut-out: the graveyard lanterns' shader is one) is offered to the static path like an opaque one, when its mesh is a hanging candidate by the same box rules; r112i turned every such pipeline away before any verdict (the survey's `disc 1`, `asked 0`). A cut-out that is no candidate is left to the plant and twig rules as before. Log: "Wind sway hang (r112l)" once and every 600 frames. |
| `BB_WIND_HANG_STATIC_GAIN` | Part of `BB_WIND_HANG_STATIC` (r112l; 0 to 1, default `0.2`; text that is no number gives the default). The share of the sway's push a static hanging candidate gets: at 4 m/s with `BB_WIND_SWAY=3` the push of 0.4 m (held to the sway's limit) becomes 8 cm, at 1.5 m/s about 1 to 2 cm; `1` is r112k's push. Hanging things with a skeleton keep theirs. |
| `BB_WIND_HANG_STATIC_TALL` | Part of `BB_WIND_HANG_STATIC` (r112l; metres, 0.15 to 40, default `2.5`). A mesh drawn at several places spans the union of them in the keys the GPU judge reads; a static candidate whose keys span more than this (held to 4 m) is kept (up to `BB_WIND_HANG_STATIC_UNION`) only when it clearly hangs: its scene box at most 1.5 m tall and its bottom 2 m or more over the ground. Any other is refused as too tall. |
"""

EDITS = {
NF: [
('rep', F1, "", F1N),
('ins', F2, F2P, ""),
('ins', F3, "", F3N),
('ins', F4, F4P, ""),
('ins', F5, "", F5N),
],
NT: [
('ins', T1, T1P, ""),
],
RC: [
('rep', C1, "", C1N),
],
RE: [
('rep', E1, "", E1N),
('ins', E2, "", E2S),
('ins', E3, "", E3S),
('rep', E4, "", E4N),
('rep', E5, "", E5N),
('ins', E6, "", E6S),
('ins', E7, "", E7S),
],
RM: [
('ins', R1, R1P, ""),
],
}

ORDER = (NF, NT, RC, RE, RM)


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


def text_checks(texts, olds):
    """The ties a compiler cannot check."""
    nf, nt, rc, re_ = texts[NF], texts[NT], texts[RC], texts[RE]
    for path in ORDER:
        if path == RM:
            continue
        if balance(texts[path]) != balance(olds[path]):
            raise SystemExit("text check: %s: braces, parens or brackets changed by %r" %
                             (path, tuple(a - b for a, b in zip(balance(texts[path]), balance(olds[path])))))
    for needle in ("inline bool ParseCut(", "inline bool CutOn()", "inline bool Cuts(", "inline bool WantedCutWith(",
                   "inline bool WantedCut(", "inline float ParseGain(", "inline float GainKnob()", "inline float ParseTall(",
                   "inline float TallKnob()", "inline std::uint32_t GainRamp(", "inline bool ClearlyHanging(",
                   "inline float SpanLimitWith(", "inline float SpanLimit(", "inline float StaticPush(",
                   "inline std::string CutNote(", "inline std::string OnceTextL(", "inline std::string CutLine(",
                   "inline std::string TallText(", "cut_asked", "cut_passed"):
        if needle not in nf:
            raise SystemExit("text check: %s missing in the header" % needle)
    # order of definitions
    def before(a, b, what):
        if nf.index(a) > nf.index(b):
            raise SystemExit("text check: %s" % what)
    before("inline bool CutKnob()", "inline bool WantedCut(", "CutKnob must precede WantedCut")
    before("inline bool Cuts(", "inline bool WantedCutWith(", "Cuts must precede WantedCutWith")
    before("inline bool StaticOn()", "inline bool ParseCut(", "StaticOn must precede CutOn")
    before("inline float UnionKnob()", "inline float SpanLimit(", "UnionKnob must precede SpanLimit")
    before("inline float TallKnob()", "inline float SpanLimit(", "TallKnob must precede SpanLimit")
    before("inline float ParseUnion(", "inline float ParseTall(", "UnionMax is defined at the top; fine")
    before("struct PushSource", "inline float StaticPush(", "PushSource must precede StaticPush")
    before("class Routes", "inline std::string CutNote(", "Routes must precede CutNote")
    before("struct Entry {", "inline bool ClearlyHanging(", "Entry must precede ClearlyHanging")
    before("class StaticBook", "inline std::string TallText(", "StaticBook must precede TallText")
    before("struct Stats {", "inline std::string CutLine(", "Stats must precede CutLine")
    before("inline std::string CutNote(", "inline std::vector<std::string> SurveyLines(", "CutNote must precede the survey")
    before("inline bool CutKnob()", "text += CutNote(routes, c.b->stream, CutKnob());", "CutKnob must precede its use in the survey")
    if nf.count("LineCharsK = 560") != 1:
        raise SystemExit("text check: LineCharsK")
    # the call chain in the rasterizer
    if rc.count("BbWindHangFind::WantedCut(") != 1 or rc.count("BbWindHangFind::Wanted(") != 0 or \
            rc.count("WindHangGpuStatic(pipeline)") != 1 or rc.count("BbWindHangFind::Cuts(") != 1:
        raise SystemExit("text check: the rasterizer's routing clause")
    if rc.index("BbWindHangFind::WantedCut(") > rc.index("WindHangGpuStatic(pipeline)"):
        raise SystemExit("text check: WantedCut must be tested before the stream's verdict")
    for needle in ("const bool cut = BbWindHangFind::Cuts(", "cut ? BbWindHangFind::CutOn() : BbWindHangFind::GpuOn()",
                   "stats.cut_asked += cut ? 1u : 0u;", "stats.cut_passed += cut ? 1u : 0u;",
                   "BbWindHangFind::SpanLimit(*placed)", "BbWindHangFind::GainRamp(hang_ramp, BbWindHangFind::GainKnob())",
                   "BbWindHangFind::CutLine(", "BbWindHangFind::TallText(", "BbWindHangFind::OnceTextL("):
        if needle not in re_:
            raise SystemExit("text check: %s missing in the effects file" % needle)
    if re_.index("const bool placed_ok") > re_.index("placed_ok ? BbWindHangFind::GainRamp("):
        raise SystemExit("text check: placed_ok is used before its definition")
    if re_.index("BbWindHangFind::CutLine(") > re_.index("hang_find_stats = {};") or \
            re_.index("BbWindHangFind::TallText(") > re_.index("hang_find_stats = {};"):
        raise SystemExit("text check: the r112l lines must print before the stats reset")
    if re_.index("const BbWindHangFind::PushSource hang_source") > re_.index("BbWindHangFind::CutLine("):
        raise SystemExit("text check: hang_source is used before its definition")
    if re_.index("const bool cut = BbWindHangFind::Cuts(") > re_.index("stats.cut_asked += cut"):
        raise SystemExit("text check: cut is used before its definition")
    if "r112l: the keys' span line says kept, within and refused" not in nt or \
            "r112l: the survey line of a cut-out stream carries the mark after its route" not in nt:
        raise SystemExit("text check: the tests are missing")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112L_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == NF and "OnceTextK(" not in cur:
            raise SystemExit("REFUSED: r112k_hang-lantern-verdict must be applied (OnceTextK)")
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
            tmp = full + ".r112ltmp"
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
        tmp = full + ".r112ltmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


if __name__ == "__main__":
    main()
