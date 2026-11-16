// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62_leaf-stage3): tests of the pure parts of the card alpha layers (rt_card_layers.h):
// the sizes, the view knob, which textures a layer takes and through which lane, the layer key,
// the fill's source level and taps, the layer table (given, filled, refilled, dropped, reused,
// full, the hint), the card rows (sun, dither, axis extras), the card test a ray runs (against
// the game's rule on the original coordinates, at a level, mirror once and border), the debug
// view's classes, mip and exclusions, and the CUT1 cache part (version, padding, byte checks).
// Built alone: c++ -std=c++20 -I. tests/test_rt_card_layers.cpp (engine/build.sh --test).

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

#include "gpu/shadps4/video_core/renderer_vulkan/rt_card_layers.h"

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

void TestSizes() {
    CHECK(CardLayerBytes == 65536u + 16384u + 4096u);
    CHECK(CardLayersBytes == 11010048u); // 10.5 MiB
    CHECK(CardLayerBytesAt(512, 3) == 344064u);
    CHECK(CardLayerBytesAt(512, 3) * 128 == 44040192u); // 42 MiB at 512
    CHECK(CardLayerBytesAt(4, 4) == 16u + 4u + 1u + 1u);
    CHECK(CardRowsBytes == 2097152u);
    CHECK(CardLayerInfoBytes == 512u);
    // The view's u32 counters over CardViewLineFrames frames: 4K and 8K fit, 600 frames of 4K not.
    CHECK(CardViewLineFrames == 120);
    CHECK(std::uint64_t(3840) * 2160 * CardViewLineFrames < (std::uint64_t(1) << 32));
    CHECK(std::uint64_t(3840) * 2160 * 600 > 0xffffffffull);
}

void TestViewKnob() {
    CHECK(ReadCardView(nullptr) == 0);
    CHECK(ReadCardView("0") == 0);
    CHECK(ReadCardView("1") == CARD_VIEW_OVERLAY);
    CHECK(ReadCardView("2") == CARD_VIEW_ALPHA);
    CHECK(ReadCardView("3") == CARD_VIEW_UV);
    CHECK(ReadCardView("4") == 0);
    CHECK(ReadCardView("11") == 0);
    CHECK(ReadCardView("") == 0);
    CHECK(!CardViewMisread(nullptr));
    CHECK(!CardViewMisread("0"));
    CHECK(!CardViewMisread("3"));
    CHECK(CardViewMisread("4"));
    CHECK(CardViewMisread(""));
    CHECK(CardViewMisread("on"));
}

void TestSource() {
    CardTexFacts f; // Color2D? not yet: type 0
    std::uint8_t lane = 0;
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::NotTwoD);
    f.type = CardTypeColor2D;
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::None && lane == 3); // BC3, BC7: a in w
    f.dst_select = {7, 7, 7, 7}; // an alpha-only view (BC4-like swizzle): every lane reads it
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::None && lane == 0);
    f.dst_select = {4, 5, 6, 1}; // BC1 without alpha in w: the test reads red
    CHECK(CardSourceCheck(f, 4, lane) == CardLayerMiss::None && lane == 0);
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::NoLane && lane == 0xff);
    CHECK(CardSourceCheck(f, 1, lane) == CardLayerMiss::Constant);
    CHECK(CardSourceCheck(f, 0, lane) == CardLayerMiss::Constant);
    f.dst_select = {4, 5, 6, 7};
    f.num_format = 9; // sRGB: the alpha lane is linear either way
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::None);
    f.num_format = 7;
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::None);
    f.num_format = 1; // Snorm
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::Format);
    f.num_format = 4; // Uint
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::Format);
    f.num_format = 0;
    f.conversion = 1;
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::Conversion);
    f.conversion = 0;
    f.type = CardTypeColor2DMsaa;
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::Multisample);
    f.type = 13; // Color2DArray (a cube reads as one)
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::NotTwoD);
    CHECK(CardViewLane({4, 5, 6, 7}, 8) == 0xff);
    for (std::size_t m = 0; m < std::size_t(CardLayerMiss::Count); ++m) {
        CHECK(std::strcmp(CardLayerMissName(CardLayerMiss(m)), "?") != 0);
    }
}

void TestKey() {
    std::array<std::uint32_t, 8> t{1, 2, 3, 4, 5, 6, 7, 8};
    const std::uint64_t k = CardLayerKey(t, 3);
    CHECK(k != 0);
    CHECK(k == CardLayerKey(t, 3));
    CHECK(k != CardLayerKey(t, 0));
    t[7] ^= 1;
    CHECK(k != CardLayerKey(t, 3));
}

void TestFillLod() {
    const auto taps = [](const CardFillTaps& t, std::uint32_t u, std::uint32_t v) {
        return t.taps_u == u && t.taps_v == v;
    };
    CardFillTaps t = CardFillLod(256, 256, 9, 256); // the same size: one tap at level 0
    CHECK(t.lod == 0.0f && taps(t, 1, 1));
    t = CardFillLod(128, 64, 8, 256); // smaller: one tap
    CHECK(t.lod == 0.0f && taps(t, 1, 1));
    t = CardFillLod(1024, 1024, 11, 256); // ratio 4: level 1, 2 x 2 taps (as before r62 rev. 1)
    CHECK(std::abs(t.lod - 1.0f) < 1e-6f && taps(t, 2, 2));
    t = CardFillLod(1024, 1024, 11, 64);
    CHECK(std::abs(t.lod - 3.0f) < 1e-6f && taps(t, 2, 2));
    t = CardFillLod(512, 512, 10, 256); // ratio 2: level 0, 2 x 2 taps
    CHECK(t.lod == 0.0f && taps(t, 2, 2));
    // Not square: the smaller side sets the level, the larger takes more taps (S7: v of a
    // 2048x512 source is read at its 512 rows' level, not 4 times coarser).
    t = CardFillLod(2048, 512, 12, 256);
    CHECK(t.lod == 0.0f && taps(t, 8, 2));
    t = CardFillLod(2048, 128, 12, 256); // v smaller than the layer: level 0, one tap in v
    CHECK(t.lod == 0.0f && taps(t, 8, 1));
    t = CardFillLod(4096, 1024, 13, 256); // ratio 4 in v: level 1, u covers 8 texels there
    CHECK(std::abs(t.lod - 1.0f) < 1e-6f && taps(t, 8, 2));
    t = CardFillLod(8192, 512, 14, 256); // u would want 16: at most CARD_FILL_MAX_TAPS
    CHECK(t.lod == 0.0f && taps(t, CARD_FILL_MAX_TAPS, 2));
    t = CardFillLod(4096, 4096, 1, 256); // no mips: level 0, the most taps
    CHECK(t.lod == 0.0f && taps(t, CARD_FILL_MAX_TAPS, CARD_FILL_MAX_TAPS));
    t = CardFillLod(700, 300, 10, 256); // not a power of two: 300 / 256 = 1.17, level 0
    CHECK(t.lod == 0.0f && taps(t, 3, 2));
    t = CardFillLod(1400, 600, 11, 256); // 600 / 256 = 2.34: level log2(2.34) - 1 = 0.23, where v
    // covers 2 texels and u 1400 / 600 * 2 = 4.67
    CHECK(std::abs(t.lod - (std::log2(600.0f / 256.0f) - 1.0f)) < 1e-6f && taps(t, 5, 2));
    CHECK(CardFillAxisTaps(0.5f) == 1 && CardFillAxisTaps(1.0f) == 1 && CardFillAxisTaps(2.0f) == 2 &&
          CardFillAxisTaps(2.01f) == 3 && CardFillAxisTaps(100.0f) == CARD_FILL_MAX_TAPS);
}

