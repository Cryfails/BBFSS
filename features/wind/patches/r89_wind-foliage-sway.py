# r89_wind-foliage-sway: FEATURE patch. Plants (weeds, bushes, hanging ivy: the skinned cut-out
# meshes the ray traced scene's plant rule takes for "lone", rt_lamp_cards.h) sway with the shared
# wind (r82, bbport_wind.h). Off by default: needs BB_WIND=1, and BB_WIND_SWAY (the amplitude's
# scale, default 1, 0 = still, at most 3) above 0. Environment only, read once; no ini key.
#
# Why: the owner's work order (wind: "Foliage sway"), and the owner could not see the sun fog's
# drift (r82): the sway must show at the default and stay natural.
#
# What:
#  1. engine/gpu/shim/bbport_wind_sway.h (new, pure): the knob, the look's constants, the sway word
#     (motion param word 7, 0 before: WordOn, the ring's frame slot, the view, the base slot, the
#     ramp), the layout of the sway words (after the motion params' ring in the same host visible
#     buffer: per frame slot and view 112 words of camera rows, wind words and a 64-sample gust
#     table; then 1024 height keys), the camera math (clip to world as RtShadow::ToWorld, world
#     direction to clip), FillView, Displace (the shaders' rule in C++), the base slots and the
#     log's counts. engine/tests/test_wind_sway.cpp (new); wind-sway-test in CMake and in
#     engine/build.sh --test (rule 2).
#  2. Shaders, both emitters, only under the new MotionVectors::Sway bit (runtime_info.h, 8): the
#     recompiler's EmitVertexSway (emit_spirv_special.cpp) and the lifter's VertexSway
#     (lift_stage.cpp; lift.h/lift_core.h/bridge.cpp carry the bit), first in the vertex epilogue,
#     before the motion store and the ray traced capture, so motion vectors and the ray traced
#     scene follow the moved positions. A draw whose word 7 lacks WordOn branches around it.
#     Height: h = the vertex's world y minus the lowest world y any vertex of its stream had so
#     far (an atomic minimum into the stream's base slot; the key is the float bits of y + 8192 m,
#     whose unsigned order is the heights' order), weight smoothstep(0, 0.75 m, h): the roots
#     (the lowest vertices) stay still and the top moves in full. Why this: the vertex shader's
#     input positions are bind pose (skinned meshes), so a height has to be measured in the world,
#     and a plant's lowest point is where it stands for a weed or a bush; a mesh-local up axis or
#     a ground height is not known to the port.
#  3. CPU: vk_pipeline_cache.cpp sets the bit (vertex runtime info and the key) for a motion
#     pipeline whose pixel shader discards, only with the knob on (SwayWanted);
#     vk_pipeline_serialization.cpp does not build a saved key with the bit when the knob is off.
#     vk_object_motion: the buffer is RegionBytes longer with the knob on, the words are set up,
#     DrawJob carries the word, WriteParam writes it as word 7 (0 for every other draw, as before),
#     also when the draw gets no motion store or load (the param is then zero but for word 7, and
#     a draw with a sway word keeps its param, so a plant does not stop swaying for a frame when
#     the store is full; with the knob off every word is 0 and Draw returns 0 as before).
#     vk_rasterizer.cpp: a skinned draw of a pipeline with the bit asks WindSwayWord
#     (vk_rasterizer_effects.cpp) for its word: RtShadow::LonePlant (vk_rt_shadow) for the draw's
#     position stream, the 864-byte camera constants, at most 2 views a frame, a base slot.
#     WindSwayFrameEnd prints the log lines.
#  4. README: a BB_WIND_SWAY row after BB_WIND_GUSTS's with the exact rule, units and limits.
#
# Ray tracing: the plant verdict is the ray traced scene's bookkeeping (RtShadow::PrepareDraw), so
# without ray tracing (effect_ray_tracing off, or RtShadow not wanted) nothing sways (counted as
# "without ray tracing" in the log). Characters, their hair and their cloth are drawn by the sun
# shadow pass, so they are never lone and never sway.
#
# BLAS: no change. A plant is a skinned entry, and skinned entries are dynamic: refitted from the
# captured positions at each of their draws (a far one at every 8th draw with graphics_rt_far_refit
# or BB_RT_REFIT_EVERY, and none when the frame's refit budget is spent), with or without sway; the
# rebuild cadence (every 120 frames, spread over 32) stays. The sway is a smooth, spatially
# coherent bend (neighbouring triangles move together), not the leaf probe's incoherent random
# +-3 cm per leaf that made card rays 2.6 times slower; card rays (BB_RT_CARD_ALPHA) are off by
# default and the lone plants are left out of lamp rays at the default card level. Not measured.
# If BB_RT_CARD_ALPHA with sway turns out costly, a later step can capture the plants unmoved.
#
# Log: "Wind sway (r89, BB_WIND=1): ..." once when on ("Wind sway (r89): off (BB_WIND_SWAY=0)..."
# with BB_WIND=1 and the scale 0; nothing with BB_WIND off, r82's line says it), and every 600
# frames "Wind sway (r89): in 600 frames N draws of sway pipelines with a skeleton, P of plants,
# S swayed (R ramping in); not swayed: ...; base slots in use U of 1024".
#
# Cost off: nothing. No key, runtime info or SPIR-V changes (the bit is never set; no host shader
# is touched), the buffer keeps its size, word 7 stays 0; per skinned motion draw one bit test.
# Cost on: per vertex of a cut-out motion pipeline one 16-byte load and a branch; per plant vertex
# about 15 loads and 60 arithmetic instructions and rarely an atomic; on the CPU a few lookups
# per plant draw. Not measured.
#
# Use: cd <tree> && python -I -X utf8 r89_wind-foliage-sway.py check | apply | revert (root from
# R89_ROOT, else the current directory). Files keep their line ends; the new files are written
# with CRLF and removed by revert. Originals are kept in r89_backup/ next to this script. Revert
# r89 before reverting any patch whose text its anchors hold (r34, r47, r54, r62c, r62d, r82).
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89_backup")
ROOT = os.environ.get("R89_ROOT") or os.getcwd()
G = "engine/gpu/"
S = G + "shadps4/shader_recompiler/"
R = G + "shadps4/video_core/renderer_vulkan/"
L = G + "shim/lifter/"
HEADER = G + "shim/bbport_wind_sway.h"

NEW = {
    HEADER: r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r89_wind-foliage-sway): plants sway with the shared wind (bbport_wind.h). Only with
// BB_WIND=1 and BB_WIND_SWAY above 0 (the amplitude's scale, default 1, at most 3).
//
// What sways: a draw of the camera pass whose pipeline has object motion and a pixel shader that
// discards (a cut-out), whose vertex shader reads a bone palette of character size (a skeleton),
// and whose vertex stream (the fetch's position stream, by its address and size) RtShadow takes
// for a plant: drawn by the camera pass as a cut-out with a skeleton for LampLoneFrames frames on
// which the sun shadow pass drew skeletons but never this stream (rt_lamp_cards.h, "lone"). That
// verdict is made by the ray traced scene's bookkeeping, so without ray tracing nothing sways.
// Characters, their hair and their cloth have sun shadows, so they never sway.
//
// How (both shader emitters, the recompiler's EmitVertexSway and the lifter's VertexSway, run it
// first in the vertex epilogue, before the motion store and the ray traced capture, so the motion
// vectors and the ray traced scene carry the sway): the clip position c is taken to the world by
// the camera's clip-to-world rows T (RtShadow::ToWorld without its translation: T c is the world
// point minus the camera's position, which keeps float precision far from the world's origin), a
// horizontal displacement d is made there, and c + F (d, 0) is written back, F being the
// projection times the view's rotation. d points along the wind (dir_x, dir_z) and across it:
//   along = clamp(G (Lean + Flutter sin a1), +-MaxAlong), cross = clamp(G Cross sin a2, +-MaxCross)
//   a1 = 2 pi SwayHz t - k s + j q, a2 = 2 pi CrossHz t - k2 s - j q,
//   k = 2 pi SwayHz / v, k2 = 2 pi CrossHz / v, v = max(speed, MinWaveSpeed), j = 2 pi / 3.3 m,
// s and q the world point along and across the wind, so the sway is a wave that travels downwind
// at the wind's mean speed; G is the gust factor at the point (BbWind::GustAt: the gusts travel
// downwind too), read from a table of GustSamples samples GustStep s apart around the camera.
// Lean, Flutter and Cross are scaled by BB_WIND_SWAY and by min(speed, SpeedCap) / 1.5 m/s.
// The displacement is multiplied by smoothstep(0, Height, h) and by the ramp: h is the height of
// the vertex above the lowest point of its mesh seen so far (the lowest world y any vertex of the
// stream had, kept by the GPU with an atomic minimum, one slot of BaseSlots per stream), so the
// roots stay still and the top of a plant Height or taller moves in full; the ramp rises from 0
// to 1 over RampTime s of wind time after a stream gets its slot, so nothing jumps.
//
// Layout (words after the motion params' ring, in the same host visible buffer, so the address
// block is unchanged): per frame slot of the ring (ObjectMotion::FrameSlots) and view (Views a
// frame) ViewWords words (ViewAt: F's 4 rows at ForwardAt, T's 3 rows at ToWorldAt, WindA
// (dir_x, dir_z, camera y, 0), WindB (Lean, Flutter, Cross scaled; a1's phase at the camera),
// WindC (k, j, a2's phase, the gust table's samples per m), WindD (1 / Height, GustMid, GustUpper,
// k2), WindE (MaxAlong, MaxCross, camera x and z, unread), the gust table at TableAt), then
// BaseSlots height keys (BaseAt). Motion param word 7 (0
// before) is the draw's sway word (PackWord): WordOn, the frame slot, the view, the base slot and
// the ramp. Pure: no Vulkan; tested by tests/test_wind_sway.cpp (Displace is the shaders' rule in
// C++, operation for operation).

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <unordered_map>
#include <utility>

#include "bbport_wind.h"

