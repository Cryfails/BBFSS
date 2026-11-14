// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r43_copy-turns): whose turn it is to be rebuilt among the shared copies of the ray
// tracing scene (RtShadow, vk_rt_shadow.cpp). No Vulkan here: tests/test_rt_copy_turns.cpp
// builds this header alone and runs the code the engine runs.
//
// A shared copy is one draw of a mesh that a pass draws more than once (the same body in every
// sun cascade, several of one prop). It has its own bottom-level structure with the vertices in
// world space and is known only by its place in the draw order, so it cannot be refit: it is
// rebuilt, and a frame's rebuilds have a budget in triangles (BB_RT_COPY_BUDGET, 300,000).
//
// Before, the budget went to the copies in draw order and began again at nothing every frame.
// The draw order of a scene is the same every frame, so wherever a frame's copies held more
// triangles than the budget the same first ones were rebuilt every frame and the same last
// ones never: they stayed in the scene in the pose of their first build (for 6,301 frames in
// the game's log) and cast a lamp shadow that did not move.
//
// Now the copies take turns. At the end of every frame the copies drawn on it are put in the
// order of their need, the greatest first, and are given tickets for their next draw until the
// tickets hold the budget (the copy that crosses it still gets one, as before). A copy's need
// is the age its build will have at that draw, in frames. A copy that does not move counts a
// quarter of its age (CopyTurnStill): its build only goes wrong when the draw order shifts (a
// prop is culled and the copy stands for another one), so it waits four times as long as a
// moving copy and leaves the budget to those. At a draw a copy with a ticket is rebuilt; one
// without is rebuilt only with what the ticket holders still to come leave of the budget. What
// follows:
//  - Where all copies fit the budget every one holds a ticket every frame: as before.
//  - Where they do not, the moving copies that are drawn every frame are all rebuilt every Nth
//    frame, N = their triangles over what the budget has for them, rounded up: every 2nd frame
//    at the 484,000 to 545,000 triangles of the game's log. That is the price of the repair at
//    one budget: before, the first 300,000 triangles in draw order were rebuilt every frame and
//    the rest never.
//  - The bound: a moving copy that is drawn every frame is not drawn more than `wait` frames in
//    a row without a rebuild (BB_RT_COPY_WAIT, 4), so its pose in the scene is never more than
//    `wait` frames old. For that every frame's tickets hold at least a (wait + 1)th of the
//    moving copies drawn every frame: past the budget where the budget does not give that much
//    (more than wait + 1 budgets of them, or a frame whose budget is held by copies that come
//    back), the same number every frame. A copy that would still wait longer (the set of
//    copies changed) gets its ticket whatever the count. A frame's tickets never hold more
//    than two budgets, so past 2 * (wait + 1) budgets of moving copies the wait grows again.
//  - A copy that is not drawn every frame (the far sun cascades are drawn every 2nd or 8th
//    frame with graphics_sun_far_shadows, and their copies stay in the scene between) gets its
//    ticket for the frame it is expected back on (its last gap later), and that frame hands
//    that many triangles fewer to the copies drawn every frame. It competes for that frame's
//    budget by the same need: it gets the ticket only while the tickets already given for the
//    frame, and the copies drawn every frame whose need is as great as its own (the bound's
//    share of them at the least), leave room in one budget. So a cascade drawn every 8th frame
//    is rebuilt each time it is drawn (its builds are the oldest by then), and cascades drawn
//    every 2nd frame take turns with the near copies by age and do not take the budget from
//    them. No more tickets are handed out for a frame than its draws honour (two budgets).
//  - A copy drawn for the first time was built on that frame and is the newest: it takes its
//    turn with the copies drawn every frame and gets a ticket only if the budget allows.

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <vector>

