// SPDX-License-Identifier: GPL-3.0-or-later

#include "video_core/renderer_vulkan/vk_point_shadow.h"

#include <algorithm>
#include <array>
#include <bit>
#include <chrono> // bbport (r65_lamp-half-at-start): how long the pipelines took
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "bbport_live_knobs.h" // bbport (r87_live-flip-knobs): TOOL
#include "bbport_settings.h"
#include "bbport_toggles.h"
#include "common/assert.h"
#include "video_core/host_shaders/point_shadow_comp.h"
#include "video_core/host_shaders/point_shadow_ray_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_comp.h" // bbport (r32_lamp-half)
// bbport (r63_leaf-stage4): the builds of BB_RT_CARD_LAMPS=1
#include "video_core/host_shaders/point_shadow_ray_cards_comp.h"
#include "video_core/host_shaders/point_shadow_ray_centred_cards_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_cards_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_centred_cards_comp.h"
// bbport (r60_lamp-centred-window): the builds of BB_LAMP_SHADOW_WINDOW=2
#include "video_core/host_shaders/point_shadow_ray_centred_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_centred_comp.h"
// bbport (r61_lamp-window-cost): the resolves' own builds of BB_LAMP_SHADOW_WINDOW=2
#include "video_core/host_shaders/point_shadow_ray_half_resolve_comp.h"
#include "video_core/host_shaders/point_shadow_ray_resolve_comp.h"
// bbport (r92_lamp-shadow-colour): the COLOUR builds of BB_LAMP_SHADOW_COLOUR=1
#include "video_core/host_shaders/point_shadow_ray_centred_colour_comp.h"
#include "video_core/host_shaders/point_shadow_ray_colour_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_centred_colour_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_colour_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_resolve_colour_comp.h"
#include "video_core/host_shaders/point_shadow_ray_resolve_colour_comp.h"
#include "video_core/renderer_vulkan/lamp_moving_edge.h" // bbport (r101_lamp-moving-edge)
#include "video_core/renderer_vulkan/lamp_shadow_layers.h" // bbport (r114_lamp-shadow-layers)
#include "video_core/renderer_vulkan/lamp_young_pixels.h" // bbport (r103_lamp-young-pixels)
#include "video_core/renderer_vulkan/lamp_moving_smooth.h" // bbport (r60c_moving-shadow-steps)
#include "video_core/renderer_vulkan/lamp_flame.h" // bbport (r113_lamp-softness)
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_gpu_profiler.h" // bbport (r61_lamp-window-cost)
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_rt_shadow.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
struct Push {
    u32 first_light;
    u32 frame_index;
    std::array<float, 2> size;
    float length_m;
    float thickness_m;
    float strength;
    float fade_start_m;
    float fade_end_m;
    u32 light_count;
    u32 steps;
    float bias_m;
    std::array<s32, 4> rect;
};
static_assert(sizeof(Push) == 64);

constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr vk::ImageSubresourceRange ColorRange{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
constexpr vk::ImageSubresourceLayers ColorLayers{vk::ImageAspectFlagBits::eColor, 0, 0, 1};
constexpr auto TargetFormat = vk::Format::eB10G11R11UfloatPack32;
constexpr u32 ConstantWords = 16, LightWords = 16;
// A batch of lamps drawn apart holds a whole frame's lights (16 words each, once per tile and
// lamp quad): 64K words held about 3,800, eight per tile on average, and a batch split for room is
// traced without reuse. 256K words is 1 MB.
constexpr u32 DataWords = 256 * 1024;
constexpr u32 UpdateWords = 16 * 1024;
constexpr u32 WholeImageBatches = 4;
constexpr u32 SnapshotCell = 16;
// What Flush adds for the first ray traced pass of a frame. bbport (r42_lamp-soft): four more
// words (LampHistoryTail): the most frames a texel of the history may hold, how far a moving
// lamp's shadows may trail, how near a moving lamp a caster is taken to move with it, and how
// far the history may lie from the answers around a pixel (point_shadow_ray.comp HISTORY_BLEND).
constexpr u32 HistoryWords = 2 + 12 + 16 + LampHistoryTailWords;
constexpr u32 ModeApart = 1;              // point_shadow_ray.comp MODE_APART
// bbport (r41_lamp-shadows): MODE_REPAIR, and where the place of the pass's tuning words
// (LampTuneWords) goes in the same word: bits 8-31. The shader only tests single bits below
// that; with DataWords 2^18 the word stays below 2^27.
constexpr u32 ModeRepair = 16;
constexpr u32 TuneAtShift = 8;
static_assert(DataWords <= 1u << (32 - TuneAtShift));
// bbport (r32_lamp-half): more bits of the same word, read only by point_shadow_ray_half_comp
// (MODE_HALF_*); its counters (HALF_SLOTS words used); the experiment bit that turns it off.
constexpr u32 ModeHalfFirst = 2, ModeHalfFill = 4, ModeHalfCount = 8;
constexpr u32 HalfSlots = 16;
constexpr u64 HalfOffBit = 72057594037927936ull;
// bbport (r60_lamp-centred-window): two more bits of the same word, read only by the builds made
// with CENTRED (point_shadow_ray.comp MODE_TRACE, MODE_RESOLVE): the pass that averages runs as a
// trace, which stores every pixel's answer in `answers`, and a resolve, which centres the ghost
// clamp's 5x5 window on every pixel. Single bits below the tuning words' place, none taken.
constexpr u32 ModeTrace = 32, ModeResolve = 64;
static_assert(ModeResolve < 1u << TuneAtShift &&
              ((ModeTrace | ModeResolve) & (ModeApart | ModeRepair | ModeHalfFirst | ModeHalfFill |
                                            ModeHalfCount)) == 0);
// One texel a pixel: the answer's float bits and the cast code (a half float) beside the strongest
// lamp's record / 16 in 16 bits. A storage format every Vulkan device has: 8 bytes a pixel.
constexpr auto AnswersFormat = vk::Format::eR32G32Uint;
// The records start on 16-word steps (after ConstantWords, LightWords each) below 2^20.
static_assert(ConstantWords % 16 == 0 && LightWords == 16 && DataWords <= 1u << 20);
// bbport (r44_half-area-lamp): set: a pass at half resolution has point lamps without a history,
// as before r44 (hard-edged shadows; for pictures of before and after). Read at every pass.
constexpr u64 HalfPointsBit = 2305843009213693952ull;
// bbport (r48_lamp-softness): a lamp radius for each graphics_lamp_shadow_softness value
static_assert(LampSoftnessRadii.size() == std::size_t(BbSettings::LampSoftnessCount));
constexpr u32 TileWords = 8;
constexpr auto HistoryFormat = vk::Format::eR16G16B16A16Sfloat;
// bbport (r52_follow-soft): the follow state (a storage format every Vulkan device has)
constexpr auto FollowFormat = vk::Format::eR32Sfloat;
constexpr u32 HistoryRead = 1, HistoryWrite = 2;
// bbport (r42_lamp-soft): the history holds the shadow ratio averaged over the frames
// (point_shadow_ray.comp HISTORY_BLEND); frames between two lines that say where the lamps are.
constexpr u32 HistoryBlend = 4;
// bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1: two more bits of the history block's
// flags, set only with HistoryBlend on a pass that shadows in colour (point_shadow_ray.comp
// HISTORY_COLOUR_READ, HISTORY_COLOUR_ONE): the colour image's part that holds the colour of the
// history this pass reads is to be read (the pass that wrote that history wrote its colour), and
// this frame's part is the second. The colour image: ColourParts parts of the pass's size stacked
// (the colour history pair and the pass's own answers), 4 bytes a pixel each.
constexpr u32 HistoryColourRead = 8, HistoryColourOne = 16;
static_assert(((HistoryColourRead | HistoryColourOne) & (HistoryRead | HistoryWrite | HistoryBlend)) == 0);
constexpr auto ColourFormat = vk::Format::eA2B10G10R10UnormPack32;
constexpr u32 ColourParts = 3;
constexpr u32 LampLineFrames = 600;
// A pass that averages shows bare single rays on a frame on which it cannot read what the frame
// before left (the first frame, a new size, a cut). After this many such frames in a row its
// lamps are points until it can (Flush).
constexpr u32 UnreadMost = 8;
constexpr u32 SoftLines = 24; // the most "Ray traced lamps (r42): <state>" lines
// bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1: one more bit of the same word, read only by the
// CARDS builds (point_shadow_ray.comp MODE_CARD_COUNT): the pass adds to the card counters (one
// pass in CardCountEvery). The most set 1s a run makes (CardLampSet).
constexpr u32 ModeCardCount = 128;
static_assert(ModeCardCount < 1u << TuneAtShift &&
              (ModeCardCount & (ModeApart | ModeRepair | ModeHalfFirst | ModeHalfFill | ModeHalfCount |
                                ModeTrace | ModeResolve)) == 0);
constexpr u32 CardCountEvery = 16;
constexpr u32 CardSetsMost = 8;
static_assert(CARD_LAMP_COUNTERS == 72); // bbport (r62h_cutout-cards-hit): was 16; r62j: was 32, then 48; r62k: was 48, then 64; r62l: was 64 (header.h card_last)
static_assert(CARD_LAMP_SOLID_FIRST < CARD_LAMP_KEPT_D0 && CARD_LAMP_KEPT_D0 + 3 == CARD_LAMP_KEPT_D3 &&
              CARD_LAMP_KEPT_D3 < CARD_LAMP_RESCUED && CARD_LAMP_RESCUED < CARD_LAMP_LOD16 &&
              CARD_LAMP_LOD16 < CARD_LAMP_SPLIT_READS && CARD_LAMP_SPLIT_READS < CARD_LAMP_COUNTERS);
// bbport (r62i_cutout-uv-proof): its nine counters fill the last of the 32
static_assert(CARD_LAMP_SPLIT_READS < CARD_LAMP_PROOF_PIXELS && CARD_LAMP_PROOF_NO_CARD == CARD_LAMP_PROOF_PIXELS + 1 &&
              CARD_LAMP_PROOF_UNJUDGED == CARD_LAMP_PROOF_NO_CARD + 5 &&
              CARD_LAMP_PROOF_UV_OUTSIDE == CARD_LAMP_PROOF_UNJUDGED + 2);
// bbport (r62j_cutout-rule-and-place): its eleven counters follow, then spare ones
static_assert(CARD_LAMP_PROOF_LAMP_KEPT == CARD_LAMP_PROOF_UV_OUTSIDE + 1 &&
              CARD_LAMP_PROOF_FRONT_LAMP_KEPT == CARD_LAMP_PROOF_LAMP_KEPT + 10 &&
              CARD_LAMP_PROOF_FRONT_LAMP_KEPT < CARD_LAMP_COUNTERS);
// bbport (r62k_cutout-lit-fence): its eighteen counters follow, then spare ones
static_assert(CARD_LAMP_FRONT_BILIN == CARD_LAMP_PROOF_FRONT_LAMP_KEPT + 1 && CARD_LAMP_FRONT_NEAR == CARD_LAMP_FRONT_BILIN + 2 &&
              CARD_LAMP_JUDGED_BILIN == CARD_LAMP_FRONT_NEAR + 1 && CARD_LAMP_JUDGED_NEAR == CARD_LAMP_JUDGED_BILIN + 2 &&
              CARD_LAMP_LIT_PIXELS == CARD_LAMP_JUDGED_NEAR + 1 && CARD_LAMP_LIT_SUM_DEPTH == CARD_LAMP_LIT_PIXELS + 11 &&
              CARD_LAMP_LIT_SUM_DEPTH < CARD_LAMP_COUNTERS);
// bbport (r62l_cutout-steady-proof): its four counters follow, then spare ones
static_assert(CARD_LAMP_LIT_NEAR == CARD_LAMP_LIT_SUM_DEPTH + 1 && CARD_LAMP_LIT_ON_CARD == CARD_LAMP_LIT_NEAR + 3 &&
              CARD_LAMP_LIT_ON_CARD < CARD_LAMP_COUNTERS);
// bbport (r62m_cutout-name-blocker) TOOL: the blocker book follows the counters in the buffer (rt_card_layers_layout.h)
static_assert(CARD_LAMP_BOOK == CARD_LAMP_COUNTERS && CARD_LAMP_BOOK_NO_SLOT == CARD_LAMP_BOOK + CARD_BOOK_ENTRIES * CARD_BOOK_WORDS &&
              CARD_LAMP_BOOK_FULL == CARD_LAMP_BOOK_NO_SLOT + 1 && CARD_LAMP_BUFFER_WORDS == CARD_LAMP_BOOK_FULL + 1);
// bbport (r62g_cutout-shadows-visible): the counters it adds (rt_card_layers_layout.h) lie in the 16
static_assert(CARD_LAMP_BLIND < CARD_LAMP_LOD_READS && CARD_LAMP_LOD_READS < CARD_LAMP_ZERO_READS &&
              CARD_LAMP_ZERO_READS < CARD_LAMP_PARTIAL_READS && CARD_LAMP_PARTIAL_READS < CARD_LAMP_SHARP_RAYS &&
              CARD_LAMP_SHARP_RAYS < CARD_LAMP_CARD_ONLY && CARD_LAMP_CARD_ONLY < CARD_LAMP_SOLID_FIRST &&
              CARD_LAMP_SOLID_FIRST < CARD_LAMP_COUNTERS);

// bbport (r62g_cutout-shadows-visible): the CARDS builds' specialization constants 1 and 2
// (point_shadow_ray.comp CARD_DISC, CARD_VIEW_SHARE), read once from the environment, and only by the code
// that makes a CARDS build (BB_RT_CARD_LAMPS=1). BB_RT_CARD_LAMP_RADIUS: metres, 0 to 0.5, default 0.02 (a
// value that is not a number: the default); 0.5: the cards are tested on the lamp's own disc, as before.
// BB_RT_CARD_LAMP_SHARE_VIEW=1: BB_LAMP_SHADOW_VIEW=7 paints the share of rays a card alone blocked.
struct CardExtras {
    float disc_m;
    bool share_view;
    float level_scale; // bbport (r62h_cutout-cards-hit): BB_RT_CARD_LAMP_LEVEL, 0 to 1, default 0
    float ref_scale;   // BB_RT_CARD_LAMP_REF, 0.1 to 1, default 0.6
    float tmin_m;      // BB_RT_CARD_LAMP_TMIN, 0 to 0.2 m, default 0.03
    u32 proof_view;    // bbport (r62i_cutout-uv-proof): BB_RT_CARD_LAMP_PROOF_VIEW, 0 (off), 1 or 2
    u32 gather;        // bbport (r62j_cutout-rule-and-place): BB_RT_CARD_LAMP_GATHER, 0 or 1, default 1
    u32 wrap_clamped;  // BB_RT_CARD_LAMP_WRAP, 0 or 1, default 0
    float lit_share;   // bbport (r62k_cutout-lit-fence): BB_RT_CARD_LIT_SHARE, 0.05 to 1, default 0.5
    float lit_dist_m;  // BB_RT_CARD_LIT_DIST, 0.5 to 15 m, default 4
    float strict_m;    // bbport (r62l_cutout-steady-proof) FEATURE: BB_RT_CARD_LAMP_STRICT, 0 to 2 m, default 0 (off)
    u32 split;         // TOOL: BB_RT_CARD_LAMP_SPLIT, tile size in pixels (16 to 1024), 0 = off
    u32 split_phase;   // TOOL: BB_RT_CARD_LAMP_SPLIT_PHASE, 0 or 1
    float housing_m;   // bbport (r62n_cutout-skinned-blocker) FEATURE: BB_RT_CARD_LAMP_HOUSING, 0 to 2 m, default 0.4 (0: off)
    u32 blocks;        // bbport (r62o_cutout-visible-foliage) FEATURE: BB_RT_CARD_LAMP_BLOCKS, 0 to 3, default 1 (point_shadow_ray.comp CARD_BLOCKS)
};
CardExtras CardExtrasFromEnv() {
    static const CardExtras extras = [] {
        CardExtras e{0.02f, false, 0.0f, 0.5f, 0.03f, 0u, 1u, 0u, 0.5f, 4.0f, 0.0f, 0u, 0u, 0.4f, 1u}; // (r62o_cutout-visible-foliage: the blocks rule) (r62n_cutout-skinned-blocker: the housing zone) (r62h: three more; r62i: the proof view; r62j: REF 0.5, gather, wrap; r62k: lit share, lit distance; r62l: strict zone, split, split phase)
        if (const char* const text = std::getenv("BB_RT_CARD_LAMP_RADIUS")) {
            char* end = nullptr;
            const float value = std::strtof(text, &end);
            if (end != text && std::isfinite(value)) {
                e.disc_m = std::clamp(value, 0.0f, 0.5f);
            }
        }
        const char* const share = std::getenv("BB_RT_CARD_LAMP_SHARE_VIEW");
        e.share_view = share && share[0] == '1';
        // bbport (r62h_cutout-cards-hit): three more numbers (clamped; not a number: the default)
        const auto number = [](const char* name, float fallback, float lo, float hi) {
            if (const char* const text = std::getenv(name)) {
                char* end = nullptr;
                const float value = std::strtof(text, &end);
                if (end != text && std::isfinite(value)) {
                    return std::clamp(value, lo, hi);
                }
            }
            return fallback;
        };
        e.level_scale = number("BB_RT_CARD_LAMP_LEVEL", e.level_scale, 0.0f, 1.0f);
        e.ref_scale = number("BB_RT_CARD_LAMP_REF", e.ref_scale, 0.1f, 1.0f);
        e.tmin_m = number("BB_RT_CARD_LAMP_TMIN", e.tmin_m, 0.0f, 0.2f);
        // bbport (r62i_cutout-uv-proof): BB_RT_CARD_LAMP_PROOF_VIEW 1 or 2 (anything else: off)
        if (const char* const proof = std::getenv("BB_RT_CARD_LAMP_PROOF_VIEW")) {
            e.proof_view = proof[0] >= '1' && proof[0] <= '3' && proof[1] == '\0' ? u32(proof[0] - '0') : 0u; // (r62k_cutout-lit-fence: 3, the lit view)
        }
        // bbport (r62j_cutout-rule-and-place): exactly "0" or "1"; anything else keeps the default
        const auto flag = [](const char* name, u32 fallback) -> u32 {
            const char* const text = std::getenv(name);
            return text && text[0] == '0' && text[1] == '\0' ? 0u : text && text[0] == '1' && text[1] == '\0' ? 1u : fallback;
        };
        e.gather = flag("BB_RT_CARD_LAMP_GATHER", e.gather);
        e.wrap_clamped = flag("BB_RT_CARD_LAMP_WRAP", e.wrap_clamped);
        // bbport (r62k_cutout-lit-fence): BB_RT_CARD_LAMP_GATHER=2: the nearest texel of the footprint (no dilation); the lit patch's
        // two numbers (clamped; not a number: the default)
        if (const char* const gather_text = std::getenv("BB_RT_CARD_LAMP_GATHER");
            gather_text && gather_text[0] == '2' && gather_text[1] == '\0') {
            e.gather = 2u;
        }
        e.lit_share = number("BB_RT_CARD_LIT_SHARE", e.lit_share, 0.05f, 1.0f);
        e.lit_dist_m = number("BB_RT_CARD_LIT_DIST", e.lit_dist_m, 0.5f, 15.0f);
        // bbport (r62l_cutout-steady-proof): the strict zone in metres (FEATURE), the checkerboard's tile size in pixels (TOOL: a whole
        // number from 16; not a number or smaller: off) and its phase (exactly 0 or 1)
        e.strict_m = number("BB_RT_CARD_LAMP_STRICT", e.strict_m, 0.0f, 2.0f);
        if (const char* const split_text = std::getenv("BB_RT_CARD_LAMP_SPLIT")) {
            char* end = nullptr;
            const long value = std::strtol(split_text, &end, 10);
            e.split = end != split_text && *end == '\0' && value >= 16 ? u32(std::min(value, 1024l)) : 0u;
        }
        e.split_phase = flag("BB_RT_CARD_LAMP_SPLIT_PHASE", e.split_phase);
        e.housing_m = number("BB_RT_CARD_LAMP_HOUSING", e.housing_m, 0.0f, 2.0f); // bbport (r62n_cutout-skinned-blocker) FEATURE
        // bbport (r62o_cutout-visible-foliage) FEATURE: BB_RT_CARD_LAMP_BLOCKS exactly "0", "1", "2" or "3"; anything else keeps the default
        if (const char* const blocks_text = std::getenv("BB_RT_CARD_LAMP_BLOCKS");
            blocks_text && blocks_text[0] >= '0' && blocks_text[0] <= '3' && blocks_text[1] == '\0') {
            e.blocks = u32(blocks_text[0] - '0');
        }
        return e;
    }();
    return extras;
}

// bbport (r63_leaf-stage4): a CARDS build: set 0 as EffectPass::Create makes it for the build
// without CARDS (push descriptors, the same types in the same order, the same push constants),
// so the two pipeline layouts are compatible for set 0 (and with r61's resolve build, which has
// the centred build's bindings: its pushes do not disturb set 1); set 1 the cards (`cards`).
// texel_scale: the shader's specialization constant 0 (CARD_TEXEL_SCALE), fixed when it is made.
bool MakeCardBuild(vk::Device device, vk::DescriptorSetLayout cards,
                   vk::UniqueDescriptorSetLayout& set_layout, vk::UniquePipelineLayout& layout,
                   vk::UniquePipeline& pipeline, std::initializer_list<vk::DescriptorType> types,
                   std::span<const u32> code, float texel_scale, u32 colour_images = 0) {
    std::vector<vk::DescriptorSetLayoutBinding> bindings;
    bindings.reserve(types.size());
    for (const vk::DescriptorType type : types) {
        bindings.push_back({u32(bindings.size()), type, 1, vk::ShaderStageFlagBits::eCompute});
    }
    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1: the colour image's binding after the
    // last, in the layout only (a CARDS build has no COLOUR form and does not read it), so that set 0
    // is as the COLOUR builds have it and pushes of r61's resolve build do not disturb set 1
    for (u32 i = 0; i < colour_images; ++i) {
        bindings.push_back({u32(bindings.size()), vk::DescriptorType::eStorageImage, 1,
                            vk::ShaderStageFlagBits::eCompute});
    }
    auto set = device.createDescriptorSetLayoutUnique({
        .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
        .bindingCount = u32(bindings.size()),
        .pBindings = bindings.data(),
    });
    if (set.result != vk::Result::eSuccess) {
        return false;
    }
    const std::array<vk::DescriptorSetLayout, 2> sets{*set.value, cards};
    const vk::PushConstantRange push{vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push)};
    auto made = device.createPipelineLayoutUnique({
        .setLayoutCount = u32(sets.size()),
        .pSetLayouts = sets.data(),
        .pushConstantRangeCount = 1,
        .pPushConstantRanges = &push,
    });
    if (made.result != vk::Result::eSuccess) {
        return false;
    }
    const auto [module_result, module] =
        device.createShaderModule({.codeSize = code.size_bytes(), .pCode = code.data()});
    if (module_result != vk::Result::eSuccess) {
        return false;
    }
    // bbport (r62g_cutout-shadows-visible): constant 0 the texel scale, 1 CARD_DISC (m), 2 CARD_VIEW_SHARE
    const CardExtras extras = CardExtrasFromEnv();
    // (r62h_cutout-cards-hit: constants 3 CARD_LEVEL_SCALE, 4 CARD_REF_SCALE, 5 CARD_TMIN)
    const std::array<u32, 16> spec_words{std::bit_cast<u32>(texel_scale), std::bit_cast<u32>(extras.disc_m),
                                        extras.share_view ? 1u : 0u, std::bit_cast<u32>(extras.level_scale),
                                        std::bit_cast<u32>(extras.ref_scale), std::bit_cast<u32>(extras.tmin_m),
                                        extras.proof_view, extras.gather,
                                        extras.wrap_clamped, std::bit_cast<u32>(extras.lit_share),
                                        std::bit_cast<u32>(extras.lit_dist_m), std::bit_cast<u32>(extras.strict_m),
                                        extras.split, extras.split_phase, std::bit_cast<u32>(extras.housing_m), extras.blocks}; // (r62o_cutout-visible-foliage: 15 CARD_BLOCKS) // (r62n_cutout-skinned-blocker: 14 CARD_HOUSING) (r62l_cutout-steady-proof: 11 CARD_STRICT, 12 CARD_SPLIT, 13 CARD_SPLIT_PHASE) (r62i: constant 6 CARD_PROOF; r62j_cutout-rule-and-place: 7 CARD_GATHER, 8 CARD_WRAP_CLAMPED; r62k_cutout-lit-fence: 9 CARD_LIT_SHARE, 10 CARD_LIT_DIST)
    const std::array<vk::SpecializationMapEntry, 16> spec_entries{{{0, 0, 4}, {1, 4, 4}, {2, 8, 4}, {3, 12, 4}, {4, 16, 4}, {5, 20, 4}, {6, 24, 4}, {7, 28, 4}, {8, 32, 4}, {9, 36, 4}, {10, 40, 4}, {11, 44, 4}, {12, 48, 4}, {13, 52, 4}, {14, 56, 4}, {15, 60, 4}}};
    const vk::SpecializationInfo spec{u32(spec_entries.size()), spec_entries.data(), sizeof(spec_words),
                                      spec_words.data()};
    auto built = device.createComputePipelineUnique(
        {}, vk::ComputePipelineCreateInfo{
                .flags = vk::PipelineCreateFlagBits::eDispatchBase,
                .stage = {.stage = vk::ShaderStageFlagBits::eCompute,
                          .module = module,
                          .pName = "main",
                          .pSpecializationInfo = &spec},
                .layout = *made.value,
            });
    device.destroyShaderModule(module);
    if (built.result != vk::Result::eSuccess) {
        return false;
    }
    set_layout = std::move(set.value);
    layout = std::move(made.value);
    pipeline = std::move(built.value);
    return true;
}

