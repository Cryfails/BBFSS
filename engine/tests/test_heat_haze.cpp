// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97_heat-haze): the heat haze's pure parts (heat_haze.h): the knobs' text, which lamps
// are flames, the lamps kept once, the column above a flame on the screen (up, leaning with the
// wind, fading with distance, left out where it cannot show) and the choice and placing of a
// frame's columns in the atlas.
#include <algorithm>
#include <array>
#include <bit>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string_view> // bbport (r97b_heat-haze-paths)
#include <vector>
#include "gpu/shadps4/video_core/renderer_vulkan/heat_haze.h"
#include "gpu/shadps4/video_core/renderer_vulkan/heat_haze_flames.h" // bbport (r97f_haze-per-flame)
#include "gpu/shadps4/video_core/renderer_vulkan/strength_knob.h" // bbport (r97e_heat-haze-option)

using namespace BbHeatHaze;

namespace {
std::array<std::uint32_t, RecordWords> Record(float x, float y, float z, float reach, float r,
                                              float g, float b) {
    std::array<std::uint32_t, RecordWords> record{};
    const float words[7] = {x, y, z, reach > 0.0f ? 1.0f / (reach * reach) : 0.0f, r, g, b};
    for (int i = 0; i < 7; ++i) {
        record[i] = std::bit_cast<std::uint32_t>(words[i]);
    }
    record[9] = 0xdeadbeefu; // words the game keeps other things in: not part of the key
    return record;
}

Lamp Torch(float x, float y, float z, float reach = 8.5f) {
    return Lamp{{x, y, z}, reach, {2.49f, 1.40f, 0.63f}};
}

// A camera looking down view +z, world +y up, ndc +y down the screen (the y scale negative).
Camera Straight(std::uint32_t width = 1920, std::uint32_t height = 1080) {
    Camera camera;
    camera.view = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
    camera.inv_view = camera.view;
    camera.proj = {1.7f * 1080.0f / 1920.0f, -1.7f, 1.0f, -0.1f};
    camera.width = width;
    camera.height = height;
    return camera;
}

bool Near(float a, float b, float tolerance) {
    return std::abs(a - b) <= tolerance;
}

bool Inside(const Push& push, float x, float y) {
    return x >= float(push.rect[0]) && x <= float(push.rect[0] + push.rect[2]) &&
           y >= float(push.rect[1]) && y <= float(push.rect[1] + push.rect[3]);
}
} // namespace

