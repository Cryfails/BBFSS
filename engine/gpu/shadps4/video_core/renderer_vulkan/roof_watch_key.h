// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <string_view>

#include "interior_roof_probe.h"

namespace Vulkan::InteriorRoof {

struct WatchKey { U64 key, mesh; };
inline constexpr std::array LibraryWatch{WatchKey{0x7b81dab39d5a59d6, 0x17507e8a05f70436},
                                          WatchKey{0xc7aceb07c5d0d623, 0x4b935065d6c74728}};
inline constexpr std::array ChurchWatch{WatchKey{0xbd9f73ad95d752b2, 0x0dae8104331bca60},
                                         WatchKey{0x737fc633dfa3e29b, 0x4133290936b83d77}};
struct WatchFrame {
    U32 mesh_draws = 0, key_draws = 0, queued = 0, captured = 0, listed = 0;
    U32 held_seen = 0, held_pick = 0, held_next = 0, scanned = 0, emitted = 0, id = ROOF_NONE;
    U32 unassigned_guard = 0;
    U32 cache_count = 0;
    bool cache_known = false, publication = false;
    U64 serial = 0, lifetime = 0, capture_frame = 0;
    const char* mesh_why = "unknown";
    const char* draw_why = "unknown";
    const char* hold_why = "unknown";
    const char* emit_why = "unknown";
    const char* cache_why = "unknown";

    bool SameState(const WatchFrame& other) const {
        return !!mesh_draws == !!other.mesh_draws && !!key_draws == !!other.key_draws &&
               !!queued == !!other.queued && !!captured == !!other.captured &&
               !!listed == !!other.listed && !!held_seen == !!other.held_seen &&
               !!held_pick == !!other.held_pick && !!held_next == !!other.held_next &&
               !!scanned == !!other.scanned && !!unassigned_guard == !!other.unassigned_guard &&
               emitted == other.emitted && cache_count == other.cache_count &&
               cache_known == other.cache_known && publication == other.publication &&
               lifetime == other.lifetime && std::string_view(mesh_why) == other.mesh_why &&
               std::string_view(draw_why) == other.draw_why &&
               std::string_view(hold_why) == other.hold_why && std::string_view(emit_why) == other.emit_why &&
               std::string_view(cache_why) == other.cache_why;
    }
};

struct WatchRow {
    WatchKey target{};
    WatchFrame now{}, prior{}, first_change{}, last_change{};
    struct Cached { U64 address{}, lifetime{}, capture_frame{}; };
    std::array<Cached, 8> cache{};
    bool overflow = false, had_cache = false, had_prior = false;
    U32 transitions = 0;
    U64 first_transition = 0, last_transition = 0;

