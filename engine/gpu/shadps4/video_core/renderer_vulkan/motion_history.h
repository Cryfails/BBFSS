// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <span>
#include <unordered_map>
#include <utility>
#include <vector>

namespace Vulkan::Motion {

struct VertexRange {
    uint32_t first{}, count{};
    bool operator==(const VertexRange&) const = default;
};

// Reserve only the vertices referenced by this draw, not the whole shared vertex buffer.
// Primitive restart markers are not vertex shader invocations. Reject signed overflow.
template <class Index, size_t Extent>
VertexRange IndexedRange(std::span<const Index, Extent> indices, int32_t base_vertex, bool restart) {
    uint32_t lo = UINT32_MAX, hi = 0;
    for (const auto index : indices) {
        if (restart && index == std::numeric_limits<Index>::max()) {
            continue;
        }
        lo = std::min(lo, uint32_t(index));
        hi = std::max(hi, uint32_t(index));
    }
    if (lo > hi || int64_t(lo) + base_vertex < 0 ||
        int64_t(hi) + base_vertex > INT32_MAX) {
        return {};
    }
    return {uint32_t(int64_t(lo) + base_vertex), hi - lo + 1};
}

// bbport (r34_motion-store): the distinct vertices `indices` reference, for `range` from
// IndexedRange of the same indices. Room is given for the whole range (the shader stores a vertex
// at its index less the range's first), so a level-of-detail list over a shared vertex buffer can
// take room for many vertices it never uses. 0 = not counted: an empty range, or one of more
// than `limit` vertices. `bits` is scratch kept by the caller.
template <class Index, size_t Extent>
uint32_t UsedVertices(std::span<const Index, Extent> indices, int32_t base_vertex, bool restart,
                      VertexRange range, uint32_t limit, std::vector<uint64_t>& bits) {
    if (!range.count || range.count > limit) {
        return 0;
    }
    bits.assign((size_t(range.count) + 63) / 64, 0);
    uint32_t used = 0;
    for (const auto index : indices) {
        if (restart && index == std::numeric_limits<Index>::max()) {
            continue;
        }
        const uint32_t at = uint32_t(int64_t(index) + base_vertex - int64_t(range.first));
        if (at >= range.count) {
            continue; // not in the range (the indices changed while they were read)
        }
        uint64_t& word = bits[at >> 6];
        const uint64_t bit = uint64_t(1) << (at & 63);
        used += (word & bit) ? 0 : 1;
        word |= bit;
    }
    return used;
}

// bbport (r34_motion-store): what a draw given to History::Prepare is. Skinned: a character-size
// bone palette (stored every frame); GpuPalette: a small skeleton whose palette the GPU wrote;
// Moved: a small skeleton whose palette changed this frame; Recent / Held: one whose palette did
// not change this frame but changed 1..History::RecentFrames / more frames ago, within
// BB_OBJECT_MOTION_HOLD frames (its store is what the next changed frame loads: a palette the
// game updates every 2nd or 3rd rendered frame, like an attached weapon, is Recent on the frames
// between); Other: anything else (BB_OBJECT_MOTION_ALL, tests).
enum class Kind : uint8_t { Other, Skinned, GpuPalette, Moved, Held, Recent };
inline constexpr size_t KindCount = 6;
/// What History::Prepare is told about a draw (History::Sort).
struct DrawSort {
    Kind kind = Kind::Other;
    uint32_t used{}; ///< distinct vertices of the draw's range (0 = not known)
};

// Vertex shader constant buffers (stride 16) of Bloodborne's G-buffer shaders: the 864-byte
// scene constants (camera), 416-byte model constants and palettes of 3x4 bone matrices
// (48 bytes per bone). Characters have 656+ bytes; weapons and props 2-8 bones (96-384).
enum class BufferRole { Other, Skeleton, SmallSkeleton };
inline BufferRole ClassifyBuffer(uint32_t size) {
    if (size == 864 || size > 16384) {
        return BufferRole::Other;
    }
    if (size >= 640) {
        return BufferRole::Skeleton;
    }
    return size >= 96 && size % 48 == 0 ? BufferRole::SmallSkeleton : BufferRole::Other;
}

// Scanning and hashing the index list of every stored draw each frame took ~10% of the GPU
// thread. Static meshes keep their index buffers, so a result is reused and fully verified
// again every `Revalidate` frames. A stale result only costs camera-quality vectors: the
// shader bounds every history access by the stored range.
class IndexRangeCache {
public:
    static constexpr uint64_t Revalidate = 32, Unused = 600;
    struct Key {
        uint64_t address{};
        uint32_t count{}, index_size{};
        int32_t base_vertex{};
        bool restart{};
        bool operator==(const Key&) const = default;
    };
    struct Result {
        VertexRange range;
        uint64_t topology{};
        uint32_t used{}; ///< bbport (r34_motion-store): UsedVertices of the range, 0 = not counted
    };
    struct Stats {
        uint64_t hits{}, scans{}, stale{};
    } stats;
    // bbport (r28_motion-stagger): true = each entry is verified again at its own frame of
    // every Revalidate-frame window (a phase from its key's hash); false = phase 0: every entry
    // on the frames where frame % Revalidate == 0 (r29_bursts: not the rule before r28, which
    // counted from each entry's own scan, but the same burst on one frame; set at run time it
    // puts the entries an ON phase spread back on one frame). Set by the owner before Get.
    bool stagger{};

