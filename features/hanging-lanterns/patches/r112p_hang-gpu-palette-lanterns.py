# r112p_hang-gpu-palette-lanterns (FEATURE fix on r112, behind BB_WIND_HANG=1; off by default with it): on top of r112o_hang-safe-goto,
# r112n, r112m ... r112d (all applied in the tree, build 63).
# GRADE: FEATURE (hanging things). The one hook outside the hang code is a single line in the buffer binding loop that feeds a diagnostic
# (the palette writer watch); it is a relaxed load of a false atomic while nothing is watched, and nothing is watched without BB_WIND_HANG=1.
#
# THE EVIDENCE (b63: b63_s1.log r112o-grave, b63_s2.log r112o-proof, b63_reports.txt)
#  - The lanterns that hang from brackets in the graveyard trees (vs e859b6d9 in the survey, 1.3-2 m tall, route S = skinned) are never
#    pushed, not even at BB_WIND_HANG_STATIC_GAIN=1. The candidate lines say 'held as moving by r112's book: a palette it draws with could
#    not be read (GPU-written or not mapped)' (61 lines) or plain 'held as moving' (21); one mesh (c829ee58, static) 'found moving by the
#    GPU judge (box grew 25798 mm)'. The pushed 97f2d384 lantern (6.29 m up) and its cage do move 0.044-0.080 m at gain 0.2.
#
# WHAT THE CODE SAYS (read, nothing run; the lead's reading 'a GPU-written palette is the blocker' is only half of it)
#  (a) bbport_wind_hang.h Book::Note(.., readable, ..) sets why_moving = 1 whenever `readable` is false, and WindHangVerdict passed
#      `readable = (content == Same || gpu)`. `content` is r112d's palette test: Same, Moved (the palette WAS read and its content differs
#      from the first draw's: an animated skeleton, or other instances of the stream posed differently, the 'not done' of r112e) or Never
#      (it could not be read). Moved and Never both ended as reason 1, whose text r112n wrote as 'could not be read'. So the 61 lines do
#      NOT prove that these palettes are GPU-written; they say the CPU test refused the stream for one of two reasons.
#  (b) Either way the stream never reaches r112f's GPU judge. For Never the door is GpuJudgeable (1 to 96 bones, and the bone count of
#      an unread palette is its V#'s size over 48: a capacity the game binds, not the mesh's rig; 84-bone (4032 B), 48-bone and 28-bone
#      palettes are the unreadable ones in the logs); for Moved there is no door at all. The GPU judge itself (the mesh's world box does
#      not grow, 20 mm over 60 frames) needs no palette, so it is the right judge for both.
#  (c) Even a stream the judge cleared would meet r112h's figure rule next (BB_WIND_HANG_BONES, 24 bones), which reads the same V# size.
#
# WHAT THIS CHANGES (BB_WIND_HANG_BOXJUDGE=0 gives r112o back, exactly)
#  (1) The two refusals get their own reasons: why_moving 5 = the palette content differed ('its palette's content differs from the first
#      draw's'); 1 stays 'could not be read'. The candidate lines say so. A candidate that is judged by the box says it in its PUSHED state
#      ('[judged by the GPU box: palette unread|content moved]').
#  (2) bbport_wind_hang_gpu.h (new, pure): BoxJudgeable(entry, content, cap): a stream refused by content (Moved) or for a reason that may pass
#      (gpu, unmapped, short, pivot) with 1 to BB_WIND_HANG_BOX_BONES bones (default 96 = CharacterBones, 13 to 341) goes to the GPU box
#      judge (WindHangVerdict sets hang_judge, as for r112f's streams). More bones (the hunter has 277) stay refused; a READABLE palette of
#      more than 96 bones is a character and is never judged; no palette (0 bones) is refused. The judge is unchanged: a box that grows 20 mm
#      over 60 frames is moving, 250 mm is a character for good, so the mesh whose box grew 25.8 m in b63 stays refused (that one is a static
#      stream: the r112i path, which this does not touch).
#  (3) r112h's figure rule reads one bone for such a stream (the one-bone stand-in the static meshes already use); the hunter's own gear
#      pieces stay out by r112h's NEAR rule (within 1.5 m of him, in his band) and by the box, which grows when he moves.
#  (4) The push is a static lantern's: WindHangWord sends the ramp of a box-judged stream through SameRamp with BB_WIND_HANG_STATIC_GAIN
#      (0.2, the live set:/unset: knob of r112m), so the bottom moves min(scale, gain) x push: 0.07 m at 4 m/s, gust 0.9 (3-10 cm range
#      for the gain 0.15-0.4 and the usual gust), settling back in 1.6 s, downwind, the pivot the top key of the stream's slot (the shaders'
#      top rule: the top 0.3 m still, full 1.2 m below; unchanged). A stream drawn at several heights swings its lower places rigidly by the
#      same push: at most 0.08 m.
#  (5) What writes those palettes, logged once: the census ('GLINT-PROOF hang box (r112p)': per refused stream the V# bones and bytes, the
#      palette's address, whether the buffer cache calls its pages GPU-modified, whether they are bound in place, and the route) and the
#      writer watch: the first palettes found GPU-written (and not in place) have their 4 KiB pages watched, and the next written
#      storage-buffer binding over one (Rasterizer::BindBuffers, which every shader write goes through) is logged once with its shader hash,
#      its stage and whether the palette lies INSIDE the written range or only SHARES a page with it. The log answers what the code cannot:
#      a compute pass that writes the palettes (inside), or a ring that shares a page with something the GPU writes (shares).
#
# Off / cost: BB_WIND_HANG unset: no hang code runs; the one hook in BindBuffers is Watch::Written, one relaxed load of a false atomic per
# written storage-buffer binding (nothing is watched). BB_WIND_HANG=1: the census costs a map lookup per draw of a refused stream, the box
# route adds r112f's judging words for the streams it takes (a sway word with no motion for about 70 frames per stream and window: the
# 13-bone x10 judging streams of b63 are that class already; at most BoxStreamsMost 256), then a static lantern's word: GPU cost of a few
# draws' sway code, not measured. Memory: a census of at most 128 items of 48 bytes, a watch of 8 pages, 12 hits.
#
# Shared files touched (none of them a neighbour's lines): vk_rasterizer.h (one include line after r112h's, one member block after
# hang_judge), vk_rasterizer.cpp (ONE hook line before 'const VideoCore::InvalidateReason reason{"storage buffer"};' in BindBuffers),
# vk_rasterizer_effects.cpp (r112's WindHangVerdict tail, WindHangActorsClear, WindHangWord's return, one once-line, one report block),
# bbport_wind_hang.h (Entry::box_only, Book::Note's two trailing parameters with defaults), bbport_wind_hang_find.h (reason 5, the
# CandInfo field and the PUSHED text), README.md (two rows before r112m's BB_WIND_HANG_PROOF row), gpu/CMakeLists.txt and build.sh (the
# test, after r112i's). No shader, no lifter, no cache version, no SPIR-V: every shader build is byte-identical.
#
# Use: python -I -X utf8 r112p_hang-gpu-palette-lanterns.py check | apply | revert
# Root: R112P_ROOT, else <tree>. Line ends kept (the new files take the tree's: CRLF). apply backs the originals up in r112p_backup
# next to this script; revert takes out exactly what apply put in and removes the new files. Needs r112 (and r112o) applied.
import os, re, sys

