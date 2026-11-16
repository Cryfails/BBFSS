// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r111_footprints): prints the hunter's feet leave on the ground after he stepped in water
// (wet), and with a test knob mud or blood; each fades out over LifeS (30 s, r111d; was 20 s).
//
// Where and when a foot lands: the renderer does not see the game's animation, so the steps are
// made from the hunter's path. Once a frame (Footprints::OnFrameEnd) the engine reads his position
// from the game (BbEngine::world_player_position: the physics position, y up); each time he has
// gone StrideM (0.75 m) across since the last print (Walk), a print is placed at his position,
// GaitHalfM (0.11 m) to the left or right of his path in turn, pointing along it. A move of more
// than JumpM (2 m) across or DropM (1 m) up or down in one frame (a warp, a load, a fall) starts the
// path anew and places nothing. The print's height is his position's: one placed in the air draws
// nothing (the shader takes only ground within FOOTPRINTS_PRINT_BAND_M of it).
// NOT KNOWN YET (the first slot run decides it): that the game's physics position and the
// renderer's world (the scene camera's matrices) are the same space; the test view's ring and the
// log's "hunter ... camera ... m away, ... m above the feet" say it.
//
// What the feet carry (the coat): wet, at full, while the hunter's position lies more than
// WaterDepthM under the water plane of a frame the game draws with a planar water reflection
// (CameraMotion::MirrorPlane: the sewers), or while the ground around his feet is glossy (the sense
// of the shader, read back a few frames late: at least MinGroundPixels ground pixels within
// FOOTPRINTS_GROUND_M of his height, WetSharePercent of them with a gloss of at least
// FOOTPRINTS_PUDDLE_GLOSS: a puddle). In water no print is placed (it would lie under the opaque
// water). Each print takes the coat's amount as its strength; a wet coat then keeps DryPerStep of it
// each step; below MinCoat the feet are dry and place nothing. BB_FOOTPRINTS_COAT (a TEST) gives the
// feet a coat that never dries.
// Pickup (r111b; the owner: "the grave yard doesn't have a bloody coat just blood on the ground"):
// the coat comes from the ground under the feet. Blood: of the up-facing ground pixels within
// FOOTPRINTS_PICK_RADIUS_M of his position and FOOTPRINTS_GROUND_M of his height (the pass counts
// them before any print is laid), at least MinPickPixels and BloodSharePercent of them are blood by
// the dark red albedo rule of blood_albedo.h (linear red 0.01 to 0.12, at least 2.5 times green and
// 2.5 times blue); the coat is then blood at BloodAmount (the share over BloodFullShare, at most 1).
// A blood coat leaves BloodFullPrints prints at its strength, then keeps BloodKeep of it each step:
// a full coat gives 3 full prints, then 0.7, 0.49 ... and is dry after 10 (7 of them fading). Water,
// (r111h: BloodFullPrints is 1 and BloodKeep 0.8: the first print of a trail is the strongest and it fades from
// there, 1, 0.8, 0.64, 0.51 ... dry after 13 as before.)
// (r111d: BloodFullPrints is 4 and BloodKeep 0.75: 4 full prints, then 0.75, 0.56 ... dry after 13, the
// last 9 fading; a wet coat leaves WetFullPrints (3) full prints, then keeps DryPerStep (0.75): 12 prints.)
// blood and puddle are tried in that order and the newest pickup wins (a new source replaces the
// coat's kind and strength). Mud has no fair rule in the G-buffer (README): only the test coat makes
// mud prints.
//
// Knobs (environment, read once):
//   BB_FOOTPRINTS       1: on; show: on with the test view (every step places a print at full
//                       strength, wet unless BB_FOOTPRINTS_COAT names a kind, painted in its kind's
//                       colour: cyan wet, orange mud, red blood; a magenta ring of 0.30-0.34 m around
//                       the hunter's position; the ground band around his feet tinted yellow).
//                       Unset, empty, 0 or other text: off, nothing of it is made.
//   BB_FOOTPRINTS_COAT  wet, mud or blood: a TEST, the feet carry that coat from the start and it
//                       never dries; unset or empty: the coat comes from the game as above; other
//                       text: as unset (said in the log).
//   BB_FOOTPRINTS_GAIN  (r111c, r111d) a number from 0 to 4, default 1: a factor on every print's weight (its
//                       strength x shape x facing; 0 draws no print); other text: 1 (said in the log). With
//                       the test tools' live knobs a running game asks again every pass (Gain()).
//   BB_FOOTPRINTS_SHOW  (r111e) 1: a test view over the finished picture: each live print a flat saturated red
//                       rectangle on its ground plane, no depth, no light (ShowFlat(); live like the gain).
//   BB_FOOTPRINTS_POST  (r111e) a number from 0 to 2, default 1: the post stamp's strength, a pass on the
//                       scene colour after the lighting (blood recoloured dark red at the lit pixel's
//                       luminance, wet and mud darkened a further 40%, r111g); 0: the G-buffer change alone (Post()).
//   BB_FOOTPRINTS_SHEEN (r111j) a number from 0 to 4, default 0 (off): a faint wet sheen on BLOOD prints so they read on
//                       near-black ground: their luminance is lifted to at least 0.012 x the number (ceiling 0.03,
//                       r100k's roll-off); lit ground above that is not touched; wet and mud prints never (Sheen()).
//   BB_FOOTPRINTS_TRAIL (r111k) default on, "0" gives r111j's rules: a coat's trail is TrailFull prints at the whole strength, then a
//                       smoothstep taper to nothing over TrailWetPrints (wet) or TrailBloodPrints (blood) prints; blood is picked up from
//                       BloodEnterPercent of the pickup disc and held down to BloodStayPercent while the feet stand in it, a puddle held
//                       down to PuddleStayPercent; a blood coat's strength is the share over BloodFullShareTrail (the strongest share of
//                       the visit); a new print fades in over FadeInS (Trail(): live with the test tools' knobs).
//   BB_FOOTPRINTS_LOOK  (r111k) default on, "0" gives r111j's look: a wet print darker (K_WET_DARKEN, K_POST_WET_DARKEN), its dull ground's
//                       gloss raised to K_WET_GLOSS and, on near-black ground, a faint cool grey (K_WET_SHEEN); a blood print dark red
//                       with the blood sheen's floor always on (Look(): live with the test tools' knobs).
// Look (r111d): a blood print's red is 0.6 times the stone's own red (0.03 to 0.085), green 0.006, blue
// 0.005, cover 95%, gloss 0.78; a wet print darkens the albedo by up to 65% (r111g: no gloss or specular added); the sole is a
// boot's (heel, waist, ball), 0.28 x 0.11 m, on ground within 0.16 m of the print's height.
// No Vulkan here: tests/test_footprints.cpp builds it alone.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>

