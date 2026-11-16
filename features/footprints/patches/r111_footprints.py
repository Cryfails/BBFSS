# r111_footprints: FEATURE patch (atmosphere work order: "footprints that react to wet surfaces
# making wet foot prints, muddy, or bloody", owner 2026-11-15 about 07:45). Off by default behind
# BB_FOOTPRINTS=1 (or show). Branch: visual/footprints.
#
# What it does (stage 1): the hunter's feet leave prints on the ground that fade out over 20 s. The
# renderer does not see the game's animation, so the steps are made from the hunter's path: once a
# frame the engine reads his physics position from the game (new BbEngine::world_player_position in
# engine_state.cpp: the chain online_fixes.cpp's Position reads), and each 0.75 m of path across
# places a print 0.11 m left or right of it in turn (footprints.h Walk). The feet are wet while his
# position lies more than 3 cm under the water plane of a mirrored frame (CameraMotion::MirrorPlane:
# the sewers) or while the ground around his feet is a puddle (the pass's sense, read back: 24+
# up-facing ground pixels within 0.45 m and 8 cm of his height, 30% of them with gloss 0.88+); each
# step leaves 0.8 of the coat, dry below 0.06 (13 prints). Mud and blood have no source the engine
# sees: BB_FOOTPRINTS_COAT=wet|mud|blood (a TEST) forces a coat that never dries. The prints are
# laid into the game's G-buffer (gloss target 1, albedo target 2, specular colour target 3) by one
# compute pass at the first light draw after each G-buffer pass (as r100's wet ground), dispatched
# with a base over the smallest screen rectangle that holds the prints' boxes and the hunter's box.
# Target 2 is R8G8B8A8_SRGB in the game (vk_ssgi.cpp takes it only so): the pass writes it through
# an R8G8B8A8_UNORM view (the texture cache makes every image mutable with extended usage) and
# decodes and encodes sRGB in the shader (FOOTPRINTS_FLAG_SRGB), so the colour rules are linear.
# (Review fix 2026-11-15: the draft wanted UNORM for target 2 and would have left every pass out.)
# NOT MEASURED: that the game's physics position and the renderer's world are the same space. The
# show view (a magenta ring at the read position, the ground band yellow) and the log line "first
# hunter position ..., camera ... m away, ... m above" decide it in the first slot run.
#
# Off (the default): the rasterizer makes no Footprints (Footprints::Wanted reads BB_FOOTPRINTS
# once), so both hooks are one null pointer test each, no pipeline, buffer or pass exists, and the
# game's memory is not read (world_player_position is called only by Footprints::OnFrameEnd). The
# other shader builds are not touched (one new build, footprints_comp).
#
# Files, new: renderer_vulkan/footprints.h (pure rules), vk_footprints.h/.cpp, host_shaders/
# footprints.comp and footprints_layout.h, engine/tests/test_footprints.cpp. Edited (insert only,
# each anchor kept whole and found exactly once; anchors are old lines, none of another drafter's
# feature): vk_rasterizer.h (include, member), vk_rasterizer.cpp (made when wanted),
# vk_rasterizer_effects.cpp (EffectsBeforeResources hook first in the function, EffectsOnFrameEnd
# hook before point_shadow->OnFrameEnd), shim/engine/engine_state.h/.cpp (world_player_position),
# CMakeLists.txt (shader include rule, add_host_shader, footprints-test), build.sh (footprints-test),
# test_effect_pipelines.cpp (include, pass entry), README.md (section before "## Sponsors").
#
# Use: python -I -X utf8 r111_footprints.py check | apply | revert
# Root: R111_ROOT (or R111_FOOTPRINTS_ROOT), else <tree>. Line ends kept (CRLF in the tree; new
# files CRLF). apply backs the originals up in r111_backup next to this script; revert takes out
# exactly what apply inserted (each inserted text found by itself, exactly once) and removes the new
# files (refused if one differs from this patch's text).
import os, sys

ROOT = os.environ.get("R111_ROOT") or os.environ.get("R111_FOOTPRINTS_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r111_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RAST_H = RV + "vk_rasterizer.h"
RAST_C = RV + "vk_rasterizer.cpp"
EFFECTS = RV + "vk_rasterizer_effects.cpp"
STATE_H = "engine/gpu/shim/engine/engine_state.h"
STATE_C = "engine/gpu/shim/engine/engine_state.cpp"
CMAKE = "engine/gpu/CMakeLists.txt"
BUILD = "engine/build.sh"
PIPES = "engine/tests/test_effect_pipelines.cpp"
README = "README.md"
ORDER = [RAST_H, RAST_C, EFFECTS, STATE_H, STATE_C, CMAKE, BUILD, PIPES, README]

NEW = {
    RV + "footprints.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r111_footprints): prints the hunter's feet leave on the ground after he stepped in water
// (wet), and with a test knob mud or blood; each fades out over LifeS (20 s).
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
// water). Each print takes the coat's amount as its strength, and the coat then keeps DryPerStep of
// it; below MinCoat the feet are dry and place nothing. BB_FOOTPRINTS_COAT (a TEST) gives the feet a
// coat that never dries. The game marks neither mud nor blood in what the engine sees (a blood pool
// is a forward draw, not ground), so mud and blood prints come only from that test knob for now.
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
// No Vulkan here: tests/test_footprints.cpp builds it alone.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>

#include "../host_shaders/footprints_layout.h"

namespace Vulkan::FootprintRules {

inline constexpr std::uint32_t Group = FOOTPRINTS_GROUP;
inline constexpr std::uint32_t MaxPrints = FOOTPRINTS_MAX_PRINTS;
inline constexpr std::uint32_t SlotWords = FOOTPRINTS_SLOT_WORDS, Slots = 2;
inline constexpr std::uint32_t FlagShow = FOOTPRINTS_FLAG_SHOW, FlagSlot = FOOTPRINTS_FLAG_SLOT;
inline constexpr std::uint32_t FlagHunter = FOOTPRINTS_FLAG_HUNTER, FlagSrgb = FOOTPRINTS_FLAG_SRGB;
static_assert(Group == 8u && MaxPrints == 48u && SlotWords == 16u);
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
static_assert(WordPrintPx == 0 && WordSeenPx == 1 && WordSenseN == 2 && WordSenseDyMm == 3);
static_assert(WordBinLow == 4 && WordBinBelow == 5 && WordGroundN == 6 && WordBinAbove == 7);
static_assert(WordBinHigh == 8 && WordGlossSum == 9 && WordWetN == 10 && WordAlbedoR == 11);
static_assert(WordAlbedoG == 12 && WordAlbedoB == 13 && WordStamp == 14 && WordRingPx == 15);
static_assert(WordRingPx + 1 == SlotWords);
// The numbers the README names.
static_assert(FOOTPRINTS_SENSE_RADIUS_M == 0.45 && FOOTPRINTS_SENSE_HEIGHT_M == 1.0);
static_assert(FOOTPRINTS_GROUND_M == 0.08 && FOOTPRINTS_BIN_M == 0.25);
static_assert(FOOTPRINTS_PUDDLE_GLOSS == 0.88 && FOOTPRINTS_PRINT_BAND_M == 0.12);
static_assert(FOOTPRINTS_WET_GLOSS == 0.62 && FOOTPRINTS_WET_SPEC_ROOT == 0.2 &&
              FOOTPRINTS_WET_DARKEN == 0.5);
static_assert(FOOTPRINTS_RING_IN_M == 0.3 && FOOTPRINTS_RING_OUT_M == 0.34);

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
inline constexpr float LifeS = 20.0f;      ///< a print fades out over this
inline constexpr float DryPerStep = 0.8f;  ///< the share of the coat a step leaves on the feet
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
inline constexpr float PrintBoxUpM = 0.15f;
/// The horizontal half extent of a print's box (metres): its sole fits in it at any heading.
inline constexpr float PrintBoxAcrossM = 0.16f;
static_assert(FOOTPRINTS_PRINT_BAND_M < PrintBoxUpM);
static_assert(FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU < PrintBoxAcrossM &&
              -(FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU) < PrintBoxAcrossM);
static_assert(FOOTPRINTS_RING_OUT_M < FOOTPRINTS_SENSE_RADIUS_M);

struct Knobs {
    bool on = false;
    bool show = false;
    bool coat_forced = false; ///< BB_FOOTPRINTS_COAT named a kind (a TEST)
    Kind coat = Kind::Wet;
    bool coat_bad = false;    ///< BB_FOOTPRINTS_COAT held text that names no kind
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
} // namespace Detail

inline Knobs Read(const char* on_text, const char* coat_text) {
    Knobs k;
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
    return k;
}

inline const Knobs& Load() {
    static const Knobs knobs = Read(std::getenv("BB_FOOTPRINTS"), std::getenv("BB_FOOTPRINTS_COAT"));
    return knobs;
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

struct Coat {
    Kind kind = Kind::Wet;
    float amount = 0.0f; ///< 0: dry
};

/// The hunter's feet are in the water: his position more than WaterDepthM under the plane.
inline bool InWater(bool plane_known, float plane_y, float feet_y) {
    return plane_known && feet_y < plane_y - WaterDepthM;
}

/// The ground band around his feet holds a puddle.
inline bool GlossyGround(std::uint32_t ground, std::uint32_t wet) {
    return ground >= MinGroundPixels && std::uint64_t(wet) * 100u >= std::uint64_t(ground) * WetSharePercent;
}

/// This frame's soaking, before a step: a forced coat always; water or a puddle make the feet wet.
inline void Soak(Coat& c, const Knobs& k, bool in_water, bool glossy) {
    if (k.coat_forced) {
        c.kind = k.coat;
        c.amount = 1.0f;
        return;
    }
    if (in_water || glossy) {
        c.kind = Kind::Wet;
        c.amount = 1.0f;
    }
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
    const float strength = c.amount;
    c.amount *= DryPerStep;
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
    std::uint32_t pad = 0;
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
''',
    RV + "vk_footprints.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r111_footprints): the hunter's footprints after he stepped in water (and, with a test
// knob, mud or blood), laid into the game's G-buffer so its own lights light them (footprints.h has
// the knobs and the rules, host_shaders/footprints.comp the pass).
//
// Where (hooks in vk_rasterizer_effects.cpp, each a null pointer test while it is off):
//  - EffectsBeforeResources, every draw (BeforeDraw): before its textures, barriers and pass. It
//    notes each G-buffer pass's depth and targets 1 (gloss), 2 (albedo) and 3 (specular colour); at
//    the first light draw after each G-buffer pass (the sun's shadow resolve, the sun or moon, or a
//    lamp of the light grid) it takes the frame's water plane (CameraMotion::MirrorPlane) and records
//    the pass over the smallest screen rectangle that holds the boxes of the prints on this pass's
//    screen and of the ground around the hunter (not while a lamps-apart batch is open: the batch's
//    lamps read the G-buffer later; not in a menu's 3D preview). Targets 1 and 3 must be
//    R8G8B8A8_UNORM, target 2 R8G8B8A8_UNORM or _SRGB (the game's: written through a UNORM view,
//    the shader decodes and encodes sRGB).
//  - EffectsOnFrameEnd (OnFrameEnd): the hunter's position (BbEngine::world_player_position), the
//    sense read back from a recent frame, the coat, the step, the prints' fading; every LineFrames
//    frames two log lines.
// The pass ends the game's render pass (the next draw begins a new one), as the engine's other
// passes between draws do.
//
// Off (BB_FOOTPRINTS unset, 0 or other text): the rasterizer makes no Footprints (Wanted), so nothing
// of this is made or run and the game's memory is not read; the frame is as before, bit for bit.
// On: one pipeline and three small buffers (1.5 KB of prints, 128 B of counters, 64 B host copy),
// made at the first pass; no image. A frame whose prints and hunter are all off this pass's screen
// records nothing. It needs the upscaler's camera (CameraMotion::Enabled): without it, off (said).
#pragma once

#include <array>
#include <chrono>

#include "common/types.h"
#include "video_core/renderer_vulkan/footprints.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class GraphicsPipeline;
class Instance;
class Runtime;
class SceneTargets;
class Scheduler;

class Footprints {
public:
    /// BB_FOOTPRINTS is 1 or "show" (FootprintRules::Load, read once).
    [[nodiscard]] static bool Wanted();
    /// Says the knobs once.
    Footprints(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
               Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~Footprints();
    Footprints(const Footprints&) = delete;
    Footprints& operator=(const Footprints&) = delete;

    /// Before every draw's resources: `targets` its colour targets (only those in its mrt_mask are
    /// this draw's), `depth` its depth target; `light_draw`: the sun's shadow resolve, the sun or
    /// moon, or a lamp of the light grid; `lamps_pending`: a lamps-apart batch is still open;
    /// `jitter`: this frame's viewport shift.
    void BeforeDraw(const GraphicsPipeline& pipeline, const std::array<VideoCore::ImageId, 8>& targets,
                    VideoCore::ImageId depth, bool light_draw, bool lamps_pending,
                    std::array<float, 2> jitter);
    /// Every frame end: the hunter, the coat, the steps and prints; every LineFrames frames the
    /// "Footprints (r111):" lines.
    void OnFrameEnd();

private:
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::Format format{};
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    /// A placed print: where, which way, its kind, its strength when placed and its time.
    struct Placed {
        float x = 0.0f, y = 0.0f, z = 0.0f;
        float dir_x = 0.0f, dir_z = 1.0f, side = 1.0f;
        FootprintRules::Kind kind = FootprintRules::Kind::Wet;
        float strength = 0.0f; ///< when placed
        float now = 0.0f;      ///< faded (OnFrameEnd)
        double born = 0.0;     ///< seconds since the start
    };

    bool Ready();
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format,
                             vk::ImageAspectFlags aspect);
    /// The scene's size for the image `id` (the reduced one, else the game's render size).
    bool SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced);
    /// A game image's view for the pass, of format `format` (the image's own, or a format of the
    /// same size it may be viewed as): the reduced proxy or the image itself (General layout);
    /// null when it cannot serve (`storage`: it is written as a storage image).
    vk::ImageView ViewOf(VideoCore::ImageId id, vk::Format format, vk::ImageAspectFlags aspect,
                         bool storage, bool write);
    struct CounterStep {
        bool clear = false, copy_back = false;
        u32 slot = 0;
    };
    /// Commands every first pass of a frame records first: the last frame's counters to the host,
    /// this frame's slot cleared.
    CounterStep TakeCounterStep();
    void Edit(std::array<float, 2> jitter);
    void Fail(const char* why);
    void Place(const FootprintRules::Step& step, FootprintRules::Kind kind, float strength, double now);

    static constexpr u32 LineFrames = 600;

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    vk::UniqueDescriptorSetLayout edit_set_layout;
    vk::UniquePipelineLayout edit_layout;
    vk::UniquePipeline edit_pipeline;
    Buffer prints_buffer, counters, readback;
    u64 counter_frame = 0; ///< frame + 1 whose slot was cleared; 0: none yet
    u64 counter_used = 0;  ///< frame + 1 that last used a slot
    std::array<ViewEntry, 8> view_cache{};
    u64 view_uses = 0;
    bool tried = false;
    bool failed = false;
    u64 frame = 0;
    std::chrono::steady_clock::time_point start;

    // The walk, the coat and the prints (OnFrameEnd).
    FootprintRules::Walker walker;
    FootprintRules::Coat coat;
    std::array<Placed, FootprintRules::MaxPrints> placed{};
    u32 placed_count = 0; ///< live prints, the oldest first
    bool hunter_known = false;
    std::array<float, 3> hunter{};
    // This frame, from BeforeDraw.
    VideoCore::ImageId gbuffer_depth{}, gbuffer_material{}, gbuffer_albedo{}, gbuffer_specular{};
    bool gbuffer_seen = false, edit_tried = false;
    bool plane_seen = false; ///< a water plane this frame (plane_y)
    float plane_y = 0.0f;
    bool told_unfit = false, told_position = false, told_unread = false, told_print = false;

    struct Stats {
        u32 frames = 0, read = 0, unread = 0, steps = 0, dry_steps = 0, in_water = 0, glossy = 0;
        u32 jumps = 0, passes = 0, off_screen = 0, no_camera = 0, cannot = 0, lamps_open = 0;
        u32 previews = 0, sense_fresh = 0, planes = 0;
        std::array<u32, 3> by_kind{}; ///< prints placed, by kind
        u64 pass_px = 0;
        float near_m = 0.0f, far_m = 0.0f, low_m = 0.0f, high_m = 0.0f; ///< camera to the hunter
        u32 camera_n = 0;
    } stats;
    std::array<u32, FootprintRules::SlotWords> sense{}; ///< the last fresh host copy
    bool sense_fresh = false;
};

} // namespace Vulkan
''',
    RV + "vk_footprints.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_footprints.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <utility>

#include "bbport_toggles.h"
#include "engine/engine_state.h"
#include "video_core/host_shaders/footprints_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
namespace R = FootprintRules;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto GbufferFormat = vk::Format::eR8G8B8A8Unorm;
/// G-buffer target 2 (albedo) as the game makes it (vk_ssgi.cpp reads it only in this format).
constexpr auto AlbedoSrgbFormat = vk::Format::eR8G8B8A8Srgb;
constexpr vk::DeviceSize SlotBytes = R::SlotWords * 4;
constexpr vk::DeviceSize PrintBytes = R::PrintFloats * 4;
constexpr u64 ProfileRow = 111; ///< EffectPass::Mark: the row "Lighting: footprints"
/// The hunter's box for the sense (and the test view's ring): across and up or down of him.
constexpr float SenseBoxAcrossM = float(FOOTPRINTS_SENSE_RADIUS_M) + 0.05f;
constexpr float SenseBoxUpM = float(FOOTPRINTS_SENSE_HEIGHT_M) + 0.05f;

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.sampler = {}, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet ImageWrite(u32 binding, vk::DescriptorType type,
                                  const vk::DescriptorImageInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type, .pImageInfo = info};
}

vk::WriteDescriptorSet BufferWrite(u32 binding, const vk::DescriptorBufferInfo* info) {
    return {.dstBinding = binding,
            .descriptorCount = 1,
            .descriptorType = vk::DescriptorType::eStorageBuffer,
            .pBufferInfo = info};
}

/// The counters' commands of a frame's first pass (Footprints::TakeCounterStep), then the barrier
/// that lets the pass add to them.
void CounterCommands(vk::CommandBuffer cmd, vk::Buffer counter_buffer, vk::Buffer host, bool clear,
                     bool copy_back, u32 slot) {
    if (!clear) {
        return;
    }
    if (copy_back) {
        cmd.copyBuffer(counter_buffer, host, vk::BufferCopy{(1 - slot) * SlotBytes, 0, SlotBytes});
    }
    cmd.fillBuffer(counter_buffer, slot * SlotBytes, SlotBytes, 0);
    EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                              Compute | vk::PipelineStageFlagBits2::eHost,
                              ReadWrite | vk::AccessFlagBits2::eHostRead);
}

/// What the pass's commands begin with: the game's writes before it (and the reads of the prints by
/// an earlier pass of the frame) are done.
void BeginBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                              Compute | Transfer,
                              ReadWrite | vk::AccessFlagBits2::eTransferRead |
                                  vk::AccessFlagBits2::eTransferWrite);
}

void EndBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands,
                              vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
}

