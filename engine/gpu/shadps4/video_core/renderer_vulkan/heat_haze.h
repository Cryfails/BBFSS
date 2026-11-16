// SPDX-License-Identifier: GPL-3.0-or-later
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
#include "../host_shaders/heat_haze_layout.h" // bbport (r97b_heat-haze-paths): the shader's numbers

namespace BbHeatHaze {

inline constexpr float MaxStrength = 2.0f;      ///< BB_HEAT_HAZE is clamped to 0..2
/// (r97e) graphics_heat_haze_strength's default: 0, off (tied to BbSettings::HeatHazeStrengthDefault
/// by a static_assert in vk_heat_haze.cpp).
inline constexpr float DefaultStrength = 0.0f;
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
/// m: the most the shimmer moves a pixel at strength 1, at the flame's distance (r97c: the noise's
/// root mean square is 0.49 of it, the column's weight at most 0.94 of that, just above the flame;
/// 0.03 and 0.3 before, which left 69% of a torch's column under half a pixel of move).
inline constexpr float AmplitudeM = 0.045f;
/// Render pixels per 1080 rows (scaled to the scene's rows, so the choice is the same at every
/// render size): the most the shimmer moves a pixel at strength 1 (a flame right at the camera),
/// and the least the column's largest move must reach, after the fade and at the strength but
/// without the test view's gain, for the column to be drawn at all.
inline constexpr float MaxAmplitudePx = 10.0f, MinAmplitudePx = 0.9f; // r97c: 8 and 0.6 before
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
    // bbport (r97b_heat-haze-paths)
    bool outline = false; ///< BB_HEAT_HAZE_SHOW=2: the test view with rectangles, no depth test
    bool depth = true;    ///< the depth tests (vk_heat_haze.cpp: DepthTests and not SHOW=2)
    bool proof = false;   ///< (r97d) BB_HEAT_HAZE_PROOF=1 with a strength above 0: written pixels magenta
};

/// BB_HEAT_HAZE: unset or empty is off; a finite number is the strength, clamped to 0..2 (1 is
/// the look as designed, 0 is off); any other text is off. BB_HEAT_HAZE_SHOW: exactly "1", or
/// (r97b) exactly "2": the test view 1 with each column's rectangle outlined and no depth test.
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
    knobs.show = knobs.strength > 0.0f && show != nullptr && (show[0] == '1' || show[0] == '2') &&
                 show[1] == 0;
    knobs.outline = knobs.show && show[0] == '2'; // bbport (r97b_heat-haze-paths)
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
// bbport (r97b_heat-haze-paths): the other flags, the haze pass's pixel counters and what they
// say. The numbers are heat_haze_layout.h's, the text the shader includes too.
inline constexpr std::int32_t FlagOutline = HH_FLAG_OUTLINE; ///< BB_HEAT_HAZE_SHOW=2: rectangles
inline constexpr std::int32_t FlagNoDepth = HH_FLAG_NO_DEPTH; ///< the depth tests counted only
inline constexpr std::int32_t FlagProbe = HH_FLAG_PROBE; ///< the nearest column: its flame pixel
static_assert(PassCopy == HH_PASS_COPY && PassHaze == HH_PASS_HAZE && FlagShow == HH_FLAG_SHOW);
// bbport (r97d_heat-haze-real-shimmer)
inline constexpr std::int32_t FlagProof = HH_FLAG_PROOF; ///< BB_HEAT_HAZE_PROOF=1: written pixels magenta
static_assert((FlagShow | FlagOutline | FlagNoDepth | FlagProbe | FlagProof) == 31, "one bit each");
static_assert(HH_WORD_OFF_BIN0 + HH_OFF_BINS == HH_WORD_OFF_SUM && HH_WORD_OFF_MAX == HH_WORD_OFF_SUM + 1 &&
                  HH_WORD_OFF_MAX < HH_WORDS && HH_SHARED == HH_WORD_OFF_SUM + 1 && HH_SHARED <= 64 &&
                  HH_WORD_FLAME_LAMP_Z < HH_WORD_OFF_BIN0,
              "the offset words follow the flame words; the shared counters fit one workgroup");
inline constexpr std::uint32_t CounterWords = HH_WORDS; ///< the counter buffer: 4 bytes a word
static_assert(HH_COUNTED == HH_WORD_Z_SKY + 1 && HH_WORD_FLAME_DEPTH == HH_COUNTED &&
              HH_WORD_FLAME_SEEN < HH_WORDS && HH_WORD_FLAME_LAMP_Z < HH_WORDS && HH_COUNTED <= 64,
              "the counted words fit one 8x8 workgroup's first invocations");

/// BB_HEAT_HAZE_DEPTH: exactly "0" turns the depth tests off (what is nearer the camera than the
/// flame shimmers too); unset or any other text keeps them.
inline bool DepthTests(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == 0);
}

