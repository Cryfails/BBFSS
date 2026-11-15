// SPDX-License-Identifier: GPL-2.0-or-later
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <filesystem>
#include <chrono>
#include <sstream>
#include <string>
#include "gpu/shim/bbport_settings.h"
#include "gpu/shim/bbport_toggles.h" // bbport (r39_master-debug): its two readers of static initialization

// bbport (r39_master-debug): the two words bbport_toggles.h asks of the runtime.
extern "C" {
std::uint64_t runtime_disabled_optimizations;
std::uint64_t runtime_experiment_bits;
}
// bbport (r39_master-debug): a reader that runs before every ordinary static initializer of
// the program (those have priority 65535, also the two of bbport_toggles.h, which ask
// BbSettings themselves) and does not ask BbSettings: only the constructor of priority 101 in
// bbport_settings.cpp can have put the variable before it.
static bool r39_profile_before_statics = false;
__attribute__((constructor(102))) static void R39ReadBeforeStatics() {
    const char* env = std::getenv("BB_GPU_PROFILE");
    r39_profile_before_statics = env && env[0] == '1';
}

static std::string Read(const char* path) {
    std::ifstream file(path);
    std::stringstream text;
    text << file.rdbuf();
    return text.str();
}

// bbport (r39_master-debug): the child of the start test at the end of main. It reports what
// this process saw at its own start (the file BB_CONFIG names, the variables it inherited) and
// does nothing else: no Load, no other test.
static int DebugSwitchesChild(const char* result_path) {
    const BbSettings::DebugSwitchState& state = BbSettings::DebugSwitchesAtStart();
    const char* env = std::getenv("BB_FRAME_STATS");
    std::ofstream file(result_path);
    file << "stats=" << BbStats::enabled << " spike=" << BbSpike::on << " profile="
         << r39_profile_before_statics << " env=" << (env ? env : "(unset)") << " applied="
         << state.applied[BbSettings::DebugFrameStats] << " set="
         << state.env_set[BbSettings::DebugFrameStats] << "\n";
    file.close();
    return file.good() ? 0 : 1;
}

