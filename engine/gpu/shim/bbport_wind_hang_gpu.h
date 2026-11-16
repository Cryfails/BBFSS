// SPDX-License-Identifier: GPL-3.0-or-later
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

/// bbport (r112q_hang-bracket-route): BB_WIND_HANG_BOX_RETRY: the frames after which a box-judged stream (Entry::box_only) that the GPU box
/// found moving, even by 0.25 m or more (BoxFinal: 'a character for good'), is judged again with a new window (BoxBook::DueSoft). A camera turn
/// brings places of a mesh into view (or takes them out) and the union box its keys span grows with them; 0.25 m of that was final in r112p: a
/// lantern pushed while the camera stood still lost its push for good at the first turn (b64: pushes counted before the look-up, none after it,
/// 13 of 15 judged streams moved). 0: r112p's rule. 30 to 3600, default 120; text that is no number gives the default.
inline constexpr std::uint64_t BoxRetryDefault = 120, BoxRetryMin = 30, BoxRetryMax = 3600;

[[nodiscard]] inline std::uint64_t ParseRetry(const char* text) {
    const float v = BbWindSway::ParseNumber(text, static_cast<float>(BoxRetryDefault));
    if (v < 0.5f) {
        return 0;
    }
    return static_cast<std::uint64_t>(std::clamp(v, static_cast<float>(BoxRetryMin), static_cast<float>(BoxRetryMax)));
}

[[nodiscard]] inline std::uint64_t BoxRetry() {
    static const std::uint64_t frames = ParseRetry(std::getenv("BB_WIND_HANG_BOX_RETRY"));
    return frames;
}

/// bbport (r112r_hang-bracket-judge): BB_WIND_HANG_BOX_NOPAL: a skinned stream with no skeleton-size palette at all (the bracket lanterns: their
/// small bone palettes are no Skeleton role) goes to the GPU box judge like the unread palettes; `0` gives r112q's rule (turned away). At most
/// NopalMost such streams are judged (Census::NopalRoom): the judge's table and the sway slots stay free for the rest of the scene.
inline constexpr std::size_t NopalMost = 48;

[[nodiscard]] inline bool ParseNopal(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == 0);
}

[[nodiscard]] inline bool NopalOn() {
    static const bool on = ParseNopal(std::getenv("BB_WIND_HANG_BOX_NOPAL"));
    return on;
}

/// bbport (r112q_hang-bracket-route): the writer watch hears more than the written storage bindings of BindBuffers: the other paths that mark
/// pages GPU-modified (ObtainBuffer with is_written: a DMA copy or fill destination, a guest-memory write, a command write) pass one of these
/// codes in place of a shader stage (a stage is 0 to 5).
inline constexpr std::uint32_t WriterCopy = 100, WriterFill = 101, WriterGuest = 102, WriterCommand = 103;

[[nodiscard]] inline const char* WriterName(std::uint32_t code) {
    switch (code) {
    case WriterCopy:
        return "DMA copy destination";
    case WriterFill:
        return "DMA fill destination";
    case WriterGuest:
        return "guest-memory write";
    case WriterCommand:
        return "command write";
    default:
        break;
    }
    return "writer ?";
}

