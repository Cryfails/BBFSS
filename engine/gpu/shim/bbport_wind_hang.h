// SPDX-License-Identifier: GPL-3.0-or-later
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
#include <cstring>
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
// bbport (r112g_hang-judge-settles): the least height was 0.8 m; lanterns on hooks, chains, cages
// and small cloth hang too now (their still top, full distance and push scale with HangScale)
inline constexpr float MinExtent = 0.15f, MaxExtent = 4.0f; ///< m of world height it may span
inline constexpr float HangScaleMin = 0.1f; ///< the least scale HangScale gives
inline constexpr std::size_t BookMost = 8192;  ///< streams known at most
inline constexpr std::uint64_t BookKeep = 600; ///< frames unseen before one may be forgotten

static_assert((W::PackWord(3, 1, 1023, 255) & HangBit) == 0, "HangBit lies in PackWord's fields");
static_assert((HangBit & W::WordOn) == 0);
static_assert(AllBytes == 14336 && TopAt % 4 == 0 && PushAt % 4 == 0);
static_assert(HangFull > HangStill && HangStill >= 0.0f);
static_assert(MinExtent > 0.0f && MaxExtent > MinExtent && MinExtent >= HangScaleMin * HangFull);
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

// bbport (r112m_hang-close-proof, TOOL): BB_WIND_HANG_PROOF=1 (needs BB_WIND_HANG): the lifter's vertex shaders tint the
// outputs of a PUSHED hang draw (a hang word whose ramp is above 0) toward cyan by ProofShare, so that a still shows which
// meshes are pushed. Read when a shader is built; off: nothing is emitted.
inline constexpr float ProofShare = 0.5f; // bbport (r112r_hang-bracket-judge): 0.4 in r112m; the recompiler's shaders tint too now

[[nodiscard]] inline bool ParseProof(const char* text) {
    return text != nullptr && text[0] == '1' && text[1] == 0;
}

[[nodiscard]] inline bool ProofOn() {
    static const bool on = KnobOnce().on && ParseProof(std::getenv("BB_WIND_HANG_PROOF"));
    return on;
}

// bbport (r112q_hang-bracket-route): the proof's tint is part of the lifter's SPIR-V and the serialized shader's binary version did not say so:
// a run with BB_WIND_HANG_PROOF=1 loaded the warm cache's sway shaders (made with no tint) and showed no cyan (b64). With the proof on, every
// sway vertex shader's binary version gets ProofBinaryAdd: a cached shader of a run without the proof is not loaded, and the proof run's own
// shaders are saved and loaded under their version. Off: 0, as before.
inline constexpr std::uint32_t ProofBinaryAdd = 200000; // bbport (r112r_hang-bracket-judge): 100000 in r112q; the tint changed (every hang bit, the recompiler too): the b65 proof shaders are not loaded

[[nodiscard]] inline std::uint32_t ProofBinaryOffset() {
    return ProofOn() ? ProofBinaryAdd : 0u;
}

// bbport (r112s_hang-bracket-move): the bracket lanterns' POSTS. b66 named the lantern's draw: a position stream of 13642 vertices (a mesh of
// 10796 vertices, 5.7 m tall, 2.2 m wide: a lamp post with the lantern on its bracket), a TREE of the twigs (a tree word, weighed by the
// vertex's height over the camera) and never a hang candidate (r112i: 0.15-2.0 m tall). BB_WIND_HANG_POST (read once; with BB_WIND_HANG=1:
// unset or `1` = on for streams of 13642 vertices, `0` = off, else the vertex counts of the posts' position streams separated by `:`, at most 8)
// gives such a stream a hang word with PostBit: its slot's keys fill (ramp 0), then it leans downwind like a hanging thing, but the shaders weigh
// the vertex by its depth below the slot's top key over the keys' height (PostT), not by its depth below the top alone: 1 in the top 20 percent
// of the mesh, 0 from 65 percent down, so the upper part of the post moves as one piece and its foot stays.
inline constexpr std::uint32_t PostBit = 1u << 15; ///< the sway word's bit for a post (free: PackWord ends at bit 12 and restarts at 16)
inline constexpr float PostBelow = 0.65f;          ///< depth below the top (share of the keys' height) where the weight is 0
inline constexpr float PostSpan = 0.45f;           ///< the weight is 1 at PostBelow - PostSpan (0.20) and above
inline constexpr float PostExtMin = 2.0f;          ///< m: the height the shaders divide by is at least this (a base key not filled yet)
inline constexpr float PostMaxExtent = 10.0f;      ///< m: the keys' span (the union of the places) above which a post gets no word
inline constexpr std::uint32_t PostBinaryAdd = 52000; ///< added to the sway shader binary version with the post rule (above every other sum, under the proof's)
inline constexpr std::uint32_t PostDefaultVerts = 13642;
inline constexpr std::size_t PostStreamsMost = 8;  ///< vertex counts BB_WIND_HANG_POST may name
inline constexpr std::size_t PostKept = 64;        ///< streams the book keeps at most

