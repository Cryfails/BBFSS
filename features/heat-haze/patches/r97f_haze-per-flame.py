# r97f_haze-per-flame: FEATURE (a fix inside the heat haze feature), on top of r97, r97b, r97c, r97d, r97e
# (apply AFTER them, revert BEFORE them). The haze itself stays off by default (the setting
# graphics_heat_haze_strength defaults to 0; BB_HEAT_HAZE wins when set); this patch only changes WHERE
# a column stands once the haze is on, and it has its own switch, BB_HEAT_HAZE_FLAMES.
#
# The owner's report (build 72): "There is only heat haze over one of the lamps on the post. Image 1 lamp
# right has haze and left doesn't" and "This lamps heat haze is in the middle of the post. image 2".
# Cause (by reading, the one thing the log and the pictures allow): the haze stands on the LIGHT RECORDS of
# the game's lamp pass (heat_haze.h Collector), and the game's artists put those where they liked: one
# light for the two lanterns of a post, between them (the haze in the middle of the post), or one on a
# single lantern (haze on one lantern, none on the other). The owner's log of that run (3 kept flames a
# frame, 2 columns drawn) agrees. No other data says where a flame is: the lamp records hold a place, a
# 1 / reach squared and a colour, nothing about the lantern.
#
# Fix: look for the flames themselves, in the picture. A new compute pass (heat_haze_find.comp) runs in
# the same place as the haze (right before the upscaler, on the scene colour), one workgroup for each of
# the 8 nearest lamps: it scans a 6 m square of the view plane around the lamp's light (32 x 32 cells, 4 x 4
# taps each, about 16000 reads a lamp), takes each cell's mean luma (blue-ish cells count 0), subtracts the
# mean of the 8 neighbouring cells (a small bright source stands out of a lit wall; a wall alone does not),
# and keeps up to 3 cells at least BB_HEAT_HAZE_FLAME_MIN (default 0.5 HDR luma) above their surround
# and a third of the strongest, each at its blob's centroid. The answer (metres in the view plane from the
# light, 16 words a lamp) goes to a 512 byte buffer that is copied to host memory like the pixel counters;
# the engine reads it a frame or two later (a block carries a fold of its words: a block the copy was still
# writing fails it and is skipped). A table (FlameTable, by the lamp's place in the WORLD, 0.4 m: the lamp
# records are in view space, which moves with the camera) keeps each lamp's flames as WORLD offsets from the
# lamp (new answers move kept flames within 0.3 m by 0.4, others replace; 8 answers with no flame in a row
# drop them), so a flame found once stays where it is as the camera moves and no frame lags the picture.
# The columns then stand on the found flames: one column a flame (up to 3 a lamp), each above its flame
# (the column's height and radius still follow the lamp's reach). Mode 2 (the default) keeps a lamp's own
# light as its column while the lamp has no answer yet or none found (so nothing is lost where the
# thresholds miss a flame); mode 1 draws no column then; mode 0 is r97e exactly.
#
# What the pass does NOT do (said honestly): it does not read depth, so a found flame is put on the plane
# of its lamp's light (a lantern half a metre nearer or farther than the light shifts on screen by the
# parallax of that half metre only); a warm bright lit pillar that is small against a dark wall can pass as a
# flame; a flame hidden behind something is not found (its kept anchors stay 8 answers, then go). Whether
# the picture's flames are bright enough over BB_HEAT_HAZE_FLAME_MIN is not known (unmeasured, the scene
# colour's exposure at that point is not logged): the log line "Heat haze (r97f)" prints the strongest blob
# and the brightest cell it saw so the number can be set from the log (the lead's job).
#
# Off: BB_HEAT_HAZE_FLAMES=0 makes no pipeline and no buffer (the constructor does not create them), and
# Apply passes the lamps to Choose as r97e did (find_made false: one bool test); with the haze's strength 0
# no HeatHaze exists or its Apply is never reached (r97e), so the whole patch costs nothing then.
# Cost on: 8 workgroups of 256 invocations a frame (about 16000 image reads and 4 passes over 1024 cells in
# shared memory each), one 512 byte device-to-host copy, 3 more barriers; estimated 0.03-0.1 ms at 1080p
# internal (not measured). Memory: 512 B device + 512 B host. CPU: one table scan of 32 entries per lamp.
#
# Files: new host_shaders/heat_haze_find_layout.h, host_shaders/heat_haze_find.comp,
# renderer_vulkan/heat_haze_flames.h (all the pure code); edited vk_heat_haze.h/.cpp (one include, members,
# 4 methods, 6 hook edits), engine/gpu/CMakeLists.txt (2 lines), tests/test_heat_haze.cpp (block n),
# tests/test_effect_pipelines.cpp (include and a row), README.md (2 rows).
# Unverified: the C++ compile (no compiler allowed): the designated vk::WriteDescriptorSet in the CTAD
# std::array, `std::span<const Lamp> = std::vector<Lamp>`, `{StorageImage, vk::DescriptorType::eStorageBuffer}`
# for EffectPass::Create's initializer_list, the test block (asserts under -Werror), the lambda captures of
# the crumb; the game; whether the finder's thresholds find the lanterns' flames.
#
# Use: python -I -X utf8 r97f_haze-per-flame.py check | apply | revert
# Root: R97F_ROOT, else <tree>. Line ends kept (new files are written CRLF). apply backs the originals
# up in r97f_backup next to this script; revert removes the new files.
import os, sys

ROOT = os.environ.get("R97F_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r97f_backup")
VC = "engine/gpu/shadps4/video_core/"
RV = VC + "renderer_vulkan/"
LAY = VC + "host_shaders/heat_haze_find_layout.h"
SH = VC + "host_shaders/heat_haze_find.comp"
FLH = RV + "heat_haze_flames.h"
VH = RV + "vk_heat_haze.h"
VCPP = RV + "vk_heat_haze.cpp"
CM = "engine/gpu/CMakeLists.txt"
UT = "engine/tests/test_heat_haze.cpp"
TEP = "engine/tests/test_effect_pipelines.cpp"
RM = "README.md"

NEW = {
LAY: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97f_haze-per-flame): what the heat haze's flame finder (heat_haze_find.comp) and the
// engine (renderer_vulkan/heat_haze_flames.h, which ties these to its constants with static_asserts)
// share. Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive
// and C++ includes it as it is, so one text holds every number both sides use.
#ifndef HEAT_HAZE_FIND_LAYOUT_H
#define HEAT_HAZE_FIND_LAYOUT_H

// One workgroup (16 x 16 invocations) scans one lamp's surroundings: HF_GRID x HF_GRID cells over a
// square of the view plane at the lamp's depth, 2 x the half side wide (the push constants give it).
#define HF_GRID 32u       // cells a side
#define HF_SUPPRESS 4     // a peak clears the cells within this many cells of it (chebyshev)
#define HF_PEAKS 3u       // flames found around one lamp, at most
#define HF_SLOTS 8u       // lamps scanned a frame, at most (one block each)
#define HF_BLOCK_WORDS 16u
// A block (one lamp, one frame), in words. Floats are given by their bits (floatBitsToUint).
#define HF_WORD_ID 0u     // the table entry's id the push constants gave (echoed)
#define HF_WORD_TAG 1u    // the frame's tag (echoed): a block is new when its tag is
#define HF_WORD_COUNT 2u  // flames found, 0 to HF_PEAKS
#define HF_WORD_BEST 3u   // float: the strongest blob (HDR luma above its surround), 0 when none
#define HF_WORD_PEAK0 4u  // peak k at HF_WORD_PEAK0 + k * HF_PEAK_WORDS: x, y (float, metres in the
#define HF_PEAK_WORDS 3u  // view plane from the lamp, +y up the view's own y) and its blob (float)
#define HF_WORD_BRIGHT 13u // float: the brightest cell's mean luma
#define HF_WORD_CELLS 14u  // cells inside the scene
#define HF_WORD_CHECK 15u  // a fold of words 0 to 14 (the engine reads these words while the GPU
                           // may still be copying them: a block that does not check is skipped)
