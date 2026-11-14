// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r43_copy-turns): the turns of the ray tracing scene's shared copies (rt_copy_turns.h),
// run as RtShadow runs them: frames of draws in a fixed order, a rebuild budget, the plan at each
// frame's end. The sizes are those of the game's log lines.
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#include "gpu/shadps4/video_core/renderer_vulkan/rt_copy_turns.h"

using namespace Vulkan;

namespace {
constexpr std::uint32_t Budget = 300000;

struct Copy {
    std::uint32_t triangles = 0;
    std::uint32_t every = 1;   ///< drawn on one frame in this many (frame % every == phase)
    std::uint32_t flicker = 0; ///< not 0: drawn or not in stretches of this many frames
    std::uint32_t phase = 0;
    std::uint64_t first = 0;   ///< not drawn before this frame
    bool moving = true;
    int group = 0;             ///< for the cases' questions
    // What RtShadow::Entry keeps.
    CopyTurnTicket turn;
    std::uint64_t seen_frame = 0, built_frame = 0;
    std::uint32_t gap = 1, run = 0, back_run = 0;
    bool built = false;
    // What the cases ask for: rebuilds, the most frames in a row without one while drawn every
    // frame, the most draws in a row without one after frames undrawn.
    std::uint32_t rebuilds = 0, worst_run = 0, worst_back_run = 0, draws = 0;
};

Copy Make(std::uint32_t triangles, std::uint32_t every = 1, std::uint32_t flicker = 0) {
    Copy c;
    c.triangles = triangles;
    c.every = every;
    c.flicker = flicker;
    return c;
}

struct Scene {
    std::vector<Copy> copies; ///< in draw order
    CopyTurns turns;
    std::vector<CopyTurnItem> items;
    std::uint64_t frame = 1;
    std::uint32_t budget = Budget, wait = CopyTurnWait;
    bool first_come = false;              ///< the rule of before
    std::uint32_t most = 0, least = ~0u;  ///< triangles rebuilt on a frame
    std::uint32_t last = 0;               ///< and on the last one
    std::uint64_t rebuilt_all = 0, past = 0;

    void Add(const std::vector<std::uint32_t>& sizes, std::uint32_t every = 1, std::uint32_t flicker = 0) {
        for (const std::uint32_t triangles : sizes) {
            copies.push_back(Make(triangles, every, flicker));
        }
    }

    // `total` triangles in copies of `each`: group `group`, moving or not, drawn on one frame
    // in `every` (a sun cascade's phase), from frame `first` on.
    void Fill(int group, std::uint32_t total, std::uint32_t each, bool moving, std::uint32_t every = 1,
              std::uint32_t phase = 0, std::uint64_t first = 0) {
        for (std::uint32_t done = 0; done < total; done += each) {
            Copy c = Make(each, every);
            c.phase = phase;
            c.first = first;
            c.moving = moving;
            c.group = group;
            copies.push_back(c);
        }
    }

    [[nodiscard]] bool Drawn(const Copy& c, std::size_t index) const {
        if (frame < c.first || frame % c.every != c.phase) {
            return false;
        }
        return c.flicker == 0 ||
               (std::uint32_t((frame / c.flicker + index) * 2654435761ull) >> 16) % 3 != 0;
    }