/// The haze pass's pixel counts between two reads of the counter words (heat_haze_layout.h).
struct PixelCounts {
    std::uint64_t rect = 0;    ///< pixels in the columns' rectangles
    std::uint64_t shape = 0;   ///< of them outside the column's shape (or too weak to move)
    std::uint64_t nearer = 0;  ///< tested pixels nearer the camera than the depth test's limit
    std::uint64_t source = 0;  ///< tested pixels whose source pixel is nearer than it
    std::uint64_t written = 0; ///< pixels written
    std::uint64_t z_bad = 0, z_close = 0, z_front = 0, z_behind = 0, sky = 0; ///< see the layout
    [[nodiscard]] std::uint64_t Tested() const {
        return rect > shape ? rect - shape : 0;
    }
};

/// The counts since `before` (the words are 32-bit totals; the difference wraps as they do).
inline PixelCounts CountsBetween(const std::uint32_t* now, const std::uint32_t* before) {
    const auto d = [&](std::uint32_t word) {
        return std::uint64_t(std::uint32_t(now[word] - before[word]));
    };
    PixelCounts c;
    c.rect = d(HH_WORD_RECT);
    c.shape = d(HH_WORD_SHAPE);
    c.nearer = d(HH_WORD_NEAR);
    c.source = d(HH_WORD_SOURCE);
    c.written = d(HH_WORD_WRITTEN);
    c.z_bad = d(HH_WORD_Z_BAD);
    c.z_close = d(HH_WORD_Z_CLOSE);
    c.z_front = d(HH_WORD_Z_FRONT);
    c.z_behind = d(HH_WORD_Z_BEHIND);
    c.sky = d(HH_WORD_Z_SKY);
    return c;
}

/// (r97d) The offsets of the written pixels between two reads of the counter words, in render pixels:
/// the mean, the upper edge of the bin the 95th percentile falls in, and the largest since the pass
/// was made (a running maximum).
struct OffsetStats {
    std::uint64_t pixels = 0;
    double mean = 0.0, p95_below = 0.0, largest = 0.0;
};
inline OffsetStats OffsetsBetween(const std::uint32_t* now, const std::uint32_t* before) {
    constexpr double Edge[HH_OFF_BINS] = {0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 4000.0};
    OffsetStats s;
    std::uint64_t bins[HH_OFF_BINS]{};
    for (std::uint32_t i = 0; i < HH_OFF_BINS; ++i) {
        bins[i] = std::uint32_t(now[HH_WORD_OFF_BIN0 + i] - before[HH_WORD_OFF_BIN0 + i]);
        s.pixels += bins[i];
    }
    if (s.pixels != 0) {
        s.mean = double(std::uint32_t(now[HH_WORD_OFF_SUM] - before[HH_WORD_OFF_SUM])) / 16.0 /
                 double(s.pixels);
        std::uint64_t seen = 0;
        for (std::uint32_t i = 0; i < HH_OFF_BINS; ++i) {
            seen += bins[i];
            if (seen * 100 >= s.pixels * 95) {
                s.p95_below = Edge[i];
                break;
            }
        }
    }
    s.largest = double(now[HH_WORD_OFF_MAX]) / 16.0;
    return s;
}

/// What the counts say about a column that the CPU drew and the picture may not show.
/// "Unusable" depth: no view z in front of the camera, or a view z under half the flame's, for 90%
/// or more of the tested pixels (the columns stand above a flame, where the scene is seldom that
/// much nearer the camera than the flame). "Covered": the depth tests drop 90% or more of them, or
/// would where they are counted only (BB_HEAT_HAZE_DEPTH=0, BB_HEAT_HAZE_SHOW=2).
inline const char* Verdict(const PixelCounts& c) {
    const std::uint64_t tested = c.Tested();
    if (c.rect == 0) {
        return "no pixel of a column reached the haze pass since the last line";
    }
    if (tested == 0) {
        return "every pixel fell outside the columns' shape: the column's numbers are at fault";
    }
    const bool unusable = (c.z_bad + c.z_close) * 10 >= tested * 9;
    if (c.written == 0) {
        return unusable ? "nothing written: the depth tests drop every pixel, and the depth read "
                          "here puts 90% or more of them under half the flame's view z or "
                          "nowhere: the depth image before the upscaler is not this view's depth"
                        : "nothing written: the depth tests drop every pixel; the depth puts "
                          "something nearer than the flame over the columns";
    }
    if (unusable) {
        return "pixels written (depth tests off or passed), but the depth read here puts 90% or "
               "more of them under half the flame's view z or nowhere: the depth image before "
               "the upscaler is not this view's depth";
    }
    if ((c.nearer + c.source) * 10 >= tested * 9) {
        return "pixels written, but the depth tests drop (or, counted only, would drop) 90% or "
               "more: the depth puts something nearer than the flame over the columns (compare "
               "the flame pixel's view z with its lamp's)";
    }
    return "pixels written: if the picture shows no column, the write is lost after this pass";
}

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
