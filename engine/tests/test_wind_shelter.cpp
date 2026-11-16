// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r117_wind-shelter): the wind shelter field's knob, layout, reader and model
// (gpu/shim/bbport_wind_shelter.h). The model's numbers were first worked out in a Python copy
// (scratch r117_src/twin.py); the GLSL copy (host_shaders/wind_shelter.comp, wind_shelter.glsl) and
// the two shader emitters are checked by compiling them (glslangValidator, spirv-val) and in the
// game, not here.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <vector>

#include "gpu/shim/bbport_wind_shelter.h"

using namespace BbWindShelter;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

bool Near(float a, float b, float tolerance) {
    return std::fabs(a - b) <= tolerance;
}

// A grid of columns: a lambda gives (bot, top) or "unknown".
Column Flat(int, int) {
    return ColumnOf(0.0f, 0.0f);
}
Column Wall(int x, int z) { // a wall 3 m high along z at x = 10, 40 m long
    return x == 10 && z >= -20 && z <= 20 ? ColumnOf(0.0f, 3.0f) : ColumnOf(0.0f, 0.0f);
}
Column Post(int x, int z) { // one cell, 3 m high
    return x == 10 && z == 0 ? ColumnOf(0.0f, 3.0f) : ColumnOf(0.0f, 0.0f);
}
Column Tomb(int x, int z) { // 5 cells wide, 2 m high
    return x == 10 && z >= -2 && z <= 2 ? ColumnOf(0.0f, 2.0f) : ColumnOf(0.0f, 0.0f);
}
Column Deck(int x, int) { // a deck 5 m up, 1 m thick, along z
    return x == 10 ? ColumnOf(5.0f, 6.0f) : ColumnOf(0.0f, 0.0f);
}
Column Room(int x, int z) { // a hall 21 x 21 cells, ceiling 3 m
    return x >= -10 && x <= 10 && z >= -10 && z <= 10 ? ColumnOf(0.0f, 3.0f) : Column{};
}
Column Pavilion(int x, int z) { // one roofed cell in flat ground
    return x == 0 && z == 0 ? ColumnOf(0.0f, 3.0f) : ColumnOf(0.0f, 0.0f);
}
Column Nothing(int, int) {
    return Column{};
}

void TestKnob() {
    Knob k = ParseKnob("1", "1", nullptr, true);
    Expect(k.wind && k.asked && k.on && k.strength == 1.0f && k.show == 0, "1 / 1 is on at full strength");
    k = ParseKnob("1", "0.5", "1", true);
    Expect(k.on && Near(k.strength, 0.5f, 1e-6f) && k.show == 1, "0.5 is half strength; show 1");
    k = ParseKnob("1", "7", "2", true);
    Expect(k.on && k.strength == 1.0f && k.show == 2, "above 1 holds at 1; show 2");
    k = ParseKnob("1", nullptr, nullptr, true);
    Expect(!k.asked && !k.on && k.strength == 0.0f, "unset is off");
    k = ParseKnob("1", "0", nullptr, true);
    Expect(!k.asked && !k.on, "0 is off");
    k = ParseKnob("0", "1", nullptr, true);
    Expect(k.asked && !k.wind && !k.on, "without BB_WIND=1 it is off");
    k = ParseKnob(nullptr, "1", nullptr, true);
    Expect(!k.on, "BB_WIND unset: off");
    k = ParseKnob("1", "1", nullptr, false);
    Expect(k.asked && !k.on, "without the plant sway's region it is off");
    k = ParseKnob("1", "abc", nullptr, true);
    Expect(k.unreadable && !k.on, "unreadable text is off and says so");
    k = ParseKnob("1", "nan", nullptr, true);
    Expect(!k.on, "a non-number is off");
    k = ParseKnob("1", "-1", nullptr, true);
    Expect(!k.on && k.strength == 0.0f, "negative is off");
    k = ParseKnob("1", "1", "11", true);
    Expect(k.show == 0, "show takes exactly 1 or 2");
    k = ParseKnob("1", "1", "", true);
    Expect(k.show == 0, "empty show is off");
}

void TestLayout() {
    static_assert(BlockWord >= BbWindSway::RegionWords);
    static_assert(BlockWords == 8 + 64 * 64 && BlockBytes == 16416);
    static_assert(sizeof(Push) == 128);
    Expect(BlockWord == 4096 && N == 64 && M == 128 && Steps == 28, "the layout's numbers");
    Expect(Cell == 1.0f && Band == 14.0f && BandSoft == 4.0f, "the band's numbers");
    // the region ends where the field's block begins, at 16 KB in the buffer
    Expect(BlockWord * 4 + BlockBytes == 32800, "the buffer grows to 32800 bytes with the field");
}

