// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <cstdint>
#include <limits>

namespace Vulkan::WindowPathProbe {

struct PaneStages {
    using U32 = std::uint32_t;
    using U64 = std::uint64_t;

    enum Guard : U32 {
        Range = 1u << 0, CameraPass = 1u << 1, CaptureHookOff = 1u << 2,
        RtUnwanted = 1u << 3, NoMotionGeometry = 1u << 4,
        Registry = 1u << 5, NotIndexed = 1u << 6, NotSolid = 1u << 7,
        Alpha = 1u << 8, Skinned = 1u << 9, Restart = 1u << 10, Strip = 1u << 11,
        NoIndices = 1u << 12, DepthImage = 1u << 13, InvalidCamera = 1u << 14,
        Scissored = 1u << 15, Reduced = 1u << 16, Extent = 1u << 17,
        NoConstants = 1u << 18, View = 1u << 19, Projection = 1u << 20,
        TargetTransform = 1u << 21, Jitter = 1u << 22, Duplicate = 1u << 23,
    };
    enum Entry : U32 { Built = 1, Dynamic = 2, Rebuilt = 4, Blas = 8 };

    U64 arm_frame = 0, arm_rt = 0, sample_rt = 0, entry = 0, base = 0;
    U64 first_frame = 0, first_rt = 0;
    U32 exact_before = 0, exact_after = 0, hook = 0, observed = 0, prepare = 0;
    U32 ordinary_needs = 0, ordinary_reuse = 0, build_added = 0, matching_build = 0;
    U32 build_left_out = 0, probe_only = 0, span_ok = 0, queued = 0;
    U32 guard = 0, motion = 0, geometry = 0, entry_flags = 0, param = 0, build = 0;
    const char* first_refusal = nullptr;
    const char* first_prepare = nullptr;
    const char* sample = "none";
    const char* finish = "unknown";

    static void Count(U32& value) {
        if (value != std::numeric_limits<U32>::max()) {
            ++value;
        }
    }
    void Refuse(const char* why, U64 frame, U64 rt) {
        if (!first_refusal) {
            first_refusal = why;
            first_frame = frame;
            first_rt = rt;
        }
    }
    void PrepareResult(const char* why) {
        if (!first_prepare) {
            first_prepare = why;
        }
    }
};

} // namespace Vulkan::WindowPathProbe

