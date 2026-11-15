// SPDX-License-Identifier: GPL-3.0-or-later
#include <vulkan/vulkan.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits>
#include <random>
#include <vector>
#include "video_core/host_shaders/contact_shadow_comp.h"
#include "video_core/host_shaders/rt_shadow_comp.h"
#include "video_core/host_shaders/rt_shadow_filter_comp.h"
#include "video_core/host_shaders/rt_lab_comp.h"
#include "video_core/host_shaders/point_shadow_ray_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_comp.h" // bbport (r42_lamp-soft)
// bbport (r60_lamp-centred-window): the BB_LAMP_SHADOW_WINDOW=2 builds
#include "video_core/host_shaders/point_shadow_ray_centred_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_centred_comp.h"
#include "video_core/host_shaders/rt_still_sig_comp.h" // bbport (r47_still-check)
#include "video_core/host_shaders/rt_unproject_comp.h"
#include "video_core/host_shaders/ssgi_gather_ray_comp.h"
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h" // bbport (r41_lamp-shadows)
#include "gpu/shadps4/video_core/renderer_vulkan/rt_still_check.h" // bbport (r47_still-check)

namespace {
#define CHECK(call) do { if (VkResult r_ = (call); r_ != VK_SUCCESS) { std::fprintf(stderr, "%s failed: %d\n", #call, int(r_)); std::exit(1); } } while (false)
constexpr unsigned W = 1920, H = 1080, Atlas = 4096;
constexpr VkDeviceSize AsAlign = 256;

struct Vec3 { float x, y, z; };
Vec3 operator+(Vec3 a, Vec3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
Vec3 operator*(Vec3 a, float s) { return {a.x * s, a.y * s, a.z * s}; }
float Dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
Vec3 Cross(Vec3 a, Vec3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
Vec3 Norm(Vec3 a) { return a * (1.0f / std::sqrt(Dot(a, a))); }

struct Mat4 {
    std::array<float, 16> m{};
    float& at(int r, int c) { return m[r * 4 + c]; }
    float at(int r, int c) const { return m[r * 4 + c]; }
};
Mat4 Identity() { Mat4 r; for (int i = 0; i < 4; ++i) r.at(i, i) = 1; return r; }
Mat4 operator*(const Mat4& a, const Mat4& b) {
    Mat4 r;
    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j)
            for (int k = 0; k < 4; ++k) r.at(i, j) += a.at(i, k) * b.at(k, j);
    return r;
}
Mat4 Inverse(const Mat4& a) {
    std::array<double, 32> t{};
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) t[r * 8 + c] = a.at(r, c);
        t[r * 8 + 4 + r] = 1;
    }
    for (int p = 0; p < 4; ++p) {
        int best = p;
        for (int r = p; r < 4; ++r) if (std::abs(t[r * 8 + p]) > std::abs(t[best * 8 + p])) best = r;
        for (int c = 0; c < 8; ++c) std::swap(t[p * 8 + c], t[best * 8 + c]);
        const double d = 1.0 / t[p * 8 + p];
        for (int c = 0; c < 8; ++c) t[p * 8 + c] *= d;
        for (int r = 0; r < 4; ++r) {
            if (r == p) continue;
            const double f = t[r * 8 + p];
            for (int c = 0; c < 8; ++c) t[r * 8 + c] -= f * t[p * 8 + c];
        }
    }
    Mat4 r;
    for (int i = 0; i < 4; ++i)
        for (int c = 0; c < 4; ++c) r.at(i, c) = float(t[i * 8 + 4 + c]);
    return r;
}
Mat4 LookTo(Vec3 eye, Vec3 forward) {
    const Vec3 z = Norm(forward);
    const Vec3 x = Norm(Cross({0, 1, 0}, z));
    const Vec3 y = Cross(z, x);
    Mat4 r = Identity();
    r.at(0, 0) = x.x; r.at(0, 1) = x.y; r.at(0, 2) = x.z; r.at(0, 3) = -Dot(x, eye);
    r.at(1, 0) = y.x; r.at(1, 1) = y.y; r.at(1, 2) = y.z; r.at(1, 3) = -Dot(y, eye);
    r.at(2, 0) = z.x; r.at(2, 1) = z.y; r.at(2, 2) = z.z; r.at(2, 3) = -Dot(z, eye);
    return r;
}

struct Mesh {
    std::vector<Vec3> vertices;
    std::vector<std::uint32_t> indices;
    Vec3 position{};
    bool skinned = false;
    Vec3 scale{1, 1, 1};
};

void AddGrid(Mesh& mesh, Vec3 origin, Vec3 du, Vec3 dv, unsigned n) {
    const auto base = std::uint32_t(mesh.vertices.size());
    for (unsigned j = 0; j <= n; ++j)
        for (unsigned i = 0; i <= n; ++i)
            mesh.vertices.push_back(origin + du * (float(i) / n) + dv * (float(j) / n));
    for (unsigned j = 0; j < n; ++j)
        for (unsigned i = 0; i < n; ++i) {
            const std::uint32_t a = base + j * (n + 1) + i, b = a + 1, c = a + n + 1, d = c + 1;
            mesh.indices.insert(mesh.indices.end(), {a, b, c, b, d, c});
        }
}

Mesh Box(Vec3 size, unsigned triangles) {
    Mesh mesh;
    const auto n = std::max(1u, unsigned(std::sqrt(float(triangles) / 12.0f)));
    const Vec3 x{size.x, 0, 0}, y{0, size.y, 0}, z{0, 0, size.z}, o{-size.x / 2, 0, -size.z / 2};
    AddGrid(mesh, o, x, y, n);
    AddGrid(mesh, o + z, y, x, n);
    AddGrid(mesh, o, y, z, n);
    AddGrid(mesh, o + x, z, y, n);
    AddGrid(mesh, o, z, x, n);
    AddGrid(mesh, o + y, x, z, n);
    return mesh;
}

Mesh Capsule(float height, float radius, unsigned triangles) {
    Mesh mesh;
    const auto n = std::max(4u, unsigned(std::sqrt(float(triangles) / 2.0f)));
    for (unsigned j = 0; j <= n; ++j) {
        const float v = float(j) / n, a = v * 3.14159265f;
        for (unsigned i = 0; i <= n; ++i) {
            const float u = float(i) / n * 6.2831853f;
            const float r = radius * std::sin(a);
            mesh.vertices.push_back({r * std::cos(u), height * (0.5f + 0.5f * std::cos(a)), r * std::sin(u)});
        }
    }
    for (unsigned j = 0; j < n; ++j)
        for (unsigned i = 0; i < n; ++i) {
            const std::uint32_t a = j * (n + 1) + i, b = a + 1, c = a + n + 1, d = c + 1;
            mesh.indices.insert(mesh.indices.end(), {a, c, b, b, c, d});
        }
    return mesh;
}

// bbport (r42_lamp-soft): a box from a to b, `thick` across (a stick, an arm).
Mesh Beam(Vec3 a, Vec3 b, float thick) {
    Mesh mesh;
    const Vec3 dir = Norm(b + a * -1.0f);
    const Vec3 side = Norm(Cross(dir, std::abs(dir.y) < 0.9f ? Vec3{0, 1, 0} : Vec3{1, 0, 0})) * (thick * 0.5f);
    const Vec3 up = Norm(Cross(dir, side)) * (thick * 0.5f);
    for (int k = 0; k < 8; ++k) {
        mesh.vertices.push_back((k & 4 ? b : a) + side * (k & 1 ? 1.0f : -1.0f) + up * (k & 2 ? 1.0f : -1.0f));
    }
    mesh.indices = {0, 1, 3, 0, 3, 2, 4, 7, 5, 4, 6, 7, 0, 4, 5, 0, 5, 1,
                    2, 3, 7, 2, 7, 6, 0, 2, 6, 0, 6, 4, 1, 5, 7, 1, 7, 3};
    return mesh;
}

// bbport (r42_lamp-soft): the torch lab's scene (rt-shadow-test --lamps): a character with a
// hand torch seen from above, as in the report the area lamp answers. The meshes, in this
// order: the ground; the character (a capsule 1.8 m tall, 0.6 m wide); its arm, 8 cm thick,
// from the shoulder to the raised hand; the torch's stick, 3.5 cm thick and 0.9 m long, from
// the hand up towards the flame; a blade at its hip, 5 cm thick, down to knee height; a second
// figure 1.5 m away; a post 8 cm thick; a low wall. The lamp sits at TorchFlame, 0.2 m off the
// stick's line (a stick that points at its lamp casts a dot, not a band) and above the head;
// the pass is blind within 0.35 m of a lamp. So the stick and the arm are thin casters near the
// lamp, the blade is a thin caster near the ground, and the two figures are bodies near and far.
constexpr unsigned TorchCharacter = 1, TorchArm = 2, TorchStick = 3, TorchBlade = 4, TorchOther = 5;
constexpr Vec3 TorchFlame{-0.72f, 2.1f, 0.55f};
std::vector<Mesh> MakeTorchScene() {
    std::vector<Mesh> scene;
    Mesh ground = Box({60, 1, 60}, 1200);
    ground.position = {0, -1, 0};
    scene.push_back(std::move(ground));
    Mesh body = Capsule(1.8f, 0.3f, 30000);
    body.skinned = true;
    scene.push_back(std::move(body));
    scene.push_back(Beam({-0.2f, 1.45f, -0.05f}, {-0.42f, 1.45f, -0.25f}, 0.08f));
    scene.push_back(Beam({-0.42f, 1.4f, -0.29f}, {-0.6f, 1.98f, 0.38f}, 0.035f));
    scene.push_back(Beam({0.35f, 0.9f, -0.1f}, {0.7f, 0.35f, -0.75f}, 0.05f));
    Mesh other = Capsule(1.8f, 0.3f, 30000);
    other.position = {1.5f, 0, 0.1f};
    other.skinned = true;
    scene.push_back(std::move(other));
    Mesh post = Box({0.08f, 2.5f, 0.08f}, 600);
    post.position = {-1.9f, 0, -0.5f};
    scene.push_back(std::move(post));
    Mesh wall = Box({5.0f, 1.2f, 0.3f}, 1200);
    wall.position = {0.3f, 0, 1.9f};
    scene.push_back(std::move(wall));
    return scene;
}

std::vector<Mesh> MakeScene(unsigned total_triangles, unsigned draws) {
    std::mt19937 rng(7);
    const auto range = [&](float lo, float hi) { return std::uniform_real_distribution<float>(lo, hi)(rng); };
    std::vector<Mesh> scene;
    const unsigned character_triangles = 30000, characters = 6;
    const unsigned static_triangles = total_triangles - std::min(total_triangles, characters * character_triangles);
    const unsigned per_draw = std::max(12u, static_triangles / draws);
    Mesh ground = Box({400, 1, 400}, per_draw);
    ground.position = {0, -1, 60};
    scene.push_back(std::move(ground));
    for (unsigned i = 1; i < draws; ++i) {
        const unsigned kind = i % 10;
        if (kind < 4) {
            Mesh m = Box({range(4, 14), range(6, 30), range(4, 14)}, per_draw);
            const float side = i % 2 ? 1.0f : -1.0f;
            m.position = {side * range(11, 40), 0, range(-20, 220)};
            scene.push_back(std::move(m));
        } else if (kind < 7) {
            Mesh m = Box({0.08f, range(1, 4), 0.08f}, per_draw);
            m.position = {range(-9, 9), 0, range(2, 60)};
            scene.push_back(std::move(m));
        } else if (kind < 8) {
            Mesh m = Box({range(0.8f, 2.5f), range(0.5f, 2.0f), range(0.8f, 2.5f)}, per_draw);
            m.position = {range(-9, 9), 0, range(3, 90)};
            scene.push_back(std::move(m));
        } else if (kind < 9) {
            Mesh m = Box({range(3, 8), 0.2f, range(1, 3)}, per_draw);
            m.position = {range(-10, 10), range(2.5f, 6), range(3, 90)};
            scene.push_back(std::move(m));
        } else {
            Mesh m = Box({0.05f, 0.05f, range(2, 8)}, per_draw);
            m.position = {range(-9, 9), range(0.5f, 3), range(2, 60)};
            scene.push_back(std::move(m));
        }
    }
    for (unsigned i = 0; i < characters; ++i) {
        Mesh m = Capsule(1.8f, 0.3f, character_triangles);
        m.position = {range(-5, 5), 0, 4.0f + 4.0f * float(i)};
        m.skinned = true;
        scene.push_back(std::move(m));
    }
    return scene;
}

struct Buffer {
    VkBuffer buffer{};
    VkDeviceMemory memory{};
    void* data{};
    VkDeviceAddress address{};
    VkDeviceSize size{};
};
struct Image {
    VkImage image{};
    VkDeviceMemory memory{};
    VkImageView view{};
};
struct Pipeline {
    VkDescriptorSetLayout set{};
    VkPipelineLayout layout{};
    VkPipeline pipeline{};
};

struct Vk {
    VkInstance instance{};
    VkPhysicalDevice gpu{};
    VkDevice device{};
    VkQueue queue{};
    VkPhysicalDeviceMemoryProperties memory{};
    VkCommandPool pool{};
    VkCommandBuffer cmd{};
    VkQueryPool stamps{};
    VkQueryPool compact_query{};
    VkSampler sampler{};
    float period = 0;
    std::uint64_t mask = ~std::uint64_t{0};
    PFN_vkCmdPushDescriptorSetKHR push{};
    PFN_vkCreateAccelerationStructureKHR create_as{};
    PFN_vkGetAccelerationStructureBuildSizesKHR sizes{};
    PFN_vkCmdBuildAccelerationStructuresKHR build{};
    PFN_vkGetAccelerationStructureDeviceAddressKHR as_address{};
    PFN_vkCmdWriteAccelerationStructuresPropertiesKHR write_props{};
    PFN_vkDestroyAccelerationStructureKHR destroy_as{};
    char name[256]{};

    unsigned Memory(unsigned bits, VkMemoryPropertyFlags flags) {
        for (unsigned i = 0; i < memory.memoryTypeCount; ++i)
            if ((bits & (1u << i)) && (memory.memoryTypes[i].propertyFlags & flags) == flags) return i;
        std::fprintf(stderr, "no memory type\n");
        std::exit(1);
    }
    Buffer MakeBuffer(VkDeviceSize bytes, VkBufferUsageFlags usage, bool host) {
        Buffer b;
        b.size = bytes;
        VkBufferCreateInfo info{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = bytes,
            .usage = usage | VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT};
        CHECK(vkCreateBuffer(device, &info, nullptr, &b.buffer));
        VkMemoryRequirements req;
        vkGetBufferMemoryRequirements(device, b.buffer, &req);
        VkMemoryAllocateFlagsInfo flags{.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_FLAGS_INFO,
            .flags = VK_MEMORY_ALLOCATE_DEVICE_ADDRESS_BIT};
        VkMemoryAllocateInfo alloc{.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .pNext = &flags,
            .allocationSize = req.size, .memoryTypeIndex = Memory(req.memoryTypeBits,
                host ? VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT
                     : VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)};
        CHECK(vkAllocateMemory(device, &alloc, nullptr, &b.memory));
        CHECK(vkBindBufferMemory(device, b.buffer, b.memory, 0));
        if (host) CHECK(vkMapMemory(device, b.memory, 0, VK_WHOLE_SIZE, 0, &b.data));
        VkBufferDeviceAddressInfo address{.sType = VK_STRUCTURE_TYPE_BUFFER_DEVICE_ADDRESS_INFO, .buffer = b.buffer};
        b.address = vkGetBufferDeviceAddress(device, &address);
        return b;
    }
    void Free(Buffer& b) {
        if (!b.buffer) return;
        if (b.data) vkUnmapMemory(device, b.memory);
        vkDestroyBuffer(device, b.buffer, nullptr);
        vkFreeMemory(device, b.memory, nullptr);
        b = {};
    }
    Image MakeImage(unsigned w, unsigned h, VkFormat format) {
        Image i;
        VkImageCreateInfo info{.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
            .imageType = VK_IMAGE_TYPE_2D, .format = format, .extent = {w, h, 1},
            .mipLevels = 1, .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT,
            .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = VK_IMAGE_USAGE_SAMPLED_BIT |
                VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT};
        CHECK(vkCreateImage(device, &info, nullptr, &i.image));
        VkMemoryRequirements req;
        vkGetImageMemoryRequirements(device, i.image, &req);
        VkMemoryAllocateInfo alloc{.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
            .allocationSize = req.size, .memoryTypeIndex = Memory(req.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)};
        CHECK(vkAllocateMemory(device, &alloc, nullptr, &i.memory));
        CHECK(vkBindImageMemory(device, i.image, i.memory, 0));
        VkImageViewCreateInfo view{.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
            .image = i.image, .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = format,
            .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
        CHECK(vkCreateImageView(device, &view, nullptr, &i.view));
        return i;
    }
    Pipeline MakePipeline(std::initializer_list<VkDescriptorType> types, unsigned push_bytes,
                          const std::uint32_t* code, std::size_t code_bytes, VkPipelineCreateFlags create_flags = 0) {
        Pipeline p;
        std::vector<VkDescriptorSetLayoutBinding> bindings;
        for (const auto type : types)
            bindings.push_back({unsigned(bindings.size()), type, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr});
        VkDescriptorSetLayoutCreateInfo si{.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
            .flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR,
            .bindingCount = unsigned(bindings.size()), .pBindings = bindings.data()};
        CHECK(vkCreateDescriptorSetLayout(device, &si, nullptr, &p.set));
        VkPushConstantRange range{VK_SHADER_STAGE_COMPUTE_BIT, 0, push_bytes};
        VkPipelineLayoutCreateInfo li{.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
            .setLayoutCount = 1, .pSetLayouts = &p.set, .pushConstantRangeCount = 1, .pPushConstantRanges = &range};
        CHECK(vkCreatePipelineLayout(device, &li, nullptr, &p.layout));
        VkShaderModule module;
        VkShaderModuleCreateInfo mi{.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = code_bytes, .pCode = code};
        CHECK(vkCreateShaderModule(device, &mi, nullptr, &module));
        VkComputePipelineCreateInfo pc{.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
            .flags = create_flags, .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
                .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = module, .pName = "main"}, .layout = p.layout};
        CHECK(vkCreateComputePipelines(device, {}, 1, &pc, nullptr, &p.pipeline));
        vkDestroyShaderModule(device, module, nullptr);
        return p;
    }
    Vk() {
        VkApplicationInfo app{.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
            .pApplicationName = "rt-shadow-test", .apiVersion = VK_API_VERSION_1_3};
        VkInstanceCreateInfo ci{.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app};
        CHECK(vkCreateInstance(&ci, nullptr, &instance));
        unsigned count = 0;
        CHECK(vkEnumeratePhysicalDevices(instance, &count, nullptr));
        std::vector<VkPhysicalDevice> devices(count);
        CHECK(vkEnumeratePhysicalDevices(instance, &count, devices.data()));
        gpu = devices.at(0);
        for (const auto candidate : devices) {
            VkPhysicalDeviceProperties p;
            vkGetPhysicalDeviceProperties(candidate, &p);
            if (p.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU) { gpu = candidate; break; }
        }
        vkGetPhysicalDeviceMemoryProperties(gpu, &memory);
        VkPhysicalDeviceProperties properties{};
        vkGetPhysicalDeviceProperties(gpu, &properties);
        std::strncpy(name, properties.deviceName, sizeof(name) - 1);
        period = properties.limits.timestampPeriod;
        unsigned family_count = 0, family = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(gpu, &family_count, nullptr);
        std::vector<VkQueueFamilyProperties> families(family_count);
        vkGetPhysicalDeviceQueueFamilyProperties(gpu, &family_count, families.data());
        while (family < family_count && !(families[family].queueFlags & VK_QUEUE_COMPUTE_BIT)) ++family;
        if (families[family].timestampValidBits < 64) mask = (std::uint64_t{1} << families[family].timestampValidBits) - 1;
        const float priority = 1;
        VkDeviceQueueCreateInfo qi{.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
            .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority};
        const std::array<const char*, 4> extensions{
            VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME, VK_KHR_ACCELERATION_STRUCTURE_EXTENSION_NAME,
            VK_KHR_DEFERRED_HOST_OPERATIONS_EXTENSION_NAME, VK_KHR_RAY_QUERY_EXTENSION_NAME};
        VkPhysicalDeviceRayQueryFeaturesKHR rq{.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_RAY_QUERY_FEATURES_KHR, .rayQuery = VK_TRUE};
        VkPhysicalDeviceAccelerationStructureFeaturesKHR as{.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ACCELERATION_STRUCTURE_FEATURES_KHR,
            .pNext = &rq, .accelerationStructure = VK_TRUE};
        VkPhysicalDeviceVulkan12Features v12{.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES,
            .pNext = &as, .scalarBlockLayout = VK_TRUE, .bufferDeviceAddress = VK_TRUE};
        VkPhysicalDeviceFeatures2 f2{.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext = &v12};
        f2.features.shaderStorageImageExtendedFormats = VK_TRUE;
        VkDeviceCreateInfo di{.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .pNext = &f2,
            .queueCreateInfoCount = 1, .pQueueCreateInfos = &qi,
            .enabledExtensionCount = unsigned(extensions.size()), .ppEnabledExtensionNames = extensions.data()};
        CHECK(vkCreateDevice(gpu, &di, nullptr, &device));
        vkGetDeviceQueue(device, family, 0, &queue);
#define LOAD(field, type, fn) field = reinterpret_cast<type>(vkGetDeviceProcAddr(device, fn))
        LOAD(push, PFN_vkCmdPushDescriptorSetKHR, "vkCmdPushDescriptorSetKHR");
        LOAD(create_as, PFN_vkCreateAccelerationStructureKHR, "vkCreateAccelerationStructureKHR");
        LOAD(sizes, PFN_vkGetAccelerationStructureBuildSizesKHR, "vkGetAccelerationStructureBuildSizesKHR");
        LOAD(build, PFN_vkCmdBuildAccelerationStructuresKHR, "vkCmdBuildAccelerationStructuresKHR");
        LOAD(as_address, PFN_vkGetAccelerationStructureDeviceAddressKHR, "vkGetAccelerationStructureDeviceAddressKHR");
        LOAD(write_props, PFN_vkCmdWriteAccelerationStructuresPropertiesKHR, "vkCmdWriteAccelerationStructuresPropertiesKHR");
        LOAD(destroy_as, PFN_vkDestroyAccelerationStructureKHR, "vkDestroyAccelerationStructureKHR");
#undef LOAD
        VkCommandPoolCreateInfo pi{.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
            .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, .queueFamilyIndex = family};
        CHECK(vkCreateCommandPool(device, &pi, nullptr, &pool));
        VkCommandBufferAllocateInfo ai{.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
            .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
        CHECK(vkAllocateCommandBuffers(device, &ai, &cmd));
        VkQueryPoolCreateInfo query{.sType = VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,
            .queryType = VK_QUERY_TYPE_TIMESTAMP, .queryCount = 2};
        CHECK(vkCreateQueryPool(device, &query, nullptr, &stamps));
        VkSamplerCreateInfo sm{.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO,
            .magFilter = VK_FILTER_NEAREST, .minFilter = VK_FILTER_NEAREST,
            .addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
            .addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
            .addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE};
        CHECK(vkCreateSampler(device, &sm, nullptr, &sampler));
    }
    void Begin() {
        CHECK(vkResetCommandBuffer(cmd, 0));
        VkCommandBufferBeginInfo begin{.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
        CHECK(vkBeginCommandBuffer(cmd, &begin));
        vkCmdResetQueryPool(cmd, stamps, 0, 2);
    }
    void Stamp(unsigned i) { vkCmdWriteTimestamp(cmd, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, stamps, i); }
    void Barrier() {
        VkMemoryBarrier b{.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_MEMORY_WRITE_BIT, .dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT};
        vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 1, &b, 0, nullptr, 0, nullptr);
    }
    void ToGeneral(VkImage image) {
        VkImageMemoryBarrier b{.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            .srcAccessMask = 0, .dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT,
            .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED, .newLayout = VK_IMAGE_LAYOUT_GENERAL,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = image, .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
        vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 0, nullptr, 0, nullptr, 1, &b);
    }
    double End() {
        CHECK(vkEndCommandBuffer(cmd));
        VkSubmitInfo submit{.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cmd};
        CHECK(vkQueueSubmit(queue, 1, &submit, {}));
        CHECK(vkQueueWaitIdle(queue));
        std::array<std::uint64_t, 2> t{};
        const VkResult r = vkGetQueryPoolResults(device, stamps, 0, 2, sizeof t, t.data(), sizeof(std::uint64_t),
                                                 VK_QUERY_RESULT_64_BIT);
        return r == VK_SUCCESS ? double((t[1] - t[0]) & mask) * period / 1e6 : 0.0;
    }
};

struct Blas {
    VkAccelerationStructureKHR handle{};
    VkDeviceAddress address{};
    VkDeviceSize offset{}, bytes{}, scratch{}, update_scratch{};
    unsigned triangles{}, vertices{};
    VkDeviceSize vertex_offset{}, index_offset{};
};

struct Scene {
    Vk& vk;
    std::vector<Mesh> meshes;
    Buffer geometry{}, staging{}, storage{}, scratch{};
    std::vector<Blas> blas;
    VkDeviceSize total_bytes = 0, total_scratch = 0;
    unsigned triangles = 0;