    void Cache(U64 address, GeometryRevision revision, U64 capture, const char* reason) {
        if (!address) {
            return;
        }
        auto found = std::ranges::find(cache, address, &Cached::address);
        if (found == cache.end()) {
            found = std::ranges::find(cache, U64{}, &Cached::address);
            if (found == cache.end()) {
                overflow = true;
                return;
            }
        }
        *found = {address, revision.lifetime, capture};
        had_cache = true;
        now.lifetime = revision.lifetime;
        now.capture_frame = capture;
        now.cache_why = reason;
    }
    void Forget(U64 address, const char* reason) {
        const auto found = std::ranges::find(cache, address, &Cached::address);
        if (address && found != cache.end()) {
            *found = {};
            now.cache_why = reason;
        }
    }
    void Seal(U64 frame) {
        const auto live = [](const Cached& item) { return item.address != 0; };
        now.cache_count = U32(std::ranges::count_if(cache, live));
        now.cache_known = had_cache && !overflow && !now.unassigned_guard;
        if (now.emitted != 1) {
            const auto single = now.cache_count == 1 && now.cache_known
                ? *std::ranges::find_if(cache, live) : Cached{};
            now.lifetime = single.lifetime;
            now.capture_frame = single.capture_frame;
        }
        if (had_prior && !now.SameState(prior)) {
            if (transitions++ == 0) {
                first_transition = frame;
                first_change = now;
            }
            last_transition = frame;
            last_change = now;
        }
        prior = now;
        had_prior = true;
        now = {};
    }
};

struct KeyWatch {
    std::array<WatchRow, 2> rows{};
    bool Active() const { return rows[0].target.key != 0; }
    void Select(const std::array<WatchKey, 2>& keys) {
        for (U32 i = 0; i < rows.size(); ++i) {
            rows[i].target = keys[i];
        }
    }
    WatchRow* ByMesh(U64 mesh) {
        if (mesh) {
            for (auto& row : rows) {
                if (row.target.mesh == mesh) {
                    return &row;
                }
            }
        }
        return nullptr;
    }
    WatchRow* Exact(U64 key, U64 mesh) {
        auto* row = ByMesh(mesh);
        return row && row->target.key == key ? row : nullptr;
    }
    void SceneRefusal(const char* reason) {
        for (auto& row : rows) {
            if (!row.now.publication) {
                row.now.emit_why = reason;
            }
        }
    }
    void UnassignedGuard() {
        for (auto& row : rows) {
            ++row.now.unassigned_guard;
        }
    }
    void Published(const Scene& scene) {
        for (auto& row : rows) {
            row.now.publication = true;
            row.now.serial = scene.serial;
            row.now.emitted = 0;
            row.now.id = ROOF_NONE;
            if (std::string_view(row.now.emit_why) == "selected-without-blas") {
                continue;
            }
            if (row.now.scanned) {
                row.now.emit_why = "scanned-but-absent-from-published-order";
            } else if (scene.requested > MaxRecords) {
                row.now.emit_why = "absent-with-instance-cap";
            } else {
                row.now.emit_why = "absent-from-published-order";
            }
        }
        for (U32 i = 0; i < scene.records.size(); ++i) {
            const auto& record = scene.records[i];
            if (auto* row = Exact(record.key, record.mesh)) {
                ++row->now.emitted;
                row->now.id = row->now.emitted == 1 ? i : ROOF_NONE;
                row->now.lifetime = record.geometry.lifetime;
                row->now.capture_frame = record.capture_frame;
                row->now.emit_why = "emitted";
            }
        }
    }
};

struct Digest {
    U64 members{}, revisions{}, masks{}, clip_maps{};
    U32 records{}, unknown{};
};
inline U64 WatchMix(U64 x) {
    x ^= x >> 30;
    x *= 0xbf58476d1ce4e5b9ull;
    x ^= x >> 27;
    x *= 0x94d049bb133111ebull;
    return x ^ (x >> 31);
}

// Order-independent multisets of recorded observations. A match is only a
// digest match. Unknown capture inputs remain unknown, even across a match.
inline Digest ObserveContent(const Scene& scene) {
    Digest out;
    out.records = U32(scene.records.size());
    for (const auto& row : scene.records) {
        const U64 member = WatchMix(row.key) + 3 * WatchMix(row.mesh) + 7 * WatchMix(row.geometry.lifetime);
        out.members += WatchMix(member);
        out.revisions += WatchMix(member + WatchMix(row.geometry.recorded) + 3 * WatchMix(row.capture_frame) + 7 * WatchMix(row.captured_inputs));
        out.masks += WatchMix(member + WatchMix(row.flags) + (row.held ? 3 : 0));
        out.clip_maps += WatchMix(member + WatchMix(row.geometry.clip_to_world));
        out.unknown += !row.key || !row.mesh || !row.geometry.lifetime || !row.geometry.recorded ||
                       !row.geometry.clip_to_world || !row.captured_inputs;
    }
    return out;
}

struct ContentDifference {
    bool available = false, serial_changed = false, membership = false,
         revision = false, masks = false, clip = false, view = false;
    U32 missing_query = 0, missing_current = 0;

    const char* Name() const {
        if (!available) return "unknown";
        if (membership || revision || masks || clip || view) return "observed-change";
        return missing_query || missing_current ? "unknown" : "digest-match";
    }
};
inline ContentDifference CompareContent(const Scene& query, const Scene* current) {
    ContentDifference out{.serial_changed = current && query.serial != current->serial};
    if (!current || query.records.empty() || current->records.empty() ||
        query.records.size() > MaxRecords || current->records.size() > MaxRecords) {
        return out;
    }
    const auto a = ObserveContent(query);
    const auto b = ObserveContent(*current);
    out.available = true;
    out.membership = a.records != b.records || a.members != b.members;
    if (!out.membership) {
        out.revision = a.revisions != b.revisions;
        out.masks = a.masks != b.masks;
        out.clip = a.clip_maps != b.clip_maps;
    }
    out.view = query.tlas_view != current->tlas_view;
    out.missing_query = a.unknown;
    out.missing_current = b.unknown;
    return out;
}

} // namespace Vulkan::InteriorRoof