static_assert((W::PackWord(3, 1, 1023, 255) & PostBit) == 0 && (PostBit & W::WordOn) == 0 && PostBit != HangBit,
              "PostBit lies outside PackWord's fields and is not HangBit");
static_assert(PostBelow < 1.0f && PostBelow > PostSpan && PostSpan > 0.0f && PostExtMin > 0.0f && PostMaxExtent > MinExtent);
static_assert(PostBinaryAdd > 20000u && PostBinaryAdd < ProofBinaryAdd, "above every sway offset sum (about 15600), under the proof's add");

/// BB_WIND_HANG_POST parsed: `on` (not exactly `0`), the vertex counts of the posts' position streams (a list of numbers separated by anything
/// that is no digit; none, or exactly `1`: PostDefaultVerts).
struct PostKnob {
    bool on = false;
    std::array<std::uint32_t, PostStreamsMost> verts{};
    std::size_t count = 0;
};

[[nodiscard]] inline PostKnob ParsePost(const char* text) {
    PostKnob k;
    k.on = true;
    if (text != nullptr && text[0] == '0' && text[1] == 0) {
        k.on = false;
        return k;
    }
    if (text != nullptr && !(text[0] == '1' && text[1] == 0)) {
        std::uint64_t value = 0;
        bool digits = false;
        for (const char* p = text;; ++p) {
            if (*p >= '0' && *p <= '9') {
                value = std::min<std::uint64_t>(value * 10u + static_cast<std::uint64_t>(*p - '0'), 100000000u);
                digits = true;
                continue;
            }
            if (digits && value > 0 && k.count < PostStreamsMost) {
                k.verts[k.count++] = static_cast<std::uint32_t>(value);
            }
            value = 0;
            digits = false;
            if (*p == 0) {
                break;
            }
        }
    }
    if (k.count == 0) {
        k.verts[0] = PostDefaultVerts;
        k.count = 1;
    }
    return k;
}

/// Read once with the hang knob (it is on only with BB_WIND_HANG on): the emitters and the draws ask it.
[[nodiscard]] inline const PostKnob& PostOnce() {
    static const PostKnob knob = [] {
        PostKnob k = ParsePost(std::getenv("BB_WIND_HANG_POST"));
        k.on = k.on && KnobOnce().on;
        return k;
    }();
    return knob;
}

[[nodiscard]] inline bool PostOn() {
    return PostOnce().on;
}

// bbport (r112v_lantern-hangs): BB_WIND_HANG_LANTERN (read once; default on, exactly 0 = r112s/r112t's post rule and r112u's guard): only the lantern of
// a post stream leans (bbport_wind_lantern.h). Asked only with the post rule. The shaders carry it: LanternBinaryAdd goes into the sway binary version.
inline constexpr std::uint32_t LanternBinaryAdd = 3000;

[[nodiscard]] inline bool LanternAsked() {
    static const bool asked = [] {
        const char* const text = std::getenv("BB_WIND_HANG_LANTERN");
        return PostOn() && !(text != nullptr && text[0] == '0' && text[1] == '\0');
    }();
    return asked;
}

/// Added to the sway shader binary version: 0 off (the shaders are as before), PostBinaryAdd with the post rule in them.
[[nodiscard]] inline std::uint32_t PostBinaryOffset() {
    return PostOn() ? PostBinaryAdd + (LanternAsked() ? LanternBinaryAdd : 0u) : 0u; // bbport (r112v_lantern-hangs): 3000 more with the lantern rule
}

/// Is a position stream of `size` bytes and `stride` bytes a vertex a post's (its vertex count one the knob names)?
[[nodiscard]] inline bool PostMatchesIn(const PostKnob& knob, std::uint32_t size, std::uint32_t stride) {
    if (!knob.on || stride == 0) {
        return false;
    }
    const std::uint32_t verts = size / stride;
    for (std::size_t i = 0; i < knob.count; ++i) {
        if (knob.verts[i] == verts) {
            return true;
        }
    }
    return false;
}