void TestTable() {
    CardLayerTable table;
    const CardLayerSource a{7, 70, 1};
    CardLayerGet g = table.Get(100, 3, a, 10);
    CHECK(g.layer == 0 && g.given && !g.taken && g.gen == 1);
    CHECK(table.At(0).state == CardLayerState::Wanted && table.Queued() == 1);
    CHECK(table.Info(0) == 1u); // not filled: no READY bit
    // Another draw of the same key and source: same layer, not queued twice.
    g = table.Get(100, 3, a, 10);
    CHECK(g.layer == 0 && !g.given && table.Queued() == 1);
    CHECK(table.NextFill() == 0 && table.NextFill() == CardNoLayer);
    table.Filled(0, a);
    CHECK(table.Info(0) == (1u | CARD_LAYER_READY));
    g = table.Get(100, 3, a, 11);
    CHECK(table.Queued() == 0 && !table.At(0).refill);
    // The image was written (streamed in, replaced): filled again, the old fill stays readable.
    const CardLayerSource a2{7, 70, 2};
    g = table.Get(100, 3, a2, 12);
    CHECK(table.At(0).refill && table.Queued() == 1 && table.Info(0) == (1u | CARD_LAYER_READY));
    CHECK(table.NextFill() == 0);
    // The image went away before the fill: the old fill stays, nothing queued.
    table.FillFailed(0);
    CHECK(table.Info(0) == (1u | CARD_LAYER_READY) && table.Queued() == 0);
    g = table.Get(100, 3, a2, 12); // the next draw asks again
    CHECK(table.Queued() == 1 && table.NextFill() == 0);
    table.Filled(0, a2);
    CHECK(!table.At(0).refill);
    // A source that changed again between the fill's start and its record stays wanted.
    g = table.Get(100, 3, CardLayerSource{7, 70, 3}, 12);
    CHECK(table.NextFill() == 0);
    table.Filled(0, a2);
    CHECK(table.At(0).refill);
    // Fill every layer in frame 20.
    CardLayerTable full;
    for (std::uint32_t k = 0; k < CardLayerCount; ++k) {
        g = full.Get(1000 + k, 3, CardLayerSource{k + 1, k + 1, 0}, 20);
        CHECK(g.layer == k && g.given);
    }
    CHECK(full.Queued() == CardLayerCount);
    for (std::uint32_t k = 0; k < CardLayerCount; ++k) {
        const std::uint32_t i = full.NextFill();
        CHECK(i == k);
        full.Filled(i, full.At(i).source);
    }
    CHECK(full.Count(CardLayerState::Ready) == CardLayerCount);
    // Frame 21: all were used in frame 20 (the last): a new key gets none.
    g = full.Get(5000, 3, CardLayerSource{999, 999, 0}, 21);
    CHECK(g.layer == CardNoLayer);
    // Frame 22: layer 5 used in frame 21, the others last in 20: the least recently used, the
    // first of those, is taken; its generation moves on and it is no longer READY.
    full.Get(1005, 3, CardLayerSource{6, 6, 0}, 21);
    full.Get(1000, 3, CardLayerSource{1, 1, 0}, 21);
    g = full.Get(5000, 3, CardLayerSource{999, 999, 0}, 22);
    CHECK(g.layer == 1 && g.given && g.taken && g.gen == 2);
    CHECK(full.Info(1) == 2u);
    // The old key's row (gen 1) no longer matches the layer.
    CHECK(full.Info(1) != (1u | CARD_LAYER_READY));
    // The old key comes back: another layer, a new generation there.
    g = full.Get(1001, 3, CardLayerSource{2, 2, 0}, 23);
    CHECK(g.given && g.layer != 1 && g.layer != 0 && g.layer != 5);

    // Another image answers a READY key (another uid, or another ImageId): no longer READY, the
    // generation kept, queued for its refill; READY again with the same generation once filled.
    CardLayerTable swap;
    const CardLayerSource s1{3, 30, 5};
    g = swap.Get(77, 3, s1, 10);
    CHECK(swap.NextFill() == g.layer);
    swap.Filled(g.layer, s1);
    const std::uint32_t gen = g.gen;
    CHECK(swap.Info(g.layer) == (gen | CARD_LAYER_READY));
    const CardLayerSource s2{3, 31, 5}; // the same slot, another image (uid)
    g = swap.Get(77, 3, s2, 11);
    CHECK(g.dropped && !g.given && g.gen == gen && swap.Info(g.layer) == gen &&
          swap.At(g.layer).state == CardLayerState::Wanted && swap.Queued() == 1);
    CHECK(swap.NextFill() == g.layer);
    swap.Filled(g.layer, s2);
    CHECK(swap.Info(g.layer) == (gen | CARD_LAYER_READY));
    g = swap.Get(77, 3, CardLayerSource{4, 31, 5}, 12); // another ImageId: dropped too
    CHECK(g.dropped && swap.Info(g.layer) == gen);
    swap.Filled(g.layer, CardLayerSource{4, 31, 5});
    g = swap.Get(77, 3, CardLayerSource{4, 31, 6}, 13); // the same image written: refill, READY
    CHECK(!g.dropped && swap.At(g.layer).refill && swap.Info(g.layer) == (gen | CARD_LAYER_READY));

    // The hint: a known key is found without the scan; a stale hint (its layer went to another
    // key) is not taken; two keys of one hint slot are both found.
    CardLayerTable hinted;
    (void)hinted.TakeHintHits();
    g = hinted.Get(5, 3, CardLayerSource{1, 1, 0}, 2);
    const std::uint32_t first = g.layer;
    CHECK(hinted.TakeHintHits() == 0);
    g = hinted.Get(5, 3, CardLayerSource{1, 1, 0}, 2);
    CHECK(g.layer == first && hinted.TakeHintHits() == 1);
    g = hinted.Get(5 + 256, 3, CardLayerSource{2, 2, 0}, 2); // the same hint slot
    const std::uint32_t second = g.layer;
    CHECK(g.given && second != first && hinted.TakeHintHits() == 0);
    g = hinted.Get(5, 3, CardLayerSource{1, 1, 0}, 2); // the slot holds 5 + 256 now: a scan
    CHECK(g.layer == first && !g.given && hinted.TakeHintHits() == 0);
    g = hinted.Get(5, 3, CardLayerSource{1, 1, 0}, 2);
    CHECK(g.layer == first && hinted.TakeHintHits() == 1);
}

