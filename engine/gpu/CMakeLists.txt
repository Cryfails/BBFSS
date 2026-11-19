# bbport GPU library: shadPS4 video core + shader recompiler + Gnm/VideoOut
# drivers, adapted to the native_probe runtime through shims in shim/.
cmake_minimum_required(VERSION 3.24)
project(bbgpu LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if (NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()
# Frame pointers keep the loader's thread dumps (watchdog, SIGUSR2 sampling) walkable.
add_compile_options(-fno-omit-frame-pointer)

# bbport: link-time optimization (BB_LTO, default on) and profile-guided optimization
# (BB_PGO: off, generate = instrumented build writing into BB_PGO_DIR, use = build with that
# profile). Covers bbgpu and the static libraries linked into it. No -march: the same build
# runs on the Steam Deck.
option(BB_LTO "Link-time optimization of bbgpu" ON)
# bbport: optional instruction set level (BB_MARCH=x86-64-v2 in build.sh; empty: the compiler's
# default, x86-64). v2 (SSE4.2, POPCNT, SSSE3, CX16) is a subset of what the game's own code
# already requires (probe.c check_cpu: AVX, BMI1, LZCNT, POPCNT, SSE4.2, MOVBE), so it shuts out
# no CPU that can run the game; v3 would (it adds AVX2/BMI2/FMA).
set(BB_MARCH "" CACHE STRING "-march for bbgpu and its static libraries (empty: default)")
if (BB_MARCH)
    add_compile_options(-march=${BB_MARCH})
endif()
set(BB_PGO "off" CACHE STRING "Profile-guided optimization: off, generate, use")
set(BB_PGO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../pgo" CACHE PATH "Profile directory")
if (BB_LTO)
    include(CheckIPOSupported)
    check_ipo_supported(RESULT bb_ipo_ok OUTPUT bb_ipo_error)
    if (bb_ipo_ok)
        set(CMAKE_INTERPROCEDURAL_OPTIMIZATION ON)
    else()
        message(WARNING "LTO unavailable: ${bb_ipo_error}")
    endif()
endif()
if (BB_PGO STREQUAL "generate")
    # Atomic counters: the GPU, recording, preparation and copy threads run the same code.
    # GCC writes .gcda files into BB_PGO_DIR, clang default_<pool>.profraw files (build.sh merges
    # them into default.profdata with llvm-profdata).
    add_compile_options(-fprofile-generate=${BB_PGO_DIR} -fprofile-update=atomic)
    add_link_options(-fprofile-generate=${BB_PGO_DIR})
    add_compile_definitions(BB_PGO_GENERATE)
elseif (BB_PGO STREQUAL "use" AND CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    # bbport: clang (MSYS2 CLANG64 on Windows) reads one merged profile. It has no
    # -fprofile-partial-training; -pgso=false keeps code the profile never ran from being
    # optimized for size instead (the closest equivalent). Changed functions are compiled
    # without profile data (warnings off).
    add_compile_options(-fprofile-use=${BB_PGO_DIR}/default.profdata
                        -Wno-profile-instr-missing -Wno-profile-instr-out-of-date
                        -Wno-profile-instr-unprofiled -Wno-backend-plugin
                        "SHELL:-mllvm -pgso=false")
elseif (BB_PGO STREQUAL "use")
    # Partial training keeps unprofiled code optimized normally; counters from concurrent
    # threads can be slightly inconsistent (correction). Functions changed since the profile
    # (or built differently for it, bbgpu_init) are compiled without it.
    add_compile_options(-fprofile-use=${BB_PGO_DIR} -fprofile-partial-training
                        -fprofile-correction -Wno-missing-profile -Wno-coverage-mismatch)
endif()

find_package(Vulkan REQUIRED)
find_package(fmt REQUIRED)
find_package(Boost REQUIRED)
find_package(tsl-robin-map REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(XXHASH REQUIRED IMPORTED_TARGET libxxhash)
pkg_check_modules(SDL3 REQUIRED IMPORTED_TARGET sdl3)
pkg_check_modules(OPUS REQUIRED IMPORTED_TARGET opus)
find_package(Zydis REQUIRED)
if (WIN32)
    # bbport: Windows (MSYS2 MINGW64). bbgpu is a static library linked into bb-probe.exe
    # (a DLL cannot leave the runtime_* symbols undefined). Packages MSYS2 does not ship
    # (magic_enum, miniz, xbyak) are fetched; VMA is header-only there.
    include(FetchContent)
    find_package(magic_enum QUIET)
    if (NOT TARGET magic_enum::magic_enum)
        FetchContent_Declare(magic_enum GIT_REPOSITORY https://github.com/Neargye/magic_enum.git
            GIT_TAG v0.9.7 GIT_SHALLOW TRUE)
        FetchContent_MakeAvailable(magic_enum)
    endif()
    find_package(miniz QUIET)
    if (NOT TARGET miniz::miniz)
        set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
        set(BUILD_TESTS OFF CACHE BOOL "" FORCE)
        set(BUILD_FUZZERS OFF CACHE BOOL "" FORCE)
        set(BUILD_NO_STDIO OFF CACHE BOOL "" FORCE)
        FetchContent_Declare(miniz GIT_REPOSITORY https://github.com/richgel999/miniz.git
            GIT_TAG 3.1.0 GIT_SHALLOW TRUE)
        FetchContent_MakeAvailable(miniz)
        if (NOT TARGET miniz::miniz)
            add_library(miniz::miniz ALIAS miniz)
        endif()
    endif()
    find_package(VulkanMemoryAllocator CONFIG QUIET)
    if (NOT TARGET GPUOpen::VulkanMemoryAllocator)
        find_path(VMA_INCLUDE_DIR vk_mem_alloc.h PATH_SUFFIXES vma REQUIRED)
        add_library(GPUOpen::VulkanMemoryAllocator INTERFACE IMPORTED)
        set_target_properties(GPUOpen::VulkanMemoryAllocator PROPERTIES
            INTERFACE_INCLUDE_DIRECTORIES ${VMA_INCLUDE_DIR})
    endif()
else()
    find_package(magic_enum REQUIRED)
    find_package(VulkanMemoryAllocator CONFIG REQUIRED)
    pkg_check_modules(X11 REQUIRED IMPORTED_TARGET x11)
    find_package(miniz REQUIRED)
endif()
# xbyak (header-only; the shader recompiler's flatten pass), fetched when not installed.
find_package(xbyak QUIET)
if (NOT TARGET xbyak::xbyak)
    include(FetchContent)
    FetchContent_Declare(xbyak GIT_REPOSITORY https://github.com/herumi/xbyak.git
        GIT_TAG v7.24.2 GIT_SHALLOW TRUE)
    FetchContent_MakeAvailable(xbyak)
endif()
find_program(GLSLANG_COMPILER NAMES glslang glslangValidator REQUIRED)

set(SIRIT_USE_SYSTEM_SPIRV_HEADERS OFF CACHE BOOL "" FORCE)
add_subdirectory(third_party/sirit EXCLUDE_FROM_ALL)

# bbport: FSR 3.1 temporal upscaling / frame generation, native Vulkan (MIT, FireBurn/FSR-Vulkan).
set(FFX_VK_PORTABLE_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(FFX_VK_PORTABLE_BUILD_PROBE OFF CACHE BOOL "" FORCE)
add_subdirectory(third_party/fsr-vulkan EXCLUDE_FROM_ALL)
if (WIN32)
    # AMD's FidelityFX sources rely on MSVC's transitive includes (memset, floor, placement new,
    # swprintf_s, _countof) on _WIN32.
    foreach(ffx_target IN ITEMS ffx_vulkan_portable ffx_vulkan_fsr3_vk_backend_1_1_4
            ffx_vulkan_fsr3_host_1_1_4 ffx_vulkan_fsr4_v07_vulkan ffx_vulkan_fsr4_v07_assets
            ffx_vulkan_fsr3_vk_framegeneration_3_1_6 ffx_vulkan_fsr3_framegen_3_1_6_scaffold
            ffx_vulkan_fsr3_sdk_core_3_1_5_scaffold)
        if (TARGET ${ffx_target})
            target_compile_options(${ffx_target} PRIVATE "$<$<COMPILE_LANGUAGE:CXX>:SHELL:-include cstdio>"
                "$<$<COMPILE_LANGUAGE:CXX>:SHELL:-include cwchar>" "$<$<COMPILE_LANGUAGE:CXX>:SHELL:-include cstring>"
                "$<$<COMPILE_LANGUAGE:CXX>:SHELL:-include cmath>" "$<$<COMPILE_LANGUAGE:CXX>:SHELL:-include new>"
                "$<$<COMPILE_LANGUAGE:CXX>:SHELL:-include mutex>" "$<$<COMPILE_LANGUAGE:CXX>:SHELL:-include cstdlib>")
        endif()
    endforeach()
endif()

# Host shaders -> headers (same scheme as shadPS4's host_shaders/CMakeLists.txt).
set(SHADER_SRC ${CMAKE_CURRENT_SOURCE_DIR}/shadps4/video_core/host_shaders)
set(SHADER_INCLUDE ${CMAKE_CURRENT_BINARY_DIR}/include)
set(SHADER_DIR ${SHADER_INCLUDE}/video_core/host_shaders)
set(SHADER_HEADERS "")
function(add_host_shader FILENAME SHADER_NAME)
    set(OUT ${SHADER_DIR}/${SHADER_NAME}.h)
    string(TOUPPER ${SHADER_NAME} SYMBOL)
    set(DEFINES ${ARGN})
    list(TRANSFORM DEFINES PREPEND "-D")
    set(INCLUDES "")
    set(STAGE "")
    if (FILENAME MATCHES "\\.frag$" AND SHADER_NAME MATCHES "_comp$")
        set(STAGE -S comp)
    endif()
    if (FILENAME MATCHES "^native_motion_blur")
        list(APPEND INCLUDES ${SHADER_SRC}/native_motion_blur.glsl)
    endif()
    # bbport (r98_ambient-particles): the motes' numbers, shared with C++ (ambient_particles.h)
    if (FILENAME MATCHES "^ambient_particles")
        list(APPEND INCLUDES ${SHADER_SRC}/ambient_particles_layout.h)
    endif()
    if (FILENAME MATCHES "^sun_vsm")
        list(APPEND INCLUDES ${SHADER_SRC}/sun_vsm.glsl)
    endif()
    if (FILENAME MATCHES "^ssgi")
        list(APPEND INCLUDES ${SHADER_SRC}/ssgi_common.glsl)
        # bbport (r83_glass-water-stage1): the gather's GLASS_SCENE build includes the panes' mask
        list(APPEND INCLUDES ${SHADER_SRC}/rt_glass_layout.h)
    endif()
    # bbport (r86_glass-light-stage2a): the sun trace's GLASS_LIGHT builds include the panes' mask
    if (FILENAME MATCHES "^rt_shadow\\.comp$")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_glass_layout.h ${SHADER_SRC}/rt_glass_light_layout.h)
    endif()
    # bbport (r86b_glass-visible): the glass glint's numbers and the panes' mask, shared with C++
    # (glass_glint.h)
    if (FILENAME MATCHES "^glass_glint")
        list(APPEND INCLUDES ${SHADER_SRC}/glass_glint_layout.h ${SHADER_SRC}/rt_glass_layout.h)
    endif()
    # bbport (r117_wind-shelter): the wind shelter's pass and its reader include their layout
    if (FILENAME STREQUAL "window_path_probe.comp")
        list(APPEND INCLUDES ${SHADER_SRC}/window_path_probe_layout.h)
    endif()
    if (FILENAME STREQUAL "interior_roof_probe.comp")
        list(APPEND INCLUDES ${SHADER_SRC}/interior_roof_layout.h)
    endif()
    if (FILENAME MATCHES "^wind_shelter")
        list(APPEND INCLUDES ${SHADER_SRC}/wind_shelter_layout.h ${SHADER_SRC}/wind_shelter.glsl)
    endif()
    # bbport (r82_wind-stage1): the WIND builds and the noise test include the fog noise.
    if (FILENAME MATCHES "^volumetric_light|^wind_noise")
        list(APPEND INCLUDES ${SHADER_SRC}/wind_noise.glsl)
    endif()
    # bbport (r88_wind-lamp-fog): and the lamp fog's WIND builds, with the wind words' layout.
    if (FILENAME MATCHES "^point_volumetric")
        list(APPEND INCLUDES ${SHADER_SRC}/wind_noise.glsl ${SHADER_SRC}/lamp_wind_layout.h)
    endif()
    # bbport (r106_lamp-fog-shaft-cap): the lamp fog shafts' table layout, shared with C++
    if (FILENAME MATCHES "^point_volumetric|^lamp_fog_shaft_map")
        list(APPEND INCLUDES ${SHADER_SRC}/lamp_fog_shaft_layout.h)
    endif()
    if (FILENAME MATCHES "^paint_")
        list(APPEND INCLUDES ${SHADER_SRC}/paint_common.glsl)
    endif()
    # bbport (r54_leaf-stage2): the card UV pass's layout, shared with C++ (rt_card_uv.h)
    if (FILENAME MATCHES "^rt_card_uv")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_uv_layout.h)
    endif()
    # bbport (r62e_leaf-cards-usable): the cut-out guard's layout, shared with C++ (rt_card_still.h)
    if (FILENAME MATCHES "^rt_card_guard")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_guard_layout.h)
    endif()
    # bbport (r62_leaf-stage3): the card alpha passes' layout and the card test
    if (FILENAME MATCHES "^rt_card_(alpha|view)")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_cards.glsl
             ${SHADER_SRC}/rt_card_uv_layout.h)
    endif()
    # bbport (r63_leaf-stage4): the lamp pass's CARDS builds include the card test
    if (FILENAME MATCHES "^point_shadow_ray")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_cards.glsl
             ${SHADER_SRC}/rt_card_uv_layout.h)
    endif()
    # bbport (r130c_glass-lamp-light): the lamp pass's GLASS builds include the glass light's numbers, shared with C++ (glass_light.h)
    if (FILENAME MATCHES "^point_shadow_ray")
        list(APPEND INCLUDES ${SHADER_SRC}/glass_light_layout.h)
    endif()
    # bbport (r130g_glass-light-forward): and the glass counter's numbers (glass_light_forward.h)
    if (FILENAME MATCHES "^point_shadow_ray")
        list(APPEND INCLUDES ${SHADER_SRC}/glass_light_forward_layout.h)
    endif()
    if (FILENAME MATCHES "^point_shadow_ray" AND "T191=1" IN_LIST ARGN)
        list(APPEND INCLUDES ${SHADER_SRC}/lamp_actual_blocker_layout.h)
    endif()
    # bbport (r131a_foliage-translucency): the back-lit glow pass includes the card test and its own numbers (foliage_glow_layout.h, shared with C++)
    if (FILENAME MATCHES "^foliage_glow")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_cards.glsl ${SHADER_SRC}/rt_card_uv_layout.h
             ${SHADER_SRC}/foliage_glow_layout.h)
    endif()
    # bbport (r81_sun-fog-no-rt): the area light gate's numbers, shared with C++ (volumetric_area_gate.h)
    if (FILENAME MATCHES "^volumetric_(light|area_gate)")
        list(APPEND INCLUDES ${SHADER_SRC}/volumetric_area_layout.h)
    endif()
    # bbport (r95_halation): the halation's numbers, shared with C++ (halation_params.h)
    if (FILENAME MATCHES "^halation")
        list(APPEND INCLUDES ${SHADER_SRC}/halation_layout.h)
    endif()
    # bbport (r100_blood-sheen): the blood sheen's numbers, shared with C++ (blood_sheen.h)
    if (FILENAME MATCHES "^blood_sheen")
        list(APPEND INCLUDES ${SHADER_SRC}/blood_sheen_layout.h)
    endif()
    # bbport (r129a_glass-registry): the glass view's numbers, shared with C++ (glass_registry.h)
    if (FILENAME MATCHES "^glass_view")
        list(APPEND INCLUDES ${SHADER_SRC}/glass_view_layout.h)
    endif()
    # bbport (r131c_cabinet-glass-clear): the glass clear's numbers, shared with C++ (vk_glass_clear.h)
    if (FILENAME MATCHES "^glass_clear")
        list(APPEND INCLUDES ${SHADER_SRC}/glass_clear_layout.h)
    endif()
    # bbport (r107_caustics): the water caustics' numbers, shared with C++ (caustics_params.h)
    if (FILENAME MATCHES "^caustics")
        list(APPEND INCLUDES ${SHADER_SRC}/caustics_layout.h)
    endif()
    # bbport (r94_fog-noise): the NOISE builds include the fog noise and its numbers
    if (FILENAME MATCHES "^volumetric_light")
        list(APPEND INCLUDES ${SHADER_SRC}/fog_noise.glsl ${SHADER_SRC}/fog_noise_layout.h)
    endif()
    # bbport (r105_cloud-shadows): the cloud shadows take the fog noise and its numbers
    if (FILENAME MATCHES "^cloud_shadow")
        list(APPEND INCLUDES ${SHADER_SRC}/fog_noise.glsl ${SHADER_SRC}/fog_noise_layout.h)
    endif()
    # bbport (r119_volumetric-clouds): the cloud layer takes the fog noise, its numbers and its own layout
    if (FILENAME MATCHES "^cloud_layer")
        list(APPEND INCLUDES ${SHADER_SRC}/fog_noise.glsl ${SHADER_SRC}/fog_noise_layout.h
             ${SHADER_SRC}/cloud_layer_layout.h)
    endif()
    # bbport (r100c_blood-pool-probe, TOOL): the probe's numbers, shared with C++ (blood_pool_probe.h)
    if (FILENAME MATCHES "^blood_pool_probe")
        list(APPEND INCLUDES ${SHADER_SRC}/blood_pool_probe_layout.h)
    endif()
    # bbport (r111_footprints): the footprints' numbers, shared with C++ (footprints.h)
    if (FILENAME MATCHES "^footprints")
        list(APPEND INCLUDES ${SHADER_SRC}/footprints_layout.h)
        list(APPEND INCLUDES ${SHADER_SRC}/blood_albedo_layout.h)
    endif()
    add_custom_command(OUTPUT ${OUT}
        COMMAND ${CMAKE_COMMAND} -E make_directory ${SHADER_DIR}
        COMMAND ${GLSLANG_COMPILER} --target-env vulkan1.3 -o ${OUT} --vn ${SYMBOL} ${STAGE} ${DEFINES} ${SHADER_SRC}/${FILENAME}
        COMMAND ${CMAKE_COMMAND} "-DHEADER_FILE=${OUT}" -P ${SHADER_SRC}/AddShaderHeaderInclude.cmake
        DEPENDS ${SHADER_SRC}/${FILENAME} ${INCLUDES} VERBATIM)
    set(SHADER_HEADERS ${SHADER_HEADERS} ${OUT} PARENT_SCOPE)
