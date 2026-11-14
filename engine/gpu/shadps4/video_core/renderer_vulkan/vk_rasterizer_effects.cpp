// SPDX-License-Identifier: GPL-3.0-or-later
#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <optional>
#include <string>

#include <fmt/format.h>

#include "bbport_settings.h"
#include "bbport_toggles.h"
#include "bbport_sun_cascades.h"
#include <xxhash.h>

#include "core/memory.h"
#include "video_core/renderer_vulkan/vk_effect_shaders.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_shader_util.h"

namespace Vulkan {

namespace {
constexpr u64 ShadowResolveHash = 0xf55643de;
constexpr u64 ShadowBlurHash = 0x11ffdfb5;
constexpr u64 PointLightsFullHash = 0x9f9ef267;
constexpr u64 HdrPostHash = 0xccbf44a6;
constexpr u64 SceneTargetHash = 0x32e47788;

constexpr u32 PointLightCount(u64 hash) {
    switch (hash) {
    case 0x370174f7:
    case 0x7cc2c044:
        return 1;
    case 0x186d69d5:
    case 0x600f86b0:
        return 2;
    case 0xd22cbfd1:
        return 3;
    case 0x3105494c:
        return 4;
    case 0xd75fe2ff:
        return 5;
    case 0x07d07cf3:
        return 6;
    case 0xf2531727:
        return 7;
    case 0xc6edb19a:
        return 8;
    case 0xb59b4c4e:
        return 9;
    case 0x505ebdbe:
        return 10;
    case 0x22b357f3:
        return 11;
    case PointLightsFullHash:
        return 12;
    default:
        return 0;
    }
}

u32 PackedOffsets(const Shader::PushData& push) {
    static_assert(offsetof(Shader::PushData, buf_offsets) == 80);
    u32 word = 0;
    std::memcpy(&word, push.buf_offsets.data(), sizeof(word));
    return word;
}

/// The draw's output to colour target `cb` is added to what the target holds, whatever that is:
/// result = target + source * (one or the source's alpha).
bool AddsLight(const AmdGpu::Regs& regs, u32 cb) {
    using Factor = AmdGpu::BlendControl::BlendFactor;
    const auto& blend = regs.blend_control[cb];
    // (With blend_bypass the pipeline is built without blending: vk_pipeline_cache.cpp.)
    return blend.enable && !regs.color_buffers[cb].info.blend_bypass &&
           blend.color_func == AmdGpu::BlendControl::BlendFunc::Add &&
           blend.color_dst_factor == Factor::One &&
           (blend.color_src_factor == Factor::One || blend.color_src_factor == Factor::SrcAlpha) &&
           regs.color_control.mode == AmdGpu::ColorControl::OperationMode::Normal &&
           regs.color_control.rop3 == AmdGpu::ColorControl::LogicOp::Copy;
}

u64 FragmentHash(const GraphicsPipeline* pipeline) {
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    return ps ? ps->pgm_hash : 0;
}

bool AnyWanted() {
    const auto& s = BbSettings::Get();
    for (const int effect : {BbSettings::EffectGi, BbSettings::EffectContactShadows,
                             BbSettings::EffectPcss, BbSettings::EffectVolumetricLight,
                             BbSettings::EffectPointFog, BbSettings::EffectPointShadows,
                             BbSettings::EffectRayTracing}) {
        if (s.effects[effect].load(std::memory_order_relaxed)) {
            return true;
        }
    }
    return s.startup_bloom_quality == BbSettings::BloomQualityFroyok ||
           EffectShaders::GtaoActive() || EffectShaders::SsrActive();
}
}

void Rasterizer::EffectsEndLampBatch() {
    if (point_shadow->Apart()) {
        const auto jitter = upscaler->Jitter();
        point_shadow->EndApart(jitter[0] != 0.0f || jitter[1] != 0.0f);
    }
}

void Rasterizer::EffectsOnFrameEnd() {
    effects_wanted = AnyWanted();
    // Lamps apart: a batch nothing ended. The frame is composed and the scene's depth forgotten
    // (CameraMotion::OnDisplayPass), so its lamp light is lost; it is counted and printed.
    point_shadow->DropUnended();
    if (!effects_wanted) {
        point_shadow->Drop();
    }
    froyok_bloom->OnFrameEnd();
    point_shadow->OnFrameEnd();
    SunHoldFrameEnd(); // r7_cascades: reads sun_atlas before SunAtlasFrameEnd resets it
    SunAtlasFrameEnd();
    rt_shadow->OnFrameEnd();
    // bbport (r19_draw-cost): the draws that took each short path, a frame.
    if (++r19_stats.frames >= 600) {
        const auto c = rt_shadow->TakeR19Counters();
        const double f = double(r19_stats.frames);
        BbReport::Printf("Draw cost (r19): experiment 17592186044416 %s; a frame: %.1f draws past the sun "
                    "atlas bookkeeping (sun not ray traced), %.1f G-buffer capture draws with the "
                    "Motion block's index check, %.1f with its palette; %.1f ray tracing capture "
                    "draws: Wanted() asked once %.1f, mesh hash made %.1f, to-world compared in "
                    "place %.1f, camera index of the draw before %.1f, shared from the occurrence "
                    "%.1f, not shared from the memo %.1f, Entry from the memo %.1f (memo filled "
                    "%.1f), far bookkeeping left out %.1f\n",
                    BbToggle::Experiment(R19DrawCostOffBit) ? "set (old paths)" : "clear",
                    double(r19_stats.sun_short) / f, double(r19_stats.motion_indices) / f,
                    double(r19_stats.motion_palettes) / f, double(c.calls) / f,
                    double(c.wanted_skipped) / f, double(c.mesh_made) / f,
                    double(c.world_in_place) / f, double(c.camera_cached) / f,
                    double(c.shared_known) / f, double(c.shared_memo) / f, double(c.entry_memo) / f,
                    double(c.entry_filled) / f, double(c.far_book_skipped) / f);
        r19_stats = {};
    }
    ssgi->OnFrameEnd();
    ssr_temporal->OnFrameEnd();
}

void Rasterizer::EffectsBeforeTargets(const GraphicsPipeline* pipeline) {
    if (!effects_wanted) {
        return;
    }
    const u64 hash = FragmentHash(pipeline);
    point_shadow->NextDraw();
    if (hash != EffectShaders::SsrHash) {
        ssr_temporal->Flush(upscaler->Jitter());
    }
    contact_shadow->Flush(hash == ShadowBlurHash);
    // A lamp draw joins the batch or ends it later (EffectsBeforeBind). While the batch's lamps
    // are drawn apart it is looked at here as well: one that is not taken into the batch (an
    // indirect draw, one without its light list) writes the light targets themselves.
    const bool lamp = PointLightCount(hash) != 0;
    if (!lamp || point_shadow->Apart()) {
        if (point_shadow->Pending()) {
            const auto& regs = Regs();
            const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
            const bool writes_color =
                pipeline->GetGraphicsKey().mrt_mask != 0 &&
                regs.color_control.mode != AmdGpu::ColorControl::OperationMode::Disable;
            const bool writes_depth =
                regs.depth_control.depth_enable && regs.depth_control.depth_write_enable;
            const auto lights = point_shadow->PendingAddresses();
            const auto is_light = [&](VAddr address) {
                return address != 0 && (address == lights[0] || address == lights[1]);
            };
            const u32 mrt = pipeline->GetGraphicsKey().mrt_mask;
            // other: touches the light targets in a way that is neither drawing into them nor
            // sampling them, or cannot be told.
            const bool other = !lights[0] || !lights[1] || (ps && ps->has_storage_images);
            bool draws = false, samples = false;
            for (u32 cb = 0; writes_color && !other && !draws && cb < 8; ++cb) {
                draws = (mrt & (1u << cb)) && is_light(regs.color_buffers[cb].Address());
            }
            for (std::size_t i = 0; ps && !other && !samples && i < ps->images.size(); ++i) {
                samples = is_light(ps->images[i].GetSharp(*ps).Address());
            }
            if (!lamp && !writes_depth && !other && !draws && !samples) {
                point_shadow->Kept();
                return;
            }
            // Lamps apart (vk_point_shadow.h): the batch's lamp light is not in the light targets
            // yet, and adding it later gives the same sum, so a draw that only adds light to them
            // (the grid's other lights, tile by tile between the lamps) leaves the batch open.
            if (!writes_depth && !other && !samples && point_shadow->Apart()) {
                bool adds = true;
                for (u32 cb = 0; adds && cb < 8; ++cb) {
                    const auto& target = regs.color_buffers[cb];
                    if ((mrt & (1u << cb)) && is_light(target.Address())) {
                        // (A fast clear still owed to the target would run when the pass begins.)
                        adds = AddsLight(regs, cb) &&
                               !texture_cache.IsMetaCleared(target.CmaskAddress(),
                                                            target.BaseSlice());
                    }
                }
                if (adds) {
                    if (!lamp) {
                        point_shadow->KeptAdding();
                    }
                    return;
                }
            }
            point_shadow->Ended(hash);
        }
        const auto jitter = upscaler->Jitter();
        point_shadow->Flush(jitter[0] != 0.0f || jitter[1] != 0.0f);
    }
}

void Rasterizer::EffectsAfterTargets(const GraphicsPipeline* pipeline) {
    const auto& key = pipeline->GetGraphicsKey();
    const bool gbuffer = std::popcount(key.mrt_mask) >= 5 && db_desc.first;
    if (gbuffer) {
        depth_of_field->Reset();
    }
    if (!effects_wanted) {
        return;
    }
    if (gbuffer) {
        volumetric_light->Reset();
        ssgi->OnGBufferDraw(db_desc.first, cb_descs[2].first, cb_descs[0].first,
                            cb_descs[1].first, cb_descs[3].first);
    }
    if (cb_descs[0].first && EffectShaders::GtaoActive() &&
        FragmentHash(pipeline) == EffectShaders::SsaoHash) {
        ssgi->OnAoDraw(cb_descs[0].first);
    }
}

void Rasterizer::EffectsBlendedScene() {
    if (effects_wanted) {
        ssgi->OnOpaqueScene(cb_descs[0].first, db_desc.first, upscaler->Jitter());
    }
}

void Rasterizer::EffectsBeforeUpscaler(u64 compute_hash) {
    if (effects_wanted && compute_hash == upscaler->TriggerHash()) {
        const auto camera = camera_motion->PassMatrices();
        volumetric_light->SetCamera({camera.view, camera.inv_view, camera.valid});
        volumetric_light->Composite(upscaler->SceneColor(), "the upscaler");
    }
}

void Rasterizer::EffectsBeforeResources(const GraphicsPipeline* pipeline) {
    if (effects_wanted && FragmentHash(pipeline) == HdrPostHash) {
        const auto camera = camera_motion->PassMatrices();
        volumetric_light->SetCamera({camera.view, camera.inv_view, camera.valid});
        volumetric_light->Composite();
    }
}

void Rasterizer::EffectsCaptureDraw(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline,
                                    bool is_indexed, u32 index_offset) {
    auto& dc = Dc();
    const u32 mode = pipeline->GetGraphicsKey().motion_vectors;
    if (mode == Shader::MotionVectors::VertexBoth) {
        dc.push_data.motion_param &= 0xffffu;
    } else {
        dc.push_data.motion_param = 0;
    }
    if (!rt_shadow->Wanted() || !dc.motion_geometry) {
        return;
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    const auto& fetch = pipeline->GetFetchShader();
    u32 first_vertex = regs.index_offset, first_instance = 0;
    if (fetch) {
        if (first_vertex == 0 && fetch->vertex_offset_sgpr != -1) {
            first_vertex = vs.UserData()[fetch->vertex_offset_sgpr];
        }
        if (fetch->instance_offset_sgpr != -1) {
            first_instance = vs.UserData()[fetch->instance_offset_sgpr];
        }
    }
    const u32 index_size = regs.index_buffer_type.index_type == AmdGpu::IndexType::Index16 ? 2u : 4u;
    RtShadow::Draw draw{
        .shader = vs.pgm_hash,
        .geometry = dc.motion_geometry,
        .index_size = index_size,
        .index_count = regs.num_indices,
        .first_vertex = first_vertex,
        .first_instance = first_instance,
        .instances = regs.num_instances.NumInstances(),
        .restart = regs.enable_primitive_restart != 0,
        .strip = regs.primitive_type == AmdGpu::PrimitiveType::TriangleStrip,
        .triangles = regs.primitive_type == AmdGpu::PrimitiveType::TriangleStrip ||
                     regs.primitive_type == AmdGpu::PrimitiveType::TriangleList,
        .shadow_pass = !gbuffer_draw &&
                       regs.depth_buffer.Pitch() == regs.depth_buffer.Height() &&
                       regs.depth_buffer.Height() >= 1024,
        .camera_pass = gbuffer_draw,
        .solid = regs.depth_control.depth_write_enable != 0 && !regs.blend_control[0].enable,
        .alpha = ps && ps->has_discard,
        .textured = ps && !ps->images.empty(),
        // bbport (r14_cascade_rt): the sun cascade of a shadow pass draw (RtShadow::SunCascade)
        .viewport = {regs.viewports[0].xoffset, regs.viewports[0].yoffset,
                     regs.viewports[0].xscale, regs.viewports[0].yscale},
        .target = regs.depth_buffer.Height(),
    };
    if (fetch) {
        for (const auto& attribute : fetch->attributes) {
            if (attribute.semantic == 0) {
                draw.positions = attribute.GetSharp(vs).base_address;
                break;
            }
        }
    }
    // bbport (r19_draw-cost): a G-buffer draw's Motion block (DrawRecord, just before) checked the
    // same index range (same address, size and predicate) and hashed the same bone palettes (same
    // buffers, order, predicates and seed 0); taken from it, the palette only when its walk ran to
    // the end (no skeleton: skinned stays false here too; no GPU-written palette). Experiment
    // 17592186044416 set: computed here again.
    const bool r19 = !BbToggle::Experiment(R19DrawCostOffBit);
    const bool r19_reuse = r19 && r19_motion.valid;
    const bool r19_palette = r19_reuse && r19_motion.palette_complete;
    draw.r19_wanted = r19; // Wanted() was true above
    if (is_indexed) {
        const VAddr address = regs.index_base_address.Address<VAddr>() + u64(index_offset) * index_size;
        const u64 bytes = u64(regs.num_indices) * index_size;
        r19_stats.motion_indices += r19_reuse ? 1u : 0u;
        if (r19_reuse ? r19_motion.indices_valid
                      : address && memory->IsValidGpuMapping(address, 0) &&
                            memory->ClampRangeSize(address, bytes) == bytes) {
            draw.indices = address;
        }
    }
    for (const auto& resource : vs.buffers) {
        if (resource.IsSpecial()) {
            continue;
        }
        const auto buffer = resource.GetSharp(vs);
        const u32 size = buffer.GetSize();
        if (!buffer.Valid() || !memory->IsValidGpuMapping(buffer.base_address, 0) ||
            memory->ClampRangeSize(buffer.base_address, size) != size) {
            continue;
        }
        if (size == 864) {
            draw.constants = reinterpret_cast<const float*>(buffer.base_address);
        } else if (buffer.GetStride() == 16) {
            const auto role = Motion::ClassifyBuffer(size);
            if (role == Motion::BufferRole::Skeleton) {
                draw.skinned = true;
            } else if (role == Motion::BufferRole::SmallSkeleton && !r19_palette) {
                draw.palette = XXH3_64bits_withSeed(reinterpret_cast<const void*>(buffer.base_address),
                                                    size, draw.palette);
            }
        }
    }
    if (r19_palette) { // bbport (r19_draw-cost)
        draw.palette = r19_motion.palette;
        ++r19_stats.motion_palettes;
    }
    // bbport (r17_rt-upkeep): BB_RT_UNCHANGED (opt-in): for a moving caster, a hash of what its
    // vertex shader reads: the program, user data (with every descriptor), the bytes of every guest
    // buffer, the vertex stream descriptors. Not provable (0) with a texture, a special or written
    // buffer, or an input the GPU wrote (its CPU copy would be stale). The vertex streams' bytes are
    // not hashed: a stream rewritten in place under the same descriptor is not seen.
    if ((draw.skinned || draw.palette != 0) && rt_shadow->InputsWanted()) {
        bool known = vs.images.empty();
        const u64 program = vs.pgm_hash;
        u64 hash = XXH3_64bits_withSeed(&program, sizeof(program), dc.motion_geometry);
        const auto user = vs.UserData();
        hash = XXH3_64bits_withSeed(user.data(), user.size_bytes(), hash);
        const auto flat = vs.FlatUserData();
        hash = XXH3_64bits_withSeed(flat.data(), flat.size_bytes(), hash);
        for (const auto& resource : vs.buffers) {
            if (!known) {
                break;
            }
            if (resource.buffer_type == Shader::BufferType::Flatbuf) {
                continue; // its words are the flat user data, hashed above
            }
            if (resource.IsSpecial() || resource.is_written) {
                known = false;
                break;
            }
            const auto buffer = resource.GetSharp(vs);
            const u32 size = buffer.GetSize();
            if (!buffer.Valid() || size == 0) {
                continue; // a null buffer reads zeros
            }
            if (!memory->IsValidGpuMapping(buffer.base_address, 0) ||
                memory->ClampRangeSize(buffer.base_address, size) != size ||
                buffer_cache.IsRegionGpuModified(buffer.base_address, size)) {
                known = false;
                break;
            }
            hash = XXH3_64bits_withSeed(reinterpret_cast<const void*>(buffer.base_address), size, hash);
        }
        if (known && fetch) {
            for (const auto& attribute : fetch->attributes) {
                const auto buffer = attribute.GetSharp(vs);
                if (buffer.Valid() && buffer.GetSize() != 0 &&
                    buffer_cache.IsRegionGpuModified(buffer.base_address, buffer.GetSize())) {
                    known = false;
                    break;
                }
            }
        }
        draw.inputs = known ? (hash ? hash : 1) : 0;
    }
    BbSections::Scope prepare_scope{BbSections::RtPrepare};
    const u32 param = rt_shadow->PrepareDraw(draw);
    prepare_scope.End();
    if (mode == Shader::MotionVectors::VertexBoth) {
        dc.push_data.motion_param |= param << 16;
    } else {
        dc.push_data.motion_param = param;
    }
}

vk::Rect2D Rasterizer::EffectTile(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline,
                                   bool is_indexed, u32 index_offset, u32 first_vertex) const {
    auto& dc = Dc();
    const vk::Rect2D scissor = DrawScissor(0);
    const auto& fetch = pipeline->GetFetchShader();
    const auto& v = dc.vertex_binds;
    const auto position =
        std::ranges::find(v.attributes, 0u, &vk::VertexInputAttributeDescription2EXT::location);
    if (!fetch || position == v.attributes.end() || position->binding >= v.num_buffers) {
        return scissor;
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    VAddr base = 0;
    u32 stride = 0;
    for (const auto& attribute : fetch->attributes) {
        if (attribute.semantic == 0) {
            const auto sharp = attribute.GetSharp(vs);
            base = sharp.base_address;
            stride = sharp.GetStride();
        }
    }
    if (!base || stride < 16) {
        return scissor;
    }
    const u32 index_size = regs.index_buffer_type.index_type == AmdGpu::IndexType::Index16 ? 2u : 4u;
    const VAddr indices =
        is_indexed ? regs.index_base_address.Address<VAddr>() + u64(index_offset) * index_size : 0;
    if (is_indexed && (!memory->IsValidGpuMapping(indices, 0) ||
                       memory->ClampRangeSize(indices, 4 * index_size) != 4 * index_size)) {
        return scissor;
    }
    const auto& vp = regs.viewports[0];
    float lo_x = 1e30f, lo_y = 1e30f, hi_x = -1e30f, hi_y = -1e30f;
    for (u32 i = 0; i < 4; ++i) {
        u32 index = i;
        if (is_indexed) {
            index = index_size == 2
                        ? reinterpret_cast<const u16*>(indices)[i]
                        : reinterpret_cast<const u32*>(indices)[i];
        }
        const VAddr at = base + u64(s64(index) + s64(s32(first_vertex))) * stride + position->offset;
        if (!memory->IsValidGpuMapping(at, 0) || memory->ClampRangeSize(at, 16) != 16) {
            return scissor;
        }
        const auto* p = reinterpret_cast<const float*>(at);
        if (!std::isfinite(p[0]) || !std::isfinite(p[1]) || !std::isfinite(p[3]) ||
            std::abs(p[3]) < 1e-8f) {
            return scissor;
        }
        const float x = p[0] / p[3] * (vp.xscale * target_scale[0]) +
                        (vp.xoffset * target_scale[0] + target_offset[0]);
        const float y = p[1] / p[3] * (vp.yscale * target_scale[1]) +
                        (vp.yoffset * target_scale[1] + target_offset[1]);
        lo_x = std::min(lo_x, x);
        lo_y = std::min(lo_y, y);
        hi_x = std::max(hi_x, x);
        hi_y = std::max(hi_y, y);
    }
    const s32 x0 = std::max(s32(std::floor(lo_x)), scissor.offset.x);
    const s32 y0 = std::max(s32(std::floor(lo_y)), scissor.offset.y);
    const s32 x1 = std::min(s32(std::ceil(hi_x)), scissor.offset.x + s32(scissor.extent.width));
    const s32 y1 = std::min(s32(std::ceil(hi_y)), scissor.offset.y + s32(scissor.extent.height));
    if (x1 <= x0 || y1 <= y0) {
        return scissor;
    }
    return {.offset = {x0, y0}, .extent = {u32(x1 - x0), u32(y1 - y0)}};
}

void Rasterizer::EffectsBeforeBind(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline,
                                   bool is_indexed, u32 index_offset, u32 first_vertex) {
    auto& dc = Dc();
    if (!pipeline->GetGraphicsKey().mrt_mask) {
        return;
    }
    const u64 hash = FragmentHash(pipeline);
    const u32 tile_lights = PointLightCount(hash);
    if (tile_lights != 0) {
        effect_tile = EffectTile(regs, pipeline, is_indexed, index_offset, first_vertex);
        if (point_shadow->Tracing()) {
            const vk::Rect2D scissor = DrawScissor(0);
            std::printf("Lamp trace: lamp vs %08llx ps %08llx mrt %#x, %u vertices%s, %u instances",
                        (unsigned long long)pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,
                        (unsigned long long)hash, u32(pipeline->GetGraphicsKey().mrt_mask),
                        regs.num_indices, is_indexed ? " indexed" : "",
                        regs.num_instances.NumInstances());
            for (int i = 0; i < 2; ++i) {
                const auto& blend = regs.blend_control[i];
                std::printf(", blend%d %u (%u %u %u) alpha %u (%u %u %u)", i, u32(blend.enable),
                            u32(blend.color_src_factor), u32(blend.color_func),
                            u32(blend.color_dst_factor), u32(blend.separate_alpha_blend),
                            u32(blend.alpha_src_factor), u32(blend.alpha_func),
                            u32(blend.alpha_dst_factor));
            }
            std::printf(", write mask %#x, color mode %u, depth test %u write %u func %u, stencil "
                        "%u, scissor %d,%d %ux%u, tile %d,%d %ux%u\n",
                        u32(regs.color_target_mask.raw), u32(regs.color_control.mode),
                        u32(regs.depth_control.depth_enable),
                        u32(regs.depth_control.depth_write_enable),
                        u32(regs.depth_control.depth_func), u32(regs.depth_control.stencil_enable),
                        scissor.offset.x, scissor.offset.y, scissor.extent.width,
                        scissor.extent.height, effect_tile.offset.x, effect_tile.offset.y,
                        effect_tile.extent.width, effect_tile.extent.height);
        }
    } else if (point_shadow->EndingUncounted()) {
        // Statistics only: a quad of the light grid has its tile, any other draw its scissor.
        const bool grid =
            pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash == PointGridVertexShaderHash;
        if (point_shadow->Tracing()) {
            const auto& ps = pipeline->GetStage(Shader::SwStage::Fragment);
            const auto& blend = regs.blend_control[0];
            const vk::Rect2D scissor = DrawScissor(0);
            std::printf("Lamp trace: ending draw vs %08llx, %u vertices%s, %zu buffers",
                        (unsigned long long)pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,
                        regs.num_indices, is_indexed ? " indexed" : "", ps.buffers.size());
            for (const auto& buffer : ps.buffers) {
                std::printf(" %u", buffer.IsSpecial() ? 0u : buffer.GetSharp(ps).GetSize());
            }
            std::printf(", %zu images, blend %u (%u %u %u), depth test %u write %u func %u, "
                        "stencil %u, scissor %d,%d %ux%u\n",
                        ps.images.size(), u32(blend.enable), u32(blend.color_src_factor),
                        u32(blend.color_func), u32(blend.color_dst_factor),
                        u32(regs.depth_control.depth_enable),
                        u32(regs.depth_control.depth_write_enable),
                        u32(regs.depth_control.depth_func), u32(regs.depth_control.stencil_enable),
                        scissor.offset.x, scissor.offset.y, scissor.extent.width,
                        scissor.extent.height);
        }
        point_shadow->EndingDraw(grid ? EffectTile(regs, pipeline, is_indexed, index_offset,
                                                   first_vertex)
                                      : DrawScissor(0));
    }
    static_assert(offsetof(Shader::PushData, motion_param) == 120);
    static_assert(offsetof(Shader::PushData, scene_size) == 124);
    if (hash == EffectShaders::SsaoHash) {
        if (EffectShaders::GtaoActive()) {
            const float k = std::clamp(
                BbSettings::Get().graphics_ao_strength.load(std::memory_order_relaxed), 0.0f, 1.0f);
            // gtao.frag reads ao_k >= 2 as graphics_smooth_normals.
            const bool smooth =
                BbSettings::Get().graphics_smooth_normals.load(std::memory_order_relaxed);
            dc.push_data.motion_param = std::bit_cast<u32>(k + (smooth ? 2.0f : 0.0f));
        }
    } else if (hash == EffectShaders::SsrHash) {
        if (EffectShaders::SsrActive() && cb_descs[0].first) {
            dc.push_data.motion_param = ssr_frame;
            SsrTemporal::TraceInputs inputs{.frame_index = ssr_frame};
            if (!dc.buffer_infos.empty() && dc.buffer_infos[0].buffer && dc.image_infos.size() == 6) {
                inputs.constants = dc.buffer_infos[0].buffer;
                inputs.constants_offset = dc.buffer_infos[0].offset;
                inputs.constants_range = dc.buffer_infos[0].range;
                inputs.constants_dword_offset = PackedOffsets(dc.push_data);
                inputs.normals_view = dc.image_infos[1].imageView;
                inputs.normals_layout = dc.image_infos[1].imageLayout;
                inputs.color_view = dc.image_infos[2].imageView;
                inputs.color_layout = dc.image_infos[2].imageLayout;
            }
            effect_skip_draw = ssr_temporal->OnSsrDraw(cb_descs[0].first, inputs);
            ++ssr_frame;
        }
    } else if (hash == ShadowBlurHash) {
        if (cb_descs[0].first) {
            const auto& blur = pipeline->GetStage(Shader::SwStage::Fragment);
            contact_shadow->OnBlurDraw(
                cb_descs[0].first, blur.images.empty() ? 0 : blur.images[0].GetSharp(blur).Address());
        }
    } else if (hash == ShadowResolveHash) {
        if (cb_descs[0].first && !dc.buffer_infos.empty() && dc.buffer_infos[0].buffer) {
            const bool has_ubo = dc.buffer_infos.size() > 1 && dc.buffer_infos[1].buffer;
            const bool has_map = dc.image_infos.size() > 1 && dc.image_infos[1].imageView;
            contact_shadow->OnShadowDraw(
                cb_descs[0].first,
                {.constants = dc.buffer_infos[0].buffer,
                 .constants_offset = dc.buffer_infos[0].offset,
                 .constants_range = dc.buffer_infos[0].range,
                 .uniforms = has_ubo ? dc.buffer_infos[1].buffer : vk::Buffer{},
                 .uniforms_offset = has_ubo ? dc.buffer_infos[1].offset : 0,
                 .uniforms_range = has_ubo ? dc.buffer_infos[1].range : 0,
                 .shadow_map = has_map ? dc.image_infos[1].imageView : vk::ImageView{},
                 .shadow_layout = has_map ? dc.image_infos[1].imageLayout : vk::ImageLayout::eUndefined,
                 .constants_offset_word = PackedOffsets(dc.push_data),
                 .frame_index = shadow_frame++});
        }
    } else if (tile_lights != 0) {
        const auto& ps = pipeline->GetStage(Shader::SwStage::Fragment);
        if ((pipeline->GetGraphicsKey().mrt_mask & 3) == 3 && cb_descs[0].first &&
            cb_descs[1].first && ps.buffers.size() >= 2 && !ps.buffers[0].IsSpecial() &&
            !ps.buffers[1].IsSpecial()) {
            const VAddr constants = ps.buffers[0].GetSharp(ps).base_address;
            const VAddr lights = ps.buffers[1].GetSharp(ps).base_address;
            const u64 light_bytes = u64(tile_lights) * 64;
            if (memory->IsValidGpuMapping(constants, 0) && memory->ClampRangeSize(constants, 64) == 64 &&
                memory->IsValidGpuMapping(lights, 0) &&
                memory->ClampRangeSize(lights, light_bytes) == light_bytes) {
                // Lamps apart (vk_point_shadow.h): the light grid's quad, which only adds to its
                // two targets and whose scissor is its tile.
                const bool adds_in_tile =
                    pipeline->GetGraphicsKey().mrt_mask == 3 && AddsLight(regs, 0) &&
                    AddsLight(regs, 1) && effect_plain_pair && !ui_pass.active &&
                    !attachment_feedback_loop && pipeline->GetGraphicsKey().num_samples <= 1 &&
                    DrawScissor(0) == effect_tile &&
                    pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash ==
                        PointGridVertexShaderHash;
                point_shadow->OnLightDraw(cb_descs[0].first, cb_descs[1].first,
                                          {.constants = reinterpret_cast<const u32*>(constants),
                                           .lights = reinterpret_cast<const u32*>(lights),
                                           .count = tile_lights,
                                           .tile = effect_tile,
                                           .adds_in_tile = adds_in_tile,
                                           .pass = effect_pass});
            }
        }
    } else if (hash == EffectShaders::SsrCompositeHash && EffectShaders::SsrCompositeActive()) {
        const float intensity =
            BbSettings::Get().graphics_ssr_intensity.load(std::memory_order_relaxed);
        dc.push_data.motion_param =
            std::bit_cast<u32>(std::clamp(std::isfinite(intensity) ? intensity : 1.0f, 0.0f, 3.0f));
        if (const auto full = ssr_temporal->FullResult(); full && dc.image_infos.size() == 12) {
            dc.image_infos[6].imageView = full;
            dc.image_infos[6].imageLayout = vk::ImageLayout::eGeneral;
        }
    }
}

// bbport: graphics_ao_quality=1 (vk_ao_spatial.h). The GTAO gather (the HQ variant of gtao.frag)
// is denoised in place; the draw right after it is the game's bilateral upscale to the internal
// resolution (R8, sampling the gather and the full-resolution depth), whose output HQ AO
// recomputed at that resolution replaces.
void Rasterizer::HqAoAfterDraw(const GraphicsPipeline* pipeline, const RenderState& state) {
    auto& dc = Dc();
    const auto* ps_info = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    const auto& dynamic = scheduler.GetDynamicState();
    const auto draw_region = [&]() -> std::optional<vk::Rect2D> {
        if (dynamic.scissors.size() != 1 || dynamic.viewports.size() != 1) {
            return std::nullopt;
        }
        const auto& vp = dynamic.viewports[0];
        const auto& scissor = dynamic.scissors[0];
        const s32 left =
            std::max(scissor.offset.x, s32(std::ceil(std::min(vp.x, vp.x + vp.width))));
        const s32 top =
            std::max(scissor.offset.y, s32(std::ceil(std::min(vp.y, vp.y + vp.height))));
        const s32 right = std::min<s32>(
            state.width, std::min<s32>(scissor.offset.x + s32(scissor.extent.width),
                                       s32(std::floor(std::max(vp.x, vp.x + vp.width)))));
        const s32 bottom = std::min<s32>(
            state.height, std::min<s32>(scissor.offset.y + s32(scissor.extent.height),
                                        s32(std::floor(std::max(vp.y, vp.y + vp.height)))));
        return vk::Rect2D{{left, top},
                          {u32(std::max(right - left, 0)), u32(std::max(bottom - top, 0))}};
    };
    if (spatial_ao->UpscalePending()) {
        const auto gather = spatial_ao->GatherTarget();
        s32 depth_index = -1;
        bool reads_gather = false;
        // bound_images lists the render target first, then the sampled images in binding order.
        if (ps_info && cb_descs[0].first && state.num_color_attachments == 1 &&
            state.num_layers == 1 && ps_info->images.size() == 2 &&
            ps_info->buffers.size() == 2 && dc.bound_images.size() == 3 &&
            dc.bound_images[0] == cb_descs[0].first && dc.image_infos.size() >= 2 &&
            dc.buffer_infos.size() >= 2) {
            for (s32 i = 0; i < 2; ++i) {
                const auto id = dc.bound_images[i + 1];
                if (id == gather) {
                    reads_gather = true;
                } else if (texture_cache.GetImage(id).info.pixel_format ==
                           vk::Format::eR32Sfloat) {
                    depth_index = i;
                }
            }
        }
        const auto region = draw_region();
        if (reads_gather && depth_index >= 0 && region && region->offset.x == 0 &&
            region->offset.y == 0 && region->extent.width == state.width &&
            region->extent.height == state.height) {
            const float k = std::clamp(
                BbSettings::Get().graphics_ao_strength.load(std::memory_order_relaxed), 0.0f,
                1.0f);
            const u32 offsets = u32(dc.push_data.buf_offsets[0]) | (u32(dc.push_data.buf_offsets[1]) << 8);
            spatial_ao->FullResolution(cb_descs[0].first, cb_descs[0].second.view_info,
                                       dc.image_infos[depth_index], dc.buffer_infos[0],
                                       dc.buffer_infos[1], offsets, k);
        } else {
            spatial_ao->SkipUpscale(fmt::format(
                "next draw: colors={} ps_images={} ps_buffers={} bound={} gather={} depth={} "
                "region={}",
                state.num_color_attachments, ps_info ? ps_info->images.size() : 0,
                ps_info ? ps_info->buffers.size() : 0, dc.bound_images.size(), reads_gather,
                depth_index,
                region ? fmt::format("{},{} {}x{} of {}x{}", region->offset.x, region->offset.y,
                                     region->extent.width, region->extent.height, state.width,
                                     state.height)
                       : std::string{"none"}));
        }
    }
    if (!ps_info || ps_info->pgm_hash != EffectShaders::SsaoHash || !EffectShaders::GtaoActive()) {
        return;
    }
    // Descriptors are appended per stage with the fragment stage first, so its Cb0 and normals
    // stay at the front while other stages may append their own buffers.
    if (cb_descs[0].first && state.num_color_attachments == 1 && state.num_layers == 1 &&
        ps_info->buffers.size() == 3 && ps_info->images.size() == 3 &&
        dc.buffer_infos.size() >= 3 && dc.image_infos.size() >= 6 && dynamic.scissors.size() == 1 &&
        dynamic.viewports.size() == 1) {
        const auto region = *draw_region();
        if (region.extent.width && region.extent.height) {
            spatial_ao->Filter(cb_descs[0].first, cb_descs[0].second.view_info, dc.image_infos[1],
                               dc.buffer_infos[0], dc.push_data.buf_offsets[0], dc.push_data.scene_size,
                               state.width, state.height, region);
            spatial_ao->NoteGather(cb_descs[0].first, dc.image_infos[1]);
        } else {
            spatial_ao->WarnUnsupported(fmt::format("empty region {},{} {}x{}", region.offset.x,
                                                    region.offset.y, region.extent.width,
                                                    region.extent.height));
        }
    } else {
        spatial_ao->WarnUnsupported(fmt::format(
            "cb={} colors={} layers={} ps_buffers={} ps_images={} images={} buffers={} "
            "scissors={} viewports={}",
            bool(cb_descs[0].first), state.num_color_attachments, state.num_layers,
            ps_info->buffers.size(), ps_info->images.size(), dc.image_infos.size(),
            dc.buffer_infos.size(), dynamic.scissors.size(), dynamic.viewports.size()));
    }
}

void Rasterizer::EffectsAfterDraw(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline, bool is_indexed,
                                  u32 num_indices, u32 num_instances, u32 first_vertex) {
    auto& dc = Dc();
    if (!effects_wanted) {
        return;
    }
    const auto* ps_info = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    if (!ps_info) {
        return;
    }
    const auto& vs_info = pipeline->GetStage(Shader::SwStage::Vertex);
    const u64 hash = ps_info->pgm_hash;
    if (hash == DofRecombinePixelShaderHash) {
        if (cb_descs[0].first && vs_info.pgm_hash == DofRecombineVertexShaderHash &&
            ps_info->images.size() == 2 && dc.image_infos.size() >= 2) {
            froyok_bloom->Generate(cb_descs[0].first);
        }
        return;
    }
    if (hash == ShadowResolveHash && cb_descs[0].first && dc.buffer_infos.size() >= 2 &&
        dc.image_infos.size() >= 2) {
        SunAtlasResolve(*ps_info);
        // Cascades left out since the last resolve are not marched through (SunAtlasSkipDraw).
        volumetric_light->SetAtlasCascades(
            sun_atlas.skipped_mask ? u32(std::countr_zero(sun_atlas.skipped_mask)) : 4u);
        sun_atlas.skipped_mask = 0;
        volumetric_light->Integrate(cb_descs[0].first, dc.image_infos[0],
                                    {.constants = dc.buffer_infos[0].buffer,
                                     .constants_offset = dc.buffer_infos[0].offset,
                                     .constants_range = dc.buffer_infos[0].range,
                                     .uniforms = dc.buffer_infos[1].buffer,
                                     .uniforms_offset = dc.buffer_infos[1].offset,
                                     .uniforms_range = dc.buffer_infos[1].range,
                                     .shadow_map = dc.image_infos[1].imageView,
                                     .shadow_layout = dc.image_infos[1].imageLayout,
                                     .constants_offset_word = PackedOffsets(dc.push_data)});
        sun_atlas.reach = volumetric_light->AtlasReach();
    } else if (hash == DirectionalFragmentShaderHash && !dc.buffer_infos.empty()) {
        volumetric_light->Tint(dc.buffer_infos[0], dc.push_data.buf_offsets[0] & 255u);
    } else if (const u32 count = PointLightCount(hash);
               count != 0 && (pipeline->GetGraphicsKey().mrt_mask & 3) == 3 && cb_descs[0].first &&
               cb_descs[1].first && dc.buffer_infos.size() >= 2) {
        if (vs_info.pgm_hash != PointGridVertexShaderHash || ps_info->buffers.size() < 2 ||
            ps_info->buffers[0].IsSpecial() || ps_info->buffers[1].IsSpecial()) {
            return;
        }
        const VAddr constants = ps_info->buffers[0].GetSharp(*ps_info).base_address;
        const VAddr lights = ps_info->buffers[1].GetSharp(*ps_info).base_address;
        const u64 light_bytes = u64(count) * 64;
        if (memory->IsValidGpuMapping(constants, 0) && memory->ClampRangeSize(constants, 64) == 64 &&
            memory->IsValidGpuMapping(lights, 0) &&
            memory->ClampRangeSize(lights, light_bytes) == light_bytes) {
            volumetric_light->AddPointLights(reinterpret_cast<const u32*>(constants),
                                             reinterpret_cast<const u32*>(lights), count);
        }
    } else if (hash == SceneTargetHash && cb_descs[0].first) {
        volumetric_light->Scene(cb_descs[0].first);
    }
}

// bbport: the game's sun shadow atlas (four cascades in the quadrants of a square depth image,
// drawn by ps a2108f5e) while the ray traced sun or the VSM replaces the game's sun shadow. Its
// readers then are the game's resolve f55643de, whose RGB is packed camera depth and whose alpha
// RtShadow's filter overwrites on every pixel with 0 < depth < 1 (at the sky the game's alpha is 1
// whatever the atlas holds: the shadow distance fades it out), and the volumetric sunlight, which
// marches to its reach and so selects only the cascades starting nearer than that. PCSS and
// contact shadows are off while the sun is ray traced. Draws into the other cascades that store
// no ray tracing capture are left out; the capture's draws still run. Experiment 8192: all drawn.
namespace {
constexpr u32 SunAtlasSteadyFrames = 8; ///< frames replaced in a row before any is left out
/// bbport (r12_atlas_skip_live): set = as before (the session-long reader latch, every colour
/// slot counted as a colour target, no water queries).
constexpr u64 SunAtlasLiveOffBit = 549755813888ull;
constexpr u64 SunWaterPsHash = 0xe3021062ull; ///< the game's water surface (vk_effect_shaders.cpp)
/// BB_SUN_ATLAS_IGNORE_READER=1 (diagnostic): every other reader of the atlas counts as absent.
bool SunAtlasIgnoreReader() {
    static const bool ignore = [] {
        const char* value = std::getenv("BB_SUN_ATLAS_IGNORE_READER");
        return value && value[0] == '1';
    }();
    return ignore;
}
}

void Rasterizer::SunAtlasResolve(const Shader::Info& ps) {
    auto& a = sun_atlas;
    a.resolved = true;
    if (ps.images.size() < 2 || ps.buffers.size() < 2 || ps.buffers[0].IsSpecial() ||
        ps.buffers[1].IsSpecial()) {
        a.address = 0;
        return;
    }
    a.address = ps.images[1].GetSharp(ps).Address();
    // The guest shader reads its constants from the V# base: dword i is at base + 4 i.
    const VAddr splits = ps.buffers[0].GetSharp(ps).base_address + 80 * sizeof(float);
    const VAddr coverage = ps.buffers[1].GetSharp(ps).base_address + 72 * sizeof(float);
    a.splits_valid = false;
    if (memory->IsValidGpuMapping(splits, 0) &&
        memory->ClampRangeSize(splits, 3 * sizeof(float)) == 3 * sizeof(float)) {
        std::memcpy(a.splits.data(), reinterpret_cast<const void*>(splits), 3 * sizeof(float));
        a.splits_valid = std::isfinite(a.splits[0]) && std::isfinite(a.splits[2]) &&
                         a.splits[0] > 0.0f && a.splits[0] < a.splits[1] &&
                         a.splits[1] < a.splits[2];
    }
    // Shadow distance (uniforms 72) and fade rate (73): coverage = clamp(rate * (distance - |p|)),
    // 0 beyond the distance only when the rate is positive.
    a.coverage = 0.0f;
    if (memory->IsValidGpuMapping(coverage, 0) &&
        memory->ClampRangeSize(coverage, 2 * sizeof(float)) == 2 * sizeof(float)) {
        std::array<float, 2> fade{};
        std::memcpy(fade.data(), reinterpret_cast<const void*>(coverage), 2 * sizeof(float));
        a.coverage = fade[1] > 0.0f && std::isfinite(fade[0]) ? fade[0] : 0.0f;
    }
}

bool Rasterizer::SunAtlasSkipDraw(const GraphicsPipeline* pipeline, const RenderState& state) {
    auto& a = sun_atlas;
    sun_reader.measure_now = false; // r12: set below for a water draw, taken by its query
    if (!a.address) {
        return false;
    }
    auto& dc = Dc();
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    const u64 ps_hash = ps ? ps->pgm_hash : 0;
    const bool live = !BbToggle::Experiment(SunAtlasLiveOffBit); // r12
    // bbport (r19_draw-cost): with the sun neither ray traced nor a VSM (ray tracing off) nothing
    // below returns true (the live skip needs SunWanted()); the rest is r7/r12 bookkeeping read
    // only by the 600-frame report or on the SunWanted() path (sun_reader.cleared, reset at every
    // frame end). Not while r7's kept cascades run, nor on r7's pass log frames.
    if (live && !a.pass_log && !sun_hold.active && !BbToggle::Experiment(R19DrawCostOffBit) &&
        !rt_shadow->SunWanted()) {
        ++r19_stats.sun_short;
        return false;
    }
    if (live) {
        // r12: every draw sampling the atlas, each time (the water is measured, not latched).
        if (ps_hash != ShadowResolveHash && rt_shadow->SunWanted() &&
            SunAtlasLiveReader(pipeline, state, ps_hash)) {
            return false;
        }
    } else if (a.other_reader) {
        // r7: the other reader's draws, known by their shaders once it is found.
        if (ps_hash != 0 && ps_hash == a.reader_ps &&
            pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash == a.reader_vs) {
            ++a.reader_draws;
        }
    } else if (ps_hash != ShadowResolveHash) {
        // Any other draw sampling the atlas (bindings are still set: ResetBindings comes after).
        for (const VideoCore::ImageId id : dc.bound_images) {
            const auto& image = texture_cache.GetImage(id);
            if (!image.binding.is_target && image.info.guest_address == a.address) {
                a.other_reader = true;
                std::printf("Sun atlas: also sampled by the draw vs %016llx ps %016llx; every "
                            "cascade is drawn from now on\n",
                            (unsigned long long)pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,
                            (unsigned long long)ps_hash);
                a.reader_vs = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
                a.reader_ps = ps_hash;
                ++a.reader_draws;
                SunAtlasDescribeReader(pipeline, state);
                return false;
            }
        }
    }
    if (!db_desc.first || texture_cache.GetImage(db_desc.first).info.guest_address != a.address) {
        return false;
    }
    // r7: every draw into the atlas, whatever is left out: its render pass, whether that pass
    // begins with a clear (load op clear: the whole image, Scheduler::BeginRendering) or the draw
    // is a DB clear, and whether it repeats the previous atlas draw's pipeline.
    const u64 pass = scheduler.PassesBegun();
    const bool new_pass = pass != a.last_pass;
    a.last_pass = pass;
    // r14: a clear taken over by kept quadrants (SunKeepBeforePass) is still the frame's clear: the
    // quadrant of a draw left out below was cleared before it (SunKeepInPass ran first).
    const bool load_clear =
        new_pass && (state.depth_stencil_attachment.depth_clear || pass == sun_keep.clear_pass);
    if (load_clear) { // r12: this image was cleared whole this frame
        sun_reader.cleared = true;
        sun_reader.cleared_image = db_desc.first;
    }
    const bool clear_draw = Regs().depth_render_control.depth_clear_enable != 0;
    ++a.atlas_draws;
    a.atlas_passes += new_pass ? 1u : 0u;
    a.clear_passes += load_clear ? 1u : 0u;
    a.clear_draws += clear_draw ? 1u : 0u;
    a.same_pipeline += pipeline == a.last_pipeline ? 1u : 0u;
    a.last_pipeline = pipeline;
    const auto& dynamic = scheduler.GetDynamicState();
    const auto note = [&](u32 code) {
        if (!a.pass_log) {
            return;
        }
        if (new_pass) {
            a.note_open = a.pass_count < a.pass_notes.size();
            if (a.note_open) {
                auto& n = a.pass_notes[a.pass_count++];
                n = {};
                n.cascade = u8(code);
                if (!dynamic.viewports.empty()) {
                    const vk::Viewport& v = dynamic.viewports[0];
                    n.x = s16(std::min(v.x, v.x + v.width));
                    n.y = s16(std::min(v.y, v.y + v.height));
                    n.w = u16(std::abs(v.width));
                    n.h = u16(std::abs(v.height));
                }
            }
        }
        if (!a.note_open) {
            return;
        }
        auto& n = a.pass_notes[a.pass_count - 1];
        n.clear |= u8((load_clear ? 1u : 0u) | (clear_draw ? 2u : 0u));
        n.draws = u16(std::min<u32>(u32(n.draws) + 1u, 65535u));
        n.cascade = n.cascade == u8(code) ? n.cascade : u8(6);
    };
    // The cascade: the quadrant holding the draw's viewport and scissor.
    if (dynamic.viewports.size() != 1 || dynamic.scissors.size() != 1 || state.width == 0 ||
        state.height == 0) {
        ++a.no_viewport;
        note(5);
        return false;
    }
    const vk::Viewport& vp = dynamic.viewports[0];
    const vk::Rect2D& sc = dynamic.scissors[0];
    const float left = std::max(float(sc.offset.x), std::min(vp.x, vp.x + vp.width));
    const float top = std::max(float(sc.offset.y), std::min(vp.y, vp.y + vp.height));
    const float right = std::min(float(sc.offset.x) + float(sc.extent.width),
                                 std::max(vp.x, vp.x + vp.width));
    const float bottom = std::min(float(sc.offset.y) + float(sc.extent.height),
                                  std::max(vp.y, vp.y + vp.height));
    const float half_w = 0.5f * float(state.width), half_h = 0.5f * float(state.height);
    if (!(right > left && bottom > top)) {
        ++a.no_viewport;
        note(5);
        return false;
    }
    const bool east = left >= half_w, south = top >= half_h;
    if ((!east && right > half_w) || (!south && bottom > half_h)) {
        ++a.spanning;
        note(4);
        return false; // more than one cascade
    }
    const u32 cascade = (east ? 1u : 0u) | (south ? 2u : 0u);
    ++a.cascade_draws[cascade];
    a.drawn_mask |= 1u << cascade;
    note(cascade);
    SunAtlasLight(pipeline, cascade, std::abs(vp.width), std::abs(vp.height));
    if (live) {
        // r12: colour targets are slots with an image (every atlas pass has one slot without:
        // "pass 4096x4096 [- ]"). Never before this frame's clear of the whole image (a left-out
        // quadrant then holds the clear value: no shadow, never an older frame's casters), nor a
        // DB clear draw, nor while r7's kept cascades are active (they narrow that clear).
        auto& r = sun_reader;
        if (r.latched || cascade < a.skip_from || BbToggle::Experiment(8192) ||
            !rt_shadow->SunWanted() || sun_hold.active) {
            return false;
        }
        u32 colour_targets = 0;
        for (u32 i = 0; i < state.num_color_attachments && i < state.color_attachments.size();
             ++i) {
            colour_targets += state.color_attachments[i].image_view ? 1u : 0u;
        }
        if (colour_targets != 0) {
            ++r.colour_kept;
            return false;
        }
        if (clear_draw || !r.cleared || db_desc.first != r.cleared_image) {
            ++r.clear_kept;
            return false;
        }
        if (dc.motion_draw) {
            ++r.motion_kept;
            return false;
        }
        if (dc.capture_draw && dc.push_data.motion_param != 0) {
            ++r.capture_kept[cascade]; // stores ray tracing geometry this frame: it runs
            return false;
        }
    } else if (a.other_reader || cascade < a.skip_from || state.num_color_attachments != 0 ||
        dc.motion_draw ||
        (dc.capture_draw && dc.push_data.motion_param != 0) || BbToggle::Experiment(8192) ||
        !rt_shadow->SunWanted()) {
        return false;
    }
    ++a.cascade_skipped[cascade];
    a.skipped_mask |= 1u << cascade;
    a.any_skipped = true;
    return true;
}

// r7: the light matrix of the first draw of each cascade in a frame (and, on 1 frame in 64, of
// every draw, compared with the first): the shadow pass's 864-byte vertex constants, projection
// (4x4 rows) at dword 52 and view to world (3x4 rows) at dword 180, as RtShadow::ToWorld reads them.
void Rasterizer::SunAtlasLight(const GraphicsPipeline* pipeline, u32 cascade, float width,
                               float height) {
    auto& a = sun_atlas;
    const bool first = ((a.light_mask >> cascade) & 1u) == 0;
    if (!first && !a.check_frame) {
        return;
    }
    std::array<float, 28> m{};
    bool found = false;
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    for (const auto& resource : vs.buffers) {
        if (resource.IsSpecial()) {
            continue;
        }
        const auto buffer = resource.GetSharp(vs);
        if (!buffer.Valid() || buffer.GetSize() != 864 ||
            !memory->IsValidGpuMapping(buffer.base_address, 0) ||
            memory->ClampRangeSize(buffer.base_address, 864) != 864) {
            continue;
        }
        const auto* data = reinterpret_cast<const float*>(buffer.base_address);
        std::memcpy(m.data(), data + 52, 16 * sizeof(float));
        std::memcpy(m.data() + 16, data + 180, 12 * sizeof(float));
        found = true;
        break;
    }
    if (!found) {
        ++a.no_constants;
        return;
    }
    if (first) {
        a.light_mask |= 1u << cascade;
        a.light[cascade] = {m, width, height, true};
    } else {
        auto& s = a.light_stats[cascade];
        ++s.checked;
        s.other_matrix += std::memcmp(m.data(), a.light[cascade].m.data(), sizeof(m)) != 0 ? 1u : 0u;
    }
}

// r7: printed once, when the other reader is found.
void Rasterizer::SunAtlasDescribeReader(const GraphicsPipeline* pipeline, const RenderState& state) {
    const auto& a = sun_atlas;
    const auto& regs = Regs();
    const u32 mrt = pipeline->GetGraphicsKey().mrt_mask;
    std::string text;
    for (u32 i = 0; i < 8; ++i) {
        if (((mrt >> i) & 1u) == 0 || !cb_descs[i].first) {
            continue;
        }
        const auto& image = texture_cache.GetImage(cb_descs[i].first);
        const auto& blend = regs.blend_control[i];
        text += fmt::format(" colour {}: {} {}x{} at {:#x}, blend {} (src {} func {} dst {});", i,
                            vk::to_string(image.info.pixel_format), image.info.size.width,
                            image.info.size.height, image.info.guest_address, u32(blend.enable),
                            u32(blend.color_src_factor), u32(blend.color_func),
                            u32(blend.color_dst_factor));
    }
    if (db_desc.first) {
        const auto& depth = texture_cache.GetImage(db_desc.first);
        text += fmt::format(" depth {} {}x{} at {:#x} (test {} write {} func {});",
                            vk::to_string(depth.info.pixel_format), depth.info.size.width,
                            depth.info.size.height, depth.info.guest_address,
                            u32(regs.depth_control.depth_enable),
                            u32(regs.depth_control.depth_write_enable),
                            u32(regs.depth_control.depth_func));
    }
    // Which image is the atlas; which constant buffers hold the resolve's splits (constants 80..82).
    const auto stage = [&](const Shader::Info& info, const char* name) {
        for (std::size_t i = 0; i < info.images.size(); ++i) {
            if (info.images[i].GetSharp(info).Address() == a.address) {
                text += fmt::format(" {} image {} of {} is the atlas;", name, i, info.images.size());
            }
        }
        if (!a.splits_valid) {
            return;
        }
        for (std::size_t i = 0; i < info.buffers.size(); ++i) {
            const auto& resource = info.buffers[i];
            if (resource.IsSpecial()) {
                continue;
            }
            const auto buffer = resource.GetSharp(info);
            const u32 size = std::min<u32>(buffer.GetSize(), 16384u);
            if (!buffer.Valid() || size < 12 || !memory->IsValidGpuMapping(buffer.base_address, 0) ||
                memory->ClampRangeSize(buffer.base_address, size) != size) {
                continue;
            }
            const auto* words = reinterpret_cast<const float*>(buffer.base_address);
            for (u32 w = 0; w + 3 <= size / 4; ++w) {
                if (words[w] == a.splits[0] && words[w + 1] == a.splits[1] &&
                    words[w + 2] == a.splits[2]) {
                    text += fmt::format(" {} buffer {} ({} bytes) holds the splits at dword {};",
                                        name, i, buffer.GetSize(), w);
                    break;
                }
            }
        }
    };
    stage(pipeline->GetStage(Shader::SwStage::Vertex), "vs");
    if (const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)]) {
        stage(*ps, "ps");
    }
    std::printf("Sun atlas: the other reader draws %ux%u:%s\n", u32(state.width),
                u32(state.height), text.c_str());
}

// A dispatch or an indirect draw (never left out) that samples or writes the atlas. Render
// targets do not count: binding.is_target is set only for a draw's own targets.
void Rasterizer::SunAtlasReader(const char* what, u64 hash) {
    auto& a = sun_atlas;
    // r12: with experiment 549755813888 clear the latch is sun_reader.latched (a latch of
    // other_reader made with the bit set does not carry over); BB_SUN_ATLAS_IGNORE_READER skips it.
    const bool live = !BbToggle::Experiment(SunAtlasLiveOffBit);
    if (!a.address || (live ? sun_reader.latched || SunAtlasIgnoreReader() : a.other_reader)) {
        return;
    }
    for (const VideoCore::ImageId id : Dc().bound_images) {
        const auto& image = texture_cache.GetImage(id);
        if (!image.binding.is_target && image.info.guest_address == a.address) {
            if (live) {
                sun_reader.latched = true;
                std::printf("Sun atlas: also used by %s %016llx; every cascade is drawn from now "
                            "on (r12)\n",
                            what, (unsigned long long)hash);
                return;
            }
            a.other_reader = true;
            std::printf("Sun atlas: also used by %s %016llx; every cascade is drawn from now on\n",
                        what, (unsigned long long)hash);
            return;
        }
    }
}

// bbport (r12_atlas_skip_live): a draw (not the game's resolve) sampling the atlas, found by its
// bound images on every draw. The water (ps e3021062: its vs and ps hold the resolve's splits, so
// it picks a cascade by view depth and may sample any of the four) is measured by an occlusion
// query around each of its draws (DrawRecord, SunAtlasReaderQuery); any other such draw latches.
bool Rasterizer::SunAtlasLiveReader(const GraphicsPipeline* pipeline, const RenderState& state,
                                    u64 ps_hash) {
    auto& a = sun_atlas;
    auto& r = sun_reader;
    bool samples = false;
    for (const VideoCore::ImageId id : Dc().bound_images) {
        const auto& image = texture_cache.GetImage(id);
        if (!image.binding.is_target && image.info.guest_address == a.address) {
            samples = true;
            break;
        }
    }
    if (!samples) {
        return false;
    }
    const u64 vs_hash = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
    if (ps_hash == SunWaterPsHash) {
        ++r.water_draws;
        r.water_now = true;
        r.measure_now = true;
        if (a.reader_ps == 0) {
            a.reader_vs = vs_hash; // the r7 report's "other reader"
            a.reader_ps = ps_hash;
        }
        a.reader_draws += ps_hash == a.reader_ps && vs_hash == a.reader_vs ? 1u : 0u;
        if (!r.water_noted) {
            r.water_noted = true;
            std::printf("Sun atlas: sampled by the water, vs %016llx ps %016llx (r12): its draws "
                        "are measured by occlusion queries; every cascade is drawn while it "
                        "showed samples within the last %llu frames%s\n",
                        (unsigned long long)vs_hash, (unsigned long long)ps_hash,
                        (unsigned long long)SunReader::QuietFrames,
                        SunAtlasIgnoreReader() ? " (BB_SUN_ATLAS_IGNORE_READER=1: ignored)" : "");
            SunAtlasDescribeReader(pipeline, state);
        }
        return true;
    }
    ++r.other_draws;
    if (!r.latched && !SunAtlasIgnoreReader()) {
        r.latched = true;
        std::printf("Sun atlas: also sampled by the draw vs %016llx ps %016llx; every cascade is "
                    "drawn from now on (r12)\n",
                    (unsigned long long)vs_hash, (unsigned long long)ps_hash);
        SunAtlasDescribeReader(pipeline, state);
    }
    return true;
}

// r12: the water draw being recorded gets query `index` of the pool, begun and ended around its
// vkCmdDraw in the same recorded closure (inside its render pass, as vk_occlusion.h's queries; no
// secondary command buffers, so no inherited queries). Not precise: any samples count as seen. A
// draw another query already wraps, or with no free query, counts as seen this frame.
void Rasterizer::SunAtlasReaderQuery(vk::QueryPool& pool, u32& index) {
    auto& r = sun_reader;
    if (!r.measure_now) {
        return;
    }
    r.measure_now = false;
    if (!r.pool_tried) {
        r.pool_tried = true;
        const vk::Device device = instance.GetDevice();
        constexpr u32 count = SunReader::Groups * SunReader::PerGroup;
        if (instance.IsHostQueryResetSupported()) {
            const vk::QueryPoolCreateInfo info = {
                .queryType = vk::QueryType::eOcclusion,
                .queryCount = count,
            };
            auto created = device.createQueryPoolUnique(info);
            if (created.result == vk::Result::eSuccess) {
                r.pool = std::move(created.value);
                device.resetQueryPool(*r.pool, 0, count);
            }
        }
        if (r.pool) {
            std::printf("Sun atlas: water visibility measured by occlusion queries (%u a frame at "
                        "most, any samples count), read without waiting once the GPU is past "
                        "the frame (r12)\n",
                        SunReader::PerGroup);
        } else {
            std::printf("Sun atlas: water visibility not measured (no host query reset or no "
                        "query pool): the water counts as seen whenever it draws (r12)\n");
        }
    }
    if (pool || !r.pool || r.blocked || r.used[r.group] >= SunReader::PerGroup) {
        r.unmeasured_now = true;
        ++r.unmeasured;
        return;
    }
    pool = *r.pool;
    index = r.group * SunReader::PerGroup + r.used[r.group]++;
    ++r.measured;
}

// r12, once a frame (SunAtlasFrameEnd): this frame's queries wait for the GPU to pass the current
// tick; answers of frames the GPU has finished are read (no wait: the tick is free, so every
// query in them is available); the next frame's group is reset from the host once read. The water
// counts as seen in a frame with any samples, with a draw not measured, or while an answer is
// later than MaxLag frames. 'quiet': not seen for QuietFrames frames.
void Rasterizer::SunAtlasQueriesFrameEnd() {
    auto& r = sun_reader;
    const u64 f = ++r.frame_index;
    r.water_frames += r.water_now ? 1u : 0u;
    // Unmeasured water, water drawn again after a frame without it (its answer is still to
    // come), or the old behaviour running (nothing measured): the water counts as seen.
    if (r.unmeasured_now || (r.water_now && !r.water_before) ||
        BbToggle::Experiment(SunAtlasLiveOffBit)) {
        r.last_seen = f;
    }
    r.water_before = r.water_now;
    if (r.pool) {
        const vk::Device device = instance.GetDevice();
        const u32 g = r.group;
        if (!r.blocked && r.used[g] != 0) {
            r.tick[g] = scheduler.CurrentTick();
            r.frame[g] = f;
            r.pending[g] = true;
        }
        for (u32 i = 0; i < SunReader::Groups; ++i) {
            if (!r.pending[i]) {
                continue;
            }
            if (!scheduler.IsFree(r.tick[i])) {
                if (f - r.frame[i] > SunReader::MaxLag) {
                    r.last_seen = f;
                    ++r.late;
                }
                continue;
            }
            std::array<u64, SunReader::PerGroup> counts{};
            const u32 n = std::min(r.used[i], SunReader::PerGroup);
            const vk::Result result = device.getQueryPoolResults(
                *r.pool, i * SunReader::PerGroup, n, n * sizeof(u64), counts.data(), sizeof(u64),
                vk::QueryResultFlagBits::e64);
            bool seen = result != vk::Result::eSuccess;
            for (u32 q = 0; q < n && !seen; ++q) {
                seen = counts[q] != 0;
            }
            if (seen) {
                r.last_seen = std::max(r.last_seen, r.frame[i]);
                ++r.seen_frames;
            } else {
                ++r.hidden_frames;
            }
            r.pending[i] = false;
        }
        r.group = (g + 1) % SunReader::Groups;
        const u32 next = r.group;
        r.blocked = r.pending[next];
        if (r.blocked) {
            ++r.blocked_frames; // still on the GPU after Groups frames: next frame unmeasured
        } else if (r.used[next] != 0) {
            device.resetQueryPool(*r.pool, next * SunReader::PerGroup, r.used[next]);
            r.used[next] = 0;
        }
    }
    r.quiet = SunAtlasIgnoreReader() || f >= r.last_seen + SunReader::QuietFrames;
    r.water_now = false;
    r.unmeasured_now = false;
    r.cleared = false;
}

namespace {
/// r7: light clip x, y of the world origin: the projection (4x4 rows, m[0..15]) times the inverse
/// of view to world (3x4 rows [A | t], m[16..27]): view = A^-1 (world - t).
std::array<double, 2> OriginInLight(const std::array<float, 28>& m) {
    const float* p = m.data();
    const float* r = m.data() + 16;
    const double a00 = r[0], a01 = r[1], a02 = r[2], a10 = r[4], a11 = r[5], a12 = r[6];
    const double a20 = r[8], a21 = r[9], a22 = r[10];
    const double t0 = -double(r[3]), t1 = -double(r[7]), t2 = -double(r[11]);
    const double det = a00 * (a11 * a22 - a12 * a21) - a01 * (a10 * a22 - a12 * a20) +
                       a02 * (a10 * a21 - a11 * a20);
    const double nan = std::numeric_limits<double>::quiet_NaN();
    if (!(std::abs(det) > 1e-12)) {
        return {nan, nan};
    }
    // Cramer's rule for A v = -t.
    const double v0 = (t0 * (a11 * a22 - a12 * a21) - a01 * (t1 * a22 - a12 * t2) +
                       a02 * (t1 * a21 - a11 * t2)) / det;
    const double v1 = (a00 * (t1 * a22 - a12 * t2) - t0 * (a10 * a22 - a12 * a20) +
                       a02 * (a10 * t2 - t1 * a20)) / det;
    const double v2 = (a00 * (a11 * t2 - t1 * a21) - a01 * (a10 * t2 - t1 * a20) +
                       t0 * (a10 * a21 - a11 * a20)) / det;
    const double w = p[12] * v0 + p[13] * v1 + p[14] * v2 + p[15];
    if (!(std::abs(w) > 1e-12)) {
        return {nan, nan};
    }
    return {(p[0] * v0 + p[1] * v1 + p[2] * v2 + p[3]) / w,
            (p[4] * v0 + p[5] * v1 + p[6] * v2 + p[7]) / w};
}
}

void Rasterizer::SunAtlasStatsFrameEnd() {
    auto& a = sun_atlas;
    for (u32 c = 0; c < 4; ++c) {
        auto& now = a.light[c];
        auto& before = a.previous_light[c];
        auto& s = a.light_stats[c];
        const bool have = ((a.light_mask >> c) & 1u) != 0;
        if (have && before.valid) {
            ++s.compared;
            double delta = 0.0;
            bool turned = false;
            for (u32 i = 0; i < 28; ++i) {
                delta = std::max(delta, std::abs(double(now.m[i]) - double(before.m[i])));
                // Translations: the projection's offsets (3, 7, 11) and view to world's column 3.
                const bool translation = (i < 16 ? i : i - 16) % 4 == 3;
                turned |= !translation && now.m[i] != before.m[i];
            }
            s.max_delta = std::max(s.max_delta, delta);
            if (std::memcmp(now.m.data(), before.m.data(), sizeof(now.m)) == 0) {
                ++s.same;
            } else if (turned) {
                ++s.turned;
            } else {
                ++s.moved;
                const auto p = OriginInLight(now.m), q = OriginInLight(before.m);
                const double dx = (p[0] - q[0]) * 0.5 * double(now.width);
                const double dy = (p[1] - q[1]) * 0.5 * double(now.height);
                if (std::isfinite(dx) && std::isfinite(dy)) {
                    const double d = std::hypot(dx, dy);
                    ++s.measured;
                    s.sum_texels += d;
                    s.max_texels = std::max(s.max_texels, d);
                    s.whole += std::abs(dx - std::round(dx)) < 0.01 &&
                                       std::abs(dy - std::round(dy)) < 0.01
                                   ? 1u
                                   : 0u;
                }
            }
        }
        before = have ? now : SunAtlas::Light{};
    }
    a.light_mask = 0;
    if (a.pass_log) {
        static constexpr const char* Names[] = {"c0",     "c1",          "c2",   "c3",
                                                "across", "no viewport", "mixed"};
        std::string text;
        for (u32 i = 0; i < a.pass_count; ++i) {
            const auto& n = a.pass_notes[i];
            text += fmt::format(" [{}{}{} {} draws, viewport {},{} {}x{}]",
                                Names[std::min<u32>(n.cascade, 6u)], n.clear & 1 ? " clear" : "",
                                n.clear & 2 ? " DB-clear" : "", n.draws, n.x, n.y, n.w, n.h);
        }
        std::printf("Sun atlas: the passes of one frame (%u%s):%s\n", a.pass_count,
                    a.pass_count == a.pass_notes.size() ? ", more not listed" : "", text.c_str());
        ++a.pass_logs;
    }
    ++a.stats_frame;
    a.pass_log = a.address && a.pass_logs < 3 && a.stats_frame % 600 == 300;
    a.pass_count = 0;
    a.note_open = false;
    a.check_frame = a.stats_frame % 64 == 0;
}

void Rasterizer::SunAtlasStatsReport(double f) {
    auto& a = sun_atlas;
    BbReport::Printf("Sun atlas: a frame %.1f draws in %.1f passes, %.2f passes begin with a clear of "
                "the whole image, %.2f DB clear draws, %.1f draws with no single viewport, %.1f "
                "across cascades, %.1f with the previous atlas draw's pipeline; the other reader "
                "(vs %016llx ps %016llx) %.1f draws\n",
                double(a.atlas_draws) / f, double(a.atlas_passes) / f, double(a.clear_passes) / f,
                double(a.clear_draws) / f, double(a.no_viewport) / f, double(a.spanning) / f,
                double(a.same_pipeline) / f, (unsigned long long)a.reader_vs,
                (unsigned long long)a.reader_ps, double(a.reader_draws) / f);
    std::string text;
    for (u32 c = 0; c < 4; ++c) {
        const auto& s = a.light_stats[c];
        const auto& l = a.previous_light[c]; // this frame's (SunAtlasStatsFrameEnd)
        const double texel_m = l.valid && l.m[0] != 0.0f && l.width > 0.0f
                                   ? 2.0 / std::abs(double(l.m[0])) / double(l.width)
                                   : 0.0;
        text += fmt::format(
            " [c{}: {} frame pairs, same {}, turned or rescaled {}, moved only {} (whole texels {} "
            "of {}, mean {:.3f} max {:.3f} texels), max element change {:.4g}, texel {:.4f} m, "
            "viewport {}x{}, another matrix in {} of {} sampled draws]",
            c, s.compared, s.same, s.turned, s.moved, s.whole, s.measured,
            s.measured ? s.sum_texels / double(s.measured) : 0.0, s.max_texels, s.max_delta,
            texel_m, l.width, l.height, s.other_matrix, s.checked);
    }
    BbReport::Printf("Sun atlas: light matrices by cascade (shadow pass constants: projection at dword "
                "52, view to world at 180):%s; %llu draws without them\n",
                text.c_str(), (unsigned long long)a.no_constants);
    a.reader_draws = 0;
    a.atlas_draws = a.atlas_passes = a.clear_passes = a.clear_draws = 0;
    a.no_viewport = a.spanning = a.same_pipeline = a.no_constants = 0;
    a.light_stats = {};
}

void Rasterizer::SunAtlasFrameEnd() {
    auto& a = sun_atlas;
    const bool replaced = contact_shadow->TakeSunReplaced();
    a.steady = replaced && a.resolved ? std::min(a.steady + 1, SunAtlasSteadyFrames) : 0u;
    // The march selects a cascade by view z <= distance <= min(reach, shadow distance).
    float limit = a.reach;
    if (std::isfinite(a.coverage) && a.coverage > 0.0f) {
        limit = std::min(limit, a.coverage);
    }
    u32 needed = 0;
    if (limit > 0.0f) {
        needed = 4;
        if (a.splits_valid) {
            needed = 1;
            for (const float split : a.splits) {
                needed += split < limit ? 1u : 0u;
            }
        }
    }
    a.needed = needed;
    SunAtlasQueriesFrameEnd(); // r12
    SunAtlasStatsFrameEnd(); // r7
    ++a.frames;
    a.left_out_frames += a.any_skipped ? 1u : 0u;
    for (u32 c = 0; c < 4; ++c) {
        a.cascade_frames[c] += (a.drawn_mask >> c) & 1u;
    }
    if (a.frames >= 600 && a.address) {
        const double f = double(a.frames);
        BbReport::Printf("Sun atlas: at %#llx, splits %.1f / %.1f / %.1f m (%s), shadow distance "
                    "%.1f m, volumetric reach %.1f m, %u cascades sampled; left out on %u of %u "
                    "frames%s; draws a frame by cascade %.1f %.1f %.1f %.1f, left out %.1f %.1f "
                    "%.1f %.1f; frames with draws %.0f%% %.0f%% %.0f%% %.0f%%\n",
                    (unsigned long long)a.address, a.splits[0], a.splits[1], a.splits[2],
                    a.splits_valid ? "valid" : "not used", a.coverage, a.reach, a.needed,
                    a.left_out_frames, a.frames,
                    a.other_reader ? " (off: another reader)" : "",
                    double(a.cascade_draws[0]) / f, double(a.cascade_draws[1]) / f,
                    double(a.cascade_draws[2]) / f, double(a.cascade_draws[3]) / f,
                    double(a.cascade_skipped[0]) / f, double(a.cascade_skipped[1]) / f,
                    double(a.cascade_skipped[2]) / f, double(a.cascade_skipped[3]) / f,
                    100.0 * double(a.cascade_frames[0]) / f, 100.0 * double(a.cascade_frames[1]) / f,
                    100.0 * double(a.cascade_frames[2]) / f, 100.0 * double(a.cascade_frames[3]) / f);
        if (!BbToggle::Experiment(SunAtlasLiveOffBit)) {
            auto& r = sun_reader;
            BbReport::Printf(
                "Sun atlas: readers (r12): water draws %.1f a frame (%llu measured, %llu without a "
                "query) on %llu of %u frames, answers read: %llu frames with samples, %llu "
                "without, %llu late, %llu frames whose query group was still busy; other reader "
                "draws %.1f a frame%s%s%s; this frame left out cascades from %u (water quiet now "
                "%s, sun replaced %u of the %u frames in a row needed); left out a frame %.1f "
                "%.1f %.1f %.1f; kept "
                "in those cascades a frame: capture draws storing ray tracing geometry %.1f %.1f "
                "%.1f %.1f, motion draws %.1f, DB clear draws or before the frame's clear %.1f, "
                "with colour targets %.1f\n",
                double(r.water_draws) / f, (unsigned long long)r.measured,
                (unsigned long long)r.unmeasured, (unsigned long long)r.water_frames, a.frames,
                (unsigned long long)r.seen_frames, (unsigned long long)r.hidden_frames,
                (unsigned long long)r.late, (unsigned long long)r.blocked_frames,
                double(r.other_draws) / f, r.latched ? " (latched: every cascade drawn)" : "",
                SunAtlasIgnoreReader() ? ", BB_SUN_ATLAS_IGNORE_READER=1: readers ignored" : "",
                sun_hold.active ? ", r7 kept cascades (BB_SUN_CASCADE_EVERY) on: nothing left out" : "",
                a.skip_from, r.quiet ? "yes" : "no", a.steady, SunAtlasSteadyFrames,
                double(a.cascade_skipped[0]) / f, double(a.cascade_skipped[1]) / f,
                double(a.cascade_skipped[2]) / f, double(a.cascade_skipped[3]) / f,
                double(r.capture_kept[0]) / f, double(r.capture_kept[1]) / f,
                double(r.capture_kept[2]) / f, double(r.capture_kept[3]) / f,
                double(r.motion_kept) / f, double(r.clear_kept) / f, double(r.colour_kept) / f);
            r.water_draws = r.measured = r.unmeasured = r.water_frames = 0;
            r.seen_frames = r.hidden_frames = r.late = r.blocked_frames = r.other_draws = 0;
            r.clear_kept = r.colour_kept = r.motion_kept = 0;
            r.capture_kept = {};
        }
        SunAtlasStatsReport(f); // r7
        a.frames = 0;
        a.left_out_frames = 0;
        a.cascade_draws = {};
        a.cascade_skipped = {};
        a.cascade_frames = {};
    }
    // r12: with experiment 549755813888 clear the readers are sun_reader's: the water only while
    // it showed samples lately, any other one for good.
    const bool reader_free = BbToggle::Experiment(SunAtlasLiveOffBit)
                                 ? !a.other_reader
                                 : !sun_reader.latched && sun_reader.quiet;
    a.skip_from = a.address && reader_free && a.steady >= SunAtlasSteadyFrames ? needed : 4u;
    a.resolved = false;
    a.reach = 0.0f;
    a.drawn_mask = 0;
    a.any_skipped = false;
}

// bbport (r7_cascades): far sun cascades kept from an earlier frame.
//
// The game draws all four cascades of its sun atlas every frame, about 2,700 caster draws. A
// cascade's quadrant is kept instead when its caster draws carry the light matrix (the 864-byte
// vertex constants: projection at dword 52, view to world at dword 180, RtShadow::ToWorld's
// layout), viewport and scissor registers its quadrant was drawn with, bit for bit. Every reader
// (the game's resolve, the water, PCSS, the volumetric sunlight) maps its pixels into the atlas
// through matrices the game builds from that same light transform, so the kept depth is what a
// redraw would give, but for casters that moved since (up to N-1 frames late).
//   SunHoldEarly       a draw into the atlas: its cascade (from its viewport and scissor registers,
//                      as learned from drawn draws) and light matrix; a kept cascade's draw is left
//                      out before any of its work.
//   SunHoldBeforePass  the atlas pass's load-op clear (the whole image) becomes a clear of the
//   SunHoldInPass      quadrants drawn this frame, recorded inside the pass before its draw.
//   SunHoldFlush       a spared quadrant whose cascade has not shown up when something samples the
//                      atlas is cleared then, as the game would have it.
//   SunHoldFrameEnd    what each quadrant holds; forced redraws; the next frame's plan; the report.
// All run on the thread recording draws: stage B with the draw pipe, else the GPU command thread.
namespace {
constexpr u64 SunHoldOffBit = 268435456;   ///< experiment: every cascade every frame (as before)
constexpr u32 SunHoldSteadyFrames = 8;     ///< frames drawn in full before any cascade is kept
constexpr float SunHoldCutMetres = 30.0f;  ///< cascade 0's light origin moving more: a camera cut

std::array<u32, 4> SunHoldEvery() {
    std::array<u32, 4> every{1, 1, 1, 1};
    const char* text = std::getenv("BB_SUN_CASCADE_EVERY");
    for (u32 c = 0; text && *text && c < 4; ++c) {
        char* end = nullptr;
        const unsigned long n = std::strtoul(text, &end, 10);
        if (end == text) {
            break;
        }
        every[c] = u32(std::clamp<unsigned long>(n, 1ul, 8ul));
        text = end;
        while (*text == ',' || *text == ' ') {
            ++text;
        }
    }
    return every;
}

/// The registers that place a draw's viewport and scissor (UpdateViewportScissorState,
/// DrawScissor); 0 when they do not fit the key.
u64 SunViewKey(const AmdGpu::Regs& regs) {
    std::array<u8, 256> bytes{};
    std::size_t size = 0;
    const auto put = [&](const auto& value) {
        if (size + sizeof(value) <= bytes.size()) {
            std::memcpy(bytes.data() + size, &value, sizeof(value));
        }
        size += sizeof(value);
    };
    u32 viewports = 0;
    for (u32 i = 0; i < AmdGpu::NUM_VIEWPORTS && i < 32; ++i) {
        viewports |= (regs.viewports[i].xscale != 0.0f ? 1u : 0u) << i;
    }
    const u32 first = viewports ? u32(std::countr_zero(viewports)) : 0u;
    put(viewports);
    put(u8(regs.primitive_type == AmdGpu::PrimitiveType::RectList)); // IsClipDisabled
    put(regs.viewports[first]);
    put(regs.viewport_depths[first]);
    put(regs.viewport_control);
    put(regs.clipper_control);
    put(regs.screen_scissor);
    put(regs.window_scissor);
    put(regs.generic_scissor);
    put(regs.window_offset);
    put(regs.mode_control);
    put(regs.viewport_scissors[first]);
    if (size > bytes.size()) {
        return 0;
    }
    return XXH3_64bits(bytes.data(), size) | 1u;
}

bool SunHoldSamples(const Shader::Info* info, VAddr atlas) {
    if (!info || !atlas) {
        return false;
    }
    for (const auto& image : info->images) {
        if (image.GetSharp(*info).Address() == atlas) {
            return true;
        }
    }
    return false;
}

bool SunWritableDepth(vk::ImageLayout layout) {
    return layout == vk::ImageLayout::eDepthAttachmentOptimal ||
           layout == vk::ImageLayout::eDepthStencilAttachmentOptimal ||
           layout == vk::ImageLayout::eDepthAttachmentStencilReadOnlyOptimal ||
           layout == vk::ImageLayout::eAttachmentOptimal || layout == vk::ImageLayout::eGeneral;
}

/// The shadow pass's 864-byte vertex constants (RtShadow::ToWorld reads the same).
bool SunCasterConstants(const Shader::Info& vs, Core::MemoryManager* memory, VAddr& address) {
    for (const auto& resource : vs.buffers) {
        if (resource.IsSpecial()) {
            continue;
        }
        const auto buffer = resource.GetSharp(vs);
        if (!buffer.Valid() || buffer.GetSize() != 864) {
            continue;
        }
        address = buffer.base_address;
        return memory->IsValidGpuMapping(address, 0) && memory->ClampRangeSize(address, 864) == 864;
    }
    return false;
}

/// bbport (r14_cascade_keep): the game leaves sun cascades undrawn on some frames (BbSunCascades,
/// shim/engine/graphics.cpp) and experiment 1099511627776 is clear.
bool SunKeepAsked() {
    return BbSunCascades::skip_period.load(std::memory_order_relaxed) > 1 &&
           !BbToggle::Experiment(BbSunCascades::kOffBit);
}

/// Clears atlas quadrants (bit c: x = c & 1, y = c >> 1 halves of width x height) inside the open
/// pass: vkCmdClearAttachments, in rasterization order with the pass's draws (unlike the transfer
/// clears). r7 and r14.
void SunClearQuadrants(Scheduler& scheduler, u32 quadrants, u32 width, u32 height, float depth) {
    const u32 half_w = width / 2, half_h = height / 2;
    std::array<vk::ClearRect, 4> rects{};
    u32 count = 0;
    for (u32 c = 0; c < 4; ++c) {
        if ((quadrants >> c) & 1u) {
            rects[count++] = vk::ClearRect{
                .rect = vk::Rect2D{.offset = vk::Offset2D{s32((c & 1u) * half_w),
                                                          s32((c >> 1) * half_h)},
                                   .extent = vk::Extent2D{half_w, half_h}},
                .baseArrayLayer = 0,
                .layerCount = 1,
            };
        }
    }
    if (count == 0 || half_w == 0 || half_h == 0) {
        return;
    }
    const vk::ClearAttachment attachment{
        .aspectMask = vk::ImageAspectFlagBits::eDepth,
        .colorAttachment = 0,
        .clearValue = vk::ClearValue{.depthStencil =
                                         vk::ClearDepthStencilValue{.depth = depth, .stencil = 0}},
    };
    scheduler.Record([attachment, rects, count](vk::CommandBuffer cmdbuf) {
        cmdbuf.clearAttachments(1, &attachment, count, rects.data());
    });
}

/// r14: the quadrant holding a draw's viewport and scissor as set (SunAtlasSkipDraw's rule):
/// 0..3; 4 across quadrants, 5 no single viewport, 6 an empty area (it writes nothing).
u32 SunQuadrant(const DynamicState& dynamic, u32 width, u32 height) {
    if (dynamic.viewports.size() != 1 || dynamic.scissors.size() != 1 || width == 0 ||
        height == 0) {
        return 5;
    }
    const vk::Viewport& vp = dynamic.viewports[0];
    const vk::Rect2D& sc = dynamic.scissors[0];
    const float left = std::max(float(sc.offset.x), std::min(vp.x, vp.x + vp.width));
    const float top = std::max(float(sc.offset.y), std::min(vp.y, vp.y + vp.height));
    const float right = std::min(float(sc.offset.x) + float(sc.extent.width),
                                 std::max(vp.x, vp.x + vp.width));
    const float bottom = std::min(float(sc.offset.y) + float(sc.extent.height),
                                  std::max(vp.y, vp.y + vp.height));
    if (!(right > left && bottom > top)) {
        return 6;
    }
    const float half_w = 0.5f * float(width), half_h = 0.5f * float(height);
    const bool east = left >= half_w, south = top >= half_h;
    if ((!east && right > half_w) || (!south && bottom > half_h)) {
        return 4;
    }
    return (east ? 1u : 0u) | (south ? 2u : 0u);
}

/// r14: whether quadrants can be cleared inside this pass: depth, one layer, the whole image
/// (width x height, even) as its size, in a layout depth can be written in.
bool SunKeepClearable(const RenderState& state, u32 width, u32 height) {
    const auto& depth = state.depth_stencil_attachment;
    return depth.has_depth && state.num_layers == 1 && state.width == width &&
           state.height == height && width >= 2 && height >= 2 && width % 2 == 0 &&
           height % 2 == 0 && SunWritableDepth(depth.image_layout);
}
} // namespace

bool Rasterizer::SunHoldEarly(const GraphicsPipeline* pipeline) {
    auto& h = sun_hold;
    if (!h.active) {
        return false;
    }
    h.draw_cascade = 4;
    h.draw_learned = 4;
    h.draw_known = false;
    h.draw_key = 0;
    const auto& regs = Regs();
    // A draw with neither the depth nor the stencil test binds no depth target (BeginRendering:
    // the game's attachmentless full-atlas rectangle, vs 89cda9e4 without a pixel shader, once a
    // frame): it is not a draw into the atlas.
    const bool binds_depth =
        (regs.depth_control.depth_enable && regs.depth_buffer.DepthValid()) ||
        (regs.depth_control.stencil_enable && regs.depth_buffer.StencilValid());
    if (!h.z_address || !binds_depth || !regs.depth_buffer.DepthValid() ||
        regs.depth_buffer.DepthAddress() != h.z_address) {
        // Not into the atlas. Sampling it while a spared quadrant is still unseen: clear that first.
        if (((h.spared & ~h.decided) | h.pending_clear) != 0 &&
            (SunHoldSamples(&pipeline->GetStage(Shader::SwStage::Vertex), sun_atlas.address) ||
             SunHoldSamples(pipeline->GetStages()[u32(Shader::SwStage::Fragment)],
                            sun_atlas.address))) {
            SunHoldFlush();
        }
        return false;
    }
    ++h.atlas_draws;
    if (!h.image_checked) {
        // The frame's first draw into the atlas: nothing is left out yet. Kept depth needs the
        // same image, untouched since (no CPU or buffer write over it: it would be uploaded).
        h.image_checked = true;
        if (h.plan && !SunHoldImageIntact()) {
            h.plan = 0;
            h.force = true;
            h.why = "the atlas image changed";
        }
    }
    if (regs.depth_render_control.depth_clear_enable) {
        return false; // a DB clear draw: SunHoldBeforePass narrows its pass's clear
    }
    const u64 key = SunViewKey(regs);
    h.draw_key = key;
    for (const auto& view : h.views) {
        if (key && view.used && view.key == key) {
            h.draw_known = true;
            h.draw_learned = view.cascade;
            break;
        }
    }
    if (!h.draw_known) {
        ++h.unknown_draws; // learned once drawn (SunHoldInPass); nothing is kept from this frame
        return false;
    }
    if (h.draw_learned >= 4) {
        // More than one quadrant, or no single viewport: never left out; writing depth, nothing
        // is kept from this frame.
        h.spanning_draws +=
            regs.depth_control.depth_enable && regs.depth_control.depth_write_enable ? 1u : 0u;
        return false;
    }
    const u32 c = h.draw_learned, bit = 1u << c;
    h.draw_cascade = u8(c);
    ++h.arrived[c];
    // Ray tracing capture or motion vectors: such draws always run (RtShadow, ObjectMotion).
    const bool special = pipeline->GetGraphicsKey().motion_vectors != 0;
    h.special[c] = h.special[c] || special;
    bool same = false;
    if (h.every[c] > 1 || !h.frame_light[c].valid) {
        VAddr address = 0;
        if (!SunCasterConstants(pipeline->GetStage(Shader::SwStage::Vertex), memory, address)) {
            h.no_constants[c] = true;
            h.const_address[c] = 0;
            h.match[c] = false;
        } else if (address != h.const_address[c]) {
            // (The same address as this cascade's draw before: the same constants.)
            h.const_address[c] = address;
            std::array<float, 28> m{};
            const auto* data = reinterpret_cast<const float*>(address);
            std::memcpy(m.data(), data + 52, 16 * sizeof(float));
            std::memcpy(m.data() + 16, data + 180, 12 * sizeof(float));
            auto& frame = h.frame_light[c];
            if (!frame.valid) {
                frame.m = m;
                frame.view = key;
                frame.valid = true;
            } else if (std::memcmp(frame.m.data(), m.data(), sizeof(m)) != 0) {
                h.multi[c] = true;
            }
            h.match[c] =
                h.held[c].valid && std::memcmp(h.held[c].m.data(), m.data(), sizeof(m)) == 0;
        }
        if (h.frame_light[c].valid && h.frame_light[c].view != key) {
            h.multi[c] = true;
        }
        same = h.match[c] && h.held[c].view == key;
    }
    if ((h.plan & bit) == 0) {
        return false;
    }
    const bool keep = same && !special; // capture and motion draws always run
    if ((h.decided & bit) == 0) {
        h.decided |= bit;
        if (keep) {
            h.confirmed |= bit;
        } else {
            ++h.broke[c]; // its light matrix, viewport or scissor moved: drawn after all
        }
    } else if (!keep) {
        // A kept cascade's later draw with other constants, or a capture or motion draw: from here
        // on the cascade is drawn, into its quadrant cleared first; the draws left out before are
        // missing from it this frame (lit, never misplaced), and it is drawn in full next frame.
        h.confirmed &= ~bit;
        h.stale |= bit;
        ++h.stale_draws;
    }
    if (keep) {
        h.draw_cascade = 4; // not drawn: SunHoldDrawn does not count it
        ++h.skipped[c];
        return true;
    }
    // The quadrant is cleared in this draw's pass, before the draw, if this frame's clear spared
    // it (SunHoldInPass); if the clear is still to come, it is not spared any more.
    h.plan &= ~bit;
    if ((h.spared & bit) != 0) {
        h.spared &= ~bit;
        h.pending_clear |= bit;
    }
    return false;
}

void Rasterizer::SunHoldBeforePass(RenderState& state) {
    auto& h = sun_hold;
    h.atlas_pass = false;
    if (!h.active || !db_desc.first || !sun_atlas.address) {
        return;
    }
    auto& image = texture_cache.GetImage(db_desc.first);
    if (image.info.guest_address != sun_atlas.address) {
        return;
    }
    h.atlas_pass = true;
    const auto& regs = Regs();
    if ((h.spared | h.confirmed) != 0 &&
        (db_desc.first != h.image || image.image_uid != h.image_uid)) {
        ++h.lost;
        h.force = true;
        h.why = "the atlas image changed";
        // The new image does not hold the kept depth: those quadrants are cleared (lit this
        // frame, never stale) and their cascades are drawn from here on.
        const u32 kept = (h.spared | h.confirmed) & 0xFu;
        h.stale |= kept;
        h.pending_clear |= kept;
        h.spared &= ~kept;
        h.plan &= ~kept;
    }
    h.z_address = regs.depth_buffer.DepthAddress();
    h.image = db_desc.first;
    h.image_uid = image.image_uid;
    h.backing = image.backing;
    h.range = db_desc.second.view_info.range;
    h.width = state.width;
    h.height = state.height;
    auto& depth = state.depth_stencil_attachment;
    // The atlas passes have one colour slot without an image (the pass list's "[- ]"): only
    // slots with a view are colour targets.
    u32 colour_targets = 0;
    for (u32 i = 0; i < state.num_color_attachments && i < state.color_attachments.size(); ++i) {
        colour_targets += state.color_attachments[i].image_view ? 1u : 0u;
    }
    const bool suitable = depth.has_depth && colour_targets == 0 &&
                          state.num_layers == 1 && !image.info.props.has_stencil &&
                          state.width >= 2 && state.height >= 2 && state.width % 2 == 0 &&
                          state.height % 2 == 0;
    if (!suitable) {
        SunHoldOff("an atlas pass with colour targets, layers, stencil or an odd size");
    }
    if (depth.depth_clear) {
        // The load-op clear covers the whole image (Scheduler::BeginRendering): only the quadrants
        // not kept are cleared, by SunHoldInPass right after the pass begins.
        const u32 spare = h.plan & 0xFu;
        if (spare != 0 && suitable && !depth.stencil_clear) {
            h.clear_depth = std::bit_cast<float>(depth.clear_value[0]);
            depth.depth_clear = false;
            depth.clear_value[0] = 0;
            h.spared |= spare;
            h.pending_clear |= 0xFu & ~spare;
            ++h.converted;
        } else if ((h.spared | h.confirmed) != 0) {
            ++h.unconverted;
            h.stale |= h.spared | h.confirmed;
            h.force = true;
            h.why = "a whole-atlas clear that could not be narrowed";
        }
    }
    if (suitable && regs.depth_control.depth_enable && regs.depth_control.depth_write_enable &&
        !regs.depth_render_control.depth_clear_enable && SunWritableDepth(depth.image_layout)) {
        h.last_state = state;
        h.last_state.depth_stencil_attachment.depth_clear = false;
        h.last_state.depth_stencil_attachment.stencil_clear = false;
        h.last_state.depth_stencil_attachment.clear_value = {};
        h.last_state_valid = true;
    }
}

void Rasterizer::SunHoldInPass(const RenderState& state) {
    auto& h = sun_hold;
    if (!h.atlas_pass) {
        return;
    }
    h.atlas_pass = false;
    if (h.pending_clear != 0 && scheduler.IsRenderingWith(state) &&
        SunWritableDepth(state.depth_stencil_attachment.image_layout)) {
        SunHoldClear(h.pending_clear);
        h.pending_clear = 0;
    }
    if (!h.draw_key) {
        return;
    }
    // Where this draw writes, from its viewport and scissor as set (as SunAtlasSkipDraw finds
    // it): learned for its registers, or checked against what was learned.
    const auto& dynamic = scheduler.GetDynamicState();
    u8 cascade = 4;
    if (dynamic.viewports.size() == 1 && dynamic.scissors.size() == 1 && state.width != 0 &&
        state.height != 0) {
        const vk::Viewport& vp = dynamic.viewports[0];
        const vk::Rect2D& sc = dynamic.scissors[0];
        const float left = std::max(float(sc.offset.x), std::min(vp.x, vp.x + vp.width));
        const float top = std::max(float(sc.offset.y), std::min(vp.y, vp.y + vp.height));
        const float right = std::min(float(sc.offset.x) + float(sc.extent.width),
                                     std::max(vp.x, vp.x + vp.width));
        const float bottom = std::min(float(sc.offset.y) + float(sc.extent.height),
                                      std::max(vp.y, vp.y + vp.height));
        const float half_w = 0.5f * float(state.width), half_h = 0.5f * float(state.height);
        if (right > left && bottom > top) {
            const bool east = left >= half_w, south = top >= half_h;
            if ((east || right <= half_w) && (south || bottom <= half_h)) {
                cascade = u8((east ? 1u : 0u) | (south ? 2u : 0u));
            }
        }
    }
    if (h.draw_known) {
        if (cascade != h.draw_learned) {
            ++h.mismatched;
            h.force = true;
            h.why = "a viewport seen before landed in another quadrant";
            SunHoldOff("a viewport and scissor seen before landed in another quadrant");
        }
        return;
    }
    if (target_scale[0] == 1.0f && target_scale[1] == 1.0f && target_offset[0] == 0.0f &&
        target_offset[1] == 0.0f) {
        auto& entry = h.views[h.next_view++ % h.views.size()];
        entry.key = h.draw_key;
        entry.cascade = cascade;
        entry.used = true;
    }
}

void Rasterizer::SunHoldDrawn() {
    auto& h = sun_hold;
    if (h.draw_cascade < 4) {
        ++h.drawn[h.draw_cascade];
        h.draw_cascade = 4;
    }
}

void Rasterizer::SunHoldOther(const Shader::Info* first, const Shader::Info* second,
                              bool graphics) {
    auto& h = sun_hold;
    if (!h.active || !h.z_address) {
        return;
    }
    if (graphics) {
        const auto& regs = Regs();
        if (regs.depth_buffer.DepthValid() && regs.depth_buffer.DepthAddress() == h.z_address) {
            // Never left out, and it may draw over kept depth: keeping stops here.
            h.stale |= h.confirmed;
            h.force = true;
            h.why = "an indirect draw into the atlas";
            SunHoldOff("an indirect draw into the atlas");
            SunHoldFlush();
            return;
        }
    }
    if (((h.spared & ~h.decided) | h.pending_clear) != 0 &&
        (SunHoldSamples(first, sun_atlas.address) || SunHoldSamples(second, sun_atlas.address))) {
        SunHoldFlush();
    }
}

// Spared quadrants whose cascade did not show up (and quadrants still waiting for their clear)
// are cleared before anything samples the atlas. Their cascades' later draws, if any, are drawn.
void Rasterizer::SunHoldFlush() {
    auto& h = sun_hold;
    const u32 quadrants = ((h.spared & ~h.decided) | h.pending_clear) & 0xFu;
    if (quadrants == 0) {
        return;
    }
    h.spared &= ~quadrants;
    h.plan &= ~quadrants;
    h.pending_clear &= ~quadrants;
    h.stale |= quadrants;
    bool done = false;
    auto* image = h.last_state_valid && h.image_uid != 0
                      ? texture_cache.TryGetImage(h.image, h.image_uid)
                      : nullptr;
    if (image) {
        // The same image and backing as the pass last_state was taken from: its view still lives.
        if (image->info.guest_address == sun_atlas.address &&
            static_cast<const void*>(image->backing) == h.backing) {
            const bool open = scheduler.IsRenderingWith(h.last_state);
            if (!open) {
                (void)runtime.Transit(image, h.last_state.depth_stencil_attachment.image_layout,
                                vk::PipelineStageFlagBits2::eEarlyFragmentTests |
                                    vk::PipelineStageFlagBits2::eLateFragmentTests,
                                vk::AccessFlagBits2::eDepthStencilAttachmentWrite |
                                    vk::AccessFlagBits2::eDepthStencilAttachmentRead,
                                h.range);
                runtime.FlushBarriers();
                scheduler.BeginRendering(h.last_state);
            }
            SunHoldClear(quadrants);
            if (!open) {
                scheduler.EndRendering();
            }
            done = true;
        }
    }
    for (u32 c = 0; c < 4; ++c) {
        if ((quadrants >> c) & 1u) {
            ++(done ? h.flushed[c] : h.flush_failed);
        }
    }
    if (!done) {
        h.force = true;
        h.why = "a kept quadrant could not be cleared";
    }
}

void Rasterizer::SunHoldClear(u32 quadrants) {
    auto& h = sun_hold;
    SunClearQuadrants(scheduler, quadrants, h.width, h.height, h.clear_depth);
}

bool Rasterizer::SunHoldImageIntact() {
    auto& h = sun_hold;
    const auto* image = h.image_uid != 0 ? texture_cache.TryGetImage(h.image, h.image_uid) : nullptr;
    return image && static_cast<const void*>(image->backing) == h.backing &&
           image->info.guest_address == h.atlas &&
           (static_cast<u32>(image->flags) & static_cast<u32>(VideoCore::ImageFlagBits::Dirty)) == 0;
}

void Rasterizer::SunHoldOff(const char* why) {
    auto& h = sun_hold;
    if (!h.off_for_good) {
        h.off_for_good = true;
        std::printf("Sun atlas: kept cascades off for good: %s\n", why);
    }
}

void Rasterizer::SunHoldFrameEnd() {
    static const std::array<u32, 4> every = SunHoldEvery();
    static const bool asked = every[0] > 1 || every[1] > 1 || every[2] > 1 || every[3] > 1;
    if (!asked) {
        return;
    }
    auto& h = sun_hold;
    const auto& a = sun_atlas;
    if (h.frames_total++ == 0) {
        std::printf("Sun atlas: BB_SUN_CASCADE_EVERY %u,%u,%u,%u: a cascade whose light matrix, "
                    "viewport and scissor equal the ones its quadrant was drawn with is kept, for "
                    "up to N-1 frames (experiment 268435456: every cascade every frame)\n",
                    every[0], every[1], every[2], every[3]);
    }
    h.every = every;
    // 1. What each quadrant holds now: kept depth (one frame older), or this frame's drawing,
    // which can be kept only if every draw of the cascade ran, with one light matrix and one
    // viewport, none a capture or motion draw, and nothing unknown or spanning drew into the atlas.
    const bool clean = h.unknown_draws == 0 && h.spanning_draws == 0 && h.pending_clear == 0 &&
                       !h.force;
    if (h.pending_clear != 0) {
        ++h.flush_failed; // a moved cascade's quadrant was drawn without its clear
    }
    h.kept_frames += h.confirmed != 0 ? 1u : 0u;
    for (u32 c = 0; c < 4; ++c) {
        const u32 bit = 1u << c;
        h.planned[c] += (h.plan_start & bit) != 0 ? 1u : 0u;
        if ((h.confirmed & bit) != 0) {
            ++h.kept[c];
            ++h.age[c];
            if ((h.stale & bit) != 0 || !clean) {
                h.held[c].valid = false;
            }
            continue;
        }
        const bool complete = clean && h.arrived[c] > 0 && h.drawn[c] == h.arrived[c] &&
                              !h.multi[c] && !h.special[c] && !h.no_constants[c] &&
                              (h.stale & bit) == 0 && h.frame_light[c].valid;
        h.held[c] = complete ? h.frame_light[c] : SunHold::Light{};
        h.age[c] = 0;
    }
    // 2. Everything drawn again when the atlas, its splits, the sun or the image change, after a
    // camera cut, and on frames without the shadow.
    const char* why = h.force ? h.why : nullptr;
    if (a.address != h.atlas) {
        why = "the atlas moved";
        h.atlas = a.address;
        h.z_address = 0;
        h.views = {};
        h.next_view = 0;
        h.image = {};
        h.image_uid = 0;
        h.backing = nullptr;
        h.last_state_valid = false;
    } else if (!a.resolved || h.atlas_draws == 0) {
        why = "a frame without the sun shadow";
    } else if (!a.splits_valid || !h.splits_valid ||
               std::memcmp(a.splits.data(), h.splits.data(), sizeof(h.splits)) != 0) {
        why = "the cascade splits changed";
    } else if (!SunHoldImageIntact()) {
        why = "the atlas image changed";
    }
    h.splits = a.splits;
    h.splits_valid = a.splits_valid;
    const auto& c0 = h.frame_light[0];
    if (!why && c0.valid && h.previous_c0.valid) {
        // View to world rows [A | t] at m[16..27]: A the light's direction, t its origin (metres).
        static constexpr u32 Rotation[] = {16, 17, 18, 20, 21, 22, 24, 25, 26};
        for (const u32 i : Rotation) {
            if (std::bit_cast<u32>(c0.m[i]) != std::bit_cast<u32>(h.previous_c0.m[i])) {
                why = "the sun turned";
                break;
            }
        }
        for (const u32 i : {19u, 23u, 27u}) {
            if (!why && !(std::abs(c0.m[i] - h.previous_c0.m[i]) <= SunHoldCutMetres)) {
                why = "a camera cut";
            }
        }
    }
    h.previous_c0 = c0;
    if (why) {
        ++h.forced_frames;
        h.last_why = why;
        h.steady = 0;
        for (auto& held : h.held) {
            held.valid = false;
        }
    } else if (h.steady < SunHoldSteadyFrames) {
        ++h.steady;
    }
    // 3. The next frame's plan: a cascade asked to be drawn every Nth frame is kept when its
    // quadrant holds a complete drawing no older than N-2 frames, off its turn ((frame + c) % N:
    // with 2 and 2, cascades 2 and 3 are drawn on alternate frames).
    // r14 (kept quadrants, BbSunCascades) wins while the game leaves cascades undrawn, or one of
    // its atlas frames is open or lingers: r7 would clear an awaited cascade that does not arrive
    // before its readers (SunHoldFlush), and both take over the same clear.
    const bool keep_on = SunKeepAsked() || sun_keep.open || sun_keep.linger != 0;
    h.active = !BbToggle::Experiment(SunHoldOffBit) && !h.off_for_good && !keep_on;
    ++h.frame;
    u32 plan = 0;
    if (h.active && !why && h.steady >= SunHoldSteadyFrames && h.z_address &&
        h.last_state_valid) {
        for (u32 c = 0; c < 4; ++c) {
            const u32 n = every[c];
            if (n > 1 && h.held[c].valid && h.age[c] + 2 <= n && (h.frame + c) % n != 0) {
                plan |= 1u << c;
            }
        }
    }
    h.plan = plan;
    h.plan_start = plan;
    // 4. Per frame.
    h.unknown_total += h.unknown_draws;
    h.spanning_total += h.spanning_draws;
    h.decided = h.confirmed = h.spared = h.pending_clear = h.stale = 0;
    h.image_checked = false;
    h.force = false;
    h.why = "";
    h.atlas_draws = h.unknown_draws = h.spanning_draws = 0;
    h.arrived = {};
    h.drawn = {};
    h.frame_light = {};
    h.const_address = {};
    h.match = {};
    h.multi = {};
    h.special = {};
    h.no_constants = {};
    h.draw_cascade = 4;
    h.draw_key = 0;
    h.atlas_pass = false;
    // 5. The report.
    if (++h.frames >= 600 && a.address) {
        const double f = double(h.frames);
        std::printf(
            "Sun atlas: kept cascades%s: draws left out a frame %.1f %.1f %.1f %.1f; kept on "
            "%.0f%% %.0f%% %.0f%% %.0f%% of frames (planned %.0f%% %.0f%% %.0f%% %.0f%%), "
            "drawn after all (matrix or viewport moved) %llu %llu %llu %llu, cleared unseen "
            "before a reader %llu %llu %llu %llu; frames keeping any %u; clears narrowed %llu, "
            "not %llu; flush failures %llu, draws over kept depth %llu, image lost %llu, "
            "quadrant mismatches %llu; unknown viewports %.1f, spanning draws %.1f a frame; "
            "forced redraws %u (last: %s)\n",
            !h.active ? (h.off_for_good ? " (off)"
                         : keep_on      ? " (off: r14 kept quadrants on)"
                                        : " (off: experiment 268435456)")
                      : "",
            double(h.skipped[0]) / f, double(h.skipped[1]) / f, double(h.skipped[2]) / f,
            double(h.skipped[3]) / f, 100.0 * double(h.kept[0]) / f,
            100.0 * double(h.kept[1]) / f, 100.0 * double(h.kept[2]) / f,
            100.0 * double(h.kept[3]) / f, 100.0 * double(h.planned[0]) / f,
            100.0 * double(h.planned[1]) / f, 100.0 * double(h.planned[2]) / f,
            100.0 * double(h.planned[3]) / f, (unsigned long long)h.broke[0],
            (unsigned long long)h.broke[1], (unsigned long long)h.broke[2],
            (unsigned long long)h.broke[3], (unsigned long long)h.flushed[0],
            (unsigned long long)h.flushed[1], (unsigned long long)h.flushed[2],
            (unsigned long long)h.flushed[3], h.kept_frames, (unsigned long long)h.converted,
            (unsigned long long)h.unconverted, (unsigned long long)h.flush_failed,
            (unsigned long long)h.stale_draws, (unsigned long long)h.lost,
            (unsigned long long)h.mismatched, double(h.unknown_total) / f,
            double(h.spanning_total) / f, h.forced_frames, h.last_why);
        h.frames = h.kept_frames = h.forced_frames = 0;
        h.skipped = {};
        h.kept = {};
        h.planned = {};
        h.broke = {};
        h.flushed = {};
        h.converted = h.unconverted = h.flush_failed = h.mismatched = h.lost = 0;
        h.stale_draws = h.unknown_total = h.spanning_total = 0;
    }
}

// bbport (r14_cascade_keep): the atlas quadrants of sun cascades the game leaves undrawn keep
// their depth.
//
// With BbSunCascades::skip_period N > 1 the game leaves far cascades undrawn on some frames (a
// cascade at most N - 1 frames in a row) and keeps its own matrices for them, so every reader
// samples such a quadrant with the matrix it was drawn with. The clear of the whole atlas (the
// game's HTILE clear: the load-op clear of its first atlas pass a frame) would wipe it. That clear
// is taken over: the pass loads, and each quadrant is cleared right before the first draw into it
// after the clear, inside the open pass (SunClearQuadrants). Which cascades arrive is learned from
// the draws themselves: the game thread runs frames ahead of this one. An atlas frame runs from
// one clear of the whole image to the next, whatever the display frames.
//   SunKeepBeforePass  an atlas pass about to begin. At a clear of the whole image the atlas frame
//                      before ends and the clear is taken over, or left whole: the first clear in
//                      the mode, a new or reallocated image or one written outside its passes
//                      (write_seq), a DB clear draw, an indirect draw, a pass quadrants cannot be
//                      cleared in. A quadrant kept N atlas frames in a row is cleared with it.
//   SunKeepInPass      the draw's quadrant (its viewport and scissor as set) cleared before the
//                      first draw into it; a draw across quadrants, without a single viewport, or
//                      indirect clears every quadrant not cleared yet (the whole clear, late).
// The atlas is native (4096x4096 is no scene size: never a reduced proxy pass). Ray tracing
// capture draws run as before. Inert while skip_period <= 1 or experiment 1099511627776 is set,
// once no atlas frame is open and the linger is over. On the thread recording draws.
namespace {
/// Atlas frames still taken over after the ask goes away: frames the game queued before with
/// cascades left out.
constexpr u32 SunKeepLinger = 8;
} // namespace

bool Rasterizer::SunKeepGate() const {
    return sun_keep.open || sun_keep.linger != 0 || SunKeepAsked();
}

void Rasterizer::SunKeepBeforePass(RenderState& state, bool indirect) {
    auto& k = sun_keep;
    k.atlas_pass = false;
    if (!db_desc.first || !sun_atlas.address) {
        return;
    }
    auto& image = texture_cache.GetImage(db_desc.first);
    if (image.info.guest_address != sun_atlas.address) {
        return;
    }
    k.atlas_pass = true;
    k.indirect = indirect;
    // The image the quadrants were kept in, written by nothing but the atlas passes since the last
    // atlas draw: each pass begun on it counts one write in write_seq (Runtime::Transit); an
    // upload, a copy or a new backing count more.
    const bool same = k.tracked && db_desc.first == k.image && image.image_uid == k.image_uid &&
                      static_cast<const void*>(image.backing) == k.backing &&
                      image.write_seq - k.write_seq <= 1;
    k.image = db_desc.first;
    k.image_uid = image.image_uid;
    k.backing = image.backing;
    k.write_seq = image.write_seq;
    auto& depth = state.depth_stencil_attachment;
    if (!depth.depth_clear) {
        if (k.open && !same) {
            // Within an atlas frame taken over, the kept depth is gone or not to be trusted: all
            // four quadrants are cleared in this pass (those drawn before in it lose those draws).
            k.pending = 0xFu;
            k.cleared = 0xFu;
            if (!k.whole_now) {
                k.whole_now = true;
                ++k.whole;
            }
            k.last_whole = "the atlas image was reallocated or written within a frame";
        }
        return;
    }
    // A clear of the whole image: the atlas frame before ends, the next begins.
    const bool asked = SunKeepAsked() && !sun_hold.active; // r7 stands down at its frame end
    if (asked) {
        k.period = BbSunCascades::skip_period.load(std::memory_order_relaxed);
        k.linger = SunKeepLinger;
    } else if (k.linger != 0) {
        --k.linger;
    }
    const bool active = asked || k.linger != 0;
    if (active != k.active) {
        k.active = active;
        if (active) {
            std::printf("Sun atlas: kept quadrants (r14) on, skip period %u: the clear of the whole "
                        "atlas becomes a clear of each quadrant before the first draw into it; a "
                        "quadrant without draws keeps its depth for up to %u atlas frames\n",
                        k.period, k.period);
        } else {
            std::printf("Sun atlas: kept quadrants (r14) off (skip period %u, experiment "
                        "1099511627776 %s%s): the atlas is cleared whole again\n",
                        BbSunCascades::skip_period.load(std::memory_order_relaxed),
                        BbToggle::Experiment(BbSunCascades::kOffBit) ? "set" : "clear",
                        sun_hold.active ? ", r7 kept cascades on" : "");
        }
    }
    // A clear still owed when that atlas frame ends (SunKeepInPass found no pass to record it in;
    // never seen) was not made: its quadrant holds older depth, and the clear stays owed.
    const u32 owed = k.open ? k.pending : 0u;
    k.cleared &= ~owed;
    // What each quadrant showed in the atlas frame that ends: a drawing of it, the clear value
    // only, or depth kept from an earlier one.
    for (u32 c = 0; c < 4; ++c) {
        const u32 bit = 1u << c;
        if ((k.drawn & bit) != 0) {
            k.age[c] = 0;
            k.blank &= ~bit;
        } else if ((k.cleared & bit) != 0) {
            k.age[c] = 0;
            k.blank |= bit;
        } else {
            ++k.age[c];
            ++k.kept[c];
        }
    }
    const char* whole =
        !active    ? nullptr
        : indirect ? "an indirect draw into the atlas"
        : Regs().depth_render_control.depth_clear_enable ? "a DB clear draw"
        : !k.tracked                                     ? "the first clear or a new atlas image"
        : !same ? "the atlas image was reallocated or written outside its passes"
        : depth.stencil_clear ||
                !SunKeepClearable(state, image.info.size.width, image.info.size.height)
            ? "a pass its quadrants cannot be cleared in"
            : nullptr;
    k.open = active && !whole;
    k.tracked = active; // cleared whole now, or by quadrants from now on
    k.drawn = 0;
    k.pending = 0;
    k.cleared = 0xFu;
    k.whole_now = false;
    if (!active) {
        k.age = {};
        k.blank = 0;
    } else if (whole) {
        k.whole_now = true;
        ++k.whole;
        k.last_whole = whole;
    } else {
        // Taken over: the pass loads the atlas (and equals the next draw's pass: no restart).
        k.clear_depth = std::bit_cast<float>(depth.clear_value[0]);
        depth.depth_clear = false;
        depth.clear_value[0] = 0;
        k.take_clear = true;
        k.width = state.width;
        k.height = state.height;
        ++k.taken;
        // A quadrant kept N atlas frames in a row is overdue (the game stopped drawing it for
        // another reason): cleared with this pass's draw. One holding only the clear value is not.
        for (u32 c = 0; c < 4; ++c) {
            if (((k.blank >> c) & 1u) == 0 && k.age[c] >= k.period) {
                k.pending |= 1u << c;
                ++k.expired[c];
            }
        }
        k.pending |= owed;
        k.cleared = k.pending;
    }
    k.mode_frames += active ? 1u : 0u;
    if (++k.frames >= 600) {
        if (k.mode_frames != 0) {
            std::printf(
                "Sun atlas: kept quadrants (r14, skip period %u): %u of %u atlas frames in the "
                "mode, %llu clears of the whole atlas taken over; quadrant clears by cascade %llu "
                "%llu %llu %llu (of them after %u atlas frames kept: %llu %llu %llu %llu); kept "
                "(no draw, depth of an earlier frame) %llu %llu %llu %llu; clear rectangles %.2f "
                "an atlas frame, %llu draws with a clear owed; whole-atlas clears in the mode "
                "%llu (last: %s)\n",
                k.period, k.mode_frames, k.frames, (unsigned long long)k.taken,
                (unsigned long long)k.clears[0], (unsigned long long)k.clears[1],
                (unsigned long long)k.clears[2], (unsigned long long)k.clears[3], k.period,
                (unsigned long long)k.expired[0], (unsigned long long)k.expired[1],
                (unsigned long long)k.expired[2], (unsigned long long)k.expired[3],
                (unsigned long long)k.kept[0], (unsigned long long)k.kept[1],
                (unsigned long long)k.kept[2], (unsigned long long)k.kept[3],
                double(k.rects) / double(k.frames), (unsigned long long)k.deferred,
                (unsigned long long)k.whole, k.last_whole);
        }
        k.frames = k.mode_frames = 0;
        k.taken = k.whole = k.rects = k.deferred = 0;
        k.clears = {};
        k.expired = {};
        k.kept = {};
    }
}

void Rasterizer::SunKeepInPass(const RenderState& state) {
    auto& k = sun_keep;
    k.atlas_pass = false;
    if (k.take_clear) {
        k.take_clear = false;
        // Still the frame's clear of the whole image for the statistics and r12's guard
        // (SunAtlasSkipDraw).
        k.clear_pass = scheduler.PassesBegun();
    }
    const u32 quadrant =
        k.indirect ? 5u : SunQuadrant(scheduler.GetDynamicState(), state.width, state.height);
    k.drawn |= quadrant < 4 ? 1u << quadrant : quadrant < 6 ? 0xFu : 0u;
    if (!k.open) {
        return;
    }
    u32 clear = k.pending;
    if (quadrant < 4) {
        clear |= (1u << quadrant) & ~k.cleared;
    } else if (quadrant < 6 && k.cleared != 0xFu) {
        // Across quadrants, without a single viewport, or indirect: every quadrant not cleared yet
        // is cleared now, as the whole clear would have; this atlas frame keeps nothing.
        clear |= 0xFu & ~k.cleared;
        if (!k.whole_now) {
            k.whole_now = true;
            ++k.whole;
        }
        k.last_whole = k.indirect      ? "an indirect draw into the atlas"
                       : quadrant == 4 ? "a draw across quadrants"
                                       : "a draw without a single viewport";
    }
    k.cleared |= clear;
    if (clear == 0) {
        return;
    }
    if (!scheduler.IsRenderingWith(state) || !SunKeepClearable(state, k.width, k.height)) {
        // Owed to the next atlas pass that can (never seen: the game's atlas passes are alike);
        // this draw may land on older depth.
        k.pending = clear;
        ++k.deferred;
        return;
    }
    SunClearQuadrants(scheduler, clear, k.width, k.height, k.clear_depth);
    k.pending = 0;
    k.rects += u64(std::popcount(clear));
    for (u32 c = 0; c < 4; ++c) {
        k.clears[c] += (clear >> c) & 1u;
    }
}

}