namespace BbWindSway {

inline constexpr float DefaultScale = 1.0f, MaxScale = 3.0f; ///< BB_WIND_SWAY
inline constexpr float Height = 0.75f;      ///< m above the mesh's lowest point for full sway
inline constexpr float RefSpeed = BbWind::DefaultSpeed; ///< m/s at which the amplitudes apply
inline constexpr float SpeedCap = 2.5f;     ///< m/s: a faster wind sways as this one
inline constexpr float Lean = 0.06f;        ///< m: steady lean downwind (times the gust factor)
inline constexpr float Flutter = 0.06f;     ///< m: the swing along the wind, either way
inline constexpr float Cross = 0.025f;      ///< m: the swing across the wind, either way
inline constexpr float SwayHz = 0.7f;       ///< Hz of the swing along the wind
inline constexpr float CrossHz = 1.3f;      ///< Hz of the swing across it
inline constexpr float MinWaveSpeed = 0.5f; ///< m/s: the slowest the sway wave travels
inline constexpr float CrossWavelength = 3.3f; ///< m: the phase's change across the wind
inline constexpr float MaxAlong = 0.4f, MaxCross = 0.15f; ///< m: the displacement's limits
inline constexpr std::uint32_t GustSamples = 64, GustMid = 32;
inline constexpr float GustStep = 1.0f;     ///< s of wind time between gust samples
inline constexpr float GustUpper = 62.999f; ///< the largest table position read
inline constexpr float HeightBias = 8192.0f; ///< m added to a world y before it is a key
inline constexpr std::uint32_t ResetKey = 0x7f7fffffu; ///< a slot's key before any vertex
inline constexpr float FiniteMost = 1.0e6f; ///< m: larger (or not finite) values do not sway
inline constexpr std::uint32_t FrameSlots = 4, Views = 2;
inline constexpr std::uint32_t ForwardAt = 0, ToWorldAt = 16, WindA = 28, WindB = 32, WindC = 36,
                               WindD = 40, WindE = 44, TableAt = 48;
inline constexpr std::uint32_t ViewWords = TableAt + GustSamples;
inline constexpr std::uint32_t BaseAt = FrameSlots * Views * ViewWords;
inline constexpr std::uint32_t BaseSlots = 1024;
inline constexpr std::uint32_t RegionWords = BaseAt + BaseSlots;
inline constexpr std::uint32_t RegionBytes = RegionWords * 4;
inline constexpr std::uint32_t WordOn = 0x80000000u;
inline constexpr std::uint32_t ConstantsBytes = 864; ///< the camera's vertex constants
inline constexpr std::uint32_t ReuseFrames = 8; ///< frames a slot rests before another stream
inline constexpr double RampTime = 1.0;         ///< s of wind time from still to full sway
inline constexpr std::uint32_t ReportFrames = 600;
inline constexpr float TwoPi = 6.28318530717958647692f;
inline constexpr float InvTwoPi = 0.15915494309189533577f;

static_assert(ViewWords == 112 && ViewWords % 4 == 0 && TableAt % 4 == 0 && WindE % 4 == 0);
static_assert(BaseAt % 4 == 0 && RegionBytes == 7680);
static_assert(BaseSlots <= 1024 && FrameSlots <= 4 && Views <= 2, "PackWord's fields");
static_assert(GustMid * 2 == GustSamples && GustUpper < float(GustSamples - 1));

[[nodiscard]] constexpr std::uint32_t ViewAt(std::uint32_t frame_slot, std::uint32_t view) {
    return (frame_slot * Views + view) * ViewWords;
}

struct Knob {
    bool wind = false; ///< BB_WIND=1
    bool on = false;   ///< wind and scale above 0
    float scale = DefaultScale;
    float gusts = BbWind::DefaultGusts; ///< BB_WIND_GUSTS as the wind reads it
};

/// A number as Rasterizer::WindOnFrameEnd reads one: missing, empty, unreadable or not finite
/// is the fallback.
[[nodiscard]] inline float ParseNumber(const char* text, float fallback) {
    if (text == nullptr || text[0] == 0) {
        return fallback;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    return end != text && std::isfinite(value) ? value : fallback;
}

[[nodiscard]] inline Knob ParseKnob(const char* wind, const char* sway, const char* gusts) {
    Knob k;
    k.wind = wind != nullptr && wind[0] == '1';
    k.scale = std::clamp(ParseNumber(sway, DefaultScale), 0.0f, MaxScale);
    BbWind::Params p;
    p.gusts = ParseNumber(gusts, BbWind::DefaultGusts);
    k.gusts = BbWind::Sanitize(p).gusts;
    k.on = k.wind && k.scale > 0.0f;
    return k;
}

/// Read once, at the first use (the pipeline cache's first key, or the motion buffer).
[[nodiscard]] inline const Knob& KnobOnce() {
    static const Knob knob = ParseKnob(std::getenv("BB_WIND"), std::getenv("BB_WIND_SWAY"),
                                       std::getenv("BB_WIND_GUSTS"));
    return knob;
}

[[nodiscard]] constexpr std::uint32_t PackWord(std::uint32_t frame_slot, std::uint32_t view,
                                               std::uint32_t base_slot, std::uint32_t ramp) {
    return WordOn | (frame_slot & 3u) | ((view & 1u) << 2) | ((base_slot & 1023u) << 3) |
           ((ramp & 255u) << 16);
}

struct Unpacked {
    bool on = false;
    std::uint32_t frame_slot = 0, view = 0, base_slot = 0, ramp = 0;
};

[[nodiscard]] constexpr Unpacked Unpack(std::uint32_t word) {
    return {(word & WordOn) != 0, word & 3u, (word >> 2) & 1u, (word >> 3) & 1023u,
            (word >> 16) & 255u};
}

[[nodiscard]] inline std::uint32_t RampByte(double ramp) {
    if (!(ramp > 0.0)) {
        return 0;
    }
    return std::uint32_t(std::lround(std::min(ramp, 1.0) * 255.0));
}

/// A world y as an unsigned key whose order is the heights' order (y above -HeightBias).
[[nodiscard]] inline std::uint32_t HeightKey(float y) {
    return std::bit_cast<std::uint32_t>(std::max(y + HeightBias, 0.0f));
}

[[nodiscard]] inline float KeyHeight(std::uint32_t key) {
    return std::bit_cast<float>(key) - HeightBias;
}

/// The camera of a draw's 864-byte constants: projection (4x4 rows) at word 52, view to world
/// (3x4 rows) at word 180, as RtShadow::ToWorld reads them.
struct Camera {
    std::array<float, 16> forward{}; ///< rows: clip of a world direction (w = 0)
    std::array<float, 12> to_world{}; ///< rows: world point minus the camera's, of a clip position
    float x = 0.0f, y = 0.0f, z = 0.0f; ///< the camera's world position
};

[[nodiscard]] inline bool Invert4(const double* m, double* out) {
    double a[4][8];
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) {
            a[r][c] = m[r * 4 + c];
            a[r][c + 4] = r == c ? 1.0 : 0.0;
        }
    }
    for (int c = 0; c < 4; ++c) {
        int pivot = c;
        for (int r = c + 1; r < 4; ++r) {
            if (std::fabs(a[r][c]) > std::fabs(a[pivot][c])) {
                pivot = r;
            }
        }
        if (!(std::fabs(a[pivot][c]) > 1e-30)) {
            return false;
        }
        if (pivot != c) {
            for (int k = 0; k < 8; ++k) {
                std::swap(a[c][k], a[pivot][k]);
            }
        }
        const double inv = 1.0 / a[c][c];
        for (int k = 0; k < 8; ++k) {
            a[c][k] *= inv;
        }
        for (int r = 0; r < 4; ++r) {
            if (r != c) {
                const double f = a[r][c];
                for (int k = 0; k < 8; ++k) {
                    a[r][k] -= f * a[c][k];
                }
            }
        }
    }
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) {
            out[r * 4 + c] = a[r][c + 4];
        }
    }
    return true;
}