#define HF_WORDS_TOTAL 128u // HF_SLOTS * HF_BLOCK_WORDS

#endif
''',
SH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97f_haze-per-flame): the heat haze's flame finder (BB_HEAT_HAZE_FLAMES; vk_heat_haze.cpp,
// the numbers in heat_haze_find_layout.h). The game's lamp lights sit where its artists put them (the
// middle of a post, one light for two lanterns), not on the flames, so the haze looks for the flames
// themselves in the scene colour: one workgroup a lamp scans a square of the view plane around the
// lamp's light (HF_GRID x HF_GRID cells, 4 x 4 taps each: a flame a few pixels wide is not missed between taps), takes each cell's mean luma (cells that
// are blue-ish count 0: a flame is not blue), subtracts the mean of the cell's 8 neighbours (a small
// bright source stands out of a lit wall), and keeps up to HF_PEAKS strongest cells at least `blob
// minimum` above their surround (and a third of the strongest), each at the blob's centroid. The
// answer, in metres of the view plane from the light, goes to a small buffer the engine reads a frame
// or two later. Reads the scene colour only; writes nothing else.
#version 450
#extension GL_GOOGLE_include_directive : require

#include "heat_haze_find_layout.h"

layout(local_size_x = 16, local_size_y = 16) in;

layout(binding = 0, rgba16f) uniform readonly image2D scene_img;
layout(std430, binding = 1) buffer Blocks {
    uint words[HF_WORDS_TOTAL];
};

// heat_haze_flames.h FindPush, field for field.
layout(push_constant) uniform Push {
    ivec4 info;   // slot, id (echoed), tag (echoed), 0
    vec4 centre;  // the light's pixel x, y; pixels a metre at its depth, x and y (signed, as the projection's)
    vec4 window;  // half side (m), blob minimum (HDR luma), the scene's width and height (px)
};

const uint CELLS = HF_GRID * HF_GRID;
shared float cell_luma[CELLS]; // -1: the cell is outside the scene
shared float cell_blob[CELLS];

const vec3 luma_weights = vec3(0.2126, 0.7152, 0.0722);

// The pixel of a point of the grid (in cells, 0 to HF_GRID a side) in the view plane around the light.
vec2 PixelOf(vec2 grid) {
    const vec2 metres = (grid / float(HF_GRID) * 2.0 - 1.0) * window.x;
    return centre.xy + metres * centre.zw;
}

float CellLuma(uint idx) {
    const vec2 cell = vec2(float(idx % HF_GRID), float(idx / HF_GRID));
    const ivec2 size = ivec2(window.zw);
    vec3 sum = vec3(0.0);
    float n = 0.0;
    for (int j = 0; j < 4; ++j) {
        for (int i = 0; i < 4; ++i) {
            const ivec2 p = ivec2(floor(PixelOf(cell + vec2(0.125 + 0.25 * float(i), 0.125 + 0.25 * float(j)))));
            if (all(greaterThanEqual(p, ivec2(0))) && all(lessThan(p, size))) {
                vec3 c = imageLoad(scene_img, p).rgb;
                c = (any(isnan(c)) || any(isinf(c))) ? vec3(0.0) : clamp(c, vec3(0.0), vec3(64.0));
                sum += c;
                n += 1.0;
            }
        }
    }
    if (n < 0.5) {
        return -1.0;
    }
    const vec3 mean = sum / n;
    return mean.b <= 1.05 * mean.r ? dot(mean, luma_weights) : 0.0;
}

void main() {
    const uint t = gl_LocalInvocationIndex;
    for (uint k = 0u; k < CELLS / 256u; ++k) {
        cell_luma[t + 256u * k] = CellLuma(t + 256u * k);
    }
    memoryBarrierShared();
    barrier();
    for (uint k = 0u; k < CELLS / 256u; ++k) {
        const uint idx = t + 256u * k;
        const float v = cell_luma[idx];
        float blob = 0.0;
        if (v > 0.0) {
            const int cx = int(idx % HF_GRID), cy = int(idx / HF_GRID);
            float sum = 0.0, n = 0.0;
            for (int dy = -1; dy <= 1; ++dy) {
                for (int dx = -1; dx <= 1; ++dx) {
                    const int nx = cx + dx, ny = cy + dy;
                    if ((dx != 0 || dy != 0) && nx >= 0 && ny >= 0 && nx < int(HF_GRID) && ny < int(HF_GRID)) {
                        sum += max(cell_luma[uint(ny) * HF_GRID + uint(nx)], 0.0);
                        n += 1.0;
                    }
                }
            }
            blob = v - sum / max(n, 1.0);
        }
        cell_blob[idx] = max(blob, 0.0);
    }
    memoryBarrierShared();
    barrier();
    if (t != 0u) {
        return;
    }
    // One invocation picks the peaks (1024 cells, up to 3 passes: a few microseconds a lamp).
    const uint base = uint(info.x) * HF_BLOCK_WORDS;
    float bright = 0.0;
    uint inside = 0u;
    for (uint i = 0u; i < CELLS; ++i) {
        const float v = cell_luma[i];
        bright = max(bright, v);
        inside += v >= 0.0 ? 1u : 0u;
    }
    uint found = 0u;
    float first = 0.0;
    for (uint k = 0u; k < HF_PEAKS; ++k) {
        float best = 0.0;
        uint at = CELLS;
        for (uint i = 0u; i < CELLS; ++i) {
            if (cell_blob[i] > best) {
                best = cell_blob[i];
                at = i;
            }
        }
        if (at == CELLS || best < window.y || (k > 0u && best < 0.35 * first)) {
            break;
        }
        if (k == 0u) {
            first = best;
        }
        const int cx = int(at % HF_GRID), cy = int(at / HF_GRID);
        float wsum = 0.0;
        vec2 pos = vec2(0.0);
        for (int dy = -1; dy <= 1; ++dy) {
            for (int dx = -1; dx <= 1; ++dx) {
                const int nx = cx + dx, ny = cy + dy;
                if (nx >= 0 && ny >= 0 && nx < int(HF_GRID) && ny < int(HF_GRID)) {
                    const float w = cell_blob[uint(ny) * HF_GRID + uint(nx)];
                    wsum += w;
                    pos += w * vec2(float(nx) + 0.5, float(ny) + 0.5);
                }
            }
        }
        pos /= max(wsum, 1e-6);
        const vec2 metres = (pos / float(HF_GRID) * 2.0 - 1.0) * window.x;
        const uint p0 = base + HF_WORD_PEAK0 + k * HF_PEAK_WORDS;
        words[p0] = floatBitsToUint(metres.x);
        words[p0 + 1u] = floatBitsToUint(metres.y);
        words[p0 + 2u] = floatBitsToUint(best);
        for (int dy = -HF_SUPPRESS; dy <= HF_SUPPRESS; ++dy) {
            for (int dx = -HF_SUPPRESS; dx <= HF_SUPPRESS; ++dx) {
                const int nx = cx + dx, ny = cy + dy;
                if (nx >= 0 && ny >= 0 && nx < int(HF_GRID) && ny < int(HF_GRID)) {
                    cell_blob[uint(ny) * HF_GRID + uint(nx)] = 0.0;
                }
            }
        }
        ++found;
    }
    for (uint k = found; k < HF_PEAKS; ++k) {
        const uint p0 = base + HF_WORD_PEAK0 + k * HF_PEAK_WORDS;
        words[p0] = 0u;
        words[p0 + 1u] = 0u;
        words[p0 + 2u] = 0u;
    }
    words[base + HF_WORD_ID] = uint(info.y);
    words[base + HF_WORD_TAG] = uint(info.z);
    words[base + HF_WORD_COUNT] = found;
    words[base + HF_WORD_BEST] = floatBitsToUint(first);
    words[base + HF_WORD_BRIGHT] = floatBitsToUint(bright);
    words[base + HF_WORD_CELLS] = inside;
    uint check = 2166136261u;
    for (uint k = 0u; k < HF_WORD_CHECK; ++k) {
        check = (check ^ words[base + k]) * 16777619u;
    }
    words[base + HF_WORD_CHECK] = check;
}
''',
FLH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97f_haze-per-flame): the pure parts of the haze's flame anchoring (vk_heat_haze.cpp,
// host_shaders/heat_haze_find.comp): the knobs, the scan of a lamp's surroundings and its answer, a
// table that remembers where each lamp's flames are, and the sources (the places the columns stand
// on) the table gives. No Vulkan, no settings; tested by tests/test_heat_haze.cpp.
//
// Why: the game's lamp lights (the records heat_haze.h reads) sit where its artists put them, not
// on the flames: one light for the two lanterns of a post stands between them (the haze came out
// in the middle of the post), and the lantern that has none got no haze. So each lamp's
// surroundings are scanned in the scene colour for small bright warm sources (the flames and the
// lit glass), and the columns stand on those; a lamp stays where it is for the table's sake (its
// place in the WORLD: the records are in view space, which moves with the camera).
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

