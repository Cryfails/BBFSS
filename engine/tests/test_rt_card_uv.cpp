// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r54_leaf-stage2): tests of the pure parts of the card UVs (rt_card_uv.h): the knob, the
// selector, the alpha test a ray repeats against the game's decompiled test, the guard of the
// draw-time dword read, the 16-byte record and what its 8-bit alpha factor keeps of the game's
// decision, the entry states (the sun shadow pass's card preferred), the frees and slots, the
// stat keys.
// Built alone: c++ -std=c++20 -I. tests/test_rt_card_uv.cpp (engine/build.sh --test).

#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

#include "gpu/shadps4/video_core/renderer_vulkan/rt_card_uv.h"

using namespace Vulkan;

namespace {

int failures = 0;
#define CHECK(x)                                                                                   \
    do {                                                                                           \
        if (!(x)) {                                                                                \
            std::printf("FAILED %s:%d: %s\n", __FILE__, __LINE__, #x);                             \
            ++failures;                                                                            \
        }                                                                                          \
    } while (0)

void TestKnob() {
    CHECK(ReadCardAlpha(nullptr) == CardAlphaOff);
    CHECK(ReadCardAlpha("") == CardAlphaOff);
    CHECK(ReadCardAlpha("0") == CardAlphaOff);
    CHECK(ReadCardAlpha("1") == CardAlphaUv);
    CHECK(ReadCardAlpha("2") == CardAlphaOff); // later stages' levels are not this stage's
    CHECK(ReadCardAlpha("10") == CardAlphaOff);
    CHECK(ReadCardAlpha(" 1") == CardAlphaOff);
    CHECK(ReadCardAlpha("yes") == CardAlphaOff);
    CHECK(!CardAlphaMisread(nullptr));
    CHECK(!CardAlphaMisread("0"));
    CHECK(!CardAlphaMisread("1"));
    CHECK(CardAlphaMisread(""));
    CHECK(CardAlphaMisread("2"));
    CHECK(CardAlphaMisread("on"));
}

void TestSizes() {
    CHECK(CardRingBytes == 24ull << 20);
    CHECK(CardPoolBytes == 64ull << 20);
    CHECK(!CardPoolFits(0));
    CHECK(CardPoolFits(1));
    CHECK(CardPoolFits(CardTrianglesMost));
    CHECK(!CardPoolFits(CardTrianglesMost + 1));
    CHECK(!CardPoolFits(CardPoolRecords + 1));
    CHECK((CardTrianglesMost + CARD_UV_GROUP - 1) / CARD_UV_GROUP <= 65535u); // one dispatch
    CHECK(CardPoolSize(3) == 48);
    CHECK(CardPoolSize(1) % 16 == 0);
    CHECK(CardRingFits(0, 3, 0));
    CHECK(!CardRingFits(0, 0, 0));
    CHECK(CardRingFits(CardRingVertices - 3, 3, 0));
    CHECK(!CardRingFits(CardRingVertices - 2, 3, 0));
    CHECK(!CardRingFits(0, 3, CardCapturesPerFrame));
    CHECK(CardRingFits(0, 3, CardCapturesPerFrame - 1));
    // a capture for the UVs alone: within the first half of the frame's params and positions
    CHECK(CardUvProbeFits(0, 8192, 0, 3, 8u << 20));
    CHECK(CardUvProbeFits(4095, 8192, (4u << 20) - 3, 3, 8u << 20));
    CHECK(!CardUvProbeFits(4096, 8192, 0, 3, 8u << 20));
    CHECK(!CardUvProbeFits(0, 8192, (4u << 20) - 2, 3, 8u << 20));
    CHECK(!CardUvProbeFits(0, 8192, 0, 0, 8u << 20));
}

void TestSelector() {
    // every field at its extremes survives the word
    for (std::uint32_t uv = 0; uv < 32; uv += 31) {
        for (std::uint32_t cu = 0; cu < 4; ++cu) {
            for (std::uint32_t cv = 0; cv < 4; ++cv) {
                for (std::uint32_t ao = 0; ao < 32; ao += 7) {
                    for (std::uint32_t ac = 0; ac < 4; ++ac) {
                        for (int ha = 0; ha < 2; ++ha) {
                            const CardSelector s{uv, cu, cv, ao, ac, ha != 0};
                            const std::uint32_t w = PackCardSelector(s);
                            CHECK(w != 0);
                            CHECK((w & CardSelectorValid) != 0);
                            CardSelector back;
                            CHECK(UnpackCardSelector(w, back));
                            CHECK(back == s);
                            // the shader's decode: the same bit fields
                            CHECK((w & 31u) == uv && ((w >> 5) & 3u) == cu && ((w >> 7) & 3u) == cv &&
                                  ((w >> 9) & 31u) == ao && ((w >> 14) & 3u) == ac &&
                                  ((w >> 16) & 1u) == std::uint32_t(ha));
                        }
                    }
                }
            }
        }
    }
    CardSelector none;
    CHECK(!UnpackCardSelector(0, none));
    CHECK(!UnpackCardSelector(0x7fffffffu, none));

    CardSelector s;
    CHECK(CardSelectorFor({4, false, false}, 0, 1, true, {2, false, false}, 3, s));
    CHECK(s == (CardSelector{4, 0, 1, 2, 3, true}));
    CHECK(CardSelectorFor({4, false, false}, 2, 3, false, {9, true, true}, 0, s));
    CHECK(s == (CardSelector{4, 2, 3, 0, 3, false})); // no alpha: its input is not looked at
    CHECK(!CardSelectorFor({4, true, false}, 0, 1, false, {}, 0, s));  // default value
    CHECK(!CardSelectorFor({4, false, true}, 0, 1, false, {}, 0, s));  // flat
    CHECK(!CardSelectorFor({32, false, false}, 0, 1, false, {}, 0, s)); // past 31
    CHECK(!CardSelectorFor({4, false, false}, 4, 1, false, {}, 0, s));
    CHECK(!CardSelectorFor({4, false, false}, 0, 1, true, {2, true, false}, 3, s));
    CHECK(!CardSelectorFor({4, false, false}, 0, 1, true, {2, false, true}, 3, s));
    CHECK(!CardSelectorFor({4, false, false}, 0, 1, true, {40, false, false}, 3, s));
    CHECK(!CardSelectorFor({4, false, false}, 0, 1, true, {2, false, false}, 4, s));
}

// The game's test, as decompiled in the stage 1 run (camera pass): the pixel is discarded where
// cb20 > cb21 * (D - 0.5) + A, or A * fade == 0. Kept otherwise.
bool GameCameraKeeps(float a, float fade, float cb20, float cb21, float d) {
    return !(cb20 > cb21 * (d - 0.5f) + a || a * fade == 0.0f);
}
// The sun shadow pass form: the dither left out, cb21 * -0.5.
bool GameShadowKeeps(float a, float fade, float cb20, float cb21) {
    return !(cb20 > cb21 * -0.5f + a || a * fade == 0.0f);
}

// The record r50b makes of that test (info.h Cutout: reference = ref + ref_scale * d1 +
// ref2_scale * d2, the dither's coefficient -1 * cb21 apart) as the engine resolves it.
CardRecordValues GameRecord() {
    CardRecordValues r;
    r.ref = 0.0f;
    r.ref_scale = 1.0f;  // cb[20]
    r.ref2_scale = 0.5f; // cb[21]
    r.named = {true, true, true, true, true, true, true};
    return r;
}

void TestAlphaRule() {
    const CardRecordValues record = GameRecord();
    // Dyadic grids, where every sum and product here is exact, so both forms decide alike.
    int compared = 0;
    for (int ti = 0; ti <= 64; ++ti) {           // texel alpha
        for (int vi = 0; vi <= 16; vi += 2) {    // vertex colour alpha
            for (int c0 = -8; c0 <= 40; c0 += 3) {       // cb20 in 1/32
                for (int c1 = -16; c1 <= 32; c1 += 4) {  // cb21 in 1/32
                    const float t = float(ti) / 64.0f;
                    const float vc = float(vi) / 16.0f;
                    const float a = t * vc;
                    const float cb20 = float(c0) / 32.0f;
                    const float cb21 = float(c1) / 32.0f;
                    const std::array<float, 7> values{1.0f, 1.0f, 0.0f, 0.0f, cb20, cb21, -cb21};
                    const CardResolved r = CardResolve(record, values);
                    CHECK(r.finite);
                    // the shadow form, exactly
                    const bool ray = CardKeeps(a, r.reference, CardOp::GreaterEqual, true);
                    CHECK(ray == GameShadowKeeps(a, 1.0f, cb20, cb21));
                    // the camera form with its dither texel at 0 is the same test
                    CHECK(ray == GameCameraKeeps(a, 1.0f, cb20, cb21, 0.0f));
                    // and the reference is cb20 + 0.5 * cb21
                    CHECK(r.reference == cb20 + 0.5f * cb21);
                    ++compared;
                }
            }
        }
    }
    CHECK(compared > 50000);

    // Random values: the two forms differ only within rounding of the boundary.
    std::mt19937 rng(54);
    std::uniform_real_distribution<float> unit(0.0f, 1.0f);
    std::uniform_real_distribution<float> wide(-1.0f, 2.0f);
    int differ = 0;
    for (int i = 0; i < 200000; ++i) {
        const float a = unit(rng) * unit(rng);
        const float cb20 = wide(rng);
        const float cb21 = wide(rng);
        const std::array<float, 7> values{1.0f, 1.0f, 0.0f, 0.0f, cb20, cb21, -cb21};
        const float ref = CardResolve(record, values).reference;
        const bool ray = CardKeeps(a, ref, CardOp::GreaterEqual, true);
        if (ray != GameShadowKeeps(a, 1.0f, cb20, cb21)) {
            ++differ;
            CHECK(std::abs(a - ref) <= 4e-7f * (1.0f + std::abs(cb20) + std::abs(cb21)));
        }
    }
    CHECK(differ < 50);

    // A zero alpha is dropped even under a reference below 0 (the nonzero term); without the
    // term it is kept. A negative alpha is not 0: kept by the term (the game's A == 0 test).
    CHECK(!CardKeeps(0.0f, -1.0f, CardOp::GreaterEqual, true));
    CHECK(CardKeeps(0.0f, -1.0f, CardOp::GreaterEqual, false));
    CHECK(CardKeeps(-0.5f, -1.0f, CardOp::GreaterEqual, true));
    CHECK(CardKeeps(-0.5f, -1.0f, CardOp::GreaterEqual, true) == GameShadowKeeps(-0.5f, 1.0f, -1.5f, 1.0f));
    CHECK(GameShadowKeeps(-0.5f, 1.0f, -1.5f, 1.0f)); // reference -1.5 + 0.5: -1
    // the ops
    CHECK(CardKeeps(0.4f, 0.5f, CardOp::Less, false) && !CardKeeps(0.5f, 0.5f, CardOp::Less, false));
    CHECK(CardKeeps(0.5f, 0.5f, CardOp::LessEqual, false) && !CardKeeps(0.6f, 0.5f, CardOp::LessEqual, false));
    CHECK(CardKeeps(0.6f, 0.5f, CardOp::Greater, false) && !CardKeeps(0.5f, 0.5f, CardOp::Greater, false));
    CHECK(CardKeeps(0.5f, 0.5f, CardOp::GreaterEqual, false) && !CardKeeps(0.4f, 0.5f, CardOp::GreaterEqual, false));
    CHECK(CardKeeps(0.5f, 0.5f, CardOp::Equal, false) && !CardKeeps(0.4f, 0.5f, CardOp::Equal, false));
    CHECK(CardKeeps(0.4f, 0.5f, CardOp::NotEqual, false) && !CardKeeps(0.5f, 0.5f, CardOp::NotEqual, false));
    // A NaN alpha: CardKeeps drops it, the game keeps it (its discard compares are ordered and
    // fail on a NaN). A known difference, pinned here; the expand pass marks a corner whose
    // alpha factor is not a number not finite (TestPack), so a Ready record never holds one.
    CHECK(!CardKeeps(std::nanf(""), 0.5f, CardOp::GreaterEqual, false));
    CHECK(!CardKeeps(std::nanf(""), 0.5f, CardOp::GreaterEqual, true));
    CHECK(GameShadowKeeps(std::nanf(""), 1.0f, 0.25f, 0.5f));
    CHECK(GameCameraKeeps(std::nanf(""), 1.0f, 0.25f, 0.5f, 0.0f));
    // The per-instance fade is left out (r50c): with fade 0 the game drops every pixel of the
    // instance, a ray keeps what the alpha test keeps (the instance still casts its shadow); with
    // any other finite fade the two agree.
    CHECK(!GameShadowKeeps(0.5f, 0.0f, 0.25f, 0.0f) && !GameCameraKeeps(0.5f, 0.0f, 0.25f, 0.0f, 0.0f));
    CHECK(CardKeeps(0.5f, 0.25f, CardOp::GreaterEqual, true));
    for (const float fade : {1e-6f, 0.3f, 1.0f, 7.0f}) {
        for (const float a : {0.0f, 0.1f, 0.25f, 0.5f}) {
            CHECK(GameShadowKeeps(a, fade, 0.25f, 0.0f) == CardKeeps(a, 0.25f, CardOp::GreaterEqual, true));
            CHECK(GameShadowKeeps(a, fade, -0.5f, 0.0f) == CardKeeps(a, -0.5f, CardOp::GreaterEqual, true));
        }
    }

    // Immediates where the record names no dword; a dword where it does.
    CardRecordValues imm;
    imm.uv_scale = {2.0f, 3.0f};
    imm.uv_offset = {0.25f, -0.5f};
    imm.ref = 0.5f;
    imm.ref_scale = 7.0f; // not named: left out
    const std::array<float, 7> junk{9, 9, 9, 9, 9, 9, 9};
    CardResolved ri = CardResolve(imm, junk);
    CHECK(ri.affine == (std::array<float, 4>{2.0f, 3.0f, 0.25f, -0.5f}));
    CHECK(ri.reference == 0.5f);
    CHECK(ri.finite);
    imm.named[1] = true;
    imm.named[2] = true;
    imm.named[4] = true;
    ri = CardResolve(imm, junk);
    CHECK(ri.affine == (std::array<float, 4>{2.0f, 9.0f, 9.0f, -0.5f}));
    CHECK(ri.reference == 0.5f + 7.0f * 9.0f);
    // the second dword of the reference counts by its own name, not the first's
    {
        CardRecordValues two;
        two.ref = 0.125f;
        two.ref_scale = 1.0f;
        two.ref2_scale = 0.5f;
        two.named[5] = true; // the second named, the first not
        const std::array<float, 7> v{1, 1, 0, 0, 100.0f, 0.25f, 0};
        CHECK(CardResolve(two, v).reference == 0.125f + 0.5f * 0.25f);
        two.named[5] = false;
        two.named[4] = true; // the first named, the second not
        CHECK(CardResolve(two, v).reference == 0.125f + 100.0f);
    }
    // the dither dword never enters the reference
    std::array<float, 7> dith{1, 1, 0, 0, 0.25f, 0.5f, 1000.0f};
    CHECK(CardResolve(record, dith).reference == 0.5f);
    CHECK(CardResolve(record, dith).dither_scale == 0.0f); // the record has no dither
    // not finite values make no card
    dith[0] = std::nanf("");
    CHECK(!CardResolve(record, dith).finite);
    dith[0] = 1.0f;
    dith[4] = INFINITY;
    CHECK(!CardResolve(record, dith).finite);
    dith[4] = 0.25f;
    dith[6] = INFINITY; // the dither's, without a dither: not used, no matter
    CHECK(CardResolve(record, dith).finite);
    // no plausibility band: any finite reference makes a card, also one <= 0
    // or above 1
    for (const float cb20 : {-3.0f, -0.5f, 0.0f, 0.0392153f, 0.892156f, 1.5f, 1e6f}) {
        const std::array<float, 7> v{1, 1, 0, 0, cb20, 0.0f, 0.0f};
        CHECK(CardResolve(record, v).finite && CardResolve(record, v).reference == cb20);
    }
}

// The camera pass's dither kept apart: the record of the camera form names the
// dither's coefficient -1 * cb[21] (dither_scale -1, its dword cb[21]); the reference stays
// cb20 + 0.5 * cb21 (the dither taken as 0), and reference + dither_scale * D is the game's
// camera pass threshold at any dither texel D.
void TestDitherApart() {
    CardRecordValues record = GameRecord();
    record.dither = true;
    record.dither_scale = -1.0f;
    int compared = 0;
    for (int ti = 0; ti <= 32; ++ti) {
        for (int c0 = -8; c0 <= 40; c0 += 4) {
            for (int c1 = -16; c1 <= 32; c1 += 8) {
                for (int di = 0; di <= 15; ++di) { // the 4x4 dither's 16 levels
                    const float a = float(ti) / 32.0f;
                    const float cb20 = float(c0) / 32.0f;
                    const float cb21 = float(c1) / 32.0f;
                    const float d = float(di) / 16.0f;
                    const std::array<float, 7> values{1.0f, 1.0f, 0.0f, 0.0f, cb20, cb21, cb21};
                    const CardResolved r = CardResolve(record, values);
                    CHECK(r.finite);
                    CHECK(r.reference == cb20 + 0.5f * cb21);
                    CHECK(r.dither_scale == -cb21);
                    CHECK(r.ref_dwords[0] == cb20 && r.ref_dwords[1] == cb21);
                    CHECK(CardKeeps(a, r.reference + r.dither_scale * d, CardOp::GreaterEqual, true) ==
                          GameCameraKeeps(a, 1.0f, cb20, cb21, d));
                    ++compared;
                }
            }
        }
    }
    CHECK(compared > 10000);
    // 998b035e's constants (cb20 0.392156, cb21 1): the reference is the strictest end 0.892156,
    // the threshold runs down to -0.108 at D = 1
    {
        const std::array<float, 7> v{1, 1, 0, 0, 0.392156f, 1.0f, 1.0f};
        const CardResolved r = CardResolve(record, v);
        CHECK(std::abs(r.reference - 0.892156f) < 1e-6f && r.dither_scale == -1.0f);
        CHECK(std::abs(r.reference + r.dither_scale * 1.0f + 0.107844f) < 1e-6f);
    }
    // a coefficient with no dword is the immediate alone; a coefficient that is not finite makes
    // no card
    {
        CardRecordValues imm = record;
        imm.named[CardDwordDither] = false;
        imm.dither_scale = -0.25f;
        const std::array<float, 7> v{1, 1, 0, 0, 0.25f, 0.5f, 99.0f};
        CHECK(CardResolve(imm, v).dither_scale == -0.25f);
        std::array<float, 7> bad = v;
        bad[CardDwordDither] = INFINITY;
        CHECK(!CardResolve(record, bad).finite);
        CHECK(CardResolve(imm, bad).finite); // not named: not used
    }
}

// A guest memory for the guard: records every call, so the order and the reads are checked.
struct FakeGuest {
    std::uint64_t mapped_lo = 0x1000, mapped_hi = 0x2000; // [lo, hi)
    std::uint64_t gpu_lo = 0, gpu_hi = 0;                 // GPU-written region
    bool in_place = false;
    std::vector<char> calls; // 'M', 'G', 'I', 'R'
    int reads = 0;
    bool Mapped(std::uint64_t a, std::uint64_t n) {
        calls.push_back('M');
        return a >= mapped_lo && a + n <= mapped_hi;
    }
    bool GpuModified(std::uint64_t a, std::uint64_t n) {
        calls.push_back('G');
        return a < gpu_hi && a + n > gpu_lo;
    }
    bool InPlace(std::uint64_t, std::uint64_t) {
        calls.push_back('I');
        return in_place;
    }
    std::uint32_t Read(std::uint64_t a) {
        calls.push_back('R');
        ++reads;
        return std::uint32_t(a * 3u);
    }
};

void TestGuard() {
    CardBufferFacts b{true, false, false, true, 0x1000, 0x100};
    {
        FakeGuest g;
        std::uint32_t raw = 0;
        CHECK(ReadCardBufferDword(b, 20, g, raw) == CardDwordState::Read);
        CHECK(raw == std::uint32_t((0x1000 + 80) * 3));
        CHECK((g.calls == std::vector<char>{'M', 'G', 'R'}));
    }
    {
        // the GPU wrote it: never read
        FakeGuest g;
        g.gpu_lo = 0x1050;
        g.gpu_hi = 0x1054;
        std::uint32_t raw = 77;
        CHECK(ReadCardBufferDword(b, 20, g, raw) == CardDwordState::GpuWritten);
        CHECK(g.reads == 0 && raw == 77);
        // a dword beside it is read
        CHECK(ReadCardBufferDword(b, 21, g, raw) == CardDwordState::Read);
        g.in_place = true;
        g.reads = 0;
        CHECK(ReadCardBufferDword(b, 20, g, raw) == CardDwordState::InPlace);
        CHECK(g.reads == 0);
    }
    {
        // outside the mapping: not even asked about the GPU
        FakeGuest g;
        g.mapped_hi = 0x1050;
        std::uint32_t raw = 0;
        CHECK(ReadCardBufferDword(b, 20, g, raw) == CardDwordState::Unreadable);
        CHECK((g.calls == std::vector<char>{'M'}));
    }
    {
        // the buffer's checks come before any memory call
        FakeGuest g;
        std::uint32_t raw = 0;
        CardBufferFacts x = b;
        x.bound = false;
        CHECK(ReadCardBufferDword(x, 0, g, raw) == CardDwordState::Unreadable);
        x = b;
        x.special = true;
        CHECK(ReadCardBufferDword(x, 0, g, raw) == CardDwordState::Unreadable);
        x = b;
        x.written = true;
        CHECK(ReadCardBufferDword(x, 0, g, raw) == CardDwordState::GpuWritten);
        x = b;
        x.valid = false;
        CHECK(ReadCardBufferDword(x, 0, g, raw) == CardDwordState::Unreadable);
        x = b;
        CHECK(ReadCardBufferDword(x, 0x40, g, raw) == CardDwordState::Unreadable); // past size
        CHECK(ReadCardBufferDword(x, 0x3f, g, raw) == CardDwordState::Read);       // last dword
        CHECK(g.reads == 1);
    }
    {
        const std::uint32_t user[4] = {1, 2, 3, 4};
        std::uint32_t raw = 0;
        CHECK(ReadCardUserDword(user, 3, raw) == CardDwordState::Read && raw == 4);
        CHECK(ReadCardUserDword(user, 4, raw) == CardDwordState::Unreadable);
    }
    CHECK(CardWorse(CardDwordState::Read, CardDwordState::InPlace) == CardDwordState::InPlace);
    CHECK(CardWorse(CardDwordState::GpuWritten, CardDwordState::InPlace) == CardDwordState::GpuWritten);
    CHECK(CardWorse(CardDwordState::Unreadable, CardDwordState::Read) == CardDwordState::Unreadable);
}

void TestHalf() {
    // every half: back to float and again, the same bits (NaNs stay NaNs)
    for (std::uint32_t h = 0; h < 65536; ++h) {
        const float f = CardHalfToFloat(std::uint16_t(h));
        const std::uint16_t again = CardHalf(f);
        if ((h & 0x7c00u) == 0x7c00u && (h & 0x3ffu) != 0) {
            CHECK(f != f);
            CHECK((again & 0x7c00u) == 0x7c00u && (again & 0x3ffu) != 0);
        } else {
            CHECK(again == h);
        }
    }
#if defined(__FLT16_MAX__)
    // against the compiler's conversion (round to nearest even)
    std::mt19937 rng(16);
    std::uniform_real_distribution<float> d(-70000.0f, 70000.0f);
    std::uniform_real_distribution<float> s(-8.0f, 8.0f);
    for (int i = 0; i < 400000; ++i) {
        const float f = (i & 1) ? d(rng) : s(rng) * std::ldexp(1.0f, -(i % 30));
        const _Float16 ref = _Float16(f);
        std::uint16_t bits;
        std::memcpy(&bits, &ref, 2);
        CHECK(CardHalf(f) == bits);
    }
#endif
    CHECK(CardHalf(1.0f) == 0x3c00u);
    CHECK(CardHalf(-2.0f) == 0xc000u);
    CHECK(CardHalf(65504.0f) == 0x7bffu);
    CHECK(CardHalf(65520.0f) == 0x7c00u); // rounds up to infinity
    CHECK(CardHalf(1e-8f) == 0);
    CHECK(CardHalfToFloat(0x0001u) == std::ldexp(1.0f, -24));
}

void TestPack() {
    // unorm8
    CHECK(CardUnorm8(0.0f) == 0 && CardUnorm8(1.0f) == 255 && CardUnorm8(-1.0f) == 0 &&
          CardUnorm8(2.0f) == 255 && CardUnorm8(std::nanf("")) == 0);
    CHECK(CardUnorm8(0.5f) == 128); // 127.5 + 0.5
    for (int k = 0; k <= 255; ++k) {
        CHECK(CardUnorm8(float(k) / 255.0f) == std::uint32_t(k));
    }
    // shifts
    CHECK(CardShift(3.2f, 3.9f, 4.1f, CARD_UV_MODE_WRAP) == 3.0f);
    CHECK(CardShift(-0.2f, 0.5f, 0.1f, CARD_UV_MODE_WRAP) == -1.0f);
    CHECK(CardShift(3.2f, 3.9f, 4.1f, CARD_UV_MODE_MIRROR) == 2.0f);
    CHECK(CardShift(5.5f, 6.0f, 5.9f, CARD_UV_MODE_MIRROR) == 4.0f);
    CHECK(CardShift(-0.5f, 0.5f, 0.5f, CARD_UV_MODE_MIRROR) == -2.0f);
    CHECK(CardShift(3.2f, 3.9f, 4.1f, CARD_UV_MODE_CLAMP) == 0.0f);

    std::mt19937 rng(4);
    std::uniform_real_distribution<float> base(-300.0f, 300.0f);
    std::uniform_real_distribution<float> spread(0.0f, 1.5f);
    std::uniform_real_distribution<float> unit(0.0f, 1.0f);
    for (int i = 0; i < 100000; ++i) {
        const std::uint32_t mu = std::uint32_t(i % 3), mv = std::uint32_t((i / 3) % 3);
        const bool has_alpha = (i & 4) != 0;
        const float bu = (mu == CARD_UV_MODE_CLAMP) ? unit(rng) : base(rng);
        const float bv = (mv == CARD_UV_MODE_CLAMP) ? unit(rng) : base(rng);
        std::array<CardCorner, 3> c{};
        for (CardCorner& k : c) {
            k = {bu + spread(rng), bv + spread(rng), unit(rng)};
        }
        const std::array<std::uint32_t, 4> w = CardPackTriangle(c, mu, mv, has_alpha);
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(w, out, flags);
        CHECK((flags & CARD_UV_TRI_NOT_FINITE) == 0);
        CHECK(((flags & CARD_UV_TRI_NO_ALPHA) != 0) == !has_alpha);
        const float su = CardShift(c[0].u, c[1].u, c[2].u, mu);
        const float sv = CardShift(c[0].v, c[1].v, c[2].v, mv);
        // the shift keeps the sampled texel: whole repeats (wrap) or pairs (mirror)
        CHECK(su == std::floor(su) && sv == std::floor(sv));
        if (mu == CARD_UV_MODE_MIRROR) {
            CHECK(std::fmod(su, 2.0f) == 0.0f);
        }
        bool wide = false;
        for (std::size_t k = 0; k < 3; ++k) {
            const float eu = c[k].u - su, ev = c[k].v - sv;
            wide = wide || std::abs(eu) >= 4.0f || std::abs(ev) >= 4.0f;
            // half precision of a value below 4: error at most 2^-10 (half an ulp of 2^-9);
            // the shift itself is exact for these magnitudes
            CHECK(std::abs(out[k].u - eu) <= std::ldexp(1.0f, -10) * std::max(1.0f, std::abs(eu)) / 2.0f + 1e-6f);
            CHECK(std::abs(out[k].v - ev) <= std::ldexp(1.0f, -10) * std::max(1.0f, std::abs(ev)) / 2.0f + 1e-6f);
            if (has_alpha) {
                CHECK(std::abs(out[k].a - c[k].a) <= 0.5f / 255.0f + 1e-6f);
            } else {
                CHECK(out[k].a == 1.0f);
            }
        }
        CHECK(((flags & CARD_UV_TRI_WIDE) != 0) == wide);
        // a spread below 1.5 after a wrap shift is never wide
        if (mu == CARD_UV_MODE_WRAP && mv == CARD_UV_MODE_WRAP) {
            CHECK(!wide);
        }
    }
    // a wide one: marked, kept
    {
        const std::array<CardCorner, 3> c{{{0.0f, 0.0f, 1.0f}, {9.5f, 0.0f, 1.0f}, {0.0f, 1.0f, 1.0f}}};
        const auto w = CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true);
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(w, out, flags);
        CHECK(flags == CARD_UV_TRI_WIDE);
        CHECK(out[1].u == 9.5f);
    }
    // exactly 4.0 after the shift is wide; just below is not
    {
        std::array<CardCorner, 3> c{{{0.0f, 0.0f, 1.0f}, {4.0f, 0.0f, 1.0f}, {0.0f, 1.0f, 1.0f}}};
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_WIDE);
        c[1].u = 3.99f;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == 0);
        c[1] = {0.5f, -4.0f, 1.0f}; // and on v, below 0 (clamp: no shift)
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_CLAMP, CARD_UV_MODE_CLAMP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_WIDE);
    }
    // an alpha factor that is not a number (a vertex no capture stored: CARD_UV_RING_UNSET)
    // marks the triangle not finite; without an alpha factor the value is not looked at
    {
        float unset = 0.0f;
        const std::uint32_t bits = CARD_UV_RING_UNSET;
        std::memcpy(&unset, &bits, 4);
        CHECK(unset != unset);
        std::array<CardCorner, 3> c{{{0.5f, 0.5f, 1.0f}, {0.6f, 0.5f, unset}, {0.5f, 0.6f, 1.0f}}};
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_NOT_FINITE);
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, false), out, flags);
        CHECK(flags == CARD_UV_TRI_NO_ALPHA);
        // an unset coordinate too
        c[1] = {unset, unset, 1.0f};
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, false), out, flags);
        CHECK(flags == (CARD_UV_TRI_NOT_FINITE | CARD_UV_TRI_NO_ALPHA));
    }
    // clamp keeps large coordinates as they are (no shift)
    {
        const std::array<CardCorner, 3> c{{{5.0f, 0.5f, 1.0f}, {5.5f, 0.5f, 1.0f}, {5.0f, 1.0f, 1.0f}}};
        const auto w = CardPackTriangle(c, CARD_UV_MODE_CLAMP, CARD_UV_MODE_CLAMP, false);
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(w, out, flags);
        CHECK(flags == (CARD_UV_TRI_WIDE | CARD_UV_TRI_NO_ALPHA));
        CHECK(out[0].u == 5.0f && out[1].u == 5.5f);
        CHECK((w[3] & 0xffffffu) == 0xffffffu);
    }
    // not finite: marked, not shifted
    {
        const std::array<CardCorner, 3> c{{{std::nanf(""), 0.5f, 1.0f}, {5.5f, 0.5f, 1.0f}, {5.0f, 1.0f, 1.0f}}};
        const auto w = CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true);
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(w, out, flags);
        CHECK(flags == CARD_UV_TRI_NOT_FINITE);
        CHECK(out[0].u != out[0].u);
        CHECK(out[1].u == 5.5f);
    }
    // the layout: words 0-2 corner (u low half, v high half), word 3 alphas and flags
    {
        const std::array<CardCorner, 3> c{{{0.5f, 0.25f, 0.0f}, {1.0f, 0.75f, 1.0f}, {0.5f, 1.5f, 0.5f}}};
        const auto w = CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true);
        CHECK(sizeof(w) == CARD_UV_RECORD_BYTES);
        CHECK(w[0] == (0x3800u | (0x3400u << 16)));
        CHECK(w[1] == (0x3c00u | (0x3a00u << 16)));
        CHECK(w[2] == (0x3800u | (0x3e00u << 16)));
        // 0.5 is 127.5 steps: off the 8-bit steps, so marked rounded
        CHECK(w[3] == (0u | (255u << 8) | (128u << 16) |
                       (std::uint32_t(CARD_UV_TRI_ALPHA_ROUNDED) << CARD_UV_FLAGS_SHIFT)));
    }
    // the affine comes first
    {
        const CardCorner k = CardApplyAffine({0.5f, 2.0f, 0.3f}, {2.0f, 0.5f, 0.25f, -1.0f});
        CHECK(k.u == 1.25f && k.v == 0.0f && k.a == 0.3f);
    }
}

