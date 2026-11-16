# r112e_hang-taken: FEATURE fix on top of r112d_hang-still-test.fixed (applied before it; r112, r112c,
# r112b, r116 and r116b are applied before it in the tree and are not touched by it: r116b's edits of
# bbport_wind_hang.h and vk_rasterizer_effects.cpp lie elsewhere, proved on a private copy with r116b
# applied and reverted). Behind r112's own knob BB_WIND_HANG=1 (off by default). With it off nothing of
# this runs: WindHangVerdict, the only function edited in the draw path, returns at its first line, the
# once-line and the groups line sit behind the knob, and the one new knob is read once inside code that
# only runs with BB_WIND_HANG=1.
#
# What b29 showed (slot_b29_result.txt, run with r112d built): r112's lines said "hang none", 40 of 40
# (graveyard) and 34 of 34 (alley) streams "moving", and no "Wind sway hang (r112d)" line was in the
# result. Why the line was missing: it was printed (it is in the same block as r112's lines, every
# 600 frames, and always comes out once) but the slot report keeps only the first 30 lines of the
# features under test, in the order the log wrote them (Test-BBFSSSlot.ps1: $featLines = ... -First 30),
# and each of the b29 jobs that carried it (none, alley1, grave1) had exactly 30 feature lines before it
# (counted again by r112e's check: 30 feature lines in each, none after the 30th); the knob-off twin,
# with no hang lines, had 26. The "full session logs" b29_s1_grave1.log and b29_s3_alley1.log are not
# those jobs' logs either: slots s1 and s3 ran a second job (r116b-di20, r116b-lt1) that overwrote
# session.log; they hold BB_WIND_SPEED 1.5 and no hang lines. So the r112d judging code did run; what
# the b29 numbers say is that nothing could be taken, for these reasons:
#  - 22 of 30 (graveyard) and 14 of 27 (alley) palettes are unreadable (the GPU wrote their page): the
#    28, 48 and 84 bone groups. The probe's "unreadable on 22" stood also with BB_GPU_WRITES_IN_PLACE=1
#    (grave1 had it): in place does not make them readable, so the cause of the refusal is not known
#    yet (r112d's groups line, now named per reason, was meant to say; the cap cut it).
#  - the readable ones are the hunter (277 bones), skin B (128 bones, character-sized for r112d) and
#    69 bone bodies that move.
#  - a stream settled as moving, or as unread, stayed so for good (r112's Settled shortcut and r112d's
#    Never): nothing was ever judged again.
#
# The fix:
#  1. Judged afresh (BbWindHangStill::Book::Due, called where r112's Settled shortcut returns true): a
#     stream settled as moving, or as unread for a reason that may pass (gpu, unmapped, short, nopal,
#     pivot), is judged again RejudgeFrames (300 frames) after it was settled, with a new first frame, in
#     both books (r112's entry is cleared with it). Not: a stream of more than 96 bones (character-sized)
#     and a stream whose first deviation was BigDeviation (20) tolerances or more (a bone turning 0.02:
#     a character's animation, never a held pose). Streams settled by their height (still content) are
#     not judged again. Cost: one lookup per draw of a settled stream; a judged-again stream costs two
#     content tests per 300 frames while it moves.
#  2. BB_WIND_HANG_READ_GPU=1 (a TEST setting, off by default, README row): a palette the buffer cache says
#     the GPU wrote, not bound in place, is read from guest memory (mapped and long enough) and judged by
#     its content. The CPU copy may be stale: the groups line counts these reads ("forced") and shows a
#     deviation for groups whose bytes live (moving, dev above 0), or none (a stale copy: every group
#     still, no deviation, to be distrusted). This is how the next run tells whether the 28/48/84 bone
#     palettes carry live bytes.
#  3. The log: a once-line (Wind sway hang (r112e): ...) and, every 600 frames, the groups line with the
#     totals first (hang, wait, height, moving, unread, char; in place, forced, judged again, not kept) and
#     then the groups by bone count, the ones with a stream that may hang first, each with its classes
#     and, for unread palettes, the reason (gpu, unmapped, short, nopal, pivot); under 300 characters
#     (the slot report cuts at 300; the line is cut at 296 with "..."). It comes every window now, not
#     only when it changes. Read the slot's own session.log, not the slot report, if the report's cap
#     (30 feature lines) hides it again: copy <slots>/sN/logs/session.log before the slot's next job.
#
# Not done: the "bottom free" test (no ground under the lowest vertex): a still standing figure 0.8 to 4
# m tall that passes the content test would lean at its lower part (README says so); streams with several
# instances in different poses compare each draw with the first one (one instance's pose differing from
# the first draw's moves the stream for 300 frames).
#
# Files: edits to engine/gpu/shim/bbport_wind_hang_still.h and engine/tests/test_wind_hang_still.cpp
# (r112d's), vk_rasterizer_effects.cpp (WindHangVerdict's Settled shortcut and palette reader, one
# once-line) and README.md (one row). No new file, no shader, no CMake or build.sh line, no vk_rasterizer.h
# line (the test is built and run by r112d's lines).
#
# Review (r112e fixed): Due refuses a stream of more than CharacterBones bones that was unread (the
# palette==nullptr test comes before the bone count in Judge, so it was judged again every 300
# frames although the rule says never), and a stream it does not know while its book is full (it
# was cleared and refused again on every draw, counting 'not kept' per draw).
# Use: python -I -X utf8 r112e_hang-taken.py check | apply | revert
# Root: R112E_ROOT, else <tree>. CRLF kept. apply backs the originals up in r112e_backup next to
# this script; revert takes out exactly what apply put in.
import os, sys

