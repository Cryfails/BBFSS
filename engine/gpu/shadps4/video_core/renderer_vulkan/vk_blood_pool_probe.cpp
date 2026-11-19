// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100c_blood-pool-probe, r100d_blood-pool-draws): TOOL (branch dev/test-tools).
// vk_blood_pool_probe.h says where it hooks in and what it costs; blood_pool_probe.h has the knob.
#include "video_core/renderer_vulkan/vk_blood_pool_probe.h"

#include <algorithm>
#include <bit>
#include <bitset>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <new>
#include <string>
#include <string_view>
#include <utility>

#include "bbport_live_knobs.h"
#include "bbport_toggles.h"
#include "common/hash.h"
#include "video_core/amdgpu/regs.h"
#include "video_core/host_shaders/blood_pool_probe_compare_comp.h"
#include "video_core/host_shaders/blood_pool_probe_snapshot_comp.h"
#include "video_core/renderer_vulkan/ivy_sample_witness.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_workflow_probe.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
namespace R = BloodPoolProbeRules;
constexpr const char* KnobName = "BB_BLOOD_POOL_PROBE";
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr vk::DeviceSize CountsBytes = vk::DeviceSize(R::CaptureFrames) * R::MaxDraws * R::RecordWords * 4;
constexpr vk::DeviceSize OwnersBytes = vk::DeviceSize(R::OwnerMaps) * R::MaxSide * R::MaxSide * 4;
// Two native R466 fixtures. These discriminate diagnostic requests only.
struct IndexFixture {
    const char* name;
    u32 x0, y0, x1, y1, count, first;
};
constexpr std::array<IndexFixture, 2> IndexFixtures{{
    {"raised", 807, 381, 810, 384, 14400, 1839104},
    {"pool", 568, 927, 573, 932, 660, 3261136},
}};
constexpr std::array<u32, 6> LayerBindings{7, 12, 13, 14, 15, 18};
constexpr u32 IndexVs = 0xc829ee58, IndexPs = 0xdbb222eb;
constexpr u32 IndexSceneWidth = 1920, IndexSceneHeight = 1080;
constexpr u64 IndexBudget = 60240;
static_assert((IndexFixtures[0].count + IndexFixtures[1].count) * sizeof(u32) == IndexBudget);

/// Role names (DrawInfo::role): 1-8 the G-buffer pass's targets 0-7, then a light draw's and the
/// scene colour (RGBA16F with the scene depth).
constexpr const char* RoleNames[] = {"", "nrm", "mat", "alb", "spc", "g4", "g5", "g6", "g7", "lit", "scn"};
constexpr u8 RoleLight = 9, RoleScene = 10;
constexpr const char* FuncNames[] = {"never", "lt", "eq", "le", "gt", "ne", "ge", "always"};

/// A colour target format the passes sample as floats (an integer format would need another
/// texture type): its short name in the log, else null.
const char* ColourName(vk::Format format) {
    switch (format) {
    case vk::Format::eR8G8B8A8Unorm:
        return "8";
    case vk::Format::eR8G8B8A8Srgb:
        return "8s";
    case vk::Format::eB8G8R8A8Unorm:
        return "b8";
    case vk::Format::eB8G8R8A8Srgb:
        return "b8s";
    case vk::Format::eA2B10G10R10UnormPack32:
        return "10";
    case vk::Format::eB10G11R11UfloatPack32:
        return "11f";
    case vk::Format::eR16G16B16A16Sfloat:
        return "16f";
    case vk::Format::eR16G16Sfloat:
        return "rg16f";
    case vk::Format::eR16Sfloat:
        return "r16f";
    case vk::Format::eR32Sfloat:
        return "32f";
    case vk::Format::eR32G32Sfloat:
        return "rg32f";
    case vk::Format::eR32G32B32A32Sfloat:
        return "128f";
    case vk::Format::eR8Unorm:
        return "r8";
    case vk::Format::eR8G8Unorm:
        return "rg8";
    case vk::Format::eR16G16B16A16Unorm:
        return "16u";
    default:
        return nullptr;
    }
}

const char* DepthName(vk::Format format) {
    switch (format) {
    case vk::Format::eD32SfloatS8Uint:
        return "d32s8";
    case vk::Format::eD32Sfloat:
        return "d32";
    case vk::Format::eD24UnormS8Uint:
        return "d24s8";
    case vk::Format::eD16Unorm:
        return "d16";
    default:
        return "d?";
    }
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.sampler = {}, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

/// What a pass's commands begin with: the game's writes before it are done.
void BeginBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute, ReadWrite);
}

/// And end with: the game's next work waits for the pass's reads, the next pass for its writes.
void EndBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, Compute, ReadWrite, AllCommands,
                              vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
}

/// Records one pass: the nine targets (unused bindings hold a view of a used one; the mask keeps
/// the shader off them), the prints, and for COMPARE the counters and owner maps.
void RecordPass(vk::CommandBuffer cmd, vk::Pipeline pipeline, vk::PipelineLayout layout,
                const std::array<vk::ImageView, R::Targets>& views, vk::Buffer prints, vk::Buffer counts,
                vk::Buffer owners, const R::Push& push, u32 groups_x, u32 groups_y) {
    BeginBarrier(cmd);
    std::array<vk::DescriptorImageInfo, R::Targets> images{};
    std::array<vk::WriteDescriptorSet, R::Targets + 3> writes{};
    for (u32 t = 0; t < R::Targets; ++t) {
        images[t] = Info(views[t]);
        writes[t] = {.dstBinding = t,
                     .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eSampledImage,
                     .pImageInfo = &images[t]};
    }
    const std::array<vk::DescriptorBufferInfo, 3> buffers{
        vk::DescriptorBufferInfo{prints, 0, VK_WHOLE_SIZE},
        vk::DescriptorBufferInfo{counts, 0, VK_WHOLE_SIZE},
        vk::DescriptorBufferInfo{owners, 0, VK_WHOLE_SIZE}};
    const u32 buffer_count = counts ? 3u : 1u;
    for (u32 b = 0; b < buffer_count; ++b) {
        writes[R::Targets + b] = {.dstBinding = R::Targets + b,
                                  .descriptorCount = 1,
                                  .descriptorType = vk::DescriptorType::eStorageBuffer,
                                  .pBufferInfo = &buffers[b]};
    }
    cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
    cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                             vk::ArrayProxy<const vk::WriteDescriptorSet>(R::Targets + buffer_count,
                                                                          writes.data()));
    cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
    cmd.dispatch(groups_x, groups_y, 2);
    EndBarrier(cmd);
}
} // namespace

namespace {
constexpr u32 FoliageLimit = 128;
constexpr u32 FoliageGeneralLimit = 64; // reserve the other half for G-buffer cutouts
constexpr u32 FoliageSelectedLimit = 16; // part of the general half, when selectors are configured
constexpr u32 FoliageSelectorLimit = 8;
constexpr u32 FoliageOwners = 8;
constexpr u32 FoliageControls = 4;

bool FoliageWanted() {
    static const bool wanted = [] {
        const char* value = std::getenv("BB_FOLIAGE_MASK_PROBE");
        return value && std::strcmp(value, "1") == 0;
    }();
    return wanted;
}

bool IvyOwnerWanted() {
    static const bool wanted = [] {
        const char* value = std::getenv("BB_IVY_OWNER_WITNESS");
        return IvyMaterialProbe::Wanted() && value && std::strcmp(value, "1") == 0;
    }();
    return wanted;
}

// Startup selectors name exact draw ranges. Multiple matches retain separate
// records unless their full copied facts compare equal.
struct FoliageDrawKey {
    u64 vs = 0, ps = 0;
    u32 count = 0, first = 0;
    bool operator==(const FoliageDrawKey&) const = default;
};

struct FoliageDrawSelection {
    std::array<FoliageDrawKey, FoliageSelectorLimit> keys{};
    u32 count = 0;
    bool invalid = false;

    u8 Find(FoliageDrawKey key) const {
        for (u32 i = 0; i < count; ++i) {
            if (keys[i] == key) {
                return u8(i + 1);
            }
        }
        return 0;
    }
};

FoliageDrawSelection ParseFoliageDraws(std::string_view text) {
    FoliageDrawSelection out;
    if (text.empty()) {
        return out;
    }
    if (text.size() > FoliageSelectorLimit * (16 + 16 + 10 + 10 + 4)) {
        return {.invalid = true};
    }
    const auto read = [](std::string_view word, auto& value, int base) {
        if (word.empty()) {
            return false;
        }
        const char* end = word.data() + word.size();
        const auto result = std::from_chars(word.data(), end, value, base);
        return result.ec == std::errc{} && result.ptr == end;
    };
    for (;;) {
        if (out.count == out.keys.size()) {
            return {.invalid = true};
        }
        const auto end = text.find(';');
        std::string_view entry = text.substr(0, end);
        std::array<std::string_view, 4> fields;
        for (u32 i = 0; i < fields.size() - 1; ++i) {
            const auto sep = entry.find(':');
            if (sep == std::string_view::npos) {
                return {.invalid = true};
            }
            fields[i] = entry.substr(0, sep);
            entry.remove_prefix(sep + 1);
        }
        fields.back() = entry;
        FoliageDrawKey key;
        if (!read(fields[0], key.vs, 16) || !read(fields[1], key.ps, 16) ||
            !read(fields[2], key.count, 10) || !read(fields[3], key.first, 10) ||
            !key.count || out.Find(key)) {
            return {.invalid = true};
        }
        out.keys[out.count++] = key;
        if (end == std::string_view::npos) {
            return out;
        }
        text.remove_prefix(end + 1);
    }
}

const FoliageDrawSelection& FoliageSelectedDraws() {
    static const auto selected = [] {
        const char* text = std::getenv("BB_FOLIAGE_MASK_PROBE_DRAWS");
        return ParseFoliageDraws(text ? std::string_view(text) : std::string_view{});
    }();
    return selected;
}

struct FoliageTarget {
    u64 uid = 0;
    VideoCore::ImageId id{};
    BloodPoolProbe::FoliageView view{};
    std::array<u32, 3> size{};
    bool checked = false;
    bool operator==(const FoliageTarget&) const = default;
};

struct FoliageMrt {
    std::array<FoliageTarget, 9> targets{}; // guest color 0..7, then depth
    std::array<u64, 2> address{};
    std::array<u32, 2> target_mask{}, shader_mask{}, host_write{}, samples{};
    std::array<bool, 2> bound{}, stores{};
    std::array<u32, 6> viewport{}; // x/y/z offset and scale as register bits
    std::array<AmdGpu::BlendControl, 8> blend{};
    u32 guest_mrt = 0, host_mrt = 0, attachments = 0, color_mode = 0;
    u32 depth_samples = 0, motion = 0, depth_func = 0;
    bool ps = false, same_depth = false, depth_test = false, depth_write = false;
    bool indirect = false, lamps_pending = false;
    u8 phase = 0;
    bool operator==(const FoliageMrt&) const = default;
};

constexpr unsigned long long Log64(u64 value) {
    return static_cast<unsigned long long>(value);
}
} // namespace

struct BloodPoolProbe::FoliageCapture {
    struct Frame {
        std::array<u8, R::MaxDraws> facts{}, states{}; // index + 1, zero if unavailable
        std::bitset<R::MaxDraws> issued;
        u64 draws = 0, delivered = 0, indirect = 0, orphan_after = 0;
        u64 export6 = 0, bound6 = 0, write6 = 0, host_write6 = 0, same_depth = 0;
        u64 host_location6 = 0, host_target6 = 0;
        u64 census_overflow = 0, target_gap = 0, export_disagrees = 0;
        u32 stats_frame = 0, stats_end = 0, fact_overflow = 0, selection_mismatch = 0;
        bool gbuffer = false;
    };
    struct CensusEntry {
        FoliageMrt state{};
        std::array<u64, R::CaptureFrames> seen{}, delivered{};
        u32 frame = 0, ordinal = 0;
        u64 vs = 0, ps = 0;
    };

    struct IvyDraw {
        u64 tick = 0;
        u32 ordinal = 0, stats = 0;
        std::array<float, 2> jitter{};
    };
    std::optional<IvyDraw> ivy;
    std::array<Frame, R::CaptureFrames> frames{};
    std::array<CensusEntry, FoliageLimit> census{};
    std::array<FoliageFacts, FoliageLimit> facts{};
    FoliageDrawSelection selection{};
    std::array<u32, FoliageSelectorLimit> selection_used{};
    u32 states_used = 0, general_used = 0, cutout_used = 0, open_ordinal = 0;
    u8 current_state = 0;
    bool draw_open = false, note_wanted = false, camera_gbuffer = false;
};

BloodPoolProbe::FoliageView BloodPoolProbe::FoliageView::From(const VideoCore::ImageViewInfo& view) {
    return {
        .range = {view.range.base.level, view.range.extent.levels,
                  view.range.base.layer, view.range.extent.layers},
        .swizzle = {u32(view.mapping.r), u32(view.mapping.g), u32(view.mapping.b), u32(view.mapping.a)},
        .type = u32(view.type), .format = u32(view.format), .min_lod = view.min_lod,
        .storage = view.is_storage,
    };
}

bool BloodPoolProbe::FoliageCapturing() const {
    return foliage && state == State::Capturing;
}

std::optional<BloodPoolProbe::FoliageToken> BloodPoolProbe::FoliageNoteToken(
    bool indexed, u32 first_index) const {
    if (!FoliageCapturing() || !note_due || note_ordinal >= infos[capture].size()) {
        return std::nullopt;
    }
    const auto& draw = infos[capture][note_ordinal];
    const u8 selected = indexed && !draw.indirect
                            ? foliage->selection.Find({draw.vs, draw.ps, draw.indices, first_index})
                            : 0;
    if (!foliage->note_wanted && !selected) {
        return std::nullopt;
    }
    return FoliageToken{foliage_serial, capture, note_ordinal, foliage->camera_gbuffer, selected};
}

bool BloodPoolProbe::IvyOwnerAllows(FoliageToken token) const {
    return !IvyOwnerWanted() || token.frame == R::CaptureFrames - 1;
}

void BloodPoolProbe::NoteIvyOwnerSample(u64 serial, u32 frame, u32 ordinal, u64 tick,
                                       std::array<float, 2> jitter) {
    if (IvyOwnerWanted() && FoliageCapturing() && serial == foliage_serial &&
        frame == capture && frame == R::CaptureFrames - 1 && !foliage->ivy) {
        foliage->ivy = FoliageCapture::IvyDraw{
            tick, ordinal, BbStats::frame_number.load(std::memory_order_relaxed), jitter};
    }
}

void BloodPoolProbe::NoteFoliageFacts(FoliageToken token, const FoliageFacts& facts) {
    if (!FoliageCapturing() || token.serial != foliage_serial || token.frame != capture ||
        token.ordinal != note_ordinal || token.ordinal >= infos[capture].size() ||
        note_due || (!foliage->note_wanted && !token.selected) ||
        !infos[capture][token.ordinal].noted || token.camera_gbuffer != foliage->camera_gbuffer ||
        token.selected > foliage->selection.count) {
        return;
    }
    auto& cap = *foliage;
    auto& frame = cap.frames[capture];
    u8& slot = frame.facts[token.ordinal];
    if (slot) {
        return;
    }
    cap.note_wanted = false;
    const bool cutout = facts.camera_gbuffer && facts.discard;
    const u32 reserved = cap.selection.count ? FoliageSelectedLimit : 0;
    u32 begin = cutout ? FoliageGeneralLimit : reserved;
    u32 limit = cutout ? FoliageLimit : FoliageGeneralLimit;
    u32* used = cutout ? &cap.cutout_used : &cap.general_used;
    if (token.selected) {
        const auto& draw = infos[capture][token.ordinal];
        const auto& key = cap.selection.keys[token.selected - 1];
        if (!draw.indexed || draw.indirect || !facts.indexed || facts.indirect ||
            key != FoliageDrawKey{draw.vs, draw.ps, draw.indices, draw.first_index} ||
            key != FoliageDrawKey{facts.vs, facts.ps, facts.count, facts.first_index}) {
            ++frame.selection_mismatch;
            return;
        }
        // A busy selector cannot use another selector's share of the bounded pool.
        const u32 index = token.selected - 1;
        begin = index * FoliageSelectedLimit / cap.selection.count;
        limit = (index + 1) * FoliageSelectedLimit / cap.selection.count;
        used = &cap.selection_used[index];
    }
    for (u32 i = begin; i < begin + *used; ++i) {
        if (cap.facts[i] == facts) {
            slot = u8(i + 1);
            return;
        }
    }
    if (begin + *used == limit) {
        ++frame.fact_overflow;
        return;
    }
    const u32 i = begin + (*used)++;
    cap.facts[i] = facts;
    slot = u8(i + 1);
}