[[nodiscard]] inline bool PostMatches(std::uint32_t size, std::uint32_t stride) {
    return PostMatchesIn(PostOnce(), size, stride);
}

/// The shaders' weight of a post's vertex before the smoothstep: `below_top` m under the slot's top key, `height` the keys' height (at least
/// PostExtMin; a number that is none gives PostExtMin): 1 within the top 20 percent, 0 from 65 percent down.
[[nodiscard]] inline float PostT(float below_top, float height) {
    const float e = height > PostExtMin ? height : PostExtMin;
    return std::clamp((PostBelow - below_top / e) * (1.0f / PostSpan), 0.0f, 1.0f);
}

/// A saved version with the proof's add taken out (only while the proof is on and the version carries it).
[[nodiscard]] inline std::uint32_t StripProofVersion(std::uint32_t version) {
    if (ProofOn() && version >= ProofBinaryAdd) {
        version -= ProofBinaryAdd;
    }
    // bbport (r112s_hang-bracket-move): and the post rule's add (52000 since r112t, under the proof's 200000; every other sum is under 20000)
    const std::uint32_t post_add = PostBinaryAdd + (LanternAsked() ? LanternBinaryAdd : 0u); // bbport (r112v_lantern-hangs)
    return PostOn() && version >= post_add ? version - post_add : version;
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

/// bbport (r112g_hang-judge-settles): the scale of a mesh shorter than HangFull: its height (top
/// minus base, from its slot's two keys: the shaders do the same sums with the keys) over
/// HangFull, at least HangScaleMin, 1 for a mesh of HangFull or more. The still top, the full
/// distance and the push of a short hanging thing (a lantern on a hook, a chain, a cage, a rag)
/// shrink with it; a tall mesh is exactly as before. 1 for a number that is not one.
[[nodiscard]] inline float HangScale(float base_y, float top_y) {
    const float s = (top_y - base_y) * (1.0f / HangFull);
    return std::isnan(s) ? 1.0f : std::clamp(s, HangScaleMin, 1.0f);
}
/// A hanging thing's sway word: r89's word with HangBit.
[[nodiscard]] constexpr std::uint32_t HangWord(std::uint32_t frame_slot, std::uint32_t view,
                                               std::uint32_t slot, std::uint32_t ramp) {
    return W::PackWord(frame_slot, view, slot, ramp) | HangBit;
}

[[nodiscard]] constexpr bool HangOf(std::uint32_t word) {
    return (word & W::WordOn) != 0 && (word & HangBit) != 0;
}

/// bbport (r112s_hang-bracket-move): a post's sway word: a hanging thing's word with PostBit.
[[nodiscard]] constexpr std::uint32_t PostWord(std::uint32_t frame_slot, std::uint32_t view, std::uint32_t slot, std::uint32_t ramp) {
    return W::PackWord(frame_slot, view, slot, ramp) | HangBit | PostBit;
}

[[nodiscard]] constexpr bool PostOf(std::uint32_t word) {
    return (word & W::WordOn) != 0 && (word & HangBit) != 0 && (word & PostBit) != 0;
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
        Extend(k_first, k_last, gusts, times, s); // bbport (r116b): the weather's gusts and speed
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
    void Extend(std::int64_t k_first, std::int64_t k_last, float gusts, const Times& times,
                const BbWind::Snapshot& s) {
        // bbport (r116b_wind-weather): with the weather the speed, so the times, change every frame: the
        // grid is kept and extended with the times of now (the samples it holds were followed at the
        // speed of their own time), not started again
        const bool same = !grid.empty() && gusts == grid_gusts &&
                          (s.weather_on || (times.rise == grid_times.rise && times.release == grid_times.release));
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
                grid.push_back(Drive(BbWind::GustOf(s, double(k0) * PushStep, gusts))); // bbport (r116b)
                grid_gusts = gusts;
                grid_times = times;
                ++restarts;
            }
        }
        while (k0 + std::int64_t(grid.size()) <= k_last) {
            const std::int64_t k = k0 + std::int64_t(grid.size());
            const float x = Drive(BbWind::GustOf(s, double(k) * PushStep, gusts)); // bbport (r116b)
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
/// r112g: `scale` the mesh's HangScale (1: a tall one): its still top and full distance times it,
/// so is its push.
[[nodiscard]] inline std::array<float, 4> HangDisplace(const float* view, const float* push,
                                                       const std::array<float, 4>& clip,
                                                       std::uint32_t stored_top, float ramp,
                                                       std::uint32_t* key_top = nullptr,
                                                       float scale = 1.0f) {
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
    const float t = std::clamp((h - HangStill * scale) * (HangInv / scale), 0.0f, 1.0f);
    const float w = t * t * (3.0f - 2.0f * t) * ramp * scale;
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
    std::uint8_t why_moving = 0; ///< bbport (r112n): the first reason `moving` was set: 1 a palette could not be read, 2 its bytes changed, 3 the GPU judge, 4 r112h's rule
    std::uint32_t moved_after = 0; ///< bbport (r112n): the frames counted before the bytes changed (2), or r112h's rule's number (4)
    std::uint8_t box_only = 0; ///< bbport (r112p_hang-gpu-palette-lanterns): the GPU box judges it in place of its palette: 1 the palette could not be read, 2 its content differed (0: no)
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
                 std::uint64_t frame, std::uint64_t vs, std::uint8_t unread_why = 1,
                 std::uint8_t box_only = 0) { // bbport (r112p_hang-gpu-palette-lanterns): why 5: the content differed; the box route
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
        e.box_only = box_only; // bbport (r112p_hang-gpu-palette-lanterns): the last draw's route
        if (!readable) {
            if (!e.moving) { // bbport (r112n_hang-teleport-camera): the first reason is kept
                e.why_moving = unread_why; // bbport (r112p): 1 the palette could not be read, 5 its content differed
            }
            e.moving = true;
        } else if (e.frames == 0) {
            e.hash = hash;
            e.frames = 1;
            e.frame = frame;
        } else if (hash != e.hash) {
            if (!e.moving) {
                e.why_moving = 2;
                e.moved_after = e.frames;
            }
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
                        const std::uint32_t* top_key, double time,
                        float max_extent = MaxExtent) { // bbport (r112k): a static candidate's union
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
        e.fits = std::isfinite(extent) && extent >= MinExtent && extent <= max_extent;
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
                  "back in %.2f s; skinned, sun-shadowed, one palette %u frames, %.2f-%.1f m "
                  "tall; top %.1f m still, full %.1f m below, less under that",
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

// ---- bbport (r112t_hang-post-measure): a post's keys from the scene's box -------------------------------------------------------------------
// b68: the post's slot judged out of 0.15-10 m for good (no word for 5252 draws). The slot's keys are atomic minima over every vertex of every draw of
// the stream, so they span the UNION of the places the post is drawn at (the sun passes draw the posts all over the graveyard: 9-10 m of ground
// height before the post's own 5.7 m). The ray traced scene has a world box per mesh entry (one per post): the CPU takes the box of the post nearest
// the camera and writes its base and top into the slot's keys, and the shaders offer no key for a word with PostBit.
inline constexpr float PostPickTie = 0.75f; ///< m: boxes of a stream whose horizontal distances to the camera differ by less are one place

struct PostPick {
    bool found = false;
    bool camera = false;           ///< dist is a distance (else the first box of the best source won)
    std::uint32_t count = 0;       ///< boxes of the stream with a usable height
    float base = 0.0f, top = 0.0f; ///< the picked box's lowest and highest world y
    float dist = -1.0f;            ///< m, horizontal, the box's centre to the camera (-1: no camera)
    char src = '?';                ///< the picked box's source (c camera capture, s still bounds, v sun VSM box)
};

/// The box of the stream nearest `camera` (x, y, z world; null: none known): `boxes` any container of items with `stream`, `box` (least x, y, z,
/// greatest x, y, z, y up) and `src`. Among boxes within PostPickTie of the nearest distance the source decides: c, then s, then v.
template <class Boxes>
[[nodiscard]] inline PostPick PickPost(const Boxes& boxes, std::uint64_t stream, const float* camera) {
    PostPick pick;
    if (stream == 0) {
        return pick;
    }
    int best_rank = 3;
    for (const auto& b : boxes) {
        if (b.stream != stream) {
            continue;
        }
        bool usable = true; // every corner finite and in range: a NaN centre would make a distance no later box can beat
        for (const float c : b.box) {
            usable = usable && std::isfinite(c) && std::fabs(c) < 1.0e5f;
        }
        const float lo = b.box[1], hi = b.box[4];
        if (!(usable && hi > lo)) {
            continue;
        }
        ++pick.count;
        float dist = 0.0f;
        if (camera != nullptr) {
            const float cx = 0.5f * (b.box[0] + b.box[3]) - camera[0];
            const float cz = 0.5f * (b.box[2] + b.box[5]) - camera[2];
            dist = std::sqrt(cx * cx + cz * cz);
        }
        const int rank = b.src == 'c' ? 0 : (b.src == 's' ? 1 : 2);
        bool better = !pick.found;
        if (pick.found) {
            const bool nearer = dist < pick.dist - PostPickTie;
            const bool same = !nearer && dist <= pick.dist + PostPickTie;
            better = nearer || (same && rank < best_rank);
        }
        if (better) {
            pick.found = true;
            pick.camera = camera != nullptr;
            pick.base = lo;
            pick.top = hi;
            pick.dist = dist;
            pick.src = b.src;
            best_rank = rank;
        }
    }
    if (!pick.camera) {
        pick.dist = -1.0f;
    }
    return pick;
}

// ---- bbport (r112u_hang-post-no-bridge): the post push moves a hanging lantern only -----------------------------------------------------------
// b70: the post rule (every stream of 13642 vertices is a lamp post) pushed a stream that is, or is shared with, the BRIDGE (5.66 m tall in the scene):
// its arc edge moved 0.24-0.35 m (the owner, 08:10). BB_WIND_HANG_POST_GUARD (default on, read once; exactly 0 = r112t's rule): a stream is refused
// (never pushed) when any of its boxes in the ray traced scene is wider than PostGuardWide in x or z or taller than PostGuardTall, when it has more
// than PostGuardSharedMost boxes that differ by more than PostGuardSharedTol (one stream drawn as several different things: architecture), or, when
// the caller has the lamps' light positions, when the picked box's lower end is not within PostGuardLamp of one. A post that passes is pushed at most
// PostGuardPush m.
inline constexpr float PostGuardWide = 1.5f;             ///< m: a box wider than this in x or z is no lantern
inline constexpr float PostGuardTall = 3.0f;             ///< m: a box taller than this is no lantern
inline constexpr std::uint32_t PostGuardSharedMost = 3;  ///< boxes of a stream above which they must all be alike
inline constexpr float PostGuardSharedTol = 0.3f;        ///< m: how much alike (width and height each)
inline constexpr float PostGuardLamp = 1.0f;             ///< m: the lamp light's largest distance from the box's lower end
inline constexpr float PostGuardPush = 0.12f;            ///< m: the largest push of a post that passes

enum class PostRefuse : std::uint8_t { None = 0, Wide, Tall, Shared, NoLamp };
inline constexpr std::size_t PostRefuseKinds = 5;

struct PostGuard {
    PostRefuse why = PostRefuse::None;
    std::array<float, 6> box{}; ///< the box that decided (the first of a shared stream)
    std::uint32_t count = 0;    ///< boxes of the stream in the scene (usable ones)
};

[[nodiscard]] inline bool ParsePostGuard(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == '\0');
}

/// Read once.
[[nodiscard]] inline bool PostGuardOn() {
    static const bool on = ParsePostGuard(std::getenv("BB_WIND_HANG_POST_GUARD"));
    return on;
}

/// The gain a post word gets: the live gain, held to PostGuardPush over the push table's largest value (MaxAlong); a number that is none gives 0.
[[nodiscard]] inline float PostGain(float gain) {
    const float cap = PostGuardPush / W::MaxAlong;
    return std::isnan(gain) ? 0.0f : std::min(gain, cap);
}

[[nodiscard]] inline const char* PostRefuseName(PostRefuse why) {
    switch (why) {
    case PostRefuse::Wide:
        return "a box wider than the limit";
    case PostRefuse::Tall:
        return "a box taller than the limit";
    case PostRefuse::Shared:
        return "a shared stream: many boxes that differ";
    case PostRefuse::NoLamp:
        return "no lamp light near the box's lower end";
    default:
        return "none";
    }
}

/// The verdict on `stream` over every box of it in `boxes` (items with `stream`, `box`: least x, y, z, greatest x, y, z, y up). `pick` is the box
/// PickPost chose; `lamps` x, y, z triples (`lamp_count` of them; none: the lamp rule is not applied).
template <class Boxes>
[[nodiscard]] inline PostGuard PostGuardCheck(const Boxes& boxes, std::uint64_t stream, const PostPick& pick, const float* lamps,
                                              std::size_t lamp_count) {
    PostGuard g;
    if (stream == 0) {
        return g;
    }
    float wmin = 1.0e30f, wmax = -1.0e30f, hmin = 1.0e30f, hmax = -1.0e30f;
    std::array<float, 6> first{}, picked{};
    bool have_pick = false;
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
        if (g.why == PostRefuse::None && w > PostGuardWide) {
            g.why = PostRefuse::Wide;
            g.box = b.box;
        } else if (g.why == PostRefuse::None && h > PostGuardTall) {
            g.why = PostRefuse::Tall;
            g.box = b.box;
        }
        wmin = std::min(wmin, w);
        wmax = std::max(wmax, w);
        hmin = std::min(hmin, h);
        hmax = std::max(hmax, h);
        if (pick.found && b.box[1] == pick.base && b.box[4] == pick.top) {
            picked = b.box;
            have_pick = true;
        }
    }
    if (g.why == PostRefuse::None && g.count > PostGuardSharedMost && (wmax - wmin > PostGuardSharedTol || hmax - hmin > PostGuardSharedTol)) {
        g.why = PostRefuse::Shared;
        g.box = first;
    }
    if (g.why == PostRefuse::None && have_pick && lamps != nullptr && lamp_count > 0) {
        bool near_lamp = false;
        for (std::size_t i = 0; i < lamp_count && !near_lamp; ++i) {
            const float x = lamps[i * 3], y = lamps[i * 3 + 1], z = lamps[i * 3 + 2];
            const float dx = std::clamp(x, picked[0], picked[3]) - x; // the nearest point of the box's lower face
            const float dz = std::clamp(z, picked[2], picked[5]) - z;
            const float dy = picked[1] - y;
            near_lamp = dx * dx + dy * dy + dz * dz <= PostGuardLamp * PostGuardLamp;
        }
        if (!near_lamp) {
            g.why = PostRefuse::NoLamp;
            g.box = picked;
        }
    }
    return g;
}

/// The line per refused stream.
inline void PostGuardText(std::uint64_t stream, const PostGuard& g, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind sway hang post guard (r112u_hang-post-no-bridge): stream 0x%llx REFUSED (%s): %u boxes of it in the scene; the box that decides: "
                  "x %.2f..%.2f (%.2f m), y %.2f..%.2f (%.2f m), z %.2f..%.2f (%.2f m); it is never pushed",
                  static_cast<unsigned long long>(stream), PostRefuseName(g.why), static_cast<unsigned>(g.count), double(g.box[0]), double(g.box[3]),
                  double(g.box[3] - g.box[0]), double(g.box[1]), double(g.box[4]), double(g.box[4] - g.box[1]), double(g.box[2]), double(g.box[5]),
                  double(g.box[5] - g.box[2]));
}

/// The once line.
inline void PostGuardOnceText(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind sway hang post guard (r112u_hang-post-no-bridge, BB_WIND_HANG_POST_GUARD): on: a post stream is pushed only when none of its "
                  "scene boxes is wider than %.1f m or taller than %.1f m, it has at most %u boxes or they are alike within %.1f m, (with a lamp list: "
                  "the lamp light is within %.1f m of the box's lower end; this build gives no lamp list, so that rule is not applied); the push is "
                  "at most %.2f m (gain at most %.2f)",
                  double(PostGuardWide), double(PostGuardTall), static_cast<unsigned>(PostGuardSharedMost), double(PostGuardSharedTol),
                  double(PostGuardLamp), double(PostGuardPush), double(PostGuardPush / W::MaxAlong));
}

