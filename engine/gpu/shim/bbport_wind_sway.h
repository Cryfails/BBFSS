// SPDX-License-Identifier: GPL-3.0-or-later
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
// k2), WindE (MaxAlong, MaxCross, camera x and z, unread), the gust table at TableAt, the
// ripple's words at RippleAt: bbport r89b_wind-sway-ripple, FillRipple), then
// BaseSlots height keys (BaseAt). Motion param word 7 (0
// before) is the draw's sway word (PackWord): WordOn, the frame slot, the view, the base slot and
// the ramp. Pure: no Vulkan; tested by tests/test_wind_sway.cpp (Displace is the shaders' rule in
// C++, operation for operation).

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdio> // bbport (r89b_wind-sway-ripple): the ripple's log texts
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
/// bbport (r89b_wind-sway-ripple): the ripple's RippleWords words (rows RippleA-RippleD) after
/// the gust table; FillRipple writes them, FillView leaves them 0 (r89's motion)
inline constexpr std::uint32_t RippleAt = TableAt + GustSamples, RippleWords = 16;
inline constexpr std::uint32_t RippleA = RippleAt, RippleB = RippleAt + 4, RippleC = RippleAt + 8,
                               RippleD = RippleAt + 12;
inline constexpr std::uint32_t ViewWords = RippleAt + RippleWords;
inline constexpr std::uint32_t BaseAt = FrameSlots * Views * ViewWords;
inline constexpr std::uint32_t BaseSlots = 1024;
/// bbport (r89c_wind-lean): the base keys' second half holds the crown keys: slot i's crown key
/// (CrownKey: the highest world y any vertex of its stream had) at CrownAt + i, so a stream's
/// slot is below PlantSlots (Slots) and the region keeps its size
inline constexpr std::uint32_t PlantSlots = BaseSlots / 2, CrownAt = BaseAt + PlantSlots;
inline constexpr std::uint32_t RegionWords = BaseAt + BaseSlots;
inline constexpr std::uint32_t RegionBytes = RegionWords * 4;
inline constexpr std::uint32_t WordOn = 0x80000000u;
inline constexpr std::uint32_t ConstantsBytes = 864; ///< the camera's vertex constants
inline constexpr std::uint32_t ReuseFrames = 8; ///< frames a slot rests before another stream
inline constexpr double RampTime = 1.0;         ///< s of wind time from still to full sway
inline constexpr std::uint32_t ReportFrames = 600;
inline constexpr float TwoPi = 6.28318530717958647692f;
inline constexpr float InvTwoPi = 0.15915494309189533577f;

// bbport (r89b_wind-sway-ripple): the ripple (BB_WIND_SWAY_RIPPLE, on by default with the sway;
// RippleOr has the rule). The strength: unset, empty, unreadable or not finite is RippleDefault, 0
// or less is 0 (r89's one-piece motion), else held to RippleMin-RippleMax.
inline constexpr float RippleDefault = 1.0f, RippleMin = 0.25f, RippleMax = 4.0f;
inline constexpr float LeanGust = 0.03f; ///< m: a gust front's extra lean (a calm's less)
inline constexpr float Leaf = 0.012f;    ///< m: the leaves' flutter, either way, x strength
inline constexpr float MaxLeaf = 0.08f;  ///< m: the flutter's limit along and across the wind
inline constexpr float LeafCalm = 0.5f;  ///< the share of the flutter that stays in a calm
inline constexpr float LeafHz1 = 1.9f, LeafHz2 = 2.7f; ///< Hz of the two leaf waves
/// The gust envelope E = EnvScale smoothstep(EnvLo, -EnvLo, n) (EnvInv = 1 / (-2 EnvLo)), n the
/// mean of three waves' sines: 0 in a calm, EnvScale in a gust front; its mean is 1 because n is
/// symmetric about 0 (wind-sway-test).
inline constexpr float EnvLo = -0.5f, EnvInv = 1.0f, EnvScale = 2.0f;
/// The gust fronts' waves in the wind's frame (rad per m along the wind s and across it q):
/// EnvWavelength m long at EnvAngle degrees off the wind; the along parts are negative, so the
/// waves, carried by the wind, travel downwind (wind-sway-test ties the numbers).
inline constexpr float EnvWavelength[3] = {9.0f, 13.0f, 17.0f}, EnvAngle[3] = {0.0f, 35.0f, -50.0f};
inline constexpr float Env1S = -0.69813170f, Env1Q = 0.0f, Env2S = -0.39591416f,
                       Env2Q = 0.27722208f, Env3S = -0.23757374f, Env3Q = -0.28312936f;
/// The leaf waves, fixed in the world (rad per m along x, y, z): LeafWavelength m long toward
/// LeafDir (with an up part: the phase changes across, along and up a plant).
inline constexpr float LeafWavelength[2] = {0.9f, 0.65f};
inline constexpr float LeafDir[2][3] = {{0.74f, 0.42f, 0.52f}, {-0.55f, 0.58f, 0.60f}};
inline constexpr float Leaf1X = 5.18070091f, Leaf1Y = 2.94039782f, Leaf1Z = 3.64049253f,
                       Leaf2X = -5.31946793f, Leaf2Y = 5.60962072f, Leaf2Z = 5.80305592f;
/// BB_WIND_SWAY_SHOW=1 (a test view): the gust fronts ShowWave times closer, the travelling part
/// and the flutter ShowGain times stronger (the limits stay).
inline constexpr float ShowGain = 2.5f, ShowWave = 2.5f;

