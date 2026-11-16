# r117_wind-shelter: FEATURE patch (wind, owner 2026-11-15 23:08: "... Then the wind goes broke or
# stopped by objects and walls"). Off by default behind BB_WIND_SHELTER (a strength 0-1; needs
# BB_WIND=1 and the plant sway's region, BB_WIND_SWAY above 0, its default). Applies on top of r89,
# r89b and r112 (as applied in the tree at 23:24); r89c (the plant motion's redraw) may come before
# or after: the shader hook sits right before the store of the displaced position, after whatever
# motion rule ran, and multiplies the displacement (so every rule, hanging things included, is
# sheltered the same way). Revert r117 before r112.
#
# Route chosen (the three the task weighed, against the real code):
#  A  wind shadow map (a depth map from the windward side): needs the scene's geometry drawn once more
#     from the wind's side, as the sun's cascades are; no cheap source of that geometry without ray
#     tracing, and a horizontal side view cannot see roofs (indoors). Not taken.
#  B  probe grid filled by short upwind rays through the ray traced scene: the most exact (roofs,
#     unseen walls, any normal) but it needs ray tracing, which the owner asked this not to need
#     ("Shouldn't this fix work without ray tracing or it needs ray tracing to work?"). Kept for
#     stage 2 as the fill of cells the depth never showed.
#  C  screen space: the depth buffer, a short march toward the wind per cell. TAKEN, made world
#     anchored: the depth's points are splatted into a toroidal 128 x 128 cache of 1 m cells (lowest
#     and highest height per cell, kept when the camera looks away), and a 64 x 64 window of the
#     field around the camera is made from the cache by three upwind rays a cell (median), a roof
#     test, a blur, an edge fade and a one second time filter. Looks right (a 3 m wall shelters fully
#     within 5 m and not at all past 17 m, the edge is soft, roofs and halls give 1); works without
#     ray tracing; stable under camera motion (world anchored cells, the window snaps to whole cells,
#     faded at its edge, followed in time); cost below; first visible stage: plants.
#  Not taken from C: "one value per plant mesh measured at its base": the CPU does not know a mesh's
#  world place and the sway shaders know every vertex's, so the plants read the field per vertex.
#
# ONE shared field (gpu/shim/bbport_wind_shelter.h has the whole interface): 64 x 64 floats and an
# 8 word header in the sway region's buffer at word 4096 (wind_shelter_layout.h), read by
# BbWindShelter::At (C++), wind_shelter_at (GLSL, wind_shelter.glsl) and the same operations emitted
# into the two plant shader emitters. What it takes away is a share 0-1 of the outside wind.
#  Stage 1 consumers: plants and hanging things (per vertex: the displacement times 1 - At, both
#  emitters); the sun fog's drift, the particles, the heat haze and the caustics (BbWind::State::
#  Advance's new `open` argument: the wind vector and the fog offsets move (1 - At at the camera) as
#  fast; at the camera only). Later stages: per sample in the fog march and per particle (the same
#  reader), the lamp fog, cloth, hair, gusts that arrive later behind an obstacle, the ray traced
#  fill, a second level (floors above).
#
# Off (the default): BbWindShelter::KnobOnce().on is false; the rasterizer makes no WindShelter (no
# pipeline, no buffer, no pass: its two hooks are null pointer tests); ObjectMotion's buffer keeps
# its length (BufferBytes) and nothing is written into it; the two emitters emit nothing (the sway
# SPIR-V is as before) and the sway shader binary version is as before (BinaryOffset 0); Advance's
# `open` is 1.0f (u * dir * 1.0f is the same float); BB_WIND off: none of it runs (the knob needs it).
# Cost on (estimates, not measured): GPU 4 small dispatches and one more with the view, 1080p
# internal: splat 130k threads (one pixel in 4: 480 x 270) with 3 atomics each = about 0.03 ms,
# merge 16k, rays 4k cells x 3 rays x 28 steps = 344k reads of a 590 KB cache = about 0.03 ms,
# final 4k: together 0.05-0.1 ms and 5 barriers; at 4K internal the splat grows with the pixels / 16
# (0.1 ms); vertex shaders of swaying plants: 8 loads and about 45 operations more a vertex (only
# draws with a sway word). CPU: one memcpy of the push (128 bytes) and one 4-byte read a frame.
# Memory: 590 KB cache + 64 B counters (device), 64 B host copy, +16.4 KB in the sway buffer.
#
# Files: new engine/gpu/shim/bbport_wind_shelter.h (knob, layout, reader, model, counters),
# engine/gpu/shadps4/video_core/host_shaders/wind_shelter_layout.h, wind_shelter.glsl,
# wind_shelter.comp (two builds: plain and SHOW=1), renderer_vulkan/vk_wind_shelter.h and .cpp,
# engine/tests/test_wind_shelter.cpp. Edits: bbport_wind.h (Advance's `open`), emit_spirv_special.cpp
# and lift_stage.cpp (the shelter block before the store), vk_pipeline_serialization.cpp (the sway
# binary version + 1000 with the knob), vk_object_motion.h/.cpp (the buffer length and the block's
# zeroing), vk_rasterizer.h/.cpp (the member and its creation), vk_rasterizer_effects.cpp (Advance's
# argument; the Apply hook right before the upscaler, after the heat haze), CMakeLists.txt (the
# shader builds, their includes, wind-shelter-test), build.sh (the test), README.md (two rows).
#
# Use: python -I -X utf8 r117_wind-shelter.py check | apply | revert
# Root: R117_ROOT, else <tree>. Line ends kept (CRLF in the tree; new files CRLF). apply backs
# the originals up in r117_backup next to this script; revert takes out exactly what apply put in
# (an inserted text is found by itself, so a later patch's text next to it stays; a replaced text
# goes back to the original) and removes the new files. check also runs a Python copy of the model
# against the numbers tests/test_wind_shelter.cpp asserts.
import math, os, sys

ROOT = os.environ.get("R117_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r117_backup")
E = "engine/gpu/"
RV = E + "shadps4/video_core/renderer_vulkan/"
HS = E + "shadps4/video_core/host_shaders/"
BW = E + "shim/bbport_wind.h"
EM = E + "shadps4/shader_recompiler/backend/spirv/emit_spirv_special.cpp"
LS = E + "shim/lifter/lift_stage.cpp"
PS = RV + "vk_pipeline_serialization.cpp"
OH = RV + "vk_object_motion.h"
OC = RV + "vk_object_motion.cpp"
RH = RV + "vk_rasterizer.h"
RC = RV + "vk_rasterizer.cpp"
RE = RV + "vk_rasterizer_effects.cpp"
CM = E + "CMakeLists.txt"
BS = "engine/build.sh"
RM = "README.md"
NH = E + "shim/bbport_wind_shelter.h"
NL = HS + "wind_shelter_layout.h"
NG = HS + "wind_shelter.glsl"
NC = HS + "wind_shelter.comp"
VH = RV + "vk_wind_shelter.h"
VC = RV + "vk_wind_shelter.cpp"
NT = "engine/tests/test_wind_shelter.cpp"

NEW_FILES = {
NH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r117_wind-shelter): where the wind is broken or stopped. ONE shelter field that every
// wind consumer reads the same way. Only with BB_WIND=1 and BB_WIND_SHELTER above 0 (the strength,
// 0-1) and the plant sway's region (BB_WIND_SWAY above 0: the field lives in its buffer).
//
// THE FIELD: a square of N x N = 64 x 64 cells of 1 m around the camera (its origin snaps to whole
// cells, so a world point's value never depends on where the camera stands inside a cell), each
// cell holding the share 0-1 of the outside wind that is taken away there: 0 in the open, 1
// indoors, in between behind a wall, a building or a tall tomb. It is a map at the camera's level
// (the reader fades it out over 4 m of height beyond 10 m from the camera's y). The GPU writes it
// once a frame (vk_wind_shelter.cpp, host_shaders/wind_shelter.comp, from the scene depth: no ray
// tracing needed) into the sway region's buffer at BlockWord (wind_shelter_layout.h has the words).
//
// THE READ: At(block, x, y, z) in C++, wind_shelter_at(region, p) in GLSL (wind_shelter.glsl) and
// the same operations emitted into the plant vertex shaders (emit_spirv_special.cpp, lift_stage.cpp:
// the displacement of a plant is multiplied by Factor = 1 - At). Bilinear, so a value changes
// smoothly with the position; the field itself is blurred, faded to 0 at its edge and followed in
// time with a 0.5 s time constant, so nothing jumps and a change is mostly through in a second.
// The wind at a point is (1 - At) times the open wind.
//
// CONSUMERS (stage 1): the plants and what hangs (r89, r89b, r112, r89c: the displacement of every
// vertex, per vertex); the sun fog's drift, the particles, the heat haze and the caustics' drift
// (BbWind::State::Advance's `open` argument: the wind vector and the fog offsets move (1 - At at
// the camera) as fast), at the camera only. Later: per sample in the fog march and per particle
// with wind_shelter_at (the interface is the same), the lamp fog, cloth, hair.
//
// THE MODEL (CPU copy of the shader's, tests/test_wind_shelter.cpp): Raw. The pure parts here are
// the knob, the layout, the quantisation, the reader and the model; the GPU copy repeats them
// operation for operation where a number must agree (the reader) and by the same rule where it is a
// loop (the passes).

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstddef>

#include "../shadps4/video_core/host_shaders/wind_shelter_layout.h"
#include "bbport_wind.h"
#include "bbport_wind_sway.h"