#include "heat_haze.h"
#include "../host_shaders/heat_haze_find_layout.h"

namespace BbHeatHaze {

/// BB_HEAT_HAZE_FLAMES: 0 the haze stands on the lamps' lights (r97e), 1 on the flames found around
/// a lamp (none found, no column), 2 the same and a lamp with no answer, or none found, keeps its own.
enum class FlameMode : int { Off = 0, Anchors = 1, AnchorsOrLight = 2 };
inline constexpr FlameMode FlamesDefault = FlameMode::AnchorsOrLight;

/// Unset or empty: FlamesDefault; exactly "0", "1" or "2": that; any other text: off.
inline FlameMode ParseFlames(const char* text) {
    if (text == nullptr || text[0] == 0) {
        return FlamesDefault;
    }
    if (text[1] == 0 && text[0] >= '0' && text[0] <= '2') {
        return static_cast<FlameMode>(text[0] - '0');
    }
    return FlameMode::Off;
}

/// BB_HEAT_HAZE_FLAME_MIN: how far above its surround (HDR luma) a cell must stand to be a flame.
inline constexpr float BlobMinDefault = 0.5f, BlobMinLowest = 0.05f, BlobMinHighest = 100.0f;
inline float ParseBlobMin(const char* text) {
    if (text == nullptr || text[0] == 0) {
        return BlobMinDefault;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || *end != 0 || !std::isfinite(value)) {
        return BlobMinDefault;
    }
    return std::clamp(value, BlobMinLowest, BlobMinHighest);
}

inline constexpr std::uint32_t MaxScans = HF_SLOTS;     ///< lamps scanned a frame
inline constexpr std::uint32_t MaxAnchors = HF_PEAKS;   ///< flames kept for one lamp
inline constexpr std::uint32_t FindWords = HF_WORDS_TOTAL;
inline constexpr std::uint32_t FindBytes = HF_WORDS_TOTAL * 4u;
static_assert(HF_SLOTS * HF_BLOCK_WORDS == HF_WORDS_TOTAL && HF_WORD_CHECK + 1u == HF_BLOCK_WORDS &&
                  HF_WORD_PEAK0 + HF_PEAKS * HF_PEAK_WORDS <= HF_WORD_BRIGHT,
              "the block's words");
static_assert(HF_SLOTS == MaxColumns && MaxLamps <= 255u, "a table id keeps the index in 8 bits");
/// m: half the side of the square around a lamp that is scanned (a post's two lanterns are about
/// 2.5 m apart, a candle holder's candles a few decimetres).
inline constexpr float ScanHalfM = 3.0f;
inline constexpr float LampMatchM = 0.4f;   ///< m: a lamp seen again within this of where it was is the same
inline constexpr float AnchorMatchM = 0.3f; ///< m: a flame found again within this is the same
inline constexpr float AnchorBlend = 0.4f;  ///< the share a new answer moves a kept flame's place
inline constexpr std::uint32_t EmptyReadsToClear = 8; ///< answers with no flame before a lamp's are dropped

/// One scan's push constants (48 bytes; heat_haze_find.comp lists the same fields in the same order).
struct FindPush {
    std::array<std::int32_t, 4> info{};  ///< slot, id, tag, 0
    std::array<float, 4> centre{};       ///< the light's pixel x, y; pixels a metre at its depth, x, y (signed)
    std::array<float, 4> window{};       ///< half side (m), blob minimum, the scene's width, height
};
static_assert(sizeof(FindPush) == 48);

/// A block of the finder's buffer (one lamp, one frame).
struct Block {
    std::uint32_t id = 0, tag = 0, count = 0, cells = 0;
    std::array<float, HF_PEAKS> x{}, y{}, blob{};
    float best = 0.0f, bright = 0.0f;
};

/// The fold the shader puts in a block's last word (words 0 to 14).
inline std::uint32_t BlockCheck(const std::uint32_t* w) {
    std::uint32_t c = 2166136261u;
    for (std::uint32_t k = 0; k < HF_WORD_CHECK; ++k) {
        c = (c ^ w[k]) * 16777619u;
    }
    return c;
}

enum class ReadKind { Blank, Torn, Bad, Ok };
/// A block as the host copy holds it: Blank (never written), Torn (the copy was in flight: the check
/// fails), Bad (a number out of range) or Ok.
inline ReadKind ReadBlock(const std::uint32_t* w, Block& out) {
    if (w[HF_WORD_TAG] == 0 && w[HF_WORD_CHECK] == 0) {
        return ReadKind::Blank;
    }
    if (BlockCheck(w) != w[HF_WORD_CHECK]) {
        return ReadKind::Torn;
    }
    Block b;
    b.id = w[HF_WORD_ID];
    b.tag = w[HF_WORD_TAG];
    b.count = w[HF_WORD_COUNT];
    b.cells = w[HF_WORD_CELLS];
    b.best = Word(w, HF_WORD_BEST);
    b.bright = Word(w, HF_WORD_BRIGHT);
    if (b.count > HF_PEAKS || !std::isfinite(b.best) || !std::isfinite(b.bright)) {
        return ReadKind::Bad;
    }
    for (std::uint32_t k = 0; k < b.count; ++k) {
        b.x[k] = Word(w, HF_WORD_PEAK0 + k * HF_PEAK_WORDS);
        b.y[k] = Word(w, HF_WORD_PEAK0 + k * HF_PEAK_WORDS + 1);
        b.blob[k] = Word(w, HF_WORD_PEAK0 + k * HF_PEAK_WORDS + 2);
        const float limit = ScanHalfM * 1.01f;
        if (!(std::abs(b.x[k]) <= limit) || !(std::abs(b.y[k]) <= limit) || !(b.blob[k] > 0.0f) ||
            !std::isfinite(b.blob[k])) {
            return ReadKind::Bad;
        }
    }
    out = b;
    return ReadKind::Ok;
}

/// A direction through a 3x4 row matrix (the rotation part: no translation).
inline std::array<float, 3> Rotate(const std::array<float, 12>& m, const std::array<float, 3>& v) {
    return {m[0] * v[0] + m[1] * v[1] + m[2] * v[2], m[4] * v[0] + m[5] * v[1] + m[6] * v[2],
            m[8] * v[0] + m[9] * v[1] + m[10] * v[2]};
}

/// A point through a 3x4 row matrix.
inline std::array<float, 3> Transform(const std::array<float, 12>& m, const std::array<float, 3>& v) {
    const auto r = Rotate(m, v);
    return {r[0] + m[3], r[1] + m[7], r[2] + m[11]};
}

inline float DistanceSquared(const std::array<float, 3>& a, const std::array<float, 3>& b) {
    const float x = a[0] - b[0], y = a[1] - b[1], z = a[2] - b[2];
    return x * x + y * y + z * z;
}

/// A flame found near a lamp: where it stands, as a world offset from the lamp, and its blob.
struct Anchor {
    std::array<float, 3> offset{};
    float blob = 0.0f;
};

/// What the table keeps of one lamp.
struct Entry {
    bool used = false;
    bool answered = false;          ///< a scan of this lamp has been read
    std::uint32_t generation = 0;   ///< counts the entry's lives (an old answer for a dead life is dropped)
    std::uint32_t count = 0;        ///< flames kept (anchors[0..count))
    std::uint32_t empty_reads = 0;  ///< answers in a row that found none
    std::uint32_t last_tag = 0;     ///< the newest answer taken
    std::array<float, 3> world{};   ///< where the lamp was last seen, in the world
    std::uint64_t last_seen = 0;    ///< the frame it was last scanned or asked for
    std::array<Anchor, MaxAnchors> anchors{};
};

enum class ApplyResult { Unknown, Same, Empty, Anchors };

/// The lamps the haze has seen, by their place in the world (a lamp record's view space place moves
/// with the camera; a lamp is the same one when it is within LampMatchM of where it was).
class FlameTable {
public:
    static constexpr std::uint32_t Size = MaxLamps;