endfunction()
add_host_shader(color_to_ms_depth.frag color_to_ms_depth_frag)
add_host_shader(ms_image_blit.frag ms_image_blit_frag)
add_host_shader(ms_image_blit.frag ms_image_blit_msaa_frag SRC_MSAA=1)
add_host_shader(fault_buffer_process.comp fault_buffer_process_comp)
add_host_shader(fs_tri.vert fs_tri_vert)
add_host_shader(fsr.comp fsr_easu_comp SAMPLE_EASU=1)
add_host_shader(fsr.comp fsr_rcas_comp SAMPLE_RCAS=1)
add_host_shader(post_process.frag post_process_frag)
add_host_shader(gtao.frag gtao_frag)
# graphics_ao_quality=1 (High, README.md): three directions, the denoiser, full internal resolution.
add_host_shader(gtao.frag gtao_hq_frag GTAO_SPATIAL_HQ=1 GTAO_SLICES=3 GTAO_STEPS=6)
add_host_shader(gtao.frag gtao_single_hq_frag GTAO_SPATIAL_HQ=1 GTAO_SLICES=1 GTAO_STEPS=6)
add_host_shader(gtao.frag gtao_reference_frag GTAO_SPATIAL_HQ=1 GTAO_SLICES=16 GTAO_STEPS=32)
add_host_shader(gtao.frag gtao_full_comp GTAO_COMPUTE=1 GTAO_SPATIAL_HQ=1 GTAO_SLICES=3 GTAO_STEPS=6)
add_host_shader(gtao_denoise.comp gtao_denoise_comp)
add_host_shader(gtao_denoise.comp gtao_denoise_full_comp FULLRES=1)
add_host_shader(gtao_denoise.comp gtao_copy_comp COPY=1)
add_host_shader(ssr.frag ssr_frag)
add_host_shader(ssr_temporal.comp ssr_temporal_resolve_comp RESOLVE=1)
add_host_shader(ssr_temporal.comp ssr_temporal_copy_comp COPY=1)
add_host_shader(ssr_trace.comp ssr_trace_comp)
add_host_shader(contact_shadow.comp contact_shadow_comp)
# bbport (r45_drawn-look): the drawn look's passes (renderer_vulkan/vk_drawn_look.cpp)
add_host_shader(paint_prep.comp paint_prep_comp)
add_host_shader(paint_stats.comp paint_stats_comp)
add_host_shader(paint_mips.comp paint_mips_comp)
add_host_shader(paint_key.comp paint_key_comp)
add_host_shader(paint_key.comp paint_key_last_comp LAST=1)
add_host_shader(paint_strokes.comp paint_strokes_comp)
add_host_shader(paint_lock.comp paint_lock_first_comp FIRST=1)
add_host_shader(paint_lock.comp paint_lock_down_comp DOWN=1)
add_host_shader(paint_lock.comp paint_lock_comp)
add_host_shader(paint_ink.comp paint_ink_comp) # bbport (r55_drawn-look-lines)
# bbport (r97_heat-haze): the heat haze above flames (BB_HEAT_HAZE; renderer_vulkan/vk_heat_haze.cpp)
add_host_shader(heat_haze.comp heat_haze_comp)
add_custom_command(OUTPUT ${SHADER_DIR}/heat_haze_comp.h APPEND DEPENDS ${SHADER_SRC}/heat_haze_layout.h) # bbport (r97b_heat-haze-paths): the shader's include
# bbport (r97f_haze-per-flame): the heat haze's flame finder (renderer_vulkan/vk_heat_haze.cpp)
add_host_shader(heat_haze_find.comp heat_haze_find_comp)
add_custom_command(OUTPUT ${SHADER_DIR}/heat_haze_find_comp.h APPEND DEPENDS ${SHADER_SRC}/heat_haze_find_layout.h)
# bbport (r107_caustics): BB_CAUSTICS only: the water caustics (renderer_vulkan/vk_caustics.cpp)
add_host_shader(caustics.comp caustics_comp)
add_host_shader(caustics.comp caustics_bed_observer_comp BB_BED_OBSERVER=1)
add_host_shader(rt_shadow.comp rt_shadow_comp)
add_host_shader(rt_shadow.comp rt_shadow_coverage_comp COVERAGE_SKIP=1)
add_host_shader(rt_unproject.comp rt_unproject_comp)
add_host_shader(rt_unproject_lamp_affine.comp rt_unproject_lamp_affine_comp)
# bbport (r62d_card-uv-diag): the geometry check of the BLAS inputs (BB_RT_CARD_UV_DIAG not 0,
# or BB_RT_GEOMETRY_CHECK=1)
add_host_shader(rt_geometry_check.comp rt_geometry_check_comp)
# bbport (r47_still-check): the bounds of a captured mesh, for the looks at casters held for still
add_host_shader(rt_still_sig.comp rt_still_sig_comp)
# bbport (r54_leaf-stage2): the cut-out cards' UVs into their records (BB_RT_CARD_ALPHA=1)
add_host_shader(rt_card_uv.comp rt_card_uv_comp)
# bbport (r62_leaf-stage3): the card alpha layers' fill and the card debug view (BB_RT_CARD_ALPHA=2)
add_host_shader(rt_card_alpha_fill.comp rt_card_alpha_fill_comp)
add_host_shader(rt_card_view.comp rt_card_view_comp)
# bbport (r62e_leaf-cards-usable): the guard of the cut-out builds (BB_RT_CARD_ALPHA on)
add_host_shader(rt_card_guard.comp rt_card_guard_comp)
add_host_shader(sun_vsm.comp sun_vsm_comp)
add_host_shader(sun_vsm_draw.vert sun_vsm_draw_vert)
add_host_shader(point_shadow_ray.comp point_shadow_ray_comp)
# bbport (r32_lamp-half): the BB_LAMP_SHADOW_HALF=1 build; the one above is unchanged.
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_comp HALF=1)
# bbport (r60_lamp-centred-window): the BB_LAMP_SHADOW_WINDOW=2 builds (trace and resolve); the
# two above are unchanged.
add_host_shader(point_shadow_ray.comp point_shadow_ray_centred_comp CENTRED=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_comp HALF=1 CENTRED=1)
# bbport (r61_lamp-window-cost): the resolves' own builds of 2 (every dispatch a resolve, no ray
# code); the first two builds above are unchanged.
add_host_shader(point_shadow_ray.comp point_shadow_ray_resolve_comp CENTRED=1 RESOLVE=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_resolve_comp HALF=1 CENTRED=1 RESOLVE=1)
add_host_shader(ssgi_gather_ray.comp ssgi_gather_ray_comp)
# bbport (r83_glass-water-stage1): BB_RT_GLASS on: the bounced light's rays leave the window panes'
# mask out (rt_glass_layout.h); the build above is unchanged.
add_host_shader(ssgi_gather_ray.comp ssgi_gather_ray_glass_comp GLASS_SCENE=1)
# bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1: the four builds of the lamp pass with the cut-out
# cards in its rays (CARDS); the lamp pass's builds above are unchanged.
add_host_shader(point_shadow_ray.comp point_shadow_ray_cards_comp CARDS=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_cards_comp HALF=1 CARDS=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_centred_cards_comp CENTRED=1 CARDS=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_cards_comp HALF=1 CENTRED=1 CARDS=1)
# bbport (r128c_lrt-cutout-props): BB_RT_CARD_SUN=1: the sun trace's two builds with the cut-out cards in its rays (CARDS; the five builds of
# rt_shadow.comp above are unchanged). They include the card test and the sun side's numbers.
add_host_shader(rt_shadow.comp rt_shadow_cards_comp COVERAGE_SKIP=1 CARDS=1)
add_host_shader(rt_shadow.comp rt_shadow_half_cards_comp COVERAGE_SKIP=1 HALF=1 CARDS=1)
add_custom_command(OUTPUT ${SHADER_DIR}/rt_shadow_cards_comp.h APPEND DEPENDS ${SHADER_SRC}/rt_cards.glsl
    ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_card_uv_layout.h ${SHADER_SRC}/rt_card_sun_layout.h)