    VkAccelerationStructureGeometryKHR Geometry(const Blas& b) const {
        VkAccelerationStructureGeometryKHR g{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_KHR,
            .geometryType = VK_GEOMETRY_TYPE_TRIANGLES_KHR, .flags = VK_GEOMETRY_OPAQUE_BIT_KHR};
        g.geometry.triangles = {.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_TRIANGLES_DATA_KHR,
            .vertexFormat = VK_FORMAT_R32G32B32_SFLOAT, .vertexStride = sizeof(Vec3),
            .maxVertex = b.vertices - 1, .indexType = VK_INDEX_TYPE_UINT32};
        g.geometry.triangles.vertexData.deviceAddress = geometry.address + b.vertex_offset;
        g.geometry.triangles.indexData.deviceAddress = geometry.address + b.index_offset;
        return g;
    }
    void Create(VkBuildAccelerationStructureFlagsKHR flags) {
        const VkDeviceSize alignment = 16;
        VkDeviceSize bytes = 0;
        blas.resize(meshes.size());
        for (std::size_t i = 0; i < meshes.size(); ++i) {
            blas[i].vertex_offset = bytes;
            bytes += (meshes[i].vertices.size() * sizeof(Vec3) + alignment - 1) & ~(alignment - 1);
            blas[i].index_offset = bytes;
            bytes += (meshes[i].indices.size() * 4 + alignment - 1) & ~(alignment - 1);
            blas[i].vertices = unsigned(meshes[i].vertices.size());
            blas[i].triangles = unsigned(meshes[i].indices.size() / 3);
            triangles += blas[i].triangles;
        }
        staging = vk.MakeBuffer(bytes, 0, true);
        for (std::size_t i = 0; i < meshes.size(); ++i) {
            std::memcpy(static_cast<char*>(staging.data) + blas[i].vertex_offset, meshes[i].vertices.data(), meshes[i].vertices.size() * sizeof(Vec3));
            std::memcpy(static_cast<char*>(staging.data) + blas[i].index_offset, meshes[i].indices.data(), meshes[i].indices.size() * 4);
        }
        geometry = vk.MakeBuffer(bytes, VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_BUILD_INPUT_READ_ONLY_BIT_KHR, false);
        vk.Begin();
        VkBufferCopy copy{0, 0, bytes};
        vkCmdCopyBuffer(vk.cmd, staging.buffer, geometry.buffer, 1, &copy);
        vk.Barrier();
        vk.Stamp(0); vk.Stamp(1);
        vk.End();
        Sizes(flags);
    }
    void Sizes(VkBuildAccelerationStructureFlagsKHR flags) {
        total_bytes = total_scratch = 0;
        for (auto& b : blas) {
            const auto g = Geometry(b);
            VkAccelerationStructureBuildGeometryInfoKHR info{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_GEOMETRY_INFO_KHR,
                .type = VK_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL_KHR, .flags = flags,
                .mode = VK_BUILD_ACCELERATION_STRUCTURE_MODE_BUILD_KHR, .geometryCount = 1, .pGeometries = &g};
            VkAccelerationStructureBuildSizesInfoKHR s{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_SIZES_INFO_KHR};
            vk.sizes(vk.device, VK_ACCELERATION_STRUCTURE_BUILD_TYPE_DEVICE_KHR, &info, &b.triangles, &s);
            b.offset = total_bytes;
            b.bytes = s.accelerationStructureSize;
            b.scratch = s.buildScratchSize;
            b.update_scratch = s.updateScratchSize;
            total_bytes += (s.accelerationStructureSize + AsAlign - 1) & ~(AsAlign - 1);
            total_scratch += (std::max(s.buildScratchSize, s.updateScratchSize) + AsAlign - 1) & ~(AsAlign - 1);
        }
    }
    void Allocate() {
        for (auto& b : blas) if (b.handle) { vk.destroy_as(vk.device, b.handle, nullptr); b.handle = {}; }
        vk.Free(storage);
        vk.Free(scratch);
        storage = vk.MakeBuffer(total_bytes, VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_STORAGE_BIT_KHR, false);
        scratch = vk.MakeBuffer(total_scratch, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, false);
        for (auto& b : blas) {
            VkAccelerationStructureCreateInfoKHR ci{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_CREATE_INFO_KHR,
                .buffer = storage.buffer, .offset = b.offset, .size = b.bytes,
                .type = VK_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL_KHR};
            CHECK(vk.create_as(vk.device, &ci, nullptr, &b.handle));
            VkAccelerationStructureDeviceAddressInfoKHR ai{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_DEVICE_ADDRESS_INFO_KHR, .accelerationStructure = b.handle};
            b.address = vk.as_address(vk.device, &ai);
        }
    }
    double BuildAll(VkBuildAccelerationStructureFlagsKHR flags) {
        std::vector<VkAccelerationStructureGeometryKHR> geometries;
        geometries.reserve(blas.size());
        std::vector<VkAccelerationStructureBuildGeometryInfoKHR> infos;
        std::vector<VkAccelerationStructureBuildRangeInfoKHR> ranges;
        std::vector<const VkAccelerationStructureBuildRangeInfoKHR*> pointers;
        VkDeviceSize at = 0;
        for (auto& b : blas) {
            geometries.push_back(Geometry(b));
            VkAccelerationStructureBuildGeometryInfoKHR info{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_GEOMETRY_INFO_KHR,
                .type = VK_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL_KHR, .flags = flags,
                .mode = VK_BUILD_ACCELERATION_STRUCTURE_MODE_BUILD_KHR, .dstAccelerationStructure = b.handle,
                .geometryCount = 1, .pGeometries = &geometries.back()};
            info.scratchData.deviceAddress = scratch.address + at;
            at += (std::max(b.scratch, b.update_scratch) + AsAlign - 1) & ~(AsAlign - 1);
            infos.push_back(info);
            ranges.push_back({b.triangles, 0, 0, 0});
        }
        for (auto& r : ranges) pointers.push_back(&r);
        vk.Begin();
        vk.Stamp(0);
        vk.build(vk.cmd, unsigned(infos.size()), infos.data(), pointers.data());
        vk.Stamp(1);
        vk.Barrier();
        return vk.End();
    }
    double Refit(VkBuildAccelerationStructureFlagsKHR flags, bool update) {
        std::vector<VkAccelerationStructureGeometryKHR> geometries;
        geometries.reserve(blas.size());
        std::vector<VkAccelerationStructureBuildGeometryInfoKHR> infos;
        std::vector<VkAccelerationStructureBuildRangeInfoKHR> ranges;
        std::vector<const VkAccelerationStructureBuildRangeInfoKHR*> pointers;
        VkDeviceSize at = 0;
        ranges.reserve(blas.size());
        for (std::size_t i = 0; i < blas.size(); ++i) {
            auto& b = blas[i];
            const VkDeviceSize scratch_at = at;
            at += (std::max(b.scratch, b.update_scratch) + AsAlign - 1) & ~(AsAlign - 1);
            if (!meshes[i].skinned) continue;
            geometries.push_back(Geometry(b));
            VkAccelerationStructureBuildGeometryInfoKHR info{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_GEOMETRY_INFO_KHR,
                .type = VK_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL_KHR, .flags = flags,
                .mode = update ? VK_BUILD_ACCELERATION_STRUCTURE_MODE_UPDATE_KHR : VK_BUILD_ACCELERATION_STRUCTURE_MODE_BUILD_KHR,
                .srcAccelerationStructure = update ? b.handle : VK_NULL_HANDLE, .dstAccelerationStructure = b.handle,
                .geometryCount = 1, .pGeometries = &geometries.back()};
            info.scratchData.deviceAddress = scratch.address + scratch_at;
            infos.push_back(info);
            ranges.push_back({b.triangles, 0, 0, 0});
            pointers.push_back(&ranges.back());
        }
        vk.Begin();
        vk.Stamp(0);
        vk.build(vk.cmd, unsigned(infos.size()), infos.data(), pointers.data());
        vk.Stamp(1);
        vk.Barrier();
        return vk.End();
    }
};

struct Tlas {
    VkAccelerationStructureKHR handle{};
    Buffer instances{}, storage{}, scratch{};
    unsigned count = 0;
};

double Median(std::vector<double> v) {
    std::sort(v.begin(), v.end());
    return v[v.size() / 2];
}

void WriteTlasInstances(Tlas& t, const Scene& scene, const Mat4& view) {
    auto* out = static_cast<VkAccelerationStructureInstanceKHR*>(t.instances.data);
    for (std::size_t i = 0; i < scene.blas.size(); ++i) {
        Mat4 model = Identity();
        model.at(0, 3) = scene.meshes[i].position.x;
        model.at(1, 3) = scene.meshes[i].position.y;
        model.at(2, 3) = scene.meshes[i].position.z;
        const Mat4 m = view * model;
        VkAccelerationStructureInstanceKHR inst{};
        std::memcpy(inst.transform.matrix, m.m.data(), 12 * sizeof(float));
        inst.mask = 0xff;
        inst.accelerationStructureReference = scene.blas[i].address;
        out[i] = inst;
    }
}

double BuildTlas(Vk& vk, Tlas& t, const Scene& scene, const Mat4& view, bool time_upload) {
    if (time_upload || !t.handle) WriteTlasInstances(t, scene, view);
    VkAccelerationStructureGeometryKHR g{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_KHR,
        .geometryType = VK_GEOMETRY_TYPE_INSTANCES_KHR, .flags = VK_GEOMETRY_OPAQUE_BIT_KHR};
    g.geometry.instances = {.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_INSTANCES_DATA_KHR};
    g.geometry.instances.data.deviceAddress = t.instances.address;
    VkAccelerationStructureBuildGeometryInfoKHR info{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_GEOMETRY_INFO_KHR,
        .type = VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR, .flags = VK_BUILD_ACCELERATION_STRUCTURE_PREFER_FAST_BUILD_BIT_KHR,
        .mode = VK_BUILD_ACCELERATION_STRUCTURE_MODE_BUILD_KHR, .dstAccelerationStructure = t.handle,
        .geometryCount = 1, .pGeometries = &g};
    info.scratchData.deviceAddress = t.scratch.address;
    VkAccelerationStructureBuildRangeInfoKHR range{t.count, 0, 0, 0};
    const VkAccelerationStructureBuildRangeInfoKHR* pointer = &range;
    vk.Begin();
    vk.Stamp(0);
    vk.build(vk.cmd, 1, &info, &pointer);
    vk.Stamp(1);
    vk.Barrier();
    return vk.End();
}

Tlas CreateTlas(Vk& vk, const Scene& scene) {
    Tlas t;
    t.count = unsigned(scene.blas.size());
    t.instances = vk.MakeBuffer(t.count * sizeof(VkAccelerationStructureInstanceKHR),
                                VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_BUILD_INPUT_READ_ONLY_BIT_KHR, true);
    VkAccelerationStructureGeometryKHR g{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_KHR,
        .geometryType = VK_GEOMETRY_TYPE_INSTANCES_KHR, .flags = VK_GEOMETRY_OPAQUE_BIT_KHR};
    g.geometry.instances = {.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_INSTANCES_DATA_KHR};
    VkAccelerationStructureBuildGeometryInfoKHR info{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_GEOMETRY_INFO_KHR,
        .type = VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR, .flags = VK_BUILD_ACCELERATION_STRUCTURE_PREFER_FAST_BUILD_BIT_KHR,
        .mode = VK_BUILD_ACCELERATION_STRUCTURE_MODE_BUILD_KHR, .geometryCount = 1, .pGeometries = &g};
    VkAccelerationStructureBuildSizesInfoKHR s{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_SIZES_INFO_KHR};
    vk.sizes(vk.device, VK_ACCELERATION_STRUCTURE_BUILD_TYPE_DEVICE_KHR, &info, &t.count, &s);
    t.storage = vk.MakeBuffer(s.accelerationStructureSize, VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_STORAGE_BIT_KHR, false);
    t.scratch = vk.MakeBuffer(s.buildScratchSize + AsAlign, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, false);
    VkAccelerationStructureCreateInfoKHR ci{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_CREATE_INFO_KHR,
        .buffer = t.storage.buffer, .size = s.accelerationStructureSize, .type = VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR};
    CHECK(vk.create_as(vk.device, &ci, nullptr, &t.handle));
    return t;
}

struct Views {
    Mat4 view, proj, inv_proj;
    std::array<Mat4, 4> cascade, cascade_inverse;
    std::array<float, 3> splits{};
};

Views MakeViews(Vec3 eye, Vec3 forward, Vec3 sun) {
    Views v;
    v.view = LookTo(eye, forward);
    const float fy = 1.0f / std::tan(0.5f * 0.87f), fx = fy * H / W, near = 0.1f, far = 3000.0f;
    v.proj.at(0, 0) = fx; v.proj.at(1, 1) = fy;
    v.proj.at(2, 2) = far / (far - near); v.proj.at(2, 3) = -near * far / (far - near);
    v.proj.at(3, 2) = 1;
    v.inv_proj = Inverse(v.proj);
    v.splits = {8, 25, 80};
    const std::array<float, 4> half{8, 22, 60, 170};
    const std::array<float, 4> centers{4, 16, 50, 150};
    const Mat4 inv_view = Inverse(v.view);
    for (int c = 0; c < 4; ++c) {
        const Vec3 center = eye + Norm(forward) * centers[c];
        const Mat4 light = LookTo(center + sun * 300.0f, sun * -1.0f);
        Mat4 ortho = Identity();
        ortho.at(0, 0) = 1.0f / half[c]; ortho.at(1, 1) = 1.0f / half[c];
        ortho.at(2, 2) = 1.0f / 800.0f;
        Mat4 tile = Identity();
        tile.at(0, 0) = 0.25f; tile.at(0, 3) = 0.25f + 0.5f * float(c & 1);
        tile.at(1, 1) = 0.25f; tile.at(1, 3) = 0.25f + 0.5f * float(c >> 1);
        const Mat4 view_to_atlas = tile * ortho * light * inv_view;
        v.cascade_inverse[c] = Inverse(view_to_atlas);
        v.cascade[c] = view_to_atlas * v.inv_proj;
    }
    return v;
}

struct Metric { double mean{}, off10{}, off25{}, signed_bias{}; };
Metric Compare(const std::vector<float>& reference, const std::vector<float>& value, const std::vector<float>& depth) {
    Metric m;
    std::size_t counted = 0;
    for (std::size_t i = 0; i < reference.size(); ++i) {
        if (!(depth[i] < 1.0f)) continue;
        const double d = double(value[i]) - reference[i];
        m.mean += std::abs(d);
        m.signed_bias += d;
        m.off10 += std::abs(d) > 0.1;
        m.off25 += std::abs(d) > 0.25;
        ++counted;
    }
    counted = std::max<std::size_t>(counted, 1);
    m.mean /= counted; m.signed_bias /= counted;
    m.off10 *= 100.0 / counted; m.off25 *= 100.0 / counted;
    return m;
}

void WritePgm(const char* path, const std::vector<float>& image) {
    std::ofstream out(path, std::ios::binary);
    out << "P5\n" << W << ' ' << H << "\n255\n";
    std::vector<unsigned char> bytes(image.size());
    for (std::size_t i = 0; i < image.size(); ++i) bytes[i] = (unsigned char)(std::clamp(image[i], 0.0f, 1.0f) * 255.0f + 0.5f);
    out.write(reinterpret_cast<const char*>(bytes.data()), std::streamsize(bytes.size()));
}

struct PcssPush {
    unsigned offsets = 0, frame = 0;
    float width = W, height = H, length = 0.6f, thickness = 0.35f, strength = 0.75f, flip = 1;
    unsigned debug = 0, contact = 0, pcss = 1;
    float light = 0.02f, maximum = 0.3f, minimum = 0.0f, bias = 0.04f;
    unsigned filter = 1;
    float blend = 0.1f;
};
static_assert(sizeof(PcssPush) == 68);
struct RtPush {
    unsigned offsets = 0, frame = 0;
    float width = W, height = H;
    unsigned rays = 1;
    float light = 0.02f, bias = 0.01f, distance = 500.0f;
};
static_assert(sizeof(RtPush) == 32);
struct FilterPush {
    unsigned offsets = 0;
    int radius = 2;
    float width = W, height = H;
};
struct LabPush {
    Mat4 to_view;
    float width, height, min_x, min_y, max_x, max_y;
    unsigned perspective;
};

struct Lab {
    Vk& vk;
    Pipeline lab, rt, filter, pcss;
    Buffer cb, ub, readback;
    Image depth, atlas, raw, shadow;
    bool laid_out = false;

    explicit Lab(Vk& v) : vk(v) {
        using enum VkDescriptorType;
        lab = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR}, sizeof(LabPush), RT_LAB_COMP, sizeof(RT_LAB_COMP));
        rt = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR}, sizeof(RtPush), RT_SHADOW_COMP, sizeof(RT_SHADOW_COMP));
        filter = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER}, sizeof(FilterPush), RT_SHADOW_FILTER_COMP, sizeof(RT_SHADOW_FILTER_COMP));
        pcss = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER}, sizeof(PcssPush), CONTACT_SHADOW_COMP, sizeof(CONTACT_SHADOW_COMP));
        cb = vk.MakeBuffer(4096, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, true);
        ub = vk.MakeBuffer(4096, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, true);
        readback = vk.MakeBuffer(W * H * 4, 0, true);
        depth = vk.MakeImage(W, H, VK_FORMAT_R32_SFLOAT);
        atlas = vk.MakeImage(Atlas, Atlas, VK_FORMAT_R32_SFLOAT);
        raw = vk.MakeImage(W, H, VK_FORMAT_R8_UNORM);
        shadow = vk.MakeImage(W, H, VK_FORMAT_R8G8B8A8_UNORM);
        auto* u = static_cast<float*>(ub.data);
        u[72] = 2000; u[73] = 1;
    }
    void LayOut() {
        if (laid_out) return;
        laid_out = true;
        for (auto image : {depth.image, atlas.image, raw.image, shadow.image}) vk.ToGeneral(image);
    }
    void SetCamera(const Views& v) {
        auto* c = static_cast<float*>(cb.data);
        for (int r = 0; r < 4; ++r)
            for (int k = 0; k < 4; ++k) {
                c[r * 4 + k] = v.inv_proj.at(r, k);
                for (int cascade = 0; cascade < 4; ++cascade)
                    c[16 + 16 * cascade + r * 4 + k] = v.cascade[cascade].at(r, k);
            }
        c[80] = v.splits[0]; c[81] = v.splits[1]; c[82] = v.splits[2];
    }
    void Lab1(VkAccelerationStructureKHR tlas, Image& target, const Mat4& to_view, float w, float h, std::array<float, 4> region, bool perspective) {
        VkDescriptorImageInfo image{{}, target.view, VK_IMAGE_LAYOUT_GENERAL};
        VkWriteDescriptorSetAccelerationStructureKHR as{.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET_ACCELERATION_STRUCTURE_KHR,
            .accelerationStructureCount = 1, .pAccelerationStructures = &tlas};
        const std::array<VkWriteDescriptorSet, 2> writes{{
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 0, .descriptorCount = 1,
             .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &image},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .pNext = &as, .dstBinding = 1, .descriptorCount = 1,
             .descriptorType = VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR}}};
        LabPush push{to_view, w, h, region[0], region[1], region[2], region[3], perspective ? 1u : 0u};
        vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lab.pipeline);
        vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lab.layout, 0, 2, writes.data());
        vkCmdPushConstants(vk.cmd, lab.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
        vkCmdDispatch(vk.cmd, (unsigned(w) + 7) / 8, (unsigned(h) + 7) / 8, 1);
        vk.Barrier();
    }
    void Prepare(VkAccelerationStructureKHR tlas, const Views& v) {
        SetCamera(v);
        vk.Begin();
        LayOut();
        vk.Barrier();
        Lab1(tlas, depth, v.inv_proj, W, H, {0, 0, 1, 1}, true);
        for (int c = 0; c < 4; ++c) {
            const float x = 0.5f * float(c & 1), y = 0.5f * float(c >> 1);
            Lab1(tlas, atlas, v.cascade_inverse[c], Atlas, Atlas, {x, y, x + 0.5f, y + 0.5f}, false);
        }
        vk.Stamp(0); vk.Stamp(1);
        vk.End();
    }
    void Rt(VkAccelerationStructureKHR tlas, RtPush p) {
        VkDescriptorBufferInfo c{cb.buffer, 0, 4096};
        VkDescriptorImageInfo d{vk.sampler, depth.view, VK_IMAGE_LAYOUT_GENERAL}, r{{}, raw.view, VK_IMAGE_LAYOUT_GENERAL};
        VkWriteDescriptorSetAccelerationStructureKHR as{.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET_ACCELERATION_STRUCTURE_KHR,
            .accelerationStructureCount = 1, .pAccelerationStructures = &tlas};
        const std::array<VkWriteDescriptorSet, 4> writes{{
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 0, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &c},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 1, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &d},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 2, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &r},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .pNext = &as, .dstBinding = 3, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR}}};
        vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, rt.pipeline);
        vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, rt.layout, 0, 4, writes.data());
        vkCmdPushConstants(vk.cmd, rt.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(p), &p);
        vkCmdDispatch(vk.cmd, (W + 7) / 8, (H + 7) / 8, 1);
    }
    void Filter(int radius) {
        VkDescriptorBufferInfo c{cb.buffer, 0, 4096}, u{ub.buffer, 0, 4096};
        VkDescriptorImageInfo d{vk.sampler, depth.view, VK_IMAGE_LAYOUT_GENERAL}, r{vk.sampler, raw.view, VK_IMAGE_LAYOUT_GENERAL}, s{{}, shadow.view, VK_IMAGE_LAYOUT_GENERAL};
        const std::array<VkWriteDescriptorSet, 5> writes{{
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 0, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &c},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 1, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &d},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 2, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &r},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 3, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &s},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 4, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &u}}};
        FilterPush p;
        p.radius = radius;
        vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, filter.pipeline);
        vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, filter.layout, 0, 5, writes.data());
        vkCmdPushConstants(vk.cmd, filter.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(p), &p);
        vkCmdDispatch(vk.cmd, (W + 7) / 8, (H + 7) / 8, 1);
    }
    void Pcss(PcssPush p) {
        VkDescriptorBufferInfo c{cb.buffer, 0, 4096}, u{ub.buffer, 0, 4096};
        VkDescriptorImageInfo d{vk.sampler, depth.view, VK_IMAGE_LAYOUT_GENERAL}, m{vk.sampler, atlas.view, VK_IMAGE_LAYOUT_GENERAL}, s{{}, shadow.view, VK_IMAGE_LAYOUT_GENERAL};
        const std::array<VkWriteDescriptorSet, 5> writes{{
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 0, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &c},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 1, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &d},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 2, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &s},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 3, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &m},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 4, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &u}}};
        vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pcss.pipeline);
        vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pcss.layout, 0, 5, writes.data());
        vkCmdPushConstants(vk.cmd, pcss.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(p), &p);
        vkCmdDispatch(vk.cmd, (W + 7) / 8, (H + 7) / 8, 1);
    }
    std::vector<float> Read(Image& image, VkFormat format) {
        vk.Begin();
        vk.Barrier();
        VkBufferImageCopy copy{.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .imageExtent = {W, H, 1}};
        vkCmdCopyImageToBuffer(vk.cmd, image.image, VK_IMAGE_LAYOUT_GENERAL, readback.buffer, 1, &copy);
        vk.Barrier();
        vk.Stamp(0); vk.Stamp(1);
        vk.End();
        std::vector<float> out(W * H);
        const auto* bytes = static_cast<const unsigned char*>(readback.data);
        for (std::size_t i = 0; i < out.size(); ++i) {
            if (format == VK_FORMAT_R32_SFLOAT) std::memcpy(&out[i], bytes + i * 4, 4);
            else if (format == VK_FORMAT_R8_UNORM) out[i] = bytes[i] / 255.0f;
            else out[i] = bytes[i * 4 + 3] / 255.0f;
        }
        return out;
    }
    void ClearShadow() {
        VkClearColorValue color{};
        color.float32[0] = color.float32[1] = color.float32[2] = color.float32[3] = 1;
        VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
        vkCmdClearColorImage(vk.cmd, shadow.image, VK_IMAGE_LAYOUT_GENERAL, &color, 1, &range);
        vk.Barrier();
    }
};