    template <class Scan>
    Result Get(const Key& key, uint64_t frame, Scan&& scan) {
        auto& entry = entries[key];
        entry.last_use = frame;
        // bbport (r28_motion-stagger): valid until the frame count crosses the entry's next
        // window boundary (at most Revalidate frames after its last scan, as before).
        const uint64_t phase = stagger ? (KeyHash{}(key) >> 20) % Revalidate : 0;
        if (entry.valid && frame >= entry.verified &&
            (frame + phase) / Revalidate == (entry.verified + phase) / Revalidate) {
            ++stats.hits;
            return entry.result;
        }
        ++stats.scans;
        const Result fresh = scan();
        if (entry.valid && (fresh.topology != entry.result.topology ||
                            !(fresh.range == entry.result.range))) {
            ++stats.stale; // the cached result was wrong for up to Revalidate frames
        }
        entry.result = fresh;
        entry.verified = frame;
        entry.valid = true;
        return entry.result;
    }
    void Trim(uint64_t frame) {
        std::erase_if(entries, [frame](const auto& e) { return frame - e.second.last_use > Unused; });
    }
    size_t Size() const { return entries.size(); }

private:
    struct Entry {
        Result result;
        uint64_t verified{}, last_use{};
        bool valid{};
    };
    struct KeyHash {
        size_t operator()(const Key& k) const {
            uint64_t h = k.address * 0x9e3779b97f4a7c15ULL;
            h ^= (uint64_t(k.count) << 32 | uint32_t(k.base_vertex)) + (h << 6) + (h >> 2);
            h ^= uint64_t(k.index_size << 1 | uint32_t(k.restart)) + (h << 6) + (h >> 2);
            return size_t(h);
        }
    };
    std::unordered_map<Key, Entry, KeyHash> entries;
};

// Open-addressing map for the per-frame tables of History: entries are keyed per draw and
// the tables are cleared every frame. std::unordered_map allocated a node per insert (four
// per draw) and freed them all at the frame end; here clear() only starts a new generation.
template <class Key, class Value, class Hash>
class FlatMap {
public:
    FlatMap() : slots(64) {}

    Value& operator[](const Key& key) {
        return Insert(key).first->value;
    }
    /// Inserts `value` when `key` is absent (like std::unordered_map::emplace).
    void emplace(const Key& key, const Value& value) {
        const auto [slot, inserted] = Insert(key);
        if (inserted) {
            slot->value = value;
        }
    }
    const Value* find(const Key& key) const {
        const size_t mask = slots.size() - 1;
        for (size_t i = Start(key) & mask;; i = (i + 1) & mask) {
            const Slot& slot = slots[i];
            if (slot.generation != generation) {
                return nullptr;
            }
            if (slot.key == key) {
                return &slot.value;
            }
        }
    }
    void clear() {
        size = 0;
        if (++generation == 0) { // wrapped: stale slots could look current
            for (auto& slot : slots) {
                slot.generation = 0;
            }
            generation = 1;
        }
    }
    void swap(FlatMap& other) noexcept {
        slots.swap(other.slots);
        std::swap(size, other.size);
        std::swap(generation, other.generation);
    }

private:
    struct Slot {
        Key key{};
        Value value{};
        uint32_t generation = 0;
    };
    static size_t Start(const Key& key) {
        const uint64_t h = uint64_t(Hash{}(key)) * 0x9e3779b97f4a7c15ULL;
        return size_t(h ^ (h >> 29));
    }
    std::pair<Slot*, bool> Insert(const Key& key) {
        if ((size + 1) * 2 > slots.size()) {
            Grow();
        }
        const size_t mask = slots.size() - 1;
        for (size_t i = Start(key) & mask;; i = (i + 1) & mask) {
            Slot& slot = slots[i];
            if (slot.generation != generation) {
                slot = {key, Value{}, generation};
                ++size;
                return {&slot, true};
            }
            if (slot.key == key) {
                return {&slot, false};
            }
        }
    }
    void Grow() {
        std::vector<Slot> old(slots.size() * 2);
        old.swap(slots);
        const uint32_t live = generation;
        generation = 1;
        size = 0;
        for (const auto& slot : old) {
            if (slot.generation == live) {
                *Insert(slot.key).first = {slot.key, slot.value, generation};
            }
        }
    }

