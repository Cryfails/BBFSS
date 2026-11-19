// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r41_lamp-shadows): the tuning of the ray traced lamp shadow pass (lamp_shadow_tune.h):
// defaults, clamping, bad text, the words the shader reads and the weight it works out.
// bbport (r42_lamp-soft): the area lamp's knobs, the frames of history, and the lamps of a pass
// told apart and followed from one frame to the next (LampTrack).
// bbport (r44_half-area-lamp): which pass of a frame has the area lamp (LampPassRadius).
// bbport (r48_lamp-softness): graphics_lamp_shadow_softness as the lamp's radius
// (LampSoftnessRadius, BB_LAMP_SHADOW_SOFT winning) and a point lamp's steps (LampPassSteps).
// bbport (r52_follow-soft): BB_LAMP_SHADOW_FOLLOW_SOFT and its bit in word 0.
// bbport (r57_lamp-window): BB_LAMP_SHADOW_WINDOW and its bit in word 0.
// bbport (r60_lamp-centred-window): its value 2 (bit 22), and a CPU model of the ghost clamp's
// 5x5 statistic: centred on every pixel it does not change as the workgroups' grid moves.
// bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR, its bit in word 0 and the colour's rescale.
#include <array>
#include <bit>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <utility>
#include <vector>
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h"
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_flame.h" // bbport (r113_lamp-softness)
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_young_pixels.h" // bbport (r103_lamp-young-pixels)

using namespace Vulkan;

namespace {
using Pair = std::pair<const char*, const char*>;
// The environment of the case being read.
const Pair* env_begin = nullptr;
const Pair* env_end = nullptr;

const char* Get(const char* name) {
    for (const Pair* it = env_begin; it != env_end; ++it) {
        if (std::strcmp(it->first, name) == 0) {
            return it->second;
        }
    }
    return nullptr;
}

template <std::size_t N>
LampShadowTune Read(const std::array<Pair, N>& env) {
    env_begin = env.data();
    env_end = env.data() + N;
    return ReadLampShadowTune(Get);
}

float F(std::uint32_t word) {
    return std::bit_cast<float>(word);
}

bool Near(float a, float b) {
    return std::abs(a - b) <= 1e-6f;
}

// A lamp record as the pass has it: its place in view space, 1 / reach squared, its colour.
std::array<std::uint32_t, 16> Record(float x, float y, float z, float reach, float grey = 1.0f) {
    std::array<std::uint32_t, 16> r{};
    const std::array<float, 7> f{x, y, z, 1.0f / (reach * reach), grey, grey, grey};
    for (std::size_t k = 0; k < f.size(); ++k) {
        r[k] = std::bit_cast<std::uint32_t>(f[k]);
    }
    return r;
}

// bbport (r60_lamp-centred-window): word 0's window bits of the default (LampWindowDefault), so
// that the asserts below hold whichever of 1 and 2 is the default.
constexpr std::uint32_t DefaultWindowBits =
    (LampWindowDefault >= 1 ? LampTuneWindow : 0u) | (LampWindowDefault == 2 ? LampTuneCentred : 0u);

// bbport (r60_lamp-centred-window): a CPU model of the ghost clamp's 5x5 statistic (count, sum,
// sum of squares of the answers, point_shadow_ray.comp). It is a hand copy of the shader's index
// arithmetic (loadTile and the centred loop), not a test of the shader: a fault made in the
// shader alone is caught only by a GPU run (rt-shadow-test --lamps). What it checks: that tile
// arithmetic, written as the shader has it, gives every pixel the statistic of its own 5x5
// neighbourhood, which Direct works out on its own (its own bounds from the rect and the
// screen, its own test for an answer). Not modelled: the half-resolution fill pass (its window
// over the first pass's answers at even pixels, and its trace not storing over them), workgroups
// without a tile, the cast codes beside the answers (CastCode below checks their packing alone).
//
// The answers the trace stored, by pass pixel: pass pixel (x, y) is full pixel (apart x, apart y),
// apart 1, or 2 in the half-resolution build's first pass. Below 0: none. size and rect in full
// pixels, as the push block has them (the rect may reach past the screen).
struct Field {
    int apart = 1;
    std::array<int, 2> size{};               // the screen
    std::array<int, 4> rect{};               // the pass's rect
    int pw = 0, ph = 0;                      // pass pixels on the screen: (size + apart - 1) / apart
    int w = 0, h = 0;                        // pass pixels stored: more, so a read past the screen
                                             // finds an answer (and a missed clip shows)
    std::vector<float> answer;               // w * h
};
struct Stat {
    float count = 0.0f, sum = 0.0f, sum2 = 0.0f;
    bool operator==(const Stat&) const = default;
};
// The statistic of pass pixel (x, y) from its own 5x5 neighbourhood, in the shader's order, on
// its own: a neighbour counts where it lies in the rect and on the screen (as bounds on pass
// pixels, rounded up from the full pixels' bounds) and has an answer.
Stat Direct(const Field& f, int x, int y) {
    const auto up = [&](int v) { return (v + f.apart - 1) / f.apart; }; // the first pass pixel at or past v
    const int x0 = up(f.rect[0]), y0 = up(f.rect[1]);
    const int x1 = std::min(up(f.rect[2]), up(f.size[0])), y1 = std::min(up(f.rect[3]), up(f.size[1]));
    Stat s;
    for (int dy = -2; dy <= 2; ++dy) {
        for (int dx = -2; dx <= 2; ++dx) {
            const int nx = x + dx, ny = y + dy;
            if (nx < x0 || ny < y0 || nx >= x1 || ny >= y1) {
                continue;
            }
            const float a = f.answer[std::size_t(ny * f.w + nx)];
            if (a < 0.0f) {
                continue;
            }
            s.count += 1.0f;
            s.sum += a;
            s.sum2 += a * a;
        }
    }
    return s;
}
// BB_LAMP_SHADOW_WINDOW=2, as the shader: loadTile (full pixel q = lo + apart * (cell - 2), "no
// answer" outside the rect or the screen) and the centred loop (cell (lid + 2 + d), counted where
// a >= 0). lo: the workgroup's first full pixel; (lx, ly): the invocation.
Stat Centred(const Field& f, int lox, int loy, int lx, int ly) {
    std::array<float, 144> tile{};
    for (std::uint32_t i = 0; i < 144u; ++i) {
        const int qx = lox + f.apart * (int(i % 12u) - 2), qy = loy + f.apart * (int(i / 12u) - 2);
        float a = -1.0f;
        if (qx >= f.rect[0] && qy >= f.rect[1] && qx < f.rect[2] && qy < f.rect[3] && qx < f.size[0] &&
            qy < f.size[1]) {
            a = f.answer[std::size_t((qy / f.apart) * f.w + qx / f.apart)];
        }
        tile[i] = a;
    }
    Stat s;
    for (int y = -2; y <= 2; ++y) {
        for (int x = -2; x <= 2; ++x) {
            const float a = tile[std::size_t((ly + 2 + y) * 12 + lx + 2 + x)];
            if (a >= 0.0f) {
                s.count += 1.0f;
                s.sum += a;
                s.sum2 += a * a;
            }
        }
    }
    return s;
}
// BB_LAMP_SHADOW_WINDOW=1: the window moved in from the workgroup's rim (around_lo), over the
// workgroup's own answers only (its pixels in the rect and on the screen).
Stat Confined(const Field& f, int gx, int gy, int lx, int ly) {
    const int ax = std::clamp(lx - 2, 0, 3), ay = std::clamp(ly - 2, 0, 3);
    Stat s;
    for (int y = ay; y < ay + 5; ++y) {
        for (int x = ax; x < ax + 5; ++x) {
            const int px = gx + x, py = gy + y, fx = f.apart * px, fy = f.apart * py;
            if (fx < f.rect[0] || fy < f.rect[1] || fx >= f.rect[2] || fy >= f.rect[3] || fx >= f.size[0] ||
                fy >= f.size[1]) {
                continue;
            }
            const float a = f.answer[std::size_t(py * f.w + px)];
            if (a >= 0.0f) {
                s.count += 1.0f;
                s.sum += a;
                s.sum2 += a * a;
            }
        }
    }
    return s;
}
// Every pass pixel's statistic with the workgroups' origins shifted by `shift` pass pixels (as the
// picture moves under the fixed grid of 8x8 workgroups); centred: value 2, else value 1.
std::vector<Stat> Statistic(const Field& f, int shift, bool centred) {
    std::vector<Stat> out(std::size_t(f.pw * f.ph));
    for (int y = 0; y < f.ph; ++y) {
        for (int x = 0; x < f.pw; ++x) {
            const int gx = (x - shift + 8) / 8 * 8 - 8 + shift, gy = (y - shift + 8) / 8 * 8 - 8 + shift;
            out[std::size_t(y * f.pw + x)] = centred ? Centred(f, f.apart * gx, f.apart * gy, x - gx, y - gy)
                                                     : Confined(f, gx, gy, x - gx, y - gy);
        }
    }
    return out;
}

// bbport (r60_lamp-centred-window): the cast code's way through the answers image, written from
// the GLSL rules (not from the shader's text): packHalf2x16 puts the code, as a half float, in the
// high 16 bits (round to nearest even here; the code's classes do not depend on the rounding),
// the record / 16 goes in the low 16 bits, unpackHalf2x16(...).y reads the code back.
std::uint16_t ToHalf(float v) {
    const std::uint32_t b = std::bit_cast<std::uint32_t>(v);
    const std::uint32_t sign = (b >> 16) & 0x8000u;
    const std::uint32_t mag = b & 0x7FFFFFFFu;
    const int exp = int(mag >> 23) - 127 + 15;
    if (mag == 0u || exp < -10) {
        return std::uint16_t(sign);
    }
    assert(exp < 31); // the codes lie within -5 and 64
    std::uint32_t man = (mag & 0x7FFFFFu) | 0x800000u;
    const int shift = exp >= 1 ? 13 : 14 - exp;
    std::uint32_t h = man >> shift;
    const std::uint32_t rest = man & ((1u << shift) - 1u), halfway = 1u << (shift - 1);
    if (rest > halfway || (rest == halfway && (h & 1u) != 0u)) {
        ++h;
    }
    if (exp >= 1) {
        h = (std::uint32_t(exp) << 10) + (h - 0x400u); // (a carry out of the mantissa moves the exponent)
    }
    return std::uint16_t(sign | h);
}
float FromHalf(std::uint16_t h) {
    const int exp = (h >> 10) & 31;
    const float man = float(h & 0x3FFu);
    const float v = exp == 0 ? std::ldexp(man, -24) : std::ldexp(1.0f + man / 1024.0f, exp - 15);
    return (h & 0x8000u) != 0u ? -v : v;
}
// What the texel's y holds (storeAnswer) and what is read back of it (the resolve).
std::uint32_t PackCast(float code, std::uint32_t record) {
    const std::uint32_t at = (record & 15u) == 0u && record < (1u << 20) ? record >> 4 : 0u;
    return (std::uint32_t(ToHalf(code)) << 16) | at;
}
float CastOf(std::uint32_t y) { return FromHalf(std::uint16_t(y >> 16)); }
std::uint32_t RecordOf(std::uint32_t y) { return (y & 0xFFFFu) << 4; }
} // namespace

