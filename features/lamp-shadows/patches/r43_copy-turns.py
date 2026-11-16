# r43_copy-turns: the rebuilds of the ray tracing scene's shared copies take turns, so that no
# moving copy keeps an old pose (vk_rt_shadow.cpp/.h, a new header rt_copy_turns.h with its test,
# bbport_toggles.h, bbport_settings.h, gpu/CMakeLists.txt). check|apply|revert (revert restores
# byte for byte and removes the two new files). On top of r1..r42 (r42_lamp-soft applied). The
# tree is <tree>/ unless the environment variable R43_ROOT names another root (a copy).
# Nothing is changed in place: every new text is written beside its target and moved over it,
# and a failure puts back what was already moved. Source files keep their CRLF line ends. Every
# old text below is found exactly once when its turn comes, every new one exactly once on the
# way back.
#
# WHY. With ray traced lamp shadows on, the hand torch threw shadow lines on the ground that did
# not move. The game's log names the cause (one line every 600 frames): "shared copies drawn on
# the last frame: 24 of 16 meshes, 483781 triangles, 24 moving ... 16 (306953 triangles) rebuilt
# on it; rebuilt budget 300000 ... 8 moving copies starved of rebuilds ... built 6301 frames
# ago". A shared copy is one draw of a mesh that a pass draws more than once (the same body in
# every sun cascade). It has its own bottom-level structure with the vertices in world space,
# is known only by its place in the draw order and so cannot be refit: it is rebuilt, within a
# budget of 300,000 triangles a frame. That budget went to the copies in draw order and began
# again at nothing every frame. The draw order of a scene is the same every frame, so the same
# first copies were rebuilt every frame and the same last ones never: they stayed in the scene,
# and in lamp rays, in the pose of the frame they were first built on. Leaving them out of lamp
# rays (BB_LAMP_SHADOW_STALE=1) removes real shadows with them; the repair is that none starves.
#
# WHAT.
#  1. The copies take turns (rt_copy_turns.h, a header without Vulkan that the engine and the
#     test both run). At the end of every frame the built shared copies drawn on it are put in
#     the order of their need, the greatest first (equal ones in draw order), and are given
#     tickets for their next draw until the tickets hold the budget (the copy that crosses it
#     still gets one, as before). The need is the age the copy's build will have at that draw;
#     a copy that does not move (several of one prop: its build only goes wrong when the draw
#     order shifts) counts a quarter of its age, so the moving copies are not held up by them.
#     At a draw a copy with a ticket is rebuilt; one without is rebuilt only with what the
#     ticket holders still to come leave of the budget. Where all copies fit the budget every
#     one holds a ticket every frame: nothing changes there.
#     THE TRADE: where they do not fit, the copies the rule of before rebuilt on every frame
#     (the first 300,000 triangles in draw order) are now rebuilt every Nth frame like all the
#     others (every 2nd at the log's 484,000 to 545,000 triangles), for the sun's rays and the
#     sun VSM's world copies as for lamp rays. A shadow of a moving body can step at half the
#     frame rate there. BB_RT_COPY_BUDGET=500000 rebuilds every copy of that scene every frame
#     and shows what that costs.
#  2. The bound. Whatever the load, a moving copy that is drawn every frame is not drawn more
#     than BB_RT_COPY_WAIT (4) frames in a row without a rebuild, so its pose is never more
#     than 4 frames old; a copy that does not move waits four times as long at the most. Every
#     frame's tickets hold a fifth of the moving copies (and a twentieth of the others) before
#     anything else, the same number every frame, so that copies of one age do not come due
#     together. Up to five budgets of moving copies a frame (1.5 million triangles; the
#     heaviest spot measured so far holds 1.32 to 1.68 million of copies) that fits the budget.
#     It goes past the budget only for a copy at the bound or one frame from it (more than five
#     budgets of moving copies: 1.68 million need 336,000 a frame; or frames whose budget is
#     held by copies that came back). A frame's tickets never hold more than two budgets; where
#     that is not enough (past ten budgets of moving copies) the wait grows again.
#  3. Copies that are not drawn every frame. With graphics_sun_far_shadows the far sun cascades
#     are drawn every 2nd or 8th frame; their copies are drawn last, stay in the scene (and in
#     lamp rays) on the frames between, and starved as well. Such a copy gets a ticket that
#     lasts until its next draw (its last gap plus 2 frames, 18 at the least), and the frame it
#     is expected back on (its last gap later) hands that many triangles fewer to the copies
#     drawn every frame. It competes for that frame's budget by the same need: it gets the
#     ticket only while one budget has room for the tickets already given for that frame and
#     the copies drawn every frame that are as old as it will be (and the bound's share of
#     them, unless it comes back more rarely than the bound's frames or is twice as old as the
#     bound allows). So a cascade drawn every 8th frame is rebuilt each time it is drawn, and
#     with "alternate" (c3 on the even frames, c2 on the odd ones: far copies come back on
#     EVERY frame) the far copies take turns with the near ones and do not hold every frame's
#     budget. No more tickets are handed out for a frame than the draws honour (two budgets).
#     A copy drawn for the first time was built on that frame: it is the newest, takes its turn
#     with the copies drawn every frame and is not rebuilt again on the next frame at the cost
#     of older ones.
#  4. r41's "starved" flag (more than 2 draws in a row without a rebuild; with
#     BB_LAMP_SHADOW_STALE=1 such a copy is left out of lamp rays) follows the turns: with turns
#     on a moving copy counts as starved past BB_RT_COPY_WAIT draws in a row without a rebuild
#     (4; never fewer than r41's 2; with BB_RT_COPY_WAIT=0, no bound, past 16), which the turns
#     do not let happen up to two budgets a frame. It is no longer starved at the first rebuild
#     that came in time, that is after no more draws without one than that (r41 asked for three
#     rebuilds in a row, which a copy that takes turns never gets). So a copy whose turns come
#     too late every time stays starved between them and does not go in and out of lamp rays
#     at every turn (each change makes the top-level structure a full build).
#     BB_LAMP_SHADOW_STALE itself is as r42 left it: 0 keeps starved copies in lamp rays, 1
#     leaves them out. With the experiment bit set both rules are r41's.
#  5. Lifetime. Nothing new is created, freed or moved: a turn leads to the same rebuild every
#     refresh of a shared copy was (in place, recorded by RecordBuilds before the top-level
#     build of the frame that traces it). Tickets live in the entries. The list of the shared
#     copies drawn on a frame and the list the plan sorts point into entries only until the
#     plan's call at the frame's end, which empties both before the evictions (as frame_entries
#     does: no entry is destroyed during a frame).
#  6. Experiment 1152921504606846976 (bit 60, BbCopyTurns::OldBit in bbport_toggles.h) set = the
#     first copies in draw order take the budget, as before (read at every draw and every frame
#     end: A/B in one run through BB_TOGGLE_FILE). It is not one of
#     BbSettings::PreviousPathsBits: set brings the picture fault back.
#
# KNOBS (environment variables, read once at start; a value that is not a whole number leaves
# the default, one above the range counts as its end).
#   BB_RT_COPY_BUDGET  [300000]  0..4000000  triangles of shared copies rebuilt a frame (new;
#                                            the default is the constant of before). 0: none
#                                            are refreshed, as experiment 256. A tool to prove a
#                                            picture fault on the budget: far above what a
#                                            scene's copies hold, every copy is rebuilt on every
#                                            draw.
#   BB_RT_COPY_WAIT    [4]       0..16       the most frames in a row a moving copy drawn every
#                                            frame goes without a rebuild before its turn comes
#                                            past the budget (a copy that does not move: four
#                                            times that and three more). 0: never past the
#                                            budget (the wait is then what the budget gives).
#   BB_LAMP_SHADOW_STALE [0]     0|1         as r42: 1 leaves starved moving copies out of lamp
#                                            rays.
#
# LOG LINE. The 600-frame "Ray tracing: ... shared copies drawn on the last frame" line keeps its
# wording and gains, after "(oldest N frames)":
#   "; copies take turns: on (experiment 1152921504606846976 clear), the oldest build first;
#    worst age of a moving copy since the last line: A frames without a rebuild while drawn
#    every frame (the bound is 4, BB_RT_COPY_WAIT, kept while a frame's turns fit two budgets),
#    B draws in a row without one for a copy drawn again after frames undrawn; C copies a frame
#    were drawn again so; D turns (E triangles) went past the budget; oldest build of a copy
#    that does not move: F frames"
# and with the bit set: "copies take turns: off (experiment 1152921504606846976 set), the first
# in draw order as before r43; ... (no bound without turns) ...". What to read after the patch:
# "oldest" and A at 1 to 4 where they were 6,301, F below 20, and "0 moving copies starved of
# rebuilds".
#
# TEST. tests/test_rt_copy_turns.cpp (target rt-copy-turns-test in gpu/CMakeLists.txt, registered
# as lamp-shadow-tune-test is): frames of draws in a fixed order run through rt_copy_turns.h as
# RtShadow runs them. The log's 24 copies with the rule of before (the same 8 never rebuilt)
# and with turns (every copy at least every 2nd frame, within the budget plus one mesh); the far
# cascades' copies coming back every 8th frame, and on alternate frames as the game's schedule
# draws them (c3 even, c2 odd), at the log's sizes, at a million triangles of near copies and at
# 1.68 million; two cascades that come back on the same frames; moving copies beside copies that
# do not move (the per-frame maximum is asserted in each); copies that do not move beside far
# cascades of a budget each; new copies arriving; everything within the budget; 1.32 million
# triangles (within the bound and the budget); 2.4 and 4 million (past the budget, and past two
# budgets); BB_RT_COPY_WAIT=0; budget 0; a set of copies that changes; tickets and knobs.
#
# REVIEW (two reviewers, after the first version was in the tree). That version put the copies
# in one order by age, served the copies that came back first with a whole budget each plan, and
# handed out turns past the budget only to copies already at the bound. Found and changed here:
# far cascades on alternate frames held every frame's budget (near copies at the bound, frames
# of two budgets, copies that do not move never rebuilt); tickets of two plans for one frame
# passed what the draws honour and the last drawn were cut every time; copies at the bound came
# due together; copies that do not move took equal turns with moving ones; a copy built for the
# first time was rebuilt on the next frame before older ones; and the starved flag went on and
# off at every turn where the wait passed its limit.

