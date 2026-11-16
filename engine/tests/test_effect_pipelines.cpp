// SPDX-License-Identifier: GPL-3.0-or-later
#include <array>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <span>
#include <vector>
#define VULKAN_HPP_NO_CONSTRUCTORS
#define VULKAN_HPP_NO_EXCEPTIONS
#define VULKAN_HPP_DISPATCH_LOADER_DYNAMIC 1
#include <vulkan/vulkan.hpp>
#include "video_core/host_shaders/bloom_downsample_frag.h"
#include "video_core/host_shaders/froyok_bloom_downsample_comp.h"
#include "video_core/host_shaders/froyok_bloom_first_comp.h"
#include "video_core/host_shaders/froyok_bloom_upsample_comp.h"
#include "video_core/host_shaders/footprints_comp.h" // bbport (r111_footprints)
#include "video_core/host_shaders/halation_comp.h" // bbport (r95_halation)
#include "video_core/host_shaders/blood_sheen_edit_comp.h"     // bbport (r100_blood-sheen)
#include "video_core/host_shaders/blood_sheen_mark_comp.h"     // bbport (r100d_blood-sheen-gbuffer)
#include "video_core/host_shaders/blood_sheen_show_comp.h"     // bbport (r100d_blood-sheen-gbuffer)
#include "video_core/host_shaders/blood_sheen_snapshot_comp.h" // bbport (r100_blood-sheen)
#include "video_core/host_shaders/caustics_comp.h" // bbport (r107_caustics)
#include "video_core/host_shaders/contact_shadow_comp.h"
#include "video_core/host_shaders/cloud_shadow_comp.h"      // bbport (r105_cloud-shadows)
#include "video_core/host_shaders/cloud_shadow_gate_comp.h" // bbport (r105_cloud-shadows)
#include "video_core/host_shaders/cloud_layer_composite_comp.h" // bbport (r119_volumetric-clouds)
#include "video_core/host_shaders/cloud_layer_march_comp.h"     // bbport (r119_volumetric-clouds)
#include "video_core/host_shaders/gtao_frag.h"
#include "video_core/host_shaders/native_motion_blur_frag.h"
#include "video_core/host_shaders/paint_key_comp.h"
#include "video_core/host_shaders/paint_key_last_comp.h"
#include "video_core/host_shaders/paint_lock_comp.h"
#include "video_core/host_shaders/paint_lock_down_comp.h"
#include "video_core/host_shaders/paint_lock_first_comp.h"
#include "video_core/host_shaders/paint_mips_comp.h"
#include "video_core/host_shaders/paint_prep_comp.h"
#include "video_core/host_shaders/paint_stats_comp.h"
#include "video_core/host_shaders/paint_strokes_comp.h"
#include "video_core/host_shaders/heat_haze_comp.h" // bbport (r97_heat-haze)
#include "video_core/host_shaders/heat_haze_find_comp.h" // bbport (r97f_haze-per-flame)
#include "video_core/host_shaders/point_shadow_comp.h"
#include "video_core/host_shaders/point_volumetric_comp.h"
// bbport (r80_lamp-fog-shafts): the lamp fog march's builds that read the shadow maps
#include "video_core/host_shaders/point_volumetric_shafts_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_view_comp.h"
// bbport (r88_wind-lamp-fog): the lamp fog's BB_WIND=1 builds
#include "video_core/host_shaders/point_volumetric_wind_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_wind_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_view_wind_comp.h"
#include "video_core/host_shaders/ssgi_composite_comp.h"
#include "video_core/host_shaders/ssgi_denoise_comp.h"
#include "video_core/host_shaders/ssgi_gather_comp.h"
#include "video_core/host_shaders/ssgi_prep_comp.h"
#include "video_core/host_shaders/ssr_frag.h"
#include "video_core/host_shaders/ssr_temporal_copy_comp.h"
#include "video_core/host_shaders/ssr_temporal_resolve_comp.h"
#include "video_core/host_shaders/ssr_trace_comp.h"
#include "video_core/host_shaders/volumetric_light_composite_comp.h"
#include "video_core/host_shaders/volumetric_light_filter_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_comp.h"
// bbport (r76_sun-fog-outdoors): the march's builds that read the ray traced sun gate (r51b), and
// the gate view's march and composite builds
#include "video_core/host_shaders/volumetric_light_integrate_gate_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_gate_view_comp.h"
#include "video_core/host_shaders/volumetric_light_composite_gate_view_comp.h"
// bbport (r82_wind-stage1): the BB_WIND=1 builds
#include "video_core/host_shaders/volumetric_light_integrate_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_gate_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_wind_view_comp.h"
// bbport (r94_fog-noise): the BB_FOG_NOISE builds
#include "video_core/host_shaders/volumetric_light_integrate_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_gate_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_area_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_area_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_gate_area_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_area_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_tint_comp.h"
// bbport (r81_sun-fog-no-rt): the march's AREA builds and the area light gate's two passes
#include "video_core/host_shaders/volumetric_area_gate_apply_comp.h"
#include "video_core/host_shaders/volumetric_area_gate_camera_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_area_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_area_comp.h"
// bbport (r85_area-with-rt-gate): the march's AREA+GATE builds
#include "video_core/host_shaders/volumetric_light_integrate_gate_area_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_area_comp.h"
// bbport (r115_sun-fog-indoors): the march's DUAL builds
#include "video_core/host_shaders/volumetric_light_integrate_gate_area_dual_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_area_dual_comp.h"