// bbport (r92_lamp-shadow-colour): a lamp build's SPIR-V, or its COLOUR form's (BB_LAMP_SHADOW_COLOUR=1)
std::span<const u32> ColourCode(bool colour, std::span<const u32> plain, std::span<const u32> coloured) {
    return colour ? coloured : plain;
}

std::array<float, 16> Invert(const u32* words, bool& ok) {
    std::array<double, 32> t{};
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) {
            t[r * 8 + c] = std::bit_cast<float>(words[r * 4 + c]);
        }
        t[r * 8 + 4 + r] = 1.0;
    }
    ok = false;
    std::array<float, 16> out{};
    for (int p = 0; p < 4; ++p) {
        int best = p;
        for (int r = p + 1; r < 4; ++r) {
            if (std::abs(t[r * 8 + p]) > std::abs(t[best * 8 + p])) {
                best = r;
            }
        }
        if (std::abs(t[best * 8 + p]) < 1e-12) {
            return out;
        }
        for (int c = 0; c < 8; ++c) {
            std::swap(t[p * 8 + c], t[best * 8 + c]);
        }
        const double scale = 1.0 / t[p * 8 + p];
        for (int c = 0; c < 8; ++c) {
            t[p * 8 + c] *= scale;
        }
        for (int r = 0; r < 4; ++r) {
            if (r != p) {
                const double f = t[r * 8 + p];
                for (int c = 0; c < 8; ++c) {
                    t[r * 8 + c] -= f * t[p * 8 + c];
                }
            }
        }
    }
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) {
            out[r * 4 + c] = float(t[r * 8 + 4 + c]);
        }
    }
    ok = std::ranges::all_of(out, [](float v) { return std::isfinite(v); });
    return out;
}

std::array<float, 12> Multiply(const std::array<float, 12>& a, const std::array<float, 12>& b) {
    std::array<float, 12> out{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 4; ++c) {
            float sum = c == 3 ? a[r * 4 + 3] : 0.0f;
            for (int k = 0; k < 3; ++k) {
                sum += a[r * 4 + k] * b[k * 4 + c];
            }
            out[r * 4 + c] = sum;
        }
    }
    return out;
}

bool Overlaps(const std::array<s32, 4>& a, const std::array<s32, 4>& b) {
    return a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
}
}

PointShadow::PointShadow(const Instance& instance_, Scheduler& scheduler_,
                         VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                         SceneTargets& scene_targets_, CameraMotion& camera_motion_,
                         RtShadow& rt_shadow_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_},
      runtime{runtime_}, scene_targets{scene_targets_}, rt_shadow{rt_shadow_},
      camera_motion{camera_motion_} {
    fade_start_m = fade_end_m * 0.6f;
    // bbport (r41_lamp-shadows): BB_LAMP_SHADOW_*, read once
    LampMovingSmoothApply(); // bbport (r60c_moving-shadow-steps): BB_LAMP_SHADOW_MOVING_SMOOTH, before the knobs below are read
    tune = ReadLampShadowTune([](const char* name) -> const char* { return std::getenv(name); });
    if (const char* env = std::getenv("LANTERN_RT_LAMPS_EXACT"); env && env[0] == '1') {
        lamp_pick = 0;
    }
    // bbport: off unless asked for. Until the tile count reached the pass (Flush) it never ran;
    // now it would cover the whole screen (lamps apart), where a shadow that moves into a settled
    // 8x8 block shows up to three frames late. It saves 0.4 of the pass's 0.8 ms at 1920x1080.
    if (const char* env = std::getenv("LANTERN_RT_LAMP_REUSE")) {
        lamp_reuse = env[0] == '1';
    }
    // bbport (r37_menu-options): set, the variable decides ("1" on, else off); not set,
    // graphics_lamp_shadow_half does (Flush, every pass).
    if (const char* env = std::getenv("BB_LAMP_SHADOW_HALF"); env && env[0]) {
        half_env = env[0] == '1' ? 1 : 0;
    }
    if (half_env == 1) { // bbport (r32_lamp-half)
        std::printf("Ray traced lamps (r32): BB_LAMP_SHADOW_HALF=1, one shadow answer per 2x2 "
                    "block first, then full-resolution rays where the answers around a pixel "
                    "differ (changes the picture; experiment 72057594037927936 set = full "
                    "resolution)\n");
    }
    // bbport (r65_lamp-half-at-start): the pass's pipelines were made at the first lamp draw
    // (Ready, from OnLightDraw) and the half-resolution build at the first pass that wanted it
    // (HalfReady, from Flush): both during play, each a one-time stall of the draw thread while
    // the driver compiles them (EffectPass::Create, as every effect pass here: no pipeline cache
    // of ours, no compile thread). Now, when the pass is wanted at start (the test OnLightDraw
    // makes), they are made here, at start, as RtShadow's constructor makes the sun's. Ready
    // makes the same objects as it would later and reads only what is fixed by now (RtShadow's
    // setup, this constructor's knobs, lantern.ini), so the picture does not change. Not wanted
    // at start, or BB_LAMP_SHADOW_AT_START=0: on first use, as before.
    const char* const at_start_env = std::getenv("BB_LAMP_SHADOW_AT_START");
    const bool early = !at_start_env || at_start_env[0] != '0';
    if (early && (BbSettings::Get().effects[BbSettings::EffectPointShadows].load(std::memory_order_relaxed) ||
                  RaysWanted())) {
        at_start = true;
        Ready();
        at_start = false;
    } else {
        std::printf("Ray traced lamps (r65): the pass's pipelines are made on first use (%s)\n",
                    early ? "lamp shadows are off at start" : "BB_LAMP_SHADOW_AT_START=0");
    }
}

// bbport (r65_lamp-half-at-start): one test for Flush and Ready (see the header)
bool PointShadow::HalfWanted() const {
    return half_env >= 0 ? half_env == 1
                         : BbSettings::Get().graphics_lamp_shadow_half.load(std::memory_order_relaxed);
}

bool PointShadow::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    const auto r65_began = std::chrono::steady_clock::now(); // bbport (r65_lamp-half-at-start)
    using enum vk::DescriptorType;
    const bool made =
        instance.GetPhysicalDevice().getFeatures().shaderStorageImageExtendedFormats &&
        EffectPass::StorageFormat(instance, TargetFormat) &&
        EffectPass::CreateSampler(instance, sampler, vk::Filter::eNearest) &&
        EffectPass::Create(instance, set_layout, layout, pipeline,
                           {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                            eStorageImage, eStorageImage},
                           sizeof(Push), POINT_SHADOW_COMP, "Point shadows", true);
    if (!made) {
        failed = true;
        std::printf("Point shadows: off - this GPU cannot run the pass\n");
        return false;
    }
    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1 (read once, LampShadowTune::colour):
    // every lamp build below and in HalfReady is made in its COLOUR form (point_shadow_ray.comp
    // COLOUR: one binding more, the colour image, after the build's last), and the CARDS builds'
    // layouts get that binding too; a build that cannot be made falls back as the plain one would,
    // to the next build in its COLOUR form. Not on a device that cannot store the image's format.
    colour_mode = tune.colour && EffectPass::StorageFormat(instance, ColourFormat);
    if (tune.colour) {
        std::printf("Ray traced lamps (r92): coloured lamp shadows %s (BB_LAMP_SHADOW_COLOUR=1): each lamp's "
                    "share of a pixel's shadow keeps the lamp's colour, so where a warm and a cool lamp "
                    "overlap the shadow of one is lit in the other's colour; the lamp light keeps the luma "
                    "the grey ratio gives it, and the grey ratio is still what the history's guards take; "
                    "one image of 12 bytes a pixel (the colour history pair and the pass's own colour "
                    "answers); passes that run a CARDS build (BB_RT_CARD_LAMPS=1) or LANTERN_RT_LAMP_REUSE's "
                    "history stay grey\n",
                    !colour_mode              ? "off - this GPU cannot store A2B10G10R10 in a compute pass"
                    : rt_shadow.Capturing() ? "on"
                                            : "on, but no ray traced lamp pass is made (no ray tracing)");
    }
    // bbport (r61_lamp-window-cost, r73_lamp-resolve-list-check): the centred build and the
    // resolves' own build of it must take the same bindings, as Flush pushes one set of descriptor
    // writes to whichever of the two runs; so the list is written once, here, and both are made
    // through this.
    const auto make_centred = [&](vk::UniqueDescriptorSetLayout& set, vk::UniquePipelineLayout& lay,
                                  vk::UniquePipeline& pipe, std::span<const u32> code, const char* name) {
        if (colour_mode) { // bbport (r92_lamp-shadow-colour): binding 12, the colour image
            return EffectPass::Create(instance, set, lay, pipe,
                                      {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                                       eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                                       eStorageImage, eStorageImage, eStorageImage, eStorageImage, eStorageImage},
                                      sizeof(Push), code, name, true);
        }
        return EffectPass::Create(instance, set, lay, pipe,
                                  {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                                   eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                                   eStorageImage, eStorageImage, eStorageImage, eStorageImage},
                                  sizeof(Push), code, name, true);
    };
    // bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW=2: the build with the centred window
    // and binding 11, its answers image. It cannot be made: the window of 1, said in the log.
    centred = tune.window && tune.window_centred;
    if (centred && rt_shadow.Capturing() &&
        !make_centred(ray_set_layout, ray_layout, ray_pipeline,
                      ColourCode(colour_mode, POINT_SHADOW_RAY_CENTRED_COMP, POINT_SHADOW_RAY_CENTRED_COLOUR_COMP), // r92
                      "Ray traced lamps")) {
        std::printf("Ray traced lamps (r60): the centred window's pass could not be made: "
                    "BB_LAMP_SHADOW_WINDOW=1\n");
        centred = false;
        tune.window_centred = false;
    }
    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1: the plain build's COLOUR form, binding 11
    // the colour image (then not the plain build below)
    if (colour_mode && !centred && rt_shadow.Capturing() &&
        !EffectPass::Create(instance, ray_set_layout, ray_layout, ray_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                             eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                             eStorageImage, eStorageImage, eStorageImage, eStorageImage},
                            sizeof(Push), POINT_SHADOW_RAY_COLOUR_COMP, "Ray traced lamps (colour)", true)) {
        std::printf("Ray traced lamps: off - the pass could not be made (r92: its COLOUR form)\n");
    }
    // bbport (r52_follow-soft): bindings 9 and 10, the follow state
    if (!colour_mode && !centred && rt_shadow.Capturing() &&
        !EffectPass::Create(instance, ray_set_layout, ray_layout, ray_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                             eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                             eStorageImage, eStorageImage, eStorageImage},
                            sizeof(Push), POINT_SHADOW_RAY_COMP, "Ray traced lamps", true)) {
        std::printf("Ray traced lamps: off - the pass could not be made\n");
    }
    // bbport (r61_lamp-window-cost): with the centred build, the resolves' own build (the centred
    // build in which every dispatch is a resolve: its ray code cannot be reached, so the driver may
    // drop it and give the build fewer registers), unless BB_LAMP_SHADOW_RESOLVE_BUILD starts with
    // 0. Same bindings (make_centred) and push constants as the centred build. Not made: the
    // resolves run the centred build, which r60 ran them in, said in the log.
    if (centred && ray_pipeline) {
        const char* const resolve_env = std::getenv("BB_LAMP_SHADOW_RESOLVE_BUILD");
        resolve_wanted = !resolve_env || resolve_env[0] != '0';
        if (resolve_wanted && !make_centred(resolve_set_layout, resolve_layout, resolve_pipeline,
                                            ColourCode(colour_mode, POINT_SHADOW_RAY_RESOLVE_COMP,
                                                       POINT_SHADOW_RAY_RESOLVE_COLOUR_COMP), // bbport (r92)
                                            "Ray traced lamps (resolve)")) {
            std::printf("Ray traced lamps (r61): the resolves' own build could not be made: they run the "
                        "centred build\n");
        }
    }
    if (ray_pipeline) { // bbport (r41_lamp-shadows, r42_lamp-soft)
        CardLampsReady(false); // bbport (r63_leaf-stage4): its CARDS form, made here with it
        // bbport (r48_lamp-softness): the radius graphics_lamp_shadow_softness gives now (Flush
        // takes it again at every pass)
        tune.radius_m = LampSoftnessRadius(
            tune, BbSettings::Get().graphics_lamp_shadow_softness.load(std::memory_order_relaxed));
        // bbport (r53_lamp-housekeeping): at radius 0 (sharp) there is no disc and no history
        char lamp_text[160];
        if (tune.radius_m > 0.0f) {
            std::snprintf(lamp_text, sizeof lamp_text,
                          "area lamp radius %.2f m, one ray a lamp a frame, history %.2f (up to %.1f frames)",
                          tune.radius_m, tune.history, LampHistoryFrames(tune));
        } else {
            std::snprintf(lamp_text, sizeof lamp_text,
                          "point lamp (radius 0.00 m), the same ray every frame, nothing averaged over frames");
        }
        std::printf("Ray traced lamps (r42): weights %s (wrap %.2f, floor %.2f, inverse-square "
                    "%s); %s, kept within %.1f deviations of the answers around a pixel, "
                    "reject %.2f, trail %.2f m, follows moving lamps %s (what blocks one within "
                    "%.2f m of it moves with it); starved moving copies %s lamp rays; clearance "
                    "%.2f m, bias %.3f m, self skip %.2f m, view %u (BB_LAMP_SHADOW_*); "
                    "experiment 35184372088832 set = the path before r41\n",
                    tune.weights ? "as the game's falloff and facing" : "as before", tune.wrap,
                    tune.facing_floor,
                    BbSettings::Get().startup_local_inverse_square ? "on" : "off", lamp_text,
                    tune.around, tune.reject, tune.trail_m,
                    tune.follow ? "yes" : "no", tune.carry_m,
                    tune.stale ? "are left out of" : "stay in", tune.clearance_m, tune.bias_m,
                    tune.self_m, tune.view);
        std::printf("Ray traced lamps (r52): soft follow %s (BB_LAMP_SHADOW_FOLLOW_SOFT): under a moving "
                    "lamp the history is read where the surface was and where the lamp's motion puts it, "
                    "mixed per pixel by a follow state and by how well each fits this frame's ray (a mix "
                    "that is unsure where the two differ holds fewer frames), not by the 5x5 vote of its "
                    "workgroup; with BB_LAMP_SHADOW_FOLLOW=0 only where the surface was; 0 = the vote\n",
                    tune.follow_soft ? "yes" : "no");
        // bbport (r91_lamp-radius-per-lamp): said once, when on
        if (tune.disc_each > 0.0f) {
            std::printf("Ray traced lamps (r91): BB_LAMP_SHADOW_RADIUS_PER_LAMP=%.4f: in the pass that averages "
                        "each lamp has a disc of its own, clamp(%.4f x its reach, %.2f m, %.2f m) x the softness "
                        "radius / %.1f m, at most %.1f m (sharp: none, the knob changes nothing); a followed "
                        "lamp's disc moves %.4f of the way to that each frame (%.1f times larger or smaller: at "
                        "once, a jump); its rays are blind within the larger of BB_LAMP_SHADOW_CLEARANCE and its "
                        "radius + %.2f m; the lamp line shows each near lamp's disc and its jumps since the line "
                        "before\n",
                        tune.disc_each, tune.disc_each, LampDiscLeast, LampDiscMost, LampSoftnessRadii[1],
                        LampDiscCap, LampDiscFollow, LampDiscJump, LampClearanceOverRadius);
        }
        // bbport (r57_lamp-window); r60_lamp-centred-window: the window of 2
        const char* const window_what =
            tune.window && centred ? "the 5x5 answers centred on every pixel bound the history (2, the centred "
                                     "window: see the r60 line)"
            : tune.window      ? "the 5x5 answers of the workgroup bound the history"
            : tune.follow_soft ? "at full resolution no answer of another pixel reaches a pixel (the half-resolution "
                                 "build still shares agreeing 3x3 blocks): its history is bound by its own last "
                                 "frames and capped by one fixed swing; a change of less than about 0.86 of the "
                                 "light is not cut but fades"
                               : "the history is bound by the pixel's own last frames, but with "
                                 "BB_LAMP_SHADOW_FOLLOW_SOFT=0 the vote and its cap still take the 5x5 answers";
        std::printf("Ray traced lamps (r57): window %s (BB_LAMP_SHADOW_WINDOW): %s; 1 = the 5x5 "
                    "answers of the workgroup bound the history and their far blockers cap its frames under a "
                    "moving lamp, as before r57\n",
                    tune.window ? "yes" : "no", window_what);
        // bbport (r60_lamp-centred-window): what the value 2 costs, said whether it is on or not
        std::printf("Ray traced lamps (r60): centred window %s (BB_LAMP_SHADOW_WINDOW=2; the default is %u): "
                    "the 5x5 answers that bound the history and cap its frames are centred on every "
                    "pixel, not confined to its 8x8 workgroup, meant to leave no squares fixed to the "
                    "screen behind moving shadows (not measured; the half-resolution build still shares "
                    "agreeing 3x3 blocks and copies a taken block's history); costs one dispatch and "
                    "barrier more (two at half resolution) and one image of 8 bytes a pixel (16.6 MB at "
                    "1920x1080, 66.4 MB at 3840x2160), made only with 2\n",
                    centred ? "yes" : "no", unsigned(LampWindowDefault));
        // bbport (r61_lamp-window-cost): what the value 2 does to save time, when it is on
        if (centred) {
            std::printf("Ray traced lamps (r61): the centred window's resolve stops at once in a workgroup "
                        "its trace answered no pixel of, loads only the ring of its tile and no lamp light "
                        "it does not use (the same as r60 in logic, not yet proven in bits); its build: %s "
                        "(BB_LAMP_SHADOW_RESOLVE_BUILD; 0 = the centred build, which r60 ran them in)\n",
                        resolve_pipeline ? "its own" : resolve_wanted ? "the centred one (its own could not be made)"
                                                                      : "the centred one");
        }
        LampYoungStartLine(centred, tune.spatial); // bbport (r103_lamp-young-pixels): only with the knob set
        // bbport (r93_lamp-shadow-spatial): BB_LAMP_SHADOW_SPATIAL=1, said once (on or off and why first:
        // the slot runs keep 300 characters of a line)
        if (tune.spatial) {
            std::printf("Ray traced lamps (r93): spatial pre-filter %s (BB_LAMP_SHADOW_SPATIAL=1%s): the centred "
                        "window's resolve takes into the history this frame's answer mixed with the mean of it and "
                        "its 3x3 neighbours that have an answer and lie on the pixel's plane (point_shadow_ray.comp "
                        "spatialMean): all of the mean where no history was found, none where the pixel's last "
                        "frames were all lit or all dark, else 8 r (1 - r) of it, r the history's ratio; every "
                        "guard against trails takes the raw answer; nothing with sharp lamps (no history), views "
                        "2, 3 and 7, or in a half-resolution pass that runs its plain build\n",
                        centred ? "on" : "off",
                        centred ? ""
                                : "; it needs the centred window, BB_LAMP_SHADOW_WINDOW=2, which this run does not "
                                  "have (not set, or its build could not be made)");
        }
    }
    // bbport (r37_menu-options): the half-resolution build is made by HalfReady, when first wanted.
    // bbport (r65_lamp-half-at-start): or at the end of this function, at start, when wanted then.
    constexpr auto Drawn = vk::FormatFeatureFlagBits::eColorAttachment |
                           vk::FormatFeatureFlagBits::eColorAttachmentBlend;
    lamp_format = (instance.GetPhysicalDevice().getFormatProperties(TargetFormat)
                       .optimalTilingFeatures & Drawn) == Drawn;
    light_data = std::make_unique<VideoCore::Buffer>(
        instance, 0, DataWords * sizeof(u32), VideoCore::MemoryType::DeviceLocal, "Point shadow lights");
    // bbport (r65_lamp-half-at-start): at start, the half-resolution build with the others when a
    // pass would take it now (Flush also needs the ray pass and ray traced lamps wanted), so that
    // the first half-resolution pass does not make it during play. Not at start
    // (BB_LAMP_SHADOW_AT_START=0, or the lamp pass switched on later) or not wanted now: made by
    // the first pass that wants it, as before.
    if (at_start && ray_pipeline && RaysWanted() && HalfWanted()) {
        HalfReady();
    }
    const double r65_ms =
        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - r65_began).count();
    std::printf("Ray traced lamps (r65): the pass's pipelines made %s in %.1f ms (ray traced %s, half "
                "resolution %s); BB_LAMP_SHADOW_AT_START=0 = at the first lamp draw\n",
                at_start ? "at start" : "at the first lamp draw (during play)", r65_ms,
                ray_pipeline ? "yes" : "no",
                half_made ? "yes" : half_tried ? "could not be made" : "not now");
    return true;
}