namespace BbWindShelter {

inline constexpr std::uint32_t N = WS_N, M = WS_M, BlockWord = WS_BLOCK_WORD,
                               HeaderWords = WS_HEADER_WORDS, Steps = WS_STEPS,
                               Stride = WS_STRIDE, MinSamples = WS_MIN_SAMPLES,
                               SnapFrames = WS_SNAP_FRAMES;
inline constexpr std::uint32_t BlockWords = HeaderWords + N * N;
inline constexpr std::uint32_t BlockBytes = BlockWords * 4;
inline constexpr float Cell = WS_CELL, Band = WS_BAND, BandSoft = WS_BAND_SOFT;
inline constexpr float HStart = WS_H_START, TanLo = WS_TAN_LO, TanHi = WS_TAN_HI;
inline constexpr float LiftLo = WS_LIFT_LO, LiftHi = WS_LIFT_HI;
inline constexpr float RoofLo = WS_ROOF_LO, RoofHi = WS_ROOF_HI, RoofGain = WS_ROOF_GAIN;
inline constexpr float RayDeg = WS_RAY_DEG, Gain = WS_GAIN, EdgeCells = WS_EDGE_CELLS;
inline constexpr float Tau = WS_TAU, NoGround = WS_NO_GROUND;
inline constexpr float YBias = WS_Y_BIAS, YScale = WS_Y_SCALE;
inline constexpr std::uint32_t BinaryAdd = 1000; ///< added to the sway shader binary version when on

static_assert(BlockWord >= BbWindSway::RegionWords && BlockWord % 4 == 0,
              "the field lies behind the sway words (r112's longer region ends at word 3584)");
static_assert(HeaderWords == 8 && N % 8 == 0 && M % 8 == 0 && M >= N + 2 * (Steps + 2),
              "the cache holds the window and every upwind ray from it");
static_assert(N / 2 > std::uint32_t(EdgeCells) && Stride >= 1);
static_assert(TanHi > TanLo && LiftHi > LiftLo && RoofHi > RoofLo);

/// What BB_WIND_SHELTER, BB_WIND_SHELTER_SHOW say.
struct Knob {
    bool wind = false;      ///< BB_WIND=1
    bool asked = false;     ///< a strength above 0
    bool on = false;        ///< wind, asked and the plant sway on (the region exists)
    float strength = 0.0f;  ///< 0-1: the most of the wind the field may take away
    int show = 0;           ///< BB_WIND_SHELTER_SHOW: 1 the field over the scene, 2 alone on black
    bool unreadable = false;
};

[[nodiscard]] inline float ParseStrength(const char* text, bool& unreadable) {
    unreadable = false;
    if (text == nullptr || text[0] == 0) {
        return 0.0f;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || !std::isfinite(value)) {
        unreadable = true;
        return 0.0f;
    }
    return std::clamp(value, 0.0f, 1.0f);
}

[[nodiscard]] inline Knob ParseKnob(const char* wind, const char* shelter, const char* show,
                                    bool sway_on) {
    Knob k;
    k.wind = wind != nullptr && wind[0] == '1';
    k.strength = ParseStrength(shelter, k.unreadable);
    k.asked = k.strength > 0.0f;
    k.on = k.wind && k.asked && sway_on;
    k.show = show != nullptr && show[0] == '1' && show[1] == 0   ? 1
             : show != nullptr && show[0] == '2' && show[1] == 0 ? 2
                                                                 : 0;
    return k;
}

/// Read once, at the first use (the pipeline cache's first key, or the motion buffer).
[[nodiscard]] inline const Knob& KnobOnce() {
    static const Knob knob = ParseKnob(std::getenv("BB_WIND"), std::getenv("BB_WIND_SHELTER"),
                                       std::getenv("BB_WIND_SHELTER_SHOW"),
                                       BbWindSway::KnobOnce().on);
    return knob;
}

/// The sway region's buffer length with the field behind it, when it is on.
[[nodiscard]] inline std::uint32_t BufferBytes(std::uint32_t region_bytes) {
    return KnobOnce().on ? std::max(region_bytes, BlockWord * 4 + BlockBytes) : region_bytes;
}

/// Added to the serialized sway shader binary version: 0 off (the shader is as before), BinaryAdd
/// on (the shader has the field's read), so a saved shader of the other kind is built again.
[[nodiscard]] inline std::uint32_t BinaryOffset() {
    return KnobOnce().on ? BinaryAdd : 0u;
}

// ---- the reader ---------------------------------------------------------------------------

[[nodiscard]] inline float Lerp(float a, float b, float t) {
    return a + (b - a) * t;
}

/// The share (0-1) of the wind taken away at the world point (x, y, z): `block` is the field's
/// words (the region's words from BlockWord, as floats; header word 4 is not read: the size is N).
/// wind_shelter_at in GLSL repeats this operation for operation. 0 outside the field, where it was not written (marker 0 or not above
/// 0.5) and beyond the vertical band; otherwise the bilinear value times the band's weight times the
/// strength the header holds.
[[nodiscard]] inline float At(const float* block, float x, float y, float z) {
    if (!(block[0] > 0.5f)) {
        return 0.0f;
    }
    const float ox = block[1], oz = block[2], inv_cell = block[3], n = float(N);
    const float ref_y = block[5], strength = block[6], band = block[7];
    float fx = (x - ox) * inv_cell - 0.5f;
    float fz = (z - oz) * inv_cell - 0.5f;
    const float x0 = std::floor(fx), z0 = std::floor(fz);
    if (!(x0 >= 0.0f && z0 >= 0.0f && x0 < n - 1.0f && z0 < n - 1.0f)) {
        return 0.0f;
    }
    fx -= x0;
    fz -= z0;
    const std::uint32_t un = std::uint32_t(n);
    const std::uint32_t cell = HeaderWords + std::uint32_t(z0) * un + std::uint32_t(x0);
    const float a = block[cell], b = block[cell + 1], c = block[cell + un], d = block[cell + un + 1];
    const float s = Lerp(Lerp(a, b, fx), Lerp(c, d, fx), fz);
    const float level = std::clamp((band - std::fabs(y - ref_y)) * (1.0f / BandSoft), 0.0f, 1.0f);
    return s * level * strength;
}

/// What a plant's displacement is multiplied by: 1 - At.
[[nodiscard]] inline float Factor(const float* block, float x, float y, float z) {
    return 1.0f - At(block, x, y, z);
}

/// The field's header for a window whose origin cell is (cell_x, cell_z) (what the final pass
/// writes; tests use it to build a block).
inline void WriteHeader(float* block, int cell_x, int cell_z, float ref_y, float strength) {
    block[0] = 1.0f;
    block[1] = float(cell_x) * Cell;
    block[2] = float(cell_z) * Cell;
    block[3] = 1.0f / Cell;
    block[4] = float(N);
    block[5] = ref_y;
    block[6] = strength;
    block[7] = Band;
}

/// `open` for BbWind::State::Advance from the field's value at the camera: the share of the wind
/// that stays, 0-1 (a value that is not a number counts as no shelter).
[[nodiscard]] inline float Open(float shelter_at_camera) {
    return std::isfinite(shelter_at_camera) ? std::clamp(1.0f - shelter_at_camera, 0.0f, 1.0f)
                                            : 1.0f;
}

// ---- the model (the shader's passes, in C++) -------------------------------------------------

/// Heights as the GPU keeps them: 16 bits, 1/32 m.
[[nodiscard]] inline std::uint32_t Quant(float y) {
    return std::uint32_t(std::clamp(std::floor((y + YBias) * YScale + 0.5f), 0.0f, 65535.0f));
}

[[nodiscard]] inline float Unquant(std::uint32_t q) {
    return float(q) / YScale - YBias;
}

/// What the cache knows of a cell: the lowest and highest height seen in it (m).
struct Column {
    float bot = 0.0f, top = 0.0f;
    bool seen = false;
};

[[nodiscard]] inline Column ColumnOf(float bot, float top) {
    return {Unquant(Quant(bot)), Unquant(Quant(top)), true};
}

[[nodiscard]] inline float Median3(float a, float b, float c) {
    return std::max(std::min(a, b), std::min(std::max(a, b), c));
}

/// A ray from the middle of cell (cx, cz) UPWIND along (dx, dz) (a unit vector): how far it is
/// blocked, 0-1. `column(ix, iz)` gives the Column of a cell. Each step is one cell; a column
/// whose top stands more than HStart above `ground` blocks by smoothstep(TanLo, TanHi, excess /
/// distance), less if its bottom is high above the ground (a deck or an arch).
template <class ColumnFn>
[[nodiscard]] float RayBlocked(ColumnFn&& column, int cx, int cz, float dx, float dz,
                               float ground) {
    const float fx = (float(cx) + 0.5f) * Cell, fz = (float(cz) + 0.5f) * Cell;
    float blocked = 0.0f;
    for (std::uint32_t k = 1; k <= Steps && blocked < 1.0f; ++k) {
        const float dist = float(k) * Cell;
        const int ix = int(std::floor((fx + dx * dist) * (1.0f / Cell)));
        const int iz = int(std::floor((fz + dz * dist) * (1.0f / Cell)));
        const Column col = column(ix, iz);
        if (col.seen) {
            const float excess = std::max(col.top - ground - HStart, 0.0f);
            const float lift = col.bot - ground;
            const float pass = 1.0f - BbWind::Smoothstep(LiftLo, LiftHi, lift);
            blocked = std::max(blocked, BbWind::Smoothstep(TanLo, TanHi, excess / dist) * pass);
        }
    }
    return blocked;
}

[[nodiscard]] inline std::array<float, 2> Rotated(float vx, float vz, float deg) {
    const float a = deg * (3.14159265358979323846f / 180.0f);
    const float cs = std::cos(a), sn = std::sin(a);
    return {vx * cs - vz * sn, vx * sn + vz * cs};
}

/// The raw shelter of cell (cx, cz) for a wind blowing toward (dir_x, dir_z): the median of three
/// upwind rays (-RayDeg, 0, +RayDeg) is the leeward value, the roof above the cell adds to it:
/// 1 - (1 - leeward) (1 - RoofGain roof). `cam_y`: the camera's height, which gives the ground of a
/// cell nothing is known about (cam_y - NoGround).
template <class ColumnFn>
[[nodiscard]] float Raw(ColumnFn&& column, int cx, int cz, float dir_x, float dir_z, float cam_y) {
    const Column own = column(cx, cz);
    float ground = cam_y - NoGround;
    if (own.seen) {
        ground = own.bot;
    } else {
        float lowest = 1.0e9f;
        for (int j = -1; j <= 1; ++j) {
            for (int i = -1; i <= 1; ++i) {
                const Column nb = column(cx + i, cz + j);
                if (nb.seen) {
                    lowest = std::min(lowest, nb.bot);
                }
            }
        }
        if (lowest < 1.0e8f) {
            ground = lowest;
        }
    }
    const float ux = -dir_x, uz = -dir_z;
    const auto a = Rotated(ux, uz, -RayDeg);
    const auto c = Rotated(ux, uz, RayDeg);
    const float r0 = RayBlocked(column, cx, cz, a[0], a[1], ground);
    const float r1 = RayBlocked(column, cx, cz, ux, uz, ground);
    const float r2 = RayBlocked(column, cx, cz, c[0], c[1], ground);
    const float leeward = Median3(r0, r1, r2);
    const float roof = own.seen ? BbWind::Smoothstep(RoofLo, RoofHi, own.top - ground) : 0.0f;
    return 1.0f - (1.0f - leeward) * (1.0f - RoofGain * roof);
}

/// The window's edge weight of cell (i, j) of the N x N window: 0 at the border, 1 from
/// EdgeCells in.
[[nodiscard]] inline float EdgeFade(std::uint32_t i, std::uint32_t j) {
    const std::uint32_t edge = std::min(std::min(i, N - 1 - i), std::min(j, N - 1 - j));
    return BbWind::Smoothstep(0.0f, EdgeCells, float(edge));
}

/// The target of the final pass from a blurred raw value and the window position.
[[nodiscard]] inline float Target(float blurred, std::uint32_t i, std::uint32_t j) {
    return std::min(blurred * Gain, 1.0f) * EdgeFade(i, j);
}

/// One step of the time filter: the share `dt` seconds take of the way to the target.
[[nodiscard]] inline float Follow(float prev, float target, float dt) {
    const float k = 1.0f - std::exp(-dt * (1.0f / Tau));
    return prev + (target - prev) * k;
}

/// wind_shelter.comp's push constants (128 bytes, the GLSL block lists the same fields in the same
/// order): the sway region's address, the pass, the frame, the camera's view to world rows (3x4),
/// the projection (x, y, z scale, z offset), the scene's size and jitter, the wind (dir_x, dir_z, dt,
/// strength) and the camera's cell, the test view, 0.
struct Push {
    std::uint64_t region = 0;
    std::uint32_t mode = 0, frame = 0;
    std::array<float, 4> row0{}, row1{}, row2{}, proj{}, size_jitter{}, wind{};
    std::array<std::int32_t, 4> cells{};
};
static_assert(sizeof(Push) == 128 && offsetof(Push, row0) == 16 && offsetof(Push, cells) == 112);

// ---- the log ---------------------------------------------------------------------------------

/// The GPU's counters (wind_shelter_layout.h's WS_C_ words) between two reads.
struct Counts {
    std::uint64_t pixels = 0, sheltered = 0, indoor = 0, sum = 0; ///< depth samples (sum: 1/1000)
    std::uint64_t cells_seen = 0, cells_sheltered = 0, cells = 0, cells_sum = 0, merged = 0;
};

[[nodiscard]] inline Counts CountsBetween(const std::uint32_t* now, const std::uint32_t* before) {
    const auto d = [&](std::uint32_t w) { return std::uint64_t(std::uint32_t(now[w] - before[w])); };
    return {d(WS_C_PIXELS),         d(WS_C_PIXELS_SHELTERED), d(WS_C_PIXELS_INDOOR),
            d(WS_C_PIXELS_SUM),     d(WS_C_CELLS_SEEN),       d(WS_C_CELLS_SHELTERED),
            d(WS_C_CELLS),          d(WS_C_CELLS_SUM),        d(WS_C_MERGED)};
}

/// The share of the sampled view (the depth pixels) with a field above 0.5, and above 0.95, and
/// the mean field there; 0 without samples.
[[nodiscard]] inline double ViewSheltered(const Counts& c) {
    return c.pixels != 0 ? double(c.sheltered) / double(c.pixels) : 0.0;
}
[[nodiscard]] inline double ViewIndoor(const Counts& c) {
    return c.pixels != 0 ? double(c.indoor) / double(c.pixels) : 0.0;
}
[[nodiscard]] inline double ViewMean(const Counts& c) {
    return c.pixels != 0 ? double(c.sum) / 1000.0 / double(c.pixels) : 0.0;
}

/// The field at the camera from the counter word (float bits), 0-1; not a number counts as 0.
[[nodiscard]] inline float CameraShelter(std::uint32_t word) {
    const float v = std::bit_cast<float>(word);
    return std::isfinite(v) ? std::clamp(v, 0.0f, 1.0f) : 0.0f;
}

} // namespace BbWindShelter
''',
NL: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r117_wind-shelter): what the wind shelter's shader (wind_shelter.comp), its reader
// (wind_shelter.glsl) and the engine (gpu/shim/bbport_wind_shelter.h, which ties these to its own
// constants with static_asserts) share. Plain #define lines only: the shaders include this file
// through GL_GOOGLE_include_directive and C++ includes it as it is, so one text holds every number
// both sides use. Floats carry the f suffix (valid in GLSL 450 and in C++).
#ifndef WIND_SHELTER_LAYOUT_H
#define WIND_SHELTER_LAYOUT_H

// The field the vertex shaders, the fog and the particles read: a square of WS_N x WS_N cells of
// WS_CELL m, in the sway region's buffer (words, from its start) at WS_BLOCK_WORD: 8 header words
// then WS_N * WS_N floats, row after row (z), cell (i, j) = world x ox + (i + 0.5) WS_CELL, z oz +
// (j + 0.5) WS_CELL. Header words (floats): 0 the marker (1 once written, 0 before), 1 ox, 2 oz,
// 3 1 / WS_CELL, 4 WS_N, 5 the camera's y (the field's level), 6 the strength (BB_WIND_SHELTER),
// 7 the half band (m) of the level within which the field holds.
#define WS_BLOCK_WORD 4096u
#define WS_HEADER_WORDS 8u
#define WS_N 64u
#define WS_CELL 1.0f
#define WS_BAND 14.0f
#define WS_BAND_SOFT 4.0f

// The cache of what the depth showed (toroidal, WS_M x WS_M cells): per cell WS_CELL_WORDS words,
// then the frame's own min/max (WS_FRESH_WORDS words a cell) after all of them.
#define WS_M 128u
#define WS_CELL_WORDS 6u
#define WS_FRESH_WORDS 3u
#define WS_STRIDE 4u
#define WS_MIN_SAMPLES 2u
#define WS_STEPS 28u

// Quantised heights: y -> round((y + WS_Y_BIAS) * WS_Y_SCALE) in 16 bits.
#define WS_Y_BIAS 1024.0f
#define WS_Y_SCALE 32.0f

// The model (see bbport_wind_shelter.h for what each number means).
#define WS_H_START 1.0f
#define WS_TAN_LO 0.12f
#define WS_TAN_HI 0.40f
#define WS_LIFT_LO 1.2f
#define WS_LIFT_HI 2.4f
#define WS_ROOF_LO 2.0f
#define WS_ROOF_HI 3.2f
#define WS_ROOF_GAIN 0.5f
#define WS_RAY_DEG 14.0f
#define WS_GAIN 1.06f
#define WS_EDGE_CELLS 4.0f
#define WS_TAU 0.5f
#define WS_SNAP_FRAMES 20u
#define WS_NO_GROUND 1.7f

// The passes, by the push word `mode`.
#define WS_MODE_CLEAR 0u
#define WS_MODE_SPLAT 1u
#define WS_MODE_MERGE 2u
#define WS_MODE_RAW 3u
#define WS_MODE_FINAL 4u
#define WS_MODE_SHOW 5u
#define WS_GROUP 8u

// The counter words (32-bit totals except WS_C_CAMERA, a float's bits, overwritten each frame).
#define WS_COUNTER_WORDS 16u
#define WS_C_PIXELS 0u         // depth samples read by the splat pass
#define WS_C_PIXELS_SHELTERED 1u // of them where last frame's field was above 0.5
#define WS_C_PIXELS_SUM 2u     // sum of last frame's field there, in thousandths
#define WS_C_PIXELS_INDOOR 3u  // of them above 0.95
#define WS_C_CELLS_SEEN 4u     // window cells with depth data (raw pass)
#define WS_C_CELLS_SHELTERED 5u // window cells whose new field is above 0.5 (final pass)
#define WS_C_CAMERA 6u         // last frame's field at the camera (float bits)
#define WS_C_CELLS_SUM 7u      // sum of the window's field, in thousandths
#define WS_C_MERGED 8u         // cache cells that took this frame's samples
#define WS_C_CELLS 9u          // window cells written (final pass)

#endif
''',
NG: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r117_wind-shelter): THE reader of the wind shelter field, for every compute shader that
// takes the wind (stage 1: wind_shelter.comp's counters and test view; the sun fog's march and the
// particles read it with this function in later stages). gpu/shim/bbport_wind_shelter.h's
// BbWindShelter::At is this function in C++, operation for operation (a lerp is a + (b - a) t), and
// the two plant shader emitters (emit_spirv_special.cpp, lift_stage.cpp) emit the same operations.
//
// The field lives in the sway region's buffer (wind_shelter_layout.h says where and how): `r` is a
// buffer reference to the region's first word (the sway words' base address, which is the motion
// params buffer's address + MotionVectors::ParamsCapacity * 32 bytes). The shader declares nothing
// else. Needs GL_EXT_buffer_reference and wind_shelter_layout.h.
//
// wind_shelter_at(r, p): the share (0-1) of the outside wind that is taken away at the world point
// p: 0 in the open, outside the field (further than half of WS_N cells from the camera) or where
// the field was never written; 1 indoors. It is the field's bilinear value times the vertical band
// (the field is a map at the camera's level: full within WS_BAND - WS_BAND_SOFT m of the camera's
// height, 0 beyond WS_BAND) times the strength BB_WIND_SHELTER. The wind there is
// (1 - wind_shelter_at) times the open wind.