// bbport (r89c_wind-lean): the lean, the default motion with the sway (BB_WIND_SWAY_STYLE unset or
// anything but "wave"; the owner: plants should not wave but bend the way the wind blows, slowly
// unless it really blows, trees barely unless it is strong, a wave only very subtle). FillLean
// writes the ripple's words so that the shaders' ripple code (RippleOr, Envelope) gives
//   along = g (LeanRest D + D E + SA E sin a1), cross = g SC E sin a2, the leaves with LF,
// E the gust fronts' envelope with each front's sine skewed (sin(p + LeanSkew sin p): a front
// comes in in about a third of its time and goes in two thirds), so a plant is pushed downwind as
// a front passes and eases back, never past its rest (WaveRatio WaveMax < 1: along >= 0). Of the
// wind speed v: D = BendMax (v / BbWind::MaxSpeed)^2 x BB_WIND_SWAY; SA = WaveRatio D and SC =
// WaveCross D, each x BB_WIND_SWAY_WAVE, at WaveHz0 + WaveHzPerSpeed v Hz along (WaveCrossFactor
// times that across); LF = Leaf x the wave knob x smoothstep(LeafFrom, LeafFull, v). Trees: a mesh
// whose crown key (its highest point, CrownAt) is more than TreeLo m above its lowest point takes,
// by tau = smoothstep(TreeLo, TreeHi, its height), the weight Ta smoothstep((h / height -
// CrownLow) / (1 - CrownLow)) in place of r89's smoothstep(h / Height): the lower half (trunk and
// main branches) still, Ta = smoothstep(TreeCalm, TreeFull, v). The tip dips by d^2 / (2 h)
// (held to MaxAlong): a stem keeps its length. The view's RippleD.y (1 with the lean, 0 else)
// turns the skew, the trees and the dip on; RippleD.z holds Ta.
inline constexpr float BendMax = 0.12f;  ///< m: D at BbWind::MaxSpeed with BB_WIND_SWAY 1
inline constexpr float LeanRest = 0.25f; ///< the steady lean, a share of D
inline constexpr float LeanSkew = 0.6f;  ///< the fronts' skew: in fast, back slowly
inline constexpr float WaveRatio = 0.15f, WaveCross = 0.075f; ///< the wave's shares of D
inline constexpr float WaveHz0 = 0.15f, WaveHzPerSpeed = 0.15f, WaveCrossFactor = 1.5f;
inline constexpr float LeafFrom = 2.5f, LeafFull = 4.0f; ///< m/s: the leaves flutter from, in full
inline constexpr float TreeLo = 2.0f, TreeHi = 3.5f;     ///< m: a mesh this tall is (all) a tree
inline constexpr float TreeInv = 1.0f / (TreeHi - TreeLo);
inline constexpr float CrownLow = 0.5f; ///< the share of a tree's height that stays still
inline constexpr float CrownInv = 1.0f / (1.0f - CrownLow);
inline constexpr float TreeCalm = 1.0f, TreeFull = 4.0f; ///< m/s: trees still below, in full at
inline constexpr float MeshFloor = 0.1f, DipFloor = 0.05f; ///< m
inline constexpr float WaveDefault = 1.0f, WaveMax = 4.0f; ///< BB_WIND_SWAY_WAVE
static_assert(WaveRatio * WaveMax < 1.0f && WaveCross <= WaveRatio, "never back past rest");

// bbport (r89b_wind-sway-ripple): 128 words a view (r89: 112) and 8192 bytes (r89: 7680)
static_assert(ViewWords == 128 && ViewWords % 4 == 0 && TableAt % 4 == 0 && WindE % 4 == 0 &&
              RippleAt % 4 == 0);
static_assert(BaseAt % 4 == 0 && RegionBytes == 8192);
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

/// bbport (r89c_wind-lean): a world y as a crown key, the key of HeightBias - y: the smallest
/// key is the highest y (y below HeightBias; ResetKey is above every key a vertex offers).
[[nodiscard]] inline std::uint32_t CrownKey(float y) {
    return std::bit_cast<std::uint32_t>(std::max(HeightBias - y, 0.0f));
}

[[nodiscard]] inline float KeyCrown(std::uint32_t key) {
    return HeightBias - std::bit_cast<float>(key);
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
        out[TableAt + i] = BbWind::GustOf(s, t, gusts); // bbport (r116b): the weather's gusts
    }
}

/// An angle taken into [-pi, pi) (the shaders' sin is exact only there).
[[nodiscard]] inline float Wrap(float a) {
    return a - TwoPi * std::floor(a * InvTwoPi + 0.5f);
}

// bbport (r89b_wind-sway-ripple): the ripple. With a strength above 0 (BB_WIND_SWAY_RIPPLE, the
// default 1) the shaders (and Displace) take, in place of r89's displacement (RippleOr):
//   along = clamp(G (L + LG (E - 1) + SA E sin a1), +-MaxAlong),
//   cross = clamp(G SC E sin a2, +-MaxCross),
//   leaf = G LF (LeafCalm + (1 - LeafCalm) E), la = clamp(leaf sin b1, +-MaxLeaf), lc = ... sin b2,
//   d = w (along, cross) + w t (la, lc) in the wind's frame (along = toward where it blows),
// with r89's t = clamp(h / Height, 0, 1) and w = smoothstep(t) times the ramp (h: the height above
// the mesh's lowest point), so the roots stay and the leaves flutter in full from Height up. E is
// the gust envelope at the vertex (Envelope: three waves carried by the wind, so fronts and calms
// pass through a bush and from plant to plant downwind at the wind's speed times its gust; up-wind
// plants move first). a1 and a2 are r89's swing waves (k, k2 and j of its words: they travel
// downwind at max(speed, MinWaveSpeed)), b1 and b2 the leaf waves (Leaf1, Leaf2: fixed in the world
// at LeafHz1 and LeafHz2), all from the phases Ripple keeps (FillRipple writes a1's and a2's into
// r89's words WindB.w and WindC.z, so the shaders' sin a1 and sin a2 serve both rules). G is r89's
// gust factor at the vertex (its gust table, which FillRipple writes from the gust time Ripple
// keeps: the gust that passed the camera, carried downwind at max(speed, 0.1 m/s)). L = Lean,
// LG = LeanGust, SA = Flutter, SC = Cross, LF = Leaf, the last four times the strength (and
// ShowGain with BB_WIND_SWAY_SHOW=1), each times r89's amp (BB_WIND_SWAY times min(speed,
// SpeedCap) / RefSpeed). Each term depends on the vertex's world position (through its clip
// position) and the draw's words, never on the vertex's index, so a vertex that two triangles
// share moves the same way in both.

/// BB_WIND_SWAY_RIPPLE and BB_WIND_SWAY_SHOW.
struct RippleKnob {
    float strength = RippleDefault; ///< 0: r89's one-piece motion
    bool show = false;              ///< the test view (only with a strength above 0)
};

[[nodiscard]] inline RippleKnob ParseRipple(const char* ripple, const char* show) {
    RippleKnob k;
    const float value = ParseNumber(ripple, RippleDefault);
    k.strength = value > 0.0f ? std::clamp(value, RippleMin, RippleMax) : 0.0f;
    k.show = k.strength > 0.0f && show != nullptr && show[0] == '1';
    return k;
}

/// Read once, at the first view filled or the first log line.
[[nodiscard]] inline const RippleKnob& RippleKnobOnce() {
    static const RippleKnob knob =
        ParseRipple(std::getenv("BB_WIND_SWAY_RIPPLE"), std::getenv("BB_WIND_SWAY_SHOW"));
    return knob;
}

/// The ripple's wave phases, kept on the CPU so that they never jump. Wave i's phase at the world
/// point p is psi_i + K_i . (p - anchor). Update moves the anchor to the camera of the view being
/// filled without changing the field (psi_i += K_i . (camera - anchor), in double), advances the
/// phases by omega_i times the wind time since the last update, and then takes the wind's direction
/// and speed now for K_i: a turning wind turns the waves about the camera, so a point d m away sees
/// its phase change by at most |K_i| d times the turn's angle. Waves: 0 and 1 r89's swing (K =
/// -k dir + j across and -k2 dir - j across; omega 2 pi SwayHz and 2 pi CrossHz), 2-4 the gust
/// fronts (Env1-Env3 in the wind's frame, ShowWave times with the test view; carried by the wind:
/// omega = -K . wind, the wind being speed times gust along dir), 5 and 6 the leaves (Leaf1, Leaf2,
/// fixed in the world; omega 2 pi LeafHz1 and 2 pi LeafHz2). The gust time is kept alike: r89's
/// gust table holds Gust(t - (p . dir) / v) of the world point p (v = max(speed, 0.1 m/s)); Ripple
/// keeps the time at the anchor (moved by -(camera - anchor) . dir / v, advanced by dt; at the
/// first view r89's own value), so the table FillRipple writes is r89's gust carried downwind, and
/// a turning wind turns it about the camera too.
class Ripple {
public:
    static constexpr std::uint32_t Waves = 7;

