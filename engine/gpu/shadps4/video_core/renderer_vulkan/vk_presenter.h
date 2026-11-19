// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <array>
#include <atomic>
#include <deque>

#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>

#include "core/libraries/videoout/buffer.h"
#include "video_core/renderer_vulkan/host_passes/fsr_pass.h"
#include "video_core/renderer_vulkan/host_passes/hdr_pass.h"
#include "video_core/renderer_vulkan/host_passes/pp_pass.h"
#include "video_core/renderer_vulkan/vk_frame_generation.h"
#include "video_core/renderer_vulkan/vk_streamline.h"
#include "video_core/renderer_vulkan/vk_hdr_native.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_swapchain.h"
#include "video_core/renderer_vulkan/vk_workflow_present.h"
#include "video_core/renderer_vulkan/vk_bottle_motion_t198.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Frontend {
class WindowSDL;
}

namespace AmdGpu {
struct Liverpool;
}

namespace Vulkan {

namespace SewerPresent { struct Capture; }
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
namespace BottleCutPresent { struct Capture; }
namespace BottleCaustic::CutSource { u32 Run(); }
#endif

struct Frame {
    u32 width;
    u32 height;
    VmaAllocation allocation;
    vk::Image image;
    vk::ImageView image_view;
    vk::Fence present_done;
    vk::Semaphore ready_semaphore;
    u64 ready_tick;
    bool is_hdr{false};
    u8 id{};
    /// bbport: native HDR output (vk_hdr_native.h): a gain map, exchanged in PrepareFrame for
    /// the one made at the display buffer's display pass; `hdr_native` while it belongs to the
    /// frame shown (else the HDR encode falls back to expand).
    std::unique_ptr<HdrGainMap> hdr_gain;
    bool hdr_native{false};
    /// bbport: frame generation (vk_frame_generation.h): the generated frame shown before this
    /// one, or null. On a generated frame: its commands recorded it (std::atomic_ref: set on a
    /// recording thread, read on the swap thread after the submission went out).
    Frame* generated{nullptr};
    bool generated_ok{false};
    /// bbport: DLSS Frame Generation (vk_streamline.h): this game frame's index and inputs.
    DlssFrameInfo dlss{};
    BottleMotion::Mark motion{};
    u64 motion_swap_epoch{};
    std::shared_ptr<SewerPresent::Capture> sewer_prepared, sewer_present_readback;
    u64 sewer_prepared_generation{};
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    u64 post_present_backing{};
#endif
    vk::Format sewer_final_format{};
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    std::shared_ptr<BottleCutPresent::Capture> bottle_prepared, bottle_present_readback;
    u64 bottle_incarnation{};
    vk::Format bottle_final_format{};
#endif
    bool workflow_display_override = false;
    u32 workflow_input_width = 0;
    u32 workflow_input_height = 0;
};

enum SchedulerType {
    Draw,
    Present,
    CpuFlip,
};

class Rasterizer;

class Presenter {
public:
    Presenter(Frontend::WindowSDL& window, AmdGpu::Liverpool* liverpool);
    ~Presenter();

    void WaitForSubmittedWork(u64 timeout_ns);
    void ReportState();

    HostPasses::PostProcessingPass::Settings& GetPPSettingsRef() {
        return pp_settings;
    }

    HostPasses::FsrPass::Settings& GetFsrSettingsRef() {
        return fsr_settings;
    }

    Frontend::WindowSDL& GetWindow() const {
        return window;
    }

    Rasterizer& GetRasterizer() const {
        return *rasterizer.get();
    }

    bool IsHDRSupported() const {
        return swapchain.HasHDR();
    }

    /// The game's own HDR request (VideoOut, every flip). bbport: off (Swapchain::HasHDR is
    /// false), so it leaves the HDR output (hdr in lantern.ini, PresentHdr) and pp_settings alone.
    void SetHDR(bool enable) {
        if (!IsHDRSupported()) {
            return;
        }
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        const bool bottle_change = BottleCaustic::CutSource::Run() && swapchain.GetHDR() != enable;
#endif
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (swapchain.GetHDR() != enable) InvalidatePostPresentSwap();
#endif
        swapchain.SetHDR(enable);
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        if (bottle_change) bottle_swap_generation.fetch_add(1, std::memory_order_acq_rel);
#endif
        pp_settings.hdr = enable ? 1 : 0;
    }