ROOT = os.environ.get("R112P_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112p_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RH = RV + "vk_rasterizer.h"
RC = RV + "vk_rasterizer.cpp"
EF = RV + "vk_rasterizer_effects.cpp"
SH = "engine/gpu/shim/"
HH = SH + "bbport_wind_hang.h"
HF = SH + "bbport_wind_hang_find.h"
HG = SH + "bbport_wind_hang_gpu.h"
TG = "engine/tests/test_wind_hang_gpu.cpp"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
RM = "README.md"

# ---- the new files -----------------------------------------------------------------------------------
NEW_FILES = {
    HG: r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r112p_hang-gpu-palette-lanterns): skinned hanging things (the bracket lanterns in the graveyard trees, vs e859b6d9,
// 1.3-2 m tall) that r112's palette test turns away. b63: 'held as moving by r112's book: a palette it draws with could not be
// read (GPU-written or not mapped)' on 61 candidate lines, 21 plain 'held as moving', not pushed at any gain.
//
// WHAT THE CODE SAYS (read, nothing run): BbWindHang::Book::Note(.., readable, ..) sets Entry::moving and why_moving = 1 when
// `readable` is false, and WindHangVerdict passed `readable = content == Same || gpu`. So the one reason 1 hides TWO different
// refusals: (a) the palette could not be read (BbWindHangStill::Result::Never: GPU-written and not in place, not mapped, too
// short, no pivot) and was not GpuJudgeable (GpuJudgeable wants 1 to CharacterBones (96) bones, and the bone count of an unread
// palette is its V#'s size over 48: a capacity the game binds, not the rig of the mesh); (b) the palette WAS read and its content
// differs from the first draw's (Result::Moved: an animated skeleton, or other instances of the stream posed differently: the
// 'not done' of r112e), which r112n's reason text called 'could not be read'. Both end in the same place: the stream is a mover
// for good (or 300 frames) and never reaches the GPU judge, whose verdict (the mesh's world box does not grow) does not need the
// palette at all.
//
// WHAT THIS ADDS (BB_WIND_HANG=1 only; BB_WIND_HANG_BOXJUDGE=0 gives r112o back, =unread takes only the unread palettes, not the
// ones whose content moved):
//  (1) the reason is kept apart: why_moving 5 = the palette content differed (1 stays: unread);
//  (2) BoxJudgeable: a stream whose CPU palette test refuses it (Moved, or Never for gpu / unmapped / short / pivot) is sent to
//      r112f's GPU box judge when its bones (V# size over 48) are at most BB_WIND_HANG_BOX_BONES (default 96 = CharacterBones, 13
//      to 341); more bones stay refused (the hunter has 277), a readable palette of more than 96 bones is a character and never
//      judged. The judge is unchanged (a box that grows 20 mm over 60 frames is moving, 250 mm is a character for good: the real
//      mover whose box grew 25.8 m in b63 stays refused);
//  (3) such a stream's bone count is no figure test (r112h's BB_WIND_HANG_BONES, 24, read the V# capacity): the one-bone stand-in
//      the static meshes use takes its place; the hunter's gear is still kept off by r112h's NEAR rule (within 1.5 m of him);
//  (4) it is pushed like a static lantern: its ramp goes through SameRamp with BB_WIND_HANG_STATIC_GAIN (live set:/unset: as
//      before), so the bottom moves min(scale, gain) x push (0.2 x 0.35 m = 0.07 m at 4 m/s gust 0.9); the pivot is the top key of
//      its slot (the highest world y of the places the stream is drawn at: the shaders' HangScale / top rule, unchanged);
//  (5) the census (what the CPU test said of each such stream: reason, V# bytes, bones, the palette's address, GPU-modified,
//      in place, judged by the box or turned away) and the writer watch: the first palettes found GPU-written have their 4 KiB
//      pages watched, and the next written storage-buffer binding over one (the binding loop of Rasterizer::BindBuffers, which
//      every GPU write through a shader goes through) is logged once with its shader hash, its stage and whether the palette
//      lies inside the written range or only shares a page with it. Both go out as 'GLINT-PROOF hang box (r112p)' lines (the
//      slot runner keeps every GLINT-PROOF line).
// Pure: no Vulkan; tested by tests/test_wind_hang_gpu.cpp. Nothing here runs without BB_WIND_HANG=1: the only call outside the
// hang code is Watch::Written in the buffer binding loop, one relaxed load of a false atomic while nothing is watched.

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

#include "bbport_wind_hang_still.h"

namespace BbWindHangGpu {

namespace S = BbWindHangStill;

inline constexpr unsigned BonesMin = 13;  ///< 640 bytes: the least a Skeleton-role palette has (Motion::ClassifyBuffer)
inline constexpr unsigned BonesMax = 341; ///< 16384 bytes: the most
inline constexpr std::size_t CensusMost = 128; ///< streams the census keeps
inline constexpr std::size_t WatchMost = 8;    ///< palettes whose pages are watched
inline constexpr std::size_t HitsMost = 12;    ///< writers logged
inline constexpr std::size_t ExamplesMost = 5; ///< streams named in the census line
inline constexpr std::uint64_t PageBytes = 4096; ///< the memory tracker's page (an assumption: the line says 4 KiB)
inline constexpr std::size_t LineChars = 640;    ///< GLINT-PROOF lines are kept up to 700 characters by the slot runner

static_assert(BonesMin * S::BoneBytes <= 640 && BonesMax * S::BoneBytes <= 16384, "the V# sizes of a skeleton");
static_assert(S::CharacterBones >= BonesMin && S::CharacterBones <= BonesMax);

/// BB_WIND_HANG_BOXJUDGE: `0` off (r112o's behaviour), `unread` only the palettes that could not be read, anything else (also unset)
/// both those and the palettes whose content moved.
enum class Mode : std::uint8_t { Off, Unread, All };

[[nodiscard]] inline Mode ParseMode(const char* text) {
    if (text != nullptr && text[0] == '0' && text[1] == 0) {
        return Mode::Off;
    }
    if (text != nullptr && std::string(text) == "unread") {
        return Mode::Unread;
    }
    return Mode::All;
}

[[nodiscard]] inline const char* ModeName(Mode m) {
    switch (m) {
    case Mode::Off:
        return "OFF";
    case Mode::Unread:
        return "unread";
    case Mode::All:
        break;
    }
    return "all";
}

[[nodiscard]] inline unsigned ParseBones(const char* text) {
    return static_cast<unsigned>(
        std::clamp(BbWindSway::ParseNumber(text, static_cast<float>(S::CharacterBones)), static_cast<float>(BonesMin),
                   static_cast<float>(BonesMax)));
}

[[nodiscard]] inline Mode ModeOnce() {
    static const Mode mode = ParseMode(std::getenv("BB_WIND_HANG_BOXJUDGE"));
    return mode;
}

[[nodiscard]] inline bool BoxOn() {
    return ModeOnce() != Mode::Off;
}

/// BB_WIND_HANG_BOX_BONES: the most bones (V# size over 48) of a stream the box judge takes in place of the palette test.
[[nodiscard]] inline unsigned BoxBones() {
    static const unsigned bones = ParseBones(std::getenv("BB_WIND_HANG_BOX_BONES"));
    return bones;
}

/// What the CPU palette test said of one draw's palette.
enum class Kind : std::uint8_t { Same, Moved, Gpu, Unmapped, Short, Pivot, NoPal, Character, Other };
inline constexpr std::size_t KindCount = 9;

[[nodiscard]] inline const char* KindName(Kind k) {
    switch (k) {
    case Kind::Same:
        return "same";
    case Kind::Moved:
        return "moved";
    case Kind::Gpu:
        return "gpu";
    case Kind::Unmapped:
        return "unmapped";
    case Kind::Short:
        return "short";
    case Kind::Pivot:
        return "pivot";
    case Kind::NoPal:
        return "nopal";
    case Kind::Character:
        return "char";
    case Kind::Other:
        break;
    }
    return "other";
}

/// `e` the stream's palette entry (null: none), `cpu` what Book::Judge said of this draw.
[[nodiscard]] inline Kind KindOf(const S::Entry* e, S::Result cpu) {
    if (cpu == S::Result::Same) {
        return Kind::Same;
    }
    if (cpu == S::Result::Moved) {
        return Kind::Moved;
    }
    if (e == nullptr) {
        return Kind::Other;
    }
    switch (e->never) {
    case S::Why::GpuWritten:
        return Kind::Gpu;
    case S::Why::NotMapped:
        return Kind::Unmapped;
    case S::Why::Short:
        return Kind::Short;
    case S::Why::NoPivot:
        return Kind::Pivot;
    case S::Why::NoPalette:
        return Kind::NoPal;
    case S::Why::Character:
        return Kind::Character;
    case S::Why::None:
        break;
    }
    return Kind::Other;
}

/// May the GPU box judge stand in for the palette test of this stream? Yes when the test refused it by content (Moved: only with
/// `moved_ok`, Mode::All) or for a reason that may pass (gpu, unmapped, short, pivot) and the stream has 1 to `cap` bones. Never a
/// palette with no bones or none bound, never a readable palette of more than CharacterBones bones (a character), never one over
/// the cap.
[[nodiscard]] inline bool BoxJudgeable(const S::Entry* e, S::Result cpu, unsigned cap, bool moved_ok = true) {
    if (e == nullptr || e->bones == 0 || e->bones > cap) {
        return false;
    }
    switch (KindOf(e, cpu)) {
    case Kind::Moved:
        return moved_ok;
    case Kind::Gpu:
    case Kind::Unmapped:
    case Kind::Short:
    case Kind::Pivot:
        return true;
    case Kind::Same:
    case Kind::NoPal:
    case Kind::Character:
    case Kind::Other:
        break;
    }
    return false;
}

/// Do the 4 KiB pages of [a, a + an) and [b, b + bn) share a page?
[[nodiscard]] inline bool SharePage(std::uint64_t a, std::uint64_t an, std::uint64_t b, std::uint64_t bn) {
    if (an == 0 || bn == 0) {
        return false;
    }
    const std::uint64_t mask = PageBytes - 1;
    const std::uint64_t a0 = a & ~mask, a1 = (a + an + mask) & ~mask;
    const std::uint64_t b0 = b & ~mask, b1 = (b + bn + mask) & ~mask;
    return a0 < b1 && b0 < a1;
}

/// Does [outer, outer + outer_n) hold all of [inner, inner + inner_n)?
[[nodiscard]] inline bool Holds(std::uint64_t outer, std::uint64_t outer_n, std::uint64_t inner, std::uint64_t inner_n) {
    return inner >= outer && inner + inner_n <= outer + outer_n;
}

[[nodiscard]] inline const char* StageName(std::uint32_t stage) {
    switch (stage) { // Shader::SwStage's order
    case 0:
        return "pixel";
    case 1:
        return "tess control";
    case 2:
        return "tess eval";
    case 3:
        return "vertex";
    case 4:
        return "geometry";
    case 5:
        return "compute";
    default:
        break;
    }
    return "stage ?";
}

/// What one stream's palette was, as the census sees it (a draw of a stream the CPU test refused).
struct Item {
    std::uint64_t stream = 0;  ///< its position stream's address
    std::uint64_t address = 0; ///< its palette's address (0: none bound)
    std::uint32_t size = 0;    ///< the palette's bytes (its V#'s size)
    std::uint32_t bones = 0;   ///< size over 48
    Kind kind = Kind::Other;
    bool modified = false;     ///< the buffer cache calls its pages GPU-modified
    bool in_place = false;     ///< and they are bound in place
    bool box = false;          ///< sent to the GPU box judge (else turned away)
};

/// The streams the CPU palette test refused, one entry each (changed: noted again), the line that says what they are.
class Census {
public:
    /// True when the stream is new here or its entry changed (its kind, size or box route); the line is due then.
    bool Note(const Item& item) {
        const auto found = items.find(item.stream);
        if (found != items.end()) {
            Item& old = found->second;
            if (old.kind == item.kind && old.size == item.size && old.box == item.box) {
                return false;
            }
            old = item;
            dirty = true;
            return true;
        }
        if (items.size() >= CensusMost) {
            ++overflow;
            return false;
        }
        items.emplace(item.stream, item);
        dirty = true;
        return true;
    }

    [[nodiscard]] std::size_t Size() const {
        return items.size();
    }

    /// Streams of `kind` that went to the box judge (`box`) or were turned away (`!box`).
    [[nodiscard]] std::size_t Count(Kind kind, bool box) const {
        std::size_t n = 0;
        for (const auto& entry : items) {
            n += entry.second.kind == kind && entry.second.box == box ? 1u : 0u;
        }
        return n;
    }

    [[nodiscard]] std::size_t Boxed() const {
        std::size_t n = 0;
        for (const auto& entry : items) {
            n += entry.second.box ? 1u : 0u;
        }
        return n;
    }

    /// The census line when something changed since the last one (false: nothing to say). `mode` BB_WIND_HANG_BOXJUDGE,
    /// `cap` BB_WIND_HANG_BOX_BONES. Under LineChars characters.
    bool TakeLine(Mode mode, unsigned cap, std::string& out) {
        if (!dirty) {
            return false;
        }
        dirty = false;
        char head[512];
        std::snprintf(head, sizeof(head),
                      "GLINT-PROOF hang box (r112p): %zu refused streams (a+b: to the GPU box + turned away): gpu %zu+%zu, "
                      "unmapped %zu+%zu, short %zu+%zu, pivot %zu+%zu, content moved %zu+%zu; box judge %s up to %u bones (V# "
                      "bytes / 48); %zu judged, %zu turned away%s; V# bones, bytes, palette address, GPU pages, route:",
                      items.size(), Count(Kind::Gpu, true), Count(Kind::Gpu, false), Count(Kind::Unmapped, true),
                      Count(Kind::Unmapped, false), Count(Kind::Short, true), Count(Kind::Short, false),
                      Count(Kind::Pivot, true), Count(Kind::Pivot, false), Count(Kind::Moved, true), Count(Kind::Moved, false),
                      ModeName(mode), cap, Boxed(), items.size() - Boxed(), overflow != 0 ? " (census full)" : "");
        out = head;
        // the examples: the boxed streams first, then the others, each group in stream order (the same set, the same text)
        std::vector<const Item*> order;
        order.reserve(items.size());
        for (const auto& entry : items) {
            order.push_back(&entry.second);
        }
        std::sort(order.begin(), order.end(), [](const Item* a, const Item* b) {
            if (a->box != b->box) {
                return a->box;
            }
            return a->stream < b->stream;
        });
        std::size_t shown = 0;
        for (const Item* item : order) {
            if (shown >= ExamplesMost) {
                break;
            }
            char one[160];
            std::snprintf(one, sizeof(one), " %ub %uB %#llx %s %s%s%s;", item->bones, item->size,
                          static_cast<unsigned long long>(item->address), KindName(item->kind),
                          item->modified ? "modified" : "clean", item->in_place ? " in place" : "",
                          item->box ? " -> box" : " -> refused");
            out += one;
            ++shown;
        }
        if (out.size() > LineChars) {
            out.resize(LineChars - 3);
            out += "...";
        }
        return true;
    }

private:
    std::unordered_map<std::uint64_t, Item> items;
    std::size_t overflow = 0;
    bool dirty = false;
};

/// One written binding that overlaps a watched palette.
struct Hit {
    std::uint64_t shader = 0;
    std::uint32_t stage = 0;
    std::uint64_t at = 0, size = 0;       ///< the written binding
    std::uint64_t palette = 0;            ///< the watched palette's address
    std::uint32_t bytes = 0, bones = 0;   ///< its bytes and V# bones
    std::uint64_t stream = 0;             ///< its position stream
    bool inside = false;                  ///< the palette lies inside the written range (else only a page is shared)
};

/// The pages of the first palettes found GPU-written, watched for the next shader write over them (see the header).
class Watch {
public:
    /// A palette found GPU-written and not in place. False: the table is full or it is watched already.
    bool Add(std::uint64_t address, std::uint32_t size, std::uint32_t bones, std::uint64_t stream) {
        if (address == 0 || size == 0) {
            return false;
        }
        std::scoped_lock guard(lock);
        if (watched.size() >= WatchMost) {
            return false;
        }
        for (const Spot& item : watched) {
            if (item.address == address && item.size == size) {
                return false;
            }
        }
        Spot item;
        item.address = address;
        item.size = size;
        item.bones = bones;
        item.stream = stream;
        watched.push_back(item);
        watched_count.store(watched.size(), std::memory_order_relaxed);
        active.store(true, std::memory_order_relaxed);
        return true;
    }

    /// Every written storage-buffer binding (Rasterizer::BindBuffers): one relaxed load while nothing is watched.
    void Written(std::uint64_t shader, std::uint32_t stage, std::uint64_t address, std::uint64_t size) {
        if (!active.load(std::memory_order_relaxed)) {
            return;
        }
        WrittenSlow(shader, stage, address, size);
    }

    [[nodiscard]] std::size_t Watched() const {
        return watched_count.load(std::memory_order_relaxed);
    }

    [[nodiscard]] std::size_t Hits() const {
        return hit_count.load(std::memory_order_relaxed);
    }

    /// The lines of the writers found since the last call (each hit once), under LineChars characters.
    std::vector<std::string> TakeLines() {
        std::vector<std::string> out;
        std::scoped_lock guard(lock);
        for (; printed < hits.size(); ++printed) {
            const Hit& h = hits[printed];
            char buf[LineChars + 64];
            std::snprintf(buf, sizeof(buf),
                          "GLINT-PROOF hang box (r112p): palette writer %zu: a %s shader %016llx binds %#llx+%llu for writing; the "
                          "palette %#llx+%u (%u bones, stream %#llx) %s that binding (4 KiB pages assumed)",
                          printed + 1, StageName(h.stage), static_cast<unsigned long long>(h.shader),
                          static_cast<unsigned long long>(h.at), static_cast<unsigned long long>(h.size),
                          static_cast<unsigned long long>(h.palette), h.bytes, h.bones,
                          static_cast<unsigned long long>(h.stream),
                          h.inside ? "lies INSIDE" : "only SHARES a page with");
            out.emplace_back(buf);
        }
        return out;
    }

private:
    struct Spot {
        std::uint64_t address = 0, stream = 0;
        std::uint32_t size = 0, bones = 0;
    };

    void WrittenSlow(std::uint64_t shader, std::uint32_t stage, std::uint64_t address, std::uint64_t size) {
        std::scoped_lock guard(lock);
        for (const Spot& item : watched) {
            if (!SharePage(address, size, item.address, item.size)) {
                continue;
            }
            const bool seen = std::any_of(hits.begin(), hits.end(), [&](const Hit& h) {
                return h.shader == shader && h.stage == stage && h.palette == item.address;
            });
            if (seen) {
                continue;
            }
            if (hits.size() >= HitsMost) {
                active.store(false, std::memory_order_relaxed);
                return;
            }
            Hit h;
            h.shader = shader;
            h.stage = stage;
            h.at = address;
            h.size = size;
            h.palette = item.address;
            h.bytes = item.size;
            h.bones = item.bones;
            h.stream = item.stream;
            h.inside = Holds(address, size, item.address, item.size);
            hits.push_back(h);
            hit_count.store(hits.size(), std::memory_order_relaxed);
        }
    }

    std::atomic<bool> active{false};
    std::atomic<std::size_t> watched_count{0}, hit_count{0};
    std::mutex lock;
    std::vector<Spot> watched;
    std::vector<Hit> hits;
    std::size_t printed = 0;
};

/// The counts of one report window (the periodic line).
struct Stats {
    std::uint64_t box_draws = 0;   ///< draws of a stream routed to the box judge
    std::uint64_t turned_away = 0; ///< draws of a refused stream the box judge did not take
    std::uint64_t words = 0;       ///< hang words of a box-judged stream with a push
    std::uint64_t ramping = 0;     ///< of them, still in the ramp's rise
};

/// The once-line.
[[nodiscard]] inline std::string OnceText(Mode mode, unsigned cap, float gain, float max_bottom) {
    char buf[900];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112p): %s: a skinned stream the CPU palette test refuses (unread: GPU-written, not mapped, "
                  "short, no pivot%s) is judged by r112f's GPU box instead when "
                  "its palette has at most %u bones (BB_WIND_HANG_BOX_BONES; the V# size is a capacity, not the rig), r112h's "
                  "bone rule reads one bone for it, and it is pushed like a static lantern (gain %.2f, BB_WIND_HANG_STATIC_GAIN, "
                  "live; its bottom moves at most %.3f m), pivot at the top key of its slot; reasons: why 1 unread, why 5 "
                  "content moved; 'GLINT-PROOF hang box (r112p)' lines: the census and the palette writers",
                  mode == Mode::Off ? "OFF (BB_WIND_HANG_BOXJUDGE=0: as r112o)"
                  : mode == Mode::Unread ? "on, unread palettes only (BB_WIND_HANG_BOXJUDGE=unread)"
                                         : "on (BB_WIND_HANG_BOXJUDGE unset or 1: unread palettes and moved content)",
                  mode == Mode::All ? "; or its content differs from the first draw's" : "", cap, double(gain),
                  double(max_bottom));
    return std::string(buf);
}

/// The periodic line (every report): `census` the refused streams, `watch` the writers, `stats` this window's counts.
[[nodiscard]] inline std::string StatsText(const Stats& stats, const Census& census, std::size_t watched, std::size_t hits,
                                           float gain) {
    char buf[420];
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112p): refused streams %zu, %zu judged by the GPU box (gpu %zu, moved %zu); in %u frames %llu "
                  "draws of them went to the judge, %llu were turned away, %llu got a push (%llu still in the rise), gain %.2f; "
                  "palette pages watched %zu, writers found %zu",
                  census.Size(), census.Boxed(), census.Count(Kind::Gpu, true), census.Count(Kind::Moved, true),
                  BbWindSway::ReportFrames, n(stats.box_draws), n(stats.turned_away), n(stats.words), n(stats.ramping),
                  double(gain), watched, hits);
    return std::string(buf);
}

} // namespace BbWindHangGpu
''',
    TG: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112p_hang-gpu-palette-lanterns): skinned hanging things the CPU palette test refuses
// (gpu/shim/bbport_wind_hang_gpu.h): the knobs, the kinds, who the GPU box judge may take (BoxJudgeable), the
// page tests, the census and its line, the palette writer watch, the book's new reason (5) and box route, the texts.
// The twin in Python (r112p_twin.py) holds the same cases.
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "gpu/shim/bbport_wind_hang_find.h"
#include "gpu/shim/bbport_wind_hang_gpu.h"

namespace G = BbWindHangGpu;
namespace S = BbWindHangStill;
namespace F = BbWindHangFind;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

bool Has(const std::string& text, const char* needle) {
    return text.find(needle) != std::string::npos;
}

S::Entry MakeEntry(std::uint32_t bones, S::Why never) {
    S::Entry e;
    e.size = bones * S::BoneBytes;
    e.bones = bones;
    e.never = never;
    return e;
}

G::Item MakeItem(std::uint64_t stream, G::Kind kind, bool box) {
    G::Item item;
    item.stream = stream;
    item.address = 0x7f0000001000ull + stream * 0x40;
    item.size = 4032;
    item.bones = 84;
    item.kind = kind;
    item.modified = true;
    item.box = box;
    return item;
}
} // namespace

int main() {
    // the knobs
    Expect(G::ParseMode(nullptr) == G::Mode::All && G::ParseMode("1") == G::Mode::All && G::ParseMode("") == G::Mode::All &&
               G::ParseMode("00") == G::Mode::All && G::ParseMode("Unread") == G::Mode::All && G::ParseMode("0") == G::Mode::Off &&
               G::ParseMode("unread") == G::Mode::Unread,
           "knobs: BOXJUDGE is all unless exactly 0 (off) or unread");
    Expect(std::string(G::ModeName(G::Mode::Off)) == "OFF" && std::string(G::ModeName(G::Mode::Unread)) == "unread" &&
               std::string(G::ModeName(G::Mode::All)) == "all",
           "knobs: mode names");
    Expect(G::ParseBones(nullptr) == 96 && G::ParseBones("200") == 200 && G::ParseBones("5") == G::BonesMin &&
               G::ParseBones("9999") == G::BonesMax && G::ParseBones("abc") == 96 && G::ParseBones("nan") == 96 &&
               G::ParseBones("") == 96,
           "knobs: the bone cap defaults to 96 and is held to 13 to 341");

    // the kinds
    const S::Entry gpu84 = MakeEntry(84, S::Why::GpuWritten);
    const S::Entry unmapped = MakeEntry(28, S::Why::NotMapped);
    const S::Entry shorter = MakeEntry(48, S::Why::Short);
    const S::Entry pivot = MakeEntry(13, S::Why::NoPivot);
    const S::Entry nopal = MakeEntry(0, S::Why::NoPalette);
    const S::Entry character = MakeEntry(277, S::Why::Character);
    const S::Entry plain = MakeEntry(69, S::Why::None);
    Expect(G::KindOf(&gpu84, S::Result::Never) == G::Kind::Gpu && G::KindOf(&unmapped, S::Result::Never) == G::Kind::Unmapped &&
               G::KindOf(&shorter, S::Result::Never) == G::Kind::Short && G::KindOf(&pivot, S::Result::Never) == G::Kind::Pivot &&
               G::KindOf(&nopal, S::Result::Never) == G::Kind::NoPal &&
               G::KindOf(&character, S::Result::Never) == G::Kind::Character &&
               G::KindOf(&plain, S::Result::Moved) == G::Kind::Moved && G::KindOf(&plain, S::Result::Same) == G::Kind::Same &&
               G::KindOf(nullptr, S::Result::Never) == G::Kind::Other && G::KindOf(&plain, S::Result::Never) == G::Kind::Other &&
               G::KindOf(nullptr, S::Result::Moved) == G::Kind::Moved,
           "kinds: each refusal has its own kind");
    Expect(std::string(G::KindName(G::Kind::Gpu)) == "gpu" && std::string(G::KindName(G::Kind::Moved)) == "moved" &&
               std::string(G::KindName(G::Kind::Character)) == "char" && std::string(G::KindName(G::Kind::Other)) == "other",
           "kinds: names");

    // who the GPU box judge may take
    Expect(G::BoxJudgeable(&gpu84, S::Result::Never, 96) && G::BoxJudgeable(&unmapped, S::Result::Never, 96) &&
               G::BoxJudgeable(&shorter, S::Result::Never, 96) && G::BoxJudgeable(&pivot, S::Result::Never, 96),
           "judge: a palette that could not be read, up to the cap, goes to the GPU box");
    Expect(!G::BoxJudgeable(&gpu84, S::Result::Never, 60) && G::BoxJudgeable(&gpu84, S::Result::Never, 84),
           "judge: the cap is the V#'s bones: 84 bones need a cap of 84");
    const S::Entry big_gpu = MakeEntry(128, S::Why::GpuWritten);
    Expect(!G::BoxJudgeable(&big_gpu, S::Result::Never, 96) && G::BoxJudgeable(&big_gpu, S::Result::Never, 200),
           "judge: 128 unread bones stay refused at the default cap and are taken when the cap is raised");
    Expect(!G::BoxJudgeable(&character, S::Result::Never, 341), "judge: a readable palette of more than 96 bones is a character, never judged");
    Expect(G::BoxJudgeable(&plain, S::Result::Moved, 96) && !G::BoxJudgeable(&plain, S::Result::Same, 96) &&
               !G::BoxJudgeable(&plain, S::Result::Never, 96),
           "judge: a palette whose content moved goes to the box, a still one needs no judge, no reason is no case");
    Expect(!G::BoxJudgeable(&plain, S::Result::Moved, 96, false) && G::BoxJudgeable(&gpu84, S::Result::Never, 96, false) &&
               G::BoxJudgeable(&plain, S::Result::Moved, 96, true),
           "judge: Mode::Unread leaves the moved content out and keeps the unread palettes");
    Expect(!G::BoxJudgeable(&nopal, S::Result::Never, 96) && !G::BoxJudgeable(nullptr, S::Result::Never, 96) &&
               !G::BoxJudgeable(nullptr, S::Result::Moved, 96),
           "judge: no bones, no palette entry: refused");

    // the page tests
    Expect(G::SharePage(0x1000, 0x40, 0x1ff0, 0x20) && !G::SharePage(0x1000, 0x40, 0x2000, 0x10) &&
               G::SharePage(0x1fff, 2, 0x2000, 1) && !G::SharePage(0x1000, 0, 0x1000, 8) && !G::SharePage(0x1000, 8, 0x1000, 0),
           "pages: sharing a 4 KiB page, the end of the last page counts, empty ranges share nothing");
    Expect(G::Holds(0x1000, 0x1000, 0x1100, 0x40) && !G::Holds(0x1000, 0x100, 0x10f0, 0x40) && G::Holds(0x1000, 0x40, 0x1000, 0x40) &&
               !G::Holds(0x1100, 0x40, 0x1000, 0x40),
           "pages: a range holds another only when all of it lies inside");

    // the census
    {
        G::Census census;
        Expect(census.Size() == 0, "census: starts empty");
        std::string line;
        Expect(!census.TakeLine(G::Mode::All, 96, line), "census: nothing noted, no line");
        Expect(census.Note(MakeItem(1, G::Kind::Gpu, true)) && !census.Note(MakeItem(1, G::Kind::Gpu, true)),
               "census: a new stream is news, the same again is not");
        Expect(census.Note(MakeItem(2, G::Kind::Moved, false)) && census.Note(MakeItem(1, G::Kind::Gpu, false)),
               "census: a changed route is news again");
        Expect(census.Size() == 2 && census.Count(G::Kind::Gpu, false) == 1 && census.Count(G::Kind::Gpu, true) == 0 &&
                   census.Count(G::Kind::Moved, false) == 1 && census.Boxed() == 0,
               "census: counts by kind and route");
        census.Note(MakeItem(3, G::Kind::Gpu, true));
        census.Note(MakeItem(4, G::Kind::Moved, true));
        Expect(census.Boxed() == 2 && census.Count(G::Kind::Moved, true) == 1, "census: boxed streams");
        Expect(census.TakeLine(G::Mode::All, 96, line), "census: a change gives a line");
        Expect(Has(line, "GLINT-PROOF hang box (r112p): 4 refused streams") && Has(line, "gpu 1+1") && Has(line, "content moved 1+1") &&
                   Has(line, "box judge all up to 96 bones") && Has(line, "2 judged, 2 turned away") && Has(line, "84b 4032B") &&
                   Has(line, "-> box") && Has(line, "-> refused") && line.size() <= G::LineChars,
               "census: the line says what the streams are");
        Expect(!census.TakeLine(G::Mode::All, 96, line), "census: the line comes once per change");
        census.Note(MakeItem(5, G::Kind::Short, true));
        std::string off;
        Expect(census.TakeLine(G::Mode::Off, 60, off) && Has(off, "box judge OFF up to 60 bones"), "census: the knob state is in the line");
        census.Note(MakeItem(6, G::Kind::Gpu, true));
        std::string unread_line;
        Expect(census.TakeLine(G::Mode::Unread, 96, unread_line) && Has(unread_line, "box judge unread up to 96 bones"), "census: the unread mode is in the line");
        G::Census full;
        for (std::uint64_t i = 1; i <= G::CensusMost + 3; ++i) {
            full.Note(MakeItem(i, G::Kind::Gpu, false));
        }
        std::string full_line;
        Expect(full.Size() == G::CensusMost && full.TakeLine(G::Mode::All, 96, full_line) && Has(full_line, "(census full)") &&
                   full_line.size() <= G::LineChars,
               "census: at most CensusMost streams, the line says it is full and stays capped");
    }

    // the writer watch
    {
        G::Watch watch;
        watch.Written(0xabcdull, 5, 0x7f0000001000ull, 0x2000); // nothing watched: nothing noted
        Expect(watch.Hits() == 0 && watch.Watched() == 0 && watch.TakeLines().empty(), "watch: nothing watched, nothing noted");
        Expect(!watch.Add(0, 4032, 84, 1) && !watch.Add(0x7f0000001000ull, 0, 84, 1), "watch: no address or no bytes is not watched");
        Expect(watch.Add(0x7f0000001100ull, 4032, 84, 0x55) && !watch.Add(0x7f0000001100ull, 4032, 84, 0x55) && watch.Watched() == 1,
               "watch: one palette once");
        watch.Written(0x1111ull, 5, 0x7f0000009000ull, 0x1000); // elsewhere
        Expect(watch.Hits() == 0, "watch: a write elsewhere is no hit");
        watch.Written(0x1111ull, 5, 0x7f0000001000ull, 0x4000); // holds the palette
        watch.Written(0x1111ull, 5, 0x7f0000001000ull, 0x4000); // the same writer again: once
        watch.Written(0x2222ull, 3, 0x7f0000002000ull, 0x10);   // only shares the page of the palette's end
        std::vector<std::string> lines = watch.TakeLines();
        Expect(watch.Hits() == 2 && lines.size() == 2 && Has(lines[0], "palette writer 1: a compute shader 0000000000001111") &&
                   Has(lines[0], "lies INSIDE that binding") && Has(lines[1], "palette writer 2: a vertex shader 0000000000002222") &&
                   Has(lines[1], "only SHARES a page") && Has(lines[0], "(84 bones, stream 0x55)") &&
                   lines[0].size() <= G::LineChars + 64,
               "watch: a writer is named once with its shader, its stage and how it meets the palette");
        Expect(watch.TakeLines().empty(), "watch: each hit is taken once");
        for (std::uint64_t i = 0; i < 20; ++i) {
            watch.Written(0x9000ull + i, 5, 0x7f0000001000ull, 0x4000);
        }
        Expect(watch.Hits() == G::HitsMost, "watch: at most HitsMost writers");
        G::Watch many;
        std::size_t added = 0;
        for (std::uint64_t i = 0; i < G::WatchMost + 4; ++i) {
            added += many.Add(0x7f0000100000ull + i * 0x10000, 640, 13, i + 1) ? 1u : 0u;
        }
        Expect(added == G::WatchMost && many.Watched() == G::WatchMost, "watch: at most WatchMost palettes");
    }

    // the book's reasons and the box route
    {
        BbWindHang::Book book;
        book.Note(7, 4096, 0, false, 1, 0xe859b6d9ull, 5, 0); // the palette's content differed
        book.Note(8, 4096, 0, false, 1, 0xe859b6d9ull);        // unread (defaults: why 1)
        book.Note(9, 4096, 0, true, 1, 0xe859b6d9ull, 1, 2);   // sent to the box judge: not moving, box route 2
        book.Note(10, 4096, 0, true, 1, 0xe859b6d9ull, 1, 1);
        book.Note(7, 4096, 0, false, 2, 0xe859b6d9ull, 1, 0);  // the first reason stays
        const BbWindHang::Entry* const content = book.Find(7);
        const BbWindHang::Entry* const unread = book.Find(8);
        const BbWindHang::Entry* const boxed = book.Find(9);
        const BbWindHang::Entry* const boxed_unread = book.Find(10);
        Expect(content != nullptr && unread != nullptr && boxed != nullptr && boxed_unread != nullptr && content->moving &&
                   content->why_moving == 5 && unread->moving && unread->why_moving == 1 && !boxed->moving &&
                   boxed->why_moving == 0 && boxed->box_only == 2 && boxed_unread->box_only == 1 && content->box_only == 0 &&
                   unread->box_only == 0,
               "book: why 5 for a changed content, why 1 for unread, the box route kept, the first reason stays");
        book.Note(9, 4096, 0, true, 2, 0xe859b6d9ull); // a later draw with the defaults: no box route
        Expect(book.Find(9)->box_only == 0, "book: the box route is the last draw's (a draw without it clears it)");
    }

    // the texts
    Expect(Has(F::MovingWhy(5, 0), "differs from the first draw's") && Has(F::MovingWhy(5, 0), "never measured") &&
               Has(F::MovingWhy(1, 0), "could not be read"),
           "texts: the reasons 1 and 5");
    {
        F::CandInfo pushed;
        pushed.e.height = 1.84f;
        pushed.hang = true;
        pushed.judged = true;
        pushed.fits = true;
        pushed.span = 1.84f;
        const std::string plain_text = F::CandState(pushed, 2.5f, 0.2f, true, 0.35f);
        pushed.box_only = 2;
        const std::string moved_text = F::CandState(pushed, 2.5f, 0.2f, true, 0.35f);
        pushed.box_only = 1;
        const std::string unread_text = F::CandState(pushed, 2.5f, 0.2f, true, 0.35f);
        Expect(Has(plain_text, "PUSHED:") && !Has(plain_text, "GPU box") && Has(moved_text, "PUSHED:") &&
                   Has(moved_text, "[judged by the GPU box: palette content moved]") &&
                   Has(unread_text, "[judged by the GPU box: palette unread]") && moved_text.size() < 320,
               "texts: a box-judged candidate's state says so");
    }
    {
        const std::string once = G::OnceText(G::Mode::All, 96, 0.2f, 0.08f);
        const std::string unread_once = G::OnceText(G::Mode::Unread, 96, 0.2f, 0.08f);
        const std::string off = G::OnceText(G::Mode::Off, 96, 0.2f, 0.08f);
        Expect(Has(once, "Wind sway hang (r112p): on (BB_WIND_HANG_BOXJUDGE unset or 1") && Has(once, "or its content differs") &&
                   Has(once, "at most 96 bones") && Has(once, "gain 0.20") && Has(once, "at most 0.080 m") &&
                   Has(unread_once, "on, unread palettes only") && !Has(unread_once, "or its content differs") &&
                   Has(off, "OFF (BB_WIND_HANG_BOXJUDGE=0: as r112o)"),
               "texts: the once-line");
        G::Stats stats;
        stats.box_draws = 120;
        stats.turned_away = 7;
        stats.words = 90;
        stats.ramping = 12;
        G::Census census;
        census.Note(MakeItem(1, G::Kind::Gpu, true));
        census.Note(MakeItem(2, G::Kind::Moved, true));
        census.Note(MakeItem(3, G::Kind::Moved, false));
        const std::string line = G::StatsText(stats, census, 2, 1, 0.2f);
        Expect(Has(line, "refused streams 3, 2 judged by the GPU box (gpu 1, moved 1)") && Has(line, "120 draws of them went to the judge") &&
                   Has(line, "7 were turned away") && Has(line, "90 got a push (12 still in the rise)") &&
                   Has(line, "palette pages watched 2, writers found 1") && line.size() < 420,
               "texts: the periodic line");
    }

    if (failures != 0) {
        std::printf("%d failures\n", failures);
        return 1;
    }
    std::printf("wind-hang-gpu-test: all passed\n");
    return 0;
}
''',
}

