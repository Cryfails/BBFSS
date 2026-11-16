// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r82_wind-stage1): the GLSL copy of the fog noise, the march step and the view helpers
// (host_shaders/wind_noise.glsl, run by wind_noise_test.comp) against gpu/shim/bbport_wind.h on
// the GPU: the pinned Noise3 and Field values of tests/test_wind.cpp to 1e-6, 4096 random points
// against the C++ functions (Noise3 1e-6, Field 1e-4: see there), the view to world rows of a
// turned and moved camera (ViewToWorld), the test view's shade (ViewShade), contrast 0 giving
// exactly 1, and the march along a view ray: at a contrast of 0 read at run time within 1e-6 of
// the march without wind (not bit for bit: the driver may fuse the two expressions' multiply-adds
// differently; a literal 1 was folded at compile time and hid that), and with the noise as the
// C++ MarchStep within 1e-4 of the even fog's light. One dispatch.
#include <vulkan/vulkan.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "gpu/shim/bbport_wind.h"
#include "video_core/host_shaders/wind_noise_test_comp.h"

namespace {
#define CHECK(call) do { if ((call) != VK_SUCCESS) { std::fprintf(stderr, "%s failed\n", #call); std::abort(); } } while (false)
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

struct Buffer { VkBuffer buffer{}; VkDeviceMemory memory{}; void* data{}; unsigned size{}; };

struct Gpu {
    VkInstance instance{};
    VkPhysicalDevice gpu{};
    VkDevice device{};
    VkQueue queue{};
    VkPhysicalDeviceMemoryProperties memory{};
    VkCommandPool pool{};
    VkCommandBuffer cmd{};
    VkDescriptorSetLayout set{};
    VkPipelineLayout layout{};
    VkPipeline pipeline{};
    PFN_vkCmdPushDescriptorSetKHR descriptors{};
    std::vector<Buffer> buffers;