// The alpha factor in 8 bits. The game's A = texel alpha * the interpolated factor; a ray's
// A = texel alpha * the interpolation of the stored factor. Texel alphas are t / 255 (BC1 gives 0
// or 1, BC7 decodes to 8 bits).
void TestAlphaFactorBits() {
    // the marks: exact steps none, between steps rounded, outside [0, 1] range
    for (int k = 0; k <= 255; ++k) {
        CHECK(CardAlphaMarks(float(k) / 255.0f) == 0u);
        if (k < 255) {
            CHECK(CardAlphaMarks((float(k) + 0.5f) / 255.0f) == CARD_UV_TRI_ALPHA_ROUNDED);
            CHECK(CardAlphaMarks((float(k) + 0.01f) / 255.0f) == CARD_UV_TRI_ALPHA_ROUNDED);
        }
    }
    CHECK(CardAlphaMarks(-0.001f) == CARD_UV_TRI_ALPHA_RANGE);
    CHECK(CardAlphaMarks(1.001f) == CARD_UV_TRI_ALPHA_RANGE);
    CHECK(CardAlphaMarks(-0.0f) == 0u);
    // The range test has the grid's tolerance: 1 + 1 ulp and -1e-9 are not marked (their
    // clamp moves them by less than 2.4e-7); a little farther out is
    CHECK(CardAlphaMarks(std::nextafter(1.0f, 2.0f)) == 0u);
    CHECK(CardAlphaMarks(-1e-9f) == 0u);
    CHECK(CardAlphaMarks(1.0f + 1e-6f) == CARD_UV_TRI_ALPHA_RANGE);
    CHECK(CardAlphaMarks(-1e-6f) == CARD_UV_TRI_ALPHA_RANGE);
    CHECK(CardAlphaRangeTolerance > 2.3e-7f && CardAlphaRangeTolerance < 2.5e-7f);
    // The grid tolerance is 2^-14 of a step. 3e-6 below 50 / 255 (7.65e-4 of a step) is
    // marked: unmarked, unorm8 would store 50 and a ray would keep what the game drops (texel 1,
    // reference 50 / 255). 2^-12 of a step off is marked too; a few ulps off is not.
    CHECK(CARD_UV_ALPHA_GRID_EPS == 1.0 / 16384.0);
    {
        const float a = 50.0f / 255.0f - 3e-6f;
        CHECK(CardAlphaMarks(a) == CARD_UV_TRI_ALPHA_ROUNDED);
        CHECK(!CardKeeps(1.0f * a, 50.0f / 255.0f, CardOp::GreaterEqual, true)); // the game drops
        CHECK(CardUnorm8(a) == 50u);                                            // stored as 50
    }
    for (int k = 1; k < 255; ++k) {
        const float step = 1.0f / 255.0f;
        CHECK(CardAlphaMarks(float(k) / 255.0f + step / 4096.0f) == CARD_UV_TRI_ALPHA_ROUNDED);
        CHECK(CardAlphaMarks(float(k) / 255.0f - step / 4096.0f) == CARD_UV_TRI_ALPHA_ROUNDED);
        CHECK(CardAlphaMarks(std::nextafter(std::nextafter(float(k) / 255.0f, 2.0f), 2.0f)) == 0u);
    }
    // a factor a vertex shader made as k / 255 in another order of operations (one ulp off)
    // is still on the step
    for (int k = 1; k < 255; ++k) {
        const float a = float(k) / 255.0f;
        CHECK(CardAlphaMarks(std::nextafter(a, 2.0f)) == 0u);
        CHECK(CardAlphaMarks(std::nextafter(a, -1.0f)) == 0u);
    }
    // the record's flags: range and rounded per triangle, only with an alpha factor
    {
        std::array<CardCorner, 3> c{{{0.5f, 0.5f, 1.0f}, {0.6f, 0.5f, 50.0f / 255.0f}, {0.5f, 0.6f, 0.0f}}};
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == 0);
        c[2].a = 1.25f;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_ALPHA_RANGE);
        CHECK(out[2].a == 1.0f); // clamped: why a reader takes it as no card data
        c[2].a = -0.25f;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_ALPHA_RANGE);
        c[2].a = 49.7f / 255.0f;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_ALPHA_ROUNDED);
        c[1].a = 2.0f;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == (CARD_UV_TRI_ALPHA_RANGE | CARD_UV_TRI_ALPHA_ROUNDED));
        // without an alpha factor the values are not looked at
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, false), out, flags);
        CHECK(flags == CARD_UV_TRI_NO_ALPHA);
    }

    std::mt19937 rng(7);
    std::uniform_int_distribution<int> step(0, 255);
    std::uniform_real_distribution<float> unit(0.0f, 1.0f);
    const float refs[] = {50.0f / 255.0f, 0.2f, 0.3f, 0.5f, 128.0f / 255.0f, 0.75f};
    const auto weights = [&](float& b0, float& b1, float& b2) {
        b0 = unit(rng);
        b1 = unit(rng) * (1.0f - b0);
        b2 = 1.0f - b0 - b1;
    };
    // Factors on the 8-bit steps: the stored factor is the same float, so a ray's A is the
    // game's A bit for bit and every decision is the same (the reference too: 50 / 255).
    int decisions = 0;
    for (int i = 0; i < 200000; ++i) {
        std::array<CardCorner, 3> c{};
        for (CardCorner& k : c) {
            k = {unit(rng), unit(rng), float(step(rng)) / 255.0f};
        }
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK((flags & (CARD_UV_TRI_ALPHA_RANGE | CARD_UV_TRI_ALPHA_ROUNDED)) == 0);
        float b0, b1, b2;
        weights(b0, b1, b2);
        const float texel = float(step(rng)) / 255.0f;
        const float game = texel * (b0 * c[0].a + b1 * c[1].a + b2 * c[2].a);
        const float ray = texel * (b0 * out[0].a + b1 * out[1].a + b2 * out[2].a);
        CHECK(game == ray);
        for (const float ref : refs) {
            CHECK(CardKeeps(game, ref, CardOp::GreaterEqual, true) == CardKeeps(ray, ref, CardOp::GreaterEqual, true));
            ++decisions;
        }
    }
    CHECK(decisions == 200000 * int(std::size(refs)));
    // Factors between the steps: marked rounded; the difference is at most texel * 0.5 / 255
    // (and float rounding), and only texels that close to the reference can change side.
    int flipped = 0;
    for (int i = 0; i < 200000; ++i) {
        std::array<CardCorner, 3> c{};
        for (CardCorner& k : c) {
            // a quarter to three quarters of a step past k / 255: off the steps, in [0, 1]
            k = {unit(rng), unit(rng), (float(step(rng) % 255) + 0.25f + 0.5f * unit(rng)) / 255.0f};
        }
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_ALPHA_ROUNDED);
        float b0, b1, b2;
        weights(b0, b1, b2);
        const float texel = float(step(rng)) / 255.0f;
        const float game = texel * (b0 * c[0].a + b1 * c[1].a + b2 * c[2].a);
        const float ray = texel * (b0 * out[0].a + b1 * out[1].a + b2 * out[2].a);
        const float bound = texel * 0.5f / 255.0f + 1e-6f;
        CHECK(std::abs(game - ray) <= bound);
        for (const float ref : refs) {
            if (CardKeeps(game, ref, CardOp::GreaterEqual, true) != CardKeeps(ray, ref, CardOp::GreaterEqual, true)) {
                ++flipped;
                CHECK(std::abs(game - ref) <= bound);
            }
        }
    }
    CHECK(flipped > 0); // it happens: why the triangle is marked
    // The example of rt_card_alpha.md: texel alpha 1, factor 49.7 / 255 at all three corners,
    // reference 50 / 255: the game drops it, the stored 50 / 255 keeps it.
    {
        const float a = 49.7f / 255.0f;
        const float ref = 50.0f / 255.0f;
        const std::array<CardCorner, 3> c{{{0.0f, 0.0f, a}, {1.0f, 0.0f, a}, {0.0f, 1.0f, a}}};
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_ALPHA_ROUNDED);
        CHECK(!CardKeeps(1.0f * a, ref, CardOp::GreaterEqual, true));
        CHECK(CardKeeps(1.0f * out[0].a, ref, CardOp::GreaterEqual, true));
    }
}

