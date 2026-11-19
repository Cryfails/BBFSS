// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <charconv>
#include <limits>
#include <string_view>

#include "rt_glass_tri.h"

namespace Vulkan::RtLampPane {
using U32 = std::uint32_t;
using U64 = std::uint64_t;
inline constexpr U32 Instances = 3, DrawIndices = 25296;
inline constexpr U32 MaxVertices = 16384, MaxTriangles = DrawIndices;
inline constexpr U64 FrameBudget = 120;

struct Request {
    U32 id = 0, width = 0, height = 0;
    std::array<RtGlassTri::Pixel, 2> pixels{};
};

inline bool Parse(std::string_view text, Request& out) {
    std::array<U32, 7> fields{};
    for (std::size_t i = 0; i < fields.size(); ++i) {
        const auto slash = text.find('/');
        const auto word = text.substr(0, slash);
        if (word.empty() || ((slash != text.npos) != (i + 1 < fields.size()))) {
            return false;
        }
        const auto [end, error] = std::from_chars(word.data(), word.data() + word.size(), fields[i]);
        if (error != std::errc{} || end != word.data() + word.size()) {
            return false;
        }
        if (slash != text.npos) {
            text.remove_prefix(slash + 1);
        }
    }
    const auto [id, w, h, px, py, mx, my] = fields;
    if (!id || !w || !h || w > 8192 || h > 8192 || px >= w || mx >= w || py >= h || my >= h ||
        (px == mx && py == my)) {
        return false;
    }
    out = {id, w, h, {{{int(px), int(py)}, {int(mx), int(my)}}}};
    return true;
}

inline bool Target(U64 vs, U64 ps, U32 indices, U32 instances) {
    return vs == 0x6a833138 && ps == 0xbb10e440 && indices == DrawIndices &&
           instances == Instances;
}

inline bool MeshSize(U32 vertices, U32 triangles, U32 instances) {
    return instances == Instances && vertices != 0 && vertices <= MaxVertices &&
           triangles != 0 && triangles % Instances == 0 &&
           triangles / Instances <= MaxTriangles;
}

struct Identity {
    U32 request = 0, draw = 0, build = 0, image = 0;
    U64 scene = 0, rt = 0, uid = 0;

    bool operator==(const Identity&) const = default;
};

inline bool SameDepth(const Identity& capture, U32 request, U64 scene, U32 image, U64 uid) {
    return capture.request == request && capture.scene == scene && capture.image == image &&
           capture.uid == uid && uid != 0 && capture.draw != 0 && capture.build != 0;
}

inline constexpr U32 MaterialTargets = 4, MaterialPixels = 2, MaterialTexelBytes = 4;
inline constexpr U32 FinalDepthBytes = MaterialPixels * MaterialTexelBytes;
inline constexpr U32 MaterialBytes = 2 * MaterialTargets * MaterialPixels * MaterialTexelBytes;

enum class MaterialPhase : U32 { Before, After };

constexpr U32 MaterialOffset(MaterialPhase phase, U32 target, U32 pixel) {
    return FinalDepthBytes +
           ((U32(phase) * MaterialTargets + target) * MaterialPixels + pixel) * MaterialTexelBytes;
}
static_assert(MaterialBytes == 64 && MaterialOffset(MaterialPhase::Before, 0, 0) == 8);
static_assert(MaterialOffset(MaterialPhase::After, 3, 1) + MaterialTexelBytes ==
              FinalDepthBytes + MaterialBytes);

struct MaterialPhases {
    Identity draw;
    U64 before_tick = 0, after_tick = 0;

    bool MayRecord(MaterialPhase phase, const Identity& current) const {
        if (!current.request || !current.draw || !current.build || !current.uid || after_tick) {
            return false;
        }
        return phase == MaterialPhase::Before ? before_tick == 0 : before_tick != 0 && draw == current;
    }

    bool Record(MaterialPhase phase, const Identity& current, U64 tick) {
        if (!tick || !MayRecord(phase, current)) {
            return false;
        }
        if (phase == MaterialPhase::Before) {
            draw = current;
            before_tick = tick;
        } else {
            after_tick = tick;
        }
        return true;
    }

    bool Complete(const Identity& current) const {
        return before_tick != 0 && after_tick != 0 && draw == current;
    }

    template <typename Ready>
    bool Retired(Ready ready) const {
        return (!before_tick || ready(before_tick)) && (!after_tick || ready(after_tick));
    }
};

struct MaterialBacking {
    U64 image = 0, backing = 0, begin = 0, end = 0, stencil_begin = 0, stencil_end = 0;
    U32 id = 0;
    U64 uid = 0;