# ---- bbport_wind_hang.h -------------------------------------------------------------------------------
H1 = r"""    std::uint32_t moved_after = 0; ///< bbport (r112n): the frames counted before the bytes changed (2), or r112h's rule's number (4)"""
H1P = r"""
    std::uint8_t box_only = 0; ///< bbport (r112p_hang-gpu-palette-lanterns): the GPU box judges it in place of its palette: 1 the palette could not be read, 2 its content differed (0: no)"""

H2 = r"""    Verdict Note(std::uint64_t stream, std::uint32_t size, std::uint64_t hash, bool readable,
                 std::uint64_t frame, std::uint64_t vs) {"""
H2N = r"""    Verdict Note(std::uint64_t stream, std::uint32_t size, std::uint64_t hash, bool readable,
                 std::uint64_t frame, std::uint64_t vs, std::uint8_t unread_why = 1,
                 std::uint8_t box_only = 0) { // bbport (r112p_hang-gpu-palette-lanterns): why 5: the content differed; the box route"""

H3 = r"""        e.seen = frame;
        e.vs = vs;
        if (!readable) {
            if (!e.moving) { // bbport (r112n_hang-teleport-camera): the first reason is kept
                e.why_moving = 1;
            }"""
H3N = r"""        e.seen = frame;
        e.vs = vs;
        e.box_only = box_only; // bbport (r112p_hang-gpu-palette-lanterns): the last draw's route
        if (!readable) {
            if (!e.moving) { // bbport (r112n_hang-teleport-camera): the first reason is kept
                e.why_moving = unread_why; // bbport (r112p): 1 the palette could not be read, 5 its content differed
            }"""

