# r100k_sheen-no-hot-spot: FEATURE fix on top of r100j_sheen-clean-rim (r100i, r100h, r100g, r100f, r100e, r100d;
# branch visual/blood-sheen). Applies ON TOP of r100j (refuses a tree without it). Off by default: BB_BLOOD_SHEEN
# unset makes no BloodSheen, so nothing of this runs and the frame stays bit-identical (r100d's null pointer test
# per hook). The G-buffer passes SNAPSHOT and MARK are untouched (their SPIR-V is byte-identical).
#
# Why (build 49, graveyard-blood, zoom _rd_blood_pair.png): the rim speckle of r100j is mostly gone, the body is the
# dark red wet sheet the owner was sent, but a bright orange-red blotch sits on the pool by the hunter's feet
# (strength 1, brighter at 2): a near light's specular on the very sharp wet lobe (gloss 0.86 = exponent 2320, red
# f0 0.15 at strength 1, 0.29 at 2): the highlight's peak of a near lamp is hundreds of times its diffuse level.
# The G-buffer pass cannot know a light's distance (the lights run later), so the fix is in two places:
#  1. SHOW pass (after the game's opaque lighting), the picked pixels only: a soft luminance CEILING with a knee.
#     luma <= knee: unchanged (knee = 0.5 x peak); above: knee + span x (1 - exp(-(luma - knee) / span)), span =
#     peak - knee, and the pixel's colour is scaled by new luma / luma (hue kept). Peak default 0.7 (knee 0.35):
#     the moonlit dark red sheet (a few tenths at most) is as b49, a near light's hot spot rolls off toward 0.7 and
#     can no longer blow out, at any strength. BB_BLOOD_SHEEN_PEAK (0..8, 0 = no ceiling, live in test builds)
#     tunes or switches it. The pass also runs now when the dimming is 0 and the ceiling is on.
#  2. EDIT pass, the rim: a gap-fill pixel's specular weight is its fill weight AGAIN (squared falloff) times the
#     rim share, and the rim cap goes from 0.5 to 0.35 (BLOOD_SHEEN_FILL_SPEC): ws = strength x fill^2 x
#     mix(0.35, 1, smoothstep(0.8, 1, share)); a pixel that passes the albedo rule is as before (weight 1 x w).
#     The normal levelling keeps w (unchanged).
#
# Cost: SHOW: for each picked pixel one luminance dot, one exp (only when above the knee) and one scale; the pass
# itself exists already (r100e's dimming); with the dimming 0 and the ceiling on it is the same pass. No fetch
# beyond the pixel's own, no image, no memory. EDIT: one extra multiply per filled pixel. Estimate, not measured:
# far below 0.01 ms beyond the 0.05 ms of the existing show pass. Off by default, costs nothing off.
#
# Files (anchored edits on r100j's text; each edit must be found exactly once): host_shaders/blood_sheen_layout.h,
# blood_sheen.comp, renderer_vulkan/blood_sheen.h, vk_blood_sheen.h, vk_blood_sheen.cpp, tests/
# test_blood_sheen.cpp, README.md. CMakeLists.txt and build.sh need no edit. The SHOW pass reads the ceiling from
# the push word `ratio` (unused there: the albedo rule's ratio belongs to EDIT); the push block stays 8 words.
#
# Use: python -I -X utf8 r100k_sheen-no-hot-spot.py check | apply | revert. Root from R100K_ROOT, else
# <tree>. Line ends kept; apply keeps the originals in r100k_sheen-no-hot-spot_backup/ next to this script;
# a mixed state is refused and nothing is written. Revert order: this script, then r100j.
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "r100k_sheen-no-hot-spot"
BASE = "r100j_sheen-clean-rim.py"
ROOT_ENV = "R100K_ROOT"
ROOT = os.environ.get(ROOT_ENV) or "<tree>"
BACKUP = os.path.join(HERE, NAME + "_backup")
TMP = ".r100ktmp"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
LAYOUT = HS + "blood_sheen_layout.h"
COMP = HS + "blood_sheen.comp"
RULES = RV + "blood_sheen.h"
SHEENH = RV + "vk_blood_sheen.h"
SHEEN = RV + "vk_blood_sheen.cpp"
TEST = "engine/tests/test_blood_sheen.cpp"
README = "README.md"