// bbport (r32_lamp-half, r37_menu-options): the half-resolution build, made the first time a
// pass wants it: the ray pass's bindings, then the block answers (9) and the counters (10).
// bbport (r52_follow-soft): then the follow state (11, 12).
// bbport (r65_lamp-half-at-start): or by Ready when it runs at start and it is wanted then.
bool PointShadow::HalfReady() {
    if (half_tried) {
        return half_made;
    }
    half_tried = true;
    const auto r65_began = std::chrono::steady_clock::now(); // bbport (r65_lamp-half-at-start)
    using enum vk::DescriptorType;
    // bbport (r61_lamp-window-cost, r73_lamp-resolve-list-check): the half-resolution centred
    // build and the resolves' own build of it must take the same bindings, as Ready's pair does;
    // so the list is written once, here, and both are made through this.
    const auto make_half_centred = [&](vk::UniqueDescriptorSetLayout& set, vk::UniquePipelineLayout& lay,
                                       vk::UniquePipeline& pipe, std::span<const u32> code, const char* name) {
        if (colour_mode) { // bbport (r92_lamp-shadow-colour): binding 14, the colour image
            return EffectPass::Create(instance, set, lay, pipe,
                                      {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                                       eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                                       eStorageImage, eStorageImage, eStorageBuffer, eStorageImage, eStorageImage,
                                       eStorageImage, eStorageImage},
                                      sizeof(Push), code, name, true);
        }
        return EffectPass::Create(instance, set, lay, pipe,
                                  {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                                   eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                                   eStorageImage, eStorageImage, eStorageBuffer, eStorageImage, eStorageImage,
                                   eStorageImage},
                                  sizeof(Push), code, name, true);
    };
    // bbport (r60_lamp-centred-window): with the centred window (Ready), its build: binding 13
    // its answers image. If it cannot be made, the plain build (the half-resolution pass then has
    // the window of 1 and does not split; the full-resolution pass keeps 2), said in the log.
    half_centred = ray_pipeline && centred &&
                   make_half_centred(half_set_layout, half_layout, half_pipeline,
                                     ColourCode(colour_mode, POINT_SHADOW_RAY_HALF_CENTRED_COMP,
                                                POINT_SHADOW_RAY_HALF_CENTRED_COLOUR_COMP), // bbport (r92)
                                     "Ray traced lamps (half resolution)");
    if (ray_pipeline && centred && !half_centred) {
        std::printf("Ray traced lamps (r60): the centred window's half-resolution pass could not be made: "
                    "the half-resolution pass has the window of 1 (BB_LAMP_SHADOW_WINDOW=1), the "
                    "full-resolution pass keeps 2\n");
    }
    // bbport (r61_lamp-window-cost): and the resolves' own build of it, as Ready makes the full one
    if (half_centred && resolve_wanted &&
        !make_half_centred(half_resolve_set_layout, half_resolve_layout, half_resolve_pipeline,
                           ColourCode(colour_mode, POINT_SHADOW_RAY_HALF_RESOLVE_COMP,
                                      POINT_SHADOW_RAY_HALF_RESOLVE_COLOUR_COMP), // bbport (r92)
                           "Ray traced lamps (half resolution, resolve)")) {
        std::printf("Ray traced lamps (r61): the half-resolution resolves' own build could not be made: "
                    "they run the centred build\n");
    }
    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1: the plain half-resolution build's COLOUR
    // form, binding 13 the colour image (then not the plain one)
    const bool half_colour_made =
        ray_pipeline && !half_centred && colour_mode &&
        EffectPass::Create(instance, half_set_layout, half_layout, half_pipeline,
                           {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage,
                            eStorageImage, eAccelerationStructureKHR, eStorageImage, eStorageImage, eStorageImage,
                            eStorageBuffer, eStorageImage, eStorageImage, eStorageImage},
                           sizeof(Push), POINT_SHADOW_RAY_HALF_COLOUR_COMP, "Ray traced lamps (half resolution, colour)",
                           true);
    const bool made =
        ray_pipeline &&
        (half_centred || half_colour_made ||
         (!colour_mode && EffectPass::Create(instance, half_set_layout, half_layout, half_pipeline,
                                            {eStorageBuffer, eCombinedImageSampler, eStorageImage,
                                             eStorageImage, eStorageImage, eStorageImage,
                                             eAccelerationStructureKHR, eStorageImage, eStorageImage,
                                             eStorageImage, eStorageBuffer, eStorageImage, eStorageImage},
                                            sizeof(Push), POINT_SHADOW_RAY_HALF_COMP,
                                            "Ray traced lamps (half resolution)", true)));
    if (made) {
        CardLampsReady(true); // bbport (r63_leaf-stage4): its CARDS form, made here with it
    }
    if (made) {
        half_counts = std::make_unique<VideoCore::Buffer>(
            instance, 0, HalfSlots * sizeof(u32), VideoCore::MemoryType::DeviceLocal,
            "Ray traced lamp half counters");
        half_readback = std::make_unique<VideoCore::Buffer>(
            instance, 0, HalfSlots * sizeof(u32), VideoCore::MemoryType::HostCached,
            "Ray traced lamp half counters readback");
        if (half_readback->mapped_data.size() >= HalfSlots * sizeof(u32)) {
            std::memset(half_readback->mapped_data.data(), 0, HalfSlots * sizeof(u32));
            half_made = true;
        }
    }
    // bbport (r42_lamp-soft, r44_half-area-lamp): and what it does to the area lamp (see Flush)
    std::printf("Ray traced lamps (r32): half resolution (%s) %s; at half resolution the lamps "
                "are area lamps averaged over the frames as at full resolution (r44: one pixel "
                "of each 2x2 block is traced and averaged first, its answer is shared where the "
                "blocks around a pixel agree, every other pixel casts its own ray and keeps its "
                "own history; experiment 2305843009213693952 set = point lamps without a "
                "history, as before r44)\n",
                half_env == 1 ? "BB_LAMP_SHADOW_HALF=1" : "graphics_lamp_shadow_half=1",
                half_made ? "ready" : "ignored - no pipeline");
    // bbport (r65_lamp-half-at-start): what this build cost, and when (during play it is a stall)
    std::printf("Ray traced lamps (r65): the half-resolution build made %s in %.1f ms\n",
                at_start ? "at start" : "during play",
                std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - r65_began).count());
    return half_made;
}

PointShadow::~PointShadow() = default;

// bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1 (RtShadow::CardLampsWanted): the CARDS form of the
// ray pass's build (half: of the half-resolution build), made where that build is made (Ready,
// HalfReady), so that no build is compiled in play; the cards' set layout, pool and counters with
// the first. A build that cannot be made: that pass traces without the cards (said in the log).
void PointShadow::CardLampsReady(bool half) {
    if (!RtShadow::CardLampsWanted() || !ray_pipeline) {
        return;
    }
    const auto device = instance.GetDevice();
    using enum vk::DescriptorType;
    if (!card_set_layout) {
        constexpr auto Stage = vk::ShaderStageFlagBits::eCompute;
        const std::array<vk::DescriptorSetLayoutBinding, 5> bindings{{{0, eStorageBuffer, 1, Stage},
                                                                      {1, eStorageBuffer, 1, Stage},
                                                                      {2, eStorageBuffer, 1, Stage},
                                                                      {3, eCombinedImageSampler, 1, Stage},
                                                                      {4, eStorageBuffer, 1, Stage}}};
        auto set = device.createDescriptorSetLayoutUnique(
            {.bindingCount = u32(bindings.size()), .pBindings = bindings.data()});
        const std::array<vk::DescriptorPoolSize, 2> sizes{
            {{eStorageBuffer, 4 * CardSetsMost}, {eCombinedImageSampler, CardSetsMost}}};
        auto pool = device.createDescriptorPoolUnique(
            {.maxSets = CardSetsMost, .poolSizeCount = u32(sizes.size()), .pPoolSizes = sizes.data()});
        if (set.result != vk::Result::eSuccess || pool.result != vk::Result::eSuccess) {
            std::printf("Ray traced lamps (r63): the cards' descriptor set could not be made: the lamp "
                        "rays leave the cards out\n");
            return;
        }
        card_counts = std::make_unique<VideoCore::Buffer>(
            instance, 0, CARD_LAMP_BUFFER_WORDS * sizeof(u32), VideoCore::MemoryType::DeviceLocal, // bbport (r62m): the book too
            "Ray traced lamp card counters");
        card_readback = std::make_unique<VideoCore::Buffer>(
            instance, 0, CARD_LAMP_BUFFER_WORDS * sizeof(u32), VideoCore::MemoryType::HostCached,
            "Ray traced lamp card counters readback");
        if (card_readback->mapped_data.size() >= CARD_LAMP_BUFFER_WORDS * sizeof(u32)) {
            std::memset(card_readback->mapped_data.data(), 0, CARD_LAMP_BUFFER_WORDS * sizeof(u32));
        }
        card_set_layout = std::move(set.value);
        card_pool = std::move(pool.value);
        const char* const cap_env = std::getenv("BB_RT_CARD_LAMP_CAP");
        card_cap_bits = CardRayCapBits(cap_env ? u32(std::strtoul(cap_env, nullptr, 10)) : 0u);
        const char* const texels_env = std::getenv("BB_RT_CARD_LAMP_TEXELS");
        card_texel_scale =
            CardRayTexelScale(texels_env ? u32(std::strtoul(texels_env, nullptr, 10)) : 0u);
        std::printf("Ray traced lamps (r63): BB_RT_CARD_LAMPS=1: one layer read a card a ray meets, "
                    "at most %u a ray, then the ray is blocked (BB_RT_CARD_LAMP_CAP, 1-63); the "
                    "level from the ray's footprint at %.0f layer texels a metre (a guess; "
                    "BB_RT_CARD_LAMP_TEXELS, 16-4096); a pass traces the cards only while the scene "
                    "holds one with data, else its build of before; BB_LAMP_SHADOW_VIEW=7 shows "
                    "where the rays met them\n",
                    CardRayCap(card_cap_bits), double(card_texel_scale * float(CARD_RAY_TEXELS_PER_M)));
        {
            const CardExtras extras = CardExtrasFromEnv();
            std::printf("Ray traced lamps (r62g): cut-out shadows visible: a lamp whose disc is larger than %.3f m "
                        "(BB_RT_CARD_LAMP_RADIUS, 0 to 0.5, 0.5 = the lamp's own disc as in r63) casts its cut-outs' "
                        "shadows with a disc of that radius: a second ray, to the cards only, for each lit lamp ray, "
                        "while the solid geometry keeps the lamp's disc; BB_LAMP_SHADOW_VIEW=7 %s\n",
                        double(extras.disc_m),
                        extras.share_view ? "paints the share of rays a leaf texel alone blocked (BB_RT_CARD_LAMP_SHARE_VIEW=1)"
                                          : "shows where the rays met cards (BB_RT_CARD_LAMP_SHARE_VIEW=1: the share a card alone blocked)");
        }
        {
            const CardExtras extras = CardExtrasFromEnv(); // bbport (r62h_cutout-cards-hit)
            std::printf("Ray traced lamps (r62h): cut-out cards hit: the lamp rays read the layer at the footprint's "
                        "level times %.2f (BB_RT_CARD_LAMP_LEVEL, 0 to 1; 1 = r63's level, 0 = level 0), keep a texel "
                        "above %.2f times the game's reference where its rule is 'above the reference' "
                        "(BB_RT_CARD_LAMP_REF, 0.1 to 1; 1 = the game's), and the card ray starts at least %.3f m from "
                        "the surface (BB_RT_CARD_LAMP_TMIN, 0 to 0.2 m; 0 = r62g's single ray for a lamp whose disc is "
                        "not larger than the card disc); r62g's behaviour: LEVEL=1 REF=1 TMIN=0\n",
                        double(extras.level_scale), double(extras.ref_scale), double(extras.tmin_m));
        }
        if (const CardExtras extras = CardExtrasFromEnv(); extras.proof_view != 0) { // bbport (r62i_cutout-uv-proof)
            std::printf("Ray traced lamps (r62i): BB_RT_CARD_LAMP_PROOF_VIEW=%u: BB_LAMP_SHADOW_VIEW=7 paints the proof "
                        "of the card chain on every shadowed pixel: a camera ray to a pixel whose surface is a card, "
                        "the layer read at the hit's coordinates (white: kept, as the game kept it, black: dropped, "
                        "magenta: no data, teal: rule not judged, dark blue: not a card%s); the log counts them\n",
                        extras.proof_view, extras.proof_view == 2 ? "; 2: the layer's alpha as grey in place of white/black" : "");
        }
        {
            const CardExtras extras = CardExtrasFromEnv(); // bbport (r62j_cutout-rule-and-place)
            std::printf("Ray traced lamps (r62j): cut-out rule: the lamp rays read a layer texel as the %s "
                        "(BB_RT_CARD_LAMP_GATHER, default 1), keep it above %.2f times the game's reference "
                        "(BB_RT_CARD_LAMP_REF, default 0.5), and %s the axes whose sampler mode is a plain clamp "
                        "(BB_RT_CARD_LAMP_WRAP, default 0: the row's mode); the proof view's line counts what each rule keeps\n",
                        extras.gather == 2 ? "nearest texel of the footprint (r62k)"
                        : extras.gather != 0 ? "maximum of the bilinear footprint's four texels" : "bilinear value",
                        double(extras.ref_scale), extras.wrap_clamped != 0 ? "wrap" : "leave as the row says");
        }
        {
            const CardExtras extras = CardExtrasFromEnv(); // bbport (r62k_cutout-lit-fence)
            std::printf("Foliage lamp shadows (r62k): lit patch finder: a pixel is lit when its strongest lamp is within %.1f m "
                        "(BB_RT_CARD_LIT_DIST) and gives at least %.0f %% of its light (BB_RT_CARD_LIT_SHARE); a window line "
                        "('Foliage lamp shadows (r62k) lit <w>') follows every change of the live knobs file and one after 240 "
                        "frames: pixels lit and under a cut-out's shadow, their centre and bearing; the layer rule is %s "
                        "(BB_RT_CARD_LAMP_GATHER: 0 bilinear, 1 maximum of four, 2 nearest texel); the proof view's window line "
                        "('proof <w>') counts what all three keep; BB_RT_CARD_LAMP_PROOF_VIEW=3 with BB_LAMP_SHADOW_VIEW=7 paints "
                        "the lit view (red lit and under a cut-out's shadow, orange shadow only, green lit)%s\n",
                        double(extras.lit_dist_m), double(extras.lit_share) * 100.0,
                        extras.gather == 2 ? "the nearest texel" : extras.gather == 1 ? "the maximum of four texels" : "bilinear",
                        extras.proof_view == 3 ? " (on)" : "");
        }
        {
            const CardExtras extras = CardExtrasFromEnv(); // bbport (r62l_cutout-steady-proof)
            std::printf("Foliage lamp shadows (r62l): steady proof: BB_RT_CARD_LAMP_STRICT=%.2f m (%s: a kept read within that of the "
                        "ray's start is taken again with the game's own rule); BB_RT_CARD_LAMP_SPLIT=%u px phase %u (%s: the pixels "
                        "of the off tiles of a checkerboard trace no cut-out card, in the same frame as their neighbours: one picture "
                        "is the steady A/B); a window line 'Foliage lamp shadows (r62l) steady <w>' follows r62k's lit line: pixels "
                        "lit and under a cut-out shadow, how many lie on a card surface, how many have the blocker within 10 cm\n",
                        double(extras.strict_m), extras.strict_m > 0.0f ? "on" : "off", extras.split, extras.split_phase,
                        extras.split != 0 ? "on" : "off");
        }
        {
            const CardExtras extras = CardExtrasFromEnv(); // bbport (r62n_cutout-skinned-blocker)
            std::printf("Foliage lamp shadows (r62n): a cut-out card within %.2f m of a lamp casts no lamp shadow (BB_RT_CARD_LAMP_HOUSING, 0 to 2 m, "
                        "0 off: the lamp's own housing or hook); lone skinned cut-outs: the line 'Foliage lamp shadows (r62n) skinned' says the "
                        "mode and the bones (BB_RT_CARD_LAMP_SKINNED, BB_RT_CARD_LAMP_BONES); the window lines of r62m name the blockers "
                        "('is the hunter, a character, a plant, unknown'); a line 'Foliage lamp shadows (r62n) <w>' counts the front reads "
                        "of the proof view and the housing skips\n",
                        double(extras.housing_m));
        }
        {
            const CardExtras extras = CardExtrasFromEnv(); // bbport (r62o_cutout-visible-foliage)
            std::printf("Foliage lamp shadows (r62o): half-resolution blocks, BB_RT_CARD_LAMP_BLOCKS=%u (0 off, 1 the three other pixels of a block whose "
                        "first-pass pixel tested a leaf card cast their own rays, 2 also those of the blocks beside it, 3 only counted; read only by the "
                        "half-resolution lamp pass, graphics_lamp_shadow_half): a leaf shadow a pixel or two wide used to fall between the first-pass "
                        "pixels and be lost; a window line 'Foliage lamp shadows (r62o) <w>' counts the marked blocks and the pixels the rule made trace\n",
                        extras.blocks);
        }
    }
    bool made = false;
    const char* what = "";
    if (half && half_centred) {
        what = "half-resolution centred";
        made = MakeCardBuild(device, *card_set_layout, card_half_set_layout, card_half_layout,
                             card_half_pipeline,
                             {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                              eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                              eStorageImage, eStorageImage, eStorageBuffer, eStorageImage, eStorageImage,
                              eStorageImage},
                             POINT_SHADOW_RAY_HALF_CENTRED_CARDS_COMP, card_texel_scale,
                             colour_mode ? 1u : 0u); // bbport (r92_lamp-shadow-colour)
    } else if (half) {
        what = "half-resolution";
        made = MakeCardBuild(device, *card_set_layout, card_half_set_layout, card_half_layout,
                             card_half_pipeline,
                             {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                              eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                              eStorageImage, eStorageImage, eStorageBuffer, eStorageImage, eStorageImage},
                             POINT_SHADOW_RAY_HALF_CARDS_COMP, card_texel_scale,
                             colour_mode ? 1u : 0u); // bbport (r92_lamp-shadow-colour)
    } else if (centred) {
        what = "centred";
        made = MakeCardBuild(device, *card_set_layout, card_ray_set_layout, card_ray_layout,
                             card_ray_pipeline,
                             {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                              eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                              eStorageImage, eStorageImage, eStorageImage, eStorageImage},
                             POINT_SHADOW_RAY_CENTRED_CARDS_COMP, card_texel_scale,
                             colour_mode ? 1u : 0u); // bbport (r92_lamp-shadow-colour)
    } else {
        what = "full-resolution";
        made = MakeCardBuild(device, *card_set_layout, card_ray_set_layout, card_ray_layout,
                             card_ray_pipeline,
                             {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                              eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                              eStorageImage, eStorageImage, eStorageImage},
                             POINT_SHADOW_RAY_CARDS_COMP, card_texel_scale,
                             colour_mode ? 1u : 0u); // bbport (r92_lamp-shadow-colour)
    }
    std::printf("Ray traced lamps (r63): the %s build with cards %s\n", what,
                made ? "made" : "could not be made: that pass leaves the cards out");
}

// bbport (r63_leaf-stage4): set 1 of a CARDS build for this pass, or null (the pass binds its
// build of before): none made, the TLAS holds no card instance with CARD_LAMP_MASK, or a handle
// not there yet. A set is written once, before any pass reads it, and never again: when a handle
// changes, a new one is made (at most CardSetsMost a run, then the cards are left out, said once).
vk::DescriptorSet PointShadow::CardLampSet(bool half) {
    if (!card_set_layout || !card_counts || !(half ? card_half_pipeline : card_ray_pipeline)) {
        return {};
    }
    // This pass could trace the cards: they may take CARD_LAMP_MASK (from the next scene on). Not
    // once the sets ran out (below): the cards are left out for good then.
    if (card_set || card_sets_made < CardSetsMost) {
        rt_shadow.NoteCardLampUser();
    }
    // bbport (r62f_cutout-live-flip): TOOL (test aid; needs r84): BB_RT_CARD_LAMPS asked again at
    // every pass through the live knobs file, so that one running game shows one view with the
    // cut-out lamp shadows and without them. Only a game whose CARDS builds were made (started with
    // BB_RT_CARD_LAMPS=1 and BB_RT_CARD_ALPHA=2) gets here. While the file sets it to anything but
    // 1, the pass binds its build of before, as it does whenever the TLAS holds no card: no pipeline
    // or set is made, and the TLAS is not touched (the pass is noted above, so the cards keep
    // CARD_LAMP_MASK); the build of before traces 0x04 alone, which no card carries. The r63
    // 600-frame line counts such passes among those without cards. Without BB_LIVE_KNOBS_FILE the
    // value is the environment's 1 and nothing changes. Said once at each change.
    {
        static BbLiveKnobs::Knob<bool> lamps_live{
            "BB_RT_CARD_LAMPS",
            [](const char* text) -> bool { return text != nullptr && std::strcmp(text, "1") == 0; }};
        static bool told_on = true;
        const bool on = lamps_live.Get();
        if (on != told_on) {
            told_on = on;
            std::printf("Ray traced lamps (r62f): cut-out lamp shadows now %s (live)\n", on ? "on" : "off");
        }
        if (!on) {
            return {};
        }
    }
    const auto r = rt_shadow.CardLampReadersNow();
    if (r.instances == 0 || !r.rows || !r.pool || !r.info || !r.layers || !r.sampler) {
        return {};
    }
    if (card_set && r.rows == card_set_rows && r.pool == card_set_pool && r.info == card_set_info &&
        r.layers == card_set_layers && r.sampler == card_set_sampler) {
        return card_set;
    }
    if (card_sets_made >= CardSetsMost) {
        if (std::exchange(card_set, vk::DescriptorSet{})) {
            std::printf("Ray traced lamps (r63): the cards' bindings changed %u times: the lamp rays "
                        "leave the cards out from now on\n",
                        card_sets_made);
        }
        return {};
    }
    const auto device = instance.GetDevice();
    const vk::DescriptorSetLayout set_layout = *card_set_layout;
    auto sets = device.allocateDescriptorSets(
        {.descriptorPool = *card_pool, .descriptorSetCount = 1, .pSetLayouts = &set_layout});
    if (sets.result != vk::Result::eSuccess || sets.value.empty()) {
        card_sets_made = CardSetsMost;
        return {};
    }
    ++card_sets_made;
    const vk::DescriptorSet set = sets.value[0];
    const vk::DescriptorBufferInfo rows{r.rows, 0, VK_WHOLE_SIZE};
    const vk::DescriptorBufferInfo pool{r.pool, 0, VK_WHOLE_SIZE};
    const vk::DescriptorBufferInfo info{r.info, 0, VK_WHOLE_SIZE};
    const vk::DescriptorBufferInfo counts{card_counts->Handle(), 0, VK_WHOLE_SIZE};
    const vk::DescriptorImageInfo alpha{r.sampler, r.layers, vk::ImageLayout::eGeneral};
    using enum vk::DescriptorType;
    const std::array<vk::WriteDescriptorSet, 5> writes{{
        {.dstSet = set, .dstBinding = 0, .descriptorCount = 1, .descriptorType = eStorageBuffer,
         .pBufferInfo = &rows},
        {.dstSet = set, .dstBinding = 1, .descriptorCount = 1, .descriptorType = eStorageBuffer,
         .pBufferInfo = &pool},
        {.dstSet = set, .dstBinding = 2, .descriptorCount = 1, .descriptorType = eStorageBuffer,
         .pBufferInfo = &info},
        {.dstSet = set, .dstBinding = 3, .descriptorCount = 1, .descriptorType = eCombinedImageSampler,
         .pImageInfo = &alpha},
        {.dstSet = set, .dstBinding = 4, .descriptorCount = 1, .descriptorType = eStorageBuffer,
         .pBufferInfo = &counts},
    }};
    device.updateDescriptorSets(writes, {});
    card_set = set;
    card_set_rows = r.rows;
    card_set_pool = r.pool;
    card_set_info = r.info;
    card_set_layers = r.layers;
    card_set_sampler = r.sampler;
    return set;
}