// ---- bbport (r112s_hang-bracket-move): the posts' book and lines ------------------------------------------------------------------------

/// The posts' streams (by position address) with what Measure keeps of their slots' keys, and the counts of the log line.
class PostBook {
public:
    struct Item {
        Entry entry;
        std::uint32_t size = 0;
        std::uint64_t seen = 0;
        bool logged = false;        ///< bbport (r112t): the stream's vertices line was written
        bool keys_written = false;  ///< bbport (r112t): the slot's keys hold base_key and top_key
        std::uint32_t base_key = 0, top_key = 0;
        PostPick pick;              ///< bbport (r112t): the pick of pick_frame
        std::uint64_t pick_frame = ~0ull;
        PostGuard guard;            ///< bbport (r112u): the guard's verdict of pick_frame
        PostRefuse refused = PostRefuse::None; ///< bbport (r112u): the reason the last refusal was logged for
    };

    std::uint64_t draws = 0;     ///< post draws given a word or none
    std::uint64_t measuring = 0; ///< of them, a word with ramp 0 while the keys fill
    std::uint64_t pushed = 0;    ///< a word that moves it
    std::uint64_t unfit = 0;     ///< no word: the keys' span was out of 0.15 m to PostMaxExtent
    std::uint64_t no_box = 0;    ///< bbport (r112t): no word: no box of the stream in the ray traced scene
    std::uint64_t written = 0;   ///< bbport (r112t): times the CPU wrote the slot's keys from a box
    std::uint64_t refused = 0;         ///< bbport (r112u): post draws given no word by the guard
    std::uint64_t refused_streams = 0; ///< bbport (r112u): streams refused (once per stream and reason)
    std::array<std::uint64_t, PostRefuseKinds> by_reason{}; ///< bbport (r112u): refused draws by reason (index PostRefuse)
    bool guard_said = false;           ///< bbport (r112u): the once line was written
    PostPick last;               ///< bbport (r112t): the last pick (a box that fits or not)