# ---- bbport_wind_hang_find.h --------------------------------------------------------------------------
F1 = r"""    default:
        std::snprintf(buf, sizeof(buf), "the reason was not recorded");"""
F1PRE = r"""    case 5: // bbport (r112p_hang-gpu-palette-lanterns): the palette was read and its content differed
        std::snprintf(buf, sizeof(buf),
                      "its palette's content differs from the first draw's (an animated skeleton, or instances of the stream posed "
                      "differently); its keys are never measured while it is held");
        break;
"""

F2 = r"""    std::uint32_t moved_after = 0;  ///< bbport (r112n): and its number (frames counted, or r112h's rule's number)"""
F2P = r"""
    std::uint8_t box_only = 0;      ///< bbport (r112p_hang-gpu-palette-lanterns): judged by the GPU box in place of its palette: 1 unread, 2 content moved"""

F3 = r"""            c.moved_after = h->moved_after;"""
F3P = r"""
            c.box_only = h->box_only; // bbport (r112p_hang-gpu-palette-lanterns)"""

F4 = r"""        std::snprintf(buf, sizeof(buf), "PUSHED: scale %.2f, its bottom moves %.3f m now (push %.3f m, gain %.2f, %s)",
                      double(scale), double(BottomPush(push_now, gain, scale, same)), double(push_now),
                      double(ClampGain(gain)), same ? "same bottom push for every size" : "scaled by its height");"""