[[nodiscard]] inline bool CameraOf(const float* constants, Camera& out) {
    double proj[16];
    for (int i = 0; i < 16; ++i) {
        proj[i] = constants[52 + i];
    }
    double inv_proj[16];
    if (!Invert4(proj, inv_proj)) {
        return false;
    }
    const float* iv = constants + 180;
    // RtShadow::ToWorld's rows without the translation's term (for a clip position the inverse
    // projection's w is 1): the world point relative to the camera.
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 4; ++c) {
            double sum = 0.0;
            for (int k = 0; k < 3; ++k) {
                sum += double(iv[r * 4 + k]) * inv_proj[k * 4 + c];
            }
            out.to_world[r * 4 + c] = float(sum);
        }
    }
    // The view's rotation: the inverse of the view to world rows' 3x3 part.
    const double a = iv[0], b = iv[1], c = iv[2], d = iv[4], e = iv[5], f = iv[6], g = iv[8],
                 h = iv[9], i = iv[10];
    const double det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
    if (!(std::fabs(det) > 1e-12)) {
        return false;
    }
    const double rot[9] = {(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
                           (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
                           (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det};
    for (int r = 0; r < 4; ++r) {
        for (int col = 0; col < 3; ++col) {
            double sum = 0.0;
            for (int k = 0; k < 3; ++k) {
                sum += proj[r * 4 + k] * rot[k * 3 + col];
            }
            out.forward[r * 4 + col] = float(sum);
        }
        out.forward[r * 4 + 3] = 0.0f;
    }
    out.x = iv[3];
    out.y = iv[7];
    out.z = iv[11];
    return std::ranges::all_of(out.forward, [](float v) { return std::isfinite(v); }) &&
           std::ranges::all_of(out.to_world, [](float v) { return std::isfinite(v); }) &&
           std::isfinite(out.x) && std::isfinite(out.y) && std::isfinite(out.z);
}

/// The 28 floats a view is known by: projection (word 52) and view to world (word 180).
using ViewKey = std::array<float, 28>;

[[nodiscard]] inline ViewKey KeyOf(const float* constants) {
    ViewKey key{};
    std::memcpy(key.data(), constants + 52, 16 * sizeof(float));
    std::memcpy(key.data() + 16, constants + 180, 12 * sizeof(float));
    return key;
}

[[nodiscard]] inline bool SameKey(const ViewKey& a, const ViewKey& b) {
    return std::memcmp(a.data(), b.data(), sizeof(ViewKey)) == 0;
}

[[nodiscard]] inline double WrapTwoPi(double a) {
    const double two_pi = 6.28318530717958647692;
    double r = std::fmod(a, two_pi);
    if (r < 0.0) {
        r += two_pi;
    }
    return r;
}

/// A view's ViewWords floats for the shaders, of the wind snapshot `s` (BB_WIND_GUSTS `gusts`,
/// BB_WIND_SWAY `scale`).
inline void FillView(const Camera& cam, const BbWind::Snapshot& s, float gusts, float scale,
                     float* out) {
    std::fill(out, out + ViewWords, 0.0f);
    std::copy(cam.forward.begin(), cam.forward.end(), out + ForwardAt);
    std::copy(cam.to_world.begin(), cam.to_world.end(), out + ToWorldAt);
    const float speed = std::isfinite(s.speed) ? std::max(s.speed, 0.0f) : 0.0f;
    const float dx = s.dir_x, dz = s.dir_z;
    const double s_cam = double(cam.x) * dx + double(cam.z) * dz;
    const double q_cam = double(cam.z) * dx - double(cam.x) * dz;
    const float amp = scale * std::min(speed, SpeedCap) / RefSpeed;
    const double wave = std::max(double(speed), double(MinWaveSpeed));
    const double two_pi = 6.28318530717958647692;
    const double k = two_pi * SwayHz / wave;
    const double k2 = two_pi * CrossHz / wave;
    const double j = two_pi / CrossWavelength;
    const double phase0 = WrapTwoPi(two_pi * SwayHz * s.time - k * s_cam + j * q_cam);
    const double phase1 = WrapTwoPi(two_pi * CrossHz * s.time - k2 * s_cam - j * q_cam);
    const double gust_speed = std::max(double(speed), 0.1);
    out[WindA + 0] = dx;
    out[WindA + 1] = dz;
    out[WindA + 2] = cam.y;
    out[WindB + 0] = Lean * amp;
    out[WindB + 1] = Flutter * amp;
    out[WindB + 2] = Cross * amp;
    out[WindB + 3] = float(phase0);
    out[WindC + 0] = float(k);
    out[WindC + 1] = float(j);
    out[WindC + 2] = float(phase1);
    out[WindC + 3] = float(1.0 / (gust_speed * GustStep));
    out[WindD + 0] = 1.0f / Height;
    out[WindD + 1] = float(GustMid);
    out[WindD + 2] = GustUpper;
    out[WindD + 3] = float(k2);
    out[WindE + 0] = MaxAlong;
    out[WindE + 1] = MaxCross;
    out[WindE + 2] = cam.x; // (the shaders do not read these two)
    out[WindE + 3] = cam.z;
    for (std::uint32_t i = 0; i < GustSamples; ++i) {
        const double t = s.time - s_cam / gust_speed + (double(i) - GustMid) * GustStep;
        out[TableAt + i] = BbWind::Gust(t, gusts);
    }
}

/// An angle taken into [-pi, pi) (the shaders' sin is exact only there).
[[nodiscard]] inline float Wrap(float a) {
    return a - TwoPi * std::floor(a * InvTwoPi + 0.5f);
}

/// What the shaders do to one vertex: `view` its ViewWords floats, `clip` the clip position,
/// `stored` its slot's height key, `ramp` the sway word's ramp / 255. The clip position written
/// back; `key` (when not null) the key the vertex offers the slot (ResetKey: none).
[[nodiscard]] inline std::array<float, 4> Displace(const float* view, const std::array<float, 4>& clip,
                                                   std::uint32_t stored, float ramp,
                                                   std::uint32_t* key = nullptr) {
    const auto dot = [&](std::uint32_t at) {
        return view[at] * clip[0] + view[at + 1] * clip[1] + view[at + 2] * clip[2] +
               view[at + 3] * clip[3];
    };
    const float rx = dot(ToWorldAt), rz = dot(ToWorldAt + 8);
    const float wy = dot(ToWorldAt + 4) + view[WindA + 2];
    if (key != nullptr) {
        *key = std::fabs(wy) < FiniteMost ? HeightKey(wy) : ResetKey;
    }
    const float h = wy - KeyHeight(stored);
    const bool fin = std::fabs(h) + std::fabs(rx) + std::fabs(rz) < FiniteMost;
    if (!fin) {
        return clip;
    }
    const float t = std::clamp(h * view[WindD], 0.0f, 1.0f);
    const float w = t * t * (3.0f - 2.0f * t) * ramp;
    const float dx = view[WindA], dz = view[WindA + 1];
    const float s = rx * dx + rz * dz;
    const float q = rz * dx - rx * dz;
    const float u = std::clamp(view[WindD + 1] - s * view[WindC + 3], 0.0f, view[WindD + 2]);
    const std::uint32_t i = std::min(std::uint32_t(std::floor(u)), GustSamples - 2);
    const float f = u - float(i);
    const float g0 = view[TableAt + i], g1 = view[TableAt + i + 1];
    const float g = g0 + (g1 - g0) * f;
    const float a1 = Wrap(view[WindB + 3] - view[WindC] * s + view[WindC + 1] * q);
    const float a2 = Wrap(view[WindC + 2] - view[WindD + 3] * s - view[WindC + 1] * q);
    const float along =
        std::clamp(g * (view[WindB] + view[WindB + 1] * std::sin(a1)), -view[WindE], view[WindE]);
    const float cross = std::clamp(g * (view[WindB + 2] * std::sin(a2)), -view[WindE + 1],
                                   view[WindE + 1]);
    const float ddx = w * (dx * along - dz * cross);
    const float ddz = w * (dz * along + dx * cross);
    std::array<float, 4> out = clip;
    for (std::uint32_t r = 0; r < 4; ++r) {
        out[r] = clip[r] + (view[ForwardAt + r * 4] * ddx + view[ForwardAt + r * 4 + 2] * ddz);
    }
    return out;
}

/// The base slots: one per plant stream (its position stream's address), with the bytes of
/// vertices it was taken with and when. A stream keeps its slot while it is drawn; a slot not
/// drawn for ReuseFrames frames may go to another stream (the oldest first). Another size at the
/// stream's address is another mesh: the slot starts again (its key reset, the ramp from 0).
class Slots {
public:
    struct Taken {
        bool ok = false;
        std::uint32_t slot = 0;
        bool reset = false;    ///< the caller writes ResetKey to the slot's key
        std::uint32_t ramp = 0; ///< 0-255
    };

    Taken Take(std::uint64_t stream, std::uint32_t size, std::uint64_t frame, double time) {
        if (stream == 0) {
            return {};
        }
        const auto found = by_stream.find(stream);
        if (found != by_stream.end()) {
            Slot& slot = slots[found->second];
            slot.last = frame;
            bool reset = false;
            if (size != 0 && slot.size != size) {
                slot.size = size;
                slot.time = time;
                reset = true;
            }
            return {true, found->second, reset, RampByte((time - slot.time) / RampTime)};
        }
        std::uint32_t best = BaseSlots;
        std::uint64_t oldest = std::numeric_limits<std::uint64_t>::max();
        for (std::uint32_t i = 0; i < BaseSlots; ++i) {
            const Slot& slot = slots[i];
            if (slot.stream == 0) {
                best = i;
                break;
            }
            if (slot.last + ReuseFrames < frame && slot.last < oldest) {
                oldest = slot.last;
                best = i;
            }
        }
        if (best == BaseSlots) {
            return {};
        }
        if (slots[best].stream != 0) {
            by_stream.erase(slots[best].stream);
        }
        slots[best] = {stream, size, frame, time};
        by_stream.emplace(stream, best);
        return {true, best, true, 0};
    }

    /// Slots drawn within the last ReuseFrames frames.
    [[nodiscard]] std::uint32_t InUse(std::uint64_t frame) const {
        std::uint32_t n = 0;
        for (const Slot& slot : slots) {
            n += slot.stream != 0 && slot.last + ReuseFrames >= frame ? 1u : 0u;
        }
        return n;
    }

private:
    struct Slot {
        std::uint64_t stream = 0;
        std::uint32_t size = 0;
        std::uint64_t last = 0;
        double time = 0.0;
    };
    std::array<Slot, BaseSlots> slots{};
    std::unordered_map<std::uint64_t, std::uint32_t> by_stream;
};

/// Counts for the log's line every ReportFrames frames.
struct Stats {
    std::uint64_t draws = 0;  ///< skinned draws of sway pipelines
    std::uint64_t plants = 0; ///< of them, plants
    std::uint64_t swayed = 0; ///< plants given a sway word
    std::uint64_t ramping = 0; ///< of those, with a ramp below 255
    std::uint64_t no_rt = 0, no_camera = 0, views_full = 0, no_slot = 0, no_region = 0;
};

} // namespace BbWindSway
''',
    "engine/tests/test_wind_sway.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r89_wind-foliage-sway): the plant sway's knob, sway word, layout, camera math, the
// shaders' rule in C++ (Displace), the gust table and the base slots (gpu/shim/bbport_wind_sway.h).
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#include "gpu/shim/bbport_wind_sway.h"

using namespace BbWindSway;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

bool Near(double a, double b, double tolerance) {
    return std::fabs(a - b) <= tolerance;
}

// A camera's 864-byte constants: a perspective projection (rows) at word 52 and the view to
// world rows (yaw `yaw`, pitch `pitch`, position `eye`) at word 180.
std::array<float, 216> Constants(double yaw, double pitch, const std::array<double, 3>& eye) {
    std::array<float, 216> c{};
    const double f = 1.0 / std::tan(0.5 * 1.0), aspect = 16.0 / 9.0, z_near = 0.1, z_far = 500.0;
    const double proj[16] = {f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, z_far / (z_near - z_far),
                             z_far * z_near / (z_near - z_far), 0, 0, -1, 0};
    for (int i = 0; i < 16; ++i) {
        c[52 + i] = float(proj[i]);
    }
    const double cy = std::cos(yaw), sy = std::sin(yaw), cp = std::cos(pitch), sp = std::sin(pitch);
    // columns: right, up, back (view space x, y, z in the world)
    const double right[3] = {cy, 0, -sy};
    const double up[3] = {sy * sp, cp, cy * sp};
    const double back[3] = {sy * cp, -sp, cy * cp};
    for (int r = 0; r < 3; ++r) {
        c[180 + r * 4 + 0] = float(right[r]);
        c[180 + r * 4 + 1] = float(up[r]);
        c[180 + r * 4 + 2] = float(back[r]);
        c[180 + r * 4 + 3] = float(eye[r]);
    }
    return c;
}

// The clip position of world point `w` for those constants (projection times the inverse view).
std::array<float, 4> ClipOf(const std::array<float, 216>& c, const std::array<double, 3>& w) {
    const float* iv = c.data() + 180;
    const double rel[3] = {w[0] - iv[3], w[1] - iv[7], w[2] - iv[11]};
    double v[4] = {0, 0, 0, 1};
    for (int k = 0; k < 3; ++k) {
        // the rotation is orthonormal: its inverse is its transpose
        v[k] = double(iv[0 * 4 + k]) * rel[0] + double(iv[1 * 4 + k]) * rel[1] +
               double(iv[2 * 4 + k]) * rel[2];
    }
    std::array<float, 4> clip{};
    for (int r = 0; r < 4; ++r) {
        double sum = 0;
        for (int k = 0; k < 4; ++k) {
            sum += double(c[52 + r * 4 + k]) * v[k];
        }
        clip[r] = float(sum);
    }
    return clip;
}

// The world point of a clip position: the view's rows give it relative to the camera, whose
// position the view holds at WindE + 2 (x), WindA + 2 (y) and WindE + 3 (z).
std::array<double, 3> WorldOf(const float* view, const std::array<float, 4>& clip) {
    std::array<double, 3> w{};
    const double camera[3] = {view[WindE + 2], view[WindA + 2], view[WindE + 3]};
    for (int r = 0; r < 3; ++r) {
        double sum = camera[r];
        for (int k = 0; k < 4; ++k) {
            sum += double(view[ToWorldAt + r * 4 + k]) * clip[k];
        }
        w[r] = sum;
    }
    return w;
}

BbWind::Snapshot Wind(double time, float deg, float speed) {
    BbWind::Snapshot s;
    s.on = true;
    s.time = time;
    s.direction_deg = deg;
    const auto dir = BbWind::DirectionXZ(deg);
    s.dir_x = dir[0];
    s.dir_z = dir[1];
    s.speed = speed;
    return s;
}

std::array<float, ViewWords> ViewOf(const std::array<float, 216>& c, const BbWind::Snapshot& s,
                                    float gusts, float scale) {
    Camera cam;
    const bool ok = CameraOf(c.data(), cam);
    Expect(ok, "the camera of the test constants");
    std::array<float, ViewWords> view{};
    FillView(cam, s, gusts, scale, view.data());
    return view;
}

double Horizontal(const std::array<double, 3>& a, const std::array<double, 3>& b) {
    return std::hypot(a[0] - b[0], a[2] - b[2]);
}
} // namespace

int main() {
    // The knob: BB_WIND=1 and a scale above 0; numbers as the wind reads them, then 0-3.
    {
        Expect(!ParseKnob(nullptr, nullptr, nullptr).on, "nothing set: off");
        const Knob plain = ParseKnob("1", nullptr, nullptr);
        Expect(plain.on && plain.scale == DefaultScale && plain.gusts == BbWind::DefaultGusts,
               "BB_WIND=1 alone: on at the default scale and gusts");
        Expect(!ParseKnob("1", "0", nullptr).on, "BB_WIND_SWAY=0: off");
        Expect(!ParseKnob("1", "-2", nullptr).on, "a negative scale: 0, off");
        Expect(ParseKnob("1", "2.5", nullptr).scale == 2.5f, "a scale is read");
        Expect(ParseKnob("1", "9", nullptr).scale == MaxScale, "a scale above 3 is 3");
        Expect(ParseKnob("1", "abc", nullptr).scale == DefaultScale, "unreadable: the default");
        Expect(ParseKnob("1", "nan", nullptr).scale == DefaultScale, "not finite: the default");
        Expect(ParseKnob("1", "", nullptr).scale == DefaultScale, "empty: the default");
        Expect(!ParseKnob("0", "2", nullptr).on && !ParseKnob("2", "2", nullptr).on,
               "BB_WIND other than 1: off");
        Expect(ParseKnob("1", nullptr, "0.8").gusts == 0.8f, "BB_WIND_GUSTS is read");
        Expect(ParseKnob("1", nullptr, "5").gusts == BbWind::MaxGusts, "gusts above 1 are 1");
        Expect(ParseKnob("1", nullptr, "x").gusts == BbWind::DefaultGusts, "gusts unreadable");
    }

    // The sway word: every field comes back; WordOn always set, so a word is never 0.
    {
        bool same = true;
        for (std::uint32_t slot = 0; slot < FrameSlots; ++slot) {
            for (std::uint32_t view = 0; view < Views; ++view) {
                for (std::uint32_t base : {0u, 1u, 511u, BaseSlots - 1}) {
                    for (std::uint32_t ramp : {0u, 1u, 128u, 255u}) {
                        const std::uint32_t word = PackWord(slot, view, base, ramp);
                        const Unpacked u = Unpack(word);
                        same &= word != 0 && u.on && u.frame_slot == slot && u.view == view &&
                                u.base_slot == base && u.ramp == ramp;
                    }
                }
            }
        }
        Expect(same, "PackWord and Unpack");
        Expect(!Unpack(0).on, "word 0 (every draw without sway): off");
        Expect(RampByte(-1.0) == 0 && RampByte(0.0) == 0 && RampByte(0.5) == 128 &&
                   RampByte(1.0) == 255 && RampByte(7.0) == 255 && RampByte(std::nan("")) == 0,
               "RampByte");
    }

    // The layout: whole vec4 rows, the views then the keys, inside RegionBytes.
    {
        Expect(ViewAt(FrameSlots - 1, Views - 1) + ViewWords == BaseAt, "views end at BaseAt");
        Expect(BaseAt + BaseSlots == RegionWords && RegionWords * 4 == RegionBytes, "region");
        Expect(TableAt + GustSamples == ViewWords && ToWorldAt == ForwardAt + 16 &&
                   WindA == ToWorldAt + 12,
               "a view's rows");
    }

    // The height keys: their order is the heights' order; ResetKey is above every finite key.
    {
        bool ordered = true, back = true;
        float last = -8000.0f;
        for (int i = 0; i <= 4000; ++i) {
            const float y = -8000.0f + float(i) * 4.0f + 0.37f;
            ordered &= HeightKey(y) >= HeightKey(last);
            last = y;
            if (std::fabs(y) < 1000.0f) {
                back &= Near(KeyHeight(HeightKey(y)), y, 1e-3);
            }
        }
        Expect(ordered, "HeightKey keeps the order");
        Expect(back, "KeyHeight undoes HeightKey");
        Expect(HeightKey(FiniteMost) < ResetKey, "ResetKey is above every key a vertex offers");
        Expect(HeightKey(-9000.0f) == 0, "far below the bias: key 0");
    }

    // The camera: to_world undoes the projection and view; F takes a world direction to clip.
    {
        const auto c = Constants(0.7, -0.2, {120.5, 14.25, -310.0});
        const auto view = ViewOf(c, Wind(10.0, 225.0f, 1.5f), 0.5f, 1.0f);
        double worst = 0.0, worst_d = 0.0;
        for (int i = 0; i < 50; ++i) {
            const double a = 0.37 * i;
            // points in front of the camera (its -z), 2 to 40 m away
            const std::array<double, 3> w = {120.5 - std::sin(0.7) * (2 + 0.76 * i) + std::cos(a),
                                             14.25 + 0.3 * std::sin(a * 3),
                                             -310.0 - std::cos(0.7) * (2 + 0.76 * i) + std::sin(a)};
            const auto clip = ClipOf(c, w);
            const auto back = WorldOf(view.data(), clip);
            for (int k = 0; k < 3; ++k) {
                worst = std::max(worst, std::fabs(back[k] - w[k]));
            }
            const double d[3] = {0.1 * std::cos(a), 0.0, 0.1 * std::sin(a)};
            std::array<float, 4> moved = clip;
            for (int r = 0; r < 4; ++r) {
                moved[r] = float(clip[r] + view[ForwardAt + r * 4] * d[0] +
                                 view[ForwardAt + r * 4 + 1] * d[1] +
                                 view[ForwardAt + r * 4 + 2] * d[2]);
            }
            const auto moved_back = WorldOf(view.data(), moved);
            for (int k = 0; k < 3; ++k) {
                worst_d = std::max(worst_d, std::fabs(moved_back[k] - (w[k] + d[k])));
            }
        }
        Expect(worst < 1e-3, "to_world takes a clip position back to its world point");
        Expect(worst_d < 1e-3, "clip + F d is the world point moved by d");
        Camera cam;
        Expect(CameraOf(c.data(), cam) && cam.x == 120.5f && cam.y == 14.25f && cam.z == -310.0f,
               "the camera's position");
        std::array<float, 216> flat = c;
        std::fill(flat.begin() + 52, flat.begin() + 68, 0.0f);
        Expect(!CameraOf(flat.data(), cam), "a projection that cannot be inverted: no camera");
        Expect(SameKey(KeyOf(c.data()), KeyOf(c.data())) &&
                   !SameKey(KeyOf(c.data()), KeyOf(flat.data())),
               "the view key");
    }

    // The rule: still where it must be, growing with the height, horizontal, within its limits.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        const float base = 0.5f;
        const std::uint32_t stored = HeightKey(base);
        const auto at = [&](double up) {
            return std::array<double, 3>{10.0 - std::sin(0.3) * 6.0, base + up,
                                         20.0 - std::cos(0.3) * 6.0};
        };
        // the wind time (of 0 to 10 s) at which the top of this plant is moved most
        double when = 0.0, most = -1.0;
        for (int i = 0; i <= 100; ++i) {
            const auto v = ViewOf(c, Wind(0.1 * i, 225.0f, 1.5f), 0.5f, 1.0f);
            const auto clip = ClipOf(c, at(1.2));
            const double moved = Horizontal(WorldOf(v.data(), Displace(v.data(), clip, stored, 1.0f)),
                                            WorldOf(v.data(), clip));
            if (moved > most) {
                most = moved;
                when = 0.1 * i;
            }
        }
        Expect(most > 0.03, "at 1.5 m/s the top of a plant moves more than 3 cm");
        const auto view = ViewOf(c, Wind(when, 225.0f, 1.5f), 0.5f, 1.0f);
        Expect(view[WindB] == Lean && view[WindB + 1] == Flutter && view[WindB + 2] == Cross,
               "at 1.5 m/s and scale 1 the amplitudes are the constants");
        const auto top = ClipOf(c, at(1.2));
        const auto same = [](const std::array<float, 4>& a, const std::array<float, 4>& b) {
            return std::memcmp(a.data(), b.data(), sizeof(a)) == 0;
        };
        Expect(same(Displace(view.data(), top, stored, 0.0f), top), "ramp 0: unchanged");
        Expect(same(Displace(view.data(), top, ResetKey, 1.0f), top),
               "a slot without a key yet: unchanged");
        const auto root = ClipOf(c, at(0.0));
        const auto root_moved = WorldOf(view.data(), Displace(view.data(), root, stored, 1.0f));
        Expect(Horizontal(root_moved, WorldOf(view.data(), root)) < 1e-4, "the roots stay");
        const auto below = ClipOf(c, at(-0.3));
        Expect(Horizontal(WorldOf(view.data(), Displace(view.data(), below, stored, 1.0f)),
                          WorldOf(view.data(), below)) < 1e-4,
               "below the lowest point seen: still");
        std::vector<double> moves;
        for (const double up : {0.1, 0.3, 0.5, 0.75, 1.5}) {
            const auto clip = ClipOf(c, at(up));
            const auto before = WorldOf(view.data(), clip);
            const auto after = WorldOf(view.data(), Displace(view.data(), clip, stored, 1.0f));
            moves.push_back(Horizontal(after, before));
            Expect(std::fabs(after[1] - before[1]) < 2e-3, "the sway is horizontal");
        }
        Expect(moves[0] < moves[1] && moves[1] < moves[2] && moves[2] < moves[3],
               "the sway grows with the height");
        Expect(Near(moves[3], moves[4], 2e-3), "from Height up: full sway");
        const auto half = WorldOf(view.data(), Displace(view.data(), top, stored, 0.5f));
        const auto full = WorldOf(view.data(), Displace(view.data(), top, stored, 1.0f));
        const auto top_world = WorldOf(view.data(), top);
        Expect(Near(Horizontal(half, top_world) * 2.0, Horizontal(full, top_world), 3e-3),
               "the ramp scales the sway");
        std::uint32_t key = 0;
        (void)Displace(view.data(), ClipOf(c, at(-0.2)), stored, 1.0f, &key);
        Expect(key < stored, "a vertex below the key offers a smaller one");
        (void)Displace(view.data(), top, stored, 1.0f, &key);
        Expect(key > stored, "one above does not lower it");

        const auto still = ViewOf(c, Wind(33.3, 225.0f, 0.0f), 0.5f, 1.0f);
        Expect(Horizontal(WorldOf(still.data(), Displace(still.data(), top, stored, 1.0f)),
                          WorldOf(still.data(), top)) < 1e-5,
               "no wind: still");
        double worst = 0.0;
        for (int i = 0; i < 200; ++i) {
            const auto strong = ViewOf(c, Wind(0.37 * i, 225.0f, 4.0f), 1.0f, MaxScale);
            const auto after = WorldOf(strong.data(), Displace(strong.data(), top, stored, 1.0f));
            worst = std::max(worst, Horizontal(after, WorldOf(strong.data(), top)));
        }
        Expect(worst <= std::hypot(double(MaxAlong), double(MaxCross)) + 3e-3,
               "the strongest wind stays within MaxAlong and MaxCross");
        Expect(worst > 0.3, "the strongest wind reaches the limits");
    }

    // The gusts: the table holds BbWind::GustAt at the points it stands for, and the sway is a
    // pattern that travels downwind at the wind's speed (gusts included).
    {
        const auto c = Constants(1.1, -0.15, {-40.0, 5.0, 75.0});
        const float speed = 1.5f, gusts = 0.8f;
        const auto s = Wind(812.25, 200.0f, speed);
        const auto view = ViewOf(c, s, gusts, 1.0f);
        double worst = 0.0;
        for (std::uint32_t i = 0; i < GustSamples; ++i) {
            const double s_rel = -(double(i) - GustMid) * speed * GustStep;
            const double x = -40.0 + s_rel * s.dir_x, z = 75.0 + s_rel * s.dir_z;
            const float truth =
                BbWind::GustAt(s.time, gusts, float(x), float(z), s.dir_x, s.dir_z, speed);
            worst = std::max(worst, double(std::fabs(view[TableAt + i] - truth)));
        }
        Expect(worst < 1e-3, "the gust table holds GustAt");

        const double dt = 2.0 * GustStep;
        const auto later = ViewOf(c, Wind(s.time + dt, 200.0f, speed), gusts, 1.0f);
        const std::uint32_t stored = HeightKey(0.0f);
        double moved_worst = 0.0;
        for (int i = 0; i < 20; ++i) {
            const double ahead = 1.0 + 0.9 * i;
            const std::array<double, 3> p = {-40.0 - std::sin(1.1) * ahead, 1.0,
                                             75.0 - std::cos(1.1) * ahead};
            const std::array<double, 3> q = {p[0] + speed * dt * s.dir_x, 1.0,
                                             p[2] + speed * dt * s.dir_z};
            const auto cp = ClipOf(c, p), cq = ClipOf(c, q);
            const auto dp = WorldOf(view.data(), Displace(view.data(), cp, stored, 1.0f));
            const auto dq = WorldOf(later.data(), Displace(later.data(), cq, stored, 1.0f));
            const auto bp = WorldOf(view.data(), cp), bq = WorldOf(later.data(), cq);
            for (int k : {0, 2}) {
                moved_worst = std::max(moved_worst, std::fabs((dp[k] - bp[k]) - (dq[k] - bq[k])));
            }
        }
        Expect(moved_worst < 3e-3, "the sway travels downwind at the wind's speed");
    }

    // The base slots.
    {
        Slots slots;
        auto a = slots.Take(0x1000, 4096, 10, 5.0);
        Expect(a.ok && a.reset && a.ramp == 0, "a new stream: a slot, reset, ramp 0");
        auto again = slots.Take(0x1000, 4096, 10, 5.25);
        Expect(again.ok && again.slot == a.slot && !again.reset && again.ramp == 64,
               "the same stream: its slot, the ramp rising");
        Expect(slots.Take(0x1000, 4096, 40, 9.0).ramp == 255, "after RampTime: full");
        auto resized = slots.Take(0x1000, 8192, 41, 9.5);
        Expect(resized.ok && resized.slot == a.slot && resized.reset && resized.ramp == 0,
               "another size at the address: reset, the ramp from 0");
        Expect(!slots.Take(0, 4096, 41, 9.5).ok, "no stream: no slot");
        bool all = true;
        for (std::uint64_t i = 1; i < BaseSlots; ++i) {
            all &= slots.Take(0x100000 + i * 64, 1024, 41, 9.5).ok;
        }
        Expect(all && slots.InUse(41) == BaseSlots, "every slot taken");
        Expect(!slots.Take(0x900000, 1024, 41, 9.5).ok, "full: no slot");
        Expect(!slots.Take(0x900000, 1024, 41 + ReuseFrames, 9.5).ok,
               "a slot rests ReuseFrames frames");
        // only 0x1000 is drawn on 49; the oldest of the others goes
        Expect(slots.Take(0x1000, 8192, 49, 10.0).slot == a.slot, "a drawn stream keeps its slot");
        const auto reused = slots.Take(0x900000, 1024, 50, 10.0);
        Expect(reused.ok && reused.reset && reused.slot != a.slot, "a rested slot is reused");
        Expect(slots.Take(0x1000, 8192, 50, 10.0).slot == a.slot, "and the drawn one kept");
    }

    if (failures == 0) {
        std::printf("wind-sway-test: ok\n");
    }
    return failures == 0 ? 0 : 1;
}
''',
}

