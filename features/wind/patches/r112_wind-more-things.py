# r112_wind-more-things (.fixed.py, reviewed 2026-11-15): FEATURE patch (wind, order item "wind on
# more things"). Off by default behind BB_WIND_HANG=1 (needs BB_WIND=1, BB_WIND_SWAY above 0 and
# ray tracing).
#
# What it does: hanging things lean downwind with the gusts and ease back, held at their top. No
# swing, no wave: the owner's rule of 2026-11-15 22:58 for the wind ("should not wave but move in
# the direction of the wind and it should be not as fast unless the wind is really blowing"). A
# hanging thing is a skinned camera pass draw (Motion's Kind::Skinned: a bone palette of character
# size) that is no plant, whose position stream a sun shadow pass draws (RtShadow::SunSkinned,
# LampLoneState::Sun), whose skeleton palettes keep the same bytes for 60 frames and never change
# (the game does not move it), and whose vertices span 0.8 to 4 m in world height (its slot's
# base key, r89's, and a top key per slot, filled by the GPU over 8 frames in which its word asks
# for no motion, then read by the CPU). Its sway word gets HangBit (bit 13); the shaders then move
# it by d = w P (dir_x, dir_z) in place of the plant sway: w = smoothstep(clamp((top - y - 0.3 m) /
# 0.9 m, 0, 1)) times the ramp, P >= 0 from a push table per view (bbport_wind_hang.h, Push): the
# squared gust factor followed with a time constant of 0.4 s growing and 1.6 s falling at 4 m/s
# (slower in a weaker wind: times 4 / speed), times 0.15 m x (speed / 4 m/s)^2 x BB_WIND_SWAY.
# Props with 2-8 bones (Motion's SmallSkeleton: likely most lanterns, cages and chains) are not
# Kind::Skinned and are never taken; the log lines say what a place has.
#
# Off: BB_WIND_HANG unset (the default): BbWindHang::KnobOnce().on is false; both emitters emit
# nothing of it (the sway SPIR-V is r89b's, cached under r89b's version), SwayWanted is r89's, the
# sway region is r89's size, WindHangVerdict returns at its first test, no hang word is made. With
# BB_WIND unset nothing of this runs at all. No host shader (host_shaders/) is touched.
#
# Review 2026-11-15 (the draft r112_wind-more-things.py is left as it was). Faults of the draft
# fixed here: (1) the hanging things moved with r89's and r89b's swing and ripple (back and forth
# through rest, waves), against the owner's 22:58 rule: now a downwind push only (never against
# or across the wind, tested), size and speed explicit functions of the wind speed, 0 at no wind;
# (2) with BB_WIND_HANG off every plant vertex still ran the hanging selects and a top key load
# (r89b's SPIR-V changed, its cache version bumped so every sway shader was rebuilt) and the
# region grew by 4 KB: now nothing is emitted or allocated with it off, and BB_WIND_HANG=1's
# shaders have their own cache version (20); (3) WindHangWord read the two keys from mapped GPU
# memory (slow CPU reads) on every hanging draw of every frame: now only while measuring;
# (4) the draft edited bbport_wind_sway.h (Displace, r89's constants), the file r89c rewrites:
# now everything is in bbport_wind_hang.h (HangDisplace is the shaders' rule in C++) and the
# emitters' hook is two blocks; (5) the once line was anchored on r89b's ripple line: now on
# r89's report test, with the push and its times at the wind's speed.
#
# Files: new engine/gpu/shim/bbport_wind_hang.h (knob, layout, keys, Push, HangDisplace, Book,
# Measure, texts) and engine/tests/test_wind_hang.cpp; edits: emit_spirv_special.cpp
# EmitVertexSway and lift_stage.cpp Lift_::VertexSway (the same rule, only with BB_WIND_HANG=1),
# vk_object_motion.cpp (SwayBytes, KeysEnd), vk_rasterizer.h (WindHangVerdict, WindHangWord,
# hang_book, hang_stats, hang_push, hang_frame, hang_filled), vk_rasterizer_effects.cpp
# (WindSwayWord asks WindHangVerdict for a draw that is no plant, resets the top key, returns
# WindHangWord's word; the two functions; the once line and the two lines every 600 frames),
# vk_rt_shadow.h/.cpp (SunSkinned beside LonePlant), vk_pipeline_cache.cpp (SkeletonRead;
# SwayWanted also for a skeleton reader with BB_WIND_HANG=1), vk_pipeline_serialization.cpp
# (HangShaderBinaryVersion 20 for sway shaders built with BB_WIND_HANG=1), engine/gpu/
# CMakeLists.txt and engine/build.sh (wind-hang-test beside wind-sway-test), README.md (a
# BB_WIND_HANG row after BB_WIND_SWAY_SHOW). bbport_wind_sway.h is NOT edited.
# Needs r89 (and r89b's SwayOr in vk_pipeline_serialization.cpp and its README row as anchors);
# revert r112 before reverting r89 or r89b. r89c (foliage lean, drafting): r112 reads none of
# r89b's ripple and none of r89's swing; it needs r89's FillView words (ForwardAt, ToWorldAt,
# WindA, WindC.w, WindD.y-z, WindE.x and WindE.z-w), PackWord's bits 0-12 and 16-23 and WordOn,
# Slots::Take, and these lines staying as they are: in EmitVertexSway `const Id d =
# ...{ddx, zero, ddz, zero}` and `ctx.AddLabel(offer_merge);` (and the r89 names word, region,
# view_index, field, ramp, rx, wy, rz, zero, i, frac, dx, dz, max_along, ddx, ddz before them), the
# lifter's `const u32 d = ComponentsF({ddx, zero, ddz, zero});` and `Open(offer_merge);`, and
# r89b's SwayOr lines in vk_pipeline_serialization.cpp. If r89c changes any of them, check mode
# refuses with the line named. r89c must not use bit 13 of the sway word nor binary version 20
# (a static_assert catches the version).
#
# Use: python -I -X utf8 r112_wind-more-things.fixed.py check | apply | revert
# Root: R112_ROOT, else <tree>. Line ends kept (CRLF in the tree; new files CRLF). apply backs
# the originals up in r112_backup next to this script; revert takes out exactly what apply put in
# (an inserted text is found by itself, so a later patch's text next to it stays; a replaced text
# goes back to the original) and removes the two new files.
import hashlib, os, sys