void TestPushAndStats() {
    CardUvPush p;
    CHECK(sizeof(p) == 48);
    const std::uint32_t f = CardPushFlags(CARD_UV_MODE_MIRROR, CARD_UV_MODE_CLAMP, true, 3);
    CHECK((f & 3u) == CARD_UV_MODE_MIRROR);
    CHECK(((f >> CARD_UV_PUSH_MODE_V_SHIFT) & 3u) == CARD_UV_MODE_CLAMP);
    CHECK((f & CARD_UV_PUSH_HAS_ALPHA) != 0);
    CHECK(((f >> CARD_UV_PUSH_STAT_SHIFT) & 7u) == 3u);
    CHECK(CardPushFlags(0, 0, false, 0) == 0);
    CHECK(CARD_UV_STAT_SLOTS + 1 <= 8); // slot + 1 fits three bits

    // keys keep the order of floats
    const float vals[] = {-INFINITY, -1e9f, -2.0f, -0.5f, -0.0f, 0.0f, 1e-30f, 0.5f, 2.0f, 1e9f, INFINITY};
    for (std::size_t i = 0; i + 1 < std::size(vals); ++i) {
        CHECK(CardStatKey(vals[i]) <= CardStatKey(vals[i + 1]));
        CHECK(CardStatValue(CardStatKey(vals[i])) == vals[i]);
    }
    CHECK(CardStatKey(-1.0f) < CardStatKey(1.0f));
    // a slot as the shader fills it: min as atomicMax(~key), max as atomicMax(key)
    std::uint32_t w[CARD_UV_STAT_WORDS] = {};
    CHECK(!CardReadStat(w).any);
    const float us[] = {0.25f, -3.0f, 2.5f};
    for (float u : us) {
        w[0] = std::max(w[0], ~CardStatKey(u));
        w[3] = std::max(w[3], CardStatKey(u));
        w[1] = std::max(w[1], ~CardStatKey(u * 2));
        w[4] = std::max(w[4], CardStatKey(u * 2));
        w[2] = std::max(w[2], ~CardStatKey(0.5f));
        w[5] = std::max(w[5], CardStatKey(0.5f));
    }
    w[6] = 2;
    w[7] = 1;
    w[8] = 4;
    w[9] = 5;
    const CardStat s = CardReadStat(w);
    CHECK(s.any && s.umin == -3.0f && s.umax == 2.5f && s.vmin == -6.0f && s.vmax == 5.0f &&
          s.amin == 0.5f && s.amax == 0.5f && s.wide == 2 && s.not_finite == 1 &&
          s.alpha_range == 4 && s.alpha_rounded == 5);
    // the shader takes atomicMax for the bounds, atomicAdd for the counts
    CHECK(CARD_UV_STAT_WORDS == 10 && CARD_UV_STAT_MAX_WORDS == 6);
    CHECK(CARD_UV_STAT_WORDS <= CARD_UV_GROUP); // one thread a word zeroes and adds the group's
    // the flags fit the record's 8 bits
    CHECK(((CARD_UV_TRI_WIDE | CARD_UV_TRI_NO_ALPHA | CARD_UV_TRI_NOT_FINITE | CARD_UV_TRI_ALPHA_RANGE |
            CARD_UV_TRI_ALPHA_ROUNDED) >> 8) == 0);
}