void BloodPoolProbe::CensusFoliage(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                                  const std::array<VideoCore::ImageId, 8>& targets,
                                  VideoCore::ImageId depth, const FoliageTargetViews& views,
                                  u32 n, u8 phase, bool indirect, bool lamps_pending) {
    auto& cap = *foliage;
    auto& frame = cap.frames[capture];
    if (frame.draws++ == 0) {
        frame.stats_frame = BbStats::frame_number.load(std::memory_order_relaxed);
    }
    frame.indirect += indirect;
    const auto& key = pipeline.GetGraphicsKey();
    const auto* ps = pipeline.GetStages()[u32(Shader::SwStage::Fragment)];
    FoliageMrt entry;
    entry.ps = ps != nullptr;
    entry.guest_mrt = ps ? ps->mrt_mask : 0;
    if (ps) {
        entry.stores = {ps->stores.GetAny(Shader::IR::Attribute::RenderTarget6),
                         ps->stores.GetAny(Shader::IR::Attribute::RenderTarget7)};
    }
    entry.host_mrt = key.mrt_mask;
    entry.attachments = key.num_color_attachments;
    entry.color_mode = u32(regs.color_control.mode);
    entry.depth_samples = key.depth_samples;
    entry.motion = key.motion_vectors;
    entry.phase = phase;
    entry.same_depth = depth && depth == scene_depth;
    entry.indirect = indirect;
    entry.lamps_pending = lamps_pending;
    entry.depth_test = regs.depth_control.depth_enable && bool(depth);
    entry.depth_write = entry.depth_test && regs.depth_control.depth_write_enable;
    entry.depth_func = u32(regs.depth_control.depth_func);
    const auto& vp = regs.viewports[0];
    entry.viewport = std::bit_cast<std::array<u32, 6>>(
        std::array<float, 6>{vp.xoffset, vp.yoffset, vp.zoffset, vp.xscale, vp.yscale, vp.zscale});
    for (u32 i = 0; i < 2; ++i) {
        const u32 cb = 6 + i;
        const auto& buffer = regs.color_buffers[cb];
        entry.bound[i] = bool(buffer);
        entry.address[i] = buffer.Address();
        entry.target_mask[i] = regs.color_target_mask.GetMask(cb);
        entry.shader_mask[i] = regs.color_shader_mask.GetMask(cb);
        entry.host_write[i] = u32(key.write_masks[cb]);
        entry.samples[i] = key.color_samples[cb];
    }
    const bool export6 = (entry.guest_mrt & (1u << 6)) != 0;
    const bool enabled = regs.color_control.mode != AmdGpu::ColorControl::OperationMode::Disable;
    frame.export6 += export6 || entry.stores[0];
    frame.export_disagrees += export6 != entry.stores[0];
    frame.bound6 += entry.bound[0];
    frame.write6 += enabled && entry.bound[0] && (entry.target_mask[0] & entry.shader_mask[0]) != 0;
    const bool host_location6 = (entry.host_mrt & (1u << 6)) != 0;
    frame.host_location6 += host_location6;
    frame.host_write6 += host_location6 && entry.host_write[0] != 0;
    frame.same_depth += entry.same_depth;

    bool target_gap = false;
    for (u32 i = 0; i < entry.targets.size(); ++i) {
        auto& target = entry.targets[i];
        const bool color = i < targets.size();
        target.id = color ? (((key.mrt_mask >> i) & 1u) ? targets[i] : VideoCore::ImageId{}) : depth;
        if (color) {
            entry.blend[i] = key.blend_controls[i];
            // The engine can add motion location 7 at BeginRendering, outside cb_descs.
            const bool engine_motion = i == Shader::MotionVectors::Output &&
                                       (key.motion_vectors & Shader::MotionVectors::VertexOutputs) != 0;
            target_gap |= !target.id && !engine_motion && key.write_masks[i] != vk::ColorComponentFlags{};
        }
        if (!target.id) {
            continue;
        }
        if (const auto* image = texture_cache.TryGetImage(target.id, 0);
            image && image->image_uid && texture_cache.IsRegisteredImage(target.id, image->image_uid)) {
            target.uid = image->image_uid;
            target.size = {image->info.size.width, image->info.size.height, image->info.size.depth};
            if (views[i]) {
                target.view = FoliageView::From(*views[i]);
                target.checked = target.view.range[1] && target.view.range[3];
            }
        }
        target_gap |= !target.checked;
    }
    frame.host_target6 += bool(entry.targets[6].id);
    frame.target_gap += target_gap;
    cap.draw_open = true;
    cap.open_ordinal = n;
    cap.camera_gbuffer = phase == R::Gbuffer;
    cap.note_wanted = entry.same_depth || cap.camera_gbuffer;

    // Consecutive draws often share the full state. The bounded scan uses full equality.
    u32 i = cap.current_state ? cap.current_state - 1u : cap.states_used;
    if (i == cap.states_used || !(cap.census[i].state == entry)) {
        for (i = 0; i < cap.states_used; ++i) {
            if (cap.census[i].state == entry) {
                break;
            }
        }
    }
    if (i == cap.states_used) {
        if (i == FoliageLimit) {
            ++frame.census_overflow;
            cap.current_state = 0;
            return;
        }
        cap.census[i] = {.state = entry, .frame = capture, .ordinal = n,
                         .vs = pipeline.GetStage(Shader::SwStage::Vertex).pgm_hash,
                         .ps = ps ? ps->pgm_hash : 0};
        ++cap.states_used;
    }
    cap.current_state = u8(i + 1);
    ++cap.census[i].seen[capture];
    if (n < R::MaxDraws) {
        frame.states[n] = cap.current_state;
    }
}

bool BloodPoolProbe::Wanted() {
    static const bool wanted = R::Parse(std::getenv(KnobName)).kind != R::Kind::Off ||
                               GlassFindRules::Wanted(std::getenv(GlassFindRules::FindKnob),
                                                      std::getenv(GlassFindRules::RectKnob)); // bbport (t86q)
    return wanted;
}

BloodPoolProbe::BloodPoolProbe(const Instance& instance_, Scheduler& scheduler_,
                               VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                               SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_} {
    const char* layer_env = std::getenv("BB_BLOOD_BOUND_LAYERS");
    bound_layer_enabled = layer_env && std::string_view(layer_env) == "1";
    const char* index_env = std::getenv("BB_BLOOD_BOUND_INDEX");
    bound_index_enabled = index_env && std::string_view(index_env) == "1";
    const char* env = std::getenv(KnobName);
    BbReport::Printf("Blood pool probe (r100d, TOOL): on (%s=%.32s); a box x0:y0:x1:y1 in scene pixels "
                     "(this value or the live knobs file) is probed after %u frames with a G-buffer pass "
                     "(%u after a live change): every draw of %u frames\n",
                     KnobName, env ? env : "", R::ArmFramesStart, R::ArmFramesLive, R::CaptureFrames);
    knob_generation = BbLiveKnobs::Generation();
    TakeKnob(true);
    // bbport (t86q_glass-finder, TOOL)
    find_frames = GlassFindRules::ParseFrames(std::getenv(GlassFindRules::FramesKnob));
    BbReport::Printf("Glass finder (t86q, TOOL): on (%s=%.16s, %s=%.40s); BB_GLASS_FIND=1 lists every draw of the "
                     "last of %u scene frames, BB_GLASS_FIND_RECT=x0,y0,x1,y1 (a 1280x720 picture's pixels, or "
                     "fractions) lists the draws that changed pixels inside the rectangle\n",
                     GlassFindRules::FindKnob, std::getenv(GlassFindRules::FindKnob) ? std::getenv(GlassFindRules::FindKnob) : "",
                     GlassFindRules::RectKnob, std::getenv(GlassFindRules::RectKnob) ? std::getenv(GlassFindRules::RectKnob) : "",
                     find_frames);
    TakeGlass(true);
}

BloodPoolProbe::~BloodPoolProbe() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    FreeBuffer(prints);
    FreeBuffer(counts);
    FreeBuffer(owners);
}

bool BloodPoolProbe::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = static_cast<VkBufferUsageFlags>(usage),
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (host) {
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    }
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &out.allocation, &info) !=
        VK_SUCCESS) {
        return false;
    }
    out.buffer = raw;
    out.mapped = info.pMappedData;
    return !host || out.mapped;
}

void BloodPoolProbe::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

bool BloodPoolProbe::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::Create(instance, snapshot_pass.set_layout, snapshot_pass.layout, snapshot_pass.pipeline,
                           {eSampledImage, eSampledImage, eSampledImage, eSampledImage, eSampledImage,
                            eSampledImage, eSampledImage, eSampledImage, eSampledImage, eStorageBuffer},
                           sizeof(R::Push), BLOOD_POOL_PROBE_SNAPSHOT_COMP, "Blood pool probe snapshot") &&
        EffectPass::Create(instance, compare_pass.set_layout, compare_pass.layout, compare_pass.pipeline,
                           {eSampledImage, eSampledImage, eSampledImage, eSampledImage, eSampledImage,
                            eSampledImage, eSampledImage, eSampledImage, eSampledImage, eStorageBuffer,
                            eStorageBuffer, eStorageBuffer},
                           sizeof(R::Push), BLOOD_POOL_PROBE_COMPARE_COMP, "Blood pool probe compare") &&
        MakeBuffer(counts, CountsBytes, true,
                   vk::BufferUsageFlagBits::eStorageBuffer | vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(owners, OwnersBytes, true,
                   vk::BufferUsageFlagBits::eStorageBuffer | vk::BufferUsageFlagBits::eTransferDst);
    if (!made) {
        Fail("this GPU cannot run the passes");
        return false;
    }
    return true;
}

void BloodPoolProbe::Fail(const char* why) {
    failed = true;
    state = State::Idle;
    pending = {};
    BbReport::Printf("Blood pool probe (r100d): off - %s\n", why);
}

vk::ImageView BloodPoolProbe::CachedView(const VideoCore::Image& image, vk::Format format,
                                         vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid && entry.format == format &&
            entry.aspect == aspect) {
            entry.last_use = ++view_uses;
            return entry.view;
        }
        if (entry.last_use < oldest->last_use) {
            oldest = &entry;
        }
    }
    const auto device = instance.GetDevice();
    if (oldest->view) {
        scheduler.DeferOperation([device, view = oldest->view] { device.destroyImageView(view); });
    }
    *oldest = {
        .image = handle,
        .uid = image.image_uid,
        .format = format,
        .aspect = aspect,
        .view = Check<"create blood pool probe view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

vk::ImageView BloodPoolProbe::ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect) {
    auto& image = texture_cache.GetImage(id);
    if (scene_targets.Reduced() && scene_targets.EligibleScene(image)) {
        VideoCore::ImageViewInfo info;
        info.format = image.info.pixel_format;
        const auto proxy = scene_targets.Read(id, info, Compute, ShaderRead);
        return (proxy.usage & vk::ImageUsageFlagBits::eSampled) ? proxy.view : vk::ImageView{};
    }
    if (!(image.usage_flags & vk::ImageUsageFlagBits::eSampled)) {
        return {};
    }
    const auto view = CachedView(image, image.info.pixel_format, aspect);
    runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, ShaderRead);
    return view;
}

void BloodPoolProbe::TakeKnob(bool at_start) {
    const BbLiveKnobs::Text text = BbLiveKnobs::Lookup(KnobName);
    const char* value = text.Get();
    const R::Knob k = R::Parse(value);
    switch (k.kind) {
    case R::Kind::Box:
        if (!at_start && k.SameBox(last_taken)) {
            return; // (another knob of the file changed)
        }
        last_taken = k;
        next = k;
        next_live = text.in_file;
        next_glass = false; // bbport (t86q): a blood box replaces a waiting glass rectangle
        return;
    case R::Kind::Off:
    case R::Kind::On:
        last_taken = {};
        next = {};
        if (state == State::Armed && !box_glass && !arm_find) { // bbport (t86q): not a glass arming
            state = State::Idle;
            BbReport::Printf("Blood pool probe (r100d): box x %u-%u y %u-%u dropped before probing (%s=%.16s)\n",
                             box.x0, box.x1, box.y0, box.y1, KnobName, value ? value : "");
        }
        return;
    case R::Kind::Bad:
        BbReport::Printf("Blood pool probe (r100d): %s=%.40s is no box (x0:y0:x1:y1, decimal, x0<=x1, "
                         "y0<=y1); nothing changed\n",
                         KnobName, value ? value : "");
        return;
    }
}

// bbport (t86q_glass-finder, TOOL): the glass finder. See t86q_glass-finder.py's header and glass_find.h.
static std::string PhaseText(u8 phases) {
    static constexpr const char* Letters = "PGBLA";
    std::string text;
    for (u32 b = 0; b < 5; ++b) {
        if ((phases >> b) & 1u) {
            text += Letters[b];
        }
    }
    return text;
}

void BloodPoolProbe::TakeGlass(bool at_start) {
    namespace G = GlassFindRules;
    const BbLiveKnobs::Text find_text = BbLiveKnobs::Lookup(G::FindKnob);
    const G::Mode mode = G::ParseMode(find_text.Get());
    if (mode == G::Mode::Bad) {
        BbReport::Printf("Glass finder (t86q): %s=%.40s is neither off, idle nor 1; nothing changed\n", G::FindKnob,
                         find_text.Get() ? find_text.Get() : "");
    } else {
        if (mode == G::Mode::Wide && glass_mode != G::Mode::Wide) {
            find_pending = true;
            find_live = find_text.in_file;
        } else if (mode != G::Mode::Wide) {
            find_pending = false;
            if (state == State::Armed && arm_find) {
                state = State::Idle;
                BbReport::Printf("Glass finder (t86q): wide find dropped before it ran (%s=%.16s)\n", G::FindKnob,
                                 find_text.Get() ? find_text.Get() : "");
            }
        }
        glass_mode = mode;
    }
    const BbLiveKnobs::Text rect_text = BbLiveKnobs::Lookup(G::RectKnob);
    const G::Rect rect = G::ParseRect(rect_text.Get());
    switch (rect.kind) {
    case R::Kind::Box:
        if (!at_start && rect.Same(glass_taken)) {
            break; // (another knob of the file changed)
        }
        glass_taken = rect;
        glass_rect = rect;
        std::snprintf(glass_text, sizeof(glass_text), "%.40s", rect_text.Get());
        next_glass = true;
        glass_live = rect_text.in_file;
        break;
    case R::Kind::Bad:
        BbReport::Printf("Glass finder (t86q): %s=%.40s is no rectangle (x0,y0,x1,y1 of a 1280x720 picture or "
                         "fractions, x0<=x1, y0<=y1); nothing changed\n",
                         G::RectKnob, rect_text.Get() ? rect_text.Get() : "");
        break;
    default:
        glass_taken = {};
        next_glass = false;
        if (state == State::Armed && box_glass) {
            state = State::Idle;
            BbReport::Printf("Glass finder (t86q): rectangle dropped before it ran (%s off)\n", G::RectKnob);
        }
        break;
    }
}

/// What makes two draws one run: the state the finder lists (not the pair, which the key holds apart).
u64 BloodPoolProbe::FindSig(const DrawInfo& d) {
    u64 h = 0xcbf29ce484222325ull;
    const auto mix = [&h](u64 v) { h = (h ^ v) * 0x100000001b3ull; };
    mix(d.mrt);
    mix(d.blend);
    mix(d.write_masks);
    mix(u64(d.depth_test ? 1u : 0u) | u64(d.depth_write ? 2u : 0u) | u64(d.depth_func) << 2 |
        u64(d.indirect ? 1u : 0u) << 8 | u64(d.light ? 1u : 0u) << 9 | u64(d.blend_separate ? 1u : 0u) << 10);
    for (u32 cb = 0; cb < 8; ++cb) {
        mix(d.format[cb]);
    }
    mix(d.depth_format);
    for (const u8 f : d.blend_f) {
        mix(f);
    }
    mix(d.blend_cb);
    return h;
}

/// " cb:format/role+b" per colour target (+b: blending on, mHEX: a partial write mask), then " d:format func w"
/// for the depth; with counts the pixels each changed a frame ("=n").
std::string BloodPoolProbe::TargetsText(const DrawInfo& d, const u32* counts, u32 frames) {
    std::string out;
    char part[96];
    for (u32 cb = 0; cb < 8; ++cb) {
        if (((d.mrt >> cb) & 1u) == 0 || d.format[cb] == 0) {
            continue;
        }
        const char* name = ColourName(vk::Format(d.format[cb]));
        const u32 mask = (d.write_masks >> (4 * cb)) & 15u;
        std::snprintf(part, sizeof(part), " %u:%s%s%s%s", cb, name ? name : "int", d.role[cb] ? "/" : "",
                      RoleNames[d.role[cb]], (d.blend >> cb) & 1u ? "+b" : "");
        out += part;
        if (mask != 15u) {
            std::snprintf(part, sizeof(part), "m%x", mask);
            out += part;
        }
        if (counts) {
            std::snprintf(part, sizeof(part), "=%llu",
                          static_cast<unsigned long long>(counts[R::WordTarget0 + cb] / frames));
            out += part;
        }
    }
    if (d.depth_test) {
        std::snprintf(part, sizeof(part), " d:%s %s%s", DepthName(vk::Format(d.depth_format)),
                      FuncNames[d.depth_func], d.depth_write ? " w" : "");
        out += part;
        if (counts) {
            std::snprintf(part, sizeof(part), "=%llu",
                          static_cast<unsigned long long>(counts[R::WordTarget0 + R::DepthTarget] / frames));
            out += part;
        }
    } else {
        out += " d:-";
    }
    return out;
}