    /// The id of the lamp at `world` (index in the low 8 bits, the entry's life above): the entry
    /// within LampMatchM when there is one, else a new one (a free entry, or the one seen longest ago).
    std::uint32_t Touch(const std::array<float, 3>& world, std::uint64_t frame) {
        std::size_t found = Size;
        float best = LampMatchM * LampMatchM;
        for (std::size_t i = 0; i < Size; ++i) {
            if (entries[i].used) {
                const float d = DistanceSquared(entries[i].world, world);
                if (d <= best) {
                    best = d;
                    found = i;
                }
            }
        }
        if (found == Size) {
            std::size_t pick = 0;
            for (std::size_t i = 0; i < Size; ++i) {
                if (!entries[i].used) {
                    pick = i;
                    break;
                }
                if (entries[i].last_seen < entries[pick].last_seen) {
                    pick = i;
                }
            }
            const std::uint32_t life = entries[pick].generation + 1u;
            entries[pick] = Entry{};
            entries[pick].generation = life;
            entries[pick].used = true;
            found = pick;
        }
        entries[found].world = world;
        entries[found].last_seen = frame;
        return (entries[found].generation << 8) | std::uint32_t(found);
    }

    /// The entry of the lamp at `world` (the nearest within LampMatchM), or null.
    [[nodiscard]] const Entry* Match(const std::array<float, 3>& world) const {
        const Entry* found = nullptr;
        float best = LampMatchM * LampMatchM;
        for (const Entry& e : entries) {
            if (e.used) {
                const float d = DistanceSquared(e.world, world);
                if (d <= best) {
                    best = d;
                    found = &e;
                }
            }
        }
        return found;
    }

    [[nodiscard]] const Entry& At(std::size_t i) const { return entries[i]; }

    /// A block the finder wrote: Unknown when its id is of no live entry, Same when its tag was
    /// taken already, Empty when it found no flame, else Anchors (the flames' offsets, from the view
    /// plane to the world by `inv_view`, blended with the ones kept where they match).
    ApplyResult Apply(const Block& block, const std::array<float, 12>& inv_view) {
        const std::uint32_t index = block.id & 255u, life = block.id >> 8;
        if (index >= Size || !entries[index].used || entries[index].generation != life) {
            return ApplyResult::Unknown;
        }
        Entry& e = entries[index];
        // (review) A slot not rescanned this frame keeps an older block of this lamp in the host copy:
        // only a NEWER tag is taken (tags rise by one a frame), or old answers would be re-applied
        // every frame, alternating with the new ones.
        if (static_cast<std::int32_t>(block.tag - e.last_tag) <= 0) {
            return ApplyResult::Same;
        }
        e.last_tag = block.tag;
        e.answered = true;
        if (block.count == 0) {
            if (++e.empty_reads >= EmptyReadsToClear) {
                e.count = 0;
            }
            return ApplyResult::Empty;
        }
        e.empty_reads = 0;
        std::array<Anchor, MaxAnchors> next{};
        std::uint32_t n = 0;
        for (std::uint32_t k = 0; k < block.count && n < MaxAnchors; ++k) {
            Anchor a;
            a.offset = Rotate(inv_view, {block.x[k], block.y[k], 0.0f});
            a.blob = block.blob[k];
            std::size_t same = MaxAnchors;
            float best = AnchorMatchM * AnchorMatchM;
            for (std::uint32_t j = 0; j < e.count; ++j) {
                const float d = DistanceSquared(e.anchors[j].offset, a.offset);
                if (d <= best) {
                    best = d;
                    same = j;
                }
            }
            if (same != MaxAnchors) {
                for (std::size_t c = 0; c < 3; ++c) {
                    a.offset[c] = e.anchors[same].offset[c] + AnchorBlend * (a.offset[c] - e.anchors[same].offset[c]);
                }
            }
            next[n++] = a;
        }
        e.anchors = next;
        e.count = n;
        return ApplyResult::Anchors;
    }

private:
    std::array<Entry, Size> entries{};
};

/// One lamp's scan of a frame.
struct ScanJob {
    FindPush push;
    std::uint32_t id = 0;
    float distance = 0.0f; ///< m from the camera
};

/// The lamps to scan this frame: the MaxScans nearest whose light is within half a screen of the
/// screen's edge, each touched in the table (made when new), nearest first (slot 0).
inline std::vector<ScanJob> PlanScans(std::span<const Lamp> lamps, FlameTable& table,
                                      const Camera& camera, std::uint32_t tag, std::uint64_t frame,
                                      float blob_min) {
    struct Candidate {
        std::size_t index;
        float distance_squared;
    };
    std::vector<Candidate> candidates;
    const float w = float(camera.width), h = float(camera.height);
    for (std::size_t i = 0; i < lamps.size(); ++i) {
        const auto& v = lamps[i].view;
        if (!(v[2] >= NearZ) || camera.width == 0 || camera.height == 0) {
            continue;
        }
        const auto px = ToPixel(camera, v);
        if (!(px[0] > -0.5f * w && px[0] < 1.5f * w && px[1] > -0.5f * h && px[1] < 1.5f * h)) {
            continue;
        }
        candidates.push_back({i, v[0] * v[0] + v[1] * v[1] + v[2] * v[2]});
    }
    std::stable_sort(candidates.begin(), candidates.end(), [](const Candidate& a, const Candidate& b) {
        return a.distance_squared < b.distance_squared;
    });
    if (candidates.size() > MaxScans) {
        candidates.resize(MaxScans);
    }
    std::vector<ScanJob> jobs;
    jobs.reserve(candidates.size());
    for (std::size_t slot = 0; slot < candidates.size(); ++slot) {
        const Lamp& lamp = lamps[candidates[slot].index];
        const auto& v = lamp.view;
        ScanJob job;
        job.id = table.Touch(Transform(camera.inv_view, v), frame);
        const auto px = ToPixel(camera, v);
        job.push.info = {std::int32_t(slot), std::int32_t(job.id), std::int32_t(tag), 0};
        job.push.centre = {px[0], px[1], 0.5f * w * camera.proj[0] / v[2], 0.5f * h * camera.proj[1] / v[2]};
        job.push.window = {ScanHalfM, blob_min, w, h};
        job.distance = std::sqrt(candidates[slot].distance_squared);
        jobs.push_back(job);
    }
    return jobs;
}

/// What the sources of a frame were made of, per lamp.
struct FlameCounts {
    std::uint32_t anchored = 0;  ///< lamps whose flames were found (a source each)
    std::uint32_t empty = 0;     ///< lamps scanned, no flame found
    std::uint32_t unscanned = 0; ///< lamps with no answer yet
    std::uint32_t flames = 0;    ///< sources made of found flames
};

/// The places the columns stand on, one a source: each found flame of a lamp, at the lamp's place
/// plus the flame's offset (the view's rotation of the world offset); a lamp that has no answer or
/// none found keeps its own light with AnchorsOrLight, none with Anchors.
inline std::vector<Lamp> FlameSources(std::span<const Lamp> lamps, const FlameTable& table,
                                      const Camera& camera, FlameMode mode, FlameCounts& counts) {
    counts = {};
    std::vector<Lamp> out;
    out.reserve(lamps.size() * 2);
    std::vector<const Entry*> emitted; // (review) two lights within LampMatchM share an entry: its flames once
    for (const Lamp& lamp : lamps) {
        const Entry* entry = table.Match(Transform(camera.inv_view, lamp.view));
        if (entry != nullptr && entry->answered && entry->count > 0) {
            if (std::find(emitted.begin(), emitted.end(), entry) != emitted.end()) {
                continue;
            }
            emitted.push_back(entry);
            ++counts.anchored;
            for (std::uint32_t k = 0; k < entry->count; ++k) {
                Lamp source = lamp;
                const auto d = Rotate(camera.view, entry->anchors[k].offset);
                source.view = {lamp.view[0] + d[0], lamp.view[1] + d[1], lamp.view[2] + d[2]};
                out.push_back(source);
                ++counts.flames;
            }
            continue;
        }
        if (entry != nullptr && entry->answered) {
            ++counts.empty;
        } else {
            ++counts.unscanned;
        }
        if (mode == FlameMode::AnchorsOrLight) {
            out.push_back(lamp);
        }
    }
    return out;
}

} // namespace BbHeatHaze
''',
}

EDITS = {
VH: [
("insert", '#include "video_core/renderer_vulkan/heat_haze.h"\n', "",
 '#include "video_core/renderer_vulkan/heat_haze_flames.h" // bbport (r97f_haze-per-flame)\n'),
("insert", "    bool told_image = false;   ///< the line about the image the pass writes went out\n", "",
 r'''    // bbport (r97f_haze-per-flame): the flame finder (host_shaders/heat_haze_find.comp, heat_haze_flames.h):
    // each frame a scan of the 8 nearest lamps' surroundings in the scene colour, read back a frame or two
    // later into the table, which keeps where each lamp's flames are; the columns stand on those
    // (BB_HEAT_HAZE_FLAMES; 0: none of this is made).
    BbHeatHaze::FlameMode flames = BbHeatHaze::FlameMode::Off;
    float blob_min = BbHeatHaze::BlobMinDefault;
    bool find_made = false;
    bool find_zeroed = false; ///< the first scan's frame filled the device buffer with zeros
    vk::UniqueDescriptorSetLayout find_set_layout;
    vk::UniquePipelineLayout find_layout;
    vk::UniquePipeline find_pipeline;
    Buffer find_buffer, find_host;
    BbHeatHaze::FlameTable flame_table;
    u64 find_frame = 0;
    void PrepareFlames(const BbHeatHaze::Camera& view, std::span<const BbHeatHaze::Lamp> lamps,
                       std::vector<BbHeatHaze::ScanJob>& scans, std::vector<BbHeatHaze::Lamp>& sources);
    void ReadFinds(const BbHeatHaze::Camera& view);
    void RecordFind(const std::vector<BbHeatHaze::ScanJob>& scans, vk::ImageView color_view);
    void ReportFlames();
    struct FlameStats {
        u64 scans = 0;       ///< lamps scanned
        u64 answers = 0;     ///< new blocks read
        u64 with_flames = 0; ///< of them with at least one flame found
        u64 none = 0;        ///< of them with none
        u64 torn = 0;        ///< blocks whose check failed (the copy was in flight)
        u64 bad = 0;         ///< blocks with a number out of range
        u64 unknown = 0;     ///< blocks of a lamp the table no longer holds
        u64 anchored = 0;    ///< lamp frames whose columns stand on found flames
        u64 empty = 0;       ///< lamp frames scanned with no flame found
        u64 unscanned = 0;   ///< lamp frames with no answer yet
        u64 flames = 0;      ///< sources made of found flames
        float blob_max = 0.0f, bright_max = 0.0f;
    } flame_stats;