SWAY_SPIRV = r'''// bbport (r89_wind-foliage-sway): with MotionVectors::Sway (BB_WIND=1 and BB_WIND_SWAY above 0;
// a motion pipeline whose pixel shader discards) a draw whose motion param word 7 has
// BbWindSway::WordOn set is a plant (Rasterizer::WindSwayWord): its clip position is moved by the
// wind before the motion store and the capture read it, and the vertex offers its world height
// to its mesh's base slot (an atomic minimum, only when lower). bbport_wind_sway.h holds the rule
// and its layout; BbWindSway::Displace is this code in C++ and the lifter's VertexSway the same
// in the lifter. Every other draw (word 7 is 0) branches around it. No local variable: the
// results are stored inside the branch.
static void EmitVertexSway(EmitContext& ctx) {
    namespace W = BbWindSway;
    const Id u32_type = ctx.U32[1];
    const Id f32_type = ctx.F32[1];
    const Id bool_type = ctx.U1[1];
    const Id param_ptr = ctx.OpAccessChain(ctx.TypePointer(spv::StorageClass::PushConstant, u32_type),
                                           ctx.push_data_block,
                                           ctx.ConstU32(PushData::MotionParamIndex));
    Id param_index = ctx.OpLoad(u32_type, param_ptr);
    if (MotionVectors::Kind(ctx.runtime_info.hw.vs.motion_vectors) == MotionVectors::VertexBoth) {
        param_index = ctx.OpBitwiseAnd(u32_type, param_index, ctx.ConstU32(0xffffU));
    }
    param_index = ctx.OpSelect(u32_type,
                               ctx.OpULessThan(bool_type, param_index,
                                               ctx.ConstU32(MotionVectors::ParamsCapacity)),
                               param_index, ctx.u32_zero_value);
    const Id params_address = ctx.OpLoad(
        ctx.U64, ctx.OpAccessChain(ctx.TypePointer(spv::StorageClass::Uniform, ctx.U64),
                                   ctx.motion_addresses, ctx.ConstU32(0u)));
    const Id u32x4_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, ctx.U32[4]);
    const Id f32x4_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, ctx.F32[4]);
    const Id u32_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, u32_type);
    const Id f32_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, f32_type);
    const auto at = [&](Id base, u64 bytes) {
        return ctx.OpIAdd(ctx.U64, base, ctx.Constant(ctx.U64, bytes));
    };
    const auto scaled = [&](Id base, Id index, u64 stride) {
        return ctx.OpIAdd(ctx.U64, base,
                          ctx.OpIMul(ctx.U64, ctx.OpUConvert(ctx.U64, index),
                                     ctx.Constant(ctx.U64, stride)));
    };
    const Id offsets = ctx.OpLoad(
        ctx.U32[4],
        ctx.OpConvertUToPtr(u32x4_ptr, at(scaled(params_address, param_index, 32u), 16u)),
        spv::MemoryAccessMask::Aligned, 16u);
    const Id word = ctx.OpCompositeExtract(u32_type, offsets, 3u);
    const Id on = ctx.OpINotEqual(bool_type, ctx.OpBitwiseAnd(u32_type, word, ctx.ConstU32(W::WordOn)),
                                  ctx.u32_zero_value);
    const Id sway_label = ctx.OpLabel();
    const Id sway_merge = ctx.OpLabel();
    ctx.OpSelectionMerge(sway_merge, spv::SelectionControlMask::MaskNone);
    ctx.OpBranchConditional(on, sway_label, sway_merge);
    ctx.AddLabel(sway_label);
    const auto field = [&](u32 offset, u32 count) {
        return ctx.OpBitFieldUExtract(u32_type, word, ctx.ConstU32(offset), ctx.ConstU32(count));
    };
    const auto f = [&](float value) { return ctx.Constant(f32_type, value); };
    const Id region = at(params_address, u64(MotionVectors::ParamsCapacity) * 32u);
    const Id view_index = ctx.OpIAdd(u32_type, ctx.OpIMul(u32_type, field(0u, 2u), ctx.ConstU32(W::Views)),
                                     field(2u, 1u));
    const Id view = scaled(region, view_index, u64(W::ViewWords) * 4u);
    const Id base_ptr = ctx.OpConvertUToPtr(u32_ptr, scaled(at(region, u64(W::BaseAt) * 4u),
                                                            field(3u, 10u), 4u));
    const Id ramp = ctx.OpFMul(f32_type, ctx.OpConvertUToF(f32_type, field(16u, 8u)), f(1.0f / 255.0f));
    const auto row = [&](u32 word_at) {
        return ctx.OpLoad(ctx.F32[4], ctx.OpConvertUToPtr(f32x4_ptr, at(view, u64(word_at) * 4u)),
                          spv::MemoryAccessMask::Aligned, 16u);
    };
    const auto comp = [&](Id vec, u32 i) { return ctx.OpCompositeExtract(f32_type, vec, i); };
    const auto add = [&](Id a, Id b) { return ctx.OpFAdd(f32_type, a, b); };
    const auto sub = [&](Id a, Id b) { return ctx.OpFSub(f32_type, a, b); };
    const auto mul = [&](Id a, Id b) { return ctx.OpFMul(f32_type, a, b); };
    const auto wrap = [&](Id a) {
        return sub(a, mul(f(W::TwoPi), ctx.OpFloor(f32_type, add(mul(a, f(W::InvTwoPi)), f(0.5f)))));
    };
    const Id position = ctx.OpLoad(ctx.F32[4], ctx.output_position);
    const Id wind_a = row(W::WindA);
    // x and z relative to the camera; y in the world (plus the camera's height, WindA.z)
    const Id rx = ctx.OpDot(f32_type, row(W::ToWorldAt), position);
    const Id wy = add(ctx.OpDot(f32_type, row(W::ToWorldAt + 4), position), comp(wind_a, 2u));
    const Id rz = ctx.OpDot(f32_type, row(W::ToWorldAt + 8), position);
    const Id wind_b = row(W::WindB);
    const Id wind_c = row(W::WindC);
    const Id wind_d = row(W::WindD);
    const Id wind_e = row(W::WindE);
    const Id stored = ctx.OpLoad(u32_type, base_ptr, spv::MemoryAccessMask::Aligned, 4u);
    const Id h = sub(wy, sub(ctx.OpBitcast(f32_type, stored), f(W::HeightBias)));
    const Id zero = f(0.0f);
    const Id fin = ctx.OpFOrdLessThan(
        bool_type,
        add(add(ctx.OpFAbs(f32_type, h), ctx.OpFAbs(f32_type, rx)), ctx.OpFAbs(f32_type, rz)),
        f(W::FiniteMost));
    const Id t = ctx.OpFClamp(f32_type, mul(h, comp(wind_d, 0u)), zero, f(1.0f));
    const Id w = mul(mul(mul(t, t), sub(f(3.0f), mul(f(2.0f), t))), ramp);
    const Id dx = comp(wind_a, 0u);
    const Id dz = comp(wind_a, 1u);
    const Id s = add(mul(rx, dx), mul(rz, dz));
    const Id q = sub(mul(rz, dx), mul(rx, dz));
    const Id u = ctx.OpFClamp(f32_type, sub(comp(wind_d, 1u), mul(s, comp(wind_c, 3u))), zero,
                              comp(wind_d, 2u));
    const Id i = ctx.OpUMin(u32_type, ctx.OpConvertFToU(u32_type, ctx.OpFloor(f32_type, u)),
                            ctx.ConstU32(W::GustSamples - 2u));
    const Id frac = sub(u, ctx.OpConvertUToF(f32_type, i));
    const Id table = scaled(at(view, u64(W::TableAt) * 4u), i, 4u);
    const Id g0 = ctx.OpLoad(f32_type, ctx.OpConvertUToPtr(f32_ptr, table),
                             spv::MemoryAccessMask::Aligned, 4u);
    const Id g1 = ctx.OpLoad(f32_type, ctx.OpConvertUToPtr(f32_ptr, at(table, 4u)),
                             spv::MemoryAccessMask::Aligned, 4u);
    const Id g = add(g0, mul(sub(g1, g0), frac));
    const Id a1 = wrap(add(sub(comp(wind_b, 3u), mul(comp(wind_c, 0u), s)), mul(comp(wind_c, 1u), q)));
    const Id a2 = wrap(sub(sub(comp(wind_c, 2u), mul(comp(wind_d, 3u), s)), mul(comp(wind_c, 1u), q)));
    const Id max_along = comp(wind_e, 0u);
    const Id max_cross = comp(wind_e, 1u);
    const Id along = ctx.OpFClamp(
        f32_type, mul(g, add(comp(wind_b, 0u), mul(comp(wind_b, 1u), ctx.OpSin(f32_type, a1)))),
        ctx.OpFNegate(f32_type, max_along), max_along);
    const Id cross = ctx.OpFClamp(f32_type, mul(g, mul(comp(wind_b, 2u), ctx.OpSin(f32_type, a2))),
                                  ctx.OpFNegate(f32_type, max_cross), max_cross);
    const Id ddx = ctx.OpSelect(f32_type, fin, mul(w, sub(mul(dx, along), mul(dz, cross))), zero);
    const Id ddz = ctx.OpSelect(f32_type, fin, mul(w, add(mul(dz, along), mul(dx, cross))), zero);
    const Id d = ctx.OpCompositeConstruct(ctx.F32[4], std::array<Id, 4>{ddx, zero, ddz, zero});
    std::array<Id, 4> moved{};
    for (u32 r = 0; r < 4; ++r) {
        moved[r] = add(comp(position, r), ctx.OpDot(f32_type, row(W::ForwardAt + r * 4u), d));
    }
    ctx.OpStore(ctx.output_position, ctx.OpCompositeConstruct(ctx.F32[4], moved));
    const Id key = ctx.OpBitcast(u32_type, ctx.OpFMax(f32_type, add(wy, f(W::HeightBias)), zero));
    const Id offer = ctx.OpLogicalAnd(
        bool_type, ctx.OpFOrdLessThan(bool_type, ctx.OpFAbs(f32_type, wy), f(W::FiniteMost)),
        ctx.OpULessThan(bool_type, key, stored));
    const Id offer_label = ctx.OpLabel();
    const Id offer_merge = ctx.OpLabel();
    ctx.OpSelectionMerge(offer_merge, spv::SelectionControlMask::MaskNone);
    ctx.OpBranchConditional(offer, offer_label, offer_merge);
    ctx.AddLabel(offer_label);
    ctx.OpAtomicUMin(u32_type, base_ptr, ctx.ConstU32(static_cast<u32>(spv::Scope::Device)),
                     ctx.u32_zero_value, key);
    ctx.OpBranch(offer_merge);
    ctx.AddLabel(offer_merge);
    ctx.OpBranch(sway_merge);
    ctx.AddLabel(sway_merge);
}

'''