bool Finite3(const float v[3]) {
    return std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]);
}
} // namespace

bool Footprints::Wanted() {
    return R::Load().on;
}

Footprints::Footprints(const Instance& instance_, Scheduler& scheduler_,
                       VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                       SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_},
      runtime{runtime_}, scene_targets{scene_targets_}, camera_motion{camera_motion_},
      start{std::chrono::steady_clock::now()} {
    const auto& k = R::Load();
    BbReport::Printf("Footprints (r111): on%s; a print each %.2f m of the hunter's path, %.2f m to "
                     "the left or right of it in turn, fading over %.0f s; coat %s%s\n",
                     k.show ? ", show (test colours, ring)" : "",
                     double(R::StrideM), double(R::GaitHalfM), double(R::LifeS),
                     k.coat_forced ? R::KindName(k.coat)
                                   : "from the game (wet from a water plane or glossy ground)",
                     k.coat_forced ? " (BB_FOOTPRINTS_COAT, a test: never dries)"
                                   : (k.coat_bad ? " (BB_FOOTPRINTS_COAT names no kind: wet, mud or blood)"
                                                 : ""));
    if (!camera_motion.Enabled()) {
        Fail("it needs the upscaler's camera (BB_UPSCALER=none)");
    }
}

Footprints::~Footprints() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    FreeBuffer(prints_buffer);
    FreeBuffer(counters);
    FreeBuffer(readback);
}

bool Footprints::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host,
                            vk::BufferUsageFlags usage) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = static_cast<VkBufferUsageFlags>(usage),
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (host) {
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags =
            VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    }
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &out.allocation,
                        &info) != VK_SUCCESS) {
        return false;
    }
    out.buffer = raw;
    out.mapped = info.pMappedData;
    return !host || out.mapped;
}

void Footprints::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

bool Footprints::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, GbufferFormat) &&
        EffectPass::Create(instance, edit_set_layout, edit_layout, edit_pipeline,
                           {eSampledImage, eStorageImage, eStorageImage, eStorageImage,
                            eStorageBuffer, eStorageBuffer},
                           sizeof(R::Push), FOOTPRINTS_COMP, "Footprints", true) &&
        MakeBuffer(prints_buffer, R::MaxPrints * PrintBytes, false,
                   vk::BufferUsageFlagBits::eStorageBuffer |
                       vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(counters, R::Slots * SlotBytes, false,
                   vk::BufferUsageFlagBits::eStorageBuffer |
                       vk::BufferUsageFlagBits::eTransferSrc |
                       vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(readback, SlotBytes, true, vk::BufferUsageFlagBits::eTransferDst);
    if (!made) {
        Fail("this GPU cannot run the pass");
        return false;
    }
    std::memset(readback.mapped, 0, SlotBytes);
    return true;
}

void Footprints::Fail(const char* why) {
    failed = true;
    BbReport::Printf("Footprints (r111): off - %s\n", why);
}

vk::ImageView Footprints::CachedView(const VideoCore::Image& image, vk::Format format,
                                     vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid &&
            entry.format == format && entry.aspect == aspect) {
            entry.last_use = ++view_uses;
            return entry.view;
        }
        if (entry.last_use < oldest->last_use) {
            oldest = &entry;
        }
    }
    const auto device = instance.GetDevice();
    if (oldest->view) {
        scheduler.DeferOperation([device, view = oldest->view] { device.destroyImageView(view); });
    }
    *oldest = {
        .image = handle,
        .uid = image.image_uid,
        .format = format,
        .aspect = aspect,
        .view = Check<"create footprints view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool Footprints::SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced) {
    const auto& image = texture_cache.GetImage(id);
    reduced = scene_targets.Reduced() && scene_targets.EligibleScene(image);
    width = image.info.size.width;
    height = image.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    return width >= 16 && height >= 16;
}

vk::ImageView Footprints::ViewOf(VideoCore::ImageId id, vk::Format format,
                                 vk::ImageAspectFlags aspect, bool storage, bool write) {
    auto& image = texture_cache.GetImage(id);
    const auto access = write ? ReadWrite : ShaderRead;
    const auto need = storage ? vk::ImageUsageFlagBits::eStorage : vk::ImageUsageFlagBits::eSampled;
    // (Game images and their reduced proxies are made with eMutableFormat and eExtendedUsage
    // (texture_cache/image.cpp; a proxy copies the image's create info): an R8G8B8A8_SRGB target
    // can be viewed as R8G8B8A8_UNORM storage.)
    if (scene_targets.Reduced() && scene_targets.EligibleScene(image)) {
        VideoCore::ImageViewInfo info;
        info.format = format;
        const auto proxy = scene_targets.Read(id, info, Compute, access);
        return (proxy.usage & need) ? proxy.view : vk::ImageView{};
    }
    if (!(image.usage_flags & need)) {
        return {};
    }
    const auto view = CachedView(image, format, aspect);
    runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, access);
    return view;
}