layout(buffer_reference, std430, buffer_reference_align = 4) buffer WindShelterRegion {
    uint w[];
};

float wind_shelter_lerp(float a, float b, float t) {
    return a + (b - a) * t;
}

float wind_shelter_at(WindShelterRegion r, vec3 p) {
    const uint at = WS_BLOCK_WORD;
    if (!(uintBitsToFloat(r.w[at]) > 0.5)) {
        return 0.0;
    }
    const float ox = uintBitsToFloat(r.w[at + 1u]);
    const float oz = uintBitsToFloat(r.w[at + 2u]);
    const float inv_cell = uintBitsToFloat(r.w[at + 3u]);
    const float n = float(WS_N); // (header word 4 holds the same number; not read)
    const float ref_y = uintBitsToFloat(r.w[at + 5u]);
    const float strength = uintBitsToFloat(r.w[at + 6u]);
    const float band = uintBitsToFloat(r.w[at + 7u]);
    float fx = (p.x - ox) * inv_cell - 0.5;
    float fz = (p.z - oz) * inv_cell - 0.5;
    const float x0 = floor(fx);
    const float z0 = floor(fz);
    if (!(x0 >= 0.0 && z0 >= 0.0 && x0 < n - 1.0 && z0 < n - 1.0)) {
        return 0.0;
    }
    fx -= x0;
    fz -= z0;
    const uint cell = at + WS_HEADER_WORDS + uint(z0) * uint(n) + uint(x0);
    const float a = uintBitsToFloat(r.w[cell]);
    const float b = uintBitsToFloat(r.w[cell + 1u]);
    const float c = uintBitsToFloat(r.w[cell + uint(n)]);
    const float d = uintBitsToFloat(r.w[cell + uint(n) + 1u]);
    const float s = wind_shelter_lerp(wind_shelter_lerp(a, b, fx), wind_shelter_lerp(c, d, fx), fz);
    const float level = clamp((band - abs(p.y - ref_y)) * (1.0 / WS_BAND_SOFT), 0.0, 1.0);
    return s * level * strength;
}
''',
NC: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r117_wind-shelter): the wind shelter field (BB_WIND_SHELTER; vk_wind_shelter.cpp runs
// these passes once a frame, right before the upscaler, when the scene depth is complete).
//
// What the field is: for every cell of a WS_N x WS_N window (1 m cells, around the camera) the
// share of the outside wind that is taken away there, 0 in the open, 1 indoors. It is made from
// what the camera's depth buffer has shown, so it needs no ray tracing:
//  SPLAT  every WS_STRIDE-th depth pixel is a world point; its cell keeps the frame's lowest and
//         highest height (atomic min/max, 16 bits) and a count. The pixels also read last frame's
//         field (the same reader the plants use) for the log's "share of the view sheltered".
//  MERGE  a cell with at least WS_MIN_SAMPLES samples takes this frame's lowest and highest height
//         into the cache (128 x 128 cells, toroidal, world anchored: a cell the camera no longer
//         sees keeps what it showed last); a cache slot that now belongs to another world cell is
//         emptied first. The frame's min/max are reset.
//  RAW    per window cell: the wind blows toward (dir_x, dir_z); three rays leave the cell UPWIND
//         (-14, 0, +14 degrees), WS_STEPS cells long. A ray is blocked by a cell whose top stands
//         more than WS_H_START above the receiving cell's ground g (its lowest height, or the
//         lowest of its neighbours, or the camera's height minus WS_NO_GROUND) by
//         smoothstep(WS_TAN_LO, WS_TAN_HI, (top - g - WS_H_START) / distance): a wall 3 m high
//         shelters fully within 5 m behind it and not at all beyond 17 m; a cell that starts
//         WS_LIFT_LO..HI above g (a bridge, an arch) blocks less. The leeward value is the MEDIAN of
//         the three rays (a thin obstacle, a lamp post, a person, cannot shelter: the air goes
//         round; a wall can). Overhead: a cell whose own top is WS_ROOF_LO..HI above its ground has
//         a roof; raw = 1 - (1 - leeward) (1 - WS_ROOF_GAIN roof): indoors the walls and the roof
//         together give 1, an open pavilion about a half.
//  FINAL  the raw field blurred 3 x 3 (1 2 1), times WS_GAIN (a bit above 1, so indoors is exactly
//         1) and faded to 0 over the outer WS_EDGE_CELLS cells of the window (so that the window
//         following the camera never makes a value jump), then followed in time (exp(-dt / WS_TAU),
//         WS_TAU 0.5 s: a change is mostly through in a second) and written into the region (the
//         reader, wind_shelter.glsl, takes it from there) with the header.
//  SHOW   (the SHOW build only) the field painted over the scene colour (cells.z 0), or alone
//         on black (1): green open, yellow half, red sheltered.
// Stage 1 limits (see the context file): one level (the camera's, +-10 m), no ray tracing, the
// player and monsters count as thin obstacles (the median drops most of them), canopies and
// bridge decks whose underside the camera has seen count as walls or roofs.
#version 450
#extension GL_EXT_buffer_reference : require
#extension GL_EXT_samplerless_texture_functions : require
#extension GL_GOOGLE_include_directive : require

#include "wind_shelter_layout.h"
#include "wind_shelter.glsl"

layout(local_size_x = WS_GROUP, local_size_y = WS_GROUP) in;

layout(binding = 0) uniform texture2D depth_tex; // D32, 0 near .. 1 far (D3D projection)
layout(std430, binding = 1) buffer State {
    uint s[];
} state;
layout(std430, binding = 2) buffer Counters {
    uint c[];
} counters;
#ifdef SHOW
layout(binding = 3, rgba16f) uniform image2D scene_img;
#endif

// wind_shelter.h's Push, field for field (128 bytes).
layout(push_constant) uniform Push {
    WindShelterRegion region;
    uint mode;
    uint frame;
    vec4 row0; // the camera's view to world matrix, 3x4 rows (w: the camera's place)
    vec4 row1;
    vec4 row2;
    vec4 proj;        // x scale, y scale (signed), z scale, z offset (as heat_haze.comp)
    vec4 size_jitter; // the scene's width, height, the viewport's shift (px)
    vec4 wind;        // dir_x, dir_z (toward where it blows), dt (s), strength
    ivec4 cells;      // the camera's cell x, z; the test view (0 tint, 1 alone); 0
};

const int M = int(WS_M);
const int N = int(WS_N);

int wrap_mod(int a, int m) {
    const int r = a - (a / m) * m;
    return r < 0 ? r + m : r;
}

uint slot_of(ivec2 c) {
    return uint(wrap_mod(c.y, M)) * WS_M + uint(wrap_mod(c.x, M));
}

uint quant(float y) {
    return uint(clamp(floor((y + WS_Y_BIAS) * WS_Y_SCALE + 0.5), 0.0, 65535.0));
}

float unquant(uint q) {
    return float(q) / WS_Y_SCALE - WS_Y_BIAS;
}

uint cache_at(uint slot, uint k) {
    return state.s[slot * WS_CELL_WORDS + k];
}

uint fresh_at(uint slot) {
    return WS_M * WS_M * WS_CELL_WORDS + slot * WS_FRESH_WORDS;
}

// What the cache holds for a world cell: x lowest y, y highest y (m), z 1 if seen.
vec3 column(ivec2 c) {
    const uint h = cache_at(slot_of(c), 0u);
    const uint top = h & 0xffffu;
    const uint bot = h >> 16u;
    if (top < bot) {
        return vec3(0.0);
    }
    return vec3(unquant(bot), unquant(top), 1.0);
}

float view_z(float depth) {
    return proj.w / min(depth - proj.z, -1e-8);
}

vec3 world_of(vec2 pix, float depth) {
    const float z = view_z(depth);
    const vec2 ndc = ((pix - size_jitter.zw) / size_jitter.xy - 0.5) * 2.0;
    const vec4 h = vec4(ndc.x * z / proj.x, ndc.y * z / proj.y, z, 1.0);
    return vec3(dot(row0, h), dot(row1, h), dot(row2, h));
}

shared uint g_pixels, g_sheltered, g_sum, g_indoor;

void splat() {
    if (gl_LocalInvocationIndex == 0u) {
        g_pixels = 0u;
        g_sheltered = 0u;
        g_sum = 0u;
        g_indoor = 0u;
    }
    barrier();
    const ivec2 size = ivec2(size_jitter.xy);
    const ivec2 px = ivec2(gl_GlobalInvocationID.xy) * int(WS_STRIDE) + int(WS_STRIDE / 2u);
    if (all(lessThan(px, size))) {
        const float depth = texelFetch(depth_tex, px, 0).r;
        if (depth > 0.0 && depth < 1.0) {
            const float z = view_z(depth);
            if (z > 0.0 && z < 90.0) {
                const vec3 p = world_of(vec2(px) + 0.5, depth);
                const ivec2 c = ivec2(floor(p.xz * (1.0 / WS_CELL)));
                const ivec2 rel = c - (cells.xy - M / 2);
                if (all(greaterThanEqual(rel, ivec2(0))) && all(lessThan(rel, ivec2(M)))) {
                    const uint f = fresh_at(slot_of(c));
                    const uint q = quant(p.y);
                    atomicMax(state.s[f], q);
                    atomicMin(state.s[f + 1u], q);
                    atomicAdd(state.s[f + 2u], 1u);
                }
                const float v = wind_shelter_at(region, p);
                atomicAdd(g_pixels, 1u);
                atomicAdd(g_sum, uint(v * 1000.0 + 0.5));
                if (v > 0.5) {
                    atomicAdd(g_sheltered, 1u);
                }
                if (v > 0.95) {
                    atomicAdd(g_indoor, 1u);
                }
            }
        }
    }
    barrier();
    if (gl_LocalInvocationIndex == 0u) {
        if (g_pixels != 0u) {
            atomicAdd(counters.c[WS_C_PIXELS], g_pixels);
            atomicAdd(counters.c[WS_C_PIXELS_SHELTERED], g_sheltered);
            atomicAdd(counters.c[WS_C_PIXELS_SUM], g_sum);
            atomicAdd(counters.c[WS_C_PIXELS_INDOOR], g_indoor);
        }
    }
    if (gl_GlobalInvocationID.x == 0u && gl_GlobalInvocationID.y == 0u) {
        // last frame's field where the camera is (the log's number, and the fog's and the
        // particles' stage 1 reader: Rasterizer::WindOnFrameEnd)
        counters.c[WS_C_CAMERA] =
            floatBitsToUint(wind_shelter_at(region, vec3(row0.w, row1.w, row2.w)));
    }
}

void clear_all() {
    const uvec2 id = gl_GlobalInvocationID.xy;
    if (id.x >= WS_M || id.y >= WS_M) {
        return;
    }
    const uint slot = id.y * WS_M + id.x;
    const uint cw = slot * WS_CELL_WORDS;
    state.s[cw] = 0xffff0000u;
    state.s[cw + 1u] = 0u;
    state.s[cw + 2u] = 0u;
    state.s[cw + 3u] = 0u;
    state.s[cw + 4u] = 0xffffffffu;
    state.s[cw + 5u] = 0u;
    const uint f = fresh_at(slot);
    state.s[f] = 0u;
    state.s[f + 1u] = 0xffffu;
    state.s[f + 2u] = 0u;
}

void merge() {
    const uvec2 id = gl_GlobalInvocationID.xy;
    if (id.x >= WS_M || id.y >= WS_M) {
        return;
    }
    const ivec2 base = cells.xy - M / 2;
    const ivec2 world = base + ivec2(wrap_mod(int(id.x) - base.x, M), wrap_mod(int(id.y) - base.y, M));
    const uint slot = id.y * WS_M + id.x;
    const uint cw = slot * WS_CELL_WORDS;
    const uint want = (uint(world.x) & 0xffffu) | ((uint(world.y) & 0xffffu) << 16u);
    if (state.s[cw + 4u] != want) {
        state.s[cw] = 0xffff0000u;
        state.s[cw + 1u] = 0u;
        state.s[cw + 2u] = 0u;
        state.s[cw + 3u] = 0u;
        state.s[cw + 4u] = want;
    }
    const uint f = fresh_at(slot);
    const uint top = state.s[f];
    const uint bot = state.s[f + 1u];
    const uint n = state.s[f + 2u];
    state.s[f] = 0u;
    state.s[f + 1u] = 0xffffu;
    state.s[f + 2u] = 0u;
    if (n >= WS_MIN_SAMPLES) {
        state.s[cw] = (top & 0xffffu) | (bot << 16u);
        atomicAdd(counters.c[WS_C_MERGED], 1u);
    }
}

// One ray from the cell centre `from` (world, m) upwind along `dir`: how far it is blocked, 0-1.
float ray(vec2 from, vec2 dir, float ground) {
    float blocked = 0.0;
    for (uint k = 1u; k <= WS_STEPS && blocked < 1.0; ++k) {
        const float dist = float(k) * WS_CELL;
        const ivec2 c = ivec2(floor((from + dir * dist) * (1.0 / WS_CELL)));
        const vec3 col = column(c);
        if (col.z > 0.0) {
            const float eff = max(col.y - ground - WS_H_START, 0.0);
            const float lift = col.x - ground;
            const float pass_ = 1.0 - smoothstep(WS_LIFT_LO, WS_LIFT_HI, lift);
            blocked = max(blocked, smoothstep(WS_TAN_LO, WS_TAN_HI, eff / dist) * pass_);
        }
    }
    return blocked;
}

vec2 rotated(vec2 v, float deg) {
    const float a = radians(deg);
    const float cs = cos(a);
    const float sn = sin(a);
    return vec2(v.x * cs - v.y * sn, v.x * sn + v.y * cs);
}

void raw_pass() {
    const uvec2 id = gl_GlobalInvocationID.xy;
    if (id.x >= WS_N || id.y >= WS_N) {
        return;
    }
    const ivec2 c = cells.xy - N / 2 + ivec2(id);
    const vec3 own = column(c);
    float ground = row1.w - WS_NO_GROUND;
    if (own.z > 0.0) {
        ground = own.x;
    } else {
        float lowest = 1.0e9;
        for (int j = -1; j <= 1; ++j) {
            for (int i = -1; i <= 1; ++i) {
                const vec3 nb = column(c + ivec2(i, j));
                if (nb.z > 0.0) {
                    lowest = min(lowest, nb.x);
                }
            }
        }
        if (lowest < 1.0e8) {
            ground = lowest;
        }
    }
    const vec2 from = (vec2(c) + 0.5) * WS_CELL;
    const vec2 upwind = -wind.xy;
    const float r0 = ray(from, rotated(upwind, -WS_RAY_DEG), ground);
    const float r1 = ray(from, upwind, ground);
    const float r2 = ray(from, rotated(upwind, WS_RAY_DEG), ground);
    const float leeward = max(min(r0, r1), min(max(r0, r1), r2));
    const float roof = own.z > 0.0 ? smoothstep(WS_ROOF_LO, WS_ROOF_HI, own.y - ground) : 0.0;
    const float raw = 1.0 - (1.0 - leeward) * (1.0 - WS_ROOF_GAIN * roof);
    state.s[slot_of(c) * WS_CELL_WORDS + 1u] = floatBitsToUint(raw);
    if (own.z > 0.0) {
        atomicAdd(counters.c[WS_C_CELLS_SEEN], 1u);
    }
}

void final_pass() {
    const uvec2 id = gl_GlobalInvocationID.xy;
    if (id.x >= WS_N || id.y >= WS_N) {
        return;
    }
    const ivec2 origin = cells.xy - N / 2;
    const ivec2 c = origin + ivec2(id);
    float blur = 0.0;
    for (int j = -1; j <= 1; ++j) {
        for (int i = -1; i <= 1; ++i) {
            const float weight = float((2 - abs(i)) * (2 - abs(j))) * (1.0 / 16.0);
            blur += weight * uintBitsToFloat(cache_at(slot_of(c + ivec2(i, j)), 1u));
        }
    }
    const int edge = min(min(int(id.x), N - 1 - int(id.x)), min(int(id.y), N - 1 - int(id.y)));
    const float fade = smoothstep(0.0, WS_EDGE_CELLS, float(edge));
    const float target = min(blur * WS_GAIN, 1.0) * fade;
    const uint cw = slot_of(c) * WS_CELL_WORDS;
    float prev = uintBitsToFloat(state.s[cw + 2u]);
    const uint stamp = state.s[cw + 3u];
    if (stamp == 0u || frame - stamp > WS_SNAP_FRAMES) {
        prev = target;
    }
    const float follow = 1.0 - exp(-wind.z * (1.0 / WS_TAU));
    const float now = prev + (target - prev) * follow;
    state.s[cw + 2u] = floatBitsToUint(now);
    state.s[cw + 3u] = frame;
    const uint at = WS_BLOCK_WORD;
    region.w[at + WS_HEADER_WORDS + id.y * WS_N + id.x] = floatBitsToUint(now);
    if (id.x == 0u && id.y == 0u) {
        region.w[at + 1u] = floatBitsToUint(float(origin.x) * WS_CELL);
        region.w[at + 2u] = floatBitsToUint(float(origin.y) * WS_CELL);
        region.w[at + 3u] = floatBitsToUint(1.0 / WS_CELL);
        region.w[at + 4u] = floatBitsToUint(float(WS_N));
        region.w[at + 5u] = floatBitsToUint(row1.w);
        region.w[at + 6u] = floatBitsToUint(wind.w);
        region.w[at + 7u] = floatBitsToUint(WS_BAND);
        region.w[at] = floatBitsToUint(1.0);
    }
    atomicAdd(counters.c[WS_C_CELLS], 1u);
    atomicAdd(counters.c[WS_C_CELLS_SUM], uint(now * 1000.0 + 0.5));
    if (now > 0.5) {
        atomicAdd(counters.c[WS_C_CELLS_SHELTERED], 1u);
    }
}

#ifdef SHOW
vec3 ramp(float v) {
    const vec3 open_ = vec3(0.1, 0.8, 0.2);
    const vec3 half_ = vec3(1.0, 0.9, 0.1);
    const vec3 shut = vec3(1.0, 0.1, 0.1);
    return v < 0.5 ? mix(open_, half_, v * 2.0) : mix(half_, shut, (v - 0.5) * 2.0);
}

void show() {
    const ivec2 px = ivec2(gl_GlobalInvocationID.xy);
    const ivec2 size = ivec2(size_jitter.xy);
    if (any(greaterThanEqual(px, size))) {
        return;
    }
    const float depth = texelFetch(depth_tex, px, 0).r;
    const vec4 scene = imageLoad(scene_img, px);
    if (!(depth > 0.0 && depth < 1.0)) {
        if (cells.z != 0) {
            imageStore(scene_img, px, vec4(0.0, 0.0, 0.0, scene.a));
        }
        return;
    }
    const vec3 p = world_of(vec2(px) + 0.5, depth);
    const vec2 off = p.xz - vec2(row0.w, row2.w);
    const float v = wind_shelter_at(region, p);
    const bool inside = all(lessThan(abs(off), vec2(float(N / 2 - 2) * WS_CELL)));
    if (cells.z != 0) {
        imageStore(scene_img, px, vec4(inside ? ramp(v) * 1.5 : vec3(0.2), scene.a));
    } else if (inside) {
        imageStore(scene_img, px, vec4(mix(scene.rgb, ramp(v) * 1.5, 0.55), scene.a));
    }
}
#endif

void main() {
    switch (mode) {
    case WS_MODE_CLEAR:
        clear_all();
        break;
    case WS_MODE_SPLAT:
        splat();
        break;
    case WS_MODE_MERGE:
        merge();
        break;
    case WS_MODE_RAW:
        raw_pass();
        break;
    case WS_MODE_FINAL:
        final_pass();
        break;
#ifdef SHOW
    case WS_MODE_SHOW:
        show();
        break;
#endif
    default:
        break;
    }
}
''',
VH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r117_wind-shelter): the wind shelter field's GPU passes (bbport_wind_shelter.h says what
// the field is and who reads it; host_shaders/wind_shelter.comp what the passes do). FEATURE, off
// unless BB_WIND=1 and BB_WIND_SHELTER is above 0 (and the plant sway's region exists). Off, the
// rasterizer makes no WindShelter (Wanted), so there is no pipeline, no buffer and no pass, and
// each of its two hooks is one null pointer test.
//
// The passes run right before the upscaler's trigger (Rasterizer::EffectsBeforeUpscaler, after the
// heat haze), when the scene depth is complete: five small dispatches (the depth's splat at one
// pixel in four, the merge into the cache, the rays, the blur and the field's write into the sway
// region's buffer), and with BB_WIND_SHELTER_SHOW the test view. Without the upscaler (BB_UPSCALER=
// none or a GPU it cannot run on) that place is never reached and nothing is drawn (said once).
#pragma once

