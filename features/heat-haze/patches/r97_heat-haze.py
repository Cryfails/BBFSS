# r97_heat-haze (reviewed copy r97_heat-haze.fixed.py, 2026-11-15: see the context file
# bbfss-ctx-heat-haze.md, review section): FEATURE patch (order item 10, "Heat haze"). A subtle shimmer of rising warm air
# above flames (the hunter's torch, candles, lanterns, street lamps' flames, bonfires). Off by
# default behind BB_HEAT_HAZE (a strength, 0..2; unset, 0 or not a number = off) and
# BB_HEAT_HAZE_SHOW=1 (test view: 3x the shimmer, columns tinted blue-green). Environment only,
# read once; no ini key, menu row or launcher row (work in progress, as the wind's knobs).
#
# What the game does already (the owner: "seems like the torch already has this and
# flickering"): the r64 surface probe of eight places (S/probe_<place>.txt, 2026-11-15) lists
# every draw that reads the scene colour back: only full-screen composites (vs 0b0acf50 ps
# 86e96401 / ccbf44a6 at the output size after the upscaler, vs 8747a367 ps 8650418f at the
# render size, 4 or 6 indices). The game's fire and particle sprites (vs 16e3fa9f, 4cd21a0f,
# 41ae600f) read their own texture and the depth (soft particles), no copy of the scene. So no
# draw moves pixels behind a flame: what looks like haze at the torch is its animated flame
# sprites (and the flicker is in the lamp's light). This patch adds the haze and doubles nothing.
#
# How:
#  - Lamps: the light lists of the game's lamp pass, where the engine already reads them
#    (Rasterizer::EffectsBeforeBind, tile lights; the same records the ray traced lamp pass and
#    TrackLamps take: view-space place, 1/reach^2, colour). Each lamp once (a lamp repeats in
#    every tile); a warm colour (orange to warm yellow) and a flame's reach (0.5-20 m) mark a
#    flame (heat_haze.h IsFlame); of those in front of the camera and nearer than 25 m the 32
#    nearest are kept (Collector). A G-buffer pass starts the list anew (EffectsAfterTargets), so
#    the scene's own lamps (the last pass) are kept, not a water reflection's.
#  - Columns: above each flame a column of air 7% of the reach tall (0.3-1 m), radius 1.5% of it
#    (0.05-0.18 m), 1.8x as wide at the top, up the world's +y, leaning downwind with BB_WIND=1
#    (BbWind::Snapshot::wind, 0.15 of the height per m/s, at most 0.6). Projected with the
#    frame's camera (CameraMotion::PassMatrices, jitter included). At most 8 a frame (the largest
#    on screen), faded from 12 m to 25 m, none where the shimmer's largest move would
#    stay under 0.6 px per 1080 rows (the same choice at every render size and with the test view).
#  - Pass (host_shaders/heat_haze.comp, one build): for each column, its rectangle of the scene
#    is copied into an atlas (RGBA16F, half the scene's width and height, shelf-packed), then
#    inside the column each pixel takes the atlas's colour up to 0.03 m (at the flame's
#    distance; at most 8 px per 1080 rows) beside it, moved by a value noise that rises at
#    0.6 m/s (real time, so frame-rate independent); weight: fades in over the lowest 12% of the
#    column, out as (1-t)^1.5 to the top and (1-x^2)^2 to the sides. Depth tested: a pixel nearer
#    than the flame by more than radius + 0.15 m is not moved, and no pixel takes a colour from
#    such a pixel. Alpha stays the pixel's own. Overlapping columns: the nearer is drawn last
#    with a barrier between.
#  - Place: Rasterizer::EffectsBeforeUpscaler at the upscaler's trigger, after the volumetric
#    fog composite (the fog behind a flame shimmers too) and before the card debug view: on the
#    scene colour at the render size, BEFORE the upscaler (DLSS/FSR/XeSS/TAA) and therefore
#    before the HUD (drawn at the output size after it). The upscaler takes the shimmer as it
#    takes the game's fire; with the reactive mask on (menu), pixels changed after the opaque
#    snapshot count as reactive, which by construction includes the haze (not verified). A
#    compute dispatch ends any lamps-apart batch before this place (Rasterizer::DispatchRecord,
#    EffectsEndLampBatch), so reading the camera depth here needs no batch end (rule 11).
#    Without the upscaler (BB_UPSCALER=none) the place is never reached: said once, not drawn.
#
# Off guarantee: HeatHaze::Wanted() reads the knob once; the Rasterizer makes a HeatHaze only
# when it gives a strength above 0. Off, heat_haze is null: no pipeline, no image, no buffer, no
# dispatch; the three hooks are one null pointer test each (per tile-light draw, per G-buffer
# pass, per upscaler trigger). The picture is bit-identical (nothing writes it).
#
# Cost (NOT MEASURED): on, with no flame in view: the light records' colour test on the CPU (the
# r64 probe counted 400 to 2300 light records a frame at the eight places; a few compares and a
# square root each, the flames also compared with the kept ones: estimated 20-60 us a frame on the
# render thread), nothing on the GPU. With flames: two compute
# dispatches per column (copy, haze; at most 16 dispatches, 2-3 barriers) over the columns'
# rectangles only, at the render size: a torch at 3 m is about 150x300 px at 1080p internal;
# estimate 0.01-0.05 ms a frame at 1080p internal (4K output with DLSS Performance), about 4x the
# pixels at 2160p internal. Memory: the atlas, 8 bytes x (w/2) x (h/2): 4.1 MB at 1080p internal,
# 16.6 MB at 2160p internal, made at the first frame with a column (none before), kept. Kept low
# by: no full-screen pass (rectangles only), half-size atlas instead of a scene copy, early outs
# in the shader before any noise (outside the column, under 1/256 weight, in front of the flame),
# the pipeline made at the start (no compile in play). Profiler row: "Lighting: heat haze"
# (EffectPass::Mark 97).
#
# Log: once at start "Heat haze (r97, BB_HEAT_HAZE=x): on; ..." (or "...: off" / "is not a number:
# off" when the variable is set to something that is off; nothing when unset); once "Heat haze
# (r97): atlas WxH RGBA16F (N bytes) ..." and "first columns drawn, N at a scene of WxH"; after the
# first 120 and then every 600 frames that reach the upscaler's trigger, through BbReport: "Heat
# haze (r97): of N frames
# before the upscaler K drew columns, C a frame (...); a frame F flames among R light records
# ...; nearest flame with a column D m, largest shimmer A px, P pixels under the columns".
#
# Files. New (5): renderer_vulkan/heat_haze.h (pure), vk_heat_haze.h, vk_heat_haze.cpp,
# host_shaders/heat_haze.comp, engine/tests/test_heat_haze.cpp (heat-haze-test, also in
# build.sh --test). Shared files hooked (anchors on lines of each neighbourhood, inserted text
# only, nothing replaced): vk_rasterizer.h (1 include, 1 member), vk_rasterizer.cpp (made after
# the card alpha, 8 lines), vk_rasterizer_effects.cpp (3 hooks: ClearLights after
# depth_of_field->Reset() in EffectsAfterTargets; AddLights after the r64 surface probe's lamp
# lines in EffectsBeforeBind; Apply before the r62 card view in EffectsBeforeUpscaler),
# engine/gpu/CMakeLists.txt (shader build after paint_lock_comp, test target after rt-glass-test),
# engine/build.sh (after out/rt-glass-test), engine/tests/test_effect_pipelines.cpp (include +
# one entry before "ssgi prep"), README.md (a section before "## Sponsors").
#
# usage: python -I -X utf8 r97_heat-haze.py check|apply|revert
#   root: env R97_HEAT_HAZE_ROOT, else <tree>. Backups of edited files: r97_backup next to
#   this script (env R97_HEAT_HAZE_BACKUP to put them elsewhere; written at apply). Each edit is a
#   block inserted right after or before its anchor: apply needs the anchor once and the block
#   absent; revert takes out the block alone, so other patches' lines at the same anchors
#   (r95_halation uses three of them), applied before or after this one, stay. New files are
#   removed by revert.
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.environ.get("R97_HEAT_HAZE_BACKUP") or os.path.join(HERE, "r97_backup")
ROOT = os.environ.get("R97_HEAT_HAZE_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"

# The new files (LF here; written with CRLF, as the tree's sources).
NEW = {}
NEW[R + "heat_haze.h"] = r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97_heat-haze): the pure parts of the heat haze (vk_heat_haze.cpp): the knobs, which of
// the game's lamps are flames, the column of rising warm air above each and its place on the
// screen, and the choice of the columns a frame draws with their places in the pass's copy of the
// scene (the atlas). No Vulkan, no settings; tested by tests/test_heat_haze.cpp.
//
// A lamp is a record of the game's lamp pass (16 words: its place in view space, 1 / reach
// squared, its colour; the words point_volumetric.comp and the ray traced lamp pass read). The
// game repeats a lamp in every screen tile it reaches, so the Collector keeps each once.
#pragma once

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <optional>
#include <span>
#include <vector>