add_custom_command(OUTPUT ${SHADER_DIR}/rt_shadow_half_cards_comp.h APPEND DEPENDS ${SHADER_SRC}/rt_cards.glsl
    ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_card_uv_layout.h ${SHADER_SRC}/rt_card_sun_layout.h)
# bbport (r131a_foliage-translucency): graphics_foliage_translucency / BB_FOLIAGE_TRANSLUCENCY only: the light through leaves and the back-lit glow. Every
# build above is unchanged, byte for byte: each new form is behind a new define. The COLOUR form of the card alpha fill also writes the colour layers; the
# FOLIAGE form of each CARDS lamp build is CARDS=1 COLOUR=1 FOLIAGE=1 (the lamp's hue comes with the colour image); the sun trace's two CARDS builds get
# a FOLIAGE form (the hue image); the glow is one build.
add_host_shader(rt_card_alpha_fill.comp rt_card_alpha_fill_colour_comp COLOUR=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_cards_colour_foliage_comp CARDS=1 COLOUR=1 FOLIAGE=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_cards_colour_foliage_comp HALF=1 CARDS=1 COLOUR=1 FOLIAGE=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_centred_cards_colour_foliage_comp CENTRED=1 CARDS=1 COLOUR=1 FOLIAGE=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_cards_colour_foliage_comp HALF=1 CENTRED=1 CARDS=1 COLOUR=1 FOLIAGE=1)
add_host_shader(rt_shadow.comp rt_shadow_cards_foliage_comp COVERAGE_SKIP=1 CARDS=1 FOLIAGE=1)
add_host_shader(rt_shadow.comp rt_shadow_half_cards_foliage_comp COVERAGE_SKIP=1 HALF=1 CARDS=1 FOLIAGE=1)
add_custom_command(OUTPUT ${SHADER_DIR}/rt_shadow_cards_foliage_comp.h APPEND DEPENDS ${SHADER_SRC}/rt_cards.glsl
    ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_card_uv_layout.h ${SHADER_SRC}/rt_card_sun_layout.h)
add_custom_command(OUTPUT ${SHADER_DIR}/rt_shadow_half_cards_foliage_comp.h APPEND DEPENDS ${SHADER_SRC}/rt_cards.glsl
    ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_card_uv_layout.h ${SHADER_SRC}/rt_card_sun_layout.h)
