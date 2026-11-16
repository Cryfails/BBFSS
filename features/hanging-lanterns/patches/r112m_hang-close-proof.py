# r112m_hang-close-proof: FEATURE fix on top of r112l_hang-discard-lanterns (r112k, r112j ... all applied in the tree),
# behind r112's own knob BB_WIND_HANG=1 (off by default). Six files edited, no new file, no shader change that is on
# without the proof knob (bbport_wind_hang_find.h, bbport_wind_hang.h, test_wind_hang_find.cpp,
# vk_rasterizer_effects.cpp, lifter/lift_stage.cpp, README.md; vk_rasterizer.h and vk_rasterizer.cpp are NOT touched).
#
# GRADES: (1), (2) and the same-bottom push of (1) are FEATURE (BB_WIND_HANG). The candidate lines of (1) with
# BB_WIND_HANG_FIND=1 and BB_WIND_HANG_PROOF of (3) (one hook block in lift_stage.cpp) are TOOL grade (test aids: they
# go to dev/test-tools, the rest to the feature branch).
#
# THE EVIDENCE (b57: slot_b57_result.txt, b57_s4.log graveyard, b57_reports.txt)
#  - The 97f2d384 streams A (1429 verts, 0.21 m) and B (2491 verts, 0.88 m) are asked 1881, passed 1880, book 'candidate'.
#    B is in r112's pushed list; A is not, and no line says why. WHY NO LINE (read in the code, not a guess): the
#    candidate lists of r112j (TakenLine), r112k (MeasureText) and r112l (TallText) keep the NEWEST TakenMost = 6
#    candidates (StaticBook::Set drops the oldest), and the graveyard has 8: A and B were judged first and fell off
#    every list ("candidates 6" while the verdict count says 8 candidate); r112's 'meshes' line (MeshesText) lists the
#    3 TALLEST streams that hang, and the 0.21 m one is the shortest. So the b57 log has NO line about A's state at
#    all: not 'unfit', not 'moving', not 'pushed'. r112m prints every candidate of the scene with its state.
#  - WHAT A WOULD GET EVEN WHEN PUSHED (code, shaders and HangScale): the shaders scale a mesh shorter than 1.2 m by its
#    height over HangFull (HangScale, at least 0.1): the still top, the full distance and the PUSH. A (0.21 m) has scale
#    0.175, B (0.88 m) 0.73; r112l's gain 0.2 on the ramp then moves A's bottom 0.175 x 0.2 x push = 1.0 cm at the push
#    now (0.285 m at gust 0.8) and B's 0.73 x 0.2 x 0.285 = 4.2 cm: A, the flame or glass INSIDE B's cage, would move a
#    quarter of the cage that holds it, and r112l's line 'pushed 0.057 m' (the table value x gain) is not what any
#    mesh moves by. Under 1 cm at 26 m is under a pixel: not visible even when pushed.
#  - THE TALL REFUSAL NEVER FIRES: the kept 9.87 m and 9.38 m 'keys' are the UNION of the places a mesh is drawn at
#    (the min and max world y of every draw of the stream while its slot lives), not a length. A refusal by the keys'
#    span can only say 'a union'; the real hanging length is the mesh's own box in the ray traced scene.
#  - THE PICTURES: the graveyard camera stood about 26 m from the lantern (a dot at 548,225); the a/b/c difference
#    equalled the off pair (the flame's flicker): no lean could be read.
#
# WHAT THIS CHANGES
#  (1) WHY A IS NOT PUSHED, AND THE SAME PUSH FOR EVERY SIZE (BB_WIND_HANG_STATIC_SAME, default 1; exactly 0 = r112l):
#      - a line per candidate of the scene (GatherCands, CandLines; nearest first, at most 12; with BB_WIND_HANG_FIND=1
#        only, the header line always with the static path): 'Wind sway hang (r112m): A vs 97f2d384 (2 places, 1429
#        verts) dist 4.2 m: scene box 0.21 m tall 0.29 wide 6.29 m up; keys span 0.21 m vs scene 0.21 m; <state>', with
#        the state one of: PUSHED (keys, scale, the bottom's push now), TOO TALL, no GPU-judge entry (never drawn through
#        the hang path), the judge's window open, the judge found it moving (box grew N mm) or refused by r112h's rules
#        (dev -2), the hang book has no entry, measuring, held as moving, unfit (span under 0.15 m or over its limit).
#        The header says candidates, pushed, too tall, without a judge entry, the nearest distance and the live gain.
#      - the ramp of a static candidate is made so that its BOTTOM moves by min(scale, gain) x push: every size moves as
#        far as a mesh of the gain's scale (SameRamp: ramp x min(1, gain / scale)); the lantern parts then move together
#        (A 1.75 x 0.285 = 5.0 cm, B 5.7 cm at the push now: at most 0.08 m at 4 m/s, as r112l's target) and the 3 to
#        10 cm target holds for a 0.2 m part. BB_WIND_HANG_STATIC_SAME=0 gives r112l's ramp x gain (GainRamp).
#      - BB_WIND_HANG_STATIC_GAIN is now LIVE where the test tools' knobs are built (set:/unset: in a slot job; else the
#        environment's value as before): the proof pair of a route 'gain 1 against the default' in ONE game.
#  (2) THE TALL RULE ON THE REAL LENGTH: a static candidate whose scene box is taller than BB_WIND_HANG_STATIC_TALL (2.5 m,
#      TooTall) is refused in WindHangWord (no hang word, counted: 'draws refused as too tall'), and every candidate line
#      says 'TOO TALL' with both numbers; the keys' span is printed next to the scene box (for stream E: 9.87 m keys, 0.89 m
#      box, 2 places) so the log says which of the two is the length. With the defaults a box is at most 2.0 m
#      (BB_WIND_HANG_STATIC_HEIGHT), so the rule only fires when that knob is raised (up to 4 m): say so, do not call it a
#      fix of anything at the defaults.
#  (3) THE PROOF TINT (TOOL, BB_WIND_HANG_PROOF=1; needs BB_WIND_HANG): in the lifter's vertex shaders every output
#      attribute of a PUSHED hang draw (a hang word with a ramp above 0) moves 0.4 toward cyan (0, 1, 1), as the twigs'
#      proof tints toward yellow, so a still shows which meshes are pushed (the keys-filling words, ramp 0, are not
#      tinted; with BB_WIND_HANG_PUSH=0 live nothing is pushed and the tint goes). Only the lifter has it (the twigs'
#      tint is there too). The knob is read at shader build time: a cold shader cache run is needed when it changes.
#  Shared lines touched (the twig and glass lanes work on lift_stage.cpp, vk_rasterizer_effects.cpp and the pick):
#    lift_stage.cpp: ONE block after the hang code's own 'Open(top_merge); }' (hang_on && ProofOn()); nothing of the twigs'.
#    vk_rasterizer_effects.cpp: the hang functions only: the live gain next to WindHangLiveOn, WindHangWord (the tall
#    refusal after max_extent, the ramp in its return), the report block of the static line (candidate lines after the
#    r112l TallText) and the once-line. The pick tool (twigs' and glass's) is NOT touched.
#
# Off: BB_WIND_HANG unset: StaticOn() is false, ProofOn() false (no tint emitted: the lifter block sits inside
# `if (hang_on && BbWindHang::ProofOn())`), the new report lines sit inside `if (BbWindHangFind::StaticOn())`, the tall
# test and SameRamp are in WindHangWord (the hang path), the live gain knob is created on first use there.
# Cost: the candidate lines walk the scene's boxes (about 400) once every 600 frames with a hash lookup each (a few
# microseconds, only with BB_WIND_HANG=1; the lines only with BB_WIND_HANG_FIND=1); WindHangWord adds one compare and
# one live-knob read per hang draw. GPU: none (the same shaders; the tint only with the proof knob, ~20 instructions per
# vertex of a hang pipeline). Memory: a vector of at most 400 small structs, freed at once.
#
# Use: python -I -X utf8 r112m_hang-close-proof.py check | apply | revert
# Root: R112M_ROOT, else <tree>. CRLF kept. apply backs the originals up in r112m_backup next to this script;
# revert takes out exactly what apply put in. Needs r112l applied (the anchors are its texts).
import os, re, sys