    // bbport (r89c_wind-lean): `sway_hz` and `cross_hz` the rates of waves 0 and 1 (r89's
    // swing; the lean's wave), `fronts` the fronts' lengths' divisor (0: in step)
    void Update(const BbWind::Snapshot& s, float cx, float cy, float cz, bool show,
                double sway_hz = SwayHz, double cross_hz = CrossHz, double fronts = 1.0) {
        const double c[3] = {cx, cy, cz};
        if (ready) {
            for (std::uint32_t i = 0; i < Waves; ++i) {
                psi[i] += k[i][0] * (c[0] - anchor[0]) + k[i][1] * (c[1] - anchor[1]) +
                          k[i][2] * (c[2] - anchor[2]);
            }
            gust_time -= ((c[0] - anchor[0]) * gust_dir[0] + (c[2] - anchor[2]) * gust_dir[1]) /
                         gust_speed;
            const double dt = s.time - time;
            if (dt > 0.0 && std::isfinite(dt)) {
                for (std::uint32_t i = 0; i < Waves; ++i) {
                    psi[i] += omega[i] * dt;
                }
                gust_time += dt;
            }
        } else {
            psi = {0.0, 1.9, 0.6, 2.7, 4.1, 0.0, 3.0};
        }
        anchor = {c[0], c[1], c[2]};
        time = s.time;
        Take(s, show, sway_hz, cross_hz, fronts);
        if (!ready) {
            // r89's FillView: s.time - (camera . dir) / v
            gust_time = s.time - (c[0] * gust_dir[0] + c[2] * gust_dir[1]) / gust_speed;
        }
        for (double& p : psi) {
            p = WrapTwoPi(p);
        }
        ready = true;
    }

    [[nodiscard]] double Phase(std::uint32_t i) const {
        return psi[i];
    }

    /// The gust time at the camera of the last Update (r89's s.time - (camera . dir) / v).
    [[nodiscard]] double GustTime() const {
        return gust_time;
    }

private:
    void Take(const BbWind::Snapshot& s, bool show, double sway_hz, double cross_hz,
              double fronts) {
        const double two_pi = 6.28318530717958647692;
        const double speed = std::isfinite(s.speed) ? std::max(double(s.speed), 0.0) : 0.0;
        const double gust = std::isfinite(s.gust) ? double(s.gust) : 1.0;
        const double dx = s.dir_x, dz = s.dir_z;
        const double wave = std::max(speed, double(MinWaveSpeed));
        const double k1 = two_pi * sway_hz / wave, k2 = two_pi * cross_hz / wave;
        const double j = two_pi / CrossWavelength;
        const double ks = show ? ShowWave : 1.0;
        const double ab[5][2] = {{-k1, j},
                                 {-k2, -j},
                                 {Env1S * ks, Env1Q * ks},
                                 {Env2S * ks, Env2Q * ks},
                                 {Env3S * ks, Env3Q * ks}};
        for (std::uint32_t i = 0; i < 5; ++i) {
            // bbport (r89c_wind-lean): the fronts' lengths divided by `fronts` (their rate kept)
            const double sc = i >= 2 ? fronts : 1.0;
            k[i] = {sc * (ab[i][0] * dx - ab[i][1] * dz), 0.0, sc * (ab[i][0] * dz + ab[i][1] * dx)};
        }
        k[5] = {Leaf1X, Leaf1Y, Leaf1Z};
        k[6] = {Leaf2X, Leaf2Y, Leaf2Z};
        const double u = speed * gust;
        omega = {two_pi * sway_hz, two_pi * cross_hz, -ab[2][0] * u,   -ab[3][0] * u,
                 -ab[4][0] * u,    two_pi * LeafHz1, two_pi * LeafHz2};
        gust_dir = {dx, dz};
        gust_speed = std::max(speed, 0.1); // r89's FillView floor
    }

    std::array<double, Waves> psi{}, omega{};
    std::array<std::array<double, 3>, Waves> k{};
    std::array<double, 3> anchor{};
    std::array<double, 2> gust_dir{};
    double gust_speed = 1.0, gust_time = 0.0;
    double time = 0.0;
    bool ready = false;
};

/// The ripple's RippleWords words of a view after FillView (which leaves them 0, r89's motion):
/// with a strength above 0, `ripple` is updated for this view's camera and the words are written
/// (RippleA: the phases of waves 0-3; RippleB: waves 4-6 and the fronts' wave scale; RippleC:
/// L, SA, SC, LF; RippleD: LG, 0, 0, the flag 1), and r89's swing phases (WindB.w, WindC.z) and
/// gust table (TableAt; BB_WIND_GUSTS `gusts`) are written again from the values Ripple keeps.
/// Returns whether it wrote them (with a strength of 0 the view stays FillView's, r89's).
inline bool FillRipple(Ripple& ripple, const Camera& cam, const BbWind::Snapshot& s, float gusts,
                       float scale, const RippleKnob& knob, float* view) {
    if (!(knob.strength > 0.0f)) {
        return false;
    }
    ripple.Update(s, cam.x, cam.y, cam.z, knob.show);
    const float speed = std::isfinite(s.speed) ? std::max(s.speed, 0.0f) : 0.0f;
    const float amp = scale * std::min(speed, SpeedCap) / RefSpeed;
    const float r = knob.strength * (knob.show ? ShowGain : 1.0f);
    float* out = view + RippleAt;
    for (std::uint32_t i = 0; i < Ripple::Waves; ++i) {
        out[i] = float(ripple.Phase(i));
    }
    view[WindB + 3] = out[0];
    view[WindC + 2] = out[1];
    for (std::uint32_t i = 0; i < GustSamples; ++i) {
        // as FillView's table, the time taken from `ripple`
        const double t = ripple.GustTime() + (double(i) - GustMid) * GustStep;
        view[TableAt + i] = BbWind::GustOf(s, t, gusts); // bbport (r116b)
    }
    out[7] = knob.show ? ShowWave : 1.0f;
    out[8] = Lean * amp;
    out[9] = r * Flutter * amp;
    out[10] = r * Cross * amp;
    out[11] = r * Leaf * amp;
    out[12] = r * LeanGust * amp;
    out[13] = 0.0f;
    out[14] = 0.0f;
    out[15] = 1.0f;
    return true;
}

/// bbport (r89c_wind-lean): BB_WIND_SWAY_STYLE and BB_WIND_SWAY_WAVE.
struct LeanKnob {
    bool lean = true;         ///< false: BB_WIND_SWAY_STYLE=wave (r89b's ripple, FillRipple)
    float wave = WaveDefault; ///< BB_WIND_SWAY_WAVE: the subtle wave's size, 0-WaveMax
};