    bool operator==(const MaterialBacking&) const = default;
};

inline bool MaterialAlias(const MaterialBacking& a, const MaterialBacking& b) {
    const auto overlap = [](U64 begin, U64 end, U64 other_begin, U64 other_end) {
        return begin < end && other_begin < other_end && begin < other_end && other_begin < end;
    };
    return a.image == b.image || a.backing == b.backing ||
           overlap(a.begin, a.end, b.begin, b.end) ||
           overlap(a.stencil_begin, a.stencil_end, b.begin, b.end) ||
           overlap(a.begin, a.end, b.stencil_begin, b.stencil_end) ||
           overlap(a.stencil_begin, a.stencil_end, b.stencil_begin, b.stencil_end);
}

inline constexpr bool MaterialWrites(U32 target, U32 mask) {
    const U32 required = target == 0 ? 1u : 7u;
    return (mask & required) == required;
}

inline constexpr U32 MaterialChanged(const std::array<std::uint8_t, 4>& before,
                                     const std::array<std::uint8_t, 4>& after) {
    U32 mask = 0;
    for (U32 c = 0; c < before.size(); ++c) {
        mask |= (before[c] != after[c] ? 1u : 0u) << c;
    }
    return mask;
}

// Clears can discard the captured target. Once sampled, later writes can stale the copy.
inline bool RefuseDepthWrite(bool cleared, bool wrote_depth, bool copied) {
    return cleared || (wrote_depth && copied);
}

struct Camera {
    std::array<float, 12> view{}, inverse{};
    std::array<float, 4> proj{};

    bool operator==(const Camera&) const = default;
};

struct Sample {
    U32 x = 0, y = 0;
    float picture_x = 0, picture_y = 0;
};

// The viewport signs are already in CameraMotion's projection. Remove only the raster jitter
// from the sampled texel centre before converting to the projection helper's picture units.
inline Sample Texel(const Request& request, const RtGlassTri::Pixel& pixel, U32 width,
                    U32 height, const std::array<float, 2>& jitter) {
    const auto x = U32((U64(pixel.x) * 2 + 1) * width / (U64(request.width) * 2));
    const auto y = U32((U64(pixel.y) * 2 + 1) * height / (U64(request.height) * 2));
    return {x, y, (float(x) + 0.5f - jitter[0]) * RtGlassFind::PictureWidth / float(width),
                  (float(y) + 0.5f - jitter[1]) * RtGlassFind::PictureHeight / float(height)};
}

struct Depth {
    float metres = 0, tolerance = 0;
    const char* refusal = nullptr;
};

template <class Unproject>
Depth ReadDepth(float raw, const Camera& camera, const Sample& pixel, Unproject unproject) {
    const auto view_depth = [&](float value, float& metres) {
        float world[3]{};
        return unproject(camera.inverse.data(), camera.proj.data(), value,
                         2 * pixel.picture_x / RtGlassFind::PictureWidth - 1,
                         2 * pixel.picture_y / RtGlassFind::PictureHeight - 1, world, &metres);
    };
    Depth depth;
    if (!(raw > 0 && raw < 1) || !view_depth(raw, depth.metres)) {
        depth.refusal = "invalid depth or view projection";
        return depth;
    }
    float lower = raw, upper = raw;
    for (int i = 0; i < 4; ++i) {
        lower = std::nextafter(lower, 0.0f);
        upper = std::nextafter(upper, 1.0f);
    }
    float a = 0, b = 0;
    if (!view_depth(lower, a) || !view_depth(upper, b)) {
        depth.refusal = "insufficient D32 precision";
        return depth;
    }
    depth.tolerance = 0.002f + std::max(std::abs(a - depth.metres), std::abs(b - depth.metres));
    if (depth.tolerance > 0.01f) {
        depth.refusal = "insufficient D32 precision";
    }
    return depth;
}

inline bool MeshValid(const RtGlassTri::Mesh& mesh, U32 vertices) {
    if (!mesh.indices || !mesh.world || !MeshSize(vertices, mesh.triangles, Instances) ||
        mesh.vertices != vertices * Instances) {
        return false;
    }
    const U32 per_instance = mesh.triangles / Instances;
    for (U32 t = 0; t < mesh.triangles; ++t) {
        for (U32 k = 0; k < 3; ++k) {
            const U32 index = mesh.indices[std::size_t(t) * 3 + k];
            if (index / vertices != t / per_instance) {
                return false;
            }
            const auto p = RtGlassTri::At(mesh, index);
            if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z)) {
                return false;
            }
        }
    }
    return true;
}

struct Hit {
    U32 inside = 0, consistent = 0, expanded = 0, instance = 0, local = 0;
    float predicted = 0, residual = std::numeric_limits<float>::infinity();
};

