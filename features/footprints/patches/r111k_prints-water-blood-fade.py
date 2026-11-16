# r111k_prints-water-blood-fade: FEATURE change on top of r111 to r111j (owner, 2026-11-16, 4K run of build 72, his words:
# "Foot prints work, but I can't tell a difference between water footprints and blood. Some times they work and sometimes
# they don't and they start and end abruptly"). Still off unless BB_FOOTPRINTS is set, and costs nothing when off: every
# edit is inside Footprints (not made without the knob) or inside the two footprint shaders (dispatched only by it); the
# new rules run only inside Footprints::OnFrameEnd and the new shader branches are uniform tests on a push word.
# Branch: visual/footprints.
#
# WHAT THE LOG OF THE OWNER'S RUN SAID (owner_b72_run1.log, the graveyard and church stretches)
#  - Blood pickups hover at the pickup rule: "share of the pickup disc in blood last 28%, max 29%, mean 27%" against a
#    threshold of 25%, "blood pickups 14" in one 600-frame window with only 3 steps in blood: the pool's own albedo
#    (linear 0.031 0.015 0.014: red only 2.1 times the green, the rule wants 2.5) classifies about 30% of the pool as
#    blood, so the pickup flickers on and off at the edge of the pool and a coat comes with strength 0.5 ("coat blood
#    0.50": the share 28% over 50%). That is the "sometimes they work": a blood trail starts late, with half strength or
#    not at all. Wet pickups (water, puddles) worked in the log ("picked up 3 wet", prints placed), but a puddle disc
#    that dips under 30% glossy pixels for a frame drops the source.
#  - A trail is 1 (blood) or 3 (wet) full prints then x0.8 or x0.75 a step and a hard stop at 0.06 (the post stamp rounds a
#    faint weight to 1 - (1 - w)^2, so the last print reads 0.13 and the next one is nothing): "end abruptly". A print
#    appears at once at its whole strength when the stride is complete: "start abruptly".
#  - Wet and blood differ only by hue on a dark ground (wet: darken 65% then 55%; blood: dark red at 0.25 of the lit
#    luminance, sheen floor off by default): on the moonlit cobbles both are a dark patch.
#
# WHAT CHANGES (all in the footprints files; two knobs, both default ON, both live with the test tools' knobs)
#  (1) BB_FOOTPRINTS_TRAIL ("0": r111j's rules, every number as before):
#      - Pickup held: blood is picked up from 15% of the pickup disc (was 25%) and, once the feet are in it, held while the
#        share stays at 8% or more (stay rule); a puddle is picked up as before (30% of the ground band glossy) and held
#        down to 15%. A pool is one pickup, not a flicker.
#      - Coat strength: a blood coat's strength is the share over 30% (was 50%): the pool's 28% is a full coat; the
#        strongest share of one visit to the pool is kept (a frame at the edge does not lower it).
#      - Soft end: a trail is TrailFull = 2 prints at the whole strength, then a smoothstep taper to nothing over 14 prints
#        (wet) or 16 (blood): the last print is 1.7% (wet) or 1.3% (blood) of the coat, under the shader's 1/64 draw limit
#        in all but a hair, so the trail ends in nothing. Standing in a source starts the trail over.
#      - Soft start: a new print fades in over 0.30 s (smoothstep) and then fades out over 30 s as before; the print is
#        kept in the table while it fades in (the drop test would remove an invisible new print).
#  (2) BB_FOOTPRINTS_LOOK ("0": r111j's look): water and blood told apart.
#      Wet = darker (G-buffer darkening 70%, was 65%; post stamp 65%, was 55%), glossier (a dull ground's gloss raised toward
#      0.85 in the G-buffer, never lowered, the specular colour untouched as r111g left it) and, on near-black ground where a
#      darkening cannot show, a faint COOL grey (a wet film's sky reflection: luminance floor 0.007, hue 0.88 1.02 1.11);
#      no red anywhere in a wet print. Blood = dark red as before, with r111j's blood sheen floor ALWAYS on (as
#      BB_FOOTPRINTS_SHEEN=1: floor 0.012 in the red tint), so on near-black ground a blood print is a faint red sole and a
#      wet one a fainter grey-blue sole. The knob travels in the post stamp's `hunter.y` and the G-buffer pass's `hunter.w`
#      (both unused until now; the push block stays 112 bytes).
#  (3) Log: three lines "Footprints (r111k): ..." (the trail's numbers once, the look's numbers once, and a counter line at
#      construction (zeros), frame 240-style every 600 frames: prints placed by the trail rules, how many in the taper,
#      frames a pickup was held by the stay share, the coat's position in its trail). No new GPU counter word.
#
# How the code guarantees nothing runs when the feature is off: BB_FOOTPRINTS unset -> Footprints is not made and its hooks
# are one null pointer test each (vk_rasterizer_effects.cpp, not touched here); the rules in footprints.h are called only
# from Footprints; the shader edits are reached only by that object's dispatches. With the feature on and both knobs "0":
# trail false (every new branch in Soak/TakeStep/the fade loop is `if (k.trail)`), hunter.y and hunter.w are 0 (the new
# shader branches are `look ? new : old` on a uniform), blood_sheen = hunter.x as in r111j: r111j's picture and log numbers.
# Cost: CPU a few multiplies a frame; GPU nothing measurable (a few ALU ops on the pixels a print stamps; one extra
# gloss write on wet G-buffer pixels). Memory: none.
#
# Files edited (the text r111j left; each old text found exactly once): footprints_layout.h, footprints_flat.comp,
# footprints.comp, footprints.h, vk_footprints.h, vk_footprints.cpp, engine/tests/test_footprints.cpp, README.md.
# r111j's own `check` refuses after this patch (its text of push.hunter and the sheen block); revert r111k before r111j.
#
# Order: needs r111j applied (refused otherwise).
# Use: python -I -X utf8 r111k_prints-water-blood-fade.py check | apply | revert
# Root: R111K_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r111k_backup next to this script; revert puts each old text back (each new text found by itself, exactly once).
import math, os, re, sys