std::string BloodPoolProbe::BlendText(const DrawInfo& d) {
    namespace G = GlassFindRules;
    if (d.blend_cb == 255) {
        return "opaque";
    }
    char text[160];
    if (d.blend_separate) {
        std::snprintf(text, sizeof(text), "blend cb%u c %s*s+%s*d (%s) a %s*s+%s*d (%s)", u32(d.blend_cb),
                      G::FactorName(d.blend_f[0]), G::FactorName(d.blend_f[1]), G::FuncName(d.blend_f[2]),
                      G::FactorName(d.blend_f[3]), G::FactorName(d.blend_f[4]), G::FuncName(d.blend_f[5]));
    } else {
        std::snprintf(text, sizeof(text), "blend cb%u %s*s+%s*d (%s)", u32(d.blend_cb), G::FactorName(d.blend_f[0]),
                      G::FactorName(d.blend_f[1]), G::FuncName(d.blend_f[2]));
    }
    return text;
}

/// "idx N first F @index buffer xI tex count hHASH address:WxH:format ..." (what Note kept).
std::string BloodPoolProbe::DrawText(const DrawInfo& d) {
    std::string out;
    char part[96];
    if (d.indirect) {
        out = "idx indirect";
    } else if (!d.noted) {
        std::snprintf(part, sizeof(part), "idx %u (no note)", d.indices);
        out = part;
    } else if (!d.indexed) {
        std::snprintf(part, sizeof(part), "idx %u (not indexed)", d.indices);
        out = part;
    } else {
        std::snprintf(part, sizeof(part), "idx %u first %u @%llx", d.indices, d.first_index,
                      static_cast<unsigned long long>(d.index_address));
        out = part;
    }
    if (d.instances > 1) {
        std::snprintf(part, sizeof(part), " x%u", d.instances);
        out += part;
    }
    if (d.noted) {
        std::snprintf(part, sizeof(part), " tex %u h%08x", d.textures_all, d.texture_hash);
        out += part;
        for (u32 i = 0; i < d.texture_count; ++i) {
            std::snprintf(part, sizeof(part), " %llx:%ux%u:%u", static_cast<unsigned long long>(d.textures[i].address),
                          d.textures[i].width, d.textures[i].height, d.textures[i].format);
            out += part;
        }
    }
    return out;
}

/// Wide find: at the end of each frame of the window (infos[0] holds the frame's draws).
void BloodPoolProbe::FindFrameEnd() {
    auto& list = infos[0];
    if (!frame_gbuffer || camera_motion.PreviewFrame()) { // a frame of a menu or a load: not counted
        list.clear();
        over_cap[0] = 0;
        return;
    }
    for (const DrawInfo& d : list) {
        FindSum& s = find_sums[std::make_tuple(d.vs, d.ps, FindSig(d))];
        if (!s.have) {
            s.have = true;
            s.rep = d;
        }
        ++s.draws;
        if (s.last_frame != find_frame + 1u) {
            s.last_frame = find_frame + 1u;
            ++s.frames;
        }
        if (!d.indirect) {
            s.idx_min = std::min(s.idx_min, d.indices);
            s.idx_max = std::max(s.idx_max, d.indices);
        }
        s.phases |= d.phase;
    }
    if (++find_frame < find_frames) {
        list.clear();
        over_cap[0] = 0;
        return;
    }
    FindLog();
    list.clear();
    over_cap[0] = 0;
    state = State::Idle;
}

void BloodPoolProbe::FindLog() {
    const auto& list = infos[0];
    u32 blended = 0, no_colour = 0, gbuffer = 0;
    for (const DrawInfo& d : list) {
        blended += d.blend_cb != 255 ? 1u : 0u;
        no_colour += d.mrt == 0 ? 1u : 0u;
        gbuffer += d.phase == R::Gbuffer ? 1u : 0u;
    }
    struct Run {
        std::tuple<u64, u64, u64> key;
        u32 first = 0, last = 0, n = 0, idx_min = ~0u, idx_max = 0;
    };
    std::vector<Run> runs;
    for (u32 i = 0; i < list.size(); ++i) {
        const DrawInfo& d = list[i];
        const auto key = std::make_tuple(d.vs, d.ps, FindSig(d));
        if (runs.empty() || runs.back().key != key) {
            runs.push_back({});
            runs.back().key = key;
            runs.back().first = i;
        }
        Run& run = runs.back();
        run.last = i;
        ++run.n;
        if (!d.indirect) {
            run.idx_min = std::min(run.idx_min, d.indices);
            run.idx_max = std::max(run.idx_max, d.indices);
        }
    }
    u32 blended_keys = 0;
    for (const auto& [key, sum] : find_sums) {
        blended_keys += sum.rep.blend_cb != 255 ? 1u : 0u;
    }
    char line[1024];
    std::snprintf(line, sizeof(line),
                  "Glass find (t86q): wide find, %u scene frames (the last one is listed), %u draws in it (%u over the "
                  "cap of %u), %zu runs of equal draws, %u blended, %u with no colour target (shadow passes), %u "
                  "G-buffer pass draws; %zu (pair, state) keys over the window, %u blended",
                  find_frames, u32(list.size()) + over_cap[0], over_cap[0], R::MaxDraws, runs.size(), blended,
                  no_colour, gbuffer, find_sums.size(), blended_keys);
    BbReport::Printf("%s\n", line);
    // The blended (pair, state) keys, the likeliest glass first: most draws a frame.
    std::vector<const FindSum*> sums;
    for (const auto& [key, sum] : find_sums) {
        if (sum.rep.blend_cb != 255) {
            sums.push_back(&sum);
        }
    }
    std::sort(sums.begin(), sums.end(), [](const FindSum* a, const FindSum* b) {
        return a->draws != b->draws ? a->draws > b->draws : a->rep.vs < b->rep.vs;
    });
    for (u32 k = 0; k < sums.size() && k < GlassFindRules::MaxBlendLines; ++k) {
        const FindSum& s = *sums[k];
        const DrawInfo& d = s.rep;
        char idx[48];
        if (s.idx_max == 0) {
            std::snprintf(idx, sizeof(idx), "indirect");
        } else if (s.idx_min == s.idx_max) {
            std::snprintf(idx, sizeof(idx), "%u", s.idx_max);
        } else {
            std::snprintf(idx, sizeof(idx), "%u-%u", s.idx_min, s.idx_max);
        }
        std::snprintf(line, sizeof(line),
                      "Glass find (t86q): blended %u/%zu %08llx:%08llx %s a frame %.1f, in %u/%u frames, idx %s, %s |%s |",
                      k + 1, sums.size(), static_cast<unsigned long long>(d.vs), static_cast<unsigned long long>(d.ps),
                      PhaseText(s.phases).c_str(), double(s.draws) / double(find_frames), s.frames, find_frames, idx,
                      BlendText(d).c_str(), TargetsText(d, nullptr, 1).c_str());
        BbReport::Printf("%s\n", line);
    }
    // Every draw of the last frame in draw order, runs of equal draws merged.
    for (u32 k = 0; k < runs.size(); ++k) {
        if (k >= GlassFindRules::MaxRuns) {
            BbReport::Printf("Glass find (t86q): %zu more runs, not listed (BB_GLASS_FIND_FRAMES does not change this)\n",
                             runs.size() - k);
            break;
        }
        const Run& run = runs[k];
        const DrawInfo& d = list[run.first];
        const auto found = find_sums.find(run.key);
        const u32 seen = found != find_sums.end() ? found->second.frames : 0u;
        std::string text;
        char part[256];
        std::snprintf(part, sizeof(part),
                      "Glass find (t86q): run %u/%zu #%u-%u x%u %08llx:%08llx %s vp %d,%d-%d,%d of %ux%u | ", k + 1,
                      runs.size(), run.first, run.last, run.n, static_cast<unsigned long long>(d.vs),
                      static_cast<unsigned long long>(d.ps), PhaseText(d.phase).c_str(), int(d.vp[0]), int(d.vp[1]),
                      int(d.vp[2]), int(d.vp[3]), u32(d.target_w), u32(d.target_h));
        text += part;
        text += BlendText(d);
        text += " |";
        text += TargetsText(d, nullptr, 1);
        text += " | ";
        text += DrawText(d);
        if (run.n > 1 && run.idx_max != 0) {
            std::snprintf(part, sizeof(part), " (run idx %u-%u)", run.idx_min, run.idx_max);
            text += part;
        }
        std::snprintf(part, sizeof(part), " | in %u/%u frames", seen, find_frames);
        text += part;
        BbReport::Printf("%s\n", text.c_str());
    }
}

namespace {
void LogFoliageTexture(u64 serial, u32 frame, u32 n, const char* role, u32 slot,
                       const BloodPoolProbe::FoliageTexture& t) {
    using Source = BloodPoolProbe::FoliageTexture::Source;
    const char* source = t.source == Source::Registered ? "registered-lookup" :
                         t.source == Source::Null ? "null" :
                         t.source == Source::Unverified ? "unverified" : "no-binding-facts";
    const auto& v = t.view;
    std::printf("Foliage mask probe (t132a): serial=%llu frame=%u rect-draw=#%u %s=%u "
                "source=%s id=%u uid=%llu write_seq=%llu "
                "T#=%08x/%08x/%08x/%08x/%08x/%08x/%08x/%08x "
                "view=%u/%u mip=%u+%u layer=%u+%u swizzle=%u/%u/%u/%u min_lod=%u storage=%d\n",
                Log64(serial), frame, n, role, slot, source, t.id, Log64(t.uid), Log64(t.write_seq),
                t.sharp[0], t.sharp[1], t.sharp[2], t.sharp[3], t.sharp[4], t.sharp[5], t.sharp[6],
                t.sharp[7], v.type, v.format, v.range[0], v.range[1], v.range[2], v.range[3],
                v.swizzle[0], v.swizzle[1], v.swizzle[2], v.swizzle[3], v.min_lod, v.storage);
}
} // namespace

