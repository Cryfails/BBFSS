// SPDX-License-Identifier: GPL-3.0-or-later
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
inline constexpr float CoverTan = WS_COVER_TAN, CoverDist = WS_COVER_DIST, CoverLo = WS_COVER_LO,
                       CoverHi = WS_COVER_HI, CoverTau = WS_COVER_TAU, CoverRadius = WS_COVER_RADIUS,
                       CoverRate = WS_COVER_RATE, CoverNear = WS_COVER_NEAR;
inline constexpr std::uint32_t CoverMin = WS_COVER_MIN, GlobalWords = WS_GLOBAL_WORDS;
inline constexpr float CoverClose = WS_COVER_CLOSE, DownNy = WS_DOWN_NY, NormalTol = WS_NORMAL_TOL,
                       EffMax = WS_EFF_MAX, NearTopLo = WS_NEAR_TOP_LO, NearTopHi = WS_NEAR_TOP_HI,
                       NearCamLo = WS_NEAR_CAM_LO, NearCamHi = WS_NEAR_CAM_HI; // r117c
inline constexpr float ThinHLo = WS_THIN_H_LO, ThinHHi = WS_THIN_H_HI, ThinWLo = WS_THIN_W_LO,
                       ThinWHi = WS_THIN_W_HI, ThinNb = WS_THIN_NB, ThinUnseen = WS_THIN_UNSEEN; // r117d
inline constexpr float DistNear = WS_DIST_NEAR, DistFar = WS_DIST_FAR, DistFloor = WS_DIST_FLOOR,
                       ElevLo = WS_ELEV_LO, ElevHi = WS_ELEV_HI; // r117f
inline constexpr float ShortLo = WS_SHORT_LO, ShortHi = WS_SHORT_HI, ShortReach = WS_SHORT_REACH,
                       SelfHLo = WS_SELF_H_LO, SelfHHi = WS_SELF_H_HI, SelfRise = WS_SELF_RISE,
                       SelfKeep = WS_SELF_KEEP; // r117g
static_assert(ShortHi > ShortLo && SelfHHi > SelfHLo && SelfRise > 0.0f && ShortReach > DistNear && ShortReach <= DistFar &&
                  SelfKeep >= 0.0f && SelfKeep <= 1.0f,
              "the short lee's and the own height's edges");
static_assert(DistFar > DistNear && ElevHi > ElevLo && ElevLo > 0.0f && DistFloor > 0.0f && DistFloor <= 1.0f,
              "the far weight's edges");
inline constexpr float RayDeg = WS_RAY_DEG, Gain = WS_GAIN, EdgeCells = WS_EDGE_CELLS;
inline constexpr float Tau = WS_TAU, NoGround = WS_NO_GROUND;
inline constexpr float YBias = WS_Y_BIAS, YScale = WS_Y_SCALE;
inline constexpr std::uint32_t BinaryAdd = 1000; ///< added to the sway shader binary version when on

static_assert(BlockWord >= BbWindSway::RegionWords && BlockWord % 4 == 0,
              "the field lies behind the sway words (r112's longer region ends at word 3584)");
static_assert(HeaderWords == 8 && N % 8 == 0 && M % 8 == 0 && M >= N + 2 * (Steps + 2),
              "the cache holds the window and every upwind ray from it");
static_assert(N / 2 > std::uint32_t(EdgeCells) && Stride >= 1);
static_assert(TanHi > TanLo && LiftHi > LiftLo && CoverHi > CoverLo && CoverRate > 0.0f &&
              CoverRate <= 1.0f && CoverRadius > CoverNear);

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

/// r117c: how much an obstacle counts: 0 for a low one (`top_above_ground` under NearTopLo..NearTopHi: the
/// Hunter, a person) that stands within NearCamLo..NearCamHi m of the camera (`dist_cam`, xz), 1 else.
[[nodiscard]] inline float NearKeep(float top_above_ground, float dist_cam) {
    return std::max(BbWind::Smoothstep(NearTopLo, NearTopHi, top_above_ground),
                    BbWind::Smoothstep(NearCamLo, NearCamHi, dist_cam));
}