ROOT = os.environ.get("R112_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
EM = "engine/gpu/shadps4/shader_recompiler/backend/spirv/emit_spirv_special.cpp"
LS = "engine/gpu/shim/lifter/lift_stage.cpp"
OM = RV + "vk_object_motion.cpp"
RH = RV + "vk_rasterizer.h"
RE = RV + "vk_rasterizer_effects.cpp"
TH = RV + "vk_rt_shadow.h"
TC = RV + "vk_rt_shadow.cpp"
PC = RV + "vk_pipeline_cache.cpp"
PS = RV + "vk_pipeline_serialization.cpp"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
RM = "README.md"
NH = "engine/gpu/shim/bbport_wind_hang.h"
NT = "engine/tests/test_wind_hang.cpp"

NEW_FILES = {
NH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r112_wind-more-things): hanging things lean with the wind, held at their top. Only with
// BB_WIND_HANG=1 and the plant sway on (BB_WIND=1, BB_WIND_SWAY above 0, ray tracing for
// RtShadow's stream verdicts).
//
// What hangs: a camera pass draw with a skeleton (a bone palette of character size, Motion's
// Kind::Skinned) of a sway pipeline (with BB_WIND_HANG=1 every motion pipeline whose vertex shader
// reads such a palette, cut-out or not: SkeletonRead in vk_pipeline_cache.cpp) that RtShadow does
// not take for a plant, whose position stream (address and size)
//  - a sun shadow pass draws with a skeleton (RtShadow::SunSkinned, LampLoneState::Sun: the game
//    gives the mesh a sun shadow, so only where a sun shadow pass draws it),
//  - is drawn on StillFrames frames with the same bytes in all its skeleton palettes and never with
//    others (Book: the game does not move it; a character, a body that moved once, cloth the game
//    simulates, a palette the GPU writes or one that is not mapped is "moving" for good while the
//    address holds a mesh of this size), and
//  - spans MinExtent to MaxExtent in world height: its lowest and highest world y as its vertices
//    offered them to the GPU's base key (r89's) and top key (TopAt) while its sway word had a ramp
//    of 0 (no motion) for JudgeFrames frames after it got its slot (Measure).
// Props with 2-8 bones (Motion's SmallSkeleton) are not Kind::Skinned and are never taken.
// Its word has HangBit (HangWord). The shaders then move it in place of the plant sway (both
// emitters; HangDisplace is their rule in C++):
//   d = w P (dir_x, dir_z), w = smoothstep(clamp((top - y - HangStill) / (HangFull - HangStill),
//   0, 1)) times the ramp, P = clamp(push table at the vertex, 0, MaxAlong)
// so its top HangStill m stays and from HangFull m below its top it is pushed downwind in full.
// There is no swing and no wave: d never points against the wind or across it (P >= 0). The push
// table (one per view, GustSamples floats at PushAt, indexed as r89's gust table: the gust that
// passes the vertex, carried downwind at the wind's speed) is filled on the CPU by Push:
//   P(t) = Amp(speed) Y(t), Amp = BB_WIND_SWAY x PushFull x (speed / FullSpeed)^2,
//   Y follows Drive(G) = G^2 (G the gust factor; the wind's push grows with the square of its
//   speed) with the time constant RiseTime while it grows and ReleaseTime while it falls, both
//   times FullSpeed / clamp(speed, SlowestSpeed, FullSpeed),
// so a gust pushes it out quickly and it eases back slowly. CPU twin (BB_WIND_GUSTS 0.5, scale
// 1): at the default 1.5 m/s the push is 0.011-0.052 m (mean 0.024 m), out in 1.07 s, back in
// 4.27 s; at 4 m/s 0.076-0.39 m (mean 0.18 m), out in 0.4 s, back in 1.6 s; at no wind 0. The
// table's samples are GustStep (1 s) apart, which softens the fastest rise a little.
// Pure: no Vulkan; tested by tests/test_wind_hang.cpp.

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <unordered_map>
#include <vector>

#include "bbport_wind.h"
#include "bbport_wind_sway.h"

namespace BbWindHang {

namespace W = BbWindSway;

/// The sway word's bit for a hanging thing: free (PackWord's base slot ends at bit 12, its ramp
/// starts at bit 16).
inline constexpr std::uint32_t HangBit = 1u << 13;
/// Words after r89's region (only with BB_WIND_HANG=1; SwayBytes): BaseSlots top keys, then the
/// push tables, GustSamples floats per frame slot and view.
inline constexpr std::uint32_t TopAt = W::RegionWords;
inline constexpr std::uint32_t PushAt = TopAt + W::BaseSlots;
inline constexpr std::uint32_t PushWords = W::FrameSlots * W::Views * W::GustSamples;
inline constexpr std::uint32_t AllWords = PushAt + PushWords;
inline constexpr std::uint32_t AllBytes = AllWords * 4;
inline constexpr float HangStill = 0.3f; ///< m below the top that stay still
inline constexpr float HangFull = 1.2f;  ///< m below the top from which it moves in full
inline constexpr float HangInv = 1.0f / (HangFull - HangStill);
inline constexpr float PushFull = 0.15f; ///< m of push at FullSpeed, gust 1, BB_WIND_SWAY 1
inline constexpr float FullSpeed = BbWind::MaxSpeed; ///< m/s
inline constexpr float SlowestSpeed = 1.0f;  ///< m/s: a slower wind's times are this one's
inline constexpr double RiseTime = 0.4;      ///< s: the push's time constant growing, at FullSpeed
inline constexpr double ReleaseTime = 1.6;   ///< s: the same falling (easing back)
inline constexpr double PushStep = 0.25;     ///< s of gust time between the follower's samples
inline constexpr double WarmMost = 24.0;     ///< s the follower runs before the first time asked
inline constexpr std::uint32_t GridMost = 360; ///< samples the follower keeps at most
inline constexpr std::uint32_t StillFrames = 60; ///< frames of one palette before it hangs
inline constexpr std::uint64_t JudgeFrames = 8;  ///< frames its keys are offered before reading
inline constexpr float MinExtent = 0.8f, MaxExtent = 4.0f; ///< m of world height it may span
inline constexpr std::size_t BookMost = 8192;  ///< streams known at most
inline constexpr std::uint64_t BookKeep = 600; ///< frames unseen before one may be forgotten

static_assert((W::PackWord(3, 1, 1023, 255) & HangBit) == 0, "HangBit lies in PackWord's fields");
static_assert((HangBit & W::WordOn) == 0);
static_assert(AllBytes == 14336 && TopAt % 4 == 0 && PushAt % 4 == 0);
static_assert(HangFull > HangStill && HangStill >= 0.0f);
static_assert(MinExtent > HangStill && MaxExtent > MinExtent);
static_assert(JudgeFrames > W::FrameSlots, "the GPU is done with the frames read");
static_assert(ReleaseTime > RiseTime && RiseTime > 0.0);
static_assert(double(W::GustSamples - 1) * W::GustStep + WarmMost + 2.0 * PushStep + 1.0 <=
                  double(GridMost) * PushStep,
              "the follower's samples cover a table and its warm-up (or the margin kept)");

/// BB_WIND_HANG: `1` asks for it; it is on only with the plant sway on.
struct Knob {
    bool asked = false;
    bool on = false;
};

[[nodiscard]] inline Knob ParseKnob(const char* hang, bool sway_on) {
    Knob k;
    k.asked = hang != nullptr && hang[0] == '1' && hang[1] == 0;
    k.on = k.asked && sway_on;
    return k;
}

/// Read once, at the first use (the first sway shader or pipeline key, or the first draw).
[[nodiscard]] inline const Knob& KnobOnce() {
    static const Knob knob = ParseKnob(std::getenv("BB_WIND_HANG"), W::KnobOnce().on);
    return knob;
}

/// Bytes of the sway words ObjectMotion makes when the plant sway is on: r89's region, and with
/// BB_WIND_HANG=1 the top keys and push tables after it.
[[nodiscard]] inline std::uint32_t SwayBytes() {
    return KnobOnce().on ? AllBytes : W::RegionBytes;
}

/// The end of the words ObjectMotion sets to ResetKey (from BaseAt): r89's base keys, and with
/// BB_WIND_HANG=1 the top keys.
[[nodiscard]] inline std::uint32_t KeysEnd() {
    return KnobOnce().on ? PushAt : W::RegionWords;
}

/// A world y as a top key, the key of HeightBias - y: the smallest key is the highest y.
[[nodiscard]] inline std::uint32_t TopKey(float y) {
    return std::bit_cast<std::uint32_t>(std::max(W::HeightBias - y, 0.0f));
}

[[nodiscard]] inline float KeyTop(std::uint32_t key) {
    return W::HeightBias - std::bit_cast<float>(key);
}

/// A hanging thing's sway word: r89's word with HangBit.
[[nodiscard]] constexpr std::uint32_t HangWord(std::uint32_t frame_slot, std::uint32_t view,
                                               std::uint32_t slot, std::uint32_t ramp) {
    return W::PackWord(frame_slot, view, slot, ramp) | HangBit;
}

[[nodiscard]] constexpr bool HangOf(std::uint32_t word) {
    return (word & W::WordOn) != 0 && (word & HangBit) != 0;
}

/// The push's amplitude (m) at gust 1: BB_WIND_SWAY `scale` x PushFull x (speed / FullSpeed)^2;
/// 0 at no wind.
[[nodiscard]] inline float Amp(float speed, float scale) {
    const float v = std::isfinite(speed) ? std::clamp(speed, 0.0f, FullSpeed) : 0.0f;
    const float r = v / FullSpeed;
    return scale * PushFull * r * r;
}

/// The push's time constants (s) at a wind speed: growing and falling.
struct Times {
    double rise = RiseTime, release = ReleaseTime;
};

[[nodiscard]] inline Times TimesAt(float speed) {
    const double v = std::isfinite(speed) ? std::clamp(double(speed), double(SlowestSpeed),
                                                       double(FullSpeed))
                                          : double(SlowestSpeed);
    return {RiseTime * FullSpeed / v, ReleaseTime * FullSpeed / v};
}

/// What drives the push: the square of the gust factor (never below 0).
[[nodiscard]] inline float Drive(float gust) {
    const float g = std::max(gust, 0.0f);
    return g * g;
}

/// One step of `dt` s of the follower from `y` toward `x`: exact for a constant x, with the rise
/// time while x is above y and the release time while it is below.
[[nodiscard]] inline float Follow(float y, float x, double dt, const Times& times) {
    const double tau = x > y ? times.rise : times.release;
    return float(double(x) + double(y - x) * std::exp(-dt / tau));
}

/// The push tables. Fill re-anchors the gust time at the view's camera (as r89b's Ripple keeps
/// it: moved by -(camera - anchor) . dir / v, advanced by the wind time since the last fill, v =
/// max(speed, 0.1 m/s) as r89's FillView takes it), so a turning wind turns the field about the
/// camera and nothing jumps. The follower runs on a grid of PushStep s of gust time (each sample
/// depends only on the one before and the gust there); the grid is kept and extended forward from
/// fill to fill (WarmMost s kept before the first time a table asks for). It starts again
/// (WarmMost s or 8 release times, whichever is less, before that time) when a table asks for
/// times before what it kept, or the gusts or the times change.
class Push {
public:
    /// The table of the view with its camera at (cx, cz): GustSamples floats, sample i the push
    /// at gust time GustTime() + (i - GustMid) GustStep, clamped to 0-MaxAlong.
    void Fill(const BbWind::Snapshot& s, float cx, float cz, float gusts, float scale,
              float* table) {
        const double speed = std::isfinite(s.speed) ? std::max(double(s.speed), 0.0) : 0.0;
        const double v = std::max(speed, 0.1);
        if (ready) {
            gust_time -= ((double(cx) - anchor_x) * dir_x + (double(cz) - anchor_z) * dir_z) /
                         gust_speed;
            const double dt = s.time - time;
            if (dt > 0.0 && std::isfinite(dt)) {
                gust_time += dt;
            }
        } else {
            gust_time = s.time - (double(cx) * s.dir_x + double(cz) * s.dir_z) / v;
        }
        anchor_x = cx;
        anchor_z = cz;
        time = s.time;
        dir_x = s.dir_x;
        dir_z = s.dir_z;
        gust_speed = v;
        ready = true;
        const Times times = TimesAt(float(speed));
        amp = Amp(float(speed), scale);
        const double first = gust_time - double(W::GustMid) * W::GustStep;
        const double last = gust_time + double(W::GustSamples - 1 - W::GustMid) * W::GustStep;
        const auto k_first = std::int64_t(std::floor(first / PushStep));
        const auto k_last = std::int64_t(std::ceil(last / PushStep)) + 1;
        Extend(k_first, k_last, gusts, times);
        for (std::uint32_t i = 0; i < W::GustSamples; ++i) {
            const double at = (first + double(i) * W::GustStep) / PushStep - double(k0);
            const auto k = std::size_t(std::clamp(std::floor(at), 0.0, double(grid.size() - 2)));
            const float f = float(std::clamp(at - double(k), 0.0, 1.0));
            const float y = grid[k] + (grid[k + 1] - grid[k]) * f;
            table[i] = std::clamp(amp * y, 0.0f, W::MaxAlong);
        }
        now = table[W::GustMid];
    }

    [[nodiscard]] double GustTime() const {
        return gust_time;
    }

    /// The push (m) at the camera of the last fill.
    [[nodiscard]] float Now() const {
        return now;
    }

    /// How often the follower started again (a few per run are expected).
    [[nodiscard]] std::uint64_t Restarts() const {
        return restarts;
    }

private:
    void Extend(std::int64_t k_first, std::int64_t k_last, float gusts, const Times& times) {
        const bool same = !grid.empty() && gusts == grid_gusts && times.rise == grid_times.rise &&
                          times.release == grid_times.release;
        if (!same || k_first < k0 || k_last - k0 >= std::int64_t(GridMost)) {
            if (same && k_first >= k0) {
                // forward only: keep WarmMost s before k_first, drop the rest
                const std::int64_t keep = k_first - std::int64_t(WarmMost / PushStep);
                if (keep > k0) {
                    grid.erase(grid.begin(), grid.begin() + std::ptrdiff_t(keep - k0));
                    k0 = keep;
                }
            } else {
                const double warm = std::min(WarmMost, 8.0 * times.release);
                k0 = k_first - std::int64_t(std::ceil(warm / PushStep));
                grid.clear();
                grid.push_back(Drive(BbWind::Gust(double(k0) * PushStep, gusts)));
                grid_gusts = gusts;
                grid_times = times;
                ++restarts;
            }
        }
        while (k0 + std::int64_t(grid.size()) <= k_last) {
            const std::int64_t k = k0 + std::int64_t(grid.size());
            const float x = Drive(BbWind::Gust(double(k) * PushStep, gusts));
            grid.push_back(Follow(grid.back(), x, PushStep, times));
        }
    }

    std::vector<float> grid;
    std::int64_t k0 = 0;
    float grid_gusts = 0.0f;
    Times grid_times{};
    double anchor_x = 0.0, anchor_z = 0.0, dir_x = 0.0, dir_z = 0.0, gust_speed = 1.0;
    double gust_time = 0.0, time = 0.0;
    float amp = 0.0f, now = 0.0f;
    std::uint64_t restarts = 0;
    bool ready = false;
};

/// What the shaders do to a vertex of a hanging thing (a word with HangBit; the plant sway's
/// result is computed too and dropped for it): `view` its ViewWords floats (r89's FillView),
/// `push` its push table, `clip` the clip position, `stored_top` its slot's top key, `ramp` the
/// word's ramp / 255. The clip position written back; `key_top` (when not null) the top key the
/// vertex offers (ResetKey: none). Its base key is offered by r89's code, as a plant's.
[[nodiscard]] inline std::array<float, 4> HangDisplace(const float* view, const float* push,
                                                       const std::array<float, 4>& clip,
                                                       std::uint32_t stored_top, float ramp,
                                                       std::uint32_t* key_top = nullptr) {
    const auto dot = [&](std::uint32_t at) {
        return view[at] * clip[0] + view[at + 1] * clip[1] + view[at + 2] * clip[2] +
               view[at + 3] * clip[3];
    };
    const float rx = dot(W::ToWorldAt), rz = dot(W::ToWorldAt + 8);
    const float wy = dot(W::ToWorldAt + 4) + view[W::WindA + 2];
    if (key_top != nullptr) {
        *key_top = std::fabs(wy) < W::FiniteMost ? TopKey(wy) : W::ResetKey;
    }
    const float h = (W::HeightBias - wy) - std::bit_cast<float>(stored_top);
    if (!(std::fabs(h) + std::fabs(rx) + std::fabs(rz) < W::FiniteMost)) {
        return clip;
    }
    const float t = std::clamp((h - HangStill) * HangInv, 0.0f, 1.0f);
    const float w = t * t * (3.0f - 2.0f * t) * ramp;
    const float dx = view[W::WindA], dz = view[W::WindA + 1];
    const float s = rx * dx + rz * dz;
    const float u = std::clamp(view[W::WindD + 1] - s * view[W::WindC + 3], 0.0f,
                               view[W::WindD + 2]);
    const std::uint32_t i = std::min(std::uint32_t(std::floor(u)), W::GustSamples - 2);
    const float f = u - float(i);
    const float p = std::clamp(push[i] + (push[i + 1] - push[i]) * f, 0.0f, view[W::WindE]);
    const float a = w * p;
    const float ddx = a * dx, ddz = a * dz;
    std::array<float, 4> out = clip;
    for (std::uint32_t r = 0; r < 4; ++r) {
        out[r] = clip[r] +
                 (view[W::ForwardAt + r * 4] * ddx + view[W::ForwardAt + r * 4 + 2] * ddz);
    }
    return out;
}

enum class Verdict : std::uint8_t { Waiting, Moving, Still, Unfit };

/// What is known of one position stream drawn with a skeleton by a sun shadow pass.
struct Entry {
    std::uint64_t hash = 0;   ///< its palettes' bytes on the first frame counted
    std::uint32_t size = 0;   ///< bytes of vertices bound at the address (0: not known)
    std::uint32_t frames = 0; ///< frames counted with that hash, up to StillFrames
    std::uint64_t frame = 0;  ///< the last frame counted
    std::uint64_t seen = 0;   ///< the last frame a draw of it was looked at
    std::uint64_t vs = 0;     ///< the vertex shader of its last draw (for the log)
    bool moving = false;      ///< for good: another palette, an unreadable or GPU-written one
    bool started = false;     ///< Measure ran since it was known
    bool judged = false;      ///< its height was read
    bool fits = false;        ///< MinExtent <= top - base <= MaxExtent
    std::uint64_t measure_from = 0; ///< the frame its slot's keys were reset
    double since = 0.0;       ///< wind time it was judged (the ramp's start)
    float base = 0.0f, top = 0.0f; ///< its lowest and highest world y (m) when judged
};

[[nodiscard]] constexpr Verdict VerdictOf(const Entry& e) {
    return e.moving                 ? Verdict::Moving
           : e.frames < StillFrames ? Verdict::Waiting
           : e.judged && !e.fits    ? Verdict::Unfit
                                    : Verdict::Still;
}

/// The streams, by their address. Another size at a known address is another mesh: what was
/// known is forgotten. At BookMost the streams not seen for BookKeep frames go, then all.
class Book {
public:
    /// True (and the stream marked seen) when its verdict is final while its size holds: moving,
    /// or measured outside MinExtent-MaxExtent. Its palettes need not be hashed then.
    bool Settled(std::uint64_t stream, std::uint32_t size, std::uint64_t frame) {
        const auto found = entries.find(stream);
        if (found == entries.end()) {
            return false;
        }
        Entry& e = found->second;
        if (size != 0 && e.size != 0 && e.size != size) {
            return false;
        }
        if (e.moving || (e.judged && !e.fits)) {
            e.seen = frame;
            return true;
        }
        return false;
    }

    /// A draw of the stream on `frame`: `hash` of its skeleton palettes' bytes, `readable` false
    /// when one of them could not be read from guest memory (the GPU writes it, or not mapped).
    Verdict Note(std::uint64_t stream, std::uint32_t size, std::uint64_t hash, bool readable,
                 std::uint64_t frame, std::uint64_t vs) {
        if (stream == 0) {
            return Verdict::Waiting;
        }
        if (entries.size() >= BookMost && entries.find(stream) == entries.end()) {
            std::erase_if(entries, [&](const auto& item) {
                return item.second.seen + BookKeep < frame;
            });
            if (entries.size() >= BookMost) {
                entries.clear();
            }
        }
        Entry& e = entries[stream];
        if (size != 0 && e.size != 0 && e.size != size) {
            e = Entry{};
        }
        if (size != 0) {
            e.size = size;
        }
        e.seen = frame;
        e.vs = vs;
        if (!readable) {
            e.moving = true;
        } else if (e.frames == 0) {
            e.hash = hash;
            e.frames = 1;
            e.frame = frame;
        } else if (hash != e.hash) {
            e.moving = true;
        } else if (frame != e.frame) {
            e.frame = frame;
            e.frames = std::min(e.frames + 1, StillFrames);
        }
        return VerdictOf(e);
    }

    [[nodiscard]] Entry* Find(std::uint64_t stream) {
        const auto found = entries.find(stream);
        return found == entries.end() ? nullptr : &found->second;
    }

    [[nodiscard]] const std::unordered_map<std::uint64_t, Entry>& Entries() const {
        return entries;
    }

private:
    std::unordered_map<std::uint64_t, Entry> entries;
};

struct Measured {
    bool measuring = false; ///< its keys are not read yet: the word asks for no motion (ramp 0)
    bool swing = false;     ///< it fits: the word's ramp is `ramp`
    std::uint32_t ramp = 0;
};

/// A still stream that has its slot (`reset`: the slot's keys were reset now) on `frame`:
/// `base_key` and `top_key` point at its slot's keys as the GPU leaves them (read only while it is
/// measured: the sway words are mapped GPU memory the CPU reads slowly), `time` the wind time.
inline Measured Measure(Entry& e, bool reset, std::uint64_t frame, const std::uint32_t* base_key,
                        const std::uint32_t* top_key, double time) {
    if (reset || !e.started) {
        e.started = true;
        e.judged = false;
        e.fits = false;
        e.measure_from = frame;
    }
    if (!e.judged) {
        if (frame < e.measure_from + JudgeFrames) {
            return {true, false, 0};
        }
        const std::uint32_t base = *base_key, top = *top_key;
        if (base == W::ResetKey || top == W::ResetKey) {
            return {true, false, 0};
        }
        e.base = W::KeyHeight(base);
        e.top = KeyTop(top);
        const float extent = e.top - e.base;
        e.judged = true;
        e.fits = std::isfinite(extent) && extent >= MinExtent && extent <= MaxExtent;
        e.since = time;
    }
    if (!e.fits) {
        return {};
    }
    return {false, true, W::RampByte((time - e.since) / W::RampTime)};
}

/// Counts of skinned draws (of sway pipelines, not plants) for the line every ReportFrames frames.
struct Stats {
    std::uint64_t draws = 0;     ///< looked at
    std::uint64_t no_sun = 0;    ///< no sun shadow pass draws its stream (or not known yet)
    std::uint64_t settled = 0;   ///< moving or out of height for good (not hashed)
    std::uint64_t waiting = 0;   ///< still for fewer than StillFrames frames
    std::uint64_t moving = 0;    ///< found moving now
    std::uint64_t unfit = 0;     ///< measured outside MinExtent-MaxExtent now
    std::uint64_t still = 0;     ///< hanging things (then: measuring, pushed, or lost on the way)
    std::uint64_t measuring = 0; ///< given a word with ramp 0 while their keys fill
    std::uint64_t swung = 0;     ///< given a word that moves them (pushed)
    std::uint64_t ramping = 0;   ///< of those, with a ramp below 255
};

/// The once line (under 300 characters): the push and its times at the wind's speed `speed`.
inline void OnceText(float speed, float scale, char* out, std::size_t size) {
    const Times t = TimesAt(speed);
    std::snprintf(out, size,
                  "Wind sway hang (r112, BB_WIND_HANG=1): hanging things lean downwind, no swing: "
                  "push %.3f m x gust^2 at %.1f m/s (%.3f m at %.0f m/s), out in %.2f s, "
                  "back in %.2f s; skinned, sun-shadowed, one palette %u frames, %.1f-%.1f m "
                  "tall; top %.1f m still, full %.1f m below",
                  double(Amp(speed, scale)), double(speed), double(Amp(FullSpeed, scale)),
                  double(FullSpeed), t.rise, t.release, StillFrames, double(MinExtent),
                  double(MaxExtent), double(HangStill), double(HangFull));
}

/// The counts' line every ReportFrames frames (under 300 characters with counts below 10^7):
/// `push` the push at the camera of the last fill.
inline void LineText(const Stats& s, const Book& book, float push, char* out, std::size_t size) {
    unsigned known = 0, moving = 0, still = 0, swing = 0, short_ = 0, tall = 0;
    for (const auto& item : book.Entries()) {
        const Entry& e = item.second;
        ++known;
        const Verdict v = VerdictOf(e);
        moving += v == Verdict::Moving ? 1u : 0u;
        if (v == Verdict::Still || v == Verdict::Unfit) {
            ++still;
            swing += e.judged && e.fits ? 1u : 0u;
            short_ += e.judged && !e.fits && e.top - e.base < MinExtent ? 1u : 0u;
            tall += e.judged && !e.fits && !(e.top - e.base < MinExtent) ? 1u : 0u;
        }
    }
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(out, size,
                  "Wind sway hang (r112): push %.3f m; %u frames %llu draws: %llu no sun, %llu "
                  "settled, %llu waiting, %llu moving, %llu unfit, %llu still (%llu measured, "
                  "%llu pushed, %llu ramping); streams %u: %u moving, %u still: %u hang, %u "
                  "under %.1f m, %u over %.1f m",
                  double(push), W::ReportFrames, n(s.draws), n(s.no_sun), n(s.settled),
                  n(s.waiting), n(s.moving), n(s.unfit), n(s.still), n(s.measuring), n(s.swung),
                  n(s.ramping), known, moving, still, swing, short_, double(MinExtent), tall,
                  double(MaxExtent));
}

/// The second line: up to three of the tallest meshes that hang and three left out by height,
/// seen within ReportFrames frames of `frame` (vertex shader's low 32 bits, height, top's world y).
inline void MeshesText(const Book& book, std::uint64_t frame, char* out, std::size_t size) {
    std::array<const Entry*, 3> hang{}, left{};
    // the list stays sorted by height, tallest first; a taller one pushes the rest down
    const auto keep = [](std::array<const Entry*, 3>& list, const Entry* e) {
        for (auto& slot : list) {
            if (slot == nullptr || e->top - e->base > slot->top - slot->base) {
                std::swap(slot, e);
                if (e == nullptr) {
                    return;
                }
            }
        }
    };
    for (const auto& item : book.Entries()) {
        const Entry& e = item.second;
        if (!e.judged || e.moving || e.seen + W::ReportFrames < frame) {
            continue;
        }
        keep(e.fits ? hang : left, &e);
    }
    int at = std::snprintf(out, size, "Wind sway hang (r112) meshes: hang");
    const auto add = [&](const std::array<const Entry*, 3>& list) {
        bool any = false;
        for (const Entry* e : list) {
            if (e == nullptr || at < 0 || std::size_t(at) >= size) {
                continue;
            }
            any = true;
            at += std::snprintf(out + at, size - std::size_t(at), " vs %08llx %.2f m (top y %.1f)",
                                static_cast<unsigned long long>(e->vs & 0xffffffffull),
                                double(e->top - e->base), double(e->top));
        }
        if (!any && at >= 0 && std::size_t(at) < size) {
            at += std::snprintf(out + at, size - std::size_t(at), " none");
        }
    };
    add(hang);
    if (at >= 0 && std::size_t(at) < size) {
        at += std::snprintf(out + at, size - std::size_t(at), "; left out by height");
    }
    add(left);
}

} // namespace BbWindHang
''',
NT: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112_wind-more-things): the hanging things' knob, sway word, push (gpu/shim/
// bbport_wind_hang.h: Amp, TimesAt, Follow, Push), the shaders' hanging rule in C++
// (HangDisplace), the book, the measure and the log texts.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

#include "gpu/shim/bbport_wind_hang.h"

namespace H = BbWindHang;
namespace W = BbWindSway;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

BbWind::Snapshot Wind(double time, float speed, float deg) {
    BbWind::Snapshot s;
    s.on = true;
    s.time = time;
    const auto dir = BbWind::DirectionXZ(deg);
    s.dir_x = dir[0];
    s.dir_z = dir[1];
    s.speed = speed;
    return s;
}

// A view whose clip position is the world point relative to a camera at (0, cam_y, 0): the
// clip-to-world rows and F are the identity on x, y and z.
std::array<float, W::ViewWords> View(float cam_y, const BbWind::Snapshot& s) {
    W::Camera cam;
    for (int r = 0; r < 3; ++r) {
        cam.forward[r * 4 + r] = 1.0f;
        cam.to_world[r * 4 + r] = 1.0f;
    }
    cam.y = cam_y;
    std::array<float, W::ViewWords> view{};
    W::FillView(cam, s, 0.5f, 1.0f, view.data());
    return view;
}

std::array<float, 4> Clip(float x, float world_y, float z) {
    return {x, world_y - 1.0f, z, 1.0f}; // camera at y 1
}

bool Same(const std::array<float, 4>& a, const std::array<float, 4>& b) {
    return std::memcmp(a.data(), b.data(), sizeof(a)) == 0;
}

// The push at a still camera over `seconds` of wind at `speed`, 30 frames a second.
struct Run {
    float most = 0.0f, mean = 0.0f, least = 1e9f, step99 = 0.0f;
};

Run PushRun(float speed, double seconds) {
    H::Push push;
    std::array<float, W::GustSamples> table{};
    Run run;
    double sum = 0.0;
    std::vector<float> steps;
    float before = 0.0f;
    const int frames = int(seconds * 30.0);
    for (int n = 0; n < frames; ++n) {
        push.Fill(Wind(n / 30.0, speed, 225.0f), 300.0f, -120.0f, 0.5f, 1.0f, table.data());
        const float p = table[W::GustMid];
        run.most = std::max(run.most, p);
        run.least = std::min(run.least, p);
        sum += p;
        if (n > 0) {
            steps.push_back(std::fabs(p - before));
        }
        before = p;
    }
    run.mean = float(sum / frames);
    std::sort(steps.begin(), steps.end());
    run.step99 = steps.empty() ? 0.0f : steps[steps.size() * 99 / 100];
    return run;
}
} // namespace

int main() {
    // The knob: `1` asks; on only with the plant sway on.
    {
        Expect(H::ParseKnob("1", true).on && H::ParseKnob("1", true).asked, "1 with the sway: on");
        Expect(!H::ParseKnob("1", false).on && H::ParseKnob("1", false).asked,
               "1 without the sway: off");
        Expect(!H::ParseKnob("0", true).on && !H::ParseKnob(nullptr, true).on &&
                   !H::ParseKnob("", true).on && !H::ParseKnob("10", true).on &&
                   !H::ParseKnob("2", true).on,
               "anything else: off");
    }

    // The word and the layout.
    {
        const std::uint32_t word = H::HangWord(3, 1, 1023, 255);
        const auto u = W::Unpack(word);
        Expect(H::HangOf(word) && u.on && u.frame_slot == 3 && u.view == 1 &&
                   u.base_slot == 1023 && u.ramp == 255,
               "HangWord is PackWord's word with HangBit");
        Expect(!H::HangOf(W::PackWord(3, 1, 1023, 255)) && !H::HangOf(0) &&
                   !H::HangOf(H::HangBit),
               "no HangBit, or no WordOn: not hanging");
        Expect(H::TopAt == W::RegionWords && H::PushAt == H::TopAt + W::BaseSlots &&
                   H::AllWords == H::PushAt + W::FrameSlots * W::Views * W::GustSamples &&
                   H::AllBytes == H::AllWords * 4,
               "top keys, then push tables, after r89's region");
    }

    // The top keys: the smallest is the highest y; KeyTop takes it back.
    {
        Expect(H::TopKey(3.0f) < H::TopKey(2.0f) && H::TopKey(-5.0f) > H::TopKey(-4.0f),
               "a higher y has a smaller key");
        Expect(H::TopKey(-W::FiniteMost) < W::ResetKey && H::TopKey(W::FiniteMost) < W::ResetKey,
               "ResetKey is above every key a vertex offers");
        bool back = true;
        for (const float y : {-120.5f, -1.0f, 0.0f, 0.25f, 7.0f, 300.0f}) {
            back = back && std::fabs(H::KeyTop(H::TopKey(y)) - y) < 2e-3f;
        }
        Expect(back, "KeyTop(TopKey(y)) is y");
    }

    // The push's size and speed are functions of the wind's speed; 0 at no wind.
    {
        Expect(H::Amp(0.0f, 1.0f) == 0.0f && H::Amp(-1.0f, 1.0f) == 0.0f &&
                   H::Amp(NAN, 1.0f) == 0.0f,
               "no wind: no push");
        Expect(H::Amp(1.5f, 1.0f) < H::Amp(2.5f, 1.0f) && H::Amp(2.5f, 1.0f) < H::Amp(4.0f, 1.0f) &&
                   std::fabs(H::Amp(4.0f, 1.0f) - H::PushFull) < 1e-6f &&
                   H::Amp(9.0f, 1.0f) == H::Amp(4.0f, 1.0f),
               "the push grows with the square of the speed, to PushFull at 4 m/s");
        Expect(H::Amp(BbWind::DefaultSpeed, 1.0f) < 0.25f * H::PushFull,
               "at the default speed under a quarter of it");
        const H::Times slow = H::TimesAt(1.5f), fast = H::TimesAt(4.0f);
        Expect(slow.rise > fast.rise && slow.release > fast.release &&
                   fast.rise == H::RiseTime && fast.release == H::ReleaseTime,
               "a weaker wind moves it more slowly");
        Expect(slow.rise < slow.release && fast.rise < fast.release, "out quickly, back slowly");
        // a step of the drive up, and one down, for one second each
        float up = 1.0f, down = 4.0f;
        for (int i = 0; i < 4; ++i) {
            up = H::Follow(up, 4.0f, H::PushStep, slow);
            down = H::Follow(down, 1.0f, H::PushStep, slow);
        }
        Expect((up - 1.0f) > 2.0f * (4.0f - down), "after 1 s: out much further than back");
        Expect(H::Drive(-2.0f) == 0.0f && H::Drive(1.5f) == 2.25f, "drive: the gust squared");
    }

    // The push over time: never below 0, calm at the default wind, large and faster at 4 m/s.
    {
        const Run none = PushRun(0.0f, 60.0);
        const Run calm = PushRun(BbWind::DefaultSpeed, 300.0);
        const Run strong = PushRun(4.0f, 300.0);
        Expect(none.most == 0.0f, "no wind: 0 at all times");
        Expect(calm.least >= 0.0f && strong.least >= 0.0f, "never below 0");
        Expect(calm.most < 0.08f && calm.mean < 0.04f, "default wind: under 8 cm, mean under 4 cm");
        Expect(strong.most > 0.25f && strong.most <= W::MaxAlong, "4 m/s: over 25 cm, held");
        Expect(strong.step99 > 4.0f * calm.step99, "4 m/s: moves faster than the default");
    }

    // A kept follower gives the tables a fresh one gives.
    {
        H::Push kept;
        std::array<float, W::GustSamples> a{}, b{};
        for (int n = 0; n < 2000; ++n) {
            kept.Fill(Wind(n / 60.0, 2.5f, 40.0f), 5.0f, 7.0f, 0.5f, 1.0f, a.data());
        }
        H::Push fresh;
        fresh.Fill(Wind(1999 / 60.0, 2.5f, 40.0f), 5.0f, 7.0f, 0.5f, 1.0f, b.data());
        Expect(std::fabs(fresh.GustTime() - kept.GustTime()) < 1e-9, "the gust time kept");
        float most = 0.0f;
        for (std::uint32_t i = 0; i < W::GustSamples; ++i) {
            most = std::max(most, std::fabs(a[i] - b[i]));
        }
        Expect(most < 1e-4f, "kept and fresh tables agree");
        Expect(kept.Restarts() == 1, "a steady wind: the follower started once");
    }

    // The hanging rule: pushed downwind, held at the top.
    {
        const BbWind::Snapshot s = Wind(37.0, 2.5f, 0.0f);
        const auto view = View(1.0f, s);
        std::array<float, W::GustSamples> push{};
        push.fill(0.2f);
        const std::uint32_t top = H::TopKey(3.0f); // the top at world y 3
        const auto hung = [&](float world_y, float ramp) {
            return H::HangDisplace(view.data(), push.data(), Clip(4.0f, world_y, 2.0f), top, ramp);
        };
        const auto moved = [&](float world_y) {
            const auto out = hung(world_y, 1.0f);
            const auto in = Clip(4.0f, world_y, 2.0f);
            return std::hypot(double(out[0]) - in[0], double(out[2]) - in[2]);
        };
        Expect(Same(hung(3.0f, 1.0f), Clip(4.0f, 3.0f, 2.0f)), "the top stays");
        Expect(Same(hung(3.0f - 0.25f, 1.0f), Clip(4.0f, 2.75f, 2.0f)), "HangStill below stays");
        Expect(Same(hung(1.0f, 0.0f), Clip(4.0f, 1.0f, 2.0f)), "ramp 0: unchanged");
        Expect(std::fabs(moved(1.0f) - 0.2) < 1e-6 && std::fabs(moved(-1.0f) - 0.2) < 1e-6,
               "from HangFull below the top: the push in full");
        const float t = (1.0f - H::HangStill) * H::HangInv;
        Expect(std::fabs(moved(2.0f) / 0.2 - double(t * t * (3.0f - 2.0f * t))) < 1e-4,
               "1 m below the top: the smoothstep's share");
        Expect(hung(1.0f, 1.0f)[1] == Clip(4.0f, 1.0f, 2.0f)[1], "horizontal");
        Expect(Same(H::HangDisplace(view.data(), push.data(), Clip(4.0f, 1.0f, 2.0f),
                                    W::ResetKey, 1.0f),
                    Clip(4.0f, 1.0f, 2.0f)),
               "no top key yet: unchanged");
        std::uint32_t key_top = 0;
        (void)H::HangDisplace(view.data(), push.data(), Clip(4.0f, 2.0f, 2.0f), top, 1.0f,
                              &key_top);
        Expect(key_top == H::TopKey(2.0f), "a hanging vertex offers its top key");
    }

    // The owner's rule (2026-11-15 22:58): a push along the wind, never against it and never
    // across it, at any speed, gust, direction, place and time.
    {
        std::mt19937 rng(112);
        std::uniform_real_distribution<float> unit(0.0f, 1.0f);
        H::Push push;
        std::array<float, W::GustSamples> table{};
        double against = 0.0, across = 0.0;
        for (int n = 0; n < 3000; ++n) {
            const float speed = 4.0f * unit(rng);
            const float deg = 360.0f * unit(rng);
            const BbWind::Snapshot s = Wind(n * 0.37, speed, deg);
            const auto view = View(1.0f, s);
            push.Fill(s, 0.0f, 0.0f, unit(rng), 3.0f * unit(rng), table.data());
            for (int v = 0; v < 8; ++v) {
                const auto in = Clip(80.0f * unit(rng) - 40.0f, 4.0f * unit(rng) - 1.0f,
                                     80.0f * unit(rng) - 40.0f);
                const auto out = H::HangDisplace(view.data(), table.data(), in, H::TopKey(3.0f),
                                                 unit(rng));
                const double mx = double(out[0]) - in[0], mz = double(out[2]) - in[2];
                against = std::min(against, mx * s.dir_x + mz * s.dir_z);
                across = std::max(across, std::fabs(mz * s.dir_x - mx * s.dir_z));
            }
        }
        Expect(against > -1e-5, "the along-wind part is never below 0 (float rounding aside)");
        Expect(across < 1e-5, "nothing across the wind");
    }

    // The book: one palette for StillFrames frames is still; another one is moving for good.
    {
        H::Book book;
        H::Verdict v = H::Verdict::Moving;
        for (std::uint32_t i = 0; i + 1 < H::StillFrames; ++i) {
            v = book.Note(0x1000, 4096, 77, true, 100 + i, 0xabc);
            if (v != H::Verdict::Waiting) {
                break;
            }
        }
        Expect(v == H::Verdict::Waiting, "fewer than StillFrames frames: waiting");
        Expect(book.Note(0x1000, 4096, 77, true, 100 + H::StillFrames - 1, 0xabc) ==
                   H::Verdict::Still,
               "StillFrames frames of one palette: still");
        Expect(book.Note(0x1000, 4096, 77, true, 100 + H::StillFrames - 1, 0xabc) ==
                   H::Verdict::Still,
               "a second draw of the frame with the same palette: still");
        Expect(!book.Settled(0x1000, 4096, 200), "still is not settled (its palette is watched)");
        Expect(book.Note(0x1000, 4096, 78, true, 300, 0xabc) == H::Verdict::Moving,
               "another palette: moving");
        Expect(book.Note(0x1000, 4096, 77, true, 301, 0xabc) == H::Verdict::Moving,
               "moving for good");
        Expect(book.Settled(0x1000, 4096, 302) && book.Settled(0x1000, 0, 302),
               "moving is settled");
        Expect(!book.Settled(0x1000, 8192, 303) &&
                   book.Note(0x1000, 8192, 77, true, 303, 0xabc) == H::Verdict::Waiting,
               "another size at the address: another mesh, known again from the start");
        Expect(book.Note(0x2000, 64, 1, false, 1, 0) == H::Verdict::Moving,
               "a palette that cannot be read: moving");
        Expect(book.Note(0x3000, 64, 5, true, 1, 0) == H::Verdict::Waiting &&
                   book.Note(0x3000, 64, 6, true, 1, 0) == H::Verdict::Moving,
               "two palettes in one frame: moving");
        Expect(book.Note(0, 64, 5, true, 1, 0) == H::Verdict::Waiting && book.Find(0) == nullptr,
               "no stream: nothing kept");
        H::Verdict gaps = H::Verdict::Waiting;
        for (std::uint32_t i = 0; i < H::StillFrames; ++i) {
            gaps = book.Note(0x4000, 64, 9, true, 1000 + 7 * i, 0);
        }
        Expect(gaps == H::Verdict::Still, "frames need not follow each other");
    }

    // Measure: no motion while the keys fill, then the height decides; the ramp from 0. The keys
    // are read only while it is measured (null pointers after that).
    {
        H::Entry e;
        std::uint32_t base = W::ResetKey, top = W::ResetKey, unset = W::ResetKey;
        Expect(H::Measure(e, true, 1000, &base, &top, 10.0).measuring, "just reset: measuring");
        base = W::HeightKey(1.0f);
        top = H::TopKey(3.0f);
        Expect(H::Measure(e, false, 1000 + H::JudgeFrames - 1, &base, &top, 10.1).measuring,
               "before JudgeFrames frames: measuring");
        Expect(H::Measure(e, false, 1000 + H::JudgeFrames, &unset, &top, 10.1).measuring,
               "a key still unset: measuring");
        const H::Measured m = H::Measure(e, false, 1000 + H::JudgeFrames, &base, &top, 10.2);
        Expect(!m.measuring && m.swing && m.ramp == 0 && e.judged && e.fits &&
                   std::fabs(e.top - e.base - 2.0f) < 2e-3f,
               "2 m tall: it hangs, from a ramp of 0");
        const H::Measured half =
            H::Measure(e, false, 2000, nullptr, nullptr, 10.2 + 0.5 * W::RampTime);
        Expect(half.swing && half.ramp > 120 && half.ramp < 136,
               "judged: the keys are not read again; half the ramp time: half");
        Expect(H::Measure(e, false, 3000, nullptr, nullptr, 20.0).ramp == 255, "then in full");
        Expect(H::Measure(e, true, 3001, &unset, &unset, 20.0).measuring && !e.judged,
               "its slot reset: measured again");
        std::uint32_t b0 = W::HeightKey(0.0f), t05 = H::TopKey(0.5f), t6 = H::TopKey(6.0f);
        H::Entry low;
        (void)H::Measure(low, true, 0, &unset, &unset, 0.0);
        const H::Measured l = H::Measure(low, false, H::JudgeFrames, &b0, &t05, 1.0);
        Expect(!l.measuring && !l.swing && low.judged && !low.fits, "0.5 m tall: left out");
        H::Entry tall;
        (void)H::Measure(tall, false, 0, &unset, &unset, 0.0);
        const H::Measured t = H::Measure(tall, false, H::JudgeFrames, &b0, &t6, 1.0);
        Expect(!t.swing && tall.judged && !tall.fits, "6 m tall: left out");
        tall.frames = H::StillFrames;
        Expect(H::VerdictOf(tall) == H::Verdict::Unfit, "measured out of height: unfit");
    }

    // The book's cap: streams not seen for BookKeep frames go first.
    {
        H::Book book;
        for (std::uint64_t i = 1; i <= H::BookMost; ++i) {
            (void)book.Note(i * 16, 64, 1, true, 5, 0);
        }
        Expect(book.Entries().size() == H::BookMost, "the book full");
        (void)book.Note(0x7777770, 64, 1, true, 5 + H::BookKeep + 1, 0);
        Expect(book.Entries().size() == 1 && book.Find(0x7777770) != nullptr,
               "the unseen went, the new one is kept");
    }

    // The log's texts stay under the slot runner's 300 characters.
    {
        char text[512];
        H::OnceText(BbWind::DefaultSpeed, W::MaxScale, text, sizeof(text));
        Expect(std::strlen(text) < 300 && std::strncmp(text, "Wind sway hang (r112", 20) == 0,
               "the once line");
        H::Stats s;
        s.draws = s.no_sun = s.settled = s.waiting = s.moving = s.unfit = s.still = s.measuring =
            s.swung = s.ramping = 9999999;
        H::Book book;
        const float heights[8] = {0.5f, 1.0f, 1.5f, 2.0f, 2.5f, 3.0f, 3.5f, 5.0f};
        for (std::uint64_t i = 1; i <= 8; ++i) {
            for (std::uint32_t f = 0; f < H::StillFrames; ++f) {
                (void)book.Note(i * 16, 64, 1, true, 10 + f, 0x12345678abcdull);
            }
            H::Entry* e = book.Find(i * 16);
            std::uint32_t unset = W::ResetKey;
            std::uint32_t base = W::HeightKey(-100.0f + float(i));
            std::uint32_t top = H::TopKey(-100.0f + float(i) + heights[i - 1]);
            (void)H::Measure(*e, true, 10, &unset, &unset, 0.0);
            (void)H::Measure(*e, false, 10 + H::JudgeFrames, &base, &top, 1.0);
        }
        H::LineText(s, book, W::MaxAlong, text, sizeof(text));
        Expect(std::strlen(text) < 300 && std::strncmp(text, "Wind sway hang (r112)", 21) == 0,
               "the counts' line");
        H::MeshesText(book, 10 + H::StillFrames, text, sizeof(text));
        Expect(std::strlen(text) < 300 &&
                   std::strstr(text, "hang vs 5678abcd 3.50 m (top y -89.5) vs 5678abcd 3.00 m") !=
                       nullptr &&
                   std::strstr(text, "left out by height vs 5678abcd 5.00 m (top y -87.0) vs "
                                     "5678abcd 0.50 m") != nullptr,
               "the meshes' line: tallest first");
        H::Book none;
        H::MeshesText(none, 0, text, sizeof(text));
        Expect(std::strcmp(text, "Wind sway hang (r112) meshes: hang none; left out by height "
                                 "none") == 0,
               "the meshes' line with none");
    }

    if (failures != 0) {
        std::printf("wind-hang-test: %d FAILED\n", failures);
        return 1;
    }
    std::printf("wind-hang-test: ok\n");
    return 0;
}
''',
}

