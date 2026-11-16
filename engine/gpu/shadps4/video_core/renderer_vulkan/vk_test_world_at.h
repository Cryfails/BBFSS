// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r120_test-camera-lookat, TOOL; test-tools branch only): BB_TEST_WORLD_AT, a live test knob ("x,y;x,y": pixels of a
// 1920x1080 picture; in a slot job write x/y;x/y, the runner splits its actions at commas). Each time its text changes, the depth
// buffer's texel under each listed pixel is copied into a small host buffer by one transfer (nothing is written to any image) and,
// once the GPU is past the copy, the world position under it is worked out from the depth and the camera of the frame's last
// G-buffer pass (BbTestCamera::WorldFromDepth: the projection's z scale and offset, the inverse view) and logged:
//   GLINT-PROOF world at (r120): pixel 1395,624 of 1920x1080 (texel ... of ...): depth ..., ... m in front of the camera, world x y z
// BB_TEST_CAMERA=lookat:centre asks for the same read at the picture's middle and four pixels around it and takes the middle's
// world point as its target (bbport_test_camera_run.h has the mailbox). The mesh under a pixel is NOT given: the engine's pick
// (BB_GLASS_PICK) needs occlusion queries on the draws, not a copy.
//
// Where: Rasterizer::EffectsBeforeUpscaler, at the upscaler's trigger dispatch (the scene's depth is complete; CameraMotion::Depth()),
// once per read; the result is printed at a frame end (EffectsOnFrameEnd) when the GPU is past it, nothing waits. Made at the
// first wanted read and kept: a pipeline-free class (no shader, no image), one small host buffer per read.
// Off (BB_TEST_WORLD_AT unset and no lookat:centre): the rasterizer makes nothing; the hook is one relaxed load of a false flag a
// frame. Cost on: one 4-byte-per-pixel transfer of up to 13 texels per read; no GPU time worth measuring.
#pragma once

#include <memory>

#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class Instance;
class Runtime;
class SceneTargets;
class Scheduler;

class TestWorldAt {
public:
    TestWorldAt(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache, Runtime& runtime,
                SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~TestWorldAt();
    TestWorldAt(const TestWorldAt&) = delete;
    TestWorldAt& operator=(const TestWorldAt&) = delete;

    /// The upscaler's trigger (once a frame): starts the read that is wanted, if one is and none is on its way.
    void OnScene(VideoCore::ImageId depth, u64 frame);
    /// Each frame end: prints the lines of a read the GPU is past.
    void OnFrameEnd();

private:
    struct Job;

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;
    std::unique_ptr<Job> job;
};

} // namespace Vulkan
