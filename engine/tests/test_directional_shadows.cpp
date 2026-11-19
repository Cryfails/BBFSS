// SPDX-License-Identifier: GPL-3.0-or-later
#include <vulkan/vulkan.h>
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <limits>
#include <vector>
#include "video_core/host_shaders/contact_shadow_comp.h"
#include "../gpu/shadps4/video_core/renderer_vulkan/vk_bend_sss.h"

namespace {
#define CHECK(call) do { if ((call) != VK_SUCCESS) { std::fprintf(stderr, "%s failed\n", #call); std::exit(1); } } while (false)
unsigned W = 17, H = 9;
constexpr unsigned Atlas = 64, CbBase = 4, UbBase = 8;
struct Push {
    unsigned offsets = (CbBase * 4) | ((UbBase * 4) << 8), frame = 0;
    float width = W, height = H;
    std::array<float, 4> light_coordinate{};
    std::array<int, 2> wave_offset{};
    float surface = 0.005f, bilinear = 0.02f, strength = 0.75f, contrast = 2;
    unsigned debug = 0, contact = 0, pcss = 0;
    float light = 0.02f, maximum = 0.3f, minimum = 0.0f, bias = 0.04f;
    unsigned filter = 1;
    float blend = 0;
    float bend_scale = 0; // 0: Bend shadows not distance-faded
};
static_assert(sizeof(Push) == 96);
constexpr unsigned PushBytes = 96;
struct Buffer { VkBuffer buffer{}; VkDeviceMemory memory{}; void* data{}; };
struct Image { VkImage image{}; VkDeviceMemory memory{}; VkImageView view{}; };

struct Test {
    VkInstance instance{};
    VkPhysicalDevice gpu{};
    VkDevice device{};
    VkQueue queue{};
    VkPhysicalDeviceMemoryProperties memory{};
    VkCommandPool pool{};
    VkCommandBuffer cmd{};
    VkDescriptorSetLayout set_layout{};
    VkPipelineLayout layout{};
    VkPipeline pipeline{};
    VkSampler sampler{};
    VkQueryPool timing{};
    float timestamp_period = 0;
    unsigned timestamp_bits = 0;
    PFN_vkCmdPushDescriptorSetKHR descriptors{};
    std::vector<Buffer> buffers;
    std::vector<Image> images;

