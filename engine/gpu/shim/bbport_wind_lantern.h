// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112v_lantern-hangs): only the LANTERN of a bracket lamp post leans with the wind (BB_WIND_HANG=1, BB_WIND_HANG_POST, new knob
// BB_WIND_HANG_LANTERN, default on). The post, its arm, the bridge, chains, grilles and hooks stay still.
//
// WHY (r112s..r112u): the lamp post's position stream (13642 vertices, 5.69 m tall, 2.15 m wide, 0.85 m deep in model space, origin at the foot)
// is one mesh: pole, arm and lantern. r112s moved its top fifth as one piece (the owner saw the bridge behind it move, and a post that bends),
// and r112u's guard refused the whole stream because its box is over the size limits: nothing moved at all.
//
// HOW the lantern is told from the post, inside the one stream. The vertex shaders (the recompiler's EmitVertexSway and the lifter's epilogue)
// know a vertex's WORLD position (the camera's world x, z plus the vertex's offset: BbWindSway WindE.z, .w and rx, rz; its world y: wy) but
// not its model position. So the weight is a function of the world position against a small plan the CPU puts in the post's slot, from the
// ray traced scene's box of the post (the world box of the post nearest the camera, r112t's pick) and the stream's own vertices (read once):
//   weight = wr x wo x wv   (then the same smoothstep and ramp as every hanging word, the push of the gust follower, held to PostGuardPush)
//   wr  radial: r = horizontal distance of the vertex from the post's axis (the box's centre in x and z; the mesh is symmetric about its
//       axis). 0 up to R0 (the pole and the foot lie inside it), 1 from R1 (the lantern, out at the arm's tip), smooth between.
//   wo  outer: 1 up to OuterFull, 0 from OuterZero. A second post of the same mesh (another instance) lies far from this axis and so
//       gets weight 0 (only the post nearest the camera has a lantern that leans: said in the log).
//   wv  vertical: d = the vertex's depth below the arm's lower edge (world y of the arm edge = the box's foot + the plan's model arm height).
//       0 down to HookStill (the hook and the arm stay still), 1 from HookStill + HookSpan. So the lantern is held at its hook.
// The plan's arm edge is found from the stream: the vertices beyond R0 from the axis and above FootClear over the mesh's lowest vertex are
// the arm and the lantern (the pole and the foot are inside R0); the arm edge is ArmBand under the highest of them.
//
// WHERE the plan lives: three keys' pairs of the post's slot that the sway region already has and nothing else reads for a post word:
//   base key (BaseAt + slot) = the arm edge - BaseBelow (so the keys' height is over HangFull and the push is not scaled down),
//   top key (TopAt + slot)   = the arm edge (the shader's hh is the depth below it),
//   the twigs' four box keys (TwigAt + 4 slot + 0..3: lowest x, highest x, lowest z, highest z) = axis x -+ R0, axis z -+ R1: the shader
//   reads the centre as the axis and the half widths as R0 and R1, so R0 and R1 are live knobs without a shader change.
// A post word makes no vertex offer to any of these keys (post_none in both emitters, as r112t did for base and top).
// It needs the twigs' box keys (BB_WIND_TWIGS, on by default with BB_WIND=1 and the lean): with them off the knob is "asked but off", said
// once, and the post gets no word (nothing moves).
//
// OFF: BB_WIND_HANG unset: nothing here is reached (the post rule needs BB_WIND_HANG). BB_WIND_HANG_LANTERN=0: r112s/r112t's rule and r112u's guard.
// The shaders differ by the knob (the sway binary version carries LanternBinaryAdd in bbport_wind_hang.h).
#pragma once

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unordered_map>

#include "bbport_wind_hang.h"
#include "bbport_wind_twigs.h"