void TestReader() {
    std::vector<float> block(BlockWords, 0.0f);
    WriteHeader(block.data(), -32, -32, 1.7f, 1.0f);
    const auto cell = [&](std::uint32_t i, std::uint32_t j) -> float& {
        return block[HeaderWords + j * N + i];
    };
    cell(10, 20) = 0.8f;
    // the middle of cell (10, 20): world x -21.5, z -11.5
    Expect(At(block.data(), -21.5f, 1.7f, -11.5f) == 0.8f, "a cell's middle gives its value");
    Expect(Near(At(block.data(), -21.0f, 1.7f, -11.5f), 0.4f, 1e-6f),
           "half way to the next cell it is half (bilinear in x)");
    Expect(Near(At(block.data(), -21.5f, 1.7f, -11.0f), 0.4f, 1e-6f), "and in z");
    Expect(Near(At(block.data(), -21.0f, 1.7f, -11.0f), 0.2f, 1e-6f), "a quarter at a corner of four");
    Expect(At(block.data(), -11.5f, 1.7f, -21.5f) == 0.0f, "another cell is 0");
    // outside the field
    Expect(At(block.data(), -32.4f, 1.7f, 0.0f) == 0.0f, "west of the first cell's middle: outside");
    Expect(At(block.data(), -32.0f + 63.6f, 1.7f, 0.0f) == 0.0f, "past the last cell pair: outside");
    Expect(At(block.data(), 0.0f, 1.7f, -32.4f) == 0.0f, "north of it: outside");
    // the marker
    std::vector<float> unwritten = block;
    unwritten[0] = 0.0f;
    Expect(At(unwritten.data(), -21.5f, 1.7f, -11.5f) == 0.0f, "marker 0: nothing is read");
    unwritten[0] = 0.5f;
    Expect(At(unwritten.data(), -21.5f, 1.7f, -11.5f) == 0.0f, "marker not above 0.5: nothing");
    // the vertical band
    Expect(Near(At(block.data(), -21.5f, 1.7f + 10.0f, -11.5f), 0.8f, 1e-5f), "10 m above the camera: full");
    Expect(Near(At(block.data(), -21.5f, 1.7f + 12.0f, -11.5f), 0.4f, 1e-5f), "12 m: half");
    Expect(At(block.data(), -21.5f, 1.7f + 14.0f, -11.5f) < 1e-5f, "14 m: none");
    Expect(Near(At(block.data(), -21.5f, 1.7f - 12.0f, -11.5f), 0.4f, 1e-5f), "12 m below: half");
    // the strength
    WriteHeader(block.data(), -32, -32, 1.7f, 0.5f);
    Expect(Near(At(block.data(), -21.5f, 1.7f, -11.5f), 0.4f, 1e-6f), "strength 0.5 halves it");
    Expect(Near(Factor(block.data(), -21.5f, 1.7f, -11.5f), 0.6f, 1e-6f), "the factor is 1 - At");
    // indoors: field 1 gives a factor of exactly 0 (nothing moves)
    WriteHeader(block.data(), -32, -32, 1.7f, 1.0f);
    cell(10, 20) = 1.0f;
    Expect(Factor(block.data(), -21.5f, 1.7f, -11.5f) == 0.0f, "field 1, strength 1: the factor is 0");
    Expect(Factor(block.data(), 0.0f, 1.7f, 0.0f) == 1.0f, "in the open the factor is 1");
}

// The same world function in two windows (the camera moved by (2, 4) cells): the same value at the
// same world point, whichever window answers.
void TestStable() {
    const auto world_value = [](int wx, int wz) {
        return float(((wx * 7 + wz * 3) % 10 + 10) % 10) / 10.0f;
    };
    std::vector<float> a(BlockWords, 0.0f), b(BlockWords, 0.0f);
    WriteHeader(a.data(), -32, -32, 1.7f, 1.0f);
    WriteHeader(b.data(), -30, -28, 1.7f, 1.0f);
    for (std::uint32_t j = 0; j < N; ++j) {
        for (std::uint32_t i = 0; i < N; ++i) {
            a[HeaderWords + j * N + i] = world_value(-32 + int(i), -32 + int(j));
            b[HeaderWords + j * N + i] = world_value(-30 + int(i), -28 + int(j));
        }
    }
    int compared = 0;
    for (float x = -20.0f; x < 20.0f; x += 1.37f) {
        for (float z = -20.0f; z < 20.0f; z += 1.91f) {
            const float va = At(a.data(), x, 1.7f, z), vb = At(b.data(), x, 1.7f, z);
            Expect(Near(va, vb, 1e-5f), "a world point has one value in either window");
            ++compared;
        }
    }
    Expect(compared > 400, "many points compared");
}