    std::vector<Slot> slots;
    size_t size = 0;
    uint32_t generation = 1;
};

inline uint32_t JitterPhases(uint32_t render_width, uint32_t output_width) {
    if (!render_width || !output_width) {
        return 8;
    }
    const double ratio = double(output_width) / render_width;
    return uint32_t(std::clamp(std::ceil(8.0 * ratio * ratio), 8.0, 256.0));
}

struct Draw {
    uint64_t shader{}, geometry{}, indices{}, topology{};
    uint32_t index_count{}, instances{}, first_instance{};
    VertexRange vertices;
    bool operator==(const Draw& rhs) const = default;
};

// CPU bookkeeping shared with the regression test. Draw identity includes topology and
// offsets: a reused index buffer or another submesh must never read uninitialised history.
class History {
public:
    explicit History(uint32_t capacity) : capacity{capacity} {}

    struct Allocation {
        uint32_t store{}, load{}, vertices{}, instances{}, first_vertex{}, first_instance{};
    };
    struct Stats {
        uint64_t draws{}, stored{}, loaded{}, unmatched{}, exhausted{}, invalid{}, still{},
            held{};
    } stats;

    // bbport (r34_motion-store): room was given first come, first served, so the draws recorded
    // last in a frame got none once the store was full, whatever they were. With `priority`
    // (set by the owner before Prepare) draws come in two classes. The first class (skinned,
    // moved, GPU palette; not sparse) takes room from the bottom as before; the second class
    // takes room from the top and never below the room the first class asked for on the frame
    // before (`reserve`), so a first-class draw recorded late still finds room when the first
    // class asks for no more than it did on the last frame. Without `priority` every draw is
    // first class: the same places as before.
    using Sort = DrawSort;
    /// Under half of the range it is given room for is used (a level-of-detail index list
    /// over a shared vertex buffer, for instance).
    static bool Sparse(Sort sort, uint32_t span) {
        return sort.used && uint64_t(sort.used) * 2 < span;
    }
    static bool FirstKind(Kind kind) {
        // bbport (r36_followups): GPU-written small palettes are second class. Measured at a
        // heavy spot they are 611 of 701 motion draws a frame and, first class, they locked
        // 10 skinned draws out of the store every frame.
        return kind == Kind::Skinned || kind == Kind::Moved || kind == Kind::Recent;
    }
    static bool FirstClass(Sort sort, uint32_t span) {
        return FirstKind(sort.kind) && !Sparse(sort, span);
    }
    /// A held draw whose palette changed at most this many frames ago is Kind::Recent (first
    /// class): its store feeds the next changed frame of a palette updated every few frames.
    static constexpr uint32_t RecentFrames = 4;
    bool priority{};
    /// The "Object motion store (r34):" report: sums since the owner last cleared it.
    struct KindStore {
        uint64_t stored_draws{}, stored{}, skipped_draws{}, skipped{}; ///< vertices x instances
    };
    struct StoreStats {
        std::array<KindStore, KindCount> kinds{};
        uint64_t instanced_stored{}, instanced_skipped{}; ///< draws of more than one instance
        uint64_t repeat_stored{}, repeat_skipped{};       ///< the same Draw again in the frame
        uint64_t known_span{}, known_used{};              ///< draws whose used vertices are known
        uint64_t sparse_draws{}, sparse_vertices{};       ///< of those, using under half the span
        uint64_t sparse_demoted{}; ///< of those, of a first-class kind (put second for it)
        uint64_t second{}, loaded{}; ///< room the second class got; vertices with history loaded
        uint64_t frames{}, prepares{}, skip_frames{}, first_skip{}, reserve{}, used{};
    } store;
    /// Only before the first frame (the store's size, BB_OBJECT_MOTION_VERTICES).
    void SetCapacity(uint32_t vertices) {
        capacity = vertices;
        used = used_back = reserve = 0;
    }
    uint32_t Capacity() const { return capacity; }
    /// The last Moving call kept the draw only for BB_OBJECT_MOTION_HOLD (palette unchanged).
    bool LastHeld() const { return last_held; }
    /// The kind of the draw of the last Moving call that returned true: Moved, Recent or Held.
    Kind LastKind() const {
        return !last_held ? Kind::Moved : last_age <= RecentFrames ? Kind::Recent : Kind::Held;
    }

