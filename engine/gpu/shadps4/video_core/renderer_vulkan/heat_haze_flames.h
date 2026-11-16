// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97f_haze-per-flame): the pure parts of the haze's flame anchoring (vk_heat_haze.cpp,
// host_shaders/heat_haze_find.comp): the knobs, the scan of a lamp's surroundings and its answer, a
// table that remembers where each lamp's flames are, and the sources (the places the columns stand
// on) the table gives. No Vulkan, no settings; tested by tests/test_heat_haze.cpp.
//
// Why: the game's lamp lights (the records heat_haze.h reads) sit where its artists put them, not
// on the flames: one light for the two lanterns of a post stands between them (the haze came out
// in the middle of the post), and the lantern that has none got no haze. So each lamp's
// surroundings are scanned in the scene colour for small bright warm sources (the flames and the
// lit glass), and the columns stand on those; a lamp stays where it is for the table's sake (its
// place in the WORLD: the records are in view space, which moves with the camera).
#pragma once

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <optional>
#include <span>
#include <vector>

#include "heat_haze.h"
#include "../host_shaders/heat_haze_find_layout.h"

namespace BbHeatHaze {

/// BB_HEAT_HAZE_FLAMES: 0 the haze stands on the lamps' lights (r97e), 1 on the flames found around
/// a lamp (none found, no column), 2 the same and a lamp with no answer, or none found, keeps its own.
enum class FlameMode : int { Off = 0, Anchors = 1, AnchorsOrLight = 2 };
inline constexpr FlameMode FlamesDefault = FlameMode::AnchorsOrLight;

/// Unset or empty: FlamesDefault; exactly "0", "1" or "2": that; any other text: off.
inline FlameMode ParseFlames(const char* text) {
    if (text == nullptr || text[0] == 0) {
        return FlamesDefault;
    }
    if (text[1] == 0 && text[0] >= '0' && text[0] <= '2') {
        return static_cast<FlameMode>(text[0] - '0');
    }
    return FlameMode::Off;
}

/// BB_HEAT_HAZE_FLAME_MIN: how far above its surround (HDR luma) a cell must stand to be a flame.
inline constexpr float BlobMinDefault = 0.5f, BlobMinLowest = 0.05f, BlobMinHighest = 100.0f;
inline float ParseBlobMin(const char* text) {
    if (text == nullptr || text[0] == 0) {
        return BlobMinDefault;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || *end != 0 || !std::isfinite(value)) {
        return BlobMinDefault;
    }
    return std::clamp(value, BlobMinLowest, BlobMinHighest);
}

inline constexpr std::uint32_t MaxScans = HF_SLOTS;     ///< lamps scanned a frame
inline constexpr std::uint32_t MaxAnchors = HF_PEAKS;   ///< flames kept for one lamp
inline constexpr std::uint32_t FindWords = HF_WORDS_TOTAL;
inline constexpr std::uint32_t FindBytes = HF_WORDS_TOTAL * 4u;
static_assert(HF_SLOTS * HF_BLOCK_WORDS == HF_WORDS_TOTAL && HF_WORD_CHECK + 1u == HF_BLOCK_WORDS &&
                  HF_WORD_PEAK0 + HF_PEAKS * HF_PEAK_WORDS <= HF_WORD_BRIGHT,
              "the block's words");
static_assert(HF_SLOTS == MaxColumns && MaxLamps <= 255u, "a table id keeps the index in 8 bits");
/// m: half the side of the square around a lamp that is scanned (a post's two lanterns are about
/// 2.5 m apart, a candle holder's candles a few decimetres).
inline constexpr float ScanHalfM = 3.0f;
inline constexpr float LampMatchM = 0.4f;   ///< m: a lamp seen again within this of where it was is the same
inline constexpr float AnchorMatchM = 0.3f; ///< m: a flame found again within this is the same
inline constexpr float AnchorBlend = 0.4f;  ///< the share a new answer moves a kept flame's place
inline constexpr std::uint32_t EmptyReadsToClear = 8; ///< answers with no flame before a lamp's are dropped

/// One scan's push constants (48 bytes; heat_haze_find.comp lists the same fields in the same order).
struct FindPush {
    std::array<std::int32_t, 4> info{};  ///< slot, id, tag, 0
    std::array<float, 4> centre{};       ///< the light's pixel x, y; pixels a metre at its depth, x, y (signed)
    std::array<float, 4> window{};       ///< half side (m), blob minimum, the scene's width, height
};
static_assert(sizeof(FindPush) == 48);

/// A block of the finder's buffer (one lamp, one frame).
struct Block {
    std::uint32_t id = 0, tag = 0, count = 0, cells = 0;
    std::array<float, HF_PEAKS> x{}, y{}, blob{};
    float best = 0.0f, bright = 0.0f;
};

/// The fold the shader puts in a block's last word (words 0 to 14).
inline std::uint32_t BlockCheck(const std::uint32_t* w) {
    std::uint32_t c = 2166136261u;
    for (std::uint32_t k = 0; k < HF_WORD_CHECK; ++k) {
        c = (c ^ w[k]) * 16777619u;
    }
    return c;
}

enum class ReadKind { Blank, Torn, Bad, Ok };
/// A block as the host copy holds it: Blank (never written), Torn (the copy was in flight: the check
/// fails), Bad (a number out of range) or Ok.
inline ReadKind ReadBlock(const std::uint32_t* w, Block& out) {
    if (w[HF_WORD_TAG] == 0 && w[HF_WORD_CHECK] == 0) {
        return ReadKind::Blank;
    }
    if (BlockCheck(w) != w[HF_WORD_CHECK]) {
        return ReadKind::Torn;
    }
    Block b;
    b.id = w[HF_WORD_ID];
    b.tag = w[HF_WORD_TAG];
    b.count = w[HF_WORD_COUNT];
    b.cells = w[HF_WORD_CELLS];
    b.best = Word(w, HF_WORD_BEST);
    b.bright = Word(w, HF_WORD_BRIGHT);
    if (b.count > HF_PEAKS || !std::isfinite(b.best) || !std::isfinite(b.bright)) {
        return ReadKind::Bad;
    }
    for (std::uint32_t k = 0; k < b.count; ++k) {
        b.x[k] = Word(w, HF_WORD_PEAK0 + k * HF_PEAK_WORDS);
        b.y[k] = Word(w, HF_WORD_PEAK0 + k * HF_PEAK_WORDS + 1);
        b.blob[k] = Word(w, HF_WORD_PEAK0 + k * HF_PEAK_WORDS + 2);
        const float limit = ScanHalfM * 1.01f;
        if (!(std::abs(b.x[k]) <= limit) || !(std::abs(b.y[k]) <= limit) || !(b.blob[k] > 0.0f) ||
            !std::isfinite(b.blob[k])) {
            return ReadKind::Bad;
        }
    }
    out = b;
    return ReadKind::Ok;
}

/// A direction through a 3x4 row matrix (the rotation part: no translation).
inline std::array<float, 3> Rotate(const std::array<float, 12>& m, const std::array<float, 3>& v) {
    return {m[0] * v[0] + m[1] * v[1] + m[2] * v[2], m[4] * v[0] + m[5] * v[1] + m[6] * v[2],
            m[8] * v[0] + m[9] * v[1] + m[10] * v[2]};
}

/// A point through a 3x4 row matrix.
inline std::array<float, 3> Transform(const std::array<float, 12>& m, const std::array<float, 3>& v) {
    const auto r = Rotate(m, v);
    return {r[0] + m[3], r[1] + m[7], r[2] + m[11]};
}

inline float DistanceSquared(const std::array<float, 3>& a, const std::array<float, 3>& b) {
    const float x = a[0] - b[0], y = a[1] - b[1], z = a[2] - b[2];
    return x * x + y * y + z * z;
}

/// A flame found near a lamp: where it stands, as a world offset from the lamp, and its blob.
struct Anchor {
    std::array<float, 3> offset{};
    float blob = 0.0f;
};

/// What the table keeps of one lamp.
struct Entry {
    bool used = false;
    bool answered = false;          ///< a scan of this lamp has been read
    std::uint32_t generation = 0;   ///< counts the entry's lives (an old answer for a dead life is dropped)
    std::uint32_t count = 0;        ///< flames kept (anchors[0..count))
    std::uint32_t empty_reads = 0;  ///< answers in a row that found none
    std::uint32_t last_tag = 0;     ///< the newest answer taken
    std::array<float, 3> world{};   ///< where the lamp was last seen, in the world
    std::uint64_t last_seen = 0;    ///< the frame it was last scanned or asked for
    std::array<Anchor, MaxAnchors> anchors{};
};

enum class ApplyResult { Unknown, Same, Empty, Anchors };

/// The lamps the haze has seen, by their place in the world (a lamp record's view space place moves
/// with the camera; a lamp is the same one when it is within LampMatchM of where it was).
class FlameTable {
public:
    static constexpr std::uint32_t Size = MaxLamps;