SWAY_LIFT = r'''// bbport (r89_wind-foliage-sway): the recompiler's EmitVertexSway (emit_spirv_special.cpp), the
// same rule (bbport_wind_sway.h; BbWindSway::Displace in C++): where the draw's motion param word
// 7 has BbWindSway::WordOn (a plant, Rasterizer::WindSwayWord) the clip position is moved by the
// wind before the motion store and the capture read it, and the vertex offers its world height to
// its mesh's base slot (an atomic minimum, only when lower). Other draws branch around it.
void Lift_::VertexSway() {
    namespace W = BbWindSway;
    MotionBlock(true);
    const u32 storage = u32(spv::StorageClass::PhysicalStorageBuffer);
    const u32 ptr_u64 = PtrType(u32(spv::StorageClass::Uniform), t_u64);
    const auto wide = [&](u32 value) { return Emit(O(spv::Op::OpUConvert), t_u64, Ty::U64, {value}); };
    const auto c64 = [&](u64 value) { return m.ConstU64(t_u64, value); };
    const auto iadd64 = [&](u32 a, u32 b) { return Emit(O(spv::Op::OpIAdd), t_u64, Ty::U64, {a, b}); };
    const auto at = [&](u32 base, u64 bytes) { return iadd64(base, c64(bytes)); };
    const auto scaled = [&](u32 base, u32 index, u64 stride) {
        return iadd64(base, Emit(O(spv::Op::OpIMul), t_u64, Ty::U64, {wide(index), c64(stride)}));
    };
    const u32 aligned = u32(spv::MemoryAccessMask::Aligned);
    const u32 ptr_v4u = PtrType(storage, t_v4u);
    const u32 ptr_v4f = PtrType(storage, t_v4f);
    const u32 ptr_u32 = PtrType(storage, t_u32);
    const u32 ptr_f32 = PtrType(storage, t_f32);
    const u32 raw_param = PushU32(11, -1);
    const u32 masked_param = in.vertex_capture ? IOp(O(spv::Op::OpBitwiseAnd), raw_param, CU(0xffffu)) : raw_param;
    const u32 param_index = Select(ICmp(O(spv::Op::OpULessThan), masked_param, CU(MotionParamsCapacity)), masked_param, CU(0));
    const u32 params_address = Emit(O(spv::Op::OpLoad), t_u64, Ty::U64, {Emit(O(spv::Op::OpAccessChain), ptr_u64, Ty::None, {var_motion_addr, CU(0)})});
    const u32 offsets_ptr = Emit(O(spv::Op::OpConvertUToPtr), ptr_v4u, Ty::None, {at(scaled(params_address, param_index, 32), 16)});
    const u32 offsets = Emit(O(spv::Op::OpLoad), t_v4u, Ty::V4U, {offsets_ptr, aligned, 16}, 6);
    const u32 word = Extract(t_u32, Ty::U32, offsets, 3);
    const u32 on = ICmp(O(spv::Op::OpINotEqual), IOp(O(spv::Op::OpBitwiseAnd), word, CU(W::WordOn)), CU(0));
    const u32 sway_label = m.NewId();
    const u32 sway_merge = m.NewId();
    EmitVoid(O(spv::Op::OpSelectionMerge), {sway_merge, 0}, 2);
    EmitVoid(O(spv::Op::OpBranchConditional), {on, sway_label, sway_merge});
    Open(sway_label);
    const auto field = [&](u32 offset, u32 count) {
        return Emit(O(spv::Op::OpBitFieldUExtract), t_u32, Ty::U32, {word, CU(offset), CU(count)});
    };
    const u32 region = at(params_address, u64(MotionParamsCapacity) * 32u);
    const u32 view_index = IOp(O(spv::Op::OpIAdd), IOp(O(spv::Op::OpIMul), field(0, 2), CU(W::Views)), field(2, 1));
    const u32 view = scaled(region, view_index, u64(W::ViewWords) * 4u);
    const u32 base_ptr = Emit(O(spv::Op::OpConvertUToPtr), ptr_u32, Ty::None, {scaled(at(region, u64(W::BaseAt) * 4u), field(3, 10), 4)});
    const u32 ramp = FMul(Emit(O(spv::Op::OpConvertUToF), t_f32, Ty::F32, {field(16, 8)}), CF(1.0f / 255.0f));
    const auto row = [&](u32 word_at) {
        const u32 ptr = Emit(O(spv::Op::OpConvertUToPtr), ptr_v4f, Ty::None, {at(view, u64(word_at) * 4u)});
        return Emit(O(spv::Op::OpLoad), t_v4f, Ty::V4F, {ptr, aligned, 16}, 6);
    };
    const auto comp = [&](u32 vec, u32 i) { return Extract(t_f32, Ty::F32, vec, i); };
    const auto dot = [&](u32 a, u32 b) { return Emit(O(spv::Op::OpDot), t_f32, Ty::F32, {a, b}); };
    const auto clamp_f = [&](u32 x, u32 lo, u32 hi) { return Ext(GLSLstd450FClamp, t_f32, Ty::F32, {x, lo, hi}); };
    const auto abs_f = [&](u32 x) { return Ext(GLSLstd450FAbs, t_f32, Ty::F32, {x}); };
    const auto floor_f = [&](u32 x) { return Ext(GLSLstd450Floor, t_f32, Ty::F32, {x}); };
    const auto sin_f = [&](u32 x) { return Ext(GLSLstd450Sin, t_f32, Ty::F32, {x}); };
    const auto wrap = [&](u32 a) { return FSub(a, FMul(CF(W::TwoPi), floor_f(FAdd(FMul(a, CF(W::InvTwoPi)), CF(0.5f))))); };
    const u32 position = Emit(O(spv::Op::OpLoad), t_v4f, Ty::V4F, {var_position});
    const u32 wind_a = row(W::WindA);
    // x and z relative to the camera; y in the world (plus the camera's height, WindA.z)
    const u32 rx = dot(row(W::ToWorldAt), position);
    const u32 wy = FAdd(dot(row(W::ToWorldAt + 4), position), comp(wind_a, 2));
    const u32 rz = dot(row(W::ToWorldAt + 8), position);
    const u32 wind_b = row(W::WindB);
    const u32 wind_c = row(W::WindC);
    const u32 wind_d = row(W::WindD);
    const u32 wind_e = row(W::WindE);
    const u32 stored = Emit(O(spv::Op::OpLoad), t_u32, Ty::U32, {base_ptr, aligned, 4}, 6);
    const u32 h = FSub(wy, FSub(Emit(O(spv::Op::OpBitcast), t_f32, Ty::F32, {stored}), CF(W::HeightBias)));
    const u32 zero = CF(0.0f);
    const u32 fin = FCmp(O(spv::Op::OpFOrdLessThan), FAdd(FAdd(abs_f(h), abs_f(rx)), abs_f(rz)), CF(W::FiniteMost));
    const u32 t = clamp_f(FMul(h, comp(wind_d, 0)), zero, CF(1.0f));
    const u32 w = FMul(FMul(FMul(t, t), FSub(CF(3.0f), FMul(CF(2.0f), t))), ramp);
    const u32 dx = comp(wind_a, 0);
    const u32 dz = comp(wind_a, 1);
    const u32 s = FAdd(FMul(rx, dx), FMul(rz, dz));
    const u32 q = FSub(FMul(rz, dx), FMul(rx, dz));
    const u32 u = clamp_f(FSub(comp(wind_d, 1), FMul(s, comp(wind_c, 3))), zero, comp(wind_d, 2));
    const u32 i = Ext(GLSLstd450UMin, t_u32, Ty::U32, {Emit(O(spv::Op::OpConvertFToU), t_u32, Ty::U32, {floor_f(u)}), CU(W::GustSamples - 2u)});
    const u32 frac = FSub(u, Emit(O(spv::Op::OpConvertUToF), t_f32, Ty::F32, {i}));
    const u32 table = scaled(at(view, u64(W::TableAt) * 4u), i, 4);
    const u32 g0 = Emit(O(spv::Op::OpLoad), t_f32, Ty::F32, {Emit(O(spv::Op::OpConvertUToPtr), ptr_f32, Ty::None, {table}), aligned, 4}, 6);
    const u32 g1 = Emit(O(spv::Op::OpLoad), t_f32, Ty::F32, {Emit(O(spv::Op::OpConvertUToPtr), ptr_f32, Ty::None, {at(table, 4)}), aligned, 4}, 6);
    const u32 g = FAdd(g0, FMul(FSub(g1, g0), frac));
    const u32 a1 = wrap(FAdd(FSub(comp(wind_b, 3), FMul(comp(wind_c, 0), s)), FMul(comp(wind_c, 1), q)));
    const u32 a2 = wrap(FSub(FSub(comp(wind_c, 2), FMul(comp(wind_d, 3), s)), FMul(comp(wind_c, 1), q)));
    const u32 max_along = comp(wind_e, 0);
    const u32 max_cross = comp(wind_e, 1);
    const u32 along = clamp_f(FMul(g, FAdd(comp(wind_b, 0), FMul(comp(wind_b, 1), sin_f(a1)))), FNeg(max_along), max_along);
    const u32 cross = clamp_f(FMul(g, FMul(comp(wind_b, 2), sin_f(a2))), FNeg(max_cross), max_cross);
    const u32 ddx = Select(fin, FMul(w, FSub(FMul(dx, along), FMul(dz, cross))), zero);
    const u32 ddz = Select(fin, FMul(w, FAdd(FMul(dz, along), FMul(dx, cross))), zero);
    const u32 d = ComponentsF({ddx, zero, ddz, zero});
    std::array<u32, 4> moved{};
    for (u32 r = 0; r < 4; ++r) {
        moved[r] = FAdd(comp(position, r), dot(row(W::ForwardAt + r * 4), d));
    }
    EmitVoid(O(spv::Op::OpStore), {var_position, ComponentsF({moved[0], moved[1], moved[2], moved[3]})});
    const u32 key = Emit(O(spv::Op::OpBitcast), t_u32, Ty::U32, {Ext(GLSLstd450FMax, t_f32, Ty::F32, {FAdd(wy, CF(W::HeightBias)), zero})});
    const u32 offer = Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool,
                           {FCmp(O(spv::Op::OpFOrdLessThan), abs_f(wy), CF(W::FiniteMost)), ICmp(O(spv::Op::OpULessThan), key, stored)});
    const u32 offer_label = m.NewId();
    const u32 offer_merge = m.NewId();
    EmitVoid(O(spv::Op::OpSelectionMerge), {offer_merge, 0}, 2);
    EmitVoid(O(spv::Op::OpBranchConditional), {offer, offer_label, offer_merge});
    Open(offer_label);
    const u32 prev = Emit(O(spv::Op::OpAtomicUMin), t_u32, Ty::U32, {base_ptr, CU(u32(spv::Scope::Device)), CU(0), key});
    nodes[m.NodeOf(prev)].effect = true;
    EmitVoid(O(spv::Op::OpBranch), {offer_merge});
    Open(offer_merge);
    EmitVoid(O(spv::Op::OpBranch), {sway_merge});
    Open(sway_merge);
}

'''