CardDraw MakeDraw(bool camera, std::uint64_t ps, float scale, float ref) {
    CardDraw d;
    d.valid = true;
    d.camera = camera;
    d.ps_hash = ps;
    d.selector = PackCardSelector({4, 0, 1, 2, 3, true});
    d.affine = {scale, scale, 0.0f, 0.0f};
    d.reference = ref;
    d.nonzero = true;
    d.tsharp = {1, 2, 3, 4, 5, 6, 7, 8};
    CardFinishHashes(d);
    return d;
}

void TestStates() {
    // hashes tell the parts apart (a, b, c and scroll are sun shadow pass cards)
    CardDraw a = MakeDraw(false, 10, 1.0f, 0.5f);
    CardDraw b = MakeDraw(false, 10, 1.0f, 0.6f);
    CardDraw c = MakeDraw(false, 10, 2.0f, 0.5f);
    CHECK(a.uv_hash == b.uv_hash && a.constants_hash != b.constants_hash);
    CHECK(a.uv_hash != c.uv_hash);
    CardDraw t = a;
    t.tsharp[3] = 99;
    CardFinishHashes(t);
    CHECK(t.uv_hash == a.uv_hash && t.constants_hash != a.constants_hash);
    t = a;
    t.mode_u = CARD_UV_MODE_MIRROR;
    CardFinishHashes(t);
    CHECK(t.uv_hash != a.uv_hash);
    // the offset is not the pool's: a moving offset changes the constants, not the coordinates
    CardDraw scroll = a;
    scroll.affine[2] = 0.375f;
    scroll.affine[3] = -2.5f;
    CardFinishHashes(scroll);
    CHECK(scroll.uv_hash == a.uv_hash && scroll.constants_hash != a.constants_hash);
    CHECK((CardPoolAffine(scroll.affine) == std::array<float, 4>{1.0f, 1.0f, 0.0f, 0.0f}));
    CHECK((CardPoolAffine({2.0f, 0.5f, 7.0f, 9.0f}) == std::array<float, 4>{2.0f, 0.5f, 0.0f, 0.0f}));
    // and adding the offset to the pooled (scaled, shifted) corner samples the texel the game
    // samples: the difference is whole repeats (wrap) or pairs (mirror)
    for (const std::uint32_t mode : {std::uint32_t(CARD_UV_MODE_WRAP), std::uint32_t(CARD_UV_MODE_MIRROR)}) {
        const std::array<float, 4> affine{2.0f, 2.0f, 0.375f, -2.5f};
        std::array<CardCorner, 3> raw{{{3.25f, 1.5f, 1.0f}, {3.5f, 1.75f, 1.0f}, {3.25f, 2.0f, 1.0f}}};
        std::array<CardCorner, 3> pooled{};
        for (std::size_t k = 0; k < 3; ++k) {
            pooled[k] = CardApplyAffine(raw[k], CardPoolAffine(affine));
        }
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(pooled, mode, mode, false), out, flags);
        const float period = mode == CARD_UV_MODE_MIRROR ? 2.0f : 1.0f;
        for (std::size_t k = 0; k < 3; ++k) {
            const CardCorner game = CardApplyAffine(raw[k], affine);
            const float du = (out[k].u + affine[2]) - game.u;
            const float dv = (out[k].v + affine[3]) - game.v;
            CHECK(std::fmod(du, period) == 0.0f && std::fmod(dv, period) == 0.0f);
        }
    }

    // The pixel shader is in uv_hash: two passes' cards with the same selector, scale and
    // modes have different uv_hash, so a capture made for one is never Ready for the other
    {
        const CardDraw sun = MakeDraw(false, 10, 1.0f, 0.5f);
        const CardDraw camera = MakeDraw(true, 20, 1.0f, 0.5f);
        CHECK(sun.selector == camera.selector && sun.affine == camera.affine);
        CHECK(sun.uv_hash != camera.uv_hash);
        CHECK(MakeDraw(true, 10, 1.0f, 0.5f).uv_hash == sun.uv_hash); // the pass itself is not
    }
    // The dither's coefficient, the reference's dwords and the fade flag
    // are constants (not coordinates)
    for (int part = 0; part < 4; ++part) {
        CardDraw k = a;
        if (part == 0) {
            k.dither_scale = -1.0f;
        } else if (part == 1) {
            k.ref_dwords[0] = 0.25f;
        } else if (part == 2) {
            k.ref_dwords[1] = 1.0f;
        } else {
            k.fade_left_out = true;
        }
        CardFinishHashes(k);
        CHECK(k.uv_hash == a.uv_hash && k.constants_hash != a.constants_hash);
    }

    // the sun shadow pass preferred: CardTakes(have, have_camera, camera, stale, sun_gone)
    CHECK(CardTakes(false, false, false, false, false)); // no card: a sun card is taken
    CHECK(CardTakes(false, false, true, false, false));  // no card: a camera card is taken
    CHECK(CardTakes(true, false, false, false, false));  // a sun card replaces a sun card
    CHECK(CardTakes(true, true, false, false, false));   // a sun card replaces a camera card
    CHECK(CardTakes(true, true, true, false, false));    // a camera card replaces a camera card
    CHECK(!CardTakes(true, false, true, false, false));  // not a sun card the sun pass still gives
    CHECK(CardTakes(true, false, true, true, false));    // a stale sun card gives way
    CHECK(CardTakes(true, false, true, false, true));    // a sun card no longer given
    CHECK(CardTakes(true, false, false, true, true));    // a sun card always replaces

    constexpr std::uint64_t f = 100; // the frame of every draw below (the sun card stays given)
    CardUv e;
    CardDraw miss;
    miss.miss = CardMiss::Constants;
    CHECK(!CardNote(e, miss, f).taken);
    CHECK(e.state == CardUvState::NotCard && e.miss == CardMiss::Constants);
    CHECK(!CardStale(e)); // no card: waiting, not stale
    CHECK(e.passes == 0 && !CardBothDiffer(e));

    // a camera pass card first
    CardDraw cam = MakeDraw(true, 20, 1.0f, 0.45f);
    CardNoted n = CardNote(e, cam, f);
    CHECK(n.taken && n.coordinates && !n.other && !n.both);
    CHECK(e.state == CardUvState::Wanted && e.miss == CardMiss::None);
    CHECK(CardCaptureWanted(e, 0));
    CHECK(e.passes == 2 && e.pass_reference[1] == 0.45f && e.pass_ps_hash[1] == 20);
    CHECK(!CardBothDiffer(e)); // one pass only: nothing to compare
    // the sun shadow pass card replaces it (another pixel shader: coordinates again); the
    // entry now has both passes' references, once
    n = CardNote(e, a, f);
    CHECK(n.taken && n.coordinates && n.both);
    CHECK(!e.card.camera && e.state == CardUvState::Wanted);
    CHECK(e.passes == 3 && e.pass_reference[0] == 0.5f && e.pass_ps_hash[0] == 10);
    CHECK(CardBothDiffer(e)); // 0.5 and 0.45
    // a camera pass card no longer does, but its reference is kept for the log
    CardDraw cam_same = MakeDraw(true, 20, 1.0f, 0.5f);
    n = CardNote(e, cam_same, f);
    CHECK(!n.taken && !n.both);
    CHECK(e.card.ps_hash == 10 && e.pass_reference[1] == 0.5f && !CardBothDiffer(e));
    n = CardNote(e, cam, f);
    CHECK(!n.taken && !n.both && CardBothDiffer(e));
    CHECK(e.card.ps_hash == 10);
    // recorded, then ready once the GPU is past it
    CardRecorded(e, 77);
    CHECK(e.state == CardUvState::Pending && e.tick == 77);
    CHECK(!CardCaptureWanted(e, 0));
    CHECK(!CardSettle(e, false) && e.state == CardUvState::Pending);
    CHECK(CardSettle(e, true) && e.state == CardUvState::Ready);
    CHECK(!CardSettle(e, true));
    // the same card again: nothing
    n = CardNote(e, a, f);
    CHECK(n.taken && !n.coordinates && !n.other && e.state == CardUvState::Ready);
    // only the reference changed: counted, the pool keeps the UVs
    n = CardNote(e, b, f);
    CHECK(n.taken && !n.coordinates && n.other && e.state == CardUvState::Ready);
    // only the offset changed (scrolling UVs): the same, Ready stays
    n = CardNote(e, scroll, f);
    CHECK(n.taken && !n.coordinates && n.other && e.state == CardUvState::Ready);
    CHECK(e.card.affine[2] == 0.375f); // the card has the newest offset for its reader
    // CardGotRoom touches nothing but NoRoom
    CardGotRoom(e);
    CHECK(e.state == CardUvState::Ready);
    {
        CardUv p = e;
        p.state = CardUvState::Pending;
        CardGotRoom(p);
        CHECK(p.state == CardUvState::Pending);
    }
    // stale: a sun shadow pass draw without card data after the sun shadow pass's card; a
    // camera pass draw without card data does not make it stale; the next sun card clears it
    CHECK(!CardStale(e));
    CardDraw lost;
    lost.camera = false;
    lost.miss = CardMiss::Constants;
    CHECK(!CardNote(e, lost, f).taken);
    CHECK(CardStale(e) && e.miss == CardMiss::Constants && e.state == CardUvState::Ready);
    n = CardNote(e, scroll, f);
    CHECK(n.taken && !CardStale(e));
    CardDraw cam_lost;
    cam_lost.camera = true;
    cam_lost.miss = CardMiss::OtherPermutation;
    CHECK(!CardNote(e, cam_lost, f).taken && !CardStale(e));
    // A valid camera card while the sun card is stale: taken (the sun card gave way), not
    // stale any more; a later sun draw without card data is of the other pass then: no miss
    CHECK(!CardNote(e, lost, f).taken && CardStale(e));
    n = CardNote(e, cam, f);
    CHECK(n.taken && n.sun_gave_way && n.coordinates && e.card.camera && !CardStale(e));
    CHECK(e.state == CardUvState::Wanted); // another pixel shader: captured again
    CHECK(!CardNote(e, lost, f).taken && !CardStale(e) && e.card.camera);
    // the sun shadow pass gives a card again: taken back
    n = CardNote(e, b, f);
    CHECK(n.taken && !n.sun_gave_way && n.coordinates && !e.card.camera && !CardStale(e));
    // the scale changed: wanted again
    n = CardNote(e, c, f);
    CHECK(n.coordinates && e.state == CardUvState::Wanted && e.wait_frames == 0);
    // a draw of the other pass without card data later changes nothing of a card
    CHECK(!CardNote(e, cam_lost, f).taken && e.state == CardUvState::Wanted && e.miss == CardMiss::None);

    // waiting frames and the UV-only capture
    for (std::uint32_t i = 0; i + 1 < CardWaitFrames; ++i) {
        CardWaitFrame(e);
    }
    CHECK(!CardUvOnlyDue(e, 0));
    CardWaitFrame(e);
    CHECK(CardUvOnlyDue(e, 0));

    // no room: wait for the pool to change
    CardNoRoom(e, 5);
    CHECK(e.state == CardUvState::NoRoom);
    CHECK(!CardCaptureWanted(e, 5));
    CHECK(CardCaptureWanted(e, 6));
    // a new card while NoRoom keeps NoRoom (no block yet)
    n = CardNote(e, a, f);
    CHECK(n.coordinates && e.state == CardUvState::NoRoom);
    CardRecorded(e, 9); // not Wanted: no change
    CHECK(e.state == CardUvState::NoRoom);
    CardGotRoom(e);
    CHECK(e.state == CardUvState::Wanted);
    CardGotRoom(e);
    CHECK(e.state == CardUvState::Wanted);

    CHECK(CardClassOf(true, true) == CardClass::Plant);
    CHECK(CardClassOf(false, true) == CardClass::Static);
    CHECK(CardClassOf(false, false) == CardClass::Static);
    CHECK(CardClassOf(true, false) == CardClass::SkinnedKept);
}