    VideoCore::Image& RegisterVideoOutSurface(
        const Libraries::VideoOut::BufferAttributeGroup& attribute, VAddr cpu_address) {
        vo_buffers_addr.emplace_back(cpu_address);
        auto desc = VideoCore::TextureCache::ImageDesc{attribute, cpu_address};
        const auto image_id = texture_cache.FindImage(desc);
        auto& image = texture_cache.GetImage(image_id);
        image.usage.vo_surface = 1u;
        return image;
    }

    bool IsVideoOutSurface(const AmdGpu::ColorBuffer& color_buffer) const;

    Frame* PrepareFrame(const Libraries::VideoOut::BufferAttributeGroup& attribute,
                        VAddr cpu_address);

    Frame* PrepareBlankFrame(bool present_thread);

    void Present(Frame* frame, bool is_reusing_frame = false, bool is_game_frame = true);
    Frame* PrepareLastFrame();

    /// bbport: frame generation: a flip was queued for the swap thread (+1) or reached it (-1).
    void NoteFlipQueued(int delta) {
        frame_gen->NoteFlipQueued(delta);
    }

private:
    Frame* GetRenderFrame();

    void RecreateFrame(Frame* frame, u32 width, u32 height);

    void SetExpectedGameSize(s32 width, s32 height);

    /// bbport: frame generation: a free generated frame (its last present done), or null.
    Frame* TakeGeneratedFrame();
    /// Shows the generated frame of `frame` (if made and in time), then waits for the real one's
    /// slot. True when it was shown.
    bool PresentGenerated(Frame* frame, Frame* generated);

    /// bbport: HDR output. A swapchain-sized image of the SDR format (the frame letterboxed into
    /// it, or the menu layer drawn into it), sampled by the HDR encode pass.
    struct HdrTarget {
        vk::Image image{};
        VmaAllocation allocation{};
        vk::ImageView view{};
    };
    /// `format`: the SDR surface format when undefined (the composite, the menu layer).
    void CreateHdrTarget(HdrTarget& target, vk::Extent2D extent, const char* name,
                         vk::Format format = vk::Format::eUndefined);
    void DestroyHdrTarget(const HdrTarget& target);
    /// The targets at the swapchain's size; the old ones go once the GPU is past them.
    void EnsureHdrTargets(vk::Extent2D extent);
    /// bbport: DLSS-G in HDR: the HUD-less frame's SDR composite and its HDR encode (the back
    /// buffer's format), made the first time a frame needs them and at a new size.
    void EnsureDlssHdrTargets(vk::Extent2D extent);
    /// Records the frame (letterboxed), the menu and the HDR encode into the swapchain image;
    /// with `dlss_inputs` also the HUD-less frame's encode for DLSS-G (DlssFrameGenHdr).
    void PresentHdr(vk::CommandBuffer cmdbuf, Frame* frame, vk::Extent2D extent, bool dlss_inputs);
    /// One line when the HDR output's mode starts or changes; in native mode one when frames
    /// stop or start having a gain map (at most every 5 s, with the switches in between).
    void LogHdrState(bool scrgb, int mode, bool native_frame);

private:
    float expected_ratio{1920.0 / 1080.0f};
    u32 expected_frame_width{1920};
    u32 expected_frame_height{1080};