F4P = r"""
        if (c.box_only != 0) { // bbport (r112p_hang-gpu-palette-lanterns): the GPU box judged it, not its palette
            const std::size_t used = std::char_traits<char>::length(buf);
            std::snprintf(buf + used, sizeof(buf) - used, " [judged by the GPU box: palette %s]",
                          c.box_only == 2 ? "content moved" : "unread");
        }"""

# ---- vk_rasterizer.h ------------------------------------------------------------------------------------
V1 = r"""#include "bbport_wind_hang_actors.h" // bbport (r112h_hang-not-the-hunter)"""
V1P = r"""
#include "bbport_wind_hang_gpu.h" // bbport (r112p_hang-gpu-palette-lanterns)"""

V2 = r"""    bool hang_judge = false; // set by WindHangVerdict: this draw's stream wants the judging word"""
V2P = r"""
    /// bbport (r112p_hang-gpu-palette-lanterns): the streams the CPU palette test refuses (census), the pages of the first
    /// GPU-written palettes watched for a shader write (watch; fed by BindBuffers), the counts of the report window
    BbWindHangGpu::Census hang_gpu_census;
    BbWindHangGpu::Watch hang_gpu_watch;
    BbWindHangGpu::Stats hang_gpu_stats;"""

# ---- vk_rasterizer.cpp ------------------------------------------------------------------------------------
C1 = r"""const VideoCore::InvalidateReason reason{"storage buffer"};"""
C1PRE = r"""hang_gpu_watch.Written(stage.pgm_hash, static_cast<u32>(stage.sw_stage), vsharp.base_address, size); // bbport (r112p_hang-gpu-palette-lanterns): palette writers (BB_WIND_HANG)
                    """

