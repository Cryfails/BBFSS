# r111j_prints-lit-graveyard: FEATURE fix on top of r111 to r111i (b52: the church's wet prints work, two hard-edged dark
# soles on the lit slab, lit luminance x0.58; the graveyard's gb1 and gbw log prints (gb1 4 prints, 521259 px stamped,
# x0.65) but the pictures show none: the cobbles are near black (lit luminance 0.004 to 0.013) and the prints were in
# shadow or out of the frame). Still off unless BB_FOOTPRINTS is set and still costs nothing when off (every edit is
# inside Footprints, which is not made without the knob, or inside the post stamp's shader, which only that object
# dispatches). Branch: visual/footprints.
#
# WHAT CHANGES (code is small; the main work is the jobs, slot_jobs_r111j_prints-lit-graveyard.json)
#  (1) JOBS: the graveyard jobs go back to the framing that showed the soles at b49 (r111h gbc: turn 0.3 s, three walks
#      of 1.5 s out of the blood pool onto the moonlit cobbles, turn 0.9 s, tilt 0.2 s), then ONE game with live knobs
#      per same-camera set (no pad between): back_post, back_sheen (BB_FOOTPRINTS_SHEEN=1), back_sheen3 (=3, the cap),
#      back_off (GAIN 0), then a lower framing with down_sheen, down_post, down_off. gb1 = coat from the ground, gbc =
#      forced blood coat (the b49 test, so every print is blood), cp1 = church (wet prints; the sheen must change
#      nothing there), dh1 = dream house (do-nothing).
#  (2) LOG, one line per view (footprints_flat.comp's counters are read back each pass; vk_footprints.cpp ViewRead):
#      "Footprints (r111j): view at frame F, camera x y z: N prints sent, I in the picture, B behind the camera, P px
#      stamped, lit luminance X before Y after, gain G sheen S, verdict V". Verdict 0: no print in the picture (all
#      off screen: a picture of it shows nothing whatever the stamp does), 1: in the picture but no pixel stamped
#      (hidden by something nearer, off the ground, gain 0), 2: stamped where the mean lit luminance is under 0.02
#      (near black: a darkening or a dark red cannot read; the honest reason for an invisible print), 3: stamped on
#      lit ground. The line is told when the verdict, the count, the gain or the sheen changes, and every 120 passes,
#      at most 80 lines; one zero copy at construction (the slot runner keeps the first and last line of each kind).
#      "In the picture" counts the print's CENTRE inside the picture over ALL prints sent (not only the first 8
#      probes). The counters come from the same pass, so they describe the picture that pass drew.
#  (3) BB_FOOTPRINTS_SHEEN (live like the gain; 0 to 4, default 0 = off; other text 0): blood prints on near-black
#      ground are useless: a dark red of 0.25 x a luminance of 0.005 is 0.001, the same black as the cobbles. A wet
#      film reflects a little of the sky, so with the knob a blood print's pixel is lifted (hue kept, the blood tint)
#      to at least SHEEN_SKY (0.012) x the knob in luminance, passed through r100k's roll-off (PeakRoll: untouched
#      under the knee 0.5 x peak, exponential toward the ceiling SHEEN_PEAK 0.03 above it, so even 4 gives 0.0283 and
#      no hot spot). The lift is max(floor - lit luminance, 0) x blood cover x blood weight: lit ground above the floor
#      (the church slab 0.077) is not touched at all, and wet or mud prints never get it. The knob travels in the
#      push block's unused `hunter.x` (the push block stays 112 bytes). One new counter word (42, FLAT_WORDS 43): the
#      blood pixels the sheen lifted, in a periodic line "Footprints (r111j): sheen S: N blood pixels lifted in R
#      read-backs; view lines told L of M" (zero copy at construction, frame 240, every 600 frames).
#      NOT done (said honestly): wet prints on near-black stone stay invisible (a multiply cannot darken black); a wet
#      sheen would be a different, brighter look and is not drafted.
#
# How the code guarantees nothing runs when the feature is off: BB_FOOTPRINTS unset -> Footprints is not made, its hook
# is one null pointer test, and nothing here is reached (the view lines and the sheen counter are read only in
# FlatProbeRead/DrawOver of that object; the shader edits run only inside the post stamp's dispatch). With the feature on
# and BB_FOOTPRINTS_SHEEN unset: hunter.x = 0, the shader's new branch is one uniform test that is false, nothing is
# written to the new counter word, and the picture is as r111i's, bit for bit. Cost with the sheen on: per stamped blood
# pixel a few multiplies and one exp, and one atomic when it lifted; one CPU projection per print sent per pass (at most
# 13). Memory: the counter buffer grows from 168 to 172 bytes (and its host copy).
#
# Files edited (the text r111i left; each old text found exactly once): footprints_layout.h, footprints_flat.comp,
# footprints.h, vk_footprints.h, vk_footprints.cpp, engine/tests/test_footprints.cpp, README.md.
# r111i's own `check` refuses after this patch (its counter-word text); revert r111j before r111i.
#
# Order: needs r111i applied (refused otherwise).
# Use: python -I -X utf8 r111j_prints-lit-graveyard.py check | apply | revert
# Root: R111J_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r111j_backup next to this script; revert puts each old text back (each new text found by itself, exactly once).
import math, os, re, sys