'''),
],
VCPP: [
("insert", '#include "video_core/host_shaders/heat_haze_comp.h"\n', "",
 '#include "video_core/host_shaders/heat_haze_find_comp.h" // bbport (r97f_haze-per-flame)\n'),
("insert", '                knobs.proof ? "on" : "off");\n', "",
 r'''    // bbport (r97f_haze-per-flame): the flame finder, unless BB_HEAT_HAZE_FLAMES=0
    flames = BbHeatHaze::ParseFlames(std::getenv("BB_HEAT_HAZE_FLAMES"));
    blob_min = BbHeatHaze::ParseBlobMin(std::getenv("BB_HEAT_HAZE_FLAME_MIN"));
    if (made && flames != BbHeatHaze::FlameMode::Off) {
        find_made = EffectPass::Create(instance, find_set_layout, find_layout, find_pipeline,
                                       {StorageImage, vk::DescriptorType::eStorageBuffer},
                                       sizeof(BbHeatHaze::FindPush), HEAT_HAZE_FIND_COMP,
                                       "Heat haze flames") &&
                    MakeBuffer(find_buffer, BbHeatHaze::FindBytes, false,
                               vk::BufferUsageFlagBits::eStorageBuffer |
                                   vk::BufferUsageFlagBits::eTransferSrc |
                                   vk::BufferUsageFlagBits::eTransferDst) &&
                    MakeBuffer(find_host, BbHeatHaze::FindBytes, true,
                               vk::BufferUsageFlagBits::eTransferDst);
        if (find_made) {
            std::memset(find_host.mapped, 0, BbHeatHaze::FindBytes);
        }
    }
    if (flames != BbHeatHaze::FlameMode::Off) {
        std::printf("Heat haze (r97f): flames %d (BB_HEAT_HAZE_FLAMES; 0 the columns stand on the lamps' "
                    "lights, 1 on the flames found around each lamp, 2 also on the light of a lamp with "
                    "none found yet): %s; each frame a scan of the %u nearest lamps' surroundings (a "
                    "%.0f m square of the view plane, %ux%u cells) in the scene colour, a flame is a "
                    "cell at least %.2f HDR luma above its surround (BB_HEAT_HAZE_FLAME_MIN), up to %u "
                    "a lamp\n",
                    int(flames), find_made ? "on" : "off - the pass could not be made",
                    BbHeatHaze::MaxScans, double(2.0f * BbHeatHaze::ScanHalfM), HF_GRID, HF_GRID,
                    double(blob_min), BbHeatHaze::MaxAnchors);
    }
'''),
("insert", "    FreeBuffer(counter_host);\n", "",
 "    FreeBuffer(find_buffer); // bbport (r97f_haze-per-flame)\n    FreeBuffer(find_host);\n"),
("insert", "    const auto columns =\n", r'''    // bbport (r97f_haze-per-flame): with the flame finder, the columns stand on the flames found around
    // each lamp (the table's), this frame's scans are planned, and the answers of earlier ones read
    std::vector<BbHeatHaze::ScanJob> scans;
    std::vector<BbHeatHaze::Lamp> flame_sources;
    std::span<const BbHeatHaze::Lamp> sources = lamps;
    if (find_made) {
        PrepareFlames(view, lamps, scans, flame_sources);
        sources = flame_sources;
    }
''', ""),
("replace",
 "        BbHeatHaze::Choose(lamps, view, Strength().value, knobs.show, wind, atlas, counts); // r97e\n",
 "        BbHeatHaze::Choose(sources, view, Strength().value, knobs.show, wind, atlas, counts); // r97e, r97f\n"),
("replace",
 "    if (columns.empty()) {\n        done();\n        return;\n    }\n    if (!EnsureAtlas(atlas.width, atlas.height)) {\n",
 "    const bool want_scan = find_made && !scans.empty(); // bbport (r97f_haze-per-flame)\n"
 "    if (columns.empty() && !want_scan) {\n        done();\n        return;\n    }\n"
 "    if (!columns.empty() && !EnsureAtlas(atlas.width, atlas.height)) {\n"),
("insert", "    // Real time (wrapped, for the floats), so the shimmer rises at its speed at any frame rate.\n",
 r'''    if (want_scan) { // bbport (r97f_haze-per-flame): the scan, before the haze changes the colour it reads
        RecordFind(scans, color_view);
    }
    if (columns.empty()) {
        done();
        return;
    }