# ---- vk_rasterizer_effects.cpp ---------------------------------------------------------------------------
E1 = r"""    bool forced = false; // bbport (r112e_hang-taken): read although the GPU wrote its page"""
E1P = r"""
    u64 palette_address = 0; // bbport (r112p_hang-gpu-palette-lanterns): the palette's address and the buffer cache's word on its pages
    bool palette_modified = false;"""

E2 = r"""        palette_size = size;
        const bool gpu = buffer_cache.IsRegionGpuModified(buffer.base_address, size);"""
E2N = r"""        palette_size = size;
        palette_address = buffer.base_address; // bbport (r112p_hang-gpu-palette-lanterns)
        const bool gpu = buffer_cache.IsRegionGpuModified(buffer.base_address, size);
        palette_modified = gpu;"""

E3 = r"""    const bool gpu = BbWindHangStill::BoxAvailable() && object_motion->SwayWords() != nullptr &&
                     (hang_static ||
                      BbWindHangStill::GpuJudgeable(hang_still.Find(positions), content));
    const bool still = content == BbWindHangStill::Result::Same || gpu;
    const BbWindHang::Verdict verdict =
        hang_book.Note(positions, positions_size, 0, still, frame, vs.pgm_hash);"""
E3N = r"""    // bbport (r112p_hang-gpu-palette-lanterns): the stream's palette entry and whether the sway keys exist, read once
    const BbWindHangStill::Entry* const palette_entry = hang_static ? nullptr : hang_still.Find(positions);
    const bool box_keys = BbWindHangStill::BoxAvailable() && object_motion->SwayWords() != nullptr;
    bool gpu = box_keys && (hang_static || BbWindHangStill::GpuJudgeable(palette_entry, content));
    // bbport (r112p_hang-gpu-palette-lanterns): a stream the palette test refuses (its content moved, or a palette that could not
    // be read, up to BB_WIND_HANG_BOX_BONES bones) is judged by the GPU's box all the same: the box needs no palette, r112f's judge
    // decides (a mover's box grows), and the stream is pushed like a static lantern (box_only: WindHangActorsClear, WindHangWord).
    // The census says what the refused streams are; the first GPU-written palettes have their pages watched for the shader that
    // writes them (BindBuffers). BB_WIND_HANG_BOXJUDGE=0: none of the routing (r112o)
    std::uint8_t box_only = 0;
    if (!hang_static && content != BbWindHangStill::Result::Same) {
        const bool box_ok = box_keys && BbWindHangGpu::BoxOn() &&
                            BbWindHangGpu::BoxJudgeable(palette_entry, content, BbWindHangGpu::BoxBones(),
                                                        BbWindHangGpu::ModeOnce() == BbWindHangGpu::Mode::All);
        BbWindHangGpu::Item refused;
        refused.stream = positions;
        refused.address = palette_address;
        refused.size = palette_size;
        refused.bones = palette_entry != nullptr ? palette_entry->bones : 0u;
        refused.kind = BbWindHangGpu::KindOf(palette_entry, content);
        refused.modified = palette_modified;
        refused.in_place = in_place;
        refused.box = box_ok;
        if (hang_gpu_census.Note(refused) && refused.kind == BbWindHangGpu::Kind::Gpu && !in_place) {
            hang_gpu_watch.Add(refused.address, refused.size, refused.bones, positions);
        }
        if (box_ok) {
            gpu = true;
            box_only = static_cast<std::uint8_t>(content == BbWindHangStill::Result::Moved ? 2 : 1);
            ++hang_gpu_stats.box_draws;
        } else if (!gpu) {
            ++hang_gpu_stats.turned_away;
        }
    }
    const bool still = content == BbWindHangStill::Result::Same || gpu;
    const BbWindHang::Verdict verdict =
        hang_book.Note(positions, positions_size, 0, still, frame, vs.pgm_hash,
                       content == BbWindHangStill::Result::Moved ? std::uint8_t{5} : std::uint8_t{1}, box_only);"""

E4 = r"""    const A::Why why =
        A::Judge(knobs, box, hang_static ? 1u : bones, hunter, open, have_field, &side);
    BbWindHang::Entry* const entry = hang_book.Find(positions);"""
E4N = r"""    BbWindHang::Entry* const entry = hang_book.Find(positions);
    // bbport (r112p_hang-gpu-palette-lanterns): a stream the GPU box judges in place of its palette has no bone count to test (an
    // unread palette's V# size is a capacity, a moving one's rig is not what the game draws it with): the one-bone stand-in of the
    // static meshes; the hunter's gear is kept off by the NEAR rule, the box and the indoor rule as before
    const bool box_only = entry != nullptr && entry->box_only != 0;
    const A::Why why =
        A::Judge(knobs, box, (hang_static || box_only) ? 1u : bones, hunter, open, have_field, &side);"""

E5 = r"""    return BbWindHang::HangWord(frame_slot, view, slot,
                                placed_ok ? BbWindHangFind::SameRamp(hang_ramp, WindHangGainNow(), hang_scale,
                                                                     BbWindHangFind::SameKnob())
                                          : hang_ramp);"""
E5N = r"""    // bbport (r112p_hang-gpu-palette-lanterns): a stream the GPU box judges in place of its palette (box_only) is pushed like a
    // static lantern: its ramp goes through SameRamp (BB_WIND_HANG_STATIC_GAIN, live; the bottom moves min(scale, gain) x push),
    // its pivot the top key of its slot (the shaders' top rule), as for every hanging thing
    const bool box_only = entry->box_only != 0;
    const u32 pushed_ramp = (placed_ok || box_only)
                                ? BbWindHangFind::SameRamp(hang_ramp, WindHangGainNow(), hang_scale, BbWindHangFind::SameKnob())
                                : hang_ramp;
    if (box_only) {
        ++hang_gpu_stats.words;
        hang_gpu_stats.ramping += m.ramp < 255 ? 1 : 0;
    }
    return BbWindHang::HangWord(frame_slot, view, slot, pushed_ramp);"""