int main(int argc, char** argv) {
    if (argc == 3 && std::string(argv[1]) == "--r39-debug-switches-at-start") {
        return DebugSwitchesChild(argv[2]);
    }
    const auto temporary = std::filesystem::temp_directory_path() /
        ("bbport-settings-test-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    const std::string filename = temporary.string();
    const char* path = filename.c_str();
    const char ini[] = "# launcher\nupscaler=fsr3\nkey.cross=X, Space\npad.circle=a\nshow_fps=0\n"
                       "fullscreen_hint=1\n";
    { std::ofstream file(path); file << ini; assert(file.good()); }
#ifdef _WIN32
    _putenv_s("BB_CONFIG", path);
#else
    setenv("BB_CONFIG", path, 1);
#endif

    BbSettings::Load();
    auto& s = BbSettings::Get();
    assert(s.upscaler == BbSettings::UpscalerFsr3 && !s.show_fps && s.menu_x < 0.0f);
    assert(s.graphics_ao_quality == 1 && s.startup_ao_quality == 1);
    s.graphics_ao_quality = 0;
    assert(s.startup_ao_quality == 1);
    s.show_fps = true;
    s.upscaler = BbSettings::UpscalerFsr411;
    s.menu_x = 0.625f;
    s.menu_y = 0.125f;
    s.fullscreen = true;
    BbSettings::Save();

    const std::string saved = Read(path);
    assert(saved.find("# launcher\nupscaler=fsr411\nkey.cross=X, Space\npad.circle=a\nshow_fps=1\n"
                      "fullscreen_hint=1\n") == 0);
    assert(saved.find("menu_pos=0.6250,0.1250\n") != std::string::npos);
    assert(saved.find("upscaler=fsr3") == std::string::npos);
    assert(saved.find("fullscreen=1\n") != std::string::npos);
    assert(saved.find("graphics_ao_quality=0\n") != std::string::npos);

    s.menu_x = -1.0f;
    s.menu_y = -1.0f;
    BbSettings::Load();
    assert(s.menu_x == 0.625f && s.menu_y == 0.125f && s.upscaler == BbSettings::UpscalerFsr411);
    assert(s.graphics_ao_quality == 0 && s.startup_ao_quality == 0);
    s.graphics_ao_quality = 1;
    assert(s.startup_ao_quality == 0);
    s.graphics_ao_quality = 0;
    s.upscaler = BbSettings::UpscalerDlss;
    BbSettings::Save();
    assert(Read(path).find("upscaler=dlss\n") != std::string::npos);
    assert(Read(path).find("key.cross=X, Space\n") != std::string::npos);
    BbSettings::ConfigureUpscalerSupport(false, false, false);
    assert(s.upscaler == BbSettings::UpscalerFsr3 && !s.dlss_supported);
    s.upscaler = BbSettings::UpscalerDlss;
    BbSettings::ConfigureUpscalerSupport(false, false, true);
    assert(s.upscaler == BbSettings::UpscalerDlss && s.dlss_supported);
    s.upscaler = BbSettings::UpscalerXess;
    BbSettings::Save();
    assert(Read(path).find("upscaler=xess\n") != std::string::npos);
    s.upscaler = BbSettings::UpscalerOff;
    BbSettings::Load();
    assert(s.upscaler == BbSettings::UpscalerXess);
    BbSettings::ConfigureUpscalerSupport(false, false, false);
    assert(s.upscaler == BbSettings::UpscalerFsr3 && !s.xess_supported);
    s.upscaler = BbSettings::UpscalerXess;
    BbSettings::ConfigureUpscalerSupport(false, false, false, false, false, true);
    assert(s.upscaler == BbSettings::UpscalerXess && s.xess_supported);
    s.upscaler = BbSettings::UpscalerFsr411;
    BbSettings::ConfigureUpscalerSupport(true, false, false);
    assert(s.upscaler == BbSettings::UpscalerFsr4);
    s.upscaler = BbSettings::UpscalerFsr411;
    BbSettings::ConfigureUpscalerSupport(false, false, false);
    assert(s.upscaler == BbSettings::UpscalerFsr3);
    s.camera_controls = true;
    s.camera_fov_scale = 1.25f;
    s.camera_distance_scale = 0.80f;
    s.camera_height_scale = 1.10f;
    BbSettings::Save();
    s.camera_controls = false;
    s.camera_fov_scale = s.camera_distance_scale = s.camera_height_scale = 1.0f;
    BbSettings::Load();
    assert(s.camera_controls && s.camera_fov_scale == 1.25f);
    assert(s.camera_distance_scale == 0.80f && s.camera_height_scale == 1.10f);
    s.change_appearance=true;s.rebirth=true;s.graphics_controls=true;
    s.graphics_bloom=0.7f;s.graphics_shadow_scale=1.4f;
    assert(s.graphics_point_fog_glow_size == 0.08f);
    s.graphics_point_fog_glow_size = 0.15f;
    BbSettings::Save();
    assert(Read(path).find("graphics_point_fog_glow_size=0.150\n") != std::string::npos);
    s.rebirth=false;s.graphics_bloom=1.0f;s.graphics_point_fog_glow_size=0.08f;
    BbSettings::Load();
    assert(s.change_appearance && s.rebirth && s.graphics_controls && s.graphics_bloom==0.7f && s.graphics_shadow_scale==1.4f);
    assert(s.graphics_point_fog_glow_size == 0.15f);
    assert(!s.graphics_auto_exposure && !s.graphics_native_sss && !s.graphics_sun_vsm &&
           !s.graphics_rt_point_shadows && !s.graphics_rt_sun && !s.graphics_rt_bounce && s.graphics_gi_probes &&
           !s.graphics_gi_reflections && !s.graphics_gi_reflections_full_res);
    assert(s.model_lod == -2 && s.startup_model_lod == -2);
    assert(s.graphics_shadow_resolution == 1 && s.startup_shadow_resolution == 1);
    assert(s.graphics_motion_blur_quality == 1 && s.startup_motion_blur_quality == 1);
    assert(s.graphics_gi_strength == 1.5f);
    assert(s.graphics_specular_model == BbSettings::SpecularGgxFull &&
           s.startup_specular_model == BbSettings::SpecularGgxFull);
    assert(!s.graphics_local_inverse_square && !s.startup_local_inverse_square);
    assert(s.graphics_local_light_intensity == 1.0f && s.startup_local_light_intensity == 1.0f);
    assert(s.graphics_local_light_core == 0.05f && s.startup_local_light_core == 0.05f);
    assert(!s.graphics_uniform_local_light && !s.startup_uniform_local_light);
    assert(s.graphics_disable_player_light && s.startup_disable_player_light);
    assert(s.graphics_local_ggx && s.graphics_specular_aa && s.graphics_env_ggx_tails);
    assert(s.startup_local_ggx && s.startup_specular_aa && s.startup_env_ggx_tails);
    assert(s.graphics_light_sharpness == BbSettings::LightSharpnessMax &&
           s.startup_light_sharpness == BbSettings::LightSharpnessMax);
    assert(s.graphics_dof_intensity == 1.0f && s.graphics_gi_reflection_strength == 1.0f);
    assert(s.graphics_gi_wet_ground == 0.5f && s.graphics_smooth_normals);
    s.graphics_smooth_normals = true;
    s.graphics_auto_exposure = true;
    s.graphics_sun_vsm = true;
    s.graphics_rt_point_shadows = true;
    s.graphics_rt_sun = false;
    s.graphics_rt_bounce = false;
    s.effects[BbSettings::EffectRayTracing] = true;
    s.graphics_gi_probes = true;
    s.graphics_gi_reflections = true;
    s.graphics_native_sss = true;
    s.graphics_specular_model = BbSettings::SpecularGgxHybrid;
    assert(s.startup_specular_model == BbSettings::SpecularGgxFull);
    s.graphics_local_inverse_square = true;
    s.graphics_local_light_intensity = 2.5f;
    s.graphics_uniform_local_light = true;
    s.graphics_disable_player_light = false;
    s.graphics_local_ggx = s.graphics_specular_aa = s.graphics_env_ggx_tails = false;
    s.graphics_light_sharpness = 250.0f;
    s.graphics_dof_intensity = 1.75f;
    s.graphics_gi_reflection_strength = 0.25f;
    s.graphics_gi_wet_ground = 0.75f;
    s.graphics_gi_reflections_full_res = true;
    assert(s.startup_specular_model == BbSettings::SpecularGgxFull && !s.startup_local_inverse_square &&
           s.startup_disable_player_light);
    assert(s.startup_local_light_intensity == 1.0f && !s.startup_uniform_local_light);
    BbSettings::Save();
    {
        const std::string fork_keys = Read(path);
        assert(fork_keys.find("graphics_auto_exposure=1\n") != std::string::npos);
        assert(fork_keys.find("graphics_sun_vsm=1\n") != std::string::npos);
        assert(fork_keys.find("graphics_rt_point_shadows=1\n") != std::string::npos);
        assert(fork_keys.find("graphics_rt_sun=0\n") != std::string::npos);
        assert(fork_keys.find("graphics_rt_bounce=0\n") != std::string::npos);
        assert(fork_keys.find("graphics_gi_probes=1\n") != std::string::npos);
        assert(fork_keys.find("graphics_gi_reflections=1\n") != std::string::npos);
        assert(fork_keys.find("graphics_gi_reflection_strength=0.25\n") != std::string::npos);
        assert(fork_keys.find("graphics_gi_wet_ground=0.75\n") != std::string::npos);
        assert(fork_keys.find("graphics_gi_reflections_full_res=1\n") != std::string::npos);
        assert(fork_keys.find("graphics_smooth_normals=1\n") != std::string::npos);
        assert(fork_keys.find("graphics_native_sss=1\n") != std::string::npos);
        assert(fork_keys.find("graphics_specular_model=ggx-hybrid\n") != std::string::npos);
        assert(fork_keys.find("graphics_local_inverse_square=1\n") != std::string::npos);
        assert(fork_keys.find("graphics_local_light_intensity=2.50\n") != std::string::npos);
        assert(fork_keys.find("graphics_uniform_local_light=1\n") != std::string::npos);
        assert(fork_keys.find("graphics_disable_player_light=0\n") != std::string::npos);
        assert(fork_keys.find("graphics_local_ggx=0\n") != std::string::npos);
        assert(fork_keys.find("graphics_specular_aa=0\n") != std::string::npos);
        assert(fork_keys.find("graphics_env_ggx_tails=0\n") != std::string::npos);
        assert(fork_keys.find("graphics_light_sharpness=250.0\n") != std::string::npos);
        assert(fork_keys.find("graphics_dof_intensity=1.75\n") != std::string::npos);
    }
    s.graphics_auto_exposure = s.graphics_native_sss = false;
    s.graphics_specular_model = BbSettings::SpecularGgxFull;
    s.graphics_local_inverse_square = true;
    s.graphics_local_light_intensity = 1.0f;
    s.graphics_uniform_local_light = false;
    s.graphics_disable_player_light = true;
    s.graphics_local_ggx = s.graphics_specular_aa = s.graphics_env_ggx_tails = true;
    s.graphics_sun_vsm = false;
    s.graphics_rt_point_shadows = false;
    s.graphics_rt_sun = true;
    s.graphics_rt_bounce = false;
    s.graphics_gi_probes = false;
    s.graphics_gi_reflections = false;
    s.graphics_gi_reflection_strength = 1.0f;
    s.graphics_gi_wet_ground = 0.5f;
    s.graphics_gi_reflections_full_res = false;
    s.graphics_dof_intensity = 1.0f;
    s.graphics_smooth_normals = false;
    BbSettings::Load();
    assert(s.graphics_gi_wet_ground == 0.75f && s.graphics_smooth_normals);
    s.graphics_smooth_normals = false;
    assert(s.graphics_sun_vsm && s.graphics_rt_point_shadows && !s.graphics_rt_sun && !s.graphics_rt_bounce &&
           s.graphics_gi_probes && s.graphics_gi_reflections &&
           s.graphics_gi_reflection_strength == 0.25f && s.graphics_gi_reflections_full_res);
    assert(s.graphics_auto_exposure && s.graphics_native_sss && s.graphics_dof_intensity == 1.75f);
    assert(s.graphics_specular_model == BbSettings::SpecularGgxHybrid &&
           s.startup_specular_model == BbSettings::SpecularGgxHybrid);
    s.graphics_specular_model = BbSettings::SpecularGgxFull;
    assert(s.startup_specular_model == BbSettings::SpecularGgxHybrid);
    s.graphics_specular_model = BbSettings::SpecularOriginal;
    assert(s.startup_specular_model == BbSettings::SpecularGgxHybrid);
    s.graphics_specular_model = BbSettings::SpecularGgxHybrid;
    assert(s.graphics_local_inverse_square && s.startup_local_inverse_square);
    s.graphics_local_inverse_square = false;
    assert(s.startup_local_inverse_square);
    s.graphics_local_inverse_square = true;
    assert(s.graphics_local_light_intensity == 2.5f && s.startup_local_light_intensity == 2.5f);
    s.graphics_local_light_intensity = 1.0f;
    assert(s.startup_local_light_intensity == 2.5f);
    assert(s.graphics_uniform_local_light && s.startup_uniform_local_light);
    s.graphics_uniform_local_light = false;
    assert(s.startup_uniform_local_light);
    assert(!s.graphics_disable_player_light && !s.startup_disable_player_light);
    s.graphics_disable_player_light = true;
    assert(!s.startup_disable_player_light);
    s.graphics_disable_player_light = false;
    assert(!s.graphics_local_ggx && !s.graphics_specular_aa && !s.graphics_env_ggx_tails);
    assert(!s.startup_local_ggx && !s.startup_specular_aa && !s.startup_env_ggx_tails);
    assert(s.graphics_light_sharpness == 100.0f && s.startup_light_sharpness == 100.0f);
    s.graphics_light_sharpness = 1.0f;
    s.graphics_local_ggx = s.graphics_specular_aa = s.graphics_env_ggx_tails = true;
    s.graphics_auto_exposure = s.graphics_native_sss = s.graphics_sun_vsm = false;
    s.graphics_rt_point_shadows = false;
    s.graphics_rt_sun = false;
    s.graphics_rt_bounce = false;
    s.graphics_gi_probes = false;
    s.graphics_gi_reflections = false;
    s.graphics_gi_reflection_strength = 1.0f;
    s.graphics_gi_wet_ground = 0.5f;
    s.graphics_gi_reflections_full_res = false;
    s.graphics_dof_intensity = 1.0f;
    BbSettings::Save();
    for (const auto& [input, expected] :
         {std::pair{"0", 0}, {"1", 1}, {"-1", 0}, {"2", 0}, {"nan", 0}, {"1bad", 0}}) {
        { std::ofstream file(path); file << "graphics_ao_quality=" << input << "\n"; }
        BbSettings::Load();
        assert(s.graphics_ao_quality == expected && s.startup_ao_quality == expected);
        BbSettings::Save();
        assert(Read(path).find("graphics_ao_quality=" + std::to_string(expected) + "\n") !=
               std::string::npos);
    }
    for (const auto& [input, expected] : {
             std::pair{"graphics_directional_ggx=0\n", BbSettings::SpecularOriginal},
             {"graphics_directional_ggx=0\ngraphics_directional_strict_ggx=1\n", BbSettings::SpecularOriginal},
             {"graphics_directional_ggx=1\n", BbSettings::SpecularGgxFull},
             {"graphics_directional_ggx=1\ngraphics_directional_strict_ggx=0\n", BbSettings::SpecularGgxHybrid},
             {"graphics_directional_ggx=1\ngraphics_directional_strict_ggx=1\n", BbSettings::SpecularGgxFull},
             {"graphics_directional_strict_ggx=0\n", BbSettings::SpecularGgxHybrid},
             {"graphics_directional_ggx=1\ngraphics_specular_model=original\n", BbSettings::SpecularOriginal},
             {"graphics_directional_ggx=0\ngraphics_specular_model=ggx-hybrid\n", BbSettings::SpecularGgxHybrid},
             {"graphics_directional_ggx=0\ngraphics_specular_model=ggx-full\n", BbSettings::SpecularGgxFull},
             {"graphics_specular_model=invalid\n", BbSettings::SpecularGgxFull},
         }) {
        { std::ofstream file(path); file << input; }
        BbSettings::Load();
        assert(s.graphics_specular_model == expected && s.startup_specular_model == expected);
        BbSettings::Save();
        const std::string saved_model = Read(path);
        assert(saved_model.find(std::string("graphics_specular_model=") +
                                BbSettings::SpecularModelNames[expected] + "\n") != std::string::npos);
    }
    for (int e = BbSettings::EffectFirstLighting; e < BbSettings::EffectCount; ++e) {
        assert(BbSettings::Effects[e].default_on ==
               (e == BbSettings::EffectGtao || e == BbSettings::EffectModernSsr ||
                e == BbSettings::EffectPomCavity || e == BbSettings::EffectGi ||
                e == BbSettings::EffectVolumetricLight || e == BbSettings::EffectPointFog));
    }
    assert(BbSettings::Effects[BbSettings::EffectSsr].default_on &&
           !BbSettings::Effects[BbSettings::EffectPcss].default_on);
    assert(BbSettings::Effects[BbSettings::EffectSkipIntro].default_on);
    { std::ofstream file(path); file << "effect_gi=1\ngraphics_gi_strength=99\ngraphics_ssr_intensity=-1\n    graphics_volumetric_intensity=nan\ngraphics_point_fog_glow_size=9\ngraphics_gi_reflection_strength=9\ngraphics_gi_wet_ground=-3\ngraphics_shadow_resolution=9\ngraphics_motion_blur_quality=1\n"; }
    BbSettings::Load();
    assert(s.effects[BbSettings::EffectGi] && s.graphics_gi_strength == 12.0f && s.graphics_ssr_intensity == 0.0f);
    assert(s.graphics_volumetric_intensity == 1.0f && s.graphics_shadow_resolution == 2);
        assert(s.graphics_point_fog_glow_size == 0.20f && s.graphics_gi_reflection_strength == 1.0f);
    assert(s.graphics_gi_wet_ground == 0.0f);
    assert(s.startup_motion_blur_quality == 1 && s.startup_effects[BbSettings::EffectGi]);
    BbSettings::Save();
    BbSettings::Load();
    assert(s.effects[BbSettings::EffectGi] && s.graphics_gi_strength == 12.0f && s.graphics_shadow_resolution == 2);
    { std::ofstream file(path); file << "camera_fov_scale=nan\ncamera_distance_scale=-10\ncamera_height_scale=inf\n"; }
    BbSettings::Load();
    assert(s.camera_fov_scale == 1.0f && s.camera_distance_scale == 0.5f && s.camera_height_scale == 1.0f);
    // An ini without graphics_rt_sun keeps the ray traced sun it was showing.
    s.graphics_sun_vsm = false;
    { std::ofstream file(path); file << "effect_ray_tracing=1\ngraphics_sun_vsm=0\ngraphics_rt_bounce=0\ngraphics_rt_point_shadows=0\n"; }
    BbSettings::Load();
    assert(s.graphics_rt_sun && s.effects[BbSettings::EffectRayTracing]);
    // Virtual shadow maps need ray tracing, so they switch it on even with nothing else using it.
    { std::ofstream file(path); file << "effect_ray_tracing=1\ngraphics_sun_vsm=1\ngraphics_rt_bounce=0\ngraphics_rt_point_shadows=0\n"; }
    BbSettings::Load();
    assert(!s.graphics_rt_sun && s.graphics_sun_vsm && s.effects[BbSettings::EffectRayTracing]);
    // An ini with the master switch off and High shadows keeps High; ray tracing now starts this launch.
    { std::ofstream file(path); file << "effect_ray_tracing=0\ngraphics_sun_vsm=1\ngraphics_rt_bounce=1\n"; }
    BbSettings::Load();
    assert(s.graphics_sun_vsm && !s.graphics_rt_bounce && s.effects[BbSettings::EffectRayTracing] &&
           s.startup_effects[BbSettings::EffectRayTracing]);
    // Master off, no VSM, bounce on: the inert bounce flag is cleared and ray tracing stays off.
    { std::ofstream file(path); file << "effect_ray_tracing=0\ngraphics_sun_vsm=0\ngraphics_rt_bounce=1\n"; }
    BbSettings::Load();
    assert(!s.graphics_sun_vsm && !s.graphics_rt_bounce && !s.effects[BbSettings::EffectRayTracing]);
    s.graphics_sun_vsm = false;
    { std::ofstream file(path); file << "graphics_sun_vsm=0\ngraphics_rt_bounce=0\ngraphics_rt_point_shadows=0\n"; }
    BbSettings::Load();
    assert(!s.graphics_rt_sun && !s.effects[BbSettings::EffectRayTracing]);
    { std::ofstream file(path); file << "effect_ray_tracing=1\ngraphics_rt_sun=0\n"; }
    BbSettings::Load();
    assert(!s.graphics_rt_sun && !s.effects[BbSettings::EffectRayTracing]);
    { std::ofstream file(path); file << "effect_ray_tracing=1\ngraphics_rt_sun=1\n"; }
    BbSettings::Load();
    assert(s.graphics_rt_sun && s.effects[BbSettings::EffectRayTracing]);
    // With the master switch off in the file, the ray traced flags were inert and stay off.
    { std::ofstream file(path); file << "effect_ray_tracing=0\ngraphics_rt_sun=1\ngraphics_rt_bounce=1\ngraphics_rt_point_shadows=1\n"; }
    BbSettings::Load();
    assert(!s.graphics_rt_sun && !s.graphics_rt_bounce && !s.graphics_rt_point_shadows &&
           !s.effects[BbSettings::EffectRayTracing] && !s.startup_effects[BbSettings::EffectRayTracing]);
    { std::ofstream file(path); file << "graphics_rt_bounce=1\n"; }
    BbSettings::Load();
    assert(!s.graphics_rt_bounce && !s.effects[BbSettings::EffectRayTracing]);
    // Lamp shadows or the bounce light switch ray tracing on.
    { std::ofstream file(path); file << "effect_ray_tracing=1\ngraphics_rt_sun=0\ngraphics_rt_point_shadows=1\n"; }
    BbSettings::Load();
    assert(s.graphics_rt_point_shadows && s.effects[BbSettings::EffectRayTracing] &&
           s.startup_effects[BbSettings::EffectRayTracing]);
    { std::ofstream file(path); file << "effect_ray_tracing=1\ngraphics_rt_sun=0\ngraphics_rt_point_shadows=0\ngraphics_rt_bounce=1\neffect_gi=0\n"; }
    BbSettings::Load();
    assert(s.graphics_rt_bounce && s.effects[BbSettings::EffectRayTracing]);
    // Probe GI overrides the bounce light, so it needs no ray tracing; the flag itself is kept.
    { std::ofstream file(path); file << "effect_ray_tracing=1\ngraphics_rt_sun=0\ngraphics_rt_bounce=1\neffect_gi=1\ngraphics_gi_probes=1\n"; }
    BbSettings::Load();
    assert(s.graphics_rt_bounce && !s.effects[BbSettings::EffectRayTracing]);
    // The derived switch follows the live flags.
    s.graphics_rt_point_shadows = true;
    BbSettings::DeriveRayTracing();
    assert(s.effects[BbSettings::EffectRayTracing] && BbSettings::RayTracingNeeded());
    s.graphics_rt_point_shadows = false;
    s.graphics_rt_bounce = false;
    BbSettings::DeriveRayTracing();
    assert(!s.effects[BbSettings::EffectRayTracing]);
    s.graphics_gi_probes = false;
    s.effects[BbSettings::EffectGi] = false;
    s.graphics_rt_sun = false;
    s.effects[BbSettings::EffectRayTracing] = false;
    { std::ofstream file(path); file << "menu_language=pt_BR\n"; }
    BbSettings::Load();
    assert(s.menu_language == BbSettings::MenuLanguage::PortugueseBrazil);
    assert(std::string(BbSettings::MenuText("Close", "Закрыть")) == "Fechar");
    assert(std::string(BbSettings::MenuText("Not in the tables", "x")) == "Not in the tables");
    BbSettings::Save();
    assert(Read(path).find("menu_language=pt_BR\n") != std::string::npos);
    s.menu_language = BbSettings::MenuLanguage::Turkish;
    assert(std::string(BbSettings::MenuText("Close", "Закрыть")) == "Kapat");
    s.menu_language = BbSettings::MenuLanguage::Russian;
    assert(std::string(BbSettings::MenuText("Close", "Закрыть")) == "Закрыть");
    { std::ofstream file(path); file << "cheat_vials=infinite\ncheat_bullets=50\n"; }
    BbSettings::Load();
    assert(s.cheat_vials == BbSettings::CheatInfinite && s.cheat_bullets == 50);
    BbSettings::Save();
    assert(Read(path).find("cheat_vials=infinite\n") != std::string::npos);
    assert(Read(path).find("cheat_bullets=50\n") != std::string::npos);
    { std::ofstream file(path); file << "cheat_vials=100\ncheat_bullets=lots\n"; }
    BbSettings::Load();
    assert(s.cheat_vials == BbSettings::CheatOff && s.cheat_bullets == BbSettings::CheatOff);
    BbSettings::Save();
    assert(Read(path).find("cheat_vials=off\n") != std::string::npos);
    assert(Read(path).find("cheat_gun_range=off\n") != std::string::npos);
    assert(Read(path).find("cheat_echo_multiplier=1\n") != std::string::npos);
    assert(Read(path).find("cheat_stamina=0\n") != std::string::npos);
    {
        std::ofstream file(path);
        file << "cheat_stamina=1\ncheat_stealth=1\ncheat_gun_range=200\ncheat_keep_echoes=1\n"
                "cheat_echo_multiplier=5\ncheat_no_durability=1\ncheat_consumables=1\n";
    }
    BbSettings::Load();
    assert(s.cheat_stamina && s.cheat_stealth && s.cheat_keep_echoes && s.cheat_no_durability && s.cheat_consumables);
    assert(s.cheat_gun_range == 200 && s.cheat_echo_multiplier == 5);
    BbSettings::Save();
    for (const char* line : {"cheat_stamina=1\n", "cheat_stealth=1\n", "cheat_gun_range=200\n", "cheat_keep_echoes=1\n",
                             "cheat_echo_multiplier=5\n", "cheat_no_durability=1\n", "cheat_consumables=1\n"}) {
        assert(Read(path).find(line) != std::string::npos);
    }
    {
        std::ofstream file(path);
        file << "cheat_stamina=0\ncheat_stealth=0\ncheat_gun_range=250\ncheat_keep_echoes=0\n"
                "cheat_echo_multiplier=3\ncheat_no_durability=0\ncheat_consumables=0\n";
    }
    BbSettings::Load();
    assert(!s.cheat_stamina && !s.cheat_stealth && !s.cheat_keep_echoes && !s.cheat_no_durability && !s.cheat_consumables);
    assert(s.cheat_gun_range == 0 && s.cheat_echo_multiplier == 1);
    { std::ofstream file(path); file << "cheat_gun_range=300\ncheat_echo_multiplier=10\n"; }
    BbSettings::Load();
    assert(s.cheat_gun_range == 300 && s.cheat_echo_multiplier == 10);
    { std::ofstream file(path); file << "cheat_gun_range=off\ncheat_echo_multiplier=x2\n"; }
    BbSettings::Load();
    assert(s.cheat_gun_range == 0 && s.cheat_echo_multiplier == 1);
    BbSettings::Save();
    assert(Read(path).find("cheat_gun_range=off\n") != std::string::npos);
    assert(Read(path).find("cheat_echo_multiplier=1\n") != std::string::npos);
    assert(Read(path).find("hdr=0\n") != std::string::npos);
    assert(Read(path).find("hdr_paper_white=200\n") != std::string::npos);
    assert(Read(path).find("hdr_peak=1000\n") != std::string::npos);
    assert(Read(path).find("hdr_boost=0.25\n") != std::string::npos);
    assert(s.hdr_mode == BbSettings::HdrModeNative);
    assert(Read(path).find("hdr_mode=native\n") != std::string::npos);
    { std::ofstream file(path); file << "hdr=1\nhdr_paper_white=250\nhdr_peak=20000\nhdr_boost=0.75\n"
                                        "hdr_mode=expand\n"; }
    BbSettings::Load();
    assert(s.hdr && s.startup_hdr && s.hdr_paper_white == 250.0f && s.hdr_peak == 4000.0f &&
           s.hdr_boost == 0.75f && s.hdr_mode == BbSettings::HdrModeExpand);
    BbSettings::Save();
    for (const char* line : {"hdr=1\n", "hdr_paper_white=250\n", "hdr_peak=4000\n", "hdr_boost=0.75\n",
                             "hdr_mode=expand\n"}) {
        assert(Read(path).find(line) != std::string::npos);
    }
    assert(Read(path).find("hdr_mode=native\n") == std::string::npos);
    { std::ofstream file(path); file << "hdr=0\nhdr_paper_white=10\nhdr_peak=nan\nhdr_boost=-1\n"
                                        "hdr_mode=bright\n"; }
    BbSettings::Load();
    assert(!s.hdr && !s.startup_hdr && s.hdr_paper_white == 10.0f && s.hdr_peak == 1000.0f &&
           s.hdr_boost == 0.0f && s.hdr_mode == BbSettings::HdrModeNative);
    { std::ofstream file(path); file << "hdr_mode=expand\n"; }
    BbSettings::Load();
    assert(s.hdr_mode == BbSettings::HdrModeExpand);
    { std::ofstream file(path); file << "hdr_mode=native\n"; }
    BbSettings::Load();
    assert(s.hdr_mode == BbSettings::HdrModeNative);
    assert(s.graphics_tonemapper == BbSettings::TonemapperOriginal && s.graphics_gt7_exposure == 1.0f);
    BbSettings::Save();
    assert(Read(path).find("graphics_tonemapper=original\n") != std::string::npos);
    { std::ofstream file(path); file << "graphics_tonemapper=gt7\ngraphics_gt7_exposure=1.5\n"; }
    BbSettings::Load();
    assert(s.graphics_tonemapper == BbSettings::TonemapperGt7 && s.graphics_gt7_exposure == 1.5f);
    BbSettings::Save();
    assert(Read(path).find("graphics_tonemapper=gt7\n") != std::string::npos);
    assert(Read(path).find("graphics_gt7_exposure=1.50\n") != std::string::npos);
    { std::ofstream file(path); file << "graphics_tonemapper=aces\ngraphics_gt7_exposure=99\n"; }
    BbSettings::Load();
    assert(s.graphics_tonemapper == BbSettings::TonemapperAces &&
           s.graphics_gt7_exposure == BbSettings::Gt7ExposureMax);
    BbSettings::Save();
    assert(Read(path).find("graphics_tonemapper=aces\n") != std::string::npos);
    { std::ofstream file(path); file << "graphics_tonemapper=unknown\n"; }
    BbSettings::Load();
    assert(s.graphics_tonemapper == BbSettings::TonemapperOriginal);
    { std::ofstream file(path); file << "graphics_gt7_exposure=nan\n"; }
    BbSettings::Load();
    assert(s.graphics_gt7_exposure == 1.0f);
    assert(s.graphics_bloom_quality == BbSettings::BloomQualityOriginal &&
           s.startup_bloom_quality == BbSettings::BloomQualityOriginal &&
           s.graphics_froyok_bloom_blend == 0.1f &&
           s.graphics_froyok_bloom_spread == BbSettings::FroyokSpreadDefault);
    { std::ofstream file(path); file << "graphics_bloom_quality=froyok\n"
                                        "graphics_froyok_bloom_blend=0.2\n"
                                        "graphics_froyok_bloom_spread=0.7\n"; }
    BbSettings::Load();
    assert(s.graphics_bloom_quality == BbSettings::BloomQualityFroyok &&
           s.startup_bloom_quality == BbSettings::BloomQualityFroyok &&
           s.graphics_froyok_bloom_blend == 0.2f && s.graphics_froyok_bloom_spread == 0.7f);
    BbSettings::Save();
    assert(Read(path).find("graphics_bloom_quality=froyok\n") != std::string::npos);
    assert(Read(path).find("graphics_froyok_bloom_blend=0.200\n") != std::string::npos);
    assert(Read(path).find("graphics_froyok_bloom_spread=0.700\n") != std::string::npos);
    { std::ofstream file(path); file << "graphics_bloom_quality=unknown\n"
                                        "graphics_froyok_bloom_blend=nan\n"
                                        "graphics_froyok_bloom_spread=nan\n"; }
    BbSettings::Load();
    assert(s.graphics_bloom_quality == BbSettings::BloomQualityOriginal &&
           s.startup_bloom_quality == BbSettings::BloomQualityOriginal &&
           s.graphics_froyok_bloom_blend == 0.1f &&
           s.graphics_froyok_bloom_spread == BbSettings::FroyokSpreadDefault);
    { std::ofstream file(path); file << "graphics_froyok_bloom_blend=-1\n"
                                        "graphics_froyok_bloom_spread=2\n"; }
    BbSettings::Load();
    assert(s.graphics_froyok_bloom_blend == BbSettings::FroyokBlendMin &&
           s.graphics_froyok_bloom_spread == BbSettings::FroyokSpreadDefault);
    { std::ofstream file(path); file << "graphics_froyok_bloom_blend=1\n"
                                        "graphics_froyok_bloom_spread=-1\n"; }
    BbSettings::Load();
    assert(s.graphics_froyok_bloom_blend == BbSettings::FroyokBlendMax &&
           s.graphics_froyok_bloom_spread == BbSettings::FroyokSpreadMin);
    { std::ofstream file(path); file << "hdr_mode=native\n"; }
#ifdef _WIN32
    _putenv_s("BB_HDR", "1");
    _putenv_s("BB_HDR_PEAK", "600");
    _putenv_s("BB_HDR_MODE", "expand");
#else
    setenv("BB_HDR", "1", 1);
    setenv("BB_HDR_PEAK", "600", 1);
    setenv("BB_HDR_MODE", "expand", 1);
#endif
    BbSettings::Load();
    assert(s.hdr && s.startup_hdr && s.hdr_peak == 600.0f && s.hdr_paper_white == 10.0f &&
           s.hdr_mode == BbSettings::HdrModeExpand);
#ifdef _WIN32
    _putenv_s("BB_HDR", "");
    _putenv_s("BB_HDR_PEAK", "");
    _putenv_s("BB_HDR_MODE", "");
#else
    unsetenv("BB_HDR");
    unsetenv("BB_HDR_PEAK");
    unsetenv("BB_HDR_MODE");
#endif
    BbSettings::Load();
    assert(s.hdr_mode == BbSettings::HdrModeNative);
    assert(!s.hdr_peak_auto);
    { std::ofstream file(path); file << "hdr_peak=800\nhdr_peak_auto=1\n"; }
    BbSettings::Load();
    assert(s.hdr_peak_auto && s.hdr_peak == 800.0f);
    s.hdr_display_peak = 450.0f;
    assert(BbSettings::HdrPeakNits(s) == 450.0f);
    s.hdr_display_peak = 5.0f;
    assert(BbSettings::HdrPeakNits(s) == 800.0f);
    s.hdr_display_peak = 9000.0f;
    assert(BbSettings::HdrPeakNits(s) == BbSettings::HdrPeakMax);
    s.hdr_peak_auto = false;
    s.hdr_display_peak = 450.0f;
    assert(BbSettings::HdrPeakNits(s) == 800.0f);
    BbSettings::Save();
    assert(Read(path).find("hdr_peak_auto=0\n") != std::string::npos);
    { std::ofstream file(path); file << "hdr_peak_auto=1\n"; }
    BbSettings::Load();
    assert(s.hdr_peak_auto);
    BbSettings::Save();
    assert(Read(path).find("hdr_peak_auto=1\n") != std::string::npos);
    s.hdr_compare = true;
    BbSettings::Save();
    assert(Read(path).find("hdr_compare") == std::string::npos);
    s.hdr_compare = false;
    s.hdr_display_peak = 0.0f;
    {
        std::ofstream file(path);
        file << "dlss_preset=e\ndlss_mip_bias=0\noptiscaler_compat=0\noptiscaler_sync_submit=1\n";
    }
    BbSettings::Load();
    assert(s.dlss_preset == 5 && !s.dlss_mip_bias && !s.optiscaler_compat &&
           s.optiscaler_sync_submit == BbSettings::OptiSubmitOn);
    assert(!s.startup_optiscaler.compat && s.startup_optiscaler.sync_submit == BbSettings::OptiSubmitOn);
    s.dlss_preset = BbSettings::DlssPresetDefault;
    s.optiscaler_compat = true;
    s.optiscaler_sync_submit = BbSettings::OptiSubmitAuto;
    BbSettings::Save();
    {
        const std::string text = Read(path);
        assert(text.find("dlss_preset=default\n") != std::string::npos);
        assert(text.find("dlss_mip_bias=0\n") != std::string::npos);
        assert(text.find("optiscaler_compat=1\n") != std::string::npos);
        assert(text.find("optiscaler_sync_submit=auto\n") != std::string::npos);
    }
    assert(!s.startup_optiscaler.compat);
#ifdef _WIN32
    _putenv_s("BB_DLSS_PRESET", "K");
#else
    setenv("BB_DLSS_PRESET", "K", 1);
#endif
    BbSettings::Load();
    assert(s.dlss_preset == BbSettings::DlssPresetK && s.optiscaler_compat && s.startup_optiscaler.compat);
#ifdef _WIN32
    _putenv_s("BB_DLSS_PRESET", "");
#else
    unsetenv("BB_DLSS_PRESET");
#endif
    // bbport (r77_parallel-test-runs): BB_CLEAN_SHOT=1 starts with clean shot on; another value
    // or none leaves it off.
#ifdef _WIN32
    _putenv_s("BB_CLEAN_SHOT", "1");
#else
    setenv("BB_CLEAN_SHOT", "1", 1);
#endif
    BbSettings::Load();
    assert(s.clean_shot.load());
#ifdef _WIN32
    _putenv_s("BB_CLEAN_SHOT", "yes");
#else
    setenv("BB_CLEAN_SHOT", "yes", 1);
#endif
    BbSettings::Load();
    assert(!s.clean_shot.load());
#ifdef _WIN32
    _putenv_s("BB_CLEAN_SHOT", "");
#else
    unsetenv("BB_CLEAN_SHOT");
#endif
    BbSettings::Load();
    assert(!s.clean_shot.load());
    assert(BbSettings::DlssPresetFromText("m") == 13 && std::string(BbSettings::DlssPresetText(13)) == "m");
    assert(std::string(BbSettings::DlssPresetText(BbSettings::DlssPresetDefault)) == "default");
    assert(BbSettings::DlssPresetFromText("a") == BbSettings::DlssPresetK);
    assert(BbSettings::DlssPresetFromText("h") == BbSettings::DlssPresetK);
    assert(BbSettings::DlssPresetFromText("j") == 10 && BbSettings::DlssPresetFromText("f") == 6);
    {
        std::ofstream file(path);
        file << "frame_gen=dlss\nframe_gen_frames=9\nreflex=boost\npreset=5\nrender_scale=1.3\n"
                "mip_bias=-5\ndlss_auto_exposure=1\n";
    }
    BbSettings::Load();
    assert(s.frame_gen == BbSettings::FrameGenDlss && s.startup_frame_gen == BbSettings::FrameGenDlss);
    assert(s.frame_gen_frames == BbSettings::FrameGenFramesMax && s.reflex == BbSettings::ReflexBoost);
    assert(s.preset == BbSettings::PresetCustom && s.render_scale == 1.3f && s.dlss_auto_exposure);
    assert(s.mip_bias == BbSettings::MipBiasMin);
    assert(BbSettings::PresetScale(BbSettings::PresetCustom) == 1.3f);
    assert(BbSettings::ModelPreset(BbSettings::PresetCustom) == BbSettings::Quality);
    assert(BbSettings::ModelPreset(BbSettings::Performance) == BbSettings::Performance);
    s.render_scale = 1.1f;
    assert(BbSettings::ModelPreset(BbSettings::PresetCustom) == BbSettings::NativeAA);
    BbSettings::Save();
    {
        const std::string text = Read(path);
        assert(text.find("frame_gen=dlss\n") != std::string::npos);
        assert(text.find("frame_gen_frames=5\n") != std::string::npos);
        assert(text.find("reflex=boost\n") != std::string::npos);
        assert(text.find("render_scale=1.10\n") != std::string::npos);
        assert(text.find("mip_bias=-2.00\n") != std::string::npos);
        assert(text.find("dlss_auto_exposure=1\n") != std::string::npos);
    }
    { std::ofstream file(path); file << "frame_gen=fsr3\nreflex=sometimes\nrender_scale=9\n"; }
    BbSettings::Load();
    assert(s.frame_gen == BbSettings::FrameGenFsr3 && s.reflex == BbSettings::ReflexOn &&
           s.render_scale == BbSettings::RenderScaleMax);
    // bbport (r15_far-shadow-setting): graphics_sun_far_shadows takes names, an unknown one is the
    // game's own, and the start value stays what the hook uses after a menu change.
    assert(s.graphics_sun_far_shadows == BbSettings::SunFarGame);
    { std::ofstream file(path); file << "graphics_sun_far_shadows=rare\n"; }
    BbSettings::Load();
    assert(s.graphics_sun_far_shadows == BbSettings::SunFarRare && s.startup_sun_far_shadows == BbSettings::SunFarRare);
    s.graphics_sun_far_shadows = BbSettings::SunFarAlternate;
    BbSettings::Save();
    assert(Read(path).find("graphics_sun_far_shadows=alternate\n") != std::string::npos);
    assert(s.startup_sun_far_shadows == BbSettings::SunFarRare);
    { std::ofstream file(path); file << "graphics_sun_far_shadows=often\n"; }
    BbSettings::Load();
    assert(s.graphics_sun_far_shadows == BbSettings::SunFarGame && s.startup_sun_far_shadows == BbSettings::SunFarGame);
    // bbport (r37_menu-options): the performance modes. Nothing above sets them: an ini without
    // their keys gives modes off and store auto; they are written back; an unknown value is the
    // default; the store's start value stays what ObjectMotion uses after a menu change.
    assert(!s.graphics_lamp_shadow_half && !s.graphics_gi_reflections_fewer_rays &&
           !s.graphics_rt_sun_half && !s.graphics_rt_far_refit);
    assert(s.object_motion_store == BbSettings::MotionStoreAuto &&
           s.startup_object_motion_store == BbSettings::MotionStoreAuto);
    BbSettings::Save();
    {
        const std::string text = Read(path);
        assert(text.find("graphics_lamp_shadow_half=0\n") != std::string::npos);
        assert(text.find("graphics_gi_reflections_fewer_rays=0\n") != std::string::npos);
        assert(text.find("graphics_rt_sun_half=0\n") != std::string::npos);
        assert(text.find("graphics_rt_far_refit=0\n") != std::string::npos);
        assert(text.find("object_motion_store=auto\n") != std::string::npos);
    }
    { std::ofstream file(path); file << "graphics_lamp_shadow_half=1\ngraphics_gi_reflections_fewer_rays=1\n"
                                        "graphics_rt_sun_half=1\ngraphics_rt_far_refit=1\n"
                                        "object_motion_store=small\n"; }
    BbSettings::Load();
    assert(s.graphics_lamp_shadow_half && s.graphics_gi_reflections_fewer_rays && s.graphics_rt_sun_half &&
           s.graphics_rt_far_refit);
    assert(s.object_motion_store == BbSettings::MotionStoreSmall &&
           s.startup_object_motion_store == BbSettings::MotionStoreSmall);
    s.graphics_rt_sun_half = false;
    s.object_motion_store = BbSettings::MotionStoreLarge;
    BbSettings::Save();
    {
        const std::string text = Read(path);
        assert(text.find("graphics_lamp_shadow_half=1\n") != std::string::npos);
        assert(text.find("graphics_gi_reflections_fewer_rays=1\n") != std::string::npos);
        assert(text.find("graphics_rt_sun_half=0\n") != std::string::npos);
        assert(text.find("graphics_rt_far_refit=1\n") != std::string::npos);
        assert(text.find("object_motion_store=large\n") != std::string::npos);
    }
    assert(s.startup_object_motion_store == BbSettings::MotionStoreSmall);
    BbSettings::Load();
    assert(s.object_motion_store == BbSettings::MotionStoreLarge &&
           s.startup_object_motion_store == BbSettings::MotionStoreLarge && !s.graphics_rt_sun_half);
    { std::ofstream file(path); file << "graphics_lamp_shadow_half=yes\ngraphics_rt_far_refit=8\n"
                                        "graphics_gi_reflections_fewer_rays=on\ngraphics_rt_sun_half=2\n"
                                        "object_motion_store=huge\n"; }
    s.graphics_rt_sun_half = true; // each of the four was on before this Load: the fallback is 0
    BbSettings::Load();
    assert(!s.graphics_lamp_shadow_half && !s.graphics_gi_reflections_fewer_rays &&
           !s.graphics_rt_sun_half && !s.graphics_rt_far_refit);
    assert(s.object_motion_store == BbSettings::MotionStoreAuto &&
           s.startup_object_motion_store == BbSettings::MotionStoreAuto);
    // bbport (r39_master-debug): engine_previous_paths and the debug_* keys. Nothing above sets
    // them: off by default, written back, read, saved after a change (the start values stay),
    // an unknown value is 0.
    // bbport (r40_master-bits): 7 (lamps not drawn apart) and 9 (the Reflex sleep in the flip
    // step) are in the mask as well; of the earlier paths that have a bit, only 14 stays out.
    static_assert(BbSettings::PreviousPathsMask == 1114031498345823968ull);
    static_assert(BbSettings::PreviousPathsMask ==
                  (1023959505797356640ull | 1ull << 13 | 1ull << 20 | 1ull << 54 | 1ull << 56 |
                   1ull << 7 | 1ull << 9));
    static_assert(sizeof(BbSettings::PreviousPathsBits) / sizeof(int) == 42); // none twice
    {
        int bits = 0;
        for (int bit = 0; bit < 64; ++bit) {
            bits += int(BbSettings::PreviousPathsMask >> bit & 1);
        }
        assert(bits == 42);
        for (const int bit : {0, 1, 2, 3, 4, 8, 14, 23, 28, 51}) { // left out on purpose
            assert(!(BbSettings::PreviousPathsMask >> bit & 1));
        }
        for (const int bit : {7, 9, 13, 20, 39, 40, 42, 54, 56, 58}) {
            assert(BbSettings::PreviousPathsMask >> bit & 1);
        }
    }
    const int debug_count = BbSettings::DebugSwitchCount;
    assert(!s.engine_previous_paths && !s.startup_engine_previous_paths);
    for (int d = 0; d < debug_count; ++d) {
        assert(!s.debug_switches[d] && !s.startup_debug_switches[d]);
        assert(BbSettings::DebugSwitchOfKey(BbSettings::DebugSwitches[d].key) == d);
    }
    assert(BbSettings::DebugSwitchOfKey("debug_frame_stat") < 0 && BbSettings::DebugSwitchOfKey("") < 0);
    // Which key and which variable belong to which row, one by one.
    static_assert(BbSettings::DebugSwitchCount == 9);
    assert(std::string(BbSettings::DebugSwitches[BbSettings::DebugFrameStats].key) == "debug_frame_stats" &&
           std::string(BbSettings::DebugSwitches[BbSettings::DebugFrameStats].env) == "BB_FRAME_STATS");
    assert(std::string(BbSettings::DebugSwitches[BbSettings::DebugGpuProfile].key) == "debug_gpu_profile" &&
           std::string(BbSettings::DebugSwitches[BbSettings::DebugGpuProfile].env) == "BB_GPU_PROFILE");
    assert(std::string(BbSettings::DebugSwitches[BbSettings::DebugGpuProfileSplit].key) == "debug_gpu_profile_split" &&
           std::string(BbSettings::DebugSwitches[BbSettings::DebugGpuProfileSplit].env) == "BB_GPU_PROFILE_SPLIT");
    assert(std::string(BbSettings::DebugSwitches[BbSettings::DebugSpikeTrace].key) == "debug_spike_trace" &&
           std::string(BbSettings::DebugSwitches[BbSettings::DebugSpikeTrace].env) == "BB_SPIKE_TRACE");
    assert(std::string(BbSettings::DebugSwitches[BbSettings::DebugSubmitDiag].key) == "debug_submit_diag" &&
           std::string(BbSettings::DebugSwitches[BbSettings::DebugSubmitDiag].env) == "BB_SUBMIT_DIAG");
    assert(std::string(BbSettings::DebugSwitches[BbSettings::DebugSceneTrips].key) == "debug_scene_trips" &&
           std::string(BbSettings::DebugSwitches[BbSettings::DebugSceneTrips].env) == "BB_SCENE_TRIPS");
    assert(std::string(BbSettings::DebugSwitches[BbSettings::DebugRtLampTrace].key) == "debug_rt_lamp_trace" &&
           std::string(BbSettings::DebugSwitches[BbSettings::DebugRtLampTrace].env) == "BB_RT_LAMP_TRACE");
    assert(std::string(BbSettings::DebugSwitches[BbSettings::DebugDrawOrder].key) == "debug_draw_order" &&
           std::string(BbSettings::DebugSwitches[BbSettings::DebugDrawOrder].env) == "BB_DRAW_ORDER");
    assert(std::string(BbSettings::DebugSwitches[BbSettings::DebugSunAtlasIgnoreReader].key) == "debug_sun_atlas_ignore_reader" &&
           std::string(BbSettings::DebugSwitches[BbSettings::DebugSunAtlasIgnoreReader].env) == "BB_SUN_ATLAS_IGNORE_READER");
    BbSettings::Save();
    {
        const std::string text = Read(path);
        assert(text.find("engine_previous_paths=0\n") != std::string::npos);
        for (int d = 0; d < debug_count; ++d) {
            assert(text.find(std::string(BbSettings::DebugSwitches[d].key) + "=0\n") != std::string::npos);
        }
    }
    {
        std::ofstream file(path);
        file << "engine_previous_paths=1\n";
        for (int d = 0; d < debug_count; ++d) {
            file << BbSettings::DebugSwitches[d].key << "=1\n";
        }
    }
    BbSettings::Load();
    assert(s.engine_previous_paths && s.startup_engine_previous_paths);
    for (int d = 0; d < debug_count; ++d) {
        assert(s.debug_switches[d] && s.startup_debug_switches[d]);
    }
    s.engine_previous_paths = false;
    s.debug_switches[BbSettings::DebugGpuProfile] = false;
    BbSettings::Save();
    {
        const std::string text = Read(path);
        assert(text.find("engine_previous_paths=0\n") != std::string::npos);
        assert(text.find("debug_gpu_profile=0\n") != std::string::npos);
        assert(text.find("debug_frame_stats=1\n") != std::string::npos);
        assert(text.find("debug_sun_atlas_ignore_reader=1\n") != std::string::npos);
    }
    assert(s.startup_engine_previous_paths && s.startup_debug_switches[BbSettings::DebugGpuProfile]);
    BbSettings::Load();
    assert(!s.engine_previous_paths && !s.startup_engine_previous_paths);
    assert(!s.debug_switches[BbSettings::DebugGpuProfile] && !s.startup_debug_switches[BbSettings::DebugGpuProfile]);
    assert(s.debug_switches[BbSettings::DebugFrameStats] && s.startup_debug_switches[BbSettings::DebugFrameStats]);
    {
        std::ofstream file(path);
        file << "engine_previous_paths=yes\n";
        for (int d = 0; d < debug_count; ++d) {
            file << BbSettings::DebugSwitches[d].key << (d % 2 ? "=2\n" : "=on\n");
        }
    }
    s.engine_previous_paths = true; // on before this Load, as most of the debug keys: the fallback is 0
    BbSettings::Load();
    assert(!s.engine_previous_paths && !s.startup_engine_previous_paths);
    for (int d = 0; d < debug_count; ++d) {
        assert(!s.debug_switches[d] && !s.startup_debug_switches[d]);
    }
    // The early reader (static initialization in the engine, before Load) reads the debug_* keys
    // of a file exactly as Load does, also where a file is odd.
    {
        const std::string long_line(300, 'x');
        const std::string cases[] = {
            "debug_frame_stats=1\n",
            "debug_frame_stats=1\r\ndebug_gpu_profile=1  \t\r\n",
            "debug_frame_stats = 1\n",
            "debug_frame_stats= 1\n",
            " debug_frame_stats=1\n",
            "#debug_frame_stats=1\n",
            "debug_frame_stats=1\ndebug_frame_stats=0\n",
            "debug_frame_stats=0\ndebug_frame_stats=1\n",
            "debug_frame_stats=1\ndebug_frame_stats=on\n",
            "debug_frame_stats=true\ndebug_gpu_profile=11\ndebug_spike_trace=\ndebug_submit_diag\n",
            "debug_frame_stats=1=1\ndebug_gpu_profile==1\n",
            "debug_draw_order=1",
            "debug_frame_statsx=1\nxdebug_frame_stats=1\nDEBUG_FRAME_STATS=1\n",
            long_line + "\ndebug_scene_trips=1\n",
            std::string(250, 'x') + "debug_spike_trace=1\n",
            std::string(255, 'x') + "debug_draw_order=1\n",
            std::string(255, '=') + "debug_rt_lamp_trace=1\n",
            "upscaler=fsr3\n\n\ndebug_sun_atlas_ignore_reader=1\ndebug_rt_lamp_trace=1\nshow_fps=0\n",
            "",
        };
        const bool expect_first[] = {true,  true,  false, false, false, false, false, true, false, false,
                                     false, false, false, false, false, false, false, false, false};
        int at = 0;
        for (const std::string& text : cases) {
            { std::ofstream file(path, std::ios::binary); file << text; }
            for (int d = 0; d < debug_count; ++d) {
                s.debug_switches[d] = false;
            }
            BbSettings::Load();
            bool early[BbSettings::DebugSwitchCount];
            BbSettings::ReadDebugSwitches(path, early);
            for (int d = 0; d < debug_count; ++d) {
                assert(early[d] == s.debug_switches[d]);
            }
            assert(early[BbSettings::DebugFrameStats] == expect_first[at]);
            ++at;
        }
        assert(s.debug_switches[BbSettings::DebugFrameStats] == false);
        { std::ofstream file(path, std::ios::binary); file << cases[1]; }
        bool early[BbSettings::DebugSwitchCount];
        BbSettings::ReadDebugSwitches(path, early);
        assert(early[BbSettings::DebugFrameStats] && early[BbSettings::DebugGpuProfile] &&
               !early[BbSettings::DebugSpikeTrace]);
        { std::ofstream file(path, std::ios::binary); file << cases[11]; }
        BbSettings::ReadDebugSwitches(path, early);
        assert(early[BbSettings::DebugDrawOrder] && !early[BbSettings::DebugFrameStats]);
        { std::ofstream file(path, std::ios::binary); file << cases[15]; }
        BbSettings::ReadDebugSwitches(path, early); // the 256th character starts a new line, as in Load
        assert(early[BbSettings::DebugDrawOrder]);
    }
    // A key that is 1 puts its variable into the environment as 1, unless the variable is set.
    {
        const auto unset = [](const char* name) {
#ifdef _WIN32
            _putenv_s(name, "");
#else
            unsetenv(name);
#endif
        };
        const auto set = [](const char* name, const char* value) {
#ifdef _WIN32
            _putenv_s(name, value);
#else
            setenv(name, value, 1);
#endif
        };
        for (int d = 0; d < debug_count; ++d) {
            unset(BbSettings::DebugSwitches[d].env);
            assert(!std::getenv(BbSettings::DebugSwitches[d].env));
        }
        set("BB_GPU_PROFILE", "0");
        { std::ofstream file(path); file << "debug_frame_stats=1\ndebug_gpu_profile=1\ndebug_spike_trace=0\n"
                                            "debug_draw_order=1\ndebug_scene_trips=yes\n"; }
        const BbSettings::DebugSwitchState state = BbSettings::ApplyDebugSwitches(path);
        for (int d = 0; d < debug_count; ++d) {
            const bool key_on = d == BbSettings::DebugFrameStats || d == BbSettings::DebugGpuProfile ||
                                d == BbSettings::DebugDrawOrder;
            const bool was_set = d == BbSettings::DebugGpuProfile;
            assert(state.ini[d] == key_on && state.env_set[d] == was_set);
            assert(state.applied[d] == (key_on && !was_set));
            const char* env = std::getenv(BbSettings::DebugSwitches[d].env);
            if (state.applied[d]) { // the value starts with 1 (what the readers test) and names its source
                assert(env && env[0] == '1' && std::string(env) == BbSettings::DebugSwitchValue);
            } else if (was_set) {
                assert(env && std::string(env) == "0"); // the variable that was set stays as it was
            } else {
                assert(!env);
            }
        }
        // The next engine process of a restart inherits these variables: one that came from a key
        // is not one set from outside, it follows the key again.
        const BbSettings::DebugSwitchState again = BbSettings::ApplyDebugSwitches(path);
        assert(!again.env_set[BbSettings::DebugFrameStats] && again.applied[BbSettings::DebugFrameStats]);
        assert(again.env_set[BbSettings::DebugGpuProfile] && !again.applied[BbSettings::DebugGpuProfile]);
        assert(std::string(std::getenv("BB_FRAME_STATS")) == BbSettings::DebugSwitchValue);
        set("BB_SCENE_TRIPS", "1"); // set from outside, its key not 1: stays, and decides
        { std::ofstream file(path); file << "debug_frame_stats=0\ndebug_gpu_profile=0\ndebug_scene_trips=0\n"; }
        const BbSettings::DebugSwitchState off = BbSettings::ApplyDebugSwitches(path);
        for (int d = 0; d < debug_count; ++d) {
            const bool outside = d == BbSettings::DebugGpuProfile || d == BbSettings::DebugSceneTrips;
            assert(!off.ini[d] && !off.applied[d] && off.env_set[d] == outside);
            assert((std::getenv(BbSettings::DebugSwitches[d].env) != nullptr) == outside); // the keys' own are gone
        }
        assert(std::string(std::getenv("BB_GPU_PROFILE")) == "0" && std::string(std::getenv("BB_SCENE_TRIPS")) == "1");
        for (int d = 0; d < debug_count; ++d) {
            unset(BbSettings::DebugSwitches[d].env);
        }
        const std::string missing = filename + ".missing";
        const BbSettings::DebugSwitchState none = BbSettings::ApplyDebugSwitches(missing.c_str());
        for (int d = 0; d < debug_count; ++d) {
            assert(!none.ini[d] && !none.env_set[d] && !none.applied[d]);
            assert(!std::getenv(BbSettings::DebugSwitches[d].env));
        }
        // The start of a process, seen in a child (this program again, DebugSwitchesChild): the
        // keys of the settings file are variables before anything reads them, also for the two
        // readers of static initialization in bbport_toggles.h (stats, spike) and for a reader
        // that runs before all ordinary static initializers (profile: R39ReadBeforeStatics).
        const std::string result = filename + ".start";
        std::filesystem::path self = std::filesystem::absolute(argv[0]);
#ifdef _WIN32
        if (char* program = nullptr; _get_pgmptr(&program) == 0 && program) {
            self = program; // the full path also when the program was found through PATH
        }
#else
        std::error_code no_link;
        if (const auto link = std::filesystem::read_symlink("/proc/self/exe", no_link); !no_link) {
            self = link;
        }
#endif
        std::string command = "\"" + self.make_preferred().string() +
                              "\" --r39-debug-switches-at-start \"" + result + "\"";
#ifdef _WIN32
        command = "\"" + command + "\""; // cmd.exe takes one pair of quotes off the whole line
#endif
        const auto child = [&](const char* expect) {
            std::filesystem::remove(result);
            const int code = std::system(command.c_str());
            const std::string got = Read(result.c_str());
            if (code != 0 || got != expect) {
                std::printf("child: exit %d, got '%s', want '%s'\n", code, got.c_str(), expect);
            }
            assert(code == 0 && got == expect);
        };
        { std::ofstream file(path); file << "debug_frame_stats=1\ndebug_spike_trace=1\ndebug_gpu_profile=1\n"; }
        child("stats=1 spike=1 profile=1 env=1:lantern.ini applied=1 set=0\n");
        set("BB_FRAME_STATS", "0"); // set from outside: it decides; the other keys still act
        child("stats=0 spike=1 profile=1 env=0 applied=0 set=1\n");
        // The process a restart from the menu starts inherits the variables the keys put; the
        // keys are 0 by then: the variables are taken out before anything reads them.
        for (const char* name : {"BB_FRAME_STATS", "BB_SPIKE_TRACE", "BB_GPU_PROFILE"}) {
            set(name, BbSettings::DebugSwitchValue);
        }
        { std::ofstream file(path); file << "debug_frame_stats=0\n"; }
        child("stats=0 spike=0 profile=0 env=(unset) applied=0 set=0\n");
        for (const char* name : {"BB_FRAME_STATS", "BB_SPIKE_TRACE", "BB_GPU_PROFILE"}) {
            unset(name);
        }
        child("stats=0 spike=0 profile=0 env=(unset) applied=0 set=0\n"); // no key, no variable: nothing
        set("BB_SPIKE_TRACE", "1"); // a variable alone, as before the keys existed
        child("stats=0 spike=1 profile=0 env=(unset) applied=0 set=0\n");
        unset("BB_SPIKE_TRACE");
        std::filesystem::remove(result);
    }
    std::filesystem::remove(temporary);
    std::puts("PASS: settings save keeps other keys, menu position");
}