add_host_shader(foliage_glow.comp foliage_glow_comp)
add_host_shader(bottle_caustic.comp bottle_caustic_comp)
add_host_shader(bottle_cold_validate.comp bottle_cold_validate_comp)
add_host_shader(reflection_first_hit.comp reflection_first_hit_comp)
add_host_shader(foliage_glow.comp foliage_glow_mask_comp FOLIAGE_MASK=1)
# bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1: the COLOUR form of each lamp build without
# CARDS (one binding more, the colour image); the lamp pass's builds above are unchanged.
add_host_shader(point_shadow_ray.comp point_shadow_ray_colour_comp COLOUR=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_colour_comp HALF=1 COLOUR=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_centred_colour_comp CENTRED=1 COLOUR=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_colour_comp HALF=1 CENTRED=1 COLOUR=1)
# bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT=1: the GLASS form of each tracing COLOUR build (lamp light through glass); the
# builds above are unchanged, byte for byte. The two resolve builds do not trace and have none.
add_host_shader(point_shadow_ray.comp point_shadow_ray_colour_glass_comp COLOUR=1 GLASS=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_colour_glass_comp HALF=1 COLOUR=1 GLASS=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_centred_colour_glass_comp CENTRED=1 COLOUR=1 GLASS=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_colour_glass_comp HALF=1 CENTRED=1 COLOUR=1 GLASS=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_resolve_colour_comp CENTRED=1 RESOLVE=1 COLOUR=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_resolve_colour_comp HALF=1 CENTRED=1 RESOLVE=1 COLOUR=1)
# t131e TEST TOOL: reuse the standard colour layouts and keep the original shaders for off.
add_host_shader(point_shadow_ray.comp point_shadow_ray_colour_t131e_comp COLOUR=1 T131E=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_centred_colour_t131e_comp CENTRED=1 COLOUR=1 T131E=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_resolve_colour_t131e_comp CENTRED=1 RESOLVE=1 COLOUR=1 T131E=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_colour_t131e_comp HALF=1 COLOUR=1 T131E=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_colour_t131e_comp HALF=1 CENTRED=1 COLOUR=1 T131E=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_resolve_colour_t131e_comp HALF=1 CENTRED=1 RESOLVE=1 COLOUR=1 T131E=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_t191_comp HALF=1 CENTRED=1 T191=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_resolve_t191_comp HALF=1 CENTRED=1 RESOLVE=1 T191=1)
add_host_shader(rt_shadow_filter.comp rt_shadow_filter_comp)
# bbport (r25_rt-sun-trace): the engine's build (fade-0 shortcut, counters); tests keep the plain
# one. The BB_RT_SUN_HALF=1 trace is a build of its own, so the default trace carries none of it.
add_host_shader(rt_shadow_filter.comp rt_shadow_filter_r25_comp R25=1)
add_host_shader(rt_shadow.comp rt_shadow_half_comp COVERAGE_SKIP=1 HALF=1)
# bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: the sun trace's builds that also ask the
# window panes (rt_glass_light.h); the builds above are unchanged.
add_host_shader(rt_shadow.comp rt_shadow_glass_comp COVERAGE_SKIP=1 GLASS_LIGHT=1)
add_host_shader(rt_shadow.comp rt_shadow_half_glass_comp COVERAGE_SKIP=1 HALF=1 GLASS_LIGHT=1)
# bbport (r86b_glass-visible): BB_GLASS_GLINT only: the glass glint's two passes
# (renderer_vulkan/vk_glass_glint.cpp)
add_host_shader(glass_glint.comp glass_glint_coarse_comp COARSE=1)
add_host_shader(glass_glint.comp glass_glint_shade_comp SHADE=1)
add_host_shader(rt_lab.comp rt_lab_comp)
add_host_shader(point_shadow.comp point_shadow_comp)
add_host_shader(point_volumetric.comp point_volumetric_comp)
# bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS=1, 2, 3 only: the lamp fog's shadow maps (ray
# queries) and the march's builds reading them (SHAFTS for 1 and 2; VIEW the debug view for 3);
# the build above is unchanged
add_host_shader(lamp_fog_shaft_map.comp lamp_fog_shaft_map_comp)
add_host_shader(point_volumetric.comp point_volumetric_shafts_comp SHAFTS=1)
add_host_shader(point_volumetric.comp point_volumetric_shafts_view_comp SHAFTS=1 VIEW=1)
# bbport (r88_wind-lamp-fog): BB_WIND=1 with BB_WIND_LAMP_FOG above 0 only (made at the first lamp
# fog that drifts): the lamp fog with the wind's fog density, plain and with r80's shadow maps;
# the builds above are unchanged
add_host_shader(point_volumetric.comp point_volumetric_wind_comp WIND=1)
add_host_shader(point_volumetric.comp point_volumetric_shafts_wind_comp SHAFTS=1 WIND=1)
add_host_shader(point_volumetric.comp point_volumetric_shafts_view_wind_comp SHAFTS=1 VIEW=1 WIND=1)
add_host_shader(native_motion_blur.frag native_motion_blur_frag)
add_host_shader(native_motion_blur_test.comp native_motion_blur_test_comp)
add_host_shader(bloom_downsample.frag bloom_downsample_frag)
add_host_shader(froyok_bloom.comp froyok_bloom_downsample_comp DOWNSAMPLE=1 FIRST=0)
add_host_shader(froyok_bloom.comp froyok_bloom_first_comp DOWNSAMPLE=1 FIRST=1)
add_host_shader(froyok_bloom.comp froyok_bloom_upsample_comp UPSAMPLE=1)
# bbport (r111_footprints): BB_FOOTPRINTS on only: the footprints laid into the G-buffer
# (renderer_vulkan/vk_footprints.cpp)
add_host_shader(footprints.comp footprints_comp)
# bbport (r111e_prints-draw): the footprints over the finished picture (flat red test view, post stamp)
add_host_shader(footprints_flat.comp footprints_flat_comp)
# bbport (r95_halation): BB_HALATION above 0 only: the film halation's four passes, one build
# (renderer_vulkan/vk_halation.cpp)
add_host_shader(halation.comp halation_comp)
# bbport (r100_blood-sheen, r100d_blood-sheen-gbuffer): BB_BLOOD_SHEEN on only: the wet film's
# snapshot, mark, wet ground and show passes in the G-buffer (renderer_vulkan/vk_blood_sheen.cpp)
add_host_shader(blood_sheen.comp blood_sheen_snapshot_comp BLOOD_SNAPSHOT=1)
add_host_shader(blood_sheen.comp blood_sheen_mark_comp BLOOD_MARK=1)
add_host_shader(blood_sheen.comp blood_sheen_edit_comp BLOOD_EDIT=1)
add_host_shader(blood_sheen.comp blood_sheen_show_comp BLOOD_SHOW=1)
# bbport (r129a_glass-registry): the glass view's snapshot, mark (G-buffer hit draws), paint (forward hit draws) and show passes
# (renderer_vulkan/vk_glass_view.cpp)
add_host_shader(glass_view.comp glass_view_snapshot_comp GLASS_SNAPSHOT=1)
add_host_shader(glass_view.comp glass_view_mark_comp GLASS_MARK=1)
add_host_shader(glass_view.comp glass_view_paint_comp GLASS_PAINT=1)
add_host_shader(glass_view.comp glass_view_show_comp GLASS_SHOW=1)
# bbport (r131c_cabinet-glass-clear): BB_GLASS_CLEAR on only: the cabinet's pane as a glass layer over the lit scene
# (renderer_vulkan/vk_glass_clear.cpp)
add_host_shader(glass_clear.comp glass_clear_comp)
# bbport (t129c_sun-term-view, TOOL): BB_RT_SUN_TERM_VIEW only: the ray traced sun/moon term's copy and show passes
# (renderer_vulkan/vk_sun_term_view.cpp)
add_host_shader(sun_term_view.comp sun_term_view_copy_comp SUN_TERM_COPY=1)
add_host_shader(sun_term_view.comp sun_term_view_show_comp SUN_TERM_SHOW=1)
# bbport (r100c_blood-pool-probe, TOOL): BB_BLOOD_POOL_PROBE only: the probe's snapshot and compare
# passes (renderer_vulkan/vk_blood_pool_probe.cpp)
add_host_shader(blood_pool_probe.comp blood_pool_probe_snapshot_comp POOL_SNAPSHOT=1)
add_host_shader(blood_pool_probe.comp blood_pool_probe_compare_comp POOL_COMPARE=1)
add_host_shader(volumetric_light.comp volumetric_light_integrate_comp INTEGRATE=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_comp REPAIR=1)
add_host_shader(volumetric_light.comp volumetric_light_tint_comp TINT=1)
add_host_shader(volumetric_light.comp volumetric_light_composite_comp COMPOSITE=1)
add_host_shader(volumetric_light.comp volumetric_light_filter_comp FILTER=1)
# bbport (r51b_volumetric-rt-check): the march and its repair reading the ray traced sun gate, and
# the gate's pass (ray queries); made at the first march with a ray traced scene unless
# BB_VOLUMETRIC_RT_GATE=0 (r76_sun-fog-outdoors: unset is 1)
add_host_shader(volumetric_light.comp volumetric_light_integrate_gate_comp INTEGRATE=1 GATE=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_gate_comp REPAIR=1 GATE=1)
add_host_shader(volumetric_rt_gate.comp volumetric_rt_gate_comp)
# bbport (r76_sun-fog-outdoors): the gate's diagnostics, made only with BB_VOLUMETRIC_GATE_PROBE=1
# or BB_VOLUMETRIC_GATE_VIEW=1: the gate to the nearest hit (DIAG), and with the view the march and
# the composite drawing it (GATE_VIEW); the builds above are unchanged
add_host_shader(volumetric_rt_gate.comp volumetric_rt_gate_diag_comp DIAG=1)
add_host_shader(volumetric_light.comp volumetric_light_integrate_gate_view_comp INTEGRATE=1 GATE=1 GATE_VIEW=1)
add_host_shader(volumetric_light.comp volumetric_light_composite_gate_view_comp COMPOSITE=1 GATE_VIEW=1)
# bbport (r81_sun-fog-no-rt): the area light gate (BB_VOLUMETRIC_AREA_GATE=1, off unless set; for
# marches without the ray traced gate): the march's builds keeping near and far energy and the
# share in sun apart, and the gate's two passes; the builds above are unchanged
add_host_shader(volumetric_light.comp volumetric_light_integrate_area_comp INTEGRATE=1 AREA=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_area_comp REPAIR=1 AREA=1)
# bbport (r85_area-with-rt-gate): BB_VOLUMETRIC_AREA_GATE=1 on marches with the ray traced gate:
# the AREA builds reading the gate (made at the first such march); the builds above are unchanged
add_host_shader(volumetric_light.comp volumetric_light_integrate_gate_area_comp INTEGRATE=1 GATE=1 AREA=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_gate_area_comp REPAIR=1 GATE=1 AREA=1)
# bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE=2 on marches with the ray traced gate (made at
# the first such march): the gate with its wider answer and the AREA+GATE march reading it
add_host_shader(volumetric_light.comp volumetric_light_integrate_gate_area_dual_comp INTEGRATE=1 GATE=1 AREA=1 DUAL=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_gate_area_dual_comp REPAIR=1 GATE=1 AREA=1 DUAL=1)
add_host_shader(volumetric_rt_gate.comp volumetric_rt_gate_dual_comp DUAL=1)
add_host_shader(volumetric_area_gate.comp volumetric_area_gate_camera_comp CAMERA=1)
add_host_shader(volumetric_area_gate.comp volumetric_area_gate_apply_comp APPLY=1)
# bbport (r117_wind-shelter): BB_WIND_SHELTER only: the wind shelter field's passes and, with
# BB_WIND_SHELTER_SHOW, the view that paints it (renderer_vulkan/vk_wind_shelter.cpp)
add_host_shader(wind_shelter.comp wind_shelter_comp)
add_host_shader(wind_shelter.comp wind_shelter_show_comp SHOW=1)
# bbport (r82_wind-stage1): BB_WIND=1 only (made at the first march that drifts): the sun fog
# march with a density drifting with the wind, plain and reading the gate, the BB_WIND_VIEW=1
# composite, and the shader of wind-noise-test.
add_host_shader(volumetric_light.comp volumetric_light_integrate_wind_comp INTEGRATE=1 WIND=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_wind_comp REPAIR=1 WIND=1)
add_host_shader(volumetric_light.comp volumetric_light_integrate_gate_wind_comp INTEGRATE=1 GATE=1 WIND=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_gate_wind_comp REPAIR=1 GATE=1 WIND=1)
add_host_shader(volumetric_light.comp volumetric_light_wind_view_comp COMPOSITE=1 WIND_VIEW=1)
add_host_shader(wind_noise_test.comp wind_noise_test_comp)
# bbport (r94_fog-noise): BB_FOG_NOISE above 0 only (each pair made at its first march): the sun fog
# march with the world anchored fog noise, plain, reading the ray traced gate, with the area light
# gate, and both (vk_volumetric_fog_noise.cpp)
add_host_shader(volumetric_light.comp volumetric_light_integrate_noise_comp INTEGRATE=1 NOISE=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_noise_comp REPAIR=1 NOISE=1)
add_host_shader(volumetric_light.comp volumetric_light_integrate_gate_noise_comp INTEGRATE=1 GATE=1 NOISE=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_gate_noise_comp REPAIR=1 GATE=1 NOISE=1)
add_host_shader(volumetric_light.comp volumetric_light_integrate_area_noise_comp INTEGRATE=1 AREA=1 NOISE=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_area_noise_comp REPAIR=1 AREA=1 NOISE=1)
add_host_shader(volumetric_light.comp volumetric_light_integrate_gate_area_noise_comp INTEGRATE=1 GATE=1 AREA=1 NOISE=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_gate_area_noise_comp REPAIR=1 GATE=1 AREA=1 NOISE=1)
# bbport (r94c_fog-noise-dual-gate): BB_FOG_NOISE with BB_VOLUMETRIC_AREA_GATE=2 on marches with
# the ray traced gate (made at the first such march): the DUAL march with the fog noise in it
add_host_shader(volumetric_light.comp volumetric_light_integrate_gate_area_dual_noise_comp INTEGRATE=1 GATE=1 AREA=1 DUAL=1 NOISE=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_gate_area_dual_noise_comp REPAIR=1 GATE=1 AREA=1 DUAL=1 NOISE=1)
add_host_shader(ssgi.comp ssgi_prep_comp PREP=1)
add_host_shader(ssgi.comp ssgi_gather_comp GATHER=1)
add_host_shader(ssgi.comp ssgi_denoise_comp DENOISE=1)
add_host_shader(ssgi.comp ssgi_composite_comp COMPOSITE=1)
add_host_shader(ssgi_probe.comp ssgi_probe_trace_comp TRACE=1)
add_host_shader(ssgi_probe.comp ssgi_probe_reflect_comp REFLECT=1)
add_host_shader(ssgi_probe.comp ssgi_probe_resolve_comp RESOLVE=1)
add_host_shader(ssgi_probe.comp ssgi_probe_composite_comp COMPOSITE=1)
# bbport (r30_ssgi-half): the BB_SSGI_HALF=1 glossy rays and resolve (made only with it set).
add_host_shader(ssgi_probe.comp ssgi_probe_reflect_half_comp REFLECT=1 HALF=1)
add_host_shader(ssgi_probe.comp ssgi_probe_resolve_half_comp RESOLVE=1 HALF=1)
add_host_shader(depth_of_field.comp depth_of_field_camera_comp CAMERA=1)
add_host_shader(depth_of_field.comp depth_of_field_snapshot_comp SNAPSHOT=1)
add_host_shader(depth_of_field.comp depth_of_field_kernel_comp KERNEL=1)
add_host_shader(depth_of_field.comp depth_of_field_prepare_comp PREPARE=1)
add_host_shader(depth_of_field.comp depth_of_field_gather_comp GATHER=1)
add_host_shader(depth_of_field.comp depth_of_field_composite_comp COMPOSITE=1)
add_host_shader(depth_of_field.comp depth_of_field_focus_comp FOCUS=1)
add_host_shader(depth_of_field.comp depth_of_field_near_tiles_comp NEAR_TILES=1)
add_host_shader(depth_of_field.comp depth_of_field_near_comp NEAR=1)
# bbport (r105_cloud-shadows): BB_CLOUD_SHADOWS above 0 only (both made at the first pass): the
# ground pass on the sun shadow target and the GATE build on the sun fog's ray traced gate
add_host_shader(cloud_shadow.comp cloud_shadow_comp)
add_host_shader(cloud_shadow.comp cloud_shadow_gate_comp GATE=1)
# bbport (r119_volumetric-clouds): BB_VOLUMETRIC_CLOUDS=1 only (both made at the start): the cloud layer's
# march (sky pixels into a half size image) and composite (that image into the scene's sky pixels)
add_host_shader(cloud_layer.comp cloud_layer_march_comp MARCH=1)
add_host_shader(cloud_layer.comp cloud_layer_composite_comp COMPOSITE=1)
add_host_shader(sky_seam.comp sky_seam_comp)
add_host_shader(sky_zenith.comp sky_zenith_validate_comp VALIDATE=1)
add_host_shader(sky_zenith.comp sky_zenith_horizontal_comp HORIZONTAL=1)
add_host_shader(sky_zenith.comp sky_zenith_vertical_comp)
add_host_shader(billboard_probe.vert billboard_probe_vertex)
add_host_shader(billboard_probe.vert billboard_probe_instanced INSTANCED=1)
add_host_shader(billboard_probe.frag billboard_probe_fragment)
add_host_shader(hdr_output.frag hdr_output_frag)
add_host_shader(hdr_native.comp hdr_native_luma_comp LUMA=1)
add_host_shader(hdr_native.comp hdr_native_stats_comp STATS=1)
add_host_shader(hdr_native.comp hdr_native_snapshot_comp STATS=1 SNAPSHOT=1)
add_host_shader(hdr_native.comp hdr_native_exposure_comp EXPOSURE=1)
add_host_shader(hdr_native.comp hdr_native_gain_comp GAIN=1)
add_host_shader(camera_motion.comp camera_motion_comp)
add_host_shader(upscale_merge.comp upscale_merge_comp)
add_host_shader(upscale_debug.comp upscale_debug_comp)
add_host_shader(upscale_debug.comp upscale_debug_ldr_comp LDR_OUTPUT=1)
add_host_shader(upscale_reactive.comp upscale_reactive_comp)
# bbport (r99_interior-exposure): the interior exposure meter (made only with BB_INTERIOR_EXPOSURE=1 or 2)
add_host_shader(interior_meter.comp interior_meter_comp)
add_host_shader(interior_roof_probe.comp interior_roof_probe_comp)
add_host_shader(window_path_probe.comp window_path_probe_comp)
add_host_shader(taa.comp taa_comp)
add_host_shader(taa_sharpen.comp taa_sharpen_comp)
add_host_shader(taa_sharpen.comp taa_sharpen_ldr_comp LDR_OUTPUT=1)
add_host_shader(fsr4_color.comp fsr4_decode_comp)
add_host_shader(fsr4_color.comp fsr4_encode_comp ENCODE=1)
add_host_shader(fsr4_reactive.comp fsr4_reactive_comp)
add_host_shader(frame_gen_compose.comp frame_gen_compose_comp)
add_host_shader(frame_gen_depth.comp frame_gen_depth_comp)
add_host_shader(dlss_ui_alpha.comp dlss_ui_alpha_comp)
add_host_shader(buffer_multi_copy.comp buffer_multi_copy_comp)
add_host_shader(indirect_clamp.comp indirect_clamp_comp)
add_host_shader(depth_resample.frag depth_resample_frag)
add_host_shader(depth_resample.frag depth_stencil_resample_frag HAS_STENCIL=1)
add_host_shader(depth_resample.frag depth_stencil_bits_frag STENCIL_BITS=1)
add_host_shader(depth_to_color.frag depth_to_color_frag)
# bbport (r98_ambient-particles): BB_PARTICLES above 0 only: the ambient motes, drawn after
# the upscale (vk_ambient_particles.cpp)
add_host_shader(ambient_particles.vert ambient_particles_vert)
add_host_shader(ambient_particles.frag ambient_particles_frag)
add_host_shader(camera_motion.comp camera_motion_debug_comp DEBUG_OVERLAY=1)
foreach(BPP IN ITEMS 8 16 32 64 96 128)
    add_host_shader(tiling.comp tiling_micro_${BPP}_comp BITS_PER_PIXEL=${BPP} IS_MACRO_TILED=0)
    add_host_shader(tiling.comp tiling_macro_${BPP}_comp BITS_PER_PIXEL=${BPP} IS_MACRO_TILED=1)