void TestRows() {
    CardRow r;
    r.ready = true;
    r.pool_offset = 4194303;
    r.triangles = 65535 * 64;
    r.layer = 127;
    r.layer_gen = 0x7fffffff;
    r.op = CardOp::NotEqual;
    r.nonzero = true;
    r.dither = true;
    r.sun = true;
    r.mode_u = CARD_UV_MODE_MIRROR;
    r.mode_v = CARD_UV_MODE_CLAMP;
    r.extra_u = CARD_AXIS_MIRROR_ONCE;
    r.extra_v = CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER;
    r.reference = 0.50196f;
    r.offset_u = -3.25f;
    r.offset_v = 1e-7f;
    r.dither_scale = -1.0f;
    const auto w = CardPackRow(r);
    const CardRow b = CardUnpackRow(w);
    CHECK(b.ready && b.pool_offset == r.pool_offset && b.triangles == r.triangles && b.layer == 127 &&
          b.layer_gen == r.layer_gen && b.op == r.op && b.nonzero && b.dither && b.sun &&
          b.mode_u == r.mode_u && b.mode_v == r.mode_v && b.extra_u == r.extra_u &&
          b.extra_v == r.extra_v && b.reference == r.reference &&
          b.offset_u == r.offset_u && b.offset_v == r.offset_v && b.dither_scale == r.dither_scale);
    for (std::uint32_t op = 0; op < 6; ++op) {
        r.op = CardOp(op);
        r.ready = false;
        r.nonzero = false;
        r.sun = false;
        r.extra_u = 0;
        const CardRow c = CardUnpackRow(CardPackRow(r));
        CHECK(c.op == CardOp(op) && !c.ready && !c.nonzero && !c.sun && c.extra_u == 0 &&
              c.extra_v == (CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER));
    }
    // Every flag in its own bits.
    CHECK((CARD_ROW_DITHER & CARD_ROW_SUN) == 0 && (CARD_ROW_SUN >> CARD_ROW_EXTRA_U_SHIFT) == 0 &&
          CARD_ROW_EXTRA_V_SHIFT + 2 <= 31);
    // The raw clamp modes' extras.
    CHECK(CardAxisExtra(0) == 0 && CardAxisExtra(1) == 0 && CardAxisExtra(2) == 0);
    CHECK(CardAxisExtra(3) == CARD_AXIS_MIRROR_ONCE && CardAxisExtra(4) == CARD_AXIS_BORDER);
    CHECK(CardAxisExtra(5) == (CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER));
    CHECK(CardAxisExtra(6) == CARD_AXIS_BORDER);
    CHECK(CardAxisExtra(7) == (CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER));
    // When a row is READY.
    CardUv uv;
    uv.card.valid = true;
    uv.card.layer = 5;
    uv.card.layer_gen = 9;
    uv.card.affine = {2.0f, 3.0f, 0.25f, -0.5f};
    uv.card.camera = true;
    uv.card.clamp_u = 7;
    uv.card.clamp_v = 2;
    uv.state = CardUvState::Ready;
    CardRow e = CardRowFor(uv, 10, 20);
    CHECK(e.ready && e.layer == 4 && e.layer_gen == 9 && e.pool_offset == 10 && e.triangles == 20 &&
          e.offset_u == 0.25f && e.offset_v == -0.5f && !e.sun && !e.dither &&
          e.extra_u == (CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER) && e.extra_v == 0);
    // The dither bit only with a coefficient not 0 (F3); the sun bit for a sun pass card (F1).
    uv.card.dither = true;
    CHECK(!CardRowFor(uv, 10, 20).dither);
    uv.card.dither_scale = -1.0f;
    CHECK(CardRowFor(uv, 10, 20).dither);
    uv.card.dither = false;
    CHECK(!CardRowFor(uv, 10, 20).dither);
    uv.card.dither_scale = 0.0f;
    uv.card.camera = false;
    CHECK(CardRowFor(uv, 10, 20).sun);
    uv.card.camera = true;
    uv.state = CardUvState::Pending;
    CHECK(!CardRowFor(uv, 10, 20).ready);
    uv.state = CardUvState::Ready;
    uv.miss = CardMiss::NoRecord; // stale
    CHECK(!CardRowFor(uv, 10, 20).ready);
    uv.miss = CardMiss::None;
    uv.card.layer = 0; // no layer
    CHECK(!CardRowFor(uv, 10, 20).ready);
}

// A smooth alpha with sharp-enough features: what the layer would hold, sampled exactly.
float Texture(float u, float v) {
    return 0.5f + 0.5f * std::sin(6.2831853f * u * 3.0f) * std::cos(6.2831853f * v * 2.0f);
}