''', ""),
("insert", "void HeatHaze::Report() {\n",
 r'''// bbport (r97f_haze-per-flame): the answers of the scans a frame or two back into the table, this frame's
// scans, and the places the columns stand on (a found flame each).
void HeatHaze::PrepareFlames(const BbHeatHaze::Camera& view, std::span<const BbHeatHaze::Lamp> lamps,
                             std::vector<BbHeatHaze::ScanJob>& scans,
                             std::vector<BbHeatHaze::Lamp>& sources) {
    ReadFinds(view);
    ++find_frame;
    scans = BbHeatHaze::PlanScans(lamps, flame_table, view, u32(find_frame), find_frame, blob_min);
    BbHeatHaze::FlameCounts counted;
    sources = BbHeatHaze::FlameSources(lamps, flame_table, view, flames, counted);
    flame_stats.scans += scans.size();
    flame_stats.anchored += counted.anchored;
    flame_stats.empty += counted.empty;
    flame_stats.unscanned += counted.unscanned;
    flame_stats.flames += counted.flames;
}

// The finder's host copy (a frame or two old, as the GPU left it): every block with a new tag goes to the
// table. A block the copy was still writing fails its check and is skipped (it is rewritten next frame).
void HeatHaze::ReadFinds(const BbHeatHaze::Camera& view) {
    if (!find_host.mapped) {
        return;
    }
    std::array<u32, BbHeatHaze::FindWords> now{};
    std::memcpy(now.data(), find_host.mapped, sizeof(now));
    for (u32 slot = 0; slot < BbHeatHaze::MaxScans; ++slot) {
        BbHeatHaze::Block block;
        const auto kind = BbHeatHaze::ReadBlock(now.data() + slot * HF_BLOCK_WORDS, block);
        if (kind == BbHeatHaze::ReadKind::Torn) {
            ++flame_stats.torn;
            continue;
        }
        if (kind == BbHeatHaze::ReadKind::Bad) {
            ++flame_stats.bad;
            continue;
        }
        if (kind != BbHeatHaze::ReadKind::Ok) {
            continue;
        }
        const auto result = flame_table.Apply(block, view.inv_view);
        if (result == BbHeatHaze::ApplyResult::Unknown) {
            ++flame_stats.unknown;
            continue;
        }
        if (result == BbHeatHaze::ApplyResult::Same) {
            continue;
        }
        ++flame_stats.answers;
        flame_stats.blob_max = std::max(flame_stats.blob_max, block.best);
        flame_stats.bright_max = std::max(flame_stats.bright_max, block.bright);
        if (result == BbHeatHaze::ApplyResult::Anchors) {
            ++flame_stats.with_flames;
        } else {
            ++flame_stats.none;
        }
    }
}

// The scans of one frame: a workgroup each, reading the scene colour, into the finder's buffer, copied to
// the host copy. Recorded before the haze (it reads the colour the haze is about to change).
void HeatHaze::RecordFind(const std::vector<BbHeatHaze::ScanJob>& scans, vk::ImageView color_view) {
    std::array<BbHeatHaze::FindPush, BbHeatHaze::MaxScans> pushes{};
    const u32 count = u32(std::min<std::size_t>(scans.size(), BbHeatHaze::MaxScans));
    for (u32 i = 0; i < count; ++i) {
        pushes[i] = scans[i].push;
    }
    const bool zero = !std::exchange(find_zeroed, true);
    EffectPass::Mark(ProfileRow, "heat haze");
    scheduler.RecordCrumb(
        {.name = "heat haze flames"},
        [pushes, count, color_view, pass_pipeline = *find_pipeline, pass_layout = *find_layout,
         blocks = find_buffer.buffer, host = find_host.buffer, zero](vk::CommandBuffer cmdbuf) {
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute, ReadWrite);
            if (zero) {
                cmdbuf.fillBuffer(blocks, 0, VK_WHOLE_SIZE, 0);
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                          vk::AccessFlagBits2::eTransferWrite, Compute, ReadWrite);
            }
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            const vk::DescriptorImageInfo image_info = Info(color_view);
            const vk::DescriptorBufferInfo buffer_info{blocks, 0, VK_WHOLE_SIZE};
            const std::array writes{Write(0, StorageImage, &image_info),
                                    vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,
                                                           .descriptorType =
                                                               vk::DescriptorType::eStorageBuffer,
                                                           .pBufferInfo = &buffer_info}};
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            for (u32 i = 0; i < count; ++i) {
                cmdbuf.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(BbHeatHaze::FindPush), &pushes[i]);
                cmdbuf.dispatch(1, 1, 1);
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands, MemoryAll);
            cmdbuf.copyBuffer(blocks, host, vk::BufferCopy{0, 0, BbHeatHaze::FindBytes});
            EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                      vk::AccessFlagBits2::eTransferWrite,
                                      vk::PipelineStageFlagBits2::eHost,
                                      vk::AccessFlagBits2::eHostRead);
        });
}

void HeatHaze::ReportFlames() {
    if (!find_made) {
        return;
    }
    const auto ull = [](u64 v) { return static_cast<unsigned long long>(v); };
    const double f = std::max(1.0, double(stats.frames));
    BbReport::Printf("Heat haze (r97f): flames %d: %llu lamps scanned (%.1f a frame), %llu answers read "
                     "(%llu found flames, %llu none), %llu torn, %llu unusable, %llu of a lamp no longer "
                     "kept; lamp frames: %llu on found flames (%llu flames), %llu none found, %llu not "
                     "answered yet\n",
                     int(flames), ull(flame_stats.scans), double(flame_stats.scans) / f,
                     ull(flame_stats.answers), ull(flame_stats.with_flames), ull(flame_stats.none),
                     ull(flame_stats.torn), ull(flame_stats.bad), ull(flame_stats.unknown),
                     ull(flame_stats.anchored), ull(flame_stats.flames), ull(flame_stats.empty),
                     ull(flame_stats.unscanned));
    BbReport::Printf("Heat haze (r97f): strongest blob %.2f and brightest cell %.2f (HDR luma) since the "
                     "last line; a flame needs a blob of %.2f (BB_HEAT_HAZE_FLAME_MIN)\n",
                     double(flame_stats.blob_max), double(flame_stats.bright_max), double(blob_min));
    flame_stats = {};
}