E6 = r"""    // bbport (r112g_hang-judge-settles): its line once (BB_WIND_HANG on)"""
E6PRE = r"""    // bbport (r112p_hang-gpu-palette-lanterns): its line once (BB_WIND_HANG on)
    static bool hang_boxj_said = false;
    if (!hang_boxj_said && BbWindHang::KnobOnce().on) {
        hang_boxj_said = true;
        BbReport::Printf("%s\n", BbWindHangGpu::OnceText(BbWindHangGpu::ModeOnce(), BbWindHangGpu::BoxBones(),
                                                          BbWindHangFind::GainKnob(),
                                                          BbWindHangFind::GainKnob() * BbWindSway::MaxAlong)
                                    .c_str());
    }
"""

E7 = r"""        hang_box.ClearNotes();"""
E7PRE = r"""        // bbport (r112p_hang-gpu-palette-lanterns): the refused streams' census and the palette writers (each when new), then
        // this window's counts
        std::string gpu_census_line;
        if (hang_gpu_census.TakeLine(BbWindHangGpu::ModeOnce(), BbWindHangGpu::BoxBones(), gpu_census_line)) {
            BbReport::Printf("%s\n", gpu_census_line.c_str());
        }
        for (const std::string& writer_line : hang_gpu_watch.TakeLines()) {
            BbReport::Printf("%s\n", writer_line.c_str());
        }
        BbReport::Printf("%s\n", BbWindHangGpu::StatsText(hang_gpu_stats, hang_gpu_census, hang_gpu_watch.Watched(),
                                                           hang_gpu_watch.Hits(), WindHangGainNow())
                                     .c_str());
        hang_gpu_stats = {};
"""

# ---- README.md ---------------------------------------------------------------------------------------------
R1 = r"""| `BB_WIND_HANG_PROOF` |"""
R1P = r"""| `BB_WIND_HANG_BOXJUDGE` | Part of `BB_WIND_HANG` (r112p; default on, exactly `0` gives r112o back, exactly `unread` takes only the palettes that could not be read). A skinned sun-drawn stream that r112's palette test refuses is judged by r112f's GPU box (its world box must not grow 20 mm over 60 frames; 250 mm is a character for good) instead of by its palette: when the palette's content differed from the first draw's (why 5: an animated skeleton, or other instances of the stream posed differently; r112n called every refusal "could not be read"), or the palette could not be read (why 1: GPU-written and not in place, not mapped, too short, no pivot) and has at most `BB_WIND_HANG_BOX_BONES` bones. `BB_WIND_HANG_BOXJUDGE=unread` takes only the second kind (a test: the first may let a figure that stands very still be pushed 0.08 m at most). The bracket lanterns in the graveyard trees were turned away this way (b63). r112h's figure rule reads one bone for such a stream (the hunter's gear stays out by the NEAR rule and the box); it is pushed like a static lantern (`BB_WIND_HANG_STATIC_GAIN`, live `set:`/`unset:`): its bottom moves min(scale, gain) x push, downwind, settling in 1.6 s, pivot at the top key of its slot (the top 0.3 m still). Static streams (r112i) are not touched. Log: `Wind sway hang (r112p)` once and every 600 frames (refused streams, judged by the box, draws, pushed words, palette pages watched, writers found) and the `GLINT-PROOF hang box (r112p)` lines: the census (per refused stream: V# bones and bytes, palette address, GPU-modified pages, in place, route) when it changes, and each shader that writes a watched palette's 4 KiB page once (its hash, stage, and whether the palette lies INSIDE the written range or only SHARES a page). Off: no hang code runs without `BB_WIND_HANG`; the only hook outside it is one relaxed load of a false atomic per written storage-buffer binding. |
| `BB_WIND_HANG_BOX_BONES` | Part of `BB_WIND_HANG_BOXJUDGE` (r112p; 13 to 341, default `96`, text that is no number gives the default). The most bones (the palette V#'s size over 48: a capacity the game binds, not the mesh's rig) of a stream the GPU box judge takes in place of the palette test. More bones stay refused (the hunter's palette has 277); a readable palette of more than 96 bones is a character and is never judged, whatever this says. |
"""

# ---- gpu/CMakeLists.txt, build.sh ----------------------------------------------------------------------------
M1 = r"""target_include_directories(wind-hang-find-test PRIVATE ..)"""
M1P = r"""
# bbport (r112p_hang-gpu-palette-lanterns): skinned hanging things the CPU palette test refuses, judged by the GPU box
# (shim/bbport_wind_hang_gpu.h); also built and run by engine/build.sh --test.
add_executable(wind-hang-gpu-test EXCLUDE_FROM_ALL ../tests/test_wind_hang_gpu.cpp)
target_compile_options(wind-hang-gpu-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-hang-gpu-test PRIVATE ..)"""

B1 = r"""tests/test_wind_hang_find.cpp -o out/wind-hang-find-test
    out/wind-hang-find-test"""
B1P = r"""
    # bbport (r112p_hang-gpu-palette-lanterns): skinned hanging things the CPU palette test refuses, judged by the GPU box
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_wind_hang_gpu.cpp -o out/wind-hang-gpu-test
    out/wind-hang-gpu-test"""

EDITS = {
HH: [
('ins', H1, "", H1P),
('rep', H2, "", H2N),
('rep', H3, "", H3N),
],
HF: [
('ins', F1, F1PRE, ""),
('ins', F2, "", F2P),
('ins', F3, "", F3P),
('ins', F4, "", F4P),
],
RH: [
('ins', V1, "", V1P),
('ins', V2, "", V2P),
],
RC: [
('ins', C1, C1PRE, ""),
],
EF: [
('ins', E1, "", E1P),
('rep', E2, "", E2N),
('rep', E3, "", E3N),
('rep', E4, "", E4N),
('rep', E5, "", E5N),
('ins', E6, E6PRE, ""),
('ins', E7, E7PRE, ""),
],
RM: [
('ins', R1, R1P, ""),
],
CM: [
('ins', M1, "", M1P),
],
BS: [
('ins', B1, "", B1P),
],
}

ORDER = (HH, HF, RH, RC, EF, RM, CM, BS)
NEW_ORDER = (HG, TG)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def parts_of(ed):
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


def new_state(path):
    """clean: the file is absent; applied: it is there with the patch's text; anything else refuses."""
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    have = open(full, "rb").read().decode("utf-8").replace("\r\n", "\n")
    if have != NEW_FILES[path]:
        raise SystemExit("REFUSED %s: the file exists and is not this patch's" % path)
    return "applied"


def balance(text):
    """(braces, parens, brackets) net of a C++ text without comments, strings and char literals."""
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', text)
    text = re.sub(r"'(?:\\.|[^'\\\n])'", "' '", text)
    return (text.count("{") - text.count("}"), text.count("(") - text.count(")"),
            text.count("[") - text.count("]"))


CPP = (HH, HF, RH, RC, EF)