int main() {
    // a. The knobs.
    {
        assert(Parse(nullptr, nullptr).strength == 0.0f && !Parse(nullptr, nullptr).unreadable);
        // bbport (r97e_heat-haze-option): off by default; the key decides unless the variable is set
        // (set and not empty: it wins, also with 0 and with text that is no number); a key outside
        // 0..2 is the nearest end; a key that is not finite is the default.
        static_assert(DefaultStrength == 0.0f);
        const auto pick = [](const char* variable, float key) {
            return StrengthKnob::Pick(StrengthKnob::ReadEnv(variable, MaxStrength), key, MaxStrength,
                                      DefaultStrength);
        };
        assert(pick(nullptr, DefaultStrength).value == 0.0f && !pick(nullptr, DefaultStrength).from_env);
        assert(pick(nullptr, 1.0f).value == 1.0f && pick("", 1.0f).value == 1.0f && !pick("", 1.0f).from_env);
        assert(pick(nullptr, 2.0f).value == 2.0f && pick(nullptr, 9.0f).value == MaxStrength);
        assert(pick(nullptr, -1.0f).value == 0.0f && pick(nullptr, std::nanf("")).value == DefaultStrength);
        assert(pick("0.5", 1.0f).value == 0.5f && pick("0.5", 1.0f).from_env);
        assert(pick("0", 1.0f).value == 0.0f && pick("0", 1.0f).from_env);
        assert(pick("abc", 1.0f).value == 0.0f && pick("abc", 1.0f).from_env);
        assert(pick("5", 0.0f).value == MaxStrength);
        assert(Parse("", "1").strength == 0.0f && !Parse("", "1").show);
        assert(Parse("1", nullptr).strength == 1.0f && !Parse("1", nullptr).show);
        assert(Parse("0.5", "1").strength == 0.5f && Parse("0.5", "1").show);
        assert(Parse("2.5", nullptr).strength == MaxStrength);
        assert(Parse("-1", "1").strength == 0.0f && !Parse("-1", "1").unreadable &&
               !Parse("-1", "1").show);
        assert(Parse("0", "1").strength == 0.0f && !Parse("0", "1").show);
        assert(Parse("on", nullptr).unreadable && Parse("on", nullptr).strength == 0.0f);
        assert(Parse("1 ", nullptr).unreadable && Parse("nan", nullptr).unreadable &&
               Parse("inf", nullptr).unreadable);
        // bbport (r97b_heat-haze-paths): "2" is the test view with rectangles and no depth test
        assert(Parse("1", "2").show && Parse("1", "2").outline && !Parse("1", "1").outline);
        assert(!Parse("0", "2").show && !Parse("0", "2").outline && !Parse("1", nullptr).outline);
        assert(!Parse("1", "3").show && !Parse("1", "11").show && !Parse("1", "").show &&
               !Parse("1", "22").outline);
        assert(Parse("1", nullptr).depth && DepthTests(nullptr) && DepthTests("") &&
               DepthTests("1") && DepthTests("00") && !DepthTests("0"));
    }
    // b. A record as a lamp.
    {
        const auto torch = Record(1, 2, 3, 8.5f, 2.49f, 1.40f, 0.63f);
        const auto lamp = ReadLamp(torch.data());
        assert(lamp && Near(lamp->reach, 8.5f, 1e-4f) && lamp->view[2] == 3.0f &&
               lamp->colour[0] == 2.49f);
        assert(!ReadLamp(Record(1, 2, 3, 0.0f, 1, 1, 1).data()));
        auto bad = torch;
        bad[5] = std::bit_cast<std::uint32_t>(NAN);
        assert(!ReadLamp(bad.data()));
    }
    // c. Flames: warm and of a flame's reach; not white, cold, red or huge.
    {
        assert(IsFlame(Torch(0, 0, 3)));
        assert(IsFlame(Lamp{{0, 0, 3}, 3.0f, {1.0f, 0.7f, 0.4f}}));   // a warm yellow candle
        assert(!IsFlame(Lamp{{0, 0, 3}, 8.0f, {1.0f, 1.0f, 1.0f}}));  // white
        assert(!IsFlame(Lamp{{0, 0, 3}, 8.0f, {1.0f, 0.9f, 0.8f}}));  // warm white
        assert(!IsFlame(Lamp{{0, 0, 3}, 8.0f, {0.4f, 0.6f, 1.0f}}));  // cold (moonlight)
        assert(!IsFlame(Lamp{{0, 0, 3}, 8.0f, {1.0f, 0.1f, 0.0f}}));  // red
        assert(!IsFlame(Lamp{{0, 0, 3}, 8.0f, {0.01f, 0.006f, 0.002f}})); // too dim
        assert(!IsFlame(Torch(0, 0, 3, 30.0f)) && !IsFlame(Torch(0, 0, 3, 0.3f)));
    }
    // d. The collector keeps each flame once and counts the rest.
    {
        Collector collector;
        std::vector<std::uint32_t> list;
        for (int tile = 0; tile < 3; ++tile) { // the same two lamps in three tiles
            const auto a = Record(0, 0, 3, 8.5f, 2.49f, 1.40f, 0.63f);
            const auto b = Record(0, 0, 4, 5.0f, 0.4f, 0.6f, 1.0f); // cold: not a flame
            list.insert(list.end(), a.begin(), a.end());
            list.insert(list.end(), b.begin(), b.end());
        }
        collector.Add(list.data(), 6);
        assert(collector.Lamps().size() == 1 && collector.Records() == 6 &&
               collector.Others() == 3 && collector.Dropped() == 0);
        // More flames than MaxLamps, the farthest first (tile order is no order of distance):
        // the MaxLamps nearest are kept.
        list.clear();
        for (std::uint32_t i = 0; i < MaxLamps + 5; ++i) {
            const float x = 0.2f * float(MaxLamps + 4 - i);
            const auto r = Record(x, 0, 5, 8.5f, 2.49f, 1.40f, 0.63f);
            list.insert(list.end(), r.begin(), r.end());
        }
        collector.Clear();
        assert(collector.Lamps().empty() && collector.Records() == 0);
        collector.Add(list.data(), MaxLamps + 5);
        assert(collector.Lamps().size() == MaxLamps && collector.Dropped() == 5);
        float nearest_x = 100.0f, farthest_x = 0.0f;
        for (const Lamp& lamp : collector.Lamps()) {
            nearest_x = std::min(nearest_x, lamp.view[0]);
            farthest_x = std::max(farthest_x, lamp.view[0]);
        }
        assert(nearest_x == 0.0f && Near(farthest_x, 0.2f * float(MaxLamps - 1), 1e-4f));
        // Flames behind the camera plane or FadeEnd away are not kept, only counted.
        list.clear();
        for (const float z : {-1.0f, 0.1f, FadeEnd + 0.5f, 3.0f}) {
            const auto r = Record(0, 0, z, 8.5f, 2.49f, 1.40f, 0.63f);
            list.insert(list.end(), r.begin(), r.end());
        }
        collector.Clear();
        collector.Add(list.data(), 4);
        assert(collector.Lamps().size() == 1 && collector.Beyond() == 3 && collector.Others() == 0 &&
               collector.Lamps()[0].view[2] == 3.0f);
    }
    // e. The column above a torch 3 m ahead: from the flame up the screen.
    const std::array<float, 3> still{};
    {
        const Camera camera = Straight();
        const auto column = MakeColumn(Torch(0, 0, 3), camera, 1.0f, false, still);
        assert(column);
        const Push& p = column->push;
        assert(Near(p.axis[0], 960.0f, 0.01f) && Near(p.axis[1], 540.0f, 0.01f));
        assert(Near(p.axis[2], 960.0f, 0.01f) && p.axis[3] < p.axis[1] - 50.0f); // up
        // 8.5 m reach: 0.595 m tall, 0.1275 m radius; 306 pixels a metre at 3 m.
        const float per_metre = 0.5f * 1080.0f * 1.7f / 3.0f;
        assert(Near(p.field[0], per_metre, 0.01f));
        assert(Near(p.axis[1] - p.axis[3], 0.595f * per_metre, 0.05f));
        assert(Near(p.shape[0], 0.1275f * per_metre, 0.01f) && p.shape[1] == Widen);
        assert(Near(p.shape[2], std::min(AmplitudeM * per_metre, MaxAmplitudePx), 1e-3f) &&
               p.shape[3] == 3.0f);
        assert(Near(p.field[1], 0.1275f + DepthMarginM, 1e-5f) && p.field[2] == 1.0f);
        assert(p.clock[0] == 1.0f && p.clock[1] == -0.1f && p.clock[3] == RiseMps);
        assert(p.atlas[2] == PassHaze && p.atlas[3] == 0);
        assert(Inside(p, p.axis[0], p.axis[1]) && Inside(p, p.axis[2], p.axis[3]));
        assert(p.rect[0] >= 0 && p.rect[1] >= 0 && p.rect[0] + p.rect[2] <= 1920 &&
               p.rect[1] + p.rect[3] <= 1080);
        // Strength and the test view scale the shimmer; jitter moves the column with the frame.
        const auto strong = MakeColumn(Torch(0, 0, 3), camera, 2.0f, false, still);
        const auto shown = MakeColumn(Torch(0, 0, 3), camera, 1.0f, true, still);
        assert(Near(strong->push.shape[2], 2.0f * p.shape[2], 1e-4f));
        assert(Near(shown->push.shape[2], ShowGain * p.shape[2], 1e-4f) &&
               shown->push.atlas[3] == FlagShow);
        Camera jittered = camera;
        jittered.jitter = {0.25f, -0.5f};
        const auto moved = MakeColumn(Torch(0, 0, 3), jittered, 1.0f, false, still);
        assert(Near(moved->push.axis[0], 960.25f, 1e-3f) && Near(moved->push.axis[1], 539.5f, 1e-3f));
        // The shimmer is capped near the camera (8 pixels a 1080 rows at strength 1).
        const auto close = MakeColumn(Torch(0, 0, 0.35f), camera, 1.0f, false, still);
        assert(close && Near(close->push.shape[2], MaxAmplitudePx, 1e-4f));
        // At 4K rows the same torch spans twice the pixels.
        const auto big = MakeColumn(Torch(0, 0, 3), Straight(3840, 2160), 1.0f, false, still);
        assert(Near(big->push.field[0], 2.0f * per_metre, 0.02f));
    }
    // f. The wind leans the top downwind, at most MaxLean of the height.
    {
        const Camera camera = Straight();
        const auto upright = MakeColumn(Torch(0, 0, 3), camera, 1.0f, false, still);
        const auto windy = MakeColumn(Torch(0, 0, 3), camera, 1.0f, false, {2.0f, 0.0f, 0.0f});
        const auto storm = MakeColumn(Torch(0, 0, 3), camera, 1.0f, false, {100.0f, 0.0f, 0.0f});
        const auto back = MakeColumn(Torch(0, 0, 3), camera, 1.0f, false, {-2.0f, 0.0f, 0.0f});
        const float per_metre = upright->push.field[0];
        assert(windy->push.axis[2] > upright->push.axis[2] + 10.0f); // toward +x: right
        assert(back->push.axis[2] < upright->push.axis[2] - 10.0f);
        // (The top is 0.595 m up and 0.15 m a m/s x 2 m/s of that across, at the flame's depth.)
        assert(Near(windy->push.axis[2] - 960.0f, 0.595f * 0.3f * per_metre, 0.5f));
        assert(Near(storm->push.axis[2] - 960.0f, 0.595f * MaxLean * per_metre, 0.5f));
        const auto nan_wind = MakeColumn(Torch(0, 0, 3), camera, 1.0f, false, {NAN, 0.0f, 0.0f});
        assert(nan_wind && Near(nan_wind->push.axis[2], upright->push.axis[2], 1e-3f));
    }
    // g. No column behind the camera, too far, off the screen, or at strength 0; a fade between.
    {
        const Camera camera = Straight();
        assert(!MakeColumn(Torch(0, 0, -1), camera, 1.0f, false, still));
        assert(!MakeColumn(Torch(0, 0, 0.2f), camera, 1.0f, false, still));
        assert(!MakeColumn(Torch(0, 0, FadeEnd + 1.0f), camera, 1.0f, false, still));
        assert(!MakeColumn(Torch(100, 0, 3), camera, 1.0f, false, still));
        assert(!MakeColumn(Torch(0, 0, 3), camera, 0.0f, false, still));
        const auto mid = MakeColumn(Torch(0, 0, 18.5f), camera, 1.0f, false, still);
        assert(mid && mid->push.field[2] > 0.3f && mid->push.field[2] < 0.7f);
        const auto inside = MakeColumn(Torch(0, 0, FadeStart - 1.0f), camera, 1.0f, false, still);
        assert(inside && inside->push.field[2] == 1.0f);
        // Looking straight up at it (the world's up is view +z), the column is a dot: none.
        Camera down = camera;
        down.view = {1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0};
        assert(!MakeColumn(Torch(0, 0, 3), down, 1.0f, false, still));
        // A torch at the screen's edge keeps a column cut to the screen.
        const auto edge = MakeColumn(Torch(-2.05f, 0, 2.0f), camera, 1.0f, false, still);
        assert(edge && edge->push.rect[0] == 0 && edge->push.rect[2] > 0);
    }
    // h. The frame's columns: the largest eight, placed apart in the atlas, farthest first.
    {
        const Camera camera = Straight();
        std::vector<Lamp> lamps;
        for (int i = 0; i < 10; ++i) {
            lamps.push_back(Torch(-2.0f + 0.4f * float(i), 0.0f, 3.0f + float(i)));
        }
        lamps.push_back(Torch(0, 0, -2)); // behind
        Counts counts;
        const Atlas atlas = AtlasFor(1920, 1080);
        assert(atlas.width == 960 && atlas.height == 540);
        const auto columns = Choose(lamps, camera, 1.0f, false, still, atlas, counts);
        assert(counts.unseen == 1 && counts.over == 2 && counts.no_room == 0);
        assert(columns.size() == MaxColumns && counts.made == MaxColumns);
        for (std::size_t i = 0; i < columns.size(); ++i) {
            const Push& a = columns[i].push;
            assert(a.atlas[0] >= 0 && a.atlas[1] >= 0 && a.atlas[0] + a.rect[2] <= 960 &&
                   a.atlas[1] + a.rect[3] <= 540);
            if (i > 0) {
                assert(columns[i - 1].distance >= columns[i].distance);
            }
            for (std::size_t j = 0; j < i; ++j) {
                const Push& b = columns[j].push;
                const bool apart = a.atlas[0] + a.rect[2] <= b.atlas[0] ||
                                   b.atlas[0] + b.rect[2] <= a.atlas[0] ||
                                   a.atlas[1] + a.rect[3] <= b.atlas[1] ||
                                   b.atlas[1] + b.rect[3] <= a.atlas[1];
                assert(apart);
            }
        }
        // The two left out are the smallest (the farthest).
        for (const Column& column : columns) {
            assert(column.distance <= 10.0f + 0.5f);
        }
        // An atlas too small for all of them leaves some out, never one that overlaps.
        const auto few = Choose(lamps, camera, 1.0f, false, still, Atlas{160, 120}, counts);
        assert(counts.no_room > 0 && few.size() + counts.no_room == MaxColumns);
        for (const Column& column : few) {
            assert(column.push.rect[2] <= 160 && column.push.rect[3] <= 120);
        }
        // Nothing to draw: nothing chosen.
        assert(Choose({}, camera, 1.0f, false, still, atlas, counts).empty() && counts.made == 0);
    }
    // i. A column taller than the atlas is cut, keeping the flame's end.
    {
        std::int32_t from = 100, size = 500;
        CutSide(from, size, 200, 560.0f, 150.0f, 10); // rising up the screen: keep the bottom
        assert(size == 200 && from == 560 + 10 - 200);
        from = 100;
        size = 500;
        CutSide(from, size, 200, 150.0f, 560.0f, 10); // upside down: keep the top
        assert(size == 200 && from == 140);
        from = 100;
        size = 500;
        CutSide(from, size, 200, 590.0f, 150.0f, 10); // never past the rectangle's end
        assert(size == 200 && from == 400);
        from = 100;
        size = 150;
        CutSide(from, size, 200, 560.0f, 150.0f, 10); // fits: unchanged
        assert(from == 100 && size == 150);
    }
    // j. Which columns are drawn does not depend on the render size or on the test view.
    {
        for (const float z : {9.0f, 18.5f, 20.0f, 23.0f}) {
            const bool full = MakeColumn(Torch(0, 0, z), Straight(1920, 1080), 1.0f, false, still)
                                  .has_value();
            const bool low = MakeColumn(Torch(0, 0, z), Straight(640, 360), 1.0f, false, still)
                                 .has_value();
            const bool shown = MakeColumn(Torch(0, 0, z), Straight(640, 360), 1.0f, true, still)
                                   .has_value();
            assert(full == low && low == shown);
            assert(full == (z < 19.0f)); // 18.5 m: 1.11 px per 1080 rows; 20 m: 0.68 px (r97c: 0.9 least)
        }
    }
    // k. bbport (r97b_heat-haze-paths): the pass's counters and what the log line makes of them.
    {
        std::array<std::uint32_t, CounterWords> before{}, now{};
        before[HH_WORD_RECT] = 0xfffffff0u; // a total that wrapped since the last line
        now[HH_WORD_RECT] = 0x10u;
        now[HH_WORD_WRITTEN] = 7u;
        PixelCounts c = CountsBetween(now.data(), before.data());
        assert(c.rect == 0x20u && c.written == 7u && c.shape == 0u && c.Tested() == 0x20u);
        PixelCounts none;
        assert(std::string_view(Verdict(none)).starts_with("no pixel"));
        PixelCounts shape_only;
        shape_only.rect = shape_only.shape = 100;
        assert(std::string_view(Verdict(shape_only)).starts_with("every pixel fell outside"));
        PixelCounts zero_depth; // a depth of 0: every view z at the near plane
        zero_depth.rect = 1000;
        zero_depth.shape = 400;
        zero_depth.z_close = 600;
        zero_depth.nearer = 600;
        assert(std::string_view(Verdict(zero_depth)).find("not this view's depth") !=
               std::string_view::npos);
        PixelCounts covered = zero_depth; // a real wall in front of the flame
        covered.z_close = 0;
        covered.z_front = 600;
        assert(std::string_view(Verdict(covered)).find("something nearer") != std::string_view::npos);
        PixelCounts shown = covered;
        shown.z_front = 100;
        shown.z_behind = 500;
        shown.nearer = 100;
        shown.written = 500;
        assert(std::string_view(Verdict(shown)).starts_with("pixels written: if"));
        PixelCounts forced = zero_depth; // depth tests off: written, the depth still unusable
        forced.written = 600;
        assert(std::string_view(Verdict(forced)).find("not this view's depth") !=
               std::string_view::npos);
        PixelCounts hidden = covered; // depth tests counted only: written, all would be dropped
        hidden.written = 600;
        assert(std::string_view(Verdict(hidden)).find("counted only, would drop) 90% or more") !=
               std::string_view::npos);
        hidden.written = 30; // depth tests on: 570 dropped, 30 written
        hidden.nearer = 570;
        assert(std::string_view(Verdict(hidden)).find("counted only, would drop) 90% or more") !=
               std::string_view::npos);
        for (const PixelCounts& v : {none, shape_only, zero_depth, covered, shown, forced, hidden}) {
            assert(std::string_view(Verdict(v)).size() < 250); // a slot log keeps 300 characters
        }
    }
    // l. bbport (r97c_heat-haze-visible): the shimmer is big enough to show at 1080 rows.
    {
        const Camera camera = Straight();
        const auto near_torch = MakeColumn(Torch(0, 0, 4.6f), camera, 1.0f, false, still);
        const auto far_torch = MakeColumn(Torch(0, 0, 10.0f), camera, 1.0f, false, still);
        assert(near_torch && far_torch);
        // (this camera's y scale 1.7 is a narrower view than the game's 2.54: 200 and 92 pixels a metre)
        assert(near_torch->push.shape[2] >= 8.0f && far_torch->push.shape[2] >= 4.0f);
        assert(AmplitudeM >= 0.04f && MaxAmplitudePx >= 9.0f);
        // The same share of the screen at 4K rows: twice the pixels.
        const auto big = MakeColumn(Torch(0, 0, 4.6f), Straight(3840, 2160), 1.0f, false, still);
        assert(big && Near(big->push.shape[2], 2.0f * near_torch->push.shape[2], 0.05f));
    }
    // m. bbport (r97d_heat-haze-real-shimmer): the offset counters, the flag and the report.
    {
        static_assert(CounterWords == HH_WORD_OFF_MAX + 1);
        std::array<std::uint32_t, CounterWords> before{}, now{};
        const auto none = OffsetsBetween(now.data(), before.data());
        assert(none.pixels == 0 && none.mean == 0.0 && none.p95_below == 0.0 && none.largest == 0.0);
        now[HH_WORD_OFF_BIN0 + 2] = 90; // 90 pixels of 0.5 to 1 px
        now[HH_WORD_OFF_BIN0 + 4] = 10; // 10 of 2 to 4 px
        now[HH_WORD_OFF_SUM] = 16u * 100u; // 100 px in all
        now[HH_WORD_OFF_MAX] = 16u * 3u;   // largest 3 px
        const auto s = OffsetsBetween(now.data(), before.data());
        assert(s.pixels == 100 && Near(float(s.mean), 1.0f, 1e-4f) && s.p95_below == 4.0 &&
               Near(float(s.largest), 3.0f, 1e-4f));
        before = now; // a second read with nothing new: the counts are differences, the maximum is not
        const auto again = OffsetsBetween(now.data(), before.data());
        assert(again.pixels == 0 && Near(float(again.largest), 3.0f, 1e-4f));
        before[HH_WORD_OFF_BIN0] = 0xfffffff0u; // a total that wrapped
        now[HH_WORD_OFF_BIN0] = 0x10u;
        assert(OffsetsBetween(now.data(), before.data()).pixels == 0x20u);
        assert((FlagProof & (FlagShow | FlagOutline | FlagNoDepth | FlagProbe)) == 0);
        assert(!Parse("1", nullptr).proof); // read in vk_heat_haze.cpp, off in Parse
    }
    // n. bbport (r97f_haze-per-flame): the flames found around a lamp, the table and the sources.
    {
        assert(ParseFlames(nullptr) == FlamesDefault && ParseFlames("") == FlamesDefault);
        assert(ParseFlames("0") == FlameMode::Off && ParseFlames("1") == FlameMode::Anchors &&
               ParseFlames("2") == FlameMode::AnchorsOrLight);
        assert(ParseFlames("3") == FlameMode::Off && ParseFlames("x") == FlameMode::Off &&
               ParseFlames("01") == FlameMode::Off);
        assert(ParseBlobMin(nullptr) == BlobMinDefault && ParseBlobMin("2") == 2.0f &&
               ParseBlobMin("0.001") == BlobMinLowest && ParseBlobMin("500") == BlobMinHighest &&
               ParseBlobMin("abc") == BlobMinDefault);
        // A block as the shader writes it, and what a torn, a blank and a wild one read as.
        std::array<std::uint32_t, HF_BLOCK_WORDS> w{};
        const auto put = [&w](std::uint32_t word, float value) {
            w[word] = std::bit_cast<std::uint32_t>(value);
        };
        w[HF_WORD_ID] = 256;
        w[HF_WORD_TAG] = 9;
        w[HF_WORD_COUNT] = 1;
        put(HF_WORD_BEST, 2.0f);
        put(HF_WORD_PEAK0, 0.5f);
        put(HF_WORD_PEAK0 + 1, -0.25f);
        put(HF_WORD_PEAK0 + 2, 2.0f);
        put(HF_WORD_BRIGHT, 7.0f);
        w[HF_WORD_CELLS] = 900;
        w[HF_WORD_CHECK] = BlockCheck(w.data());
        Block got;
        assert(ReadBlock(w.data(), got) == ReadKind::Ok && got.id == 256 && got.tag == 9 &&
               got.count == 1 && got.cells == 900 && Near(got.x[0], 0.5f, 1e-6f) &&
               Near(got.y[0], -0.25f, 1e-6f) && Near(got.blob[0], 2.0f, 1e-6f) &&
               Near(got.bright, 7.0f, 1e-6f));
        auto torn = w;
        torn[HF_WORD_PEAK0] ^= 0x1000u;
        assert(ReadBlock(torn.data(), got) == ReadKind::Torn);
        const std::array<std::uint32_t, HF_BLOCK_WORDS> blank{};
        assert(ReadBlock(blank.data(), got) == ReadKind::Blank);
        auto many = w;
        many[HF_WORD_COUNT] = 4;
        many[HF_WORD_CHECK] = BlockCheck(many.data());
        assert(ReadBlock(many.data(), got) == ReadKind::Bad);
        auto wild = w;
        wild[HF_WORD_PEAK0] = std::bit_cast<std::uint32_t>(10.0f); // outside the scanned square
        wild[HF_WORD_CHECK] = BlockCheck(wild.data());
        assert(ReadBlock(wild.data(), got) == ReadKind::Bad);
        // The table: a lamp is the same one within 0.4 m of where it was seen (in the world).
        const std::array<float, 12> identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        FlameTable table;
        const std::array<float, 3> at{0.0f, 0.0f, 5.0f};
        const std::uint32_t id = table.Touch(at, 1);
        assert(id == ((1u << 8) | 0u));
        assert(table.Touch({0.1f, 0.0f, 5.0f}, 2) == id);
        assert(table.Touch({3.0f, 0.0f, 5.0f}, 3) == ((1u << 8) | 1u));
        assert(table.Match(at) != nullptr && !table.Match(at)->answered);
        assert(table.Match({50.0f, 0.0f, 5.0f}) == nullptr);
        Block first;
        first.id = id;
        first.tag = 3;
        first.count = 2;
        first.x = {0.5f, -1.0f, 0.0f};
        first.y = {0.2f, 0.1f, 0.0f};
        first.blob = {2.0f, 1.0f, 0.0f};
        assert(table.Apply(first, identity) == ApplyResult::Anchors);
        const Entry& entry = table.At(0);
        assert(entry.answered && entry.count == 2 && Near(entry.anchors[0].offset[0], 0.5f, 1e-5f) &&
               Near(entry.anchors[1].offset[0], -1.0f, 1e-5f) &&
               Near(entry.anchors[1].offset[1], 0.1f, 1e-5f));
        assert(table.Apply(first, identity) == ApplyResult::Same); // the same tag again
        Block dead = first; // an answer for another life of the entry
        dead.id = (2u << 8) | 0u;
        dead.tag = 4;
        assert(table.Apply(dead, identity) == ApplyResult::Unknown);
        Block second = first; // one flame again near the first: the kept one moves 0.4 of the way
        second.tag = 4;
        second.count = 1;
        second.x = {0.6f, 0.0f, 0.0f};
        second.y = {0.2f, 0.0f, 0.0f};
        assert(table.Apply(second, identity) == ApplyResult::Anchors);
        assert(entry.count == 1 && Near(entry.anchors[0].offset[0], 0.54f, 1e-5f));
        assert(table.Apply(first, identity) == ApplyResult::Same); // (review) an older tag: not taken again
        Block nothing;
        nothing.id = id;
        nothing.count = 0;
        for (std::uint32_t tag = 5; tag < 12; ++tag) { // 7 answers with no flame: the flame stays
            nothing.tag = tag;
            const ApplyResult r = table.Apply(nothing, identity);
            assert(r == ApplyResult::Empty);
        }
        assert(entry.count == 1);
        nothing.tag = 12; // the 8th: it goes
        assert(table.Apply(nothing, identity) == ApplyResult::Empty);
        assert(entry.count == 0 && entry.answered);
        // The sources: a lamp's found flames, at the lamp's place plus the flame's offset.
        const Camera camera = Straight();
        const Lamp lamp = Torch(0.0f, 0.0f, 5.0f);
        const std::array<Lamp, 1> lamps{lamp};
        FlameTable t2;
        const std::uint32_t lid = t2.Touch(Transform(camera.inv_view, lamp.view), 1);
        FlameCounts counts;
        assert(FlameSources(lamps, t2, camera, FlameMode::Anchors, counts).empty() &&
               counts.unscanned == 1);
        assert(FlameSources(lamps, t2, camera, FlameMode::AnchorsOrLight, counts).size() == 1 &&
               counts.unscanned == 1);
        Block found = first;
        found.id = lid;
        found.tag = 1;
        assert(t2.Apply(found, camera.inv_view) == ApplyResult::Anchors);
        const auto sources = FlameSources(lamps, t2, camera, FlameMode::Anchors, counts);
        assert(sources.size() == 2 && counts.anchored == 1 && counts.flames == 2 &&
               Near(sources[0].view[0], 0.5f, 1e-5f) && Near(sources[0].view[1], 0.2f, 1e-5f) &&
               Near(sources[0].view[2], 5.0f, 1e-5f) && Near(sources[0].reach, lamp.reach, 1e-6f));
        // The camera moved 1 m to the right: the lamp's record is 1 m to the left in the view, the
        // table still knows it by its place in the world, and the flames follow it.
        Camera moved = Straight();
        moved.view[3] = -1.0f;
        moved.inv_view[3] = 1.0f;
        const std::array<Lamp, 1> shifted{Torch(-1.0f, 0.0f, 5.0f)};
        const auto after = FlameSources(shifted, t2, moved, FlameMode::Anchors, counts);
        assert(after.size() == 2 && Near(after[0].view[0], -0.5f, 1e-5f) &&
               Near(after[1].view[0], -2.0f, 1e-5f));
        Block none_found = found; // answered, none found (8 answers drop the flames)
        for (std::uint32_t tag = 2; tag < 10; ++tag) {
            none_found.tag = tag;
            none_found.count = 0;
            (void)t2.Apply(none_found, camera.inv_view);
        }
        assert(FlameSources(lamps, t2, camera, FlameMode::Anchors, counts).empty() && counts.empty == 1);
        assert(FlameSources(lamps, t2, camera, FlameMode::AnchorsOrLight, counts).size() == 1);
        // The scans: the 8 nearest lamps, nearest first, the light's pixel and pixels a metre, off-screen ones skipped.
        FlameTable t3;
        std::vector<Lamp> row;
        for (int i = 0; i < 10; ++i) {
            row.push_back(Torch(0.0f, 0.0f, 3.0f + float(i)));
        }
        const auto jobs = PlanScans(row, t3, camera, 7, 1, 0.5f);
        assert(jobs.size() == MaxScans && jobs[0].id != jobs[1].id);
        assert(Near(jobs[0].distance, 3.0f, 1e-4f) && jobs[0].distance < jobs[1].distance);
        assert(jobs[0].push.info[0] == 0 && jobs[1].push.info[0] == 1 && jobs[0].push.info[2] == 7);
        assert(Near(jobs[0].push.centre[0], 960.0f, 0.01f) && Near(jobs[0].push.centre[1], 540.0f, 0.01f));
        assert(Near(jobs[0].push.centre[2], 0.5f * 1920.0f * camera.proj[0] / 3.0f, 0.01f) &&
               jobs[0].push.centre[3] < 0.0f);
        assert(jobs[0].push.window[0] == ScanHalfM && jobs[0].push.window[1] == 0.5f &&
               jobs[0].push.window[2] == 1920.0f && jobs[0].push.window[3] == 1080.0f);
        const std::array<Lamp, 1> aside{Torch(100.0f, 0.0f, 5.0f)};
        assert(PlanScans(aside, t3, camera, 8, 2, 0.5f).empty());
        // (review) two lights 0.2 m apart match one entry: its flames are given once
        const std::array<Lamp, 2> pair{lamp, Torch(0.2f, 0.0f, 5.0f)};
        Block again = found;
        again.tag = 20;
        assert(t2.Apply(again, camera.inv_view) == ApplyResult::Anchors);
        assert(FlameSources(pair, t2, camera, FlameMode::Anchors, counts).size() == 2 && counts.anchored == 1);
    }
    std::printf("heat-haze-test: all checks passed\n");
    return 0;
}
