# (review: BoxBook::Read counts stats.reads, the line's "reads" was always 0; its test now exact)
# r112f_hang-gpu-judge: FEATURE fix on top of r112e_hang-taken.fixed (applied before it; r112, r112b,
# r112c, r112d, r116, r116b, r89d are applied before it in the tree and are not touched). Behind r112's
# own knob BB_WIND_HANG=1 (off by default). With it off nothing of this runs: WindHangVerdict, the only
# function of the draw path that learns a line, returns at its first line (the knob test), the two log
# lines sit behind the knob, the new knob BB_WIND_HANG_BOX_TOL is read once inside code that only runs
# with BB_WIND_HANG=1, and WindSwayWord's new test reads a member that only WindHangVerdict sets.
#
# Why five CPU-side tries failed (b33 logs): the bone palettes of the hanging candidates are written by the
# GPU (the buffer cache keeps them in VRAM: IsRegionGpuModified, not in place), so the CPU either cannot
# read them (gpu=, 84, 48, 28 bone groups) or reads a stale copy (the forced read: "pivot", "moving").
#
# The fix (no shader, no new buffer, no new draw call): judge the stillness where the bones are applied,
# on the GPU, with the keys r89d's shaders ALREADY keep. A sway word (any sway word: HangBit, TreeBit,
# plant) makes the vertex shader (both emitters) offer, for every vertex, the vertex's WORLD position
# (after skinning, clip position through the camera's inverse; the same value whoever wrote the palette)
# to its base slot's keys with an atomic minimum: lowest y (r89 BaseAt), highest y (r89c CrownAt) and,
# with BB_WIND_TWIGS on (the default with BB_WIND=1 and the lean), lowest and highest x and z (r89d
# TwigAt). These six numbers are the world box of the mesh. A still thing has a box that does not grow; a
# character, a body, an animal, cloth the game simulates has one that does. r89d already reads the keys
# twice, 60 frames apart, to tell trees; r112f does the same for the hanging candidates with a tolerance
# in millimetres.
#
#  1. WindHangVerdict (CPU, as before) finds a stream a candidate: sun-drawn (RtShadow::SunSkinned),
#     palette still or unread, 60 frames (Book::Note). New: the palette content test alone no longer
#     decides: a palette the CPU could not read (gpu / unmapped / short / pivot) used to settle the stream
#     as moving for good; with the box keys available (BbWindHangStill::BoxAvailable = BB_WIND_TWIGS on,
#     and the sway words exist) it counts as "no objection" (GpuJudgeable: at most 96 bones, never a
#     character, never "no palette bound"). A palette the CPU can read must still be still, as before.
#  2. The candidate is not taken yet: WindHangVerdict sets hang_judge and WindSwayWord, which has the
#     stream's base slot by then, calls BoxBook::Step. Step starts a window (the slot's keys back to
#     ResetKey, so the history of an earlier moving life does not count), the word is a hang word with a
#     ramp of 0 (no motion; the shaders offer the keys, the top key too) for JudgeFrames (8) frames,
#     then reads the six keys (the first read: the snapshot), 60 frames later again: the greatest change
#     of any of the six numbers is the deviation. At or under BoxTol (20 mm; BB_WIND_HANG_BOX_TOL, in mm,
#     2-200) the stream is "still" and goes on as r112's hanging thing (measure its height: 0.8-4 m, then
#     the ramp and the push); over it, it moved: the book entry is set to moving (no word any more). The
#     reference is the first read, so a drift is caught, and the keys only ever grow (cumulative
#     minimum), so noise cannot cancel a movement.
#  3. A hanging thing keeps being watched: every BoxCheckFrames (30) frames the keys are read again (one
#     read of six words); a box that grew by more than twice the tolerance sets the stream moving (it
#     stops being pushed at once).
#  4. Judged again: a stream the keys found moving by less than BoxFinal (0.25 m: a drifting thing, a
#     thing the game moved once) is judged again RejudgeFrames (300) frames later, with a new window
#     (Due, called from WindHangVerdict's settled test with r112e's Due); one that went 0.25 m or more is
#     a character for good (Final). A stream settled by its height (still, outside 0.8-4 m) is never
#     judged again (r112e's rule, now also for streams the GPU judged).
#
# Cost, estimated (nothing measured): CPU, per draw of a candidate stream one hash lookup (BoxBook), per
# stream 2 key reads (6 mapped words each) per judgement and one every 30 frames while it hangs, at most
# 256 streams, about 100 bytes each; GPU, none added to a draw that had no sway word; a candidate stream's
# draws get a sway word with ramp 0 for about 70 frames (the sway code of ~120 ALU ops and 8 loads per
# vertex, with the twig box keys the shaders offer anyway for every sway word), then, if it hangs, what
# r112 already costs; no buffer, no copy, no barrier; memory 0 (the keys exist since r89d).
#
# Needs BB_WIND_TWIGS above 0 (default 1; BB_WIND_TWIGS=0 gives no box keys: then the old behaviour
# stays, palettes the GPU wrote stay unread, and the once line says so).
#
# Files: engine/gpu/shim/bbport_wind_hang_still.h (r112d's, r112e's: BoxBook and friends),
# engine/tests/test_wind_hang_still.cpp (cases), vk_rasterizer_effects.cpp (WindHangVerdict, WindSwayWord,
# the once line and the line every 600 frames), vk_rasterizer.h (two members) and README.md (one row).
# No new file, no shader, no CMake or build.sh line (the test is built and run by r112d's lines).
#
# Use: python -I -X utf8 r112f_hang-gpu-judge.py check | apply | revert
# Root: R112F_ROOT, else <tree>. CRLF kept. apply backs the originals up in r112f_backup next to
# this script; revert takes out exactly what apply put in.
import os, sys