// bbport (r62m_cutout-name-blocker) TOOL: the blocker book's lines (point_shadow_ray.comp bookAdd; rt_card_layers_layout.h): the cards
// that blocked the lamp rays of the lit and shadowed pixels, with the most pixels first, each named by RtShadow::CardBlockerOf. `now` and
// `last` are the book's words as copied (the entries, then the pixels without a slot and with the table full); the pixels and the
// distances are since the last window, the hit boxes since the start. Two lines a card, at most four cards (a slot run keeps 300
// characters of a line).
using CardBook = std::array<u32, CARD_BOOK_ENTRIES * CARD_BOOK_WORDS + 2>;
static void CardBlockerLines(const CardBook& now, CardBook& last, const RtShadow& rt, const char* tag, double both) {
    struct Row {
        u32 at;
        u32 slot;
        double px, lamp_m, went_m, game;
    };
    std::array<Row, CARD_BOOK_ENTRIES> rows{};
    u32 used = 0;
    double total = 0.0;
    for (u32 i = 0; i < CARD_BOOK_ENTRIES; ++i) {
        const u32 at = i * CARD_BOOK_WORDS;
        const u32 slot = now[at];
        if (slot == 0) {
            continue;
        }
        const bool same = last[at] == slot;
        const auto diff = [&](u32 w) { return double(u32(now[at + w] - (same ? last[at + w] : 0u))); };
        const double px = diff(1);
        if (px > 0.0) {
            rows[used++] = Row{at, slot, px, diff(8) / px / 100.0, diff(9) / px / 100.0, diff(10)};
            total += px;
        }
    }
    const u32 no_slot = now[CARD_BOOK_ENTRIES * CARD_BOOK_WORDS] - last[CARD_BOOK_ENTRIES * CARD_BOOK_WORDS];
    const u32 full = now[CARD_BOOK_ENTRIES * CARD_BOOK_WORDS + 1] - last[CARD_BOOK_ENTRIES * CARD_BOOK_WORDS + 1];
    last = now;
    if (used == 0 && no_slot == 0 && full == 0) {
        return;
    }
    std::sort(rows.begin(), rows.begin() + used, [](const Row& a, const Row& b) { return a.px > b.px; });
    std::printf("Foliage lamp shadows (r62m) blocker book %s: %u cards named, %.0f counted px of %.0f lit+shadowed (no slot %u, table full %u)\n",
                tag, used, total, both, no_slot, full);
    for (u32 n = 0; n < used && n < 4; ++n) {
        const Row& row = rows[n];
        const RtShadow::CardBlockerInfo info = rt.CardBlockerOf(row.slot);
        const char* where = row.lamp_m < 0.3 ? "lamp-side" : row.went_m < 0.1 ? "surface-side" : "between";
        if (!info.found) {
            std::printf("Foliage lamp shadows (r62m) blocker %s #%u: %.0f px (%.0f %%), game keeps %.0f %%, hit-lamp %.2f m, hit-surface %.2f m (%s), "
                        "slot %u: no entry carries it any more\n",
                        tag, n + 1, row.px, 100.0 * row.px / std::max(total, 1.0), 100.0 * row.game / row.px, row.lamp_m, row.went_m,
                        where, row.slot);
        } else {
            std::printf("Foliage lamp shadows (r62m) blocker %s #%u: %.0f px (%.0f %%), game keeps %.0f %%, hit-lamp %.2f m, hit-surface %.2f m (%s), "
                        "slot %u key %016llx ps %016llx (%s pass), %u tris %u verts, %s%s%s, size %.2f x %.2f x %.2f m\n",
                        tag, n + 1, row.px, 100.0 * row.px / std::max(total, 1.0), 100.0 * row.game / row.px, row.lamp_m, row.went_m,
                        where, row.slot, static_cast<unsigned long long>(info.key), static_cast<unsigned long long>(info.ps),
                        info.camera_pass ? "camera" : "sun", info.triangles, info.vertices, info.skinned ? "skinned" : "static",
                        info.dynamic ? " moving" : "", info.instance ? " instance" : "", double(info.box[3] - info.box[0]),
                        double(info.box[4] - info.box[1]), double(info.box[5] - info.box[2]));
        }
        const auto lo = [&](u32 a) { return 32.0 - double(now[row.at + 2 + a]) / 100.0; };
        const auto hi = [&](u32 a) { return double(now[row.at + 5 + a]) / 100.0 - 32.0; };
        std::printf("Foliage lamp shadows (r62m) blocker %s #%u where: hits right %.1f..%.1f up %.1f..%.1f ahead %.1f..%.1f m; box centre in "
                    "view %.1f %.1f %.1f; world box %.1f %.1f %.1f to %.1f %.1f %.1f (%c); rule op %u ref %.3g layer %u\n",
                    tag, n + 1, lo(0), hi(0), lo(1), hi(1), lo(2), hi(2), double(info.centre_view[0]), double(info.centre_view[1]),
                    double(info.centre_view[2]), double(info.box[0]), double(info.box[1]), double(info.box[2]), double(info.box[3]),
                    double(info.box[4]), double(info.box[5]), info.box_src, info.op, double(info.reference), info.layer);
        // bbport (r62n_cutout-skinned-blocker) TOOL: what the blocker is. The skeleton's bones, r46b's sign and the hunter (the game's physics
        // position, BbEngine::world_player_position) against the hits' centre: 'the hunter' a figure-sized rig (not lone, or over
        // BB_RT_CARD_LAMP_BONES bones) whose hits lie within 1.5 m sideways of him and from 1.5 m under to 2.5 m over his position (r112h's
        // test), 'a character' such a rig elsewhere, 'a plant' a lone skinned card with few bones, 'unknown' a card with no skeleton.
        if (n < 2 && info.found) {
            const std::array<float, 3> centre{float(0.5 * (lo(0) + hi(0))), float(0.5 * (lo(1) + hi(1))), float(0.5 * (lo(2) + hi(2)))};
            const RtShadow::HunterRel hunter = rt.HunterAgainst(centre);
            const bool on_hunter = hunter.known && CardNearHunter(hunter.horizontal_m, hunter.up_m, CardHunterNearM);
            const CardBlockerKind kind =
                CardBlockerKindOf(info.skinned, info.lone, info.bones, RtShadow::CardSkinnedBonesNow(), on_hunter);
            std::printf("Foliage lamp shadows (r62n) blocker %s #%u is %s: %.0f px, %u bones, %s, hits' centre %.1f %.1f %.1f m (view), hunter %s at "
                        "%.1f %.1f %.1f m (view), %.2f m sideways and %.2f m up of him, skinned mode %u\n",
                        tag, n + 1, CardBlockerKindText(kind), row.px, info.bones, info.lone_text, double(centre[0]), double(centre[1]),
                        double(centre[2]), hunter.known ? "read" : "unread", double(hunter.view[0]), double(hunter.view[1]),
                        double(hunter.view[2]), double(hunter.horizontal_m), double(hunter.up_m),
                        unsigned(RtShadow::CardSkinnedModeNow()));
        }
    }
}

// bbport (r62k_cutout-lit-fence): the window lines of the lit patch (point_shadow_ray.comp cardLit) and, with the proof view on, of what
// each layer rule keeps. The numbers come first (a slot run keeps 300 characters of a line) under the "Foliage" prefix its evidence list
// keeps ahead of the rest. A window ends at each change of the live knobs file (BbLiveKnobs::Generation: a test job's set: and unset:
// actions, so the line of the n-th window says what the game did before the n-th change: the capture taken in that state) and once at 240
// frames, so a short job still prints before its first picture. The counters are those the card passes copied (read as CardLampsLine
// reads them, without waiting for the GPU). Called every frame while the card passes' set layout exists (BB_RT_CARD_LAMPS=1): with the
// knob off nothing runs.
static void CardLitWindowLine(VideoCore::Buffer* readback, const RtShadow& rt) { // bbport (r62m): rt names the blockers
    static std::array<u32, CARD_LAMP_COUNTERS> last{};
    static u32 frames = 0;
    static u32 windows = 0;
    static u32 seen_generation = BbLiveKnobs::Generation();
    static bool early_done = false;
    ++frames;
    const u32 generation = BbLiveKnobs::Generation();
    const bool changed = generation != seen_generation && frames >= 20;
    const bool early = !early_done && frames >= 240;
    if (!changed && !early) {
        return;
    }
    seen_generation = generation;
    early_done = true;
    const char letter[2] = {char('a' + (windows % 26)), '\0'};
    const char* const tag = early && !changed ? "early" : letter;
    windows += early && !changed ? 0 : 1;
    std::array<u32, CARD_LAMP_COUNTERS> now{};
    if (readback && readback->mapped_data.size() >= sizeof(now)) {
        readback->Invalidate(0, sizeof(now));
        std::memcpy(now.data(), readback->mapped_data.data(), sizeof(now));
    }
    std::array<double, CARD_LAMP_COUNTERS> d{};
    for (u32 i = 0; i < CARD_LAMP_COUNTERS; ++i) {
        d[i] = double(u32(now[i] - last[i]));
    }
    last = now;
    const u32 was_frames = std::exchange(frames, 0u);
    const auto share = [](double part, double whole) { return whole > 0.0 ? 100.0 * part / whole : 0.0; };
    const double both = d[CARD_LAMP_LIT_BOTH];
    const auto mean = [&](u32 index) { return both > 0.0 ? d[index] / both : 0.0; };
    const double x = both > 0.0 ? mean(CARD_LAMP_LIT_SUM_X) / 100.0 - 32.0 : 0.0;
    const double y = both > 0.0 ? mean(CARD_LAMP_LIT_SUM_Y) / 100.0 - 32.0 : 0.0;
    const double z = mean(CARD_LAMP_LIT_SUM_Z) / 100.0;
    std::printf("Foliage lamp shadows (r62k) lit %s: %.0f px lit and under a cut-out shadow of %.0f blocked, %.0f lit, %.0f seen "
                "(%u frames); dark %.0f %%, lamp %.0f %% of light at %.1f m; centre %.1f %.1f %.1f m (right up ahead) %.0f deg, "
                "screen %.0f %.0f\n",
                tag, both, d[CARD_LAMP_LIT_BLOCKED], d[CARD_LAMP_LIT_BRIGHT], d[CARD_LAMP_LIT_PIXELS], was_frames,
                mean(CARD_LAMP_LIT_SUM_DEPTH), mean(CARD_LAMP_LIT_SUM_SHARE), mean(CARD_LAMP_LIT_SUM_DIST) / 100.0, x, y, z,
                std::atan2(x, z) * 57.29578, mean(CARD_LAMP_LIT_SUM_PX), mean(CARD_LAMP_LIT_SUM_PY));
    // bbport (r62l_cutout-steady-proof): what kind of surface the lit and shadowed pixels are, how far their blockers lie, how many
    // reads the strict zone overruled, and how many front reads the game kept itself (not false shadows: the card is drawn there)
    std::printf("Foliage lamp shadows (r62l) steady %s: %.0f px lit+shadowed, on a card %.0f %%, blocker within 10 cm %.0f %%, mean "
                "blocker %.2f m; strict drops %.0f (zone %.2f m); front reads %.0f, game-kept %.1f %%; split %u px\n",
                tag, both, share(d[CARD_LAMP_LIT_ON_CARD], both), share(d[CARD_LAMP_LIT_NEAR], both),
                both > 0.0 ? d[CARD_LAMP_LIT_SUM_WENT] / both / 100.0 : 0.0, d[CARD_LAMP_STRICT_DROPS],
                double(CardExtrasFromEnv().strict_m), d[CARD_LAMP_PROOF_FRONT_READS],
                share(d[CARD_LAMP_PROOF_FRONT_GAME_KEPT], d[CARD_LAMP_PROOF_FRONT_READS]), CardExtrasFromEnv().split);
    // bbport (r62m_cutout-name-blocker) TOOL: which cards blocked the lit and shadowed pixels
    static CardBook book_last{};
    CardBook book_now{};
    if (readback && readback->mapped_data.size() >= CARD_LAMP_BUFFER_WORDS * sizeof(u32)) {
        readback->Invalidate(CARD_LAMP_BOOK * sizeof(u32), sizeof(book_now));
        std::memcpy(book_now.data(), readback->mapped_data.data() + CARD_LAMP_BOOK * sizeof(u32), sizeof(book_now));
    }
    CardBlockerLines(book_now, book_last, rt, tag, both);
    // bbport (r62n_cutout-skinned-blocker) TOOL: the camera-ray front reads of the proof view (BB_RT_CARD_LAMP_PROOF_VIEW=1 with BB_LAMP_SHADOW_VIEW=7:
    // the cards in front of a surface the game dropped, and what each rule keeps there) and the housing skips, in one short line a window
    // that has either prints (a window without proof pixels and without skips prints none: front reads are then 0 by construction)
    if (d[CARD_LAMP_PROOF_PIXELS] > 0.0 || d[CARD_LAMP_HOUSING_SKIPS] > 0.0) {
        const double reads = d[CARD_LAMP_PROOF_FRONT_READS];
        std::printf("Foliage lamp shadows (r62n) %s: front reads %.0f (game kept %.1f %%, game alpha 0 %.1f %%, lamp rule kept %.1f %%) of %.0f proof px; "
                    "housing skips %.0f (zone %.2f m); skinned mode %u\n",
                    tag, reads, share(d[CARD_LAMP_PROOF_FRONT_GAME_KEPT], reads), share(d[CARD_LAMP_PROOF_FRONT_ZERO], reads),
                    share(d[CARD_LAMP_PROOF_FRONT_LAMP_KEPT], reads), d[CARD_LAMP_PROOF_PIXELS], d[CARD_LAMP_HOUSING_SKIPS],
                    double(CardExtrasFromEnv().housing_m), unsigned(RtShadow::CardSkinnedModeNow()));
    }
    // bbport (r62o_cutout-visible-foliage) FEATURE: the half-resolution blocks (BB_RT_CARD_LAMP_BLOCKS): a window that counted a first-pass pixel prints ONE line
    if (d[CARD_LAMP_BLK_FIRST] > 0.0) {
        const double fill = d[CARD_LAMP_BLK_TAKEN_ALL];
        std::printf("Foliage lamp shadows (r62o) %s: first-pass px %.0f, %.1f %% tested a leaf card; of %.0f second-pass px that reached the take decision "
                    "%.1f %% lie in a marked block and %.1f %% beside one; %.0f traced their own rays because of it (%.1f %%) (blocks mode %u)\n",
                    tag, d[CARD_LAMP_BLK_FIRST], share(d[CARD_LAMP_BLK_FIRST_CARD], d[CARD_LAMP_BLK_FIRST]), fill, share(d[CARD_LAMP_BLK_OWN], fill),
                    share(d[CARD_LAMP_BLK_RING], fill), d[CARD_LAMP_BLK_FORCED], share(d[CARD_LAMP_BLK_FORCED], fill), unsigned(CardExtrasFromEnv().blocks));
    }
    if (d[CARD_LAMP_PROOF_PIXELS] > 0.0) {
        const double judged = d[CARD_LAMP_PROOF_KEPT] + d[CARD_LAMP_PROOF_ZERO] + d[CARD_LAMP_PROOF_PARTIAL];
        const double front = d[CARD_LAMP_PROOF_FRONT_READS];
        const double dropped = std::max(front - d[CARD_LAMP_PROOF_FRONT_GAME_KEPT], 0.0); // bbport (r62l_cutout-steady-proof): the reads the game dropped
        std::printf("Foliage lamp shadows (r62k) proof %s: of %.0f judged card px the game keeps %.1f %%, bilinear %.1f %%, max4 "
                    "%.1f %%, nearest %.1f %%; of %.0f reads at a card in front (game dropped) bilinear keeps %.1f %%, max4 "
                    "%.1f %%, nearest %.1f %% (false shadow)\n",
                    tag, judged, share(d[CARD_LAMP_PROOF_KEPT], judged), share(d[CARD_LAMP_JUDGED_BILIN], judged),
                    share(d[CARD_LAMP_JUDGED_MAX], judged), share(d[CARD_LAMP_JUDGED_NEAR], judged), dropped,
                    share(d[CARD_LAMP_FRONT_BILIN], dropped), share(d[CARD_LAMP_FRONT_MAX], dropped),
                    share(d[CARD_LAMP_FRONT_NEAR], dropped));
    }
}

// bbport (r63_leaf-stage4): every LampLineFrames frames with BB_RT_CARD_LAMPS=1: what the passes
// with cards did. The counters are those of the counted passes (one in CardCountEvery, the rays of
// one pixel in 64), copied before each counted pass (so a line may miss the last one) and read
// here without waiting for the GPU (as r32's half counters): one line may mix two copies, so its
// shares are approximate; u32 differences survive the wrap. The mask changes: how many card
// instances changed their bit, and in how many TLAS writes (each such write is a full build; the
// r17 line's "TLAS ... built, ... refit" says how many builds there were in all).
void PointShadow::CardLampsLine() {
    if (card_set_layout) {
        CardLitWindowLine(card_readback.get(), rt_shadow); // bbport (r62k_cutout-lit-fence; r62m: rt_shadow names the blockers)
    }
    if (!card_set_layout || ++card_frames < LampLineFrames) {
        return;
    }
    std::array<u32, CARD_LAMP_COUNTERS> now{};
    if (card_readback && card_readback->mapped_data.size() >= sizeof(now)) {
        card_readback->Invalidate(0, sizeof(now));
        std::memcpy(now.data(), card_readback->mapped_data.data(), sizeof(now));
    }
    std::array<double, CARD_LAMP_COUNTERS> d{};
    for (u32 i = 0; i < CARD_LAMP_COUNTERS; ++i) {
        d[i] = double(u32(now[i] - card_last[i]));
    }
    card_last = now;
    const auto counts = rt_shadow.TakeCardLampCounts();
    const auto share = [](double part, double whole) { return whole > 0.0 ? 100.0 * part / whole : 0.0; };
    const double card_rays = d[CARD_LAMP_CARD_RAYS];
    const auto ull = [](u64 v) { return static_cast<unsigned long long>(v); };
    std::printf("Ray traced lamps (r63): %u frames: %u passes with leaf cards (%u counted), %u without "
                "(no card with data in the scene); card instances in the TLAS now %u (%u plants, %u "
                "moving props); %llu card mask changes in %llu of %llu TLAS writes (each such write "
                "a full build); counted rays %.0f, %.1f %% met a card: of those %.1f %% blocked by a "
                "leaf texel, %.1f %% blocked at the cap (%u), %.1f %% reached the lamp, %.1f %% "
                "blocked by solid geometry, %.1f %% met only cards without data; a ray that met a "
                "card read %.2f layers and passed %.2f cards without data; most layer reads by one "
                "ray since the start %u (shares approximate)\n",
                card_frames, card_line_passes, card_line_counted, card_line_plain, counts.instances,
                counts.plants, counts.moving, ull(counts.flips), ull(counts.flip_writes),
                ull(counts.writes), d[CARD_LAMP_RAYS], share(card_rays, d[CARD_LAMP_RAYS]),
                share(d[CARD_LAMP_HOW + CARD_RAY_KEPT], card_rays),
                share(d[CARD_LAMP_HOW + CARD_RAY_CAP], card_rays), CardRayCap(card_cap_bits),
                share(d[CARD_LAMP_HOW + CARD_RAY_FREE], card_rays),
                share(d[CARD_LAMP_HOW + CARD_RAY_OPAQUE], card_rays),
                share(d[CARD_LAMP_BLIND], card_rays),
                card_rays > 0.0 ? d[CARD_LAMP_TESTED] / card_rays : 0.0,
                card_rays > 0.0 ? d[CARD_LAMP_NO_DATA] / card_rays : 0.0, now[CARD_LAMP_MOST]);
    {
        // bbport (r62g_cutout-shadows-visible): what the layer reads were and what the card rays did, the
        // numbers first (a slot run keeps 300 characters of a line)
        const CardExtras extras = CardExtrasFromEnv();
        const double reads = d[CARD_LAMP_TESTED];
        const double kept_reads = std::max(reads - d[CARD_LAMP_ZERO_READS] - d[CARD_LAMP_PARTIAL_READS], 0.0);
        std::printf("Ray traced lamps (r62g): %.0f counted rays, %.1f %% blocked by a card alone, %.1f %% by solid "
                    "geometry before a card ray was cast, %.0f card rays cast (%.1f %%); of %.0f layer reads %.1f %% "
                    "at a level above 0, %.1f %% on a texel of alpha 0, %.1f %% on a partly covered texel the rule "
                    "dropped, %.1f %% kept; card disc %.3f m (BB_RT_CARD_LAMP_RADIUS, 0.5 = the lamp's own)\n",
                    d[CARD_LAMP_RAYS], share(d[CARD_LAMP_CARD_ONLY], d[CARD_LAMP_RAYS]),
                    share(d[CARD_LAMP_SOLID_FIRST], d[CARD_LAMP_RAYS]), d[CARD_LAMP_SHARP_RAYS],
                    share(d[CARD_LAMP_SHARP_RAYS], d[CARD_LAMP_RAYS]), reads, share(d[CARD_LAMP_LOD_READS], reads),
                    share(d[CARD_LAMP_ZERO_READS], reads), share(d[CARD_LAMP_PARTIAL_READS], reads),
                    share(kept_reads, reads), double(extras.disc_m));
    }
    {
        // bbport (r62h_cutout-cards-hit): the two-ray form's rays by where a card stopped them, and its reads
        // (the numbers first). Near hits (under 3 cm) are the pixel's own blade or leaf, far ones a shadow.
        const CardExtras extras = CardExtrasFromEnv();
        const double stopped = d[CARD_LAMP_KEPT_D0] + d[CARD_LAMP_KEPT_D1] + d[CARD_LAMP_KEPT_D2] +
                               d[CARD_LAMP_KEPT_D3];
        const double split_reads = d[CARD_LAMP_SPLIT_READS];
        std::printf("Ray traced lamps (r62h): of %.0f card rays cast, %.0f stopped by a card: %.1f %% within 3 cm of "
                    "the ray's start, %.1f %% 3-10 cm, %.1f %% 10-30 cm, %.1f %% farther; of %.0f layer reads of "
                    "these rays %.1f %% kept only by the reference scale %.2f, mean level %.2f (level scale %.2f); "
                    "card ray starts %.3f m from the surface at least (BB_RT_CARD_LAMP_TMIN)\n",
                    d[CARD_LAMP_SHARP_RAYS], stopped, share(d[CARD_LAMP_KEPT_D0], stopped),
                    share(d[CARD_LAMP_KEPT_D1], stopped), share(d[CARD_LAMP_KEPT_D2], stopped),
                    share(d[CARD_LAMP_KEPT_D3], stopped), split_reads, share(d[CARD_LAMP_RESCUED], split_reads),
                    double(extras.ref_scale), split_reads > 0.0 ? d[CARD_LAMP_LOD16] / 16.0 / split_reads : 0.0,
                    double(extras.level_scale), double(extras.tmin_m));
    }
    if (CardExtrasFromEnv().proof_view != 0) {
        // bbport (r62i_cutout-uv-proof): the proof view's numbers (cardProof; view 7 must be on, else all 0): of the
        // screen pixels read, the card pixels by what the layer said at the camera ray's hit. On a pixel the game kept,
        // 'kept' must be near 100 % if the chain is right.
        const double pixels = d[CARD_LAMP_PROOF_PIXELS];
        const double cards = pixels - d[CARD_LAMP_PROOF_NO_CARD];
        const double judged = d[CARD_LAMP_PROOF_KEPT] + d[CARD_LAMP_PROOF_ZERO] + d[CARD_LAMP_PROOF_PARTIAL];
        std::printf("Ray traced lamps (r62i): proof of %.0f screen pixels, %.0f card pixels (%.1f %% of them no data, "
                    "%.1f %% not judged); of %.0f judged card pixels: %.1f %% kept at level 0, %.1f %% dropped on alpha "
                    "0, %.1f %% dropped on a partly covered texel, %.1f %% kept at level 1; %.1f %% of the card pixels "
                    "have coordinates outside 0-1 (BB_RT_CARD_LAMP_PROOF_VIEW, view 7)\n",
                    pixels, cards, share(d[CARD_LAMP_PROOF_NO_DATA], cards), share(d[CARD_LAMP_PROOF_UNJUDGED], cards),
                    judged, share(d[CARD_LAMP_PROOF_KEPT], judged), share(d[CARD_LAMP_PROOF_ZERO], judged),
                    share(d[CARD_LAMP_PROOF_PARTIAL], judged), share(d[CARD_LAMP_PROOF_KEPT_L1], judged),
                    share(d[CARD_LAMP_PROOF_UV_OUTSIDE], cards));
        // bbport (r62j_cutout-rule-and-place): the two-sided proof of the rule (shares of the judged card pixels, then of the
        // outside-0-1 pixels, then of the reads at cards in front of the surface, which the game dropped)
        const double out_judged = d[CARD_LAMP_PROOF_OUT_JUDGED];
        const double front = d[CARD_LAMP_PROOF_FRONT_READS];
        const CardExtras rule = CardExtrasFromEnv();
        std::printf("Ray traced lamps (r62j): of %.0f judged card pixels the lamp rule (reference x%.2f, 2x2 maximum %u, "
                    "wrap %u) keeps %.1f %% (the game's rule %.1f %%); of them the game dropped on a partly covered texel "
                    "by texel alpha over the reference: %.1f %% under 0.25, %.1f %% 0.25-0.5, %.1f %% 0.5-1; of %.0f pixels "
                    "with coordinates outside 0-1 the row's mode keeps %.1f %%, a wrap would keep %.1f %%; of %.0f reads at a "
                    "card in front of the surface (the game dropped them): %.1f %% on alpha 0, the game's rule keeps %.1f %% "
                    "(a chain fault if not 0), the lamp rule keeps %.1f %% (false shadow)\n",
                    judged, double(rule.ref_scale), rule.gather, rule.wrap_clamped, share(d[CARD_LAMP_PROOF_LAMP_KEPT], judged),
                    share(d[CARD_LAMP_PROOF_KEPT], judged), share(d[CARD_LAMP_PROOF_BIN1], judged),
                    share(d[CARD_LAMP_PROOF_BIN2], judged), share(d[CARD_LAMP_PROOF_BIN3], judged), out_judged,
                    share(d[CARD_LAMP_PROOF_OUT_KEPT], out_judged), share(d[CARD_LAMP_PROOF_OUT_WRAP_KEPT], out_judged), front,
                    share(d[CARD_LAMP_PROOF_FRONT_ZERO], front), share(d[CARD_LAMP_PROOF_FRONT_GAME_KEPT], front),
                    share(d[CARD_LAMP_PROOF_FRONT_LAMP_KEPT], front));
    }
    card_frames = 0;
    card_line_passes = 0;
    card_line_counted = 0;
    card_line_plain = 0;
}