def text_checks(texts, olds):
    """The ties a compiler cannot check."""
    hh, hf, rh, rc, ef = texts[HH], texts[HF], texts[RH], texts[RC], texts[EF]
    hg, tg = NEW_FILES[HG], NEW_FILES[TG]
    for path in CPP:
        if balance(texts[path]) != balance(olds[path]):
            raise SystemExit("text check: %s: braces, parens or brackets changed by %r" %
                             (path, tuple(a - b for a, b in zip(balance(texts[path]), balance(olds[path])))))
    for path, text in ((HG, hg), (TG, tg)):
        if balance(text) != (0, 0, 0):
            raise SystemExit("text check: %s: braces, parens or brackets do not balance: %r" % (path, balance(text)))
        if "\t" in text:
            raise SystemExit("text check: a tab in %s" % path)
        try:
            text.encode("ascii")
        except UnicodeEncodeError:
            raise SystemExit("text check: %s is not ASCII" % path)
    for part in (E3N, E4N, E5N, E6PRE, E7PRE, F1PRE, F4P):
        if balance(part) != (0, 0, 0):
            raise SystemExit("text check: an inserted block does not balance: %r" % part[:60])
    # the header's names and their order of declaration
    for needle in ("enum class Mode : std::uint8_t { Off, Unread, All };", "inline Mode ModeOnce()", "inline Mode ParseMode(", "inline bool BoxOn()", "inline unsigned BoxBones()", "inline bool BoxJudgeable(", "inline Kind KindOf(",
                   "class Census {", "class Watch {", "struct Stats {", "inline std::string OnceText(", "inline std::string StatsText(",
                   "inline bool SharePage(", "inline bool Holds(", "void WrittenSlow(", "std::vector<std::string> TakeLines()",
                   "bool TakeLine(Mode mode, unsigned cap, std::string& out)"):
        if needle not in hg:
            raise SystemExit("text check: %s missing in the new header" % needle)
    for first, second in (("enum class Kind", "inline const char* KindName("), ("inline const char* KindName(", "inline Kind KindOf("),
                          ("inline Kind KindOf(", "inline bool BoxJudgeable("), ("struct Item {", "class Census {"),
                          ("inline bool SharePage(", "class Watch {"), ("inline bool Holds(", "class Watch {"),
                          ("inline const char* StageName(", "class Watch {"), ("struct Hit {", "class Watch {"),
                          ("class Census {", "inline std::string StatsText("), ("struct Stats {", "inline std::string StatsText(")):
        if hg.index(first) > hg.index(second):
            raise SystemExit("text check: %s must precede %s in the new header" % (first, second))
    # every switch over an enum names all its values (no -Wswitch under -Werror)
    for enum_name, values, anchor in (("Kind", ["Same", "Moved", "Gpu", "Unmapped", "Short", "Pivot", "NoPal", "Character", "Other"],
                                       "inline const char* KindName("),):
        seg = hg[hg.index(anchor):hg.index(anchor) + 900]
        for v in values:
            if "case Kind::%s:" % v not in seg:
                raise SystemExit("text check: KindName misses %s" % v)
    why_values = ["GpuWritten", "NotMapped", "Short", "NoPivot", "NoPalette", "Character", "None"]
    seg = hg[hg.index("inline Kind KindOf("):hg.index("inline bool BoxJudgeable(")]
    for v in why_values:
        if "case S::Why::%s:" % v not in seg:
            raise SystemExit("text check: KindOf misses S::Why::%s" % v)
    # the real enum is what the header assumes
    still_src = open(os.path.join(ROOT, SH + "bbport_wind_hang_still.h"), "rb").read().decode("utf-8")
    m = re.search(r"enum class Why : std::uint8_t \{(.*?)\};", still_src, re.S)
    names = [x.strip() for x in re.sub(r"///[^\n]*", "", m.group(1)).replace("\n", " ").split(",") if x.strip()]
    if sorted(names) != sorted(why_values):
        raise SystemExit("text check: BbWindHangStill::Why has %r, the header assumes %r" % (names, why_values))
    m = re.search(r"enum class Result : std::uint8_t \{(.*?)\};", still_src, re.S)
    names = [x.strip() for x in re.sub(r"///[^\n]*", "", m.group(1)).replace("\n", " ").split(",") if x.strip()]
    if names != ["Same", "Moved", "Never"]:
        raise SystemExit("text check: BbWindHangStill::Result has %r" % names)
    if "std::uint8_t unread_why = 1," not in hh:
        raise SystemExit("text check: Note's new parameters")
    if hh.count("e.box_only = box_only;") != 1 or hh.count("e.why_moving = unread_why;") != 1 or hh.count("e.why_moving = 1;") != 0 \
            or hh.count("e.why_moving = 2;") != 1:
        raise SystemExit("text check: the book's reasons")
    if hf.count("case 5:") != 1 or hf.count("c.box_only = h->box_only;") != 1 or hf.count("std::uint8_t box_only = 0;") != 1:
        raise SystemExit("text check: the find header's new lines")
    if rh.index('#include "bbport_wind_hang_gpu.h"') > rh.index("BbWindHangGpu::Census hang_gpu_census;") or \
            rh.index('#include "bbport_wind_hang_still.h"') > rh.index('#include "bbport_wind_hang_gpu.h"') or \
            rh.index('#include "bbport_wind_hang_find.h"') < rh.index('#include "bbport_wind_hang_gpu.h"'):
        raise SystemExit("text check: the include of the new header comes after its dependencies and before the members")
    if rc.count("hang_gpu_watch.Written(") != 1 or rc.index("hang_gpu_watch.Written(") > rc.index('const VideoCore::InvalidateReason reason{"storage buffer"};'):
        raise SystemExit("text check: the one hook line in the binding loop")
    # the hook sits inside BindBuffers (stage and vsharp are in scope) and inside the written branch
    at = rc.index("hang_gpu_watch.Written(")
    body_start = rc.rindex("void Rasterizer::BindBuffers(", 0, at)
    if rc.count("\nvoid Rasterizer::", body_start, at) != 0 or "if (desc.is_written) {" not in rc[at - 220:at]:
        raise SystemExit("text check: the hook is not inside BindBuffers' written branch")
    if "const auto vsharp" not in rc[body_start:at] and "vsharp" not in rc[body_start:at]:
        raise SystemExit("text check: vsharp is not in scope at the hook")
    # the effects file: the new pieces and their order in WindHangVerdict
    v0 = ef.index("bool Rasterizer::WindHangVerdict(")
    v1 = ef.index("bool Rasterizer::WindHangActorsClear(")
    verdict = ef[v0:v1]
    order = ["u64 palette_address = 0;", "palette_modified = gpu;", "const BbWindHangStill::Result content =",
             "const BbWindHangStill::Entry* const palette_entry", "bool gpu = box_keys &&", "std::uint8_t box_only = 0;",
             "BbWindHangGpu::BoxJudgeable(", "hang_gpu_census.Note(refused)", "hang_gpu_watch.Add(", "const bool still = content ==",
             "hang_book.Note(positions, positions_size, 0, still, frame, vs.pgm_hash,", "switch (verdict) {"]
    last = -1
    for needle in order:
        k = verdict.find(needle)
        if k < 0 or k < last:
            raise SystemExit("text check: WindHangVerdict: %r missing or out of order" % needle)
        last = k
    actors = ef[v1:ef.index("// bbport (r112i_hang-find-lanterns): the ray traced scene's world boxes")]
    if actors.index("BbWindHang::Entry* const entry = hang_book.Find(positions);") > actors.index("const bool box_only = entry != nullptr"):
        raise SystemExit("text check: entry is used before it is declared in WindHangActorsClear")
    if actors.count("BbWindHang::Entry* const entry = hang_book.Find(positions);") != 1:
        raise SystemExit("text check: entry declared twice in WindHangActorsClear")
    word = ef[ef.index("u32 Rasterizer::WindHangWord("):ef.index("// bbport (r89d_tree-twigs): whether a skinned sway draw that is no plant may be a tree")]
    if "const float hang_scale" not in word or word.index("const float hang_scale") > word.index("const u32 pushed_ramp"):
        raise SystemExit("text check: hang_scale is declared before the ramp that uses it")
    if "hang_gpu_stats.ramping += m.ramp < 255" not in word or word.count("const bool box_only") != 1:
        raise SystemExit("text check: WindHangWord's counters")
    # the report block sits inside r112's if (BbWindHang::KnobOnce().on) block, before hang_stats is cleared
    r0 = ef.index("std::string gpu_census_line;")
    if ef.index("hang_box.ClearNotes();") < r0 or ef.index("hang_stats = {};", r0) < ef.index("hang_gpu_stats = {};", r0):
        raise SystemExit("text check: the report block comes before r112's ClearNotes and the counter reset")
    if ef.count("hang_boxj_said") != 3:
        raise SystemExit("text check: the once-line's flag")
    # the knob names and the log prefixes the lead greps for
    for needle in ("BB_WIND_HANG_BOXJUDGE", "BB_WIND_HANG_BOX_BONES", "GLINT-PROOF hang box (r112p)", "Wind sway hang (r112p)"):
        if needle not in hg:
            raise SystemExit("text check: %s missing in the header" % needle)
    rm = texts[RM]
    if rm.count("| `BB_WIND_HANG_BOXJUDGE` |") != 1 or rm.count("| `BB_WIND_HANG_BOX_BONES` |") != 1 or \
            rm.index("| `BB_WIND_HANG_BOXJUDGE` |") > rm.index("| `BB_WIND_HANG_PROOF` |"):
        raise SystemExit("text check: the README rows")
    if texts[CM].count("wind-hang-gpu-test") != 3 or texts[BS].count("wind-hang-gpu-test") != 2:
        raise SystemExit("text check: the test registrations")
    if "int main()" not in tg or "wind-hang-gpu-test: all passed" not in tg:
        raise SystemExit("text check: the test's main")
    # the test's strings are what the header prints
    for needle in ("GLINT-PROOF hang box (r112p): 4 refused streams", "gpu 1+1", "content moved 1+1", "box judge all up to 96 bones",
                   "2 judged, 2 turned away", "palette writer 1: a compute shader 0000000000001111", "lies INSIDE that binding",
                   "only SHARES a page"):
        if needle not in tg:
            raise SystemExit("text check: the test lacks %r" % needle)
    for needle in ("gpu %zu+%zu", "content moved %zu+%zu", "box judge %s up to %u bones", "%zu judged, %zu turned away",
                   "palette writer %zu: a %s shader %016llx", "lies INSIDE", "only SHARES a page with", "OFF (BB_WIND_HANG_BOXJUDGE=0: as r112o)",
                   "refused streams %zu, %zu judged by the GPU box", "palette pages watched %zu, writers found %zu"):
        if needle not in hg:
            raise SystemExit("text check: the header lacks %r" % needle)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112P_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == EF and "hang_gpu_census" not in cur and "BbWindHangFind::OnceTextM(" not in cur:
            raise SystemExit("REFUSED: r112m (and r112o) must be applied")
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    news = [(path, new_state(path)) for path in NEW_ORDER]
    states = {p[5] for p in plan} | {n[1] for n in news}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) + ", " +
                         ", ".join("%s %s" % n for n in news))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_edits(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    olds = {p[0]: p[4] for p in plan}
    if cmd == "check":
        if state == "applied":
            text_checks(olds, {p[0]: revert_edits(p[4], p[1]) for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts(), olds)
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW_ORDER)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts, olds)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r112ptmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path in NEW_ORDER:
            open(os.path.join(ROOT, path), "wb").write(NEW_FILES[path].replace("\n", "\r\n").encode("utf-8"))
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
        tmp = full + ".r112ptmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_ORDER:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


if __name__ == "__main__":
    main()