/// r117d: how much an obstacle of height `top_above_ground` counts: 0 under ThinHLo, 1 from ThinHHi.
[[nodiscard]] inline float HeightWeight(float top_above_ground) {
    return BbWind::Smoothstep(ThinHLo, ThinHHi, top_above_ground);
}

/// r117f: how much an obstacle counts at `dist` m along a ray (wind_shelter.comp's far_weight): its weight by distance
/// (1 up to DistNear, DistFloor from DistFar, linear between) times Smoothstep(ElevLo, ElevHi, the tangent of the
/// elevation of its top, `top_above_ground` less HStart, over `dist`): its real height, no cap.
[[nodiscard]] inline float FarWeight(float dist, float top_above_ground) {
    // r117g: a low thing (under ShortLo) gives a lee ShortReach m long and nothing beyond, one from ShortHi as in r117f
    const float s = BbWind::Smoothstep(ShortLo, ShortHi, top_above_ground);
    const float reach = ShortReach + (DistFar - ShortReach) * s;
    const float t = std::clamp((dist - DistNear) / (reach - DistNear), 0.0f, 1.0f);
    return (1.0f - (1.0f - DistFloor * s) * t) *
           BbWind::Smoothstep(ElevLo, ElevHi, (top_above_ground - HStart) / dist);
}

/// r117g: how much a hit of `top_above_ground` m counts for a cell whose own top is `own_up` m over its ground
/// (wind_shelter.comp's self_weight): 1 for a cell that is not tall and for a hit rising SelfRise m or more above the
/// cell's top, down to SelfKeep for a hit no higher than a tall cell's own top.
[[nodiscard]] inline float SelfWeight(float top_above_ground, float own_up) {
    const float k = BbWind::Smoothstep(SelfHLo, SelfHHi, own_up);
    const float over = BbWind::Smoothstep(0.0f, SelfRise, top_above_ground - own_up);
    return 1.0f - k * (1.0f - SelfKeep) * (1.0f - over);
}

/// r117d: the weight of an obstacle by its width across a ray: the thing met at the world point (x, z) m by a
/// ray along the unit vector (dx, dz): w = 1 + the cells 1 and 2 to either side of it across the ray, counted from
/// the middle of the cell met (a slanted ray meets a cell near its edge) (a known
/// cell with a top at least ThinNb above `ground` adds 1, an unknown cell ThinUnseen, a known low cell 0),
/// the weight Smoothstep(ThinWLo, ThinWHi, w): one cell wide with known low cells either side 0, two cells 0.5,
/// three or more 1 (wind_shelter.comp's thick_weight, operation for operation).
template <class ColumnFn>
[[nodiscard]] float ThinWeight(ColumnFn&& column, float x, float z, float dx, float dz, float ground) {
    const float sx = -dz * Cell, sz = dx * Cell;
    const float ax = dx * Cell, az = dz * Cell;
    const float mx = (std::floor(x * (1.0f / Cell)) + 0.5f) * Cell, mz = (std::floor(z * (1.0f / Cell)) + 0.5f) * Cell;
    float w = 1.0f;
    for (int j = -2; j <= 2; ++j) {
        if (j != 0) {
            // the cell across the ray and the two one step up and down the ray from it (a slanting wall stays
            // wide): tall if any of the three is; unknown only by the middle one
            const float px = mx + sx * float(j), pz = mz + sz * float(j);
            float v = 0.0f;
            for (int a = -1; a <= 1; ++a) {
                const Column nb = column(int(std::floor((px + ax * float(a)) * (1.0f / Cell))),
                                         int(std::floor((pz + az * float(a)) * (1.0f / Cell))));
                if (nb.seen && nb.top - ground >= ThinNb && nb.bot - ground < LiftLo) { // r117e: it stands
                    v = 1.0f;
                } else if (a == 0 && !nb.seen) {
                    v = std::max(v, ThinUnseen);
                }
            }
            w += v;
        }
    }
    return BbWind::Smoothstep(ThinWLo, ThinWHi, w);
}