#include <array>
#include <chrono>

#include "bbport_wind.h"
#include "bbport_wind_shelter.h"
#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include <vk_mem_alloc.h> // after vk_common.h (its configuration)
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

class WindShelter {
public:
    /// BB_WIND=1 with BB_WIND_SHELTER above 0 and the plant sway on (read once).
    [[nodiscard]] static bool Wanted();
    WindShelter(const Instance& instance, Scheduler& scheduler,
                VideoCore::TextureCache& texture_cache, Runtime& runtime,
                SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~WindShelter();
    WindShelter(const WindShelter&) = delete;
    WindShelter& operator=(const WindShelter&) = delete;

    /// The place before the upscaler is never reached: said once.
    void NoSceneHooks();
    /// Right before the upscaler's trigger: this frame's passes. `region`: the device address of the
    /// sway region's first word (ObjectMotion::AddressTable().params + ParamsCapacity * 32; 0: none,
    /// nothing is made), `wind` the shared wind as last advanced.
    void Apply(VideoCore::ImageId color, VideoCore::ImageId depth, std::array<float, 2> jitter,
               u64 region, const BbWind::Snapshot& wind);
    /// The share of the wind that stays at the camera (BbWindShelter::Open of the field there, as
    /// the GPU wrote it a frame or two ago): 1 before any pass has run.
    [[nodiscard]] float CameraOpen() const;

private:
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    vk::ImageView CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect);
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    void Report();

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    BbWindShelter::Knob knobs;
    vk::UniqueDescriptorSetLayout set_layout, show_set_layout;
    vk::UniquePipelineLayout layout, show_layout;
    vk::UniquePipeline pipeline, show_pipeline;
    bool made = false;
    bool show_made = false;
    Buffer state_buffer, counter_buffer, counter_host;
    std::array<ViewEntry, 4> view_cache{};
    u64 view_uses = 0;
    u32 frame = 0;                ///< the passes run so far (the push's frame, never 0 once run)
    bool zeroed = false;          ///< the state and counters were cleared (the first pass)
    std::chrono::steady_clock::time_point last_pass{};
    std::array<u32, WS_COUNTER_WORDS> counters_seen{}; ///< as the last line read them