// bbport (r47_still-check): --still: rt_still_sig.comp and rt_unproject.comp in the order
// RtShadow::RecordBuilds runs them (slots zeroed, bounds from the positions as the captures
// stored them, copy to the host, then to world space), on two meshes in one positions buffer.
// Each mesh's vertex range also holds vertices no triangle uses, filled as an earlier frame's
// capture would leave them, differently on every run. The signature the GPU writes must be the
// one rt_still_check.h makes of the vertices the triangles use, word for word; so a mesh
// captured again in place differs by nothing and a moved one by its move, whatever lies in the
// unused vertices. Then a mesh that stands still far from a perspective camera, captured under
// two poses of that camera: its bounds must not differ (the scene's own positions, made with
// one product, differ by more than the tolerance there).
bool StillLab(Vk& vk) {
    struct Unproject { float rows[12]; std::uint32_t first, count; };
    struct Sign { float rows[12]; float origin[3]; std::uint32_t first; std::uint64_t indices; std::uint32_t count, slot; };
    static_assert(sizeof(Unproject) == 56 && sizeof(Sign) == 80);
    // What takes a mesh's stored positions to the world: for the signature (two parts) and for
    // rt_unproject.comp (one product).
    struct Place { std::array<float, 12> rows{}; std::array<float, 3> origin{}; std::array<float, 12> product{}; };
    constexpr std::uint32_t Range = 600, Meshes = 2, Slots = 4, Words = Vulkan::StillSigWords;
    const Pipeline unproject = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER}, sizeof(Unproject), RT_UNPROJECT_COMP, sizeof(RT_UNPROJECT_COMP));
    const Pipeline sign = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER}, sizeof(Sign), RT_STILL_SIG_COMP, sizeof(RT_STILL_SIG_COMP));
    Buffer positions = vk.MakeBuffer(Meshes * Range * 16, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, true);
    Buffer sigs = vk.MakeBuffer(Slots * Words * 4, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, false);
    Buffer readback = vk.MakeBuffer(Slots * Words * 4, 0, true);
    // The triangles leave out every seventh vertex and the last hundred of the range.
    const auto unused = [](std::uint32_t v) { return v % 7 == 3 || v >= Range - 100; };
    std::vector<std::uint32_t> used, list;
    for (std::uint32_t v = 0; v < Range; ++v)
        if (!unused(v)) used.push_back(v);
    for (std::size_t i = 0; i + 2 < used.size(); ++i) list.insert(list.end(), {used[i], used[i + 1], used[i + 2]});
    Buffer indices = vk.MakeBuffer(list.size() * 4, 0, true);
    std::memcpy(indices.data, list.data(), list.size() * 4);
    std::mt19937 rng(47);
    std::uniform_real_distribution<float> coord(-2.0f, 2.0f);
    std::vector<float> local(Meshes * Range * 3);
    for (float& c : local) c = coord(rng);
    const float nan = std::numeric_limits<float>::quiet_NaN();
    bool ok = true;
    using Words8 = std::array<std::uint32_t, Words>;
    // One frame's commands over what the positions buffer holds: the GPU's signatures of the
    // two meshes and of a slot nothing writes to. Afterwards the positions are in world space.
    const auto run = [&](const std::array<Place, Meshes>& place) {
        vk.Begin();
        vkCmdFillBuffer(vk.cmd, sigs.buffer, 0, VK_WHOLE_SIZE, 0);
        vk.Barrier();
        const VkDescriptorBufferInfo position_info{positions.buffer, 0, VK_WHOLE_SIZE}, sig_info{sigs.buffer, 0, VK_WHOLE_SIZE};
        const std::array<VkWriteDescriptorSet, 2> writes{{
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 0, .descriptorCount = 1,
             .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &position_info},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 1, .descriptorCount = 1,
             .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &sig_info}}};
        vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, sign.pipeline);
        vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, sign.layout, 0, 2, writes.data());
        for (std::uint32_t m = 0; m < Meshes; ++m) {
            Sign push{{}, {}, m * Range, indices.address, std::uint32_t(list.size()), m};
            std::memcpy(push.rows, place[m].rows.data(), sizeof(push.rows));
            std::memcpy(push.origin, place[m].origin.data(), sizeof(push.origin));
            vkCmdPushConstants(vk.cmd, sign.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
            vkCmdDispatch(vk.cmd, (push.count + 63) / 64, 1, 1);
        }
        vk.Barrier();
        const VkBufferCopy copy{0, 0, Slots * Words * 4};
        vkCmdCopyBuffer(vk.cmd, sigs.buffer, readback.buffer, 1, &copy);
        vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, unproject.pipeline);
        vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, unproject.layout, 0, 1, writes.data());
        for (std::uint32_t m = 0; m < Meshes; ++m) {
            Unproject push{{}, m * Range, Range};
            std::memcpy(push.rows, place[m].product.data(), sizeof(push.rows));
            vkCmdPushConstants(vk.cmd, unproject.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
            vkCmdDispatch(vk.cmd, (Range + 63) / 64, 1, 1);
        }
        vk.Barrier();
        vk.End();
        std::array<Words8, Meshes + 1> got{};
        std::memcpy(got.data(), readback.data, sizeof(got));
        return got;
    };
    // One capture of both meshes, each moved by its shift; `junk` is what the unused vertices
    // hold; `broken`: a vertex the second mesh's triangles use is not a number. The bounds, or
    // none where the signature holds none.
    const auto capture = [&](const std::array<Vec3, Meshes>& shift, float junk, bool broken) {
        auto* p = static_cast<float*>(positions.data);
        std::array<Words8, Meshes> want{};
        std::array<Place, Meshes> place{};
        for (std::uint32_t m = 0; m < Meshes; ++m) {
            place[m].rows = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
            place[m].origin = {shift[m].x, shift[m].y, shift[m].z};
            place[m].product = {1, 0, 0, shift[m].x, 0, 1, 0, shift[m].y, 0, 0, 1, shift[m].z};
            for (std::uint32_t v = 0; v < Range; ++v) {
                const float* l = &local[(m * Range + v) * 3];
                float* at = p + (m * Range + v) * 4;
                at[0] = unused(v) ? junk * float(v + 1) : l[0];
                at[1] = unused(v) ? -junk : l[1];
                at[2] = unused(v) ? (v % 2 ? nan : junk) : l[2];
                at[3] = 1.0f;
            }
            if (broken && m == 1) p[(m * Range + used[5]) * 4 + 1] = nan;
            for (const std::uint32_t i : list) {
                const auto q = Vulkan::StillPoint(place[m].rows, place[m].origin, p + (m * Range + i) * 4);
                Vulkan::StillSigAdd(want[m].data(), q[0], q[1], q[2]);
            }
        }
        const auto got = run(place);
        std::array<Vulkan::StillBox, Meshes> boxes{};
        for (std::uint32_t m = 0; m < Meshes; ++m) {
            if (got[m] != want[m]) {
                std::fprintf(stderr, "still check: mesh %u: the shader's signature is not rt_still_check.h's (vertices taken %u against %u, left out %u against %u)\n",
                             m, got[m][6], want[m][6], got[m][7], want[m][7]);
                ok = false;
            }
            if (Vulkan::DecodeStillSig(got[m].data(), boxes[m]) != !(broken && m == 1)) {
                std::fprintf(stderr, "still check: mesh %u: the signature %s\n", m, broken && m == 1 ? "of a mesh with a vertex that is not a number was taken" : "holds no bounds");
                ok = false;
            }
        }
        Vulkan::StillBox none{};
        if (Vulkan::DecodeStillSig(got[Meshes].data(), none)) {
            std::fprintf(stderr, "still check: a slot no mesh wrote to holds bounds\n");
            ok = false;
        }
        // The pass after the signatures brought the stored positions to world space.
        const float* l = &local[used[0] * 3];
        const float* w = p + used[0] * 4;
        if (w[0] != l[0] + shift[0].x || w[1] != l[1] + shift[0].y || w[2] != l[2] + shift[0].z) {
            std::fprintf(stderr, "still check: the positions are not in world space after the signatures\n");
            ok = false;
        }
        return boxes;
    };
    const Vec3 a{10.25f, 1.5f, -3.0f}, b{-4.0f, 0.5f, 7.0f};
    const auto first = capture({a, b}, 1.0e6f, false);
    const auto again = capture({a, b}, -3.0e5f, false);
    const auto moved = capture({Vec3{a.x + 0.5f, a.y - 1.0f, a.z + 0.02f}, b}, 77.0f, false);
    const auto nudged = capture({Vec3{a.x + 0.001f, a.y, a.z}, b}, 1.0e6f, false);
    capture({a, b}, 1.0e6f, true);
    const float same_a = Vulkan::StillMoved(first[0], again[0]), same_b = Vulkan::StillMoved(first[1], again[1]);
    const float far_a = Vulkan::StillMoved(first[0], moved[0]), far_b = Vulkan::StillMoved(first[1], moved[1]);
    const float near_a = Vulkan::StillMoved(first[0], nudged[0]);
    std::printf("Still check: %zu indices over %zu of %u vertices a mesh; captured again in place: %.6f m and %.6f m; one mesh moved by "
                "(0.5 -1 0.02): %.4f m, the other %.6f m; moved by 1 mm: %.5f m (tolerance %.4f m, %.2f m between the passes)\n",
                list.size(), used.size(), Range, double(same_a), double(same_b), double(far_a), double(far_b), double(near_a),
                double(Vulkan::StillTolerance), double(Vulkan::StillCrossTolerance));
    if (same_a != 0.0f || same_b != 0.0f || far_b != 0.0f) {
        std::fprintf(stderr, "still check: a mesh that did not move differs between two captures\n");
        ok = false;
    }
    if (std::abs(far_a - 1.0f) > 1e-4f || !(far_a > Vulkan::StillCrossTolerance)) {
        std::fprintf(stderr, "still check: a mesh moved by a metre is not found moved by a metre\n");
        ok = false;
    }
    if (near_a > Vulkan::StillTolerance || !(near_a > 0.0f)) {
        std::fprintf(stderr, "still check: a move of a millimetre is not within the tolerance, or not seen at all\n");
        ok = false;
    }

    // Two poses of a perspective camera about a hundred metres from the world's origin (as in
    // the game), near plane 0.1 m; the first mesh stands 60 m in front of it, the second 3 m,
    // neither moves. What a vertex shader stores (clip space, in float) goes through the GPU's
    // signature; beside it, on the CPU, the bounds of the positions rt_unproject.comp's one
    // product makes of the same captures.
    struct Camera {
        std::array<float, 12> view_to_world{}, world_to_view{};
        std::array<float, 16> inverse{};
        float p00 = 0, p11 = 0, a = 0, b = 0;
    };
    const auto camera_at = [](double yaw, double pitch, const std::array<double, 3>& at) {
        const double cy = std::cos(yaw), sy = std::sin(yaw), cp = std::cos(pitch), sp = std::sin(pitch);
        const double turn[3][3] = {{cy, sy * sp, sy * cp}, {0.0, cp, -sp}, {-sy, cy * sp, cy * cp}};
        Camera c;
        for (int r = 0; r < 3; ++r) {
            double t = 0.0;
            for (int k = 0; k < 3; ++k) {
                c.view_to_world[r * 4 + k] = float(turn[r][k]);
                c.world_to_view[r * 4 + k] = float(turn[k][r]);
                t -= turn[k][r] * at[k];
            }
            c.view_to_world[r * 4 + 3] = float(at[r]);
            c.world_to_view[r * 4 + 3] = float(t);
        }
        const double near_plane = 0.1, far_plane = 3000.0, p00 = 1.0 / std::tan(0.6), p11 = p00 * 16.0 / 9.0;
        const double za = far_plane / (near_plane - far_plane), zb = near_plane * za;
        c.p00 = float(p00), c.p11 = float(p11), c.a = float(za), c.b = float(zb);
        c.inverse = {float(1.0 / p00), 0, 0, 0, 0, float(1.0 / p11), 0, 0, 0, 0, 0, -1, 0, 0, float(1.0 / zb), float(za / zb)};
        return c;
    };
    const std::array<double, 3> eye{-22.3, -107.1, -26.1};
    const std::array<Camera, 2> cameras{camera_at(0.7, -0.1, eye), camera_at(0.9, -0.15, {eye[0] + 0.3, eye[1] + 0.1, eye[2] - 0.2})};
    const std::array<double, Meshes> ahead{60.0, 3.0};
    std::array<std::array<Vulkan::StillBox, Meshes>, 2> seen{}, product{};
    float off = 0.0f;
    for (std::uint32_t pose = 0; pose < 2; ++pose) {
        const Camera& c = cameras[pose];
        auto* p = static_cast<float*>(positions.data);
        std::array<Place, Meshes> place{};
        std::array<Words8, Meshes> want{}, old{};
        for (std::uint32_t m = 0; m < Meshes; ++m) {
            Vulkan::StillClipToWorld(c.inverse.data(), c.view_to_world.data(), place[m].rows, place[m].origin);
            for (int r = 0; r < 3; ++r) {
                for (int col = 0; col < 4; ++col) {
                    float sum = c.view_to_world[r * 4 + 3] * c.inverse[12 + col];
                    for (int k = 0; k < 3; ++k) sum += c.view_to_world[r * 4 + k] * c.inverse[k * 4 + col];
                    place[m].product[r * 4 + col] = sum;
                }
            }
            for (std::uint32_t v = 0; v < Range; ++v) {
                // The mesh in the world: in front of the first camera, the same for both poses.
                const float* l = &local[(m * Range + v) * 3];
                float world[3], view[3];
                for (int r = 0; r < 3; ++r) world[r] = float(eye[r] - double(cameras[0].view_to_world[r * 4 + 2]) * ahead[m]) + l[r];
                for (int k = 0; k < 3; ++k) view[k] = c.world_to_view[k * 4] * world[0] + c.world_to_view[k * 4 + 1] * world[1] + c.world_to_view[k * 4 + 2] * world[2] + c.world_to_view[k * 4 + 3];
                float* at = p + (m * Range + v) * 4;
                at[0] = c.p00 * view[0], at[1] = c.p11 * view[1], at[2] = c.a * view[2] + c.b, at[3] = -view[2];
                if (unused(v)) at[0] = 1.0e6f * float(pose + 1), at[1] = nan;
            }
            for (const std::uint32_t i : list) {
                const float* at = p + (m * Range + i) * 4;
                const auto q = Vulkan::StillPoint(place[m].rows, place[m].origin, at);
                Vulkan::StillSigAdd(want[m].data(), q[0], q[1], q[2]);
                const float* row = place[m].product.data();
                Vulkan::StillSigAdd(old[m].data(), row[0] * at[0] + row[1] * at[1] + row[2] * at[2] + row[3] * at[3],
                                    row[4] * at[0] + row[5] * at[1] + row[6] * at[2] + row[7] * at[3],
                                    row[8] * at[0] + row[9] * at[1] + row[10] * at[2] + row[11] * at[3]);
            }
        }
        const auto got = run(place);
        for (std::uint32_t m = 0; m < Meshes; ++m) {
            Vulkan::StillBox cpu{};
            if (!Vulkan::DecodeStillSig(got[m].data(), seen[pose][m]) || !Vulkan::DecodeStillSig(want[m].data(), cpu) ||
                !Vulkan::DecodeStillSig(old[m].data(), product[pose][m]) || got[m][6] != want[m][6]) {
                std::fprintf(stderr, "still check: pose %u, mesh %u: no bounds\n", pose, m);
                ok = false;
            }
            // The GPU may round a sum of products another way than the CPU: not word for word.
            off = std::max(off, Vulkan::StillMoved(seen[pose][m], cpu));
        }
    }
    const float far_seen = Vulkan::StillMoved(seen[0][0], seen[1][0]), near_seen = Vulkan::StillMoved(seen[0][1], seen[1][1]);
    const float far_product = Vulkan::StillMoved(product[0][0], product[1][0]), near_product = Vulkan::StillMoved(product[0][1], product[1][1]);
    std::printf("Still check: a still mesh under two poses of the camera: its bounds differ by %.6f m at 60 m and %.6f m at 3 m "
                "(the scene's one product: %.5f m and %.5f m); the GPU's bounds are within %.6f m of rt_still_check.h's\n",
                double(far_seen), double(near_seen), double(far_product), double(near_product), double(off));
    if (far_seen > Vulkan::StillToleranceLeast / 4 || near_seen > Vulkan::StillToleranceLeast / 4 || off > Vulkan::StillToleranceLeast / 4) {
        std::fprintf(stderr, "still check: a mesh that stands still reads as moved when the camera moves\n");
        ok = false;
    }
    for (Buffer* buffer : {&positions, &sigs, &readback, &indices}) vk.Free(*buffer);
    std::puts(ok ? "Still check: ok" : "Still check: FAILED");
    return ok;
}
}

