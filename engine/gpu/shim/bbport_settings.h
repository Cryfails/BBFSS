// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once
#include <string>

#include <atomic>
#include <cstdint> // bbport (r39_master-debug): the mask, and the early reader of the debug_* keys
#include <cstdio>
#include <cstdlib>

namespace BbSettings {

enum Upscaler : int { UpscalerOff = 0, UpscalerFsr3 = 1, UpscalerFsr4 = 2, UpscalerFsr411 = 3,
                      UpscalerTaa = 4, UpscalerDlss = 5, UpscalerFsr = 6, UpscalerXess = 7,
                      UpscalerCount };
inline bool IsFsr4(int upscaler) {
    return upscaler == UpscalerFsr4 || upscaler == UpscalerFsr411 || upscaler == UpscalerFsr;
}
inline bool IsFrameUpscaler(int upscaler) {
    return IsFsr4(upscaler) || upscaler == UpscalerDlss || upscaler == UpscalerXess;
}
enum FrameGen : int { FrameGenOff = 0, FrameGenFsr3 = 1, FrameGenDlss = 2, FrameGenCount };
inline constexpr const char* FrameGenNames[] = {"off", "fsr3", "dlss"};
static_assert(sizeof(FrameGenNames) / sizeof(FrameGenNames[0]) == FrameGenCount);
inline constexpr int FrameGenFramesMax = 5;
inline constexpr float LightSharpnessMax = 100.0f; // Matches GgxLobes::SharpnessRemoved.
enum Reflex : int { ReflexOff = 0, ReflexOn = 1, ReflexBoost = 2, ReflexCount };
inline constexpr const char* ReflexNames[] = {"off", "on", "boost"};
static_assert(sizeof(ReflexNames) / sizeof(ReflexNames[0]) == ReflexCount);
enum Preset : int { NativeAA = 0, Quality, Balanced, Performance, UltraPerformance, PresetCustom, PresetCount };
inline constexpr float RenderScaleMin = 1.0f, RenderScaleMax = 3.0f;
inline constexpr float MipBiasMin = -2.0f, MipBiasMax = 1.0f;
enum FpsPosition : int { FpsTopRight = 0, FpsTopLeft, FpsBottomRight, FpsBottomLeft, FpsTopCentre, FpsPositionCount };
enum DebugView : int { DebugNone = 0, DebugReactive = 1, DebugMotion = 2, DebugViewCount };
enum class MenuLanguage {
    English, Russian, Spanish, PortugueseBrazil, French, German, Italian, Polish, Turkish, ChineseSimplified
};
inline constexpr const char* MenuLanguageCodes[] = {"en", "ru", "es", "pt_BR", "fr", "de", "it", "pl", "tr", "zh_CN"};
inline constexpr int MenuLanguageCount = int(sizeof(MenuLanguageCodes) / sizeof(MenuLanguageCodes[0]));
static_assert(MenuLanguageCount == int(MenuLanguage::ChineseSimplified) + 1);

struct Effect {
    const char* key;
    const char* label;
    const char* label_ru;
    bool default_on;
};
inline constexpr Effect Effects[] = {
    {"effect_chromatic_aberration", "Chromatic aberration", "Хроматическая аберрация", false},
    {"effect_dof", "Depth of field (DoF)", "Глубина резкости (DoF)", false},
    {"effect_motion_blur", "Motion blur", "Размытие в движении", false},
    {"effect_ssao", "Ambient occlusion (SSAO)", "Затенение SSAO", true},
    {"effect_game_aa", "Game's own anti-aliasing", "Собственное сглаживание игры", false},
    {"effect_dynamic_shadows", "Shadows from dynamic lights", "Тени от динамических источников", true},
    {"effect_ssr", "Screen-space reflections (not in original game)", "Отражения SSR (не было в игре)", true},
    {"skip_intro", "Skip startup intros", "Пропуск заставок при запуске", true},
    {"debug_camera", "Free camera (Cross + L3)", "Свободная камера (Cross + L3)", false},
    {"debug_menu", "Debug menu (requires font files)", "Debug menu (нужны файлы шрифтов)", false},
    {"effect_gtao", "Ground-truth ambient occlusion (GTAO, experimental)", "Затенение GTAO (эксперимент)", true},
    {"effect_modern_ssr", "Improved reflections", "Улучшенные отражения", true},
    {"effect_pom_cavity", "Deeper parallax surfaces", "Глубокие параллакс-поверхности", true},
    {"effect_contact_shadows", "Contact shadows", "Контактные тени", false},
    {"effect_pcss", "Soft sun shadows (PCSS)", "Мягкие тени солнца (PCSS)", false},
    {"effect_gi", "Indirect lighting (GI)", "Непрямое освещение (GI)", true},
    {"effect_volumetric_light", "Volumetric sunlight", "Объёмный солнечный свет", true},
    {"effect_point_fog", "Fog around lamps", "Туман вокруг ламп", true},
    {"effect_point_shadows", "Point light shadows (experimental)", "Тени от точечных источников (эксперимент)", false},
    {"effect_ray_tracing", "Ray traced lighting (experimental)", "Трассированное освещение (эксперимент)", false},
};
inline constexpr int EffectCount = int(sizeof(Effects) / sizeof(Effects[0]));
inline constexpr int EffectFirstLighting = 10;
inline constexpr int EffectDof = 1;
inline constexpr int EffectSsao = 3;
inline constexpr int EffectSsr = 6;
inline constexpr int EffectSkipIntro = 7;
inline constexpr int EffectGtao = 10;
inline constexpr int EffectModernSsr = 11;
inline constexpr int EffectPomCavity = 12;
inline constexpr int EffectContactShadows = 13;
inline constexpr int EffectPcss = 14;
inline constexpr int EffectGi = 15;
inline constexpr int EffectVolumetricLight = 16;
inline constexpr int EffectPointFog = 17;
inline constexpr int EffectPointShadows = 18;
inline constexpr int EffectRayTracing = 19;
// Ray traced lighting needs its device extensions and position capture from the start when enabled.
inline constexpr bool EffectIsLive(int effect) { return effect >= EffectContactShadows; }
inline constexpr bool EffectChangeNeedsRestart(int effect, bool now, bool at_start) {
    return now != at_start && (!EffectIsLive(effect) || (effect == EffectRayTracing && now));
}
inline constexpr int OutputWidths[] = {1280,1600,1920,2560,3840,2560,3440,3840,3840,5120,5120,7680,0,0};
inline constexpr int OutputHeights[] = {720,900,1080,1440,2160,1080,1440,1600,1080,1440,2160,2160,0,0};
inline constexpr int OutputCount = 14;
inline constexpr int OutputAuto = 12;
inline constexpr int OutputCustom = 13;
bool ValidOutputSize(int w, int h);
inline constexpr int OutputDefault = 2;
static_assert(sizeof(OutputWidths) / sizeof(OutputWidths[0]) == OutputCount &&
              sizeof(OutputHeights) / sizeof(OutputHeights[0]) == OutputCount);
int OutputWidth(int index);
int OutputHeight(int index);
inline constexpr int CheatOff = 0, CheatInfinite = -1, CheatMaxAmount = 99;
inline constexpr int CheatGunRanges[] = {0, 150, 200, 300};
inline constexpr int CheatEchoMultipliers[] = {1, 2, 5, 10};
inline constexpr float HdrPaperWhiteDefault = 200.0f, HdrPaperWhiteMin = 10.0f, HdrPaperWhiteMax = 500.0f;
inline constexpr float HdrPeakDefault = 1000.0f, HdrPeakMin = 10.0f, HdrPeakMax = 4000.0f;
inline constexpr float HdrBoostDefault = 0.25f;
inline constexpr float HdrUiBrightnessMin = 0.5f, HdrUiBrightnessMax = 2.0f, HdrUiColorDefault = 1.0f;
enum HdrOutput : int { HdrOutputOff = 0, HdrOutputHdr10 = 1, HdrOutputScRgb = 2 };
enum HdrMode : int { HdrModeNative = 0, HdrModeExpand = 1, HdrModeCount };
inline constexpr const char* HdrModeNames[] = {"native", "expand"};
static_assert(sizeof(HdrModeNames) / sizeof(HdrModeNames[0]) == HdrModeCount);
enum Tonemapper : int { TonemapperOriginal = 0, TonemapperGt7 = 1, TonemapperAces = 2, TonemapperCount };
inline constexpr const char* TonemapperNames[] = {"original", "gt7", "aces"};
static_assert(sizeof(TonemapperNames) / sizeof(TonemapperNames[0]) == TonemapperCount);
enum SpecularModel : int { SpecularOriginal = 0, SpecularGgxHybrid, SpecularGgxFull, SpecularModelCount };
inline constexpr const char* SpecularModelNames[] = {"original", "ggx-hybrid", "ggx-full"};
static_assert(sizeof(SpecularModelNames) / sizeof(SpecularModelNames[0]) == SpecularModelCount);
inline constexpr float Gt7ExposureMin = 0.25f, Gt7ExposureMax = 4.0f;
enum BloomQuality : int { BloomQualityOriginal = 0, BloomQualityFroyok = 1, BloomQualityCount };
inline constexpr const char* BloomQualityNames[] = {"original", "froyok"};
static_assert(sizeof(BloomQualityNames) / sizeof(BloomQualityNames[0]) == BloomQualityCount);
inline constexpr float FroyokBlendMin = 0.1f, FroyokBlendMax = 0.3f;
inline constexpr float FroyokSpreadMin = 0.5f, FroyokSpreadDefault = 0.85f, FroyokSpreadMax = FroyokSpreadDefault;
inline constexpr float WetGroundMin = 0.0f, WetGroundMax = 1.0f, WetGroundDefault = 0.5f;
inline constexpr float DofIntensityMin = 0.0f, DofIntensityMax = 3.0f;
// bbport (r45_drawn-look): the drawn look's keys (graphics_drawn_look_*) that do not run 0..1.
inline constexpr float DrawnLookStrengthDefault = 0.6f;
inline constexpr float DrawnLookStrokeSizeMin = 0.6f, DrawnLookStrokeSizeMax = 1.4f;
inline constexpr float DrawnLookTextureMax = 1.2f;
inline constexpr float DrawnLookOutlinesDefault = 0.35f, DrawnLookCharactersDefault = 0.5f;
inline constexpr float DrawnLookShadowSoftMin = 0.05f, DrawnLookShadowSoftMax = 0.3f,
                       DrawnLookShadowSoftDefault = 0.12f;
inline constexpr int DrawnLookDebugMax = 4; // DrawnLookParams::ViewMax (drawn_look_params.h)
inline constexpr float LocalLightIntensityMin = 0.0f, LocalLightIntensityMax = 4.0f;
// Source size of local lights under inverse-square falloff, as a fraction of the light radius.
inline constexpr float LocalLightCoreMin = 0.0f, LocalLightCoreMax = 0.35f, LocalLightCoreDefault = 0.05f;

inline constexpr int DlssPresetDefault = 0, DlssPresetK = 11, DlssPresetMax = 26;
inline constexpr int DlssPresetAuto = -1, DlssPresetL = 12, DlssPresetM = 13;
int DlssPresetFromText(const char* text);
const char* DlssPresetText(int preset);

enum OptiSubmit : int { OptiSubmitAuto = -1, OptiSubmitOff = 0, OptiSubmitOn = 1 };

enum ButtonPrompts : int { PromptsAuto = 0, PromptsKeyboard = 1, PromptsController = 2, PromptsCount };
inline constexpr const char* ButtonPromptsNames[] = {"auto", "keyboard", "controller"};
static_assert(sizeof(ButtonPromptsNames) / sizeof(ButtonPromptsNames[0]) == PromptsCount);

enum PadIcons : int { PadIconsAuto = 0, PadIconsPlayStation = 1, PadIconsXbox = 2, PadIconsCount };
inline constexpr const char* PadIconsNames[] = {"auto", "playstation", "xbox"};
static_assert(sizeof(PadIconsNames) / sizeof(PadIconsNames[0]) == PadIconsCount);

// bbport (r15_far-shadow-setting): how often the game draws its two far sun shadow cascades
// (shim/engine/graphics.cpp hooks its cascade loop at start; BB_SUN_CASCADES, when set, wins).
// Game: every frame, nothing hooked. Alternate: the far two take turns. Rare: each every 8th frame.
enum SunFarShadows : int { SunFarGame = 0, SunFarAlternate = 1, SunFarRare = 2, SunFarShadowsCount };
inline constexpr const char* SunFarShadowsNames[] = {"game", "alternate", "rare"};
static_assert(sizeof(SunFarShadowsNames) / sizeof(SunFarShadowsNames[0]) == SunFarShadowsCount);

// bbport (r37_menu-options): the motion-vector vertex store (renderer_vulkan/vk_object_motion.cpp
// makes it at start; BB_OBJECT_MOTION_VERTICES, when set, wins). Large: 8388608 vertices a frame
// half (256 MiB in all); small: 4194304 (128 MiB); auto: large, small where Instance::IsLowVramAmd
// (an AMD discrete card whose largest device-local heap is at most 8 GiB + 512 MiB, or BB_AMD_LOW_VRAM=1).
enum MotionStore : int { MotionStoreAuto = 0, MotionStoreLarge = 1, MotionStoreSmall = 2, MotionStoreCount };
inline constexpr const char* MotionStoreNames[] = {"auto", "large", "small"};
static_assert(sizeof(MotionStoreNames) / sizeof(MotionStoreNames[0]) == MotionStoreCount);

// bbport (r39_master-debug): engine_previous_paths (lantern.ini and the menu's Debug tab; 0|1,
// default 0). On: these experiment bits are forced (a set bit is the path from before the
// performance work), ORed with the bits of BB_TOGGLE_FILE, live (ApplyPreviousPaths). In it:
// the first measured mask (1023959505797356640, the before/after measurements of the work), and
// 13, 20, 54 and 56 (read in the source to be the earlier path and safe to set at any time; not
// part of that first mask).
// bbport (r40_master-bits): 7 and 9 are in it as well, so that the switch goes back to the
// engine before the work as fully as the run-time switches allow. 7 set: the lamps of ray traced
// lamp shadows are not drawn apart for one pass; together with 6 that is the lamp pass as it
// was, a batch with a whole-image snapshot and a shadow pass per tile (vk_point_shadow.h). 9
// set: the Reflex sleep in the flip step as before, not before the game reads input
// (vk_streamline.cpp). The whole mask as it is now, 1114031498345823968 (so with 13, 20, 54 and
// 56 set too), was measured before 7 and 9 went in, through BB_TOGGLE_FILE (uncapped, one heavy
// spot, picture and run stable), bits clear against set: 90.2 against 63.6 FPS with ray tracing
// off, 74.9 against 26.4 with it on, 59.3 against 24.0 game FPS with DLSS frame generation as
// well. Ray traced lamp shadows cost several times more while the switch is on, as before the
// work; the row's hint says so. Not in it, although set is the engine before the work (the
// row's hint names it): 14 (the ghost fix: set brings the fault back). Not in it because set is
// not an earlier path: 0-4 (upstream's own experiments), 8 (a diagnostic: shared ray tracing
// copies never refreshed), 23 (no Reflex sleep at all), 28 (acts only with BB_SUN_CASCADE_EVERY)
// and 51 (acts only with BB_RT_UPKEEP_FREEZE).
inline constexpr int PreviousPathsBits[] = {5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20,
                                            21, 22, 24, 25, 26, 27, 30, 31, 33, 34, 35, 36, 37, 39,
                                            40, 42, 44, 46, 47, 48, 50, 52, 53, 54, 56, 57, 58, 59};
inline constexpr std::uint64_t PreviousPathsMask = [] {
    std::uint64_t mask = 0;
    for (const int bit : PreviousPathsBits) {
        mask |= std::uint64_t{1} << bit;
    }
    return mask;
}();
static_assert(PreviousPathsMask == 1114031498345823968ull); // bbport (r40_master-bits)
/// Forces PreviousPathsMask while engine_previous_paths is on and nothing while it is off; one
/// log line when it is on at the start and at each change. Defined in bbgpu.cpp: it needs the
/// runtime's runtime_experiment_force, which the settings tests do not link.
void ApplyPreviousPaths();

// bbport (r39_master-debug): the measuring and tracing switches of the menu's Debug tab. Each
// is a lantern.ini key (0|1, default 0) that stands for an environment variable the engine
// reads once at the start. With the key 1 and the variable not set (or empty), the variable is
// put into the process environment before anything reads it; a variable that is set decides.
// The value put is DebugSwitchValue: it starts with 1, which is all the readers look at, and
// it tells a later engine process that inherits it (the restart from the menu starts the next
// process with this one's environment) that the variable came from the key and not from the
// user: that process follows its key again, and takes the variable out when the key is 0.
// BB_FRAME_STATS and BB_SPIKE_TRACE are read during static initialization (bbport_toggles.h),
// before Load: so this reader is header-only and those initializers call DebugSwitchesAtStart
// first.
enum DebugSwitchId : int { DebugFrameStats, DebugGpuProfile, DebugGpuProfileSplit, DebugSpikeTrace,
                           DebugSubmitDiag, DebugSceneTrips, DebugRtLampTrace, DebugDrawOrder,
                           DebugSunAtlasIgnoreReader, DebugSwitchCount };
struct DebugSwitch {
    const char* key; ///< in lantern.ini
    const char* env; ///< the variable it stands for
};
inline constexpr DebugSwitch DebugSwitches[] = {
    {"debug_frame_stats", "BB_FRAME_STATS"},
    {"debug_gpu_profile", "BB_GPU_PROFILE"},
    {"debug_gpu_profile_split", "BB_GPU_PROFILE_SPLIT"},
    {"debug_spike_trace", "BB_SPIKE_TRACE"},
    {"debug_submit_diag", "BB_SUBMIT_DIAG"},
    {"debug_scene_trips", "BB_SCENE_TRIPS"},
    {"debug_rt_lamp_trace", "BB_RT_LAMP_TRACE"},
    {"debug_draw_order", "BB_DRAW_ORDER"},
    {"debug_sun_atlas_ignore_reader", "BB_SUN_ATLAS_IGNORE_READER"},
};
static_assert(sizeof(DebugSwitches) / sizeof(DebugSwitches[0]) == DebugSwitchCount);
inline constexpr const char* DebugSwitchValue = "1:lantern.ini";
inline int DebugSwitchOfKey(const std::string& key) {
    for (int d = 0; d < DebugSwitchCount; ++d) {
        if (key == DebugSwitches[d].key) {
            return d;
        }
    }
    return -1;
}
struct DebugSwitchState {
    bool ini[DebugSwitchCount]{};     ///< the key was 1 in the file
    bool env_set[DebugSwitchCount]{}; ///< the variable was set from outside (not empty): it decides
    bool applied[DebugSwitchCount]{}; ///< the variable is in the environment because of the key
};
/// The settings file: BB_CONFIG, else lantern.ini in the working directory.
inline const char* IniPath() {
    const char* env = std::getenv("BB_CONFIG");
    return env && env[0] ? env : "lantern.ini";
}
/// The debug_* keys of a settings file, read as Load reads them (the same lines of at most 255
/// characters, blanks cut at the end only, '#' lines and lines without '=' left out, the key up
/// to the first '=', on only for the value 1, the last line of a key decides).
inline void ReadDebugSwitches(const char* path, bool (&on)[DebugSwitchCount]) {
    for (bool& value : on) {
        value = false;
    }
    if (std::FILE* file = std::fopen(path, "r")) {
        char line[256];
        while (std::fgets(line, sizeof(line), file)) {
            std::string text{line};
            text.erase(text.find_last_not_of(" \t\r\n") + 1);
            const auto eq = text.find('=');
            if (text.empty() || text[0] == '#' || eq == std::string::npos) {
                continue;
            }
            for (int d = 0; d < DebugSwitchCount; ++d) {
                if (text.compare(0, eq, DebugSwitches[d].key) == 0) {
                    on[d] = text.compare(eq + 1, std::string::npos, "1") == 0;
                }
            }
        }
        std::fclose(file);
    }
}
/// Reads the keys of `path`; puts the variable of each key that is 1 into the process
/// environment unless the variable is set from outside, and takes out a variable an earlier
/// engine process put there whose key is no longer 1. Changes the environment: not for a
/// running engine, see DebugSwitchesAtStart.
inline DebugSwitchState ApplyDebugSwitches(const char* path) {
    DebugSwitchState state;
    ReadDebugSwitches(path, state.ini);
    for (int d = 0; d < DebugSwitchCount; ++d) {
        const char* name = DebugSwitches[d].env;
        const char* env = std::getenv(name);
        const bool inherited = env && std::string(env) == DebugSwitchValue; // from the key, earlier
        state.env_set[d] = env && env[0] && !inherited;
        if (state.env_set[d]) {
            continue;
        }
#ifdef _WIN32
        if (state.ini[d]) {
            state.applied[d] = inherited || _putenv_s(name, DebugSwitchValue) == 0;
        } else if (inherited) {
            _putenv_s(name, ""); // an empty value takes the variable out
        }
#else
        if (state.ini[d]) {
            state.applied[d] = inherited || setenv(name, DebugSwitchValue, 1) == 0;
        } else if (inherited) {
            unsetenv(name);
        }
#endif
    }
    return state;
}
/// Once per process, at its first call: during static initialization in the engine (before main
/// and before any other thread of the engine exists), else at the first Load.
inline const DebugSwitchState& DebugSwitchesAtStart() {
    static const DebugSwitchState state = ApplyDebugSwitches(IniPath());
    return state;
}

struct Values {
    std::atomic<MenuLanguage> menu_language{MenuLanguage::English};
    std::atomic<int> upscaler{UpscalerFsr3};
    std::atomic<int> preset{NativeAA};
    std::atomic<int> frame_gen{FrameGenOff};
    std::atomic<bool> frame_gen_cap{false};
    std::atomic<bool> frame_gen_active{false};
    std::atomic<float> frame_gen_shown_fps{0.0f}, frame_gen_game_fps{0.0f};
    std::atomic<int> frame_gen_multiplier{2};
    std::atomic<int> frame_gen_frames{1};
    std::atomic<bool> frame_gen_dynamic{false};
    std::atomic<int> frame_gen_target_fps{0};
    std::atomic<bool> dlss_fg_dynamic_supported{false};
    std::atomic<int> reflex{ReflexOn};
    std::atomic<bool> anti_lag{true}, anti_lag_supported{false};
    std::atomic<bool> streamline_loaded{false}, dlss_fg_supported{false};
    std::atomic<int> dlss_fg_max_frames{0};
    std::atomic<const char*> dlss_fg_problem{nullptr};
    std::atomic<bool> sharpen{true};
    std::atomic<float> sharpness{0.3f};
    std::atomic<bool> jitter{true};
    std::atomic<bool> reactive{false};
    std::atomic<bool> object_motion{true};
    std::atomic<int> object_motion_store{MotionStoreAuto}; // bbport (r37_menu-options), restart
    std::atomic<float> reactive_scale{1.0f};
    std::atomic<float> reactive_threshold{0.2f};
    std::atomic<float> reactive_max{0.9f};
    std::atomic<float> fsr3_velocity_factor{1.0f}, fsr3_reactiveness_scale{1.0f},
        fsr3_shading_change_scale{1.0f}, fsr3_accumulation{0.333f}, fsr3_min_disocclusion{-0.333f};
    std::atomic<int> debug_view{DebugNone};
    std::atomic<bool> show_fps{false};
    std::atomic<bool> voice_enabled{true}, voice_push_to_talk{true}, voice_mic_muted{false};
    std::atomic<int> voice_talk_key{25};
    std::atomic<float> voice_volume{1.0f};
    std::atomic<bool> coop_status{true}, coop_notices{true}, coop_warp_requests{true}, coop_hud_ping{true}, coop_open_room{false};
    std::atomic<bool> show_fps_rate{true};
    std::atomic<bool> show_fps_frame_time{true};
    std::atomic<bool> show_fps_upscaler{true};
    std::atomic<bool> show_fps_cpu{false};
    std::atomic<bool> show_fps_gpu{false};
    std::atomic<bool> show_compile_note{true};
    std::atomic<int> fps_position{0};
    std::atomic<float> fps_scale{1.0f};
    std::atomic<unsigned> fps_text_color{0xFFFFFFu};
    std::atomic<unsigned> fps_bg_color{0x0F0F0Fu};
    std::atomic<float> fps_bg_opacity{0.5f};
    std::atomic<float> fps_text_opacity{1.0f};
    std::atomic<bool> fps_border{true};
    std::atomic<bool> hide_cursor{true};
    std::atomic<float> menu_x{-1.0f}, menu_y{-1.0f};
    std::atomic<bool> fsr4_auto_exposure{true};
    std::atomic<bool> fsr4_invert_jitter{false};
    std::atomic<int> active_render_width{1920}, active_render_height{1080};
    std::atomic<bool> motion_blur_held{false};
    std::atomic<bool> effects[EffectCount]{};
    std::atomic<bool> camera_controls{false};
    std::atomic<bool> widescreen{true},pc_controls{true},mouse_camera{true},mouse_menu{true};
    std::atomic<bool> menu_move{false};
    std::atomic<bool> mouse_invert_x{false},mouse_invert_y{false},mouse_auto_rotation{false};
    std::atomic<bool> pc_menus{true};
    std::atomic<int> mouse_sensitivity{5};
    std::atomic<int> button_prompts{PromptsAuto};
    std::atomic<int> pad_icons{PadIconsAuto};
    std::atomic<bool> change_appearance{false}, rebirth{false};
    std::atomic<bool> graphics_controls{false}, graphics_vignette{true};
    std::atomic<bool> graphics_auto_exposure{false};
    std::atomic<bool> graphics_sun_vsm{false};
    std::atomic<bool> graphics_rt_sun{false};
    std::atomic<bool> graphics_rt_point_shadows{false};
    std::atomic<bool> graphics_rt_bounce{false};
    std::atomic<bool> graphics_gi_probes{true};
    std::atomic<bool> graphics_gi_reflections{false};
    std::atomic<bool> graphics_gi_reflections_full_res{false};
    std::atomic<float> graphics_gi_reflection_strength{1.0f};
    std::atomic<float> graphics_gi_wet_ground{WetGroundDefault};
    std::atomic<bool> graphics_smooth_normals{true}; // Smoothed normals for GTAO and indirect light.
    std::atomic<bool> graphics_native_sss{false};
    std::atomic<int> graphics_specular_model{SpecularGgxFull};
    std::atomic<bool> graphics_local_inverse_square{false};
    std::atomic<float> graphics_local_light_intensity{1.0f};
    std::atomic<float> graphics_local_light_core{LocalLightCoreDefault};
    std::atomic<bool> graphics_uniform_local_light{false};
    std::atomic<bool> graphics_disable_player_light{true};
    // Game-shader specular upgrades applied at shader compile time (restart required).
    std::atomic<bool> graphics_local_ggx{true}, graphics_specular_aa{true}, graphics_env_ggx_tails{true};
    // Multiplies each light's specular sharpness limit; LightSharpnessMax removes the limit.
    std::atomic<float> graphics_light_sharpness{LightSharpnessMax};
    std::atomic<float> graphics_dof_intensity{1};
    std::atomic<float> graphics_ao_strength{1},graphics_shadow_scale{1},graphics_bloom{1},graphics_saturation{1};
    std::atomic<float> graphics_gi_strength{1.5f},graphics_volumetric_intensity{1},graphics_point_fog_intensity{1},graphics_ssr_intensity{1};
    std::atomic<int> graphics_tonemapper{TonemapperOriginal};
    std::atomic<float> graphics_gt7_exposure{1.0f};
    std::atomic<int> graphics_bloom_quality{BloomQualityOriginal};
    std::atomic<float> graphics_froyok_bloom_blend{0.1f};
    std::atomic<float> graphics_froyok_bloom_spread{FroyokSpreadDefault};
    std::atomic<float> graphics_point_fog_glow_size{0.08f}; // Lamp fog inverse-square core / radius, 0.03-0.20.
    std::atomic<int> graphics_shadow_resolution{1},graphics_local_shadow_resolution{0},graphics_motion_blur_quality{1};
    std::atomic<int> graphics_ao_quality{1}; // 0 regular GTAO, 1 high (full-res bitmask GTAO)
    std::atomic<int> graphics_sun_far_shadows{SunFarGame}; // bbport (r15_far-shadow-setting), restart
    // bbport (r37_menu-options): performance modes that were environment variables only (named
    // after each); a set variable still decides. Live: the renderer reads them every frame.
    std::atomic<bool> graphics_lamp_shadow_half{false};          // BB_LAMP_SHADOW_HALF
    std::atomic<bool> graphics_gi_reflections_fewer_rays{false}; // BB_SSGI_HALF
    std::atomic<bool> graphics_rt_sun_half{false};               // BB_RT_SUN_HALF
    std::atomic<bool> graphics_rt_far_refit{false};              // BB_RT_REFIT_EVERY=8
    // bbport (r45_drawn-look): the drawn look, an optional hand-painted look (renderer_vulkan/
    // vk_drawn_look.h). All live. While the switch is off or the strength is 0 nothing of it
    // runs. The renderer reads the switch, strength, stroke_size, texture, characters and debug
    // so far; the others are parsed, clamped and saved for the parts of the look that are not
    // built yet (ink lines, painted shadow edges).
    std::atomic<bool> graphics_drawn_look{false};
    std::atomic<float> graphics_drawn_look_strength{DrawnLookStrengthDefault}; // 0..1; 0: no pass
    std::atomic<float> graphics_drawn_look_stroke_size{1.0f};  // 0.6..1.4, a factor on the strokes' size
    std::atomic<float> graphics_drawn_look_texture{1.0f};      // 0..1.2, the brush's marks in a stroke
    std::atomic<float> graphics_drawn_look_outlines{DrawnLookOutlinesDefault}; // 0..1, ink on characters
    std::atomic<float> graphics_drawn_look_shadow_edges{1.0f}; // 0..1; 0: the game's shadows as they are
    std::atomic<float> graphics_drawn_look_ink_world{0.0f};    // 0..1, ink on the world
    std::atomic<float> graphics_drawn_look_characters{DrawnLookCharactersDefault}; // 0..1, the strength on characters
    std::atomic<float> graphics_drawn_look_shadow_soft{DrawnLookShadowSoftDefault}; // 0.05..0.3
    std::atomic<int> graphics_drawn_look_quality{1};           // 0 low, 1 high
    // 0 the look; 1, 2, 4 the test view: every stroke in a flat colour of its own (sizes as the
    // look mixes them, all fine, all bold); 3 is kept for the ink lines' view.
    std::atomic<int> graphics_drawn_look_debug{0};
    // Why the drawn look cannot run, for the menu; null while it can. Set by the renderer.
    std::atomic<const char*> drawn_look_problem{nullptr};
    std::atomic<bool> engine_previous_paths{false}; // bbport (r39_master-debug): PreviousPathsMask, live
    std::atomic<bool> debug_switches[DebugSwitchCount]{}; // bbport (r39_master-debug): debug_* keys, restart
    std::atomic<int> look_choice{0};
    std::atomic<float> graphics_fog{1},graphics_brightness{1},graphics_contrast{1},graphics_hue{0};
    std::atomic<float> camera_fov_scale{1.0f}, camera_distance_scale{1.0f}, camera_height_scale{1.0f};
    std::atomic<int> model_lod{-2};
    std::atomic<int> output_res{OutputDefault};
    int custom_output_w = 1920, custom_output_h = 1080;
    std::atomic<int> cheat_vials{CheatOff}, cheat_bullets{CheatOff};
    std::atomic<bool> cheat_stamina{false}, cheat_stealth{false}, cheat_keep_echoes{false},
        cheat_no_durability{false}, cheat_consumables{false};
    std::atomic<int> cheat_gun_range{0}, cheat_echo_multiplier{1};
    std::atomic<bool> fullscreen{false};
    std::atomic<bool> hdr{false};
    std::atomic<float> hdr_paper_white{HdrPaperWhiteDefault}, hdr_peak{HdrPeakDefault},
        hdr_boost{HdrBoostDefault};
    std::atomic<bool> hdr_peak_auto{true};
    std::atomic<float> hdr_display_peak{0.0f};
    std::atomic<bool> hdr_compare{false};
    std::atomic<float> hdr_ui_brightness{1.0f}, hdr_ui_color{HdrUiColorDefault};
    std::atomic<int> hdr_mode{HdrModeNative};
    std::atomic<int> hdr_output{HdrOutputOff};
    std::atomic<int> live_resolution{0};
    std::atomic<const char*> fsr4_problem{nullptr};
    std::atomic<bool> fsr4_supported{false}, fsr411_supported{false}, dlss_supported{false},
        fsr_sdk_supported{false}, xess_supported{false};
    std::atomic<int> dlss_preset{DlssPresetK}, dlss_applied_preset{-1};
    std::atomic<bool> dlss_mip_bias{true};
    std::atomic<bool> dlss_auto_exposure{false};
    std::atomic<bool> dlss_jitter_fade{false};
    std::atomic<bool> upscale_before_post{false};
    std::atomic<float> render_scale{1.3f};
    std::atomic<float> mip_bias{0.0f};
    std::atomic<bool> optiscaler_compat{true}, optiscaler_ngx_lock{true}, optiscaler_clean_thread{true};
    std::atomic<int> optiscaler_sync_submit{OptiSubmitAuto};
    struct OptiScalerSwitches {
        bool compat = true, ngx_lock = true, clean_thread = true;
        int sync_submit = OptiSubmitAuto;
    } startup_optiscaler;