ROW = ("| `BB_WIND_HANG` | Hanging things lean with the wind: `1` turns it on (it needs `BB_WIND=1`, "
"`BB_WIND_SWAY` above 0 and ray tracing, `effect_ray_tracing`); unset or any other text is off. A hanging "
"thing is a mesh drawn with a skeleton (a bone palette of character size; props with 2 to 8 bones are not "
"taken) that a sun shadow pass also draws (plants have no sun shadow and sway as `BB_WIND_SWAY` says), "
"whose palettes keep the same bytes over 60 frames and never change (the game does not move it: "
"characters, a body that moved, cloth the game moves itself and palettes the GPU writes never count while "
"their vertices keep that address), and whose vertices span 0.8 to 4 m in height (read from the GPU over "
"its slot's first 8 frames, in which it does not move). It is pushed downwind only, never against the "
"wind or across it, with no swing and no wave: by w P, w = smoothstep(clamp((top - y - 0.3 m) / 0.9 m, "
"0, 1)) (top: the highest point of its mesh; its top 0.3 m stays, from 1.2 m below its top it moves in "
"full), coming in over 1 s. P follows the square of the gust factor at the mesh (the gusts travel "
"downwind at the wind's speed), growing with a time constant of 0.4 s and easing back with one of 1.6 s "
"at 4 m/s (both times 4 m/s over the speed, at most that of 1 m/s), times 0.15 m x (speed / 4 m/s)^2 x "
"`BB_WIND_SWAY`, held to 0.4 m: at the default 1.5 m/s and gusts 0.5 about 0.01-0.05 m, slow; at 4 m/s "
"about 0.08-0.39 m (estimates from a CPU copy of the rule); nothing at no wind. Limits: the game's own sun "
"shadow of it does not move; a still standing figure 0.8 to 4 m tall that passes these rules would lean at "
"its lower part; vertices drawn with two palettes in one frame count as moving. The log says once that it "
"is on, with the push and its times at the wind's speed (`Wind sway hang (r112, BB_WIND_HANG=1)`), and "
"every 600 frames gives the push at the camera, counts the draws and meshes by verdict and names up to "
"three meshes that hang and three left out by their height (`Wind sway hang (r112)` lines). Cost: nothing "
"with it unset (no code is added to the sway shaders, no memory). On: every motion pipeline with a "
"skeleton gets the sway code (built once more; sway shaders have their own cache version with it on), "
"whose draws pay a load and a test per vertex; a plant vertex pays about 25 operations and 3 loads more, "
"a hanging vertex the sway's work; on the CPU a hash of the palettes of each draw of a sun-shadowed mesh "
"until it is known as moving or out of height (then one lookup), and a push table per view a frame while "
"something hangs; 6 KB more sway words; an estimate, not measured | unset |\n")

