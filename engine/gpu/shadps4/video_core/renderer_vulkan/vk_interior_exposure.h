// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

namespace Vulkan {
class CameraMotion;
class Instance;
class Scheduler;

/// bbport (r99_interior-exposure, r99b_interior-brightness): the meter of the interior exposure
/// lift (gpu/shim/bbport_interior_exposure.h has the rule and the knobs).
namespace InteriorExposure {

struct RoofEvidence {
    bool valid = false;
    u64 read_ms = 0, lift_ms = 0, observed_ms = 0;
    float far_raw = 0, far_eased = 0, open_raw = 0, open_eased = 0;
    float meter = 0, target = 0, indoor = 0, wanted = 0, applied = 0;
};
// t132e read-only telemetry. Times use the same steady clock as the query samples.
[[nodiscard]] bool RoofEvidenceWanted();
[[nodiscard]] RoofEvidence ReadRoofEvidence();

/// Called by TemporalUpscaler::Run with the frame's camera (its projection turns depth into view
/// depth for the open share), HDR scene colour (`color`: rgba16f, GENERAL, storage) and depth
/// (`depth`: GENERAL, sampled) of w x h render pixels, before the upscaler reads them. Reads the
/// newest earlier reading the GPU has finished, eases the open share and the lift and stores the
/// lift's factor (BbInteriorExposure::Scale), then records this frame's meter dispatch. With
/// the setting graphics_interior_brightness at 0 and BB_INTERIOR_EXPOSURE not 1 or 2 (the setting
/// and the environment are resolved at every call) it returns at once: nothing is recorded or read;
/// a lift it had applied goes back to none, once (BbInteriorExposure::Resolve, r99c).
void Meter(const Instance& instance, Scheduler& scheduler, const CameraMotion& camera,
           vk::ImageView color, vk::ImageView depth, u32 w, u32 h);

} // namespace InteriorExposure
} // namespace Vulkan