bool PointShadow::RaysWanted() const {
    return rt_shadow.Wanted() &&
           BbSettings::Get().graphics_rt_point_shadows.load(std::memory_order_relaxed);
}

bool PointShadow::BeginApart(u32 width, u32 height) {
    if (!rt_shadow.PrepareScene()) {
        return false;
    }
    const bool have = lamp[0].image && lamp[0].width == width && lamp[0].height == height;
    const bool have_history =
        history[0].image && history[0].width == width && history[0].height == height;
    const u64 pixels = u64(width) * height;
    // bbport (r52_follow-soft): the history's 8 bytes a pixel and the follow state's 4, twice
    const u64 needed = (have ? 0 : 2 * 4 * pixels) + (have_history ? 0 : 2 * (8 + 4) * pixels);
    if (needed && !EffectPass::HasRoom(instance, needed)) {
        return false;
    }
    for (auto& own : lamp) {
        if (EnsureImage(own, width, height, TargetFormat, "Ray traced lamp light",
                        vk::ImageUsageFlagBits::eColorAttachment)) {
            lamp_dirty = true;
            lamp_laid_out = false;
        }
    }
    if (lamp_dirty) {
        // New images, or a batch that ended without its pass (the pass zeroes what it reads).
        const auto old_layout =
            lamp_laid_out ? vk::ImageLayout::eGeneral : vk::ImageLayout::eUndefined;
        lamp_laid_out = true;
        scheduler.RecordCrumb(
            {.name = "Ray traced lamp light clear"},
            [images = std::array{vk::Image(lamp[0].image), vk::Image(lamp[1].image)},
             old_layout](vk::CommandBuffer cmdbuf) {
                std::array<vk::ImageMemoryBarrier2, 2> barriers;
                for (int i = 0; i < 2; ++i) {
                    barriers[i] = {
                        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                        .srcAccessMask = vk::AccessFlagBits2::eMemoryRead |
                                         vk::AccessFlagBits2::eMemoryWrite,
                        .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                        .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
                        .oldLayout = old_layout,
                        .newLayout = vk::ImageLayout::eGeneral,
                        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .image = images[i],
                        .subresourceRange = ColorRange,
                    };
                }
                cmdbuf.pipelineBarrier2(
                    {.imageMemoryBarrierCount = 2, .pImageMemoryBarriers = barriers.data()});
                const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
                for (const vk::Image image : images) {
                    cmdbuf.clearColorImage(image, vk::ImageLayout::eGeneral, zero, ColorRange);
                }
                const vk::MemoryBarrier2 after{
                    .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
                    .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .dstAccessMask = vk::AccessFlagBits2::eMemoryRead |
                                     vk::AccessFlagBits2::eMemoryWrite};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
            });
    }
    lamp_dirty = true; // until the batch's pass has moved the light out
    return true;
}

bool PointShadow::EnsureImage(OwnImage& own, u32 width, u32 height, vk::Format format,
                              const char* name, vk::ImageUsageFlags more_usage) {
    if (own.image && own.width == width && own.height == height) {
        return false;
    }
    if (own.image) {
        scheduler.DeferOperation(
            [image = std::move(own.image), view = std::move(own.view)]() mutable {
                view.reset();
                image.Destroy();
            });
    }
    const auto device = instance.GetDevice();
    own.image = VideoCore::UniqueImage(device, instance.GetAllocator());
    own.image.Create(vk::ImageCreateInfo{
        .imageType = vk::ImageType::e2D,
        .format = format,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eTransferDst |
                 more_usage,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    SetObjectName(device, vk::Image(own.image), name);
    own.view = Check<"create point shadow snapshot view">(device.createImageViewUnique({
        .image = vk::Image(own.image),
        .viewType = vk::ImageViewType::e2D,
        .format = format,
        .subresourceRange = ColorRange,
    }));
    own.width = width;
    own.height = height;
    return true;
}

void PointShadow::OnFrameEnd() {
    // bbport (r42_lamp-soft): this frame's lamps are "the frame before" of the next one when
    // its pass left an averaged history
    track.End(history_written && history_blend && track_frame == frame_index);
    ++lamp_line_frames;
    ++frame_index;
    if (history_written) {
        history_index ^= 1u;
        last_view = pending_view;
        last_proj = pending_proj;
        last_valid = pending_valid;
        history_fresh = true;
        history_blended = history_blend; // bbport (r42_lamp-soft)
    } else {
        history_fresh = false;
    }
    history_written = false;
    if (batches != 0 && (!reported || frame_index % 1800 == 0)) {
        reported = true;
        std::printf("Point shadows: %u light tiles in %u batches this frame; %u draws between tiles "
                    "kept the batch, %u ended it (%08llx %08llx %08llx %08llx); snapshots: %u "
                    "copies, %.1f MB%s",
                    frame_tiles, batches, kept_draws, ended_by_draws,
                    (unsigned long long)ending_hashes[0], (unsigned long long)ending_hashes[1],
                    (unsigned long long)ending_hashes[2], (unsigned long long)ending_hashes[3],
                    snapshot_copies, double(snapshot_pixels) * 4.0 / (1024.0 * 1024.0),
                    tile_snapshots ? " (by tile, BB_RT_LAMP_SNAPSHOT)" : "");
        if (tile_snapshots) {
            std::printf("; %u of the %u ending draws with a known place drew away from the "
                        "batch's cells",
                        ended_apart, ended_placed);
        }
        if (apart_draws) {
            std::printf("; lamps apart: %u draws in %u passes, %u adding draws kept a batch, %u "
                        "batches ended by a compute pass (BB_RT_LAMP_APART)",
                        apart_draws, apart_passes, kept_adding, dispatch_flushes);
        }
        std::printf("\n");
    }
    // bbport (r32_lamp-half): every 600 frames, what the two passes did: means per counted
    // pass (one in 8; u32 differences survive the wrap; read while the GPU may still copy a later
    // pass's counters, which then fall in the next line). half_readback: made by HalfReady
    // (bbport r37_menu-options), the first time a pass wants the half resolution (bbport
    // r65_lamp-half-at-start: or at start, by Ready; the line still waits for the first pass that
    // asks for it, half_asked, as before).
    if (half_made && half_asked && half_readback && ++half_frames >= 600) {
        std::array<u32, HalfSlots> now{};
        half_readback->Invalidate(0, sizeof(now));
        std::memcpy(now.data(), half_readback->mapped_data.data(), sizeof(now));
        const u32 counted = now[0] - half_last[0];
        std::array<double, HalfSlots> d{};
        for (u32 i = 0; i < HalfSlots && counted != 0; ++i) {
            d[i] = double(u32(now[i] - half_last[i])) / double(counted);
        }
        half_last = now;
        std::printf("Ray traced lamps (r32): %u frames: %u passes at half resolution, %u at full "
                    "resolution (experiment 72057594037927936 set); a counted pass (mean of %u): "
                    "first pass (pixel 2x,2y of each block) %.0f pixels traced with %.0f rays, "
                    "%.0f from history; second pass (the other three) %.0f pixels took the "
                    "block's answer, %.0f traced at full resolution with %.0f rays (%.0f a block "
                    "near them had no answer, %.0f the answers differed, %.0f another surface), "
                    "%.0f from history; second-pass workgroups with no ray %.0f of %.0f",
                    half_frames, half_line_passes, half_line_full, counted, d[1], d[2], d[3],
                    d[4], d[5], d[6], d[10], d[11], d[12], d[7], d[9], d[8]);
        // bbport (r44_half-area-lamp): whether the passes had the area lamp, and what share of
        // its pixels the second pass traced (the first pass always traces a quarter of the
        // screen: this share is what the half resolution saves or does not).
        const double second = d[4] + d[5] + d[7];
        std::printf("; r44: %u of the half-resolution passes averaged area lamps over the frames "
                    "(the others had point lamps: experiment 2305843009213693952 or "
                    "35184372088832 set, graphics_lamp_shadow_softness=sharp or "
                    "BB_LAMP_SHADOW_SOFT=0, BB_LAMP_SHADOW_HISTORY=0, not the "
                    "pass that takes the history, or a history that could not be read for 8 "
                    "frames), the second pass traced %.1f%% of its pixels\n",
                    half_line_soft, second > 0.0 ? 100.0 * d[5] / second : 0.0);
        LampMovingEdgeLine(d[14], d[5]); // bbport (r101_lamp-moving-edge): only with the knob on
        LampYoungHalfLine(d[13] * counted, half_line_passes, half_frames, d[15] * counted); // bbport (r103_lamp-young-pixels; r103b: d[15])
        half_frames = 0;
        half_line_passes = 0;
        half_line_full = 0;
        half_line_soft = 0;
    }
    CardLampsLine(); // bbport (r63_leaf-stage4)
    dispatch_flushes = 0;
    if ((unended || lost_passes || flushed_in_draw > 60) && frame_index % 300 == 0) {
        // Each of the first two is a frame without (part of) its lamp light.
        static u32 lines = 0;
        if (lines < 20) {
            ++lines;
            std::printf("Lamps apart: since the last line %u batches were still open at the end "
                        "of a frame and %u passes could not run (their lamp light is lost); %u "
                        "batches were ended by a lamp draw\n",
                        unended, lost_passes, flushed_in_draw);
        }
        unended = lost_passes = flushed_in_draw = 0;
    }
    apart_last_frame = apart_draws != 0;
    apart_passes = 0;
    apart_draws = 0;
    kept_adding = 0;
    ended_placed = 0;
    static const bool trace_wanted = [] {
        const char* env = std::getenv("BB_RT_LAMP_TRACE");
        return env && env[0] == '1';
    }();
    trace_left = 0;
    if (trace_wanted && !traced && batches > 100) {
        traced = true;
        trace_left = 90; // of the next frame
    }
    ended_apart = 0;
    snapshot_copies = 0;
    snapshot_pixels = 0;
    batches = 0;
    frame_tiles = 0;
    kept_draws = 0;
    ended_by_draws = 0;
    ending_hashes = {};
}

std::array<VAddr, 2> PointShadow::PendingAddresses() const {
    std::array<VAddr, 2> out{};
    for (int i = 0; i < 2; ++i) {
        if (pending[i]) {
            if (const auto* image = texture_cache.TryGetImage(pending[i], pending_uid[i])) {
                out[i] = image->info.guest_address;
            }
        }
    }
    return out;
}

void PointShadow::Ended(u64 hash) {
    if (tiles.empty()) {
        return;
    }
    ++ended_by_draws;
    ending_uncounted = tile_snapshots;
    ending_hash = hash;
    for (u64& slot : ending_hashes) {
        if (slot == hash) {
            return;
        }
        if (slot == 0) {
            slot = hash;
            return;
        }
    }
}

void PointShadow::EndingDraw(const vk::Rect2D& area) {
    // The cells are those of the batch that ended: they stay until the next batch begins.
    ending_uncounted = false;
    const s32 width = s32(snapshot[0].width), height = s32(snapshot[0].height);
    const s32 x0 = std::clamp(area.offset.x, 0, width);
    const s32 y0 = std::clamp(area.offset.y, 0, height);
    const s32 x1 = std::clamp(area.offset.x + s32(area.extent.width), x0, width);
    const s32 y1 = std::clamp(area.offset.y + s32(area.extent.height), y0, height);
    if (snapshot_cells.empty() || snapshot_cells_wide != (u32(width) + SnapshotCell - 1) / SnapshotCell) {
        return;
    }
    bool apart = true;
    for (u32 cy = u32(y0) / SnapshotCell; apart && cy * SnapshotCell < u32(y1); ++cy) {
        for (u32 cx = u32(x0) / SnapshotCell; apart && cx * SnapshotCell < u32(x1); ++cx) {
            const u32 index = cy * snapshot_cells_wide + cx;
            apart = index >> 6 < snapshot_cells.size() &&
                    !(snapshot_cells[index >> 6] & (1ull << (index & 63)));
        }
    }
    ++ended_placed;
    ended_apart += apart;
    if (trace_left) {
        --trace_left;
        std::printf("Lamp trace: batch ended by ps %08llx at %d,%d %dx%d, %s\n",
                    (unsigned long long)ending_hash, x0, y0, x1 - x0, y1 - y0,
                    apart ? "away from the batch's cells" : "over the batch's cells");
    }
}

void PointShadow::Drop() {
    ending_uncounted = false;
    apart = false; // its lamp light is lost; the lamp images are cleared before their next use
    redirect_draw = false;
    tiles.clear();
    pending[0] = pending[1] = {};
    merged = false;
    history_fresh = false;
}

// bbport (r71_lamp-target-log): a light draw is skipped because its targets do not fit. One line
// for each new combination (at most TargetMismatchKinds), and at most once per 600 frames (at a
// skipped draw, the first 600 frames after the first skip) the draws per combination. Only reached
// on that skip path.
void PointShadow::LogTargetMismatch(const std::array<VideoCore::Image*, 2>& targets,
                                    const std::array<u32, 2>& misfit, bool reduced,
                                    const Inputs& inputs) {
    ++target_mismatches;
    TargetMismatch kind{.ps_hash = inputs.ps_hash,
                        .mrt_mask = inputs.mrt_mask,
                        .adds_in_tile = inputs.adds_in_tile,
                        .reduced = reduced};
    for (int i = 0; i < 2; ++i) {
        const auto& info = targets[i]->info;
        kind.format[i] = static_cast<u32>(info.pixel_format);
        kind.usage[i] = static_cast<u32>(static_cast<VkImageUsageFlags>(targets[i]->usage_flags));
        kind.width[i] = info.size.width;
        kind.height[i] = info.size.height;
        kind.misfit[i] = misfit[i];
        kind.address[i] = info.guest_address;
    }
    u32 k = 0;
    while (k < mismatch_kind_count && !(mismatch_kinds[k] == kind)) {
        ++k;
    }
    if (k < mismatch_kind_count) {
        ++mismatch_kind_draws[k];
        mismatch_kind_frame[k] = frame_index;
    } else if (k < TargetMismatchKinds) {
        mismatch_kinds[k] = kind;
        mismatch_kind_draws[k] = 1;
        mismatch_kind_frame[k] = frame_index;
        ++mismatch_kind_count;
        std::printf("Point shadows (r71): light targets do not fit, combination #%u at frame %u: "
                    "target 0 format %u usage %08x %ux%u at %#llx misfit %x; target 1 format %u "
                    "usage %08x %ux%u at %#llx misfit %x; wanted format %d; pixel shader "
                    "%016llx, mrt mask %x, adds in tile %d, reduced path %d; this light draw is "
                    "skipped, %llu so far\n",
                    k, frame_index, kind.format[0], kind.usage[0], kind.width[0], kind.height[0],
                    static_cast<unsigned long long>(kind.address[0]), kind.misfit[0],
                    kind.format[1], kind.usage[1], kind.width[1], kind.height[1],
                    static_cast<unsigned long long>(kind.address[1]), kind.misfit[1],
                    static_cast<int>(TargetFormat), static_cast<unsigned long long>(kind.ps_hash),
                    kind.mrt_mask, kind.adds_in_tile ? 1 : 0, reduced ? 1 : 0,
                    static_cast<unsigned long long>(target_mismatches));
    } else if (mismatch_unlisted++ == 0) {
        std::printf("Point shadows (r71): more than %u light target combinations; further new "
                    "ones are counted, not logged\n",
                    TargetMismatchKinds);
    }
    // review fix: at most one line per 600 frames, not one per 600 skipped draws (a frame can skip
    // several hundred light tiles: that was about one line a frame, as with r68)
    if (target_mismatches == 1) {
        mismatch_line_frame = frame_index;
    } else if (frame_index - mismatch_line_frame >= 600) {
        mismatch_line_frame = frame_index;
        char line[1024];
        int at = std::snprintf(line, sizeof(line),
                               "Point shadows (r71): %llu light draws skipped so far at frame %u; "
                               "draws (last frame) by combination:",
                               static_cast<unsigned long long>(target_mismatches), frame_index);
        for (u32 j = 0; j < mismatch_kind_count && at > 0 && at < int(sizeof(line)); ++j) {
            at += std::snprintf(line + at, sizeof(line) - at, " #%u %llu (%u)", j,
                                static_cast<unsigned long long>(mismatch_kind_draws[j]),
                                mismatch_kind_frame[j]);
        }
        std::printf("%s; not listed %llu\n", line,
                    static_cast<unsigned long long>(mismatch_unlisted));
    }
}

void PointShadow::OnLightDraw(VideoCore::ImageId color0, VideoCore::ImageId color1,
                              const Inputs& inputs) {
    ending_uncounted = false;
    redirect_draw = false;
    if (failed || !color0 || !color1 || !inputs.constants || !inputs.lights || inputs.count == 0 ||
        (!BbSettings::Get().effects[BbSettings::EffectPointShadows].load(
             std::memory_order_relaxed) &&
         !RaysWanted()) ||
        !Ready()) {
        return;
    }
    const auto depth_id = camera_motion.Depth();
    if (!depth_id) {
        return;
    }
    const bool reduced = scene_targets.Reduced() &&
                         scene_targets.Eligible(texture_cache.GetImage(depth_id));
    const std::array ids{color0, color1};
    const std::array<VideoCore::Image*, 2> targets{&texture_cache.GetImage(ids[0]),
                                                   &texture_cache.GetImage(ids[1])};
    // bbport (r71_lamp-target-log): the fit of both targets first (the bits are LogTargetMismatch's
    // misfit bits). Light draws used to stop at the first target that did not fit, so the second
    // was never looked at.
    std::array<u32, 2> misfit{};
    for (int i = 0; i < 2; ++i) {
        const auto& info = targets[i]->info;
        const auto usage = targets[i]->usage_flags;
        u32 bits = info.pixel_format != TargetFormat ? 1u : 0u;
        if (!reduced) {
            bits |= !(usage & vk::ImageUsageFlagBits::eStorage) ? 2u : 0u;
            bits |= !(usage & vk::ImageUsageFlagBits::eTransferSrc) ? 4u : 0u;
        } else if (!scene_targets.Eligible(*targets[i])) {
            bits |= 8u;
        }
        if (info.size.width != targets[0]->info.size.width ||
            info.size.height != targets[0]->info.size.height) {
            bits |= 16u;
        }
        misfit[i] = bits;
    }
    if ((misfit[0] | misfit[1]) != 0) [[unlikely]] {
        // bbport (r68_lamp-target-mismatch): this used to switch the pass off for the whole
        // session. Only this light draw is skipped now (the game's own draw goes ahead) and
        // the next one is tried again; r71 says what did not fit.
        LogTargetMismatch(targets, misfit, reduced, inputs);
        return;
    }
    u32 width = targets[0]->info.size.width, height = targets[0]->info.size.height;
    if (reduced) {
        const auto size = scene_targets.ProxySize(*targets[0]);
        width = size.width;
        height = size.height;
    }
    const s32 x0 = std::clamp(inputs.tile.offset.x, 0, s32(width));
    const s32 y0 = std::clamp(inputs.tile.offset.y, 0, s32(height));
    const s32 x1 = std::clamp(inputs.tile.offset.x + s32(inputs.tile.extent.width), x0, s32(width));
    const s32 y1 = std::clamp(inputs.tile.offset.y + s32(inputs.tile.extent.height), y0, s32(height));
    if (x0 == x1 || y0 == y1) {
        return;
    }
    const std::array<s32, 4> rect{x0, y0, x1, y1};
    if (trace_left) {
        --trace_left;
        std::printf("Lamp trace: lamp draw, %u lights at %d,%d %dx%d, %zu tiles pending\n",
                    inputs.count, x0, y0, x1 - x0, y1 - y0, tiles.size());
    }
    const u32 words = inputs.count * LightWords;
    const auto add_lights = [&] {
        data.insert(data.end(), inputs.lights, inputs.lights + words);
        ++frame_tiles;
        redirect_draw = apart;
        apart_draws += apart;
    };
    static const bool apart_on = [] {
        const char* env = std::getenv("BB_RT_LAMP_APART");
        return !env || env[0] != '0';
    }();
    // A light that takes light away cannot be drawn apart: the lamp images hold nothing below
    // zero, where the light target would have been lowered.
    const auto darkens = [&] {
        for (u32 k = 0; k < inputs.count; ++k) {
            for (u32 c = 4; c < 7; ++c) {
                if (std::bit_cast<float>(inputs.lights[k * LightWords + c]) < 0.0f) {
                    return true;
                }
            }
        }
        return false;
    };
    // Whether this draw can go into a batch that keeps the lamps' light apart.
    const bool can_apart = apart_on && inputs.adds_in_tile && lamp_format && ray_pipeline &&
                           RaysWanted() && inputs.pass.width == width &&
                           inputs.pass.height == height && apart_refused != frame_index &&
                           !BbToggle::Experiment(128) && !darkens();
    if (!tiles.empty()) {
        const bool same_targets = pending[0] == color0 && pending[1] == color1 &&
                                  pending_uid[0] == targets[0]->image_uid &&
                                  pending_uid[1] == targets[1]->image_uid;
        // (An apart batch's pass always has the history words after the tiles.)
        const bool room = data.size() + words + TileWords * (tiles.size() + 1) +
                              (apart || merged ? HistoryWords + LampTuneWordCount : 0) <=
                          DataWords; // bbport (r41_lamp-shadows): and the tuning words
        const OwnImage& before = apart ? lamp[0] : snapshot[0];
        const bool same_size = before.width == width && before.height == height;
        if (same_targets && same_size && apart == can_apart && (merged || !one_tile_batches) &&
            room) {
            if (tiles.back().rect == rect) {
                tiles.back().count += inputs.count;
                add_lights();
                return;
            }
            if (merged ||
                std::ranges::none_of(tiles, [&](const Tile& t) { return Overlaps(t.rect, rect); })) {
                if (tile_snapshots) {
                    // Before this tile's lamps are drawn: the cells no earlier tile of the batch
                    // took still hold what they held when the batch began. Each copy ends the
                    // render pass and three of them cost more than one copy of the whole image
                    // (about 5 against 15 microseconds of GPU time), so a batch's third copy
                    // takes every cell left: a long batch then stays in one pass, as before.
                    const std::array<s32, 4> whole{0, 0, s32(width), s32(height)};
                    auto regions =
                        TakeSnapshotCells(batch_copies >= 2 ? whole : rect, width, height);
                    if (!regions.empty()) {
                        ++batch_copies;
                        if (!CopySnapshot(ids, targets, reduced, std::move(regions), true)) {
                            Drop();
                            return;
                        }
                    }
                }
                tiles.push_back({rect, u32(data.size()), inputs.count});
                add_lights();
                return;
            }
        }
        // This draw's render state is computed already (Rasterizer::BeginRendering), with the
        // layouts its attachments had then: the pass leaves the light targets and the depth
        // readable by compute, so they go back to what the draw expects.
        auto* depth_image = texture_cache.TryGetImage(depth_id, 0);
        const auto depth_layout =
            depth_image ? depth_image->backing->state.layout : vk::ImageLayout::eUndefined;
        flushed_in_draw += apart;
        Flush(false);
        if (failed) {
            return;
        }
        // (A batch with snapshots puts the light targets back itself: CopySnapshot.)
        if (reduced) {
            VideoCore::ImageViewInfo target_info, depth_info;
            target_info.format = TargetFormat;
            if (can_apart) {
                scene_targets.Attachment(ids[0], target_info);
                scene_targets.Attachment(ids[1], target_info);
            }
            if (depth_image) {
                depth_info.format = depth_image->info.pixel_format;
                scene_targets.Attachment(depth_id, depth_info);
            }
        } else {
            for (auto* target : targets) {
                if (!can_apart) {
                    break;
                }
                runtime.Transit(target, vk::ImageLayout::eColorAttachmentOptimal,
                                vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                                vk::AccessFlagBits2::eColorAttachmentWrite |
                                    vk::AccessFlagBits2::eColorAttachmentRead);
            }
            if (depth_image && depth_layout != vk::ImageLayout::eUndefined &&
                depth_image->backing->state.layout != depth_layout) {
                runtime.Transit(depth_image, depth_layout,
                                vk::PipelineStageFlagBits2::eEarlyFragmentTests |
                                    vk::PipelineStageFlagBits2::eLateFragmentTests,
                                vk::AccessFlagBits2::eDepthStencilAttachmentRead |
                                    vk::AccessFlagBits2::eDepthStencilAttachmentWrite);
            }
            runtime.FlushBarriers();
        }
    }
    static bool printed = false;
    if (!printed) {
        printed = true;
        std::printf("Point shadows: %ux%u, length %.2f m, thickness %.2f m, strength %.2f, "
                    "%u steps, first tile %dx%d\n",
                    width, height, length_m, thickness_m, strength, steps, x1 - x0, y1 - y0);
    }

    scheduler.EndRendering();
    merged = ray_pipeline && RaysWanted();
    apart = can_apart && BeginApart(width, height);
    if (can_apart && !apart) {
        apart_refused = frame_index; // not asked again this frame: the batches stay as they are
    }
    tile_snapshots = false;
    if (!apart) {
        if ((!snapshot[0].image || snapshot[0].width != width || snapshot[0].height != height) &&
            !EffectPass::HasRoom(instance, 2ull * 4 * width * height)) {
            failed = true;
            std::printf("Point shadows: off - not enough video memory\n");
            return;
        }
        for (auto& own : snapshot) {
            if (EnsureImage(own, width, height, TargetFormat, "Point shadow snapshot")) {
                snapshot_laid_out = false;
            }
        }
    }
    one_tile_batches = ++batches > WholeImageBatches;
    static const bool by_tile = [] {
        const char* env = std::getenv("BB_RT_LAMP_SNAPSHOT");
        return !env || env[0] != '0';
    }();
    tile_snapshots = !apart && merged && by_tile && !BbToggle::Experiment(64);
    std::vector<vk::ImageCopy> regions;
    if (apart) {
        // No snapshot: the lamps' light is drawn apart.
    } else if (tile_snapshots) {
        snapshot_cells_wide = (width + SnapshotCell - 1) / SnapshotCell;
        const u32 cells = snapshot_cells_wide * ((height + SnapshotCell - 1) / SnapshotCell);
        snapshot_cells.assign((cells + 63) / 64, 0);
        batch_copies = 1;
        regions = TakeSnapshotCells(rect, width, height);
    } else {
        const std::array<s32, 4> copied = one_tile_batches && !merged
                                              ? rect
                                              : std::array<s32, 4>{0, 0, s32(width), s32(height)};
        regions.push_back({.srcSubresource = ColorLayers,
                           .srcOffset = {copied[0], copied[1], 0},
                           .dstSubresource = ColorLayers,
                           .dstOffset = {copied[0], copied[1], 0},
                           .extent = {u32(copied[2] - copied[0]), u32(copied[3] - copied[1]), 1}});
    }
    if (!apart && !CopySnapshot(ids, targets, reduced, std::move(regions), tile_snapshots)) {
        return;
    }

    pending[0] = color0;
    pending[1] = color1;
    pending_uid = {targets[0]->image_uid, targets[1]->image_uid};
    data.assign(inputs.constants, inputs.constants + ConstantWords);
    tiles.push_back({rect, u32(data.size()), inputs.count});
    add_lights();
}

std::vector<vk::ImageCopy> PointShadow::TakeSnapshotCells(const std::array<s32, 4>& rect, u32 width,
                                                          u32 height) {
    std::vector<vk::ImageCopy> regions;
    const u32 cx0 = u32(rect[0]) / SnapshotCell, cy0 = u32(rect[1]) / SnapshotCell;
    const u32 cx1 = (u32(rect[2]) + SnapshotCell - 1) / SnapshotCell;
    const u32 cy1 = (u32(rect[3]) + SnapshotCell - 1) / SnapshotCell;
    // Whether the cell was taken already; it is now.
    const auto take = [&](u32 cx, u32 cy) {
        const u32 index = cy * snapshot_cells_wide + cx;
        u64& word = snapshot_cells[index >> 6];
        const u64 mask = 1ull << (index & 63);
        const bool taken = (word & mask) != 0;
        word |= mask;
        return taken;
    };
    // open: the regions that end at the row of cells being walked, so that a run over the same
    // columns makes one of them taller instead of starting another.
    auto& open = cell_rows[0];
    auto& next = cell_rows[1];
    open.clear();
    for (u32 cy = cy0; cy < cy1; ++cy) {
        next.clear();
        const s32 y = s32(cy * SnapshotCell);
        const u32 h = std::min((cy + 1) * SnapshotCell, height) - cy * SnapshotCell;
        for (u32 cx = cx0; cx < cx1; ++cx) {
            if (take(cx, cy)) {
                continue;
            }
            u32 end = cx + 1;
            while (end < cx1 && !take(end, cy)) {
                ++end;
            }
            const s32 x = s32(cx * SnapshotCell);
            const u32 w = std::min(end * SnapshotCell, width) - cx * SnapshotCell;
            const auto same = std::ranges::find_if(open, [&](u32 i) {
                return regions[i].srcOffset.x == x && regions[i].extent.width == w;
            });
            if (same != open.end()) {
                regions[*same].extent.height += h;
                next.push_back(*same);
            } else {
                next.push_back(u32(regions.size()));
                regions.push_back({.srcSubresource = ColorLayers,
                                   .srcOffset = {x, y, 0},
                                   .dstSubresource = ColorLayers,
                                   .dstOffset = {x, y, 0},
                                   .extent = {w, h, 1}});
            }
            cx = end; // the cell at `end` is taken, or past the tile
        }
        std::swap(open, next);
    }
    return regions;
}

bool PointShadow::CopySnapshot(const std::array<VideoCore::ImageId, 2>& ids,
                               const std::array<VideoCore::Image*, 2>& targets, bool reduced,
                               std::vector<vk::ImageCopy> regions, bool keep) {
    scheduler.EndRendering();
    VideoCore::ImageViewInfo target_info;
    target_info.format = TargetFormat;
    std::array<vk::Image, 2> src{};
    vk::ImageLayout src_layout = vk::ImageLayout::eTransferSrcOptimal;
    if (reduced) {
        src_layout = vk::ImageLayout::eGeneral;
        for (int i = 0; i < 2; ++i) {
            const auto proxy = scene_targets.Read(ids[i], target_info, vk::PipelineStageFlagBits2::eCopy,
                                                  vk::AccessFlagBits2::eTransferRead);
            if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage) ||
                !(proxy.usage & vk::ImageUsageFlagBits::eTransferSrc)) {
                failed = true;
                scene_targets.Attachment(ids[0], target_info);
                scene_targets.Attachment(ids[1], target_info);
                std::printf("Point shadows: the reduced light targets cannot be used; off\n");
                return false;
            }
            src[i] = proxy.image;
        }
    } else {
        for (auto* target : targets) {
            runtime.Transit(target, vk::ImageLayout::eTransferSrcOptimal,
                            vk::PipelineStageFlagBits2::eCopy, vk::AccessFlagBits2::eTransferRead);
        }
        runtime.FlushBarriers();
        src = {targets[0]->GetImage(), targets[1]->GetImage()};
    }
    const std::array<vk::Image, 2> dst{vk::Image(snapshot[0].image),
                                       vk::Image(snapshot[1].image)};
    // Undefined lets the driver drop what the snapshots hold.
    const auto old_layout =
        keep && snapshot_laid_out ? vk::ImageLayout::eGeneral : vk::ImageLayout::eUndefined;
    snapshot_laid_out = true;
    ++snapshot_copies;
    for (const auto& region : regions) {
        snapshot_pixels += 2ull * region.extent.width * region.extent.height;
    }
    EffectPass::Mark(5, "point shadow snapshots");
    scheduler.RecordCrumb({.name = "Point shadows snapshot"},
                          [src, dst, regions = std::move(regions), src_layout,
                           old_layout](vk::CommandBuffer cmdbuf) {
        std::array<vk::ImageMemoryBarrier2, 2> to_dst;
        for (int i = 0; i < 2; ++i) {
            to_dst[i] = {
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead |
                                 vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = vk::PipelineStageFlagBits2::eCopy,
                .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
                .oldLayout = old_layout,
                .newLayout = vk::ImageLayout::eTransferDstOptimal,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = dst[i],
                .subresourceRange = ColorRange,
            };
        }
        cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 2, .pImageMemoryBarriers = to_dst.data()});
        for (int i = 0; i < 2; ++i) {
            cmdbuf.copyImage(src[i], src_layout, dst[i],
                             vk::ImageLayout::eTransferDstOptimal, regions);
        }
        std::array<vk::ImageMemoryBarrier2, 2> to_general;
        for (int i = 0; i < 2; ++i) {
            to_general[i] = to_dst[i];
            to_general[i].srcStageMask = vk::PipelineStageFlagBits2::eCopy;
            to_general[i].srcAccessMask = vk::AccessFlagBits2::eTransferWrite;
            to_general[i].dstStageMask = Compute;
            to_general[i].dstAccessMask = vk::AccessFlagBits2::eShaderRead;
            to_general[i].oldLayout = vk::ImageLayout::eTransferDstOptimal;
            to_general[i].newLayout = vk::ImageLayout::eGeneral;
        }
        cmdbuf.pipelineBarrier2(
            {.imageMemoryBarrierCount = 2, .pImageMemoryBarriers = to_general.data()});
    });
    if (reduced) {
        scene_targets.Attachment(ids[0], target_info);
        scene_targets.Attachment(ids[1], target_info);
    } else {
        for (auto* target : targets) {
            runtime.Transit(target, vk::ImageLayout::eColorAttachmentOptimal,
                            vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                            vk::AccessFlagBits2::eColorAttachmentWrite |
                                vk::AccessFlagBits2::eColorAttachmentRead);
        }
        runtime.FlushBarriers();
    }
    return true;
}