void BloodPoolProbe::LogFoliage(const std::map<u32, std::array<u32, R::OwnerMaps>>& owners,
                               bool gpu_done, u32 wrong_counts, u32 unlisted) {
    const auto& cap = *foliage;
    const auto serial = Log64(foliage_serial);
    const u32 last = R::CaptureFrames - 1;
    const auto& lists = infos[last];
    const auto& frame = cap.frames[last];
    std::printf("Foliage mask probe (t132a): serial=%llu rect=%u,%u-%u,%u native=%ux%u "
                "probe=%ux%u reduced=%d records=%u+%u/%u census=%u/%u host_bytes=%zu "
                "selector_config=%s selectors=%u reserved_records=%u "
                "scope=recorded-direct-and-indirect-graphics-hooks\n",
                serial, box.x0, box.y0, box.x1, box.y1, cap_width, cap_height, pixels_width, pixels_height,
                capture_reduced, cap.general_used, cap.cutout_used, FoliageLimit, cap.states_used,
                FoliageLimit, sizeof(FoliageCapture) + sizeof(foliage) + sizeof(foliage_serial) +
                              sizeof(FoliageDrawSelection),
                cap.selection.invalid ? "invalid" : cap.selection.count ? "valid" : "unset",
                cap.selection.count, cap.selection.count ? FoliageSelectedLimit : 0);

    struct SelectionCount {
        u32 matched = 0, issued = 0, retained = 0;
    };
    std::array<std::array<SelectionCount, FoliageSelectorLimit>, R::CaptureFrames> selected{};
    const auto selection_of = [&](const DrawInfo& draw) {
        return draw.noted && draw.indexed && !draw.indirect
                   ? cap.selection.Find({draw.vs, draw.ps, draw.indices, draw.first_index})
                   : u8(0);
    };
    bool selection_gap = cap.selection.invalid;
    bool census_gap = !gpu_done;
    bool export6 = false, guest_binding6 = false, host_location6 = false, host_target6 = false;
    u32 roi_gap = 0, unnoted = 0;
    for (u32 f = 0; f < R::CaptureFrames; ++f) {
        const auto& row = cap.frames[f];
        export6 |= row.export6 != 0;
        guest_binding6 |= row.bound6 != 0;
        host_location6 |= row.host_location6 != 0;
        host_target6 |= row.host_target6 != 0;
        selection_gap |= row.selection_mismatch != 0;
        census_gap |= !row.gbuffer || row.draws != row.delivered || row.orphan_after ||
                      row.census_overflow || row.target_gap || row.export_disagrees;
        for (u32 n = 0; n < infos[f].size(); ++n) {
            const auto& draw = infos[f][n];
            if (const u8 key = selection_of(draw)) {
                auto& counts = selected[f][key - 1];
                const bool issued = row.issued.test(n);
                ++counts.matched;
                counts.issued += issued;
                counts.retained += issued && row.facts[n] != 0 &&
                                   row.facts[n] <= FoliageSelectedLimit;
            }
            const u8 state_id = row.states[n];
            const bool relevant = draw.phase == R::Gbuffer ||
                                  (state_id && cap.census[state_id - 1].state.same_depth);
            unnoted += relevant && !draw.noted;
            if (f == last && relevant) {
                roi_gap += !draw.probed ||
                           (draw.role[2] == 3 && (draw.read_mask & (1u << 2)) == 0) ||
                           (draw.depth_test && (draw.read_mask & (1u << R::DepthTarget)) == 0);
            }
        }
        std::printf("Foliage mask probe (t132a): serial=%llu frame=%u stats_at_first=%u stats_at_end=%u "
                    "gbuffer=%d draws=%llu issued=%llu indirect_packets=%llu not_issued=%llu orphan_after=%llu "
                    "same_scene_depth=%llu export6=%llu bound6=%llu guest_write6=%llu host_key_write6=%llu "
                    "host_location6=%llu host_prepared_target6=%llu census_overflow=%llu target_gap=%llu "
                    "export_sources_differ=%llu draw_cap=%u fact_overflow=%u selection_mismatch=%u\n",
                    serial, f, row.stats_frame, row.stats_end, row.gbuffer, Log64(row.draws),
                    Log64(row.delivered), Log64(row.indirect), Log64(row.draws - row.delivered),
                    Log64(row.orphan_after), Log64(row.same_depth), Log64(row.export6), Log64(row.bound6),
                    Log64(row.write6), Log64(row.host_write6), Log64(row.host_location6),
                    Log64(row.host_target6), Log64(row.census_overflow), Log64(row.target_gap),
                    Log64(row.export_disagrees), over_cap[f], row.fact_overflow, row.selection_mismatch);
    }
    for (u32 i = 0; i < cap.selection.count; ++i) {
        const auto& key = cap.selection.keys[i];
        const auto& a = selected[0][i];
        const auto& b = selected[1][i];
        const bool missing = !a.issued || !b.issued || a.matched != a.issued || b.matched != b.issued ||
                             a.issued != a.retained || b.issued != b.retained;
        selection_gap |= missing;
        std::printf("Foliage mask probe (t132a): serial=%llu selector=%u draw=%016llx:%016llx:%u:%u "
                    "matched=%u/%u issued=%u/%u retained=%u/%u distinct_records=%u selection=%s\n",
                    serial, i + 1, Log64(key.vs), Log64(key.ps), key.count, key.first,
                    a.matched, b.matched, a.issued, b.issued, a.retained, b.retained,
                    cap.selection_used[i], missing ? "INCONCLUSIVE" : "retained-matches");
    }
    const char* observation = "no-use-in-observed-draws";
    if (host_target6) {
        observation = "host-target-observed";
    } else if (export6 || host_location6) {
        observation = "guest-export-or-host-key-location";
    } else if (guest_binding6) {
        observation = "guest-register-binding-only";
    } else if (census_gap) {
        observation = "no-use-seen-with-gaps";
    }
    std::printf("Foliage mask probe (t132a): serial=%llu MRT6 coverage=%s observation=%s "
                "(pre-bind draw states and prepared targets; issued counts separate; indirect "
                "counts are packets; engine passes outside these hooks are unobserved)\n",
                serial, census_gap ? "INCONCLUSIVE" : "observed-hooks", observation);

    for (u32 i = 0; i < cap.states_used; ++i) {
        const auto& e = cap.census[i];
        const auto& s = e.state;
        std::printf("Foliage mask probe (t132a): serial=%llu state=%u seen=%llu/%llu issued=%llu/%llu "
                    "example=frame:%u,draw:#%u,vs:%016llx,ps:%016llx phase=%u same_scene_depth=%d "
                    "indirect=%d lamps_pending=%d ps_present=%d guest_mrt=%02x host_mrt=%02x "
                    "attachments=%u color_mode=%u depth_samples=%u motion=%08x depth=%d/%d/%u "
                    "viewport_bits=%08x/%08x/%08x/%08x/%08x/%08x\n",
                    serial, i + 1, Log64(e.seen[0]), Log64(e.seen[1]), Log64(e.delivered[0]),
                    Log64(e.delivered[1]), e.frame, e.ordinal, Log64(e.vs), Log64(e.ps), u32(s.phase),
                    s.same_depth, s.indirect, s.lamps_pending, s.ps, s.guest_mrt, s.host_mrt,
                    s.attachments, s.color_mode, s.depth_samples, s.motion, s.depth_test, s.depth_write,
                    s.depth_func, s.viewport[0], s.viewport[1], s.viewport[2], s.viewport[3], s.viewport[4],
                    s.viewport[5]);
        for (u32 j = 0; j < 2; ++j) {
            std::printf("Foliage mask probe (t132a): serial=%llu state=%u loc%u export=%d store=%d "
                        "bound=%d address=%llx target_mask=%x shader_mask=%x host_write=%x color_samples=%u "
                        "host_location=%d prepared_target=%d\n",
                        serial, i + 1, 6 + j, (s.guest_mrt & (1u << (6 + j))) != 0, s.stores[j],
                        s.bound[j], Log64(s.address[j]), s.target_mask[j], s.shader_mask[j],
                        s.host_write[j], s.samples[j], (s.host_mrt & (1u << (6 + j))) != 0,
                        bool(s.targets[6 + j].id));
        }
        for (u32 j = 0; j < s.targets.size(); ++j) {
            const auto& t = s.targets[j];
            const bool color = j < s.blend.size();
            if (!t.id && !(color && ((s.host_mrt >> j) & 1u))) {
                continue; // absent target
            }
            const auto& v = t.view;
            const auto b = color ? s.blend[j] : AmdGpu::BlendControl{};
            std::printf("Foliage mask probe (t132a): serial=%llu state=%u attachment=%u "
                        "(8=depth) id=%u uid=%llu checked=%d extent=%ux%ux%u format=%u "
                        "mip=%u+%u layer=%u+%u blend=%u/%u:%u,%u,%u:%u,%u,%u\n",
                        serial, i + 1, j, t.id.index, Log64(t.uid), t.checked, t.size[0], t.size[1],
                        t.size[2], v.format, v.range[0], v.range[1], v.range[2], v.range[3],
                        u32(b.enable), u32(b.separate_alpha_blend), u32(b.color_src_factor),
                        u32(b.color_dst_factor), u32(b.color_func), u32(b.alpha_src_factor),
                        u32(b.alpha_dst_factor), u32(b.alpha_func));
        }
    }

    if (!gpu_done || wrong_counts) {
        std::printf("Foliage mask probe (t132a): serial=%llu owner-join=INCONCLUSIVE gpu_done=%d "
                    "wrong_counts=%u\n", serial, gpu_done, wrong_counts);
        std::fflush(stdout);
        return;
    }

    // The existing owner map keeps the final value-changing draw. Keep the largest albedo
    // owners first, then depth-only owners, with a stable ordinal tie-break.
    struct Owner {
        u32 n = 0, a = 0, z = 0;
        u64 Rank() const { return (u64(a) << 32) | z; }
    };
    std::array<Owner, FoliageOwners> picked{};
    u32 owner_count = 0;
    for (const auto& [n, px] : owners) {
        Owner candidate{n, px[0], px[2]};
        if (!candidate.Rank()) {
            continue;
        }
        ++owner_count;
        for (auto& best : picked) {
            if (candidate.Rank() > best.Rank()) {
                std::swap(candidate, best);
            }
        }
    }

    const auto joined = [&](u32 n, const char* role, u32 a, u32 z) {
        const auto& d = lists[n];
        const u8 record = frame.facts[n];
        const u8 state_id = frame.states[n];
        std::printf("Foliage mask probe (t132a): serial=%llu frame=%u stats=%u rect-draw=#%u "
                    "%s own_a=%u own_z=%u pair=%016llx:%016llx state=%u record=%u selector=%u\n",
                    serial, last, frame.stats_frame, n, role, a, z, Log64(d.vs), Log64(d.ps),
                    u32(state_id), u32(record), u32(selection_of(d)));
        if (!record || !frame.issued.test(n)) {
            std::printf("Foliage mask probe (t132a): serial=%llu frame=%u rect-draw=#%u "
                        "facts=INCONCLUSIVE missing_record=%d missing_after=%d\n",
                        serial, last, n, !record, !frame.issued.test(n));
            return false;
        }
        const auto& f = cap.facts[record - 1];
        const bool truncated = f.texture_count > f.textures.size();
        bool texture_gap = f.texture_count && (!f.bindings_exact || truncated);
        for (u32 i = 0; i < std::min<u32>(f.texture_count, f.textures.size()); ++i) {
            using Source = FoliageTexture::Source;
            texture_gap |= f.textures[i].source != Source::Registered &&
                           f.textures[i].source != Source::Null;
        }
        const bool mesh_gap = !f.position_valid || !f.offsets_known || (f.indexed && !f.index_base);
        const bool alpha_gap = f.discard && (!f.card_valid || f.alpha_matches != 1 ||
                               f.alpha.source != FoliageTexture::Source::Registered);
        const bool input_gap = f.num_inputs > f.input_offsets.size();
        const bool gap = !state_id || mesh_gap || texture_gap || alpha_gap || input_gap;
        std::printf("Foliage mask probe (t132a): serial=%llu frame=%u rect-draw=#%u facts=%s "
                    "mesh_gap=%d texture_gap=%d alpha_gap=%d input_gap=%d census_state_missing=%d "
                    "position=%llx+%u stride=%u dfmt=%u nfmt=%u primitive=%u restart=%d "
                    "indexed=%d ibase=%llx itype=%u range=%s first=%u count=%u instances=%u "
                    "offsets=%s vertex=%d instance=%u\n",
                    serial, last, n, gap ? "INCONCLUSIVE" : "copied", mesh_gap, texture_gap, alpha_gap,
                    input_gap, !state_id, Log64(f.position_base), f.position_size, f.stride,
                    f.position_data_format, f.position_number_format, f.primitive, f.restart, f.indexed,
                    Log64(f.index_base), f.index_type, f.indirect ? "unknown-indirect" : "direct",
                    f.first_index, f.count, f.instances, f.offsets_known ? "known" : "unknown",
                    std::bit_cast<s32>(f.first_vertex), f.first_instance);
        std::printf("Foliage mask probe (t132a): serial=%llu frame=%u rect-draw=#%u "
                    "camera_gbuffer=%d ps_present=%d discard=%d cutout_verdict=%u "
                    "inputs=%u default=%08x flat=%08x textures=%u binding_lookup_enabled=%d "
                    "one_to_one_stage=%d binding_count=%u texture_truncated=%d resolver=%s miss=%u "
                    "alpha_matches=%u layer=unobserved homogeneity=undetermined\n",
                    serial, last, n, f.camera_gbuffer, f.has_ps, f.discard, f.verdict, f.num_inputs,
                    f.default_inputs, f.flat_inputs, f.texture_count, f.binding_enabled, f.bindings_exact,
                    f.binding_count, truncated, !f.resolved ? "not-applicable" : f.card_valid ? "valid" : "miss",
                    f.miss, f.alpha_matches);
        if (f.has_ps) {
            char input_offsets[3 * 32 + 1] = {};
            for (u32 i = 0; i < std::min<u32>(f.num_inputs, f.input_offsets.size()); ++i) {
                std::snprintf(input_offsets + 3 * i, 4, "%02x/", u32(f.input_offsets[i]));
            }
            std::printf("Foliage mask probe (t132a): serial=%llu frame=%u rect-draw=#%u "
                        "input_offsets=%s\n", serial, last, n, input_offsets);
        }
        if (f.card_valid) {
            const auto& w = f.card_words;
            std::printf("Foliage mask probe (t132a): serial=%llu frame=%u rect-draw=#%u "
                        "selector=%08x channel=%u format=%u op=%u nonzero=%d clamp=%u/%u "
                        "dither=%d fade_left_out=%d affine_bits=%08x/%08x/%08x/%08x "
                        "ref_bits=%08x dither_bits=%08x ref_dwords=%08x/%08x uv_hash=%016llx "
                        "constants_hash=%016llx T#=%08x/%08x/%08x/%08x/%08x/%08x/%08x/%08x\n",
                        serial, last, n, f.selector, f.stored_channel, f.card_format, f.op, f.nonzero,
                        u32(f.clamp_u), u32(f.clamp_v), f.dither, f.fade_left_out, w[0], w[1], w[2], w[3],
                        w[4], w[5], w[6], w[7], Log64(f.uv_hash), Log64(f.constants_hash),
                        f.tsharp[0], f.tsharp[1], f.tsharp[2], f.tsharp[3], f.tsharp[4], f.tsharp[5],
                        f.tsharp[6], f.tsharp[7]);
            if (f.alpha_matches == 1) {
                LogFoliageTexture(foliage_serial, last, n, "alpha_slot", f.alpha_slot, f.alpha);
            }
        }
        for (u32 i = 0; i < std::min<u32>(f.texture_count, f.textures.size()); ++i) {
            LogFoliageTexture(foliage_serial, last, n, "ps_texture", i, f.textures[i]);
        }
        return !gap;
    };

    u32 owner_gaps = 0, controls = 0, available_controls = 0, missing_controls = 0;
    u32 control_gaps = 0, repeated_controls = 0;
    std::bitset<FoliageLimit> used_records;
    for (const auto& p : picked) {
        if (!p.Rank()) {
            break;
        }
        owner_gaps += !joined(p.n, "owner", p.a, p.z);
        if (const u8 slot = frame.facts[p.n]) {
            used_records.set(slot - 1);
        }
    }
    for (u32 n = 0; n < lists.size(); ++n) {
        const auto owned = owners.find(n);
        if (!frame.issued.test(n) || (owned != owners.end() && (owned->second[0] || owned->second[2]))) {
            continue;
        }
        const auto& d = lists[n];
        const bool same_pair = std::any_of(picked.begin(), picked.end(), [&](const Owner& p) {
            return p.Rank() && d.vs == lists[p.n].vs && d.ps == lists[p.n].ps;
        });
        if (!same_pair) {
            continue;
        }
        const u8 slot = frame.facts[n];
        if (!slot) {
            ++missing_controls;
        } else if (!used_records.test(slot - 1)) {
            used_records.set(slot - 1);
            ++available_controls;
            if (controls < FoliageControls) {
                ++controls;
                control_gaps += !joined(n, "same-pair-control", 0, 0);
            }
        } else {
            ++repeated_controls;
        }
    }
    const bool incomplete = census_gap || selection_gap || roi_gap || unnoted || unlisted ||
                            !owner_count || box.cut ||
                            owner_gaps || owner_count > FoliageOwners || missing_controls || control_gaps ||
                            available_controls > FoliageControls ||
                            frame.fact_overflow || cap.frames[0].fact_overflow ||
                            over_cap[0] || over_cap[last];
    std::printf("Foliage mask probe (t132a): serial=%llu owner-join=%s owners=%u omitted=%u "
                "owner_fact_gaps=%u relevant_probe_gaps=%u relevant_no_note=%u t86q_unlisted=%u "
                "rectangle_clipped=%d same_pair_controls=%u/%u same_pair_no_record=%u "
                "control_fact_gaps=%u same_pair_repeated_records=%u selection_gap=%d "
                "(changed-values only; owner map is last capture frame)\n",
                serial, incomplete ? "INCONCLUSIVE" : "observed-owners", owner_count,
                owner_count - std::min(owner_count, FoliageOwners), owner_gaps, roi_gap,
                unnoted, unlisted, box.cut, controls, available_controls, missing_controls, control_gaps,
                repeated_controls, selection_gap);
    std::fflush(stdout);
}

/// Rectangle find: the draws of the last probed frame that changed a pixel of the rectangle, in draw order.
void BloodPoolProbe::GlassRectLog() {
    const bool gpu_done = scheduler.IsFree(done_tick);
    const auto* c = static_cast<const u32*>(counts.mapped);
    const auto* o = static_cast<const u32*>(owners.mapped);
    const u32 frames = R::CaptureFrames;
    const u32 f = frames - 1u;
    const auto& list = infos[f];
    const u32 box_px = box.Width() * box.Height();
    // The last writer of each rectangle pixel (map 0 G-buffer albedo, 1 scene colour, 2 depth), this frame's.
    std::map<u32, std::array<u32, R::OwnerMaps>> own;
    std::array<u32, R::OwnerMaps> owned{};
    for (u32 m = 0; m < R::OwnerMaps; ++m) {
        for (u32 i = 0; i < box_px; ++i) {
            const u32 v = o[std::size_t(m) * box_px + i];
            const u32 vf = (v >> R::OwnerFrameShift) - 1u, n = v & ((1u << R::OwnerFrameShift) - 1u);
            if (v == 0 || vf != f || n >= list.size()) {
                continue;
            }
            ++own[n][m];
            ++owned[m];
        }
    }
    u32 probed = 0, changed = 0, wrong = 0;
    std::array<u32, 7> skipped{};
    for (u32 i = 0; i < list.size(); ++i) {
        const DrawInfo& d = list[i];
        if (!d.probed) {
            if (d.skipped < skipped.size()) {
                ++skipped[d.skipped];
            }
            continue;
        }
        ++probed;
        const u32* r = c + (std::size_t(f) * R::MaxDraws + i) * R::RecordWords;
        changed += r[R::WordBox] != 0 ? 1u : 0u;
        wrong += (r[R::WordSeenBox] != box_px || r[R::WordBox] > box_px) ? 1u : 0u;
    }
    char line[1024];
    std::snprintf(line, sizeof(line),
                  "Glass find (t86q): rect %s -> box x %u-%u y %u-%u (%u px)%s of the %ux%u scene%s, %u frames, "
                  "logged %s; last frame: %u draws (%u over the cap of %u), %u probed, %u changed the rectangle; "
                  "not probed: %u lamps apart, %u not scene-sized, %u unreadable, %u left out, %u menu preview, "
                  "%u no view; self-check %s (%u compared draws saw other than the box or counted more than its "
                  "pixels); last writers: albedo %u px, scene colour %u px, depth %u px of %u",
                  glass_text, box.x0, box.x1, box.y0, box.y1, box_px, box.cut ? " (a side cut to 256)" : "",
                  pixels_width, pixels_height, capture_reduced ? " (reduced)" : "", frames,
                  gpu_done ? "after the GPU" : "BEFORE the GPU was done (counts may be short)", u32(list.size()) + over_cap[f],
                  over_cap[f], R::MaxDraws, probed, changed, skipped[LampsApart], skipped[NotScene], skipped[Unreadable],
                  skipped[LeftOut], skipped[Preview], skipped[NoView], wrong != 0 ? "COUNTS WRONG" : "counts sound",
                  wrong, owned[0], owned[1], owned[2], box_px);
    BbReport::Printf("%s\n", line);
    BbReport::Printf("Glass find (t86q): rect-draw lines in DRAW ORDER of the last frame, only draws that changed a "
                     "rectangle pixel: #n draw number, phase P/G/B/L/A, box = rectangle px changed / its px, own a/s/z = "
                     "rectangle px it was the LAST writer of (G-buffer albedo / scene colour by draws over 6 indices / "
                     "depth), frame~ = px it changed in the whole frame (a full-screen pass changes about all of "
                     "them); targets cb:format/role+b blending =px changed in the rectangle, d: depth\n");
    u32 listed = 0, more = 0;
    for (u32 i = 0; i < list.size(); ++i) {
        const DrawInfo& d = list[i];
        if (!d.probed) {
            continue;
        }
        const u32* r = c + (std::size_t(f) * R::MaxDraws + i) * R::RecordWords;
        if (r[R::WordBox] == 0) {
            continue;
        }
        if (listed >= GlassFindRules::MaxRectLines) {
            ++more;
            continue;
        }
        ++listed;
        const auto found = own.find(i);
        const std::array<u32, R::OwnerMaps> w = found != own.end() ? found->second : std::array<u32, R::OwnerMaps>{};
        std::string text;
        char part[256];
        std::snprintf(part, sizeof(part),
                      "Glass find (t86q): rect-draw #%u %08llx:%08llx %s box %u/%u own a%u s%u z%u frame~%llu | ", i,
                      static_cast<unsigned long long>(d.vs), static_cast<unsigned long long>(d.ps),
                      PhaseText(d.phase).c_str(), r[R::WordBox], box_px, w[0], w[1], w[2],
                      static_cast<unsigned long long>(u64(r[R::WordFrame]) * R::Stride * R::Stride));
        text += part;
        text += BlendText(d);
        text += " |";
        text += TargetsText(d, r, 1);
        std::snprintf(part, sizeof(part), " | vp %d,%d-%d,%d of %ux%u | ", int(d.vp[0]), int(d.vp[1]), int(d.vp[2]),
                      int(d.vp[3]), u32(d.target_w), u32(d.target_h));
        text += part;
        text += DrawText(d);
        BbReport::Printf("%s\n", text.c_str());
    }
    if (more != 0) {
        BbReport::Printf("Glass find (t86q): %u more draws changed the rectangle, not listed\n", more);
    }
    // The scene colour's last writers by count: who has the final say in the rectangle.
    std::vector<std::pair<u32, u32>> by_scene; // px, draw number
    for (const auto& [n, w] : own) {
        if (w[1] != 0) {
            by_scene.emplace_back(w[1], n);
        }
    }
    std::sort(by_scene.begin(), by_scene.end(), [](const auto& a, const auto& b) {
        return a.first != b.first ? a.first > b.first : a.second < b.second;
    });
    for (u32 k = 0; k < by_scene.size() && k < GlassFindRules::MaxOwnerLines; ++k) {
        const DrawInfo& d = list[by_scene[k].second];
        BbReport::Printf("Glass find (t86q): rect-owner %u/%zu scene colour last written by #%u %08llx:%08llx for %u of %u "
                         "rectangle px (%s, %s)\n",
                         k + 1, by_scene.size(), by_scene[k].second, static_cast<unsigned long long>(d.vs),
                         static_cast<unsigned long long>(d.ps), by_scene[k].first, box_px, PhaseText(d.phase).c_str(),
                         BlendText(d).c_str());
    }
    if (by_scene.empty()) {
        BbReport::Printf("Glass find (t86q): rect-owner none: no draw over 6 indices into the scene colour (RGBA16F with the "
                         "scene depth) was the last writer of a rectangle pixel\n");
    }
    if (foliage) {
        LogFoliage(own, gpu_done, wrong, more);
        if (IvyOwnerWanted()) {
            LogIvyOwner(gpu_done, wrong, skipped);
        }
    }
}