namespace BbWindLantern {

namespace H = BbWindHang;
namespace W = BbWindSway;

inline constexpr float R0Default = 0.55f;    ///< m from the post's axis: the weight starts (the shaft and the foot lie inside: the foot is 0.42 m)
inline constexpr float R1Default = 0.85f;    ///< m from the axis: the weight is full radially
inline constexpr float ArmBandDefault = 0.25f; ///< m under the highest far vertex: the arm's lower edge
inline constexpr float OuterFull = 1.30f;    ///< m: radial weight 1 up to here (the mesh's own farthest vertex is 1.16 m out)
inline constexpr float OuterZero = 1.55f;    ///< m: and 0 from here (another post of the same mesh lies far from this axis)
inline constexpr float HookStill = 0.05f;    ///< m under the arm's lower edge that stay still (the hook)
inline constexpr float HookSpan = 0.25f;     ///< m over which the vertical weight rises to 1
inline constexpr float FootClear = 1.0f;     ///< m over the mesh's lowest vertex under which no vertex counts as arm or lantern
inline constexpr float SpanMin = 0.05f;      ///< m: the least R1 - R0 the shaders divide by
inline constexpr float BaseBelow = 3.0f;     ///< m: the base key's distance under the arm's edge (the keys' height is over HangFull: no scale-down)
inline constexpr float ProofMin = 0.02f;     ///< the proof tint marks a vertex whose weight is above this
inline constexpr float WideMost = 3.0f;      ///< m: a box of the stream wider than this in x or z is no lamp post
inline constexpr float TallMost = 8.0f;      ///< m: or taller
inline constexpr std::size_t BookMost = 64;  ///< streams kept at most

static_assert(OuterZero > OuterFull && OuterFull > R1Default && R1Default > R0Default && R0Default > 0.0f);
static_assert(HookSpan > 0.0f && HookStill >= 0.0f && FootClear > 0.5f && BaseBelow > H::HangFull);
static_assert(H::PostBinaryAdd + H::LanternBinaryAdd < H::ProofBinaryAdd, "under the proof's add");

/// BB_WIND_HANG_LANTERN_R0, _R1, _ARM, _ARM_Y read once and clamped. `arm_y` (model y of the arm's lower edge) 0 = from the stream.
struct Knob {
    float r0 = R0Default, r1 = R1Default, arm = ArmBandDefault, arm_y = 0.0f;
};

[[nodiscard]] inline Knob ParseKnob(const char* r0, const char* r1, const char* arm, const char* arm_y) {
    Knob k;
    k.r0 = std::clamp(W::ParseNumber(r0, R0Default), 0.2f, 1.0f);
    k.r1 = std::clamp(W::ParseNumber(r1, R1Default), k.r0 + SpanMin, 1.4f);
    k.arm = std::clamp(W::ParseNumber(arm, ArmBandDefault), 0.05f, 1.5f);
    k.arm_y = std::clamp(W::ParseNumber(arm_y, 0.0f), 0.0f, 100.0f);
    return k;
}

[[nodiscard]] inline const Knob& KnobOnce() {
    static const Knob knob = ParseKnob(std::getenv("BB_WIND_HANG_LANTERN_R0"), std::getenv("BB_WIND_HANG_LANTERN_R1"),
                                       std::getenv("BB_WIND_HANG_LANTERN_ARM"), std::getenv("BB_WIND_HANG_LANTERN_ARM_Y"));
    return knob;
}

/// The lantern rule is in force: asked (BB_WIND_HANG_LANTERN not 0, with the post rule) and the twigs' box keys exist. Read once.
[[nodiscard]] inline bool On() {
    static const bool on = H::LanternAsked() && BbWindTwigs::On();
    return on;
}

/// The shaders' weight of a vertex `r` m from the axis and `below` m under the arm's lower edge (R0, R1 from the slot's box keys), operation for
/// operation as the emitters (the radial weight is clamp((r - r0) / max(r1 - r0, SpanMin)); NaN gives 0).
[[nodiscard]] inline float Weight(float r, float below, float r0, float r1) {
    const float span = std::max(r1 - r0, SpanMin);
    const float wr = std::clamp((r - r0) / span, 0.0f, 1.0f);
    const float wo = std::clamp((OuterZero - r) * (1.0f / (OuterZero - OuterFull)), 0.0f, 1.0f);
    const float wv = std::clamp((below - HookStill) * (1.0f / HookSpan), 0.0f, 1.0f);
    const float w = wr * wo * wv;
    return std::isnan(w) ? 0.0f : w;
}

/// What one pass over the stream's vertices (floats 0-2 of each) found, in the mesh's own (model) space.
struct Plan {
    bool ok = false;
    const char* why = "not read"; ///< when not ok
    std::uint32_t verts = 0, core = 0, far = 0, moving = 0, full = 0;
    float ymin = 0.0f, ymax = 0.0f;    ///< the lowest and highest vertex
    float cx = 0.0f, cz = 0.0f;        ///< the centre of the box in x and z (the axis)
    float far_top = 0.0f, far_bottom = 0.0f; ///< the highest and the lowest vertex beyond R0 and above the foot
    float arm_y = 0.0f;                ///< the arm's lower edge (model y): the weight is 0 from here up
    float move_ymin = 0.0f, move_ymax = 0.0f, move_rmin = 0.0f, move_rmax = 0.0f; ///< the moving vertices' height and radius range
    std::array<std::uint32_t, 16> far_by_y{};  ///< far vertices by 0.10 m down from far_top
    std::array<std::uint32_t, 16> far_by_r{};  ///< far vertices by 0.10 m of radius from R0
    std::array<std::uint32_t, 12> core_by_y{}; ///< vertices within R0, by 0.5 m of height above ymin
    float r0 = R0Default, r1 = R1Default;
};

[[nodiscard]] inline bool ReadVertex(const unsigned char* data, std::uint32_t stride, std::uint32_t i, float* out) {
    std::memcpy(out, data + static_cast<std::size_t>(i) * stride, 3 * sizeof(float));
    return std::isfinite(out[0]) && std::isfinite(out[1]) && std::isfinite(out[2]) && std::fabs(out[0]) < 1.0e4f &&
           std::fabs(out[1]) < 1.0e4f && std::fabs(out[2]) < 1.0e4f;
}

/// The plan of a stream of `size` bytes at `stride` bytes a vertex (floats 0-2 are the position). `data` null: not readable.
[[nodiscard]] inline Plan Analyse(const unsigned char* data, std::uint32_t size, std::uint32_t stride, const Knob& knob) {
    Plan p;
    p.r0 = knob.r0;
    p.r1 = knob.r1;
    if (data == nullptr || stride < 12 || size < stride) {
        p.why = "the stream cannot be read";
        return p;
    }
    p.verts = size / stride;
    float xmin = 1.0e30f, xmax = -1.0e30f, zmin = 1.0e30f, zmax = -1.0e30f;
    p.ymin = 1.0e30f;
    p.ymax = -1.0e30f;
    std::uint32_t good = 0;
    float v[3];
    for (std::uint32_t i = 0; i < p.verts; ++i) {
        if (!ReadVertex(data, stride, i, v)) {
            continue;
        }
        ++good;
        xmin = std::min(xmin, v[0]);
        xmax = std::max(xmax, v[0]);
        p.ymin = std::min(p.ymin, v[1]);
        p.ymax = std::max(p.ymax, v[1]);
        zmin = std::min(zmin, v[2]);
        zmax = std::max(zmax, v[2]);
    }
    if (good < 16) {
        p.why = "fewer than 16 finite vertices";
        return p;
    }
    p.cx = 0.5f * (xmin + xmax);
    p.cz = 0.5f * (zmin + zmax);
    p.far_top = -1.0e30f;
    p.far_bottom = 1.0e30f;
    for (std::uint32_t i = 0; i < p.verts; ++i) {
        if (!ReadVertex(data, stride, i, v)) {
            continue;
        }
        const float r = std::hypot(v[0] - p.cx, v[2] - p.cz);
        const float up = v[1] - p.ymin;
        if (r >= p.r0 && up >= FootClear) {
            ++p.far;
            p.far_top = std::max(p.far_top, v[1]);
            p.far_bottom = std::min(p.far_bottom, v[1]);
        } else if (r < p.r0) {
            ++p.core;
            const std::size_t bin = std::min<std::size_t>(static_cast<std::size_t>(up * 2.0f), p.core_by_y.size() - 1);
            ++p.core_by_y[bin];
        }
    }
    if (p.far == 0) {
        p.why = "no vertex beyond R0 from the axis above the foot: not a post with an arm";
        return p;
    }
    p.arm_y = knob.arm_y > 0.0f ? knob.arm_y : p.far_top - knob.arm;
    p.move_ymin = 1.0e30f;
    p.move_ymax = -1.0e30f;
    p.move_rmin = 1.0e30f;
    p.move_rmax = -1.0e30f;
    for (std::uint32_t i = 0; i < p.verts; ++i) {
        if (!ReadVertex(data, stride, i, v)) {
            continue;
        }
        const float r = std::hypot(v[0] - p.cx, v[2] - p.cz);
        const float up = v[1] - p.ymin;
        if (r >= p.r0 && up >= FootClear) {
            const std::size_t by = std::min<std::size_t>(static_cast<std::size_t>(std::max(p.far_top - v[1], 0.0f) * 10.0f), p.far_by_y.size() - 1);
            ++p.far_by_y[by];
            const std::size_t br = std::min<std::size_t>(static_cast<std::size_t>((r - p.r0) * 10.0f), p.far_by_r.size() - 1);
            ++p.far_by_r[br];
        }
        const float w = Weight(r, p.arm_y - v[1], p.r0, p.r1);
        if (w > ProofMin) {
            ++p.moving;
            p.full += w >= 0.99f ? 1u : 0u;
            p.move_ymin = std::min(p.move_ymin, v[1]);
            p.move_ymax = std::max(p.move_ymax, v[1]);
            p.move_rmin = std::min(p.move_rmin, r);
            p.move_rmax = std::max(p.move_rmax, r);
        }
    }
    if (p.moving == 0) {
        p.why = "no vertex would move (the arm edge or the radii leave none)";
        return p;
    }
    p.ok = true;
    p.why = "ok";
    return p;
}

/// The slot's words for a plan: the keys the shaders read, as above. `foot_y` the world y of the picked box's lowest point (the model's ymin),
/// `axis_x`, `axis_z` the box's centre.
struct Keys {
    std::uint32_t base = 0, top = 0, x_lo = 0, x_hi = 0, z_lo = 0, z_hi = 0;
    float arm_world = 0.0f;
};

[[nodiscard]] inline Keys MakeKeys(const Plan& plan, float foot_y, float axis_x, float axis_z) {
    Keys k;
    k.arm_world = foot_y + (plan.arm_y - plan.ymin);
    k.base = W::HeightKey(k.arm_world - BaseBelow);
    k.top = H::TopKey(k.arm_world);
    k.x_lo = W::HeightKey(axis_x - plan.r0);
    k.x_hi = H::TopKey(axis_x + plan.r0);
    k.z_lo = W::HeightKey(axis_z - plan.r1);
    k.z_hi = H::TopKey(axis_z + plan.r1);
    return k;
}

/// What the shaders read back from the keys (the test's twin of their decode): centre, R0, R1 and the arm's world y.
struct Decoded {
    float cx = 0.0f, cz = 0.0f, r0 = 0.0f, r1 = 0.0f, arm_world = 0.0f, height = 0.0f;
};

[[nodiscard]] inline Decoded Decode(const Keys& k) {
    Decoded d;
    const float x_lo = std::bit_cast<float>(k.x_lo) - W::HeightBias;
    const float x_hi = W::HeightBias - std::bit_cast<float>(k.x_hi);
    const float z_lo = std::bit_cast<float>(k.z_lo) - W::HeightBias;
    const float z_hi = W::HeightBias - std::bit_cast<float>(k.z_hi);
    d.cx = 0.5f * (x_lo + x_hi);
    d.cz = 0.5f * (z_lo + z_hi);
    d.r0 = 0.5f * (x_hi - x_lo);
    d.r1 = 0.5f * (z_hi - z_lo);
    d.arm_world = W::HeightBias - std::bit_cast<float>(k.top);
    d.height = (W::HeightBias - std::bit_cast<float>(k.top)) - (std::bit_cast<float>(k.base) - W::HeightBias);
    return d;
}

/// The post's own box (the one PickPost chose) among `boxes` (items with `stream`, `box`: least x, y, z, greatest x, y, z, `src`): its centre.
/// Two posts of the same mesh on flat ground have the same y: with `camera` (x, y, z; null: none) the box whose distance to the camera is the
/// pick's own wins, as PickPost measured it.
struct Axis {
    bool found = false;
    float x = 0.0f, z = 0.0f;
};

template <class Boxes>
[[nodiscard]] inline Axis AxisOf(const Boxes& boxes, std::uint64_t stream, const H::PostPick& pick, const float* camera = nullptr) {
    Axis a;
    if (!pick.found) {
        return a;
    }
    const bool by_distance = camera != nullptr && pick.camera;
    float best = 1.0e30f;
    for (const auto& b : boxes) {
        if (b.stream != stream || b.box[1] != pick.base || b.box[4] != pick.top || b.src != pick.src) {
            continue;
        }
        if (!(std::isfinite(b.box[0]) && std::isfinite(b.box[3]) && std::isfinite(b.box[2]) && std::isfinite(b.box[5]))) {
            continue;
        }
        const float x = 0.5f * (b.box[0] + b.box[3]);
        const float z = 0.5f * (b.box[2] + b.box[5]);
        const float miss = by_distance ? std::fabs(std::sqrt((x - camera[0]) * (x - camera[0]) + (z - camera[2]) * (z - camera[2])) - pick.dist) : 0.0f;
        if (!a.found || miss < best) {
            a.found = true;
            a.x = x;
            a.z = z;
            best = miss;
        }
        if (!by_distance) {
            break;
        }
    }
    return a;
}

enum class Refuse : std::uint8_t { None = 0, Wide, Tall, Shared };
inline constexpr std::size_t RefuseKinds = 4;

struct Guard {
    Refuse why = Refuse::None;
    std::uint32_t count = 0;
    std::array<float, 6> box{};
};

[[nodiscard]] inline const char* RefuseName(Refuse why) {
    switch (why) {
    case Refuse::Wide:
        return "a box wider than the limit";
    case Refuse::Tall:
        return "a box taller than the limit";
    case Refuse::Shared:
        return "a shared stream: many boxes that differ";
    default:
        return "none";
    }
}

/// The verdict on `stream` over every box of it in `boxes`: refused when a box is wider than WideMost or taller than TallMost (a bridge, a wall,
/// a building) or when it has more than PostGuardSharedMost boxes that differ by more than PostGuardSharedTol. A lamp post (5.7 x 2.2 m) passes.
template <class Boxes>
[[nodiscard]] inline Guard GuardCheck(const Boxes& boxes, std::uint64_t stream) {
    Guard g;
    if (stream == 0) {
        return g;
    }
    float wmin = 1.0e30f, wmax = -1.0e30f, hmin = 1.0e30f, hmax = -1.0e30f;
    std::array<float, 6> first{};
    for (const auto& b : boxes) {
        if (b.stream != stream) {
            continue;
        }
        bool usable = true;
        for (const float c : b.box) {
            usable = usable && std::isfinite(c) && std::fabs(c) < 1.0e5f;
        }
        if (!(usable && b.box[4] > b.box[1])) {
            continue;
        }
        const float w = std::max(b.box[3] - b.box[0], b.box[5] - b.box[2]);
        const float h = b.box[4] - b.box[1];
        if (g.count == 0) {
            first = b.box;
        }
        ++g.count;
        if (g.why == Refuse::None && w > WideMost) {
            g.why = Refuse::Wide;
            g.box = b.box;
        } else if (g.why == Refuse::None && h > TallMost) {
            g.why = Refuse::Tall;
            g.box = b.box;
        }
        wmin = std::min(wmin, w);
        wmax = std::max(wmax, w);
        hmin = std::min(hmin, h);
        hmax = std::max(hmax, h);
    }
    if (g.why == Refuse::None && g.count > H::PostGuardSharedMost && (wmax - wmin > H::PostGuardSharedTol || hmax - hmin > H::PostGuardSharedTol)) {
        g.why = Refuse::Shared;
        g.box = first;
    }
    return g;
}

/// One stream's state.
struct StreamPlan {
    std::uint32_t size = 0;
    bool analysed = false;
    Plan plan;
    std::uint64_t guard_frame = ~0ull;
    Guard guard;
    Axis axis;
    Refuse said = Refuse::None;
};

struct Book {
    std::unordered_map<std::uint64_t, StreamPlan> map;
    std::uint64_t draws = 0, pushed = 0, no_plan = 0, no_axis = 0, refused = 0, twigs_off = 0;
    std::array<std::uint64_t, RefuseKinds> by_reason{};
    std::uint32_t plans_ok = 0, plans_bad = 0;
    bool said = false;
    float last_arm_world = 0.0f, last_x = 0.0f, last_z = 0.0f;