ROOT = os.environ.get("R111K_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r111k_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RULES = RV + "footprints.h"
VKH = RV + "vk_footprints.h"
VKC = RV + "vk_footprints.cpp"
LAYOUT = HS + "footprints_layout.h"
FLAT = HS + "footprints_flat.comp"
COMP = HS + "footprints.comp"
TEST = "engine/tests/test_footprints.cpp"
README = "README.md"
ORDER = [LAYOUT, FLAT, COMP, RULES, VKH, VKC, TEST, README]

# (old, new): `old` found exactly once and `new` not at all (clean), or `new` exactly once (applied).
EDITS = {
    LAYOUT: [
        (r'''#define FOOTPRINTS_VIEW_READABLE_LUM 0.02
''',
         r'''#define FOOTPRINTS_VIEW_READABLE_LUM 0.02
// (r111k) Water against blood (BB_FOOTPRINTS_LOOK, default on; 0 is r111j's look). A wet print darkens more (the G-buffer
// change K_WET_DARKEN, was 0.65; the post stamp K_POST_WET_DARKEN, was 0.55), raises a dull ground's gloss toward
// K_WET_GLOSS (never lowered; the specular colour is not touched, as r111g left it) and on near-black ground is lifted to
// a faint COOL grey, a wet film's sky reflection: luminance floor K_WET_SHEEN in the hue K_WET_TINT (luminance 1, so the
// lift adds exactly the floor; no red). A blood print keeps its dark red and, under the look, always has the blood
// sheen's floor (K_BLOOD_SHEEN times SHEEN_SKY, as BB_FOOTPRINTS_SHEEN=1). Wet reads dark, cool and glossy; blood dark red.
#define FOOTPRINTS_K_WET_DARKEN 0.70
#define FOOTPRINTS_K_POST_WET_DARKEN 0.65
#define FOOTPRINTS_K_WET_GLOSS 0.85
#define FOOTPRINTS_K_WET_SHEEN 0.007
#define FOOTPRINTS_K_WET_TINT_R 0.88
#define FOOTPRINTS_K_WET_TINT_G 1.02
#define FOOTPRINTS_K_WET_TINT_B 1.11
#define FOOTPRINTS_K_BLOOD_SHEEN 1.0
'''),
    ],
    FLAT: [
        (r'''// BB_FOOTPRINTS_SHEEN (the blood prints' wet sheen, 0: off), the rest of `hunter` is not used.
''',
         r'''// BB_FOOTPRINTS_SHEEN (the blood prints' wet sheen, 0: off), (r111k) `hunter.y` is the look (BB_FOOTPRINTS_LOOK, 1: on,
// 0: r111j's look), the rest of `hunter` is not used.
'''),
        (r'''    vec3 rgb = c.rgb * (1.0 - FOOTPRINTS_POST_WET_DARKEN * max(wet, mud));
''',
         r'''    const bool look = hunter.y > 0.5; // (r111k) BB_FOOTPRINTS_LOOK: water and blood told apart
    vec3 rgb = c.rgb * (1.0 - (look ? FOOTPRINTS_K_POST_WET_DARKEN : FOOTPRINTS_POST_WET_DARKEN) * max(wet, mud));
'''),
        (r'''    if (hunter.x > 0.0 && blood > max(wet, mud)) { // (r111j) the wet film's faint sky reflection on a blood print
        const float sheen_floor = PeakRoll(FOOTPRINTS_SHEEN_SKY * hunter.x, FOOTPRINTS_SHEEN_PEAK);
''',
         r'''    // (r111k) the look gives a blood print the sheen's floor even with BB_FOOTPRINTS_SHEEN at 0
    const float blood_sheen = max(hunter.x, look ? FOOTPRINTS_K_BLOOD_SHEEN : 0.0);
    if (blood_sheen > 0.0 && blood > max(wet, mud)) { // (r111j) the wet film's faint sky reflection on a blood print
        const float sheen_floor = PeakRoll(FOOTPRINTS_SHEEN_SKY * blood_sheen, FOOTPRINTS_SHEEN_PEAK);
'''),
        (r'''        lifted = lift > 0.0;
    }
''',
         r'''        lifted = lift > 0.0;
    }
    if (look && wet > max(mud, blood)) { // (r111k) a wet film on dark ground: a faint cool grey sky reflection, never red
        const float wet_lift = max(FOOTPRINTS_K_WET_SHEEN - dot(rgb, vec3(0.2126, 0.7152, 0.0722)), 0.0) * wet;
        rgb += vec3(FOOTPRINTS_K_WET_TINT_R, FOOTPRINTS_K_WET_TINT_G, FOOTPRINTS_K_WET_TINT_B) * wet_lift;
    }
'''),
    ],
    COMP: [
        (r'''    vec4 hunter;      // his position (x, y, z), 0
''',
         r'''    vec4 hunter;      // his position (x, y, z), (r111k) then the look (BB_FOOTPRINTS_LOOK: 1 on, 0 r111j's look)
'''),
        (r'''                    a.rgb *= 1.0 - FOOTPRINTS_WET_DARKEN * wet;
''',
         r'''                    // (r111k) the look (hunter.w): darker (K_WET_DARKEN), and a dull ground's gloss raised toward K_WET_GLOSS
                    // (never lowered; the specular colour stays as r111g left it, so no pale shape on a glossy floor)
                    const bool look = hunter.w > 0.5;
                    a.rgb *= 1.0 - (look ? FOOTPRINTS_K_WET_DARKEN : FOOTPRINTS_WET_DARKEN) * wet;
                    if (look) {
                        m.r = max(m.r, mix(m.r, FOOTPRINTS_K_WET_GLOSS, wet));
                    }
'''),
    ],
    RULES: [
        (r'''//                       r100k's roll-off); lit ground above that is not touched; wet and mud prints never (Sheen()).
''',
         r'''//                       r100k's roll-off); lit ground above that is not touched; wet and mud prints never (Sheen()).
//   BB_FOOTPRINTS_TRAIL (r111k) default on, "0" gives r111j's rules: a coat's trail is TrailFull prints at the whole strength, then a
//                       smoothstep taper to nothing over TrailWetPrints (wet) or TrailBloodPrints (blood) prints; blood is picked up from
//                       BloodEnterPercent of the pickup disc and held down to BloodStayPercent while the feet stand in it, a puddle held
//                       down to PuddleStayPercent; a blood coat's strength is the share over BloodFullShareTrail (the strongest share of
//                       the visit); a new print fades in over FadeInS (Trail(): live with the test tools' knobs).
//   BB_FOOTPRINTS_LOOK  (r111k) default on, "0" gives r111j's look: a wet print darker (K_WET_DARKEN, K_POST_WET_DARKEN), its dull ground's
//                       gloss raised to K_WET_GLOSS and, on near-black ground, a faint cool grey (K_WET_SHEEN); a blood print dark red
//                       with the blood sheen's floor always on (Look(): live with the test tools' knobs).
'''),
        (r'''    bool gain_bad = false;    ///< BB_FOOTPRINTS_GAIN held something but a number from GainMin to GainMax
};
''',
         r'''    bool gain_bad = false;    ///< BB_FOOTPRINTS_GAIN held something but a number from GainMin to GainMax
    bool trail = false;       ///< (r111k) BB_FOOTPRINTS_TRAIL: the trail rules (Read's own default is off: r111j's rules)
};
'''),
        (r'''} // namespace Detail

inline Knobs Read(const char* on_text, const char* coat_text, const char* gain_text = nullptr) {
    Knobs k;
''',
         r'''/// (r111k) `text` is not "0" (blanks around allowed): unset, empty, "1" or other text is on.
inline bool UnlessZero(const char* text) {
    return !Is(text, "0");
}
} // namespace Detail

/// `trail_text` (r111k) is BB_FOOTPRINTS_TRAIL's: "0" is r111j's rules, anything else (nullptr, empty too) the trail rules.
/// Its default "0" keeps r111j's rules for the callers that name no text (the rules' unit tests); Load() passes the
/// environment, where unset means on.
inline Knobs Read(const char* on_text, const char* coat_text, const char* gain_text = nullptr,
                  const char* trail_text = "0") {
    Knobs k;
    k.trail = Detail::UnlessZero(trail_text);
'''),
        (r'''    static const Knobs knobs = Read(std::getenv("BB_FOOTPRINTS"), std::getenv("BB_FOOTPRINTS_COAT"),
                                    std::getenv("BB_FOOTPRINTS_GAIN"));
''',
         r'''    static const Knobs knobs = Read(std::getenv("BB_FOOTPRINTS"), std::getenv("BB_FOOTPRINTS_COAT"),
                                    std::getenv("BB_FOOTPRINTS_GAIN"), std::getenv("BB_FOOTPRINTS_TRAIL"));
'''),
        (r'''    std::uint32_t full = 0; ///< prints that still leave the whole amount
    Source source = Source::None;
};
''',
         r'''    std::uint32_t full = 0; ///< prints that still leave the whole amount
    Source source = Source::None;
    std::uint32_t step_n = 0; ///< (r111k, trail rules) the prints of this trail so far; standing in a source resets it
};
'''),
        (r'''inline constexpr float BloodFullShare = 0.5f;
''',
         r'''inline constexpr float BloodFullShare = 0.5f;

// (r111k) The trail rules (BB_FOOTPRINTS_TRAIL, default on). A trail starts with TrailFull prints at the coat's whole
// strength and tapers by a smoothstep to nothing, so it neither starts nor stops with a step; blood is picked up from a
// lower share of the pickup disc and held (stay) while the feet are in it, a puddle held down to a lower share, and a new
// print fades in.
inline constexpr std::uint32_t TrailFull = 2;                            ///< prints at the coat's whole strength
inline constexpr std::uint32_t TrailWetPrints = 14, TrailBloodPrints = 16; ///< prints of a trail, the last about 1% of the coat
inline constexpr std::uint32_t BloodEnterPercent = 15; ///< blood is picked up from this share of the pickup disc (r111j: 25)
inline constexpr std::uint32_t BloodStayPercent = 8;   ///< and held while the feet stand in it down to this share
inline constexpr std::uint32_t PuddleStayPercent = 15; ///< a puddle is held down to this share of glossy ground pixels (enter: WetSharePercent)
inline constexpr float BloodFullShareTrail = 0.30f;    ///< a blood coat's strength: its share over this (r111j: 0.5)
inline constexpr float FadeInS = 0.30f;                ///< a new print fades in over this
inline constexpr float TailStrength = 0.25f;           ///< a print weaker than this counts as in the taper (a log counter)
static_assert(TrailFull >= 1u && TrailFull + 2u < TrailWetPrints && TrailWetPrints <= TrailBloodPrints &&
              TrailBloodPrints < MaxPrints);
static_assert(BloodStayPercent < BloodEnterPercent && BloodEnterPercent < BloodSharePercent &&
              PuddleStayPercent < WetSharePercent);
// The look's numbers (footprints_layout.h): a wet print darker than r111j's, in range, the cool tint of luminance 1.
static_assert(FOOTPRINTS_K_WET_DARKEN > FOOTPRINTS_WET_DARKEN && FOOTPRINTS_K_WET_DARKEN < 1.0 &&
              FOOTPRINTS_K_POST_WET_DARKEN > FOOTPRINTS_POST_WET_DARKEN && FOOTPRINTS_K_POST_WET_DARKEN < 1.0);
static_assert(FOOTPRINTS_K_WET_GLOSS > 0.0 && FOOTPRINTS_K_WET_GLOSS <= 1.0 && FOOTPRINTS_K_WET_SHEEN > 0.0 &&
              FOOTPRINTS_K_WET_SHEEN < FOOTPRINTS_SHEEN_SKY * FOOTPRINTS_K_BLOOD_SHEEN);
static_assert(0.2126 * FOOTPRINTS_K_WET_TINT_R + 0.7152 * FOOTPRINTS_K_WET_TINT_G + 0.0722 * FOOTPRINTS_K_WET_TINT_B > 0.99 &&
              0.2126 * FOOTPRINTS_K_WET_TINT_R + 0.7152 * FOOTPRINTS_K_WET_TINT_G + 0.0722 * FOOTPRINTS_K_WET_TINT_B < 1.01);
static_assert(FOOTPRINTS_K_BLOOD_SHEEN > 0.0 && FOOTPRINTS_K_BLOOD_SHEEN <= SheenMax);

/// The prints a coat leaves under the trail rules before the feet are dry: wet and mud, or blood.
inline constexpr std::uint32_t TrailPrints(Kind kind) {
    return kind == Kind::Blood ? TrailBloodPrints : TrailWetPrints;
}

/// The share of a coat's strength the `k`-th print (0 first) of a trail of `total` prints leaves: 1 for the first TrailFull,
/// then a smoothstep from just under 1 down to about 1% for the last one; 0 from `total` on.
inline constexpr float TrailProfile(std::uint32_t k, std::uint32_t total) {
    if (k >= total) {
        return 0.0f;
    }
    if (k < TrailFull) {
        return 1.0f;
    }
    const float u = float(total - k) / float(total - TrailFull + 1u);
    return u * u * (3.0f - 2.0f * u);
}

/// The pickup disc is in blood under the trail rules: `holding` (the feet already stand in blood) lowers the share needed.
inline bool InBloodTrail(std::uint32_t pick, std::uint32_t blood, bool holding) {
    return pick >= MinPickPixels &&
           std::uint64_t(blood) * 100u >= std::uint64_t(pick) * (holding ? BloodStayPercent : BloodEnterPercent);
}

/// A puddle already under the feet is held while this share of the ground band's pixels is still glossy.
inline bool GlossyGroundStay(std::uint32_t ground, std::uint32_t wet) {
    return ground >= MinGroundPixels && std::uint64_t(wet) * 100u >= std::uint64_t(ground) * PuddleStayPercent;
}

/// A blood coat's strength under the trail rules: its blood share over BloodFullShareTrail, 0 to 1.
inline float BloodAmountTrail(std::uint32_t pick, std::uint32_t blood) {
    if (pick == 0) {
        return 0.0f;
    }
    return std::clamp(float(blood) / float(pick) / BloodFullShareTrail, 0.0f, 1.0f);
}

/// The share of its strength a print shows `age` seconds after it was placed (trail rules): 0 at 0, 1 from FadeInS on.
inline float FadeIn(double age) {
    const float u = std::clamp(float(age) / FadeInS, 0.0f, 1.0f);
    return u * u * (3.0f - 2.0f * u);
}

/// BB_FOOTPRINTS_TRAIL and BB_FOOTPRINTS_LOOK: "0" (blanks allowed) is off, anything else (unset, empty) is on.
inline bool TrailOfText(const char* text) {
    return Detail::UnlessZero(text);
}
inline bool LookOfText(const char* text) {
    return Detail::UnlessZero(text);
}

/// The trail rules now: with the test tools' live knobs asked again every call, else the environment read once (Load().trail).
inline bool Trail() {
#if BB_FOOTPRINTS_LIVE
    static BbLiveKnobs::Knob<bool> knob{"BB_FOOTPRINTS_TRAIL", TrailOfText};
    return knob.Get();
#else
    return Load().trail;
#endif
}

/// The look now (live like the trail rules).
inline bool Look() {
#if BB_FOOTPRINTS_LIVE
    static BbLiveKnobs::Knob<bool> knob{"BB_FOOTPRINTS_LOOK", LookOfText};
    return knob.Get();
#else
    static const bool on = LookOfText(std::getenv("BB_FOOTPRINTS_LOOK"));
    return on;
#endif
}
'''),
        (r'''inline bool Soak(Coat& c, const Knobs& k, bool in_water, bool glossy, std::uint32_t pick = 0,
                 std::uint32_t blood = 0) {
    if (k.coat_forced) {
        c.kind = k.coat;
        c.amount = 1.0f;
        return false;
    }
    const Source now = in_water                  ? Source::Water
                       : InBlood(pick, blood)    ? Source::Blood
                       : glossy                  ? Source::Puddle
                                                 : Source::None;
    const bool picked = now != Source::None && now != c.source;
    c.source = now;
    if (now == Source::None) {
        return false;
    }
    c.kind = now == Source::Blood ? Kind::Blood : Kind::Wet;
    c.amount = now == Source::Blood ? BloodAmount(pick, blood) : 1.0f;
    c.full = RuleOf(c.kind).full;
    return picked;
}
''',
         r'''inline bool Soak(Coat& c, const Knobs& k, bool in_water, bool glossy, std::uint32_t pick = 0,
                 std::uint32_t blood = 0, bool glossy_stay = false) {
    if (k.coat_forced) {
        c.kind = k.coat;
        c.amount = 1.0f;
        return false;
    }
    // (r111k, trail rules) a source the feet already stand in is held by the lower stay shares, so one pool is one pickup and
    // not a flicker at its edge; `glossy_stay` is GlossyGroundStay of the same ground band as `glossy`.
    const Source before = c.source;
    const bool in_blood = k.trail ? InBloodTrail(pick, blood, before == Source::Blood) : InBlood(pick, blood);
    const bool on_puddle = glossy || (k.trail && before == Source::Puddle && glossy_stay);
    const Source now = in_water                  ? Source::Water
                       : in_blood                ? Source::Blood
                       : on_puddle               ? Source::Puddle
                                                 : Source::None;
    const bool picked = now != Source::None && now != c.source;
    c.source = now;
    if (now == Source::None) {
        return false;
    }
    c.kind = now == Source::Blood ? Kind::Blood : Kind::Wet;
    const float amount = now == Source::Blood ? (k.trail ? BloodAmountTrail(pick, blood) : BloodAmount(pick, blood)) : 1.0f;
    // (trail rules) the strongest share of one visit to a pool is kept: a frame at its edge does not lower the coat
    c.amount = (k.trail && now == before && now == Source::Blood) ? std::max(c.amount, amount) : amount;
    c.full = RuleOf(c.kind).full;
    c.step_n = 0;
    return picked;
}
'''),
        (r'''    if (c.amount < MinCoat) {
        c.amount = 0.0f;
        return 0.0f;
    }
    kind = c.kind;
    const float strength = c.amount;
''',
         r'''    if (c.amount < MinCoat) {
        c.amount = 0.0f;
        return 0.0f;
    }
    kind = c.kind;
    if (k.trail) { // (r111k) TrailFull prints at the whole amount, then a smooth taper to dry after TrailPrints(kind)
        const std::uint32_t total = TrailPrints(c.kind);
        const float taper = c.amount * TrailProfile(c.step_n, total);
        ++c.step_n;
        if (c.step_n >= total) {
            c.amount = 0.0f;
        }
        return taper;
    }
    const float strength = c.amount;
'''),
    ],
    VKH: [
        (r'''    void LogSheen() const;
''',
         r'''    void LogSheen() const;
    void LogTrail() const; // (r111k)
'''),
        (r'''        u64 sheen_px = 0; ///< (r111j) over the read-backs, the blood pixels the sheen lifted
''',
         r'''        u64 sheen_px = 0; ///< (r111j) over the read-backs, the blood pixels the sheen lifted
        u32 trail_prints = 0, tail_prints = 0, trail_holds = 0; ///< (r111k) prints by the trail rules, in the taper; frames held
'''),
    ],
    VKC: [
        (r'''    if (!camera_motion.Enabled()) {
        Fail("it needs the upscaler's camera (BB_UPSCALER=none)");
    }
}
''',
         r'''    BbReport::Printf("Footprints (r111k): trail %u (BB_FOOTPRINTS_TRAIL, 0 = r111j's rules): %u full prints, then a taper "
                     "to dry over %u (blood) or %u (wet); blood from %u%% of the pickup disc, held to %u%%, a puddle held "
                     "to %u%%; blood strength = share over %.2f; a print fades in over %.2f s\n",
                     R::Trail() ? 1u : 0u, R::TrailFull, R::TrailBloodPrints, R::TrailWetPrints, R::BloodEnterPercent,
                     R::BloodStayPercent, R::PuddleStayPercent, double(R::BloodFullShareTrail), double(R::FadeInS));
    BbReport::Printf("Footprints (r111k): look %u (BB_FOOTPRINTS_LOOK, 0 = r111j's): wet darkens %.0f%% (G-buffer) and "
                     "%.0f%% (post), was %.0f%% and %.0f%%; gloss to %.2f; cool grey floor %.3f; blood keeps its dark red, "
                     "sheen floor %.2f times %.3f\n",
                     R::Look() ? 1u : 0u, double(FOOTPRINTS_K_WET_DARKEN) * 100.0, double(FOOTPRINTS_K_POST_WET_DARKEN) * 100.0,
                     double(FOOTPRINTS_WET_DARKEN) * 100.0, double(FOOTPRINTS_POST_WET_DARKEN) * 100.0,
                     double(FOOTPRINTS_K_WET_GLOSS), double(FOOTPRINTS_K_WET_SHEEN), double(FOOTPRINTS_K_BLOOD_SHEEN),
                     double(FOOTPRINTS_SHEEN_SKY));
    if (!camera_motion.Enabled()) {
        Fail("it needs the upscaler's camera (BB_UPSCALER=none)");
    }
}
'''),
        (r'''        LogSheen();                                // (r111j) a zero copy
''',
         r'''        LogSheen();                                // (r111j) a zero copy
        LogTrail();                                // (r111k) a zero copy
'''),
        (r'''/// (r111j) A stamp pass's read-back as a view: told when it differs from the last line told, and every ViewEvery passes.
''',
         r'''/// (r111k) Numbers first: the prints placed by the trail rules, how many of them in the taper (under TailStrength of a coat),
/// the frames a pickup was held by the lower stay share, and where the coat stands in its trail. Told at construction (zeros),
/// and with the periodic lines.
void Footprints::LogTrail() const {
    BbReport::Printf("Footprints (r111k): trail %u look %u: %u prints placed by the trail rules, %u of them in the taper "
                     "(under %.2f of a coat), %u frames a pickup was held by the lower stay share; the coat is %u prints "
                     "into a trail of %u\n",
                     R::Trail() ? 1u : 0u, R::Look() ? 1u : 0u, stats.trail_prints, stats.tail_prints,
                     double(R::TailStrength), stats.trail_holds, coat.step_n, R::TrailPrints(coat.kind));
}

/// (r111j) A stamp pass's read-back as a view: told when it differs from the last line told, and every ViewEvery passes.
'''),
        (r'''    push.hunter = {hunter[0], hunter[1], hunter[2], 0.0f};
''',
         r'''    push.hunter = {hunter[0], hunter[1], hunter[2], R::Look() ? 1.0f : 0.0f}; // (r111k) .w: the look
'''),
        (r'''    push.hunter = {R::Sheen(), 0.0f, 0.0f, 0.0f}; // (r111j) the flat shader reads BB_FOOTPRINTS_SHEEN here
''',
         r'''    push.hunter = {R::Sheen(), R::Look() ? 1.0f : 0.0f, 0.0f, 0.0f}; // (r111j) .x: BB_FOOTPRINTS_SHEEN; (r111k) .y: the look
'''),
        (r'''    const auto& k = R::Load();
    const double now =
''',
         r'''    R::Knobs k = R::Load();
    k.trail = R::Trail(); // (r111k) the trail rules, live with the test tools' knobs
    const double now =
'''),
        (r'''    const bool glossy = fresh && R::GlossyGround(c[R::WordGroundN], c[R::WordWetN]);
''',
         r'''    const bool glossy = fresh && R::GlossyGround(c[R::WordGroundN], c[R::WordWetN]);
    const bool glossy_stay = fresh && R::GlossyGroundStay(c[R::WordGroundN], c[R::WordWetN]); // (r111k)
'''),
        (r'''        if ((fresh || in_water || k.coat_forced) && R::Soak(coat, k, in_water, glossy, pick_px, blood_px)) {
''',
         r'''        if ((fresh || in_water || k.coat_forced) &&
            R::Soak(coat, k, in_water, glossy, pick_px, blood_px, glossy_stay)) {
'''),
        (r'''        const R::Step s = R::Walk(walker, pos);
''',
         r'''        if (k.trail && fresh) { // (r111k) frames a source is held by the lower stay share and not by the pickup rule
            stats.trail_holds += ((coat.source == R::Source::Blood && !R::InBloodTrail(pick_px, blood_px, false)) ||
                                  (coat.source == R::Source::Puddle && !glossy))
                                     ? 1u
                                     : 0u;
        }
        const R::Step s = R::Walk(walker, pos);
'''),
        (r'''            if (strength > 0.0f) {
                Place(s, kind, strength, now);
            } else {
''',
         r'''            if (strength > 0.0f) {
                Place(s, kind, strength, now);
                stats.trail_prints += k.trail ? 1u : 0u; // (r111k)
                stats.tail_prints += (k.trail && strength < R::TailStrength) ? 1u : 0u;
            } else {
'''),
        (r'''        Placed p = placed[i];
        p.now = p.strength * R::Fade(now - p.born);
        if (p.now > 1.0f / 64.0f) {
''',
         r'''        Placed p = placed[i];
        const double age = now - p.born;
        p.now = p.strength * R::Fade(age) * (k.trail ? R::FadeIn(age) : 1.0f); // (r111k) a new print fades in
        if (p.now > 1.0f / 64.0f || (k.trail && age < double(R::FadeInS))) {
'''),
        (r'''    LogFlat(); // (r111f) the line of r111e, in numbers only, with the read-back count
    flat = {};
''',
         r'''    LogFlat(); // (r111f) the line of r111e, in numbers only, with the read-back count
    LogTrail(); // (r111k)
    flat = {};
'''),
    ],
    TEST: [
        (r'''    // Screen boxes: a camera at the origin looking along +z (view = identity), 90 degrees.
''',
         r'''    // (r111k) The trail rules: a soft start and end, a held pickup, a print that fades in; the knobs.
    {
        // BB_FOOTPRINTS_TRAIL: "0" is r111j's rules, unset, empty, "1" or other text the trail rules; Read(on, coat) alone is r111j's.
        assert(!Read("1", nullptr).trail && !Read("1", nullptr, nullptr, "0").trail && !Read("1", nullptr, nullptr, " 0 ").trail);
        assert(Read("1", nullptr, nullptr, nullptr).trail && Read("1", nullptr, nullptr, "").trail &&
               Read("1", nullptr, nullptr, "1").trail && Read("1", nullptr, nullptr, "x").trail);
        assert(TrailOfText(nullptr) && TrailOfText("1") && !TrailOfText("0") && !TrailOfText(" 0 ") && TrailOfText("00"));
        assert(LookOfText(nullptr) && LookOfText("") && !LookOfText("0") && LookOfText("1"));
        const Knobs on = Read("1", nullptr, nullptr, nullptr);
        const Knobs old = Read("1", nullptr);
        // The profile: the first TrailFull prints whole, then a smooth taper to a hair; nothing from `total` on.
        assert(TrailPrints(Kind::Wet) == 14u && TrailPrints(Kind::Blood) == 16u && TrailPrints(Kind::Mud) == 14u);
        for (const std::uint32_t total : {TrailWetPrints, TrailBloodPrints}) {
            assert(TrailProfile(0, total) == 1.0f && TrailProfile(1, total) == 1.0f && TrailProfile(total, total) == 0.0f);
            assert(TrailProfile(TrailFull, total) > 0.97f); // no step after the whole prints
            float prev = 1.0f;
            for (std::uint32_t i = 0; i < total; ++i) {
                const float s = TrailProfile(i, total);
                assert(s <= prev && s > 0.0f);
                prev = s;
            }
            assert(prev < 0.02f); // the last print is about 1% of the coat
        }
        // A wet trail after the water: 14 prints, each no stronger than the one before, then dry.
        {
            Coat c;
            Kind kind = Kind::Blood;
            Soak(c, on, true, false);
            assert(c.kind == Kind::Wet && c.amount == 1.0f && c.step_n == 0u);
            int prints = 0;
            float before = 2.0f;
            for (int i = 0; i < 40; ++i) {
                const float s = TakeStep(c, on, false, kind);
                if (s == 0.0f) {
                    break;
                }
                assert(kind == Kind::Wet && s <= before && Near(s, TrailProfile(std::uint32_t(i), TrailWetPrints)));
                before = s;
                ++prints;
            }
            assert(prints == int(TrailWetPrints) && c.amount == 0.0f && TakeStep(c, on, false, kind) == 0.0f);
            // Standing in a source starts the trail over.
            Soak(c, on, true, false);
            TakeStep(c, on, false, kind);
            TakeStep(c, on, false, kind);
            assert(c.step_n == 2u);
            Soak(c, on, true, false);
            assert(c.step_n == 0u && c.amount == 1.0f);
        }
        // Blood: the share to step in, the share to stay, the coat's strength.
        assert(InBloodTrail(100, BloodEnterPercent, false) && !InBloodTrail(100, BloodEnterPercent - 1u, false));
        assert(InBloodTrail(100, BloodStayPercent, true) && !InBloodTrail(100, BloodStayPercent - 1u, true));
        assert(!InBloodTrail(MinPickPixels - 1u, MinPickPixels - 1u, true) && !InBloodTrail(0, 0, true));
        assert(Near(BloodAmountTrail(100, 30), 1.0) && Near(BloodAmountTrail(100, 15), 0.5) && BloodAmountTrail(0, 0) == 0.0f);
        assert(GlossyGroundStay(100, PuddleStayPercent) && !GlossyGroundStay(100, PuddleStayPercent - 1u));
        assert(!GlossyGroundStay(MinGroundPixels - 1u, MinGroundPixels - 1u));
        {
            Coat b;
            assert(!Soak(b, on, false, false, 100, 14) && b.source == Source::None); // 14%: not enough to step into it
            assert(Soak(b, on, false, false, 100, 20) && b.kind == Kind::Blood && b.source == Source::Blood);
            assert(Near(b.amount, 0.2 / 0.3));
            // 9% of the disc: held by the stay share (no new pickup), and the strongest share of the visit is kept
            assert(!Soak(b, on, false, false, 100, 9) && b.source == Source::Blood && Near(b.amount, 0.2 / 0.3));
            assert(!Soak(b, on, false, false, 100, 5) && b.source == Source::None && b.amount > 0.6f); // left: coat kept
            // r111j's rules: 20% is not blood and nothing is held
            Coat o;
            assert(!Soak(o, old, false, false, 100, 20) && o.source == Source::None);
            assert(Soak(o, old, false, false, 100, 60) && !Soak(o, old, false, false, 100, 9) && o.source == Source::None);
            // A puddle: held while the stay rule holds, only with the trail rules.
            Coat p;
            assert(Soak(p, on, false, true, 100, 0, true) && p.source == Source::Puddle);
            assert(!Soak(p, on, false, false, 0, 0, true) && p.source == Source::Puddle);
            assert(!Soak(p, on, false, false, 0, 0, false) && p.source == Source::None);
            Coat q;
            assert(Soak(q, old, false, true, 0, 0, true) && !Soak(q, old, false, false, 0, 0, true) && q.source == Source::None);
        }
        // A new print fades in: 0 at birth, half at half the time, whole from FadeInS on; never negative or above 1.
        assert(FadeIn(0.0) == 0.0f && Near(FadeIn(double(FadeInS) / 2.0), 0.5) && FadeIn(double(FadeInS)) == 1.0f);
        assert(FadeIn(5.0) == 1.0f && FadeIn(-1.0) == 0.0f);
    }
    // Screen boxes: a camera at the origin looking along +z (view = identity), 90 degrees.
'''),
    ],
    README: [
        (r'''the counter buffer is 172 bytes | `0` |
''',
         r'''the counter buffer is 172 bytes | `0` |
| `BB_FOOTPRINTS_TRAIL` | Only with `BB_FOOTPRINTS` on (r111k). `0`: r111j's rules (the numbers of the paragraph above). Unset, empty or anything else: on. The trail rules: a coat's trail is its first 2 prints at the whole strength and then a smoothstep taper to nothing over 14 prints (wet) or 16 (blood), the last print about 1% of the coat, under the shader's 1/64 limit in all but a hair, so a trail ends in nothing instead of stopping at a visible print; blood is picked up from 15% of the pickup disc (was 25%: the graveyard pool's own albedo, 0.031 0.015 0.014, is blood by the rule over only about 30% of it, so the pickup flickered at the pool's edge and left a coat of half strength) and held while the feet stand in it down to 8%, a puddle is picked up as before (30% of the ground band glossy) and held down to 15%, a blood coat's strength is its share over 30% (was 50%) and the strongest share of one visit is kept, standing in a source starts the trail over; and a new print fades in over 0.30 s (smoothstep) before it fades out over 30 s. Cost: a few multiplies a frame on the CPU, nothing on the GPU. In a build with the test tools' live knobs (`BB_LIVE_KNOBS_FILE`) it is asked again every frame | on |
| `BB_FOOTPRINTS_LOOK` | Only with `BB_FOOTPRINTS` on (r111k). `0`: r111j's look. Unset, empty or anything else: on. Water and blood are told apart: a wet print darkens the lit pixel 65% in the post stamp (was 55%) and the albedo 70% in the G-buffer (was 65%), raises a dull ground's gloss toward 0.85 in the G-buffer (never lowers it; the specular colour is not touched, as r111g left it, so a glossy floor shows no pale shape) and, on near-black ground where a darkening cannot show, is lifted to a faint cool grey (luminance floor 0.007, hue 0.88 1.02 1.11, by the print's weight; lit ground above the floor is not touched); a blood print keeps its dark red (the stone's own red at 0.25 of its luminance) and has r111j's blood sheen floor always on (as `BB_FOOTPRINTS_SHEEN=1`, 0.012 in the red tint; a larger `BB_FOOTPRINTS_SHEEN` still wins), so on near-black stone a blood print is a faint red sole and a wet one a fainter grey-blue sole: dark, cool and glossy against dark red. The knob travels in the push words `hunter.w` (G-buffer pass) and `hunter.y` (post stamp). Cost: a few ALU operations on the pixels a print stamps and one gloss write on wet G-buffer pixels; no memory. In a build with the test tools' live knobs (`BB_LIVE_KNOBS_FILE`) it is asked again every frame, so one running game can show the same view with and without it | on |
'''),
        (r'''and every 600 frames the blood pixels the sheen lifted.''',
         r'''and every 600 frames the blood pixels the sheen lifted. Lines of r111k: once at the start the trail rules' numbers and the look's numbers, and one `Footprints (r111k): trail T look L: ...` line at the start (zeros) and every 600 frames: the prints placed by the trail rules, how many of them in the taper (under 0.25 of a coat), the frames a pickup was held by the lower stay share (a pool or a puddle kept by the stay rule and not by the pickup rule: 0 means the stay rule never did anything), and how many prints into its trail the coat is. With `BB_FOOTPRINTS_TRAIL` on (the default) the coat numbers of the paragraph above (3 full prints then 0.75 for wet, 1 then 0.8 for blood, 25% of the pickup disc, strength over 50%, a wet print darkening 65% and 55%) are replaced by the rules of the `BB_FOOTPRINTS_TRAIL` and `BB_FOOTPRINTS_LOOK` rows.'''),
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
                             "and 1; is r111j applied, and is this patch's own earlier version reverted?): %r" %
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


def cdef(rules, name):
    """A `inline constexpr <type> Name = value;` of footprints.h (first number after `Name =`)."""
    m = re.search(r"\b%s\s*=\s*([0-9.]+)f?;" % name, rules)
    if not m:
        raise SystemExit("text check: footprints.h lacks %s" % name)
    return float(m.group(1))


def text_checks(texts):
    """Ties a compiler cannot check, on the full result."""
    cpp = texts[VKC]
    n_new = 0
    for m in re.finditer(r'BbReport::Printf\(((?:\s*"(?:[^"\\]|\\.)*")+)(.*?)\);\n', cpp, re.S):
        fmt = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))).replace("\\n", "")
        if not fmt.startswith("Footprints (r111"):
            raise SystemExit("text check: a log line without its prefix: %r" % fmt[:60])
        if not fmt.startswith("Footprints (r111k)"):
            continue
        n_new += 1
        convs = re.findall(r"%(?!%)[-+ 0-9.]*(?:ll)?[udfs]", fmt.replace("%%", ""))
        args = split_args(m.group(2).lstrip().lstrip(",")) if m.group(2).strip() else []
        if len(convs) != len(args):
            raise SystemExit("text check: %d conversions, %d arguments: %r" % (len(convs), len(args), fmt[:70]))
        if "%s" in fmt:
            raise SystemExit("text check: a %%s in an r111k line (kinds fold on digits only): %r" % fmt[:60])
        for conv, arg in zip(convs, args):  # the type of each argument against its conversion
            if conv.endswith("u") and not (arg.endswith("1u : 0u") or arg.startswith("stats.") or arg.startswith("R::")
                                           or arg.startswith("coat.")):
                raise SystemExit("text check: %%u argument of an unexpected shape: %r" % arg)
            if conv.endswith("f") and not arg.startswith("double("):
                raise SystemExit("text check: %%f argument not a double(...): %r" % arg)
        wide = re.sub(r"%[-+]?[0-9]*\.[0-9]+f", "X" * 6, fmt)  # (a realistic width: the runner keeps 300 characters)
        wide = re.sub(r"%(?:ll)?[ud]", "X" * 4, wide)
        wide = wide.replace("%%", "%")
        print("  r111k log line (wide %d, %d conversions): %s..." % (len(wide), len(convs), fmt[:50]))
        if len(wide) > 300:
            raise SystemExit("text check: a log line may pass 300 characters (%d): %r" % (len(wide), fmt[:60]))
    if n_new != 3:
        raise SystemExit("text check: %d r111k log lines (3 expected)" % n_new)
    if cpp.count("LogTrail();") != 2 or cpp.count("void Footprints::LogTrail() const {") != 1:
        raise SystemExit("text check: LogTrail must be defined once and called twice")
    if cpp.count("R::Look() ? 1.0f : 0.0f") != 2:  # the two pushes
        raise SystemExit("text check: the look flag must reach both pushes and the log line")
    lay = texts[LAYOUT]
    rules = texts[RULES]
    wet_d, post_d = define(lay, "FOOTPRINTS_K_WET_DARKEN"), define(lay, "FOOTPRINTS_K_POST_WET_DARKEN")
    gloss, wsheen = define(lay, "FOOTPRINTS_K_WET_GLOSS"), define(lay, "FOOTPRINTS_K_WET_SHEEN")
    tint = [define(lay, "FOOTPRINTS_K_WET_TINT_" + c) for c in "RGB"]
    lum = 0.2126 * tint[0] + 0.7152 * tint[1] + 0.0722 * tint[2]
    sky = define(lay, "FOOTPRINTS_SHEEN_SKY")
    if not (define(lay, "FOOTPRINTS_WET_DARKEN") < wet_d < 1.0 and define(lay, "FOOTPRINTS_POST_WET_DARKEN") < post_d < 1.0):
        raise SystemExit("text check: the look's darkening is not above r111j's or not under 1")
    if not (0.99 < lum < 1.01 and 0.0 < wsheen < sky and 0.0 < gloss <= 1.0 and tint[2] > tint[0]):
        raise SystemExit("text check: the wet tint is not a cool colour of luminance 1 under the blood floor (lum %.4f)" % lum)
    full, wet_n, blood_n = cdef(rules, "TrailFull"), 14.0, 16.0
    if not re.search(r"TrailWetPrints = 14, TrailBloodPrints = 16;", rules):
        raise SystemExit("text check: the trail lengths changed (the unit test and README say 14 and 16)")

    def prof(k, total):
        if k >= total:
            return 0.0
        if k < full:
            return 1.0
        u = (total - k) / (total - full + 1.0)
        return u * u * (3.0 - 2.0 * u)

    for total in (int(wet_n), int(blood_n)):
        vals = [prof(i, total) for i in range(total)]
        if not (all(a >= b for a, b in zip(vals, vals[1:])) and vals[-1] < 0.02 and vals[int(full)] > 0.97):
            raise SystemExit("text check: the taper is not a smooth decline (total %d)" % total)
    print("  taper wet: %s ... last %.4f; blood last %.4f; wet tint luminance %.4f, floor %.4f (blood floor %.4f)" %
          (" ".join("%.2f" % prof(i, 14) for i in range(14)), prof(13, 14), prof(15, 16), lum, wsheen, sky))
    enter, stay, puddle = cdef(rules, "BloodEnterPercent"), cdef(rules, "BloodStayPercent"), cdef(rules, "PuddleStayPercent")
    if not (stay < enter < cdef(rules, "BloodSharePercent") and puddle < cdef(rules, "WetSharePercent")):
        raise SystemExit("text check: the stay rules are not below the enter rules")
    flat, comp = texts[FLAT], texts[COMP]
    for needle in ("hunter.y > 0.5", "FOOTPRINTS_K_POST_WET_DARKEN", "FOOTPRINTS_K_BLOOD_SHEEN", "FOOTPRINTS_K_WET_SHEEN",
                   "blood_sheen > 0.0 && blood > max(wet, mud)", "look && wet > max(mud, blood)"):
        if needle not in flat:
            raise SystemExit("text check: footprints_flat.comp lacks %r" % needle)
    for needle in ("hunter.w > 0.5", "FOOTPRINTS_K_WET_DARKEN", "FOOTPRINTS_K_WET_GLOSS"):
        if needle not in comp:
            raise SystemExit("text check: footprints.comp lacks %r" % needle)
    if flat.count("atomicAdd(counts[FOOTPRINTS_FLAT_WORD_SHEEN], 1u);") != 1:
        raise SystemExit("text check: the sheen counter must still be added once")
    if comp.count("m.r = max(m.r, mix(m.r, FOOTPRINTS_K_WET_GLOSS, wet));") != 1:
        raise SystemExit("text check: the wet gloss is lifted once and never lowered (max)")
    for needle in ("void LogTrail() const;", "u32 trail_prints = 0, tail_prints = 0, trail_holds = 0;"):
        if needle not in texts[VKH]:
            raise SystemExit("text check: vk_footprints.h lacks %r" % needle)
    for needle in ("R::Knobs k = R::Load();", "k.trail = R::Trail();", "R::Soak(coat, k, in_water, glossy, pick_px, blood_px, glossy_stay)",
                   "R::FadeIn(age)", "(k.trail && age < double(R::FadeInS))"):
        if needle not in cpp:
            raise SystemExit("text check: vk_footprints.cpp lacks %r" % needle)
    # nothing of the rules may run with the trail knob off: every new branch tests k.trail
    for needle in ("k.trail ? InBloodTrail(", "(k.trail && now == before && now == Source::Blood)", "if (k.trail) {"):
        if needle not in rules:
            raise SystemExit("text check: footprints.h lacks the guard %r" % needle)
    for needle in ("| `BB_FOOTPRINTS_TRAIL` |", "| `BB_FOOTPRINTS_LOOK` |", "Lines of r111k:"):
        if texts[README].count(needle) != 1:
            raise SystemExit("text check: README lacks %r once" % needle)
    if "TrailProfile(TrailFull, total) > 0.97f" not in texts[TEST]:
        raise SystemExit("text check: the unit test lacks the taper asserts")
    for path, eds in EDITS.items():
        for old, new in eds:
            if "\t" in new or "\r" in new:
                raise SystemExit("text check: an edit of %s has a tab or a CR" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 r111k_prints-water-blood-fade.py check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R111K_ROOT)" % ROOT)
    if "(r111j) BloodSheenRules::PeakRoll's arithmetic" not in load(FLAT)[2]:
        raise SystemExit("REFUSED: r111j is not applied (%s lacks its sheen code)" % FLAT)
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
            tmp = full + ".r111ktmp"
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
        tmp = full + ".r111ktmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted (%d files edited back)" % len(plan))


main()
