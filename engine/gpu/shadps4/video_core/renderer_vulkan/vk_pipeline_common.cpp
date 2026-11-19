// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <span>
#include <string>

#include <boost/container/small_vector.hpp>
#include <boost/container/static_vector.hpp>

#include "bbport_settings.h"
#include "bbport_interior_exposure.h" // bbport (r99_interior-exposure)
#include "bbport_test_exposure_lock.h" // bbport (t125, TOOL)
#include "shader_recompiler/native/froyok_composite.h"
#include "shader_recompiler/native/gt7_tonemap.h"
#include "shader_recompiler/native/tone_curve.h"
#include "shader_recompiler/resource.h"
#include "video_core/renderer_vulkan/pipeline_compile_queue.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_pipeline_cache.h"
#include "video_core/renderer_vulkan/vk_pipeline_common.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
#include "video_core/renderer_vulkan/vk_bottle_set0_b182.h"
#endif

namespace Vulkan {

Pipeline::Pipeline(const Instance& instance_, Scheduler& scheduler_, DescriptorHeap& desc_heap_,
                   const Shader::Profile& profile_, vk::PipelineCache pipeline_cache,
                   bool is_compute_ /*= false*/)
    : instance{instance_}, scheduler{scheduler_}, desc_heap{desc_heap_}, profile{profile_},
      is_compute{is_compute_} {}

Pipeline::~Pipeline() {
    // bbport: a compile thread may still be writing `pipeline` (BB_ASYNC_PIPELINES).
    WaitReady();
}

// bbport: time render threads waited for pipelines created on compile threads; reported with
// the compile time of the GPU thread (BB_FRAME_STATS "shader/pipeline compiles, ... ms").
extern std::atomic<u64> g_bb_compile_ns, g_bb_compile_ns_total;

void Pipeline::WaitReady() const noexcept {
    if (ready.load(std::memory_order_acquire)) {
        return;
    }
    const auto start = std::chrono::steady_clock::now();
    // bbport: still queued (the compile threads busy with the pipelines before it): compiled
    // here, instead of waiting for them first and then for this one.
    if (auto job = TakePipelineJob(this)) {
        job();
        pipeline_compile_stats.taken.fetch_add(1, std::memory_order_relaxed);
    }
    while (!ready.load(std::memory_order_acquire)) {
        ready.wait(false, std::memory_order_acquire);
    }
    const u64 waited = u64(std::chrono::duration_cast<std::chrono::nanoseconds>(
                               std::chrono::steady_clock::now() - start)
                               .count());
    g_bb_compile_ns += waited;
    g_bb_compile_ns_total += waited;
    pipeline_compile_stats.NoteWait(waited);
}

namespace {
bool EnvOff(const char* name) {
    const char* env = std::getenv(name);
    return env && env[0] == '0';
}
} // namespace

u64 SkipUncompiledBudgetNs() {
    static const u64 budget = [] {
        if (EnvOff("BB_SKIP_UNCOMPILED")) {
            return u64{0};
        }
        const char* env = std::getenv("BB_SKIP_UNCOMPILED_MS");
        const u64 ms = env && env[0] ? std::strtoull(env, nullptr, 10) : 1000;
        return ms * 1'000'000;
    }();
    return budget;
}

bool LatePipelineBindEnabled() {
    static const bool enabled = !EnvOff("BB_LATE_PIPELINE_BIND");
    return enabled;
}

void LogPipelineCompileMode(const Instance& instance, bool late_binds_possible) {
    if (!AsyncPipelinesEnabled()) {
        std::printf("Pipelines: new ones compiled where the draw needs them (BB_ASYNC_PIPELINES=0)\n");
        return;
    }
    // VK_EXT_graphics_pipeline_library is reported, not used: shaders reach the port at the draw
    // that needs them and a pipeline's shaders share one descriptor set layout, so the libraries
    // would be compiled at that draw as well (docs/pipeline_compiles.md).
    const auto extensions = instance.GetAvailableExtensions();
    const bool gpl = std::ranges::find(extensions, std::string{
                                                       VK_EXT_GRAPHICS_PIPELINE_LIBRARY_EXTENSION_NAME}) !=
                     extensions.end();
    bool fast_linking = false;
    if (gpl) {
        const auto chain = instance.GetPhysicalDevice()
                               .getProperties2<vk::PhysicalDeviceProperties2,
                                               vk::PhysicalDeviceGraphicsPipelineLibraryPropertiesEXT>();
        fast_linking = chain.get<vk::PhysicalDeviceGraphicsPipelineLibraryPropertiesEXT>()
                           .graphicsPipelineLibraryFastLinking;
    }
    const u64 budget_ms = SkipUncompiledBudgetNs() / 1'000'000;
    std::printf("Pipelines: new ones compiled on %u threads; draws of one still compiling: scene "
                "geometry %s, other draws %s (BB_SKIP_UNCOMPILED, BB_LATE_PIPELINE_BIND); graphics "
                "pipeline library %s, not used\n",
                PipelineCompileThreads(),
                budget_ms ? fmt::format("left out for up to {} ms", budget_ms).c_str() : "waits",
                late_binds_possible && LatePipelineBindEnabled()
                    ? "bind it on the recording threads (they wait for it)"
                    : "wait for it on the draw recording thread",
                gpl ? (fast_linking ? "offered (fast linking)" : "offered (no fast linking)")
                    : "not offered");
    std::fflush(stdout);
}

void Pipeline::MarkReady() noexcept {
    ready.store(true, std::memory_order_release);
    ready.notify_all();
}


namespace {
/// bbport: the tone curve extension's parameters for this draw (native/tone_curve.h), from the
/// HDR settings: on only with an HDR output. BB_HDR_SCENE_KNEE (0.75): the curve's output where
/// the extension starts.
Shader::Native::ToneCurvePush ToneCurveParams() {
    static const float knee = [] {
        const char* env = std::getenv("BB_HDR_SCENE_KNEE");
        const float value = env ? float(std::atof(env)) : 0.75f;
        return value > 0.0f && value < 1.0f ? value : 0.75f;
    }();
    const auto& settings = BbSettings::Get();
    const float paper = std::clamp(settings.hdr_paper_white.load(std::memory_order_relaxed),
                                   BbSettings::HdrPaperWhiteMin, BbSettings::HdrPaperWhiteMax);
    const bool hdr = settings.hdr_output.load(std::memory_order_relaxed) != BbSettings::HdrOutputOff;
    return {
        .knee = knee,
        .peak = BbSettings::HdrPeakNits(settings) / paper,
        // As native mode: boost is the share of the scene's range above white, sqrt in log2.
        .strength = std::sqrt(std::clamp(settings.hdr_boost.load(std::memory_order_relaxed), 0.0f, 1.0f)),
        .enabled = hdr ? 1.0f : 0.0f,
    };
}
} // namespace

#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
static void NoteBottleSet0(Scheduler& scheduler, BottleDisplay182::DescriptorTicket& selected,
                           vk::CommandBuffer cmd, vk::PipelineBindPoint bind_point, vk::PipelineLayout layout,
                           BottleDisplay182::DescriptorSlots slots, BottleDisplay182::BindRoute route,
                           vk::DescriptorSet set = {}) {
    const auto* worker = NativeWriteSuffix::worker_segment;
    selected.NoteBind(BottleDisplay182::NoteOrigin(scheduler, selected, cmd,
                         worker ? worker->scheduler : nullptr, worker ? worker->buffer : vk::CommandBuffer{},
                         worker ? worker->tick : 0, worker ? worker->segment : 0),
                      bind_point, layout, slots, route, set);
}
#endif

void Pipeline::BindResources(DescriptorWrites& set_writes, const Shader::PushData& push_data,
                             std::span<const vk::DescriptorImageInfo> image_infos,
                             std::span<const vk::DescriptorBufferInfo> buffer_infos,
                             float froyok_blend
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
                             , const std::shared_ptr<BottleDisplay182::DescriptorTicket>& bottle
#endif
                             ) const {
    const auto bind_point =
        IsCompute() ? vk::PipelineBindPoint::eCompute : vk::PipelineBindPoint::eGraphics;
    const auto stage_flags = IsCompute() ? vk::ShaderStageFlagBits::eCompute : AllGraphicsStageBits;
    const vk::PipelineLayout layout = *pipeline_layout;
    scheduler.Record([layout, stage_flags, push_data](vk::CommandBuffer cmdbuf) {
        cmdbuf.pushConstants(layout, stage_flags, 0u, sizeof(push_data), &push_data);
    });
    if (uses_tone_curve && !Shader::Native::ToneCurveEnabled()) {
        const auto& settings = BbSettings::Get();
        const Shader::Native::Gt7Push tone_map{
            .mode = float(settings.graphics_tonemapper.load(std::memory_order_relaxed)),
            // bbport (r99_interior-exposure): times the interior lift, exactly 1 unless
            // BB_INTERIOR_EXPOSURE is on (gpu/shim/bbport_interior_exposure.h)
            .exposure = settings.graphics_gt7_exposure.load(std::memory_order_relaxed) *
                        BbTestExposureLock::HoldScale(BbInteriorExposure::Scale()),
            .unused = {},
        };
        scheduler.Record([layout, stage_flags, tone_map](vk::CommandBuffer cmdbuf) {
            cmdbuf.pushConstants(layout, stage_flags, Shader::Native::ToneCurvePushOffset,
                                 sizeof(tone_map), &tone_map);
        });
    } else if (uses_tone_curve) {
        const Shader::Native::ToneCurvePush tone = ToneCurveParams();
        scheduler.Record([layout, stage_flags, tone](vk::CommandBuffer cmdbuf) {
            cmdbuf.pushConstants(layout, stage_flags, Shader::Native::ToneCurvePushOffset,
                                 sizeof(tone), &tone);
        });
    }
    if (uses_froyok_bloom) {
        const Shader::Native::FroyokPush bloom{.blend = froyok_blend, .unused = {}};
        scheduler.Record([layout, stage_flags, bloom](vk::CommandBuffer cmdbuf) {
            cmdbuf.pushConstants(layout, stage_flags, Shader::Native::FroyokPushOffset,
                                 sizeof(bloom), &bloom);
        });
    }

    // Bind descriptor set.
    if (set_writes.empty()) {
        return;
    }

    if (uses_push_descriptors) {
        if (!scheduler.IsRecordingDeferred()) {
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
            if (bottle) {
                // Same inline call and operands as the ordinary branch. Only the owned receipt
                // persists. The synchronous Vulkan write span is never retained by the ticket.
                scheduler.Record([&, ticket = bottle](vk::CommandBuffer cmdbuf) {
                    cmdbuf.pushDescriptorSetKHR(bind_point, layout, 0, set_writes);
                    NoteBottleSet0(scheduler, *ticket, cmdbuf, bind_point, layout,
                                   BottleDisplay182::InspectSet0(set_writes), BottleDisplay182::BindRoute::InlinePush);
                });
                return;
            }
#endif
            scheduler.Record([&](vk::CommandBuffer cmdbuf) {
                cmdbuf.pushDescriptorSetKHR(bind_point, layout, 0, set_writes);
            });
            return;
        }
        // Writes and the infos they point to are laid out in the recording chunk, with the
        // pointers already aimed at those copies: the command only carries a span.
        // bbport: when every write points into the caller's info arrays (draws and
        // dispatches), each array is copied once and the pointers are rebased: a copy per
        // descriptor (two per write) cost the draw recording thread ~3% of its time.
        const auto within = [](const auto* p, u32 count, const auto& array) {
            return p >= array.data() && p + count <= array.data() + array.size();
        };
        bool bulk = !image_infos.empty() || !buffer_infos.empty();
        for (const auto& write : set_writes) {
            if (!bulk) {
                break;
            }
            bulk = !write.pTexelBufferView &&
                   (!write.pImageInfo || within(write.pImageInfo, write.descriptorCount,
                                                image_infos)) &&
                   (!write.pBufferInfo || within(write.pBufferInfo, write.descriptorCount,
                                                 buffer_infos));
        }
        if (bulk) {
            scheduler.ReserveRecordData(set_writes.size() * sizeof(vk::WriteDescriptorSet) +
                                        image_infos.size_bytes() + buffer_infos.size_bytes() +
                                        256);
            const auto writes =
                scheduler.RecordData(std::span<const vk::WriteDescriptorSet>{set_writes});
            const auto images = scheduler.RecordData(image_infos);
            const auto buffers = scheduler.RecordData(buffer_infos);
            auto* patched = const_cast<vk::WriteDescriptorSet*>(writes.data());
            for (size_t i = 0; i < writes.size(); ++i) {
                auto& write = patched[i];
                if (write.pImageInfo) {
                    write.pImageInfo = images.data() + (write.pImageInfo - image_infos.data());
                }
                if (write.pBufferInfo) {
                    write.pBufferInfo = buffers.data() + (write.pBufferInfo - buffer_infos.data());
                }
            }
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
            if (bottle) {
                scheduler.Record([producer = &scheduler, bind_point, layout, writes, ticket = bottle](vk::CommandBuffer cmdbuf) {
                    cmdbuf.pushDescriptorSetKHR(bind_point, layout, 0, writes);
                    NoteBottleSet0(*producer, *ticket, cmdbuf, bind_point, layout,
                                   BottleDisplay182::InspectSet0(writes), BottleDisplay182::BindRoute::BulkPush);
                });
                return;
            }
#endif
            scheduler.Record([bind_point, layout, writes](vk::CommandBuffer cmdbuf) {
                cmdbuf.pushDescriptorSetKHR(bind_point, layout, 0, writes);
            });
            return;
        }
        size_t bytes = set_writes.size() * sizeof(vk::WriteDescriptorSet) + 64;
        for (const auto& write : set_writes) {
            bytes += write.descriptorCount *
                         (sizeof(vk::DescriptorBufferInfo) + sizeof(vk::DescriptorImageInfo) +
                          sizeof(vk::BufferView)) +
                     32;
        }
        scheduler.ReserveRecordData(bytes);
        const auto writes = scheduler.RecordData(std::span<const vk::WriteDescriptorSet>{set_writes});
        auto* patched = const_cast<vk::WriteDescriptorSet*>(writes.data());
        for (size_t i = 0; i < writes.size(); ++i) {
            auto& write = patched[i];
            if (write.pBufferInfo) {
                write.pBufferInfo = scheduler.RecordData(std::span{write.pBufferInfo, write.descriptorCount}).data();
            }
            if (write.pImageInfo) {
                write.pImageInfo = scheduler.RecordData(std::span{write.pImageInfo, write.descriptorCount}).data();
            }
            if (write.pTexelBufferView) {
                write.pTexelBufferView =
                    scheduler.RecordData(std::span{write.pTexelBufferView, write.descriptorCount}).data();
            }
        }
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
        if (bottle) {
            scheduler.Record([producer = &scheduler, bind_point, layout, writes, ticket = bottle](vk::CommandBuffer cmdbuf) {
                cmdbuf.pushDescriptorSetKHR(bind_point, layout, 0, writes);
                NoteBottleSet0(*producer, *ticket, cmdbuf, bind_point, layout,
                               BottleDisplay182::InspectSet0(writes), BottleDisplay182::BindRoute::RebasedPush);
            });
            return;
        }
#endif
        scheduler.Record([bind_point, layout, writes](vk::CommandBuffer cmdbuf) {
            cmdbuf.pushDescriptorSetKHR(bind_point, layout, 0, writes);
        });
        return;
    }

    // Descriptor set updates are device calls: they stay on this thread.
    const auto desc_set = desc_heap.Commit(*desc_layout);
    for (auto& set_write : set_writes) {
        set_write.dstSet = desc_set;
    }
    instance.GetDevice().updateDescriptorSets(set_writes, {});
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    if (bottle) {
        const auto updated = BottleDisplay182::InspectSet0(set_writes, desc_set);
        scheduler.Record([producer = &scheduler, bind_point, layout, desc_set, updated,
                          ticket = bottle](vk::CommandBuffer cmdbuf) {
            cmdbuf.bindDescriptorSets(bind_point, layout, 0, desc_set, {});
            NoteBottleSet0(*producer, *ticket, cmdbuf, bind_point, layout, updated,
                           BottleDisplay182::BindRoute::UpdatedSet, desc_set);
        });
        return;
    }
#endif
    scheduler.Record([bind_point, layout, desc_set](vk::CommandBuffer cmdbuf) {
        cmdbuf.bindDescriptorSets(bind_point, layout, 0, desc_set, {});
    });
}

std::string Pipeline::GetDebugString() const {
    std::string stage_desc;
    for (const auto& stage : stages) {
        if (stage) {
            const auto shader_name = PipelineCache::GetShaderName(stage->hw_stage, stage->pgm_hash);
            if (stage_desc.empty()) {
                stage_desc = shader_name;
            } else {
                stage_desc = fmt::format("{},{}", stage_desc, shader_name);
            }
        }
    }
    return stage_desc;
}

} // namespace Vulkan