    StreamPlan& Touch(std::uint64_t stream, std::uint32_t size) {
        if (map.size() >= BookMost && map.find(stream) == map.end()) {
            map.clear();
        }
        StreamPlan& e = map[stream];
        if (e.size != size) {
            e = StreamPlan{};
            e.size = size;
        }
        return e;
    }
};

/// The one book (the thread recording draws writes it, the periodic report reads it).
[[nodiscard]] inline Book& Global() {
    static Book book;
    return book;
}

// ---- log lines -----------------------------------------------------------------------------------------------------------------------------

inline void OnceText(char* out, std::size_t size) {
    const Knob& k = KnobOnce();
    std::snprintf(out, size,
                  "Wind sway hang lantern (r112v_lantern-hangs, BB_WIND_HANG_LANTERN): on: only the lantern of a post stream leans (the vertices beyond "
                  "%.2f m of the post's axis, full from %.2f m, held %.2f m under the arm's lower edge, full %.2f m further down; the post, its arm, "
                  "the bridge, chains and hooks stay still); the arm's edge is %.2f m under the highest such vertex%s; the post nearest the camera "
                  "only (its box in the ray traced scene: a second post of the same mesh does not lean); the push is at most %.2f m; knobs "
                  "BB_WIND_HANG_LANTERN_R0, _R1, _ARM, _ARM_Y; 0 = r112s/r112t's post rule",
                  double(k.r0), double(k.r1), double(HookStill), double(HookSpan), double(k.arm),
                  k.arm_y > 0.0f ? " (set by BB_WIND_HANG_LANTERN_ARM_Y)" : "", double(H::PostGuardPush));
}

inline void OffText(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind sway hang lantern (r112v_lantern-hangs): BB_WIND_HANG_LANTERN is asked but the twigs' box keys are off (BB_WIND_TWIGS above 0 "
                  "with BB_WIND=1 and the lean are needed): the post gets no word and nothing moves");
}