#include "../host_shaders/footprints_layout.h"
#include "blood_albedo.h"
// (r111d) The test tools' live knobs (branch dev/test-tools): with that header the gain is asked again every
// pass; without it (a feature branch) it is read once, as before.
#if __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h" // test tools (r84_live-test-knobs) only
#define BB_FOOTPRINTS_LIVE 1
#else
#define BB_FOOTPRINTS_LIVE 0
#endif

namespace Vulkan::FootprintRules {

inline constexpr std::uint32_t Group = FOOTPRINTS_GROUP;
inline constexpr std::uint32_t MaxPrints = FOOTPRINTS_MAX_PRINTS;
inline constexpr std::uint32_t SlotWords = FOOTPRINTS_SLOT_WORDS, Slots = 2;
inline constexpr std::uint32_t FlagShow = FOOTPRINTS_FLAG_SHOW, FlagSlot = FOOTPRINTS_FLAG_SLOT;
inline constexpr std::uint32_t FlagHunter = FOOTPRINTS_FLAG_HUNTER, FlagSrgb = FOOTPRINTS_FLAG_SRGB;
static_assert(Group == 8u && MaxPrints == 48u && SlotWords == 18u);
static_assert((FlagShow | FlagSlot | FlagHunter | FlagSrgb) == 15u);
inline constexpr std::uint32_t WordPrintPx = FOOTPRINTS_WORD_PRINT_PX;
inline constexpr std::uint32_t WordSeenPx = FOOTPRINTS_WORD_SEEN_PX;
inline constexpr std::uint32_t WordSenseN = FOOTPRINTS_WORD_SENSE_N;
inline constexpr std::uint32_t WordSenseDyMm = FOOTPRINTS_WORD_SENSE_DY_MM;
inline constexpr std::uint32_t WordBinLow = FOOTPRINTS_WORD_BIN_LOW;
inline constexpr std::uint32_t WordBinBelow = FOOTPRINTS_WORD_BIN_BELOW;
inline constexpr std::uint32_t WordGroundN = FOOTPRINTS_WORD_GROUND_N;
inline constexpr std::uint32_t WordBinAbove = FOOTPRINTS_WORD_BIN_ABOVE;
inline constexpr std::uint32_t WordBinHigh = FOOTPRINTS_WORD_BIN_HIGH;
inline constexpr std::uint32_t WordGlossSum = FOOTPRINTS_WORD_GLOSS_SUM;
inline constexpr std::uint32_t WordWetN = FOOTPRINTS_WORD_WET_N;
inline constexpr std::uint32_t WordAlbedoR = FOOTPRINTS_WORD_ALBEDO_R;
inline constexpr std::uint32_t WordAlbedoG = FOOTPRINTS_WORD_ALBEDO_G;
inline constexpr std::uint32_t WordAlbedoB = FOOTPRINTS_WORD_ALBEDO_B;
inline constexpr std::uint32_t WordStamp = FOOTPRINTS_WORD_STAMP;
inline constexpr std::uint32_t WordRingPx = FOOTPRINTS_WORD_RING_PX;
inline constexpr std::uint32_t WordPickN = FOOTPRINTS_WORD_PICK_N;
inline constexpr std::uint32_t WordBloodN = FOOTPRINTS_WORD_BLOOD_N;
// (r111e, r111f) the draw over the picture: its counter words
inline constexpr std::uint32_t FlatWords = FOOTPRINTS_FLAT_WORDS;
inline constexpr std::uint32_t WordFlatRedPx = FOOTPRINTS_FLAT_WORD_RED_PX;
inline constexpr std::uint32_t WordFlatPostPx = FOOTPRINTS_FLAT_WORD_POST_PX;
inline constexpr std::uint32_t WordFlatGroups = FOOTPRINTS_FLAT_WORD_GROUPS;
inline constexpr std::uint32_t WordFlatStamp = FOOTPRINTS_FLAT_WORD_STAMP;
inline constexpr std::uint32_t WordFlatProbe = FOOTPRINTS_FLAT_WORD_PROBE;
inline constexpr std::uint32_t FlatProbes = FOOTPRINTS_FLAT_PROBES;
inline constexpr std::uint32_t FlatProbeWords = FOOTPRINTS_FLAT_PROBE_WORDS;
// (r111i) six more words after the probes: pixels, luminance before, luminance after, for wet or mud, then blood
inline constexpr std::uint32_t WordFlatLum = FOOTPRINTS_FLAT_WORD_LUM;
inline constexpr std::uint32_t FlatLumWords = FOOTPRINTS_FLAT_LUM_WORDS;
inline constexpr std::uint32_t WordFlatSheen = FOOTPRINTS_FLAT_WORD_SHEEN; // (r111j) the blood pixels the sheen lifted
static_assert(WordFlatRedPx == 0u && WordFlatPostPx == 1u && WordFlatGroups == 2u && WordFlatStamp == 3u &&
              WordFlatProbe == 4u && WordFlatLum == WordFlatProbe + FlatProbes * FlatProbeWords &&
              FlatLumWords == 6u && WordFlatSheen == WordFlatLum + FlatLumWords && FlatWords == WordFlatSheen + 1u);
static_assert(WordPrintPx == 0 && WordSeenPx == 1 && WordSenseN == 2 && WordSenseDyMm == 3);
static_assert(WordBinLow == 4 && WordBinBelow == 5 && WordGroundN == 6 && WordBinAbove == 7);
static_assert(WordBinHigh == 8 && WordGlossSum == 9 && WordWetN == 10 && WordAlbedoR == 11);
static_assert(WordAlbedoG == 12 && WordAlbedoB == 13 && WordStamp == 14 && WordRingPx == 15);
static_assert(WordPickN == 16 && WordBloodN == 17 && WordBloodN + 1 == SlotWords);
// The numbers the README names.
static_assert(FOOTPRINTS_SENSE_RADIUS_M == 0.45 && FOOTPRINTS_SENSE_HEIGHT_M == 1.0);
static_assert(FOOTPRINTS_GROUND_M == 0.08 && FOOTPRINTS_BIN_M == 0.25);
static_assert(FOOTPRINTS_PUDDLE_GLOSS == 0.88 && FOOTPRINTS_PRINT_BAND_M == 0.16);
static_assert(FOOTPRINTS_WET_GLOSS == 0.8 && FOOTPRINTS_WET_SPEC_ROOT == 0.25 &&
              FOOTPRINTS_WET_DARKEN == 0.65);
static_assert(FOOTPRINTS_RING_IN_M == 0.3 && FOOTPRINTS_RING_OUT_M == 0.34);
static_assert(FOOTPRINTS_PICK_RADIUS_M == 0.25 && FOOTPRINTS_PICK_RADIUS_M < FOOTPRINTS_SENSE_RADIUS_M);
// A blood print's own colour is blood by the pickup rule (a print is never read as ground without it).
static_assert(BloodAlbedo::IsBlood(float(FOOTPRINTS_BLOOD_ALBEDO_R), float(FOOTPRINTS_BLOOD_ALBEDO_G),
                                   float(FOOTPRINTS_BLOOD_ALBEDO_B)));
// (r111c) the print's red runs from RED_MIN to RED_MAX and every one of them is blood by that rule too.
static_assert(FOOTPRINTS_BLOOD_RED_MIN <= FOOTPRINTS_BLOOD_ALBEDO_R &&
              FOOTPRINTS_BLOOD_ALBEDO_R <= FOOTPRINTS_BLOOD_RED_MAX);
static_assert(BloodAlbedo::IsBlood(float(FOOTPRINTS_BLOOD_RED_MIN), float(FOOTPRINTS_BLOOD_ALBEDO_G),
                                   float(FOOTPRINTS_BLOOD_ALBEDO_B)) &&
              BloodAlbedo::IsBlood(float(FOOTPRINTS_BLOOD_RED_MAX), float(FOOTPRINTS_BLOOD_ALBEDO_G),
                                   float(FOOTPRINTS_BLOOD_ALBEDO_B)));
static_assert(FOOTPRINTS_SOLE_SCALE == 1.0 && FOOTPRINTS_BLOOD_RED_KEEP == 0.6 &&
              FOOTPRINTS_BLOOD_COVER == 0.95 && FOOTPRINTS_BLOOD_GLOSS == 0.78);
// (r111d) The boot: 0.28 m long (heel's back to the ball's front), 0.11 m across at the ball; the waist
// ellipse reaches from the heel block to the ball, so the three make one print.
static_assert((FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU - (FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU)) *
                      FOOTPRINTS_SOLE_SCALE > 0.279 &&
              (FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU - (FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU)) *
                      FOOTPRINTS_SOLE_SCALE < 0.281);
static_assert(2.0 * FOOTPRINTS_FORE_RV * FOOTPRINTS_SOLE_SCALE > 0.109 &&
              2.0 * FOOTPRINTS_FORE_RV * FOOTPRINTS_SOLE_SCALE < 0.111);
static_assert(FOOTPRINTS_WAIST_U - FOOTPRINTS_WAIST_RU < FOOTPRINTS_HEEL_U + FOOTPRINTS_HEEL_RU &&
              FOOTPRINTS_WAIST_U + FOOTPRINTS_WAIST_RU > FOOTPRINTS_FORE_U - FOOTPRINTS_FORE_RU &&
              FOOTPRINTS_WAIST_RV < FOOTPRINTS_HEEL_RV && FOOTPRINTS_WAIST_RV < FOOTPRINTS_FORE_RV);
static_assert(FOOTPRINTS_EDGE > 0.0 && FOOTPRINTS_EDGE < 1.0);

enum class Kind : std::uint32_t {
    Wet = FOOTPRINTS_KIND_WET,
    Mud = FOOTPRINTS_KIND_MUD,
    Blood = FOOTPRINTS_KIND_BLOOD,
};
static_assert(FOOTPRINTS_KINDS == 3u && FOOTPRINTS_KIND_BLOOD + 1u == FOOTPRINTS_KINDS);

inline const char* KindName(Kind kind) {
    return kind == Kind::Mud ? "mud" : kind == Kind::Blood ? "blood" : "wet";
}

// The walk.
inline constexpr float StrideM = 0.75f;   ///< a print each time the hunter has gone this far across
inline constexpr float GaitHalfM = 0.11f; ///< a print this far to the left or right of his path
inline constexpr float JumpM = 2.0f;      ///< farther across in one frame: the path starts anew
inline constexpr float DropM = 1.0f;      ///< farther up or down in one frame: the path starts anew
inline constexpr float TurnMinM = 0.05f;  ///< the step's direction needs at least this much path
// The coat and the prints.
inline constexpr float LifeS = 30.0f;      ///< a print fades out over this (r111d: 30 s, was 20)
inline constexpr float DryPerStep = 0.75f; ///< the share of the coat a step leaves on the feet (r111d: 0.75, was 0.8)
inline constexpr float MinCoat = 0.06f;    ///< less: the feet are dry
inline constexpr float WaterDepthM = 0.03f; ///< this far under the water plane: in the water
inline constexpr std::uint32_t MinGroundPixels = 24;
inline constexpr std::uint32_t WetSharePercent = 30;
/// The sense read back counts only while its stamp is at most this many frames old.
inline constexpr std::uint32_t SenseFreshFrames = 8;
/// Prints farther than this from the camera are not sent.
inline constexpr float MaxDistanceM = 40.0f;
/// A box corner nearer than this in front of the camera (or behind it) makes the box the screen.
inline constexpr float NearZ = 0.05f;
/// Pixels added around a projected box.
inline constexpr std::int32_t MarginPx = 3;
/// The vertical half extent of a print's box (metres): its band and some.
inline constexpr float PrintBoxUpM = 0.2f;
/// The horizontal half extent of a print's box (metres): its sole (drawn FOOTPRINTS_SOLE_SCALE times
/// larger, r111c) fits in it at any heading.
inline constexpr float PrintBoxAcrossM = 0.2f;
static_assert(FOOTPRINTS_PRINT_BAND_M < PrintBoxUpM);
static_assert((FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU) * FOOTPRINTS_SOLE_SCALE < PrintBoxAcrossM &&
              -(FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU) * FOOTPRINTS_SOLE_SCALE < PrintBoxAcrossM);
static_assert(FOOTPRINTS_RING_OUT_M < FOOTPRINTS_SENSE_RADIUS_M);

/// BB_FOOTPRINTS_GAIN (r111c): the accepted range (r111d: from 0, which draws no print).
inline constexpr double GainMin = 0.0, GainMax = 4.0;

struct Knobs {
    bool on = false;
    bool show = false;
    bool coat_forced = false; ///< BB_FOOTPRINTS_COAT named a kind (a TEST)
    Kind coat = Kind::Wet;
    bool coat_bad = false;    ///< BB_FOOTPRINTS_COAT held text that names no kind
    float gain = 1.0f;        ///< BB_FOOTPRINTS_GAIN (r111c): a factor on every print's weight
    bool gain_bad = false;    ///< BB_FOOTPRINTS_GAIN held something but a number from GainMin to GainMax
    bool trail = false;       ///< (r111k) BB_FOOTPRINTS_TRAIL: the trail rules (Read's own default is off: r111j's rules)
};

namespace Detail {
inline const char* Trim(const char* t) {
    while (t != nullptr && (*t == ' ' || *t == '\t')) {
        ++t;
    }
    return t;
}
/// `text` (leading and trailing blanks left out) is `word`.
inline bool Is(const char* text, const char* word) {
    const char* t = Trim(text);
    if (t == nullptr) {
        return false;
    }
    const std::size_t n = std::strlen(word);
    if (std::strncmp(t, word, n) != 0) {
        return false;
    }
    return *Trim(t + n) == '\0';
}
/// (r111k) `text` is not "0" (blanks around allowed): unset, empty, "1" or other text is on.
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
    if (Detail::Is(on_text, "1")) {
        k.on = true;
    } else if (Detail::Is(on_text, "show")) {
        k.on = k.show = true;
    }
    const char* coat = Detail::Trim(coat_text);
    if (coat != nullptr && *coat != '\0') {
        if (Detail::Is(coat, "wet")) {
            k.coat_forced = true;
            k.coat = Kind::Wet;
        } else if (Detail::Is(coat, "mud")) {
            k.coat_forced = true;
            k.coat = Kind::Mud;
        } else if (Detail::Is(coat, "blood")) {
            k.coat_forced = true;
            k.coat = Kind::Blood;
        } else {
            k.coat_bad = true;
        }
    }
    // BB_FOOTPRINTS_GAIN: a number from GainMin to GainMax; anything else is 1 (said in the log).
    const char* gain = Detail::Trim(gain_text);
    if (gain != nullptr && *gain != '\0') {
        char* end = nullptr;
        const double g = std::strtod(gain, &end);
        if (end != gain && *Detail::Trim(end) == '\0' && g >= GainMin && g <= GainMax) {
            k.gain = float(g);
        } else {
            k.gain_bad = true;
        }
    }
    return k;
}

inline const Knobs& Load() {
    static const Knobs knobs = Read(std::getenv("BB_FOOTPRINTS"), std::getenv("BB_FOOTPRINTS_COAT"),
                                    std::getenv("BB_FOOTPRINTS_GAIN"), std::getenv("BB_FOOTPRINTS_TRAIL"));
    return knobs;
}

/// (r111d) The gain of BB_FOOTPRINTS_GAIN's text: the number, else 1 (as Read gives it).
inline float GainOfText(const char* text) {
    return Read("1", nullptr, text).gain;
}

/// (r111d) The gain to draw with now. With the test tools' live knobs (BB_LIVE_KNOBS_FILE) it is asked again
/// every call, so one running game can draw a view with its prints (1) and the same view without them (0);
/// without them it is Load().gain, read once.
inline float Gain() {
#if BB_FOOTPRINTS_LIVE
    static BbLiveKnobs::Knob<float> knob{"BB_FOOTPRINTS_GAIN", GainOfText};
    return knob.Get();
#else
    return Load().gain;
#endif
}

/// (r111e) BB_FOOTPRINTS_SHOW's text: "1" (blanks around allowed) draws the flat red test view; anything else
/// (unset, empty, 0, other text) does not.
inline bool ShowFlatOfText(const char* text) {
    return Detail::Is(text, "1");
}

/// (r111e) The test view now: with the live knobs asked again every call, else read once.
inline bool ShowFlat() {
#if BB_FOOTPRINTS_LIVE
    static BbLiveKnobs::Knob<bool> knob{"BB_FOOTPRINTS_SHOW", ShowFlatOfText};
    return knob.Get();
#else
    static const bool on = ShowFlatOfText(std::getenv("BB_FOOTPRINTS_SHOW"));
    return on;
#endif
}

/// (r111e) BB_FOOTPRINTS_POST: the accepted range, 0 (no post stamp) to PostMax.
inline constexpr double PostMax = 2.0;

/// (r111e) BB_FOOTPRINTS_POST's text: a number from 0 to PostMax; unset, empty, other text or a number out of
/// range: 1.
inline float PostOfText(const char* text) {
    const char* t = Detail::Trim(text);
    if (t == nullptr || *t == '\0') {
        return 1.0f;
    }
    char* end = nullptr;
    const double g = std::strtod(t, &end);
    if (end != t && *Detail::Trim(end) == '\0' && g >= 0.0 && g <= PostMax) {
        return float(g);
    }
    return 1.0f;
}

/// (r111e) The post stamp's strength now (live like the gain).
inline float Post() {
#if BB_FOOTPRINTS_LIVE
    static BbLiveKnobs::Knob<float> knob{"BB_FOOTPRINTS_POST", PostOfText};
    return knob.Get();
#else
    static const float strength = PostOfText(std::getenv("BB_FOOTPRINTS_POST"));
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

/// The hunter's path since the last print.
struct Walker {
    bool have = false;
    float last[3]{};
    float acc = 0.0f;            ///< path across since the last print
    float anchor_x = 0.0f, anchor_z = 0.0f; ///< where the last print (or the path) began
    float dir_x = 0.0f, dir_z = 1.0f;
    float side = 1.0f;           ///< the next print's side (+1, -1 in turn)
    std::uint32_t jumps = 0;     ///< the path started anew
};

struct Step {
    bool step = false;
    float x = 0.0f, y = 0.0f, z = 0.0f;
    float dir_x = 0.0f, dir_z = 1.0f;
    float side = 1.0f;
};

/// One frame's position: a step when the path since the last print reached StrideM. The print stands
/// GaitHalfM from the position, on the side (-dir_z, dir_x) times `side`.
inline Step Walk(Walker& w, const float pos[3]) {
    Step s;
    if (!w.have) {
        w.have = true;
        std::copy(pos, pos + 3, w.last);
        w.acc = 0.0f;
        w.anchor_x = pos[0];
        w.anchor_z = pos[2];
        return s;
    }
    const float dx = pos[0] - w.last[0], dy = pos[1] - w.last[1], dz = pos[2] - w.last[2];
    const float across = std::sqrt(dx * dx + dz * dz);
    std::copy(pos, pos + 3, w.last);
    if (!(across <= JumpM) || !(std::fabs(dy) <= DropM)) { // (a NaN fails both)
        ++w.jumps;
        w.acc = 0.0f;
        w.anchor_x = pos[0];
        w.anchor_z = pos[2];
        return s;
    }
    w.acc += across;
    if (w.acc < StrideM) {
        return s;
    }
    const float ax = pos[0] - w.anchor_x, az = pos[2] - w.anchor_z;
    const float along = std::sqrt(ax * ax + az * az);
    if (along >= TurnMinM) {
        w.dir_x = ax / along;
        w.dir_z = az / along;
    }
    // A run's frame may pass two strides: one print, and the path counts on from 0.
    w.acc = w.acc >= 2.0f * StrideM ? 0.0f : w.acc - StrideM;
    w.anchor_x = pos[0];
    w.anchor_z = pos[2];
    s.step = true;
    s.side = w.side;
    s.dir_x = w.dir_x;
    s.dir_z = w.dir_z;
    s.x = pos[0] - w.side * GaitHalfM * w.dir_z;
    s.y = pos[1];
    s.z = pos[2] + w.side * GaitHalfM * w.dir_x;
    w.side = -w.side;
    return s;
}

/// What the feet stand in, and so pick up: water, blood, a puddle (tried in that order).
enum class Source : std::uint32_t { None = 0, Water = 1, Puddle = 2, Blood = 3 };

inline const char* SourceName(Source source) {
    return source == Source::Water    ? "water"
           : source == Source::Puddle ? "a puddle"
           : source == Source::Blood  ? "blood"
                                      : "nothing";
}

/// The coat: its kind, how much is on the feet (0: dry), the prints still to leave at the whole
/// amount, and what the feet stood in at the last Soak.
struct Coat {
    Kind kind = Kind::Wet;
    float amount = 0.0f;    ///< 0: dry
    std::uint32_t full = 0; ///< prints that still leave the whole amount
    Source source = Source::None;
    std::uint32_t step_n = 0; ///< (r111k, trail rules) the prints of this trail so far; standing in a source resets it
};

/// How a coat wears off: `full` prints at the whole amount, then each step keeps `keep` of it.
struct CoatRule {
    std::uint32_t full;
    float keep;
};
inline constexpr std::uint32_t BloodFullPrints = 1; ///< a blood coat: this many full prints (r111h: 1, was 4)
inline constexpr float BloodKeep = 0.8f;            ///< then each step keeps this much (r111h: 0.8, was 0.75)
inline constexpr std::uint32_t WetFullPrints = 3;   ///< (r111d) a wet coat: this many full prints (was 1)
inline constexpr CoatRule RuleOf(Kind kind) {
    // (mud, which only the test coat makes, wears as wet does)
    return kind == Kind::Blood ? CoatRule{BloodFullPrints, BloodKeep} : CoatRule{WetFullPrints, DryPerStep};
}
/// (r111d) The prints a coat of amount 1 leaves before the feet are dry: what TakeStep does, counted (the
/// first `full` at the whole amount, then each step keeps `keep`; dry below MinCoat).
inline constexpr std::uint32_t CoatPrints(Kind kind) {
    const CoatRule rule = RuleOf(kind);
    float amount = 1.0f;
    std::uint32_t full = rule.full, n = 0;
    while (amount >= MinCoat && n < 64) {
        ++n;
        if (full > 1) {
            --full;
        } else {
            amount *= rule.keep;
        }
    }
    return n;
}
// Blood under the feet: of the pickup disc's up-facing ground pixels (at least MinPickPixels), at
// least BloodSharePercent are blood (blood_albedo.h); the coat's strength is the share over
// BloodFullShare, at most 1.
inline constexpr std::uint32_t MinPickPixels = 24;
inline constexpr std::uint32_t BloodSharePercent = 25;
inline constexpr float BloodFullShare = 0.5f;

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

/// The hunter's feet are in the water: his position more than WaterDepthM under the plane.
inline bool InWater(bool plane_known, float plane_y, float feet_y) {
    return plane_known && feet_y < plane_y - WaterDepthM;
}

/// The ground band around his feet holds a puddle.
inline bool GlossyGround(std::uint32_t ground, std::uint32_t wet) {
    return ground >= MinGroundPixels && std::uint64_t(wet) * 100u >= std::uint64_t(ground) * WetSharePercent;
}

/// The pickup disc is in blood: `pick` up-facing ground pixels, `blood` of them blood.
inline bool InBlood(std::uint32_t pick, std::uint32_t blood) {
    return pick >= MinPickPixels && std::uint64_t(blood) * 100u >= std::uint64_t(pick) * BloodSharePercent;
}

/// A blood coat's strength from the pickup disc: its blood share over BloodFullShare, 0 to 1.
inline float BloodAmount(std::uint32_t pick, std::uint32_t blood) {
    if (pick == 0) {
        return 0.0f;
    }
    return std::clamp(float(blood) / float(pick) / BloodFullShare, 0.0f, 1.0f);
}

/// This frame's pickup, before a step: a forced coat always. Else what the feet stand in is water
/// (wet), else blood (blood, at BloodAmount), else a puddle (wet); the newest pickup replaces the
/// coat's kind and strength, and with nothing under the feet the coat is kept as it is. True when
/// the feet stepped into a source (a different one than the frame before, or one after none).
inline bool Soak(Coat& c, const Knobs& k, bool in_water, bool glossy, std::uint32_t pick = 0,
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

/// A step's print strength (0: no print) and its kind; the coat afterwards. In the water nothing is
/// placed. The test view places every step at full (its kind the forced coat's, else wet) and dries
/// nothing; a forced coat never dries.
inline float TakeStep(Coat& c, const Knobs& k, bool in_water, Kind& kind) {
    if (in_water) {
        return 0.0f;
    }
    if (k.show || k.coat_forced) {
        kind = k.coat_forced ? k.coat : Kind::Wet;
        return 1.0f;
    }
    if (c.amount < MinCoat) {
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
    if (c.full > 1) { // (a blood coat: its first prints leave the whole amount)
        --c.full;
    } else {
        c.amount *= RuleOf(c.kind).keep;
    }
    if (c.amount < MinCoat) {
        c.amount = 0.0f;
    }
    return strength;
}

/// The share of a print's strength left at `age` seconds: 1 at 0, 0 from LifeS on, a smooth step.
inline float Fade(double age) {
    const float u = std::clamp(1.0f - float(age) / LifeS, 0.0f, 1.0f);
    return u * u * (3.0f - 2.0f * u);
}

/// A pixel rectangle [x0, x1) x [y0, y1).
struct Rect {
    std::int32_t x0 = 0, y0 = 0, x1 = 0, y1 = 0;
    [[nodiscard]] bool Empty() const {
        return x1 <= x0 || y1 <= y0;
    }
};

inline Rect Union(const Rect& a, const Rect& b) {
    if (a.Empty()) {
        return b;
    }
    if (b.Empty()) {
        return a;
    }
    return {std::min(a.x0, b.x0), std::min(a.y0, b.y0), std::max(a.x1, b.x1), std::max(a.y1, b.y1)};
}

/// The pixels a world box [lo, hi] covers on a pass's screen: `view` world to view (3x4 rows, view
/// +z in front), `proj` the x and y scales (signed: ndc +y down), `size` pixels, `jitter` render
/// pixels. The inverse of the shader's pixel to view rule (ndc = ((p + 0.5) - jitter) / size * 2 - 1,
/// view = (ndc.x z / proj.x, ndc.y z / proj.y, z)), widened by MarginPx and cut to the screen. A box
/// wholly behind NearZ is empty; one partly behind it is the whole screen.
inline Rect Project(const std::array<float, 12>& view, const std::array<float, 4>& proj, float width,
                    float height, const std::array<float, 2>& jitter, const float lo[3],
                    const float hi[3]) {
    float min_x = 0.0f, min_y = 0.0f, max_x = 0.0f, max_y = 0.0f;
    std::uint32_t behind = 0;
    bool any = false;
    for (std::uint32_t i = 0; i < 8; ++i) {
        const float x = (i & 1u) ? hi[0] : lo[0], y = (i & 2u) ? hi[1] : lo[1], z = (i & 4u) ? hi[2] : lo[2];
        const float vx = view[0] * x + view[1] * y + view[2] * z + view[3];
        const float vy = view[4] * x + view[5] * y + view[6] * z + view[7];
        const float vz = view[8] * x + view[9] * y + view[10] * z + view[11];
        if (!(vz > NearZ)) {
            ++behind;
            continue;
        }
        const float px = (vx * proj[0] / vz * 0.5f + 0.5f) * width + jitter[0] - 0.5f;
        const float py = (vy * proj[1] / vz * 0.5f + 0.5f) * height + jitter[1] - 0.5f;
        if (!std::isfinite(px) || !std::isfinite(py)) {
            ++behind;
            continue;
        }
        min_x = any ? std::min(min_x, px) : px;
        max_x = any ? std::max(max_x, px) : px;
        min_y = any ? std::min(min_y, py) : py;
        max_y = any ? std::max(max_y, py) : py;
        any = true;
    }
    const std::int32_t w = std::int32_t(width), h = std::int32_t(height);
    if (behind == 8) {
        return {};
    }
    if (behind != 0) {
        return {0, 0, w, h};
    }
    // (far outside the screen: cut before the casts)
    const float lim = 4.0f * std::max(width, height) + 64.0f;
    Rect r;
    r.x0 = std::max(std::int32_t(std::floor(std::max(min_x, -lim))) - MarginPx, 0);
    r.y0 = std::max(std::int32_t(std::floor(std::max(min_y, -lim))) - MarginPx, 0);
    r.x1 = std::min(std::int32_t(std::ceil(std::min(max_x, lim))) + 1 + MarginPx, w);
    r.y1 = std::min(std::int32_t(std::ceil(std::min(max_y, lim))) + 1 + MarginPx, h);
    return r.Empty() ? Rect{} : r;
}

/// (r111f) Where one world point lands on a pass's screen, by the rule of Project and of the shaders: `view`
/// world to view (3x4 rows, view +z in front), `proj` the x and y scales (signed), `size` pixels, `jitter`
/// render pixels. `state`: 1 inside the picture, 0 outside it, 2 behind the camera (view z at or under
/// NearZ, or not a number: x and y are then 0). (x, y) is the pixel as the shaders' `p` (centres at integers).
struct ScreenPoint {
    float x = 0.0f, y = 0.0f, z = 0.0f; ///< the pixel, the view z in metres
    std::int32_t state = 2;
};

inline ScreenPoint ProjectPoint(const std::array<float, 12>& view, const std::array<float, 4>& proj, float width,
                                float height, const std::array<float, 2>& jitter, float wx, float wy, float wz) {
    ScreenPoint s;
    s.z = view[8] * wx + view[9] * wy + view[10] * wz + view[11];
    if (!(s.z > NearZ)) {
        return s;
    }
    const float vx = view[0] * wx + view[1] * wy + view[2] * wz + view[3];
    const float vy = view[4] * wx + view[5] * wy + view[6] * wz + view[7];
    s.x = (vx * proj[0] / s.z * 0.5f + 0.5f) * width + jitter[0] - 0.5f;
    s.y = (vy * proj[1] / s.z * 0.5f + 0.5f) * height + jitter[1] - 0.5f;
    if (!std::isfinite(s.x) || !std::isfinite(s.y)) {
        s.x = s.y = 0.0f;
        s.state = 2;
        return s;
    }
    s.state = (s.x >= 0.0f && s.y >= 0.0f && s.x <= width - 1.0f && s.y <= height - 1.0f) ? 1 : 0;
    return s;
}

/// The push block, word for word as footprints.comp declares it (112 bytes).
struct Push {
    std::array<float, 12> inv_view{}; ///< this pass's view to world, 3x4 rows
    std::array<float, 4> proj{};      ///< x scale, y scale (signed), z scale, z offset
    std::array<float, 2> size{};      ///< pixels
    std::array<float, 2> jitter{};    ///< render pixels
    std::array<float, 4> hunter{};    ///< his position (x, y, z), 0
    std::uint32_t count = 0;          ///< prints in the buffer
    std::uint32_t flags = 0;          ///< FOOTPRINTS_FLAG_*
    std::uint32_t stamp = 0;          ///< the frame + 1 (the counter slot's STAMP word)
    float gain = 1.0f;                ///< BB_FOOTPRINTS_GAIN (r111c)
};
static_assert(sizeof(Push) == 112);

/// `srgb`: G-buffer target 2 is R8G8B8A8_SRGB (the shader decodes and encodes it).
inline std::uint32_t Flags(const Knobs& k, bool hunter, std::uint32_t slot, bool srgb) {
    return (k.show ? FlagShow : 0u) | (slot != 0 ? FlagSlot : 0u) | (hunter ? FlagHunter : 0u) |
           (srgb ? FlagSrgb : 0u);
}

/// A print as the shader reads it: (x, y, z, strength), (dir x, dir z, side, kind).
inline constexpr std::uint32_t PrintFloats = 8;
inline void Pack(float x, float y, float z, float strength, float dir_x, float dir_z, float side,
                 Kind kind, float* out) {
    out[0] = x;
    out[1] = y;
    out[2] = z;
    out[3] = strength;
    out[4] = dir_x;
    out[5] = dir_z;
    out[6] = side;
    out[7] = float(std::uint32_t(kind));
}

} // namespace Vulkan::FootprintRules