    // A small skeleton (weapon, prop; most are static world pieces) only needs history
    // while its bone palette changes: with last frame's bones its motion is the camera's.
    // Checked before the index scan of Prepare, with a cheap identity. The first frame
    // of a change stores positions (nothing to load yet), the next one loads them.
    //
    // bbport: a draw whose palette changed keeps its history for `hold` more frames
    // (SetHold, BB_OBJECT_MOTION_HOLD in vk_object_motion.cpp). Without it, bones that move
    // on some frames only never got a vector: a changed frame that follows an unchanged one
    // has nothing to load (that frame stored nothing; it counts as unmatched), and the frame
    // after it is "still" again. The palettes hold world-space bones (the G-buffer vertex
    // shaders multiply by the palette, then by the scene camera; the model constants only
    // give the first bone index), so an attached weapon changes its palette only on the
    // frames the game updates its attachment, which at 120 FPS need not be every rendered
    // frame. Ludwig's Holy Blade on the back showed it: orange (camera motion) in the debug
    // view while the body, a large skeleton stored every frame, was blue, and DLSS dropped
    // the blade's history while the player ran. A held frame stores and loads like a moving
    // one; for an object that did not move its vector equals the camera's, so holding costs
    // only the vertex stores of objects that moved within the last `hold` frames.
    struct GateKey {
        uint64_t shader{}, geometry{}, indices{};
        uint32_t index_count{}, instances{}, first_instance{}, occurrence{};
        bool operator==(const GateKey&) const = default;
    };
    void SetHold(uint32_t frames) { hold = frames; }
    bool Moving(GateKey key, uint64_t palette) {
        key.occurrence = 0;
        key.occurrence = gate_occurrences[key]++;
        const auto* prev = gate_previous.find(key);
        GateState state{palette, 0};
        bool moving = false;
        last_held = false; // bbport (r34_motion-store)
        if (prev && prev->palette != palette) {
            moving = true;
            state.hold = hold;
        } else if (prev && prev->hold) {
            moving = true; // unchanged, but changed within the last `hold` frames
            state.hold = prev->hold - 1;
            ++stats.held;
            last_held = true; // bbport (r34_motion-store)
            last_age = hold > state.hold ? hold - state.hold : 1; // frames since the change
        }
        gate_current.emplace(key, state);
        stats.still += moving ? 0 : 1;
        return moving;
    }

    void NextFrame() {
        previous.swap(current);
        current.clear();
        occurrences.clear();
        gate_previous.swap(gate_current);
        gate_current.clear();
        gate_occurrences.clear();
        // bbport (r34_motion-store): the room the first class would have taken on the frame
        // that ended with the whole store to itself (first come) is kept for it on the next
        // one. A frame without draws (an invalidation calls NextFrame twice) leaves the
        // reserve as it was.
        if (frame_prepares) {
            reserve = uint32_t(std::min<uint64_t>(first_demand, capacity));
            ++store.frames;
            store.prepares += frame_prepares;
            store.used += uint64_t(used) + used_back;
            store.reserve += reserve;
            if (first_skip) {
                ++store.skip_frames;
                store.first_skip += first_skip;
            }
        }
        frame_prepares = 0;
        first_skip = 0;
        first_demand = 0;
        used_back = 0;
        ++frame;
        used = 0;
    }

