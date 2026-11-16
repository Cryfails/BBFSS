// SPDX-License-Identifier: GPL-3.0-or-later
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

    // r112g_hang-judge-settles: a short mesh scales its still top, full distance and push
    {
        Expect(H::HangScale(0.0f, 2.0f) == 1.0f && H::HangScale(0.0f, H::HangFull) == 1.0f,
               "scale: a tall mesh is 1");
        Expect(std::fabs(H::HangScale(1.0f, 1.6f) - 0.5f) < 1e-6f, "scale: 0.6 m is half");
        Expect(std::fabs(H::HangScale(0.0f, 0.15f) - 0.125f) < 1e-6f, "scale: 0.15 m is 0.125");
        Expect(H::HangScale(0.0f, 0.01f) == H::HangScaleMin &&
                   H::HangScale(3.0e38f, -3.0e38f) == H::HangScaleMin &&
                   H::HangScale(0.0f, std::nanf("")) == 1.0f,
               "scale: the least, reset keys, no number");
        Expect(H::MinExtent >= H::HangScaleMin * H::HangFull,
               "scale: a fitting mesh is not clamped");
        const BbWind::Snapshot s = Wind(37.0, 2.5f, 0.0f);
        const auto view = View(1.0f, s);
        std::array<float, W::GustSamples> push{};
        push.fill(0.2f);
        const std::uint32_t top = H::TopKey(1.0f); // a 0.6 m mesh: its top at world y 1, base 0.4
        const auto moved = [&](float world_y, float scale) {
            const auto in = Clip(4.0f, world_y, 2.0f);
            const auto out =
                H::HangDisplace(view.data(), push.data(), in, top, 1.0f, nullptr, scale);
            return std::hypot(double(out[0]) - in[0], double(out[2]) - in[2]);
        };
        Expect(moved(0.875f, 0.5f) == 0.0, "scale 0.5: its top 0.15 m stays");
        Expect(std::fabs(moved(0.375f, 0.5f) - 0.1) < 1e-5,
               "scale 0.5: from 0.6 m below its top half the push");
        Expect(moved(0.875f, 1.0f) == 0.0 && std::fabs(moved(-0.25f, 1.0f) - 0.2) < 1e-5,
               "scale 1: as before");
        const double u = 0.1 / 0.45; // (0.25 m below the top - 0.15 m) over 0.45 m
        Expect(std::fabs(moved(0.75f, 0.5f) - 0.2 * 0.5 * u * u * (3.0 - 2.0 * u)) < 1e-5,
               "scale 0.5: the smoothstep over the scaled distance");
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
        std::uint32_t b0 = W::HeightKey(0.0f), t01 = H::TopKey(0.1f), t6 = H::TopKey(6.0f);
        H::Entry low;
        (void)H::Measure(low, true, 0, &unset, &unset, 0.0);
        const H::Measured l = H::Measure(low, false, H::JudgeFrames, &b0, &t01, 1.0);
        Expect(!l.measuring && !l.swing && low.judged && !low.fits, "0.1 m tall: left out");
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
        const float heights[8] = {0.1f, 1.0f, 1.5f, 2.0f, 2.5f, 3.0f, 3.5f, 5.0f};
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
                                     "5678abcd 0.10 m") != nullptr,
               "the meshes' line: tallest first");
        H::Book none;
        H::MeshesText(none, 0, text, sizeof(text));
        Expect(std::strcmp(text, "Wind sway hang (r112) meshes: hang none; left out by height "
                                 "none") == 0,
               "the meshes' line with none");
    }

    // r116b_wind-weather: the weather moves the speed (and with it the follower's times) every frame: the
    // follower is kept, started once, and the tables do not jump between frames.
    {
        BbWind::Params p;
        p.on = true;
        p.weather = true;
        p.weather_rate = 30.0;
        p.weather_at = 1850.0;
        BbWind::State state;
        H::Push push;
        std::array<float, W::GustSamples> table{}, last{};
        float jump = 0.0f, most = 0.0f;
        for (int n = 0; n < 2400; ++n) { // 40 s at 60 Hz: 1200 s of weather through the 1990-2210 s spell
            state.Advance(p, 1.0 / 60.0);
            push.Fill(state.Get(), 3.0f, 4.0f, 0.5f, 1.0f, table.data());
            for (std::uint32_t i = 0; i < W::GustSamples; ++i) {
                most = std::max(most, table[i]);
                if (n > 0) {
                    jump = std::max(jump, std::fabs(table[i] - last[i]));
                }
            }
            last = table;
        }
        Expect(push.Restarts() == 1, "the weather: the follower started once, not at each change of the speed");
        Expect(jump < 0.05f, "the weather: the push tables move less than 5 cm between frames");
        Expect(most > 0.0f && most <= W::MaxAlong, "the weather: the push is positive and held");
    }

    // bbport (r112s_hang-bracket-move): the bracket lanterns' posts
    {
        const H::PostKnob unset = H::ParsePost(nullptr);
        Expect(unset.on && unset.count == 1 && unset.verts[0] == 13642u, "post: unset = on, 13642 vertices");
        const H::PostKnob one = H::ParsePost("1");
        Expect(one.on && one.count == 1 && one.verts[0] == 13642u, "post: 1 = the default");
        Expect(!H::ParsePost("0").on, "post: 0 = off");
        const H::PostKnob list = H::ParsePost("20000:13642 77");
        Expect(list.on && list.count == 3 && list.verts[0] == 20000u && list.verts[1] == 13642u && list.verts[2] == 77u, "post: a list");
        const H::PostKnob junk = H::ParsePost("abc");
        Expect(junk.on && junk.count == 1 && junk.verts[0] == 13642u, "post: no number = the default");
        const H::PostKnob zero = H::ParsePost("0:5");
        Expect(zero.on && zero.count == 1 && zero.verts[0] == 5u, "post: a zero in a list is none (only exactly 0 is off)");
        const H::PostKnob many = H::ParsePost("1:2:3:4:5:6:7:8:9:10");
        Expect(many.count == H::PostStreamsMost && many.verts[7] == 8u, "post: at most 8 counts");
        Expect(H::ParsePost("999999999999999").verts[0] == 100000000u, "post: a huge number is held");
        Expect(H::PostMatchesIn(unset, 13642u * 32u, 32u) && !H::PostMatchesIn(unset, 13642u * 32u, 16u) && !H::PostMatchesIn(unset, 0, 0) &&
                   H::PostMatchesIn(unset, 13642u * 32u + 31u, 32u),
               "post: a stream matches by size / stride");
        Expect(!H::PostMatchesIn(H::ParsePost("0"), 13642u * 32u, 32u), "post: off matches nothing");
        Expect(H::PostBit == (1u << 15) && (H::PostBit & H::HangBit) == 0 && (H::PostBit & W::WordOn) == 0, "post: the bit is free");
        const std::uint32_t word = H::PostWord(2, 1, 77, 200);
        Expect(H::PostOf(word) && H::HangOf(word) && word == (H::HangWord(2, 1, 77, 200) | H::PostBit) && !H::PostOf(H::HangWord(2, 1, 77, 200)),
               "post: a post's word is a hang word with PostBit");
        // the shaders' weight: 1 in the top 20 percent, 0 from 65 percent down, 0.5 half way, a bad height = 2 m
        Expect(H::PostT(0.0f, 5.66f) == 1.0f && H::PostT(0.2f * 5.66f, 5.66f) >= 0.999f, "post: full at the top 20 percent");
        Expect(H::PostT(0.65f * 5.66f, 5.66f) < 1e-5f && H::PostT(0.9f * 5.66f, 5.66f) == 0.0f && H::PostT(5.66f, 5.66f) == 0.0f,
               "post: none from 65 percent down");
        Expect(std::fabs(H::PostT(0.425f * 5.66f, 5.66f) - 0.5f) < 1e-4f, "post: half way down the ramp");
        Expect(H::PostT(1.0f, std::nanf("")) == H::PostT(1.0f, 0.5f) && H::PostT(1.0f, 0.5f) == H::PostT(1.0f, H::PostExtMin),
               "post: a height under 2 m or not a number is 2 m");
        float last = 2.0f;
        bool steps = true;
        for (int k = 0; k <= 100; ++k) {
            const float t = H::PostT(5.66f * float(k) / 100.0f, 5.66f);
            steps = steps && t >= 0.0f && t <= 1.0f && t <= last + 1e-6f;
            last = t;
        }
        Expect(steps, "post: the weight falls from the top down and stays in 0-1");
        // the keys: a post of 5.66 m measures and swings, a union of 12 m gets no word
        const std::uint32_t base_key = std::bit_cast<std::uint32_t>(-42.0f + W::HeightBias);
        const std::uint32_t top_key = H::TopKey(-36.34f);
        H::Entry e;
        const H::Measured m0 = H::Measure(e, true, 100, &base_key, &top_key, 1.0, H::PostMaxExtent);
        Expect(m0.measuring && !m0.swing, "post: the keys are read after JudgeFrames");
        const H::Measured m1 = H::Measure(e, false, 100 + H::JudgeFrames, &base_key, &top_key, 1.0, H::PostMaxExtent);
        Expect(!m1.measuring && m1.swing && e.judged && e.fits && std::fabs((e.top - e.base) - 5.66f) < 0.01f, "post: 5.66 m fits");
        const std::uint32_t tall_top = H::TopKey(-30.0f);
        H::Entry tall_entry;
        (void)H::Measure(tall_entry, true, 100, &base_key, &tall_top, 1.0, H::PostMaxExtent);
        const H::Measured m2 = H::Measure(tall_entry, false, 100 + H::JudgeFrames, &base_key, &tall_top, 1.0, H::PostMaxExtent);
        Expect(!m2.measuring && !m2.swing && tall_entry.judged && !tall_entry.fits, "post: a 12 m span (the union of far places) gets no word");
        // the book
        H::PostBook book;
        H::PostBook::Item& a = book.Touch(0x1000, 436544u, 5);
        a.entry.judged = true;
        a.entry.fits = true;
        a.entry.base = -42.0f;
        a.entry.top = -36.34f;
        Expect(&book.Touch(0x1000, 436544u, 6) == &a && a.seen == 6, "post book: the same stream, the same item");
        (void)book.Touch(0x1000, 99u, 7);
        Expect(!book.Touch(0x1000, 99u, 7).entry.judged, "post book: another size at the address forgets it");
        for (std::uint64_t k = 0; k < H::PostKept + 5; ++k) {
            (void)book.Touch(0x2000 + k, 1u, 8);
        }
        Expect(book.Items().size() <= H::PostKept, "post book: bounded");
        H::PostBook shown;
        H::PostBook::Item& b = shown.Touch(0x3000, 436544u, 1);
        b.entry.judged = true;
        b.entry.fits = true;
        b.entry.base = -42.0f;
        b.entry.top = -36.34f;
        shown.draws = 10;
        shown.measuring = 3;
        shown.pushed = 6;
        shown.unfit = 1;
        char line[700];
        H::PostLineText(shown, 0.123f, line, sizeof(line));
        Expect(std::strstr(line, "Wind sway hang post (r112s, BB_WIND_HANG_POST): since the start 10 draws of 1 streams: 3 measuring, 6 pushed, 1 with no word") == line &&
                   std::strstr(line, "1 judged, 1 swinging (the first: base y -42.00, top y -36.34, 5.66 m tall); push 0.123 m") != nullptr,
               "post: the periodic line");
        char once[1100];
        H::PostOnceText(once, sizeof(once));
        Expect(std::strstr(once, "holds 13642 vertices") != nullptr && std::strstr(once, "top 20 percent") != nullptr &&
                   std::strstr(once, "from 65 percent down") != nullptr && std::strstr(once, "(+52000)") != nullptr,
               "post: the once line");
        Expect(H::StripProofVersion(22u + 2000u + 8000u) == 22u + 2000u + 8000u, "post: the strip leaves a version with neither add");
        // bbport (r112t_hang-post-measure): the post's keys from the scene's boxes, the vertices line, the box line
        struct TestBox {
            std::uint64_t stream;
            std::array<float, 6> box;
            char src;
        };
        const std::vector<TestBox> test_boxes{
            {0x1000, {10.0f, -42.0f, 5.0f, 11.1f, -36.34f, 7.2f}, 'v'},   // a post on lower ground, 12 m away
            {0x1000, {-2.0f, -30.0f, 3.0f, -0.9f, -24.34f, 5.2f}, 'c'},   // the post near the camera, camera pass box
            {0x1000, {-2.0f, -30.01f, 3.0f, -0.9f, -24.34f, 5.2f}, 'v'},  // the same post by the sun's box
            {0x2000, {0.0f, 0.0f, 0.0f, 1.0f, 1.0f, 1.0f}, 'c'},          // another stream
            {0x1000, {std::nanf(""), 0.0f, 0.0f, 1.0f, 1.0f, 1.0f}, 'c'}, // not finite: skipped
            {0x1000, {0.0f, 5.0f, 0.0f, 1.0f, 5.0f, 1.0f}, 'c'},          // no height: skipped
        };
        const float test_camera[3] = {-2.5f, -26.0f, 0.0f};
        const H::PostPick near_pick = H::PickPost(test_boxes, 0x1000, test_camera);
        Expect(near_pick.found && near_pick.camera && near_pick.count == 3 && near_pick.src == 'c' && std::fabs(near_pick.base + 30.0f) < 1e-4f &&
                   std::fabs(near_pick.top + 24.34f) < 1e-4f && near_pick.dist > 3.9f && near_pick.dist < 4.6f,
               "post pick: the nearest post, the camera pass box wins within the tie");
        const H::PostPick no_camera = H::PickPost(test_boxes, 0x1000, nullptr);
        Expect(no_camera.found && !no_camera.camera && no_camera.dist < 0.0f && no_camera.src == 'c' && no_camera.count == 3,
               "post pick: no camera: the first box of the best source");
        Expect(!H::PickPost(test_boxes, 0x3000, test_camera).found && !H::PickPost(test_boxes, 0, test_camera).found &&
                   !H::PickPost(std::vector<TestBox>{}, 0x1000, test_camera).found,
               "post pick: no box, stream 0, no boxes: none");
        const float far_camera[3] = {11.0f, -40.0f, 6.0f};
        const H::PostPick far_pick = H::PickPost(test_boxes, 0x1000, far_camera);
        Expect(far_pick.found && far_pick.src == 'v' && std::fabs(far_pick.base + 42.0f) < 1e-4f, "post pick: from the other post the other box is nearest");
        // the keys the CPU writes read back as the box
        const std::uint32_t base_key = W::HeightKey(near_pick.base);
        const std::uint32_t top_key = H::TopKey(near_pick.top);
        Expect(std::fabs(W::KeyHeight(base_key) - near_pick.base) < 1e-3f && std::fabs(H::KeyTop(top_key) - near_pick.top) < 1e-3f &&
                   base_key != W::ResetKey && top_key != W::ResetKey,
               "post keys: written keys read back as the box");
        std::array<float, 8 * 5> raw{};
        const float ys[5] = {0.0f, 5.66f, 2.0f, 1.0f, 3.0f};
        for (int v = 0; v < 5; ++v) {
            raw[static_cast<std::size_t>(v) * 8 + 0] = static_cast<float>(v);
            raw[static_cast<std::size_t>(v) * 8 + 1] = ys[v];
            raw[static_cast<std::size_t>(v) * 8 + 2] = 0.5f * static_cast<float>(v);
            raw[static_cast<std::size_t>(v) * 8 + 3] = 1.0f;
        }
        char vertices_text[1024];
        H::PostVerticesText(reinterpret_cast<const unsigned char*>(raw.data()), static_cast<std::uint32_t>(sizeof(raw)), 32, vertices_text,
                            sizeof(vertices_text));
        Expect(std::strstr(vertices_text, "the stream holds 5 vertices (stride 32, 160 bytes)") != nullptr &&
                   std::strstr(vertices_text, "v0 (0.00, 0.00, 0.00, 1.00, 0.00, 0.00, 0.00, 0.00) v1 (1.00, 5.66, 0.50, 1.00") != nullptr &&
                   std::strstr(vertices_text, "x 0.00..4.00 (4.00 m), y 0.00..5.66 (5.66 m), z 0.00..2.00 (2.00 m)") != nullptr,
               "post vertices: the line");
        H::PostVerticesText(nullptr, 100, 32, vertices_text, sizeof(vertices_text));
        Expect(std::strstr(vertices_text, "cannot be read (not mapped, 100 bytes, stride 32)") != nullptr, "post vertices: not mapped");
        H::PostVerticesText(reinterpret_cast<const unsigned char*>(raw.data()), 8, 32, vertices_text, sizeof(vertices_text));
        Expect(std::strstr(vertices_text, "too short") != nullptr, "post vertices: too short");
        H::PostBook box_book;
        box_book.no_box = 4;
        box_book.unfit = 2;
        box_book.written = 3;
        char box_line[704];
        H::PostBoxLineText(box_book, box_line, sizeof(box_line));
        Expect(std::strstr(box_line, "no box of the stream yet") != nullptr && std::strstr(box_line, "4 draws with no box") != nullptr &&
                   std::strstr(box_line, "3 key writes") != nullptr,
               "post box line: no pick yet");
        box_book.last = near_pick;
        H::PostBoxLineText(box_book, box_line, sizeof(box_line));
        Expect(std::strstr(box_line, "3 boxes of the stream, picked (c)") != nullptr && std::strstr(box_line, "base y -30.00, top y -24.34, 5.66 m tall") != nullptr,
               "post box line: the pick");
        // bbport (r112u_hang-post-no-bridge): the guard
        Expect(H::ParsePostGuard(nullptr) && H::ParsePostGuard("") && H::ParsePostGuard("1") && !H::ParsePostGuard("0") && H::ParsePostGuard("00"),
               "post guard: the knob is on unless exactly 0");
        Expect(std::fabs(H::PostGain(0.2f) - 0.2f) < 1e-6f && std::fabs(H::PostGain(1.0f) - 0.3f) < 1e-6f && H::PostGain(std::nanf("")) == 0.0f &&
                   std::fabs(H::PostGain(1.0f) * W::MaxAlong - H::PostGuardPush) < 1e-6f,
               "post guard: the gain is held so that the push is at most 0.12 m");
        const std::vector<TestBox> guard_boxes{
            {0x5000, {0.0f, -41.0f, 0.0f, 12.0f, -35.4f, 3.0f}, 'c'},  // a bridge: 12 m wide
            {0x5001, {0.0f, 0.0f, 0.0f, 1.0f, 3.5f, 1.0f}, 'c'},        // 1 m wide, 3.5 m tall
            {0x5002, {0.0f, 2.0f, 0.0f, 0.4f, 2.9f, 0.4f}, 'c'},        // a lantern
            {0x5003, {0.0f, 0.0f, 0.0f, 0.4f, 1.0f, 0.4f}, 'c'},        // four boxes that differ: architecture
            {0x5003, {5.0f, 0.0f, 0.0f, 5.4f, 1.5f, 0.4f}, 'c'},
            {0x5003, {9.0f, 0.0f, 0.0f, 9.4f, 1.2f, 0.4f}, 'c'},
            {0x5003, {13.0f, 0.0f, 0.0f, 13.4f, 1.0f, 0.4f}, 'c'},
            {0x5004, {0.0f, 2.0f, 0.0f, 0.4f, 2.9f, 0.4f}, 'c'},        // four lanterns alike
            {0x5004, {5.0f, 2.1f, 0.0f, 5.4f, 3.0f, 0.4f}, 'c'},
            {0x5004, {9.0f, 2.0f, 3.0f, 9.4f, 2.9f, 3.4f}, 'c'},
            {0x5004, {13.0f, 1.9f, 0.0f, 13.4f, 2.8f, 0.4f}, 'c'},
            {0x5005, {0.0f, 2.0f, 0.0f, 0.4f, 2.9f, 0.4f}, 'c'},        // three that differ: few enough
            {0x5005, {5.0f, 0.0f, 0.0f, 5.4f, 1.5f, 0.4f}, 'c'},
            {0x5005, {9.0f, 0.0f, 0.0f, 9.4f, 1.0f, 0.4f}, 'c'},
            {0x5006, {0.0f, 2.0f, 0.0f, 1.6f, 2.9f, 0.4f}, 'c'},        // 1.6 m wide
            {0x5006, {0.0f, 2.0f, 0.0f, 0.4f, 2.9f, 0.4f}, 'v'},
        };
        const auto guard_of = [&](std::uint64_t stream, const float* lamps, std::size_t lamp_count) {
            return H::PostGuardCheck(guard_boxes, stream, H::PickPost(guard_boxes, stream, nullptr), lamps, lamp_count);
        };
        const H::PostGuard bridge = guard_of(0x5000, nullptr, 0);
        Expect(bridge.why == H::PostRefuse::Wide && bridge.count == 1 && std::fabs(bridge.box[3] - 12.0f) < 1e-4f, "post guard: a 12 m wide box is refused as wide");
        Expect(guard_of(0x5001, nullptr, 0).why == H::PostRefuse::Tall, "post guard: a 3.5 m tall box is refused as tall");
        Expect(guard_of(0x5002, nullptr, 0).why == H::PostRefuse::None && guard_of(0x5002, nullptr, 0).count == 1, "post guard: a lantern passes");
        Expect(guard_of(0x5003, nullptr, 0).why == H::PostRefuse::Shared && guard_of(0x5003, nullptr, 0).count == 4,
               "post guard: four boxes that differ are a shared stream");
        Expect(guard_of(0x5004, nullptr, 0).why == H::PostRefuse::None && guard_of(0x5004, nullptr, 0).count == 4, "post guard: four alike boxes pass");
        Expect(guard_of(0x5005, nullptr, 0).why == H::PostRefuse::None, "post guard: three boxes that differ are not yet a shared stream");
        Expect(guard_of(0x5006, nullptr, 0).why == H::PostRefuse::Wide, "post guard: ANY box of the stream over the limit refuses it");
        Expect(guard_of(0x9999, nullptr, 0).why == H::PostRefuse::None && guard_of(0x9999, nullptr, 0).count == 0 &&
                   H::PostGuardCheck(guard_boxes, 0, H::PostPick{}, nullptr, 0).why == H::PostRefuse::None,
               "post guard: no box, stream 0: nothing to refuse");
        const float near_lamp[3] = {0.2f, 2.5f, 0.2f}, far_lamp[3] = {0.2f, 5.0f, 0.2f}, below_lamp[3] = {0.2f, 1.2f, 0.2f};
        Expect(guard_of(0x5002, near_lamp, 1).why == H::PostRefuse::None && guard_of(0x5002, below_lamp, 1).why == H::PostRefuse::None &&
                   guard_of(0x5002, far_lamp, 1).why == H::PostRefuse::NoLamp,
               "post guard: the lamp rule: a light within 1 m of the box's lower end passes, one 3 m above refuses, none given: not applied");
        Expect(guard_of(0x5000, near_lamp, 1).why == H::PostRefuse::Wide, "post guard: the size rule comes before the lamp rule");
        char guard_text[704];
        H::PostGuardText(0x5000, bridge, guard_text, sizeof(guard_text));
        Expect(std::strstr(guard_text, "stream 0x5000 REFUSED (a box wider than the limit): 1 boxes") != nullptr &&
                   std::strstr(guard_text, "x 0.00..12.00 (12.00 m)") != nullptr && std::strstr(guard_text, "never pushed") != nullptr,
               "post guard: the line per refused stream");
        H::PostGuardOnceText(guard_text, sizeof(guard_text));
        Expect(std::strstr(guard_text, "wider than 1.5 m or taller than 3.0 m") != nullptr && std::strstr(guard_text, "at most 0.12 m (gain at most 0.30)") != nullptr,
               "post guard: the once line");
        H::PostBook guard_book;
        guard_book.draws = 9;
        guard_book.refused = 5;
        guard_book.refused_streams = 2;
        guard_book.by_reason[static_cast<std::size_t>(H::PostRefuse::Wide)] = 4;
        guard_book.by_reason[static_cast<std::size_t>(H::PostRefuse::Tall)] = 1;
        H::PostGuardLineText(guard_book, guard_text, sizeof(guard_text));
        Expect(std::strstr(guard_text, "5 post draws refused of 9 (2 streams): wide 4, tall 1, shared 0, no lamp 0") != nullptr,
               "post guard: the counter line");
    }

    if (failures != 0) {
        std::printf("wind-hang-test: %d FAILED\n", failures);
        return 1;
    }
    std::printf("wind-hang-test: ok\n");
    return 0;
}