// The orders in which the two passes' cards arrive. sun: a sun
// shadow pass card (ps 10), cam: a camera pass card (ps 20, another reference).
void TestSunOrders() {
    const CardDraw sun = MakeDraw(false, 10, 1.0f, 0.196078f);
    const CardDraw cam = MakeDraw(true, 20, 1.0f, 0.50196f);
    CardDraw sun_lost;
    sun_lost.camera = false;
    sun_lost.miss = CardMiss::Constants;
    CHECK(CardSunFrames == 17);
    {
        // camera then sun: the sun card replaces the camera card; the pair is said once
        CardUv e;
        CardNoted n = CardNote(e, cam, 1);
        CHECK(n.taken && e.card.camera && !n.both);
        n = CardNote(e, sun, 1);
        CHECK(n.taken && n.both && n.coordinates && !n.sun_gave_way && !e.card.camera);
        CHECK(e.sun_frame == 1 && e.pass_reference[1] == 0.50196f && e.pass_reference[0] == 0.196078f);
        // each pass's second reference dword (cb[21]) is kept for the log, taken or not
        CardDraw cam21 = cam;
        cam21.ref_dwords = {0.392156f, 1.0f};
        CardFinishHashes(cam21);
        CHECK(!CardNote(e, cam21, 2).taken);
        CHECK(e.pass_ref2[1] == 1.0f && e.pass_ref2[0] == 0.0f);
    }
    {
        // sun then camera: the camera card is not taken, but completes the pair
        CardUv e;
        CHECK(CardNote(e, sun, 1).taken);
        const CardNoted n = CardNote(e, cam, 1);
        CHECK(!n.taken && n.both && !e.card.camera && e.passes == 3);
    }
    {
        // camera card first, then a sun draw without card data: not stale (another pass)
        CardUv e;
        CHECK(CardNote(e, cam, 1).taken);
        CHECK(!CardNote(e, sun_lost, 1).taken);
        CHECK(!CardStale(e) && e.miss == CardMiss::None && e.card.camera);
    }
    {
        // sun stops: the camera pass keeps drawing; the sun card holds for CardSunFrames
        // frames after its last sun draw, then the next camera card takes over (once)
        CardUv e;
        CHECK(CardNote(e, sun, 1).taken);
        for (std::uint64_t frame = 2; frame <= 1 + CardSunFrames; ++frame) {
            CHECK(!CardSunGone(e, frame));
            const CardNoted n = CardNote(e, cam, frame);
            CHECK(!n.taken && !e.card.camera);
        }
        CHECK(CardSunGone(e, 2 + CardSunFrames));
        CardNoted n = CardNote(e, cam, 2 + CardSunFrames);
        CHECK(n.taken && n.sun_gave_way && n.coordinates && e.card.camera);
        CHECK(!CardSunGone(e, 2 + CardSunFrames)); // a camera card is never "gone"
        n = CardNote(e, cam, 3 + CardSunFrames);
        CHECK(n.taken && !n.sun_gave_way && !n.coordinates); // the same card again: nothing new
        // sun returns: its card is taken back at once, and holds again
        n = CardNote(e, sun, 40);
        CHECK(n.taken && !n.sun_gave_way && n.coordinates && !e.card.camera && e.sun_frame == 40);
        CHECK(!CardNote(e, cam, 41).taken && !e.card.camera);
        // no draw at all for long, then a camera draw: the sun card gives way
        CHECK(CardSunGone(e, 1000));
        CHECK(CardNote(e, cam, 1000).taken && e.card.camera);
    }
    {
        // a sun shadow pass card that stops (no draw of either pass): counted as gone, kept
        CardUv e;
        CHECK(CardNote(e, sun, 5).taken);
        CHECK(!CardSunGone(e, 5 + CardSunFrames) && CardSunGone(e, 6 + CardSunFrames));
        CHECK(!e.card.camera);
    }
    {
        // r14's longest cascade period (16): the sun pass draws the entry every 16th frame, the
        // camera pass every frame. The card stays the sun's: no hand-over back and forth.
        CardUv e;
        int taken_camera = 0;
        for (std::uint64_t frame = 1; frame <= 400; ++frame) {
            if (frame % 16 == 1) {
                CHECK(CardNote(e, sun, frame).taken);
            }
            taken_camera += CardNote(e, cam, frame).taken ? 1 : 0;
            CHECK(!e.card.camera);
        }
        CHECK(taken_camera == 0);
    }
    {
        // a sun shadow pass card lost for good (stale) while the camera's stays valid:
        // the next camera card is taken at once, before CardSunFrames
        CardUv e;
        CHECK(CardNote(e, sun, 1).taken);
        CHECK(!CardNote(e, sun_lost, 2).taken && CardStale(e));
        const CardNoted n = CardNote(e, cam, 2);
        CHECK(n.taken && n.sun_gave_way && e.card.camera && !CardStale(e));
    }
    {
        // a sun draw with card data refreshes the frame whether or not its card is taken
        CardUv e;
        CHECK(CardNote(e, sun, 1).taken);
        CHECK(CardNote(e, sun, 10).taken && e.sun_frame == 10);
        CHECK(!CardNote(e, cam, 27).taken); // 27 = 10 + 17: still given
        CHECK(CardNote(e, cam, 28).taken);
        // a camera draw does not refresh it
        CHECK(e.sun_frame == 10);
    }
}