void BloodPoolProbe::LogIvyOwner(bool gpu_done, u32 wrong, const std::array<u32, 7>& skipped) {
    constexpr u32 frame = R::CaptureFrames - 1;
    const auto& list = infos[frame];
    const auto& track = foliage->frames[frame];
    const auto serial = Log64(foliage_serial);
    std::printf("Ivy owner (t154): serial=%llu frame=%u fence=%u bad_counts=%u cap=%u "
                "skipped_none=%u lamps=%u not_scene=%u unreadable=%u left_out=%u preview=%u no_view=%u "
                "scope=observed-value-changes-only unhooked=unobserved\n",
                serial, frame, u32(gpu_done), wrong, over_cap[frame], skipped[NotSkipped],
                skipped[LampsApart], skipped[NotScene], skipped[Unreadable], skipped[LeftOut],
                skipped[Preview], skipped[NoView]);
    if (!foliage->ivy) {
        std::printf("Ivy owner (t154): serial=%llu frame=%u status=unavailable reason=no-sample-draw\n",
                    serial, frame);
        return;
    }

    const auto& ivy = *foliage->ivy;
    char identity[160];
    std::snprintf(identity, sizeof(identity),
                  "serial=%llu frame=%u draw=%u tick=%llu stats=%u jitter_bits=%08x,%08x",
                  serial, frame, ivy.ordinal, Log64(ivy.tick), ivy.stats,
                  std::bit_cast<u32>(ivy.jitter[0]), std::bit_cast<u32>(ivy.jitter[1]));
    const auto unavailable = [&](const char* reason) {
        std::printf("Ivy owner (t154): %s status=unavailable reason=%s\n", identity, reason);
    };
    if (!gpu_done || wrong || !owners.mapped || !counts.mapped) {
        unavailable("rectangle-readback");
        return;
    }
    // The display counter can advance during a single probe frame. Unsigned differences
    // keep the capture interval inclusive even when the counter wraps.
    const bool stats_in_frame = u32(ivy.stats - track.stats_frame) <=
                                u32(track.stats_end - track.stats_frame);
    std::printf("Ivy owner (t154): %s native_guard=checked capture_reduced=%u box_cut=%u "
                "extent=%ux%u expected=%ux%u stats_first=%u stats_end=%u stats_in_frame=%u\n",
                identity, u32(capture_reduced), u32(box.cut), pixels_width, pixels_height,
                IvySampleWitness::Width, IvySampleWitness::Height,
                track.stats_frame, track.stats_end, u32(stats_in_frame));
    if (capture_reduced || box.cut || pixels_width != IvySampleWitness::Width ||
        pixels_height != IvySampleWitness::Height || !stats_in_frame) {
        unavailable("native-frame-or-box");
        return;
    }
    if (ivy.ordinal >= list.size() || !track.issued.test(ivy.ordinal)) {
        unavailable("draw-not-issued");
        return;
    }
    const auto& draw = list[ivy.ordinal];
    const u8 slot = track.states[ivy.ordinal];
    constexpr u32 required_reads = 1u | (1u << R::DepthTarget);
    if (!draw.noted || !draw.probed || !slot || draw.role[0] != RoleScene ||
        (draw.read_mask & required_reads) != required_reads ||
        !IvyMaterialProbe::Matches(draw.vs, draw.ps, draw.first_index, draw.indices, draw.indexed)) {
        unavailable("exact-draw-compare");
        return;
    }
    const auto& targets = foliage->census[slot - 1].state.targets;
    const auto& colour = targets[0];
    const auto& depth = targets[R::DepthTarget];
    const auto native_view = [](const FoliageTarget& target, u32 format) {
        return target.checked && target.size[0] == IvySampleWitness::Width &&
               target.size[1] == IvySampleWitness::Height && target.size[2] == 1 &&
               target.view.range == std::array<u32, 4>{0, 1, 0, 1} &&
               target.view.format == format;
    };
    if (!native_view(colour, draw.format[0]) || !native_view(depth, draw.depth_format)) {
        unavailable("native-target-view");
        return;
    }

    const auto* counts_words = static_cast<const u32*>(counts.mapped);
    const auto* record = counts_words + (std::size_t(frame) * R::MaxDraws + ivy.ordinal) * R::RecordWords;
    std::printf("Ivy owner (t154): %s status=observed scene_uid=%llu depth_uid=%llu "
                "rect_scene_changes=%u rect_depth_changes=%u\n",
                identity, Log64(colour.uid), Log64(depth.uid), record[R::WordTarget0],
                record[R::WordTarget0 + R::DepthTarget]);

    const auto* owner_words = static_cast<const u32*>(owners.mapped);
    const u32 box_px = box.Width() * box.Height();
    for (const auto coordinate : IvySampleWitness::Coordinates) {
        const u32 x = u32(coordinate.x), y = u32(coordinate.y);
        if (x < box.x0 || x > box.x1 || y < box.y0 || y > box.y1) {
            std::printf("Ivy owner (t154): %s x=%u y=%u status=outside-box\n", identity, x, y);
            continue;
        }
        const u32 pixel = (y - box.y0) * box.Width() + x - box.x0;
        std::array<u32, R::OwnerMaps> writer{};
        std::array<const char*, R::OwnerMaps> status{};
        for (u32 map = 0; map < R::OwnerMaps; ++map) {
            const u32 value = owner_words[std::size_t(map) * box_px + pixel];
            const u32 ordinal = value & ((1u << R::OwnerFrameShift) - 1u);
            const u32 packed_frame = value >> R::OwnerFrameShift;
            writer[map] = ordinal;
            if (!value) {
                status[map] = "uncovered";
            } else if (packed_frame < frame + 1) {
                status[map] = "prior-frame";
            } else if (packed_frame != frame + 1 || ordinal >= list.size() || !list[ordinal].probed) {
                status[map] = "invalid";
            } else if (ordinal == ivy.ordinal) {
                status[map] = "ivy-change";
            } else if (map == 0) {
                status[map] = "observed";
            } else {
                const u32 attachment = map == 1 ? 0 : R::DepthTarget;
                const u8 owner_slot = track.states[ordinal];
                const auto uid = targets[attachment].uid;
                const bool same_image = owner_slot &&
                    foliage->census[owner_slot - 1].state.targets[attachment].uid == uid;
                status[map] = !same_image ? "other-or-unknown-image"
                                          : ordinal > ivy.ordinal ? "later-change" : "earlier-change";
            }
        }
        std::printf("Ivy owner (t154): %s x=%u y=%u albedo=%s:%u scene=%s:%u depth=%s:%u\n",
                    identity, x, y, status[0], writer[0], status[1], writer[1], status[2], writer[2]);
    }
    std::fflush(stdout);
}

void BloodPoolProbe::BeforeDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                                const std::array<VideoCore::ImageId, 8>& targets, VideoCore::ImageId depth,
                                bool light, bool lamps_pending, bool indirect,
                                const FoliageTargetViews* foliage_views) {
    if (pending.on) {
        // The draw SNAPSHOT was recorded for was left out (a pipeline still compiling, a cascade
        // nothing samples): no COMPARE for it.
        if (state == State::Capturing && pending.ordinal < infos[capture].size()) {
            infos[capture][pending.ordinal].skipped = LeftOut;
        }
        pending = {};
    }
    note_due = false;
    if (state == State::Idle || state == State::Waiting) {
        return;
    }
    const u32 mrt = u32(pipeline.GetGraphicsKey().mrt_mask);
    const bool gbuffer = std::popcount(mrt) >= 5 && bool(depth);
    const u8 phase = gbuffer                ? R::Gbuffer
                     : light                ? R::Light
                     : !frame_gbuffer       ? R::BeforeGbuffer
                     : frame_lit            ? R::AfterLight
                                            : R::BeforeLight;
    if (gbuffer) {
        frame_gbuffer = true;
        frame_lit = false;
        scene_depth = depth;
        const auto& image = texture_cache.GetImage(depth);
        scene_width = image.info.size.width;
        scene_height = image.info.size.height;
    } else if (light) {
        frame_lit = true;
    }
    if (state != State::Capturing && state != State::Finding) { // bbport (t86q): Finding lists draws too
        return;
    }
    const u32 n = ordinal++;
    if (foliage_views) {
        CensusFoliage(regs, pipeline, targets, depth, *foliage_views, n, phase, indirect, lamps_pending);
    }
    auto& list = infos[capture];
    if (n >= R::MaxDraws || n != list.size()) {
        ++over_cap[capture];
        return;
    }
    DrawInfo& info = list.emplace_back();
    note_due = true;
    note_ordinal = n;
    info.vs = pipeline.GetStage(Shader::SwStage::Vertex).pgm_hash;
    const auto* ps = pipeline.GetStages()[u32(Shader::SwStage::Fragment)];
    info.ps = ps ? ps->pgm_hash : 0;
    info.indices = indirect ? 0u : u32(regs.num_indices);
    info.instances = indirect ? 0u : regs.num_instances.NumInstances();
    info.mrt = mrt;
    info.phase = phase;
    info.indirect = indirect;
    info.light = light;
    info.depth_test = regs.depth_control.depth_enable != 0 && bool(depth);
    info.depth_write = info.depth_test && regs.depth_control.depth_write_enable != 0;
    info.depth_func = u8(u32(regs.depth_control.depth_func) & 7u);
    std::array<VideoCore::ImageId, R::Targets> ids{};
    for (u32 cb = 0; cb < 8; ++cb) {
        if (((mrt >> cb) & 1u) == 0 || !targets[cb]) {
            continue;
        }
        ids[cb] = targets[cb];
        const auto& image = texture_cache.GetImage(targets[cb]);
        info.format[cb] = u32(image.info.pixel_format);
        info.write_masks |= (regs.color_target_mask.GetMask(cb) & 15u) << (4 * cb);
        if (regs.blend_control[cb].enable && !regs.color_buffers[cb].info.blend_bypass) {
            info.blend |= u8(1u << cb);
        }
        info.role[cb] = gbuffer ? u8(1 + cb)
                        : light ? RoleLight
                        : (cb == 0 && image.info.pixel_format == vk::Format::eR16G16B16A16Sfloat &&
                           depth && depth == scene_depth)
                            ? RoleScene
                            : u8(0);
    }
    if (depth) {
        ids[R::DepthTarget] = depth;
        info.depth_format = u32(texture_cache.GetImage(depth).info.pixel_format);
    }
    {   // bbport (t86q_glass-finder, TOOL): the blend state and screen box of the draw (host reads only)
        for (u32 cb = 0; cb < 8; ++cb) {
            if (((info.blend >> cb) & 1u) != 0) {
                const auto& blend_control = regs.blend_control[cb];
                info.blend_cb = u8(cb);
                info.blend_f[0] = u8(u32(blend_control.color_src_factor));
                info.blend_f[1] = u8(u32(blend_control.color_dst_factor));
                info.blend_f[2] = u8(u32(blend_control.color_func));
                info.blend_separate = blend_control.separate_alpha_blend != 0;
                info.blend_f[3] = info.blend_separate ? u8(u32(blend_control.alpha_src_factor)) : info.blend_f[0];
                info.blend_f[4] = info.blend_separate ? u8(u32(blend_control.alpha_dst_factor)) : info.blend_f[1];
                info.blend_f[5] = info.blend_separate ? u8(u32(blend_control.alpha_func)) : info.blend_f[2];
                break;
            }
        }
        const auto& viewport = regs.viewports[0];
        const auto to_s16 = [](float v) { return s16(std::clamp(v, -32000.0f, 32000.0f)); };
        info.vp[0] = to_s16(viewport.xoffset - std::abs(viewport.xscale));
        info.vp[1] = to_s16(viewport.yoffset - std::abs(viewport.yscale));
        info.vp[2] = to_s16(viewport.xoffset + std::abs(viewport.xscale));
        info.vp[3] = to_s16(viewport.yoffset + std::abs(viewport.yscale));
        for (u32 t = 0; t < R::Targets; ++t) {
            if (ids[t]) {
                const auto& first = texture_cache.GetImage(ids[t]);
                info.target_w = u16(std::min<u32>(first.info.size.width, 65535u));
                info.target_h = u16(std::min<u32>(first.info.size.height, 65535u));
                break;
            }
        }
    }
    if (state == State::Finding) {
        return; // the wide find reads the draw's state only: no pass, no snapshot
    }
    if (camera_motion.PreviewFrame()) {
        info.skipped = Preview;
        return;
    }
    // Lamps apart (vk_point_shadow.h): an open batch's lamps go into images of their own, so the
    // light targets do not hold them yet; those draws are left alone (no read while it is open).
    if (lamps_pending) {
        info.skipped = LampsApart;
        return;
    }
    // The targets of the scene's size (the G-buffer pass's depth, or its reduced proxy) that the
    // passes can sample.
    u32 mask = 0;
    bool other_size = false;
    for (u32 t = 0; t < R::Targets; ++t) {
        if (!ids[t]) {
            continue;
        }
        const auto& image = texture_cache.GetImage(ids[t]);
        const bool proxy = scene_targets.Reduced() && scene_targets.EligibleScene(image);
        const bool scene_sized = proxy == capture_reduced &&
                                 (proxy || (image.info.size.width == cap_width &&
                                            image.info.size.height == cap_height));
        if (!scene_sized) {
            other_size = true;
            continue;
        }
        if ((t != R::DepthTarget && !ColourName(image.info.pixel_format)) || image.info.num_samples != 1) {
            continue; // (the passes read single-sample float textures)
        }
        mask |= 1u << t;
    }
    if (!mask) {
        info.skipped = other_size ? NotScene : Unreadable;
        return;
    }
    const SceneUseScope scene_use{"blood pool probe"};
    scheduler.EndRendering();
    std::array<vk::ImageView, R::Targets> views{};
    for (u32 t = 0; t < R::Targets; ++t) {
        if ((mask >> t) & 1u) {
            views[t] = ViewOf(ids[t], t == R::DepthTarget ? vk::ImageAspectFlagBits::eDepth
                                                          : vk::ImageAspectFlagBits::eColor);
            if (!views[t]) {
                mask &= ~(1u << t);
            }
        }
    }
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!mask) {
        info.skipped = NoView;
        return;
    }
    const vk::ImageView any = views[std::countr_zero(mask)];
    for (auto& view : views) {
        view = view ? view : any;
    }
    // Owners: the G-buffer's albedo (target 2), the scene colour by a draw of more than six indices
    // (full-screen passes left out; an indirect draw's count is unknown: taken), the depth.
    u32 albedo = R::NoTarget, scene = R::NoTarget;
    if (gbuffer && ((mask >> 2) & 1u)) {
        albedo = 2;
    }
    if (info.role[0] == RoleScene && (mask & 1u) && (indirect || info.indices > 6 || info.instances > 1)) {
        scene = 0;
    }
    R::Push push{};
    push.box[0] = s32(box.x0);
    push.box[1] = s32(box.y0);
    push.box[2] = s32(box.Width());
    push.box[3] = s32(box.Height());
    push.grid[0] = s32(grid_cols);
    push.grid[1] = s32(grid_rows);
    push.grid[2] = s32(R::Stride);
    push.mask = mask;
    const u32 gx = (std::max(box.Width(), grid_cols) + R::Group - 1) / R::Group;
    const u32 gy = (std::max(box.Height(), grid_rows) + R::Group - 1) / R::Group;
    info.read_mask = mask;
    scheduler.RecordCrumb({.name = "blood pool probe snapshot"},
                          [views, push, gx, gy, prints_buffer = prints.buffer,
                           pipeline_handle = *snapshot_pass.pipeline,
                           layout = *snapshot_pass.layout](vk::CommandBuffer cmd) {
                              RecordPass(cmd, pipeline_handle, layout, views, prints_buffer, {}, {}, push,
                                         gx, gy);
                          });
    pending = {.on = true,
               .ordinal = n,
               .mask = mask,
               .ids = ids,
               .owner_targets = albedo | (scene << 8) | ((mask >> R::DepthTarget) & 1u ? R::OwnDepth : 0u)};
    if (foliage_views && (albedo != R::NoTarget || (pending.owner_targets & R::OwnDepth))) {
        foliage->note_wanted = true;
    }
}