EDITS = {
LAYOUT: [
(r'''// mix(FILL_SPEC, 1, smoothstep(FILL_HI, 1, share)): at the pool's rim at most FILL_SPEC (0.5) of the body's,
''',
r'''// mix(FILL_SPEC, 1, smoothstep(FILL_HI, 1, share)): at the pool's rim at most FILL_SPEC (0.35, r100k) of the body's,
'''),
(r'''#define BLOOD_SHEEN_FILL_SPEC 0.5
''',
r'''#define BLOOD_SHEEN_FILL_SPEC 0.35
// r100k_sheen-no-hot-spot: the gap-fill pixel's specular weight is also multiplied by its fill weight again (a squared
// falloff toward the rim's outer edge). SHOW, the picked pixels of the lit scene: a soft luminance ceiling,
// PEAK (BB_BLOOD_SHEEN_PEAK, default 0.7); luminance up to KNEE x PEAK is untouched, above it rolls off
// exponentially toward PEAK (colour scaled, hue kept). A near light's tight highlight on the wet lobe cannot
// blow out; the moonlit dark red sheet (below the knee) is as before. PEAK 0: no ceiling.
#define BLOOD_SHEEN_PEAK_DEFAULT 0.7
#define BLOOD_SHEEN_PEAK_KNEE 0.5
'''),
],

COMP: [
(r'''            const float ws = w * rim_k;
''',
r'''            // r100k_sheen-no-hot-spot: a gap-fill pixel's weight is also scaled by its fill weight again (squared
            // falloff), its rim cap is FILL_SPEC 0.35; a pixel that passes the albedo rule keeps w (as b49).
            const float ws = w * (filled ? wet : 1.0) * rim_k;
'''),
(r'''void main() {
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
''',
r'''#if defined(BLOOD_SHOW)
// r100k_sheen-no-hot-spot: BloodSheenRules::PeakRoll, the same arithmetic: luminance up to the knee as it is, above
// it an exponential roll-off toward `peak` (continuous, slope 1 at the knee, never above peak).
float PeakRoll(float luma, float peak) {
    const float knee = BLOOD_SHEEN_PEAK_KNEE * peak;
    const float span = peak - knee;
    return luma <= knee ? luma : knee + span * (1.0 - exp(-(luma - knee) / span));
}
#endif

void main() {
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
'''),
(r'''            const float darken = uintBitsToFloat(unused);
            if (tag == BLOOD_SHEEN_TAG_WET && darken > 0.0) {
                const vec4 c = imageLoad(scene_img, p);
                const float luma = dot(c.rgb, vec3(0.2126, 0.7152, 0.0722));
                const float dim = clamp(darken, 0.0, 1.0) *
                                  (1.0 - smoothstep(BLOOD_SHEEN_DARKEN_LUMA_LO, BLOOD_SHEEN_DARKEN_LUMA_HI, luma));
                const vec3 mult = mix(vec3(1.0), vec3(BLOOD_SHEEN_DARKEN_RED, BLOOD_SHEEN_DARKEN_OTHER, BLOOD_SHEEN_DARKEN_OTHER), dim);
                imageStore(scene_img, p, vec4(c.rgb * mult, c.a));
            }
''',
r'''            const float darken = uintBitsToFloat(unused);
            // r100k_sheen-no-hot-spot: the luminance ceiling of the picked pixels (0: none) is in the push word
            // `ratio` (the albedo rule's ratio is for EDIT only); with it the pass also runs at darken 0.
            const float peak = ratio;
            if (tag == BLOOD_SHEEN_TAG_WET && (darken > 0.0 || peak > 0.0)) {
                const vec4 c = imageLoad(scene_img, p);
                const float luma = dot(c.rgb, vec3(0.2126, 0.7152, 0.0722));
                const float dim = clamp(darken, 0.0, 1.0) *
                                  (1.0 - smoothstep(BLOOD_SHEEN_DARKEN_LUMA_LO, BLOOD_SHEEN_DARKEN_LUMA_HI, luma));
                const vec3 mult = mix(vec3(1.0), vec3(BLOOD_SHEEN_DARKEN_RED, BLOOD_SHEEN_DARKEN_OTHER, BLOOD_SHEEN_DARKEN_OTHER), dim);
                vec3 lit = c.rgb * mult;
                if (peak > 0.0) {
                    const float lit_luma = dot(lit, vec3(0.2126, 0.7152, 0.0722));
                    if (lit_luma > BLOOD_SHEEN_PEAK_KNEE * peak) {
                        lit *= PeakRoll(lit_luma, peak) / lit_luma;
                    }
                }
                imageStore(scene_img, p, vec4(lit, c.a));
            }
'''),
],

RULES: [
(r'''//                         the default.
// No Vulkan here:''',
r'''//                         the default.
//   BB_BLOOD_SHEEN_PEAK   bbport (r100k): 0..8, default 0.7: the lit scene's luminance ceiling for the picked
//                         pixels (a soft roll-off above half of it: a near light's highlight cannot blow
//                         out); 0: no ceiling. Unset or other text: the default.
// No Vulkan here:'''),
(r'''static_assert(BLOOD_SHEEN_FILL_SPEC == 0.5);
''',
r'''static_assert(BLOOD_SHEEN_FILL_SPEC == 0.35);
inline constexpr float PeakDefault = float(BLOOD_SHEEN_PEAK_DEFAULT); ///< r100k: BB_BLOOD_SHEEN_PEAK's default
inline constexpr float PeakKnee = float(BLOOD_SHEEN_PEAK_KNEE);       ///< r100k: the knee, as a share of the peak
inline constexpr float MaxPeak = 8.0f;                                ///< r100k: the largest BB_BLOOD_SHEEN_PEAK
static_assert(BLOOD_SHEEN_PEAK_DEFAULT == 0.7 && BLOOD_SHEEN_PEAK_KNEE == 0.5);
'''),
(r'''/// The knobs, read once.
inline const Knobs& Load() {''',
r'''/// BB_BLOOD_SHEEN_PEAK's text (r100k_sheen-no-hot-spot): a number into 0..MaxPeak (0: no ceiling); unset, empty or
/// other text: the default. Never a pure function of anything but its text, so the live knobs can call it.
inline float ReadPeak(const char* text) {
    if (text == nullptr || text[0] == '\0') {
        return PeakDefault;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || !std::isfinite(value)) {
        return PeakDefault;
    }
    while (*end == ' ') {
        ++end;
    }
    return *end == '\0' ? std::clamp(value, 0.0f, MaxPeak) : PeakDefault;
}

/// The knobs, read once.
inline const Knobs& Load() {'''),
(r'''    return FillSpec + (1.0f - FillSpec) * t;
}
''',
r'''    return FillSpec + (1.0f - FillSpec) * t;
}
/// bbport (r100k_sheen-no-hot-spot): the weight a made-wet pixel gives its specular tint and gloss (the shader's
/// `ws`): w (strength, at most 1, times the fill weight `wet`) for a pixel that passes the albedo rule; for a
/// gap-fill pixel w times its fill weight AGAIN (squared falloff) times RimSpecShare: never above FillSpec (0.35)
/// x w where the share is at most FILL_HI, never above w.
inline float SpecWeight(float w, float wet, bool filled, float pool_share) {
    return w * (filled ? wet : 1.0f) * RimSpecShare(filled, pool_share);
}
/// bbport (r100k_sheen-no-hot-spot): the SHOW pass's luminance after the soft ceiling `peak` (> 0): unchanged up to
/// the knee (PeakKnee x peak), above it knee + span x (1 - exp(-(luma - knee) / span)), span = peak - knee:
/// continuous, slope 1 at the knee, increasing, never above peak. The pixel's colour is scaled by this / luma.
inline float PeakRoll(float luma, float peak) {
    const float knee = PeakKnee * peak;
    const float span = peak - knee;
    return luma <= knee ? luma : knee + span * (1.0f - std::exp(-(luma - knee) / span));
}
'''),
],

SHEENH: [
(r'''previews = 0, lamps_pending = 0, normals = 0;
''',
r'''previews = 0, lamps_pending = 0, normals = 0;
        u32 peak_shows = 0; ///< r100k: shows with the luminance ceiling on
'''),
],

SHEEN: [
(r'''vk::DescriptorImageInfo Info(vk::ImageView view) {
''',
r'''/// BB_BLOOD_SHEEN_PEAK (r100k_sheen-no-hot-spot): the lit scene's luminance ceiling for the picked pixels, 0: none.
/// Live in a build with the live knobs header (a test aid: the same view with and without it); said in the log at
/// each change (and once at the first use).
float PeakCap() {
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static BbLiveKnobs::Knob<float> knob{"BB_BLOOD_SHEEN_PEAK", R::ReadPeak};
    const float now = knob.Get();
#else
    static const float fixed = R::ReadPeak(std::getenv("BB_BLOOD_SHEEN_PEAK"));
    const float now = fixed;
#endif
    static float last = -1.0f;
    if (now != last) {
        last = now;
        if (now > 0.0f) {
            BbReport::Printf("Blood sheen (r100k): luminance ceiling %.2f on the picked pixels of the lit scene "
                             "(soft above %.2f; BB_BLOOD_SHEEN_PEAK)\n",
                             double(now), double(R::PeakKnee * now));
        } else {
            BbReport::Printf("Blood sheen (r100k): no luminance ceiling (BB_BLOOD_SHEEN_PEAK 0)\n");
        }
    }
    return now;
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
'''),
(r'''                     double(R::FillSpec));
''',
r'''                     double(R::FillSpec));
    // bbport (r100k_sheen-no-hot-spot): the rim's weight falls with the square of its fill weight.
    BbReport::Printf("Blood sheen (r100k): a rim pixel's specular weight is its fill weight squared times at most "
                     "%.2f; a near light's highlight on the pool is rolled off by a luminance ceiling "
                     "(default %.2f, BB_BLOOD_SHEEN_PEAK, 0 = none)\n",
                     double(R::FillSpec), double(R::PeakDefault));
'''),
(r'''    show_due = k.show || k.darken > 0.0f; // the test view, or the dimming after the lighting
''',
r'''    show_due = k.show || k.darken > 0.0f || PeakCap() > 0.0f; // the test view, the dimming or the ceiling (r100k)
'''),
(r'''    push.darken = k.show ? 0.0f : k.darken * std::min(k.strength, 1.0f);
    ++stats.shows;
''',
r'''    push.darken = k.show ? 0.0f : k.darken * std::min(k.strength, 1.0f);
    push.ratio = k.show ? 0.0f : PeakCap(); // r100k: the SHOW pass reads its luminance ceiling from `ratio`
    stats.peak_shows += push.ratio > 0.0f ? 1u : 0u;
    ++stats.shows;
'''),
(r'''                     100.0 * double(c[R::WordGlossy]) / wet, double(R::WetGloss), stats.normals, stats.edits);
''',
r'''                     100.0 * double(c[R::WordGlossy]) / wet, double(R::WetGloss), stats.normals, stats.edits);
    BbReport::Printf("Blood sheen (r100k): %u of %u shows with the luminance ceiling %.2f (0: none)\n",
                     stats.peak_shows, stats.shows, double(PeakCap()));
'''),
],

TEST: [
(r'''        // albedo rule is the body (1); a gap-fill pixel gets half at the rim and in the fill's range up to
''',
r'''        // albedo rule is the body (1); a gap-fill pixel gets 0.35 (r100k) at the rim and in the fill's range up to
'''),
(r'''        assert(Near(FillSpec, 0.5, 1e-6));
''',
r'''        assert(Near(FillSpec, 0.35, 1e-6));
'''),
(r'''        assert(Near(RimSpecShare(true, 0.5f), 0.5) && Near(RimSpecShare(true, 0.65f), 0.5) && Near(RimSpecShare(true, 0.8f), 0.5));
        assert(Near(RimSpecShare(true, 0.9f), 0.75) && Near(RimSpecShare(true, 1.0f), 1.0));
''',
r'''        assert(Near(RimSpecShare(true, 0.5f), 0.35) && Near(RimSpecShare(true, 0.65f), 0.35) && Near(RimSpecShare(true, 0.8f), 0.35));
        assert(Near(RimSpecShare(true, 0.9f), 0.675) && Near(RimSpecShare(true, 1.0f), 1.0));
'''),
(r'''a >= 0.5f - 1e-6f &&''',
r'''a >= 0.35f - 1e-6f &&'''),
(r'''tint and gloss half of the body's.
''',
r'''tint and gloss 0.35 of the body's (r100k).
'''),
(r'''            assert(Near(fill, 1.0) && Near(k, 0.5));
            assert(Near(rim.g, 0.2 + (body.g - 0.2) * 0.5, 1e-4) && Near(rim.b, 0.2 + (body.b - 0.2) * 0.5, 1e-4));
            assert(rim.r >= 0.2f && Near(Wet(0.3f, 0.2f, 1.0f, fill * k).gloss, 0.3 + (WetGloss - 0.3) * 0.5, 1e-4));
''',
r'''            assert(Near(fill, 1.0) && Near(k, 0.35));
            assert(Near(rim.g, 0.2 + (body.g - 0.2) * 0.35, 1e-4) && Near(rim.b, 0.2 + (body.b - 0.2) * 0.35, 1e-4));
            assert(rim.r >= 0.2f && Near(Wet(0.3f, 0.2f, 1.0f, fill * k).gloss, 0.3 + (WetGloss - 0.3) * 0.35, 1e-4));
'''),
(r'''            assert(Near(rim2.g, body2.g * 0.5, 1e-4) && Near(rim2.r, body2.r * 0.5, 1e-4));
        }
''',
r'''            assert(Near(rim2.g, body2.g * 0.5, 1e-4) && Near(rim2.r, body2.r * 0.5, 1e-4));
        }
        // k. bbport (r100k_sheen-no-hot-spot): the rim's squared falloff and the luminance ceiling.
        assert(Near(PeakDefault, 0.7, 1e-6) && Near(PeakKnee, 0.5, 1e-6));
        assert(SpecWeight(0.6f, 1.0f, false, 0.7f) == 0.6f && SpecWeight(1.0f, 1.0f, false, 0.0f) == 1.0f);
        assert(Near(SpecWeight(0.5f, 0.5f, true, 0.65f), 0.5 * 0.5 * 0.35));        // half fill at the rim: 0.0875
        assert(Near(SpecWeight(1.0f, 1.0f, true, 0.8f), 0.35));                      // full fill at the rim: the cap
        assert(Near(SpecWeight(1.0f, 1.0f, true, 1.0f), 1.0));                       // deep inside: the body
        for (float share = 0.0f; share <= 0.8f; share += 0.01f) {                  // the rim never above the cap
            for (float wet = 0.0f; wet <= 1.0f; wet += 0.1f) {
                assert(SpecWeight(wet, wet, true, share) <= 0.35f * wet + 1e-6f);
                assert(SpecWeight(wet, wet, true, share) <= SpecWeight(wet, 1.0f, false, share) + 1e-6f);
            }
        }
        for (float wet = 0.0f; wet < 1.0f; wet += 0.01f) {                         // never decreases with the fill weight
            assert(SpecWeight(wet + 0.01f, wet + 0.01f, true, 0.7f) >= SpecWeight(wet, wet, true, 0.7f));
        }
        assert(PeakRoll(0.0f, 0.7f) == 0.0f && PeakRoll(0.1f, 0.7f) == 0.1f && PeakRoll(0.35f, 0.7f) == 0.35f);
        assert(Near(PeakRoll(0.36f, 0.7f), 0.36, 2e-3));                            // slope 1 at the knee: no step
        for (float l = 0.0f; l < 40.0f; l += 0.01f) {
            const float a = PeakRoll(l, 0.7f), b = PeakRoll(l + 0.01f, 0.7f);
            assert(b >= a && b - a <= 0.01f + 1e-6f && a <= 0.7f + 1e-6f && a <= l + 1e-6f);
        }
        assert(PeakRoll(1.0e4f, 0.7f) <= 0.7f + 1e-6f && PeakRoll(1.0e4f, 0.7f) > 0.69f);
        assert(PeakRoll(5.0f, 0.7f) < 0.7f && PeakRoll(5.0f, 0.7f) > 0.69f);       // a hot spot of luminance 5 reads 0.7
        assert(PeakRoll(0.5f, 0.7f) > 0.45f && PeakRoll(0.5f, 0.7f) < 0.5f);       // a bright sheet is only touched a little
        assert(ReadPeak(nullptr) == PeakDefault && ReadPeak("") == PeakDefault && ReadPeak("x") == PeakDefault);
        assert(ReadPeak("0") == 0.0f && ReadPeak("1.5") == 1.5f && ReadPeak(" 2") == 2.0f);
        assert(ReadPeak("99") == MaxPeak && ReadPeak("-1") == 0.0f && ReadPeak("0.5x") == PeakDefault);
        assert(ReadPeak("nan") == PeakDefault && ReadPeak("inf") == PeakDefault);
'''),
],

README: [
(r'''gets at most half of that tint and gloss (BLOOD_SHEEN_FILL_SPEC 0.5, rising smoothly''',
 r'''gets at most 0.35 of that tint and gloss, scaled again by its own fill weight (squared falloff; BLOOD_SHEEN_FILL_SPEC 0.35, rising smoothly'''),
(r'''| `BB_BLOOD_SHEEN_PAUSE` | A test knob''',
 r'''| `BB_BLOOD_SHEEN_PEAK` | Only with `BB_BLOOD_SHEEN` on. 0 to 8: a soft luminance ceiling for the picked pixels of the lit scene, applied after the game's opaque lighting in the same pass as the dimming: luminance up to half of it is untouched, above it rolls off toward it (colour scaled, hue kept), so a near lamp's or torch's tight highlight on the wet lobe cannot blow out an orange-red blotch; the moonlit dark red sheet is below the knee and unchanged. `0`: no ceiling. Unset or other text: the default. Live in a test build (live knobs file), the log says each change. Cost: one luminance and one exp for each picked pixel, inside the dimming pass (an estimate, not measured: far below 0.01 ms beyond it); with the dimming 0 and the ceiling on the pass runs for the ceiling alone | `0.7` |
| `BB_BLOOD_SHEEN_PAUSE` | A test knob'''),
],
}