SWAY_RASTER = r'''// bbport (r89_wind-foliage-sway): the sway word (BbWindSway::PackWord) of a skinned draw of a
// pipeline with the Sway bit: 0 unless RtShadow takes the draw's position stream (the fetch's
// semantic 0: address and bytes, as EffectsCaptureDraw takes it) for a plant (LonePlant: needs
// ray tracing), the draw's 864-byte camera constants give a camera, this frame has room for its
// view (BbWindSway::Views: the first views' words are written into the ring's frame slot,
// ObjectMotion::FrameSlot, which the GPU is done with since ObjectMotion::OnFrameStart) and the
// stream has or gets a base slot (a slot new to its stream gets its key reset here; the GPU
// lowers it from then on). The wind is r82's state as last advanced. On the thread recording draws.
u32 Rasterizer::WindSwayWord(const GraphicsPipeline* pipeline) {
    const auto& knob = BbWindSway::KnobOnce();
    ++sway_stats.draws;
    u32* const words = object_motion->SwayWords();
    if (!knob.on || words == nullptr) {
        ++sway_stats.no_region;
        return 0;
    }
    if (!rt_shadow->Wanted()) {
        ++sway_stats.no_rt;
        return 0;
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto& fetch = pipeline->GetFetchShader();
    u64 positions = 0;
    u32 positions_size = 0;
    if (fetch) {
        for (const auto& attribute : fetch->attributes) {
            if (attribute.semantic == 0) {
                const auto stream = attribute.GetSharp(vs);
                positions = stream.base_address;
                positions_size = stream.GetSize();
                break;
            }
        }
    }
    if (!rt_shadow->LonePlant(positions, positions_size)) {
        return 0;
    }
    ++sway_stats.plants;
    const float* constants = nullptr;
    for (const auto& resource : vs.buffers) {
        if (resource.IsSpecial()) {
            continue;
        }
        const auto buffer = resource.GetSharp(vs);
        if (buffer.Valid() && buffer.GetSize() == BbWindSway::ConstantsBytes &&
            memory->IsValidGpuMapping(buffer.base_address, 0) &&
            memory->ClampRangeSize(buffer.base_address, BbWindSway::ConstantsBytes) ==
                BbWindSway::ConstantsBytes) {
            constants = reinterpret_cast<const float*>(buffer.base_address);
        }
    }
    if (constants == nullptr) {
        ++sway_stats.no_camera;
        return 0;
    }
    const u64 frame = object_motion->Frame();
    const u32 frame_slot = object_motion->FrameSlot();
    if (frame != sway_frame) {
        sway_frame = frame;
        sway_views = 0;
    }
    const BbWindSway::ViewKey key = BbWindSway::KeyOf(constants);
    u32 view = 0;
    while (view < sway_views && !BbWindSway::SameKey(sway_keys[view], key)) {
        ++view;
    }
    const BbWind::Snapshot snapshot = wind.Get();
    if (view == sway_views) {
        if (sway_views == BbWindSway::Views) {
            ++sway_stats.views_full;
            return 0;
        }
        BbWindSway::Camera camera;
        if (!BbWindSway::CameraOf(constants, camera)) {
            ++sway_stats.no_camera;
            return 0;
        }
        std::array<float, BbWindSway::ViewWords> filled{};
        BbWindSway::FillView(camera, snapshot, knob.gusts, knob.scale, filled.data());
        std::memcpy(words + BbWindSway::ViewAt(frame_slot, view), filled.data(), sizeof(filled));
        sway_keys[view] = key;
        ++sway_views;
    }
    const auto taken = sway_slots.Take(positions, positions_size, frame, snapshot.time);
    if (!taken.ok) {
        ++sway_stats.no_slot;
        return 0;
    }
    if (taken.reset) {
        words[BbWindSway::BaseAt + taken.slot] = BbWindSway::ResetKey;
    }
    ++sway_stats.swayed;
    sway_stats.ramping += taken.ramp < 255 ? 1 : 0;
    return BbWindSway::PackWord(frame_slot, view, taken.slot, taken.ramp);
}

// bbport (r89_wind-foliage-sway): the knob's line once (nothing with BB_WIND off: r82's line says
// it), then with the sway on a line of counts every BbWindSway::ReportFrames frame ends.
void Rasterizer::WindSwayFrameEnd() {
    static const bool on = [] {
        const auto& knob = BbWindSway::KnobOnce();
        if (knob.on) {
            BbReport::Printf(
                "Wind sway (r89, BB_WIND=1): plants sway (cut-outs with a skeleton that no sun "
                "shadow pass draws, as the ray traced scene finds them; none without ray tracing), "
                "scale %.2f, gusts %.2f: full sway %.2f m above a mesh's lowest point, lean %.3f m, "
                "swing %.3f m at %.1f Hz along the wind and %.3f m at %.1f Hz across it at 1.5 m/s\n",
                double(knob.scale), double(knob.gusts), double(BbWindSway::Height),
                double(BbWindSway::Lean * knob.scale), double(BbWindSway::Flutter * knob.scale),
                double(BbWindSway::SwayHz), double(BbWindSway::Cross * knob.scale),
                double(BbWindSway::CrossHz));
        } else if (knob.wind) {
            BbReport::Printf("Wind sway (r89): off (BB_WIND_SWAY=0); no plant sways\n");
        }
        return knob.on;
    }();
    if (!on || ++sway_frames % BbWindSway::ReportFrames != 0) {
        return;
    }
    const auto n = [](u64 v) { return static_cast<unsigned long long>(v); };
    const BbWindSway::Stats& s = sway_stats;
    BbReport::Printf("Wind sway (r89): in %u frames %llu draws of sway pipelines with a skeleton, "
                     "%llu of plants, %llu swayed (%llu ramping in); not swayed: %llu without ray "
                     "tracing, %llu without a camera, %llu with the views full, %llu without a "
                     "base slot, %llu without the sway words; base slots in use %u of %u\n",
                     BbWindSway::ReportFrames, n(s.draws), n(s.plants), n(s.swayed), n(s.ramping),
                     n(s.no_rt), n(s.no_camera), n(s.views_full), n(s.no_slot), n(s.no_region),
                     sway_slots.InUse(sway_frame), BbWindSway::BaseSlots);
    sway_stats = {};
}

'''

README_ROW = (
    "| `BB_WIND_SWAY` | Plants sway with the wind: the scale of the sway, 0 (still) to 3. It needs "
    "`BB_WIND=1` and ray tracing (`effect_ray_tracing`): the plants are the meshes the ray traced "
    "scene takes for plants, cut-outs with a skeleton that no sun shadow pass draws (weeds, bushes, "
    "ivy); characters, their hair and their cloth have sun shadows and never sway. Each vertex of a "
    "plant moves sideways in the world, along the wind by G (0.06 + 0.06 sin a) m and across it by "
    "G 0.025 sin b m, each times the scale and times min(speed, 2.5) / 1.5 m/s and then held to "
    "(at most 0.4 m and 0.15 m), and all of it times smoothstep(0, 0.75 m, h), h being the vertex's height above the "
    "lowest point of its mesh seen so far: the roots stay still, the top of a plant 0.75 m or taller "
    "moves in full. G is the gust factor where the vertex is (the gusts travel downwind); a and b "
    "turn at 0.7 Hz and 1.3 Hz and change along the wind so that the sway travels downwind at the "
    "wind's speed (at least 0.5 m/s), and change across the wind every 3.3 m. A plant's mesh "
    "sways in over 1 s when it first gets a base slot (again when its slot went to another mesh). "
    "The motion vectors and the ray traced scene take the moved positions (a plant's ray traced "
    "shape is refitted at its draws like any mesh with a skeleton). Limits: ivy that hangs "
    "from a wall sways most at its top (its lowest point is its tip) and may move into the wall; "
    "the plants of one mesh on a slope all count from its lowest point, so roots uphill move. The "
    "log says once that it is on and every 600 frames how many plant draws swayed (`Wind sway "
    "(r89)`). Cost: nothing when off; when on, on the GPU one load and a test per vertex of a "
    "cut-out with motion and about 15 loads and 60 operations per plant vertex, on the CPU a few "
    "lookups per plant draw; an estimate under 0.05 ms, not measured | `1` |")