ROOT = os.environ.get("R112E_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112e_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RE = RV + "vk_rasterizer_effects.cpp"
NH = "engine/gpu/shim/bbport_wind_hang_still.h"
NT = "engine/tests/test_wind_hang_still.cpp"
RM = "README.md"

README_ROW = (
    "| `BB_WIND_HANG_READ_GPU` | A TEST setting for `BB_WIND_HANG` (off by default; `1` turns it on; it "
    "does nothing without `BB_WIND_HANG=1`): bone palettes that the buffer cache says the GPU wrote and "
    "that are not bound in place are read from guest memory all the same and judged by their content "
    "like the others. Without it such a palette is not read (the CPU copy of what the GPU wrote may be "
    "stale) and its stream is never taken; with it a stale copy that never changes would pass for a "
    "still one, so use it to look (the `Wind sway hang (r112e)` line counts these reads as `forced`, and "
    "a group whose bytes live shows a deviation) and not to play. `BB_WIND_HANG` itself judges "
    "a palette by its content (within 0.001 of its first frame, taken relative to a pivot bone, so a "
    "moving camera or palette ring changes nothing), not by a hash of its bytes; a stream that moved a "
    "little or whose palette could not be read is judged again every 300 frames (not one that turned a "
    "bone by 0.02 or more, nor one of more than 96 bones: characters); the `Wind sway hang (r112e)` line "
    "comes every 600 frames with the totals (hang, wait, height, moving, unread, char) and the groups by "
    "bone count, with the reason each unread palette was refused (gpu, unmapped, short, nopal, pivot), "
    "and is under 300 characters. Cost: nothing with `BB_WIND_HANG` unset; on, a lookup per draw of a "
    "settled sun-shadowed skinned stream and a content test per draw of a stream being judged. |\n"
)

OLD_SETTLED = r'''    if (hang_book.Settled(positions, positions_size, frame)) {
        ++hang_stats.settled;
        return false;
    }
'''

NEW_SETTLED = r'''    if (hang_book.Settled(positions, positions_size, frame)) {
        // bbport (r112e_hang-taken): a stream settled as moving or as unread is judged afresh after
        // RejudgeFrames, in both books, unless it moved far (a character) or has too many bones
        if (!hang_still.Due(positions, frame)) {
            ++hang_stats.settled;
            return false;
        }
        if (BbWindHang::Entry* const settled = hang_book.Find(positions)) {
            *settled = BbWindHang::Entry{};
        }
    }
'''

OLD_FLAGS = r'''    bool in_place = false;
    BbWindHangStill::Why why = BbWindHangStill::Why::None;
'''

NEW_FLAGS = r'''    bool in_place = false;
    bool forced = false; // bbport (r112e_hang-taken): read although the GPU wrote its page
    BbWindHangStill::Why why = BbWindHangStill::Why::None;
'''

OLD_GPU = r'''        in_place = gpu && buffer_cache.IsInPlace(buffer.base_address, size);
        if (gpu && !in_place) {
            why = BbWindHangStill::Why::GpuWritten;
'''

NEW_GPU = r'''        in_place = gpu && buffer_cache.IsInPlace(buffer.base_address, size);
        // bbport (r112e_hang-taken): BB_WIND_HANG_READ_GPU=1 (a test setting) reads it all the same
        forced = gpu && !in_place && BbWindHangStill::ReadFlagged();
        if (gpu && !in_place && !forced) {
            why = BbWindHangStill::Why::GpuWritten;
'''

OLD_JUDGE = r'''    const bool still = hang_still.Judge(positions, palette_size, palette, why, in_place, frame) ==
                       BbWindHangStill::Result::Same;
'''

NEW_JUDGE = r'''    const bool still = hang_still.Judge(positions, palette_size, palette, why, in_place, frame,
                                        forced) == BbWindHangStill::Result::Same;
'''

ONCE_BLOCK = r'''    // bbport (r112e_hang-taken): its line once (BB_WIND_HANG on)
    static bool hang_taken_said = false;
    if (!hang_taken_said && BbWindHang::KnobOnce().on) {
        hang_taken_said = true;
        BbReport::Printf("Wind sway hang (r112e): palettes judged by content (0.001 of the first "
                         "frame), moved or unread streams judged afresh every %u frames, over %u "
                         "bones never; palettes the GPU wrote, not in place: %s; groups line every "
                         "%u frames\n",
                         static_cast<unsigned>(BbWindHangStill::RejudgeFrames),
                         BbWindHangStill::CharacterBones,
                         BbWindHangStill::ReadFlagged() ? "read anyway (BB_WIND_HANG_READ_GPU=1)"
                                                        : "not read",
                         BbWindSway::ReportFrames);
    }
'''

EDITS = {
RE: [
("rep", OLD_SETTLED, "", NEW_SETTLED),
("rep", OLD_FLAGS, "", NEW_FLAGS),
("rep", OLD_GPU, "", NEW_GPU),
("rep", OLD_JUDGE, "", NEW_JUDGE),
("ins", "    if (!on || ++sway_frames % BbWindSway::ReportFrames != 0) {\n", ONCE_BLOCK, ""),
],
NH: [
    ("rep", r'''// is unchanged: BbWindHang::Book keeps the frames and the height; this file only says whether a
// frame's palette is the same one. Report names the groups (by bone count) taken and skipped.
// Pure: no Vulkan; tested by tests/test_wind_hang_still.cpp.
''', "", r'''// is unchanged: BbWindHang::Book keeps the frames and the height; this file only says whether a
// frame's palette is the same one. Report names the groups (by bone count) taken and skipped.
// bbport (r112e_hang-taken): (1) a stream settled as moving or as unread (a reason that may pass)
// is judged afresh after RejudgeFrames (Due), unless it went BigDeviation tolerances (a character);
// (2) BB_WIND_HANG_READ_GPU=1 (TEST) reads palettes the buffer cache calls GPU-written too
// (ReadFlagged);
// (3) the groups line comes every window, under 300 characters, totals first (Report).
// Pure: no Vulkan; tested by tests/test_wind_hang_still.cpp.
'''),
    ("rep", r'''#include <cstdint>
#include <cstdio>
#include <cstring>
#include <functional>''', "", r'''#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>'''),
    ("rep", r'''inline constexpr std::uint64_t SeenFrames = BbWindHang::BookKeep; ///< listed if drawn this recently
inline constexpr std::size_t GroupsMost = 12;       ///< groups the line names at most
inline constexpr std::size_t LineMost = 380;        ///< characters of the groups line, about

/// A 3x4 matrix, row major (row r at r * 4), the fourth row 0 0 0 1.''', "", r'''inline constexpr std::uint64_t SeenFrames = BbWindHang::BookKeep; ///< listed if drawn this recently
inline constexpr std::size_t GroupsMost = 12;       ///< groups the line names at most
inline constexpr std::size_t LineMost = 200;        ///< no group is added to a line this long
inline constexpr std::size_t LineChars = 296;       ///< the line's end: the slot report keeps 300
// bbport (r112e_hang-taken): a stream settled as moving, or as unread for a reason that may pass,
// is judged afresh RejudgeFrames after (a new first frame): a pose the game held for a moment, a
// palette in flight when it was first asked, a ring that moved. One that went BigDeviation
// tolerances from its first frame (2 cm or 0.02 in a bone: a character's animation, not a held
// pose) is a mover for good, as are the streams of more than CharacterBones bones.
inline constexpr std::uint64_t RejudgeFrames = 300;
inline constexpr double BigDeviation = 20.0;

/// BB_WIND_HANG_READ_GPU=1 (a TEST setting, off by default): a palette the buffer cache says
/// the GPU wrote and that is not bound in place is read from guest memory all the same (mapped
/// and long enough), and judged by its content like any other. The CPU copy of such a palette
/// may be stale (a stale copy that never changes would pass for a still one): the groups line
/// counts those reads ("forced") so the test says whether their bytes live (moving groups with a
/// deviation) or not (every group still, deviation 0).
[[nodiscard]] inline bool ReadFlagged() {
    static const bool on = [] {
        const char* v = std::getenv("BB_WIND_HANG_READ_GPU");
        return v != nullptr && v[0] == '1' && v[1] == 0;
    }();
    return on;
}

/// A 3x4 matrix, row major (row r at r * 4), the fourth row 0 0 0 1.'''),
    ("rep", r'''    bool moved = false;
    bool in_place = false; ///< its palette was read from a page the GPU writes, bound in place
    Why never = Why::None;
    double worst_a = 0.0, worst_b = 0.0; ///< greatest difference from `ref`, in tolerances''', "", r'''    bool moved = false;
    bool in_place = false; ///< its palette was read from a page the GPU writes, bound in place
    bool forced = false;   ///< (BB_WIND_HANG_READ_GPU) read from a GPU-written page, not in place
    std::uint64_t settled = 0; ///< the frame it was settled as moving or unread (Due)
    std::uint32_t again = 0;   ///< times it was judged afresh (Due)
    Why never = Why::None;
    double worst_a = 0.0, worst_b = 0.0; ///< greatest difference from `ref`, in tolerances'''),
    ("rep", r'''    /// A skinned draw of `stream` on `frame`: `palette` its bone palette's bytes (null: not
    /// readable, `why` says why), `size` their number, `in_place` it was read from a GPU-written
    /// page bound in place. Same: this frame's palette is the first one's.
    Result Judge(std::uint64_t stream, std::uint32_t size, const unsigned char* palette, Why why,
                 bool in_place, std::uint64_t frame) {
        if (stream == 0) {
            return Result::Same; // BbWindHang::Book::Note ignores it too''', "", r'''    /// A skinned draw of `stream` on `frame`: `palette` its bone palette's bytes (null: not
    /// readable, `why` says why), `size` their number, `in_place` it was read from a GPU-written
    /// page bound in place, `forced` (BB_WIND_HANG_READ_GPU) from one that is not. Same: this
    /// frame's palette is the first one's.
    Result Judge(std::uint64_t stream, std::uint32_t size, const unsigned char* palette, Why why,
                 bool in_place, std::uint64_t frame, bool forced = false) {
        if (stream == 0) {
            return Result::Same; // BbWindHang::Book::Note ignores it too'''),
    ("rep", r'''        if (e.bones == 0) {
            e.never = Why::NoPalette;
            return Result::Never;
        }
        if (palette == nullptr) { // first: the log should say why a big palette was not read too
            e.never = why == Why::None ? Why::NoPalette : why;
            e.ref = Shape{};
            return Result::Never;''', "", r'''        if (e.bones == 0) {
            e.never = Why::NoPalette;
            e.settled = frame;
            return Result::Never;
        }
        if (palette == nullptr) { // first: the log should say why a big palette was not read too
            e.never = why == Why::None ? Why::NoPalette : why;
            e.settled = frame;
            e.ref = Shape{};
            return Result::Never;'''),
    ("rep", r'''        if (e.bones > CharacterBones) {
            e.never = Why::Character;
            e.ref = Shape{};
            return Result::Never;
        }
        e.in_place = e.in_place || in_place;
        if (!e.have) {
            if (!MakeShape(palette, e.bones, e.ref)) {
                e.never = Why::NoPivot;
                return Result::Never;
            }''', "", r'''        if (e.bones > CharacterBones) {
            e.never = Why::Character;
            e.settled = frame;
            e.ref = Shape{};
            return Result::Never;
        }
        e.in_place = e.in_place || in_place;
        e.forced = e.forced || forced;
        if (!e.have) {
            if (!MakeShape(palette, e.bones, e.ref)) {
                e.never = Why::NoPivot;
                e.settled = frame;
                return Result::Never;
            }'''),
    ("rep", r'''        if (!MakeShape(palette, e.bones, now)) {
            e.never = Why::NoPivot;
            e.ref = Shape{};
            return Result::Never;''', "", r'''        if (!MakeShape(palette, e.bones, now)) {
            e.never = Why::NoPivot;
            e.settled = frame;
            e.ref = Shape{};
            return Result::Never;'''),
    ("rep", r'''        if (!e.a_alive && !e.b_alive) {
            e.moved = true;
            e.ref = Shape{};
            return Result::Moved;
        }
        return Result::Same;
    }
''', "", r'''        if (!e.a_alive && !e.b_alive) {
            e.moved = true;
            e.settled = frame;
            e.ref = Shape{};
            return Result::Moved;
        }
        return Result::Same;
    }

    /// Asked for a stream the height book (BbWindHang::Book) holds as settled (moving, or out of
    /// height): true when its judgement starts afresh now (the caller then clears the height
    /// book's entry too). That is so for a stream settled here as moving, or as unread for a
    /// reason that may pass (not Character), at least RejudgeFrames ago, unless it went
    /// BigDeviation tolerances from its first frame (a character's animation: for good), nor one
    /// of more than CharacterBones bones; also for a stream not known here while the book has room
    /// (the book forgot it: nothing says it moves; full, Judge would refuse it on every draw and
    /// count it as not kept each time). The stream counts as
    /// seen. False: the verdict stands (a stream settled by its height, whose content is still,
    /// is not judged again).
    bool Due(std::uint64_t stream, std::uint64_t frame) {
        const auto found = entries.find(stream);
        if (found == entries.end()) {
            return entries.size() < StreamsMost;
        }
        Entry& e = found->second;
        e.seen = frame;
        const bool unread = e.never != Why::None && e.never != Why::Character;
        if (!(e.moved || unread) || e.bones > CharacterBones ||
            e.settled + RejudgeFrames > frame) {
            return false;
        }
        if (e.moved && std::min(e.worst_a, e.worst_b) >= BigDeviation) {
            return false;
        }
        Entry fresh;
        fresh.size = e.size;
        fresh.bones = e.bones;
        fresh.again = e.again + 1;
        fresh.in_place = e.in_place;
        fresh.forced = e.forced;
        fresh.seen = frame;
        e = std::move(fresh);
        ++rejudged;
        return true;
    }

    [[nodiscard]] std::uint64_t Rejudged() const {
        return rejudged;
    }
'''),
    ("rep", r'''    }

    /// The groups line (by bone count, most bones first; every stream drawn within SeenFrames of
    /// `frame`): per group the streams in each class, using `heights` (the height book of r112,
    /// by the same stream) for the streams whose content stayed still:
    ///   hang = taken (still, 0.8-4 m, or its height is being measured), wait = still for fewer
    ///   than StillFrames frames, height = still but outside 0.8-4 m, moving = the content moved
    ///   (dev: the least of the two forms' greatest differences, in tolerances),
    ///   gpu / unmapped / short / nopal / pivot = no content test (Why), char = over CharacterBones
    /// True (and `out` set) when the line differs from the last one reported: one line per run once
    /// the groups are known. At most GroupsMost groups are named.
    bool Report(BbWindHang::Book& heights, std::uint64_t frame, std::string& out) {
        struct Group {''', "", r'''    }

    /// The groups line, every 600 frames (r112e: every window, not only when it changes): the
    /// streams drawn within SeenFrames of `frame`, in totals and then by bone count (most bones
    /// first, groups of nothing but character-sized streams left out: they count under `char`),
    /// using `heights` (the height book of r112, by the same stream) for the streams whose
    /// content stayed still:
    ///   hang = taken (still, 0.8-4 m, or its height is being measured), wait = still for fewer
    ///   than StillFrames frames, height = still but outside 0.8-4 m, moving = the content moved
    ///   (dev: the least of the two forms' greatest differences, in tolerances),
    ///   gpu / unmapped / short / nopal / pivot = no content test (Why), char = over CharacterBones
    /// and the totals: read in place, read though GPU-written (forced, BB_WIND_HANG_READ_GPU),
    /// judged again (Due), not kept. The text is at most LineChars characters (the slot report
    /// keeps 300). True (and `out` set) always: the caller prints it.
    bool Report(BbWindHang::Book& heights, std::uint64_t frame, std::string& out) {
        struct Group {'''),
    ("rep", r'''        };
        std::map<std::uint32_t, Group, std::greater<std::uint32_t>> groups;
        unsigned in_place = 0, listed = 0;
        for (const auto& item : entries) {
            const Entry& e = item.second;''', "", r'''        };
        std::map<std::uint32_t, Group, std::greater<std::uint32_t>> groups;
        unsigned in_place = 0, forced = 0, listed = 0, again = 0;
        unsigned hang = 0, wait = 0, height = 0, moving = 0, unread = 0, chars = 0;
        for (const auto& item : entries) {
            const Entry& e = item.second;'''),
    ("rep", r'''            ++listed;
            in_place += e.in_place ? 1u : 0u;
            Group& g = groups[e.bones];
            ++g.streams;
            if (e.never != Why::None) {
                ++g.never[std::size_t(e.never)];
            } else if (e.moved) {
                ++g.moving;
                g.dev = std::max(g.dev, std::min(e.worst_a, e.worst_b));
            } else {
                switch (h == nullptr ? BbWindHang::Verdict::Waiting : BbWindHang::VerdictOf(*h)) {
                case BbWindHang::Verdict::Still:
                    if (h->judged && !h->fits) {
                        ++g.height;
                    } else {
                        ++g.hang;
                    }
                    break;
                case BbWindHang::Verdict::Unfit:
                    ++g.height;
                    break;
                case BbWindHang::Verdict::Moving:
                    ++g.moving;
                    break;
                case BbWindHang::Verdict::Waiting:
                    ++g.wait;
                    break;
                }
            }
        }
        char buf[200];
        std::snprintf(buf, sizeof(buf),
                      "Wind sway hang (r112d): %u sun-shadowed skinned streams by bones "
                      "(%u palettes read in place, %llu not kept)",
                      listed, in_place, static_cast<unsigned long long>(overflow));
        std::string text = buf;
        std::size_t shown = 0;
        for (const auto& item : groups) {
            if (shown == GroupsMost || text.size() > LineMost) {
                std::snprintf(buf, sizeof(buf), "; +%zu groups", groups.size() - shown);
                text += buf;
                break;''', "", r'''            ++listed;
            in_place += e.in_place ? 1u : 0u;
            forced += e.forced ? 1u : 0u;
            again += e.again != 0 ? 1u : 0u;
            if (e.never == Why::Character) {
                ++chars;
                continue;
            }
            Group& g = groups[e.bones];
            ++g.streams;
            if (e.never != Why::None) {
                ++g.never[std::size_t(e.never)];
                ++unread;
            } else if (e.moved) {
                ++g.moving;
                ++moving;
                g.dev = std::max(g.dev, std::min(e.worst_a, e.worst_b));
            } else {
                switch (h == nullptr ? BbWindHang::Verdict::Waiting : BbWindHang::VerdictOf(*h)) {
                case BbWindHang::Verdict::Still:
                    ++g.hang;
                    ++hang;
                    break;
                case BbWindHang::Verdict::Unfit:
                    ++g.height;
                    ++height;
                    break;
                case BbWindHang::Verdict::Moving:
                    ++g.moving;
                    ++moving;
                    break;
                case BbWindHang::Verdict::Waiting:
                    ++g.wait;
                    ++wait;
                    break;
                }
            }
        }
        char buf[300];
        std::snprintf(buf, sizeof(buf),
                      "Wind sway hang (r112e): %u sun-drawn skinned: %u hang %u wait %u height %u "
                      "moving %u unread %u char; in place %u, forced %u, judged again %u (%llux), "
                      "not kept %llu; bones",
                      listed, hang, wait, height, moving, unread, chars, in_place, forced, again,
                      static_cast<unsigned long long>(rejudged),
                      static_cast<unsigned long long>(overflow));
        std::string text = buf;
        // the groups with a stream that may hang first, then by bones, most first
        std::vector<std::pair<std::uint32_t, Group>> order(groups.begin(), groups.end());
        const auto candidates = [](const Group& g) { return g.hang + g.wait + g.height; };
        std::stable_sort(order.begin(), order.end(), [&](const auto& x, const auto& y) {
            return candidates(x.second) != 0 && candidates(y.second) == 0;
        });
        std::size_t shown = 0;
        for (const auto& item : order) {
            if (shown == GroupsMost || text.size() > LineMost) {
                std::snprintf(buf, sizeof(buf), "; +%zu groups", order.size() - shown);
                text += buf;
                break;'''),
    ("rep", r'''            }
        }
        if (text == last_line) {
            return false;
        }
        last_line = text;
        out = std::move(text);
        return true;''', "", r'''            }
        }
        if (text.size() > LineChars) {
            text.resize(LineChars - 3);
            text += "...";
        }
        out = std::move(text);
        return true;'''),
    ("rep", r'''
    std::unordered_map<std::uint64_t, Entry> entries;
    std::uint64_t overflow = 0;
    std::string last_line;
};
''', "", r'''
    std::unordered_map<std::uint64_t, Entry> entries;
    std::uint64_t overflow = 0, rejudged = 0;
};
'''),
],
NT: [
    ("rep", r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112d_hang-still-test): the content test of the hanging things' palettes (gpu/shim/
// bbport_wind_hang_still.h): shapes relative to the pivot, the tolerance, the book, the groups
// line.
// The twin in Python (r112d_twin.py) holds the same cases.
#include <algorithm>
#include <cmath>''', "", r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112d_hang-still-test, r112e_hang-taken): the content test of the hanging things'
// palettes (gpu/shim/bbport_wind_hang_still.h): shapes relative to the pivot, the tolerance, the
// book, the groups line, the judgement afresh (Due), the forced reads.
// The twin in Python (r112d_twin.py, r112e_twin.py) holds the same cases.
#include <algorithm>
#include <cmath>'''),
    ("rep", r'''               "full book: the unseen ones are forgotten");
    }
    // the groups line: groups by bones, the classes, once
    {
        S::Book book;''', "", r'''               "full book: the unseen ones are forgotten");
    }
    // the groups line: totals, then the groups with a stream that may hang, then by bones
    {
        S::Book book;'''),
    ("rep", r'''        const std::uint32_t size = std::uint32_t(bytes.size());
        for (std::uint64_t f = 0; f < 70; ++f) {
            // stream 10: still, 28 bones; 11: moving; 12: unreadable (84 bones); 13: 128 bones
            const auto r10 = book.Judge(10, size, bytes.data(), S::Why::None, true, f);
            heights.Note(10, 4096, 0, r10 == S::Result::Same, f, 1);''', "", r'''        const std::uint32_t size = std::uint32_t(bytes.size());
        for (std::uint64_t f = 0; f < 70; ++f) {
            // stream 10: still, 28 bones; 11: moving; 12: unreadable (84 bones); 13: 128 bones;
            // 14: still, 28 bones, read though GPU-written (forced)
            const auto r10 = book.Judge(10, size, bytes.data(), S::Why::None, true, f);
            heights.Note(10, 4096, 0, r10 == S::Result::Same, f, 1);'''),
    ("rep", r'''            book.Judge(12, 84 * S::BoneBytes, nullptr, S::Why::GpuWritten, false, f);
            book.Judge(13, 128 * S::BoneBytes, bytes.data(), S::Why::None, false, f);
        }
        std::string line;
        Expect(book.Report(heights, 70, line), "the groups line is reported");
        Expect(line.find("28b x2:") != std::string::npos, "groups: 28 bones, 2 streams");
        Expect(line.find(" hang=1") != std::string::npos, "groups: the still one hangs");
        Expect(line.find(" moving=1(dev ") != std::string::npos, "groups: the turning one moves");
        Expect(line.find("84b x1: gpu=1") != std::string::npos, "groups: 84 bones, gpu");
        Expect(line.find("128b x1: char=1") != std::string::npos, "groups: 128 bones, char");
        Expect(line.find("1 palettes read in place") != std::string::npos,
               "groups: in place count");
        Expect(line.find("; 128b x") < line.find("; 84b x") &&
                   line.find("; 84b x") < line.find("; 28b x"),
               "groups: most bones first");
        Expect(!book.Report(heights, 70, line), "the same line is not reported twice");
        Expect(line.size() < 400, "the line is short");
    }
    if (failures == 0) {''', "", r'''            book.Judge(12, 84 * S::BoneBytes, nullptr, S::Why::GpuWritten, false, f);
            book.Judge(13, 128 * S::BoneBytes, bytes.data(), S::Why::None, false, f);
            const auto r14 = book.Judge(14, size, bytes.data(), S::Why::None, false, f, true);
            heights.Note(14, 4096, 0, r14 == S::Result::Same, f, 1);
        }
        std::string line;
        Expect(book.Report(heights, 70, line), "the groups line is reported");
        Expect(line.find("28b x3:") != std::string::npos, "groups: 28 bones, 3 streams");
        Expect(line.find(" hang=2") != std::string::npos, "groups: the two still ones hang");
        Expect(line.find(" moving=1(dev ") != std::string::npos, "groups: the turning one moves");
        Expect(line.find("84b x1: gpu=1") != std::string::npos, "groups: 84 bones, gpu");
        Expect(line.find("128b") == std::string::npos,
               "groups: character-sized ones are not named");
        Expect(line.find(" 1 char;") != std::string::npos, "totals: 1 char");
        Expect(line.find(" 2 hang ") != std::string::npos, "totals: 2 hang");
        Expect(line.find("in place 1,") != std::string::npos, "totals: in place count");
        Expect(line.find("forced 1,") != std::string::npos, "totals: forced count");
        Expect(line.find("; 28b x") < line.find("; 84b x"), "groups: those that may hang first");
        Expect(line.find("Wind sway hang (r112e): 5 sun-drawn skinned:") == 0, "totals: listed");
        Expect(book.Report(heights, 70, line), "the line comes every window, also unchanged");
        Expect(line.size() <= S::LineChars, "the line is short");
        // many groups: the line stays under 300 characters and counts the rest
        S::Book many;
        BbWindHang::Book none;
        for (std::uint32_t bones = 3; bones < 3 + 40; ++bones) {
            const std::uint32_t big = bones * S::BoneBytes;
            many.Judge(1000 + bones, big, nullptr, S::Why::GpuWritten, false, 5);
            many.Judge(2000 + bones, big, nullptr, S::Why::NotMapped, false, 5);
        }
        Expect(many.Report(none, 6, line) && line.size() <= S::LineChars, "many groups: short");
        Expect(line.find("+") != std::string::npos, "many groups: the rest is counted");
    }
    // judged afresh: a held pose, an unread palette that passes; not a character, not big movers
    {
        S::Book book;
        const std::uint64_t again = S::RejudgeFrames;
        // moved by a small step (2 mm on a bone): afresh after RejudgeFrames, then still
        Judge(book, 1, base, 0);
        std::vector<S::Mat> held = base;
        held[5][3] += 2e-3;
        Expect(Judge(book, 1, held, 1) == S::Result::Moved, "a small step moves it");
        Expect(book.Find(1)->settled == 1, "moved: the frame it settled");
        Expect(!book.Due(1, 1 + again - 1), "not due before RejudgeFrames");
        Expect(book.Due(1, 1 + again), "due after RejudgeFrames (a small deviation)");
        Expect(book.Rejudged() == 1 && book.Find(1)->again == 1, "judged afresh once");
        Expect(!book.Find(1)->moved && !book.Find(1)->have, "afresh: a new first frame");
        Expect(Judge(book, 1, held, 1 + again) == S::Result::Same,
               "afresh: the held pose is the reference");
        Expect(Judge(book, 1, held, 2 + again) == S::Result::Same, "afresh: and it holds");
        Expect(!book.Due(1, 2 + again), "still: not due");
        // a character's animation (a bone turning a radian) is a mover for good
        Judge(book, 2, base, 0);
        std::vector<S::Mat> turned = base;
        turned[9] = RotZ(0.9, 0.0, 1.0, 0.0);
        Expect(Judge(book, 2, turned, 1) == S::Result::Moved, "a bone turning 1 rad moved");
        Expect(!book.Due(2, 1000000), "a big mover is never judged again");
        // unread (gpu): afresh after RejudgeFrames and read then
        book.Judge(3, 1344, nullptr, S::Why::GpuWritten, false, 10);
        Expect(!book.Due(3, 10 + again - 1) && book.Due(3, 10 + again), "unread: due later");
        Expect(Judge(book, 3, base, 10 + again) == S::Result::Same, "unread: read later, judged");
        // character-sized: never afresh
        Judge(book, 4, Bones(rng, 128), 0);
        Expect(!book.Due(4, 1000000), "character-sized: never due");
        // not known: due (the caller clears the height book's entry)
        Expect(book.Due(99, 5), "a stream the book does not know is due");
        // a still stream is not due
        Judge(book, 5, base, 0);
        Expect(!book.Due(5, 1000000), "a still stream is not due");
        // the forced flag is kept through a fresh start
        const auto bytes = Bytes(base);
        book.Judge(6, std::uint32_t(bytes.size()), bytes.data(), S::Why::None, false, 0, true);
        Expect(book.Find(6)->forced, "forced is noted");
        std::vector<S::Mat> shifted = base;
        shifted[3][3] += 3e-3;
        Judge(book, 6, shifted, 1);
        Expect(book.Due(6, 1 + again) && book.Find(6)->forced, "forced is kept when judged afresh");
    }
    if (failures == 0) {'''),
],
RM: [
("ins", "| `BB_WIND_HANG` | Hanging things lean with the wind", README_ROW, ""),
],
}

ORDER = (RE, NH, NT, RM)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def parts_of(ed):
    """(anchor-or-old, texts that must each be found exactly once when applied, texts that must be
    gone when applied)."""
    if ed[0] == "rep":
        return ed[1], [ed[3]], [ed[1]]
    return ed[1], [t for t in (ed[2], ed[3]) if t], []


def state_of(cur, eds, path):
    done = todo = 0
    for ed in eds:
        anchor, present, absent = parts_of(ed)
        if ed[0] == "rep":
            n_old, n_new = cur.count(anchor), cur.count(present[0])
            if n_new == 1 and n_old == 0:
                done += 1
            elif n_old == 1 and n_new == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times (wanted once), new text %d "
                                 "times: %r" % (path, n_old, n_new, anchor[:70]))
            continue
        na, counts = cur.count(anchor), [cur.count(t) for t in present]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s "
                             "times: %r" % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_edits(cur, eds):
    for ed in eds:
        if ed[0] == "rep":
            cur = cur.replace(ed[1], ed[3], 1)
        else:
            cur = cur.replace(ed[1], ed[2] + ed[1] + ed[3], 1)
    return cur