/// The line that says what 'writers found 0' means (printed with the periodic line while pages are watched and no writer is found).
[[nodiscard]] inline std::string NoWriterText(std::size_t watched) {
    char buf[900];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112q): no writer found for %zu watched palette pages although the buffer cache calls them GPU-modified: its flag is "
                  "set by every ObtainBuffer(.., is_written): a shader's written storage binding (BindBuffers: the only path r112p watched, so 'writers "
                  "found 0' said that no such binding ever touched those pages) and, heard since r112q, a DMA copy or fill destination, a guest-memory "
                  "write and a command write; none of the four here either: the flag comes from a neighbour in the same page or from the in-place write "
                  "tick (a GPU write not yet finished counts as modified)",
                  watched);
    return std::string(buf);
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
[[nodiscard]] inline bool BoxJudgeable(const S::Entry* e, S::Result cpu, unsigned cap, bool moved_ok = true, bool nopal_ok = false) {
    // bbport (r112r_hang-bracket-judge): a stream with NO skeleton-size palette (Kind::NoPal: bones 0, the bracket lanterns' small bone
    // palettes are none Motion::ClassifyBuffer takes for a skeleton) is box-judged when `nopal_ok`; r112p's "never a palette with no bones"
    // kept the lanterns away from the judge (b65: 'book moving (why 1, box 0)', 'judge none')
    if (nopal_ok && e != nullptr && cpu == S::Result::Never && KindOf(e, cpu) == Kind::NoPal && e->bones <= cap) {
        return true;
    }
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
    if (stage >= WriterCopy) { // bbport (r112q_hang-bracket-route): not a shader stage: a copy, fill or write path
        return WriterName(stage);
    }
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
            nopal_boxed -= old.kind == Kind::NoPal && old.box ? 1u : 0u; // bbport (r112r_hang-bracket-judge)
            nopal_boxed += item.kind == Kind::NoPal && item.box ? 1u : 0u;
            old = item;
            dirty = true;
            return true;
        }
        if (items.size() >= CensusMost) {
            ++overflow;
            return false;
        }
        nopal_boxed += item.kind == Kind::NoPal && item.box ? 1u : 0u; // bbport (r112r_hang-bracket-judge)
        items.emplace(item.stream, item);
        dirty = true;
        return true;
    }

    [[nodiscard]] std::size_t Size() const {
        return items.size();
    }

    /// bbport (r112r_hang-bracket-judge): may this stream be box-judged although it has no skeleton-size palette? Yes when the census holds it
    /// as box-judged already, or fewer than NopalMost such streams are and the census can hold this one (a stream the full census
    /// cannot note would not be counted, so the cap would not hold).
    [[nodiscard]] bool NopalRoom(std::uint64_t stream) const {
        const auto found = items.find(stream);
        if (found != items.end() && found->second.kind == Kind::NoPal && found->second.box) {
            return true;
        }
        return nopal_boxed < NopalMost && (found != items.end() || items.size() < CensusMost);
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
        char head[768];
        std::snprintf(head, sizeof(head),
                      "GLINT-PROOF hang box (r112p): %zu refused streams (a+b: to the GPU box + turned away): gpu %zu+%zu, "
                      "unmapped %zu+%zu, short %zu+%zu, pivot %zu+%zu, content moved %zu+%zu, no palette %zu+%zu, character %zu+%zu, other %zu+%zu; box judge %s up to %u bones (V# "
                      "bytes / 48); %zu judged, %zu turned away%s; V# bones, bytes, palette address, GPU pages, route:",
                      items.size(), Count(Kind::Gpu, true), Count(Kind::Gpu, false), Count(Kind::Unmapped, true),
                      Count(Kind::Unmapped, false), Count(Kind::Short, true), Count(Kind::Short, false),
                      Count(Kind::Pivot, true), Count(Kind::Pivot, false), Count(Kind::Moved, true), Count(Kind::Moved, false),
                      Count(Kind::NoPal, true), Count(Kind::NoPal, false), Count(Kind::Character, true), Count(Kind::Character, false),
                      Count(Kind::Other, true), Count(Kind::Other, false), ModeName(mode), cap, Boxed(), items.size() - Boxed(), overflow != 0 ? " (census full)" : "");
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
    std::size_t nopal_boxed = 0; // bbport (r112r_hang-bracket-judge): streams of Kind::NoPal sent to the box judge
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
            if (h.stage >= WriterCopy) { // bbport (r112q_hang-bracket-route): a copy, fill or write path, no shader
                std::snprintf(buf, sizeof(buf),
                              "GLINT-PROOF hang box (r112p): palette writer %zu: a %s (no shader) writes %#llx+%llu; the palette %#llx+%u (%u bones, "
                              "stream %#llx) %s that range (4 KiB pages assumed)",
                              printed + 1, StageName(h.stage), static_cast<unsigned long long>(h.at),
                              static_cast<unsigned long long>(h.size), static_cast<unsigned long long>(h.palette), h.bytes, h.bones,
                              static_cast<unsigned long long>(h.stream), h.inside ? "lies INSIDE" : "only SHARES a page with");
            }
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
