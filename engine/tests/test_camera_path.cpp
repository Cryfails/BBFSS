// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r102_camera-mode-3-4): camera mode's path rules (gpu/shim/input/camera_path.h).
#include "gpu/shim/input/camera_path.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>

using namespace CameraPath;

namespace {
bool Near(float a, float b, float e = 1e-4f) { return std::fabs(a - b) <= e; }

void SecondsFromText() {
    assert(SecondsFrom(nullptr) == kSecondsDefault && SecondsFrom("") == kSecondsDefault);
    assert(SecondsFrom("2.5") == 2.5f && SecondsFrom("0.5") == 0.5f && SecondsFrom("60") == 60.0f);
    assert(SecondsFrom("0.4") == kSecondsDefault && SecondsFrom("61") == kSecondsDefault);
    assert(SecondsFrom("fast") == kSecondsDefault && SecondsFrom("nan") == kSecondsDefault);
}

void UnwrapTakesTheShortWay() {
    Key k[3] = {{3.0f, 0, 1}, {-3.0f, 0, 1}, {3.0f, 0, 1}};
    Unwrap(k, 3);
    // -3 is 0.28 rad past +pi from 3: it becomes 3.28, then 3 is the short way back.
    assert(Near(k[1].yaw, -3.0f + 2 * kPi) && Near(k[2].yaw, 3.0f));
    for (int i = 1; i < 3; ++i) assert(std::fabs(k[i].yaw - k[i - 1].yaw) <= kPi + 1e-5f);
}

void SamplePassesThroughEveryKey() {
    Key k[4] = {{0, 0.1f, 1}, {1, 0.2f, 1.2f}, {2.5f, 0.0f, 0.8f}, {3, -0.1f, 1}};
    for (int i = 0; i < 4; ++i) {
        const Key s = Sample(k, 4, float(i));
        assert(Near(s.yaw, k[i].yaw) && Near(s.pitch, k[i].pitch) && Near(s.radius, k[i].radius));
    }
    // Before the start and after the end it holds the end keys.
    assert(Near(Sample(k, 4, -1).yaw, 0) && Near(Sample(k, 4, 9).yaw, 3));
    // A step in u gives a small step in the pose (no jump at a key).
    for (float u = 0; u < 3; u += 0.01f) {
        const Key a = Sample(k, 4, u), b = Sample(k, 4, u + 0.01f);
        assert(std::fabs(a.yaw - b.yaw) < 0.05f && std::fabs(a.pitch - b.pitch) < 0.01f);
    }
    // The radius never leaves the orbit's range, even where the curve would overshoot.
    Key r[3] = {{0, 0, 0.5f}, {1, 0, 1.5f}, {2, 0, 0.5f}};
    for (float u = 0; u <= 2; u += 0.05f) {
        const float v = Sample(r, 3, u).radius;
        assert(v >= kRadiusLeast && v <= kRadiusMost);
    }
    assert(Sample(k, 1, 0.5f).yaw == k[0].yaw && Sample(k, 0, 0).radius == 1.0f);
}

void TimingEasesInAndOut() {
    const Timing t = TimingFor(3, 4.0f); // the start pose and two keys: 8 s of cruise
    assert(Near(t.span, 2) && Near(t.rate, 0.25f) && Near(t.ease, kEaseMost) && Near(t.total, 9.5f));
    assert(Progress(t, -1) == 0 && Progress(t, 0) == 0 && Progress(t, t.total) == t.span && Progress(t, 99) == t.span);
    float last = 0, last_speed = 0;
    const float dt = 0.001f;
    for (float s = dt; s <= t.total; s += dt) {
        const float u = Progress(t, s);
        const float speed = (u - last) / dt;
        assert(u >= last - 1e-6f);                       // never backwards
        assert(speed <= t.rate + 1e-2f);                 // never faster than the cruise
        assert(std::fabs(speed - last_speed) < 0.01f);   // no step in speed
        last = u;
        last_speed = speed;
    }
    assert(Near(last, t.span, 1e-3f));
    // A short play: the ease shrinks to the cruise and the play stays smooth.
    const Timing q = TimingFor(2, 0.5f);
    assert(Near(q.ease, 0.5f) && Near(q.total, 1.0f) && Near(Progress(q, 0.5f), 0.5f));
    assert(TimingFor(1, 4).total == 0 && Progress(TimingFor(1, 4), 1) == 0);
}

void FileLines() {
    Key k;
    assert(Parse("90 -10 1.2", k) && Near(k.yaw, 90 * kRadiansPerDegree) && Near(k.pitch, -10 * kRadiansPerDegree) &&
           Near(k.radius, 1.2f));
    assert(Parse("270 0 1", k) && Near(k.yaw, -90 * kRadiansPerDegree, 1e-3f));
    assert(Parse("0 0 9", k) && k.radius == kRadiusMost);
    assert(!Parse("# yaw pitch radius", k) && !Parse("", k) && !Parse("1 2", k) && !Parse("0 120 1", k));
    char line[64];
    const Key w{0.5f, -0.25f, 0.75f};
    assert(Format(w, line, sizeof line) > 0);
    Key r;
    assert(Parse(line, r) && Near(r.yaw, w.yaw, 1e-4f) && Near(r.pitch, w.pitch, 1e-4f) && Near(r.radius, w.radius));
}
}

int main() {
    SecondsFromText();
    UnwrapTakesTheShortWay();
    SamplePassesThroughEveryKey();
    TimingEasesInAndOut();
    FileLines();
    std::puts("camera path: ok");
}