# Edits: ("ins", anchor, before, after): the anchor stays, `before` goes in front of it, `after`
# behind it; ("rep", old, new): `old` (found once, `new` absent) becomes `new`.
EDITS = {
EM: [
("ins", '#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)\n', "",
        '#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)\n'),
("rep", "    const Id d = ctx.OpCompositeConstruct(ctx.F32[4], std::array<Id, 4>{ddx, zero, ddz, zero});\n",
r"""    // bbport (r112_wind-more-things): with BB_WIND_HANG=1 (read once; such sway code has its own
    // shader cache version) a word with BbWindHang::HangBit is a hanging thing's: in place of the
    // plant sway above it is pushed downwind only, d = w P (dx, dz), w the smoothstep of
    // (top - y - HangStill) / (HangFull - HangStill) times the ramp, P its view's push table at the
    // vertex (BbWindHang::HangDisplace is this code in C++). Off: nothing of it is emitted.
    const bool hang_on = BbWindHang::KnobOnce().on;
    Id hang{}, top_ptr{}, stored_top{};
    Id ddx_all = ddx, ddz_all = ddz;
    if (hang_on) {
        namespace H = BbWindHang;
        hang = ctx.OpINotEqual(bool_type,
                               ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(H::HangBit)),
                               ctx.u32_zero_value);
        top_ptr = ctx.OpConvertUToPtr(u32_ptr, scaled(at(region, u64(H::TopAt) * 4u),
                                                      field(3u, 10u), 4u));
        stored_top = ctx.OpLoad(u32_type, top_ptr, spv::MemoryAccessMask::Aligned, 4u);
        const Id hh = sub(sub(f(W::HeightBias), wy), ctx.OpBitcast(f32_type, stored_top));
        const Id hfin = ctx.OpFOrdLessThan(
            bool_type,
            add(add(ctx.OpFAbs(f32_type, hh), ctx.OpFAbs(f32_type, rx)), ctx.OpFAbs(f32_type, rz)),
            f(W::FiniteMost));
        const Id ht =
            ctx.OpFClamp(f32_type, mul(sub(hh, f(H::HangStill)), f(H::HangInv)), zero, f(1.0f));
        const Id hw = mul(mul(mul(ht, ht), sub(f(3.0f), mul(f(2.0f), ht))), ramp);
        const Id push = scaled(
            at(region, u64(H::PushAt) * 4u),
            ctx.OpIAdd(u32_type, ctx.OpIMul(u32_type, view_index, ctx.ConstU32(W::GustSamples)), i),
            4u);
        const Id p0 = ctx.OpLoad(f32_type, ctx.OpConvertUToPtr(f32_ptr, push),
                                 spv::MemoryAccessMask::Aligned, 4u);
        const Id p1 = ctx.OpLoad(f32_type, ctx.OpConvertUToPtr(f32_ptr, at(push, 4u)),
                                 spv::MemoryAccessMask::Aligned, 4u);
        const Id a =
            mul(hw, ctx.OpFClamp(f32_type, add(p0, mul(sub(p1, p0), frac)), zero, max_along));
        ddx_all = ctx.OpSelect(f32_type, hang, ctx.OpSelect(f32_type, hfin, mul(a, dx), zero), ddx);
        ddz_all = ctx.OpSelect(f32_type, hang, ctx.OpSelect(f32_type, hfin, mul(a, dz), zero), ddz);
    }
    const Id d =
        ctx.OpCompositeConstruct(ctx.F32[4], std::array<Id, 4>{ddx_all, zero, ddz_all, zero});
"""),
("ins", "    ctx.AddLabel(offer_merge);\n", "",
r"""    if (hang_on) { // bbport (r112_wind-more-things): a hanging thing also offers its top: the key
        // of HeightBias - y to its slot at BbWindHang::TopAt (an atomic minimum, only when lower)
        const Id key_top =
            ctx.OpBitcast(u32_type, ctx.OpFMax(f32_type, sub(f(W::HeightBias), wy), zero));
        const Id offer_top = ctx.OpLogicalAnd(
            bool_type, hang,
            ctx.OpLogicalAnd(
                bool_type,
                ctx.OpFOrdLessThan(bool_type, ctx.OpFAbs(f32_type, wy), f(W::FiniteMost)),
                ctx.OpULessThan(bool_type, key_top, stored_top)));
        const Id top_label = ctx.OpLabel();
        const Id top_merge = ctx.OpLabel();
        ctx.OpSelectionMerge(top_merge, spv::SelectionControlMask::MaskNone);
        ctx.OpBranchConditional(offer_top, top_label, top_merge);
        ctx.AddLabel(top_label);
        ctx.OpAtomicUMin(u32_type, top_ptr, ctx.ConstU32(static_cast<u32>(spv::Scope::Device)),
                         ctx.u32_zero_value, key_top);
        ctx.OpBranch(top_merge);
        ctx.AddLabel(top_merge);
    }
"""),
],
LS: [
("ins", '#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)\n', "",
        '#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)\n'),
("rep", "    const u32 d = ComponentsF({ddx, zero, ddz, zero});\n",
r"""    // bbport (r112_wind-more-things): with BB_WIND_HANG=1 a hanging thing (BbWindHang::HangBit) is pushed downwind
    // only, as the recompiler's EmitVertexSway (BbWindHang::HangDisplace in C++). Off: nothing of it is emitted.
    const bool hang_on = BbWindHang::KnobOnce().on;
    u32 hang = 0, top_ptr = 0, stored_top = 0;
    u32 ddx_all = ddx, ddz_all = ddz;
    if (hang_on) {
        namespace H = BbWindHang;
        hang = ICmp(O(spv::Op::OpINotEqual), IOp(O(spv::Op::OpBitwiseAnd), word, CU(H::HangBit)), CU(0));
        top_ptr = Emit(O(spv::Op::OpConvertUToPtr), ptr_u32, Ty::None, {scaled(at(region, u64(H::TopAt) * 4u), field(3, 10), 4)});
        stored_top = Emit(O(spv::Op::OpLoad), t_u32, Ty::U32, {top_ptr, aligned, 4}, 6);
        const u32 hh = FSub(FSub(CF(W::HeightBias), wy), Emit(O(spv::Op::OpBitcast), t_f32, Ty::F32, {stored_top}));
        const u32 hfin = FCmp(O(spv::Op::OpFOrdLessThan), FAdd(FAdd(abs_f(hh), abs_f(rx)), abs_f(rz)), CF(W::FiniteMost));
        const u32 ht = clamp_f(FMul(FSub(hh, CF(H::HangStill)), CF(H::HangInv)), zero, CF(1.0f));
        const u32 hw = FMul(FMul(FMul(ht, ht), FSub(CF(3.0f), FMul(CF(2.0f), ht))), ramp);
        const u32 push = scaled(at(region, u64(H::PushAt) * 4u), IOp(O(spv::Op::OpIAdd), IOp(O(spv::Op::OpIMul), view_index, CU(W::GustSamples)), i), 4);
        const u32 p0 = Emit(O(spv::Op::OpLoad), t_f32, Ty::F32, {Emit(O(spv::Op::OpConvertUToPtr), ptr_f32, Ty::None, {push}), aligned, 4}, 6);
        const u32 p1 = Emit(O(spv::Op::OpLoad), t_f32, Ty::F32, {Emit(O(spv::Op::OpConvertUToPtr), ptr_f32, Ty::None, {at(push, 4)}), aligned, 4}, 6);
        const u32 a = FMul(hw, clamp_f(FAdd(p0, FMul(FSub(p1, p0), frac)), zero, max_along));
        ddx_all = Select(hang, Select(hfin, FMul(a, dx), zero), ddx);
        ddz_all = Select(hang, Select(hfin, FMul(a, dz), zero), ddz);
    }
    const u32 d = ComponentsF({ddx_all, zero, ddz_all, zero});
"""),
("ins", "    Open(offer_merge);\n", "",
r"""    if (hang_on) { // bbport (r112_wind-more-things): a hanging thing also offers its top (BbWindHang::TopAt)
        const u32 key_top = Emit(O(spv::Op::OpBitcast), t_u32, Ty::U32, {Ext(GLSLstd450FMax, t_f32, Ty::F32, {FSub(CF(W::HeightBias), wy), zero})});
        const u32 offer_top = Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool,
                                   {hang, Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool,
                                               {FCmp(O(spv::Op::OpFOrdLessThan), abs_f(wy), CF(W::FiniteMost)), ICmp(O(spv::Op::OpULessThan), key_top, stored_top)})});
        const u32 top_label = m.NewId();
        const u32 top_merge = m.NewId();
        EmitVoid(O(spv::Op::OpSelectionMerge), {top_merge, 0}, 2);
        EmitVoid(O(spv::Op::OpBranchConditional), {offer_top, top_label, top_merge});
        Open(top_label);
        const u32 prev_top = Emit(O(spv::Op::OpAtomicUMin), t_u32, Ty::U32, {top_ptr, CU(u32(spv::Scope::Device)), CU(0), key_top});
        nodes[m.NodeOf(prev_top)].effect = true;
        EmitVoid(O(spv::Op::OpBranch), {top_merge});
        Open(top_merge);
    }
"""),
],
OM: [
("ins", '#include "bbport_toggles.h"\n', "",
        '#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)\n'),
("rep", "                         (BbWindSway::KnobOnce().on ? BbWindSway::RegionBytes : 0u),\n",
        "                         (BbWindSway::KnobOnce().on ? BbWindHang::SwayBytes() : 0u), // (r112)\n"),
("rep", "        std::memset(sway_words, 0, BbWindSway::RegionBytes);\n",
        "        std::memset(sway_words, 0, BbWindHang::SwayBytes()); // bbport (r112): and its words\n"),
("rep", "        for (u32 i = BbWindSway::BaseAt; i < BbWindSway::RegionWords; ++i) {\n",
        "        for (u32 i = BbWindSway::BaseAt; i < BbWindHang::KeysEnd(); ++i) { // (r112): top keys\n"),
],
RH: [
("ins", '#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)\n', "",
        '#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)\n'),
("ins", "    void WindSwayFrameEnd();\n", "",
r"""    /// bbport (r112_wind-more-things): with BB_WIND_HANG=1, whether a skinned draw that is no plant
    /// is a hanging thing's (bbport_wind_hang.h), and once it has a slot its sway word (0, or one
    /// with HangBit: a ramp of 0 while its height is read); a view's push table is filled at its
    /// first pushed draw of a frame
    bool WindHangVerdict(const GraphicsPipeline* pipeline, u64 positions, u32 positions_size);
    u32 WindHangWord(u32* words, u32 frame_slot, u32 view, u32 slot, bool reset, u64 positions,
                     u64 frame, const BbWind::Snapshot& now);
"""),
("ins", "    u64 sway_frames = 0;\n", "",
r"""    /// bbport (r112_wind-more-things): the hanging things' streams, the log's counts, the push
    /// tables' follower, and which views of ObjectMotion frame hang_frame have their table
    BbWindHang::Book hang_book;
    BbWindHang::Stats hang_stats;
    BbWindHang::Push hang_push;
    u64 hang_frame = ~u64{0};
    std::array<bool, BbWindSway::Views> hang_filled{};
"""),
],
RE: [
("rep", "    if (!rt_shadow->LonePlant(positions, positions_size)) {\n        return 0;\n    }\n    ++sway_stats.plants;\n",
r"""    // bbport (r112_wind-more-things): or, with BB_WIND_HANG=1, a hanging thing (WindHangVerdict)
    const bool plant = rt_shadow->LonePlant(positions, positions_size);
    const bool hang = !plant && WindHangVerdict(pipeline, positions, positions_size);
    if (!plant && !hang) {
        return 0;
    }
    sway_stats.plants += plant ? 1 : 0;
"""),
("ins", "        words[BbWindSway::BaseAt + taken.slot] = BbWindSway::ResetKey;\n", "",
        "        words[BbWindHang::TopAt + taken.slot] = BbWindSway::ResetKey; // bbport (r112)\n"),
("ins", "    ++sway_stats.swayed;\n",
r"""    if (hang) { // bbport (r112_wind-more-things): its word (WindHangWord), counted in its lines
        return WindHangWord(words, frame_slot, view, taken.slot, taken.reset, positions, frame,
                            snapshot);
    }
""", ""),
("ins", "// bbport (r89_wind-foliage-sway): the knob's line once (nothing with BB_WIND off: r82's line says\n",
r"""// bbport (r112_wind-more-things): BB_WIND_HANG=1 (bbport_wind_hang.h): a skinned draw of a sway
// pipeline that is no plant is a hanging thing's when RtShadow takes its position stream for one a
// sun shadow pass draws (SunSkinned) and the Book finds the bytes of its skeleton palettes (stride
// 16, Motion's Skeleton size) the same on StillFrames frames and never others; a palette the GPU
// writes (not bound in place) or that is not mapped makes it moving. A stream the Book settled for
// good (moving, or measured out of height) is not hashed again. On the thread recording draws.
bool Rasterizer::WindHangVerdict(const GraphicsPipeline* pipeline, u64 positions,
                                 u32 positions_size) {
    if (!BbWindHang::KnobOnce().on) {
        return false;
    }
    ++hang_stats.draws;
    if (!rt_shadow->SunSkinned(positions, positions_size)) {
        ++hang_stats.no_sun;
        return false;
    }
    const u64 frame = object_motion->Frame();
    if (hang_book.Settled(positions, positions_size, frame)) {
        ++hang_stats.settled;
        return false;
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    u64 hash = 0;
    bool readable = true;
    for (const auto& resource : vs.buffers) {
        if (resource.IsSpecial()) {
            continue;
        }
        const auto buffer = resource.GetSharp(vs);
        const u32 size = buffer.GetSize();
        if (!buffer.Valid() || buffer.GetStride() != 16 ||
            Motion::ClassifyBuffer(size) != Motion::BufferRole::Skeleton) {
            continue;
        }
        if ((buffer_cache.IsRegionGpuModified(buffer.base_address, size) &&
             !buffer_cache.IsInPlace(buffer.base_address, size)) ||
            !memory->IsValidGpuMapping(buffer.base_address, 0) ||
            memory->ClampRangeSize(buffer.base_address, size) != size) {
            readable = false;
            break;
        }
        hash = XXH3_64bits_withSeed(reinterpret_cast<const void*>(buffer.base_address), size, hash);
    }
    switch (hang_book.Note(positions, positions_size, hash, readable, frame, vs.pgm_hash)) {
    case BbWindHang::Verdict::Still:
        ++hang_stats.still;
        return true;
    case BbWindHang::Verdict::Moving:
        ++hang_stats.moving;
        return false;
    case BbWindHang::Verdict::Unfit:
        ++hang_stats.unfit;
        return false;
    case BbWindHang::Verdict::Waiting:
        break;
    }
    ++hang_stats.waiting;
    return false;
}

// bbport (r112_wind-more-things): a hanging thing's sway word once its stream has its slot
// (`reset`: its keys were reset now): HangBit with a ramp of 0 while the GPU fills its base and
// top keys (Measure reads them, only then: mapped GPU memory is slow for the CPU), then, if it
// spans MinExtent-MaxExtent, its ramp; out of height 0 (and the Book keeps it out without
// hashing). The first pushed draw of a view in a frame fills the view's push table (Push, from
// the camera FillView left in the view's WindE.z and WindE.w and the wind `now`).
u32 Rasterizer::WindHangWord(u32* words, u32 frame_slot, u32 view, u32 slot, bool reset,
                             u64 positions, u64 frame, const BbWind::Snapshot& now) {
    BbWindHang::Entry* const entry = hang_book.Find(positions);
    if (entry == nullptr) {
        return 0;
    }
    const BbWindHang::Measured m =
        BbWindHang::Measure(*entry, reset, frame, words + BbWindSway::BaseAt + slot,
                            words + BbWindHang::TopAt + slot, now.time);
    if (m.measuring) {
        ++hang_stats.measuring;
        return BbWindHang::HangWord(frame_slot, view, slot, 0);
    }
    if (!m.swing) {
        ++hang_stats.unfit;
        return 0;
    }
    if (frame != hang_frame) {
        hang_frame = frame;
        hang_filled = {};
    }
    if (!hang_filled[view]) {
        const u32* const words_of_view = words + BbWindSway::ViewAt(frame_slot, view);
        const auto& knob = BbWindSway::KnobOnce();
        std::array<float, BbWindSway::GustSamples> table{};
        hang_push.Fill(now, std::bit_cast<float>(words_of_view[BbWindSway::WindE + 2]),
                       std::bit_cast<float>(words_of_view[BbWindSway::WindE + 3]), knob.gusts,
                       knob.scale, table.data());
        std::memcpy(words + BbWindHang::PushAt +
                        (frame_slot * BbWindSway::Views + view) * BbWindSway::GustSamples,
                    table.data(), sizeof(table));
        hang_filled[view] = true;
    }
    ++hang_stats.swung;
    hang_stats.ramping += m.ramp < 255 ? 1 : 0;
    return BbWindHang::HangWord(frame_slot, view, slot, m.ramp);
}

""", ""),
("ins", "    if (!on || ++sway_frames % BbWindSway::ReportFrames != 0) {\n",
r"""    // bbport (r112_wind-more-things): BB_WIND_HANG's line once, with the wind's speed then
    static bool hang_said = false;
    if (!hang_said && BbWindHang::KnobOnce().asked) {
        hang_said = true;
        char hang[512];
        if (BbWindHang::KnobOnce().on) {
            BbWindHang::OnceText(wind.Get().speed, BbWindSway::KnobOnce().scale, hang,
                                 sizeof(hang));
        } else {
            std::snprintf(hang, sizeof(hang),
                          "Wind sway hang (r112): off (BB_WIND_HANG=1 needs BB_WIND=1 and "
                          "BB_WIND_SWAY above 0); nothing hangs");
        }
        BbReport::Printf("%s\n", hang);
    }
""", ""),
("ins", "    sway_stats = {};\n", "",
r"""    if (BbWindHang::KnobOnce().on) { // bbport (r112_wind-more-things): its two lines
        char hang[512];
        BbWindHang::LineText(hang_stats, hang_book, hang_push.Now(), hang, sizeof(hang));
        BbReport::Printf("%s\n", hang);
        BbWindHang::MeshesText(hang_book, object_motion->Frame(), hang, sizeof(hang));
        BbReport::Printf("%s\n", hang);
        hang_stats = {};
    }
"""),
],
TH: [
("ins", "    [[nodiscard]] bool LonePlant(u64 positions, u32 size) const;\n", "",
r"""    // bbport (r112_wind-more-things): whether a sun shadow pass drew the stream at `positions` with
    // `size` bytes bound (0: not known) with a skeleton (LampLoneState::Sun of lone_streams: the
    // game gives the mesh a sun shadow; characters, and the hanging things of BB_WIND_HANG), as of
    // the draws so far. Another size than the stream is known with is another mesh: false.
    [[nodiscard]] bool SunSkinned(u64 positions, u32 size) const;
"""),
],
TC: [
("ins", """bool RtShadow::LonePlant(u64 positions, u32 size) const {
    if (positions == 0) {
        return false;
    }
    const auto known = lone_streams.find(positions);
    return known != lone_streams.end() && LampLoneOf(known->second) == LampLoneState::Lone &&
           (size == 0 || known->second.size == 0 || known->second.size == size);
}
""", "",
r"""
// bbport (r112_wind-more-things): see the declaration (as LonePlant, for LampLoneState::Sun)
bool RtShadow::SunSkinned(u64 positions, u32 size) const {
    if (positions == 0) {
        return false;
    }
    const auto known = lone_streams.find(positions);
    return known != lone_streams.end() && LampLoneOf(known->second) == LampLoneState::Sun &&
           (size == 0 || known->second.size == 0 || known->second.size == size);
}
"""),
],
PC: [
("ins", '#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)\n', "",
        '#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)\n'),
("ins", "// bbport (r89_wind-foliage-sway): MotionVectors::Sway for a motion pipeline whose pixel shader\n",
r"""// bbport (r112_wind-more-things): whether the selection's vertex shader reads a bone palette of
// character size (a stride-16 buffer Motion takes for a Skeleton, by which the rasterizer's
// Motion block takes a draw for Kind::Skinned), for SwayWanted with BB_WIND_HANG=1
static bool SkeletonRead(const PipelineSelection& sel) {
    const auto* vs = sel.infos[static_cast<u32>(Shader::SwStage::Vertex)];
    if (!vs) {
        return false;
    }
    for (const auto& resource : vs->buffers) {
        if (resource.IsSpecial()) {
            continue;
        }
        const auto buffer = resource.GetSharp(*vs);
        if (buffer.Valid() && buffer.GetStride() == 16 &&
            Motion::ClassifyBuffer(buffer.GetSize()) == Motion::BufferRole::Skeleton) {
            return true;
        }
    }
    return false;
}

""", ""),
("rep", "    return sel.motion && BbWindSway::KnobOnce().on && FragmentDiscards(sel);\n",
r"""    // bbport (r112_wind-more-things): with BB_WIND_HANG=1 also one whose vertex shader reads a
    // skeleton (SkeletonRead), cut-out or not: it may draw a hanging thing (bbport_wind_hang.h)
    return sel.motion && BbWindSway::KnobOnce().on &&
           (FragmentDiscards(sel) || (BbWindHang::KnobOnce().on && SkeletonRead(sel)));
"""),
],
PS: [
("ins", '#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)\n', "",
        '#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)\n'),
("ins", "} // namespace Serialization\n",
r"""// bbport (r112_wind-more-things): a vertex shader with the plant sway built with BB_WIND_HANG=1
// (its code has the hanging rule; without it the emitters add nothing): its own version, so a run
// with the other setting builds it again
static constexpr u32 HangShaderBinaryVersion = 20u;
static_assert(HangShaderBinaryVersion != SwayShaderBinaryVersion &&
              HangShaderBinaryVersion != CaptureShaderBinaryVersion &&
              HangShaderBinaryVersion != MotionShaderBinaryVersion &&
              HangShaderBinaryVersion != ShaderBinaryVersion);
""", ""),
("rep", "               ? Serialization::SwayShaderBinaryVersion\n",
r"""               ? (BbWindHang::KnobOnce().on ? Serialization::HangShaderBinaryVersion // (r112)
                                            : Serialization::SwayShaderBinaryVersion)
"""),
("rep", "        binary_version != Serialization::SwayShaderBinaryVersion) { // bbport (r89b)\n",
r"""        binary_version != Serialization::SwayShaderBinaryVersion && // bbport (r89b)
        binary_version != Serialization::HangShaderBinaryVersion) { // bbport (r112)
"""),
],
CM: [
("ins", "target_include_directories(wind-sway-test PRIVATE ..)\n", "",
r"""# bbport (r112_wind-more-things): the hanging things' knob, layout, push, rule (HangDisplace), book,
# measure and log texts (shim/bbport_wind_hang.h); also built and run by engine/build.sh --test.
add_executable(wind-hang-test EXCLUDE_FROM_ALL ../tests/test_wind_hang.cpp)
target_compile_options(wind-hang-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-hang-test PRIVATE ..)
"""),
],
BS: [
("ins", "    out/wind-sway-test\n", "",
r"""    # bbport (r112_wind-more-things): the hanging things' knob, push, rule, book, measure and texts
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_wind_hang.cpp -o out/wind-hang-test
    out/wind-hang-test
"""),
],
}