    /// The stream's item (made at the first draw); another size at a known address is another mesh: what was known is forgotten.
    Item& Touch(std::uint64_t stream, std::uint32_t size, std::uint64_t frame) {
        if (items.size() >= PostKept && items.find(stream) == items.end()) {
            items.clear();
        }
        Item& item = items[stream];
        if (item.size != 0 && size != 0 && item.size != size) {
            item = Item{};
        }
        item.size = size;
        item.seen = frame;
        return item;
    }

    [[nodiscard]] const std::unordered_map<std::uint64_t, Item>& Items() const {
        return items;
    }

private:
    std::unordered_map<std::uint64_t, Item> items;
};

/// The periodic line (every ReportFrames frames, with r112's): `push` the push at the camera of the last table fill.
inline void PostLineText(const PostBook& book, float push, char* out, std::size_t size) {
    unsigned streams = 0, judged = 0, swing = 0;
    float base = 0.0f, top = 0.0f;
    for (const auto& item : book.Items()) {
        const Entry& e = item.second.entry;
        ++streams;
        if (e.judged) {
            ++judged;
            if (e.fits) {
                if (swing == 0) {
                    base = e.base;
                    top = e.top;
                }
                ++swing;
            }
        }
    }
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(out, size,
                  "Wind sway hang post (r112s, BB_WIND_HANG_POST): since the start %llu draws of %u streams: %llu measuring, %llu pushed, %llu with no word "
                  "(keys span over %.0f m or under %.2f m); %u judged, %u swinging (the first: base y %.2f, top y %.2f, %.2f m tall); push %.3f m",
                  n(book.draws), streams, n(book.measuring), n(book.pushed), n(book.unfit), double(PostMaxExtent), double(MinExtent), judged,
                  swing, double(base), double(top), double(top - base), double(push));
}

