// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <unordered_map>
#include <vector>

#include "../host_shaders/interior_roof_layout.h"

namespace Vulkan::InteriorRoof {
using U32 = std::uint32_t;
using U64 = std::uint64_t;
using Vec = std::array<float, 3>;
using Matrix = std::array<float, 12>;
inline constexpr U32 MaxRecords = 8192, Slots = 3;
inline constexpr U64 PeriodMs = 250;

struct Camera {
    Matrix view{}, inverse{};
    bool operator==(const Camera&) const = default;
    [[nodiscard]] Vec Position() const { return {inverse[3], inverse[7], inverse[11]}; }
};
inline Vec Transform(const Matrix& matrix, const Vec& value, float w) {
    Vec out{};
    for (U32 i = 0; i < out.size(); ++i) {
        const float* row = matrix.data() + i * 4;
        out[i] = row[0] * value[0] + row[1] * value[1] + row[2] * value[2] + row[3] * w;
    }
    return out;
}
inline float Dot(const Vec& a, const Vec& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}
inline bool Valid(const Camera& camera) {
    const auto finite = [](float x) { return std::isfinite(x); };
    if (!std::ranges::all_of(camera.view, finite) || !std::ranges::all_of(camera.inverse, finite)) {
        return false;
    }
    const auto origin = Transform(camera.view, camera.Position(), 1.0f);
    if (!(Dot(origin, origin) <= 0.01f * 0.01f)) {
        return false;
    }
    for (U32 i = 0; i < 3; ++i) {
        Vec basis{};
        basis[i] = 1.0f;
        const auto view_axis = Transform(camera.view, basis, 0.0f);
        const auto round_trip = Transform(camera.inverse, view_axis, 0.0f);
        for (U32 j = 0; j < 3; ++j) {
            Vec other{};
            other[j] = 1.0f;
            if (!(std::abs(round_trip[j] - basis[j]) <= 0.001f) ||
                !(std::abs(Dot(view_axis, Transform(camera.view, other, 0.0f)) - basis[j]) <= 0.001f)) {
                return false;
            }
        }
    }
    return true;
}
inline Vec Direction(U32 index) {
    constexpr float d = 0.3535533905932738f;
    constexpr float y = 0.8660254037844386f;
    constexpr std::array<Vec, ROOF_RAYS> fan{{
        {0, 1, 0}, {0.5f, y, 0}, {d, y, d}, {0, y, 0.5f}, {-d, y, d},
        {-0.5f, y, 0}, {-d, y, -d}, {0, y, -0.5f}, {d, y, -d},
    }};
    return fan[index];
}
enum Exclusion : U32 { Glass = 1, Cutout = 2, Skinned = 4, Moving = 8, Palette = 16 };
inline U32 Flags(U32 mask, bool glass, bool cutout, bool skinned, bool moving, bool palette) {
    const U32 exclusions = (glass ? Glass : 0u) | (cutout ? Cutout : 0u) |
                           (skinned ? Skinned : 0u) | (moving ? Moving : 0u) |
                           (palette ? Palette : 0u);
    return (mask & 0xffu) | (exclusions << ROOF_EXCLUDE_SHIFT);
}
// Stamps describe recorded BLAS work and its clip-to-world map. A rebuild can
// use an identical map and produce identical geometry. A changed map is not object motion.
struct GeometryRevision {
    U64 lifetime{}, recorded{}, clip_to_world{};
};

class GeometryRevisions {
public:
    void Record(U64 address, U64 clip_to_world) {
        if (!address) {
            return;
        }
        auto entry = records.find(address);
        if (entry == records.end()) {
            if (records.size() == MaxRecords) {
                ++drops;
                return;
            }
            entry = records.emplace(address, GeometryRevision{}).first;
            entry->second.lifetime = sequence + 1;
        }
        entry->second.recorded = ++sequence;
        entry->second.clip_to_world = clip_to_world;
    }