Footprints::CounterStep Footprints::TakeCounterStep() {
    CounterStep step{};
    step.slot = u32(frame & 1);
    if (counter_frame != frame + 1) {
        counter_frame = frame + 1;
        step.clear = true;
        // the frame before used the other slot: its counts are complete in the queue before this
        step.copy_back = counter_used == frame && frame != 0;
    }
    counter_used = frame + 1;
    return step;
}

void Footprints::BeforeDraw(const GraphicsPipeline& draw_pipeline,
                            const std::array<VideoCore::ImageId, 8>& targets,
                            VideoCore::ImageId depth, bool light_draw, bool lamps_pending,
                            std::array<float, 2> jitter) {
    if (failed) {
        return;
    }
    const u32 mrt = u32(draw_pipeline.GetGraphicsKey().mrt_mask);
    // The G-buffer pass: its depth, gloss (target 1), albedo (target 2), specular colour (target 3).
    if (std::popcount(mrt) >= 5 && depth) {
        // Each G-buffer pass's lighting comes after it (a planar reflection's pass and the world's
        // each get their own pass).
        edit_tried = false;
        gbuffer_seen = true;
        gbuffer_depth = depth;
        gbuffer_material = (mrt & 2u) ? targets[1] : VideoCore::ImageId{};
        gbuffer_albedo = (mrt & 4u) ? targets[2] : VideoCore::ImageId{};
        gbuffer_specular = (mrt & 8u) ? targets[3] : VideoCore::ImageId{};
        return;
    }
    if (!light_draw || !gbuffer_seen || edit_tried) {
        return;
    }
    edit_tried = true;
    // The water plane of this frame's passes so far (the world's pass comes after its mirror image).
    if (float y = 0.0f; camera_motion.MirrorPlane(y)) {
        plane_seen = true;
        plane_y = y;
    }
    if (camera_motion.PreviewFrame()) {
        ++stats.previews;
        return;
    }
    // Lamps apart (vk_point_shadow.h): the open batch's lamps read the G-buffer later; prints laid
    // now would be lit by half of the lamps.
    if (lamps_pending) {
        ++stats.lamps_open;
        return;
    }
    Edit(jitter);
}

void Footprints::Edit(std::array<float, 2> jitter) {
    if (placed_count == 0 && !hunter_known) {
        ++stats.off_screen;
        return; // nothing to lay and no one to sense
    }
    const auto camera = camera_motion.PassMatrices();
    if (!camera.valid || camera.proj[0] == 0.0f || camera.proj[1] == 0.0f) {
        ++stats.no_camera;
        return;
    }
    if (!gbuffer_depth || gbuffer_depth != camera_motion.Depth() || !gbuffer_material ||
        !gbuffer_albedo || !gbuffer_specular) {
        ++stats.cannot;
        return;
    }
    u32 width = 0, height = 0;
    bool reduced = false;
    if (!SceneSize(gbuffer_depth, width, height, reduced)) {
        ++stats.cannot;
        return;
    }
    // Targets 1, 2 and 3 must be RGBA8 (the shader's rgba8 images: 1 and 3 UNORM, 2 UNORM or SRGB,
    // the game's) and stand where the depth does.
    const bool albedo_srgb = texture_cache.GetImage(gbuffer_albedo).info.pixel_format == AlbedoSrgbFormat;
    for (const auto id : {gbuffer_material, gbuffer_albedo, gbuffer_specular}) {
        const auto& image = texture_cache.GetImage(id);
        const bool fits = (image.info.pixel_format == GbufferFormat ||
                           (id == gbuffer_albedo && albedo_srgb)) &&
                          (scene_targets.Reduced() && scene_targets.EligibleScene(image)) == reduced &&
                          image.info.size.width >= (reduced ? 1u : width) &&
                          image.info.size.height >= (reduced ? 1u : height);
        if (!fits) {
            ++stats.cannot;
            if (!told_unfit) {
                told_unfit = true;
                BbReport::Printf("Footprints (r111): left out (first time): G-buffer target 1 format "
                                 "%u, target 2 format %u, target 3 format %u, %ux%u (the pass writes "
                                 "R8G8B8A8_UNORM, 37, target 2 also _SRGB, 43, on a %ux%u scene)\n",
                                 u32(texture_cache.GetImage(gbuffer_material).info.pixel_format),
                                 u32(texture_cache.GetImage(gbuffer_albedo).info.pixel_format),
                                 u32(texture_cache.GetImage(gbuffer_specular).info.pixel_format),
                                 image.info.size.width, image.info.size.height, width, height);
            }
            return;
        }
    }
    // The prints on this pass's screen (their boxes), and the hunter's box for the sense.
    const float fw = float(width), fh = float(height);
    const float cam_x = camera.inv_view[3], cam_y = camera.inv_view[7], cam_z = camera.inv_view[11];
    std::array<float, R::MaxPrints * R::PrintFloats> packed{};
    u32 count = 0;
    R::Rect rect{};
    for (u32 i = 0; i < placed_count; ++i) {
        const Placed& p = placed[i];
        const float dx = p.x - cam_x, dy = p.y - cam_y, dz = p.z - cam_z;
        if (p.now <= 0.0f || dx * dx + dy * dy + dz * dz > R::MaxDistanceM * R::MaxDistanceM) {
            continue;
        }
        const float lo[3] = {p.x - R::PrintBoxAcrossM, p.y - R::PrintBoxUpM, p.z - R::PrintBoxAcrossM};
        const float hi[3] = {p.x + R::PrintBoxAcrossM, p.y + R::PrintBoxUpM, p.z + R::PrintBoxAcrossM};
        const R::Rect r = R::Project(camera.view, camera.proj, fw, fh, jitter, lo, hi);
        if (r.Empty()) {
            continue;
        }
        rect = R::Union(rect, r);
        R::Pack(p.x, p.y, p.z, p.now, p.dir_x, p.dir_z, p.side, p.kind,
                packed.data() + std::size_t(count) * R::PrintFloats);
        ++count;
    }
    bool sensing = false;
    if (hunter_known) {
        const float lo[3] = {hunter[0] - SenseBoxAcrossM, hunter[1] - SenseBoxUpM, hunter[2] - SenseBoxAcrossM};
        const float hi[3] = {hunter[0] + SenseBoxAcrossM, hunter[1] + SenseBoxUpM, hunter[2] + SenseBoxAcrossM};
        const R::Rect r = R::Project(camera.view, camera.proj, fw, fh, jitter, lo, hi);
        sensing = !r.Empty();
        rect = R::Union(rect, r);
    }
    if (rect.Empty()) {
        ++stats.off_screen;
        return;
    }
    if (!Ready()) {
        return;
    }
    const SceneUseScope scene_use{"footprints"};
    scheduler.EndRendering();
    constexpr auto Color = vk::ImageAspectFlagBits::eColor;
    const vk::ImageView depth_view =
        ViewOf(gbuffer_depth, texture_cache.GetImage(gbuffer_depth).info.pixel_format,
               vk::ImageAspectFlagBits::eDepth, false, false);
    const vk::ImageView material_view = ViewOf(gbuffer_material, GbufferFormat, Color, true, true);
    // (an SRGB albedo through a UNORM view: the shader decodes and encodes, FOOTPRINTS_FLAG_SRGB)
    const vk::ImageView albedo_view = ViewOf(gbuffer_albedo, GbufferFormat, Color, true, true);
    const vk::ImageView specular_view = ViewOf(gbuffer_specular, GbufferFormat, Color, true, true);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!depth_view || !material_view || !albedo_view || !specular_view) {
        ++stats.cannot;
        return;
    }
    const auto& k = R::Load();
    const CounterStep step = TakeCounterStep();
    R::Push push{};
    push.inv_view = camera.inv_view;
    push.proj = camera.proj;
    push.size = {fw, fh};
    push.jitter = jitter;
    push.hunter = {hunter[0], hunter[1], hunter[2], 0.0f};
    push.count = count;
    push.flags = R::Flags(k, sensing, step.slot, albedo_srgb);
    push.stamp = u32(frame + 1);
    const u32 gx0 = u32(rect.x0) / R::Group, gy0 = u32(rect.y0) / R::Group;
    const u32 gx1 = (u32(rect.x1) + R::Group - 1) / R::Group;
    const u32 gy1 = (u32(rect.y1) + R::Group - 1) / R::Group;
    ++stats.passes;
    stats.pass_px += u64(rect.x1 - rect.x0) * u64(rect.y1 - rect.y0);
    EffectPass::Mark(ProfileRow, "footprints", true);
    scheduler.RecordCrumb(
        {.name = "footprints"},
        [push, step, packed, count, gx0, gy0, gx1, gy1, depth_view, material_view, albedo_view,
         specular_view, prints = prints_buffer.buffer, counter_buffer = counters.buffer,
         host = readback.buffer, pass_pipeline = *edit_pipeline,
         pass_layout = *edit_layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            CounterCommands(cmd, counter_buffer, host, step.clear, step.copy_back, step.slot);
            if (count != 0) {
                cmd.updateBuffer(prints, 0, vk::DeviceSize(count) * PrintBytes, packed.data());
                EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                                          Compute, ShaderRead);
            }
            using enum vk::DescriptorType;
            const std::array infos{Info(depth_view), Info(material_view), Info(albedo_view),
                                   Info(specular_view)};
            const vk::DescriptorBufferInfo prints_info{prints, 0, R::MaxPrints * PrintBytes};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, R::Slots * SlotBytes};
            const std::array writes{ImageWrite(0, eSampledImage, &infos[0]),
                                    ImageWrite(1, eStorageImage, &infos[1]),
                                    ImageWrite(2, eStorageImage, &infos[2]),
                                    ImageWrite(3, eStorageImage, &infos[3]),
                                    BufferWrite(4, &prints_info), BufferWrite(5, &counter_info)};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            cmd.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
            EndBarrier(cmd);
        });
}

void Footprints::Place(const R::Step& s, R::Kind kind, float strength, double now) {
    if (placed_count == placed.size()) {
        // full: the oldest goes
        std::move(placed.begin() + 1, placed.end(), placed.begin());
        --placed_count;
    }
    placed[placed_count++] = {.x = s.x,
                              .y = s.y,
                              .z = s.z,
                              .dir_x = s.dir_x,
                              .dir_z = s.dir_z,
                              .side = s.side,
                              .kind = kind,
                              .strength = strength,
                              .now = strength,
                              .born = now};
    ++stats.by_kind[std::min<u32>(u32(kind), 2u)];
    if (!told_print) {
        told_print = true;
        BbReport::Printf("Footprints (r111): first print at frame %llu: %s, strength %.2f, at %.2f %.2f "
                         "%.2f, heading %.2f %.2f, %s foot\n",
                         static_cast<unsigned long long>(frame), R::KindName(kind), double(strength),
                         double(s.x), double(s.y), double(s.z), double(s.dir_x), double(s.dir_z),
                         s.side > 0.0f ? "one" : "the other");
    }
}