// bbport (r42_lamp-soft): the lamps of the pass that takes the history: its records are
// data[ConstantWords, end), LightWords each. blend: the pass averages over the frames; then
// every record gets, in words 12 to 14 (the pass reads words 0 to 6 of a record and nothing
// else; the game's records hold other things there, so they are always written), how far its
// lamp moved since the frame before, in that frame's view space, or zero
// (BB_LAMP_SHADOW_FOLLOW=0): the pass looks a pixel's history up where its strongest lamp's
// motion puts it (LampTrack); and in word 15 that distance in metres, which shortens the
// history under a moving lamp (BB_LAMP_SHADOW_TRAIL). read: there is a frame before to follow
// the lamps from. line: the log line that says where the lamps are.
void PointShadow::TrackLamps(u32 end, bool blend, bool read, bool line) {
    const auto camera = camera_motion.PassMatrices();
    const u32 records = end > ConstantWords ? (end - ConstantWords) / LightWords : 0u;
    track.Begin(camera.valid ? camera.inv_view.data() : nullptr);
    track_index.resize(records);
    // The lamps near the camera first: with more than LampTrack::Most lamps in a pass those
    // are the ones told apart and followed (a hand torch is always near). untold: records of
    // lamps beyond that number.
    u32 untold = 0;
    for (const bool close_first : {true, false}) {
        for (u32 k = 0; k < records; ++k) {
            const u32* record = data.data() + ConstantWords + k * LightWords;
            if ((LampTrack::Away(record) <= LampTrack::Near) != close_first) {
                continue;
            }
            track_index[k] = s8(track.Add(record));
            untold += track_index[k] < 0 && std::bit_cast<float>(record[3]) > 0.0f ? 1 : 0;
        }
    }
    if (blend) {
        if (read) {
            track.Follow();
        }
        for (u32 k = 0; k < records; ++k) {
            std::array<float, 3> shift{};
            if (read && tune.follow) {
                shift = track.Shift(track_index[k], last_view.data());
            }
            const float step = read ? track.Step(track_index[k]) : 0.0f;
            u32* record = data.data() + ConstantWords + k * LightWords;
            for (u32 c = 0; c < 3; ++c) {
                record[12 + c] = std::bit_cast<u32>(shift[c]);
            }
            record[15] = std::bit_cast<u32>(step);
            // bbport (r91_lamp-radius-per-lamp): word 10, the lamp's own disc and its rays' blind
            // distance (LampDiscWord), read by the pass only with tune word 0 bit 24, which Flush
            // sets after this call
            if (tune.disc_each > 0.0f) {
                const float disc = track.Disc(track_index[k], LampDiscRadius(tune, std::bit_cast<float>(record[3])));
                record[10] = LampDiscWord(tune, disc);
            }
        }
    }
    if (!line) {
        return;
    }
    lamp_line_frames = 0;
    u32 close = 0;
    for (u32 i = 0; i < track.Count(); ++i) {
        close += track.Lamp(i).away <= LampTrack::Near ? 1 : 0;
    }
    // (A lamp is told apart by its place, reach and colour: two lights of one torch at one
    // place are two lamps here. The steps: a flame whose lamp wobbles shows a mean step while
    // its carrier stands.)
    std::printf("Ray traced lamps (r42): %u lamp records in the pass, %u lamps told apart (the "
                "near ones first, %u at most; %u records are of more lamps than that), %u "
                "within %.0f m of the camera; since the last such line the pass averaged on %u "
                "frames and read its history on %u of them (%u camera cuts), and %u ray traced "
                "lamp passes beside it had point lamps; on %u of the averaged frames the pass "
                "ran at half resolution (r44); the brightest near lamps (%s, reach, "
                "luminance, distance to the camera, records, moved since the frame before; "
                "then over the frames it was followed since the last line: how many, its mean "
                "step and its largest):",
                records, track.Count(), LampTrack::Most, untold, close, double(LampTrack::Near),
                line_blend, line_read, line_cuts, line_beside, line_half,
                camera.valid ? "world x y z" : "view space x y z, the camera is not known");
    for (const int index : track.Strongest()) {
        if (index < 0) {
            break;
        }
        const LampSeen& lamp = track.Lamp(u32(index));
        std::printf(" (%.2f %.2f %.2f) %.1f m, %.2f, %.2f m, %u", lamp.world[0], lamp.world[1],
                    lamp.world[2], lamp.radius, lamp.luma, lamp.away, lamp.records);
        if (tune.disc_each > 0.0f) { // bbport (r91_lamp-radius-per-lamp)
            std::printf(", disc %.3f m (%u jumps)", lamp.disc, lamp.disc_moves);
        }
        if (lamp.followed) {
            std::printf(", %.3f m (%u frames, mean %.4f m, most %.4f m);",
                        std::sqrt(lamp.moved[0] * lamp.moved[0] + lamp.moved[1] * lamp.moved[1] +
                                  lamp.moved[2] * lamp.moved[2]),
                        lamp.steps, lamp.steps ? lamp.step_sum / float(lamp.steps) : 0.0f,
                        lamp.step_most);
        } else {
            std::printf(", not followed;");
        }
    }
    std::printf("\n");
    line_blend = line_read = line_cuts = line_beside = line_half = 0;
    // bbport (r93_lamp-shadow-spatial): a short line of its own right after the r42 line, at its
    // times (the slot runs keep 300 characters of a log line; the r42 line is longer before its lamps)
    if (tune.spatial) {
        std::printf("Ray traced lamps (r93): the spatial pre-filter ran in the resolve on %u of the frames "
                    "the r42 line above counts as averaged\n",
                    line_spatial);
    }
    line_spatial = 0; // bbport (r93_lamp-shadow-spatial)
    LampYoungLine(); // bbport (r103_lamp-young-pixels): a short line after the r42 line, only with the knob set
    LampMovingSmoothLine(); // bbport (r60c_moving-shadow-steps): a short line after r103's, only with the knob on
    LampLayersLine(); // bbport (r114_lamp-shadow-layers): a short line after the r42 line, with the knob set
    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1: a short line of its own after the r42
    // line, at its times (the slot runs keep 300 characters of a log line; the r42 line is longer
    // than that before its lamps)
    if (colour_mode) {
        std::printf("Ray traced lamps (r92): %u ray traced lamp passes shadowed in colour since the last "
                    "r42 line (%u of them read their colour history), %u stayed grey (a CARDS build, "
                    "LANTERN_RT_LAMP_REUSE's history, the repair off, or no colour image of their size)\n",
                    line_colour, line_colour_read, line_colour_grey);
    }
    line_colour = line_colour_read = line_colour_grey = 0; // bbport (r92_lamp-shadow-colour)
    track.ClearSteps();
}