    /// The id of the lamp at `world` (index in the low 8 bits, the entry's life above): the entry
    /// within LampMatchM when there is one, else a new one (a free entry, or the one seen longest ago).
    std::uint32_t Touch(const std::array<float, 3>& world, std::uint64_t frame) {
        std::size_t found = Size;
        float best = LampMatchM * LampMatchM;
        for (std::size_t i = 0; i < Size; ++i) {
            if (entries[i].used) {
                const float d = DistanceSquared(entries[i].world, world);
                if (d <= best) {
                    best = d;
                    found = i;
                }
            }
        }
        if (found == Size) {
            std::size_t pick = 0;
            for (std::size_t i = 0; i < Size; ++i) {
                if (!entries[i].used) {
                    pick = i;
                    break;
                }
                if (entries[i].last_seen < entries[pick].last_seen) {
                    pick = i;
                }
            }
            const std::uint32_t life = entries[pick].generation + 1u;
            entries[pick] = Entry{};
            entries[pick].generation = life;
            entries[pick].used = true;
            found = pick;
        }
        entries[found].world = world;
        entries[found].last_seen = frame;
        return (entries[found].generation << 8) | std::uint32_t(found);
    }

    /// The entry of the lamp at `world` (the nearest within LampMatchM), or null.
    [[nodiscard]] const Entry* Match(const std::array<float, 3>& world) const {
        const Entry* found = nullptr;
        float best = LampMatchM * LampMatchM;
        for (const Entry& e : entries) {
            if (e.used) {
                const float d = DistanceSquared(e.world, world);
                if (d <= best) {
                    best = d;
                    found = &e;
                }
            }
        }
        return found;
    }