import os
import sys

ROOT = os.environ.get("R43_ROOT", "<tree>/").replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
B = G + "shadps4/video_core/"
R = B + "renderer_vulkan/"
TESTS = E + "tests/"

TMP = ".r43tmp"  # a new text waits under this name beside its target (main)

# The two files this round adds (apply writes them with CRLF line ends, revert removes them if
# they are still as written here).
NEW_FILES = {
    R + "rt_copy_turns.h": r"""// SPDX-License-Identifier: GPL-3.0-or-later
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
""",
    TESTS + "test_rt_copy_turns.cpp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
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
""",
}

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old.
EDITS = {
    G + "shim/bbport_toggles.h": [
        (r"""    void Spend(std::uint64_t ns) {
        spent_ns += ns;
    }
};
} // namespace BbPendingOps
""",
         r"""    void Spend(std::uint64_t ns) {
        spent_ns += ns;
    }
};
} // namespace BbPendingOps

// bbport (r43_copy-turns): the rebuilds of the ray tracing scene's shared copies take turns, the
// oldest build first, moving copies four times as often as those that do not move (RtShadow,
// renderer_vulkan/rt_copy_turns.h).
namespace BbCopyTurns {
/// Experiment bit 60: set = the rebuild budget goes to the first copies in draw order, as
/// before (the same late copies are never rebuilt, keep the pose of their first build and cast
/// lamp shadows that do not move). Read at every draw and every frame end. Not bit 60 of the
/// other mask (BbToggle::CameraOwnInverse).
inline constexpr std::uint64_t OldBit = 1152921504606846976ull;
} // namespace BbCopyTurns
"""),
    ],
    G + "shim/bbport_settings.h": [
        (r"""// brings picture faults back (doubled and faint torch shadows).