void Footprints::OnFrameEnd() {
    gbuffer_seen = edit_tried = false;
    gbuffer_depth = gbuffer_material = gbuffer_albedo = gbuffer_specular = {};
    const bool plane = std::exchange(plane_seen, false);
    ++frame;
    if (failed) {
        return;
    }
    const auto& k = R::Load();
    const double now =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    ++stats.frames;
    stats.planes += plane ? 1 : 0;
    // The sense of a recent frame (the host copy; no fence is waited for: it may be a few frames old,
    // its stamp says how old).
    std::array<u32, R::SlotWords> c{};
    if (readback.mapped) {
        std::memcpy(c.data(), readback.mapped, sizeof(c));
    }
    const bool fresh = c[R::WordStamp] != 0 && u64(c[R::WordStamp]) + R::SenseFreshFrames >= frame;
    if (fresh) {
        sense = c;
        sense_fresh = true;
        ++stats.sense_fresh;
    }
    const bool glossy = fresh && R::GlossyGround(c[R::WordGroundN], c[R::WordWetN]);
    // The hunter.
    float pos[3] = {};
    hunter_known = BbEngine::world_player_position(pos) && Finite3(pos);
    if (!hunter_known) {
        ++stats.unread;
        if (!told_unread && stats.unread == 120) {
            told_unread = true;
            BbReport::Printf("Footprints (r111): the hunter's position cannot be read (the engine "
                             "features are off, or not in a level yet): no prints\n");
        }
    } else {
        ++stats.read;
        hunter = {pos[0], pos[1], pos[2]};
        const auto cam = camera_motion.CameraMatrices();
        if (cam.valid) {
            const float dx = cam.inv_view[3] - pos[0], dy = cam.inv_view[7] - pos[1];
            const float dz = cam.inv_view[11] - pos[2];
            const float d = std::sqrt(dx * dx + dy * dy + dz * dz);
            stats.near_m = stats.camera_n ? std::min(stats.near_m, d) : d;
            stats.far_m = stats.camera_n ? std::max(stats.far_m, d) : d;
            stats.low_m = stats.camera_n ? std::min(stats.low_m, dy) : dy;
            stats.high_m = stats.camera_n ? std::max(stats.high_m, dy) : dy;
            ++stats.camera_n;
            if (!told_position) {
                told_position = true;
                BbReport::Printf("Footprints (r111): first hunter position %.2f %.2f %.2f, camera at %.2f "
                                 "%.2f %.2f: %.2f m away, %.2f m above his position (the same space "
                                 "when about 1.5 to 6 m away and 0.5 to 3 m above)\n",
                                 double(pos[0]), double(pos[1]), double(pos[2]), double(cam.inv_view[3]),
                                 double(cam.inv_view[7]), double(cam.inv_view[11]), double(d), double(dy));
            }
        }
        const bool in_water = R::InWater(plane, plane_y, pos[1]);
        stats.in_water += in_water ? 1 : 0;
        stats.glossy += glossy ? 1 : 0;
        R::Soak(coat, k, in_water, glossy);
        const R::Step s = R::Walk(walker, pos);
        if (s.step) {
            ++stats.steps;
            R::Kind kind = R::Kind::Wet;
            const float strength = R::TakeStep(coat, k, in_water, kind);
            if (strength > 0.0f) {
                Place(s, kind, strength, now);
            } else {
                ++stats.dry_steps;
            }
        }
    }
    stats.jumps = walker.jumps;
    // Fading: a print whose strength is gone is dropped (the oldest come first).
    u32 kept = 0;
    for (u32 i = 0; i < placed_count; ++i) {
        Placed p = placed[i];
        p.now = p.strength * R::Fade(now - p.born);
        if (p.now > 1.0f / 64.0f) {
            placed[kept++] = p;
        }
    }
    placed_count = kept;
    if (stats.frames < LineFrames) {
        return;
    }
    // (Five lines, each under 300 characters: the slot runner keeps 300 of a log line.)
    BbReport::Printf("Footprints (r111): %u frames, hunter read in %u (at %.2f %.2f %.2f; camera %.2f to "
                     "%.2f m away, %.2f to %.2f m above his position); %u steps: %u prints placed "
                     "(%u wet, %u mud, %u blood), %u dry\n",
                     stats.frames, stats.read, double(hunter[0]), double(hunter[1]), double(hunter[2]),
                     double(stats.near_m), double(stats.far_m), double(stats.low_m), double(stats.high_m),
                     stats.steps, stats.by_kind[0] + stats.by_kind[1] + stats.by_kind[2],
                     stats.by_kind[0], stats.by_kind[1], stats.by_kind[2], stats.dry_steps);
    BbReport::Printf("Footprints (r111): frames %u in water, %u on glossy ground, %u with a water "
                     "plane; %u path restarts; %u live; coat %s %.2f; %u passes (%.0f px each)\n",
                     stats.in_water, stats.glossy, stats.planes, stats.jumps, placed_count,
                     R::KindName(coat.kind), double(coat.amount), stats.passes,
                     stats.passes ? double(stats.pass_px) / double(stats.passes) : 0.0);
    BbReport::Printf("Footprints (r111): skipped %u off screen, %u no camera, %u unfit, %u lamps "
                     "open, %u previews\n",
                     stats.off_screen, stats.no_camera, stats.cannot, stats.lamps_open, stats.previews);
    const auto& s = sense;
    const u32 ground = s[R::WordGroundN];
    const double g = ground ? 1.0 / (255.0 * double(ground)) : 0.0;
    char water[48] = "none";
    if (plane_y != 0.0f) {
        std::snprintf(water, sizeof(water), "y %.2f (last seen)", double(plane_y));
    }
    BbReport::Printf("Footprints (r111): recent frame (%s, %u fresh): %u print pixels of %u looked at; "
                     "around the feet %u up-facing px, mean height %+.3f m (under -0.25 m %u, -0.25 "
                     "to -0.08 %u, band %u, 0.08 to 0.25 %u, above %u)\n",
                     sense_fresh ? "read back" : "none yet", stats.sense_fresh, s[R::WordPrintPx],
                     s[R::WordSeenPx], s[R::WordSenseN],
                     s[R::WordSenseN] ? double(s[R::WordSenseDyMm]) / (1000.0 * double(s[R::WordSenseN])) -
                                            double(FOOTPRINTS_SENSE_HEIGHT_M)
                                      : 0.0,
                     s[R::WordBinLow], s[R::WordBinBelow], ground, s[R::WordBinAbove],
                     s[R::WordBinHigh]);
    BbReport::Printf("Footprints (r111): ground band gloss mean %.3f, %u at 0.88 or more (%u needed of "
                     "%u); linear albedo mean %.3f %.3f %.3f; ring %u px; water plane %s\n",
                     double(s[R::WordGlossSum]) * g, s[R::WordWetN],
                     (ground * R::WetSharePercent + 99u) / 100u, ground,
                     double(s[R::WordAlbedoR]) * g, double(s[R::WordAlbedoG]) * g,
                     double(s[R::WordAlbedoB]) * g, s[R::WordRingPx], water);
    stats = {};
}

} // namespace Vulkan
''',
    HS + "footprints.comp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r111_footprints): the hunter's footprints laid into the game's G-buffer, at the first light
// draw after each G-buffer pass (renderer_vulkan/vk_footprints.cpp records it, footprints.h has the
// rules), so the game's own sun or moon, its lamps and its reflections light them: a wet print is
// darker and glossier than the ground, a blood print dark red and glossy, a mud print brown.
// One build. It runs over the pixels of the boxes of this pass's prints and of the ground around the
// hunter (dispatched with a base: gl_GlobalInvocationID is the pixel). For each pixel with depth:
// its world point from the depth and this pass's camera, its up-facing share from the depth of its
// right (or left) and lower (or upper) neighbours; around the hunter's position the up-facing ground
// is counted (the sense: its height, gloss and albedo, before any print is laid on it); then each
// print within FOOTPRINTS_PRINT_BAND_M of the point's height weighs the point by its sole's shape
// and the print's strength (faded on the host), times the up-facing share, and the strongest print
// of each kind changes the material.
#version 450
#extension GL_GOOGLE_include_directive : require
#extension GL_EXT_samplerless_texture_functions : require
#include "footprints_layout.h"

layout(local_size_x = FOOTPRINTS_GROUP, local_size_y = FOOTPRINTS_GROUP, local_size_z = 1) in;

// FootprintRules::Push, word for word (28 words, 112 bytes).
layout(push_constant) uniform Push {
    vec4 inv_view[3]; // this pass's view to world, rows
    vec4 proj;        // x scale, y scale (signed: ndc +y down), z scale, z offset
    vec2 size;        // pixels
    vec2 jitter;      // render pixels
    vec4 hunter;      // his position (x, y, z), 0
    uint print_count;
    uint flags;       // FOOTPRINTS_FLAG_*
    uint stamp;       // the host's frame + 1
    uint pad;
};

layout(binding = 0) uniform texture2D depth_tex;         // the G-buffer pass's depth
layout(binding = 1, rgba8) uniform image2D material_img; // G-buffer target 1: .r gloss
layout(binding = 2, rgba8) uniform image2D albedo_img;   // G-buffer target 2: .rgb albedo
                                                         // (sRGB bytes with FOOTPRINTS_FLAG_SRGB)
layout(binding = 3, rgba8) uniform image2D specular_img; // G-buffer target 3: .rgb root of f0
struct Print {
    vec4 a; // x, y, z, strength
    vec4 b; // dir x, dir z, side, kind
};
layout(binding = 4, std430) readonly buffer Prints {
    Print prints[];
};
layout(binding = 5, std430) buffer Counters {
    uint counts[];
};

// View depth (metres, in front: positive) from a depth value, as camera_motion.comp: depth =
// zs + zo / z; 0 for the sky or no depth.
float ViewZ(float depth) {
    if (!(depth > 0.0) || depth >= 1.0) {
        return 0.0;
    }
    return proj.w / min(depth - proj.z, -1e-8);
}

// The world point of pixel `p` at view depth `z`.
vec3 World(ivec2 p, float z) {
    const vec2 uv = (vec2(p) + 0.5) / size - jitter / size;
    const vec2 ndc = uv * 2.0 - 1.0;
    const vec4 view = vec4(ndc.x * z / proj.x, ndc.y * z / proj.y, z, 1.0);
    return vec3(dot(inv_view[0], view), dot(inv_view[1], view), dot(inv_view[2], view));
}

// The world point of a neighbour pixel; false for the sky.
bool Neighbour(ivec2 q, out vec3 w) {
    const float z = ViewZ(texelFetch(depth_tex, q, 0).x);
    w = World(q, z);
    return z > 0.0;
}

// 0..1: the sole's shape at (u along the step, v across it, outward positive).
float Ellipse(vec2 d, vec2 r) {
    return 1.0 - smoothstep(FOOTPRINTS_EDGE, 1.0, length(d / r));
}
float Sole(float u, float v) {
    const float fore = Ellipse(vec2(u - FOOTPRINTS_FORE_U, v), vec2(FOOTPRINTS_FORE_RU, FOOTPRINTS_FORE_RV));
    const float heel = Ellipse(vec2(u - FOOTPRINTS_HEEL_U, v), vec2(FOOTPRINTS_HEEL_RU, FOOTPRINTS_HEEL_RV));
    return max(fore, heel);
}

// The sRGB transfer (the albedo target is R8G8B8A8_SRGB, bound through a UNORM view): the colour
// rules work on linear albedo, as the game's lighting reads it.
vec3 ToLinear(vec3 c) {
    c = clamp(c, 0.0, 1.0);
    return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), greaterThan(c, vec3(0.04045)));
}
vec3 ToSrgb(vec3 c) {
    c = clamp(c, 0.0, 1.0);
    return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, greaterThan(c, vec3(0.0031308)));
}

// 0..1 from a world point's cell (2.5 cm): the uneven edge of a print.
float Grain(vec2 xz) {
    uvec2 c = uvec2(ivec2(floor(xz * 40.0)) + ivec2(32768));
    uint h = c.x * 0x8da6b343u ^ c.y * 0xd8163841u;
    h ^= h >> 13u;
    h *= 0x5bd1e995u;
    h ^= h >> 15u;
    return float(h & 0xffffu) / 65535.0;
}

// The group's counts, then one atomic per word for the group: sums add, STAMP is a maximum.
shared uint group_counts[FOOTPRINTS_SLOT_WORDS];
void AddCounts(uint n[FOOTPRINTS_SLOT_WORDS]) {
    if (gl_LocalInvocationIndex < FOOTPRINTS_SLOT_WORDS) {
        group_counts[gl_LocalInvocationIndex] = 0u;
    }
    memoryBarrierShared();
    barrier();
    for (uint i = 0u; i < FOOTPRINTS_SLOT_WORDS; ++i) {
        if (n[i] != 0u) {
            if (i == FOOTPRINTS_WORD_STAMP) {
                atomicMax(group_counts[i], n[i]);
            } else {
                atomicAdd(group_counts[i], n[i]);
            }
        }
    }
    memoryBarrierShared();
    barrier();
    const uint w = gl_LocalInvocationIndex;
    if (w < FOOTPRINTS_SLOT_WORDS && group_counts[w] != 0u) {
        const uint at = ((flags & FOOTPRINTS_FLAG_SLOT) != 0u ? FOOTPRINTS_SLOT_WORDS : 0u) + w;
        if (w == FOOTPRINTS_WORD_STAMP) {
            atomicMax(counts[at], group_counts[w]);
        } else {
            atomicAdd(counts[at], group_counts[w]);
        }
    }
}

void main() {
    uint n[FOOTPRINTS_SLOT_WORDS];
    for (uint i = 0u; i < FOOTPRINTS_SLOT_WORDS; ++i) {
        n[i] = 0u;
    }
    n[FOOTPRINTS_WORD_STAMP] = stamp;
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    const ivec2 last = ivec2(size) - 1;
    const bool inside = p.x <= last.x && p.y <= last.y;
    const float z = inside ? ViewZ(texelFetch(depth_tex, p, 0).x) : 0.0;
    if (z > 0.0) {
        n[FOOTPRINTS_WORD_SEEN_PX] = 1u;
        const vec3 w = World(p, z);
        // The up-facing share from two neighbours (the right or left one, the lower or upper one).
        const ivec2 qx = ivec2(p.x < last.x ? p.x + 1 : p.x - 1, p.y);
        const ivec2 qy = ivec2(p.x, p.y < last.y ? p.y + 1 : p.y - 1);
        vec3 wx, wy;
        float up = 0.0;
        if (Neighbour(qx, wx) && Neighbour(qy, wy)) {
            const vec3 c = cross(wx - w, wy - w);
            const float l = length(c);
            up = l > 1e-12 ? abs(c.y) / l : 0.0;
        }
        vec4 m = imageLoad(material_img, p);
        vec4 a = imageLoad(albedo_img, p);
        const bool srgb = (flags & FOOTPRINTS_FLAG_SRGB) != 0u;
        if (srgb) {
            a.rgb = ToLinear(a.rgb);
        }
        bool changed = false;
        const bool show = (flags & FOOTPRINTS_FLAG_SHOW) != 0u;
        // The sense around the hunter's position (before any print changes the pixel).
        if ((flags & FOOTPRINTS_FLAG_HUNTER) != 0u) {
            const vec2 h = w.xz - hunter.xz;
            const float across = length(h);
            const float dy = w.y - hunter.y;
            if (across <= FOOTPRINTS_SENSE_RADIUS_M && abs(dy) <= FOOTPRINTS_SENSE_HEIGHT_M &&
                up >= FOOTPRINTS_UP_MIN) {
                n[FOOTPRINTS_WORD_SENSE_N] = 1u;
                n[FOOTPRINTS_WORD_SENSE_DY_MM] = uint((dy + FOOTPRINTS_SENSE_HEIGHT_M) * 1000.0 + 0.5);
                if (dy < -FOOTPRINTS_BIN_M) {
                    n[FOOTPRINTS_WORD_BIN_LOW] = 1u;
                } else if (dy < -FOOTPRINTS_GROUND_M) {
                    n[FOOTPRINTS_WORD_BIN_BELOW] = 1u;
                } else if (dy <= FOOTPRINTS_GROUND_M) {
                    n[FOOTPRINTS_WORD_GROUND_N] = 1u;
                    n[FOOTPRINTS_WORD_GLOSS_SUM] = uint(clamp(m.r, 0.0, 1.0) * 255.0 + 0.5);
                    n[FOOTPRINTS_WORD_WET_N] = m.r >= FOOTPRINTS_PUDDLE_GLOSS ? 1u : 0u;
                    n[FOOTPRINTS_WORD_ALBEDO_R] = uint(clamp(a.r, 0.0, 1.0) * 255.0 + 0.5);
                    n[FOOTPRINTS_WORD_ALBEDO_G] = uint(clamp(a.g, 0.0, 1.0) * 255.0 + 0.5);
                    n[FOOTPRINTS_WORD_ALBEDO_B] = uint(clamp(a.b, 0.0, 1.0) * 255.0 + 0.5);
                    if (show) {
                        a.rgb = mix(a.rgb, vec3(1.0, 0.9, 0.1), 0.35);
                        changed = true;
                    }
                } else if (dy <= FOOTPRINTS_BIN_M) {
                    n[FOOTPRINTS_WORD_BIN_ABOVE] = 1u;
                } else {
                    n[FOOTPRINTS_WORD_BIN_HIGH] = 1u;
                }
            }
            if (show && across >= FOOTPRINTS_RING_IN_M && across <= FOOTPRINTS_RING_OUT_M &&
                abs(dy) <= FOOTPRINTS_SENSE_HEIGHT_M) {
                a.rgb = vec3(1.0, 0.0, 1.0);
                changed = true;
                n[FOOTPRINTS_WORD_RING_PX] = 1u;
            }
        }
        // The prints: the strongest of each kind here.
        float weight[FOOTPRINTS_KINDS] = float[FOOTPRINTS_KINDS](0.0, 0.0, 0.0);
        const uint count = min(print_count, FOOTPRINTS_MAX_PRINTS);
        for (uint i = 0u; i < count; ++i) {
            const Print pr = prints[i];
            const vec3 l = w - pr.a.xyz;
            if (abs(l.y) > FOOTPRINTS_PRINT_BAND_M) {
                continue;
            }
            const vec2 dir = pr.b.xy;
            const float u = dot(l.xz, dir);
            const float v = dot(l.xz, vec2(-dir.y, dir.x)) * pr.b.z;
            const float s = Sole(u, v) * pr.a.w;
            const uint kind = min(uint(pr.b.w + 0.5), FOOTPRINTS_KINDS - 1u);
            weight[kind] = max(weight[kind], s);
        }
        const float face = smoothstep(FOOTPRINTS_UP_MIN, FOOTPRINTS_UP_FULL, up);
        const float grain = 0.8 + 0.2 * Grain(w.xz);
        const float wet = clamp(weight[FOOTPRINTS_KIND_WET] * face * grain, 0.0, 1.0);
        const float mud = clamp(weight[FOOTPRINTS_KIND_MUD] * face * grain, 0.0, 1.0);
        const float blood = clamp(weight[FOOTPRINTS_KIND_BLOOD] * face * grain, 0.0, 1.0);
        if (max(wet, max(mud, blood)) > 1.0 / 64.0) {
            n[FOOTPRINTS_WORD_PRINT_PX] = 1u;
            vec4 s = imageLoad(specular_img, p);
            if (show) {
                // Test view: each kind in its colour, over the albedo.
                a.rgb = mix(a.rgb, vec3(0.0, 0.9, 1.0), 0.85 * wet);
                a.rgb = mix(a.rgb, vec3(1.0, 0.55, 0.1), 0.85 * mud);
                a.rgb = mix(a.rgb, vec3(1.0, 0.05, 0.05), 0.85 * blood);
            } else {
                if (wet > 0.0) {
                    a.rgb *= 1.0 - FOOTPRINTS_WET_DARKEN * wet;
                    m.r = max(m.r, mix(m.r, FOOTPRINTS_WET_GLOSS, wet));
                    s.rgb = max(s.rgb, mix(s.rgb, vec3(FOOTPRINTS_WET_SPEC_ROOT), wet));
                }
                if (mud > 0.0) {
                    const vec3 mud_albedo = vec3(FOOTPRINTS_MUD_ALBEDO_R, FOOTPRINTS_MUD_ALBEDO_G,
                                                 FOOTPRINTS_MUD_ALBEDO_B);
                    a.rgb = mix(a.rgb, mud_albedo, FOOTPRINTS_MUD_COVER * mud);
                    m.r = mix(m.r, FOOTPRINTS_MUD_GLOSS, mud);
                }
                if (blood > 0.0) {
                    const vec3 blood_albedo = vec3(FOOTPRINTS_BLOOD_ALBEDO_R, FOOTPRINTS_BLOOD_ALBEDO_G,
                                                   FOOTPRINTS_BLOOD_ALBEDO_B);
                    a.rgb = mix(a.rgb, blood_albedo, FOOTPRINTS_BLOOD_COVER * blood);
                    m.r = max(m.r, mix(m.r, FOOTPRINTS_BLOOD_GLOSS, blood));
                    s.rgb = max(s.rgb, mix(s.rgb, vec3(FOOTPRINTS_WET_SPEC_ROOT), blood));
                }
                imageStore(material_img, p, m);
                imageStore(specular_img, p, s);
            }
            changed = true;
        }
        if (changed) {
            if (srgb) {
                a.rgb = ToSrgb(a.rgb);
            }
            imageStore(albedo_img, p, a);
        }
    }
    AddCounts(n);
}
''',
    HS + "footprints_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r111_footprints): what the footprints' shader (footprints.comp) and the engine