void TestCardTest() {
    std::mt19937 rng(62);
    std::uniform_real_distribution<float> uv01(-2.0f, 3.0f), alpha(0.2f, 1.0f), bary(0.0f, 1.0f);
    const std::array<float, 4> affine{1.5f, 0.75f, 0.3125f, -0.125f}; // scale u, v, offset u, v
    std::uint32_t checked = 0, near_ref = 0, differ = 0;
    for (std::uint32_t mode = 0; mode < 3; ++mode) {
        std::vector<std::array<std::uint32_t, 4>> pool;
        std::vector<std::array<CardCorner, 3>> original;
        for (int t = 0; t < 400; ++t) {
            std::array<CardCorner, 3> c{};
            const float bu = uv01(rng), bv = uv01(rng);
            for (CardCorner& k : c) {
                k = {bu + 0.3f * bary(rng), bv + 0.3f * bary(rng), alpha(rng)};
                k.a = float(CardUnorm8(k.a)) / 255.0f; // on the 8-bit grid: not rounded
            }
            original.push_back(c);
            std::array<CardCorner, 3> scaled{};
            for (std::size_t i = 0; i < 3; ++i) {
                scaled[i] = CardApplyAffine(c[i], CardPoolAffine(affine));
            }
            pool.push_back(CardPackTriangle(scaled, mode, mode, true));
        }
        CardRow r;
        r.ready = true;
        r.pool_offset = 0;
        r.triangles = std::uint32_t(pool.size());
        r.layer = 3;
        r.layer_gen = 77;
        r.op = CardOp::GreaterEqual;
        r.nonzero = true;
        r.mode_u = mode;
        r.mode_v = mode;
        r.reference = 0.392f;
        r.offset_u = affine[2];
        r.offset_v = affine[3];
        const auto row = CardPackRow(r);
        std::uint32_t layer_seen = 0;
        float lod_seen = -1.0f;
        const auto sample = [&](std::uint32_t layer, float u, float v, float lod) {
            layer_seen = layer;
            lod_seen = lod;
            return Texture(u, v);
        };
        for (std::uint32_t p = 0; p < pool.size(); ++p) {
            float b1 = bary(rng), b2 = bary(rng);
            if (b1 + b2 > 1.0f) {
                b1 = 1.0f - b1;
                b2 = 1.0f - b2;
            }
            const float lod = float(p % 3) * 0.5f;
            const CardTestResult got =
                CardTest(row, 77u | CARD_LAYER_READY, pool, p, b1, b2, lod, sample);
            std::uint32_t flags = pool[p][3] >> CARD_UV_FLAGS_SHIFT;
            CHECK((flags & CARD_UV_TRI_NOT_FINITE) == 0);
            CHECK(got.status != CARD_NO_DATA && layer_seen == 3 && lod_seen == lod);
            // The game: the original coordinates, the draw's whole affine, the sampler's repeat.
            const auto& c = original[p];
            const float b0 = 1.0f - b1 - b2;
            const float u = (c[0].u * b0 + c[1].u * b1 + c[2].u * b2) * affine[0] + affine[2];
            const float v = (c[0].v * b0 + c[1].v * b1 + c[2].v * b2) * affine[1] + affine[3];
            const float a = c[0].a * b0 + c[1].a * b1 + c[2].a * b2;
            const float ga = Texture(CardRepeat(u, mode), CardRepeat(v, mode)) * a;
            const bool game = CardKeeps(ga, r.reference, r.op, r.nonzero);
            // The raw coordinates: before the repeat, the offset in (half precision of the
            // shifted pool coordinates: within a whole repeat for wrap, two for mirror).
            if (mode == CARD_UV_MODE_CLAMP) {
                CHECK(std::abs(got.raw_u - u) < 0.01f && std::abs(got.raw_v - v) < 0.01f);
            } else {
                const float period = mode == CARD_UV_MODE_WRAP ? 1.0f : 2.0f;
                const float du = (got.raw_u - u) / period, dv = (got.raw_v - v) / period;
                CHECK(std::abs(du - std::round(du)) < 0.01f && std::abs(dv - std::round(dv)) < 0.01f);
            }
            // Half precision of a shifted coordinate within 4: 2^-11 relative; the texture's
            // slope is at most 3 * 2 * pi * 0.5 + 2 * 2 * pi * 0.5 per unit: about 16.
            const float bound = 16.0f * 0.0025f + 1e-4f;
            ++checked;
            if (std::abs(ga - r.reference) < bound) {
                ++near_ref;
            } else {
                CHECK(game == (got.status == CARD_KEPT));
                differ += game == (got.status == CARD_KEPT) ? 0 : 1;
                CHECK(std::abs(got.alpha - ga) < bound);
            }
        }
        // No data: not ready, another generation, the layer not filled, past the triangles, a
        // record marked not finite.
        CHECK(CardTest(row, 77u, pool, 0, 0.2f, 0.2f, 0.0f, sample).status == CARD_NO_DATA);
        CHECK(CardTest(row, 78u | CARD_LAYER_READY, pool, 0, 0.2f, 0.2f, 0.0f, sample).status == CARD_NO_DATA);
        CHECK(CardTest(row, 77u | CARD_LAYER_READY, pool, r.triangles, 0.2f, 0.2f, 0.0f, sample).status ==
              CARD_NO_DATA);
        CardRow nr = r;
        nr.ready = false;
        CHECK(CardTest(CardPackRow(nr), 77u | CARD_LAYER_READY, pool, 0, 0.2f, 0.2f, 0.0f, sample).status ==
              CARD_NO_DATA);
        auto bad = pool;
        bad[0] = CardPackTriangle({CardCorner{NAN, 0.0f, 1.0f}, CardCorner{}, CardCorner{}}, mode,
                                  mode, true);
        CHECK(CardTest(row, 77u | CARD_LAYER_READY, bad, 0, 0.2f, 0.2f, 0.0f, sample).status == CARD_NO_DATA);
        bad[0] = CardPackTriangle({CardCorner{0.0f, 0.0f, 1.5f}, CardCorner{}, CardCorner{}}, mode,
                                  mode, true); // CARD_UV_TRI_ALPHA_RANGE
        CHECK(CardTest(row, 77u | CARD_LAYER_READY, bad, 0, 0.2f, 0.2f, 0.0f, sample).status == CARD_NO_DATA);
    }
    CHECK(checked == 1200 && differ == 0 && near_ref < checked / 4);
    // A border axis outside [0, 1] is no data; inside it is tested. Mirror once mirrors about 0.
    {
        std::vector<std::array<std::uint32_t, 4>> one{CardPackTriangle(
            {CardCorner{-0.5f, 0.5f, 1.0f}, CardCorner{-0.5f, 0.5f, 1.0f}, CardCorner{-0.5f, 0.5f, 1.0f}},
            CARD_UV_MODE_CLAMP, CARD_UV_MODE_CLAMP, true)};
        CardRow br;
        br.ready = true;
        br.triangles = 1;
        br.layer_gen = 5;
        br.mode_u = CARD_UV_MODE_CLAMP;
        br.mode_v = CARD_UV_MODE_CLAMP;
        br.reference = 0.5f;
        float u_seen = -1.0f;
        const auto flat = [&](std::uint32_t, float u, float, float) {
            u_seen = u;
            return 1.0f;
        };
        CardTestResult t = CardTest(CardPackRow(br), 5u | CARD_LAYER_READY, one, 0, 0.3f, 0.3f, 0.0f, flat);
        CHECK(t.status == CARD_KEPT && u_seen == 0.0f); // clamp to the last texel
        br.extra_u = CARD_AXIS_MIRROR_ONCE;
        t = CardTest(CardPackRow(br), 5u | CARD_LAYER_READY, one, 0, 0.3f, 0.3f, 0.0f, flat);
        CHECK(t.status == CARD_KEPT && std::abs(u_seen - 0.5f) < 1e-3f); // -0.5 mirrored to 0.5
        br.extra_u = CARD_AXIS_BORDER;
        t = CardTest(CardPackRow(br), 5u | CARD_LAYER_READY, one, 0, 0.3f, 0.3f, 0.0f, flat);
        CHECK(t.status == CARD_NO_DATA); // the border colour: not in the row
        br.extra_u = CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER; // mirrored inside: tested
        t = CardTest(CardPackRow(br), 5u | CARD_LAYER_READY, one, 0, 0.3f, 0.3f, 0.0f, flat);
        CHECK(t.status == CARD_KEPT);
        bool border = false;
        CHECK(CardRepeatAxis(1.5f, CARD_UV_MODE_CLAMP, CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER,
                             border) == 1.0f && border);
        border = false;
        CHECK(CardRepeatAxis(1.5f, CARD_UV_MODE_WRAP, CARD_AXIS_BORDER, border) == 0.5f && !border);
        CHECK(CardRepeatAxis(-0.25f, CARD_UV_MODE_CLAMP, CARD_AXIS_MIRROR_ONCE, border) == 0.25f &&
              !border);
        CHECK(CardRepeatAxis(NAN, CARD_UV_MODE_CLAMP, CARD_AXIS_BORDER, border) != 2.0f && border);
    }
    // The repeat of one axis.
    CHECK(CardRepeat(1.25f, CARD_UV_MODE_WRAP) == 0.25f);
    CHECK(CardRepeat(-0.25f, CARD_UV_MODE_WRAP) == 0.75f);
    CHECK(CardRepeat(1.25f, CARD_UV_MODE_MIRROR) == 0.75f);
    CHECK(CardRepeat(-0.25f, CARD_UV_MODE_MIRROR) == 0.25f);
    CHECK(CardRepeat(2.25f, CARD_UV_MODE_MIRROR) == 0.25f);
    CHECK(CardRepeat(1.25f, CARD_UV_MODE_CLAMP) == 1.0f);
    CHECK(CardRepeat(-0.25f, CARD_UV_MODE_CLAMP) == 0.0f);
}