    // One frame, as RtShadow::PrepareDraw and OnFrameEnd do it.
    void Frame() {
        std::uint32_t rebuilt = 0;
        items.clear();
        for (std::size_t i = 0; i < copies.size(); ++i) {
            Copy& c = copies[i];
            if (!Drawn(c, i)) {
                continue;
            }
            ++c.draws;
            c.gap = c.seen_frame == 0 ? CopyTurnGapUnknown
                                      : std::uint32_t(std::min<std::uint64_t>(frame - c.seen_frame,
                                                                              CopyTurnGapUnknown));
            c.seen_frame = frame;
            if (!c.built) {
                // The first build is not a refresh: it has the budget of new casters.
                c.built = true;
                c.built_frame = frame;
            } else if (first_come ? rebuilt < budget
                                  : turns.Take(c.turn, c.triangles, frame, rebuilt, budget)) {
                rebuilt += c.triangles;
                c.built_frame = frame;
                c.run = c.back_run = 0;
                ++c.rebuilds;
            } else if (c.gap == 1) {
                c.worst_run = std::max(c.worst_run, ++c.run);
            } else {
                c.run = 0;
                c.worst_back_run = std::max(c.worst_back_run, ++c.back_run);
            }
            items.push_back({&c.turn, c.built_frame, c.triangles, c.gap, c.moving});
        }
        last = rebuilt;
        most = std::max(most, rebuilt);
        least = std::min(least, rebuilt);
        rebuilt_all += rebuilt;
        if (first_come) {
            turns.Clear();
        } else {
            past += turns.Plan(items, frame, budget, wait).past;
        }
        ++frame;
    }

    void Run(int frames) {
        for (int i = 0; i < frames; ++i) {
            Frame();
        }
    }

    // The counts start again (after the frames a scene needs to come in).
    void Settle(int frames) {
        Run(frames);
        most = 0;
        least = ~0u;
        rebuilt_all = past = 0;
        for (Copy& c : copies) {
            c.rebuilds = c.worst_run = c.worst_back_run = c.draws = 0;
        }
    }

    [[nodiscard]] std::uint32_t WorstRun() const {
        std::uint32_t worst = 0;
        for (const Copy& c : copies) {
            worst = std::max(worst, c.worst_run);
        }
        return worst;
    }

    // Of one group: the most frames in a row a copy went without a rebuild while drawn every
    // frame, the most draws in a row without one after frames undrawn, the fewest rebuilds of
    // a copy, and the triangles rebuilt since the counts began.
    struct Group {
        std::uint32_t worst_run = 0, worst_back_run = 0, fewest = ~0u;
        std::uint64_t rebuilt = 0;
    };
    [[nodiscard]] Group Of(int group) const {
        Group g;
        for (const Copy& c : copies) {
            if (c.group == group) {
                g.worst_run = std::max(g.worst_run, c.worst_run);
                g.worst_back_run = std::max(g.worst_back_run, c.worst_back_run);
                g.fewest = std::min(g.fewest, c.rebuilds);
                g.rebuilt += std::uint64_t(c.rebuilds) * c.triangles;
            }
        }
        return g;
    }
};

// The game's log: "24 of 16 meshes, 483781 triangles, 24 moving ... 16 (306953 triangles)
// rebuilt on it; rebuilt budget 300000 ... 8 moving copies starved of rebuilds ... the largest:
// 53592 triangles ... 38896 ... 28824 ... 20700". The first 16 in draw order take the budget.
const std::vector<std::uint32_t> Near24{40000, 36000, 30000, 26953, 24000, 22000, 20000, 18000,
                                        16000, 14000, 13000, 12000, 11000, 10000, 5000,  9000,
                                        53592, 38896, 28824, 20700, 12000, 9816,  8000,  5000};
// "26 of 18 meshes, 545332 triangles": two more.
const std::vector<std::uint32_t> Near2{31551, 30000};
// "35 of 18 meshes, 779210 triangles": nine more on the frames the far cascades are drawn.
const std::vector<std::uint32_t> Far9{53592, 38896, 28824, 20700, 31551, 30000, 12000, 9816, 8499};
constexpr std::uint32_t Largest = 53592;
} // namespace