/// bbport (r112u_hang-post-no-bridge): the third periodic line (the guard's counters).
inline void PostGuardLineText(const PostBook& book, char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    const auto at = [&](PostRefuse why) { return n(book.by_reason[static_cast<std::size_t>(why)]); };
    std::snprintf(out, size,
                  "Wind sway hang post guard (r112u): %llu post draws refused of %llu (%llu streams): wide %llu, tall %llu, shared %llu, no lamp %llu; "
                  "the push of a post is at most %.2f m (lamp rule: no lamp list in this build)",
                  n(book.refused), n(book.draws), n(book.refused_streams), at(PostRefuse::Wide), at(PostRefuse::Tall), at(PostRefuse::Shared),
                  at(PostRefuse::NoLamp), double(PostGuardPush));
}

/// bbport (r112t_hang-post-measure): the second periodic line (the box the keys come from).
inline void PostBoxLineText(const PostBook& book, char* out, std::size_t size) {
    const PostPick& p = book.last;
    char where[160];
    if (p.found) {
        std::snprintf(where, sizeof(where), "%u boxes of the stream, picked (%c) %.1f m from the camera: base y %.2f, top y %.2f, %.2f m tall",
                      static_cast<unsigned>(p.count), p.src, double(p.dist), double(p.base), double(p.top), double(p.top - p.base));
    } else {
        std::snprintf(where, sizeof(where), "no box of the stream yet");
    }
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(out, size,
                  "Wind sway hang post (r112t, keys from the scene's box): %llu draws with no box of the stream in the ray traced scene, %llu out of "
                  "%.2f-%.0f m, %llu key writes; the last pick: %s; the shaders offer no key for a post word",
                  n(book.no_box), n(book.unfit), double(MinExtent), double(PostMaxExtent), n(book.written), where);
}

