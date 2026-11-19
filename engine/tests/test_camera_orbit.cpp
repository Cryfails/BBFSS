// SPDX-License-Identifier: GPL-3.0-or-later
#include "gpu/shim/input/camera_orbit.h"
#include <cassert>
#include <cmath>
#include <cstdio>

namespace {
using namespace CameraOrbit;

bool Near(float a, float b, float within) { return std::fabs(a - b) <= within; }

// A turning speed in degrees a second to test with (BB_CAMERA_ORBIT's range is -kSpeedMost..kSpeedMost).
constexpr float kTurn = 12.0f;

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
    const Targets t{true, kTurn, 0.0f, 1.0f};
    const Pose first = Step(r, t, 0.0f, pitch, 0.5f, -1.0f, 1.0f);
    assert(first.yaw == 0.5f); // the first update after a start does not move the camera
    RunFor(r, t, 0.1f, 60.0f, pitch);
    assert(r.rate.value > 0.0f && r.rate.value < 0.3f * kTurn * kRadiansPerDegree);
    RunFor(r, t, 4.0f, 60.0f, pitch);
    assert(Near(r.rate.value, kTurn * kRadiansPerDegree, 0.01f * kTurn * kRadiansPerDegree));
}

void StopEasesOutAndSettles() {
    Run r;
    float pitch = 0.0f;
    RunFor(r, {true, kTurn, 0.0f, 1.3f}, 5.0f, 60.0f, pitch);
    assert(!Settled(r));
    const Targets off{false, kTurn, 0.0f, 1.3f};
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
    RunFor(r, {true, kTurn, 0.4f, 1.0f}, 5.0f, 60.0f, pitch);
    const float held = pitch;
    RunFor(r, {false, kTurn, -0.4f, 1.0f}, 3.0f, 60.0f, pitch);
    assert(Near(pitch, held, 1e-3f));
}

