// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "rt_lamp_pane_probe.h"
#include "window_path_probe.h"

namespace Vulkan::WindowPathProbe {

struct PaneRead {
    Stamp capture, sample;
    DrawKey draw;
    U64 owner = 0;
    U32 vertices_per_instance = 0, instances = 0;
    std::span<const float> world;
    std::span<const U32> expanded_indices;
    RtLampPane::Camera camera;
    RtLampPane::Sample pixel;
    float raw_depth = 0;
    bool final_gbuffer_owner = false;
    bool triangle_list = false;
};

inline constexpr U32 PaneVerticesMost = 4096;

template <class Unproject>
Status SamplePanePrimitive(const PaneRead& read, const GlassRegistryRules::Table& table,
                           Unproject unproject, Witness& out) {
    out = {};
    if (!read.capture.request || !read.capture.frame || !read.capture.camera ||
        !read.capture.depth_uid || read.capture != read.sample) {
        return Status::Stale;
    }
    if (!ExactRegistry(table, read.draw)) {
        return Status::Registry;
    }
    if (!read.owner || !read.triangle_list ||
        !read.vertices_per_instance || !read.instances || read.draw.count % 3) {
        return Status::PaneProvenance;
    }
    const U64 vertices = U64(read.vertices_per_instance) * read.instances;
    const U64 expanded = U64(read.draw.count) * read.instances;
    if (vertices > PaneVerticesMost || expanded / 3 > WP_TRI_WORDS * 32 ||
        read.world.size() != vertices * 4 || read.expanded_indices.size() != expanded) {
        return Status::Budget;
    }
    const RtGlassTri::Mesh mesh{read.world.data(), U32(vertices), read.expanded_indices.data(), U32(expanded / 3)};
    for (U32 i = 0; i < mesh.triangles; ++i) {
        if (!RtGlassTri::Usable(mesh, i)) {
            return Status::PaneProvenance;
        }
    }
    const auto depth = RtLampPane::ReadDepth(read.raw_depth, read.camera, read.pixel, unproject);
    const auto hit = RtLampPane::PickExpanded(mesh, read.vertices_per_instance, read.instances,
                                               read.camera, read.pixel, depth);
    if (hit.consistent != 1) {
        return Status::PaneProvenance;
    }
    Witness witness{.triangle = {.primitive = hit.expanded}, .tolerance = depth.tolerance,
                    .camera_primitive = hit.expanded};
    for (U32 corner = 0; corner < 3; ++corner) {
        const auto point = RtGlassTri::At(mesh, mesh.indices[hit.expanded * 3 + corner]);
        witness.triangle.corners[corner] = {point.x, point.y, point.z};
    }
    float view_z = 0;
    if (!unproject(read.camera.inverse.data(), read.camera.proj.data(), read.raw_depth,
                   2 * read.pixel.picture_x / RtGlassFind::PictureWidth - 1,
                   2 * read.pixel.picture_y / RtGlassFind::PictureHeight - 1,
                   witness.depth_point.data(), &view_z) ||
        !Contains(witness.triangle, witness.depth_point, witness.tolerance)) {
        return Status::PaneProvenance;
    }
    out = witness;
    return Status::Ready;
}

template <class Unproject>
Status WitnessPane(const PaneRead& read, const GlassRegistryRules::Table& table,
                   Unproject unproject, Witness& out) {
    if (!read.final_gbuffer_owner) {
        out = {};
        return Status::PaneProvenance;
    }
    if (!read.capture.Valid()) {
        out = {};
        return Status::Stale;
    }
    return SamplePanePrimitive(read, table, unproject, out);
}

} // namespace Vulkan::WindowPathProbe

