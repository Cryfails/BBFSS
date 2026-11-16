// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62_leaf-stage3): the card alpha layers and the card debug view (BB_RT_CARD_ALPHA=2;
// docs/rt_card_alpha.md, "Stage 3"). The pure parts are in rt_card_layers.h.
//
// A cut-out draw's card (CardDraw, EffectsCaptureDraw) is given a layer of one R8 2D array: the
// draw's alpha texture, the image this draw's own texture binding found (Rasterizer's
// DrawContext::card_bound, from either binding path), is copied into it by the GPU (RecordFills,
// from RtShadow::PrepareCapture: before any reader of the scene) through the game's own image
// view. RtShadow writes the card's row (the pool offset, the layer, the rule) and gives the TLAS
// instance its card slot as custom index. The debug view (BB_RT_CARD_ALPHA_VIEW) traces the
// camera's rays through that chain and compares each card candidate's decision with what the
// game drew. Nothing of a shadow reads any of it yet (stage 4). With the knob unset or 1 the
// rasterizer makes no CardAlpha (Wanted) and no draw calls in.
#pragma once

#include <array>
#include <atomic>

#include "common/types.h"
#include "video_core/renderer_vulkan/rt_card_layers.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image_view.h"
#include "video_core/texture_cache/types.h"

namespace AmdGpu {
struct Image;
}
namespace Shader {
struct ImageResource;
}
namespace VideoCore {
class TextureCache;
struct Image;
} // namespace VideoCore

namespace Vulkan {

class CameraMotion;
class Instance;
class RtShadow;
class Runtime;
class SceneTargets;
class Scheduler;

/// The CUT1 cache parts (vk_pipeline_serialization.cpp): discarding pixel shaders the warm-up
/// took with their cut-out record, and those it left to compile in play (no part, or the log
/// knob wants the IR). Printed with the 600-frame line.
struct CardCacheCounts {
    u64 loaded = 0;
    u64 refused = 0;
};
CardCacheCounts CardCacheTally();
void NoteCardCutoutLoaded();
void NoteCardCutoutRefused();

class CardAlpha {
public:
    /// BB_RT_CARD_ALPHA=2 (both knobs are read once, here or at the first call): the rasterizer
    /// makes a CardAlpha only then. Otherwise a view knob that is set is said off, once.
    [[nodiscard]] static bool Wanted();
    CardAlpha(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
              Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion,
              RtShadow& rt_shadow);
    ~CardAlpha();
    CardAlpha(const CardAlpha&) = delete;
    CardAlpha& operator=(const CardAlpha&) = delete;

    /// BB_RT_CARD_ALPHA=2 and the layers were made.
    [[nodiscard]] bool On() const noexcept {
        return made;
    }
    /// And BB_RT_CARD_ALPHA_VIEW names a mode.
    [[nodiscard]] bool ViewOn() const noexcept {
        return made && view_mode != 0;
    }
    /// A cut-out draw's card (valid) and the image its binding of the alpha texture found
    /// (`image`, `uid`): the card's layer + 1 and the layer's generation into card.layer and
    /// card.layer_gen (0: none, counted why). Render thread, after BindResources.
    void NoteDraw(CardDraw& card, const AmdGpu::Image& sharp, const Shader::ImageResource& res,
                  VideoCore::ImageId image, u64 uid);
    /// The draw's binding of the alpha texture is not known (no image found, or the binding
    /// record is another stage's): no layer.
    void NoteNoSource(CardDraw& card);
    /// The upscaler is off: the view has no place in the frame (EffectsBeforeUpscaler). Said
    /// once when the view knob is set.
    void NoSceneHooks();
    /// The fills asked for, up to CardFillsPerFrame a frame, and the layer info when it changed
    /// (RtShadow::PrepareCapture, outside rendering).
    void RecordFills();
    /// The debug view over the scene colour before the upscaler (EffectsBeforeUpscaler).
    void View(VideoCore::ImageId color, VideoCore::ImageId depth, std::array<float, 2> jitter);
    void OnFrameEnd();

    /// What a reader of the layers binds (stage 4: rt_cards.glsl's CARD_BINDING_ALPHA and
    /// CARD_BINDING_LAYER_INFO). The sampler reads every level (linear between them): a lamp ray
    /// asks level 0, the view the game's mip, stage 6 levels 1 and 2.
    struct Bindings {
        vk::ImageView layers;
        vk::Sampler sampler;
        vk::Buffer info;
    };
    [[nodiscard]] Bindings ReaderBindings() const noexcept {
        return {*layers_view, *layer_sampler, info_buffer.buffer};
    }

private:
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    bool Make();
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    /// What a fill did: recorded; not yet (the image holds CPU writes not uploaded: the next
    /// draw that binds it uploads them and asks again); gone (the image is not registered).
    enum class FillResult { Recorded, NotYet, Gone };
    FillResult Fill(u32 layer);
    bool MakeView();
    vk::ImageView CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect);
    void Miss(CardDraw& card, CardLayerMiss why);

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;
    RtShadow& rt_shadow;

    u32 level = 0;     ///< BB_RT_CARD_ALPHA, read once (Shader::Optimization::CardAlphaLevel)
    u32 view_mode = 0; ///< BB_RT_CARD_ALPHA_VIEW, read once
    bool made = false;
    bool view_failed = false;
    u64 frame = 2; ///< CardLayerTable wants "this frame and the last" to be > 0
    u64 fills_frame = 0;
    u32 fills_left = 0;
    bool info_dirty = true;

    CardLayerTable table;
    /// The view a layer's fill samples: the game's view of the texture (ImageViewInfo of the
    /// draw's T# and resource), taken when the layer is queued.
    std::array<VideoCore::ImageViewInfo, CardLayerCount> fill_view{};

    vk::Image layers_image{};
    VmaAllocation layers_allocation{};
    vk::UniqueImageView layers_view;
    std::array<vk::UniqueImageView, CardLayerMips> level_views;
    vk::UniqueSampler layer_sampler;  ///< linear, clamp to edge, every level (readers)
    vk::UniqueSampler source_sampler; ///< linear, linear between levels (the fill's source)
    vk::UniqueSampler depth_sampler;
    Buffer info_buffer;
    vk::UniqueDescriptorSetLayout fill_set;
    vk::UniquePipelineLayout fill_layout;
    vk::UniquePipeline fill_pipeline;

    // The debug view: its pass, its counters (CARD_VIEW_COUNTERS uints, copied to the readback
    // every CardViewLineFrames frames with a view), and the views of the scene's images.
    vk::UniqueDescriptorSetLayout view_set;
    vk::UniquePipelineLayout view_layout;
    vk::UniquePipeline view_pipeline;
    Buffer view_counters, view_readback;
    u32 view_frames = 0;
    u32 view_copied_frames = 0; ///< the view frames the copy in flight sums
    u64 view_readback_tick = 0;
    bool view_readback_pending = false;
    bool view_said_no_hooks = false;
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    std::array<ViewEntry, 4> view_cache{};
    u64 view_uses = 0;

    struct Stats {
        u64 draws = 0, given = 0, taken = 0, fills = 0, refills = 0, failed_fills = 0;
        u64 dirty_waits = 0; ///< fills put off: the image held CPU writes not uploaded
        u64 dropped = 0;     ///< READY layers whose key another image now answers
        u64 views = 0, view_skipped = 0;
        std::array<u64, std::size_t(CardLayerMiss::Count)> miss{};
    } stats;
    u32 line_frames = 0;
};

} // namespace Vulkan
