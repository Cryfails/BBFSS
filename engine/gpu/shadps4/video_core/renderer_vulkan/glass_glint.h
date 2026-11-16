// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r86b_glass-visible): the lamps' glints on the glass BB_RT_GLASS puts into the ray traced
// scene (the Hunter's Dream house's bottles and jars: the pane pair e30b0480:8a6c7657, drawn
// forward after the lamp pass). No Vulkan here: the knobs, the lamps a pass takes, the order of
// the reasons a pass is skipped and the shader's numbers in C++ (engine/tests/test_glass_glint.cpp
// checks them). The pass is GlassGlint (vk_glass_glint.h), the shader host_shaders/glass_glint.comp.
//
// The rules:
//  - BB_GLASS_GLINT, read once: unset, empty, 0 or a negative number: off; `1`: strength 1; a
//    number above 0: the strength, put into 0.25 to 4; `show`: strength 1 and the test view (cyan a
//    pane in front of the depth, blue a pane only behind it, magenta a glint); other text: off,
//    said once. BB_GLASS_GLINT_SHARP: the Blinn-Phong exponent, 16 to 4096 (default 32, 256 before r86c; other
//    text: the default, said once). Off also while BB_RT_GLASS is off (no pane in the scene).
//  - On, RtShadow carries the panes drawn in a frame into the next frame's scene and builds their
//    waiting captures at the frame end, as BB_RT_GLASS_LIGHT does (RtGlassCarryOn).
//  - A pass runs right after a pane's forward draw (at most MaxPasses a frame, once a depth), when
//    in this order: the TLAS was written this frame and holds a pane (else "no pane"), with the
//    camera of this draw, not in a menu's preview frame (else "camera"), a lamp of the last
//    G-buffer pass's light grid can
//    shine (else "no lamps"), no lamps-apart batch is open (else "lamps open": the pass reads the
//    camera depth and is skipped, not made to end it), target 0 is a writable RGBA16F image of the
//    depth's size and the game's own scene (not the reduced one) (else "shape"), and fewer than
//    MaxPasses passes ran this frame and none on this depth (else "cap"; r86c asks the cap first,
//    before any other work, so a draw it leaves out costs a few compares).
//  - Lamps: of the lights of the last G-buffer pass (each kept once, as drawn, with
//    BB_LAMP_FLICKER's colour), LampFog::Select's MaxLamps that show most; a channel below 0 is 0,
//    a colour over LampColourMost is scaled down to it (bad guest data only).
#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <span>

#include "../host_shaders/glass_glint_layout.h"
#include "../host_shaders/rt_glass_layout.h"
#include "lamp_fog_lights.h"
#include "rt_glass.h"