ORDER = list(EDITS)


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        raise SystemExit("REFUSED %s: missing" % path)
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def one_state(cur, old, new):
    """An edit's state: a replacement (old not in new) or an insertion (new holds old)."""
    o, n = cur.count(old), cur.count(new)
    inner = new.count(old)
    if n == 1 and o == inner:
        return "applied"
    if n == 0 and o == 1:
        return "clean"
    return None


def edit_state(path, cur):
    states = [one_state(cur, old, new) for old, new in EDITS[path]]
    if None in states:
        bad = EDITS[path][states.index(None)]
        raise SystemExit("REFUSED %s: an edit's text is not found exactly once (before: %d times, after: %d "
                         "times; %s must be applied): %r" % (path, cur.count(bad[0]), cur.count(bad[1]), BASE,
                                                              bad[0][:70]))
    if all(s == "applied" for s in states):
        return "applied"
    if all(s == "clean" for s in states):
        return "clean"
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, states.count("applied"), len(states)))


def need(path, text, want, n=1):
    if text.count(want) != n:
        raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, want[:90], text.count(want), n))


def text_checks(t):
    comp, lay, hdr, cpp, tst = t[COMP], t[LAYOUT], t[RULES], t[SHEEN], t[TEST]
    need(LAYOUT, lay, "#define BLOOD_SHEEN_FILL_SPEC 0.35\n")
    need(LAYOUT, lay, "#define BLOOD_SHEEN_PEAK_DEFAULT 0.7\n")
    need(LAYOUT, lay, "#define BLOOD_SHEEN_PEAK_KNEE 0.5\n")
    need(LAYOUT, lay, "#define BLOOD_SHEEN_TINT_R 0.85\n")  # r100i is under this
    need(COMP, comp, "const float ws = w * (filled ? wet : 1.0) * rim_k;")
    need(COMP, comp, "m.r = mix(m.r, BLOOD_SHEEN_WET_GLOSS, ws);")
    need(COMP, comp, "s.gb = mix(s.gb, target.gb, ws);")
    need(COMP, comp, "const float level = BLOOD_SHEEN_NORMAL_SMOOTH * w *")  # the levelling keeps w (unchanged)
    need(COMP, comp, "float PeakRoll(float luma, float peak)")
    need(COMP, comp, "const float peak = ratio;")
    need(COMP, comp, "barrier()", 2)                      # the counter code's two only
    need(RULES, hdr, "static_assert(BLOOD_SHEEN_FILL_SPEC == 0.35);")
    need(RULES, hdr, "inline float ReadPeak(const char* text)")
    need(RULES, hdr, "inline float PeakRoll(float luma, float peak)")
    need(RULES, hdr, "inline float SpecWeight(")
    need(SHEEN, cpp, "float PeakCap()")
    need(SHEEN, cpp, "push.ratio = k.show ? 0.0f : PeakCap();")
    need(SHEEN, cpp, "Blood sheen (r100j): the pool's rim")
    need(SHEEN, cpp, "Blood sheen (r100k): a rim pixel's")
    need(TEST, tst, "// k. bbport (r100k_sheen-no-hot-spot)")
    for line in cpp.split("\n"):
        if 'BbReport::Printf("' in line and "Blood sheen (r100" not in line and "Blood sheen (r128d)" not in line:
            raise SystemExit("text check: a log line without its prefix: %r" % line)
    added = [new for eds in EDITS.values() for old, new in eds]
    if any(ord(ch) > 127 for text in added for ch in text):
        raise SystemExit("text check: a new text is not plain ASCII")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 %s.py check | apply | revert" % NAME)
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set %s)" % (ROOT, ROOT_ENV))
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, raw, eol, cur, edit_state(path, cur)))
    states = {p[4] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[4]) for p in plan))
    state = states.pop()

    def result(forward):
        out = {}
        for path, raw, eol, cur, _ in plan:
            for old, new in EDITS[path]:
                cur = cur.replace(old, new) if forward else cur.replace(new, old)
            want = "applied" if forward else "clean"
            if edit_state(path, cur) != want:
                raise SystemExit("%s: the result does not read as %s; nothing written" % (path, want))
            out[path] = cur
        return out

    def write(texts):
        for path, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            open(full + TMP, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(full + TMP, full)

    edits = sum(len(e) for e in EDITS.values())
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[3] for p in plan})
            print("applied (%d edits in %d files; text checks pass)" % (edits, len(EDITS)))
        else:
            text_checks(result(True))
            print("not applied; would apply (%d edits in %d files; text checks on the result pass)" % (edits, len(EDITS)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = result(True)
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        write(texts)
        print("applied (%d edits in %d files)" % (edits, len(EDITS)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    write(result(False))
    print("reverted (%d edits taken out of %d files)" % (edits, len(EDITS)))


main()