int main(int argc, char** argv) {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    const char* dump = argc > 1 ? argv[1] : nullptr;
    Vk vk;
    std::printf("GPU: %s, %ux%u, atlas %u\n", vk.name, W, H, Atlas);
    if (argc > 1 && std::strcmp(argv[1], "--still") == 0) { // bbport (r47_still-check)
        return StillLab(vk) ? 0 : 1;
    }
    Lab lab(vk);
    vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER}, 56, RT_UNPROJECT_COMP, sizeof(RT_UNPROJECT_COMP));
    vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                     VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE}, // bbport (r52_follow-soft): 9, 10
                    64, POINT_SHADOW_RAY_COMP, sizeof(POINT_SHADOW_RAY_COMP));
    vk.MakePipeline({VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE,
                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE,
                     VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR},
                    128, SSGI_GATHER_RAY_COMP, sizeof(SSGI_GATHER_RAY_COMP));
    if (argc > 1 && std::strcmp(argv[1], "--pipelines") == 0) {
        // bbport (r52_follow-soft): the half-resolution lamp pass too, with the layout --lamps
        // gives it: the ray pass's bindings 0-8, the block answers (9), the counters (10), the
        // follow state (11, 12)
        vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                        64, POINT_SHADOW_RAY_HALF_COMP, sizeof(POINT_SHADOW_RAY_HALF_COMP),
                        VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
        // bbport (r60_lamp-centred-window): the BB_LAMP_SHADOW_WINDOW=2 builds, as --lamps makes
        // them: the full one's bindings and its answers (11); the half one's and its answers (13)
        vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                        64, POINT_SHADOW_RAY_CENTRED_COMP, sizeof(POINT_SHADOW_RAY_CENTRED_COMP),
                        VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
        vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                        64, POINT_SHADOW_RAY_HALF_CENTRED_COMP, sizeof(POINT_SHADOW_RAY_HALF_CENTRED_COMP),
                        VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
        std::puts("RT pipelines: built");
        return 0;
    }
    const Vec3 sun = Norm({-0.5f, 0.75f, 0.4f});
    constexpr auto Trace = VK_BUILD_ACCELERATION_STRUCTURE_PREFER_FAST_TRACE_BIT_KHR;
    constexpr auto Fast = VK_BUILD_ACCELERATION_STRUCTURE_PREFER_FAST_BUILD_BIT_KHR;
    constexpr auto Update = VK_BUILD_ACCELERATION_STRUCTURE_ALLOW_UPDATE_BIT_KHR;
    const std::array<std::array<Vec3, 2>, 3> cameras{{
        {{{0, 1.6f, -2}, {0.1f, -0.05f, 1}}},
        {{{-4, 1.7f, 12}, {0.8f, -0.25f, 0.5f}}},
        {{{5, 3, 30}, {-0.5f, -0.5f, 1}}},
    }};
    // bbport (r42_lamp-soft): --lamps [directory]: the torch lab (below), with the lamp pass's
    // images and pipeline as --speed makes them.
    const bool torch_lab = argc > 1 && std::strcmp(argv[1], "--lamps") == 0;
    if (argc > 1 && (std::strcmp(argv[1], "--speed") == 0 || torch_lab)) {
        const unsigned total = argc > 2 && !torch_lab ? unsigned(std::strtoul(argv[2], nullptr, 10)) : 1500000u;
        Scene scene{vk, torch_lab ? MakeTorchScene() : MakeScene(total, total / 1875)};
        scene.Create(Trace | Update);
        scene.Allocate();
        scene.BuildAll(Trace | Update);
        const unsigned n = unsigned(scene.blas.size());
        std::printf("== Speed: %u triangles in %u BLAS\n", scene.triangles, n);
        struct Variant { const char* name; VkBuildAccelerationStructureFlagsKHR flags; bool doubled; };
        const std::array<Variant, 3> variants{{{"TLAS fast build", Fast, false},
                                               {"TLAS fast trace", Trace, false},
                                               {"TLAS fast build, every mesh twice", Fast, true}}};
        const auto make_tlas = [&](unsigned count, VkBuildAccelerationStructureFlagsKHR flags) {
            Tlas t;
            t.count = count;
            t.instances = vk.MakeBuffer(count * sizeof(VkAccelerationStructureInstanceKHR),
                                        VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_BUILD_INPUT_READ_ONLY_BIT_KHR, true);
            VkAccelerationStructureGeometryKHR g{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_KHR,
                .geometryType = VK_GEOMETRY_TYPE_INSTANCES_KHR, .flags = VK_GEOMETRY_OPAQUE_BIT_KHR};
            g.geometry.instances = {.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_INSTANCES_DATA_KHR};
            VkAccelerationStructureBuildGeometryInfoKHR info{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_GEOMETRY_INFO_KHR,
                .type = VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR, .flags = flags,
                .mode = VK_BUILD_ACCELERATION_STRUCTURE_MODE_BUILD_KHR, .geometryCount = 1, .pGeometries = &g};
            VkAccelerationStructureBuildSizesInfoKHR s{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_SIZES_INFO_KHR};
            vk.sizes(vk.device, VK_ACCELERATION_STRUCTURE_BUILD_TYPE_DEVICE_KHR, &info, &t.count, &s);
            t.storage = vk.MakeBuffer(s.accelerationStructureSize, VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_STORAGE_BIT_KHR, false);
            t.scratch = vk.MakeBuffer(s.buildScratchSize + AsAlign, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, false);
            VkAccelerationStructureCreateInfoKHR ci{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_CREATE_INFO_KHR,
                .buffer = t.storage.buffer, .size = s.accelerationStructureSize, .type = VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR};
            CHECK(vk.create_as(vk.device, &ci, nullptr, &t.handle));
            return t;
        };
        // bbport (r41_lamp-shadows): more_mask: more instance mask bits (4: lamp rays hit)
        const auto build_tlas = [&](Tlas& t, const Mat4& view, VkBuildAccelerationStructureFlagsKHR flags, bool doubled,
                                    unsigned more_mask = 0) {
            auto* out = static_cast<VkAccelerationStructureInstanceKHR*>(t.instances.data);
            for (unsigned copy = 0; copy < (doubled ? 2u : 1u); ++copy) {
                for (unsigned i = 0; i < n; ++i) {
                    Mat4 model = Identity();
                    model.at(0, 3) = scene.meshes[i].position.x;
                    model.at(1, 3) = scene.meshes[i].position.y;
                    model.at(2, 3) = scene.meshes[i].position.z;
                    const Mat4 m = view * model;
                    VkAccelerationStructureInstanceKHR inst{};
                    std::memcpy(inst.transform.matrix, m.m.data(), 12 * sizeof(float));
                    inst.mask = (doubled ? (copy ? 2 : 1) : 3) | more_mask;
                    inst.accelerationStructureReference = scene.blas[i].address;
                    out[copy * n + i] = inst;
                }
            }
            VkAccelerationStructureGeometryKHR g{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_KHR,
                .geometryType = VK_GEOMETRY_TYPE_INSTANCES_KHR, .flags = VK_GEOMETRY_OPAQUE_BIT_KHR};
            g.geometry.instances = {.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_INSTANCES_DATA_KHR};
            g.geometry.instances.data.deviceAddress = t.instances.address;
            VkAccelerationStructureBuildGeometryInfoKHR info{.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_GEOMETRY_INFO_KHR,
                .type = VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR, .flags = flags,
                .mode = VK_BUILD_ACCELERATION_STRUCTURE_MODE_BUILD_KHR, .dstAccelerationStructure = t.handle,
                .geometryCount = 1, .pGeometries = &g};
            info.scratchData.deviceAddress = t.scratch.address;
            VkAccelerationStructureBuildRangeInfoKHR range{doubled ? 2 * n : n, 0, 0, 0};
            const VkAccelerationStructureBuildRangeInfoKHR* pointer = &range;
            vk.Begin();
            vk.Stamp(0);
            vk.build(vk.cmd, 1, &info, &pointer);
            vk.Stamp(1);
            vk.Barrier();
            return vk.End();
        };
        struct LampPush {
            unsigned first_light = 0, frame = 0;
            float width = W, height = H, length = 0, thickness = 0, strength = 1, fade_start = 60, fade_end = 100;
            unsigned count = 1, steps = 0;
            float bias = 0.02f;
            std::array<int, 4> rect{};
        };
        static_assert(sizeof(LampPush) == 64);
        Pipeline lamp = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                         VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE}, // bbport (r52_follow-soft): 9, 10
                                        64, POINT_SHADOW_RAY_COMP, sizeof(POINT_SHADOW_RAY_COMP),
                                        VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
        Buffer lights = vk.MakeBuffer(64 * 1024 * 4, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, true);
        Image zero_image = vk.MakeImage(W, H, VK_FORMAT_B10G11R11_UFLOAT_PACK32);
        std::array<Image, 2> history{vk.MakeImage(W, H, VK_FORMAT_R16G16B16A16_SFLOAT),
                                     vk.MakeImage(W, H, VK_FORMAT_R16G16B16A16_SFLOAT)};
        // bbport (r52_follow-soft): the follow state beside the history, taken in turn with it
        std::array<Image, 2> follow{vk.MakeImage(W, H, VK_FORMAT_R32_SFLOAT), vk.MakeImage(W, H, VK_FORMAT_R32_SFLOAT)};
        std::array<Image, 4> lamp_images{};
        for (auto& image : lamp_images) image = vk.MakeImage(W, H, VK_FORMAT_B10G11R11_UFLOAT_PACK32);
        vk.Begin();
        for (auto& image : lamp_images) vk.ToGeneral(image.image);
        vk.ToGeneral(zero_image.image);
        for (auto& image : history) vk.ToGeneral(image.image);
        for (auto& image : follow) vk.ToGeneral(image.image); // bbport (r52_follow-soft)
        {
            VkClearColorValue zero{};
            const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
            vkCmdClearColorImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, &zero, 1, &range);
            for (auto& image : follow) vkCmdClearColorImage(vk.cmd, image.image, VK_IMAGE_LAYOUT_GENERAL, &zero, 1, &range);
        }
        vk.Stamp(0); vk.Stamp(1);
        vk.End();
        const auto decode = [](std::uint32_t v) {
            const unsigned e = (v >> 6) & 31u, m = v & 63u;
            return e == 0 ? float(m) / 64.0f * std::ldexp(1.0f, -14) : std::ldexp(1.0f + float(m) / 64.0f, int(e) - 15);
        };
        if (torch_lab) {
            // bbport (r42_lamp-soft): the torch lab. One torch lamp at the flame of a hand torch,
            // the camera above and tilted down. It runs the lamp pass over many frames with its
            // history (the words PointShadow::Flush hands it: flags, frame, the way back to the
            // camera of the frame before, that camera's projection, the most frames a texel may
            // hold), moves the scene and the camera between frames, and compares what the pass
            // shows with the mean of many single frames (the area lamp's true picture). With a
            // directory it writes the pictures there (PGM, the shadow ratio as grey).
            const char* out_dir = argc > 2 ? argv[2] : nullptr;
            Pipeline half = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                                             VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                             VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                             VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                             VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                             VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                             VK_DESCRIPTOR_TYPE_STORAGE_IMAGE}, // bbport (r52_follow-soft): 11, 12
                                            64, POINT_SHADOW_RAY_HALF_COMP, sizeof(POINT_SHADOW_RAY_HALF_COMP),
                                            VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
            Image half_answers = vk.MakeImage((W + 1) / 2, (H + 1) / 2, VK_FORMAT_R16G16B16A16_SFLOAT);
            Buffer half_counts = vk.MakeBuffer(64, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, true);
            std::memset(half_counts.data, 0, 64);
            // bbport (r60_lamp-centred-window): the BB_LAMP_SHADOW_WINDOW=2 builds (a pass whose tuning
            // has window_centred runs them, as PointShadow::Ready picks them) and their answers image
            Pipeline lamp_centred = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                                                    64, POINT_SHADOW_RAY_CENTRED_COMP, sizeof(POINT_SHADOW_RAY_CENTRED_COMP),
                                                    VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
            Pipeline half_centred = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                                                    64, POINT_SHADOW_RAY_HALF_CENTRED_COMP, sizeof(POINT_SHADOW_RAY_HALF_CENTRED_COMP),
                                                    VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
            Image lamp_answers = vk.MakeImage(W, H, VK_FORMAT_R32G32_UINT);
            vk.Begin();
            vk.ToGeneral(lamp_answers.image);
            vk.ToGeneral(half_answers.image);
            vk.Stamp(0); vk.Stamp(1);
            vk.End();
            Tlas tlas = make_tlas(n, Fast);
            std::vector<Vec3> home;
            for (const Mesh& mesh : scene.meshes) home.push_back(mesh.position);
            auto* raw = static_cast<std::uint32_t*>(lights.data);
            constexpr unsigned LampAt = 16, TableAt = 48, HistoryAt = 64, TuneAt = 100;
            Vec3 flame = TorchFlame;
            // A second lamp that stands (reach 6 m, as bright as the torch); none unless `second`.
            // wobble: added to the torch lamp's place for one frame (a flame that flickers).
            bool second = false;
            constexpr Vec3 SecondLamp{1.2f, 2.3f, -1.6f};
            Vec3 wobble{0, 0, 0};
            const auto camera = [&](float pan, float along) {
                return MakeViews({0.2f + pan, 4.5f, -1.2f + along}, {0.0f, -0.97f, 0.26f}, sun);
            };
            // The character with its torch `walk` metres towards the camera's foot (-z), the
            // other figure `other` metres along z; stick false: without the torch's stick.
            const auto place = [&](const Views& v, float walk, float other, bool stick = true) {
                for (const unsigned i : {TorchCharacter, TorchArm, TorchStick, TorchBlade}) {
                    scene.meshes[i].position = home[i] + Vec3{0, i == TorchStick && !stick ? -100.0f : 0.0f, -walk};
                }
                scene.meshes[TorchOther].position = home[TorchOther] + Vec3{0, 0, other};
                flame = TorchFlame + Vec3{0, 0, -walk};
                build_tlas(tlas, v.view, Fast, false, 4);
                lab.Prepare(tlas.handle, v);
            };
            struct Pass {
                const Vulkan::LampShadowTune* tune = nullptr; // null: mode 0 (the experiment bit's path)
                unsigned frame = 0;
                int parity = -1;               // the history image written; -1: no history
                bool read = false;             // with a history: the frame before is read
                const Views* before = nullptr; // with read: the camera of the frame before (null: this one)
                bool follow = true;            // with read: the history is looked up where the lamp's motion puts it
                bool half = false;             // the half-resolution build, in its two passes
                bool again = false;            // the pass before once more (its lamps and history block as they
                                               // are in the buffer), with this tuning: for a view of that frame
                // bbport (r60_lamp-centred-window): MODE_APART, the engine's lamps-apart pass (the one
                // with the history): the light without the lamps in the targets (0 here), the lamps'
                // light in the snapshots (1), moved into the targets by the pass. The targets then
                // end as without it (0 + 1 * ratio, 1 where nothing is shadowed).
                bool apart = false;
            };
            Vulkan::LampTrack track;
            // bbport (r44_half-area-lamp): whether the half-resolution build counts what it does
            // (MODE_HALF_COUNT). Off while it is timed: the counters are in host memory here, where
            // the shader's atomic adds cost fifty times the pass (the engine keeps them on the GPU
            // and counts one pass in eight).
            bool half_count = true;
            const auto run = [&](const Views& v, const Pass& pass) {
                auto* words = static_cast<float*>(lights.data);
                for (int r = 0; r < 4; ++r)
                    for (int k = 0; k < 4; ++k) words[r * 4 + k] = v.inv_proj.at(r, k);
                const unsigned lamps = second ? 2u : 1u;
                for (unsigned l = 0; l < lamps && !pass.again; ++l) {
                    const Vec3 at = l == 0 ? flame + wobble : SecondLamp;
                    std::array<float, 16> light{};
                    for (int r = 0; r < 3; ++r)
                        light[r] = v.view.at(r, 0) * at.x + v.view.at(r, 1) * at.y + v.view.at(r, 2) * at.z + v.view.at(r, 3);
                    light[3] = 1.0f / 36.0f;
                    light[4] = 1.0f; light[5] = 0.8f; light[6] = l == 0 ? 0.6f : 0.7f;
                    std::memcpy(raw + LampAt + 16 * l, light.data(), sizeof(light));
                }
                const std::array<std::uint32_t, 8> row{0u, 0u, W, H, LampAt, lamps, 0u, 0u};
                std::memcpy(raw + TableAt, row.data(), sizeof(row));
                unsigned mode = 0;
                if (pass.tune) {
                    const auto tune_words = Vulkan::LampTuneWords(*pass.tune, false, 0.05f, v.view.m.data(), pass.frame);
                    std::memcpy(raw + TuneAt, tune_words.data(), sizeof(tune_words));
                    mode = 16u | TuneAt << 8; // MODE_REPAIR | place << 8
                }
                if (pass.parity >= 0 && !pass.again) {
                    // What PointShadow::Flush does for the pass that holds the history.
                    const Views& was = pass.before ? *pass.before : v;
                    const Mat4 back = was.view * Inverse(v.view), to_world = Inverse(v.view);
                    track.Begin(to_world.m.data());
                    std::array<int, 2> index{};
                    for (unsigned l = 0; l < lamps; ++l) index[l] = track.Add(raw + LampAt + 16 * l);
                    if (pass.read) track.Follow();
                    for (unsigned l = 0; l < lamps; ++l) {
                        const auto moved = pass.read && pass.follow && pass.tune->follow ? track.Shift(index[l], was.view.m.data())
                                                                                         : std::array<float, 3>{};
                        std::memcpy(raw + LampAt + 16 * l + 12, moved.data(), sizeof(moved));
                        const float step = pass.read ? track.Step(index[l]) : 0.0f;
                        std::memcpy(raw + LampAt + 16 * l + 15, &step, 4);
                    }
                    track.End(true);
                    raw[HistoryAt] = 2u | 4u | (pass.read ? 1u : 0u); // HISTORY_WRITE | HISTORY_BLEND | HISTORY_READ
                    raw[HistoryAt + 1] = pass.frame;
                    std::memcpy(raw + HistoryAt + 2, back.m.data(), 48);
                    std::memcpy(raw + HistoryAt + 14, was.proj.m.data(), 64);
                    const auto tail = Vulkan::LampHistoryTail(*pass.tune); // words 30 to 33
                    std::memcpy(raw + HistoryAt + 30, tail.data(), sizeof(tail));
                    static_assert(HistoryAt + 30 + Vulkan::LampHistoryTailWords <= TuneAt);
                }
                vk.Begin();
                VkClearColorValue one{};
                one.float32[0] = one.float32[1] = one.float32[2] = 1.0f;
                const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
                const VkImageCopy whole{.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                    .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .extent = {W, H, 1}};
                if (pass.apart) { // bbport (r60_lamp-centred-window): cur0 0, snap0 1, cur1 and snap1 0
                    vkCmdClearColorImage(vk.cmd, lamp_images[1].image, VK_IMAGE_LAYOUT_GENERAL, &one, 1, &range);
                    for (const int k : {0, 2, 3})
                        vkCmdCopyImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, lamp_images[std::size_t(k)].image,
                                       VK_IMAGE_LAYOUT_GENERAL, 1, &whole);
                    mode |= 1u; // MODE_APART
                } else {
                    vkCmdClearColorImage(vk.cmd, lamp_images[0].image, VK_IMAGE_LAYOUT_GENERAL, &one, 1, &range);
                    vkCmdClearColorImage(vk.cmd, lamp_images[2].image, VK_IMAGE_LAYOUT_GENERAL, &one, 1, &range);
                    vkCmdCopyImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, lamp_images[1].image, VK_IMAGE_LAYOUT_GENERAL, 1, &whole);
                    vkCmdCopyImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, lamp_images[3].image, VK_IMAGE_LAYOUT_GENERAL, 1, &whole);
                }
                vk.Barrier();
                VkDescriptorBufferInfo data{lights.buffer, 0, (TuneAt + Vulkan::LampTuneWordCount) * 4};
                VkDescriptorImageInfo depth{vk.sampler, lab.depth.view, VK_IMAGE_LAYOUT_GENERAL};
                std::array<VkDescriptorImageInfo, 4> images{};
                for (int k = 0; k < 4; ++k) images[k] = {{}, lamp_images[k].view, VK_IMAGE_LAYOUT_GENERAL};
                VkWriteDescriptorSetAccelerationStructureKHR as{.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET_ACCELERATION_STRUCTURE_KHR,
                    .accelerationStructureCount = 1, .pAccelerationStructures = &tlas.handle};
                const int cur_history = pass.parity < 0 ? 0 : pass.parity;
                VkDescriptorImageInfo history_prev{{}, history[cur_history ^ 1].view, VK_IMAGE_LAYOUT_GENERAL};
                VkDescriptorImageInfo history_cur{{}, history[cur_history].view, VK_IMAGE_LAYOUT_GENERAL};
                VkDescriptorImageInfo answers{{}, half_answers.view, VK_IMAGE_LAYOUT_GENERAL};
                VkDescriptorBufferInfo counts{half_counts.buffer, 0, 64};
                std::array<VkWriteDescriptorSet, 14> writes{}; // bbport (r60): 13, the centred window's answers
                for (unsigned k = 0; k < 14; ++k) writes[k] = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = k, .descriptorCount = 1};
                writes[0].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER; writes[0].pBufferInfo = &data;
                writes[1].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER; writes[1].pImageInfo = &depth;
                for (int k = 0; k < 4; ++k) { writes[2 + k].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[2 + k].pImageInfo = &images[k]; }
                writes[6].descriptorType = VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR; writes[6].pNext = &as;
                writes[7].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[7].pImageInfo = &history_prev;
                writes[8].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[8].pImageInfo = &history_cur;
                writes[9].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[9].pImageInfo = &answers;
                writes[10].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER; writes[10].pBufferInfo = &counts;
                // bbport (r52_follow-soft): the follow state, taken in turn with the history:
                // bindings 11 and 12 of the half-resolution build, 9 and 10 of the full one
                VkDescriptorImageInfo follow_prev{{}, follow[cur_history ^ 1].view, VK_IMAGE_LAYOUT_GENERAL};
                VkDescriptorImageInfo follow_cur{{}, follow[cur_history].view, VK_IMAGE_LAYOUT_GENERAL};
                writes[11].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[11].pImageInfo = &follow_prev;
                writes[12].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[12].pImageInfo = &follow_cur;
                // bbport (r60_lamp-centred-window): the centred window's answers, binding 13 of the
                // half-resolution build and 11 of the full one (bound only with those builds)
                VkDescriptorImageInfo centred_answers{{}, lamp_answers.view, VK_IMAGE_LAYOUT_GENERAL};
                writes[13].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[13].pImageInfo = &centred_answers;
                std::array<VkWriteDescriptorSet, 12> full_writes{};
                std::copy_n(writes.begin(), 9, full_writes.begin());
                full_writes[9] = writes[11];
                full_writes[9].dstBinding = 9;
                full_writes[10] = writes[12];
                full_writes[10].dstBinding = 10;
                full_writes[11] = writes[13];
                full_writes[11].dstBinding = 11;
                // As PointShadow::Ready and Flush: the window centred (BB_LAMP_SHADOW_WINDOW=2) runs
                // its builds, and the pass that averages (not view 2 or 3) as a trace and a resolve.
                const bool centred = pass.tune && pass.tune->window && pass.tune->window_centred;
                const bool split = centred && pass.parity >= 0 && pass.tune->view != 2 && pass.tune->view != 3;
                constexpr unsigned Trace = 32u, Resolve = 64u; // MODE_TRACE, MODE_RESOLVE
                LampPush push;
                push.first_light = TableAt;
                push.count = 1;
                push.rect = {0, 0, int(W), int(H)};
                push.steps = 1;
                push.frame = pass.frame;
                push.bias = pass.tune ? pass.tune->bias_m : 0.03f;
                if (pass.parity >= 0) {
                    const unsigned history_at = HistoryAt;
                    std::memcpy(&push.length, &history_at, 4);
                }
                vk.Stamp(0);
                if (pass.parity >= 0) {
                    VkClearColorValue zero{};
                    vkCmdClearColorImage(vk.cmd, history[cur_history].image, VK_IMAGE_LAYOUT_GENERAL, &zero, 1, &range);
                    vk.Barrier();
                }
                if (pass.half) {
                    const Pipeline& p = centred ? half_centred : half; // bbport (r60)
                    vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, p.pipeline);
                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, p.layout, 0, centred ? 14 : 13, writes.data());
                    const unsigned count = half_count ? 8u : 0u; // MODE_HALF_COUNT
                    // bbport (r60_lamp-centred-window): split, each half's trace and resolve (the
                    // resolves count nothing), as PointShadow::Flush records them
                    const auto dispatch = [&](unsigned word, unsigned x, unsigned y) {
                        std::memcpy(&push.thickness, &word, 4);
                        vkCmdPushConstants(vk.cmd, p.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                        vkCmdDispatchBase(vk.cmd, 0, 0, 0, x, y, 1);
                    };
                    dispatch(mode | 2u | count | (split ? Trace : 0u), (W + 15) / 16, (H + 15) / 16); // MODE_HALF_FIRST
                    vk.Barrier();
                    if (split) {
                        dispatch(mode | 2u | Resolve, (W + 15) / 16, (H + 15) / 16);
                        vk.Barrier();
                    }
                    dispatch(mode | 4u | count | (split ? Trace : 0u), (W + 7) / 8, (H + 7) / 8); // MODE_HALF_FILL
                    if (split) {
                        vk.Barrier();
                        dispatch(mode | 4u | Resolve, (W + 7) / 8, (H + 7) / 8);
                    }
                } else {
                    const Pipeline& p = centred ? lamp_centred : lamp; // bbport (r60)
                    vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, p.pipeline);
                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, p.layout, 0, centred ? 12 : 11, full_writes.data());
                    unsigned word = mode | (split ? Trace : 0u);
                    std::memcpy(&push.thickness, &word, 4);
                    vkCmdPushConstants(vk.cmd, p.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                    vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 7) / 8, (H + 7) / 8, 1);
                    if (split) {
                        vk.Barrier();
                        word = mode | Resolve;
                        std::memcpy(&push.thickness, &word, 4);
                        vkCmdPushConstants(vk.cmd, p.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                        vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 7) / 8, (H + 7) / 8, 1);
                    }
                }
                vk.Barrier();
                vk.Stamp(1);
                vk.Barrier();
                return vk.End();
            };
            const auto values = [&] {
                const auto bits = lab.Read(lamp_images[0], VK_FORMAT_R32_SFLOAT);
                std::vector<float> out(bits.size());
                for (std::size_t k = 0; k < bits.size(); ++k) {
                    std::uint32_t word;
                    std::memcpy(&word, &bits[k], 4);
                    out[k] = decode(word);
                }
                return out;
            };
            const auto dump = [&](const std::string& name, const std::vector<float>& picture) {
                if (out_dir) WritePgm((std::string(out_dir) + "/" + name + ".pgm").c_str(), picture);
            };
            // The frames in turn: the frame counter, and whether the frame before left a history.
            unsigned clock = 0;
            bool have_history = false;
            const auto restart = [&] {
                clock = 0;
                have_history = false;
                track.End(false);
            };
            // bbport (r44_half-area-lamp): at_half: `frame` and `held_view` run the half-resolution build
            // (with the same history block: PointShadow::Flush hands both builds the same words).
            // half_did: what its two passes did since the counters were last zeroed (the shader's
            // half_counts words); traced_share: the share of the second pass's pixels that cast their
            // own rays, in percent.
            bool at_half = false;
            // bbport (r60_lamp-centred-window): at_apart: `frame` and `held_view` run the pass with
            // MODE_APART, as the engine runs its pass with the history (Pass::apart)
            bool at_apart = false;
            using HalfDid = std::array<std::uint32_t, 16>;
            const auto half_zero = [&] { std::memset(half_counts.data, 0, 64); };
            const auto half_did = [&] {
                HalfDid did{};
                std::memcpy(did.data(), half_counts.data, 64);
                return did;
            };
            const auto traced_share = [](const HalfDid& did) {
                const double all = double(did[4]) + double(did[5]) + double(did[7]);
                return all > 0.0 ? 100.0 * double(did[5]) / all : 0.0;
            };
            // One frame as the engine runs it. before: the camera of the frame before.
            const auto frame = [&](const Views& v, const Vulkan::LampShadowTune& tune, const Views* before = nullptr,
                                   bool follow = true) {
                const bool history = Vulkan::LampHistoryFrames(tune) > 0.0f;
                const double ms = run(v, {.tune = &tune, .frame = clock, .parity = history ? int(clock & 1u) : -1,
                                          .read = have_history && history, .before = before, .follow = follow,
                                          .half = at_half, .apart = at_apart});
                have_history = history;
                ++clock;
                return ms;
            };
            // The frame `frame` just ran, once more as BB_LAMP_SHADOW_VIEW=5 shows it: for every pixel the
            // share of the frames its history may hold that it does hold (the pass writes the same history
            // again). Below 0: the pass does not shadow the pixel.
            const auto held_view = [&](const Views& v, const Vulkan::LampShadowTune& tune) {
                Vulkan::LampShadowTune shown = tune;
                shown.view = 5;
                shown.view_gain = 0.5f;
                run(v, {.tune = &shown, .frame = clock - 1, .parity = int((clock - 1) & 1u), .half = at_half, .again = true,
                        .apart = at_apart});
                auto picture = values(); // red: (1 - held) / 2; a pixel the pass leaves alone keeps 1
                for (float& p : picture) p = p > 0.75f ? -1.0f : 1.0f - 2.0f * p;
                return picture;
            };
            // The area lamp's true picture: the mean of `count` frames, each one ray a lamp.
            const auto truth = [&](const Views& v, const Vulkan::LampShadowTune& tune, unsigned count = 128) {
                Vulkan::LampShadowTune single = tune;
                single.history = 0.0f;
                std::vector<float> mean(W * H, 0.0f);
                for (unsigned k = 0; k < count; ++k) {
                    run(v, {.tune = &single, .frame = 4096u + k});
                    const auto one = values();
                    for (std::size_t i = 0; i < one.size(); ++i) mean[i] += one[i] / float(count);
                }
                return mean;
            };
            // Mean difference from `reference`: over the picture, over the reference's penumbra
            // (0.05 to 0.95), and the share of pixels more than 0.25 off, in percent.
            // bbport (r44_half-area-lamp): part 1: over pixel (2x, 2y) of every 2x2 block alone, which
            // the half-resolution build's first pass works out; part 0: over the other three, its
            // second pass's. A fault of one of the two passes shows as a difference between these.
            struct Off { double all = 0, penumbra = 0, far = 0; };
            const auto off = [&](const std::vector<float>& picture, const std::vector<float>& reference, int part = -1) {
                Off o;
                std::size_t soft = 0, count = 0;
                for (std::size_t i = 0; i < picture.size(); ++i) {
                    if (part >= 0 && int((i % W) % 2 == 0 && (i / W) % 2 == 0) != part) continue;
                    ++count;
                    const double d = std::abs(double(picture[i]) - reference[i]);
                    o.all += d;
                    o.far += d > 0.25 ? 1 : 0;
                    if (reference[i] > 0.05f && reference[i] < 0.95f) {
                        o.penumbra += d;
                        ++soft;
                    }
                }
                o.all /= double(std::max<std::size_t>(count, 1));
                o.far *= 100.0 / double(std::max<std::size_t>(count, 1));
                o.penumbra /= double(std::max<std::size_t>(soft, 1));
                return o;
            };
            // The mean of `held` (held_view) over the reference's penumbra: how much history the pixels
            // that need it have. The error numbers alone rank a smeared picture above a noisy one.
            const auto held_mean = [&](const std::vector<float>& held, const std::vector<float>& reference) {
                double sum = 0;
                std::size_t soft = 0;
                for (std::size_t i = 0; i < held.size(); ++i) {
                    if (held[i] >= 0.0f && reference[i] > 0.05f && reference[i] < 0.95f) {
                        sum += held[i];
                        ++soft;
                    }
                }
                return sum / double(std::max<std::size_t>(soft, 1));
            };
            // A stand-in for the temporal upscaler that runs after the pass (still camera only):
            // each frame's picture goes into a running mean that keeps 0.8 of what it held.
            const auto settle = [](std::vector<float>& held, const std::vector<float>& one, bool first) {
                if (first) {
                    held = one;
                    return;
                }
                for (std::size_t i = 0; i < one.size(); ++i) held[i] = 0.8f * held[i] + 0.2f * one[i];
            };

            // The knobs as the environment has them (BB_LAMP_SHADOW_*), as the engine reads them:
            // a radius or a history blend can be tried here before the game is started. The
            // checks below are made for the defaults (checked) and left out otherwise.
            Vulkan::LampShadowTune soft = Vulkan::ReadLampShadowTune([](const char* name) -> const char* { return std::getenv(name); });
            soft.view = 0;
            const Vulkan::LampShadowTune stock;
            const bool checked = soft.radius_m == stock.radius_m && soft.history == stock.history &&
                                 soft.reject == stock.reject && soft.trail_m == stock.trail_m &&
                                 soft.follow == stock.follow && soft.carry_m == stock.carry_m &&
                                 soft.around == stock.around && soft.weights == stock.weights &&
                                 soft.clearance_m == stock.clearance_m && soft.bias_m == stock.bias_m &&
                                 soft.self_m == stock.self_m;
            if (!checked) std::puts("Torch lab: BB_LAMP_SHADOW_* knobs differ from the defaults: numbers and pictures only, no checks");
            Vulkan::LampShadowTune point = soft;
            point.radius_m = 0.0f;
            const Views view = camera(0.0f, 0.0f);
            // bbport (r44_half-area-lamp): how much further from the true picture the half-resolution
            // build may be than the full-resolution pass in the same scene (over all pixels, over the
            // penumbra) before a check fails.
            constexpr double HalfAllMost = 1.25, HalfPenumbraMost = 1.25;

            // 1. The point lamp: the same picture whatever the frame counter, and no history.
            place(view, 0.0f, 0.0f, false);
            run(view, {.tune = &point});
            const auto point_bare = values(); // without the stick
            place(view, 0.0f, 0.0f);
            run(view, {.tune = &point, .frame = 0});
            const auto point_picture = values();
            run(view, {.tune = &point, .frame = 7});
            if (values() != point_picture || Vulkan::LampHistoryFrames(point) != 0.0f) {
                std::fprintf(stderr, "the point lamp (BB_LAMP_SHADOW_SOFT=0) changes with the frame counter, or keeps a history\n");
                return 1;
            }
            dump("point", point_picture);
            // The stick's band: dark with the stick, lit without. The bodies' shadows: dark without it.
            std::vector<std::size_t> band, body;
            for (std::size_t i = 0; i < point_picture.size(); ++i) {
                if (point_bare[i] < 0.25f) body.push_back(i);
                else if (point_picture[i] < 0.25f && point_bare[i] > 0.75f) band.push_back(i);
            }

            // 2. The area lamp: one frame, the true picture, 16 and 48 frames of history.
            run(view, {.tune = &soft, .frame = 0});
            const auto one_frame = values();
            dump("area_1_frame", one_frame);
            const auto reference = truth(view, soft);
            dump("area_true", reference);
            restart();
            // (late: the plain mean of frames 33 to 48, for what the history adds to or takes from the
            // light where the true picture is nearly dark or nearly lit: a bound that pulled the history
            // towards the answers around a pixel would show there.)
            std::vector<float> after4, after16, after48, upscaled, late(W * H, 0.0f);
            for (unsigned k = 0; k < 48; ++k) {
                frame(view, soft);
                if (k == 3 || k == 15 || k >= 32) {
                    auto now = values();
                    if (k >= 32) {
                        settle(upscaled, now, k == 32);
                        for (std::size_t i = 0; i < now.size(); ++i) late[i] += now[i] / 16.0f;
                    }
                    if (k == 3) after4 = std::move(now);
                    else if (k == 15) after16 = std::move(now);
                    else if (k == 47) after48 = std::move(now);
                }
            }
            dump("area_16_frames", after16);
            dump("area_48_frames", after48);
            dump("area_48_frames_upscaled", upscaled);
            const Off off1 = off(one_frame, reference), off4 = off(after4, reference), off16 = off(after16, reference),
                      off48 = off(after48, reference), off_up = off(upscaled, reference);
            double mean_true = 0, mean48 = 0, band_point = 0, band_light = 0, band_true = 0;
            std::array<double, 2> lean{}; // late minus true where the true picture is 0.05 to 0.2, 0.8 to 0.95
            std::array<std::size_t, 2> lean_n{};
            for (std::size_t i = 0; i < reference.size(); ++i) {
                mean_true += reference[i] / double(reference.size());
                mean48 += after48[i] / double(reference.size());
                const int bin = reference[i] > 0.05f && reference[i] < 0.2f ? 0 : reference[i] > 0.8f && reference[i] < 0.95f ? 1 : -1;
                if (bin >= 0) {
                    lean[std::size_t(bin)] += double(late[i]) - reference[i];
                    ++lean_n[std::size_t(bin)];
                }
            }
            for (std::size_t b = 0; b < 2; ++b) lean[b] /= double(std::max<std::size_t>(lean_n[b], 1));
            for (const std::size_t i : band) {
                band_point += point_picture[i] / double(std::max<std::size_t>(band.size(), 1));
                band_light += after48[i] / double(std::max<std::size_t>(band.size(), 1));
                band_true += reference[i] / double(std::max<std::size_t>(band.size(), 1));
            }
            std::size_t body_dark = 0;
            for (const std::size_t i : body) body_dark += after48[i] < 0.25f ? 1 : 0;
            std::printf("Torch lab, radius %.2f m, history %.2f (%.0f frames): difference from the true picture (mean of "
                        "128 frames), all pixels / penumbra / share more than 0.25 off: one frame %.4f / %.4f / %.2f%%, "
                        "4 frames %.4f / %.4f / %.2f%%, 16 frames %.4f / %.4f / %.2f%%, 48 frames %.4f / %.4f / %.2f%%, "
                        "48 frames through the upscaler's stand-in %.4f / %.4f / %.2f%%; mean light true %.4f, after 48 "
                        "frames %.4f; the mean of frames 33 to 48 less the true picture where that is 0.05 to 0.2: "
                        "%+.4f, 0.8 to 0.95: %+.4f\n",
                        soft.radius_m, soft.history, Vulkan::LampHistoryFrames(soft), off1.all, off1.penumbra, off1.far,
                        off4.all, off4.penumbra, off4.far, off16.all, off16.penumbra, off16.far, off48.all, off48.penumbra,
                        off48.far, off_up.all, off_up.penumbra, off_up.far, mean_true, mean48, lean[0], lean[1]);
            std::printf("Torch lab: the stick's band (%zu pixels the point lamp leaves dark): light kept %.3f with the "
                        "point lamp, %.3f with the area lamp (true %.3f); the bodies' shadows (%zu pixels dark without "
                        "the stick): %zu still below 0.25 with the area lamp\n",
                        band.size(), band_point, band_light, band_true, body.size(), body_dark);
            if (checked && (std::abs(mean48 - mean_true) > 0.004 || std::abs(lean[0]) > 0.02 || std::abs(lean[1]) > 0.02)) {
                std::fprintf(stderr, "the history is biased: mean light %.4f against the true %.4f, off by %+.4f where "
                                     "that is nearly dark and %+.4f where it is nearly lit\n",
                             mean48, mean_true, lean[0], lean[1]);
                return 1;
            }
            if (checked && (band.empty() || band_light < 0.5 || body_dark * 2 < body.size())) {
                std::fprintf(stderr, "the area lamp keeps %.3f of the light in the stick's band (%zu pixels) and %zu of "
                                     "%zu dark pixels of the bodies' shadows\n",
                             band_light, band.size(), body_dark, body.size());
                return 1;
            }

            // 3. Raw frames (BB_LAMP_SHADOW_HISTORY=0) through the upscaler's stand-in alone.
            {
                Vulkan::LampShadowTune single = soft;
                single.history = 0.0f;
                std::vector<float> held;
                restart();
                for (unsigned k = 0; k < 16; ++k) {
                    frame(view, single);
                    settle(held, values(), k == 0);
                }
                const Off o = off(held, reference);
                dump("area_no_history_upscaled", held);
                std::printf("Torch lab: no history, 16 frames through the upscaler's stand-in: %.4f / %.4f / %.2f%%\n",
                            o.all, o.penumbra, o.far);
            }

            // 3b. A lamp that sits lower over a surface than its radius (a candle on the ground): the
            // surface must not shadow itself under the lamp's disc. The figures are 30 m off, the lamp
            // 5 cm and 2 cm over bare ground: the area lamp's light where the point lamp's is whole.
            {
                std::array<double, 2> kept{};
                unsigned slot = 0;
                for (const float height : {0.05f, 0.02f}) {
                    place(view, 30.0f, 30.0f);
                    wobble = Vec3{0.2f - flame.x, height - flame.y, 0.0f - flame.z};
                    run(view, {.tune = &point, .frame = 0});
                    const auto low_point = values();
                    const auto low_true = truth(view, soft, 32);
                    double sum = 0;
                    std::size_t lit = 0;
                    for (std::size_t i = 0; i < low_true.size(); ++i) {
                        if (low_point[i] > 0.999f) {
                            sum += low_true[i];
                            ++lit;
                        }
                    }
                    kept[slot++] = sum / double(std::max<std::size_t>(lit, 1));
                    if (height > 0.03f) dump("low_lamp_true", low_true);
                }
                wobble = {0, 0, 0};
                place(view, 0.0f, 0.0f);
                std::printf("Torch lab: a lamp 5 cm and 2 cm over bare ground, radius %.2f m: the area lamp keeps %.4f "
                            "and %.4f of the light where the point lamp's is whole\n", soft.radius_m, kept[0], kept[1]);
                if (checked && !(kept[0] > 0.98 && kept[1] > 0.98)) {
                    std::fprintf(stderr, "the ground shadows itself under a lamp that sits lower than its radius\n");
                    return 1;
                }
            }

            // 4. Motion. 24 still frames, then `frames` frames in which the character walks with its
            // torch (walk, metres a frame; the camera goes with it as the game's does), the second
            // figure walks under the lamps (other), or the torch's lamp is off its place by up to
            // `shake` metres, anew every frame (a flame that flickers); then the picture of the last
            // frame against the true picture of that moment. plain: the history without its guards
            // (BB_LAMP_SHADOW_CLAMP=0, BB_LAMP_SHADOW_REJECT=0, BB_LAMP_SHADOW_TRAIL=0); follow
            // false: looked up where the ground was, never where the lamp's motion puts it.
            Vulkan::LampShadowTune plain = soft;
            plain.around = 0.0f;
            plain.reject = 0.0f;
            plain.trail_m = 0.0f;
            struct Move {
                float walk = 0.0f, other = 0.0f, shake = 0.0f;
                unsigned frames = 16;
                bool follow = true;
                bool carried = true; // bbport (r57_lamp-window): false: the torch's lamp walks, its carrier stands
            };
            // bbport (r57_lamp-window): the lattice score. The squares behind a moving shadow sat on
            // the workgroups' grid at 0, 3, 4 and 5 px of every 8 (and on even pixels in the
            // half-resolution build), which the r52 seams (the x mod 8 == 0 lines alone) miss. The
            // mean step between neighbours (column x - 1 to x, row y - 1 to y) is folded by x and by y
            // mod 16 over the moving frames, on the steps where the history without its guards shows
            // a penumbra or a wake on that frame (a value of 0.02 to 0.98 at either pixel; so every
            // case of one walk is measured on the same steps). Two scores: a fold's largest bin over
            // its smallest (any grid), and the window's own phases, the mean of the fold mod 8's
            // bins 0, 3, 4 and 5 (where the 5x5 window changes from one pixel to the next) over that
            // of bins 1, 2, 6 and 7. Both are near 1 with no grid, but shadows that stay put on the
            // screen (the carried torch's: camera, character and torch move together) lift some
            // bins in every run, the reference included: compare the runs, not the number with 1.
            struct Lattice {
                std::vector<std::uint8_t>* mask = nullptr; // per moving frame and pixel: measured there
                bool record = false;                       // this run sets the mask
                std::array<std::array<double, 16>, 2> sum{}, count{}; // [x, y][the coordinate mod 16]
            };
            const auto fold = [&](Lattice& lattice, const std::vector<float>& picture, unsigned k) {
                const std::size_t at = std::size_t(k) * W * H;
                if (lattice.record) {
                    lattice.mask->resize(at + std::size_t(W) * H);
                    for (std::size_t i = 0; i < picture.size(); ++i)
                        (*lattice.mask)[at + i] = picture[i] > 0.02f && picture[i] < 0.98f ? 1 : 0;
                }
                const std::uint8_t* m = lattice.mask->data() + at;
                for (unsigned y = 0; y < H; ++y) {
                    for (unsigned x = 0; x < W; ++x) {
                        const std::size_t i = std::size_t(y) * W + x;
                        if (x > 0 && (m[i] | m[i - 1]) != 0) {
                            lattice.sum[0][x % 16] += std::abs(double(picture[i]) - double(picture[i - 1]));
                            lattice.count[0][x % 16] += 1.0;
                        }
                        if (y > 0 && (m[i] | m[i - W]) != 0) {
                            lattice.sum[1][y % 16] += std::abs(double(picture[i]) - double(picture[i - W]));
                            lattice.count[1][y % 16] += 1.0;
                        }
                    }
                }
            };
            const auto lattice_bins = [](const Lattice& lattice, int axis, unsigned mod) {
                std::vector<double> bins(mod, 0.0);
                for (unsigned b = 0; b < mod; ++b) {
                    double sum = 0, count = 0;
                    for (unsigned j = b; j < 16; j += mod) {
                        sum += lattice.sum[std::size_t(axis)][j];
                        count += lattice.count[std::size_t(axis)][j];
                    }
                    bins[b] = sum / std::max(count, 1.0);
                }
                return bins;
            };
            const auto lattice_score = [&](const Lattice& lattice, int axis, unsigned mod) {
                const std::vector<double> bins = lattice_bins(lattice, axis, mod);
                const auto [lo, hi] = std::minmax_element(bins.begin(), bins.end());
                return *hi / std::max(*lo, 1e-12);
            };
            const auto window_score = [&](const Lattice& lattice, int axis) {
                const std::vector<double> b = lattice_bins(lattice, axis, 8);
                return (b[0] + b[3] + b[4] + b[5]) / std::max(b[1] + b[2] + b[6] + b[7], 1e-12);
            };
            Views moved_view = view;
            std::vector<float> moved_held; // held_view of the last frame
            HalfDid moved_did{};           // at_half: what the two passes did on the last frame
            const auto moving = [&](const Vulkan::LampShadowTune& tune, const Move& move,
                                    std::vector<float>* upscaled_out = nullptr, Lattice* lattice = nullptr) {
                restart();
                Views now = view;
                wobble = {0, 0, 0};
                place(now, 0.0f, 0.0f);
                for (unsigned k = 0; k < 24; ++k) frame(now, tune);
                std::vector<float> held;
                std::mt19937 rng(11);
                for (unsigned k = 1; k <= move.frames; ++k) {
                    const float walked = move.walk * float(k);
                    const Views before = now;
                    now = camera(0.0f, -walked);
                    if (move.shake > 0.0f) {
                        std::uniform_real_distribution<float> off(-move.shake, move.shake);
                        wobble = {off(rng), 0.0f, off(rng)};
                    }
                    place(now, move.carried ? walked : 0.0f, move.other * float(k));
                    if (!move.carried) flame = TorchFlame + Vec3{0, 0, -walked};
                    if (k == move.frames) half_zero();
                    frame(now, tune, &before, move.follow);
                    if (upscaled_out) settle(held, values(), k == 1);
                    if (lattice) fold(*lattice, values(), k - 1);
                }
                moved_did = half_did();
                if (upscaled_out) *upscaled_out = std::move(held);
                moved_view = now;
                auto picture = values();
                moved_held = Vulkan::LampHistoryFrames(tune) > 0.0f ? held_view(now, tune) : std::vector<float>{};
                return picture;
            };
            // bbport (r52_follow-soft): the squares of a carried torch's shadows lay on the
            // workgroups' grid: 8 px, 16 px in the half-resolution build's first pass. Seam: the
            // mean step between neighbouring pixels across those lines (between column x - 1 and
            // x, or row y - 1 and y, where x or y is a multiple of `step`) minus the mean step
            // off every 8 px line (so the 16 px seam is not measured against the 8 px lines of
            // the half-resolution build's second pass), over the picture (all) and over the
            // steps that touch the reference's penumbra (0.05 to 0.95). About 0 where nothing
            // lines up with the grid. Printed only: no bound is checked.
            struct Seam { double all = 0, penumbra = 0; };
            const auto seam = [&](const std::vector<float>& picture, const std::vector<float>& reference, unsigned step) {
                std::array<double, 4> sum{}; // across the lines, elsewhere; the same in the penumbra
                std::array<std::size_t, 4> count{};
                const auto soft_ref = [&](std::size_t k) { return reference[k] > 0.05f && reference[k] < 0.95f; };
                const auto add = [&](std::size_t i, std::size_t j, bool across) {
                    const double d = std::abs(double(picture[i]) - double(picture[j]));
                    const std::size_t at = across ? 0 : 1;
                    sum[at] += d;
                    ++count[at];
                    if (soft_ref(i) || soft_ref(j)) {
                        sum[at + 2] += d;
                        ++count[at + 2];
                    }
                };
                for (unsigned y = 0; y < H; ++y) {
                    for (unsigned x = 0; x < W; ++x) {
                        const std::size_t i = std::size_t(y) * W + x;
                        if (x > 0 && (x % step == 0 || x % 8 != 0)) add(i, i - 1, x % step == 0);
                        if (y > 0 && (y % step == 0 || y % 8 != 0)) add(i, i - W, y % step == 0);
                    }
                }
                const auto mean = [&](std::size_t k) { return sum[k] / double(std::max<std::size_t>(count[k], 1)); };
                return Seam{mean(0) - mean(1), mean(2) - mean(3)};
            };
            // (The true picture of the moment `moving` ended at: the scene and the lamp stand as its
            // last frame left them.)
            for (const float speed : {0.067f, 0.02f}) {
                // 6.7 cm a frame is a run (4 m/s at 60 frames a second), 2 cm a walk.
                const Move walk{.walk = speed};
                Move anchored = walk;
                anchored.follow = false;
                const auto alone = moving(plain, walk), all = moving(soft, walk);
                const auto all_held = moved_held;
                // bbport (r52_follow-soft): word 0 bit 20 (LampTuneFollowSoft) is the bit the
                // shader reads: after this walk the follow images hold a state somewhere (the
                // carried torch's blocked rays) with it, and stay as zeroed without it (the pass
                // stores nothing there).
                if (checked) {
                    bool kept_state = false;
                    for (auto& image : follow) {
                        for (const float x : lab.Read(image, VK_FORMAT_R32_SFLOAT)) kept_state = kept_state || x != 0.0f;
                    }
                    if (kept_state != soft.follow_soft) {
                        std::fprintf(stderr, "BB_LAMP_SHADOW_FOLLOW_SOFT=%d, but the follow images %s\n",
                                     soft.follow_soft ? 1 : 0, kept_state ? "hold a state" : "hold nothing");
                        return 1;
                    }
                }
                const auto guarded = moving(soft, anchored);
                Vulkan::LampShadowTune loose = soft;
                loose.trail_m = 0.0f;
                const auto untrailed = moving(loose, walk);
                const auto untrailed_held = moved_held;
                // bbport (r44_half-area-lamp): the default once more in the half-resolution build
                at_half = true;
                const auto halved = moving(soft, walk);
                const auto halved_held = moved_held;
                const HalfDid halved_did = moved_did;
                at_half = false;
                const auto moved_true = truth(moved_view, soft);
                const Off a = off(alone, moved_true), c = off(guarded, moved_true), d = off(all, moved_true),
                          e = off(untrailed, moved_true), h = off(halved, moved_true);
                const std::string tag = speed > 0.05f ? "run" : "walk";
                dump(tag + "_true", moved_true);
                dump(tag + "_history_alone", alone);
                dump(tag + "_not_followed", guarded);
                dump(tag + "_no_trail", untrailed);
                dump(tag + "_default", all);
                std::printf("Torch lab, the character goes with its torch, %.1f cm a frame (the camera with it), the 16th "
                            "moving frame against the true picture of that moment (all / penumbra / more than 0.25 off): "
                            "the history without its guards %.4f / %.4f / %.2f%%; the default %.4f / %.4f / %.2f%% "
                            "(history held in the penumbra: %.2f of what it may); looked up where the ground was only "
                            "%.4f / %.4f / %.2f%%; with BB_LAMP_SHADOW_TRAIL=0 %.4f / %.4f / %.2f%% (held %.2f); the "
                            "default in the half-resolution build %.4f / %.4f / %.2f%% (held %.2f; its second pass "
                            "traced %.1f%% of its pixels on that frame)\n",
                            speed * 100.0f, a.all, a.penumbra, a.far, d.all, d.penumbra, d.far,
                            held_mean(all_held, moved_true), c.all, c.penumbra, c.far, e.all, e.penumbra, e.far,
                            held_mean(untrailed_held, moved_true), h.all, h.penumbra, h.far,
                            held_mean(halved_held, moved_true), traced_share(halved_did));
                {
                    // bbport (r52_follow-soft): the seams of the same pictures (new line; the
                    // line above is unchanged)
                    const Seam sa = seam(alone, moved_true, 8), sd = seam(all, moved_true, 8),
                               sc = seam(guarded, moved_true, 8), se = seam(untrailed, moved_true, 8),
                               sh8 = seam(halved, moved_true, 8), sh16 = seam(halved, moved_true, 16);
                    std::printf("Torch lab, the character goes with its torch, %.1f cm a frame, r52 seams "
                                "(BB_LAMP_SHADOW_FOLLOW_SOFT=%d): the mean step across the 8 px grid lines minus "
                                "the mean step elsewhere (all / penumbra): the history without its guards "
                                "%+.5f / %+.5f; the default %+.5f / %+.5f; looked up where the ground was only "
                                "%+.5f / %+.5f; with BB_LAMP_SHADOW_TRAIL=0 %+.5f / %+.5f; the default in the "
                                "half-resolution build %+.5f / %+.5f (across its 16 px lines %+.5f / %+.5f)\n",
                                speed * 100.0f, soft.follow_soft ? 1 : 0, sa.all, sa.penumbra, sd.all, sd.penumbra,
                                sc.all, sc.penumbra, se.all, se.penumbra, sh8.all, sh8.penumbra, sh16.all,
                                sh16.penumbra);
                }
                if (checked && !(d.all < a.all && d.penumbra < c.penumbra)) {
                    std::fprintf(stderr, "the guards, or following the lamp, do not help a carried torch\n");
                    return 1;
                }
                if (checked && !(h.all < HalfAllMost * d.all && h.penumbra < HalfPenumbraMost * d.penumbra)) {
                    std::fprintf(stderr, "a carried torch looks worse in the half-resolution build than at full resolution\n");
                    return 1;
                }
                // bbport (r57_lamp-window): the lattice scores (new lines; nothing above changes). Per
                // case and build: the history without its guards (no grid of its own: the reference),
                // BB_LAMP_SHADOW_WINDOW=1 (the default) and =0 (to try), whatever the environment says.
                // Checked (with the defaults):
                //  - the last frame's pictures with 1 and with 0 differ somewhere (else bit 21 does not
                //    reach the shader; the lab is deterministic, so equal pictures differ by 0);
                //  - with the soft follow, 0's window-phase score (x and y) at most 1.1 times the
                //    reference's (with BB_LAMP_SHADOW_FOLLOW_SOFT=0 the vote keeps the window).
                // Printed only, until a first run gives the numbers and their noise: whether 1's
                // window-phase score lies above 1.1 times the reference's (the grid the score is made
                // to see; "no" in every case means it does not see it here), and 0 against 1.
                // bbport (r60_lamp-centred-window): and BB_LAMP_SHADOW_WINDOW=2 (the window centred),
                // run with MODE_APART as the engine runs it (the others run without; the two modes
                // give the same picture, which the r60 apart line below compares once). 0's verdict is
                // now the folds' largest-over-smallest bin ratios, each against the reference's of the
                // same fold (r57's numbers: 0 within 1.005 of the reference's in every fold, 1 up to
                // 1.2 times it in the carried and walking-past cases; the window-phase score saw no
                // grid). A run "lines up with the grid" where a checked fold (x and y mod 8; at half
                // resolution mod 16 too; mod 2 is printed only) lies above GridMost times the
                // reference's. Checked (with the defaults): 0 never lines up with the soft follow.
                // Printed only, until a first GPU run gives their numbers (r57's rule: a check nobody
                // has measured could turn the default lab red): whether 2 lines up, judged only in a
                // case and build where 1 lines up ("blind" elsewhere: r57's numbers have 1 at 1.01 to
                // 1.06 with BB_LAMP_SHADOW_FOLLOW=0, too near the bound to see a grid); whether the
                // pictures with 2 and 1 differ (else bit 22 or the trace and resolve do not reach the
                // shader); whether MODE_APART changes the picture of 1 or 2.
                {
                    constexpr double GridMost = 1.05;
                    struct LatticeCase {
                        const char* name;
                        Move move;
                        bool follow;
                    };
                    Move standing = walk;
                    standing.carried = false;
                    const std::array<LatticeCase, 3> cases{{{"the character goes with its torch", walk, soft.follow},
                                                            {"the torch's lamp walks past standing casters", standing,
                                                             soft.follow},
                                                            {"the character goes with its torch, BB_LAMP_SHADOW_FOLLOW=0",
                                                             walk, false}}};
                    std::string lattice_fault, same_fault;
                    // bbport (r60_lamp-centred-window): printed only (see above)
                    std::string centred_fault, centred_same_fault, centred_apart_fault;
                    bool grid_seen = false;
                    unsigned judged_2 = 0, blind_2 = 0; // (case, build) pairs where 1 lines up; where it does not
                    for (const LatticeCase& lc : cases) {
                        for (const bool half_build : {false, true}) {
                            // (0 the reference, 1 BB_LAMP_SHADOW_WINDOW=1, 2 =0; bbport r60: 3 =2)
                            std::array<Vulkan::LampShadowTune, 4> tunes{plain, soft, soft, soft};
                            tunes[1].window = true;
                            tunes[0].window = tunes[2].window = false;
                            tunes[3].window = true;
                            tunes[0].window_centred = tunes[1].window_centred = tunes[2].window_centred = false;
                            tunes[3].window_centred = true;
                            for (auto& t : tunes) t.follow = lc.follow;
                            std::vector<std::uint8_t> mask;
                            mask.reserve(std::size_t(lc.move.frames) * W * H);
                            std::array<Lattice, 4> lattices{};
                            for (std::size_t r = 0; r < 4; ++r) {
                                lattices[r].mask = &mask;
                                lattices[r].record = r == 0;
                            }
                            at_half = half_build;
                            std::array<std::vector<float>, 4> last;
                            for (std::size_t r = 0; r < 4; ++r) {
                                at_apart = r == 3; // bbport (r60): 2 as the engine runs it
                                last[r] = moving(tunes[r], lc.move, nullptr, &lattices[r]);
                            }
                            at_apart = false;
                            // bbport (r60_lamp-centred-window): once (the first case, the first speed, both
                            // builds): 1 with MODE_APART and 2 without, against the runs above. Every pixel
                            // the same is what the modes must give (the light the pass moves is 0 + 1 * ratio
                            // in both); a difference is the apart path of the trace or the resolve.
                            if (&lc == &cases[0] && speed == 0.067f) {
                                at_apart = true;
                                const auto apart_1 = moving(tunes[1], lc.move);
                                at_apart = false;
                                const auto plain_2 = moving(tunes[3], lc.move);
                                std::array<std::size_t, 2> differ{};
                                std::array<double, 2> most{};
                                for (std::size_t i = 0; i < last[1].size(); ++i) {
                                    const double d1 = std::abs(double(apart_1[i]) - double(last[1][i]));
                                    const double d2 = std::abs(double(plain_2[i]) - double(last[3][i]));
                                    differ[0] += d1 > 0.0 ? 1 : 0;
                                    differ[1] += d2 > 0.0 ? 1 : 0;
                                    most[0] = std::max(most[0], d1);
                                    most[1] = std::max(most[1], d2);
                                }
                                std::printf("Torch lab, r60 apart, %s, %.1f cm a frame, %s: the last frame with MODE_APART "
                                            "against without (printed only; the same is expected): BB_LAMP_SHADOW_WINDOW=1 "
                                            "%zu pixels differ (most %.5f), =2 %zu pixels differ (most %.5f)\n",
                                            lc.name, speed * 100.0f, half_build ? "half-resolution build" : "full resolution",
                                            differ[0], most[0], differ[1], most[1]);
                                if (checked && centred_apart_fault.empty() && (differ[0] != 0 || differ[1] != 0)) {
                                    centred_apart_fault = lc.name;
                                }
                            }
                            at_half = false;
                            const std::vector<std::pair<int, unsigned>> folds =
                                half_build ? std::vector<std::pair<int, unsigned>>{{0, 8}, {1, 8}, {0, 16}, {1, 16}, {0, 2}, {1, 2}}
                                           : std::vector<std::pair<int, unsigned>>{{0, 8}, {1, 8}};
                            // bbport (r60_lamp-centred-window): each run's largest checked fold ratio
                            // over the reference's of the same fold (mod 2 not checked)
                            std::array<double, 4> over{};
                            for (std::size_t r = 1; r < 4; ++r) {
                                for (const auto& [axis, mod] : folds) {
                                    if (mod == 2) continue;
                                    over[r] = std::max(over[r], lattice_score(lattices[r], axis, mod) /
                                                                    std::max(lattice_score(lattices[0], axis, mod), 1e-12));
                                }
                            }
                            std::array<std::string, 4> text;
                            std::array<double, 4> phase{}; // the window-phase score, the larger of x and y
                            for (std::size_t r = 0; r < 4; ++r) {
                                phase[r] = std::max(window_score(lattices[r], 0), window_score(lattices[r], 1));
                                char part[96];
                                std::snprintf(part, sizeof(part), "window phases %.3f; largest over smallest bin ",
                                              phase[r]);
                                text[r] = part;
                                bool first_fold = true;
                                for (const auto& [axis, mod] : folds) {
                                    std::snprintf(part, sizeof(part), "%s%c%u %.3f", first_fold ? "" : ", ",
                                                  axis == 0 ? 'x' : 'y', mod, lattice_score(lattices[r], axis, mod));
                                    text[r] += part;
                                    first_fold = false;
                                }
                            }
                            double apart = 0;
                            std::size_t apart_n = 0;
                            for (std::size_t i = 0; i < last[1].size(); ++i) {
                                const double d = std::abs(double(last[1][i]) - double(last[2][i]));
                                apart += d;
                                apart_n += d > 0.01 ? 1 : 0;
                            }
                            apart /= double(std::max<std::size_t>(last[1].size(), 1));
                            // bbport (r60_lamp-centred-window): 2 against 1, as 0 against 1 above
                            double centred_apart = 0;
                            std::size_t centred_apart_n = 0;
                            for (std::size_t i = 0; i < last[1].size(); ++i) {
                                const double d = std::abs(double(last[1][i]) - double(last[3][i]));
                                centred_apart += d;
                                centred_apart_n += d > 0.01 ? 1 : 0;
                            }
                            centred_apart /= double(std::max<std::size_t>(last[1].size(), 1));
                            const bool seen = phase[1] > 1.1 * phase[0];
                            grid_seen = grid_seen || seen;
                            std::printf("Torch lab, r57 lattice, %s, %.1f cm a frame, %s (%u frames, on the steps where "
                                        "the history without its guards shows a penumbra or a wake; the mean step "
                                        "between neighbours: the window-phase score, bins 0, 3, 4, 5 over 1, 2, 6, 7 of "
                                        "the fold mod 8, the larger of x and y; and per fold mod %s the largest over the "
                                        "smallest bin): the history without its guards %s; BB_LAMP_SHADOW_WINDOW=1 %s; "
                                        "BB_LAMP_SHADOW_WINDOW=0 %s. 1 above 1.1 times the reference (the grid seen): "
                                        "%s; 0 over 1: %.3f; the last frame with 0 against 1: mean difference %.5f, "
                                        "%zu pixels apart by more than 0.01\n",
                                        lc.name, speed * 100.0f, half_build ? "half-resolution build" : "full resolution",
                                        lc.move.frames, half_build ? "8, 16 and 2" : "8", text[0].c_str(),
                                        text[1].c_str(), text[2].c_str(), seen ? "yes" : "no",
                                        phase[2] / std::max(phase[1], 1e-12), apart, apart_n);
                            // bbport (r60_lamp-centred-window): 2 is judged only where 1 lines up
                            const bool sees = over[1] > GridMost;
                            std::printf("Torch lab, r60 lattice, %s, %.1f cm a frame, %s: BB_LAMP_SHADOW_WINDOW=2 (with "
                                        "MODE_APART) %s. The largest checked fold ratio (mod %s) over the reference's of "
                                        "the same fold (above %.2f: lines up with the grid): 1 %.3f (%s), 0 %.3f (%s), 2 "
                                        "%.3f (%s); the last frame with 2 against 1: mean difference %.5f, %zu pixels "
                                        "apart by more than 0.01\n",
                                        lc.name, speed * 100.0f, half_build ? "half-resolution build" : "full resolution",
                                        text[3].c_str(), half_build ? "8 and 16" : "8", GridMost, over[1],
                                        sees ? "lines up" : "does not", over[2], over[2] > GridMost ? "lines up" : "does not",
                                        over[3],
                                        !sees                ? "blind: 1 does not line up here"
                                        : over[3] > GridMost ? "lines up"
                                                             : "does not",
                                        centred_apart, centred_apart_n);
                            judged_2 += sees ? 1u : 0u;
                            blind_2 += sees ? 0u : 1u;
                            if (!lc.move.carried) {
                                // A standing caster's penumbra under the walking lamp: is it darker or
                                // lighter on the mean than the true picture of the last frame (a frame
                                // cap that depends on this frame's ray would make it darker)?
                                const auto standing_true = truth(moved_view, soft, 64);
                                std::array<double, 3> bias{};
                                std::size_t n = 0;
                                for (std::size_t i = 0; i < standing_true.size(); ++i) {
                                    if (!(standing_true[i] > 0.05f && standing_true[i] < 0.95f)) continue;
                                    ++n;
                                    for (std::size_t r = 0; r < 3; ++r) bias[r] += double(last[r][i]) - standing_true[i];
                                }
                                for (double& b : bias) b /= double(std::max<std::size_t>(n, 1));
                                std::printf("Torch lab, r57, %s, %.1f cm a frame, %s: the last frame's mean of the picture "
                                            "minus the true one over the true penumbra (%zu pixels; below 0 darker; printed "
                                            "only): the history without its guards %+.4f; BB_LAMP_SHADOW_WINDOW=1 %+.4f; "
                                            "BB_LAMP_SHADOW_WINDOW=0 %+.4f\n",
                                            lc.name, speed * 100.0f, half_build ? "half-resolution build" : "full resolution",
                                            n, bias[0], bias[1], bias[2]);
                            }
                            const std::string where =
                                std::string(lc.name) + (half_build ? ", half-resolution build" : ", full resolution");
                            if (checked && same_fault.empty() && !(apart > 0.0)) same_fault = where;
                            // bbport (r60_lamp-centred-window): the verdict is the bin ratios (r57: the
                            // window-phase score within 1.1 times the reference's)
                            if (checked && soft.follow_soft && lattice_fault.empty() && !(over[2] <= GridMost)) {
                                lattice_fault = where;
                            }
                            if (checked && centred_same_fault.empty() && !(centred_apart > 0.0)) centred_same_fault = where;
                            if (checked && sees && centred_fault.empty() && !(over[3] <= GridMost)) centred_fault = where;
                        }
                    }
                    std::printf("Torch lab, r57 lattice, %.1f cm a frame: the window's grid is seen by the score with "
                                "BB_LAMP_SHADOW_WINDOW=1 in %s case (printed only; \"no case\" means the score is blind "
                                "to it in this lab)\n",
                                speed * 100.0f, grid_seen ? "at least one" : "no");
                    if (!same_fault.empty()) {
                        std::fprintf(stderr, "BB_LAMP_SHADOW_WINDOW=0 and =1 give the same picture: word 0 bit 21 does not "
                                             "reach the shader (%s, %.1f cm a frame)\n", same_fault.c_str(), speed * 100.0f);
                        return 1;
                    }
                    if (!lattice_fault.empty()) {
                        std::fprintf(stderr, "without the window a moving shadow still lines up with the window's grid (%s, "
                                             "%.1f cm a frame)\n", lattice_fault.c_str(), speed * 100.0f);
                        return 1;
                    }
                    // bbport (r60_lamp-centred-window): printed only, until a first GPU run gives the
                    // numbers (each "would fail" below is to become a check then)
                    std::printf("Torch lab, r60 lattice, %.1f cm a frame (printed only): BB_LAMP_SHADOW_WINDOW=1 lines up "
                                "with the grid in %u of %u case and build pairs (2 is judged in those, blind in the "
                                "other %u); 2 lines up where 1 does: %s; 2 and 1 give the same picture: %s; MODE_APART "
                                "changes the picture: %s\n",
                                speed * 100.0f, judged_2, judged_2 + blind_2, blind_2,
                                centred_fault.empty() ? "no" : ("would fail (" + centred_fault + ")").c_str(),
                                centred_same_fault.empty() ? "no" : ("would fail (" + centred_same_fault + ")").c_str(),
                                centred_apart_fault.empty() ? "no" : ("would fail (" + centred_apart_fault + ")").c_str());
                }
            }
            for (const bool two : {false, true}) {
                second = two;
                std::vector<float> held;
                const Move other{.other = 0.05f};
                const auto alone = moving(plain, other), all = moving(soft, other, &held);
                // bbport (r44_half-area-lamp): the default once more in the half-resolution build. Its
                // first pass bounds a pixel's history by the answers of the blocks around it, which
                // lie twice as far apart as the pixels around a full-resolution pixel, so behind a
                // shadow's moving edge that one pixel in four could trail as dots: its error is
                // given for those pixels and for the other three apart (off's part), beside the
                // full-resolution pass's on the same pixels.
                at_half = true;
                const auto halved = moving(soft, other);
                const HalfDid halved_did = moved_did;
                at_half = false;
                const auto moved_true = truth(moved_view, soft);
                const Off a = off(alone, moved_true), d = off(all, moved_true), e = off(held, moved_true),
                          h = off(halved, moved_true);
                const std::array<Off, 2> half_part{off(halved, moved_true, 1), off(halved, moved_true, 0)},
                                         full_part{off(all, moved_true, 1), off(all, moved_true, 0)};
                const std::string tag = two ? "other_two_lamps" : "other";
                dump(tag + "_true", moved_true);
                dump(tag + "_history_alone", alone);
                dump(tag + "_default", all);
                dump(tag + "_default_upscaled", held);
                dump(tag + "_half", halved);
                // And the frames one by one without a history, through the stand-in alone.
                Vulkan::LampShadowTune single = soft;
                single.history = 0.0f;
                std::vector<float> bare;
                const auto raw_frame = moving(single, other, &bare);
                const Off f = off(bare, moved_true), g = off(raw_frame, moved_true);
                dump(tag + "_no_history_upscaled", bare);
                std::printf("Torch lab, a figure walks under %s (5 cm a frame), the 16th moving frame against the true "
                            "picture of that moment: the history without its guards %.4f / %.4f / %.2f%%; the default "
                            "%.4f / %.4f / %.2f%%; one frame's rays alone %.4f / %.4f / %.2f%%; through the upscaler's "
                            "stand-in: the default %.4f / %.4f / %.2f%%, the rays alone %.4f / %.4f / %.2f%%\n",
                            two ? "the still torch and a second lamp" : "the still torch", a.all, a.penumbra, a.far,
                            d.all, d.penumbra, d.far, g.all, g.penumbra, g.far, e.all, e.penumbra, e.far, f.all,
                            f.penumbra, f.far);
                if (checked && !(d.all < a.all && d.all < g.all)) {
                    std::fprintf(stderr, "the history's guards do not help a moving caster (%s)\n", tag.c_str());
                    return 1;
                }
                std::printf("Torch lab, that figure under %s in the half-resolution build: %.4f / %.4f / %.2f%% (its second "
                            "pass traced %.1f%% of its pixels on that frame); pixel (2x,2y) of each block alone %.4f / "
                            "%.4f / %.2f%%, the other three %.4f / %.4f / %.2f%% (at full resolution %.4f / %.4f / %.2f%% "
                            "and %.4f / %.4f / %.2f%%)\n",
                            two ? "the still torch and a second lamp" : "the still torch", h.all, h.penumbra, h.far,
                            traced_share(halved_did), half_part[0].all, half_part[0].penumbra, half_part[0].far,
                            half_part[1].all, half_part[1].penumbra, half_part[1].far, full_part[0].all,
                            full_part[0].penumbra, full_part[0].far, full_part[1].all, full_part[1].penumbra,
                            full_part[1].far);
                if (checked && !(h.all < HalfAllMost * d.all && h.penumbra < HalfPenumbraMost * d.penumbra)) {
                    std::fprintf(stderr, "a moving caster looks worse in the half-resolution build than at full resolution (%s)\n",
                                 tag.c_str());
                    return 1;
                }
                if (checked && !(half_part[0].all < HalfAllMost * half_part[1].all &&
                                 half_part[0].penumbra < HalfPenumbraMost * half_part[1].penumbra)) {
                    std::fprintf(stderr, "behind a moving caster the half-resolution build's first-pass pixels trail the other "
                                         "three of their blocks (%s)\n", tag.c_str());
                    return 1;
                }
            }
            // A caster is gone from one frame to the next (the second figure, set 30 m off): how
            // much of the old picture is left where the true one changed by more than 0.15, after
            // 1, 2, 4, 8 and 16 frames. With one lamp, and with two (where a shadow is only a part
            // of the pixel's light).
            for (const bool two : {false, true}) {
                second = two;
                // (which: 0 the default, 1 the history without its guards; bbport r44_half-area-lamp:
                // 2 the default in the half-resolution build; bbport r57_lamp-window: 3 the default
                // with BB_LAMP_SHADOW_WINDOW=0, printed only; bbport r60_lamp-centred-window: 4 and 5
                // with BB_LAMP_SHADOW_WINDOW=2 at full and at half resolution, with MODE_APART as the
                // engine runs it; printed beside the default's bounds, not yet checked)
                std::array<std::array<double, 5>, 6> left{};
                place(view, 0.0f, 0.0f);
                const auto old_true = truth(view, soft, 64);
                place(view, 0.0f, 30.0f);
                const auto new_true = truth(view, soft, 64);
                Vulkan::LampShadowTune own = soft;
                own.window = false;
                Vulkan::LampShadowTune centred = soft; // bbport (r60)
                centred.window = centred.window_centred = true;
                for (int which = 0; which < 6; ++which) {
                    const Vulkan::LampShadowTune& tune = which == 1 ? plain : which == 3 ? own : which >= 4 ? centred : soft;
                    at_half = which == 2 || which == 5;
                    at_apart = which >= 4; // bbport (r60)
                    restart();
                    place(view, 0.0f, 0.0f);
                    for (unsigned k = 0; k < 24; ++k) frame(view, tune);
                    place(view, 0.0f, 30.0f);
                    unsigned slot = 0;
                    for (unsigned k = 1; k <= 16; ++k) {
                        frame(view, tune);
                        if (k != 1 && k != 2 && k != 4 && k != 8 && k != 16) continue;
                        const auto now = values();
                        double sum = 0;
                        std::size_t changed = 0;
                        for (std::size_t i = 0; i < now.size(); ++i) {
                            const double change = double(old_true[i]) - new_true[i];
                            if (std::abs(change) > 0.15) {
                                sum += (double(now[i]) - new_true[i]) / change;
                                ++changed;
                            }
                        }
                        left[which][slot++] = sum / double(std::max<std::size_t>(changed, 1));
                    }
                }
                at_half = false;
                at_apart = false;
                std::printf("Torch lab, a figure is gone from one frame to the next, %s: share of the old picture left "
                            "where the true one changed, after 1 / 2 / 4 / 8 / 16 frames: the default %.3f / %.3f / %.3f "
                            "/ %.3f / %.3f; the history without its guards %.3f / %.3f / %.3f / %.3f / %.3f; the default "
                            "in the half-resolution build %.3f / %.3f / %.3f / %.3f / %.3f\n",
                            two ? "two lamps" : "one lamp", left[0][0], left[0][1], left[0][2], left[0][3], left[0][4],
                            left[1][0], left[1][1], left[1][2], left[1][3], left[1][4], left[2][0], left[2][1],
                            left[2][2], left[2][3], left[2][4]);
                // bbport (r57_lamp-window): new line, no check (no bound exists for it yet; the
                // checks below take the knobs as the environment has them).
                std::printf("Torch lab, r57, a figure is gone from one frame to the next, %s: the same with "
                            "BB_LAMP_SHADOW_WINDOW=0 (not checked; the per-pixel bound cuts only a change of more than "
                            "about 0.86): %.3f / %.3f / %.3f / %.3f / %.3f\n",
                            two ? "two lamps" : "one lamp", left[3][0], left[3][1], left[3][2], left[3][3], left[3][4]);
                if (checked && !(left[0][1] < 0.2 && left[0][2] < 0.15 && left[0][2] < 0.5 * left[1][2])) {
                    std::fprintf(stderr, "a shadow that is gone lingers (%s)\n", two ? "two lamps" : "one lamp");
                    return 1;
                }
                if (checked && !(left[2][1] < 0.2 && left[2][2] < 0.15 && left[2][2] < 0.5 * left[1][2])) {
                    std::fprintf(stderr, "a shadow that is gone lingers in the half-resolution build (%s)\n",
                                 two ? "two lamps" : "one lamp");
                    return 1;
                }
                // bbport (r60_lamp-centred-window): the window centred is meant to bind as the confined
                // one: the default's bounds (which 0 fails with two lamps), printed only until a first
                // GPU run gives the numbers
                const auto within = [&](std::size_t k) {
                    return left[k][1] < 0.2 && left[k][2] < 0.15 && left[k][2] < 0.5 * left[1][2];
                };
                std::printf("Torch lab, r60, a figure is gone from one frame to the next, %s: the same with "
                            "BB_LAMP_SHADOW_WINDOW=2 and MODE_APART %.3f / %.3f / %.3f / %.3f / %.3f (%s the default's "
                            "bounds); in the half-resolution build %.3f / %.3f / %.3f / %.3f / %.3f (%s them); printed "
                            "only\n",
                            two ? "two lamps" : "one lamp", left[4][0], left[4][1], left[4][2], left[4][3], left[4][4],
                            within(4) ? "within" : "outside", left[5][0], left[5][1], left[5][2], left[5][3], left[5][4],
                            within(5) ? "within" : "outside");
            }
            second = false;
            // A flame that flickers: the torch's lamp is up to 2 cm off its place, anew every frame,
            // over a still scene.
            {
                const Move shaken{.shake = 0.02f, .frames = 24};
                Move anchored = shaken;
                anchored.follow = false;
                const auto all = moving(soft, shaken);
                const auto all_held = moved_held;
                const auto unfollowed = moving(soft, anchored);
                // bbport (r44_half-area-lamp): the default once more in the half-resolution build
                at_half = true;
                const auto halved = moving(soft, shaken);
                const auto halved_held = moved_held;
                const HalfDid halved_did = moved_did;
                at_half = false;
                const auto moved_true = truth(moved_view, soft);
                wobble = {0, 0, 0};
                const Off d = off(all, moved_true), c = off(unfollowed, moved_true), h = off(halved, moved_true);
                dump("flicker_true", moved_true);
                dump("flicker_default", all);
                dump("flicker_half", halved);
                std::printf("Torch lab, the torch's lamp is up to 2 cm off its place, anew every frame, the 24th frame "
                            "against its true picture: the default %.4f / %.4f / %.2f%% (history held in the penumbra: "
                            "%.2f of what it may); looked up where the ground was only %.4f / %.4f / %.2f%%; the default "
                            "in the half-resolution build %.4f / %.4f / %.2f%% (held %.2f; its second pass traced %.1f%% "
                            "of its pixels on that frame)\n",
                            d.all, d.penumbra, d.far, held_mean(all_held, moved_true), c.all, c.penumbra, c.far, h.all,
                            h.penumbra, h.far, held_mean(halved_held, moved_true), traced_share(halved_did));
                if (checked && !(h.all < HalfAllMost * d.all && h.penumbra < HalfPenumbraMost * d.penumbra)) {
                    std::fprintf(stderr, "a flickering lamp looks worse in the half-resolution build than at full resolution\n");
                    return 1;
                }
            }

            // 5. The camera moves 3 cm a frame over a still scene: the history follows it (the
            // way back to the camera of the frame before), or, as a check that it matters, does
            // not (as if the camera had stood still).
            {
                // (which: 0 the history follows the camera, 1 it does not; bbport r44_half-area-lamp:
                // 2 as 0 in the half-resolution build)
                std::array<Off, 3> offs{};
                std::vector<float> pan_true;
                HalfDid pan_did{};
                for (const int which : {0, 1, 2}) {
                    at_half = which == 2;
                    restart();
                    Views before = view;
                    for (unsigned k = 0; k <= 24; ++k) {
                        const Views now = camera(0.03f * float(k), 0.0f);
                        place(now, 0.0f, 0.0f);
                        if (k == 24) half_zero();
                        frame(now, soft, which != 1 ? &before : nullptr);
                        before = now;
                    }
                    const auto picture = values();
                    if (which == 0) {
                        pan_true = truth(before, soft);
                        dump("pan_true", pan_true);
                        dump("pan_default", picture);
                    } else if (which == 2) {
                        pan_did = half_did();
                        dump("pan_half", picture);
                    }
                    offs[std::size_t(which)] = off(picture, pan_true);
                }
                at_half = false;
                std::printf("Torch lab, the camera moves 3 cm a frame, the 25th frame against its true picture: %.4f / "
                            "%.4f / %.2f%%; with the history left where it was on screen %.4f / %.4f / %.2f%%; in the "
                            "half-resolution build %.4f / %.4f / %.2f%% (its second pass traced %.1f%% of its pixels on "
                            "that frame)\n",
                            offs[0].all, offs[0].penumbra, offs[0].far, offs[1].all, offs[1].penumbra, offs[1].far,
                            offs[2].all, offs[2].penumbra, offs[2].far, traced_share(pan_did));
                if (checked && !(offs[0].penumbra < offs[1].penumbra)) {
                    std::fprintf(stderr, "the history does not follow the camera\n");
                    return 1;
                }
                if (checked && !(offs[2].all < HalfAllMost * offs[0].all && offs[2].penumbra < HalfPenumbraMost * offs[0].penumbra)) {
                    std::fprintf(stderr, "a moving camera looks worse in the half-resolution build than at full resolution\n");
                    return 1;
                }
            }

            // 6. The half-resolution build on the still scene (bbport r44_half-area-lamp; its
            // moving scenes are in 4 and 5).
            place(view, 0.0f, 0.0f);
            // Without a history it keeps the point lamp whatever the radius (one bare ray to a
            // point of the lamp's disc cannot be shared by the four pixels of a block), and it is the
            // picture of the radius zeroed: what the pass hands it while experiment
            // 2305843009213693952 is set, the half-resolution pass of before r44.
            HalfDid point_did{};
            {
                run(view, {.tune = &soft, .frame = 3, .half = true});
                const auto bare_picture = values();
                half_zero();
                run(view, {.tune = &point, .frame = 3, .half = true});
                point_did = half_did();
                const auto half_point = values();
                std::size_t differ = 0;
                for (std::size_t i = 0; i < half_point.size(); ++i) {
                    differ += std::abs(half_point[i] - point_picture[i]) > 1.0f / 64.0f ? 1 : 0;
                }
                std::printf("Torch lab: the half-resolution build with point lamps (the radius zeroed, as with experiment "
                            "2305843009213693952 set) differs from the point lamp at full resolution on %zu pixels; with "
                            "the default tuning and no history it shows %s\n",
                            differ, bare_picture == half_point ? "that same picture" : "another picture");
                if (differ * 500 > half_point.size() || bare_picture != half_point) {
                    std::fprintf(stderr, "the half-resolution build without a history does not show the point lamp\n");
                    return 1;
                }
            }
            // With its history it shows the area lamp: 48 frames as in 2, against the same true
            // picture and beside the full-resolution pass's numbers, and what its two passes did on
            // the first frame (no history yet: bare rays) and on the last.
            {
                restart();
                at_half = true;
                std::vector<float> half1, half16;
                HalfDid first_did{};
                for (unsigned k = 0; k < 48; ++k) {
                    if (k == 0 || k == 47) half_zero();
                    frame(view, soft);
                    if (k == 0) {
                        first_did = half_did();
                        half1 = values();
                    }
                    if (k == 15) half16 = values();
                }
                const HalfDid did = half_did();
                const auto half48 = values();
                const auto half_held = held_view(view, soft);
                at_half = false;
                dump("half_16_frames", half16);
                dump("half_48_frames", half48);
                const Off h16 = off(half16, reference), h48 = off(half48, reference);
                double half_mean = 0, half_band = 0;
                for (const float p : half48) half_mean += p / double(half48.size());
                for (const std::size_t i : band) half_band += half48[i] / double(std::max<std::size_t>(band.size(), 1));
                std::size_t half_dark = 0;
                for (const std::size_t i : body) half_dark += half48[i] < 0.25f ? 1 : 0;
                std::printf("Torch lab, the half-resolution build with its history, the still scene against the true "
                            "picture (all / penumbra / more than 0.25 off): 16 frames %.4f / %.4f / %.2f%%, 48 frames "
                            "%.4f / %.4f / %.2f%% (at full resolution %.4f / %.4f / %.2f%% and %.4f / %.4f / %.2f%%); "
                            "history held in the penumbra %.2f of what it may; mean light %.4f (true %.4f); the stick's "
                            "band keeps %.3f of the light (at full resolution %.3f, true %.3f), %zu of the %zu dark pixels "
                            "of the bodies' shadows are still below 0.25\n",
                            h16.all, h16.penumbra, h16.far, h48.all, h48.penumbra, h48.far, off16.all, off16.penumbra,
                            off16.far, off48.all, off48.penumbra, off48.far, held_mean(half_held, reference), half_mean,
                            mean_true, half_band, band_light, band_true, half_dark, body.size());
                const auto tell = [&](const char* when, const HalfDid& n) {
                    std::printf("Torch lab, the half-resolution build, %s: the first pass traced %u pixels with %u rays; "
                                "of the second pass's pixels %u took their block's answer and %u cast their own rays (%u "
                                "rays; %u a block near them had no answer, %u the blocks' answers differed, %u another "
                                "surface): %.1f%% traced\n",
                                when, n[1], n[2], n[4], n[5], n[6], n[10], n[11], n[12], traced_share(n));
                };
                tell("point lamps without a history (before r44)", point_did);
                tell("the area lamp's first frame (no history to read)", first_did);
                tell("the area lamp's 48th frame", did);
                // The first frame has bare rays (so has the frame after a camera cut). The second pass
                // shares them only where those of the nine blocks around a pixel agree, so no block
                // stands out from the blocks around it; the frame is held to the bound of the other
                // scenes against the full-resolution pass's first frame.
                const Off h1 = off(half1, reference);
                dump("half_1_frame", half1);
                std::printf("Torch lab, the half-resolution build's first frame (no history to read) against the true "
                            "picture: %.4f / %.4f / %.2f%% (at full resolution %.4f / %.4f / %.2f%%)\n",
                            h1.all, h1.penumbra, h1.far, off1.all, off1.penumbra, off1.far);
                if (checked && !(h1.all < HalfAllMost * off1.all && h1.penumbra < HalfPenumbraMost * off1.penumbra)) {
                    std::fprintf(stderr, "the half-resolution build's first frame is worse than the full-resolution pass's\n");
                    return 1;
                }
                if (checked && (std::abs(half_mean - mean_true) > 0.004 || half_band < 0.5 || half_dark * 2 < body.size())) {
                    std::fprintf(stderr, "the half-resolution build does not show the area lamp: mean light %.4f against "
                                         "the true %.4f, %.3f of the light in the stick's band, %zu of %zu dark pixels\n",
                                 half_mean, mean_true, half_band, half_dark, body.size());
                    return 1;
                }
                if (checked && !(h48.all < HalfAllMost * off48.all && h48.penumbra < HalfPenumbraMost * off48.penumbra)) {
                    std::fprintf(stderr, "the still scene looks worse in the half-resolution build than at full resolution\n");
                    return 1;
                }
                // (A second pass that shared nothing would be the full-resolution pass in two
                // dispatches; one that traced nothing would have no penumbra.)
                if (checked && (did[4] == 0 || did[5] == 0 || did[5] >= did[4])) {
                    std::fprintf(stderr, "the half-resolution build's second pass shares too little, or traces nothing\n");
                    return 1;
                }
            }

            // 7. The cost here (a small scene; --speed has the heavy one): the fastest of 40 runs
            // taken in turn, the history's clear included.
            {
                std::array<double, 5> best{1e9, 1e9, 1e9, 1e9, 1e9};
                restart();
                for (int i = 0; i < 40; ++i) {
                    best[0] = std::min(best[0], run(view, {.frame = unsigned(i)}));
                    best[1] = std::min(best[1], run(view, {.tune = &point, .frame = unsigned(i)}));
                    best[2] = std::min(best[2], frame(view, soft));
                }
                // bbport (r44_half-area-lamp): the half-resolution build, with point lamps (before
                // r44) and with the area lamp and its history (once that has settled: its first
                // frames trace more), without its counters
                restart();
                at_half = true;
                half_count = false;
                for (int i = 0; i < 48; ++i) {
                    best[3] = std::min(best[3], run(view, {.tune = &point, .frame = unsigned(i), .half = true}));
                    const double ms = frame(view, soft);
                    if (i >= 8) best[4] = std::min(best[4], ms);
                }
                half_count = true;
                at_half = false;
                std::printf("Torch lab: mode 0 of this shader (the experiment bit's path; not the shader before r41) %.3f ms, the point lamp %.3f ms, the area lamp with its "
                            "history %.3f ms; the half-resolution build: with point lamps %.3f ms, with the area lamp "
                            "and its history %.3f ms\n", best[0], best[1], best[2], best[3], best[4]);
                // bbport (r60_lamp-centred-window): the area lamp with its history, the window confined
                // (1) and centred (2), at full and at half resolution (settled, without counters, with
                // MODE_APART as the engine runs it); printed only, a small scene
                std::array<Vulkan::LampShadowTune, 2> windows{soft, soft};
                windows[0].window = true;
                windows[0].window_centred = false;
                windows[1].window = windows[1].window_centred = true;
                std::array<double, 4> window_best{1e9, 1e9, 1e9, 1e9};
                half_count = false;
                at_apart = true;
                for (int w = 0; w < 2; ++w) {
                    for (const bool h : {false, true}) {
                        restart();
                        at_half = h;
                        for (int i = 0; i < 48; ++i) {
                            const double ms = frame(view, windows[std::size_t(w)]);
                            if (i >= 8) window_best[std::size_t(w * 2 + (h ? 1 : 0))] = std::min(window_best[std::size_t(w * 2 + (h ? 1 : 0))], ms);
                        }
                    }
                }
                at_half = false;
                at_apart = false;
                half_count = true;
                std::printf("Torch lab, r60: the area lamp with its history, BB_LAMP_SHADOW_WINDOW=1 %.3f ms, =2 %.3f ms; "
                            "the half-resolution build =1 %.3f ms, =2 %.3f ms (printed only)\n",
                            window_best[0], window_best[2], window_best[1], window_best[3]);
            }
            vk.destroy_as(vk.device, tlas.handle, nullptr);
            vk.Free(tlas.instances); vk.Free(tlas.storage); vk.Free(tlas.scratch);
            std::puts(checked ? "torch lab: ok" : "torch lab: done, not checked");
            return 0;
        }
        std::vector<std::array<double, 3>> lamp_ms(variants.size()), sun_ms(variants.size());
        std::array<double, 3> per_tile_ms{}, pick_ms{}, reuse_ms{}, reuse_error{};
        std::array<std::array<double, 2>, 3> pick_error{};
        // bbport (r41_lamp-shadows): per camera, on casters a lamp ray can hit, for the street
        // lamps and for the torch lamps: ms of mode 0 and of the default repair (picked lamps);
        // mean lamp light kept by mode 0, by the repair with a point lamp and by the repair
        // (every lamp traced). Pixels on which two runs of mode 0 differ and on which the old
        // tuning under MODE_REPAIR differs from mode 0 (picked); mean lamp light kept with the
        // inverse-square weights; pixels a torch leaves dark as a point lamp and repaired.
        // bbport (r42_lamp-soft): the default repair is the area lamp now: timed with its history
        // (third: as a point lamp, BB_LAMP_SHADOW_SOFT=0), its light and its dark pixels taken
        // from the mean of 16 frames.
        std::array<std::array<double, 3>, 3> repair_ms{}, torch_ms{};
        std::array<std::array<double, 3>, 3> repair_kept{}, torch_kept{};
        std::array<std::array<std::size_t, 2>, 3> repair_differ{}, torch_dark{};
        std::array<double, 3> inverse_kept{};
        std::vector<double> tlas_ms(variants.size());
        double lit_sum = 0;
        unsigned tile_sum = 0;
        for (std::size_t cam = 0; cam < cameras.size(); ++cam) {
            const Views views = MakeViews(cameras[cam][0], cameras[cam][1], sun);
            std::vector<LampPush> tiles;
            auto* words = static_cast<float*>(lights.data);
            for (int r = 0; r < 4; ++r)
                for (int k = 0; k < 4; ++k) words[r * 4 + k] = views.inv_proj.at(r, k);
            unsigned used = 16;
            const float radius = 9.0f;
            for (float z = 2.0f; z < 100.0f; z += 6.5f) {
                for (const float x : {-7.0f, 7.0f, 0.0f}) {
                    if (x == 0.0f && int(z) % 3 != 0) continue;
                    const Vec3 world{x, x == 0.0f ? 1.2f : 3.5f, z + (x > 0 ? 3.0f : 0.0f)};
                    Vec3 v{};
                    for (int r = 0; r < 3; ++r) {
                        const float value = views.view.at(r, 0) * world.x + views.view.at(r, 1) * world.y +
                                            views.view.at(r, 2) * world.z + views.view.at(r, 3);
                        (r == 0 ? v.x : r == 1 ? v.y : v.z) = value;
                    }
                    if (v.z < -radius) continue;
                    float x0 = 0, y0 = 0, x1 = float(W), y1 = float(H);
                    if (v.z - radius > 0.1f) {
                        x0 = float(W); y0 = float(H); x1 = 0; y1 = 0;
                        for (int c = 0; c < 8; ++c) {
                            const Vec3 corner{v.x + (c & 1 ? radius : -radius), v.y + (c & 2 ? radius : -radius),
                                              v.z + (c & 4 ? radius : -radius)};
                            const float nx = views.proj.at(0, 0) * corner.x / corner.z;
                            const float ny = views.proj.at(1, 1) * corner.y / corner.z;
                            const float px = (nx * 0.5f + 0.5f) * W, py = (0.5f - ny * 0.5f) * H;
                            x0 = std::min(x0, px); x1 = std::max(x1, px);
                            y0 = std::min(y0, py); y1 = std::max(y1, py);
                        }
                    }
                    LampPush push;
                    push.rect = {std::clamp(int(x0), 0, int(W)), std::clamp(int(y0), 0, int(H)),
                                 std::clamp(int(x1) + 1, 0, int(W)), std::clamp(int(y1) + 1, 0, int(H))};
                    if (push.rect[0] >= push.rect[2] || push.rect[1] >= push.rect[3]) continue;
                    push.first_light = used;
                    const std::array<float, 16> light{v.x, v.y, v.z, 1.0f / (radius * radius), 1.0f, 0.8f, 0.6f};
                    std::memcpy(words + used, light.data(), sizeof(light));
                    used += 16;
                    tiles.push_back(push);
                }
            }
            tile_sum += unsigned(tiles.size());
            const unsigned table = used;
            std::array<int, 4> covered{int(W), int(H), 0, 0};
            for (const LampPush& tile : tiles) {
                const std::array<std::uint32_t, 8> row{unsigned(tile.rect[0]), unsigned(tile.rect[1]), unsigned(tile.rect[2]),
                                                       unsigned(tile.rect[3]), tile.first_light, 1u, 0u, 0u};
                std::memcpy(words + used, row.data(), sizeof(row));
                used += 8;
                covered = {std::min(covered[0], tile.rect[0]), std::min(covered[1], tile.rect[1]),
                           std::max(covered[2], tile.rect[2]), std::max(covered[3], tile.rect[3])};
            }
            for (std::size_t at = 0; at < variants.size(); ++at) {
                const Variant& variant = variants[at];
                Tlas tlas = make_tlas(variant.doubled ? 2 * n : n, variant.flags);
                std::vector<double> builds;
                for (int i = 0; i < 9; ++i) builds.push_back(build_tlas(tlas, views.view, variant.flags, variant.doubled));
                tlas_ms[at] += Median(builds) / cameras.size();
                if (at == 0) {
                    lab.Prepare(tlas.handle, views);
                }
                std::vector<double> sun_samples, lamp_samples;
                for (int i = 0; i < 15; ++i) {
                    vk.Begin();
                    vk.Stamp(0);
                    RtPush p;
                    p.rays = 2;
                    lab.Rt(tlas.handle, p);
                    vk.Stamp(1);
                    vk.Barrier();
                    sun_samples.push_back(vk.End());
                }
                const unsigned history_at = used;
                // bbport (r41_lamp-shadows): more ways to run the pass. tune: with MODE_REPAIR:
                // its words go after the history block, their place into the mode word, and the
                // world's axes come from this camera's view matrix (as PointShadow::Flush does);
                // without it the mode word is 0, as before. inverse_square: the weights' curve.
                // engine_bias: the ray start offset the engine pushes (the tuning's, 0.03 without
                // one) in place of the lab's 0.02. torch: the torch lamps (written after the
                // tuning words by the block that uses them) in place of the street lamps.
                struct LampRun {
                    const Vulkan::LampShadowTune* tune = nullptr;
                    bool inverse_square = false;
                    bool engine_bias = false;
                    bool torch = false;
                    // bbport (r42_lamp-soft): with a history (parity) and a tuning: the history
                    // averages the ratio over the frames (HISTORY_BLEND), as the engine's does
                    // for the area lamp.
                    bool blend = false;
                };
                constexpr unsigned MaxTorches = 8;
                const unsigned tune_at = used + 30 + Vulkan::LampHistoryTailWords; // after the history block
                const unsigned torch_at = tune_at + Vulkan::LampTuneWordCount;
                unsigned torch_count = 0;
                // bbport (r60_lamp-centred-window): this section runs the build without CENTRED only
                // (lamp.pipeline, one dispatch), which does not read word 0 bit 22: with
                // BB_LAMP_SHADOW_WINDOW=2 in the environment it measures the window of 1 here. The
                // torch lab (--lamps) runs the centred builds.
                const auto run_lamps = [&](bool per_tile, unsigned pick = 0, unsigned frame = 0, int parity = -1,
                                           LampRun more = {}) {
                    if (more.tune) {
                        const auto tune_words =
                            Vulkan::LampTuneWords(*more.tune, more.inverse_square, 0.05f, views.view.m.data(), frame);
                        std::memcpy(reinterpret_cast<std::uint32_t*>(words) + tune_at, tune_words.data(),
                                    sizeof(tune_words));
                    }
                    if (parity >= 0) {
                        auto* block = reinterpret_cast<std::uint32_t*>(words) + history_at;
                        block[0] = frame == 0 ? 2u : 3u;
                        block[1] = frame;
                        const std::array<float, 12> identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
                        std::memcpy(block + 2, identity.data(), sizeof(identity));
                        std::memcpy(block + 14, views.proj.m.data(), 64);
                        if (more.blend && more.tune) { // bbport (r42_lamp-soft): words 30 to 33
                            block[0] |= 4u;
                            const auto tail = Vulkan::LampHistoryTail(*more.tune);
                            std::memcpy(block + 30, tail.data(), sizeof(tail));
                        }
                    }
                    vk.Begin();
                    VkClearColorValue one{};
                    one.float32[0] = one.float32[1] = one.float32[2] = 1.0f;
                    const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
                    vkCmdClearColorImage(vk.cmd, lamp_images[0].image, VK_IMAGE_LAYOUT_GENERAL, &one, 1, &range);
                    vkCmdClearColorImage(vk.cmd, lamp_images[2].image, VK_IMAGE_LAYOUT_GENERAL, &one, 1, &range);
                    vk.Barrier();
                    VkDescriptorBufferInfo data{lights.buffer, 0,
                                                (tune_at + Vulkan::LampTuneWordCount + MaxTorches * 24) * 4};
                    VkDescriptorImageInfo depth{vk.sampler, lab.depth.view, VK_IMAGE_LAYOUT_GENERAL};
                    std::array<VkDescriptorImageInfo, 4> images{};
                    for (int k = 0; k < 4; ++k) images[k] = {{}, lamp_images[k].view, VK_IMAGE_LAYOUT_GENERAL};
                    VkWriteDescriptorSetAccelerationStructureKHR as{.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET_ACCELERATION_STRUCTURE_KHR,
                        .accelerationStructureCount = 1, .pAccelerationStructures = &tlas.handle};
                    const int cur_history = parity < 0 ? 0 : parity;
                    VkDescriptorImageInfo history_prev{{}, history[cur_history ^ 1].view, VK_IMAGE_LAYOUT_GENERAL};
                    VkDescriptorImageInfo history_cur{{}, history[cur_history].view, VK_IMAGE_LAYOUT_GENERAL};
                    // bbport (r52_follow-soft): the follow state, taken in turn with the history
                    VkDescriptorImageInfo follow_prev{{}, follow[cur_history ^ 1].view, VK_IMAGE_LAYOUT_GENERAL};
                    VkDescriptorImageInfo follow_cur{{}, follow[cur_history].view, VK_IMAGE_LAYOUT_GENERAL};
                    std::array<VkWriteDescriptorSet, 11> writes{};
                    for (unsigned k = 0; k < 11; ++k) writes[k] = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = k, .descriptorCount = 1};
                    writes[0].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER; writes[0].pBufferInfo = &data;
                    writes[1].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER; writes[1].pImageInfo = &depth;
                    for (int k = 0; k < 4; ++k) { writes[2 + k].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[2 + k].pImageInfo = &images[k]; }
                    writes[6].descriptorType = VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR; writes[6].pNext = &as;
                    writes[7].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[7].pImageInfo = &history_prev;
                    writes[8].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[8].pImageInfo = &history_cur;
                    writes[9].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[9].pImageInfo = &follow_prev;
                    writes[10].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[10].pImageInfo = &follow_cur;
                    const auto snapshot = [&](std::array<int, 4> r) {
                        const VkImageCopy region{.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .srcOffset = {r[0], r[1], 0},
                            .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .dstOffset = {r[0], r[1], 0},
                            .extent = {unsigned(r[2] - r[0]), unsigned(r[3] - r[1]), 1}};
                        vkCmdCopyImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, lamp_images[1].image, VK_IMAGE_LAYOUT_GENERAL, 1, &region);
                        vkCmdCopyImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, lamp_images[3].image, VK_IMAGE_LAYOUT_GENERAL, 1, &region);
                        vk.Barrier();
                    };
                    const auto dispatch = [&](LampPush push) {
                        vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lamp.pipeline);
                        vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lamp.layout, 0, 11, writes.data());
                        vkCmdPushConstants(vk.cmd, lamp.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                        const unsigned gx0 = unsigned(push.rect[0]) / 8, gy0 = unsigned(push.rect[1]) / 8;
                        const unsigned gx1 = (unsigned(push.rect[2]) + 7) / 8, gy1 = (unsigned(push.rect[3]) + 7) / 8;
                        vkCmdDispatchBase(vk.cmd, gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                        vk.Barrier();
                    };
                    vk.Stamp(0);
                    if (parity >= 0) {
                        VkClearColorValue zero{};
                        vkCmdClearColorImage(vk.cmd, history[cur_history].image, VK_IMAGE_LAYOUT_GENERAL, &zero, 1, &range);
                        vk.Barrier();
                    }
                    if (per_tile) {
                        for (std::size_t t = 0; t < tiles.size(); ++t) {
                            snapshot(tiles[t].rect);
                            LampPush push = tiles[t];
                            push.first_light = table + unsigned(t) * 8;
                            push.count = 1;
                            dispatch(push);
                        }
                    } else if (!tiles.empty()) {
                        snapshot({0, 0, int(W), int(H)});
                        LampPush push = tiles[0];
                        push.first_light = table;
                        push.count = unsigned(tiles.size());
                        push.rect = covered;
                        push.steps = pick;
                        push.frame = frame;
                        if (parity >= 0) std::memcpy(&push.length, &history_at, 4);
                        if (more.torch) { // bbport (r41_lamp-shadows)
                            push.first_light = torch_at + torch_count * 16;
                            push.count = torch_count;
                            push.rect = {0, 0, int(W), int(H)};
                        }
                        if (more.engine_bias) {
                            push.bias = more.tune ? more.tune->bias_m : 0.03f;
                        }
                        if (more.tune) { // MODE_REPAIR | place << 8
                            const unsigned mode = 16u | tune_at << 8;
                            std::memcpy(&push.thickness, &mode, 4);
                        }
                        dispatch(push);
                    }
                    vk.Stamp(1);
                    vk.Barrier();
                    return vk.End();
                };
                if (at == 1) {
                    std::vector<double> per_tile;
                    for (int i = 0; i < 15; ++i) per_tile.push_back(run_lamps(true));
                    per_tile_ms[cam] = Median(per_tile);
                    const auto lamp_values = [&] {
                        const auto raw = lab.Read(lamp_images[0], VK_FORMAT_R32_SFLOAT);
                        std::vector<float> out(raw.size());
                        for (std::size_t k = 0; k < raw.size(); ++k) {
                            std::uint32_t bits;
                            std::memcpy(&bits, &raw[k], 4);
                            out[k] = decode(bits);
                        }
                        return out;
                    };
                    run_lamps(false);
                    const auto exact = lamp_values();
                    std::vector<double> picked;
                    for (int i = 0; i < 15; ++i) picked.push_back(run_lamps(false, 1, unsigned(i)));
                    pick_ms[cam] = Median(picked);
                    std::vector<float> average(exact.size(), 0.0f);
                    double one_frame = 0, sixteen = 0;
                    for (unsigned f = 0; f < 16; ++f) {
                        run_lamps(false, 1, f);
                        const auto one = lamp_values();
                        for (std::size_t k = 0; k < one.size(); ++k) {
                            average[k] += one[k] / 16.0f;
                            if (f == 0) one_frame += std::abs(double(one[k]) - exact[k]);
                        }
                    }
                    for (std::size_t k = 0; k < exact.size(); ++k) sixteen += std::abs(double(average[k]) - exact[k]);
                    pick_error[cam] = {one_frame / double(exact.size()), sixteen / double(exact.size())};
                    std::vector<double> reused;
                    std::vector<float> reuse_average(exact.size(), 0.0f);
                    for (unsigned f = 0; f < 24; ++f) {
                        const double ms = run_lamps(false, 1, f, int(f & 1u));
                        if (f >= 8) reused.push_back(ms);
                        if (f >= 8) {
                            const auto one = lamp_values();
                            for (std::size_t k = 0; k < one.size(); ++k) reuse_average[k] += one[k] / 16.0f;
                        }
                    }
                    reuse_ms[cam] = Median(reused);
                    double reuse_sum = 0;
                    for (std::size_t k = 0; k < exact.size(); ++k) reuse_sum += std::abs(double(reuse_average[k]) - exact[k]);
                    reuse_error[cam] = reuse_sum / double(exact.size());
                    // bbport (r41_lamp-shadows): MODE_REPAIR, on casters a lamp ray can hit. The
                    // lab's instances carry masks 1 to 3 and a lamp ray asks for 4 (vk_rt_shadow.cpp
                    // LampMask): no lamp ray of the runs above and below hits anything, and they
                    // stay as they are. For these runs the instances get the lamp bit as well.
                    //  - The old weights, a point lamp and no self skip under MODE_REPAIR give the
                    //    very numbers of mode 0 when every lamp is traced. With picked lamps the
                    //    second lamp depends on the order in which a workgroup's invocations list
                    //    its tiles, which is not fixed (two runs of mode 0 differ on some pixels),
                    //    so there the difference is bounded, not zero.
                    //  - bbport (r42_lamp-soft): the point lamp (BB_LAMP_SHADOW_SOFT=0) gives the
                    //    same picture whatever the frame counter; the area lamp's picture is the
                    //    mean of 16 frames here (one ray a lamp a frame, to a point of the lamp's
                    //    disc that moves with the frame counter).
                    //  - The torch lamps: one beside each character (a capsule 1.8 m tall and 0.6 m
                    //    wide), 0.45 m from its side at 1.4 m, reaching 5 m, as a hand torch is
                    //    held: the caster is near the lamp, which is where a point lamp magnifies
                    //    it (the street lamps stand metres from what they shadow). The same
                    //    checks, and the body keeps most of its shadow.
                    //  - What the default repair costs against mode 0 of this same shader (the
                    //    experiment bit's path; the shader before r41 is not in this build), with
                    //    the engine's ray start offset, runs taken in turn: the area lamp with
                    //    its history (cleared and written every frame, read from the second on),
                    //    and the point lamp.
                    {
                        build_tlas(tlas, views.view, variant.flags, variant.doubled, 4);
                        {
                            auto* raw = reinterpret_cast<std::uint32_t*>(words);
                            torch_count = 0;
                            for (unsigned i = 0; i < n && torch_count < MaxTorches; ++i) {
                                if (!scene.meshes[i].skinned) continue;
                                const Vec3 world{scene.meshes[i].position.x + 0.75f, 1.4f, scene.meshes[i].position.z};
                                std::array<float, 16> light{};
                                for (int r = 0; r < 3; ++r)
                                    light[r] = views.view.at(r, 0) * world.x + views.view.at(r, 1) * world.y +
                                               views.view.at(r, 2) * world.z + views.view.at(r, 3);
                                light[3] = 1.0f / 25.0f;
                                light[4] = 1.0f; light[5] = 0.8f; light[6] = 0.6f;
                                std::memcpy(raw + torch_at + torch_count * 16, light.data(), sizeof(light));
                                ++torch_count;
                            }
                            for (unsigned t = 0; t < torch_count; ++t) {
                                const std::array<std::uint32_t, 8> row{0u, 0u, unsigned(W), unsigned(H),
                                                                       torch_at + t * 16, 1u, 0u, 0u};
                                std::memcpy(raw + torch_at + torch_count * 16 + t * 8, row.data(), sizeof(row));
                            }
                        }
                        if (torch_count == 0) {
                            std::fprintf(stderr, "the lab scene has no character for a torch lamp\n");
                            return 1;
                        }
                        Vulkan::LampShadowTune same;
                        same.weights = false;
                        same.radius_m = 0.0f;
                        same.self_m = 0.0f;
                        // (bbport r52_follow-soft: same.follow_soft stays at its default; these runs
                        // hand no history block, and without one the bit changes nothing.)
                        const auto differing = [&](unsigned pick, const Vulkan::LampShadowTune* tune, bool torch) {
                            run_lamps(false, pick, 0, -1, {.torch = torch});
                            const auto before = lamp_values();
                            run_lamps(false, pick, 0, -1, {.tune = tune, .torch = torch});
                            const auto after = lamp_values();
                            std::size_t differ = 0;
                            for (std::size_t k = 0; k < before.size(); ++k) differ += before[k] != after[k] ? 1 : 0;
                            return differ;
                        };
                        for (const bool torch : {false, true}) {
                            if (const std::size_t differ = differing(0, &same, torch); differ != 0) {
                                std::fprintf(stderr, "every lamp traced: lamp repair with the old tuning differs from "
                                                     "mode 0 on %zu pixels (camera %zu, %s lamps)\n",
                                             differ, cam, torch ? "torch" : "street");
                                return 1;
                            }
                        }
                        const std::size_t noise = differing(1, nullptr, false);
                        const std::size_t picked = differing(1, &same, false);
                        if (picked > 4 * noise + 64) {
                            std::fprintf(stderr, "picked lamps: lamp repair with the old tuning differs from mode 0 on "
                                                 "%zu pixels, two runs of mode 0 on %zu (camera %zu)\n", picked, noise, cam);
                            return 1;
                        }
                        const auto kept = [](const std::vector<float>& values) {
                            double sum = 0;
                            for (const float v : values) sum += v;
                            return sum / double(values.size());
                        };
                        Vulkan::LampShadowTune repaired, point;
                        point.radius_m = 0.0f;
                        // bbport (r52_follow-soft): BB_LAMP_SHADOW_FOLLOW_SOFT as the environment has
                        // it (0: the passes below run as before r52)
                        repaired.follow_soft = point.follow_soft =
                            Vulkan::ReadLampShadowTune([](const char* name) -> const char* { return std::getenv(name); })
                                .follow_soft;
                        for (const bool torch : {false, true}) {
                            run_lamps(false, 0, 0, -1, {.torch = torch});
                            const double kept_before = kept(lamp_values());
                            run_lamps(false, 0, 0, -1, {.tune = &point, .torch = torch});
                            const auto with_point = lamp_values();
                            run_lamps(false, 0, 5, -1, {.tune = &point, .torch = torch});
                            if (lamp_values() != with_point) {
                                std::fprintf(stderr, "the point lamp's picture changes with the frame counter (camera "
                                                     "%zu, %s lamps)\n", cam, torch ? "torch" : "street");
                                return 1;
                            }
                            std::vector<float> with_radius(with_point.size(), 0.0f);
                            for (unsigned f = 0; f < 16; ++f) {
                                run_lamps(false, 0, f, -1, {.tune = &repaired, .torch = torch});
                                const auto one = lamp_values();
                                for (std::size_t k = 0; k < one.size(); ++k) with_radius[k] += one[k] / 16.0f;
                            }
                            std::size_t dark_point = 0, dark_radius = 0;
                            for (std::size_t k = 0; k < with_point.size(); ++k) {
                                dark_point += with_point[k] < 0.25f ? 1 : 0;
                                dark_radius += with_radius[k] < 0.25f ? 1 : 0;
                            }
                            (torch ? torch_kept : repair_kept)[cam] = {kept_before, kept(with_point), kept(with_radius)};
                            if (torch) {
                                torch_dark[cam] = {dark_point, dark_radius};
                                if (dark_radius * 2 < dark_point) {
                                    std::fprintf(stderr, "torch lamps: the default radius left %zu dark pixels of the "
                                                         "point lamp's %zu (camera %zu)\n", dark_radius, dark_point, cam);
                                    return 1;
                                }
                            }
                            std::vector<double> plain, fixed, as_point;
                            for (int i = 0; i < 40; ++i) {
                                plain.push_back(run_lamps(false, 1, unsigned(i), -1, {.engine_bias = true, .torch = torch}));
                                fixed.push_back(run_lamps(false, 1, unsigned(i), i & 1,
                                                          {.tune = &repaired, .engine_bias = true, .torch = torch, .blend = true}));
                                as_point.push_back(run_lamps(false, 1, unsigned(i), -1,
                                                             {.tune = &point, .engine_bias = true, .torch = torch}));
                            }
                            // The fastest run of each: this lab's lamp pass times jump between runs
                            // by several times, and the median moves with them.
                            (torch ? torch_ms : repair_ms)[cam] = {*std::min_element(plain.begin(), plain.end()),
                                                                   *std::min_element(fixed.begin(), fixed.end()),
                                                                   *std::min_element(as_point.begin(), as_point.end())};
                        }
                        // The inverse-square weights (startup_local_inverse_square): they run and
                        // give a ratio.
                        run_lamps(false, 0, 0, -1, {.tune = &repaired, .inverse_square = true});
                        const auto inverse = lamp_values();
                        for (const float v : inverse) {
                            if (!(v >= 0.0f && v <= 1.0001f)) {
                                std::fprintf(stderr, "inverse-square weights: a pixel holds %g (camera %zu)\n", double(v), cam);
                                return 1;
                            }
                        }
                        inverse_kept[cam] = kept(inverse);
                        repair_differ[cam] = {noise, picked};
                        build_tlas(tlas, views.view, variant.flags, variant.doubled); // as it was
                    }
                }
                for (int i = 0; i < 15; ++i) lamp_samples.push_back(run_lamps(false));
                sun_ms[at][cam] = Median(sun_samples);
                lamp_ms[at][cam] = Median(lamp_samples);
                if (at == 0) {
                    const auto out = lab.Read(lamp_images[0], VK_FORMAT_R32_SFLOAT);
                    double lit = 0;
                    for (const float f : out) {
                        std::uint32_t bits;
                        std::memcpy(&bits, &f, 4);
                        lit += decode(bits);
                    }
                    lit_sum += lit / double(out.size()) / cameras.size();
                }
                vk.destroy_as(vk.device, tlas.handle, nullptr);
                vk.Free(tlas.instances); vk.Free(tlas.storage); vk.Free(tlas.scratch);
            }
        }
        std::printf("%u lamp tiles over %zu cameras, mean lamp light kept %.4f\n", tile_sum, cameras.size(), lit_sum);
        std::printf("Lamps on the fast-trace TLAS, a snapshot, dispatch and barriers per tile: %.3f %.3f %.3f ms\n",
                    per_tile_ms[0], per_tile_ms[1], per_tile_ms[2]);
        std::printf("Lamps, strongest lamp plus one picked by weight: %.3f %.3f %.3f ms; mean error against every lamp "
                    "%.4f %.4f %.4f in one frame, %.4f %.4f %.4f over 16 frames\n",
                    pick_ms[0], pick_ms[1], pick_ms[2], pick_error[0][0], pick_error[1][0], pick_error[2][0],
                    pick_error[0][1], pick_error[1][1], pick_error[2][1]);
        std::printf("Lamps, picked, reusing still 8x8 blocks (still camera, frames 8-23): %.3f %.3f %.3f ms; mean error "
                    "against every lamp over 16 frames %.4f %.4f %.4f\n",
                    reuse_ms[0], reuse_ms[1], reuse_ms[2], reuse_error[0], reuse_error[1], reuse_error[2]);
        // bbport (r41_lamp-shadows)
        std::printf("Lamps that hit (instances with the lamp bit), picked, repaired (r42, default tuning: the area "
                    "lamp with its history): %.3f %.3f %.3f ms, as a point lamp %.3f %.3f %.3f ms, against %.3f %.3f "
                    "%.3f ms of mode 0 of this shader (the experiment bit's path; the "
                    "fastest of 40 runs taken in turn, the engine's ray start offset); mean lamp light kept with "
                    "every lamp traced: mode 0 "
                    "%.4f %.4f %.4f, repaired with a point lamp %.4f %.4f %.4f, repaired (16 frames) %.4f %.4f %.4f, "
                    "repaired with inverse-square weights %.4f %.4f %.4f; the old "
                    "tuning under MODE_REPAIR gave mode 0's numbers with every lamp traced, and with picked lamps "
                    "differed on %zu %zu %zu pixels where two runs of mode 0 differed on %zu %zu %zu\n",
                    repair_ms[0][1], repair_ms[1][1], repair_ms[2][1], repair_ms[0][2], repair_ms[1][2],
                    repair_ms[2][2], repair_ms[0][0], repair_ms[1][0],
                    repair_ms[2][0], repair_kept[0][0], repair_kept[1][0], repair_kept[2][0], repair_kept[0][1],
                    repair_kept[1][1], repair_kept[2][1], repair_kept[0][2], repair_kept[1][2], repair_kept[2][2],
                    inverse_kept[0], inverse_kept[1], inverse_kept[2],
                    repair_differ[0][1], repair_differ[1][1], repair_differ[2][1], repair_differ[0][0],
                    repair_differ[1][0], repair_differ[2][0]);
        std::printf("Torch lamps (0.45 m from a character's side, reach 5 m), picked, repaired: %.3f %.3f %.3f ms, "
                    "as a point lamp %.3f %.3f %.3f ms, "
                    "against %.3f %.3f %.3f ms of mode 0 of this shader; mean lamp light kept with every lamp traced: "
                    "mode 0 %.4f %.4f %.4f, repaired with a point lamp %.4f %.4f %.4f, repaired (16 frames) %.4f %.4f "
                    "%.4f; dark pixels repaired %zu %zu %zu, with a point lamp %zu %zu %zu\n",
                    torch_ms[0][1], torch_ms[1][1], torch_ms[2][1], torch_ms[0][2], torch_ms[1][2], torch_ms[2][2],
                    torch_ms[0][0], torch_ms[1][0], torch_ms[2][0],
                    torch_kept[0][0], torch_kept[1][0], torch_kept[2][0], torch_kept[0][1], torch_kept[1][1],
                    torch_kept[2][1], torch_kept[0][2], torch_kept[1][2], torch_kept[2][2], torch_dark[0][1],
                    torch_dark[1][1], torch_dark[2][1], torch_dark[0][0], torch_dark[1][0], torch_dark[2][0]);
        std::printf("%-36s %9s %21s %21s\n", "", "TLAS ms", "sun 2 rays ms", "lamp rays ms");
        for (std::size_t at = 0; at < variants.size(); ++at) {
            std::printf("%-36s %9.3f   %5.3f %5.3f %5.3f   %5.3f %5.3f %5.3f\n", variants[at].name, tlas_ms[at],
                        sun_ms[at][0], sun_ms[at][1], sun_ms[at][2], lamp_ms[at][0], lamp_ms[at][1], lamp_ms[at][2]);
        }
        return 0;
    }
    for (const auto [total, draws] : std::array<std::array<unsigned, 2>, 3>{{{500000, 400}, {1500000, 800}, {4000000, 1200}}}) {
        Scene scene{vk, MakeScene(total, draws)};
        scene.Create(Trace | Update);
        std::printf("\n== Scene: %u triangles in %zu BLAS\n", scene.triangles, scene.blas.size());
        const auto report_builds = [&](const char* name, VkBuildAccelerationStructureFlagsKHR flags) {
            scene.Sizes(flags);
            scene.Allocate();
            std::vector<double> times;
            for (int i = 0; i < 5; ++i) times.push_back(scene.BuildAll(flags));
            std::printf("All BLAS %-22s build %8.2f ms, %7.1f MB, scratch %7.1f MB\n", name, Median(times),
                        double(scene.total_bytes) / 1048576.0, double(scene.total_scratch) / 1048576.0);
        };
        report_builds("fast build", Fast);
        report_builds("fast trace", Trace);
        report_builds("fast build + update", Fast | Update);
        {
            std::vector<double> refit, rebuild;
            for (int i = 0; i < 9; ++i) refit.push_back(scene.Refit(Fast | Update, true));
            for (int i = 0; i < 9; ++i) rebuild.push_back(scene.Refit(Fast | Update, false));
            std::printf("6 characters, 180k triangles: refit %.3f ms, rebuild %.3f ms\n", Median(refit), Median(rebuild));
        }
        for (const bool fast_blas : {false, true}) {
            const VkBuildAccelerationStructureFlagsKHR flags = fast_blas ? Fast : Trace;
            scene.Sizes(flags);
            scene.Allocate();
            scene.BuildAll(flags);
            Tlas tlas = CreateTlas(vk, scene);
            std::array<double, 5> sums{};
            std::array<Metric, 6> metrics{};
            double tlas_ms = 0;
            for (std::size_t cam = 0; cam < cameras.size(); ++cam) {
                const Views views = MakeViews(cameras[cam][0], cameras[cam][1], sun);
                std::vector<double> times;
                for (int i = 0; i < 9; ++i) times.push_back(BuildTlas(vk, tlas, scene, views.view, true));
                tlas_ms += Median(times) / cameras.size();
                lab.Prepare(tlas.handle, views);
                const auto depth = lab.Read(lab.depth, VK_FORMAT_R32_SFLOAT);
                if (fast_blas) continue;
                const auto covered = std::count_if(depth.begin(), depth.end(), [](float d) { return d < 1.0f; });
                if (covered < depth.size() / 4) {
                    std::fprintf(stderr, "camera %zu sees geometry in only %lld pixels\n", cam, (long long)covered);
                    return 1;
                }
                std::vector<float> truth(W * H, 0.0f);
                for (unsigned frame = 0; frame < 64; ++frame) {
                    vk.Begin();
                    RtPush p;
                    p.frame = frame;
                    p.rays = 16;
                    lab.Rt(tlas.handle, p);
                    vk.Barrier();
                    vk.Stamp(0); vk.Stamp(1);
                    vk.End();
                    const auto one = lab.Read(lab.raw, VK_FORMAT_R8_UNORM);
                    for (std::size_t i = 0; i < truth.size(); ++i) truth[i] += one[i] / 64.0f;
                }
                const auto timed = [&](auto&& body) {
                    std::vector<double> samples;
                    for (int i = 0; i < 16; ++i) {
                        vk.Begin();
                        vk.Stamp(0);
                        body();
                        vk.Stamp(1);
                        vk.Barrier();
                        samples.push_back(vk.End());
                    }
                    return Median(samples);
                };
                const auto add = [&](Metric& into, const Metric& m) {
                    into.mean += m.mean / cameras.size(); into.off10 += m.off10 / cameras.size();
                    into.off25 += m.off25 / cameras.size(); into.signed_bias += m.signed_bias / cameras.size();
                };
                vk.Begin(); lab.ClearShadow(); vk.Stamp(0); vk.Stamp(1); vk.End();
                sums[0] += timed([&] { lab.Pcss({}); }) / cameras.size();
                vk.Begin(); lab.ClearShadow(); vk.Stamp(0); vk.Stamp(1); vk.End();
                vk.Begin(); lab.Pcss({}); vk.Barrier(); vk.Stamp(0); vk.Stamp(1); vk.End();
                const auto pcss = lab.Read(lab.shadow, VK_FORMAT_R8G8B8A8_UNORM);
                add(metrics[0], Compare(truth, pcss, depth));
                unsigned at = 1;
                std::vector<float> rt_best;
                for (unsigned rays : {1u, 2u, 4u, 8u}) {
                    RtPush p;
                    p.rays = rays;
                    sums[at] += timed([&] { lab.Rt(tlas.handle, p); }) / cameras.size();
                    vk.Begin(); lab.Rt(tlas.handle, p); vk.Barrier(); vk.Stamp(0); vk.Stamp(1); vk.End();
                    vk.Begin(); lab.ClearShadow(); lab.Filter(2); vk.Barrier(); vk.Stamp(0); vk.Stamp(1); vk.End();
                    const auto out = lab.Read(lab.shadow, VK_FORMAT_R8G8B8A8_UNORM);
                    add(metrics[at], Compare(truth, out, depth));
                    if (rays == 4) rt_best = out;
                    ++at;
                }
                metrics[5].off10 += timed([&] { lab.Filter(2); }) / cameras.size();
                if (dump && total == 1500000 && cam < 3) {
                    const std::string base = std::string(dump) + "/cam" + std::to_string(cam);
                    WritePgm((base + "_truth.pgm").c_str(), truth);
                    WritePgm((base + "_pcss.pgm").c_str(), pcss);
                    WritePgm((base + "_rt4.pgm").c_str(), rt_best);
                }
            }
            std::printf("TLAS %zu instances on %s BLAS: %.3f ms\n", scene.blas.size(), fast_blas ? "fast-build" : "fast-trace", tlas_ms);
            if (fast_blas) {
                const Views views = MakeViews(cameras[0][0], cameras[0][1], sun);
                BuildTlas(vk, tlas, scene, views.view, true);
                lab.Prepare(tlas.handle, views);
                std::vector<double> samples;
                for (int i = 0; i < 16; ++i) {
                    vk.Begin();
                    vk.Stamp(0);
                    RtPush p;
                    p.rays = 2;
                    lab.Rt(tlas.handle, p);
                    vk.Stamp(1);
                    vk.Barrier();
                    samples.push_back(vk.End());
                }
                std::printf("2 rays per pixel on fast-build BLAS, camera 0: %.3f ms\n", Median(samples));
            } else {
                std::printf("%-20s %8s %9s %8s %8s %8s\n", "Against 1024 rays", "GPU ms", "mean err", ">0.10 %", ">0.25 %", "bias");
                std::printf("%-20s %8.3f %9.4f %8.2f %8.2f %+8.4f\n", "PCSS 4096 atlas", sums[0], metrics[0].mean, metrics[0].off10, metrics[0].off25, metrics[0].signed_bias);
                unsigned at = 1;
                for (unsigned rays : {1u, 2u, 4u, 8u}) {
                    std::printf("RT %u rays + filter  %8.3f %9.4f %8.2f %8.2f %+8.4f\n", rays, sums[at] + metrics[5].off10, metrics[at].mean, metrics[at].off10, metrics[at].off25, metrics[at].signed_bias);
                    ++at;
                }
                std::printf("Filter alone: %.3f ms\n", metrics[5].off10);
            }
            vk.destroy_as(vk.device, tlas.handle, nullptr);
            vk.Free(tlas.instances); vk.Free(tlas.storage); vk.Free(tlas.scratch);
        }
        for (auto& b : scene.blas) if (b.handle) vk.destroy_as(vk.device, b.handle, nullptr);
        vk.Free(scene.storage); vk.Free(scene.scratch); vk.Free(scene.geometry); vk.Free(scene.staging);
    }
    return 0;
}