void BloodPoolProbe::Note(bool indexed, u64 index_address, u32 first_index,
                          const std::array<Texture, R::DrawTextures>& textures, u32 count, u32 all, u32 hash) {
    if (!std::exchange(note_due, false) || (state != State::Capturing && state != State::Finding) ||
        note_ordinal >= infos[capture].size()) {
        return;
    }
    DrawInfo& info = infos[capture][note_ordinal];
    info.noted = true;
    info.indexed = indexed;
    info.index_address = index_address;
    info.first_index = first_index;
    info.textures = textures;
    info.texture_count = std::min<u32>(count, R::DrawTextures);
    info.textures_all = all;
    info.texture_hash = hash;
}

bool BloodPoolProbe::WantsBoundIndex(u32 count, u32 first) const {
    if (!bound_index_target || state != State::Capturing || capture != R::CaptureFrames - 1 ||
        !pending.on || pending.ordinal != note_ordinal || pending.ordinal >= infos[capture].size()) {
        return false;
    }
    const auto& fixture = IndexFixtures[bound_index_target - 1];
    const auto& draw = infos[capture][pending.ordinal];
    return count == fixture.count && first == fixture.first &&
        draw.vs == IndexVs && draw.ps == IndexPs && draw.indices == count &&
        draw.phase == R::Gbuffer && !draw.light && !draw.indirect && draw.depth_test &&
        draw.depth_write && draw.role[2] == 3 && !(draw.blend & (1u << 2)) &&
        (pending.owner_targets & 0xffu) == 2 && (pending.owner_targets & R::OwnDepth);
}

void BloodPoolProbe::NoteBoundLayers(const RenderState& render, const IndexCommand& command,
                                  BoundLayerInput input) {
    auto& result = bound_layer_evidence;
    if (++result.issued != 1) {
        result.refusal = "duplicate_issued_draw";
        return;
    }
    result.refusal = "binding_command_or_extent_unconfirmed";
    const auto& draw = infos[capture][pending.ordinal];
    if (!command.confirmed || !command.instances || command.instances != draw.instances ||
        command.vk_first != 0 || command.vertex_offset != 0 ||
        command.topology != vk::PrimitiveTopology::eTriangleList || command.restart ||
        render.width != IndexSceneWidth || render.height != IndexSceneHeight || render.num_layers != 1 ||
        !render.color_attachments[2].image_view || render.color_attachments[2].is_clear ||
        !render.depth_stencil_attachment.has_depth || render.depth_stencil_attachment.depth_clear ||
        !render.depth_stencil_attachment.image_view || !input.writes || !input.pipeline ||
        input.frame != capture || input.ordinal != pending.ordinal) {
        return;
    }

    const auto& key = input.pipeline->GetGraphicsKey();
    constexpr u32 ps = u32(Shader::SwStage::Fragment), vs = u32(Shader::SwStage::Vertex);
    if (key.foliage_mask || !key.stage_hashes[ps]) {
        result.refusal = "native_fragment_permutation_unconfirmed";
        return;
    }
    result.serial = bound_index_serial;
    result.frame = capture;
    result.ordinal = pending.ordinal;
    result.tick = scheduler.CurrentTick();
    result.fragment_key = key.stage_hashes[ps];
    result.vertex_key = key.stage_hashes[vs];
    result.pipeline_key = std::hash<GraphicsPipelineKey>{}(key);
    // GetProgram keys a native fragment with HashCombine(guest_hash, permutation).
    // Inverting that combination recovers the index used in the ShaderBinary filename.
    const u64 program = IndexPs;
    result.permutation = (result.fragment_key ^ program) - (HashCombine(program, u64{0}) ^ program);

    for (size_t i = 0; i < LayerBindings.size(); ++i) {
        const u32 binding = LayerBindings[i];
        auto& row = result.rows[i];
        const vk::WriteDescriptorSet* write = nullptr;
        for (const auto& candidate : *input.writes) {
            if (candidate.dstBinding != binding) continue;
            if (write) {
                row.result = "duplicate_write";
                break;
            }
            write = &candidate;
        }
        if (!write || row.result == std::string_view("duplicate_write")) continue;
        const bool sampler = binding == LayerBindings.back();
        row.result = "descriptor_shape_differs";
        if (write->dstArrayElement || write->descriptorCount != 1 || !write->pImageInfo ||
            write->descriptorType != (sampler ? vk::DescriptorType::eSampler :
                                               vk::DescriptorType::eSampledImage)) {
            continue;
        }
        const auto& descriptor = *write->pImageInfo;
        if (sampler) {
            row.sampler = std::bit_cast<u64>(descriptor.sampler);
            row.result = descriptor.sampler ? "sampler" : "null_sampler";
            continue;
        }

        row.view = std::bit_cast<u64>(descriptor.imageView);
        row.result = descriptor.imageView ? "view_unresolved" : "null_view";
        if (!descriptor.imageView) continue;
        const VideoCore::Image* image = nullptr;
        const VideoCore::ImageView* view = nullptr;
        VideoCore::ImageId image_id{};
        for (const auto id : input.images) {
            if (!id || id == image_id) continue;
            const auto* candidate = texture_cache.TryGetImage(id, 0);
            if (!candidate || !candidate->backing || candidate->binding.needs_rebind ||
                !texture_cache.IsRegisteredImage(id, candidate->image_uid)) {
                continue;
            }
            for (const auto view_id : candidate->backing->image_view_ids) {
                const auto& entry = texture_cache.GetImageView(view_id);
                if (entry.image_view.get() != descriptor.imageView) continue;
                if (image) {
                    row.result = "registered_view_ambiguous";
                    break;
                }
                image = candidate;
                image_id = id;
                view = &entry;
                break;
            }
            if (row.result == std::string_view("registered_view_ambiguous")) break;
        }
        if (!image || row.result == std::string_view("registered_view_ambiguous")) continue;
        const auto& info = image->info;
        row.result = "registered_view";
        row.view_info = FoliageView::From(view->info);
        row.id = image_id.index;
        row.uid = image->image_uid;
        row.write_seq = image->write_seq;
        row.address = info.guest_address;
        row.width = info.size.width;
        row.height = info.size.height;
        row.levels = info.resources.levels;
        row.layers = info.resources.layers;
        row.format = u32(info.pixel_format);
        row.pitch = info.pitch;
        row.bits = info.num_bits;
        row.tile_mode = u32(info.tile_mode);
        row.array_mode = u32(info.array_mode);
        row.bank_swizzle = info.bank_swizzle;
        row.alt_tile = info.alt_tile;
        row.flags = u32(image->flags);
        // Cache history records the guest upload inputs, not a readback. A GPU write,
        // invalidation or untracked address invalidates this content identity.
        if (image->mip_hashes_current &&
            !(row.flags & u32(VideoCore::ImageFlagBits::Dirty | VideoCore::ImageFlagBits::GpuModified)) &&
            row.levels <= row.guest_mip_hash.size() && image->mip_hashes.size() == row.levels) {
            for (u32 level = 0; level < row.levels; ++level) {
                row.guest_mip_hash[level] = image->mip_hashes[level];
                row.guest_mip_size[level] = info.mips_layout[level].size;
            }
        }
    }
    result.refusal = nullptr;
}

bool BloodPoolProbe::ExactBoundOwner(bool gpu_done, u64 serial, u32 frame, u32 draw_ordinal) const {
    if (!gpu_done || serial != bound_index_serial || frame != R::CaptureFrames - 1 ||
        draw_ordinal >= infos[frame].size() || !infos[frame][draw_ordinal].probed ||
        over_cap[0] || over_cap[1]) {
        return false;
    }
    const u32 box_px = box.Width() * box.Height();
    const auto* map = static_cast<const u32*>(owners.mapped);
    const u32 token = R::OwnerValue(frame, draw_ordinal);
    const auto matches = [token, box_px](const u32* start) {
        return std::all_of(start, start + box_px, [token](u32 value) { return value == token; });
    };
    return map && matches(map) && matches(map + 2 * box_px);
}

void BloodPoolProbe::LogBoundLayers(bool gpu_done, const char* role) {
    bound_layer_input = {};
    const auto result = std::exchange(bound_layer_evidence, BoundLayerEvidence{});
    const char* refusal = result.refusal;
    if (!refusal && (!scheduler.IsFree(result.tick) ||
                     !ExactBoundOwner(gpu_done, result.serial, result.frame, result.ordinal))) {
        refusal = "exact_albedo_or_depth_owner_unconfirmed";
    }
    if (refusal) {
        BbReport::Printf("Blood bound layers (t189): refuse role=%s serial=%llu reason=%s\n",
                         role, Log64(bound_index_serial), refusal);
        return;
    }

    const u32 box_px = box.Width() * box.Height();
    BbReport::Printf("Blood bound layers (t189): owner role=%s serial=%llu frame=%u ordinal=%u "
                     "scene=1920x1080 box=%u:%u:%u:%u a=%u z=%u vs=%08x ps=%08x "
                     "count=%u guest_first=%u vk_first=0 vertex_offset=0 "
                     "vertex_key=%llx fragment_key=%llx pipeline_key=%llx cache_perm=%llu tick=%llu\n",
                     role, Log64(result.serial), result.frame, result.ordinal,
                     box.x0, box.y0, box.x1, box.y1, box_px, box_px, IndexVs, IndexPs,
                     IndexFixtures[bound_index_target - 1].count,
                     IndexFixtures[bound_index_target - 1].first, Log64(result.vertex_key),
                     Log64(result.fragment_key), Log64(result.pipeline_key), Log64(result.permutation),
                     Log64(result.tick));
    for (size_t i = 0; i < LayerBindings.size(); ++i) {
        const auto& row = result.rows[i];
        const auto& view = row.view_info;
        std::string mips;
        for (u32 level = 0; level < row.guest_mip_size.size() && row.guest_mip_size[level]; ++level) {
            char value[40];
            std::snprintf(value, sizeof(value), "%s%u:%016llx", level ? "," : "",
                          row.guest_mip_size[level], Log64(row.guest_mip_hash[level]));
            mips += value;
        }
        BbReport::Printf("Blood bound layers (t189): descriptor serial=%llu set=0 binding=%u result=%s "
                         "view=%llx sampler=%llx id=%u uid=%llu seq=%llu guest=%llx "
                         "size=%ux%u image_format=%u view_format=%u view_type=%u "
                         "mip=%u+%u layer=%u+%u swizzle=%u:%u:%u:%u min_lod=%u "
                         "storage=%u levels=%u layers=%u pitch=%u bits=%u tile=%u array=%u bank=%u "
                         "alt=%u flags=%x guest_mips=%s\n",
                         Log64(result.serial), LayerBindings[i], row.result, Log64(row.view),
                         Log64(row.sampler), row.id, Log64(row.uid), Log64(row.write_seq),
                         Log64(row.address), row.width, row.height, row.format, view.format, view.type,
                         view.range[0], view.range[1], view.range[2], view.range[3],
                         view.swizzle[0], view.swizzle[1], view.swizzle[2], view.swizzle[3],
                         view.min_lod, u32(view.storage), row.levels, row.layers, row.pitch,
                         row.bits, row.tile_mode, row.array_mode, row.bank_swizzle, u32(row.alt_tile),
                         row.flags, mips.empty() ? "-" : mips.c_str());
    }
}

void BloodPoolProbe::CopyBoundIndex(const RenderState& render, const BoundIndex& index,
                                   const IndexCommand& command) {
    if (!WantsBoundIndex(command.count, command.guest_first)) return;
    const auto& draw = infos[capture][pending.ordinal];
    if (note_due || !draw.noted || !draw.indexed || draw.first_index != command.guest_first) return;
    if (bound_layer_enabled) {
        NoteBoundLayers(render, command, std::exchange(bound_layer_input, BoundLayerInput{}));
    }
    if (!bound_index_enabled) return;
    auto& result = bound_index_evidence;
    if (++result.issued != 1) {
        result.refusal = "duplicate_issued_draw";
        return;
    }
    const u32 width = index.type == vk::IndexType::eUint16 ? 2u :
        index.type == vk::IndexType::eUint32 ? 4u : 0u;
    const u64 prefix = index.offset % 4;
    const u64 payload = u64(command.count) * width;
    const u64 bytes = (prefix + payload + 3) & ~u64(3);
    const auto& fixture = IndexFixtures[bound_index_target - 1];
    result.refusal = "binding_command_or_extent_unconfirmed";
    if (!command.confirmed || !index.buffer || !index.transfer_src ||
        !width || !command.instances || command.instances != draw.instances || command.vk_first != 0 ||
        command.topology != vk::PrimitiveTopology::eTriangleList || command.restart ||
        render.width != IndexSceneWidth || render.height != IndexSceneHeight || render.num_layers != 1 ||
        !render.color_attachments[2].image_view || render.color_attachments[2].is_clear ||
        !render.depth_stencil_attachment.has_depth || render.depth_stencil_attachment.depth_clear ||
        !render.depth_stencil_attachment.image_view || index.offset % width || index.guest % width ||
        index.bytes != payload || !payload || bytes > u64(fixture.count) * sizeof(u32) ||
        index.offset > index.capacity || bytes > index.capacity - (index.offset - prefix)) {
        return;
    }
    // The proven fixture payloads are multiples of four; the optional prefix/suffix
    // would sample indices outside the mapped draw extent. Refuse instead.
    if (prefix || bytes != payload) {
        result.refusal = "unaligned_exact_range";
        return;
    }
    result.refusal = "staging_allocation_failed";
    auto staging = WorkflowProbe::AllocateTransfer(instance.GetAllocator(), bytes);
    if (!staging) return;
    result.refusal = "render_pass_cannot_suspend_for_readback";
    if (!scheduler.SuspendRenderingForReadback(render)) return;

    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    runtime.FlushBarriers();
    scheduler.RecordCrumb({.name = "blood pool bound index t178"},
                          [src = index.buffer, dst = staging->buffer, offset = index.offset,
                           bytes](vk::CommandBuffer cmd) {
        EffectPass::MemoryBarrier(cmd, Stage::eAllCommands | Stage::eHost,
                                  Access::eMemoryWrite | Access::eHostWrite,
                                  Stage::eCopy, Access::eTransferRead);
        const vk::BufferCopy range{.srcOffset = offset, .dstOffset = 0, .size = bytes};
        cmd.copyBuffer(src, vk::Buffer{dst}, range);
        EffectPass::MemoryBarrier(cmd, Stage::eCopy, Access::eTransferWrite,
                                  Stage::eHost, Access::eHostRead);
        EffectPass::MemoryBarrier(cmd, Stage::eCopy, Access::eTransferRead,
                                  Stage::eAllCommands, Access::eMemoryWrite);
    });
    staging->tick = scheduler.CurrentTick();
    scheduler.DeferPriorityOperation([staging] {});
    scheduler.BeginRendering(render);
    result.transfer = std::move(staging);
    result.command = command;
    result.serial = bound_index_serial;
    result.frame = capture;
    result.ordinal = pending.ordinal;
    result.width = width;
    result.offset = index.offset;
    result.sealed = index.sealed;
    result.generation = index.generation;
    result.refusal = "staged";
}