/// bbport (r112t_hang-post-measure): once, what the post's position stream holds: `data` its bytes (null: not readable), `size` bytes at `stride`:
/// the first three vertices' floats (up to 8) and the box of floats 0-2 over all vertices.
inline void PostVerticesText(const unsigned char* data, std::uint32_t size, std::uint32_t stride, char* out, std::size_t out_size) {
    if (data == nullptr || stride < 12 || size < stride) {
        std::snprintf(out, out_size,
                      "Wind sway hang post vertices (r112t_hang-post-measure): the stream cannot be read (%s, %u bytes, stride %u)",
                      data == nullptr ? "not mapped" : "too short or no float3 position", static_cast<unsigned>(size), static_cast<unsigned>(stride));
        return;
    }
    const std::uint32_t count = size / stride;
    const std::uint32_t floats = std::min<std::uint32_t>(8u, stride / 4u);
    float lo[3] = {1.0e30f, 1.0e30f, 1.0e30f};
    float hi[3] = {-1.0e30f, -1.0e30f, -1.0e30f};
    char first[3][160] = {};
    for (std::uint32_t v = 0; v < count; ++v) {
        float p[8] = {};
        std::memcpy(p, data + static_cast<std::size_t>(v) * stride, static_cast<std::size_t>(floats) * 4u);
        for (int k = 0; k < 3; ++k) {
            if (std::isfinite(p[k]) && std::fabs(p[k]) < 1.0e6f) {
                lo[k] = std::min(lo[k], p[k]);
                hi[k] = std::max(hi[k], p[k]);
            }
        }
        if (v < 3) {
            std::size_t at = 0;
            for (std::uint32_t f = 0; f < floats; ++f) {
                const int w = std::snprintf(first[v] + at, sizeof(first[v]) - at, f == 0 ? "%.2f" : ", %.2f", double(p[f]));
                at = std::min<std::size_t>(at + (w > 0 ? static_cast<std::size_t>(w) : std::size_t{0}), sizeof(first[v]) - 1);
            }
        }
    }
    std::snprintf(out, out_size,
                  "Wind sway hang post vertices (r112t_hang-post-measure): the stream holds %u vertices (stride %u, %u bytes); the first three, as "
                  "floats: v0 (%s) v1 (%s) v2 (%s); the box of floats 0-2 over all of them: x %.2f..%.2f (%.2f m), y %.2f..%.2f (%.2f m), "
                  "z %.2f..%.2f (%.2f m)",
                  static_cast<unsigned>(count), static_cast<unsigned>(stride), static_cast<unsigned>(size), first[0], first[1], first[2],
                  double(lo[0]), double(hi[0]), double(hi[0] - lo[0]), double(lo[1]), double(hi[1]), double(hi[1] - lo[1]), double(lo[2]),
                  double(hi[2]), double(hi[2] - lo[2]));
}