''', ""),
("insert", "    ReportPixels(); // bbport (r97b_heat-haze-paths)\n", "",
 "    ReportFlames(); // bbport (r97f_haze-per-flame)\n"),
],
CM: [
("insert",
 "add_custom_command(OUTPUT ${SHADER_DIR}/heat_haze_comp.h APPEND DEPENDS ${SHADER_SRC}/heat_haze_layout.h) # bbport (r97b_heat-haze-paths): the shader's include\n",
 "",
 "# bbport (r97f_haze-per-flame): the heat haze's flame finder (renderer_vulkan/vk_heat_haze.cpp)\n"
 "add_host_shader(heat_haze_find.comp heat_haze_find_comp)\n"
 "add_custom_command(OUTPUT ${SHADER_DIR}/heat_haze_find_comp.h APPEND DEPENDS ${SHADER_SRC}/heat_haze_find_layout.h)\n"),
],
TEP: [
("insert", '#include "video_core/host_shaders/heat_haze_comp.h" // bbport (r97_heat-haze)\n', "",
 '#include "video_core/host_shaders/heat_haze_find_comp.h" // bbport (r97f_haze-per-flame)\n'),
("insert",
 "         {eStorageImage, eStorageImage, eSampledImage, eStorageBuffer}, // r97b: the counters\n         96},\n",
 "",
 "        // bbport (r97f_haze-per-flame): the flame finder, as vk_heat_haze.cpp makes it (BbHeatHaze::FindPush, 48 bytes)\n"
 '        {"heat haze flames", HEAT_HAZE_FIND_COMP, {eStorageImage, eStorageBuffer}, 48},\n'),
],
UT: [
("insert", '#include "gpu/shadps4/video_core/renderer_vulkan/heat_haze.h"\n', "",
 '#include "gpu/shadps4/video_core/renderer_vulkan/heat_haze_flames.h" // bbport (r97f_haze-per-flame)\n'),
("insert", '    std::printf("heat-haze-test: all checks passed\\n");\n',
 r'''    // n. bbport (r97f_haze-per-flame): the flames found around a lamp, the table and the sources.
    {
        assert(ParseFlames(nullptr) == FlamesDefault && ParseFlames("") == FlamesDefault);
        assert(ParseFlames("0") == FlameMode::Off && ParseFlames("1") == FlameMode::Anchors &&
               ParseFlames("2") == FlameMode::AnchorsOrLight);
        assert(ParseFlames("3") == FlameMode::Off && ParseFlames("x") == FlameMode::Off &&
               ParseFlames("01") == FlameMode::Off);
        assert(ParseBlobMin(nullptr) == BlobMinDefault && ParseBlobMin("2") == 2.0f &&
               ParseBlobMin("0.001") == BlobMinLowest && ParseBlobMin("500") == BlobMinHighest &&
               ParseBlobMin("abc") == BlobMinDefault);
        // A block as the shader writes it, and what a torn, a blank and a wild one read as.
        std::array<std::uint32_t, HF_BLOCK_WORDS> w{};
        const auto put = [&w](std::uint32_t word, float value) {
            w[word] = std::bit_cast<std::uint32_t>(value);
        };
        w[HF_WORD_ID] = 256;
        w[HF_WORD_TAG] = 9;
        w[HF_WORD_COUNT] = 1;
        put(HF_WORD_BEST, 2.0f);
        put(HF_WORD_PEAK0, 0.5f);
        put(HF_WORD_PEAK0 + 1, -0.25f);
        put(HF_WORD_PEAK0 + 2, 2.0f);
        put(HF_WORD_BRIGHT, 7.0f);
        w[HF_WORD_CELLS] = 900;
        w[HF_WORD_CHECK] = BlockCheck(w.data());
        Block got;
        assert(ReadBlock(w.data(), got) == ReadKind::Ok && got.id == 256 && got.tag == 9 &&
               got.count == 1 && got.cells == 900 && Near(got.x[0], 0.5f, 1e-6f) &&
               Near(got.y[0], -0.25f, 1e-6f) && Near(got.blob[0], 2.0f, 1e-6f) &&
               Near(got.bright, 7.0f, 1e-6f));
        auto torn = w;
        torn[HF_WORD_PEAK0] ^= 0x1000u;
        assert(ReadBlock(torn.data(), got) == ReadKind::Torn);
        const std::array<std::uint32_t, HF_BLOCK_WORDS> blank{};
        assert(ReadBlock(blank.data(), got) == ReadKind::Blank);
        auto many = w;
        many[HF_WORD_COUNT] = 4;
        many[HF_WORD_CHECK] = BlockCheck(many.data());
        assert(ReadBlock(many.data(), got) == ReadKind::Bad);
        auto wild = w;
        wild[HF_WORD_PEAK0] = std::bit_cast<std::uint32_t>(10.0f); // outside the scanned square
        wild[HF_WORD_CHECK] = BlockCheck(wild.data());
        assert(ReadBlock(wild.data(), got) == ReadKind::Bad);
        // The table: a lamp is the same one within 0.4 m of where it was seen (in the world).
        const std::array<float, 12> identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        FlameTable table;
        const std::array<float, 3> at{0.0f, 0.0f, 5.0f};
        const std::uint32_t id = table.Touch(at, 1);
        assert(id == ((1u << 8) | 0u));
        assert(table.Touch({0.1f, 0.0f, 5.0f}, 2) == id);
        assert(table.Touch({3.0f, 0.0f, 5.0f}, 3) == ((1u << 8) | 1u));
        assert(table.Match(at) != nullptr && !table.Match(at)->answered);
        assert(table.Match({50.0f, 0.0f, 5.0f}) == nullptr);
        Block first;
        first.id = id;
        first.tag = 3;
        first.count = 2;
        first.x = {0.5f, -1.0f, 0.0f};
        first.y = {0.2f, 0.1f, 0.0f};
        first.blob = {2.0f, 1.0f, 0.0f};
        assert(table.Apply(first, identity) == ApplyResult::Anchors);
        const Entry& entry = table.At(0);
        assert(entry.answered && entry.count == 2 && Near(entry.anchors[0].offset[0], 0.5f, 1e-5f) &&
               Near(entry.anchors[1].offset[0], -1.0f, 1e-5f) &&
               Near(entry.anchors[1].offset[1], 0.1f, 1e-5f));
        assert(table.Apply(first, identity) == ApplyResult::Same); // the same tag again
        Block dead = first; // an answer for another life of the entry
        dead.id = (2u << 8) | 0u;
        dead.tag = 4;
        assert(table.Apply(dead, identity) == ApplyResult::Unknown);
        Block second = first; // one flame again near the first: the kept one moves 0.4 of the way
        second.tag = 4;
        second.count = 1;
        second.x = {0.6f, 0.0f, 0.0f};
        second.y = {0.2f, 0.0f, 0.0f};
        assert(table.Apply(second, identity) == ApplyResult::Anchors);
        assert(entry.count == 1 && Near(entry.anchors[0].offset[0], 0.54f, 1e-5f));
        assert(table.Apply(first, identity) == ApplyResult::Same); // (review) an older tag: not taken again
        Block nothing;
        nothing.id = id;
        nothing.count = 0;
        for (std::uint32_t tag = 5; tag < 12; ++tag) { // 7 answers with no flame: the flame stays
            nothing.tag = tag;
            const ApplyResult r = table.Apply(nothing, identity);
            assert(r == ApplyResult::Empty);
        }
        assert(entry.count == 1);
        nothing.tag = 12; // the 8th: it goes
        assert(table.Apply(nothing, identity) == ApplyResult::Empty);
        assert(entry.count == 0 && entry.answered);
        // The sources: a lamp's found flames, at the lamp's place plus the flame's offset.
        const Camera camera = Straight();
        const Lamp lamp = Torch(0.0f, 0.0f, 5.0f);
        const std::array<Lamp, 1> lamps{lamp};
        FlameTable t2;
        const std::uint32_t lid = t2.Touch(Transform(camera.inv_view, lamp.view), 1);
        FlameCounts counts;
        assert(FlameSources(lamps, t2, camera, FlameMode::Anchors, counts).empty() &&
               counts.unscanned == 1);
        assert(FlameSources(lamps, t2, camera, FlameMode::AnchorsOrLight, counts).size() == 1 &&
               counts.unscanned == 1);
        Block found = first;
        found.id = lid;
        found.tag = 1;
        assert(t2.Apply(found, camera.inv_view) == ApplyResult::Anchors);
        const auto sources = FlameSources(lamps, t2, camera, FlameMode::Anchors, counts);
        assert(sources.size() == 2 && counts.anchored == 1 && counts.flames == 2 &&
               Near(sources[0].view[0], 0.5f, 1e-5f) && Near(sources[0].view[1], 0.2f, 1e-5f) &&
               Near(sources[0].view[2], 5.0f, 1e-5f) && Near(sources[0].reach, lamp.reach, 1e-6f));
        // The camera moved 1 m to the right: the lamp's record is 1 m to the left in the view, the
        // table still knows it by its place in the world, and the flames follow it.
        Camera moved = Straight();
        moved.view[3] = -1.0f;
        moved.inv_view[3] = 1.0f;
        const std::array<Lamp, 1> shifted{Torch(-1.0f, 0.0f, 5.0f)};
        const auto after = FlameSources(shifted, t2, moved, FlameMode::Anchors, counts);
        assert(after.size() == 2 && Near(after[0].view[0], -0.5f, 1e-5f) &&
               Near(after[1].view[0], -2.0f, 1e-5f));
        Block none_found = found; // answered, none found (8 answers drop the flames)
        for (std::uint32_t tag = 2; tag < 10; ++tag) {
            none_found.tag = tag;
            none_found.count = 0;
            (void)t2.Apply(none_found, camera.inv_view);
        }
        assert(FlameSources(lamps, t2, camera, FlameMode::Anchors, counts).empty() && counts.empty == 1);
        assert(FlameSources(lamps, t2, camera, FlameMode::AnchorsOrLight, counts).size() == 1);
        // The scans: the 8 nearest lamps, nearest first, the light's pixel and pixels a metre, off-screen ones skipped.
        FlameTable t3;
        std::vector<Lamp> row;
        for (int i = 0; i < 10; ++i) {
            row.push_back(Torch(0.0f, 0.0f, 3.0f + float(i)));
        }
        const auto jobs = PlanScans(row, t3, camera, 7, 1, 0.5f);
        assert(jobs.size() == MaxScans && jobs[0].id != jobs[1].id);
        assert(Near(jobs[0].distance, 3.0f, 1e-4f) && jobs[0].distance < jobs[1].distance);
        assert(jobs[0].push.info[0] == 0 && jobs[1].push.info[0] == 1 && jobs[0].push.info[2] == 7);
        assert(Near(jobs[0].push.centre[0], 960.0f, 0.01f) && Near(jobs[0].push.centre[1], 540.0f, 0.01f));
        assert(Near(jobs[0].push.centre[2], 0.5f * 1920.0f * camera.proj[0] / 3.0f, 0.01f) &&
               jobs[0].push.centre[3] < 0.0f);
        assert(jobs[0].push.window[0] == ScanHalfM && jobs[0].push.window[1] == 0.5f &&
               jobs[0].push.window[2] == 1920.0f && jobs[0].push.window[3] == 1080.0f);
        const std::array<Lamp, 1> aside{Torch(100.0f, 0.0f, 5.0f)};
        assert(PlanScans(aside, t3, camera, 8, 2, 0.5f).empty());
        // (review) two lights 0.2 m apart match one entry: its flames are given once
        const std::array<Lamp, 2> pair{lamp, Torch(0.2f, 0.0f, 5.0f)};
        Block again = found;
        again.tag = 20;
        assert(t2.Apply(again, camera.inv_view) == ApplyResult::Anchors);
        assert(FlameSources(pair, t2, camera, FlameMode::Anchors, counts).size() == 2 && counts.anchored == 1);
    }