void BloodPoolProbe::LogBoundIndex(bool gpu_done) {
    if (!bound_index_target) return;
    const auto& fixture = IndexFixtures[bound_index_target - 1];
    if (bound_layer_enabled) LogBoundLayers(gpu_done, fixture.name);
    if (!bound_index_enabled) {
        bound_index_target = 0;
        return;
    }
    IndexEvidence result = std::exchange(bound_index_evidence, IndexEvidence{});
    bound_index_target = 0;
    const auto refuse = [&](const char* reason) {
        BbReport::Printf("Blood bound index (t178): refusing %s serial=%llu reason=%s\n",
                         fixture.name, Log64(bound_index_serial), reason);
    };
    if (result.issued != 1 || !result.transfer) {
        refuse(result.refusal);
        return;
    }
    const auto& stage = *result.transfer;
    if (!gpu_done || !scheduler.IsFree(stage.tick)) {
        refuse("gpu_pending");
        return;
    }
    if (result.serial != bound_index_serial || result.frame != R::CaptureFrames - 1 ||
        result.ordinal >= infos[result.frame].size() || !infos[result.frame][result.ordinal].probed ||
        over_cap[0] || over_cap[1]) {
        refuse("stale_or_truncated_owner_capture");
        return;
    }
    const u32 box_px = box.Width() * box.Height();
    const auto* map = static_cast<const u32*>(owners.mapped);
    const u32 token = R::OwnerValue(result.frame, result.ordinal);
    if (!map || !std::all_of(map, map + box_px, [=](u32 value) { return value == token; }) ||
        !std::all_of(map + 2 * box_px, map + 3 * box_px, [=](u32 value) { return value == token; })) {
        refuse("albedo_or_depth_owner_differs");
        return;
    }
    if (!stage.mapped || stage.start || stage.bytes != stage.payload ||
        stage.payload != u64(fixture.count) * result.width ||
        vmaInvalidateAllocation(stage.allocator, stage.allocation, 0, VK_WHOLE_SIZE) != VK_SUCCESS) {
        refuse("staging_unmapped_or_wrong_extent");
        return;
    }
    const auto& command = result.command;
    BbReport::Printf("Blood bound index (t178): begin %s serial=%llu frame=%u ordinal=%u "
                     "scene=1920x1080 box=%u:%u:%u:%u a=%u z=%u vs=%08x ps=%08x "
                     "count=%u guest_first=%u vk_first=%u width=%u bytes=%llu offset=%llu "
                     "vertex_offset=%d instances=%u first_instance=%u topology=triangle_list "
                     "restart=0 sealed=%u generation=%u tick=%llu\n",
                     fixture.name, Log64(result.serial), result.frame, result.ordinal,
                     box.x0, box.y0, box.x1, box.y1, box_px, box_px, IndexVs, IndexPs,
                     command.count, command.guest_first, command.vk_first, result.width,
                     Log64(stage.payload), Log64(result.offset), command.vertex_offset,
                     command.instances, command.first_instance, u32(result.sealed), result.generation,
                     Log64(stage.tick));
    constexpr u32 chunk = 256;
    constexpr char hex[] = "0123456789abcdef";
    const auto* payload = static_cast<const u8*>(stage.mapped);
    for (u32 start = 0; start < stage.payload; start += chunk) {
        const u32 size = std::min<u32>(chunk, u32(stage.payload) - start);
        char line[chunk * 2 + 1];
        for (u32 i = 0; i < size; ++i) {
            const u8 value = payload[start + i];
            line[2 * i] = hex[value >> 4];
            line[2 * i + 1] = hex[value & 15];
        }
        line[2 * size] = '\0';
        BbReport::Printf("Blood bound index (t178): data serial=%llu at=%u %s\n",
                         Log64(result.serial), start, line);
    }
    BbReport::Printf("Blood bound index (t178): end serial=%llu\n", Log64(result.serial));
}

void BloodPoolProbe::AfterDraw() {
    if (FoliageCapturing()) {
        auto& cap = *foliage;
        auto& frame = cap.frames[capture];
        if (std::exchange(cap.draw_open, false)) {
            ++frame.delivered;
            if (cap.open_ordinal < R::MaxDraws) {
                frame.issued.set(cap.open_ordinal);
            }
            if (cap.current_state) {
                ++cap.census[cap.current_state - 1].delivered[capture];
            }
        } else {
            ++frame.orphan_after;
        }
    }
    if (!pending.on) {
        return;
    }
    const Pending p = pending;
    pending = {};
    DrawInfo& info = infos[capture][p.ordinal];
    const SceneUseScope scene_use{"blood pool probe"};
    scheduler.EndRendering();
    std::array<vk::ImageView, R::Targets> views{};
    bool lost = false;
    for (u32 t = 0; t < R::Targets; ++t) {
        if ((p.mask >> t) & 1u) {
            views[t] = ViewOf(p.ids[t], t == R::DepthTarget ? vk::ImageAspectFlagBits::eDepth
                                                            : vk::ImageAspectFlagBits::eColor);
            lost = lost || !views[t];
        }
    }
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (lost) {
        info.skipped = NoView;
        return;
    }
    const vk::ImageView any = views[std::countr_zero(p.mask)];
    for (auto& view : views) {
        view = view ? view : any;
    }
    R::Push push{};
    push.box[0] = s32(box.x0);
    push.box[1] = s32(box.y0);
    push.box[2] = s32(box.Width());
    push.box[3] = s32(box.Height());
    push.grid[0] = s32(grid_cols);
    push.grid[1] = s32(grid_rows);
    push.grid[2] = s32(R::Stride);
    push.mask = p.mask;
    push.record = (capture * R::MaxDraws + p.ordinal) * R::RecordWords;
    push.owner = R::OwnerValue(capture, p.ordinal);
    push.owner_targets = p.owner_targets;
    const u32 gx = (std::max(box.Width(), grid_cols) + R::Group - 1) / R::Group;
    const u32 gy = (std::max(box.Height(), grid_rows) + R::Group - 1) / R::Group;
    scheduler.RecordCrumb({.name = "blood pool probe compare"},
                          [views, push, gx, gy, prints_buffer = prints.buffer, counts_buffer = counts.buffer,
                           owners_buffer = owners.buffer, pipeline_handle = *compare_pass.pipeline,
                           layout = *compare_pass.layout](vk::CommandBuffer cmd) {
                              RecordPass(cmd, pipeline_handle, layout, views, prints_buffer, counts_buffer,
                                         owners_buffer, push, gx, gy);
                          });
    info.probed = true;
}

bool BloodPoolProbe::StartCapture() {
    if (!scene_depth || scene_width == 0 || scene_height == 0) {
        return false;
    }
    const auto& depth_image = texture_cache.GetImage(scene_depth);
    cap_width = scene_width;
    cap_height = scene_height;
    capture_reduced = scene_targets.Reduced() && scene_targets.EligibleScene(depth_image);
    pixels_width = cap_width;
    pixels_height = cap_height;
    if (capture_reduced) {
        pixels_width = scene_targets.Size().width;
        pixels_height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        pixels_width = std::min(pixels_width, render[0]);
        pixels_height = std::min(pixels_height, render[1]);
    }
    if (box_glass) { // bbport (t86q): the glass rectangle (1280x720 picture pixels or fractions) in scene pixels
        const R::Knob scaled = GlassFindRules::Scale(glass_rect, pixels_width, pixels_height);
        if (scaled.kind == R::Kind::Box) {
            box = scaled;
        }
    }
    if (box.x1 >= pixels_width || box.y1 >= pixels_height) {
        BbReport::Printf("Blood pool probe (r100d): box x %u-%u y %u-%u is not inside the %ux%u scene; "
                         "not probed\n",
                         box.x0, box.x1, box.y0, box.y1, pixels_width, pixels_height);
        state = State::Idle;
        return false;
    }
    if (!Ready()) {
        return false;
    }
    grid_cols = (pixels_width + R::Stride - 1) / R::Stride;
    grid_rows = (pixels_height + R::Stride - 1) / R::Stride;
    const vk::DeviceSize need =
        (vk::DeviceSize(box.Width()) * box.Height() + vk::DeviceSize(grid_cols) * grid_rows) * R::Targets * 4;
    if (need > prints_size) {
        if (prints.buffer) {
            scheduler.DeferOperation([allocator = instance.GetAllocator(), buffer = prints.buffer,
                                      allocation = prints.allocation] {
                vmaDestroyBuffer(allocator, buffer, allocation);
            });
            prints = {};
            prints_size = 0;
        }
        if (!EffectPass::HasRoom(instance, need) ||
            !MakeBuffer(prints, need, false, vk::BufferUsageFlagBits::eStorageBuffer)) {
            prints = {};
            Fail("no room for the prints");
            return false;
        }
        prints_size = need;
    }
    for (auto& list : infos) {
        list.clear();
        list.reserve(2048);
    }
    over_cap = {};
    capture = 0;
    pending = {};
    if ((bound_index_enabled || bound_layer_enabled) && !box_glass && !box.cut &&
        !capture_reduced &&
        pixels_width == IndexSceneWidth && pixels_height == IndexSceneHeight) {
        for (u32 i = 0; i < IndexFixtures.size(); ++i) {
            const auto& fixture = IndexFixtures[i];
            if (!(bound_index_targets & (1u << i)) && box.x0 == fixture.x0 && box.y0 == fixture.y0 &&
                box.x1 == fixture.x1 && box.y1 == fixture.y1) {
                bound_index_target = u8(i + 1);
                bound_index_targets |= u8(1u << i);
                ++bound_index_serial;
                break;
            }
        }
    }
    if (box_glass && FoliageWanted()) {
        static_assert(sizeof(FoliageCapture) + sizeof(foliage) + sizeof(foliage_serial) +
                          sizeof(FoliageDrawSelection) < 480 * 1024);
        static_assert(FoliageSelectedLimit >= FoliageSelectorLimit);
        static_assert(FoliageLimit < 255 && R::CaptureFrames == 2);
        ++foliage_serial;
        foliage.reset(new (std::nothrow) FoliageCapture{.selection = FoliageSelectedDraws()});
        if (!foliage) {
            std::printf("Foliage mask probe (t132a): serial=%llu INCONCLUSIVE host allocation failed\n",
                        Log64(foliage_serial));
        }
    }
    // The counters and owner maps start at 0 (the host reads them once the GPU is past the frames).
    scheduler.EndRendering();
    scheduler.RecordCrumb({.name = "blood pool probe clear"},
                          [counts_buffer = counts.buffer, owners_buffer = owners.buffer](vk::CommandBuffer cmd) {
                              EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryRead,
                                                        Transfer, vk::AccessFlagBits2::eTransferWrite);
                              cmd.fillBuffer(counts_buffer, 0, VK_WHOLE_SIZE, 0);
                              cmd.fillBuffer(owners_buffer, 0, VK_WHOLE_SIZE, 0);
                              EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                                                        Compute, ReadWrite);
                          });
    return true;
}

void BloodPoolProbe::EndCapture() {
    scheduler.EndRendering();
    scheduler.RecordCrumb({.name = "blood pool probe done"}, [](vk::CommandBuffer cmd) {
        EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite,
                                  vk::PipelineStageFlagBits2::eHost, vk::AccessFlagBits2::eHostRead);
    });
    done_tick = scheduler.CurrentTick();
}

void BloodPoolProbe::OnFrameEnd() {
    if (pending.on) {
        if (state == State::Capturing && pending.ordinal < infos[capture].size()) {
            infos[capture][pending.ordinal].skipped = LeftOut;
        }
        pending = {};
    }
    if (const u32 generation = BbLiveKnobs::Generation(); generation != knob_generation) {
        knob_generation = generation;
        TakeKnob(false);
        TakeGlass(false); // bbport (t86q_glass-finder, TOOL)
    }
    switch (state) {
    case State::Idle:
        if (find_pending && !failed) { // bbport (t86q_glass-finder, TOOL): a wide find
            find_pending = false;
            arm_find = true;
            box_glass = false;
            arm_need = find_live ? R::ArmFramesLive : R::ArmFramesStart;
            arm_frames = 0;
            state = State::Armed;
            BbReport::Printf("Glass finder (t86q): wide find armed (%s); lists the last of %u scene frames after %u "
                             "frames in a row with a G-buffer pass\n",
                             find_live ? "live knobs file" : "at start", find_frames, arm_need);
            break;
        }
        if (next_glass && !failed) { // bbport (t86q_glass-finder, TOOL): a rectangle find (r100d's capture)
            next_glass = false;
            arm_find = false;
            box_glass = true;
            box = {};
            box_live = glass_live;
            arm_need = glass_live ? R::ArmFramesLive : R::ArmFramesStart;
            arm_frames = 0;
            state = State::Armed;
            BbReport::Printf("Glass finder (t86q): rectangle %s armed (%s); probed after %u frames in a row with a "
                             "G-buffer pass\n",
                             glass_text, glass_live ? "live knobs file" : "at start", arm_need);
            break;
        }
        if (next.kind == R::Kind::Box && !failed) {
            box_glass = false; // bbport (t86q): a blood box
            arm_find = false;
            box = next;
            box_live = next_live;
            next = {};
            arm_need = box_live ? R::ArmFramesLive : R::ArmFramesStart;
            arm_frames = 0;
            state = State::Armed;
            BbReport::Printf("Blood pool probe (r100d): box x %u-%u y %u-%u (%u px)%s armed (%s); probed "
                             "after %u frames in a row with a G-buffer pass\n",
                             box.x0, box.x1, box.y0, box.y1, box.Width() * box.Height(),
                             box.cut ? ", a side cut to 256" : "", box_live ? "live knobs file" : "at start",
                             arm_need);
        }
        break;
    case State::Armed:
        arm_frames = frame_gbuffer && !camera_motion.PreviewFrame() ? arm_frames + 1 : 0;
        if (arm_frames >= arm_need && arm_find) { // bbport (t86q): the wide find needs no pass or buffer
            for (auto& list : infos) {
                list.clear();
                list.reserve(2048);
            }
            over_cap = {};
            capture = 0;
            pending = {};
            find_frame = 0;
            find_sums.clear();
            state = State::Finding;
            BbReport::Printf("Glass finder (t86q): wide find running, %u scene frames\n", find_frames);
        } else if (arm_frames >= arm_need && StartCapture()) {
            state = State::Capturing;
        }
        break;
    case State::Capturing:
        if (foliage) {
            auto& frame = foliage->frames[capture];
            frame.stats_end = BbStats::frame_number.load(std::memory_order_relaxed);
            frame.gbuffer = frame_gbuffer;
            foliage->draw_open = false;
            foliage->note_wanted = false;
        }
        if (++capture >= R::CaptureFrames) {
            capture = R::CaptureFrames - 1;
            EndCapture();
            state = State::Waiting;
            wait_frames = 0;
        }
        break;
    case State::Finding: // bbport (t86q_glass-finder, TOOL)
        FindFrameEnd();
        break;
    case State::Waiting:
        if (scheduler.IsFree(done_tick) || ++wait_frames >= R::WaitFrames) {
            if (box_glass) {
                GlassRectLog(); // bbport (t86q): the glass finder's reading of the same capture
                foliage.reset();
            } else {
                Log();
            }
            state = State::Idle;
        }
        break;
    }
    frame_gbuffer = frame_lit = false;
    ordinal = 0;
    note_due = false;
}

