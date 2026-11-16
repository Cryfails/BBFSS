// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r95_halation): the halation's knobs and push words (halation_params.h). Pure: no Vulkan.
// Built and run by engine/build.sh --test and the CMake target halation-test.
#undef NDEBUG
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include "gpu/shadps4/video_core/renderer_vulkan/halation_params.h"

using namespace Vulkan::HalationParams;

namespace {
bool Near(double a, double b, double eps = 1e-5) {
    return std::abs(a - b) <= eps;
}

/// The shader's fixed point for a quarter texel's mean luminance (halation.comp, Down).
std::uint32_t Encode(float mean) {
    const float stops = std::clamp(std::log2(std::max(mean, KeyFloor)), -KeyBias, KeyBias);
    return std::uint32_t((stops + KeyBias) * KeyScale + 0.5f);
}
} // namespace

int main() {
    // a. Off unless a strength above 0 is named; at most MaxStrength.
    assert(Read(nullptr, nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("", nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("0", nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("-1", nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("on", nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("nan", nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("inf", nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("1", nullptr, nullptr, nullptr).strength == 1.0f);
    assert(Read("0.5", nullptr, nullptr, nullptr).strength == 0.5f);
    assert(Read("7", nullptr, nullptr, nullptr).strength == MaxStrength);

    // b. Radius and threshold: defaults for missing or unreadable text, then the ranges.
    const Knobs d = Read("1", nullptr, nullptr, nullptr);
    assert(d.radius == DefaultRadius && d.threshold == DefaultThreshold && d.show == ShowOff);
    assert(Read("1", "x", "y", nullptr).radius == DefaultRadius);
    assert(Read("1", "0.1", nullptr, nullptr).radius == MinRadius);
    assert(Read("1", "9", nullptr, nullptr).radius == MaxRadius);
    assert(Read("1", "2", nullptr, nullptr).radius == 2.0f);
    assert(Read("1", nullptr, "0", nullptr).threshold == MinThreshold);
    assert(Read("1", nullptr, "20", nullptr).threshold == MaxThreshold);
    assert(Read("1", nullptr, "5", nullptr).threshold == 5.0f);

    // c. Show: exactly "1" or "2".
    assert(Read("1", nullptr, nullptr, "1").show == ShowStrong);
    assert(Read("1", nullptr, nullptr, "2").show == ShowGlowOnly);
    assert(Read("1", nullptr, nullptr, "3").show == ShowOff);
    assert(Read("1", nullptr, nullptr, "12").show == ShowOff);
    assert(Read("1", nullptr, nullptr, "").show == ShowOff);

    // d. The quarter size covers every pixel; the blur's width is a share of the height.
    assert(Quarter(1920) == 480 && Quarter(1080) == 270 && Quarter(1078) == 270 &&
           Quarter(1) == 1 && Quarter(5) == 2);
    assert(Near(Sigma(d, 1080), 3.0) && Near(Sigma(d, 2160), 6.0) && Near(Sigma(d, 720), 2.0));
    assert(Taps(3.0f) == 9 && Taps(0.1f) == 1 && Taps(1000.0f) == MaxTaps);
    const Knobs wide = Read("1", "3", nullptr, nullptr);
    assert(Taps(Sigma(wide, 2160)) == 54); // the widest blur at a 2160-line scene still fits

    // e. The push words.
    const Push p = Make(d, 1920, 1080, 3, Add);
    assert(p.mode == Add && p.slot == 1 && p.scene_w == 1920 && p.scene_h == 1080);
    assert(p.quarter_w == 480 && p.quarter_h == 270 && p.taps == 9 && p.show == ShowOff);
    assert(Near(p.sigma, 3.0) && p.threshold_stops == DefaultThreshold && p.cap_stops == CapStops);
    assert(Near(p.gain, Gain) && p.hue_keep == HueKeep);
    assert(p.key_scale == KeyScale && p.key_bias == KeyBias && p.key_floor == KeyFloor);
    const Knobs strong = Read("2", nullptr, nullptr, "1");
    const Push s = Make(strong, 1920, 1080, 0, Down);
    assert(Near(s.gain, Gain * 2.0f * ShowGain) && s.slot == 0);
    assert(Near(s.threshold_stops, DefaultThreshold - ShowThresholdDrop));
    assert(Make(Read("1", nullptr, nullptr, "2"), 64, 64, 0, Add).show == ShowGlowOnly);

    // f. The tint is red-orange with a luminance of 1.
    assert(Near(0.2126 * TintR + 0.7152 * TintG + 0.0722 * TintB, 1.0, 1e-5));
    assert(TintR > TintG && TintG > TintB);

    // g. The key: the shader's fixed point and its decoding agree; sums fit 32 bits.
    for (const float mean : {0.001f, 0.02f, 0.18f, 1.0f, 40.0f}) {
        const double back = KeyOf(Encode(mean) * 1000u, 1000u);
        assert(std::abs(std::log2(back) - std::log2(double(mean))) <= 0.5 / KeyScale + 1e-6);
    }
    assert(Near(KeyOf(Encode(0.0f), 1), KeyFloor, 1e-6)); // black counts as the floor
    assert(KeyOf(0, 0) == 0.0);
    assert(KeyFits(Quarter(3840), Quarter(2160)));  // a 2160-line scene
    assert(KeyFits(Quarter(7680), Quarter(4320)));  // 4320 lines still fit (2048 x 1920 x 1080)
    assert(!KeyFits(Quarter(8192), Quarter(8192))); // too large: skipped, counted
    assert(2.0f * KeyBias * KeyScale * float(Quarter(3840)) * float(Quarter(2160)) < 4294967296.0f);

    // h. bbport (r109a_strength-settings-engine): the strength a frame uses: BB_HALATION when it
    // is set (by Read's rule), else the setting, clamped; and when the strength's line is due.
    {
        using StrengthKnob::ReadEnv;
        const StrengthKnob::Env unset = ReadEnv(nullptr, MaxStrength);
        assert(!unset.set && !ReadEnv("", MaxStrength).set);
        const StrengthKnob::Value d = StrengthOf(unset, DefaultStrength);
        assert(DefaultStrength == 1.0f && d.value == 1.0f && !d.from_env);
        assert(StrengthOf(unset, 0.0f).value == 0.0f && StrengthOf(unset, 1.5f).value == 1.5f);
        assert(StrengthOf(unset, 9.0f).value == MaxStrength && StrengthOf(unset, -1.0f).value == 0.0f);
        assert(StrengthOf(unset, NAN).value == DefaultStrength &&
               StrengthOf(unset, INFINITY).value == DefaultStrength);
        assert(StrengthOf(ReadEnv("", MaxStrength), 0.5f).value == 0.5f); // empty: the setting
        for (const char* text : {"0", "-1", "on", "nan", "inf", "1", "0.5", "7"}) {
            const StrengthKnob::Value e = StrengthOf(ReadEnv(text, MaxStrength), 1.25f);
            assert(e.from_env && e.value == Read(text, nullptr, nullptr, nullptr).strength);
        }
        StrengthKnob::Line line;
        const StrengthKnob::Value one{1.0f, false}, half{0.5f, false}, env_half{0.5f, true};
        assert(line.Due(600, one));  // the first frame
        assert(!line.Due(600, one)); // unchanged
        int at = -1;
        for (int f = 2; f < 2000 && at < 0; ++f) {
            at = line.Due(600, half) ? f : -1;
        }
        assert(at == 600); // a change: 600 frames after the last line
        assert(!line.Due(600, half));
        int changes = 0;
        for (int f = 0; f < 599; ++f) {
            changes += line.Due(600, f % 2 ? one : half) ? 1 : 0; // dragged and back
        }
        assert(changes == 0 && !line.Due(600, half)); // back where it was: no line
        at = -1;
        for (int f = 0; f < 2000 && at < 0; ++f) {
            at = line.Due(600, env_half) ? f : -1;
        }
        assert(at >= 0); // the source counts as a change
        // The key slots: cleared at the first pass and after more than KeyStaleFrames frame ends
        // without one; kept from one frame to the next, also with two frame ends a pass.
        static_assert(KeyStaleFrames == 30);
        assert(ClearsKey(0, 0, 0) && ClearsKey(0, 500, 0));
        assert(!ClearsKey(1, 1, 0) && !ClearsKey(7, 12, 11) && !ClearsKey(7, 13, 11));
        assert(!ClearsKey(7, 11 + KeyStaleFrames, 11) && ClearsKey(7, 12 + KeyStaleFrames, 11));
    }

    std::printf("halation-test: all checks passed\n");
    return 0;
}