// (renderer_vulkan/footprints.h, which ties these to its constants with static_asserts) share.
// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and
// C++ includes it as it is, so one text holds every number both sides use.
#ifndef FOOTPRINTS_LAYOUT_H
#define FOOTPRINTS_LAYOUT_H

// Pixels a side of one workgroup (FootprintRules::Group).
#define FOOTPRINTS_GROUP 8u
// Prints the shader reads at most (the host sends only those whose box is on this pass's screen).
#define FOOTPRINTS_MAX_PRINTS 48u
// The push word `flags`: the test view (BB_FOOTPRINTS=show); the counter slot of this frame (0 or
// 1); the hunter's position in `hunter` is known (the sense around the feet runs, and the test view
// draws its ring); G-buffer target 2 is R8G8B8A8_SRGB, bound through an R8G8B8A8_UNORM view (the
// shader decodes it to linear and encodes what it writes back).
#define FOOTPRINTS_FLAG_SHOW 1u
#define FOOTPRINTS_FLAG_SLOT 2u
#define FOOTPRINTS_FLAG_HUNTER 4u
#define FOOTPRINTS_FLAG_SRGB 8u
// A print's kind (the print's b.w): what the feet stepped in.
#define FOOTPRINTS_KIND_WET 0u
#define FOOTPRINTS_KIND_MUD 1u
#define FOOTPRINTS_KIND_BLOOD 2u
#define FOOTPRINTS_KINDS 3u
// A counter slot's words. All sums (each group adds its own with one atomic a word), except STAMP,
// a maximum: the push word `stamp` of the pass that wrote the slot (the host's frame + 1).
#define FOOTPRINTS_SLOT_WORDS 16u
// Pixels a print changed (weight above 1/64), pixels the pass looked at.
#define FOOTPRINTS_WORD_PRINT_PX 0u
#define FOOTPRINTS_WORD_SEEN_PX 1u
// Around the hunter (within FOOTPRINTS_SENSE_RADIUS_M across, FOOTPRINTS_SENSE_HEIGHT_M up or
// down of his position's height), up-facing pixels: their count; the sum of (height above his
// position + FOOTPRINTS_SENSE_HEIGHT_M) in millimetres; the count by that height: below
// -FOOTPRINTS_BIN_M, below -FOOTPRINTS_GROUND_M, within FOOTPRINTS_GROUND_M (the ground band),
// up to FOOTPRINTS_BIN_M, above it.
#define FOOTPRINTS_WORD_SENSE_N 2u
#define FOOTPRINTS_WORD_SENSE_DY_MM 3u
#define FOOTPRINTS_WORD_BIN_LOW 4u
#define FOOTPRINTS_WORD_BIN_BELOW 5u
#define FOOTPRINTS_WORD_GROUND_N 6u
#define FOOTPRINTS_WORD_BIN_ABOVE 7u
#define FOOTPRINTS_WORD_BIN_HIGH 8u
// The ground band's pixels, before any print is laid on them: the sum of the gloss (G-buffer target
// 1, red) times 255; how many have a gloss of at least FOOTPRINTS_PUDDLE_GLOSS; the sums of the
// linear albedo (G-buffer target 2, decoded from sRGB when it is so) red, green and blue times 255.
#define FOOTPRINTS_WORD_GLOSS_SUM 9u
#define FOOTPRINTS_WORD_WET_N 10u
#define FOOTPRINTS_WORD_ALBEDO_R 11u
#define FOOTPRINTS_WORD_ALBEDO_G 12u
#define FOOTPRINTS_WORD_ALBEDO_B 13u
#define FOOTPRINTS_WORD_STAMP 14u
#define FOOTPRINTS_WORD_RING_PX 15u
// The sense around the feet (metres).
#define FOOTPRINTS_SENSE_RADIUS_M 0.45
#define FOOTPRINTS_SENSE_HEIGHT_M 1.0
#define FOOTPRINTS_BIN_M 0.25
#define FOOTPRINTS_GROUND_M 0.08
// Gloss a puddle has at least (exponent 2^(13 g) in the game's lighting).
#define FOOTPRINTS_PUDDLE_GLOSS 0.88
// A pixel is up-facing when its normal (from the depth of its neighbours) has an upward share of at
// least FOOTPRINTS_UP_MIN; a print's weight grows from 0 at FOOTPRINTS_UP_MIN to full at
// FOOTPRINTS_UP_FULL (walls and the hunter's legs get none).
#define FOOTPRINTS_UP_MIN 0.6
#define FOOTPRINTS_UP_FULL 0.85
// A print lies on the ground within this height of its centre (metres): a print placed in the air
// (a jump) or on another level draws nothing.
#define FOOTPRINTS_PRINT_BAND_M 0.12
// The sole (metres, along the step u, across v): the fore part an ellipse at u FORE_U with half
// axes FORE_RU x FORE_RV, the heel one at u HEEL_U with HEEL_RU x HEEL_RV; edges soft from
// FOOTPRINTS_EDGE of the radius out.
#define FOOTPRINTS_FORE_U 0.05
#define FOOTPRINTS_FORE_RU 0.075
#define FOOTPRINTS_FORE_RV 0.048
#define FOOTPRINTS_HEEL_U -0.09
#define FOOTPRINTS_HEEL_RU 0.048
#define FOOTPRINTS_HEEL_RV 0.038
#define FOOTPRINTS_EDGE 0.7
// What a fully weighted print does to the G-buffer (albedo values linear). Wet: the albedo
// darkened by WET_DARKEN (review 2026-11-15: 0.5, so that it reads in a still); the
// gloss raised toward WET_GLOSS and the root of the specular colour (target 3, f0 = rgb^2) toward
// WET_SPEC_ROOT (a water film, f0 0.04; never lowered). Mud: the albedo toward MUD_ALBEDO by
// MUD_COVER; the gloss toward MUD_GLOSS. Blood: the albedo toward BLOOD_ALBEDO by BLOOD_COVER; the
// gloss raised toward BLOOD_GLOSS, the specular colour as wet (never lowered).
#define FOOTPRINTS_WET_DARKEN 0.5
#define FOOTPRINTS_WET_GLOSS 0.62
#define FOOTPRINTS_WET_SPEC_ROOT 0.2
#define FOOTPRINTS_MUD_ALBEDO_R 0.2
#define FOOTPRINTS_MUD_ALBEDO_G 0.14
#define FOOTPRINTS_MUD_ALBEDO_B 0.08
#define FOOTPRINTS_MUD_COVER 0.8
#define FOOTPRINTS_MUD_GLOSS 0.42
#define FOOTPRINTS_BLOOD_ALBEDO_R 0.3
#define FOOTPRINTS_BLOOD_ALBEDO_G 0.02
#define FOOTPRINTS_BLOOD_ALBEDO_B 0.015
#define FOOTPRINTS_BLOOD_COVER 0.85
#define FOOTPRINTS_BLOOD_GLOSS 0.58
// Test view: the ring around the hunter's position (metres from it, across).
#define FOOTPRINTS_RING_IN_M 0.3
#define FOOTPRINTS_RING_OUT_M 0.34