void TestModel() {
    // flat ground, wind toward +x
    Expect(Raw(Flat, 5, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "flat ground: no shelter");
    Expect(Raw(Nothing, 5, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "nothing known: no shelter");
    // a wall 3 m high at x = 10
    Expect(Near(Raw(Wall, 11, 0, 1.0f, 0.0f, 1.7f), 1.0f, 1e-6f), "close behind a wall: 1");
    // r117f: a hit counts less with its distance and only above an elevation of about 25 degrees
    Expect(Near(Raw(Wall, 12, 0, 1.0f, 0.0f, 1.7f), 0.886f, 0.01f) && Near(Raw(Wall, 14, 0, 1.0f, 0.0f, 1.7f), 0.657f, 0.01f),
           "2 m and 4 m behind a 3 m wall: 0.89 and 0.66 (r117e: 1)");
    Expect(Near(Raw(Wall, 16, 0, 1.0f, 0.0f, 1.7f), 0.027f, 0.01f), "6 m behind a 3 m wall: 0.03 (r117e: 0.86)");
    Expect(Raw(Wall, 20, 0, 1.0f, 0.0f, 1.7f) < 0.005f, "10 m behind it: 0 (r117e: 0.2)");
    Expect(Raw(Wall, 26, 0, 1.0f, 0.0f, 1.7f) < 0.01f, "16 m behind it: about 0");
    Expect(Raw(Wall, 30, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "20 m behind it: 0");
    Expect(Raw(Wall, 5, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "in front of the wall (upwind): 0");
    Expect(Raw(Wall, 12, 0, 0.0f, 1.0f, 1.7f) == 0.0f, "wind along the wall: the wall's end is far");
    Expect(Raw(Wall, 12, 0, -1.0f, 0.0f, 1.7f) == 0.0f, "wind from the other side: the cell is upwind");
    Expect(Near(Raw(Wall, 7, 0, -1.0f, 0.0f, 1.7f), 0.771f, 0.01f), "wind toward -x: the cell at 7 is behind it (3 m: 0.77)");
    const float r = std::sqrt(0.5f);
    Expect(Near(Raw(Wall, 13, 0, r, r, 1.7f), 0.657f, 0.02f), "a diagonal wind: behind the wall too (4 m along the ray: 0.66)");
    // a thin obstacle (one cell) shelters only just behind it (the median of the three rays)
    Expect(Raw(Post, 11, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "right behind a one-cell post: 0 (r117d: a thin thing shelters nothing)");
    Expect(Raw(Post, 13, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "3 m behind a post: 0 (the air goes round)");
    Expect(Raw(Post, 16, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "6 m behind a post: 0");
    // a 2 m tomb, 5 cells wide
    Expect(Raw(Tomb, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "right behind a tomb: 1");
    Expect(Near(Raw(Tomb, 13, 0, 1.0f, 0.0f, 1.7f), 0.013f, 0.01f), "3 m behind it: 0.02 (r117f: 0.05, r117e: 0.86; a 2 m tomb is low, its lee short)");
    Expect(Raw(Tomb, 18, 0, 1.0f, 0.0f, 1.7f) < 0.01f, "8 m behind it: about 0");
    // a deck 5 m up does not block the wind at the ground
    Expect(Raw(Deck, 14, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "under a bridge: the wind passes");
    // indoors: a hall, in the middle and at its edge
    // r117g: the cell is tall itself and the walls are no higher: 0.4 (the cover, what the camera saw overhead, makes it 1)
    Expect(Near(Raw(Room, 0, 0, 1.0f, 0.0f, 1.7f), 0.4f, 1e-5f), "in a hall without cover: 0.4 (r117f: 1)");
    Expect(Near(Raw(Room, 9, 0, 1.0f, 0.0f, 1.7f), 0.4f, 1e-5f), "at its downwind edge: 0.4 (r117f: 1)");
    Expect(Near(Raw(Room, 0, 0, 1.0f, 0.0f, 1.7f, 1.0f), 1.0f, 1e-6f), "in a hall with cover 1: 1");
    // r117b: a tall cell gives its own cell no roof; only the cover (what the camera saw overhead) does
    Expect(Raw(Pavilion, 0, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "a tall cell alone in the open: 0");
    Expect(Raw(Pavilion, 0, 0, 1.0f, 0.0f, 1.7f, 1.0f) == 1.0f, "cover 1: 1");
    Expect(Near(Raw(Flat, 5, 0, 1.0f, 0.0f, 1.7f, 0.5f), 0.5f, 1e-6f), "open ground, cover 0.5: 0.5");
    Expect(Near(Raw(Wall, 11, 0, 1.0f, 0.0f, 1.7f, 0.3f), 1.0f, 1e-6f), "behind a wall with cover: still 1");
    Expect(Near(Raw(Wall, 14, 0, 1.0f, 0.0f, 1.7f, 0.5f), 1.0f - (1.0f - 0.657f) * 0.5f, 0.01f),
           "the lee and the cover combine as 1 - (1 - lee)(1 - cover)");
    Expect(Raw(Tomb, 18, 0, 1.0f, 0.0f, 1.7f) < 0.01f && Raw(Wall, 5, 0, 1.0f, 0.0f, 1.7f) == 0.0f,
           "open ground by a tomb or in front of a wall: still open");
    // the ground of a cell nothing is known about is the neighbours' lowest
    const auto step_up = [](int x, int z) {
        return x == 10 && z >= -3 && z <= 3 ? ColumnOf(0.0f, 3.0f)
               : x == 11 && z == 0         ? Column{}
                                           : ColumnOf(0.0f, 0.0f);
    };
    Expect(Raw(step_up, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "an unknown cell takes its neighbours' ground");
}

void TestSteps() {
    Expect(Median3(0.1f, 0.5f, 0.9f) == 0.5f && Median3(0.9f, 0.1f, 0.5f) == 0.5f &&
               Median3(0.5f, 0.9f, 0.1f) == 0.5f && Median3(0.3f, 0.3f, 0.9f) == 0.3f,
           "the median of three");
    const auto r = Rotated(1.0f, 0.0f, 90.0f);
    Expect(Near(r[0], 0.0f, 1e-6f) && Near(r[1], 1.0f, 1e-6f), "a quarter turn");
    Expect(Near(Unquant(Quant(1.7f)), 1.6875f, 1e-6f), "heights keep 1/32 m");
    Expect(Quant(-2000.0f) == 0 && Quant(5000.0f) == 65535, "heights are clamped");
    Expect(Near(Unquant(Quant(-3.1f)), -3.1f, 1.0f / 63.0f), "the round trip is within 1/64 m");
    Expect(Unquant(Quant(3.0f)) == 3.0f, "3 m is exact");
    // the window's edge and the target
    Expect(EdgeFade(0, 30) == 0.0f && EdgeFade(30, 0) == 0.0f && EdgeFade(63, 30) == 0.0f &&
               EdgeFade(30, 63) == 0.0f,
           "0 at the window's border");
    Expect(EdgeFade(32, 32) == 1.0f && EdgeFade(4, 40) == 1.0f && EdgeFade(59, 40) == 1.0f,
           "1 from 4 cells in");
    Expect(Near(EdgeFade(1, 32), 0.15625f, 1e-6f) && EdgeFade(1, 32) == EdgeFade(62, 32),
           "the fade is symmetric");
    Expect(Target(1.0f, 32, 32) == 1.0f && Target(0.95f, 32, 32) == 1.0f,
           "indoors reaches exactly 1 (the gain)");
    Expect(Near(Target(0.5f, 32, 32), 0.53f, 1e-6f) && Target(0.5f, 0, 5) == 0.0f, "gain and edge");
    // the time filter: a second brings it most of the way, never past, never jumping
    Expect(Follow(0.0f, 1.0f, 0.0f) == 0.0f && Follow(0.3f, 0.3f, 0.1f) == 0.3f, "no step, no change");
    Expect(Near(Follow(0.0f, 1.0f, 0.5f), 0.632f, 0.001f), "a time constant of 0.5 s");
    Expect(Follow(0.0f, 1.0f, 1.0f) > 0.86f && Follow(0.0f, 1.0f, 1.0f) < 0.87f,
           "a second: 86 percent of the way");
    float v = 0.0f;
    float biggest_step = 0.0f;
    for (int i = 0; i < 60; ++i) { // 60 frames of 1/60 s toward 1: a smooth rise
        const float next = Follow(v, 1.0f, 1.0f / 60.0f);
        biggest_step = std::max(biggest_step, next - v);
        v = next;
    }
    Expect(v > 0.85f && v < 0.88f && biggest_step < 0.04f, "frame by frame it rises smoothly: a second of frames gives 86 percent");
    // the consumers' scalars
    Expect(Near(Open(0.3f), 0.7f, 1e-6f) && Open(0.0f) == 1.0f && Open(1.0f) == 0.0f && Open(2.0f) == 0.0f &&
               Open(-1.0f) == 1.0f,
           "Open is the share that stays, held to 0-1");
    Expect(Open(std::numeric_limits<float>::quiet_NaN()) == 1.0f &&
               Open(std::numeric_limits<float>::infinity()) == 1.0f,
           "not a number: no shelter");
    const auto bits = [](float f) {
        std::uint32_t w = 0;
        std::memcpy(&w, &f, 4);
        return w;
    };
    Expect(CameraShelter(bits(0.25f)) == 0.25f && CameraShelter(bits(2.0f)) == 1.0f &&
               CameraShelter(bits(-1.0f)) == 0.0f &&
               CameraShelter(bits(std::numeric_limits<float>::quiet_NaN())) == 0.0f,
           "the camera's counter word");
}

void TestCounts() {
    std::array<std::uint32_t, WS_COUNTER_WORDS> before{}, now{};
    now[WS_C_PIXELS] = 1000;
    now[WS_C_PIXELS_SHELTERED] = 250;
    now[WS_C_PIXELS_INDOOR] = 100;
    now[WS_C_PIXELS_SUM] = 300000; // 1/1000: mean 0.3
    now[WS_C_CELLS] = 4096;
    now[WS_C_CELLS_SEEN] = 1024;
    now[WS_C_CELLS_SHELTERED] = 512;
    now[WS_C_CELLS_SUM] = 2048000;
    now[WS_C_MERGED] = 77;
    Counts c = CountsBetween(now.data(), before.data());
    Expect(c.pixels == 1000 && c.sheltered == 250 && c.indoor == 100 && c.sum == 300000 &&
               c.cells == 4096 && c.cells_seen == 1024 && c.cells_sheltered == 512 &&
               c.cells_sum == 2048000 && c.merged == 77,
           "the counts, word by word");
    Expect(Near(float(ViewSheltered(c)), 0.25f, 1e-6f) && Near(float(ViewIndoor(c)), 0.1f, 1e-6f) &&
               Near(float(ViewMean(c)), 0.3f, 1e-6f),
           "the view's shares and mean");
    before[WS_C_PIXELS] = 0xfffffffeu; // the 32-bit totals wrap
    now[WS_C_PIXELS] = 5;
    c = CountsBetween(now.data(), before.data());
    Expect(c.pixels == 7, "a wrapped total counts the difference");
    // r117b: the sum is a 64-bit total, the high word carries (it wrapped at 2^32 in the b28 log)
    before = {};
    now = {};
    before[WS_C_PIXELS_SUM] = 0xfffffff0u;
    now[WS_C_PIXELS_SUM] = 5;
    now[WS_C_PIXELS_SUM_HI] = 1;
    now[WS_C_PIXELS] = 10;
    c = CountsBetween(now.data(), before.data());
    Expect(c.sum == 21 && c.pixels == 10, "a carry word makes the sum 64 bits");
    before = {};
    now = {};
    now[WS_C_PIXELS] = 8565458;
    now[WS_C_PIXELS_SUM] = 0x2d2ea940u; // 5,053,000,000 - 2^32: alone it reads 0.088
    now[WS_C_PIXELS_SUM_HI] = 1;
    c = CountsBetween(now.data(), before.data());
    Expect(Near(float(ViewMean(c)), 0.59f, 0.01f), "the b28 graveyard's mean: about 0.59, not 0.086");
    // r117c: where the climbing rays ended
    before = {};
    now = {};
    now[WS_C_UP] = 1000;
    now[WS_C_CLOSE] = 200;
    now[WS_C_DOWN] = 100;
    now[WS_C_MID] = 450;
    c = CountsBetween(now.data(), before.data());
    Expect(c.climb_up == 1000 && c.climb_close == 200 && c.climb_down == 100 && c.climb_mid == 450,
           "the climbing rays' counts, word by word");
    // r117d: the obstacle cells the rays met
    before = {};
    now = {};
    now[WS_C_THIN_SEEN] = 900;
    now[WS_C_THIN_LOW] = 300;
    now[WS_C_THIN_NARROW] = 200;
    c = CountsBetween(now.data(), before.data());
    Expect(c.thin_seen == 900 && c.thin_low == 300 && c.thin_narrow == 200,
           "the obstacle counts, word by word");
    // r117e: the kept and tall hits
    before = {};
    now = {};
    now[WS_C_THIN_SEEN] = 900;
    now[WS_C_THIN_KEPT] = 400;
    now[WS_C_THIN_TALL] = 300;
    c = CountsBetween(now.data(), before.data());
    Expect(c.thin_seen == 900 && c.thin_kept == 400 && c.thin_tall == 300, "the kept and tall counts, word by word");
    const Counts none{};
    Expect(ViewSheltered(none) == 0.0 && ViewIndoor(none) == 0.0 && ViewMean(none) == 0.0,
           "no samples: 0");
}
// r117c: open ground reads open, the Hunter does not shelter the camera, indoors is as before
Column Person(int x, int z) { // the Hunter: 2 x 2 cells, 1.9 m, at x 8..9
    return x >= 8 && x <= 9 && z >= -1 && z <= 0 ? ColumnOf(0.0f, 1.9f) : ColumnOf(0.0f, 0.0f);
}
Column BigTomb(int x, int z) { // the same block, 2.6 m high
    return x >= 8 && x <= 9 && z >= -1 && z <= 0 ? ColumnOf(0.0f, 2.6f) : ColumnOf(0.0f, 0.0f);
}
Column TallWall(int x, int z) { // a wall 9 m high along z at x = 10, 40 m long
    return x == 10 && z >= -20 && z <= 20 ? ColumnOf(0.0f, 9.0f) : ColumnOf(0.0f, 0.0f);
}
Column Tree(int x, int z) { // a trunk with its canopy: 5 x 5 cells, 8 m (the ground under it seen too)
    return x >= 8 && x <= 12 && z >= -2 && z <= 2 ? ColumnOf(0.0f, 8.0f) : ColumnOf(0.0f, 0.0f);
}

void TestOutdoors() {
    // an obstacle counts at most as a 3 m wall in the tangent (r117c), by its real height in the elevation (r117f)
    Expect(Near(Raw(TallWall, 16, 0, 1.0f, 0.0f, 1.7f), 0.367f, 0.01f), "6 m behind a 9 m wall: 0.37 (r117e: as behind a 3 m one, 0.86)");
    Expect(Near(Raw(TallWall, 20, 0, 1.0f, 0.0f, 1.7f), 0.04f, 0.01f), "10 m behind it: 0.04 (r117e: 0.2)");
    Expect(Raw(TallWall, 27, 0, 1.0f, 0.0f, 1.7f) == 0.0f && Raw(TallWall, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f,
           "17 m behind it: 0 (was 28 m before the cap), right behind it: 1");
    Expect(Near(Raw(Tree, 21, 0, 1.0f, 0.0f, 1.7f), 0.061f, 0.02f) && Raw(Tree, 13, 0, 1.0f, 0.0f, 1.7f) > 0.99f,
           "a tree: sheltered close behind it, 0.06 at 9 m (r117e: 0.3, r117b: 1.0)");
    // the Hunter: a low block 2-3 m upwind of the camera cell is ignored, only near the camera
    const float cx = 11.5f, cz = 0.5f; // the camera in the middle of cell (11, 0)
    Expect(Near(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f), 0.25f, 0.05f), "without the camera's place the 2 x 2 block shelters by a quarter (r117g: 0.25, r117f: 0.37, r117d: half)");
    Expect(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz) == 0.0f, "the Hunter next to the camera: ignored");
    Expect(Near(Raw(BigTomb, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz), 0.5f, 0.1f), "a 2.6 m block next to it still shelters by half (r117d)");
    Expect(Near(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, 30.5f, 0.5f), 0.25f, 0.05f),
           "the same low block with the camera 19 m away shelters as before");
    Expect(NearKeep(1.9f, 2.0f) == 0.0f && NearKeep(2.6f, 2.0f) == 1.0f && NearKeep(1.9f, 7.0f) == 1.0f &&
               Near(NearKeep(1.9f, 5.5f), 0.5f, 1e-6f) && Near(NearKeep(2.3f, 2.0f), 0.5f, 1e-6f),
           "the keep weight");
    Expect(Near(Raw(Wall, 12, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz), 0.886f, 0.01f) &&
               Raw(Wall, 16, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz) < 0.05f,
           "a 3 m wall near the camera shelters in full (3 m is not low)");
    // the covered rays
    Expect(CoverHit(10.0f, 0.0f) && CoverHit(34.9f, 0.9f) && !CoverHit(40.0f, 0.0f) && !CoverHit(40.0f, 0.4f) &&
               CoverHit(40.0f, -0.6f) && CoverHit(79.0f, -0.9f) && !CoverHit(80.0f, -0.9f) && !CoverHit(60.0f, 0.9f),
           "a ray is covered within 35 m, or on a surface facing down within 80 m; a far wall is not");
}

// r117d: thin and low things shelter little, walls and wide things as before
Column Trunk(int x, int z) { // a trunk: one cell, 8 m
    return x == 10 && z == 0 ? ColumnOf(0.0f, 8.0f) : ColumnOf(0.0f, 0.0f);
}
Column TrunkUnknown(int x, int z) { // the same trunk, its neighbours across the ray not known
    return x == 10 && z == 0 ? ColumnOf(0.0f, 8.0f) : x == 10 ? Column{} : ColumnOf(0.0f, 0.0f);
}
Column Rail(int x, int z) { // a rail 1.2 m high along z at x = 10, 40 m long
    return x == 10 && z >= -20 && z <= 20 ? ColumnOf(0.0f, 1.2f) : ColumnOf(0.0f, 0.0f);
}
Column Stone(int x, int z) { // a fence of 1.6 m
    return x == 10 && z >= -20 && z <= 20 ? ColumnOf(0.0f, 1.6f) : ColumnOf(0.0f, 0.0f);
}
Column TwoCells(int x, int z) { // a thing two cells wide, 3 m
    return x == 10 && z >= 0 && z <= 1 ? ColumnOf(0.0f, 3.0f) : ColumnOf(0.0f, 0.0f);
}

// r117e: branches over a trunk do not make it wide; a neighbour that stands does
Column Overhang(int x, int z) { // a trunk 8 m with branch cells 4-8 m either side across the wind
    return x == 10 && z == 0 ? ColumnOf(0.0f, 8.0f)
           : x == 10 && z >= -2 && z <= 2 ? ColumnOf(4.0f, 8.0f)
                                          : ColumnOf(0.0f, 0.0f);
}
Column Standing(int x, int z) { // the same cells reaching the ground: a canopy, 5 wide
    return x == 10 && z >= -2 && z <= 2 ? ColumnOf(0.0f, 8.0f) : ColumnOf(0.0f, 0.0f);
}

void TestStanding() {
    Expect(Raw(Overhang, 11, 0, 1.0f, 0.0f, 1.7f) == 0.0f && Raw(Overhang, 13, 0, 1.0f, 0.0f, 1.7f) == 0.0f,
           "a trunk with branches over it: thin (r117d: as a wall)");
    Expect(ThinWeight(Overhang, 10.5f, 0.5f, 1.0f, 0.0f, 0.0f) == 0.0f &&
               Near(ThinWeight(Standing, 10.5f, 0.5f, 1.0f, 0.0f, 0.0f), 1.0f, 1e-6f),
           "the width weight: lifted neighbours 0, neighbours that stand 1");
    Expect(Raw(Standing, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "a canopy that reaches the ground: a wall, as before");
}

// r117f: a hit counts less with its distance and only above an elevation of about 25 degrees
void TestFar() {
    Expect(FarWeight(1.0f, 3.0f) == 1.0f && FarWeight(1.0f, 9.0f) == 1.0f, "a wall one cell away counts in full");
    Expect(Near(FarWeight(4.0f, 8.0f), 0.657f, 0.002f) && Near(FarWeight(4.0f, 4.0f), 0.657f, 0.002f),
           "4 m away: 0.66 by distance, the elevation is above 27 degrees");
    Expect(Near(FarWeight(8.0f, 20.0f), 0.2f, 1e-6f) && Near(FarWeight(30.0f, 30.0f), 0.2f, 1e-6f), "from 8 m: the floor, 0.2");
    Expect(Near(FarWeight(6.0f, 3.0f), 0.0317f, 0.002f) && Near(FarWeight(3.0f, 2.0f), 0.0148f, 0.002f),
           "a low thing is cut by the elevation: a 3 m wall at 6 m, a 2 m tomb at 3 m");
    Expect(Near(FarWeight(10.0f, 5.66f), 0.1846f, 0.003f), "the elevation of 25 degrees counts 0.92 of the distance weight");
    float last = 2.0f;
    bool falling = true;
    for (float d = 1.0f; d <= 28.0f; d += 1.0f) {
        const float w = FarWeight(d, 9.0f);
        // the floor holds while the top rises 27 degrees or more (to 16 m for a 9 m wall); beyond, the elevation cuts it
        falling = falling && w <= last + 1e-6f && (d > 16.0f || w >= 0.2f - 1e-6f);
        last = w;
    }
    Expect(falling && FarWeight(17.0f, 9.0f) < 0.2f, "for a tall wall the weight never rises with the distance, keeps the floor to 16 m");
    // the log's counter word
    std::array<std::uint32_t, WS_COUNTER_WORDS> before{}, now{};
    now[WS_C_FAR_CUT] = 120;
    const auto c = CountsBetween(now.data(), before.data());
    Expect(WS_C_FAR_CUT < WS_COUNTER_WORDS && c.far_cut == 120, "the far-cut count, word by word");
}

// r117g: the lee of a low thing is short; a tall cell is sheltered by a hit no higher than its own top only by 0.4
void TestGraveyard() {
    Expect(FarWeight(1.0f, 2.0f) == 1.0f && Near(FarWeight(2.0f, 2.0f), 0.6f, 0.002f),
           "a 2 m thing: full at 1 m, 0.6 at 2 m (r117f 0.89)");
    Expect(Near(FarWeight(3.0f, 2.5f), 0.621f, 0.003f) && FarWeight(3.5f, 2.0f) < 1e-6f && FarWeight(5.0f, 1.9f) < 1e-6f,
           "a 2.5 m thing at 3 m, none from 3.5 m for a low one");
    Expect(Near(FarWeight(2.0f, 3.0f), 0.886f, 0.002f) && Near(FarWeight(4.0f, 3.0f), 0.657f, 0.002f) &&
               Near(FarWeight(4.0f, 9.0f), 0.657f, 0.002f),
           "a 3 m thing and the taller ones keep r117f's numbers");
    Expect(SelfWeight(8.0f, 0.0f) == 1.0f && SelfWeight(3.0f, 1.5f) == 1.0f && SelfWeight(1.0f, 1.9f) == 1.0f,
           "a cell that is not tall: every hit counts in full");
    Expect(Near(SelfWeight(3.0f, 3.0f), 0.4f, 1e-6f) && Near(SelfWeight(8.0f, 8.0f), 0.4f, 1e-6f) &&
               Near(SelfWeight(2.0f, 8.0f), 0.4f, 1e-6f),
           "a tall cell, a hit no higher: 0.4");
    Expect(Near(SelfWeight(4.0f, 3.0f), 0.7f, 1e-5f) && SelfWeight(5.0f, 3.0f) == 1.0f && SelfWeight(11.0f, 8.0f) == 1.0f,
           "a hit 1 m higher: 0.7; 2 m or more higher: 1");
    Expect(Near(SelfWeight(3.0f, 2.5f), 0.7469f, 1e-4f), "a cell 2.5 m tall is half a tall cell");
    // a tree mass (5 x 5 cells, 8 m): its inside is not sheltered by its own neighbours; behind it, it is
    Expect(Near(Raw(Tree, 10, 0, 1.0f, 0.0f, 1.7f), 0.4f, 0.02f) && Near(Raw(Tree, 11, 0, 1.0f, 0.0f, 1.7f), 0.4f, 0.02f),
           "inside a tree mass: 0.4 (r117f: 1)");
    Expect(Raw(Tree, 13, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "right behind it: 1");
    // the log's counter words
    std::array<std::uint32_t, WS_COUNTER_WORDS> before{}, now{};
    now[WS_C_SELF_CUT] = 33;
    now[WS_C_SELF_CELLS] = 44;
    const auto c = CountsBetween(now.data(), before.data());
    Expect(WS_C_SELF_CELLS < WS_COUNTER_WORDS && c.self_cut == 33 && c.self_cells == 44 && c.far_cut == 0,
           "the own-height counts, word by word");
}

void TestThin() {
    Expect(HeightWeight(1.0f) == 0.0f && HeightWeight(1.2f) == 0.0f && HeightWeight(2.0f) == 1.0f &&
               HeightWeight(3.0f) == 1.0f && Near(HeightWeight(1.6f), 0.5f, 1e-6f),
           "the height weight: 0 under 1.2 m, half at 1.6, 1 from 2.0");
    // a trunk (one cell, all neighbours known low): nothing, close or far
    Expect(Raw(Trunk, 11, 0, 1.0f, 0.0f, 1.7f) == 0.0f && Raw(Trunk, 12, 0, 1.0f, 0.0f, 1.7f) == 0.0f,
           "behind a one-cell trunk: nothing (r117c: 1.0 close behind it)");
    // the same trunk with its neighbours unknown (cache gaps) is not called thin: w = 3, as before
    Expect(Near(Raw(TrunkUnknown, 11, 0, 1.0f, 0.0f, 1.7f), 0.216f, 0.01f),
           "a trunk whose neighbours are not known: mostly thin (r117e: 0.22, r117d: as a wall)");
    // a low rail, 40 m long: its height alone keeps it from counting
    Expect(Raw(Rail, 11, 0, 1.0f, 0.0f, 1.7f) == 0.0f && Raw(Rail, 13, 0, 1.0f, 0.0f, 1.7f) == 0.0f,
           "behind a 1.2 m rail: 0 (r117c: it counted by its 0.2 m of excess)");
    Expect(Near(Raw(Stone, 11, 0, 1.0f, 0.0f, 1.7f), 0.5f, 0.05f), "behind a 1.6 m fence: half (the height weight)");
    // a thing two cells wide: half
    Expect(Near(Raw(TwoCells, 11, 0, 1.0f, 0.0f, 1.7f), 0.5f, 0.1f), "a thing two cells wide: about half");
    // walls, tombs, trees as before
    Expect(Near(Raw(Wall, 11, 0, 1.0f, 0.0f, 1.7f), 1.0f, 1e-6f) && Near(Raw(Wall, 14, 0, 1.0f, 0.0f, 1.7f), 0.657f, 0.01f) &&
               Raw(Tomb, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f && Raw(Tree, 13, 0, 1.0f, 0.0f, 1.7f) > 0.99f,
           "a wall, a tomb and a tree are not thin");
    // ThinWeight directly: a wide wall's cell is 1; a lone cell with known low neighbours 0; unknown ones 0.5 each
    Expect(Near(ThinWeight(Wall, 10.5f, 0.5f, 1.0f, 0.0f, 0.0f), 1.0f, 1e-6f) &&
               ThinWeight(Post, 10.5f, 0.5f, 1.0f, 0.0f, 0.0f) == 0.0f &&
               Near(ThinWeight(Post, 10.5f, 0.5f, 0.0f, 1.0f, 0.0f), 0.0f, 1e-6f) &&
               Near(ThinWeight(TrunkUnknown, 10.5f, 0.5f, 1.0f, 0.0f, 0.0f), 0.216f, 0.002f),
           "the width weight");
}

// r117b: the camera's cover
void TestCover() {
    Expect(CoverRayUp(0.0f, 1.0f, 1.0f) && !CoverRayUp(1.0f, 0.1f, 0.0f) && !CoverRayUp(3.0f, 1.0f, 4.0f) &&
               CoverRayUp(3.0f, 2.0f, 4.0f) && CoverRayUp(0.0f, 1.0f, 0.0f) && !CoverRayUp(0.0f, -1.0f, 1.0f),
           "a ray climbs when its elevation's tangent is above 0.35");
    Expect(CoverShare(0, 0) == 0.0f && Near(CoverShare(200, 150), 0.75f, 1e-6f), "the covered share");
    Expect(CoverFollow(0.3f, 10, 10, 0.1f, false) == 0.3f && CoverFollow(0.3f, 63, 63, 0.1f, true) == 0.3f,
           "fewer than 64 climbing rays: no news");
    Expect(CoverFollow(0.0f, 100, 100, 0.0f, true) == 1.0f, "the first measure is taken whole");
    Expect(Near(CoverFollow(0.0f, 100, 100, CoverTau, false), 0.632f, 0.001f), "a time constant of 0.4 s");
    Expect(CoverFollow(0.5f, 100, 50, 0.0f, false) == 0.5f, "no time passed: no step");
    Expect(CoverIndoors(0.0f) == 0.0f && CoverIndoors(0.8f) == 0.0f && CoverIndoors(0.96f) == 1.0f &&
               CoverIndoors(1.0f) == 1.0f && CoverIndoors(0.45f) == 0.0f && CoverIndoors(0.78f) == 0.0f,
           "a share above 0.96 is indoors, below 0.8 is not (r117c: the graveyard's 0.77-0.79 is open)");
    Expect(CoverIndoors(0.88f) > 0.49f && CoverIndoors(0.88f) < 0.51f, "half way: half");
    Expect(CoverCell(0.2f, 1.0f, 1.0f, 0) == 1.0f && CoverCell(0.9f, 0.0f, 2.0f, 0) == 0.0f,
           "the cells next to the camera take the cover outright, seen or not");
    Expect(CoverCell(0.0f, 1.0f, 10.0f, 0) == 0.0f && CoverCell(0.0f, 1.0f, 10.0f, 1) == 0.0f,
           "a cell not seen (fewer than 2 samples) keeps what it had");
    Expect(Near(CoverCell(0.0f, 1.0f, 10.0f, 5), 0.25f, 1e-6f), "a cell seen moves 25% toward it");
    Expect(CoverCell(0.0f, 1.0f, 17.0f, 50) == 0.0f && CoverCell(1.0f, 0.0f, 17.0f, 50) == 1.0f,
           "a cell seen beyond 16 m keeps what it had (it may be seen through a door)");
    float cell = 0.0f;
    for (int i = 0; i < 12; ++i) { // 12 frames seen from indoors
        cell = CoverCell(cell, 1.0f, 8.0f, 9);
    }
    Expect(cell > 0.96f, "a dozen frames seen indoors: covered");
    for (int i = 0; i < 12; ++i) { // seen again from the open
        cell = CoverCell(cell, 0.0f, 8.0f, 9);
    }
    Expect(cell < 0.04f, "and as many seen from the open: open again");
}

} // namespace

int main() {
    TestKnob();
    TestLayout();
    TestReader();
    TestStable();
    TestModel();
    TestSteps();
    TestCounts();
    TestCover();
    TestOutdoors();
    TestThin();
    TestStanding();
    TestFar();
    TestGraveyard();
    if (failures != 0) {
        std::printf("wind shelter test: %d failures\n", failures);
        return 1;
    }
    std::printf("wind shelter test: ok\n");
    return 0;
}