/// Appends printf text to a buffer (never past its end).
struct Cat {
    char* out;
    std::size_t size;
    std::size_t n;
    __attribute__((format(printf, 2, 3))) void Add(const char* fmt, ...) {
        if (n + 1 >= size) {
            return;
        }
        va_list args;
        va_start(args, fmt);
        const int w = std::vsnprintf(out + n, size - n, fmt, args);
        va_end(args);
        n += w > 0 ? std::min(static_cast<std::size_t>(w), size - n - 1) : 0;
    }
};

inline void PlanText(std::uint64_t stream, const Plan& p, char* out, std::size_t size) {
    Cat cat{out, size, 0};
    if (!p.ok) {
        cat.Add("Wind sway hang lantern plan (r112v_lantern-hangs): stream 0x%llx: NO PLAN (%s): %u vertices, %u beyond R0 %.2f m; this stream's word gets no "
            "lean",
            static_cast<unsigned long long>(stream), p.why, static_cast<unsigned>(p.verts), static_cast<unsigned>(p.far), double(p.r0));
        return;
    }
    cat.Add("Wind sway hang lantern plan (r112v_lantern-hangs): stream 0x%llx: %u vertices, model y %.2f..%.2f, axis at x %.2f z %.2f; %u within R0 %.2f "
        "m (the pole and the foot), %u beyond it above the foot (y %.2f..%.2f); arm's lower edge y %.2f; %u vertices move (%.1f percent), %u in full, "
        "their y %.2f..%.2f, radius %.2f..%.2f m",
        static_cast<unsigned long long>(stream), static_cast<unsigned>(p.verts), double(p.ymin), double(p.ymax), double(p.cx), double(p.cz),
        static_cast<unsigned>(p.core), double(p.r0), static_cast<unsigned>(p.far), double(p.far_bottom), double(p.far_top), double(p.arm_y),
        static_cast<unsigned>(p.moving), 100.0 * double(p.moving) / double(p.verts), static_cast<unsigned>(p.full), double(p.move_ymin),
        double(p.move_ymax), double(p.move_rmin), double(p.move_rmax));
    cat.Add("; far vertices by 0.1 m down from y %.2f:", double(p.far_top));
    for (const std::uint32_t c : p.far_by_y) {
        cat.Add(" %u", static_cast<unsigned>(c));
    }
    cat.Add("; far vertices by 0.1 m of radius from R0:");
    for (const std::uint32_t c : p.far_by_r) {
        cat.Add(" %u", static_cast<unsigned>(c));
    }
    cat.Add("; vertices within R0 by 0.5 m of height:");
    for (const std::uint32_t c : p.core_by_y) {
        cat.Add(" %u", static_cast<unsigned>(c));
    }
}