void PointShadow::Flush(bool animate_noise) {
    if (tiles.empty()) {
        return;
    }
    const auto ids = pending;
    const auto uids = pending_uid;
    auto batch = std::move(tiles);
    tiles.clear();
    pending[0] = pending[1] = {};
    // Every return before the pass is recorded loses an apart batch's lamp light for this frame
    // (lamp_dirty stays set: the lamp images are cleared before their next use).
    const bool batch_apart = std::exchange(apart, false);
    redirect_draw = false;
    // Counts the batch as lost on every return before its pass is recorded.
    struct Lost {
        u32& count;
        bool armed;
        ~Lost() {
            count += armed;
        }
    } lost{lost_passes, batch_apart};
    const auto depth_id = camera_motion.Depth();
    if (!depth_id) {
        return;
    }
    auto* depth_ptr = texture_cache.TryGetImage(depth_id, 0);
    auto* target0 = texture_cache.TryGetImage(ids[0], uids[0]);
    auto* target1 = texture_cache.TryGetImage(ids[1], uids[1]);
    if (!depth_ptr || !target0 || !target1) {
        return;
    }
    auto& depth = *depth_ptr;
    std::array<VideoCore::Image*, 2> targets{target0, target1};
    const bool reduced = scene_targets.Reduced() && scene_targets.Eligible(depth) &&
                         scene_targets.Eligible(*targets[0]);
    u32 width = targets[0]->info.size.width, height = targets[0]->info.size.height;
    if (reduced) {
        const auto size = scene_targets.ProxySize(*targets[0]);
        width = size.width;
        height = size.height;
    }
    // What the pass reads beside the light targets: their snapshots, or the lamps' light.
    const OwnImage* before = batch_apart ? lamp : snapshot;
    if (before[0].width != width || before[0].height != height) {
        return;
    }

    scheduler.EndRendering();
    const bool batch_merged = merged;
    merged = false;
    // (An apart batch was begun for rays: the setting going off meanwhile does not drop it.)
    const bool use_rays =
        ray_pipeline && (batch_apart || RaysWanted()) && rt_shadow.PrepareScene();
    if (!use_rays &&
        (batch_merged ||
         !BbSettings::Get().effects[BbSettings::EffectPointShadows].load(std::memory_order_relaxed))) {
        return;
    }
    std::array<s32, 4> covered{s32(width), s32(height), 0, 0};
    u32 table = 0;
    // bbport (r41_lamp-shadows): the repair, unless experiment 35184372088832 is set (read at
    // every pass): the tuning words go after the tile table, their place into the mode word.
    bool repair = false;
    u32 tune_at = 0;
    // One pass a frame can use the history. While the lamps are drawn apart that is their pass, the
    // one that covers the screen: a small batch before it (a lamp quad that could not go apart)
    // does not take it.
    const bool history_ours = batch_apart || (apart_draws == 0 && !apart_last_frame);
    // bbport (r37_menu-options): BB_LAMP_SHADOW_HALF when set, else graphics_lamp_shadow_half.
    // bbport (r65_lamp-half-at-start): HalfWanted, the test Ready makes at start too.
    const bool half_on = HalfWanted();
    // bbport (r32_lamp-half): BB_LAMP_SHADOW_HALF=1 and experiment 72057594037927936 clear: the
    // lamps-apart pass in two halves (point_shadow_ray_half_comp), with the block answers in an
    // image of half the size.
    // bbport (r37_menu-options): half_on, above: BB_LAMP_SHADOW_HALF when set, else
    // graphics_lamp_shadow_half.
    // bbport (r42_lamp-soft): decided here, before the pass's tuning, which depends on it (it
    // was decided after: a pass that asked for the half resolution and did not get it, no
    // pipeline or no room, ran at full resolution with point lamps and said "half resolution").
    // bbport (r65_lamp-half-at-start): where HalfReady was first called before r65; from here
    // the counters line runs (OnFrameEnd), as it did then.
    half_asked = half_asked || (use_rays && batch_apart && half_on);
    bool use_half = use_rays && batch_apart && half_on && HalfReady();
    if (use_half && BbToggle::Experiment(HalfOffBit)) {
        use_half = false;
        ++half_line_full;
    }
    if (use_half) {
        const u32 half_width = (width + 1) / 2, half_height = (height + 1) / 2;
        if (half_answers.width != half_width || half_answers.height != half_height) {
            if (!EffectPass::HasRoom(instance, 8ull * half_width * half_height)) {
                use_half = false;
            } else if (EnsureImage(half_answers, half_width, half_height, HistoryFormat,
                                   "Ray traced lamp half answers")) {
                half_laid_out = false;
            }
        }
    }
    // bbport (r42_lamp-soft): the tuning of this pass. The area lamp shows one ray's answer a
    // frame, which is noise until the history has averaged it, so only the pass that takes the
    // history has it (with the lamps drawn apart, the default, that is the one pass that covers
    // the screen); another ray traced pass of the frame (`beside`) keeps the point lamp.
    // BB_LAMP_SHADOW_HISTORY=0 asks for the bare rays: then every full-resolution pass has the
    // area lamp.
    // bbport (r44_half-area-lamp): the pass at half resolution (r32) has the area lamp as well
    // when it takes the history. r42 kept point lamps there (one area-lamp ray for a 2x2 block
    // would show as noise in blocks), which left the hard bands the area lamp was made to
    // remove in every game played with graphics_lamp_shadow_half. Now the pass's first half
    // averages the pixel it traces for a block in the history, as the full-resolution pass
    // does for every pixel, so a block's answer is an averaged ratio: 0 or 1 where light or
    // shadow is flat, where the second half shares it as before; where the blocks around a
    // pixel differ (a shadow's edge, a penumbra) every pixel casts its own ray and averages it
    // in its own history, which is of full resolution (point_shadow_ray.comp). What the half
    // resolution saves is then the flat part of the screen: the 600-frame line of the
    // half-resolution pass says what share of its pixels the second half traced. Without the
    // averaging a pass at half resolution has point lamps, and with experiment
    // 2305843009213693952 set (half_points) it is the pass of before r44: point lamps without
    // a history (LampPassRadius).
    // bbport (r48_lamp-softness): the lamp's radius as graphics_lamp_shadow_softness has it now
    // (BB_LAMP_SHADOW_SOFT, when it gave a number, wins: LampSoftnessRadius), taken at every pass
    // before anything below is worked out from it, so the menu switches it live. A history
    // written at another radius is not read (history_radius_m, below): it would blend two
    // softnesses.
    const int softness = BbSettings::Get().graphics_lamp_shadow_softness.load(std::memory_order_relaxed);
    // bbport (r62f_cutout-live-flip): TOOL (test aid; needs r84): BB_LAMP_SHADOW_VIEW asked again at
    // every pass through the live knobs file, by ReadLampShadowTune's rule (not set, empty or not a
    // whole number: 0; else clamped to 0-7). Every use of the view is per pass (LampTuneWords, the
    // centred window's split below); the history and the half-resolution answers never hold a view.
    // Without BB_LIVE_KNOBS_FILE it is the environment's value, which the constructor read: nothing
    // changes. Said once at each change.
    {
        static BbLiveKnobs::Knob<u32> view_knob{
            "BB_LAMP_SHADOW_VIEW", [](const char* text) -> u32 {
                const u32 fallback = LampShadowTune{}.view;
                if (text == nullptr || text[0] == 0) {
                    return fallback;
                }
                char* end = nullptr;
                const long value = std::strtol(text, &end, 10);
                return end != text && LampTuneDetail::Ends(end)
                           ? u32(std::clamp(value, 0l, long(LampTuneViewMax)))
                           : fallback;
            }};
        const u32 view_now = view_knob.Get();
        if (view_now != tune.view) {
            tune.view = view_now;
            std::printf("Ray traced lamps (r62f): view %u now (BB_LAMP_SHADOW_VIEW, live)\n", view_now);
        }
    }
    // bbport (r87_live-flip-knobs): TOOL: BB_LAMP_SHADOW_CLEARANCE asked again at every pass (a live
    // knob), so one running game can flip the blind sphere at the lamp; the rule of
    // ReadLampShadowTune (not set or not a number: the default; 0.05-2)
    {
        static BbLiveKnobs::Knob<float> clearance{
            "BB_LAMP_SHADOW_CLEARANCE", [](const char* text) -> float {
                const float fallback = LampShadowTune{}.clearance_m;
                if (text == nullptr || text[0] == 0) {
                    return fallback;
                }
                char* end = nullptr;
                const float value = std::strtof(text, &end);
                return end != text && std::isfinite(value) ? std::clamp(value, 0.05f, 2.0f) : fallback;
            }};
        tune.clearance_m = clearance.Get();
    }
    tune.radius_m = LampSoftnessRadius(tune, softness);
    if (use_rays && tune.radius_m != told_radius_m) {
        told_radius_m = tune.radius_m;
        std::printf("Ray traced lamps (r48): lamp radius %.2f m (%s%s)%s\n", tune.radius_m,
                    tune.radius_set ? "BB_LAMP_SHADOW_SOFT" : "graphics_lamp_shadow_softness=",
                    tune.radius_set ? ""
                                    : BbSettings::LampSoftnessNames[std::clamp(
                                          softness, 0, BbSettings::LampSoftnessCount - 1)],
                    tune.radius_m > 0.0f
                        ? "; the history starts again at this radius"
                        : ": point lamps without a history, every lamp that reaches a pixel traced");
    }
    const bool history_pass = use_rays && !history_written && history_ours;
    const bool half_points = use_half && BbToggle::Experiment(HalfPointsBit);
    const bool beside = use_rays && !half_points && !history_pass && LampHistoryFrames(tune) > 0.0f;
    LampShadowTune pass_tune = tune;
    pass_tune.radius_m = LampPassRadius(tune, history_pass, use_half, half_points);
    if (use_rays) {
        table = u32(data.size());
        for (const Tile& tile : batch) {
            covered = {std::min(covered[0], tile.rect[0]), std::min(covered[1], tile.rect[1]),
                       std::max(covered[2], tile.rect[2]), std::max(covered[3], tile.rect[3])};
            data.insert(data.end(), {u32(tile.rect[0]), u32(tile.rect[1]), u32(tile.rect[2]),
                                     u32(tile.rect[3]), tile.first_light, tile.count, 0u, 0u});
        }
        repair = !BbToggle::Experiment(LampRepairOffBit);
        line_beside += repair && beside ? 1 : 0; // bbport (r42_lamp-soft): for the lamp line
        if (repair) {
            const auto& settings = BbSettings::Get();
            // The scene the rays cross is in this camera's view space (RtShadow::PrepareScene,
            // true above, wrote its instances with this matrix): the world's axes for the
            // lamp's disc, so that it does not turn with the camera. bbport (r42_lamp-soft): and
            // the frame counter, which moves the point of the disc a ray goes to.
            const auto camera = camera_motion.PassMatrices();
            const auto tune_words = LampTuneWords(pass_tune, settings.startup_local_inverse_square,
                                                  settings.startup_local_light_core,
                                                  camera.valid ? camera.view.data() : nullptr,
                                                  frame_index);
            tune_at = u32(data.size());
            data.insert(data.end(), tune_words.begin(), tune_words.end());
            data[tune_at] |= LampFlameBits(); // bbport (r113_lamp-softness): bits 11, 23; 0 when off
            data[tune_at] |= LampYoungBits(pass_tune); // bbport (r103_lamp-young-pixels): bits 27, 28; 0 when off
            data[tune_at] |= LampMovingEdgeBits(); // bbport (r101_lamp-moving-edge): 0 when off
            data[tune_at] |= LampTuneSpatialBit(pass_tune); // bbport (r93_lamp-shadow-spatial): bit 26
            data[tune_at] |= LampLayersBits(pass_tune.radius_m > 0.0f && LampHistoryFrames(pass_tune) > 0.0f); // bbport (r114_lamp-shadow-layers): bits 4-7, 18, 19, 30, 31; 0 when off
        }
        if (int(repair) != std::exchange(repair_state, int(repair))) {
            std::printf("Ray traced lamps (r41): repair %s (experiment 35184372088832 %s)\n",
                        repair ? "on" : "off", repair ? "clear" : "set");
        }
        if (data.size() > DataWords || covered[0] >= covered[2] || covered[1] >= covered[3]) {
            data.clear();
            return;
        }
        bool made = false;
        // bbport (r52_follow-soft): the follow state is made with the history, its room counted
        // with it: without room for both, neither (and no pass).
        if (!history[0].image || history[0].width != width || history[0].height != height ||
            !follow[0].image || follow[0].width != width || follow[0].height != height) {
            if (!EffectPass::HasRoom(instance, 2ull * (8 + 4) * width * height)) {
                data.clear();
                return;
            }
            for (int i = 0; i < 2; ++i) {
                EnsureImage(history[i], width, height, HistoryFormat, "Ray traced lamp history");
                history_laid_out[i] = false;
                EnsureImage(follow[i], width, height, FollowFormat, "Ray traced lamp follow state");
                follow_laid_out[i] = false;
            }
            made = true;
        }
        if (made) {
            history_fresh = false;
            history_written = false; // the new images hold nothing: this frame's history starts again
        }
        // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1 (the COLOUR builds, Ready): the colour
        // image (point_shadow_ray.comp colour_image: ColourParts parts of this pass's size stacked, 4
        // bytes a pixel each), made at this pass's size as the history is. Without room for it: no
        // pass while there is none (the COLOUR builds read the binding), else this pass binds the one
        // there is and stays grey (bit 25 clear, below). Not cleared: a part is read only where this
        // pass, or the pass that wrote the history it reads (HistoryColourRead), wrote it first.
        if (colour_mode && (colour_image.width != width || colour_image.height != ColourParts * height)) {
            if (EffectPass::HasRoom(instance, 4ull * ColourParts * width * height) &&
                EnsureImage(colour_image, width, ColourParts * height, ColourFormat, "Ray traced lamp colour")) {
                colour_laid_out = false;
                colour_wrote_frame = ~0u;
                std::printf("Ray traced lamps (r92): the colour image, %ux%u (three parts of %ux%u), %.1f MB\n",
                            width, ColourParts * height, width, height, 4.0 * ColourParts * width * height / 1e6);
            } else if (!colour_image.image) {
                data.clear();
                return;
            }
        }
        // bbport (r60_lamp-centred-window): the centred window's answers (binding 11 of the full
        // build, which every ray traced pass binds), one image of 8 bytes a pixel. Made here, at
        // this pass's size, only when there is none: without room for it, no pass. Only the pass
        // that splits uses it and gives it its own size (below, once `split` is known), so a
        // pass of another size beside it (two ray passes of different size a frame) does not
        // make it anew. Nothing is read from it that the pass's trace did not write first
        // (point_shadow_ray.comp loadTile), so it is not cleared.
        if (centred && !answers.image) {
            if (!EffectPass::HasRoom(instance, 8ull * width * height)) {
                data.clear();
                return;
            }
            if (EnsureImage(answers, width, height, AnswersFormat, "Ray traced lamp answers")) {
                answers_laid_out = false;
                std::printf("Ray traced lamps (r60): the centred window's answers, %ux%u, %.1f MB\n", width,
                            height, 8.0 * width * height / 1e6);
            }
        }
    }
    u32 history_at = 0;
    bool clear_history = false;
    std::array<bool, 2> lay_out{};
    std::array<bool, 2> follow_lay_out{}; // bbport (r52_follow-soft)
    // bbport (r60_lamp-centred-window): the pass runs as a trace and a resolve (the shader takes
    // the same decision: the pass averages, the centred window, not view 2 or 3)
    bool split = false;
    // (history_ours: above.)
    if (use_rays && !history_written && history_ours) {
        const auto camera = camera_motion.PassMatrices();
        bool ok = false;
        const auto proj = Invert(data.data(), ok);
        // bbport (r42_lamp-soft): the area lamp's history: the pass averages each pixel's shadow
        // ratio over the frames (HistoryBlend; `keep`: the most frames a texel may hold), which
        // takes the place of LANTERN_RT_LAMP_REUSE's history for as long as it is on. A history
        // of the other kind (the experiment bit or a setting changed) is not read.
        const float keep = repair ? LampHistoryFrames(pass_tune) : 0.0f;
        const bool blend = keep > 0.0f;
        const bool kept = blend || lamp_reuse;
        u32 flags = blend ? HistoryWrite | HistoryBlend : lamp_reuse ? HistoryWrite : 0u;
        // bbport (r60_lamp-centred-window): the half-resolution pass splits only with its centred
        // build (HalfReady may have made the plain one)
        // bbport (r63_leaf-stage4): nor view 7, which the trace draws
        split = centred && (!use_half || half_centred) && blend && pass_tune.view != 2 && pass_tune.view != 3 &&
                pass_tune.view != 7;
        constexpr std::array<float, 12> Identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        auto reproject = Identity;
        // bbport (r48_lamp-softness): nor is one written at another lamp radius (the softness
        // changed): as across a camera cut, the pass starts again from this frame's rays.
        if (kept && history_fresh && history_blended == blend &&
            history_radius_m == pass_tune.radius_m && last_valid && camera.valid && ok) {
            reproject = Multiply(last_view, camera.inv_view);
            // bbport (r42_lamp-soft): an averaged history is not read across a cut (the camera
            // jumped: what of the frame before passes the depth test there does so by chance)
            if (blend && LampCameraCut(reproject.data())) {
                reproject = Identity;
                ++line_cuts;
            } else {
                flags |= HistoryRead;
            }
        }
        // bbport (r42_lamp-soft): a pass that averages and cannot read its history shows bare
        // single rays. For a frame or two that passes (the first frame, a new size, a cut); when
        // it goes on (no camera for the pass, or two ray passes of different size in every
        // frame, which make the history anew every time) the lamps are points until it can
        // read again: the tuning words are in `data` already, so their radius is zeroed there
        // (the pass still writes its history, so the first frame that can read it does).
        bool unread = false;
        if (blend) {
            blend_unread = (flags & HistoryRead) ? 0u : std::min(blend_unread + 1u, UnreadMost + 1u);
            ++line_blend;
            line_read += (flags & HistoryRead) ? 1 : 0;
            line_half += use_half ? 1 : 0; // bbport (r44_half-area-lamp): for the lamp line
            unread = blend_unread > UnreadMost;
            if (unread) {
                data[tune_at + 2] = std::bit_cast<u32>(0.0f);
            }
            // bbport (r44_half-area-lamp): for the half-resolution pass's line, which says
            // "area lamps": not a pass whose radius was just zeroed
            half_line_soft += use_half && !unread ? 1 : 0;
        }
        // What the lamps are on this pass, logged at each change (SoftLines times at most).
        // bbport (r44_half-area-lamp): 1, 6 and 7 are the pass at half resolution.
        const int soft = !repair                                ? 0
                         : half_points                          ? 1
                         : !(tune.radius_m > 0.0f)              ? 2
                         : !(LampHistoryFrames(tune) > 0.0f)    ? (use_half ? 6 : 3)
                         : unread                               ? 5
                         : use_half                             ? 7
                                                                : 4;
        if (soft != std::exchange(soft_state, soft) && soft_lines < SoftLines) {
            static constexpr std::array<const char*, 8> What{
                "point lamps: experiment 35184372088832 is set, the pass of before r41",
                "point lamps without a history: the pass runs at half resolution "
                "(graphics_lamp_shadow_half or BB_LAMP_SHADOW_HALF) and experiment "
                "2305843009213693952 is set, the half-resolution pass of before r44",
                "point lamps without a history, every lamp that reaches a pixel traced "
                "(graphics_lamp_shadow_softness=sharp or BB_LAMP_SHADOW_SOFT=0)",
                "area lamps, one ray a lamp a frame, not averaged (BB_LAMP_SHADOW_HISTORY=0)",
                "area lamps, one ray a lamp a frame, averaged over the frames in the pass's "
                "history",
                "point lamps for now: the pass could not read its history for 8 frames (no "
                "camera for the pass, or the history is made anew every frame)",
                "point lamps without a history: the pass runs at half resolution "
                "(graphics_lamp_shadow_half or BB_LAMP_SHADOW_HALF), where a lamp is an area "
                "lamp only when its answers are averaged (BB_LAMP_SHADOW_HISTORY=0)",
                "area lamps at half resolution (graphics_lamp_shadow_half or "
                "BB_LAMP_SHADOW_HALF): one ray a lamp a frame for one pixel of each 2x2 block "
                "and for every pixel where the blocks' averaged answers differ, averaged over "
                "the frames in the pass's history; experiment 2305843009213693952 set = point "
                "lamps there, as before r44",
            };
            ++soft_lines;
            std::printf("Ray traced lamps (r42): %s%s\n", What[std::size_t(soft)],
                        soft_lines == SoftLines ? " (the last time this is logged)" : "");
        }
        // (Before the lamps' records are written to: a batch without room for the block is
        // dropped as it was.)
        if (data.size() + HistoryWords > DataWords) {
            data.clear();
            return;
        }
        // The lamps of this pass, once a frame: followed for the history, and for the log line.
        // A pass that averages and comes after the frame's TrackLamps (the history was made
        // anew for it) has its lamps standing: words 12 to 15 of its records must not stay
        // what the game left there.
        if (const bool line = lamp_line_frames >= LampLineFrames; blend || line) {
            if (track_frame != frame_index) {
                track_frame = frame_index;
                TrackLamps(table, blend, (flags & HistoryRead) != 0, line);
                // bbport (r91_lamp-radius-per-lamp): the records hold their discs now (word 10):
                // the bit that has the pass read them. Not in a pass that averages after this
                // frame's TrackLamps (below) or one that does not average: their word 10 is the
                // game's.
                if (blend && tune.disc_each > 0.0f) {
                    data[tune_at] |= LampTuneDiscEach;
                }
            } else if (blend) {
                for (u32 at = ConstantWords; at + LightWords <= table; at += LightWords) {
                    std::fill_n(data.begin() + at + 12, 4, 0u);
                }
            }
        }
        history_at = u32(data.size());
        data.push_back(flags);
        data.push_back(frame_index);
        for (const float v : reproject) {
            data.push_back(std::bit_cast<u32>(v));
        }
        for (const float v : last_proj) {
            data.push_back(std::bit_cast<u32>(v));
        }
        // bbport (r42_lamp-soft): words 30 to 33 (the first: 0 unless the pass averages)
        auto tail = LampHistoryTail(pass_tune);
        tail[0] = std::bit_cast<u32>(keep);
        data.insert(data.end(), tail.begin(), tail.end());
        pending_view = camera.view;
        pending_proj = proj;
        pending_valid = camera.valid && ok;
        history_written = kept;
        history_blend = blend;
        history_radius_m = pass_tune.radius_m; // bbport (r48_lamp-softness)
        LampFlamePass(repair && !unread && pass_tune.radius_m > 0.0f); // bbport (r113_lamp-softness): its line
        clear_history = kept;
    }
    // bbport (r60_lamp-centred-window): the pass that splits gives the answers image its size.
    // Without room for that, this pass runs whole (the shader then takes the window of 1), said
    // once in the log.
    if (split && (answers.width != width || answers.height != height)) {
        if (EffectPass::HasRoom(instance, 8ull * width * height) &&
            EnsureImage(answers, width, height, AnswersFormat, "Ray traced lamp answers")) {
            answers_laid_out = false;
            std::printf("Ray traced lamps (r60): the centred window's answers, %ux%u, %.1f MB\n", width, height,
                        8.0 * width * height / 1e6);
        } else {
            split = false;
            if (!std::exchange(answers_short, true)) {
                std::printf("Ray traced lamps (r60): no room for the centred window's answers at %ux%u: the "
                            "pass runs with the window of 1 until there is\n", width, height);
            }
        }
    }
    if (split) {
        answers_short = false;
    }
    LampYoungPass(split && repair && LampYoungBits(pass_tune) != 0u && // bbport (r103_lamp-young-pixels)
                  LampHistoryFrames(pass_tune) >= 2.0f);
    line_spatial += split && repair && LampTuneSpatialBit(pass_tune) != 0u ? 1 : 0; // bbport (r93)
    if (use_rays) {
        lay_out = {!history_laid_out[0], !history_laid_out[1]};
        history_laid_out = {true, true};
        follow_lay_out = {!follow_laid_out[0], !follow_laid_out[1]};
        follow_laid_out = {true, true};
    }
    const vk::ImageView history_prev = use_rays ? *history[history_index ^ 1u].view : vk::ImageView{};
    const vk::ImageView history_cur = use_rays ? *history[history_index].view : vk::ImageView{};
    const vk::Image history_cur_image = use_rays ? vk::Image(history[history_index].image) : vk::Image{};
    const std::array<vk::Image, 2> history_images{
        use_rays ? vk::Image(history[0].image) : vk::Image{},
        use_rays ? vk::Image(history[1].image) : vk::Image{}};
    // bbport (r52_follow-soft): the follow state, taken in turn with the history
    const vk::ImageView follow_prev = use_rays ? *follow[history_index ^ 1u].view : vk::ImageView{};
    const vk::ImageView follow_cur = use_rays ? *follow[history_index].view : vk::ImageView{};
    const std::array<vk::Image, 2> follow_images{
        use_rays ? vk::Image(follow[0].image) : vk::Image{},
        use_rays ? vk::Image(follow[1].image) : vk::Image{}};
    // bbport (r60_lamp-centred-window): the centred window's answers (null without it)
    const bool with_answers = use_rays && centred;
    const bool answers_lay_out = with_answers && !std::exchange(answers_laid_out, true);
    const vk::ImageView answers_view = with_answers ? *answers.view : vk::ImageView{};
    const vk::Image answers_image = with_answers ? vk::Image(answers.image) : vk::Image{};
    const auto device = instance.GetDevice();
    std::array<vk::ImageView, 2> target_views;
    vk::ImageView depth_view{};
    if (reduced) {
        VideoCore::ImageViewInfo target_info, depth_info;
        target_info.format = TargetFormat;
        depth_info.format = depth.info.pixel_format;
        for (int i = 0; i < 2; ++i) {
            target_views[i] = scene_targets
                                  .Read(ids[i], target_info, Compute,
                                        vk::AccessFlagBits2::eShaderRead |
                                            vk::AccessFlagBits2::eShaderWrite)
                                  .view;
        }
        // bbport (r22_barriers): right after the targets' barriers (their Read, compute stage)
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
    } else {
        for (int i = 0; i < 2; ++i) {
            target_views[i] = Check<"create point shadow target view">(device.createImageView({
                .image = targets[i]->GetImage(),
                .viewType = vk::ImageViewType::e2D,
                .format = TargetFormat,
                .subresourceRange = ColorRange,
            }));
        }
        depth_view = Check<"create point shadow depth view">(device.createImageView({
            .image = depth.GetImage(),
            .viewType = vk::ImageViewType::e2D,
            .format = depth.info.pixel_format,
            .subresourceRange = {vk::ImageAspectFlagBits::eDepth, 0, 1, 0, 1},
        }));
        scheduler.DeferOperation([device, target_views, depth_view] {
            device.destroyImageView(target_views[0]);
            device.destroyImageView(target_views[1]);
            device.destroyImageView(depth_view);
        });
        for (auto* target : targets) {
            runtime.Transit(target, vk::ImageLayout::eGeneral, Compute,
                            vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
        }
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute,
                        vk::AccessFlagBits2::eShaderRead);
        runtime.FlushBarriers();
    }

    // bbport (r32_lamp-half): the half resolution (use_half: decided above, r42_lamp-soft)
    const bool half_lay_out = use_half && !std::exchange(half_laid_out, true);
    const bool half_count = use_half && (half_passes++ & 7u) == 0;
    const bool half_clear = use_half && !std::exchange(half_cleared, true);
    half_line_passes += use_half;
    Push push{
        .first_light = 0,
        .frame_index = animate_noise ? frame_index : 0u,
        .size = {float(width), float(height)},
        .length_m = use_rays ? std::bit_cast<float>(history_at) : length_m,
        // bbport (r41_lamp-shadows): MODE_REPAIR and the place of its words
        .thickness_m = use_rays ? std::bit_cast<float>((batch_apart ? ModeApart : 0u) |
                                                       (repair ? ModeRepair | tune_at << TuneAtShift
                                                               : 0u))
                                : thickness_m,
        .strength = use_rays ? 1.0f : strength,
        .fade_start_m = use_rays ? 60.0f : fade_start_m,
        .fade_end_m = use_rays ? 100.0f : fade_end_m,
        .light_count = 0,
        // bbport (r48_lamp-softness): a point lamp traces every lamp (LampPassSteps)
        .steps = use_rays ? LampPassSteps(tune, repair, lamp_pick) : steps,
        .bias_m = repair ? tune.bias_m : bias_m, // bbport (r41_lamp-shadows): BB_LAMP_SHADOW_BIAS
        .rect = {},
    };
    // bbport: counted here. As a capture after `batch = std::move(batch)` it was the size of the
    // emptied vector, zero: the ray traced pass then found no tile in any group and left the
    // lamps unshadowed, for the full cost of its batches.
    const u32 tile_count = u32(batch.size());
    // bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1 and the TLAS holds a card with CARD_LAMP_MASK:
    // this pass runs the CARDS form of its build with set 1 (card_bind), its cap in the tuning word,
    // and one pass in CardCountEvery counts (ModeCardCount; the counters are copied for the host
    // first, zeroed before the first). Its own profiler row. Else the pass of before.
    const vk::DescriptorSet card_bind = use_rays ? CardLampSet(use_half) : vk::DescriptorSet{};
    const bool card_full = card_bind && !use_half, card_half = card_bind && use_half;
    const vk::PipelineLayout card_bind_layout =
        card_half ? *card_half_layout : card_full ? *card_ray_layout : vk::PipelineLayout{};
    card_line_plain += use_rays && card_set_layout && !card_bind ? 1 : 0;
    if (card_bind) {
        const bool counted = card_passes++ % CardCountEvery == 0;
        ++card_line_passes;
        card_line_counted += counted ? 1 : 0;
        push.thickness_m = std::bit_cast<float>(std::bit_cast<u32>(push.thickness_m) |
                                                (counted ? ModeCardCount : 0u));
        if (repair) {
            data[tune_at] |= card_cap_bits << LampTuneCardCapShift;
        }
        if (counted) {
            scheduler.Record([clear = std::exchange(card_counts_clear, false),
                              counters = card_counts->Handle(),
                              readback = card_readback->Handle()](vk::CommandBuffer cmdbuf) {
                if (clear) {
                    cmdbuf.fillBuffer(counters, 0, VK_WHOLE_SIZE, 0);
                } else {
                    EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                              vk::PipelineStageFlagBits2::eTransfer,
                                              vk::AccessFlagBits2::eTransferRead);
                    const vk::BufferCopy region{0, 0, CARD_LAMP_BUFFER_WORDS * sizeof(u32)}; // bbport (r62m): the book too
                    cmdbuf.copyBuffer(counters, readback, region);
                }
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                          vk::AccessFlagBits2::eTransferWrite |
                                              vk::AccessFlagBits2::eTransferRead,
                                          vk::PipelineStageFlagBits2::eHost | Compute,
                                          vk::AccessFlagBits2::eHostRead |
                                              vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite);
            });
        }
    }
    // bbport (r92_lamp-shadow-colour): this pass shadows in colour (tuning word 0 bit 25,
    // LampTuneColour) when its build is a COLOUR one (not a CARDS build), the repair's words are there,
    // the colour image has its size and its history is not LANTERN_RT_LAMP_REUSE's (a history without
    // HistoryBlend: its pixels that take the history's ratio in place of rays would be grey on the
    // frames between their rays). A pass that averages then also says which part of the image is
    // this frame's colour history (HistoryColourOne: history_index, as the history images are taken)
    // and whether the other part holds the colour of the history it reads (HistoryColourRead: the last
    // pass that wrote a history, the one read, wrote its colour too: colour_wrote_frame, set by every
    // pass that writes a history, ~0u by one that wrote it without colour and by a new colour image).
    // The image is bound to every ray traced pass while the COLOUR builds are made (their layouts
    // have the binding).
    const u32 colour_flags = history_at != 0 ? data[history_at] : 0u;
    const bool colour_pass = use_rays && colour_mode && repair && !card_bind &&
                             colour_image.width == width && colour_image.height == ColourParts * height &&
                             (colour_flags == 0u || (colour_flags & HistoryBlend) != 0);
    line_colour += colour_pass ? 1 : 0;
    line_colour_grey += use_rays && colour_mode && !colour_pass ? 1 : 0;
    if (colour_pass) {
        data[tune_at] |= LampTuneColour;
    }
    if (colour_mode && (colour_flags & HistoryWrite) != 0) {
        const bool colour_blend = colour_pass && (colour_flags & HistoryBlend) != 0;
        if (colour_blend) {
            const bool colour_read = (colour_flags & HistoryRead) != 0 && colour_wrote_frame != ~0u;
            data[history_at] |= (history_index != 0 ? HistoryColourOne : 0u) | (colour_read ? HistoryColourRead : 0u);
            line_colour_read += colour_read ? 1 : 0;
        }
        colour_wrote_frame = colour_blend ? frame_index : ~0u;
    }
    const vk::ImageView colour_view = use_rays && colour_mode ? *colour_image.view : vk::ImageView{};
    const vk::Image colour_vk_image = use_rays && colour_mode ? vk::Image(colour_image.image) : vk::Image{};
    const bool colour_lay_out = bool(colour_view) && !std::exchange(colour_laid_out, true);
    EffectPass::Mark(card_bind ? 64 : 6, card_bind ? "point shadows (leaf cards)" : "point shadows");
    if (batch_apart) {
        lamp_dirty = false; // the pass zeroes every lamp texel that holds light
        ++apart_passes;
        lost.armed = false;
    }
    // bbport (r61_lamp-window-cost): the resolves of a split pass run their own build (made beside
    // the centred builds by Ready and HalfReady; null: the centred build, which r60 ran them in). With
    // BB_GPU_PROFILE=1 a split pass is recorded in parts with a mark between them, so that the
    // resolves have a row of their own ("Lighting: point shadows: resolve"): the trace and the
    // resolve at full resolution; the first half's trace, its resolve, the second half's trace and
    // its resolve at half resolution. Without the profiler, or a split, it is one part, as before.
    const bool own_resolve = split && (use_half ? bool(half_resolve_pipeline) : bool(resolve_pipeline));
    const int parts = split && GpuProfiler::Get() ? (use_half ? 4 : 2) : 0;
    auto record =
        [push, base_word = std::bit_cast<u32>(push.thickness_m), last_part = parts - 1, // bbport (r61)
         resolve_pipe = own_resolve ? (use_half ? *half_resolve_pipeline : *resolve_pipeline) : vk::Pipeline{},
         resolve_pipe_layout = own_resolve ? (use_half ? *half_resolve_layout : *resolve_layout)
                                           : vk::PipelineLayout{},
         target_views, depth_view, sampler = *sampler, snap0 = *before[0].view,
         snap1 = *before[1].view, batch = std::move(batch), words = std::move(data),
         buffer = light_data->Handle(),
         pipeline = card_full ? *card_ray_pipeline : use_rays ? *ray_pipeline : *pipeline, // (r63)
         layout = card_full ? *card_ray_layout : use_rays ? *ray_layout : *layout, use_rays,
         scene = rt_shadow.Scene(), covered,
         table, tile_count, history_prev, history_cur, history_cur_image,
         history_images, lay_out, clear_history,
         follow_prev, follow_cur, follow_images, follow_lay_out, // bbport (r52_follow-soft)
         with_answers, answers_lay_out, answers_view, answers_image, split, // bbport (r60)
         card_bind, card_bind_layout, // bbport (r63_leaf-stage4)
         colour_view, colour_vk_image, colour_lay_out, // bbport (r92_lamp-shadow-colour)
         half_with_answers = with_answers && use_half && half_centred,     // bbport (r60)
         // bbport (r32_lamp-half): null unless this pass runs in two halves
         half_pipe = card_half ? *card_half_pipeline : use_half ? *half_pipeline : vk::Pipeline{}, // (r63)
         half_pipe_layout = card_half ? *card_half_layout : use_half ? *half_layout : vk::PipelineLayout{},
         half_view = use_half ? *half_answers.view : vk::ImageView{},
         half_image = use_half ? vk::Image(half_answers.image) : vk::Image{},
         half_count_buffer = use_half ? half_counts->Handle() : vk::Buffer{},
         half_read_buffer = use_half ? half_readback->Handle() : vk::Buffer{}, half_lay_out,
         half_count, half_clear](vk::CommandBuffer cmdbuf, int part) mutable {
            // bbport (r61_lamp-window-cost): part: -1 the whole pass; else one part of the split pass
            // (above). The first part lays out, clears and fills what the pass uses, as the whole pass
            // does; every part binds its own pipeline, descriptors and constants.
            if (part <= 0) {
                for (int i = 0; i < 2; ++i) {
                    if (!lay_out[i]) {
                        continue;
                    }
                    const vk::ImageMemoryBarrier2 to_general{
                        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                        .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                        .dstAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                        .oldLayout = vk::ImageLayout::eUndefined,
                        .newLayout = vk::ImageLayout::eGeneral,
                        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .image = history_images[i],
                        .subresourceRange = ColorRange,
                    };
                    cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
                }
                // bbport (r52_follow-soft): the follow images on their first use, as the history's
                // (and zeroed below: nothing reads a texel the pass has not written, this keeps them
                // defined all the same)
                for (int i = 0; i < 2; ++i) {
                    if (!follow_lay_out[i]) {
                        continue;
                    }
                    const vk::ImageMemoryBarrier2 to_general{
                        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                        .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                        .dstAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                        .oldLayout = vk::ImageLayout::eUndefined,
                        .newLayout = vk::ImageLayout::eGeneral,
                        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .image = follow_images[i],
                        .subresourceRange = ColorRange,
                    };
                    cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
                }
                if (answers_lay_out) { // bbport (r60_lamp-centred-window): on its first use
                    const vk::ImageMemoryBarrier2 to_general{
                        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                        .dstStageMask = Compute,
                        .dstAccessMask = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite,
                        .oldLayout = vk::ImageLayout::eUndefined,
                        .newLayout = vk::ImageLayout::eGeneral,
                        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .image = answers_image,
                        .subresourceRange = ColorRange,
                    };
                    cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
                }
                if (colour_lay_out) { // bbport (r92_lamp-shadow-colour): on its first use
                    const vk::ImageMemoryBarrier2 to_general{
                        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                        .dstStageMask = Compute,
                        .dstAccessMask = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite,
                        .oldLayout = vk::ImageLayout::eUndefined,
                        .newLayout = vk::ImageLayout::eGeneral,
                        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .image = colour_vk_image,
                        .subresourceRange = ColorRange,
                    };
                    cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
                }
                const vk::MemoryBarrier2 to_transfer{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eMemoryRead,
                    .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                    .dstAccessMask = vk::AccessFlagBits2::eTransferWrite};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_transfer});
                if (clear_history) {
                    const vk::MemoryBarrier2 history_free{
                        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                        .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                        .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                        .dstAccessMask = vk::AccessFlagBits2::eTransferWrite};
                    cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &history_free});
                    const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
                    cmdbuf.clearColorImage(history_cur_image, vk::ImageLayout::eGeneral, zero, ColorRange);
                }
                for (int i = 0; i < 2; ++i) { // bbport (r52_follow-soft)
                    if (follow_lay_out[i]) {
                        const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
                        cmdbuf.clearColorImage(follow_images[i], vk::ImageLayout::eGeneral, zero, ColorRange);
                    }
                }
                for (u32 at = 0; at < words.size(); at += UpdateWords) {
                    const u32 count = std::min<u32>(UpdateWords, u32(words.size()) - at);
                    cmdbuf.updateBuffer(buffer, at * sizeof(u32), count * sizeof(u32), words.data() + at);
                }
                const vk::MemoryBarrier2 before{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
                    .dstStageMask = Compute,
                    .dstAccessMask = vk::AccessFlagBits2::eShaderRead |
                                     vk::AccessFlagBits2::eShaderWrite};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
            }
            const vk::DescriptorBufferInfo lights{buffer, 0, words.size() * sizeof(u32)};
            const vk::DescriptorImageInfo depth_info{sampler, depth_view,
                                                     vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo cur0{{}, target_views[0], vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo old0{{}, snap0, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo cur1{{}, target_views[1], vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo old1{{}, snap1, vk::ImageLayout::eGeneral};
            const std::array<vk::WriteDescriptorSet, 6> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &lights},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                 .pImageInfo = &depth_info},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &cur0},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &old0},
                {.dstBinding = 4, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &cur1},
                {.dstBinding = 5, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &old1},
            }};
            const vk::WriteDescriptorSetAccelerationStructureKHR scene_info{
                .accelerationStructureCount = 1, .pAccelerationStructures = &scene};
            const vk::DescriptorImageInfo prev_info{{}, history_prev, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo cur_info{{}, history_cur, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo follow_prev_info{{}, follow_prev, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo follow_cur_info{{}, follow_cur, vk::ImageLayout::eGeneral};
            // bbport (r60_lamp-centred-window): with the centred window's builds, binding 11 too
            const vk::DescriptorImageInfo answers_info{{}, answers_view, vk::ImageLayout::eGeneral};
            const u32 ray_count = with_answers ? 12u : 11u;
            const std::array<vk::WriteDescriptorSet, 12> ray_writes{
                writes[0], writes[1], writes[2], writes[3], writes[4], writes[5],
                vk::WriteDescriptorSet{.pNext = &scene_info, .dstBinding = 6, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eAccelerationStructureKHR},
                vk::WriteDescriptorSet{.dstBinding = 7, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &prev_info},
                vk::WriteDescriptorSet{.dstBinding = 8, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &cur_info},
                // bbport (r52_follow-soft): the follow state
                vk::WriteDescriptorSet{.dstBinding = 9, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &follow_prev_info},
                vk::WriteDescriptorSet{.dstBinding = 10, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &follow_cur_info},
                vk::WriteDescriptorSet{.dstBinding = 11, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &answers_info}};
            // bbport (r92_lamp-shadow-colour): with the COLOUR builds (and the CARDS builds' layouts
            // then), the colour image in the binding after the build's last (11; 12 with the centred
            // window's answers)
            const vk::DescriptorImageInfo colour_info{{}, colour_view, vk::ImageLayout::eGeneral};
            std::array<vk::WriteDescriptorSet, 13> colour_writes{};
            std::copy_n(ray_writes.begin(), ray_count, colour_writes.begin());
            colour_writes[ray_count] = vk::WriteDescriptorSet{.dstBinding = ray_count, .descriptorCount = 1,
                                                              .descriptorType = vk::DescriptorType::eStorageImage,
                                                              .pImageInfo = &colour_info};
            const u32 ray_pushed = colour_view ? ray_count + 1u : ray_count;
            const vk::WriteDescriptorSet* const ray_push = colour_view ? colour_writes.data() : ray_writes.data();
            // bbport (r60_lamp-centred-window): between the trace and the resolve (and after the
            // resolve of the half-resolution build's first pass): what one dispatch wrote, the
            // next reads.
            const auto between = [&cmdbuf] {
                EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite, Compute,
                                          vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
            };
            // bbport (r63_leaf-stage4): the cards' set 1, bound after one push of set 0 with the
            // same layout (a push of set 0 with a layout not compatible for it, left by another
            // pass, would disturb set 1). The pass's own pushes of set 0 below use this layout (or
            // r61's resolve layout, compatible for set 0): set 1 stays bound through them.
            if (card_bind) {
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, card_bind_layout, 0, writes[0]);
                cmdbuf.bindDescriptorSets(vk::PipelineBindPoint::eCompute, card_bind_layout, 1, card_bind, {});
            }
            // bbport (r32_lamp-half): BB_LAMP_SHADOW_HALF=1: pixel (2x, 2y) of each 2x2 block
            // (16x16 pixels a workgroup), then the other three, each taking its block's answer
            // or tracing; then what the full-resolution pass does after its dispatch.
            if (half_pipe) {
                if (half_lay_out && part <= 0) {
                    const vk::ImageMemoryBarrier2 to_general{
                        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                        .dstStageMask = Compute,
                        .dstAccessMask = vk::AccessFlagBits2::eShaderRead |
                                         vk::AccessFlagBits2::eShaderWrite,
                        .oldLayout = vk::ImageLayout::eUndefined,
                        .newLayout = vk::ImageLayout::eGeneral,
                        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .image = half_image,
                        .subresourceRange = ColorRange,
                    };
                    cmdbuf.pipelineBarrier2(
                        {.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
                }
                if (half_clear && part <= 0) { // the counters start at zero
                    cmdbuf.fillBuffer(half_count_buffer, 0, VK_WHOLE_SIZE, 0);
                    EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                              vk::AccessFlagBits2::eTransferWrite, Compute,
                                              vk::AccessFlagBits2::eShaderRead |
                                                  vk::AccessFlagBits2::eShaderWrite);
                }
                const vk::DescriptorImageInfo half_info{{}, half_view, vk::ImageLayout::eGeneral};
                const vk::DescriptorBufferInfo count_info{half_count_buffer, 0, VK_WHOLE_SIZE};
                const std::array<vk::WriteDescriptorSet, 14> half_writes{
                    ray_writes[0], ray_writes[1], ray_writes[2], ray_writes[3], ray_writes[4],
                    ray_writes[5], ray_writes[6], ray_writes[7], ray_writes[8],
                    vk::WriteDescriptorSet{.dstBinding = 9, .descriptorCount = 1,
                                           .descriptorType = vk::DescriptorType::eStorageImage,
                                           .pImageInfo = &half_info},
                    vk::WriteDescriptorSet{.dstBinding = 10, .descriptorCount = 1,
                                           .descriptorType = vk::DescriptorType::eStorageBuffer,
                                           .pBufferInfo = &count_info},
                    // bbport (r52_follow-soft): the follow state
                    vk::WriteDescriptorSet{.dstBinding = 11, .descriptorCount = 1,
                                           .descriptorType = vk::DescriptorType::eStorageImage,
                                           .pImageInfo = &follow_prev_info},
                    vk::WriteDescriptorSet{.dstBinding = 12, .descriptorCount = 1,
                                           .descriptorType = vk::DescriptorType::eStorageImage,
                                           .pImageInfo = &follow_cur_info},
                    // bbport (r60_lamp-centred-window): the centred window's answers
                    vk::WriteDescriptorSet{.dstBinding = 13, .descriptorCount = 1,
                                           .descriptorType = vk::DescriptorType::eStorageImage,
                                           .pImageInfo = &answers_info}};
                // bbport (r92_lamp-shadow-colour): the colour image after the build's last (13; 14 with
                // the centred window's answers), as for the full-resolution builds
                const u32 half_written = half_with_answers ? 14u : 13u;
                std::array<vk::WriteDescriptorSet, 15> half_colour_writes{};
                std::copy_n(half_writes.begin(), half_written, half_colour_writes.begin());
                half_colour_writes[half_written] = vk::WriteDescriptorSet{
                    .dstBinding = half_written, .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &colour_info};
                const u32 half_pushed = colour_view ? half_written + 1u : half_written;
                const vk::WriteDescriptorSet* const half_push =
                    colour_view ? half_colour_writes.data() : half_writes.data();
                // bbport (r61_lamp-window-cost): a build and its bindings (the resolves' own build
                // or the pass's)
                const auto bind = [&](vk::Pipeline pipe, vk::PipelineLayout pipe_layout) {
                    cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipe);
                    cmdbuf.pushDescriptorSetKHR(
                        vk::PipelineBindPoint::eCompute, pipe_layout, 0,
                        vk::ArrayProxy<const vk::WriteDescriptorSet>(half_pushed, half_push)); // bbport (r92)
                };
                bind(half_pipe, half_pipe_layout);
                const vk::PipelineLayout resolve_push_layout = resolve_pipe ? resolve_pipe_layout : half_pipe_layout;
                push.first_light = table;
                push.light_count = tile_count;
                push.rect = covered;
                const u32 mode = base_word | (half_count ? ModeHalfCount : 0u); // bbport (r61): as before
                // bbport (r60_lamp-centred-window): split, each half as a trace and a resolve; the
                // second half's trace reads the block answers and the history the first half's
                // resolve wrote (HalfAnswer, a taken block's copy), so four dispatches. The
                // resolves count nothing (each pixel is counted once, by its trace).
                const u32 trace = split ? ModeTrace : 0u;
                const u32 resolve = (mode & ~ModeHalfCount) | ModeResolve;
                const u32 hx0 = u32(covered[0]) / 16, hy0 = u32(covered[1]) / 16;
                const u32 hx1 = (u32(covered[2]) + 15) / 16, hy1 = (u32(covered[3]) + 15) / 16;
                if (part <= 0) {
                    push.thickness_m = std::bit_cast<float>(mode | ModeHalfFirst | trace);
                    cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(Push), &push);
                    cmdbuf.dispatchBase(hx0, hy0, 0, hx1 - hx0, hy1 - hy0, 1);
                    EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                              Compute,
                                              vk::AccessFlagBits2::eShaderRead |
                                                  vk::AccessFlagBits2::eShaderWrite);
                }
                if (split && (part < 0 || part == 1)) {
                    if (resolve_pipe) { // bbport (r61_lamp-window-cost)
                        bind(resolve_pipe, resolve_pipe_layout);
                    }
                    push.thickness_m = std::bit_cast<float>(resolve | ModeHalfFirst);
                    cmdbuf.pushConstants(resolve_push_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(Push), &push);
                    cmdbuf.dispatchBase(hx0, hy0, 0, hx1 - hx0, hy1 - hy0, 1);
                    between();
                }
                const u32 gx0 = u32(covered[0]) / 8, gy0 = u32(covered[1]) / 8;
                const u32 gx1 = (u32(covered[2]) + 7) / 8, gy1 = (u32(covered[3]) + 7) / 8;
                if (part < 0 || part == 2) {
                    if (resolve_pipe && part < 0) { // bbport (r61_lamp-window-cost): the trace's build again
                        bind(half_pipe, half_pipe_layout);
                    }
                    push.thickness_m = std::bit_cast<float>(mode | ModeHalfFill | trace);
                    cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(Push), &push);
                    cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                    if (split) {
                        between();
                    }
                }
                if (split && (part < 0 || part == 3)) {
                    if (resolve_pipe) { // bbport (r61_lamp-window-cost)
                        bind(resolve_pipe, resolve_pipe_layout);
                    }
                    push.thickness_m = std::bit_cast<float>(resolve | ModeHalfFill);
                    cmdbuf.pushConstants(resolve_push_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(Push), &push);
                    cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                }
                if (part >= 0 && part != last_part) {
                    return; // bbport (r61_lamp-window-cost): what follows ends the last part
                }
                const vk::MemoryBarrier2 half_after{
                    .srcStageMask = Compute,
                    .srcAccessMask = vk::AccessFlagBits2::eShaderWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .dstAccessMask = vk::AccessFlagBits2::eMemoryRead |
                                     vk::AccessFlagBits2::eMemoryWrite};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &half_after});
                if (half_count) { // to the host (OnFrameEnd reads it); later counting waits
                    const vk::BufferCopy region{0, 0, HalfSlots * sizeof(u32)};
                    cmdbuf.copyBuffer(half_count_buffer, half_read_buffer, region);
                    EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eCopy,
                                              vk::AccessFlagBits2::eTransferWrite |
                                                  vk::AccessFlagBits2::eTransferRead,
                                              vk::PipelineStageFlagBits2::eHost | Compute,
                                              vk::AccessFlagBits2::eHostRead |
                                                  vk::AccessFlagBits2::eShaderRead |
                                                  vk::AccessFlagBits2::eShaderWrite);
                }
                return;
            }
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            if (use_rays) {
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                                            vk::ArrayProxy<const vk::WriteDescriptorSet>(ray_pushed, ray_push)); // bbport (r92)
            } else {
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            }
            if (use_rays) {
                push.first_light = table;
                push.light_count = tile_count;
                push.rect = covered;
                const u32 gx0 = u32(covered[0]) / 8, gy0 = u32(covered[1]) / 8;
                const u32 gx1 = (u32(covered[2]) + 7) / 8, gy1 = (u32(covered[3]) + 7) / 8;
                if (split) { // bbport (r60_lamp-centred-window): the trace, then the resolve
                    if (part <= 0) {
                        push.thickness_m = std::bit_cast<float>(base_word | ModeTrace);
                        cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push), &push);
                        cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                        between();
                    }
                    if (part < 0 || part == 1) {
                        // bbport (r61_lamp-window-cost): the resolves' own build, when there is one
                        if (resolve_pipe) {
                            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, resolve_pipe);
                            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, resolve_pipe_layout, 0,
                                                        vk::ArrayProxy<const vk::WriteDescriptorSet>(
                                                            ray_pushed, ray_push)); // bbport (r92)
                        }
                        push.thickness_m = std::bit_cast<float>(base_word | ModeResolve);
                        cmdbuf.pushConstants(resolve_pipe ? resolve_pipe_layout : layout,
                                             vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push), &push);
                        cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                    }
                } else {
                    cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push), &push);
                    cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                }
                batch.clear();
            }
            if (part >= 0 && part != last_part) {
                return; // bbport (r61_lamp-window-cost): what follows ends the last part
            }
            for (const Tile& tile : batch) {
                push.first_light = tile.first_light;
                push.light_count = tile.count;
                push.rect = tile.rect;
                cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push),
                                     &push);
                const u32 gx0 = u32(tile.rect[0]) / 8, gy0 = u32(tile.rect[1]) / 8;
                const u32 gx1 = (u32(tile.rect[2]) + 7) / 8, gy1 = (u32(tile.rect[3]) + 7) / 8;
                cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
            }
            const vk::MemoryBarrier2 after{
                .srcStageMask = Compute,
                .srcAccessMask = vk::AccessFlagBits2::eShaderWrite,
                .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .dstAccessMask = vk::AccessFlagBits2::eMemoryRead |
                                 vk::AccessFlagBits2::eMemoryWrite};
            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
        };
    if (parts == 0) {
        scheduler.RecordCrumb({.name = "Point shadows"},
                              [record = std::move(record)](vk::CommandBuffer cmdbuf) mutable { record(cmdbuf, -1); });
        return;
    }
    // bbport (r61_lamp-window-cost): the parts in order, one closure shared by them (it holds the
    // pass's words and tiles once); the marks are written where each part starts
    const auto shared = std::make_shared<decltype(record)>(std::move(record));
    for (int part = 0; part < parts; ++part) {
        if (part > 0) {
            EffectPass::Mark(part % 2 != 0 ? 61 : 6, part % 2 != 0 ? "point shadows: resolve" : "point shadows");
        }
        scheduler.RecordCrumb({.name = "Point shadows"},
                              [shared, part](vk::CommandBuffer cmdbuf) { (*shared)(cmdbuf, part); });
    }
}

}