endforeach()
add_custom_target(host_shaders DEPENDS ${SHADER_HEADERS})

file(GLOB_RECURSE VIDEO_CORE CONFIGURE_DEPENDS shadps4/video_core/*.cpp)
file(GLOB_RECURSE RECOMPILER CONFIGURE_DEPENDS shadps4/shader_recompiler/*.cpp)
list(FILTER VIDEO_CORE EXCLUDE REGEX "renderdoc\\.cpp$")
set(COMMON
    shadps4/common/decoder.cpp shadps4/common/error.cpp
    shadps4/common/io_file.cpp shadps4/common/native_clock.cpp shadps4/common/number_utils.cpp
    shadps4/common/path_util.cpp shadps4/common/rdtsc.cpp shadps4/common/spin_lock.cpp shadps4/common/recursive_lock.cpp
    shadps4/common/string_util.cpp shadps4/common/thread.cpp shadps4/common/signal_context.cpp
    shim/common/logging/log.cpp)
pkg_check_modules(FFMPEG REQUIRED IMPORTED_TARGET libavformat libavcodec libavutil libswscale libswresample)
file(GLOB SHIM_SOURCES CONFIGURE_DEPENDS shim/*.cpp shim/*/*.cpp)
if (WIN32)
    # These optional experiments use Linux dma-buf mappings and SIGTRAP hooks (the libGnm entry
    # hooks, bbport_gnm_hooks.cpp, are inline patches and build on Windows too). Keep the
    # section-backed Win32 memory and its vectored crash diagnostics; do not emulate dma-buf.
    list(FILTER SHIM_SOURCES EXCLUDE REGEX "/bbport_(guest_memory|guest_hooks|free_check|heap_sites)\\.cpp$")
    # The PC memory model has Windows files of its own (_win.cpp: host memory import, a vectored
    # exception handler for the guest hooks).
    set(BBGPU_LIBRARY_TYPE STATIC)
else()
    list(FILTER SHIM_SOURCES EXCLUDE REGEX "_win\\.cpp$")
    set(BBGPU_LIBRARY_TYPE SHARED)
endif()
add_library(bbgpu ${BBGPU_LIBRARY_TYPE} ${VIDEO_CORE} ${RECOMPILER} ${COMMON} ${SHIM_SOURCES}
    shadps4/core/libraries/gnmdriver/gnmdriver.cpp)
add_dependencies(bbgpu host_shaders)
target_sources(bbgpu PRIVATE ../tools/engine/sha256.cpp)
add_subdirectory(bbnet)
target_link_libraries(bbgpu PUBLIC bbnet)
# In-game settings menu: Dear ImGui (third_party/imgui, MIT) with its Vulkan backend, and an
# embedded Cyrillic font (third_party/fonts); party names in Flesh and Blood by JoannaVu.
target_sources(bbgpu PRIVATE third_party/imgui/imgui.cpp third_party/imgui/imgui_draw.cpp
    third_party/imgui/imgui_tables.cpp third_party/imgui/imgui_widgets.cpp
    third_party/imgui/backends/imgui_impl_vulkan.cpp)
target_include_directories(bbgpu PRIVATE third_party/imgui third_party/imgui/backends)
target_compile_definitions(bbgpu PRIVATE IMGUI_IMPL_VULKAN_NO_PROTOTYPES
    BB_FONT_PATH="${CMAKE_CURRENT_SOURCE_DIR}/third_party/fonts/DejaVuSans.ttf"
    BB_CJK_FONT_PATH="${CMAKE_CURRENT_SOURCE_DIR}/third_party/fonts/LanternMenuSC.ttf"
    BB_NAME_FONT_PATH="${CMAKE_CURRENT_SOURCE_DIR}/third_party/fonts/FleshAndBlood.ttf"
    BB_KEYCAP_FONT_PATH="${CMAKE_CURRENT_SOURCE_DIR}/third_party/imgui/misc/fonts/Roboto-Medium.ttf")
