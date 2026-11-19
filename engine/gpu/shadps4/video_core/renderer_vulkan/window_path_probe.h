// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <memory>
#include <span>

#include "../host_shaders/glass_light_layout.h"
#include "../host_shaders/glass_light_forward_layout.h"
#include "../host_shaders/window_path_probe_layout.h"
#include "glass_registry.h"
#include "interior_roof_probe.h"

namespace Vulkan::WindowPathProbe {
namespace Roof = InteriorRoof;
using Roof::U32;
using Roof::U64;
using Roof::Vec;
using Roof::Dot;
using Roof::Transform;
static_assert(WP_RECORDS == Roof::MaxRecords);
static_assert(WP_SEGMENTS == WP_RECEIVERS * (WP_LAMPS + 1u));

struct Stamp {
    U64 request = 0, frame = 0, generation = 0, camera = 0, depth_uid = 0;
    bool operator==(const Stamp&) const = default;
    bool Valid() const { return request && frame && generation && camera && depth_uid; }
};
struct DrawKey {
    U64 vs = 0, ps = 0;
    U32 count = 0, first = GlassRegistryRules::AnyFirst;
    bool operator==(const DrawKey&) const = default;
};
inline U32 ExactRegistry(const GlassRegistryRules::Table& table, const DrawKey& key) {
    if (!key.vs || !key.ps || !key.count || key.first == GlassRegistryRules::AnyFirst) {
        return 0;
    }
    const U32 n = GlassRegistryRules::Lookup(table, key.vs, key.ps, key.count, key.first);
    if (!n || n > table.count) {
        return 0;
    }
    const auto& entry = table.entries[n - 1];
    return entry.kind == GlassRegistryRules::Kind::Window && entry.index_count == key.count &&
           entry.first_index == key.first ? n : 0;
}

struct Ray {
    Vec origin{}, direction{};
    float minimum = 0, maximum = 0;
};
inline Vec Sub(const Vec& a, const Vec& b) {
    return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}
inline Vec At(const Ray& ray, float t) {
    return {ray.origin[0] + ray.direction[0] * t, ray.origin[1] + ray.direction[1] * t,
            ray.origin[2] + ray.direction[2] * t};
}
inline bool Finite(const Vec& v) {
    return std::ranges::all_of(v, [](float x) { return std::isfinite(x); });
}
inline bool Unit(const Vec& v) {
    return Finite(v) && std::abs(Dot(v, v) - 1.0f) < 0.001f;
}
inline bool ValidRay(const Ray& ray) {
    return Finite(ray.origin) && Unit(ray.direction) && std::isfinite(ray.minimum) &&
           std::isfinite(ray.maximum) && ray.minimum >= 0 && ray.maximum > ray.minimum;
}
inline Ray LampCentreRay(Vec origin, const Vec& centre, float measured_minimum) {
    const Vec d = Sub(centre, origin);
    const float len = std::sqrt(Dot(d, d));
    if (!(std::isfinite(len) && len > float(GLASS_LAMP_CLEAR))) {
        return {};
    }
    return {origin, {d[0] / len, d[1] / len, d[2] / len},
            std::max(measured_minimum, float(GLASS_LIGHT_TMIN)), len - float(GLASS_LAMP_CLEAR)};
}

struct Triangle {
    U32 primitive = WP_NONE;
    std::array<Vec, 3> corners{};
};
// A directly attributed depth point must lie on the local triangle, inside its edges.
// The producer supplies its measured uncertainty, capped at the existing pane picker's 1 cm.
inline bool Contains(const Triangle& tri, const Vec& p, float tolerance) {
    if (!Finite(p) || !(tolerance > 0 && tolerance <= 0.01f) ||
        !std::ranges::all_of(tri.corners, Finite)) {
        return false;
    }
    const Vec a = Sub(tri.corners[1], tri.corners[0]);
    const Vec b = Sub(tri.corners[2], tri.corners[0]);
    const Vec q = Sub(p, tri.corners[0]);
    const float aa = Dot(a, a), bb = Dot(b, b), ab = Dot(a, b);
    const float det = aa * bb - ab * ab;
    if (!(det > 1e-10f)) {
        return false;
    }
    const float u = (bb * Dot(q, a) - ab * Dot(q, b)) / det;
    const float v = (aa * Dot(q, b) - ab * Dot(q, a)) / det;
    const Vec error{q[0] - u * a[0] - v * b[0], q[1] - u * a[1] - v * b[1], q[2] - u * a[2] - v * b[2]};
    return u > 1e-5f && v > 1e-5f && u + v < 1.0f - 1e-5f && Dot(error, error) <= tolerance * tolerance;
}
inline bool SameTriangle(const Triangle& a, const Triangle& b) {
    std::array<U32, 3> order{0, 1, 2};
    do {
        bool same = true;
        for (U32 i = 0; i < order.size(); ++i) {
            const Vec d = Sub(a.corners[i], b.corners[order[i]]);
            same &= Dot(d, d) <= 0.001f * 0.001f;
        }
        if (same) {
            return true;
        }
    } while (std::ranges::next_permutation(order).found);
    return false;
}

struct RecordFacts {
    U64 key = 0, capture_frame = 0;
    U32 triangles = 0, custom_index = 0;
};
struct PublishedScene {
    std::shared_ptr<const Roof::Scene> scene; // same retained record order and camera as t132e
    std::span<const RecordFacts> facts;       // window-only extension, in the exact same order
    Stamp stamp;
    bool guarded = false;
    bool single_triangle_geometry = false;   // existing BLAS geometryCount=1, no forced-opaque instances
};
struct Witness {
    Triangle triangle;
    Vec depth_point{};
    float tolerance = 0;
    U32 camera_primitive = WP_NONE; // for a twin, the directly witnessed primitive on the camera BLAS
};
struct Selection {
    Stamp stamp;
    DrawKey exact_camera_draw;
    U32 record = WP_NONE, camera_record = WP_NONE;
    U64 key = 0, capture_frame = 0;
    std::span<const Witness> witnesses;
    // These assertions come from the new hookup's readback, never from a registry tag alone.
    bool final_gbuffer_owner = false;
    bool exact_shadow_range_twin = false;
};
enum class DirectKind : U32 { Unavailable, LightSetOnly, IsolatedDelta };
struct Direct {
    Stamp stamp;
    U64 draw = 0, output_uid = 0;
    U32 x = 0, y = 0, light_set = WP_NONE;
    Vec before{}, after{};
    DirectKind kind = DirectKind::Unavailable;
};
struct Receiver {
    Stamp stamp;
    Vec world{}, normal{};
    U32 x = 0, y = 0;
    U64 owner_key = 0;
    Triangle surface;
    float depth_tolerance = 0;
    // The producer matched the nearest original depth to the actual owner and verified that
    // surface is the receiver of interest (an intervening actor/prop is not that receiver).
    bool receiver_owner_verified = false;
    Direct direct;
};
enum class Path : U32 { SunOpaque, LampOpaque, Unsupported };
struct Segment {
    Stamp stamp;
    U32 receiver = WP_NONE, light = WP_NONE; // directional draw identity or actual lamp record ID
    Path path = Path::Unsupported;
    Ray solid;
    Vec source{}, rgb{}, glass_origin{}; // toward-light unit vector for sun, centre for lamp
    float range = 0, glass_minimum = 0;
};
struct Request {
    DrawKey exact;
    PublishedScene publication;
    std::span<const Selection> selected;
    std::span<const Receiver> receivers;
    std::span<const Segment> segments;
};

struct GpuRay { std::array<float, 4> o_min, d_max; };
struct GpuSegment { GpuRay solid, pane; std::array<U32, 4> masks; };
struct GpuSelection {
    std::array<U32, 4> info; // record ID, origin camera record, one-based registry index, tag verified
    std::array<U32, WP_TRI_WORDS> bits;
};
using GpuRecord = std::array<U32, 2>;
struct GpuInput {
    std::array<GpuSegment, WP_SEGMENTS> segments;
    std::array<GpuSelection, WP_SELECTED> selected;
    std::array<GpuRecord, WP_RECORDS> records;
};
struct Hit {
    U32 status, looked, id, primitive, custom, front;
    float distance;
    U32 reserved;
};
struct Result { Hit pane, actual, skipped; };
struct Push { U32 segments, records, selected; };
static_assert(sizeof(GpuSegment) == 80 && sizeof(GpuSelection) == 48 && sizeof(GpuRecord) == 8);
static_assert(sizeof(Hit) == 32 && sizeof(Result) == 96 && sizeof(Push) == 12);
static_assert(sizeof(Result) * WP_SEGMENTS <= 16 * 1024);
struct Packet {
    GpuInput gpu{};
    Push counts{};
    DrawKey exact;
    Stamp stamp;
    std::shared_ptr<const Roof::Scene> scene;
    std::array<Receiver, WP_RECEIVERS> receivers{};
    std::array<Segment, WP_SEGMENTS> segments{};
    std::array<Ray, WP_SEGMENTS> pane_rays{};
    U32 registry = 0;
};

enum class Status {
    Ready, Disabled, Busy, Budget, MissingScene, Stale, Registry, RecordOrder,
    PaneProvenance, ReceiverEvidence, UnsupportedPath, Readback
};
inline GpuRay PackRay(const Ray& ray, const Roof::Camera& camera) {
    const Vec o = Transform(camera.view, ray.origin, 1);
    const Vec d = Transform(camera.view, ray.direction, 0);
    return {{o[0], o[1], o[2], ray.minimum}, {d[0], d[1], d[2], ray.maximum}};
}
inline bool IsSelected(const Packet& p, U32 id, U32 primitive) {
    return primitive < WP_TRI_WORDS * 32 && std::ranges::any_of(
        std::span(p.gpu.selected).first(p.counts.selected), [&](const GpuSelection& s) {
            return s.info[0] == id && ((s.bits[primitive / 32] >> (primitive % 32)) & 1u);
        });
}
inline Status Prepare(const Request& r, const GlassRegistryRules::Table& table, Packet& out) {
    const auto& pub = r.publication;
    if (!pub.scene || !pub.guarded || !pub.single_triangle_geometry || pub.scene->records.empty() ||
        !Roof::Valid(pub.scene->camera)) {
        return Status::MissingScene;
    }
    if (!pub.stamp.Valid() || pub.stamp.generation != pub.scene->serial || pub.scene->frame > pub.stamp.frame) {
        return Status::Stale;
    }
    if (r.receivers.empty() || r.receivers.size() > WP_RECEIVERS || r.segments.empty() ||
        r.segments.size() > WP_SEGMENTS || r.selected.size() > WP_SELECTED || pub.facts.size() > WP_RECORDS) {
        return Status::Budget;
    }
    if (pub.facts.size() != pub.scene->records.size()) {
        return Status::RecordOrder;
    }
    out.registry = ExactRegistry(table, r.exact);
    if (!out.registry) {
        return Status::Registry;
    }
    out.exact = r.exact;
    out.stamp = pub.stamp;
    out.scene = pub.scene;
    out.counts = {U32(r.segments.size()), U32(pub.facts.size()), U32(r.selected.size())};
    for (U32 i = 0; i < out.counts.records; ++i) {
        const auto& f = pub.facts[i];
        const auto& record = pub.scene->records[i];
        if (f.key != record.key || f.capture_frame != record.capture_frame ||
            f.capture_frame > pub.stamp.frame || f.custom_index > 0xffffffu) {
            return Status::RecordOrder;
        }
        // Unknown records are not safe blockers or clear space. The shader refuses a hit on one.
        out.gpu.records[i] = {record.key && f.capture_frame ? f.triangles : 0,
                              ((record.flags & 0xffu) << 24u) | f.custom_index};
    }
    U32 masks = 0;
    bool all_tagged = true;
    bool camera_witness = false;
    for (U32 i = 0; i < out.counts.selected; ++i) {
        const auto& s = r.selected[i];
        if (s.stamp != out.stamp) {
            return Status::Stale;
        }
        if (s.exact_camera_draw != r.exact || s.record >= out.counts.records ||
            s.witnesses.empty() || s.witnesses.size() > WP_TRI_WORDS * 32 ||
            std::ranges::any_of(r.selected.first(i), [&](const Selection& a) { return a.record == s.record; })) {
            return Status::PaneProvenance;
        }
        const auto& f = pub.facts[s.record];
        const U32 mask = pub.scene->records[s.record].flags & 0xffu;
        const bool tagged = (f.custom_index & GLASS_INDEX_BIT) != 0;
        if (!s.key || f.key != s.key || f.capture_frame != s.capture_frame ||
            !s.capture_frame || f.triangles == 0 || f.triangles > WP_TRI_WORDS * 32 || mask == 0 ||
            (tagged && ((mask & GLASS_LIGHT_MASK) == 0 ||
             f.custom_index != (GLASS_INDEX_BIT | (out.registry - 1))))) {
            return Status::PaneProvenance;
        }
        const bool is_camera = s.camera_record == s.record && s.final_gbuffer_owner;
        auto& gpu = out.gpu.selected[i];
        gpu = {{s.record, s.camera_record, out.registry, U32(tagged)}, {}};
        for (const auto& w : s.witnesses) {
            const U32 primitive = w.triangle.primitive;
            if (primitive >= f.triangles || ((gpu.bits[primitive / 32] >> (primitive % 32)) & 1u)) {
                return Status::PaneProvenance;
            }
            if (is_camera) {
                if (!Contains(w.triangle, w.depth_point, w.tolerance)) {
                    return Status::PaneProvenance;
                }
            } else {
                const auto camera = std::ranges::find_if(r.selected, [&](const Selection& other) {
                    return other.record == s.camera_record && other.camera_record == other.record &&
                           other.final_gbuffer_owner;
                });
                if (!s.exact_shadow_range_twin || camera == r.selected.end() ||
                    std::ranges::none_of(camera->witnesses, [&](const Witness& camera_w) {
                        return camera_w.triangle.primitive == w.camera_primitive &&
                               SameTriangle(camera_w.triangle, w.triangle);
                    })) {
                    return Status::PaneProvenance;
                }
            }
            gpu.bits[primitive / 32] |= 1u << (primitive % 32);
        }
        all_tagged &= tagged;
        masks |= mask;
        camera_witness |= is_camera;
    }
    if (!camera_witness) {
        return Status::PaneProvenance;
    }
    for (U32 i = 0; i < r.receivers.size(); ++i) {
        const auto& rec = r.receivers[i];
        if (rec.stamp != out.stamp) {
            return Status::Stale;
        }
        if (!rec.receiver_owner_verified || !rec.owner_key || rec.surface.primitive == WP_NONE ||
            !Unit(rec.normal) || !Contains(rec.surface, rec.world, rec.depth_tolerance)) {
            return Status::ReceiverEvidence;
        }
        out.receivers[i] = rec; // keep raw light-set evidence from this same request until fence completion
    }
    std::array<U32, WP_LAMPS> lamp_ids{};
    U32 lamps = 0;
    for (U32 i = 0; i < out.counts.segments; ++i) {
        const auto& s = r.segments[i];
        if (s.stamp != out.stamp) {
            return Status::Stale;
        }
        if (s.receiver >= r.receivers.size() || s.light == WP_NONE || !ValidRay(s.solid) || !Finite(s.rgb) ||
            std::ranges::any_of(r.segments.first(i), [&](const Segment& a) {
                return a.receiver == s.receiver && a.path == s.path && a.light == s.light;
            })) {
            return Status::UnsupportedPath;
        }
        const bool sun = s.path == Path::SunOpaque;
        const auto& receiver = r.receivers[s.receiver];
        const Vec bias = Sub(s.solid.origin, receiver.world);
        if (Dot(bias, receiver.normal) < -0.001f) {
            return Status::UnsupportedPath;
        }
        if (sun) {
            if (!Unit(s.source) || Dot(s.source, s.solid.direction) <= 0 || !(s.range > 0) ||
                !std::isfinite(s.range) || s.solid.maximum > s.range ||
                std::ranges::any_of(r.segments.first(i), [&](const Segment& a) {
                    return a.path == s.path && (a.light != s.light || a.receiver == s.receiver);
                })) {
                return Status::UnsupportedPath;
            }
        } else if (s.path != Path::LampOpaque || !Finite(s.source) || !Finite(s.glass_origin) ||
                   !(s.range > 0) || !std::isfinite(s.range) ||
                   !std::isfinite(s.glass_minimum) || s.glass_minimum < 0) {
            return Status::UnsupportedPath;
        }
        if (!sun) {
            const auto seen = std::span(lamp_ids).first(lamps);
            if (std::ranges::find(seen, s.light) == seen.end()) {
                if (lamps == lamp_ids.size()) {
                    return Status::Budget;
                }
                lamp_ids[lamps++] = s.light;
            }
        }
        const Ray pane = sun ? s.solid : LampCentreRay(s.glass_origin, s.source, s.glass_minimum);
        if (!ValidRay(pane)) {
            return Status::UnsupportedPath;
        }
        out.segments[i] = s;
        out.pane_rays[i] = pane;
        out.gpu.segments[i] = {PackRay(s.solid, pub.scene->camera), PackRay(pane, pub.scene->camera),
                               {sun ? 0x01u : 0x04u, all_tagged ? GLASS_LIGHT_MASK : masks, 0, 0}};
    }
    return Status::Ready;
}

enum class Geometry { Unresolved, NoSelectedCrossing, ClearBeforeSkip, StillBlocked, Opened };
struct Evidence {
    Geometry geometry = Geometry::Unresolved;
    DirectKind direct = DirectKind::Unavailable;
    Vec delta{};
};
inline bool MatchHit(const Packet& p, const Hit& h, const Ray& ray, U32 mask, U32 mode) {
    if (h.status != WP_COMPLETE || h.looked > WP_CANDIDATES) {
        return false;
    }
    if (h.id == WP_NONE) {
        return h.primitive == WP_NONE && h.custom == WP_NONE && h.distance == -1;
    }
    if (!h.looked || h.id >= p.counts.records || h.front > 1 ||
        !(h.distance >= ray.minimum && h.distance <= ray.maximum)) {
        return false;
    }
    const auto& record = p.gpu.records[h.id];
    return h.primitive < record[0] && h.custom == (record[1] & 0xffffffu) &&
           ((record[1] >> 24u) & mask) != 0 && WP_ACCEPT(mode, IsSelected(p, h.id, h.primitive));
}
inline Evidence Resolve(const Packet& p, U32 i, const Result& r, Stamp wanted) {
    Evidence result;
    if (wanted != p.stamp || i >= p.counts.segments) {
        return result;
    }
    const auto& segment = p.segments[i];
    const auto& rec = p.receivers[segment.receiver];
    const auto& d = rec.direct;
    if (segment.path == Path::SunOpaque && d.kind != DirectKind::Unavailable &&
        d.stamp == p.stamp && d.draw && d.draw == segment.light && d.x == rec.x && d.y == rec.y && d.light_set < 256) {
        result.direct = DirectKind::LightSetOnly; // set 0 is a valid index, not zero irradiance
        if (d.kind == DirectKind::IsolatedDelta && d.output_uid && Finite(d.before) && Finite(d.after)) {
            result.delta = Sub(d.after, d.before);
            if (Finite(result.delta)) {
                result.direct = DirectKind::IsolatedDelta;
            }
        }
    }
    const auto& masks = p.gpu.segments[i].masks;
    if (!MatchHit(p, r.pane, p.pane_rays[i], masks[1], WP_PANE) ||
        !MatchHit(p, r.actual, segment.solid, masks[0], WP_ACTUAL) ||
        !MatchHit(p, r.skipped, segment.solid, masks[0], WP_SKIP)) {
        return result;
    }
    if (r.skipped.id != WP_NONE && (r.actual.id == WP_NONE || r.actual.distance > r.skipped.distance + 0.001f)) {
        return result;
    }
    const bool actual_selected = r.actual.id != WP_NONE && IsSelected(p, r.actual.id, r.actual.primitive);
    if ((segment.path == Path::SunOpaque && actual_selected && r.pane.id == WP_NONE) ||
        (r.skipped.id == WP_NONE && r.actual.id != WP_NONE && !actual_selected)) {
        return result;
    }
    result.geometry = r.pane.id == WP_NONE ? Geometry::NoSelectedCrossing :
                      r.actual.id == WP_NONE ? Geometry::ClearBeforeSkip :
                      r.skipped.id != WP_NONE ? Geometry::StillBlocked : Geometry::Opened;
    return result;
}
} // namespace Vulkan::WindowPathProbe