ROOT = os.environ.get("R112M_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112m_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RE = RV + "vk_rasterizer_effects.cpp"
NF = "engine/gpu/shim/bbport_wind_hang_find.h"
NH = "engine/gpu/shim/bbport_wind_hang.h"
NT = "engine/tests/test_wind_hang_find.cpp"
LS = "engine/gpu/shim/lifter/lift_stage.cpp"
RM = "README.md"

# ---- bbport_wind_hang.h ----------------------------------------------------------------------------
H1 = r"""/// Bytes of the sway words ObjectMotion makes when the plant sway is on: r89's region, and with
"""
H1P = r"""// bbport (r112m_hang-close-proof, TOOL): BB_WIND_HANG_PROOF=1 (needs BB_WIND_HANG): the lifter's vertex shaders tint the
// outputs of a PUSHED hang draw (a hang word whose ramp is above 0) toward cyan by ProofShare, so that a still shows which
// meshes are pushed. Read when a shader is built; off: nothing is emitted.
inline constexpr float ProofShare = 0.4f;

[[nodiscard]] inline bool ParseProof(const char* text) {
    return text != nullptr && text[0] == '1' && text[1] == 0;
}

[[nodiscard]] inline bool ProofOn() {
    static const bool on = KnobOnce().on && ParseProof(std::getenv("BB_WIND_HANG_PROOF"));
    return on;
}

"""

# ---- bbport_wind_hang_find.h -----------------------------------------------------------------------
F1 = r"""    std::uint64_t cut_passed = 0; ///< bbport (r112l): and those of a candidate stream
"""
F1N = r"""    std::uint64_t too_tall = 0;   ///< bbport (r112m): draws of a static candidate refused as too tall (its scene box)
"""

F2 = r"""/// The survey: a header line and up to ListMost candidate lines (a mesh of the scene of
"""
F2P = r"""// bbport (r112m_hang-close-proof): BB_WIND_HANG_STATIC_SAME (default on; exactly 0 = r112l): the ramp of a static candidate
// makes its BOTTOM move by min(scale, gain) x push (scale: the shaders' HangScale of its keys' height), so a 0.21 m part
// moves as far as the 0.88 m cage it hangs in (r112l: scale x gain x push: 1.0 cm against 4.2 cm).
inline constexpr std::size_t CandMost = 12; ///< candidate lines of one report at most

[[nodiscard]] inline bool ParseSame(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == 0);
}

[[nodiscard]] inline bool SameKnob() {
    static const bool on = ParseSame(std::getenv("BB_WIND_HANG_STATIC_SAME"));
    return on;
}

[[nodiscard]] inline float ClampGain(float gain) {
    return std::isnan(gain) ? 0.0f : std::clamp(gain, 0.0f, 1.0f);
}

[[nodiscard]] inline float ClampScale(float scale) {
    return std::clamp(std::isnan(scale) ? 1.0f : scale, H::HangScaleMin, 1.0f);
}

/// A static candidate's ramp byte: with `same` the ramp times min(1, gain / scale) (the bottom then moves min(scale, gain) x
/// push), else r112l's ramp times gain (GainRamp: the bottom moves scale x gain x push).
[[nodiscard]] inline std::uint32_t SameRamp(std::uint32_t ramp, float gain, float scale, bool same) {
    const float g = ClampGain(gain);
    const float f = same ? std::min(1.0f, g / ClampScale(scale)) : g;
    return static_cast<std::uint32_t>(std::lround(float(ramp) * f));
}

/// How far the bottom of a static candidate of scale `scale` moves (m) when the push table says `now`.
[[nodiscard]] inline float BottomPush(float now, float gain, float scale, bool same) {
    const float g = ClampGain(gain);
    const float s = ClampScale(scale);
    return now * (same ? std::min(s, g) : s * g);
}

/// The real hanging length of a static candidate is its mesh's own box in the ray traced scene (the keys of its slot span
/// the union of all the places the mesh is drawn at): refused when that box is taller than the tall limit.
[[nodiscard]] inline bool TooTall(const Entry& e, float tall_m) {
    return e.height > tall_m;
}

/// One candidate of the scene now, as the report lines see it.
struct CandInfo {
    std::uint64_t stream = 0;
    Entry e;                        ///< the static book's entry: vs, verts, scene height, width, height over the ground
    std::array<float, 6> box{};     ///< its nearest box in the scene
    float dist = -1.0f;             ///< m from the camera to that box's middle (-1: the camera was not read)
    unsigned places = 1;            ///< scene boxes of the stream: places a mesh is drawn at
    bool hang = false;              ///< r112's book knows the stream
    bool judged = false, fits = false, moving = false;
    float span = 0.0f;              ///< the keys of its slot: top minus base (m), when judged
    std::uint32_t frames = 0;
    int judge = 0;                  ///< the GPU judge: 0 no entry, 1 judging, 2 still, 3 moved
    float dev = 0.0f;               ///< its box growth (m); -2: refused by r112h's rules; -1: no key ever offered
    std::uint64_t judge_draws = 0;
};

/// The scene's candidates (a stream with a candidate verdict in the static book), one per stream (`places` boxes counted),
/// nearest first (the camera unread: in the scene's order). `JudgeBook::Find(stream)` gives null or an entry with `state`
/// (Judging, Still, Moved: 0, 1, 2), `dev` and `draws` (BbWindHangStill::BoxBook).
template <class JudgeBook>
[[nodiscard]] inline std::vector<CandInfo> GatherCands(const BoxSet& set, const StaticBook& book, H::Book& heights,
                                                       const JudgeBook& judge) {
    std::vector<CandInfo> out;
    for (const Box& b : set.All()) {
        if (b.stream == 0) {
            continue;
        }
        const Entry* const e = book.Find(b.stream);
        if (e == nullptr || e->why != Why::Ok) {
            continue;
        }
        float dist = -1.0f;
        if (set.camera_ok) {
            const float dx = 0.5f * (b.box[0] + b.box[3]) - set.camera[0];
            const float dy = 0.5f * (b.box[1] + b.box[4]) - set.camera[1];
            const float dz = 0.5f * (b.box[2] + b.box[5]) - set.camera[2];
            dist = std::sqrt(dx * dx + dy * dy + dz * dz);
        }
        const auto same = std::find_if(out.begin(), out.end(),
                                       [&](const CandInfo& c) { return c.stream == b.stream; });
        if (same != out.end()) {
            ++same->places;
            if (dist >= 0.0f && (same->dist < 0.0f || dist < same->dist)) {
                same->dist = dist;
                same->box = b.box;
            }
            continue;
        }
        CandInfo c;
        c.stream = b.stream;
        c.e = *e;
        c.box = b.box;
        c.dist = dist;
        if (const H::Entry* const h = heights.Find(b.stream)) {
            c.hang = true;
            c.judged = h->judged;
            c.fits = h->fits;
            c.moving = h->moving;
            c.frames = h->frames;
            c.span = h->judged ? h->top - h->base : 0.0f;
        }
        if (const auto* const j = judge.Find(b.stream)) {
            c.judge = 1 + static_cast<int>(j->state);
            c.dev = j->dev;
            c.judge_draws = static_cast<std::uint64_t>(j->draws);
        }
        out.push_back(c);
    }
    std::stable_sort(out.begin(), out.end(), [](const CandInfo& a, const CandInfo& b) {
        if ((a.dist < 0.0f) != (b.dist < 0.0f)) {
            return b.dist < 0.0f;
        }
        return a.dist < b.dist;
    });
    return out;
}

enum class CandClass : std::uint8_t { Pushed, Tall, NoJudge, Other };

[[nodiscard]] inline CandClass ClassOf(const CandInfo& c, float tall_m) {
    if (TooTall(c.e, tall_m)) {
        return CandClass::Tall;
    }
    if (c.judge == 3) {
        return CandClass::Other;
    }
    if (c.hang && !c.moving && c.judged && c.fits) {
        return CandClass::Pushed;
    }
    if (!c.hang && c.judge == 0) {
        return CandClass::NoJudge;
    }
    return CandClass::Other;
}

/// Why one candidate is or is not pushed (the state part of its line).
[[nodiscard]] inline std::string CandState(const CandInfo& c, float tall_m, float gain, bool same, float push_now) {
    char buf[320];
    if (TooTall(c.e, tall_m)) {
        std::snprintf(buf, sizeof(buf),
                      "TOO TALL: its scene box is %.2f m, over %.1f m (BB_WIND_HANG_STATIC_TALL): refused, no hang word",
                      double(c.e.height), double(tall_m));
    } else if (c.judge == 3 && c.dev < -1.5f) {
        std::snprintf(buf, sizeof(buf),
                      "refused by r112h's rules (the hunter's gear, a figure, indoors or unplaced): held as moving");
    } else if (c.judge == 3) {
        std::snprintf(buf, sizeof(buf), "the GPU judge found it moving (its box grew %.0f mm): held as moving",
                      double(c.dev) * 1000.0);
    } else if (!c.hang && c.judge == 0) {
        std::snprintf(buf, sizeof(buf),
                      "no GPU-judge entry: no draw of it has taken a sway slot (never drawn through the hang path)");
    } else if (!c.hang && c.judge == 1) {
        std::snprintf(buf, sizeof(buf), "the GPU judge's window is open (judging): its word has no motion yet");
    } else if (!c.hang) {
        std::snprintf(buf, sizeof(buf), "the GPU judge says still, but r112's book has no entry for it");
    } else if (c.moving) {
        std::snprintf(buf, sizeof(buf), "held as moving by r112's book");
    } else if (!c.judged) {
        std::snprintf(buf, sizeof(buf), "measuring: the keys of its slot are not read yet (a word with no motion)");
    } else if (!c.fits) {
        if (c.span < H::MinExtent) {
            std::snprintf(buf, sizeof(buf), "unfit: its keys span %.2f m, under %.2f m", double(c.span),
                          double(H::MinExtent));
        } else {
            std::snprintf(buf, sizeof(buf), "unfit: its keys span %.2f m, over its limit %.1f m", double(c.span),
                          double(SpanLimitWith(UnionKnob(), tall_m, c.e)));
        }
    } else {
        const float scale = H::HangScale(0.0f, c.span);
        std::snprintf(buf, sizeof(buf), "PUSHED: scale %.2f, its bottom moves %.3f m now (push %.3f m, gain %.2f, %s)",
                      double(scale), double(BottomPush(push_now, gain, scale, same)), double(push_now),
                      double(ClampGain(gain)), same ? "same bottom push for every size" : "scaled by its height");
    }
    return std::string(buf);
}

/// The lines of r112m every ReportFrames frames: the header (counts, the nearest candidate, the gain, the knobs), then with
/// `lines` (BB_WIND_HANG_FIND=1) one line per candidate, nearest first, at most CandMost.
[[nodiscard]] inline std::vector<std::string> CandLines(const std::vector<CandInfo>& cands, const Stats& s, float tall_m,
                                                        float gain, bool same, float push_now, bool lines, bool proof) {
    std::size_t pushed = 0, tall = 0, nojudge = 0;
    for (const CandInfo& c : cands) {
        const CandClass k = ClassOf(c, tall_m);
        pushed += k == CandClass::Pushed ? 1u : 0u;
        tall += k == CandClass::Tall ? 1u : 0u;
        nojudge += k == CandClass::NoJudge ? 1u : 0u;
    }
    char near_text[48] = "none";
    if (!cands.empty() && cands.front().dist >= 0.0f) {
        std::snprintf(near_text, sizeof(near_text), "%.1f m (vs %08x)", double(cands.front().dist),
                      static_cast<unsigned>(cands.front().e.vs & 0xffffffffull));
    }
    char buf[640];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112m): candidates in the scene now %zu (%zu pushed, %zu too tall, %zu with no GPU-judge "
                  "entry, %zu other); nearest %s; %llu draws refused as too tall (scene box over %.1f m, "
                  "BB_WIND_HANG_STATIC_TALL); static gain %.2f (live), same-bottom rule %d (BB_WIND_HANG_STATIC_SAME), "
                  "table push now %.3f m; proof tint %s (BB_WIND_HANG_PROOF)",
                  cands.size(), pushed, tall, nojudge, cands.size() - pushed - tall - nojudge, near_text,
                  static_cast<unsigned long long>(s.too_tall), double(tall_m), double(ClampGain(gain)), same ? 1 : 0,
                  double(push_now), proof ? "ON" : "off");
    std::vector<std::string> out;
    out.push_back(Cap(buf));
    for (std::size_t i = 0; lines && i < cands.size() && i < CandMost; ++i) {
        const CandInfo& c = cands[i];
        char dist[16], keys[24];
        if (c.dist >= 0.0f) {
            std::snprintf(dist, sizeof(dist), "%.1f", double(c.dist));
        } else {
            std::snprintf(dist, sizeof(dist), "n/a");
        }
        if (c.hang && c.judged) {
            std::snprintf(keys, sizeof(keys), "%.2f m", double(c.span));
        } else {
            std::snprintf(keys, sizeof(keys), "not read");
        }
        const std::string state = CandState(c, tall_m, gain, same, push_now);
        std::snprintf(buf, sizeof(buf),
                      "Wind sway hang (r112m): %c vs %08x (%u place%s, %u verts) dist %s m: scene box %.2f m tall %.2f m "
                      "wide, %.2f m up; keys span %s (the union of its places) vs scene box %.2f m; %s",
                      char('A' + int(i)), static_cast<unsigned>(c.e.vs & 0xffffffffull), c.places,
                      c.places == 1 ? "" : "s", c.e.verts, dist, double(c.e.height), double(c.e.width), double(c.e.above),
                      keys, double(c.e.height), state.c_str());
        out.push_back(Cap(buf));
    }
    return out;
}

/// The once-line of r112m: why A had no line, the same-bottom push, the tall rule's number, the proof tint.
[[nodiscard]] inline std::string OnceTextM(bool same, bool proof, float tall_m) {
    char buf[1536];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112m): the candidate lists of r112j, r112k and r112l keep the newest %zu candidates "
                  "(the oldest, a lantern's streams among them, fall off) and r112's meshes line the 3 tallest: the "
                  "r112m lines list every candidate of the scene nearest first with its state (the candidate lines with "
                  "BB_WIND_HANG_FIND=1); a static candidate's keys span the UNION of the places its mesh is drawn at: its "
                  "length is its scene box, refused over %.1f m (BB_WIND_HANG_STATIC_TALL), counted in 'too tall'; the "
                  "bottom of every static candidate moves by gain x push (a short part as far as a long one: "
                  "BB_WIND_HANG_STATIC_SAME=%d); BB_WIND_HANG_STATIC_GAIN is live where the test tools' knobs are built; "
                  "proof tint (BB_WIND_HANG_PROOF=%d, TOOL): pushed hang draws of the lifter's shaders tint toward cyan",
                  TakenMost, double(tall_m), same ? 1 : 0, proof ? 1 : 0);
    return std::string(buf);
}

"""

# ---- test_wind_hang_find.cpp -----------------------------------------------------------------------
T1 = r"""    // bbport (r112k_hang-lantern-verdict): skinned streams stay out, the route's tail, the focus, the knobs, the union
"""
T1P = r"""    // bbport (r112m_hang-close-proof): the candidates' state lines, the tall rule on the scene box, the same-bottom push
    {
        Expect(F::ParseSame(nullptr) && F::ParseSame("1") && !F::ParseSame("0") && F::ParseSame("00") && F::ParseSame(""),
               "r112m: the same-bottom knob is on unless exactly 0");
        Expect(BbWindHang::ParseProof("1") && !BbWindHang::ParseProof(nullptr) && !BbWindHang::ParseProof("0") &&
                   !BbWindHang::ParseProof("11") && !BbWindHang::ParseProof(""),
               "r112m: the proof knob is exactly 1");

        // the push of a short part against a long one (A 0.21 m and B 0.88 m of the graveyard lantern)
        const float scale_a = BbWindHang::HangScale(0.0f, 0.21f);
        const float scale_b = BbWindHang::HangScale(0.0f, 0.88f);
        Expect(std::fabs(scale_a - 0.175f) < 1e-4f && std::fabs(scale_b - 0.7333f) < 1e-3f && scale_b > scale_a,
               "r112m: the shaders' scales of the two parts");
        const float push_table = 0.285f; // the table's push at gust 0.8, 4 m/s, BB_WIND_SWAY 3
        const float old_a = F::BottomPush(push_table, F::GainDefault, scale_a, false);
        const float old_b = F::BottomPush(push_table, F::GainDefault, scale_b, false);
        const float new_a = F::BottomPush(push_table, F::GainDefault, scale_a, true);
        const float new_b = F::BottomPush(push_table, F::GainDefault, scale_b, true);
        Expect(old_a < 0.011f && old_b > 0.04f && std::fabs(new_b - 0.057f) < 1e-3f && std::fabs(new_a - 0.0499f) < 1e-3f &&
                   std::fabs(new_a - new_b) < 0.01f,
               "r112m: r112l moved the part a quarter of the cage, the same-bottom rule moves both alike");
        // the ramp byte gives that bottom in the shader's own product (ramp / 255 x scale x push)
        const float shader_b = scale_b * float(F::SameRamp(255, F::GainDefault, scale_b, true)) / 255.0f * push_table;
        const float shader_a = scale_a * float(F::SameRamp(255, F::GainDefault, scale_a, true)) / 255.0f * push_table;
        const float shader_old = scale_a * float(F::SameRamp(255, F::GainDefault, scale_a, false)) / 255.0f * push_table;
        Expect(std::fabs(shader_b - new_b) < 1e-3f && std::fabs(shader_a - new_a) < 1e-3f && std::fabs(shader_old - old_a) < 1e-3f,
               "r112m: SameRamp and BottomPush agree");
        Expect(F::SameRamp(255, 0.2f, 1.0f, true) == 51 && F::SameRamp(255, 0.2f, 1.0f, false) == 51 &&
                   F::SameRamp(255, 0.2f, scale_a, false) == F::GainRamp(255, 0.2f) &&
                   F::SameRamp(255, 0.2f, scale_a, true) == 255 && F::SameRamp(255, 1.0f, 0.1f, true) == 255 &&
                   F::SameRamp(255, 0.0f, 0.5f, true) == 0 && F::SameRamp(0, 0.2f, 0.5f, true) == 0 &&
                   F::SameRamp(255, 0.2f, std::nanf(""), true) == 51,
               "r112m: the ramp byte (scale 1 and a short part, SAME=0 is r112l's, gain 0, no number)");

        // the tall rule reads the scene box, not the keys
        F::Entry tall_e;
        tall_e.height = 2.6f;
        F::Entry edge_e;
        edge_e.height = 2.5f;
        F::Entry lantern_e;
        lantern_e.height = 0.89f;
        lantern_e.above = 10.49f;
        Expect(F::TooTall(tall_e, 2.5f) && !F::TooTall(edge_e, 2.5f) && !F::TooTall(lantern_e, 2.5f) &&
                   F::TooTall(lantern_e, 0.5f),
               "r112m: too tall is a scene box over the tall limit (the keys' union is no length)");

        // the lines: four candidates of one scene, one of them at two places
        struct JudgeEntry {
            enum class JState : std::uint8_t { Judging, Still, Moved } state = JState::Judging;
            float dev = 0.0f;
            std::uint64_t draws = 0;
        };
        struct OneJudge {
            std::uint64_t stream = 0;
            JudgeEntry e;
            const JudgeEntry* Find(std::uint64_t s) const {
                return s == stream && stream != 0 ? &e : nullptr;
            }
        };
        F::BoxSet set;
        set.Begin(0);
        set.camera_ok = true;
        set.camera = {-34.0f, -33.0f, 103.0f};
        set.Add(Ground());
        set.Add(MakeBox(7, -34.5f, -36.0f, 107.0f, -33.5f, -35.12f, 107.8f)); // B: 5.1 m away
        set.Add(MakeBox(7, -34.5f, -36.0f, 207.0f, -33.5f, -35.12f, 207.8f)); // a second place of B, 105 m away
        set.Add(MakeBox(8, -34.4f, -36.0f, 106.8f, -34.1f, -35.79f, 107.1f)); // A: 4.9 m away, never judged
        set.Add(MakeBox(9, -30.0f, -36.0f, 120.0f, -29.0f, -33.2f, 121.0f));  // 2.8 m tall: too tall
        set.Add(MakeBox(10, -30.0f, -36.0f, 130.0f, -29.5f, -35.5f, 130.5f)); // not a candidate (no verdict)
        F::StaticBook book;
        F::Entry cand;
        cand.why = F::Why::Ok;
        cand.until = 100000;
        cand.vs = 0x97f2d384ull;
        cand.verts = 2491;
        cand.height = 0.88f;
        cand.width = 1.0f;
        cand.above = 6.3f;
        book.Set(7, cand, 100);
        cand.verts = 1429;
        cand.height = 0.21f;
        cand.width = 0.3f;
        book.Set(8, cand, 100);
        cand.verts = 900;
        cand.height = 2.8f;
        cand.width = 1.0f;
        cand.above = 3.0f;
        book.Set(9, cand, 100);
        BbWindHang::Book heights;
        heights.Note(7, 4096, 0, true, 100, 0x97f2d384ull);
        BbWindHang::Entry* const hang_b = heights.Find(7);
        Expect(hang_b != nullptr, "r112m: the test's hang book has B");
        if (hang_b != nullptr) {
            const std::uint32_t b_base = BbWindSway::HeightKey(-36.0f);
            const std::uint32_t b_top = BbWindHang::TopKey(-35.12f);
            BbWindHang::Measure(*hang_b, true, 100, &b_base, &b_top, 1.0, 12.0f);
            BbWindHang::Measure(*hang_b, false, 100 + BbWindHang::JudgeFrames, &b_base, &b_top, 1.0, 12.0f);
        }
        OneJudge judge; // B: no judge entry; the judge knows stream 9 as moved with a growth of 60 mm
        judge.stream = 9;
        judge.e.state = JudgeEntry::JState::Moved;
        judge.e.dev = 0.06f;
        const std::vector<F::CandInfo> infos = F::GatherCands(set, book, heights, judge);
        Expect(infos.size() == 3 && infos[0].stream == 8 && infos[1].stream == 7 && infos[2].stream == 9,
               "r112m: the candidates of the scene nearest first, one per stream");
        if (infos.size() == 3) {
            Expect(infos[1].places == 2 && infos[0].places == 1 && std::fabs(infos[1].dist - 5.09f) < 0.1f &&
                       std::fabs(infos[0].dist - 4.9f) < 0.2f && infos[1].hang && infos[1].judged && infos[1].fits &&
                       std::fabs(infos[1].span - 0.88f) < 0.02f && !infos[0].hang && infos[0].judge == 0 &&
                       infos[2].judge == 3 && std::fabs(infos[2].dev - 0.06f) < 1e-5f,
                   "r112m: places, distances and states are gathered");
            Expect(F::ClassOf(infos[0], 2.5f) == F::CandClass::NoJudge && F::ClassOf(infos[1], 2.5f) == F::CandClass::Pushed &&
                       F::ClassOf(infos[2], 2.5f) == F::CandClass::Tall && F::ClassOf(infos[2], 3.0f) == F::CandClass::Other,
                   "r112m: the classes");
            F::Stats ms;
            ms.too_tall = 41;
            const std::vector<std::string> lines = F::CandLines(infos, ms, 2.5f, F::GainDefault, true, push_table, true, false);
            Expect(lines.size() == 4 && Has(lines[0], "(r112m)") && Has(lines[0], "candidates in the scene now 3 (1 pushed, 1 too tall, 1 with no GPU-judge entry, 0 other)") &&
                       Has(lines[0], "nearest 4.9 m (vs 97f2d384)") && Has(lines[0], "41 draws refused as too tall") &&
                       Has(lines[0], "proof tint off"),
                   "r112m: the header line");
            Expect(Has(lines[1], "A vs 97f2d384 (1 place, 1429 verts) dist 4.9 m: scene box 0.21 m tall") &&
                       Has(lines[1], "keys span not read") && Has(lines[1], "no GPU-judge entry") &&
                       Has(lines[2], "B vs 97f2d384 (2 places, 2491 verts)") && Has(lines[2], "keys span 0.88 m") &&
                       Has(lines[2], "PUSHED: scale 0.73") && Has(lines[2], "its bottom moves 0.057 m now") &&
                       Has(lines[3], "C vs 97f2d384") && Has(lines[3], "TOO TALL: its scene box is 2.80 m, over 2.5 m"),
                   "r112m: a line per candidate: the unjudged part, the pushed cage, the too tall one");
            Expect(F::CandLines(infos, ms, 2.5f, F::GainDefault, true, push_table, false, true).size() == 1 &&
                       Has(F::CandLines(infos, ms, 2.5f, F::GainDefault, true, push_table, false, true)[0], "proof tint ON"),
                   "r112m: no candidate lines without the survey knob");
            Expect(Has(F::CandState(infos[1], 2.5f, F::GainDefault, false, push_table), "its bottom moves 0.042 m now") &&
                       Has(F::CandState(infos[1], 2.5f, F::GainDefault, false, push_table), "scaled by its height"),
                   "r112m: SAME=0 prints r112l's push");
            for (const std::string& line : lines) {
                Expect(line.size() <= F::LineCharsK, "r112m: a line is capped");
            }
        }
        // the other states
        F::CandInfo state;
        state.e.height = 0.5f;
        state.hang = true;
        Expect(Has(F::CandState(state, 2.5f, 0.2f, true, 0.1f), "measuring"), "r112m: state: measuring");
        state.judged = true;
        state.span = 0.1f;
        Expect(Has(F::CandState(state, 2.5f, 0.2f, true, 0.1f), "unfit: its keys span 0.10 m, under 0.15 m"), "r112m: state: short");
        state.span = 20.0f;
        Expect(Has(F::CandState(state, 2.5f, 0.2f, true, 0.1f), "unfit: its keys span 20.00 m, over its limit"), "r112m: state: long");
        state.moving = true;
        Expect(Has(F::CandState(state, 2.5f, 0.2f, true, 0.1f), "held as moving by r112's book"), "r112m: state: moving");
        F::CandInfo refused;
        refused.judge = 3;
        refused.dev = -2.0f;
        Expect(Has(F::CandState(refused, 2.5f, 0.2f, true, 0.1f), "refused by r112h's rules"), "r112m: state: refused by r112h");
        F::CandInfo window;
        window.judge = 1;
        Expect(Has(F::CandState(window, 2.5f, 0.2f, true, 0.1f), "window is open"), "r112m: state: judging");
        F::CandInfo still_no_book;
        still_no_book.judge = 2;
        Expect(Has(F::CandState(still_no_book, 2.5f, 0.2f, true, 0.1f), "has no entry for it"), "r112m: state: still, no book entry");
        const std::string once_m = F::OnceTextM(true, true, F::TallDefault);
        Expect(Has(once_m, "(r112m)") && Has(once_m, "newest 6 candidates") && Has(once_m, "BB_WIND_HANG_STATIC_SAME=1") &&
                   Has(once_m, "BB_WIND_HANG_PROOF=1") && Has(F::OnceTextM(false, false, 1.0f), "SAME=0") &&
                   once_m.size() < 1536,
               "r112m: the once line");
    }

"""

# ---- vk_rasterizer_effects.cpp ---------------------------------------------------------------------
E1 = r"""static bool WindHangLiveOn() {
    return true;
}
#endif
"""
E1S = r"""
// bbport (r112m_hang-close-proof, TOOL): BB_WIND_HANG_STATIC_GAIN now: with the test tools' live knobs (r84) the value in
// the live knobs file (set:/unset:), else the environment's, read when the knob is first asked. Read in WindHangWord only.
#if BB_WIND_TWIGS_LIVE
static float HangGainParseLive(const char* text) {
    return BbWindHangFind::ParseGain(text);
}

static float WindHangGainNow() {
    static BbLiveKnobs::Knob<float> knob{"BB_WIND_HANG_STATIC_GAIN", HangGainParseLive};
    return knob.Get();
}
#else
static float WindHangGainNow() {
    return BbWindHangFind::GainKnob();
}
#endif
"""

E2 = r"""    const float max_extent = placed_ok ? BbWindHangFind::SpanLimit(*placed) : BbWindHang::MaxExtent;
"""
E2S = r"""    // bbport (r112m_hang-close-proof): the keys of a static candidate's slot span the UNION of the places its mesh is drawn
    // at (no length): its real hanging length is its scene box. Taller than BB_WIND_HANG_STATIC_TALL: refused, counted,
    // and its candidate line says TOO TALL
    if (placed_ok && BbWindHangFind::TooTall(*placed, BbWindHangFind::TallKnob())) {
        ++hang_find_stats.too_tall;
        return 0;
    }
"""

E3 = r"""    return BbWindHang::HangWord(frame_slot, view, slot,
                                placed_ok ? BbWindHangFind::GainRamp(hang_ramp, BbWindHangFind::GainKnob()) : hang_ramp);
"""
E3N = r"""    // bbport (r112m_hang-close-proof): the gain is live (set:/unset:), and with BB_WIND_HANG_STATIC_SAME (default) the ramp of
    // a short candidate is made so that its bottom moves as far as a tall one's (the shaders scale the push of a mesh
    // under 1.2 m by its height over 1.2 m: a 0.21 m lantern part moved a quarter of the cage that holds it)
    const float hang_scale = BbWindHang::HangScale(entry->base, entry->top);
    return BbWindHang::HangWord(frame_slot, view, slot,
                                placed_ok ? BbWindHangFind::SameRamp(hang_ramp, WindHangGainNow(), hang_scale,
                                                                     BbWindHangFind::SameKnob())
                                          : hang_ramp);
"""

E4 = r"""            BbReport::Printf("%s\n", BbWindHangFind::TallText(hang_static_book, hang_book, BbWindHangFind::UnionKnob(),
                                                              BbWindHangFind::TallKnob())
                                         .c_str());
"""
E4S = r"""            // bbport (r112m_hang-close-proof): every candidate of the scene now, nearest first, with its state (a header
            // line always; the candidate lines with BB_WIND_HANG_FIND=1)
            for (const std::string& line : BbWindHangFind::CandLines(
                     BbWindHangFind::GatherCands(hang_find_boxes, hang_static_book, hang_book, hang_box),
                     hang_find_stats, BbWindHangFind::TallKnob(), WindHangGainNow(), BbWindHangFind::SameKnob(),
                     hang_source.now, BbWindHangFind::FindOn(), BbWindHang::ProofOn())) {
                BbReport::Printf("%s\n", line.c_str());
            }
"""

E5 = r"""                                     .c_str()); // bbport (r112l_hang-discard-lanterns)
"""
E5S = r"""        BbReport::Printf("%s\n", BbWindHangFind::OnceTextM(BbWindHangFind::SameKnob(), BbWindHang::ProofOn(),
                                                           BbWindHangFind::TallKnob())
                                     .c_str()); // bbport (r112m_hang-close-proof)
"""

# ---- lifter/lift_stage.cpp -------------------------------------------------------------------------
L1 = r"""        Open(top_merge);
    }
"""
L1N = r"""    if (hang_on && BbWindHang::ProofOn()) { // bbport (r112m_hang-close-proof, TOOL): the proof tint of a pushed hang draw
        // every output attribute of a vertex with a hang word whose ramp is above 0 (a pushed one: the words that only
        // fill the keys have a ramp of 0) moves BbWindHang::ProofShare toward cyan (0, 1, 1); the twigs' proof tints yellow
        const u32 pushed = Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool, {hang, FCmp(O(spv::Op::OpFOrdGreaterThan), ramp, zero)});
        const u32 share = Select(pushed, CF(BbWindHang::ProofShare), zero);
        for (u32 p = 0; p < u32(var_param_out.size()); ++p) {
            if (!var_param_out[p]) {
                continue;
            }
            const u32 attribute = Emit(O(spv::Op::OpLoad), t_v4f, Ty::V4F, {var_param_out[p]});
            const auto toward = [&](u32 index, float target) {
                const u32 c = Extract(t_f32, Ty::F32, attribute, index);
                return FAdd(c, FMul(FSub(CF(target), c), share));
            };
            EmitVoid(O(spv::Op::OpStore), {var_param_out[p], ComponentsF({toward(0, 0.0f), toward(1, 1.0f), toward(2, 1.0f), Extract(t_f32, Ty::F32, attribute, 3)})});
        }
    }
"""

# ---- README.md -------------------------------------------------------------------------------------
R1 = r"""| `BB_WIND_HANG_FIND` |"""
R1P = r"""| `BB_WIND_HANG_STATIC_SAME` | Part of `BB_WIND_HANG_STATIC` (r112m; default on, exactly `0` gives r112l's ramp). The shaders scale the push of a hanging mesh shorter than 1.2 m by its height over 1.2 m, so a 0.21 m lantern part moved a quarter of the 0.88 m cage that holds it. With this knob the ramp of a static candidate is made so that its bottom moves by `BB_WIND_HANG_STATIC_GAIN` x the push whatever its size (a very short part is held to its scale). Also: a static candidate whose own scene box is taller than `BB_WIND_HANG_STATIC_TALL` is refused (its keys span the union of the places the mesh is drawn at, no length); `BB_WIND_HANG_STATIC_GAIN` can be changed live in the test tools' knobs file. Log: "Wind sway hang (r112m)" once and every 600 frames (a line per candidate with `BB_WIND_HANG_FIND=1`). |
| `BB_WIND_HANG_PROOF` | A TEST aid for `BB_WIND_HANG` (r112m; `1` turns it on, needs the lifter's shaders and a cold shader cache). Every output attribute of a pushed hanging draw is tinted 40 % toward cyan, so that a picture shows which meshes are pushed (nothing is tinted with `BB_WIND_HANG_PUSH=0` live). Off by default; costs nothing off. |
"""

EDITS = {
NH: [
('ins', H1, H1P, ""),
],
NF: [
('ins', F1, "", F1N),
('ins', F2, F2P, ""),
],
NT: [
('ins', T1, T1P, ""),
],
RE: [
('ins', E1, "", E1S),
('ins', E2, "", E2S),
('rep', E3, "", E3N),
('ins', E4, "", E4S),
('ins', E5, "", E5S),
],
LS: [
('ins', L1, "", L1N),
],
RM: [
('ins', R1, R1P, ""),
],
}

ORDER = (NH, NF, NT, RE, LS, RM)


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
    nf, nh, nt, re_, ls = texts[NF], texts[NH], texts[NT], texts[RE], texts[LS]
    for path in ORDER:
        if path == RM:
            continue
        if balance(texts[path]) != balance(olds[path]):
            raise SystemExit("text check: %s: braces, parens or brackets changed by %r" %
                             (path, tuple(a - b for a, b in zip(balance(texts[path]), balance(olds[path])))))
    for needle in ("inline bool ParseSame(", "inline bool SameKnob()", "inline float ClampGain(", "inline float ClampScale(",
                   "inline std::uint32_t SameRamp(", "inline float BottomPush(", "inline bool TooTall(", "struct CandInfo {",
                   "inline std::vector<CandInfo> GatherCands(", "enum class CandClass", "inline CandClass ClassOf(",
                   "inline std::string CandState(", "inline std::vector<std::string> CandLines(",
                   "inline std::string OnceTextM(", "std::uint64_t too_tall = 0;"):
        if needle not in nf:
            raise SystemExit("text check: %s missing in the find header" % needle)
    for needle in ("inline bool ProofOn()", "inline bool ParseProof(", "inline constexpr float ProofShare"):
        if needle not in nh:
            raise SystemExit("text check: %s missing in the hang header" % needle)

    def before(text, a, b, what):
        if text.index(a) > text.index(b):
            raise SystemExit("text check: %s" % what)
    before(nf, "inline bool TooTall(", "inline CandClass ClassOf(", "TooTall must precede ClassOf")
    before(nf, "struct CandInfo {", "inline std::vector<CandInfo> GatherCands(", "CandInfo must precede GatherCands")
    before(nf, "inline float ClampGain(", "inline std::uint32_t SameRamp(", "ClampGain must precede SameRamp")
    before(nf, "inline float ClampScale(", "inline std::uint32_t SameRamp(", "ClampScale must precede SameRamp")
    before(nf, "inline std::string CandState(", "inline std::vector<std::string> CandLines(", "CandState must precede CandLines")
    before(nf, "inline float SpanLimitWith(", "inline std::string CandState(", "SpanLimitWith (r112l) must precede CandState")
    before(nf, "inline float UnionKnob()", "inline std::string CandState(", "UnionKnob must precede CandState")
    before(nf, "inline std::string Cap(", "inline std::vector<std::string> CandLines(", "Cap must precede CandLines")
    before(nf, "struct Stats {", "inline std::vector<std::string> CandLines(", "Stats must precede CandLines")
    before(nf, "class StaticBook", "inline std::vector<CandInfo> GatherCands(", "StaticBook must precede GatherCands")
    before(nf, "class BoxSet", "inline std::vector<CandInfo> GatherCands(", "BoxSet must precede GatherCands")
    before(nh, "inline const Knob& KnobOnce()", "inline bool ProofOn()", "KnobOnce must precede ProofOn")
    if "#include <cstdlib>" not in nh:
        raise SystemExit("text check: getenv needs <cstdlib> in the hang header")
    for needle in ("static float WindHangGainNow()", "BbWindHangFind::TooTall(*placed, BbWindHangFind::TallKnob())",
                   "++hang_find_stats.too_tall;", "BbWindHang::HangScale(entry->base, entry->top)",
                   "BbWindHangFind::SameRamp(hang_ramp, WindHangGainNow(), hang_scale,", "BbWindHangFind::CandLines(",
                   "BbWindHangFind::GatherCands(hang_find_boxes, hang_static_book, hang_book, hang_box)",
                   "BbWindHangFind::OnceTextM("):
        if needle not in re_:
            raise SystemExit("text check: %s missing in the effects file" % needle)
    if re_.index("static float WindHangGainNow()") > re_.index("BbWindHangFind::SameRamp(hang_ramp"):
        raise SystemExit("text check: WindHangGainNow is used before its definition")
    if re_.count("static float WindHangGainNow()") != 2:
        raise SystemExit("text check: WindHangGainNow must be defined in both branches of the live knobs switch")
    if re_.index("const bool placed_ok") > re_.index("BbWindHangFind::TooTall(*placed"):
        raise SystemExit("text check: placed_ok is used before its definition")
    if re_.index("BbWindHangFind::CandLines(") > re_.index("hang_find_stats = {};"):
        raise SystemExit("text check: the r112m lines must print before the stats reset")
    if re_.index("const BbWindHangFind::PushSource hang_source") > re_.index("BbWindHangFind::CandLines("):
        raise SystemExit("text check: hang_source is used before its definition")
    if ls.count("BbWindHang::ProofOn()") != 1 or ls.count("hang_on && BbWindHang::ProofOn()") != 1:
        raise SystemExit("text check: the lifter's proof block")
    if ls.index("Open(top_merge);") > ls.index("BbWindHang::ProofShare"):
        raise SystemExit("text check: the proof block must follow the hang top offer")
    if "r112m: the candidates of the scene nearest first, one per stream" not in nt or \
            "r112m: SameRamp and BottomPush agree" not in nt:
        raise SystemExit("text check: the tests are missing")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112M_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == NF and "OnceTextL(" not in cur:
            raise SystemExit("REFUSED: r112l_hang-discard-lanterns must be applied (OnceTextL)")
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
            tmp = full + ".r112mtmp"
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
        tmp = full + ".r112mtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


if __name__ == "__main__":
    main()