#endif
''',
    "engine/tests/test_footprints.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r111_footprints): the footprints' knobs, walk, coat, fade and screen boxes (footprints.h).
// Pure: no Vulkan. Built and run by engine/build.sh --test and the CMake target footprints-test.
#undef NDEBUG
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include "gpu/shadps4/video_core/renderer_vulkan/footprints.h"

using namespace Vulkan::FootprintRules;

namespace {
bool Near(double a, double b, double eps = 1e-4) {
    return std::abs(a - b) <= eps;
}
} // namespace

int main() {
    // Knobs.
    {
        assert(!Read(nullptr, nullptr).on);
        assert(!Read("", nullptr).on && !Read("0", nullptr).on && !Read("yes", nullptr).on);
        assert(!Read("11", nullptr).on && !Read("shows", nullptr).on);
        const Knobs on = Read(" 1 ", nullptr);
        assert(on.on && !on.show && !on.coat_forced && !on.coat_bad);
        const Knobs show = Read("show", "");
        assert(show.on && show.show && !show.coat_forced && !show.coat_bad);
        const Knobs blood = Read("1", "blood");
        assert(blood.coat_forced && blood.coat == Kind::Blood);
        assert(Read("1", " mud").coat == Kind::Mud && Read("1", "wet ").coat_forced);
        const Knobs bad = Read("1", "lava");
        assert(!bad.coat_forced && bad.coat_bad);
        assert(Flags(show, true, 1, false) == (FlagShow | FlagSlot | FlagHunter));
        assert(Flags(on, false, 0, false) == 0u);
        assert(Flags(on, false, 0, true) == FlagSrgb);
    }
    // The walk: straight along +z at 5 cm a frame, a print each 0.75 m, sides in turn.
    {
        Walker w;
        float pos[3] = {1.0f, 2.0f, 3.0f};
        assert(!Walk(w, pos).step); // the first position starts the path
        std::array<Step, 8> steps{};
        int n = 0;
        for (int f = 1; f <= 64; ++f) { // 3.2 m: strides end near 0.75, 1.5, 2.25 and 3 m
            pos[2] = 3.0f + 0.05f * float(f);
            const Step s = Walk(w, pos);
            if (s.step) {
                assert(n < 8);
                steps[std::size_t(n++)] = s;
            }
        }
        assert(n == 4);
        for (int i = 0; i < n; ++i) {
            const Step& s = steps[std::size_t(i)];
            assert(Near(s.dir_x, 0.0) && Near(s.dir_z, 1.0));
            assert(Near(s.side, i % 2 == 0 ? 1.0 : -1.0));
            // to the side (-dir_z, dir_x) * side: x moves by -side * GaitHalfM
            assert(Near(s.x, 1.0 - s.side * GaitHalfM) && Near(s.y, 2.0));
            assert(Near(s.z, 3.0 + 0.75 * (i + 1), 0.051)); // (a float sum may take one frame more)
        }
        // A warp starts the path anew: no print, the walk counts on from there.
        pos[0] += 50.0f;
        assert(!Walk(w, pos).step && w.jumps == 1);
        pos[2] += 0.7f; // under a stride since the warp
        assert(!Walk(w, pos).step);
        // A fall of more than DropM in one frame too.
        pos[1] -= 1.5f;
        assert(!Walk(w, pos).step && w.jumps == 2);
        // A NaN position.
        float bad[3] = {NAN, 0.0f, 0.0f};
        assert(!Walk(w, bad).step && w.jumps == 3);
    }
    // A fast frame (two strides at once) places one print and counts on from 0.
    {
        Walker w;
        float pos[3] = {0.0f, 0.0f, 0.0f};
        Walk(w, pos);
        pos[0] = 1.6f;
        const Step s = Walk(w, pos);
        assert(s.step && Near(s.dir_x, 1.0) && Near(s.dir_z, 0.0) && w.acc == 0.0f);
    }
    // The coat: water or a puddle soak the feet; each step leaves DryPerStep; dry below MinCoat.
    {
        const Knobs k = Read("1", nullptr);
        Coat c;
        Kind kind = Kind::Blood;
        assert(TakeStep(c, k, false, kind) == 0.0f); // dry from the start
        Soak(c, k, true, false);
        assert(c.amount == 1.0f && c.kind == Kind::Wet);
        assert(TakeStep(c, k, true, kind) == 0.0f && c.amount == 1.0f); // in the water: nothing
        int prints = 0;
        float last = 2.0f;
        for (int i = 0; i < 40; ++i) {
            const float s = TakeStep(c, k, false, kind);
            if (s == 0.0f) {
                break;
            }
            assert(kind == Kind::Wet && s < last);
            last = s;
            ++prints;
        }
        // 0.8^n >= 0.06: n <= 12.6, so 13 prints (1, 0.8, ..., 0.8^12 = 0.0687)
        assert(prints == 13 && c.amount == 0.0f);
        Soak(c, k, false, true);
        assert(c.amount == 1.0f);
        // InWater and GlossyGround.
        assert(InWater(true, 5.0f, 4.9f) && !InWater(true, 5.0f, 4.98f) && !InWater(false, 5.0f, 0.0f));
        assert(!GlossyGround(23, 23) && GlossyGround(24, 8) && !GlossyGround(100, 29) && GlossyGround(100, 30));
    }
    // A forced coat never dries; the test view prints every step at full.
    {
        const Knobs k = Read("1", "blood");
        Coat c;
        Soak(c, k, false, false);
        Kind kind = Kind::Wet;
        for (int i = 0; i < 50; ++i) {
            assert(TakeStep(c, k, false, kind) == 1.0f && kind == Kind::Blood);
        }
        const Knobs show = Read("show", nullptr);
        Coat dry;
        assert(TakeStep(dry, show, false, kind) == 1.0f && kind == Kind::Wet);
        assert(TakeStep(dry, show, true, kind) == 0.0f);
    }
    // Fade: full at 0, half at LifeS / 2, none from LifeS on.
    {
        assert(Near(Fade(0.0), 1.0) && Near(Fade(10.0), 0.5) && Near(Fade(20.0), 0.0) && Near(Fade(99.0), 0.0));
        assert(Fade(2.0) > 0.96 && Fade(5.0) > Fade(15.0));
    }
    // Screen boxes: a camera at the origin looking along +z (view = identity), 90 degrees.
    {
        const std::array<float, 12> view = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const std::array<float, 4> proj = {1.0f, 1.0f, 0.0f, 0.0f};
        const std::array<float, 2> jitter = {0.0f, 0.0f};
        // A point straight ahead lands in the middle of a 100 x 100 screen.
        const float lo[3] = {-0.01f, -0.01f, 4.99f}, hi[3] = {0.01f, 0.01f, 5.01f};
        const Rect r = Project(view, proj, 100.0f, 100.0f, jitter, lo, hi);
        assert(!r.Empty() && r.x0 <= 49 && r.x1 >= 51 && r.y0 <= 49 && r.y1 >= 51);
        assert(r.x1 - r.x0 <= 2 + 2 * MarginPx + 2);
        // Behind the camera: empty; across the camera plane: the whole screen.
        const float blo[3] = {-1.0f, -1.0f, -3.0f}, bhi[3] = {1.0f, 1.0f, -2.0f};
        assert(Project(view, proj, 100.0f, 100.0f, jitter, blo, bhi).Empty());
        const float xlo[3] = {-1.0f, -1.0f, -1.0f}, xhi[3] = {1.0f, 1.0f, 1.0f};
        const Rect all = Project(view, proj, 100.0f, 100.0f, jitter, xlo, xhi);
        assert(all.x0 == 0 && all.y0 == 0 && all.x1 == 100 && all.y1 == 100);
        // Off to the side: empty.
        const float slo[3] = {20.0f, -0.1f, 4.9f}, shi[3] = {20.2f, 0.1f, 5.1f};
        assert(Project(view, proj, 100.0f, 100.0f, jitter, slo, shi).Empty());
        // A jitter of +2 px moves the box by 2 px.
        const Rect j = Project(view, proj, 100.0f, 100.0f, {2.0f, 0.0f}, lo, hi);
        assert(j.x0 == r.x0 + 2 && j.x1 == r.x1 + 2 && j.y0 == r.y0);
        // Union.
        const Rect u = Union(r, Rect{});
        assert(u.x0 == r.x0 && u.x1 == r.x1);
        const Rect v = Union(Rect{1, 2, 3, 4}, Rect{10, 0, 12, 3});
        assert(v.x0 == 1 && v.y0 == 0 && v.x1 == 12 && v.y1 == 4);
    }
    // Pack.
    {
        float out[PrintFloats];
        Pack(1, 2, 3, 0.5f, 0, 1, -1, Kind::Blood, out);
        assert(out[3] == 0.5f && out[6] == -1.0f && out[7] == 2.0f);
    }
    std::puts("footprints: ok");
    return 0;
}
''',
}