inline constexpr int PreviousPathsBits[] = {5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20,
""",
         r"""// brings picture faults back (doubled and faint torch shadows).
// bbport (r43_copy-turns): nor is 60 (1152921504606846976; set = the rebuilds of shared ray
// tracing copies go to the first in draw order, bbport_toggles.h BbCopyTurns::OldBit), for the
// same reason: set brings lamp shadows that do not move back.
inline constexpr int PreviousPathsBits[] = {5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20,
"""),
    ],
    G + "CMakeLists.txt": [
        (r"""add_executable(lamp-shadow-tune-test EXCLUDE_FROM_ALL ../tests/test_lamp_shadow_tune.cpp)
target_compile_options(lamp-shadow-tune-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-shadow-tune-test PRIVATE ..)
""",
         r"""add_executable(lamp-shadow-tune-test EXCLUDE_FROM_ALL ../tests/test_lamp_shadow_tune.cpp)
target_compile_options(lamp-shadow-tune-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-shadow-tune-test PRIVATE ..)
# bbport (r43_copy-turns): the turns of the ray tracing scene's shared copies (rt_copy_turns.h)
add_executable(rt-copy-turns-test EXCLUDE_FROM_ALL ../tests/test_rt_copy_turns.cpp)
target_compile_options(rt-copy-turns-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rt-copy-turns-test PRIVATE ..)
"""),
    ],
    R + "vk_rt_shadow.h": [
        (r"""#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/renderer_vulkan/vk_sun_vsm.h"
""",
         r"""#include "common/types.h"
#include "video_core/renderer_vulkan/rt_copy_turns.h" // bbport (r43_copy-turns)
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/renderer_vulkan/vk_sun_vsm.h"
"""),
        (r"""        // bbport (r41_lamp-shadows): a moving shared copy (rebuilt and dynamic): draws in a row
        // that went without a rebuild (PrepareDraw's skip, up to LampStaleSkips + 1), rebuilds
        // in a row since it was left out, and whether lamp rays leave it out (PrepareScene).
        u8 lamp_skips = 0;
        u8 lamp_builds = 0;
        bool lamp_out = false;
    };
""",
         r"""        // bbport (r41_lamp-shadows): a moving shared copy (rebuilt and dynamic): draws in a row
        // that went without a rebuild (PrepareDraw's skip, up to one more than counts as
        // starved), rebuilds in a row since it was left out, and whether it is starved: with
        // BB_LAMP_SHADOW_STALE=1 lamp rays leave it out (PrepareScene).
        u8 lamp_skips = 0;
        u8 lamp_builds = 0;
        bool lamp_out = false;
        // bbport (r43_copy-turns): a shared copy's turn to be rebuilt (rt_copy_turns.h): the
        // ticket the end of a frame gave it for its next draw, and the frames from its draw
        // before to its last (1: drawn every frame; CopyTurnGapUnknown: never before, or long
        // ago). For a moving copy, the draws in a row without a rebuild: on frames in a row
        // (turn_run; it starts again at a draw after frames undrawn) and after frames undrawn
        // (turn_back_run). Both feed the 600-frame line only. turn_listed: it is in turn_drawn.
        CopyTurnTicket turn;
        u8 turn_gap = 1;
        bool turn_listed = false;
        u16 turn_run = 0;
        u16 turn_back_run = 0;
    };