void TestViewClass() {
    CHECK(CardViewClass(true, true, 5.0f, CARD_KEPT, 5.0f) == CARD_VIEW_SKY);
    CHECK(CardViewClass(false, false, 0.0f, CARD_NO_DATA, 5.0f) == CARD_VIEW_NO_CARD);
    // The game's depth at the card: kept by the game.
    CHECK(CardViewClass(false, true, 5.0f, CARD_KEPT, 5.01f) == CARD_VIEW_AGREE_KEPT);
    CHECK(CardViewClass(false, true, 5.0f, CARD_DROPPED, 5.01f) == CARD_VIEW_RAY_DROPPED_GAME_KEPT);
    // Behind it: dropped by the game (the pixel sees through the card).
    CHECK(CardViewClass(false, true, 5.0f, CARD_DROPPED, 7.0f) == CARD_VIEW_AGREE_DROPPED);
    CHECK(CardViewClass(false, true, 5.0f, CARD_KEPT, 7.0f) == CARD_VIEW_RAY_KEPT_GAME_DROPPED);
    // In front of it: something the scene does not hold.
    CHECK(CardViewClass(false, true, 5.0f, CARD_KEPT, 3.0f) == CARD_VIEW_NO_CARD);
    CHECK(CardViewClass(false, true, 5.0f, CARD_NO_DATA, 5.0f) == CARD_VIEW_NO_DATA);
    // The tolerance: 0.5 % + 2 cm (at 10 m: 7 cm).
    CHECK(CardViewClass(false, true, 10.0f, CARD_KEPT, 10.06f) == CARD_VIEW_AGREE_KEPT);
    CHECK(CardViewClass(false, true, 10.0f, CARD_KEPT, 10.09f) == CARD_VIEW_RAY_KEPT_GAME_DROPPED);
    CHECK(CardViewClass(false, true, 10.0f, CARD_KEPT, 9.94f) == CARD_VIEW_AGREE_KEPT);
    CHECK(CardViewClass(false, true, 10.0f, CARD_KEPT, 9.9f) == CARD_VIEW_NO_CARD);

    // The game's mip: a pixel covering 1/256 of the texture is level 0, 1/128 level 1; the
    // larger axis decides; a neighbour on another card is not used; none: 0.
    CHECK(std::abs(CardViewLod(1.0f / 256.0f, 0.0f, true, 0.0f, 0.0f, false)) < 1e-5f);
    CHECK(std::abs(CardViewLod(0.0f, 1.0f / 128.0f, true, 1.0f / 512.0f, 0.0f, true) - 1.0f) < 1e-5f);
    CHECK(std::abs(CardViewLod(1.0f / 1024.0f, 0.0f, true, 0.0f, 1.0f / 32.0f, false) + 2.0f) < 1e-5f);
    CHECK(std::abs(CardViewLod(0.03f, 0.04f, true, 0.0f, 0.0f, true) - std::log2(0.05f * 256.0f)) < 1e-5f);
    CHECK(CardViewLod(0.5f, 0.5f, false, 0.5f, 0.5f, false) == 0.0f);
    CHECK(CardViewLod(0.0f, 0.0f, true, 0.0f, 0.0f, true) == 0.0f);
    CHECK(CardViewLod(-1.0f / 64.0f, 0.0f, true, 0.0f, 0.0f, false) == 2.0f);
    // What is not judged: a sun pass card first, then a dithered one, then a coarse mip.
    CHECK(CardViewExcluded(0u, 0.0f) == 0u && CardViewExcluded(0u, 2.0f) == 0u);
    CHECK(CardViewExcluded(0u, 2.01f) == CARD_VIEW_COARSE);
    CHECK(CardViewExcluded(CARD_ROW_DITHER, 0.0f) == CARD_VIEW_DITHERED);
    CHECK(CardViewExcluded(CARD_ROW_SUN | CARD_ROW_DITHER, 5.0f) == CARD_VIEW_SUN_CARD);
    CHECK(CardViewExcluded(CARD_ROW_READY | 0x3ffu, 1.0f) == 0u);
    // A judged class of an excluded card counts as its reason; other classes as themselves.
    for (std::uint32_t c = CARD_VIEW_AGREE_KEPT; c <= CARD_VIEW_RAY_DROPPED_GAME_KEPT; ++c) {
        CHECK(CardViewCounter(c, 0) == c && CardViewCounter(c, CARD_VIEW_SUN_CARD) == CARD_VIEW_SUN_CARD);
    }
    for (const std::uint32_t c : {std::uint32_t(CARD_VIEW_NO_DATA), std::uint32_t(CARD_VIEW_NO_CARD),
                                  std::uint32_t(CARD_VIEW_SKY)}) {
        CHECK(CardViewCounter(c, CARD_VIEW_COARSE) == c);
    }
    CHECK(CARD_VIEW_CLEAR + 1 == CARD_VIEW_COUNTERS && CARD_VIEW_COARSE + 1 == CARD_VIEW_CLEAR &&
          CARD_VIEW_SUN_CARD < CARD_VIEW_COUNTERS); // (r62b) CLEAR added
}