namespace BbHeatHaze {

inline constexpr float MaxStrength = 2.0f;      ///< BB_HEAT_HAZE is clamped to 0..2
inline constexpr float ShowGain = 3.0f;         ///< BB_HEAT_HAZE_SHOW=1: the shimmer 3 times wider
inline constexpr std::uint32_t RecordWords = 16; ///< a light record of the lamp pass
inline constexpr std::uint32_t KeyWords = 7;     ///< the words that tell two lamps apart
inline constexpr std::uint32_t MaxLamps = 32;    ///< distinct flames kept a frame
inline constexpr std::uint32_t MaxColumns = 8;   ///< columns drawn a frame (the largest on screen)
inline constexpr float NearZ = 0.3f;             ///< m: a flame nearer the camera plane draws none
inline constexpr float FadeStart = 12.0f;        ///< m from the camera: the haze starts to fade
inline constexpr float FadeEnd = 25.0f;          ///< m: and is gone (no column further away)
inline constexpr float MinReach = 0.5f, MaxReach = 20.0f; ///< m: a flame's lamp reaches this far
/// The column's height and its radius at the flame follow the lamp's reach (a bonfire reaches
/// further than a candle): 7% and 1.5% of it, within these bounds (m).
inline constexpr float HeightPerReach = 0.07f, MinHeight = 0.3f, MaxHeight = 1.0f;
inline constexpr float RadiusPerReach = 0.015f, MinRadius = 0.05f, MaxRadius = 0.18f;
inline constexpr float Widen = 0.8f;        ///< the column is this much wider at its top
/// m: the most the shimmer moves a pixel at strength 1, at the flame's distance (the noise's
/// root mean square is 0.3 of it, the column's weight at most 0.83 of that, just above the flame).
inline constexpr float AmplitudeM = 0.03f;
/// Render pixels per 1080 rows (scaled to the scene's rows, so the choice is the same at every
/// render size): the most the shimmer moves a pixel at strength 1 (a flame right at the camera),
/// and the least the column's largest move must reach, after the fade and at the strength but
/// without the test view's gain, for the column to be drawn at all.
inline constexpr float MaxAmplitudePx = 8.0f, MinAmplitudePx = 0.6f;
inline constexpr float DepthMarginM = 0.15f; ///< m beyond the column's radius: what is nearer
                                             ///< the camera than the flame by more is in front
inline constexpr float LeanPerMps = 0.15f;   ///< the column's top leans this share of its height
inline constexpr float MaxLean = 0.6f;       ///< per m/s of wind, at most this share
inline constexpr float RiseMps = 0.6f;       ///< m/s: how fast the shimmer's pattern rises

/// The two knobs, read once (vk_heat_haze.cpp: HeatHaze::Wanted).
struct Knobs {
    float strength = 0.0f;   ///< 0: off (no pass, no image)
    bool show = false;       ///< BB_HEAT_HAZE_SHOW=1 with a strength above 0
    bool unreadable = false; ///< BB_HEAT_HAZE held text that is not a number: off
};

/// BB_HEAT_HAZE: unset or empty is off; a finite number is the strength, clamped to 0..2 (1 is
/// the look as designed, 0 is off); any other text is off. BB_HEAT_HAZE_SHOW: exactly "1".
inline Knobs Parse(const char* haze, const char* show) {
    Knobs knobs;
    if (haze == nullptr || haze[0] == 0) {
        return knobs;
    }
    char* end = nullptr;
    const float value = std::strtof(haze, &end);
    if (end == haze || *end != 0 || !std::isfinite(value)) {
        knobs.unreadable = true;
        return knobs;
    }
    knobs.strength = std::clamp(value, 0.0f, MaxStrength);
    knobs.show = knobs.strength > 0.0f && show != nullptr && show[0] == '1' && show[1] == 0;
    return knobs;
}

struct Lamp {
    std::array<float, 3> view{};   ///< its place in view space, m (+z ahead of the camera)
    float reach = 0.0f;            ///< m
    std::array<float, 3> colour{}; ///< as the record holds it
};

inline float Word(const std::uint32_t* record, std::size_t i) {
    return std::bit_cast<float>(record[i]);
}

/// A record as a lamp; none for one the lamp pass skips (no reach) or with a word not finite.
inline std::optional<Lamp> ReadLamp(const std::uint32_t* record) {
    for (std::size_t i = 0; i < KeyWords; ++i) {
        if (!std::isfinite(Word(record, i))) {
            return std::nullopt;
        }
    }
    const float inverse_reach_squared = Word(record, 3);
    if (!(inverse_reach_squared > 0.0f)) {
        return std::nullopt;
    }
    Lamp lamp;
    lamp.view = {Word(record, 0), Word(record, 1), Word(record, 2)};
    lamp.reach = 1.0f / std::sqrt(inverse_reach_squared);
    lamp.colour = {Word(record, 4), Word(record, 5), Word(record, 6)};
    return lamp;
}

/// A flame's lamp: orange to warm yellow (green 0.25 to 0.92 of red, blue at most 0.75 of green
/// and 0.6 of red), some light (luminance 0.02 or more) and the reach of a flame (0.5 to 20 m).
/// A warm white, a cold, a red or a coloured light is none. A warm light the game placed where
/// nothing burns (a fill light) passes too; BB_HEAT_HAZE_SHOW=1 shows where the columns stand.
inline bool IsFlame(const Lamp& lamp) {
    const float r = lamp.colour[0], g = lamp.colour[1], b = lamp.colour[2];
    return r > 0.0f && b >= 0.0f && g >= 0.25f * r && g <= 0.92f * r && b <= 0.75f * g &&
           b <= 0.6f * r && 0.2126f * r + 0.7152f * g + 0.0722f * b >= 0.02f &&
           lamp.reach >= MinReach && lamp.reach <= MaxReach;
}

/// The flames of one lamp pass that can have a column (in front of the camera, nearer than
/// FadeEnd), each kept once: the MaxLamps nearest (a candle-lit hall lists more flames than
/// that, and the game's tile order is no order of distance).
class Collector {
public:
    void Clear() {
        count = 0;
        records = others = beyond = dropped = 0;
    }
    /// `n` records of one tile's light list.
    void Add(const std::uint32_t* list, std::uint32_t n) {
        for (std::uint32_t k = 0; k < n; ++k) {
            const std::uint32_t* record = list + std::size_t(k) * RecordWords;
            ++records;
            const auto lamp = ReadLamp(record);
            if (!lamp || !IsFlame(*lamp)) {
                ++others;
                continue;
            }
            const auto& v = lamp->view;
            const float distance_squared = v[0] * v[0] + v[1] * v[1] + v[2] * v[2];
            if (!(v[2] >= NearZ) || !(distance_squared < FadeEnd * FadeEnd)) {
                ++beyond;
                continue;
            }
            bool known = false;
            for (std::uint32_t i = 0; i < count && !known; ++i) {
                known = std::equal(keys[i].begin(), keys[i].end(), record);
            }
            if (known) {
                continue;
            }
            std::uint32_t at = count;
            if (count >= MaxLamps) {
                // Full: the farthest kept one gives way to a nearer one.
                ++dropped;
                at = 0;
                for (std::uint32_t i = 1; i < count; ++i) {
                    at = squared[i] > squared[at] ? i : at;
                }
                if (!(distance_squared < squared[at])) {
                    continue;
                }
            } else {
                ++count;
            }
            std::copy_n(record, KeyWords, keys[at].begin());
            lamps[at] = *lamp;
            squared[at] = distance_squared;
        }
    }
    [[nodiscard]] std::span<const Lamp> Lamps() const {
        return {lamps.data(), count};
    }
    [[nodiscard]] std::uint32_t Records() const { return records; }
    [[nodiscard]] std::uint32_t Others() const { return others; } ///< records not of a flame
    /// Flame records behind the camera plane (NearZ) or FadeEnd or further away (one a tile).
    [[nodiscard]] std::uint32_t Beyond() const { return beyond; }
    /// Flame records over MaxLamps: a farther one left out or given way (one a tile).
    [[nodiscard]] std::uint32_t Dropped() const { return dropped; }

private:
    std::array<std::array<std::uint32_t, KeyWords>, MaxLamps> keys{};
    std::array<Lamp, MaxLamps> lamps{};
    std::array<float, MaxLamps> squared{}; ///< each kept lamp's distance squared, m^2
    std::uint32_t count = 0, records = 0, others = 0, beyond = 0, dropped = 0;
};

/// The frame's camera as CameraMotion::PassMatrices gives it, and the scene's size.
struct Camera {
    std::array<float, 12> view{};     ///< world to view, 3x4 rows
    std::array<float, 12> inv_view{}; ///< view to world, 3x4 rows
    std::array<float, 4> proj{};      ///< x scale, y scale (signed: ndc +y down), z scale, z offset
    std::uint32_t width = 0, height = 0; ///< the scene's pixels
    std::array<float, 2> jitter{};    ///< the viewport's shift this frame, pixels (x right, y down)
};

/// A view space point's place in the scene, pixels (as the frame was drawn, jitter included).
inline std::array<float, 2> ToPixel(const Camera& camera, const std::array<float, 3>& v) {
    const float x = v[0] * camera.proj[0] / v[2];
    const float y = v[1] * camera.proj[1] / v[2];
    return {(x * 0.5f + 0.5f) * float(camera.width) + camera.jitter[0],
            (y * 0.5f + 0.5f) * float(camera.height) + camera.jitter[1]};
}

/// One column's words for host_shaders/heat_haze.comp (its push constants, 96 bytes; the GLSL
/// block there lists the same fields in the same order).
struct Push {
    std::array<std::int32_t, 4> rect{};  ///< x, y, width, height in the scene, pixels
    std::array<std::int32_t, 4> atlas{}; ///< x, y of its copy in the atlas; the pass; flags
    std::array<float, 4> axis{};         ///< the flame's (base) and the top's x, y, pixels
    std::array<float, 4> shape{};        ///< half width at the base (px), widening to the top,
                                         ///< the shimmer's reach (px), the flame's view z (m)
    std::array<float, 4> field{};        ///< pixels a metre at the flame, the depth margin (m),
                                         ///< the fade with distance, the pattern's seed
    std::array<float, 4> clock{};        ///< the projection's z scale and z offset (depth to
                                         ///< view z), the time (s), the rise (m/s)
};
static_assert(sizeof(Push) == 96);
inline constexpr std::int32_t PassCopy = 0; ///< the column's rectangle into the atlas
inline constexpr std::int32_t PassHaze = 1; ///< the shimmer, from the atlas into the scene
inline constexpr std::int32_t FlagShow = 1; ///< BB_HEAT_HAZE_SHOW=1: the column tinted too

struct Column {
    Push push;
    float score = 0.0f;    ///< its length on screen (px) times the fade: the largest are drawn
    float distance = 0.0f; ///< m from the camera
};

inline float Smoothstep(float edge0, float edge1, float x) {
    const float t = std::clamp((x - edge0) / (edge1 - edge0), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

/// The column above a flame, or none: behind or at the camera, FadeEnd or further, off the
/// screen, shorter than 2 pixels, or with a shimmer under MinAmplitudePx (per 1080 rows) after
/// the fade.
/// `wind`: the wind in the world, m/s (BbWind::Snapshot::wind; zero without BB_WIND): the top
/// leans with it, LeanPerMps of the height per m/s, at most MaxLean.
inline std::optional<Column> MakeColumn(const Lamp& lamp, const Camera& camera, float strength,
                                        bool show, const std::array<float, 3>& wind) {
    if (!(strength > 0.0f) || camera.width == 0 || camera.height == 0) {
        return std::nullopt;
    }
    const auto& v = lamp.view;
    if (!(v[2] >= NearZ)) {
        return std::nullopt;
    }
    const float distance = std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (!(distance < FadeEnd)) {
        return std::nullopt;
    }
    const float fade = 1.0f - Smoothstep(FadeStart, FadeEnd, distance);
    const float height = std::clamp(HeightPerReach * lamp.reach, MinHeight, MaxHeight);
    const float radius = std::clamp(RadiusPerReach * lamp.reach, MinRadius, MaxRadius);
    const auto& m = camera.view;
    // The world's up (+y) and the wind, in view space.
    const std::array<float, 3> up{m[1], m[5], m[9]};
    std::array<float, 3> lean{};
    for (std::size_t r = 0; r < 3; ++r) {
        lean[r] = (m[r * 4] * wind[0] + m[r * 4 + 1] * wind[1] + m[r * 4 + 2] * wind[2]) * LeanPerMps;
    }
    const float lean_length = std::sqrt(lean[0] * lean[0] + lean[1] * lean[1] + lean[2] * lean[2]);
    if (!std::isfinite(lean_length)) {
        lean = {};
    } else if (lean_length > MaxLean) {
        for (float& c : lean) {
            c *= MaxLean / lean_length;
        }
    }
    std::array<float, 3> top{};
    for (std::size_t r = 0; r < 3; ++r) {
        top[r] = v[r] + height * (up[r] + lean[r]);
    }
    if (!(top[2] >= 0.5f * NearZ)) {
        return std::nullopt;
    }
    const auto base_px = ToPixel(camera, v);
    const auto top_px = ToPixel(camera, top);
    const float dx = top_px[0] - base_px[0], dy = top_px[1] - base_px[1];
    const float length = std::sqrt(dx * dx + dy * dy);
    const float rows = float(camera.height);
    const float per_metre = 0.5f * rows * std::abs(camera.proj[1]) / v[2];
    // Whether a column is drawn does not depend on the test view: it shows the columns as drawn.
    const float plain = std::min(AmplitudeM * per_metre, MaxAmplitudePx * rows / 1080.0f) * strength;
    const float amplitude = plain * (show ? ShowGain : 1.0f);
    if (!std::isfinite(length) || !(length >= 2.0f) ||
        !(plain * fade >= MinAmplitudePx * rows / 1080.0f)) {
        return std::nullopt;
    }
    const float half_base = radius * per_metre, half_top = half_base * (1.0f + Widen);
    const float pad = amplitude + 2.0f;
    const float x0 = std::min(base_px[0] - half_base, top_px[0] - half_top) - pad;
    const float x1 = std::max(base_px[0] + half_base, top_px[0] + half_top) + pad;
    const float y0 = std::min(base_px[1] - half_base, top_px[1] - half_top) - pad;
    const float y1 = std::max(base_px[1] + half_base, top_px[1] + half_top) + pad;
    // (Clamped before the casts: a column across the camera plane can reach far off the screen.)
    const float w = float(camera.width), h = float(camera.height);
    const std::int32_t ix0 = std::int32_t(std::floor(std::clamp(x0, 0.0f, w)));
    const std::int32_t iy0 = std::int32_t(std::floor(std::clamp(y0, 0.0f, h)));
    const std::int32_t ix1 = std::int32_t(std::ceil(std::clamp(x1, 0.0f, w)));
    const std::int32_t iy1 = std::int32_t(std::ceil(std::clamp(y1, 0.0f, h)));
    if (ix1 <= ix0 || iy1 <= iy0) {
        return std::nullopt;
    }
    // The pattern's seed from the flame's place in the world (continuous: a carried torch moves
    // through the pattern, lamps side by side do not shimmer alike), kept small for the floats.
    const auto& iv = camera.inv_view;
    const float world_x = iv[0] * v[0] + iv[1] * v[1] + iv[2] * v[2] + iv[3];
    const float world_z = iv[8] * v[0] + iv[9] * v[1] + iv[10] * v[2] + iv[11];
    float seed = std::fmod(0.37f * world_x + 0.61f * world_z, 64.0f);
    if (!std::isfinite(seed)) {
        seed = 0.0f;
    }
    Column column;
    column.push.rect = {ix0, iy0, ix1 - ix0, iy1 - iy0};
    column.push.atlas = {0, 0, PassHaze, show ? FlagShow : 0};
    column.push.axis = {base_px[0], base_px[1], top_px[0], top_px[1]};
    column.push.shape = {half_base, Widen, amplitude, v[2]};
    column.push.field = {per_metre, radius + DepthMarginM, fade, seed};
    column.push.clock = {camera.proj[2], camera.proj[3], 0.0f, RiseMps};
    column.score = length * fade;
    column.distance = distance;
    return column;
}

/// The pass's copy of the scene under the columns: half the scene's width and height (at least
/// 64 texels a side), RGBA16F.
struct Atlas {
    std::uint32_t width = 0, height = 0;
};
inline Atlas AtlasFor(std::uint32_t width, std::uint32_t height) {
    return {std::max(64u, (width + 1u) / 2u), std::max(64u, (height + 1u) / 2u)};
}

/// One side of a rectangle cut to `room`, keeping the flame's end: `from`, `size` the side's
/// start and length; `base`, `top` the flame's and the top's coordinate on it; `pad` pixels.
inline void CutSide(std::int32_t& from, std::int32_t& size, std::int32_t room, float base, float top,
                    std::int32_t pad) {
    if (size <= room) {
        return;
    }
    const std::int32_t start = top < base ? std::int32_t(std::ceil(base)) + pad - room
                                          : std::int32_t(std::floor(base)) - pad;
    from = std::clamp(start, from, from + size - room);
    size = room;
}

/// What the choice of a frame's columns left out.
struct Counts {
    std::uint32_t made = 0;    ///< columns drawn
    std::uint32_t unseen = 0;  ///< flames with no column (behind, far, off the screen, too small)
    std::uint32_t over = 0;    ///< columns beyond MaxColumns
    std::uint32_t no_room = 0; ///< columns the atlas had no room for
};

/// The frame's columns: one a flame, the MaxColumns with the highest score, cut to the atlas and
/// placed in it shelf by shelf (tallest first, left to right; a column that fits on no shelf is
/// left out), returned farthest first (drawn in that order, so that where two overlap the nearer
/// one is on top).
inline std::vector<Column> Choose(std::span<const Lamp> lamps, const Camera& camera, float strength,
                                  bool show, const std::array<float, 3>& wind, Atlas atlas,
                                  Counts& counts) {
    counts = {};
    std::vector<Column> columns;
    columns.reserve(lamps.size());
    for (const Lamp& lamp : lamps) {
        if (auto column = MakeColumn(lamp, camera, strength, show, wind)) {
            columns.push_back(*column);
        } else {
            ++counts.unseen;
        }
    }
    std::stable_sort(columns.begin(), columns.end(),
                     [](const Column& a, const Column& b) { return a.score > b.score; });
    if (columns.size() > MaxColumns) {
        counts.over = std::uint32_t(columns.size() - MaxColumns);
        columns.resize(MaxColumns);
    }
    for (Column& column : columns) {
        auto& rect = column.push.rect;
        const std::int32_t pad = std::int32_t(std::ceil(column.push.shape[2])) + 2;
        CutSide(rect[0], rect[2], std::int32_t(atlas.width), column.push.axis[0],
                column.push.axis[2], pad);
        CutSide(rect[1], rect[3], std::int32_t(atlas.height), column.push.axis[1],
                column.push.axis[3], pad);
    }
    std::stable_sort(columns.begin(), columns.end(), [](const Column& a, const Column& b) {
        return a.push.rect[3] > b.push.rect[3];
    });
    std::vector<Column> placed;
    placed.reserve(columns.size());
    std::int32_t x = 0, y = 0, shelf = 0;
    for (Column& column : columns) {
        const std::int32_t w = column.push.rect[2], h = column.push.rect[3];
        if (x + w > std::int32_t(atlas.width)) {
            x = 0;
            y += shelf;
            shelf = 0;
        }
        if (y + h > std::int32_t(atlas.height)) {
            ++counts.no_room;
            continue;
        }
        column.push.atlas[0] = x;
        column.push.atlas[1] = y;
        x += w;
        shelf = std::max(shelf, h);
        placed.push_back(column);
    }
    std::stable_sort(placed.begin(), placed.end(),
                     [](const Column& a, const Column& b) { return a.distance > b.distance; });
    counts.made = std::uint32_t(placed.size());
    return placed;
}

} // namespace BbHeatHaze
'''
NEW[R + "vk_heat_haze.h"] = r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97_heat-haze): a shimmer of rising warm air above flames (torches, candles, lanterns,
// bonfires), where the game draws none. The game's own pictures move no pixel of the scene behind
// a flame: in the surface probe (r64) of eight places, the draws that read the scene colour back
// are full-screen composites only, and its fire sprites read their texture and the depth, no copy
// of the scene. So this adds the haze and doubles nothing.
//
// Off unless BB_HEAT_HAZE is a strength above 0 (environment, read once, heat_haze.h Parse). Off,
// the rasterizer makes no HeatHaze (Wanted), so there is no pipeline, no image and no pass, and
// each of its three hooks is one null pointer test.
//
// The lamps: the light lists of the game's lamp pass (Rasterizer::EffectsBeforeBind, the tile
// lights, as the ray traced lamp pass takes them); a G-buffer pass starts the list anew, so the
// last pass's (the scene's, not a reflection's) are kept; a warm colour marks a flame (IsFlame).
// The pass: right before the upscaler's trigger (Rasterizer::EffectsBeforeUpscaler, after the
// fog composite), on the scene colour at the render size: the upscaler (DLSS, FSR, XeSS, TAA)
// then takes the shimmer as it takes the game's fire, and the HUD, drawn after the upscaler, is
// never moved. Without the upscaler (BB_UPSCALER=none or a GPU it cannot run on) that place is
// never reached and the haze is not drawn (said once).
#pragma once

#include <array>
#include <chrono>

#include "common/types.h"
#include "video_core/renderer_vulkan/heat_haze.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class Instance;
class Runtime;
class SceneTargets;
class Scheduler;

class HeatHaze {
public:
    /// BB_HEAT_HAZE gives a strength above 0 (read once; the first call says the knobs' state).
    [[nodiscard]] static bool Wanted();
    HeatHaze(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
             Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~HeatHaze();
    HeatHaze(const HeatHaze&) = delete;
    HeatHaze& operator=(const HeatHaze&) = delete;

    /// The place before the upscaler is never reached: said once.
    void NoSceneHooks();
    /// A G-buffer pass begins: the lamps gathered so far were another view's.
    void ClearLights() {
        collector.Clear();
    }
    /// One tile's light list of the lamp pass (`count` records of 16 words).
    void AddLights(const u32* records, u32 count) {
        collector.Add(records, count);
    }
    /// Right before the upscaler's trigger: the columns of this frame's flames into `color`
    /// (the scene colour), depth tested against `depth` (the scene's). `wind`: m/s in the world
    /// (zero without BB_WIND).
    void Apply(VideoCore::ImageId color, VideoCore::ImageId depth, std::array<float, 2> jitter,
               const std::array<float, 3>& wind);

private:
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    vk::ImageView CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect);
    bool EnsureAtlas(u32 width, u32 height);
    void Report();

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    ::BbHeatHaze::Knobs knobs;
    ::BbHeatHaze::Collector collector;
    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    bool made = false;
    VideoCore::UniqueImage atlas_image;
    vk::UniqueImageView atlas_view;
    u32 atlas_width = 0, atlas_height = 0;
    u32 refused_width = 0, refused_height = 0; ///< a scene size the atlas found no room at
    std::array<ViewEntry, 4> view_cache{};
    u64 view_uses = 0;
    std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();

    /// For the line after the first 120 frames that reached the upscaler, then every 600.
    struct Stats {
        u32 frames = 0;      ///< frames that reached the place before the upscaler
        u32 lit = 0;         ///< of them with at least one column drawn
        u64 columns = 0;     ///< columns drawn
        u64 flames = 0;      ///< flames kept (distinct, in front, nearer than FadeEnd), a frame
        u64 records = 0;     ///< light records seen
        u64 others = 0;      ///< records not of a flame
        u64 beyond = 0;      ///< flame records behind the camera or beyond FadeEnd
        u64 dropped = 0;     ///< flame records over BbHeatHaze::MaxLamps
        u64 unseen = 0;      ///< kept flames without a column (off screen, too short or small)
        u64 over = 0;        ///< columns beyond BbHeatHaze::MaxColumns
        u64 no_room = 0;     ///< columns the atlas had no room for
        u32 no_camera = 0;   ///< frames with flames but no camera, or a menu's preview
        u32 no_scene = 0;    ///< frames whose scene colour could not be written (not storage)
        u32 no_memory = 0;   ///< frames without room for the atlas
        float nearest = 0.0f;   ///< m: the nearest flame with a column
        float most_px = 0.0f;   ///< the largest shimmer reach of a column, px
        u64 pixels = 0;         ///< pixels under the columns' rectangles (each pass reads them)
    } stats;
    bool reported = false; ///< the first line (after FirstLineFrames) went out
    bool told_size = false;
};

} // namespace Vulkan
'''
NEW[R + "vk_heat_haze.cpp"] = r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97_heat-haze): the heat haze above flames (vk_heat_haze.h; the numbers in heat_haze.h,
// the pass in host_shaders/heat_haze.comp).

#include "video_core/renderer_vulkan/vk_heat_haze.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>

#include "bbport_toggles.h"
#include "video_core/host_shaders/heat_haze_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr auto StorageImage = vk::DescriptorType::eStorageImage;
constexpr auto SampledImage = vk::DescriptorType::eSampledImage;
constexpr vk::ImageSubresourceRange ColorRange{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
constexpr u32 LineFrames = 600;
constexpr u32 FirstLineFrames = 120; ///< the first line comes sooner, for short test runs
constexpr u64 ProfileRow = 97; ///< EffectPass::Mark: the row "Lighting: heat haze"

/// BB_HEAT_HAZE and BB_HEAT_HAZE_SHOW, read once (the first caller: Wanted, at the rasterizer's
/// start). Set to something that is off, it says so.
const BbHeatHaze::Knobs& ReadKnobs() {
    static const BbHeatHaze::Knobs knobs = [] {
        const char* haze = std::getenv("BB_HEAT_HAZE");
        const BbHeatHaze::Knobs read = BbHeatHaze::Parse(haze, std::getenv("BB_HEAT_HAZE_SHOW"));
        if (read.unreadable) {
            std::printf("Heat haze (r97): BB_HEAT_HAZE=%.16s is not a number: off\n", haze);
        } else if (haze != nullptr && haze[0] != 0 && !(read.strength > 0.0f)) {
            std::printf("Heat haze (r97): BB_HEAT_HAZE=%.16s: off\n", haze);
        }
        return read;
    }();
    return knobs;
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet Write(u32 binding, vk::DescriptorType type,
                             const vk::DescriptorImageInfo* image) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type,
            .pImageInfo = image};
}

bool Overlap(const std::array<s32, 4>& a, const std::array<s32, 4>& b) {
    return a[0] < b[0] + b[2] && b[0] < a[0] + a[2] && a[1] < b[1] + b[3] && b[1] < a[1] + a[3];
}
} // namespace

bool HeatHaze::Wanted() {
    return ReadKnobs().strength > 0.0f;
}

HeatHaze::HeatHaze(const Instance& instance_, Scheduler& scheduler_,
                   VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                   SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_}, knobs{ReadKnobs()} {
    // The pipeline is made here, at the start (no compile in play); the atlas at the first
    // frame with a column, at that scene's size.
    made = EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
           EffectPass::Create(instance, set_layout, layout, pipeline,
                              {StorageImage, StorageImage, SampledImage},
                              sizeof(BbHeatHaze::Push), HEAT_HAZE_COMP, "Heat haze");
    std::printf("Heat haze (r97, BB_HEAT_HAZE=%.2f): %s; a shimmer in a column above each flame "
                "(a warm lamp of the game's lamp pass), at most %u columns a frame, up to %.0f m "
                "away, drawn into the scene colour right before the upscaler (under the HUD); "
                "test view %s\n",
                double(knobs.strength), made ? "on" : "off - the pass could not be made",
                BbHeatHaze::MaxColumns, double(BbHeatHaze::FadeEnd),
                knobs.show ? "on (BB_HEAT_HAZE_SHOW=1: 3 times the shimmer, the columns tinted)"
                           : "off");
}

HeatHaze::~HeatHaze() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
}