def revert_edits(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "rep":
            cur = cur.replace(ed[3], ed[1], 1)
        else:
            for part in (ed[3], ed[2]):
                if part:
                    cur = cur.replace(part, "", 1)
    return cur


def text_checks(texts):
    """The ties a compiler cannot check."""
    def need(path, want, n):
        if texts[path].count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" %
                             (path, want, texts[path].count(want), n))
    re_ = texts[RE]
    hh, tt = texts[NH], texts[NT]
    need(RE, "hang_still.Due(positions, frame)", 1)
    need(RE, "BbWindHangStill::ReadFlagged()", 2)
    need(RE, "frame,\n                                        forced) == BbWindHangStill::Result::Same;", 1)
    need(RE, "hang_still.Judge(positions, palette_size, palette, why, in_place, frame,", 1)
    need(RE, "hang_still.Report(hang_book, object_motion->Frame(), still_line)", 1)
    need(RE, "*settled = BbWindHang::Entry{};", 1)
    need(RE, "hang_taken_said", 3)
    # the judgement afresh sits inside WindHangVerdict, between r112's Settled shortcut and the
    # content test; the knob test is first
    a = re_.find("bool Rasterizer::WindHangVerdict(")
    k = re_.find("if (!BbWindHang::KnobOnce().on) {", a)
    s = re_.find("rt_shadow->SunSkinned(positions, positions_size)", a)
    t = re_.find("hang_book.Settled(positions, positions_size, frame)", a)
    d = re_.find("hang_still.Due(positions, frame)", a)
    f = re_.find("forced = gpu && !in_place && BbWindHangStill::ReadFlagged();", a)
    j = re_.find("hang_still.Judge(", a)
    n = re_.find("hang_book.Note(", a)
    e = re_.find("\n}\n", a)
    if not (0 <= a < k < s < t < d < f < j < n < e):
        raise SystemExit("text check: Due / the flagged read are not in order inside WindHangVerdict")
    # the once-line sits before the 600-frame test, behind the knob
    o = re_.find("hang_taken_said = true;")
    r = re_.find("if (!on || ++sway_frames % BbWindSway::ReportFrames != 0) {", o)
    if not (0 <= o < r):
        raise SystemExit("text check: the once-line is not before the report's frame test")
    for path in (RE,):
        for ed in EDITS[path]:
            for part in (ed[3:] if ed[0] == "rep" else ed[2:]):
                for line in part.split("\n"):
                    if len(line) > 100:
                        raise SystemExit("text check: %s: a new line over 100 columns: %r" %
                                         (path, line[:60]))
    for path in (NH, NT):
        for line in texts[path].split("\n"):
            if len(line) > 100:
                raise SystemExit("text check: %s: a line over 100 columns: %r" % (path, line[:60]))
        if not texts[path].isascii() or "\t" in texts[path] or "\r" in texts[path]:
            raise SystemExit("text check: %s is not plain ASCII without tabs" % path)
    for want in ("RejudgeFrames = 300;", "BigDeviation = 20.0;", "LineChars = 296;", "bool Due(",
                 "ReadFlagged()", "bool forced = false) {", "std::uint64_t overflow = 0, rejudged = 0;"):
        if want not in hh:
            raise SystemExit("text check: %r is missing in the header" % want)
    need(NH, "std::getenv(\"BB_WIND_HANG_READ_GPU\")", 1)
    need(NH, "#include <cstdlib>", 1)
    need(NH, "Wind sway hang (r112d)", 0)
    need(NH, "Wind sway hang (r112e): %u sun-drawn skinned", 1)
    if "S::Book" not in tt or "book.Due(" not in tt or "Rejudged()" not in tt:
        raise SystemExit("text check: the test does not hold the judgement afresh")
    need(NT, "return failures == 0 ? 0 : 1;", 1)
    # the README row
    if texts[RM].count("| `BB_WIND_HANG_READ_GPU` |") != 1:
        raise SystemExit("text check: README has not exactly one BB_WIND_HANG_READ_GPU row")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112E_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == RE and "hang_still.Judge(" not in cur:
            raise SystemExit("REFUSED: r112d_hang-still-test is not applied (no hang_still.Judge)")
        if path == NH and "namespace BbWindHangStill" not in cur:
            raise SystemExit("REFUSED: r112d_hang-still-test is not applied (no BbWindHangStill)")
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_edits(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits; text checks on the result "
                  "pass)" % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r112etmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_edits(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r112etmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


if __name__ == "__main__":
    main()