''', ""),
],
RM: [
("insert", "| `BB_HEAT_HAZE_PROOF` | Test view (r97d)",
 "| `BB_HEAT_HAZE_FLAMES` | (r97f) Where a column stands, with `BB_HEAT_HAZE` above 0: the game's lamp lights sit where its artists put them (the middle of a post that has two lanterns, one lantern of the two), so the haze came out in the middle of the post, or over one lantern only. `1`: each of the 8 nearest lamps' surroundings (a 6 m square of the view plane, 32x32 cells) is scanned in the scene colour right before the upscaler for small bright warm sources (a cell at least `BB_HEAT_HAZE_FLAME_MIN` above the mean of its 8 neighbours, up to 3 a lamp), the answer is read a frame or two later, and one column stands above each flame found (kept where it is in the world, so it stays put as the camera moves); a lamp with no flame found gets none. `2` (the default): the same, and a lamp with no answer yet or none found keeps its own light's column. `0` (or text that is not 0, 1 or 2): the columns stand on the lights, as before. The log's `Heat haze (r97f)` lines count the scans, the answers, the flames found and the strongest blob and brightest cell seen, so the minimum can be set. Cost with the haze on: 8 workgroups a frame (about 16000 image reads and a few passes over 1024 cells each), a 512 byte copy; the haze off (strength 0): nothing | `2` |\n"
 "| `BB_HEAT_HAZE_FLAME_MIN` | (r97f) How far above the mean of its 8 neighbouring cells (HDR luma of the scene colour right before the upscaler) a cell of the scan must stand to count as a flame, 0.05 to 100 (text that is not a number: the default). Raise it if lit stone is taken for a flame, lower it if the log's strongest blob is under it where a flame burns | `0.5` |\n",
 ""),
],
}
PATHS = (VH, VCPP, CM, TEP, UT, RM)


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        raise SystemExit("%s is missing (are r97 to r97e applied?)" % path)
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    done = todo = 0
    for ed in eds:
        if ed[0] == "insert":
            _, anchor, before, after = ed
            parts = [t for t in (before, after) if t]
            na, counts = cur.count(anchor), [cur.count(t) for t in parts]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                                 % (path, na, counts, anchor[:70]))
        else:
            _, old, new = ed
            no, nn = cur.count(old), cur.count(new)
            if no == 0 and nn == 1:
                done += 1
            elif no == 1 and nn == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times, its new text %d times: %r"
                                 % (path, no, nn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_edits(cur, eds):
    for ed in eds:
        if ed[0] == "insert":
            _, anchor, before, after = ed
            cur = cur.replace(anchor, before + anchor + after, 1)
        else:
            cur = cur.replace(ed[1], ed[2], 1)
    return cur


def revert_edits(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "insert":
            _, anchor, before, after = ed
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        else:
            cur = cur.replace(ed[2], ed[1], 1)
    return cur


def new_state(path):
    full = os.path.join(ROOT, path)
    want = NEW[path].replace("\n", "\r\n").encode("utf-8")
    if not os.path.exists(full):
        return "clean"
    if open(full, "rb").read() == want:
        return "applied"
    raise SystemExit("REFUSED %s: the file exists and is not this patch's" % path)


def text_checks(t):
    c = t[VCPP]
    if c.find("Heat haze (r97d): the log also counts") > c.find("Heat haze (r97f): flames"):
        raise SystemExit("text check: the r97f once-line is not after r97d's")
    if c.count("find_made") < 6 or c.count("HeatHaze::PrepareFlames") != 1 or c.count("ReportFlames") != 2:
        raise SystemExit("text check: vk_heat_haze.cpp")
    if "BbHeatHaze::Choose(sources," not in c or "BbHeatHaze::Choose(lamps," in c:
        raise SystemExit("text check: Choose is not given the sources")
    if t[VH].count("FlameTable flame_table;") != 1 or t[VH].count("#include \"video_core/renderer_vulkan/heat_haze_flames.h\"") != 1:
        raise SystemExit("text check: vk_heat_haze.h")
    if t[UT].find("// m. bbport (r97d") > t[UT].find("// n. bbport (r97f"):
        raise SystemExit("text check: the unit test block is out of place")
    if t[CM].count("heat_haze_find_comp") != 2 or t[TEP].count("HEAT_HAZE_FIND_COMP") != 1:
        raise SystemExit("text check: cmake or pipeline test")
    if t[RM].count("BB_HEAT_HAZE_FLAMES") != 1 or t[RM].count("BB_HEAT_HAZE_FLAME_MIN") < 2:
        raise SystemExit("text check: README")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R97F_ROOT)" % ROOT)
    plan, states = [], []
    for path in PATHS:
        raw, eol, cur = load(path)
        if path == VCPP and "Heat haze (r97e)" not in cur:
            raise SystemExit("%s: r97e is not applied" % path)
        states.append((path, state_of(cur, EDITS[path], path)))
        plan.append((path, EDITS[path], raw, eol, cur))
    for path in NEW:
        states.append((path, new_state(path)))
    kinds = {s for _, s in states}
    if len(kinds) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % p for p in states))
    state = kinds.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur in plan:
            res = apply_edits(cur, eds)
            if state_of(res, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = res
        return out

    def write(items):
        for path, data in items:
            full = os.path.join(ROOT, path)
            tmp = full + ".r97ftmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, full)

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        write([(p[0], texts[p[0]].replace("\n", p[3]).encode("utf-8")) for p in plan])
        write([(path, text.replace("\n", "\r\n").encode("utf-8")) for path, text in NEW.items()])
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = []
    for path, eds, raw, eol, cur in plan:
        res = revert_edits(cur, eds)
        if state_of(res, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out.append((path, res.replace("\n", eol).encode("utf-8")))
    write(out)
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