VULKAN_HPP_DEFAULT_DISPATCH_LOADER_DYNAMIC_STORAGE

using u32 = uint32_t;

namespace {
u32 messages = 0;

VKAPI_ATTR VkBool32 VKAPI_CALL Message(VkDebugUtilsMessageSeverityFlagBitsEXT severity,
                                       VkDebugUtilsMessageTypeFlagsEXT,
                                       const VkDebugUtilsMessengerCallbackDataEXT* data, void*) {
    if (severity >= VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT) {
        ++messages;
        std::printf("%s\n", data->pMessage);
    }
    return VK_FALSE;
}

struct Pass {
    const char* name;
    std::span<const u32> code;
    std::vector<vk::DescriptorType> types;
    u32 push;
};
}

int main() {
    static vk::detail::DynamicLoader loader;
    VULKAN_HPP_DEFAULT_DISPATCHER.init(
        loader.getProcAddress<PFN_vkGetInstanceProcAddr>("vkGetInstanceProcAddr"));
    const vk::ApplicationInfo app{.pApplicationName = "effect-pipelines-test",
                                  .apiVersion = VK_API_VERSION_1_3};
    const char* debug_utils = VK_EXT_DEBUG_UTILS_EXTENSION_NAME;
    auto instance = vk::createInstanceUnique({.pApplicationInfo = &app,
                                              .enabledExtensionCount = 1,
                                              .ppEnabledExtensionNames = &debug_utils})
                        .value;
    VULKAN_HPP_DEFAULT_DISPATCHER.init(*instance);
    auto messenger =
        instance
            ->createDebugUtilsMessengerEXTUnique(
                {.messageSeverity = vk::DebugUtilsMessageSeverityFlagBitsEXT::eWarning |
                                    vk::DebugUtilsMessageSeverityFlagBitsEXT::eError,
                 .messageType = vk::DebugUtilsMessageTypeFlagBitsEXT::eValidation |
                                vk::DebugUtilsMessageTypeFlagBitsEXT::eGeneral,
                 .pfnUserCallback =
                     reinterpret_cast<vk::PFN_DebugUtilsMessengerCallbackEXT>(Message)})
            .value;
    const auto gpus = instance->enumeratePhysicalDevices().value;
    assert(!gpus.empty());
    const auto physical = gpus[0];
    std::printf("device: %s\n", physical.getProperties().deviceName.data());
    const auto supported = physical.getFeatures();
    const float priority = 1;
    const vk::DeviceQueueCreateInfo queue{.queueFamilyIndex = 0,
                                          .queueCount = 1,
                                          .pQueuePriorities = &priority};
    const char* extension = VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME;
    const vk::PhysicalDeviceFeatures features{
        .shaderStorageImageExtendedFormats = supported.shaderStorageImageExtendedFormats};
    vk::PhysicalDeviceVulkan12Features v12{.scalarBlockLayout = true,
                                           .uniformBufferStandardLayout = true};
    auto owned = physical
                     .createDeviceUnique({.pNext = &v12,
                                          .queueCreateInfoCount = 1,
                                          .pQueueCreateInfos = &queue,
                                          .enabledExtensionCount = 1,
                                          .ppEnabledExtensionNames = &extension,
                                          .pEnabledFeatures = &features})
                     .value;
    const auto device = *owned;
    VULKAN_HPP_DEFAULT_DISPATCHER.init(device);

    using enum vk::DescriptorType;
    const std::vector<Pass> passes = {
        {"froyok downsample", FROYOK_BLOOM_DOWNSAMPLE_COMP,
         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage}, 32},
        {"froyok first downsample", FROYOK_BLOOM_FIRST_COMP,
         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage}, 32},
        {"froyok upsample", FROYOK_BLOOM_UPSAMPLE_COMP,
         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage}, 32},
        // bbport (r111_footprints): as vk_footprints.cpp makes it (FootprintRules::Push, 112 bytes)
        {"footprints",
         FOOTPRINTS_COMP,
         {eSampledImage, eStorageImage, eStorageImage, eStorageImage, eStorageBuffer,
          eStorageBuffer},
         112},
        // bbport (r95_halation): as vk_halation.cpp makes it (HalationParams::Push)
        {"halation", HALATION_COMP, {eCombinedImageSampler, eStorageImage, eStorageBuffer}, 80},
        // bbport (r100_blood-sheen): as vk_blood_sheen.cpp makes them (BloodSheenRules::Push)
        // bbport (r100d_blood-sheen-gbuffer): the G-buffer passes (32 push bytes)
        {"blood sheen snapshot",
         BLOOD_SHEEN_SNAPSHOT_COMP,
         {eSampledImage, eSampledImage, eStorageImage, eStorageImage},
         32},
        {"blood sheen mark",
         BLOOD_SHEEN_MARK_COMP,
         {eSampledImage, eSampledImage, eStorageImage, eStorageImage, eStorageBuffer},
         32},
        {"blood sheen wet ground",
         BLOOD_SHEEN_EDIT_COMP,
         {eSampledImage, eSampledImage, eStorageImage, eStorageImage, eStorageImage, eStorageImage,
          eStorageBuffer},
         32},
        {"blood sheen show", BLOOD_SHEEN_SHOW_COMP, {eStorageImage, eStorageImage}, 32},
        // bbport (r45_drawn-look): as vk_drawn_look.cpp makes them (DrawnLookParams::Params)
        {"drawn look prep", PAINT_PREP_COMP, {eSampledImage, eSampledImage, eStorageImage}, 112},
        {"drawn look stats", PAINT_STATS_COMP, {eSampledImage, eStorageImage, eStorageImage}, 112},
        {"drawn look mips",
         PAINT_MIPS_COMP,
         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage, eStorageImage},
         112},
        {"drawn look key sums", PAINT_KEY_COMP, {eSampledImage, eStorageImage}, 112},
        {"drawn look key", PAINT_KEY_LAST_COMP, {eSampledImage, eStorageImage}, 112},
        {"drawn look strokes",
         PAINT_STROKES_COMP,
         {eCombinedImageSampler, eSampledImage, eSampledImage, eSampledImage, eStorageImage,
          eCombinedImageSampler},
         112},
        {"drawn look lock means", PAINT_LOCK_FIRST_COMP, {eSampledImage, eStorageImage}, 112},
        {"drawn look lock levels",
         PAINT_LOCK_DOWN_COMP,
         {eCombinedImageSampler, eStorageImage},
         112},
        {"drawn look lock",
         PAINT_LOCK_COMP,
         {eCombinedImageSampler, eSampledImage, eSampledImage, eStorageImage,
          eCombinedImageSampler},
         112},
        // bbport (r97_heat-haze): as vk_heat_haze.cpp makes it (BbHeatHaze::Push, 96 bytes)
        {"heat haze", HEAT_HAZE_COMP,
         {eStorageImage, eStorageImage, eSampledImage, eStorageBuffer}, // r97b: the counters
         96},
        // bbport (r97f_haze-per-flame): the flame finder, as vk_heat_haze.cpp makes it (BbHeatHaze::FindPush, 48 bytes)
        {"heat haze flames", HEAT_HAZE_FIND_COMP, {eStorageImage, eStorageBuffer}, 48},
        // bbport (r107_caustics): as vk_caustics.cpp makes it (BbCaustics::Push, 128 bytes; r107b:
        // the albedo and light set targets)
        {"water caustics", CAUSTICS_COMP,
         {eStorageImage, eSampledImage, eSampledImage, eSampledImage, eStorageBuffer, eSampledImage,
          eSampledImage, eStorageBuffer}, // r107f: the world map
         128},
        {"ssgi prep", SSGI_PREP_COMP, {eSampledImage, eStorageImage, eSampledImage}, 128},
        {"ssgi gather",
         SSGI_GATHER_COMP,
         {eSampledImage, eSampledImage, eSampledImage, eStorageImage, eSampledImage},
         128},
        {"ssgi denoise", SSGI_DENOISE_COMP, {eSampledImage, eSampledImage, eStorageImage}, 128},
        {"ssgi composite",
         SSGI_COMPOSITE_COMP,
         {eSampledImage, eSampledImage, eStorageImage, eSampledImage, eSampledImage},
         128},
        {"ssr resolve",
         SSR_TEMPORAL_RESOLVE_COMP,
         {eSampledImage, eSampledImage, eSampledImage, eStorageImage},
         128},
        {"ssr copy", SSR_TEMPORAL_COPY_COMP, {eSampledImage, eStorageImage}, 128},
        {"ssr trace",
         SSR_TRACE_COMP,
         {eUniformBuffer, eCombinedImageSampler, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage},
         16},
        {"contact shadows",
         CONTACT_SHADOW_COMP,
         {eStorageBuffer, eCombinedImageSampler, eStorageImage, eCombinedImageSampler,
          eStorageBuffer},
         68},
        // bbport (r105_cloud-shadows): CloudShadow's two passes (CloudShadows::Push, 120 bytes)
        {"cloud shadows", CLOUD_SHADOW_COMP, {eStorageBuffer, eCombinedImageSampler, eStorageImage},
         120},
        {"cloud shadows gate", CLOUD_SHADOW_GATE_COMP, {eStorageBuffer, eStorageBuffer, eStorageImage},
         120},
        // bbport (r119_volumetric-clouds): CloudLayer's two passes (CloudLayerParams::Push, 16 bytes)
        {"cloud layer march", CLOUD_LAYER_MARCH_COMP,
         {eStorageImage, eStorageImage, eSampledImage, eStorageBuffer, eStorageBuffer}, 16},
        {"cloud layer composite", CLOUD_LAYER_COMPOSITE_COMP,
         {eStorageImage, eStorageImage, eSampledImage, eStorageBuffer}, 16},
        {"point shadows",
         POINT_SHADOW_COMP,
         {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage,
          eStorageImage},
         64},
        {"volumetric integrate",
         VOLUMETRIC_LIGHT_INTEGRATE_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage},
         32},
        {"volumetric repair",
         VOLUMETRIC_LIGHT_REPAIR_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage},
         32},
        // bbport (r76_sun-fog-outdoors): as VolumetricLight::GateReady and DiagReady make them: the
        // pass's own bindings, then the gate (3D) and each column's first open slice; the view's
        // march adds its image and the cells' bands, its composite the view. The gate's own two
        // builds need ray queries, which this test's device does not turn on: not built here.
        {"volumetric integrate (gate)",
         VOLUMETRIC_LIGHT_INTEGRATE_GATE_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler},
         32},
        {"volumetric repair (gate)",
         VOLUMETRIC_LIGHT_REPAIR_GATE_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
          eCombinedImageSampler},
         32},
        {"volumetric integrate (gate view)",
         VOLUMETRIC_LIGHT_INTEGRATE_GATE_VIEW_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eCombinedImageSampler},
         32},
        {"volumetric composite (gate view)",
         VOLUMETRIC_LIGHT_COMPOSITE_GATE_VIEW_COMP,
         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage, eStorageBuffer,
          eCombinedImageSampler, eCombinedImageSampler, eCombinedImageSampler},
         4},
        // bbport (r81_sun-fog-no-rt): as VolumetricLight::AreaReady makes them: the march's AREA
        // builds take the plain builds' bindings; the area light gate's camera and apply passes
        {"volumetric integrate (area gate)",
         VOLUMETRIC_LIGHT_INTEGRATE_AREA_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage},
         32},
        {"volumetric repair (area gate)",
         VOLUMETRIC_LIGHT_REPAIR_AREA_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage},
         32},
        {"volumetric area gate (camera)",
         VOLUMETRIC_AREA_GATE_CAMERA_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler},
         16},
        {"volumetric area gate (apply)",
         VOLUMETRIC_AREA_GATE_APPLY_COMP,
         {eStorageBuffer, eCombinedImageSampler, eStorageImage},
         16},
        // bbport (r85_area-with-rt-gate): as VolumetricLight::AreaGatedReady makes them: the
        // AREA+GATE builds take the GATE builds' bindings
        {"volumetric integrate (gate, area gate)",
         VOLUMETRIC_LIGHT_INTEGRATE_GATE_AREA_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler},
         32},
        {"volumetric repair (gate, area gate)",
         VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
          eCombinedImageSampler},
         32},
        // bbport (r115_sun-fog-indoors): as VolumetricLight::DualReady makes them: the AREA+GATE
        // bindings, then the gate's wider answer
        {"volumetric integrate (gate, area gate, dual)",
         VOLUMETRIC_LIGHT_INTEGRATE_GATE_AREA_DUAL_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler,
          eCombinedImageSampler},
         32},
        {"volumetric repair (gate, area gate, dual)",
         VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_DUAL_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
          eCombinedImageSampler, eCombinedImageSampler},
         32},
        {"volumetric tint",
         VOLUMETRIC_LIGHT_TINT_COMP,
         {eStorageBuffer, eStorageBuffer},
         16},
        {"volumetric filter",
         VOLUMETRIC_LIGHT_FILTER_COMP,
         {eCombinedImageSampler, eStorageImage},
         4},
        {"volumetric composite",
         VOLUMETRIC_LIGHT_COMPOSITE_COMP,
         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage, eStorageBuffer,
          eCombinedImageSampler, eCombinedImageSampler},
         4},
        {"point volumetric",
         POINT_VOLUMETRIC_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage},
         12},
        // bbport (r80_lamp-fog-shafts): as VolumetricLight::ShaftsReady makes them: the pass's own
        // bindings, then the shadow maps (2D array); 20 bytes of push constants (the bias and the
        // segment count added). The maps' own pass needs ray queries, which this test's device
        // does not turn on: not built here.
        // bbport (r106_lamp-fog-shaft-cap): all four shafts builds also bind 5, the shaft table
        // bbport (r106c_shaft-march-cheaper): the four shafts builds push 24 bytes now (shaft_fast
        // after the segment count)
        {"point volumetric (shafts)",
         POINT_VOLUMETRIC_SHAFTS_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
          eCombinedImageSampler, eStorageBuffer},
         24},
        {"point volumetric (shafts view)",
         POINT_VOLUMETRIC_SHAFTS_VIEW_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
          eCombinedImageSampler, eStorageBuffer},
         24},
        // bbport (r88_wind-lamp-fog): as VolumetricLight::LampWindPasses makes them: the bindings
        // and push sizes of the plain lamp fog and of r80's shafts builds
        {"point volumetric (wind)",
         POINT_VOLUMETRIC_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage},
         12},
        {"point volumetric (shafts, wind)",
         POINT_VOLUMETRIC_SHAFTS_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
          eCombinedImageSampler, eStorageBuffer},
         24},
        {"point volumetric (shafts view, wind)",
         POINT_VOLUMETRIC_SHAFTS_VIEW_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
          eCombinedImageSampler, eStorageBuffer},
         24},
        // bbport (r82_wind-stage1): as VolumetricLight::WindPasses makes them (WindParams: 112
        // bytes); the gated two have the gate builds' bindings
        {"volumetric integrate (wind)",
         VOLUMETRIC_LIGHT_INTEGRATE_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage},
         112},
        {"volumetric repair (wind)",
         VOLUMETRIC_LIGHT_REPAIR_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage},
         112},
        {"volumetric integrate (gate, wind)",
         VOLUMETRIC_LIGHT_INTEGRATE_GATE_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler},
         112},
        {"volumetric repair (gate, wind)",
         VOLUMETRIC_LIGHT_REPAIR_GATE_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
          eCombinedImageSampler},
         112},
        {"volumetric composite (wind view)",
         VOLUMETRIC_LIGHT_WIND_VIEW_COMP,
         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage, eStorageBuffer,
          eCombinedImageSampler, eCombinedImageSampler},
         4},
        // bbport (r94_fog-noise): as VolumetricLight::NoisePasses makes them (PushBytes: 128); each
        // takes the bindings of the build it stands for
        {"volumetric integrate (fog noise)",
         VOLUMETRIC_LIGHT_INTEGRATE_NOISE_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage},
         128},
        {"volumetric repair (fog noise)",
         VOLUMETRIC_LIGHT_REPAIR_NOISE_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage},
         128},
        {"volumetric integrate (gate, fog noise)",
         VOLUMETRIC_LIGHT_INTEGRATE_GATE_NOISE_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler},
         128},
        {"volumetric repair (gate, fog noise)",
         VOLUMETRIC_LIGHT_REPAIR_GATE_NOISE_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
          eCombinedImageSampler},
         128},
        {"volumetric integrate (area gate, fog noise)",
         VOLUMETRIC_LIGHT_INTEGRATE_AREA_NOISE_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage},
         128},
        {"volumetric repair (area gate, fog noise)",
         VOLUMETRIC_LIGHT_REPAIR_AREA_NOISE_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage},
         128},
        {"volumetric integrate (gate, area gate, fog noise)",
         VOLUMETRIC_LIGHT_INTEGRATE_GATE_AREA_NOISE_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler},
         128},
        {"volumetric repair (gate, area gate, fog noise)",
         VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_NOISE_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
          eCombinedImageSampler},
         128},
    };
    u32 built = 0;
    for (const Pass& pass : passes) {
        std::vector<vk::DescriptorSetLayoutBinding> bindings;
        for (const auto type : pass.types) {
            bindings.push_back({.binding = u32(bindings.size()),
                                .descriptorType = type,
                                .descriptorCount = 1,
                                .stageFlags = vk::ShaderStageFlagBits::eCompute});
        }
        auto set = device
                       .createDescriptorSetLayoutUnique(
                           {.flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
                            .bindingCount = u32(bindings.size()),
                            .pBindings = bindings.data()})
                       .value;
        const vk::PushConstantRange push{.stageFlags = vk::ShaderStageFlagBits::eCompute,
                                         .offset = 0,
                                         .size = pass.push};
        auto layout = device
                          .createPipelineLayoutUnique({.setLayoutCount = 1,
                                                       .pSetLayouts = &*set,
                                                       .pushConstantRangeCount = 1,
                                                       .pPushConstantRanges = &push})
                          .value;
        auto module = device
                          .createShaderModuleUnique({.codeSize = pass.code.size_bytes(),
                                                     .pCode = pass.code.data()})
                          .value;
        auto pipeline = device.createComputePipelineUnique(
            {}, vk::ComputePipelineCreateInfo{.flags = vk::PipelineCreateFlagBits::eDispatchBase,
                                              .stage = {.stage = vk::ShaderStageFlagBits::eCompute,
                                                        .module = *module,
                                                        .pName = "main"},
                                              .layout = *layout});
        if (pipeline.result != vk::Result::eSuccess) {
            std::printf("%s: %s\n", pass.name, vk::to_string(pipeline.result).c_str());
            return 1;
        }
        ++built;
    }
    for (const auto code : {std::span<const u32>(GTAO_FRAG), std::span<const u32>(SSR_FRAG),
                            std::span<const u32>(NATIVE_MOTION_BLUR_FRAG),
                            std::span<const u32>(BLOOM_DOWNSAMPLE_FRAG)}) {
        auto module = device.createShaderModuleUnique(
            {.codeSize = code.size_bytes(), .pCode = code.data()});
        assert(module.result == vk::Result::eSuccess);
    }
    std::printf("effect pipelines: %u built, %u validation messages\n", built, messages);
    return messages == 0 ? 0 : 1;
}