ROOT = os.environ.get("R112F_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112f_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RE = RV + "vk_rasterizer_effects.cpp"
RH = RV + "vk_rasterizer.h"
NH = "engine/gpu/shim/bbport_wind_hang_still.h"
NT = "engine/tests/test_wind_hang_still.cpp"
RM = "README.md"

README_ROW = (
    "| `BB_WIND_HANG_BOX_TOL` | A TEST setting for `BB_WIND_HANG` (r112f; millimetres, 2 to 200, default "
    "20). `BB_WIND_HANG` judges whether a skinned thing stands still on the GPU, where its bones are "
    "applied (the game writes the bone palettes on the GPU, so the CPU cannot read them): the vertex "
    "shaders already keep, for every mesh they sway, the lowest and highest world y, x and z of its "
    "vertices (r89's base and crown keys, r89d's box keys); a candidate (sun-drawn, skinned, at most 96 "
    "bones, still palette or unreadable palette) gets a sway word with no motion for about 70 frames, its "
    "keys are read 8 and 68 frames after its window began, and it is still when none of the six numbers "
    "grew by more than this; it is then measured (0.8 to 4 m) and leans downwind as before, and its box is "
    "read again every 30 frames (twice this grows: it stops). A mesh whose box grew by 250 mm or more is a "
    "character for good, one that grew less is judged again after 300 frames. Needs `BB_WIND_TWIGS` above "
    "0 (its default; the box keys are the twigs'); with `BB_WIND_TWIGS=0` palettes the GPU wrote stay "
    "unread and nothing of them is taken. Raise this if the `Wind sway hang (r112f)` line shows still "
    "meshes whose `quiet` deviation is near it (projection jitter), lower it if a character stands "
    "still enough to pass. Cost: nothing with `BB_WIND_HANG` unset; on, a lookup per draw of a "
    "candidate stream, two reads of six mapped words per judgement and one per 30 frames of a hanging "
    "stream, a sway word with no motion for about 70 frames per candidate, no buffer. |\n"
)

OLD_SETTLED = r'''    if (hang_book.Settled(positions, positions_size, frame)) {
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

NEW_SETTLED = r'''    if (hang_book.Settled(positions, positions_size, frame)) {
        // bbport (r112e_hang-taken): a stream settled as moving or as unread is judged afresh after
        // RejudgeFrames, in both books, unless it moved far (a character) or has too many bones
        // bbport (r112f_hang-gpu-judge): and the GPU's keys' verdict first: a stream settled by its
        // height stands, one whose box grew 0.25 m or more is a character for good, one that grew
        // less is due again after RejudgeFrames (BoxBook::Due), with a new window
        const BbWindHang::Entry* const known = hang_book.Find(positions);
        const bool by_height = known != nullptr && !known->moving && known->judged && !known->fits;
        if (by_height || hang_box.Final(positions) ||
            (!hang_box.Due(positions, frame) && !hang_still.Due(positions, frame))) {
            ++hang_stats.settled;
            return false;
        }
        hang_box.Forget(positions);
        if (BbWindHang::Entry* const settled = hang_book.Find(positions)) {
            *settled = BbWindHang::Entry{};
        }
    }
'''

OLD_JUDGE = r'''    const bool still = hang_still.Judge(positions, palette_size, palette, why, in_place, frame,
                                        forced) == BbWindHangStill::Result::Same;
    switch (hang_book.Note(positions, positions_size, 0, still, frame, vs.pgm_hash)) {
    case BbWindHang::Verdict::Still:
        ++hang_stats.still;
        return true;
'''

NEW_JUDGE = r'''    const BbWindHangStill::Result content =
        hang_still.Judge(positions, palette_size, palette, why, in_place, frame, forced);
    // bbport (r112f_hang-gpu-judge): with the sway's box keys (BB_WIND_TWIGS on) a palette the CPU
    // cannot read (the GPU wrote it) is no objection: the GPU's keys judge the stream
    // (WindSwayWord, hang_box); a palette it can read must still be still, as before
    const bool gpu = BbWindHangStill::BoxAvailable() && object_motion->SwayWords() != nullptr &&
                     BbWindHangStill::GpuJudgeable(hang_still.Find(positions), content);
    const bool still = content == BbWindHangStill::Result::Same || gpu;
    switch (hang_book.Note(positions, positions_size, 0, still, frame, vs.pgm_hash)) {
    case BbWindHang::Verdict::Still:
        if (gpu) { // the CPU would take it: the GPU's keys say whether (WindSwayWord)
            hang_judge = true;
            return false;
        }
        ++hang_stats.still;
        return true;
'''

OLD_WORD = r'''    const bool hang = !plant && !tree && WindHangVerdict(pipeline, positions, positions_size);
    if (!plant && !hang && !tree) {
        return 0;
    }
'''

NEW_WORD = r'''    hang_judge = false; // bbport (r112f_hang-gpu-judge): WindHangVerdict sets it for a candidate
    bool hang = !plant && !tree && WindHangVerdict(pipeline, positions, positions_size);
    const bool judge = hang_judge && !hang && !plant && !tree; // (r112f) its keys decide
    if (!plant && !hang && !tree && !judge) {
        return 0;
    }
'''

JUDGE_BLOCK = r'''    if (judge) { // bbport (r112f_hang-gpu-judge): the GPU's keys say whether it stands still
        switch (hang_box.Step(positions, positions_size, taken.slot, taken.reset, frame, words)) {
        case BbWindHangStill::BoxState::Judging: // a hang word with no motion: the keys fill
            return BbWindHang::HangWord(frame_slot, view, taken.slot, 0);
        case BbWindHangStill::BoxState::Still:
            ++hang_stats.still;
            hang = true;
            break;
        case BbWindHangStill::BoxState::Moved:
            if (BbWindHang::Entry* const moved = hang_book.Find(positions)) {
                moved->moving = true;
            }
            ++hang_stats.moving;
            return 0;
        }
    }
'''

ONCE_BLOCK = r'''    // bbport (r112f_hang-gpu-judge): its line once (BB_WIND_HANG on)
    static bool hang_gpu_said = false;
    if (!hang_gpu_said && BbWindHang::KnobOnce().on) {
        hang_gpu_said = true;
        BbReport::Printf("Wind sway hang (r112f): stillness judged on the GPU by the mesh's world "
                         "box (the sway keys): it must hold within %.0f mm over %u frames (watched "
                         "every %u), 250 mm or more is a character for good (box keys: %s); line "
                         "every %u frames\n",
                         double(BbWindHangStill::BoxTol()) * 1000.0,
                         static_cast<unsigned>(BbWindHangStill::BoxStillFrames),
                         static_cast<unsigned>(BbWindHangStill::BoxCheckFrames),
                         BbWindHangStill::BoxAvailable() ? "on"
                                                         : "OFF, BB_WIND_TWIGS=0: GPU-written "
                                                           "palettes stay unread",
                         BbWindSway::ReportFrames);
    }
'''

LINE_BLOCK = r'''        std::string box_line; // bbport (r112f_hang-gpu-judge): the GPU judge's line
        if (BbWindHangStill::BoxAvailable() &&
            hang_box.Report(hang_book, hang_still, object_motion->Frame(), box_line)) {
            BbReport::Printf("%s\n", box_line.c_str());
        }
'''

HEADER_MEMBERS = r'''    BbWindHangStill::BoxBook hang_box; // bbport (r112f_hang-gpu-judge): the GPU keys' verdicts
    bool hang_judge = false; // set by WindHangVerdict: this draw's stream wants the judging word
'''

NH_NOTE = r'''// bbport (r112f_hang-gpu-judge): (4) the GPU judges stillness (BoxBook): the mesh's world box as
// the vertex shaders keep it (r89's base and crown keys, r89d's box keys) must not grow, so a
// palette the GPU wrote and the CPU cannot read is judged too; GpuJudgeable says which may be.
'''

NH_INCLUDE = r'''#include "bbport_wind_twigs.h" // bbport (r112f_hang-gpu-judge): the box keys' layout and reader
'''

NH_BODY = r'''// ------------------------------------------------------------------------------------------------
// bbport (r112f_hang-gpu-judge): the GPU's judgement of a stream's stillness. The vertex shaders
// of a sway draw (any sway word) offer each vertex's WORLD position, after skinning, to the
// stream's base slot: lowest y (BaseAt), highest y (CrownAt), lowest and highest x and z (r89d's
// TwigAt, with BB_WIND_TWIGS on): the mesh's world box, as atomic minima, so it only ever grows.
// The CPU resets a slot's keys, waits, reads them, waits BoxStillFrames, reads again: the
// greatest change of the six numbers is the deviation. Whoever wrote the bone palette, the keys
// are what the screen shows.
inline constexpr float BoxTolDefault = 0.02f;         ///< m: the box of a still mesh grows no more
inline constexpr float BoxTolMin = 0.002f, BoxTolMax = 0.2f; ///< BB_WIND_HANG_BOX_TOL's range (m)
inline constexpr float BoxFinal = 0.25f;              ///< m: grown this much it is a character
inline constexpr std::uint64_t BoxJudgeFrames = BbWindTwigs::JudgeFrames; ///< before the first read
inline constexpr std::uint64_t BoxStillFrames = BbWindTwigs::StillFrames; ///< between the two reads
inline constexpr std::uint64_t BoxCheckFrames = 30;   ///< a still stream's box is read this often
inline constexpr std::uint64_t BoxGiveUpFrames = 600; ///< no key offered in this long: not judged
inline constexpr std::size_t BoxStreamsMost = 256;    ///< streams kept
static_assert(BoxJudgeFrames > BbWindSway::FrameSlots, "the GPU is done with the frames read");
static_assert(BoxTolMin < BoxTolDefault && BoxTolDefault < BoxTolMax && BoxTolMax < BoxFinal);

/// BB_WIND_HANG_BOX_TOL in millimetres (2-200, default 20), read once.
[[nodiscard]] inline float BoxTol() {
    static const float tol = [] {
        const float mm = BbWindSway::ParseNumber(std::getenv("BB_WIND_HANG_BOX_TOL"),
                                                 BoxTolDefault * 1000.0f);
        return std::clamp(mm * 0.001f, BoxTolMin, BoxTolMax);
    }();
    return tol;
}

/// The box keys exist only with BB_WIND_TWIGS on (r89d: the keys, their buffer, their shader code).
[[nodiscard]] inline bool BoxAvailable() {
    return BbWindTwigs::On();
}

/// May the GPU's keys stand in for the palette's content for this stream? `e` its palette entry
/// (may be null), `cpu` what Book::Judge said of this draw. Yes when the palette was read and is
/// still, or it could not be read for a reason that may pass (the GPU wrote it, no mapping, too
/// short, no pivot), and the stream has at most CharacterBones bones. Never a character (more
/// bones), never a stream with no palette bound, never a palette that moved.
[[nodiscard]] inline bool GpuJudgeable(const Entry* e, Result cpu) {
    if (e == nullptr || e->bones == 0 || e->bones > CharacterBones) {
        return false;
    }
    if (cpu == Result::Same) {
        return true;
    }
    return cpu == Result::Never &&
           (e->never == Why::GpuWritten || e->never == Why::NotMapped || e->never == Why::Short ||
            e->never == Why::NoPivot);
}

/// A slot's keys back to ResetKey: base, crown, top and the four box keys (as the caller does when
/// the slot is taken, without BbWindTwigs::ResetSlot's knob test: only called with BoxAvailable()).
inline void ResetKeys(std::uint32_t* words, std::uint32_t slot) {
    words[BbWindSway::BaseAt + slot] = BbWindSway::ResetKey;
    words[BbWindSway::CrownAt + slot] = BbWindSway::ResetKey;
    words[BbWindHang::TopAt + slot] = BbWindSway::ResetKey;
    for (std::uint32_t i = 0; i < BbWindTwigs::TwigSlotWords; ++i) {
        words[BbWindTwigs::TwigAt + slot * BbWindTwigs::TwigSlotWords + i] = BbWindSway::ResetKey;
    }
}

enum class BoxState : std::uint8_t {
    Judging, ///< the window is open: the stream's word has no motion
    Still,   ///< the box did not grow: the CPU's rules go on (height, ramp, push)
    Moved,   ///< it grew (or nothing was offered): not taken
};

struct BoxEntry {
    std::uint32_t size = 0;                 ///< the position stream's bytes (another: another mesh)
    std::uint32_t slot = 0xffffffffu;       ///< the base slot of the window
    std::uint64_t started = 0, seen = 0;    ///< frame the window began; frame last drawn
    std::uint64_t last = ~std::uint64_t{0}; ///< the last frame stepped (one read a frame at most)
    std::uint64_t snap_at = 0, checked = 0; ///< frame of the first read; of the last read if still
    std::uint64_t settled = 0;              ///< frame it was found moving
    bool snapped = false;
    BbWindTwigs::Measure snap;               ///< the first read
    BoxState state = BoxState::Judging;
    float dev = 0.0f; ///< the greatest change from `snap` seen (m); -1 when no key was ever offered
};

struct BoxStats {
    std::uint64_t words = 0;    ///< judging words given (a draw each)
    std::uint64_t reads = 0;    ///< reads of a slot's keys (six mapped words each)
    std::uint64_t restarts = 0; ///< windows begun
    std::uint64_t again = 0;    ///< judged again (Due)
};

/// The streams the GPU's keys judge, by position stream address.
class BoxBook {
public:
    /// A draw of `stream` on `frame` whose CPU rules would take it, in base slot `slot` (`reset`:
    /// the slot was just taken, its keys reset by the caller); `words` the sway region's words.
    /// Judging until BoxJudgeFrames + BoxStillFrames frames after the window began; then Still (the
    /// box grew at most BoxTol) or Moved; a Still stream's keys are read again every
    /// BoxCheckFrames frames (it is Moved when the box grew more than twice BoxTol). At most one
    /// read of the mapped memory a frame.
    BoxState Step(std::uint64_t stream, std::uint32_t size, std::uint32_t slot, bool reset,
                  std::uint64_t frame, std::uint32_t* words) {
        if (stream == 0 || words == nullptr || slot >= BbWindSway::PlantSlots) {
            return BoxState::Moved;
        }
        auto found = entries.find(stream);
        if (found == entries.end()) {
            if (entries.size() >= BoxStreamsMost) {
                Prune(frame);
                if (entries.size() >= BoxStreamsMost) {
                    return BoxState::Moved;
                }
            }
            found = entries.emplace(stream, BoxEntry{}).first;
            Start(found->second, size, slot, frame, words);
        }
        BoxEntry& e = found->second;
        if (reset || e.slot != slot || e.size != size) {
            Start(e, size, slot, frame, words);
        }
        e.seen = frame;
        if (e.state == BoxState::Moved || e.last == frame) {
            return Judged(e);
        }
        e.last = frame;
        if (e.state == BoxState::Still) {
            if (frame >= e.checked + BoxCheckFrames) {
                e.checked = frame;
                const BbWindTwigs::Measure m = Read(words, slot);
                if (m.ok) {
                    const float dev = BbWindTwigs::Moved(e.snap, m);
                    e.dev = std::max(e.dev, dev);
                    if (!(dev <= 2.0f * BoxTol())) {
                        Settle(e, frame);
                    }
                }
            }
            return e.state;
        }
        if (frame < e.started + BoxJudgeFrames ||
            (e.snapped && frame < e.snap_at + BoxStillFrames)) {
            return Judged(e);
        }
        const BbWindTwigs::Measure m = Read(words, slot);
        if (!m.ok) { // nothing offered yet (the mesh may be off screen): wait, then give up
            if (frame >= e.started + BoxGiveUpFrames) {
                e.dev = -1.0f;
                Settle(e, frame);
                return e.state;
            }
            return Judged(e);
        }
        if (!e.snapped) {
            e.snapped = true;
            e.snap = m;
            e.snap_at = frame;
            return Judged(e);
        }
        const float dev = BbWindTwigs::Moved(e.snap, m);
        e.dev = std::max(e.dev, dev);
        if (dev <= BoxTol()) {
            e.state = BoxState::Still;
            e.checked = frame;
        } else {
            Settle(e, frame);
        }
        return e.state;
    }

    /// A stream whose box grew BoxFinal or more: a character, never judged again.
    [[nodiscard]] bool Final(std::uint64_t stream) const {
        const auto found = entries.find(stream);
        return found != entries.end() && found->second.state == BoxState::Moved &&
               found->second.dev >= BoxFinal;
    }

    /// A stream found moving by less than BoxFinal (or with no key offered), at least RejudgeFrames
    /// ago: true, and it is forgotten (the next Step opens a new window with the keys reset).
    bool Due(std::uint64_t stream, std::uint64_t frame) {
        const auto found = entries.find(stream);
        if (found == entries.end() || found->second.state != BoxState::Moved ||
            found->second.dev >= BoxFinal || found->second.settled + RejudgeFrames > frame) {
            return false;
        }
        entries.erase(found);
        ++stats.again;
        return true;
    }

    void Forget(std::uint64_t stream) {
        entries.erase(stream);
    }

    [[nodiscard]] const BoxEntry* Find(std::uint64_t stream) const {
        const auto found = entries.find(stream);
        return found == entries.end() ? nullptr : &found->second;
    }

    [[nodiscard]] std::size_t Size() const {
        return entries.size();
    }

    [[nodiscard]] const BoxStats& Counts() const {
        return stats;
    }

    /// The line every 600 frames (under LineChars characters): the totals (judging, still = the box
    /// held but the height is not measured yet, hang = still and 0.8-4 m, height = still and out of
    /// it, moved), the counts, then the groups by the palette's bone count (`palettes`: the content
    /// book knows it), those with a stream that may hang first: per group the classes, `quiet` the
    /// greatest deviation of a still one (mm) and `moved` the least of a moving one (mm).
    /// `heights` is r112's book. True always: the caller prints it.
    bool Report(BbWindHang::Book& heights, const Book& palettes, std::uint64_t frame,
                std::string& out) const {
        struct Group {
            unsigned streams = 0, judging = 0, still = 0, hang = 0, height = 0, moved = 0;
            float quiet = 0.0f; ///< the greatest deviation of a stream the keys found still (m)
            float least = -1.0f; ///< the least of one they found moving (m); -1: none
        };
        std::map<std::uint32_t, Group, std::greater<std::uint32_t>> groups;
        unsigned listed = 0, judging = 0, still = 0, hang = 0, height = 0, moved = 0;
        for (const auto& item : entries) {
            const BoxEntry& e = item.second;
            if (e.seen + SeenFrames < frame) {
                continue;
            }
            const Entry* const palette = palettes.Find(item.first);
            Group& g = groups[palette == nullptr ? 0u : palette->bones];
            ++listed;
            ++g.streams;
            switch (e.state) {
            case BoxState::Judging:
                ++g.judging;
                ++judging;
                break;
            case BoxState::Moved:
                ++g.moved;
                ++moved;
                if (e.dev >= 0.0f && (g.least < 0.0f || e.dev < g.least)) {
                    g.least = e.dev;
                }
                break;
            case BoxState::Still: {
                const BbWindHang::Entry* const h = heights.Find(item.first);
                if (h != nullptr && h->judged && h->fits) {
                    ++g.hang;
                    ++hang;
                } else if (h != nullptr && h->judged) {
                    ++g.height;
                    ++height;
                } else {
                    ++g.still;
                    ++still;
                }
                g.quiet = std::max(g.quiet, e.dev);
                break;
            }
            }
        }
        const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
        char buf[300];
        std::snprintf(buf, sizeof(buf),
                      "Wind sway hang (r112f): GPU judge, tol %.0f mm: %u streams: %u judging "
                      "%u still %u hang %u height %u moved; words %llu, reads %llu, restarts "
                      "%llu, again %llu; bones",
                      double(BoxTol()) * 1000.0, listed, judging, still, hang, height, moved,
                      n(stats.words), n(stats.reads), n(stats.restarts), n(stats.again));
        std::string text = buf;
        std::vector<std::pair<std::uint32_t, Group>> order(groups.begin(), groups.end());
        const auto may = [](const Group& g) { return g.judging + g.still + g.hang + g.height; };
        std::stable_sort(order.begin(), order.end(), [&](const auto& x, const auto& y) {
            return may(x.second) != 0 && may(y.second) == 0;
        });
        std::size_t shown = 0;
        for (const auto& item : order) {
            if (shown == GroupsMost || text.size() > LineMost) {
                std::snprintf(buf, sizeof(buf), "; +%zu groups", order.size() - shown);
                text += buf;
                break;
            }
            ++shown;
            const Group& g = item.second;
            std::snprintf(buf, sizeof(buf), "; %ub x%u:", item.first, g.streams);
            text += buf;
            const auto put = [&](const char* name, unsigned count) {
                if (count != 0) {
                    std::snprintf(buf, sizeof(buf), " %s=%u", name, count);
                    text += buf;
                }
            };
            put("judging", g.judging);
            put("still", g.still);
            put("hang", g.hang);
            put("height", g.height);
            put("moved", g.moved);
            if (g.streams != g.judging + g.moved) {
                std::snprintf(buf, sizeof(buf), " quiet<=%.0fmm", double(g.quiet) * 1000.0);
                text += buf;
            }
            if (g.least >= 0.0f) {
                std::snprintf(buf, sizeof(buf), " moved>=%.0fmm", double(g.least) * 1000.0);
                text += buf;
            }
        }
        if (text.size() > LineChars) {
            text.resize(LineChars - 3);
            text += "...";
        }
        out = std::move(text);
        return true;
    }

private:
    /// One read of a slot's six keys (mapped memory), counted for the line.
    BbWindTwigs::Measure Read(const std::uint32_t* words, std::uint32_t slot) {
        ++stats.reads;
        return BbWindTwigs::MeasureOf(BbWindTwigs::ReadKeys(words, slot));
    }

    void Start(BoxEntry& e, std::uint32_t size, std::uint32_t slot, std::uint64_t frame,
               std::uint32_t* words) {
        e = BoxEntry{};
        e.size = size;
        e.slot = slot;
        e.started = frame;
        e.seen = frame;
        ResetKeys(words, slot); // a new window: the history of an earlier life does not count
        ++stats.restarts;
    }

    void Settle(BoxEntry& e, std::uint64_t frame) {
        e.state = BoxState::Moved;
        e.settled = frame;
    }

    /// The answer of a Judging entry's draw (a word with no motion is given: counted); else as is.
    BoxState Judged(const BoxEntry& e) {
        stats.words += e.state == BoxState::Judging ? 1u : 0u;
        return e.state;
    }

    void Prune(std::uint64_t frame) {
        for (auto it = entries.begin(); it != entries.end();) {
            if (it->second.seen + SeenFrames < frame) {
                it = entries.erase(it);
            } else {
                ++it;
            }
        }
    }

    std::unordered_map<std::uint64_t, BoxEntry> entries;
    BoxStats stats;
};

'''

NT_BODY = r'''    // r112f: the GPU judge (the sway words' keys: base, crown and the box), case for case with
    // r112f_twin.py
    {
        std::vector<std::uint32_t> words(BbWindTwigs::TwigEnd, BbWindSway::ResetKey);
        namespace W = BbWindSway;
        const auto offer = [&](std::uint32_t slot, float y0, float y1, float x0, float x1, float z0,
                               float z1) {
            const auto low = [&](std::uint32_t at, std::uint32_t key) {
                words[at] = std::min(words[at], key);
            };
            const std::uint32_t box = BbWindTwigs::TwigAt + slot * BbWindTwigs::TwigSlotWords;
            low(W::BaseAt + slot, W::HeightKey(y0));
            low(W::CrownAt + slot, W::CrownKey(y1));
            low(box + 0, W::HeightKey(x0));
            low(box + 1, W::CrownKey(x1));
            low(box + 2, W::HeightKey(z0));
            low(box + 3, W::CrownKey(z1));
        };
        // still: judging until frame 168 (window 100, first read 108, second 168), then still
        S::BoxBook box;
        for (std::uint64_t f = 100; f < 200; ++f) {
            if (f >= 101) {
                offer(7, 0.0f, 2.0f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            const S::BoxState st = box.Step(10, 4096, 7, f == 100, f, words.data());
            if (f < 168) {
                Expect(st == S::BoxState::Judging, "box: judging before frame 168");
            } else {
                Expect(st == S::BoxState::Still, "box: still from frame 168");
            }
        }
        Expect(box.Find(10)->dev == 0.0f && !box.Final(10), "box: no deviation, not final");
        // 5 mm of jitter stays still
        S::BoxBook jitter;
        for (std::uint64_t f = 100; f < 200; ++f) {
            const float d = 0.005f * float(f % 2);
            if (f >= 101) {
                offer(8, 0.0f, 2.0f + d, 10.0f - d, 11.0f + d, 20.0f, 21.0f - d);
            }
            jitter.Step(11, 4096, 8, f == 100, f, words.data());
        }
        Expect(jitter.Find(11)->state == S::BoxState::Still && jitter.Find(11)->dev < 0.012f,
               "box: 5 mm of jitter is still");
        // a mover (0.5 m): moved for good
        S::BoxBook mover;
        for (std::uint64_t f = 100; f < 170; ++f) {
            if (f >= 101) {
                offer(9, 0.0f, f < 120 ? 2.0f : 2.5f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            mover.Step(12, 4096, 9, f == 100, f, words.data());
        }
        Expect(mover.Find(12)->state == S::BoxState::Moved && mover.Final(12) &&
                   !mover.Due(12, 100000),
               "box: a mover is final, never judged again");
        // a small mover (50 mm): moved, due after RejudgeFrames, then judged afresh with fresh keys
        S::BoxBook nudged;
        for (std::uint64_t f = 100; f < 170; ++f) {
            if (f >= 101) {
                offer(10, 0.0f, f < 120 ? 2.0f : 2.05f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            nudged.Step(13, 4096, 10, f == 100, f, words.data());
        }
        const std::uint64_t at = nudged.Find(13)->settled;
        Expect(nudged.Find(13)->state == S::BoxState::Moved && !nudged.Final(13),
               "box: small mover");
        Expect(!nudged.Due(13, at + S::RejudgeFrames - 1) && nudged.Due(13, at + S::RejudgeFrames),
               "box: due after RejudgeFrames");
        Expect(nudged.Find(13) == nullptr && nudged.Counts().again == 1, "box: forgotten, counted");
        nudged.Step(13, 4096, 10, false, at + S::RejudgeFrames, words.data());
        Expect(nudged.Find(13)->state == S::BoxState::Judging &&
                   words[W::CrownAt + 10] == W::ResetKey,
               "box: judged afresh with the keys reset");
        // watched: still, then the box grows 0.1 m: moved at the next check
        S::BoxBook watched;
        S::BoxState at197 = S::BoxState::Judging, at198 = S::BoxState::Judging;
        for (std::uint64_t f = 100; f < 230; ++f) {
            if (f >= 101) {
                offer(11, 0.0f, f < 190 ? 2.0f : 2.1f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            const S::BoxState st = watched.Step(14, 4096, 11, f == 100, f, words.data());
            at197 = f == 197 ? st : at197;
            at198 = f == 198 ? st : at198;
        }
        Expect(at197 == S::BoxState::Still && at198 == S::BoxState::Moved,
               "box: a still stream is watched every 30 frames");
        // a reset, another slot and another size start again
        S::BoxBook restart;
        for (std::uint64_t f = 100; f < 130; ++f) {
            restart.Step(15, 4096, 12, f == 100, f, words.data());
        }
        restart.Step(15, 4096, 12, true, 130, words.data());
        Expect(restart.Find(15)->started == 130 && words[W::BaseAt + 12] == W::ResetKey,
               "box: a reset starts again, keys reset");
        restart.Step(15, 4096, 13, false, 131, words.data());
        Expect(restart.Find(15)->slot == 13 && restart.Find(15)->started == 131,
               "box: another slot starts again");
        restart.Step(15, 8192, 13, false, 132, words.data());
        Expect(restart.Find(15)->started == 132, "box: another size starts again");
        // nothing offered: waits, gives up after BoxGiveUpFrames (dev -1: not final, due later)
        S::BoxBook none;
        S::BoxState before = S::BoxState::Judging, after = S::BoxState::Judging;
        for (std::uint64_t f = 100; f <= 100 + S::BoxGiveUpFrames; ++f) {
            const S::BoxState st = none.Step(16, 4096, 20, f == 100, f, words.data());
            before = f == 100 + S::BoxGiveUpFrames - 1 ? st : before;
            after = f == 100 + S::BoxGiveUpFrames ? st : after;
        }
        Expect(before == S::BoxState::Judging && after == S::BoxState::Moved, "box: gives up");
        Expect(none.Find(16)->dev == -1.0f && !none.Final(16), "box: no key: dev -1, not final");
        // refused: no stream, a slot beyond the plant slots, no words
        Expect(none.Step(0, 4096, 1, false, 1, words.data()) == S::BoxState::Moved,
               "box: stream 0");
        Expect(none.Step(5, 4096, W::PlantSlots, false, 1, words.data()) == S::BoxState::Moved,
               "box: slot out of range");
        Expect(none.Step(5, 4096, 1, false, 1, nullptr) == S::BoxState::Moved, "box: no words");
        // one read a frame: three draws of one frame read once
        S::BoxBook once;
        once.Step(1, 4096, 3, true, 0, words.data());
        const std::uint64_t reads = once.Counts().reads;
        once.Step(1, 4096, 3, false, 50, words.data());
        once.Step(1, 4096, 3, false, 50, words.data());
        once.Step(1, 4096, 3, false, 50, words.data());
        Expect(once.Counts().reads == reads + 1, "box: one read a frame");
        // which streams the keys may judge
        S::Book palettes;
        palettes.Judge(3, 28 * S::BoneBytes, nullptr, S::Why::GpuWritten, false, 10);
        palettes.Judge(4, 277 * S::BoneBytes, nullptr, S::Why::GpuWritten, false, 10);
        palettes.Judge(5, 28 * S::BoneBytes, nullptr, S::Why::NotMapped, false, 10);
        palettes.Judge(6, 0, nullptr, S::Why::None, false, 10);
        palettes.Judge(7, 28 * S::BoneBytes, nullptr, S::Why::None, false, 10);
        Expect(S::GpuJudgeable(palettes.Find(3), S::Result::Never),
               "judgeable: 28 bones, GPU-written");
        Expect(!S::GpuJudgeable(palettes.Find(4), S::Result::Never), "judgeable: the hunter's 277");
        Expect(S::GpuJudgeable(palettes.Find(5), S::Result::Never), "judgeable: not mapped");
        Expect(!S::GpuJudgeable(palettes.Find(6), S::Result::Never), "judgeable: no palette");
        Expect(!S::GpuJudgeable(palettes.Find(7), S::Result::Never),
               "judgeable: no palette bound (nopal)");
        Expect(!S::GpuJudgeable(nullptr, S::Result::Same), "judgeable: unknown stream");
        Expect(!S::GpuJudgeable(palettes.Find(3), S::Result::Moved),
               "judgeable: a palette that moved");
        Expect(S::GpuJudgeable(palettes.Find(3), S::Result::Same), "judgeable: a still palette");
        // the line
        BbWindHang::Book heights;
        std::string line;
        Expect(box.Report(heights, palettes, 230, line), "box: the line is reported");
        Expect(line.find("Wind sway hang (r112f): GPU judge, tol 20 mm: 1 streams: 0 judging "
                         "1 still") == 0,
               "box line: totals");
        Expect(line.find("; 0b x1: still=1 quiet<=0mm") != std::string::npos, "box line: group");
        Expect(line.size() <= S::LineChars, "box line: short");
        Expect(mover.Report(heights, palettes, 200, line) &&
                   line.find(" moved=1 moved>=500mm") != std::string::npos,
               "box line: a moved stream and its least deviation");
        S::BoxBook many;
        for (std::uint64_t s = 1; s < 60; ++s) {
            many.Step(s, 4096, std::uint32_t(s), true, 5, words.data());
        }
        Expect(many.Report(heights, palettes, 6, line) && line.size() <= S::LineChars,
               "box line: many streams, short");
    }
'''

OLD_NT_END = '''    if (failures == 0) {
        std::printf("wind-hang-still-test: all passed\\n");
'''

EDITS = {
RE: [
("rep", OLD_SETTLED, "", NEW_SETTLED),
("rep", OLD_JUDGE, "", NEW_JUDGE),
("rep", OLD_WORD, "", NEW_WORD),
("ins", "    if (hang) { // bbport (r112_wind-more-things): its word (WindHangWord), counted in its lines\n",
 JUDGE_BLOCK, ""),
("ins", "    if (!on || ++sway_frames % BbWindSway::ReportFrames != 0) {\n", ONCE_BLOCK, ""),
("ins", "        hang_stats = {};\n", LINE_BLOCK, ""),
],
RH: [
("ins", "    BbWindHangStill::Book hang_still; // bbport (r112d_hang-still-test): palettes' content\n",
 "", HEADER_MEMBERS),
],
NH: [
("ins", '#include "bbport_wind_hang.h"\n', "", NH_INCLUDE),
("ins", "// Pure: no Vulkan; tested by tests/test_wind_hang_still.cpp.\n", NH_NOTE, ""),
("ins", "} // namespace BbWindHangStill\n", NH_BODY, ""),
],
NT: [
("ins", OLD_NT_END, NT_BODY, ""),
],
RM: [
("ins", "| `BB_WIND_HANG_READ_GPU` | A TEST setting for `BB_WIND_HANG`", README_ROW, ""),
],
}

ORDER = (RE, RH, NH, NT, RM)


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
    re_, hh, tt, rh = texts[RE], texts[NH], texts[NT], texts[RH]
    need(RE, "hang_box.Step(positions, positions_size, taken.slot, taken.reset, frame, words)", 1)
    need(RE, "hang_judge = true;", 1)
    need(RE, "hang_judge = false;", 1)
    need(RE, "hang_box.Final(positions)", 1)
    need(RE, "hang_box.Due(positions, frame)", 1)
    need(RE, "hang_box.Forget(positions);", 1)
    need(RE, "hang_gpu_said", 3)
    need(RE, "hang_box.Report(hang_book, hang_still, object_motion->Frame(), box_line)", 1)
    need(RE, "BbWindHangStill::GpuJudgeable(hang_still.Find(positions), content)", 1)
    need(RH, "BbWindHangStill::BoxBook hang_box;", 1)
    need(RH, "bool hang_judge = false;", 1)
    # order inside WindHangVerdict: knob test, sun test, settled/Due, the palette reader, Judge, Note
    a = re_.find("bool Rasterizer::WindHangVerdict(")
    k = re_.find("if (!BbWindHang::KnobOnce().on) {", a)
    s = re_.find("rt_shadow->SunSkinned(positions, positions_size)", a)
    t = re_.find("hang_book.Settled(positions, positions_size, frame)", a)
    f = re_.find("hang_box.Final(positions)", a)
    d = re_.find("hang_still.Due(positions, frame)", a)
    j = re_.find("hang_still.Judge(", a)
    g = re_.find("BbWindHangStill::GpuJudgeable(", a)
    sj = re_.find("hang_judge = true;", a)
    n = re_.find("hang_book.Note(", a)
    e = re_.find("\n}\n", a)
    if not (0 <= a < k < s < t < f < d < j < g < n < sj < e):
        raise SystemExit("text check: the GPU judge is not in order inside WindHangVerdict")
    # in WindSwayWord: hang_judge reset, then the verdict, then the judge block before the hang word
    w = re_.find("u32 Rasterizer::WindSwayWord(")
    r0 = re_.find("hang_judge = false;", w)
    v0 = re_.find("WindHangVerdict(pipeline, positions, positions_size)", w)
    ts = re_.find("sway_slots.Take(positions, positions_size, frame, snapshot.time)", w)
    jb = re_.find("hang_box.Step(", w)
    hw = re_.find("return WindHangWord(words, frame_slot, view, taken.slot, taken.reset, positions", w)
    en = re_.find("\n}\n", w)
    if not (0 <= w < r0 < v0 < ts < jb < hw < en):
        raise SystemExit("text check: the judge block is not between Take and WindHangWord")
    if re_.find("const bool hang = !plant && !tree && WindHangVerdict") >= 0:
        raise SystemExit("text check: hang is still const")
    # the once-line sits before the 600-frame test, behind the knob
    o = re_.find("hang_gpu_said = true;")
    r = re_.find("if (!on || ++sway_frames % BbWindSway::ReportFrames != 0) {", o)
    if not (0 <= o < r):
        raise SystemExit("text check: the once-line is not before the report's frame test")
    for path in (RE, RH):
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
    for want in ("class BoxBook {", "inline bool GpuJudgeable(", "BoxTolDefault = 0.02f",
                 "BoxFinal = 0.25f", "BoxCheckFrames = 30", "BB_WIND_HANG_BOX_TOL",
                 'bbport_wind_twigs.h"', "enum class BoxState", "inline void ResetKeys("):
        if want not in hh:
            raise SystemExit("text check: %r is missing in the header" % want)
    need(NH, "Wind sway hang (r112f): GPU judge, tol %.0f mm", 1)
    need(NT, "return failures == 0 ? 0 : 1;", 1)
    if "S::BoxBook" not in tt or "S::GpuJudgeable" not in tt:
        raise SystemExit("text check: the test does not hold the GPU judge")
    # the keys the reset writes are the ones the shaders and r112's taken.reset block use
    need(RE, "words[BbWindHang::TopAt + taken.slot] = BbWindSway::ResetKey;", 1)
    if texts[RM].count("| `BB_WIND_HANG_BOX_TOL` |") != 1:
        raise SystemExit("text check: README has not exactly one BB_WIND_HANG_BOX_TOL row")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112F_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == RE and "hang_still.Due(positions, frame)" not in cur and "hang_box.Final(" not in cur:
            raise SystemExit("REFUSED: r112e_hang-taken is not applied (no hang_still.Due)")
        if path == NH and "bool Due(" not in cur:
            raise SystemExit("REFUSED: r112e_hang-taken is not applied (no Due in the header)")
        if path == NH and "namespace BbWindHangStill" not in cur:
            raise SystemExit("REFUSED: r112d_hang-still-test is not applied (no BbWindHangStill)")
        if path == RE and "BbWindTwigs::Entry& entry =" not in cur:
            raise SystemExit("REFUSED: r89d_tree-twigs is not applied (no twig Book in WindTwigWord)")
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
            tmp = full + ".r112ftmp"
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
        tmp = full + ".r112ftmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


if __name__ == "__main__":
    main()