EDITS = {
    S + "runtime_info.h": [
        (r'''    static constexpr u32 CaptureUvStride = 16;
''', r'''    static constexpr u32 CaptureUvStride = 16;
    /// bbport (r89_wind-foliage-sway): with BB_WIND=1 and BB_WIND_SWAY above 0, a motion vertex
    /// shader (VertexOutputs) whose pixel shader discards first moves its clip position by the
    /// wind where its draw's motion param word 7 says so (a plant; bbport_wind_sway.h). Never set
    /// with the knob off: keys and SPIR-V are then as before.
    static constexpr u8 Sway = 8;
'''),
    ],
    S + "backend/spirv/emit_spirv_special.cpp": [
        (r'''#include "shader_recompiler/ir/microinstruction.h"
''', r'''#include "shader_recompiler/ir/microinstruction.h"
#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)
'''),
        (r'''// Screen-space motion (previous minus current, pixels) through the viewport scale; z = valid.
''', SWAY_SPIRV + r'''// Screen-space motion (previous minus current, pixels) through the viewport scale; z = valid.
'''),
        (r'''void EmitEpilogue(EmitContext& ctx) {
    if (Sirit::ValidId(ctx.motion_out_cur)) {
        EmitVertexMotion(ctx);
''', r'''void EmitEpilogue(EmitContext& ctx) {
    // bbport (r89_wind-foliage-sway): first, so the motion store and the capture take the
    // swayed position (not with the clip space conversion: that position is not clip space yet)
    if (Sirit::ValidId(ctx.motion_out_cur) && ctx.VertexMotion() &&
        (ctx.runtime_info.hw.vs.motion_vectors & MotionVectors::Sway) != 0 &&
        !ctx.runtime_info.hw.vs.clip_disable) {
        EmitVertexSway(ctx);
    }
    if (Sirit::ValidId(ctx.motion_out_cur)) {
        EmitVertexMotion(ctx);
'''),
    ],
    L + "lift.h": [
        (r'''    bool vertex_motion{};
    bool vertex_capture{};
''', r'''    bool vertex_motion{};
    bool vertex_sway{}; // bbport (r89_wind-foliage-sway): MotionVectors::Sway, VertexSway
    bool vertex_capture{};
'''),
    ],
    L + "lift_core.h": [
        (r'''    void MotionBlock(bool outputs);
    void VertexMotion();
''', r'''    void MotionBlock(bool outputs);
    void VertexSway(); ///< bbport (r89_wind-foliage-sway)
    void VertexMotion();
'''),
    ],
    L + "bridge.cpp": [
        (r'''        in.vertex_capture = (vs.motion_vectors & Shader::MotionVectors::VertexCapture) != 0;
''', r'''        in.vertex_capture = (vs.motion_vectors & Shader::MotionVectors::VertexCapture) != 0;
        // bbport (r89_wind-foliage-sway): the plant sway, as the recompiler's EmitVertexSway
        in.vertex_sway = in.vertex_motion && (vs.motion_vectors & Shader::MotionVectors::Sway) != 0;
'''),
    ],
    L + "lift_stage.cpp": [
        (r'''#include "lifter/lift_core.h"
''', r'''#include "lifter/lift_core.h"
#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)
'''),
        (r'''void Lift_::Epilogue() {
    if (user_clip_planes) {
''', r'''void Lift_::Epilogue() {
    // bbport (r89_wind-foliage-sway): first, so the clip planes, the motion store and the capture
    // take the swayed position (not with the clip space conversion: not clip space yet)
    if (in.vertex_sway && in.stage == Stage::Vertex && !in.clip_disable) {
        VertexSway();
    }
    if (user_clip_planes) {
'''),
        (r'''void Lift_::VertexMotion() {
    MotionBlock(true);
''', SWAY_LIFT + r'''void Lift_::VertexMotion() {
    MotionBlock(true);
'''),
    ],
    R + "vk_pipeline_cache.cpp": [
        (r'''#include "lifter/bridge.h"
''', r'''#include "lifter/bridge.h"
#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)
'''),
        (r'''static bool FragmentDiscards(const PipelineSelection& sel) {
    const auto* fs = sel.infos[static_cast<u32>(Shader::SwStage::Fragment)];
    return fs && fs->has_discard;
}
''', r'''static bool FragmentDiscards(const PipelineSelection& sel) {
    const auto* fs = sel.infos[static_cast<u32>(Shader::SwStage::Fragment)];
    return fs && fs->has_discard;
}

// bbport (r89_wind-foliage-sway): MotionVectors::Sway for a motion pipeline whose pixel shader
// discards (a cut-out: what a plant is drawn with), only with BB_WIND=1 and BB_WIND_SWAY above 0
// (read once). Which of its draws sway is the draw's motion param word 7 (WindSwayWord).
static bool SwayWanted(const PipelineSelection& sel) {
    return sel.motion && BbWindSway::KnobOnce().on && FragmentDiscards(sel);
}
'''),
        (r'''        info.hw.vs.motion_vectors =
            u8((sel.capture ? Shader::MotionVectors::VertexCapture : 0) | (sel.motion ? 1 : 0) |
               (sel.capture && Shader::Optimization::CaptureUvWanted(FragmentDiscards(sel))
                    ? Shader::MotionVectors::CaptureUv
                    : 0));
''', r'''        info.hw.vs.motion_vectors =
            u8((sel.capture ? Shader::MotionVectors::VertexCapture : 0) | (sel.motion ? 1 : 0) |
               (sel.capture && Shader::Optimization::CaptureUvWanted(FragmentDiscards(sel))
                    ? Shader::MotionVectors::CaptureUv
                    : 0) |
               (SwayWanted(sel) ? Shader::MotionVectors::Sway : 0)); // bbport (r89_wind-foliage-sway)
'''),
        (r'''        constexpr u32 mv = Shader::MotionVectors::Output;
        key.motion_vectors |= 1;
''', r'''        constexpr u32 mv = Shader::MotionVectors::Output;
        key.motion_vectors |= 1;
        if (SwayWanted(sel)) { // bbport (r89_wind-foliage-sway): as the vertex stage's runtime info
            key.motion_vectors |= Shader::MotionVectors::Sway;
        }
'''),
    ],
    R + "vk_pipeline_serialization.cpp": [
        (r'''#include "bbport_threads.h"
''', r'''#include "bbport_threads.h"
#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)
'''),
        (r'''    if (!uv_by_fragment &&
        key_uv != (key_capture && Shader::Optimization::CaptureUvWanted(true))) {
        return false;
    }
''', r'''    if (!uv_by_fragment &&
        key_uv != (key_capture && Shader::Optimization::CaptureUvWanted(true))) {
        return false;
    }
    // bbport (r89_wind-foliage-sway): nor a key with the plant sway (a run with BB_WIND=1 and
    // BB_WIND_SWAY above 0 saved it) when this run's knob is off: no draw asks for it, and its
    // vertex shader would read sway words the motion buffer does not have.
    if ((sel.graphics_key.motion_vectors & Shader::MotionVectors::Sway) != 0 &&
        !BbWindSway::KnobOnce().on) {
        return false;
    }
'''),
    ],
    R + "vk_object_motion.h": [
        (r'''#include "video_core/renderer_vulkan/motion_history.h"
''', r'''#include "video_core/renderer_vulkan/motion_history.h"
#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)
'''),
        (r'''    [[nodiscard]] Shader::MotionVectors::Addresses AddressTable() const noexcept {
        return address_table;
    }
''', r'''    [[nodiscard]] Shader::MotionVectors::Addresses AddressTable() const noexcept {
        return address_table;
    }
    /// bbport (r89_wind-foliage-sway): the plant sway's words right after the params' ring in its
    /// buffer (bbport_wind_sway.h; null unless BB_WIND=1 with BB_WIND_SWAY above 0 and the buffer
    /// was made), the frame and its slot of the ring (the views of this frame are written there).
    [[nodiscard]] u32* SwayWords() const noexcept {
        return sway_words;
    }
    [[nodiscard]] u64 Frame() const noexcept {
        return frame;
    }
    [[nodiscard]] u32 FrameSlot() const noexcept {
        return u32(frame % FrameSlots);
    }
'''),
        (r'''        Motion::Kind kind = Motion::Kind::Other;
''', r'''        Motion::Kind kind = Motion::Kind::Other;
        /// bbport (r89_wind-foliage-sway): the param's word 7, the sway word
        /// (BbWindSway::PackWord; 0: no sway, as for every draw before)
        u32 sway = 0;
'''),
        (r'''    void WriteParam(u32 index, const Motion::History::Allocation& allocation);
''', r'''    void WriteParam(u32 index, const Motion::History::Allocation& allocation, u32 sway);
'''),
        (r'''    static_assert(1 + FrameSlots * ParamsPerFrame == Shader::MotionVectors::ParamsCapacity);
''', r'''    static_assert(1 + FrameSlots * ParamsPerFrame == Shader::MotionVectors::ParamsCapacity);
    // bbport (r89_wind-foliage-sway): the sway words' views are per slot of this ring, and they
    // start at a 16-byte boundary (ParamsCapacity * 32 bytes in, as both emitters read them)
    static_assert(BbWindSway::FrameSlots == FrameSlots);
    static_assert((Shader::MotionVectors::ParamsCapacity * 32u) % 16u == 0);
'''),
        (r'''    u32* params_mapped{};
''', r'''    u32* params_mapped{};
    u32* sway_words{}; ///< bbport (r89_wind-foliage-sway): SwayWords
'''),
    ],
    R + "vk_object_motion.cpp": [
        (r'''        CreateBuffer(instance, vk::DeviceSize(1 + FrameSlots * ParamsPerFrame) * 32, true,
''', r'''        CreateBuffer(instance,
                     vk::DeviceSize(1 + FrameSlots * ParamsPerFrame) * 32 +
                         // bbport (r89_wind-foliage-sway): and the plant sway's words
                         (BbWindSway::KnobOnce().on ? BbWindSway::RegionBytes : 0u),
                     true,
'''),
        (r'''    std::memset(params_mapped, 0, 32);
''', r'''    std::memset(params_mapped, 0, 32);
    // bbport (r89_wind-foliage-sway): the plant sway's words: the views zero, no base slot with a
    // key yet
    if (BbWindSway::KnobOnce().on) {
        sway_words = params_mapped + (1 + FrameSlots * ParamsPerFrame) * 8;
        std::memset(sway_words, 0, BbWindSway::RegionBytes);
        for (u32 i = BbWindSway::BaseAt; i < BbWindSway::RegionWords; ++i) {
            sway_words[i] = BbWindSway::ResetKey;
        }
    }
'''),
        (r'''        WriteParam(job.param, Evaluate(job.draw));
''', r'''        WriteParam(job.param, Evaluate(job.draw), job.draw.sway);
'''),
        (r'''void ObjectMotion::WriteParam(u32 index, const Motion::History::Allocation& allocation) {
''', r'''void ObjectMotion::WriteParam(u32 index, const Motion::History::Allocation& allocation, u32 sway) {
'''),
        (r'''    if (!flags) {
        std::memset(param, 0, 32);
        return;
''', r'''    if (!flags) {
        std::memset(param, 0, 32);
        param[7] = sway; // bbport (r89_wind-foliage-sway): a plant without a store still sways
        return;
'''),
        (r'''    param[7] = 0;
''', r'''    param[7] = sway; // bbport (r89_wind-foliage-sway): the sway word (0: none)
'''),
        (r'''    const auto allocation = Evaluate(job);
    if (!allocation.store && !allocation.load) {
        return 0;
''', r'''    const auto allocation = Evaluate(job);
    // bbport (r89_wind-foliage-sway): a draw with a sway word keeps its param (word 7) without a
    // store or load; with the knob off every sway word is 0 and this is as before
    if (!allocation.store && !allocation.load && job.sway == 0) {
        return 0;
'''),
        (r'''    WriteParam(index, allocation);
''', r'''    WriteParam(index, allocation, job.sway);
'''),
    ],
    R + "vk_rasterizer.h": [
        (r'''#include "bbport_wind.h" // bbport (r82_wind-stage1)
''', r'''#include "bbport_wind.h" // bbport (r82_wind-stage1)
#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)
'''),
        (r'''    void WindOnFrameEnd(); ///< bbport (r82_wind-stage1): first in EffectsOnFrameEnd
''', r'''    void WindOnFrameEnd(); ///< bbport (r82_wind-stage1): first in EffectsOnFrameEnd
    /// bbport (r89_wind-foliage-sway): a skinned draw of a pipeline with MotionVectors::Sway: its
    /// motion param word 7 (BbWindSway::PackWord; 0: no sway); the log lines at each frame end
    u32 WindSwayWord(const GraphicsPipeline* pipeline);
    void WindSwayFrameEnd();
'''),
        (r'''    std::chrono::steady_clock::time_point wind_time{};
''', r'''    std::chrono::steady_clock::time_point wind_time{};
    /// bbport (r89_wind-foliage-sway): the plants' base slots, this frame's views (their 28
    /// constants, sway_views of them, of ObjectMotion frame sway_frame), the log's counts and
    /// the frame ends counted (all only with BB_WIND=1 and BB_WIND_SWAY above 0)
    BbWindSway::Slots sway_slots;
    std::array<BbWindSway::ViewKey, BbWindSway::Views> sway_keys{};
    u32 sway_views = 0;
    u64 sway_frame = ~u64{0};
    BbWindSway::Stats sway_stats;
    u64 sway_frames = 0;
'''),
    ],
    R + "vk_rasterizer.cpp": [
        (r'''        r19_motion = {true, indices_valid, r19_complete, palette}; // bbport (r19_draw-cost)
        dc.push_data.motion_param = object_motion->Draw({
''', r'''        r19_motion = {true, indices_valid, r19_complete, palette}; // bbport (r19_draw-cost)
        // bbport (r89_wind-foliage-sway): a plant's sway word (WindSwayWord); 0 for every other
        // draw, and with the knob off no pipeline has the Sway bit
        const u32 sway =
            r34_kind == Motion::Kind::Skinned &&
                    (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::Sway) != 0
                ? WindSwayWord(pipeline)
                : 0u;
        dc.push_data.motion_param = object_motion->Draw({
'''),
        (r'''            .kind = r34_kind, // bbport (r34_motion-store)
        });
''', r'''            .kind = r34_kind, // bbport (r34_motion-store)
            .sway = sway,     // bbport (r89_wind-foliage-sway)
        });
'''),
    ],
    R + "vk_rasterizer_effects.cpp": [
        (r'''void Rasterizer::EffectsOnFrameEnd() {
''', SWAY_RASTER + r'''void Rasterizer::EffectsOnFrameEnd() {
'''),
        (r'''    WindOnFrameEnd(); // bbport (r82_wind-stage1): BB_WIND=1 only
''', r'''    WindOnFrameEnd(); // bbport (r82_wind-stage1): BB_WIND=1 only
    WindSwayFrameEnd(); // bbport (r89_wind-foliage-sway): its log lines
'''),
    ],
    R + "vk_rt_shadow.h": [
        (r'''    void CaptureLeftOut(u32 motion_param, u32 mode);
''', r'''    void CaptureLeftOut(u32 motion_param, u32 mode);
    // bbport (r89_wind-foliage-sway): whether the plant rule takes the position stream at
    // `positions` (an address; 0: none) with `size` bytes bound (0: not known) for lone
    // (LampLoneOf of lone_streams: a cut-out with a skeleton no sun shadow pass draws, a plant),
    // as of the draws so far. Another size than the stream is known with is another mesh: false.
    [[nodiscard]] bool LonePlant(u64 positions, u32 size) const;
'''),
    ],
    R + "vk_rt_shadow.cpp": [
        (r'''bool RtShadow::RayTracing() const {
''', r'''// bbport (r89_wind-foliage-sway): see the declaration (the plant sway asks for each skinned draw
// of a sway pipeline; the same map PrepareDraw keeps, on the same thread)
bool RtShadow::LonePlant(u64 positions, u32 size) const {
    if (positions == 0) {
        return false;
    }
    const auto known = lone_streams.find(positions);
    return known != lone_streams.end() && LampLoneOf(known->second) == LampLoneState::Lone &&
           (size == 0 || known->second.size == 0 || known->second.size == size);
}

bool RtShadow::RayTracing() const {
'''),
    ],
    G + "CMakeLists.txt": [
        (r'''# bbport (r82_wind-stage1): the shared wind state and the CPU copy of the fog noise and march step
''', r'''# bbport (r89_wind-foliage-sway): the plant sway's knob, word, layout, camera math and rule
# (shim/bbport_wind_sway.h); also built and run by engine/build.sh --test.
add_executable(wind-sway-test EXCLUDE_FROM_ALL ../tests/test_wind_sway.cpp)
target_compile_options(wind-sway-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-sway-test PRIVATE ..)
# bbport (r82_wind-stage1): the shared wind state and the CPU copy of the fog noise and march step
'''),
    ],
    "engine/build.sh": [
        (r'''    # bbport (r82_wind-stage1): the shared wind state, the fog noise and the march step
''', r'''    # bbport (r89_wind-foliage-sway): the plant sway's knob, word, layout, camera math and rule
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_wind_sway.cpp -o out/wind-sway-test
    out/wind-sway-test
    # bbport (r82_wind-stage1): the shared wind state, the fog noise and the march step
'''),
    ],
    "README.md": [
        (r'''| `BB_WIND_GUSTS` | Gusts, 0 (steady) to 1 | `0.5` |
''', r'''| `BB_WIND_GUSTS` | Gusts, 0 (steady) to 1 | `0.5` |
''' + README_ROW + "\n"),
    ],
}