int main() {
    // The rule of before: the first 16 copies are rebuilt on every frame and the same 8 never.
    {
        Scene scene;
        scene.first_come = true;
        scene.Add(Near24);
        scene.Run(200);
        for (std::size_t i = 0; i < scene.copies.size(); ++i) {
            const Copy& c = scene.copies[i];
            assert(c.rebuilds == (i < 16 ? 199u : 0u) && c.worst_run == (i < 16 ? 0u : 199u));
        }
        assert(scene.most == 306953);
    }
    // Turns: every copy is rebuilt at least every 2nd frame, and a frame rebuilds the budget
    // and at most one mesh more, as before.
    std::uint32_t log_most = 0;
    {
        Scene scene;
        scene.Add(Near24);
        scene.Settle(4);
        scene.Run(200);
        for (const Copy& c : scene.copies) {
            assert(c.worst_run <= 1 && c.rebuilds >= 100 && c.worst_back_run == 0);
        }
        assert(scene.least >= Budget && scene.most < Budget + Largest && scene.past == 0);
        log_most = scene.most;
    }
    // The 26 copies of the other log line and the far cascades' 9 on every 8th frame, drawn
    // last (graphics_sun_far_shadows = rare): the 26 are rebuilt at least every 3rd frame, the 9
    // each time they are drawn, and from their second return on a frame stays within the
    // budget and two meshes (one for the copies drawn every frame, one for those that came
    // back). The rule of before never rebuilt the 9, nor the last of the 26.
    std::uint32_t far_worst = 0, far_most = 0;
    {
        Scene before;
        before.first_come = true;
        before.Add(Near24);
        before.Add(Near2);
        before.Add(Far9, 8);
        before.Run(400);
        for (std::size_t i = 26; i < before.copies.size(); ++i) {
            assert(before.copies[i].rebuilds == 0 && before.copies[i].worst_back_run == 49);
        }
        Scene scene;
        scene.Add(Near24);
        scene.Add(Near2);
        scene.Add(Far9, 8);
        scene.Settle(20);
        scene.Run(400);
        for (std::size_t i = 0; i < scene.copies.size(); ++i) {
            const Copy& c = scene.copies[i];
            if (i < 26) {
                assert(c.worst_run <= 2 && c.rebuilds >= 133);
            } else {
                assert(c.draws == 50 && c.rebuilds == 50 && c.worst_back_run == 0);
            }
        }
        assert(scene.most < Budget + 2 * Largest && scene.past == 0);
        far_worst = scene.WorstRun();
        far_most = scene.most;
    }
    // graphics_sun_far_shadows = alternate: c3 is drawn on the even frames and c2 on the odd
    // ones (SunParse in graphics.cpp gives them different phases), so far copies come back on
    // EVERY frame. They take turns with the 26 by age and do not hold every frame's budget: the
    // 26 wait 3 frames at most, a far copy is rebuilt at least every 2nd time it is drawn, and
    // no frame goes past the budget and two meshes.
    std::uint32_t alt_worst = 0, alt_most = 0;
    {
        Scene scene;
        scene.Add(Near24);
        scene.Add(Near2);
        scene.Add(Far9, 2);
        scene.Add(Far9, 2);
        for (std::size_t i = 26; i < scene.copies.size(); ++i) {
            scene.copies[i].group = 1;
            scene.copies[i].phase = i < 35 ? 0 : 1;
        }
        scene.Settle(20);
        scene.Run(400);
        const Scene::Group near = scene.Of(0), far = scene.Of(1);
        assert(near.worst_run <= 3 && far.worst_run == 0 && far.worst_back_run <= 1 && far.fewest >= 100);
        assert(scene.most < Budget + 2 * Largest && scene.past == 0);
        alt_worst = near.worst_run;
        alt_most = scene.most;
    }
    // The same schedule with more of everything: 1 million triangles of moving near copies and
    // 340,000 in each far cascade. The near copies keep the bound within the budget (the far
    // ones leave them the bound's share), the far ones are rebuilt at least every 4th draw.
    {
        Scene scene;
        scene.Fill(0, 1000000, 20000, true);
        scene.Fill(1, 340000, 20000, true, 2, 0);
        scene.Fill(1, 340000, 20000, true, 2, 1);
        scene.Settle(40);
        scene.Run(600);
        const Scene::Group near = scene.Of(0), far = scene.Of(1);
        assert(near.worst_run <= CopyTurnWait && far.worst_back_run <= 3 && far.fewest >= 75);
        assert(scene.most <= Budget + 20000 && scene.past == 0);
    }
    // And past what two budgets can keep: 1.68 million triangles of moving near copies need
    // 336,000 a frame for the bound alone. No frame rebuilds more than two budgets, no copy is
    // left out, and the near copies go one frame past the bound at most.
    {
        Scene scene;
        scene.Fill(0, 1680000, 20000, true);
        scene.Fill(1, 300000, 20000, true, 2, 0);
        scene.Fill(1, 300000, 20000, true, 2, 1);
        scene.Settle(40);
        scene.Run(600);
        const Scene::Group near = scene.Of(0), far = scene.Of(1);
        assert(near.worst_run <= CopyTurnWait + 1 && far.worst_back_run <= 4 && far.fewest >= 60);
        assert(scene.most <= 2 * Budget && scene.past > 0);
    }
    // Two cascades that come back on the same frames (BB_SUN_CASCADES="1 2 4 8": one every 2nd
    // frame, one every 8th) beside 900,000 triangles of near copies. No ticket is handed out
    // that the draw turns down: the cascade drawn every 8th frame, last in draw order, is
    // rebuilt each time it is drawn (with a whole budget for every plan's copies that came
    // back, the two-budget limit cut its tickets on every return).
    {
        Scene scene;
        scene.Fill(0, 900000, 20000, true);
        scene.Fill(1, 320000, 20000, true, 2, 0);
        scene.Fill(2, 300000, 20000, true, 8, 0);
        scene.Settle(40);
        scene.Run(800);
        const Scene::Group near = scene.Of(0), second = scene.Of(1), eighth = scene.Of(2);
        assert(near.worst_run <= CopyTurnWait && second.worst_back_run <= 3 && second.fewest >= 100);
        assert(eighth.worst_back_run == 0 && eighth.fewest == 100);
        assert(scene.most <= Budget + 180000 + 20000); // the 8th frame's copies and the bound's share
    }
    // Copies that do not move (several of one prop) wait four times as long as moving ones and
    // leave them the budget, but are not left out. 600,000 moving and 1.2 million that do not:
    // the moving ones wait 2 frames, the others 12 (one order by age made all wait 5, and the
    // moving ones past the bound's 4 got their turns together on one frame, past the budget).
    // 240,000 moving: rebuilt every 2nd frame at the least. All within the budget.
    {
        Scene scene;
        scene.Fill(0, 600000, 20000, true);
        scene.Fill(1, 1200000, 20000, false);
        scene.Settle(40);
        scene.Run(600);
        assert(scene.Of(0).worst_run <= 2 && scene.Of(1).worst_run <= 12 && scene.Of(1).fewest >= 40);
        assert(scene.most <= Budget + 20000 && scene.past == 0);

        Scene few;
        few.Fill(1, 1200000, 20000, false); // drawn first
        few.Fill(0, 240000, 20000, true);
        few.Settle(40);
        few.Run(600);
        assert(few.Of(0).worst_run <= 1 && few.Of(1).worst_run <= 8 && few.Of(1).fewest >= 60);
        assert(few.most <= Budget + 20000 && few.past == 0);
    }
    // The heaviest spot with its copies that do not move (1.32 million moving, 360,000 not):
    // the moving ones keep the bound, the others are rebuilt every 20th frame at the least,
    // and no frame goes past the budget.
    {
        Scene scene;
        scene.Fill(0, 1320000, 20000, true);
        scene.Fill(1, 360000, 20000, false);
        scene.Settle(40);
        scene.Run(600);
        assert(scene.Of(0).worst_run <= CopyTurnWait);
        assert(scene.Of(1).worst_run < CopyTurnStill * (CopyTurnWait + 1) && scene.Of(1).fewest >= 30);
        assert(scene.most <= Budget + 20000 && scene.past == 0);
    }
    // Copies that do not move beside far cascades that could hold every frame's budget
    // (alternate, 300,000 and more in each): they get their turns (before: none in 3,000
    // frames, with or without moving copies beside them).
    {
        Scene scene;
        scene.Fill(1, 100000, 10000, false);
        scene.Fill(2, 300000, 20000, true, 2, 0);
        scene.Fill(2, 300000, 20000, true, 2, 1);
        scene.Settle(40);
        scene.Run(600);
        assert(scene.Of(1).worst_run <= 8 && scene.Of(1).fewest >= 60 && scene.Of(2).worst_back_run <= 1);
        assert(scene.most <= Budget + 20000);

        Scene mixed;
        mixed.Fill(1, 200000, 20000, false);
        mixed.Fill(0, 200000, 20000, true);
        mixed.Fill(2, 320000, 20000, true, 2, 0);
        mixed.Fill(2, 320000, 20000, true, 2, 1);
        mixed.Settle(40);
        mixed.Run(600);
        assert(mixed.Of(0).worst_run <= 2 && mixed.Of(1).worst_run <= 8 && mixed.Of(1).fewest >= 60);
        assert(mixed.Of(2).worst_back_run <= 1 && mixed.most <= Budget + 20000 && mixed.past == 0);
    }
    // New copies (200,000 triangles appear on frame 300 beside the log's 484,000): they were
    // built on that frame and are the newest, so the frame after it rebuilds none of them and
    // the older copies keep their turns; from then on they take turns with the rest.
    {
        Scene scene;
        scene.Fill(0, 484000, 22000, true);
        scene.Fill(1, 200000, 20000, true, 1, 0, 300);
        scene.Settle(300);
        assert(scene.frame == 301 && scene.Of(1).rebuilt == 0);
        scene.Frame();
        assert(scene.Of(1).rebuilt == 0 && scene.last >= Budget && scene.Of(0).worst_run <= 1);
        scene.Run(200);
        assert(scene.Of(0).worst_run <= 2 && scene.Of(1).worst_run <= 2 && scene.Of(1).fewest >= 60);
        assert(scene.most < Budget + 22000 && scene.past == 0);
    }
    // Everything within the budget: every copy on every frame, with turns as without.
    for (const bool first_come : {false, true}) {
        Scene scene;
        scene.first_come = first_come;
        scene.Add({40000, 36000, 30000, 26953, 24000, 22000, 20000, 18000, 16000, 14000});
        scene.Run(100);
        for (const Copy& c : scene.copies) {
            assert(c.rebuilds == 99 && c.worst_run == 0);
        }
    }
    // The heaviest spot measured (156 copies, 1.32 million triangles): no copy waits longer
    // than the bound, within the budget and a mesh.
    std::uint32_t heavy_worst = 0;
    {
        Scene scene;
        for (std::uint32_t i = 0; i < 156; ++i) {
            scene.copies.push_back(Make(2460 + (i * 7919u) % 12001u));
        }
        std::uint64_t triangles = 0;
        for (const Copy& c : scene.copies) {
            triangles += c.triangles;
        }
        assert(triangles > 1300000 && triangles < 1340000);
        scene.Settle(10);
        scene.Run(300);
        heavy_worst = scene.WorstRun();
        assert(heavy_worst <= CopyTurnWait && scene.most < Budget + 14461 && scene.past == 0);
    }
    // 2.4 million triangles: the bound holds by turns past the budget, as many as it needs
    // (a fifth of the copies a frame). With BB_RT_COPY_WAIT=0 nothing goes past the budget and
    // the wait is what the budget gives. 4 million: a frame's turns stop at two budgets, and
    // the wait grows past the bound.
    std::uint32_t most_24 = 0, worst_40 = 0;
    {
        const auto fill = [](Scene& scene, std::uint32_t count) {
            for (std::uint32_t i = 0; i < count; ++i) {
                scene.copies.push_back(Make(20000));
            }
        };
        Scene scene;
        fill(scene, 120);
        scene.Settle(10);
        scene.Run(300);
        assert(scene.WorstRun() == CopyTurnWait && scene.past > 0);
        assert(scene.most <= 2400000 / (CopyTurnWait + 1) + 20000 && scene.most < 2 * Budget);
        most_24 = scene.most;

        Scene plain;
        plain.wait = 0;
        fill(plain, 120);
        plain.Settle(10);
        plain.Run(300);
        assert(plain.WorstRun() == 7 && plain.past == 0 && plain.most == Budget);

        Scene net;
        fill(net, 200);
        net.Settle(10);
        net.Run(300);
        worst_40 = net.WorstRun();
        assert(worst_40 > CopyTurnWait && worst_40 <= 7 && net.most <= 2 * Budget + 20000);
    }
    // Budget 0 (experiment 256, BB_RT_COPY_BUDGET=0): no copy is refreshed.
    {
        Scene scene;
        scene.budget = 0;
        scene.Add(Near24);
        scene.Run(50);
        assert(scene.most == 0 && scene.turns.Expected() == 0);
    }
    // A set that changes: a third of the copies come and go in stretches of 1 to 7 frames.
    // No copy is drawn more than the bound's frames in a row without a rebuild, a frame never
    // rebuilds more than two budgets and a mesh, and over the run no more than the budget and
    // two meshes a frame.
    {
        Scene scene;
        for (std::uint32_t i = 0; i < 90; ++i) {
            scene.copies.push_back(Make(4000 + (i * 7919u) % 20001u, 1, i % 3 == 0 ? 1 + i % 7 : 0));
        }
        scene.Settle(10);
        scene.Run(1000);
        assert(scene.WorstRun() <= CopyTurnWait);
        assert(scene.most <= 2 * Budget + 24000 && scene.rebuilt_all <= 1000ull * (Budget + 2 * 24000));
        for (const Copy& c : scene.copies) {
            assert(c.rebuilds > 0);
        }
    }
    // A ticket: good from its first frame for `keep` frames more; used up by the draw that
    // asks, whatever the answer; a holder is rebuilt up to two budgets, a copy without one only
    // within what is not promised.
    {
        CopyTurns turns;
        CopyTurnTicket steady, back, none;
        std::vector<CopyTurnItem> items{{&steady, 5, 1000, 1, true}, {&back, 2, 150000, 8, true}};
        const CopyTurnPlan plan = turns.Plan(items, 10, Budget, CopyTurnWait);
        assert(plan.steady == 1000 && plan.back == 150000 && plan.past == 0);
        assert(steady.Good(11) && !steady.Good(10) && !steady.Good(12));
        assert(back.Good(11) && back.Good(28) && !back.Good(29) && back.from + back.due == 18);
        assert(turns.Expected() == 1000);
        assert(!turns.Take(none, 500, 11, Budget - 1000, Budget)); // promised to `steady`
        assert(turns.Take(none, 500, 11, Budget - 1001, Budget));
        assert(turns.Take(steady, 1000, 11, 2 * Budget - 1, Budget) && !steady.Good(11));
        assert(turns.Expected() == 0);
        assert(turns.Take(none, 500, 11, Budget - 1, Budget) && !turns.Take(none, 500, 11, Budget, Budget));
        CopyTurnTicket late{11, 0, 0};
        assert(!turns.Take(late, 500, 11, 2 * Budget, Budget)); // the safety net
        // The frame the copy that came back is expected on gives its triangles fewer to the
        // others: of two copies of 200,000 only the older gets a ticket then.
        CopyTurnTicket a, b;
        for (std::uint64_t frame = 11; frame <= 17; ++frame) {
            std::vector<CopyTurnItem> two{{&a, frame, 200000, 1, true}, {&b, frame - 1, 200000, 1, true}};
            const CopyTurnPlan each = turns.Plan(two, frame, Budget, CopyTurnWait);
            assert(frame < 17 ? each.steady == 400000 : (each.steady == 200000 && b.Good(18) && !a.Good(18)));
        }
        assert(turns.Expected() == 350000 && turns.Take(back, 150000, 18, 0, Budget));
        assert(turns.Expected() == 200000);
        // A copy seen for the first time was built on this frame: it takes its turn with the
        // copies drawn every frame, with a ticket for the next frame only. One that is back
        // after a time too long to know (built before) is expected on the next frame with a
        // ticket that lasts CopyTurnKeep frames; a gap longer than the plan looks ahead is
        // waited for.
        CopyTurnTicket fresh, old, rare;
        std::vector<CopyTurnItem> more{{&fresh, 18, 3000, CopyTurnGapUnknown, true},
                                       {&old, 3, 5000, CopyTurnGapUnknown, true},
                                       {&rare, 1, 4000, 100, true}};
        const CopyTurnPlan last = turns.Plan(more, 18, Budget, CopyTurnWait);
        assert(last.steady == 3000 && last.back == 9000);
        assert(fresh.Good(19) && !fresh.Good(20));
        assert(old.Good(19) && old.Good(18 + CopyTurnKeep) && !old.Good(19 + CopyTurnKeep));
        assert(rare.Good(19) && rare.Good(18 + 102) && !rare.Good(18 + 103));
        assert(turns.Expected() == 12000);
        // A copy that came back gets no ticket for a frame whose budget is already given out:
        // by an earlier plan, or to copies drawn every frame that are as old as it will be.
        CopyTurns full;
        CopyTurnTicket first, second, near, far;
        std::vector<CopyTurnItem> one{{&first, 1, 300000, 4, true}};
        assert(full.Plan(one, 10, Budget, CopyTurnWait).back == 300000 && first.from + first.due == 14);
        std::vector<CopyTurnItem> two{{&second, 1, 50000, 3, true}};
        assert(full.Plan(two, 11, Budget, CopyTurnWait).back == 0 && !second.Good(12));
        std::vector<CopyTurnItem> three{{&near, 8, 300000, 1, true}, {&far, 10, 50000, 3, true}};
        assert(full.Plan(three, 12, Budget, CopyTurnWait).back == 0 && near.Good(13) && !far.Good(13));
        std::vector<CopyTurnItem> four{{&near, 12, 300000, 1, true}, {&far, 10, 50000, 3, true}};
        assert(full.Plan(four, 13, Budget, CopyTurnWait).back == 50000 && far.from + far.due == 16);
    }
    // The knobs: a whole number, at most the range's end; anything else leaves the default.
    assert(ReadCopyTurnKnob(nullptr, 300000, CopyTurnBudgetMost) == 300000);
    assert(ReadCopyTurnKnob("", 300000, CopyTurnBudgetMost) == 300000);
    assert(ReadCopyTurnKnob("800000", 300000, CopyTurnBudgetMost) == 800000);
    assert(ReadCopyTurnKnob(" 0 ", 300000, CopyTurnBudgetMost) == 0);
    assert(ReadCopyTurnKnob("99999999999999", 300000, CopyTurnBudgetMost) == CopyTurnBudgetMost);
    assert(ReadCopyTurnKnob("-1", 4, CopyTurnWaitMost) == 4 && ReadCopyTurnKnob("2x", 4, CopyTurnWaitMost) == 4);
    assert(ReadCopyTurnKnob("abc", 4, CopyTurnWaitMost) == 4 && ReadCopyTurnKnob("40", 4, CopyTurnWaitMost) == 16);
    std::printf("rt copy turns: ok (the log's 484k triangles: every copy at least every 2nd frame, at most %u "
                "triangles a frame; with far cascades every 8th frame: %u frames without a rebuild at most, %u "
                "triangles; with far cascades on alternate frames: %u frames, %u triangles; 1.32M: %u frames; "
                "2.4M: %u triangles a frame; 4M: %u frames)\n",
                log_most, far_worst, far_most, alt_worst, alt_most, heavy_worst, most_24, worst_40);
    return 0;
}
