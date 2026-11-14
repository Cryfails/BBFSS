// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <array>
#include <memory>
#include <optional>
#include <functional>
#include <unordered_map>
#include <unordered_set>
#include <mutex>
#include <vector>
#include "video_core/renderer_vulkan/scene_proxy_release.h"
#include "video_core/renderer_vulkan/scene_resolution.h"
#include "video_core/texture_cache/image.h"

namespace VideoCore { class TextureCache; }
namespace Vulkan {
/// bbport: what asks for a proxied scene image, for the resolve/fill table (SceneTargets::NoteTrip,
/// every 600 frames with BB_SCENE_TRIPS=1, BB_FRAME_STATS=1 or BB_GPU_PROFILE=1). The innermost
/// scope on this thread names the consumer of a resolve, the user of a fill and the writer that
/// drops a proxy. `keep_proxy`: the access declares a write it cannot do (a depth attachment in a
/// read-only layout, no clear): the proxy stays current (experiment bit 1073741824: dropped).
struct SceneUse {
    const char* what = nullptr;
    u64 hash = 0;
    bool keep_proxy = false;
};
class SceneUseScope {
public:
    explicit SceneUseScope(const char* what, u64 hash = 0, bool keep_proxy = false)
        : prev{current} {
        current = {what, hash, keep_proxy};
    }
    ~SceneUseScope() {
        current = prev;
    }
    SceneUseScope(const SceneUseScope&) = delete;
    SceneUseScope& operator=(const SceneUseScope&) = delete;
    static inline thread_local SceneUse current{};

private:
    SceneUse prev;
};
class Instance;
class Runtime;
class Scheduler;

// Reduced raster targets, with native-size images retained for unmodified guest compute,
// integer texture loads, copies and CPU readbacks. All native access passes Runtime::Transit.
class SceneTargets {
public:
    SceneTargets(const Instance&, Scheduler&, Runtime&, VideoCore::TextureCache&);
    using Lookup = std::function<VideoCore::Image*(VideoCore::ImageId, u64)>;
    SceneTargets(const Instance&, Scheduler&, Runtime&, Lookup);
    ~SceneTargets();
    bool SetSize(SceneResolution::Size);
    SceneResolution::Size Size() const { return size; }
    bool Reduced() const { return size != SceneResolution::Native(); }
    /// A reduced proxy can stand in for the image: a 1920x1080 scene target or, scaled by
    /// the same factor, a half-resolution (960x540) one (toggle SceneHalfRes).
    bool Eligible(const VideoCore::Image&) const;
    /// Eligible at the full scene size (1920x1080): the upscaler's inputs, the scene start.
    bool EligibleScene(const VideoCore::Image&) const;
    /// The proxy size of an eligible image: the scene size divided like the native size.
    SceneResolution::Size ProxySize(const VideoCore::Image&, u32 level = 0) const;
    struct Target {
        vk::Image image;
        vk::ImageView view;
        vk::ImageLayout layout;
        vk::ImageUsageFlags usage;
    };
    /// bbport: `cleared`: the pass clears all of the proxy (load op clear; a reduced pass has the
    /// proxy's size), so a proxy a native write dropped needs no fill first (experiment bit
    /// 1073741824: filled as before).
    Target Attachment(VideoCore::ImageId, const VideoCore::ImageViewInfo&, bool cleared = false);
    Target Read(VideoCore::ImageId, const VideoCore::ImageViewInfo&,
                vk::PipelineStageFlags2 = vk::PipelineStageFlagBits2::eComputeShader,
                vk::AccessFlags2 = vk::AccessFlagBits2::eShaderRead);
    /// bbport (r22_barriers): Read() with its defaults (compute shader, shader read) for a caller
    /// whose last recorded command is a proxy barrier with the compute stage in its destination
    /// (the Read() of its target just before, nothing recorded between). While the proxy is in
    /// General and the destination of its last barrier covers this read with only reads declared
    /// since, no barrier is recorded (experiment 140737488355328 set: always, as Read()).
    Target ReadNext(VideoCore::ImageId, const VideoCore::ImageViewInfo&);
    void NativeAccess(VideoCore::Image&, vk::AccessFlags2,
                      vk::ImageLayout = vk::ImageLayout::eUndefined);
    /// The proxy of `image` for sampling when it holds the current content (else nullopt: the
    /// native image is current). Transitions only after other use (attachment, copy).
    /// Mipmapped targets have one proxy per level: views of one level only.
    std::optional<Target> SampleProxy(const VideoCore::Image& image,
                                      const VideoCore::ImageViewInfo& info);
    /// Whether SampleProxy would return the proxy of `image` for these levels.
    [[nodiscard]] bool ProxyCurrent(const VideoCore::Image& image, u32 level = 0,
                                    u32 levels = 1) const;
    /// SampleProxy for a view obtained before (valid while Generation() is unchanged): the
    /// layout to sample it in.
    vk::ImageLayout PrepareSample(const VideoCore::Image& image, u32 level = 0);
    /// Changes when proxies and their views are destroyed (SetSize).
    [[nodiscard]] u64 Generation() const noexcept {
        return generation;
    }
    /// Whether NativeAccess has work for this image (a reduced-size proxy exists).
    [[nodiscard]] bool Tracks(u64 image_uid) const {
        return !copying && tracked.contains(image_uid);
    }
    /// A proxy of the image holds writes its native image has not seen yet (NativeAccess would
    /// resolve them).
    [[nodiscard]] bool NativeStale(const VideoCore::Image& image) const;
    void ResolveAll();
    void Forget(u64 image_uid) {
        releases.Add(image_uid);
    }
    [[nodiscard]] std::size_t ProxyCount() const noexcept {
        return entries.size();
    }
    void DropForgotten();
    /// bbport: whether CopyDepthProxyToColor can write `dst` from the proxy of `depth`: reduced
    /// targets, a depth proxy holding writes its native image has not seen yet (the native
    /// image would be its nearest upscale), a 32-bit float depth format, `dst` a single-level
    /// R32F color image of the native size, and the pipeline. Creates the pipeline once.
    [[nodiscard]] bool CanCopyDepthProxyToColor(const VideoCore::Image& depth,
                                                const VideoCore::Image& dst);
    /// Writes the depth of that proxy into `dst` with a fullscreen draw (nearest upscale, the
    /// mapping of the resolve), without resolving the native depth image. `dst` ends as after
    /// Runtime::CopyImage: written through Runtime::Transit (layout, write_seq), GpuModified as
    /// the source, not Dirty. False (nothing recorded) when CanCopyDepthProxyToColor is false.
    bool CopyDepthProxyToColor(VideoCore::Image& depth, VideoCore::Image& dst);
    /// bbport: why a whole-image copy of `src` into `dst` cannot be done between their proxies
    /// at the reduced size (nullptr: it can). Needs reduced targets, single-level single-sample
    /// colour images of one format and size that both have a level-0 proxy, and a source proxy
    /// holding writes its native image has not seen (dirty: the native image would be its upscale).
    /// bbport (r10_proxy_copies): before a whole-image render-target copy of `src` into `dst`:
    /// when the source proxy is dirty and `dst` (eligible, same colour format and size, one
    /// level, layer and sample) has no proxy, creates its level-0 proxy without a fill (the copy
    /// overwrites all of it), so ProxyCopyBlocker passes and CopyProxy copies at the reduced
    /// size. Returns a reason the copy must stay native (experiment bit 34359738368 set and `dst`
    /// holds a proxy made here before), else nullptr. With the bit set no proxy is made.
    const char* ProxyForCopy(const VideoCore::Image& src, VideoCore::Image& dst,
                             VideoCore::ImageId dst_id);
    [[nodiscard]] const char* ProxyCopyBlocker(const VideoCore::Image& src,
                                               const VideoCore::Image& dst) const;
    /// Copies the proxy of `src` into the proxy of `dst` at the proxy size and marks it written
    /// (valid, dirty). Neither native image is touched; `dst` ends as after Runtime::CopyImage
    /// (write_seq counted, GpuModified as the source, not Dirty). False (nothing recorded) when
    /// ProxyCopyBlocker names a reason.
    bool CopyProxy(VideoCore::Image& src, VideoCore::Image& dst);
    /// The caller overwrites the whole native image next: its proxies drop their contents without
    /// being resolved first (a later proxy use fills them from the native image).
    void NativeOverwritten(const VideoCore::Image& image);
    /// bbport (r9_clear): Runtime::ClearImage is about to clear `levels` levels of the native
    /// image from `base_level`. Those levels' proxies drop their contents without the resolve the
    /// clear would overwrite. False: no proxy is involved, or experiment bit 17179869184 (the
    /// old way: resolve, clear, fill later).
    bool NativeClearBegin(const VideoCore::Image& image, u32 base_level, u32 levels);
    /// After the native clear is recorded: the same proxies are cleared to the same colour and
    /// are current again (valid, not dirty), so their next reduced use needs no fill.
    void NativeClearEnd(const VideoCore::Image& image, u32 base_level, u32 levels,
                        const vk::ClearColorValue& color);
    /// bbport (r11_depth_clear): a native pass is about to begin with `image` as its depth
    /// attachment and a clear in its load ops. `depth_clear`: the depth aspect is cleared;
    /// `depth_written`: the pass's draws may write depth (a clear through HTILE, not a DB clear);
    /// `stencil_clear`: the stencil aspect is cleared (a DB clear: its draws do not write it);
    /// `whole`: the render area and the view cover all of the image; `load_ops`: the scheduler
    /// begins a pass that runs them (not the open one, not a resumed one). When all of `image`
    /// ends as `value`, its level-0 proxy is cleared to `value` and is current (no fill at the
    /// next reduced use). Experiment bit 68719476736: nothing is done (the fill as before).
    void NativeDepthClear(const VideoCore::Image& image, bool depth_clear, bool depth_written,
                          bool stencil_clear, const vk::ClearDepthStencilValue& value,
                          bool whole, bool load_ops);
    /// Whether a resolve of `image` upscales linearly (else nearest), as Copy decides.
    [[nodiscard]] bool ResolvesLinear(const VideoCore::Image& image) const;
    bool debug = false; ///< BB_SCENE_DEBUG frame: print resolves and fills
    /// bbport (r9_clear): NativeAccess acts on these levels only. Set by NativeClearBegin for the
    /// Transit of Runtime::ClearImage, which puts it back: a clear of level 0 does not touch the
    /// other levels, so their proxies are neither resolved nor dropped for it.
    u32 native_level_begin = 0, native_level_end = 16;
private:
    struct Entry {
        VideoCore::ImageId source{};
        u64 uid = 0;
        u32 level = 0; ///< mip level of the native image this proxy stands for
        VideoCore::UniqueImage image;
        std::vector<std::pair<VideoCore::ImageViewInfo, vk::UniqueImageView>> views;
        vk::ImageLayout layout = vk::ImageLayout::eUndefined;
        SceneResolution::Coherence state;
        /// bbport: the native write that last dropped this proxy (SceneUse), for NoteTrip.
        const char* dropped_by = "first use of a new proxy";
        const char* dropped_how = "";
        u64 dropped_hash = 0;
        bool copy_made = false;   ///< bbport (r10_proxy_copies): created by ProxyForCopy
        bool copy_source = false; ///< copied into such a proxy, not drawn or resolved since
        bool r11_cleared = false; ///< bbport (r11_depth_clear): cleared with a native clear
        /// bbport (r22_barriers): the destination of the last barrier of this proxy (Transition,
        /// the only place its layout changes); empty before the first.
        vk::PipelineStageFlags2 r22_stages{};
        vk::AccessFlags2 r22_access{};
    };
    static constexpr u64 Key(u64 uid, u32 level) {
        return uid << 4 | level;
    }
    /// bbport: `use` names who needs the proxy (NoteTrip); `overwritten`: an invalid proxy is
    /// not filled (Fill).
    Entry& Get(VideoCore::ImageId, u32 level, const char* use, bool overwritten = false);
    vk::ImageView View(Entry&, const VideoCore::Image&, const VideoCore::ImageViewInfo&);
    void Copy(Entry&, VideoCore::Image&, bool to_native);
    void Fill(Entry&, VideoCore::Image&, const char* use, bool overwritten);
    // Depth/stencil formats without blit support (D32S8 on RADV) are resampled by a
    // fullscreen draw writing gl_FragDepth and, with stencil export, the stencil value.
    vk::FormatFeatureFlags Features(vk::Format) const;
    bool Blittable(vk::Format) const;
    bool ShaderResampled(const VideoCore::Image&) const;
    void Resample(vk::Image src, vk::Image dst, const VideoCore::Image& original,
                  vk::Extent2D dst_size);
    vk::Pipeline ResamplePipeline(vk::Format, bool stencil);
    void CreateResampleResources();
    vk::Pipeline DepthToColorPipeline();
    void Transition(Entry&, vk::ImageAspectFlags, vk::ImageLayout,
                    vk::PipelineStageFlags2, vk::AccessFlags2, bool discard = false);
    u32 clear_calls = 0, clear_proxies = 0, clear_resolves_saved = 0; ///< bbport (r9_clear)
    const Instance& instance;
    Scheduler& scheduler;
    Runtime& runtime;
    Lookup lookup;
    SceneResolution::Size size;
    std::unordered_map<u64, std::unique_ptr<Entry>> entries; ///< by Key(uid, level)
    std::unordered_set<u64> tracked; ///< uids with proxies
    ProxyReleases releases;
    u64 released_proxies = 0, released_bytes = 0, release_report_proxies = 0;
    bool copying = false;
    /// bbport (r22_barriers): the caller the next Transition serves, set only while experiment
    /// 140737488355328 is clear (R22None: its own barrier call, as before).
    enum R22Site : u32 { R22None, R22Copy, R22Pair, R22EffectRead };
    u32 r22_site = R22None;
    bool r22_read_next = false;              ///< ReadNext: the next Read follows a proxy barrier
    vk::PipelineStageFlags2 r22_last_dst{};  ///< destination stages of the last proxy barrier
    std::array<vk::ImageMemoryBarrier2, 2> r22_pair{}; ///< CopyProxy's barriers, one call
    u32 r22_pair_count = 0;
    bool force_stencil_bits = false; ///< test the portable resampler on any driver
    u64 generation = 0;
    mutable std::unordered_map<vk::Format, vk::FormatFeatureFlags> format_features;
    mutable std::array<vk::FormatFeatureFlags, 256> format_table{};
    mutable std::array<bool, 256> format_known{};
    std::array<std::pair<u64, Entry*>, 8> recent{}; ///< last entries by Key
    u32 recent_next = 0;
    vk::UniqueShaderModule fs_tri_vert, depth_frag, depth_stencil_frag, stencil_bits_frag;
    vk::UniqueDescriptorSetLayout resample_set_layout;
    vk::UniquePipelineLayout resample_layout;
    std::vector<std::pair<std::pair<vk::Format, bool>, vk::UniquePipeline>> resample_pipelines;
    vk::UniqueShaderModule depth_to_color_frag;
    vk::UniquePipeline depth_to_color_pipeline;
    bool depth_to_color_failed = false;
    /// bbport (r10_proxy_copies): "Scene proxies:" line every 4096 ProxyForCopy calls.
    u32 r10_calls = 0, r10_made = 0, r10_other = 0, r10_no_source = 0, r10_not_eligible = 0,
        r10_copies = 0, r10_resolves = 0, r10_source_resolves = 0, r10_samples = 0;
    /// bbport (r11_depth_clear): "Scene proxies:" line every 600 NativeDepthClear calls.
    u32 r11_passes = 0, r11_cleared = 0, r11_fills_saved = 0, r11_dropped = 0, r11_no_depth = 0,
        r11_depth_written = 0, r11_no_stencil = 0, r11_not_whole = 0, r11_continued = 0,
        r11_other = 0, r11_old = 0;
    /// The first use (Get) of a proxy NativeDepthClear cleared: still current, a fill left out;
    /// else a native write dropped it again before.
    void R11Use(Entry& e) {
        if (e.r11_cleared) {
            e.r11_cleared = false;
            ++(e.state.valid ? r11_fills_saved : r11_dropped);
        }
    }
    bool r10_old_way = false; ///< bit 34359738368 of the current counter window
    // bbport: resolves and fills per frame by consumer (NoteTrip).
    enum TripEvent : u32 { TripResolve, TripFill, TripFillSkipped, TripProxyKept, TripCopyRefused };
    struct TripRow {
        u32 event;
        vk::Format format;
        u32 width, height, level;
        const char* use;
        u64 use_hash;
        const char* how;
        const char* dropped_by;
        const char* dropped_how;
        u64 dropped_hash;
        u64 count;
    };
    void NoteTrip(TripEvent, const VideoCore::Image&, u32 level, const char* how,
                  const Entry*) const;
    /// ProxyCopyBlocker without the note of its reason (NoteTrip).
    [[nodiscard]] const char* ProxyCopyBlockerWhy(const VideoCore::Image& src,
                                                  const VideoCore::Image& dst) const;
    mutable std::vector<TripRow> trip_rows;     ///< this window (600 frames), first seen first
    mutable std::vector<TripRow> trip_sequence; ///< one frame in order (after each table)
    mutable u64 trip_window_start = ~0ull, trip_sequence_frame = ~0ull;
    mutable u64 trip_bit = 0; ///< experiment bits 1073741824, 17179869184 of the current window
    mutable std::mutex trip_mutex;
};
} // namespace Vulkan