void HeatHaze::NoSceneHooks() {
    std::printf("Heat haze (r97): not drawn - the upscaler is not available (BB_UPSCALER=none, or "
                "this GPU cannot run it), and the haze is drawn right before it\n");
}

vk::ImageView HeatHaze::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid &&
            entry.aspect == aspect) {
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
        .aspect = aspect,
        .view = Check<"create heat haze view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool HeatHaze::EnsureAtlas(u32 width, u32 height) {
    if (atlas_image && atlas_width == width && atlas_height == height) {
        return true;
    }
    if (width == refused_width && height == refused_height) {
        return false;
    }
    const vk::DeviceSize bytes = 8ull * width * height;
    if (!EffectPass::HasRoom(instance, bytes)) {
        refused_width = width;
        refused_height = height;
        std::printf("Heat haze (r97): no room in video memory for its atlas of %ux%u (%llu bytes); "
                    "asked again when the scene's size changes\n",
                    width, height, static_cast<unsigned long long>(bytes));
        return false;
    }
    refused_width = refused_height = 0;
    if (atlas_image) {
        scheduler.DeferOperation(
            [image = std::move(atlas_image), view = std::move(atlas_view)]() mutable {
                view.reset();
                image.Destroy();
            });
    }
    const auto device = instance.GetDevice();
    atlas_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    atlas_image.Create(vk::ImageCreateInfo{
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    SetObjectName(device, vk::Image(atlas_image), "Heat haze atlas");
    atlas_view = Check<"create heat haze atlas view">(device.createImageViewUnique({
        .image = vk::Image(atlas_image),
        .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .subresourceRange = ColorRange,
    }));
    atlas_width = width;
    atlas_height = height;
    std::printf("Heat haze (r97): atlas %ux%u RGBA16F (%llu bytes) for a scene of %ux%u\n", width,
                height, static_cast<unsigned long long>(bytes), width * 2, height * 2);
    return true;
}

void HeatHaze::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                     std::array<float, 2> jitter, const std::array<float, 3>& wind) {
    ++stats.frames;
    const auto lamps = collector.Lamps();
    stats.records += collector.Records();
    stats.others += collector.Others();
    stats.dropped += collector.Dropped();
    stats.beyond += collector.Beyond();
    stats.flames += lamps.size();
    // The frame's lamps are used once: the next frame gathers its own (a frame that draws no
    // G-buffer pass gathers none).
    // The first line after FirstLineFrames (a short test run sees it), then every LineFrames.
    const auto done = [&] {
        collector.Clear();
        if (stats.frames >= (reported ? LineFrames : FirstLineFrames)) {
            reported = true;
            Report();
        }
    };
    if (!made || lamps.empty() || !color_id || !depth_id) {
        done();
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    if (camera_motion.PreviewFrame() || !camera.valid) {
        ++stats.no_camera;
        done();
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    auto& depth = texture_cache.GetImage(depth_id);
    if (color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat) {
        ++stats.no_scene;
        done();
        return;
    }
    // The scene's size is the reduced one while a preset renders below the game's own size,
    // else the game's render size (its targets may be allocated larger).
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    if (width < 16 || height < 16) {
        done();
        return;
    }
    const BbHeatHaze::Camera view{camera.view, camera.inv_view, camera.proj, width, height, jitter};
    const auto atlas = BbHeatHaze::AtlasFor(width, height);
    BbHeatHaze::Counts counts;
    const auto columns =
        BbHeatHaze::Choose(lamps, view, knobs.strength, knobs.show, wind, atlas, counts);
    stats.unseen += counts.unseen;
    stats.over += counts.over;
    stats.no_room += counts.no_room;
    if (columns.empty()) {
        done();
        return;
    }
    if (!EnsureAtlas(atlas.width, atlas.height)) {
        ++stats.no_memory;
        done();
        return;
    }
    const SceneUseScope scene_use{"heat haze"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{};
    if (reduced) {
        VideoCore::ImageViewInfo color_info, depth_info;
        color_info.format = color.info.pixel_format;
        depth_info.format = depth.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, color_info, Compute, ReadWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            done();
            return;
        }
        color_view = proxy.view;
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            done();
            return;
        }
        color_view = CachedView(color, vk::ImageAspectFlagBits::eColor);
        depth_view = CachedView(depth, vk::ImageAspectFlagBits::eDepth);
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();
    // Real time (wrapped, for the floats), so the shimmer rises at its speed at any frame rate.
    const float time = float(std::fmod(
        std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count(), 4096.0));
    std::array<BbHeatHaze::Push, BbHeatHaze::MaxColumns> pushes{};
    // barrier[i]: column i's rectangle overlaps one drawn before it; its haze waits for theirs.
    std::array<bool, BbHeatHaze::MaxColumns> barrier{};
    const u32 count = u32(std::min<std::size_t>(columns.size(), BbHeatHaze::MaxColumns));
    for (u32 i = 0; i < count; ++i) {
        pushes[i] = columns[i].push;
        pushes[i].clock[2] = time;
        for (u32 j = 0; j < i && !barrier[i]; ++j) {
            barrier[i] = Overlap(pushes[i].rect, pushes[j].rect);
        }
        stats.pixels += u64(pushes[i].rect[2]) * u64(pushes[i].rect[3]);
        stats.most_px = std::max(stats.most_px, pushes[i].shape[2]);
        stats.nearest = stats.columns == 0 && i == 0
                            ? columns[i].distance
                            : std::min(stats.nearest, columns[i].distance);
    }
    stats.columns += count;
    ++stats.lit;
    if (!told_size) {
        told_size = true;
        std::printf("Heat haze (r97): first columns drawn, %u at a scene of %ux%u (%s)\n", count,
                    width, height, reduced ? "reduced scene" : "the game's scene");
    }
    EffectPass::Mark(ProfileRow, "heat haze");
    scheduler.RecordCrumb(
        {.name = "heat haze"},
        [pushes, barrier, count, color_view, depth_view, atlas_handle = vk::Image(atlas_image),
         atlas_handle_view = *atlas_view, pass_pipeline = *pipeline,
         pass_layout = *layout](vk::CommandBuffer cmdbuf) {
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute, ReadWrite);
            // The atlas is written anew where it is read; what it held before is of no use.
            const vk::ImageMemoryBarrier2 to_general{
                .srcStageMask = AllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eNone,
                .dstStageMask = Compute,
                .dstAccessMask = ReadWrite,
                .oldLayout = vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eGeneral,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = atlas_handle,
                .subresourceRange = ColorRange,
            };
            cmdbuf.pipelineBarrier2(
                {.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            const std::array infos{Info(color_view), Info(atlas_handle_view), Info(depth_view)};
            const std::array writes{Write(0, StorageImage, &infos[0]),
                                    Write(1, StorageImage, &infos[1]),
                                    Write(2, SampledImage, &infos[2])};
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            for (const s32 pass : {BbHeatHaze::PassCopy, BbHeatHaze::PassHaze}) {
                for (u32 i = 0; i < count; ++i) {
                    if (pass == BbHeatHaze::PassHaze && barrier[i]) {
                        EffectPass::ComputeBarrier(cmdbuf);
                    }
                    BbHeatHaze::Push push = pushes[i];
                    push.atlas[2] = pass;
                    cmdbuf.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(push), &push);
                    cmdbuf.dispatch((u32(push.rect[2]) + 7) / 8, (u32(push.rect[3]) + 7) / 8, 1);
                }
                if (pass == BbHeatHaze::PassCopy) {
                    EffectPass::ComputeBarrier(cmdbuf);
                }
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands, MemoryAll);
        });
    done();
}

void HeatHaze::Report() {
    const double f = std::max(1.0, double(stats.frames));
    const double drawn = std::max(1.0, double(stats.lit));
    BbReport::Printf(
        "Heat haze (r97): of %u frames before the upscaler %u drew columns, %.2f a frame (%llu in "
        "all); a frame %.1f flames kept among %.1f light records (%.1f records not of a flame, "
        "%.1f flame records behind the camera or beyond %.0f m, %llu flame records over %u); %llu "
        "kept flames without a column (off the screen, too short or too small), %llu columns "
        "beyond %u, %llu without room in the atlas; %u frames without a "
        "camera, %u whose scene colour was not writable, %u without video memory for the atlas; "
        "nearest flame with a column %.1f m, largest shimmer %.1f px, %.0f pixels under the "
        "columns a drawing frame\n",
        stats.frames, stats.lit, double(stats.columns) / f,
        static_cast<unsigned long long>(stats.columns), double(stats.flames) / f,
        double(stats.records) / f, double(stats.others) / f, double(stats.beyond) / f,
        double(BbHeatHaze::FadeEnd), static_cast<unsigned long long>(stats.dropped),
        BbHeatHaze::MaxLamps, static_cast<unsigned long long>(stats.unseen),
        static_cast<unsigned long long>(stats.over), BbHeatHaze::MaxColumns,
        static_cast<unsigned long long>(stats.no_room), stats.no_camera, stats.no_scene,
        stats.no_memory, double(stats.nearest), double(stats.most_px),
        double(stats.pixels) / drawn);
    stats = {};
}

} // namespace Vulkan
'''
NEW[H + "heat_haze.comp"] = r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97_heat-haze): the heat haze above flames (BB_HEAT_HAZE; vk_heat_haze.cpp, the column's
// numbers from heat_haze.h). One dispatch a column and pass, over the column's rectangle:
//  - pass 0 (copy): the scene under the rectangle into the column's place in the atlas;
//  - pass 1 (haze): inside the column (from the flame up to its top, widening, fading in just
//    above the flame and out towards the top and the sides), each pixel takes the atlas's colour
//    a little beside it, moved by a noise that rises with time: a shimmer of a few pixels.
//    What is nearer the camera than the flame (by more than the column's radius and a margin)
//    is neither moved nor moved into a pixel behind the column. Alpha stays the pixel's own.
// The scene is written only where a pixel moves; the copy is read, so no pixel reads another
// one this pass has already written.
#version 450
#extension GL_EXT_samplerless_texture_functions : require

layout(local_size_x = 8, local_size_y = 8) in;

layout(binding = 0, rgba16f) uniform image2D scene_img;
layout(binding = 1, rgba16f) uniform image2D atlas_img;
layout(binding = 2) uniform texture2D depth_tex; // D32, depth 0..1 (D3D projection)

// heat_haze.h Push, field for field.
layout(push_constant) uniform Push {
    ivec4 rect;  // x, y, width, height in the scene
    ivec4 atlas; // x, y in the atlas; pass (0 copy, 1 haze); flags (1 show)
    vec4 axis;   // the flame's x, y and the top's x, y (pixels)
    vec4 shape;  // half width at the flame (px), widening to the top, reach (px), flame's view z
    vec4 field;  // pixels a metre at the flame, depth margin (m), fade, seed
    vec4 clock;  // projection z scale, z offset, time (s), rise (m/s)
};

uint Hash(uvec3 v) {
    v = v * 1664525u + 1013904223u;
    v.x += v.y * v.z;
    v.y += v.z * v.x;
    v.z += v.x * v.y;
    v ^= v >> 16u;
    v.x += v.y * v.z;
    return v.x;
}

float Corner(ivec3 c) {
    return float(Hash(uvec3(c & 1023)) >> 8u) * (1.0 / 16777216.0);
}

// Value noise in [0, 1), smooth (quintic) between the lattice's corners.
float Noise(vec3 p) {
    const vec3 f = floor(p);
    const ivec3 i = ivec3(f);
    const vec3 u = p - f;
    const vec3 s = u * u * u * (u * (u * 6.0 - 15.0) + 10.0);
    const float x00 = mix(Corner(i), Corner(i + ivec3(1, 0, 0)), s.x);
    const float x10 = mix(Corner(i + ivec3(0, 1, 0)), Corner(i + ivec3(1, 1, 0)), s.x);
    const float x01 = mix(Corner(i + ivec3(0, 0, 1)), Corner(i + ivec3(1, 0, 1)), s.x);
    const float x11 = mix(Corner(i + ivec3(0, 1, 1)), Corner(i + ivec3(1, 1, 1)), s.x);
    return mix(mix(x00, x10, s.y), mix(x01, x11, s.y), s.z);
}

// The view z (m) of a scene pixel; the sky is far behind every flame.
float ViewZ(ivec2 p) {
    const float depth = texelFetch(depth_tex, p, 0).r;
    if (depth >= 1.0) {
        return 1e9;
    }
    return clock.y / min(depth - clock.x, -1e-8);
}

vec4 Atlas(ivec2 t) {
    return imageLoad(atlas_img, clamp(t, atlas.xy, atlas.xy + rect.zw - 1));
}

void main() {
    const ivec2 local = ivec2(gl_GlobalInvocationID.xy);
    if (any(greaterThanEqual(local, rect.zw))) {
        return;
    }
    const ivec2 p = rect.xy + local;
    const ivec2 own = atlas.xy + local;
    if (atlas.z == 0) {
        imageStore(atlas_img, own, imageLoad(scene_img, p));
        return;
    }
    const vec2 base = axis.xy;
    const vec2 along = axis.zw - base;
    const float len = max(length(along), 1.0);
    const vec2 dir = along / len;
    const vec2 across_dir = vec2(-dir.y, dir.x);
    const vec2 rel = vec2(p) + 0.5 - base;
    const float t = dot(rel, dir) / len;
    if (t <= 0.0 || t >= 1.0) {
        return;
    }
    const float half_width = shape.x * (1.0 + shape.y * t);
    const float across = dot(rel, across_dir);
    const float x = across / max(half_width, 0.5);
    if (abs(x) >= 1.0) {
        return;
    }
    const float side = 1.0 - x * x;
    const float weight = smoothstep(0.0, 0.12, t) * pow(1.0 - t, 1.5) * side * side * field.z;
    if (weight < 1.0 / 256.0) {
        return;
    }
    const float front = shape.w - field.y;
    if (ViewZ(p) < front) {
        return;
    }
    // The pattern in metres around the column (eddies of about 11 and 5 cm across, 17 and 7 cm
    // along it), rising at clock.w m/s and changing slowly as it goes.
    const float per_metre = max(field.x, 1e-3);
    const float time = clock.z;
    const vec3 q = vec3(across / per_metre * 9.0, (t * len / per_metre - time * clock.w) * 6.0,
                        field.w + time * 0.35);
    const float n1 = Noise(q) + 0.5 * Noise(q * 2.3 + vec3(7.1, 3.7, 1.3));
    const float n2 = Noise(q + vec3(19.7, 5.3, 11.1)) + 0.5 * Noise(q * 2.3 + vec3(2.9, 13.1, 4.7));
    const vec2 d = vec2(n1 - 0.75, 0.5 * (n2 - 0.75)) * (1.0 / 0.75);
    const vec2 offset = (across_dir * d.x + dir * d.y) * (shape.z * weight);
    const vec2 source = vec2(p) + 0.5 + offset;
    const ivec2 source_pixel = clamp(ivec2(floor(source)), rect.xy, rect.xy + rect.zw - 1);
    if (ViewZ(source_pixel) < front) {
        return;
    }
    // Between the four atlas texels around the source.
    const vec2 at = source - vec2(rect.xy) + vec2(atlas.xy) - 0.5;
    const ivec2 lo = ivec2(floor(at));
    const vec2 f = at - vec2(lo);
    const vec4 colour = mix(mix(Atlas(lo), Atlas(lo + ivec2(1, 0)), f.x),
                            mix(Atlas(lo + ivec2(0, 1)), Atlas(lo + ivec2(1, 1)), f.x), f.y);
    vec3 rgb = colour.rgb;
    if ((atlas.w & 1) != 0) {
        // Test view: the column tinted blue-green, its brightness kept but at least a tenth of
        // the flame's (the pixel at the flame, from the copy): at night the air above a flame
        // is often near black, where a tint alone would not show.
        const vec3 luma_weights = vec3(0.2126, 0.7152, 0.0722);
        const vec3 flame = Atlas(atlas.xy + ivec2(floor(axis.xy)) - rect.xy).rgb;
        const float luma = max(dot(rgb, luma_weights), 0.1 * dot(max(flame, vec3(0.0)), luma_weights));
        rgb = mix(rgb, luma * vec3(0.55, 0.95, 1.5), 0.6 * weight / max(field.z, 1e-3));
    }
    imageStore(scene_img, p, vec4(rgb, imageLoad(atlas_img, own).a));
}
'''
NEW["engine/tests/test_heat_haze.cpp"] = r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97_heat-haze): the heat haze's pure parts (heat_haze.h): the knobs' text, which lamps
// are flames, the lamps kept once, the column above a flame on the screen (up, leaning with the
// wind, fading with distance, left out where it cannot show) and the choice and placing of a
// frame's columns in the atlas.
#include <algorithm>
#include <array>
#include <bit>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <vector>
#include "gpu/shadps4/video_core/renderer_vulkan/heat_haze.h"

using namespace BbHeatHaze;

namespace {
std::array<std::uint32_t, RecordWords> Record(float x, float y, float z, float reach, float r,
                                              float g, float b) {
    std::array<std::uint32_t, RecordWords> record{};
    const float words[7] = {x, y, z, reach > 0.0f ? 1.0f / (reach * reach) : 0.0f, r, g, b};
    for (int i = 0; i < 7; ++i) {
        record[i] = std::bit_cast<std::uint32_t>(words[i]);
    }
    record[9] = 0xdeadbeefu; // words the game keeps other things in: not part of the key
    return record;
}

Lamp Torch(float x, float y, float z, float reach = 8.5f) {
    return Lamp{{x, y, z}, reach, {2.49f, 1.40f, 0.63f}};
}

// A camera looking down view +z, world +y up, ndc +y down the screen (the y scale negative).
Camera Straight(std::uint32_t width = 1920, std::uint32_t height = 1080) {
    Camera camera;
    camera.view = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
    camera.inv_view = camera.view;
    camera.proj = {1.7f * 1080.0f / 1920.0f, -1.7f, 1.0f, -0.1f};
    camera.width = width;
    camera.height = height;
    return camera;
}

bool Near(float a, float b, float tolerance) {
    return std::abs(a - b) <= tolerance;
}

bool Inside(const Push& push, float x, float y) {
    return x >= float(push.rect[0]) && x <= float(push.rect[0] + push.rect[2]) &&
           y >= float(push.rect[1]) && y <= float(push.rect[1] + push.rect[3]);
}
} // namespace

int main() {
    // a. The knobs.
    {
        assert(Parse(nullptr, nullptr).strength == 0.0f && !Parse(nullptr, nullptr).unreadable);
        assert(Parse("", "1").strength == 0.0f && !Parse("", "1").show);
        assert(Parse("1", nullptr).strength == 1.0f && !Parse("1", nullptr).show);
        assert(Parse("0.5", "1").strength == 0.5f && Parse("0.5", "1").show);
        assert(Parse("2.5", nullptr).strength == MaxStrength);
        assert(Parse("-1", "1").strength == 0.0f && !Parse("-1", "1").unreadable &&
               !Parse("-1", "1").show);
        assert(Parse("0", "1").strength == 0.0f && !Parse("0", "1").show);
        assert(Parse("on", nullptr).unreadable && Parse("on", nullptr).strength == 0.0f);
        assert(Parse("1 ", nullptr).unreadable && Parse("nan", nullptr).unreadable &&
               Parse("inf", nullptr).unreadable);
        assert(!Parse("1", "2").show && !Parse("1", "11").show && !Parse("1", "").show);
    }
    // b. A record as a lamp.
    {
        const auto torch = Record(1, 2, 3, 8.5f, 2.49f, 1.40f, 0.63f);
        const auto lamp = ReadLamp(torch.data());
        assert(lamp && Near(lamp->reach, 8.5f, 1e-4f) && lamp->view[2] == 3.0f &&
               lamp->colour[0] == 2.49f);
        assert(!ReadLamp(Record(1, 2, 3, 0.0f, 1, 1, 1).data()));
        auto bad = torch;
        bad[5] = std::bit_cast<std::uint32_t>(NAN);
        assert(!ReadLamp(bad.data()));
    }
    // c. Flames: warm and of a flame's reach; not white, cold, red or huge.
    {
        assert(IsFlame(Torch(0, 0, 3)));
        assert(IsFlame(Lamp{{0, 0, 3}, 3.0f, {1.0f, 0.7f, 0.4f}}));   // a warm yellow candle
        assert(!IsFlame(Lamp{{0, 0, 3}, 8.0f, {1.0f, 1.0f, 1.0f}}));  // white
        assert(!IsFlame(Lamp{{0, 0, 3}, 8.0f, {1.0f, 0.9f, 0.8f}}));  // warm white
        assert(!IsFlame(Lamp{{0, 0, 3}, 8.0f, {0.4f, 0.6f, 1.0f}}));  // cold (moonlight)
        assert(!IsFlame(Lamp{{0, 0, 3}, 8.0f, {1.0f, 0.1f, 0.0f}}));  // red
        assert(!IsFlame(Lamp{{0, 0, 3}, 8.0f, {0.01f, 0.006f, 0.002f}})); // too dim
        assert(!IsFlame(Torch(0, 0, 3, 30.0f)) && !IsFlame(Torch(0, 0, 3, 0.3f)));
    }
    // d. The collector keeps each flame once and counts the rest.
    {
        Collector collector;
        std::vector<std::uint32_t> list;
        for (int tile = 0; tile < 3; ++tile) { // the same two lamps in three tiles
            const auto a = Record(0, 0, 3, 8.5f, 2.49f, 1.40f, 0.63f);
            const auto b = Record(0, 0, 4, 5.0f, 0.4f, 0.6f, 1.0f); // cold: not a flame
            list.insert(list.end(), a.begin(), a.end());
            list.insert(list.end(), b.begin(), b.end());
        }
        collector.Add(list.data(), 6);
        assert(collector.Lamps().size() == 1 && collector.Records() == 6 &&
               collector.Others() == 3 && collector.Dropped() == 0);
        // More flames than MaxLamps, the farthest first (tile order is no order of distance):
        // the MaxLamps nearest are kept.
        list.clear();
        for (std::uint32_t i = 0; i < MaxLamps + 5; ++i) {
            const float x = 0.2f * float(MaxLamps + 4 - i);
            const auto r = Record(x, 0, 5, 8.5f, 2.49f, 1.40f, 0.63f);
            list.insert(list.end(), r.begin(), r.end());
        }
        collector.Clear();
        assert(collector.Lamps().empty() && collector.Records() == 0);
        collector.Add(list.data(), MaxLamps + 5);
        assert(collector.Lamps().size() == MaxLamps && collector.Dropped() == 5);
        float nearest_x = 100.0f, farthest_x = 0.0f;
        for (const Lamp& lamp : collector.Lamps()) {
            nearest_x = std::min(nearest_x, lamp.view[0]);
            farthest_x = std::max(farthest_x, lamp.view[0]);
        }
        assert(nearest_x == 0.0f && Near(farthest_x, 0.2f * float(MaxLamps - 1), 1e-4f));
        // Flames behind the camera plane or FadeEnd away are not kept, only counted.
        list.clear();
        for (const float z : {-1.0f, 0.1f, FadeEnd + 0.5f, 3.0f}) {
            const auto r = Record(0, 0, z, 8.5f, 2.49f, 1.40f, 0.63f);
            list.insert(list.end(), r.begin(), r.end());
        }
        collector.Clear();
        collector.Add(list.data(), 4);
        assert(collector.Lamps().size() == 1 && collector.Beyond() == 3 && collector.Others() == 0 &&
               collector.Lamps()[0].view[2] == 3.0f);
    }
    // e. The column above a torch 3 m ahead: from the flame up the screen.
    const std::array<float, 3> still{};
    {
        const Camera camera = Straight();
        const auto column = MakeColumn(Torch(0, 0, 3), camera, 1.0f, false, still);
        assert(column);
        const Push& p = column->push;
        assert(Near(p.axis[0], 960.0f, 0.01f) && Near(p.axis[1], 540.0f, 0.01f));
        assert(Near(p.axis[2], 960.0f, 0.01f) && p.axis[3] < p.axis[1] - 50.0f); // up
        // 8.5 m reach: 0.595 m tall, 0.1275 m radius; 306 pixels a metre at 3 m.
        const float per_metre = 0.5f * 1080.0f * 1.7f / 3.0f;
        assert(Near(p.field[0], per_metre, 0.01f));
        assert(Near(p.axis[1] - p.axis[3], 0.595f * per_metre, 0.05f));
        assert(Near(p.shape[0], 0.1275f * per_metre, 0.01f) && p.shape[1] == Widen);
        assert(Near(p.shape[2], std::min(AmplitudeM * per_metre, MaxAmplitudePx), 1e-3f) &&
               p.shape[3] == 3.0f);
        assert(Near(p.field[1], 0.1275f + DepthMarginM, 1e-5f) && p.field[2] == 1.0f);
        assert(p.clock[0] == 1.0f && p.clock[1] == -0.1f && p.clock[3] == RiseMps);
        assert(p.atlas[2] == PassHaze && p.atlas[3] == 0);
        assert(Inside(p, p.axis[0], p.axis[1]) && Inside(p, p.axis[2], p.axis[3]));
        assert(p.rect[0] >= 0 && p.rect[1] >= 0 && p.rect[0] + p.rect[2] <= 1920 &&
               p.rect[1] + p.rect[3] <= 1080);
        // Strength and the test view scale the shimmer; jitter moves the column with the frame.
        const auto strong = MakeColumn(Torch(0, 0, 3), camera, 2.0f, false, still);
        const auto shown = MakeColumn(Torch(0, 0, 3), camera, 1.0f, true, still);
        assert(Near(strong->push.shape[2], 2.0f * p.shape[2], 1e-4f));
        assert(Near(shown->push.shape[2], ShowGain * p.shape[2], 1e-4f) &&
               shown->push.atlas[3] == FlagShow);
        Camera jittered = camera;
        jittered.jitter = {0.25f, -0.5f};
        const auto moved = MakeColumn(Torch(0, 0, 3), jittered, 1.0f, false, still);
        assert(Near(moved->push.axis[0], 960.25f, 1e-3f) && Near(moved->push.axis[1], 539.5f, 1e-3f));
        // The shimmer is capped near the camera (8 pixels a 1080 rows at strength 1).
        const auto close = MakeColumn(Torch(0, 0, 0.35f), camera, 1.0f, false, still);
        assert(close && Near(close->push.shape[2], MaxAmplitudePx, 1e-4f));
        // At 4K rows the same torch spans twice the pixels.
        const auto big = MakeColumn(Torch(0, 0, 3), Straight(3840, 2160), 1.0f, false, still);
        assert(Near(big->push.field[0], 2.0f * per_metre, 0.02f));
    }
    // f. The wind leans the top downwind, at most MaxLean of the height.
    {
        const Camera camera = Straight();
        const auto upright = MakeColumn(Torch(0, 0, 3), camera, 1.0f, false, still);
        const auto windy = MakeColumn(Torch(0, 0, 3), camera, 1.0f, false, {2.0f, 0.0f, 0.0f});
        const auto storm = MakeColumn(Torch(0, 0, 3), camera, 1.0f, false, {100.0f, 0.0f, 0.0f});
        const auto back = MakeColumn(Torch(0, 0, 3), camera, 1.0f, false, {-2.0f, 0.0f, 0.0f});
        const float per_metre = upright->push.field[0];
        assert(windy->push.axis[2] > upright->push.axis[2] + 10.0f); // toward +x: right
        assert(back->push.axis[2] < upright->push.axis[2] - 10.0f);
        // (The top is 0.595 m up and 0.15 m a m/s x 2 m/s of that across, at the flame's depth.)
        assert(Near(windy->push.axis[2] - 960.0f, 0.595f * 0.3f * per_metre, 0.5f));
        assert(Near(storm->push.axis[2] - 960.0f, 0.595f * MaxLean * per_metre, 0.5f));
        const auto nan_wind = MakeColumn(Torch(0, 0, 3), camera, 1.0f, false, {NAN, 0.0f, 0.0f});
        assert(nan_wind && Near(nan_wind->push.axis[2], upright->push.axis[2], 1e-3f));
    }
    // g. No column behind the camera, too far, off the screen, or at strength 0; a fade between.
    {
        const Camera camera = Straight();
        assert(!MakeColumn(Torch(0, 0, -1), camera, 1.0f, false, still));
        assert(!MakeColumn(Torch(0, 0, 0.2f), camera, 1.0f, false, still));
        assert(!MakeColumn(Torch(0, 0, FadeEnd + 1.0f), camera, 1.0f, false, still));
        assert(!MakeColumn(Torch(100, 0, 3), camera, 1.0f, false, still));
        assert(!MakeColumn(Torch(0, 0, 3), camera, 0.0f, false, still));
        const auto mid = MakeColumn(Torch(0, 0, 18.5f), camera, 1.0f, false, still);
        assert(mid && mid->push.field[2] > 0.3f && mid->push.field[2] < 0.7f);
        const auto inside = MakeColumn(Torch(0, 0, FadeStart - 1.0f), camera, 1.0f, false, still);
        assert(inside && inside->push.field[2] == 1.0f);
        // Looking straight up at it (the world's up is view +z), the column is a dot: none.
        Camera down = camera;
        down.view = {1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0};
        assert(!MakeColumn(Torch(0, 0, 3), down, 1.0f, false, still));
        // A torch at the screen's edge keeps a column cut to the screen.
        const auto edge = MakeColumn(Torch(-2.05f, 0, 2.0f), camera, 1.0f, false, still);
        assert(edge && edge->push.rect[0] == 0 && edge->push.rect[2] > 0);
    }
    // h. The frame's columns: the largest eight, placed apart in the atlas, farthest first.
    {
        const Camera camera = Straight();
        std::vector<Lamp> lamps;
        for (int i = 0; i < 10; ++i) {
            lamps.push_back(Torch(-2.0f + 0.4f * float(i), 0.0f, 3.0f + float(i)));
        }
        lamps.push_back(Torch(0, 0, -2)); // behind
        Counts counts;
        const Atlas atlas = AtlasFor(1920, 1080);
        assert(atlas.width == 960 && atlas.height == 540);
        const auto columns = Choose(lamps, camera, 1.0f, false, still, atlas, counts);
        assert(counts.unseen == 1 && counts.over == 2 && counts.no_room == 0);
        assert(columns.size() == MaxColumns && counts.made == MaxColumns);
        for (std::size_t i = 0; i < columns.size(); ++i) {
            const Push& a = columns[i].push;
            assert(a.atlas[0] >= 0 && a.atlas[1] >= 0 && a.atlas[0] + a.rect[2] <= 960 &&
                   a.atlas[1] + a.rect[3] <= 540);
            if (i > 0) {
                assert(columns[i - 1].distance >= columns[i].distance);
            }
            for (std::size_t j = 0; j < i; ++j) {
                const Push& b = columns[j].push;
                const bool apart = a.atlas[0] + a.rect[2] <= b.atlas[0] ||
                                   b.atlas[0] + b.rect[2] <= a.atlas[0] ||
                                   a.atlas[1] + a.rect[3] <= b.atlas[1] ||
                                   b.atlas[1] + b.rect[3] <= a.atlas[1];
                assert(apart);
            }
        }
        // The two left out are the smallest (the farthest).
        for (const Column& column : columns) {
            assert(column.distance <= 10.0f + 0.5f);
        }
        // An atlas too small for all of them leaves some out, never one that overlaps.
        const auto few = Choose(lamps, camera, 1.0f, false, still, Atlas{160, 120}, counts);
        assert(counts.no_room > 0 && few.size() + counts.no_room == MaxColumns);
        for (const Column& column : few) {
            assert(column.push.rect[2] <= 160 && column.push.rect[3] <= 120);
        }
        // Nothing to draw: nothing chosen.
        assert(Choose({}, camera, 1.0f, false, still, atlas, counts).empty() && counts.made == 0);
    }
    // i. A column taller than the atlas is cut, keeping the flame's end.
    {
        std::int32_t from = 100, size = 500;
        CutSide(from, size, 200, 560.0f, 150.0f, 10); // rising up the screen: keep the bottom
        assert(size == 200 && from == 560 + 10 - 200);
        from = 100;
        size = 500;
        CutSide(from, size, 200, 150.0f, 560.0f, 10); // upside down: keep the top
        assert(size == 200 && from == 140);
        from = 100;
        size = 500;
        CutSide(from, size, 200, 590.0f, 150.0f, 10); // never past the rectangle's end
        assert(size == 200 && from == 400);
        from = 100;
        size = 150;
        CutSide(from, size, 200, 560.0f, 150.0f, 10); // fits: unchanged
        assert(from == 100 && size == 150);
    }
    // j. Which columns are drawn does not depend on the render size or on the test view.
    {
        for (const float z : {9.0f, 18.5f, 20.0f, 23.0f}) {
            const bool full = MakeColumn(Torch(0, 0, z), Straight(1920, 1080), 1.0f, false, still)
                                  .has_value();
            const bool low = MakeColumn(Torch(0, 0, z), Straight(640, 360), 1.0f, false, still)
                                 .has_value();
            const bool shown = MakeColumn(Torch(0, 0, z), Straight(640, 360), 1.0f, true, still)
                                   .has_value();
            assert(full == low && low == shown);
            assert(full == (z < 19.0f)); // 18.5 m: 0.74 px per 1080 rows; 20 m: 0.46 px
        }
    }
    std::printf("heat-haze-test: all checks passed\n");
    return 0;
}
'''

EDITS = {
    R + "vk_rasterizer.h": [
        ('#include "video_core/renderer_vulkan/vk_card_alpha.h" // bbport (r62_leaf-stage3)\n',
         '#include "video_core/renderer_vulkan/vk_card_alpha.h" // bbport (r62_leaf-stage3)\n'
         '#include "video_core/renderer_vulkan/vk_heat_haze.h" // bbport (r97_heat-haze)\n'),
        ('    std::unique_ptr<DrawnLook> drawn_look; // bbport (r45_drawn-look)\n',
         '    std::unique_ptr<DrawnLook> drawn_look; // bbport (r45_drawn-look)\n'
         '    // bbport (r97_heat-haze): made only while BB_HEAT_HAZE gives a strength above 0\n'
         '    // (HeatHaze::Wanted, read once), else null: its hooks are null pointer tests.\n'
         '    std::unique_ptr<HeatHaze> heat_haze;\n'),
    ],
    R + "vk_rasterizer.cpp": [
        ('    rt_shadow->SetCardLayers(card_bound_on ? card_alpha.get() : nullptr);\n',
         '    rt_shadow->SetCardLayers(card_bound_on ? card_alpha.get() : nullptr);\n'
         '    // bbport (r97_heat-haze): BB_HEAT_HAZE above 0 only: the shimmer above flames, drawn\n'
         '    // right before the upscaler; without the upscaler that place is never reached (said once).\n'
         '    if (HeatHaze::Wanted()) {\n'
         '        heat_haze = std::make_unique<HeatHaze>(instance, scheduler, texture_cache, runtime,\n'
         '                                               *scene_targets, *camera_motion);\n'
         '        if (!upscaler->Enabled()) {\n'
         '            heat_haze->NoSceneHooks();\n'
         '        }\n'
         '    }\n'),
    ],
    R + "vk_rasterizer_effects.cpp": [
        ('    if (gbuffer) {\n'
         '        depth_of_field->Reset();\n',
         '    if (gbuffer) {\n'
         '        depth_of_field->Reset();\n'
         '        if (heat_haze) { // bbport (r97_heat-haze): the lamps of the last G-buffer pass only\n'
         '            heat_haze->ClearLights();\n'
         '        }\n'),
        ('                if (surface_probe_on) { // bbport (r64_surface-probe): the lamps of this tile, logged\n'
         '                    SurfaceProbeLamps(reinterpret_cast<const u32*>(lights), tile_lights);\n'
         '                }\n',
         '                if (surface_probe_on) { // bbport (r64_surface-probe): the lamps of this tile, logged\n'
         '                    SurfaceProbeLamps(reinterpret_cast<const u32*>(lights), tile_lights);\n'
         '                }\n'
         '                if (heat_haze) { // bbport (r97_heat-haze): the flames among this tile\'s lamps\n'
         '                    heat_haze->AddLights(reinterpret_cast<const u32*>(lights), tile_lights);\n'
         '                }\n'),
        ('    // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA_VIEW: the card debug view, last, over all of it.\n',
         '    // bbport (r97_heat-haze): BB_HEAT_HAZE only: the shimmer above flames, after the fog\n'
         '    // composite (the fog behind a flame shimmers too), before the upscaler and the HUD.\n'
         '    if (heat_haze && compute_hash == upscaler->TriggerHash()) {\n'
         '        heat_haze->Apply(upscaler->SceneColor(), camera_motion->Depth(), upscaler->Jitter(),\n'
         '                         wind.Get().wind);\n'
         '    }\n'
         '    // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA_VIEW: the card debug view, last, over all of it.\n'),
    ],
    "engine/gpu/CMakeLists.txt": [
        ('add_host_shader(paint_lock.comp paint_lock_comp)\n',
         'add_host_shader(paint_lock.comp paint_lock_comp)\n'
         '# bbport (r97_heat-haze): the heat haze above flames (BB_HEAT_HAZE; renderer_vulkan/vk_heat_haze.cpp)\n'
         'add_host_shader(heat_haze.comp heat_haze_comp)\n'),
        ('target_include_directories(rt-glass-test PRIVATE ..)\n',
         'target_include_directories(rt-glass-test PRIVATE ..)\n'
         '# bbport (r97_heat-haze): the heat haze\'s knobs, flames, columns and atlas (heat_haze.h); also\n'
         '# built and run by engine/build.sh --test.\n'
         'add_executable(heat-haze-test EXCLUDE_FROM_ALL ../tests/test_heat_haze.cpp)\n'
         'target_compile_options(heat-haze-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n'
         'target_include_directories(heat-haze-test PRIVATE ..)\n'),
    ],
    "engine/build.sh": [
        ('    out/rt-glass-test\n',
         '    out/rt-glass-test\n'
         '    # bbport (r97_heat-haze): the heat haze\'s knobs, flames, columns and atlas\n'
         '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_heat_haze.cpp -o out/heat-haze-test\n'
         '    out/heat-haze-test\n'),
    ],
    "engine/tests/test_effect_pipelines.cpp": [
        ('#include "video_core/host_shaders/paint_strokes_comp.h"\n',
         '#include "video_core/host_shaders/paint_strokes_comp.h"\n'
         '#include "video_core/host_shaders/heat_haze_comp.h" // bbport (r97_heat-haze)\n'),
        ('        {"ssgi prep", SSGI_PREP_COMP, {eSampledImage, eStorageImage, eSampledImage}, 128},\n',
         '        // bbport (r97_heat-haze): as vk_heat_haze.cpp makes it (BbHeatHaze::Push, 96 bytes)\n'
         '        {"heat haze", HEAT_HAZE_COMP, {eStorageImage, eStorageImage, eSampledImage}, 96},\n'
         '        {"ssgi prep", SSGI_PREP_COMP, {eSampledImage, eStorageImage, eSampledImage}, 128},\n'),
    ],
    "README.md": [
        ('## Sponsors\n',
         '### Heat haze (in development)\n'
         '\n'
         'A shimmer of rising warm air above flames: the hunter\'s torch, candles, lanterns, the flames of lamps and bonfires. The game itself moves no pixel behind a flame (its fire is drawn as sprites that read no copy of the picture), so this adds the haze and doubles nothing. Off unless `BB_HEAT_HAZE` is set. These environment variables are read once when the game starts; they are for testing, no ini key yet.\n'
         '\n'
         '| Variable | What it does | Default |\n'
         '|---|---|---|\n'
         '| `BB_HEAT_HAZE` | Strength of the haze, a number from 0 to 2 (above 2 counts as 2; 0, unset or text that is not a number is off); `1` is the look as designed. Each warm light of the game\'s lamp pass (orange to warm yellow, reaching 0.5 to 20 m) is taken for a flame, and a column of rising air stands above it: 7% of the light\'s reach tall (0.3 to 1 m), with a radius of 1.5% of the reach at the flame (0.05 to 0.18 m) and 1.8 times that at its top. Inside it, each pixel behind the flame takes its colour from a little beside it, moved by a noise that rises at 0.6 m/s: at strength 1 by up to 0.03 m at the flame\'s distance (at most 8 pixels per 1080 rows; the root mean square of the noise is 0.3 of that), most just above the flame, fading to the top and the sides. A column whose largest move would stay under 0.6 pixels per 1080 rows is not drawn. What stands nearer the camera than the flame by more than the column\'s radius and 0.15 m is not moved. The haze fades from 12 m and is gone at 25 m; of the flames in front of the camera and nearer than that the 32 nearest are looked at, and at most 8 columns are drawn a frame, the largest on the screen. With `BB_WIND=1` the column leans downwind, 0.15 of its height per m/s, at most 0.6. Drawn into the scene colour right before the upscaler, so the HUD is never moved and the upscaler takes the haze as it takes the game\'s fire; without the upscaler (`BB_UPSCALER=none`) it is not drawn. The lamps are read where the engine\'s own effects look at the game\'s lamp pass, so one of them must be on (indirect light, contact shadows, PCSS, volumetric sunlight, lamp fog, lamp shadows, ray tracing, the Froyok bloom, GTAO or the modern SSR). Cost: an estimate of 0.01 to 0.05 ms at 1080p internal (two small compute passes over the columns only, nothing without a flame in view), not measured; read it on the `Lighting: heat haze` row of `BB_GPU_PROFILE=1`. Memory: a copy of half the scene\'s width and height, RGBA16F (4.1 MB at 1080p internal), made at the first frame with a column. The log says at the start that it is on, once when the first columns are drawn, and after the first 120 frames and then every 600 how many frames drew columns | off |\n'
         '| `BB_HEAT_HAZE_SHOW` | Test view, with `BB_HEAT_HAZE` above 0: `1` makes the shimmer 3 times wider and tints the columns blue-green (at least a tenth as bright as the flame), so where they stand shows in a still picture; it draws the same columns as without it | off |\n'
         '\n'
         '## Sponsors\n'),
    ],
}

# Text checks on the patched result: (text, count).
CHECKS = {
    R + "vk_rasterizer.h": [('#include "video_core/renderer_vulkan/vk_heat_haze.h"', 1),
                            ("std::unique_ptr<HeatHaze> heat_haze;", 1)],
    R + "vk_rasterizer.cpp": [("heat_haze = std::make_unique<HeatHaze>(", 1), ("HeatHaze::Wanted()", 1),
                              ("heat_haze->NoSceneHooks();", 1)],
    R + "vk_rasterizer_effects.cpp": [("heat_haze->ClearLights();", 1), ("heat_haze->AddLights(", 1),
                                      ("heat_haze->Apply(", 1), ("if (heat_haze", 3)],
    "engine/gpu/CMakeLists.txt": [("add_host_shader(heat_haze.comp heat_haze_comp)\n", 1),
                                  ("add_executable(heat-haze-test", 1)],
    "engine/build.sh": [("tests/test_heat_haze.cpp -o out/heat-haze-test", 1), ("    out/heat-haze-test\n", 1)],
    "engine/tests/test_effect_pipelines.cpp": [('heat_haze_comp.h"', 1), ("HEAT_HAZE_COMP,", 1)],
    "README.md": [("| `BB_HEAT_HAZE` |", 1), ("| `BB_HEAT_HAZE_SHOW` |", 1), ("### Heat haze", 1)],
}

# Order checks on the patched result: each string after the one before it (first occurrence).
ORDER = {
    R + "vk_rasterizer.cpp": ["upscaler = std::make_unique<TemporalUpscaler>", "card_alpha = std::make_unique<CardAlpha>",
                              "heat_haze = std::make_unique<HeatHaze>", "if (!upscaler->Enabled()) {\n            heat_haze->NoSceneHooks();"],
    R + "vk_rasterizer_effects.cpp": ["void Rasterizer::EffectsAfterTargets(", "depth_of_field->Reset();",
                                      "heat_haze->ClearLights();", "if (!effects_wanted) {",
                                      "void Rasterizer::EffectsBeforeUpscaler(",
                                      'volumetric_light->Composite(upscaler->SceneColor(), "the upscaler");',
                                      "heat_haze->Apply(", "BB_RT_CARD_ALPHA_VIEW: the card debug view",
                                      "void Rasterizer::EffectsBeforeBind(", "SurfaceProbeLamps(reinterpret_cast",
                                      "heat_haze->AddLights(", "point_shadow->OnLightDraw("],
    "README.md": ["### Wind (in development)", "### Heat haze (in development)", "## Sponsors"],
}

# Numbers written twice (rule 10): the header's constants and the README / pipeline test text.
HEADER = R + "heat_haze.h"
TIES = [
    (HEADER, "AmplitudeM = 0.03f;", "README.md", "by up to 0.03 m at the flame"),
    (HEADER, "MinAmplitudePx = 0.6f", "README.md", "under 0.6 pixels per 1080 rows"),
    (HEADER, "MaxLamps = 32;", "README.md", "the 32 nearest are looked at"),
    (R + "vk_heat_haze.cpp", "FirstLineFrames = 120;", "README.md", "after the first 120 frames"),
    (R + "vk_heat_haze.cpp", "LineFrames = 600;", "README.md", "then every 600 how many"),
    (HEADER, "MaxAmplitudePx = 8.0f", "README.md", "at most 8 pixels per 1080 rows"),
    (HEADER, "FadeStart = 12.0f", "README.md", "fades from 12 m"),
    (HEADER, "FadeEnd = 25.0f", "README.md", "gone at 25 m"),
    (HEADER, "MaxColumns = 8;", "README.md", "at most 8 columns are drawn a frame"),
    (HEADER, "RiseMps = 0.6f", "README.md", "rises at 0.6 m/s"),
    (HEADER, "ShowGain = 3.0f", "README.md", "3 times wider"),
    (HEADER, "LeanPerMps = 0.15f", "README.md", "0.15 of its height per m/s"),
    (HEADER, "MaxLean = 0.6f", "README.md", "per m/s, at most 0.6"),
    (HEADER, "HeightPerReach = 0.07f, MinHeight = 0.3f, MaxHeight = 1.0f", "README.md", "7% of the light's reach tall (0.3 to 1 m)"),
    (HEADER, "RadiusPerReach = 0.015f, MinRadius = 0.05f, MaxRadius = 0.18f", "README.md", "radius of 1.5% of the reach at the flame (0.05 to 0.18 m)"),
    (HEADER, "Widen = 0.8f", "README.md", "1.8 times that at its top"),
    (HEADER, "DepthMarginM = 0.15f", "README.md", "radius and 0.15 m"),
    (HEADER, "MinReach = 0.5f, MaxReach = 20.0f", "README.md", "reaching 0.5 to 20 m"),
    (HEADER, "MaxStrength = 2.0f", "README.md", "a number from 0 to 2"),
    (HEADER, "static_assert(sizeof(Push) == 96);", "engine/tests/test_effect_pipelines.cpp", "{eStorageImage, eStorageImage, eSampledImage}, 96}"),
    (R + "vk_heat_haze.cpp", "{StorageImage, StorageImage, SampledImage}", "engine/tests/test_effect_pipelines.cpp", "HEAT_HAZE_COMP, {eStorageImage, eStorageImage, eSampledImage}"),
    (R + "vk_heat_haze.cpp", "constexpr u64 ProfileRow = 97;", "README.md", "`Lighting: heat haze` row"),
]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def new_bytes(text):
    return text.replace("\n", "\r\n").encode("utf-8")


def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d"
                                 % (path, s, texts[path].count(s), n))
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                raise SystemExit("order check: %s: %r not after the one before" % (path, s))
            at = i
    every = dict(texts)
    every.update(NEW)
    for a_path, a_text, b_path, b_text in TIES:
        if every[a_path].count(a_text) != 1 or every[b_path].count(b_text) != 1:
            raise SystemExit("tie check: %r in %s against %r in %s" % (a_text, a_path, b_text, b_path))
    for path, text in NEW.items():
        if not all(ord(c) < 128 for c in text) or "\r" in text:
            raise SystemExit("%s: new text must be ASCII with LF in the script" % path)


def blocks(edits):
    """Each edit as (anchor, block, where): the block is inserted right after or before its anchor
    line(s); apply needs the anchor exactly once and the block nowhere, revert takes out the block
    alone (exactly once), so another patch's lines inserted at the same anchor, before or after
    this one, stay where they are (r95_halation inserts at three of these anchors)."""
    out = []
    for old, new in edits:
        if new.startswith(old):
            out.append((old, new[len(old):], "after"))
        elif new.endswith(old):
            out.append((old, new[:-len(old)], "before"))
        else:
            raise SystemExit("internal: an edit is not an insertion next to its anchor")
    return out


def insert(cur, edits):
    for anchor, block, where in blocks(edits):
        cur = cur.replace(anchor, anchor + block if where == "after" else block + anchor, 1)
    return cur


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R97_HEAT_HAZE_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        parts = blocks(edits)
        done = sum(cur.count(block) == 1 and cur.count(anchor) == 1 for anchor, block, _ in parts)
        todo = sum(cur.count(block) == 0 and cur.count(anchor) == 1 for anchor, block, _ in parts)
        if done == len(parts):
            state = "applied"
        elif todo == len(parts):
            state = "clean"
        else:
            raise SystemExit("REFUSED %s: %d of %d blocks in place, %d insertable (anchor once, block absent)"
                             % (path, done, len(parts), todo))
        plan.append((path, edits, raw, eol, cur, state))
    for path, text in NEW.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            state = "clean"
        elif open(full, "rb").read() == new_bytes(text):
            state = "applied"
        else:
            raise SystemExit("REFUSED %s exists and is not this patch's file" % path)
        plan.append((path, None, None, None, None, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    edited = [p for p in plan if p[1] is not None]
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in edited})
            print("applied (text checks pass)")
        else:
            text_checks({path: insert(cur, edits) for path, edits, raw, eol, cur, _ in edited})
            print("not applied; would apply (%d files edited, %d new; text checks on the result pass)"
                  % (len(edited), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts, outs = {}, []
        for path, edits, raw, eol, cur, _ in edited:
            cur = insert(cur, edits)
            texts[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        for path, text in NEW.items():
            outs.append((path, new_bytes(text), None))
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r97tmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(ROOT, path))
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r97tmp"
                if os.path.exists(tmp):
                    os.remove(tmp)
            for path, raw in written:
                if raw is None:
                    os.remove(os.path.join(ROOT, path))
                else:
                    open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    for path, edits, raw, eol, cur, _ in edited:
        for anchor, block, _ in blocks(edits):
            cur = cur.replace(block, "", 1)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