int main() {
    // Nothing set: the defaults the patch documents.
    {
        const LampShadowTune t = Read(std::array<Pair, 0>{});
        assert(t.weights && t.wrap == 0.15f && t.facing_floor == 0.05f);
        assert(t.radius_m == 0.1f && t.history == 0.9f && t.reject == 0.5f && t.trail_m == 0.08f);
        assert(t.follow && !t.stale && t.carry_m == 2.5f && t.around == 1.6f);
        assert(t.self_m == 0.06f && t.view == 0u && t.view_gain == 0.5f);
        // The values of before where the shader had constants.
        assert(t.clearance_m == 0.18f && t.bias_m == 0.03f); // bbport (r90): 0.35 before
    }
    // Every knob read.
    {
        const LampShadowTune t = Read(std::array<Pair, 16>{{
            {"BB_LAMP_SHADOW_CARRY", "1.5"},
            {"BB_LAMP_SHADOW_CLAMP", "2.5"},
            {"BB_LAMP_SHADOW_FLOOR", "0.25"},
            {"BB_LAMP_SHADOW_WEIGHTS", "0"},
            {"BB_LAMP_SHADOW_WRAP", "0.5"},
            {"BB_LAMP_SHADOW_SOFT", "0.2"},
            {"BB_LAMP_SHADOW_HISTORY", "0.8"},
            {"BB_LAMP_SHADOW_REJECT", "0.7"},
            {"BB_LAMP_SHADOW_TRAIL", "0.5"},
            {"BB_LAMP_SHADOW_FOLLOW", "0"},
            {"BB_LAMP_SHADOW_STALE", "1"},
            {"BB_LAMP_SHADOW_CLEARANCE", "0.2"},
            {"BB_LAMP_SHADOW_BIAS", "0.05"},
            {"BB_LAMP_SHADOW_SELF", "0.12"},
            {"BB_LAMP_SHADOW_VIEW", "4"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "4"},
        }});
        assert(!t.weights && t.wrap == 0.5f && t.facing_floor == 0.25f);
        assert(t.radius_m == 0.2f && t.history == 0.8f && t.reject == 0.7f && t.trail_m == 0.5f);
        assert(!t.follow && t.stale && t.carry_m == 1.5f && t.around == 2.5f);
        assert(t.clearance_m == 0.2f && t.bias_m == 0.05f);
        assert(t.self_m == 0.12f && t.view == 4u && t.view_gain == 4.0f);
    }
    // r41's rim knobs are gone: set, they change nothing.
    {
        const LampShadowTune t = Read(std::array<Pair, 3>{{
            {"BB_LAMP_SHADOW_RIM", "4"},
            {"BB_LAMP_SHADOW_SHARE", "0.9"},
            {"BB_LAMP_SHADOW_NEAR", "1"},
        }});
        const LampShadowTune d;
        assert(LampTuneWords(t, false, 0.05f) == LampTuneWords(d, false, 0.05f));
        assert(t.history == d.history && t.trail_m == d.trail_m && t.follow == d.follow && t.stale == d.stale);
    }
    // Out of range: clamped to the nearest end.
    {
        const LampShadowTune low = Read(std::array<Pair, 16>{{
            {"BB_LAMP_SHADOW_CARRY", "-1"},
            {"BB_LAMP_SHADOW_CLAMP", "-1"},
            {"BB_LAMP_SHADOW_FLOOR", "-1"},
            {"BB_LAMP_SHADOW_WEIGHTS", "-3"},
            {"BB_LAMP_SHADOW_WRAP", "-1"},
            {"BB_LAMP_SHADOW_SOFT", "-0.5"},
            {"BB_LAMP_SHADOW_HISTORY", "-1"},
            {"BB_LAMP_SHADOW_REJECT", "-1"},
            {"BB_LAMP_SHADOW_TRAIL", "-1"},
            {"BB_LAMP_SHADOW_FOLLOW", "-3"},
            {"BB_LAMP_SHADOW_STALE", "-1"},
            {"BB_LAMP_SHADOW_CLEARANCE", "0"},
            {"BB_LAMP_SHADOW_BIAS", "0"},
            {"BB_LAMP_SHADOW_SELF", "-1"},
            {"BB_LAMP_SHADOW_VIEW", "-1"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "0"},
        }});
        assert(!low.weights && low.wrap == 0.0f && low.facing_floor == 0.0f);
        assert(low.radius_m == 0.0f && low.history == 0.0f && low.reject == 0.0f && low.trail_m == 0.0f);
        assert(!low.follow && !low.stale && low.carry_m == 0.0f && low.around == 0.0f);
        assert(low.clearance_m == 0.05f && low.bias_m == 0.005f);
        assert(low.self_m == 0.0f && low.view == 0u && low.view_gain == 0.01f);
        const LampShadowTune high = Read(std::array<Pair, 16>{{
            {"BB_LAMP_SHADOW_CARRY", "9"},
            {"BB_LAMP_SHADOW_CLAMP", "9"},
            {"BB_LAMP_SHADOW_FLOOR", "4"},
            {"BB_LAMP_SHADOW_WEIGHTS", "7"},
            {"BB_LAMP_SHADOW_WRAP", "3"},
            {"BB_LAMP_SHADOW_SOFT", "5"},
            {"BB_LAMP_SHADOW_HISTORY", "2"},
            {"BB_LAMP_SHADOW_REJECT", "3"},
            {"BB_LAMP_SHADOW_TRAIL", "9"},
            {"BB_LAMP_SHADOW_FOLLOW", "7"},
            {"BB_LAMP_SHADOW_STALE", "9"},
            {"BB_LAMP_SHADOW_CLEARANCE", "50"},
            {"BB_LAMP_SHADOW_BIAS", "1"},
            {"BB_LAMP_SHADOW_SELF", "1"},
            {"BB_LAMP_SHADOW_VIEW", "9"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "1000"},
        }});
        assert(high.weights && high.wrap == 1.0f && high.facing_floor == 1.0f);
        assert(high.radius_m == 0.5f && high.history == 0.98f && high.reject == 1.0f && high.trail_m == 2.0f);
        assert(high.follow && high.stale && high.carry_m == 5.0f && high.around == 4.0f);
        assert(high.clearance_m == 2.0f && high.bias_m == 0.2f);
        assert(high.self_m == 0.3f && high.view == 7u && high.view_gain == 16.0f); // (r63: 7 views)
        // A reject that is on is never below the least that leaves a history standing, and
        // the same for the bound by the answers around a pixel.
        const LampShadowTune weak = Read(std::array<Pair, 2>{{{"BB_LAMP_SHADOW_REJECT", "0.1"},
                                                              {"BB_LAMP_SHADOW_CLAMP", "0.1"}}});
        assert(weak.reject == LampRejectLeast && LampRejectLeast * 0.9f > 0.4f);
        assert(weak.around == LampAroundLeast);
    }
    // Not a number (empty, words, a number with a tail, not finite): the default stays. Blanks
    // after a number are allowed.
    {
        const LampShadowTune t = Read(std::array<Pair, 16>{{
            {"BB_LAMP_SHADOW_CARRY", "near"},
            {"BB_LAMP_SHADOW_CLAMP", "1.6x"},
            {"BB_LAMP_SHADOW_FLOOR", "low"},
            {"BB_LAMP_SHADOW_WEIGHTS", "off"},
            {"BB_LAMP_SHADOW_WRAP", ""},
            {"BB_LAMP_SHADOW_SOFT", "0.2m"},
            {"BB_LAMP_SHADOW_HISTORY", "0.5x"},
            {"BB_LAMP_SHADOW_REJECT", "nan"},
            {"BB_LAMP_SHADOW_TRAIL", "far"},
            {"BB_LAMP_SHADOW_FOLLOW", "no"},
            {"BB_LAMP_SHADOW_STALE", "yes"},
            {"BB_LAMP_SHADOW_CLEARANCE", "inf"},
            {"BB_LAMP_SHADOW_BIAS", "0,05"},
            {"BB_LAMP_SHADOW_SELF", "0.12 "},
            {"BB_LAMP_SHADOW_VIEW", "1x"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "-"},
        }});
        const LampShadowTune d;
        assert(t.weights == d.weights && t.wrap == d.wrap && t.radius_m == d.radius_m);
        assert(t.history == d.history && t.reject == d.reject && t.trail_m == d.trail_m);
        assert(t.follow == d.follow && t.stale == d.stale && t.clearance_m == d.clearance_m);
        assert(t.bias_m == d.bias_m && t.view == d.view && t.view_gain == d.view_gain);
        assert(t.facing_floor == d.facing_floor && t.carry_m == d.carry_m && t.around == d.around);
        assert(t.self_m == 0.12f);
    }
    // The frames of history: a frame's share is 1 / (frames + 1).
    {
        LampShadowTune t;
        assert(std::abs(LampHistoryFrames(t) - 9.0f) < 1e-4f);
        t.history = 0.5f;
        assert(Near(LampHistoryFrames(t), 1.0f));
        t.history = 0.98f;
        assert(std::abs(LampHistoryFrames(t) - 49.0f) < 1e-3f);
        t.history = 0.0f;
        assert(LampHistoryFrames(t) == 0.0f); // this frame's ray alone
        t = {};
        t.radius_m = 0.0f;
        assert(LampHistoryFrames(t) == 0.0f); // a point lamp keeps no history
        // The last four words of the history block.
        static_assert(LampHistoryTailWords == 4);
        t = {};
        t.trail_m = 0.25f;
        t.carry_m = 1.5f;
        t.around = 2.0f;
        const auto tail = LampHistoryTail(t);
        assert(std::abs(F(tail[0]) - 9.0f) < 1e-4f && F(tail[1]) == 0.25f && F(tail[2]) == 1.5f && F(tail[3]) == 2.0f);
    }
    // bbport (r44_half-area-lamp): the lamp's radius for one pass of a frame (takes the history,
    // half resolution, experiment 2305843009213693952 set).
    {
        const LampShadowTune d;
        // Full resolution: the pass that takes the history has the area lamp, a pass beside it
        // the point lamp; the experiment bit is about the half resolution only.
        assert(LampPassRadius(d, true, false, false) == 0.1f);
        assert(LampPassRadius(d, false, false, false) == 0.0f);
        assert(LampPassRadius(d, true, false, true) == 0.1f);
        assert(LampPassRadius(d, false, false, true) == 0.0f);
        // Half resolution: the same, and point lamps while the bit is set (the pass of before).
        assert(LampPassRadius(d, true, true, false) == 0.1f);
        assert(LampPassRadius(d, false, true, false) == 0.0f);
        assert(LampPassRadius(d, true, true, true) == 0.0f);
        assert(LampPassRadius(d, false, true, true) == 0.0f);
        // What the pass averages follows from the radius it got: with the bit set no history.
        LampShadowTune pass = d;
        pass.radius_m = LampPassRadius(d, true, true, false);
        assert(std::abs(LampHistoryFrames(pass) - 9.0f) < 1e-4f);
        pass.radius_m = LampPassRadius(d, true, true, true);
        assert(LampHistoryFrames(pass) == 0.0f);
        // BB_LAMP_SHADOW_HISTORY=0: every full-resolution pass shows the bare rays; a pass at
        // half resolution cannot share them among a block's pixels and has point lamps.
        LampShadowTune bare;
        bare.history = 0.0f;
        bare.radius_m = 0.25f;
        assert(LampPassRadius(bare, true, false, false) == 0.25f && LampPassRadius(bare, false, false, false) == 0.25f);
        assert(LampPassRadius(bare, true, true, false) == 0.0f && LampPassRadius(bare, false, true, false) == 0.0f);
        assert(LampPassRadius(bare, true, true, true) == 0.0f);
        // BB_LAMP_SHADOW_SOFT=0: a point lamp in every pass.
        LampShadowTune point;
        point.radius_m = 0.0f;
        for (int k = 0; k < 8; ++k) {
            assert(LampPassRadius(point, (k & 1) != 0, (k & 2) != 0, (k & 4) != 0) == 0.0f);
        }
    }
    // bbport (r48_lamp-softness): graphics_lamp_shadow_softness (0 sharp, 1 soft, 2 softer) as the
    // lamp's radius; BB_LAMP_SHADOW_SOFT, when it gives a number, wins; a point lamp traces every
    // lamp (steps 0), an area lamp keeps the pick.
    {
        const LampShadowTune d = Read(std::array<Pair, 0>{});
        assert(!d.radius_set);
        static_assert(LampSoftnessRadii.size() == 3);
        assert(LampSoftnessRadius(d, 0) == 0.0f && LampSoftnessRadius(d, 1) == 0.1f &&
               LampSoftnessRadius(d, 2) == 0.2f);
        assert(LampSoftnessRadius(d, 1) == d.radius_m); // soft: the radius of before (r42)
        // out of range: the nearest choice, as the menu shows it and the ini saves it (r53)
        assert(LampSoftnessRadius(d, -1) == 0.0f && LampSoftnessRadius(d, 3) == 0.2f &&
               LampSoftnessRadius(d, 7) == 0.2f);
        // Softer is wider than soft, and the lamp's centre stays inside the blind sphere at the
        // end of every ray to its disc (a target lies at most the radius from the centre).
        assert(LampSoftnessRadii[2] > LampSoftnessRadii[1]);
        // bbport (r90_lamp-clearance-default): the pass's clearance keeps it so at every radius
        for (const float r : LampSoftnessRadii) {
            LampShadowTune p = d;
            p.radius_m = r;
            assert(LampPassClearance(p) > r && LampPassClearance(p) >= d.clearance_m);
        }
        {
            LampShadowTune p = d;
            p.radius_m = 0.1f;
            assert(LampPassClearance(p) == 0.18f);
            p.radius_m = 0.2f;
            assert(std::abs(LampPassClearance(p) - 0.25f) < 1e-6f);
        }
        for (int k = 0; k < 3; ++k) {
            LampShadowTune pass = d;
            pass.radius_m = LampSoftnessRadius(d, k);
            // Sharp keeps no history; soft and softer average the same 9 frames.
            const float frames = LampHistoryFrames(pass);
            assert(k == 0 ? frames == 0.0f : std::abs(frames - 9.0f) < 1e-4f);
            // The pass that takes the history, at full and at half resolution: the setting's
            // radius; a pass beside it: the point lamp, as before.
            assert(LampPassRadius(pass, true, false, false) == pass.radius_m);
            assert(LampPassRadius(pass, true, true, false) == pass.radius_m);
            assert(LampPassRadius(pass, false, false, false) == 0.0f);
            assert(LampPassRadius(pass, true, true, true) == 0.0f); // experiment 2305843009213693952
            // Sharp traces every lamp; with the pick (1) soft and softer keep it, and so does the
            // pass of before r41 (no repair); LANTERN_RT_LAMPS_EXACT=1 (0) traces every lamp.
            assert(LampPassSteps(pass, true, 1u) == (k == 0 ? 0u : 1u));
            assert(LampPassSteps(pass, false, 1u) == 1u);
            assert(LampPassSteps(pass, true, 0u) == 0u && LampPassSteps(pass, false, 0u) == 0u);
        }
        // The variable, when it gives a number, wins over every value of the setting (0 too).
        for (const char* value : {"0", "0.35", "0.05 "}) {
            const LampShadowTune t = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SOFT", value}}});
            assert(t.radius_set);
            for (int k = -1; k < 4; ++k) {
                assert(LampSoftnessRadius(t, k) == t.radius_m);
            }
        }
        const LampShadowTune point = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SOFT", "0"}}});
        assert(point.radius_m == 0.0f && LampSoftnessRadius(point, 2) == 0.0f && LampPassSteps(point, true, 1u) == 0u);
        const LampShadowTune high = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SOFT", "5"}}});
        assert(high.radius_set && LampSoftnessRadius(high, 0) == 0.5f); // clamped, and it still wins
        // Not set, empty or not a number: the setting decides.
        for (const char* value : {"", "0.2m", "soft", "nan"}) {
            const LampShadowTune t = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SOFT", value}}});
            assert(!t.radius_set && t.radius_m == d.radius_m);
            assert(LampSoftnessRadius(t, 0) == 0.0f && LampSoftnessRadius(t, 2) == 0.2f);
        }
    }
    // A cut: the way back to the camera of the frame before is more than 2 m or about 20 degrees.
    {
        std::array<float, 12> back{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        assert(!LampCameraCut(back.data()));
        back[3] = 0.5f;
        back[11] = -1.5f; // a fast camera: 1.6 m in a frame
        assert(!LampCameraCut(back.data()));
        back[7] = 1.3f; // 2.05 m
        assert(LampCameraCut(back.data()));
        const auto turned = [](float degrees) {
            const float a = degrees * 0.01745329f, c = std::cos(a), s = std::sin(a);
            return std::array<float, 12>{c, 0, s, 0.1f, 0, 1, 0, 0, -s, 0, c, 0};
        };
        assert(!LampCameraCut(turned(5.0f).data()) && !LampCameraCut(turned(-18.0f).data()));
        assert(LampCameraCut(turned(25.0f).data()) && LampCameraCut(turned(180.0f).data()));
        back = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        back[5] = std::nanf("");
        assert(LampCameraCut(back.data()));
    }
    // The words: flags, nine floats, two axes.
    {
        static_assert(LampTuneWordCount == 16);
        const LampShadowTune d;
        const auto words = LampTuneWords(d, false, 0.05f);
        assert(words.size() == LampTuneWordCount);
        // new weights, view 0, the soft follow (r52), the window (bbport r57_lamp-window; r60: of
        // the default)
        assert(words[0] == (1u | LampTuneFollowSoft | DefaultWindowBits));
        assert(F(words[1]) == 0.18f && F(words[2]) == 0.1f && words[3] == 0u); // bbport (r90)
        assert(F(words[4]) == 0.06f && F(words[5]) == 0.15f && F(words[7]) == 0.5f);
        // The frame counter goes into word 3 as it is, and changes nothing else.
        const auto later = LampTuneWords(d, false, 0.05f, nullptr, 0xC0000077u);
        assert(later[3] == 0xC0000077u);
        for (std::size_t k = 0; k < LampTuneWordCount; ++k) {
            assert(k == 3 || later[k] == words[k]);
        }
        assert(Near(F(words[6]), 0.0025f));
        assert(F(words[8]) == 0.05f && F(words[9]) == 0.5f);
        // No view matrix: the view's own x and y axes.
        assert(F(words[10]) == 1.0f && F(words[11]) == 0.0f && F(words[12]) == 0.0f);
        assert(F(words[13]) == 0.0f && F(words[14]) == 1.0f && F(words[15]) == 0.0f);
        // A view matrix (rows of four; here the camera looks down the world's -y, turned by
        // 30 degrees about it, and stands away from the origin): the world's +x and +y axes as
        // the view sees them are its first two columns, whatever the translation.
        const float c = std::cos(0.5235988f), s = std::sin(0.5235988f);
        const std::array<float, 12> view{c,    0.0f, -s,   5.0f,  s,    0.0f,
                                         c,    -7.0f, 0.0f, -1.0f, 0.0f, 9.0f};
        const auto turned = LampTuneWords(d, false, 0.05f, view.data());
        assert(Near(F(turned[10]), c) && Near(F(turned[11]), s) && Near(F(turned[12]), 0.0f));
        assert(Near(F(turned[13]), 0.0f) && Near(F(turned[14]), 0.0f));
        assert(Near(F(turned[15]), -1.0f));
        for (int k = 0; k < 10; ++k) {
            assert(turned[k] == words[k]); // the axes change nothing else
        }
        // A matrix that is no rotation (scaled, sheared, not finite, empty): the view's own axes.
        std::array<float, 12> bad = view;
        bad[0] = 3.0f;
        assert(LampTuneAxes(bad.data()) == LampTuneAxes(nullptr));
        bad = view;
        bad[1] = 0.5f;
        assert(LampTuneAxes(bad.data()) == LampTuneAxes(nullptr));
        bad = view;
        bad[4] = std::nanf("");
        assert(LampTuneAxes(bad.data()) == LampTuneAxes(nullptr));
        bad = {};
        assert(LampTuneAxes(bad.data()) == LampTuneAxes(nullptr));
        LampShadowTune t;
        t.weights = false;
        t.view = 4;
        t.reject = 0.75f;
        const auto other = LampTuneWords(t, true, 0.1f);
        assert(other[0] == (2u | 4u << 8 | LampTuneFollowSoft | DefaultWindowBits)); // (r57: the window)
        assert(F(other[9]) == 0.75f);
        assert(Near(F(other[6]), 0.01f));
        // A core that is not a positive number counts as 0, as in LocalFalloff::Patch.
        assert(F(LampTuneWords(d, true, -1.0f)[6]) == 0.0f);
        assert(F(LampTuneWords(d, true, std::nanf(""))[6]) == 0.0f);
        // The view cannot leave its field.
        t.view = 100;
        assert(LampTuneWords(t, false, 0.0f)[0] == (7u << 8 | LampTuneFollowSoft | DefaultWindowBits)); // (r63)
    }
    // bbport (r52_follow-soft): BB_LAMP_SHADOW_FOLLOW_SOFT is on unless the variable says 0 (out
    // of range is clamped, text that is not a whole number leaves the default). In the words it is
    // word 0's bit 20 and nothing else; bits 12-17 stay clear. (That the shader reads the same
    // bit is checked by rt-shadow-test --lamps: the follow images hold a state only with it.)
    {
        const LampShadowTune d = Read(std::array<Pair, 0>{});
        assert(d.follow_soft);
        const LampShadowTune off = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_FOLLOW_SOFT", "0"}}});
        assert(!off.follow_soft);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_FOLLOW_SOFT", "1"}}}).follow_soft);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_FOLLOW_SOFT", "7"}}}).follow_soft);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_FOLLOW_SOFT", "-2"}}}).follow_soft);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_FOLLOW_SOFT", "no"}}}).follow_soft);
        // The other knobs are read as without it.
        LampShadowTune again = off;
        again.follow_soft = d.follow_soft;
        assert(LampTuneWords(again, false, 0.05f) == LampTuneWords(d, false, 0.05f));
        assert(off.follow == d.follow && off.radius_m == d.radius_m && off.view == d.view);
        const float c = std::cos(0.3f), s = std::sin(0.3f);
        const std::array<float, 12> view{c, 0.0f, -s, 1.0f, 0.0f, 1.0f, 0.0f, 2.0f, s, 0.0f, c, 3.0f};
        for (const float* v : {static_cast<const float*>(nullptr), view.data()}) {
            for (const bool inverse : {false, true}) {
                const auto on_words = LampTuneWords(d, inverse, 0.05f, v, 41u);
                const auto off_words = LampTuneWords(off, inverse, 0.05f, v, 41u);
                assert((on_words[0] ^ off_words[0]) == LampTuneFollowSoft);
                assert((on_words[0] & LampTuneFollowSoft) != 0 && (off_words[0] & LampTuneFollowSoft) == 0);
                assert((on_words[0] & (0x3Fu << 12)) == 0 && (off_words[0] & (0x3Fu << 12)) == 0);
                for (std::size_t k = 1; k < LampTuneWordCount; ++k) {
                    assert(on_words[k] == off_words[k]);
                }
            }
        }
        // Nor is it in the history block's words.
        assert(LampHistoryTail(d) == LampHistoryTail(off));
    }
    // bbport (r57_lamp-window): BB_LAMP_SHADOW_WINDOW is on (the window, as before r57) unless the
    // variable says 0 (out of range is clamped, text that is not a whole number leaves the
    // default). In the words it is word 0's bit 21 and nothing else: bits 12-17 stay clear and bit
    // 20 (the soft follow) keeps its own value. (That the shader reads the same bit is checked by
    // rt-shadow-test --lamps: its r57 lattice block fails when the pictures with 0 and with 1 are
    // the same.)
    {
        static_assert(LampTuneWindow == 1u << 21 && (LampTuneWindow & LampTuneFollowSoft) == 0);
        static_assert((LampTuneWindow & (0x3Fu << 12)) == 0 && (LampTuneWindow & (7u << LampTuneViewShift)) == 0);
        const LampShadowTune d = Read(std::array<Pair, 0>{});
        static_assert(LampWindowDefault == 1 || LampWindowDefault == 2); // (r60: either has the window)
        assert(d.window);
        assert((LampTuneWords(d, false, 0.05f)[0] & LampTuneWindow) == LampTuneWindow);
        const LampShadowTune off = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "0"}}});
        assert(!off.window);
        assert((LampTuneWords(off, false, 0.05f)[0] & LampTuneWindow) == 0);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "1"}}}).window);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "5"}}}).window);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "-1"}}}).window);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "no"}}}).window);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", ""}}}).window);
        // Round trip: the bit the words carry gives the knob back, for both values of the soft
        // follow, and the other knobs are read as without it.
        LampShadowTune again = off;
        again.window = d.window;
        again.window_centred = d.window_centred; // (r60)
        assert(LampTuneWords(again, false, 0.05f) == LampTuneWords(d, false, 0.05f));
        assert(off.follow_soft == d.follow_soft && off.around == d.around && off.view == d.view);
        const float c = std::cos(0.3f), s = std::sin(0.3f);
        const std::array<float, 12> view{c, 0.0f, -s, 1.0f, 0.0f, 1.0f, 0.0f, 2.0f, s, 0.0f, c, 3.0f};
        for (const bool soft : {false, true}) {
            for (const bool window : {false, true}) {
                LampShadowTune t = d;
                t.follow_soft = soft;
                t.window = window;
                t.window_centred = false; // (r60: bit 22 below)
                t.view = 3;
                const auto words = LampTuneWords(t, true, 0.05f, view.data(), 77u);
                assert(((words[0] & LampTuneWindow) != 0) == window);
                assert(((words[0] & LampTuneFollowSoft) != 0) == soft);
                assert((words[0] & (0x3Fu << 12)) == 0);
                assert(((words[0] >> LampTuneViewShift) & 7u) == 3u);
                LampShadowTune other = t;
                other.window = !window;
                const auto flipped = LampTuneWords(other, true, 0.05f, view.data(), 77u);
                assert((words[0] ^ flipped[0]) == LampTuneWindow);
                for (std::size_t k = 1; k < LampTuneWordCount; ++k) {
                    assert(words[k] == flipped[k]);
                }
            }
        }
        // Nor is it in the history block's words.
        assert(LampHistoryTail(d) == LampHistoryTail(off));
    }
    // bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW=2 is the window (bit 21) centred
    // (bit 22); 3 or more is 2, below 0 is 0, text that is no whole number leaves the default
    // (LampWindowDefault). Bit 22 is set only with bit 21, and nothing else of the words moves with
    // it; 0 and 1 give the words they gave before r60. (That the shader reads it is checked by
    // rt-shadow-test --lamps: its lattice block fails when the pictures with 1 and 2 are the same.)
    {
        static_assert(LampTuneCentred == 1u << 22);
        static_assert((LampTuneCentred & (LampTuneWindow | LampTuneFollowSoft | (0x3Fu << 12) |
                                          (7u << LampTuneViewShift) | LampTuneNewWeights |
                                          LampTuneInverseSquare)) == 0);
        const LampShadowTune d = Read(std::array<Pair, 0>{});
        assert(LampWindowValue(d) == LampWindowDefault);
        assert(d.window_centred == (LampWindowDefault == 2));
        const LampShadowTune two = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "2"}}});
        assert(two.window && two.window_centred && LampWindowValue(two) == 2u);
        const LampShadowTune one = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "1"}}});
        assert(one.window && !one.window_centred && LampWindowValue(one) == 1u);
        const LampShadowTune zero = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "0"}}});
        assert(!zero.window && !zero.window_centred && LampWindowValue(zero) == 0u);
        assert(LampWindowValue(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "5"}}})) == 2u);
        assert(LampWindowValue(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "-1"}}})) == 0u);
        assert(LampWindowValue(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "two"}}})) == LampWindowDefault);
        assert(LampWindowValue(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "2.5"}}})) == LampWindowDefault);
        assert(LampWindowValue(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", " 2 "}}})) == 2u);
        // The words of 0 and 1 are those of before r60 (bit 21 as r57 had it, no bit 22); 2 adds
        // bit 22 alone.
        const float c = std::cos(0.3f), s = std::sin(0.3f);
        const std::array<float, 12> view{c, 0.0f, -s, 1.0f, 0.0f, 1.0f, 0.0f, 2.0f, s, 0.0f, c, 3.0f};
        for (const bool soft : {false, true}) {
            for (const std::uint32_t v : {0u, 4u, 6u}) {
                LampShadowTune t0 = zero, t1 = one, t2 = two;
                for (LampShadowTune* t : {&t0, &t1, &t2}) {
                    t->follow_soft = soft;
                    t->view = v;
                }
                const auto w0 = LampTuneWords(t0, true, 0.05f, view.data(), 9u);
                const auto w1 = LampTuneWords(t1, true, 0.05f, view.data(), 9u);
                const auto w2 = LampTuneWords(t2, true, 0.05f, view.data(), 9u);
                assert((w0[0] & (LampTuneWindow | LampTuneCentred)) == 0);
                assert((w1[0] & (LampTuneWindow | LampTuneCentred)) == LampTuneWindow);
                assert((w2[0] ^ w1[0]) == LampTuneCentred && (w1[0] ^ w0[0]) == LampTuneWindow);
                assert(((w2[0] & LampTuneFollowSoft) != 0) == soft && ((w2[0] >> LampTuneViewShift) & 7u) == v);
                for (std::size_t k = 1; k < LampTuneWordCount; ++k) {
                    assert(w0[k] == w1[k] && w1[k] == w2[k]);
                }
                // r57's word 0, as LampTuneWords made it before r60
                const std::uint32_t r57 = (t1.weights ? LampTuneNewWeights : 0u) | LampTuneInverseSquare |
                                          v << LampTuneViewShift | (soft ? LampTuneFollowSoft : 0u);
                assert(w0[0] == r57 && w1[0] == (r57 | LampTuneWindow));
            }
        }
        // Bit 22 without the window is never written (2 is the window centred, not a window of its own).
        LampShadowTune odd = zero;
        odd.window_centred = true;
        assert((LampTuneWords(odd, false, 0.05f)[0] & (LampTuneWindow | LampTuneCentred)) == 0);
        assert(LampWindowValue(odd) == 0u);
        // Round trip: the value the bits carry reads back as the same knob.
        for (const LampShadowTune& t : {zero, one, two}) {
            const std::uint32_t w = LampTuneWords(t, false, 0.05f)[0];
            const std::uint32_t back = (w & LampTuneWindow) ? ((w & LampTuneCentred) ? 2u : 1u) : 0u;
            assert(back == LampWindowValue(t));
            char text[4] = {char('0' + back), 0, 0, 0};
            const std::array<Pair, 1> env{{{"BB_LAMP_SHADOW_WINDOW", text}}};
            const LampShadowTune again = Read(env);
            assert(LampWindowValue(again) == back && LampTuneWords(again, false, 0.05f) == LampTuneWords(t, false, 0.05f));
        }
        // Nor is it in the history block's words.
        assert(LampHistoryTail(two) == LampHistoryTail(one) && LampHistoryTail(one) == LampHistoryTail(zero));
    }
    // bbport (r60_lamp-centred-window): the CPU model of the 5x5 statistic (only the tile's index
    // arithmetic: see Field). Fields of answers with holes (no answer), exact 0s and 1s (so a
    // count of "above 0" in place of "0 or more" shows), rects that do not cover the screen, end on
    // even and odd full pixels or reach past the screen (so a missed clip shows); the workgroups'
    // grid shifted by 0 to 7 pass pixels (full pixels 0 to 7; at the half-resolution build's first
    // pass, two apart, full pixels 0 to 14). Value 2 (the 12x12 tile, as point_shadow_ray.comp
    // loadTile and its centred loop index it) gives every pixel the statistic of its own 5x5
    // neighbourhood (Direct), to the bit, at every shift; value 1 (the window confined to the
    // workgroup) does not, and changes with the shift: the squares.
    {
        struct Case {
            std::array<int, 2> size;
            std::array<int, 4> rect;
        };
        constexpr std::array<Case, 4> cases{{{{122, 94}, {6, 10, 115, 88}},
                                             {{121, 93}, {3, 5, 140, 100}},
                                             {{64, 48}, {0, 0, 64, 48}},
                                             {{100, 70}, {17, 9, 58, 66}}}};
        for (const int apart : {1, 2}) {
            for (const Case& c : cases) {
                Field f;
                f.apart = apart;
                f.size = c.size;
                f.rect = c.rect;
                f.pw = (c.size[0] + apart - 1) / apart;
                f.ph = (c.size[1] + apart - 1) / apart;
                f.w = f.pw + 10;
                f.h = f.ph + 10;
                f.answer.resize(std::size_t(f.w * f.h));
                std::uint32_t seed = 12345u + std::uint32_t(apart) + std::uint32_t(c.size[0]);
                std::size_t zeros = 0;
                for (float& a : f.answer) {
                    seed = seed * 747796405u + 2891336453u;
                    const std::uint32_t r = (seed >> 9) & 0x3FFFu;
                    const std::uint32_t kind = r % 5u; // none, 0, 1, or (twice as often) a fraction
                    a = kind == 0u ? -1.0f : kind == 1u ? 0.0f : kind == 2u ? 1.0f : float(r & 0x3FFu) / 1023.0f;
                    zeros += a == 0.0f ? 1 : 0;
                }
                assert(zeros > 100);
                std::vector<Stat> direct(std::size_t(f.pw * f.ph));
                for (int y = 0; y < f.ph; ++y) {
                    for (int x = 0; x < f.pw; ++x) {
                        direct[std::size_t(y * f.pw + x)] = Direct(f, x, y);
                    }
                }
                const auto first1 = Statistic(f, 0, false);
                bool confined_differs = false, confined_moves = false;
                for (int shift = 0; shift < 8; ++shift) {
                    const auto centred = Statistic(f, shift, true);
                    const auto confined = Statistic(f, shift, false);
                    for (std::size_t i = 0; i < direct.size(); ++i) {
                        assert(centred[i] == direct[i]); // bit for bit
                        assert(std::memcmp(&centred[i], &direct[i], sizeof(Stat)) == 0);
                        confined_differs = confined_differs || !(confined[i] == direct[i]);
                        confined_moves = confined_moves || !(confined[i] == first1[i]);
                    }
                }
                assert(confined_differs && confined_moves);
                // A pixel's own answer is always in its window: count >= 1 where it has one and
                // lies in the rect.
                for (int y = 0; y < f.ph; ++y) {
                    for (int x = 0; x < f.pw; ++x) {
                        const int fx = apart * x, fy = apart * y;
                        const bool in = fx >= c.rect[0] && fy >= c.rect[1] && fx < c.rect[2] && fy < c.rect[3];
                        assert(!in || !(f.answer[std::size_t(y * f.w + x)] >= 0.0f) ||
                               direct[std::size_t(y * f.pw + x)].count >= 1.0f);
                    }
                }
            }
        }
    }
    // bbport (r60_lamp-centred-window): the cast code through the answers image (storeAnswer, read
    // back by the resolve): the classes the blend takes from it are those of the ray it stands for.
    // Written from the shader's rules in plain words: blocker "near" (-2 under a moving lamp), "far"
    // (0 or more: the swing), else none; the follow evidence e +1 near, -1 further off, 0 free or no
    // ray to the strongest lamp (a block's answer taken, -5, has none: it copies its block's state).
    {
        struct Want {
            float code;
            bool near, far;
            float e;
        };
        constexpr std::array<Want, 5> fixed{{{-1.0f, false, false, 0.0f},
                                             {-2.0f, true, false, 1.0f},
                                             {-3.0f, false, false, 1.0f},
                                             {-4.0f, false, false, -1.0f},
                                             {-5.0f, false, false, 0.0f}}};
        // What the resolve reads of a code (point_shadow_ray.comp: the centred loop and castEvidence)
        const auto near_of = [](float c) { return c < -1.5f && c > -2.5f; };
        const auto far_of = [](float c) { return c >= 0.0f; };
        const auto evidence = [](float c) {
            if (c >= 0.0f || (c < -3.5f && c > -4.5f)) {
                return -1.0f;
            }
            return c < -1.5f && c > -3.5f ? 1.0f : 0.0f;
        };
        const std::array<std::uint32_t, 4> records{0u, 16u, 48u * 16u, (1u << 20) - 16u};
        for (const std::uint32_t record : records) {
            for (const Want& w : fixed) {
                const std::uint32_t y = PackCast(w.code, record);
                const float c = CastOf(y);
                assert(c == w.code && RecordOf(y) == record);
                assert(near_of(c) == w.near && far_of(c) == w.far && evidence(c) == w.e);
            }
            // The far blocker's swing, 0 to 64: far, e -1, back within half a unit in the last place
            // of a half float (relative 2^-11).
            for (int k = 0; k <= 6400; ++k) {
                const float swing = k == 6400 ? 64.0f : float(k) * 0.01f + float(k % 7) * 1e-4f;
                const std::uint32_t y = PackCast(swing, record);
                const float c = CastOf(y);
                assert(far_of(c) && !near_of(c) && evidence(c) == -1.0f && RecordOf(y) == record);
                assert(std::abs(c - swing) <= std::max(swing * 0x1.0p-11f, 0x1.0p-25f));
            }
            assert(CastOf(PackCast(-0.0f, record)) == 0.0f && far_of(CastOf(PackCast(-0.0f, record))));
        }
        // A record off the 16-word steps, or past 2^20, is stored as none (0).
        assert(RecordOf(PackCast(-1.0f, 24u)) == 0u && RecordOf(PackCast(-1.0f, 1u << 20)) == 0u);
        // The half float of a whole number is exact.
        for (int k = -5; k <= 64; ++k) {
            assert(FromHalf(ToHalf(float(k))) == float(k));
        }
    }
    // The weight. Halfway to the radius the game's curve (1 - d/r)^2 gives a quarter, the old
    // one (1 - d^2/r^2)^2 gave 0.5625: a distant lamp counted 2.25 times too much.
    {
        const LampShadowTune d;
        assert(Near(LampWeight(d, false, 0.05f, 0.25f, 1.0f, true, 1.0f), 0.25f));
        assert(Near(LampWeight(d, false, 0.05f, 0.25f, 1.0f, true, 0.5f), 0.125f)); // luma
        LampShadowTune old;
        old.weights = false;
        assert(Near(LampWeight(old, false, 0.05f, 0.25f, 1.0f, true, 1.0f), 0.5625f));
        // The old weight knows no facing and no curve switch.
        assert(LampWeight(old, true, 0.05f, 0.25f, -1.0f, true, 1.0f) ==
               LampWeight(old, false, 0.05f, 0.25f, 1.0f, true, 1.0f));
        // Behind the surface, floor 0: nothing with wrap 0, nothing past the wrap otherwise.
        // The whole weight with wrap 1 (no N.L) or where the pass found no normal.
        LampShadowTune hard;
        hard.wrap = 0.0f;
        hard.facing_floor = 0.0f;
        assert(LampWeight(hard, false, 0.05f, 0.25f, -0.2f, true, 1.0f) == 0.0f);
        assert(LampWeight(hard, false, 0.05f, 0.25f, 0.0f, true, 1.0f) == 0.0f);
        assert(Near(LampWeight(hard, false, 0.05f, 0.25f, 0.5f, true, 1.0f), 0.125f));
        LampShadowTune gate;
        gate.facing_floor = 0.0f;
        assert(LampWeight(gate, false, 0.05f, 0.25f, -0.15f, true, 1.0f) == 0.0f);
        assert(LampWeight(gate, false, 0.05f, 0.25f, -0.1f, true, 1.0f) > 0.0f);
        // The default floor: a lamp behind the surface keeps a twentieth of its weight (so a
        // pixel whose only lamp it is still gets its ray), and still ranks below one in front.
        assert(Near(LampWeight(d, false, 0.05f, 0.25f, -1.0f, true, 1.0f), 0.0125f));
        assert(Near(LampWeight(d, false, 0.05f, 0.25f, -0.15f, true, 1.0f), 0.0125f));
        assert(LampWeight(d, false, 0.05f, 0.25f, -1.0f, true, 1.0f) > 1e-5f);
        assert(LampWeight(d, false, 0.05f, 0.25f, 0.3f, true, 1.0f) >
               LampWeight(d, false, 0.05f, 0.25f, -1.0f, true, 1.0f) * 5.0f);
        LampShadowTune none;
        none.wrap = 1.0f;
        assert(Near(LampWeight(none, false, 0.05f, 0.25f, -1.0f, true, 1.0f), 0.25f));
        assert(Near(LampWeight(hard, false, 0.05f, 0.25f, -1.0f, false, 1.0f), 0.25f));
        // The inverse-square curve: 1 / (x^2 + core^2) - 1 / (1 + core^2), 0 at the radius.
        const float core2 = 0.05f * 0.05f;
        assert(Near(LampWeight(d, true, 0.05f, 0.25f, 1.0f, true, 1.0f),
                    1.0f / (0.25f + core2) - 1.0f / (1.0f + core2)));
        assert(Near(LampWeight(d, true, 0.05f, 1.0f, 1.0f, true, 1.0f), 0.0f));
        assert(std::isfinite(LampWeight(d, true, 0.0f, 0.0f, 1.0f, true, 1.0f)));
        // Both curves end at the radius and fall with distance.
        assert(Near(LampWeight(d, false, 0.05f, 1.0f, 1.0f, true, 1.0f), 0.0f));
        assert(LampWeight(d, false, 0.05f, 0.04f, 1.0f, true, 1.0f) >
               LampWeight(d, false, 0.05f, 0.64f, 1.0f, true, 1.0f));
    }
    // bbport (r42_lamp-soft): the lamps of a pass, told apart and followed.
    {
        constexpr std::array<float, 12> Same{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        // The camera of the second frame stands 2 m along x: world = view + (2, 0, 0).
        constexpr std::array<float, 12> Moved{1, 0, 0, 2, 0, 1, 0, 0, 0, 0, 1, 0};
        LampTrack track;
        // Frame 1: lamp A (listed for three tiles), lamp B, and a record with no reach.
        const auto a1 = Record(1.0f, 2.0f, 3.0f, 6.0f, 0.5f), b1 = Record(5.0f, 1.0f, 0.0f, 4.0f, 2.0f);
        track.Begin(Same.data());
        assert(track.Add(a1.data()) == 0 && track.Add(b1.data()) == 1 && track.Add(a1.data()) == 0);
        assert(track.Add(a1.data()) == 0 && track.Count() == 2);
        std::array<std::uint32_t, 16> none{};
        assert(track.Add(none.data()) == -1 && track.Count() == 2);
        assert(track.Lamp(0).records == 3 && track.Lamp(1).records == 1);
        assert(Near(track.Lamp(0).radius, 6.0f) && Near(track.Lamp(0).luma, 0.5f));
        assert(Near(track.Lamp(1).away, std::sqrt(26.0f)));
        track.Follow(); // no frame before: nothing is followed, nothing shifts
        assert(!track.Lamp(0).followed && track.Shift(0, Same.data()) == (std::array<float, 3>{}));
        // The brightest first.
        assert(track.Strongest() == (std::array<int, 4>{1, 0, -1, -1}));
        track.End(true);
        // Frame 2: A went (0.1, 0, 0.05) in the world, B stands; the camera moved, so both
        // records hold other numbers. C is new; D stands where B does with twice its reach.
        const auto a2 = Record(1.1f - 2.0f, 2.0f, 3.05f, 6.0f, 0.5f), b2 = Record(3.0f, 1.0f, 0.0f, 4.0f, 2.0f);
        const auto c2 = Record(9.0f, 0.0f, 0.0f, 4.0f), d2 = Record(3.0f, 1.0f, 0.01f, 8.0f);
        track.Begin(Moved.data());
        assert(track.Add(a2.data()) == 0 && track.Add(b2.data()) == 1 && track.Add(c2.data()) == 2);
        assert(track.Add(d2.data()) == 3);
        track.Follow();
        assert(track.Lamp(0).followed && track.Lamp(1).followed);
        assert(!track.Lamp(2).followed && !track.Lamp(3).followed);
        assert(Near(track.Lamp(0).world[0], 1.1f) && Near(track.Lamp(0).moved[0], 0.1f));
        assert(Near(track.Lamp(0).moved[1], 0.0f) && Near(track.Lamp(0).moved[2], 0.05f));
        assert(track.Lamp(1).moved == (std::array<float, 3>{})); // it stands
        // The shift is the lamp's motion turned into the view of the frame before (here a
        // quarter turn about y), whatever that camera's place.
        constexpr std::array<float, 12> Turned{0, 0, -1, 7, 0, 1, 0, 8, 1, 0, 0, 9};
        const auto shift = track.Shift(0, Turned.data());
        assert(Near(shift[0], -0.05f) && Near(shift[1], 0.0f) && Near(shift[2], 0.1f));
        assert(track.Shift(1, Turned.data()) == (std::array<float, 3>{}));
        // The step is the length of the motion, with or without a view to turn it into. A
        // lamp that was looked for in the frame before and not found has no history: Lost.
        assert(Near(track.Step(0), std::sqrt(0.1f * 0.1f + 0.05f * 0.05f)));
        assert(track.Step(1) == 0.0f && track.Step(2) == LampTrack::Lost && track.Step(-1) == 0.0f);
        assert(track.Step(3) == LampTrack::Lost);
        // What a followed lamp did since the steps were last cleared.
        assert(track.Lamp(0).steps == 1 && Near(track.Lamp(0).step_most, track.Step(0)));
        assert(track.Lamp(1).steps == 1 && track.Lamp(1).step_sum == 0.0f && track.Lamp(2).steps == 0);
        assert(track.Shift(-1, Turned.data()) == (std::array<float, 3>{}));
        assert(track.Shift(0, nullptr) == (std::array<float, 3>{}));
        track.End(true);
        // Frame 3: two lamps near where A was: the nearer one is A, the other is new. A lamp
        // further than Reach from every lamp of the frame before is new.
        const auto a3 = Record(1.2f - 2.0f, 2.0f, 3.05f, 6.0f), e3 = Record(1.4f - 2.0f, 2.0f, 3.05f, 6.0f);
        const auto b3 = Record(3.0f + LampTrack::Reach + 0.1f, 1.0f, 0.0f, 4.0f);
        track.Begin(Moved.data());
        assert(track.Add(e3.data()) == 0 && track.Add(a3.data()) == 1 && track.Add(b3.data()) == 2);
        track.Follow();
        assert(!track.Lamp(0).followed && track.Lamp(1).followed && !track.Lamp(2).followed);
        assert(Near(track.Lamp(1).moved[0], 0.1f));
        assert(track.Lamp(1).steps == 2 && Near(track.Lamp(1).step_sum, track.Lamp(1).step_most + 0.1f));
        track.ClearSteps();
        assert(track.Lamp(1).steps == 0 && track.Lamp(1).step_sum == 0.0f && track.Lamp(1).step_most == 0.0f);
        track.End(false); // the pass kept no history: the next frame follows nothing
        track.Begin(Moved.data());
        assert(track.Add(a3.data()) == 0);
        track.Follow();
        assert(!track.Lamp(0).followed && track.Step(0) == 0.0f); // not looked for: not Lost
        track.End(true);
        // No camera: the lamps are listed in view space and not followed, on this frame or the next.
        track.Begin(nullptr);
        assert(track.Add(a3.data()) == 0);
        track.Follow();
        assert(!track.Lamp(0).followed && Near(track.Lamp(0).world[0], 1.2f - 2.0f));
        track.End(true);
        track.Begin(Same.data());
        assert(track.Add(a3.data()) == 0);
        track.Follow();
        assert(!track.Lamp(0).followed);
        track.End(true);
        // More lamps than it tells apart: the first Most keep their numbers, the rest have none.
        track.Begin(Same.data());
        for (std::uint32_t k = 0; k < LampTrack::Most + 6; ++k) {
            const auto r = Record(float(k), 0.0f, 20.0f, 3.0f, k == 5 ? 9.0f : 1.0f);
            assert(track.Add(r.data()) == (k < LampTrack::Most ? int(k) : -1));
        }
        const auto again = Record(7.0f, 0.0f, 20.0f, 3.0f);
        assert(track.Add(again.data()) == 7 && track.Count() == LampTrack::Most);
        // Strongest: none of them is within Near of the camera.
        assert(track.Strongest() == (std::array<int, 4>{-1, -1, -1, -1}));
        track.End(false);
        // Strongest: by luminance, the nearer first among equals, four at most.
        track.Begin(Same.data());
        const std::array<std::array<std::uint32_t, 16>, 6> some{
            Record(0, 0, 5, 3, 1.0f), Record(0, 0, 2, 3, 1.0f), Record(0, 0, 9, 3, 4.0f),
            Record(0, 0, 14, 3, 0.2f), Record(0, 0, 16, 3, 50.0f), Record(1, 0, 3, 3, 0.5f)};
        for (const auto& r : some) {
            track.Add(r.data());
        }
        assert(track.Strongest() == (std::array<int, 4>{2, 1, 0, 5}));
        track.End(false);
        // Two lights at one place with different reach or colour are two lamps (a torch made
        // of two); the same seven words are one.
        track.Begin(Same.data());
        const auto wide = Record(1, 2, 3, 6.0f), small = Record(1, 2, 3, 1.5f), red = Record(1, 2, 3, 6.0f, 0.3f);
        assert(track.Add(wide.data()) == 0 && track.Add(small.data()) == 1 && track.Add(red.data()) == 2);
        assert(track.Add(wide.data()) == 0 && track.Add(small.data()) == 1 && track.Count() == 3);
        assert(Near(LampTrack::Away(wide.data()), std::sqrt(14.0f)));
        track.End(false);
    }
    // bbport (r91_lamp-radius-per-lamp): BB_LAMP_SHADOW_RADIUS_PER_LAMP, each lamp's disc from its
    // reach (LampDiscRadius), word 10 (LampDiscWord), the disc a followed lamp keeps (LampDiscKeep,
    // LampTrack::Disc), and its bit, which LampTuneWords never sets (Flush does).
    {
        const LampShadowTune d;
        assert(d.disc_each == 0.0f);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_RADIUS_PER_LAMP", "0.02"}}}).disc_each == 0.02f);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_RADIUS_PER_LAMP", "-1"}}}).disc_each == 0.0f);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_RADIUS_PER_LAMP", "5"}}}).disc_each == 1.0f);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_RADIUS_PER_LAMP", "wide"}}}).disc_each == 0.0f);
        LampShadowTune on = d;
        on.disc_each = 0.02f;
        // The knob is no tuning word: the words, word 0 included, are those of the knob off.
        assert(LampTuneWords(on, false, 0.05f) == LampTuneWords(d, false, 0.05f));
        assert((LampTuneWords(on, true, 0.05f)[0] & LampTuneDiscEach) == 0u);
        const auto inv = [](float reach) { return 1.0f / (reach * reach); };
        // Soft (0.1 m): clamp(k x reach, 0.03 m, 0.3 m).
        assert(std::abs(LampDiscRadius(on, inv(5.0f)) - 0.1f) < 1e-6f);
        assert(std::abs(LampDiscRadius(on, inv(12.0f)) - 0.24f) < 1e-6f);
        assert(LampDiscRadius(on, inv(40.0f)) == LampDiscMost && LampDiscRadius(on, inv(0.5f)) == LampDiscLeast);
        assert(LampDiscRadius(on, 0.0f) == LampDiscLeast && LampDiscRadius(on, std::nanf("")) == LampDiscLeast);
        // The softness is the base: softer twice (at most LampDiscCap), sharp no disc.
        LampShadowTune softer = on;
        softer.radius_m = LampSoftnessRadii[2];
        assert(std::abs(LampDiscRadius(softer, inv(5.0f)) - 0.2f) < 1e-6f);
        assert(LampDiscRadius(softer, inv(40.0f)) == LampDiscCap);
        LampShadowTune sharp = on;
        sharp.radius_m = LampSoftnessRadii[0];
        assert(LampDiscRadius(sharp, inv(5.0f)) == 0.0f);
        // Word 10: radius and blind distance in millimetres (BB_LAMP_SHADOW_CLEARANCE, at least the
        // radius + 0.05 m), as point_shadow_ray.comp lampVisibility unpacks it.
        assert(LampDiscWord(on, 0.1f) == (100u | 180u << 16));
        assert(LampDiscWord(on, 0.3f) == (300u | 350u << 16));
        assert(LampDiscWord(on, 0.03f) == (30u | 180u << 16));
        LampShadowTune far = on;
        far.clearance_m = 2.0f;
        assert(LampDiscWord(far, 0.5f) == (500u | 2000u << 16));
        for (const float r : {0.03f, 0.1f, 0.17f, 0.24f, 0.3f, 0.5f}) {
            const std::uint32_t w = LampDiscWord(on, r);
            assert(std::abs(float(w & 0xFFFFu) * 0.001f - r) <= 0.0005f);
            assert(float(w >> 16) * 0.001f >= std::max(on.clearance_m, r + LampClearanceOverRadius) - 1e-5f);
        }
        // A followed lamp's disc moves a sixteenth of the way to the new one each frame (a flame's
        // flickering reach); one 1.6 times larger or smaller is taken at once and counted; a
        // record of no lamp takes its own.
        assert(LampDiscKeep(0.0f, 0.1f) == 0.1f && std::abs(LampDiscKeep(0.1f, 0.132f) - 0.102f) < 1e-6f);
        assert(LampDiscKeep(0.1f, 0.2f) == 0.2f && LampDiscKeep(0.2f, 0.1f) == 0.1f);
        assert(LampDiscKeep(0.1f, 0.1f) == 0.1f);
        constexpr std::array<float, 12> Same{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        LampTrack track;
        assert(track.Disc(-1, 0.07f) == 0.07f);
        // A carried flame whose reach is 5 m and 6.6 m in turn (0.1 m and 0.132 m): a steady disc
        // near their mean, at most 2 mm from one frame to the next, no jump; then 12 m: a jump.
        float held = 0.0f;
        for (int f = 0; f < 97; ++f) {
            const float reach = f == 96 ? 12.0f : (f % 2 == 1 ? 6.6f : 5.0f);
            const auto a = Record(0.0f, 1.0f, 2.0f, reach);
            track.Begin(Same.data());
            const int i = track.Add(a.data());
            track.Follow();
            const float disc = track.Disc(i, LampDiscRadius(on, F(a[3])));
            assert(track.Disc(i, LampDiscRadius(on, F(a[3]))) == disc); // its other records
            const LampSeen& lamp = track.Lamp(std::uint32_t(i));
            if (f == 0) {
                assert(!lamp.followed && std::abs(disc - 0.1f) < 1e-6f);
            } else if (f < 96) {
                assert(lamp.followed && disc >= 0.1f - 1e-6f && disc <= 0.132f + 1e-6f);
                assert(std::abs(disc - held) <= 0.0021f && lamp.disc_moves == 0u);
            } else {
                assert(std::abs(held - 0.116f) < 0.002f);
                assert(lamp.followed && std::abs(disc - 0.24f) < 1e-6f && lamp.disc_moves == 1u);
                track.ClearSteps();
                assert(lamp.disc_moves == 0u && lamp.disc == disc);
            }
            held = disc;
            track.End(true);
        }
    }
    // Two lamps a few centimetres apart that move together (a hand torch made of two lights):
    // each is found again as itself, from the first moving frame on, and both have the step.
    // Before, each took the nearest place of the frame before: one of them the other's, with
    // a wrong step or one against the motion, and the other none.
    {
        constexpr std::array<float, 12> Same{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const std::array<std::array<float, 2>, 5> cases{{{0.05f, 0.067f}, {0.05f, 0.03f}, {0.1f, 0.067f},
                                                         {0.02f, 0.01f}, {0.3f, 0.067f}}};
        for (const auto& [gap, step] : cases) {
            for (const bool second_first : {false, true}) {
                LampTrack track;
                for (int frame = 0; frame < 4; ++frame) {
                    const float x = step * float(frame);
                    const auto a = Record(x, 1.0f, 2.0f, 5.0f), b = Record(x + gap, 1.0f, 2.0f, 5.0f);
                    track.Begin(Same.data());
                    const int ia = second_first ? (track.Add(b.data()), track.Add(a.data())) : track.Add(a.data());
                    const int ib = track.Add(b.data());
                    track.Follow();
                    if (frame > 0) {
                        assert(track.Lamp(std::uint32_t(ia)).followed && track.Lamp(std::uint32_t(ib)).followed);
                        assert(std::abs(track.Step(ia) - step) < 1e-4f && std::abs(track.Step(ib) - step) < 1e-4f);
                        assert(std::abs(track.Lamp(std::uint32_t(ia)).moved[0] - step) < 1e-4f);
                        assert(std::abs(track.Lamp(std::uint32_t(ib)).moved[0] - step) < 1e-4f);
                    }
                    track.End(true);
                }
            }
        }
        // A flame whose reach flickers (5 m, 6.6 m) while it is carried is one lamp all the same.
        LampTrack track;
        for (int frame = 0; frame < 4; ++frame) {
            const auto a = Record(0.05f * float(frame), 1.0f, 2.0f, frame & 1 ? 6.6f : 5.0f);
            track.Begin(Same.data());
            track.Add(a.data());
            track.Follow();
            assert(frame == 0 || (track.Lamp(0).followed && std::abs(track.Step(0) - 0.05f) < 1e-4f));
            track.End(true);
        }
        // A lamp that jumps further than Reach is new, and what the history holds under it is
        // not its own: Lost. Unless the frame before had as many lamps as are told apart (it
        // may have been one more of them): then nothing is known, and the step is 0.
        const auto jumped = Record(0.15f + LampTrack::Reach + 0.2f, 1.0f, 2.0f, 5.0f);
        track.Begin(Same.data());
        track.Add(jumped.data());
        track.Follow();
        assert(!track.Lamp(0).followed && track.Step(0) == LampTrack::Lost);
        track.End(true);
        track.Begin(Same.data());
        for (std::uint32_t k = 0; k < LampTrack::Most; ++k) {
            const auto r = Record(float(k), 0.0f, 20.0f, 3.0f);
            track.Add(r.data());
        }
        track.End(true);
        track.Begin(Same.data());
        const auto stranger = Record(-5.0f, 0.0f, 20.0f, 3.0f), known = Record(3.0f, 0.0f, 20.0f, 3.0f);
        assert(track.Add(stranger.data()) == 0 && track.Add(known.data()) == 1);
        track.Follow();
        assert(!track.Lamp(0).followed && track.Step(0) == 0.0f);
        assert(track.Lamp(1).followed && track.Step(1) == 0.0f);
        track.End(false);
    }
    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR: off unless set, any whole number above 0
    // is on, text that is no number leaves it off; LampTuneWords never sets its bit (Flush does).
    {
        assert(!Read(std::array<Pair, 0>{}).colour);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_COLOUR", "1"}}}).colour);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_COLOUR", "0"}}}).colour);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_COLOUR", "7"}}}).colour);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_COLOUR", "-1"}}}).colour);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_COLOUR", "yes"}}}).colour);
        LampShadowTune on;
        on.colour = true;
        assert(LampTuneWords(on, true, 0.05f) == LampTuneWords(LampShadowTune{}, true, 0.05f));
        assert((LampTuneWords(on, true, 0.05f)[0] & LampTuneColour) == 0u && LampTuneColour == 1u << 25);
        // The rescale (the shader's colourScale). Lit by every lamp or by none, or one lamp's colour
        // only: the grey ratio in every channel.
        const auto luma = [](const LampRgb& light, const LampRgb& s) {
            return 0.299f * light[0] * s[0] + 0.587f * light[1] * s[1] + 0.114f * light[2] * s[2];
        };
        const LampRgb warm{1.0f, 0.6f, 0.3f}, cool{0.3f, 0.5f, 1.0f};
        for (const float r : {0.0f, 0.4f, 1.0f}) {
            const LampRgb x = LampColourScale({r, r, r}, r, warm);
            assert(std::abs(x[0] - r) < 1e-5f && std::abs(x[1] - r) < 1e-5f && std::abs(x[2] - r) < 1e-5f);
        }
        // The owner's photo: a warm and a cool lamp of equal weight, the warm one blocked. Their
        // channel weights are weight x colour / luma (point_shadow_ray.comp colourOf); the light is
        // their sum. The exact answer in each channel is the cool lamp's share; it already gives the
        // grey ratio's luma (0.5), so the rescale keeps it: bluish, as bright as the grey shadow.
        const float lw = luma({1.0f, 1.0f, 1.0f}, warm), lc = luma({1.0f, 1.0f, 1.0f}, cool);
        LampRgb light{}, rc{};
        for (int c = 0; c < 3; ++c) {
            light[c] = warm[c] / lw + cool[c] / lc;
            rc[c] = (cool[c] / lc) / light[c];
        }
        const LampRgb x = LampColourScale(rc, 0.5f, light);
        for (int c = 0; c < 3; ++c) {
            assert(std::abs(x[c] - rc[c]) < 1e-4f && x[c] >= 0.0f && x[c] <= 1.0f);
        }
        assert(x[2] > x[1] && x[1] > x[0]);
        assert(std::abs(luma(light, x) - 0.5f * luma(light, {1.0f, 1.0f, 1.0f})) < 1e-4f);
        // A history whose colour lies below the grey ratio: lifted to its luma and kept within 1.
        const LampRgb lifted = LampColourScale({0.2f, 0.5f, 0.9f}, 0.95f, light);
        for (const float v : lifted) {
            assert(v >= 0.0f && v <= 1.0f + 1e-6f);
        }
        assert(std::abs(luma(light, lifted) - 0.95f * luma(light, {1.0f, 1.0f, 1.0f})) < 1e-4f);
        assert(lifted[2] > lifted[0]);
        // A channel without lamp light counts for nothing; no light at all: the grey ratio.
        const LampRgb no_blue = LampColourScale({0.5f, 0.5f, 0.0f}, 0.5f, {1.0f, 1.0f, 0.0f});
        assert(std::abs(no_blue[0] - 0.5f) < 1e-5f && std::abs(no_blue[1] - 0.5f) < 1e-5f);
        const LampRgb dark = LampColourScale({0.1f, 0.9f, 0.3f}, 0.3f, {0.0f, 0.0f, 0.0f});
        assert(dark[0] == 0.3f && dark[1] == 0.3f && dark[2] == 0.3f);
        // bbport (r131d_lamp-colour-blob): a grey ratio one rounding step above 1 (an averaged history) with a grey or coloured
        // rc can yield NaN channels. This supplies the ratio to the CPU mirror. The in-game probe checks the shader.
        const float above = std::nextafter(1.0f, 2.0f);
        for (const LampRgb& rc_in : {LampRgb{1.0f, 1.0f, 1.0f}, LampRgb{0.7f, 0.7f, 0.7f}, LampRgb{0.2f, 0.5f, 0.9f}}) {
            for (const LampRgb& lit : {LampRgb{1.0f, 1.0f, 1.0f}, LampRgb{0.8f, 0.6f, 0.3f}}) {
                for (const float v : LampColourScale(rc_in, above, lit)) {
                    assert(std::isfinite(v) && v >= 0.0f && v <= 1.0f);
                }
            }
        }
    }
    // bbport (r93_lamp-shadow-spatial): BB_LAMP_SHADOW_SPATIAL is off unless set to 1 (2 or more: 1;
    // below 0 or text: off). It changes none of LampTuneWords' words nor the history block's: Flush
    // ORs bit 26 in (LampTuneSpatialBit), and only with the centred window (0 and 1 have no resolve).
    {
        static_assert(LampTuneSpatial == 1u << 26);
        const LampShadowTune d = Read(std::array<Pair, 0>{});
        assert(!d.spatial && LampTuneSpatialBit(d) == 0u);
        const LampShadowTune on = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", "1"}}});
        assert(on.spatial && LampTuneSpatialBit(on) == (LampWindowDefault == 2 ? LampTuneSpatial : 0u));
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", "0"}}}).spatial);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", "3"}}}).spatial);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", "-1"}}}).spatial);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", "yes"}}}).spatial);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", ""}}}).spatial);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", " 1 "}}}).spatial);
        const float c = std::cos(0.3f), s = std::sin(0.3f);
        const std::array<float, 12> view{c, 0.0f, -s, 1.0f, 0.0f, 1.0f, 0.0f, 2.0f, s, 0.0f, c, 3.0f};
        for (const char* window : {"0", "1", "2"}) {
            const std::array<Pair, 2> with{{{"BB_LAMP_SHADOW_WINDOW", window}, {"BB_LAMP_SHADOW_SPATIAL", "1"}}};
            const std::array<Pair, 1> without{{{"BB_LAMP_SHADOW_WINDOW", window}}};
            const LampShadowTune t = Read(with), p = Read(without);
            assert(t.spatial && !p.spatial);
            const auto words = LampTuneWords(t, true, 0.05f, view.data(), 9u);
            assert(words == LampTuneWords(p, true, 0.05f, view.data(), 9u) && (words[0] & LampTuneSpatial) == 0u);
            assert(LampHistoryTail(t) == LampHistoryTail(p));
            assert(LampTuneSpatialBit(t) == (window[0] == '2' ? LampTuneSpatial : 0u) && LampTuneSpatialBit(p) == 0u);
        }
        // As bit 22: never without the window, even with window_centred set.
        LampShadowTune odd = on;
        odd.window = false;
        odd.window_centred = true;
        assert(LampTuneSpatialBit(odd) == 0u);
    }
    // bbport (r103_lamp-young-pixels): BB_LAMP_SHADOW_YOUNG is 0 to 2 (3 or more: 2; below 0, text or
    // nothing: 0); its bits only with the centred window, and never in LampTuneWords (Flush ORs them in).
    {
        static_assert(LampTuneYoung == 1u << 27 && LampTuneYoungKeep == 1u << 28);
        assert(LampYoungParse(nullptr) == 0u && LampYoungParse("") == 0u && LampYoungParse("0") == 0u);
        assert(LampYoungParse("1") == 1u && LampYoungParse(" 2 ") == 2u && LampYoungParse("7") == 2u);
        assert(LampYoungParse("-1") == 0u && LampYoungParse("yes") == 0u && LampYoungParse("1x") == 0u);
        LampShadowTune t;
        t.window = true;
        t.window_centred = true;
        assert(LampYoungBitsFor(0u, t) == 0u && LampYoungBitsFor(1u, t) == LampTuneYoung &&
               LampYoungBitsFor(2u, t) == (LampTuneYoung | LampTuneYoungKeep));
        t.window_centred = false;
        assert(LampYoungBitsFor(1u, t) == 0u && LampYoungBitsFor(2u, t) == 0u);
        t.window = false;
        t.window_centred = true;
        assert(LampYoungBitsFor(2u, t) == 0u);
        const LampShadowTune d{};
        assert((LampTuneWords(d, true, 0.05f, nullptr, 9u)[0] & (LampTuneYoung | LampTuneYoungKeep)) == 0u);
    }
    // bbport (r103b_lamp-young-standing): BB_LAMP_SHADOW_YOUNG_STILL is on unless it is the whole number 0;
    // its bit 29 is free and never in LampTuneWords (LampYoungBits ORs it in with bit 27).
    {
        static_assert(LampTuneYoungStill == 1u << 29 && (LampTuneYoungStill & (LampTuneYoung | LampTuneYoungKeep)) == 0u);
        assert(LampYoungStillParse(nullptr) && LampYoungStillParse("") && LampYoungStillParse("1"));
        assert(!LampYoungStillParse("0") && !LampYoungStillParse(" 0 ") && !LampYoungStillParse("-0"));
        assert(LampYoungStillParse("2") && LampYoungStillParse("yes") && LampYoungStillParse("0x"));
        const LampShadowTune d{};
        assert((LampTuneWords(d, true, 0.05f, nullptr, 9u)[0] & LampTuneYoungStill) == 0u);
    }
    // bbport (r113_lamp-softness): BB_LAMP_SHADOW_FLAME (lamp_flame.h): the parse, word 0's bits 11 and
    // 23 (the shader reads ((word 0 >> 11) & 1) * (1 + ((word 0 >> 23) & 1)); LampTuneWords never sets
    // them), and the flame's radius as the shader's flameOffset works it out: from 0 to LampFlameReach,
    // never falling, the core's edge at LampFlameSplit, and the inverse of the share of the light within it.
    {
        assert(LampFlameParse(nullptr) == 0u && LampFlameParse("") == 0u && LampFlameParse("0") == 0u);
        assert(LampFlameParse("1") == 1u && LampFlameParse(" 2 ") == 2u && LampFlameParse("7") == 2u);
        assert(LampFlameParse("-1") == 0u && LampFlameParse("yes") == 0u && LampFlameParse("1x") == 0u);
        assert(LampFlameBitsFor(0u) == 0u && LampFlameBitsFor(1u) == LampTuneFlame &&
               LampFlameBitsFor(2u) == (LampTuneFlame | LampTuneFlameTall) &&
               LampFlameBitsFor(9u) == (LampTuneFlame | LampTuneFlameTall));
        for (std::uint32_t v = 0; v <= 2; ++v) {
            assert(LampFlameOf(LampFlameBitsFor(v)) == v && LampFlameOf(LampFlameBitsFor(v) | 0xFF7FF7FFu) == v);
        }
        assert(LampFlameOf(LampTuneFlameTall) == 0u); // bit 23 alone: no flame
        const LampShadowTune d = Read(std::array<Pair, 0>{});
        assert((LampTuneWords(d, true, 0.05f)[0] & (LampTuneFlame | LampTuneFlameTall)) == 0u);
        assert(std::fabs(LampFlameSplit - 0.53125f) < 1e-6f);
        float last = -1.0f;
        for (int i = 0; i <= 1000; ++i) {
            const float u = float(i) / 1000.0f;
            const float r = LampFlameRadius(u);
            assert(r >= last && r >= 0.0f && r <= LampFlameReach + 1e-5f);
            const float c = std::min(r / LampFlameCore, 1.0f);
            const float share = LampFlameCoreShare * c * c +
                                (1.0f - LampFlameCoreShare) * (r / LampFlameReach) * (r / LampFlameReach);
            assert(std::fabs(share - u) < 1e-4f);
            last = r;
        }
        assert(LampFlameRadius(0.0f) == 0.0f && std::fabs(LampFlameRadius(1.0f) - LampFlameReach) < 1e-5f);
        assert(std::fabs(LampFlameRadius(LampFlameSplit) - LampFlameCore) < 1e-5f);
    }
    std::puts("lamp shadow tune: ok");
    return 0;
}