    struct Stats {
        u32 frames = 0;     ///< frames that reached the place before the upscaler
        u32 passes = 0;     ///< of them with the passes recorded
        u32 no_region = 0;  ///< frames without the sway region or with the wind off
        u32 no_camera = 0;  ///< frames without a camera, or a menu's preview
        u32 no_scene = 0;   ///< frames whose scene could not be read or was too small
    } stats;
    bool reported = false;
    bool told_size = false;
};

} // namespace Vulkan
''',
VC: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r117_wind-shelter): the wind shelter field's GPU passes (vk_wind_shelter.h; the numbers in
// bbport_wind_shelter.h, the passes in host_shaders/wind_shelter.comp). The structure of
// vk_heat_haze.cpp: one effect pass pipeline (two builds of one shader), push descriptors, a crumb
// recorded at the place before the upscaler, a host copy of the counters for the log.

#include "video_core/renderer_vulkan/vk_wind_shelter.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <utility>

#include "bbport_toggles.h"
#include "video_core/host_shaders/wind_shelter_comp.h"
#include "video_core/host_shaders/wind_shelter_show_comp.h"
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
constexpr u32 LineFrames = 600;
constexpr u32 FirstLineFrames = 120; ///< the first line comes sooner, for short test runs
constexpr u64 ProfileRow = 117;      ///< EffectPass::Mark: the row "Lighting: wind shelter"
constexpr float MaxStep = 0.1f;      ///< s: the longest dt a pass is given

vk::WriteDescriptorSet BufferWrite(u32 binding, const vk::DescriptorBufferInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1,
            .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = info};
}

vk::WriteDescriptorSet ImageWrite(u32 binding, vk::DescriptorType type,
                                  const vk::DescriptorImageInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type,
            .pImageInfo = info};
}
} // namespace

bool WindShelter::Wanted() {
    return BbWindShelter::KnobOnce().on;
}

WindShelter::WindShelter(const Instance& instance_, Scheduler& scheduler_,
                         VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                         SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_},
      knobs{BbWindShelter::KnobOnce()} {
    using enum vk::DescriptorType;
    made = EffectPass::Create(instance, set_layout, layout, pipeline,
                              {eSampledImage, eStorageBuffer, eStorageBuffer},
                              sizeof(BbWindShelter::Push), WIND_SHELTER_COMP, "Wind shelter") &&
           MakeBuffer(state_buffer,
                      vk::DeviceSize(WS_M) * WS_M * (WS_CELL_WORDS + WS_FRESH_WORDS) * 4, false,
                      vk::BufferUsageFlagBits::eStorageBuffer |
                          vk::BufferUsageFlagBits::eTransferDst) &&
           MakeBuffer(counter_buffer, WS_COUNTER_WORDS * 4, false,
                      vk::BufferUsageFlagBits::eStorageBuffer |
                          vk::BufferUsageFlagBits::eTransferSrc |
                          vk::BufferUsageFlagBits::eTransferDst) &&
           MakeBuffer(counter_host, WS_COUNTER_WORDS * 4, true,
                      vk::BufferUsageFlagBits::eTransferDst);
    if (made) {
        std::memset(counter_host.mapped, 0, WS_COUNTER_WORDS * 4);
    }
    show_made = made && knobs.show != 0 &&
                EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
                EffectPass::Create(instance, show_set_layout, show_layout, show_pipeline,
                                   {eSampledImage, eStorageBuffer, eStorageBuffer, eStorageImage},
                                   sizeof(BbWindShelter::Push), WIND_SHELTER_SHOW_COMP,
                                   "Wind shelter view");
    BbReport::Printf("Wind shelter (r117, BB_WIND_SHELTER=%.2f): %s; a field of %ux%u cells of %.0f "
                     "m around the camera from the scene depth (no ray tracing), %u upwind rays "
                     "of %u m with a median, roofs; read per vertex by the plants, at the camera "
                     "by the fog drift and the particles; drawn right before the upscaler; test "
                     "view %s\n",
                     double(knobs.strength), made ? "on" : "off - the passes could not be made",
                     BbWindShelter::N, BbWindShelter::N, double(BbWindShelter::Cell), 3u,
                     BbWindShelter::Steps,
                     knobs.show == 0 ? "off"
                     : show_made     ? (knobs.show == 2 ? "on (alone on black)" : "on (over the scene)")
                                     : "requested but not made");
}

WindShelter::~WindShelter() {
    FreeBuffer(state_buffer);
    FreeBuffer(counter_buffer);
    FreeBuffer(counter_host);
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
}

bool WindShelter::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host,
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

void WindShelter::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

void WindShelter::NoSceneHooks() {
    BbReport::Printf("Wind shelter (r117): not drawn - the upscaler is not available "
                     "(BB_UPSCALER=none, or this GPU cannot run it), and the field is made right "
                     "before it: nothing reads a field, the wind is as it was\n");
}

float WindShelter::CameraOpen() const {
    if (!made || !counter_host.mapped || frame == 0) {
        return 1.0f;
    }
    std::uint32_t word = 0;
    std::memcpy(&word, static_cast<const u8*>(counter_host.mapped) + WS_C_CAMERA * 4, 4);
    return BbWindShelter::Open(BbWindShelter::CameraShelter(word));
}

vk::ImageView WindShelter::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {
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
        .view = Check<"create wind shelter view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

void WindShelter::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                        std::array<float, 2> jitter, u64 region, const BbWind::Snapshot& wind) {
    ++stats.frames;
    const auto done = [&] {
        if (stats.frames >= (reported ? LineFrames : FirstLineFrames)) {
            reported = true;
            Report();
        }
    };
    if (!made || region == 0 || !wind.on || !color_id || !depth_id) {
        ++stats.no_region;
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
    // The scene's size is the reduced one while a preset renders below the game's own size, else
    // the game's render size (its targets may be allocated larger): as the heat haze takes it.
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    if (width < 16 || height < 16 ||
        (show_made && color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat)) {
        ++stats.no_scene;
        done();
        return;
    }
    const bool show = show_made;
    const SceneUseScope scene_use{"wind shelter"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{};
    if (reduced) {
        VideoCore::ImageViewInfo color_info, depth_info;
        color_info.format = color.info.pixel_format;
        depth_info.format = depth.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, color_info, Compute, ReadWrite);
        if (show && !(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            done();
            return;
        }
        color_view = proxy.view;
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
    } else {
        if (show && !(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            done();
            return;
        }
        if (show) {
            color_view = CachedView(color, vk::ImageAspectFlagBits::eColor);
            runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        }
        depth_view = CachedView(depth, vk::ImageAspectFlagBits::eDepth);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();

    const auto now = std::chrono::steady_clock::now();
    const float dt = last_pass == std::chrono::steady_clock::time_point{}
                         ? 0.0f
                         : std::min(std::chrono::duration<float>(now - last_pass).count(), MaxStep);
    last_pass = now;
    ++frame;
    const auto& iv = camera.inv_view;
    BbWindShelter::Push push{};
    push.region = region;
    push.frame = frame;
    push.row0 = {iv[0], iv[1], iv[2], iv[3]};
    push.row1 = {iv[4], iv[5], iv[6], iv[7]};
    push.row2 = {iv[8], iv[9], iv[10], iv[11]};
    push.proj = camera.proj;
    push.size_jitter = {float(width), float(height), jitter[0], jitter[1]};
    push.wind = {wind.dir_x, wind.dir_z, dt, knobs.strength};
    push.cells = {s32(std::floor(iv[3] / BbWindShelter::Cell)),
                  s32(std::floor(iv[11] / BbWindShelter::Cell)), knobs.show == 2 ? 1 : 0, 0};
    const bool first = !std::exchange(zeroed, true);
    ++stats.passes;
    if (!told_size) {
        told_size = true;
        BbReport::Printf("Wind shelter (r117): first pass at a scene of %ux%u (%s), %ux%u depth "
                         "samples a frame\n",
                         width, height, reduced ? "reduced scene" : "the game's scene",
                         (width + WS_STRIDE - 1) / WS_STRIDE, (height + WS_STRIDE - 1) / WS_STRIDE);
    }
    EffectPass::Mark(ProfileRow, "wind shelter");
    scheduler.RecordCrumb(
        {.name = "wind shelter"},
        [push, width, height, first, show, depth_view, color_view,
         state = state_buffer.buffer, counters = counter_buffer.buffer,
         host = counter_host.buffer, pass_pipeline = *pipeline, pass_layout = *layout,
         view_pipeline = show ? *show_pipeline : vk::Pipeline{},
         view_layout = show ? *show_layout : vk::PipelineLayout{}](vk::CommandBuffer cmdbuf) {
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute, ReadWrite);
            if (first) {
                cmdbuf.fillBuffer(state, 0, VK_WHOLE_SIZE, 0);
                cmdbuf.fillBuffer(counters, 0, VK_WHOLE_SIZE, 0);
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                          vk::AccessFlagBits2::eTransferWrite, Compute,
                                          ReadWrite);
            }
            const vk::DescriptorImageInfo depth_info{
                {}, depth_view, vk::ImageLayout::eGeneral};
            const vk::DescriptorBufferInfo state_info{state, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo counter_info{counters, 0, VK_WHOLE_SIZE};
            const vk::DescriptorImageInfo color_info{{}, color_view, vk::ImageLayout::eGeneral};
            const auto run = [&](vk::PipelineLayout run_layout, u32 mode, u32 gx, u32 gy) {
                BbWindShelter::Push p = push;
                p.mode = mode;
                cmdbuf.pushConstants(run_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(p),
                                     &p);
                cmdbuf.dispatch(gx, gy, 1);
            };
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            const std::array writes{
                ImageWrite(0, vk::DescriptorType::eSampledImage, &depth_info),
                BufferWrite(1, &state_info), BufferWrite(2, &counter_info)};
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            const u32 group = WS_GROUP;
            const u32 cache_groups = WS_M / group, window_groups = WS_N / group;
            const u32 splat_x = ((width + WS_STRIDE - 1) / WS_STRIDE + group - 1) / group;
            const u32 splat_y = ((height + WS_STRIDE - 1) / WS_STRIDE + group - 1) / group;
            if (first) {
                run(pass_layout, WS_MODE_CLEAR, cache_groups, cache_groups);
                EffectPass::ComputeBarrier(cmdbuf);
            }
            run(pass_layout, WS_MODE_SPLAT, splat_x, splat_y);
            EffectPass::ComputeBarrier(cmdbuf);
            run(pass_layout, WS_MODE_MERGE, cache_groups, cache_groups);
            EffectPass::ComputeBarrier(cmdbuf);
            run(pass_layout, WS_MODE_RAW, window_groups, window_groups);
            EffectPass::ComputeBarrier(cmdbuf);
            run(pass_layout, WS_MODE_FINAL, window_groups, window_groups);
            if (show) {
                EffectPass::ComputeBarrier(cmdbuf);
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, view_pipeline);
                const std::array view_writes{
                    ImageWrite(0, vk::DescriptorType::eSampledImage, &depth_info),
                    BufferWrite(1, &state_info), BufferWrite(2, &counter_info),
                    ImageWrite(3, vk::DescriptorType::eStorageImage, &color_info)};
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, view_layout, 0,
                                            view_writes);
                run(view_layout, WS_MODE_SHOW, (width + group - 1) / group,
                    (height + group - 1) / group);
            }
            // The field (host visible memory the vertex shaders read) and the scene are final.
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands, MemoryAll);
            cmdbuf.copyBuffer(counters, host, vk::BufferCopy{0, 0, WS_COUNTER_WORDS * 4});
            EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                      vk::AccessFlagBits2::eTransferWrite,
                                      vk::PipelineStageFlagBits2::eHost,
                                      vk::AccessFlagBits2::eHostRead);
        });
    done();
}

void WindShelter::Report() {
    std::array<u32, WS_COUNTER_WORDS> now{};
    if (counter_host.mapped) {
        std::memcpy(now.data(), counter_host.mapped, sizeof(now));
    }
    const auto c = BbWindShelter::CountsBetween(now.data(), counters_seen.data());
    counters_seen = now;
    const auto ull = [](u64 v) { return static_cast<unsigned long long>(v); };
    const double cells = std::max(1.0, double(c.cells));
    // Two lines, each under 300 characters (the slot runs keep that much of a line).
    BbReport::Printf("Wind shelter (r117): %u frames before the upscaler, %u passes; the view: "
                     "%.1f%% of %llu depth samples sheltered (field above 0.5), %.1f%% indoors "
                     "(above 0.95), mean %.3f; at the camera %.2f\n",
                     stats.frames, stats.passes, 100.0 * BbWindShelter::ViewSheltered(c),
                     ull(c.pixels), 100.0 * BbWindShelter::ViewIndoor(c),
                     BbWindShelter::ViewMean(c), double(1.0f - CameraOpen()));
    BbReport::Printf("Wind shelter (r117): the window: %.0f of %llu cells with depth data a frame "
                     "(%.1f%%), %.1f%% of the cells sheltered, mean %.3f; %.0f cache cells "
                     "updated a frame; skipped %u without the region or wind, %u without a "
                     "camera, %u without a usable scene\n",
                     double(c.cells_seen) / std::max(1.0, double(stats.passes)), ull(c.cells),
                     100.0 * double(c.cells_seen) / cells, 100.0 * double(c.cells_sheltered) / cells,
                     double(c.cells_sum) / 1000.0 / cells,
                     double(c.merged) / std::max(1.0, double(stats.passes)), stats.no_region,
                     stats.no_camera, stats.no_scene);
    stats = {};
}

} // namespace Vulkan
''',
NT: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r117_wind-shelter): the wind shelter field's knob, layout, reader and model
// (gpu/shim/bbport_wind_shelter.h). The model's numbers were first worked out in a Python copy
// (scratch r117_src/twin.py); the GLSL copy (host_shaders/wind_shelter.comp, wind_shelter.glsl) and
// the two shader emitters are checked by compiling them (glslangValidator, spirv-val) and in the
// game, not here.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <vector>

#include "gpu/shim/bbport_wind_shelter.h"

using namespace BbWindShelter;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

bool Near(float a, float b, float tolerance) {
    return std::fabs(a - b) <= tolerance;
}

// A grid of columns: a lambda gives (bot, top) or "unknown".
Column Flat(int, int) {
    return ColumnOf(0.0f, 0.0f);
}
Column Wall(int x, int z) { // a wall 3 m high along z at x = 10, 40 m long
    return x == 10 && z >= -20 && z <= 20 ? ColumnOf(0.0f, 3.0f) : ColumnOf(0.0f, 0.0f);
}
Column Post(int x, int z) { // one cell, 3 m high
    return x == 10 && z == 0 ? ColumnOf(0.0f, 3.0f) : ColumnOf(0.0f, 0.0f);
}
Column Tomb(int x, int z) { // 5 cells wide, 2 m high
    return x == 10 && z >= -2 && z <= 2 ? ColumnOf(0.0f, 2.0f) : ColumnOf(0.0f, 0.0f);
}
Column Deck(int x, int) { // a deck 5 m up, 1 m thick, along z
    return x == 10 ? ColumnOf(5.0f, 6.0f) : ColumnOf(0.0f, 0.0f);
}
Column Room(int x, int z) { // a hall 21 x 21 cells, ceiling 3 m
    return x >= -10 && x <= 10 && z >= -10 && z <= 10 ? ColumnOf(0.0f, 3.0f) : Column{};
}
Column Pavilion(int x, int z) { // one roofed cell in flat ground
    return x == 0 && z == 0 ? ColumnOf(0.0f, 3.0f) : ColumnOf(0.0f, 0.0f);
}
Column Nothing(int, int) {
    return Column{};
}

void TestKnob() {
    Knob k = ParseKnob("1", "1", nullptr, true);
    Expect(k.wind && k.asked && k.on && k.strength == 1.0f && k.show == 0, "1 / 1 is on at full strength");
    k = ParseKnob("1", "0.5", "1", true);
    Expect(k.on && Near(k.strength, 0.5f, 1e-6f) && k.show == 1, "0.5 is half strength; show 1");
    k = ParseKnob("1", "7", "2", true);
    Expect(k.on && k.strength == 1.0f && k.show == 2, "above 1 holds at 1; show 2");
    k = ParseKnob("1", nullptr, nullptr, true);
    Expect(!k.asked && !k.on && k.strength == 0.0f, "unset is off");
    k = ParseKnob("1", "0", nullptr, true);
    Expect(!k.asked && !k.on, "0 is off");
    k = ParseKnob("0", "1", nullptr, true);
    Expect(k.asked && !k.wind && !k.on, "without BB_WIND=1 it is off");
    k = ParseKnob(nullptr, "1", nullptr, true);
    Expect(!k.on, "BB_WIND unset: off");
    k = ParseKnob("1", "1", nullptr, false);
    Expect(k.asked && !k.on, "without the plant sway's region it is off");
    k = ParseKnob("1", "abc", nullptr, true);
    Expect(k.unreadable && !k.on, "unreadable text is off and says so");
    k = ParseKnob("1", "nan", nullptr, true);
    Expect(!k.on, "a non-number is off");
    k = ParseKnob("1", "-1", nullptr, true);
    Expect(!k.on && k.strength == 0.0f, "negative is off");
    k = ParseKnob("1", "1", "11", true);
    Expect(k.show == 0, "show takes exactly 1 or 2");
    k = ParseKnob("1", "1", "", true);
    Expect(k.show == 0, "empty show is off");
}

void TestLayout() {
    static_assert(BlockWord >= BbWindSway::RegionWords);
    static_assert(BlockWords == 8 + 64 * 64 && BlockBytes == 16416);
    static_assert(sizeof(Push) == 128);
    Expect(BlockWord == 4096 && N == 64 && M == 128 && Steps == 28, "the layout's numbers");
    Expect(Cell == 1.0f && Band == 14.0f && BandSoft == 4.0f, "the band's numbers");
    // the region ends where the field's block begins, at 16 KB in the buffer
    Expect(BlockWord * 4 + BlockBytes == 32800, "the buffer grows to 32800 bytes with the field");
}

