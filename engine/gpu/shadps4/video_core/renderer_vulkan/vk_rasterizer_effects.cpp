// SPDX-License-Identifier: GPL-3.0-or-later
#include <algorithm>
#include <bit>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <optional>
#include <string>
#include <array>         // bbport (r64_surface-probe)
#include <chrono>        // bbport (r64_surface-probe)
#include <ctime>         // bbport (r64_surface-probe)
#include <mutex>         // bbport (r64_surface-probe)
#include <unordered_map> // bbport (r64_surface-probe)
#include <vector>        // bbport (r64_surface-probe)
#include <atomic>        // bbport (r64b_surface-probe-more)
#include <memory>        // bbport (r64b_surface-probe-more)
#include <string_view>   // bbport (r64b_surface-probe-more)
#include <thread>        // bbport (r64b_surface-probe-more)
#include <unordered_set> // bbport (r64b_surface-probe-more)

#include <fmt/format.h>
#include "bbport_wind_felt_shelter.h" // bbport (r97g_shelter-haze-sparks)

#include "bbport_settings.h"
#include "bbport_toggles.h"
#include "bbport_sun_cascades.h"
#include <xxhash.h>
#include "engine/engine_state.h" // bbport (r112h_hang-not-the-hunter): the hunter's position
#include "engine/loading.h"
#include "bbport_test_goto_hang.h" // bbport (r112n_hang-teleport-camera, TOOL): BB_TEST_GOTO
#include "bbport_wind_lantern.h" // bbport (r112v_lantern-hangs)

#include "core/memory.h"
#include "shader_recompiler/ir/passes/cutout_analysis.h" // bbport (r50b_leaf-matcher)
#include "video_core/renderer_vulkan/rt_card_uv.h"           // bbport (r54_leaf-stage2)
#include "video_core/renderer_vulkan/vk_card_alpha.h" // bbport (r62_leaf-stage3)
#include "video_core/renderer_vulkan/vk_effect_shaders.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "engine/gx_objects.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
#include "video_core/renderer_vulkan/vk_bottle_cold_source_b177.h"
#if defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
#include "video_core/renderer_vulkan/vk_bottle_raw_apply_b180.h"
#endif
#endif
#include "video_core/renderer_vulkan/vk_reflection_first_retire.h"
#include "video_core/renderer_vulkan/vk_reflection_fragment_discard.h"
#if __has_include("bbport_live_knobs.h")
#include "bbport_live_knobs.h" // bbport (r89d_tree-twigs): the test tools' (r84) live knobs, when present
#define BB_WIND_TWIGS_LIVE 1
#else
#define BB_WIND_TWIGS_LIVE 0
#endif
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_shader_util.h"
#include "video_core/renderer_vulkan/vk_window_path_directional.h"
#include "video_core/renderer_vulkan/volumetric_occlusion.h"
#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)
#include "video_core/renderer_vulkan/rt_glass_find.h" // bbport (r86g_glint-find-bottles)
#include "video_core/renderer_vulkan/rt_glass_static.h" // bbport (r121b_glass-pane-hang)
#include "bbport_test_camera_run.h" // bbport (r120_test-camera-lookat, TOOL): BB_TEST_CAMERA, BB_TEST_WORLD_AT
#include "video_core/renderer_vulkan/vk_sewer_motion_observer.h"
#include "video_core/renderer_vulkan/vk_lamp_pane_probe.h"
#include "video_core/renderer_vulkan/lamp_flicker.h" // bbport (r96_lamp-flicker-colour)

namespace Vulkan {

namespace {
constexpr u64 ShadowResolveHash = 0xf55643de;
constexpr u64 ShadowBlurHash = 0x11ffdfb5;
constexpr u64 PointLightsFullHash = 0x9f9ef267;
constexpr u64 HdrPostHash = 0xccbf44a6;
constexpr u64 SceneTargetHash = 0x32e47788;

#ifdef BB_TEST_BOTTLE_CUT_SOURCE
namespace BottleSource = BottleCaustic::CutSource;
namespace BottleCold = BottleColdSource177;

BottleCold::Frame BottleCutFrame(const Rasterizer* owner, u32 request, Scheduler& scheduler,
                                 const SceneTargets& targets, const RtShadow& rt,
                                 const ObjectMotion& objects) {
    return {owner, request, BbStats::frame_number.load(std::memory_order_relaxed),
            BbEngine::Loading::Generation(), targets.Generation(), rt.WindowDiagnosticFrame(),
            objects.Frame(), scheduler.GetWorkSemaphore()->Handle(), BbEngine::Loading::ScreenUp()};
}

BottleSource::Camera BottleCutCamera(const CameraMotion& owner, std::array<float, 2> jitter) {
    const auto matrices = owner.PassMatrices();
    return matrices.valid ? BottleSource::Camera{matrices.view, matrices.proj, jitter}
                          : BottleSource::Camera{};
}

bool BottleCutNativeScope(const SceneTargets& targets) {
    return !BbEngine::Loading::ScreenUp() && SceneResolution::Native() == SceneResolution::Size{3840, 2160} &&
           targets.Size() == SceneResolution::Size{1920, 1080};
}

BottleCold::Image BottleCutImage(const SceneTargets& targets, VideoCore::ImageId id,
                                 const VideoCore::Image* image, bool depth) {
    if (!id || !image || image->binding.needs_rebind || !image->backing || !targets.EligibleScene(*image) ||
        bool(image->info.props.is_depth) != depth || image->info.resources != VideoCore::SubresourceExtent{1, 1} ||
        image->info.num_samples != 1 || image->backing->num_samples != 1) return {};
    return {id.index, image->image_uid, image->GetImage(), image->backing->image.allocation};
}

struct BottleCutBindings {
    BottleSource::Backing color{}, depth{};
};

BottleCutBindings BottleCutBoundAttachments(Scheduler& scheduler, const SceneTargets& targets,
                                           VideoCore::ImageId color_id, const VideoCore::Image& color,
                                           VideoCore::ImageId depth_id, const VideoCore::Image& depth) {
    const auto& state = scheduler.GetRenderState();
    if (!scheduler.IsRenderingWith(state) || state.width != 1920 || state.height != 1080 ||
        state.num_layers != 1) return {};
    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    const auto& cb = state.color_attachments[0];
    const auto& db = state.depth_stencil_attachment;
    BottleCutBindings result;
    if (state.num_color_attachments && cb.image_view &&
        cb.image_layout == vk::ImageLayout::eColorAttachmentOptimal) {
        result.color = BottleCaustic::ObserveCutBacking(targets, color_id, color, cb.image_view,
                           Stage::eColorAttachmentOutput, Access::eColorAttachmentRead | Access::eColorAttachmentWrite);
        if (result.color.layout != cb.image_layout) result.color = {};
    }
    if (db.has_depth && db.image_view &&
        db.image_layout == vk::ImageLayout::eDepthStencilAttachmentOptimal) {
        result.depth = BottleCaustic::ObserveCutBacking(targets, depth_id, depth, db.image_view,
                           Stage::eEarlyFragmentTests | Stage::eLateFragmentTests,
                           Access::eDepthStencilAttachmentRead | Access::eDepthStencilAttachmentWrite);
        if (result.depth.layout != db.image_layout) result.depth = {};
    }
    return result;
}
#endif

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
           EffectShaders::GtaoActive() || EffectShaders::SsrActive() ||
           LampFlicker::On(); // bbport (r96_lamp-flicker-colour): its light draws are looked at
}
}

void Rasterizer::EffectsEndLampBatch() {
    if (point_shadow->Apart()) {
        const auto jitter = upscaler->Jitter();
        point_shadow->EndApart(jitter[0] != 0.0f || jitter[1] != 0.0f);
    }
}

// bbport (r82_wind-stage1): BB_WIND_SHOW=1, read once at the first call: the "Wind:" line and
// the sun fog's "Wind fog:" line. Both callers sit behind the wind's on, so it is read only with
// BB_WIND=1.
static bool WindShow() {
    static const bool show = [] {
        const char* env = std::getenv("BB_WIND_SHOW");
        return env != nullptr && env[0] == '1';
    }();
    return show;
}

// bbport (r82_wind-stage1): the shared wind (bbport_wind.h), advanced by the steady clock each
// time EffectsOnFrameEnd runs (the display pass, while camera_motion->Enabled(): not with
// BB_UPSCALER=none unless BB_DEBUG_MOTION=1), only with BB_WIND=1. The environment is read once,
// at the first call, and its state said once (on or off): BB_WIND (on when it starts with 1),
// BB_WIND_DIR (deg, 0 = +x, 90 = +z, the way it blows toward), BB_WIND_SPEED (m/s) and
// BB_WIND_GUSTS; a missing, unreadable or non-finite number takes BbWind::DefaultDirection /
// DefaultSpeed / DefaultGusts, then BbWind::Sanitize applies the clamps (MaxSpeed, MaxGusts).
// With BB_WIND on, BB_WIND_SHOW (1: a "Wind:" line each time the wind time passes a multiple of
// 2 s) is read too. Without BB_WIND this returns after the static parameters' initialisation guard
// and one bool test: no clock read, the state stays as constructed. The sun fog reads the wind
// right before each Integrate (EffectsAfterDraw). The wind time is real time (steps clamped to
// 0.1 s), so it also runs in pause menus.
void Rasterizer::WindOnFrameEnd() {
    static const BbWind::Params params = [] {
        const auto number = [](const char* name, float fallback) {
            const char* env = std::getenv(name);
            if (env == nullptr || env[0] == 0) {
                return fallback;
            }
            char* end = nullptr;
            const float value = std::strtof(env, &end);
            return end != env && std::isfinite(value) ? value : fallback;
        };
        const char* on = std::getenv("BB_WIND");
        // bbport (r116b_wind-weather): the weather is on with the wind unless BB_WIND_WEATHER=0 or
        // BB_WIND_SPEED is set (a pinned speed for repeatable tests and clips)
        const char* weather_env = std::getenv("BB_WIND_WEATHER");
        const char* speed_env = std::getenv("BB_WIND_SPEED");
        const bool weather_wanted = !(weather_env != nullptr && weather_env[0] == '0') &&
                                    !(speed_env != nullptr && speed_env[0] != 0);
        BbWind::Params p{
            .on = on != nullptr && on[0] == '1',
            .direction_deg = number("BB_WIND_DIR", BbWind::DefaultDirection),
            .speed = number("BB_WIND_SPEED", BbWind::DefaultSpeed),
            .gusts = number("BB_WIND_GUSTS", BbWind::DefaultGusts),
            .wander = number("BB_WIND_WANDER", BbWind::Wander),
            .weather = on != nullptr && on[0] == '1' && weather_wanted,
            .weather_rate = double(number("BB_WIND_WEATHER_RATE", 1.0f)),
            .weather_at = double(number("BB_WIND_WEATHER_AT", 0.0f)),
        };
        p = BbWind::Sanitize(p);
        if (p.on) {
            BbReport::Printf("Wind (r82, BB_WIND=1): toward %.0f deg, %.2f m/s, gusts %.2f; the "
                             "sun fog drifts with it while the volumetric sunlight is on\n",
                             double(p.direction_deg), double(p.speed), double(p.gusts));
            BbReport::Printf("Wind (r116, BB_WIND=1): one heading for the clouds and the wind: toward "
                             "%.0f deg, wandering at most %.0f deg either way (BB_WIND_WANDER); the "
                             "clouds move at %.0fx the mean speed, gusts come from upwind; a Wind "
                             "(r116) line every 600 frames says what each follower read\n",
                             double(p.direction_deg), double(p.wander), double(BbWind::CloudRatio));
            if (p.weather) {
                BbReport::Printf("Wind (r116b, BB_WIND_WEATHER=1): the speed is the weather's, %.1f-%.1f m/s: "
                                 "mostly calm or light, now and then in-between (2-2.5), rarely strong; a new "
                                 "state about every %.0f s, clock x%.2f from %.0f s; gusts and the clouds "
                                 "follow; BB_WIND_SPEED or BB_WIND_WEATHER=0 pins it\n",
                                 double(BbWind::WeatherMin), double(BbWind::WeatherMax),
                                 BbWind::WeatherCell, p.weather_rate, p.weather_at);
            } else {
                BbReport::Printf("Wind (r116b): weather off (BB_WIND_WEATHER=0 or BB_WIND_SPEED set): the speed "
                                 "stays %.2f m/s\n", double(p.speed));
            }
        } else {
            BbReport::Printf("Wind (r82): off (BB_WIND is not 1); nothing drifts\n");
        }
        return p;
    }();
    if (!params.on) {
        return;
    }
    const bool show = WindShow();
    const auto now = std::chrono::steady_clock::now();
    const double seconds = wind_time == std::chrono::steady_clock::time_point{}
                               ? 0.0
                               : std::chrono::duration<double>(now - wind_time).count();
    wind_time = now;
    const double before = wind.Get().time;
    // bbport (r117_wind-shelter): the wind at the camera is the open wind times the share the
    // shelter field leaves there (1 without BB_WIND_SHELTER)
    wind.Advance(params, seconds, wind_shelter ? wind_shelter->CameraOpen() : 1.0f);
    const BbWind::Snapshot s = wind.Get();
    // bbport (r116_wind-one-source): every 600 wind steps one line: the shared heading and what each
    // follower read since the last one
    static std::uint32_t follower_steps = 0;
    if (++follower_steps % 600u == 0) {
        char followers[320];
        BbWind::FollowersText(s, followers, sizeof(followers));
        BbReport::Printf("%s\n", followers);
        { // bbport (r97g_shelter-haze-sparks): what the haze and the sparks read of the shelter
            char felt[320];
            if (BbWindFelt::ReportText(felt, sizeof(felt))) {
                BbReport::Printf("%s\n", felt);
            }
        }
        if (BbWindGame::CutOn()) { // bbport (r122_game-wind-drive)
            char game[256];
            BbWindGame::ReportText(game, sizeof(game));
            BbReport::Printf("%s\n", game);
        }
        if (BbWindParticles::On()) { // bbport (r122b_game-particles-follow-wind)
            char particles[320];
            BbWindParticles::ReportText(particles, sizeof(particles));
            BbReport::Printf("%s\n", particles);
        }
    }
    // bbport (r116b_wind-weather): one line each WeatherLine of weather clock (a minute of weather; at
    // BB_WIND_WEATHER_RATE=20 every 3 s): the state, the speed now with its mean and range, the gust
    // strength, the clouds' speed
    static BbWind::WeatherWindow weather_window;
    weather_window.Add(s.speed);
    if (std::floor(BbWind::ClockOf(s, s.time) / BbWind::WeatherLine) !=
        std::floor(BbWind::ClockOf(s, before) / BbWind::WeatherLine)) {
        char weather[320];
        BbWind::WeatherText(s, weather_window, cloud_shadow ? cloud_shadow->Velocity() : s.cloud_speed, weather,
                            sizeof(weather));
        BbReport::Printf("%s\n", weather);
    }
    if (show && std::floor(s.time / 2.0) != std::floor(before / 2.0)) {
        BbReport::Printf("Wind: toward %.0f deg (x %.2f z %.2f), %.2f m/s, gust %.2f, offsets %.2f %.2f "
                         "%.2f / %.2f %.2f %.2f\n",
                         double(s.direction_deg), double(s.dir_x), double(s.dir_z), double(s.speed),
                         double(s.gust), double(s.off1[0]), double(s.off1[1]), double(s.off1[2]),
                         double(s.off2[0]), double(s.off2[1]), double(s.off2[2]));
    }
}

// bbport (r89d_tree-twigs): BB_WIND_TWIGS now: with the test tools' live knobs (r84) the value in the
// live knobs file, else the environment's, read when the knob is first asked. The shaders carry the twig
// code only if the knob was above 0 at the start; a live 0 gives the twigs a gain of 0 at the next view
// (the trees then stand still, not as r89c has them: that is BB_WIND_TWIGS=0 at the start).
#if BB_WIND_TWIGS_LIVE
static float TwigsParseLive(const char* text) {
    return BbWindTwigs::ParseTwigs(text);
}
#endif

static float WindTwigsNow() {
#if BB_WIND_TWIGS_LIVE
    static BbLiveKnobs::Knob<float> knob{"BB_WIND_TWIGS", TwigsParseLive};
    return knob.Get();
#else
    return BbWindTwigs::KnobOnce().twigs;
#endif
}

// bbport (r89p_twigs-really-move, TOOL): BB_WIND_FREEZE with the test tools' live knobs (r84): "1" freezes every new view's wind at a
// full gust front (BbWindTrees::FreezeView), anything else or no text leaves it as it is. Read at each new view. Without the tools'
// header: the environment.
#if BB_WIND_TWIGS_LIVE
static bool FreezeParseLive(const char* text) {
    return text != nullptr && text[0] == '1' && text[1] == 0;
}

static bool WindFreezeNow() {
    static BbLiveKnobs::Knob<bool> knob{"BB_WIND_FREEZE", FreezeParseLive};
    return knob.Get();
}
#else
static bool WindFreezeNow() {
    return BbWindTrees::FreezeEnv();
}
#endif

// bbport (r112k_hang-lantern-verdict, TOOL): BB_WIND_HANG_PUSH with the test tools' live knobs (r84): "0" gives
// every hang word a ramp of 0 (nothing pushed; the shaders and everything else as they are), anything else or no
// text the push as it is. Read in WindHangWord only. Without the tools' header: always on. BB_WIND_HANG itself is
// read once (it decides pipeline keys and shaders) and cannot be live.
#if BB_WIND_TWIGS_LIVE
static bool HangPushParseLive(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == 0);
}

static bool WindHangLiveOn() {
    static BbLiveKnobs::Knob<bool> knob{"BB_WIND_HANG_PUSH", HangPushParseLive};
    return knob.Get();
}
#else
static bool WindHangLiveOn() {
    return true;
}
#endif

// bbport (r112m_hang-close-proof, TOOL): BB_WIND_HANG_STATIC_GAIN now: with the test tools' live knobs (r84) the value in
// the live knobs file (set:/unset:), else the environment's, read when the knob is first asked. Read in WindHangWord only.
#if BB_WIND_TWIGS_LIVE
static float HangGainParseLive(const char* text) {
    return BbWindHangFind::ParseGain(text);
}

static float WindHangGainNow() {
    static BbLiveKnobs::Knob<float> knob{"BB_WIND_HANG_STATIC_GAIN", HangGainParseLive};
    return knob.Get();
}
#else
static float WindHangGainNow() {
    return BbWindHangFind::GainKnob();
}
#endif

// bbport (r89g_twigs-proof, TOOL): the draws of each twig-taken stream since the last proof lines: how many, how
// many on a pipeline whose key has the sway bit, on how many distinct pipelines (at most 4 are told apart).
struct TwigProofDraws {
    u64 draws = 0;
    u64 patched = 0;
    u64 gbuffer = 0; // bbport (r89l_twigs-palette-move): of the draws, those of the G-buffer pass
    u32 pipelines = 0;
    std::array<const void*, 4> seen{};
};
static std::unordered_map<u64, TwigProofDraws> twig_proof_draws;

static void TwigProofNote(u64 stream, const GraphicsPipeline* pipeline, bool gbuffer) {
    TwigProofDraws& d = twig_proof_draws[stream];
    ++d.draws;
    d.gbuffer += gbuffer ? 1 : 0; // bbport (r89l_twigs-palette-move)
    d.patched += (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::Sway) != 0 ? 1 : 0;
    bool known = false;
    for (u32 i = 0; i < d.pipelines; ++i) {
        known = known || d.seen[i] == pipeline;
    }
    if (!known && d.pipelines < d.seen.size()) {
        d.seen[d.pipelines++] = pipeline;
    }
}

// bbport (r89_wind-foliage-sway): the sway word (BbWindSway::PackWord) of a skinned draw of a
// pipeline with the Sway bit: 0 unless RtShadow takes the draw's position stream (the fetch's
// semantic 0: address and bytes, as EffectsCaptureDraw takes it) for a plant (LonePlant: needs
// ray tracing), the draw's 864-byte camera constants give a camera, this frame has room for its
// view (BbWindSway::Views: the first views' words are written into the ring's frame slot,
// ObjectMotion::FrameSlot, which the GPU is done with since ObjectMotion::OnFrameStart) and the
// stream has or gets a base slot (a slot new to its stream gets its key reset here; the GPU
// lowers it from then on). The wind is r82's state as last advanced. On the thread recording draws.
u32 Rasterizer::WindSwayWord(const GraphicsPipeline* pipeline, int small_palette,
                             bool hang_static) {
    const auto& knob = BbWindSway::KnobOnce();
    ++sway_stats.draws;
    u32* const words = object_motion->SwayWords();
    if (!knob.on || words == nullptr) {
        ++sway_stats.no_region;
        return 0;
    }
    if (!rt_shadow->Wanted()) {
        ++sway_stats.no_rt;
        return 0;
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto& fetch = pipeline->GetFetchShader();
    u64 positions = 0;
    u32 positions_size = 0;
    u32 positions_stride = 0;     // bbport (r89e_twigs-big-trees): for the static cut-outs
    bool positions_floats = false; // (float vectors: FarShare reads them for the log)
    if (fetch) {
        for (const auto& attribute : fetch->attributes) {
            if (attribute.semantic == 0) {
                const auto stream = attribute.GetSharp(vs);
                positions = stream.base_address;
                positions_size = stream.GetSize();
                positions_stride = stream.GetStride();
                positions_floats = (stream.GetDataFmt() == AmdGpu::DataFormat::Format32_32_32 ||
                                    stream.GetDataFmt() == AmdGpu::DataFormat::Format32_32_32_32) &&
                                   stream.GetNumberFmt() == AmdGpu::NumberFormat::Float;
                break;
            }
        }
    }
    // bbport (r112_wind-more-things): or, with BB_WIND_HANG=1, a hanging thing (WindHangVerdict)
    // bbport (r89e_twigs-big-trees): small_palette 0 or 1: a static cut-out (Kind::Other) candidate for the
    // twigs only (WindTwigSmall), never a plant or a hanging thing; -1: a skinned draw, as before
    // bbport (r89j_twigs-pick-trees): BB_WIND_TWIGS_TREES: a candidate draw (static or GPU palette, no hanging mesh) is a
    // tree when its own vertices are tree-shaped and the camera is outdoors; its vertex range is then its mesh
    // (positions and positions_size become its key and size). Anything else of a candidate gets no word.
    // bbport (r112s_hang-bracket-move): a draw of a post lantern's position stream (BB_WIND_HANG_POST) has its own word below (WindPostWord):
    // it is no plant, no tree of the twigs and no hanging thing of r112's judges
    const bool post = BbWindHang::PostOn() && BbWindHang::PostMatches(positions_size, positions_stride);
    if (small_palette >= 0 && !hang_static && !post && BbWindTwigs::TreesWanted() &&
        !WindTreesDraw(positions, positions_size, positions_stride, positions_floats,
                       // bbport (r89k_twigs-opaque-word): an opaque draw (no discard) may be a limb piece of a tree
                       pipeline->GetStages()[u32(Shader::SwStage::Fragment)] != nullptr &&
                           !pipeline->GetStages()[u32(Shader::SwStage::Fragment)]->has_discard)) {
        return 0;
    }
    const bool plant = !post && small_palette < 0 && rt_shadow->LonePlant(positions, positions_size);
    // bbport (r89d_tree-twigs): or a sun-drawn skinned stream that measures as a tree (WindTwigTree)
    const bool tree = !plant && !post && !hang_static && (small_palette >= 0 // (r112i: a static hanging mesh)
                                     ? WindTwigSmall(pipeline, positions, positions_size,
                                                     positions_stride, positions_floats,
                                                     small_palette != 0)
                                     : WindTwigTree(positions, positions_size));
    hang_judge = false; // bbport (r112f_hang-gpu-judge): WindHangVerdict sets it for a candidate
    bool hang = !plant && !tree && !post && (small_palette < 0 || hang_static) && // (r89e: no static cut-out)
                WindHangVerdict(pipeline, positions, positions_size, hang_static, positions_stride);
    const bool judge = hang_judge && !hang && !plant && !tree; // (r112f) its keys decide
    // bbport (r112q_hang-bracket-route, TOOL): BB_WIND_HANG_FORCE: a skinned draw of a named vertex shader (or all) that no rule took is given a
    // hang word all the same, with no judge (WindHangForceWord): the proof of the shader chain, whatever the judges say
    const bool force = !plant && !tree && !hang && !judge && !post && small_palette < 0 &&
                       BbWindHangRoute::ForceMatches(static_cast<u32>(vs.pgm_hash & 0xffffffffu));
    if (!plant && !hang && !tree && !judge && !force && !post) {
        return 0;
    }
    sway_stats.plants += plant ? 1 : 0;
    const float* constants = nullptr;
    for (const auto& resource : vs.buffers) {
        if (resource.IsSpecial()) {
            continue;
        }
        const auto buffer = resource.GetSharp(vs);
        if (buffer.Valid() && buffer.GetSize() == BbWindSway::ConstantsBytes &&
            memory->IsValidGpuMapping(buffer.base_address, 0) &&
            memory->ClampRangeSize(buffer.base_address, BbWindSway::ConstantsBytes) ==
                BbWindSway::ConstantsBytes) {
            constants = reinterpret_cast<const float*>(buffer.base_address);
        }
    }
    if (constants == nullptr) {
        ++sway_stats.no_camera;
        return 0;
    }
    const u64 frame = object_motion->Frame();
    const u32 frame_slot = object_motion->FrameSlot();
    if (frame != sway_frame) {
        sway_frame = frame;
        sway_views = 0;
    }
    const BbWindSway::ViewKey key = BbWindSway::KeyOf(constants);
    u32 view = 0;
    while (view < sway_views && !BbWindSway::SameKey(sway_keys[view], key)) {
        ++view;
    }
    const BbWind::Snapshot snapshot = wind.Get();
    if (view == sway_views) {
        if (sway_views == BbWindSway::Views) {
            ++sway_stats.views_full;
            return 0;
        }
        BbWindSway::Camera camera;
        if (!BbWindSway::CameraOf(constants, camera)) {
            ++sway_stats.no_camera;
            return 0;
        }
        std::array<float, BbWindSway::ViewWords> filled{};
        BbWindSway::FillView(camera, snapshot, knob.gusts, knob.scale, filled.data());
        BbWind::Use(BbWind::Follower::Plants, snapshot, snapshot.wind); // bbport (r116)
        // bbport (r89b_wind-sway-ripple): the ripple's words (left 0 with BB_WIND_SWAY_RIPPLE=0)
        // bbport (r89c_wind-lean): the lean's words (FillLean) unless BB_WIND_SWAY_STYLE=wave
        if (BbWindSway::LeanKnobOnce().lean
                ? BbWindSway::FillLean(sway_ripple, camera, snapshot, knob.gusts, knob.scale,
                                       BbWindSway::RippleKnobOnce(), BbWindSway::LeanKnobOnce(),
                                       filled.data())
                : BbWindSway::FillRipple(sway_ripple, camera, snapshot, knob.gusts, knob.scale,
                                         BbWindSway::RippleKnobOnce(), filled.data())) {
            ++sway_stats.rippled_views;
        }
        if (BbWindTwigs::On()) { // bbport (r89d_tree-twigs): RippleD.z: the twigs' gain (not the trees' Ta)
            filled[BbWindSway::RippleD + 2] = BbWindTwigs::Gain(WindTwigsNow());
        }
        if (WindFreezeNow()) { // bbport (r89p_twigs-really-move, TOOL): the view's wind frozen at a full gust front
            BbWindTrees::FreezeView(filled.data());
            static bool freeze_said = false;
            if (!freeze_said) {
                freeze_said = true;
                char freeze_text[512];
                BbWindTrees::FreezeOnceText(freeze_text, sizeof(freeze_text));
                BbReport::Printf("%s\n", freeze_text);
            }
        }
        std::memcpy(words + BbWindSway::ViewAt(frame_slot, view), filled.data(), sizeof(filled));
        if (view == 0 && BbWindTwigs::ProofOn() && BbWindTwigs::PushOn()) { // bbport (r89h_twigs-alive, TOOL)
            BbWindTwigs::ProofLagStep(words, filled.data()); // the front phases of 15 frames ago, for the change counters
        }
        sway_keys[view] = key;
        ++sway_views;
    }
    const auto taken = sway_slots.Take(positions, positions_size, frame, snapshot.time);
    if (!taken.ok) {
        ++sway_stats.no_slot;
        return 0;
    }
    if (taken.reset) {
        words[BbWindSway::CrownAt + taken.slot] = BbWindSway::ResetKey; // bbport (r89c)
        BbWindTwigs::ResetSlot(words, taken.slot); // bbport (r89d_tree-twigs): the box keys
        words[BbWindSway::BaseAt + taken.slot] = BbWindSway::ResetKey;
        if (BbWindHang::KnobOnce().on) { // bbport (r112c): the top keys exist only with BB_WIND_HANG
            words[BbWindHang::TopAt + taken.slot] = BbWindSway::ResetKey; // bbport (r112)
        }
    }
    if (post) { // bbport (r112s_hang-bracket-move): a post lantern's word (the keys fill, then the lean)
        return WindPostWord(words, frame_slot, view, taken.slot, taken.reset, positions, positions_size, positions_stride, frame, snapshot);
    }
    if (tree && BbWindTwigs::ProofOn()) { // bbport (r89g_twigs-proof, TOOL): which pipelines draw it
        TwigProofNote(positions, pipeline, gbuffer_draw);
    }
    if (tree) { // bbport (r89d_tree-twigs): its word (WindTwigWord), counted in its line
        const u32 tree_word = WindTwigWord(words, frame_slot, view, taken, positions, positions_size, frame,
                                           snapshot.time, small_palette >= 0);
        // bbport (r89l_twigs-palette-move, TOOL): with the proof knob a G-buffer draw's word has PassBit (the
        // lifter's offset counters keep the G-buffer's vertex runs apart from the other passes')
        return tree_word != 0 && gbuffer_draw && BbWindTwigs::ProofOn() ? (tree_word | BbWindTwigs::PassBit) : tree_word;
    }
    if (force) { // bbport (r112q_hang-bracket-route, TOOL): the word of BB_WIND_HANG_FORCE
        return WindHangForceWord(words, frame_slot, view, taken.slot, snapshot);
    }
    if (judge) { // bbport (r112f_hang-gpu-judge): the GPU's keys say whether it stands still
        // bbport (r112h_hang-not-the-hunter): a give-up holds the stream for a long time (0: r112g's)
        hang_box.SetKeylessHold(BbWindHangActors::KnobOnce().on
                                    ? BbWindHangActors::KeylessHoldFrames
                                    : std::uint64_t{0});
        switch (hang_box.Step(positions, positions_size, taken.slot, taken.reset, frame, words)) {
        case BbWindHangStill::BoxState::Judging: { // a hang word with no motion: the keys fill
            const u32 word = BbWindHang::HangWord(frame_slot, view, taken.slot, 0);
            if (BbWindHangActors::KnobOnce().on) {
                // bbport (r112h_hang-not-the-hunter): what this draw had, for the give-up's facts
                const u32* const view_words = words + BbWindSway::ViewAt(frame_slot, view);
                BbWindHangActors::Facts facts;
                facts.vs = static_cast<u32>(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash &
                                            0xffffffffu);
                facts.size = positions_size;
                facts.stride = positions_stride;
                facts.slot = taken.slot;
                facts.view = view;
                facts.views = sway_views;
                facts.word = word;
                facts.cam[0] = std::bit_cast<float>(view_words[BbWindSway::WindE + 2]);
                facts.cam[1] = std::bit_cast<float>(view_words[BbWindSway::WindA + 2]);
                facts.cam[2] = std::bit_cast<float>(view_words[BbWindSway::WindE + 3]);
                facts.floats = positions_floats;
                facts.frame = frame;
                hang_actors.Fact(positions, facts);
            }
            return word;
        }
        case BbWindHangStill::BoxState::Still:
            if (!WindHangActorsClear(positions, frame, hang_static)) { // bbport (r112h, r112i)
                return 0;
            }
            ++hang_stats.still;
            hang = true;
            break;
        case BbWindHangStill::BoxState::Moved:
            if (BbWindHang::Entry* const moved = hang_book.Find(positions)) {
                moved->moving = true;
                if (moved->why_moving == 0) { // bbport (r112n_hang-teleport-camera): the first reason is kept
                    moved->why_moving = 3;
                }
            }
            ++hang_stats.moving;
            return 0;
        }
    }
    if (hang) { // bbport (r112_wind-more-things): its word (WindHangWord), counted in its lines
        u32 hang_word = WindHangWord(words, frame_slot, view, taken.slot, taken.reset, positions, frame,
                                     snapshot);
        // bbport (r112j_hang-static-verts): a static hanging thing's push is scaled while the camera is under a
        // roof by r117's field (BB_WIND_HANG_STATIC_ROOF; RoofScale: the roof knob at or under the indoor share,
        // 1 from 0.5 of the wind open); the GPU also scales every vertex by the field at the vertex
        if (hang_static && hang_word != 0 && wind_shelter != nullptr &&
            BbWindHangFind::RoofKnob() < 1.0f) {
            const float scale = BbWindHangFind::RoofScale(
                BbWindHangFind::RoofKnob(), BbWindHangActors::KnobOnce().indoor, wind_shelter->CameraOpen());
            if (scale < 1.0f) {
                ++hang_find_stats.roof_words;
                hang_find_stats.roof_least = std::min(hang_find_stats.roof_least, scale);
            } else {
                ++hang_find_stats.full_words;
            }
            hang_word = BbWindHangFind::ScaleRamp(hang_word, scale);
        }
        return hang_word;
    }
    ++sway_stats.swayed;
    sway_stats.ramping += taken.ramp < 255 ? 1 : 0;
    return BbWindSway::PackWord(frame_slot, view, taken.slot, taken.ramp);
}

// bbport (r112_wind-more-things): BB_WIND_HANG=1 (bbport_wind_hang.h): a skinned draw of a sway
// pipeline that is no plant is a hanging thing's when RtShadow takes its position stream for one a
// sun shadow pass draws (SunSkinned) and the Book finds the bytes of its skeleton palettes (stride
// 16, Motion's Skeleton size) the same on StillFrames frames and never others; a palette the GPU
// writes (not bound in place) or that is not mapped makes it moving. A stream the Book settled for
// good (moving, or measured out of height) is not hashed again. On the thread recording draws.
bool Rasterizer::WindHangVerdict(const GraphicsPipeline* pipeline, u64 positions,
                                 u32 positions_size, bool hang_static, u32 stride) {
    if (!BbWindHang::KnobOnce().on) {
        return false;
    }
    ++hang_stats.draws;
    if (BbWindHangProbe::On() && !hang_static) { // bbport (r112b_hang-probe, TOOL): every skinned draw
        WindHangProbeSkin(pipeline, positions, positions_size);
    }
    if (hang_static) { // bbport (r112i_hang-find-lanterns): an opaque static mesh: its box, no sun pass
        if (!BbWindHangStill::BoxAvailable() || object_motion->SwayWords() == nullptr) {
            ++hang_find_stats.no_keys; // only the GPU's keys can judge a mesh with no palette
            return false;
        }
        if (!WindHangStaticAllowed(positions, positions_size, stride, object_motion->Frame(),
                                   pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash)) {
            return false;
        }
    } else if (!rt_shadow->SunSkinned(positions, positions_size)) {
        ++hang_stats.no_sun;
        return false;
    }
    const u64 frame = object_motion->Frame();
    if (hang_book.Settled(positions, positions_size, frame)) {
        // bbport (r112e_hang-taken): a stream settled as moving or as unread is judged afresh after
        // RejudgeFrames, in both books, unless it moved far (a character) or has too many bones
        // bbport (r112f_hang-gpu-judge): and the GPU's keys' verdict first: a stream settled by its
        // height stands, one whose box grew 0.25 m or more is a character for good, one that grew
        // less is due again after RejudgeFrames (BoxBook::Due), with a new window
        const BbWindHang::Entry* const known = hang_book.Find(positions);
        const bool by_height = known != nullptr && !known->moving && known->judged && !known->fits;
        // bbport (r112g_hang-judge-settles): a stream the GPU judge holds as moving (a verdict, or
        // a give-up) is due when the judge says so (BoxBook::Due); the palette book's Due decides
        // only the others (it fired at once for a stream whose palette was never read, so a
        // give-up was forgotten the next frame and the stream cycled for ever)
        // bbport (r112q_hang-bracket-route): a stream the GPU box judges in place of its palette (box_only) is no character for good when its box
        // grew 0.25 m: a camera turn brings places of the mesh into view and the union its keys span grows (b64: pushes before the look-up, none
        // after it). It is judged again BB_WIND_HANG_BOX_RETRY frames after it was found moving (0: r112p's rule)
        const std::uint64_t retry = BbWindHangGpu::BoxRetry();
        const bool soft = retry != 0 && known != nullptr && known->box_only != 0;
        if (by_height || (!soft && hang_box.Final(positions)) ||
            (hang_box.HoldsMoved(positions)
                 ? !(soft ? hang_box.DueSoft(positions, frame, retry) : hang_box.Due(positions, frame))
                 : !hang_still.Due(positions, frame))) {
            ++hang_stats.settled;
            return false;
        }
        hang_box.Forget(positions);
        if (BbWindHang::Entry* const settled = hang_book.Find(positions)) {
            *settled = BbWindHang::Entry{};
        }
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    // bbport (r112d_hang-still-test): the first Skeleton-size palette (stride 16) is judged by
    // its content relative to its pivot bone, within a tolerance (BbWindHangStill), not by a
    // hash of its bytes: the game writes palettes to a ring (the address changes on every draw)
    // and float noise changed a hash. The reader's tests are r112's, in its order; the one that
    // refuses is kept (Why).
    const unsigned char* palette = nullptr;
    u32 palette_size = 0;
    bool in_place = false;
    bool forced = false; // bbport (r112e_hang-taken): read although the GPU wrote its page
    u64 palette_address = 0; // bbport (r112p_hang-gpu-palette-lanterns): the palette's address and the buffer cache's word on its pages
    bool palette_modified = false;
    BbWindHangStill::Why why = BbWindHangStill::Why::None;
    for (const auto& resource : vs.buffers) {
        if (resource.IsSpecial()) {
            continue;
        }
        const auto buffer = resource.GetSharp(vs);
        const u32 size = buffer.GetSize();
        if (!buffer.Valid() || buffer.GetStride() != 16 ||
            Motion::ClassifyBuffer(size) != Motion::BufferRole::Skeleton) {
            continue;
        }
        palette_size = size;
        palette_address = buffer.base_address; // bbport (r112p_hang-gpu-palette-lanterns)
        const bool gpu = buffer_cache.IsRegionGpuModified(buffer.base_address, size);
        palette_modified = gpu;
        in_place = gpu && buffer_cache.IsInPlace(buffer.base_address, size);
        // bbport (r112e_hang-taken): BB_WIND_HANG_READ_GPU=1 (a test setting) reads it all the same
        forced = gpu && !in_place && BbWindHangStill::ReadFlagged();
        if (gpu && !in_place && !forced) {
            why = BbWindHangStill::Why::GpuWritten;
        } else if (!memory->IsValidGpuMapping(buffer.base_address, 0)) {
            why = BbWindHangStill::Why::NotMapped;
        } else if (memory->ClampRangeSize(buffer.base_address, size) != size) {
            why = BbWindHangStill::Why::Short;
        } else {
            palette = reinterpret_cast<const unsigned char*>(buffer.base_address);
        }
        break;
    }
    const BbWindHangStill::Result content =
        hang_static ? BbWindHangStill::Result::Same // (r112i: no palette: the GPU's keys judge)
                    : hang_still.Judge(positions, palette_size, palette, why, in_place, frame, forced);
    // bbport (r112f_hang-gpu-judge): with the sway's box keys (BB_WIND_TWIGS on) a palette the CPU
    // cannot read (the GPU wrote it) is no objection: the GPU's keys judge the stream
    // (WindSwayWord, hang_box); a palette it can read must still be still, as before
    // bbport (r112p_hang-gpu-palette-lanterns): the stream's palette entry and whether the sway keys exist, read once
    const BbWindHangStill::Entry* const palette_entry = hang_static ? nullptr : hang_still.Find(positions);
    const bool box_keys = BbWindHangStill::BoxAvailable() && object_motion->SwayWords() != nullptr;
    bool gpu = box_keys && (hang_static || BbWindHangStill::GpuJudgeable(palette_entry, content));
    // bbport (r112p_hang-gpu-palette-lanterns): a stream the palette test refuses (its content moved, or a palette that could not
    // be read, up to BB_WIND_HANG_BOX_BONES bones) is judged by the GPU's box all the same: the box needs no palette, r112f's judge
    // decides (a mover's box grows), and the stream is pushed like a static lantern (box_only: WindHangActorsClear, WindHangWord).
    // The census says what the refused streams are; the first GPU-written palettes have their pages watched for the shader that
    // writes them (BindBuffers). BB_WIND_HANG_BOXJUDGE=0: none of the routing (r112o)
    std::uint8_t box_only = 0;
    if (!hang_static && content != BbWindHangStill::Result::Same) {
        const bool box_ok = box_keys && BbWindHangGpu::BoxOn() &&
                            BbWindHangGpu::BoxJudgeable(palette_entry, content, BbWindHangGpu::BoxBones(),
                                                        BbWindHangGpu::ModeOnce() == BbWindHangGpu::Mode::All,
                                                        // bbport (r112r_hang-bracket-judge): a stream with no skeleton-size palette (the lanterns')
                                                        BbWindHangGpu::NopalOn() && hang_gpu_census.NopalRoom(positions));
        BbWindHangGpu::Item refused;
        refused.stream = positions;
        refused.address = palette_address;
        refused.size = palette_size;
        refused.bones = palette_entry != nullptr ? palette_entry->bones : 0u;
        refused.kind = BbWindHangGpu::KindOf(palette_entry, content);
        refused.modified = palette_modified;
        refused.in_place = in_place;
        refused.box = box_ok;
        if (hang_gpu_census.Note(refused) && refused.kind == BbWindHangGpu::Kind::Gpu && !in_place) {
            hang_gpu_watch.Add(refused.address, refused.size, refused.bones, positions);
        }
        if (box_ok) {
            gpu = true;
            box_only = static_cast<std::uint8_t>(content == BbWindHangStill::Result::Moved ? 2 : 1);
            ++hang_gpu_stats.box_draws;
        } else if (!gpu) {
            ++hang_gpu_stats.turned_away;
        }
    }
    const bool still = content == BbWindHangStill::Result::Same || gpu;
    const BbWindHang::Verdict verdict =
        hang_book.Note(positions, positions_size, 0, still, frame, vs.pgm_hash,
                       content == BbWindHangStill::Result::Moved ? std::uint8_t{5} : std::uint8_t{1}, box_only);
    // bbport (r112g_hang-judge-settles): the GPU judge is the judge: it does not wait for
    // StillFrames frames of still palettes first (its own keys take BoxJudgeFrames +
    // BoxStillFrames)
    if (gpu && verdict == BbWindHang::Verdict::Waiting) {
        hang_judge = true;
        return false;
    }
    switch (verdict) {
    case BbWindHang::Verdict::Still:
        if (gpu) { // the CPU would take it: the GPU's keys say whether (WindSwayWord)
            hang_judge = true;
            return false;
        }
        ++hang_stats.still;
        return true;
    case BbWindHang::Verdict::Moving:
        ++hang_stats.moving;
        return false;
    case BbWindHang::Verdict::Unfit:
        ++hang_stats.unfit;
        return false;
    case BbWindHang::Verdict::Waiting:
        break;
    }
    ++hang_stats.waiting;
    return false;
}

// bbport (r112h_hang-not-the-hunter): a stream whose box keys first read as still in this GPU-judge
// window (once a window: its answer is kept): may it hang? Not when its palette has more bones than a
// lantern's (a figure's rig: the hunter's gear pieces have 28), not when its world box lies on the hunter
// (BbEngine::world_player_position), not when it is not placed (no box keys) or the hunter is unread, not
// when the camera is indoors by r117's field (CameraOpen). A refused stream is held as moving
// (BoxBook::Reject), judged again later with a new window. See bbport_wind_hang_actors.h. On the thread
// recording draws; BB_WIND_HANG_ACTORS=0: true at once (r112g).
bool Rasterizer::WindHangActorsClear(u64 positions, u64 frame, bool hang_static) {
    namespace A = BbWindHangActors;
    const A::Knobs& knobs = A::KnobOnce();
    if (!knobs.on) {
        return !hang_static; // bbport (r112i): a static mesh hangs only under the hunter and indoor rules
    }
    const BbWindHangStill::BoxEntry* const box = hang_box.Find(positions);
    if (box != nullptr && hang_actors.Cleared(positions, box->started)) {
        return true;
    }
    A::Hunter& hunter = hang_actors.hunter;
    if (hunter.frame != frame) { // the hunter, once a frame at most, only when a stream is tested
        hunter.frame = frame;
        float pos[3] = {};
        hunter.known = BbEngine::world_player_position(pos) && A::Finite3(pos);
        if (hunter.known) {
            hunter.x = pos[0];
            hunter.y = pos[1];
            hunter.z = pos[2];
            ++hang_actors.hunter_read;
        } else {
            ++hang_actors.hunter_unread;
        }
    }
    const BbWindHangStill::Entry* const palette = hang_still.Find(positions);
    const unsigned bones = palette != nullptr ? palette->bones : 0u;
    const bool have_field = wind_shelter != nullptr;
    const float open = have_field ? wind_shelter->CameraOpen() : 1.0f;
    float side = -1.0f;
    // bbport (r112i): a static mesh has no palette: one bone stands in for the figure rule
    BbWindHang::Entry* const entry = hang_book.Find(positions);
    // bbport (r112p_hang-gpu-palette-lanterns): a stream the GPU box judges in place of its palette has no bone count to test (an
    // unread palette's V# size is a capacity, a moving one's rig is not what the game draws it with): the one-bone stand-in of the
    // static meshes; the hunter's gear is kept off by the NEAR rule, the box and the indoor rule as before
    const bool box_only = entry != nullptr && entry->box_only != 0;
    const A::Why why =
        A::Judge(knobs, box, (hang_static || box_only) ? 1u : bones, hunter, open, have_field, &side);
    A::Seen seen;
    seen.vs = entry != nullptr ? static_cast<u32>(entry->vs & 0xffffffffu) : 0u;
    seen.bones = bones;
    if (box != nullptr) {
        seen.height = box->snap.crown - box->snap.base;
        seen.top = box->snap.crown;
        seen.window = box->started;
    }
    seen.side = side;
    seen.why = why;
    seen.frame = frame;
    hang_actors.Note(positions, seen);
    if (why == A::Why::Ok) {
        return true;
    }
    hang_box.Reject(positions, frame, A::HoldOf(why));
    if (entry != nullptr) {
        entry->moving = true;
        if (entry->why_moving == 0) { // bbport (r112n_hang-teleport-camera): r112h's rule, its number
            entry->why_moving = 4;
            entry->moved_after = static_cast<u32>(why);
        }
    }
    return false;
}

// bbport (r112i_hang-find-lanterns): the ray traced scene's world boxes, read from its entries (the sun VSM's
// box or the still check's bounds, RtShadow::WindHangFindBoxes) when the set is older than RefreshFrames
// frames, for the static hanging things' verdicts and the survey. On the thread recording draws.
void Rasterizer::WindHangFindRefresh(u64 frame) {
    if (hang_find_boxes.Fresh(frame)) {
        return;
    }
    std::vector<RtShadow::HangFindBox> boxes;
    std::array<float, 3> camera{};
    bool camera_ok = false;
    rt_shadow->WindHangFindBoxes(boxes, camera, camera_ok);
    hang_find_boxes.Begin(frame);
    for (const RtShadow::HangFindBox& source : boxes) {
        BbWindHangFind::Box b;
        b.stream = source.stream;
        b.vertices = source.vertices;
        b.triangles = source.triangles;
        b.box = source.box;
        b.src = source.src;
        b.skinned = source.skinned;
        b.dynamic = source.dynamic;
        b.palette = source.palette;
        b.shadow = source.shadow;
        hang_find_boxes.Add(b);
    }
    hang_static_book.DropSkinned(hang_find_boxes.All(), frame); // bbport (r112k_hang-lantern-verdict)
    hang_find_boxes.camera = camera;
    hang_find_boxes.camera_ok = camera_ok;
    if (camera_motion) { // bbport (r112j_hang-static-verts): the view and projection, for the survey's screen estimate
        const auto matrices = camera_motion->CameraMatrices();
        const auto size = camera_motion->RenderSize();
        hang_find_boxes.view = matrices.view;
        hang_find_boxes.proj = matrices.proj;
        hang_find_boxes.render = {size[0], size[1]};
        hang_find_boxes.view_ok = size[0] != 0 && size[1] != 0 && matrices.proj[0] != 0.0f &&
                                  matrices.proj[1] != 0.0f;
    }
    if (BbTestGoto::On()) { // bbport (r112n_hang-teleport-camera, TOOL): BB_TEST_GOTO: the hunter and the camera to the target
        float hunter_pos[3] = {};
        const bool hunter_read = BbEngine::world_player_position(hunter_pos);
        for (const std::string& line : BbTestGoto::Observe(hang_find_boxes, hang_static_book, hang_book, hang_box,
                                                           BbWindHangFind::TallKnob(), frame,
                                                           hunter_read ? hunter_pos : nullptr)) {
            BbReport::Printf("%s\n", line.c_str());
        }
    }
}

// bbport (r112i_hang-find-lanterns): an opaque static draw (Kind::Other, a pipeline with the Sway bit, no
// discard) of the stream at `positions` (`positions_size` bytes at `stride`): may it hang? A stream with a
// standing verdict (BbWindHangFind::StaticBook) costs one lookup; a new one gets its verdict from its
// vertex count and its box in the ray traced scene (Evaluate), held for 120-3600 frames. True: a
// candidate: the caller goes on to the GPU judge. On the thread recording draws.
bool Rasterizer::WindHangStaticAllowed(u64 positions, u32 positions_size, u32 stride, u64 frame,
                                        u64 vs) {
    BbWindHangFind::Stats& stats = hang_find_stats;
    ++stats.draws;
    if (positions == 0 || positions_size == 0 || stride == 0) {
        ++stats.no_stream;
        return false;
    }
    WindHangFindRefresh(frame); // bbport (r112k_hang-lantern-verdict): the scene's boxes every 60 frames, even for known streams
    const BbWindHangFind::StaticBook::Look look =
        hang_static_book.Peek(positions, positions_size, frame);
    if (look.known) {
        if (look.pass) {
            ++stats.passed;
        } else {
            ++stats.refused;
        }
        if (BbWindHangFind::FindOn()) { // bbport (r112k_hang-lantern-verdict, TOOL grade)
            hang_find_routes.Asked(positions, look.pass);
        }
        return look.pass;
    }
    WindHangFindRefresh(frame);
    // bbport (r112j_hang-static-verts): the vertex test reads the mesh's own count from the scene's box (the
    // bytes over the stride are the buffer's); a stream with no box yet is NoBox and asked again
    BbWindHangFind::Entry verdict = BbWindHangFind::Evaluate(
        BbWindHangFind::KnobOnce(), positions_size, positions_size / stride, positions,
        hang_find_boxes.Find(positions), hang_find_boxes.All(), frame);
    verdict.vs = vs;
    hang_static_book.Set(positions, verdict, frame);
    ++stats.judged;
    if (BbWindHangFind::FindOn()) { // bbport (r112k_hang-lantern-verdict, TOOL grade)
        hang_find_routes.Asked(positions, verdict.why == BbWindHangFind::Why::Ok);
    }
    return verdict.why == BbWindHangFind::Why::Ok;
}

// bbport (r112k_hang-lantern-verdict): may a draw whose small bone palette the GPU writes (Motion::Kind::GpuPalette,
// an opaque pipeline with the Sway bit: the caller tested both) go to the static path: its position stream (the
// pipeline's fetch, semantic 0) is a hanging candidate by the book's standing verdict, or gets a verdict now
// (WindHangStaticAllowed: box, size, ground rules). Only with BB_WIND_HANG_STATIC_GPU (default) and what the static
// path needs (the box keys, the sway words, ray tracing). False: the draw falls to the twig rule. On the thread
// recording draws.
bool Rasterizer::WindHangGpuStatic(const GraphicsPipeline* pipeline) {
    // bbport (r112l_hang-discard-lanterns): a pipeline whose pixel shader discards (a cut-out) is asked by its own knob
    // (BB_WIND_HANG_STATIC_CUT); r112k's GPU-palette knob (BB_WIND_HANG_STATIC_GPU) is for the opaque ones
    const bool cut = BbWindHangFind::Cuts(pipeline->GetStages()[u32(Shader::SwStage::Fragment)]);
    if (!(cut ? BbWindHangFind::CutOn() : BbWindHangFind::GpuOn()) || !BbWindHangStill::BoxAvailable() ||
        object_motion->SwayWords() == nullptr || !rt_shadow->Wanted()) {
        return false;
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto& fetch = pipeline->GetFetchShader();
    if (!fetch) {
        return false;
    }
    u64 positions = 0;
    u32 positions_size = 0;
    u32 stride = 0;
    for (const auto& attribute : fetch->attributes) {
        if (attribute.semantic == 0) {
            const auto stream = attribute.GetSharp(vs);
            positions = stream.base_address;
            positions_size = stream.GetSize();
            stride = stream.GetStride();
            break;
        }
    }
    BbWindHangFind::Stats& stats = hang_find_stats;
    ++stats.gpu_asked;
    stats.cut_asked += cut ? 1u : 0u; // bbport (r112l_hang-discard-lanterns)
    if (positions == 0 || positions_size == 0 || stride == 0) {
        return false;
    }
    const u64 frame = object_motion->Frame();
    const BbWindHangFind::StaticBook::Look look =
        hang_static_book.Peek(positions, positions_size, frame);
    const bool pass = look.known ? look.pass
                                 : WindHangStaticAllowed(positions, positions_size, stride, frame,
                                                         vs.pgm_hash);
    if (pass) {
        ++stats.gpu_passed;
        stats.cut_passed += cut ? 1u : 0u; // bbport (r112l_hang-discard-lanterns)
    }
    return pass;
}

// bbport (r112k_hang-lantern-verdict, TOOL grade; BB_WIND_HANG_FIND=1): what the Motion block made of a draw of the
// stream at the pipeline's position attribute: its kind ('S' skinned, 'P' GPU palette, 'O' other), whether its
// pipeline has the Sway bit and a pixel shader that discards, whether it got a sway word and whether the word
// reached the motion parameter (BbWindHangFind::Routes; the survey prints it after the stream's line).
void Rasterizer::WindHangFindRoute(const GraphicsPipeline* pipeline, char kind, u32 sway,
                                   bool delivered) {
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto& fetch = pipeline->GetFetchShader();
    if (!fetch) {
        return;
    }
    for (const auto& attribute : fetch->attributes) {
        if (attribute.semantic == 0) {
            const auto stream = attribute.GetSharp(vs);
            const auto fragment = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
            hang_find_routes.Note(stream.base_address, kind,
                                  (pipeline->GetGraphicsKey().motion_vectors &
                                   Shader::MotionVectors::Sway) != 0,
                                  fragment != nullptr && fragment->has_discard, sway != 0, delivered,
                                  object_motion->Frame());
            return;
        }
    }
}

// bbport (r112q_hang-bracket-route, TOOL): the counters a draw's sway word and r112's verdict move, copied before and after the word
// (BbWindHangRoute::Classify says from them where the draw left the chain). Only with BB_WIND_HANG_FIND=1. On the thread recording draws.
BbWindHangRoute::Mark Rasterizer::WindHangRouteMark() {
    BbWindHangRoute::Mark mark;
    mark.called = sway_stats.draws;
    mark.no_region = sway_stats.no_region;
    mark.no_rt = sway_stats.no_rt;
    mark.no_camera = sway_stats.no_camera;
    mark.no_slot = sway_stats.no_slot + sway_stats.views_full;
    mark.plants = sway_stats.plants;
    mark.no_sun = hang_stats.no_sun;
    mark.settled = hang_stats.settled;
    mark.waiting = hang_stats.waiting;
    mark.moving = hang_stats.moving;
    mark.unfit = hang_stats.unfit;
    mark.forced = hang_route.forced_total;
    mark.why = hang_actors.by_why;
    return mark;
}

// bbport (r112q_hang-bracket-route, TOOL): a Motion block draw of the pipeline, with its kind ('S' skinned, 'P' GPU palette, 'O' static),
// the sway word it got and whether the word reached the draw's motion parameter: noted by its pair of shaders (the stream group).
void Rasterizer::WindHangRouteNote(const GraphicsPipeline* pipeline, char kind, u32 word, bool delivered) {
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto* const fragment = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    u64 stream = 0;
    const auto& fetch = pipeline->GetFetchShader();
    if (fetch) {
        for (const auto& attribute : fetch->attributes) {
            if (attribute.semantic == 0) {
                stream = attribute.GetSharp(vs).base_address;
                break;
            }
        }
    }
    const bool sway_bit = (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::Sway) != 0;
    hang_route.Note(vs.pgm_hash, fragment != nullptr ? fragment->pgm_hash : u64{0}, kind, sway_bit,
                    fragment != nullptr && fragment->has_discard, stream, word, delivered, hang_route_before,
                    WindHangRouteMark());
}

// bbport (r112q_hang-bracket-route, TOOL): BB_WIND_HANG_FORCE's word: a hang word with the live BB_WIND_HANG_STATIC_GAIN as its ramp (0 with
// the live BB_WIND_HANG_PUSH=0), no judge, no rule; the view's push table is filled as WindHangWord fills it. On the thread recording draws.
u32 Rasterizer::WindHangForceWord(u32* words, u32 frame_slot, u32 view, u32 slot, const BbWind::Snapshot& now) {
    const u64 frame = object_motion->Frame();
    if (frame != hang_frame) {
        hang_frame = frame;
        hang_filled = {};
    }
    if (!hang_filled[view]) {
        const u32* const words_of_view = words + BbWindSway::ViewAt(frame_slot, view);
        const auto& knob = BbWindSway::KnobOnce();
        std::array<float, BbWindSway::GustSamples> table{};
        hang_push.Fill(now, std::bit_cast<float>(words_of_view[BbWindSway::WindE + 2]),
                       std::bit_cast<float>(words_of_view[BbWindSway::WindE + 3]), knob.gusts,
                       knob.scale, table.data());
        std::memcpy(words + BbWindHang::PushAt +
                        (frame_slot * BbWindSway::Views + view) * BbWindSway::GustSamples,
                    table.data(), sizeof(table));
        hang_filled[view] = true;
    }
    ++hang_route.forced_total;
    const u32 ramp = WindHangLiveOn() ? BbWindHangFind::SameRamp(255u, WindHangGainNow(), 1.0f, true) : 0u;
    return BbWindHang::HangWord(frame_slot, view, slot, ramp);
}

// bbport (r112r_hang-bracket-judge, TOOL): BB_WIND_HANG_PROOF_HIDE=1 (live with the test tools' knobs, else read once): the proof leaves every
// draw whose hang word reached the motion parameter out of the picture; WindHangProofDraw says so for the draw in flight.
#if BB_WIND_TWIGS_LIVE
static bool HangHideParseLive(const char* text) {
    return BbWindHangRoute::ParseHide(text);
}

static bool WindHangHideNow() {
    static BbLiveKnobs::Knob<bool> knob{"BB_WIND_HANG_PROOF_HIDE", HangHideParseLive};
    return knob.Get();
}
#else
static bool WindHangHideNow() {
    static const bool hide = BbWindHangRoute::ParseHide(std::getenv("BB_WIND_HANG_PROOF_HIDE"));
    return hide;
}
#endif

// bbport (r112r_hang-bracket-judge, TOOL): a Motion block draw (only with BB_WIND_HANG_PROOF=1 or BB_WIND_HANG_FIND=1) counted by its pair of
// shaders (BbWindHangRoute::TintBook: the draws whose hang word reached the motion parameter are the draws the proof's shaders tint, and the glass
// pick's rows name them), and true when BB_WIND_HANG_PROOF_HIDE=1 and the proof is on and the draw's word reached the parameter: the caller leaves
// the draw out (effect_skip_draw). On the thread recording draws.
bool Rasterizer::WindHangProofDraw(const GraphicsPipeline* pipeline, char kind, u32 word, bool delivered) {
    static bool said = false;
    const bool proof = BbWindHang::ProofOn();
    if (!said) {
        said = true;
        if (proof) {
            BbReport::Printf("%s\n", BbWindHangRoute::ProofOnceText(BbWindHang::ProofShare, BbWindHang::ProofBinaryAdd).c_str());
        }
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto* const fragment = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    const bool hang_word = delivered && word != 0 && (word & BbWindHang::HangBit) != 0;
    const bool hide = proof && hang_word && WindHangHideNow();
    hang_tint.Note(vs.pgm_hash, fragment != nullptr ? fragment->pgm_hash : u64{0}, kind, word, delivered, hide, object_motion->Frame());
    return hide;
}

// bbport (r112q_hang-bracket-route, TOOL): the window's route lines (BbWindHangRoute::Lines): one a stream group, then the books are cleared.
// On the thread recording draws, with r112's lines.
void Rasterizer::WindHangRouteReport() {
    static bool said = false;
    if (!said) {
        said = true;
        BbReport::Printf("%s\n", BbWindHangRoute::OnceText(static_cast<unsigned>(BbWindHangGpu::BoxRetry()),
                                                           BbWindHangRoute::ForceOn(), BbWindHangRoute::ForceOnce().all)
                                     .c_str());
    }
    WindHangFindRefresh(object_motion->Frame());
    const BbWindHangRoute::Lookup look = [this](u64 stream) {
        BbWindHangRoute::StreamInfo info;
        if (const BbWindHangFind::Box* const box = hang_find_boxes.Find(stream)) {
            info.scene = true;
            info.height = BbWindHangFind::HeightOf(box->box);
            info.width = BbWindHangFind::WidthOf(box->box);
            info.verts = box->vertices;
        }
        if (const BbWindHangStill::BoxEntry* const judged = hang_box.Find(stream)) {
            info.box = true;
            info.box_state = static_cast<std::uint8_t>(judged->state);
            info.dev = judged->dev;
        }
        if (const BbWindHang::Entry* const book = hang_book.Find(stream)) {
            info.book = true;
            info.moving = book->moving;
            info.judged = book->judged;
            info.fits = book->fits;
            info.why_moving = book->why_moving;
            info.box_only = book->box_only;
        }
        return info;
    };
    const BbWindHangRoute::PathOf path = [](u64 vs) {
        return BbWindTwigs::PathName(BbWindTwigs::ShaderPathOf(vs));
    };
    for (const std::string& line : BbWindHangRoute::Lines(hang_route, BbWindHangFind::KnobOnce().focus, look, path,
                                                          BbWindSway::ReportFrames)) {
        BbReport::Printf("%s\n", line.c_str());
    }
    if (BbWindHang::ProofOn()) { // bbport (r112r_hang-bracket-judge, TOOL): the pairs whose hang word reached the motion parameter (tinted), since the start
        for (const std::string& line : hang_tint.Lines(BbWindHangRoute::TintLinesMost)) {
            BbReport::Printf("%s\n", line.c_str());
        }
    }
    hang_route.Clear();
}

// bbport (r112i_hang-find-lanterns, TOOL grade; BB_WIND_HANG_FIND=1): the survey's lines (the header and the
// meshes that hang), every 600 frames with r112h's. On the thread recording draws.
void Rasterizer::WindHangFindReport() {
    const u64 frame = object_motion->Frame();
    WindHangFindRefresh(frame);
    for (const std::string& line : BbWindHangFind::SurveyLines(BbWindHangFind::KnobOnce(),
                                                                hang_find_boxes, hang_find_draws,
                                                                hang_static_book, frame, &hang_find_routes)) {
        BbReport::Printf("%s\n", line.c_str());
    }
}

// bbport (r112b_hang-probe, TOOL): the first bone palette (stride 16, Skeleton size: the buffer
// WindHangVerdict hashes) of a skinned sway draw, with r112's readability test (a palette the GPU
// writes, or one not mapped, is not read: a null pointer). On the thread recording draws.
void Rasterizer::WindHangProbeSkin(const GraphicsPipeline* pipeline, u64 positions,
                                   u32 positions_size) {
    if (hang_probe == nullptr) {
        hang_probe = std::make_unique<BbWindHangProbe::Skin>();
    }
    if (hang_probe->reported) {
        return; // done: the report went out
    }
    const u64 frame = object_motion->Frame();
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    for (const auto& resource : vs.buffers) {
        if (resource.IsSpecial()) {
            continue;
        }
        const auto buffer = resource.GetSharp(vs);
        const u32 size = buffer.GetSize();
        if (!buffer.Valid() || buffer.GetStride() != 16 ||
            Motion::ClassifyBuffer(size) != Motion::BufferRole::Skeleton) {
            continue;
        }
        const bool readable =
            !(buffer_cache.IsRegionGpuModified(buffer.base_address, size) &&
              !buffer_cache.IsInPlace(buffer.base_address, size)) &&
            memory->IsValidGpuMapping(buffer.base_address, 0) &&
            memory->ClampRangeSize(buffer.base_address, size) == size;
        const u64 stream = positions != 0 ? positions : (u64(buffer.base_address) | (u64{1} << 63));
        hang_probe->Note(stream, u64(buffer.base_address), size,
                         readable ? reinterpret_cast<const void*>(buffer.base_address) : nullptr,
                         rt_shadow->SunSkinned(positions, positions_size), frame);
        break;
    }
}

// bbport (r112b_hang-probe, TOOL): the skin lines, once (r112's block calls this every 600 frames).
void Rasterizer::WindHangProbeReport() {
    if (hang_probe == nullptr || hang_probe->reported) {
        return;
    }
    hang_probe->reported = true;
    for (const std::string& line : hang_probe->Lines(object_motion->Frame())) {
        BbReport::Printf("%s\n", line.c_str());
    }
    hang_probe->Release();
}

// bbport (r112_wind-more-things): a hanging thing's sway word once its stream has its slot
// (`reset`: its keys were reset now): HangBit with a ramp of 0 while the GPU fills its base and
// top keys (Measure reads them, only then: mapped GPU memory is slow for the CPU), then, if it
// spans MinExtent-MaxExtent, its ramp; out of height 0 (and the Book keeps it out without
// hashing). The first pushed draw of a view in a frame fills the view's push table (Push, from
// the camera FillView left in the view's WindE.z and WindE.w and the wind `now`).
u32 Rasterizer::WindHangWord(u32* words, u32 frame_slot, u32 view, u32 slot, bool reset,
                             u64 positions, u64 frame, const BbWind::Snapshot& now) {
    BbWindHang::Entry* const entry = hang_book.Find(positions);
    if (entry == nullptr) {
        return 0;
    }
    // bbport (r112k_hang-lantern-verdict): a static candidate (a standing verdict of the static book) is a mesh drawn
    // at several places: the keys of its slot span the union of them, up to BB_WIND_HANG_STATIC_UNION
    const BbWindHangFind::Entry* const placed = hang_static_book.Find(positions);
    // bbport (r112l_hang-discard-lanterns): a keys' span beyond BB_WIND_HANG_STATIC_TALL is the union of the places of a
    // mesh that clearly hangs (SpanLimit: BB_WIND_HANG_STATIC_UNION); any other tall one is refused as r112 did
    const bool placed_ok = placed != nullptr && placed->why == BbWindHangFind::Why::Ok;
    const float max_extent = placed_ok ? BbWindHangFind::SpanLimit(*placed) : BbWindHang::MaxExtent;
    // bbport (r112m_hang-close-proof): the keys of a static candidate's slot span the UNION of the places its mesh is drawn
    // at (no length): its real hanging length is its scene box. Taller than BB_WIND_HANG_STATIC_TALL: refused, counted,
    // and its candidate line says TOO TALL
    if (placed_ok && BbWindHangFind::TooTall(*placed, BbWindHangFind::TallKnob())) {
        ++hang_find_stats.too_tall;
        return 0;
    }
    const BbWindHang::Measured m =
        BbWindHang::Measure(*entry, reset, frame, words + BbWindSway::BaseAt + slot,
                            words + BbWindHang::TopAt + slot, now.time, max_extent);
    if (m.measuring) {
        ++hang_stats.measuring;
        return BbWindHang::HangWord(frame_slot, view, slot, 0);
    }
    if (!m.swing) {
        ++hang_stats.unfit;
        return 0;
    }
    if (frame != hang_frame) {
        hang_frame = frame;
        hang_filled = {};
    }
    if (!hang_filled[view]) {
        const u32* const words_of_view = words + BbWindSway::ViewAt(frame_slot, view);
        const auto& knob = BbWindSway::KnobOnce();
        std::array<float, BbWindSway::GustSamples> table{};
        hang_push.Fill(now, std::bit_cast<float>(words_of_view[BbWindSway::WindE + 2]),
                       std::bit_cast<float>(words_of_view[BbWindSway::WindE + 3]), knob.gusts,
                       knob.scale, table.data());
        std::memcpy(words + BbWindHang::PushAt +
                        (frame_slot * BbWindSway::Views + view) * BbWindSway::GustSamples,
                    table.data(), sizeof(table));
        hang_filled[view] = true;
    }
    ++hang_stats.swung;
    hang_stats.ramping += m.ramp < 255 ? 1 : 0;
    // bbport (r112k): BB_WIND_HANG_PUSH=0 (live) gives the word no motion
    // bbport (r112l_hang-discard-lanterns): a static candidate's push is its ramp times BB_WIND_HANG_STATIC_GAIN (r112j's
    // roof scale multiplies on top; a skinned hanging thing keeps its push)
    const u32 hang_ramp = WindHangLiveOn() ? m.ramp : 0u;
    // bbport (r112m_hang-close-proof): the gain is live (set:/unset:), and with BB_WIND_HANG_STATIC_SAME (default) the ramp of
    // a short candidate is made so that its bottom moves as far as a tall one's (the shaders scale the push of a mesh
    // under 1.2 m by its height over 1.2 m: a 0.21 m lantern part moved a quarter of the cage that holds it)
    const float hang_scale = BbWindHang::HangScale(entry->base, entry->top);
    // bbport (r112p_hang-gpu-palette-lanterns): a stream the GPU box judges in place of its palette (box_only) is pushed like a
    // static lantern: its ramp goes through SameRamp (BB_WIND_HANG_STATIC_GAIN, live; the bottom moves min(scale, gain) x push),
    // its pivot the top key of its slot (the shaders' top rule), as for every hanging thing
    const bool box_only = entry->box_only != 0;
    const u32 pushed_ramp = (placed_ok || box_only)
                                ? BbWindHangFind::SameRamp(hang_ramp, WindHangGainNow(), hang_scale, BbWindHangFind::SameKnob())
                                : hang_ramp;
    if (box_only) {
        ++hang_gpu_stats.words;
        hang_gpu_stats.ramping += m.ramp < 255 ? 1 : 0;
    }
    return BbWindHang::HangWord(frame_slot, view, slot, pushed_ramp);
}

// bbport (r112s_hang-bracket-move): a post lantern's sway word (BB_WIND_HANG_POST) once its stream has its slot (`reset`: its keys were reset now):
// PostBit and HangBit with a ramp of 0 while the GPU fills the slot's base and top keys (Measure, as for a hanging thing), then, if the keys' span
// is 0.15 m to PostMaxExtent, the ramp: Measure's times BB_WIND_HANG_STATIC_GAIN (live, as a static lantern's) and the live BB_WIND_HANG_PUSH switch;
// out of height 0 (no word). The first pushed draw of a view in a frame fills the view's push table, as WindHangWord does. On the thread recording draws.
u32 Rasterizer::WindPostWord(u32* words, u32 frame_slot, u32 view, u32 slot, bool reset, u64 positions, u32 positions_size, u32 positions_stride, u64 frame,
                             const BbWind::Snapshot& now) {
    BbWindHang::PostBook::Item& item = hang_post.Touch(positions, positions_size, frame);
    ++hang_post.draws;
    // bbport (r112t_hang-post-measure): the slot's keys were the union of every place the stream is drawn at (b68: over 10 m, no word for good):
    // the CPU writes the keys of the post nearest the camera from the ray traced scene's boxes instead (the shaders offer no key for a post word)
    if (!item.logged) { // the stream's first three vertices and its box of floats 0-2, once
        item.logged = true;
        const bool readable = positions_stride >= 12 && memory->IsValidGpuMapping(positions, 0) &&
                              memory->ClampRangeSize(positions, positions_size) == positions_size;
        char vertices_line[1024];
        BbWindHang::PostVerticesText(readable ? reinterpret_cast<const unsigned char*>(positions) : nullptr, positions_size, positions_stride,
                                     vertices_line, sizeof(vertices_line));
        BbReport::Printf("%s\n", vertices_line);
    }
    if (reset) {
        item.keys_written = false; // the slot is new: its keys were just reset
    }
    if (item.pick_frame != frame) { // the boxes change every 60 frames, the camera every frame: once a frame
        WindHangFindRefresh(frame);
        item.pick = BbWindHang::PickPost(hang_find_boxes.All(), positions, hang_find_boxes.camera_ok ? hang_find_boxes.camera.data() : nullptr);
        item.pick_frame = frame;
        item.guard = BbWindHang::PostGuardOn() ? BbWindHang::PostGuardCheck(hang_find_boxes.All(), positions, item.pick, nullptr, 0)
                                               : BbWindHang::PostGuard{}; // bbport (r112u_hang-post-no-bridge): no lamp list here, see the once line
    }
    const BbWindHang::PostPick pick = item.pick;
    if (pick.found) {
        hang_post.last = pick;
    }
    if (!pick.found) {
        ++hang_post.no_box;
        return 0;
    }
    BbWindLantern::Keys lantern_keys{}; // bbport (r112v_lantern-hangs): only the lantern leans (bbport_wind_lantern.h); the slot's words are written below
    if (BbWindHang::LanternAsked()) {
        BbWindLantern::Book& lantern = BbWindLantern::Global();
        ++lantern.draws;
        if (!lantern.said) {
            lantern.said = true;
            char lantern_once[1280];
            if (BbWindLantern::On()) {
                BbWindLantern::OnceText(lantern_once, sizeof(lantern_once));
            } else {
                BbWindLantern::OffText(lantern_once, sizeof(lantern_once));
            }
            BbReport::Printf("%s\n", lantern_once);
        }
        if (!BbWindLantern::On()) { // the twigs' box keys do not exist: no plan can be given, so nothing moves
            ++lantern.twigs_off;
            return 0;
        }
        BbWindLantern::StreamPlan& stream_plan = lantern.Touch(positions, positions_size);
        if (!stream_plan.analysed) { // the stream's vertices, read once
            stream_plan.analysed = true;
            const bool lantern_readable = positions_stride >= 12 && memory->IsValidGpuMapping(positions, 0) &&
                                          memory->ClampRangeSize(positions, positions_size) == positions_size;
            stream_plan.plan = BbWindLantern::Analyse(lantern_readable ? reinterpret_cast<const unsigned char*>(positions) : nullptr, positions_size,
                                                      positions_stride, BbWindLantern::KnobOnce());
            if (stream_plan.plan.ok) {
                ++lantern.plans_ok;
            } else {
                ++lantern.plans_bad;
            }
            char plan_line[1792];
            BbWindLantern::PlanText(positions, stream_plan.plan, plan_line, sizeof(plan_line));
            BbReport::Printf("%s\n", plan_line);
        }
        if (!stream_plan.plan.ok) {
            ++lantern.no_plan;
            return 0;
        }
        if (stream_plan.guard_frame != frame) { // the boxes change every 60 frames, the camera every frame: once a frame
            stream_plan.guard_frame = frame;
            stream_plan.guard = BbWindLantern::GuardCheck(hang_find_boxes.All(), positions);
            stream_plan.axis = BbWindLantern::AxisOf(hang_find_boxes.All(), positions, pick,
                                                     hang_find_boxes.camera_ok ? hang_find_boxes.camera.data() : nullptr);
        }
        if (stream_plan.guard.why != BbWindLantern::Refuse::None) { // a bridge, a wall, a building, architecture: never pushed
            ++lantern.refused;
            ++lantern.by_reason[static_cast<std::size_t>(stream_plan.guard.why)];
            if (stream_plan.said != stream_plan.guard.why) { // one line per stream and reason
                stream_plan.said = stream_plan.guard.why;
                char lantern_guard_line[640];
                BbWindLantern::GuardText(positions, stream_plan.guard, lantern_guard_line, sizeof(lantern_guard_line));
                BbReport::Printf("%s\n", lantern_guard_line);
            }
            return 0;
        }
        stream_plan.said = BbWindLantern::Refuse::None;
        if (!stream_plan.axis.found) {
            ++lantern.no_axis;
            return 0;
        }
        lantern_keys = BbWindLantern::MakeKeys(stream_plan.plan, pick.base, stream_plan.axis.x, stream_plan.axis.z);
        lantern.last_arm_world = lantern_keys.arm_world;
        lantern.last_x = stream_plan.axis.x;
        lantern.last_z = stream_plan.axis.z;
        ++lantern.pushed;
    }
    if (BbWindHang::PostGuardOn() && !BbWindLantern::On()) { // bbport (r112u_hang-post-no-bridge): only a hanging lantern is pushed, never the bridge or a post (r112v: the lantern rule has its own guard)
        if (!hang_post.guard_said) {
            hang_post.guard_said = true;
            char guard_once[640];
            BbWindHang::PostGuardOnceText(guard_once, sizeof(guard_once));
            BbReport::Printf("%s\n", guard_once);
        }
        if (item.guard.why != BbWindHang::PostRefuse::None) {
            ++hang_post.refused;
            ++hang_post.by_reason[static_cast<std::size_t>(item.guard.why)];
            if (item.refused != item.guard.why) { // one line per stream and reason
                item.refused = item.guard.why;
                ++hang_post.refused_streams;
                char guard_line[640];
                BbWindHang::PostGuardText(positions, item.guard, guard_line, sizeof(guard_line));
                BbReport::Printf("%s\n", guard_line);
            }
            return 0;
        }
        item.refused = BbWindHang::PostRefuse::None;
    }
    const float post_height = pick.top - pick.base;
    if (!(post_height >= BbWindHang::MinExtent && post_height <= BbWindHang::PostMaxExtent)) {
        ++hang_post.unfit;
        return 0;
    }
    BbWindHang::Entry& post_entry = item.entry;
    if (reset || !post_entry.judged || !post_entry.fits) { // the ramp starts with a new slot or the first box that fits
        post_entry.started = true;
        post_entry.judged = true;
        post_entry.fits = true;
        post_entry.since = now.time;
        post_entry.measure_from = frame;
    }
    post_entry.base = pick.base;
    post_entry.top = pick.top;
    u32 post_base_key = BbWindSway::HeightKey(pick.base);
    u32 post_top_key = BbWindHang::TopKey(pick.top);
    if (BbWindLantern::On()) { // bbport (r112v_lantern-hangs): the plan's keys: the arm's edge, and in the twigs' box keys the axis and R0, R1 (every call: the same values)
        post_base_key = lantern_keys.base;
        post_top_key = lantern_keys.top;
        if (slot < BbWindSway::BaseSlots) {
            u32* const box_words = words + BbWindTwigs::TwigAt + slot * BbWindTwigs::TwigSlotWords;
            box_words[0] = lantern_keys.x_lo;
            box_words[1] = lantern_keys.x_hi;
            box_words[2] = lantern_keys.z_lo;
            box_words[3] = lantern_keys.z_hi;
        }
    }
    if (!item.keys_written || item.base_key != post_base_key || item.top_key != post_top_key) {
        words[BbWindSway::BaseAt + slot] = post_base_key; // two stores into the mapped words, as the slot's reset does
        words[BbWindHang::TopAt + slot] = post_top_key;
        item.base_key = post_base_key;
        item.top_key = post_top_key;
        item.keys_written = true;
        ++hang_post.written;
    }
    const BbWindHang::Measured m{false, true, BbWindSway::RampByte((now.time - post_entry.since) / BbWindSway::RampTime)};
    if (frame != hang_frame) {
        hang_frame = frame;
        hang_filled = {};
    }
    if (!hang_filled[view]) {
        const u32* const words_of_view = words + BbWindSway::ViewAt(frame_slot, view);
        const auto& knob = BbWindSway::KnobOnce();
        std::array<float, BbWindSway::GustSamples> table{};
        hang_push.Fill(now, std::bit_cast<float>(words_of_view[BbWindSway::WindE + 2]),
                       std::bit_cast<float>(words_of_view[BbWindSway::WindE + 3]), knob.gusts, knob.scale, table.data());
        std::memcpy(words + BbWindHang::PushAt + (frame_slot * BbWindSway::Views + view) * BbWindSway::GustSamples, table.data(),
                    sizeof(table));
        hang_filled[view] = true;
    }
    ++hang_post.pushed;
    const u32 ramp = WindHangLiveOn() ? m.ramp : 0u;
    const float post_gain = BbWindHang::PostGuardOn() ? BbWindHang::PostGain(WindHangGainNow()) : WindHangGainNow(); // bbport (r112u): a post moves 0.12 m at most
    return BbWindHang::PostWord(frame_slot, view, slot, BbWindHangFind::SameRamp(ramp, post_gain, 1.0f, true));
}

// bbport (r89d_tree-twigs): whether a skinned sway draw that is no plant may be a tree
// (BB_WIND_TWIGS_REACH 1 or more): its stream is one a sun shadow pass draws (RtShadow::SunSkinned:
// a character, a prop with a skeleton or a tree, outdoors) that the Book has not judged a non-tree.
// Counts the draws it turns away. On the thread recording draws.
bool Rasterizer::WindTwigTree(u64 positions, u32 positions_size) {
    if (!BbWindTwigs::ReachSun()) {
        return false;
    }
    if (!rt_shadow->SunSkinned(positions, positions_size)) {
        ++twig_stats.no_sun;
        return false;
    }
    const BbWindTwigs::Entry* const entry = twig_book.Find(positions);
    if (entry != nullptr && entry->size == positions_size &&
        entry->verdict == BbWindTwigs::Verdict::NotTree) {
        ++twig_stats.not_tree;
        return false;
    }
    return true;
}

// bbport (r89d_tree-twigs): a sun-drawn stream's sway word once it has its slot: TreeBit with a ramp
// of 0 while the Book judges it (the shaders offer its keys; the CPU reads them JudgeFrames frames
// after the slot was taken, and StillFrames frames later), once it is a tree a ramp from the verdict
// (BbWindSway::RampTime of wind time `time`, so the twigs do not start at once), 0 (no sway code run)
// once it is not. On the thread recording draws.
u32 Rasterizer::WindTwigWord(u32* words, u32 frame_slot, u32 view,
                             const BbWindSway::Slots::Taken& taken, u64 positions,
                             u32 positions_size, u64 frame, double time, bool small) {
    BbWindTwigs::Entry& entry =
        twig_book.Touch(positions, positions_size, taken.slot, taken.reset, frame);
    if (small) { // bbport (r89e_twigs-big-trees): a static cut-out: its own judging and counts
        entry.small = true;
        entry.loose = BbWindTwigs::SmallLoose();
        entry.limb = BbWindTrees::On() && trees_last_limb; // bbport (r89k_twigs-opaque-word): judged from LimbMinH
        if (const BbWindTwigs::SmallInfo* const info = twig_book.FindInfo(positions)) {
            entry.per_frame = info->max_per_frame;
            // bbport (r89i_twigs-colour-pass): BB_WIND_TWIGS_PALETTE: a stream with a bone palette is judged
            // without the shape and instance checks (one mesh drawn once for each tree it stands for has the
            // union of all its places as its box); its height, stillness and vertex count still count
            // bbport (r89j_twigs-pick-trees): with TREES the shape rule has judged the draw: height and stillness only
            entry.loose = entry.loose || BbWindTrees::On() || (BbWindCensus::PaletteOn() && info->palette);
        }
    }
    const BbWindTwigs::Verdict verdict = BbWindTwigs::Judge(entry, words, frame);
    if (small && verdict != BbWindTwigs::Verdict::Waiting) {
        WindTwigSmallVerdict(entry, positions);
    }
    switch (verdict) {
    case BbWindTwigs::Verdict::Tree:
        if (small && BbWindTwigs::SmallLogOnly()) { // BB_WIND_TWIGS_SMALL=2: measured, none taken
            ++twig_stats.small_judging;
            return BbWindTwigs::TreeWord(frame_slot, view, taken.slot, 0);
        }
        if (small) {
            ++twig_stats.small_tree;
        } else {
            ++twig_stats.tree_draws;
        }
        // bbport (r89l_twigs-palette-move): a draw of the trees route keeps BB_WIND_TWIGS_TREES_GAIN of its ramp byte
        return BbWindTwigs::TreeWord(
            frame_slot, view, taken.slot,
            small && BbWindTrees::On()
                ? BbWindTrees::GainRamp(BbWindTwigs::TreeRamp(entry, time, taken.ramp), BbWindTrees::TreesGain())
                : BbWindTwigs::TreeRamp(entry, time, taken.ramp));
    case BbWindTwigs::Verdict::NotTree:
        if (small) { // its slot goes back at once; the stream costs a lookup from now on
            ++twig_stats.small_refused;
            sway_slots.Release(positions);
        } else {
            ++twig_stats.not_tree;
        }
        return 0;
    case BbWindTwigs::Verdict::Waiting:
        break;
    }
    if (small) {
        ++twig_stats.small_judging;
    } else {
        ++twig_stats.measuring;
    }
    return BbWindTwigs::TreeWord(frame_slot, view, taken.slot, 0);
}

// bbport (r89e_twigs-big-trees): whether a static cut-out draw (Kind::Other, a pipeline with the Sway
// bit) may be a tree the twigs take (BB_WIND_TWIGS_SMALL above 0): a stream already judged not a tree,
// or refused by the cheap check, costs one map lookup; a new stream is checked by its vertex count
// (SmallPrefilter), read for the log (FarShare, shader hashes), and measured by the Book (the caller
// gives it a slot and a word of ramp 0) while fewer than SmallLiveMax streams are being measured.
// Counts the draws of a stream in a frame (SmallInstMax). On the thread recording draws.
bool Rasterizer::WindTwigSmall(const GraphicsPipeline* pipeline, u64 positions, u32 positions_size,
                               u32 stride, bool floats, bool palette) {
    if (!BbWindTwigs::ReachSmall() || positions == 0 || positions_size == 0 || stride == 0) {
        return false;
    }
    ++twig_stats.small_seen;
    const u64 frame = object_motion->Frame();
    const u32 verts = positions_size / stride;
    const BbWindTwigs::Entry* const entry = twig_book.Find(positions);
    if (entry != nullptr && entry->size == positions_size) {
        if (!entry->small) {
            return false; // a stream the sun-drawn rule keeps
        }
        if (entry->verdict == BbWindTwigs::Verdict::NotTree) {
            ++twig_stats.small_refused;
            return false;
        }
    }
    if (BbWindTwigs::SmallInfo* const known = twig_book.FindInfo(positions)) {
        if (known->verts == verts) {
            ++known->draws;
            if (known->frame != frame) {
                known->frame = frame;
                known->frame_draws = 0;
            }
            known->max_per_frame = std::max(known->max_per_frame, ++known->frame_draws);
            return true;
        }
    }
    if (twig_book.LiveSmall(frame) >= BbWindTwigs::SmallLiveMax) {
        ++twig_stats.small_deferred;
        return false;
    }
    BbWindTwigs::SmallInfo fresh;
    fresh.verts = verts;
    fresh.palette = palette;
    fresh.draws = 1;
    fresh.frame = frame;
    fresh.frame_draws = fresh.max_per_frame = 1;
    fresh.vs = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
    fresh.ps = FragmentHash(pipeline);
    const u64 bytes = u64(verts) * stride;
    if (floats && stride >= 12 && bytes != 0 && memory->IsValidGpuMapping(positions, 0) &&
        memory->ClampRangeSize(positions, bytes) == bytes) {
        fresh.far_share =
            BbWindTwigs::FarShare(reinterpret_cast<const unsigned char*>(positions), stride, verts);
    }
    twig_book.SetInfo(positions, fresh);
    if (const char* const why = BbWindTwigs::SmallPrefilter(verts)) {
        BbWindTwigs::Entry& refused = twig_book.Refuse(positions, positions_size, frame, why);
        ++twig_stats.small_pre;
        ++twig_stats.small_refused;
        WindTwigSmallVerdict(refused, positions);
        return false;
    }
    return true;
}

// bbport (r89e_twigs-big-trees): a candidate's verdict line, once per entry, at most SmallLogJudged
// lines for judged streams and SmallLogRefused for those the cheap check refused (no slot). On the
// thread recording draws.
void Rasterizer::WindTwigSmallVerdict(BbWindTwigs::Entry& entry, u64 positions) {
    static u32 judged_lines = 0, refused_lines = 0;
    if (entry.logged) {
        return;
    }
    entry.logged = true;
    const bool cheap = entry.slot == 0xffffffffu;
    static u32 limb_lines = 0; // bbport (r89k_twigs-opaque-word): limb pieces have a budget of their own (128 lines)
    u32& lines = cheap ? refused_lines : (entry.limb ? limb_lines : judged_lines);
    if (lines >= (cheap ? BbWindTwigs::SmallLogRefused
                        : (entry.limb ? 2 * BbWindTwigs::SmallLogJudged : BbWindTwigs::SmallLogJudged))) {
        return;
    }
    ++lines;
    char text[384];
    BbWindTwigs::SmallLine(entry, twig_book.FindInfo(positions), text, sizeof(text));
    BbReport::Printf("%s\n", text);
}

// bbport (r89d_tree-twigs): the Motion block's draws that got no sway word because the sway cannot
// reach them (counted for the twigs' line, twigs on only): a skinned draw of a pipeline without the
// Sway bit (no cut-out: an opaque mesh; BB_WIND_TWIGS_REACH=2 would take it) and a draw of a
// pipeline with the Sway bit that is not Kind::Skinned (a cut-out with a small skeleton or a palette).
// Returns 0, the sway word.
u32 Rasterizer::WindTwigSkip(bool skinned, bool sway_bit) {
    if (BbWindTwigs::On()) {
        if (skinned && !sway_bit) {
            ++twig_stats.opaque;
        } else if (!skinned && sway_bit) {
            ++twig_stats.small;
        }
    }
    return 0;
}

// bbport (r89j_twigs-pick-trees; BB_WIND_TWIGS_TREES=1): whether the candidate draw being recorded (trees_draw: its index
// range) is a tree. Its vertex range is found from the lowest and highest index value (at most ShapeIndexMax indices read
// from guest memory), up to ShapeSamples of its vertices are read and BbWindTrees::ShapeOf judges their shape, once per
// (stream, base vertex, index address, index count) and RecheckFrames frames. A tree-shaped draw is taken only while the
// camera is outdoors (r117's field at the camera; without the field the camera counts as outdoors). True: `positions` and
// `positions_size` are then the draw's own vertex range (the address of its first used vertex, its bytes): the key and the
// size of its sway slot, so the box keys the shaders keep measure one tree. On the thread recording draws.
bool Rasterizer::WindTreesDraw(u64& positions, u32& positions_size, u32 stride, bool floats, bool opaque) {
    BbWindTrees::Stats& st = trees_stats;
    ++st.draws;
    trees_last_limb = false; // bbport (r89k_twigs-opaque-word): set below for a limb piece
    const TreesDraw& d = trees_draw;
    if (positions == 0 || positions_size == 0 || stride < 12 || !floats || !d.valid || d.num_indices == 0 ||
        (d.index_size != 2 && d.index_size != 4)) {
        ++st.unread;
        return false;
    }
    const u64 frame = object_motion->Frame();
    const u64 key = BbWindTrees::MeshKey(positions, d.base_vertex, d.index_address, d.num_indices);
    BbWindTrees::Mesh* mesh = trees_book.Find(key, frame);
    if (mesh == nullptr) { // at most JudgeMost draw ranges judged a frame: an older verdict holds, or the draw waits
        static u64 judge_frame = ~u64(0);
        static u32 judged = 0;
        if (judge_frame != frame) {
            judge_frame = frame;
            judged = 0;
        }
        if (judged >= BbWindTrees::JudgeMost) {
            mesh = trees_book.Any(key);
            if (mesh == nullptr) {
                ++st.unread;
                return false;
            }
        } else {
            ++judged;
        }
    }
    if (mesh == nullptr) {
        BbWindTrees::Mesh fresh;
        fresh.at = frame;
        const unsigned char* const data = reinterpret_cast<const unsigned char*>(d.index_address);
        const u32 count = std::min<u32>(d.num_indices, BbWindTrees::ShapeIndexMax);
        u32 lo = 0xffffffffu;
        u32 hi = 0;
        for (u32 i = 0; i < count; ++i) {
            u32 value = 0;
            if (d.index_size == 2) {
                u16 narrow = 0;
                std::memcpy(&narrow, data + u64(i) * 2, sizeof(narrow));
                value = narrow == 0xffffu ? 0xffffffffu : u32(narrow); // the restart index is no vertex
            } else {
                std::memcpy(&value, data + u64(i) * 4, sizeof(value));
            }
            if (value == 0xffffffffu) {
                continue;
            }
            lo = std::min(lo, value);
            hi = std::max(hi, value);
        }
        const s64 first = s64(d.base_vertex) + s64(lo);
        const u64 verts = lo <= hi ? u64(hi) - u64(lo) + 1u : u64(0);
        if (lo > hi) {
            fresh.why = "indices";
        } else if (first < 0) {
            fresh.why = "base";
        } else if (verts < BbWindTwigs::SmallMinVerts) {
            fresh.why = "verts-few";
        } else if (verts > BbWindTwigs::SmallMaxVerts) {
            fresh.why = "verts-many";
        } else {
            const u64 address = positions + u64(first) * stride;
            const u64 bytes = verts * stride;
            if (!memory->IsValidGpuMapping(address, 0) || memory->ClampRangeSize(address, bytes) != bytes) {
                fresh.why = "memory";
            } else if (buffer_cache.IsRegionGpuModified(address, bytes)) {
                fresh.why = "gpu";
            } else {
                const unsigned char* const base = reinterpret_cast<const unsigned char*>(address);
                const u64 step = std::max<u64>(1, verts / BbWindTrees::ShapeSamples);
                std::vector<float> samples;
                samples.reserve(3 * BbWindTrees::ShapeSamples + 3);
                for (u64 v = 0; v < verts; v += step) {
                    float xyz[3];
                    std::memcpy(xyz, base + v * stride, sizeof(xyz));
                    if (std::isfinite(xyz[0]) && std::isfinite(xyz[1]) && std::isfinite(xyz[2])) {
                        samples.push_back(xyz[0]);
                        samples.push_back(xyz[1]);
                        samples.push_back(xyz[2]);
                    }
                }
                fresh.shape = BbWindTrees::ShapeOf(samples.data(), samples.size() / 3);
                fresh.tree = fresh.shape.tree;
                // bbport (r89k_twigs-opaque-word): a shape the rule refuses may still be a limb piece of a tree
                if (!fresh.tree && fresh.shape.up >= 0 && BbWindTrees::LimbOn()) {
                    const BbWindTrees::Limb limb = BbWindTrees::LimbOf(samples.data(), samples.size() / 3,
                                                                       BbWindTrees::LimbBoxyMax());
                    fresh.limb = limb.ok;
                    fresh.boxy = limb.boxy;
                    fresh.limb_why = limb.ok ? "ok" : limb.why;
                }
                fresh.why = fresh.shape.why != nullptr ? fresh.shape.why : "";
                fresh.addr = address;
                fresh.size = static_cast<u32>(bytes);
                fresh.verts = static_cast<u32>(verts);
            }
        }
        ++st.new_meshes;
        if (fresh.tree) {
            ++st.tree_meshes;
        } else {
            ++st.refused_meshes;
            // bbport (r89k_twigs-opaque-word): ranges the limb rule took, and ranges it refused too
            if (fresh.limb) {
                ++st.limb_new;
            } else if (fresh.limb_why[0] != '\0') {
                ++st.limb_refused;
            }
        }
        mesh = &trees_book.Put(key, fresh);
        static unsigned refused_lines = 0;
        static unsigned limb_lines = 0;
        unsigned& lines = fresh.tree ? trees_lines : (fresh.limb ? limb_lines : refused_lines);
        const unsigned lines_most = fresh.tree ? BbWindTrees::MeshLines
                                               : (fresh.limb ? BbWindTrees::LimbLines : BbWindTrees::MeshLines / 2);
        if (lines < lines_most) {
            ++lines;
            char text[512];
            BbWindTrees::MeshText(*mesh, positions, text, sizeof(text));
            BbReport::Printf("%s\n", text);
        }
    }
    // bbport (r89k_twigs-opaque-word): an opaque draw the shape rule refuses but the limb rule takes (a piece of a tree)
    // bbport (r89q_twigs-limb-discard): a limb piece whose pixel shader discards (alpha-tested bark and twig cards) is taken too
    // (BB_WIND_TWIGS_LIMB_CUTOUT, default 1): the visible wood of the bare trees; r89k took opaque draws only
    const bool limb = !mesh->tree && mesh->limb && (opaque || BbWindTrees::CutoutOn()) && BbWindTrees::LimbOn();
    const bool cut_limb = limb && !opaque;
    if (!mesh->tree && !limb) {
        // bbport (r89p_twigs-really-move): a limb piece by shape, refused only because the draw is not opaque
        st.limb_cutout += (mesh->limb && !opaque && BbWindTrees::LimbOn()) ? 1u : 0u;
        ++st.refused;
        return false;
    }
    // bbport (r89o_wind-chains-twigs-visible): a chain, a grille bar or a prop whose model is small is no tree, however its proportions
    // read (BbWindTrees::SizeOk, BB_WIND_TWIGS_MIN_MODEL): it stays still
    // bbport (r89r_twigs-limb-units): a limb piece is sized by its world box (BbWindTwigs::Judge), not by its model height: the model
    // units are not metres and Shape::height of a limb piece is an arbitrary axis (0.01 to 0.11 for the bare trees' cards)
    if (!BbWindTrees::SizeOk(mesh->shape.height, limb) && !(limb && BbWindTrees::LimbWorldOn())) {
        ++st.too_small;
        st.lr_model += limb ? 1u : 0u;
        return false;
    }
    // bbport (r89q_twigs-limb-discard): a cut-out limb piece must also be tall enough (BB_WIND_TWIGS_CUTOUT_MIN_MODEL: fences and cages)
    if (cut_limb && !BbWindTrees::LimbWorldOn() && !BbWindTrees::CutoutSizeOk(mesh->shape.height)) {
        ++st.limb_cut_small;
        return false;
    }
    // bbport (r89p_twigs-really-move): the gate is BB_WIND_TWIGS_OPEN_MIN (0.2; was the constant 0.5, which a canopy tripped)
    if (wind_shelter != nullptr && wind_shelter->CameraOpen() < BbWindTrees::OpenMin()) {
        ++st.indoors;
        st.lr_indoors += limb ? 1u : 0u; // bbport (r89r_twigs-limb-units)
        return false;
    }
    positions = mesh->addr;
    positions_size = mesh->size;
    ++st.taken;
    if (limb) {
        ++st.limbs;
        trees_last_limb = true;
        st.lr_old += BbWindTrees::LimbOldRuleRefuses(mesh->shape.height, cut_limb) ? 1u : 0u; // bbport (r89r_twigs-limb-units)
        if (cut_limb) { // bbport (r89q_twigs-limb-discard): counted, and the first few told once each
            ++st.limb_cut;
            static u64 cut_said[12];
            static u32 cut_said_count = 0;
            if (cut_said_count < 12) {
                bool known = false;
                for (u32 i = 0; i < cut_said_count; ++i) {
                    known = known || cut_said[i] == key;
                }
                if (!known) {
                    cut_said[cut_said_count++] = key;
                    char cut_text[320];
                    BbWindTrees::CutLimbText(*mesh, mesh->addr, cut_text, sizeof(cut_text));
                    BbReport::Printf("%s\n", cut_text);
                }
            }
        }
    }
    return true;
}

// bbport (r89j_twigs-pick-trees, TOOL; BB_WIND_TWIGS_PICK): the G-buffer draw being recorded in a pick frame gets the next
// query of the pool (a draw another query wraps, or a full group, is left out) and its facts are kept for the winner
// rule: the pipeline's shader hashes, cut-out, sway bit, motion pipeline, depth write, the position stream, the draw's
// range, its kind and sway word (trees_pick_note, set by the Motion block or the census site of the draw). On the thread
// recording draws.
void Rasterizer::WindTreesPickQuery(const GraphicsPipeline* pipeline, const AmdGpu::Regs& regs, u32 index_offset,
                                    s32 base_vertex, vk::QueryPool& pool, u32& index) {
    TreesPick& p = trees_pick;
    if (!p.pool || pool) {
        return;
    }
    TreesPickGroup& g = p.groups[p.group];
    if (g.pending) {
        return;
    }
    if (g.used >= BbWindTrees::PickPerGroup) {
        ++g.skipped; // no query left: the report says so (a missing late draw could be the winner)
        return;
    }
    const auto& key = pipeline->GetGraphicsKey();
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto& fetch = pipeline->GetFetchShader();
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    BbWindTrees::PickDraw d;
    d.vs = static_cast<u32>(vs.pgm_hash & 0xffffffffu);
    d.ps = static_cast<u32>(FragmentHash(pipeline) & 0xffffffffu);
    d.indices = regs.num_indices;
    d.first = index_offset;
    d.base = base_vertex;
    d.kind = trees_pick_note.kind;
    d.sway = trees_pick_note.sway;
    d.cutout = ps != nullptr && ps->has_discard;
    d.sway_bit = (key.motion_vectors & Shader::MotionVectors::Sway) != 0;
    d.motion = (key.motion_vectors & Shader::MotionVectors::VertexOutputs) != 0;
    d.depth_write = regs.depth_control.depth_write_enable != 0;
    const u32 index_size = regs.index_buffer_type.index_type == AmdGpu::IndexType::Index16 ? 2u : 4u;
    d.index_address = regs.index_base_address.Address<VAddr>() + u64(index_offset) * index_size;
    if (fetch) {
        for (const auto& attribute : fetch->attributes) {
            if (attribute.semantic == 0) {
                const auto stream = attribute.GetSharp(vs);
                d.stream = stream.base_address;
                d.stride = stream.GetStride();
                d.stream_verts = d.stride != 0 ? stream.GetSize() / d.stride : 0u;
                break;
            }
        }
    }
    if (trees_pick_glass) { // bbport (r86l_glint-pick-glass, TOOL): what the glass pick says of this draw
        const auto& pick_dc = Dc();
        d.glass_flags = (gbuffer_draw ? RtGlassPick::FlagGBuffer : 0u) |
                        (regs.blend_control[0].enable != 0 ? RtGlassPick::FlagBlend : 0u) |
                        (d.depth_write ? RtGlassPick::FlagZWrite : 0u) |
                        (regs.depth_control.depth_enable != 0 ? RtGlassPick::FlagZTest : 0u) |
                        (ps != nullptr && !ps->images.empty() ? RtGlassPick::FlagTextured : 0u) |
                        (pick_dc.capture_draw ? RtGlassPick::FlagCapture : 0u) |
                        (pick_dc.motion_geometry != 0 ? RtGlassPick::FlagGeometry : 0u) |
                        (trees_pick_indexed ? RtGlassPick::FlagIndexed : 0u);
        d.targets = u32(std::popcount(key.mrt_mask));
        d.instances = regs.num_instances.NumInstances();
        d.index_size = index_size;
        d.images = ps != nullptr ? u32(ps->images.size()) : 0u;
        d.pair_vs = vs.pgm_hash;
        d.pair_ps = ps != nullptr ? ps->pgm_hash : 0u;
        GlassPickNote& note = glass_pick_note;
        if (note.valid && note.positions == d.stream && note.index_count == d.indices) {
            // the capture hook saw this draw: its key and facts (the skeleton, the bone palette, its own camera constants)
            d.mesh = note.key;
            d.glass_flags |= note.flags | RtGlassPick::FlagStashed;
        } else if (d.stream != 0) {
            const std::array<u64, 4> parts{d.stream, trees_pick_indexed ? d.index_address : u64(0),
                                           (u64(d.indices) << 32) | u32(d.base), u64(d.instances)};
            d.mesh = XXH3_64bits(parts.data(), sizeof(parts)); // the key PrepareDraw makes of a draw with a position stream
        }
        note.valid = false;
    }
    pool = *p.pool;
    index = p.group * BbWindTrees::PickPerGroup + g.used++;
    g.draws.push_back(d);
}

// bbport (r89j_twigs-pick-trees), once a frame (EffectsOnFrameEnd): the once lines; with BB_WIND_TWIGS_TREES the trees'
// line every BbWindSway::ReportFrames frames; with BB_WIND_TWIGS_PICK (TOOL) the pick: this frame's group of queries is
// closed (it waits for the GPU's tick), groups the GPU has passed are read without waiting (the winner rule and the log
// lines; the query range is reset from the host), and the next frame's patch is set while it lies in the pick's frames.
void Rasterizer::WindTreesPickFrameEnd() {
    static bool trees_said = false;
    if (!trees_said && BbWindTrees::On()) {
        trees_said = true;
        char once[1024];
        BbWindTrees::OnceText(once, sizeof(once));
        BbReport::Printf("%s\n", once);
        BbWindTrees::CutoutOnceText(once, sizeof(once)); // bbport (r89q_twigs-limb-discard)
        BbReport::Printf("%s\n", once);
        BbWindTrees::UnitsOnceText(once, sizeof(once)); // bbport (r89r_twigs-limb-units)
        BbReport::Printf("%s\n", once);
    }
    // bbport (r89r_twigs-limb-units): the limb counts line (why each limb-shaped draw was refused, and the world box verdicts of the
    // twig book's limb entries): at frame UnitsEarlyFrame and with the 600-frame lines. Only called with the trees route on.
    const auto limb_units_line = [&]() {
        BbWindTrees::LimbCensus census;
        twig_book.ForEach([&](std::uint64_t, const BbWindTwigs::Entry& e) {
            if (e.limb) {
                census.Add(e.verdict == BbWindTwigs::Verdict::Waiting, e.verdict == BbWindTwigs::Verdict::Tree, e.why, e.height);
            }
        });
        char units_text[720];
        BbWindTrees::UnitsLineText(trees_stats, census, units_text, sizeof(units_text));
        BbReport::Printf("%s\n", units_text);
    };
    if (BbWindTrees::On() && ++trees_frames == BbWindTrees::UnitsEarlyFrame) {
        limb_units_line();
    }
    if (BbWindTrees::On() && trees_frames % BbWindSway::ReportFrames == 0) {
        char text[704];
        // bbport (r89k_twigs-opaque-word): the limb pieces in the twig book, and those its world box judged trees
        unsigned limb_meshes = 0, limb_trees = 0;
        twig_book.ForEach([&](std::uint64_t, const BbWindTwigs::Entry& e) {
            limb_meshes += e.limb ? 1u : 0u;
            limb_trees += e.limb && e.verdict == BbWindTwigs::Verdict::Tree ? 1u : 0u;
        });
        BbWindTrees::LineText(trees_stats, trees_book, BbWindSway::ReportFrames, limb_meshes, limb_trees, text,
                              sizeof(text));
        BbReport::Printf("%s\n", text);
        BbWindTrees::SizeLineText(trees_stats, text, sizeof(text)); // bbport (r89o_wind-chains-twigs-visible)
        BbReport::Printf("%s\n", text);
        BbWindTrees::GateLineText(trees_stats, text, sizeof(text)); // bbport (r89p_twigs-really-move)
        BbReport::Printf("%s\n", text);
        BbWindTrees::CutoutLineText(trees_stats, text, sizeof(text)); // bbport (r89q_twigs-limb-discard)
        BbReport::Printf("%s\n", text);
        limb_units_line(); // bbport (r89r_twigs-limb-units)
        trees_stats = {};
    }
    GlassPickPoll(); // bbport (r86l_glint-pick-glass, TOOL): BB_GLASS_PICK armed or dropped (live)
    if (glass_tri_job) { // bbport (r86m_glint-pane-from-triangle, TOOL): the readback's lines, once the GPU is past it
        GlassTriReadPoll();
    }
    if (!BbWindTrees::PickOn()) {
        return;
    }
    TreesPick& p = trees_pick;
    const BbWindTrees::PickKnob& knob = BbWindTrees::PickCurrent(); // bbport (r86l): the glass pick's while it is armed
    trees_pick_glass = knob.glass;
    ++p.frame;
    const vk::Device device = instance.GetDevice();
    constexpr u32 queries = BbWindTrees::PickPerGroup * BbWindTrees::PickGroups;
    if (!p.tried) {
        p.tried = true;
        if (instance.IsHostQueryResetSupported()) {
            const vk::QueryPoolCreateInfo info = {
                .queryType = vk::QueryType::eOcclusion,
                .queryCount = queries,
            };
            auto created = device.createQueryPoolUnique(info);
            if (created.result == vk::Result::eSuccess) {
                p.pool = std::move(created.value);
                device.resetQueryPool(*p.pool, 0, queries);
            }
        }
    }
    if (!p.said) {
        p.said = true;
        char once[768];
        BbWindTrees::PickOnceText(knob, once, sizeof(once));
        BbReport::Printf("%s%s\n", once, p.pool ? "" : " (NO host query reset or no query pool: the pick cannot run)");
    }
    if (!p.pool) {
        return;
    }
    if (trees_pick_rect_on) { // this frame drew the patch: its group goes to the GPU
        TreesPickGroup& g = p.groups[p.group];
        if (g.used != 0) {
            // bbport (r89k_twigs-opaque-word): the frame, the camera and how many scissors met the patch (the note line)
            g.frame = object_motion->Frame();
            g.meet = trees_pick_meet;
            g.apart = trees_pick_apart;
            WindHangFindRefresh(g.frame);
            g.cam_ok = hang_find_boxes.camera_ok;
            g.cam = hang_find_boxes.camera;
            g.pending = true;
            g.tick = scheduler.CurrentTick();
            p.group = (p.group + 1) % BbWindTrees::PickGroups;
        }
        trees_pick_rect_on = false;
        trees_pick_meet = 0; // bbport (r89k_twigs-opaque-word)
        trees_pick_apart = 0;
    }
    for (u32 gi = 0; gi < BbWindTrees::PickGroups; ++gi) {
        TreesPickGroup& g = p.groups[gi];
        if (!g.pending || !scheduler.IsFree(g.tick)) {
            continue;
        }
        const u32 n = g.used;
        std::vector<u64> counts(n, u64(0));
        const vk::Result result = device.getQueryPoolResults(*p.pool, gi * BbWindTrees::PickPerGroup, n,
                                                             n * sizeof(u64), counts.data(), sizeof(u64),
                                                             vk::QueryResultFlagBits::e64);
        const BbWindTrees::Point& pt = knob.points[g.point];
        char text[704];
        if (knob.glass) { // bbport (r86l_glint-pick-glass, TOOL): its own lines: every draw that passed, not one winner
            GlassPickGroup(g, counts, result, pt);
        } else if (result != vk::Result::eSuccess) {
            std::snprintf(text, sizeof(text),
                          "Wind twigs pick (r89j): pixel %d,%d: the query results were not available (result %d)", pt.x,
                          pt.y, static_cast<int>(result));
            BbReport::Printf("%s\n", text);
        } else {
            const u64 frame = object_motion->Frame();
            WindHangFindRefresh(frame);
            const auto describe = [&](std::size_t row, std::size_t passed, bool is_under) {
                const BbWindTrees::PickDraw& d = g.draws[row];
                char box[200];
                std::snprintf(box, sizeof(box), "no scene box for the stream");
                if (const BbWindHangFind::Box* const b = hang_find_boxes.Find(d.stream)) {
                    std::snprintf(box, sizeof(box), "scene box y %.1f..%.1f m, %.1f x %.1f m wide",
                                  static_cast<double>(b->box[1]), static_cast<double>(b->box[4]),
                                  static_cast<double>(b->box[3] - b->box[0]), static_cast<double>(b->box[5] - b->box[2]));
                    if (hang_find_boxes.camera_ok) {
                        char tail[96];
                        std::snprintf(tail, sizeof(tail), "; over the camera %.1f..%.1f m",
                                      static_cast<double>(b->box[1] - hang_find_boxes.camera[1]),
                                      static_cast<double>(b->box[4] - hang_find_boxes.camera[1]));
                        std::strncat(box, tail, sizeof(box) - std::strlen(box) - 1);
                    }
                }
                const u64 mesh_key = BbWindTrees::MeshKey(d.stream, d.base, d.index_address, d.indices);
                const BbWindTrees::Mesh* const mesh = trees_book.Find(mesh_key, frame);
                const BbWindTwigs::Entry* const entry =
                    twig_book.Find(mesh != nullptr && mesh->tree ? mesh->addr : d.stream);
                const char* const entry_why = entry != nullptr && entry->why != nullptr ? entry->why : "";
                char book[200];
                std::snprintf(book, sizeof(book), "tree shape: %s; twig book: %s%s%s%s",
                              mesh != nullptr ? (mesh->tree ? "TREE-SHAPED" : mesh->why) : "not judged",
                              entry == nullptr ? "no entry"
                                               : (entry->verdict == BbWindTwigs::Verdict::Tree
                                                      ? "Tree"
                                                      : (entry->verdict == BbWindTwigs::Verdict::NotTree ? "NotTree"
                                                                                                         : "Waiting")),
                              entry_why[0] != '\0' ? " (" : "", entry_why, entry_why[0] != '\0' ? ")" : "");
                char line[704];
                BbWindTrees::PickLine(pt, g.rect, row, g.draws.size(), passed, d, is_under, box, book, line,
                                      sizeof(line));
                BbReport::Printf("%s\n", line);
            };
            const BbWindTrees::PickResult res = BbWindTrees::PickWinner(g.draws, counts.data());
            if (!res.found) {
                BbWindTrees::PickNoneLine(pt, g.rect, g.draws.size(), res.passed, text, sizeof(text));
                BbReport::Printf("%s\n", text);
                if (res.any) { // bbport (r89k_twigs-opaque-word): the last draw with samples, though it wrote no depth
                    describe(res.any_row, res.passed, true);
                }
            } else {
                describe(res.row, res.passed, false);
                for (std::size_t k = 0; k < res.under_n; ++k) {
                    describe(res.under[k], res.passed, true);
                }
            }
        }
        if (result == vk::Result::eSuccess) { // bbport (r89k_twigs-opaque-word): which frame, camera and patch
            BbWindTrees::PickNoteLine(pt, g.rect, knob.out_w, knob.out_h, g.frame, g.cam_ok, g.cam.data(), g.meet,
                                      g.apart, g.draws.size(), text, sizeof(text));
            BbReport::Printf("%s\n", text);
        }
        if (g.skipped != 0) {
            std::snprintf(text, sizeof(text),
                          "Wind twigs pick (r89j): NOTE pixel %d,%d: %u G-buffer draws of that frame had no query (the group "
                          "of %u was full): a late draw may be the real winner",
                          pt.x, pt.y, g.skipped, static_cast<unsigned>(BbWindTrees::PickPerGroup));
            BbReport::Printf("%s\n", text);
        }
        device.resetQueryPool(*p.pool, gi * BbWindTrees::PickPerGroup, n);
        g.pending = false;
        g.used = 0;
        g.skipped = 0;
        g.draws.clear();
    }
    const int point = BbWindTrees::PointAt(p.frame + 1, knob.start, knob.count, knob.repeat); // bbport (r89k)
    if (point >= 0 && camera_motion && !p.groups[p.group].pending) {
        const auto size = camera_motion->RenderSize();
        const BbWindTrees::Rect r = BbWindTrees::PickRect(knob.points[static_cast<std::size_t>(point)], knob.out_w,
                                                          knob.out_h, size[0], size[1]);
        if (r.w > 0 && r.h > 0) {
            trees_pick_rect = vk::Rect2D{.offset = {r.x, r.y}, .extent = {u32(r.w), u32(r.h)}};
            trees_pick_game = r; // bbport (r89l_twigs-palette-move): game-target pixels; the scissor block scales them
            trees_pick_rect_on = true;
            p.groups[p.group].point = static_cast<u32>(point);
            p.groups[p.group].rect = r;
        }
    }
}

// bbport (r86l_glint-pick-glass, TOOL), once a frame before the pick's own work (WindTreesPickFrameEnd): the glass pick's knobs
// (RtShadow::GlassPickRead: live where the test tools' knobs file exists, else the environment) arm or drop it. Armed:
// BbWindTrees::GlassPickState() holds its knob and the first pixel comes BB_GLASS_PICK_FRAME frames after the set, counted in
// the pick's own frames (trees_pick.frame). Dropped: this frame's patch goes (the picture is whole again) and the pick stops.
// A change of another live knob that leaves the five texts as they were does nothing.
void Rasterizer::GlassPickPoll() {
    static RtGlassPick::Texts fresh, last;
    if (!rt_shadow->GlassPickRead(fresh)) {
        return;
    }
    if (std::memcmp(&fresh, &last, sizeof(fresh)) == 0) {
        return;
    }
    last = fresh;
    BbWindTrees::GlassPickLive& live = BbWindTrees::GlassPickState();
    glass_pick_panes = RtGlassPick::ParsePanes(fresh.panes);
    const BbWindTrees::PickKnob knob = RtGlassPick::MakeKnob(fresh, trees_pick.frame);
    if (knob.count == 0) {
        if (live.armed.load(std::memory_order_relaxed)) {
            live.armed.store(false, std::memory_order_relaxed);
            trees_pick_rect_on = false;
            trees_pick_draw = false;
            trees_pick_glass = false;
            trees_pick_meet = 0;
            trees_pick_apart = 0;
            std::printf("GLINT-PROOF glass pick (r86l): BB_GLASS_PICK unset: the pick stops, the picture is whole again\n");
        }
        return;
    }
    live.knob = knob;
    live.armed.store(true, std::memory_order_relaxed);
    trees_pick.said = true; // the twig pick's once-line is for BB_WIND_TWIGS_PICK
    char once[1024];
    RtGlassPick::OnceText(knob, glass_pick_panes, once, sizeof(once));
    std::printf("%s\n", once);
    if (glass_tri_on) { // bbport (r86m_glint-pane-from-triangle, TOOL): the G-buffer's texels at the pixels, once
        glass_tri_read = true;
        glass_tri_gb = {}; // bbport (r86m review): no target ids of an earlier arming (read only after a G-buffer pass)
        glass_tri_depth = {};
    }
}

// bbport (r86l_glint-pick-glass, TOOL): the capture hook's facts of the draw it just prepared (EffectsCaptureDraw, before
// PrepareDraw): the position key and what PrepareDraw will see (a skeleton, a bone palette, own camera constants, solid).
// WindTreesPickQuery uses them when the same draw (its position stream and index count) asks for its query.
void Rasterizer::GlassPickStash(const RtShadow::Draw& draw) {
    GlassPickNote& note = glass_pick_note;
    note.valid = true;
    note.positions = draw.positions;
    note.index_count = draw.index_count;
    note.key = 0;
    if (draw.positions != 0) {
        const std::array<u64, 4> parts{draw.positions, draw.indices, (u64(draw.index_count) << 32) | draw.first_vertex,
                                       u64(draw.instances)};
        note.key = XXH3_64bits(parts.data(), sizeof(parts));
    }
    note.flags = (draw.skinned ? RtGlassPick::FlagSkinned : 0u) | (draw.palette != 0 ? RtGlassPick::FlagBonePalette : 0u) |
                 (draw.constants != nullptr ? RtGlassPick::FlagOwnCamera : 0u) | (draw.solid ? RtGlassPick::FlagSolid : 0u);
}

// bbport (r86l_glint-pick-glass, TOOL): one pick pixel's group of queries, read once the GPU passed it: the header line, the last
// RtGlassPick::RowsShown draws that had samples in draw order (with what the scene's entry list says of each, the index
// list's span and use, and for a box over 100 m a cause line), and for a pane pixel the draws taken as panes (a G-buffer draw
// by its mesh key, a forward draw by its shader pair) or why not.
void Rasterizer::GlassPickGroup(const TreesPickGroup& g, const std::vector<u64>& counts, vk::Result result,
                                const BbWindTrees::Point& pt) {
    char line[1100];
    if (result != vk::Result::eSuccess) {
        std::printf("GLINT-PROOF glass pick (r86l): pixel %d,%d: the query results were not available (result %d)\n", pt.x,
                    pt.y, static_cast<int>(result));
        return;
    }
    const u64 frame = object_motion->Frame();
    std::vector<std::size_t> rows;
    std::size_t gbuffer = 0, forward = 0;
    for (std::size_t i = 0; i < g.draws.size() && i < counts.size(); ++i) {
        if (counts[i] == 0) {
            continue;
        }
        rows.push_back(i);
        if ((g.draws[i].glass_flags & RtGlassPick::FlagGBuffer) != 0) {
            ++gbuffer;
        } else {
            ++forward;
        }
    }
    const bool pane_pixel = RtGlassPick::PaneAt(glass_pick_panes, pt);
    RtGlassPick::HeaderLine(pt, g.rect, g.draws.size(), rows.size(), gbuffer, forward, g.skipped, frame, pane_pixel, line,
                            sizeof(line));
    std::printf("%s\n", line);
    const std::size_t first_shown = rows.size() > RtGlassPick::RowsShown ? rows.size() - RtGlassPick::RowsShown : 0;
    std::size_t last_gbuffer = rows.size(); // bbport (r86m_glint-pane-from-triangle, TOOL): the last G-buffer draw with samples is the surface seen
    for (std::size_t n = 0; n < rows.size(); ++n) {
        if ((g.draws[rows[n]].glass_flags & RtGlassPick::FlagGBuffer) != 0) {
            last_gbuffer = n;
        }
    }
    for (std::size_t n = 0; n < rows.size(); ++n) {
        const std::size_t i = rows[n];
        const BbWindTrees::PickDraw& d = g.draws[i];
        const bool shown = n >= first_shown;
        std::array<RtGlassPick::EntryView, RtGlassPick::EntriesShown> views;
        const u32 found = d.mesh != 0 ? rt_shadow->GlassPickEntries(d.mesh, views.data(), u32(views.size())) : 0u;
        RtGlassPick::IndexUse use;
        if (shown && found != 0 && (d.glass_flags & RtGlassPick::FlagIndexed) != 0 && d.index_address != 0 && d.indices != 0 &&
            d.index_size != 0) {
            const u64 bytes = u64(d.indices) * d.index_size;
            if (memory->IsValidGpuMapping(d.index_address, 0) && memory->ClampRangeSize(d.index_address, bytes) == bytes) {
                use = RtGlassPick::ScanIndices(reinterpret_cast<const void*>(d.index_address), d.indices, d.index_size);
            }
        }
        if (shown) {
            RtGlassPick::DrawLine(pt, n + 1, rows.size(), counts[i], d, views.data(), found, use, line, sizeof(line));
            std::printf("%s\n", line);
            if (BbWindHang::ProofOn() || BbWindHangRoute::On()) { // bbport (r112r_hang-bracket-judge, TOOL): what the Motion block did with this pair
                std::printf("%s\n", hang_tint.PickText(pt.x, pt.y, d.vs, d.ps, BbWindHang::ProofOn()).c_str());
            }
            if (found != 0 && views[0].has_bounds && RtGlassPick::Diagonal(views[0]) > RtGlassPick::BogusMetres) {
                RtGlassPick::BoundsLine(pt, d, views[0], use, line, sizeof(line));
                std::printf("%s\n", line);
            }
        }
        if (!pane_pixel) {
            continue;
        }
        if (RtGlassTri::On()) { // bbport (r86m_glint-pane-from-triangle, TOOL): a pane pixel's surface is cut into a pane by its triangles
            if (n == last_gbuffer) {
                const char* note = nullptr;
                const char* reason = nullptr;
                if (!RtGlassOn()) {
                    reason = "BB_RT_GLASS is off: nothing is taken (set it, for example auto)";
                } else if (d.mesh == 0 || found == 0) {
                    reason = "not wanted: the mesh has no entry in the ray traced scene (no solid entry to copy the world "
                             "positions from)";
                } else if ((d.glass_flags & RtGlassPick::FlagSkinned) != 0 || d.instances != 1) {
                    reason = "not wanted: a skinned or instanced draw";
                } else if (rt_shadow->GlassTriWant(d.mesh, pt.x, pt.y, note) || note != nullptr) {
                    reason = note;
                }
                if (reason != nullptr) {
                    std::snprintf(line, sizeof(line),
                                  "GLINT-PROOF glass pick (r86m): triangle route: pixel %d,%d, last G-buffer draw vs:ps %08x:%08x "
                                  "mesh key %016llx, %u scene entr%s: %s",
                                  pt.x, pt.y, d.vs, d.ps, static_cast<unsigned long long>(d.mesh), found, found == 1 ? "y" : "ies",
                                  reason);
                    std::printf("%s\n", line);
                }
            }
            continue;
        }
        const RtGlassPick::Verdict verdict = RtGlassPick::PaneVerdict(d, glass_pick_panes.mode);
        if (verdict != RtGlassPick::Verdict::Take) {
            if (shown) {
                RtGlassPick::PaneLine(pt, d, verdict, false, "", line, sizeof(line));
                std::printf("%s\n", line);
            }
            continue;
        }
        const char* how = "";
        bool took = false;
        if (!RtGlassOn()) {
            how = "BB_RT_GLASS is off: nothing is taken (set it, for example auto)";
        } else if ((d.glass_flags & RtGlassPick::FlagGBuffer) != 0) {
            took = rt_shadow->GlassPickTake(d.mesh);
            how = took ? "G-buffer draw: its mesh key joins the pane keys; its next draws are made pane records of their own "
                         "vertices (the r86i/r86k box pane route; no entry bound is used)"
                       : "this mesh key was taken before, or the table of 32 keys is full";
        } else {
            took = RtGlassPickAdd(d.pair_vs, d.pair_ps);
            how = took ? "forward draw: its shader pair joins the capture list; its pipeline is made again with a capture "
                         "variant at the next draw, and every draw of the pair is a pane record"
                       : "this shader pair was taken before, or the table of 16 pairs is full";
        }
        if (took || shown) {
            RtGlassPick::PaneLine(pt, d, verdict, took, how, line, sizeof(line));
            std::printf("%s\n", line);
        }
    }
}

// bbport (r89i_twigs-colour-pass, TOOL; BB_WIND_TWIGS_CENSUS=1): one draw of the G-buffer or a sun shadow pass
// for the census (bbport_wind_census.h): the pipeline's row (render target kind, colour targets and first format,
// depth, shader hashes, cut-out, motion pipeline, sway bit, position stream) is made the first time, the draw is
// counted (indices, the largest draw's first index and base vertex, its kind, whether it got a sway word) and the
// first draw of a row has its index values' range read from guest memory (at most BbWindCensus::RangeScanMax
// indices, once a row and report). Draws of other passes are left out. On the thread recording draws.
void Rasterizer::WindTwigCensus(const GraphicsPipeline* pipeline, const AmdGpu::Regs& regs, bool is_indexed,
                                u32 index_offset, int kind_slot, u32 sway, int base_vertex) {
    const auto& key = pipeline->GetGraphicsKey();
    const u32 colour = key.mrt_mask & ~(1u << Shader::MotionVectors::Output);
    BbWindCensus::Target target = BbWindCensus::Target::Gbuffer;
    if (!gbuffer_draw) {
        const bool sun_pass = colour == 0 && regs.depth_buffer.DepthValid() &&
                              regs.depth_buffer.Pitch() == regs.depth_buffer.Height() &&
                              regs.depth_buffer.Height() >= 1024;
        if (!sun_pass) {
            return;
        }
        target = BbWindCensus::Target::Sun;
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto& fetch = pipeline->GetFetchShader();
    u64 positions = 0;
    u32 positions_size = 0;
    u32 positions_stride = 0;
    if (fetch) {
        for (const auto& attribute : fetch->attributes) {
            if (attribute.semantic == 0) {
                const auto stream = attribute.GetSharp(vs);
                positions = stream.base_address;
                positions_size = stream.GetSize();
                positions_stride = stream.GetStride();
                break;
            }
        }
    }
    ++twig_census.draws[target == BbWindCensus::Target::Gbuffer ? 0 : 1];
    bool fresh = false;
    BbWindCensus::Row* const row =
        twig_census.Touch(reinterpret_cast<std::uintptr_t>(pipeline), positions, fresh);
    if (row == nullptr) {
        return;
    }
    if (fresh) {
        const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        row->vs = static_cast<u32>(vs.pgm_hash & 0xffffffffu);
        row->ps = static_cast<u32>(FragmentHash(pipeline) & 0xffffffffu);
        row->target = target;
        row->targets = static_cast<u32>(std::popcount(colour));
        row->format = colour != 0 ? static_cast<u32>(key.color_buffers[std::countr_zero(colour)].data_format) : 0u;
        row->depth_w = regs.depth_buffer.Pitch();
        row->depth_h = regs.depth_buffer.Height();
        row->cutout = ps != nullptr && ps->has_discard;
        row->sway_bit = (key.motion_vectors & Shader::MotionVectors::Sway) != 0;
        row->motion = (key.motion_vectors & Shader::MotionVectors::VertexOutputs) != 0;
        row->depth_write = regs.depth_control.depth_write_enable != 0;
        row->stride = positions_stride;
        row->stream_verts = positions_stride != 0 ? positions_size / positions_stride : 0u;
    }
    BbWindCensus::Count(*row, static_cast<std::size_t>(kind_slot), regs.num_indices, index_offset, base_vertex,
                        sway != 0);
    if (!row->ranged && is_indexed && regs.num_indices != 0) {
        row->ranged = true;
        const u32 index_size = regs.index_buffer_type.index_type == AmdGpu::IndexType::Index16 ? 2u : 4u;
        const VAddr address = regs.index_base_address.Address<VAddr>() + u64(index_offset) * index_size;
        const u64 bytes = u64(regs.num_indices) * index_size;
        if (memory->IsValidGpuMapping(address, 0) && memory->ClampRangeSize(address, bytes) == bytes) {
            const unsigned char* const data = reinterpret_cast<const unsigned char*>(address);
            const u32 count = std::min<u32>(regs.num_indices, BbWindCensus::RangeScanMax);
            u32 lo = 0xffffffffu;
            u32 hi = 0;
            for (u32 i = 0; i < count; ++i) {
                u32 value = 0;
                if (index_size == 2) {
                    u16 narrow = 0;
                    std::memcpy(&narrow, data + u64(i) * 2, sizeof(narrow));
                    value = narrow == 0xffffu ? 0xffffffffu : u32(narrow); // the restart index is no vertex
                } else {
                    std::memcpy(&value, data + u64(i) * 4, sizeof(value));
                }
                if (value == 0xffffffffu) {
                    continue;
                }
                lo = std::min(lo, value);
                hi = std::max(hi, value);
            }
            if (lo <= hi) {
                row->vmin = lo;
                row->vmax = hi;
            }
        }
    }
}

// bbport (r89d_tree-twigs): the twigs' line every BbWindSway::ReportFrames frame ends: the census
// of the meshes in use (the GPU's keys of each slot, read here: mapped memory is slow, once in 600
// frames), the counts of the draws and the tip move at the wind now.
void Rasterizer::WindTwigsReport() {
    u32* const words = object_motion->SwayWords();
    if (words == nullptr) {
        return;
    }
    BbWindTwigs::Census census;
    sway_slots.ForEachInUse(object_motion->Frame(), [&](u32 slot, u64 stream, u32 size) {
        const BbWindTwigs::Measure m = BbWindTwigs::MeasureOf(BbWindTwigs::ReadKeys(words, slot));
        const float height = m.crown - m.base;
        if (!m.ok || height < BbWindSway::TreeLo) {
            return;
        }
        if (height > BbWindTwigs::SmallMaxH) { // bbport (r89e): over 40 m: no tree
            census.Huge(height);
            return;
        }
        const BbWindTwigs::Entry* const entry = twig_book.Find(stream);
        if (entry != nullptr && entry->small) { // bbport (r89e): a static cut-out candidate
            if (entry->verdict == BbWindTwigs::Verdict::Tree) {
                ++census.small;
                census.Tall(height);
            } else if (entry->verdict == BbWindTwigs::Verdict::Waiting) {
                ++census.small_wait;
            }
        } else if (entry != nullptr && entry->verdict == BbWindTwigs::Verdict::Tree) {
            ++census.sun;
            census.Tall(height);
        } else if (rt_shadow->LonePlant(stream, size)) {
            ++census.lone;
            census.Tall(height);
        } else if (entry != nullptr) {
            ++census.sun_not;
        }
    });
    char text[512];
    BbWindTwigs::Knob knob = BbWindTwigs::KnobOnce();
    knob.twigs = WindTwigsNow(); // BB_WIND_TWIGS as it is now (the live knobs)
    BbWindTwigs::LineText(census, twig_stats, wind.Get(), knob,
                          BbWindSway::KnobOnce().scale, BbWindSway::LeanKnobOnce().wave, text,
                          sizeof(text));
    BbReport::Printf("%s\n", text);
    if (BbWindTwigs::ReachSmall()) { // bbport (r89e_twigs-big-trees): the candidates' line
        char small_text[320];
        BbWindTwigs::SmallReportText(census, twig_stats, BbWindTwigs::KnobOnce(), small_text,
                                     sizeof(small_text));
        BbReport::Printf("%s\n", small_text);
    }
    if (BbWindTwigs::SizeOn()) { // bbport (r89f_twigs-scale): the size-scaled tips' line
        char size_text[320];
        BbWindTwigs::SizeReportText(census, twig_stats, wind.Get(), knob,
                                    BbWindSway::KnobOnce().scale, BbWindSway::LeanKnobOnce().wave,
                                    size_text, sizeof(size_text));
        BbReport::Printf("%s\n", size_text);
    }
    if (BbWindTwigs::PushOn()) { // bbport (r89h_twigs-alive): the push rule's line
        char push_text[400];
        BbWindTwigs::PushReportText(twig_stats, wind.Get(), knob, BbWindSway::KnobOnce().scale, push_text,
                                    sizeof(push_text));
        BbReport::Printf("%s\n", push_text);
    }
    if (BbWindTwigs::ProofOn()) { // bbport (r89g_twigs-proof, TOOL): a proof line per tree mesh, then the counters at 0
        u32 lines = 0;
        BbWindTwigs::OffsetTotals palette_total, static_total; // bbport (r89l_twigs-palette-move): every tree mesh counts
        sway_slots.ForEachInUse(object_motion->Frame(), [&](u32 slot, u64 stream, u32) {
            const BbWindTwigs::Entry* const entry = twig_book.Find(stream);
            if (entry == nullptr || entry->verdict != BbWindTwigs::Verdict::Tree) {
                return;
            }
            {
                const BbWindTwigs::SmallInfo* const offset_info = twig_book.FindInfo(stream);
                const auto offset_found = twig_proof_draws.find(stream);
                const TwigProofDraws offset_draws =
                    offset_found != twig_proof_draws.end() ? offset_found->second : TwigProofDraws{};
                BbWindTwigs::OffsetTotals& total = offset_info != nullptr && offset_info->palette ? palette_total : static_total;
                total.Add(offset_draws.draws, offset_draws.gbuffer, BbWindTwigs::ReadOffset(words, slot),
                          offset_info != nullptr ? static_cast<std::uint32_t>(offset_info->vs & 0xffffffffu) : 0u,
                          offset_info != nullptr ? BbWindTwigs::ShaderPathOf(offset_info->vs) : std::uint8_t{0});
            }
            BbWindTwigs::ClearOffset(words, slot);
            if (lines >= BbWindTwigs::ProofLines) { // only the first ProofLines meshes have a line of their own
                BbWindTwigs::ClearProof(words, slot);
                return;
            }
            ++lines;
            const BbWindTwigs::SmallInfo* const info = twig_book.FindInfo(stream);
            const auto found = twig_proof_draws.find(stream);
            const TwigProofDraws seen = found != twig_proof_draws.end() ? found->second : TwigProofDraws{};
            char proof_text[1024]; // bbport (r89h_twigs-alive): the line grew by the time motion
            BbWindTwigs::ProofLine(BbWindTwigs::ReadProof(words, slot), slot, seen.draws, seen.patched,
                                   seen.pipelines, info != nullptr ? info->verts : 0u, proof_text,
                                   sizeof(proof_text));
            BbReport::Printf("%s\n", proof_text);
            BbWindTwigs::ClearProof(words, slot);
        });
        // bbport (r89l_twigs-palette-move, TOOL): the twig offset of every tree mesh of the window
        static bool offset_said = false;
        if (!offset_said) {
            offset_said = true;
            char offset_once[704];
            BbWindTwigs::OffsetOnceText(offset_once, sizeof(offset_once));
            BbReport::Printf("%s\n", offset_once);
        }
        char offset_text[1400];
        BbWindTwigs::OffsetLine(palette_total, static_total, offset_text, sizeof(offset_text));
        BbReport::Printf("%s\n", offset_text);
        twig_proof_draws.clear();
    }
    // bbport (r89i_twigs-colour-pass): its once line (with the first report), and with BB_WIND_TWIGS_CENSUS=1 (TOOL) the
    // colour passes' census: a header line and the rows (BbWindCensus::Pick), then the book is emptied
    static bool census_said = false;
    if (!census_said) {
        census_said = true;
        char census_once[704];
        BbWindCensus::OnceText(BbWindCensus::KnobOnce(), census_once, sizeof(census_once));
        BbReport::Printf("%s\n", census_once);
    }
    if (BbWindCensus::CensusOn()) {
        char census_text[704];
        BbWindCensus::HeaderLine(twig_census, BbWindCensus::PaletteOn(), BbWindCensus::KnobOnce(), census_text,
                                 sizeof(census_text));
        BbReport::Printf("%s\n", census_text);
        unsigned census_rank = 0;
        for (const BbWindCensus::Row* const census_row : BbWindCensus::Pick(twig_census)) {
            BbWindCensus::RowLine(*census_row, ++census_rank, BbWindCensus::PaletteOn(), census_text,
                                  sizeof(census_text));
            BbReport::Printf("%s\n", census_text);
        }
        twig_census.Clear();
    }
    twig_stats = {};
}

// bbport (r89_wind-foliage-sway): the knob's line once (nothing with BB_WIND off: r82's line says
// it), then with the sway on a line of counts every BbWindSway::ReportFrames frame ends.
void Rasterizer::WindSwayFrameEnd() {
    static const bool on = [] {
        const auto& knob = BbWindSway::KnobOnce();
        if (knob.on) {
            BbReport::Printf(
                "Wind sway (r89, BB_WIND=1): plants sway (cut-outs with a skeleton that no sun "
                "shadow pass draws, as the ray traced scene finds them; none without ray tracing), "
                "scale %.2f, gusts %.2f: full sway %.2f m above a mesh's lowest point, lean %.3f m, "
                "swing %.3f m at %.1f Hz along the wind and %.3f m at %.1f Hz across it at 1.5 m/s\n",
                double(knob.scale), double(knob.gusts), double(BbWindSway::Height),
                double(BbWindSway::Lean * knob.scale), double(BbWindSway::Flutter * knob.scale),
                double(BbWindSway::SwayHz), double(BbWindSway::Cross * knob.scale),
                double(BbWindSway::CrossHz));
            char ripple[512]; // bbport (r89b_wind-sway-ripple): which motion runs
            if (BbWindSway::LeanKnobOnce().lean) { // bbport (r89c_wind-lean): its two lines
                char table[512];
                BbWindSway::LeanTableText(BbWindSway::LeanKnobOnce(), BbWindSway::RippleKnobOnce(),
                                          knob.scale, table, sizeof(table));
                BbReport::Printf("%s\n", table);
                BbWindSway::LeanOnceText(BbWindSway::LeanKnobOnce(), BbWindSway::RippleKnobOnce(),
                                         knob.scale, ripple, sizeof(ripple));
            } else {
                BbWindSway::RippleOnceText(BbWindSway::RippleKnobOnce(), knob.scale, ripple,
                                           sizeof(ripple));
            }
            BbReport::Printf("%s\n", ripple);
        } else if (knob.wind) {
            BbReport::Printf("Wind sway (r89): off (BB_WIND_SWAY=0); no plant sways\n");
        }
        return knob.on;
    }();
    // bbport (r89d_tree-twigs): BB_WIND_TWIGS's line once (nothing with BB_WIND off)
    static bool twigs_said = false;
    if (!twigs_said && BbWindSway::KnobOnce().on) {
        twigs_said = true;
        char twigs[512];
        if (BbWindTwigs::On()) {
            BbWindTwigs::OnceText(BbWindTwigs::KnobOnce(), BbWindSway::KnobOnce().scale,
                                  BbWindSway::LeanKnobOnce().wave, twigs, sizeof(twigs));
        } else {
            std::snprintf(twigs, sizeof(twigs),
                          "Wind twigs (r89d): off (BB_WIND_TWIGS=0, or BB_WIND_SWAY_STYLE=wave); "
                          "trees as with r89c");
        }
        BbReport::Printf("%s\n", twigs);
        if (BbWindTwigs::ReachSmall()) { // bbport (r89e_twigs-big-trees)
            char small_once[320];
            BbWindTwigs::SmallOnceText(BbWindTwigs::KnobOnce(), small_once, sizeof(small_once));
            BbReport::Printf("%s\n", small_once);
        }
        if (BbWindTwigs::SizeOn()) { // bbport (r89f_twigs-scale)
            char size_once[640];
            BbWindTwigs::SizeOnceText(BbWindTwigs::KnobOnce(), BbWindSway::KnobOnce().scale,
                                      BbWindSway::LeanKnobOnce().wave, size_once,
                                      sizeof(size_once));
            BbReport::Printf("%s\n", size_once);
        }
        if (BbWindTwigs::On()) { // bbport (r89g_twigs-proof): the fit rule's line, and the proof knob's
            char fit_once[640];
            BbWindTwigs::FitOnceText(BbWindTwigs::KnobOnce(), fit_once, sizeof(fit_once));
            BbReport::Printf("%s\n", fit_once);
            BbWindTwigs::CapOnceText(fit_once, sizeof(fit_once)); // bbport (r89m_twigs-no-tear)
            BbReport::Printf("%s\n", fit_once);
            if (BbWindTwigs::ProofOn()) {
                BbWindTwigs::ProofOnceText(fit_once, sizeof(fit_once));
                BbReport::Printf("%s\n", fit_once);
            }
            BbWindTwigs::PushOnceText(BbWindTwigs::KnobOnce(), BbWindSway::KnobOnce().scale, fit_once,
                                      sizeof(fit_once)); // bbport (r89h_twigs-alive)
            BbReport::Printf("%s\n", fit_once);
        }
    }
    // bbport (r112_wind-more-things): BB_WIND_HANG's line once, with the wind's speed then
    static bool hang_said = false;
    if (!hang_said && BbWindHang::KnobOnce().asked) {
        hang_said = true;
        char hang[512];
        if (BbWindHang::KnobOnce().on) {
            BbWindHang::OnceText(wind.Get().speed, BbWindSway::KnobOnce().scale, hang,
                                 sizeof(hang));
        } else {
            std::snprintf(hang, sizeof(hang),
                          "Wind sway hang (r112): off (BB_WIND_HANG=1 needs BB_WIND=1 and "
                          "BB_WIND_SWAY above 0); nothing hangs");
        }
        BbReport::Printf("%s\n", hang);
    }
    // bbport (r112s_hang-bracket-move): BB_WIND_HANG_POST's line once
    static bool hang_post_said = false;
    if (!hang_post_said && BbWindHang::PostOn()) {
        hang_post_said = true;
        char post_once[1024];
        BbWindHang::PostOnceText(post_once, sizeof(post_once));
        BbReport::Printf("%s\n", post_once);
    }
    // bbport (r112e_hang-taken): its line once (BB_WIND_HANG on)
    static bool hang_taken_said = false;
    if (!hang_taken_said && BbWindHang::KnobOnce().on) {
        hang_taken_said = true;
        BbReport::Printf("Wind sway hang (r112e): palettes judged by content (0.001 of the first "
                         "frame), moved or unread streams judged afresh every %u frames, over %u "
                         "bones never; palettes the GPU wrote, not in place: %s; groups line every "
                         "%u frames\n",
                         static_cast<unsigned>(BbWindHangStill::RejudgeFrames),
                         BbWindHangStill::CharacterBones,
                         BbWindHangStill::ReadFlagged() ? "read anyway (BB_WIND_HANG_READ_GPU=1)"
                                                        : "not read",
                         BbWindSway::ReportFrames);
    }
    // bbport (r112f_hang-gpu-judge): its line once (BB_WIND_HANG on)
    static bool hang_gpu_said = false;
    if (!hang_gpu_said && BbWindHang::KnobOnce().on) {
        hang_gpu_said = true;
        BbReport::Printf("Wind sway hang (r112f): stillness judged on the GPU by the mesh's world "
                         "box (the sway keys): it must hold within %.0f mm over %u frames (watched "
                         "every %u), 250 mm or more is a character for good (box keys: %s); line "
                         "every %u frames\n",
                         double(BbWindHangStill::BoxTol()) * 1000.0,
                         static_cast<unsigned>(BbWindHangStill::BoxStillFrames),
                         static_cast<unsigned>(BbWindHangStill::BoxCheckFrames),
                         BbWindHangStill::BoxAvailable() ? "on"
                                                         : "OFF, BB_WIND_TWIGS=0: GPU-written "
                                                           "palettes stay unread",
                         BbWindSway::ReportFrames);
    }
    // bbport (r112h_hang-not-the-hunter): its line once (BB_WIND_HANG on)
    static bool hang_actors_said = false;
    if (!hang_actors_said && BbWindHang::KnobOnce().on) {
        hang_actors_said = true;
        const BbWindHangActors::Knobs& actors = BbWindHangActors::KnobOnce();
        if (actors.on) {
            BbReport::Printf("Wind sway hang (r112h): not on the hunter (within %.1f m, "
                             "BB_WIND_HANG_NEAR), not a figure (over %u bones, BB_WIND_HANG_BONES), "
                             "not indoors (open wind share at the camera %.2f or less, "
                             "BB_WIND_HANG_INDOOR), placed; keyless streams held %u frames; lines "
                             "every %u frames\n",
                             double(actors.near_m), actors.bones, double(actors.indoor),
                             static_cast<unsigned>(BbWindHangActors::KeylessHoldFrames),
                             BbWindSway::ReportFrames);
        } else {
            BbReport::Printf("Wind sway hang (r112h): OFF (BB_WIND_HANG_ACTORS=0): as r112g\n");
        }
    }
    // bbport (r112i_hang-find-lanterns): its line once (BB_WIND_HANG on)
    static bool hang_find_said = false;
    if (!hang_find_said && BbWindHang::KnobOnce().on) {
        hang_find_said = true;
        BbReport::Printf("%s\n", BbWindHangFind::OnceText(BbWindHangFind::KnobOnce()).c_str());
        BbReport::Printf("%s\n", BbWindHangFind::OnceTextJ(BbWindHangFind::KnobOnce(),
                                                           BbWindHangFind::RoofKnob(),
                                                           BbWindHangActors::KnobOnce().indoor)
                                     .c_str()); // bbport (r112j_hang-static-verts)
        BbReport::Printf("%s\n", BbWindHangFind::OnceTextK(BbWindHangFind::KnobOnce(),
                                                           BbWindHangFind::GpuOn(),
                                                           BB_WIND_TWIGS_LIVE != 0,
                                                           BbWindHangFind::UnionKnob())
                                     .c_str()); // bbport (r112k_hang-lantern-verdict)
        BbReport::Printf("%s\n", BbWindHangFind::OnceTextL(BbWindHangFind::CutOn(), BbWindHangFind::GainKnob(),
                                                           BbWindHangFind::TallKnob())
                                     .c_str()); // bbport (r112l_hang-discard-lanterns)
        BbReport::Printf("%s\n", BbWindHangFind::OnceTextM(BbWindHangFind::SameKnob(), BbWindHang::ProofOn(),
                                                           BbWindHangFind::TallKnob())
                                     .c_str()); // bbport (r112m_hang-close-proof)
    }
    // bbport (r112p_hang-gpu-palette-lanterns): its line once (BB_WIND_HANG on)
    static bool hang_boxj_said = false;
    if (!hang_boxj_said && BbWindHang::KnobOnce().on) {
        hang_boxj_said = true;
        BbReport::Printf("%s\n", BbWindHangGpu::OnceText(BbWindHangGpu::ModeOnce(), BbWindHangGpu::BoxBones(),
                                                          BbWindHangFind::GainKnob(),
                                                          BbWindHangFind::GainKnob() * BbWindSway::MaxAlong)
                                    .c_str());
    }
    // bbport (r112g_hang-judge-settles): its line once (BB_WIND_HANG on)
    static bool hang_settles_said = false;
    if (!hang_settles_said && BbWindHang::KnobOnce().on) {
        hang_settles_said = true;
        BbReport::Printf("Wind sway hang (r112g): meshes from %.2f m tall hang (under %.1f m their "
                         "top, distance and push scale down); GPU judge at once; the y keys alone "
                         "after %u frames without the box keys; gives up after %u frames without a "
                         "key; verdicts kept %u frames; line every %u frames\n",
                         double(BbWindHang::MinExtent), double(BbWindHang::HangFull),
                         static_cast<unsigned>(BbWindHangStill::BoxBoxWaitFrames),
                         static_cast<unsigned>(BbWindHangStill::BoxGiveUpFrames),
                         static_cast<unsigned>(BbWindHangStill::RejudgeFrames),
                         BbWindSway::ReportFrames);
    }
    if (!on || ++sway_frames % BbWindSway::ReportFrames != 0) {
        return;
    }
    const auto n = [](u64 v) { return static_cast<unsigned long long>(v); };
    const BbWindSway::Stats& s = sway_stats;
    char ripple[256]; // bbport (r89b_wind-sway-ripple): the ripple's state, first in the line
    if (BbWindSway::LeanKnobOnce().lean) { // bbport (r89c_wind-lean): the lean's state
        BbWindSway::LeanText(BbWindSway::LeanKnobOnce(), BbWindSway::RippleKnobOnce(), wind.Get(),
                             BbWindSway::KnobOnce().scale, s.rippled_views, ripple,
                             sizeof(ripple));
    } else {
        BbWindSway::RippleText(BbWindSway::RippleKnobOnce(), wind.Get(), s.rippled_views, ripple,
                               sizeof(ripple));
    }
    BbReport::Printf("Wind sway (r89): %s; in %u frames %llu draws of sway pipelines with a "
                     "skeleton, "
                     "%llu of plants, %llu swayed (%llu ramping in); not swayed: %llu without ray "
                     "tracing, %llu without a camera, %llu with the views full, %llu without a "
                     "base slot, %llu without the sway words; base slots in use %u of %u\n",
                     ripple, BbWindSway::ReportFrames, n(s.draws), n(s.plants), n(s.swayed),
                     n(s.ramping),
                     n(s.no_rt), n(s.no_camera), n(s.views_full), n(s.no_slot), n(s.no_region),
                     sway_slots.InUse(sway_frame), BbWindSway::PlantSlots); // (r89c)
    sway_stats = {};
    if (BbWindTwigs::On()) { // bbport (r89d_tree-twigs): its line
        WindTwigsReport();
    }
    if (BbWindHang::KnobOnce().on) { // bbport (r112_wind-more-things): its two lines
        char hang[512];
        BbWindHang::LineText(hang_stats, hang_book, hang_push.Now(), hang, sizeof(hang));
        BbReport::Printf("%s\n", hang);
        BbWindHang::MeshesText(hang_book, object_motion->Frame(), hang, sizeof(hang));
        BbReport::Printf("%s\n", hang);
        if (BbWindHang::PostOn()) { // bbport (r112s_hang-bracket-move): the posts' line
            char post_line[640];
            BbWindHang::PostLineText(hang_post, hang_push.Now(), post_line, sizeof(post_line));
            BbReport::Printf("%s\n", post_line);
            char post_box_line[704]; // bbport (r112t_hang-post-measure): the box the keys come from
            BbWindHang::PostBoxLineText(hang_post, post_box_line, sizeof(post_box_line));
            BbReport::Printf("%s\n", post_box_line);
            if (BbWindHang::LanternAsked()) { // bbport (r112v_lantern-hangs)
                char lantern_line[768];
                BbWindLantern::LineText(BbWindLantern::Global(), lantern_line, sizeof(lantern_line));
                BbReport::Printf("%s\n", lantern_line);
            }
            if (BbWindHang::PostGuardOn()) { // bbport (r112u_hang-post-no-bridge)
                char post_guard_line[640];
                BbWindHang::PostGuardLineText(hang_post, post_guard_line, sizeof(post_guard_line));
                BbReport::Printf("%s\n", post_guard_line);
            }
        }
        if (BbWindHangProbe::On()) { // bbport (r112b_hang-probe, TOOL)
            WindHangProbeReport();
        }
        std::string still_line; // bbport (r112d_hang-still-test): groups by bones, once
        if (hang_still.Report(hang_book, object_motion->Frame(), still_line)) {
            BbReport::Printf("%s\n", still_line.c_str());
        }
        std::string box_line; // bbport (r112f_hang-gpu-judge): the GPU judge's line
        if (BbWindHangStill::BoxAvailable() &&
            hang_box.Report(hang_book, hang_still, object_motion->Frame(), box_line)) {
            BbReport::Printf("%s\n", box_line.c_str());
        }
        std::string cause_line; // bbport (r112g_hang-judge-settles): why streams do not settle
        if (BbWindHangStill::BoxAvailable() && hang_box.Causes(cause_line)) {
            BbReport::Printf("%s\n", cause_line.c_str());
        }
        for (const BbWindHangStill::GiveUpNote& note : hang_box.Notes()) {
            BbReport::Printf("Wind sway hang (r112g): no key offered: stream %llx slot %u size %u "
                             "after %llu frames, drawn on %llu (%llu draws); keys base %08x crown "
                             "%08x box %08x %08x %08x %08x top %08x\n",
                             static_cast<unsigned long long>(note.stream), note.slot, note.size,
                             static_cast<unsigned long long>(note.frames),
                             static_cast<unsigned long long>(note.drawn),
                             static_cast<unsigned long long>(note.draws), note.keys[0],
                             note.keys[1], note.keys[2], note.keys[3], note.keys[4], note.keys[5],
                             note.keys[6]);
        }
        if (BbWindHangActors::KnobOnce().on) {
            // bbport (r112h_hang-not-the-hunter): the facts of each keyless give-up, then its lines
            std::string fact_line;
            for (const BbWindHangStill::GiveUpNote& note : hang_box.Notes()) {
                if (hang_actors.FactsText(note.stream, fact_line)) {
                    BbReport::Printf("%s\n", fact_line.c_str());
                }
            }
            std::string first_line, second_line;
            hang_actors.Lines(object_motion->Frame(), wind_shelter != nullptr,
                              hang_box.Keyless(object_motion->Frame()), first_line, second_line);
            BbReport::Printf("%s\n%s\n", first_line.c_str(), second_line.c_str());
        }
        if (BbWindHangFind::StaticOn()) { // bbport (r112i_hang-find-lanterns): the static path's line
            const std::string static_line = BbWindHangFind::StaticLine(
                hang_find_stats, hang_static_book, BbWindHangFind::KnobOnce(), BbWindSway::ReportFrames);
            BbReport::Printf("%s\n", static_line.c_str());
            // bbport (r112j_hang-static-verts): the candidates and the numbers the vertex test compared
            BbReport::Printf("%s\n",
                             BbWindHangFind::TakenLine(hang_static_book, BbWindHangFind::KnobOnce(),
                                                       hang_find_stats)
                                 .c_str());
            // bbport (r112k_hang-lantern-verdict): the GPU-palette draws, skinned refusals, the push's source and
            // the candidates' measures
            const BbWind::Snapshot hang_snap = wind.Get();
            const auto& hang_knob = BbWindSway::KnobOnce();
            const BbWindHangFind::PushSource hang_source = BbWindHangFind::PushSourceOf(
                hang_snap.on, hang_snap.speed,
                BbWind::GustOf(hang_snap, hang_snap.time, hang_knob.gusts), hang_knob.scale);
            BbReport::Printf("%s\n", BbWindHangFind::KLine(hang_find_stats, hang_static_book,
                                                           hang_find_routes, BbWindHangFind::GpuOn(),
                                                           hang_source)
                                         .c_str());
            BbReport::Printf("%s\n",
                             BbWindHangFind::MeasureText(hang_static_book, hang_book).c_str());
            // bbport (r112l_hang-discard-lanterns): the cut-out draws, the static push, the keys' spans
            BbReport::Printf("%s\n", BbWindHangFind::CutLine(hang_find_stats, BbWindHangFind::CutOn(),
                                                              BbWindHangFind::GainKnob(), hang_source)
                                         .c_str());
            BbReport::Printf("%s\n", BbWindHangFind::TallText(hang_static_book, hang_book, BbWindHangFind::UnionKnob(),
                                                              BbWindHangFind::TallKnob())
                                         .c_str());
            // bbport (r112m_hang-close-proof): every candidate of the scene now, nearest first, with its state (a header
            // line always; the candidate lines with BB_WIND_HANG_FIND=1)
            for (const std::string& line : BbWindHangFind::CandLines(
                     BbWindHangFind::GatherCands(hang_find_boxes, hang_static_book, hang_book, hang_box),
                     hang_find_stats, BbWindHangFind::TallKnob(), WindHangGainNow(), BbWindHangFind::SameKnob(),
                     hang_source.now, BbWindHangFind::FindOn(), BbWindHang::ProofOn())) {
                BbReport::Printf("%s\n", line.c_str());
            }
            hang_find_stats = {};
        }
        if (BbWindHangFind::FindOn()) { // (r112i) the survey: what hangs, with its shaders
            WindHangFindReport();
        }
        if (BbWindHangRoute::On()) { // bbport (r112q_hang-bracket-route, TOOL): one line a stream group (vs:ps), FIRST BREAK in each
            WindHangRouteReport();
        }
        // bbport (r112p_hang-gpu-palette-lanterns): the refused streams' census and the palette writers (each when new), then
        // this window's counts
        std::string gpu_census_line;
        if (hang_gpu_census.TakeLine(BbWindHangGpu::ModeOnce(), BbWindHangGpu::BoxBones(), gpu_census_line)) {
            BbReport::Printf("%s\n", gpu_census_line.c_str());
        }
        for (const std::string& writer_line : hang_gpu_watch.TakeLines()) {
            BbReport::Printf("%s\n", writer_line.c_str());
        }
        BbReport::Printf("%s\n", BbWindHangGpu::StatsText(hang_gpu_stats, hang_gpu_census, hang_gpu_watch.Watched(),
                                                           hang_gpu_watch.Hits(), WindHangGainNow())
                                     .c_str());
        if (hang_gpu_watch.Watched() > 0 && hang_gpu_watch.Hits() == 0) { // bbport (r112q_hang-bracket-route): what 'writers found 0' means
            BbReport::Printf("%s\n", BbWindHangGpu::NoWriterText(hang_gpu_watch.Watched()).c_str());
        }
        hang_gpu_stats = {};
        hang_box.ClearNotes();
        hang_stats = {};
    }
}

void Rasterizer::EffectsOnFrameEnd() {
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    if (const u32 request = BottleSource::Run()) {
        const auto frame = BottleCutFrame(this, request, scheduler, *scene_targets, *rt_shadow, *object_motion);
        if (const auto closed = BottleCold::Current().Close(frame, {}, {}, {}, false)) BottleCold::Report(*closed);
    }
#endif
    if (reflection_probe) {
        if (reflection_native_serial) {
            ReflectionNativePoll();
        }
        ReflectionFrameEnd();
    }
    if (window_receiver_enabled) {
        PollWindowReceiver();
    }
    if (foliage_mask) {
        FoliageFrameEnd();
    }
    if (blood_pool_probe) { // bbport (r100c_blood-pool-probe, TOOL): a new box, the frames, the log
        blood_pool_probe->OnFrameEnd();
    }
    if (test_world_at) { // bbport (r120_test-camera-lookat, TOOL): BB_TEST_WORLD_AT: a finished depth read's lines
        test_world_at->OnFrameEnd();
    }
    if (BbTestCamera::Wanted()) { // bbport (r120_test-camera-lookat, TOOL): BB_TEST_CAMERA (live): the held camera's frame
        BbTestCamera::TickIn tick;
        tick.frame = object_motion->Frame();
        if (camera_motion) {
            const auto matrices = camera_motion->CameraMatrices();
            const auto size = camera_motion->RenderSize();
            tick.matrices_ok = matrices.valid && size[0] != 0 && size[1] != 0 && matrices.proj[0] != 0.0f && matrices.proj[1] != 0.0f;
            std::copy(matrices.view.begin(), matrices.view.end(), tick.view);
            std::copy(matrices.inv_view.begin(), matrices.inv_view.end(), tick.inv_view);
            std::copy(matrices.proj.begin(), matrices.proj.end(), tick.proj);
            tick.width = float(size[0]);
            tick.height = float(size[1]);
        }
        float camera_hunter[3] = {};
        tick.hunter_ok = BbEngine::world_player_position(camera_hunter);
        std::memcpy(tick.hunter, camera_hunter, sizeof tick.hunter);
        const BbTestGoto::Session& goto_session = BbTestGoto::Sess(); // r112n's locked target, for BB_TEST_CAMERA=hang
        tick.hang_ok = BbTestGoto::On() && BbTestGoto::KnobsOnce().hang && goto_session.locked;
        if (tick.hang_ok) {
            std::memcpy(tick.hang_centre, goto_session.centre, sizeof tick.hang_centre);
            std::copy(goto_session.box.begin(), goto_session.box.end(), tick.hang_box);
            tick.hang_box_ok = true;
        }
        std::vector<std::string> camera_lines;
        BbTestCamera::TheDriver().Tick(tick, camera_lines);
        for (const std::string& line : camera_lines) {
            BbReport::Printf("%s\n", line.c_str());
        }
    }
    if (SewerMotion::Alternate::Enabled() && SewerMotion::Alternate::pending &&
        !SewerMotion::Alternate::pending->frame_end_seen) {
        const auto* active_depth = texture_cache.TryGetImage(previous_scene_depth, 0);
        SewerMotion::Alternate::Close(camera_motion ? camera_motion->CameraMatrices() : CameraMotion::Matrices{},
                                      object_motion->Frame(), BbStats::frame_number.load(std::memory_order_relaxed),
                                      BbEngine::Loading::Generation(), scene_targets->Generation(),
                                      scene_targets->Reduced() && !BbEngine::Loading::ScreenUp(),
                                      previous_scene_depth.index, active_depth ? active_depth->image_uid : 0);
    }
    WindOnFrameEnd(); // bbport (r82_wind-stage1): BB_WIND=1 only
    WindSwayFrameEnd(); // bbport (r89_wind-foliage-sway): its log lines
    if (workflow) WorkflowFrameEnd();
    WindTreesPickFrameEnd(); // bbport (r89j_twigs-pick-trees): the trees' line, the pick (TOOL)
    // bbport (r119_volumetric-clouds): the cloud layer (null when off): its own clock while the cloud
    // shadows are off (after the wind's step, so that BB_WIND=1 gives this frame's direction; the
    // wind's "clouds" line then gets its heading and speed), its counters and its log
    if (cloud_layer) {
        const BbWind::Snapshot w = wind.Get();
        cloud_layer->OnFrameEnd(w.on, w.direction_deg);
        if (cloud_layer->OwnClock()) {
            BbWind::UseHeading(BbWind::Follower::Clouds, w, cloud_layer->Direction(),
                               cloud_layer->Velocity(), BbWind::CloudRatio);
        }
    }
    // bbport (r105_cloud-shadows): the clouds' direction and drift (null when off), after the
    // wind's step so that BB_WIND=1 gives this frame's direction
    if (cloud_shadow) {
        const BbWind::Snapshot w = wind.Get();
        // bbport (r116b_wind-weather): the clouds move at the weather's speed and their cover follows its level
        cloud_shadow->OnFrameEnd(w.on, w.direction_deg, w.weather_on ? w.speed : -1.0f,
                                 w.weather_on ? BbWind::CoverShift(w.weather) : 0.0f);
        BbWind::UseHeading(BbWind::Follower::Clouds, w, cloud_shadow->Direction(),
                           cloud_shadow->Velocity(), BbWind::CloudRatio); // bbport (r116)
    }
    // bbport (r109a_strength-settings-engine): the lamp flicker's two strengths for the next
    // frame, before AnyWanted asks LampFlicker::On(): the settings (each frame), or
    // BB_LAMP_FLICKER and BB_LAMP_FLICKER_ON_GAME when set; both 0: nothing of the flicker runs.
    static_assert(BbSettings::LampFlickerSteadyDefault == LampFlicker::DefaultSteady &&
                  BbSettings::LampFlickerOnGameDefault == LampFlicker::DefaultOnGame &&
                  BbSettings::LampFlickerStrengthMax == LampFlicker::MaxStrength &&
                  BbSettings::LampFlickerStrengthMin == 0.0f);
    LampFlicker::Update(
        BbSettings::Get().graphics_lamp_flicker_strength.load(std::memory_order_relaxed),
        BbSettings::Get().graphics_lamp_flicker_on_game_strength.load(std::memory_order_relaxed));
    effects_wanted = AnyWanted();
    drawn_look_wanted = DrawnLook::Wanted(); // bbport (r45_drawn-look)
    if (cloud_probe_on) { // bbport (r104_cloud-probe): TOOL, BB_CLOUD_PROBE=1 only
        CloudProbe::OnFrameEnd();
    }
    drawn_look->OnFrameEnd(drawn_look_wanted);
    // Lamps apart: a batch nothing ended. The frame is composed and the scene's depth forgotten
    // (CameraMotion::OnDisplayPass), so its lamp light is lost; it is counted and printed.
    point_shadow->DropUnended();
    if (!effects_wanted) {
        point_shadow->Drop();
    }
    froyok_bloom->OnFrameEnd();
    Halation::StrengthLine(); // bbport (r109a_strength-settings-engine): the strength's line
    if (halation) { // bbport (r95_halation)
        halation->OnFrameEnd();
    }
    if (blood_sheen) { // bbport (r100_blood-sheen)
        blood_sheen->OnFrameEnd();
    }
    if (glass_view) { // bbport (r129a_glass-registry): first (drops a pending MARK), then the registry's frame counts
        glass_view->OnFrameEnd();
    }
    if (glass_registry) {
        glass_registry->OnFrameEnd();
    }
    if (glass_clear) { // bbport (r131c_cabinet-glass-clear): the live knob, counters, log; the knob to the ray traced scene
        glass_clear->OnFrameEnd();
        rt_shadow->SetGlassClear(glass_clear->On());
    }
    if (sun_term_view) { // bbport (t129c_sun-term-view, TOOL)
        sun_term_view->OnFrameEnd();
    }
    if (glass_glint) { // bbport (r86b_glass-visible); a noted pane draw never made is forgotten
        glass_glint->OnFrameEnd();
        glint_pending = nullptr;
        glint_gpane_on = false; // bbport (r86i_glint-find-gbuffer)
    }
    if (foliage_glow) { // bbport (r131a_foliage-translucency)
        foliage_glow->OnFrameEnd();
    }
    if (footprints) { // bbport (r111_footprints): the hunter, the steps, the prints' fading
        footprints->OnFrameEnd();
    }
    point_shadow->OnFrameEnd();
    SunHoldFrameEnd(); // r7_cascades: reads sun_atlas before SunAtlasFrameEnd resets it
    SunAtlasFrameEnd();
    if (surface_probe_on) {
        SurfaceProbeRtScene(); // bbport (r64b_surface-probe-more): before the scene's frame end
    }
    rt_shadow->OnFrameEnd();
    rt_shadow->PollLampPane(object_motion->Frame());
    if (card_alpha) { // bbport (r62_leaf-stage3)
        card_alpha->OnFrameEnd();
    }
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
    // bbport (r96_lamp-flicker-colour, r109a): the strengths' line; the tracker's frame end while a
    // strength is above 0
    LampFlicker::FrameEnd(BbReport::Printf);
    if (surface_probe_on) {
        SurfaceProbeFrameEnd(); // bbport (r64_surface-probe): its lines go out with the reports
        SurfaceProbeRect(true); // bbport (t70b_mirror-probe, TOOL): its lines, and the hide line
    }
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

void Rasterizer::LampPaneTargets(const GraphicsPipeline* pipeline, bool gbuffer) {
    auto* p = rt_shadow->ActiveLampPane();
    if (!p) {
        return;
    }
    const u64 frame = object_motion->Frame();
    if (frame == p->armed_frame || (p->Captured() && p->capture.scene != frame)) {
        return;
    }
    if (p->seen_frame != frame) {
        p->seen_frame = frame;
        p->ordinal = 0;
        p->exact_draws = 0;
    }
    ++p->ordinal;
    const auto& regs = Regs();
    const bool writes_depth = regs.depth_control.depth_enable && regs.depth_control.depth_write_enable;
    // Before the copy, same-image scene writes are included in the two depth samples.
    // A write over either pick can still make its triangle fail depth matching.
    if (p->Captured() && db_desc.first.index == p->capture.image &&
        RtLampPane::RefuseDepthWrite(regs.depth_render_control.depth_clear_enable,
                                    writes_depth, p->depth_tick != 0)) {
        const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
        const auto* image = texture_cache.TryGetImage(db_desc.first, 0);
        std::printf("Lamp pane (t132d): depth-refusal req=%u scene=%llu ord=%u pair=%llx:%llx g=%u clear=%u write=%u "
                    "depth-tick=%llu image=%u/%llu capture=%u/%llu\n",
                    p->request.id, static_cast<unsigned long long>(frame), p->ordinal,
                    static_cast<unsigned long long>(vs.pgm_hash),
                    static_cast<unsigned long long>(ps ? ps->pgm_hash : 0),
                    unsigned(gbuffer), unsigned(regs.depth_render_control.depth_clear_enable),
                    unsigned(writes_depth), static_cast<unsigned long long>(p->depth_tick),
                    db_desc.first.index, static_cast<unsigned long long>(image ? image->image_uid : 0),
                    p->capture.image, static_cast<unsigned long long>(p->capture.uid));
        p->refusal = "depth target cleared or written outside the sampled G-buffer pass";
        return;
    }
    if (!gbuffer || regs.num_indices != RtLampPane::DrawIndices ||
        regs.num_instances.NumInstances() != RtLampPane::Instances) {
        return;
    }
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    if (ps && RtLampPane::Target(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash, ps->pgm_hash,
                                regs.num_indices, regs.num_instances.NumInstances())) {
        p->saw_target = true;
        if (++p->exact_draws > 1 && p->Captured()) {
            p->refusal = "multiple exact target draws in the capture frame";
        }
    }
}

bool Rasterizer::LampPaneDraw(LampPaneProbe& p, const AmdGpu::Regs& regs,
                              const GraphicsPipeline* pipeline, bool is_indexed, u32 index_offset,
                              const RtShadow::Draw& draw) {
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    const u64 frame = object_motion->Frame();
    if (p.Captured() || p.seen_frame != frame || p.exact_draws != 1 ||
        !ps || !RtLampPane::Target(draw.shader, ps->pgm_hash, draw.index_count, draw.instances)) {
        return false;
    }
    p.capture = {.request = p.request.id, .draw = p.ordinal, .scene = frame};
    const auto fail = [&](const char* why) {
        p.refusal = why;
        return false;
    };
    if (!is_indexed || !draw.triangles || !draw.camera_pass || !draw.solid || draw.glass ||
        !regs.depth_control.depth_enable || !db_desc.first ||
        db_desc.first != camera_motion->Depth()) {
        return fail("target is not an indexed solid camera depth draw");
    }
    if (trees_pick_rect_on || scene_targets->Reduced()) {
        return fail("scissored pick or reduced depth proxy unsupported");
    }
    const auto matrices = camera_motion->PassMatrices();
    const auto size = camera_motion->RenderSize();
    const auto& viewport = regs.viewports[0];
    const auto& controls = regs.viewport_control;
    const float zoffset = controls.zoffset_enable ? viewport.zoffset : 0.f;
    const float zscale = controls.zscale_enable ? viewport.zscale : 1.f;
    if (!size[0] || !size[1] || (u64(p.request.width) * size[1] != u64(p.request.height) * size[0]) ||
        regs.IsClipDisabled() || regs.clipper_control.clip_space != AmdGpu::ClipSpace::ZeroToW ||
        !controls.xscale_enable || !controls.xoffset_enable || !controls.yscale_enable ||
        !controls.yoffset_enable || zoffset != 0.f || zscale != 1.f ||
        regs.polygon_control.NeedsBias() ||
        target_scale[0] != 1.f || target_scale[1] != 1.f ||
        target_offset[0] != 0.f || target_offset[1] != 0.f ||
        viewport.xoffset != float(size[0]) * 0.5f || viewport.yoffset != float(size[1]) * 0.5f ||
        std::abs(viewport.xscale) != viewport.xoffset || std::abs(viewport.yscale) != viewport.yoffset) {
        return fail("unsupported viewport, depth range, bias or picture aspect");
    }
    for (u32 i = 1; i < AmdGpu::NUM_VIEWPORTS; ++i) {
        if (regs.viewports[i].xscale != 0.f) {
            return fail("multiple raster viewports unsupported");
        }
    }
    const float* constants = draw.constants;
    if (!matrices.valid || !constants || !std::equal(matrices.view.begin(), matrices.view.end(), constants + 8) ||
        matrices.proj[0] != constants[52] * (viewport.xscale < 0.f ? -1.f : 1.f) ||
        matrices.proj[1] != constants[57] * (viewport.yscale < 0.f ? -1.f : 1.f) ||
        matrices.proj[2] != constants[62] || matrices.proj[3] != constants[63] ||
        !(matrices.proj[3] < 0.f) ||
        constants[53] != 0.f || constants[54] != 0.f || constants[55] != 0.f ||
        constants[56] != 0.f || constants[58] != 0.f || constants[59] != 0.f ||
        constants[60] != 0.f || constants[61] != 0.f ||
        constants[64] != 0.f || constants[65] != 0.f || constants[66] != 1.f || constants[67] != 0.f) {
        return fail("capture and depth camera/projection not equivalent");
    }
    const auto& range = db_desc.second.view_info.range;
    if (range.base.level != 0 || range.base.layer != 0 || range.extent.layers != 1) {
        return fail("depth attachment is not the base layer and mip");
    }
    p.width = size[0];
    p.height = size[1];
    p.jitter = upscaler->Enabled() ? upscaler->Jitter() : std::array<float, 2>{};
    if (!std::isfinite(p.jitter[0]) || !std::isfinite(p.jitter[1]) ||
        std::abs(p.jitter[0]) > 1.f || std::abs(p.jitter[1]) > 1.f) {
        return fail("invalid raster jitter");
    }
    const auto scissor = DrawScissor(0);
    for (u32 i = 0; i < p.samples.size(); ++i) {
        const auto sample = RtLampPane::Texel(p.request, p.request.pixels[i], p.width, p.height, p.jitter);
        if (s64(sample.x) < scissor.offset.x || s64(sample.y) < scissor.offset.y ||
            s64(sample.x) >= s64(scissor.offset.x) + scissor.extent.width ||
            s64(sample.y) >= s64(scissor.offset.y) + scissor.extent.height) {
            return fail("control pixel outside the draw scissor");
        }
        p.samples[i] = sample;
    }
    if (p.samples[0].x == p.samples[1].x && p.samples[0].y == p.samples[1].y) {
        return fail("pane and control map to the same depth texel");
    }
    p.capture.image = db_desc.first.index;
    p.capture.uid = texture_cache.GetImage(db_desc.first).image_uid;
    p.camera = {matrices.view, matrices.inv_view, matrices.proj};
    if (p.reconstruction) {
        auto& reconstruction = *p.reconstruction;
        std::copy_n(constants + 52, reconstruction.projection.size(), reconstruction.projection.begin());
        std::copy_n(constants + 180, reconstruction.inverse_view.size(), reconstruction.inverse_view.begin());
        reconstruction.projection_saved = true;
    }
    p.first_index = index_offset;
    p.base_vertex = draw.first_vertex;
    return true;
}

void Rasterizer::LampPaneDepth(LampPaneProbe& p) {
    if (!p.Captured() || p.depth_tick) {
        return;
    }
    const auto id = camera_motion->Depth();
    auto* image = id ? texture_cache.TryGetImage(id, p.capture.uid) : nullptr;
    const auto matrices = camera_motion->PassMatrices();
    const RtLampPane::Camera camera{matrices.view, matrices.inv_view, matrices.proj};
    if (!image || !RtLampPane::SameDepth(p.capture, p.request.id, object_motion->Frame(), id.index,
                                        image->image_uid) ||
        !matrices.valid || !(camera == p.camera) ||
        camera_motion->RenderSize() != std::array<u32, 2>{p.width, p.height} || scene_targets->Reduced()) {
        p.refusal = "depth source, frame, extent or camera changed";
        return;
    }
    if (p.material_enabled) {
        if (!image->backing || !image->GetImage() || image->scene_proxy || scene_targets->Tracks(image->image_uid)) {
            p.refusal = "alias-unproven: final depth is not isolated native backing";
            return;
        }
        if (p.material.phases.Complete(p.capture)) {
            const auto& immediate = p.material.sources.back().backing;
            if (immediate.image != std::bit_cast<u64>(VkImage(image->GetImage())) ||
                immediate.backing != u64(reinterpret_cast<std::uintptr_t>(image->backing)) ||
                immediate.begin != image->guest_begin || immediate.end != image->guest_end) {
                p.material.refusal = "alias-unproven: final depth backing changed after B";
            }
        }
    }
    const auto format = image->info.pixel_format;
    if ((format != vk::Format::eD32Sfloat && format != vk::Format::eD32SfloatS8Uint) ||
        image->info.num_samples > 1 || p.width > image->info.size.width ||
        p.height > image->info.size.height ||
        !(image->usage_flags & vk::ImageUsageFlagBits::eTransferSrc)) {
        p.refusal = "unsupported depth format, samples, size or transfer usage";
        return;
    }
    if (!p.Allocate(instance.GetAllocator(), scheduler)) {
        return;
    }
    scheduler.EndRendering();
    runtime.Transit(image, vk::ImageLayout::eTransferSrcOptimal, vk::PipelineStageFlagBits2::eTransfer,
                    vk::AccessFlagBits2::eTransferRead);
    runtime.FlushBarriers();
    std::array<vk::BufferImageCopy, 2> regions{};
    for (u32 i = 0; i < regions.size(); ++i) {
        regions[i] = {.bufferOffset = p.WorldBytes() + i * sizeof(float),
                      .imageSubresource = {vk::ImageAspectFlagBits::eDepth, 0, 0, 1},
                      .imageOffset = {s32(p.samples[i].x), s32(p.samples[i].y), 0},
                      .imageExtent = {1, 1, 1}};
    }
    scheduler.RecordCrumb({.name = "t132d lamp pane depth"}, [source = image->GetImage(),
                          target = vk::Buffer{p.buffer}, regions](vk::CommandBuffer cmdbuf) {
        cmdbuf.copyImageToBuffer(source, vk::ImageLayout::eTransferSrcOptimal, target, regions);
        const vk::MemoryBarrier2 to_host{
            .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
            .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eHost,
            .dstAccessMask = vk::AccessFlagBits2::eHostRead,
        };
        cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_host});
    });
    p.depth_tick = scheduler.CurrentTick();
}

void Rasterizer::FoliageRefuseWriter(const char* guard, u32 subject, u64 observed, u64 expected) {
    auto& probe = pipeline_cache.BoundaryProbe();
    if (probe.Active() && std::strcmp(guard, "overlapping-writer") != 0) {
        probe.Observe({.kind = FoliageBoundary::Kind::Writer,
                       .later = foliage_mask->Reason() != FoliageMask::Refusal::None,
                       .reason = guard, .epoch = mask_receivers.key.serial,
                       .ps = subject, .a = observed, .b = expected});
    }
    if (mask_diagnostic && foliage_mask->Reason() == FoliageMask::Refusal::None) {
        mask_writer_evidence = {guard, subject, observed, expected};
    }
    foliage_mask->Invalidate(FoliageMask::Refusal::Writer);
}

void Rasterizer::FoliageCheckReceivers() {
    const auto& tracked = mask_receivers;
    if (!tracked.key.serial || mask_finished) return;
    auto& probe = pipeline_cache.BoundaryProbe();
    if (foliage_mask->Reason() != FoliageMask::Refusal::None) {
        // Production stamps stop advancing. A later check cannot establish validity
        // against stamps that would have changed if the refused draws had attached.
        if (probe.Active()) {
            probe.Observe({.kind = FoliageBoundary::Kind::Receiver, .later = true,
                           .reason = "unknown-stamps-after-refusal", .epoch = tracked.key.serial}, true);
        }
        return;
    }
    const u64 generation = scene_targets->Generation();
    if (generation != tracked.proxy_generation) {
        return FoliageRefuseWriter("proxy-generation", 0, generation, tracked.proxy_generation);
    }
    const std::array uid{tracked.key.depth.uid, tracked.key.normal.uid, tracked.key.albedo.uid};
    const std::array backing{tracked.key.depth.generation, tracked.key.normal.generation,
                             tracked.key.albedo.generation};
    for (u32 i = 0; i < tracked.ids.size(); ++i) {
        const auto* image = texture_cache.TryGetImage(tracked.ids[i], uid[i]);
        if (!image) {
            return FoliageRefuseWriter("receiver-missing", i, 0, uid[i]);
        }
        if (!texture_cache.IsRegisteredImage(tracked.ids[i], uid[i])) {
            return FoliageRefuseWriter("receiver-unregistered", i);
        }
        const u64 current_backing = std::bit_cast<u64>(image->GetImage());
        if (current_backing != backing[i]) {
            return FoliageRefuseWriter("receiver-backing", i, current_backing, backing[i]);
        }
        if (image->write_seq != tracked.writes[i]) {
            return FoliageRefuseWriter("receiver-write-seq", i, image->write_seq, tracked.writes[i]);
        }
        if (True(image->flags & VideoCore::ImageFlagBits::Dirty)) {
            return FoliageRefuseWriter("receiver-dirty", i, u64(image->flags));
        }
    }
}

void Rasterizer::FoliageWriter(VAddr address, u64 size, FoliageBoundary::Source source) {
    if (!mask_receivers.key.serial || mask_finished || size == 0) return;
    auto& probe = pipeline_cache.BoundaryProbe();
    const bool later = foliage_mask->Reason() != FoliageMask::Refusal::None;
    if (later && !probe.Active()) return;
    for (u32 i = 0; i < mask_receivers.starts.size(); ++i) {
        const VAddr start = mask_receivers.starts[i];
        if (address < mask_receivers.ends[i] && (address >= start || size > start - address)) {
            if (probe.Active()) {
                constexpr std::array names{"overlap-depth", "overlap-normal", "overlap-albedo"};
                probe.Observe({.kind = FoliageBoundary::Kind::Writer, .source = source, .later = later,
                               .reason = names[i], .epoch = mask_receivers.key.serial,
                               .a = address, .b = size});
            }
            if (!later) FoliageRefuseWriter("overlapping-writer", i, size);
            return;
        }
    }
}

void Rasterizer::FoliageObserveDraw(const GraphicsPipeline* pipeline, FoliageBoundary::Source source,
                                    bool tagged) {
    constexpr u32 fragment = u32(Shader::SwStage::Fragment);
    const char* selection = source == FoliageBoundary::Source::Indirect ? "class-not-run-indirect" :
                            tagged ? "grass-diagnostic" : "class-zero";
    pipeline_cache.BoundaryProbe().Observe({
        .kind = FoliageBoundary::Kind::Draw, .source = source,
        .later = foliage_mask->Reason() != FoliageMask::Refusal::None,
        .reason = selection, .epoch = mask_receivers.key.serial,
        .original = reinterpret_cast<uintptr_t>(pipeline),
        .stage = pipeline->GetGraphicsKey().stage_hashes[fragment],
        .ps = FragmentHash(pipeline), .a = tagged});
}

void Rasterizer::FoliageFrameEnd() {
    auto& probe = pipeline_cache.BoundaryProbe();
    if (probe.Active()) {
        probe.End("abandoned-frame-end", unsigned(foliage_mask->Reason()), mask_writer_evidence.guard);
    }
    if (mask_frame_started && (mask_diagnostic || mask_tags)) {
        std::printf("Foliage mask (r132a): frame %llu draws %u diagnostic tags %u refusal %u\n",
                    static_cast<unsigned long long>(mask_frame), mask_draws, mask_tags,
                    unsigned(foliage_mask->Reason()));
        if (mask_diagnostic && foliage_mask->Reason() == FoliageMask::Refusal::Writer &&
            mask_writer_evidence.guard) {
            const auto& evidence = mask_writer_evidence;
            // Receiver subjects are depth/normal/albedo (0/1/2). Candidate subjects are guest PS hashes.
            std::printf("Foliage mask (r132a): frame %llu epoch %llu writer guard %s subject 0x%x "
                        "observed %llu expected %llu\n",
                        static_cast<unsigned long long>(mask_frame),
                        static_cast<unsigned long long>(mask_receivers.key.serial), evidence.guard,
                        evidence.subject, static_cast<unsigned long long>(evidence.observed),
                        static_cast<unsigned long long>(evidence.expected));
        }
    }
    foliage_mask->OnFrameEnd();
    mask_receivers = {};
    mask_frame_started = false;
    mask_finished = false;
    mask_draws = mask_tags = 0;
    ++mask_frame;

    const bool collect = FoliageTranslucency::GlowNow();
    foliage_collect.store(collect, std::memory_order_relaxed);
    bool arm = false;
#if BB_WIND_TWIGS_LIVE
    static BbLiveKnobs::Knob<bool> diagnostic{"BB_FOLIAGE_MASK_DIAGNOSTIC", [](const char* text) {
        return text && std::strcmp(text, "1") == 0;
    }};
    arm = diagnostic.Get();
#else
    {
        const char* startup = std::getenv("BB_FOLIAGE_MASK_DIAGNOSTIC");
        arm = startup && std::strcmp(startup, "1") == 0;
    }
#endif
    arm = arm && collect && FoliageTranslucency::Tuning().strength == 0.0f;
    if (arm && !mask_diag_requested) {
        ++mask_capture;
        mask_diag_started = mask_frame;
    }
    mask_diag_requested = arm;
    mask_diagnostic = arm && mask_frame - mask_diag_started <= 4;
    if (probe.Active()) {
        probe.FrameEnd(mask_diagnostic);
    } else if (mask_diagnostic && mask_frame == mask_diag_started) {
        const char* census = std::getenv("BB_FOLIAGE_BOUNDARY");
        if (census && std::strcmp(census, "1") == 0) {
            const auto& profile = pipeline_cache.GetProfile();
            probe.Arm(mask_frame, mask_capture,
                      {reinterpret_cast<const u8*>(&profile), sizeof(profile)});
        }
    }
    if (!mask_diagnostic) {
        foliage_mask->Selection().Reset();
    }
}

const GraphicsPipeline* Rasterizer::FoliageAttach(const GraphicsPipeline* pipeline,
                                                const RenderState& original, RenderState& state,
                                                FoliageBoundary::Source source) {
    if (!foliage_collect.load(std::memory_order_relaxed) || mask_finished) {
        return pipeline;
    }
    using Refusal = FoliageMask::Refusal;
    auto& probe = pipeline_cache.BoundaryProbe();
    const bool observe = probe.Active();
    const auto& regs = Regs();
    const auto& key = pipeline->GetGraphicsKey();
    constexpr u32 slot = Shader::FoliageMaskOutput::Location;
    const bool slot6 = original.num_color_attachments > slot &&
                       original.color_attachments[slot].image_view;
    const auto& ds = original.depth_stencil_attachment;
    const bool depth_write = regs.depth_control.depth_enable && regs.depth_control.depth_write_enable;
    const auto& old = mask_receivers;
    const bool color_pair = (key.mrt_mask & 5u) == 5u &&
                            cb_descs[0].first && cb_descs[2].first;
    const bool candidate = gbuffer_draw && ds.has_depth && color_pair &&
                           db_desc.first == camera_motion->Depth();
    const bool depth_clear = ds.depth_clear && scheduler.WillRunLoadOps(original);
    const bool full_clear = candidate && depth_clear && original.color_attachments[0].is_clear &&
                            original.color_attachments[2].is_clear;

    if (!candidate) {
        if (old.key.serial) {
            // Native pass setup may declare a depth-write access even for depth testing.
            // Refresh that stamp only for the exact, read-only receiver binding.
            for (u32 i = 0; i < original.num_color_attachments; ++i) {
                if ((key.mrt_mask & (1u << i)) && original.color_attachments[i].image_view &&
                    cb_descs[i].first && (key.write_masks[i] || original.color_attachments[i].is_clear)) {
                    const auto& image = texture_cache.GetImage(cb_descs[i].first);
                    FoliageWriter(image.guest_begin, image.guest_end - image.guest_begin, source);
                }
            }
            if (db_desc.first && (depth_write || depth_clear)) {
                const auto& image = texture_cache.GetImage(db_desc.first);
                FoliageWriter(image.guest_begin, image.guest_end - image.guest_begin, source);
            } else if (db_desc.first == old.ids[0] && ds.image_view == old.views[0] &&
                       foliage_mask->Reason() == Refusal::None) {
                mask_receivers.writes[0] = texture_cache.GetImage(db_desc.first).write_seq;
            }
        }
        return pipeline;
    }

    const bool first = !std::exchange(mask_frame_started, true);
    const bool new_epoch = first || full_clear;
    const auto camera = camera_motion->PassMatrices();
    // Shading uses the base depth/normal/albedo views. Scope this increment to the same
    // single-layer, base-level receivers and to the original internal raster extent.
    const std::array ids{db_desc.first, cb_descs[0].first, cb_descs[2].first};
    const std::array ranges{db_desc.second.view_info.range, cb_descs[0].second.view_info.range,
                            cb_descs[2].second.view_info.range};
    const std::array views{ds.image_view, original.color_attachments[0].image_view,
                           original.color_attachments[2].image_view};
    MaskReceivers current;
    current.ids = ids;
    current.views = views;
    current.view = camera.view;
    current.projection = camera.proj;
    current.jitter = upscaler->Jitter();
    current.proxy_generation = scene_targets->Generation();
    current.key = {.serial = new_epoch ? ++mask_serial : old.key.serial,
                   .frame = mask_frame, .width = original.width, .height = original.height};
    std::array receivers{&current.key.depth, &current.key.normal, &current.key.albedo};
    bool supported = camera.valid && original.num_layers == 1 && !ui_pass.active &&
                     !attachment_feedback_loop && !Dc().clear_draw;
    for (u32 i = 0; i < ids.size(); ++i) {
        const auto& image = texture_cache.GetImage(ids[i]);
        const auto& range = ranges[i];
        supported &= views[i] && range.base.layer == 0 && range.base.level == 0 &&
                     range.extent.layers == 1 && range.extent.levels == 1 &&
                     !image.binding.needs_rebind;
        *receivers[i] = {image.image_uid, std::bit_cast<u64>(image.GetImage()), 0};
        current.writes[i] = image.write_seq;
        current.starts[i] = image.guest_begin;
        current.ends[i] = image.guest_end;
    }
    current.key.camera = supported ? current.key.depth.uid : 0;
    if (new_epoch) {
        if (observe) {
            probe.End("superseded-by-full-clear", unsigned(foliage_mask->Reason()), mask_writer_evidence.guard);
        }
        mask_receivers = current;
        mask_writer_evidence = {};
        foliage_mask->BeginEpoch(current.key);
        if (observe) {
            probe.Begin({.key = current.key,
                         .views = {std::bit_cast<u64>(views[0]), std::bit_cast<u64>(views[1]),
                                   std::bit_cast<u64>(views[2])},
                         .writes = current.writes, .begins = current.starts, .ends = current.ends,
                         .proxy = current.proxy_generation, .samples = key.num_samples},
                        full_clear ? "full-clear-load-ops" : "first-receiver-setup");
        }
    }
    const auto* variant = pipeline->FoliageVariant();
    if (observe) {
        constexpr u32 fs = u32(Shader::SwStage::Fragment);
        const auto* ps = pipeline->GetStages()[fs];
        const bool later = foliage_mask->Reason() != Refusal::None;
        // Inspect original prepared targets before any host mask is attached.
        const u64 facts = u64(slot6) | (u64(bool(key.mrt_mask & (1u << slot))) << 1) |
                          (u64(ps && (ps->mrt_mask & (1u << slot))) << 2) |
                          (u64(ps && ps->stores.GetAny(Shader::IR::Attribute::RenderTarget6)) << 3) |
                          (u64(bool(key.cb_shader_mask.GetMask(slot))) << 4) |
                          (u64(supported) << 5) | (u64(depth_write) << 6) |
                          (u64(full_clear) << 7) | (u64(bool(pipeline->HandleIfReady())) << 8);
        const char* readiness = !variant ? "variant-absent" :
                                variant->HandleIfReady() ? "variant-ready" : "variant-pending";
        probe.Observe({.kind = FoliageBoundary::Kind::Candidate, .source = source, .later = later,
                       .reason = readiness, .epoch = current.key.serial,
                       .original = reinterpret_cast<uintptr_t>(pipeline), .stage = key.stage_hashes[fs],
                       .masked = variant ? variant->GetGraphicsKey().stage_hashes[fs] : 0,
                       .ps = ps ? ps->pgm_hash : 0, .a = facts, .b = key.num_samples}, !ps);
    }
    constexpr auto rgb = vk::ColorComponentFlagBits::eR | vk::ColorComponentFlagBits::eG |
                         vk::ColorComponentFlagBits::eB;
    if (slot6 || (key.mrt_mask & (1u << slot))) {
        if (mask_diagnostic && foliage_mask->Reason() == Refusal::None) {
            std::printf("Foliage mask (r132a): location 6 collision, PS %08x\n", u32(FragmentHash(pipeline)));
        }
        if (observe) {
            probe.Observe({.kind = FoliageBoundary::Kind::Writer, .source = source,
                           .later = foliage_mask->Reason() != Refusal::None,
                           .reason = "guest-slot6", .epoch = current.key.serial,
                           .ps = FragmentHash(pipeline)});
        }
        foliage_mask->Invalidate(Refusal::Slot6);
    } else if (!supported || current.key != old.key || current.views != old.views ||
               current.view != old.view || current.projection != old.projection ||
               current.jitter != old.jitter || current.proxy_generation != old.proxy_generation ||
               (state.color_attachments[0].image_view != original.color_attachments[0].image_view) ||
               (state.color_attachments[2].image_view != original.color_attachments[2].image_view) ||
               (state.depth_stencil_attachment.image_view != ds.image_view)) {
        if (observe) {
            probe.Observe({.kind = FoliageBoundary::Kind::Writer, .source = source,
                           .later = foliage_mask->Reason() != Refusal::None,
                           .reason = "receiver-targets", .epoch = current.key.serial,
                           .ps = FragmentHash(pipeline)});
        }
        foliage_mask->Invalidate(Refusal::Targets);
    } else if (!new_epoch && (depth_clear || ds.stencil_clear ||
                              original.color_attachments[0].is_clear ||
                              original.color_attachments[2].is_clear)) {
        FoliageRefuseWriter("candidate-partial-clear", u32(FragmentHash(pipeline)));
    } else if ((key.write_masks[0] & rgb) != rgb || (key.write_masks[2] & rgb) != rgb) {
        FoliageRefuseWriter("candidate-rgb-write-mask", u32(FragmentHash(pipeline)),
                            u64(u32(key.write_masks[0])) | (u64(u32(key.write_masks[2])) << 8),
                            u64(u32(rgb)) | (u64(u32(rgb)) << 8));
    } else if (key.blend_controls[0].enable || key.blend_controls[2].enable) {
        FoliageRefuseWriter("candidate-blend", u32(FragmentHash(pipeline)),
                            u32(key.blend_controls[0].enable) | (u32(key.blend_controls[2].enable) << 1));
    } else if (!variant) {
        FoliageRefuseWriter("candidate-no-variant", u32(FragmentHash(pipeline)));
    } else if (!variant->HandleIfReady()) {
        FoliageRefuseWriter("candidate-variant-pending", u32(FragmentHash(pipeline)));
    } else if (!pipeline->HandleIfReady()) {
        FoliageRefuseWriter("candidate-original-pending", u32(FragmentHash(pipeline)));
    }
    if (!foliage_mask->Attach(mask_receivers.key, state)) {
        return pipeline;
    }
    mask_receivers.writes = current.writes;
    return variant;
}

bool Rasterizer::FoliageClass(const GraphicsPipeline& pipeline, bool indexed, u32 first) {
    const auto& regs = Regs();
    const auto* ps = pipeline.GetStages()[u32(Shader::SwStage::Fragment)];
    const auto& vs = pipeline.GetStage(Shader::SwStage::Vertex);
    auto& probe = pipeline_cache.BoundaryProbe();
    const auto observe = [&](const char* result) {
        if (probe.Active()) {
            probe.Observe({.kind = FoliageBoundary::Kind::Selection, .source = FoliageBoundary::Source::Direct,
                           .later = foliage_mask->Reason() != FoliageMask::Refusal::None,
                           .reason = result, .epoch = mask_receivers.key.serial,
                           .original = reinterpret_cast<uintptr_t>(&pipeline),
                           .stage = pipeline.GetGraphicsKey().stage_hashes[u32(Shader::SwStage::Fragment)],
                           .ps = ps ? ps->pgm_hash : 0, .a = first, .b = regs.num_indices});
        }
    };
    if (!mask_diagnostic || !indexed || !ps || vs.pgm_hash != 0x3eaa5555 || ps->pgm_hash != 0xdbeccd9c ||
        !((first == 0 && regs.num_indices == 45150) ||
          (first == 342552 && regs.num_indices == 173016))) {
        observe("selection-prefilter-rejected");
        return false;
    }
    // Reuse the leaf owner's exact material/mesh facts from the settled local ROI. The
    // descriptor addresses and resource generations are collected fresh for this arm.
    const auto facts = FoliageProbeFacts(pipeline, true, false, true, first);
    if (!facts.bindings_exact || !facts.card_valid || facts.alpha_matches != 1 ||
        facts.alpha_slot != 1 || !facts.position_valid || !facts.offsets_known ||
        facts.position_size != 2648884 || facts.position_data_format != 13 ||
        facts.position_number_format != 7 || facts.texture_count != 2 ||
        facts.num_inputs != 4 || facts.default_inputs || facts.flat_inputs ||
        facts.input_offsets[0] != 0 || facts.input_offsets[1] != 1 ||
        facts.input_offsets[2] != 2 || facts.input_offsets[3] != 3 ||
        facts.uv_hash != 0xdd861594842ba966ULL ||
        facts.constants_hash != (first == 0 ? 0xca309f3ab6b27b22ULL : 0xdef535f1f7f0da0fULL)) {
        foliage_mask->Selection().Reset();
        observe("selection-probe-facts-rejected");
        FoliageRefuseWriter("class-probe-facts", first);
        return false;
    }
    const auto& alpha = facts.textures[1].sharp;
    const std::array expected_alpha = first == 0
        ? std::array{0x26300000u, 0x01ffc7ffu, 0x96db0facu, 0x00ffe000u, 0u, 0u, 0u}
        : std::array{0x26300000u, 0x007fc1ffu, 0x96d90facu, 0x003fe000u, 0u, 0u, 0u};
    if (!std::equal(expected_alpha.begin(), expected_alpha.end(), alpha.begin() + 1)) {
        foliage_mask->Selection().Reset();
        observe("selection-alpha-descriptor-rejected");
        FoliageRefuseWriter("class-alpha-descriptor", first);
        return false;
    }
    const auto& draw = Dc();
    if (!draw.vertex_binds.num_buffers || !draw.index_bind.handle) {
        observe("selection-bindings-missing");
        return false;
    }
    const u64 vertex_generation = std::bit_cast<u64>(draw.vertex_binds.host_buffers[0]);
    const u64 index_generation = std::bit_cast<u64>(draw.index_bind.handle);
    FoliageMaskRules::Draw signature{
        .vs = facts.vs, .ps = facts.ps,
        .permutation = pipeline.GetGraphicsKey().stage_hashes[u32(Shader::SwStage::Fragment)],
        .capture = mask_capture, .vertex_address = facts.position_base,
        .index_address = facts.index_base, .vertex_generation = vertex_generation,
        .index_generation = index_generation, .vertex_size = facts.position_size,
        .vertex_binding_offset = draw.vertex_binds.host_offsets[0],
        .index_binding_offset = draw.index_bind.offset,
        .uv_hash = facts.uv_hash, .constants_hash = facts.constants_hash,
        .first_index = first, .index_count = facts.count, .first_instance = facts.first_instance,
        .instance_count = facts.instances, .stride = facts.stride, .first_vertex = s32(facts.first_vertex),
        .primitive = facts.primitive, .index_type = facts.index_type, .camera_gbuffer = true,
        .direct_indexed = true, .restart = facts.restart, .resolved_cutout = facts.discard,
        .complete_textures = true,
    };
    for (u32 i = 0; i < signature.textures.size(); ++i) {
        const auto& texture = facts.textures[i];
        if (texture.source != BloodPoolProbe::FoliageTexture::Source::Registered) {
            foliage_mask->Selection().Reset();
            observe("selection-texture-unregistered");
            return false;
        }
        const auto& view = texture.view;
        signature.textures[i] = {
            .image = {texture.uid, texture.uid, 0}, .write_sequence = texture.write_seq,
            .descriptor = texture.sharp,
            .view = {view.range[0], view.range[1], view.range[2], view.range[3],
                     view.swizzle[0], view.swizzle[1], view.swizzle[2], view.swizzle[3],
                     view.type, view.format, view.min_lod},
        };
    }
    auto& selection = foliage_mask->Selection();
    const float strength = FoliageTranslucency::Tuning().strength;
    if (!selection.Authorize(signature, true, strength, mask_frame)) {
        observe("selection-authorization-rejected");
        FoliageRefuseWriter("class-authorize", first);
        return false;
    }
    const bool tagged = selection.ClassifyDraw(signature, strength, mask_frame) ==
                        FoliageMaskRules::Class::GrassDiagnostic;
    observe(tagged ? "selection-qualified" : "selection-unqualified");
    return tagged;
}

vk::ImageView Rasterizer::FoliageDiagnosticView() {
    if (mask_finished || !mask_frame_started) {
        return {};
    }
    FoliageCheckReceivers();
    const auto& tracked = mask_receivers;
    const auto camera = camera_motion->PassMatrices();
    mask_finished = true;
    auto& probe = pipeline_cache.BoundaryProbe();
    if (!mask_diagnostic || db_desc.first != tracked.ids[0] || !camera.valid ||
        camera.view != tracked.view || camera.proj != tracked.projection ||
        upscaler->Jitter() != tracked.jitter) {
        if (probe.Active()) {
            probe.End("consumer-camera-or-depth-refused", unsigned(foliage_mask->Reason()),
                      mask_writer_evidence.guard);
        }
        return {};
    }
    const auto view = foliage_mask->ReadableMask(tracked.key);
    if (probe.Active()) {
        probe.End(view ? "consumer-readable" : "consumer-no-readable-mask",
                  unsigned(foliage_mask->Reason()), mask_writer_evidence.guard);
    }
    return view;
}

namespace {
struct ReflectionInputTrace;
ReflectionInputTrace* ReflectionInputsFor(u32 role);

// The first failing condition in the existing short-circuit order.
enum NativeStampReject : u32 {
    StampAbsent = 1u << 0,
    StampFrame = 1u << 1,
    StampGeneration = 1u << 2,
    StampLoading = 1u << 3,
    StampPreview = 1u << 4,
    StampReduced = 1u << 5,
    StampCamera = 1u << 6,
    StampView = 1u << 7,
    StampProjection = 1u << 8,
    StampExtent = 1u << 9,
    StampCameraDepth = 1u << 10,
    StampBindDepth = 1u << 11,
    StampBindCb0 = 1u << 12,
    StampJitter = 1u << 13,
    StampDepthUid = 1u << 14,
    StampCb0Uid = 1u << 15,
    StampDepthBacking = 1u << 16,
    StampCb0Backing = 1u << 17,
    StampDepthImage = 1u << 18,
    StampCb0Image = 1u << 19,
};

constexpr u32 FireplaceRole = u32(ReflectionFirstHit::PlacedSource::Fireplace);

const char* StampRetryValidatorRefusal(u32 reason) {
    constexpr std::array names{"stamp-absent", "stamp-frame", "stamp-generation", "stamp-loading",
        "stamp-preview", "stamp-reduced", "stamp-camera", "stamp-view", "stamp-projection", "stamp-extent",
        "stamp-camera-depth", "stamp-bound-depth", "stamp-bound-cb0", "stamp-jitter", "stamp-depth-uid",
        "stamp-cb0-uid", "stamp-depth-backing", "stamp-cb0-backing", "stamp-depth-image", "stamp-cb0-image"};
    const auto index = std::countr_zero(reason);
    return index < int(names.size()) ? names[index] : "native-unqualified";
}

const char* RetryBindingRefusal(const ReflectionNativeProbe::Binding* binding,
                               Core::MemoryManager& memory, VideoCore::BufferCache& cache,
                               bool& live_handle) {
    if (!binding) return "palette-descriptor";
    live_handle = binding->buffer->Handle() == binding->handle;
    if (!live_handle) return "palette-handle";
    const auto size = binding->guest_bytes;
    const auto backing_size = binding->buffer->SizeBytes();
    if (binding->descriptor_offset > backing_size || size > backing_size - binding->descriptor_offset) {
        return "palette-backing-span";
    }
    if (!binding->guest || !memory.IsValidGpuMapping(binding->guest, 0) ||
        memory.ClampRangeSize(binding->guest, size) != size) return "palette-guest-span";
    if (cache.IsInPlace(binding->guest, size)) return "palette-in-place";
    if (!cache.IsRegionGpuModified(binding->guest, size)) return "palette-clean";
    return nullptr;
}
}

void Rasterizer::ReflectionNativeBeforeDraw(ReflectionNativeProbe::Draw& draw) {
    using namespace ReflectionNativeProbe;
    const auto& observed = reflection_probe->stamp;
    const auto camera = camera_motion->PassMatrices();
    const auto frame = rt_shadow->WindowDiagnosticFrame();
    auto* retry = draw.stamp_retry && draw.stamp_retry->attempted ? &*draw.stamp_retry : nullptr;
    const auto reject = [&](bool refused, NativeStampReject reason) {
        if (refused && retry) {
            retry->validator_reject = reason;
        } else if (refused && ReflectionInputsFor(Match(draw.key))) {
            draw.stamp_reject = reason;
        }
        return refused;
    };
    const auto unsafe = [&] {
        return point_shadow->Apart() || std::ranges::any_of(Dc().bound_buffers, [](const BoundBuffer& binding) {
            return binding.is_written;
        });
    };
    if (reject(!observed, StampAbsent)) {
        return;
    }
    if (reject(observed->frame != frame, StampFrame)) {
        // Current camera evidence is independent of the still-published previous stamp.
        if (!retry && !draw.stamp_retry && !draw.trace && !draw.stamped && !draw.placement_safe &&
            gbuffer_draw && ReflectionFirstHit::On() && ReflectionFirstHit::PlacedOn() &&
            Match(draw.key) == FireplaceRole &&
            OneFrameBehind(*observed, BbEngine::Loading::Generation(), frame) &&
            !BbEngine::Loading::ScreenUp() && !camera_motion->PreviewFrame() &&
            !scene_targets->Reduced() && camera.valid && db_desc.first && cb_descs[0].first &&
            camera_motion->Depth() == db_desc.first && !unsafe()) {
            const auto* binding = PlacedDescriptor(draw);
            const auto* depth = texture_cache.TryGetImage(db_desc.first, 0);
            const auto* cb0 = texture_cache.TryGetImage(cb_descs[0].first, 0);
            const u64 tick = scheduler.CurrentTick();
            if (binding && binding->buffer->Handle() == binding->handle && depth && cb0 &&
                depth->backing && cb0->backing && depth->GetImage() && cb0->GetImage() && tick) {
                draw.stamp_retry.emplace(StampRetry{
                    .early = {
                        .generation = observed->generation, .frame = frame,
                        .depth = db_desc.first, .cb0 = cb_descs[0].first,
                        .depth_uid = depth->image_uid, .cb0_uid = cb0->image_uid,
                        .depth_image = depth->GetImage(), .cb0_image = cb0->GetImage(),
                        .view = camera.view, .projection = camera.proj,
                        .jitter = upscaler->Enabled() ? upscaler->Jitter() : std::array<float, 2>{},
                        .extent = camera_motion->RenderSize(), .valid_native = true,
                    },
                    .prior_frame = observed->frame, .prior_pass = observed->pass, .early_tick = tick,
                });
            }
        }
        return;
    }
    if (reject(observed->generation != BbEngine::Loading::Generation(), StampGeneration) ||
        reject(BbEngine::Loading::ScreenUp(), StampLoading) ||
        reject(camera_motion->PreviewFrame(), StampPreview) ||
        reject(scene_targets->Reduced(), StampReduced) ||
        reject(!camera.valid, StampCamera) ||
        reject(camera.view != observed->view, StampView) ||
        reject(camera.proj != observed->projection, StampProjection) ||
        reject(camera_motion->RenderSize() != observed->extent, StampExtent) ||
        reject(camera_motion->Depth() != observed->depth, StampCameraDepth) ||
        reject(db_desc.first != observed->depth, StampBindDepth) ||
        reject(cb_descs[0].first != observed->cb0, StampBindCb0) ||
        reject((upscaler->Enabled() ? upscaler->Jitter() : std::array<float, 2>{}) != observed->jitter,
               StampJitter)) {
        return;
    }
    const auto* depth = texture_cache.TryGetImage(observed->depth, observed->depth_uid);
    const auto* cb0 = texture_cache.TryGetImage(observed->cb0, observed->cb0_uid);
    if (reject(!depth, StampDepthUid) || reject(!cb0, StampCb0Uid) ||
        reject(!depth->backing, StampDepthBacking) || reject(!cb0->backing, StampCb0Backing) ||
        reject(depth->GetImage() != observed->depth_image, StampDepthImage) ||
        reject(cb0->GetImage() != observed->cb0_image, StampCb0Image)) {
        return;
    }
    if (retry) {
        if (unsafe()) {
            retry->failure = "pending-lamp-batch-or-writable-draw";
            return;
        }
        const auto* binding = PlacedDescriptor(draw);
        retry->palette = binding != nullptr;
        if (const char* failure = RetryBindingRefusal(binding, *memory, buffer_cache, retry->handle)) {
            retry->failure = failure;
            return;
        }
    }
    draw.stamp = *observed;
    draw.stamped = true;
    if (!retry && unsafe()) {
        draw.readback_reason = "pending-lamp-batch-or-writable-draw";
        return;
    }
    draw.placement_safe = true;
    if (!draw.trace) {
        return;
    }
    if (draw.overflow) {
        draw.readback_reason = "binding-cap";
        return;
    }
    std::array<u32, MaxBindings> copied{};
    const auto bindings = std::span{draw.bindings}.first(draw.binding_count);
    bool any = false;
    for (u32 i = 0; i < bindings.size(); ++i) {
        const auto& src = bindings[i];
        if (!src.range_known) {
            draw.readback_reason = "guest-binding-range-unknown";
            return;
        }
        if (!src.gpu_dirty) {
            continue;
        }
        const u64 offset = src.descriptor_offset + src.adjust;
        if (!src.buffer || !src.handle || src.handle != src.buffer->Handle() || src.in_place ||
            src.writable || src.effective_bytes != src.guest_bytes || src.guest_bytes > MaxBindingBytes ||
            offset < src.descriptor_offset || (offset % 4) || (src.guest_bytes % 4) ||
            offset > src.buffer->SizeBytes() || src.guest_bytes > src.buffer->SizeBytes() - offset) {
            draw.readback_reason = "unsupported-effective-buffer";
            return;
        }
        copied[i] = src.guest_bytes;
        any = true;
    }
    if (!any) {
        draw.readback_reason = "no-dirty-small-skeleton";
        return;
    }
    if (!scheduler.CurrentTick()) {
        draw.readback_reason = "no-active-scheduler-tick";
        return;
    }
    const auto free = std::ranges::find_if(reflection_native_slots, [](const ReflectionNativeSlot& slot) {
        return !slot.tick;
    });
    if (free == reflection_native_slots.end()) {
        draw.readback_reason = "ring-busy";
        return;
    }
    if (!free->buffer) {
        const VkBufferCreateInfo create{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                                        .size = ReadbackBytes, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
        const VmaAllocationCreateInfo memory{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
        };
        VkBuffer buffer{};
        VmaAllocationInfo info{};
        if (!EffectPass::HasRoom(instance, ReadbackBytes) ||
            vmaCreateBuffer(instance.GetAllocator(), &create, &memory, &buffer, &free->allocation, &info) != VK_SUCCESS) {
            draw.readback_reason = "readback-allocation";
            return;
        }
        if (!info.pMappedData || info.size > 65536) {
            vmaDestroyBuffer(instance.GetAllocator(), buffer, free->allocation);
            free->allocation = {};
            draw.readback_reason = "readback-mapping-or-limit";
            return;
        }
        free->buffer = buffer;
        free->mapped = info.pMappedData;
        free->bytes = info.size;
    }
    scheduler.EndRendering();
    runtime.FlushBarriers();
    using S = vk::PipelineStageFlagBits2;
    using A = vk::AccessFlagBits2;
    std::array<vk::BufferMemoryBarrier2, MaxBindings> before{};
    std::array<vk::BufferCopy, MaxBindings> regions{};
    for (u32 i = 0; i < bindings.size(); ++i) {
        if (!copied[i]) {
            continue;
        }
        const auto& src = bindings[i];
        const u64 offset = src.descriptor_offset + src.adjust;
        before[i] = {.srcStageMask = S::eAllCommands, .srcAccessMask = A::eMemoryWrite,
                     .dstStageMask = S::eCopy, .dstAccessMask = A::eTransferRead,
                     .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                     .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                     .buffer = src.handle, .offset = offset, .size = copied[i]};
        regions[i] = {.srcOffset = offset, .dstOffset = u64(i) * MaxBindingBytes, .size = copied[i]};
        runtime.AccessBuffer(src.buffer, offset, copied[i], S::eCopy, A::eTransferRead);
    }
    scheduler.RecordCrumb({.name = "Reflection native palette readback"},
                          [before, regions, target = free->buffer](vk::CommandBuffer cmd) {
        for (u32 i = 0; i < regions.size(); ++i) {
            if (regions[i].size) {
                cmd.pipelineBarrier2({.bufferMemoryBarrierCount = 1, .pBufferMemoryBarriers = &before[i]});
                cmd.copyBuffer(before[i].buffer, target, regions[i]);
            }
        }
        EffectPass::MemoryBarrier(cmd, S::eCopy, A::eTransferWrite, S::eHost, A::eHostRead);
    });
    free->tick = scheduler.CurrentTick();
    free->generation = draw.stamp.generation;
    free->serial = draw.serial;
    free->key = draw.key;
    free->binding_bytes = copied;
    free->confirmed = false;
    draw.readback_reason = "recorded";
}

void Rasterizer::ReflectionNativeAfterDraw(const ReflectionNativeProbe::Draw& draw) {
    using namespace ReflectionNativeProbe;
    const auto& stamp = reflection_probe->stamp;
    const bool confirmed = draw.submission_stamp && stamp && *stamp == draw.stamp && gbuffer_draw &&
                           draw.stamp.frame == rt_shadow->WindowDiagnosticFrame() &&
                           !BbEngine::Loading::ScreenUp() && draw.stamp.generation == BbEngine::Loading::Generation() &&
                           Dc().draw_jitter == draw.stamp.jitter && Dc().draw_inputs.index_offset == draw.key.first;
    if (confirmed) {
        rt_shadow->ReflectionNativeSubmitted(draw);
        for (auto& slot : reflection_native_slots) {
            if (slot.tick && slot.serial == draw.serial) {
                slot.confirmed = true;
            }
        }
    }
    const auto u = [](u64 n) { return static_cast<unsigned long long>(n); };
    const auto label = labels[Match(draw.key)];
    std::printf("Reflection native draw target=%s cookie=%llu generation=%llu frame=%llu pass=%llu "
                "depth_uid=%llu cb0_uid=%llu confirmed=%u ordinary_entry=%u allocation=%llu "
                "param=%u resident_frame=%llu revision=%llu resident_cookie=%llu binds=%u readback=%s\n",
                label, u(draw.serial), u(draw.stamp.generation), u(draw.stamp.frame), u(draw.stamp.pass),
                u(draw.stamp.depth_uid), u(draw.stamp.cb0_uid), u32(confirmed), u32(draw.native_entry),
                u(draw.allocation), draw.capture_param, u(draw.resident_frame), u(draw.revision),
                u(draw.resident_cookie), draw.binding_count, draw.readback_reason);
    for (const auto& b : std::span{draw.bindings}.first(draw.binding_count)) {
        std::printf("Reflection native bind target=%s cookie=%llu ordinal=%u slot=%u guest=%llx "
                    "guest_bytes=%u buffer=%llx offset=%llu range=%llu shader_offset=%u "
                    "effective_offset=%llu effective_bytes=%u range_known=%u gpu_dirty=%u in_place=%u writable=%u\n",
                    label, u(draw.serial), b.ordinal, b.slot, u(b.guest), b.guest_bytes,
                    u(std::bit_cast<u64>(b.handle)), u(b.descriptor_offset), u(b.descriptor_range), b.adjust,
                    u(b.descriptor_offset + b.adjust), b.effective_bytes, u32(b.range_known),
                    u32(b.gpu_dirty), u32(b.in_place), u32(b.writable));
    }
}

void Rasterizer::ReflectionNativePoll() {
    using namespace ReflectionNativeProbe;
    for (auto& slot : reflection_native_slots) {
        if (!slot.tick || !scheduler.IsFree(slot.tick)) {
            continue;
        }
        slot.tick = 0;
        const auto u = [](u64 n) { return static_cast<unsigned long long>(n); };
        const auto label = labels[Match(slot.key)];
        if (!slot.confirmed || slot.generation != BbEngine::Loading::Generation() ||
            BbEngine::Loading::ScreenUp() ||
            vmaInvalidateAllocation(instance.GetAllocator(), slot.allocation, 0, ReadbackBytes) != VK_SUCCESS) {
            std::printf("Reflection native bytes target=%s cookie=%llu status=stale-unconfirmed-or-unreadable\n",
                        label, u(slot.serial));
            continue;
        }
        const auto* data = static_cast<const u8*>(slot.mapped);
        for (u32 i = 0; i < slot.binding_bytes.size(); ++i) {
            const auto bytes = slot.binding_bytes[i];
            if (bytes) {
                const auto digest = XXH3_128bits(data + i * MaxBindingBytes, bytes);
                std::printf("Reflection native bytes target=%s cookie=%llu bind_row=%u bytes=%u "
                            "xxh3_128=%016llx%016llx scope=effective-native-bind\n",
                            label, u(slot.serial), i, bytes, u(digest.high64), u(digest.low64));
            }
        }
    }
}

void Rasterizer::ReflectionNativeDestroy() {
    // The Presenter finishes its schedulers before Rasterizer destruction.
    for (auto& slot : reflection_native_slots) {
        if (slot.buffer) {
            vmaDestroyBuffer(instance.GetAllocator(), slot.buffer, slot.allocation);
            slot = {};
        }
    }
}

bool Rasterizer::ReflectionStamp(const AmdGpu::Regs& regs) {
    auto& probe = *reflection_probe;
    const u64 frame = rt_shadow->WindowDiagnosticFrame();
    const u64 generation = BbEngine::Loading::Generation();
    if (probe.input_frame != frame) {
        probe.input_frame = frame;
        probe.input_bytes = 0;
        probe.source_attempts = 0;
        probe.tainted = false;
    }
    if (BbEngine::Loading::ScreenUp() || camera_motion->PreviewFrame() ||
        (probe.stamp && probe.stamp->generation != generation)) {
        if (probe.stamp) {
            rt_shadow->ReflectionCloseEpoch();
            probe.stamp.reset();
        }
        return false;
    }
    const auto matrices = camera_motion->PassMatrices();
    const auto extent = camera_motion->RenderSize();
    const auto jitter = upscaler->Enabled() ? upscaler->Jitter() : std::array<float, 2>{};
    const auto depth_id = db_desc.first;
    const auto cb0_id = cb_descs[0].first;
    auto* depth = depth_id ? texture_cache.TryGetImage(depth_id, 0) : nullptr;
    auto* cb0 = cb0_id ? texture_cache.TryGetImage(cb0_id, 0) : nullptr;
    const auto& vp = regs.viewports[0];
    const auto& vp_ctl = regs.viewport_control;
    const auto near = [](float a, float b) { return std::abs(a - b) <= 0.01f; };
    if (probe.tainted || !matrices.valid || camera_motion->Depth() != depth_id ||
        !depth || !cb0 || !depth->backing || !cb0->backing || scene_targets->Reduced() ||
        trees_pick_rect_on || regs.IsClipDisabled() ||
        !vp_ctl.xscale_enable || !vp_ctl.yscale_enable ||
        !vp_ctl.xoffset_enable || !vp_ctl.yoffset_enable ||
        extent != std::array<u32, 2>{1920, 1080} ||
        target_scale != std::array<float, 2>{1.f, 1.f} || target_offset != std::array<float, 2>{} ||
        !near(std::abs(vp.xscale), float(extent[0]) * .5f) ||
        !near(std::abs(vp.yscale), float(extent[1]) * .5f) ||
        !near(vp.xoffset, float(extent[0]) * .5f) || !near(vp.yoffset, float(extent[1]) * .5f)) {
        ++probe.bad_stamp;
        return false;
    }
    const bool same_camera_pass = probe.stamp && probe.stamp->frame == frame &&
                                  probe.stamp->depth == depth_id && probe.stamp->cb0 == cb0_id;
    const ReflectionFirstHit::Stamp stamp{
        .generation = generation,
        .frame = frame,
        .pass = same_camera_pass ? probe.stamp->pass : ++probe.pass_serial,
        .depth = depth_id,
        .cb0 = cb0_id,
        .depth_uid = depth->image_uid,
        .cb0_uid = cb0->image_uid,
        .depth_image = depth->GetImage(),
        .cb0_image = cb0->GetImage(),
        .view = matrices.view,
        .projection = matrices.proj,
        .jitter = jitter,
        .extent = extent,
        .valid_native = true,
    };
    if (!same_camera_pass || *probe.stamp != stamp) {
        if (!rt_shadow->ReflectionBeginPass(stamp)) {
            probe.stamp.reset();
            probe.tainted = true;
            ++probe.bad_stamp;
            return false;
        }
        probe.stamp = stamp;
    }
    return true;
}

namespace {
bool ReflectionJoinTraceOn() {
    static const bool on = [] {
        const char* text = std::getenv("BB_REFLECTION_JOIN_DIAG");
        return text && std::strcmp(text, "1") == 0;
    }();
    return on;
}

enum class ReflectionJoinTarget { None, Mirror, Fireplace, WallCandidate };

ReflectionJoinTarget JoinTarget(u64 vs, u64 ps, u32 count, u32 first) {
    using enum ReflectionJoinTarget;
    if (count == 42441) {
        return WallCandidate;
    }
    if (vs != 0x9da6aacb) {
        return None;
    }
    if (ps == 0xca7226ec && count == 24 && first == 2440816) {
        return Mirror;
    }
    if (ps == 0xbb10e440 && count == 18282 && first == 158744) {
        return Fireplace;
    }
    return None;
}

bool JoinCount(u32 count) {
    return count == 24 || count == 18282 || count == 42441;
}

// At most 24 distinct rows for each of the three witnesses in a process. No guest-data
// reads, allocation or GPU work are introduced by the trace.
void TraceReflectionJoin(ReflectionJoinTarget target, u64 frame, u64 phase, u64 vs, u64 ps,
                         u32 count, u32 first, std::string_view stage, std::string_view gate,
                         const AmdGpu::Regs& regs, u32 mrt,
                         const RtShadow::Draw* draw = nullptr, u64 a = 0, u64 b = 0) {
    if (target == ReflectionJoinTarget::None) {
        return;
    }
    struct Key {
        u64 phase, vs, ps;
        u32 first;
        std::string_view stage, gate;
        bool operator==(const Key&) const = default;
    };
    struct Rows {
        std::array<Key, 24> emitted{};
        u32 used{};
    };
    static std::array<Rows, 3> by_target{};
    auto& rows = by_target[u32(target) - 1];
    const Key key{phase, vs, ps, first, stage, gate};
    const auto seen = std::span{rows.emitted}.first(rows.used);
    if (rows.used == rows.emitted.size() || std::ranges::find(seen, key) != seen.end()) {
        return;
    }
    rows.emitted[rows.used++] = key;
    u32 blend = 0;
    for (u32 slot = 0; slot < std::size(regs.blend_control); ++slot) {
        blend |= u32(regs.blend_control[slot].enable != 0) << slot;
    }
    const auto u = [](u64 n) { return static_cast<unsigned long long>(n); };
    constexpr std::array names{"mirror", "fireplace", "wall-candidate"};
    std::printf("Reflection join target=%s frame=%llu phase=%llu vs=%08llx ps=%08llx "
                "count=%u first=%u stage=%.*s gate=%.*s mrt=%02x cb0_mask=%x blend=%02x "
                "blend_active=%02x depth_test=%u depth_write=%u depth_compare=%u "
                "instances=%u index_type=%u swap=%u value_a=%llu value_b=%llu\n",
                names[u32(target) - 1], u(frame), u(phase), u(vs), u(ps), count, first,
                int(stage.size()), stage.data(), int(gate.size()), gate.data(), mrt,
                regs.color_target_mask.GetMask(0), blend, blend & mrt,
                u32(regs.depth_control.depth_enable), u32(regs.depth_control.depth_write_enable),
                u32(regs.depth_control.depth_func), regs.num_instances.NumInstances(),
                u32(regs.index_buffer_type.index_type), u32(regs.index_buffer_type.swap_mode),
                u(a), u(b));
    if (draw) {
        std::printf("Reflection join inputs target=%s frame=%llu phase=%llu position=%u "
                    "constants=%u indices=%u index_bytes=%u placement_palette=%u cpu_palette=%u "
                    "skinned=%u bones=%u first_vertex=%d first_instance=%u glass=%u glass_entry=%u "
                    "alpha=%u solid=%u strip=%u restart=%u\n",
                    names[u32(target) - 1], u(frame), u(phase), u32(draw->positions != 0),
                    u32(draw->constants != nullptr), u32(draw->indices != 0), draw->index_size,
                    u32(draw->palette_placed), u32(draw->palette && !draw->palette_placed),
                    u32(draw->skinned), draw->skeleton_bones, s32(draw->first_vertex),
                    draw->first_instance, u32(draw->glass), u32(draw->glass_entry), u32(draw->alpha),
                    u32(draw->solid), u32(draw->strip), u32(draw->restart));
    }
}

enum class PlacementPart : u8 {
    Binding, Index, ObjectDescriptor, ObjectContent, PaletteDescriptor, FetchDescriptor, FetchContent, End,
};

struct PlacementCheckpoint {
    u64 prefix{};
    u32 bytes{};
    u16 ordinal{};
    PlacementPart part = PlacementPart::End;
    bool operator==(const PlacementCheckpoint&) const = default;
};

struct PlacementSample {
    std::array<PlacementCheckpoint, 128> checkpoints{};
    // These four categories can be compared independently. Their inputs are already local
    // descriptor tuples. Content uses the original hash chain and is never read a second time.
    std::array<u64, 4> descriptors{};
    u64 generation{}, frame{}, pass{}, final{};
    u32 used{};
    bool overflow{};

    void Add(PlacementPart part, u16 ordinal, u64 bytes, u64 prefix) {
        if (used == checkpoints.size()) {
            overflow = true;
            return;
        }
        checkpoints[used++] = {.prefix = prefix, .bytes = u32(bytes), .ordinal = ordinal, .part = part};
    }

    void Descriptor(u32 category, PlacementPart part, u16 ordinal,
                    std::span<const u64> fields, u64 prefix) {
        auto& digest = descriptors[category];
        digest = XXH3_64bits_withSeed(fields.data(), fields.size_bytes(), digest);
        Add(part, ordinal, fields.size_bytes(), prefix);
    }
};

struct PlacementHistory {
    PlacementSample sample{}, queued{};
    u64 build_cookie{}, build_allocation{};
    u32 build_param{}, rows{};
};

constexpr u32 PlacementTraceRows = 12;

PlacementHistory* ReflectionPlacementHistory(u32 role) {
    static const bool on = [] {
        const char* flag = std::getenv("BB_REFLECTION_PLACEMENT_COMPONENTS");
        return flag && std::strcmp(flag, "1") == 0;
    }();
    if (!on || role >= ReflectionNativeProbe::WitnessCount) {
        return nullptr;
    }
    static std::array<PlacementHistory, ReflectionNativeProbe::WitnessCount> history{};
    auto& row = history[role];
    return row.rows < PlacementTraceRows ? &row : nullptr;
}

PlacementSample* StartPlacementSample(u32 role, const ReflectionFirstHit::Stamp& stamp) {
    auto* history = ReflectionPlacementHistory(role);
    if (!history) {
        return nullptr;
    }
    auto& sample = history->sample;
    sample.descriptors = {};
    sample.generation = stamp.generation;
    sample.frame = stamp.frame;
    sample.pass = stamp.pass;
    sample.final = 0;
    sample.used = 0;
    sample.overflow = false;
    return &sample;
}

void FinishPlacementSample(const ReflectionFirstHit::Stamp& stamp,
                           const RtShadow::ReflectionDrawToken& token, u32 capture_param) {
    auto* history = ReflectionPlacementHistory(u32(token.placed));
    if (!history || !token.cookie) {
        return;
    }
    const auto& sample = history->sample;
    if (sample.generation != stamp.generation || sample.frame != stamp.frame || sample.pass != stamp.pass ||
        sample.final != token.placement) {
        return;
    }
    const auto u = [](u64 v) { return static_cast<unsigned long long>(v); };
    const auto label = ReflectionNativeProbe::labels[u32(token.placed)];
    const auto& queued = history->queued;
    if (history->build_param && queued.generation == sample.generation && queued.frame < sample.frame) {
        constexpr std::array names{"binding", "index-data", "object-descriptor", "object-content",
                                   "palette-descriptor", "fetch-descriptor", "fetch-content", "end"};
        u32 first = 0;
        const u32 shared = std::min(sample.used, queued.used);
        while (first < shared && sample.checkpoints[first] == queued.checkpoints[first]) {
            ++first;
        }
        const auto a = first < queued.used ? queued.checkpoints[first] : PlacementCheckpoint{};
        const auto b = first < sample.used ? sample.checkpoints[first] : PlacementCheckpoint{};
        const bool same = a.part == PlacementPart::End && b.part == PlacementPart::End;
        u32 descriptor_delta = 0;
        for (u32 i = 0; i < sample.descriptors.size(); ++i) {
            descriptor_delta |= u32(sample.descriptors[i] != queued.descriptors[i]) << i;
        }
        // Only the first differing prefix is attributable. Later prefixes inherit its seed.
        const char* change = sample.overflow || queued.overflow ? "overflow" :
                             same && sample.final != queued.final ? "unexplained" :
                             same ? "same" : a.part != b.part || a.ordinal != b.ordinal || a.bytes != b.bytes
                                 ? "shape" : "prefix";
        std::printf("Reflection placement components target=%s event=compare generation=%llu "
                    "build_frame=%llu build_pass=%llu build_allocation=%llu build_cookie=%llu build_param=%u "
                    "frame=%llu pass=%llu allocation=%llu cookie=%llu capture_param=%u "
                    "result=%s first_step=%u before=%s/%u/%u after=%s/%u/%u "
                    "descriptor_delta=%u previous_hash=%016llx hash=%016llx previous_prefix=%016llx prefix=%016llx\n",
                    label, u(sample.generation), u(queued.frame), u(queued.pass), u(history->build_allocation),
                    u(history->build_cookie), history->build_param, u(sample.frame), u(sample.pass),
                    u(token.allocation), u(token.cookie), capture_param, change, first,
                    names[u32(a.part)], a.ordinal, a.bytes, names[u32(b.part)], b.ordinal, b.bytes,
                    descriptor_delta, u(queued.final), u(sample.final), u(a.prefix), u(b.prefix));
        ++history->rows;
        history->build_param = 0;
    }
    if (capture_param && history->rows < PlacementTraceRows) {
        // This is a preflight with a native capture parameter. The lifecycle trace attests
        // whether it actually became an ordinary build with the same frame, pass and cookie.
        history->queued = sample;
        history->build_param = capture_param;
        history->build_cookie = token.cookie;
        history->build_allocation = token.allocation;
        std::printf("Reflection placement components target=%s event=capture generation=%llu "
                    "frame=%llu pass=%llu allocation=%llu cookie=%llu capture_param=%u "
                    "steps=%u overflow=%u hash=%016llx\n",
                    label, u(sample.generation), u(sample.frame), u(sample.pass), u(token.allocation),
                    u(token.cookie), capture_param, sample.used, u32(sample.overflow), u(sample.final));
        ++history->rows;
    }
}

constexpr u32 OrdinalZeroByteLimit = 4096;
constexpr u32 OrdinalZeroWordCount = 104;
constexpr u32 OrdinalZeroWordBytes = OrdinalZeroWordCount * sizeof(u32);
constexpr u32 OrdinalZeroPlacementWord = 20;
using OrdinalZeroWords = std::array<u32, OrdinalZeroWordCount>;

bool CopyOrdinalZeroWords(OrdinalZeroWords& words, std::span<const u8> owned, u64 range,
                          u32 stride, u32 records, std::string_view route) {
    // The binder supplies a span only after the direct CPU copy is complete at the bound offset.
    if ((route != "constant-ring" && route != "staged-cpu-copy") || range != OrdinalZeroWordBytes ||
        stride != 16 || records != 26 || owned.size() < OrdinalZeroWordBytes) {
        return false;
    }
    std::memcpy(words.data(), owned.data(), OrdinalZeroWordBytes);
    return true;
}

struct OrdinalZeroSample {
    OrdinalZeroWords words{};
    u64 exact_object3_digest{};
    u32 exact_object3_origin{};
    bool exact_object3{}, exact_placement{};
    AmdGpu::Buffer sharp{};
    std::string_view route{};
    u64 source_address{}, descriptor_range{}, effective_digest{}, guest_digest{};
    u64 preflight_address{}, cookie{}, allocation{}, placement{}, generation{}, frame{}, pass{};
    u32 slot{}, adjust{}, binding_type{}, flags{}, effective_bytes{}, guest_bytes{};
    u32 preflight_size{}, param{};
    bool descriptor_present{}, preflight{}, exact_sharp{}, words_certified{};
    u64 guest_vs{}, guest_ps{}, stage_vs{}, stage_ps{};
    u32 foliage_mask{}, user_clip_planes{};
};

struct OrdinalZeroDifference {
    std::array<u64, 2> mask{};
    u32 before20{}, after20{};
    bool certified{};
};

OrdinalZeroDifference CompareOrdinalZeroWords(const OrdinalZeroSample& before,
                                              const OrdinalZeroSample& after) {
    OrdinalZeroDifference result;
    if (!before.words_certified || !after.words_certified) {
        return result;
    }
    result.certified = true;
    result.before20 = before.words[OrdinalZeroPlacementWord];
    result.after20 = after.words[OrdinalZeroPlacementWord];
    for (u32 i = 0; i < OrdinalZeroWordCount; ++i) {
        result.mask[i / 64] |= u64(before.words[i] != after.words[i]) << (i % 64);
    }
    return result;
}

struct OrdinalZeroTrace {
    const ReflectionNativeProbe::Draw* owner{};
    OrdinalZeroSample bind{}, build{};
    u32 attempts{}, rows{};
};
constexpr u32 OrdinalZeroRowLimit = 12;

OrdinalZeroTrace* OrdinalZeroTraceFor(u32 target) {
    static const bool on = [] {
        const char* flag = std::getenv("BB_REFLECTION_ORDINAL0_PROOF");
        return flag && std::strcmp(flag, "1") == 0;
    }();
    if (!on || target >= ReflectionNativeProbe::WitnessCount) {
        return nullptr;
    }
    static std::array<OrdinalZeroTrace, ReflectionNativeProbe::WitnessCount> traces{};
    return &traces[target];
}

OrdinalZeroSample* OrdinalZeroFor(const ReflectionNativeProbe::Draw& draw) {
    auto* trace = OrdinalZeroTraceFor(ReflectionNativeProbe::Match(draw.key));
    return trace && trace->owner == &draw ? &trace->bind : nullptr;
}

void LogOrdinalZero(const char* event, u32 role, const OrdinalZeroSample& now,
                    const OrdinalZeroSample& build) {
    const auto u = [](u64 v) { return static_cast<unsigned long long>(v); };
    const auto tag = [&](u64 address) { return u(XXH3_64bits(&address, sizeof(address))); };
    const auto compare = [](u32 a_len, u64 a, u32 b_len, u64 b) {
        return !a_len || !b_len ? "unavailable" : a_len == b_len && a == b ? "same" : "different";
    };
    const u32 delta = u32(now.sharp.base_address != build.sharp.base_address) |
                      (u32(now.sharp.GetSize() != build.sharp.GetSize()) << 1) |
                      (u32(now.sharp.GetStride() != build.sharp.GetStride()) << 2) |
                      (u32(now.sharp.type != build.sharp.type || now.binding_type != build.binding_type) << 3) |
                      (u32(now.flags != build.flags) << 4) |
                      (u32(now.source_address != build.source_address) << 5);
    const auto words = CompareOrdinalZeroWords(build, now);
    const char* word_compare = !words.certified ? "unavailable" :
                               words.mask[0] || words.mask[1] ? "different" : "same";
    // Print most-significant hex digits first; bit 0 is ordinal0 word 0.
    std::array<char, 27> changed_words{'-'};
    std::array<char, 9> before20{'-'}, after20{'-'};
    if (words.certified) {
        std::snprintf(changed_words.data(), changed_words.size(), "%010llx%016llx",
                      u(words.mask[1]), u(words.mask[0]));
        std::snprintf(before20.data(), before20.size(), "%08x", words.before20);
        std::snprintf(after20.data(), after20.size(), "%08x", words.after20);
    }
    std::printf("Reflection ordinal0 target=%s event=%s generation=%llu frame=%llu pass=%llu "
                "allocation=%llu cookie=%llu param=%u placement=%016llx "
                "build_frame=%llu build_pass=%llu build_allocation=%llu build_cookie=%llu build_param=%u "
                "guest_address_tag=%016llx source_address_tag=%016llx preflight_address_tag=%016llx "
                "guest_size=%u preflight_size=%u stride=%u records=%u sharp_type=%u resource_type=%u "
                "flags=%u slot=%u range=%llu adjust=%u sharp_matches_preflight=%u "
                "source=%.*s descriptor_present=%u actual_bytes=%u actual_digest=%016llx "
                "guest_bytes=%u guest_digest=%016llx descriptor_delta=%u actual_compare=%s guest_compare=%s "
                "word_compare=%s changed_words=%s word20_build=%s word20_now=%s "
                "guest_vs=%016llx guest_ps=%016llx stage_vs=%016llx stage_ps=%016llx foliage_mask=%u "
                "build_guest_vs=%016llx build_guest_ps=%016llx build_stage_vs=%016llx build_stage_ps=%016llx "
                "build_foliage_mask=%u user_clip_planes=%u build_user_clip_planes=%u\n",
                ReflectionNativeProbe::labels[role], event, u(now.generation), u(now.frame), u(now.pass),
                u(now.allocation), u(now.cookie), now.param, u(now.placement), u(build.frame), u(build.pass),
                u(build.allocation), u(build.cookie), build.param,
                tag(now.sharp.base_address), tag(now.source_address), tag(now.preflight_address),
                now.sharp.GetSize(), now.preflight_size, now.sharp.GetStride(), now.sharp.num_records,
                u32(now.sharp.type), now.binding_type, now.flags, now.slot, u(now.descriptor_range), now.adjust,
                u32(now.exact_sharp), int(now.route.size()), now.route.data(), u32(now.descriptor_present),
                now.effective_bytes, u(now.effective_digest), now.guest_bytes, u(now.guest_digest), delta,
                compare(now.effective_bytes, now.effective_digest, build.effective_bytes, build.effective_digest),
                compare(now.guest_bytes, now.guest_digest, build.guest_bytes, build.guest_digest),
                word_compare, changed_words.data(), before20.data(), after20.data(),
                u(now.guest_vs), u(now.guest_ps), u(now.stage_vs), u(now.stage_ps), now.foliage_mask,
                u(build.guest_vs), u(build.guest_ps), u(build.stage_vs), u(build.stage_ps), build.foliage_mask,
                now.user_clip_planes, build.user_clip_planes);
}

constexpr u64 ReflectionInputDrawBytes = 4 << 20;
constexpr u64 ReflectionInputRoleBytes = 12 << 20;
constexpr u32 ReflectionInputSlots = 32;
constexpr u32 ReflectionNoPayload = ~u32{0};

enum class ReflectionInputPart : u8 { Index, Object, UnboundObject, Camera, Palette, Fetch };

struct ReflectionInputEntry {
    AmdGpu::Buffer sharp{};
    // Object resource metadata, palette effective binding, or fetch load fields.
    std::array<u64, 6> fields{};
    u64 guest{}, bytes{};
    u32 ordinal{}, payload = ReflectionNoPayload;
    ReflectionInputPart part{};
    bool fetch_guarded{};
};

struct ReflectionInputPayload {
    u64 guest{}, bytes{}, digest{};
};

struct ReflectionInputSample {
    std::array<u64, 6> binding{};
    std::array<ReflectionInputEntry, ReflectionInputSlots> entries{};
    std::array<ReflectionInputPayload, ReflectionInputSlots> payloads{};
    u64 generation{}, frame{}, pass{}, hashed{};
    u32 used{}, unique{};
    bool overflow{}, fetch_unsupported{};

    u32 HashPayload(u64 guest, u64 bytes, u64& remaining) {
        const auto checked = std::span{payloads}.first(unique);
        const auto duplicate = std::ranges::find_if(checked, [&](const auto& payload) {
            return payload.guest == guest && payload.bytes == bytes;
        });
        if (duplicate != checked.end()) {
            return u32(duplicate - checked.begin());
        }
        if (bytes > remaining || bytes > ReflectionInputDrawBytes - hashed ||
            unique == payloads.size()) {
            overflow = true;
            return ReflectionNoPayload;
        }
        const u32 slot = unique++;
        payloads[slot] = {guest, bytes, XXH3_64bits(reinterpret_cast<const void*>(guest), bytes)};
        remaining -= bytes;
        hashed += bytes;
        return slot;
    }

    // Fetch descriptors only arrive here for clean ranges or exact repeats of them.
    // Hash the overlapping fetch unions after the full descriptor inventory is known.
    void Add(ReflectionInputEntry entry, bool clean, u64& remaining) {
        if (used == entries.size()) {
            overflow = true;
            return;
        }
        if (entry.part == ReflectionInputPart::Fetch) {
            entry.fetch_guarded = clean;
        } else if (clean) {
            entry.payload = HashPayload(entry.guest, entry.bytes, remaining);
        }
        entries[used++] = entry;
    }

    template <typename Guard>
    void FinishFetch(u64& remaining, Guard&& guarded) {
        std::array<u32, ReflectionInputSlots> order{};
        u32 count = 0;
        for (u32 slot = 0; slot < used; ++slot) {
            const auto& entry = entries[slot];
            if (entry.part != ReflectionInputPart::Fetch) {
                continue;
            }
            if (!entry.fetch_guarded || !entry.guest || !entry.bytes ||
                entry.bytes > std::numeric_limits<u64>::max() - entry.guest) {
                fetch_unsupported = true;
                continue;
            }
            order[count++] = slot;
        }
        const auto fetches = std::span{order}.first(count);
        std::ranges::sort(fetches, {}, [&](u32 slot) { return entries[slot].guest; });
        for (u32 start = 0; start < count;) {
            const auto& first = entries[fetches[start]];
            const u64 address = first.guest;
            u64 end = address + first.bytes;
            u32 next = start + 1;
            while (next < count && entries[fetches[next]].guest < end) {
                const auto& overlap = entries[fetches[next++]];
                end = std::max(end, overlap.guest + overlap.bytes);
            }
            const u64 bytes = end - address;
            if (!guarded(address, bytes)) {
                fetch_unsupported = true;
            } else {
                const u32 payload = HashPayload(address, bytes, remaining);
                for (u32 slot : fetches.subspan(start, next - start)) {
                    entries[slot].payload = payload;
                }
            }
            start = next;
        }
    }
};

struct ReflectionInputTrace {
    ReflectionInputSample current{}, build{};
    u64 remaining = ReflectionInputRoleBytes;
    struct Refusal {
        u64 request{};
        u32 flags{}, native_stamp_reject{};
        bool operator==(const Refusal&) const = default;
    };
    std::array<Refusal, 8> refusals{};
    u32 refusal_count{};
    bool stamp_retry_reported{};
};

ReflectionInputTrace* ReflectionInputsFor(u32 role) {
    static const bool on = [] {
        const char* flag = std::getenv("BB_REFLECTION_INDEPENDENT_INPUTS");
        return flag && std::strcmp(flag, "1") == 0;
    }();
    if (!on || role >= ReflectionNativeProbe::WitnessCount || !ReflectionFirstHit::PlacedOn()) {
        return nullptr;
    }
    static std::array<ReflectionInputTrace, ReflectionNativeProbe::WitnessCount> traces{};
    return &traces[role];
}

bool ClaimStampRetryTrace(const Rasterizer* owner, const ReflectionNativeProbe::StampRetry& retry) {
    const auto* row = ReflectionFirstRetire::Current(owner);
    if (!row || !ReflectionFirstRetire::receipt.fireplace.current ||
        ReflectionFirstRetire::receipt.fireplace.generation != retry.early.generation) {
        return false;
    }
    auto* input = ReflectionInputsFor(FireplaceRole);
    return input && !std::exchange(input->stamp_retry_reported, true);
}

void TraceStampRetry(const char* event, const Rasterizer* owner, const ReflectionNativeProbe::StampRetry& retry,
                     const ReflectionFirstHit::Stamp* stamp, u64 tick, const RtShadow::ReflectionDrawToken& token,
                     bool original = false, bool exact = false, bool confirmed = false) {
    const auto* row = ReflectionFirstRetire::Current(owner);
    if (!retry.reporting || !row) return;
    const auto u = ReflectionFirstRetire::Print;
    std::printf("Reflection stamp retry (r140a): event=%s renderer=%llx sequence=%llu generation=%llu "
                "prior_frame=%llu prior_pass=%llu early_frame=%llu frame=%llu pass=%llu early_tick=%llu tick=%llu "
                "early_reason=%u failure=%s validator_reject=%u current=%u safe=%u palette=%u handle=%u alpha=%u "
                "classified=%u allocation=%llu cookie=%llu placement=%llu original=%u exact=%u confirmed=%u\n",
                event, u(reinterpret_cast<uintptr_t>(owner)), u(row->sequence), u(retry.early.generation),
                u(retry.prior_frame), u(retry.prior_pass), u(retry.early.frame),
                u(stamp ? stamp->frame : 0), u(stamp ? stamp->pass : 0), u(retry.early_tick), u(tick),
                u32(StampFrame), retry.failure, retry.validator_reject, u32(retry.current), u32(retry.safe),
                u32(retry.palette), u32(retry.handle), u32(retry.alpha), u32(retry.classified),
                u(token.allocation), u(token.cookie), u(token.placement), u32(original), u32(exact), u32(confirmed));
}

bool SameInputStamp(const ReflectionInputSample& sample, const OrdinalZeroSample& note) {
    return sample.generation == note.generation && sample.frame == note.frame && sample.pass == note.pass;
}

void LogReflectionInputs(const char* event, u32 role, const OrdinalZeroSample& note,
                         const OrdinalZeroSample& build_note) {
    auto* trace = ReflectionInputsFor(role);
    if (!trace) {
        return;
    }
    const bool capture = note.frame == build_note.frame && note.pass == build_note.pass;
    const auto& now = trace->current;
    const auto& before = capture ? now : trace->build;
    const bool stamped = SameInputStamp(now, note) && SameInputStamp(before, build_note);
    const char* status = !stamped ? "unavailable" :
                         now.fetch_unsupported || before.fetch_unsupported ? "unsupported" :
                         now.overflow || before.overflow ? "overflow" : "complete";
    const auto u = [](u64 v) { return static_cast<unsigned long long>(v); };
    const auto label = ReflectionNativeProbe::labels[role];
    std::printf("Reflection independent target=%s event=%s generation=%llu frame=%llu pass=%llu "
                "allocation=%llu cookie=%llu param=%u placement=%016llx "
                "build_frame=%llu build_pass=%llu build_allocation=%llu build_cookie=%llu build_param=%u "
                "status=%s entries=%u/%u unique=%u/%u hashed=%llu/%llu remaining=%llu binding_same=%u\n",
                label, event, u(note.generation), u(note.frame), u(note.pass), u(note.allocation),
                u(note.cookie), note.param, u(note.placement), u(build_note.frame), u(build_note.pass),
                u(build_note.allocation), u(build_note.cookie), build_note.param, status,
                before.used, now.used, before.unique, now.unique, u(before.hashed), u(now.hashed),
                u(trace->remaining), u32(stamped && before.binding == now.binding));
    if (!stamped) {
        return;
    }
    const auto log_sample = [&](const char* side, const OrdinalZeroSample& stamp,
                                const ReflectionInputSample& sample) {
        const auto& bind = sample.binding;
        std::printf("Reflection independent binding target=%s event=%s side=%s frame=%llu pass=%llu "
                    "cookie=%llu words=%016llx/%016llx/%016llx/%016llx/%016llx/%016llx\n",
                    label, event, side, u(stamp.frame), u(stamp.pass), u(stamp.cookie),
                    u(bind[0]), u(bind[1]), u(bind[2]), u(bind[3]), u(bind[4]), u(bind[5]));
        constexpr std::array parts{"index", "object", "unbound-object", "camera", "palette", "fetch"};
        for (const auto& entry : std::span{sample.entries}.first(sample.used)) {
            std::array<u32, 4> words{};
            static_assert(sizeof(words) == sizeof(entry.sharp));
            std::memcpy(words.data(), &entry.sharp, sizeof(words));
            const auto* payload = entry.payload == ReflectionNoPayload ? nullptr : &sample.payloads[entry.payload];
            const auto& f = entry.fields;
            std::printf("Reflection independent input target=%s event=%s side=%s frame=%llu pass=%llu "
                        "cookie=%llu part=%s ordinal=%u sharp=%08x/%08x/%08x/%08x stride=%u format=%u/%u "
                        "guest=%016llx bytes=%llu fields=%016llx/%016llx/%016llx/%016llx/%016llx/%016llx "
                        "payload_slot=%d digest=%016llx payload_guest=%016llx payload_bytes=%llu payload_scope=%s\n",
                        label, event, side, u(stamp.frame), u(stamp.pass), u(stamp.cookie),
                        parts[u32(entry.part)], entry.ordinal, words[0], words[1], words[2], words[3],
                        entry.sharp.GetStride(), u32(entry.sharp.data_format), u32(entry.sharp.num_format),
                        u(entry.guest), u(entry.bytes), u(f[0]), u(f[1]), u(f[2]), u(f[3]), u(f[4]), u(f[5]),
                        payload ? int(entry.payload) : -1, u(payload ? payload->digest : 0),
                        u(payload ? payload->guest : 0), u(payload ? payload->bytes : 0),
                        !payload ? "unavailable" : entry.part == ReflectionInputPart::Fetch ?
                            "fetch-union" : "span");
        }
    };
    if (capture) {
        trace->build = now;
        log_sample("build", note, now);
    } else {
        log_sample("build", build_note, before);
        log_sample("now", note, now);
    }
}

void TraceReflectionPlacedRefusal(u32 role, u64 request, const ReflectionFirstHit::Stamp& stamp,
                                  const ReflectionNativeProbe::Draw* native) {
    auto* trace = ReflectionInputsFor(role);
    if (!trace) {
        return;
    }
    const bool same_stamp = native && native->stamped && native->stamp == stamp;
    const auto* binding = native && native->binding_count ? &native->bindings.front() : nullptr;
    const u32 flags = u32(native != nullptr) | (u32(native && native->stamped) << 1) |
                      (u32(same_stamp) << 2) | (u32(native && native->placement_safe) << 3) |
                      (u32(native && native->overflow) << 4) | (u32(binding && binding->range_known) << 5) |
                      (u32(binding && binding->gpu_dirty) << 6) | (u32(binding && binding->in_place) << 7) |
                      (u32(binding && binding->writable) << 8) | (u32(binding && binding->handle) << 9) |
                      (u32(binding && binding->buffer) << 10);
    const u32 stamp_reject = native ? native->stamp_reject : 0;
    const ReflectionInputTrace::Refusal key{request, flags, stamp_reject};
    const auto seen = std::span{trace->refusals}.first(trace->refusal_count);
    if (trace->refusal_count == trace->refusals.size() || std::ranges::find(seen, key) != seen.end()) {
        return;
    }
    trace->refusals[trace->refusal_count++] = key;
    const auto u = [](u64 v) { return static_cast<unsigned long long>(v); };
    std::printf("Reflection independent refusal target=%s stage=preflight request=%llu generation=%llu "
                "frame=%llu pass=%llu native_generation=%llu native_frame=%llu native_pass=%llu "
                "flags=%x native_stamp_reject=%x bindings=%u ordinal=%u slot=%u adjust=%u offset=%llu "
                "guest_bytes=%u effective_bytes=%u range=%llu\n",
                ReflectionNativeProbe::labels[role], u(request), u(stamp.generation), u(stamp.frame),
                u(stamp.pass), u(native ? native->stamp.generation : 0), u(native ? native->stamp.frame : 0),
                u(native ? native->stamp.pass : 0), flags, stamp_reject, native ? native->binding_count : 0,
                binding ? binding->ordinal : 0, binding ? binding->slot : 0, binding ? binding->adjust : 0,
                u(binding ? binding->descriptor_offset : 0), binding ? binding->guest_bytes : 0,
                binding ? binding->effective_bytes : 0, u(binding ? binding->descriptor_range : 0));
}

void SubmitOrdinalZero(const ReflectionNativeProbe::Draw& draw, const ReflectionFirstHit::Stamp& stamp,
                       const RtShadow::ReflectionDrawToken& token, const GraphicsPipeline& raster_pipeline,
                       u32 user_clip_planes) {
    const u32 role = ReflectionNativeProbe::Match(draw.key);
    auto* trace = OrdinalZeroTraceFor(role);
    if (!trace || trace->owner != &draw ||
        !token.cookie || u32(token.placed) != role || trace->rows >= OrdinalZeroRowLimit) {
        return;
    }
    trace->owner = nullptr;
    auto& actual = trace->bind;
    if (!actual.preflight || actual.param == ~u32{0}) {
        return;
    }
    actual.cookie = token.cookie;
    actual.allocation = token.allocation;
    actual.placement = token.placement;
    actual.generation = stamp.generation;
    actual.frame = stamp.frame;
    actual.pass = stamp.pass;
    actual.user_clip_planes = user_clip_planes;
    constexpr u32 vs = u32(Shader::SwStage::Vertex), ps = u32(Shader::SwStage::Fragment);
    const auto& key = raster_pipeline.GetGraphicsKey();
    const auto stages = raster_pipeline.GetStages();
    // Pipeline keys name the selected ShaderMeta permutation. Guest pgm_hash alone cannot.
    actual.guest_vs = stages[vs] ? stages[vs]->pgm_hash : 0;
    actual.guest_ps = stages[ps] ? stages[ps]->pgm_hash : 0;
    actual.stage_vs = key.stage_hashes[vs];
    actual.stage_ps = key.stage_hashes[ps];
    actual.foliage_mask = key.foliage_mask;
    if (draw.exact) {
        const auto& exact = *draw.exact;
        actual.exact_object3 = exact.binding3.complete;
        actual.exact_object3_origin = u32(exact.binding3.origin);
        actual.exact_placement = exact.placement && exact.submitted;
        if (actual.exact_object3) {
            actual.exact_object3_digest = XXH3_64bits(exact.object3.data(), exact.object3.size());
        }
    }
    auto& build = trace->build;
    if (build.param && build.generation == actual.generation && build.frame < actual.frame) {
        const char* event = actual.param ? "next-capture" : "next-cached";
        LogOrdinalZero(event, role, actual, build);
        if (draw.exact) {
            const auto u = [](u64 n) { return static_cast<unsigned long long>(n); };
            std::printf("Reflection exact pair target=%s generation=%llu frame=%llu pass=%llu cookie=%llu "
                        "build_frame=%llu build_pass=%llu build_cookie=%llu status=%s "
                        "object3_effective=%016llx/%016llx origin=%u/%u canonical=%u/%u\n",
                        ReflectionNativeProbe::labels[role], u(actual.generation), u(actual.frame),
                        u(actual.pass), u(actual.cookie), u(build.frame), u(build.pass), u(build.cookie),
                        !build.exact_object3 || !actual.exact_object3 ? "unsupported" :
                        build.exact_object3_digest == actual.exact_object3_digest ? "same" : "changed",
                        u(build.exact_object3_digest), u(actual.exact_object3_digest),
                        build.exact_object3_origin, actual.exact_object3_origin,
                        u32(build.exact_placement), u32(actual.exact_placement));
        }
        LogReflectionInputs(event, role, actual, build);
        ++trace->rows;
        build = {};
    }
    if (actual.param && trace->rows < OrdinalZeroRowLimit) {
        build = actual;
        LogOrdinalZero("capture", role, actual, build);
        LogReflectionInputs("capture", role, actual, build);
        ++trace->rows;
    }
}
} // namespace

namespace ReflectionNativeProbe {
bool BeginOrdinalZero(const Draw& draw) {
    if (!ReflectionFirstHit::PlacedOn()) {
        return false;
    }
    auto* trace = OrdinalZeroTraceFor(Match(draw.key));
    if (!trace) {
        return false;
    }
    trace->owner = nullptr;
    if (trace->rows >= OrdinalZeroRowLimit || trace->attempts == 32) {
        return false;
    }
    ++trace->attempts;
    trace->owner = &draw;
    trace->bind = {};
    trace->bind.param = ~u32{0};
    return true;
}

void RecordOrdinalZero(const Draw& draw, const Shader::BufferResource& resource,
                       const AmdGpu::Buffer& sharp, const vk::DescriptorBufferInfo& bound,
                       u32 slot, u32 adjust, VAddr source_address, bool prepared,
                       std::string_view route, std::span<const u8> owned) {
    auto* sample = OrdinalZeroFor(draw);
    if (!sample) {
        return;
    }
    sample->sharp = sharp;
    sample->source_address = source_address;
    sample->route = route;
    sample->descriptor_present = bool(bound.buffer);
    sample->descriptor_range = bound.range;
    sample->slot = slot;
    sample->adjust = adjust;
    sample->binding_type = u32(resource.buffer_type);
    sample->flags = u32(resource.is_uniform) | (u32(resource.is_written) << 1) |
                    (u32(resource.is_formatted) << 2) | (u32(resource.only_const_reads) << 3) |
                    (u32(prepared) << 4);
    if (!bound.buffer || resource.IsSpecial() || resource.is_written || adjust || !bound.range ||
        bound.range == VK_WHOLE_SIZE || (route != "constant-ring" && route != "staged-cpu-copy")) {
        return;
    }
    const u64 effective = bound.range;
    if (effective <= OrdinalZeroByteLimit && effective <= owned.size()) {
        sample->effective_bytes = u32(effective);
        sample->effective_digest = XXH3_64bits(owned.data(), effective);
        sample->words_certified = sharp.Valid() && sharp.GetSize() == effective &&
            CopyOrdinalZeroWords(sample->words, owned, effective, sharp.GetStride(), sharp.num_records, route);
    }
}
void RecordExactObject(ReflectionFirstRetire::Row* receipt, Draw& draw, u32 ordinal,
                       const Shader::BufferResource& resource,
                       const AmdGpu::Buffer& sharp, const vk::DescriptorBufferInfo& bound,
                       u32 slot, u32 adjust, VAddr source_address, std::string_view route,
                       std::span<const u8> owned) {
    auto& exact = *draw.exact;
    auto& note = ordinal == 0 ? exact.binding0 : exact.binding3;
    const bool duplicate = note.origin != ObjectOrigin::Unseen;
    const auto out = ordinal == 0 ? std::span<u8>{exact.object0} : std::span<u8>{exact.object3};
    auto* observed = receipt && receipt->key == draw.key ? &receipt->objects[ordinal == 0 ? 0 : 1] : nullptr;
    ObjectOrigin origin = ObjectOrigin::BufferCache;
    if (route == "constant-ring") {
        origin = ObjectOrigin::ConstantRing;
    } else if (route == "staged-cpu-copy") {
        origin = ObjectOrigin::StagedCpuCopy;
    } else if (route == "gpu-copy-unavailable") {
        origin = ObjectOrigin::GpuCopy;
    } else if (route == "stream-copy-unproven") {
        origin = ObjectOrigin::UnprovenStream;
    }
    constexpr std::array slots0{20u, 17u, 23u}, slots3{23u, 20u, 26u};
    const u32 role = Match(draw.key);
    note = {.sharp = sharp, .address = source_address, .range = bound.range,
            .slot = slot, .adjust = adjust, .origin = origin};
    if (ordinal == 3 && receipt && ReflectionOrdinal3::On()) {
        auto& chosen = ReflectionOrdinal3::state.chosen;
        if (chosen.active && chosen.draw.sequence == receipt->sequence) {
            chosen.bind_complete = ReflectionOrdinal3::writer.Cutoff(ReflectionOrdinal3::Bound);
        }
    }
    if (observed) {
        *observed = {.buffer = std::bit_cast<u64>(bound.buffer), .offset = bound.offset,
            .range = bound.range, .guest = source_address, .guest_bytes = sharp.Valid() ? sharp.GetSize() : 0,
            .slot = slot, .adjust = adjust, .origin = u32(origin), .count = observed->count + 1, .route = route};
    }
    if (duplicate || role == NoWitness || !bound.buffer || resource.IsSpecial() ||
        !resource.is_uniform || resource.is_written || resource.is_formatted || !resource.only_const_reads ||
        !sharp.Valid() || !source_address || sharp.base_address != source_address ||
        sharp.GetStride() != 16 || sharp.GetSize() != out.size() || sharp.num_records != out.size() / 16 ||
        slot != (ordinal == 0 ? slots0[role] : slots3[role]) || adjust || bound.range != out.size() ||
        owned.size() != out.size() ||
        (origin != ObjectOrigin::ConstantRing && origin != ObjectOrigin::StagedCpuCopy)) {
        return;
    }
    std::ranges::copy(owned, out.begin());
    note.complete = true;
    if (observed) {
        observed->complete = true;
        observed->digest = XXH3_64bits(out.data(), out.size());
    }
}
} // namespace ReflectionNativeProbe

namespace {
bool ExactReflectionActiveWordsOn() {
    static const bool on = [] {
        const char* flag = std::getenv("BB_REFLECTION_EXACT_ACTIVE_WORDS");
        return flag && std::strcmp(flag, "1") == 0;
    }();
    return on;
}

bool ExactReflectionWord22On() {
    static const bool on = [] {
        const char* flag = std::getenv("BB_REFLECTION_EXACT_WORD22");
        return flag && std::strcmp(flag, "1") == 0;
    }();
    return on;
}

enum class DeltaPart : u8 {
    Binding, Mode, Index, PaletteGuest, PaletteBinding, ObjectRange, ObjectSharp, ObjectResource,
    ObjectBinding, ObjectWords, ObjectPayload, FetchRange, FetchSharp, FetchResource, FetchPayload
};
constexpr std::array delta_parts{"binding", "exact-domain", "index-payload", "palette-guest",
    "palette-binding", "object-range", "object-sharp", "object-resource", "object-binding",
    "object-words", "object-payload", "fetch-range", "fetch-sharp", "fetch-resource", "fetch-payload"};

struct PlacementDeltaStep {
    u64 before{}, after{}, address{}, bytes{};
    u16 offset{}, ordinal{};
    DeltaPart part{};
    u8 word_bytes{};
};

struct PlacementDeltaSample {
    std::array<PlacementDeltaStep, 48> steps{};
    std::array<u8, 1280> small{};
    u64 generation{}, frame{}, pass{}, key{}, cookie{}, allocation{};
    u16 used{}, small_used{};
    bool overflow{}, canonical{};
    u32 origin0{}, origin3{}, raw_word22{}, raw_word23{};

    void Begin(const ReflectionFirstHit::Stamp& stamp) {
        generation = stamp.generation;
        frame = stamp.frame;
        pass = stamp.pass;
        used = small_used = 0;
        overflow = canonical = false;
        key = cookie = allocation = 0;
        origin0 = origin3 = raw_word22 = raw_word23 = 0;
    }

    void Add(DeltaPart part, u16 ordinal, u64 hash, u64 guest, u64 bytes,
             const void* data = nullptr, u8 word_bytes = 0) {
        if (used == steps.size() || (data && bytes > small.size() - small_used)) {
            overflow = true;
            return;
        }
        const u64 before = used ? steps[used - 1].after : 0;
        steps[used++] = {before, hash, guest, bytes, small_used, ordinal, part, word_bytes};
        if (data) {
            std::memcpy(small.data() + small_used, data, bytes);
            small_used += u16(bytes);
        }
    }

    template <typename T, size_t Count>
    void Tuple(DeltaPart part, u16 ordinal, const std::array<T, Count>& value, u64 hash) {
        Add(part, ordinal, hash, 0, sizeof(value), value.data(), sizeof(T));
    }

    u64 Word(const PlacementDeltaStep& step, u32 index) const {
        u64 value = 0;
        std::memcpy(&value, small.data() + step.offset + index * step.word_bytes, step.word_bytes);
        return value;
    }
};

enum class DeltaKind : u8 { Same, Mode, Field, Shape, Range, Payload, Coverage, Overflow };

struct PlacementDeltaDifference {
    DeltaKind kind{};
    u32 step{}, field{};
};

PlacementDeltaDifference FirstPlacementDifference(const PlacementDeltaSample& old,
                                                  const PlacementDeltaSample& next) {
    if (old.overflow || next.overflow) {
        return {DeltaKind::Overflow};
    }
    if (old.canonical != next.canonical) {
        return {DeltaKind::Mode};
    }
    for (u32 i = 0; i < std::min(old.used, next.used); ++i) {
        const auto& a = old.steps[i];
        const auto& b = next.steps[i];
        if (a.part != b.part || a.ordinal != b.ordinal || a.word_bytes != b.word_bytes) {
            return {DeltaKind::Shape, i};
        }
        if (a.before != b.before) {
            return {DeltaKind::Coverage, i};
        }
        if (a.address != b.address || a.bytes != b.bytes) {
            return {DeltaKind::Range, i};
        }
        if (a.word_bytes) {
            for (u32 word = 0; word < a.bytes / a.word_bytes; ++word) {
                if (old.Word(a, word) != next.Word(b, word)) {
                    return {DeltaKind::Field, i, word};
                }
            }
        }
        if (a.after != b.after) {
            return {a.word_bytes ? DeltaKind::Coverage : DeltaKind::Payload, i};
        }
    }
    if (old.used != next.used) {
        return {DeltaKind::Shape, std::min(old.used, next.used)};
    }
    return {old.key == next.key ? DeltaKind::Same : DeltaKind::Coverage, old.used};
}

struct PlacementDeltaTrace {
    std::array<PlacementDeltaSample, 2> samples{};
    u32 current{};
    u8 raw_words_reported{};
    bool baseline{}, done{};

    PlacementDeltaSample& Pending() { return samples[current]; }
    const PlacementDeltaSample& Prior() const { return samples[current ^ 1]; }
};
static_assert(sizeof(PlacementDeltaTrace) <= 8 * 1024);

PlacementDeltaTrace* FireplacePlacementDelta(const ReflectionNativeProbe::Draw* draw) {
    static const bool on = [] {
        const char* flag = std::getenv("BB_REFLECTION_FIRST_PLACEMENT_DELTA");
        return flag && std::strcmp(flag, "1") == 0;
    }();
    if (!on || !draw || !ReflectionFirstHit::PlacedOn() ||
        ReflectionNativeProbe::Match(draw->key) != u32(ReflectionFirstHit::PlacedSource::Fireplace)) {
        return nullptr;
    }
    static PlacementDeltaTrace trace;
    return trace.done ? nullptr : &trace;
}

const char* PlacementDeltaField(DeltaPart part, u32 field) {
    switch (part) {
    case DeltaPart::Binding: {
        constexpr std::array names{"vs", "positions", "indices", "first", "first-vertex", "index-size"};
        return names[field];
    }
    case DeltaPart::PaletteGuest: {
        constexpr std::array names{"guest-base", "guest-bytes"};
        return names[field];
    }
    case DeltaPart::PaletteBinding: {
        constexpr std::array names{"slot", "adjust", "descriptor-offset", "descriptor-range", "handle"};
        return names[field];
    }
    case DeltaPart::ObjectRange: {
        constexpr std::array names{"normalized-base", "size"};
        return names[field];
    }
    case DeltaPart::ObjectResource: {
        constexpr std::array names{"ordinal", "resource-type", "flags", "used-types", "post-op", "post-mask"};
        return names[field];
    }
    case DeltaPart::ObjectBinding: {
        constexpr std::array names{"slot", "adjust", "range", "origin"};
        return names[field];
    }
    case DeltaPart::FetchRange: {
        constexpr std::array names{"guest-base", "bytes", "semantic", "stride"};
        return names[field];
    }
    case DeltaPart::FetchResource: {
        constexpr std::array names{"ordinal", "dest-vgpr", "elements", "sgpr-and-offset",
                                   "instance-offset-and-data", "data-and-number-format"};
        return names[field];
    }
    case DeltaPart::ObjectSharp:
    case DeltaPart::FetchSharp:
    case DeltaPart::ObjectWords: return "dword";
    default: return "-";
    }
}

void ReportPlacementDelta(const char* event, const char* why, const PlacementDeltaSample& old,
                          const PlacementDeltaSample& next, const RtShadow::ReflectionDrawToken& token,
                          bool joined, PlacementDeltaDifference difference = {}) {
    const auto u = [](u64 n) { return static_cast<unsigned long long>(n); };
    const auto& prior = token.placement_delta;
    std::printf("Reflection placement delta target=fireplace event=%s why=%s generation=%llu "
                "old_generation=%llu old_allocation=%llu old_frame=%llu old_pass=%llu "
                "old_cookie=%llu old_key=%016llx "
                "frame=%llu pass=%llu cookie=%llu key=%016llx allocation=%llu "
                "prior_pass=%llu prior_cookie=%llu prior_key=%016llx prior_revision=%llu "
                "joined=%u canonical=%u/%u object0_origin=%u/%u object3_origin=%u/%u\n",
                event, why, u(next.generation), u(old.generation), u(old.allocation),
                u(old.frame), u(old.pass), u(old.cookie), u(old.key),
                u(next.frame), u(next.pass), u(next.cookie), u(next.key), u(token.allocation),
                u(prior.pass), u(prior.cookie), u(prior.key), u(prior.revision), u32(joined),
                u32(old.canonical), u32(next.canonical), old.origin0, next.origin0,
                old.origin3, next.origin3);
    if (difference.kind == DeltaKind::Same || difference.kind == DeltaKind::Mode ||
        difference.step >= old.used || difference.step >= next.used) {
        return;
    }
    const auto& a = old.steps[difference.step];
    const auto& b = next.steps[difference.step];
    const bool field = difference.kind == DeltaKind::Field;
    std::printf("Reflection placement delta first step=%u part=%s/%s ordinal=%u/%u field=%s[%u] "
                "value=%016llx/%016llx guest=%016llx/%016llx bytes=%llu/%llu "
                "in=%016llx/%016llx out=%016llx/%016llx\n",
                difference.step, delta_parts[u32(a.part)], delta_parts[u32(b.part)], a.ordinal, b.ordinal,
                field ? PlacementDeltaField(a.part, difference.field) : "-", difference.field,
                u(field ? old.Word(a, difference.field) : 0),
                u(field ? next.Word(b, difference.field) : 0),
                u(a.address), u(b.address), u(a.bytes), u(b.bytes), u(a.before), u(b.before), u(a.after), u(b.after));
}

void SubmitPlacementDelta(const ReflectionNativeProbe::Draw* draw, const ReflectionFirstHit::Stamp& stamp,
                          const RtShadow::ReflectionDrawToken& token, bool joined) {
    auto* trace = FireplacePlacementDelta(draw);
    if (!trace || !token.placement_delta.enabled) {
        return;
    }
    auto& next = trace->Pending();
    const auto& old = trace->Prior();
    const auto& prior = token.placement_delta;
    if (next.generation != stamp.generation || next.frame != stamp.frame || next.pass != stamp.pass ||
        next.key != token.placement) {
        if (prior.revision) {
            trace->done = true;
            ReportPlacementDelta("unavailable", "submission-stamp-or-key-mismatch", old, next, token, joined);
        }
        return;
    }
    next.cookie = token.cookie;
    next.allocation = token.allocation;
    const bool same_allocation = old.cookie && old.generation == next.generation &&
                                 old.allocation == next.allocation;
    const bool adjacent = same_allocation && old.frame + 1 == next.frame && old.pass + 1 == next.pass;
    if (joined && adjacent && old.canonical && next.canonical) {
        const bool active_words = ExactReflectionActiveWordsOn();
        const bool word22 = (active_words || ExactReflectionWord22On()) && old.raw_word22 != next.raw_word22;
        const bool word23 = active_words && old.raw_word23 != next.raw_word23;
        const u8 changed = u8(word22) | (u8(word23) << 1);
        if (changed & ~trace->raw_words_reported) {
            trace->raw_words_reported |= changed;
            const auto u = [](u64 n) { return static_cast<unsigned long long>(n); };
            if (active_words) {
                std::printf("Reflection exact active words target=fireplace generation=%llu allocation=%llu "
                            "old_frame=%llu old_pass=%llu old_cookie=%llu frame=%llu pass=%llu cookie=%llu "
                            "raw22=%08x/%08x raw23=%08x/%08x key=%016llx/%016llx prior_revision=%llu\n",
                            u(next.generation), u(next.allocation), u(old.frame), u(old.pass), u(old.cookie),
                            u(next.frame), u(next.pass), u(next.cookie), old.raw_word22, next.raw_word22,
                            old.raw_word23, next.raw_word23, u(old.key), u(next.key), u(prior.revision));
            } else {
                std::printf("Reflection exact word22 target=fireplace generation=%llu allocation=%llu "
                            "old_frame=%llu old_pass=%llu old_cookie=%llu frame=%llu pass=%llu cookie=%llu "
                            "raw=%08x/%08x key=%016llx/%016llx prior_revision=%llu\n",
                            u(next.generation), u(next.allocation), u(old.frame), u(old.pass), u(old.cookie),
                            u(next.frame), u(next.pass), u(next.cookie), old.raw_word22, next.raw_word22,
                            u(old.key), u(next.key), u(prior.revision));
            }
        }
    }
    if (prior.revision) {
        trace->done = true;
        if (!prior.same_identity || !adjacent || old.key != prior.key || old.cookie != prior.cookie ||
            old.pass != prior.pass || !joined) {
            const char* why = !prior.same_identity ? "different-identity" :
                !adjacent ? "nonconsecutive-or-missing" :
                !joined ? "submission-refused" : "prior-identity-unjoined";
            ReportPlacementDelta("unavailable", why, old, next, token, joined);
            return;
        }
        const auto difference = FirstPlacementDifference(old, next);
        constexpr std::array reasons{"final-key-unaccounted", "exact-route-changed", "tuple-field",
            "component-shape", "payload-range", "payload-hash", "checkpoint-coverage", "snapshot-cap"};
        const bool explained = difference.kind != DeltaKind::Same &&
                               difference.kind != DeltaKind::Coverage && difference.kind != DeltaKind::Overflow;
        ReportPlacementDelta(explained ? "changed" : "unavailable", reasons[u32(difference.kind)],
                             old, next, token, joined, difference);
    } else if (joined && adjacent && !trace->baseline && old.key == next.key && next.canonical &&
               FirstPlacementDifference(old, next).kind == DeltaKind::Same) {
        trace->baseline = true;
        ReportPlacementDelta("unchanged", "consecutive-confirmed", old, next, token, joined);
    }
    if (joined) {
        trace->current ^= 1;
    }
}

u64 HashExactObject(const ReflectionNativeProbe::ExactObjects& exact, u32 ordinal, u64 hash,
                    PlacementDeltaSample* delta) {
    const auto& note = ordinal == 0 ? exact.binding0 : exact.binding3;
    const std::array<u64, 4> effective{note.slot, note.adjust, note.range, u32(note.origin)};
    auto payload = ordinal == 0
        ? std::span<const u8>{exact.object0}.first(ReflectionNativeProbe::ExactObjects::UsedObject0Bytes)
        : std::span<const u8>{exact.object3};
    std::array<u8, ReflectionNativeProbe::ExactObjects::UsedObject0Bytes> normalized;
    const bool active_words = ordinal == 0 && ExactReflectionActiveWordsOn();
    if (ordinal == 0 && (active_words || ExactReflectionWord22On())) {
        constexpr u32 word22 = 22 * sizeof(u32);
        constexpr u32 word23 = 23 * sizeof(u32);
        static_assert(word23 + sizeof(u32) == normalized.size());
        if (delta) {
            std::memcpy(&delta->raw_word22, payload.data() + word22, sizeof(u32));
            if (active_words) {
                std::memcpy(&delta->raw_word23, payload.data() + word23, sizeof(u32));
            }
        }
        if (active_words) {
            // The pinned VS stages read only words 12Ã¢â‚¬â€œ15 and 20 of ordinal0 with adjust=0.
            // Keep their slots fixed in the diagnostic key and keep the full actual bind check.
            normalized.fill(0);
            constexpr u32 first = 12 * sizeof(u32), palette = 20 * sizeof(u32);
            std::memcpy(normalized.data() + first, payload.data() + first, 4 * sizeof(u32));
            std::memcpy(normalized.data() + palette, payload.data() + palette, sizeof(u32));
        } else {
            std::ranges::copy(payload, normalized.begin());
            std::fill_n(normalized.begin() + word22, sizeof(u32), u8{0});
        }
        payload = normalized;
    }
    hash = XXH3_64bits_withSeed(effective.data(), sizeof(effective), hash);
    if (delta) {
        delta->Tuple(DeltaPart::ObjectBinding, u16(ordinal), effective, hash);
    }
    hash = XXH3_64bits_withSeed(payload.data(), payload.size(), hash);
    if (delta) {
        delta->Add(DeltaPart::ObjectWords, u16(ordinal), hash, 0, payload.size(), payload.data(), sizeof(u32));
    }
    return hash;
}

bool ReflectProbeHide(u64 vs, u64 ps, bool indirect, bool indexed, u32 index_count, u32 first_index,
                      bool record = true);

bool ExactReflectionStages(const GraphicsPipeline& pipeline, const ReflectionNativeProbe::Draw& draw) {
    constexpr std::array<u64, ReflectionNativeProbe::WitnessCount> vs_ids{
        0x000009db8f183ea1ull, ReflectionDiscard::Fireplace.vertex_stage, ReflectionDiscard::Wall.vertex_stage};
    constexpr std::array<u64, ReflectionNativeProbe::WitnessCount> ps_ids{
        0x00000ca7073f7ac4ull, ReflectionDiscard::Fireplace.fragment_stage, ReflectionDiscard::Wall.fragment_stage};
    const u32 role = ReflectionNativeProbe::Match(draw.key);
    const auto stages = pipeline.GetStages();
    const auto& key = pipeline.GetGraphicsKey();
    constexpr u32 vs = u32(Shader::SwStage::Vertex), ps = u32(Shader::SwStage::Fragment);
    return role != ReflectionNativeProbe::NoWitness && !key.foliage_mask &&
        stages[vs] && stages[ps] && stages[vs]->pgm_hash == draw.key.vs && stages[ps]->pgm_hash == draw.key.ps &&
        key.stage_hashes[vs] == vs_ids[role] && key.stage_hashes[ps] == ps_ids[role];
}

struct ReflectionDiscardGate {
    const Rasterizer* owner{};
    const GraphicsPipeline* pipeline{};
    ReflectionFirstHit::Stamp stamp;
    u64 tick{}, stage{};
    bool shared_discard{}, alpha{};
};

std::array<ReflectionDiscardGate, ReflectionNativeProbe::WitnessCount>& ReflectionDiscardGates() {
    // EffectsCaptureDraw and EffectsAfterDraw are in the same direct DrawRecord call.
    static thread_local std::array<ReflectionDiscardGate, ReflectionNativeProbe::WitnessCount> gates{};
    return gates;
}

std::array<std::atomic_bool, ReflectionNativeProbe::WitnessCount> reflection_discard_reported{};

void RememberReflectionDiscard(const Rasterizer* owner, const GraphicsPipeline& pipeline,
                               const ReflectionFirstHit::Stamp& stamp, const RtShadow::Draw& draw,
                               u32 first, u64 tick, bool shared_discard) {
    const auto role = ReflectionNativeProbe::Match({draw.shader, draw.pixel_shader, draw.index_count, first});
    if (role == ReflectionNativeProbe::NoWitness || reflection_discard_reported[role].load()) return;
    auto& gate = ReflectionDiscardGates()[role];
    gate = {};
    if (!stamp.valid_native || !tick || !draw.camera_pass || !draw.triangles || draw.restart ||
        draw.strip || draw.instances != 1 || draw.first_vertex != 0 || draw.first_instance != 0) {
        return;
    }
    gate = {owner, &pipeline, stamp, tick,
            pipeline.GetGraphicsKey().stage_hashes[u32(Shader::SwStage::Fragment)],
            shared_discard, draw.alpha};
}

void FinishReflectionDiscard(const Rasterizer* owner, const PipelineCache& cache,
                             ReflectionNativeProbe::Key key, const GraphicsPipeline* source,
                             const GraphicsPipeline& raster, const ReflectionFirstHit::Stamp& stamp,
                             u64 tick) {
    const u32 role = ReflectionNativeProbe::Match(key);
    if (role == ReflectionNativeProbe::NoWitness || reflection_discard_reported[role].load()) return;
    const auto gate = std::exchange(ReflectionDiscardGates()[role], {});
    constexpr u32 vs = u32(Shader::SwStage::Vertex), ps = u32(Shader::SwStage::Fragment);
    const auto& graphics_key = raster.GetGraphicsKey();
    if (gate.owner != owner || gate.pipeline != source || source != &raster || gate.stamp != stamp ||
        gate.tick != tick || !gate.stage || gate.stage != graphics_key.stage_hashes[ps] ||
        graphics_key.foliage_mask || !raster.HandleIfReady()) {
        return;
    }

    ReflectionDiscard::Pipeline proof{};
    const bool unchanged = cache.CaptureProofUnchanged();
    const bool joined = unchanged && raster.GetReflectionDiscardProof(&cache, gate.stage, proof) &&
                        proof.fragment.id.guest == key.ps && cache.CaptureProofUnchanged();
    const auto& module = proof.fragment;
    const bool scanned = joined && module.opcodes.valid;
    if (reflection_discard_reported[role].exchange(true)) return;
    const auto u = [](u64 x) { return static_cast<unsigned long long>(x); };
    // Command recording selected the original graphics pipeline. This is a static opcode fact,
    // not a visibility test for an individual GPU fragment invocation.
    std::printf("Reflection fragment discard (t201): role=%s status=%s generation=%llu frame=%llu pass=%llu "
                "tick=%llu vs=%llx ps=%llx count=%u first=%u vs_stage=%llx ps_stage=%llx "
                "pipeline_key=%llx pipeline=%llx shared=%u alpha=%u joined=%u permutation=%lld "
                "module=%llx module_gen=%llu route=%s bytes=%zu xxh3=%016llx warm_raw_discard=%d "
                "scan=%u kill=%u terminate=%u demote=%u\n",
                ReflectionNativeProbe::labels[role],
                !unchanged ? "hot-replacement" : !joined ? "module-unjoined" :
                !scanned ? "scan-unavailable" : "recorded",
                u(stamp.generation), u(stamp.frame), u(stamp.pass), u(tick), u(key.vs), u(key.ps),
                key.count, key.first, u(graphics_key.stage_hashes[vs]), u(gate.stage),
                u(std::hash<GraphicsPipelineKey>{}(graphics_key)), u(std::bit_cast<u64>(raster.HandleIfReady())),
                u32(gate.shared_discard), u32(gate.alpha), u32(joined),
                joined ? static_cast<long long>(module.permutation) : -1ll,
                u(joined ? module.id.handle : 0), u(joined ? module.id.generation : 0),
                joined ? ReflectionDiscard::Name(module.route) : "unknown", joined ? module.bytes : 0,
                u(scanned ? module.effective_xxh3 : 0), joined && module.warm_raw_discard ? *module.warm_raw_discard : -1,
                u32(scanned), scanned ? module.opcodes.kill : 0, scanned ? module.opcodes.terminate : 0,
                scanned ? module.opcodes.demote : 0);
}

void TraceExactReflectionObjects(const ReflectionNativeProbe::Draw& draw, const char* status) {
    using namespace ReflectionNativeProbe;
    static std::array<u32, WitnessCount> rows{};
    static std::array<const char*, WitnessCount> last{};
    const u32 role = Match(draw.key);
    if (role == NoWitness || rows[role] == 12 || last[role] == status) {
        return;
    }
    ++rows[role];
    last[role] = status;
    const auto& exact = *draw.exact;
    const auto u = [](u64 n) { return static_cast<unsigned long long>(n); };
    std::printf("Reflection exact target=%s status=%s generation=%llu frame=%llu pass=%llu "
                "object0=%u/%u/%llu/%u/%u object3=%u/%u/%llu/%u/%u\n",
                labels[role], status, u(draw.stamp.generation), u(draw.stamp.frame), u(draw.stamp.pass),
                u32(exact.binding0.complete), exact.binding0.slot, u(exact.binding0.range),
                exact.binding0.adjust, u32(exact.binding0.origin),
                u32(exact.binding3.complete), exact.binding3.slot, u(exact.binding3.range),
                exact.binding3.adjust, u32(exact.binding3.origin));
}
} // namespace

bool Rasterizer::ReflectionCapture(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                                   const RtShadow::Draw& draw, u32 first,
                                   RtShadow::ReflectionDrawToken& token) {

    auto* retire = ReflectionFirstRetire::Current(this);
    if (retire) retire->capture = "preflight-refused";
    auto& probe = *reflection_probe;
    const auto& stamp = *probe.stamp;
    const auto& vs = pipeline.GetStage(Shader::SwStage::Vertex);
    const auto* ps = pipeline.GetStages()[u32(Shader::SwStage::Fragment)];
    const auto& fetch = pipeline.GetFetchShader();
    const bool exact_mirror = draw.shader == 0x9da6aacb && draw.pixel_shader == 0xca7226ec &&
                              draw.index_count == 24 && first == 2440816;
    const auto target = JoinCount(draw.index_count) && ReflectionJoinTraceOn()
        ? JoinTarget(draw.shader, draw.pixel_shader, draw.index_count, first)
        : ReflectionJoinTarget::None;
    const auto trace = [&](std::string_view stage, std::string_view gate, u64 a = 0, u64 b = 0) {
        TraceReflectionJoin(target, stamp.frame, probe.last_request, draw.shader, draw.pixel_shader,
                            draw.index_count, first, stage, gate, regs,
                            pipeline.GetGraphicsKey().mrt_mask, &draw, a, b);
    };
    const auto refused = [&](bool test, std::string_view gate) {
        if (test && retire) retire->capture = gate;
        if (test && target != ReflectionJoinTarget::None) {
            trace("draw", gate);
        }
        return test;
    };
    if (ps && JoinCount(draw.index_count) && ReflectionDiscard::On()) {
        RememberReflectionDiscard(this, pipeline, stamp, draw, first, scheduler.CurrentTick(), ps->has_discard);
    }
    const auto* placed = draw.palette_placed && draw.reflection_native && ReflectionFirstHit::PlacedOn()
        ? ReflectionNativeProbe::PlacedBinding(*draw.reflection_native) : nullptr;
    // Other vertex programs stay in the direct census, except the independently fingerprinted
    // wall whose native direct shader is still to be identified.
    if (refused(draw.shader != 0x9da6aacb && draw.index_count != 42441, "vertex-program") ||
        refused(!fetch, "fetch-missing") || refused(!ps, "fragment-missing") ||
        refused(!vs.images.empty(), "vertex-samples-image") || refused(!draw.camera_pass, "non-camera") ||
        refused(!draw.solid, "non-solid") || refused(draw.glass, "glass-capture") ||
        refused(draw.glass_entry && !exact_mirror, "glass-registry") || refused(draw.alpha, "discard") ||
        refused(draw.skinned, "skinned") || refused(draw.skeleton_bones, "skeleton-bones") ||
        refused(draw.palette_placed && !placed, "gpu-placed-palette") || refused(!draw.positions, "positions-missing") ||
        refused(!draw.constants, "camera-constants-missing") || refused(!draw.indices, "indices-missing") ||
        refused(draw.indices % draw.index_size, "indices-unaligned") ||
        refused(draw.instances != 1, "instance-count") || refused(draw.first_instance != 0, "first-instance") ||
        refused(draw.restart, "primitive-restart") || refused(draw.strip, "triangle-strip") ||
        refused(!draw.triangles, "non-triangle") || refused(draw.index_count < 3, "index-count-short") ||
        refused(draw.index_count % 3, "index-count-not-triangles") ||
        refused(draw.index_count > 200000, "index-count-cap") ||
        refused(regs.index_buffer_type.swap_mode != AmdGpu::IndexSwapMode::None, "index-swap") ||
        refused(!regs.depth_control.depth_enable, "depth-test-off") ||
        refused(regs.depth_control.depth_func == AmdGpu::CompareFunc::Always, "depth-test-always") ||
        refused(regs.color_target_mask.GetMask(0) != 0xf, "cb0-write-mask") ||
        refused(!(pipeline.GetGraphicsKey().mrt_mask & 1u), "cb0-attachment-missing") ||
        refused(std::ranges::any_of(regs.blend_control, [](const auto& control) {
            return control.enable != 0;
        }), "any-blend-register")) {
        ++probe.input_refused;
        return false;
    }
    const auto& vp = regs.viewports[0];
    const auto* constants = draw.constants;
    if (placed && (buffer_cache.IsRegionGpuModified(reinterpret_cast<VAddr>(constants), 864) ||
                   !memory->IsValidGpuMapping(reinterpret_cast<VAddr>(constants), 0) ||
                   memory->ClampRangeSize(reinterpret_cast<VAddr>(constants), 864) != 864)) {
        trace("camera-buffer", "placed-camera-range");
        ++probe.input_refused;
        return false;
    }
    if (refused(!std::equal(stamp.view.begin(), stamp.view.end(), constants + 8), "camera-view") ||
        refused(stamp.projection != std::array{constants[52] * (vp.xscale < 0.f ? -1.f : 1.f),
                                              constants[57] * (vp.yscale < 0.f ? -1.f : 1.f),
                                              constants[62], constants[63]}, "camera-projection")) {
        ++probe.input_refused;
        return false;
    }
    // A frame may read at most 24 MiB of local guest inputs; reserve half for the three
    // witnesses so unrelated draws cannot starve the actual claim. Refusals are counted.
    constexpr u64 Bytes = 24 << 20;
    const bool witness = draw.index_count == 24 || draw.index_count == 18282 || draw.index_count == 42441;
    const u64 limit = witness ? Bytes : Bytes / 2;
    if ((!witness && ++probe.source_attempts > 256) || probe.input_bytes >= limit) {
        trace("source", "input-budget", probe.input_bytes, limit);
        ++probe.input_refused;
        return false;
    }
    const auto readable = [&](VAddr address, u64 bytes, std::string_view stage) {
        const auto reject = [&](bool test, std::string_view gate) {
            if (test && target != ReflectionJoinTarget::None) {
                trace(stage, gate, bytes, probe.input_bytes);
            }
            return test;
        };
        if (reject(!address || !bytes, "empty-range") ||
            reject(bytes > limit - probe.input_bytes, "byte-budget") ||
            reject(!memory->IsValidGpuMapping(address, 0), "unmapped") ||
            reject(memory->ClampRangeSize(address, bytes) != bytes, "short-mapping") ||
            reject(buffer_cache.IsRegionGpuModified(address, bytes), "gpu-modified")) {
            return false;
        }
        probe.input_bytes += bytes;
        return true;
    };
    const auto index_bytes = u64(draw.index_count) * draw.index_size;
    if (!readable(draw.indices, index_bytes, "index-range")) {
        ++probe.input_refused;
        return false;
    }
    const auto bounds = [&]<typename Index>(const Index* p) {
        const auto [lo, hi] = std::ranges::minmax(std::span{p, draw.index_count});
        return std::pair{u32(lo), u32(hi)};
    };
    const auto [lo, hi] = draw.index_size == 2
        ? bounds(reinterpret_cast<const u16*>(draw.indices))
        : bounds(reinterpret_cast<const u32*>(draw.indices));
    const std::array<u64, 6> binding{draw.shader, draw.positions, draw.indices, first,
                                     draw.first_vertex, draw.index_size};
    u64 hash = XXH3_64bits(binding.data(), sizeof(binding));
    auto* delta_trace = placed ? FireplacePlacementDelta(draw.reflection_native) : nullptr;
    auto* delta = delta_trace ? &delta_trace->Pending() : nullptr;
    if (delta) {
        delta->Begin(stamp);
        delta->Tuple(DeltaPart::Binding, 0, binding, hash);
    }

    namespace Object3 = ReflectionOrdinal3;
    auto* sample = placed && retire && Object3::On() &&
        Object3::state.working.sequence == retire->sequence &&
        Object3::Active(this, stamp.generation, retire->sequence) ? &Object3::state.working : nullptr;
    if (sample) {
        sample->frame = stamp.frame;
        sample->pass = stamp.pass;
        sample->generation = stamp.generation;
        sample->pose = {.depth_uid = stamp.depth_uid, .cb0_uid = stamp.cb0_uid,
            .depth_image = std::bit_cast<u64>(stamp.depth_image), .cb0_image = std::bit_cast<u64>(stamp.cb0_image),
            .view = stamp.view, .projection = stamp.projection, .jitter = stamp.jitter, .extent = stamp.extent,
            .native = stamp.valid_native, .preview = camera_motion->PreviewFrame(),
            .loading = BbEngine::Loading::ScreenUp()};
        sample->palette = {.guest = placed->guest, .bytes = placed->guest_bytes,
            .handle = std::bit_cast<u64>(placed->handle), .offset = placed->descriptor_offset,
            .range = placed->descriptor_range, .slot = placed->slot, .adjust = placed->adjust,
            .flags = u32(placed->range_known) | (u32(placed->gpu_dirty) << 1) |
                (u32(placed->in_place) << 2) | (u32(placed->writable) << 3)};
        sample->palette_current = placed->buffer->Handle() == placed->handle;
        // Independent of the canonical/fallback seed. The tuple also carries the actual index span.
        sample->geometry = hash;
    }
    auto* native = placed && draw.reflection_native->exact ? draw.reflection_native : nullptr;
    ReflectionNativeProbe::ExactObjects* exact = nullptr;
    if (native) {
        const auto matches = [&](u32 ordinal, const auto& note, const auto& owned) {
            if (!note.complete || ordinal >= vs.buffers.size() ||
                !(vs.buffers[ordinal].GetSharp(vs) == note.sharp) ||
                !memory->IsValidGpuMapping(note.address, owned.size()) ||
                !memory->IsValidMapping(note.address, owned.size()) ||
                buffer_cache.IsRegionGpuModified(note.address, owned.size())) {
                return false;
            }
            return std::memcmp(reinterpret_cast<const void*>(note.address), owned.data(), owned.size()) == 0;
        };
        auto& objects = *native->exact;
        if (delta) {
            delta->origin0 = u32(objects.binding0.origin);
            delta->origin3 = u32(objects.binding3.origin);
        }
        // Without a foliage attachment the direct draw uses this pipeline. Check the
        // actual recorded draw again before the existing placed submission observes it.
        const auto match_object3 = [&] {
            if (sample) {
                auto& chosen = Object3::state.chosen;
                if (chosen.active && chosen.draw.sequence == sample->sequence) {
                    chosen.classify_seen = true;
                    chosen.classify_complete = Object3::writer.Cutoff(Object3::Classified);
                    chosen.capture_tick = scheduler.CurrentTick();
                }
            }
            return matches(3, objects.binding3, objects.object3);
        };
        const char* status = foliage_mask || !pipeline.HandleIfReady() ||
                                     !ExactReflectionStages(pipeline, *native) ||
                                     regs.clipper_control.user_clip_plane_enable
            ? "pipeline-refused" : !matches(0, objects.binding0, objects.object0)
            ? "object0-refused" : !match_object3()
            ? "object3-refused" : "objects-qualified";
        if (sample) {
            sample->geometry = XXH3_64bits_withSeed(reinterpret_cast<const void*>(draw.indices),
                                                  index_bytes, sample->geometry);
            sample->object0_complete = objects.binding0.complete;
            sample->object3_complete = objects.binding3.complete;
            sample->native_origin0 = u32(objects.binding0.origin);
            sample->native_origin3 = u32(objects.binding3.origin);
            sample->active_words = ExactReflectionActiveWordsOn();
            if (objects.binding0.complete) {
                sample->object0_digest = XXH3_64bits(objects.object0.data(), objects.object0.size());
            }
            if (objects.binding3.complete) sample->bytes = objects.object3;

            auto& chosen = Object3::state.chosen;
            if (chosen.active && chosen.draw.sequence == sample->sequence) {
                chosen.ready_handle = std::bit_cast<u64>(pipeline.HandleIfReady());
                chosen.sharp_same = vs.buffers.size() > 3 &&
                    vs.buffers[3].GetSharp(vs) == objects.binding3.sharp;
                const auto address = sample->object3.guest;
                const bool gpu_mapped = address && memory->IsValidGpuMapping(address, Object3::Bytes);
                const bool mapped = gpu_mapped && memory->IsValidMapping(address, Object3::Bytes) &&
                    memory->ClampRangeSize(address, Object3::Bytes) == Object3::Bytes;
                const bool gpu_clean = mapped && !buffer_cache.IsRegionGpuModified(address, Object3::Bytes);
                const bool cpu_clean = mapped && !buffer_cache.IsOrdinal3CpuModified(address, Object3::Bytes);
                chosen.guest_protections = u32(chosen.sharp_same) | (u32(gpu_mapped) << 1) |
                    (u32(mapped) << 2) | (u32(gpu_clean) << 3) | (u32(cpu_clean) << 4);
                // Require a live engine-owned seal for an independent guest snapshot.
                // Dirty/mapping checks alone cannot establish stable guest backing.
                u32 seal{}, seal_generation{};
                u64 seal_base{};
                if (chosen.guest_protections == 0x1f && chosen.expected_descriptor && !chosen.competing &&
                    BbEngine::GxObjects::SealedFind(address, Object3::Bytes, &seal, &seal_generation, &seal_base) &&
                    BbEngine::GxObjects::SealedValid(seal, seal_generation)) {
                    Object3::Payload owned;
                    std::memcpy(owned.data(), reinterpret_cast<const void*>(address), owned.size());
                    if (BbEngine::GxObjects::SealedValid(seal, seal_generation) &&
                        !buffer_cache.IsOrdinal3CpuModified(address, owned.size()) &&
                        !buffer_cache.IsRegionGpuModified(address, owned.size())) {
                        chosen.guest_protections |= 1u << 5;
                        chosen.guest = owned;
                        chosen.guest_available = true;
                    }
                }
                const auto descriptor = chosen.draw.object3;
                chosen.draw = *sample;
                chosen.draw.object3 = descriptor;
            }
        }
        TraceExactReflectionObjects(*native, status);
        if (retire) retire->exact = status;
        if (std::string_view{status} == "objects-qualified") {
            exact = &objects;
            constexpr std::string_view domain = "exact placed reflection t184";
            hash = XXH3_64bits_withSeed(domain.data(), domain.size(), hash);
            if (delta) {
                delta->canonical = true;
                delta->Add(DeltaPart::Mode, 0, hash, 0, domain.size(), domain.data(), 1);
            }
        }
    }
    auto* placement_sample = placed
        ? StartPlacementSample(ReflectionNativeProbe::Match(draw.reflection_native->key), stamp) : nullptr;
    if (placement_sample) {
        placement_sample->descriptors[0] = hash;
        placement_sample->Add(PlacementPart::Binding, 0, sizeof(binding), hash);
    }
    auto* input_trace = placed && OrdinalZeroFor(*draw.reflection_native)
        ? ReflectionInputsFor(ReflectionNativeProbe::Match(draw.reflection_native->key)) : nullptr;
    if (input_trace) {
        auto& sample = input_trace->current;
        sample.binding = binding;
        sample.generation = stamp.generation;
        sample.frame = stamp.frame;
        sample.pass = stamp.pass;
        sample.hashed = 0;
        sample.used = 0;
        sample.unique = 0;
        sample.overflow = false;
        sample.fetch_unsupported = false;
        sample.Add({.fields = {lo, hi, u32(regs.index_buffer_type.index_type),
                               u32(regs.index_buffer_type.swap_mode)},
                    .guest = draw.indices, .bytes = index_bytes, .part = ReflectionInputPart::Index},
                   true, input_trace->remaining);
    }
    hash = XXH3_64bits_withSeed(reinterpret_cast<const void*>(draw.indices), index_bytes, hash);
    if (delta) {
        delta->Add(DeltaPart::Index, 0, hash, draw.indices, index_bytes);
    }
    if (placement_sample) {
        placement_sample->Add(PlacementPart::Index, 0, index_bytes, hash);
    }
    bool camera_seen = false;
    bool palette_seen = false;
    for (const auto& resource : vs.buffers) {
        if (resource.buffer_type == Shader::BufferType::Flatbuf) {
            continue;
        }
        if (placed && resource.buffer_type == Shader::BufferType::ClipPlanes) {
            // LowerUserClipPlanes always declares this host buffer for the hardware vertex stage.
            // A zero user-plane mask specializes away its reads, and BindBuffers binds it null.
            const u32 user_planes = regs.clipper_control.user_clip_plane_enable;
            const auto& output = regs.vs_output_control;
            const u32 distance_exports = (output.vs_out_ccdist0_enable ? 0x0fu : 0u) |
                                         (output.vs_out_ccdist1_enable ? 0xf0u : 0u);
            const u32 guest_clip = output.clip_distance_enable & distance_exports;
            const u32 guest_cull = output.cull_distance_enable & distance_exports;
            const bool stored_clip = vs.stores.GetAny(Shader::IR::Attribute::ClipDistance);
            const bool stored_cull = vs.stores.GetAny(Shader::IR::Attribute::CullDistance);
            const auto stages = pipeline.GetStages();
            const bool plain_vertex = vs.hw_stage == Shader::HwStage::Vertex &&
                                      !stages[u32(Shader::SwStage::Geometry)] &&
                                      !stages[u32(Shader::SwStage::TessellationControl)] &&
                                      !stages[u32(Shader::SwStage::TessellationEval)];
            const bool inert = plain_vertex && !resource.is_written && !user_planes &&
                               !guest_clip && !guest_cull && !stored_clip && !stored_cull;
            // value_a is UCP_ENA. value_b packs guest clip/cull masks and the refusal flags.
            const u32 evidence = guest_clip | (guest_cull << 8) | (u32(stored_clip) << 16) |
                                 (u32(stored_cull) << 17) | (u32(!plain_vertex) << 18) |
                                 (u32(resource.is_written) << 19);
            trace("vertex-buffer", inert ? "inert-clip-planes" : "unsupported-clip-planes",
                  user_planes, evidence);
            if (!inert) {
                ++probe.input_refused;
                return false;
            }
            continue;
        }
        if (resource.IsSpecial() || resource.is_written) {
            trace("vertex-buffer", "special-or-written", u32(resource.buffer_type), resource.is_written);
            ++probe.input_refused;
            return false;
        }
        const auto buffer = resource.GetSharp(vs);
        const u32 size = buffer.GetSize();
        const auto input_object = [&](ReflectionInputPart part, bool clean) {
            if (input_trace) {
                const u32 flags = u32(resource.is_uniform) | (u32(resource.is_formatted) << 1) |
                                  (u32(resource.only_const_reads) << 2);
                const auto& fetch = resource.sharp_fetch;
                input_trace->current.Add({.sharp = buffer,
                    .fields = {u32(resource.buffer_type), flags, u32(resource.used_types),
                               u32(resource.post_op), resource.post_op_dw1_mask, fetch.load_mask},
                    .guest = buffer.base_address, .bytes = size,
                    .ordinal = u32(&resource - vs.buffers.data()), .part = part},
                    clean, input_trace->remaining);
            }
        };
        if (!buffer.Valid() || size == 0) {
            input_object(ReflectionInputPart::UnboundObject, false);
            continue;
        }
        if (size == 864 && buffer.base_address == reinterpret_cast<VAddr>(constants)) {
            if (camera_seen || !readable(buffer.base_address, size, "camera-buffer")) {
                if (camera_seen) {
                    trace("camera-buffer", "duplicate");
                }
                ++probe.input_refused;
                return false;
            }
            input_object(ReflectionInputPart::Camera, false);
            camera_seen = true;
            continue;
        }
        if (placed && u32(&resource - vs.buffers.data()) == placed->ordinal) {
            const std::array<u64, 2> binding_key{placed->guest, ReflectionFirstHit::PaletteBytes};
            if (buffer.base_address != placed->guest || size != placed->guest_bytes ||
                buffer.GetStride() != 16 ||
                draw.palette != XXH3_64bits_withSeed(binding_key.data(), sizeof(binding_key), 0)) {
                trace("object-buffer", "placed-palette-provenance");
                ++probe.input_refused;
                return false;
            }
            // Its actual bytes are GPU-owned. Read them only through the effective descriptor.
            hash = XXH3_64bits_withSeed(binding_key.data(), sizeof(binding_key), hash);
            if (delta) {
                delta->Tuple(DeltaPart::PaletteGuest, u16(placed->ordinal), binding_key, hash);
            }
            if (exact) {
                const std::array<u64, 5> effective{placed->slot, placed->adjust, placed->descriptor_offset,
                                                   placed->descriptor_range, std::bit_cast<u64>(placed->handle)};
                hash = XXH3_64bits_withSeed(effective.data(), sizeof(effective), hash);
                if (delta) {
                    delta->Tuple(DeltaPart::PaletteBinding, u16(placed->ordinal), effective, hash);
                }
            }
            if (placement_sample) {
                placement_sample->Descriptor(2, PlacementPart::PaletteDescriptor, u16(placed->ordinal),
                                             binding_key, hash);
            }
            if (input_trace) {
                input_trace->current.Add({.sharp = buffer,
                    .fields = {placed->slot, placed->adjust, placed->descriptor_offset,
                               placed->descriptor_range, placed->effective_bytes,
                               std::bit_cast<u64>(placed->handle)},
                    .guest = placed->guest, .bytes = placed->guest_bytes, .ordinal = placed->ordinal,
                    .part = ReflectionInputPart::Palette}, false, input_trace->remaining);
            }
            palette_seen = true;
            continue;
        }
        if (size > 64 * 1024 || !readable(buffer.base_address, size, "object-buffer")) {
            if (size > 64 * 1024) {
                trace("object-buffer", "size-cap", size, 64 * 1024);
            }
            ++probe.input_refused;
            return false;
        }
        // The actual submitted ordinal0 copy is already covered by t177.
        input_object(ReflectionInputPart::Object, true);
        const u16 ordinal = u16(&resource - vs.buffers.data());
        const bool relocating = exact && (ordinal == 0 || ordinal == 3);
        const std::array<u64, 2> desc{relocating ? 0 : buffer.base_address, size};
        hash = XXH3_64bits_withSeed(desc.data(), sizeof(desc), hash);
        if (delta) {
            delta->Tuple(DeltaPart::ObjectRange, ordinal, desc, hash);
        }
        if (exact) {
            auto sharp = buffer;
            if (relocating) {
                sharp.base_address = 0;
            }
            const u32 flags = u32(resource.is_uniform) | (u32(resource.is_formatted) << 1) |
                              (u32(resource.only_const_reads) << 2);
            const std::array<u64, 6> metadata{ordinal, u32(resource.buffer_type), flags, u32(resource.used_types),
                                              u32(resource.post_op), resource.post_op_dw1_mask};
            hash = XXH3_64bits_withSeed(&sharp, sizeof(sharp), hash);
            if (delta) {
                delta->Tuple(DeltaPart::ObjectSharp, ordinal, std::bit_cast<std::array<u32, 4>>(sharp), hash);
            }
            hash = XXH3_64bits_withSeed(metadata.data(), sizeof(metadata), hash);
            if (delta) {
                delta->Tuple(DeltaPart::ObjectResource, ordinal, metadata, hash);
            }
        }
        if (placed && ordinal == 0) {
            if (auto* proof = OrdinalZeroFor(*draw.reflection_native)) {
                proof->preflight = true;
                proof->exact_sharp = proof->sharp == buffer;
                proof->preflight_address = buffer.base_address;
                proof->preflight_size = size;
                // The original preflight has just verified this clean guest span. This is
                // still only a guest snapshot when no completed owned copy was observed.
                if (size <= OrdinalZeroByteLimit && memory->IsValidMapping(buffer.base_address, size)) {
                    proof->guest_bytes = size;
                    proof->guest_digest = XXH3_64bits(reinterpret_cast<const void*>(buffer.base_address), size);
                }
            }
        }
        if (placement_sample) {
            placement_sample->Descriptor(1, PlacementPart::ObjectDescriptor, ordinal, desc, hash);
        }
        if (relocating) {
            hash = HashExactObject(*exact, ordinal, hash, delta);
            if (retire) retire->objects[ordinal == 0 ? 0 : 1].hashed = true;
        } else {
            hash = XXH3_64bits_withSeed(reinterpret_cast<const void*>(buffer.base_address), size, hash);
            if (delta) {
                delta->Add(DeltaPart::ObjectPayload, ordinal, hash, buffer.base_address, size);
            }
        }
        if (sample && ordinal == 0) sample->ordinary_object0_prefix = hash;
        if (sample && ordinal == 3) sample->ordinary_object3_prefix = hash;
        if (placement_sample) {
            placement_sample->Add(PlacementPart::ObjectContent, ordinal, size, hash);
        }
    }
    bool position_seen = false;
    const s64 first_vertex = s32(draw.first_vertex);
    if (first_vertex + lo < 0) {
        trace("vertex-fetch", "negative-relative-index");
        ++probe.input_refused;
        return false;
    }
    std::array<std::array<u64, 2>, 16> ranges{};
    u32 range_count = 0;
    for (const auto& attribute : fetch->attributes) {
        const auto buffer = attribute.GetSharp(vs);
        const auto stride = buffer.GetStride();
        const u64 start = u64(first_vertex + lo) * stride;
        const u64 end = u64(first_vertex + hi + 1) * stride;
        if (!buffer.Valid() || !stride || end > buffer.GetSize() || start >= end) {
            trace("vertex-fetch", "descriptor-span", attribute.semantic, buffer.GetSize());
            ++probe.input_refused;
            return false;
        }
        position_seen |= attribute.semantic == 0 && buffer.base_address == draw.positions;
        const std::array<u64, 2> range{buffer.base_address + start, end - start};
        const std::array<u64, 4> placement{range[0], range[1], attribute.semantic, stride};
        hash = XXH3_64bits_withSeed(placement.data(), sizeof(placement), hash);
        if (sample) sample->geometry = XXH3_64bits_withSeed(placement.data(), sizeof(placement), sample->geometry);
        const u16 ordinal = u16(&attribute - fetch->attributes.data());
        if (delta) {
            delta->Tuple(DeltaPart::FetchRange, ordinal, placement, hash);
        }
        if (exact) {
            const std::array<u64, 6> metadata{ordinal, attribute.dest_vgpr, attribute.num_elements,
                u64(attribute.sgpr_base) << 32 | attribute.dword_offset,
                u64(attribute.inst_offset) << 32 | attribute.instance_data,
                u64(attribute.data_format) << 32 | attribute.num_format};
            hash = XXH3_64bits_withSeed(&buffer, sizeof(buffer), hash);
            if (delta) {
                delta->Tuple(DeltaPart::FetchSharp, ordinal, std::bit_cast<std::array<u32, 4>>(buffer), hash);
            }
            hash = XXH3_64bits_withSeed(metadata.data(), sizeof(metadata), hash);
            if (delta) {
                delta->Tuple(DeltaPart::FetchResource, ordinal, metadata, hash);
            }
        }
        if (placement_sample) {
            placement_sample->Descriptor(3, PlacementPart::FetchDescriptor, ordinal, placement, hash);
        }
        const auto input_fetch = [&] {
            if (input_trace) {
                input_trace->current.Add({.sharp = buffer,
                    .fields = {attribute.semantic, attribute.dest_vgpr, attribute.num_elements,
                               u64(attribute.sgpr_base) << 32 | attribute.dword_offset,
                               u64(attribute.inst_offset) << 32 | attribute.instance_data,
                               u64(attribute.data_format) << 32 | attribute.num_format},
                    .guest = range[0], .bytes = range[1], .ordinal = ordinal,
                    .part = ReflectionInputPart::Fetch}, true, input_trace->remaining);
            }
        };
        const auto checked = std::span{ranges}.first(range_count);
        if (std::ranges::find(checked, range) != checked.end()) {
            input_fetch();
            continue;
        }
        if (range_count == ranges.size() || !readable(range[0], range[1], "vertex-range")) {
            if (range_count == ranges.size()) {
                trace("vertex-range", "range-count-cap", range_count);
            }
            ++probe.input_refused;
            return false;
        }
        ranges[range_count++] = range;
        input_fetch();
        hash = XXH3_64bits_withSeed(reinterpret_cast<const void*>(range[0]), range[1], hash);
        if (sample) sample->fetch_prefix = hash;
        if (delta) {
            delta->Add(DeltaPart::FetchPayload, ordinal, hash, range[0], range[1]);
        }
        if (placement_sample) {
            placement_sample->Add(PlacementPart::FetchContent, ordinal, range[1], hash);
        }
    }
    if (!camera_seen || !position_seen || (placed && !palette_seen)) {
        trace("source", !camera_seen ? "camera-unbound" :
                        !position_seen ? "position-unbound" : "placed-palette-unbound");
        ++probe.input_refused;
        return false;
    }
    if (input_trace) {
        input_trace->current.FinishFetch(input_trace->remaining, [&](VAddr address, u64 bytes) {
            // The full union has to remain in one clean CPU-readable guest mapping.
            // These diagnostic checks do not consume the original capture's read budget.
            return memory->IsValidGpuMapping(address, bytes) &&
                   memory->IsValidMapping(address, bytes) &&
                   !buffer_cache.IsRegionGpuModified(address, bytes);
        });
    }
    token.placement = hash ? hash : 1;
    if (sample) {
        sample->canonical = exact != nullptr;
        sample->final_key = token.placement;
        auto& chosen = Object3::state.chosen;
        if (chosen.active && chosen.draw.sequence == sample->sequence) {
            chosen.draw.canonical = sample->canonical;
            chosen.draw.final_key = sample->final_key;
            chosen.draw.ordinary_object0_prefix = sample->ordinary_object0_prefix;
            chosen.draw.ordinary_object3_prefix = sample->ordinary_object3_prefix;
            chosen.draw.fetch_prefix = sample->fetch_prefix;
            chosen.draw.geometry = sample->geometry;
        }
    }
    if (delta) {
        delta->key = token.placement;
        token.placement_delta.enabled = true;
    }
    if (exact) {
        exact->placement = true;
    }
    if (placement_sample) {
        placement_sample->final = token.placement;
    }
    if (placed) {
        token.placed = ReflectionFirstHit::PlacedSource(ReflectionNativeProbe::Match(draw.reflection_native->key));
    }
    token.first = first;
    token.min_index = lo;
    token.max_index = hi;
    trace("source", "accepted", lo, hi);
    return true;
}

namespace {
template <typename Integer>
bool ReflectionNumber(std::string_view text, Integer& result) {
    if (text.empty()) {
        return false;
    }
    const auto [end, ec] = std::from_chars(text.data(), text.data() + text.size(), result);
    return ec == std::errc{} && end == text.data() + text.size();
}

std::string_view ReflectionPart(std::string_view& input, char delimiter) {
    const auto split = input.find(delimiter);
    const auto part = input.substr(0, split);
    input = split == std::string_view::npos ? std::string_view{} : input.substr(split + 1);
    return part;
}

bool ParseReflectionRequest(std::string_view spec, ReflectionFirstHit::Request& request) {
    using ReflectionFirstHit::Mode;
    if (spec.size() > 256 || spec.ends_with(';') ||
        !ReflectionNumber(ReflectionPart(spec, ':'), request.serial) || !request.serial ||
        spec.empty()) {
        return false;
    }
    // Authored placed mirror plane independently joined to native depth (R362).
    request.receiver_plane_normal = {-0.8996664f, -0.17364765f, -0.40055816f};
    while (!spec.empty()) {
        if (request.count == ReflectionFirstHit::PixelLimit) {
            return false;
        }
        auto item = ReflectionPart(spec, ';');
        auto& pixel = request.pixels[request.count];
        if (item.ends_with('/') || !ReflectionNumber(ReflectionPart(item, '/'), pixel.x) ||
            !ReflectionNumber(ReflectionPart(item, '/'), pixel.y)) {
            return false;
        }
        const auto mode = ReflectionPart(item, '/');
        if (mode == "d") {
            pixel.mode = Mode::Direct;
        } else if (mode == "s") {
            pixel.mode = Mode::Shaded;
        } else if (mode == "p") {
            pixel.mode = Mode::Planar;
        } else {
            return false;
        }
        if (!item.empty() && (!ReflectionNumber(item, pixel.farther) || pixel.farther > 2)) {
            return false;
        }
        ++request.count;
    }
    return true;
}

void LogReflectionReport(const ReflectionFirstHit::Report& report) {
    using namespace ReflectionFirstHit;
    const auto u = [](u64 n) { return static_cast<unsigned long long>(n); };
    const auto& stamp = report.stamp;
    std::printf("Reflection result request=%llu generation=%llu frame=%llu pass=%llu "
                "depth_uid=%llu cb0_uid=%llu extent=%u/%u jitter=%.8g/%.8g "
                "retained_scene=%llu current_scene=%llu direct_evidence_only=1 placed_mask=%u\n",
                u(report.request.serial), u(stamp.generation), u(stamp.frame), u(stamp.pass),
                u(stamp.depth_uid), u(stamp.cb0_uid), stamp.extent[0], stamp.extent[1],
                double(stamp.jitter[0]), double(stamp.jitter[1]),
                u(report.scenes[0].serial), u(report.scenes[1].serial), report.placed_mask);
    for (u32 row = 0; row < 3; ++row) {
        const auto* v = stamp.view.data() + 4 * row;
        std::printf("Reflection camera request=%llu row=%u view=%.9g/%.9g/%.9g/%.9g projection=%.9g/%.9g/%.9g/%.9g\n",
                    u(report.request.serial), row, double(v[0]), double(v[1]), double(v[2]), double(v[3]),
                    double(stamp.projection[0]), double(stamp.projection[1]),
                    double(stamp.projection[2]), double(stamp.projection[3]));
    }
    const auto hex_digit = [](u8 n) { return "0123456789abcdef"[n]; };
    for (u32 arm = 0; arm < report.scenes.size(); ++arm) {
        const auto& scene = report.scenes[arm];
        for (u32 i = 0; i < scene.members.size(); ++i) {
            const auto& member = scene.members[i];
            const auto& id = member.identity;
            char hash[65]{};
            for (u32 j = 0; j < id.topology_sha256.size(); ++j) {
                hash[2 * j] = hex_digit(id.topology_sha256[j] >> 4);
                hash[2 * j + 1] = hex_digit(id.topology_sha256[j] & 0xf);
            }
            std::printf("Reflection member request=%llu arm=%u scene=%llu id=%u "
                        "surface=%016llx placement=%016llx allocation=%llu revision=%llu "
                        "vs=%08x ps=%08x count=%u first=%u sha256=%s receiver=%u wall=%u current=%u age=%llu "
                        "placed_source=%u palette_build_cookie=%llu palette_draw_cookie=%llu\n",
                        u(report.request.serial), arm, u(scene.serial), i, u(id.surface), u(id.placement),
                        u(id.allocation), u(id.revision), id.vs, id.ps, id.count, id.first, hash,
                        u32(id.receiver), u32(id.wall_witness), u32(member.current),
                        u(stamp.frame - member.last_submit_frame), u32(id.placed), u(member.placement_build_cookie),
                        u(member.placement_cookie));
        }
    }
    const auto log_hit = [&](u32 sample, const char* kind, u32 arm, const Hit& hit) {
        std::printf("Reflection hit request=%llu sample=%u kind=%s arm=%u id=%u geometry=%u "
                    "primitive=%u t=%.9g bary=%.9g/%.9g view_z=%.9g world=%.9g/%.9g/%.9g\n",
                    u(report.request.serial), sample, kind, arm, hit.instance, hit.geometry, hit.primitive,
                    double(hit.distance[0]), double(hit.distance[1]), double(hit.distance[2]),
                    double(hit.distance[3]), double(hit.world[0]), double(hit.world[1]), double(hit.world[2]));
    };
    for (u32 i = 0; i < report.request.count; ++i) {
        const auto& sample = report.samples[i];
        const auto& raw = sample.cb0_bytes;
        const auto& native = sample.native_point_depth;
        const auto& origin = sample.origin_t;
        const auto& dir = sample.direction_depth_delta;
        std::printf("Reflection sample request=%llu sample=%u pixel=%u/%u mode=%u outcome=%u "
                    "cb0=%u/%u/%u/%u native=%.9g/%.9g/%.9g depth=%.9g origin=%.9g/%.9g/%.9g "
                    "receiver_t=%.9g direction=%.9g/%.9g/%.9g depth_delta=%.9g\n",
                    u(report.request.serial), i, sample.x, sample.y, u32(sample.mode), u32(sample.outcome),
                    raw[0], raw[1], raw[2], raw[3], double(native[0]), double(native[1]), double(native[2]),
                    double(native[3]), double(origin[0]), double(origin[1]), double(origin[2]),
                    double(origin[3]), double(dir[0]), double(dir[1]), double(dir[2]), double(dir[3]));
        log_hit(i, "receiver", 0, sample.receiver);
        for (u32 arm = 0; arm < report.scenes.size(); ++arm) {
            log_hit(i, "world", arm, sample.world[arm]);
            if (report.request.pixels[i].farther) {
                log_hit(i, report.request.pixels[i].farther == 2 ? "wall-only" : "farther",
                        arm, sample.farther[arm]);
            }
        }
    }
}
} // namespace

void Rasterizer::ReflectionPollRequest() {
    auto& probe = *reflection_probe;
#if BB_WIND_TWIGS_LIVE
    const u32 generation = BbLiveKnobs::Generation();
    if (probe.knob_generation == generation) {
        return;
    }
    probe.knob_generation = generation;
    const auto value = BbLiveKnobs::Lookup("BB_REFLECTION_FIRST_HIT_REQUEST");
    const char* text = value.Get();
#else
    if (probe.knob_generation == 0) {
        return;
    }
    probe.knob_generation = 0;
    const char* text = std::getenv("BB_REFLECTION_FIRST_HIT_REQUEST");
#endif
    if (!text || !*text) {
        return;
    }
    ReflectionFirstHit::Request request;
    if (!ParseReflectionRequest(text, request)) {
        std::printf("Reflection refused reason=invalid-request-format expected=serial:x/y/s[|p|d][/1|/2];...\n");
        return;
    }
    if (request.serial <= probe.last_request) {
        return;
    }
    probe.last_request = request.serial;
    if (probe.request) {
        std::printf("Reflection refused request=%llu reason=request-already-pending\n",
                    static_cast<unsigned long long>(request.serial));
        return;
    }
    probe.request = request;
    probe.request_frame = rt_shadow->WindowDiagnosticFrame();
}

void Rasterizer::ReflectionBlendedScene() {
    auto& probe = *reflection_probe;
    ReflectionPollRequest();
    const auto view = camera_motion->PassMatrices();
    if (!probe.stamp || probe.tainted || probe.blended_pass == probe.stamp->pass ||
        probe.stamp->frame != rt_shadow->WindowDiagnosticFrame() ||
        probe.stamp->generation != BbEngine::Loading::Generation() || BbEngine::Loading::ScreenUp() ||
        !view.valid || view.view != probe.stamp->view || view.proj != probe.stamp->projection ||
        db_desc.first != probe.stamp->depth || camera_motion->Depth() != probe.stamp->depth ||
        camera_motion->PreviewFrame() || scene_targets->Reduced() || point_shadow->Apart() ||
        (upscaler->Enabled() ? upscaler->Jitter() : std::array<float, 2>{}) != probe.stamp->jitter) {
        return;
    }
    const auto stamp = *probe.stamp;
    probe.blended_pass = stamp.pass;
    rt_shadow->ReflectionFlush(stamp);
    if (probe.request) {
        const auto request = *probe.request;
        probe.request.reset();
        const auto status = probe.pass.Submit(stamp, request);
        rt_shadow->ReflectionAdmissions(request.serial);
        std::printf("Reflection dispatch request=%llu status=%s input_bytes=%llu input_refused=%llu bad_stamp=%llu\n",
                    static_cast<unsigned long long>(request.serial), ReflectionFirstHit::StatusName(status),
                    static_cast<unsigned long long>(probe.input_bytes),
                    static_cast<unsigned long long>(probe.input_refused),
                    static_cast<unsigned long long>(probe.bad_stamp));
    }
}

void Rasterizer::ReflectionFrameEnd() {
    auto& probe = *reflection_probe;
    ReflectionPollRequest();
    const u64 frame = rt_shadow->WindowDiagnosticFrame();
    if (probe.stamp && (probe.stamp->generation != BbEngine::Loading::Generation() ||
        BbEngine::Loading::ScreenUp() || camera_motion->PreviewFrame() ||
        (frame > probe.stamp->frame && frame - probe.stamp->frame > 1))) {
        rt_shadow->ReflectionCloseEpoch();
        probe.stamp.reset();
    }
    if (probe.request && frame >= probe.request_frame && frame - probe.request_frame >= 30) {
        std::printf("Reflection refused request=%llu reason=no-matched-native-blended-pass bad_stamp=%llu\n",
                    static_cast<unsigned long long>(probe.request->serial),
                    static_cast<unsigned long long>(probe.bad_stamp));
        probe.request.reset();
    }
    for (u32 slot = 0; slot < 2; ++slot) {
        ReflectionFirstHit::Report result;
        const auto status = probe.pass.Poll(result);
        if (status == ReflectionFirstHit::Status::Pending) {
            break;
        }
        if (status == ReflectionFirstHit::Status::Recorded) {
            LogReflectionReport(result);
        } else {
            std::printf("Reflection readback refused reason=%s\n", ReflectionFirstHit::StatusName(status));
        }
    }
}

#ifdef BB_TEST_BOTTLE_CUT_SOURCE
std::optional<BottleCold::Closed> BottleColdSource177::CloseBeforeDisplay(
    const Rasterizer& owner, Scheduler& scheduler, const SceneTargets& targets,
    const RtShadow& rt, const ObjectMotion& objects, const CameraMotion& camera,
    const TemporalUpscaler& upscaler, VideoCore::TextureCache& textures) {
    const u32 request = BottleSource::Run();
    if (!request) return {};
    const auto frame = BottleCutFrame(&owner, request, scheduler, targets, rt, objects);
    BottleCold::Image depth{}, color{};
    if (BottleCutNativeScope(targets)) {
        const auto depth_id = camera.Depth();
        const auto color_id = upscaler.SceneColor();
        depth = BottleCutImage(targets, depth_id, textures.TryGetImage(depth_id, 0), true);
        const auto* current = textures.TryGetImage(color_id, 0);
        if (current && current->info.pixel_format == vk::Format::eR16G16B16A16Sfloat) {
            color = BottleCutImage(targets, color_id, current, false);
        }
    }
    // The upscaler has finished its jittered draws here. Compare the current pass pose;
    // each ordinary opportunity retains the actual jitter sampled at its own branch.
    bool read_backing_current = false;
#if defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
    if (const auto* read = Current().ReadFor(frame); read && depth && color) {
        const auto c = targets.InspectSewerProxy(upscaler.SceneColor(), color.uid, read->color.view);
        const auto d = targets.InspectSewerProxy(camera.Depth(), depth.uid, read->depth.view);
        // Merge may invalidate logical proxy content. Only the actual retained image/view
        // ownership needs to survive unchanged for this earlier raw consumer observation.
        read_backing_current = read->tick <= scheduler.CurrentTick() &&
            c.target.image == read->color.image && c.target.view == read->color.view &&
            d.target.image == read->depth.image && d.target.view == read->depth.view &&
            c.incarnation == read->color.incarnation && d.incarnation == read->depth.incarnation &&
            c.extent == vk::Extent3D{1920, 1080, 1} && d.extent == c.extent;
    }
#endif
    auto closed = Current().Close(frame, depth, color, BottleCutCamera(camera, camera.Jitter()),
                                  true, read_backing_current);
    if (closed) Report(*closed);
    return closed;
}
#endif

void Rasterizer::EffectsAfterTargets(const GraphicsPipeline* pipeline) {
    const auto& key = pipeline->GetGraphicsKey();
    const bool gbuffer = std::popcount(key.mrt_mask) >= 5 && db_desc.first;
    if (rt_shadow->ActiveLampPane()) {
        LampPaneTargets(pipeline, gbuffer);
    }
    if (gbuffer) {
        if (ReflectionFirstHit::On() && !reflection_probe) {
            if (instance.IsRayQuerySupported()) {
                reflection_probe = std::make_unique<ReflectionProbe>(instance, scheduler,
                                                                    texture_cache, runtime);
                rt_shadow->ReflectionAttach(&reflection_probe->pass);
                std::printf("Reflection first hit armed (native direct draws, no colour)\n");
            } else {
                static const bool reported = [] {
                    std::printf("Reflection first hit refused reason=ray-query-unavailable\n");
                    return true;
                }();
                (void)reported;
            }
        }
        depth_of_field->Reset();
        if (heat_haze) { // bbport (r97_heat-haze): the lamps of the last G-buffer pass only
            heat_haze->ClearLights();
        }
        if (glass_glint) { // bbport (r86b_glass-visible): the same rule
            glass_glint->ClearLights();
        }
        if (glass_tri_read) { // bbport (r86m_glint-pane-from-triangle, TOOL): this pass's targets, for the pixel readback
            for (u32 cb = 0; cb < 5; ++cb) {
                glass_tri_gb[cb] = ((key.mrt_mask >> cb) & 1u) != 0 ? cb_descs[cb].first : VideoCore::ImageId{};
            }
            glass_tri_depth = db_desc.first;
        }
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        const auto bottle_master = BottleCaustic::ReadCutMaster();
        if (bottle_master.on) {
#else
        if (BottleCaustic::On()) {
#endif
            if (!bottle_caustic) {
                bottle_caustic = std::make_unique<BottleCaustic::Pass>(
                    instance, scheduler, texture_cache, runtime, *scene_targets,
                    *camera_motion, *point_shadow, *rt_shadow);
            }
            bottle_caustic->OnTargets(db_desc.first, cb_descs[0].first, cb_descs[2].first);
        }
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        if (bottle_master && gbuffer_draw && camera_motion->Depth() == db_desc.first &&
            BottleCutNativeScope(*scene_targets)) {
            const auto* depth = texture_cache.TryGetImage(db_desc.first, 0);
            if (const auto depth_key = BottleCutImage(*scene_targets, db_desc.first, depth, true)) {
                const auto* normal = (key.mrt_mask & 1u) ? texture_cache.TryGetImage(cb_descs[0].first, 0) : nullptr;
                const auto* albedo = (key.mrt_mask & 4u) ? texture_cache.TryGetImage(cb_descs[2].first, 0) : nullptr;
                BottleCold::Current().GBuffer(
                    BottleCutFrame(this, BottleSource::Run(), scheduler, *scene_targets, *rt_shadow, *object_motion),
                    {depth_key, BottleCutImage(*scene_targets, cb_descs[0].first, normal, false),
                                BottleCutImage(*scene_targets, cb_descs[2].first, albedo, false)},
                    scheduler.CurrentTick(), bottle_master);
            }
        }
#endif
        if (caustics) { // bbport (r107_caustics): cb 1 holds the gloss; arms its pass
            caustics->OnGBufferDraw(db_desc.first, cb_descs[1].first, cb_descs[2].first,
                                    cb_descs[3].first); // r107b: albedo, light sets
        }
        if (drawn_look_wanted) { // bbport (r45_drawn-look): cb 0 holds the world normals
            drawn_look->OnGBufferDraw(db_desc.first, cb_descs[0].first);
        }
        if (foliage_glow) { // bbport (r131a_foliage-translucency): cb 0 holds the world normals, cb 2 the albedo; arms its pass
            foliage_glow->OnGBufferDraw(db_desc.first, cb_descs[0].first, cb_descs[2].first);
        }
        if (ambient_particles) { // bbport (r98c_particles-visible): the last pass's lamps only
            ambient_particles->ClearLamps();
        }
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
    if (reflection_probe) {
        ReflectionBlendedScene();
    }
    if (surface_probe_on) {
        SurfaceProbeBlendedScene(); // bbport (r64b_surface-probe-more): its readback, log only
        SurfaceProbeRect(false); // bbport (t70b_mirror-probe, TOOL): BB_REFLECT_PROBE_RECT's readback, log only
    }
    if (effects_wanted) {
        ssgi->OnOpaqueScene(cb_descs[0].first, db_desc.first, upscaler->Jitter());
    }
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    using Branch = BottleSource::Guard::Branch;
    const auto bottle_master = bottle_caustic ? BottleCaustic::ReadCutMaster() : BottleSource::MasterRead{};
    std::optional<BottleSource::Opportunity> bottle_opportunity;
#if defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    std::shared_ptr<BottleRawApply180::Receipt> raw_phase;
#endif
    if (const u32 request = BottleSource::Run(); request && BottleCutNativeScope(*scene_targets)) {
        const auto color_id = cb_descs[0].first;
        const auto depth_id = db_desc.first;
        const auto* color = texture_cache.TryGetImage(color_id, 0);
        const auto* depth = texture_cache.TryGetImage(depth_id, 0);
        const auto color_key = upscaler->SceneColor() == color_id && color &&
                               color->info.pixel_format == vk::Format::eR16G16B16A16Sfloat
            ? BottleCutImage(*scene_targets, color_id, color, false) : BottleCold::Image{};
        const auto depth_key = camera_motion->Depth() == depth_id
            ? BottleCutImage(*scene_targets, depth_id, depth, true) : BottleCold::Image{};
        const auto camera = BottleCutCamera(*camera_motion, upscaler->Jitter());
        const auto bindings = color_key && depth_key
            ? BottleCutBoundAttachments(scheduler, *scene_targets, color_id, *color, depth_id, *depth)
            : BottleCutBindings{};
        const auto branch = !bottle_caustic ? Branch::NoPassObject
                                          : (bottle_master.on ? Branch::MasterOn : Branch::MasterOff);
        const auto latest = bottle_caustic ? BottleSource::MasterRead{} : BottleCaustic::LatestCutMaster();
        const void* reader = nullptr;
#if defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
        if (upscaler->BottleRawSearchRequested()) reader = upscaler.get();
#endif
        const auto frame = BottleCutFrame(this, request, scheduler, *scene_targets, *rt_shadow, *object_motion);
        bottle_opportunity = BottleCold::Current().Observe(
            frame, depth_key, color_key, scheduler.CurrentTick(), camera, bindings.color, bindings.depth,
            {branch, bottle_master}, latest, reader);
#if defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
        if (reader && bottle_opportunity)
            raw_phase = BottleRawApply180::CurrentBudget().Begin(
                BottleRawApply180::Selected(request), *bottle_opportunity, frame, color_key, depth_key);
#endif
    }
    if (bottle_master.on) {
        bottle_caustic->Apply(cb_descs[0].first, db_desc.first, upscaler->Jitter(),
                              bottle_opportunity ? &*bottle_opportunity : nullptr
#if defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
                              , raw_phase
#endif
                              );
    }
#if defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    if (raw_phase) BottleRawApply180::CurrentBudget().Finish(*raw_phase);
#endif
    if (bottle_opportunity) BottleCold::Current().Add(*bottle_opportunity);
#else
    if (bottle_caustic && BottleCaustic::On()) {
        bottle_caustic->Apply(cb_descs[0].first, db_desc.first, upscaler->Jitter());
    }
#endif
    // bbport (r107_caustics): BB_CAUSTICS only: the water caustics, once after each G-buffer
    // pass, after the indirect light is in (they move the lit surface's light) and before the
    // drawn look paints it.
    if (caustics) {
        caustics->Apply(cb_descs[0].first, db_desc.first, upscaler->Jitter(), wind.Get().wind,
                        sewer_receiver ? this : nullptr);
    }
    // bbport (r131a_foliage-translucency): the back-lit glow of leaves and grass, once after each G-buffer pass's opaque lighting, right after the
    // caustics and before the blood sheen, the glass view and the drawn look (off: one null pointer test).
    if (foliage_glow) {
        const auto mask = foliage_mask ? FoliageDiagnosticView() : vk::ImageView{};
        foliage_glow->Apply(cb_descs[0].first, db_desc.first, upscaler->Jitter(), {},
                            mask, {mask_receivers.key.width, mask_receivers.key.height});
    }
    // bbport (r100d_blood-sheen-gbuffer): BB_BLOOD_SHEEN=show only: the pixels the wet film took
    // painted over the lit scene, once after each wet-ground pass (vk_blood_sheen.h).
    if (blood_sheen) {
        blood_sheen->Show(cb_descs[0].first, point_shadow->Pending());
    }
    // bbport (r129a_glass-registry): BB_GLASS_VIEW on only (off: one null pointer test): the tagged pixels of the registry's
    // G-buffer hit draws painted over the lit scene, once after each G-buffer pass's opaque lighting (vk_glass_view.h).
    if (glass_view) {
        glass_view->Show(cb_descs[0].first, point_shadow->Pending());
    }
    // bbport (r131c_cabinet-glass-clear): BB_GLASS_CLEAR on only (off: one null pointer test): the cabinet's pane put back as a glass
    // layer over the lit scene, once after each G-buffer pass's opaque lighting that had a redirected pane draw (vk_glass_clear.h).
    if (glass_clear) {
        glass_clear->Composite(cb_descs[0].first, db_desc.first, upscaler->Jitter(), point_shadow->Pending());
    }
    // bbport (t129c_sun-term-view, TOOL): BB_RT_SUN_TERM_VIEW on only (off: one null pointer test): the lit scene overwritten with
    // the ray traced sun/moon shadow term as grey (vk_sun_term_view.h).
    if (sun_term_view) {
        sun_term_view->Show(cb_descs[0].first, point_shadow->Pending());
    }
    // bbport (r45_drawn-look): after the indirect light is in: the strokes take the lit surface.
    if (drawn_look_wanted) {
        drawn_look->OnBlendedScene(cb_descs[0].first, db_desc.first, upscaler->Jitter());
    }
    // bbport (r86i_glint-find-gbuffer): the glint of a pane the G-buffer drew (BB_GLASS_BOX_PANES), once a
    // frame, over the lit scene (the pane's own draw has the normal target as target 0). Off: one bool.
    if (glass_glint && glint_gpane_on) {
        glint_gpane_on = false;
        RtGlassFind::Chain().after_blended.fetch_add(1, std::memory_order_relaxed); // bbport (r86j)
        glass_glint->AfterGlassDraw(cb_descs[0].first, db_desc.first, upscaler->Jitter(), point_shadow->Pending(),
                                    glint_gpane);
    }
    if (glass_tri_read) { // bbport (r86m_glint-pane-from-triangle, TOOL): the G-buffer's texels at the pick pixels, once
        GlassTriReadback();
    }
}

// bbport (r45_drawn-look): a full-screen pass over the scene colour is about to be drawn.
void Rasterizer::EffectsSceneComposite(const GraphicsPipeline* pipeline) {
    if (glass_tri_read) { // bbport (r86m_glint-pane-from-triangle, TOOL): as in EffectsBlendedScene, when no blended draw came
        GlassTriReadback();
    }
    // bbport (r86j_glint-same-game): no blended draw came after the pane's G-buffer draw: its glint runs here
    // (still over the lit scene, under the drawn look's strokes). Off: one bool.
    if (glass_glint && glint_gpane_on) {
        glint_gpane_on = false;
        RtGlassFind::Chain().after_composite.fetch_add(1, std::memory_order_relaxed);
        glass_glint->AfterGlassDraw(cb_descs[0].first, db_desc.first, upscaler->Jitter(), point_shadow->Pending(),
                                    glint_gpane);
    }
    if (drawn_look_wanted) {
        drawn_look->OnSceneComposite(FragmentHash(pipeline), cb_descs[0].first, db_desc.first,
                                     upscaler->Jitter());
    }
}

void Rasterizer::EffectsBeforeUpscaler(u64 compute_hash) {
    // bbport (r111e_prints-draw): BB_FOOTPRINTS on only (off: one null pointer test): the footprints
    // over the scene colour, the flat red test view or the post stamp (vk_footprints.h).
    if (footprints && compute_hash == upscaler->TriggerHash()) {
        footprints->DrawOver(upscaler->SceneColor(), upscaler->Jitter());
    }
    // bbport (r45_drawn-look): before the volumetric light below, which is fog and stays
    // unpainted.
    if (drawn_look_wanted && compute_hash == upscaler->TriggerHash()) {
        drawn_look->OnBeforeUpscaler(upscaler->SceneColor(), camera_motion->Depth(),
                                     upscaler->Jitter());
    }
    // bbport (r119_volumetric-clouds): BB_VOLUMETRIC_CLOUDS=1 only (off: one null pointer test): the
    // clouds over the sky pixels of the scene colour, after the sky, the world and the drawn look,
    // before the volumetric fog composite below (the fog lies over them), the tonemap and the upscaler.
    if (cloud_layer && compute_hash == upscaler->TriggerHash()) {
        cloud_layer->Apply(upscaler->SceneColor(), camera_motion->Depth(), upscaler->Jitter());
    }
    if (effects_wanted && compute_hash == upscaler->TriggerHash()) {
        const auto camera = camera_motion->PassMatrices();
        volumetric_light->SetCamera({camera.view, camera.inv_view, camera.valid});
        // bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS set and lamp fog on only: this frame's
        // ray traced scene for the lamp fog's shadow maps. PrepareScene returns at once when the
        // TLAS already holds every entry of the frame, else it builds or refits it again (r17
        // tlas_prepared).
        if (LampFogShafts::Level() != LampFogShafts::Off &&
            BbSettings::Get().effects[BbSettings::EffectPointFog].load(std::memory_order_relaxed)) {
            scheduler.EndRendering();
            volumetric_light->SetLampScene(rt_shadow->PrepareScene()
                                               ? rt_shadow->Scene()
                                               : vk::AccelerationStructureKHR{});
        }
        volumetric_light->Composite(upscaler->SceneColor(), "the upscaler");
    }
    // bbport (r95_halation, r109a_strength-settings-engine): the film halation into the scene
    // colour at this frame's strength (Halation::Strength: the setting, or BB_HALATION when set),
    // after the drawn look and the fog; the HUD is drawn later, on the upscaler's output. At 0
    // nothing is drawn; the Halation is made at the first frame above 0 and kept.
    if (compute_hash == upscaler->TriggerHash()) {
        if (const float strength = Halation::Strength().value; strength > 0.0f) {
            if (!halation) {
                halation = std::make_unique<Halation>(instance, scheduler, texture_cache, runtime,
                                                      *scene_targets, *camera_motion,
                                                      upscaler->Enabled());
            }
            halation->Apply(upscaler->SceneColor(), strength);
        }
    }
    // bbport (r128b_lrt-caustics-water): the water caustics' strengths are settings
    // (graphics_water_caustics_sun_strength, graphics_water_caustics_lamps_strength; BB_CAUSTICS and
    // BB_CAUSTICS_LAMPS win when set), read every frame. The Caustics is made at the start when a strength is
    // above 0 and here, at the first frame one is, when it was not; it is kept. At 0 its passes return at
    // once. Without an object at 0: four relaxed loads and a few compares.
    if (compute_hash == upscaler->TriggerHash()) {
        Caustics::StrengthLine();
        if (!caustics && Caustics::Wanted()) {
            caustics = std::make_unique<Caustics>(instance, scheduler, texture_cache, runtime,
                                                  *scene_targets, *camera_motion, *point_shadow,
                                                  upscaler->Enabled());
        }
        if (caustics) {
            caustics->Refresh();
        }
    }
    // bbport (r97e_heat-haze-option): the haze's strength is a setting (HeatHaze::Strength: the key
    // graphics_heat_haze_strength, or BB_HEAT_HAZE when set), read every frame. The HeatHaze is made at
    // the first frame above 0 when it was not made at the start, and kept; at 0 the lamps are not
    // gathered and the pass below does not run. Without an object at 0: two relaxed loads.
    if (compute_hash == upscaler->TriggerHash()) {
        HeatHaze::StrengthLine();
        const bool haze_on = HeatHaze::Wanted();
        if (!heat_haze && haze_on) {
            heat_haze = std::make_unique<HeatHaze>(instance, scheduler, texture_cache, runtime,
                                                   *scene_targets, *camera_motion);
        }
        if (heat_haze) {
            heat_haze->Gather(haze_on);
        }
    }
    // bbport (r97_heat-haze): BB_HEAT_HAZE only: the shimmer above flames, after the fog
    // composite (the fog behind a flame shimmers too), before the upscaler and the HUD.
    if (heat_haze && compute_hash == upscaler->TriggerHash() && HeatHaze::Wanted()) { // r97e
        heat_haze->Apply(upscaler->SceneColor(), camera_motion->Depth(), upscaler->Jitter(),
                         BbWindFelt::Felt(BbWind::Follower::Haze, wind.Get(),
                                          camera_motion->CameraMatrices().inv_view,
                                          wind_shelter ? wind_shelter->CameraOpen() : 1.0f)); // bbport (r116, r97g): in sheltered air the haze rises straight
    }
    // bbport (r117_wind-shelter): BB_WIND_SHELTER only: the wind shelter field's passes, after the
    // heat haze, with the sway region's address (0 without the region: nothing is made).
    if (wind_shelter && compute_hash == upscaler->TriggerHash()) {
        wind_shelter->Apply(upscaler->SceneColor(), camera_motion->Depth(), upscaler->Jitter(),
                            object_motion->SwayWords() != nullptr
                                ? object_motion->AddressTable().params +
                                      u64(Shader::MotionVectors::ParamsCapacity) * 32u
                                : 0u,
                            wind.Get());
    }
    if (auto* pane = rt_shadow->ActiveLampPane(); pane && compute_hash == upscaler->TriggerHash()) {
        LampPaneDepth(*pane);
    }
    if (window_receiver && compute_hash == upscaler->TriggerHash()) {
        CaptureWindowDepth();
    }
    // bbport (r120_test-camera-lookat, TOOL): BB_TEST_WORLD_AT and BB_TEST_CAMERA=lookat:centre: the world under pixels, from the
    // scene's depth (made at the first wanted read; off: one relaxed load of a false flag).
    if (BbTestCamera::WorldWanted() && compute_hash == upscaler->TriggerHash()) {
        if (!test_world_at) {
            test_world_at = std::make_unique<TestWorldAt>(instance, scheduler, texture_cache, runtime, *scene_targets, *camera_motion);
        }
        test_world_at->OnScene(camera_motion->Depth(), object_motion->Frame());
    }
    // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA_VIEW: the card debug view, last, over all of it.
    if (card_alpha && card_alpha->ViewOn() && compute_hash == upscaler->TriggerHash()) {
        card_alpha->View(upscaler->SceneColor(), camera_motion->Depth(), upscaler->Jitter());
    }
}

void Rasterizer::EffectsBeforeResources(const GraphicsPipeline* pipeline) {
    // bbport (r111_footprints): BB_FOOTPRINTS on only (off: one null pointer test a draw). Before
    // this draw's textures, barriers and pass: the G-buffer pass's targets, and the prints laid
    // into the G-buffer at the first light draw after each G-buffer pass (vk_footprints.h).
    if (footprints) {
        std::array<VideoCore::ImageId, AmdGpu::NUM_COLOR_BUFFERS> print_targets{};
        for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
            print_targets[cb] = cb_descs[cb].first;
        }
        const u64 print_ps = FragmentHash(pipeline);
        footprints->BeforeDraw(*pipeline, print_targets, db_desc.first,
                               PointLightCount(print_ps) != 0 ||
                                   print_ps == DirectionalFragmentShaderHash ||
                                   print_ps == ShadowResolveHash,
                               point_shadow->Pending(), upscaler->Jitter());
    }
    // bbport (r100c_blood-pool-probe, TOOL): BB_BLOOD_POOL_PROBE only (off: one null pointer test a
    // draw). First, so that what the passes below write before this draw counts for it as well.
    // A light draw: the shadow resolve, the sun or moon, a lamp of the grid (as r100's kinds).
    if (blood_pool_probe) {
        const u64 probe_ps = FragmentHash(pipeline);
        BloodPoolProbeBefore(pipeline, false,
                             PointLightCount(probe_ps) != 0 || probe_ps == DirectionalFragmentShaderHash ||
                                 probe_ps == ShadowResolveHash);
    }
    // bbport (r100_blood-sheen): BB_BLOOD_SHEEN on only (off: one null pointer test a draw). Before
    // this draw's textures, barriers and pass: the G-buffer and light targets of the frame, the
    // wet ground before the sun and lamps, and the snapshot before the blood pool's draw
    // (vk_blood_sheen.h).
    if (blood_sheen) {
        std::array<VideoCore::ImageId, AmdGpu::NUM_COLOR_BUFFERS> sheen_targets{};
        for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
            sheen_targets[cb] = cb_descs[cb].first;
        }
        const u64 sheen_ps = FragmentHash(pipeline);
        blood_sheen->BeforeDraw(Regs(), *pipeline, sheen_targets, db_desc.first,
                                {.lamp = PointLightCount(sheen_ps) != 0,
                                 .sun = sheen_ps == DirectionalFragmentShaderHash,
                                 .resolve = sheen_ps == ShadowResolveHash},
                                point_shadow->Pending(), upscaler->Jitter());
    }
    if (effects_wanted && FragmentHash(pipeline) == HdrPostHash) {
        const auto camera = camera_motion->PassMatrices();
        volumetric_light->SetCamera({camera.view, camera.inv_view, camera.valid});
        // bbport (r80_lamp-fog-shafts): as before the upscaler's composite above
        if (LampFogShafts::Level() != LampFogShafts::Off &&
            BbSettings::Get().effects[BbSettings::EffectPointFog].load(std::memory_order_relaxed)) {
            scheduler.EndRendering();
            volumetric_light->SetLampScene(rt_shadow->PrepareScene()
                                               ? rt_shadow->Scene()
                                               : vk::AccelerationStructureKHR{});
        }
        volumetric_light->Composite();
    }
}

namespace {
/// bbport (r50b_leaf-matcher): with BB_RT_CARD_ALPHA_LOG=1, every draw of a matched cut-out pixel
/// shader whose record holds RepeatableWithConstants() is counted by its memory dwords
/// (Shader::Optimization::CutoutConstants), and the first one of each pgm_hash prints the dwords'
/// values (the record's camera pass reference and coordinates, for a ray to repeat). A draw whose
/// pixel shader inputs are not the ones the record was analysed with is drawn by another
/// permutation: counted, nothing read. A dword is read only from the shader's own user data, or
/// from a guest constant buffer the shader does not write, at a valid V#, inside it and inside a
/// GPU mapping, in no region the GPU wrote (as the r17 hash below: such a page may be the GPU's
/// with BB_READBACKS=2, and a read fault here would wait for this thread; its CPU copy is stale
/// otherwise); one in such a region is not read (NaN), and marked GPU-written, or in place when
/// that range is bound in place (BB_GUEST_IN_PLACE: a write still pending).
void LogCutoutConstants(const AmdGpu::Regs& regs, const Shader::Info& ps,
                        Core::MemoryManager& memory, VideoCore::BufferCache& buffer_cache) {
    namespace Opt = Shader::Optimization;
    using Ref = Shader::Info::Cutout::Ref;
    using State = Opt::CutoutConstants;
    const Shader::Info::Cutout* cut = &ps.cutout;
    if (cut->verdict == Shader::Info::Cutout::Verdict::NotAnalysed) {
        // a program from the cache: the first compile's record
        cut = Opt::FindCutout(ps.pgm_hash);
        if (!cut || cut->image_count != ps.images.size() ||
            cut->buffer_count != ps.buffers.size()) {
            return;
        }
    }
    if (!cut->RepeatableWithConstants()) {
        return;
    }
    // (E6) the permutation: a draw gets permutation 0's Info (PipelineCache::GetProgram)
    u32 default_mask = 0, flat_mask = 0;
    for (u32 i = 0; i < regs.num_interp && i < 32 && i < regs.ps_inputs.size(); ++i) {
        default_mask |= regs.ps_inputs[i].use_default ? 1u << i : 0u;
        flat_mask |= regs.ps_inputs[i].flat_shade ? 1u << i : 0u;
    }
    if (!Opt::CutoutSamePermutation(*cut, regs.num_interp, default_mask, flat_mask)) {
        (void)Opt::NoteCutoutConstants(ps.pgm_hash, State::OtherPermutation);
        return;
    }
    const auto dwords = Opt::CutoutDwords(*cut);
    std::array<f32, 7> values{};
    values.fill(std::numeric_limits<f32>::quiet_NaN());
    State state = State::CpuWritten;
    const auto worse = [&state](State s) {
        state = u8(s) > u8(state) ? s : state;
    };
    const auto user_data = ps.UserData();
    const auto flat = ps.FlatUserData();
    for (size_t i = 0; i < dwords.size(); ++i) {
        const Opt::CutoutDword& d = dwords[i];
        if (d.kind == Ref::UserData || d.kind == Ref::FlatUserData) {
            const auto ud = d.kind == Ref::UserData ? user_data : flat;
            if (d.dword < ud.size()) {
                values[i] = std::bit_cast<f32>(ud[d.dword]);
            } else {
                worse(State::Unreadable);
            }
            continue;
        }
        if (d.kind != Ref::ConstBuffer) {
            continue;
        }
        if (d.buffer >= ps.buffers.size() || ps.buffers[d.buffer].IsSpecial()) {
            worse(State::Unreadable);
            continue;
        }
        if (ps.buffers[d.buffer].is_written) {
            worse(State::GpuWritten); // the shader's own writes
            continue;
        }
        const AmdGpu::Buffer sharp = ps.buffers[d.buffer].GetSharp(ps);
        const u64 offset = u64(d.dword) * 4;
        const VAddr address = sharp.base_address + offset;
        if (!sharp.Valid() || offset + 4 > sharp.GetSize() ||
            !memory.IsValidGpuMapping(address, 4) || memory.ClampRangeSize(address, 4) != 4) {
            worse(State::Unreadable);
            continue;
        }
        if (buffer_cache.IsRegionGpuModified(address, 4)) {
            worse(buffer_cache.IsInPlace(address, 4) ? State::InPlace : State::GpuWritten);
            continue; // not read
        }
        u32 raw = 0;
        std::memcpy(&raw, reinterpret_cast<const void*>(address), sizeof(raw));
        values[i] = std::bit_cast<f32>(raw);
    }
    if (!Opt::NoteCutoutConstants(ps.pgm_hash, state)) {
        return; // the line was printed for an earlier draw
    }
    const auto vs_out = [&regs](u32 input) {
        if (input >= regs.ps_inputs.size()) {
            return -1;
        }
        const AmdGpu::PsInputControl& control = regs.ps_inputs[input];
        if (control.use_default) {
            return -1;
        }
        return int(control.input_offset) | (control.flat_shade ? Opt::CutoutFlatInput : 0);
    };
    u8 stored = 0xff;
    if (cut->image < ps.images.size()) {
        const AmdGpu::Image image = ps.images[cut->image].GetSharp(ps);
        if (image.Valid()) {
            stored = u8(image.DstSelect().array[cut->channel & 3]);
        }
    }
    std::array<u32, 2> dither_size{};
    if (cut->dither && cut->dither_image < ps.images.size()) {
        const AmdGpu::Image image = ps.images[cut->dither_image].GetSharp(ps);
        if (image.Valid()) {
            dither_size = {u32(image.width) + 1, u32(image.height) + 1};
        }
    }
    const int alpha_vs_out =
        cut->alpha_input != Shader::Info::Cutout::NoInput ? vs_out(cut->alpha_input) : -1;
    const std::string line = Opt::CutoutConstantsLine(ps.pgm_hash, *cut, values,
                                                      vs_out(cut->input), alpha_vs_out, stored,
                                                      state, dither_size);
    std::printf("%s\n", line.c_str());
}
} // namespace

namespace {
// bbport (r54_leaf-stage2): the record's ops in the order the card data keeps them.
static_assert(u8(CardOp::Less) == u8(Shader::Info::Cutout::Op::Less) &&
              u8(CardOp::LessEqual) == u8(Shader::Info::Cutout::Op::LessEqual) &&
              u8(CardOp::Greater) == u8(Shader::Info::Cutout::Op::Greater) &&
              u8(CardOp::GreaterEqual) == u8(Shader::Info::Cutout::Op::GreaterEqual) &&
              u8(CardOp::Equal) == u8(Shader::Info::Cutout::Op::Equal) &&
              u8(CardOp::NotEqual) == u8(Shader::Info::Cutout::Op::NotEqual));

/// The guest memory as ReadCardBufferDword asks about it: the checks r50b's draw-time line makes
/// (LogCutoutConstants above), in the same order.
struct CardGuest {
    Core::MemoryManager& memory;
    VideoCore::BufferCache& buffer_cache;
    bool Mapped(u64 address, u64 size) {
        return memory.IsValidGpuMapping(address, size) && memory.ClampRangeSize(address, size) == size;
    }
    bool GpuModified(u64 address, u64 size) {
        return buffer_cache.IsRegionGpuModified(address, size);
    }
    bool InPlace(u64 address, u64 size) {
        return buffer_cache.IsInPlace(address, size);
    }
    u32 Read(u64 address) {
        u32 raw = 0;
        std::memcpy(&raw, reinterpret_cast<const void*>(address), sizeof(raw));
        return raw;
    }
};

/// bbport (r54_leaf-stage2): with BB_RT_CARD_ALPHA=1, a cut-out pixel shader's test as this draw
/// holds it (rt_card_uv.h, CardDraw): the record of its pixel shader (r50b: matched, repeatable
/// with the draw's constants, this permutation), the vertex shader outputs its inputs read (the
/// selector the capture stores by), the dwords the coordinates and the reference read (from
/// memory the GPU did not write only: a dword it wrote, or one bound in place, is not read and
/// the draw has no card data), the alpha texture's T# and its sampler's repeat. A plain value:
/// nothing in it points into the shader's Info or guest memory. miss says why not valid.
/// RepeatableWithConstants() alone decides which records count. Since r50c it accepts a record
/// whose nonzero term has an ignored factor that is a buffer load with one address a triangle
/// (the game's per-instance fade): that factor is left out, never read here, and ignored_kinds
/// is not looked at (CardKeeps says what leaving it out means); ignored_factor_terms only sets
/// CardDraw::fade_left_out, which the 600-frame line counts (judge's item 7).
CardDraw ResolveCardDraw(const AmdGpu::Regs& regs, const Shader::Info& ps, bool camera,
                         Core::MemoryManager& memory, VideoCore::BufferCache& buffer_cache) {
    namespace Opt = Shader::Optimization;
    using Cutout = Shader::Info::Cutout;
    using Ref = Cutout::Ref;
    CardDraw out;
    out.camera = camera;
    out.ps_hash = ps.pgm_hash;
    const Cutout* cut = &ps.cutout;
    if (cut->verdict == Cutout::Verdict::NotAnalysed) {
        cut = Opt::FindCutout(ps.pgm_hash); // a program from the cache: the first compile's
        if (!cut) {
            out.miss = CardMiss::NoRecord;
            return out;
        }
        // a record, but of another resource list: its dword and image indices are not this
        // draw's, so none is read (counted apart from "no record")
        if (cut->image_count != ps.images.size() || cut->buffer_count != ps.buffers.size()) {
            out.miss = CardMiss::OtherResources;
            return out;
        }
    }
    // A sample of one fixed layer (Layer::Immediate) is repeatable, but the card data has no
    // layer (stage 3 copies one 2D slice of the T#): no card for it until a stage carries one.
    if (!cut->RepeatableWithConstants() || cut->layer != Cutout::Layer::None) {
        out.miss = CardMiss::NotRepeatable;
        return out;
    }
    u32 default_mask = 0, flat_mask = 0;
    for (u32 i = 0; i < regs.num_interp && i < 32 && i < regs.ps_inputs.size(); ++i) {
        default_mask |= regs.ps_inputs[i].use_default ? 1u << i : 0u;
        flat_mask |= regs.ps_inputs[i].flat_shade ? 1u << i : 0u;
    }
    if (!Opt::CutoutSamePermutation(*cut, regs.num_interp, default_mask, flat_mask)) {
        out.miss = CardMiss::OtherPermutation;
        return out;
    }
    const auto input = [&regs](u32 i) {
        if (i >= regs.ps_inputs.size()) {
            return CardInput{0, true, false};
        }
        const AmdGpu::PsInputControl& control = regs.ps_inputs[i];
        return CardInput{u32(control.input_offset), control.use_default != 0,
                         control.flat_shade != 0};
    };
    const bool has_alpha = cut->alpha_input != Cutout::NoInput;
    CardSelector selector;
    if (!CardSelectorFor(input(cut->input), cut->comp_u, cut->comp_v, has_alpha,
                         has_alpha ? input(cut->alpha_input) : CardInput{}, cut->alpha_comp,
                         selector)) {
        out.miss = CardMiss::Inputs;
        return out;
    }
    // The dwords (CutoutDwords' order): every one the record names, the dither's coefficient
    // too (a camera pass draw that dithers: kept apart from the reference, CardDraw::dither_scale).
    // Slots come from the record, never fixed numbers.
    const auto dwords = Opt::CutoutDwords(*cut);
    CardRecordValues record;
    record.uv_scale = cut->uv_scale;
    record.uv_offset = cut->uv_offset;
    record.ref = cut->ref;
    record.ref_scale = cut->ref_scale;
    record.ref2_scale = cut->ref2_scale;
    record.dither = camera && cut->dither;
    record.dither_scale = cut->dither_scale;
    std::array<float, 7> values{};
    CardDwordState state = CardDwordState::Read;
    CardGuest guest{memory, buffer_cache};
    for (size_t i = 0; i < dwords.size(); ++i) {
        const Opt::CutoutDword& d = dwords[i];
        if (d.kind == Ref::Immediate || (i == CardDwordDither && !record.dither)) {
            continue;
        }
        record.named[i] = true;
        u32 raw = 0;
        CardDwordState s = CardDwordState::Unreadable;
        if (d.kind == Ref::UserData || d.kind == Ref::FlatUserData) {
            s = ReadCardUserDword(d.kind == Ref::UserData ? ps.UserData() : ps.FlatUserData(),
                                  d.dword, raw);
        } else if (d.kind == Ref::ConstBuffer) {
            CardBufferFacts facts;
            facts.bound = d.buffer < ps.buffers.size();
            facts.special = facts.bound && ps.buffers[d.buffer].IsSpecial();
            facts.written = facts.bound && ps.buffers[d.buffer].is_written;
            if (facts.bound && !facts.special && !facts.written) {
                const AmdGpu::Buffer sharp = ps.buffers[d.buffer].GetSharp(ps);
                facts.valid = sharp.Valid();
                facts.base = sharp.base_address;
                facts.size = sharp.GetSize();
            }
            s = ReadCardBufferDword(facts, d.dword, guest, raw);
        }
        state = CardWorse(state, s);
        if (s == CardDwordState::Read) {
            values[i] = std::bit_cast<f32>(raw);
        }
    }
    if (state != CardDwordState::Read) {
        out.miss = CardMiss::Constants;
        return out;
    }
    const CardResolved resolved = CardResolve(record, values);
    if (!resolved.finite) {
        out.miss = CardMiss::Constants;
        return out;
    }
    if (cut->image >= ps.images.size() || cut->sampler >= ps.samplers.size()) {
        out.miss = CardMiss::Image;
        return out;
    }
    const AmdGpu::Image image = ps.images[cut->image].GetSharp(ps);
    if (!image.Valid()) {
        out.miss = CardMiss::Image;
        return out;
    }
    static_assert(sizeof(image) == sizeof(out.tsharp));
    std::memcpy(out.tsharp.data(), &image, sizeof(out.tsharp));
    out.stored_channel = u8(image.DstSelect().array[cut->channel & 3]);
    out.data_format = u8(image.GetDataFmt());
    const AmdGpu::Sampler sampler = ps.samplers[cut->sampler].GetSharp(ps);
    out.mode_u = u8(CardAxisMode(u32(sampler.clamp_x.Value())));
    out.mode_v = u8(CardAxisMode(u32(sampler.clamp_y.Value())));
    // bbport (r62_leaf-stage3): the raw modes, for the mirror once and border modes the axis
    // modes fold into CLAMP (CardAxisExtra).
    out.clamp_u = u8(u32(sampler.clamp_x.Value()));
    out.clamp_v = u8(u32(sampler.clamp_y.Value()));
    out.selector = PackCardSelector(selector);
    out.affine = resolved.affine;
    out.reference = resolved.reference;
    out.dither_scale = resolved.dither_scale;
    out.ref_dwords = resolved.ref_dwords;
    out.op = CardOp(u8(cut->op));
    out.nonzero = cut->nonzero;
    out.dither = record.dither;
    out.fade_left_out = cut->nonzero && cut->ignored_factor_terms != 0;
    CardFinishHashes(out);
    out.valid = true;
    return out;
}
} // namespace

// t132a: only called for a noted draw of the armed rectangle. This also works when RT capture
// is off. ResolveCardDraw uses the existing checked constant reads and returns a value.
BloodPoolProbe::FoliageFacts Rasterizer::FoliageProbeFacts(
    const GraphicsPipeline& pipeline, bool camera_gbuffer, bool indirect, bool is_indexed,
    u32 index_offset) {
    using Texture = BloodPoolProbe::FoliageTexture;
    using Source = Texture::Source;
    BloodPoolProbe::FoliageFacts out;
    const auto& regs = Regs();
    const auto& vs = pipeline.GetStage(Shader::SwStage::Vertex);
    out.vs = vs.pgm_hash;
    out.camera_gbuffer = camera_gbuffer;
    out.indirect = indirect;
    out.indexed = is_indexed;
    out.primitive = u32(regs.primitive_type);
    out.restart = regs.enable_primitive_restart != 0;
    if (is_indexed) {
        out.index_base = regs.index_base_address.Address<VAddr>();
        out.index_type = u32(regs.index_buffer_type.index_type);
    }
    // Indirect arguments may have been written by the GPU. Use no range or offset register
    // as a substitute for the arguments of that command.
    if (!indirect) {
        out.first_index = is_indexed ? index_offset : 0;
        out.count = regs.num_indices;
        out.instances = regs.num_instances.NumInstances();
        out.first_vertex = regs.index_offset;
        out.offsets_known = true;
    }
    if (const auto& fetch = pipeline.GetFetchShader()) {
        if (!indirect) {
            const auto data = vs.UserData();
            const auto offset = [&](s32 sgpr, u32& value) {
                if (sgpr == -1) {
                    return;
                }
                if (sgpr < 0 || u32(sgpr) >= data.size()) {
                    out.offsets_known = false;
                    return;
                }
                value = data[sgpr];
            };
            if (out.first_vertex == 0) {
                offset(fetch->vertex_offset_sgpr, out.first_vertex);
            }
            offset(fetch->instance_offset_sgpr, out.first_instance);
        }
        for (const auto& attribute : fetch->attributes) {
            if (attribute.semantic == 0) {
                const auto stream = attribute.GetSharp(vs);
                out.position_base = stream.base_address;
                out.position_size = stream.GetSize();
                out.stride = stream.GetStride();
                out.position_data_format = stream.data_format;
                out.position_number_format = stream.num_format;
                out.position_valid = stream.Valid() && out.position_base && out.position_size;
                break;
            }
        }
    }
    const auto* ps = pipeline.GetStages()[u32(Shader::SwStage::Fragment)];
    if (!ps) {
        return out;
    }
    out.has_ps = true;
    out.ps = ps->pgm_hash;
    out.discard = ps->has_discard;
    out.verdict = u32(ps->cutout.verdict);
    out.num_inputs = regs.num_interp;
    for (u32 i = 0; i < std::min({out.num_inputs, u32(out.input_offsets.size()),
                                  u32(regs.ps_inputs.size())}); ++i) {
        const auto& input = regs.ps_inputs[i];
        out.input_offsets[i] = u8(input.input_offset);
        out.default_inputs |= input.use_default ? 1u << i : 0u;
        out.flat_inputs |= input.flat_shade ? 1u << i : 0u;
    }
    if (camera_gbuffer && out.discard) {
        const CardDraw card = ResolveCardDraw(regs, *ps, true, *memory, buffer_cache);
        out.resolved = true;
        out.card_valid = card.valid;
        out.miss = u32(card.miss);
        out.selector = card.selector;
        out.stored_channel = card.stored_channel;
        out.card_format = card.data_format;
        out.op = u32(card.op);
        out.tsharp = card.tsharp;
        for (u32 i = 0; i < card.affine.size(); ++i) {
            out.card_words[i] = std::bit_cast<u32>(card.affine[i]);
        }
        out.card_words[4] = std::bit_cast<u32>(card.reference);
        out.card_words[5] = std::bit_cast<u32>(card.dither_scale);
        out.card_words[6] = std::bit_cast<u32>(card.ref_dwords[0]);
        out.card_words[7] = std::bit_cast<u32>(card.ref_dwords[1]);
        out.dither = card.dither;
        out.fade_left_out = card.fade_left_out;
        out.nonzero = card.nonzero;
        out.clamp_u = card.clamp_u;
        out.clamp_v = card.clamp_v;
        out.uv_hash = card.uv_hash;
        out.constants_hash = card.constants_hash;
    }

    const auto& bound = Dc().card_bound;
    out.texture_count = u32(ps->images.size());
    out.binding_enabled = card_bound_on;
    out.bindings_exact = card_bound_on && bound.stage == ps &&
                         bound.count == out.texture_count && bound.count <= bound.ids.size();
    out.binding_count = out.bindings_exact ? bound.count : 0;
    for (u32 i = 0; i < out.texture_count; ++i) {
        if (i >= out.textures.size() && !out.card_valid) {
            break;
        }
        const auto& res = ps->images[i];
        const auto sharp = res.GetSharp(*ps);
        const auto words = std::bit_cast<std::array<u32, 8>>(sharp);
        // Match the same full T# as NoteCardLayer. Record ambiguity if more than one
        // resource matches, since the shader may use different views for the same T#.
        const bool alpha = out.card_valid && words == out.tsharp;
        out.alpha_matches += alpha;
        if (i >= out.textures.size() && (!alpha || out.alpha_matches != 1)) {
            continue;
        }
        Texture value;
        value.sharp = words;
        value.view = BloodPoolProbe::FoliageView::From(VideoCore::ImageViewInfo(sharp, res));
        if (out.bindings_exact) {
            const auto id = bound.ids[i];
            value.id = id.index;
            value.uid = bound.uids[i];
            if (id && value.uid) {
                const auto* image = texture_cache.TryGetImage(id, value.uid);
                if (image && texture_cache.IsRegisteredImage(id, value.uid)) {
                    value.write_seq = image->write_seq;
                    value.source = Source::Registered;
                } else {
                    value.source = Source::Unverified;
                }
            } else {
                value.source = !id && !sharp ? Source::Null : Source::Unverified;
            }
        }
        if (i < out.textures.size()) {
            out.textures[i] = value;
        }
        if (alpha && out.alpha_matches == 1) {
            out.alpha = value;
            out.alpha_slot = i;
        }
    }
    return out;
}

// bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA=2: the image a cut-out draw's card reads its alpha
// from, for its layer (CardAlpha::NoteDraw). This draw's own binding of its pixel shader's
// textures (BindTextures, before EffectsCaptureDraw) left what it found in the draw context
// (DrawContext::card_bound): from the texture set memo on a set hit, from its lookups otherwise.
// Not from the binding memo (image_desc_cache): a set hit does not touch it, so another T# may
// have evicted the card texture's entry while the card's draws keep hitting their set. The
// record is taken only when it is this pixel shader's (the stage pointer) and holds one image a
// shader image (no mip arrays); its image must still be the registered image of its uid
// (NoteDraw). Otherwise no layer this draw; a later draw of the card may.
void Rasterizer::NoteCardLayer(CardDraw& card, const Shader::Info& ps) {
    const DrawContext::CardBound& bound = Dc().card_bound;
    if (bound.stage == &ps) {
        for (u32 i = 0; i < bound.count && i < ps.images.size(); ++i) {
            const auto& res = ps.images[i];
            const AmdGpu::Image sharp = res.GetSharp(ps);
            static_assert(sizeof(sharp) == sizeof(card.tsharp));
            if (std::memcmp(&sharp, card.tsharp.data(), sizeof(card.tsharp)) != 0) {
                continue;
            }
            if (bound.ids[i]) {
                card_alpha->NoteDraw(card, sharp, res, bound.ids[i], bound.uids[i]);
                return;
            }
            break;
        }
    }
    card_alpha->NoteNoSource(card);
}

void Rasterizer::InitColdWindowPane() {
    using namespace WindowPathProbe;
    const char* text = std::getenv("BB_WINDOW_PATH_COLD_PANE");
    if (!text || !*text) {
        return;
    }
    PixelRequest request;
    if (!ParsePixelRequest(text, request) || request.count != 1) {
        std::printf("Window cold pane (t132f): invalid startup request (id:width:height:x:y)\n");
        return;
    }
    const auto pixel = request.pixels[0];
    window_cold_pane.Arm({request.id, request.width, request.height, pixel.x, pixel.y},
                         ColdPaneWatch::Clock::now());
    std::printf("Window cold pane (t132f): req=%u prearmed native=%ux%u xy=%u,%u deadline=120s\n",
                request.id, request.width, request.height, pixel.x, pixel.y);
}

void Rasterizer::ExpireColdWindowPane() {
    using namespace WindowPathProbe;
    if (window_cold_pane.Active() && window_cold_pane.Expired(ColdPaneWatch::Clock::now())) {
        std::printf("Window cold pane (t132f): req=%u unresolved (no exact indexed camera draw before startup deadline)\n",
                    window_cold_pane.pixels.id);
        window_cold_pane.pixels = {};
    }
}

void Rasterizer::ArmWindowPane(WindowPathProbe::ReceiverCapture& capture, bool wait_for_natural) {
    using namespace WindowPathProbe;
    capture.pane = std::make_unique<PaneAcquisition>(instance, scheduler);
    capture.pane->stages.arm_frame = object_motion->Frame();
    capture.pane->stages.arm_rt = rt_shadow->WindowDiagnosticFrame();
    if (wait_for_natural) {
        capture.pane->natural.Arm(capture.request.id, capture.pane->stages.arm_frame,
                                   NaturalPanePair::Clock::now());
    }
    rt_shadow->WatchWindowPane(capture.pane.get());
}

void Rasterizer::NoteWindowPaneDraw(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline,
                                    bool indexed, u32 first) {
    using namespace WindowPathProbe;
    auto* pane = window_receiver ? window_receiver->pane.get() : nullptr;
    if (!pane && !window_cold_pane.Active()) {
        return;
    }
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    if (!ps || ps->pgm_hash != WindowPaneDrawKey.ps ||
        pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash != WindowPaneDrawKey.vs) {
        return;
    }
    if (regs.num_indices != WindowPaneDrawKey.count || first != WindowPaneDrawKey.first) {
        if (pane) {
            pane->stages.guard |= PaneStages::Range;
        }
        return;
    }
    const auto& dc = Dc();
    if (window_cold_pane.Active() && !window_receiver && indexed && gbuffer_draw) {
        ExpireColdWindowPane();
        const auto launch = window_cold_pane.Take(true, ColdPaneWatch::Clock::now());
        if (launch.id) {
            PixelRequest request{.id = launch.id, .width = launch.width, .height = launch.height, .count = 1};
            request.pixels[0] = {launch.x, launch.y};
            window_receiver = std::make_unique<ReceiverCapture>(instance, scheduler, runtime, request);
            auto& capture = *window_receiver;
            capture.pane_sample = 0;
            capture.scene.textures = &texture_cache;
            ArmWindowPane(capture, true);
            pane = capture.pane.get();
            const char* owner = std::getenv("BB_WINDOW_PATH_PANE_OWNER");
            if (owner && std::string_view(owner) == "1" && launch.width == 1920 &&
                launch.height == 1080 && launch.x == 1003 && launch.y == 281) {
                pane->owner = std::make_unique<PaneOwnerAcquisition>(instance, scheduler);
            }
            window_receiver_last_request = std::max(window_receiver_last_request, launch.id);
            std::printf("Window cold pane (t132f): req=%u first exact indexed camera draw frame=%llu/%llu capture=%u\n",
                        launch.id, static_cast<unsigned long long>(pane->stages.arm_frame),
                        static_cast<unsigned long long>(pane->stages.arm_rt), unsigned(bool(dc.capture_draw)));
        }
    }
    if (!pane) {
        return;
    }
    auto& stage = pane->stages;
    if (window_receiver->pending.request) {
        PaneStages::Count(stage.exact_after);
        if (pane->natural.Latched() && gbuffer_draw &&
            pane->natural.build.object_frame == object_motion->Frame() &&
            pane->natural.build.rt_frame == rt_shadow->WindowDiagnosticFrame()) {
            stage.guard |= PaneStages::Duplicate;
            pane->Refuse("duplicate exact pane draw after sample");
        }
        return;
    }
    PaneStages::Count(stage.exact_before);
    stage.motion = pipeline->GetGraphicsKey().motion_vectors;
    stage.geometry = unsigned(bool(dc.motion_geometry));
    if (!indexed) {
        stage.guard |= PaneStages::NotIndexed;
    }
    if (!gbuffer_draw) {
        stage.guard |= PaneStages::CameraPass;
    }
    if (!dc.capture_draw) {
        stage.guard |= PaneStages::CaptureHookOff;
        stage.Refuse("outer-capture-draw-off", object_motion->Frame(), rt_shadow->WindowDiagnosticFrame());
    } else {
        PaneStages::Count(stage.hook);
    }
}

void Rasterizer::EffectsCaptureDraw(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline,
                                    bool is_indexed, u32 index_offset, RtShadow::BottleDrawToken& bottle,
                                    RtShadow::ReflectionDrawToken& reflection,
                                    ReflectionDiscard::StockRole original_stock_role,
                                    vk::Pipeline& classified_stock) {
    auto& dc = Dc();
    const u32 mode = pipeline->GetGraphicsKey().motion_vectors;
    if (Shader::MotionVectors::Kind(mode) == Shader::MotionVectors::VertexBoth) {
        dc.push_data.motion_param &= 0xffffu;
    } else {
        dc.push_data.motion_param = 0;
    }
    // bbport (r83b_glass-pane-probe): BB_RT_GLASS on: a capture draw of a named pair reached this
    // hook, and whether it stops just below (rt_glass_probe.h). Off: one test of a static bool.
    static const bool glass_probe = RtGlass().on;
    const auto* glass_ps =
        glass_probe ? pipeline->GetStages()[u32(Shader::SwStage::Fragment)] : nullptr;
    // bbport (r86g_glint-find-bottles): BB_RT_GLASS=auto: a forward draw blended with depth write and
    // a modest index count is a pane (rt_glass.h), whatever its shader pair
    const bool glass_auto_state =
        glass_ps && !gbuffer_draw && RtGlassAuto() &&
        RtGlassAutoDraw(regs.blend_control[0].enable != 0, regs.depth_control.depth_write_enable != 0,
                        regs.num_indices, RtGlassAutoIndices());
    // bbport (r86h_glint-camera): the state rule took the HUD (screen space draws after the display pass:
    // clip z 0, no 3D camera). A pane also has the shape of a mesh (BB_GLASS_AUTO_MIN indices or more, a
    // texture, no discard) and is drawn while the scene's frame runs (scene_started: from the first
    // G-buffer pass to the display pass). Off: glass_ps is null, nothing of this is read.
    const bool glass_shape =
        glass_auto_state && RtGlassAutoShape(regs.num_indices, RtGlassAutoMin(),
                                             !glass_ps->images.empty(), glass_ps->has_discard);
    const bool glass_auto = glass_shape && scene_started;
    const bool glass_hook =
        glass_ps && (RtGlassMatch(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,
                                  glass_ps->pgm_hash) ||
                     glass_auto);
    if (glass_hook) {
        RtGlassProbe::Add(RtGlassProbe::Hook);
    }
    // bbport (r86h_glint-camera): an auto draw left out above, said in the find table (a listed pair stays in)
    if (glass_auto_state && !glass_auto && RtGlassFind::On() &&
        !RtGlassMatch(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash, glass_ps->pgm_hash)) {
        RtGlassFind::NoteVerdict(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash, glass_ps->pgm_hash,
                                 scene_started ? RtGlassFind::Shape : RtGlassFind::Outside, nullptr);
    }
    const bool rt_wanted = rt_shadow->Wanted();
    if (!rt_wanted || !dc.motion_geometry) {
        if (reflection_probe && gbuffer_draw && is_indexed && JoinCount(regs.num_indices) &&
            ReflectionJoinTraceOn()) {
            const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
            const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
            const u64 frag = ps ? ps->pgm_hash : 0;
            TraceReflectionJoin(JoinTarget(vs.pgm_hash, frag, regs.num_indices, index_offset),
                                rt_shadow->WindowDiagnosticFrame(), reflection_probe->last_request,
                                vs.pgm_hash, frag, regs.num_indices, index_offset, "capture",
                                !rt_wanted ? "ordinary-rt-not-wanted" : "motion-geometry-missing",
                                regs, pipeline->GetGraphicsKey().mrt_mask);
        }
        if (window_receiver && window_receiver->pane && !window_receiver->pending.request &&
            regs.num_indices == WindowPathProbe::WindowPaneDrawKey.count &&
            index_offset == WindowPathProbe::WindowPaneDrawKey.first) {
            const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
            if (ps && ps->pgm_hash == WindowPathProbe::WindowPaneDrawKey.ps &&
                pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash == WindowPathProbe::WindowPaneDrawKey.vs) {
                auto& stage = window_receiver->pane->stages;
                stage.guard |= (!rt_wanted ? WindowPathProbe::PaneStages::RtUnwanted : 0u) |
                               (!dc.motion_geometry ? WindowPathProbe::PaneStages::NoMotionGeometry : 0u);
                stage.Refuse(!rt_wanted ? "capture-rt-unwanted" : "capture-motion-geometry-missing",
                             object_motion->Frame(), rt_shadow->WindowDiagnosticFrame());
            }
        }
        if (glass_hook) { // bbport (r83b_glass-pane-probe)
            RtGlassProbe::Add(RtGlassProbe::NoGeometry);
            if (RtGlassFind::On()) { // bbport (r86g_glint-find-bottles)
                RtGlassFind::NoteVerdict(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,
                                         glass_ps->pgm_hash, RtGlassFind::NoGeometry, nullptr);
            }
        }
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
    const bool shared_alpha = ps && ps->has_discard;
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
        .alpha = shared_alpha,
        .textured = ps && !ps->images.empty(),
        // bbport (r14_cascade_rt): the sun cascade of a shadow pass draw (RtShadow::SunCascade)
        .viewport = {regs.viewports[0].xoffset, regs.viewports[0].yoffset,
                     regs.viewports[0].xscale, regs.viewports[0].yscale},
        .target = regs.depth_buffer.Height(),
        .pixel_shader = ps ? ps->pgm_hash : 0, // bbport (r50_leaf-stage1)
        .glass_entry = dc.glass_hit, // bbport (r129a_glass-registry): 0 while the registry is off (S1 reads it)
    };
    // bbport (r50b_leaf-matcher): with BB_RT_CARD_ALPHA_LOG=1, the memory constants of a
    // matched cut-out pixel shader as this draw holds them (once per pgm_hash).
    static const bool cutout_log = Shader::Optimization::CutoutLogOn(); // (r54)
    if (cutout_log && shared_alpha) {
        LogCutoutConstants(regs, *ps, *memory, buffer_cache);
    }
    // bbport (r54_leaf-stage2): with BB_RT_CARD_ALPHA=1 (a capture pipeline with CaptureUv), a
    // cut-out pixel shader's card data as this draw holds it, for RtShadow::PrepareDraw (the
    // entry's UV capture). Kept on this stack until PrepareDraw returns: nothing is allocated.
    std::optional<CardDraw> card;
    const auto resolve_card = [&](bool cutout) {
        if ((mode & Shader::MotionVectors::CaptureUv) != 0 && ps && cutout &&
            (draw.camera_pass || draw.shadow_pass)) {
            card = ResolveCardDraw(regs, *ps, draw.camera_pass, *memory, buffer_cache);
            draw.card = &*card;
            // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA=2: the card's alpha layer
            if (card->valid && card_bound_on) {
                NoteCardLayer(*card, *ps);
            }
        }
    };

    auto* retire = ReflectionFirstRetire::Current(this);
    const auto stock_gate = [&](bool accepted, const char* name) {
        if (!accepted && retire) retire->candidate = name;
        return accepted;
    };
    const bool stock_candidate = stock_gate(original_stock_role != ReflectionDiscard::StockRole::None, "original-role") &&
        stock_gate(bool(dc.reflection_native), "native-probe") &&
        stock_gate(is_indexed, "not-indexed") &&
        stock_gate(draw.camera_pass, "non-camera") &&
        stock_gate(draw.solid, "non-solid") &&
        stock_gate(!draw.glass_entry, "glass-registry") &&
        stock_gate(draw.triangles, "non-triangle") &&
        stock_gate(!draw.strip, "strip") &&
        stock_gate(!draw.restart, "restart") &&
        stock_gate(draw.instances == 1, "instances") &&
        stock_gate(!first_vertex, "base-vertex") &&
        stock_gate(!first_instance, "first-instance") &&
        stock_gate(regs.depth_control.depth_enable, "depth-disabled") &&
        stock_gate(regs.depth_control.depth_func != AmdGpu::CompareFunc::Always, "depth-always") &&
        stock_gate(regs.color_target_mask.GetMask(0) == 0xf, "cb0-mask") &&
        stock_gate(pipeline->GetGraphicsKey().mrt_mask & 1u, "cb0-mrt") &&
        stock_gate(std::ranges::none_of(regs.blend_control, [](const auto& control) { return control.enable; }), "blend") &&
        stock_gate(ExactReflectionStages(*pipeline, *dc.reflection_native), "exact-stages") &&
        stock_gate(!surface_probe_on || !ReflectProbeHide(draw.shader, draw.pixel_shader, false, true,
                                               draw.index_count, index_offset, false), "surface-hide");
    const auto ready_stock = stock_candidate ? pipeline->HandleIfReady() : vk::Pipeline{};
    const auto stock_verdict = ready_stock
        ? pipeline->GetStockFragmentVerdict(pipeline_cache, original_stock_role, ready_stock)
        : ReflectionDiscard::Verdict::Unknown;
    const bool defer_card = stock_verdict != ReflectionDiscard::Verdict::Unknown;
    if (retire) {
        if (stock_candidate) retire->candidate = ready_stock ? "passed" : "pipeline-unready";
        retire->ready = std::bit_cast<u64>(ready_stock);
        retire->verdict = stock_verdict;
        retire->shared = shared_alpha;
        retire->defer_card = defer_card;
        retire->decision = defer_card ? "reflection-pass-unavailable" : "shared-untouched";
        retire->draw_flags |= u32(draw.camera_pass) | (u32(draw.shadow_pass) << 1) |
            (u32(draw.solid) << 2) | (u32(draw.triangles) << 3) | (u32(draw.strip) << 4) |
            (u32(draw.restart) << 5) | (u32(draw.glass_entry) << 6);
    }
    if (!defer_card) resolve_card(shared_alpha);
    if (fetch) {
        for (const auto& attribute : fetch->attributes) {
            if (attribute.semantic == 0) {
                const auto stream = attribute.GetSharp(vs);
                draw.positions = stream.base_address;
                draw.positions_size = stream.GetSize(); // bbport (r47c_review-fixes)
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
    // bbport (r47b_casters): a small bone palette in memory the GPU wrote is known by where it
    // lies, not by its bytes (see RtShadow::Draw::palette_placed). Experiment StillCheckOldBit
    // set: by its bytes in guest memory, as before.
    // bbport (r47c_review-fixes): nor with BB_RT_PALETTE_PLACE=0 (RtShadow::PalettePlace).
    const bool r47b_placed = !BbToggle::Experiment(StillCheckOldBit) && RtShadow::PalettePlace();
    if (is_indexed) {
        const VAddr address = regs.index_base_address.Address<VAddr>() + u64(index_offset) * index_size;
        const u64 bytes = u64(regs.num_indices) * index_size;
        r19_stats.motion_indices += r19_reuse ? 1u : 0u;
        if (r19_reuse ? r19_motion.indices_valid
                      : address && memory->IsValidGpuMapping(address, 0) &&
                            memory->ClampRangeSize(address, bytes) == bytes) {
            draw.indices = address;
            draw.lamp_affine_candidate =
                rt_shadow->LampAffineAvailable() && draw.camera_pass && draw.solid && !draw.alpha &&
                index_offset == 0 && first_vertex == 0 && first_instance == 0 &&
                draw.index_size == 2 && draw.triangles && !draw.strip && !draw.restart &&
                RtLampPane::Target(draw.shader, draw.pixel_shader, draw.index_count, draw.instances) &&
                !buffer_cache.IsRegionGpuModified(address, bytes);
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
                draw.skeleton_bones = std::max(draw.skeleton_bones, size / 48u); // bbport (r62n_cutout-skinned-blocker)
            } else if (role == Motion::BufferRole::SmallSkeleton && !r19_palette) {
                // (r19_palette: the Motion block hashed every palette of this draw, none of
                // them GPU-written)
                // bbport (r47c_review-fixes): not while the range is bound to the game's own
                // memory in place (BB_GUEST_IN_PLACE). There IsRegionGpuModified only says that
                // a write of the command stream is not done yet: the bytes in guest memory are
                // the palette's, and the answer changes with the GPU's progress (one prop would
                // be known by its address on one draw and by its bytes on the next). What the
                // GPU wrote for good is kept in VRAM, not in place.
                if (r47b_placed &&
                    buffer_cache.IsRegionGpuModified(buffer.base_address, size) &&
                    !buffer_cache.IsInPlace(buffer.base_address, size)) {
                    const std::array<u64, 2> place{buffer.base_address, size};
                    draw.palette = XXH3_64bits_withSeed(place.data(), sizeof(place), draw.palette);
                    draw.palette_placed = true;
                } else {
                    draw.palette = XXH3_64bits_withSeed(
                        reinterpret_cast<const void*>(buffer.base_address), size, draw.palette);
                }
            }
        }
    }
    if (r19_palette) { // bbport (r19_draw-cost)
        draw.palette = r19_motion.palette;
        ++r19_stats.motion_palettes;
    }
    if (BbWindHangFind::FindOn()) { // bbport (r112i_hang-find-lanterns): the survey's shader pairs
        BbWindHangFind::Seen noted;
        noted.vs = vs.pgm_hash;
        noted.ps = ps ? ps->pgm_hash : 0;
        noted.frame = object_motion->Frame();
        noted.indices = regs.num_indices;
        noted.skinned = draw.skinned;
        noted.palette = draw.palette != 0;
        noted.camera = draw.camera_pass;
        hang_find_draws.Note(draw.positions, noted);
    }
    // bbport (r76c_sun-fog-shells): with BB_VOLUMETRIC_GATE_PROBE=1 or BB_VOLUMETRIC_GATE_SHELLS set
    // (VolumetricOcclusion::GateCaptureOn, read once), what the guest registers say of this draw,
    // for the entry PrepareDraw takes it into: its shaders and pass, depth test, write and compare
    // function, culled faces, front face, z clip and whether the viewport depth clamp is on (as
    // the pipeline key's depth_clamp_enable), the depth range its viewport maps to (as the
    // rasterizer sets the Vulkan viewport: zoffset and zscale where enabled) and the depth clamp
    // bounds. Off: one test of a static bool.
    static const bool gate_capture = VolumetricOcclusion::GateCaptureOn();
    if (gate_capture) {
        VolumetricOcclusion::GateCapture cap;
        cap.vs = vs.pgm_hash;
        cap.ps = ps ? ps->pgm_hash : 0;
        cap.depth = VolumetricOcclusion::GateDepthBits(regs.depth_control.depth_enable != 0,
                                                       regs.depth_control.depth_write_enable != 0,
                                                       u32(regs.depth_control.depth_func));
        cap.raster = VolumetricOcclusion::GateRasterBits(
            regs.polygon_control.cull_front != 0, regs.polygon_control.cull_back != 0,
            regs.polygon_control.front_face == AmdGpu::FrontFace::Clockwise,
            regs.clipper_control.ZclipEnable(),
            !regs.depth_render_override.disable_viewport_clamp);
        const auto& viewport = regs.viewports[0];
        const float zoffset = regs.viewport_control.zoffset_enable ? viewport.zoffset : 0.0f;
        const float zscale = regs.viewport_control.zscale_enable ? viewport.zscale : 1.0f;
        cap.dmin = regs.clipper_control.clip_space == AmdGpu::ClipSpace::MinusWToW ? zoffset - zscale
                                                                                  : zoffset;
        cap.dmax = zoffset + zscale;
        cap.zmin = regs.viewport_depths[0].zmin;
        cap.zmax = regs.viewport_depths[0].zmax;
        cap.camera_pass = draw.camera_pass;
        cap.known = true;
        rt_shadow->SetGateCapture(cap);
    }
    if (trees_pick_glass) { // bbport (r86l_glint-pick-glass, TOOL): the glass pick keeps this draw's facts
        GlassPickStash(draw);
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
    // bbport (r83_glass-water-stage1): BB_RT_GLASS (rt_glass.h): a forward draw of a pair the knob
    // names has a capture pipeline only through it (PipelineCache::RefreshGraphicsKey). It goes
    // to PrepareDraw as a window pane (Draw::glass): drawn with the camera, solid and whole (its
    // blend and discard are the pane's look, not holes), static: one with a skeleton or a bone
    // palette is left out (neither pass, PrepareDraw takes nothing). Off: one test of a static bool.
    // bbport (r86g_glint-find-bottles): BB_GLASS_FIND=1: what the pane test of PrepareDraw says of
    // this pane draw (RtShadow::GlassVerdict, before the call) and the pane records counted before it
    // (an unset sample is never read: find_verdict stays RtGlassFind::Verdicts without the knob)
    static const bool glass_find = RtGlassFind::On();
    u32 find_verdict = RtGlassFind::Verdicts;
    u32 find_notes = 0;
    char find_sample[RtGlassFind::SampleMost];
    find_sample[0] = '\0';
    // bbport (r86i_glint-find-gbuffer): BB_GLASS_BOX_PANES=1: a G-buffer draw of a mesh the box rule took (static,
    // not skinned) is a pane too. Off: RtGlassOn() is false first, or no mesh was taken and GlassBoxMatch returns
    // at its first test.
    // bbport (r86k_glint-box-gbuffer): BB_GLASS_FIND=1 with a box set (RtShadow::GlassBoxCandidate): a G-buffer
    // draw PrepareDraw would give no entry (a discard, blended or without depth write) is given one as a pane, so
    // that the box listing sees it. Off: glass_find is false, nothing of this runs.
    bool box_cand = false;
    if (glass_find && draw.camera_pass && ps) {
        draw.find_flags = RtGlassFind::FlagGBuffer | (regs.blend_control[0].enable ? RtGlassFind::FlagBlend : 0u) |
                          (regs.depth_control.depth_write_enable != 0 ? RtGlassFind::FlagZWrite
                                                                      : RtGlassFind::FlagNoZWrite) |
                          (ps->has_discard ? RtGlassFind::FlagDiscard : 0u);
        box_cand = RtGlassOn() && rt_shadow->GlassBoxCandidate(draw, vs.pgm_hash, ps->pgm_hash,
                                                                draw.alpha || !draw.solid);
    }
    const bool box_pane = draw.camera_pass && ps && RtGlassOn() && rt_shadow->GlassBoxMatch(draw);
    u32 box_notes = 0; // bbport (r86j_glint-same-game): the pane records counted before PrepareDraw
    if (box_pane) {
        RtGlassFind::Chain().matched.fetch_add(1, std::memory_order_relaxed);
        box_notes = RtGlassProbe::Get().counts[RtGlassProbe::Note].load(std::memory_order_relaxed);
    }
    if (((!draw.camera_pass && !draw.shadow_pass) || box_pane || box_cand) && RtGlassOn()) {
        // bbport (r83b_glass-pane-probe): the named pair's draw at the test below (a skeleton,
        // a bone palette, or neither) and its vertex shader's buffers as the loop above read them
        // (size and stride; 864 = the camera constants), for the r83b line
        if (glass_hook) {
            RtGlassProbe::NoteStatic(draw.skinned, draw.palette != 0);
            std::array<u32, RtGlassProbe::BuffersMost * 2> glass_buffers{};
            u32 glass_kept = 0, glass_all = 0;
            for (const auto& resource : vs.buffers) {
                if (resource.IsSpecial()) {
                    continue;
                }
                ++glass_all;
                if (glass_kept < RtGlassProbe::BuffersMost) {
                    const auto buffer = resource.GetSharp(vs);
                    glass_buffers[glass_kept * 2] = buffer.GetSize();
                    glass_buffers[glass_kept * 2 + 1] = buffer.GetStride();
                    ++glass_kept;
                }
            }
            RtGlassProbe::NoteBuffers(glass_buffers.data(), glass_kept, glass_all);
        }
        // bbport (r121b_glass-pane-hang): BB_RT_GLASS_STATIC (default on with BB_RT_GLASS): only static world
        // geometry is a pane. Refused (counted by reason): a skeleton, a palette the GPU wrote (known by its
        // address: the held torch's), a vertex stream in GPU modified memory, a small palette that is not
        // finite. A pane instance that moves or is new is judged in PrepareDraw (RtGlassStatic::Judge). Evaluated only
        // for a draw that matched the pane tests; the knob off: the old test `!draw.skinned` alone.
        const auto glass_refused = [&]() -> bool {
            if (draw.skinned) {
                RtGlassStatic::Add(RtGlassStatic::Skinned);
                return true;
            }
            if (draw.palette_placed && // bbport (r130g_glass-light-forward): a registered pane may keep a placed palette
                !(draw.glass_placed = rt_shadow->GlassPlacedAllowed(draw.glass_entry))) {
                RtGlassStatic::Add(RtGlassStatic::PlacedPalette);
                return true;
            }
            if (draw.positions != 0 && draw.positions_size != 0 &&
                buffer_cache.IsRegionGpuModified(draw.positions, draw.positions_size) &&
                !buffer_cache.IsInPlace(draw.positions, draw.positions_size)) {
                RtGlassStatic::Add(RtGlassStatic::GpuStream);
                return true;
            }
            if (draw.palette != 0) {
                for (const auto& resource : vs.buffers) {
                    if (resource.IsSpecial()) {
                        continue;
                    }
                    const auto buffer = resource.GetSharp(vs);
                    const u32 size = buffer.GetSize();
                    if (!buffer.Valid() || buffer.GetStride() != 16 ||
                        !memory->IsValidGpuMapping(buffer.base_address, 0) ||
                        memory->ClampRangeSize(buffer.base_address, size) != size ||
                        Motion::ClassifyBuffer(size) != Motion::BufferRole::SmallSkeleton) {
                        continue;
                    }
                    if (!RtGlassStatic::Finite(reinterpret_cast<const float*>(buffer.base_address), size / 4u)) {
                        RtGlassStatic::Add(RtGlassStatic::NonFinite);
                        return true;
                    }
                }
            }
            return false;
        };
        // bbport (r83c_glass-pane-palette): a pane with a small palette (its world matrix comes from
        // a table of 48-byte matrices, 96 bytes at the dream house) is taken: PrepareDraw gives a
        // palette draw an entry per mesh and palette. A skinned draw (a larger table) is still left.
        if (ps && (RtGlassMatch(vs.pgm_hash, ps->pgm_hash) || glass_auto || box_pane || box_cand) &&
            (RtGlassStatic::On() ? !glass_refused() : !draw.skinned)) { // bbport (r121b_glass-pane-hang)
            draw.glass = true;
            draw.camera_pass = true;
            draw.solid = true;
            draw.alpha = false;
            draw.box_candidate = box_cand; // bbport (r86k_glint-box-gbuffer)
            // bbport (r86f_glass-static-panes): a static pane (the bottles, jars, windows: a vertex shader
            // without the 864-byte camera constants) takes the frame's main camera's constants, so that
            // PrepareDraw gives it an entry; a pane with constants of its own keeps them
            const bool find_own = draw.constants != nullptr; // bbport (r86g_glint-find-bottles)
            if (!draw.constants) {
                draw.constants = rt_shadow->GlassCamera();
            }
            glint_pending = glass_glint && !box_pane && !box_cand ? pipeline : nullptr; // bbport (r86b_glass-visible; r86k)
            if (box_pane && glass_glint) { // bbport (r86i_glint-find-gbuffer): its glint runs after the lighting
                glint_gpane = {.vs = vs.pgm_hash,
                               .ps = ps->pgm_hash,
                               .indices = regs.num_indices,
                               .instances = regs.num_instances.NumInstances()};
                glint_gpane_on = true;
                RtGlassFind::Chain().noted.fetch_add(1, std::memory_order_relaxed); // bbport (r86j)
            }
            if (glass_find) { // bbport (r86g_glint-find-bottles)
                find_verdict =
                    rt_shadow->GlassVerdict(draw, find_own, find_sample, sizeof(find_sample));
                find_notes = RtGlassProbe::Get().counts[RtGlassProbe::Note].load(
                    std::memory_order_relaxed);
            }
        } else if (glass_find && glass_hook) { // a pane draw with a skeleton buffer: left out by r83
            RtGlassFind::NoteVerdict(vs.pgm_hash, ps->pgm_hash, RtGlassFind::Skinned, nullptr);
        }
    }
    if (window_receiver && window_receiver->pane && !window_receiver->pending.request) {
        using namespace WindowPathProbe;
        auto& pane = *window_receiver->pane;
        const DrawKey key{draw.shader, draw.pixel_shader, draw.index_count, index_offset};
        if (key == WindowPaneDrawKey && draw.camera_pass) {
            const u64 frame = object_motion->Frame();
            if (!pane.tick && !pane.natural.Latched() && pane.source_frame != frame) {
                pane.source_frame = frame;
                pane.draw_count = 0;
                pane.param = 0;
                pane.refusal = nullptr;
            }
            const bool expired = pane.natural.Active() &&
                pane.natural.Expired(frame, ReceiverCapture::FrameBudget, NaturalPanePair::Clock::now());
            if (pane.source_frame == frame && ++pane.draw_count == 1 && !pane.tick && !expired &&
                !pane.natural.Latched()) {
                const u32 registry = ExactRegistry(GlassRegistryRules::Load(), key);
                const auto matrices = camera_motion->PassMatrices();
                const auto depth = camera_motion->Depth();
                const auto* image = depth ? texture_cache.TryGetImage(depth, 0) : nullptr;
                const auto render = camera_motion->RenderSize();
                const auto& request = window_receiver->request;
                const auto& viewport = regs.viewports[0];
                const float* constants = draw.constants;
                const auto jitter = upscaler->Enabled() ? upscaler->Jitter() : std::array<float, 2>{};
                if (!registry || dc.glass_hit != registry || !is_indexed || !draw.solid ||
                    draw.alpha || draw.skinned || draw.restart || draw.strip || !draw.indices ||
                    !image || db_desc.first != depth || !matrices.valid || trees_pick_rect_on ||
                    scene_targets->Reduced() || render[0] != request.width || render[1] != request.height ||
                    !constants || !std::equal(matrices.view.begin(), matrices.view.end(), constants + 8) ||
                    matrices.proj[0] != constants[52] * (viewport.xscale < 0.f ? -1.f : 1.f) ||
                    matrices.proj[1] != constants[57] * (viewport.yscale < 0.f ? -1.f : 1.f) ||
                    matrices.proj[2] != constants[62] || matrices.proj[3] != constants[63] ||
                    target_scale != std::array<float, 2>{1.f, 1.f} ||
                    target_offset != std::array<float, 2>{0.f, 0.f} ||
                    !std::isfinite(jitter[0]) || !std::isfinite(jitter[1]) ||
                    std::abs(jitter[0]) > 1.f || std::abs(jitter[1]) > 1.f) {
                    auto& stage = pane.stages;
                    const auto failed = [&](bool test, PaneStages::Guard bit) {
                        if (test) stage.guard |= bit;
                    };
                    failed(!registry || dc.glass_hit != registry, PaneStages::Registry);
                    failed(!is_indexed, PaneStages::NotIndexed);
                    failed(!draw.solid, PaneStages::NotSolid);
                    failed(draw.alpha, PaneStages::Alpha);
                    failed(draw.skinned, PaneStages::Skinned);
                    failed(draw.restart, PaneStages::Restart);
                    failed(draw.strip, PaneStages::Strip);
                    failed(!draw.indices, PaneStages::NoIndices);
                    failed(!image || db_desc.first != depth, PaneStages::DepthImage);
                    failed(!matrices.valid, PaneStages::InvalidCamera);
                    failed(trees_pick_rect_on, PaneStages::Scissored);
                    failed(scene_targets->Reduced(), PaneStages::Reduced);
                    failed(render[0] != request.width || render[1] != request.height, PaneStages::Extent);
                    failed(!constants, PaneStages::NoConstants);
                    if (constants) {
                        failed(!std::equal(matrices.view.begin(), matrices.view.end(), constants + 8),
                               PaneStages::View);
                        failed(matrices.proj[0] != constants[52] * (viewport.xscale < 0.f ? -1.f : 1.f) ||
                               matrices.proj[1] != constants[57] * (viewport.yscale < 0.f ? -1.f : 1.f) ||
                               matrices.proj[2] != constants[62] || matrices.proj[3] != constants[63],
                               PaneStages::Projection);
                    }
                    failed(target_scale != std::array<float, 2>{1.f, 1.f} ||
                           target_offset != std::array<float, 2>{0.f, 0.f}, PaneStages::TargetTransform);
                    failed(!std::isfinite(jitter[0]) || !std::isfinite(jitter[1]) ||
                           std::abs(jitter[0]) > 1.f || std::abs(jitter[1]) > 1.f, PaneStages::Jitter);
                    stage.Refuse("pane-admission-guard", frame, rt_shadow->WindowDiagnosticFrame());
                    pane.refusal = "exact registry, native camera/attachment or static triangle draw unavailable";
                } else {
                    pane.depth_uid = image->image_uid;
                    pane.camera = {matrices.view, matrices.inv_view, matrices.proj};
                    pane.jitter = jitter;
                    draw.window_pane_observe = true;
                    PaneStages::Count(pane.stages.observed);
                }
            } else if (pane.source_frame == frame && pane.draw_count > 1) {
                pane.stages.guard |= PaneStages::Duplicate;
                pane.stages.Refuse("duplicate-exact-draw", frame, rt_shadow->WindowDiagnosticFrame());
                pane.refusal = "multiple exact indexed pane draws in the sampled frame";
            }
        }
    }
    if (bottle_caustic && BottleCaustic::On() && BottleCaustic::ExactDraw(
            draw.shader, draw.pixel_shader, index_offset, draw.index_count) &&
        bottle_caustic->Capturing(db_desc.first) && draw.camera_pass && is_indexed && rt_shadow->TryBottleDraw() &&
        draw.solid && !draw.glass && !draw.alpha && !draw.skinned && draw.triangles && !draw.strip && !draw.restart &&
        draw.index_size == 4 && draw.instances == 1 && draw.indices &&
        (draw.indices % alignof(u32) == 0) &&
        !buffer_cache.IsRegionGpuModified(draw.indices, u64(draw.index_count) * sizeof(u32))) {
        draw.bottle_candidate = true;
        draw.bottle_delivery = &bottle;
    }
    if (auto* pane = rt_shadow->ActiveLampPane()) {
        draw.lamp_pane_observe = LampPaneDraw(*pane, regs, pipeline, is_indexed, index_offset, draw);
    }
    auto* retry = dc.reflection_native && dc.reflection_native->stamp_retry &&
                  !dc.reflection_native->stamp_retry->attempted
        ? &*dc.reflection_native->stamp_retry : nullptr;
    const bool current_stamp = reflection_probe && gbuffer_draw && is_indexed && ReflectionStamp(regs);
    if (retry) {
        auto& note = *dc.reflection_native;
        retry->attempted = true;
        retry->reporting = ClaimStampRetryTrace(this, *retry);
        retry->failure = !current_stamp ? "pass-unpublished" :
            note.trace ? "tracing-draw" : note.stamped ? "already-stamped" :
            note.placement_safe ? "already-safe" :
            note.key != ReflectionNativeProbe::Key{draw.shader, draw.pixel_shader, draw.index_count, index_offset}
                ? "draw-key-changed" :
            original_stock_role != ReflectionDiscard::StockRole::Fireplace || !stock_candidate
                ? "original-candidate" :
            !ready_stock ? "pipeline-unready" :
            stock_verdict == ReflectionDiscard::Verdict::DiscardPresent ? "positive-discard" :
            stock_verdict != ReflectionDiscard::Verdict::CertifiedClear ? "stock-uncertified" :
            draw.glass || draw.glass_entry ? "glass" :
            draw.skinned || draw.skeleton_bones ? "skinned" :
            !draw.palette_placed || !draw.palette ? "palette-unplaced" :
            ReflectionNativeProbe::RetryStampRefusal(*retry, *reflection_probe->stamp);
        if (!retry->failure) {
            retry->current = true;
            // The validator still owns stamping and the normal placement-safety bit.
            // This marker cannot take its tracing branch or arm again.
            ReflectionNativeBeforeDraw(note);
            retry->safe = note.stamped && note.placement_safe;
            if (!retry->safe && !retry->failure) {
                retry->failure = StampRetryValidatorRefusal(retry->validator_reject);
            }
        }
    }
    if (current_stamp) {
        if (dc.reflection_native && dc.reflection_native->stamped &&
            dc.reflection_native->stamp == *reflection_probe->stamp) {
            draw.reflection_native = dc.reflection_native;
        }
        if (retire) {
            const auto& stamp = *reflection_probe->stamp;
            retire->generation = stamp.generation;
            retire->frame = stamp.frame;
            retire->pass = stamp.pass;
            retire->depth_uid = stamp.depth_uid;
            retire->cb0_uid = stamp.cb0_uid;
            retire->stamped = stamp.valid_native;
            if (draw.reflection_native) retire->palette.flags |= 1u;
            if (defer_card) {
                retire->decision = draw.glass ? "glass" : !draw.palette_placed ? "palette-unplaced" :
                    !draw.palette ? "palette-empty" : draw.skinned ? "skinned" :
                    draw.skeleton_bones ? "skeleton-bones" :
                    !draw.reflection_native ? "native-stamp-unjoined" : "palette-binding-refused";
            }
        }
        if (defer_card && !draw.glass && draw.palette_placed && draw.palette &&
            !draw.skinned && !draw.skeleton_bones && draw.reflection_native) {
            const auto* placement = ReflectionNativeProbe::PlacedBinding(*draw.reflection_native);
            if (retire && placement) {
                retire->palette.flags |= 1u << 8;
                retire->decision = "palette-handle-mismatch";
            }
            if (placement && placement->buffer->Handle() == placement->handle) {
                classified_stock = ready_stock;
                draw.alpha = ReflectionDiscard::EffectiveAlpha(stock_verdict, shared_alpha);
                if (retire) {
                    retire->palette.flags |= 1u << 9;
                    retire->decision = stock_verdict == ReflectionDiscard::Verdict::CertifiedClear
                        ? "certified-clear-applied" : "positive-discard-applied";
                }
                if (ReflectionJoinTraceOn()) {
                    const auto& stamp = *reflection_probe->stamp;
                    const auto& key = draw.reflection_native->key;
                    TraceReflectionJoin(JoinTarget(key.vs, key.ps, key.count, key.first), stamp.frame,
                        reflection_probe->last_request, key.vs, key.ps, key.count,
                        index_offset, "fragment-classification", shared_alpha ? "shared-discard-1"
                                                                             : "shared-discard-0",
                        regs, pipeline->GetGraphicsKey().mrt_mask, &draw);
                }
            }
        }
        if (defer_card) resolve_card(classified_stock ? draw.alpha : shared_alpha);
        if (draw.palette_placed && JoinCount(draw.index_count) && ReflectionFirstHit::PlacedOn()) {
            const auto role = ReflectionNativeProbe::Match({draw.shader, draw.pixel_shader,
                                                           draw.index_count, index_offset});
            if (ReflectionInputsFor(role) && (!draw.reflection_native ||
                    !ReflectionNativeProbe::PlacedBinding(*draw.reflection_native))) {
                TraceReflectionPlacedRefusal(role, reflection_probe->last_request, *reflection_probe->stamp,
                                             dc.reflection_native);
            }
        }
        if (ReflectionCapture(regs, *pipeline, draw, index_offset, reflection)) {
            draw.reflection = &reflection;
            if (retire) retire->capture = "accepted";
        }
    } else if (defer_card) {
        resolve_card(shared_alpha);
    }

    if (retire) {
        retire->effective = draw.alpha;
        retire->placement = reflection.placement;
        if (dc.reflection_native) {
            const auto& native = *dc.reflection_native;
            retire->palette.count = native.binding_count;
            retire->palette.flags |= (u32(native.placement_safe) << 1) | (u32(native.overflow) << 2);
            for (const auto& binding : std::span{native.bindings}.first(native.binding_count)) {
                if (binding.ordinal != 1) continue;
                retire->palette.buffer = std::bit_cast<u64>(binding.handle);
                retire->palette.offset = binding.descriptor_offset;
                retire->palette.range = binding.descriptor_range;
                retire->palette.guest = binding.guest;
                retire->palette.ordinal = binding.ordinal;
                retire->palette.slot = binding.slot;
                retire->palette.adjust = binding.adjust;
                retire->palette.guest_bytes = binding.guest_bytes;
                retire->palette.effective_bytes = binding.effective_bytes;
                retire->palette.flags |= (u32(binding.range_known) << 3) | (u32(binding.gpu_dirty) << 4) |
                    (u32(binding.in_place) << 5) | (u32(binding.writable) << 6) |
                    (u32(bool(binding.buffer)) << 7);
            }
        }
    }
    BbSections::Scope prepare_scope{BbSections::RtPrepare};
    const u32 param = rt_shadow->PrepareDraw(draw);
    prepare_scope.End();
    if (retire) {
        retire->cookie = reflection.cookie;
        retire->allocation = reflection.allocation;
    }
    if (retry) {
        retry->alpha = draw.alpha;
        retry->classified = ready_stock && classified_stock == ready_stock;
        if (!retry->failure) {
            retry->failure = !retry->classified ? "classification-unjoined" :
                !draw.reflection || !reflection.placement ? "capture-unjoined" :
                !reflection.cookie ? "entry-unjoined" : "none";
        }
        TraceStampRetry(retry->safe ? "prepared" : "refused", this, *retry,
                        current_stamp ? &*reflection_probe->stamp : nullptr,
                        scheduler.CurrentTick(), reflection);
    }
    if (draw.reflection && reflection.placed != ReflectionFirstHit::PlacedSource::None) {
        FinishPlacementSample(*reflection_probe->stamp, reflection, param);
        if (auto* proof = OrdinalZeroFor(*draw.reflection_native)) {
            proof->param = param;
        }
    }
    if (draw.reflection && JoinCount(draw.index_count) && ReflectionJoinTraceOn()) {
        TraceReflectionJoin(JoinTarget(draw.shader, draw.pixel_shader, draw.index_count, index_offset),
                            rt_shadow->WindowDiagnosticFrame(), reflection_probe->last_request,
                            draw.shader, draw.pixel_shader, draw.index_count, index_offset,
                            "prepare", reflection.cookie ? "entry-joined" : "no-entry-join", regs,
                            pipeline->GetGraphicsKey().mrt_mask, &draw, param,
                            reflection.cookie != 0);
    }
    if (draw.window_pane_observe && window_receiver && window_receiver->pane &&
        window_receiver->pane->natural.Latched() && !window_receiver->pane->refusal) {
        rt_shadow->WatchWindowScene(&window_receiver->scene);
    }
    if (box_pane) { // bbport (r86j_glint-same-game): did the box pane get its record
        const bool made = RtGlassProbe::Get().counts[RtGlassProbe::Note].load(std::memory_order_relaxed) != box_notes;
        (made ? RtGlassFind::Chain().recorded : RtGlassFind::Chain().not_recorded)
            .fetch_add(1, std::memory_order_relaxed);
    }
    if (find_verdict != RtGlassFind::Verdicts && ps) { // bbport (r86g_glint-find-bottles)
        u32 found = find_verdict;
        if (found == RtGlassFind::Pane &&
            RtGlassProbe::Get().counts[RtGlassProbe::Note].load(std::memory_order_relaxed) ==
                find_notes) {
            found = RtGlassFind::Dropped; // passed the tests, no record came (budget, MakeEntry)
        }
        RtGlassFind::NoteVerdict(vs.pgm_hash, ps->pgm_hash, RtGlassFind::Verdict(found), find_sample);
    }
    if (Shader::MotionVectors::Kind(mode) == Shader::MotionVectors::VertexBoth) {
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

// bbport (r96_lamp-flicker-colour): BB_LAMP_FLICKER (lamp_flicker.h). For a light draw whose pixel
// stage reads `count` lamp records at `lights` (its buffer 1), after the draw's buffers are bound
// (BindResources) and before the pipeline writes its descriptors (after EffectsBeforeBind): when a
// lamp of the draw flickers this frame, buffer 1 is bound to a copy in the stream buffer of the
// binding's bytes with the records patched, at the same push offset, and the patched records are
// returned for the lamp shadow pass and the lamp fog. The bytes come from guest memory, which
// PointShadow::OnLightDraw and the lamp fog read for these records too; the constant ring is never
// read by the CPU (device memory mapped for sequential writes: a read of it is uncached and slow)
// nor written here. A ring binding is copied only when it is stage A's copy of exactly these
// bytes. Host writes only: no command is recorded, so no lamps-apart batch is ended. Null: the
// draw stays as the game made it (nothing flickers in it, or the binding is not one this copies:
// counted in the "Lamp flicker (r96)" line; one that would take more than MostCopyBytes turns the
// flicker off for the session).
const u32* Rasterizer::LampFlickerBind(const GraphicsPipeline* pipeline, const Shader::Info& ps,
                                       VAddr lights, u32 count) {
    auto& flicker = LampFlicker::Get();
    auto& dc = Dc();
    // Buffer bindings are numbered across the stages in GetStages() order (BindResources, and
    // Info::AddBindings for the shaders); dc.buffer_infos and the push offsets use those numbers.
    u32 index = 0;
    bool found = false;
    for (const auto* stage : pipeline->GetStages()) {
        if (stage == &ps) {
            found = true;
            break;
        }
        index += stage ? u32(stage->buffers.size()) : 0u;
    }
    ++index; // the records are the pixel stage's buffer 1
    const u64 bytes = u64(count) * 64;
    if (!found || ps.buffers.size() < 2 || ps.buffers[1].IsSpecial() ||
        index >= dc.buffer_infos.size() || index >= dc.push_data.buf_offsets.size()) {
        flicker.Skipped(LampFlicker::Skip::Binding);
        return nullptr;
    }
    auto& info = dc.buffer_infos[index];
    const u64 adjust = dc.push_data.buf_offsets[index];
    const u64 range = info.range;
    const u64 size = ps.buffers[1].GetSharp(ps).GetSize();
    if (!info.buffer || range == VK_WHOLE_SIZE || range < adjust + bytes || range > size + adjust) {
        flicker.Skipped(LampFlicker::Skip::Binding);
        return nullptr;
    }
    if (range > LampFlicker::MostCopyBytes || flicker.TooLarge()) {
        flicker.Skipped(LampFlicker::Skip::Large);
        return nullptr;
    }
    const RingBinding* ring = dc.num_ring_stages ? FindRingBinding(ps, 1) : nullptr;
    if (ring && (info.buffer != constant_ring->Handle() || info.offset != ring->Offset() ||
                 adjust != 0 || ring->address != lights || range > ring->size)) {
        flicker.Skipped(LampFlicker::Skip::Binding);
        return nullptr;
    }
    if (memory->ClampRangeSize(lights, range - adjust) != range - adjust ||
        buffer_cache.IsRegionGpuModified(lights, range - adjust)) {
        flicker.Skipped(LampFlicker::Skip::GpuWritten);
        return nullptr;
    }
    const auto camera = camera_motion->PassMatrices();
    const u32* patched =
        flicker.PatchDraw(reinterpret_cast<const void*>(lights), reinterpret_cast<const u32*>(lights),
                          count, camera.valid ? camera.inv_view.data() : nullptr);
    if (!patched) {
        return nullptr;
    }
    const u64 alignment =
        std::max<u64>(instance.UniformMinAlignment(), instance.StorageMinAlignment());
    auto& stream = buffer_cache.GetStreamBuffer();
    const auto [data, at] = stream.Map(range, alignment);
    if (!data) {
        flicker.Skipped(LampFlicker::Skip::Stream);
        return nullptr;
    }
    std::memset(data, 0, adjust);
    memory->CopySparseMemory(lights, data + adjust, range - adjust);
    std::memcpy(data + adjust, patched, bytes);
    stream.Commit();
    info.buffer = stream.Handle();
    info.offset = at;
    info.range = range;
    flicker.Bound();
    return patched;
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
            const auto& ps = pipeline->GetStage(Shader::SwStage::Fragment);
            // The shader's constant word 0 is the sharp's base address (buf_offsets[0] is only
            // the alignment remainder the shader adds to the aligned binding). Copy the floats
            // Bend's CPU dispatch layout needs now: Flush runs after the blur draw, by which
            // time the game may have reused this memory.
            const VAddr constants = !ps.buffers.empty() && !ps.buffers[0].IsSpecial()
                                        ? ps.buffers[0].GetSharp(ps).base_address
                                        : 0;
            ContactShadow::Inputs inputs{
                 .constants = dc.buffer_infos[0].buffer,
                 .constants_offset = dc.buffer_infos[0].offset,
                 .constants_range = dc.buffer_infos[0].range,
                 .uniforms = has_ubo ? dc.buffer_infos[1].buffer : vk::Buffer{},
                 .uniforms_offset = has_ubo ? dc.buffer_infos[1].offset : 0,
                 .uniforms_range = has_ubo ? dc.buffer_infos[1].range : 0,
                 .shadow_map = has_map ? dc.image_infos[1].imageView : vk::ImageView{},
                 .shadow_layout = has_map ? dc.image_infos[1].imageLayout : vk::ImageLayout::eUndefined,
                 .constants_offset_word = PackedOffsets(dc.push_data),
                 .frame_index = shadow_frame++};
            constexpr u64 bytes = sizeof(inputs.constants_cpu);
            if (constants && memory->IsValidGpuMapping(constants, bytes) &&
                memory->ClampRangeSize(constants, bytes) == bytes) {
                std::memcpy(inputs.constants_cpu.data(), reinterpret_cast<const void*>(constants),
                            bytes);
                inputs.has_constants_cpu = true;
            }
            contact_shadow->OnShadowDraw(cb_descs[0].first, inputs);
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
                if (surface_probe_on) { // bbport (r64_surface-probe): the lamps of this tile, logged
                    SurfaceProbeLamps(reinterpret_cast<const u32*>(lights), tile_lights);
                }
                if (heat_haze) { // bbport (r97_heat-haze): the flames among this tile's lamps
                    heat_haze->AddLights(reinterpret_cast<const u32*>(lights), tile_lights);
                }
                // bbport (r96_lamp-flicker-colour): BB_LAMP_FLICKER only (off: one bool test)
                const u32* flickered =
                    LampFlicker::On() ? LampFlickerBind(pipeline, ps, lights, tile_lights) : nullptr;
                // bbport (r98c_particles-visible): the lamps the ambient motes take light from
                if (ambient_particles && ambient_particles->LampsWanted()) {
                    ambient_particles->AddLamps(
                        flickered ? flickered : reinterpret_cast<const u32*>(lights), tile_lights);
                }
                if (bottle_caustic && BottleCaustic::On() && rt_shadow->BottleObserved()) {
                    bottle_caustic->AddLights(flickered ? flickered : reinterpret_cast<const u32*>(lights),
                                             tile_lights);
                }
                // bbport (r107b_caustics-visible): the lamps the water caustics reflect (as drawn)
                if (caustics && caustics->LampsWanted()) {
                    caustics->AddLights(flickered ? flickered : reinterpret_cast<const u32*>(lights),
                                        tile_lights);
                }
                point_shadow->OnLightDraw(cb_descs[0].first, cb_descs[1].first,
                                          {.constants = reinterpret_cast<const u32*>(constants),
                                           .lights = flickered ? flickered
                                                               : reinterpret_cast<const u32*>(lights),
                                           .count = tile_lights,
                                           .tile = effect_tile,
                                           .adds_in_tile = adds_in_tile,
                                           .pass = effect_pass,
                                           // bbport (r71_lamp-target-log): logged on a skip only
                                           .ps_hash = hash,
                                           .mrt_mask = pipeline->GetGraphicsKey().mrt_mask});
                if (glass_glint) { // bbport (r86b_glass-visible): the lamps of its glints (as drawn)
                    glass_glint->AddLights(flickered ? flickered : reinterpret_cast<const u32*>(lights),
                                           tile_lights);
                }
                if (foliage_glow) { // bbport (r131a_foliage-translucency): the lamps the back-lit glow takes (as drawn)
                    foliage_glow->AddLights(flickered ? flickered : reinterpret_cast<const u32*>(lights), tile_lights);
                }
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


bool Rasterizer::SampleWindowOwner(const RenderState& state, const LampMaterialDelivery& draw, bool after) {
    using namespace WindowPathProbe;
    using namespace RtLampPane;
    auto& capture = *window_receiver;
    auto& pane = *capture.pane;
    auto& owner = *pane.owner;
    const auto& build = pane.natural.build;
    const auto& regs = Regs();
    const auto* ps = draw.original->GetStages()[u32(Shader::SwStage::Fragment)];
    if (!pane.natural.Latched() || pane.refusal || !draw.indexed || !ps ||
        DrawKey{draw.original->GetStage(Shader::SwStage::Vertex).pgm_hash, ps->pgm_hash,
                regs.num_indices, draw.first} != WindowPaneDrawKey ||
        build.object_frame != object_motion->Frame() || build.rt_frame != rt_shadow->WindowDiagnosticFrame() ||
        !pane.natural.MatchBuild(build.rt_frame, pane.param, build.ordinal, pane.key) ||
        pane.draw_count != 1 || owner.material.refusal) {
        return false;
    }
    const auto& depth_attachment = state.depth_stencil_attachment;
    if (state.num_color_attachments <= 2 || Dc().clear_draw ||
        state.color_attachments[2].is_clear || depth_attachment.depth_clear ||
        depth_attachment.stencil_clear) {
        std::printf("Window pane owner (t132f): req=%u pre-sample attachments=%u glass-clear=%u "
                    "albedo-clear=%u depth-clear=%u stencil-clear=%u albedo-view=%u gbuffer=%u\n",
                    capture.request.id, u32(state.num_color_attachments), u32(Dc().clear_draw),
                    u32(state.color_attachments[2].is_clear), u32(depth_attachment.depth_clear),
                    u32(depth_attachment.stencil_clear),
                    u32(bool(state.color_attachments[2].image_view)), u32(gbuffer_draw));
        owner.material.refusal = "selected draw clears or has no albedo attachment";
        return false;
    }
    // Scope is the single 1920x1080 church texel, no display scaling.
    constexpr RawDrawPixel pixel{1003, 281};
    const auto scissor = DrawScissor(0);
    const auto contains = [](u32 value, s32 start, u32 extent) {
        return s64(value) >= start && s64(value) - start < extent;
    };
    if (state.width != capture.request.width || state.height != capture.request.height ||
        !gbuffer_draw || !contains(pixel.x, scissor.offset.x, scissor.extent.width) ||
        !contains(pixel.y, scissor.offset.y, scissor.extent.height)) {
        owner.material.refusal = "selected texel not inside native G-buffer draw";
        return false;
    }
    // This is the request-local draw ordinal. 'build.ordinal' is a different identity.
    const Identity stamp{capture.request.id, owner.draws_before + 1, build.ordinal, db_desc.first.index,
                         build.object_frame, build.rt_frame, pane.depth_uid};
    if (!after) owner.stamp = stamp;
    DrawRawRead read{owner.material, stamp, pane.camera, pane.jitter, std::span(&pixel, 1),
                     owner.buffer, [&] { return owner.Allocate(); }, 0, capture.request.width,
                     capture.request.height, owner.stamp.draw, draw.first, draw.base, draw.first_instance,
                     WindowPaneDrawKey.vs, WindowPaneDrawKey.ps, WindowPaneDrawKey.count, pane.instances, true};
    if (!SampleDrawRaw(read, state, draw, after)) return false;
    if (after) {
        u32 i = 0;
        for (const auto target : {RawAlbedo, RawDepth}) {
            const auto& source = owner.material.sources[target].backing;
            const auto* image = texture_cache.TryGetImage(VideoCore::ImageId{source.id}, source.uid);
            if (!image) {
                owner.material.refusal = "selected attachment disappeared after draw";
                return false;
            }
            owner.after_writes[i++] = image->write_seq;
        }
    }
    return true;
}

void Rasterizer::NoteWindowOwnerTargets(const GraphicsPipeline* pipeline) {
    using namespace RtLampPane;
    using WindowPathProbe::PaneOwnerGap;
    auto& owner = *window_receiver->pane->owner;
    if (owner.final_tick || owner.material.refusal) return;
    if (!owner.material.phases.after_tick) {
        // Count only while the cold acquisition is active. The trigger itself may
        // precede construction of this optional observer.
        ++owner.draws_before;
        return;
    }
    if (object_motion->Frame() != owner.stamp.scene) return;
    if (owner.draws_after == 4096) {
        if (NoteWindowOwnerGap(PaneOwnerGap::DrawCap)) {
            LogWindowOwnerGap("draw-cap", "limit=4096");
        }
        return;
    }
    ++owner.draws_after;
    if (owner.first_writer) return;
    const auto& key = pipeline->GetGraphicsKey();
    const auto& regs = Regs();
    const auto possible = [&](const RenderTargetInfo& target, const char* attachment, u32 slot) {
        const auto& [id, desc] = target;
        if (!id) return false;
        const auto* image = texture_cache.TryGetImage(id, 0);
        if (!image || !image->backing || image->guest_end <= image->guest_begin ||
            !image->GetImage()) {
            if (NoteWindowOwnerGap(PaneOwnerGap::NonresidentTarget)) {
                const char* reason = "no-vk-image";
                if (!image) {
                    reason = "missing-image";
                } else if (!image->backing) {
                    reason = "no-backing";
                } else if (image->guest_end <= image->guest_begin) {
                    reason = "invalid-range";
                }
                const auto& range = desc.view_info.range;
                LogWindowOwnerGap("nonresident-target",
                                  fmt::format("attachment={} slot={} id={} uid={} reason={} "
                                              "dst={:#x}+{:#x} stencil-dst={:#x} mip={} layer={} layers={}",
                                              attachment, slot, id.index, image ? image->image_uid : 0,
                                              reason, desc.info.guest_address, desc.info.guest_size,
                                              desc.info.stencil_addr, range.base.level, range.base.layer,
                                              range.extent.layers).c_str());
            }
            return false;
        }
        const MaterialBacking write{
            .image = std::bit_cast<u64>(VkImage(image->GetImage())),
            .backing = u64(reinterpret_cast<std::uintptr_t>(image->backing)),
            .begin = image->guest_begin, .end = image->guest_end,
            .stencil_begin = image->info.stencil_addr,
            .stencil_end = image->info.stencil_addr + image->info.stencil_size,
            .id = id.index, .uid = image->image_uid,
        };
        return MaterialAlias(write, owner.material.sources[RawAlbedo].backing) ||
               MaterialAlias(write, owner.material.sources[RawDepth].backing);
    };
    for (u32 slot = 0; slot < cb_descs.size(); ++slot) {
        if ((key.mrt_mask & (1u << slot)) && possible(cb_descs[slot], "color", slot)) {
            owner.first_writer = owner.stamp.draw + owner.draws_after;
            return;
        }
    }
    const bool clear = regs.depth_render_control.depth_clear_enable;
    const bool depth_write = regs.depth_control.depth_enable && regs.depth_control.depth_write_enable;
    if ((clear || depth_write) && possible(db_desc, "depth", 0)) {
        owner.first_writer = owner.stamp.draw + owner.draws_after;
        owner.later_clear = clear;
    }
}

bool Rasterizer::NoteWindowOwnerGap(WindowPathProbe::PaneOwnerGap kind) {
    auto& owner = *window_receiver->pane->owner;
    // Compute/copy/clear paths can use aliases whose targets are not in cb_descs or db_desc.
    if (!owner.final_tick && owner.material.phases.after_tick && object_motion->Frame() == owner.stamp.scene) {
        owner.coverage_gap = true;
        const auto bit = static_cast<u8>(kind);
        if (owner.logged_gap_kinds & bit) return false;
        owner.logged_gap_kinds |= bit;
        return true;
    }
    return false;
}

void Rasterizer::LogWindowOwnerGap(const char* kind, const char* identity) {
    const auto& owner = *window_receiver->pane->owner;
    std::printf("Window pane owner gap (t132f): req=%u obj=%llu rt=%llu selected=%u later=%u "
                "kind=%s %s\n",
                window_receiver->request.id, static_cast<unsigned long long>(owner.stamp.scene),
                static_cast<unsigned long long>(owner.stamp.rt), owner.stamp.draw, owner.draws_after,
                kind, identity);
}

void Rasterizer::FinalWindowOwner(u64 directional, u64 depth_uid, u64 depth_tick) {
    using namespace RtLampPane;
    auto& owner = *window_receiver->pane->owner;
    if (owner.material.refusal || owner.final_tick) return;
    if (!owner.material.phases.Complete(owner.stamp) ||
        !SameDepth(owner.stamp, window_receiver->request.id, object_motion->Frame(),
                   db_desc.first.index, depth_uid) ||
        owner.stamp.rt != rt_shadow->WindowDiagnosticFrame() || !depth_tick) {
        owner.material.refusal = "A/B not delivered on the exact directional sample frame";
        return;
    }
    std::array<VideoCore::Image*, MaterialTargets> images{};
    u32 i = 0;
    for (const auto target : {RawAlbedo, RawDepth}) {
        const auto& saved = owner.material.sources[target];
        const auto id = VideoCore::ImageId{saved.backing.id};
        auto* image = texture_cache.TryGetImage(id, saved.backing.uid);
        if (!image || !image->backing || !texture_cache.IsRegisteredImage(id, saved.backing.uid) ||
            image->binding.needs_rebind || image->scene_proxy || scene_targets->Tracks(saved.backing.uid) ||
            scene_targets->NativeStale(*image) ||
            std::bit_cast<u64>(VkImage(image->GetImage())) != saved.backing.image ||
            u64(reinterpret_cast<std::uintptr_t>(image->backing)) != saved.backing.backing ||
            image->guest_begin != saved.backing.begin || image->guest_end != saved.backing.end ||
            !image->backing->subresource_states.empty() ||
            image->backing->image.image_ci.format != saved.created_format ||
            image->backing->state.layout == vk::ImageLayout::eUndefined) {
            owner.material.refusal = "final attachment lost exact native image or subresource identity";
            return;
        }
        const auto exact_view = [&](auto view_id) {
            const auto& view = texture_cache.GetImageView(view_id);
            return view.image_view.get() == saved.view && view.info == saved.info;
        };
        if (!std::ranges::any_of(image->backing->image_view_ids, exact_view)) {
            owner.material.refusal = "final attachment lost native view";
            return;
        }
        owner.final_writes[i++] = image->write_seq;
        if (target == RawAlbedo) images[target] = image;
    }
    // DirectionalReadback has already ended the pass and copied C-depth.
    // No other guest command can be inserted between those samples.
    constexpr RawDrawPixel pixel{1003, 281};
    std::array<u64, MaterialTargets> offsets{};
    offsets[RawAlbedo] = RawFinalAlbedo;
    owner.directional = directional;
    owner.final_depth_tick = depth_tick;
    owner.final_tick = scheduler.CurrentTick();
    RecordDrawRaw(images, std::span(&pixel, 1), vk::Buffer{owner.buffer}, offsets);
}

void Rasterizer::CaptureWindowReceiver(const AmdGpu::Regs& regs, u64 ps_hash) {
    using namespace WindowPathProbe;
    auto& capture = *window_receiver;
    if (capture.pending.request ||
        (capture.pane && !capture.pane->CanSample(capture.request.id, object_motion->Frame(),
                                         rt_shadow->WindowDiagnosticFrame(), ReceiverCapture::FrameBudget))) {
        return;
    }
    if (!camera_motion->Enabled() || scene_targets->Reduced() || ui_pass.active ||
        !db_desc.first || db_desc.first != camera_motion->Depth() ||
        !regs.depth_control.depth_enable || regs.depth_control.depth_write_enable ||
        regs.depth_render_control.depth_clear_enable || target_scale[0] != 1.f || target_scale[1] != 1.f ||
        target_offset[0] != 0.f || target_offset[1] != 0.f || !cb_descs[0].first || !capture.set_id) {
        capture.refusal = "original native depth or bound directional light-set unavailable";
        return;
    }
    auto* depth = texture_cache.TryGetImage(db_desc.first, 0);
    auto* sets = texture_cache.TryGetImage(capture.set_id, capture.set_uid);
    auto* output = texture_cache.TryGetImage(cb_descs[0].first, 0);
    const auto render = camera_motion->RenderSize();
    const auto scissor = DrawScissor(0);
    const auto matrices = camera_motion->PassMatrices();
    if (!depth || !sets || !output || !matrices.valid || !capture.ordinal ||
        !object_motion->Frame() || !output->image_uid ||
        render[0] != capture.request.width || render[1] != capture.request.height ||
        output->info.size.width != render[0] || output->info.size.height != render[1] ||
        scissor.offset.x != 0 || scissor.offset.y != 0 ||
        scissor.extent.width != render[0] || scissor.extent.height != render[1]) {
        capture.refusal = "directional draw identity, native render size or full scissor unavailable";
        return;
    }
    if (capture.pane && capture.pane->natural.Active() &&
        !capture.pane->SameSampleState(depth->image_uid, {matrices.view, matrices.inv_view, matrices.proj},
            upscaler->Enabled() ? upscaler->Jitter() : std::array<float, 2>{})) {
        capture.refusal = "natural pane sample camera, jitter or depth identity changed";
        capture.pane->stages.Refuse(capture.refusal, object_motion->Frame(), rt_shadow->WindowDiagnosticFrame());
        return;
    }
    const u64 view = XXH3_64bits(matrices.view.data(), sizeof(matrices.view));
    const u64 stamp = XXH3_64bits_withSeed(matrices.proj.data(), sizeof(matrices.proj), view);
    // Generation remains zero for this independent receiver lookup. It does
    // not claim a guarded scene association or a measured contribution.
    const DirectionalSource source{
        .stamp = {capture.request.id, object_motion->Frame(), 0, stamp, depth->image_uid},
        .fragment_hash = ps_hash, .draw = capture.ordinal, .set_uid = sets->image_uid,
        .output_uid = output->image_uid, .width = render[0], .height = render[1], .matched_native_inputs = true,
    };
    const auto result = capture.copy.Submit(source, capture.request.Points(), matrices,
                                           *depth, db_desc.second.view_info, sets, &capture.set_view);
    if (result == Status::Ready) {
        capture.pending = source.stamp;
        capture.sampled_draw = source.draw;
        if (capture.pane && capture.pane->owner) {
            FinalWindowOwner(source.draw, source.stamp.depth_uid, scheduler.CurrentTick());
        }
        if (capture.pane) {
            if (capture.pane->natural.Active()) {
                capture.pane->natural.sampled = true;
            }
            capture.pane->stages.sample = "directional";
            capture.pane->stages.sample_rt = rt_shadow->WindowDiagnosticFrame();
        }
        capture.depth_camera = {matrices.view, matrices.inv_view, matrices.proj};
        capture.depth_jitter = upscaler->Enabled() ? upscaler->Jitter() : std::array<float, 2>{};
    } else {
        capture.refusal = Name(result);
    }
}

void Rasterizer::CaptureWindowDepth() {
    using namespace WindowPathProbe;
    auto& capture = *window_receiver;
    if (capture.pending.request || !camera_motion->Enabled() || scene_targets->Reduced() ||
        (capture.pane && !capture.pane->CanSample(capture.request.id, object_motion->Frame(),
                                         rt_shadow->WindowDiagnosticFrame(), ReceiverCapture::FrameBudget))) {
        return;
    }
    const auto render = camera_motion->RenderSize();
    const auto matrices = camera_motion->PassMatrices();
    const auto id = camera_motion->Depth();
    auto* depth = id ? texture_cache.TryGetImage(id, 0) : nullptr;
    if (!depth || !matrices.valid || !object_motion->Frame() ||
        render[0] != capture.request.width || render[1] != capture.request.height) {
        return;
    }
    if (capture.pane && capture.pane->natural.Active() &&
        !capture.pane->SameSampleState(depth->image_uid, {matrices.view, matrices.inv_view, matrices.proj},
            upscaler->Enabled() ? upscaler->Jitter() : std::array<float, 2>{})) {
        capture.refusal = "natural pane sample camera, jitter or depth identity changed";
        capture.pane->stages.Refuse(capture.refusal, object_motion->Frame(), rt_shadow->WindowDiagnosticFrame());
        return;
    }
    const u64 view = XXH3_64bits(matrices.view.data(), sizeof(matrices.view));
    const u64 stamp = XXH3_64bits_withSeed(matrices.proj.data(), sizeof(matrices.proj), view);
    const DirectionalSource source{
        .stamp = {capture.request.id, object_motion->Frame(), 0, stamp, depth->image_uid},
        .width = render[0], .height = render[1], .matched_native_inputs = true, .depth_only = true,
    };
    VideoCore::ImageViewInfo depth_view;
    depth_view.format = depth->info.pixel_format;
    const auto result = capture.copy.Submit(source, capture.request.Points(), matrices, *depth, depth_view);
    if (result == Status::Ready) {
        capture.pending = source.stamp;
        if (capture.pane) {
            if (capture.pane->natural.Active()) {
                capture.pane->natural.sampled = true;
            }
            capture.pane->stages.sample = "depth-only";
            capture.pane->stages.sample_rt = rt_shadow->WindowDiagnosticFrame();
        }
        capture.depth_camera = {matrices.view, matrices.inv_view, matrices.proj};
        capture.depth_jitter = upscaler->Enabled() ? upscaler->Jitter() : std::array<float, 2>{};
    }
}

void Rasterizer::PollWindowReceiver() {
    using namespace WindowPathProbe;
    ExpireColdWindowPane();
    const u32 generation = BbLiveKnobs::Generation();
    if (generation != window_receiver_generation) {
        window_receiver_generation = generation;
        const auto value = BbLiveKnobs::Lookup("BB_WINDOW_PATH_PIXELS");
        if (const char* text = value.Get(); text && *text) {
            PixelRequest request;
            if (!ParsePixelRequest(text, request)) {
                std::printf("Window path (t132f): invalid BB_WINDOW_PATH_PIXELS (id:width:height:x:y[:x:y...])\n");
            } else if (request.id > window_receiver_last_request) {
                window_receiver_last_request = request.id;
                if (window_receiver || window_cold_pane.Active()) {
                    std::printf("Window path (t132f): req=%u receiver unresolved (request busy)\n", request.id);
                } else {
                    window_receiver = std::make_unique<ReceiverCapture>(instance, scheduler, runtime, request);
                    const auto pane_value = BbLiveKnobs::Lookup("BB_WINDOW_PATH_PANE_PIXEL");
                    bool wait_for_natural = false;
                    if (const char* pane_text = pane_value.Get(); pane_text && *pane_text) {
                        std::string_view spec = pane_text;
                        constexpr std::string_view option = ":natural";
                        wait_for_natural = spec.ends_with(option);
                        if (wait_for_natural) {
                            spec.remove_suffix(option.size());
                        }
                        PixelRequest pane_request;
                        if (ParsePixelRequest(spec, pane_request) && pane_request.id == request.id &&
                            pane_request.width == request.width && pane_request.height == request.height &&
                            pane_request.count == 1) {
                            auto& capture = *window_receiver;
                            const auto point = pane_request.pixels[0];
                            const auto points = capture.request.Points();
                            const auto found = std::ranges::find(points, point);
                            if (found != points.end()) {
                                capture.pane_sample = u32(found - points.begin());
                            } else if (capture.request.count < WP_RECEIVERS) {
                                capture.pane_sample = capture.request.count;
                                capture.request.pixels[capture.request.count++] = point;
                            }
                            if (capture.pane_sample != WP_NONE) {
                                ArmWindowPane(capture, wait_for_natural);
                            } else {
                                std::printf("Window path (t132f): req=%u pane unresolved (eight-texel budget)\n", request.id);
                            }
                        } else {
                            std::printf("Window path (t132f): req=%u pane unresolved (pane request identity/extent)\n", request.id);
                        }
                    }
                    if (wait_for_natural && !window_receiver->pane) {
                        window_receiver.reset(); // invalid paired request, no default sample
                        return;
                    }
                    window_receiver->scene.textures = &texture_cache;
                    if (!wait_for_natural) {
                        rt_shadow->WatchWindowScene(&window_receiver->scene);
                    } else {
                        std::printf("Window natural pane (t132f): req=%u waiting for first ordinary build (90 frames/20 s)\n",
                                    request.id);
                    }
                    std::printf("Window path (t132f): armed req=%u native=%ux%u samples=%u\n",
                                request.id, request.width, request.height, request.count);
                    return;
                }
            }
        }
    }
    if (!window_receiver) {
        return;
    }
    auto& capture = *window_receiver;
    const auto finish = [&] {
        rt_shadow->WatchWindowScene(nullptr);
        rt_shadow->WatchWindowPane(nullptr);
        if (capture.pane) {
            const auto& pane = *capture.pane;
            const auto& d = pane.stages;
            const auto u = [](u64 value) { return static_cast<unsigned long long>(value); };
            std::printf("Window pane stages (t132f): req=%u arm=%llu/%llu sample=%s:%llu/%llu finish=%s:%llu/%llu "
                        "pane=%llu/%llu draws=%u exact-before/after=%u/%u hook=%u motion=%#x geometry=%u "
                        "guard=%#x observe=%u prepare=%u first-prepare=\"%s\" entry=%llx base=%llx flags=%#x "
                        "needs/reuse=%u/%u param=%u/%u build=%u added=%u match=%u left-out=%u probe=%u "
                        "span-ok=%u queue=%u tick=%llu first-refusal=\"%s\":%llu/%llu final-refusal=\"%s\"\n",
                        capture.request.id, u(d.arm_frame), u(d.arm_rt), d.sample, u(capture.pending.frame),
                        u(d.sample_rt), d.finish, u(object_motion->Frame()), u(rt_shadow->WindowDiagnosticFrame()),
                        u(pane.source_frame), u(pane.rt_frame), pane.draw_count, d.exact_before, d.exact_after,
                        d.hook, d.motion, d.geometry, d.guard, d.observed, d.prepare,
                        d.first_prepare ? d.first_prepare : "unobserved", u(d.entry), u(d.base), d.entry_flags,
                        d.ordinary_needs, d.ordinary_reuse, d.param, pane.param, d.build, d.build_added,
                        d.matching_build, d.build_left_out, d.probe_only, d.span_ok, d.queued, u(pane.tick),
                        d.first_refusal ? d.first_refusal : "none", u(d.first_frame), u(d.first_rt),
                        pane.refusal ? pane.refusal : "none");
            if (pane.natural.Active()) {
                const auto& build = pane.natural.build;
                std::printf("Window natural pane (t132f): req=%u finish=%s latched=%u frame=%llu/%llu "
                            "entry=%llx base=%llx new-entry=%s param=%u build=%u sample=%u copy-tick=%llu\n",
                            capture.request.id, d.finish, unsigned(pane.natural.Latched()),
                            u(build.object_frame), u(build.rt_frame), u(build.entry), u(build.base),
                            !pane.natural.Latched() ? "unknown" : build.new_entry ? "yes" : "no",
                            build.param, build.ordinal, unsigned(pane.natural.sampled), u(pane.tick));
            }
        }
        const auto& root = capture.scene;
        if (root.scene) {
            std::printf("Window path (t132f): req=%u observed guarded scene frame=%llu serial=%llu records=%zu "
                        "paired_receiver=unresolved\n", capture.request.id,
                        static_cast<unsigned long long>(root.scene->frame),
                        static_cast<unsigned long long>(root.scene->serial), root.facts.size());
        } else {
            const char* reason = root.status == SceneStatus::UnattestedReuse ? "unattested reuse" :
                                 root.status == SceneStatus::Budget ? "metadata budget" : "no attested new emission";
            std::printf("Window path (t132f): req=%u guarded scene unresolved (%s)\n",
                        capture.request.id, reason);
        }
        std::printf("Window path (t132f): req=%u path unresolved (pane primitive witness, receiver owner/triangle and production segment absent)\n",
                    capture.request.id);
        if (capture.pane && capture.pane->owner && !capture.pane->owner->reported) {
            const auto& owner = *capture.pane->owner;
            std::printf("Window pane owner (t132f): req=%u ambiguous (%s)\n", capture.request.id,
                        owner.material.refusal ? owner.material.refusal : "complete A/B/C and primitive join unavailable");
        }
        window_receiver.reset();
    };
    if (auto* pane = capture.pane.get(); pane && pane->natural.Active()) {
        const auto rt_frame = rt_shadow->WindowDiagnosticFrame();
        const auto object_frame = object_motion->Frame();
        if (pane->natural.Expired(object_frame, ReceiverCapture::FrameBudget, NaturalPanePair::Clock::now())) {
            pane->stages.finish = !pane->natural.Latched() ? "no-natural-build" :
                !capture.pending.request ? "no-same-frame-depth" :
                !pane->tick ? "no-matching-world-copy" : "paired-readback-deadline";
            finish();
            return;
        }
        if (pane->natural.Latched()) {
            if (!pane->natural.Closed(rt_frame)) {
                return; // this poll precedes the RT frame handoff
            }
            if (!capture.pending.request) {
                pane->stages.finish = pane->refusal ? "pane-refused" : "no-same-frame-depth";
                finish();
                return;
            }
        }
    }
    if (!capture.pending.request) {
        capture.ordinal = 0;
        if (++capture.frames >= ReceiverCapture::FrameBudget) {
            std::printf("Window path (t132f): req=%u receiver unresolved (%s)\n",
                        capture.request.id, capture.refusal);
            if (capture.pane) {
                capture.pane->stages.finish = "no-depth-sample";
            }
            finish();
        }
        return;
    }
    if (capture.pane && capture.pane->tick && !capture.pane->Ready() &&
        capture.frames + 1 < ReceiverCapture::FrameBudget) {
        ++capture.frames;
        return;
    }
    if (capture.pane && capture.pane->owner) {
        const auto& owner = *capture.pane->owner;
        if (owner.final_tick && !owner.Ready() && capture.frames + 1 < ReceiverCapture::FrameBudget) {
            ++capture.frames;
            return;
        }
    }
    DirectionalBatch output;
    const auto result = capture.copy.Poll(capture.pending, output);
    if (result == Status::Busy) {
        if (++capture.frames >= ReceiverCapture::FrameBudget) {
            std::printf("Window path (t132f): req=%u receiver unresolved (readback deadline)\n",
                        capture.request.id);
            if (capture.pane) {
                capture.pane->stages.finish = "sample-fence-timeout";
            }
            finish();
        }
        return;
    }
    if (result == Status::Ready) {
        const auto u = [](u64 value) { return static_cast<unsigned long long>(value); };
        if (!output.set_uid) {
            std::printf("Window path (t132f): req=%u light-set unresolved (%s)\n", capture.request.id, capture.refusal);
        }
        for (u32 i = 0; i < output.count; ++i) {
            const auto& pixel = output.pixels[i];
            char set[16];
            if (pixel.raw_light_set == WP_NONE) {
                std::snprintf(set, sizeof(set), "unavailable");
            } else {
                std::snprintf(set, sizeof(set), "%u", pixel.raw_light_set);
            }
            std::printf("Window path (t132f): req=%llu frame=%llu directional=%llu camera=%llx depth_uid=%llu "
                        "set_uid=%llu xy=%u,%u depth=%.8f world_valid=%u world=%.5f,%.5f,%.5f "
                        "raw_set=%s receiver_owner=unresolved direct=unavailable\n",
                        u(output.stamp.request), u(output.stamp.frame), u(capture.sampled_draw), u(output.stamp.camera),
                        u(output.stamp.depth_uid), u(output.set_uid), pixel.pixel.x, pixel.pixel.y,
                        double(pixel.raw_depth), unsigned(pixel.world_valid), double(pixel.world[0]),
                        double(pixel.world[1]), double(pixel.world[2]), set);
        }
        if (capture.pane) {
            auto& pane = *capture.pane;
            const auto pane_world = pane.Read();
            if (!pane.refusal && capture.pane_sample < output.count && !pane_world.empty() &&
                pane.source_frame == output.stamp.frame && pane.depth_uid == output.stamp.depth_uid &&
                pane.camera == capture.depth_camera && pane.jitter == capture.depth_jitter) {
                const auto& point = output.pixels[capture.pane_sample];
                const RtLampPane::Request size{.width = capture.request.width, .height = capture.request.height};
                const auto pixel = RtLampPane::Texel(size, {s32(point.pixel.x), s32(point.pixel.y)},
                                                     size.width, size.height, pane.jitter);
                const PaneRead read{
                    .capture = output.stamp, .sample = output.stamp, .draw = WindowPaneDrawKey,
                    .owner = pane.key, .vertices_per_instance = pane.vertices, .instances = pane.instances,
                    .world = pane_world, .expanded_indices = {pane.indices.data(), size_t(pane.triangles) * 3},
                    .camera = pane.camera, .pixel = pixel, .raw_depth = point.raw_depth,
                    .final_gbuffer_owner = false, .triangle_list = true,
                };
                Witness local;
                const auto matched = SamplePanePrimitive(read, GlassRegistryRules::Load(),
                                                         BbTestCamera::WorldFromDepth, local);
                const char* final_owner = "unresolved";
                if (auto* owner = pane.owner.get(); owner && !owner->material.refusal && owner->final_tick &&
                    owner->directional == capture.sampled_draw && owner->stamp.build == pane.natural.build.ordinal &&
                    owner->stamp.scene == output.stamp.frame && owner->stamp.uid == output.stamp.depth_uid) {
                    OwnerTexel a, b, c{.depth = std::bit_cast<u32>(point.raw_depth)};
                    if (owner->Read(a, b, c.albedo)) {
                        const bool later = owner->first_writer || owner->after_writes != owner->final_writes;
                        const auto verdict = ClassifyPaneOwner(true, matched == Status::Ready, a, b, c,
                                                              later, owner->coverage_gap || owner->later_clear);
                        final_owner = OwnerName(verdict);
                        owner->reported = true;
                        const auto& albedo = owner->material.sources[RawAlbedo];
                        const auto& phase = owner->material.phases;
                        std::printf("Window pane owner (t132f): req=%u %s xy=%u,%u obj=%llu rt=%llu draw=%u build=%u "
                                    "param=%u world=%llu ticks=%llu/%llu/%llu/%llu later=%u writer=%u clear=%u gap=%u "
                                    "pair=97f2d384:2390c887 count=246 first=0 mip=0 layer=0 "
                                    "albedo=%u/%llu format=%u depth=%u/%llu cam=%llx jitter=%.6f,%.6f "
                                    "raw-albedo=%08x/%08x/%08x raw-depth=%08x/%08x/%08x "
                                    "writes=%llu/%llu->%llu/%llu\n",
                                    capture.request.id, final_owner, point.pixel.x, point.pixel.y,
                                    u(owner->stamp.scene), u(owner->stamp.rt), owner->stamp.draw, owner->stamp.build,
                                    pane.param, u(pane.tick), u(phase.before_tick), u(phase.after_tick),
                                    u(owner->final_tick), u(owner->final_depth_tick), owner->draws_after,
                                    owner->first_writer, unsigned(owner->later_clear), unsigned(owner->coverage_gap),
                                    albedo.backing.id, u(albedo.backing.uid), u32(albedo.created_format),
                                    owner->stamp.image, u(owner->stamp.uid), u(output.stamp.camera),
                                    pane.jitter[0], pane.jitter[1], a.albedo, b.albedo, c.albedo, a.depth, b.depth, c.depth,
                                    u(owner->after_writes[0]), u(owner->after_writes[1]),
                                    u(owner->final_writes[0]), u(owner->final_writes[1]));
                    }
                }
                pane.stages.finish = matched == Status::Ready ?
                    (std::string_view(final_owner) == "proven" ? "primitive-with-final-owner" :
                     "primitive-with-owner-unresolved") : Name(matched);
                if (matched == Status::Ready) {
                    const u32 each = pane.triangles / pane.instances;
                    std::printf("Window path (t132f): req=%u pane xy=%u,%u depth-matched primitive=%u instance=%u local=%u "
                                "key=%llx draw=97f2d384:2390c887 idx=246 first=0 final_owner=%s\n",
                                capture.request.id, point.pixel.x, point.pixel.y, local.triangle.primitive,
                                local.triangle.primitive / each, local.triangle.primitive % each,
                                u(pane.key), final_owner);
                    const auto& root = capture.scene;
                    if (root.scene && root.scene->frame == pane.rt_frame &&
                        root.scene->camera == Roof::Camera{pane.camera.view, pane.camera.inverse} &&
                        root.projection == pane.camera.proj && root.depth_uid == pane.depth_uid &&
                        root.facts.size() == root.scene->records.size()) {
                        const auto same = [&](const RecordFacts& fact) {
                            return fact.key == pane.key && fact.capture_frame == pane.rt_frame &&
                                   fact.triangles == pane.triangles;
                        };
                        const auto record = std::ranges::find_if(root.facts, same);
                        if (record != root.facts.end() && std::none_of(record + 1, root.facts.end(), same)) {
                            const auto id = size_t(record - root.facts.begin());
                            std::printf("Window path (t132f): req=%u pane observed record=%zu serial=%llu mask=%#x custom=%#x\n",
                                        capture.request.id, id, u(root.scene->serial),
                                        root.scene->records[id].flags & 0xffu, record->custom_index);
                        }
                    }
                } else {
                    std::printf("Window path (t132f): req=%u pane unresolved (%s)\n", capture.request.id, Name(matched));
                }
            } else {
                std::printf("Window path (t132f): req=%u pane unresolved (%s)\n", capture.request.id,
                            pane.refusal ? pane.refusal : !pane.tick ? "no bounded ordinary world capture" :
                            "same-frame camera, depth identity or world fence unavailable");
                pane.stages.finish = pane.refusal ? "pane-refused" :
                    !pane.tick ? (pane.natural.Active() ? "no-matching-world-copy" : "no-world-queue") :
                    "world-sample-join-unavailable";
            }
        }
    } else {
        std::printf("Window path (t132f): req=%u receiver unresolved (%s)\n", capture.request.id, Name(result));
        if (capture.pane) {
            capture.pane->stages.finish = Name(result);
        }
    }
    finish();
}


void ReflectionFirstRetire::ReadModule(Row& row, const PipelineCache& cache, const GraphicsPipeline& pipeline) {
    if (!cache.CaptureProofUnchanged()) {
        row.module = "hot-replacement";
        return;
    }
    ReflectionDiscard::Pipeline proof{};
    const bool found = row.raster_ps && pipeline.GetReflectionDiscardProof(&cache, row.raster_ps, proof);
    if (!cache.CaptureProofUnchanged()) {
        row.module = "hot-replacement";
        return;
    }
    if (!found || proof.fragment.id.guest != row.key.ps || proof.fragment.id.stage != row.raster_ps ||
        std::bit_cast<u64>(proof.handle) != row.handle || !proof.vertex) {
        row.module = "module-unjoined";
        return;
    }
    row.proof = proof;
    row.module = proof.fragment.opcodes.valid ? "scanned" : "scan-unavailable";
    const auto* stock = ReflectionDiscard::StockFragmentForStages(row.raster_vs, row.raster_ps);
    const auto& fragment = proof.fragment;
    if (stock && stock->vertex_guest == row.key.vs && stock->fragment_guest == row.key.ps &&
        stock->permutation == fragment.permutation) {
        row.observed_certificate = ReflectionDiscard::Classify(*stock, fragment.opcodes,
            fragment.route, fragment.bytes, fragment.effective_xxh3);
    }
}

void Rasterizer::EffectsAfterDraw(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline, bool is_indexed,
                                  u32 num_indices, u32 num_instances, u32 first_vertex,
                                  const RtShadow::ReflectionDrawToken& reflection,
                                  const GraphicsPipeline& raster_pipeline, bool classified_stock_issued) {
    auto& dc = Dc();
    if (reflection_probe && gbuffer_draw && is_indexed && ReflectionStamp(regs)) {
        const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        const auto& stamp = *reflection_probe->stamp;
        if (ps && dc.capture_draw && num_instances == 1 && first_vertex == 0 && JoinCount(num_indices) &&
            ReflectionDiscard::On() && dc.draw_jitter == stamp.jitter && !BbEngine::Loading::ScreenUp() &&
            stamp.generation == BbEngine::Loading::Generation()) {
            FinishReflectionDiscard(this, pipeline_cache,
                {pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash, ps->pgm_hash,
                 num_indices, dc.draw_inputs.index_offset}, pipeline, raster_pipeline, stamp,
                scheduler.CurrentTick());
        }
        if (dc.reflection_native) {
            auto& note = *dc.reflection_native;
            note.submission_stamp = note.stamped && note.stamp == stamp &&
                note.key == ReflectionNativeProbe::Key{
                    pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash, ps ? ps->pgm_hash : 0,
                    num_indices, dc.draw_inputs.index_offset};
        }
        if (JoinCount(num_indices) && ReflectionJoinTraceOn()) {
            const auto vs = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
            const auto frag = ps ? ps->pgm_hash : 0;
            const u32 first = dc.draw_inputs.index_offset;
            const char* gate = !dc.capture_draw ? "capture-hook-inactive"
                               : !reflection.placement ? "capture-preflight-unjoined"
                               : !reflection.cookie ? "entry-unjoined"
                               : dc.draw_jitter != stamp.jitter ? "draw-jitter"
                               : "draw-confirmed";
            TraceReflectionJoin(JoinTarget(vs, frag, num_indices, first), stamp.frame,
                                reflection_probe->last_request, vs, frag, num_indices, first,
                                "submitted", gate, regs, pipeline->GetGraphicsKey().mrt_mask,
                                nullptr, dc.capture_draw, reflection.cookie != 0);
        }
        const RtShadow::ReflectionDrawToken empty;
        const auto* placed = dc.reflection_native && dc.reflection_native->submission_stamp &&
                             reflection.placed != ReflectionFirstHit::PlacedSource::None
            ? ReflectionNativeProbe::PlacedBinding(*dc.reflection_native) : nullptr;
        const auto* exact = dc.reflection_native && dc.reflection_native->exact
            ? &*dc.reflection_native->exact : nullptr;
        const bool exact_ok = classified_stock_issued && (!exact || !exact->placement ||
            (exact->submitted && ExactReflectionStages(raster_pipeline, *dc.reflection_native)));
        if (!exact_ok && exact) {
            TraceExactReflectionObjects(*dc.reflection_native, "submission-refused");
        }
        if (!classified_stock_issued && dc.reflection_native && ReflectionJoinTraceOn()) {
            const auto& key = dc.reflection_native->key;
            const auto target = JoinTarget(key.vs, key.ps, key.count, key.first);
            const char* gate = target == ReflectionJoinTarget::WallCandidate
                ? "classified-wall-route-mismatch" : "classified-fireplace-route-mismatch";
            TraceReflectionJoin(target, stamp.frame, reflection_probe->last_request,
                                key.vs, key.ps, key.count, key.first, "submitted", gate,
                                regs, pipeline->GetGraphicsKey().mrt_mask);
        }
        const bool placed_live = placed && placed->handle == placed->buffer->Handle();
        const bool joined = rt_shadow->ReflectionSubmitted(
            stamp, dc.draw_jitter == stamp.jitter && exact_ok ? reflection : empty,
            pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash, ps ? ps->pgm_hash : 0, num_indices,
            dc.draw_inputs.index_offset, placed_live ? placed : nullptr);
        if (dc.reflection_native && dc.reflection_native->stamp_retry &&
            dc.reflection_native->stamp_retry->reporting && dc.reflection_native->stamp_retry->safe) {
            auto& retry = *dc.reflection_native->stamp_retry;
            const auto* row = ReflectionFirstRetire::Current(this);
            const bool original = retry.classified && classified_stock_issued && row && row->original;
            const bool exact_issued = exact && exact->placement && exact_ok;
            retry.handle = placed_live;
            if (std::string_view{retry.failure} == "none") {
                retry.failure = !dc.reflection_native->submission_stamp ? "submission-stamp" :
                    dc.draw_jitter != stamp.jitter ? "submission-jitter" :
                    !original ? "submission-original" : !exact_issued ? "submission-exact" :
                    !placed_live ? "submission-binding" : !joined ? "submission-unjoined" : "none";
            }
            TraceStampRetry("submitted", this, retry, &stamp, scheduler.CurrentTick(),
                            reflection, original, exact_issued, joined);
        }
        if (auto* retire = ReflectionFirstRetire::Current(this)) {
            retire->confirmed = joined && exact_ok && reflection.cookie && reflection.placement;
        }
        if (ReflectionOrdinal3::On()) {
            auto* row = ReflectionFirstRetire::Current(this);
            auto& witness = ReflectionOrdinal3::state;
            const auto& resident = witness.resident;
            auto& sample = witness.working;
            if (row && ReflectionOrdinal3::Active(this, stamp.generation, row->sequence) &&
                row->original && row->stamped && exact && exact->placement && exact_ok && joined &&
                sample.sequence == row->sequence && sample.frame == stamp.frame && sample.pass == stamp.pass &&
                sample.object0_complete && sample.object3_complete && sample.native_origin3 == 1 &&
                sample.palette_current && reflection.cookie && reflection.placement == resident.placement &&
                reflection.allocation == resident.allocation) {
                sample.cookie = reflection.cookie;
                sample.placement = reflection.placement;
                sample.allocation = reflection.allocation;
                sample.tick = row->record_tick;
                witness.predecessor = sample;
            }
        }
        if (reflection.placement_delta.enabled) {
            SubmitPlacementDelta(dc.reflection_native, stamp, reflection, joined);
        }
        if (placed && placed->handle == placed->buffer->Handle() && dc.draw_jitter == stamp.jitter && exact_ok) {
            SubmitOrdinalZero(*dc.reflection_native, stamp, reflection, raster_pipeline,
                              regs.clipper_control.user_clip_plane_enable);
        }
    }
    if (blood_pool_probe) { // bbport (r100c_blood-pool-probe, TOOL): the compare right after the draw
        blood_pool_probe->AfterDraw();
    }
    if (blood_sheen) { // bbport (r100_blood-sheen): the glint right after the pool's draw
        blood_sheen->AfterDraw();
    }
    if (glass_glint) { // bbport (r86b_glass-visible): right after a pane's draw it noted
        if (glint_pending == pipeline) {
            const auto* pane_ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)]; // bbport (r86e)
            glass_glint->AfterGlassDraw(cb_descs[0].first, db_desc.first, upscaler->Jitter(),
                                        point_shadow->Pending(),
                                        {.vs = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,
                                         .ps = pane_ps ? pane_ps->pgm_hash : 0,
                                         .indices = num_indices, .instances = num_instances});
        }
        glint_pending = nullptr;
    }
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
        // bbport (r51_volumetric-leak): with BB_VOLUMETRIC_OCCLUSION bit 1 neither are cascades
        // holding no casters: without draws, unless r14 or r7 keeps an earlier drawing (r7's
        // quadrants it marked stale or owes a clear hold the clear value: not kept).
        const u32 count =
            sun_atlas.skipped_mask ? u32(std::countr_zero(sun_atlas.skipped_mask)) : 4u;
        sun_atlas.valid_mask = VolumetricOcclusion::Valid(
            {.count = count, .drawn = sun_atlas.drawn_mask, .spread = sun_atlas.mask_spread != 0,
             .held = sun_hold.confirmed, .held_lost = sun_hold.stale | sun_hold.pending_clear,
             .kept_tracked = sun_keep.tracked, .kept_drawn = sun_keep.drawn,
             .kept_cleared = sun_keep.cleared, .kept_blank = sun_keep.blank},
            VolumetricOcclusion::Bits());
        volumetric_light->SetAtlasCascades(count, sun_atlas.valid_mask);
        sun_atlas.skipped_mask = 0;
        // bbport (r51b_volumetric-rt-check): with BB_VOLUMETRIC_RT_GATE the march also asks this
        // frame's ray traced scene (in the camera's view space) whether the sun reaches each cell
        // of its gate. The ray traced sun prepares the scene at the next draw (ContactShadow::
        // Flush) from the same entries (nothing is captured in between), so this call only moves
        // that build forward and the sun's call then returns at once. No scene: stage A's march.
        // bbport (r76_sun-fog-outdoors): unset is 1 (the sun's casters), so the gate runs whenever
        // RtShadow builds a scene (effect_ray_tracing on and RtShadow::SceneWanted: the ray traced
        // sun, lamps or bounced light); 0 turns it off. Without a scene the mask in force is 0
        // (GateInForce). With the ray traced sun off the next reader of the scene (the lamps)
        // builds or refits the TLAS again only if entries arrived since this call.
        const u32 rt_gate = VolumetricOcclusion::RtGateMask();
        const bool rt_scene = rt_gate != 0 && rt_shadow->PrepareScene();
        volumetric_light->SetSunScene(rt_scene ? rt_shadow->Scene() : vk::AccelerationStructureKHR{},
                                      VolumetricOcclusion::GateInForce(rt_gate, rt_scene));
        // bbport (r76_sun-fog-outdoors): the scene's instances in TLAS order (filled only with
        // BB_VOLUMETRIC_GATE_PROBE=1), and the direction toward the sun or moon as the host reads it
        // from this resolve's shadow constants (the 32 dwords the gate's rays take theirs from, at
        // the V# base as SunAtlasResolve reads the splits), turned to world space with this frame's
        // camera (the one PrepareScene placed the scene's instances with). A 128-byte read and a
        // 4x4 inverse; the march says it once and when it moves (VolumetricLight::SayLight).
        volumetric_light->SetSunSceneTable(rt_scene ? &rt_shadow->GateTable() : nullptr);
        // bbport (r76c_sun-fog-shells): and what the capture knew of each (probe only)
        volumetric_light->SetSunSceneCaptures(rt_scene ? &rt_shadow->GateCaptures() : nullptr);
        {
            VolumetricOcclusion::SunLight light{};
            if (ps_info->buffers.size() >= 2 && !ps_info->buffers[0].IsSpecial()) {
                const VAddr rows = ps_info->buffers[0].GetSharp(*ps_info).base_address;
                std::array<float, 32> constants{};
                if (memory->IsValidGpuMapping(rows, 0) &&
                    memory->ClampRangeSize(rows, sizeof(constants)) == sizeof(constants)) {
                    std::memcpy(constants.data(), reinterpret_cast<const void*>(rows),
                                sizeof(constants));
                    const auto camera = camera_motion->PassMatrices();
                    light = VolumetricOcclusion::MakeSunLight(constants, camera.inv_view,
                                                              camera.valid);
                }
            }
            volumetric_light->SetSunLight(light);
            // bbport (r107_caustics): the screen shadow target and the sun's or moon's direction
            if (caustics) {
                caustics->OnShadowResolve(cb_descs[0].first, light.world, light.valid);
            }
            if (foliage_glow) { // bbport (r131a_foliage-translucency): the sun's or moon's direction for the glow
                foliage_glow->OnSun(light.world, light.valid);
            }
            // bbport (r105_cloud-shadows): the light and the camera (null when off)
            if (cloud_shadow) {
                cloud_shadow->SetSunLight(light.world, light.view_to_world, light.valid);
            }
            // bbport (r119_volumetric-clouds): the same light for the cloud layer (null when off)
            if (cloud_layer) {
                cloud_layer->SetSunLight(light.world, light.valid);
            }
        }
        // bbport (r82_wind-stage1): with BB_WIND=1 the march drifts with the wind. The view to
        // world matrix is the G-buffer pass's camera as it stands at this call, not at the
        // composite.
        if (const BbWind::Snapshot w = wind.Get(); w.on) {
            const auto camera = camera_motion->PassMatrices();
            volumetric_light->SetWind(w.off1, w.off2, camera.inv_view, camera.valid, WindShow());
            BbWind::Use(BbWind::Follower::Fog, w, w.wind); // bbport (r116)
        }
        // bbport (r94_fog-noise): BB_FOG_NOISE above 0 only (read once): the sun fog's world
        // anchored noise, with the G-buffer pass's camera at this call and the wind's snapshot (it
        // drifts while BB_WIND=1 and stands still without it). After SetWind: the noise then
        // carries the drift in place of r82's WIND build.
        if (VolumetricLight::FogNoiseKnob()) {
            const BbWind::Snapshot w = wind.Get();
            const auto camera = camera_motion->PassMatrices();
            volumetric_light->SetFogNoise(w.on, w.time, w.wind, camera.inv_view, camera.valid);
            BbWind::Use(BbWind::Follower::FogNoise, w, w.wind); // bbport (r116)
        }
        // bbport (r115b_sun-fog-out-of-sewer-library): BB_VOLUMETRIC_ROOF=1: the camera's overhead cover for the march's strength (-1 without the wind shelter field)
        if (VolumetricLight::RoofMode() != 0) {
            volumetric_light->SetRoofCover(wind_shelter ? wind_shelter->CameraCover() : -1.0f);
        }
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
        // bbport (r51_volumetric-leak): the r19 path counts the next atlas draws for the mask.
        sun_atlas.mask_wanted = sun_atlas.reach > 0.0f &&
                                (VolumetricOcclusion::Bits() & VolumetricOcclusion::SkipEmpty) != 0;
    } else if (hash == DirectionalFragmentShaderHash && !dc.buffer_infos.empty()) {
        volumetric_light->Tint(dc.buffer_infos[0], dc.push_data.buf_offsets[0] & 255u);
        // bbport (r81_sun-fog-no-rt): BB_VOLUMETRIC_AREA_GATE=1: after a march without the ray
        // traced gate, the fog weighed with the game's light sets; the draw's texture 0 names each
        // pixel's record in its alpha byte (engine/tools/re/ggx_directional_controls.py)
        volumetric_light->AreaGate(dc.buffer_infos[0], dc.push_data.buf_offsets[0] & 255u,
                                   dc.image_infos.empty() || ps_info->images.empty()
                                       ? vk::DescriptorImageInfo{}
                                       : dc.image_infos[0]);
        // bbport (r107b_caustics-visible): the light sets for the water caustics' sun: the table
        // (as Tint reads it, at most 256 sets of 288 bytes from the buffer's V# base) and the
        // address of texture 0, whose alpha byte names each pixel's set
        if (caustics && caustics->SunWanted() && !ps_info->buffers.empty() &&
            !ps_info->buffers[0].IsSpecial() && !ps_info->images.empty()) {
            const u64 skip = dc.push_data.buf_offsets[0] & 255u;
            const u64 bytes = std::min<u64>(
                dc.buffer_infos[0].range > skip ? dc.buffer_infos[0].range - skip : 0, 256ull * 288ull);
            const VAddr table = ps_info->buffers[0].GetSharp(*ps_info).base_address;
            if (bytes >= 288 && memory->IsValidGpuMapping(table, 0) &&
                memory->ClampRangeSize(table, bytes) == bytes) {
                caustics->OnLightSets(reinterpret_cast<const float*>(table), u32(bytes / 4),
                                      ps_info->images[0].GetSharp(*ps_info).Address());
            }
        }
        // bbport (r131a_foliage-translucency): the light sets' table again for the glow's sun colour (the brightest set's light 0)
        if (foliage_glow && !ps_info->buffers.empty() && !ps_info->buffers[0].IsSpecial()) {
            const u64 skip = dc.push_data.buf_offsets[0] & 255u;
            const u64 bytes = std::min<u64>(
                dc.buffer_infos[0].range > skip ? dc.buffer_infos[0].range - skip : 0, 256ull * 288ull);
            const VAddr table = ps_info->buffers[0].GetSharp(*ps_info).base_address;
            if (bytes >= 288 && memory->IsValidGpuMapping(table, 0) && memory->ClampRangeSize(table, bytes) == bytes) {
                foliage_glow->OnLightSets(reinterpret_cast<const float*>(table), u32(bytes / 4));
            }
        }
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
                                             // bbport (r96_lamp-flicker-colour): as drawn
                                             LampFlicker::Fog(reinterpret_cast<const u32*>(lights)),
                                             count);
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
/// r14's quadrant of a draw (below); bbport (r51_volumetric-leak): the r19 path's too.
u32 SunQuadrant(const DynamicState& dynamic, u32 width, u32 height);
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
        // bbport (r51_volumetric-leak): the volumetric march's mask needs the cascades with draws
        // (r14 records its own); whether the depth target is the atlas is looked up once a pass.
        if (a.mask_wanted && db_desc.first && !sun_keep.tracked) {
            const u64 pass = scheduler.PassesBegun();
            if (pass != a.mask_pass) {
                a.mask_pass = pass;
                a.mask_atlas =
                    texture_cache.GetImage(db_desc.first).info.guest_address == a.address;
            }
            if (a.mask_atlas) {
                // As the full path below counts it (cascade_draws, drawn_mask); a draw across
                // quadrants or without a single viewport counts for all four (r14's rule).
                const u32 quadrant =
                    SunQuadrant(scheduler.GetDynamicState(), state.width, state.height);
                if (quadrant < 4) {
                    ++a.cascade_draws[quadrant];
                    a.drawn_mask |= 1u << quadrant;
                } else if (quadrant < 6) {
                    ++a.mask_spread;
                }
            }
        }
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
    // bbport (r51_volumetric-leak): a draw across quadrants or without a single viewport
    // returns below without a cascade; for the volumetric march's mask it counts for all four,
    // as r14 counts it (the r19 path above does the same).
    if (a.mask_wanted && !sun_keep.tracked) {
        const u32 quadrant = SunQuadrant(dynamic, state.width, state.height);
        a.mask_spread += quadrant == 4 || quadrant == 5 ? 1u : 0u;
    }
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
            // bbport (r64_surface-probe): the water's samples, for the log (queries not precise:
            // a driver may give any count above 0 for "some")
            if (surface_probe_on && result == vk::Result::eSuccess) {
                SurfaceProbeWater(counts.data(), n);
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

// bbport (r64_surface-probe): BB_SURFACE_PROBE=1 (read once at start, off by default): a log of how
// the game draws its surfaces. Light through window panes and caustics in small water need to know
// how the game draws panes, lantern glass, puddles, fountains, canals and blood, and the engine sees
// draws, not materials. So for each pair of vertex and pixel shaders, in each kind of pass and under
// each render state, one line is printed the first time it draws with what can tell those surfaces
// apart: its targets, blend, write mask, depth, stencil, cull, discard, the textures it reads
// (reading the scene colour or depth back is a sign of refraction or of soft edges) and whether the
// ray traced scene took it. Every 600 frames a "window" line carries the run time, the clock time
// and the camera position (to match the log to where the player stood), with the ids of the pairs
// that drew, a short line for each pair whose draw or vertex count changed, the lamps the game sent
// to the lamp pass, whether a mirrored (water reflection) G-buffer pass was drawn and what the
// water's existing occlusion queries saw. Nothing is drawn, bound, measured or compiled for it: the
// picture and the GPU's work are the same with it on. Off, each draw pays one bool test.
namespace {
constexpr u32 ProbeMaxPairs = 4096;         ///< pairs kept; draws of further pairs are only counted
constexpr u32 ProbeWindowFrames = 600;      ///< frames between the short repeat lines
constexpr u32 ProbeMaxWindowLines = 512;    ///< "pair" lines a window prints at most
constexpr u64 ProbeDetailWindows = 200;     ///< windows that print "pair", "active" and "lamps" lines
constexpr u32 ProbeMaxLamps = 64;           ///< distinct lamps kept a frame (as LampTrack::Most)
constexpr u32 ProbeMaxTextures = 8;         ///< textures a "new" line lists (all are counted)
constexpr u32 ProbeMaxInstances = 64;       ///< MaxInstancesPerDraw of the ray traced scene (vk_rt_shadow.cpp)
constexpr u64 ProbeNoFrameEndDraws = 200000; ///< draws with no frame end before the probe warns
constexpr u64 ProbeWaterPsHash = 0xe3021062ull; ///< the game's water (WaterHash, vk_effect_shaders.cpp)

enum class ProbePass : u8 { Shadow, GBuffer, Forward, Other };

const char* ProbePassName(ProbePass pass) {
    switch (pass) {
    case ProbePass::Shadow:
        return "shadow";
    case ProbePass::GBuffer:
        return "gbuffer";
    case ProbePass::Forward:
        return "forward";
    default:
        return "other";
    }
}

/// The names of AmdGpu::BlendControl's factors, functions and the depth compare, for the log.
const char* ProbeFactor(u32 factor) {
    static constexpr const char* names[] = {
        "Zero",          "One",         "SrcColor",         "OneMinusSrcColor",
        "SrcAlpha",      "OneMinusSrcAlpha", "DstAlpha",    "OneMinusDstAlpha",
        "DstColor",      "OneMinusDstColor", "SrcAlphaSaturate", "Factor11",
        "Factor12",      "ConstantColor", "OneMinusConstantColor", "Src1Color",
        "InvSrc1Color",  "Src1Alpha",   "InvSrc1Alpha",     "ConstantAlpha",
        "OneMinusConstantAlpha"};
    return factor < std::size(names) ? names[factor] : "Factor?";
}

const char* ProbeBlendFunc(u32 func) {
    static constexpr const char* names[] = {"Add", "Subtract", "Min", "Max", "ReverseSubtract"};
    return func < std::size(names) ? names[func] : "Func?";
}

const char* ProbeCompare(u32 func) {
    static constexpr const char* names[] = {"Never",   "Less",     "Equal",        "LessEqual",
                                            "Greater", "NotEqual", "GreaterEqual", "Always"};
    return func < std::size(names) ? names[func] : "Compare?";
}

/// The local clock time, HH:MM:SS, so the owner can match the log to the times he noted.
std::string ProbeClock() {
    const std::time_t now = std::time(nullptr);
    std::tm local{};
#ifdef _WIN32
    localtime_s(&local, &now);
#else
    localtime_r(&now, &local);
#endif
    char text[16];
    return std::strftime(text, sizeof(text), "%H:%M:%S", &local) != 0 ? std::string(text)
                                                                      : std::string("-");
}

struct ProbeKey {
    u64 vs = 0;
    u64 ps = 0;
    ProbePass pass{};
    u32 state = 0; ///< a hash of the draw's render state (SurfaceProbeDraw)
    bool operator==(const ProbeKey&) const = default;
};

struct ProbeKeyHash {
    std::size_t operator()(const ProbeKey& k) const noexcept {
        return std::size_t((k.vs * 0x9e3779b97f4a7c15ull) ^ (k.ps * 0xc2b2ae3d27d4eb4full) ^
                           (u64(k.state) * 0x165667b19e3779f9ull) ^ u64(k.pass));
    }
};

struct ProbeEntry {
    ProbeKey key;
    std::string facts;     ///< the first draw's facts, printed at the end of its frame
    bool water = false;    ///< the water's pixel shader
    bool printed = false;  ///< the "new" line is out
    bool touched = false;  ///< drawn this frame (listed in ProbeState::touched)
    u8 gbuffer_passes = 0; ///< this frame: bit i set, drawn in the frame's G-buffer pass i
    u64 first_window = 0;  ///< the window it first drew in
    u64 total = 0;         ///< draws since the start
    // This window.
    u64 draws = 0, vertices = 0, captured = 0, indirect = 0;
    u32 index_min = ~0u, index_max = 0; ///< the smallest and largest index count of its direct draws
    u64 mirrored_frames = 0; ///< frames it drew in a mirrored G-buffer pass (not the frame's last)
    u64 main_frames = 0;     ///< frames it drew in the frame's main pass (or a pass of any other kind)
    const char* drop = "-";  ///< why its last draw left out of the ray traced scene was
    // bbport (r64b_surface-probe-more): this window: draws that reached a ray traced scene entry,
    // the last entry's key, the smallest and largest entry triangle count; the cube maps its
    // pixel shader reads (from its "new" line's facts)
    u64 rt_in = 0, rt_key = 0;
    u32 rt_tris_min = ~0u, rt_tris_max = 0;
    u32 cube = 0;
    // As the last "pair" line (or none yet) said.
    u64 shown_draws = ~0ull, shown_vertices = ~0ull;
};

struct ProbeReadJob; // bbport (r64b_surface-probe-more): a readback on its way (defined below)

struct ProbeState {
    std::mutex lock; // draws may be recorded on the GPU thread or on stage B
    std::unordered_map<ProbeKey, u32, ProbeKeyHash> index;
    std::vector<ProbeEntry> entries;
    std::vector<u32> touched; ///< entries drawn this frame
    u64 frame = 0, window = 0;
    u32 window_frames = 0;
    std::chrono::steady_clock::time_point start{}, window_start{}; ///< the first frame end, the window's
    u64 draws_before_frame_end = 0; ///< draws seen while no frame end has come yet
    u64 untracked = 0;     ///< this window: draws of pairs the full table could not take
    u64 new_pairs = 0;     ///< this window
    // This frame's G-buffer passes, told apart by their depth target as CameraMotion does.
    VideoCore::ImageId gbuffer_depth{};
    u32 gbuffer_passes = 0;
    u64 multi_frames = 0, mirrored_frames = 0; ///< this window
    // Lamps: this frame's distinct records (words 0-6), the last frame that had any.
    std::vector<std::array<u32, 7>> lamps, shown_lamps;
    u64 shown_lamps_frame = 0;
    u64 lamp_records = 0, lamps_over = 0, lamp_frames = 0, lamps_sum = 0; ///< this window
    u32 lamps_max = 0;
    u64 water_samples = 0, water_queries = 0; ///< this window
    // bbport (r64b_surface-probe-more)
    u64 frame_draw = 0; ///< draws this frame so far (their numbers, from 1)
    std::array<VideoCore::ImageId, 5> gb{}; ///< cb0 to cb4 of this frame's last G-buffer pass
    VideoCore::ImageId gb_depth{};
    VideoCore::ImageId shadow_target{}; ///< the screen shadow target, followed as ContactShadow does
    u64 shadow_ps = 0;                  ///< the pixel shader that drew it last (resolve or blur)
    bool blended_seen = false;  ///< this frame's readback try came (SurfaceProbeBlendedScene)
    bool readback_done = false; ///< this window took its readback
    u32 passes_last = 0;        ///< the G-buffer passes of the last frame
    std::shared_ptr<ProbeReadJob> readback; ///< the readback on its way (frame ends see to it)
    std::vector<std::string> readback_lines; ///< its lines, printed with the next window line
    struct Order { ///< draw numbers in a frame (0: none)
        u64 frame = 0, draws = 0, gb_first = 0, gb_last = 0, lamp_first = 0, lamp_last = 0,
            water_first = 0, water_last = 0, blended = 0;
        u32 water_draws = 0;
        u32 blended_pass = 0, passes = 0; ///< G-buffer passes before `blended`, and in the frame
    } now, order_last, order_water;
    u8 water_zwrite = 0; ///< this window: bit 0 water drawn without depth write, bit 1 with
    u64 water_frames = 0, water_draws = 0, water_before = 0, water_after = 0, water_among = 0,
        water_alone = 0; ///< this window
    u32 water_draws_max = 0;
    // Lamp record words 7-11, this window.
    std::array<float, 5> word_min{std::numeric_limits<float>::infinity(),
                                  std::numeric_limits<float>::infinity(),
                                  std::numeric_limits<float>::infinity(),
                                  std::numeric_limits<float>::infinity(),
                                  std::numeric_limits<float>::infinity()};
    std::array<float, 5> word_max{-std::numeric_limits<float>::infinity(),
                                  -std::numeric_limits<float>::infinity(),
                                  -std::numeric_limits<float>::infinity(),
                                  -std::numeric_limits<float>::infinity(),
                                  -std::numeric_limits<float>::infinity()};
    std::array<u32, 5> word_umin{~0u, ~0u, ~0u, ~0u, ~0u}, word_umax{};
    u64 word_records = 0, word_zero = 0, word_nonfinite = 0, lamps_negative = 0;
    // The ray traced scene at the window's last frame (SurfaceProbeRtScene).
    std::string rt_scene_line, rt_skinned_line;
    // Plane fits (RtShadow::ProbeCopyBuild): a slot per fit on its way.
    struct Fit {
        bool active = false, listed = false, skinned = false;
        ProbePass pass{};
        u32 id = 0, triangles = 0, vertices = 0, instances = 0;
        u64 vs = 0, ps = 0, key = 0, frame = 0;
        std::vector<u32> indices;
    };
    std::array<Fit, RtShadow::ProbeSlots> fits{};
    std::unordered_set<u64> fitted; ///< entry keys fitted or on their way (a dropped build is asked again)
    u64 fits_window = 0, fits_asked = 0, fits_no_slot = 0, fits_done = 0, fits_lost = 0,
        fits_dropped = 0;
    std::vector<std::pair<u64, u64>> env_pairs; ///< BB_SURFACE_PROBE_PAIRS (vs, ps)
    // Skinned entries by key: the last pair whose draw reached it, and this window's samples of
    // its guest index list (hashed every ProbeSkinHashFrames frames) and how often it changed.
    struct Skin {
        u32 pair = 0; ///< 1 + the pair's id (0: none)
        u64 window = ~0ull, last_hash = 0;
        u32 samples = 0, changes = 0;
    };
    std::unordered_map<u64, Skin> skins;
};

ProbeState& Probe() {
    static ProbeState state;
    return state;
}

int ProbeOrder(const ProbeEntry& e) {
    // Forward and mirrored draws first: glass, water and its reflection are likely among them.
    switch (e.key.pass) {
    case ProbePass::Forward:
        return 0;
    case ProbePass::GBuffer:
        return e.mirrored_frames != 0 ? 1 : 2;
    case ProbePass::Other:
        return 3;
    default:
        return 4;
    }
}

const char* ProbeGBufferName(const ProbeEntry& e) {
    if (e.key.pass != ProbePass::GBuffer || e.mirrored_frames == 0) {
        return ProbePassName(e.key.pass);
    }
    return e.main_frames != 0 ? "gbuffer+mirrored" : "mirrored";
}
// bbport (r64b_surface-probe-more): what the additions below use.
constexpr u32 ProbeReadbackFrame = 300;   ///< the frame of a window from which the readback is taken
constexpr u32 ProbeReadbackRows = 64;     ///< rows read of each target, evenly spaced
constexpr u64 ProbeReadbackMaxBytes = 32ull << 20; ///< host memory one readback may take
constexpr u32 ProbeFitSlots = RtShadow::ProbeSlots;
constexpr u32 ProbeFitsPerWindow = 16;    ///< plane fits asked for a window at most
constexpr u32 ProbeFitAutoTriangles = 2048; ///< without BB_SURFACE_PROBE_PAIRS: entries this small
constexpr u32 ProbeFitMaxTriangles = 8192; ///< the most triangles a fit takes
constexpr u32 ProbeFitWaitFrames = 1200;  ///< a copy not back by then is given up
constexpr std::size_t ProbeMaxFitted = 4096; ///< entries fitted (each once)
constexpr std::size_t ProbeMaxEnvPairs = 20; ///< pairs BB_SURFACE_PROBE_PAIRS may name
constexpr u32 ProbeSkinnedMost = 16;      ///< skinned entries an "rt-skinned" line lists
constexpr std::size_t ProbeMaxSkins = 1024; ///< skinned entry keys followed (pair, index list)
constexpr u64 ProbeSkinHashFrames = 60;   ///< the skinned draws' index lists are hashed every 60 frames
constexpr u32 ProbeReadbackStep = 4;      ///< every 4th texel of a row is read

/// How a target's texels are read (ProbeDecode); None: not read.
enum class ProbeTexel : u8 {
    None, Rgba8, Bgra8, Rg8, R8, A2Bgr10, A2Rgb10, B10G11R11, Rgba16F, Rg16F, R16F, Rgba16, Rg16,
    R16, Rgba32F, Rg32F, R32F, R32U, D32F, D24, D16
};

ProbeTexel ProbeTexelOf(vk::Format format) {
    switch (format) {
    case vk::Format::eR8G8B8A8Unorm:
    case vk::Format::eR8G8B8A8Srgb:
        return ProbeTexel::Rgba8;
    case vk::Format::eB8G8R8A8Unorm:
    case vk::Format::eB8G8R8A8Srgb:
        return ProbeTexel::Bgra8;
    case vk::Format::eR8G8Unorm:
        return ProbeTexel::Rg8;
    case vk::Format::eR8Unorm:
        return ProbeTexel::R8;
    case vk::Format::eA2B10G10R10UnormPack32:
        return ProbeTexel::A2Bgr10;
    case vk::Format::eA2R10G10B10UnormPack32:
        return ProbeTexel::A2Rgb10;
    case vk::Format::eB10G11R11UfloatPack32:
        return ProbeTexel::B10G11R11;
    case vk::Format::eR16G16B16A16Sfloat:
        return ProbeTexel::Rgba16F;
    case vk::Format::eR16G16Sfloat:
        return ProbeTexel::Rg16F;
    case vk::Format::eR16Sfloat:
        return ProbeTexel::R16F;
    case vk::Format::eR16G16B16A16Unorm:
        return ProbeTexel::Rgba16;
    case vk::Format::eR16G16Unorm:
        return ProbeTexel::Rg16;
    case vk::Format::eR16Unorm:
        return ProbeTexel::R16;
    case vk::Format::eR32G32B32A32Sfloat:
        return ProbeTexel::Rgba32F;
    case vk::Format::eR32G32Sfloat:
        return ProbeTexel::Rg32F;
    case vk::Format::eR32Sfloat:
        return ProbeTexel::R32F;
    case vk::Format::eR32Uint:
        return ProbeTexel::R32U;
    case vk::Format::eD32Sfloat:
    case vk::Format::eD32SfloatS8Uint:
        return ProbeTexel::D32F;
    case vk::Format::eD24UnormS8Uint:
    case vk::Format::eX8D24UnormPack32:
        return ProbeTexel::D24;
    case vk::Format::eD16Unorm:
    case vk::Format::eD16UnormS8Uint:
        return ProbeTexel::D16;
    default:
        return ProbeTexel::None;
    }
}

u32 ProbeTexelBytes(ProbeTexel texel) {
    switch (texel) {
    case ProbeTexel::None:
        return 0;
    case ProbeTexel::R8:
        return 1;
    case ProbeTexel::Rg8:
    case ProbeTexel::R16F:
    case ProbeTexel::R16:
    case ProbeTexel::D16:
        return 2;
    case ProbeTexel::Rgba16F:
    case ProbeTexel::Rgba16:
    case ProbeTexel::Rg32F:
        return 8;
    case ProbeTexel::Rgba32F:
        return 16;
    default:
        return 4;
    }
}

u32 ProbeChannels(ProbeTexel texel) {
    switch (texel) {
    case ProbeTexel::Rgba8:
    case ProbeTexel::Bgra8:
    case ProbeTexel::A2Bgr10:
    case ProbeTexel::A2Rgb10:
    case ProbeTexel::Rgba16F:
    case ProbeTexel::Rgba16:
    case ProbeTexel::Rgba32F:
        return 4;
    case ProbeTexel::B10G11R11:
        return 3;
    case ProbeTexel::Rg8:
    case ProbeTexel::Rg16F:
    case ProbeTexel::Rg16:
    case ProbeTexel::Rg32F:
        return 2;
    default:
        return 1;
    }
}

/// An unsigned small float with a 5-bit exponent (the 11 and 10 bit channels of B10G11R11).
float ProbeSmallFloat(u32 bits, u32 mantissa_bits) {
    const u32 e = bits >> mantissa_bits;
    const u32 m = bits & ((1u << mantissa_bits) - 1u);
    const float f = float(m) / float(1u << mantissa_bits);
    if (e == 0) {
        return std::ldexp(f, -14);
    }
    if (e == 31) {
        return m != 0 ? std::numeric_limits<float>::quiet_NaN()
                      : std::numeric_limits<float>::infinity();
    }
    return std::ldexp(1.0f + f, int(e) - 15);
}

/// A 16-bit float (1 sign, 5 exponent, 10 mantissa bits).
float ProbeHalf(u32 bits) {
    const float m = ProbeSmallFloat(bits & 0x7fffu, 10);
    return (bits & 0x8000u) != 0 ? -m : m;
}

/// The texel at `at` as up to four channels, in the format's r, g, b, a order.
void ProbeDecode(ProbeTexel texel, const u8* at, std::array<float, 4>& c) {
    std::array<u32, 4> v{}; // the texel's bytes as 32-bit words (up to 16 bytes)
    std::memcpy(v.data(), at, ProbeTexelBytes(texel));
    const u32 w = v[0];
    const auto f32 = [&](u32 i) { return std::bit_cast<float>(v[i]); };
    const auto f16 = [&](u32 i) { return ProbeHalf((v[i / 2] >> (16 * (i % 2))) & 0xffffu); };
    const auto u16 = [&](u32 i) { return float((v[i / 2] >> (16 * (i % 2))) & 0xffffu) / 65535.0f; };
    switch (texel) {
    case ProbeTexel::Rgba8:
        c = {float(w & 0xffu) / 255.0f, float((w >> 8) & 0xffu) / 255.0f,
             float((w >> 16) & 0xffu) / 255.0f, float(w >> 24) / 255.0f};
        break;
    case ProbeTexel::Bgra8:
        c = {float((w >> 16) & 0xffu) / 255.0f, float((w >> 8) & 0xffu) / 255.0f,
             float(w & 0xffu) / 255.0f, float(w >> 24) / 255.0f};
        break;
    case ProbeTexel::Rg8:
        c = {float(w & 0xffu) / 255.0f, float((w >> 8) & 0xffu) / 255.0f, 0.0f, 0.0f};
        break;
    case ProbeTexel::R8:
        c = {float(w & 0xffu) / 255.0f, 0.0f, 0.0f, 0.0f};
        break;
    case ProbeTexel::A2Bgr10:
        c = {float(w & 0x3ffu) / 1023.0f, float((w >> 10) & 0x3ffu) / 1023.0f,
             float((w >> 20) & 0x3ffu) / 1023.0f, float(w >> 30) / 3.0f};
        break;
    case ProbeTexel::A2Rgb10:
        c = {float((w >> 20) & 0x3ffu) / 1023.0f, float((w >> 10) & 0x3ffu) / 1023.0f,
             float(w & 0x3ffu) / 1023.0f, float(w >> 30) / 3.0f};
        break;
    case ProbeTexel::B10G11R11:
        c = {ProbeSmallFloat(w & 0x7ffu, 6), ProbeSmallFloat((w >> 11) & 0x7ffu, 6),
             ProbeSmallFloat(w >> 22, 5), 0.0f};
        break;
    case ProbeTexel::Rgba16F:
        c = {f16(0), f16(1), f16(2), f16(3)};
        break;
    case ProbeTexel::Rg16F:
        c = {f16(0), f16(1), 0.0f, 0.0f};
        break;
    case ProbeTexel::R16F:
        c = {f16(0), 0.0f, 0.0f, 0.0f};
        break;
    case ProbeTexel::Rgba16:
        c = {u16(0), u16(1), u16(2), u16(3)};
        break;
    case ProbeTexel::Rg16:
        c = {u16(0), u16(1), 0.0f, 0.0f};
        break;
    case ProbeTexel::R16:
    case ProbeTexel::D16:
        c = {u16(0), 0.0f, 0.0f, 0.0f};
        break;
    case ProbeTexel::Rgba32F:
        c = {f32(0), f32(1), f32(2), f32(3)};
        break;
    case ProbeTexel::Rg32F:
        c = {f32(0), f32(1), 0.0f, 0.0f};
        break;
    case ProbeTexel::R32F:
    case ProbeTexel::D32F:
        c = {f32(0), 0.0f, 0.0f, 0.0f};
        break;
    case ProbeTexel::R32U:
        c = {float(w), 0.0f, 0.0f, 0.0f};
        break;
    case ProbeTexel::D24:
        c = {float(w & 0xffffffu) / 16777215.0f, 0.0f, 0.0f, 0.0f};
        break;
    default:
        c = {};
        break;
    }
}

/// The cb1.r value (the specular exponent's code, exponent = 2^(13 m)) whose roughness is
/// `roughness` under ssgi_probe.comp's materialRoughness, before its wet ground change.
float ProbeGlossFor(float roughness) {
    const double a2 = std::max(std::pow(double(roughness), 4.0), 1e-6);
    const double c2 = 1.0 / (1.0 + 1.41421356 * a2);
    const double exponent = -2.0 / std::log2(c2);
    return float(std::log2(exponent) / 13.0);
}

/// Min, max and mean per channel of the texels added.
struct ProbeStats4 {
    std::array<double, 4> sum{};
    std::array<float, 4> lo{}, hi{};
    u64 n = 0, nonfinite = 0;
    ProbeStats4() {
        lo.fill(std::numeric_limits<float>::infinity());
        hi.fill(-std::numeric_limits<float>::infinity());
    }
    void Add(const std::array<float, 4>& c, u32 channels) {
        for (u32 i = 0; i < channels; ++i) {
            if (!std::isfinite(c[i])) {
                ++nonfinite;
                return;
            }
        }
        ++n;
        for (u32 i = 0; i < channels; ++i) {
            sum[i] += c[i];
            lo[i] = std::min(lo[i], c[i]);
            hi[i] = std::max(hi[i], c[i]);
        }
    }
    /// " <prefix>r=min,max,mean ..." per channel ("-" with no texel).
    std::string Text(u32 channels, const char* prefix) const {
        static constexpr const char* names[] = {"r", "g", "b", "a"};
        std::string out;
        for (u32 i = 0; i < channels && i < 4; ++i) {
            out += n == 0 ? fmt::format(" {}{}=-", prefix, names[i])
                          : fmt::format(" {}{}={:.4f},{:.4f},{:.4f}", prefix, names[i], lo[i], hi[i],
                                        sum[i] / double(n));
        }
        return out;
    }
};

/// One target of a readback: what it is, where its rows are in the host buffer.
struct ProbeReadItem {
    const char* name = "-";
    vk::Format format = vk::Format::eUndefined;
    ProbeTexel texel = ProbeTexel::None;
    u32 width = 0, height = 0, rows = 0;
    u64 offset = 0, row_bytes = 0;
    bool read = false;
    bool proxy = false; ///< read from the reduced scene target that stands in for it
    const char* why = "-";
};

struct ProbeReadJob {
    u64 window = 0, frame = 0;
    double t = 0.0;
    std::string clock, cam;
    u8 sun_path = 0;
    bool sun_wanted = false, rt_complete = false, rt_on = false, contact = false, pcss = false;
    bool reduced = false, shadow_blurred = false;
    u32 gbuffer_pass = 0;   ///< the G-buffer passes of the frame when the copy was taken
    u32 gbuffer_passes = 0; ///< the frame's G-buffer passes, set at its end (0: not yet)
    u32 passes_before = 0;  ///< the G-buffer passes of the frame before
    std::vector<ProbeReadItem> items; ///< cb0, cb1, cb3, cb4, depth, shadow
    // The copy. The host buffer is freed at a frame end once the rows are copied out of it.
    // stage: 0 on the GPU, 1 given to the thread, 2 rows copied out, 3 lines made. Only the
    // thread writes data and lines, and only before it sets stage 2 and 3.
    VkBuffer buffer = VK_NULL_HANDLE;
    VmaAllocation allocation{};
    const u8* mapped = nullptr;
    u64 bytes = 0, tick = 0;
    std::atomic<u32> stage{0};
    std::vector<u8> data;
    std::vector<std::string> lines;
};

const char* ProbeSunPathName(u8 path) {
    switch (path) {
    case 1:
        return "vsm";
    case 2:
        return "rt";
    case 3:
        return "rt-half";
    default:
        return "game";
    }
}

/// The lines of a readback whose rows are at `data` (null when nothing was read).
std::vector<std::string> ProbeReadLines(const ProbeReadJob& job, const u8* data) {
    std::vector<std::string> lines;
    const ProbeReadItem* depth = nullptr;
    for (const auto& item : job.items) {
        if (data && item.read && std::string_view(item.name) == "depth") {
            depth = &item;
        }
    }
    // A texel with no geometry: the depth target holds its clear value (0 or 1) at that place.
    // Rows are taken at the same heights of every target (the same count, evenly spaced); a
    // target of another width (a reduced proxy against the full-size depth) is scaled across.
    const auto background = [&](const ProbeReadItem& item, u32 row, u32 x) {
        if (!depth || depth->rows != item.rows || item.width == 0) {
            return false;
        }
        const u64 dx = std::min<u64>(u64(x) * depth->width / item.width, depth->width - 1);
        std::array<float, 4> d{};
        ProbeDecode(depth->texel,
                    data + depth->offset + row * depth->row_bytes +
                        dx * ProbeTexelBytes(depth->texel),
                    d);
        return d[0] == 0.0f || d[0] == 1.0f;
    };
    u64 depth_n = 0, depth_zero = 0, depth_one = 0;
    if (depth) {
        for (u32 row = 0; row < depth->rows; ++row) {
            for (u32 x = 0; x < depth->width; x += ProbeReadbackStep) {
                std::array<float, 4> d{};
                ProbeDecode(depth->texel,
                            data + depth->offset + row * depth->row_bytes +
                                u64(x) * ProbeTexelBytes(depth->texel),
                            d);
                ++depth_n;
                depth_zero += d[0] == 0.0f ? 1u : 0u;
                depth_one += d[0] == 1.0f ? 1u : 0u;
            }
        }
    }
    const auto share = [](u64 part, u64 whole) { return whole ? double(part) / double(whole) : 0.0; };
    // main=1: the copy came after the frame's last G-buffer pass (the main camera's; mirrored
    // passes come before it)
    const bool main = job.gbuffer_passes != 0 && job.gbuffer_pass == job.gbuffer_passes;
    lines.push_back(fmt::format(
        "[surface-probe] readback window={} frame={} t={:.1f} clock={} cam={} gbuffer_pass={}/{} "
        "main={} passes_before={} reduced={} rows={} column_step={} geometry_mask={} "
        "depth_zero={:.4f} depth_one={:.4f}",
        job.window, job.frame, job.t, job.clock, job.cam, job.gbuffer_pass,
        job.gbuffer_passes != 0 ? fmt::format("{}", job.gbuffer_passes) : std::string("?"),
        job.gbuffer_passes != 0 ? (main ? "1" : "0") : "?", job.passes_before,
        job.reduced ? 1 : 0, ProbeReadbackRows, ProbeReadbackStep, depth ? "depth" : "none",
        share(depth_zero, depth_n), share(depth_one, depth_n)));
    const float ray_gloss = ProbeGlossFor(0.7f);    // RAY_MAX_ROUGHNESS
    const float mirror_gloss = ProbeGlossFor(0.12f); // MIRROR_ROUGHNESS
    for (const auto& item : job.items) {
        const std::string_view name = item.name;
        const std::string format =
            item.format == vk::Format::eUndefined ? std::string("-") : vk::to_string(item.format);
        const bool shadow = name == "shadow";
        if (!data || !item.read) {
            lines.push_back(fmt::format("[surface-probe] {} window={} name={} read=0 why={} format={}",
                                        shadow ? "shadow" : "target", job.window, item.name,
                                        item.why, format));
            continue;
        }
        const u32 channels = ProbeChannels(item.texel);
        const u32 bytes = ProbeTexelBytes(item.texel);
        ProbeStats4 all, geo;
        std::array<u64, 16> hist{};
        u64 gloss_n = 0, rays = 0, mirror = 0;
        for (u32 row = 0; row < item.rows; ++row) {
            const u8* line = data + item.offset + row * item.row_bytes;
            for (u32 x = 0; x < item.width; x += ProbeReadbackStep) {
                std::array<float, 4> c{};
                ProbeDecode(item.texel, line + u64(x) * bytes, c);
                all.Add(c, channels);
                if (background(item, row, x)) {
                    continue;
                }
                geo.Add(c, channels);
                if (name == "cb1" && std::isfinite(c[0])) {
                    ++gloss_n;
                    ++hist[std::min<u32>(15u, u32(std::clamp(c[0], 0.0f, 1.0f) * 16.0f))];
                    rays += c[0] >= ray_gloss ? 1u : 0u;
                    mirror += c[0] >= mirror_gloss ? 1u : 0u;
                }
            }
        }
        const std::string size = fmt::format("{}x{}", item.width, item.height);
        if (shadow) {
            lines.push_back(fmt::format(
                "[surface-probe] shadow window={} frame={} sun_path={} sun_wanted={} rt_complete={} "
                "rt={} contact={} pcss={} from={} format={} size={} proxy={} samples={} "
                "geometry={} nonfinite={}{}{}",
                job.window, job.frame, ProbeSunPathName(job.sun_path), job.sun_wanted ? 1 : 0,
                job.rt_complete ? 1 : 0, job.rt_on ? 1 : 0, job.contact ? 1 : 0, job.pcss ? 1 : 0,
                job.shadow_blurred ? "blur" : "resolve", format, size, item.proxy ? 1 : 0, all.n,
                geo.n, all.nonfinite, geo.Text(channels, ""), all.Text(channels, "all_")));
            continue;
        }
        lines.push_back(fmt::format(
            "[surface-probe] target window={} name={} format={} size={} proxy={} samples={} "
            "geometry={} nonfinite={}{}{}",
            job.window, item.name, format, size, item.proxy ? 1 : 0, all.n, geo.n, all.nonfinite,
            geo.Text(channels, ""), all.Text(channels, "all_")));
        if (name == "cb1") {
            std::string text;
            for (u32 i = 0; i < 16; ++i) {
                text += fmt::format("{}{}", i ? "," : "", hist[i]);
            }
            lines.push_back(fmt::format(
                "[surface-probe] gloss window={} samples={} hist={} gloss_ssgi_rays={:.3f} "
                "share_ssgi_rays={:.4f} gloss_ssgi_mirror={:.3f} share_ssgi_mirror={:.4f} "
                "ssr_zero_weight=n/a",
                job.window, gloss_n, text, ray_gloss, share(rays, gloss_n), mirror_gloss,
                share(mirror, gloss_n)));
        }
    }
    return lines;
}

/// The readback's own thread (one a readback, started at a frame end once the GPU is past the
/// copy): it copies the rows out of the host buffer, then makes the lines. It touches only the
/// job, never the probe's state, the allocator or the engine's queues.
void ProbeReadWork(ProbeReadJob& job) {
    job.data.assign(job.mapped, job.mapped + job.bytes);
    job.stage.store(2, std::memory_order_release);
    job.lines = ProbeReadLines(job, job.data.data());
    job.data.clear();
    job.data.shrink_to_fit();
    job.stage.store(3, std::memory_order_release);
}

/// The eigenvalues (ascending) and eigenvectors (columns of v, same order) of a symmetric 3x3.
void ProbeEigen(std::array<std::array<double, 3>, 3> a, std::array<double, 3>& w,
                std::array<std::array<double, 3>, 3>& v) {
    v = {{{1.0, 0.0, 0.0}, {0.0, 1.0, 0.0}, {0.0, 0.0, 1.0}}};
    for (int sweep = 0; sweep < 50; ++sweep) {
        const double off = a[0][1] * a[0][1] + a[0][2] * a[0][2] + a[1][2] * a[1][2];
        if (off < 1e-30) {
            break;
        }
        for (int p = 0; p < 2; ++p) {
            for (int q = p + 1; q < 3; ++q) {
                if (std::abs(a[p][q]) < 1e-300) {
                    continue;
                }
                const double theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q]);
                const double t = (theta >= 0.0 ? 1.0 : -1.0) /
                                 (std::abs(theta) + std::sqrt(theta * theta + 1.0));
                const double c = 1.0 / std::sqrt(t * t + 1.0);
                const double s = t * c;
                for (int k = 0; k < 3; ++k) {
                    const double kp = a[k][p], kq = a[k][q];
                    a[k][p] = c * kp - s * kq;
                    a[k][q] = s * kp + c * kq;
                }
                for (int k = 0; k < 3; ++k) {
                    const double pk = a[p][k], qk = a[q][k];
                    a[p][k] = c * pk - s * qk;
                    a[q][k] = s * pk + c * qk;
                }
                for (int k = 0; k < 3; ++k) {
                    const double kp = v[k][p], kq = v[k][q];
                    v[k][p] = c * kp - s * kq;
                    v[k][q] = s * kp + c * kq;
                }
            }
        }
    }
    std::array<int, 3> order{0, 1, 2};
    std::sort(order.begin(), order.end(), [&](int x, int y) { return a[x][x] < a[y][y]; });
    const auto vectors = v;
    for (int i = 0; i < 3; ++i) {
        w[i] = a[order[i]][order[i]];
        for (int k = 0; k < 3; ++k) {
            v[k][i] = vectors[k][order[i]];
        }
    }
}

/// A plane fit of the vertices the triangles use (world positions, 4 floats a vertex): normal
/// (towards `eye` when given), distance (n.x + d = 0), RMS and largest distance from the plane
/// in cm (taking the world unit as the metre, as the ray traced code does), the size in the plane
/// along its two axes, how flat the triangles lie (area-weighted |cos| to the normal) and their
/// area.
std::string ProbeFitText(const float* world, const std::vector<u32>& indices, u32 count,
                         const std::array<double, 3>* eye) {
    std::vector<u8> used(count, 0);
    u64 bad_indices = 0, bad_vertices = 0;
    for (const u32 i : indices) {
        if (i < count) {
            used[i] = 1;
        } else {
            ++bad_indices;
        }
    }
    const auto at = [&](u32 i) {
        return std::array<double, 3>{world[std::size_t(i) * 4], world[std::size_t(i) * 4 + 1],
                                     world[std::size_t(i) * 4 + 2]};
    };
    const auto finite = [](const std::array<double, 3>& p) {
        return std::isfinite(p[0]) && std::isfinite(p[1]) && std::isfinite(p[2]);
    };
    double n = 0.0;
    std::array<double, 3> c{};
    for (u32 i = 0; i < count; ++i) {
        if (!used[i]) {
            continue;
        }
        const auto p = at(i);
        if (!finite(p)) {
            used[i] = 0;
            ++bad_vertices;
            continue;
        }
        n += 1.0;
        for (int k = 0; k < 3; ++k) {
            c[k] += p[k];
        }
    }
    if (n < 3.0) {
        return fmt::format("plane=none used_vertices={} bad_vertices={} bad_indices={}", u64(n),
                           bad_vertices, bad_indices);
    }
    for (int k = 0; k < 3; ++k) {
        c[k] /= n;
    }
    std::array<std::array<double, 3>, 3> cov{};
    for (u32 i = 0; i < count; ++i) {
        if (!used[i]) {
            continue;
        }
        const auto p = at(i);
        for (int r = 0; r < 3; ++r) {
            for (int k = 0; k < 3; ++k) {
                cov[r][k] += (p[r] - c[r]) * (p[k] - c[k]) / n;
            }
        }
    }
    std::array<double, 3> w{};
    std::array<std::array<double, 3>, 3> v{};
    ProbeEigen(cov, w, v);
    std::array<double, 3> normal{v[0][0], v[1][0], v[2][0]};
    if (eye) {
        const double side = normal[0] * ((*eye)[0] - c[0]) + normal[1] * ((*eye)[1] - c[1]) +
                            normal[2] * ((*eye)[2] - c[2]);
        if (side < 0.0) {
            normal = {-normal[0], -normal[1], -normal[2]};
        }
    }
    const auto dot = [](const std::array<double, 3>& x, const std::array<double, 3>& y) {
        return x[0] * y[0] + x[1] * y[1] + x[2] * y[2];
    };
    const std::array<double, 3> axis1{v[0][1], v[1][1], v[2][1]}, axis2{v[0][2], v[1][2], v[2][2]};
    double sq = 0.0, most = 0.0;
    std::array<double, 2> lo{1e300, 1e300}, hi{-1e300, -1e300};
    for (u32 i = 0; i < count; ++i) {
        if (!used[i]) {
            continue;
        }
        const auto p = at(i);
        const std::array<double, 3> d{p[0] - c[0], p[1] - c[1], p[2] - c[2]};
        const double off = dot(d, normal);
        sq += off * off;
        most = std::max(most, std::abs(off));
        const double u = dot(d, axis2), s = dot(d, axis1);
        lo[0] = std::min(lo[0], u);
        hi[0] = std::max(hi[0], u);
        lo[1] = std::min(lo[1], s);
        hi[1] = std::max(hi[1], s);
    }
    double area = 0.0, facing = 0.0;
    for (std::size_t t = 0; t + 2 < indices.size(); t += 3) {
        const u32 i0 = indices[t], i1 = indices[t + 1], i2 = indices[t + 2];
        if (i0 >= count || i1 >= count || i2 >= count || !used[i0] || !used[i1] || !used[i2]) {
            continue;
        }
        const auto a = at(i0), b = at(i1), e = at(i2);
        const std::array<double, 3> x{b[0] - a[0], b[1] - a[1], b[2] - a[2]};
        const std::array<double, 3> y{e[0] - a[0], e[1] - a[1], e[2] - a[2]};
        const std::array<double, 3> cross{x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2],
                                          x[0] * y[1] - x[1] * y[0]};
        const double len = std::sqrt(dot(cross, cross));
        area += 0.5 * len;
        facing += 0.5 * std::abs(dot(cross, normal));
    }
    return fmt::format(
        "normal={:.4f},{:.4f},{:.4f} dist={:.4f} rms_cm={:.3f} max_cm={:.3f} size={:.3f},{:.3f} "
        "facing={:.4f} area={:.4f} centre={:.3f},{:.3f},{:.3f} used_vertices={} bad_vertices={} "
        "bad_indices={}",
        normal[0], normal[1], normal[2], -dot(c, normal), 100.0 * std::sqrt(sq / n), 100.0 * most,
        hi[0] - lo[0], hi[1] - lo[1], area > 0.0 ? facing / area : 0.0, area, c[0], c[1], c[2],
        u64(n), bad_vertices, bad_indices);
}
} // namespace

namespace {
// bbport (t70b, t167, t171, t174, TOOL): Startup hide knobs skip selected direct draws.
// BB_REFLECT_PROBE_RECT reads a G-buffer rectangle once a second. These knobs require BB_SURFACE_PROBE=1.
constexpr u32 ReflectProbeRows = 32; ///< rows of the rectangle read (evenly spaced inside it)
constexpr u32 ReflectProbeCols = 64; ///< columns decoded of each row (evenly spaced across it)
constexpr double ReflectProbeSeconds = 1.0;

struct ReflectProbeItem {
    const char* name = "-";
    vk::Format format = vk::Format::eUndefined;
    ProbeTexel texel = ProbeTexel::None;
    u32 width = 0, height = 0; ///< the target (or its reduced proxy)
    u32 x0 = 0, cols = 0, y0 = 0, y1 = 0;
    u64 offset = 0, row_bytes = 0;
    bool read = false, proxy = false;
    const char* why = "-";
};

constexpr std::array ReflectProbeHideKnobs{
    "BB_REFLECT_PROBE_HIDE", "BB_REFLECT_PROBE_HIDE2", "BB_REFLECT_PROBE_HIDE3"};

constexpr const char* ReflectProbeHideRanges = "BB_REFLECT_PROBE_HIDE_RANGES";

struct ReflectProbeHidePair {
    bool on = false;
    u32 index_count = 0, first_index = 0; ///< zero count means legacy unrestricted selection
    u64 vs = 0, ps = 0;
    std::atomic<u64> skipped{0}, indirect{0}, pair_not_exact{0};
    u64 shown = 0;
};

struct ReflectProbeState {
    std::mutex lock;
    std::array<ReflectProbeHidePair, ReflectProbeHideKnobs.size()> hide{};
    bool rect_on = false;
    std::array<double, 4> rect{}; ///< as given
    bool started = false;
    u64 frames = 0;
    std::chrono::steady_clock::time_point start{}, last_hide{}, last_rect{};
    // The readback on its way (under `lock`).
    bool pending = false;
    std::vector<ReflectProbeItem> items; ///< cb0, cb1, depth
    VkBuffer buffer = VK_NULL_HANDLE;
    VmaAllocation allocation{};
    const u8* mapped = nullptr;
    u64 tick = 0, frame = 0;
    double t = 0.0;
    u32 ref_w = 0, ref_h = 0;
    std::array<double, 4> fraction{}; ///< the rectangle as fractions of the full-size G-buffer
    std::string clock, cam;
};

bool ReflectProbeParseExactPair(std::string_view text, ReflectProbeHidePair& pair) {
    const auto separator = text.find(':');
    if (separator == std::string_view::npos) {
        return false;
    }
    const auto parse_hash = [](std::string_view hash, u64& value) {
        if (hash.empty() || hash.size() > 16) {
            return false;
        }
        const auto end = hash.data() + hash.size();
        const auto parsed = std::from_chars(hash.data(), end, value, 16);
        return parsed.ec == std::errc{} && parsed.ptr == end;
    };
    return parse_hash(text.substr(0, separator), pair.vs) &&
           parse_hash(text.substr(separator + 1), pair.ps);
}

bool ReflectProbeParseRanges(std::string_view text, ReflectProbeState& s) {
    if (text.empty() || text.back() == ';') {
        return false;
    }
    for (std::size_t i = 0; i < s.hide.size(); ++i) {
        const auto item = ReflectionPart(text, ';');
        const auto shader_sep = item.find(':');
        if (shader_sep == std::string_view::npos) {
            return false;
        }
        const auto range_sep = item.find(':', shader_sep + 1);
        if (range_sep == std::string_view::npos) {
            return false;
        }
        auto& pair = s.hide[i];
        auto range = item.substr(range_sep + 1);
        if (!ReflectProbeParseExactPair(item.substr(0, range_sep), pair) ||
            !ReflectionNumber(ReflectionPart(range, ':'), pair.index_count) || pair.index_count == 0 ||
            !ReflectionNumber(range, pair.first_index)) {
            return false;
        }
        if (std::any_of(s.hide.begin(), s.hide.begin() + i, [&pair](const auto& prior) {
                return prior.vs == pair.vs && prior.ps == pair.ps;
            })) {
            std::printf("[reflect-probe] %s repeats shader pair %08llx:%08llx; all hides off\n",
                        ReflectProbeHideRanges, (unsigned long long)pair.vs, (unsigned long long)pair.ps);
            return false;
        }
    }
    if (!text.empty()) {
        return false;
    }
    for (auto& pair : s.hide) {
        pair.on = true;
    }
    return true;
}

void ReflectProbeParseLegacyHide(ReflectProbeState& s) {
    auto& primary = s.hide[0];
    if (const char* h = std::getenv("BB_REFLECT_PROBE_HIDE"); h && h[0]) {
        char* end = nullptr;
        const u64 vs = std::strtoull(h, &end, 16);
        if (end != h && *end == ':') {
            char* end_ps = nullptr;
            const u64 ps = std::strtoull(end + 1, &end_ps, 16);
            if (end_ps != end + 1) {
                primary.on = true;
                primary.vs = vs;
                primary.ps = ps;
            }
        }
    }
    for (std::size_t i = 1; i < s.hide.size(); ++i) {
        const char* knob = ReflectProbeHideKnobs[i];
        const char* text = std::getenv(knob);
        if (!text) {
            continue;
        }
        auto& pair = s.hide[i];
        if (!ReflectProbeParseExactPair(text, pair)) {
            std::printf("[reflect-probe] %s needs 1-16 hex digits per hash in vs:ps form; off\n", knob);
            continue;
        }
        const auto duplicate = std::find_if(s.hide.begin(), s.hide.end(), [&pair](const auto& prior) {
            return prior.on && prior.vs == pair.vs && prior.ps == pair.ps;
        });
        if (duplicate != s.hide.end()) {
            std::printf("[reflect-probe] %s duplicates %s; off\n", knob,
                        ReflectProbeHideKnobs[duplicate - s.hide.begin()]);
            continue;
        }
        pair.on = true;
    }
}

void ReflectProbeParse(ReflectProbeState& s) {
    if (const char* text = std::getenv(ReflectProbeHideRanges)) {
        if (std::any_of(ReflectProbeHideKnobs.begin(), ReflectProbeHideKnobs.end(),
                        [](const char* knob) { return std::getenv(knob) != nullptr; })) {
            std::printf("[reflect-probe] %s cannot be combined with legacy hide knobs; all hides off\n",
                        ReflectProbeHideRanges);
        } else if (!ReflectProbeParseRanges(text, s)) {
            std::printf("[reflect-probe] %s requires three unique hex vs:ps pairs with decimal count:first; all hides off\n",
                        ReflectProbeHideRanges);
        }
    } else {
        ReflectProbeParseLegacyHide(s);
    }
    if (const char* v = std::getenv("BB_REFLECT_PROBE_RECT"); v && v[0]) {
        std::array<double, 4> a{};
        u32 n = 0;
        const char* at = v;
        while (n < 4) {
            while (*at == ',' || *at == ';' || *at == ':' || *at == ' ') {
                ++at;
            }
            char* end = nullptr;
            const double d = std::strtod(at, &end);
            if (end == at) {
                break;
            }
            a[n++] = d;
            at = end;
        }
        if (n == 4 && a[0] >= 0.0 && a[1] >= 0.0 && a[2] > a[0] && a[3] > a[1]) {
            s.rect_on = true;
            s.rect = a;
        }
    }
}

ReflectProbeState& ReflectProbe() {
    static ReflectProbeState state;
    static std::once_flag once;
    std::call_once(once, [] { ReflectProbeParse(state); });
    return state;
}

void ReflectProbeAnnounce(bool surface_probe) {
    const bool asked_hide = std::getenv("BB_REFLECT_PROBE_HIDE");
    const bool asked_rect = std::getenv("BB_REFLECT_PROBE_RECT");
    const bool asked_extra = std::any_of(ReflectProbeHideKnobs.begin() + 1, ReflectProbeHideKnobs.end(),
                                         [](const char* knob) { return std::getenv(knob) != nullptr; });
    const bool asked_ranges = std::getenv(ReflectProbeHideRanges);
    if (!asked_hide && !asked_rect && !asked_extra && !asked_ranges) {
        return;
    }
    if (!surface_probe) {
        std::printf("[reflect-probe] a knob is set but BB_SURFACE_PROBE=1 is not: nothing happens\n");
        return;
    }
    const auto& s = ReflectProbe();
    const auto& primary = s.hide[0];
    if (asked_ranges) {
        for (const auto& pair : s.hide) {
            if (pair.on) {
                std::printf("[reflect-probe] %s on (%08llx:%08llx count=%u guest_first=%u), indexed direct draws only\n",
                            ReflectProbeHideRanges, (unsigned long long)pair.vs, (unsigned long long)pair.ps,
                            pair.index_count, pair.first_index);
            }
        }
        return;
    }
    if (asked_hide || asked_rect) {
        std::printf("[reflect-probe] on (t70b, TOOL, log only): hide=%s (%08llx:%08llx), rect=%s (%.3f,%.3f,%.3f,%.3f"
                    "; fractions when all four are 1 or less). A \"rect\" group of lines once a second, a \"hide\" "
                    "line once a second\n",
                    primary.on ? "on" : "off", (unsigned long long)primary.vs, (unsigned long long)primary.ps,
                    s.rect_on ? "on" : "off", s.rect[0], s.rect[1], s.rect[2], s.rect[3]);
        if ((asked_hide && !primary.on) || (asked_rect && !s.rect_on)) {
            std::printf("[reflect-probe] a knob was set but could not be read (HIDE is hex vs:ps; RECT is four numbers "
                        "x0;y0;x1;y1 with x1 > x0 and y1 > y0): that one is off\n");
        }
    }
    for (std::size_t i = 1; i < s.hide.size(); ++i) {
        const auto& pair = s.hide[i];
        if (pair.on) {
            std::printf("[reflect-probe] %s on (%08llx:%08llx), direct draws only\n", ReflectProbeHideKnobs[i],
                        (unsigned long long)pair.vs, (unsigned long long)pair.ps);
        }
    }
}

/// True when a direct draw matches an enabled pair and its optional guest index range.
bool ReflectProbeHide(u64 vs, u64 ps, bool indirect, bool indexed, u32 index_count, u32 first_index,
                      bool record) {
    for (auto& pair : ReflectProbe().hide) {
        if (!pair.on || vs != pair.vs || ps != pair.ps) {
            continue;
        }
        if (indirect) {
            if (record) pair.indirect.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
        if (pair.index_count != 0 &&
            (!indexed || index_count != pair.index_count || first_index != pair.first_index)) {
            if (record) pair.pair_not_exact.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
        if (record) pair.skipped.fetch_add(1, std::memory_order_relaxed);
        return true;
    }
    return false;
}

/// Stats of a channel over the samples added: min, max, mean and standard deviation.
struct ReflectProbeStats {
    std::array<double, 4> sum{}, sum2{};
    std::array<float, 4> lo{}, hi{};
    u64 n = 0;
    ReflectProbeStats() {
        lo.fill(std::numeric_limits<float>::infinity());
        hi.fill(-std::numeric_limits<float>::infinity());
    }
    void Add(const std::array<float, 4>& c, u32 channels) {
        for (u32 i = 0; i < channels; ++i) {
            if (!std::isfinite(c[i])) {
                return;
            }
        }
        ++n;
        for (u32 i = 0; i < channels; ++i) {
            sum[i] += c[i];
            sum2[i] += double(c[i]) * double(c[i]);
            lo[i] = std::min(lo[i], c[i]);
            hi[i] = std::max(hi[i], c[i]);
        }
    }
    std::string Text(u32 channels) const {
        static constexpr const char* names[] = {"r", "g", "b", "a"};
        std::string out;
        for (u32 i = 0; i < channels && i < 4; ++i) {
            if (n == 0) {
                out += fmt::format(" {}=-", names[i]);
                continue;
            }
            const double mean = sum[i] / double(n);
            const double var = std::max(0.0, sum2[i] / double(n) - mean * mean);
            out += fmt::format(" {}={:.4f},{:.4f},{:.4f},{:.4f}", names[i], lo[i], hi[i], mean, std::sqrt(var));
        }
        return out;
    }
};

/// The "rect" lines of a finished readback (r.mapped holds its rows; null: nothing was read).
std::vector<std::string> ReflectProbeLines(const ReflectProbeState& r) {
    std::vector<std::string> lines;
    constexpr u32 count = ReflectProbeRows * ReflectProbeCols;
    std::array<std::vector<std::array<float, 4>>, 3> samples;
    for (u32 i = 0; i < 3 && i < r.items.size(); ++i) {
        const ReflectProbeItem& item = r.items[i];
        if (!r.mapped || !item.read) {
            continue;
        }
        const u32 bytes = ProbeTexelBytes(item.texel);
        samples[i].reserve(count);
        for (u32 k = 0; k < ReflectProbeRows; ++k) {
            const u8* row = r.mapped + item.offset + u64(k) * item.row_bytes;
            for (u32 j = 0; j < ReflectProbeCols; ++j) {
                const u64 x = (u64(2 * j + 1) * item.cols) / (2ull * ReflectProbeCols);
                std::array<float, 4> c{};
                ProbeDecode(item.texel, row + x * bytes, c);
                samples[i].push_back(c);
            }
        }
    }
    const bool depth_ok = samples[2].size() == count;
    // A sample with geometry: its depth is not the clear value (0 or 1); with no depth, every sample.
    const auto geometry = [&](u32 s) {
        if (!depth_ok) {
            return true;
        }
        const float d = samples[2][s][0];
        return std::isfinite(d) && d != 0.0f && d != 1.0f;
    };
    u64 geo = 0;
    for (u32 s = 0; s < count; ++s) {
        geo += geometry(s) ? 1u : 0u;
    }
    lines.push_back(fmt::format(
        "[reflect-probe] rect t={:.1f} frame={} clock={} cam={} rect={:.3f},{:.3f},{:.3f},{:.3f} of {}x{} "
        "grid={}x{} samples={} geometry={} depth={}",
        r.t, r.frame, r.clock, r.cam, r.fraction[0], r.fraction[1], r.fraction[2], r.fraction[3], r.ref_w, r.ref_h,
        ReflectProbeRows, ReflectProbeCols, count, geo, depth_ok ? "yes" : "no"));
    const float mirror_gloss = ProbeGlossFor(0.12f); // MIRROR_ROUGHNESS, as the surface probe's gloss line
    for (u32 i = 0; i < 3 && i < r.items.size(); ++i) {
        const ReflectProbeItem& item = r.items[i];
        const std::string format =
            item.format == vk::Format::eUndefined ? std::string("-") : vk::to_string(item.format);
        if (samples[i].size() != count) {
            lines.push_back(fmt::format("[reflect-probe] rect-{} read=0 why={} format={}", item.name, item.why, format));
            continue;
        }
        const u32 channels = ProbeChannels(item.texel);
        ReflectProbeStats stats;
        for (u32 s = 0; s < count; ++s) {
            if (geometry(s)) {
                stats.Add(samples[i][s], channels);
            }
        }
        std::string extra;
        const std::string_view name = item.name;
        if (name == "cb0" && channels >= 3) {
            // A guess at the code: rgb*2-1 is the normal. Mean direction and the mean angle to it.
            std::vector<std::array<double, 3>> dirs;
            std::array<double, 3> sum{};
            for (u32 s = 0; s < count; ++s) {
                if (!geometry(s)) {
                    continue;
                }
                const auto& c = samples[i][s];
                std::array<double, 3> v{2.0 * c[0] - 1.0, 2.0 * c[1] - 1.0, 2.0 * c[2] - 1.0};
                const double len = std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
                if (!std::isfinite(len) || len < 1e-6) {
                    continue;
                }
                for (auto& x : v) {
                    x /= len;
                }
                dirs.push_back(v);
                for (u32 a = 0; a < 3; ++a) {
                    sum[a] += v[a];
                }
            }
            const double mean_len = std::sqrt(sum[0] * sum[0] + sum[1] * sum[1] + sum[2] * sum[2]);
            if (!dirs.empty() && mean_len > 1e-9) {
                const std::array<double, 3> m{sum[0] / mean_len, sum[1] / mean_len, sum[2] / mean_len};
                double angle = 0.0;
                for (const auto& v : dirs) {
                    angle += std::acos(std::clamp(v[0] * m[0] + v[1] * m[1] + v[2] * m[2], -1.0, 1.0));
                }
                extra = fmt::format(" normal_guess=({:.3f},{:.3f},{:.3f}) spread_deg={:.2f} (guess: rgb*2-1; read "
                                    "the raw ranges if cb0 is coded otherwise)",
                                    m[0], m[1], m[2], angle / double(dirs.size()) * 57.29577951308232);
            }
        } else if (name == "cb1") {
            u64 near_one = 0, mirror = 0, total = 0;
            for (u32 s = 0; s < count; ++s) {
                const float g = samples[i][s][0];
                if (!geometry(s) || !std::isfinite(g)) {
                    continue;
                }
                ++total;
                near_one += g >= 0.9375f ? 1u : 0u;
                mirror += g >= mirror_gloss ? 1u : 0u;
            }
            extra = fmt::format(" gloss_mean={:.4f} gloss_ge_0.9375={:.4f} gloss_ge_{:.3f}={:.4f}",
                                stats.n != 0 ? stats.sum[0] / double(stats.n) : 0.0,
                                total ? double(near_one) / double(total) : 0.0, mirror_gloss,
                                total ? double(mirror) / double(total) : 0.0);
        }
        lines.push_back(fmt::format("[reflect-probe] rect-{} format={} size={}x{} proxy={} px={},{},{},{} n={} "
                                    "(min,max,mean,std){}{}",
                                    item.name, format, item.width, item.height, item.proxy ? 1 : 0, item.x0, item.y0,
                                    item.x0 + item.cols, item.y1, stats.n, stats.Text(channels), extra));
    }
    return lines;
}
} // namespace

bool Rasterizer::SurfaceProbeWanted() {
    const char* value = std::getenv("BB_SURFACE_PROBE");
    const bool on = value && value[0] == '1' && value[1] == '\0';
    if (on) {
        std::printf("[surface-probe] on (BB_SURFACE_PROBE=1, r64): a \"new\" line per vertex and pixel "
                    "shader pair, pass and render state the first time it draws; every %u frames a "
                    "\"window\" line with the run time, clock time and camera, and for the first %llu "
                    "windows an \"active\", a \"lamps\" and a \"pair\" line for each pair whose draws "
                    "or vertices changed (at most %u a window); up to %u pairs. Log only: nothing drawn "
                    "changes. Unset it after the run\n",
                    ProbeWindowFrames, (unsigned long long)ProbeDetailWindows, ProbeMaxWindowLines,
                    ProbeMaxPairs);
        // bbport (r64b_surface-probe-more): BB_SURFACE_PROBE_PAIRS=vs:ps,vs:ps (hex, at most 20):
        // the pairs whose ray traced entries get a plane fit when built (without it: G-buffer
        // pairs whose pixel shader reads a cube map)
        auto& pairs = Probe().env_pairs;
        if (const char* list = std::getenv("BB_SURFACE_PROBE_PAIRS"); list && list[0]) {
            const char* at = list;
            while (*at && pairs.size() < ProbeMaxEnvPairs) {
                char* end = nullptr;
                const u64 vs = std::strtoull(at, &end, 16);
                if (end == at || *end != ':') {
                    break;
                }
                at = end + 1;
                const u64 ps = std::strtoull(at, &end, 16);
                if (end == at) {
                    break;
                }
                pairs.emplace_back(vs, ps);
                at = end;
                while (*at == ',' || *at == ';' || *at == ' ') {
                    ++at;
                }
            }
        }
        std::printf("[surface-probe] on-more (r64b): once a window a readback of 64 rows of the "
                    "G-buffer, its depth and the screen shadow target (read on another thread, no "
                    "wait); the ray traced scene, the draw order and the lamp record words every "
                    "window; plane fits of %s (at most %u a window). Log only\n",
                    pairs.empty() ? "G-buffer pairs that read a cube map"
                                  : "the pairs of BB_SURFACE_PROBE_PAIRS",
                    ProbeFitsPerWindow);
    }
    ReflectProbeAnnounce(on); // bbport (t70b_mirror-probe, TOOL): its note or its "on" line
    return on;
}

void Rasterizer::SurfaceProbeDraw(const GraphicsPipeline* pipeline, bool indirect) {
    auto& dc = Dc();
    const auto& regs = Regs();
    const auto& key = pipeline->GetGraphicsKey();
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    const u64 vs_hash = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
    const u64 ps_hash = ps ? ps->pgm_hash : 0;
    // The direct call records the original guest index offset in DrawInputs before binding.
    const auto& inputs = dc.draw_inputs;
    if (ReflectProbeHide(vs_hash, ps_hash, indirect, !indirect && inputs.pipeline == pipeline && inputs.is_indexed,
                         regs.num_indices, indirect ? 0 : inputs.index_offset)) {
        hang_proof_hide = true; // the engine's own leave-this-draw-out word (turned into effect_skip_draw after this call)
    }
    // The render state, hashed (FNV-1a) into one word that is part of the pair's key: on GCN blend,
    // write mask, depth, stencil and cull are set per draw, so a see-through pane or a blood layer
    // drawn with an opaque surface's shaders under another state gets a line of its own.
    u64 state_hash = 0xcbf29ce484222325ull;
    const auto mix = [&state_hash](u64 value) {
        state_hash = (state_hash ^ value) * 0x100000001b3ull;
    };
    // The draw's own targets, as PrepareRenderState bound them (cb_descs past the mask's slots
    // may hold an earlier draw's images: only the slots of the mask are read).
    u32 targets = 0, blend_bits = 0;
    for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
        if (((key.mrt_mask >> cb) & 1u) == 0 || !cb_descs[cb].first) {
            continue;
        }
        ++targets;
        const auto& b = regs.blend_control[cb];
        const bool on = b.enable && !regs.color_buffers[cb].info.blend_bypass;
        blend_bits |= on ? 1u << cb : 0u;
        mix(cb | (u32(on) << 4) | (regs.color_target_mask.GetMask(cb) << 5));
        if (on) {
            const u32 alpha = b.separate_alpha_blend
                                  ? 1u | (u32(b.alpha_src_factor) << 1) | (u32(b.alpha_func) << 6) |
                                        (u32(b.alpha_dst_factor) << 9)
                                  : 0u;
            mix(u32(b.color_src_factor) | (u32(b.color_func) << 5) | (u32(b.color_dst_factor) << 8) |
                (alpha << 13));
        }
    }
    const auto& depth_control = regs.depth_control;
    const u32 stencil = depth_control.stencil_enable
                            ? 1u | (u32(depth_control.stencil_ref_func) << 1) |
                                  (u32(depth_control.backface_enable) << 4) |
                                  (u32(depth_control.stencil_bf_func) << 5)
                            : 0u;
    mix(u32(depth_control.depth_enable) | (u32(depth_control.depth_write_enable) << 1) |
        (u32(depth_control.depth_func) << 2) | (stencil << 5) |
        (u32(regs.polygon_control.cull_front) << 13) | (u32(regs.polygon_control.cull_back) << 14) |
        (u32(regs.depth_shader_control.kill_enable) << 15) | (std::min(targets, 15u) << 16));
    const auto& depth_buffer = regs.depth_buffer;
    ProbePass pass = ProbePass::Other;
    if (std::popcount(key.mrt_mask) >= 5 && db_desc.first) {
        pass = ProbePass::GBuffer; // as gbuffer_draw (PrepareRenderState)
    } else if (db_desc.first && depth_buffer.Pitch() == depth_buffer.Height() &&
               depth_buffer.Height() >= 1024) {
        pass = ProbePass::Shadow; // as RtShadow::Draw::shadow_pass (EffectsCaptureDraw)
    } else if (db_desc.first && camera_motion->Enabled() && db_desc.first == camera_motion->Depth() &&
               std::popcount(key.mrt_mask) <= 2 && ((key.mrt_mask & 1u) != 0) && cb_descs[0].first) {
        // The scene colour: a full-size RGBA16F target drawn with the scene depth (as
        // PrepareRenderState's test before upscaler->OnSceneColor).
        const auto& colour = texture_cache.GetImage(cb_descs[0].first);
        const auto& depth = texture_cache.GetImage(db_desc.first);
        if (colour.info.pixel_format == vk::Format::eR16G16B16A16Sfloat &&
            colour.info.size.width == depth.info.size.width &&
            colour.info.size.height == depth.info.size.height) {
            pass = ProbePass::Forward;
        }
    }
    // The textures: dc.bound_images lists the draw's colour targets, then its depth target
    // (PrepareRenderState), then every stage's images (BindResources). BeginRendering appends a
    // target it had to find again (needs_rebind) after them, so an image that is one of the draw's
    // own targets is kept apart ("own"): either that, or the draw reads what it draws into.
    const u32 own = targets + (db_desc.first ? 1u : 0u);
    const VideoCore::ImageId scene_colour =
        upscaler->Enabled() ? upscaler->SceneColor() : VideoCore::ImageId{};
    const VideoCore::ImageId scene_depth =
        camera_motion->Enabled() ? camera_motion->Depth() : VideoCore::ImageId{};
    const VAddr colour_at = scene_colour ? texture_cache.GetImage(scene_colour).info.guest_address : 0;
    const VAddr depth_at = scene_depth ? texture_cache.GetImage(scene_depth).info.guest_address : 0;
    u32 textures = 0, reads_colour = 0, reads_depth = 0, reads_target = 0, reads_own = 0;
    const auto kind_of = [&](VideoCore::ImageId id, const VideoCore::Image& image) {
        if (db_desc.first && id == db_desc.first) {
            return 4; // the draw's own depth target
        }
        for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
            if (((key.mrt_mask >> cb) & 1u) != 0 && cb_descs[cb].first == id) {
                return 4; // one of the draw's own colour targets
            }
        }
        const VAddr at = image.info.guest_address;
        if ((scene_colour && id == scene_colour) || (colour_at != 0 && at == colour_at)) {
            return 1; // the scene colour (or an image at its address)
        }
        if ((scene_depth && id == scene_depth) || (depth_at != 0 && at == depth_at) ||
            (previous_scene_depth && id == previous_scene_depth)) {
            return 2; // the scene depth, this frame's or the last one's
        }
        return image.usage.render_target || image.usage.depth_target ? 3 : 0;
    };
    for (std::size_t i = own; i < dc.bound_images.size(); ++i) {
        const auto id = dc.bound_images[i];
        const int kind = kind_of(id, texture_cache.GetImage(id));
        ++textures;
        reads_colour += kind == 1 ? 1u : 0u;
        reads_depth += kind == 2 ? 1u : 0u;
        reads_target += kind == 3 ? 1u : 0u;
        reads_own += kind == 4 ? 1u : 0u;
    }
    mix(std::min(textures, 31u) | (std::min(reads_colour, 1u) << 5) | (std::min(reads_depth, 1u) << 6) |
        (std::min(reads_target, 1u) << 7) | (std::min(reads_own, 1u) << 8));
    const u32 state = u32(state_hash ^ (state_hash >> 32));
    // Whether the ray traced scene took the draw. EffectsCaptureDraw ran just before: its
    // answer is in motion_param (the high half when the pipeline also writes motion vectors).
    const u32 mode = key.motion_vectors;
    u32 param = dc.push_data.motion_param;
    if ((mode & Shader::MotionVectors::VertexBoth) == Shader::MotionVectors::VertexBoth) {
        param >>= 16;
    }
    const bool solid = regs.depth_control.depth_write_enable != 0 && !regs.blend_control[0].enable;
    const bool discard = ps && ps->has_discard;
    const u32 instances = regs.num_instances.NumInstances();
    const bool triangles = regs.primitive_type == AmdGpu::PrimitiveType::TriangleStrip ||
                           regs.primitive_type == AmdGpu::PrimitiveType::TriangleList;
    bool captured = false;
    const char* rt;
    // (the order of RtShadow::PrepareDraw's tests; what it does not say is "other")
    if (indirect) {
        rt = "dropped:indirect";
    } else if (!dc.capture_draw) {
        rt = "dropped:no-capture-pipeline";
    } else if (!rt_shadow->Wanted()) {
        rt = "off";
    } else if (!dc.motion_geometry) {
        rt = "dropped:no-geometry";
    } else if (param != 0) {
        captured = true;
        rt = pass == ProbePass::GBuffer ? "captured:camera" : "captured:sun";
    } else if (!solid) {
        rt = "dropped:not-solid";
    } else if (discard && pass != ProbePass::Shadow) {
        rt = "dropped:cut-out-camera-pass";
    } else if (!triangles) {
        rt = "dropped:not-triangles";
    } else if (instances > ProbeMaxInstances) {
        rt = "dropped:over-64-instances";
    } else {
        rt = "dropped:other";
    }
    const u64 vertices = indirect ? 0 : u64(regs.num_indices) * instances;
    // bbport (r64b_surface-probe-more): the ray traced scene entry this draw reached, if any
    // (taken at every draw so none is left for the next; an indirect draw has none)
    RtShadow::ProbeDraw rt_entry = rt_shadow->ProbeTakeDraw();
    if (indirect) {
        rt_entry = {};
    }

    auto& p = Probe();
    std::scoped_lock guard{p.lock};
    if (p.frame == 0 && ++p.draws_before_frame_end == ProbeNoFrameEndDraws) {
        // Printed in place (no report capture is open on a draw).
        std::printf("[surface-probe] warning: %llu draws and no frame end yet. The probe prints at the "
                    "display pass, which the engine marks only while the upscaler (BB_UPSCALER unset) "
                    "or the motion overlay is on; this run will print nothing more\n",
                    (unsigned long long)ProbeNoFrameEndDraws);
    }
    u32 gbuffer_index = 0;
    if (pass == ProbePass::GBuffer) {
        if (db_desc.first != p.gbuffer_depth) { // another depth target: another G-buffer pass
            p.gbuffer_depth = db_desc.first;
            ++p.gbuffer_passes;
        }
        gbuffer_index = std::min<u32>(p.gbuffer_passes - 1, 7u);
    }
    // bbport (r64b_surface-probe-more): the draw's number in the frame, the targets of the frame's
    // last G-buffer pass, the screen shadow target (the shadow resolve's target, then the blur's
    // when the blur reads it, as ContactShadow follows it) and the water's draws
    const u64 seq = ++p.frame_draw;
    if (pass == ProbePass::GBuffer) {
        for (u32 cb = 0; cb < 5; ++cb) {
            p.gb[cb] = ((key.mrt_mask >> cb) & 1u) != 0 ? cb_descs[cb].first : VideoCore::ImageId{};
        }
        p.gb_depth = db_desc.first;
        p.now.gb_first = p.now.gb_first != 0 ? p.now.gb_first : seq;
        p.now.gb_last = seq;
    }
    if (ps_hash == ShadowResolveHash && cb_descs[0].first) {
        p.shadow_target = cb_descs[0].first;
        p.shadow_ps = ps_hash;
    } else if (ps_hash == ShadowBlurHash && cb_descs[0].first && p.shadow_target && ps &&
               !ps->images.empty() &&
               ps->images[0].GetSharp(*ps).Address() ==
                   texture_cache.GetImage(p.shadow_target).info.guest_address) {
        p.shadow_target = cb_descs[0].first;
        p.shadow_ps = ps_hash;
    }
    if (ps_hash == ProbeWaterPsHash) {
        ++p.now.water_draws;
        p.now.water_first = p.now.water_first != 0 ? p.now.water_first : seq;
        p.now.water_last = seq;
        p.water_zwrite |= depth_control.depth_write_enable ? 2u : 1u;
    }
    const ProbeKey k{vs_hash, ps_hash, pass, state};
    ProbeEntry* e;
    u32 at;
    if (const auto found = p.index.find(k); found != p.index.end()) {
        at = found->second;
        e = &p.entries[at];
    } else {
        if (p.entries.size() >= ProbeMaxPairs) {
            ++p.untracked;
            return;
        }
        at = u32(p.entries.size());
        p.index.emplace(k, at);
        e = &p.entries.emplace_back();
        e->key = k;
        e->water = ps_hash == ProbeWaterPsHash;
        e->first_window = p.window + 1;
        ++p.new_pairs;
        // The facts, once per pair (the only formatting a draw does).
        std::string formats, blend, mask;
        for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
            if (((key.mrt_mask >> cb) & 1u) == 0 || !cb_descs[cb].first) {
                continue;
            }
            const auto& image = texture_cache.GetImage(cb_descs[cb].first);
            const auto& b = regs.blend_control[cb];
            formats += fmt::format("{}{}", formats.empty() ? "" : ",", vk::to_string(image.info.pixel_format));
            std::string how = b.enable ? "bypass" : "off";
            if (((blend_bits >> cb) & 1u) != 0) {
                how = fmt::format("{}/{}/{}", ProbeFactor(u32(b.color_src_factor)),
                                  ProbeBlendFunc(u32(b.color_func)), ProbeFactor(u32(b.color_dst_factor)));
                if (b.separate_alpha_blend) {
                    how += fmt::format("+a:{}/{}/{}", ProbeFactor(u32(b.alpha_src_factor)),
                                       ProbeBlendFunc(u32(b.alpha_func)),
                                       ProbeFactor(u32(b.alpha_dst_factor)));
                }
            }
            blend += fmt::format("{}cb{}:{}", blend.empty() ? "" : ",", cb, how);
            const u32 m = regs.color_target_mask.GetMask(cb);
            mask += fmt::format("{}cb{}:{}{}{}{}{}", mask.empty() ? "" : ",", cb, (m & 1u) ? "R" : "",
                                (m & 2u) ? "G" : "", (m & 4u) ? "B" : "", (m & 8u) ? "A" : "",
                                m == 0 ? "-" : "");
        }
        std::string size = "-", depth = "-";
        for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
            if (((key.mrt_mask >> cb) & 1u) != 0 && cb_descs[cb].first) {
                const auto& image = texture_cache.GetImage(cb_descs[cb].first);
                size = fmt::format("{}x{}", image.info.size.width, image.info.size.height);
                break;
            }
        }
        if (db_desc.first) {
            const auto& image = texture_cache.GetImage(db_desc.first);
            depth = fmt::format("{}:{}x{}", vk::to_string(image.info.pixel_format),
                                image.info.size.width, image.info.size.height);
        }
        const std::string stencil_text =
            !depth_control.stencil_enable
                ? std::string("off")
                : depth_control.backface_enable
                      ? fmt::format("{}/bf:{}", ProbeCompare(u32(depth_control.stencil_ref_func)),
                                    ProbeCompare(u32(depth_control.stencil_bf_func)))
                      : std::string(ProbeCompare(u32(depth_control.stencil_ref_func)));
        static constexpr const char* culls[] = {"none", "front", "back", "both"};
        const char* cull =
            culls[u32(regs.polygon_control.cull_front) | (u32(regs.polygon_control.cull_back) << 1)];
        std::string list;
        for (std::size_t i = own; i < dc.bound_images.size() && i < own + ProbeMaxTextures; ++i) {
            const auto id = dc.bound_images[i];
            const auto& image = texture_cache.GetImage(id);
            static constexpr const char* tags[] = {"", ":scene-colour", ":scene-depth", ":target",
                                                   ":own"};
            list += fmt::format("{}{}:{}x{}{}{}", list.empty() ? "" : ",",
                                vk::to_string(image.info.pixel_format), image.info.size.width,
                                image.info.size.height,
                                image.info.resources.layers > 1
                                    ? fmt::format("x{}", image.info.resources.layers)
                                    : std::string{},
                                tags[kind_of(id, image)]);
        }
        u32 cubes = 0;
        for (std::size_t i = 0; ps && i < ps->images.size(); ++i) {
            const auto& resource = ps->images[i];
            cubes += resource.post_op == Shader::SharpFetchPostOp::ConvertCubeTo2DArray ||
                             resource.GetSharp(*ps).IsCube()
                         ? 1u
                         : 0u;
        }
        e->cube = cubes; // bbport (r64b_surface-probe-more)
        e->facts = fmt::format(
            "targets={} formats={} size={} mask={} depth={} blend={} ztest={} zwrite={} zfunc={} "
            "stencil={} cull={} discard={} kill={} a2c=n/a solid={} rt={} tex={} scene_colour={} "
            "scene_depth={} target_tex={} own_tex={} cube={} textures={} prim={} indices={} "
            "instances={} water={}",
            targets, formats.empty() ? "-" : formats, size, mask.empty() ? "-" : mask, depth,
            blend.empty() ? "-" : blend, u32(depth_control.depth_enable),
            u32(depth_control.depth_write_enable), ProbeCompare(u32(depth_control.depth_func)),
            stencil_text, cull, discard ? 1 : 0, u32(regs.depth_shader_control.kill_enable),
            solid ? 1 : 0, rt, textures, reads_colour, reads_depth, reads_target, reads_own, cubes,
            list.empty() ? "-" : list, u32(regs.primitive_type), indirect ? 0u : regs.num_indices,
            instances, e->water ? 1 : 0);
    }
    if (!e->touched) {
        e->touched = true;
        e->gbuffer_passes = 0;
        p.touched.push_back(at);
    }
    ++e->draws;
    ++e->total;
    e->vertices += vertices;
    e->indirect += indirect ? 1u : 0u;
    if (!indirect) {
        e->index_min = std::min<u32>(e->index_min, regs.num_indices);
        e->index_max = std::max<u32>(e->index_max, regs.num_indices);
    }
    if (captured) {
        ++e->captured;
    } else {
        e->drop = rt;
    }
    // bbport (r64b_surface-probe-more): the ray traced scene entry the draw reached. A plane fit
    // of its world triangles when this draw builds it: for a pair named in BB_SURFACE_PROBE_PAIRS,
    // else (no list) for a G-buffer pair whose pixel shader reads a cube map (a reflective
    // candidate), static and of at most ProbeFitAutoTriangles triangles. Each entry once, at most
    // ProbeFitsPerWindow a window and only in the windows printed in full, ProbeFitSlots on their
    // way at once.
    if (rt_entry.key != 0) {
        ++e->rt_in;
        e->rt_key = rt_entry.key;
        e->rt_tris_min = std::min(e->rt_tris_min, rt_entry.triangles);
        e->rt_tris_max = std::max(e->rt_tris_max, rt_entry.triangles);
        if (rt_entry.skinned) {
            // A skinned entry: its pair (for "rt-skinned"), and this window's samples of its guest
            // index list (RtShadow hashes it in the frames probe_hash_skinned names)
            auto found = p.skins.find(rt_entry.key);
            if (found == p.skins.end() && p.skins.size() < ProbeMaxSkins) {
                found = p.skins.emplace(rt_entry.key, ProbeState::Skin{}).first;
            }
            if (found != p.skins.end()) {
                ProbeState::Skin& skin = found->second;
                skin.pair = at + 1;
                if (skin.window != p.window) {
                    skin.window = p.window;
                    skin.last_hash = 0;
                    skin.samples = skin.changes = 0;
                }
                if (rt_entry.guest_hash != 0) {
                    ++skin.samples;
                    skin.changes += skin.last_hash != 0 && skin.last_hash != rt_entry.guest_hash ? 1u : 0u;
                    skin.last_hash = rt_entry.guest_hash;
                }
            }
        }
        const bool listed =
            !p.env_pairs.empty() &&
            std::find(p.env_pairs.begin(), p.env_pairs.end(), std::pair<u64, u64>{vs_hash, ps_hash}) !=
                p.env_pairs.end();
        const bool candidate =
            listed || (p.env_pairs.empty() && pass == ProbePass::GBuffer && e->cube != 0 &&
                       !rt_entry.skinned && !rt_entry.dynamic &&
                       rt_entry.triangles <= ProbeFitAutoTriangles);
        if (rt_entry.build != 0 && candidate && rt_entry.indices && rt_entry.triangles != 0 &&
            rt_entry.triangles <= ProbeFitMaxTriangles &&
            u64(rt_entry.vertices) * rt_entry.instances <= RtShadow::ProbeSlotVertices &&
            p.window < ProbeDetailWindows && p.fits_window < ProbeFitsPerWindow &&
            p.fitted.size() < ProbeMaxFitted &&
            !p.fitted.contains(rt_entry.key)) {
            ++p.fits_asked;
            u32 slot = 0;
            while (slot < ProbeFitSlots && p.fits[slot].active) {
                ++slot;
            }
            if (slot == ProbeFitSlots) {
                ++p.fits_no_slot;
            } else if (rt_shadow->ProbeCopyBuild(rt_entry.build, slot)) {
                ProbeState::Fit& f = p.fits[slot];
                f = {};
                f.active = true;
                f.listed = listed;
                f.skinned = rt_entry.skinned;
                f.pass = pass;
                f.id = at;
                f.triangles = rt_entry.triangles;
                f.vertices = rt_entry.vertices;
                f.instances = rt_entry.instances;
                f.vs = vs_hash;
                f.ps = ps_hash;
                f.key = rt_entry.key;
                f.frame = p.frame + 1;
                f.indices.assign(rt_entry.indices,
                                 rt_entry.indices + std::size_t(rt_entry.triangles) * 3);
                p.fitted.insert(rt_entry.key);
                ++p.fits_window;
            }
        }
    }
    if (pass == ProbePass::GBuffer) {
        e->gbuffer_passes |= u8(1u << gbuffer_index);
    }
}

void Rasterizer::SurfaceProbeLamps(const u32* lights, u32 count) {
    auto& p = Probe();
    std::scoped_lock guard{p.lock};
    // bbport (r64b_surface-probe-more): the lamp pass's place in the frame (its tiles' draws; this
    // runs before the tile's draw is counted, so its number is the next one)
    const u64 seq = p.frame_draw + 1;
    p.now.lamp_first = p.now.lamp_first != 0 ? p.now.lamp_first : seq;
    p.now.lamp_last = seq;
    for (u32 i = 0; i < count; ++i) {
        // A lamp record: position words 0-2, 1 / reach squared word 3, colour words 4-6
        // (point_shadow_ray.comp). Each tile repeats the lamps that reach it.
        const u32* r = lights + std::size_t(i) * 16;
        const float inv_r2 = std::bit_cast<float>(r[3]);
        if (!(inv_r2 > 0.0f)) {
            continue;
        }
        ++p.lamp_records;
        // bbport (r64b_surface-probe-more): words 7-11 of each record (a spot cone may be kept
        // there): their range as floats and as words
        ++p.word_records;
        bool zero = true;
        for (u32 j = 0; j < 5; ++j) {
            const u32 word = r[7 + j];
            zero = zero && word == 0;
            p.word_umin[j] = std::min(p.word_umin[j], word);
            p.word_umax[j] = std::max(p.word_umax[j], word);
            const float value = std::bit_cast<float>(word);
            if (!std::isfinite(value)) {
                ++p.word_nonfinite;
                continue;
            }
            p.word_min[j] = std::min(p.word_min[j], value);
            p.word_max[j] = std::max(p.word_max[j], value);
        }
        p.word_zero += zero ? 1u : 0u;
        std::array<u32, 7> words{};
        std::memcpy(words.data(), r, sizeof(words));
        if (std::find(p.lamps.begin(), p.lamps.end(), words) != p.lamps.end()) {
            continue;
        }
        if (p.lamps.size() < ProbeMaxLamps) {
            p.lamps.push_back(words);
            // bbport (r64b_surface-probe-more): a lamp with a negative colour (it takes light away)
            p.lamps_negative += std::bit_cast<float>(words[4]) < 0.0f ||
                                        std::bit_cast<float>(words[5]) < 0.0f ||
                                        std::bit_cast<float>(words[6]) < 0.0f
                                    ? 1u
                                    : 0u;
        } else {
            ++p.lamps_over;
        }
    }
}

void Rasterizer::SurfaceProbeWater(const u64* counts, u32 count) {
    auto& p = Probe();
    std::scoped_lock guard{p.lock};
    for (u32 i = 0; i < count; ++i) {
        p.water_samples += counts[i];
    }
    p.water_queries += count;
}

void Rasterizer::SurfaceProbeFrameEnd() {
    auto& p = Probe();
    std::scoped_lock guard{p.lock};
    const auto now = std::chrono::steady_clock::now();
    if (p.frame == 0) {
        p.start = p.window_start = now;
    }
    ++p.frame;
    ++p.window_frames;
    // The run time, the clock time and the camera, so the lines can be matched to where the
    // player stood. The clock and the camera are formatted only when a line is printed.
    const double t = std::chrono::duration<double>(now - p.start).count();
    std::string clock_time, cam;
    const auto clock_text = [&]() -> const char* {
        if (clock_time.empty()) {
            clock_time = ProbeClock();
        }
        return clock_time.c_str();
    };
    const auto cam_text = [&]() -> const char* {
        if (cam.empty()) {
            // The frame's camera (CommitFrameCamera ran in OnDisplayPass just before): the view to
            // world matrix's translation, in the game's world units.
            const auto m = camera_motion->CameraMatrices();
            cam = m.valid ? fmt::format("{:.2f},{:.2f},{:.2f}", m.inv_view[3], m.inv_view[7],
                                        m.inv_view[11])
                          : std::string("-");
        }
        return cam.c_str();
    };
    // A mirrored frame: several G-buffer passes that CameraMotion took for a water reflection
    // (the same x and z, another height; OnDisplayPass ran just before this). The frame's last
    // pass is the main camera's ("the last pass's camera goes with its depth"); the earlier ones
    // are the mirrored ones (a guess from that line, not checked).
    const bool mirrored = p.gbuffer_passes > 1 && camera_motion->Enabled() && !camera_motion->PreviewFrame();
    p.multi_frames += p.gbuffer_passes > 1 ? 1u : 0u;
    p.mirrored_frames += mirrored ? 1u : 0u;
    const u8 last = u8(1u << std::min<u32>(p.gbuffer_passes > 0 ? p.gbuffer_passes - 1 : 0, 7u));
    for (const u32 at : p.touched) {
        ProbeEntry& e = p.entries[at];
        e.touched = false;
        const bool in_mirror = mirrored && (e.gbuffer_passes & ~last) != 0;
        const bool in_main = !mirrored || e.key.pass != ProbePass::GBuffer || (e.gbuffer_passes & last) != 0;
        e.mirrored_frames += in_mirror ? 1u : 0u;
        e.main_frames += in_main ? 1u : 0u;
        if (!e.printed) {
            e.printed = true;
            u32 first = 0;
            while (first < 8 && ((e.gbuffer_passes >> first) & 1u) == 0) {
                ++first;
            }
            const std::string where =
                e.key.pass == ProbePass::GBuffer
                    ? fmt::format(" gbuffer_pass={}/{}", first + 1, p.gbuffer_passes)
                    : std::string{};
            BbReport::Printf("[surface-probe] new id=%u window=%llu frame=%llu t=%.1f clock=%s vs=%08llx "
                             "ps=%08llx pass=%s state=%08x%s draws=%llu captured=%llu cam=%s %s\n",
                             at, (unsigned long long)e.first_window, (unsigned long long)p.frame, t,
                             clock_text(), (unsigned long long)e.key.vs, (unsigned long long)e.key.ps,
                             e.key.pass == ProbePass::GBuffer && in_mirror
                                 ? (in_main ? "gbuffer+mirrored" : "mirrored")
                                 : ProbePassName(e.key.pass),
                             e.key.state, where.c_str(), (unsigned long long)e.draws,
                             (unsigned long long)e.captured, cam_text(), e.facts.c_str());
            e.facts.clear();
            e.facts.shrink_to_fit();
        }
    }
    p.touched.clear();
    // bbport (r64b_surface-probe-more): this frame's G-buffer passes, before they are reset. The
    // next frame's readback waits for as many; a readback of this frame says which pass it read.
    p.passes_last = p.gbuffer_passes;
    p.now.passes = p.gbuffer_passes;
    if (p.readback && p.readback->frame == p.frame) {
        p.readback->gbuffer_passes = p.gbuffer_passes;
    }
    p.gbuffer_depth = {};
    p.gbuffer_passes = 0;
    // bbport (r64b_surface-probe-more): this frame's draw order (the water against the lamp pass),
    // the plane fits whose world positions are back, the readback, and the state kept for one
    // frame.
    p.now.frame = p.frame;
    p.now.draws = p.frame_draw;
    if (p.now.water_draws != 0) {
        ++p.water_frames;
        p.water_draws += p.now.water_draws;
        p.water_draws_max = std::max(p.water_draws_max, p.now.water_draws);
        if (p.now.lamp_first == 0) {
            ++p.water_alone;
        } else if (p.now.water_last < p.now.lamp_first) {
            ++p.water_before;
        } else if (p.now.water_first > p.now.lamp_last) {
            ++p.water_after;
        } else {
            ++p.water_among;
        }
        p.order_water = p.now;
    }
    p.order_last = p.now;
    p.now = {};
    p.frame_draw = 0;
    p.blended_seen = false;
    p.gb = {};
    p.gb_depth = {};
    p.shadow_target = {};
    p.shadow_ps = 0;
    rt_shadow->probe_sun_path = 0;
    for (u32 s = 0; s < ProbeFitSlots; ++s) {
        ProbeState::Fit& f = p.fits[s];
        if (!f.active) {
            continue;
        }
        u64 tick = 0;
        const float* world = rt_shadow->ProbeWorld(s, tick);
        if (tick == RtShadow::ProbeDroppedTick) {
            // The build was dropped before it was recorded (its draw left out, or no RecordBuilds
            // came before the scene's frame end). The entry is built again at its next draw, so
            // its key is asked again then.
            BbReport::Printf("[surface-probe] fit id=%u vs=%08llx ps=%08llx rt_key=%016llx "
                             "built_frame=%llu frame=%llu lost=1 why=build-dropped\n",
                             f.id, (unsigned long long)f.vs, (unsigned long long)f.ps,
                             (unsigned long long)f.key, (unsigned long long)f.frame,
                             (unsigned long long)p.frame);
            ++p.fits_dropped;
            p.fitted.erase(f.key);
            rt_shadow->ProbeForget(s);
            f = {};
            continue;
        }
        if (!world || tick == 0 || !scheduler.IsFree(tick)) {
            if (p.frame > f.frame + ProbeFitWaitFrames) {
                BbReport::Printf("[surface-probe] fit id=%u vs=%08llx ps=%08llx rt_key=%016llx "
                                 "built_frame=%llu frame=%llu lost=1 why=%s\n",
                                 f.id, (unsigned long long)f.vs, (unsigned long long)f.ps,
                                 (unsigned long long)f.key, (unsigned long long)f.frame,
                                 (unsigned long long)p.frame,
                                 tick == 0 ? "copy-not-recorded" : "gpu-not-past");
                ++p.fits_lost;
                rt_shadow->ProbeForget(s);
                f = {};
            }
            continue;
        }
        const auto m = camera_motion->CameraMatrices();
        const std::array<double, 3> eye{m.inv_view[3], m.inv_view[7], m.inv_view[11]};
        const std::string fit = ProbeFitText(world, f.indices, f.vertices * f.instances,
                                             m.valid ? &eye : nullptr);
        BbReport::Printf("[surface-probe] fit id=%u vs=%08llx ps=%08llx pass=%s why=%s "
                         "rt_key=%016llx tris=%u verts=%u instances=%u skinned=%d built_frame=%llu "
                         "frame=%llu t=%.1f clock=%s cam=%s %s\n",
                         f.id, (unsigned long long)f.vs, (unsigned long long)f.ps,
                         ProbePassName(f.pass), f.listed ? "listed" : "cube", (unsigned long long)f.key,
                         f.triangles, f.vertices, f.instances, f.skinned ? 1 : 0,
                         (unsigned long long)f.frame, (unsigned long long)p.frame, t, clock_text(),
                         cam_text(), fit.c_str());
        ++p.fits_done;
        rt_shadow->ProbeForget(s);
        f = {};
    }
    // The readback: once the GPU is past its copy, a thread of its own copies the rows out and
    // makes the lines (ProbeReadWork). The host buffer is freed here once the rows are out, and
    // the lines are taken here once made. Nothing waits for the GPU or for the thread.
    if (p.readback) {
        ProbeReadJob& job = *p.readback;
        if (job.stage.load(std::memory_order_acquire) == 0 && scheduler.IsFree(job.tick)) {
            vmaInvalidateAllocation(instance.GetAllocator(), job.allocation, 0, VK_WHOLE_SIZE);
            job.stage.store(1, std::memory_order_relaxed);
            try {
                std::thread([held = p.readback] { ProbeReadWork(*held); }).detach();
            } catch (...) {
                for (auto& item : job.items) {
                    if (item.read) {
                        item.read = false;
                        item.why = "no-thread";
                    }
                }
                job.lines = ProbeReadLines(job, nullptr);
                job.stage.store(3, std::memory_order_release);
            }
        }
        const u32 stage = job.stage.load(std::memory_order_acquire);
        if (stage >= 2 && job.buffer) {
            vmaDestroyBuffer(instance.GetAllocator(), job.buffer, job.allocation);
            job.buffer = VK_NULL_HANDLE;
        }
        if (stage == 3) {
            for (auto& line : job.lines) {
                p.readback_lines.push_back(std::move(line));
            }
            p.readback.reset();
        }
    }
    // The skinned draws' guest index lists are hashed in the next frame every
    // ProbeSkinHashFrames frames (the windows printed in full only).
    rt_shadow->probe_hash_skinned =
        p.window < ProbeDetailWindows && (p.frame + 1) % ProbeSkinHashFrames == 0;
    if (!p.lamps.empty()) {
        ++p.lamp_frames;
        p.lamps_sum += p.lamps.size();
        p.lamps_max = std::max<u32>(p.lamps_max, u32(p.lamps.size()));
        p.shown_lamps.swap(p.lamps);
        p.shown_lamps_frame = p.frame;
    }
    p.lamps.clear();
    if (p.window_frames < ProbeWindowFrames) {
        return;
    }
    // The window's lines.
    ++p.window;
    const double secs = std::chrono::duration<double>(now - p.window_start).count();
    const bool detail = p.window <= ProbeDetailWindows;
    const auto& settings = BbSettings::Get();
    const bool lamp_rt = settings.effects[BbSettings::EffectPointShadows].load(std::memory_order_relaxed);
    std::vector<u32> changed;
    std::string active;
    u32 active_pairs = 0;
    for (u32 i = 0; i < p.entries.size(); ++i) {
        const ProbeEntry& e = p.entries[i];
        if (e.draws != e.shown_draws || e.vertices != e.shown_vertices) {
            if (e.draws != 0 || e.shown_draws != ~0ull) {
                changed.push_back(i);
            }
        }
        // "active": the ids that drew in this window, as ranges (a pair standing still has the
        // same counts each window and gets no "pair" line; this says it was still there).
        if (detail && e.draws != 0 && (i == 0 || p.entries[i - 1].draws == 0)) {
            u32 j = i;
            while (j + 1 < p.entries.size() && p.entries[j + 1].draws != 0) {
                ++j;
            }
            active += fmt::format("{}{}", active.empty() ? "" : ",",
                                  i == j ? fmt::format("{}", i) : fmt::format("{}-{}", i, j));
            active_pairs += j - i + 1;
        }
    }
    // Pairs new in this window first, then pairs that started or stopped drawing, then the rest;
    // in each group forward and mirrored before G-buffer, other and shadow (the 512 lines a window
    // must not cut the stops walked to last).
    const auto rank = [&](const ProbeEntry& e) {
        if (e.first_window == p.window) {
            return 0;
        }
        const bool was_off = e.shown_draws == 0 || e.shown_draws == ~0ull;
        return was_off != (e.draws == 0) ? 1 : 2;
    };
    std::stable_sort(changed.begin(), changed.end(), [&](u32 a, u32 b) {
        const ProbeEntry& ea = p.entries[a];
        const ProbeEntry& eb = p.entries[b];
        return rank(ea) * 8 + ProbeOrder(ea) < rank(eb) * 8 + ProbeOrder(eb);
    });
    BbReport::Printf("[surface-probe] window window=%llu t=%.1f clock=%s secs=%.1f frames=%u cam=%s "
                     "pairs=%zu new=%llu changed=%zu table=%zu/%u untracked_draws=%llu effects=%s "
                     "rt=%s sun_rt=%s lamp_rt=%s gbuffer_multi_frames=%llu mirrored_frames=%llu "
                     "lamp_frames=%llu lamps_max=%u lamps_mean=%.1f lamp_records=%llu lamps_over=%llu "
                     "water_queries=%llu water_samples=%llu\n",
                     (unsigned long long)p.window, t, clock_text(), secs, p.window_frames, cam_text(),
                     p.entries.size(), (unsigned long long)p.new_pairs, changed.size(), p.entries.size(),
                     ProbeMaxPairs, (unsigned long long)p.untracked, effects_wanted ? "on" : "off",
                     rt_shadow->Wanted() ? "on" : "off", rt_shadow->SunWanted() ? "on" : "off",
                     lamp_rt ? "on" : "off", (unsigned long long)p.multi_frames,
                     (unsigned long long)p.mirrored_frames, (unsigned long long)p.lamp_frames, p.lamps_max,
                     p.lamp_frames ? double(p.lamps_sum) / double(p.lamp_frames) : 0.0,
                     (unsigned long long)p.lamp_records, (unsigned long long)p.lamps_over,
                     (unsigned long long)p.water_queries, (unsigned long long)p.water_samples);
    // bbport (r64b_surface-probe-more): the readback (taken at frame 300 of a window and read on
    // another thread, so it shows with this window or the next), the ray traced scene, the draw
    // order, the lamp record words and the fits of this window.
    if (detail) {
        for (const auto& line : p.readback_lines) {
            BbReport::Printf("%s\n", line.c_str());
        }
        if (!p.rt_scene_line.empty()) {
            BbReport::Printf("%s\n%s\n", p.rt_scene_line.c_str(), p.rt_skinned_line.c_str());
        }
        const auto order_text = [](const ProbeState::Order& o, const char* prefix) {
            const auto span = [](u64 a, u64 b) {
                return a == 0 ? std::string("-") : fmt::format("{}-{}", a, b);
            };
            return o.frame == 0
                       ? fmt::format(" {}frame=-", prefix)
                       : fmt::format(" {0}frame={1} {0}draws={2} {0}gbuffer={3} {0}lamps={4} "
                                     "{0}water={5} {0}water_draws={6} {0}blended={7} "
                                     "{0}blended_pass={8}",
                                     prefix, o.frame, o.draws, span(o.gb_first, o.gb_last),
                                     span(o.lamp_first, o.lamp_last),
                                     span(o.water_first, o.water_last), o.water_draws,
                                     o.blended == 0 ? std::string("-") : fmt::format("{}", o.blended),
                                     o.blended == 0 ? std::string("-")
                                                    : fmt::format("{}/{}", o.blended_pass, o.passes));
        };
        static constexpr const char* zwrite_names[] = {"-", "off", "on", "both"};
        BbReport::Printf("[surface-probe] order window=%llu water_frames=%llu water_draws=%llu "
                         "water_draws_max=%u water_zwrite=%s water_before_lamps=%llu "
                         "water_after_lamps=%llu water_among_lamps=%llu water_no_lamps=%llu%s%s\n",
                         (unsigned long long)p.window, (unsigned long long)p.water_frames,
                         (unsigned long long)p.water_draws, p.water_draws_max,
                         zwrite_names[p.water_zwrite & 3u], (unsigned long long)p.water_before,
                         (unsigned long long)p.water_after, (unsigned long long)p.water_among,
                         (unsigned long long)p.water_alone,
                         order_text(p.order_last, "last_").c_str(),
                         order_text(p.order_water, "water_last_").c_str());
        std::string words;
        for (u32 j = 0; j < 5; ++j) {
            words += p.word_records == 0
                         ? fmt::format(" w{}=-", 7 + j)
                         : fmt::format(" w{}={},{},{:08x},{:08x}", 7 + j,
                                       p.word_min[j] <= p.word_max[j] ? fmt::format("{:.4g}", p.word_min[j]) : std::string("-"),
                                       p.word_min[j] <= p.word_max[j] ? fmt::format("{:.4g}", p.word_max[j]) : std::string("-"),
                                       p.word_umin[j], p.word_umax[j]);
        }
        BbReport::Printf("[surface-probe] lamp-words window=%llu records=%llu zero_records=%llu "
                         "nonfinite=%llu lamps_negative=%llu%s\n",
                         (unsigned long long)p.window, (unsigned long long)p.word_records,
                         (unsigned long long)p.word_zero, (unsigned long long)p.word_nonfinite,
                         (unsigned long long)p.lamps_negative, words.c_str());
        u32 pending = 0;
        for (const auto& f : p.fits) {
            pending += f.active ? 1u : 0u;
        }
        BbReport::Printf("[surface-probe] fits window=%llu asked=%llu no_slot=%llu done=%llu "
                         "dropped=%llu lost=%llu pending=%u fitted_keys=%zu listed_pairs=%zu\n",
                         (unsigned long long)p.window, (unsigned long long)p.fits_asked,
                         (unsigned long long)p.fits_no_slot, (unsigned long long)p.fits_done,
                         (unsigned long long)p.fits_dropped, (unsigned long long)p.fits_lost,
                         pending, p.fitted.size(), p.env_pairs.size());
    }
    p.readback_lines.clear();
    p.rt_scene_line.clear();
    p.rt_skinned_line.clear();
    if (p.untracked != 0) {
        BbReport::Printf("[surface-probe] full window=%llu: the table holds %u pairs; %llu draws of "
                         "other pairs were not looked at\n",
                         (unsigned long long)p.window, ProbeMaxPairs, (unsigned long long)p.untracked);
    }
    if (detail && !p.shown_lamps.empty()) {
        // Every lamp kept (64 at most), the nearest first: dist = |at|, the distance from the camera
        // when the positions are in view space (point_shadow_ray.comp works in view space). reach =
        // 1 / sqrt(word 3), where the game's falloff ends.
        const auto dist = [](const std::array<u32, 7>& w) {
            const float x = std::bit_cast<float>(w[0]), y = std::bit_cast<float>(w[1]),
                        z = std::bit_cast<float>(w[2]);
            return std::sqrt(x * x + y * y + z * z);
        };
        std::vector<std::array<u32, 7>> lamps = p.shown_lamps;
        std::stable_sort(lamps.begin(), lamps.end(),
                         [&](const auto& a, const auto& b) { return dist(a) < dist(b); });
        std::string text;
        for (std::size_t i = 0; i < lamps.size(); ++i) {
            const auto& w = lamps[i];
            const auto f = [&](u32 j) { return std::bit_cast<float>(w[j]); };
            text += fmt::format("{}dist={:.2f} rgb={:.2f},{:.2f},{:.2f} reach={:.2f} at={:.2f},{:.2f},{:.2f}",
                                i ? "; " : "", dist(w), f(4), f(5), f(6), 1.0f / std::sqrt(f(3)), f(0),
                                f(1), f(2));
        }
        BbReport::Printf("[surface-probe] lamps window=%llu frame=%llu sent=%zu lamp_rt=%s: %s\n",
                         (unsigned long long)p.window, (unsigned long long)p.shown_lamps_frame,
                         lamps.size(), lamp_rt ? "on" : "off", text.c_str());
    }
    if (detail) {
        BbReport::Printf("[surface-probe] active window=%llu pairs=%u ids=%s\n", (unsigned long long)p.window,
                         active_pairs, active.empty() ? "-" : active.c_str());
    }
    std::size_t shown = 0;
    for (const u32 i : changed) {
        ProbeEntry& e = p.entries[i];
        if (!detail || shown >= ProbeMaxWindowLines) {
            break;
        }
        ++shown;
        std::string water =
            e.water ? fmt::format(" water_queries={} water_samples={}", p.water_queries, p.water_samples)
                    : std::string{};
        // bbport (r64b_surface-probe-more): the ray traced scene entries its draws reached
        water += e.rt_in != 0 ? fmt::format(" rt_in={} rt_key={:016x} rt_tris={}-{}", e.rt_in, e.rt_key,
                                            e.rt_tris_min, e.rt_tris_max)
                              : std::string(" rt_in=0");
        const std::string range = e.index_min == ~0u ? std::string("-")
                                                     : fmt::format("{}-{}", e.index_min, e.index_max);
        BbReport::Printf("[surface-probe] pair id=%u window=%llu vs=%08llx ps=%08llx pass=%s state=%08x "
                         "draws=%llu verts=%llu idx=%s captured=%llu dropped=%llu why=%s "
                         "mirrored_frames=%llu main_frames=%llu indirect=%llu total=%llu%s\n",
                         i, (unsigned long long)p.window, (unsigned long long)e.key.vs,
                         (unsigned long long)e.key.ps, ProbeGBufferName(e), e.key.state,
                         (unsigned long long)e.draws, (unsigned long long)e.vertices,
                         range.c_str(), (unsigned long long)e.captured,
                         (unsigned long long)(e.draws - e.captured), e.draws > e.captured ? e.drop : "-",
                         (unsigned long long)e.mirrored_frames, (unsigned long long)e.main_frames,
                         (unsigned long long)e.indirect, (unsigned long long)e.total, water.c_str());
        e.shown_draws = e.draws;
        e.shown_vertices = e.vertices;
    }
    if (detail && changed.size() > shown) {
        BbReport::Printf("[surface-probe] more window=%llu: %zu more pairs changed (at most %u lines a "
                         "window)\n",
                         (unsigned long long)p.window, changed.size() - shown, ProbeMaxWindowLines);
    }
    if (p.window == ProbeDetailWindows) {
        BbReport::Printf("[surface-probe] quiet window=%llu: %llu windows printed in full; from now on "
                         "only \"window\", \"new\" and \"full\" lines (unset BB_SURFACE_PROBE after the "
                         "run)\n",
                         (unsigned long long)p.window, (unsigned long long)ProbeDetailWindows);
    }
    for (ProbeEntry& e : p.entries) {
        e.draws = e.vertices = e.captured = e.indirect = 0;
        e.index_min = ~0u;
        e.index_max = 0;
        e.mirrored_frames = e.main_frames = 0;
        e.drop = "-";
        e.rt_in = e.rt_key = 0; // bbport (r64b_surface-probe-more)
        e.rt_tris_min = ~0u;
        e.rt_tris_max = 0;
    }
    p.window_frames = 0;
    p.window_start = now;
    p.untracked = p.new_pairs = p.multi_frames = p.mirrored_frames = 0;
    p.lamp_records = p.lamps_over = p.lamp_frames = p.lamps_sum = 0;
    p.lamps_max = 0;
    p.shown_lamps.clear();
    p.water_samples = p.water_queries = 0;
    // bbport (r64b_surface-probe-more): the window's counts
    p.readback_done = false;
    p.order_water = {};
    p.water_zwrite = 0;
    p.water_frames = p.water_draws = p.water_before = p.water_after = p.water_among = 0;
    p.water_alone = 0;
    p.water_draws_max = 0;
    p.word_min.fill(std::numeric_limits<float>::infinity());
    p.word_max.fill(-std::numeric_limits<float>::infinity());
    p.word_umin.fill(~0u);
    p.word_umax.fill(0u);
    p.word_records = p.word_zero = p.word_nonfinite = p.lamps_negative = 0;
    p.fits_window = p.fits_asked = p.fits_no_slot = p.fits_done = p.fits_lost = 0;
    p.fits_dropped = 0;
    if (p.skins.size() >= ProbeMaxSkins) {
        p.skins.clear(); // the table is full: it starts again with the entries drawn from now on
    }
}

// bbport (r86m_glint-pane-from-triangle, TOOL; BB_GLASS_PICK_TRI=1): the G-buffer's channels at the pick pixels, once when
// BB_GLASS_PICK was armed (GlassPickPoll sets glass_tri_read; EffectsAfterTargets notes the targets of the frame's last G-buffer
// pass at its draws): at the first blended scene draw (or fog composite) of a frame that is not a pick frame, one texel of cb0
// to cb4 and of the depth at each pixel is copied into a small host buffer (as the surface probe's readback does it:
// Runtime::Transit, the reduced scene target's proxy when it holds the content), and GlassTriReadPoll prints the texels once
// the GPU is past the copy. Nothing is written to the targets. The aim: whether glass is tellable from the frame or the wall
// by the G-buffer's channels (the material, the roughness code, the albedo), for a later automatic rule.
struct Rasterizer::GlassTriJob {
    struct Item {
        const char* name = "-";
        vk::Format format = vk::Format::eUndefined;
        u8 texel = 0; ///< a ProbeTexel
        u32 width = 0, height = 0;
        u64 offset = 0;
        bool read = false, proxy = false;
        const char* why = "-";
    };
    std::array<Item, 6> items{};
    std::array<BbWindTrees::Point, BbWindTrees::PickMost> points{};
    std::array<bool, BbWindTrees::PickMost> pane{};
    u32 count = 0, out_w = 1920, out_h = 1080;
    VkBuffer buffer = VK_NULL_HANDLE;
    VmaAllocation allocation{};
    const u8* mapped = nullptr;
    u64 tick = 0, frame = 0;
};

void Rasterizer::GlassTriReadback() {
    if (!glass_tri_read || glass_tri_job || trees_pick_rect_on) {
        return;
    }
    const BbWindTrees::GlassPickLive& live = BbWindTrees::GlassPickState();
    if (!live.armed.load(std::memory_order_relaxed)) {
        glass_tri_read = false;
        return;
    }
    if (!glass_tri_gb[1]) {
        return; // no G-buffer pass seen yet: the next blended draw tries again
    }
    glass_tri_read = false; // one try
    auto job = std::make_shared<GlassTriJob>();
    const BbWindTrees::PickKnob& knob = live.knob;
    job->count = u32(std::min<std::size_t>(knob.count, BbWindTrees::PickMost));
    job->out_w = knob.out_w != 0 ? u32(knob.out_w) : 1920u;
    job->out_h = knob.out_h != 0 ? u32(knob.out_h) : 1080u;
    job->frame = object_motion->Frame();
    for (u32 i = 0; i < job->count; ++i) {
        job->points[i] = knob.points[i];
        job->pane[i] = RtGlassPick::PaneAt(glass_pick_panes, knob.points[i]);
    }
    const std::array<std::pair<const char*, VideoCore::ImageId>, 6> wanted{
        {{"cb0", glass_tri_gb[0]},
         {"cb1", glass_tri_gb[1]},
         {"cb2", glass_tri_gb[2]},
         {"cb3", glass_tri_gb[3]},
         {"cb4", glass_tri_gb[4]},
         {"depth", glass_tri_depth}}};
    const bool reduced = scene_targets->Reduced();
    std::array<VideoCore::ImageId, 6> ids{};
    constexpr u64 per_item = u64(BbWindTrees::PickMost) * 16;
    u64 bytes = 0;
    for (std::size_t i = 0; i < wanted.size(); ++i) {
        GlassTriJob::Item& item = job->items[i];
        item.name = wanted[i].first;
        const VideoCore::ImageId id = wanted[i].second;
        if (!id) {
            item.why = "none";
            continue;
        }
        const auto& image = texture_cache.GetImage(id);
        item.format = image.info.pixel_format;
        const ProbeTexel texel = ProbeTexelOf(item.format);
        item.texel = static_cast<u8>(texel);
        item.proxy = reduced && scene_targets->Eligible(image) && scene_targets->ProxyCurrent(image);
        item.width = image.info.size.width;
        item.height = image.info.size.height;
        if (item.proxy) {
            const auto size = scene_targets->ProxySize(image);
            item.width = size.width;
            item.height = size.height;
        }
        item.offset = u64(i) * per_item;
        if (texel == ProbeTexel::None) {
            item.why = "format";
        } else if (image.info.num_samples > 1) {
            item.why = "multisampled";
        } else if (!item.proxy && !(image.usage_flags & vk::ImageUsageFlagBits::eTransferSrc)) {
            item.why = "usage";
        } else if (item.width == 0 || item.height == 0) {
            item.why = "size";
        } else {
            item.read = true;
            ids[i] = id;
            bytes = item.offset + per_item;
        }
    }
    VkBuffer buffer{};
    VmaAllocation allocation{};
    VmaAllocationInfo info{};
    if (bytes != 0) {
        const VkBufferCreateInfo buffer_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = bytes,
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        const VmaAllocationCreateInfo alloc_ci{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
        };
        if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &buffer, &allocation, &info) != VK_SUCCESS ||
            !info.pMappedData) {
            if (buffer) {
                vmaDestroyBuffer(instance.GetAllocator(), buffer, allocation);
            }
            buffer = VK_NULL_HANDLE;
        }
    }
    if (!buffer) {
        std::printf("GLINT-PROOF glass material (r86m): nothing could be read (no readable G-buffer target or no host "
                    "memory for the copy)\n");
        return;
    }
    struct Copy {
        vk::Image image;
        vk::ImageLayout layout{};
        std::vector<vk::BufferImageCopy> regions;
    };
    auto copies = std::make_shared<std::vector<Copy>>();
    scheduler.EndRendering();
    for (std::size_t i = 0; i < job->items.size(); ++i) {
        GlassTriJob::Item& item = job->items[i];
        if (!item.read) {
            continue;
        }
        auto& image = texture_cache.GetImage(ids[i]);
        Copy copy;
        if (item.proxy) {
            VideoCore::ImageViewInfo view_info;
            view_info.format = item.format;
            const auto target = scene_targets->Read(ids[i], view_info, vk::PipelineStageFlagBits2::eTransfer,
                                                    vk::AccessFlagBits2::eTransferRead);
            if (!(target.usage & vk::ImageUsageFlagBits::eTransferSrc)) {
                item.read = false;
                item.why = "proxy-usage";
                continue;
            }
            copy.image = target.image;
            copy.layout = target.layout;
        } else {
            runtime.Transit(&image, vk::ImageLayout::eTransferSrcOptimal, vk::PipelineStageFlagBits2::eTransfer,
                            vk::AccessFlagBits2::eTransferRead);
            copy.image = image.GetImage();
            copy.layout = vk::ImageLayout::eTransferSrcOptimal;
        }
        const auto aspect = std::string_view(item.name) == "depth" ? vk::ImageAspectFlagBits::eDepth
                                                                   : vk::ImageAspectFlagBits::eColor;
        for (u32 p = 0; p < job->count; ++p) {
            const u64 px = u64(std::max(0, job->points[p].x)) * item.width / job->out_w;
            const u64 py = u64(std::max(0, job->points[p].y)) * item.height / job->out_h;
            copy.regions.push_back(vk::BufferImageCopy{
                .bufferOffset = item.offset + u64(p) * 16,
                .imageSubresource = {aspect, 0, 0, 1},
                .imageOffset = {s32(std::min<u64>(px, item.width - 1)), s32(std::min<u64>(py, item.height - 1)), 0},
                .imageExtent = {1, 1, 1},
            });
        }
        copies->push_back(std::move(copy));
    }
    runtime.FlushBarriers();
    const vk::Buffer target_buffer{buffer};
    scheduler.RecordCrumb({.name = "Glass pick G-buffer readback"}, [copies, target_buffer](vk::CommandBuffer cmdbuf) {
        for (const Copy& copy : *copies) {
            cmdbuf.copyImageToBuffer(copy.image, copy.layout, target_buffer, copy.regions);
        }
        const vk::MemoryBarrier2 to_host{
            .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
            .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eHost,
            .dstAccessMask = vk::AccessFlagBits2::eHostRead,
        };
        cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_host});
    });
    job->buffer = buffer;
    job->allocation = allocation;
    job->mapped = static_cast<const u8*>(info.pMappedData);
    job->tick = scheduler.CurrentTick();
    glass_tri_job = std::move(job);
}

// bbport (r86m_glint-pane-from-triangle, TOOL): the readback's lines, once the GPU is past the copy (a frame end; nothing waits):
// a header and a line a pixel with every target's texel (its channels in the format's order), the pane pixels marked.
void Rasterizer::GlassTriReadPoll() {
    GlassTriJob& job = *glass_tri_job;
    if (!scheduler.IsFree(job.tick)) {
        return;
    }
    vmaInvalidateAllocation(instance.GetAllocator(), job.allocation, 0, VK_WHOLE_SIZE);
    std::string head = fmt::format(
        "GLINT-PROOF glass material (r86m): the G-buffer's texels at {} pick pixels of a {}x{} picture, read at frame {} "
        "(pane pixels are the ones of BB_GLASS_PICK_PANES; compare them with the frame and wall pixels); targets:",
        job.count, job.out_w, job.out_h, job.frame);
    for (const GlassTriJob::Item& item : job.items) {
        head += item.read ? fmt::format(" {}={}x{} {}{}", item.name, item.width, item.height, vk::to_string(item.format),
                                        item.proxy ? " (proxy)" : "")
                          : fmt::format(" {}=not read ({})", item.name, item.why);
    }
    std::printf("%s\n", head.c_str());
    for (u32 p = 0; p < job.count; ++p) {
        std::string line = fmt::format("GLINT-PROOF glass material (r86m): pixel {},{} ({}):", job.points[p].x, job.points[p].y,
                                       job.pane[p] ? "pane pixel" : "other pixel");
        for (const GlassTriJob::Item& item : job.items) {
            if (!item.read) {
                continue;
            }
            const ProbeTexel texel = static_cast<ProbeTexel>(item.texel);
            std::array<float, 4> c{};
            ProbeDecode(texel, job.mapped + item.offset + u64(p) * 16, c);
            std::string values;
            for (u32 ch = 0; ch < ProbeChannels(texel); ++ch) {
                values += fmt::format("{}{:.4f}", ch != 0 ? "," : "", c[ch]);
            }
            line += fmt::format(" {}={}", item.name, values);
        }
        std::printf("%s\n", line.c_str());
    }
    vmaDestroyBuffer(instance.GetAllocator(), job.buffer, job.allocation);
    glass_tri_job.reset();
}

// bbport (r64b_surface-probe-more): BB_SURFACE_PROBE=1. Once a window, at the first blended scene
// draw from the window's frame 300 on (the G-buffer and the lighting are done; the transparents
// start) that comes after as many G-buffer passes as the last frame had (mirrored passes come
// before the main one): 64 evenly spaced rows of the last G-buffer pass's cb0, cb1, cb3, cb4 and
// depth and of the screen shadow target are copied into host memory. The targets are made ready
// for the copy as the engine's own effects read them (Runtime::Transit, or the reduced scene
// target's Read when its proxy holds the current content); nothing is written to them. A frame end
// hands the copy to a thread of its own once the GPU is past it (no wait), and its lines go out
// with the next window line.
void Rasterizer::SurfaceProbeBlendedScene() {
    auto& p = Probe();
    std::unique_lock guard{p.lock};
    // The order line's first blended draw: the first one after the frame's last G-buffer pass so
    // far (a later pass's blended draw takes the place of an earlier pass's).
    if (p.now.blended == 0 || p.gbuffer_passes > p.now.blended_pass) {
        p.now.blended = p.frame_draw + 1; // this draw's number (counted after this call)
        p.now.blended_pass = p.gbuffer_passes;
    }
    if (p.blended_seen || p.gbuffer_passes == 0 || p.gbuffer_passes < p.passes_last) {
        return;
    }
    p.blended_seen = true;
    if (p.frame == 0 || p.readback_done || p.readback || p.window >= ProbeDetailWindows ||
        p.window_frames < ProbeReadbackFrame || !p.gb[1]) {
        return;
    }
    p.readback_done = true; // one try a window
    auto job = std::make_shared<ProbeReadJob>();
    job->window = p.window + 1;
    job->frame = p.frame + 1;
    job->t = std::chrono::duration<double>(std::chrono::steady_clock::now() - p.start).count();
    job->clock = ProbeClock();
    const auto m = camera_motion->CameraMatrices();
    job->cam = m.valid ? fmt::format("{:.2f},{:.2f},{:.2f}", m.inv_view[3], m.inv_view[7],
                                     m.inv_view[11])
                       : std::string("-");
    job->gbuffer_pass = p.gbuffer_passes;
    job->passes_before = p.passes_last;
    job->shadow_blurred = p.shadow_ps == ShadowBlurHash;
    const std::array<std::pair<const char*, VideoCore::ImageId>, 6> wanted{
        {{"cb0", p.gb[0]},
         {"cb1", p.gb[1]},
         {"cb3", p.gb[3]},
         {"cb4", p.gb[4]},
         {"depth", p.gb_depth},
         {"shadow", p.shadow_target}}};
    guard.unlock();
    job->sun_path = rt_shadow->probe_sun_path;
    job->sun_wanted = rt_shadow->SunWanted();
    job->rt_complete = rt_shadow->Complete();
    job->rt_on = rt_shadow->Wanted();
    const auto& settings = BbSettings::Get();
    job->contact = settings.effects[BbSettings::EffectContactShadows].load(std::memory_order_relaxed);
    job->pcss = settings.effects[BbSettings::EffectPcss].load(std::memory_order_relaxed);
    job->reduced = scene_targets->Reduced();
    // Where each target's rows go in the host buffer, and which can be read.
    std::array<VideoCore::ImageId, 6> ids{};
    u64 bytes = 0;
    for (std::size_t i = 0; i < wanted.size(); ++i) {
        ProbeReadItem item{};
        item.name = wanted[i].first;
        const VideoCore::ImageId id = wanted[i].second;
        if (!id) {
            item.why = "none";
            job->items.push_back(item);
            continue;
        }
        const auto& image = texture_cache.GetImage(id);
        item.format = image.info.pixel_format;
        item.texel = ProbeTexelOf(item.format);
        // The reduced proxy only when it holds the current content (as SpatialAo reads); else
        // the full-size image is the current one. Nothing here makes or fills a proxy.
        item.proxy = job->reduced && scene_targets->Eligible(image) &&
                     scene_targets->ProxyCurrent(image);
        item.width = image.info.size.width;
        item.height = image.info.size.height;
        if (item.proxy) {
            const auto size = scene_targets->ProxySize(image);
            item.width = size.width;
            item.height = size.height;
        }
        item.rows = std::min(ProbeReadbackRows, item.height);
        item.row_bytes = (u64(item.width) * ProbeTexelBytes(item.texel) + 3) & ~u64(3);
        item.offset = (bytes + 255) & ~u64(255);
        if (item.texel == ProbeTexel::None) {
            item.why = "format";
        } else if (image.info.num_samples > 1) {
            item.why = "multisampled";
        } else if (!item.proxy && !(image.usage_flags & vk::ImageUsageFlagBits::eTransferSrc)) {
            item.why = "usage";
        } else if (item.width == 0 || item.rows == 0 ||
                   item.offset + item.row_bytes * item.rows > ProbeReadbackMaxBytes) {
            item.why = "size";
        } else {
            item.read = true;
            ids[i] = id;
            bytes = item.offset + item.row_bytes * item.rows;
        }
        job->items.push_back(item);
    }
    VkBuffer buffer{};
    VmaAllocation allocation{};
    VmaAllocationInfo info{};
    if (bytes != 0) {
        const VkBufferCreateInfo buffer_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = bytes,
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        const VmaAllocationCreateInfo alloc_ci{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
        };
        if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &buffer, &allocation,
                            &info) != VK_SUCCESS ||
            !info.pMappedData) {
            if (buffer) {
                vmaDestroyBuffer(instance.GetAllocator(), buffer, allocation);
            }
            buffer = VK_NULL_HANDLE;
            for (auto& item : job->items) {
                if (item.read) {
                    item.read = false;
                    item.why = "no-host-memory";
                }
            }
        }
    }
    if (!buffer) {
        auto lines = ProbeReadLines(*job, nullptr);
        guard.lock();
        for (auto& line : lines) {
            p.readback_lines.push_back(std::move(line));
        }
        return;
    }
    struct Copy {
        vk::Image image;
        vk::ImageLayout layout{};
        std::vector<vk::BufferImageCopy> regions;
    };
    auto copies = std::make_shared<std::vector<Copy>>();
    scheduler.EndRendering();
    for (std::size_t i = 0; i < job->items.size(); ++i) {
        ProbeReadItem& item = job->items[i];
        if (!item.read) {
            continue;
        }
        auto& image = texture_cache.GetImage(ids[i]);
        Copy copy;
        if (item.proxy) {
            VideoCore::ImageViewInfo view_info;
            view_info.format = item.format;
            const auto target = scene_targets->Read(ids[i], view_info,
                                                    vk::PipelineStageFlagBits2::eTransfer,
                                                    vk::AccessFlagBits2::eTransferRead);
            if (!(target.usage & vk::ImageUsageFlagBits::eTransferSrc)) {
                item.read = false;
                item.why = "proxy-usage";
                continue;
            }
            copy.image = target.image;
            copy.layout = target.layout;
        } else {
            runtime.Transit(&image, vk::ImageLayout::eTransferSrcOptimal,
                            vk::PipelineStageFlagBits2::eTransfer,
                            vk::AccessFlagBits2::eTransferRead);
            copy.image = image.GetImage();
            copy.layout = vk::ImageLayout::eTransferSrcOptimal;
        }
        const auto aspect = std::string_view(item.name) == "depth" ? vk::ImageAspectFlagBits::eDepth
                                                                   : vk::ImageAspectFlagBits::eColor;
        for (u32 row = 0; row < item.rows; ++row) {
            const u32 y = u32((u64(2 * row + 1) * item.height) / (2ull * item.rows));
            copy.regions.push_back(vk::BufferImageCopy{
                .bufferOffset = item.offset + u64(row) * item.row_bytes,
                .imageSubresource = {aspect, 0, 0, 1},
                .imageOffset = {0, s32(y), 0},
                .imageExtent = {item.width, 1, 1},
            });
        }
        copies->push_back(std::move(copy));
    }
    runtime.FlushBarriers();
    const vk::Buffer target_buffer{buffer};
    scheduler.RecordCrumb({.name = "Surface probe readback"},
                          [copies, target_buffer](vk::CommandBuffer cmdbuf) {
                              for (const Copy& copy : *copies) {
                                  cmdbuf.copyImageToBuffer(copy.image, copy.layout, target_buffer,
                                                           copy.regions);
                              }
                              const vk::MemoryBarrier2 to_host{
                                  .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
                                  .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
                                  .dstStageMask = vk::PipelineStageFlagBits2::eHost,
                                  .dstAccessMask = vk::AccessFlagBits2::eHostRead,
                              };
                              cmdbuf.pipelineBarrier2(
                                  {.memoryBarrierCount = 1, .pMemoryBarriers = &to_host});
                          });
    job->buffer = buffer;
    job->allocation = allocation;
    job->mapped = static_cast<const u8*>(info.pMappedData);
    job->bytes = bytes;
    job->tick = scheduler.CurrentTick();
    guard.lock();
    p.readback = std::move(job); // the frame ends see to it from here (SurfaceProbeFrameEnd)
}

// bbport (t70b, t167, TOOL): At a blended draw, start one readback of BB_REFLECT_PROBE_RECT per second.
// At frame end, report any finished readback and emit one counter line per enabled hide pair each second.
// The callers require BB_SURFACE_PROBE=1.
void Rasterizer::SurfaceProbeRect(bool frame_end) {
    auto& r = ReflectProbe();
    const bool hide_on = std::any_of(r.hide.begin(), r.hide.end(), [](const auto& pair) { return pair.on; });
    if (!r.rect_on && !hide_on) {
        return;
    }
    const auto now = std::chrono::steady_clock::now();
    const auto seconds = [](std::chrono::steady_clock::duration d) {
        return std::chrono::duration<double>(d).count();
    };
    if (frame_end) {
        std::scoped_lock guard{r.lock};
        if (!r.started) {
            r.started = true;
            r.start = r.last_hide = now;
        }
        ++r.frames;
        if (r.pending && scheduler.IsFree(r.tick)) {
            vmaInvalidateAllocation(instance.GetAllocator(), r.allocation, 0, VK_WHOLE_SIZE);
            for (const auto& line : ReflectProbeLines(r)) {
                BbReport::Printf("%s\n", line.c_str());
            }
            vmaDestroyBuffer(instance.GetAllocator(), r.buffer, r.allocation);
            r.buffer = VK_NULL_HANDLE;
            r.mapped = nullptr;
            r.pending = false;
        }
        if (hide_on && seconds(now - r.last_hide) >= ReflectProbeSeconds) {
            r.last_hide = now;
            for (auto& pair : r.hide) {
                if (!pair.on) {
                    continue;
                }
                const u64 total = pair.skipped.load(std::memory_order_relaxed);
                if (pair.index_count != 0) {
                    BbReport::Printf("[reflect-probe] hide-range %08llx:%08llx count=%u guest_first=%u "
                                     "t=%.1f frames=%llu exact_matches_suppressed=%llu (since the last line %llu) "
                                     "pair_not_exact_retained=%llu indirect_draws_not_hidden=%llu\n",
                                     (unsigned long long)pair.vs, (unsigned long long)pair.ps,
                                     pair.index_count, pair.first_index, seconds(now - r.start),
                                     (unsigned long long)r.frames, (unsigned long long)total,
                                     (unsigned long long)(total - pair.shown),
                                     (unsigned long long)pair.pair_not_exact.load(std::memory_order_relaxed),
                                     (unsigned long long)pair.indirect.load(std::memory_order_relaxed));
                    pair.shown = total;
                    continue;
                }
                BbReport::Printf("[reflect-probe] hide %08llx:%08llx t=%.1f frames=%llu hidden_draws=%llu (since the "
                                 "last line %llu) indirect_draws_not_hidden=%llu\n",
                                 (unsigned long long)pair.vs, (unsigned long long)pair.ps,
                                 seconds(now - r.start), (unsigned long long)r.frames, (unsigned long long)total,
                                 (unsigned long long)(total - pair.shown),
                                 (unsigned long long)pair.indirect.load(std::memory_order_relaxed));
                pair.shown = total;
            }
        }
        return;
    }
    if (!r.rect_on) {
        return;
    }
    std::scoped_lock guard{r.lock};
    if (r.pending || seconds(now - r.last_rect) < ReflectProbeSeconds) {
        return;
    }
    // The targets of the frame's last G-buffer pass (the surface probe follows them), once the pass is
    // in (as SurfaceProbeBlendedScene waits for it).
    std::array<VideoCore::ImageId, 3> ids{};
    {
        auto& p = Probe();
        std::scoped_lock probe_guard{p.lock};
        if (p.gbuffer_passes == 0 || p.gbuffer_passes < p.passes_last || !p.gb[0] || !p.gb[1] || !p.gb_depth) {
            return;
        }
        ids = {p.gb[0], p.gb[1], p.gb_depth};
    }
    r.last_rect = now; // one try a second
    const bool reduced = scene_targets->Reduced();
    const auto& reference = texture_cache.GetImage(ids[0]);
    r.ref_w = reference.info.size.width;
    r.ref_h = reference.info.size.height;
    if (r.ref_w == 0 || r.ref_h == 0) {
        return;
    }
    const bool fractions = r.rect[0] <= 1.0 && r.rect[1] <= 1.0 && r.rect[2] <= 1.0 && r.rect[3] <= 1.0;
    r.fraction = {fractions ? r.rect[0] : r.rect[0] / double(r.ref_w), fractions ? r.rect[1] : r.rect[1] / double(r.ref_h),
                  fractions ? r.rect[2] : r.rect[2] / double(r.ref_w), fractions ? r.rect[3] : r.rect[3] / double(r.ref_h)};
    for (auto& f : r.fraction) {
        f = std::clamp(f, 0.0, 1.0);
    }
    static constexpr const char* names[3] = {"cb0", "cb1", "depth"};
    r.items.assign(3, ReflectProbeItem{});
    u64 bytes = 0;
    for (u32 i = 0; i < 3; ++i) {
        ReflectProbeItem& item = r.items[i];
        item.name = names[i];
        const auto& image = texture_cache.GetImage(ids[i]);
        item.format = image.info.pixel_format;
        item.texel = ProbeTexelOf(item.format);
        item.proxy = reduced && scene_targets->Eligible(image) && scene_targets->ProxyCurrent(image);
        item.width = image.info.size.width;
        item.height = image.info.size.height;
        if (item.proxy) {
            const auto size = scene_targets->ProxySize(image);
            item.width = size.width;
            item.height = size.height;
        }
        if (item.width == 0 || item.height == 0) {
            item.why = "size";
            continue;
        }
        item.x0 = std::min<u32>(u32(r.fraction[0] * double(item.width)), item.width - 1);
        const u32 x1 = std::clamp<u32>(u32(std::ceil(r.fraction[2] * double(item.width))), item.x0 + 1, item.width);
        item.cols = x1 - item.x0;
        item.y0 = std::min<u32>(u32(r.fraction[1] * double(item.height)), item.height - 1);
        item.y1 = std::clamp<u32>(u32(std::ceil(r.fraction[3] * double(item.height))), item.y0 + 1, item.height);
        item.row_bytes = (u64(item.cols) * ProbeTexelBytes(item.texel) + 3) & ~u64(3);
        item.offset = (bytes + 255) & ~u64(255);
        if (item.texel == ProbeTexel::None) {
            item.why = "format";
        } else if (image.info.num_samples > 1) {
            item.why = "multisampled";
        } else if (!item.proxy && !(image.usage_flags & vk::ImageUsageFlagBits::eTransferSrc)) {
            item.why = "usage";
        } else if (item.offset + item.row_bytes * ReflectProbeRows > ProbeReadbackMaxBytes) {
            item.why = "size";
        } else {
            item.read = true;
            bytes = item.offset + item.row_bytes * ReflectProbeRows;
        }
    }
    r.clock = ProbeClock();
    r.t = seconds(now - (r.started ? r.start : now));
    r.frame = r.frames;
    {
        const auto m = camera_motion->CameraMatrices();
        r.cam = m.valid ? fmt::format("{:.2f},{:.2f},{:.2f}", m.inv_view[3], m.inv_view[7], m.inv_view[11])
                        : std::string("-");
    }
    VkBuffer buffer{};
    VmaAllocation allocation{};
    VmaAllocationInfo info{};
    if (bytes != 0) {
        const VkBufferCreateInfo buffer_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = bytes,
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        const VmaAllocationCreateInfo alloc_ci{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
        };
        if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &buffer, &allocation, &info) !=
                VK_SUCCESS ||
            !info.pMappedData) {
            if (buffer) {
                vmaDestroyBuffer(instance.GetAllocator(), buffer, allocation);
            }
            buffer = VK_NULL_HANDLE;
            for (auto& item : r.items) {
                if (item.read) {
                    item.read = false;
                    item.why = "no-host-memory";
                }
            }
        }
    }
    if (!buffer) {
        r.mapped = nullptr;
        for (const auto& line : ReflectProbeLines(r)) {
            BbReport::Printf("%s\n", line.c_str());
        }
        return;
    }
    struct Copy {
        vk::Image image;
        vk::ImageLayout layout{};
        std::vector<vk::BufferImageCopy> regions;
    };
    auto copies = std::make_shared<std::vector<Copy>>();
    scheduler.EndRendering();
    for (u32 i = 0; i < 3; ++i) {
        ReflectProbeItem& item = r.items[i];
        if (!item.read) {
            continue;
        }
        auto& image = texture_cache.GetImage(ids[i]);
        Copy copy;
        if (item.proxy) {
            VideoCore::ImageViewInfo view_info;
            view_info.format = item.format;
            const auto target = scene_targets->Read(ids[i], view_info, vk::PipelineStageFlagBits2::eTransfer,
                                                    vk::AccessFlagBits2::eTransferRead);
            if (!(target.usage & vk::ImageUsageFlagBits::eTransferSrc)) {
                item.read = false;
                item.why = "proxy-usage";
                continue;
            }
            copy.image = target.image;
            copy.layout = target.layout;
        } else {
            runtime.Transit(&image, vk::ImageLayout::eTransferSrcOptimal, vk::PipelineStageFlagBits2::eTransfer,
                            vk::AccessFlagBits2::eTransferRead);
            copy.image = image.GetImage();
            copy.layout = vk::ImageLayout::eTransferSrcOptimal;
        }
        const auto aspect =
            i == 2 ? vk::ImageAspectFlagBits::eDepth : vk::ImageAspectFlagBits::eColor;
        for (u32 k = 0; k < ReflectProbeRows; ++k) {
            const u32 y = item.y0 + u32((u64(2 * k + 1) * (item.y1 - item.y0)) / (2ull * ReflectProbeRows));
            copy.regions.push_back(vk::BufferImageCopy{
                .bufferOffset = item.offset + u64(k) * item.row_bytes,
                .imageSubresource = {aspect, 0, 0, 1},
                .imageOffset = {s32(item.x0), s32(y), 0},
                .imageExtent = {item.cols, 1, 1},
            });
        }
        copies->push_back(std::move(copy));
    }
    runtime.FlushBarriers();
    const vk::Buffer target_buffer{buffer};
    scheduler.RecordCrumb({.name = "Reflect probe readback"},
                          [copies, target_buffer](vk::CommandBuffer cmdbuf) {
                              for (const Copy& copy : *copies) {
                                  cmdbuf.copyImageToBuffer(copy.image, copy.layout, target_buffer, copy.regions);
                              }
                              const vk::MemoryBarrier2 to_host{
                                  .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
                                  .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
                                  .dstStageMask = vk::PipelineStageFlagBits2::eHost,
                                  .dstAccessMask = vk::AccessFlagBits2::eHostRead,
                              };
                              cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_host});
                          });
    r.buffer = buffer;
    r.allocation = allocation;
    r.mapped = static_cast<const u8*>(info.pMappedData);
    r.tick = scheduler.CurrentTick();
    r.pending = true;
}

// bbport (r64b_surface-probe-more): the ray traced scene at the last frame of a window, before
// RtShadow::OnFrameEnd resets its frame (the TLAS count, the entries drawn this frame).
void Rasterizer::SurfaceProbeRtScene() {
    auto& p = Probe();
    std::scoped_lock guard{p.lock};
    if (p.window_frames + 1 < ProbeWindowFrames || p.window >= ProbeDetailWindows) {
        return;
    }
    const auto s = rt_shadow->ProbeSceneNow(ProbeSkinnedMost);
    const double mb = 1.0 / 1048576.0;
    p.rt_scene_line = fmt::format(
        "[surface-probe] rt-scene window={} frame={} capturing={} scene={} entries={} "
        "drawn_entries={} tlas_instances={} blas_mb={:.1f} blas_limit_mb={:.0f} "
        "static_camera_alive={} static_camera_drawn={} static_camera_alive_mb={:.2f} "
        "static_camera_drawn_mb={:.2f} static_camera_alive_tris={} static_camera_drawn_tris={} "
        "sun_only_alive={} sun_only_drawn={} moving_alive={} moving_drawn={} skinned_alive={} "
        "skinned_drawn={} skinned_drawn_tris={}",
        p.window + 1, p.frame + 1, s.capturing ? 1 : 0, s.need_scene ? 1 : 0, s.entries,
        s.frame_entries, s.tlas_instances, double(s.blas_bytes) * mb, double(s.blas_limit) * mb,
        s.static_alive, s.static_drawn, double(s.static_alive_bytes) * mb,
        double(s.static_drawn_bytes) * mb, s.static_alive_triangles, s.static_drawn_triangles,
        s.shadow_alive, s.shadow_drawn, s.moving_alive, s.moving_drawn, s.skinned_alive,
        s.skinned_drawn, s.skinned_drawn_triangles);
    // Each: key:triangles:mask:pair:samples:changes. pair: the id of the last pair whose draw
    // reached it ("-": none seen); samples, changes: this window's hashes of its guest index list
    // and how many differed from the one before.
    std::string list;
    for (const auto& k : s.skinned) {
        const auto found = p.skins.find(k.key);
        const bool known = found != p.skins.end();
        const bool now = known && found->second.window == p.window;
        list += fmt::format("{}{:016x}:{}:{}:{}:{}:{}", list.empty() ? "" : ",", k.key, k.triangles,
                            u32(k.mask),
                            known && found->second.pair != 0
                                ? fmt::format("{}", found->second.pair - 1)
                                : std::string("-"),
                            now ? found->second.samples : 0u, now ? found->second.changes : 0u);
    }
    p.rt_skinned_line = fmt::format("[surface-probe] rt-skinned window={} drawn={} listed={} "
                                    "entries={}",
                                    p.window + 1, s.skinned_drawn, s.skinned.size(),
                                    list.empty() ? std::string("-") : list);
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
    a.march_frames += a.reach > 0.0f ? 1u : 0u; // bbport (r51_volumetric-leak)
    a.spread_frames += a.mask_spread != 0 ? 1u : 0u;
    for (u32 c = 0; c < 4; ++c) {
        a.cascade_frames[c] += (a.drawn_mask >> c) & 1u;
        a.valid_frames[c] += a.reach > 0.0f ? (a.valid_mask >> c) & 1u : 0u;
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
        if (a.march_frames != 0) { // bbport (r51_volumetric-leak)
            BbReport::Printf("Sun atlas: volumetric march (r51) reads cascades %#x now, "
                             "BB_VOLUMETRIC_OCCLUSION %u; c0..c3 read on %u %u %u %u of %u frames "
                             "marched; frames with an atlas draw of no single quadrant (all four "
                             "read) %u\n",
                             a.valid_mask, VolumetricOcclusion::Bits(), a.valid_frames[0],
                             a.valid_frames[1], a.valid_frames[2], a.valid_frames[3],
                             a.march_frames, a.spread_frames);
        }
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
        a.valid_frames = {}; // bbport (r51_volumetric-leak)
        a.march_frames = 0;
        a.spread_frames = 0;
    }
    // r12: with experiment 549755813888 clear the readers are sun_reader's: the water only while
    // it showed samples lately, any other one for good.
    const bool reader_free = BbToggle::Experiment(SunAtlasLiveOffBit)
                                 ? !a.other_reader
                                 : !sun_reader.latched && sun_reader.quiet;
    a.skip_from = a.address && reader_free && a.steady >= SunAtlasSteadyFrames ? needed : 4u;
    // bbport (r51_volumetric-leak): a frame without a resolve (the effects off, no sun shadow)
    // ends the r19 path's counting for the mask; the next resolve starts it again.
    if (!a.resolved) {
        a.mask_wanted = false;
    }
    a.mask_spread = 0;
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
            // bbport (r51_volumetric-leak): and their draws are gone: only the draws from here on
            // hold casters (the volumetric march's mask; the quadrants left blank count as blank).
            k.drawn = 0;
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