ROOT = os.environ.get("R111J_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r111j_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RULES = RV + "footprints.h"
VKH = RV + "vk_footprints.h"
VKC = RV + "vk_footprints.cpp"
LAYOUT = HS + "footprints_layout.h"
FLAT = HS + "footprints_flat.comp"
TEST = "engine/tests/test_footprints.cpp"
README = "README.md"
ORDER = [LAYOUT, FLAT, RULES, VKH, VKC, TEST, README]

# (old, new): `old` found exactly once and `new` not at all (clean), or `new` exactly once (applied).
EDITS = {
    LAYOUT: [
        (r'''#define FOOTPRINTS_FLAT_WORDS 42u
''',
         r'''// (r111j) One more counter word after the luminance words: the blood pixels the faint wet sheen lifted.
#define FOOTPRINTS_FLAT_WORD_SHEEN 42u
#define FOOTPRINTS_FLAT_WORDS 43u
'''),
        (r'''#define FOOTPRINTS_POST_SILHOUETTE_REL 0.03
''',
         r'''#define FOOTPRINTS_POST_SILHOUETTE_REL 0.03
// (r111j) BB_FOOTPRINTS_SHEEN (blood prints only, default 0 = off): a wet film on dark ground reflects a little of the
// sky, so a dark red print on near-black stone is lifted to at least SHEEN_SKY x the knob in luminance (the blood
// tint's luminance is 1, so the lift adds exactly that), passed through r100k's roll-off: untouched under SHEEN_KNEE
// x SHEEN_PEAK, an exponential toward SHEEN_PEAK above it, never above it. Lit ground above the floor is not touched.
#define FOOTPRINTS_SHEEN_SKY 0.012
#define FOOTPRINTS_SHEEN_PEAK 0.03
#define FOOTPRINTS_SHEEN_KNEE 0.5
// (r111j) A view line's verdict 2 or 3: the mean lit luminance under the stamp is under this (near black), or not.
#define FOOTPRINTS_VIEW_READABLE_LUM 0.02
'''),
    ],
    FLAT: [
        (r'''; `hunter` and `stamp` are not used.
''',
         r'''; `stamp` is not used; (r111j) `hunter.x` is
// BB_FOOTPRINTS_SHEEN (the blood prints' wet sheen, 0: off), the rest of `hunter` is not used.
'''),
        (r'''// 0..1: the sole's shape at (u along the step, v across it), as footprints.comp.
''',
         r'''// (r111j) BloodSheenRules::PeakRoll's arithmetic (r100k): luminance up to the knee as it is, above it an exponential
// roll-off toward `peak` (continuous, slope 1 at the knee, never above peak).
float PeakRoll(float luma, float peak) {
    const float knee = FOOTPRINTS_SHEEN_KNEE * peak;
    const float span = peak - knee;
    return luma <= knee ? luma : knee + span * (1.0 - exp(-(luma - knee) / span));
}

// 0..1: the sole's shape at (u along the step, v across it), as footprints.comp.
'''),
        (r'''    rgb = mix(rgb, dark_red, FOOTPRINTS_POST_BLOOD_COVER * blood);
''',
         r'''    rgb = mix(rgb, dark_red, FOOTPRINTS_POST_BLOOD_COVER * blood);
    bool lifted = false;
    if (hunter.x > 0.0 && blood > max(wet, mud)) { // (r111j) the wet film's faint sky reflection on a blood print
        const float sheen_floor = PeakRoll(FOOTPRINTS_SHEEN_SKY * hunter.x, FOOTPRINTS_SHEEN_PEAK);
        const float lift = max(sheen_floor - dot(rgb, vec3(0.2126, 0.7152, 0.0722)), 0.0) *
                           FOOTPRINTS_POST_BLOOD_COVER * blood;
        rgb += vec3(FOOTPRINTS_POST_BLOOD_TINT_R, FOOTPRINTS_POST_BLOOD_TINT_G, FOOTPRINTS_POST_BLOOD_TINT_B) * lift;
        lifted = lift > 0.0;
    }
'''),
        (r'''    atomicAdd(counts[FOOTPRINTS_FLAT_WORD_POST_PX], 1u);
''',
         r'''    atomicAdd(counts[FOOTPRINTS_FLAT_WORD_POST_PX], 1u);
    if (lifted) { // (r111j)
        atomicAdd(counts[FOOTPRINTS_FLAT_WORD_SHEEN], 1u);
    }
'''),
    ],
    RULES: [
        (r'''//                       luminance, wet and mud darkened a further 40%, r111g); 0: the G-buffer change alone (Post()).
''',
         r'''//                       luminance, wet and mud darkened a further 40%, r111g); 0: the G-buffer change alone (Post()).
//   BB_FOOTPRINTS_SHEEN (r111j) a number from 0 to 4, default 0 (off): a faint wet sheen on BLOOD prints so they read on
//                       near-black ground: their luminance is lifted to at least 0.012 x the number (ceiling 0.03,
//                       r100k's roll-off); lit ground above that is not touched; wet and mud prints never (Sheen()).
'''),
        (r'''inline constexpr std::uint32_t FlatLumWords = FOOTPRINTS_FLAT_LUM_WORDS;
''',
         r'''inline constexpr std::uint32_t FlatLumWords = FOOTPRINTS_FLAT_LUM_WORDS;
inline constexpr std::uint32_t WordFlatSheen = FOOTPRINTS_FLAT_WORD_SHEEN; // (r111j) the blood pixels the sheen lifted
'''),
        (r'''              FlatLumWords == 6u && FlatWords == WordFlatLum + FlatLumWords);
''',
         r'''              FlatLumWords == 6u && WordFlatSheen == WordFlatLum + FlatLumWords && FlatWords == WordFlatSheen + 1u);
'''),
        (r'''    static const float strength = PostOfText(std::getenv("BB_FOOTPRINTS_POST"));
    return strength;
#endif
}
''',
         r'''    static const float strength = PostOfText(std::getenv("BB_FOOTPRINTS_POST"));
    return strength;
#endif
}

/// (r111j) BB_FOOTPRINTS_SHEEN: the accepted range, 0 (off) to SheenMax.
inline constexpr double SheenMax = 4.0;

/// (r111j) BB_FOOTPRINTS_SHEEN's text: a number from 0 to SheenMax; unset, empty, other text or a number out of range:
/// 0 (off, the default).
inline float SheenOfText(const char* text) {
    const char* t = Detail::Trim(text);
    if (t == nullptr || *t == '\0') {
        return 0.0f;
    }
    char* end = nullptr;
    const double g = std::strtod(t, &end);
    if (end != t && *Detail::Trim(end) == '\0' && g >= 0.0 && g <= SheenMax) {
        return float(g);
    }
    return 0.0f;
}

/// (r111j) The blood sheen's knob now (live like the gain).
inline float Sheen() {
#if BB_FOOTPRINTS_LIVE
    static BbLiveKnobs::Knob<float> knob{"BB_FOOTPRINTS_SHEEN", SheenOfText};
    return knob.Get();
#else
    static const float strength = SheenOfText(std::getenv("BB_FOOTPRINTS_SHEEN"));
    return strength;
#endif
}

/// (r111j) The shader's PeakRoll (r100k): luminance up to the knee (FOOTPRINTS_SHEEN_KNEE x peak) as it is, above it
/// knee + span x (1 - exp(-(luma - knee) / span)), span = peak - knee: continuous, increasing, never above peak.
inline float PeakRoll(float luma, float peak) {
    const float knee = float(FOOTPRINTS_SHEEN_KNEE) * peak;
    const float span = peak - knee;
    return luma <= knee ? luma : knee + span * (1.0f - std::exp(-(luma - knee) / span));
}

/// (r111j) The luminance floor a blood print's pixel is lifted to with the sheen knob `knob` (0: none).
inline float SheenFloor(float knob) {
    return knob > 0.0f ? PeakRoll(float(FOOTPRINTS_SHEEN_SKY) * knob, float(FOOTPRINTS_SHEEN_PEAK)) : 0.0f;
}

/// (r111j) A view line's verdict: 0 no print in the picture, 1 prints in the picture but no pixel stamped, 2 stamped
/// where the mean lit luminance before the stamp is under FOOTPRINTS_VIEW_READABLE_LUM (near black), 3 stamped on lit
/// ground.
inline std::uint32_t ViewVerdict(std::uint32_t in_frame, std::uint32_t px, double mean_before) {
    if (in_frame == 0u) {
        return 0u;
    }
    if (px == 0u) {
        return 1u;
    }
    return mean_before < double(FOOTPRINTS_VIEW_READABLE_LUM) ? 2u : 3u;
}
'''),
    ],
    VKH: [
        (r'''        std::array<u64, 2> lum_px{}, lum_before{}, lum_after{};
''',
         r'''        std::array<u64, 2> lum_px{}, lum_before{}, lum_after{};
        u64 sheen_px = 0; ///< (r111j) over the read-backs, the blood pixels the sheen lifted
'''),
        (r'''        u32 stamp = 0, show = 0, count = 0, groups = 0, mode_pass = 0, episode = 0;
''',
         r'''        u32 stamp = 0, show = 0, count = 0, groups = 0, mode_pass = 0, episode = 0;
        u32 in_frame = 0, behind = 0;     ///< (r111j) of the prints sent: centre inside the picture, behind the camera
        float gain = 0.0f, sheen = 0.0f;  ///< (r111j) the pass's strength and BB_FOOTPRINTS_SHEEN
'''),
        (r'''    void LogLuma() const;   // (r111i)
''',
         r'''    void LogLuma() const;   // (r111i)
    // (r111j) one line per view, and the sheen's counter
    void ViewRead(const FlatSnap& snap, const std::array<u32, FootprintRules::FlatWords>& counts);
    void LogView(u64 at_frame, const FlatSnap& snap, u32 px, double lum_before, double lum_after, u32 verdict) const;
    void LogSheen() const;
    struct ViewTold { ///< what the last view line said (a line is told when it changes, and every ViewEvery passes)
        u32 lines = 0, since = 0, verdict = 99, in_frame = ~0u;
        float gain = -1.0f, sheen = -1.0f;
    } view_told;
'''),
        (r'''    static constexpr u32 LineFrames = 600;
''',
         r'''    static constexpr u32 LineFrames = 600;
    static constexpr u32 ViewMax = 80, ViewEvery = 120; ///< (r111j) most view lines, and the passes between two
'''),
    ],
    VKC: [
        (r'''        LogLuma();                                 // (r111i) a zero copy
''',
         r'''        LogLuma();                                 // (r111i) a zero copy
        LogView(0, FlatSnap{}, 0u, 0.0, 0.0, 0u);  // (r111j) a zero copy
        LogSheen();                                // (r111j) a zero copy
'''),
        (r'''    if (!camera_motion.Enabled()) {
        Fail("it needs the upscaler's camera (BB_UPSCALER=none)");
''',
         r'''    BbReport::Printf("Footprints (r111j): a view line when the verdict, the prints in the picture, the gain or the sheen "
                     "changes, or every %u passes, at most %u; verdict 0 no print in the picture, 1 in it but no pixel "
                     "stamped, 2 stamped where the lit luminance is under %.3f (near black), 3 on lit ground\n",
                     ViewEvery, ViewMax, double(FOOTPRINTS_VIEW_READABLE_LUM));
    BbReport::Printf("Footprints (r111j): sheen %.2f (BB_FOOTPRINTS_SHEEN, 0 to %.0f, default 0, blood prints only): a "
                     "blood print's luminance is lifted to at least %.4f times it (ceiling %.3f, knee %.2f of it)\n",
                     double(R::Sheen()), double(R::SheenMax), double(FOOTPRINTS_SHEEN_SKY),
                     double(FOOTPRINTS_SHEEN_PEAK), double(FOOTPRINTS_SHEEN_KNEE));
    if (!camera_motion.Enabled()) {
        Fail("it needs the upscaler's camera (BB_UPSCALER=none)");
'''),
        (r'''void Footprints::FlatProbeRead(const std::array<u32, R::FlatWords>& counts) {
''',
         r'''/// (r111j) One line about a view: the prints in the picture, the pixels the stamp wrote there and their lit luminance
/// before and after, the gain and the sheen, and the verdict (see the once-line): so a picture without prints is told
/// from a stamp that wrote nothing and from prints on near-black ground. Told by ViewRead.
void Footprints::LogView(u64 at_frame, const FlatSnap& snap, u32 px, double lum_before, double lum_after,
                         u32 verdict) const {
    BbReport::Printf("Footprints (r111j): view at frame %llu, camera %.1f %.1f %.1f: %u prints sent, %u in the picture, "
                     "%u behind the camera, %u px stamped, lit luminance %.4f before %.4f after, gain %.2f sheen %.2f, "
                     "verdict %u\n",
                     static_cast<unsigned long long>(at_frame), double(snap.camera[0]), double(snap.camera[1]),
                     double(snap.camera[2]), snap.count, snap.in_frame, snap.behind, px, lum_before, lum_after,
                     double(snap.gain), double(snap.sheen), verdict);
}

/// (r111j) The sheen's counter: blood pixels it lifted, over the read-backs.
void Footprints::LogSheen() const {
    BbReport::Printf("Footprints (r111j): sheen %.2f: %llu blood pixels lifted in %u read-backs; view lines told %u of %u\n",
                     double(R::Sheen()), static_cast<unsigned long long>(stats.sheen_px), flat.read_back,
                     view_told.lines, ViewMax);
}

/// (r111j) A stamp pass's read-back as a view: told when it differs from the last line told, and every ViewEvery passes.
void Footprints::ViewRead(const FlatSnap& snap, const std::array<u32, R::FlatWords>& counts) {
    u64 px = 0, before = 0, after = 0; // wet or mud, and blood, together
    for (u32 k = 0; k < 2; ++k) {
        const u32* lw = counts.data() + R::WordFlatLum + k * 3u;
        px += lw[0];
        before += lw[1];
        after += lw[2];
    }
    const double scale = px != 0u ? double(px) * FOOTPRINTS_FLAT_LUM_SCALE : 1.0;
    const double lum_before = double(before) / scale, lum_after = double(after) / scale;
    const u32 px32 = u32(std::min<u64>(px, 0xFFFFFFFFull));
    const u32 verdict = R::ViewVerdict(snap.in_frame, px32, lum_before);
    ViewTold& t = view_told;
    ++t.since;
    const bool changed = verdict != t.verdict || snap.in_frame != t.in_frame || snap.gain != t.gain ||
                         snap.sheen != t.sheen;
    if (t.lines >= ViewMax || !(changed || t.since >= ViewEvery)) {
        return;
    }
    ++t.lines;
    t.since = 0;
    t.verdict = verdict;
    t.in_frame = snap.in_frame;
    t.gain = snap.gain;
    t.sheen = snap.sheen;
    LogView(frame, snap, px32, lum_before, lum_after, verdict);
}

void Footprints::FlatProbeRead(const std::array<u32, R::FlatWords>& counts) {
'''),
        (r'''            stats.lum_after[k] += lw[2];
        }
''',
         r'''            stats.lum_after[k] += lw[2];
        }
        stats.sheen_px += counts[R::WordFlatSheen]; // (r111j)
        if (!snap.show) {
            ViewRead(snap, counts); // (r111j) one line per view
        }
'''),
        (r'''    push.gain = strength;
    const u32 gx0 = u32(rect.x0) / R::Group, gy0 = u32(rect.y0) / R::Group;
''',
         r'''    push.gain = strength;
    push.hunter = {R::Sheen(), 0.0f, 0.0f, 0.0f}; // (r111j) the flat shader reads BB_FOOTPRINTS_SHEEN here
    const u32 gx0 = u32(rect.x0) / R::Group, gy0 = u32(rect.y0) / R::Group;
'''),
        (r'''        snap.camera = {cam_x, cam_y, cam_z};
''',
         r'''        snap.camera = {cam_x, cam_y, cam_z};
        for (u32 i = 0; i < count; ++i) { // (r111j) where every print sent lands (the view line's count)
            const float* q = packed.data() + std::size_t(i) * R::PrintFloats;
            const R::ScreenPoint where = R::ProjectPoint(camera.view, camera.proj, fw, fh, jitter, q[0], q[1], q[2]);
            snap.in_frame += where.state == 1 ? 1u : 0u;
            snap.behind += where.state == 2 ? 1u : 0u;
        }
        snap.gain = push.gain;
        snap.sheen = push.hunter[0];
'''),
        (r'''        LogTotals(); // (r111h)
        LogLuma();   // (r111i)
''',
         r'''        LogTotals(); // (r111h)
        LogLuma();   // (r111i)
        LogSheen();  // (r111j)
'''),
    ],
    TEST: [
        (r'''        assert(PostOfText("1 x") == 1.0f);
''',
         r'''        assert(PostOfText("1 x") == 1.0f);
        // (r111j) BB_FOOTPRINTS_SHEEN: off unless a number from 0 to 4; the roll-off keeps the floor under the ceiling
        assert(SheenOfText(nullptr) == 0.0f && SheenOfText("") == 0.0f && SheenOfText("0") == 0.0f);
        assert(SheenOfText("1") == 1.0f && Near(SheenOfText(" 0.5 "), 0.5) && Near(SheenOfText("4"), 4.0));
        assert(SheenOfText("5") == 0.0f && SheenOfText("-1") == 0.0f && SheenOfText("x") == 0.0f);
        assert(SheenOfText("1 x") == 0.0f);
        assert(SheenFloor(0.0f) == 0.0f && Near(SheenFloor(1.0f), FOOTPRINTS_SHEEN_SKY));
        {
            const double peak = FOOTPRINTS_SHEEN_PEAK, knee = FOOTPRINTS_SHEEN_KNEE * FOOTPRINTS_SHEEN_PEAK;
            assert(Near(PeakRoll(float(knee) * 0.5f, float(peak)), knee * 0.5)); // under the knee: as it is
            assert(Near(PeakRoll(float(knee), float(peak)), knee));              // continuous at the knee
            float last = 0.0f;
            for (int i = 0; i <= 40; ++i) { // increasing, never above the ceiling
                const float v = PeakRoll(float(i) * 0.005f, float(peak));
                assert(v >= last && v <= float(peak));
                last = v;
            }
            assert(SheenFloor(float(SheenMax)) < float(peak) && SheenFloor(float(SheenMax)) > SheenFloor(1.0f));
            // the floor over near-black ground: a print on 0.005 stone reads at 0.012 (the dark red), under the 0.02
            // readable boundary; a print on the lit church slab (0.077 x 0.25) is above the floor and not lifted
            assert(SheenFloor(1.0f) > 0.005f * 0.25f * 4.0f && 0.077f * 0.25f > SheenFloor(1.0f));
        }
        // the view verdicts
        assert(ViewVerdict(0u, 500u, 0.5) == 0u && ViewVerdict(3u, 0u, 0.0) == 1u);
        assert(ViewVerdict(3u, 500u, 0.01) == 2u && ViewVerdict(3u, 500u, 0.05) == 3u);
'''),
        (r'''        assert(FlatWords == 42u && WordFlatRedPx != WordFlatPostPx); // (r111i) six luminance words
''',
         r'''        assert(FlatWords == 43u && WordFlatRedPx != WordFlatPostPx); // (r111i) six luminance words, (r111j) a sheen word
'''),
        (r'''        assert(FOOTPRINTS_FLAT_WORDS == FOOTPRINTS_FLAT_WORD_LUM + FOOTPRINTS_FLAT_LUM_WORDS);
''',
         r'''        assert(FOOTPRINTS_FLAT_WORD_SHEEN == FOOTPRINTS_FLAT_WORD_LUM + FOOTPRINTS_FLAT_LUM_WORDS &&
               FOOTPRINTS_FLAT_WORDS == FOOTPRINTS_FLAT_WORD_SHEEN + 1u);
'''),
    ],
    README: [
        (r'''In a build with the test tools' live knobs it is asked again every frame | `1` |
''',
         r'''In a build with the test tools' live knobs it is asked again every frame | `1` |
| `BB_FOOTPRINTS_SHEEN` | Only with `BB_FOOTPRINTS` on. A number from 0 to 4, default 0 (off; unset, empty, other text or a number out of range: 0). A faint wet sheen on blood prints so they read on near-black ground (a dark red of a quarter of the luminance of a moonlit graveyard cobble, 0.005 to 0.013, is the same black as the cobble): in the post stamp a blood print's pixel is lifted, in the blood tint, to at least 0.012 times this number in linear luminance, passed through the blood sheen's soft ceiling (untouched under half of 0.03, an exponential roll-off toward 0.03 above it, so 4 gives 0.0283 and never a hot spot), by the print's weight and cover; ground whose lit luminance is above the floor (the church's slabs, 0.08) is not touched, and wet and mud prints never get it. Wet prints on near-black stone stay invisible (a darkening cannot darken black); the log's view lines say so. In a build with the test tools' live knobs it is asked again every frame, so one running game can show the same view with and without it. Cost, only while on and only for the blood pixels of a stamp: a few multiplies and one exponential, plus one atomic on a counter word when the pixel was lifted; the counter buffer is 172 bytes | `0` |
'''),
        (r'''and "print strength gain now" at the first pass and at each change of the gain.''',
         r'''and "print strength gain now" at the first pass and at each change of the gain. Lines of r111j: once at the start what the view lines mean and the sheen's numbers; one `Footprints (r111j): view at frame ...` line per view (told when the verdict, the number of prints whose centre is inside the picture, the gain or the sheen changes, and every 120 passes, at most 80): the camera, the prints sent, those in the picture and behind the camera, the pixels the stamp wrote, their mean lit luminance before and after, the gain, the sheen and the verdict (0: no print in the picture, 1: in the picture but no pixel stamped, 2: stamped on near-black ground, mean lit luminance under 0.02, where a dark red or a darkening cannot read, 3: stamped on lit ground), so a picture without prints is told from prints out of frame or on black stone; and every 600 frames the blood pixels the sheen lifted.'''),
    ],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    """'applied' (each new text once), 'clean' (each old text once, no new text), else refuse."""
    done = todo = 0
    for old, new in eds:
        co, cn = cur.count(old), cur.count(new)
        if cn == 1 and (co == 0 or new.find(old) >= 0 and co == 1):
            done += 1
        elif cn == 0 and co == 1:
            todo += 1
        else:
            raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1 and 0, or 0 or 1 "
                             "and 1; is r111i applied, and is this patch's own earlier version reverted?): %r" %
                             (path, co, cn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, done, len(eds)))


def split_args(text):
    """The top-level comma separated arguments of a call's text after its format string."""
    out, depth, cur, quote = [], 0, "", False
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            cur += ch
            if ch == "\\":
                cur += text[i + 1]
                i += 1
            elif ch == '"':
                quote = False
        elif ch == '"':
            quote = True
            cur += ch
        elif ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    if cur.strip():
        out.append(cur.strip())
    return out


def define(lay, name):
    m = re.search(r"#define %s ([0-9.]+)u?\n" % name, lay)
    if not m:
        raise SystemExit("text check: layout lacks %s" % name)
    return float(m.group(1))


def text_checks(texts):
    """Ties a compiler cannot check, on the full result."""
    cpp = texts[VKC]
    n_new = 0
    for m in re.finditer(r'BbReport::Printf\(((?:\s*"(?:[^"\\]|\\.)*")+)(.*?)\);\n', cpp, re.S):
        fmt = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))).replace("\\n", "")
        if not fmt.startswith("Footprints (r111"):
            raise SystemExit("text check: a log line without its prefix: %r" % fmt[:60])
        if not fmt.startswith("Footprints (r111j)"):
            continue
        n_new += 1
        convs = re.findall(r"%(?!%)[-+ 0-9.]*(?:ll)?[udfs]", fmt.replace("%%", ""))
        args = split_args(m.group(2).lstrip().lstrip(",")) if m.group(2).strip() else []
        if len(convs) != len(args):
            raise SystemExit("text check: %d conversions, %d arguments: %r" % (len(convs), len(args), fmt[:70]))
        if "%s" in fmt:
            raise SystemExit("text check: a %%s in an r111j line (kinds fold on digits only): %r" % fmt[:60])
        for conv, arg in zip(convs, args):  # the type of each argument against its conversion
            if conv.endswith("llu") and "static_cast<unsigned long long>" not in arg:
                raise SystemExit("text check: %%llu without the cast: %r" % arg)
            if conv.endswith("f") and not arg.startswith("double(") and arg not in ("lum_before", "lum_after"):
                raise SystemExit("text check: %%f argument not a double(...): %r" % arg)
        wide = re.sub(r"%[-+]?[0-9]*\.[0-9]+f", "X" * 9, fmt)
        wide = re.sub(r"%(?:ll)?[ud]", "X" * 10, wide)
        wide = wide.replace("%%", "%")
        print("  r111j log line (wide %d, %d conversions): %s..." % (len(wide), len(convs), fmt[:50]))
        if len(wide) > 330:
            raise SystemExit("text check: a log line may pass 330 characters (%d): %r" % (len(wide), fmt[:60]))
    if n_new != 4:
        raise SystemExit("text check: %d r111j log lines (4 expected)" % n_new)
    lay = texts[LAYOUT]
    sky, peak, knee = (define(lay, "FOOTPRINTS_SHEEN_SKY"), define(lay, "FOOTPRINTS_SHEEN_PEAK"),
                       define(lay, "FOOTPRINTS_SHEEN_KNEE"))
    readable = define(lay, "FOOTPRINTS_VIEW_READABLE_LUM")
    if not (0.0 < sky < peak and 0.0 < knee < 1.0 and 0.0 < readable < 0.1):
        raise SystemExit("text check: sheen numbers out of range (sky %.4f peak %.4f knee %.2f)" % (sky, peak, knee))

    def roll(luma):
        k = knee * peak
        s = peak - k
        return luma if luma <= k else k + s * (1.0 - math.exp(-(luma - k) / s))

    top = roll(sky * 4.0)
    if not (sky * 4.0 > top > roll(sky * 2.0) > roll(sky) and top < peak):
        raise SystemExit("text check: the roll-off does not rise below the ceiling")
    print("  sheen floor: knob 1 -> %.4f, 2 -> %.4f, 4 -> %.4f (ceiling %.3f); readable boundary %.3f" %
          (roll(sky), roll(sky * 2.0), top, peak, readable))
    sheen_w = define(lay, "FOOTPRINTS_FLAT_WORD_SHEEN")
    lum = define(lay, "FOOTPRINTS_FLAT_WORD_LUM")
    if sheen_w != lum + define(lay, "FOOTPRINTS_FLAT_LUM_WORDS") or define(lay, "FOOTPRINTS_FLAT_WORDS") != sheen_w + 1:
        raise SystemExit("text check: the counter words do not tie (lum %d, sheen %d)" % (lum, sheen_w))
    flat = texts[FLAT]
    for needle in ("FOOTPRINTS_SHEEN_SKY", "FOOTPRINTS_SHEEN_PEAK", "FOOTPRINTS_SHEEN_KNEE", "FOOTPRINTS_FLAT_WORD_SHEEN",
                   "hunter.x > 0.0 && blood > max(wet, mud)", "float PeakRoll(float luma, float peak)"):
        if needle not in flat:
            raise SystemExit("text check: footprints_flat.comp lacks %r" % needle)
    if flat.count("atomicAdd(counts[FOOTPRINTS_FLAT_WORD_SHEEN], 1u);") != 1:
        raise SystemExit("text check: the shader should add the sheen word once")
    if "WordFlatSheen == WordFlatLum + FlatLumWords && FlatWords == WordFlatSheen + 1u" not in texts[RULES]:
        raise SystemExit("text check: footprints.h does not tie the counter words")
    for needle in ("void ViewRead(", "void LogView(", "void LogSheen() const;", "u32 in_frame = 0, behind = 0;",
                   "static constexpr u32 ViewMax = 80"):
        if needle not in texts[VKH]:
            raise SystemExit("text check: vk_footprints.h lacks %r" % needle)
    for needle in ("push.hunter = {R::Sheen(), 0.0f, 0.0f, 0.0f};", "ViewRead(snap, counts);", "snap.sheen = push.hunter[0];",
                   "stats.sheen_px += counts[R::WordFlatSheen];"):
        if needle not in cpp:
            raise SystemExit("text check: vk_footprints.cpp lacks %r" % needle)
    if cpp.count("LogSheen();") != 2 or cpp.count("LogView(0, FlatSnap{}") != 1:
        raise SystemExit("text check: LogSheen or the LogView zero copy calls are missing")
    if "SheenOfText(\"5\") == 0.0f" not in texts[TEST] or "FlatWords == 43u" not in texts[TEST]:
        raise SystemExit("text check: the unit test lacks the sheen asserts")
    for needle in ("| `BB_FOOTPRINTS_SHEEN` |", "Lines of r111j:"):
        if texts[README].count(needle) != 1:
            raise SystemExit("text check: README lacks %r once" % needle)
    for path, eds in EDITS.items():
        for old, new in eds:
            if "\t" in new or "\r" in new:
                raise SystemExit("text check: an edit of %s has a tab or a CR" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 r111j_prints-lit-graveyard.py check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R111J_ROOT)" % ROOT)
    if "(r111i) next to something much nearer" not in load(FLAT)[2]:
        raise SystemExit("REFUSED: r111i is not applied (%s lacks its silhouette rule)" % FLAT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in eds:
                cur = cur.replace(old, new, 1)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (%d files edited; text checks pass)" % len(plan))
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)" %
                  (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r111jtmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied (%d files edited)" % len(plan))
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for old, new in reversed(eds):
            if cur.count(new) != 1:
                raise SystemExit("%s: new text found %d times in the revert: %r" % (path, cur.count(new), new[:70]))
            cur = cur.replace(new, old, 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r111jtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted (%d files edited back)" % len(plan))


main()