    void Forget(U64 address) { records.erase(address); }
    [[nodiscard]] GeometryRevision Find(U64 address) const {
        const auto it = records.find(address);
        return it == records.end() ? GeometryRevision{} : it->second;
    }
    [[nodiscard]] U64 Drops() const { return drops; }

private:
    std::unordered_map<U64, GeometryRevision> records;
    U64 sequence{}, drops{};
};

struct Record {
    U64 key, mesh, capture_frame;
    U32 flags;
    bool held;
    bool palette_nonzero = false;
    bool palette_placed = false;
    GeometryRevision geometry{};
    U64 captured_inputs = 0; // Existing capture input signature. Zero means unknown.
};
static_assert(sizeof(Record) <= 64);

struct Scene {
    Camera camera;
    std::vector<Record> records;
    U64 serial = 0, frame = 0, ms = 0;
    U32 held = 0, requested = 0, flags = 0;
    U32 palette_nonzero = 0, palette_placed = 0, palette_both = 0, geometry_unknown = 0;
    U64 tlas_view = 0;
};

inline bool Append(Scene& scene, U32 emitted_id, const Record& record) {
    if (emitted_id != scene.records.size() || emitted_id >= MaxRecords) {
        return false;
    }
    scene.records.push_back(record);
    scene.held += record.held;
    scene.palette_nonzero += record.palette_nonzero;
    scene.palette_placed += record.palette_placed;
    scene.palette_both += record.palette_nonzero && record.palette_placed;
    scene.geometry_unknown += record.geometry.recorded == 0;
    return true;
}

struct EmittedPresence {
    U32 matching_key{};
    U32 matching_lifetime{};
    U32 unique_key_id{ROOF_NONE};
    U32 unique_lifetime_id{ROOF_NONE};
    [[nodiscard]] U32 Id() const {
        return matching_lifetime == 1 ? unique_lifetime_id :
               matching_key == 1 ? unique_key_id : ROOF_NONE;
    }
};

// Match the reported base key and mesh. An exact BLAS lifetime is separately
// reported when available. A repeated base key or lifetime can be ambiguous.
inline EmittedPresence FindEmitted(const Scene& scene, const Record& watch) {
    EmittedPresence result;
    for (U32 i = 0; i < scene.records.size(); ++i) {
        const Record& record = scene.records[i];
        if (record.key != watch.key || record.mesh != watch.mesh) {
            continue;
        }
        ++result.matching_key;
        result.unique_key_id = i;
        if (watch.geometry.lifetime && record.geometry.lifetime == watch.geometry.lifetime) {
            ++result.matching_lifetime;
            result.unique_lifetime_id = i;
        }
    }
    return result;
}

template <class SlotArray>
auto FreeSlot(SlotArray& slots) {
    return std::ranges::find_if(slots, [](const auto& slot) { return slot.tick == 0; });
}
template <class IsFree>
bool Ready(U64 tick, IsFree is_free) {
    return tick && is_free(tick);
}

struct Ray {
    U32 status, candidates, hit_id, hit_primitive, hit_front;
    float hit_t;
    U32 raw_id, raw_primitive, raw_front;
    float raw_t;
    std::array<U32, 5> rejected;
    U32 reserved;
};
static_assert(sizeof(Ray) == 64);
using Results = std::array<Ray, ROOF_RAYS>;

inline bool Complete(const Ray& ray, U32 records) {
    const auto valid = [records](U32 id, float t) {
        return id == ROOF_NONE || (id < records && t >= ROOF_TMIN && t <= ROOF_TMAX);
    };
    return records && ray.status == ROOF_DONE && ray.candidates <= ROOF_CANDIDATES &&
           valid(ray.hit_id, ray.hit_t) && valid(ray.raw_id, ray.raw_t) &&
           (ray.hit_id == ROOF_NONE || (ray.raw_id != ROOF_NONE && ray.raw_t <= ray.hit_t));
}
inline bool OriginChanged(const Vec& origin, const Vec& current) {
    const Vec delta{origin[0] - current[0], origin[1] - current[1], origin[2] - current[2]};
    return Dot(delta, delta) > 0.001f * 0.001f;
}

struct Staleness {
    bool age{}, generation{}, origin{}, scene_missing{}, unavailable{};
    [[nodiscard]] bool Any() const {
        return age || generation || origin || scene_missing || unavailable;
    }
};

inline Staleness CompareSample(U64 at, U64 now, U64 query_generation, U64 current_generation,
                              const Vec& origin, const Vec& current_origin, bool unavailable,
                              bool origin_current) {
    return {
        .age = now - at > PeriodMs,
        .generation = current_generation && query_generation != current_generation,
        .origin = origin_current && OriginChanged(origin, current_origin),
        .scene_missing = current_generation == 0,
        .unavailable = unavailable,
    };
}

inline bool Stale(U64 at, U64 now, U64 generation, U64 current, const Vec& origin, const Vec& current_origin) {
    return now - at > PeriodMs || generation != current || OriginChanged(origin, current_origin);
}
} // namespace Vulkan::InteriorRoof