void TestReader() {
    std::vector<float> block(BlockWords, 0.0f);
    WriteHeader(block.data(), -32, -32, 1.7f, 1.0f);
    const auto cell = [&](std::uint32_t i, std::uint32_t j) -> float& {
        return block[HeaderWords + j * N + i];
    };
    cell(10, 20) = 0.8f;
    // the middle of cell (10, 20): world x -21.5, z -11.5
    Expect(At(block.data(), -21.5f, 1.7f, -11.5f) == 0.8f, "a cell's middle gives its value");
    Expect(Near(At(block.data(), -21.0f, 1.7f, -11.5f), 0.4f, 1e-6f),
           "half way to the next cell it is half (bilinear in x)");
    Expect(Near(At(block.data(), -21.5f, 1.7f, -11.0f), 0.4f, 1e-6f), "and in z");
    Expect(Near(At(block.data(), -21.0f, 1.7f, -11.0f), 0.2f, 1e-6f), "a quarter at a corner of four");
    Expect(At(block.data(), -11.5f, 1.7f, -21.5f) == 0.0f, "another cell is 0");
    // outside the field
    Expect(At(block.data(), -32.4f, 1.7f, 0.0f) == 0.0f, "west of the first cell's middle: outside");
    Expect(At(block.data(), -32.0f + 63.6f, 1.7f, 0.0f) == 0.0f, "past the last cell pair: outside");
    Expect(At(block.data(), 0.0f, 1.7f, -32.4f) == 0.0f, "north of it: outside");
    // the marker
    std::vector<float> unwritten = block;
    unwritten[0] = 0.0f;
    Expect(At(unwritten.data(), -21.5f, 1.7f, -11.5f) == 0.0f, "marker 0: nothing is read");
    unwritten[0] = 0.5f;
    Expect(At(unwritten.data(), -21.5f, 1.7f, -11.5f) == 0.0f, "marker not above 0.5: nothing");
    // the vertical band
    Expect(Near(At(block.data(), -21.5f, 1.7f + 10.0f, -11.5f), 0.8f, 1e-5f), "10 m above the camera: full");
    Expect(Near(At(block.data(), -21.5f, 1.7f + 12.0f, -11.5f), 0.4f, 1e-5f), "12 m: half");
    Expect(At(block.data(), -21.5f, 1.7f + 14.0f, -11.5f) < 1e-5f, "14 m: none");
    Expect(Near(At(block.data(), -21.5f, 1.7f - 12.0f, -11.5f), 0.4f, 1e-5f), "12 m below: half");
    // the strength
    WriteHeader(block.data(), -32, -32, 1.7f, 0.5f);
    Expect(Near(At(block.data(), -21.5f, 1.7f, -11.5f), 0.4f, 1e-6f), "strength 0.5 halves it");
    Expect(Near(Factor(block.data(), -21.5f, 1.7f, -11.5f), 0.6f, 1e-6f), "the factor is 1 - At");
    // indoors: field 1 gives a factor of exactly 0 (nothing moves)
    WriteHeader(block.data(), -32, -32, 1.7f, 1.0f);
    cell(10, 20) = 1.0f;
    Expect(Factor(block.data(), -21.5f, 1.7f, -11.5f) == 0.0f, "field 1, strength 1: the factor is 0");
    Expect(Factor(block.data(), 0.0f, 1.7f, 0.0f) == 1.0f, "in the open the factor is 1");
}

// The same world function in two windows (the camera moved by (2, 4) cells): the same value at the
// same world point, whichever window answers.
void TestStable() {
    const auto world_value = [](int wx, int wz) {
        return float(((wx * 7 + wz * 3) % 10 + 10) % 10) / 10.0f;
    };
    std::vector<float> a(BlockWords, 0.0f), b(BlockWords, 0.0f);
    WriteHeader(a.data(), -32, -32, 1.7f, 1.0f);
    WriteHeader(b.data(), -30, -28, 1.7f, 1.0f);
    for (std::uint32_t j = 0; j < N; ++j) {
        for (std::uint32_t i = 0; i < N; ++i) {
            a[HeaderWords + j * N + i] = world_value(-32 + int(i), -32 + int(j));
            b[HeaderWords + j * N + i] = world_value(-30 + int(i), -28 + int(j));
        }
    }
    int compared = 0;
    for (float x = -20.0f; x < 20.0f; x += 1.37f) {
        for (float z = -20.0f; z < 20.0f; z += 1.91f) {
            const float va = At(a.data(), x, 1.7f, z), vb = At(b.data(), x, 1.7f, z);
            Expect(Near(va, vb, 1e-5f), "a world point has one value in either window");
            ++compared;
        }
    }
    Expect(compared > 400, "many points compared");
}