ORDER = (EM, LS, OM, RH, RE, TH, TC, PC, PS, CM, BS, RM)


def readme_edit(text):
    """The README row goes after the BB_WIND_SWAY_SHOW row (the whole line is the anchor)."""
    lines = [l for l in text.split("\n") if l.startswith("| `BB_WIND_SWAY_SHOW` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_WIND_SWAY_SHOW row is there %d times, wanted 1" % len(lines))
    return ("ins", lines[0] + "\n", "", ROW)


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
    """'applied' or 'clean' (every edit in that state), else refuse. Inserted texts are found by
    themselves (exactly once), not next to their anchor."""
    done = todo = 0
    for ed in eds:
        if ed[0] == "ins":
            _, anchor, before, after = ed
            parts = [t for t in (before, after) if t]
            na, counts = cur.count(anchor), [cur.count(t) for t in parts]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s "
                                 "times: %r" % (path, na, counts, anchor[:70]))
        else:
            _, old, new = ed
            no, nn = cur.count(old), cur.count(new)
            if no == 0 and nn == 1:
                done += 1
            elif no == 1 and nn == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times, its replacement %d times "
                                 "(wanted 1 and 0, or 0 and 1): %r" % (path, no, nn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def new_state(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    have = open(full, "rb").read().replace(b"\r\n", b"\n")
    if have == NEW_FILES[path].encode("utf-8"):
        return "applied"
    raise SystemExit("REFUSED %s: the file exists with other content" % path)


def sanity():
    for ed_list in EDITS.values():
        for ed in ed_list:
            if ed[0] == "rep" and (ed[1] in ed[2] or ed[2] in ed[1]):
                raise SystemExit("script fault: a replacement holds its original: %r" % ed[1][:60])


def text_checks(texts):
    """The ties a compiler cannot check (both emitters alike, README numbers, the off path)."""
    def need(path, want, n):
        if texts[path].count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, want, texts[path].count(want), n))
    hh = NEW_FILES[NH]
    for want in ("HangBit = 1u << 13;", "HangStill = 0.3f;", "HangFull = 1.2f;", "PushFull = 0.15f;",
                 "RiseTime = 0.4;", "ReleaseTime = 1.6;", "SlowestSpeed = 1.0f;", "StillFrames = 60;",
                 "JudgeFrames = 8;", "MinExtent = 0.8f, MaxExtent = 4.0f;", "AllBytes == 14336",
                 "FullSpeed = BbWind::MaxSpeed;"):
        if hh.count(want) != 1:
            raise SystemExit("text check: bbport_wind_hang.h lacks %r" % want)
    row = texts[RM]
    for want in ("over 60 frames", "0.8 to 4 m in height", "first 8 frames", "(top - y - 0.3 m) / 0.9 m",
                 "its top 0.3 m stays, from 1.2 m below", "over 1 s", "every 600 frames",
                 "time constant of 0.4 s", "one of 1.6 s", "0.15 m x (speed / 4 m/s)^2", "at most that of 1 m/s",
                 "held to 0.4 m", "never against the"):
        if row.count(want) < 1 or ROW.count(want) != 1:
            raise SystemExit("text check: README row lacks %r" % want)
    # both emitters: everything of the hanging rule behind the knob, in the same order
    for path, start, end, d_line, merge in (
            (EM, "static void EmitVertexSway(", "static void EmitFragmentMotion(",
             "const Id d =\n", "ctx.AddLabel(offer_merge);"),
            (LS, "void Lift_::VertexSway() {", "void Lift_::VertexMotion()",
             "const u32 d = ComponentsF({ddx_all", "Open(offer_merge);")):
        s = texts[path]
        s = s[s.find(start):s.find(end)]
        need(path, "BbWindHang::KnobOnce().on", 1)
        need(path, "OpAtomicUMin", 2)
        sel = "ddx_all = ctx.OpSelect" if path == EM else "ddx_all = Select("
        marks = [s.find(x) for x in ("const bool hang_on", "H::HangBit", "H::TopAt", "H::HangStill",
                                     "H::HangInv", "H::PushAt", sel, d_line, merge,
                                     "if (hang_on) { //", "key_top")]
        if not all(m >= 0 for m in marks) or marks != sorted(marks):
            raise SystemExit("text check: %s: the hanging parts are missing or out of order: %s" % (path, marks))
        if s.count("if (hang_on)") != 2:
            raise SystemExit("text check: %s: the hanging rule is not all behind the knob" % path)
    need(PS, "HangShaderBinaryVersion = 20u;", 1)
    need(PS, "Serialization::HangShaderBinaryVersion", 2)
    need(OM, "BbWindSway::RegionBytes", 0)
    need(OM, "BbWindHang::SwayBytes()", 2)
    need(OM, "BbWindHang::KeysEnd()", 1)
    need(RE, "WindHangVerdict(pipeline, positions, positions_size)", 1)
    need(RE, "words[BbWindHang::TopAt + taken.slot] = BbWindSway::ResetKey;", 1)
    need(RE, "return WindHangWord(words, frame_slot, view, taken.slot, taken.reset", 1)
    re = texts[RE]
    if not (re.find("const bool hang = !plant") < re.find("return WindHangWord(") < re.find("++sway_stats.swayed;")):
        raise SystemExit("text check: WindSwayWord's hanging parts are out of order")
    need(PC, "BbWindHang::KnobOnce().on && SkeletonRead(sel)", 1)
    need(CM, "add_executable(wind-hang-test", 1)
    need(BS, "out/wind-hang-test\n", 2)
    # new C++ lines stay within 100 columns (the lifter's file has longer lines; README is a table)
    for path in (EM, OM, RH, RE, TH, TC, PC, PS, CM):
        for ed in EDITS[path]:
            for part in (ed[2:] if ed[0] == "ins" else ed[2:3]):
                for line in part.split("\n"):
                    if len(line) > 100:
                        raise SystemExit("text check: %s: a new line over 100 columns: %r" % (path, line[:60]))
    for name, body in NEW_FILES.items():
        for line in body.split("\n"):
            if len(line) > 100:
                raise SystemExit("text check: %s: a line over 100 columns: %r" % (name, line[:60]))
        if not body.isascii():
            raise SystemExit("text check: %s is not ASCII" % name)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112_ROOT)" % ROOT)
    sanity()
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    news = {p: new_state(p) for p in NEW_FILES}
    states = {p[5] for p in plan} | set(news.values())
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join(["%s %s" % (p[0], p[5]) for p in plan] +
                                                     ["%s %s" % (p, s) for p, s in news.items()]))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for ed in eds:
                if ed[0] == "ins":
                    _, anchor, before, after = ed
                    cur = cur.replace(anchor, before + anchor + after)
                else:
                    cur = cur.replace(ed[1], ed[2])
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new; text checks on the "
                  "result pass)" % (len(plan), sum(len(p[1]) for p in plan), len(NEW_FILES)))
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
            tmp = full + ".r112tmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path, body in NEW_FILES.items():
            full = os.path.join(ROOT, path)
            tmp = full + ".r112tmp"
            open(tmp, "wb").write(body.replace("\n", "\r\n").encode("utf-8"))
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for ed in reversed(eds):
            if ed[0] == "ins":
                for part in (ed[3], ed[2]):
                    if part:
                        cur = cur.replace(part, "", 1)
            else:
                cur = cur.replace(ed[2], ed[1], 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r112tmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


if __name__ == "__main__":
    main()