// Use the same projection and reciprocal depth interpolation as FindTriangleAt. Count all
// strictly interior depth matches across the expanded instance slices, with no edge fallback.
// Callers impose their own capture size limits before passing the readback.
inline Hit PickExpanded(const RtGlassTri::Mesh& mesh, U32 vertices, U32 instances,
                        const Camera& camera, const Sample& pixel, const Depth& depth) {
    Hit hit;
    if (depth.refusal || !vertices || !instances || mesh.vertices != U64(vertices) * instances ||
        !mesh.triangles || mesh.triangles % instances || !mesh.indices || !mesh.world) {
        return hit;
    }
    const U32 per_instance = mesh.triangles / instances;
    for (U32 triangle = 0; triangle < mesh.triangles; ++triangle) {
        const U32 instance = triangle / per_instance;
        std::array<RtGlassFind::ScreenPoint, 3> screen{};
        std::array<float, 3> view_depth{};
        bool valid = true;
        for (U32 corner = 0; corner < 3; ++corner) {
            const U32 index = mesh.indices[std::size_t(triangle) * 3 + corner];
            if (index / vertices != instance) {
                valid = false;
                break;
            }
            const auto p = RtGlassTri::At(mesh, index);
            const auto& view = camera.view;
            view_depth[corner] = view[8] * p.x + view[9] * p.y + view[10] * p.z + view[11];
            screen[corner] = RtGlassFind::ProjectToPicture(view, camera.proj, p.x, p.y, p.z);
            const float projected_depth = camera.proj[2] + camera.proj[3] / view_depth[corner];
            valid &= std::isfinite(view_depth[corner]) && view_depth[corner] > 0.05f &&
                     screen[corner].front && std::isfinite(screen[corner].x) &&
                     std::isfinite(screen[corner].y) && projected_depth >= 0 && projected_depth <= 1;
        }
        if (!valid) {
            continue;
        }
        const auto [a, b, c] = screen;
        const float bx = b.x - a.x, by = b.y - a.y;
        const float cx = c.x - a.x, cy = c.y - a.y;
        const float determinant = bx * cy - by * cx;
        if (!std::isfinite(determinant) || std::abs(determinant) < 1e-6f) {
            continue;
        }
        const float x = pixel.picture_x - a.x, y = pixel.picture_y - a.y;
        const float w1 = (x * cy - y * cx) / determinant;
        const float w2 = (bx * y - by * x) / determinant;
        const float w0 = 1 - w1 - w2;
        if (!(w0 > 1e-5f && w1 > 1e-5f && w2 > 1e-5f)) {
            continue;
        }
        const float predicted = 1 / (w0 / view_depth[0] + w1 / view_depth[1] + w2 / view_depth[2]);
        const float residual = std::abs(predicted - depth.metres);
        ++hit.inside;
        hit.consistent += residual <= depth.tolerance ? 1u : 0u;
        if (residual < hit.residual) {
            hit.expanded = triangle;
            hit.instance = instance;
            hit.local = triangle % per_instance;
            hit.predicted = predicted;
            hit.residual = residual;
        }
    }
    return hit;
}

inline Hit Pick(const RtGlassTri::Mesh& mesh, U32 vertices, const Camera& camera,
                const Sample& pixel, const Depth& depth) {
    if (!MeshSize(vertices, mesh.triangles, Instances)) {
        return {};
    }
    return PickExpanded(mesh, vertices, Instances, camera, pixel, depth);
}

inline const char* ValidatePair(const std::array<Hit, 2>& picks) {
    for (const auto& hit : picks) {
        if (hit.consistent == 0) {
            return "no depth-consistent inside triangle";
        }
        if (hit.consistent != 1) {
            return "ambiguous depth-consistent inside triangles";
        }
    }
    if (picks[0].instance != picks[1].instance || picks[0].local == picks[1].local) {
        return "metal control needs a different seed in the same instance";
    }
    return nullptr;
}

inline RtGlassTri::Panel Grow(const RtGlassTri::Mesh& mesh, U32 vertices, const Hit& pane) {
    const U32 triangles = mesh.triangles / Instances;
    const U32 base = pane.instance * vertices;
    const U32* indices = mesh.indices + std::size_t(pane.instance) * triangles * 3;
    std::vector<U32> local(std::size_t(triangles) * 3);
    std::transform(indices, indices + local.size(), local.begin(), [base](U32 index) {
        return index - base;
    });
    RtGlassTri::Rules rules;
    rules.longest_metres = 0;
    rules.narrowest_metres = 0;
    return RtGlassTri::Grow({mesh.world + std::size_t(base) * 4, vertices, local.data(),
                            triangles}, pane.local, rules);
}
} // namespace Vulkan::RtLampPane