set_source_files_properties(shim/bbport_overlay.cpp PROPERTIES
    OBJECT_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/third_party/fonts/DejaVuSans.ttf;${CMAKE_CURRENT_SOURCE_DIR}/third_party/fonts/LanternMenuSC.ttf;${CMAKE_CURRENT_SOURCE_DIR}/third_party/fonts/FleshAndBlood.ttf")
# Keyboard prompts' keycaps (shim/engine/keycap_art.cpp): Roboto Medium (Apache License 2.0).
set_source_files_properties(shim/engine/keycap_art.cpp PROPERTIES
    OBJECT_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/third_party/imgui/misc/fonts/Roboto-Medium.ttf)
target_include_directories(bbgpu PRIVATE shim shadps4 ../src ${SHADER_INCLUDE} third_party/gcn/include third_party/half/include)
# bbport: NVIDIA Streamline SDK headers (MIT), for DLSS Frame Generation (vk_streamline.cpp).
target_include_directories(bbgpu PRIVATE third_party/streamline/include)
target_compile_definitions(bbgpu PRIVATE BOOST_ASIO_STANDALONE NDEBUG)
# The separately applied T04 raw-capture build overlay shares C++ renderer types with
# optional tests that link bbgpu. Keep the experiment's definitions on that interface.
target_compile_definitions(bbgpu PUBLIC
    $<$<COMPILE_LANGUAGE:CXX>:BB_TEST_BOTTLE_CUT_SOURCE=1>
    $<$<COMPILE_LANGUAGE:CXX>:BB_TEST_SHARED_POST_GRAPH=1>
    $<$<COMPILE_LANGUAGE:CXX>:BB_TEST_POST_PRESENT_RESOURCES=1>)
target_compile_options(bbgpu PRIVATE -Wno-deprecated-declarations -Wno-missing-field-initializers)
# The Linux shared library is loaded at process startup; Windows links it statically.
if(NOT WIN32)
    target_compile_options(bbgpu PRIVATE -ftls-model=initial-exec)
    target_link_options(bbgpu PRIVATE -Wl,--allow-shlib-undefined)
    # A static FFmpeg (the Linux package's, packaging/linux/setup-ubuntu.sh): its assembly reaches
    # its tables PC-relative, which lld refuses for symbols the library exports. They stay inside.
    target_link_options(bbgpu PRIVATE
        -Wl,--exclude-libs,libavcodec.a:libavformat.a:libavutil.a:libswscale.a:libswresample.a)
endif()
target_link_libraries(bbgpu PRIVATE ffx-vulkan::portable ffx-vulkan::fsr4-v07-vulkan
    ffx-vulkan::fsr3-vk-framegeneration-3.1.6) # bbport: frame generation (vk_frame_generation.cpp)
target_link_libraries(bbgpu PUBLIC Vulkan::Headers fmt::fmt Boost::headers magic_enum::magic_enum
    tsl::robin_map GPUOpen::VulkanMemoryAllocator PkgConfig::XXHASH PkgConfig::SDL3 PkgConfig::OPUS PkgConfig::FFMPEG miniz::miniz Zydis::Zydis sirit
    xbyak::xbyak)
if (WIN32)
    # Windows headers: no min/max macros, no winsock 1 clash; Windows 10+ APIs (SetThreadDescription).
    target_compile_definitions(bbgpu PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN _WIN32_WINNT=0x0A00)
    target_link_libraries(bbgpu PUBLIC setupapi)
    if (BB_PGO STREQUAL "generate")
        # bbport: the instrumented static library needs the profile runtime in bb-probe.exe's
        # link (add_link_options does not reach it): written into bbgpu_link.txt below.
        target_link_options(bbgpu INTERFACE -fprofile-generate=${BB_PGO_DIR})
    endif()
    # bb-probe.exe links libbbgpu.a with these (out/gpu/bbgpu_link.txt, one argument per line,
    # in link order): the static library's transitive dependencies.
    include(cmake/LinkClosure.cmake)
    bb_write_link_closure(bbgpu ${CMAKE_CURRENT_BINARY_DIR}/bbgpu_link.txt)
else()
    # Runtime symbols (runtime_memory_*, runtime_process_*) resolve against bb-probe.
    target_link_options(bbgpu PRIVATE -Wl,--allow-shlib-undefined)
    target_link_libraries(bbgpu PUBLIC PkgConfig::X11)
endif()

# Explicit test targets; neither launches the game nor needs a Vulkan device.
add_executable(pipeline-cache-blob-test EXCLUDE_FROM_ALL ../tests/test_pipeline_cache_blob.cpp)
target_compile_options(pipeline-cache-blob-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(pipeline-cache-blob-test PRIVATE ..)
add_executable(exposure-policy-test EXCLUDE_FROM_ALL ../tests/test_exposure_policy.cpp)
target_compile_options(exposure-policy-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(exposure-policy-test PRIVATE ..)
# bbport (r99_interior-exposure): the interior exposure floor's knobs, rule and easing
# (shim/bbport_interior_exposure.h); also built and run by engine/build.sh --test.
add_executable(interior-exposure-test EXCLUDE_FROM_ALL ../tests/test_interior_exposure.cpp)
target_compile_options(interior-exposure-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(interior-exposure-test PRIVATE ..)
add_executable(native-exposure-test EXCLUDE_FROM_ALL ../tests/test_native_exposure.cpp
    shim/engine/auto_exposure.cpp)
target_include_directories(native-exposure-test PRIVATE shim)
target_compile_options(native-exposure-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
add_executable(native-sss-test EXCLUDE_FROM_ALL ../tests/test_native_sss.cpp
    shim/engine/native_sss.cpp)
target_include_directories(native-sss-test PRIVATE shim)
target_compile_options(native-sss-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
add_executable(billboard-probe-test EXCLUDE_FROM_ALL ../tests/test_billboard_probe.cpp
    ${SHADER_DIR}/billboard_probe_vertex.h ${SHADER_DIR}/billboard_probe_instanced.h
    ${SHADER_DIR}/billboard_probe_fragment.h)
target_include_directories(billboard-probe-test PRIVATE ${SHADER_INCLUDE})
target_compile_options(billboard-probe-test PRIVATE -UNDEBUG -Wall -Wextra -Werror
    -Wno-missing-field-initializers)
target_link_libraries(billboard-probe-test PRIVATE Vulkan::Vulkan)
add_executable(sky-seam-test EXCLUDE_FROM_ALL ../tests/test_sky_seam.cpp
    ${SHADER_DIR}/sky_seam_comp.h)
target_include_directories(sky-seam-test PRIVATE ${SHADER_INCLUDE})
target_compile_options(sky-seam-test PRIVATE -UNDEBUG -Wall -Wextra -Werror
    -Wno-missing-field-initializers)
target_link_libraries(sky-seam-test PRIVATE Vulkan::Vulkan)
add_executable(sky-zenith-test EXCLUDE_FROM_ALL ../tests/test_sky_zenith.cpp
    ${SHADER_DIR}/sky_zenith_validate_comp.h ${SHADER_DIR}/sky_zenith_horizontal_comp.h
    ${SHADER_DIR}/sky_zenith_vertical_comp.h)
target_include_directories(sky-zenith-test PRIVATE ${SHADER_INCLUDE})
target_compile_features(sky-zenith-test PRIVATE cxx_std_20)
target_compile_options(sky-zenith-test PRIVATE -UNDEBUG -Wall -Wextra -Werror
    -Wno-missing-field-initializers)
target_link_libraries(sky-zenith-test PRIVATE Vulkan::Vulkan)
add_executable(depth-of-field-shader-test EXCLUDE_FROM_ALL ../tests/test_depth_of_field.cpp)
target_include_directories(depth-of-field-shader-test PRIVATE ${SHADER_INCLUDE})
target_compile_options(depth-of-field-shader-test PRIVATE -UNDEBUG -Wall -Werror)
target_link_libraries(depth-of-field-shader-test PRIVATE Vulkan::Vulkan)
add_dependencies(depth-of-field-shader-test host_shaders)
add_executable(ggx-directional-test EXCLUDE_FROM_ALL ../tests/test_ggx_directional.cpp)
target_compile_options(ggx-directional-test PRIVATE -Wall -Wextra -Werror
    -Wno-missing-field-initializers)
target_link_libraries(ggx-directional-test PRIVATE Vulkan::Vulkan)
add_executable(ggx-patch-test EXCLUDE_FROM_ALL ../tests/test_ggx_patch.cpp)
target_compile_options(ggx-patch-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
add_executable(ggx-lobes-test EXCLUDE_FROM_ALL ../tests/test_ggx_lobes.cpp)
target_compile_options(ggx-lobes-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
add_executable(local-falloff-test EXCLUDE_FROM_ALL ../tests/test_local_falloff.cpp)
target_compile_options(local-falloff-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
add_executable(local-light-unify-test EXCLUDE_FROM_ALL ../tests/test_local_light_unify.cpp)
target_include_directories(local-light-unify-test PRIVATE shadps4)
target_compile_options(local-light-unify-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
add_executable(image-overlap-test EXCLUDE_FROM_ALL ../tests/test_image_overlap.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_compile_options(image-overlap-test PRIVATE -UNDEBUG)
target_include_directories(image-overlap-test PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(image-overlap-test PRIVATE bbgpu)
if (WIN32)
    target_link_libraries(image-overlap-test PRIVATE winmm ws2_32 psapi onecore)
endif()
set_source_files_properties(../tests/test_image_overlap.cpp PROPERTIES
    COMPILE_OPTIONS "-fvisibility=hidden;-fvisibility-inlines-hidden")
add_executable(pipeline-archive-test EXCLUDE_FROM_ALL ../tests/test_pipeline_archive.cpp)
target_compile_options(pipeline-archive-test PRIVATE -UNDEBUG)
target_include_directories(pipeline-archive-test PRIVATE shadps4)
target_link_libraries(pipeline-archive-test PRIVATE fmt::fmt)
add_executable(motion-history-test EXCLUDE_FROM_ALL ../tests/test_motion_history.cpp)
target_compile_options(motion-history-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(motion-history-test PRIVATE ..)
add_executable(lamp-fog-lights-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_lights.cpp)
target_compile_options(lamp-fog-lights-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-fog-lights-test PRIVATE ..)
# bbport (r80_lamp-fog-shafts): the lamp fog shafts' knob, sizes and map math (lamp_fog_shafts.h)
add_executable(lamp-fog-shafts-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_shafts.cpp)
target_compile_options(lamp-fog-shafts-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-fog-shafts-test PRIVATE ..)
# bbport (r106_lamp-fog-shaft-cap): the shafts' ray budget and planner (lamp_fog_shaft_cap.h)
add_executable(lamp-fog-shaft-cap-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_shaft_cap.cpp)
target_compile_options(lamp-fog-shaft-cap-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-fog-shaft-cap-test PRIVATE ..)
# bbport (r106c_shaft-march-cheaper): the fast march's knob, counters and a mirror of its sampling
# (lamp_fog_shaft_fast.h); also built and run by engine/build.sh --test.
add_executable(lamp-fog-shaft-fast-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_shaft_fast.cpp)
target_compile_options(lamp-fog-shaft-fast-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-fog-shaft-fast-test PRIVATE ..)
# bbport (r80b_shafts-smooth-visible): the shafts' smoothing and gain knobs and the pushed word
# (lamp_fog_shaft_smooth.h); also built and run by engine/build.sh --test.
add_executable(lamp-fog-shaft-smooth-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_shaft_smooth.cpp)
target_compile_options(lamp-fog-shaft-smooth-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-fog-shaft-smooth-test PRIVATE ..)
# bbport (r96_lamp-flicker-colour): the lamp flicker's knobs, wave, colour gains, flame test and
# tracker (lamp_flicker.h); also built and run by engine/build.sh --test.
add_executable(lamp-flicker-test EXCLUDE_FROM_ALL ../tests/test_lamp_flicker.cpp)
target_compile_options(lamp-flicker-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-flicker-test PRIVATE ..)
# bbport (r123_lamp-colour-temperature): the lamp colour temperature's knobs, blackbody colours, kinds,
# tint and its place in the lamp flicker's tracker (lamp_temperature.h); also built and run by
# engine/build.sh --test.
add_executable(lamp-temperature-test EXCLUDE_FROM_ALL ../tests/test_lamp_temperature.cpp)
target_compile_options(lamp-temperature-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-temperature-test PRIVATE ..)
# bbport (r89_wind-foliage-sway): the plant sway's knob, word, layout, camera math and rule
# (shim/bbport_wind_sway.h); also built and run by engine/build.sh --test.
add_executable(wind-sway-test EXCLUDE_FROM_ALL ../tests/test_wind_sway.cpp)
target_compile_options(wind-sway-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-sway-test PRIVATE ..)
# bbport (r89i_twigs-colour-pass): the colour-pass census and its knobs (shim/bbport_wind_census.h); also built and
# run by engine/build.sh --test.
add_executable(wind-census-test EXCLUDE_FROM_ALL ../tests/test_wind_census.cpp)
target_compile_options(wind-census-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-census-test PRIVATE ..)
# bbport (r89j_twigs-pick-trees): the tree shape rule, the pick's points, patch and winner rule (shim/bbport_wind_trees.h);
# also built and run by engine/build.sh --test.
add_executable(wind-trees-test EXCLUDE_FROM_ALL ../tests/test_wind_trees.cpp)
target_compile_options(wind-trees-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-trees-test PRIVATE ..)
# bbport (r112_wind-more-things): the hanging things' knob, layout, push, rule (HangDisplace), book,
# measure and log texts (shim/bbport_wind_hang.h); also built and run by engine/build.sh --test.
add_executable(wind-hang-test EXCLUDE_FROM_ALL ../tests/test_wind_hang.cpp)
target_compile_options(wind-hang-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-hang-test PRIVATE ..)
# bbport (r112d_hang-still-test): the palettes' content test (shim/bbport_wind_hang_still.h); also
# built and run by engine/build.sh --test.
add_executable(wind-hang-still-test EXCLUDE_FROM_ALL ../tests/test_wind_hang_still.cpp)
target_compile_options(wind-hang-still-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-hang-still-test PRIVATE ..)
# bbport (r112h_hang-not-the-hunter): who may hang (shim/bbport_wind_hang_actors.h); also built and run
# by engine/build.sh --test.
add_executable(wind-hang-actors-test EXCLUDE_FROM_ALL ../tests/test_wind_hang_actors.cpp)
target_compile_options(wind-hang-actors-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-hang-actors-test PRIVATE ..)
# bbport (r112i_hang-find-lanterns): static hanging things and the survey (shim/bbport_wind_hang_find.h); also
# built and run by engine/build.sh --test.
add_executable(wind-hang-find-test EXCLUDE_FROM_ALL ../tests/test_wind_hang_find.cpp)
target_compile_options(wind-hang-find-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-hang-find-test PRIVATE ..)
# bbport (r112p_hang-gpu-palette-lanterns): skinned hanging things the CPU palette test refuses, judged by the GPU box
# (shim/bbport_wind_hang_gpu.h); also built and run by engine/build.sh --test.
add_executable(wind-hang-gpu-test EXCLUDE_FROM_ALL ../tests/test_wind_hang_gpu.cpp)
target_compile_options(wind-hang-gpu-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-hang-gpu-test PRIVATE ..)
# bbport (r112q_hang-bracket-route): the route lines, BB_WIND_HANG_FORCE, BB_WIND_HANG_BOX_RETRY and the judge's DueSoft
# (shim/bbport_wind_hang_route.h); also built and run by engine/build.sh --test.
add_executable(wind-hang-route-test EXCLUDE_FROM_ALL ../tests/test_wind_hang_route.cpp)
target_compile_options(wind-hang-route-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-hang-route-test PRIVATE ..)
# bbport (r112v_lantern-hangs): the lantern rule's plan, weight, keys and guard (shim/bbport_wind_lantern.h); also built and run by
# engine/build.sh --test.
add_executable(wind-lantern-test EXCLUDE_FROM_ALL ../tests/test_wind_lantern.cpp)
target_compile_options(wind-lantern-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-lantern-test PRIVATE ..)
# bbport (r82_wind-stage1): the shared wind state and the CPU copy of the fog noise and march step
# (shim/bbport_wind.h; wind-noise-test checks the GLSL copy); also built and run by
# engine/build.sh --test.
add_executable(wind-test EXCLUDE_FROM_ALL ../tests/test_wind.cpp)
target_compile_options(wind-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-test PRIVATE ..)
# bbport (r117_wind-shelter): the wind shelter field's knob, layout, reader and model
# (shim/bbport_wind_shelter.h); also built and run by engine/build.sh --test.
add_executable(wind-shelter-test EXCLUDE_FROM_ALL ../tests/test_wind_shelter.cpp)
target_compile_options(wind-shelter-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-shelter-test PRIVATE ..)
# bbport (r97g_shelter-haze-sparks): the wind the haze and the sparks feel in sheltered air
# (shim/bbport_wind_felt_shelter.h); also built and run by engine/build.sh --test.
add_executable(wind-felt-shelter-test EXCLUDE_FROM_ALL ../tests/test_wind_felt_shelter.cpp)
target_compile_options(wind-felt-shelter-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-felt-shelter-test PRIVATE ..)
# bbport (r122_game-wind-drive): the game-wind cut's knob, level, bit and counters (shim/bbport_wind_game.h);
# also built and run by engine/build.sh --test.
add_executable(wind-game-test EXCLUDE_FROM_ALL ../tests/test_wind_game.cpp)
target_compile_options(wind-game-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-game-test PRIVATE ..)
# bbport (r122b_game-particles-follow-wind): the game-particle lean's knob text, lean, word, counters and the patch of
# the vertex module (shim/bbport_wind_game_particles.h); also built and run by engine/build.sh --test.
add_executable(wind-game-particles-test EXCLUDE_FROM_ALL ../tests/test_wind_game_particles.cpp)
target_compile_options(wind-game-particles-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-game-particles-test PRIVATE ..)
# bbport (r94_fog-noise): the sun fog noise's knobs, shaping and drift (volumetric_fog_noise.h);
# also built and run by engine/build.sh --test
add_executable(volumetric-fog-noise-test EXCLUDE_FROM_ALL ../tests/test_volumetric_fog_noise.cpp)
target_compile_options(volumetric-fog-noise-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(volumetric-fog-noise-test PRIVATE ..)
# bbport (r95_halation): the halation's knobs and push words (halation_params.h); also built and
# run by engine/build.sh --test.
add_executable(halation-test EXCLUDE_FROM_ALL ../tests/test_halation.cpp)
target_compile_options(halation-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(halation-test PRIVATE ..)
# bbport (r100_blood-sheen, r100d_blood-sheen-gbuffer): the blood sheen's knobs, draw key, albedo
# rule and wet film (blood_sheen.h);
# also built and run by engine/build.sh --test.
add_executable(blood-sheen-test EXCLUDE_FROM_ALL ../tests/test_blood_sheen.cpp)
target_compile_options(blood-sheen-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(blood-sheen-test PRIVATE ..)
# bbport (r105_cloud-shadows): the cloud shadows' knobs, direction rule, drift and push words
# (cloud_shadow_params.h); also built and run by engine/build.sh --test.
add_executable(cloud-shadows-test EXCLUDE_FROM_ALL ../tests/test_cloud_shadows.cpp)
target_compile_options(cloud-shadows-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(cloud-shadows-test PRIVATE ..)
# bbport (r119_volumetric-clouds): the cloud layer's knobs, slab, cloud field and Params block
# (cloud_layer_params.h); also built and run by engine/build.sh --test.
add_executable(cloud-layer-test EXCLUDE_FROM_ALL ../tests/test_cloud_layer.cpp)
target_compile_options(cloud-layer-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(cloud-layer-test PRIVATE ..)
# bbport (r51_volumetric-leak): the volumetric march's cascades and knob (volumetric_occlusion.h)
add_executable(volumetric-occlusion-test EXCLUDE_FROM_ALL ../tests/test_volumetric_occlusion.cpp)
target_compile_options(volumetric-occlusion-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(volumetric-occlusion-test PRIVATE ..)
# bbport (r81_sun-fog-no-rt): the area light gate's knob and weights (volumetric_area_gate.h)
add_executable(volumetric-area-gate-test EXCLUDE_FROM_ALL ../tests/test_volumetric_area_gate.cpp)
target_compile_options(volumetric-area-gate-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(volumetric-area-gate-test PRIVATE ..)
# bbport (r115b_sun-fog-out-of-sewer-library): the roof rule's knob text, curve and counts (volumetric_roof.h)
add_executable(volumetric-roof-test EXCLUDE_FROM_ALL ../tests/test_volumetric_roof.cpp)
target_compile_options(volumetric-roof-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(volumetric-roof-test PRIVATE ..)
# bbport (r98_ambient-particles): the ambient motes' knobs, drift and push block
# (ambient_particles.h); also built and run by engine/build.sh --test.
add_executable(ambient-particles-test EXCLUDE_FROM_ALL ../tests/test_ambient_particles.cpp)
target_compile_options(ambient-particles-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(ambient-particles-test PRIVATE ..)
# bbport (r41_lamp-shadows): the tuning of the ray traced lamp shadow pass (lamp_shadow_tune.h)
add_executable(lamp-shadow-tune-test EXCLUDE_FROM_ALL ../tests/test_lamp_shadow_tune.cpp)
target_compile_options(lamp-shadow-tune-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-shadow-tune-test PRIVATE ..)
# bbport (r45_drawn-look): the drawn look's passes on a synthetic scene (the strokes stay on
# their surfaces under the jitter and a camera move, the colours stay) or on a picture; plain
# Vulkan, no bbgpu.
add_executable(drawn-look-test EXCLUDE_FROM_ALL ../tests/test_drawn_look.cpp)
target_include_directories(drawn-look-test PRIVATE ${SHADER_INCLUDE} shadps4)
target_compile_options(drawn-look-test PRIVATE -UNDEBUG -Wall -Wextra -Werror -Wno-missing-field-initializers)
target_link_libraries(drawn-look-test PRIVATE Vulkan::Vulkan)
add_dependencies(drawn-look-test host_shaders)
# bbport (r55_drawn-look-lines): the drawn look's rules that need no GPU (drawn_look_params.h:
# which passes a frame records, the ink pass's words, BB_DRAWN_LOOK_LINE); also in build.sh --test.
add_executable(drawn-look-rules-test EXCLUDE_FROM_ALL ../tests/test_drawn_look_rules.cpp)
target_compile_options(drawn-look-rules-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(drawn-look-rules-test PRIVATE ..)
# bbport (r43_copy-turns): the turns of the ray tracing scene's shared copies (rt_copy_turns.h)
add_executable(rt-copy-turns-test EXCLUDE_FROM_ALL ../tests/test_rt_copy_turns.cpp)
target_compile_options(rt-copy-turns-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rt-copy-turns-test PRIVATE ..)
# bbport (r46_lamp-cards): which cut-out cards lamp rays leave out (rt_lamp_cards.h)
add_executable(rt-lamp-cards-test EXCLUDE_FROM_ALL ../tests/test_rt_lamp_cards.cpp)
target_compile_options(rt-lamp-cards-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rt-lamp-cards-test PRIVATE ..)
# bbport (r47_still-check): whether a caster held for still has moved (rt_still_check.h)
add_executable(rt-still-check-test EXCLUDE_FROM_ALL ../tests/test_rt_still_check.cpp)
target_compile_options(rt-still-check-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rt-still-check-test PRIVATE ..)
# bbport (r83_glass-water-stage1): the window panes' knob, masks and key (rt_glass.h)
add_executable(rt-glass-test EXCLUDE_FROM_ALL ../tests/test_rt_glass.cpp)
target_compile_options(rt-glass-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rt-glass-test PRIVATE ..)
# bbport (r97_heat-haze): the heat haze's knobs, flames, columns and atlas (heat_haze.h); also
# built and run by engine/build.sh --test.
add_executable(heat-haze-test EXCLUDE_FROM_ALL ../tests/test_heat_haze.cpp)
target_compile_options(heat-haze-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(heat-haze-test PRIVATE ..)
# bbport (r107_caustics): the water caustics' knob, push words, drift and pattern
# (caustics_params.h); also built and run by engine/build.sh --test.
add_executable(caustics-test EXCLUDE_FROM_ALL ../tests/test_caustics.cpp)
target_compile_options(caustics-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(caustics-test PRIVATE ..)
# bbport (r86b_glass-visible): the glass glint's knobs, lamps, gate and numbers (glass_glint.h);
# also built and run by engine/build.sh --test.
add_executable(glass-glint-test EXCLUDE_FROM_ALL ../tests/test_glass_glint.cpp)
target_compile_options(glass-glint-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(glass-glint-test PRIVATE ..)
# bbport (r129a_glass-registry): the glass registry's table text, lookup and view knob (glass_registry.h); also built and run
# by engine/build.sh --test.
# bbport (r130g_glass-light-forward): the forward glass light's steady rule and shared numbers (glass_light_forward.h); also
# built and run by engine/build.sh --test.
add_executable(glass-light-forward-test EXCLUDE_FROM_ALL ../tests/test_glass_light_forward.cpp)
target_compile_options(glass-light-forward-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(glass-light-forward-test PRIVATE ..)
# bbport (r131a_foliage-translucency): the foliage translucency's knob rules, leaf pass and card ray rule (foliage_translucency.h); also built and run by
# engine/build.sh --test.
add_executable(foliage-translucency-test EXCLUDE_FROM_ALL ../tests/test_foliage_translucency.cpp)
target_compile_options(foliage-translucency-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(foliage-translucency-test PRIVATE ..)
add_executable(glass-registry-test EXCLUDE_FROM_ALL ../tests/test_glass_registry.cpp)
target_compile_options(glass-registry-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(glass-registry-test PRIVATE ..)
# bbport (r130c_glass-lamp-light): lamp light through glass: tint words, strengths, custom index, the s token (glass_light.h); also
# built and run by engine/build.sh --test.
add_executable(glass-light-test EXCLUDE_FROM_ALL ../tests/test_glass_light.cpp)
target_compile_options(glass-light-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(glass-light-test PRIVATE ..)
# bbport (r54_leaf-stage2): the card UVs' pure parts (renderer_vulkan/rt_card_uv.h)
add_executable(rt-card-uv-test EXCLUDE_FROM_ALL ../tests/test_rt_card_uv.cpp)
target_compile_options(rt-card-uv-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rt-card-uv-test PRIVATE ..)
# bbport (r62_leaf-stage3): the card alpha layers' pure parts (renderer_vulkan/rt_card_layers.h)
add_executable(rt-card-layers-test EXCLUDE_FROM_ALL ../tests/test_rt_card_layers.cpp)
target_compile_options(rt-card-layers-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rt-card-layers-test PRIVATE ..)
foreach(effect_test
        "motion-blur-shader-test;test_motion_blur.cpp"
        "directional-shadow-test;test_directional_shadows.cpp"
        "rt-shadow-test;test_rt_shadows.cpp"
        "point-volumetric-test;test_point_volumetric.cpp"
        "wind-noise-test;test_wind_noise.cpp"
        "volumetric-tint-test;test_volumetric_tint.cpp"
        "effect-pipelines-test;test_effect_pipelines.cpp")
    list(GET effect_test 0 effect_test_name)
    list(GET effect_test 1 effect_test_source)
    add_executable(${effect_test_name} EXCLUDE_FROM_ALL ../tests/${effect_test_source})
    target_include_directories(${effect_test_name} PRIVATE ${SHADER_INCLUDE})
    target_compile_options(${effect_test_name} PRIVATE -UNDEBUG -Wall -Werror)
    target_link_libraries(${effect_test_name} PRIVATE Vulkan::Vulkan)
    add_dependencies(${effect_test_name} host_shaders)
endforeach()
# bbport (r41_lamp-shadows): the lab runs the lamp pass with lamp_shadow_tune.h's words
target_include_directories(rt-shadow-test PRIVATE ..)
# bbport (r82_wind-stage1): wind-noise-test compares the GPU with gpu/shim/bbport_wind.h
target_include_directories(wind-noise-test PRIVATE ..)
add_executable(native-local-shadows-test EXCLUDE_FROM_ALL ../tests/test_native_local_shadows.cpp
    shim/engine/graphics.cpp shim/engine/native_sss.cpp shim/engine/engine_hooks.cpp shim/bbport_settings.cpp shim/bbport_menu_i18n.cpp)
target_include_directories(native-local-shadows-test PRIVATE shim)
target_compile_options(native-local-shadows-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
add_executable(foliage-mask-test EXCLUDE_FROM_ALL ../tests/test_foliage_mask.cpp)
target_include_directories(foliage-mask-test PRIVATE shadps4)
target_compile_options(foliage-mask-test PRIVATE -UNDEBUG)
add_executable(occlusion-test EXCLUDE_FROM_ALL ../tests/test_occlusion.cpp)
target_compile_options(occlusion-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(occlusion-test PRIVATE ..)
# Pipeline compiles off the frame path (docs/pipeline_compiles.md); the draw pipe's waits run
# with real threads (bbgpu: the platform and thread helpers).
add_executable(pipeline-compile-test EXCLUDE_FROM_ALL ../tests/test_pipeline_compile.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_compile_options(pipeline-compile-test PRIVATE -UNDEBUG)
target_include_directories(pipeline-compile-test PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(pipeline-compile-test PRIVATE bbgpu)
if (WIN32)
    target_link_libraries(pipeline-compile-test PRIVATE winmm ws2_32 psapi onecore)
endif()
# The shader lab (tests/shader_lab.cpp): shader captures compiled offline, without the game.
add_executable(bb-shader-lab EXCLUDE_FROM_ALL ../tests/shader_lab.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_include_directories(bb-shader-lab PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(bb-shader-lab PRIVATE bbgpu miniz::miniz)
if (WIN32)
    target_link_libraries(bb-shader-lab PRIVATE winmm ws2_32 psapi onecore)
endif()
add_executable(motion-shader-test EXCLUDE_FROM_ALL ../tests/test_motion_shaders.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_compile_options(motion-shader-test PRIVATE -UNDEBUG)
target_include_directories(motion-shader-test PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(motion-shader-test PRIVATE bbgpu)
if (WIN32)
    target_link_libraries(motion-shader-test PRIVATE winmm ws2_32 psapi onecore)
endif()
# bbport (r50_leaf-stage1): the cut-out analysis of pixel shaders (cutout_analysis.h).
add_executable(rt-card-alpha-test EXCLUDE_FROM_ALL ../tests/test_rt_card_alpha.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_compile_options(rt-card-alpha-test PRIVATE -UNDEBUG)
target_include_directories(rt-card-alpha-test PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(rt-card-alpha-test PRIVATE bbgpu)
if (WIN32)
    target_link_libraries(rt-card-alpha-test PRIVATE winmm ws2_32 psapi onecore)
endif()
add_executable(ui-composition-test EXCLUDE_FROM_ALL ../tests/test_ui_composition.cpp)
target_compile_options(ui-composition-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(ui-composition-test PRIVATE ..)
add_executable(camera-orbit-test EXCLUDE_FROM_ALL ../tests/test_camera_orbit.cpp)
target_compile_options(camera-orbit-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(camera-orbit-test PRIVATE ..)
add_executable(camera-path-test EXCLUDE_FROM_ALL ../tests/test_camera_path.cpp)
target_compile_options(camera-path-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(camera-path-test PRIVATE ..)
add_executable(settings-test EXCLUDE_FROM_ALL ../tests/test_settings.cpp shim/bbport_settings.cpp
    shim/bbport_menu_i18n.cpp)
target_compile_options(settings-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(settings-test PRIVATE .. shim)
# bbport: GTAO on synthetic scenes (Regular, High and its denoiser); plain Vulkan, no bbgpu.
add_executable(gtao-test EXCLUDE_FROM_ALL ../tests/test_gtao.cpp)
target_include_directories(gtao-test PRIVATE ${SHADER_INCLUDE})
target_compile_options(gtao-test PRIVATE -UNDEBUG -Wall -Wextra -Werror -Wno-missing-field-initializers)
target_link_libraries(gtao-test PRIVATE Vulkan::Vulkan)
add_dependencies(gtao-test host_shaders)

add_executable(scene-resolution-test EXCLUDE_FROM_ALL ../tests/test_scene_resolution.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_include_directories(scene-resolution-test PRIVATE shim shadps4 third_party/gcn/include)
# The test's Vulkan-Hpp inline methods have a different set of platform extensions
# from vk_platform.cpp. Keep them local and use an explicit dispatcher in the test.
target_compile_options(scene-resolution-test PRIVATE -UNDEBUG -fPIC)
set_source_files_properties(../tests/test_scene_resolution.cpp PROPERTIES
    COMPILE_OPTIONS "-fvisibility=hidden;-fvisibility-inlines-hidden")
target_link_libraries(scene-resolution-test PRIVATE bbgpu)
if (WIN32)
    target_link_libraries(scene-resolution-test PRIVATE winmm ws2_32 psapi onecore)
endif()
add_executable(taa-shader-test EXCLUDE_FROM_ALL ../tests/test_taa_shader.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_include_directories(taa-shader-test PRIVATE shim shadps4 ${SHADER_INCLUDE} third_party/gcn/include)
target_compile_options(taa-shader-test PRIVATE -UNDEBUG -fPIC)
set_source_files_properties(../tests/test_taa_shader.cpp PROPERTIES
    COMPILE_OPTIONS "-fvisibility=hidden;-fvisibility-inlines-hidden")
target_link_libraries(taa-shader-test PRIVATE bbgpu)
if (WIN32)
    target_link_libraries(taa-shader-test PRIVATE winmm ws2_32 psapi onecore)
endif()
add_dependencies(taa-shader-test host_shaders)

add_executable(camera-motion-test EXCLUDE_FROM_ALL ../tests/test_camera_motion.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_include_directories(camera-motion-test PRIVATE shim shadps4 ${SHADER_INCLUDE} third_party/gcn/include)
target_compile_options(camera-motion-test PRIVATE -UNDEBUG -fPIC)
target_link_libraries(camera-motion-test PRIVATE bbgpu)
if (WIN32)
    target_link_libraries(camera-motion-test PRIVATE winmm ws2_32 psapi onecore)
endif()
add_dependencies(camera-motion-test host_shaders)

# bbport: indirect_clamp.comp as Rasterizer::ClampDispatchArgs records it, then an indirect
# dispatch from its output (run it under the validation layer); plain Vulkan, no bbgpu.
add_executable(indirect-clamp-test EXCLUDE_FROM_ALL ../tests/test_indirect_clamp.cpp)
target_include_directories(indirect-clamp-test PRIVATE ${SHADER_INCLUDE})
target_compile_options(indirect-clamp-test PRIVATE -UNDEBUG -Wall -Werror)
target_link_libraries(indirect-clamp-test PRIVATE Vulkan::Vulkan)
add_dependencies(indirect-clamp-test host_shaders)
# bbport: native HDR output's shaders on a synthetic frame (docs/hdr.md); plain Vulkan, no bbgpu.
add_executable(hdr-native-shader-test EXCLUDE_FROM_ALL ../tests/test_hdr_native.cpp)
target_include_directories(hdr-native-shader-test PRIVATE ${SHADER_INCLUDE})
target_compile_options(hdr-native-shader-test PRIVATE -UNDEBUG -Wall -Werror)
target_link_libraries(hdr-native-shader-test PRIVATE Vulkan::Vulkan)
add_dependencies(hdr-native-shader-test host_shaders)
# The composite tone curve extension on the GPU (docs/hdr-scene-path.md): the ramp modules of
# bb-shader-lab --ramp-modules, the game's curve against the extended one.
add_executable(tone-curve-shader-test EXCLUDE_FROM_ALL ../tests/test_tone_curve.cpp)
target_include_directories(tone-curve-shader-test PRIVATE ${SHADER_INCLUDE})
target_compile_options(tone-curve-shader-test PRIVATE -UNDEBUG -Wall -Werror)
target_link_libraries(tone-curve-shader-test PRIVATE Vulkan::Vulkan)
add_dependencies(tone-curve-shader-test host_shaders)

# bbport: FSR 4 benchmark outside the game (tools/fsr4_bench.cpp): ninja -C out/gpu fsr4-bench.
add_executable(upscaler-support-test EXCLUDE_FROM_ALL ../tests/test_upscaler_support.cpp
    shim/bbport_settings.cpp shim/bbport_menu_i18n.cpp)
target_include_directories(upscaler-support-test PRIVATE shim)
target_compile_options(upscaler-support-test PRIVATE -UNDEBUG)

add_executable(fsr4-bench EXCLUDE_FROM_ALL tools/fsr4_bench.cpp
    shadps4/video_core/renderer_vulkan/fsr411/fsr411.cpp)
target_include_directories(fsr4-bench PRIVATE shadps4/video_core/renderer_vulkan/fsr411)
target_link_libraries(fsr4-bench PRIVATE ffx-vulkan::fsr4-v07-vulkan ffx-vulkan::fsr4-v07-assets Vulkan::Vulkan)

# bbport (r111_footprints): the footprints' knobs, walk, coat, fade and screen boxes
# (footprints.h); also built and run by engine/build.sh --test.
add_executable(footprints-test EXCLUDE_FROM_ALL ../tests/test_footprints.cpp)
target_compile_options(footprints-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(footprints-test PRIVATE ..)
# bbport (r111b_footprints-pickup): the blood rule (blood_albedo.h); also built and run by
# engine/build.sh --test.
add_executable(blood-albedo-test EXCLUDE_FROM_ALL ../tests/test_blood_albedo.cpp)
target_compile_options(blood-albedo-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(blood-albedo-test PRIVATE ..)
add_executable(engine-hooks-test EXCLUDE_FROM_ALL ../tests/test_engine_hooks.cpp shim/engine/engine_hooks.cpp)
target_compile_options(engine-hooks-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(engine-hooks-test PRIVATE ..)
add_executable(frame-rate-test EXCLUDE_FROM_ALL ../tests/test_frame_rate.cpp shim/engine/engine_hooks.cpp)
target_compile_options(frame-rate-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(frame-rate-test PRIVATE .. shim shim/engine)
# Local game-derived native menu assets. No game data is embedded in this tool.
find_package(ZLIB REQUIRED)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    ${CMAKE_CURRENT_SOURCE_DIR}/../tools/engine/pc_option_messages.tsv)
file(READ ${CMAKE_CURRENT_SOURCE_DIR}/../tools/engine/pc_option_messages.tsv BB_ENGINE_MESSAGES)
file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/include/pc_option_messages.inc "R\"tsv(${BB_ENGINE_MESSAGES})tsv\"\n")
set(BB_MENU_ASSETS ../tools/engine/menu_assets.cpp ../tools/engine/esd.cpp ../tools/engine/rebirth_script.cpp
    ../tools/engine/sha256.cpp)
add_executable(bb-engine-assets ../tools/engine/menu_assets_main.cpp ${BB_MENU_ASSETS})
target_include_directories(bb-engine-assets PRIVATE ${CMAKE_CURRENT_BINARY_DIR}/include)
target_link_libraries(bb-engine-assets PRIVATE ZLIB::ZLIB)
if (WIN32)
    target_link_libraries(bb-engine-assets PRIVATE shell32)
endif()
add_executable(bb-ui-4k ../tools/engine/ui_4k.cpp shim/hud_gauge.cpp)
target_include_directories(bb-ui-4k PRIVATE shim)
target_link_libraries(bb-ui-4k PRIVATE ZLIB::ZLIB PkgConfig::XXHASH)
if (WIN32)
    target_link_libraries(bb-ui-4k PRIVATE shell32)
endif()
add_executable(menu-assets-test EXCLUDE_FROM_ALL ../tests/test_menu_assets.cpp ${BB_MENU_ASSETS})
target_include_directories(menu-assets-test PRIVATE ${CMAKE_CURRENT_BINARY_DIR}/include)
target_compile_options(menu-assets-test PRIVATE -UNDEBUG -Wall -Wextra)
target_link_libraries(menu-assets-test PRIVATE ZLIB::ZLIB)
add_executable(option-rows-test EXCLUDE_FROM_ALL ../tests/test_option_rows.cpp shim/engine/option_rows.cpp)
target_compile_options(option-rows-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(option-rows-test PRIVATE ..)
add_executable(engine-menu-memory-test EXCLUDE_FROM_ALL ../tests/test_engine_menu_memory.cpp shim/engine/menu_memory.cpp)
target_compile_options(engine-menu-memory-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(engine-menu-memory-test PRIVATE ..)
add_executable(shared-progress-test EXCLUDE_FROM_ALL ../tests/test_shared_progress.cpp)
target_compile_options(shared-progress-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(shared-progress-test PRIVATE ..)
add_executable(party-death-test EXCLUDE_FROM_ALL ../tests/test_party_death.cpp)
target_compile_options(party-death-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(party-death-test PRIVATE ..)
add_executable(anti-lag-pacer-test EXCLUDE_FROM_ALL ../tests/test_anti_lag_pacer.cpp)
target_compile_options(anti-lag-pacer-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(anti-lag-pacer-test PRIVATE .)
add_executable(world-copy-test EXCLUDE_FROM_ALL ../tests/test_world_copy.cpp)
target_compile_options(world-copy-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(world-copy-test PRIVATE ..)
add_executable(kept-travel-test EXCLUDE_FROM_ALL ../tests/test_kept_travel.cpp)
target_compile_options(kept-travel-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(kept-travel-test PRIVATE ..)
add_executable(rebirth-cost-test EXCLUDE_FROM_ALL ../tests/test_rebirth_cost.cpp)
target_compile_options(rebirth-cost-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rebirth-cost-test PRIVATE ..)
add_executable(pc-input-test EXCLUDE_FROM_ALL ../tests/test_pc_input.cpp shim/input/bindings.cpp)
target_include_directories(pc-input-test PRIVATE shim)
target_link_libraries(pc-input-test PRIVATE PkgConfig::SDL3)
target_compile_options(pc-input-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
add_executable(widescreen-test EXCLUDE_FROM_ALL ../tests/test_widescreen.cpp
    shim/engine/widescreen.cpp shim/engine/camera.cpp shim/engine/engine_hooks.cpp shim/bbport_settings.cpp
    shim/bbport_menu_i18n.cpp)
target_include_directories(widescreen-test PRIVATE shim)
target_compile_options(widescreen-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