/// The once line (BB_WIND_HANG=1 and the post rule on).
inline void PostOnceText(char* out, std::size_t size) {
    char list[96] = {};
    std::size_t at = 0;
    const PostKnob& knob = PostOnce();
    for (std::size_t i = 0; i < knob.count && at + 16 < sizeof(list); ++i) {
        const unsigned verts = static_cast<unsigned>(knob.verts[i]);
        const int w = i == 0 ? std::snprintf(list + at, sizeof(list) - at, "%u", verts)
                             : std::snprintf(list + at, sizeof(list) - at, " or %u", verts);
        at += w > 0 ? static_cast<std::size_t>(w) : std::size_t{0};
    }
    std::snprintf(out, size,
                  "Wind sway hang post (r112s, BB_WIND_HANG_POST): on: a draw whose position stream holds %s vertices (the bracket lanterns' posts) "
                  "has its own hang word: the part of the post within the top %.0f percent of its height leans downwind in full, nothing moves "
                  "from %.0f percent down (as one piece: the lantern on its bracket leans, the foot stays); push as a hanging thing's, times "
                  "BB_WIND_HANG_STATIC_GAIN (live) and the live BB_WIND_HANG_PUSH; its keys are the ray traced scene's box of the post nearest the camera (0.15-%.0f m tall); its shaders have their own cache version "
                  "(+%u)",
                  list, 100.0 * double(PostBelow - PostSpan), 100.0 * double(PostBelow), double(PostMaxExtent),
                  static_cast<unsigned>(PostBinaryAdd));
}

} // namespace BbWindHang