CHECKS = {
    S + "runtime_info.h": [("static constexpr u8 Sway = 8;", 1), ("static constexpr u8 CaptureUv = 4;", 1)],
    S + "backend/spirv/emit_spirv_special.cpp": [("EmitVertexSway(ctx);", 1), ("static void EmitVertexSway(", 1),
                                                 ("OpAtomicUMin", 1)],
    L + "lift_stage.cpp": [("VertexSway();", 1), ("void Lift_::VertexSway() {", 1), ("OpAtomicUMin", 1)],
    L + "bridge.cpp": [("in.vertex_sway =", 1)],
    R + "vk_pipeline_cache.cpp": [("SwayWanted(sel)", 2), ("static bool SwayWanted(", 1)],
    R + "vk_object_motion.cpp": [("WriteParam(", 3), ("job.draw.sway", 1), ("job.sway", 2), ("param[7] = sway;", 2),
                                 ("job.sway == 0", 1), ("param[7] = 0;", 0)],
    R + "vk_object_motion.h": [("u32 sway = 0;", 1), ("u32* sway_words{};", 1)],
    R + "vk_rasterizer.cpp": [("WindSwayWord(pipeline)", 1), (".sway = sway,", 1)],
    R + "vk_rasterizer_effects.cpp": [("u32 Rasterizer::WindSwayWord(", 1), ("void Rasterizer::WindSwayFrameEnd() {", 1),
                                      ("    WindSwayFrameEnd();", 1)],
    R + "vk_rt_shadow.cpp": [("bool RtShadow::LonePlant(", 1)],
    G + "CMakeLists.txt": [("add_executable(wind-sway-test", 1), ("add_executable(wind-test", 1)],
    "engine/build.sh": [("out/wind-sway-test\n", 2), ("out/wind-test\n", 2)],
    "README.md": [("| `BB_WIND_SWAY` |", 1), ("| `BB_WIND_GUSTS` |", 1), ("| `BB_WIND_SHOW` |", 1)],
}

# README numbers tied to the header's constants (rule 10: written twice): (header text, README).
TIES = [("DefaultScale = 1.0f, MaxScale = 3.0f", "the scale of the sway, 0 (still) to 3."),
        ("DefaultScale = 1.0f", "lookups per plant draw; an estimate under 0.05 ms, not measured | `1` |"),
        ("Lean = 0.06f", "G (0.06 + 0.06 sin a) m"), ("Flutter = 0.06f", "G (0.06 + 0.06 sin a) m"),
        ("Cross = 0.025f", "G 0.025 sin b m"), ("MaxAlong = 0.4f, MaxCross = 0.15f", "(at most 0.4 m and 0.15 m)"),
        ("SpeedCap = 2.5f", "min(speed, 2.5) / 1.5 m/s"), ("RefSpeed = BbWind::DefaultSpeed", "min(speed, 2.5) / 1.5 m/s"),
        ("Height = 0.75f", "smoothstep(0, 0.75 m, h)"), ("SwayHz = 0.7f", "0.7 Hz and 1.3 Hz"),
        ("CrossHz = 1.3f", "0.7 Hz and 1.3 Hz"), ("MinWaveSpeed = 0.5f", "(at least 0.5 m/s)"),
        ("CrossWavelength = 3.3f", "every 3.3 m"), ("RampTime = 1.0;", "sways in over 1 s when it first gets a base slot"),
        ("ReportFrames = 600;", "every 600 frames")]

# Order checks on the patched result: each string after the one before it (first occurrence).
ORDER = {
    S + "backend/spirv/emit_spirv_special.cpp": ["static void EmitVertexMotion(", "static void EmitVertexCapture(",
                                                 "static void EmitVertexSway(", "static void EmitFragmentMotion(",
                                                 "void EmitEpilogue(", "EmitVertexSway(ctx);",
                                                 "EmitVertexMotion(ctx);", "EmitVertexCapture(ctx);"],
    L + "lift_stage.cpp": ["void Lift_::Epilogue() {", "VertexSway();", "UserClipPlanes();", "VertexMotion();",
                           "VertexCapture();", "void Lift_::VertexSway() {", "void Lift_::VertexMotion() {"],
    R + "vk_rasterizer.cpp": ["r34_kind = Motion::Kind::Skinned;", "const u32 sway =",
                              "dc.push_data.motion_param = object_motion->Draw({", ".kind = r34_kind,",
                              ".sway = sway,"],
    R + "vk_rasterizer_effects.cpp": ["void Rasterizer::WindOnFrameEnd()", "u32 Rasterizer::WindSwayWord(",
                                      "void Rasterizer::WindSwayFrameEnd()",
                                      "void Rasterizer::EffectsOnFrameEnd() {\n    WindOnFrameEnd();",
                                      "    WindSwayFrameEnd();"],
    R + "vk_object_motion.h": ["Motion::Kind kind = Motion::Kind::Other;", "u32 sway = 0;", "u32 Draw(const DrawJob& job);"],
    "README.md": ["| `BB_WIND` |", "| `BB_WIND_GUSTS` |", "| `BB_WIND_SWAY` |", "| `BB_WIND_FOG` |", "| `BB_WIND_SHOW` |"],
    G + "CMakeLists.txt": ["add_executable(wind-sway-test", "add_executable(wind-test"],
    "engine/build.sh": ["out/wind-sway-test", "out/wind-test"],
}

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
    header = NEW[HEADER]
    rows = [l for l in texts["README.md"].split("\n") if l.startswith("| `BB_WIND_SWAY` |")]
    for const, value in TIES:
        if header.count(const) != 1 or len(rows) != 1 or value not in rows[0]:
            raise SystemExit("tie check: %r against the BB_WIND_SWAY row (%r)" % (const, value))
    # the C++ test is built by both CMake and build.sh --test (rule 2)
    if "tests/test_wind_sway.cpp" not in texts["engine/build.sh"] or \
            "../tests/test_wind_sway.cpp" not in texts[G + "CMakeLists.txt"]:
        raise SystemExit("rule 2: the test is not built by both")
    for path, text in list(NEW.items()) + [("README_ROW", README_ROW)]:
        if not all(ord(c) < 128 for c in text) or "\r" in text:
            raise SystemExit("%s: new text must be ASCII with LF in the script" % path)
    public = list(NEW.values()) + [new for edits in EDITS.values() for old, new in edits]
    if any(("C:/" in x or "G:/" in x or "<user>" in x or "Temp/claude" in x) for x in public):
        raise SystemExit("a local path in the patch's text")

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R89_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(new) == 1 for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): state = "applied"
        elif todo == len(edits): state = "clean"
        else: raise SystemExit("%s: %d of %d edits applied, %d anchors found once" % (path, done, len(edits), todo))
        plan.append((path, edits, raw, eol, cur, state))
    for path, text in NEW.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full): state = "clean"
        elif open(full, "rb").read() == new_bytes(text): state = "applied"
        else: raise SystemExit("%s exists and is not this patch's file" % path)
        plan.append((path, None, None, None, None, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    edited = [p for p in plan if p[1] is not None]
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in edited})
            print("applied (text checks pass)")
        else:
            texts = {}
            for path, edits, raw, eol, cur, _ in edited:
                for old, new in edits: cur = cur.replace(old, new)
                texts[path] = cur
            text_checks(texts)
            print("not applied; would apply (%d files edited, %d new; text checks on the result pass)"
                  % (len(edited), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied": print("already applied"); return
        texts, outs = {}, []
        for path, edits, raw, eol, cur, _ in edited:
            for old, new in edits: cur = cur.replace(old, new)
            texts[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        for path, text in NEW.items():
            outs.append((path, new_bytes(text), None))
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r89tmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(ROOT, path))
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r89tmp"
                if os.path.exists(tmp): os.remove(tmp)
            for path, raw in written:
                if raw is None: os.remove(os.path.join(ROOT, path))
                else: open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    for path, edits, raw, eol, cur, _ in edited:
        for old, new in reversed(edits): cur = cur.replace(new, old)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")

main()