[[nodiscard]] inline LeanKnob ParseLean(const char* style, const char* wave) {
    LeanKnob k;
    k.lean = !(style != nullptr && std::strcmp(style, "wave") == 0);
    k.wave = std::clamp(ParseNumber(wave, WaveDefault), 0.0f, WaveMax);
    return k;
}

/// Read once, at the first view filled or the first log line.
[[nodiscard]] inline const LeanKnob& LeanKnobOnce() {
    static const LeanKnob knob =
        ParseLean(std::getenv("BB_WIND_SWAY_STYLE"), std::getenv("BB_WIND_SWAY_WAVE"));
    return knob;
}

/// The lean's numbers at wind speed `speed` (m/s, held to 0-BbWind::MaxSpeed), BB_WIND_SWAY
/// `scale`, BB_WIND_SWAY_WAVE `wave` and the test view `show`: m at a full weight and a gust factor
/// of 1, before the limits (bend D, rest LeanRest D, the wave's along SA and across SC, the leaves
/// LF), Hz (the wave along and across) and the trees' Ta.
struct LeanCurve {
    float bend = 0.0f, rest = 0.0f, along = 0.0f, cross = 0.0f;
    float hz = 0.0f, cross_hz = 0.0f, leaf = 0.0f, tree = 0.0f;
};

[[nodiscard]] inline LeanCurve LeanAt(float speed, float scale, float wave, bool show) {
    const float v = std::isfinite(speed) ? std::clamp(speed, 0.0f, BbWind::MaxSpeed) : 0.0f;
    const float x = v / BbWind::MaxSpeed;
    const float gain = scale * (show ? ShowGain : 1.0f);
    LeanCurve c;
    c.bend = gain * BendMax * x * x;
    c.rest = LeanRest * c.bend;
    c.along = WaveRatio * wave * c.bend;
    c.cross = WaveCross * wave * c.bend;
    c.hz = WaveHz0 + WaveHzPerSpeed * v;
    c.cross_hz = WaveCrossFactor * c.hz;
    c.leaf = gain * wave * Leaf * BbWind::Smoothstep(LeafFrom, LeafFull, v);
    c.tree = BbWind::Smoothstep(TreeCalm, TreeFull, v);
    return c;
}

/// The lean's words of a view after FillView (in place of FillRipple's; always written): `ripple`
/// is updated for this view's camera with the wave's rates and the fronts' scale (BB_WIND_SWAY_RIPPLE
/// `knob.strength`: 0 every plant in step), the phases (RippleA, RippleB), r89's swing phases and
/// wave numbers (WindB.w, WindC.z, WindC.x, WindD.w) and gust table written from it, RippleB.w the
/// fronts' scale, RippleC (LeanRest D + D, SA, SC, LF), RippleD (D, 1: the lean, Ta, 1: the flag).
inline bool FillLean(Ripple& ripple, const Camera& cam, const BbWind::Snapshot& s, float gusts,
                     float scale, const RippleKnob& knob, const LeanKnob& lean, float* view) {
    const float speed = std::isfinite(s.speed) ? std::max(s.speed, 0.0f) : 0.0f;
    const LeanCurve c = LeanAt(speed, scale, lean.wave, knob.show);
    ripple.Update(s, cam.x, cam.y, cam.z, knob.show, c.hz, c.cross_hz, knob.strength);
    float* out = view + RippleAt;
    for (std::uint32_t i = 0; i < Ripple::Waves; ++i) {
        out[i] = float(ripple.Phase(i));
    }
    view[WindB + 3] = out[0];
    view[WindC + 2] = out[1];
    const double two_pi = 6.28318530717958647692;
    const double wave = std::max(double(speed), double(MinWaveSpeed));
    view[WindC] = float(two_pi * double(c.hz) / wave); // as Ripple's k of wave 0 and 1
    view[WindD + 3] = float(two_pi * double(c.cross_hz) / wave);
    for (std::uint32_t i = 0; i < GustSamples; ++i) {
        const double t = ripple.GustTime() + (double(i) - GustMid) * GustStep;
        view[TableAt + i] = BbWind::GustOf(s, t, gusts); // bbport (r116b)
    }
    out[7] = (knob.show ? ShowWave : 1.0f) * knob.strength;
    out[8] = c.rest + c.bend;
    out[9] = c.along;
    out[10] = c.cross;
    out[11] = c.leaf;
    out[12] = c.bend;
    out[13] = 1.0f;
    out[14] = c.tree;
    out[15] = 1.0f;
    return true;
}

/// The lean's once line (Rasterizer::WindSwayFrameEnd), under 300 characters.
inline void LeanOnceText(const LeanKnob& lean, const RippleKnob& k, float scale, char* out,
                         std::size_t size) {
    const LeanCurve c = LeanAt(BbWind::DefaultSpeed, scale, lean.wave, k.show);
    std::snprintf(out, size,
                  "Wind sway lean (r89c, BB_WIND_SWAY_WAVE=%.2f, RIPPLE=%.2f%s): plants bend "
                  "downwind as gust fronts pass (%s), in fast, back slowly, never past rest; wave "
                  "%.0f%% of the bend at %.2f Hz; trees (meshes %.1f-%.1f m tall) x%.2f at 1.5 m/s, "
                  "top half only; leaves from %.1f m/s; tips dip",
                  double(lean.wave), double(k.strength), k.show ? ", SHOW" : "",
                  k.strength > 0.0f ? "travelling downwind" : "every plant in step",
                  double(100.0f * WaveRatio * lean.wave), double(c.hz), double(TreeLo),
                  double(TreeHi), double(c.tree), double(LeafFrom));
}

/// The lean's numbers at 0.5, 1.5, 3 and 4 m/s, once, under 300 characters: a tip's bend at most
/// (a front's E of 2, a gust factor of 1), the time between the 9 m fronts, the wave's size (E 2)
/// and rate, the leaves, the trees' Ta.
inline void LeanTableText(const LeanKnob& lean, const RippleKnob& k, float scale, char* out,
                          std::size_t size) {
    const float at[4] = {0.5f, 1.5f, 3.0f, 4.0f};
    double tip[4], apart[4], wave[4], hz[4], leaf[4], tree[4];
    for (int i = 0; i < 4; ++i) {
        const LeanCurve c = LeanAt(at[i], scale, lean.wave, k.show);
        tip[i] = double((LeanRest + EnvScale) * c.bend);
        apart[i] = double(EnvWavelength[0] / (k.show ? ShowWave : 1.0f) / at[i]);
        wave[i] = double(EnvScale * c.along);
        hz[i] = double(c.hz);
        leaf[i] = double(c.leaf);
        tree[i] = double(c.tree);
    }
    std::snprintf(out, size,
                  "Wind sway lean (r89c) at 0.5/1.5/3.0/4.0 m/s: tip bend up to %.3f/%.3f/%.3f/%.3f "
                  "m x the gust, fronts %.1f/%.1f/%.1f/%.1f s apart, wave +-%.3f/%.3f/%.3f/%.3f m "
                  "at %.2f/%.2f/%.2f/%.2f Hz, leaves %.3f/%.3f/%.3f/%.3f m, trees "
                  "x%.2f/%.2f/%.2f/%.2f",
                  tip[0], tip[1], tip[2], tip[3], apart[0], apart[1], apart[2], apart[3], wave[0],
                  wave[1], wave[2], wave[3], hz[0], hz[1], hz[2], hz[3], leaf[0], leaf[1], leaf[2],
                  leaf[3], tree[0], tree[1], tree[2], tree[3]);
}