README_SECTION = r'''### Footprints (in development)

After the hunter walks out of water, his feet leave wet prints on the ground that fade out over 20 seconds: darker and glossier than the ground around them, so the game's own sun or moon, its lamps and its reflections light them. Off unless `BB_FOOTPRINTS` is set. The engine does not see the game's animation, so the steps come from the hunter's path: once a frame it reads his position from the game, and each time he has gone 0.75 m across since the last print, a print is placed at his position, 0.11 m to the left or right of his path in turn, pointing along it (a sole about 0.26 m long). A move of more than 2 m across or 1 m up or down in one frame (a warp, a load, a fall) starts the path anew. The feet are wet while his position lies more than 3 cm under the water plane of a frame the game draws with a planar water reflection (the sewers), or while the ground around his feet holds a puddle: of the up-facing pixels within 0.45 m of him and 8 cm of his height (read back from the GPU a few frames late), at least 24, and at least 30% of them with a gloss of 0.88 or more. No print is placed while he stands in the water. Each print's strength is what the feet carry, and each step leaves 0.8 of it on them; below 0.06 they are dry (so 13 prints after wading out). The game marks neither mud nor blood on the ground in what the engine sees, so mud and blood prints come only from the test variable `BB_FOOTPRINTS_COAT` for now. The prints are laid into the game's G-buffer (gloss, albedo and specular colour; the albedo is changed in linear values, decoded from and encoded back to the game's sRGB target) right before the first light draw after each G-buffer pass (the sun's shadow resolve, the sun or moon, or a lamp of the light grid), only on up-facing ground within 12 cm of the print's height; not while a lamps-apart batch is still open (counted in the log) and not in a menu's 3D preview. It needs the upscaler's camera (the engine's default; with `BB_UPSCALER=none` it is off and says so). These environment variables are read once when the game starts; they are for testing, no ini key yet. When on, the session log has lines starting with `Footprints (r111`: the knobs at the start, the first position read (with the camera's distance and height above it: about 1.5 to 6 m away and 0.5 to 3 m above means the game's position and the picture agree), the first print, a G-buffer it cannot write (once), and every 600 frames five lines: the frames with the position read, the camera's distance range, the steps and prints placed by kind and the dry steps; the frames in water, on glossy ground and with a water plane, path restarts, live prints, the coat, the passes and their mean size in pixels; the reasons for skipping; a recent frame's print pixels and the up-facing pixels around the feet with their mean height and their count by height; the ground band's mean gloss, its pixels at 0.88 or more against the number a puddle needs, its mean linear albedo, the test view's ring pixels and the last water plane.

| Variable | What it does | Default |
|---|---|---|
| `BB_FOOTPRINTS` | `1`: on; `show`: on with a test view: every step places a print at full strength (wet unless `BB_FOOTPRINTS_COAT` names a kind), painted into the albedo in its kind's colour (cyan wet, orange mud, red blood) instead of the material change, a magenta ring 0.30 to 0.34 m around the hunter's position, and the ground band around his feet (up-facing, within 0.45 m and 8 cm of his height) tinted yellow; so a still picture shows whether the prints and the ring lie at his feet. Unset, empty, `0` or other text: off, nothing of it is made and the game's memory is not read. A wet print darkens the (linear) albedo by up to 50%, raises the gloss toward 0.62 and the specular colour toward f0 0.04 (never lowered); a mud print takes the albedo toward a dark brown by up to 80% and the gloss toward 0.42; a blood print takes the albedo toward a dark red by up to 85%, raises the gloss toward 0.58 and the specular colour as wet. Cost: an estimate of 0.02 to 0.08 ms at 1080p internal for each G-buffer pass with a print or the hunter on screen (one pass over the smallest screen rectangle holding the prints' boxes and a box around the hunter, plus the end of the game's render pass there; with the hunter on screen it runs every frame, for the puddle sense), about four times that at 2160p internal, not measured; nothing in a frame with neither on screen. Memory: under 2 KB of buffers, no image. It is the `Lighting: footprints` row of `BB_GPU_PROFILE=1` | off |
| `BB_FOOTPRINTS_COAT` | A test, only with `BB_FOOTPRINTS` on. `wet`, `mud` or `blood`: the feet carry that from the start and it never dries, so every step places a print of that kind at full strength anywhere. Unset or empty: the coat comes from the game as above; other text: as unset (the log says so) | unset |
'''

# (anchor, before, after): the anchor stays as it is; `before` goes in front of it, `after` behind it.
EDITS = {
    RAST_H: [
        ('#include "video_core/renderer_vulkan/vk_drawn_look.h"\n', "",
         '#include "video_core/renderer_vulkan/vk_footprints.h" // bbport (r111_footprints)\n'),
        ("    std::unique_ptr<DrawnLook> drawn_look; // bbport (r45_drawn-look)\n",
         "    /// bbport (r111_footprints): made only with BB_FOOTPRINTS on (Footprints::Wanted), else null:\n"
         "    /// its two hooks are null pointer tests.\n"
         "    std::unique_ptr<Footprints> footprints;\n", ""),
    ],
    RAST_C: [
        ("    // bbport (r45_drawn-look): nothing of Vulkan is made here; its pipelines and its image are\n",
         "    // bbport (r111_footprints): BB_FOOTPRINTS on only (Footprints::Wanted, read once); otherwise\n"
         "    // no Footprints is made, nothing of it runs and the game's memory is not read. Its pipeline\n"
         "    // and buffers are made at its first pass (vk_footprints.h).\n"
         "    if (Footprints::Wanted()) {\n"
         "        footprints = std::make_unique<Footprints>(instance, scheduler, texture_cache, runtime,\n"
         "                                                  *scene_targets, *camera_motion);\n"
         "    }\n", ""),
    ],
    EFFECTS: [
        ("void Rasterizer::EffectsBeforeResources(const GraphicsPipeline* pipeline) {\n", "",
         "    // bbport (r111_footprints): BB_FOOTPRINTS on only (off: one null pointer test a draw). Before\n"
         "    // this draw's textures, barriers and pass: the G-buffer pass's targets, and the prints laid\n"
         "    // into the G-buffer at the first light draw after each G-buffer pass (vk_footprints.h).\n"
         "    if (footprints) {\n"
         "        std::array<VideoCore::ImageId, AmdGpu::NUM_COLOR_BUFFERS> print_targets{};\n"
         "        for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {\n"
         "            print_targets[cb] = cb_descs[cb].first;\n"
         "        }\n"
         "        const u64 print_ps = FragmentHash(pipeline);\n"
         "        footprints->BeforeDraw(*pipeline, print_targets, db_desc.first,\n"
         "                               PointLightCount(print_ps) != 0 ||\n"
         "                                   print_ps == DirectionalFragmentShaderHash ||\n"
         "                                   print_ps == ShadowResolveHash,\n"
         "                               point_shadow->Pending(), upscaler->Jitter());\n"
         "    }\n"),
        ("    point_shadow->OnFrameEnd();\n"
         "    SunHoldFrameEnd(); // r7_cascades: reads sun_atlas before SunAtlasFrameEnd resets it\n",
         "    if (footprints) { // bbport (r111_footprints): the hunter, the steps, the prints' fading\n"
         "        footprints->OnFrameEnd();\n"
         "    }\n", ""),
    ],
    STATE_H: [
        ("bool world_player_block(std::uint32_t* block);\n", "",
         "// bbport (r111_footprints): the hunter's position (x, y, z; y up) as the game's physics keeps it.\n"
         "bool world_player_position(float pos[3]);\n"),
    ],
    STATE_C: [
        ("bool world_player_block(std::uint32_t* block) {\n"
         "    const std::uint64_t man = Singleton(kWorldChrMan), chr = man ? Follow(man + kPlayerChr) : 0;\n"
         "    std::uint32_t v = 0xffffffffu;\n"
         "    if (!chr || !Peek(chr + kPlayerBlock, &v) || v == 0xffffffffu) return false;\n"
         "    if (block) *block = v;\n"
         "    return true;\n"
         "}\n", "",
         "\n"
         "// bbport (r111_footprints): the hunter's position (x, y, z; y up) as the game's physics keeps it:\n"
         "// the player character (WorldChrMan +0x60), then +0x58, +0x8, +0x3b0 and +0x68 (each a pointer),\n"
         "// then three floats at +0x1e0: the chain online_fixes.cpp's Position reads. False while a link is\n"
         "// null or unreadable. Six pointer reads and one 12-byte read; only BB_FOOTPRINTS calls it (once a\n"
         "// frame, on the render thread; the floats may be from two game steps, which does not matter).\n"
         "bool world_player_position(float pos[3]) {\n"
         "    static constexpr std::array<std::size_t, 4> kChain{0x58, 0x8, 0x3b0, 0x68};\n"
         "    constexpr std::size_t kPosition = 0x1e0;\n"
         "    const std::uint64_t man = Singleton(kWorldChrMan);\n"
         "    std::uint64_t at = man ? Follow(man + kPlayerChr) : 0;\n"
         "    for (const std::size_t link : kChain) at = at ? Follow(at + link) : 0;\n"
         "    float v[3] = {};\n"
         "    if (!at || !Peek(at + kPosition, &v)) return false;\n"
         "    pos[0] = v[0];\n"
         "    pos[1] = v[1];\n"
         "    pos[2] = v[2];\n"
         "    return true;\n"
         "}\n"),
    ],
    CMAKE: [
        ("    add_custom_command(OUTPUT ${OUT}\n",
         "    # bbport (r111_footprints): the footprints' numbers, shared with C++ (footprints.h)\n"
         "    if (FILENAME MATCHES \"^footprints\")\n"
         "        list(APPEND INCLUDES ${SHADER_SRC}/footprints_layout.h)\n"
         "    endif()\n", ""),
        ("add_host_shader(froyok_bloom.comp froyok_bloom_upsample_comp UPSAMPLE=1)\n", "",
         "# bbport (r111_footprints): BB_FOOTPRINTS on only: the footprints laid into the G-buffer\n"
         "# (renderer_vulkan/vk_footprints.cpp)\n"
         "add_host_shader(footprints.comp footprints_comp)\n"),
        ("add_executable(engine-hooks-test EXCLUDE_FROM_ALL ../tests/test_engine_hooks.cpp shim/engine/engine_hooks.cpp)\n",
         "# bbport (r111_footprints): the footprints' knobs, walk, coat, fade and screen boxes\n"
         "# (footprints.h); also built and run by engine/build.sh --test.\n"
         "add_executable(footprints-test EXCLUDE_FROM_ALL ../tests/test_footprints.cpp)\n"
         "target_compile_options(footprints-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
         "target_include_directories(footprints-test PRIVATE ..)\n", ""),
    ],
    BUILD: [
        ('    "${CXX:-clang++}" -std=c++20 -O1 -Wall -Wextra -Werror -I. tests/test_draw_tokens.cpp -o out/draw-tokens-test\n',
         "    # bbport (r111_footprints): the footprints' knobs, walk, coat, fade and screen boxes\n"
         '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_footprints.cpp -o out/footprints-test\n'
         "    out/footprints-test\n", ""),
    ],
    PIPES: [
        ('#include "video_core/host_shaders/froyok_bloom_upsample_comp.h"\n', "",
         '#include "video_core/host_shaders/footprints_comp.h" // bbport (r111_footprints)\n'),
        ('        {"froyok upsample", FROYOK_BLOOM_UPSAMPLE_COMP,\n'
         "         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage}, 32},\n", "",
         "        // bbport (r111_footprints): as vk_footprints.cpp makes it (FootprintRules::Push, 112 bytes)\n"
         '        {"footprints",\n'
         "         FOOTPRINTS_COMP,\n"
         "         {eSampledImage, eStorageImage, eStorageImage, eStorageImage, eStorageBuffer,\n"
         "          eStorageBuffer},\n"
         "         112},\n"),
    ],
    README: [
        ("\n## Sponsors\n", "\n" + README_SECTION.rstrip("\n") + "\n", ""),
    ],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    """'applied' (anchor once, every inserted text once), 'clean' (anchor once, none of them), else refuse.
    Inserted texts are found by themselves, not next to their anchor: a later patch may have put its own
    text between them."""
    done = todo = 0
    for anchor, before, after in eds:
        parts = [t for t in (before, after) if t]
        na, counts = cur.count(anchor), [cur.count(t) for t in parts]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                             % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, done, len(eds)))


