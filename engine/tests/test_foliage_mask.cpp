// SPDX-License-Identifier: GPL-3.0-or-later
#include <cassert>
#include <cstdio>

#include "video_core/renderer_vulkan/foliage_mask.h"

using namespace Vulkan::FoliageMaskRules;

int main() {
    Slot6 slot{.has_fragment = true};
    assert(slot.Available()); // inactive guest binding is deliberately absent from the veto
    for (bool Slot6::* bit : {&Slot6::guest_export, &Slot6::guest_store, &Slot6::guest_shader_channels,
                              &Slot6::host_location, &Slot6::host_write, &Slot6::host_samples,
                              &Slot6::prepared_guest, &Slot6::dual_source}) {
        slot.*bit = true;
        assert(!slot.Available());
        slot.*bit = false;
    }
    assert(!Slot6{}.Available());
    assert(SupportedLimits(132, 132, 7, 7, true));
    assert(!SupportedLimits(128, 132, 7, 7, true));
    assert(!SupportedLimits(132, 132, 6, 7, true));
    assert(!SupportedLimits(132, 132, 7, 7, false));

    Epoch epoch;
    EpochKey key{1, 5, 8, {1, 1, 0}, {2, 6, 0}, {3, 9, 0}, 1920, 1080};
    assert(epoch.Begin(key) && !epoch.Readable(key));
    epoch.NoteTag();
    assert(epoch.Readable(key));
    auto stale = key;
    ++stale.normal.generation;
    assert(!epoch.Readable(stale));
    epoch.Refuse(Refusal::Slot6);
    epoch.Refuse(Refusal::Writer);
    assert(epoch.Reason() == Refusal::Slot6);
    assert(!epoch.Readable(key) && !epoch.Begin(key));
    ++key.serial;
    assert(epoch.Begin(key) && !epoch.Readable(key));

    Draw draw{
        .vs = 0x3eaa5555, .ps = 0xdbeccd9c, .permutation = 1, .capture = 1,
        .vertex_address = 100, .index_address = 101, .vertex_generation = 1, .index_generation = 1,
        .vertex_size = 2648884, .uv_hash = 2, .constants_hash = 3, .index_count = 45150,
        .instance_count = 1, .stride = 28, .primitive = 4,
        .textures = {{{.image = {9, 1, 0}}, {.image = {10, 1, 0}}}},
        .camera_gbuffer = true, .direct_indexed = true, .resolved_cutout = true,
        .complete_textures = true,
    };
    Diagnostic diagnostic;
    assert(diagnostic.ClassifyDraw(draw, 0, 10) == Class::Unknown);
    assert(!diagnostic.Authorize(draw, false, 0, 10));
    assert(!diagnostic.Authorize(draw, true, 1, 10));
    assert(diagnostic.Authorize(draw, true, 0, 10));
    assert(diagnostic.ClassifyDraw(draw, 0, 10) == Class::GrassDiagnostic);
    auto other = draw;
    other.first_index = 123;
    assert(diagnostic.ClassifyDraw(other, 0, 10) == Class::Unknown);
    other = draw;
    other.camera_gbuffer = false;
    assert(diagnostic.ClassifyDraw(other, 0, 10) == Class::Other);
    other = draw;
    ++other.textures[1].image.generation;
    assert(diagnostic.ClassifyDraw(other, 0, 10) == Class::Unknown);
    assert(diagnostic.ClassifyDraw(draw, 0, 10) == Class::Unknown);
    assert(!diagnostic.Authorize(draw, true, 0, 10));
    ++draw.capture;
    assert(diagnostic.Authorize(draw, true, 0, 10));
    assert(diagnostic.ClassifyDraw(draw, 0, 15) == Class::Unknown);
    assert(!diagnostic.Authorize(draw, true, 0, 15));
    std::puts("foliage mask rules: pass");
}