/// The lean's state at the front of r89's line every ReportFrames frames: the wave knob, the
/// fronts' spacing (m), the wind (m/s: speed times its gust now; degrees), a tip's bend at most
/// now (m), the wave's rate (Hz), the trees' Ta and the views that got the lean's words.
inline void LeanText(const LeanKnob& lean, const RippleKnob& k, const BbWind::Snapshot& s,
                     float scale, std::uint64_t views, char* out, std::size_t size) {
    const float speed = std::isfinite(s.speed) ? std::max(s.speed, 0.0f) : 0.0f;
    const float gust = std::isfinite(s.gust) ? s.gust : 1.0f;
    const LeanCurve c = LeanAt(speed, scale, lean.wave, k.show);
    char fronts[48];
    if (k.strength > 0.0f) {
        std::snprintf(fronts, sizeof(fronts), "fronts %.1f m apart",
                      double(EnvWavelength[0] / (k.strength * (k.show ? ShowWave : 1.0f))));
    } else {
        std::snprintf(fronts, sizeof(fronts), "fronts in step");
    }
    std::snprintf(out, size,
                  "lean wave %.2f (%s, %.2f m/s toward %.0f deg, tip bend up to %.3f m, wave "
                  "%.2f Hz, trees x%.2f, %llu views)",
                  double(lean.wave), fronts, double(speed * gust), double(s.direction_deg),
                  double((LeanRest + EnvScale) * c.bend), double(c.hz), double(c.tree),
                  static_cast<unsigned long long>(views));
}

/// The gust envelope E at s, q m along and across the wind from the view's camera (the shaders'
/// rule): 0 in a calm, up to EnvScale in a front.
[[nodiscard]] inline float Envelope(const float* view, float s, float q) {
    const float* p = view + RippleAt;
    const float se = s * p[7], qe = q * p[7];
    // bbport (r89c_wind-lean): each front's sine skewed by RippleD.y x LeanSkew (0 but with the
    // lean, which leaves r89b's envelope as it was): a front comes in fast and goes slowly
    const float skew = p[13] * LeanSkew;
    const auto wave = [&](float phase, float ka, float kb) {
        const float a = Wrap(phase + ka * se + kb * qe);
        return std::sin(a + skew * std::sin(a));
    };
    const float n =
        (wave(p[2], Env1S, Env1Q) + wave(p[3], Env2S, Env2Q) + wave(p[4], Env3S, Env3Q)) *
        (1.0f / 3.0f);
    const float tt = std::clamp((n - EnvLo) * EnvInv, 0.0f, 1.0f);
    return tt * tt * (3.0f - 2.0f * tt) * EnvScale;
}

/// What the shaders put in place of r89's (ddx_one, ddz_one): the ripple's displacement where the
/// view's flag word (RippleD + 3) is above 0, else (ddx_one, ddz_one) themselves. rx, rz: the
/// vertex relative to the camera; s, q: along and across the wind; t, w: r89's weights; g, a1, a2:
/// r89's gust factor at the vertex and swing angles (from the words FillRipple rewrote).
[[nodiscard]] inline std::array<float, 2> RippleOr(const float* view,
                                                   const std::array<float, 4>& clip, float rx,
                                                   float rz, float s, float q, float t, float w,
                                                   float g, float a1, float a2, float ddx_one,
                                                   float ddz_one) {
    const float* p = view + RippleAt;
    if (!(0.0f < p[15])) {
        return {ddx_one, ddz_one};
    }
    const float ry = view[ToWorldAt + 4] * clip[0] + view[ToWorldAt + 5] * clip[1] +
                     view[ToWorldAt + 6] * clip[2] + view[ToWorldAt + 7] * clip[3];
    const float env = Envelope(view, s, q);
    const auto leaf_wave = [&](float phase, float kx, float ky, float kz) {
        return std::sin(Wrap(phase + kx * rx + ky * ry + kz * rz));
    };
    const float b1 = leaf_wave(p[5], Leaf1X, Leaf1Y, Leaf1Z);
    const float b2 = leaf_wave(p[6], Leaf2X, Leaf2Y, Leaf2Z);
    const float dx = view[WindA], dz = view[WindA + 1];
    const float along = std::clamp(g * (p[8] + p[12] * (env - 1.0f) + p[9] * env * std::sin(a1)),
                                   -view[WindE], view[WindE]);
    const float cross =
        std::clamp(g * (p[10] * env * std::sin(a2)), -view[WindE + 1], view[WindE + 1]);
    const float leaf = g * (p[11] * (LeafCalm + (1.0f - LeafCalm) * env));
    const float la = std::clamp(leaf * b1, -MaxLeaf, MaxLeaf);
    const float lc = std::clamp(leaf * b2, -MaxLeaf, MaxLeaf);
    const float wf = w * t;
    return {w * (dx * along - dz * cross) + wf * (dx * la - dz * lc),
            w * (dz * along + dx * cross) + wf * (dz * la + dx * lc)};
}

/// The once line (Rasterizer::WindSwayFrameEnd), under 300 characters: the amplitudes at
/// RefSpeed and a gust factor of 1, before the limits it names.
inline void RippleOnceText(const RippleKnob& k, float scale, char* out, std::size_t size) {
    if (!(k.strength > 0.0f)) {
        std::snprintf(out, size,
                      "Wind sway ripple (r89b): off (BB_WIND_SWAY_RIPPLE=0); the plants sway as "
                      "one piece (r89's motion)");
        return;
    }
    const float ks = k.show ? ShowWave : 1.0f;
    const float r = k.strength * (k.show ? ShowGain : 1.0f) * scale;
    std::snprintf(out, size,
                  "Wind sway ripple (r89b, BB_WIND_SWAY_RIPPLE=%.2f%s): gust fronts (waves %.1f, "
                  "%.1f, %.1f m) travel downwind; at 1.5 m/s swing %.3f/%.3f m "
                  "x front 0-%.0f, lean %.3f +-%.3f m, leaves %.3f m at %.1f/%.1f Hz, all x the "
                  "gust at the plant (held to %.2f/%.2f/%.2f m); roots still",
                  double(k.strength), k.show ? ", SHOW" : "", double(EnvWavelength[0] / ks),
                  double(EnvWavelength[1] / ks), double(EnvWavelength[2] / ks),
                  double(Flutter * r), double(Cross * r), double(EnvScale), double(Lean * scale),
                  double(LeanGust * r), double(Leaf * r), double(LeafHz1), double(LeafHz2),
                  double(MaxAlong), double(MaxCross), double(MaxLeaf));
}