void LongUpdatesAreCut() {
    Run a, b;
    const Targets t{true, kTurn, 0.0f, 1.0f};
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
    float r = 1.0f;
    r = NextRadius(r, 1);
    assert(Near(r, 1.1f, 1e-5f));
    for (int i = 0; i < 20; ++i) r = NextRadius(r, 1);
    assert(r == kRadiusMost);
    for (int i = 0; i < 20; ++i) r = NextRadius(r, -1);
    assert(r == kRadiusLeast);
    for (int i = 0; i < 5; ++i) r = NextRadius(r, 1);
    assert(Near(r, 1.0f, 1e-5f));
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

// bbport (r124_camera-mode-keys): the hand's look in camera mode.
void AxisReadings() {
    assert(AxisUnit(0) == 0.0f && AxisUnit(3000) == 0.0f && AxisUnit(-3000) == 0.0f); // inside the dead zone
    assert(AxisUnit(32767) == 1.0f && AxisUnit(-32768) == -1.0f && AxisUnit(100000) == 1.0f);
    const int edge = int(kStickDead * 32767.0f);
    assert(AxisUnit(edge) == 0.0f && AxisUnit(edge + 200) > 0.0f && AxisUnit(edge + 200) < 0.02f);
    assert(Near(AxisUnit(16384), (0.5f - kStickDead) / (1.0f - kStickDead), 1e-3f));
    assert(AxisUnit(-16384) == -AxisUnit(16384));
    float last = 0.0f;
    for (int raw = 0; raw <= 32767; raw += 512) { // never goes down as the stick goes further
        assert(AxisUnit(raw) >= last);
        last = AxisUnit(raw);
    }
}

void LookAxisSumsAndClamps() {
    assert(LookAxis(1.0f, 0.0f) == 1.0f && LookAxis(-1.0f, 1.0f) == 0.0f);
    assert(LookAxis(1.0f, 1.0f) == 1.0f && LookAxis(-1.0f, -0.5f) == -1.0f && LookAxis(0.25f, 0.25f) == 0.5f);
    assert(LookAxis(NAN, 0.5f) == 0.0f && LookAxis(INFINITY, -INFINITY) == 0.0f);
}

void LookSpeedAddsTheHandsToTheKnobs() {
    assert(LookSpeed(0.0f, 0.0f) == 0.0f);
    assert(LookSpeed(0.0f, 1.0f) == kLookYawDegrees && LookSpeed(0.0f, -1.0f) == -kLookYawDegrees);
    assert(LookSpeed(20.0f, -0.5f) == 20.0f - 0.5f * kLookYawDegrees);
    assert(LookSpeed(kSpeedMost, 1.0f) == kSpeedMost + kLookYawDegrees); // the sum is bounded
    assert(LookSpeed(-kSpeedMost, -1.0f) == -kSpeedMost - kLookYawDegrees);
}

void LookPitchMovesAndStaysInsideTheLimits() {
    // Held down for a second: kLookPitchDegrees degrees (in updates of 1/60 s).
    float goal = 0.0f;
    for (int i = 0; i < 60; ++i) goal = LookPitch(goal, 1.0f, 0.0f, 1.0f / 60.0f, -1.5f, 1.5f);
    assert(Near(goal, kLookPitchDegrees * kRadiansPerDegree, 1e-3f));
    for (int i = 0; i < 60; ++i) goal = LookPitch(goal, -1.0f, 0.0f, 1.0f / 60.0f, -1.5f, 1.5f);
    assert(Near(goal, 0.0f, 1e-3f));
    // The mouse's turn adds at once, whatever dt is.
    assert(Near(LookPitch(0.1f, 0.0f, 0.2f, 0.0f, -1.5f, 1.5f), 0.3f, 1e-6f));
    // Never past the game's limits, either way, however long it is held.
    goal = 0.0f;
    for (int i = 0; i < 600; ++i) goal = LookPitch(goal, 1.0f, 0.0f, 1.0f / 60.0f, -0.5f, 0.6f);
    assert(goal == 0.6f);
    for (int i = 0; i < 600; ++i) goal = LookPitch(goal, -1.0f, 0.0f, 1.0f / 60.0f, -0.5f, 0.6f);
    assert(goal == -0.5f);
    assert(LookPitch(0.0f, 0.0f, 5.0f, 0.016f, -0.5f, 0.6f) == 0.6f);
    // Limits not in order (or not numbers) leave it unclamped, as Step leaves the game's pitch alone.
    assert(Near(LookPitch(0.0f, 0.0f, 0.2f, 0.016f, 0.6f, -0.5f), 0.2f, 1e-6f));
    assert(Near(LookPitch(0.0f, 0.0f, 0.2f, 0.016f, NAN, 0.6f), 0.2f, 1e-6f));
    // Anything not a number keeps the old goal; a long update is cut.
    assert(LookPitch(0.3f, NAN, 0.0f, 0.016f, -1.0f, 1.0f) == 0.3f && LookPitch(0.3f, 0.0f, NAN, 0.016f, -1.0f, 1.0f) == 0.3f);
    assert(LookPitch(0.0f, 1.0f, 0.0f, 9.0f, -9.0f, 9.0f) == LookPitch(0.0f, 1.0f, 0.0f, kLongestStep, -9.0f, 9.0f));
}

void ZoomMovesTheRadiusInsideItsRange() {
    float r = 1.0f;
    for (int i = 0; i < 60; ++i) r = ZoomRadius(r, 1.0f, 1.0f / 60.0f); // farther for a second
    assert(Near(r, 1.0f + kZoomPerSecond, 1e-3f) || r == kRadiusMost);
    for (int i = 0; i < 600; ++i) r = ZoomRadius(r, 1.0f, 1.0f / 60.0f);
    assert(r == kRadiusMost);
    for (int i = 0; i < 600; ++i) r = ZoomRadius(r, -1.0f, 1.0f / 60.0f);
    assert(r == kRadiusLeast);
    assert(ZoomRadius(1.0f, 0.0f, 0.016f) == 1.0f && ZoomRadius(1.0f, NAN, 0.016f) == 1.0f);
    assert(ZoomRadius(1.0f, 1.0f, -1.0f) == 1.0f); // a negative dt does not turn it round
}

// A turn by hand eases in and out with the quick spring, and the default times are the orbit's.
void HandLookIsQuickAndHolds() {
    Run slow, quick;
    float pitch_a = 0.0f, pitch_b = 0.0f, yaw_a = 0.0f, yaw_b = 0.0f;
    const Targets t{true, kLookYawDegrees, 0.0f, 1.0f};
    for (int i = 0; i < 12; ++i) { // 0.2 s at 60 updates a second
        yaw_a = Step(slow, t, 1.0f / 60.0f, pitch_a, yaw_a, -1.0f, 1.0f).yaw;
        yaw_b = Step(quick, t, 1.0f / 60.0f, pitch_b, yaw_b, -1.0f, 1.0f, kLookRateTime, kLookPitchTime).yaw;
    }
    assert(yaw_b > 3.0f * yaw_a && quick.rate.value > 0.4f * kLookYawDegrees * kRadiansPerDegree);
    for (int i = 0; i < 120; ++i) yaw_b = Step(quick, t, 1.0f / 60.0f, pitch_b, yaw_b, -1.0f, 1.0f, kLookRateTime, kLookPitchTime).yaw;
    assert(Near(quick.rate.value, kLookYawDegrees * kRadiansPerDegree, 0.01f * kLookYawDegrees * kRadiansPerDegree));
    // Let go: the turn stops within a second and never turns back.
    const Targets still{true, 0.0f, 0.0f, 1.0f};
    float last = quick.rate.value;
    for (int i = 0; i < 60; ++i) {
        yaw_b = Step(quick, still, 1.0f / 60.0f, pitch_b, yaw_b, -1.0f, 1.0f, kLookRateTime, kLookPitchTime).yaw;
        assert(quick.rate.value >= 0.0f && quick.rate.value <= last);
        last = quick.rate.value;
    }
    assert(quick.rate.value < 0.01f * kLookYawDegrees * kRadiansPerDegree);
    // The defaults are the orbit's own times.
    Run a, b;
    const Pose pa = Step(a, t, 0.016f, 0.1f, 0.2f, -1.0f, 1.0f);
    const Pose pb = Step(b, t, 0.016f, 0.1f, 0.2f, -1.0f, 1.0f, kRateTime, kPitchTime);
    assert(pa.yaw == pb.yaw && pa.pitch == pb.pitch && a.rate.value == b.rate.value);
}

// The hand's pitch goal moved by LookPitch is followed by the pitch spring and never leaves the limits.
void PitchFollowsTheHandsGoal() {
    Run r;
    r.pitch = {0.0f, 0.0f};
    float pitch = 0.0f, goal = 0.0f;
    for (int i = 0; i < 300; ++i) { // held down for 5 s: the goal reaches the limit, the pitch follows it
        goal = LookPitch(goal, 1.0f, 0.0f, 1.0f / 60.0f, -0.5f, 0.6f);
        pitch = Step(r, {true, 0.0f, goal, 1.0f}, 1.0f / 60.0f, pitch, 0.0f, -0.5f, 0.6f, kLookRateTime, kLookPitchTime).pitch;
        assert(pitch >= -0.5f && pitch <= 0.6f);
    }
    assert(Near(pitch, 0.6f, 1e-2f));
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
    EarlyEndEasesTheRadiusHome();
    AutoSpeedFromEnv(); // bbport (r102b_camera-clean-hud)
    AxisReadings(); // bbport (r124_camera-mode-keys)
    LookAxisSumsAndClamps();
    LookSpeedAddsTheHandsToTheKnobs();
    LookPitchMovesAndStaysInsideTheLimits();
    ZoomMovesTheRadiusInsideItsRange();
    HandLookIsQuickAndHolds();
    PitchFollowsTheHandsGoal();
    std::puts("camera orbit test passed");
    return 0;
}
