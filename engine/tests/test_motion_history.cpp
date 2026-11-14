// SPDX-License-Identifier: GPL-2.0-or-later
#include <array>
#include <cassert>
#include <cstdio>
#include "gpu/shadps4/video_core/renderer_vulkan/motion_history.h"

using namespace Vulkan::Motion;

int main() {
    const std::array<uint16_t, 5> indices{1000, 1007, 1002, 1007, UINT16_MAX};
    const auto range = IndexedRange(std::span(indices), -900, true);
    assert(range.first == 100 && range.count == 8);
    assert(IndexedRange(std::span(indices), -1001, true).count == 0);
    assert(IndexedRange(std::span(indices), 0, false).count == 64536);
    const std::array<uint32_t, 3> large{100000, 100003, UINT32_MAX};
    assert(IndexedRange(std::span(large), 7, true).count == 4);
    assert(IndexedRange(std::span(large), INT32_MAX, true).count == 0);
    const std::array<uint16_t, 1> restart{UINT16_MAX};
    assert(IndexedRange(std::span(restart), 0, true).count == 0);
    assert(IndexedRange(std::span<const uint16_t>{}, 0, false).count == 0);

    Draw draw{.shader = 1, .geometry = 2, .indices = 3, .topology = 4,
              .index_count = 5, .instances = 2, .first_instance = 100,
              .vertices = range};
    History history(32);
    history.NextFrame();
    const auto first = history.Prepare(draw);
    const auto duplicate = history.Prepare(draw);
    assert(first.store && !first.load && first.first_vertex == 100);
    assert(first.first_instance == 100 && first.instances == 2);
    assert(duplicate.store == first.store + 16);
    assert(history.Used() == 32);
    assert(!history.Prepare(draw).store && history.stats.exhausted == 1);
    history.NextFrame();
    const auto next = history.Prepare(draw);
    assert(next.load == first.store && next.store != first.store);
    assert(history.Prepare(draw).load == duplicate.store);
    history.NextFrame();
    history.NextFrame();
    assert(!history.Prepare(draw).load);

    history.NextFrame();
    auto changed = draw;
    changed.topology++;
    assert(!history.Prepare(changed).load);
    changed = draw;
    changed.first_instance++;
    assert(!history.Prepare(changed).load);
    history.NextFrame();
    changed = draw;
    changed.vertices.first++;
    assert(!history.Prepare(changed).load);

    History overflow(32);
    draw.vertices.first = 0;
    draw.vertices.count = INT32_MAX;
    draw.instances = UINT32_MAX;
    draw.first_instance = 0;
    assert(!overflow.Prepare(draw).store);
    assert(overflow.stats.exhausted == 1);
    draw.first_instance = 10;
    assert(!overflow.Prepare(draw).store && overflow.stats.invalid == 1);
    draw.first_instance = 0;
    draw.vertices.first = INT32_MAX;
    draw.vertices.count = 2;
    assert(!overflow.Prepare(draw).store && overflow.stats.invalid == 2);

    History gated(1024);
    const History::GateKey weapon{.shader = 7, .index_count = 3, .instances = 1};
    const auto frame = [&](uint64_t palette) {
        gated.NextFrame();
        return gated.Moving(weapon, palette);
    };
    assert(!gated.Moving(weapon, 1) && gated.stats.still == 1);
    assert(!frame(1));
    assert(frame(2) && frame(3));
    assert(!frame(3));
    gated.NextFrame();
    gated.NextFrame();
    assert(!gated.Moving(weapon, 4));
    assert(!gated.Moving(weapon, 5));

    History held(1024);
    held.SetHold(2);
    const auto step = [&](uint64_t palette) {
        held.NextFrame();
        return held.Moving(weapon, palette);
    };
    assert(!held.Moving(weapon, 1));
    assert(step(2));
    assert(step(2) && held.stats.held == 1);
    assert(step(3));
    assert(step(3) && step(3));
    assert(!step(3) && held.stats.held == 3);
    held.NextFrame();
    held.NextFrame();
    assert(!held.Moving(weapon, 4));
    assert(ClassifyBuffer(864) == BufferRole::Other && ClassifyBuffer(416) == BufferRole::Other);
    assert(ClassifyBuffer(96) == BufferRole::SmallSkeleton &&
           ClassifyBuffer(384) == BufferRole::SmallSkeleton);
    assert(ClassifyBuffer(656) == BufferRole::Skeleton && ClassifyBuffer(64) == BufferRole::Other);

    IndexRangeCache ranges;
    uint32_t scans = 0;
    const IndexRangeCache::Key mesh{.address = 0x1000, .count = 3, .index_size = 2};
    const auto scan = [&] {
        ++scans;
        return IndexRangeCache::Result{{4, 3}, 99};
    };
    assert(ranges.Get(mesh, 0, scan).topology == 99 && scans == 1);
    assert(ranges.Get(mesh, IndexRangeCache::Revalidate - 1, scan).range == (VertexRange{4, 3}));
    assert(scans == 1);
    ranges.Get(mesh, IndexRangeCache::Revalidate, scan);
    assert(scans == 2);
    ranges.Trim(IndexRangeCache::Revalidate + IndexRangeCache::Unused + 1);
    assert(ranges.Size() == 0);
    // bbport (r29_bursts): stagger off is phase 0 (rescanned on the frames where frame %
    // Revalidate == 0, wherever first scanned); switched off at run time, entries a staggered
    // run spread are all rescanned on the next such frame (the burst the A/B bit brings back);
    // stagger on is never trusted Revalidate frames after the last scan, and an entry used every
    // frame is rescanned exactly Revalidate frames apart after its first rescan, which comes
    // 1..Revalidate frames after its first scan.
    {
        constexpr uint64_t Every = IndexRangeCache::Revalidate;
        IndexRangeCache phase0;
        scans = 0;
        phase0.Get(mesh, 5, scan);
        phase0.Get(mesh, Every - 1, scan);
        assert(scans == 1);
        phase0.Get(mesh, Every, scan);
        assert(scans == 2);
        const IndexRangeCache::Key other{.address = 0x7654320000, .count = 6, .index_size = 4};
        IndexRangeCache switched;
        switched.stagger = true;
        for (uint64_t f = 0; f < 4 * Every; ++f) {
            switched.Get(mesh, f, scan);
            switched.Get(other, f, scan);
        }
        switched.stagger = false; // experiment 4503599627370496 set at run time
        const uint32_t before_switch = scans;
        switched.Get(mesh, 4 * Every, scan);
        switched.Get(other, 4 * Every, scan);
        assert(scans == before_switch + 2);
        for (uint64_t f = 4 * Every + 1; f < 5 * Every; ++f) {
            switched.Get(mesh, f, scan);
            switched.Get(other, f, scan);
        }
        assert(scans == before_switch + 2);
        IndexRangeCache staggered;
        staggered.stagger = true;
        scans = 0;
        uint64_t scanned_at = 0;
        for (uint64_t f = 7; f < 7 + 8 * Every; ++f) {
            const uint32_t before = scans;
            staggered.Get(mesh, f, scan);
            if (scans != before) {
                assert(scans == 1 || (scans == 2 && f - scanned_at >= 1 && f - scanned_at <= Every) ||
                       (scans > 2 && f - scanned_at == Every));
                scanned_at = f;
            }
            assert(f - scanned_at < Every);
        }
        assert(scans >= 8);
    }

    // bbport (r34_motion-store): used vertices of a range; room by class (first from the
    // bottom, second from the top above last frame's first-class demand); first come without
    // `priority` (the places of before); sparse draws second; held draws reported as held.
    {
        std::vector<uint64_t> bits;
        const std::array<uint16_t, 6> lod{10, 50, 10, 99, UINT16_MAX, 50};
        const auto lod_range = IndexedRange(std::span(lod), 5, true);
        assert(lod_range.first == 15 && lod_range.count == 90);
        assert(UsedVertices(std::span(lod), 5, true, lod_range, 1024, bits) == 3);
        const auto no_restart = IndexedRange(std::span(lod), 5, false);
        assert(no_restart.count == 65526);
        assert(UsedVertices(std::span(lod), 5, false, no_restart, 1u << 20, bits) == 4);
        assert(UsedVertices(std::span(lod), 5, true, lod_range, 89, bits) == 0);
        assert(UsedVertices(std::span(lod), 5, true, VertexRange{}, 1024, bits) == 0);
        const std::array<uint32_t, 4> wide{7, 70000, 7, 3};
        const auto wide_range = IndexedRange(std::span(wide), 0, false);
        assert(UsedVertices(std::span(wide), 0, false, wide_range, 1u << 20, bits) == 3);

        const History::Sort skinned{Kind::Skinned, 10}, held_sort{Kind::Held, 20};
        const History::Sort sparse{Kind::Skinned, 3}, moved{Kind::Moved, 0};
        assert(History::FirstClass(skinned, 10) && History::FirstClass(moved, 10));
        assert(!History::FirstClass(held_sort, 20) && !History::FirstClass(sparse, 10));
        assert(!History::FirstClass({Kind::GpuPalette, 5}, 10) && !History::FirstClass({}, 10));
        assert(History::FirstClass({Kind::Recent, 0}, 10) && !History::FirstClass({Kind::Recent, 4}, 10));
        Draw a{.shader = 1, .geometry = 2, .indices = 3, .topology = 4, .index_count = 30,
               .instances = 1, .vertices = {0, 10}};
        Draw b = a;
        b.shader = 5;
        Draw prop = a;
        prop.shader = 9;
        prop.vertices = {0, 20};
        // First come: a held prop recorded first keeps a late skinned draw out, every frame.
        History old(32);
        for (int f = 0; f < 3; ++f) {
            old.NextFrame();
            const uint32_t half = 1 + uint32_t((f + 1) & 1) * 32;
            assert(old.Prepare(prop, held_sort).store == half);
            assert(old.Prepare(a, skinned).store == half + 20);
            assert(!old.Prepare(b, skinned).store);
        }
        assert(old.stats.exhausted == 3 && old.Used() == 30);
        assert(old.store.kinds[size_t(Kind::Skinned)].skipped == 30);
        assert(old.store.kinds[size_t(Kind::Held)].stored == 60 && old.store.second == 0);
        // By priority: the first frame has no reserve yet; from the second, both skinned draws.
        History pri(32);
        pri.priority = true;
        pri.NextFrame(); // half 1: 33..64
        const auto p1 = pri.Prepare(prop, held_sort);
        const auto a1 = pri.Prepare(a, skinned);
        assert(p1.store == 33 + 12 && a1.store == 33);
        assert(!pri.Prepare(b, skinned).store && pri.Used() == 30);
        pri.NextFrame(); // half 0: 1..32, reserve 20
        const auto p2 = pri.Prepare(prop, held_sort);
        assert(!p2.store && p2.load == p1.store);
        const auto a2 = pri.Prepare(a, skinned);
        const auto b2 = pri.Prepare(b, skinned);
        assert(a2.store == 1 && a2.load == a1.store && b2.store == 11 && !b2.load);
        pri.NextFrame(); // half 1, reserve 20: the prop does not fit above it (12 left)
        assert(!pri.Prepare(prop, held_sort).store);
        assert(pri.Prepare(a, skinned).load == a2.store && pri.Prepare(b, skinned).load == b2.store);
        // A small second-class draw still fits above the reserve; first class may use any room
        // the second left.
        Draw small = prop;
        small.shader = 11;
        small.vertices = {0, 4};
        pri.NextFrame(); // half 0, reserve 20
        assert(pri.Prepare(small, held_sort).store == 1 + 28);
        Draw c = a;
        c.shader = 13;
        c.vertices = {0, 8};
        assert(pri.Prepare(a, skinned).store == 1 && pri.Prepare(b, skinned).store == 11);
        assert(pri.Prepare(c, moved).store == 21 && pri.Used() == 32);
        assert(!pri.Prepare(c, moved).store);
        assert(pri.store.kinds[size_t(Kind::Moved)].skipped == 8 && pri.store.second == 24);
        pri.NextFrame();
        assert(pri.store.frames == 4 && pri.store.skip_frames == 4);
        // Invalidation (two frames without draws) keeps the reserve.
        pri.NextFrame();
        pri.NextFrame();
        assert(!pri.Prepare(prop, held_sort).store);
        // Sparse: a skinned draw using 3 of its 10 vertices goes second.
        History thin(16);
        thin.priority = true;
        thin.NextFrame();
        assert(thin.Prepare(a, sparse).store == 17 + 6);
        assert(!thin.Prepare(b, skinned).store);
        thin.NextFrame();
        assert(!thin.Prepare(a, sparse).store && thin.Prepare(b, skinned).store == 1);
        assert(thin.store.sparse_draws == 2 && thin.store.known_used == 26 &&
               thin.store.known_span == 40);
        // Repeats and instances are reported; a held Moving call is reported as held.
        History count(64);
        count.NextFrame();
        Draw twice = a;
        twice.instances = 2;
        count.Prepare(twice, skinned);
        count.Prepare(twice, skinned);
        assert(count.store.instanced_stored == 40 && count.store.repeat_stored == 20);
        count.SetHold(1);
        assert(!count.Moving(weapon, 1));
        count.NextFrame();
        assert(count.Moving(weapon, 2) && !count.LastHeld());
        count.NextFrame();
        assert(count.Moving(weapon, 2) && count.LastHeld());
        count.NextFrame();
        assert(!count.Moving(weapon, 2) && !count.LastHeld());
        // Recent: held 1..RecentFrames frames after a change is first class, later held.
        History aged(64);
        aged.SetHold(10);
        assert(!aged.Moving(weapon, 1));
        aged.NextFrame();
        assert(aged.Moving(weapon, 2) && aged.LastKind() == Kind::Moved);
        for (uint32_t f = 1; f <= 10; ++f) {
            aged.NextFrame();
            assert(aged.Moving(weapon, 2));
            assert(aged.LastKind() == (f <= History::RecentFrames ? Kind::Recent : Kind::Held));
        }
        aged.NextFrame();
        assert(!aged.Moving(weapon, 2));
        aged.NextFrame();
        assert(aged.Moving(weapon, 3) && aged.LastKind() == Kind::Moved);
        // The reserve is what the first class would take alone: a first-class draw larger than
        // the store does not keep the second class out of room nobody else takes.
        History lone(32);
        lone.priority = true;
        Draw big = a;
        big.shader = 15;
        big.vertices = {0, 40};
        const History::Sort big_sort{Kind::Skinned, 40}; // dense: first class
        lone.NextFrame(); // half 1: 33..64
        assert(!lone.Prepare(big, big_sort).store && lone.Prepare(a, skinned).store == 33);
        lone.NextFrame(); // half 0: 1..32, reserve 10
        assert(lone.Prepare(prop, held_sort).store == 1 + 12);
        assert(!lone.Prepare(big, big_sort).store && lone.Prepare(a, skinned).store == 1);
        assert(lone.Used() == 30);
        History sized(32);
        sized.SetCapacity(8);
        sized.NextFrame();
        assert(sized.Capacity() == 8 && !sized.Prepare(a, skinned).store);
    }

    assert(JitterPhases(1920, 1920) == 8);
    assert(JitterPhases(1280, 1920) == 18);
    assert(JitterPhases(960, 1920) == 32);
    assert(JitterPhases(640, 1920) == 72);
    assert(JitterPhases(0, 1920) == 8);
    std::puts("Motion history: PASS (ranges, restart, offsets, matching, capacity, gating, index cache, jitter)");
}