/// The ripple's state at the front of r89's line every ReportFrames frames: the strength, the
/// fronts' spacing (m), their speed (m/s: the wind's speed times its gust now), the direction
/// (degrees), the swing's wavelength (m) and how many views got the ripple's words.
inline void RippleText(const RippleKnob& k, const BbWind::Snapshot& s, std::uint64_t views,
                       char* out, std::size_t size) {
    if (!(k.strength > 0.0f)) {
        std::snprintf(out, size, "ripple off (r89's one-piece motion)");
        return;
    }
    const float speed = std::isfinite(s.speed) ? std::max(s.speed, 0.0f) : 0.0f;
    const float gust = std::isfinite(s.gust) ? s.gust : 1.0f;
    std::snprintf(out, size,
                  "ripple %.2f%s (fronts %.1f m apart, %.2f m/s toward %.0f deg, swing wave "
                  "%.1f m, %llu views)",
                  double(k.strength), k.show ? " SHOW" : "",
                  double(EnvWavelength[0] / (k.show ? ShowWave : 1.0f)), double(speed * gust),
                  double(s.direction_deg), double(std::max(speed, MinWaveSpeed) / SwayHz),
                  static_cast<unsigned long long>(views));
}

// bbport (r89d_tree-twigs): the twigs (bbport_wind_twigs.h has the knob, the box keys and the
// judgement of sun-drawn meshes). With BB_WIND_TWIGS on a tall mesh (the lean's tree rule: tau above
// 0) takes, in place of the top half's weight, a twig weight from where the vertex lies in the mesh's
// box:
//   wt = Gain x smoothstep(TwigRad2Lo, TwigRad2Hi; r^2 / half^2) x smoothstep(TwigHeightLo,
//        TwigHeightHi; h / height),
// r the vertex's distance from the box's centre line, half the box's half width (the larger of the x
// and z extents, at least TwigHalfFloor), h its height above the mesh's lowest point, height the
// mesh's, Gain (the view's RippleD.z, written by the CPU) = TwigRatio x BB_WIND_TWIGS. The trunk and
// the main limbs (near the centre line, or low) stay still; the outer, upper parts move by TwigRatio
// of a bush's lean at most. The weights are smooth in position, so a branch moves as one. A word
// with TreeBit (a sun-drawn stream: a tree, or a character) has no bush weight.
inline constexpr float TwigRatio = 0.30f;
inline constexpr float TwigRadLo = 0.35f, TwigRadHi = 0.85f; ///< of the box's half width
inline constexpr float TwigRad2Lo = TwigRadLo * TwigRadLo, TwigRad2Hi = TwigRadHi * TwigRadHi;
inline constexpr float TwigRad2Inv = 1.0f / (TwigRad2Hi - TwigRad2Lo);
inline constexpr float TwigHeightLo = 0.30f, TwigHeightHi = 0.70f; ///< of the mesh's height
inline constexpr float TwigHeightInv = 1.0f / (TwigHeightHi - TwigHeightLo);
inline constexpr float TwigHalfFloor = 0.5f; ///< m
/// bbport (r89m_twigs-no-tear): the soft cap of a tree word's weight w: w / (1 + |w| / cap). Smooth, about w for a small w, never above
/// cap, slope at most 1. TwigCap x (the largest along and cross 0.427 m + the largest leaf flutter 0.113 m) is the largest move
/// (15.1 cm at the strongest wind); the proof knob's x5 has TwigCapProofMul x the cap (at most about 30 cm). BbWindTwigs::CapOn().
/// bbport (r89n_twigs-visible): r89m's cap kept the twigs under 3 cm. The weight is now boosted by TwigBoost and capped at TwigCap:
/// TwigSoftCap(w) = w / (1 / TwigBoost + |w| / TwigCap): about TwigBoost x w for a small w, tending to TwigCap, slope at most TwigBoost.
/// A limb piece's raw weight 0.05 / 0.15 / 0.3 / 0.6 gives 0.24 / 0.53 / 0.76 / 0.95, and with the push rule's gust crest (D 0.12 m at
/// 4 m/s x (TwigRest + TwigPush) = 0.324 m) 8 / 17 / 25 / 31 cm; at most TwigCap x 0.324 = 42 cm (70 cm by the limits' bound).
/// bbport (r89o_wind-chains-twigs-visible): TwigBoost 6 -> 10, TwigCap 1.3 -> 1.5 (the 4K clips of build 72 showed no twig motion). With the
/// trees' gain 1 (raw weights 0.1 / 0.3 / 0.6 / 1.2) y is 0.60 / 1.00 / 1.20 / 1.33: 19 / 32 / 39 / 43 cm at a gust crest at 4 m/s, at most
/// TwigCap x 0.324 = 49 cm (81 cm by the limits' bound); at 1.5 m/s 7 times less.
inline constexpr float TwigCap = 1.5f, TwigBoost = 10.0f, TwigCapProofMul = 1.0f;
static_assert(TwigCap > 0.0f && TwigBoost >= 1.0f && TwigCapProofMul >= 1.0f);

[[nodiscard]] inline float TwigSoftCap(float w, float cap = TwigCap) {
    return w / (1.0f / TwigBoost + std::fabs(w) / cap); // bbport (r89n_twigs-visible): boosted
}
// bbport (r89f_twigs-scale): with BB_WIND_TWIGS_SIZE the twig weight is multiplied by the vertex's height
// above its mesh's lowest point over SizeRefH, held to 1 .. SizeMax (the lever arm: the lean's bend is a
// bush's, in metres, so a tall tree's tips need a larger move to show). Not applied: BbWindTwigs::SizeOn().
inline constexpr float SizeRefH = 6.0f, SizeMax = 7.0f; ///< m, and a factor
inline constexpr float SizeInv = 1.0f / SizeRefH;
static_assert(SizeRefH > 0.0f && SizeMax >= 1.0f);

// bbport (r89g_twigs-proof): with BB_WIND_TWIGS_FIT (default 1) the twig weight is not a shape in the mesh's box
// (the GPU's box keys of a stream that holds many trees, or whose pieces come and go, measured 4 m, 37 m and 42 m
// of "height" in one run: the fractions of that put the weight on no visible vertex) but a rule of the vertex's own
// height above the camera, hc = wy - the camera's y: smoothstep(FitLo, FitHi; hc) x FitShare, x the size factor at
// hc + FitEye (the camera is about FitEye above the ground where the player stands). BbWindTwigs::FitOn().
inline constexpr float FitLo = 3.0f, FitHi = 9.0f, FitShare = 0.6f, FitEye = 2.0f; ///< m, m, a share, m
inline constexpr float FitInv = 1.0f / (FitHi - FitLo);
static_assert(FitLo < FitHi && FitShare > 0.0f && FitShare <= 1.0f && FitEye >= 0.0f);

