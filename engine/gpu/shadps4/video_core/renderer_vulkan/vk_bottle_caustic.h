// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <memory>
#include "common/types.h"

#include "video_core/renderer_vulkan/lamp_fog_lights.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include <vk_mem_alloc.h>
#include "video_core/texture_cache/image.h"
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
#include "video_core/renderer_vulkan/vk_bottle_cut_source.h"
#endif

namespace VideoCore {
class Image;
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class Instance;
class PointShadow;
class RtShadow;
class Runtime;
class SceneTargets;
class Scheduler;
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
namespace BottleRawApply180 { class Receipt; }
#endif

namespace BottleCaustic {
bool On();
bool LogNow();
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
// Only call this in place of the ordinary On() read. A null pass still short-circuits.
CutSource::MasterRead ReadCutMaster();
CutSource::MasterRead LatestCutMaster();
CutSource::Backing ObserveCutBacking(const SceneTargets&, VideoCore::ImageId,
                                     const VideoCore::Image&, vk::ImageView,
                                     vk::PipelineStageFlags2, vk::AccessFlags2);
#endif

class Pass {
public:
    Pass(const Instance&, Scheduler&, VideoCore::TextureCache&, Runtime&, SceneTargets&,
         CameraMotion&, PointShadow&, RtShadow&);
    ~Pass();

    void OnTargets(VideoCore::ImageId depth, VideoCore::ImageId normal, VideoCore::ImageId albedo);
    bool Capturing(VideoCore::ImageId depth) const noexcept;
    void AddLights(const u32* records, u32 count) { lamps.Add(records, count); }
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    void Apply(VideoCore::ImageId color, VideoCore::ImageId depth, std::array<float, 2> jitter,
               CutSource::Opportunity* cut_opportunity = nullptr
#if defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
               , std::shared_ptr<BottleRawApply180::Receipt> raw_phase = {}
#endif
               );
#else
    void Apply(VideoCore::ImageId color, VideoCore::ImageId depth, std::array<float, 2> jitter);
#endif

private:
    struct MotionProof;
    std::array<std::shared_ptr<MotionProof>,2> motion_slots;
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    struct CutProof;
    std::array<std::shared_ptr<CutProof>, 2> cut_slots;
#endif
    bool Make();
    vk::ImageView View(const VideoCore::Image&, vk::ImageAspectFlagBits);

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& textures;
    Runtime& runtime;
    SceneTargets& targets;
    CameraMotion& camera;
    PointShadow& point_shadow;
    RtShadow& rt;
    struct CachedView {
        vk::Image image{};
        u64 uid = 0;
        vk::ImageAspectFlagBits aspect{};
        vk::ImageView view{};
        u64 use = 0;
    };
    std::array<CachedView, 8> views{};
    u64 uses = 0;
    u64 captured_frame = ~u64{0};
    vk::UniqueDescriptorSetLayout descriptors;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    vk::Buffer data{};
    VmaAllocation allocation{};
    std::array<VideoCore::ImageId, 3> captured{};
    std::array<u64, 3> uids{};
    LampFog::FrameLights lamps;
    bool armed = false;
    bool failed = false;
    bool told = false;
};
} // namespace BottleCaustic
} // namespace Vulkan