    Allocation Prepare(const Draw& draw, Sort sort = {}) {
        ++stats.draws;
        ++frame_prepares; // bbport (r34_motion-store)
        Key key{draw, 0};
        key.occurrence = occurrences[key]++;
        const uint64_t count = uint64_t(draw.vertices.count) * draw.instances;
        if (!count || uint64_t(draw.vertices.first) + draw.vertices.count - 1 > INT32_MAX ||
            uint64_t(draw.first_instance) + draw.instances > UINT32_MAX) {
            ++stats.invalid;
            return {};
        }
        const auto* prev = previous.find(key);
        Allocation result{0, 0, draw.vertices.count, draw.instances,
                          draw.vertices.first, draw.first_instance};
        if (prev) {
            result.load = *prev;
            ++stats.loaded;
            store.loaded += count; // bbport (r34_motion-store)
        } else {
            ++stats.unmatched;
        }
        // bbport (r34_motion-store): first class from the bottom, second from the top above
        // the reserve (see Sort). Without `priority`: all from the bottom, as before.
        const bool first = !priority || FirstClass(sort, draw.vertices.count);
        bool fits = false;
        uint64_t offset = 0;
        if (first) {
            if (count <= uint64_t(capacity) - first_demand) {
                first_demand += count; // as if the first class had the whole store
            }
            fits = count <= uint64_t(capacity) - used - used_back;
            offset = used;
        } else {
            const uint64_t low = std::max(used, reserve);
            fits = low + used_back + count <= capacity;
            offset = fits ? uint64_t(capacity) - used_back - count : 0;
        }
        if (fits) {
            result.store = 1 + uint32_t(frame & 1) * capacity + uint32_t(offset);
            (first ? used : used_back) += uint32_t(count);
            current.emplace(key, result.store);
            ++stats.stored;
        } else {
            ++stats.exhausted;
            if (!first_skip) {
                first_skip = frame_prepares;
            }
        }
        Note(sort, draw, count, fits, first, key.occurrence != 0);
        return result;
    }

    /// Vertices given room this frame (both classes).
    uint32_t Used() const { return used + used_back; }

private:
    struct Key {
        Draw draw;
        uint32_t occurrence;
        bool operator==(const Key&) const = default;
    };
    struct Hash {
        size_t operator()(const Key& key) const {
            uint64_t h = 0;
            const auto mix = [&](uint64_t v) { h ^= v + 0x9e3779b97f4a7c15ULL + (h << 6) + (h >> 2); };
            const auto& d = key.draw;
            mix(d.shader); mix(d.geometry); mix(d.indices); mix(d.topology);
            mix(d.index_count); mix(d.instances); mix(d.first_instance);
            mix(d.vertices.first); mix(d.vertices.count); mix(key.occurrence);
            return size_t(h);
        }
    };
    uint32_t capacity{}, used{};
    // bbport (r34_motion-store)
    uint32_t used_back{};    ///< room the second class took from the top this frame
    uint32_t reserve{};      ///< room the second class leaves (first_demand of last frame)
    uint64_t first_demand{}; ///< room the first class would take this frame with the whole store
    uint32_t last_age{};     ///< frames since the palette changed, of the last held Moving call
    uint32_t frame_prepares{}, first_skip{}; ///< Prepare calls; 1-based call of the first skip
    bool last_held{};
    void Note(Sort sort, const Draw& draw, uint64_t count, bool fits, bool first, bool repeat) {
        auto& kind = store.kinds[size_t(sort.kind) < KindCount ? size_t(sort.kind) : 0];
        (fits ? kind.stored_draws : kind.skipped_draws) += 1;
        (fits ? kind.stored : kind.skipped) += count;
        if (draw.instances > 1) {
            (fits ? store.instanced_stored : store.instanced_skipped) += count;
        }
        if (repeat) {
            (fits ? store.repeat_stored : store.repeat_skipped) += count;
        }
        if (sort.used) {
            store.known_span += count;
            store.known_used += uint64_t(std::min(sort.used, draw.vertices.count)) * draw.instances;
            if (Sparse(sort, draw.vertices.count)) {
                ++store.sparse_draws;
                store.sparse_vertices += count;
                store.sparse_demoted += FirstKind(sort.kind) ? 1 : 0;
            }
        }
        if (!first && fits) {
            store.second += count;
        }
    }
    uint32_t hold{}; ///< frames a small skeleton keeps its history after a change (SetHold)
    uint64_t frame{};
    FlatMap<Key, uint32_t, Hash> previous, current, occurrences;
    struct GateHash {
        size_t operator()(const GateKey& key) const {
            uint64_t h = 0;
            const auto mix = [&](uint64_t v) { h ^= v + 0x9e3779b97f4a7c15ULL + (h << 6) + (h >> 2); };
            mix(key.shader); mix(key.geometry); mix(key.indices); mix(key.index_count);
            mix(key.instances); mix(key.first_instance); mix(key.occurrence);
            return size_t(h);
        }
    };
    struct GateState {
        uint64_t palette{};
        uint32_t hold{}; ///< further frames this draw keeps its history (Moving)
    };
    FlatMap<GateKey, GateState, GateHash> gate_previous, gate_current;
    FlatMap<GateKey, uint32_t, GateHash> gate_occurrences;
};

} // namespace Vulkan::Motion