namespace Vulkan {

/// BB_RT_COPY_WAIT: its default and its most (0: no turn goes past the budget).
inline constexpr std::uint32_t CopyTurnWait = 4;
inline constexpr std::uint32_t CopyTurnWaitMost = 16;
/// BB_RT_COPY_BUDGET's most, triangles a frame.
inline constexpr std::uint32_t CopyTurnBudgetMost = 4000000;
/// The ticket of a copy that is not drawn every frame is good for this many frames at the
/// least: as long as RtShadow holds a sun cascade's copies undrawn (MaxHoldPeriod +
/// HoldMarginFrames).
inline constexpr std::uint32_t CopyTurnKeep = 18;
/// A copy is expected back at most this many frames ahead (a longer gap: on the next frame).
/// BB_SUN_CASCADES draws a cascade every 60th frame at the rarest.
inline constexpr std::uint32_t CopyTurnAhead = 62;
/// CopyTurnItem::gap of a copy never drawn before, or not for this many frames.
inline constexpr std::uint32_t CopyTurnGapUnknown = 255;
/// A moving copy's need is this many times that of a copy of the same age that does not move.
inline constexpr std::uint32_t CopyTurnStill = 4;

/// A knob's text as a whole number, at most `most`; no text or anything else: `fallback`.
inline std::uint32_t ReadCopyTurnKnob(const char* text, std::uint32_t fallback, std::uint32_t most) {
    if (!text) {
        return fallback;
    }
    while (*text == ' ' || *text == '\t') {
        ++text;
    }
    if (*text < '0' || *text > '9') {
        return fallback;
    }
    char* end = nullptr;
    const unsigned long long value = std::strtoull(text, &end, 10);
    while (*end == ' ' || *end == '\t' || *end == '\r' || *end == '\n') {
        ++end;
    }
    if (*end != '\0') {
        return fallback;
    }
    return std::uint32_t(std::min<unsigned long long>(value, most));
}

/// A copy's turn, kept in the copy itself (RtShadow::Entry::turn).
struct CopyTurnTicket {
    std::uint64_t from = 0; ///< the first frame it is good on; 0: no ticket
    std::uint32_t keep = 0; ///< good on this many frames after `from` as well
    std::uint32_t due = 0;  ///< the frame from + due counts on it (CopyTurns::Expected)