void BloodPoolProbe::Log() {
    const bool gpu_done = scheduler.IsFree(done_tick);
    if (bound_index_target) LogBoundIndex(gpu_done);
    const auto* c = static_cast<const u32*>(counts.mapped);
    const auto* o = static_cast<const u32*>(owners.mapped);
    const u32 frames = R::CaptureFrames;
    const u32 box_px = box.Width() * box.Height();
    struct Sum {
        u64 vs = 0, ps = 0;
        u32 draws = 0, probed = 0, box_draws = 0, box_max = 0;
        u64 box = 0, frame = 0;
        std::array<u64, R::Targets> by_target{};
        std::array<u32, R::OwnerMaps> own{};
        u32 idx_min = ~0u, idx_max = 0, inst_max = 0;
        u8 phases = 0;
        bool indirect = false;
        const DrawInfo* rep = nullptr;
        bool rep_changed = false;
        int first = -1, last = -1;
    };
    std::vector<Sum> sums;
    std::map<std::pair<u64, u64>, std::size_t> where;
    std::array<u32, 7> skipped{};
    u32 probed = 0;
    int gb_first = -1, gb_last = -1, light_first = -1;
    const u32 last_frame = frames - 1;
    for (u32 f = 0; f < frames; ++f) {
        for (u32 i = 0; i < infos[f].size(); ++i) {
            const DrawInfo& d = infos[f][i];
            const auto [it, added] = where.try_emplace({d.vs, d.ps}, sums.size());
            if (added) {
                sums.push_back({.vs = d.vs, .ps = d.ps});
            }
            Sum& s = sums[it->second];
            ++s.draws;
            s.phases |= d.phase;
            s.indirect = s.indirect || d.indirect;
            if (!d.indirect) {
                s.idx_min = std::min(s.idx_min, d.indices);
                s.idx_max = std::max(s.idx_max, d.indices);
                s.inst_max = std::max(s.inst_max, d.instances);
            }
            if (f == last_frame) {
                s.first = s.first < 0 ? int(i) : s.first;
                s.last = int(i);
                if (d.phase == R::Gbuffer) {
                    gb_first = gb_first < 0 ? int(i) : gb_first;
                    gb_last = int(i);
                } else if (d.phase == R::Light && light_first < 0) {
                    light_first = int(i);
                }
            }
            u32 changed = 0;
            if (d.probed) {
                ++probed;
                ++s.probed;
                const u32* r = c + (std::size_t(f) * R::MaxDraws + i) * R::RecordWords;
                changed = r[R::WordBox];
                s.box += changed;
                s.frame += r[R::WordFrame];
                s.box_max = std::max(s.box_max, changed);
                s.box_draws += changed != 0 ? 1u : 0u;
                for (u32 t = 0; t < R::Targets; ++t) {
                    s.by_target[t] += r[R::WordTarget0 + t];
                }
            } else if (d.skipped < skipped.size()) {
                ++skipped[d.skipped];
            }
            if (!s.rep || (!s.rep_changed && changed != 0)) {
                s.rep = &d;
                s.rep_changed = changed != 0;
            }
        }
    }
    // The owner maps: the last change of each box pixel over the probed frames.
    std::array<u32, R::OwnerMaps> owned{}, owner_pairs{};
    std::vector<std::array<bool, R::OwnerMaps>> owns(sums.size());
    for (u32 m = 0; m < R::OwnerMaps; ++m) {
        for (u32 i = 0; i < box_px; ++i) {
            const u32 v = o[std::size_t(m) * box_px + i];
            const u32 f = (v >> R::OwnerFrameShift) - 1u, n = v & ((1u << R::OwnerFrameShift) - 1u);
            if (v == 0 || f >= frames || n >= infos[f].size()) {
                continue;
            }
            const DrawInfo& d = infos[f][n];
            const std::size_t k = where[{d.vs, d.ps}];
            ++sums[k].own[m];
            ++owned[m];
            if (!owns[k][m]) {
                owns[k][m] = true;
                ++owner_pairs[m];
            }
        }
    }
    std::vector<std::size_t> order;
    for (std::size_t k = 0; k < sums.size(); ++k) {
        const Sum& s = sums[k];
        if (s.box != 0 || s.own[0] != 0 || s.own[1] != 0 || s.own[2] != 0) {
            order.push_back(k);
        }
    }
    std::sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
        const Sum &x = sums[a], &y = sums[b];
        const u64 ox = u64(x.own[0]) + x.own[1] + x.own[2], oy = u64(y.own[0]) + y.own[1] + y.own[2];
        // owners first: full-screen passes change the whole box but own none of it
        return ox != oy ? ox > oy : x.box != y.box ? x.box > y.box : a < b;
    });
    char line[280];
    std::snprintf(line, sizeof(line),
                  "Blood pool probe (r100d): box x %u-%u y %u-%u (%u px)%s of the %ux%u scene%s, %u frames, logged "
                  "%s; last frame: G-buffer draws #%d-%d, light draws from #%d",
                  box.x0, box.x1, box.y0, box.y1, box_px, box.cut ? " (cut)" : "", pixels_width, pixels_height,
                  capture_reduced ? " (reduced)" : "", frames,
                  gpu_done ? "after the GPU" : "BEFORE the GPU was done (counts may be short)", gb_first, gb_last,
                  light_first);
    BbReport::Printf("%s\n", line);
    std::snprintf(line, sizeof(line),
                  "Blood pool probe (r100d): %u draws in the last frame (%u over the cap of %u), %u probed in %u "
                  "frames; not probed: %u lamps apart, %u not scene-sized, %u unreadable, %u left out, %u menu "
                  "preview, %u no view; %zu pairs changed the box",
                  u32(infos[last_frame].size()) + over_cap[last_frame], over_cap[last_frame], R::MaxDraws,
                  probed, frames, skipped[LampsApart], skipped[NotScene], skipped[Unreadable], skipped[LeftOut],
                  skipped[Preview], skipped[NoView], order.size());
    BbReport::Printf("%s\n", line);
    std::snprintf(line, sizeof(line),
                  "Blood pool probe (r100d): last writer of each box pixel (a G-buffer albedo, s scene colour by "
                  "draws over 6 indices, z depth): a %u px by %u pairs, s %u by %u, z %u by %u; none: a %u, s %u, "
                  "z %u",
                  owned[0], owner_pairs[0], owned[1], owner_pairs[1], owned[2], owner_pairs[2], box_px - owned[0],
                  box_px - owned[1], box_px - owned[2]);
    BbReport::Printf("%s\n", line);
    BbReport::Printf("Blood pool probe (r100d): pair lines by own, then box: box px changed a frame, own = last writer, "
                     "frame~ px changed a frame, n draws a frame, p probed, #first-last draw in the last frame, "
                     "P pre-G-buffer G G-buffer B pre-light L light A after; cb:format/role+b blend=box px\n");
    static constexpr const char* PhaseLetters = "PGBLA";
    const u32 shown = std::min<u32>(u32(order.size()), R::MaxLines);
    u64 rest_px = 0;
    for (u32 rank = 0; rank < order.size(); ++rank) {
        const Sum& s = sums[order[rank]];
        if (rank >= shown) {
            rest_px += s.box;
            continue;
        }
        char phases[8] = {};
        for (u32 b = 0, n = 0; b < 5; ++b) {
            if ((s.phases >> b) & 1u) {
                phases[n++] = PhaseLetters[b];
            }
        }
        char idx[40];
        if (s.idx_max == 0 && s.indirect) {
            std::snprintf(idx, sizeof(idx), "indirect");
        } else if (s.idx_min == s.idx_max) {
            std::snprintf(idx, sizeof(idx), "%u%s", s.idx_max, s.indirect ? "+ind" : "");
        } else {
            std::snprintf(idx, sizeof(idx), "%u-%u%s", s.idx_min, s.idx_max, s.indirect ? "+ind" : "");
        }
        if (s.inst_max > 1) {
            const std::size_t used = std::strlen(idx);
            std::snprintf(idx + used, sizeof(idx) - used, "x%u", s.inst_max);
        }
        // The representative draw's targets: cb:format/role, +b blending, m<mask> a partial write
        // mask, =box pixels a frame where that target changed; then the depth.
        std::string targets;
        const DrawInfo& d = *s.rep;
        for (u32 cb = 0; cb < 8; ++cb) {
            if (((d.mrt >> cb) & 1u) == 0 || d.format[cb] == 0) {
                continue;
            }
            const char* name = ColourName(vk::Format(d.format[cb]));
            const u32 mask = (d.write_masks >> (4 * cb)) & 15u;
            char part[48];
            std::snprintf(part, sizeof(part), " %u:%s%s%s%s", cb, name ? name : "int",
                          d.role[cb] ? "/" : "", RoleNames[d.role[cb]], (d.blend >> cb) & 1u ? "+b" : "");
            targets += part;
            if (mask != 15u) {
                std::snprintf(part, sizeof(part), "m%x", mask);
                targets += part;
            }
            std::snprintf(part, sizeof(part), "=%llu", static_cast<unsigned long long>(s.by_target[cb] / frames));
            targets += part;
        }
        {
            char part[48];
            if (d.depth_test) {
                std::snprintf(part, sizeof(part), " d:%s %s%s=%llu", DepthName(vk::Format(d.depth_format)),
                              FuncNames[d.depth_func], d.depth_write ? " w" : "",
                              static_cast<unsigned long long>(s.by_target[R::DepthTarget] / frames));
            } else {
                std::snprintf(part, sizeof(part), " d:-");
            }
            targets += part;
        }
        std::snprintf(line, sizeof(line),
                      "Blood pool probe (r100d): %u/%zu %08llx:%08llx box %llu/f max %u own a%u s%u z%u "
                      "frame~%llu n%u/f p%u%s idx %s #%d-%d %s |%s",
                      rank + 1, order.size(), static_cast<unsigned long long>(s.vs),
                      static_cast<unsigned long long>(s.ps), static_cast<unsigned long long>(s.box / frames),
                      s.box_max, s.own[0], s.own[1], s.own[2],
                      static_cast<unsigned long long>(s.frame * R::Stride * R::Stride / frames), s.draws / frames,
                      s.probed, s.rep_changed ? "" : " (none)", idx, s.first, s.last, phases,
                      targets.c_str());
        BbReport::Printf("%s\n", line);
    }
    if (order.size() > shown) {
        std::snprintf(line, sizeof(line),
                      "Blood pool probe (r100d): %zu more pairs changed the box (%llu px a frame together), not "
                      "listed",
                      order.size() - shown, static_cast<unsigned long long>(rest_px / frames));
        BbReport::Printf("%s\n", line);
    }
    // r100d: the self-check of the counts: every compared draw looked at the whole box and the
    // whole sample grid (r100c's b21 run had draws counting more changed box pixels than the box).
    {
        const u32 want_frame = grid_cols * grid_rows;
        u32 checked = 0, wrong_box = 0, wrong_frame = 0, over_box = 0;
        u32 first_box = 0, first_frame = 0, first_changed = 0;
        bool first = false;
        for (u32 f = 0; f < frames; ++f) {
            for (u32 i = 0; i < infos[f].size(); ++i) {
                if (!infos[f][i].probed) {
                    continue;
                }
                const u32* r = c + (std::size_t(f) * R::MaxDraws + i) * R::RecordWords;
                ++checked;
                const bool box_wrong = r[R::WordSeenBox] != box_px;
                const bool frame_wrong = r[R::WordSeenFrame] != want_frame;
                const bool over = r[R::WordBox] > box_px;
                wrong_box += box_wrong ? 1u : 0u;
                wrong_frame += frame_wrong ? 1u : 0u;
                over_box += over ? 1u : 0u;
                if (!first && (box_wrong || frame_wrong || over)) {
                    first = true;
                    first_box = r[R::WordSeenBox];
                    first_frame = r[R::WordSeenFrame];
                    first_changed = r[R::WordBox];
                }
            }
        }
        std::snprintf(line, sizeof(line),
                      "Blood pool probe (r100d): self-check, %u compared draws: %u saw other than the %u box px, "
                      "%u other than the %u samples, %u changed more box px than the box; %s (first: saw %u "
                      "box px, %u samples, changed %u)",
                      checked, wrong_box, box_px, wrong_frame, want_frame, over_box,
                      first ? "COUNTS WRONG" : "counts sound", first_box, first_frame, first_changed);
        BbReport::Printf("%s\n", line);
    }
    // r100d: the draws of the pair that owns the most box albedo, each draw on its own line (a decal
    // mesh drawn with the ground's shaders shows as one small draw owning the pool; the ground's
    // texture as the same large draw in the pool box and the control box).
    std::size_t top = sums.size();
    for (std::size_t k = 0; k < sums.size(); ++k) {
        if (sums[k].own[0] != 0 && (top == sums.size() || sums[k].own[0] > sums[top].own[0])) {
            top = k;
        }
    }
    if (top == sums.size()) {
        BbReport::Printf("Blood pool probe (r100d): draw lines: no pair owns box albedo\n");
        return;
    }
    const Sum& top_sum = sums[top];
    std::map<u32, std::array<u32, 2>> by_draw; // owner value: own a, own z
    for (u32 m = 0; m < R::OwnerMaps; m += 2) {
        for (u32 i = 0; i < box_px; ++i) {
            const u32 v = o[std::size_t(m) * box_px + i];
            const u32 f = (v >> R::OwnerFrameShift) - 1u, n = v & ((1u << R::OwnerFrameShift) - 1u);
            if (v == 0 || f >= frames || n >= infos[f].size()) {
                continue;
            }
            const DrawInfo& d = infos[f][n];
            if (d.vs == top_sum.vs && d.ps == top_sum.ps) {
                ++by_draw[v][m == 0 ? 0 : 1];
            }
        }
    }
    std::vector<std::pair<u32, u32>> listed; // own a, owner value
    u32 listed_px = 0, owning = 0;
    for (const auto& [v, own] : by_draw) {
        owning += own[0] != 0 ? 1u : 0u;
        if (own[0] != 0 && u64(own[0]) * R::DrawLineShare >= box_px) {
            listed.emplace_back(own[0], v);
            listed_px += own[0];
        }
    }
    std::sort(listed.begin(), listed.end(), [](const auto& a, const auto& b) {
        return a.first != b.first ? a.first > b.first : a.second < b.second;
    });
    std::snprintf(line, sizeof(line),
                  "Blood pool probe (r100d): draws of %08llx:%08llx (own a%u of %u box px; %u draws a frame): %u "
                  "own albedo, %zu own at least 1/%u of the box (%u px); by own: f frame#draw, idx count, first "
                  "index @index buffer, textures address:WxH:format",
                  static_cast<unsigned long long>(top_sum.vs), static_cast<unsigned long long>(top_sum.ps),
                  top_sum.own[0], box_px, top_sum.draws / frames, owning, listed.size(), R::DrawLineShare, listed_px);
    BbReport::Printf("%s\n", line);
    for (std::size_t rank = 0; rank < listed.size() && rank < R::MaxDrawLines; ++rank) {
        const u32 v = listed[rank].second;
        const u32 f = (v >> R::OwnerFrameShift) - 1u, n = v & ((1u << R::OwnerFrameShift) - 1u);
        const DrawInfo& d = infos[f][n];
        const u32* r = c + (std::size_t(f) * R::MaxDraws + n) * R::RecordWords;
        char idx[64];
        if (d.indirect) {
            std::snprintf(idx, sizeof(idx), "indirect");
        } else if (!d.noted) {
            std::snprintf(idx, sizeof(idx), "%u first ? (no note)", d.indices);
        } else if (!d.indexed) {
            std::snprintf(idx, sizeof(idx), "%u (not indexed)", d.indices);
        } else {
            std::snprintf(idx, sizeof(idx), "%u first %u @%llx", d.indices, d.first_index,
                          static_cast<unsigned long long>(d.index_address));
        }
        if (d.instances > 1) {
            const std::size_t used = std::strlen(idx);
            std::snprintf(idx + used, sizeof(idx) - used, " x%u", d.instances);
        }
        std::string textures;
        for (u32 i = 0; i < d.texture_count; ++i) {
            char part[64];
            std::snprintf(part, sizeof(part), " %llx:%ux%u:%u",
                          static_cast<unsigned long long>(d.textures[i].address), d.textures[i].width,
                          d.textures[i].height, d.textures[i].format);
            textures += part;
        }
        std::snprintf(line, sizeof(line),
                      "Blood pool probe (r100d): draw %c f%u#%u own a%u z%u box %u frame~%llu idx %s tex %u h%08x%s",
                      char('A' + rank), f, n, by_draw[v][0], by_draw[v][1], d.probed ? r[R::WordBox] : 0u,
                      static_cast<unsigned long long>(u64(d.probed ? r[R::WordFrame] : 0u) * R::Stride * R::Stride),
                      idx, d.textures_all, d.texture_hash, textures.c_str());
        BbReport::Printf("%s\n", line);
    }
}

// bbport (r100d_blood-pool-draws, TOOL): once the draw's textures are bound (DrawRecord and
// DrawIndirectRecord, after BindResources and BeginRendering): its index range and textures, for the
// probe's draw lines. dc.bound_images lists the draw's colour targets, then its depth target, then
// every stage's images (as SparkProbeDraw reads it).
void Rasterizer::BloodPoolProbeNote(const GraphicsPipeline* pipeline, bool indirect, bool is_indexed,
                                    u32 index_offset) {
    const auto& dc = Dc();
    const auto& regs = Regs();
    const u32 mrt = u32(pipeline->GetGraphicsKey().mrt_mask);
    u32 own = db_desc.first ? 1u : 0u;
    for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
        own += ((mrt >> cb) & 1u) != 0 && cb_descs[cb].first ? 1u : 0u;
    }
    std::array<BloodPoolProbe::Texture, BloodPoolProbeRules::DrawTextures> textures{};
    u32 count = 0;
    u64 hash = 0xcbf29ce484222325ull;
    for (std::size_t i = own; i < dc.bound_images.size(); ++i) {
        const auto& image = texture_cache.GetImage(dc.bound_images[i]);
        hash = (hash ^ image.info.guest_address) * 0x100000001b3ull;
        if (count < textures.size()) {
            textures[count++] = {.address = image.info.guest_address,
                                 .width = image.info.size.width,
                                 .height = image.info.size.height,
                                 .format = u32(image.info.pixel_format)};
        }
    }
    const bool indexed = is_indexed && !indirect;
    const auto foliage_token = blood_pool_probe->FoliageNoteToken(indexed, index_offset);
    blood_pool_probe->Note(indexed, indexed ? regs.index_base_address.Address<VAddr>() : 0, indexed ? index_offset : 0,
                           textures, count,
                           u32(dc.bound_images.size() > own ? dc.bound_images.size() - own : 0),
                           u32(hash ^ (hash >> 32)));
    if (indexed && blood_pool_probe->bound_layer_enabled &&
        blood_pool_probe->WantsBoundIndex(regs.num_indices, index_offset)) {
        blood_pool_probe->bound_layer_input = {
            .writes = &dc.set_writes,
            .images = {dc.bound_images.data(), dc.bound_images.size()},
            .pipeline = pipeline,
            .frame = blood_pool_probe->capture,
            .ordinal = blood_pool_probe->pending.ordinal,
        };
    }
    if (foliage_token) {
        const auto facts = FoliageProbeFacts(*pipeline, foliage_token->camera_gbuffer, indirect,
                                            is_indexed, index_offset);
        blood_pool_probe->NoteFoliageFacts(*foliage_token, facts);
    }
}

// bbport (r100c_blood-pool-probe, TOOL): the probe's before-draw hook (direct and indirect draws).
void Rasterizer::BloodPoolProbeBefore(const GraphicsPipeline* pipeline, bool indirect, bool light) {
    static_assert(AmdGpu::NUM_COLOR_BUFFERS == 8);
    std::array<VideoCore::ImageId, 8> targets{};
    for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
        targets[cb] = cb_descs[cb].first;
    }
    if (blood_pool_probe->FoliageCapturing()) {
        BloodPoolProbe::FoliageTargetViews views{};
        for (u32 cb = 0; cb < targets.size(); ++cb) {
            if (targets[cb]) {
                views[cb] = &cb_descs[cb].second.view_info;
            }
        }
        if (db_desc.first) {
            views.back() = &db_desc.second.view_info;
        }
        blood_pool_probe->BeforeDraw(Regs(), *pipeline, targets, db_desc.first, light,
                                    point_shadow->Pending(), indirect, &views);
        return;
    }
    blood_pool_probe->BeforeDraw(Regs(), *pipeline, targets, db_desc.first, light, point_shadow->Pending(),
                                 indirect);
}

} // namespace Vulkan