void TestFreesAndSlots() {
    std::vector<CardFree> frees{{1, 1, 10}, {2, 2, 20}, {3, 3, 30}};
    std::vector<std::uint64_t> released;
    std::size_t n = CardReleaseFrees(
        frees, [](std::uint64_t tick) { return tick <= 20; },
        [&](const CardFree& f) { released.push_back(f.block); });
    CHECK(n == 2 && frees.size() == 1 && frees[0].block == 3);
    CHECK((released == std::vector<std::uint64_t>{1, 2}));
    n = CardReleaseFrees(frees, [](std::uint64_t) { return false; }, [&](const CardFree&) { CHECK(false); });
    CHECK(n == 0 && frees.size() == 1);

    CardSlots slots;
    CHECK(slots.Take() == 1);
    CHECK(slots.Take() == 2);
    CHECK(slots.Take() == 3);
    slots.Give(2);
    slots.Give(0); // none: ignored
    CHECK(slots.Take() == 2);
    CHECK(slots.Take() == 4);
    slots.next = CardSlotsMost - 1;
    CHECK(slots.Take() == CardSlotsMost - 1);
    CHECK(slots.Take() == 0);
    slots.Give(7);
    CHECK(slots.Take() == 7);
}

// The knob off: the engine makes no card data (no CaptureUv pipeline), so a draw's card stays the
// default, and an entry's part the default: nothing is wanted, recorded or due, and a default
// card is never taken.
void TestOffPath() {
    const CardDraw none;
    CHECK(!none.valid && none.miss == CardMiss::None && none.selector == 0);
    CardSelector s;
    CHECK(!UnpackCardSelector(none.selector, s)); // word 7 stays 0: the capture stores nothing
    CardUv e;
    CHECK(e.state == CardUvState::NotCard);
    CHECK(!CardCaptureWanted(e, 0) && !CardCaptureWanted(e, 1));
    CHECK(!CardUvOnlyDue(e, 0));
    CardWaitFrame(e);
    CHECK(e.wait_frames == 0);
    const CardNoted n = CardNote(e, none, 1);
    CHECK(!n.taken && !n.coordinates && !n.other && e.state == CardUvState::NotCard);
    CHECK(!n.both && e.passes == 0); // no reference is kept for a draw without card data
    CardRecorded(e, 5);
    CHECK(e.state == CardUvState::NotCard && e.tick == 0);
    CHECK(!CardSettle(e, true));
}

void TestAxisModes() {
    CHECK(CardAxisMode(0) == CARD_UV_MODE_WRAP);
    CHECK(CardAxisMode(1) == CARD_UV_MODE_MIRROR);
    for (std::uint32_t m = 2; m < 8; ++m) {
        CHECK(CardAxisMode(m) == CARD_UV_MODE_CLAMP);
    }
}

} // namespace

int main() {
    TestKnob();
    TestSizes();
    TestSelector();
    TestAlphaRule();
    TestDitherApart();
    TestGuard();
    TestHalf();
    TestPack();
    TestAlphaFactorBits();
    TestPushAndStats();
    TestStates();
    TestSunOrders();
    TestFreesAndSlots();
    TestAxisModes();
    TestOffPath();
    if (failures != 0) {
        std::printf("rt-card-uv-test: %d failed\n", failures);
        return 1;
    }
    std::printf("rt-card-uv-test: all passed\n");
    return 0;
}