    [[nodiscard]] bool Good(std::uint64_t frame) const noexcept {
        return from != 0 && frame >= from && frame - from <= keep;
    }
};

/// A built copy drawn on the frame that ends, for CopyTurns::Plan.
struct CopyTurnItem {
    CopyTurnTicket* ticket = nullptr; ///< where its ticket is kept (written by Plan)
    std::uint64_t built_frame = 0;    ///< the frame of its last build
    std::uint32_t triangles = 0;
    /// The frames from its draw before to this one: 1 drawn on the frame before too, 2 and more
    /// drawn again after frames undrawn, CopyTurnGapUnknown never before or long ago.
    std::uint32_t gap = 1;
    bool moving = false;
};

/// What a plan handed out, in triangles: to the copies drawn every frame and to those drawn
/// again after frames undrawn; and the tickets (and their triangles) that went past the budget
/// for the bound.
struct CopyTurnPlan {
    std::uint32_t steady = 0, back = 0;
    std::uint32_t past = 0, past_triangles = 0;
};

class CopyTurns {
public:
    /// The end of `frame`: tickets for the next draw of every item, or none. `items` is in
    /// draw order (which decides between copies built on the same frame).
    CopyTurnPlan Plan(std::vector<CopyTurnItem>& items, std::uint64_t frame, std::uint32_t budget,
                      std::uint32_t wait) {
        if (frame != planned + 1) {
            ahead.fill(0); // frames went by without a plan: what was expected back is not known
        }
        planned = frame;
        CopyTurnPlan plan;
        std::uint32_t& next = ahead[(frame + 1) % ahead.size()];
        for (CopyTurnItem& item : items) {
            *item.ticket = {};
        }
        if (budget == 0) {
            next = 0;
            expected = 0;
            return plan;
        }
        // A copy drawn again after frames undrawn is expected back its last gap later; every
        // other on the next frame, also one drawn for the first time, which was built on this
        // frame (it is the newest and takes its turn with the copies drawn every frame).
        const auto came_back = [&](const CopyTurnItem& item) {
            return item.gap != 1 && !(item.gap >= CopyTurnGapUnknown && item.built_frame >= frame);
        };
        const auto due = [&](const CopyTurnItem& item) -> std::uint32_t {
            return came_back(item) && item.gap <= CopyTurnAhead ? item.gap : 1;
        };
        // The need: the age of the build at the draw the ticket is for; a copy that does not
        // move counts a quarter of it.
        const auto need = [&](const CopyTurnItem& item) -> std::uint64_t {
            const std::uint64_t age = frame + due(item) - std::min(item.built_frame, frame);
            return item.moving ? age * CopyTurnStill : age;
        };
        steady.clear();
        back.clear();
        for (std::uint32_t i = 0; i < items.size(); ++i) {
            (came_back(items[i]) ? back : steady).push_back(i);
        }
        const auto greatest_need = [&](std::uint32_t a, std::uint32_t b) {
            return need(items[a]) > need(items[b]);
        };
        std::stable_sort(steady.begin(), steady.end(), greatest_need);
        std::stable_sort(back.begin(), back.end(), greatest_need);
        // The bound's share: what a frame's tickets must hold of the copies drawn every frame
        // for none to wait longer than the bound, the same number every frame. A moving copy
        // may be drawn `wait` frames in a row without a rebuild, so a (wait + 1)th of the
        // moving ones; one that does not move waits CopyTurnStill times as long. No bound
        // (wait 0): no share, the budget alone decides.
        const auto limit = [&](bool moving) {
            return std::uint64_t(wait + 1) * (moving ? 1 : CopyTurnStill);
        };
        std::uint64_t even[2] = {0, 0}; // [0] of the copies that do not move, [1] of the moving
        if (wait != 0) {
            for (const std::uint32_t i : steady) {
                even[items[i].moving ? 1 : 0] += items[i].triangles;
            }
            even[0] = (even[0] + limit(false) - 1) / limit(false);
            even[1] = (even[1] + limit(true) - 1) / limit(true);
        }
        // The copies drawn again after frames undrawn. A ticket lasts until its copy is drawn
        // next, and the frame the copy is expected on is told how many triangles it will take.
        // That frame's budget is also wanted by the copies drawn every frame, which get their
        // tickets only at the end of the frame before it; they are taken to be then as they
        // are now. So a copy that came back gets its ticket while one budget has room for the
        // tickets already given for its frame (by this plan and earlier ones) together with
        // the copies drawn every frame whose need is as great as its own, and no fewer of
        // those than the bound's share: else that share would go past the budget on every
        // frame a cascade comes back on. A copy that comes back more rarely than the bound's
        // frames, or whose build is twice as old as the bound lets a copy drawn every frame
        // get, does not leave that share alone (it would never be rebuilt where the share is
        // a budget or more). Before, these copies were served first with a whole budget each
        // plan: far cascades drawn every 2nd frame, one on the even and one on the odd frames,
        // held the budget of every frame, the near copies fell to the bound's turns past the
        // budget, and copies that do not move got none at all.
        std::size_t s = 0;
        std::uint64_t before = 0;
        for (const std::uint32_t i : back) {
            const CopyTurnItem& item = items[i];
            const std::uint64_t mine = need(item);
            for (; s < steady.size() && need(items[steady[s]]) >= mine; ++s) {
                before += items[steady[s]].triangles;
            }
            const std::uint32_t frames = due(item);
            std::uint32_t& slot = ahead[(frame + frames) % ahead.size()];
            const bool overdue = item.gap > wait || mine >= 2 * CopyTurnStill * limit(true);
            if (slot + (overdue ? before : std::max(before, even[0] + even[1])) >= budget) {
                continue;
            }
            const std::uint32_t good =
                item.gap < CopyTurnGapUnknown ? std::max(CopyTurnKeep, item.gap + 2) : CopyTurnKeep;
            *item.ticket = {frame + 1, good - 1, frames - 1};
            plan.back += item.triangles;
            slot += item.triangles;
        }
        // The copies drawn every frame share what the copies expected back on the next frame
        // leave of the budget (`room`). First the bound's share: of the moving copies, then of
        // those that do not move, the oldest get tickets until they hold it, so that the
        // copies of one age do not reach the bound together and are rebuilt on one frame (and
        // so that copies that do not move, which come of age together, do not take a whole
        // frame from the moving ones). The share goes past the budget only for a copy that is
        // at the bound or one frame from it: a frame whose budget is held by copies that came
        // back costs no more while the turns of the frames around it keep the bound. A copy at
        // the bound gets its ticket whatever the count. All tickets good on the next frame
        // hold two budgets at most, which is what Take honours: no ticket is handed out that
        // the draw would turn down.
        const std::uint32_t room = budget - std::min(next, budget);
        const auto hand = [&](const CopyTurnItem& item) {
            *item.ticket = {frame + 1, 0, 0};
            plan.steady += item.triangles;
        };
        for (const bool moving : {true, false}) {
            if (wait == 0) {
                break; // no bound, no share
            }
            std::uint64_t given = 0;
            for (const std::uint32_t i : steady) { // the oldest of a kind come first
                const CopyTurnItem& item = items[i];
                if (item.moving != moving) {
                    continue;
                }
                const std::uint64_t age = frame + 1 - std::min(item.built_frame, frame);
                if (given >= even[moving ? 1 : 0] && age < limit(moving)) {
                    break;
                }
                if (plan.steady >= room) {
                    if (age + 1 < limit(moving)) {
                        break;
                    }
                    if (std::uint64_t(next) + plan.steady + item.triangles > 2ull * budget) {
                        continue;
                    }
                    ++plan.past;
                    plan.past_triangles += item.triangles;
                }
                hand(item);
                given += item.triangles;
            }
        }
        // Then what is left of the budget, the greatest need first.
        for (const std::uint32_t i : steady) {
            if (plan.steady >= room) {
                break;
            }
            if (items[i].ticket->from == 0) {
                hand(items[i]);
            }
        }
        expected = plan.steady + next;
        next = 0;
        return plan;
    }