    unsigned Memory(unsigned bits, VkMemoryPropertyFlags flags) {
        for (unsigned i = 0; i < memory.memoryTypeCount; ++i)
            if ((bits & (1u << i)) && (memory.memoryTypes[i].propertyFlags & flags) == flags) return i;
        std::abort();
    }
    Buffer MakeBuffer(unsigned size) {
        Buffer b{.size = size};
        VkBufferCreateInfo info{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = size,
            .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT};
        CHECK(vkCreateBuffer(device, &info, nullptr, &b.buffer));
        VkMemoryRequirements req;
        vkGetBufferMemoryRequirements(device, b.buffer, &req);
        VkMemoryAllocateInfo alloc{.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
            .allocationSize = req.size, .memoryTypeIndex = Memory(req.memoryTypeBits,
                VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
        CHECK(vkAllocateMemory(device, &alloc, nullptr, &b.memory));
        CHECK(vkBindBufferMemory(device, b.buffer, b.memory, 0));
        CHECK(vkMapMemory(device, b.memory, 0, VK_WHOLE_SIZE, 0, &b.data));
        std::memset(b.data, 0, size);
        buffers.push_back(b);
        return b;
    }
    Gpu() {
        VkApplicationInfo app{.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
            .pApplicationName = "wind-noise-test", .apiVersion = VK_API_VERSION_1_3};
        VkInstanceCreateInfo ci{.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app};
        CHECK(vkCreateInstance(&ci, nullptr, &instance));
        unsigned count = 0;
        CHECK(vkEnumeratePhysicalDevices(instance, &count, nullptr));
        if (count == 0) {
            std::fprintf(stderr, "no Vulkan device\n");
            std::abort();
        }
        std::vector<VkPhysicalDevice> devices(count);
        CHECK(vkEnumeratePhysicalDevices(instance, &count, devices.data()));
        gpu = devices[0];
        vkGetPhysicalDeviceMemoryProperties(gpu, &memory);
        unsigned families_count = 0, family = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(gpu, &families_count, nullptr);
        std::vector<VkQueueFamilyProperties> families(families_count);
        vkGetPhysicalDeviceQueueFamilyProperties(gpu, &families_count, families.data());
        while (family < families_count && !(families[family].queueFlags & VK_QUEUE_COMPUTE_BIT)) ++family;
        if (family == families_count) std::abort();
        const float priority = 1;
        VkDeviceQueueCreateInfo qi{.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
            .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority};
        const char* extension = VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME;
        VkDeviceCreateInfo di{.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
            .queueCreateInfoCount = 1, .pQueueCreateInfos = &qi,
            .enabledExtensionCount = 1, .ppEnabledExtensionNames = &extension};
        CHECK(vkCreateDevice(gpu, &di, nullptr, &device));
        vkGetDeviceQueue(device, family, 0, &queue);
        descriptors = reinterpret_cast<PFN_vkCmdPushDescriptorSetKHR>(
            vkGetDeviceProcAddr(device, "vkCmdPushDescriptorSetKHR"));
        if (!descriptors) std::abort();
        VkCommandPoolCreateInfo pi{.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
            .queueFamilyIndex = family};
        CHECK(vkCreateCommandPool(device, &pi, nullptr, &pool));
        VkCommandBufferAllocateInfo ai{.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
            .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
        CHECK(vkAllocateCommandBuffers(device, &ai, &cmd));
        std::array<VkDescriptorSetLayoutBinding, 3> bindings{};
        for (unsigned i = 0; i < bindings.size(); ++i)
            bindings[i] = {i, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr};
        VkDescriptorSetLayoutCreateInfo si{.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
            .flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR,
            .bindingCount = unsigned(bindings.size()), .pBindings = bindings.data()};
        CHECK(vkCreateDescriptorSetLayout(device, &si, nullptr, &set));
        VkPushConstantRange range{VK_SHADER_STAGE_COMPUTE_BIT, 0, 4};
        VkPipelineLayoutCreateInfo li{.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
            .setLayoutCount = 1, .pSetLayouts = &set, .pushConstantRangeCount = 1, .pPushConstantRanges = &range};
        CHECK(vkCreatePipelineLayout(device, &li, nullptr, &layout));
        VkShaderModule module;
        VkShaderModuleCreateInfo mi{.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
            .codeSize = sizeof(WIND_NOISE_TEST_COMP), .pCode = WIND_NOISE_TEST_COMP};
        CHECK(vkCreateShaderModule(device, &mi, nullptr, &module));
        VkComputePipelineCreateInfo pc{.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
            .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
                .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = module, .pName = "main"}, .layout = layout};
        CHECK(vkCreateComputePipelines(device, {}, 1, &pc, nullptr, &pipeline));
        vkDestroyShaderModule(device, module, nullptr);
    }
    void Run(const Buffer& cases, const Buffer& values, const Buffer& marches, unsigned count) {
        VkCommandBufferBeginInfo begin{.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
        CHECK(vkBeginCommandBuffer(cmd, &begin));
        const std::array<VkDescriptorBufferInfo, 3> infos{{{cases.buffer, 0, cases.size},
                                                           {values.buffer, 0, values.size},
                                                           {marches.buffer, 0, marches.size}}};
        std::array<VkWriteDescriptorSet, 3> writes{};
        for (unsigned i = 0; i < writes.size(); ++i)
            writes[i] = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = i,
                         .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
                         .pBufferInfo = &infos[i]};
        vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
        descriptors(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, layout, 0, 3, writes.data());
        vkCmdPushConstants(cmd, layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, 4, &count);
        vkCmdDispatch(cmd, (count + 63) / 64, 1, 1);
        VkMemoryBarrier host{.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
        vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
            0, 1, &host, 0, nullptr, 0, nullptr);
        CHECK(vkEndCommandBuffer(cmd));
        VkSubmitInfo submit{.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cmd};
        CHECK(vkQueueSubmit(queue, 1, &submit, {}));
        CHECK(vkQueueWaitIdle(queue));
    }
    ~Gpu() {
        vkDeviceWaitIdle(device);
        for (auto b : buffers) {
            vkUnmapMemory(device, b.memory);
            vkDestroyBuffer(device, b.buffer, nullptr);
            vkFreeMemory(device, b.memory, nullptr);
        }
        vkDestroyPipeline(device, pipeline, nullptr);
        vkDestroyPipelineLayout(device, layout, nullptr);
        vkDestroyDescriptorSetLayout(device, set, nullptr);
        vkDestroyCommandPool(device, pool, nullptr);
        vkDestroyDevice(device, nullptr);
        vkDestroyInstance(instance, nullptr);
    }
};

/// splitmix64, as in tests/test_wind.cpp.
struct Random {
    std::uint64_t state;
    std::uint64_t Next() {
        std::uint64_t z = (state += 0x9e3779b97f4a7c15ull);
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
        return z ^ (z >> 31);
    }
    float Unit() { // [0, 1)
        return float(Next() >> 40) * (1.0f / 16777216.0f);
    }
};

struct Case {
    std::array<float, 3> p, o1, o2;
    float contrast, density, ds, jitter, seed;
    std::array<float, 12> rows;  ///< view to world, 3x4 rows
    std::array<float, 3> ray;    ///< unit view ray of the march
};

constexpr std::array<float, 12> Identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};

/// The C++ side of the shader's third march: MarchStep with m = Density at ViewToWorld(ray t),
/// as wind_ray_step takes it.
float CpuMarch(const Case& c) {
    BbWind::March march;
    for (unsigned i = 0; i < 32; ++i) {
        const float t = (float(i) + c.jitter) * c.ds;
        const float scaled = float(i) * 0.6180339f + c.seed;
        const float vis = scaled - std::floor(scaled);
        const std::array<float, 3> v{c.ray[0] * t, c.ray[1] * t, c.ray[2] * t};
        const float m = BbWind::Density(BbWind::ViewToWorld(c.rows, v), c.o1, c.o2, c.contrast);
        BbWind::MarchStep(march, c.density, t, c.ds, c.jitter, m, vis);
    }
    return march.energy;
}
} // namespace

int main() {
    char what[200];
    std::vector<Case> cases;
    // The six Noise3 pins and the four Field pins of tests/test_wind.cpp (h, k).
    constexpr std::array<std::array<float, 4>, 6> noise_pins{{
        {0.0f, 0.0f, 0.0f, 0.6081519f},
        {0.5f, 0.5f, 0.5f, 0.5781672f},
        {1.25f, 7.5f, -3.75f, 0.5259736f},
        {255.9f, 0.0f, 0.0f, 0.6062171f},
        {-0.3f, 12.7f, 100.1f, 0.4207422f},
        {3.0f, 3.0f, 3.0f, 0.4130008f},
    }};
    struct FieldPin {
        std::array<float, 3> p, o1, o2;
        float value;
    };
    const std::array<FieldPin, 4> field_pins{{
        {{0.0f, 0.0f, 0.0f}, {0.25f, 0.5f, 0.75f}, {1.5f, 2.25f, 3.0f}, 0.2916170f},
        {{13.0f, 7.0f, -25.0f}, {3.125f, 0.0f, 250.5f}, {17.75f, 0.0f, 128.0f}, 0.4034448f},
        {{101.3f, 2.4f, 57.9f}, {200.0f, 0.0f, 33.3f}, {5.5f, 0.0f, 99.9f}, 0.6770673f},
        {{-48.6f, 15.2f, 211.7f}, {12.75f, 0.0f, 0.5f}, {255.5f, 0.0f, 64.25f}, 0.3751206f},
    }};
    for (const auto& pin : noise_pins)
        cases.push_back({{pin[0], pin[1], pin[2]}, {}, {}, 0.4f, 0.025f, 1.25f, 0.5f, 0.25f,
                         Identity, {1.0f, 0.0f, 0.0f}});
    for (const auto& pin : field_pins)
        cases.push_back({pin.p, pin.o1, pin.o2, 0.4f, 0.025f, 1.25f, 0.5f, 0.75f, Identity,
                         {0.0f, 0.0f, 1.0f}});
    Random random{2026};
    // 0 (an even fog), the plan's 0.4, the default and the largest.
    const std::array<float, 4> contrasts{0.0f, 0.4f, BbWind::DefaultContrast, BbWind::MaxContrast};
    for (unsigned i = 0; i < 4096; ++i) {
        Case c{};
        for (unsigned k = 0; k < 3; ++k) {
            c.p[k] = random.Unit() * 600.0f - 300.0f;
            c.o1[k] = random.Unit() * 256.0f;
            c.o2[k] = random.Unit() * 256.0f;
        }
        c.contrast = contrasts[i % contrasts.size()];
        c.density = 0.01f + 0.04f * random.Unit();
        c.ds = 0.1f + 1.4f * random.Unit();
        c.jitter = random.Unit();
        c.seed = random.Unit();
        // A camera turned by yaw and pitch, placed up to 300 m from the origin: a matrix whose
        // rows all differ, so a swapped row or a lost translation changes the world point.
        const float yaw = random.Unit() * 6.2831853f, pitch = (random.Unit() - 0.5f) * 1.5f;
        const float cy = std::cos(yaw), sy = std::sin(yaw), cp = std::cos(pitch), sp = std::sin(pitch);
        c.rows = {cy, sy * sp, sy * cp, random.Unit() * 600.0f - 300.0f,
                  0.0f, cp, -sp, random.Unit() * 40.0f - 20.0f,
                  -sy, cy * sp, cy * cp, random.Unit() * 600.0f - 300.0f};
        const float a = random.Unit() * 6.2831853f, e = (random.Unit() - 0.5f) * 1.2f;
        c.ray = {std::cos(a) * std::cos(e), std::sin(e), std::sin(a) * std::cos(e)};
        cases.push_back(c);
    }
    const unsigned count = unsigned(cases.size());
    Gpu gpu;
    const Buffer in = gpu.MakeBuffer(count * 128), values = gpu.MakeBuffer(count * 32),
                 marches = gpu.MakeBuffer(count * 16);
    auto* words = static_cast<float*>(in.data);
    for (unsigned i = 0; i < count; ++i) {
        const Case& c = cases[i];
        const std::array<float, 32> v{c.p[0], c.p[1], c.p[2], c.contrast, c.o1[0], c.o1[1], c.o1[2],
                                      c.density, c.o2[0], c.o2[1], c.o2[2], c.ds, c.jitter, c.seed,
                                      0.0f, 0.0f, c.rows[0], c.rows[1], c.rows[2], c.rows[3],
                                      c.rows[4], c.rows[5], c.rows[6], c.rows[7], c.rows[8],
                                      c.rows[9], c.rows[10], c.rows[11], c.ray[0], c.ray[1],
                                      c.ray[2], 0.0f};
        std::memcpy(words + i * 32, v.data(), sizeof(v));
    }
    gpu.Run(in, values, marches, count);
    const auto* out = static_cast<const float*>(values.data);
    const auto* bits = static_cast<const std::uint32_t*>(marches.data);

    for (unsigned i = 0; i < noise_pins.size(); ++i) {
        const float got = out[i * 8];
        std::printf("wind-noise-test: GPU Noise3(%g, %g, %g) = %.7f (pinned %.7f)\n",
                    double(noise_pins[i][0]), double(noise_pins[i][1]), double(noise_pins[i][2]),
                    double(got), double(noise_pins[i][3]));
        std::snprintf(what, sizeof(what), "GPU Noise3 pin %u within 1e-6", i);
        Expect(std::fabs(got - noise_pins[i][3]) <= 1e-6f, what);
    }
    for (unsigned i = 0; i < field_pins.size(); ++i) {
        const float got = out[(noise_pins.size() + i) * 8 + 1];
        std::printf("wind-noise-test: GPU Field pin %u = %.7f (pinned %.7f)\n", i, double(got),
                    double(field_pins[i].value));
        std::snprintf(what, sizeof(what), "GPU Field pin %u within 1e-6", i);
        Expect(std::fabs(got - field_pins[i].value) <= 1e-6f, what);
    }
    float worst_noise = 0.0f, worst_field = 0.0f, worst_density = 0.0f, worst_march = 0.0f;
    float worst_rows = 0.0f, worst_world = 0.0f, worst_shade = 0.0f, worst_flat = 0.0f;
    unsigned same_bits = 0, flat_exact = 0, flat_cases = 0;
    for (unsigned i = 0; i < count; ++i) {
        const Case& c = cases[i];
        const float* o = out + i * 8;
        const float noise = BbWind::Noise3(c.p[0], c.p[1], c.p[2]);
        const float field = BbWind::Field(c.p, c.o1, c.o2);
        const float density = BbWind::Density(c.p, c.o1, c.o2, c.contrast);
        const std::array<float, 3> world = BbWind::ViewToWorld(c.rows, c.p);
        const float through_rows = BbWind::Density(world, c.o1, c.o2, c.contrast);
        worst_noise = std::max(worst_noise, std::fabs(o[0] - noise));
        worst_field = std::max(worst_field, std::fabs(o[1] - field));
        worst_density = std::max(worst_density, std::fabs(o[2] - density));
        worst_rows = std::max(worst_rows, std::fabs(o[3] - through_rows));
        for (unsigned k = 0; k < 3; ++k)
            worst_world = std::max(worst_world, std::fabs(o[4 + k] - world[k]));
        // The shade of the GPU's own m: this checks wind_view_shade alone.
        worst_shade = std::max(worst_shade, std::fabs(o[7] - BbWind::ViewShade(o[2], c.contrast)));
        if (c.contrast == 0.0f) {
            ++flat_cases;
            flat_exact += o[2] == 1.0f;
        }
        same_bits += bits[i * 4] == bits[i * 4 + 1];
        float plain_energy, flat_energy, gpu_energy;
        std::memcpy(&plain_energy, &bits[i * 4], 4);
        std::memcpy(&flat_energy, &bits[i * 4 + 1], 4);
        std::memcpy(&gpu_energy, &bits[i * 4 + 2], 4);
        worst_flat = std::max(worst_flat, std::fabs(flat_energy - plain_energy) /
                                              std::max(plain_energy, 1e-12f));
        // Against the even fog's light, not the drifting one's: at contrast 2 a ray can run
        // through holes (m = 0) almost all the way, and a tiny energy makes a relative error
        // meaningless.
        const float cpu_energy = CpuMarch(c);
        worst_march = std::max(worst_march, std::fabs(gpu_energy - cpu_energy) /
                                                std::max({cpu_energy, plain_energy, 1e-12f}));
    }
    std::printf("wind-noise-test: %u points against bbport_wind.h: Noise3 %.2g, Field %.2g, "
                "Density %.2g, Density through the view to world rows %.2g, the world point %.2g "
                "m, the view shade %.2g at most; contrast 0 gave exactly 1 at %u of %u; the ray "
                "step at a contrast of 0 read at run time is %.2g (relative) from the march "
                "without wind, the same bits at %u of %u; with the noise it is %.2g (of the even "
                "fog's light) from MarchStep\n",
                count, double(worst_noise), double(worst_field), double(worst_density),
                double(worst_rows), double(worst_world), double(worst_shade), flat_exact,
                flat_cases, double(worst_flat), same_bits, count, double(worst_march));
    // Noise3 takes the coordinates as they are: 1e-6. Field divides them first, and Vulkan lets a
    // GPU's division be 2.5 ulp off (a driver may also multiply by a reciprocal), so at |p| up to
    // 300 m and offsets up to 256 cells the cell coordinate's last bits (up to 3e-5 cells) can
    // differ from the C++ division: 1e-4. Density: 2 times the largest contrast times that. The
    // world point: |p| and the translation up to 300 m each, a few float ulps of 600 m (the GPU
    // may fuse the dot product's multiply-adds): 1e-3 m. The pins above, nearer the origin,
    // hold 1e-6.
    const float density_tolerance = 2.0f * BbWind::MaxContrast * 1e-4f;
    Expect(worst_noise <= 1e-6f, "the GPU Noise3 is the C++ Noise3 within 1e-6");
    Expect(worst_field <= 1e-4f && worst_density <= density_tolerance,
           "the GPU Field and Density are the C++ ones within 1e-4 and 2 MaxContrast 1e-4");
    Expect(worst_rows <= density_tolerance,
           "the GPU factor through the rows is Density(ViewToWorld) within 2 MaxContrast 1e-4");
    Expect(worst_world <= 1e-3f, "the GPU view to world point is ViewToWorld's within 1e-3 m");
    Expect(worst_shade <= 1e-6f, "the GPU view shade is ViewShade within 1e-6");
    Expect(flat_exact == flat_cases, "contrast 0 gives exactly 1 on the GPU");
    Expect(worst_flat <= 1e-6f,
           "at a run-time contrast of 0 the GPU ray step is the plain march within 1e-6");
    Expect(worst_march <= 1e-4f,
           "the GPU march with the noise is MarchStep's within 1e-4 of the even fog's light");
    if (failures) {
        std::printf("wind-noise-test: %d failure(s)\n", failures);
        return 1;
    }
    std::printf("wind-noise-test: ok\n");
    return 0;
}