namespace BbGlassGlint {

inline constexpr float MinStrength = 0.25f, MaxStrength = 4.0f;
inline constexpr std::uint32_t SharpDefault = 32, SharpMin = 16, SharpMax = 4096;
inline constexpr std::uint32_t MaxPasses = 2;
inline constexpr float LampColourMost = 16.0f;

inline constexpr std::uint32_t Group = GLASS_GLINT_GROUP, Block = GLASS_GLINT_BLOCK;
inline constexpr std::uint32_t FlagShow = GLASS_GLINT_FLAG_SHOW;
inline constexpr std::uint32_t LampMask = GLASS_GLINT_LAMP_MASK;
inline constexpr std::uint32_t Slots = GLASS_GLINT_SLOTS, SlotWords = GLASS_GLINT_SLOT_WORDS;
inline constexpr std::uint32_t MaxLamps = GLASS_GLINT_MAX_LAMPS, LampWords = GLASS_GLINT_LAMP_WORDS;
inline constexpr std::uint32_t DataCount = GLASS_GLINT_DATA_COUNT, DataLamps = GLASS_GLINT_DATA_LAMPS;
inline constexpr std::uint32_t DataWords = GLASS_GLINT_DATA_WORDS;
// bbport (r86e_glint-hit-distance): the pane draw's words and the camera's in the data block, and the
// raw-value records after the data blocks (glass_glint_layout.h)
inline constexpr std::uint32_t DataDraw = GLASS_GLINT_DATA_DRAW, DataView = GLASS_GLINT_DATA_VIEW;
inline constexpr std::uint32_t DbgWords = GLASS_GLINT_DBG_WORDS, DbgFirst = GLASS_GLINT_DBG_FIRST;
inline constexpr std::uint32_t DbgRecord = GLASS_GLINT_DBG_RECORD;
inline constexpr std::uint32_t DbgPaneMax = GLASS_GLINT_DBG_PANE_MAX, DbgGridMax = GLASS_GLINT_DBG_GRID_MAX;
inline constexpr float PaneMax = float(GLASS_GLINT_PANE_MAX);
/// The pane draw a pass follows (the log says which pair and how many indices).
struct PaneDraw {
    std::uint64_t vs = 0, ps = 0;
    std::uint32_t indices = 0, instances = 0;
};
inline constexpr std::uint32_t CounterWords = GLASS_GLINT_W_COUNT;
inline constexpr std::uint32_t QuadPercent = GLASS_GLINT_QUAD_PERCENT;
inline constexpr float F0 = float(GLASS_GLINT_F0), AddMax = float(GLASS_GLINT_ADD_MAX);
inline constexpr float Gain = float(GLASS_GLINT_GAIN); // bbport (r86c_glass-glint-visible)
inline constexpr float TolAbs = float(GLASS_GLINT_TOL_ABS), TolRel = float(GLASS_GLINT_TOL_REL);
inline constexpr float ShadowLevel = float(GLASS_GLINT_SHADOW_LEVEL);

static_assert(Group == 8 && Block == 4, "glass_glint.comp's SPAN (6 blocks) is for these");
static_assert((Group + 2) * 2 / Block + 1 <= 6 && 6 * 6 <= Group * Group,
              "SHADE: the blocks under a quad tile and its border, one a thread");
static_assert(MaxLamps * 2 <= Group * Group, "SHADE: two vec4 a lamp, one a thread");
static_assert(DataLamps + MaxLamps * LampWords <= DataWords && DataCount < DataLamps);
// bbport (r86e_glint-hit-distance)
static_assert(DataDraw + 6 <= DataLamps && DataView >= DataLamps + MaxLamps * LampWords &&
                  DataView + 12 <= DataWords,
              "the data block: count, the pane draw, the lamps, the camera");
static_assert(DbgFirst + (DbgPaneMax + DbgGridMax) * DbgRecord == DbgWords && DbgRecord == 16 &&
                  DbgFirst >= 1,
              "the raw-value area: a count, then the records");
static_assert(CounterWords <= SlotWords && GLASS_GLINT_W_MAX_ADD < CounterWords &&
              GLASS_GLINT_W_NO_NORMAL < CounterWords);
// bbport (r86c_glass-glint-visible): the shader flushes 12 to 15 with atomicAdd, 16 to 18 with
// atomicMax, 19 and 20 with atomicAdd
static_assert(GLASS_GLINT_W_NO_NORMAL + 1 == GLASS_GLINT_W_UNITS &&
                  GLASS_GLINT_W_DIST_SUM + 1 == GLASS_GLINT_W_DIST_MIN &&
                  GLASS_GLINT_W_NH_MAX + 1 == GLASS_GLINT_W_CURVED &&
                  GLASS_GLINT_W_T_SUM + 1 == GLASS_GLINT_W_FAR_SUM && GLASS_GLINT_W_NEAR + 1 == GLASS_GLINT_W_COUNT && GLASS_GLINT_W_NH_MAX > GLASS_GLINT_W_BEST_MAX &&
                  GLASS_GLINT_W_BEST_MAX > GLASS_GLINT_W_DIST_MIN);
static_assert(GLASS_GLINT_W_GLASS < GLASS_GLINT_W_SHADOWED &&
              GLASS_GLINT_W_SHADOWED + 1 == GLASS_GLINT_W_MAX_ADD,
              "SHADE flushes words W_GLASS to W_SHADOWED with atomicAdd, W_MAX_ADD with atomicMax");
static_assert(LampMask == 0x04u && (LampMask & RT_GLASS_MASK) == 0,
              "a shadow ray never meets a pane (the panes are under RT_GLASS_MASK alone)");
static_assert(Slots >= 4, "a slot is read back Slots - 1 passes after its pass");

struct Knobs {
    float strength = 0.0f;
    bool show = false;
    bool unreadable = false;
    std::uint32_t sharp = SharpDefault;
    bool sharp_unreadable = false;
};

/// BB_GLASS_GLINT's text (see the rules above).
inline float ParseStrength(const char* text, bool& show, bool& unreadable) {
    if (text == nullptr || text[0] == 0) {
        return 0.0f;
    }
    if (std::strcmp(text, "show") == 0) {
        show = true;
        return 1.0f;
    }
    char* end = nullptr;
    const float v = std::strtof(text, &end);
    while (end != nullptr && (*end == ' ' || *end == '\t')) {
        ++end;
    }
    if (end == text || end == nullptr || *end != 0 || !std::isfinite(v)) {
        unreadable = true;
        return 0.0f;
    }
    return v > 0.0f ? std::clamp(v, MinStrength, MaxStrength) : 0.0f;
}

/// BB_GLASS_GLINT_SHARP's text: unset or empty is SharpDefault; a whole number is put into SharpMin
/// to SharpMax; other text is SharpDefault and unreadable.
inline std::uint32_t ParseSharp(const char* text, bool& unreadable) {
    if (text == nullptr || text[0] == 0) {
        return SharpDefault;
    }
    char* end = nullptr;
    const long v = std::strtol(text, &end, 10);
    while (end != nullptr && (*end == ' ' || *end == '\t')) {
        ++end;
    }
    if (end == text || end == nullptr || *end != 0) {
        unreadable = true;
        return SharpDefault;
    }
    return v < long(SharpMin) ? SharpMin : v > long(SharpMax) ? SharpMax : std::uint32_t(v);
}

inline Knobs Parse(const char* glint, const char* sharp) {
    Knobs k;
    k.strength = ParseStrength(glint, k.show, k.unreadable);
    k.sharp = ParseSharp(sharp, k.sharp_unreadable);
    return k;
}

/// bbport (r86j_glint-same-game): BB_GLASS_GLINT's text read again while the game runs (the test tools' live
/// knobs): the strength, negative for the test view ("show", strength 1); 0 for off, empty or unreadable text.
inline float ParseLive(const char* text) {
    bool show = false, unreadable = false;
    const float strength = ParseStrength(text, show, unreadable);
    return show ? -strength : strength;
}

/// The knobs, read once (the first caller).
inline const Knobs& Load() {
    static const Knobs knobs =
        Parse(std::getenv("BB_GLASS_GLINT"), std::getenv("BB_GLASS_GLINT_SHARP"));
    return knobs;
}

/// On: a strength above 0 and BB_RT_GLASS on. Off, nothing of the glint is made or run.
inline bool On() {
    static const bool on = Load().strength > 0.0f && Vulkan::RtGlassOn();
    return on;
}

/// The push words of glass_glint.comp, field for field.
struct Push {
    std::array<float, 4> proj{};          ///< x scale, y scale, z scale, z offset
    std::array<float, 4> frame{};         ///< width, height, jitter x, jitter y (pixels)
    std::array<std::uint32_t, 4> info{};  ///< blocks across, blocks down, slot, flags
    std::array<float, 4> params{};        ///< strength, exponent, Normalisation(exponent), 0
};
static_assert(sizeof(Push) == 64);

/// Blinn-Phong's normalisation for exponent `n` in the game's lamp units: (n + 8) / 8. The game's
/// lamp light is colour x (1 - d / reach)^2 x N.L, times albedo, with no 1/pi (Lambert as albedo /
/// pi, so the colour is pi x the radiance factor); the BRDF's (n + 8) / (8 pi) times that pi.
constexpr float Normalisation(float n) {
    return (n + 8.0f) / 8.0f;
}

/// Schlick's Fresnel from F0 at cos(view, half) `vh`.
inline float Fresnel(float vh) {
    return F0 + (1.0f - F0) * std::pow(1.0f - std::clamp(vh, 0.0f, 1.0f), 5.0f);
}

/// One lamp's term before its colour and the strength (glass_glint.comp's Glint): 0 at or past the
/// reach or facing away.
inline float Term(float d, float reach, float nl, float nh, float vh, float n) {
    if (!(d < reach) || !(nl > 0.0f)) {
        return 0.0f;
    }
    const float fall = 1.0f - d / reach;
    return fall * fall * nl * Fresnel(vh) * Normalisation(n) * Gain * std::pow(std::max(nh, 0.0f), n);
}

/// A pane at distance `t` is in front of the depth at distance `depth_t` (the shader's Reach).
constexpr bool InFront(float t, float depth_t) {
    return t <= depth_t + TolAbs + TolRel * depth_t;
}

/// More than QuadPercent of the blocks flagged: SHADE's quad mode (the shader's 32-bit words).
constexpr bool Quads(std::uint32_t flagged, std::uint32_t blocks) {
    return flagged * 100u > blocks * QuadPercent;
}

constexpr std::uint32_t BlocksOf(std::uint32_t pixels) {
    return (pixels + Block - 1) / Block;
}

constexpr std::uint32_t GroupsOf(std::uint32_t units) {
    return (units + Group - 1) / Group;
}

/// bbport (r86c_glass-glint-visible): the nearest lamp-to-pane distance of a pass in metres from its
/// counter word (0xFFFFFFFF less the distance in mm; 0: no pair, -1).
constexpr float DistMinMetres(std::uint32_t stored) {
    return stored == 0 ? -1.0f : float(0xFFFFFFFFu - stored) * 0.001f;
}

/// A lamp of a pass, in view space.
struct Lamp {
    std::array<float, 3> view{};
    float reach = 0.0f;
    std::array<float, 3> colour{};
};

struct Picked {
    std::array<Lamp, MaxLamps> lamps{};
    std::uint32_t count = 0;
};

/// The pass's lamps from the light grid's records (lamp_fog_lights.h: view x, y, z, inverse reach
/// squared, colour r, g, b, ...).
inline Picked PickLamps(std::span<const LampFog::Light> lights) {
    Picked picked;
    const auto chosen = LampFog::Select(lights, MaxLamps);
    for (const auto& light : chosen.lights) {
        const auto word = [&](std::size_t i) { return std::bit_cast<float>(light[i]); };
        const float reach = 1.0f / std::sqrt(word(3));
        if (!std::isfinite(reach) || !(reach > 0.0f) || picked.count >= MaxLamps) {
            continue;
        }
        Lamp lamp{{word(0), word(1), word(2)}, reach,
                  {std::max(word(4), 0.0f), std::max(word(5), 0.0f), std::max(word(6), 0.0f)}};
        const float most = std::max({lamp.colour[0], lamp.colour[1], lamp.colour[2]});
        if (most > LampColourMost) {
            for (float& c : lamp.colour) {
                c *= LampColourMost / most;
            }
        }
        picked.lamps[picked.count++] = lamp;
    }
    return picked;
}

/// A lamp's words in the data block.
inline std::array<float, LampWords> Words(const Lamp& lamp) {
    return {lamp.view[0],   lamp.view[1],   lamp.view[2],   lamp.reach,
            lamp.colour[0], lamp.colour[1], lamp.colour[2], 0.0f};
}

/// The same camera (world to view, 3x4 rows): each entry within 1e-4 of the larger of 1 and its
/// size.
inline bool SameCamera(const std::array<float, 12>& a, const std::array<float, 12>& b) {
    for (std::size_t i = 0; i < a.size(); ++i) {
        if (!(std::fabs(a[i] - b[i]) <= 1e-4f * std::max(1.0f, std::fabs(a[i])))) {
            return false;
        }
    }
    return true;
}

/// Why a pass does not run, in the order the gate asks.
enum class Skip : std::uint32_t { None, NoPane, OtherCamera, NoLamps, LampsOpen, Shape, Cap };

struct Gate {
    bool panes = false;       ///< the TLAS holds a pane record
    bool this_frame = false;  ///< and was written this frame
    bool same_camera = false; ///< with this draw's camera
    bool lamps = false;       ///< a lamp of the pass can shine
    bool lamps_open = false;  ///< a lamps-apart batch is open
    bool shape = false;       ///< target 0 and the depth fit
    std::uint32_t passes = 0; ///< passes run this frame
    bool depth_done = false;  ///< a pass ran on this depth this frame
};

/// bbport (r86c_glass-glint-visible): the cap, asked first and before any other work: MaxPasses
/// passes ran this frame, or one ran on this depth.
constexpr bool Capped(std::uint32_t passes, bool depth_done) {
    return passes >= MaxPasses || depth_done;
}

constexpr Skip Decide(const Gate& g) {
    return Capped(g.passes, g.depth_done)       ? Skip::Cap
           : (!g.panes || !g.this_frame)        ? Skip::NoPane
           : !g.same_camera                     ? Skip::OtherCamera
           : !g.lamps                           ? Skip::NoLamps
           : g.lamps_open                       ? Skip::LampsOpen
           : !g.shape                           ? Skip::Shape
                                                : Skip::None;
}

} // namespace BbGlassGlint