"""),
        (r"""    u32 new_triangles = 0;
    u32 rebuilt_triangles = 0;
    u64 scratch_used = 0;
""",
         r"""    u32 new_triangles = 0;
    u32 rebuilt_triangles = 0;
    // bbport (r43_copy-turns): the turns of the shared copies. PrepareDraw takes them,
    // PlanCopyTurns hands them out at the end of a frame. turn_drawn: the shared copies drawn
    // on this frame, in draw order, each once (Entry::turn_listed); like frame_entries it holds
    // entries only until the frame's end, where PlanCopyTurns empties it before the evictions.
    // turn_items is filled and emptied inside PlanCopyTurns (it points into entries).
    // turn_stats, since the last 600-frame line: the most frames in a row a moving copy drawn
    // every frame went without a rebuild, the most draws in a row one drawn again after frames
    // undrawn did, draws of copies after frames undrawn, and the turns (and their triangles)
    // that went past the budget for the bound.
    CopyTurns copy_turns;
    std::vector<Entry*> turn_drawn;
    std::vector<CopyTurnItem> turn_items;
    void PlanCopyTurns();
    struct TurnStats {
        u64 back = 0, past = 0, past_triangles = 0;
        u32 worst_run = 0, worst_back_run = 0;
    } turn_stats;
    u64 scratch_used = 0;
"""),
    ],
    R + "vk_rt_shadow.cpp": [
        (r"""// holds the right pose and stays in. The sun's rays keep every copy, as before. Experiment
// LampRepairOffBit set: all stay in lamp rays (the counting goes on).
constexpr u32 LampStaleSkips = 2;
""",
         r"""// holds the right pose and stays in. The sun's rays keep every copy, as before. Experiment
// LampRepairOffBit set: all stay in lamp rays (the counting goes on).
// bbport (r43_copy-turns): "the same ones go without every frame" was the budget's first-come
// rule, and is repaired where it arose: the copies take turns (rt_copy_turns.h; CopyTurnsOn
// below), and a moving copy that is drawn every frame is rebuilt before it was drawn more than
// CopyWait() frames in a row without. With turns on a copy therefore counts as starved only
// past that many draws (LampStaleAfter), and no longer at the first rebuild that came in time
// (no more draws than that went without since the rebuild before): a copy that takes turns is
// never rebuilt on LampFreshBuilds draws in a row. One whose turns come too late every time
// (more copies than two budgets a frame keep within the bound) stays starved between them: it
// does not change sides at every turn, and neither does its instance's mask. With
// BB_RT_COPY_WAIT=0 no bound is asked for, and a copy counts as starved only past
// CopyTurnWaitMost draws. With BbCopyTurns::OldBit set both rules are as r41 made them.
constexpr u32 LampStaleSkips = 2;
"""),
        (r"""u32 RebuiltBudget() {
    return BbToggle::Experiment(256) ? 0u : RebuiltTrianglesPerFrame;
}
""",
         r"""// bbport (r43_copy-turns): BB_RT_COPY_BUDGET, read once: the triangles of shared copies rebuilt