    int startup_preset = NativeAA;
    float startup_render_scale = 1.3f;
    int startup_frame_gen = FrameGenOff;
    int startup_upscaler = UpscalerFsr3;
    bool startup_object_motion = true;
    int startup_object_motion_store = MotionStoreAuto; // bbport (r37_menu-options): what ObjectMotion uses
    bool startup_engine_previous_paths = false; // bbport (r39_master-debug): the store, thread placement
    bool startup_debug_switches[DebugSwitchCount]{}; // bbport (r39_master-debug)
    int startup_motion_blur_quality = 1;
    int startup_specular_model = SpecularGgxFull;
    bool startup_local_inverse_square = false;
    float startup_local_light_intensity = 1.0f;
    float startup_local_light_core = LocalLightCoreDefault;
    bool startup_uniform_local_light = false;
    bool startup_disable_player_light = true;
    bool startup_local_ggx = true, startup_specular_aa = true, startup_env_ggx_tails = true;
    float startup_light_sharpness = LightSharpnessMax;
    int startup_ao_quality = 1;
    int startup_shadow_resolution = 1;
    int startup_local_shadow_resolution = 0;
    int startup_sun_far_shadows = SunFarGame; // bbport (r15_far-shadow-setting): what the hook uses
    bool startup_effects[EffectCount]{};
    int startup_model_lod = -2;
    int startup_output_res = OutputDefault;
    int startup_live_resolution = 0;
    int startup_bloom_quality = BloomQualityOriginal;
    bool startup_hdr = false;
};

Values& Get();
inline float HdrPeakNits(const Values& v) {
    const float display = v.hdr_display_peak.load(std::memory_order_relaxed);
    const float peak = v.hdr_peak_auto.load(std::memory_order_relaxed) && display >= HdrPeakMin
                           ? display
                           : v.hdr_peak.load(std::memory_order_relaxed);
    return peak < HdrPeakMin ? HdrPeakMin : peak > HdrPeakMax ? HdrPeakMax : peak;
}
void SetValue(const std::string& key, const std::string& value);
std::string SavedValue(const char* key, const char* fallback);
const char* MenuText(const char* english, const char* russian);
inline const char* MenuText(const char* english) { return MenuText(english, english); }

void Load();
void ConfigureUpscalerSupport(bool fsr4, bool fsr411, bool dlss = false, bool fsr_sdk = false,
                              bool fsr4_to_sdk = false, bool xess = false);
bool FixedRenderSession();
int RenderPreset();
bool ResolutionNeedsRestart();
bool AoNeedsRestart();
// Ray tracing is on exactly when the sun shadow method, the lamp shadows or the bounce light use it.
bool RayTracingNeeded();
void DeriveRayTracing();
void Save();

float PresetScale(int preset);
const char* PresetName(int preset);
int ModelPreset(int preset);
bool DlssPresetValid(int preset);
const char* UpscalerName(int upscaler);

}