    unsigned Memory(unsigned bits, VkMemoryPropertyFlags flags) {
        for (unsigned i = 0; i < memory.memoryTypeCount; ++i)
            if ((bits & (1u << i)) && (memory.memoryTypes[i].propertyFlags & flags) == flags) return i;
        std::abort();
    }
    Buffer MakeBuffer(unsigned bytes) {
        Buffer b;
        VkBufferCreateInfo info{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = bytes,
            .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                     VK_BUFFER_USAGE_TRANSFER_DST_BIT};
        CHECK(vkCreateBuffer(device, &info, nullptr, &b.buffer));
        VkMemoryRequirements req;
        vkGetBufferMemoryRequirements(device, b.buffer, &req);
        VkMemoryAllocateInfo alloc{.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
            .allocationSize = req.size, .memoryTypeIndex = Memory(req.memoryTypeBits,
                VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
        CHECK(vkAllocateMemory(device, &alloc, nullptr, &b.memory));
        CHECK(vkBindBufferMemory(device, b.buffer, b.memory, 0));
        CHECK(vkMapMemory(device, b.memory, 0, VK_WHOLE_SIZE, 0, &b.data));
        std::memset(b.data, 0, bytes);
        buffers.push_back(b);
        return b;
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
        images.push_back(i);
        return i;
    }
    Test() {
        VkApplicationInfo app{.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
            .pApplicationName = "directional-shadow-test", .apiVersion = VK_API_VERSION_1_3};
        VkInstanceCreateInfo ci{.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app};
        CHECK(vkCreateInstance(&ci, nullptr, &instance));
        unsigned count = 0;
        CHECK(vkEnumeratePhysicalDevices(instance, &count, nullptr));
        std::vector<VkPhysicalDevice> devices(count);
        CHECK(vkEnumeratePhysicalDevices(instance, &count, devices.data()));
        assert(count);
        gpu = devices[0];
        vkGetPhysicalDeviceMemoryProperties(gpu, &memory);
        unsigned family_count = 0, family = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(gpu, &family_count, nullptr);
        std::vector<VkQueueFamilyProperties> families(family_count);
        vkGetPhysicalDeviceQueueFamilyProperties(gpu, &family_count, families.data());
        while (family < family_count && !(families[family].queueFlags & VK_QUEUE_COMPUTE_BIT)) ++family;
        assert(family < family_count);
        timestamp_bits = families[family].timestampValidBits;
        VkPhysicalDeviceProperties properties{};
        vkGetPhysicalDeviceProperties(gpu, &properties);
        timestamp_period = properties.limits.timestampPeriod;
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
        assert(descriptors);
        VkCommandPoolCreateInfo pi{.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
            .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, .queueFamilyIndex = family};
        CHECK(vkCreateCommandPool(device, &pi, nullptr, &pool));
        VkCommandBufferAllocateInfo ai{.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
            .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
        CHECK(vkAllocateCommandBuffers(device, &ai, &cmd));
        const std::array<VkDescriptorType, 5> types{
            VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
            VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
            VK_DESCRIPTOR_TYPE_STORAGE_BUFFER};
        std::array<VkDescriptorSetLayoutBinding, 5> bindings{};
        for (unsigned i = 0; i < 5; ++i) bindings[i] = {i, types[i], 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr};
        VkDescriptorSetLayoutCreateInfo si{.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
            .flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR,
            .bindingCount = 5, .pBindings = bindings.data()};
        CHECK(vkCreateDescriptorSetLayout(device, &si, nullptr, &set_layout));
        VkPushConstantRange range{VK_SHADER_STAGE_COMPUTE_BIT, 0, PushBytes};
        VkPipelineLayoutCreateInfo li{.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
            .setLayoutCount = 1, .pSetLayouts = &set_layout, .pushConstantRangeCount = 1, .pPushConstantRanges = &range};
        CHECK(vkCreatePipelineLayout(device, &li, nullptr, &layout));
        VkShaderModule module;
        VkShaderModuleCreateInfo mi{.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
            .codeSize = sizeof(CONTACT_SHADOW_COMP), .pCode = CONTACT_SHADOW_COMP};
        CHECK(vkCreateShaderModule(device, &mi, nullptr, &module));
        VkComputePipelineCreateInfo pc{.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
            .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
                .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = module, .pName = "main"}, .layout = layout};
        CHECK(vkCreateComputePipelines(device, {}, 1, &pc, nullptr, &pipeline));
        vkDestroyShaderModule(device, module, nullptr);
        VkSamplerCreateInfo sm{.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO,
            .magFilter = VK_FILTER_NEAREST, .minFilter = VK_FILTER_NEAREST,
            .addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_BORDER,
            .addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_BORDER,
            .addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_BORDER,
            .borderColor = VK_BORDER_COLOR_FLOAT_OPAQUE_WHITE};
        CHECK(vkCreateSampler(device, &sm, nullptr, &sampler));
        if (timestamp_bits) {
            VkQueryPoolCreateInfo query{.sType = VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,
                .queryType = VK_QUERY_TYPE_TIMESTAMP, .queryCount = 2};
            CHECK(vkCreateQueryPool(device, &query, nullptr, &timing));
        }
    }
    void Barrier(VkImage image, VkImageLayout old_layout, VkImageLayout next) {
        VkImageMemoryBarrier b{.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            .srcAccessMask = old_layout == VK_IMAGE_LAYOUT_UNDEFINED ? 0u : VK_ACCESS_MEMORY_WRITE_BIT,
            .dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT,
            .oldLayout = old_layout, .newLayout = next, .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = image,
            .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
        vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
            0, 0, nullptr, 0, nullptr, 1, &b);
    }
    ~Test() {
        vkDeviceWaitIdle(device);
        for (auto i : images) {
            vkDestroyImageView(device, i.view, nullptr);
            vkDestroyImage(device, i.image, nullptr);
            vkFreeMemory(device, i.memory, nullptr);
        }
        for (auto b : buffers) {
            vkUnmapMemory(device, b.memory);
            vkDestroyBuffer(device, b.buffer, nullptr);
            vkFreeMemory(device, b.memory, nullptr);
        }
        vkDestroySampler(device, sampler, nullptr);
        if (timing) vkDestroyQueryPool(device, timing, nullptr);
        vkDestroyPipeline(device, pipeline, nullptr);
        vkDestroyPipelineLayout(device, layout, nullptr);
        vkDestroyDescriptorSetLayout(device, set_layout, nullptr);
        vkDestroyCommandPool(device, pool, nullptr);
        vkDestroyDevice(device, nullptr);
        vkDestroyInstance(instance, nullptr);
    }
};
}

int main(int argc, char** argv) {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    const bool benchmark = argc > 1 && std::strcmp(argv[1], "--benchmark") == 0;
    if (benchmark) { W = 1280; H = 720; }
    Test t;
    auto cb = t.MakeBuffer(1024), ub = t.MakeBuffer(1024);
    auto scene = t.MakeBuffer(W * H * 4), atlas = t.MakeBuffer(Atlas * Atlas * 4);
    auto pixels = t.MakeBuffer(W * H * 4), result = t.MakeBuffer(W * H * 4);
    auto depth = t.MakeImage(W, H, VK_FORMAT_R32_SFLOAT);
    auto map = t.MakeImage(Atlas, Atlas, VK_FORMAT_R32_SFLOAT);
    auto output = t.MakeImage(W, H, VK_FORMAT_R8G8B8A8_UNORM);
    auto* constants = static_cast<float*>(cb.data) + CbBase;
    auto* uniforms = static_cast<float*>(ub.data) + UbBase;
    for (unsigned i = 0; i < 4; ++i) constants[i * 5] = 1;
    for (unsigned c = 0; c < 4; ++c) {
        auto* m = constants + 16 + 16 * c;
        m[0] = m[5] = 0.1f;
        m[3] = 0.25f + float(c & 1) * 0.5f;
        m[7] = 0.25f + float(c >> 1) * 0.5f;
        m[10] = 0.5f; m[11] = 0.25f; m[15] = 1;
    }
    constants[80] = 0.5f; constants[81] = 0.7f; constants[82] = 0.9f;
    uniforms[72] = 100; uniforms[73] = 1;
    std::fill_n(static_cast<unsigned*>(pixels.data), W * H, 0x601e140au);
    bool initialized = false;
    bool patterned_depth = false;
    std::vector<float> custom_depth; // when set, the depth buffer (W * H) instead of view_z

    double gpu_ms = 0;
    const auto dispatch = [&](Push push, float view_z, bool tilted = false) {
        for (unsigned y = 0; y < H; ++y)
            for (unsigned x = 0; x < W; ++x)
                static_cast<float*>(scene.data)[y * W + x] =
                    !custom_depth.empty() ? custom_depth[y * W + x] :
                    patterned_depth && (x + y) % 4 == 0 ? 1.0f :
                    view_z + (tilted ? 0.02f * (2 * (float(x) + 0.5f) / W - 1) : 0);
        Vulkan::BendSss::DispatchList bend;
        if (push.contact) {
            bend = Vulkan::BendSss::BuildDirectionalDispatchList(constants, W, H);
            assert(bend.dispatch_count > 0);
            push.light_coordinate = bend.light_coordinate;
        }
        CHECK(vkResetCommandBuffer(t.cmd, 0));
        VkCommandBufferBeginInfo begin{.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
        CHECK(vkBeginCommandBuffer(t.cmd, &begin));
        if (t.timing) vkCmdResetQueryPool(t.cmd, t.timing, 0, 2);
        for (auto i : {depth, map, output}) t.Barrier(i.image,
            initialized ? VK_IMAGE_LAYOUT_GENERAL : VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL);
        const std::array<Image, 3> ims{depth, map, output};
        const std::array<Buffer, 3> src{scene, atlas, pixels};
        for (unsigned i = 0; i < 3; ++i) {
            VkBufferImageCopy copy{.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                .imageExtent = i == 1 ? VkExtent3D{Atlas, Atlas, 1} : VkExtent3D{W, H, 1}};
            vkCmdCopyBufferToImage(t.cmd, src[i].buffer, ims[i].image, VK_IMAGE_LAYOUT_GENERAL, 1, &copy);
            t.Barrier(ims[i].image, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL);
        }
        const VkDescriptorBufferInfo cbi{cb.buffer, 0, 1024}, ubi{ub.buffer, 0, 1024};
        const VkDescriptorImageInfo d{t.sampler, depth.view, VK_IMAGE_LAYOUT_GENERAL},
            m{t.sampler, map.view, VK_IMAGE_LAYOUT_GENERAL}, o{{}, output.view, VK_IMAGE_LAYOUT_GENERAL};
        const std::array<VkWriteDescriptorSet, 5> writes{{
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 0, .descriptorCount = 1,
                .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &cbi},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 1, .descriptorCount = 1,
                .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &d},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 2, .descriptorCount = 1,
                .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &o},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 3, .descriptorCount = 1,
                .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &m},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 4, .descriptorCount = 1,
                .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &ubi}}};
        vkCmdBindPipeline(t.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, t.pipeline);
        t.descriptors(t.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, t.layout, 0, 5, writes.data());
        if (t.timing) vkCmdWriteTimestamp(t.cmd, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, t.timing, 0);
        const unsigned repeats = benchmark ? 16 : 1;
        for (unsigned repeat = 0; repeat < repeats; ++repeat) {
            if (repeat) t.Barrier(output.image, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL);
            if (!push.contact) {
                // Shadow-map filter only: one thread per pixel, in rows of 64.
                vkCmdPushConstants(t.cmd, t.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, PushBytes, &push);
                vkCmdDispatch(t.cmd, (W + 63) / 64, H, 1);
            }
            for (int i = 0; push.contact && i < bend.dispatch_count; ++i) {
                Push dispatch_push = push;
                dispatch_push.wave_offset = bend.dispatches[i].wave_offset;
                vkCmdPushConstants(t.cmd, t.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, PushBytes,
                                   &dispatch_push);
                const auto& count = bend.dispatches[i].wave_count;
                vkCmdDispatch(t.cmd, count[0], count[1], count[2]);
            }
        }
        if (t.timing) vkCmdWriteTimestamp(t.cmd, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, t.timing, 1);
        t.Barrier(output.image, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL);
        VkBufferImageCopy copy{.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .imageExtent = {W, H, 1}};
        vkCmdCopyImageToBuffer(t.cmd, output.image, VK_IMAGE_LAYOUT_GENERAL, result.buffer, 1, &copy);
        VkMemoryBarrier host{.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
        vkCmdPipelineBarrier(t.cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
            0, 1, &host, 0, nullptr, 0, nullptr);
        CHECK(vkEndCommandBuffer(t.cmd));
        VkSubmitInfo submit{.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &t.cmd};
        CHECK(vkQueueSubmit(t.queue, 1, &submit, {}));
        CHECK(vkQueueWaitIdle(t.queue));
        if (t.timing) {
            std::array<std::uint64_t, 2> stamps{};
            CHECK(vkGetQueryPoolResults(t.device, t.timing, 0, 2, sizeof stamps, stamps.data(),
                sizeof(std::uint64_t), VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT));
            const auto mask = t.timestamp_bits == 64 ? ~std::uint64_t{0} : (std::uint64_t{1} << t.timestamp_bits) - 1;
            gpu_ms = double((stamps[1] - stamps[0]) & mask) * t.timestamp_period / (1e6 * repeats);
        }
        initialized = true;
        const auto* out = static_cast<unsigned*>(result.data);
        float alpha = 0;
        for (unsigned i = 0; i < W * H; ++i) {
            assert((out[i] & 0x00ffffff) == 0x001e140a);
            alpha += float(out[i] >> 24) / 255;
        }
        return alpha / (W * H);
    };
    const auto run = [&](Push push, float view_z, bool tilted = false) {
        return dispatch(push, view_z, tilted);
    };
    auto* depths = static_cast<float*>(atlas.data);
    Push p;
    if (benchmark) {
        assert(t.timing);
        for (unsigned y = 0; y < Atlas; ++y)
            for (unsigned x = 0; x < Atlas; ++x)
                depths[y * Atlas + x] = x < 16 ? 0.2f : 1.0f;
        for (unsigned scenario = 0; scenario < 4; ++scenario) {
            const unsigned pcss = scenario & 1;
            p.pcss = pcss; p.contact = 1; p.blend = 0.1f;
            p.light = 0.5f;
            uniforms[72] = scenario < 2 ? 100 : 0;
            run(p, 0.475f, true);
            std::vector<double> samples;
            for (unsigned trial = 0; trial < 24; ++trial) {
                dispatch(p, 0.475f, true);
                if (trial >= 4) samples.push_back(gpu_ms);
            }
            std::sort(samples.begin(), samples.end());
            std::printf("1280x720 Bend + %s (%s), median GPU ms: %.4f\n",
                pcss ? "PCSS" : "PCF", scenario < 2 ? "visible" : "fully faded",
                samples[samples.size()/2]);
        }
        return 0;
    }
    std::fill_n(depths, Atlas * Atlas, 1.0f);
    assert(run(p, 0.4f) > 0.999f);
    std::fill_n(depths, Atlas * Atlas, 0.0f);
    assert(run(p, 0.4f) < 0.001f);
    p.filter = 0;
    assert(std::abs(run(p, 0.4f) - 96.0f / 255) < 0.001f);
    p.filter = 1;
    assert(std::abs(run(p, 1.0f) - 96.0f / 255) < 0.001f);
    for (unsigned c = 0; c < 4; ++c) {
        const float z = c == 0 ? 0.4f : c == 1 ? 0.6f : c == 2 ? 0.8f : 0.95f;
        auto* matrix = constants + 16 + 16 * c;
        const float saved_u = matrix[3];
        matrix[0] = 0;
        matrix[3] = 0.5f * float((c & 1) + 1) - 0.001f;
        for (unsigned y = 0; y < Atlas; ++y)
            for (unsigned x = 0; x < Atlas; ++x)
                depths[y * Atlas + x] = (x / 32 + 2 * (y / 32)) == c ? 0.0f : 1.0f;

        matrix[0] = 0.0005f;
        p.pcss = 0;
        assert(run(p, z) < 0.001f);
        p.pcss = 1; p.maximum = 10;
        assert(run(p, z) < 0.001f);
        matrix[0] = 0.1f; matrix[3] = saved_u;
    }
    p.pcss = 0; p.maximum = 0.3f; p.blend = 0.1f;
    for (unsigned y = 0; y < Atlas; ++y)
        for (unsigned x = 0; x < Atlas; ++x)
            depths[y * Atlas + x] = x < 32 && y < 32 ? 0.0f : 1.0f;
    assert(run(p, 0.45f) < 0.001f);
    assert(std::abs(run(p, 0.475f) - 0.5f) < 0.01f);
    assert(run(p, 0.5f) > 0.999f && run(p, 0.501f) > 0.999f);
    p.blend = 0;
    assert(run(p, 0.475f) < 0.001f);
    for (unsigned y = 0; y < Atlas; ++y)
        for (unsigned x = 0; x < Atlas; ++x)
            depths[y * Atlas + x] = 0.45f + 0.1f * ((float(x) + 0.5f) / Atlas - 0.25f);
    assert(run(p, 0.4f, true) > 0.999f);
    p.pcss = 1;
    assert(run(p, 0.4f, true) > 0.999f);
    for (unsigned y = 0; y < Atlas; ++y)
        for (unsigned x = 0; x < Atlas; ++x)
            depths[y * Atlas + x] -= 0.1f;
    assert(run(p, 0.4f, true) < 0.001f);
    p.pcss = 0;
    for (unsigned y = 0; y < Atlas; ++y)
        for (unsigned x = 0; x < Atlas; ++x)
            depths[y * Atlas + x] = x < 16 ? 0.0f : 1.0f;
    const float edge = run(p, 0.4f);
    assert(edge > 0.4f && edge < 0.6f);
    unsigned fractional = 0;
    for (unsigned i = 0; i < W * H; ++i) {
        const unsigned a = static_cast<unsigned*>(result.data)[i] >> 24;
        fractional += a > 0 && a < 255;
    }
    std::printf("Regular PCF fractional edge pixels: %u\n", fractional);
    assert(fractional >= 2 * H && fractional <= 5 * H);

    p.pcss = 1; p.bias = 0; p.light = 1; p.maximum = 2;
    const auto soft_pixels = [&] {
        unsigned count = 0;
        for (unsigned i = 0; i < W * H; ++i) {
            const unsigned a = static_cast<unsigned*>(result.data)[i] >> 24;
            count += a > 12 && a < 243;
        }
        return count;
    };
    const auto edge_at = [&](float blocker) {
        for (unsigned y = 0; y < Atlas; ++y)
            for (unsigned x = 0; x < Atlas; ++x)
                depths[y * Atlas + x] = x < 16 ? blocker : 1.0f;
        run(p, 0.4f);
        return soft_pixels();
    };
    const unsigned contact_width = edge_at(0.449f);
    const unsigned middle_width = edge_at(0.2f);
    const unsigned far_width = edge_at(0.0f);
    std::printf("PCSS edge widths (pixels): contact %u, middle %u, far %u\n",
                contact_width, middle_width, far_width);
    assert(contact_width >= H && middle_width > contact_width && far_width > middle_width);

    auto* first = constants + 16;
    first[0] = first[5] = 0.0001f;
    first[3] = first[7] = 16.5f / Atlas;
    std::fill_n(depths, Atlas * Atlas, 1.0f);
    depths[16 * Atlas + 16] = 0.449f;
    const float thin_visibility = run(p, 0.4f);
    std::printf("PCSS single-texel caster visibility: %.4f\n", thin_visibility);
    assert(thin_visibility < 0.5f);
    first[0] = first[5] = 0.1f;
    first[3] = first[7] = 0.25f;

    edge_at(0.2f);
    std::vector<unsigned> previous(static_cast<unsigned*>(result.data),
                                   static_cast<unsigned*>(result.data) + W * H);
    p.frame = 37;
    run(p, 0.4f);
    assert(std::equal(previous.begin(), previous.end(), static_cast<unsigned*>(result.data)));
    uniforms[72] = 0;
    assert(run(p, 0.4f) > 0.999f);
    p.contact = 1;
    first[0] = 0; first[1] = 0.1f;
    first[4] = 0.1f; first[5] = 0; first[6] = 0.1f;
    first[8] = 0.5f; first[10] = 0;
    const float flat_contact = run(p, 0.4f);
    assert(flat_contact > 1.0f - p.strength);
    patterned_depth = true;
    // Sky holes (depth 1) keep the native alpha and must not break the pass; they darken the
    // average only because their native alpha is 96/255 (they cast nothing).
    assert(run(p, 0.4f) < flat_contact - 0.01f);
    patterned_depth = false;

    // Bend contact occlusion with a real forward-Z perspective camera (the identity fixture
    // above projects every sun to W = 0, which no game projection does and which Bend's sign and
    // light-depth formulas don't cover). A plane facing the sun, plus a thin caster placed where
    // the receiver's Bend ray passes, with the sun in front of the camera (W > 0) and behind it
    // (W < 0), both from the left.
    {
        std::array<float, 32> saved;
        std::copy_n(constants, saved.size(), saved.begin());
        const float n = 0.1f, f = 100.0f, a = f / (f - n), b = -n * f / (f - n);
        // inverse(P) for P = {1,0,0,0 | 0,1,0,0 | 0,0,a,b | 0,0,1,0}: clip -> view.
        const float inv[16] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1 / b, -a / b};
        std::copy_n(inv, 16, constants);
        // The receiver: the plane -0.3 x - z = -5 (normal (-0.3, 0, -1), towards the camera and
        // the left), so z = 5 / (1 + 0.3 ndc_x).
        const auto plane_depth = [&](unsigned x) {
            const float ndc = (float(x) + 0.5f) / W * 2 - 1;
            return a + b / (5.0f / (1 + 0.3f * ndc));
        };
        const auto column = [&](unsigned x) {
            return float(static_cast<unsigned*>(result.data)[(H / 2) * W + x] >> 24) / 255;
        };
        // Native result fully lit and the shadow-map filter off: only Bend can darken pixels.
        std::fill_n(static_cast<unsigned*>(pixels.data), W * H, 0xff1e140au);
        p.filter = 0;
        const unsigned receiver = 12;
        for (const float sz : {0.1f, -0.1f}) {
            const float len = std::sqrt(1 + sz * sz);
            const float s[3] = {-1 / len, 0, sz / len}; // towards the sun, view space
            // Orthographic sun view -> light rows; stored as clip -> light (rows * inverse(P)).
            const float rows[4][4] = {{0, 1, 0, 0.25f},
                                      {s[2], 0, -s[0], 0.25f},
                                      {-0.01f * s[0], -0.01f * s[1], -0.01f * s[2], 0.5f},
                                      {0, 0, 0, 1}};
            const unsigned slot[4] = {0, 4, 8, 12}; // u, v, light depth, w
            for (unsigned r = 0; r < 4; ++r)
                for (unsigned c = 0; c < 4; ++c) {
                    float sum = 0;
                    for (unsigned i = 0; i < 4; ++i) sum += rows[r][i] * inv[i * 4 + c];
                    first[slot[r] + c] = sum;
                }
            const auto bend = Vulkan::BendSss::BuildDirectionalDispatchList(constants, W, H);
            const auto& light = bend.light_coordinate;
            // In front: the sun projects left of the screen, rays march towards it. Behind: its
            // antipode projects right of the screen, rays march away from it. Both go left.
            assert(bend.dispatch_count > 0);
            assert(sz > 0 ? light[3] == 1 && light[0] < 0 : light[3] == -1 && light[0] > W);
            const float direction = -light[3];
            const float distance = std::abs(float(receiver) + 0.5f - light[0]);
            const float d0 = plane_depth(receiver);

            custom_depth.assign(W * H, 0);
            for (unsigned y = 0; y < H; ++y)
                for (unsigned x = 0; x < W; ++x) custom_depth[y * W + x] = plane_depth(x);
            const float lit = run(p, 0.4f);
            // Bend's ray keeps (depth - light z) / pixel distance constant. Its shadowing window
            // is (1 - depth) / min(distance + direction, 1 / thickness) in front of the ray; put
            // the caster 80% into it, 1-3 pixels along the march (the hard samples).
            const float window =
                (1 - d0) / std::min(distance + direction, 1 / p.surface);
            for (unsigned k = 1; k <= 3; ++k) {
                const float ray = light[2] + (d0 - light[2]) * (distance + direction * k) / distance;
                for (unsigned y = 0; y < H; ++y)
                    custom_depth[y * W + receiver - k] = ray - 0.8f * window;
            }
            const float cast = run(p, 0.4f);
            std::printf("Bend caster, sun %s: light %.1f %.1f %.4f %.0f, flat %.4f, caster %.4f;"
                        " columns:", sz > 0 ? "in front" : "behind", light[0], light[1], light[2],
                        light[3], lit, cast);
            for (unsigned x = 0; x < W; ++x) std::printf(" %.2f", column(x));
            std::printf("\n");
            assert(lit > 0.99f);
            // Darkest possible is 1 - strength (0.25).
            assert(column(receiver) < 0.6f);
            for (unsigned x = 0; x + 6 <= receiver; ++x) assert(column(x) > 0.99f);
            // Distance fade: fade end 0 removes the shadow; far inside it, unchanged.
            p.bend_scale = 1.5f;
            uniforms[72] = 0;
            assert(run(p, 0.4f) > 0.999f);
            uniforms[72] = 100;
            assert(std::abs(run(p, 0.4f) - cast) < 0.001f);
            uniforms[72] = 0;
            p.bend_scale = 0;
        }
        custom_depth.clear();
        p.filter = 1;
        std::fill_n(static_cast<unsigned*>(pixels.data), W * H, 0x601e140au);
        std::copy_n(saved.begin(), saved.size(), constants);
    }

    first[3] = 2;
    assert(std::abs(run(p, 0.4f) - 96.0f / 255) < 0.001f);
    first[3] = 0.25f;

    constants[0] = 0.8f; constants[5] = -0.7f;
    constants[3] = 0.03f; constants[7] = -0.02f;
    constants[10] = 0.9f; constants[14] = 0.07f;
    uniforms[72] = 100;
    for (unsigned mode : {0u, 1u}) {
        p.pcss = mode;
        p.blend = 0.1f;
        for (float z : {0.4f, 0.54f, 0.75f, 0.96f})
            run(p, z, true);
        for (float z : {0.0f, 1.0f, std::numeric_limits<float>::quiet_NaN()})
            run(p, z);
        patterned_depth = true;
        for (float fade_end : {0.0f, 1.0f, 100.0f}) {
            uniforms[72] = fade_end;
            run(p, 0.54f, true);
        }
        patterned_depth = false;
    }
    std::puts("Directional shadows: PASS (four atlas tiles, PCF/PCSS edges, lit/shadow, "
              "cascade blending, sloped receivers, fractional comparisons, stock/sky fallback, fade, "
              "RGB preservation, odd sizes, buffer offsets, Bend contact occlusion, thin caster, "
              "frame stability)");
}