    [[nodiscard]] const Entry& At(std::size_t i) const { return entries[i]; }

    /// A block the finder wrote: Unknown when its id is of no live entry, Same when its tag was
    /// taken already, Empty when it found no flame, else Anchors (the flames' offsets, from the view
    /// plane to the world by `inv_view`, blended with the ones kept where they match).
    ApplyResult Apply(const Block& block, const std::array<float, 12>& inv_view) {
        const std::uint32_t index = block.id & 255u, life = block.id >> 8;
        if (index >= Size || !entries[index].used || entries[index].generation != life) {
            return ApplyResult::Unknown;
        }
        Entry& e = entries[index];
        // (review) A slot not rescanned this frame keeps an older block of this lamp in the host copy:
        // only a NEWER tag is taken (tags rise by one a frame), or old answers would be re-applied
        // every frame, alternating with the new ones.
        if (static_cast<std::int32_t>(block.tag - e.last_tag) <= 0) {
            return ApplyResult::Same;
        }
        e.last_tag = block.tag;
        e.answered = true;
        if (block.count == 0) {
            if (++e.empty_reads >= EmptyReadsToClear) {
                e.count = 0;
            }
            return ApplyResult::Empty;
        }
        e.empty_reads = 0;
        std::array<Anchor, MaxAnchors> next{};
        std::uint32_t n = 0;
        for (std::uint32_t k = 0; k < block.count && n < MaxAnchors; ++k) {
            Anchor a;
            a.offset = Rotate(inv_view, {block.x[k], block.y[k], 0.0f});
            a.blob = block.blob[k];
            std::size_t same = MaxAnchors;
            float best = AnchorMatchM * AnchorMatchM;
            for (std::uint32_t j = 0; j < e.count; ++j) {
                const float d = DistanceSquared(e.anchors[j].offset, a.offset);
                if (d <= best) {
                    best = d;
                    same = j;
                }
            }
            if (same != MaxAnchors) {
                for (std::size_t c = 0; c < 3; ++c) {
                    a.offset[c] = e.anchors[same].offset[c] + AnchorBlend * (a.offset[c] - e.anchors[same].offset[c]);
                }
            }
            next[n++] = a;
        }
        e.anchors = next;
        e.count = n;
        return ApplyResult::Anchors;
    }

private:
    std::array<Entry, Size> entries{};
};

/// One lamp's scan of a frame.
struct ScanJob {
    FindPush push;
    std::uint32_t id = 0;
    float distance = 0.0f; ///< m from the camera
};

/// The lamps to scan this frame: the MaxScans nearest whose light is within half a screen of the
/// screen's edge, each touched in the table (made when new), nearest first (slot 0).
inline std::vector<ScanJob> PlanScans(std::span<const Lamp> lamps, FlameTable& table,
                                      const Camera& camera, std::uint32_t tag, std::uint64_t frame,
                                      float blob_min) {
    struct Candidate {
        std::size_t index;
        float distance_squared;
    };
    std::vector<Candidate> candidates;
    const float w = float(camera.width), h = float(camera.height);
    for (std::size_t i = 0; i < lamps.size(); ++i) {
        const auto& v = lamps[i].view;
        if (!(v[2] >= NearZ) || camera.width == 0 || camera.height == 0) {
            continue;
        }
        const auto px = ToPixel(camera, v);
        if (!(px[0] > -0.5f * w && px[0] < 1.5f * w && px[1] > -0.5f * h && px[1] < 1.5f * h)) {
            continue;
        }
        candidates.push_back({i, v[0] * v[0] + v[1] * v[1] + v[2] * v[2]});
    }
    std::stable_sort(candidates.begin(), candidates.end(), [](const Candidate& a, const Candidate& b) {
        return a.distance_squared < b.distance_squared;
    });
    if (candidates.size() > MaxScans) {
        candidates.resize(MaxScans);
    }
    std::vector<ScanJob> jobs;
    jobs.reserve(candidates.size());
    for (std::size_t slot = 0; slot < candidates.size(); ++slot) {
        const Lamp& lamp = lamps[candidates[slot].index];
        const auto& v = lamp.view;
        ScanJob job;
        job.id = table.Touch(Transform(camera.inv_view, v), frame);
        const auto px = ToPixel(camera, v);
        job.push.info = {std::int32_t(slot), std::int32_t(job.id), std::int32_t(tag), 0};
        job.push.centre = {px[0], px[1], 0.5f * w * camera.proj[0] / v[2], 0.5f * h * camera.proj[1] / v[2]};
        job.push.window = {ScanHalfM, blob_min, w, h};
        job.distance = std::sqrt(candidates[slot].distance_squared);
        jobs.push_back(job);
    }
    return jobs;
}

/// What the sources of a frame were made of, per lamp.
struct FlameCounts {
    std::uint32_t anchored = 0;  ///< lamps whose flames were found (a source each)
    std::uint32_t empty = 0;     ///< lamps scanned, no flame found
    std::uint32_t unscanned = 0; ///< lamps with no answer yet
    std::uint32_t flames = 0;    ///< sources made of found flames
};

/// The places the columns stand on, one a source: each found flame of a lamp, at the lamp's place
/// plus the flame's offset (the view's rotation of the world offset); a lamp that has no answer or
/// none found keeps its own light with AnchorsOrLight, none with Anchors.
inline std::vector<Lamp> FlameSources(std::span<const Lamp> lamps, const FlameTable& table,
                                      const Camera& camera, FlameMode mode, FlameCounts& counts) {
    counts = {};
    std::vector<Lamp> out;
    out.reserve(lamps.size() * 2);
    std::vector<const Entry*> emitted; // (review) two lights within LampMatchM share an entry: its flames once
    for (const Lamp& lamp : lamps) {
        const Entry* entry = table.Match(Transform(camera.inv_view, lamp.view));
        if (entry != nullptr && entry->answered && entry->count > 0) {
            if (std::find(emitted.begin(), emitted.end(), entry) != emitted.end()) {
                continue;
            }
            emitted.push_back(entry);
            ++counts.anchored;
            for (std::uint32_t k = 0; k < entry->count; ++k) {
                Lamp source = lamp;
                const auto d = Rotate(camera.view, entry->anchors[k].offset);
                source.view = {lamp.view[0] + d[0], lamp.view[1] + d[1], lamp.view[2] + d[2]};
                out.push_back(source);
                ++counts.flames;
            }
            continue;
        }
        if (entry != nullptr && entry->answered) {
            ++counts.empty;
        } else {
            ++counts.unscanned;
        }
        if (mode == FlameMode::AnchorsOrLight) {
            out.push_back(lamp);
        }
    }
    return out;
}

} // namespace BbHeatHaze