// bbport (r62b_leaf-stage3-followups): a rule that keeps no alpha in [0, 1] (a reference above 1,
// never clamped), the row bits CLEAR and SUN_SOLID, a clear row's test (dropped without a sample
// or a layer; a bad record is still no data) and the view's CLEAR class.
void TestClear() {
    // The judge's hair material: cb[20] 0.588235, cb[21] 1, the sun pass's >=: reference 1.088.
    const float hair = 0.588235f + 0.5f * 1.0f;
    CHECK(CardRuleClear(CardOp::GreaterEqual, hair, true, false, 0.0f));
    CHECK(CardRuleClear(CardOp::GreaterEqual, 1.0f + 1.0f / 255.0f, false, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::GreaterEqual, 1.0f, false, false, 0.0f)); // alpha 1 passes
    CHECK(CardRuleClear(CardOp::Greater, 1.0f, false, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::Greater, 0.999f, false, false, 0.0f));
    // Its camera pass card dithers (coefficient -cb[21]): thresholds 0.088 to 1.088, not clear.
    CHECK(!CardRuleClear(CardOp::GreaterEqual, hair, true, true, -1.0f));
    CHECK(CardRuleClear(CardOp::GreaterEqual, hair, true, false, -1.0f)); // no dither: k unused
    CHECK(CardRuleClear(CardOp::GreaterEqual, 2.5f, true, true, -1.0f));  // 1.5 to 2.5
    CHECK(CardRuleClear(CardOp::Less, 0.0f, false, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::Less, 0.01f, false, false, 0.0f));
    CHECK(CardRuleClear(CardOp::LessEqual, -0.01f, false, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::LessEqual, 0.0f, false, false, 0.0f)); // alpha 0 passes
    CHECK(CardRuleClear(CardOp::LessEqual, 0.0f, true, false, 0.0f));   // but not alpha != 0
    CHECK(CardRuleClear(CardOp::Equal, 1.5f, false, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::Equal, 0.5f, false, false, 0.0f));
    CHECK(CardRuleClear(CardOp::Equal, 0.0f, true, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::NotEqual, 5.0f, false, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::GreaterEqual, INFINITY, false, false, 0.0f)); // not a valid card
    CHECK(!CardRuleClear(CardOp::GreaterEqual, NAN, false, false, 0.0f));
    // Against CardKeeps over alpha k / 255 and dither d / 16 (both ends included): the same for
    // the ordered ops (their extremes are on the grid), never clear where the grid keeps one.
    const float refs[] = {-0.5f, -0.004f, 0.0f, 0.004f, 0.3f, 0.996f, 1.0f, 1.004f, hair, 2.0f};
    const float coefficients[] = {0.0f, -1.0f, 1.0f, -0.05f};
    std::uint32_t disagree = 0, unsound = 0, cases = 0;
    for (std::uint32_t op = 0; op < 6; ++op) {
        for (const float ref : refs) {
            for (const float k : coefficients) {
                for (const bool nonzero : {false, true}) {
                    const bool dither = k != 0.0f;
                    bool any = false;
                    for (int ai = 0; ai <= 255 && !any; ++ai) {
                        for (int di = 0; di <= 16 && !any; ++di) {
                            const float t = ref + (dither ? k * float(di) / 16.0f : 0.0f);
                            any = CardKeeps(float(ai) / 255.0f, t, CardOp(op), nonzero);
                        }
                    }
                    const bool clear = CardRuleClear(CardOp(op), ref, nonzero, dither, k);
                    unsound += clear && any ? 1 : 0;
                    disagree += op <= std::uint32_t(CardOp::GreaterEqual) && clear == any ? 1 : 0;
                    ++cases;
                }
            }
        }
    }
    CHECK(cases == 480 && unsound == 0 && disagree == 0);

    // The row: CLEAR is READY without a layer; the reference is kept as read; SUN_SOLID apart.
    CardUv uv;
    uv.card.valid = true;
    uv.card.op = CardOp::GreaterEqual;
    uv.card.nonzero = true;
    uv.card.reference = hair;
    uv.card.camera = false;
    uv.card.layer = 0; // no layer
    uv.state = CardUvState::Ready;
    const CardRow r = CardRowFor(uv, 3, 2);
    CHECK(r.clear && r.ready && r.sun && !r.sun_solid && r.reference == hair);
    const CardRow back = CardUnpackRow(CardPackRow(CardRowFor(uv, 3, 2, true)));
    CHECK(back.clear && back.sun_solid && back.ready && back.sun && back.reference == hair);
    uv.state = CardUvState::Pending;
    CHECK(!CardRowFor(uv, 3, 2).ready); // the records first, clear or not
    uv.state = CardUvState::Ready;
    uv.card.reference = 0.5f;
    CHECK(!CardRowFor(uv, 3, 2).clear && !CardRowFor(uv, 3, 2).ready); // a layer is needed
    uv.card.reference = hair;
    uv.card.camera = true;
    uv.card.dither = true;
    uv.card.dither_scale = -1.0f;
    CHECK(!CardRowFor(uv, 3, 2).clear && CardRowFor(uv, 3, 2).dither); // 0.088 to 1.088
    uv.card.valid = false;
    uv.card.dither = false;
    CHECK(!CardRowFor(uv, 3, 2).clear);
    const std::uint32_t others = CARD_ROW_LAYER_MASK | (7u << CARD_ROW_OP_SHIFT) | CARD_ROW_NONZERO |
                                 (15u << CARD_ROW_MODE_U_SHIFT) | CARD_ROW_DITHER | CARD_ROW_SUN |
                                 (15u << CARD_ROW_EXTRA_U_SHIFT) | CARD_ROW_READY;
    CHECK((CARD_ROW_CLEAR & CARD_ROW_SUN_SOLID) == 0 &&
          ((CARD_ROW_CLEAR | CARD_ROW_SUN_SOLID) & others) == 0);

    // The test: dropped without a sample, whatever the layer info says; no data stays no data.
    std::vector<std::array<std::uint32_t, 4>> one{CardPackTriangle(
        {CardCorner{0.2f, 0.2f, 1.0f}, CardCorner{0.8f, 0.2f, 1.0f}, CardCorner{0.5f, 0.8f, 1.0f}},
        CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true)};
    CardRow cr;
    cr.ready = true;
    cr.clear = true;
    cr.triangles = 1;
    cr.layer = 7;
    cr.layer_gen = 3;
    cr.op = CardOp::GreaterEqual;
    cr.reference = hair;
    bool sampled = false;
    const auto opaque = [&](std::uint32_t, float, float, float) {
        sampled = true;
        return 1.0f;
    };
    CardTestResult t = CardTest(CardPackRow(cr), 0u, one, 0, 0.3f, 0.3f, 0.0f, opaque);
    CHECK(t.status == CARD_DROPPED && !sampled && t.alpha == 0.0f);
    CHECK(std::abs(t.raw_u - (0.2f * 0.4f + 0.8f * 0.3f + 0.5f * 0.3f)) < 1e-3f); // for the mip
    // Without the bit the same rule drops an opaque texel too, by the test (reference as read).
    cr.clear = false;
    t = CardTest(CardPackRow(cr), 3u | CARD_LAYER_READY, one, 0, 0.3f, 0.3f, 0.0f, opaque);
    CHECK(t.status == CARD_DROPPED && sampled && t.alpha > 0.999f);
    cr.clear = true;
    auto bad = one;
    bad[0] = CardPackTriangle({CardCorner{0.0f, 0.0f, 1.5f}, CardCorner{}, CardCorner{}},
                              CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true); // ALPHA_RANGE
    CHECK(CardTest(CardPackRow(cr), 0u, bad, 0, 0.3f, 0.3f, 0.0f, opaque).status == CARD_NO_DATA);
    CHECK(CardTest(CardPackRow(cr), 0u, one, 1, 0.3f, 0.3f, 0.0f, opaque).status == CARD_NO_DATA);
    cr.ready = false;
    CHECK(CardTest(CardPackRow(cr), 0u, one, 0, 0.3f, 0.3f, 0.0f, opaque).status == CARD_NO_DATA);
    // A border axis outside [0, 1]: still dropped (the border colour's alpha is at most 1).
    cr.ready = true;
    cr.mode_u = CARD_UV_MODE_CLAMP;
    cr.extra_u = CARD_AXIS_BORDER;
    cr.offset_u = -2.0f;
    sampled = false;
    t = CardTest(CardPackRow(cr), 0u, one, 0, 0.3f, 0.3f, 0.0f, opaque);
    CHECK(t.status == CARD_DROPPED && !sampled);

    // The view: CLEAR before every other reason, counted for the judged classes only.
    CHECK(CardViewExcluded(CARD_ROW_CLEAR | CARD_ROW_SUN | CARD_ROW_DITHER, 5.0f) == CARD_VIEW_CLEAR);
    CHECK(CardViewExcluded(CARD_ROW_SUN_SOLID, 0.0f) == 0u);
    CHECK(CardViewCounter(CARD_VIEW_RAY_DROPPED_GAME_KEPT, CARD_VIEW_CLEAR) == CARD_VIEW_CLEAR);
    CHECK(CardViewCounter(CARD_VIEW_AGREE_DROPPED, CARD_VIEW_CLEAR) == CARD_VIEW_CLEAR);
    CHECK(CardViewCounter(CARD_VIEW_NO_DATA, CARD_VIEW_CLEAR) == CARD_VIEW_NO_DATA);
}