// bbport (r89h_twigs-alive): with BB_WIND_TWIGS_PUSH (default 1, needs the fit rule) the along-wind move of a twig
// (the share tau x lean x twig weight x ramp of a vertex's move) is a push that gust fronts bring and release:
//   along = g (D (TwigRest + TwigPush F^2) + TwigFlutter SA E sin a1),  F = E / EnvScale (0..1),
// D the ripple's bend (RippleAt + 12), SA its along wave (RippleAt + 9), E the front envelope (Envelope), g the gust
// factor, held to the view's MaxAlong. A small steady lean (TwigRest of D), a push of up to TwigPush D in a full front
// (F^2: gusts are peaks with calms between), half of the lean's very subtle wave on top. BbWindTwigs::PushOn().
// bbport (r89n_twigs-visible): TwigRest 0.05 -> 0.2 (the steady lean between gusts: a twig's lean was 0.6 cm at 4 m/s, invisible)
inline constexpr float TwigRest = 0.2f, TwigPush = 2.5f, TwigFlutter = 0.5f;
static_assert(TwigRest >= 0.0f && TwigPush > 0.0f && TwigFlutter >= 0.0f && TwigRest + TwigPush <= 4.0f);

/// The twig push rule's along-wind move (m, before the share) of a vertex: `g` the gust factor, `env` the front
/// envelope at the vertex (Envelope), `a1` the swing phase. The shaders do the same, operation for operation.
[[nodiscard]] inline float TwigAlong(const float* view, float g, float env, float a1) {
    const float* p = view + RippleAt;
    const float front = env * (1.0f / EnvScale);
    return std::clamp(g * (p[12] * (TwigRest + TwigPush * (front * front)) + TwigFlutter * p[9] * env * std::sin(a1)),
                      -view[WindE], view[WindE]);
}

/// The ripple's own along-wind move (m, before the weight) of a vertex, as RippleOr computes it (the move the push
/// rule replaces for a twig's share).
[[nodiscard]] inline float RippleAlong(const float* view, float g, float env, float a1) {
    const float* p = view + RippleAt;
    return std::clamp(g * (p[8] + p[12] * (env - 1.0f) + p[9] * env * std::sin(a1)), -view[WindE], view[WindE]);
}

/// The size factor of a vertex `h` m above its mesh's lowest point (the shaders' clamp).
[[nodiscard]] inline float SizeFactor(float h) {
    return std::clamp(h * SizeInv, 1.0f, SizeMax);
}
static_assert(TwigRadLo < TwigRadHi && TwigHeightLo < TwigHeightHi && TwigRatio < 1.0f);

/// smoothstep of x between lo and lo + 1 / inv (the shaders' rule).
[[nodiscard]] inline float Smooth01(float x, float lo, float inv) {
    const float c = std::clamp((x - lo) * inv, 0.0f, 1.0f);
    return c * c * (3.0f - 2.0f * c);
}

/// bbport (r89g_twigs-proof): the twig weight of BB_WIND_TWIGS_FIT for a vertex `hc` m above the camera (before
/// the lean's gust and front): Gain x FitShare x smoothstep(FitLo, FitHi; hc), x the size factor at hc + FitEye
/// when `sized`. The shaders do the same, operation for operation (hc = wy - the camera's y).
[[nodiscard]] inline float FitWeight(const float* view, float hc, bool sized = false) {
    const float weight = view[RippleD + 2] * (FitShare * Smooth01(hc, FitLo, FitInv));
    return sized ? weight * SizeFactor(hc + FitEye) : weight;
}

/// What a vertex knows of its mesh's box: the four keys (HeightKey of the lowest x, CrownKey of the
/// highest x, the same for z; ResetKey: none yet) and the word's TreeBit.
struct TwigIn {
    std::array<std::uint32_t, 4> keys{ResetKey, ResetKey, ResetKey, ResetKey};
    bool tree_only = false;
    bool sized = false; ///< bbport (r89f_twigs-scale): BB_WIND_TWIGS_SIZE (the weight x SizeFactor)
    bool fit = false;   ///< bbport (r89g_twigs-proof): BB_WIND_TWIGS_FIT (FitWeight in place of TwigWeight)
    bool push = false;  ///< bbport (r89h_twigs-alive): BB_WIND_TWIGS_PUSH (TwigAlong for the twig's share)
    bool cap = false;   ///< bbport (r89m_twigs-no-tear): a tree-only word's weight and push share are soft capped (TwigSoftCap)
};

/// The twig weight (before the lean's gust and front) at world x `ax`, z `az`, height `h` above the
/// mesh's lowest point, of a mesh `mesh` m tall with box keys `keys`; `view` holds the gain.
[[nodiscard]] inline float TwigWeight(const float* view, float ax, float az, float h, float mesh,
                                      const std::array<std::uint32_t, 4>& keys, bool sized = false) {
    const float x_lo = KeyHeight(keys[0]), x_hi = KeyCrown(keys[1]);
    const float z_lo = KeyHeight(keys[2]), z_hi = KeyCrown(keys[3]);
    const float cx = 0.5f * (x_lo + x_hi), cz = 0.5f * (z_lo + z_hi);
    const float half_w = std::max(0.5f * std::max(x_hi - x_lo, z_hi - z_lo), TwigHalfFloor);
    const float ex = ax - cx, ez = az - cz;
    const float r2 = (ex * ex + ez * ez) / (half_w * half_w);
    const float wr = Smooth01(r2, TwigRad2Lo, TwigRad2Inv);
    const float wh = Smooth01(h / std::max(mesh, MeshFloor), TwigHeightLo, TwigHeightInv);
    const float weight = view[RippleD + 2] * (wr * wh);
    return sized ? weight * SizeFactor(h) : weight; // bbport (r89f_twigs-scale)
}