void TestModel() {
    // flat ground, wind toward +x
    Expect(Raw(Flat, 5, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "flat ground: no shelter");
    Expect(Raw(Nothing, 5, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "nothing known: no shelter");
    // a wall 3 m high at x = 10
    for (int x : {11, 12, 14}) {
        Expect(Near(Raw(Wall, x, 0, 1.0f, 0.0f, 1.7f), 1.0f, 1e-6f), "close behind a wall: 1");
    }
    Expect(Near(Raw(Wall, 16, 0, 1.0f, 0.0f, 1.7f), 0.857f, 0.01f), "6 m behind a 3 m wall: 0.86");
    Expect(Near(Raw(Wall, 20, 0, 1.0f, 0.0f, 1.7f), 0.198f, 0.01f), "10 m behind it: 0.2");
    Expect(Raw(Wall, 26, 0, 1.0f, 0.0f, 1.7f) < 0.01f, "16 m behind it: about 0");
    Expect(Raw(Wall, 30, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "20 m behind it: 0");
    Expect(Raw(Wall, 5, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "in front of the wall (upwind): 0");
    Expect(Raw(Wall, 12, 0, 0.0f, 1.0f, 1.7f) == 0.0f, "wind along the wall: the wall's end is far");
    Expect(Raw(Wall, 12, 0, -1.0f, 0.0f, 1.7f) == 0.0f, "wind from the other side: the cell is upwind");
    Expect(Raw(Wall, 7, 0, -1.0f, 0.0f, 1.7f) > 0.99f, "wind toward -x: the cell at 7 is behind it");
    const float r = std::sqrt(0.5f);
    Expect(Raw(Wall, 13, 0, r, r, 1.7f) > 0.99f, "a diagonal wind: behind the wall too");
    // a thin obstacle (one cell) shelters only just behind it (the median of the three rays)
    Expect(Raw(Post, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "right behind a post: 1");
    Expect(Raw(Post, 13, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "3 m behind a post: 0 (the air goes round)");
    Expect(Raw(Post, 16, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "6 m behind a post: 0");
    // a 2 m tomb, 5 cells wide
    Expect(Raw(Tomb, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "right behind a tomb: 1");
    Expect(Near(Raw(Tomb, 13, 0, 1.0f, 0.0f, 1.7f), 0.857f, 0.01f), "3 m behind it: 0.86");
    Expect(Raw(Tomb, 18, 0, 1.0f, 0.0f, 1.7f) < 0.01f, "8 m behind it: about 0");
    // a deck 5 m up does not block the wind at the ground
    Expect(Raw(Deck, 14, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "under a bridge: the wind passes");
    // indoors: a hall, in the middle and at its edge
    Expect(Near(Raw(Room, 0, 0, 1.0f, 0.0f, 1.7f), 1.0f, 1e-6f), "in a hall: 1");
    Expect(Near(Raw(Room, 9, 0, 1.0f, 0.0f, 1.7f), 1.0f, 1e-6f), "at its downwind edge: 1");
    // a roofed cell with open sides: only the roof's half
    const float pavilion = Raw(Pavilion, 0, 0, 1.0f, 0.0f, 1.7f);
    Expect(pavilion > 0.4f && pavilion < 0.5f, "an open pavilion: about 0.46");
    // the ground of a cell nothing is known about is the neighbours' lowest
    const auto step_up = [](int x, int z) {
        return x == 10 && z >= -3 && z <= 3 ? ColumnOf(0.0f, 3.0f)
               : x == 11 && z == 0         ? Column{}
                                           : ColumnOf(0.0f, 0.0f);
    };
    Expect(Raw(step_up, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "an unknown cell takes its neighbours' ground");
}

void TestSteps() {
    Expect(Median3(0.1f, 0.5f, 0.9f) == 0.5f && Median3(0.9f, 0.1f, 0.5f) == 0.5f &&
               Median3(0.5f, 0.9f, 0.1f) == 0.5f && Median3(0.3f, 0.3f, 0.9f) == 0.3f,
           "the median of three");
    const auto r = Rotated(1.0f, 0.0f, 90.0f);
    Expect(Near(r[0], 0.0f, 1e-6f) && Near(r[1], 1.0f, 1e-6f), "a quarter turn");
    Expect(Near(Unquant(Quant(1.7f)), 1.6875f, 1e-6f), "heights keep 1/32 m");
    Expect(Quant(-2000.0f) == 0 && Quant(5000.0f) == 65535, "heights are clamped");
    Expect(Near(Unquant(Quant(-3.1f)), -3.1f, 1.0f / 63.0f), "the round trip is within 1/64 m");
    Expect(Unquant(Quant(3.0f)) == 3.0f, "3 m is exact");
    // the window's edge and the target
    Expect(EdgeFade(0, 30) == 0.0f && EdgeFade(30, 0) == 0.0f && EdgeFade(63, 30) == 0.0f &&
               EdgeFade(30, 63) == 0.0f,
           "0 at the window's border");
    Expect(EdgeFade(32, 32) == 1.0f && EdgeFade(4, 40) == 1.0f && EdgeFade(59, 40) == 1.0f,
           "1 from 4 cells in");
    Expect(Near(EdgeFade(1, 32), 0.15625f, 1e-6f) && EdgeFade(1, 32) == EdgeFade(62, 32),
           "the fade is symmetric");
    Expect(Target(1.0f, 32, 32) == 1.0f && Target(0.95f, 32, 32) == 1.0f,
           "indoors reaches exactly 1 (the gain)");
    Expect(Near(Target(0.5f, 32, 32), 0.53f, 1e-6f) && Target(0.5f, 0, 5) == 0.0f, "gain and edge");
    // the time filter: a second brings it most of the way, never past, never jumping
    Expect(Follow(0.0f, 1.0f, 0.0f) == 0.0f && Follow(0.3f, 0.3f, 0.1f) == 0.3f, "no step, no change");
    Expect(Near(Follow(0.0f, 1.0f, 0.5f), 0.632f, 0.001f), "a time constant of 0.5 s");
    Expect(Follow(0.0f, 1.0f, 1.0f) > 0.86f && Follow(0.0f, 1.0f, 1.0f) < 0.87f,
           "a second: 86 percent of the way");
    float v = 0.0f;
    float biggest_step = 0.0f;
    for (int i = 0; i < 60; ++i) { // 60 frames of 1/60 s toward 1: a smooth rise
        const float next = Follow(v, 1.0f, 1.0f / 60.0f);
        biggest_step = std::max(biggest_step, next - v);
        v = next;
    }
    Expect(v > 0.85f && v < 0.88f && biggest_step < 0.04f, "frame by frame it rises smoothly: a second of frames gives 86 percent");
    // the consumers' scalars
    Expect(Near(Open(0.3f), 0.7f, 1e-6f) && Open(0.0f) == 1.0f && Open(1.0f) == 0.0f && Open(2.0f) == 0.0f &&
               Open(-1.0f) == 1.0f,
           "Open is the share that stays, held to 0-1");
    Expect(Open(std::numeric_limits<float>::quiet_NaN()) == 1.0f &&
               Open(std::numeric_limits<float>::infinity()) == 1.0f,
           "not a number: no shelter");
    const auto bits = [](float f) {
        std::uint32_t w = 0;
        std::memcpy(&w, &f, 4);
        return w;
    };
    Expect(CameraShelter(bits(0.25f)) == 0.25f && CameraShelter(bits(2.0f)) == 1.0f &&
               CameraShelter(bits(-1.0f)) == 0.0f &&
               CameraShelter(bits(std::numeric_limits<float>::quiet_NaN())) == 0.0f,
           "the camera's counter word");
}

void TestCounts() {
    std::array<std::uint32_t, WS_COUNTER_WORDS> before{}, now{};
    now[WS_C_PIXELS] = 1000;
    now[WS_C_PIXELS_SHELTERED] = 250;
    now[WS_C_PIXELS_INDOOR] = 100;
    now[WS_C_PIXELS_SUM] = 300000; // 1/1000: mean 0.3
    now[WS_C_CELLS] = 4096;
    now[WS_C_CELLS_SEEN] = 1024;
    now[WS_C_CELLS_SHELTERED] = 512;
    now[WS_C_CELLS_SUM] = 2048000;
    now[WS_C_MERGED] = 77;
    Counts c = CountsBetween(now.data(), before.data());
    Expect(c.pixels == 1000 && c.sheltered == 250 && c.indoor == 100 && c.sum == 300000 &&
               c.cells == 4096 && c.cells_seen == 1024 && c.cells_sheltered == 512 &&
               c.cells_sum == 2048000 && c.merged == 77,
           "the counts, word by word");
    Expect(Near(float(ViewSheltered(c)), 0.25f, 1e-6f) && Near(float(ViewIndoor(c)), 0.1f, 1e-6f) &&
               Near(float(ViewMean(c)), 0.3f, 1e-6f),
           "the view's shares and mean");
    before[WS_C_PIXELS] = 0xfffffffeu; // the 32-bit totals wrap
    now[WS_C_PIXELS] = 5;
    c = CountsBetween(now.data(), before.data());
    Expect(c.pixels == 7, "a wrapped total counts the difference");
    const Counts none{};
    Expect(ViewSheltered(none) == 0.0 && ViewIndoor(none) == 0.0 && ViewMean(none) == 0.0,
           "no samples: 0");
}
} // namespace

int main() {
    TestKnob();
    TestLayout();
    TestReader();
    TestStable();
    TestModel();
    TestSteps();
    TestCounts();
    if (failures != 0) {
        std::printf("wind shelter test: %d failures\n", failures);
        return 1;
    }
    std::printf("wind shelter test: ok\n");
    return 0;
}
''',
}

# ("ins", anchor, before, after): the anchor stays whole; `before` goes in front of it, `after`
# behind it. ("rep", old, new): the text old becomes new (new does not hold old).
EMIT_BLOCK = r'''    // bbport (r117_wind-shelter): with BB_WIND_SHELTER on (read once; such sway code has its own
    // shader cache version) the displacement of every sway vertex (a plant, a hanging thing:
    // whichever motion rule ran above) is multiplied by the wind shelter field's factor 1 - At at
    // the vertex's world point: moved = position + (moved - position) (1 - At). BbWindShelter::At
    // is this code in C++, operation for operation (the field: bbport_wind_shelter.h, its words in
    // the sway region at BlockWord; world x and z: the camera's (WindE.z, .w) plus the vertex's
    // offset from it). The loads are indexed inside the field (clamped) and the value is zeroed
    // outside it, before the marker is written and beyond the vertical band. Off: nothing is
    // emitted (the SPIR-V is as before).
    if (BbWindShelter::KnobOnce().on) {
        namespace S = BbWindShelter;
        const Id block = at(region, u64(S::BlockWord) * 4u);
        const auto shelter_word = [&](u64 word) {
            return ctx.OpLoad(f32_type, ctx.OpConvertUToPtr(f32_ptr, at(block, word * 4u)),
                              spv::MemoryAccessMask::Aligned, 4u);
        };
        const auto both = [&](Id a, Id b) { return ctx.OpLogicalAnd(bool_type, a, b); };
        const Id marker = shelter_word(0u);
        const Id inv_cell = shelter_word(3u);
        const Id fx = sub(mul(sub(add(comp(wind_e, 2u), rx), shelter_word(1u)), inv_cell), f(0.5f));
        const Id fz = sub(mul(sub(add(comp(wind_e, 3u), rz), shelter_word(2u)), inv_cell), f(0.5f));
        const Id x0 = ctx.OpFloor(f32_type, fx);
        const Id z0 = ctx.OpFloor(f32_type, fz);
        const Id last = f(float(S::N) - 1.0f);
        const Id inside = both(both(both(ctx.OpFOrdGreaterThan(bool_type, marker, f(0.5f)),
                                         ctx.OpFOrdGreaterThanEqual(bool_type, x0, zero)),
                                    both(ctx.OpFOrdGreaterThanEqual(bool_type, z0, zero),
                                         ctx.OpFOrdLessThan(bool_type, x0, last))),
                               ctx.OpFOrdLessThan(bool_type, z0, last));
        // (review: the index is x0, z0 only inside the field, else 0: a vertex whose position is
        // not finite makes x0 NaN, which FClamp does not clamp everywhere, and a NaN index through
        // the buffer's address would read out of bounds)
        const Id x0c = ctx.OpSelect(f32_type, inside, x0, zero);
        const Id z0c = ctx.OpSelect(f32_type, inside, z0, zero);
        const Id index =
            ctx.OpIAdd(u32_type,
                       ctx.OpIMul(u32_type, ctx.OpConvertFToU(u32_type, z0c), ctx.ConstU32(S::N)),
                       ctx.OpConvertFToU(u32_type, x0c));
        const Id cell = scaled(at(block, u64(S::HeaderWords) * 4u), index, 4u);
        const auto cell_word = [&](u64 bytes) {
            return ctx.OpLoad(f32_type, ctx.OpConvertUToPtr(f32_ptr, at(cell, bytes)),
                              spv::MemoryAccessMask::Aligned, 4u);
        };
        const Id ca = cell_word(0u);
        const Id cb = cell_word(4u);
        const Id cc = cell_word(u64(S::N) * 4u);
        const Id cd = cell_word(u64(S::N) * 4u + 4u);
        const auto lerp = [&](Id a, Id b, Id t) { return add(a, mul(sub(b, a), t)); };
        const Id tx = sub(fx, x0);
        const Id tz = sub(fz, z0);
        const Id value = lerp(lerp(ca, cb, tx), lerp(cc, cd, tx), tz);
        const Id level = ctx.OpFClamp(
            f32_type,
            mul(sub(shelter_word(7u), ctx.OpFAbs(f32_type, sub(wy, shelter_word(5u)))),
                f(1.0f / S::BandSoft)),
            zero, f(1.0f));
        const Id taken =
            ctx.OpSelect(f32_type, inside, mul(mul(value, level), shelter_word(6u)), zero);
        const Id factor = sub(f(1.0f), taken);
        for (u32 r = 0; r < 4; ++r) {
            const Id from = comp(position, r);
            moved[r] = add(from, mul(sub(moved[r], from), factor));
        }
    }
'''

LIFT_BLOCK = r'''    // bbport (r117_wind-shelter): the wind shelter field's factor 1 - At on the displacement, as the
    // recompiler's EmitVertexSway (emit_spirv_special.cpp) and BbWindShelter::At in C++ (see the
    // comment there). Off (BB_WIND_SHELTER unset): nothing is emitted.
    if (BbWindShelter::KnobOnce().on) {
        namespace S = BbWindShelter;
        const u32 block = at(region, u64(S::BlockWord) * 4u);
        const auto shelter_word = [&](u64 word) {
            return Emit(O(spv::Op::OpLoad), t_f32, Ty::F32, {Emit(O(spv::Op::OpConvertUToPtr), ptr_f32, Ty::None, {at(block, word * 4u)}), aligned, 4}, 6);
        };
        const auto both = [&](u32 a, u32 b) { return Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool, {a, b}); };
        const u32 marker = shelter_word(0u);
        const u32 inv_cell = shelter_word(3u);
        const u32 fx = FSub(FMul(FSub(FAdd(comp(wind_e, 2), rx), shelter_word(1u)), inv_cell), CF(0.5f));
        const u32 fz = FSub(FMul(FSub(FAdd(comp(wind_e, 3), rz), shelter_word(2u)), inv_cell), CF(0.5f));
        const u32 x0 = floor_f(fx);
        const u32 z0 = floor_f(fz);
        const u32 last = CF(float(S::N) - 1.0f);
        const u32 inside = both(both(both(FCmp(O(spv::Op::OpFOrdGreaterThan), marker, CF(0.5f)), FCmp(O(spv::Op::OpFOrdGreaterThanEqual), x0, zero)),
                                     both(FCmp(O(spv::Op::OpFOrdGreaterThanEqual), z0, zero), FCmp(O(spv::Op::OpFOrdLessThan), x0, last))),
                                FCmp(O(spv::Op::OpFOrdLessThan), z0, last));
        // (review: the index is x0, z0 only inside the field, else 0: see emit_spirv_special.cpp)
        const u32 x0c = Select(inside, x0, zero);
        const u32 z0c = Select(inside, z0, zero);
        const u32 index = IOp(O(spv::Op::OpIAdd), IOp(O(spv::Op::OpIMul), Emit(O(spv::Op::OpConvertFToU), t_u32, Ty::U32, {z0c}), CU(S::N)),
                              Emit(O(spv::Op::OpConvertFToU), t_u32, Ty::U32, {x0c}));
        const u32 cell = scaled(at(block, u64(S::HeaderWords) * 4u), index, 4);
        const auto cell_word = [&](u64 bytes) {
            return Emit(O(spv::Op::OpLoad), t_f32, Ty::F32, {Emit(O(spv::Op::OpConvertUToPtr), ptr_f32, Ty::None, {at(cell, bytes)}), aligned, 4}, 6);
        };
        const u32 ca = cell_word(0u);
        const u32 cb = cell_word(4u);
        const u32 cc = cell_word(u64(S::N) * 4u);
        const u32 cd = cell_word(u64(S::N) * 4u + 4u);
        const auto lerp = [&](u32 a, u32 b, u32 t) { return FAdd(a, FMul(FSub(b, a), t)); };
        const u32 tx = FSub(fx, x0);
        const u32 tz = FSub(fz, z0);
        const u32 value = lerp(lerp(ca, cb, tx), lerp(cc, cd, tx), tz);
        const u32 level = clamp_f(FMul(FSub(shelter_word(7u), abs_f(FSub(wy, shelter_word(5u)))), CF(1.0f / S::BandSoft)), zero, CF(1.0f));
        const u32 taken = Select(inside, FMul(FMul(value, level), shelter_word(6u)), zero);
        const u32 factor = FSub(CF(1.0f), taken);
        for (u32 r = 0; r < 4; ++r) {
            const u32 from = comp(position, r);
            moved[r] = FAdd(from, FMul(FSub(moved[r], from), factor));
        }
    }
'''

MEMSET_TEXT = r'''        if (BbWindShelter::KnobOnce().on) { // bbport (r117_wind-shelter): the field's block, marker 0
            static_assert(BbWindHang::AllBytes <= BbWindShelter::BlockWord * 4,
                          "the field's block lies behind r112's longer region");
            std::memset(sway_words + BbWindShelter::BlockWord, 0, BbWindShelter::BlockBytes);
        }
'''

CREATE_TEXT = r'''    // bbport (r117_wind-shelter): BB_WIND=1 with BB_WIND_SHELTER above 0 only: the wind shelter
    // field, made right before the upscaler (as the heat haze); without the upscaler that place is
    // never reached (said once).
    if (WindShelter::Wanted()) {
        wind_shelter = std::make_unique<WindShelter>(instance, scheduler, texture_cache, runtime,
                                                     *scene_targets, *camera_motion);
        if (!upscaler->Enabled()) {
            wind_shelter->NoSceneHooks();
        }
    }
'''

HOOK_TEXT = r'''    // bbport (r117_wind-shelter): BB_WIND_SHELTER only: the wind shelter field's passes, after the
    // heat haze, with the sway region's address (0 without the region: nothing is made).
    if (wind_shelter && compute_hash == upscaler->TriggerHash()) {
        wind_shelter->Apply(upscaler->SceneColor(), camera_motion->Depth(), upscaler->Jitter(),
                            object_motion->SwayWords() != nullptr
                                ? object_motion->AddressTable().params +
                                      u64(Shader::MotionVectors::ParamsCapacity) * 32u
                                : 0u,
                            wind.Get());
    }
'''

ADVANCE_NEW = ("    void Advance(Params p, double seconds, float open = 1.0f) {\n")
ADVANCE_OLD = ("    void Advance(Params p, double seconds) {\n")
WIND_OLD = "        snapshot.wind = {u * dir[0], 0.0f, u * dir[1]};\n"
WIND_NEW = ("        // bbport (r117_wind-shelter): `open` (0-1) is the share of the wind that stays where the\n"
            "        // camera is (BbWindShelter::Open); 1 (the default) gives the same floats as before. It\n"
            "        // takes the wind vector (the particles, the heat haze, the caustics) and the offsets\n"
            "        // below (the fog's drift), not the direction, the speed or the gust (the plants).\n"
            "        const float calm = std::isfinite(open) ? std::clamp(open, 0.0f, 1.0f) : 1.0f;\n"
            "        snapshot.wind = {u * dir[0] * calm, 0.0f, u * dir[1] * calm};\n")

EDITS = {
BW: [
    ("rep", ADVANCE_OLD, ADVANCE_NEW),
    ("rep", WIND_OLD, WIND_NEW),
],
EM: [
    ("ins", '#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)\n', "",
     '#include "bbport_wind_shelter.h" // bbport (r117_wind-shelter)\n'),
    ("ins", "    ctx.OpStore(ctx.output_position, ctx.OpCompositeConstruct(ctx.F32[4], moved));\n",
     EMIT_BLOCK, ""),
],
LS: [
    ("ins", '#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)\n', "",
     '#include "bbport_wind_shelter.h" // bbport (r117_wind-shelter)\n'),
    ("ins", "    EmitVoid(O(spv::Op::OpStore), {var_position, ComponentsF({moved[0], moved[1], moved[2], moved[3]})});\n",
     LIFT_BLOCK, ""),
],
PS: [
    ("ins", '#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)\n', "",
     '#include "bbport_wind_shelter.h" // bbport (r117_wind-shelter)\n'),
    ("rep", "                                            : Serialization::SwayShaderBinaryVersion)\n",
     "                                            : Serialization::SwayShaderBinaryVersion) +\n"
     "                     BbWindShelter::BinaryOffset() // (r117_wind-shelter: 1000 with the field's read)\n"),
    ("rep", "        binary_version != Serialization::HangShaderBinaryVersion) { // bbport (r112)\n",
     "        binary_version != Serialization::HangShaderBinaryVersion && // bbport (r112)\n"
     "        binary_version != Serialization::SwayShaderBinaryVersion + BbWindShelter::BinaryAdd && // (r117)\n"
     "        binary_version != Serialization::HangShaderBinaryVersion + BbWindShelter::BinaryAdd) {\n"),
],
OH: [
    ("ins", '#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)\n', "",
     '#include "bbport_wind_shelter.h" // bbport (r117_wind-shelter)\n'),
],
OC: [
    ("rep", "(BbWindSway::KnobOnce().on ? BbWindHang::SwayBytes() : 0u), // (r112)",
     "(BbWindSway::KnobOnce().on ? BbWindShelter::BufferBytes(BbWindHang::SwayBytes()) : 0u), // (r112, r117)"),
    ("ins", "        std::memset(sway_words, 0, BbWindHang::SwayBytes()); // bbport (r112): and its words\n",
     "", MEMSET_TEXT),
],
RH: [
    ("ins", '#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)\n', "",
     '#include "video_core/renderer_vulkan/vk_wind_shelter.h" // bbport (r117_wind-shelter)\n'),
    ("ins", "    BbWindSway::Ripple sway_ripple;\n", "",
     "    /// bbport (r117_wind-shelter): made only with BB_WIND=1 and BB_WIND_SHELTER above 0\n"
     "    /// (WindShelter::Wanted, read once), else null: its hooks are null pointer tests.\n"
     "    std::unique_ptr<WindShelter> wind_shelter;\n"),
],
RC: [
    ("ins", "    // bbport (r98_ambient-particles): BB_PARTICLES above 0 only (AmbientMotes::Get, read once\n",
     CREATE_TEXT, ""),
],
RE: [
    ("rep", "    wind.Advance(params, seconds);\n",
     "    // bbport (r117_wind-shelter): the wind at the camera is the open wind times the share the\n"
     "    // shelter field leaves there (1 without BB_WIND_SHELTER)\n"
     "    wind.Advance(params, seconds, wind_shelter ? wind_shelter->CameraOpen() : 1.0f);\n"),
    ("ins", "    // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA_VIEW: the card debug view, last, over all of it.\n",
     HOOK_TEXT, ""),
],
CM: [
    ("ins", "    # bbport (r82_wind-stage1): the WIND builds and the noise test include the fog noise.\n",
     "    # bbport (r117_wind-shelter): the wind shelter's pass and its reader include their layout\n"
     "    if (FILENAME MATCHES \"^wind_shelter\")\n"
     "        list(APPEND INCLUDES ${SHADER_SRC}/wind_shelter_layout.h ${SHADER_SRC}/wind_shelter.glsl)\n"
     "    endif()\n", ""),
    ("ins", "# bbport (r82_wind-stage1): BB_WIND=1 only (made at the first march that drifts): the sun fog\n",
     "# bbport (r117_wind-shelter): BB_WIND_SHELTER only: the wind shelter field's passes and, with\n"
     "# BB_WIND_SHELTER_SHOW, the view that paints it (renderer_vulkan/vk_wind_shelter.cpp)\n"
     "add_host_shader(wind_shelter.comp wind_shelter_comp)\n"
     "add_host_shader(wind_shelter.comp wind_shelter_show_comp SHOW=1)\n", ""),
    ("ins", "target_include_directories(wind-test PRIVATE ..)\n", "",
     "# bbport (r117_wind-shelter): the wind shelter field's knob, layout, reader and model\n"
     "# (shim/bbport_wind_shelter.h); also built and run by engine/build.sh --test.\n"
     "add_executable(wind-shelter-test EXCLUDE_FROM_ALL ../tests/test_wind_shelter.cpp)\n"
     "target_compile_options(wind-shelter-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
     "target_include_directories(wind-shelter-test PRIVATE ..)\n"),
],
BS: [
    ("ins", "    out/wind-test\n", "",
     "    # bbport (r117_wind-shelter): the wind shelter field's knob, layout, reader and model\n"
     "    \"${CXX:-clang++}\" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_wind_shelter.cpp -o out/wind-shelter-test\n"
     "    out/wind-shelter-test\n"),
],
}

README_ROWS = (
    "| `BB_WIND_SHELTER` | Where the wind is broken or stopped: behind a wall, a building or a tall tomb "
    "the plants and what hangs move much less, indoors not at all, in the open as before. A strength, 0 "
    "(off) to 1 (the most of the wind it may take away); needs `BB_WIND=1` and the plant sway "
    "(`BB_WIND_SWAY` above 0, its default). It is made from the scene depth, so it needs no ray tracing "
    "(the plant sway itself does): once a frame right before the upscaler (not with `BB_UPSCALER=none`) a "
    "64 m window of 1 m cells around the camera gets, per cell, three rays 28 m upwind and the median of "
    "what they meet (a wall 3 m high shelters fully within 5 m behind it and not at all beyond 17 m; a "
    "post or a person shelters hardly), a roof overhead adds (a hall gives 1, an open pavilion about a "
    "half), the result is blurred, faded at the window's edge and followed over about a second. Plants "
    "and hanging things read it per vertex; the sun fog's drift, the particles and the heat haze read "
    "it at the camera (the wind there is the open wind times 1 minus the field). The log line `Wind "
    "shelter (r117)` gives the share of the view sheltered and the mean value | `0` |\n"
    "| `BB_WIND_SHELTER_SHOW` | Test view of the field: `1` paints it over the scene within 30 m of the "
    "camera (green open, yellow half, red sheltered), `2` paints it alone on black | off |\n")


def readme_edit(text):
    """The README rows go after the BB_WIND_SWAY_SHOW row (the whole line is the anchor)."""
    lines = [l for l in text.split("\n") if l.startswith("| `BB_WIND_SWAY_SHOW` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_WIND_SWAY_SHOW row is there %d times, wanted 1" % len(lines))
    return ("ins", lines[0] + "\n", "", README_ROWS)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    if path == RM:
        return [readme_edit(text)]
    return EDITS[path]


def state_of(cur, eds, path):
    """'applied' (every edit's text there once, anchors and olds as they should be), 'clean' (none),
    else refuse. Inserted texts are found by themselves, not next to their anchor."""
    done = todo = 0
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
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
            _, old, new = e
            if old in new:
                raise SystemExit("patch bug: a replacement holds its own old text: %r" % old[:50])
            no, nn = cur.count(old), cur.count(new)
            if no == 0 and nn == 1:
                done += 1
            elif no == 1 and nn == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: old text %d times, new text %d times (wanted 1 and 0, or 0 and 1): %r"
                                 % (path, no, nn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def new_files_state():
    have = []
    for path, text in NEW_FILES.items():
        full = os.path.join(ROOT, path)
        if os.path.exists(full):
            same = open(full, "rb").read().decode("utf-8").replace("\r\n", "\n") == text
            if not same:
                raise SystemExit("REFUSED: %s exists with other content" % path)
            have.append(True)
        else:
            have.append(False)
    if all(have):
        return "applied"
    if not any(have):
        return "clean"
    raise SystemExit("some of the new files are there, some not: %s" % [p for p, h in zip(NEW_FILES, have) if h])


# ---- the Python copy of the model (twin of BbWindShelter's), for the numbers the test asserts ----
def _ss(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def _q(y):
    return min(max(math.floor((y + 1024.0) * 32.0 + 0.5), 0), 65535) / 32.0 - 1024.0


def _col(bot, top):
    return (_q(bot), _q(top))


def _ray(col, cx, cz, dx, dz, g):
    fx, fz, blocked, k = cx + 0.5, cz + 0.5, 0.0, 1
    while k <= 28 and blocked < 1.0:
        c = col(math.floor(fx + dx * k), math.floor(fz + dz * k))
        if c:
            ex, lift = max(c[1] - g - 1.0, 0.0), c[0] - g
            blocked = max(blocked, _ss(0.12, 0.40, ex / k) * (1.0 - _ss(1.2, 2.4, lift)))
        k += 1
    return blocked


def _rot(vx, vz, deg):
    a = math.radians(deg)
    return vx * math.cos(a) - vz * math.sin(a), vx * math.sin(a) + vz * math.cos(a)


def _raw(col, cx, cz, dx, dz, cam_y=1.7):
    own = col(cx, cz)
    g = cam_y - 1.7
    if own:
        g = own[0]
    else:
        lows = [col(cx + i, cz + j)[0] for j in (-1, 0, 1) for i in (-1, 0, 1) if col(cx + i, cz + j)]
        if lows:
            g = min(lows)
    a, c = _rot(-dx, -dz, -14.0), _rot(-dx, -dz, 14.0)
    r = [_ray(col, cx, cz, a[0], a[1], g), _ray(col, cx, cz, -dx, -dz, g), _ray(col, cx, cz, c[0], c[1], g)]
    lee = max(min(r[0], r[1]), min(max(r[0], r[1]), r[2]))
    roof = _ss(2.0, 3.2, own[1] - g) if own else 0.0
    return 1.0 - (1.0 - lee) * (1.0 - 0.5 * roof)


def model_checks():
    flat = lambda x, z: _col(0, 0)
    wall = lambda x, z: _col(0, 3) if x == 10 and -20 <= z <= 20 else _col(0, 0)
    post = lambda x, z: _col(0, 3) if (x, z) == (10, 0) else _col(0, 0)
    tomb = lambda x, z: _col(0, 2) if x == 10 and -2 <= z <= 2 else _col(0, 0)
    deck = lambda x, z: _col(5, 6) if x == 10 else _col(0, 0)
    room = lambda x, z: _col(0, 3) if -10 <= x <= 10 and -10 <= z <= 10 else None
    pavilion = lambda x, z: _col(0, 3) if (x, z) == (0, 0) else _col(0, 0)
    want = [
        ("flat", _raw(flat, 5, 0, 1, 0), 0.0, 0.0), ("wall 11", _raw(wall, 11, 0, 1, 0), 1.0, 1e-6),
        ("wall 14", _raw(wall, 14, 0, 1, 0), 1.0, 1e-6), ("wall 16", _raw(wall, 16, 0, 1, 0), 0.857, 0.01),
        ("wall 20", _raw(wall, 20, 0, 1, 0), 0.198, 0.01), ("wall 26", _raw(wall, 26, 0, 1, 0), 0.0, 0.01),
        ("wall 30", _raw(wall, 30, 0, 1, 0), 0.0, 0.0), ("wall front", _raw(wall, 5, 0, 1, 0), 0.0, 0.0),
        ("wall along", _raw(wall, 12, 0, 0, 1), 0.0, 0.0), ("wall toward -x", _raw(wall, 7, 0, -1, 0), 1.0, 0.01),
        ("post 11", _raw(post, 11, 0, 1, 0), 1.0, 0.01), ("post 13", _raw(post, 13, 0, 1, 0), 0.0, 0.0),
        ("tomb 13", _raw(tomb, 13, 0, 1, 0), 0.857, 0.01), ("tomb 18", _raw(tomb, 18, 0, 1, 0), 0.0, 0.01),
        ("deck", _raw(deck, 14, 0, 1, 0), 0.0, 0.0), ("room", _raw(room, 0, 0, 1, 0), 1.0, 1e-6),
        ("pavilion", _raw(pavilion, 0, 0, 1, 0), 0.4635, 0.05),
    ]
    for name, got, expect, tol in want:
        if abs(got - expect) > tol:
            raise SystemExit("model check: %s is %.4f, the test asserts %.4f +- %g" % (name, got, expect, tol))
    k = 1.0 - math.exp(-1.0 / 0.5)
    if not 0.86 < k < 0.87:
        raise SystemExit("model check: a second's follow is %.4f" % k)


def text_checks(texts):
    layout, header, comp, glsl = texts[NL], texts[NH], texts[NC], texts[NG]
    for want in ("#define WS_BLOCK_WORD 4096u", "#define WS_N 64u", "#define WS_M 128u", "#define WS_STEPS 28u",
                 "#define WS_BAND 14.0f", "#define WS_TAN_LO 0.12f", "#define WS_TAN_HI 0.40f",
                 "#define WS_RAY_DEG 14.0f", "#define WS_TAU 0.5f", "#define WS_GAIN 1.06f"):
        if layout.count(want) != 1:
            raise SystemExit("text check: %s lacks %r" % (NL, want))
    for want in ("static_assert(BlockWord >= BbWindSway::RegionWords", "static_assert(sizeof(Push) == 128",
                 "static_assert(HeaderWords == 8 && N % 8 == 0 && M % 8 == 0 && M >= N + 2 * (Steps + 2)"):
        if header.count(want) != 1:
            raise SystemExit("text check: %s lacks %r" % (NH, want))
    # the shader and its reader use the layout's names, once each where it matters
    for want, n in (("#include \"wind_shelter_layout.h\"", 1), ("#include \"wind_shelter.glsl\"", 1),
                    ("case WS_MODE_SPLAT:", 1), ("case WS_MODE_MERGE:", 1), ("case WS_MODE_RAW:", 1),
                    ("case WS_MODE_FINAL:", 1), ("#ifdef SHOW", 3)):
        if comp.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (NC, want, comp.count(want), n))
    if glsl.count("float wind_shelter_at(WindShelterRegion r, vec3 p)") != 1:
        raise SystemExit("text check: the GLSL reader is not there once")
    # the two emitters' blocks are the same text apart from the dialect: same constants in the same order
    import re
    def consts(block):
        return re.findall(r"S::(\w+)", block)
    if consts(EMIT_BLOCK) != consts(LIFT_BLOCK):
        raise SystemExit("text check: the two emitters' shelter blocks use different constants")
    for block in (EMIT_BLOCK, LIFT_BLOCK):
        if block.count("BbWindShelter::KnobOnce().on") != 1 or block.count("f(1.0f / S::BandSoft)") + block.count("CF(1.0f / S::BandSoft)") != 1:
            raise SystemExit("text check: a shelter block lacks its knob test or its band")
    # one reader semantics: header words 0, 1, 2, 3, 5, 6, 7 read in the emitters, 4 never (N is a constant)
    for block in (EMIT_BLOCK, LIFT_BLOCK):
        words = sorted(set(re.findall(r"shelter_word\((\d)u\)", block)))
        if words != ["0", "1", "2", "3", "5", "6", "7"]:
            raise SystemExit("text check: a shelter block reads header words %s" % words)
    rm = [l for l in texts[RM].split("\n") if l.startswith("| `BB_WIND_SHELTER` |") or l.startswith("| `BB_WIND_SHELTER_SHOW` |")]
    if len(rm) != 2:
        raise SystemExit("text check: the README rows are not both there once")
    if "BB_WIND_SHELTER" not in texts[CM] or texts[CM].count("add_host_shader(wind_shelter.comp") != 2:
        raise SystemExit("text check: CMakeLists.txt lacks the two shader builds")
    # the emitter hook sits right before the store of the displaced position, after `moved` is made
    for path in (EM, LS):
        t = texts[path]
        a = t.find("if (BbWindShelter::KnobOnce().on) {")
        b = t.find("moved[r] = " if path == LS else "moved[r] = add(comp(position, r)")
        if not (0 <= b < a):
            raise SystemExit("text check: %s: the shelter block does not come after `moved` is made" % path)
    model_checks()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R117_ROOT)" % ROOT)
    plan = []
    for path in (BW, EM, LS, PS, OH, OC, RH, RC, RE, CM, BS, RM):
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    nstate = new_files_state()
    states.add(nstate)
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) + ", new files " + nstate)
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for e in eds:
                if e[0] == "ins":
                    cur = cur.replace(e[1], e[2] + e[1] + e[3])
                else:
                    cur = cur.replace(e[1], e[2])
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        out.update(NEW_FILES)
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan} | NEW_FILES)
            print("applied (text checks and the model's numbers pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the "
                  "result and the model's numbers pass)" % (len(plan), sum(len(p[1]) for p in plan), len(NEW_FILES)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r117tmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path, text in NEW_FILES.items():
            full = os.path.join(ROOT, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            open(full, "wb").write(text.replace("\n", "\r\n").encode("utf-8"))
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for e in reversed(eds):
            if e[0] == "ins":
                for part in (e[3], e[2]):
                    if part:
                        cur = cur.replace(part, "", 1)
            else:
                cur = cur.replace(e[2], e[1], 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r117tmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