def new_state(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    have = open(full, "rb").read().decode("utf-8").replace("\r\n", "\n")
    if have == NEW[path]:
        return "applied"
    raise SystemExit("REFUSED %s: exists and differs from this patch's text" % path)


def text_checks(texts):
    """Ties a compiler cannot check, on the full result (edited and new files)."""
    def need(path, text, n=1):
        if texts[path].count(text) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d"
                             % (path, text, texts[path].count(text), n))
    rules, cpp, lay = texts[RV + "footprints.h"], texts[RV + "vk_footprints.cpp"], texts[HS + "footprints_layout.h"]
    comp = texts[HS + "footprints.comp"]
    need(CMAKE, "add_host_shader(footprints.comp footprints_comp)\n")
    need(CMAKE, "        list(APPEND INCLUDES ${SHADER_SRC}/footprints_layout.h)\n")
    need(CMAKE, "add_executable(footprints-test EXCLUDE_FROM_ALL ../tests/test_footprints.cpp)\n")
    need(BUILD, "tests/test_footprints.cpp -o out/footprints-test\n")
    need(RV + "vk_footprints.cpp", '#include "video_core/host_shaders/footprints_comp.h"')
    need(RV + "vk_footprints.cpp", "FOOTPRINTS_COMP")
    need(PIPES, '#include "video_core/host_shaders/footprints_comp.h"')
    need(PIPES, "FOOTPRINTS_COMP,\n")
    # The descriptor lists of the C++ and the pipeline test agree with the shader's bindings, in order.
    need(RV + "vk_footprints.cpp", "{eSampledImage, eStorageImage, eStorageImage, eStorageImage,\n"
                                   "                            eStorageBuffer, eStorageBuffer},")
    need(PIPES, "{eSampledImage, eStorageImage, eStorageImage, eStorageImage, eStorageBuffer,\n"
                "          eStorageBuffer},\n         112},\n")
    for binding, decl in ((0, "uniform texture2D depth_tex;"), (1, "rgba8) uniform image2D material_img;"),
                          (2, "rgba8) uniform image2D albedo_img;"), (3, "rgba8) uniform image2D specular_img;"),
                          (4, "std430) readonly buffer Prints"), (5, "std430) buffer Counters")):
        if comp.count("layout(binding = %d" % binding) != 1 or comp.count(decl) != 1:
            raise SystemExit("text check: footprints.comp binding %d is not %r" % (binding, decl))
    need(RV + "footprints.h", "static_assert(sizeof(Push) == 112);")
    need(RV + "vk_footprints.cpp", '"Footprints", true)')  # made with eDispatchBase (dispatchBase below)
    need(RV + "vk_footprints.cpp", "cmd.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);")
    # The numbers the README states are the code's.
    for words in ("StrideM = 0.75f", "GaitHalfM = 0.11f", "JumpM = 2.0f", "DropM = 1.0f", "LifeS = 20.0f",
                  "DryPerStep = 0.8f", "MinCoat = 0.06f", "WaterDepthM = 0.03f", "MinGroundPixels = 24;",
                  "WetSharePercent = 30;"):
        need(RV + "footprints.h", words)
    for define, value in (("FOOTPRINTS_SENSE_RADIUS_M", "0.45"), ("FOOTPRINTS_GROUND_M", "0.08"),
                          ("FOOTPRINTS_PUDDLE_GLOSS", "0.88"), ("FOOTPRINTS_PRINT_BAND_M", "0.12"),
                          ("FOOTPRINTS_WET_DARKEN", "0.5"), ("FOOTPRINTS_WET_GLOSS", "0.62"),
                          ("FOOTPRINTS_WET_SPEC_ROOT", "0.2"), ("FOOTPRINTS_MUD_COVER", "0.8"),
                          ("FOOTPRINTS_MUD_GLOSS", "0.42"), ("FOOTPRINTS_BLOOD_COVER", "0.85"),
                          ("FOOTPRINTS_BLOOD_GLOSS", "0.58"), ("FOOTPRINTS_RING_IN_M", "0.3"),
                          ("FOOTPRINTS_RING_OUT_M", "0.34")):
        need(HS + "footprints_layout.h", "#define %s %s\n" % (define, value))
    prints, amount = 0, 1.0
    while amount >= 0.06:
        prints, amount = prints + 1, amount * 0.8
    if prints != 13:
        raise SystemExit("text check: the coat gives %d prints, the README says 13" % prints)
    whole = texts[README]
    if whole.count("### Footprints (in development)\n") != 1:
        raise SystemExit("text check: the README section is not there once")
    rd = whole[whole.find("### Footprints (in development)\n"):]
    rd = rd[:rd.find("\n## ") + 1] if "\n## " in rd else rd
    for words in ("### Footprints (in development)", "0.75 m across", "0.11 m to the left or right", "over 20 seconds",
                  "more than 3 cm under", "within 0.45 m of him and 8 cm of his height", "at least 24",
                  "at least 30%", "gloss of 0.88 or more", "leaves 0.8 of it", "below 0.06", "13 prints",
                  "within 12 cm of the print's height", "more than 2 m across or 1 m up or down",
                  "by up to 50%", "toward 0.62", "smallest screen rectangle", "f0 0.04", "toward 0.42", "by up to 80%", "by up to 85%",
                  "toward 0.58", "0.30 to 0.34 m", "`Lighting: footprints`", "`Footprints (r111`",
                  "| `BB_FOOTPRINTS` |", "| `BB_FOOTPRINTS_COAT` |"):
        if rd.count(words) != 1:
            raise SystemExit("text check: README holds %r %d times, wanted 1" % (words, rd.count(words)))
    if whole.find("### Footprints (in development)") > whole.find("\n## Sponsors\n"):
        raise SystemExit("text check: the README section is not before Sponsors")
    # Hooks: each once, the BeforeDraw one inside EffectsBeforeResources (review: not required to be
    # first, so that another patch's line at the function's head does not fail this check).
    need(EFFECTS, "footprints->BeforeDraw(")
    need(EFFECTS, "footprints->OnFrameEnd();")
    need(RAST_C, "footprints = std::make_unique<Footprints>(")
    need(RAST_H, "std::unique_ptr<Footprints> footprints;")
    e = texts[EFFECTS]
    head = "void Rasterizer::EffectsBeforeResources(const GraphicsPipeline* pipeline) {\n"
    a = e.find(head)
    b = e.find("\n}\n", a) if a >= 0 else -1
    if not (0 <= a < e.find("footprints->BeforeDraw(") < b):
        raise SystemExit("text check: the BeforeDraw hook is not inside EffectsBeforeResources")
    # The albedo target is the game's R8G8B8A8_SRGB (vk_ssgi.cpp takes it only so): taken, viewed as
    # UNORM, decoded and encoded by the shader.
    need(RV + "vk_footprints.cpp", "constexpr auto AlbedoSrgbFormat = vk::Format::eR8G8B8A8Srgb;")
    need(RV + "vk_footprints.cpp", "push.flags = R::Flags(k, sensing, step.slot, albedo_srgb);")
    need(HS + "footprints_layout.h", "#define FOOTPRINTS_FLAG_SRGB 8u\n")
    need(HS + "footprints.comp", "            a.rgb = ToLinear(a.rgb);\n")
    need(HS + "footprints.comp", "                a.rgb = ToSrgb(a.rgb);\n")
    # Every log line under 300 characters with wide numbers (the slot runner keeps 300 of a line):
    # %u as 7 characters, a float as 9, a %s as 12 (the constructor's line, whose texts are longer:
    # about 285 with its longest texts, counted by the review).
    import re
    for m in re.finditer(r'BbReport::Printf\(((?:\s*"(?:[^"\\]|\\.)*")+)', cpp):
        fmt = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))).replace("\\n", "")
        wide = re.sub(r"%[-+]?[0-9]*\.[0-9]+f", "X" * 9, fmt)
        wide = re.sub(r"%(?:ll)?[ud]", "X" * 7, wide)
        wide = re.sub(r"%s", "X" * 12, wide)
        if len(wide) > 300:
            raise SystemExit("text check: a log line may pass 300 characters (%d): %r" % (len(wide), fmt[:60]))
    f = e.find("void Rasterizer::EffectsOnFrameEnd() {\n")
    if not (0 <= f < e.find("footprints->OnFrameEnd();", f) < e.find("    point_shadow->OnFrameEnd();\n", f)):
        raise SystemExit("text check: the OnFrameEnd hook is not in EffectsOnFrameEnd before point_shadow's")
    # The position reader: declared and defined once; nothing else in the patch reads the game's memory.
    need(STATE_H, "bool world_player_position(float pos[3]);\n")
    need(STATE_C, "bool world_player_position(float pos[3]) {\n")
    need(RV + "vk_footprints.cpp", "BbEngine::world_player_position(pos)")
    # Every log line of the class starts with "Footprints (r111)" (the slot runs keep such lines).
    for line in cpp.split("\n"):
        if "BbReport::Printf(\"" in line and "Footprints (r111)" not in line:
            raise SystemExit("text check: a log line without its prefix: %r" % line)
    # No tab, no CR in the new texts (they are written with CRLF).
    for path, text in NEW.items():
        if "\t" in text or "\r" in text or not text.endswith("\n"):
            raise SystemExit("text check: %s has a tab, a CR or no final newline" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 r111_footprints.py check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R111_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    news = {path: new_state(path) for path in NEW}
    states = {p[5] for p in plan} | set(news.values())
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join(["%s %s" % (p[0], p[5]) for p in plan] +
                                                       ["%s %s" % (k, v) for k, v in news.items()]))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for anchor, before, after in eds:
                cur = cur.replace(anchor, before + anchor + after)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        out.update(NEW)
        return out

    if cmd == "check":
        if state == "applied":
            texts = {p[0]: p[4] for p in plan}
            texts.update(NEW)
            text_checks(texts)
            print("applied (%d files edited, %d new; text checks pass)" % (len(plan), len(NEW)))
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW)))
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
            tmp = full + ".r111tmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path, text in NEW.items():
            full = os.path.join(ROOT, path)
            tmp = full + ".r111tmp"
            open(tmp, "wb").write(text.replace("\n", "\r\n").encode("utf-8"))
            os.replace(tmp, full)
        print("applied (%d files edited, %d new)" % (len(plan), len(NEW)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for anchor, before, after in reversed(eds):
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r111tmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted (%d files edited back, %d removed)" % (len(plan), len(NEW)))


main()