/// What the shaders do to one vertex: `view` its ViewWords floats, `clip` the clip position,
/// `stored` its slot's height key, `ramp` the sway word's ramp / 255. The clip position written
/// back; `key` (when not null) the key the vertex offers the slot (ResetKey: none).
[[nodiscard]] inline std::array<float, 4> Displace(const float* view, const std::array<float, 4>& clip,
                                                   std::uint32_t stored, float ramp,
                                                   std::uint32_t* key = nullptr,
                                                   std::uint32_t stored_crown = ResetKey, // r89c
                                                   std::uint32_t* key_crown = nullptr,
                                                   const TwigIn* twig = nullptr, // r89d
                                                   std::array<std::uint32_t, 4>* twig_offer = nullptr) {
    const auto dot = [&](std::uint32_t at) {
        return view[at] * clip[0] + view[at + 1] * clip[1] + view[at + 2] * clip[2] +
               view[at + 3] * clip[3];
    };
    const float rx = dot(ToWorldAt), rz = dot(ToWorldAt + 8);
    const float wy = dot(ToWorldAt + 4) + view[WindA + 2];
    // bbport (r89c_wind-lean): the key the vertex offers its mesh's crown (`key_crown`, CrownKey;
    // the GPU keeps the smaller of it and `stored_crown`, the slot's crown key)
    if (key_crown != nullptr) {
        *key_crown = std::fabs(wy) < FiniteMost ? CrownKey(wy) : ResetKey;
    }
    if (key != nullptr) {
        *key = std::fabs(wy) < FiniteMost ? HeightKey(wy) : ResetKey;
    }
    const float h = wy - KeyHeight(stored);
    const bool fin = std::fabs(h) + std::fabs(rx) + std::fabs(rz) < FiniteMost;
    // bbport (r89d_tree-twigs): the keys the vertex offers its mesh's box (`twig_offer`: the GPU
    // keeps the smaller of each and the stored one)
    if (twig_offer != nullptr) {
        const float ax = view[WindE + 2] + rx, az = view[WindE + 3] + rz;
        *twig_offer = fin ? std::array<std::uint32_t, 4>{HeightKey(ax), CrownKey(ax), HeightKey(az),
                                                          CrownKey(az)}
                          : std::array<std::uint32_t, 4>{ResetKey, ResetKey, ResetKey, ResetKey};
    }
    if (!fin) {
        return clip;
    }
    const float t = std::clamp(h * view[WindD], 0.0f, 1.0f);
    // bbport (r89c_wind-lean): with the lean (the view's RippleD.y 1) a tall mesh (its crown key
    // more than TreeLo m above its lowest point) takes the tree weight in place of r89's
    const float lean = view[RippleD + 1];
    const float mesh = KeyCrown(stored_crown) - KeyHeight(stored);
    const float tc = std::clamp((mesh - TreeLo) * TreeInv, 0.0f, 1.0f);
    const float tau = tc * tc * (3.0f - 2.0f * tc);
    const float tk = std::clamp((h / std::max(mesh, MeshFloor) - CrownLow) * CrownInv, 0.0f, 1.0f);
    const float wt = view[RippleD + 2] * (tk * tk * (3.0f - 2.0f * tk));
    const float wb = t * t * (3.0f - 2.0f * t);
    // bbport (r89d_tree-twigs): with `twig` (BB_WIND_TWIGS on) a tall mesh takes the twig weight in
    // place of the top half's, and a mesh that may only be a tree (TreeBit) has no bush weight
    float wt_use = wt, wb_use = wb;
    if (twig != nullptr) {
        wt_use = tau > 0.0f
                     ? (twig->fit ? FitWeight(view, wy - view[WindA + 2], twig->sized) // bbport (r89g)
                                  : TwigWeight(view, view[WindE + 2] + rx, view[WindE + 3] + rz, h, mesh,
                                               twig->keys, twig->sized))
                     : 0.0f;
        wb_use = twig->tree_only ? 0.0f : wb;
    }
    float w = (wb_use + tau * lean * (wt_use - wb_use)) * ramp;
    if (twig != nullptr && twig->cap && twig->tree_only) { // bbport (r89m_twigs-no-tear): the soft cap
        w = TwigSoftCap(w);
    }
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
    // bbport (r89b_wind-sway-ripple): the ripple's displacement where its flag word is above 0;
    // with it 0 (BB_WIND_SWAY_RIPPLE=0: FillView alone) these two of r89's, unchanged
    const std::array<float, 2> moved = RippleOr(view, clip, rx, rz, s, q, t, w, g, a1, a2,
                                                w * (dx * along - dz * cross),
                                                w * (dz * along + dx * cross));
    float ddx = moved[0], ddz = moved[1];
    // bbport (r89h_twigs-alive): the twig's share of the move (tau x lean x twig weight x ramp) takes the push rule's
    // along in place of the ripple's (only with the ripple, the flag word above 0)
    if (twig != nullptr && twig->push && 0.0f < view[RippleD + 3]) {
        const float env = Envelope(view, s, q);
        float twig_share = tau * lean * wt_use * ramp;
        if (twig->cap && twig->tree_only) { // bbport (r89m_twigs-no-tear): the same cap
            twig_share = TwigSoftCap(twig_share);
        }
        const float extra = twig_share * (TwigAlong(view, g, env, a1) - RippleAlong(view, g, env, a1));
        ddx += extra * dx;
        ddz += extra * dz;
    }
    std::array<float, 4> out = clip;
    for (std::uint32_t r = 0; r < 4; ++r) {
        out[r] = clip[r] + (view[ForwardAt + r * 4] * ddx + view[ForwardAt + r * 4 + 2] * ddz);
    }
    // bbport (r89c_wind-lean): with the lean the tip dips as it bends (a stem keeps its length):
    // d^2 / (2 h), held to MaxAlong; none without it (r89's and r89b's results stay bit for bit)
    if (0.0f < lean) {
        const float dip =
            std::min(0.5f * (ddx * ddx + ddz * ddz) / std::max(h, DipFloor), MaxAlong);
        for (std::uint32_t r = 0; r < 4; ++r) {
            out[r] -= view[ForwardAt + r * 4 + 1] * dip;
        }
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
        std::uint32_t best = PlantSlots; // bbport (r89c_wind-lean): the plant slots
        std::uint64_t oldest = std::numeric_limits<std::uint64_t>::max();
        for (std::uint32_t i = 0; i < PlantSlots; ++i) {
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
        if (best == PlantSlots) {
            return {};
        }
        if (slots[best].stream != 0) {
            const auto old = by_stream.find(slots[best].stream); // bbport (r89e): Release
            if (old != by_stream.end() && old->second == best) {
                by_stream.erase(old);
            }
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

    /// bbport (r89e_twigs-big-trees): gives a stream's slot back (a static cut-out judged not a
    /// tree). The slot rests ReuseFrames frames like any slot no longer drawn (frames still in
    /// flight write the old stream's keys; FrameSlots < ReuseFrames), then another stream may
    /// take it and reset its keys.
    void Release(std::uint64_t stream) {
        const auto found = by_stream.find(stream);
        if (found == by_stream.end()) {
            return;
        }
        slots[found->second].released = true;
        by_stream.erase(found);
    }

    /// bbport (r89d_tree-twigs): fn(slot, stream, size) for each slot drawn within the last
    /// ReuseFrames frames.
    template <class F>
    void ForEachInUse(std::uint64_t frame, F&& fn) const {
        for (std::uint32_t i = 0; i < PlantSlots; ++i) {
            const Slot& slot = slots[i];
            if (slot.stream != 0 && slot.last + ReuseFrames >= frame) {
                fn(i, slot.stream, slot.size);
            }
        }
    }

private:
    struct Slot {
        std::uint64_t stream = 0;
        std::uint32_t size = 0;
        std::uint64_t last = 0;
        double time = 0.0;
        bool released = false; ///< bbport (r89e_twigs-big-trees): given back by Release
    };
    std::array<Slot, PlantSlots> slots{}; // bbport (r89c_wind-lean): CrownAt's half is crowns
    std::unordered_map<std::uint64_t, std::uint32_t> by_stream;
};

/// Counts for the log's line every ReportFrames frames.
struct Stats {
    std::uint64_t draws = 0;  ///< skinned draws of sway pipelines
    std::uint64_t plants = 0; ///< of them, plants
    std::uint64_t swayed = 0; ///< plants given a sway word
    std::uint64_t ramping = 0; ///< of those, with a ramp below 255
    std::uint64_t no_rt = 0, no_camera = 0, views_full = 0, no_slot = 0, no_region = 0;
    std::uint64_t rippled_views = 0; ///< bbport (r89b_wind-sway-ripple): views given the ripple
};

} // namespace BbWindSway