inline void GuardText(std::uint64_t stream, const Guard& g, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind sway hang lantern (r112v_lantern-hangs): stream 0x%llx REFUSED (%s): %u boxes of it in the scene (limits %.1f m wide, %.1f m "
                  "tall); the box that decides: x %.2f..%.2f, y %.2f..%.2f, z %.2f..%.2f; it is never pushed",
                  static_cast<unsigned long long>(stream), RefuseName(g.why), static_cast<unsigned>(g.count), double(WideMost), double(TallMost),
                  double(g.box[0]), double(g.box[3]), double(g.box[1]), double(g.box[4]), double(g.box[2]), double(g.box[5]));
}

inline void LineText(const Book& b, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind sway hang lantern (r112v): since the start %llu post draws: %llu given the lantern's word, %llu with no plan (stream not "
                  "readable or no arm), %llu with no box of the stream in the scene, %llu refused (wide %llu, tall %llu, shared %llu), %llu with the "
                  "twigs' keys off; plans %u ok, %u bad; the last arm edge y %.2f, axis x %.2f z %.2f",
                  static_cast<unsigned long long>(b.draws), static_cast<unsigned long long>(b.pushed), static_cast<unsigned long long>(b.no_plan),
                  static_cast<unsigned long long>(b.no_axis), static_cast<unsigned long long>(b.refused),
                  static_cast<unsigned long long>(b.by_reason[static_cast<std::size_t>(Refuse::Wide)]),
                  static_cast<unsigned long long>(b.by_reason[static_cast<std::size_t>(Refuse::Tall)]),
                  static_cast<unsigned long long>(b.by_reason[static_cast<std::size_t>(Refuse::Shared)]),
                  static_cast<unsigned long long>(b.twigs_off), static_cast<unsigned>(b.plans_ok), static_cast<unsigned>(b.plans_bad),
                  double(b.last_arm_world), double(b.last_x), double(b.last_z));
}

} // namespace BbWindLantern