    /// The draw of a built copy on `frame`, `built` triangles of copies rebuilt on it so far:
    /// whether this one is rebuilt. Its ticket is used up either way (a holder that is then
    /// not rebuilt after all gets a new one by its age at the frame's end).
    bool Take(CopyTurnTicket& ticket, std::uint32_t triangles, std::uint64_t frame,
              std::uint32_t built, std::uint32_t budget) {
        const bool holder = ticket.Good(frame);
        if (holder && frame == ticket.from + ticket.due) {
            expected -= std::min(expected, triangles);
        }
        ticket = {};
        // A holder is stopped only by the safety net of two budgets; a copy without a ticket
        // may not take what the holders still to come were promised.
        return holder ? built < 2ull * budget : std::uint64_t(built) + expected < budget;
    }

    /// Turns are off (the rule of before): nothing is expected of the next frame.
    void Clear() {
        ahead.fill(0);
        expected = 0;
        planned = 0;
    }

    /// Triangles of the tickets counted on the running frame and not used yet.
    [[nodiscard]] std::uint32_t Expected() const noexcept {
        return expected;
    }

private:
    /// Triangles of the tickets of copies expected back, by frame (frame % size).
    std::array<std::uint32_t, 64> ahead{};
    std::vector<std::uint32_t> steady, back; ///< reused by Plan: its two orders of the items
    std::uint64_t planned = 0;        ///< the frame Plan last ended
    std::uint32_t expected = 0;
};
static_assert(CopyTurnAhead < 64 && CopyTurnKeep >= 2);

} // namespace Vulkan