    Frontend::WindowSDL& window;
    Instance instance;
    HostPasses::FsrPass fsr_pass;
    HostPasses::FsrPass::Settings fsr_settings{};
    HostPasses::PostProcessingPass::Settings pp_settings{};
    HostPasses::PostProcessingPass pp_pass;
    HostPasses::HdrOutputPass hdr_pass; ///< bbport: HDR output encode (present thread)
    HdrTarget hdr_game{}, hdr_overlay{}; ///< bbport: HDR output's SDR composite and menu layer
    vk::Extent2D hdr_extent{};
    HdrTarget dlss_hdr_composite{}, dlss_hdr_hudless{}; ///< bbport: EnsureDlssHdrTargets
    vk::Extent2D dlss_hdr_extent{};
    /// bbport: while a generated frame is presented, the real frame whose gain map it uses
    /// (PresentGenerated, PresentHdr; present thread).
    const Frame* hdr_gain_source = nullptr;
    WorkflowPresent workflow_present;
    bool MotionMarker(vk::CommandBuffer cb,vk::Image target,const BottleMotion::Mark& mark);
    void ReportMotionAttempts();
    VkBuffer motion_buffer{};
    VmaAllocation motion_allocation{};
    std::atomic<u64> motion_swap_epoch{0};
    std::atomic<u64> sewer_swap_generation{1};
#ifdef BB_TEST_SHARED_POST_GRAPH
    void InvalidatePostPresentSwap();
#endif
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    std::atomic<u64> post_present_next_backing{0};
#endif
    u64 sewer_next_frame_generation = 0; // draw owner
    u64 sewer_present_serial = 0; // submit_mutex, actual Vk present attempts
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    std::atomic<u64> bottle_swap_generation{1};
    u64 bottle_next_incarnation{}; // draw owner
    u64 bottle_present_serial{}; // submit_mutex, actual Vk present attempts
#endif
    struct MotionAttempt {
        BottleMotion::Mark mark;
        u64 ready_tick,submit_ns,result_ns,swap_epoch;
        vk::SwapchainKHR swap;
        vk::Image swap_image;
        u32 swap_index;
        bool success;
    };
    std::array<MotionAttempt,BottleMotion::MaxOn+BottleMotion::MaxOff> motion_attempts{};
    u32 motion_attempts_count{};
    int hdr_logged_mode = -1;   ///< bbport: LogHdrState (present thread)
    int hdr_native_state = -1;  ///< native mode: the last frame had a gain map (1) or not (0)
    int hdr_logged_native = -1; ///< ... as last logged
    u32 hdr_native_switches = 0;
    std::chrono::steady_clock::time_point hdr_next_log{};
    std::mutex passes_mutex; ///< bbport: the passes are recorded on the recording threads
    AmdGpu::Liverpool* liverpool;
    Scheduler draw_scheduler;
    std::deque<u64> recent_frame_ticks; ///< bbport: BB_FRAMES_AHEAD bound (PrepareFrame)
    Scheduler present_scheduler;
    Scheduler flip_scheduler;
    Swapchain swapchain;
    Runtime runtime;
    std::unique_ptr<Rasterizer> rasterizer;
    VideoCore::TextureCache& texture_cache;
    vk::UniqueCommandPool command_pool;
    std::vector<Frame> present_frames;
    std::queue<Frame*> free_queue;
    Frame* last_submit_frame;
    std::mutex free_mutex;
    std::condition_variable free_cv;
    std::condition_variable_any frame_cv;
    std::vector<VAddr> vo_buffers_addr;
    /// bbport: frame generation and its own presentation frames (outside free_queue: the game
    /// never waits for one; a busy one is in a frame on its way to the swap thread).
    std::unique_ptr<FrameGenerator> frame_gen;
    /// One per game frame between preparation and the swap thread: with 2, every third frame
    /// found both busy and got no generated frame (100 FPS shown instead of 120, beta 9.8).
    static constexpr size_t NumGeneratedFrames = 4;
    std::array<Frame, NumGeneratedFrames> generated_frames{};
    std::array<std::atomic<bool>, NumGeneratedFrames> generated_busy{};
    /// bbport: DLSS Frame Generation (vk_streamline.h), and each presentation frame's frame
    /// without its UI through the post process (by Frame::id).
    std::unique_ptr<DlssFrameGen> dlss_fg;
    std::vector<Frame> dlss_hudless_frames;
};

} // namespace Vulkan