/// A ray from the middle of cell (cx, cz) UPWIND along (dx, dz) (a unit vector): how far it is
/// blocked, 0-1. `column(ix, iz)` gives the Column of a cell. Each step is one cell; a column
/// whose top stands more than HStart above `ground` blocks by smoothstep(TanLo, TanHi, excess /
/// distance), less if its bottom is high above the ground (a deck or an arch).
template <class ColumnFn>
[[nodiscard]] float RayBlocked(ColumnFn&& column, int cx, int cz, float dx, float dz,
                               float ground, float cam_x = 1.0e9f, float cam_z = 1.0e9f, float own_up = 0.0f) {
    const float fx = (float(cx) + 0.5f) * Cell, fz = (float(cz) + 0.5f) * Cell;
    float blocked = 0.0f;
    for (std::uint32_t k = 1; k <= Steps && blocked < 1.0f; ++k) {
        const float dist = float(k) * Cell;
        const int ix = int(std::floor((fx + dx * dist) * (1.0f / Cell)));
        const int iz = int(std::floor((fz + dz * dist) * (1.0f / Cell)));
        const Column col = column(ix, iz);
        if (col.seen) {
            // r117c: at most EffMax (a tree is a 3 m wall), and a low obstacle near the camera not at all
            const float excess = std::min(std::max(col.top - ground - HStart, 0.0f), EffMax);
            const float lift = col.bot - ground;
            const float pass = 1.0f - BbWind::Smoothstep(LiftLo, LiftHi, lift);
            const float keep = NearKeep(col.top - ground, std::hypot((float(ix) + 0.5f) * Cell - cam_x,
                                                                      (float(iz) + 0.5f) * Cell - cam_z));
            // r117d: by the height and by the width across the ray, the width only when it matters
            float hit = BbWind::Smoothstep(TanLo, TanHi, excess / dist) * pass * keep;
            if (hit > blocked) {
                hit *= HeightWeight(col.top - ground);
                if (hit > blocked) {
                    hit *= FarWeight(dist, col.top - ground); // r117f: by the distance and the elevation
                    hit *= SelfWeight(col.top - ground, own_up); // r117g: by the cell's own height
                    if (hit > blocked) {
                        hit *= ThinWeight(column, fx + dx * dist, fz + dz * dist, dx, dz, ground);
                    }
                    blocked = std::max(blocked, hit);
                }
            }
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
/// upwind rays (-RayDeg, 0, +RayDeg) is the leeward value, the cover (0-1, r117b: what the camera saw
/// overhead; the biggest of the cell and its 8 neighbours; a cell's own height gives no roof) adds
/// to it: 1 - (1 - leeward) (1 - cover). `cam_y`: the camera's height, which gives the ground of a
/// cell nothing is known about (cam_y - NoGround).
template <class ColumnFn>
[[nodiscard]] float Raw(ColumnFn&& column, int cx, int cz, float dir_x, float dir_z, float cam_y,
                        float cover = 0.0f, float cam_x = 1.0e9f, float cam_z = 1.0e9f) {
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
    const float own_up = own.seen ? own.top - ground : 0.0f; // r117g: how tall the cell itself is
    const float r0 = RayBlocked(column, cx, cz, a[0], a[1], ground, cam_x, cam_z, own_up);
    const float r1 = RayBlocked(column, cx, cz, ux, uz, ground, cam_x, cam_z, own_up);
    const float r2 = RayBlocked(column, cx, cz, c[0], c[1], ground, cam_x, cam_z, own_up);
    const float leeward = Median3(r0, r1, r2);
    return 1.0f - (1.0f - leeward) * (1.0f - cover);
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

// ---- the cover (r117b: indoors, measured at the camera) -------------------------------------

/// A view ray (any length, world) climbs steeply enough to count: its elevation's tangent is above
/// CoverTan.
[[nodiscard]] inline bool CoverRayUp(float dx, float dy, float dz) {
    return dy > CoverTan * std::sqrt(dx * dx + dz * dz);
}

/// r117c: a climbing view ray that ended `dist` m from the camera on a surface whose normal (unit, turned
/// toward the camera) has y `normal_y` is covered: within CoverClose of any surface, or beyond that, within
/// CoverDist, on one that faces down (normal y below -DownNy: a ceiling, a vault, a canopy's underside).
[[nodiscard]] inline bool CoverHit(float dist, float normal_y) {
    return dist < CoverClose || (dist < CoverDist && normal_y < -DownNy);
}

/// The share of the climbing rays (`up` of them) that ended within CoverDist (`covered`).
[[nodiscard]] inline float CoverShare(std::uint32_t up, std::uint32_t covered) {
    return up != 0 ? float(covered) / float(up) : 0.0f;
}

/// The camera's smoothed covered share after a frame: fewer than CoverMin climbing rays: the old
/// value stands; the first measure (`first`) is taken whole; else a time constant of CoverTau.
[[nodiscard]] inline float CoverFollow(float prev, std::uint32_t up, std::uint32_t covered, float dt,
                                       bool first) {
    if (up < CoverMin) {
        return prev;
    }
    const float k = first ? 1.0f : 1.0f - std::exp(-dt * (1.0f / CoverTau));
    return prev + (CoverShare(up, covered) - prev) * k;
}

/// The cover the cells take from the smoothed share.
[[nodiscard]] inline float CoverIndoors(float share) {
    return BbWind::Smoothstep(CoverLo, CoverHi, share);
}

/// One cache cell's cover after a frame: `away` m from the camera, `samples` depth samples of the
/// cell in this frame; the cells next to the camera take `indoors` outright, a cell seen within
/// CoverRadius moves toward it by CoverRate, any other keeps what it had.
[[nodiscard]] inline float CoverCell(float cover, float indoors, float away, std::uint32_t samples) {
    if (away < CoverNear * Cell) {
        return indoors;
    }
    if (samples >= MinSamples && away < CoverRadius * Cell) {
        return cover + (indoors - cover) * CoverRate;
    }
    return cover;
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
    std::uint64_t climb_up = 0, climb_close = 0, climb_down = 0, climb_mid = 0; ///< r117c
    std::uint64_t thin_seen = 0, thin_low = 0, thin_narrow = 0; ///< r117d
    std::uint64_t thin_kept = 0, thin_tall = 0; ///< r117e
    std::uint64_t far_cut = 0; ///< r117f
    std::uint64_t self_cut = 0, self_cells = 0; ///< r117g
};

[[nodiscard]] inline Counts CountsBetween(const std::uint32_t* now, const std::uint32_t* before) {
    const auto d = [&](std::uint32_t w) { return std::uint64_t(std::uint32_t(now[w] - before[w])); };
    const auto d64 = [&](std::uint32_t lo, std::uint32_t hi) { // a total in two words (r117b)
        return ((std::uint64_t(now[hi]) << 32) | now[lo]) -
               ((std::uint64_t(before[hi]) << 32) | before[lo]);
    };
    return {d(WS_C_PIXELS),         d(WS_C_PIXELS_SHELTERED), d(WS_C_PIXELS_INDOOR),
            d64(WS_C_PIXELS_SUM, WS_C_PIXELS_SUM_HI), d(WS_C_CELLS_SEEN), d(WS_C_CELLS_SHELTERED),
            d(WS_C_CELLS),          d(WS_C_CELLS_SUM),        d(WS_C_MERGED),
            d(WS_C_UP),             d(WS_C_CLOSE),            d(WS_C_DOWN),
            d(WS_C_MID),
            d(WS_C_THIN_SEEN),      d(WS_C_THIN_LOW),         d(WS_C_THIN_NARROW),
            d(WS_C_THIN_KEPT),      d(WS_C_THIN_TALL),        d(WS_C_FAR_CUT),       d(WS_C_SELF_CUT),
            d(WS_C_SELF_CELLS)};
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