// a frame (default RebuiltTrianglesPerFrame, at most CopyTurnBudgetMost; 0: none, as experiment
// 256). A tool to prove a picture fault on the budget: far above what a scene's copies hold,
// every copy is rebuilt on every draw.
u32 RebuiltBudget() {
    static const u32 budget = ReadCopyTurnKnob(std::getenv("BB_RT_COPY_BUDGET"),
                                               RebuiltTrianglesPerFrame, CopyTurnBudgetMost);
    return BbToggle::Experiment(256) ? 0u : budget;
}
// bbport (r43_copy-turns): experiment BbCopyTurns::OldBit clear = the shared copies take turns
// at being rebuilt, the oldest build first (rt_copy_turns.h); set = the first in draw order
// take the budget, as before. Read at each use.
bool CopyTurnsOn() {
    return !BbToggle::Experiment(BbCopyTurns::OldBit);
}
// BB_RT_COPY_WAIT, read once: the most frames in a row a moving copy that is drawn every frame
// goes without a rebuild; past that its turn comes whatever the budget says, up to two budgets
// a frame (default CopyTurnWait, 4; at most CopyTurnWaitMost; 0: no turn goes past the budget,
// and the wait is what the budget gives).
u32 CopyWait() {
    static const u32 wait =
        ReadCopyTurnKnob(std::getenv("BB_RT_COPY_WAIT"), CopyTurnWait, CopyTurnWaitMost);
    return wait;
}
// Draws in a row without a rebuild past which a moving copy counts as starved (LampStaleSkips).
// With turns on: the bound the turns keep, never fewer than r41's 2; with no bound asked for
// (BB_RT_COPY_WAIT=0, the wait is what the budget gives) the longest that can be asked for.
u32 LampStaleAfter() {
    if (!CopyTurnsOn()) {
        return LampStaleSkips;
    }
    return CopyWait() != 0 ? std::max(LampStaleSkips, CopyWait()) : CopyTurnWaitMost;
}
"""),
        (r"""    entry.rebuilt = entry.rebuilt || shared;
    if (entry.palette != draw.palette) {
""",
         r"""    entry.rebuilt = entry.rebuilt || shared;
    // bbport (r43_copy-turns): the frames since a shared copy's draw before (seen_frame is still
    // that draw's here): a copy that is not drawn every frame takes its turn another way. And
    // the copy is listed for the plan at the frame's end (PlanCopyTurns), once.
    if (entry.rebuilt) {
        entry.turn_gap = entry.seen_frame == 0
                             ? u8(CopyTurnGapUnknown)
                             : u8(std::min<u64>(frame - entry.seen_frame, CopyTurnGapUnknown));
        if (!entry.turn_listed) {
            entry.turn_listed = true;
            turn_drawn.push_back(&entry);
        }
    }
    if (entry.palette != draw.palette) {
"""),
        (r"""        if (entry.rebuilt && entry.dynamic) {
            entry.lamp_builds = 0;
            if (draw.inputs != 0 && draw.inputs == entry.r17_inputs) {
                entry.lamp_skips = 0; // the BLAS holds this very pose
                entry.lamp_out = false;
            } else if (entry.lamp_skips > LampStaleSkips || ++entry.lamp_skips > LampStaleSkips) {
                entry.lamp_out = true;
            }
        }
""",
         r"""        if (entry.rebuilt && entry.dynamic) {
            entry.lamp_builds = 0;
            const u32 stale_after = LampStaleAfter(); // bbport (r43_copy-turns)
            if (draw.inputs != 0 && draw.inputs == entry.r17_inputs) {
                entry.lamp_skips = 0; // the BLAS holds this very pose
                entry.lamp_out = false;
                entry.turn_run = entry.turn_back_run = 0;
            } else {
                if (entry.lamp_skips > stale_after || ++entry.lamp_skips > stale_after) {
                    entry.lamp_out = true;
                }
                // bbport (r43_copy-turns): for the 600-frame line, the wait the turns bound:
                // frames in a row without a rebuild while drawn every frame, and draws in a
                // row without one after frames undrawn.
                if (entry.turn_gap == 1) {
                    entry.turn_run += entry.turn_run != 0xffff ? 1 : 0;
                    turn_stats.worst_run = std::max<u32>(turn_stats.worst_run, entry.turn_run);
                } else {
                    entry.turn_run = 0;
                    entry.turn_back_run += entry.turn_back_run != 0xffff ? 1 : 0;
                    turn_stats.worst_back_run =
                        std::max<u32>(turn_stats.worst_back_run, entry.turn_back_run);
                }
            }
        }
"""),
        (r"""        const bool over = refresh ? rebuilt_triangles >= RebuiltBudget()
                                  : !update && !recapture && new_triangles >= NewTrianglesPerFrame;
""",
         r"""        // bbport (r43_copy-turns): a shared copy's refresh takes its turn. With a ticket of the
        // last frame's end (PlanCopyTurns) it is rebuilt; without one only with what the ticket
        // holders still to come leave of the budget. The ticket is used up here, whatever the
        // limits below say: a holder they cut gets a new one by its age. Experiment
        // BbCopyTurns::OldBit set: the first copies in draw order take the budget, as before.
        bool refresh_over = false;
        if (refresh) {
            const u32 budget = RebuiltBudget();
            refresh_over = CopyTurnsOn() ? !copy_turns.Take(entry.turn, entry.triangles, frame,
                                                            rebuilt_triangles, budget)
                                         : rebuilt_triangles >= budget;
            turn_stats.back += entry.turn_gap != 1 ? 1 : 0;
        }
        const bool over = refresh ? refresh_over
                                  : !update && !recapture && new_triangles >= NewTrianglesPerFrame;
"""),
        (r"""            // bbport (r41_lamp-shadows): rebuilt: back in lamp rays after LampFreshBuilds in a row
            entry.lamp_skips = 0;
            if (entry.lamp_out && ++entry.lamp_builds >= LampFreshBuilds) {
""",
         r"""            // bbport (r41_lamp-shadows): rebuilt: back in lamp rays after LampFreshBuilds in a row
            // bbport (r43_copy-turns): with turns on at the first rebuild that came in time: no
            // more draws went without since the rebuild before than count as starved. A copy
            // whose every turn comes too late stays starved (see LampStaleSkips).
            const bool in_time = entry.lamp_skips <= LampStaleAfter();
            entry.lamp_skips = 0;
            entry.turn_run = entry.turn_back_run = 0;
            if (entry.lamp_out &&
                (CopyTurnsOn() ? in_time : ++entry.lamp_builds >= LampFreshBuilds)) {
"""),
        (r"""void RtShadow::OnFrameEnd() {
    if (!capturing) {
        return;
    }
""",
         r"""// bbport (r43_copy-turns): the end of a frame hands out the turns of the next
// (rt_copy_turns.h): tickets for the built shared copies drawn on this frame, the oldest build
// first, so that no moving copy that is drawn every frame goes more than CopyWait() frames in a
// row without a rebuild. The tickets are kept in the entries themselves; turn_drawn and
// turn_items point into the entries only up to the end of this call, which runs before the
// frame end's evictions (no entry is destroyed during a frame). A turn leads to the rebuild
// every refresh of a shared copy is: in place, recorded by RecordBuilds before the top-level
// build of the frame that traces it (PrepareScene), nothing created or freed.
void RtShadow::PlanCopyTurns() {
    const bool on = CopyTurnsOn();
    turn_items.clear();
    for (Entry* entry : turn_drawn) {
        entry->turn_listed = false;
        // (Listed and then not drawn after all, not built yet, or promoted to an instance's
        // entry on this frame: no turn.)
        if (on && entry->rebuilt && entry->built && entry->seen_frame == frame) {
            turn_items.push_back({&entry->turn, entry->built_frame, entry->triangles,
                                  u32(entry->turn_gap), entry->dynamic});
        }
    }
    turn_drawn.clear();
    if (!on) {
        copy_turns.Clear();
        return;
    }
    const CopyTurnPlan plan = copy_turns.Plan(turn_items, frame, RebuiltBudget(), CopyWait());
    turn_items.clear();
    turn_stats.past += plan.past;
    turn_stats.past_triangles += plan.past_triangles;
}

void RtShadow::OnFrameEnd() {
    if (!capturing) {
        return;
    }
"""),
        (r"""        // bbport: what the shared entries are: copies of a mesh drawn more than once in a pass,
        // known by draw order and fully rebuilt every frame within RebuiltTrianglesPerFrame (see
        // PrepareDraw).
""",
         r"""        // bbport: what the shared entries are: copies of a mesh drawn more than once in a pass,
        // known by draw order and fully rebuilt within RebuiltBudget() triangles a frame, in turn
        // (r43_copy-turns; before, the first in draw order every frame; see PrepareDraw).
"""),
        (r"""        std::printf("Ray tracing: %.0f triangles refit a frame; shared copies drawn on the last "
""",
         r"""        // bbport (r43_copy-turns): whether the copies take turns, and the bound on the frames a
        // moving copy drawn every frame goes without a rebuild
        const bool turns = CopyTurnsOn();
        char turn_bound[96];
        if (turns && CopyWait() != 0) {
            std::snprintf(turn_bound, sizeof(turn_bound),
                          "the bound is %u, BB_RT_COPY_WAIT, kept while a frame's turns fit two "
                          "budgets",
                          CopyWait());
        } else {
            std::snprintf(turn_bound, sizeof(turn_bound), "%s",
                          turns ? "no bound: BB_RT_COPY_WAIT=0, the budget alone decides"
                                : "no bound without turns");
        }
        std::printf("Ray tracing: %.0f triangles refit a frame; shared copies drawn on the last "
"""),
        (r"""                    "%u; %llu left out of lamp rays (oldest %llu frames); %llu moving copies "
                    "starved of rebuilds, %s (BB_LAMP_SHADOW_STALE=%d)%s",
""",
         r"""                    "%u; %llu left out of lamp rays (oldest %llu frames); copies take turns: %s; "
                    "worst age of a moving copy since the last line: %u frames without a rebuild "
                    "while drawn every frame (%s), %u draws in a row without one for a copy drawn "
                    "again after frames undrawn; %.1f copies a frame were drawn again so; %llu "
                    "turns (%llu triangles) went past the budget; oldest build of a copy that "
                    "does not move: %llu frames; %llu moving copies "
                    "starved of rebuilds, %s (BB_LAMP_SHADOW_STALE=%d)%s",
"""),
        (r"""                    static_cast<unsigned long long>(shared_oldest),
                    static_cast<unsigned long long>(shared_starved),
""",
         r"""                    static_cast<unsigned long long>(shared_oldest),
                    turns ? "on (experiment 1152921504606846976 clear), the oldest build first"
                          : "off (experiment 1152921504606846976 set), the first in draw order as "
                            "before r43",
                    turn_stats.worst_run, turn_bound, turn_stats.worst_back_run,
                    double(turn_stats.back) / f,
                    static_cast<unsigned long long>(turn_stats.past),
                    static_cast<unsigned long long>(turn_stats.past_triangles),
                    static_cast<unsigned long long>(shared_oldest_still),
                    static_cast<unsigned long long>(shared_starved),
"""),
        (r"""            if (e->dynamic) { // bbport (r41_lamp-shadows)
                shared_oldest = std::max(shared_oldest, frame - e->built_frame);
""",
         r"""            // bbport (r43_copy-turns): the copies that do not move take turns too, four times
            // as slowly (CopyTurnStill): their oldest build, for the 600-frame line
            if (!e->dynamic) {
                shared_oldest_still = std::max(shared_oldest_still, frame - e->built_frame);
            }
            if (e->dynamic) { // bbport (r41_lamp-shadows)
                shared_oldest = std::max(shared_oldest, frame - e->built_frame);
"""),
        (r"""        u64 shared_no_lamp = 0, shared_oldest = 0;
""",
         r"""        u64 shared_no_lamp = 0, shared_oldest = 0;
        u64 shared_oldest_still = 0; // bbport (r43_copy-turns)
"""),
        (r"""        std::printf("\n");
        stats = {};
    }
""",
         r"""        std::printf("\n");
        stats = {};
        turn_stats = {}; // bbport (r43_copy-turns)
    }
"""),
        (r"""    UpdateHeld(); // bbport (r14_cascade_rt): before the evictions, which spare held entries
    ++frame;
""",
         r"""    // bbport (r43_copy-turns): the next frame's turns, while frame_entries still holds this
    // frame's entries and before the evictions below (no pointer to an entry is kept past it)
    PlanCopyTurns();
    UpdateHeld(); // bbport (r14_cascade_rt): before the evictions, which spare held entries
    ++frame;
"""),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text: the engine and the header agree on the
    turns' calls, the experiment bit is the one the task gave and is read where the budget is
    handed out and where the plan is made, the plan runs before the frame end's evictions, the
    600-frame line is still one line, and the C texts kept their line breaks."""
    ok = True
    scene = texts[R + "vk_rt_shadow.cpp"]
    head = texts[R + "vk_rt_shadow.h"]
    toggles = texts[G + "shim/bbport_toggles.h"]
    cmake = texts[G + "CMakeLists.txt"]
    turns = NEW_FILES[R + "rt_copy_turns.h"]
    test = NEW_FILES[TESTS + "test_rt_copy_turns.cpp"]
    if toggles.count("inline constexpr std::uint64_t OldBit = 1152921504606846976ull;") != 1 or \
            1152921504606846976 != 1 << 60 or scene.count("BbToggle::Experiment(BbCopyTurns::OldBit)") != 1:
        print("experiment 1152921504606846976 is not registered once in bbport_toggles.h and read in one place")
        ok = False
    if scene.count("copy_turns.Take(entry.turn, entry.triangles, frame,") != 1 or \
            scene.count("copy_turns.Plan(turn_items, frame, RebuiltBudget(), CopyWait())") != 1 or \
            "bool Take(CopyTurnTicket& ticket, std::uint32_t triangles, std::uint64_t frame," not in turns or \
            "CopyTurnPlan Plan(std::vector<CopyTurnItem>& items, std::uint64_t frame, std::uint32_t budget," not in turns:
        print("vk_rt_shadow.cpp and rt_copy_turns.h do not agree on the turns' calls")
        ok = False
    # Old rule kept word for word behind the bit; the new one in front of the limits it must
    # come before (the ticket is used up whatever they say).
    if scene.count(": rebuilt_triangles >= budget;") != 1 or \
            scene.index("copy_turns.Take(") > scene.index("if (positions_used + stored > MaxPositions"):
        print("the budget test is not where the patch put it")
        ok = False
    plan = scene.index("    PlanCopyTurns();")
    if scene.count("    PlanCopyTurns();") != 1 or scene.count("void RtShadow::PlanCopyTurns() {") != 1 or \
            not plan < scene.index("    UpdateHeld(); // bbport (r14_cascade_rt)") < scene.index("        std::erase_if(entries, [&](auto& item) {") or \
            scene.count("turn_items.clear();") != 2 or scene.count("turn_drawn.clear();") != 1 or \
            scene.count("turn_drawn.push_back(&entry);") != 1 or head.count("void PlanCopyTurns();") != 1 or \
            scene.index("    turn_drawn.clear();") > scene.index("        copy_turns.Clear();"):
        print("the plan should run once a frame end, before the evictions, and leave no pointer to an entry")
        ok = False
    if scene.count("CopyTurnsOn()") != 6 or scene.count("LampStaleAfter()") != 3 or \
            scene.count("LampStaleOut()") != 4:
        print("the turns' switch or the starved rule is not read where the patch reads it")
        ok = False
    if scene.count('std::printf("Ray tracing: %.0f triangles refit a frame; shared copies drawn on the last "') != 1 or \
            scene.count("copies take turns: %s; ") != 1 or scene.count("turn_stats = {};") != 1:
        print("the 600-frame line should stay one line with the turns in it")
        ok = False
    if 'std::printf("' + chr(92) + 'n");' not in scene or 'a frame; 4M: %u frames)' + chr(92) + 'n",' not in test or \
            "'" + chr(92) + "0'" not in turns:
        print("a C escape lost its backslash on the way into the script")
        ok = False
    if cmake.count("add_executable(rt-copy-turns-test EXCLUDE_FROM_ALL ../tests/test_rt_copy_turns.cpp)") != 1 or \
            '#include "video_core/renderer_vulkan/rt_copy_turns.h"' not in head or \
            '#include "gpu/shadps4/video_core/renderer_vulkan/rt_copy_turns.h"' not in test:
        print("the new header or its test is not registered")
        ok = False
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts, or None with the reason printed."""
    out = {}
    for path, pairs in EDITS.items():
        t = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in t else "\n"
        for old, new in (pairs if mode != "revert" else reversed(pairs)):
            a, b = (fix(old, nl), fix(new, nl)) if mode != "revert" else (fix(new, nl), fix(old, nl))
            n = t.count(a)
            if n != 1:
                if not quiet:
                    print("anchor found %d times (want 1) in %s: %a" % (n, path, a[:90]))
                return None
            t = t.replace(a, b)
        out[path] = t
    for path, text in NEW_FILES.items():
        there = os.path.exists(path)
        if mode != "revert" and there:
            if not quiet:
                print("%s is there already" % path)
            return None
        if mode == "revert":
            # Removed only as this script wrote it.
            if not there or open(path, encoding="utf-8", newline="").read() != fix(text, "\r\n"):
                if not quiet:
                    print("%s is not there as this script writes it" % path)
                return None
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r43_copy-turns.py check|apply|revert   (R43_ROOT names another tree)")
        return 2
    out = run(mode, quiet=(mode == "check"))
    if out is None:
        if mode == "check":
            if run("revert", quiet=True) is not None:
                print("already applied (revert would restore the tree)")
            else:
                run("check")  # says which anchor
            return 1
        return 1
    if mode == "check":
        print("anchors OK (applies cleanly)")
        return 0
    # Nothing is changed in place: every new text goes to a file beside its target first, then
    # each is moved over its target (one rename a file). If a step fails, what was already moved
    # is put back from the texts read at the start, so the tree is never left half patched.
    if mode == "apply":
        for path, text in NEW_FILES.items():
            out[path] = fix(text, "\r\n")
    before = {}
    for path in out:
        before[path] = open(path, "rb").read() if os.path.exists(path) else None
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path in out:
            os.replace(path + TMP, path)
            done.append(path)
        if mode == "revert":
            for path in NEW_FILES:
                before[path] = open(path, "rb").read()
                os.remove(path)
                done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            if before[path] is None:
                os.remove(path)
            else:
                with open(path, "wb") as f:
                    f.write(before[path])
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