struct MockCutout {
    std::uint8_t verdict = 1;
    bool flag = true;
    std::uint16_t dword = 0xbeef;
    float ref = 0.392f;
    std::array<float, 2> scale{1.5f, -2.0f};
    std::uint32_t mask = 0x12345678u;
};

// A stand-in for Info::Cutout with the members and enums CardCutoutBytesValid reads, and
// padding (after `layer`).
struct ValidCutout {
    enum class Verdict : std::uint8_t { NotAnalysed, Matched, Other };
    enum class Detail : std::uint8_t { None, Clamped, Count };
    enum class Op : std::uint8_t { Less, NotEqual };
    enum class Ref : std::uint8_t { Immediate, ConstBuffer };
    enum class Layer : std::uint8_t { None, Other };
    Verdict verdict{};
    Detail detail{};
    Op op{};
    Ref ref_kind{};
    Ref ref2_kind{};
    Ref uv_kind{};
    Ref dither_kind{};
    Layer layer{};
    bool uv_by_constant{};
    bool uv_unrecorded{};
    bool texel_offset{};
    bool dither{};
    bool nonzero{};
    float ref = 0.5f;
};
static_assert(sizeof(ValidCutout) == 20 && offsetof(ValidCutout, ref) == 16);

void TestCutoutValid() {
    ValidCutout c;
    c.verdict = ValidCutout::Verdict::Other;
    c.detail = ValidCutout::Detail::Clamped;
    c.op = ValidCutout::Op::NotEqual;
    c.ref_kind = c.ref2_kind = c.uv_kind = c.dither_kind = ValidCutout::Ref::ConstBuffer;
    c.layer = ValidCutout::Layer::Other;
    c.uv_by_constant = c.uv_unrecorded = c.texel_offset = c.dither = c.nonzero = true;
    std::array<std::uint8_t, sizeof(ValidCutout)> b{};
    std::memcpy(b.data(), &c, sizeof(c));
    CHECK(CardCutoutBytesValid<ValidCutout>(b.data()));
    // Each enum one past its last value, each bool 2: refused.
    const std::size_t enums[] = {offsetof(ValidCutout, verdict), offsetof(ValidCutout, op),
                                 offsetof(ValidCutout, ref_kind), offsetof(ValidCutout, ref2_kind),
                                 offsetof(ValidCutout, uv_kind), offsetof(ValidCutout, dither_kind),
                                 offsetof(ValidCutout, layer)};
    for (const std::size_t at : enums) {
        auto bad = b;
        ++bad[at];
        CHECK(!CardCutoutBytesValid<ValidCutout>(bad.data()));
    }
    auto bad = b;
    bad[offsetof(ValidCutout, detail)] = std::uint8_t(ValidCutout::Detail::Count); // Count itself
    CHECK(!CardCutoutBytesValid<ValidCutout>(bad.data()));
    const std::size_t bools[] = {offsetof(ValidCutout, uv_by_constant), offsetof(ValidCutout, uv_unrecorded),
                                 offsetof(ValidCutout, texel_offset), offsetof(ValidCutout, dither),
                                 offsetof(ValidCutout, nonzero)};
    for (const std::size_t at : bools) {
        auto two = b;
        two[at] = 2;
        CHECK(!CardCutoutBytesValid<ValidCutout>(two.data()));
    }
    // The other bytes are not looked at (the float, the padding).
    auto other = b;
    other[offsetof(ValidCutout, ref)] = 0xff;
    other[offsetof(ValidCutout, nonzero) + 1] = 0xff;
    CHECK(CardCutoutBytesValid<ValidCutout>(other.data()));
}

void TestCutoutPart() {
    MockCutout m;
    const std::uint32_t version = CardCutoutVersion(7);
    CHECK(version == ((CardCutoutFormat << 16) | 7u) && CardCutoutVersion(8) != version);
    std::vector<std::uint8_t> bytes(CardCutoutBytes<MockCutout> + 4, 0xcd);
    CardCutoutEncode(m, version, {}, bytes.data());
    std::uint32_t tag = 0;
    std::memcpy(&tag, bytes.data(), 4);
    CHECK(tag == CardCutoutTag && std::memcmp(bytes.data(), "CUT1", 4) == 0);
    const std::uint8_t* payload = nullptr;
    std::size_t used = CardCutoutPart<MockCutout>(bytes.data(), bytes.size(), version, payload);
    CHECK(used == CardCutoutBytes<MockCutout> && payload == bytes.data() + CardCutoutHeader);
    MockCutout back{};
    back.verdict = 0;
    back.flag = false;
    std::memcpy(&back, payload, sizeof(back));
    CHECK(back.verdict == 1 && back.flag && back.dword == 0xbeef && back.ref == 0.392f &&
          back.scale[1] == -2.0f && back.mask == 0x12345678u);
    // Another version (another analysis, or another format): skipped whole, nothing taken.
    used = CardCutoutPart<MockCutout>(bytes.data(), bytes.size(), CardCutoutVersion(8), payload);
    CHECK(used == CardCutoutBytes<MockCutout> && payload == nullptr);
    std::vector<std::uint8_t> other = bytes;
    // Another size (the struct changed without a new version): skipped by its own size.
    const std::uint32_t size2 = sizeof(MockCutout) - 4;
    std::memcpy(other.data() + 8, &size2, 4);
    used = CardCutoutPart<MockCutout>(other.data(), other.size(), version, payload);
    CHECK(used == CardCutoutHeader + size2 && payload == nullptr);
    // Cut short: broken.
    CHECK(CardCutoutPart<MockCutout>(bytes.data(), CardCutoutBytes<MockCutout> - 1, version, payload) == 0);
    CHECK(CardCutoutPart<MockCutout>(bytes.data(), 8, version, payload) == 0);
    // Not this tag.
    std::vector<std::uint8_t> fry = bytes;
    std::memcpy(fry.data(), "FRY1", 4);
    CHECK(CardCutoutPart<MockCutout>(fry.data(), fry.size(), version, payload) == 0);
    // Padding: whatever the struct's padding bytes hold, the part has 0 there; the values stay.
    ValidCutout v;
    std::memset(static_cast<void*>(&v), 0xcd, sizeof(v));
    v.verdict = ValidCutout::Verdict::Matched;
    v.nonzero = true;
    v.ref = 0.25f;
    const std::size_t pad[] = {offsetof(ValidCutout, nonzero) + 1, offsetof(ValidCutout, nonzero) + 2,
                               offsetof(ValidCutout, nonzero) + 3, 999};
    std::array<std::uint8_t, CardCutoutBytes<ValidCutout>> part{};
    CardCutoutEncode(v, version, pad, part.data());
    const std::uint8_t* body = part.data() + CardCutoutHeader;
    CHECK(body[pad[0]] == 0 && body[pad[1]] == 0 && body[pad[2]] == 0);
    ValidCutout back_v;
    std::memcpy(static_cast<void*>(&back_v), body, sizeof(back_v));
    CHECK(back_v.verdict == ValidCutout::Verdict::Matched && back_v.nonzero && back_v.ref == 0.25f);
    // Two encodes of equal values with other padding bytes are equal byte for byte.
    ValidCutout w = v;
    std::memset(reinterpret_cast<std::uint8_t*>(&w) + pad[0], 0x11, 3);
    std::array<std::uint8_t, CardCutoutBytes<ValidCutout>> part2{};
    CardCutoutEncode(w, version, pad, part2.data());
    CHECK(part == part2);
}

