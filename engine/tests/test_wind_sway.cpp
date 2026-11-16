// SPDX-License-Identifier: GPL-3.0-or-later
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
#include "gpu/shim/bbport_wind_twigs.h" // bbport (r89d_tree-twigs)

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

// bbport (r89b_wind-sway-ripple): r89's Displace before the ripple, word for word but for its name
// and the key it can return (not needed here), for the check that BB_WIND_SWAY_RIPPLE=0 is r89's
// motion bit for bit.
std::array<float, 4> R89Displace(const float* view, const std::array<float, 4>& clip,
                                 std::uint32_t stored, float ramp) {
    const auto dot = [&](std::uint32_t at) {
        return view[at] * clip[0] + view[at + 1] * clip[1] + view[at + 2] * clip[2] +
               view[at + 3] * clip[3];
    };
    const float rx = dot(ToWorldAt), rz = dot(ToWorldAt + 8);
    const float wy = dot(ToWorldAt + 4) + view[WindA + 2];
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

// bbport (r89b_wind-sway-ripple): a view of constants c in wind s with the ripple of `knob` (its
// phases kept in `ripple`, which each call updates for this camera and time).
std::array<float, ViewWords> RippleViewOf(const std::array<float, 216>& c,
                                          const BbWind::Snapshot& s, Ripple& ripple,
                                          const RippleKnob& knob, float scale = 1.0f,
                                          float gusts = 0.5f) {
    Camera cam;
    const bool ok = CameraOf(c.data(), cam);
    Expect(ok, "the camera of the test constants");
    std::array<float, ViewWords> view{};
    FillView(cam, s, gusts, scale, view.data());
    (void)FillRipple(ripple, cam, s, gusts, scale, knob, view.data());
    return view;
}

// How the sway moves world point p (its mesh's lowest point at height `base`), in the world.
std::array<double, 3> MoveOf(const float* view, const std::array<float, 216>& c,
                             const std::array<double, 3>& p, float base, float ramp = 1.0f) {
    const auto clip = ClipOf(c, p);
    const auto before = WorldOf(view, clip);
    const auto after = WorldOf(view, Displace(view, clip, HeightKey(base), ramp));
    return {after[0] - before[0], after[1] - before[1], after[2] - before[2]};
}

double Length(const std::array<double, 3>& d) {
    return std::hypot(d[0], d[2]);
}

double Correlation(const std::vector<double>& a, const std::vector<double>& b) {
    double ma = 0.0, mb = 0.0;
    for (std::size_t i = 0; i < a.size(); ++i) {
        ma += a[i];
        mb += b[i];
    }
    ma /= double(a.size());
    mb /= double(b.size());
    double ab = 0.0, aa = 0.0, bb = 0.0;
    for (std::size_t i = 0; i < a.size(); ++i) {
        ab += (a[i] - ma) * (b[i] - mb);
        aa += (a[i] - ma) * (a[i] - ma);
        bb += (b[i] - mb) * (b[i] - mb);
    }
    return ab / std::sqrt(aa * bb);
}

// bbport (r89c_wind-lean): a view of constants c in wind s with the lean (its phases kept in
// `ripple`, which each call updates for this camera and time).
std::array<float, ViewWords> LeanViewOf(const std::array<float, 216>& c, const BbWind::Snapshot& s,
                                        Ripple& ripple, const RippleKnob& knob,
                                        const LeanKnob& lean, float scale = 1.0f,
                                        float gusts = 0.5f) {
    Camera cam;
    const bool ok = CameraOf(c.data(), cam);
    Expect(ok, "the camera of the test constants");
    std::array<float, ViewWords> view{};
    FillView(cam, s, gusts, scale, view.data());
    Expect(FillLean(ripple, cam, s, gusts, scale, knob, lean, view.data()), "FillLean writes");
    return view;
}

// How the lean moves world point p of a mesh whose lowest point is at height `base` and highest
// at `crown` (a crown below the base: no crown key yet, ResetKey), in the world (x, y, z).
std::array<double, 3> LeanMoveOf(const float* view, const std::array<float, 216>& c,
                                 const std::array<double, 3>& p, float base, float crown) {
    const auto clip = ClipOf(c, p);
    const auto before = WorldOf(view, clip);
    const std::uint32_t crown_key = crown < base ? ResetKey : CrownKey(crown);
    const auto after =
        WorldOf(view, Displace(view, clip, HeightKey(base), 1.0f, nullptr, crown_key));
    return {after[0] - before[0], after[1] - before[1], after[2] - before[2]};
}

// The parts of a move along the wind (toward where it blows) and across it.
double AlongOf(const std::array<double, 3>& d, const BbWind::Snapshot& s) {
    return d[0] * s.dir_x + d[2] * s.dir_z;
}

double AcrossOf(const std::array<double, 3>& d, const BbWind::Snapshot& s) {
    return d[2] * s.dir_x - d[0] * s.dir_z;
}

// A wind as BbWind gives it: the gust factor at its time (BB_WIND_GUSTS `gusts`).
BbWind::Snapshot Gusty(double time, float deg, float speed, float gusts) {
    BbWind::Snapshot s = Wind(time, deg, speed);
    s.gust = BbWind::Gust(time, gusts);
    return s;
}

// bbport (r89d_tree-twigs): a tree mesh's box in the world (m) as the GPU's keys hold it: lowest and
// highest y, lowest and highest x, lowest and highest z.
struct TreeBox {
    float base, crown, x_lo, x_hi, z_lo, z_hi;
};

TwigIn TwigInOf(const TreeBox& b, bool tree_only) {
    TwigIn in;
    in.keys = {HeightKey(b.x_lo), CrownKey(b.x_hi), HeightKey(b.z_lo), CrownKey(b.z_hi)};
    in.tree_only = tree_only;
    return in;
}

// A view with the lean and the twigs' gain in RippleD.z, as the CPU writes it (BB_WIND_TWIGS `twigs`).
std::array<float, ViewWords> TwigViewOf(const std::array<float, 216>& c, const BbWind::Snapshot& s,
                                        Ripple& ripple, float twigs, float scale = 1.0f,
                                        float gusts = 0.5f) {
    auto view = LeanViewOf(c, s, ripple, ParseRipple(nullptr, nullptr), ParseLean(nullptr, nullptr),
                           scale, gusts);
    view[RippleD + 2] = TwigRatio * twigs;
    return view;
}

// How the lean moves world point p of a mesh with box b, with the twigs (or, `twigs_on` false, as
// before them): after minus before, in the world (x, y, z).
std::array<double, 3> TwigMoveOf(const float* view, const std::array<float, 216>& c,
                                 const std::array<double, 3>& p, const TreeBox& b,
                                 bool tree_only = false, bool twigs_on = true) {
    const auto clip = ClipOf(c, p);
    const auto before = WorldOf(view, clip);
    const TwigIn in = TwigInOf(b, tree_only);
    const auto after = WorldOf(view, Displace(view, clip, HeightKey(b.base), 1.0f, nullptr,
                                              CrownKey(b.crown), nullptr,
                                              twigs_on ? &in : nullptr));
    return {after[0] - before[0], after[1] - before[1], after[2] - before[2]};
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
        Expect(TableAt + GustSamples == RippleAt && RippleAt + RippleWords == ViewWords && // r89b
                   ToWorldAt == ForwardAt + 16 &&
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
        for (std::uint64_t i = 1; i < PlantSlots; ++i) { // bbport (r89c_wind-lean)
            all &= slots.Take(0x100000 + i * 64, 1024, 41, 9.5).ok;
        }
        Expect(all && slots.InUse(41) == PlantSlots, "every slot taken");
        Expect(!slots.Take(0x900000, 1024, 41, 9.5).ok, "full: no slot");
        Expect(!slots.Take(0x900000, 1024, 41 + ReuseFrames, 9.5).ok,
               "a slot rests ReuseFrames frames");
        // only 0x1000 is drawn on 49; the oldest of the others goes
        Expect(slots.Take(0x1000, 8192, 49, 10.0).slot == a.slot, "a drawn stream keeps its slot");
        const auto reused = slots.Take(0x900000, 1024, 50, 10.0);
        Expect(reused.ok && reused.reset && reused.slot != a.slot, "a rested slot is reused");
        Expect(slots.Take(0x1000, 8192, 50, 10.0).slot == a.slot, "and the drawn one kept");
    }

    // bbport (r89b_wind-sway-ripple): the ripple's knob.
    {
        Expect(ParseRipple(nullptr, nullptr).strength == RippleDefault &&
                   !ParseRipple(nullptr, nullptr).show,
               "BB_WIND_SWAY_RIPPLE unset: the ripple at 1, no test view");
        Expect(ParseRipple("1", nullptr).strength == 1.0f, "1: the ripple");
        Expect(ParseRipple("0", "1").strength == 0.0f && !ParseRipple("0", "1").show,
               "0: r89's motion, and no test view");
        Expect(ParseRipple("-2", nullptr).strength == 0.0f, "below 0: 0");
        Expect(ParseRipple("0.1", nullptr).strength == RippleMin &&
                   ParseRipple("9", nullptr).strength == RippleMax,
               "a strength is held to 0.25-4");
        Expect(ParseRipple("2.5", nullptr).strength == 2.5f, "a strength is read");
        Expect(ParseRipple("abc", nullptr).strength == RippleDefault &&
                   ParseRipple("nan", nullptr).strength == RippleDefault &&
                   ParseRipple("", nullptr).strength == RippleDefault,
               "unreadable, not finite or empty: the default");
        Expect(ParseRipple(nullptr, "1").show && !ParseRipple(nullptr, "0").show,
               "BB_WIND_SWAY_SHOW=1");
    }

    // The ripple's constants are their wavelengths and angles; the envelope's mean is 1.
    {
        const double pi = 3.14159265358979323846;
        const float env[3][2] = {{Env1S, Env1Q}, {Env2S, Env2Q}, {Env3S, Env3Q}};
        bool tied = true;
        for (int i = 0; i < 3; ++i) {
            const double k = 2.0 * pi / EnvWavelength[i], a = EnvAngle[i] * pi / 180.0;
            tied &= Near(env[i][0], -k * std::cos(a), 1e-6) &&
                    Near(env[i][1], k * std::sin(a), 1e-6);
        }
        const float leaf[2][3] = {{Leaf1X, Leaf1Y, Leaf1Z}, {Leaf2X, Leaf2Y, Leaf2Z}};
        for (int i = 0; i < 2; ++i) {
            const double len = std::sqrt(double(LeafDir[i][0]) * LeafDir[i][0] +
                                         double(LeafDir[i][1]) * LeafDir[i][1] +
                                         double(LeafDir[i][2]) * LeafDir[i][2]);
            for (int d = 0; d < 3; ++d) {
                tied &= Near(leaf[i][d], 2.0 * pi / LeafWavelength[i] * LeafDir[i][d] / len, 1e-5);
            }
        }
        Expect(tied, "the waves' numbers are their wavelengths and directions");
        Expect(Near(EnvInv, 1.0 / (-2.0 * double(EnvLo)), 1e-7), "EnvInv = 1 / (-2 EnvLo)");
        std::array<float, ViewWords> view{};
        view[RippleB + 3] = 1.0f;
        double sum = 0.0;
        const int n = 40;
        for (int a = 0; a < n; ++a) {
            for (int b = 0; b < n; ++b) {
                for (int c = 0; c < n; ++c) {
                    view[RippleA + 2] = float(2.0 * pi * (a + 0.5) / n);
                    view[RippleA + 3] = float(2.0 * pi * (b + 0.5) / n);
                    view[RippleB] = float(2.0 * pi * (c + 0.5) / n);
                    sum += Envelope(view.data(), 0.0f, 0.0f);
                }
            }
        }
        Expect(Near(sum / (n * n * n), 1.0, 0.01), "the gust envelope's mean over its phases is 1");
    }

    // BB_WIND_SWAY_RIPPLE=0: no ripple words, and r89's displacement bit for bit.
    {
        std::uint32_t seed = 12345u;
        const auto rnd = [&seed]() {
            seed = seed * 1664525u + 1013904223u;
            return double(seed >> 8) / 16777216.0;
        };
        const RippleKnob off = ParseRipple("0", nullptr);
        bool same = true, zero = true, filled = false;
        int moved = 0;
        for (int i = 0; i < 400; ++i) {
            const double yaw = 6.28 * rnd(), pitch = -0.4 * rnd();
            const std::array<double, 3> eye = {400.0 * rnd() - 200.0, 20.0 * rnd(),
                                               400.0 * rnd() - 200.0};
            const auto c = Constants(yaw, pitch, eye);
            const auto s = Wind(1000.0 * rnd(), float(360.0 * rnd()), float(4.0 * rnd()));
            auto view = ViewOf(c, s, float(rnd()), float(3.0 * rnd()));
            Camera cam;
            Ripple ripple;
            Expect(CameraOf(c.data(), cam), "a camera");
            filled |= FillRipple(ripple, cam, s, 0.5f, 1.0f, off, view.data());
            zero &= std::all_of(view.begin() + RippleAt, view.end(),
                                [](float v) { return v == 0.0f; });
            const double ahead = 2.0 + 20.0 * rnd();
            const std::array<double, 3> p = {eye[0] - std::sin(yaw) * ahead + rnd() - 0.5,
                                             eye[1] - 1.5 + 2.0 * rnd(),
                                             eye[2] - std::cos(yaw) * ahead + rnd() - 0.5};
            const auto clip = ClipOf(c, p);
            const std::uint32_t stored = HeightKey(float(eye[1] - 1.6));
            const float ramp = float(rnd());
            const auto a = Displace(view.data(), clip, stored, ramp);
            const auto b = R89Displace(view.data(), clip, stored, ramp);
            same &= std::memcmp(a.data(), b.data(), sizeof(a)) == 0;
            moved += std::memcmp(a.data(), clip.data(), sizeof(a)) != 0 ? 1 : 0;
        }
        Expect(!filled && zero, "BB_WIND_SWAY_RIPPLE=0: no ripple words");
        Expect(same, "BB_WIND_SWAY_RIPPLE=0: r89's displacement bit for bit");
        Expect(moved > 200, "and those vertices moved");
    }

    // The ripple: still at weight 0, the same for the same world point, horizontal.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const RippleKnob on = ParseRipple(nullptr, nullptr);
        const auto s = Wind(5.0, 225.0f, 1.5f);
        const auto view = RippleViewOf(c, s, ripple, on);
        Expect(view[RippleD + 3] == 1.0f && view[RippleC] == Lean && view[RippleC + 1] == Flutter &&
                   view[RippleC + 3] == Leaf && view[RippleB + 3] == 1.0f,
               "the ripple's words at 1.5 m/s, gust 1, strength 1");
        const auto at = [](double up) {
            return std::array<double, 3>{10.0 - std::sin(0.3) * 6.0, 0.5 + up,
                                         20.0 - std::cos(0.3) * 6.0};
        };
        const auto top = ClipOf(c, at(1.2));
        const auto a = Displace(view.data(), top, HeightKey(0.5f), 1.0f);
        const auto b = Displace(view.data(), top, HeightKey(0.5f), 1.0f);
        Expect(std::memcmp(a.data(), b.data(), sizeof(a)) == 0, "the same vertex: the same result");
        const auto still = Displace(view.data(), top, HeightKey(0.5f), 0.0f);
        Expect(std::memcmp(still.data(), top.data(), sizeof(top)) == 0,
               "weight 0 (ramp 0): unchanged");
        Expect(Length(MoveOf(view.data(), c, at(0.0), 0.5f)) < 1e-4, "ripple: the roots stay");
        Expect(Length(MoveOf(view.data(), c, at(-0.3), 0.5f)) < 1e-4,
               "ripple: below the lowest point, still");
        const auto moved = MoveOf(view.data(), c, at(1.2), 0.5f);
        Expect(std::fabs(moved[1]) < 2e-3 && Length(moved) > 1e-3,
               "the ripple is horizontal and moves the top");
        // the same world points through a second view of the same frame, with its own camera
        const auto c2 = Constants(1.4, -0.3, {14.0, 3.0, 13.0});
        const auto view2 = RippleViewOf(c2, s, ripple, on);
        const auto view1 = RippleViewOf(c, s, ripple, on);
        double worst = 0.0;
        for (int i = 0; i < 40; ++i) {
            const std::array<double, 3> p = {8.0 + 0.1 * i, 1.4, 14.0 + 0.07 * i};
            const auto d1 = MoveOf(view1.data(), c, p, 0.5f);
            const auto d2 = MoveOf(view2.data(), c2, p, 0.5f);
            worst = std::max(worst, std::hypot(d1[0] - d2[0], d1[2] - d2[2]));
        }
        Expect(worst < 2e-3, "a world point moves alike in two views (a function of its position)");
    }

    // The ripple's amplitude is bounded: the strongest wind, scale, strength and test view.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const RippleKnob strongest = ParseRipple("4", "1");
        std::uint32_t seed = 777u;
        const auto rnd = [&seed]() {
            seed = seed * 1664525u + 1013904223u;
            return double(seed >> 8) / 16777216.0;
        };
        double worst = 0.0;
        for (int i = 0; i < 2000; ++i) {
            auto s = Wind(0.37 * i, float(225.0 + 40.0 * std::sin(0.01 * i)), BbWind::MaxSpeed);
            s.gust = BbWind::GustMax;
            const auto view = RippleViewOf(c, s, ripple, strongest, MaxScale, BbWind::MaxGusts);
            const std::array<double, 3> p = {10.0 - std::sin(0.3) * 6.0 + 6.0 * rnd() - 3.0, 2.0,
                                             20.0 - std::cos(0.3) * 6.0 + 6.0 * rnd() - 3.0};
            worst = std::max(worst, Length(MoveOf(view.data(), c, p, 0.5f)));
        }
        const double bound = std::hypot(double(MaxAlong), double(MaxCross)) +
                             std::hypot(double(MaxLeaf), double(MaxLeaf));
        Expect(worst <= bound + 3e-3, "the strongest ripple stays within its limits");
        Expect(worst > 0.3, "the strongest ripple reaches them");
    }

    // The gust fronts and the swing's wave move downwind with the wind (the crests too).
    {
        const auto c = Constants(0.7, -0.2, {120.0, 5.0, -310.0});
        Ripple ripple;
        const RippleKnob on = ParseRipple(nullptr, nullptr);
        const float speed = 1.5f;
        const auto first = RippleViewOf(c, Wind(100.0, 200.0f, speed), ripple, on);
        double t = 100.0;
        std::array<float, ViewWords> later{};
        for (int f = 0; f < 30; ++f) {
            t += 1.0 / 60.0;
            later = RippleViewOf(c, Wind(t, 200.0f, speed), ripple, on);
        }
        // the gust factor is 1 (Wind leaves it so): the fronts travel at the wind's speed, and the
        // swing's wave at max(speed, 0.5 m/s), the same here
        const double shift = speed * (t - 100.0);
        double same = 0.0, back = 0.0, swing = 0.0;
        for (int i = 0; i <= 80; ++i) {
            const float s = float(-20.0 + 0.5 * i), q = 1.3f;
            const float e = Envelope(later.data(), s, q);
            const float down = Envelope(first.data(), float(s - shift), q);
            const float up = Envelope(first.data(), float(s + shift), q);
            same = std::max(same, double(std::fabs(e - down)));
            back = std::max(back, double(std::fabs(e - up)));
            // the swing's phase as the shaders read it (r89's word, written by FillRipple)
            const float a_later = later[WindB + 3] - later[WindC] * s + later[WindC + 1] * q;
            const float a_first = first[WindB + 3] - first[WindC] * float(s - shift) +
                                  first[WindC + 1] * q;
            swing = std::max(swing, double(std::fabs(Wrap(a_later - a_first))));
        }
        Expect(same < 2e-3, "the gust fronts move downwind at the wind's speed");
        Expect(back > 0.05, "and not upwind");
        Expect(swing < 2e-3, "the swing's crests move downwind too");
        Expect(later[WindB + 3] == later[RippleA] && later[WindC + 2] == later[RippleA + 1],
               "r89's swing phases are the ripple's");
    }

    // The gust at the vertex: the first view's gust table is r89's; then it moves one sample
    // (GustStep s) per GustStep s of wind time, so a gust is carried downwind as with r89.
    {
        const auto c = Constants(0.7, -0.2, {120.0, 5.0, -310.0});
        Ripple ripple;
        const RippleKnob on = ParseRipple(nullptr, nullptr);
        const auto s0 = Wind(100.0, 200.0f, 1.5f);
        const auto first = RippleViewOf(c, s0, ripple, on);
        const auto plain = ViewOf(c, s0, 0.5f, 1.0f);
        double r89 = 0.0, moved = 0.0, still = 0.0;
        for (std::uint32_t i = 0; i < GustSamples; ++i) {
            r89 = std::max(r89, double(std::fabs(first[TableAt + i] - plain[TableAt + i])));
        }
        std::array<float, ViewWords> later{};
        for (int f = 1; f <= 60; ++f) {
            later = RippleViewOf(c, Wind(100.0 + f / 60.0, 200.0f, 1.5f), ripple, on);
        }
        for (std::uint32_t i = 0; i + 1 < GustSamples; ++i) {
            moved = std::max(moved, double(std::fabs(later[TableAt + i] - first[TableAt + i + 1])));
            still = std::max(still, double(std::fabs(later[TableAt + i] - first[TableAt + i])));
        }
        Expect(r89 < 1e-6, "the ripple's first gust table is r89's");
        Expect(moved < 1e-4 && still > 1e-3, "the ripple's gust table moves with the wind time");
    }

    // Calm moments and gust fronts at one point; the envelope's mean there is about 1.
    {
        const auto c = Constants(0.7, -0.2, {120.0, 5.0, -310.0});
        Ripple ripple;
        const RippleKnob on = ParseRipple(nullptr, nullptr);
        double sum = 0.0;
        int calm = 0, front = 0;
        const int steps = 6000;
        for (int i = 1; i <= steps; ++i) {
            const auto view = RippleViewOf(c, Wind(0.1 * i, 225.0f, 1.5f), ripple, on);
            const float e = Envelope(view.data(), 3.0f, -2.0f);
            sum += e;
            calm += e < 0.25f ? 1 : 0;
            front += e > 1.5f ? 1 : 0;
        }
        Expect(Near(sum / steps, 1.0, 0.15), "the gust envelope's mean at a point is about 1");
        Expect(calm > steps / 10 && front > steps / 10,
               "calm moments and gust fronts, each over a tenth of the time");
    }

    // Neighbouring leaves are out of step: the flutter of two points 0.3 m apart.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const RippleKnob on = ParseRipple(nullptr, nullptr);
        const std::array<double, 3> pa = {10.0 - std::sin(0.3) * 4.0, 1.6,
                                          20.0 - std::cos(0.3) * 4.0};
        const std::array<double, 3> pb = {pa[0] + 0.18, 1.6, pa[2] + 0.24};
        std::vector<double> fa, fb;
        for (int i = 1; i <= 600; ++i) {
            const auto view = RippleViewOf(c, Wind(50.0 + i / 60.0, 225.0f, 1.5f), ripple, on);
            auto calm = view;
            calm[RippleC + 3] = 0.0f; // no flutter
            fa.push_back(MoveOf(view.data(), c, pa, 0.5f)[0] - MoveOf(calm.data(), c, pa, 0.5f)[0]);
            fb.push_back(MoveOf(view.data(), c, pb, 0.5f)[0] - MoveOf(calm.data(), c, pb, 0.5f)[0]);
        }
        double rms = 0.0;
        for (const double v : fa) {
            rms += v * v;
        }
        rms = std::sqrt(rms / double(fa.size()));
        Expect(std::fabs(Correlation(fa, fb)) < 0.5 && rms > 2e-3,
               "leaves 0.3 m apart flutter out of step");
    }

    // A wind turning 2 deg/s, 3900 m from the world's origin: no jump (the steps from frame to
    // frame stay those of a steady wind).
    {
        const auto largest_step = [](double turn) {
            const std::array<double, 3> eye = {3000.0, 10.0, -2500.0};
            const auto c = Constants(0.4, -0.1, eye);
            Ripple ripple;
            const RippleKnob on = ParseRipple(nullptr, nullptr);
            const std::array<double, 3> p = {eye[0] - std::sin(0.4) * 8.0, 9.0,
                                             eye[2] - std::cos(0.4) * 8.0};
            std::array<double, 3> last{};
            double worst = 0.0;
            for (int f = 1; f <= 1200; ++f) {
                const double t = 10.0 + f / 60.0;
                const auto view =
                    RippleViewOf(c, Wind(t, float(225.0 + turn * (t - 10.0)), 1.5f), ripple, on);
                const auto d = MoveOf(view.data(), c, p, 7.5f);
                if (f > 1) {
                    worst = std::max(worst, std::hypot(d[0] - last[0], d[2] - last[2]));
                }
                last = d;
            }
            return worst;
        };
        const double steady = largest_step(0.0), turning = largest_step(2.0);
        Expect(steady > 1e-3 && turning <= 1.5 * steady + 1e-4, "a turning wind: no jump");
    }

    // bbport (r89c_wind-lean): the style and the wave's knobs.
    {
        Expect(ParseLean(nullptr, nullptr).lean && ParseLean(nullptr, nullptr).wave == WaveDefault,
               "unset: the lean, wave 1");
        Expect(!ParseLean("wave", nullptr).lean && ParseLean("lean", nullptr).lean &&
                   ParseLean("x", nullptr).lean && ParseLean("", nullptr).lean,
               "BB_WIND_SWAY_STYLE=wave: r89b's ripple; anything else: the lean");
        Expect(ParseLean(nullptr, "0").wave == 0.0f && ParseLean(nullptr, "-1").wave == 0.0f &&
                   ParseLean(nullptr, "9").wave == WaveMax && ParseLean(nullptr, "2.5").wave == 2.5f &&
                   ParseLean(nullptr, "abc").wave == WaveDefault &&
                   ParseLean(nullptr, "nan").wave == WaveDefault,
               "BB_WIND_SWAY_WAVE: 0-4, unreadable 1");
    }

    // The lean's numbers are of the wind speed: none at 0 m/s, growing with it; calm at 1.5 m/s.
    {
        const LeanCurve calm = LeanAt(0.0f, 1.0f, 1.0f, false);
        Expect(calm.bend == 0.0f && calm.rest == 0.0f && calm.along == 0.0f && calm.cross == 0.0f &&
                   calm.leaf == 0.0f && calm.tree == 0.0f,
               "no wind: no bend, wave, flutter or tree");
        bool rising = true;
        LeanCurve last = calm;
        for (int i = 1; i <= 80; ++i) {
            const LeanCurve c = LeanAt(0.05f * float(i), 1.0f, 1.0f, false);
            rising = rising && c.bend > last.bend && c.along > last.along && c.hz > last.hz &&
                     c.leaf >= last.leaf && c.tree >= last.tree;
            last = c;
        }
        Expect(rising, "the bend, the wave, its rate, the flutter and the trees grow with the wind");
        Expect(Near(last.bend, BendMax, 1e-6) && last.tree == 1.0f && Near(last.leaf, Leaf, 1e-6),
               "at 4 m/s: BendMax, the trees in full, the leaves Leaf");
        const LeanCurve normal = LeanAt(BbWind::DefaultSpeed, 1.0f, 1.0f, false);
        Expect(normal.leaf == 0.0f && normal.tree < 0.1f && normal.hz < 0.5f &&
                   (LeanRest + EnvScale) * normal.bend < 0.04f,
               "at 1.5 m/s: no flutter, trees under a tenth, the wave under 0.5 Hz, a bend under 4 cm");
        Expect(EnvScale * normal.along * BbWind::GustMax < 0.0105f &&
                   Near(normal.along / normal.bend, WaveRatio, 1e-6),
               "at 1.5 m/s the wave is 15% of the bend and under about 1 cm");
        Expect(LeanAt(4.0f, 1.0f, 0.0f, false).along == 0.0f &&
                   LeanAt(4.0f, 1.0f, 0.0f, false).leaf == 0.0f,
               "BB_WIND_SWAY_WAVE=0: no wave, no flutter");
    }

    // The lean's words; zero wind moves nothing.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const auto s = Wind(5.0, 225.0f, 1.5f);
        const auto view = LeanViewOf(c, s, ripple, ParseRipple(nullptr, nullptr),
                                     ParseLean(nullptr, nullptr));
        const LeanCurve n = LeanAt(1.5f, 1.0f, 1.0f, false);
        Expect(view[RippleD + 3] == 1.0f && view[RippleD + 1] == 1.0f && view[RippleD] == n.bend &&
                   view[RippleC] == n.rest + n.bend && view[RippleC + 1] == n.along &&
                   view[RippleD + 2] == n.tree && view[RippleB + 3] == 1.0f &&
                   view[WindB + 3] == view[RippleA],
               "the lean's words at 1.5 m/s");
        Ripple still_ripple;
        double worst = 0.0;
        for (int i = 0; i < 300; ++i) {
            const auto still = LeanViewOf(c, Gusty(1.0 + 0.1 * i, 225.0f, 0.0f, 1.0f), still_ripple,
                                          ParseRipple(nullptr, nullptr), ParseLean(nullptr, "4"),
                                          MaxScale, BbWind::MaxGusts);
            const std::array<double, 3> p = {7.0 + 0.02 * i, 0.5 + 0.01 * i, 14.0 - 0.01 * i};
            const auto d = LeanMoveOf(still.data(), c, p, 0.5f, float(0.5 + 0.02 * i));
            worst = std::max(worst, std::fabs(d[0]) + std::fabs(d[1]) + std::fabs(d[2]));
        }
        Expect(worst == 0.0, "zero wind: nothing moves");
    }

    // Downwind only: the bend never points upwind, with the wave at 0 nothing moves across the
    // wind, and even BB_WIND_SWAY_WAVE=4 never swings a plant back past its rest; the wave's part
    // (the move with WAVE=1 minus the move with WAVE=0) stays within its bound at each speed.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        std::uint32_t seed = 4242u;
        const auto rnd = [&seed]() {
            seed = seed * 1664525u + 1013904223u;
            return double(seed >> 8) / 16777216.0;
        };
        const float speeds[4] = {0.5f, 1.5f, 3.0f, 4.0f};
        const RippleKnob fronts = ParseRipple(nullptr, nullptr);
        double low0 = 1.0, low4 = 1.0, across0 = 0.0;
        bool bounded = true;
        double wave15 = 0.0;
        for (int k = 0; k < 4; ++k) {
            Ripple r0, r1, r4;
            const LeanCurve n = LeanAt(speeds[k], 1.0f, 1.0f, false);
            const double bound =
                BbWind::GustMax * EnvScale * std::hypot(double(n.along), double(n.cross)) +
                BbWind::GustMax * double(n.leaf) * (LeafCalm + (1.0 - LeafCalm) * EnvScale) * 1.4143 +
                1e-4;
            double worst = 0.0;
            for (int i = 0; i < 1500; ++i) {
                const auto s = Gusty(0.2 * i, float(225.0 + 20.0 * std::sin(0.003 * i)), speeds[k],
                                     BbWind::MaxGusts);
                const auto v0 = LeanViewOf(c, s, r0, fronts, ParseLean(nullptr, "0"), 1.0f,
                                           BbWind::MaxGusts);
                const auto v1 = LeanViewOf(c, s, r1, fronts, ParseLean(nullptr, nullptr), 1.0f,
                                           BbWind::MaxGusts);
                const auto v4 = LeanViewOf(c, s, r4, fronts, ParseLean(nullptr, "4"), 1.0f,
                                           BbWind::MaxGusts);
                const std::array<double, 3> p = {10.0 - std::sin(0.3) * 6.0 + 6.0 * rnd() - 3.0,
                                                 0.5 + 2.5 * rnd(),
                                                 20.0 - std::cos(0.3) * 6.0 + 6.0 * rnd() - 3.0};
                const auto d0 = LeanMoveOf(v0.data(), c, p, 0.5f, 0.0f);
                const auto d1 = LeanMoveOf(v1.data(), c, p, 0.5f, 0.0f);
                const auto d4 = LeanMoveOf(v4.data(), c, p, 0.5f, 0.0f);
                low0 = std::min(low0, AlongOf(d0, s));
                low4 = std::min(low4, AlongOf(d4, s));
                across0 = std::max(across0, std::fabs(AcrossOf(d0, s)));
                worst = std::max(worst, std::hypot(d1[0] - d0[0], d1[2] - d0[2]));
            }
            bounded = bounded && worst <= bound;
            if (k == 1) {
                wave15 = worst;
            }
        }
        Expect(low0 > -5e-5, "BB_WIND_SWAY_WAVE=0: the bend never points upwind");
        Expect(across0 < 5e-5, "BB_WIND_SWAY_WAVE=0: nothing moves across the wind");
        Expect(low4 > -5e-5, "BB_WIND_SWAY_WAVE=4: never back past the rest");
        Expect(bounded, "the wave's part stays within its bound at 0.5, 1.5, 3 and 4 m/s");
        Expect(wave15 < 0.0115, "at 1.5 m/s the wave's part stays at about 1 cm (strongest gusts)");
    }

    // Trees: a mesh 6 m tall barely moves at 1.5 m/s (its lower half not at all) and moves as a
    // bush's top at 4 m/s; a 1.5 m bush is a bush.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        const std::array<double, 3> top = {10.0 - std::sin(0.3) * 7.0, 6.5,
                                           20.0 - std::cos(0.3) * 7.0};
        const std::array<double, 3> trunk = {top[0], 2.5, top[2]};
        const std::array<double, 3> bush_top = {top[0], 1.8, top[2]};
        const auto worst_of = [&](float speed, float crown, const std::array<double, 3>& p) {
            Ripple ripple;
            double worst = 0.0;
            for (int i = 0; i < 1200; ++i) {
                const auto view =
                    LeanViewOf(c, Gusty(0.1 * i, 225.0f, speed, BbWind::DefaultGusts), ripple,
                               ParseRipple(nullptr, nullptr), ParseLean(nullptr, nullptr));
                worst = std::max(worst, Length(LeanMoveOf(view.data(), c, p, 0.5f, crown)));
            }
            return worst;
        };
        const double tree15 = worst_of(1.5f, 6.5f, top), bush15 = worst_of(1.5f, 0.0f, top);
        const double tree4 = worst_of(4.0f, 6.5f, top), bush4 = worst_of(4.0f, 0.0f, top);
        Expect(tree15 < 0.008 && tree15 < 0.1 * bush15 && bush15 > 0.02,
               "a tree's top at 1.5 m/s: under 8 mm, under a tenth of a bush's");
        Expect(Near(tree4, bush4, 1e-4) && tree4 > 0.2, "a tree's top at 4 m/s moves as a bush's");
        Expect(worst_of(4.0f, 6.5f, trunk) < 1e-6, "a tree's lower half stays still");
        Expect(Near(worst_of(1.5f, 2.0f, bush_top), worst_of(1.5f, 0.0f, bush_top), 1e-9),
               "a bush 1.5 m tall sways as a bush");
    }

    // Faster wind, larger bend (at a point over 2 minutes, gusts 0); a front comes in faster than
    // it goes; the fronts travel downwind (with the skew); BB_WIND_SWAY_RIPPLE=0: in step.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        const std::array<double, 3> p = {10.0 - std::sin(0.3) * 6.0, 1.8, 20.0 - std::cos(0.3) * 6.0};
        double last = 0.0;
        bool larger = true;
        const float list[4] = {0.5f, 1.5f, 3.0f, 4.0f};
        for (const float speed : list) {
            Ripple ripple;
            double most = 0.0;
            for (int i = 0; i < 1200; ++i) {
                const auto view = LeanViewOf(c, Wind(0.1 * i, 225.0f, speed), ripple,
                                             ParseRipple(nullptr, nullptr),
                                             ParseLean(nullptr, nullptr), 1.0f, 0.0f);
                most = std::max(most, Length(LeanMoveOf(view.data(), c, p, 0.5f, 0.0f)));
            }
            larger = larger && most > last;
            last = most;
        }
        Expect(larger, "the faster the wind, the larger the bend");
        Ripple ripple;
        int rising = 0, falling = 0;
        float before = 0.0f;
        for (int i = 0; i <= 6000; ++i) {
            const auto view = LeanViewOf(c, Wind(0.05 * i, 225.0f, 1.5f), ripple,
                                         ParseRipple(nullptr, nullptr), ParseLean(nullptr, nullptr));
            const float e = Envelope(view.data(), 3.0f, -2.0f);
            if (i > 0 && e > before + 1e-4f) {
                ++rising;
            } else if (i > 0 && e < before - 1e-4f) {
                ++falling;
            }
            before = e;
        }
        Expect(rising * 10 < falling * 8, "a front comes in faster than it goes");
        Ripple travel;
        const RippleKnob on = ParseRipple(nullptr, nullptr);
        const auto first =
            LeanViewOf(c, Wind(100.0, 200.0f, 1.5f), travel, on, ParseLean(nullptr, nullptr));
        std::array<float, ViewWords> later{};
        double t = 100.0;
        for (int f = 0; f < 30; ++f) {
            t += 1.0 / 60.0;
            later = LeanViewOf(c, Wind(t, 200.0f, 1.5f), travel, on, ParseLean(nullptr, nullptr));
        }
        const double shift = 1.5 * (t - 100.0);
        double same = 0.0;
        for (int i = 0; i <= 80; ++i) {
            const float s = float(-20.0 + 0.5 * i);
            same = std::max(same, double(std::fabs(Envelope(later.data(), s, 1.3f) -
                                                   Envelope(first.data(), float(s - shift), 1.3f))));
        }
        Expect(same < 2e-3, "the lean's fronts move downwind at the wind's speed");
        Ripple in_step;
        const auto view = LeanViewOf(c, Wind(40.0, 225.0f, 1.5f), in_step,
                                     ParseRipple("0", nullptr), ParseLean(nullptr, nullptr));
        double spread = 0.0;
        for (int i = 0; i <= 40; ++i) {
            spread = std::max(spread, double(std::fabs(Envelope(view.data(), float(i - 20), float(20 - i)) -
                                                       Envelope(view.data(), 0.0f, 0.0f))));
        }
        Expect(spread < 1e-6, "BB_WIND_SWAY_RIPPLE=0 with the lean: every plant in step");
    }

    // A wind turning 2 deg/s, 3900 m from the world's origin: no jump with the lean either; its
    // strongest stays within the limits.
    {
        const auto largest_step = [](double turn, double base) {
            const std::array<double, 3> eye = {3000.0, 10.0, -2500.0};
            const auto c = Constants(0.4, -0.1, eye);
            Ripple ripple;
            const std::array<double, 3> p = {eye[0] - std::sin(0.4) * 8.0, 9.0,
                                             eye[2] - std::cos(0.4) * 8.0};
            std::array<double, 3> last{};
            double worst = 0.0;
            for (int f = 1; f <= 1200; ++f) {
                const double t = 10.0 + f / 60.0;
                const auto view = LeanViewOf(c, Wind(t, float(base + turn * (t - 10.0)), 3.0f),
                                             ripple, ParseRipple(nullptr, nullptr),
                                             ParseLean(nullptr, nullptr));
                const auto d = LeanMoveOf(view.data(), c, p, 7.5f, 0.0f);
                if (f > 1) {
                    worst = std::max(worst, std::hypot(d[0] - last[0], d[2] - last[2]));
                }
                last = d;
            }
            return worst;
        };
        // the steady wind's largest step at the directions the turning one passes (its largest
        // step over 20 s varies by itself with the direction)
        double steady = 0.0;
        for (int i = 0; i <= 4; ++i) {
            steady = std::max(steady, largest_step(0.0, 225.0 + 10.0 * i));
        }
        const double turning = largest_step(2.0, 225.0);
        Expect(steady > 1e-4 && turning <= 1.5 * steady + 1e-4, "the lean: a turning wind, no jump");
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        std::uint32_t seed = 99u;
        const auto rnd = [&seed]() {
            seed = seed * 1664525u + 1013904223u;
            return double(seed >> 8) / 16777216.0;
        };
        double worst = 0.0, dip = 0.0;
        for (int i = 0; i < 2000; ++i) {
            auto s = Wind(0.37 * i, float(225.0 + 40.0 * std::sin(0.01 * i)), BbWind::MaxSpeed);
            s.gust = BbWind::GustMax;
            const auto view = LeanViewOf(c, s, ripple, ParseRipple("4", "1"), ParseLean(nullptr, "4"),
                                         MaxScale, BbWind::MaxGusts);
            const std::array<double, 3> p = {10.0 - std::sin(0.3) * 6.0 + 6.0 * rnd() - 3.0,
                                             0.5 + 3.0 * rnd(),
                                             20.0 - std::cos(0.3) * 6.0 + 6.0 * rnd() - 3.0};
            const auto d = LeanMoveOf(view.data(), c, p, 0.5f, 0.0f);
            worst = std::max(worst, Length(d));
            dip = std::max(dip, -d[1]);
        }
        Expect(worst <= std::hypot(double(MaxAlong), double(MaxCross)) +
                            std::hypot(double(MaxLeaf), double(MaxLeaf)) + 3e-3 &&
                   worst > 0.3 && dip <= double(MaxAlong) + 3e-3 && dip > 0.01,
               "the strongest lean stays within its limits and dips");
    }

    // The crown keys: their order, back to a height, and the key a vertex offers.
    {
        Expect(CrownKey(3.0f) < CrownKey(2.0f) && CrownKey(-5.0f) > CrownKey(-4.0f) &&
                   CrownKey(-FiniteMost) < ResetKey && CrownKey(FiniteMost) < ResetKey,
               "CrownKey: higher is smaller, below ResetKey");
        bool back = true;
        const float heights[6] = {-120.5f, -1.0f, 0.0f, 0.25f, 7.0f, 300.0f};
        for (const float y : heights) {
            back = back && std::fabs(KeyCrown(CrownKey(y)) - y) < 2e-3f;
        }
        Expect(back, "KeyCrown undoes CrownKey");
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const auto view = LeanViewOf(c, Wind(5.0, 225.0f, 1.5f), ripple,
                                     ParseRipple(nullptr, nullptr), ParseLean(nullptr, nullptr));
        const auto clip = ClipOf(c, {10.0 - std::sin(0.3) * 6.0, 2.0, 20.0 - std::cos(0.3) * 6.0});
        std::uint32_t key = 0, key_crown = 0;
        (void)Displace(view.data(), clip, HeightKey(0.5f), 1.0f, &key, ResetKey, &key_crown);
        Expect(std::fabs(KeyCrown(key_crown) - 2.0f) < 2e-3f && std::fabs(KeyHeight(key) - 2.0f) < 2e-3f,
               "a vertex offers its height to the base and crown keys");
        Expect(PlantSlots * 2 == BaseSlots && CrownAt + PlantSlots == RegionWords,
               "the crown keys are the base keys' second half");
    }

    // The lean's log texts.
    {
        char text[512];
        LeanOnceText(ParseLean(nullptr, nullptr), ParseRipple(nullptr, nullptr), 1.0f, text,
                     sizeof(text));
        Expect(std::strncmp(text, "Wind sway lean (r89c, BB_WIND_SWAY_WAVE=1.00, RIPPLE=1.00)", 59) ==
                       0 &&
                   std::strlen(text) < 300,
               "the lean's once line, under 300 characters");
        LeanOnceText(ParseLean(nullptr, "4"), ParseRipple("4", "1"), MaxScale, text, sizeof(text));
        Expect(std::strlen(text) < 300, "the lean's once line at the strongest, under 300 characters");
        LeanTableText(ParseLean(nullptr, nullptr), ParseRipple(nullptr, nullptr), 1.0f, text,
                      sizeof(text));
        Expect(std::strncmp(text, "Wind sway lean (r89c) at 0.5/1.5/3.0/4.0 m/s: tip bend up to", 61) ==
                       0 &&
                   std::strlen(text) < 300,
               "the lean's numbers, under 300 characters");
        LeanTableText(ParseLean(nullptr, "4"), ParseRipple("4", "1"), MaxScale, text, sizeof(text));
        Expect(std::strlen(text) < 300, "the lean's numbers at the strongest, under 300 characters");
        LeanText(ParseLean(nullptr, nullptr), ParseRipple(nullptr, nullptr), Wind(10.0, 231.0f, 1.5f),
                 1.0f, 7, text, sizeof(text));
        Expect(std::strstr(text, "lean wave 1.00 (fronts 9.0 m apart, 1.50 m/s toward 231 deg") !=
                       nullptr &&
                   std::strstr(text, "7 views)") != nullptr,
               "the line's lean state");
        LeanText(ParseLean(nullptr, nullptr), ParseRipple("0", nullptr), Wind(10.0, 231.0f, 1.5f),
                 1.0f, 7, text, sizeof(text));
        Expect(std::strstr(text, "fronts in step") != nullptr, "the line's lean state, in step");
    }

    // bbport (r89d_tree-twigs): the knobs, the layout, the sway word's bit and the saved versions.
    {
        namespace T = BbWindTwigs;
        const T::Knob def = T::ParseKnob(nullptr, nullptr, true, true);
        Expect(def.on && def.asked && def.twigs == 1.0f && def.reach == 1,
               "BB_WIND_TWIGS unset: on at 1, reach 1");
        Expect(!T::ParseKnob("0", nullptr, true, true).on &&
                   !T::ParseKnob("0", nullptr, true, true).asked,
               "BB_WIND_TWIGS=0: off (trees as r89c)");
        Expect(T::ParseKnob("9", nullptr, true, true).twigs == T::TwigsMax &&
                   T::ParseKnob("-1", nullptr, true, true).twigs == 0.0f &&
                   T::ParseKnob("abc", nullptr, true, true).twigs == 1.0f &&
                   T::ParseKnob("2.5", nullptr, true, true).twigs == 2.5f,
               "BB_WIND_TWIGS: 0-4, unreadable 1");
        Expect(!T::ParseKnob(nullptr, nullptr, false, true).on &&
                   !T::ParseKnob(nullptr, nullptr, true, false).on,
               "the twigs need the sway and its lean");
        Expect(T::ParseKnob(nullptr, "0", true, true).reach == 0 &&
                   T::ParseKnob(nullptr, "1", true, true).reach == 1 &&
                   T::ParseKnob(nullptr, "2", true, true).reach == 2 &&
                   T::ParseKnob(nullptr, "x", true, true).reach == 1,
               "BB_WIND_TWIGS_REACH 0, 1, 2; unreadable 1");
        Expect(T::TwigAt >= 4096 + 8 + 64 * 64 && T::TwigEnd == T::TwigAt + BaseSlots * 4 &&
                   T::TwigBytes == T::TwigEnd * 4,
               "the box keys lie behind r117's field block");
        const std::uint32_t word = T::TreeWord(3, 1, 511, 200);
        const Unpacked u = Unpack(word);
        Expect(T::IsTreeWord(word) && u.on && u.frame_slot == 3 && u.view == 1 &&
                   u.base_slot == 511 && u.ramp == 200 && !T::IsTreeWord(PackWord(3, 1, 511, 200)),
               "TreeWord keeps PackWord's fields and adds TreeBit");
        Expect(T::KnownVersion(11, 11, 21, 1000) && T::KnownVersion(2011, 11, 21, 1000) &&
                   T::KnownVersion(3021, 11, 21, 1000) && T::KnownVersion(1021, 11, 21, 1000) &&
                   !T::KnownVersion(4011, 11, 21, 1000) && !T::KnownVersion(12, 11, 21, 1000),
               "the saved sway versions that are known");
        Expect(T::Gain(1.0f) == TwigRatio && T::Gain(4.0f) == TwigRatio * 4.0f && T::Gain(0.0f) == 0.0f &&
                   T::ParseTwigs(nullptr) == 1.0f && T::ParseTwigs("2") == 2.0f &&
                   T::ParseTwigs("9") == T::TwigsMax,
               "the gain is TwigRatio x BB_WIND_TWIGS; live values parse as the knob does");
    }

    // The twig weight: the trunk and the main limbs still, the outer upper parts in full, smooth.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const auto view = TwigViewOf(c, Wind(5.0, 225.0f, 1.5f), ripple, 1.0f);
        const float gain = view[RippleD + 2];
        const std::array<double, 3> mid = {10.0 - std::sin(0.3) * 7.0, 0.0, 20.0 - std::cos(0.3) * 7.0};
        const TreeBox tree = {0.5f, 10.5f, float(mid[0] - 4.0), float(mid[0] + 4.0),
                              float(mid[2] - 4.0), float(mid[2] + 4.0)};
        const TwigIn in = TwigInOf(tree, false);
        const auto weight = [&](double dx, double dz, double h) {
            return TwigWeight(view.data(), float(mid[0] + dx), float(mid[2] + dz), float(h), 10.0f,
                              in.keys);
        };
        Expect(weight(0.0, 0.0, 2.0) == 0.0f && weight(0.0, 0.0, 9.0) == 0.0f,
               "on the box's centre line: still at any height");
        Expect(weight(3.8, 0.0, 2.0) == 0.0f && weight(-3.8, 1.0, 1.5) == 0.0f,
               "low (the roots, the trunk's flare): still at any radius");
        Expect(std::fabs(weight(3.7, 0.0, 9.0) - gain) < 1e-6 &&
                   std::fabs(weight(0.0, -3.7, 9.0) - gain) < 1e-6,
               "outer and high: the full twig gain");
        Expect(weight(1.0, 0.0, 9.0) == 0.0f, "near the centre line (a main limb): still");
        bool rising = true, smooth = true;
        float last = 0.0f;
        for (int i = 0; i <= 400; ++i) { // outward at h = 9 m, 1 cm steps
            const float w = weight(0.01 * i, 0.0, 9.0);
            rising = rising && w >= last - 1e-9f;
            smooth = smooth && std::fabs(w - last) < 0.03f * gain;
            last = w;
        }
        last = 0.0f;
        for (int i = 0; i <= 1000; ++i) { // upward at r = 3.7 m, 1 cm steps
            const float w = weight(3.7, 0.0, 0.01 * i);
            rising = rising && w >= last - 1e-9f;
            smooth = smooth && std::fabs(w - last) < 0.03f * gain;
            last = w;
        }
        Expect(rising, "the twig weight grows with the radius and the height");
        Expect(smooth, "neighbouring vertices (1 cm apart) have neighbouring weights");
        // a mesh with no box yet or a thin one: finite, and a box under 1 m wide counts as 1 m
        const TwigIn none{};
        Expect(std::isfinite(TwigWeight(view.data(), 10.0f, 20.0f, 9.0f, 10.0f, none.keys)),
               "no box keys yet: a finite weight");
        const TreeBox thin = {0.5f, 10.5f, float(mid[0] - 0.05), float(mid[0] + 0.05),
                              float(mid[2] - 0.05), float(mid[2] + 0.05)};
        const TwigIn thin_in = TwigInOf(thin, false);
        Expect(TwigWeight(view.data(), float(mid[0] + 0.1), float(mid[2]), 9.0f, 10.0f, thin_in.keys) == 0.0f,
               "a thin box: the half width is held to 0.5 m");
    }

    // The twigs move by TwigRatio of a bush's lean: a tip at 1.5 m/s at most about 3 cm, at 4 m/s
    // about 9 cm (10 at a gust factor of 1.1); the trunk does not move.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        const std::array<double, 3> mid = {10.0 - std::sin(0.3) * 7.0, 0.0, 20.0 - std::cos(0.3) * 7.0};
        const TreeBox tree = {0.5f, 10.5f, float(mid[0] - 4.0), float(mid[0] + 4.0),
                              float(mid[2] - 4.0), float(mid[2] + 4.0)};
        const std::array<double, 3> tip = {mid[0] + 3.7, 9.5, mid[2]};
        const std::array<double, 3> trunk = {mid[0], 5.0, mid[2]};
        double peak15 = 0.0, peak4 = 0.0, trunk_move = 0.0;
        for (int k = 0; k < 2; ++k) {
            const float speed = k == 0 ? 1.5f : 4.0f;
            double& peak = k == 0 ? peak15 : peak4;
            Ripple ripple;
            for (int i = 0; i < 1500; ++i) {
                const auto view = TwigViewOf(c, Gusty(0.1 * i, 225.0f, speed, 0.5f), ripple, 1.0f);
                const auto d = TwigMoveOf(view.data(), c, tip, tree);
                peak = std::max(peak, std::hypot(d[0], d[2]));
                trunk_move = std::max(trunk_move, Length(TwigMoveOf(view.data(), c, trunk, tree)));
            }
        }
        // the analytic bound at 1.5 m/s (no leaves): gust factor GustMax, front EnvScale, the wave
        // at its crest, the twig weight TwigRatio at a tip (gain 0.3 x BB_WIND_TWIGS 1)
        const LeanCurve n15 = LeanAt(1.5f, 1.0f, 1.0f, false);
        const double along15 = double(BbWind::GustMax) *
                               (double(n15.rest) + double(n15.bend) +
                                double(n15.bend) * (double(EnvScale) - 1.0) +
                                double(n15.along) * double(EnvScale));
        const double cross15 = double(BbWind::GustMax) * double(n15.cross) * double(EnvScale);
        const double bound15 = double(TwigRatio) * std::hypot(along15, cross15) * 1.02;
        Expect(peak15 > 0.003 && peak15 < 0.03 && peak15 < bound15 + 1e-4,
               "a twig tip at 1.5 m/s: between 0.3 and 3 cm");
        Expect(peak4 > 0.03 && peak4 < 0.14, "a twig tip at 4 m/s: between 3 and 14 cm");
        Expect(peak4 > 2.5 * peak15 && peak4 < 20.0 * peak15,
               "the stronger wind moves the twigs several times as far");
        Expect(trunk_move < 1e-9, "the trunk does not move");
        const BbWindTwigs::Tip d15 = BbWindTwigs::TipAt(1.5f, 1.0f, 1.0f, 1.0f, false);
        const BbWindTwigs::Tip d4 = BbWindTwigs::TipAt(4.0f, 1.0f, 1.0f, 1.0f, false);
        Expect(Near(d15.lean, 0.0063, 2e-4) && Near(d15.front, 0.0129, 3e-4) &&
                   Near(d4.lean, 0.045, 1e-4) && Near(d4.front, 0.0918, 3e-4),
               "TipAt: 0.6/1.3 cm at 1.5 m/s and 4.5/9.2 cm at 4 m/s");
        Expect(BbWindTwigs::TipAt(0.0f, 1.0f, 1.0f, 1.0f, false).front == 0.0f,
               "no wind: no twig move");
    }

    // The twigs change nothing for a bush (tau 0), nothing without them (twig null), and a mesh
    // that may only be a tree (TreeBit) has no bush weight.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        const std::array<double, 3> mid = {10.0 - std::sin(0.3) * 7.0, 0.0, 20.0 - std::cos(0.3) * 7.0};
        const TreeBox bush = {0.5f, 2.0f, float(mid[0] - 1.0), float(mid[0] + 1.0), float(mid[2] - 1.0),
                              float(mid[2] + 1.0)};
        const TreeBox tree = {0.5f, 10.5f, float(mid[0] - 4.0), float(mid[0] + 4.0),
                              float(mid[2] - 4.0), float(mid[2] + 4.0)};
        const TreeBox prop = {0.5f, 1.7f, float(mid[0] - 1.0), float(mid[0] + 1.0), float(mid[2] - 1.0),
                              float(mid[2] + 1.0)};
        Ripple ripple;
        double bush_diff = 0.0, off_diff = 0.0, tree_only_diff = 0.0, prop_only = 0.0;
        for (int i = 0; i < 600; ++i) {
            const auto view = TwigViewOf(c, Gusty(0.2 * i, 225.0f, 3.0f, 0.5f), ripple, 1.0f);
            const std::array<double, 3> p = {mid[0] + 0.9, 1.4, mid[2] - 0.2};
            const auto with = TwigMoveOf(view.data(), c, p, bush);
            const auto without = TwigMoveOf(view.data(), c, p, bush, false, false);
            bush_diff = std::max(bush_diff, Length({with[0] - without[0], with[1] - without[1],
                                                    with[2] - without[2]}));
            const std::array<double, 3> q = {mid[0] + 3.7, 9.5, mid[2]};
            const auto a = TwigMoveOf(view.data(), c, q, tree, false);
            const auto b = TwigMoveOf(view.data(), c, q, tree, true);
            tree_only_diff = std::max(tree_only_diff,
                                      Length({a[0] - b[0], a[1] - b[1], a[2] - b[2]}));
            prop_only = std::max(prop_only, Length(TwigMoveOf(view.data(), c, p, prop, true)));
            const auto plain = TwigMoveOf(view.data(), c, p, bush, false, false);
            const auto old = LeanMoveOf(view.data(), c, p, 0.5f, 2.0f);
            off_diff = std::max(off_diff, Length({plain[0] - old[0], plain[1] - old[1], plain[2] - old[2]}));
        }
        Expect(bush_diff == 0.0, "a bush (mesh under 2 m) moves as before with the twigs on");
        Expect(off_diff == 0.0, "twig null: Displace is r89c's (the old path, bit for bit)");
        Expect(tree_only_diff < 1e-6, "a tall tree-only mesh moves as a tree: no bush weight to lose");
        Expect(prop_only == 0.0, "a short mesh that may only be a tree does not move");
    }

    // The keys a vertex offers the box.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const auto view = TwigViewOf(c, Wind(5.0, 225.0f, 1.5f), ripple, 1.0f);
        const std::array<double, 3> p = {10.0 - std::sin(0.3) * 6.0 + 1.25, 2.0, 20.0 - std::cos(0.3) * 6.0 - 0.75};
        const auto clip = ClipOf(c, p);
        const TwigIn in{};
        std::array<std::uint32_t, 4> offered{};
        (void)Displace(view.data(), clip, HeightKey(0.5f), 1.0f, nullptr, ResetKey, nullptr, &in,
                       &offered);
        Expect(Near(KeyHeight(offered[0]), p[0], 3e-3) && Near(KeyCrown(offered[1]), p[0], 3e-3) &&
                   Near(KeyHeight(offered[2]), p[2], 3e-3) && Near(KeyCrown(offered[3]), p[2], 3e-3),
               "a vertex offers its world x and z to the box keys");
        Expect(offered[0] < ResetKey && offered[1] < ResetKey && offered[2] < ResetKey &&
                   offered[3] < ResetKey,
               "the offered keys lie below ResetKey");
    }

    // The CPU's judgement of a sun-drawn stream (Book, Judge) and the key words.
    {
        namespace T = BbWindTwigs;
        std::vector<std::uint32_t> words(T::TwigEnd, 0u);
        const auto set = [&](std::uint32_t slot, float base, float crown, float x0, float x1, float z0,
                             float z1) {
            words[BaseAt + slot] = HeightKey(base);
            words[CrownAt + slot] = CrownKey(crown);
            words[T::TwigAt + slot * 4 + 0] = HeightKey(x0);
            words[T::TwigAt + slot * 4 + 1] = CrownKey(x1);
            words[T::TwigAt + slot * 4 + 2] = HeightKey(z0);
            words[T::TwigAt + slot * 4 + 3] = CrownKey(z1);
        };
        const auto none = [&](std::uint32_t slot) {
            words[BaseAt + slot] = ResetKey;
            words[CrownAt + slot] = ResetKey;
            for (std::uint32_t i = 0; i < T::TwigSlotWords; ++i) {
                words[T::TwigAt + slot * T::TwigSlotWords + i] = ResetKey;
            }
        };
        T::Book book;
        // a still tall mesh: waiting for 8 + 60 frames (the first read at frame 108), then a tree
        set(5, 0.5f, 10.5f, 20.0f, 28.0f, 40.0f, 46.0f);
        T::Entry& tree = book.Touch(0xa000, 4096, 5, true, 100);
        bool waiting = true;
        for (std::uint64_t f = 100; f < 168; ++f) {
            tree.seen = f;
            waiting = waiting && T::Judge(tree, words.data(), f) == T::Verdict::Waiting;
        }
        Expect(waiting && tree.snapped && tree.snap_at == 108, "judging: waits, first read at frame 108");
        Expect(T::Judge(tree, words.data(), 168) == T::Verdict::Tree && Near(tree.height, 10.0, 2e-3),
               "a still mesh 10 m tall is a tree");
        // a prop 1.2 m tall, still: not a tree
        set(6, 0.5f, 1.7f, 20.0f, 21.0f, 40.0f, 41.0f);
        T::Entry& prop = book.Touch(0xa100, 512, 6, true, 100);
        (void)T::Judge(prop, words.data(), 108);
        Expect(T::Judge(prop, words.data(), 168) == T::Verdict::NotTree, "a 1.2 m mesh is not a tree");
        // a walking character 3.4 m tall (a giant): its box moves 2 m in a second: not a tree
        set(7, 0.5f, 3.9f, 20.0f, 21.0f, 40.0f, 41.0f);
        T::Entry& walker = book.Touch(0xa200, 512, 7, true, 100);
        (void)T::Judge(walker, words.data(), 108);
        set(7, 0.5f, 3.9f, 22.0f, 23.0f, 40.0f, 41.0f);
        Expect(T::Judge(walker, words.data(), 168) == T::Verdict::NotTree, "a mesh whose box moves is not a tree");
        // a mesh whose keys were never offered: waits, then gives up
        none(8);
        T::Entry& unseen = book.Touch(0xa300, 512, 8, true, 100);
        Expect(T::Judge(unseen, words.data(), 120) == T::Verdict::Waiting &&
                   T::Judge(unseen, words.data(), 100 + T::GiveUpFrames) == T::Verdict::NotTree,
               "keys never offered: waiting, then not a tree");
        // a verdict stays until the slot, the size or the keys change
        T::Entry& again = book.Touch(0xa000, 4096, 5, false, 200);
        Expect(again.verdict == T::Verdict::Tree, "a verdict stays");
        T::Entry& reset = book.Touch(0xa000, 4096, 5, true, 300);
        Expect(reset.verdict == T::Verdict::Waiting && reset.first == 300 && !reset.snapped,
               "a reset slot is judged again");
        T::Entry& resized = book.Touch(0xa000, 8192, 5, false, 301);
        Expect(resized.size == 8192 && resized.verdict == T::Verdict::Waiting, "another size: again");
        Expect(book.Find(0xa000) != nullptr && book.Find(0xdead) == nullptr, "Find");
        // a tree's ramp starts at the verdict, in wind time (and never above the slot's own ramp)
        T::Entry fresh;
        Expect(T::TreeRamp(fresh, 100.0, 255) == 0 && T::TreeRamp(fresh, 100.5, 255) >= 126 &&
                   T::TreeRamp(fresh, 100.5, 255) <= 129 && T::TreeRamp(fresh, 101.0, 255) == 255 &&
                   T::TreeRamp(fresh, 105.0, 50) == 50,
               "TreeRamp: from 0 at the verdict to 255 in 1 s, held to the slot's ramp");
        // the keys' reading and the measure
        const T::Keys keys = T::ReadKeys(words.data(), 5);
        const T::Measure m = T::MeasureOf(keys);
        Expect(m.ok && Near(m.base, 0.5, 2e-3) && Near(m.crown, 10.5, 2e-3) && Near(m.x_lo, 20.0, 2e-3) &&
                   Near(m.x_hi, 28.0, 2e-3) && Near(m.z_lo, 40.0, 2e-3) && Near(m.z_hi, 46.0, 2e-3),
               "ReadKeys and MeasureOf give back the box");
        Expect(!T::MeasureOf(T::Keys{}).ok, "keys at ResetKey: no measure");
    }

    // bbport (r89e_twigs-big-trees): the static cut-out rule, the far share, the slot release, the knob.
    {
        namespace T = BbWindTwigs;
        const auto meas = [](float base, float crown, float x0, float x1, float z0, float z1) {
            T::Measure m;
            m.base = base;
            m.crown = crown;
            m.x_lo = x0;
            m.x_hi = x1;
            m.z_lo = z0;
            m.z_hi = z1;
            m.ok = true;
            return m;
        };
        const auto is = [](const char* got, const char* want) {
            return got != nullptr && std::strcmp(got, want) == 0;
        };
        Expect(T::SmallWhy(meas(0, 10, 0, 6, 0, 6), 0.0f, 1, false) == nullptr,
               "a still bare tree 10 m tall, 6 x 6 m, one draw a frame: a tree");
        Expect(T::SmallWhy(meas(0, 25, 0, 14, 0, 12), 0.1f, 2, false) == nullptr,
               "a 25 m tree with two draws a frame: a tree");
        Expect(is(T::SmallWhy(meas(0, 10, 0, 6, 0, 6), 0.5f, 1, false), "moved"), "a box that moved: no");
        Expect(is(T::SmallWhy(meas(0, 3, 0, 3, 0, 3), 0.0f, 1, false), "short"), "a 3 m fence post: short");
        Expect(is(T::SmallWhy(meas(0, 171.4f, 0, 60, 0, 60), 0.0f, 1, false), "tall"), "171 m: tall");
        Expect(is(T::SmallWhy(meas(0, 12, 0, 40, 0, 0.5f), 0.0f, 1, false), "wide"), "a long wall 12 m: wide");
        Expect(is(T::SmallWhy(meas(0, 6, 0, 5, 0, 0.4f), 0.0f, 1, false), "thin"), "a flat panel: thin");
        Expect(is(T::SmallWhy(meas(0, 12, 0, 1, 0, 1), 0.0f, 1, false), "slim"), "a lamp post: slim");
        Expect(is(T::SmallWhy(meas(0, 10, 0, 6, 0, 6), 0.0f, 3, false), "instanced"), "3 draws a frame: instanced");
        Expect(is(T::SmallWhy(meas(0, 10, 0, 100, 0, 6), 0.0f, 1, false), "box"), "a box over 80 m: box");
        Expect(T::SmallWhy(meas(0, 6, 0, 5, 0, 0.4f), 0.0f, 3, true) == nullptr &&
                   is(T::SmallWhy(meas(0, 3, 0, 5, 0, 5), 0.0f, 1, true), "short") &&
                   is(T::SmallWhy(meas(0, 60, 0, 5, 0, 5), 0.0f, 1, true), "tall") &&
                   is(T::SmallWhy(meas(0, 6, 0, 5, 0, 5), 0.9f, 1, true), "moved"),
               "the loose rule keeps the height and the still checks only");
        Expect(is(T::SmallPrefilter(60), "verts-few") && T::SmallPrefilter(120) == nullptr &&
                   is(T::SmallPrefilter(300000), "verts-many"),
               "SmallPrefilter");
        // the Book: Judge uses SmallWhy for a small entry; a refusal has no slot
        {
            std::vector<std::uint32_t> words(T::TwigEnd, 0u);
            words[BaseAt + 9] = HeightKey(0.5f);
            words[CrownAt + 9] = CrownKey(10.5f);
            words[T::TwigAt + 9 * 4 + 0] = HeightKey(20.0f);
            words[T::TwigAt + 9 * 4 + 1] = CrownKey(26.0f);
            words[T::TwigAt + 9 * 4 + 2] = HeightKey(40.0f);
            words[T::TwigAt + 9 * 4 + 3] = CrownKey(46.0f);
            T::Book book;
            T::Entry& e = book.Touch(0xb000, 4096, 9, true, 100);
            e.small = true;
            Expect(book.LiveSmall(100) == 1u, "LiveSmall counts the measured candidate");
            (void)T::Judge(e, words.data(), 108);
            Expect(T::Judge(e, words.data(), 168) == T::Verdict::Tree && e.why == nullptr && e.last.ok,
                   "a small candidate: still, 10 m, 6 x 6: a tree");
            T::Entry& r = book.Refuse(0xb100, 2048, 100, "verts-few");
            Expect(r.small && r.verdict == T::Verdict::NotTree && r.slot == 0xffffffffu &&
                       book.Find(0xb100) != nullptr,
                   "Refuse: an entry with no slot");
            T::SmallInfo info;
            info.verts = 5000;
            (void)book.SetInfo(0xb000, info);
            Expect(book.FindInfo(0xb000) != nullptr && book.FindInfo(0xb000)->verts == 5000 &&
                       book.FindInfo(0xdead) == nullptr,
                   "SetInfo and FindInfo");
        }
        // the far share: a trunk with a ring of limbs far from the axis (local y up)
        {
            std::vector<float> trunk;
            for (int i = 0; i < 300; ++i) { // near the axis, spread in height
                trunk.insert(trunk.end(), {0.05f * float(i % 3), float(i) * 0.03f, 0.05f * float(i % 2), 0.0f});
            }
            for (int i = 0; i < 100; ++i) { // limbs: 2 m out at the top
                const float a = float(i) * 0.0628f;
                trunk.insert(trunk.end(), {2.0f * std::cos(a), 8.0f + 0.01f * float(i), 2.0f * std::sin(a), 0.0f});
            }
            const float share = T::FarShare(reinterpret_cast<const unsigned char*>(trunk.data()), 16, 400);
            Expect(share > 0.2f && share < 0.3f, "FarShare: 100 of 400 vertices far from the axis");
            Expect(T::FarShare(nullptr, 16, 400) == -1.0f && T::FarShare(reinterpret_cast<const unsigned char*>(trunk.data()), 8, 400) == -1.0f &&
                       T::FarShare(reinterpret_cast<const unsigned char*>(trunk.data()), 16, 4) == -1.0f,
                   "FarShare: unreadable input gives -1");
        }
        // the knob: BB_WIND_TWIGS_SMALL 0 off, 1 the default, 2 log only, 3 loose
        Expect(T::ParseKnob(nullptr, nullptr, true, true).small == 1 &&
                   T::ParseKnob(nullptr, nullptr, true, true, "0").small == 0 &&
                   T::ParseKnob(nullptr, nullptr, true, true, "2").small == 2 &&
                   T::ParseKnob(nullptr, nullptr, true, true, "3").small == 3 &&
                   T::ParseKnob(nullptr, nullptr, true, true, "x").small == 1,
               "BB_WIND_TWIGS_SMALL: 0-3, unreadable 1");
        // the slot release: the slot rests (frames in flight still write its keys), the stream is gone
        {
            Slots slots;
            const auto a = slots.Take(0x1000, 64, 10, 0.0);
            slots.Release(0x1000);
            const auto b = slots.Take(0x2000, 64, 10, 0.0);
            const auto again = slots.Take(0x1000, 64, 11, 0.0);
            Expect(a.ok && b.ok && b.slot != a.slot && b.reset && again.ok && again.reset &&
                       again.slot != a.slot,
                   "Release: the slot rests, the stream is taken anew elsewhere");
            slots.Release(0x9999); // a stream with no slot: nothing
        }
        char line[400];
        T::Entry shown;
        shown.small = true;
        shown.verdict = T::Verdict::NotTree;
        shown.why = "wide";
        shown.last = meas(0, 12, 0, 40, 0, 0.5f);
        T::SmallInfo shown_info;
        shown_info.verts = 5400;
        shown_info.far_share = 0.62f;
        shown_info.palette = true;
        shown_info.draws = 120;
        shown_info.max_per_frame = 2;
        T::SmallLine(shown, &shown_info, line, sizeof(line));
        Expect(std::strstr(line, "candidate refused: height 12.0 m, box 40.0 x 0.5 m") != nullptr &&
                   std::strstr(line, "verts 5400, far 0.62, palette 1") != nullptr &&
                   std::strstr(line, "per frame 2, why wide") != nullptr && std::strlen(line) < 300,
               "SmallLine");
        T::Census census;
        census.small = 3;
        census.Huge(171.4f);
        T::Stats stats;
        stats.small_seen = 700;
        T::SmallReportText(census, stats, T::ParseKnob(nullptr, nullptr, true, true), line, sizeof(line));
        Expect(std::strstr(line, "meshes 3 tree, 0 judging; draws 700 seen") != nullptr &&
                   std::strstr(line, "over 40 m: 1 meshes (tallest 171.4 m)") != nullptr && std::strlen(line) < 320,
               "SmallReportText");
        T::SmallOnceText(T::ParseKnob(nullptr, nullptr, true, true), line, sizeof(line));
        Expect(std::strstr(line, "BB_WIND_TWIGS_SMALL=1") != nullptr && std::strlen(line) < 320, "SmallOnceText");
    }

    // bbport (r89f_twigs-scale): the size factor, the sized twig weight and tip, the knob, the versions, the texts.
    {
        namespace T = BbWindTwigs;
        Expect(Near(SizeFactor(0.0f), 1.0, 1e-6) && Near(SizeFactor(3.0f), 1.0, 1e-6) &&
                   Near(SizeFactor(6.0f), 1.0, 1e-5) && Near(SizeFactor(12.0f), 2.0, 1e-5) &&
                   Near(SizeFactor(37.0f), 37.0 / 6.0, 1e-4) && Near(SizeFactor(60.0f), double(SizeMax), 1e-6) &&
                   Near(SizeFactor(-5.0f), 1.0, 1e-6),
               "SizeFactor: 1 up to 6 m, h / 6 m above, held to 7");
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const auto view = TwigViewOf(c, Wind(5.0, 225.0f, 1.5f), ripple, 1.0f);
        const float gain = view[RippleD + 2];
        const std::array<double, 3> mid = {10.0 - std::sin(0.3) * 7.0, 0.0, 20.0 - std::cos(0.3) * 7.0};
        const TreeBox giant = {0.5f, 37.5f, float(mid[0] - 20.0), float(mid[0] + 20.0), float(mid[2] - 20.0),
                               float(mid[2] + 20.0)};
        const TwigIn giant_in = TwigInOf(giant, false);
        const float plain = TwigWeight(view.data(), float(mid[0] + 19.0), float(mid[2]), 33.0f, 37.0f, giant_in.keys);
        const float sized =
            TwigWeight(view.data(), float(mid[0] + 19.0), float(mid[2]), 33.0f, 37.0f, giant_in.keys, true);
        Expect(std::fabs(plain - gain) < 1e-6 && Near(sized, double(gain) * SizeFactor(33.0f), 1e-5),
               "a 37 m tree's outer upper vertex: the gain, and x h / 6 m with the size factor");
        Expect(TwigWeight(view.data(), float(mid[0]), float(mid[2]), 33.0f, 37.0f, giant_in.keys, true) == 0.0f &&
                   TwigWeight(view.data(), float(mid[0] + 19.0), float(mid[2]), 2.0f, 37.0f, giant_in.keys, true) ==
                       0.0f,
               "the size factor keeps the trunk and the low parts still (weight 0 stays 0)");
        // the tip's move over 60 s of gusts: the same at 6 m, 5.4 times as far on the 37 m tree
        const auto peak_of = [&](const TreeBox& b, const std::array<double, 3>& p, float speed, bool use_size) {
            double peak = 0.0;
            Ripple wind_ripple;
            for (int i = 0; i < 600; ++i) {
                const auto v = TwigViewOf(c, Gusty(0.1 * i, 225.0f, speed, 0.5f), wind_ripple, 1.0f);
                const auto clip = ClipOf(c, p);
                const auto before = WorldOf(v.data(), clip);
                TwigIn in = TwigInOf(b, false);
                in.sized = use_size;
                const auto after = WorldOf(v.data(), Displace(v.data(), clip, HeightKey(b.base), 1.0f, nullptr,
                                                              CrownKey(b.crown), nullptr, &in));
                peak = std::max(peak, std::hypot(after[0] - before[0], after[2] - before[2]));
            }
            return peak;
        };
        const TreeBox small_tree = {0.5f, 6.5f, float(mid[0] - 2.5), float(mid[0] + 2.5), float(mid[2] - 2.5),
                                    float(mid[2] + 2.5)};
        const std::array<double, 3> small_tip = {mid[0] + 2.4, 5.5, mid[2]};
        const std::array<double, 3> giant_tip = {mid[0] + 19.0, 33.0, mid[2]};
        const double small_plain = peak_of(small_tree, small_tip, 4.0f, false);
        const double small_sized = peak_of(small_tree, small_tip, 4.0f, true);
        const double giant_plain = peak_of(giant, giant_tip, 4.0f, false);
        const double giant_sized = peak_of(giant, giant_tip, 4.0f, true);
        const double giant_slow = peak_of(giant, giant_tip, 1.5f, true);
        const double scale_of_giant = double(SizeFactor(32.5f));
        Expect(small_plain > 0.0 && Near(small_sized, small_plain, 1e-9),
               "a 6 m tree's tip (5 m up): the size factor is 1, the move is r89e's");
        Expect(giant_plain > 0.0 && giant_sized > giant_plain * scale_of_giant * 0.9 &&
                   giant_sized < giant_plain * scale_of_giant * 1.1,
               "a 37 m tree's tip (32.5 m up) moves SizeFactor times as far as without it");
        Expect(giant_sized > 0.12 && giant_sized < 0.9, "a 37 m tree's tip at 4 m/s: a few tens of cm");
        Expect(giant_slow > 0.01 && giant_slow < 0.2 && giant_slow < 0.5 * giant_sized,
               "the same tip at 1.5 m/s: a few cm, much less than at 4 m/s");
        // the knob and the versions
        Expect(T::ParseKnob(nullptr, nullptr, true, true).size == 1 &&
                   T::ParseKnob(nullptr, nullptr, true, true, nullptr, "0").size == 0 &&
                   T::ParseKnob(nullptr, nullptr, true, true, nullptr, "1").size == 1 &&
                   T::ParseKnob(nullptr, nullptr, true, true, nullptr, "x").size == 1,
               "BB_WIND_TWIGS_SIZE: 0 or 1, unset or unreadable 1");
        Expect(T::KnownVersion(2111, 11, 21, 1000) && T::KnownVersion(3121, 11, 21, 1000) &&
                   T::KnownVersion(2011, 11, 21, 1000) && !T::KnownVersion(2211, 11, 21, 1000) &&
                   !T::KnownVersion(111, 11, 21, 1000) && T::SizeAdd == 100,
               "the saved versions with the size offset are known; no other");
        // the tip numbers and the texts
        const T::Tip base_tip = T::TipAt(4.0f, 1.0f, 1.0f, 1.0f, false);
        const T::Tip big_tip = T::TipSized(4.0f, 1.0f, 1.0f, 1.0f, 37.0f, true);
        const T::Tip none_tip = T::TipSized(4.0f, 1.0f, 1.0f, 1.0f, 37.0f, false);
        Expect(Near(big_tip.lean, double(base_tip.lean) * 37.0 / 6.0, 1e-4) &&
                   Near(big_tip.front, double(base_tip.front) * 37.0 / 6.0, 1e-4) &&
                   none_tip.lean == base_tip.lean && none_tip.front == base_tip.front,
               "TipSized: TipAt x h / 6 m (37 m), TipAt when not sized");
        char line[704];
        T::SizeOnceText(T::ParseKnob(nullptr, nullptr, true, true), 1.0f, 1.0f, line, sizeof(line));
        Expect(std::strstr(line, "BB_WIND_TWIGS_SIZE=1") != nullptr && std::strstr(line, "(37 m)") != nullptr &&
                   std::strstr(line, "at 4 m/s:") != nullptr && std::strlen(line) < 600,
               "SizeOnceText");
        T::Census census;
        census.Tall(37.3f);
        T::Stats stats;
        stats.small_tree = 40;
        stats.tree_draws = 2;
        T::SizeReportText(census, stats, Wind(5.0, 225.0f, 4.0f), T::ParseKnob(nullptr, nullptr, true, true), 1.0f,
                          1.0f, line, sizeof(line));
        Expect(std::strstr(line, "42 tree draws") != nullptr && std::strstr(line, "tallest 37.3 m") != nullptr &&
                   std::strlen(line) < 320,
               "SizeReportText");
    }

    // bbport (r89g_twigs-proof): the fit weight and its place in Displace, the knobs, the versions, the proof
    // counters, the verdicts and the texts.
    {
        namespace T = BbWindTwigs;
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const auto view = TwigViewOf(c, Wind(5.0, 225.0f, 1.5f), ripple, 1.0f);
        const float gain = view[RippleD + 2];
        Expect(FitWeight(view.data(), -5.0f) == 0.0f && FitWeight(view.data(), 0.0f) == 0.0f &&
                   FitWeight(view.data(), FitLo) == 0.0f && FitWeight(view.data(), FitLo, true) == 0.0f,
               "FitWeight: 0 up to FitLo m over the camera");
        Expect(Near(FitWeight(view.data(), FitHi), double(gain) * double(FitShare), 1e-6) &&
                   Near(FitWeight(view.data(), 40.0f), double(gain) * double(FitShare), 1e-6),
               "FitWeight: the gain x FitShare from FitHi m up, unsized");
        Expect(Near(FitWeight(view.data(), FitHi, true),
                    double(gain) * double(FitShare) * double(SizeFactor(FitHi + FitEye)), 1e-6) &&
                   Near(FitWeight(view.data(), 20.0f, true),
                        double(gain) * double(FitShare) * double(SizeFactor(20.0f + FitEye)), 1e-6),
               "FitWeight sized: x the size factor at hc + FitEye");
        bool rises = true;
        float last_weight = 0.0f;
        for (int i = 0; i <= 80; ++i) {
            const float w = FitWeight(view.data(), 0.5f * float(i), true);
            rises = rises && w >= last_weight;
            last_weight = w;
        }
        Expect(rises, "FitWeight sized never steps down as the height rises");
        // the cause: a stream whose box is a stand's (45 x 39 m, 37 m) gives r89f's box rule no weight on its centre
        // line, 14 m up (12 m over the camera); the fit rule moves that vertex
        const std::array<double, 3> mid = {10.0 - std::sin(0.3) * 7.0, 0.0, 20.0 - std::cos(0.3) * 7.0};
        const TreeBox stand = {0.0f, 37.0f, float(mid[0] - 22.5), float(mid[0] + 22.5), float(mid[2] - 19.5),
                               float(mid[2] + 19.5)};
        const std::array<double, 3> limb = {mid[0], 14.0, mid[2]};
        const auto peak_of = [&](bool use_fit) {
            double peak = 0.0;
            Ripple wind_ripple;
            for (int i = 0; i < 600; ++i) {
                const auto v = TwigViewOf(c, Gusty(0.1 * i, 225.0f, 4.0f, 0.5f), wind_ripple, 1.0f);
                const auto clip = ClipOf(c, limb);
                const auto before = WorldOf(v.data(), clip);
                TwigIn in = TwigInOf(stand, true);
                in.sized = true;
                in.fit = use_fit;
                const auto after = WorldOf(v.data(), Displace(v.data(), clip, HeightKey(stand.base), 1.0f, nullptr,
                                                              CrownKey(stand.crown), nullptr, &in));
                peak = std::max(peak, std::hypot(after[0] - before[0], after[2] - before[2]));
            }
            return peak;
        };
        const double box_peak = peak_of(false);
        const double fit_peak = peak_of(true);
        Expect(box_peak < 1e-6, "the box rule leaves a vertex on a stand's centre line still (the break)");
        Expect(fit_peak > 0.02 && fit_peak < 1.0, "the fit rule moves it by a few cm to tens of cm at 4 m/s");
        // the knobs and the versions
        const T::Knob dflt = T::ParseKnob(nullptr, nullptr, true, true);
        const T::Knob asked = T::ParseKnob(nullptr, nullptr, true, true, nullptr, nullptr, "0", "1");
        const T::Knob junk = T::ParseKnob(nullptr, nullptr, true, true, nullptr, nullptr, "x", "x");
        Expect(dflt.fit == 1 && !dflt.proof && asked.fit == 0 && asked.proof && junk.fit == 1 && !junk.proof,
               "BB_WIND_TWIGS_FIT: 0 or 1, default 1; BB_WIND_TWIGS_PROOF: default off");
        Expect(T::KnownVersion(2131, 11, 21, 1000) && T::KnownVersion(2141, 11, 21, 1000) &&
                   T::KnownVersion(2121, 11, 21, 1000) && T::KnownVersion(2031, 11, 21, 1000) &&
                   T::KnownVersion(3141, 11, 21, 1000) && !T::KnownVersion(2201, 11, 21, 1000) &&
                   T::FitAdd == 10 && T::ProofAdd == 20,
               "the saved versions with the fit and proof offsets are known; no other");
        // the counters, the verdicts, the line
        std::vector<std::uint32_t> words(T::LagEnd, 0u); // bbport (r89h): the change words are read too
        const std::uint32_t slot = 5;
        std::uint32_t* const at = words.data() + T::ProofAt + slot * T::ProofSlotWords;
        const auto bits = [](float v) {
            std::uint32_t u = 0;
            std::memcpy(&u, &v, sizeof(u));
            return u;
        };
        at[0] = 100; at[1] = 100; at[2] = 100; at[3] = 0; at[4] = 60; at[5] = 60; at[6] = 40; at[15] = 70;
        at[7] = bits(0.123f); at[8] = bits(0.3f); at[9] = bits(1.0f); at[10] = bits(1.0f);
        at[11] = bits(0.2f); at[12] = bits(18.5f); at[13] = bits(0.9f); at[14] = bits(0.4f);
        const T::ProofCounts pc = T::ReadProof(words.data(), slot);
        Expect(pc.verts == 100 && pc.fin == 100 && pc.tall == 100 && pc.old_w == 0 && pc.fit_w == 60 &&
                   pc.used_w == 60 && pc.moved == 40 && pc.high == 70 && Near(pc.move_max, 0.123, 1e-6) &&
                   Near(pc.gain, 0.3, 1e-6) && Near(pc.lean, 1.0, 1e-6) && Near(pc.ramp, 1.0, 1e-6) &&
                   Near(pc.along, 0.2, 1e-6) && Near(pc.hc_max, 18.5, 1e-5) && Near(pc.gust, 0.9, 1e-6) &&
                   Near(pc.w_max, 0.4, 1e-6),
               "ReadProof reads the slot's 16 words");
        Expect(T::ReadProof(words.data(), slot + 1).verts == 0 && T::ReadProof(words.data(), BaseSlots).verts == 0 &&
                   T::ReadProof(nullptr, 0).verts == 0,
               "ReadProof: another slot, a slot out of range and no words read as 0");
        Expect(std::strstr(T::ProofVerdict(pc), "OK:") != nullptr, "ProofVerdict: counts that move read OK");
        const auto verdict_has = [&](const char* what, const auto& change) {
            T::ProofCounts k = pc;
            change(k);
            return std::strstr(T::ProofVerdict(k), what) != nullptr;
        };
        Expect(verdict_has("no vertex counted", [](T::ProofCounts& k) { k.verts = 0; }) &&
                   verdict_has("not finite", [](T::ProofCounts& k) { k.fin = 10; }) &&
                   verdict_has("tau is 0", [](T::ProofCounts& k) { k.tall = 0; }) &&
                   verdict_has("ramp 0", [](T::ProofCounts& k) { k.ramp = 0.0f; }) &&
                   verdict_has("gain 0", [](T::ProofCounts& k) { k.gain = 0.0f; }) &&
                   verdict_has("lean 0", [](T::ProofCounts& k) { k.lean = 0.0f; }) &&
                   verdict_has("weight 0", [](T::ProofCounts& k) { k.used_w = 0; }) &&
                   verdict_has("under 1 mm", [](T::ProofCounts& k) { k.move_max = 0.0001f; }),
               "ProofVerdict names the first break in the shader's order");
        char line[1100]; // bbport (r89h): the line grew by the time motion
        T::ProofLine(pc, slot, 600, 600, 1, 156641, line, sizeof(line));
        Expect(std::strstr(line, "slot 5:") != nullptr && std::strstr(line, "600 draws (600 on pipelines") != nullptr &&
                   std::strstr(line, "verdict: OK:") != nullptr && std::strlen(line) < 1000,
               "ProofLine");
        T::ClearProof(words.data(), slot);
        Expect(T::ReadProof(words.data(), slot).verts == 0 && words[T::ProofAt + slot * T::ProofSlotWords + 7] == 0,
               "ClearProof");
        T::ClearProof(words.data(), BaseSlots);
        Expect(words[T::ProofEnd - 1] == 0 && T::ProofBytes == T::ProofEnd * 4 && T::ProofSlotWords == 16,
               "ClearProof out of range writes nothing; the counters' size");
        char once[640];
        T::FitOnceText(dflt, once, sizeof(once));
        Expect(std::strstr(once, "BB_WIND_TWIGS_FIT=1") != nullptr && std::strstr(once, "smoothstep 3 to 9 m") != nullptr &&
                   std::strlen(once) < 520,
               "FitOnceText");
        T::FitOnceText(asked, once, sizeof(once));
        Expect(std::strstr(once, "BB_WIND_TWIGS_FIT=0") != nullptr, "FitOnceText with FIT=0");
        T::ProofOnceText(once, sizeof(once));
        Expect(std::strstr(once, "BB_WIND_TWIGS_PROOF=1, TOOL") != nullptr && std::strlen(once) < 520, "ProofOnceText");
    }

    // bbport (r89h_twigs-alive): the push rule's along-wind move, its place in Displace, the knob, the versions, the
    // change counters and the lag step, the texts.
    {
        namespace T = BbWindTwigs;
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        // the rule's numbers on a view at 4 m/s (the bend is BendMax), gust factor 1
        Ripple shape_ripple;
        const auto sv = TwigViewOf(c, Gusty(5.0, 225.0f, 4.0f, 0.0f), shape_ripple, 1.0f, 1.0f, 0.0f);
        const double bend = double(sv[RippleAt + 12]);
        Expect(Near(bend, double(BendMax), 1e-6), "the view's bend at 4 m/s is BendMax");
        Expect(Near(TwigAlong(sv.data(), 1.0f, 0.0f, 0.0f), bend * double(TwigRest), 1e-6) &&
                   Near(TwigAlong(sv.data(), 1.0f, EnvScale, 0.0f), bend * double(TwigRest + TwigPush), 1e-5) &&
                   Near(TwigAlong(sv.data(), 1.0f, 1.0f, 0.0f), bend * double(TwigRest + 0.25f * TwigPush), 1e-6) &&
                   TwigAlong(sv.data(), 0.0f, 1.0f, 1.0f) == 0.0f,
               "TwigAlong: the rest with no front, rest + push in a full front, the squared share between, 0 with no gust");
        Expect(Near(RippleAlong(sv.data(), 1.0f, 1.0f, 0.0f), double(sv[RippleAt + 8]), 1e-6) &&
                   TwigAlong(sv.data(), 1.0f, 0.0f, 0.0f) < RippleAlong(sv.data(), 1.0f, 0.0f, 0.0f),
               "RippleAlong is the ripple's own (its rest at a front of 1); the push's steady part is smaller");
        // the time series of one limb 12 m over the camera in a 4 m/s wind (a gust factor of 1)
        const std::array<double, 3> mid = {10.0 - std::sin(0.3) * 7.0, 0.0, 20.0 - std::cos(0.3) * 7.0};
        const TreeBox stand = {0.0f, 37.0f, float(mid[0] - 22.5), float(mid[0] + 22.5), float(mid[2] - 19.5),
                               float(mid[2] + 19.5)};
        struct Range {
            double lo = 1.0e9, hi = 0.0;
        };
        const auto range_of = [&](bool push) {
            Range range;
            Ripple wind_ripple;
            const std::array<double, 3> limb = {mid[0], 14.0, mid[2]};
            for (int i = 0; i < 600; ++i) {
                const BbWind::Snapshot snap = Gusty(0.1 * i, 225.0f, 4.0f, 0.0f);
                const auto v = TwigViewOf(c, snap, wind_ripple, 1.0f, 1.0f, 0.0f);
                const auto clip = ClipOf(c, limb);
                const auto before = WorldOf(v.data(), clip);
                TwigIn in = TwigInOf(stand, true);
                in.sized = true;
                in.fit = true;
                in.push = push;
                const auto after = WorldOf(v.data(), Displace(v.data(), clip, HeightKey(stand.base), 1.0f, nullptr,
                                                              CrownKey(stand.crown), nullptr, &in));
                const std::array<double, 3> moved = {after[0] - before[0], after[1] - before[1], after[2] - before[2]};
                const double along = AlongOf(moved, snap);
                range.lo = std::min(range.lo, along);
                range.hi = std::max(range.hi, along);
            }
            return range;
        };
        const Range on = range_of(true);
        const Range off = range_of(false);
        Expect(on.hi > 0.03 && on.hi < 0.25, "the push rule: the largest along-wind move 12 m over the camera is 3-25 cm");
        Expect(on.lo < 0.15 * on.hi && on.hi - on.lo > 0.5 * on.hi,
               "the push rule: the steady part is small, the swing is over half the largest move");
        Expect(off.hi > 0.02, "push off: r89g's rule still moves the limb");
        {   // where the twig weight is 0 (1 m over the camera) the rule changes nothing, bit for bit
            const std::array<double, 3> low = {mid[0], 3.0, mid[2]};
            const auto clip = ClipOf(c, low);
            TwigIn with_push = TwigInOf(stand, true);
            with_push.sized = true;
            with_push.fit = true;
            with_push.push = true;
            TwigIn without = with_push;
            without.push = false;
            Expect(Displace(sv.data(), clip, HeightKey(stand.base), 1.0f, nullptr, CrownKey(stand.crown), nullptr,
                            &with_push) ==
                       Displace(sv.data(), clip, HeightKey(stand.base), 1.0f, nullptr, CrownKey(stand.crown), nullptr,
                                &without),
                   "the push rule changes nothing where the twig weight is 0");
        }
        // the knob and the versions
        const T::Knob dflt = T::ParseKnob(nullptr, nullptr, true, true);
        const T::Knob nopush = T::ParseKnob(nullptr, nullptr, true, true, nullptr, nullptr, nullptr, nullptr, "0");
        const T::Knob nofit = T::ParseKnob(nullptr, nullptr, true, true, nullptr, nullptr, "0", nullptr, nullptr);
        const T::Knob junk = T::ParseKnob(nullptr, nullptr, true, true, nullptr, nullptr, nullptr, nullptr, "x");
        Expect(dflt.push == 1 && nopush.push == 0 && junk.push == 1 && T::PushWanted(dflt) && !T::PushWanted(nopush) &&
                   !T::PushWanted(nofit) && !T::PushWanted(T::ParseKnob(nullptr, nullptr, false, true)),
               "BB_WIND_TWIGS_PUSH: 0 or 1, default 1; the rule needs the twigs and the fit rule");
        Expect(T::KnownVersion(2011 + 150, 11, 21, 1000) && T::KnownVersion(2011 + 170, 11, 21, 1000) &&
                   T::KnownVersion(2011 + 40, 11, 21, 1000) && !T::KnownVersion(2016, 11, 21, 1000) && T::PushAdd == 40,
               "the saved versions with the push offset are known; no other");
        // the change counters and the line
        std::vector<std::uint32_t> words(T::LagEnd, 0u);
        const std::uint32_t slot = 7;
        std::uint32_t* const ch = words.data() + T::ChangeAt + slot * T::ChangeSlotWords;
        const auto bits = [](float v) {
            std::uint32_t u = 0;
            std::memcpy(&u, &v, sizeof(u));
            return u;
        };
        ch[0] = bits(0.12f);
        ch[1] = 1500;
        ch[2] = 300;
        ch[3] = bits(0.4f);
        const T::ProofCounts pc = T::ReadProof(words.data(), slot);
        Expect(Near(pc.change_max, 0.12, 1e-6) && pc.change_sum == 1500 && pc.change_n == 300 &&
                   Near(pc.front_max, 0.4, 1e-6) && pc.verts == 0,
               "ReadProof reads the slot's change words");
        char line[1100];
        T::ProofLine(pc, slot, 600, 600, 1, 156641, line, sizeof(line));
        Expect(std::strstr(line, "time motion over 15 frames: 300 twig vertices") != nullptr &&
                   std::strstr(line, "change mean 0.50 cm, largest 12.00 cm") != nullptr &&
                   std::strstr(line, "(moving)") != nullptr && std::strlen(line) < 1000,
               "ProofLine says the time motion");
        Expect(std::strstr(T::ChangeVerdict(pc), "moving") != nullptr &&
                   std::strstr(T::ChangeVerdict(T::ProofCounts{}), "no twig vertex") != nullptr,
               "ChangeVerdict");
        T::ProofCounts still = pc;
        still.change_max = 0.0f;
        Expect(std::strstr(T::ChangeVerdict(still), "STILL") != nullptr, "ChangeVerdict: still");
        T::ClearProof(words.data(), slot);
        Expect(T::ReadProof(words.data(), slot).change_n == 0 && ch[1] == 0 && ch[0] == 0, "ClearProof clears the change words");
        // the lag step: 15 steps with the flag 0, then the phases of 15 steps ago and the flag 1
        std::vector<std::uint32_t> lag_words(T::LagEnd, 0u);
        std::array<float, ViewWords> pv{};
        const auto lag_of = [&](std::uint32_t k) {
            float f = 0.0f;
            std::memcpy(&f, &lag_words[T::LagAt + k], sizeof(f));
            return f;
        };
        bool lag_ok = true;
        for (int i = 0; i < 40; ++i) {
            pv[RippleA + 2] = float(i);
            pv[RippleA + 3] = float(i) + 0.25f;
            pv[RippleB] = float(i) + 0.5f;
            T::ProofLagStep(lag_words.data(), pv.data());
            const bool valid = i >= int(T::LagFrames);
            lag_ok = lag_ok && lag_of(3) == (valid ? 1.0f : 0.0f) &&
                     (!valid || (lag_of(0) == float(i - int(T::LagFrames)) &&
                                 lag_of(1) == float(i - int(T::LagFrames)) + 0.25f &&
                                 lag_of(2) == float(i - int(T::LagFrames)) + 0.5f));
        }
        Expect(lag_ok, "ProofLagStep: the flag is 0 for 15 steps, then the words hold the phases 15 steps ago");
        // the texts
        char text[640];
        T::PushOnceText(dflt, 1.0f, text, sizeof(text));
        Expect(std::strstr(text, "BB_WIND_TWIGS_PUSH=1") != nullptr && std::strstr(text, "steady/peak cm at 4 m/s") != nullptr &&
                   std::strlen(text) < 560,
               "PushOnceText");
        T::PushOnceText(nopush, 1.0f, text, sizeof(text));
        Expect(std::strstr(text, "BB_WIND_TWIGS_PUSH=0") != nullptr && std::strstr(text, "off") != nullptr, "PushOnceText off");
        T::Stats push_stats;
        push_stats.tree_draws = 42;
        T::PushReportText(push_stats, Wind(5.0, 225.0f, 4.0f), dflt, 1.0f, text, sizeof(text));
        Expect(std::strstr(text, "42 tree draws pushed") != nullptr && std::strstr(text, "at 4.00 m/s") != nullptr &&
                   std::strlen(text) < 400,
               "PushReportText");
        const T::PushTip slow_tip = T::PushTipAt(1.5f, 1.0f, 1.0f, 8.0f, true);
        const T::PushTip fast_tip = T::PushTipAt(4.0f, 1.0f, 1.0f, 8.0f, true);
        Expect(fast_tip.peak > 0.07f && fast_tip.peak < 0.10f && slow_tip.peak < 0.015f && fast_tip.steady < 0.1f * fast_tip.peak,
               "PushTipAt: 7-10 cm peak at 4 m/s at 8 m over the camera, under 1.5 cm at 1.5 m/s, the steady part small");
    }

    // The slots in use.
    {
        Slots slots;
        (void)slots.Take(0x1000, 64, 10, 0.0);
        (void)slots.Take(0x2000, 128, 10, 0.0);
        std::vector<std::uint64_t> seen;
        slots.ForEachInUse(12, [&](std::uint32_t slot, std::uint64_t stream, std::uint32_t size) {
            Expect(slot < PlantSlots && size != 0, "ForEachInUse: slot and size");
            seen.push_back(stream);
        });
        std::uint32_t later = 0;
        slots.ForEachInUse(10 + ReuseFrames + 1, [&](std::uint32_t, std::uint64_t, std::uint32_t) { ++later; });
        Expect(seen.size() == 2 && (seen[0] == 0x1000 || seen[1] == 0x1000) && later == 0,
               "ForEachInUse: the streams drawn within ReuseFrames frames");
    }

    // The twigs' log texts (under 300 characters), the model's share.
    {
        namespace T = BbWindTwigs;
        char text[512];
        T::Census census;
        census.lone = 3;
        census.sun = 4;
        census.sun_not = 2;
        for (const float h : {9.2f, 7.1f, 6.4f, 3.0f, 8.0f}) {
            census.Tall(h);
        }
        T::Stats st;
        st.small = 40;
        st.opaque = 12;
        T::LineText(census, st, Wind(10.0, 231.0f, 1.5f), T::ParseKnob(nullptr, nullptr, true, true),
                    1.0f, 1.0f, text, sizeof(text));
        const char* head =
            "Wind twigs (r89d): trees taken 7 (meshes: 3 lone, 4 sun; tallest 9.2/8.0/7.1 m), skipped 54 by "
            "reason (draws: small-skeleton 40, opaque 12, no-sun 0; meshes: sun-not-still 2); twig share of "
            "tree vertices ";
        Expect(std::strncmp(text, head, std::strlen(head)) == 0 && std::strlen(text) < 300 &&
                   std::strstr(text, "(model); tip move at 1.50 m/s: 0.6 cm lean, 1.3 cm gust front") != nullptr,
               "the twigs' line");
        census = T::Census{};
        st.small = 999999;
        st.opaque = 999999;
        st.no_sun = 999999;
        census.lone = 30;
        census.sun = 40;
        census.sun_not = 99;
        for (const float h : {19.2f, 18.0f, 17.1f}) {
            census.Tall(h);
        }
        T::LineText(census, st, Wind(10.0, 231.0f, 4.0f), T::ParseKnob("4", "2", true, true), MaxScale, 4.0f,
                    text, sizeof(text));
        Expect(std::strlen(text) < 300, "the line at 6-digit counts stays under 300 characters");
        T::LineText(T::Census{}, T::Stats{}, Wind(10.0, 231.0f, 1.5f), T::ParseKnob(nullptr, nullptr, true, true),
                    1.0f, 1.0f, text, sizeof(text));
        Expect(std::strstr(text, "trees taken 0 (meshes: 0 lone, 0 sun; tallest none m)") != nullptr,
               "the line with no tree");
        T::OnceText(T::ParseKnob(nullptr, nullptr, true, true), 1.0f, 1.0f, text, sizeof(text));
        Expect(std::strncmp(text, "Wind twigs (r89d, BB_WIND_TWIGS=1.00, REACH=1): small branches", 62) == 0 &&
                   std::strlen(text) < 300 &&
                   std::strstr(text, "tip 0.6/1.3 cm (lean/gust front) at 1.5 m/s, 4.5/9.2 cm at 4 m/s") != nullptr,
               "the twigs' once line");
        T::OnceText(T::ParseKnob("4", "2", true, true), MaxScale, 4.0f, text, sizeof(text));
        Expect(std::strlen(text) < 300, "the once line at the strongest");
        const float share = T::ModelShare();
        Expect(share > 0.2f && share < 0.35f, "the model's twig share is about 28 percent");
    }

    // The log's texts.
    {
        char text[512];
        const auto s = Wind(10.0, 231.0f, 1.5f);
        RippleText(ParseRipple("0", nullptr), s, 0, text, sizeof(text));
        Expect(std::strstr(text, "ripple off") != nullptr, "the line says the ripple is off");
        RippleText(ParseRipple(nullptr, nullptr), s, 7, text, sizeof(text));
        Expect(std::strstr(text, "ripple 1.00 (fronts 9.0 m apart, 1.50 m/s toward 231 deg") !=
                       nullptr &&
                   std::strstr(text, "7 views)") != nullptr,
               "the line's ripple state");
        RippleOnceText(ParseRipple("0", nullptr), 1.0f, text, sizeof(text));
        Expect(std::strncmp(text, "Wind sway ripple (r89b): off", 28) == 0, "the once line, off");
        RippleOnceText(ParseRipple("4", "1"), MaxScale, text, sizeof(text));
        const char* on_text = "Wind sway ripple (r89b, BB_WIND_SWAY_RIPPLE=4.00, SHOW";
        Expect(std::strncmp(text, on_text, std::strlen(on_text)) == 0 && std::strlen(text) < 300,
               "the once line, on, under 300 characters");
    }

    if (failures == 0) {
        std::printf("wind-sway-test: ok\n");
    }
    return failures == 0 ? 0 : 1;
}
