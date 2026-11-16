// SPDX-License-Identifier: GPL-3.0-or-later
#include "gpu/shim/input/camera_orbit.h"
#include <cassert>
#include <cmath>
#include <cstdio>

namespace {
using namespace CameraOrbit;

bool Near(float a, float b, float within) { return std::fabs(a - b) <= within; }

// Runs the orbit for seconds at hz updates a second; returns the yaw turned (not wrapped).
float RunFor(Run& r, const Targets& t, float seconds, float hz, float& pitch, float lowest = -1.0f, float highest = 1.0f) {
    float yaw = 0.0f, turned = 0.0f;
    const int updates = int(std::lround(seconds * hz));
    for (int i = 0; i < updates; ++i) {
        const Pose p = Step(r, t, 1.0f / hz, pitch, yaw, lowest, highest);
        float d = p.yaw - yaw;
        if (d > kPi) d -= 2 * kPi;
        if (d < -kPi) d += 2 * kPi;
        turned += d;
        assert(p.yaw >= -kPi && p.yaw <= kPi);
        assert(p.pitch >= lowest && p.pitch <= highest);
        yaw = p.yaw;
        pitch = p.pitch;
    }
    return turned;
}

void SpringFromRestNeverOvershoots() {
    Spring s;
    float last = 0.0f;
    for (int i = 0; i < 600; ++i) {
        Approach(s, 1.0f, 0.8f, 1.0f / 60.0f);
        assert(s.value >= last && s.value <= 1.0f);
        last = s.value;
    }
    assert(Near(s.value, 1.0f, 1e-4f));
}

void SpringIsTheSameAtAnyFrameRate() {
    Spring a, b, c;
    for (int i = 0; i < 60; ++i) Approach(a, 1.0f, 0.8f, 1.0f / 30.0f);
    for (int i = 0; i < 288; ++i) Approach(b, 1.0f, 0.8f, 1.0f / 144.0f);
    Approach(c, 1.0f, 0.8f, 2.0f);
    assert(Near(a.value, b.value, 1e-4f) && Near(a.value, c.value, 1e-4f));
}

void StartEasesIn() {
    Run r;
    float pitch = 0.0f;
    const Targets t{true, kSpeedStart, 0.0f, 1.0f};
    const Pose first = Step(r, t, 0.0f, pitch, 0.5f, -1.0f, 1.0f);
    assert(first.yaw == 0.5f); // the first update after a start does not move the camera
    RunFor(r, t, 0.1f, 60.0f, pitch);
    assert(r.rate.value > 0.0f && r.rate.value < 0.3f * kSpeedStart * kRadiansPerDegree);
    RunFor(r, t, 4.0f, 60.0f, pitch);
    assert(Near(r.rate.value, kSpeedStart * kRadiansPerDegree, 0.01f * kSpeedStart * kRadiansPerDegree));
}

void StopEasesOutAndSettles() {
    Run r;
    float pitch = 0.0f;
    RunFor(r, {true, kSpeedStart, 0.0f, 1.3f}, 5.0f, 60.0f, pitch);
    assert(!Settled(r));
    const Targets off{false, kSpeedStart, 0.0f, 1.3f};
    float last = r.rate.value, turned = 0.0f;
    int updates = 0;
    while (!Settled(r) && updates < 60 * 10) {
        turned += RunFor(r, off, 1.0f / 60.0f, 60.0f, pitch);
        assert(r.rate.value >= 0.0f && r.rate.value <= last); // slows down, never turns back
        last = r.rate.value;
        ++updates;
    }
    assert(Settled(r));
    assert(updates < 60 * 4);                         // at rest within 4 seconds
    assert(turned > 0.0f && turned < 15.0f * kRadiansPerDegree);
    assert(Near(r.radius.value, 1.0f, 0.002f));
}

void PitchStaysInsideTheGamesLimits() {
    Run r;
    r.pitch = {0.2f, 0.0f};
    float pitch = 0.2f;
    RunFor(r, {true, 0.0f, 3.0f, 1.0f}, 5.0f, 60.0f, pitch, -0.5f, 0.6f);
    assert(Near(pitch, 0.6f, 1e-3f));
    RunFor(r, {true, 0.0f, -3.0f, 1.0f}, 5.0f, 60.0f, pitch, -0.5f, 0.6f);
    assert(Near(pitch, -0.5f, 1e-3f));
    // Limits out of order (or not numbers): the pitch is left as the game has it.
    const Pose p = Step(r, {true, 0.0f, 0.3f, 1.0f}, 0.016f, 0.25f, 0.0f, 0.6f, -0.5f);
    assert(p.pitch == 0.25f);
    const Pose q = Step(r, {true, 0.0f, 0.3f, 1.0f}, 0.016f, 0.25f, 0.0f, NAN, 0.6f);
    assert(q.pitch == 0.25f);
}

void StopKeepsThePitch() {
    Run r;
    float pitch = 0.0f;
    RunFor(r, {true, kSpeedStart, 0.4f, 1.0f}, 5.0f, 60.0f, pitch);
    const float held = pitch;
    RunFor(r, {false, kSpeedStart, -0.4f, 1.0f}, 3.0f, 60.0f, pitch);
    assert(Near(pitch, held, 1e-3f));
}

void LongUpdatesAreCut() {
    Run a, b;
    const Targets t{true, kSpeedStart, 0.0f, 1.0f};
    const Pose pa = Step(a, t, 5.0f, 0.0f, 0.0f, -1.0f, 1.0f);
    const Pose pb = Step(b, t, kLongestStep, 0.0f, 0.0f, -1.0f, 1.0f);
    assert(pa.yaw == pb.yaw && a.rate.value == b.rate.value);
    Run c;
    const Pose pc = Step(c, t, -1.0f, 0.0f, 0.3f, -1.0f, 1.0f);
    assert(pc.yaw == 0.3f && c.rate.value == 0.0f);
}

void YawWraps() {
    assert(Near(Wrap(kPi + 0.5f), -kPi + 0.5f, 1e-5f));
    assert(Near(Wrap(-kPi - 0.5f), kPi - 0.5f, 1e-5f));
    assert(Wrap(1.0f) == 1.0f);
    Run r;
    float pitch = 0.0f;
    RunFor(r, {true, -kSpeedMost, 0.0f, 1.0f}, 30.0f, 60.0f, pitch); // more than three turns, asserts the range
}

void Steps() {
    assert(NextSpeed(kSpeedStart, 1) == 15.0f && NextSpeed(kSpeedStart, -1) == 9.0f);
    float s = kSpeedStart;
    for (int i = 0; i < 4; ++i) s = NextSpeed(s, -1);
    assert(s == 0.0f);
    s = NextSpeed(s, -1);
    assert(s == -3.0f);
    for (int i = 0; i < 40; ++i) s = NextSpeed(s, 1);
    assert(s == kSpeedMost);
    for (int i = 0; i < 40; ++i) s = NextSpeed(s, -1);
    assert(s == -kSpeedMost);

    float r = 1.0f;
    r = NextRadius(r, 1);
    assert(Near(r, 1.1f, 1e-5f));
    for (int i = 0; i < 20; ++i) r = NextRadius(r, 1);
    assert(r == kRadiusMost);
    for (int i = 0; i < 20; ++i) r = NextRadius(r, -1);
    assert(r == kRadiusLeast);
    for (int i = 0; i < 5; ++i) r = NextRadius(r, 1);
    assert(Near(r, 1.0f, 1e-5f));

    assert(NextHeight(0, 1) == 1 && NextHeight(kHeightStepsMost, 1) == kHeightStepsMost);
    assert(NextHeight(-kHeightStepsMost, -1) == -kHeightStepsMost);
}

void HeightStaysInsideTheGamesLimits() {
    const float step = kHeightStep * kRadiansPerDegree;
    // Far from both limits: 8 steps either way.
    HeightRange h = HeightRangeFrom(0.0f, -1.5f, 1.5f);
    assert(h.least == -kHeightStepsMost && h.most == kHeightStepsMost);
    // 10 degrees below the highest pitch (exactly two steps) and 12.5 above the lowest.
    h = HeightRangeFrom(0.3f, 0.3f - 2.5f * step, 0.3f + 2.0f * step);
    assert(h.least == -2 && h.most == 2);
    // At a limit: no steps that way.
    h = HeightRangeFrom(0.6f, -0.5f, 0.6f);
    assert(h.most == 0 && h.least == -kHeightStepsMost);
    // Every step inside the range keeps the target pitch inside the limits.
    for (int s = h.least; s <= h.most; ++s) assert(0.6f + float(s) * step >= -0.5f - 1e-4f && 0.6f + float(s) * step <= 0.6f + 1e-4f);
    // Limits not in order, or not numbers, and a base that is not a number: no steps.
    h = HeightRangeFrom(0.0f, 0.6f, -0.5f);
    assert(h.least == 0 && h.most == 0);
    h = HeightRangeFrom(0.0f, NAN, 0.6f);
    assert(h.least == 0 && h.most == 0);
    h = HeightRangeFrom(NAN, -0.5f, 0.6f);
    assert(h.least == 0 && h.most == 0);
}

void EarlyEndEasesTheRadiusHome() {
    Spring radius{1.5f, 0.0f};
    float last = radius.value;
    int updates = 0;
    while (!EaseRadiusHome(radius, 1.0f / 60.0f)) {
        assert(radius.value < last && radius.value > 1.0f); // never a jump, never past 1 from rest
        assert(last - radius.value < 0.02f);                 // less than 2% of the distance a frame at 60
        last = radius.value;
        assert(++updates < 60 * 6);
    }
    assert(radius.value == 1.0f && radius.velocity == 0.0f);
    assert(updates > 60); // it takes more than a second, not one frame
    Spring home{1.0f, 0.0f};
    assert(EaseRadiusHome(home, 0.0f) && home.value == 1.0f);
}

// bbport (r102b_camera-clean-hud): BB_CAMERA_ORBIT's speed.
void AutoSpeedFromEnv() {
    assert(AutoSpeedFrom(nullptr) == 0.0f && AutoSpeedFrom("") == 0.0f);
    assert(AutoSpeedFrom("12") == 12.0f && AutoSpeedFrom("-20") == -20.0f && AutoSpeedFrom("7.5") == 7.5f);
    assert(AutoSpeedFrom("90") == kSpeedMost && AutoSpeedFrom("-90") == -kSpeedMost);
    assert(AutoSpeedFrom("0") == 0.0f && AutoSpeedFrom("x") == 0.0f && AutoSpeedFrom("12x") == 0.0f);
    assert(AutoSpeedFrom("nan") == 0.0f && AutoSpeedFrom("inf") == 0.0f);
}
}

int main() {
    SpringFromRestNeverOvershoots();
    SpringIsTheSameAtAnyFrameRate();
    StartEasesIn();
    StopEasesOutAndSettles();
    PitchStaysInsideTheGamesLimits();
    StopKeepsThePitch();
    LongUpdatesAreCut();
    YawWraps();
    Steps();
    HeightStaysInsideTheGamesLimits();
    EarlyEndEasesTheRadiusHome();
    AutoSpeedFromEnv(); // bbport (r102b_camera-clean-hud)
    std::puts("camera orbit test passed");
    return 0;
}