// bbport (r63_leaf-stage4): the lamp rays' parts: the mask hold, the cap, the footprint's level
// and the candidate loop (CardRayRun, the CPU form of rt_cards.glsl's cardTraceShadow).
void TestCardLamps() {
    static_assert(CARD_LAMP_MASK == 8u && (CARD_LAMP_MASK & (1u | 2u | 4u)) == 0u);
    static_assert(CARD_LAMP_HOW + CARD_RAY_CAP < CARD_LAMP_COUNTERS && CARD_LAMP_MOST < CARD_LAMP_HOW);
    static_assert(CARD_LAMP_BLIND > CARD_LAMP_HOW + CARD_RAY_CAP && CARD_LAMP_BLIND < CARD_LAMP_COUNTERS);
    static_assert(CARD_RAY_CAP_MOST <= 63u && CARD_RAY_CAP_DEFAULT <= CARD_RAY_CAP_MOST);
    // The hold: on at once with data, kept for CardLampHoldFrames without, then off; never on
    // without having had data.
    CHECK(CardLampHold(false, true, 10, 10, 120));
    CHECK(!CardLampHold(false, false, 10, 0, 120));
    CHECK(CardLampHold(true, false, 130, 10, 120));
    CHECK(!CardLampHold(true, false, 131, 10, 120));
    CHECK(!CardLampHold(true, false, 5, 10, 120)); // a frame before the last one with data
    CHECK(CardLampHoldFrames == 120);
    // The cap: 0 the default, at most 63.
    CHECK(CardRayCap(0) == 16u && CardRayCap(5) == 5u && CardRayCap(63) == 63u && CardRayCap(100) == 63u);
    CHECK(CardRayCapBits(0) == 0u && CardRayCapBits(9) == 9u && CardRayCapBits(1000) == 63u);
    // The texels a metre: unset 1, else 16..4096 over 256.
    static_assert(CardRayTexelScale(0) == 1.0f && CardRayTexelScale(256) == 1.0f);
    static_assert(CardRayTexelScale(512) == 2.0f && CardRayTexelScale(128) == 0.5f);
    static_assert(CardRayTexelScale(1) == 0.0625f && CardRayTexelScale(100000) == 16.0f);
    CHECK(std::fabs(CardRayLod(0.0078125f * CardRayTexelScale(512), 0.0f, 0.0f) - 2.0f) < 1e-5f);
    // The level: a 4 mm footprint (about one texel) reads level 0, 8 mm level 1, 2 cm or more
    // the last level; at the lamp (the footprint narrowed to 0) level 0; not a number: 0.
    CHECK(CardRayLod(0.002f, 0.0f, 0.0f) == 0.0f);
    CHECK(std::fabs(CardRayLod(0.0078125f, 0.0f, 0.0f) - 1.0f) < 1e-5f);
    CHECK(CardRayLod(0.02f, 0.0f, 0.0f) == 2.0f);
    CHECK(CardRayLod(0.1f, -0.01f, 10.0f) == 0.0f);
    CHECK(std::fabs(CardRayLod(0.0156250f, -0.0078125f, 1.0f) - 1.0f) < 1e-5f); // halfway to the lamp
    CHECK(CardRayLod(std::nanf(""), 0.0f, 0.0f) == 0.0f);
    CHECK(CardRayLod(-1.0f, 0.0f, 0.0f) == 0.0f);
    // The loop.
    const auto run = [](std::initializer_list<std::uint32_t> e, std::uint32_t cap) {
        return CardRayRun(std::span<const std::uint32_t>(e.begin(), e.size()), cap);
    };
    const std::uint32_t N = CARD_NO_DATA, K = CARD_KEPT, D = CARD_DROPPED, O = CardRayOpaque;
    CardRayResult r = run({}, 16);
    CHECK(r.how == CARD_RAY_FREE && r.seen == 0u); // no card: the opaque ray's answer
    r = run({O}, 16);
    CHECK(r.how == CARD_RAY_OPAQUE && r.seen == 0u);
    r = run({D, D}, 16);
    CHECK(r.how == CARD_RAY_FREE && r.seen == 2u && r.tested == 2u);
    r = run({D, K, D}, 16);
    CHECK(r.how == CARD_RAY_KEPT && r.seen == 2u && r.tested == 2u);
    r = run({D, O}, 16);
    CHECK(r.how == CARD_RAY_OPAQUE && r.tested == 1u);
    r = run({N, N, N, N, N, K}, 16); // no data is passed and does not count to the cap
    CHECK(r.how == CARD_RAY_KEPT && r.no_data == 5u && r.tested == 1u);
    std::vector<std::uint32_t> many(16, D);
    r = CardRayRun(many, 16);
    CHECK(r.how == CARD_RAY_FREE && r.tested == 16u); // the cap itself is still tested
    many.push_back(D);
    r = CardRayRun(many, 16);
    CHECK(r.how == CARD_RAY_CAP && r.tested == 16u && r.seen == 17u); // the 17th blocks, untested
    many.back() = N;
    r = CardRayRun(many, 16);
    CHECK(r.how == CARD_RAY_CAP && r.tested == 16u); // whatever it is
    std::vector<std::uint32_t> blind(64, N);
    r = CardRayRun(blind, 16);
    CHECK(r.how == CARD_RAY_FREE && r.no_data == 64u);
    blind.push_back(N);
    r = CardRayRun(blind, 16);
    CHECK(r.how == CARD_RAY_CAP && r.seen == 65u); // the guard: 4 times the cap of any kind
    r = run({D, D}, 1);
    CHECK(r.how == CARD_RAY_CAP && r.tested == 1u);
    r = run({K}, 1);
    CHECK(r.how == CARD_RAY_KEPT);
    // A card whose rule keeps nothing (a reference above 1, CARD_ROW_CLEAR) gives DROPPED (TestClear):
    // the ray passes it.
    r = run({D, D, D}, CardRayCap(0));
    CHECK(r.how == CARD_RAY_FREE);
}

} // namespace

int main() {
    TestSizes();
    TestViewKnob();
    TestSource();
    TestKey();
    TestFillLod();
    TestTable();
    TestRows();
    TestCardTest();
    TestViewClass();
    TestClear(); // (r62b)
    TestCutoutValid();
    TestCutoutPart();
    TestCardLamps(); // (r63)
    if (failures != 0) {
        std::printf("rt-card-layers-test: %d failed\n", failures);
        return 1;
    }
    std::printf("rt-card-layers-test: all passed\n");
    return 0;
}
