// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_reflection_first_hit.h"
#include "video_core/renderer_vulkan/vk_reflection_first_retire.h"

#include <algorithm>
#include <atomic>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <optional>
#include <span>
#include <string_view>
#include <utility>
#include <vk_mem_alloc.h>

#include "common/scope_exit.h"
#include "engine/loading.h"
#include "video_core/buffer_cache/buffer.h"
#include "video_core/host_shaders/reflection_first_hit_comp.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan::ReflectionFirstHit {
namespace {
constexpr auto AsBuild = vk::PipelineStageFlagBits2::eAccelerationStructureBuildKHR;
constexpr auto All = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eAllTransfer;
constexpr auto Host = vk::PipelineStageFlagBits2::eHost;
constexpr auto AsRead = vk::AccessFlagBits2::eAccelerationStructureReadKHR;
constexpr auto AsWrite = vk::AccessFlagBits2::eAccelerationStructureWriteKHR;
constexpr auto Copy = vk::PipelineStageFlagBits2::eCopy;
constexpr auto MemoryRead = vk::AccessFlagBits2::eMemoryRead;
constexpr auto MemoryWrite = vk::AccessFlagBits2::eMemoryWrite;
constexpr auto TransferRead = vk::AccessFlagBits2::eTransferRead;
constexpr auto TransferWrite = vk::AccessFlagBits2::eTransferWrite;
constexpr auto ImageRead = vk::AccessFlagBits2::eShaderSampledRead;
constexpr auto StorageRead = vk::AccessFlagBits2::eShaderStorageRead;
constexpr auto StorageWrite = vk::AccessFlagBits2::eShaderStorageWrite;
constexpr auto HostRead = vk::AccessFlagBits2::eHostRead;
constexpr vk::DeviceSize MiB = 1024 * 1024;
constexpr vk::DeviceSize Budget = 64 * MiB;
constexpr vk::DeviceSize ClonePayloadLimit = 8 * MiB;
constexpr u32 CloneLimit = 2;
constexpr u32 AllocationLimit = SceneLimit + 32;
constexpr u64 RetainFrames = 600;
constexpr u8 ReceiverMask = 1;
constexpr u8 WorldMask = 2;
constexpr u8 WallMask = 4;
constexpr u32 ArmCount = u32(Arm::Count);
constexpr vk::DeviceSize PaletteBankBytes = PlacedSourceCount * PaletteBytes;
constexpr vk::DeviceSize PlacementBufferBytes = 2 * PaletteBankBytes;
constexpr u32 PlacedBit(PlacedSource source) {
    return 1u << u32(source);
}
constexpr std::array<float, 12> IdentityTransform{
    1.f, 0.f, 0.f, 0.f,
    0.f, 1.f, 0.f, 0.f,
    0.f, 0.f, 1.f, 0.f,
};
constexpr std::array<u8, 32> MirrorTopology{
    0xc4, 0xba, 0x3f, 0x63, 0xd6, 0x52, 0x3b, 0x00, 0x00, 0x6d, 0xa5,
    0x6b, 0x37, 0xd1, 0xe4, 0xa9, 0x3b, 0xcc, 0xa6, 0xe6, 0xd6, 0xd7,
    0x3e, 0x3c, 0xc5, 0xd3, 0x3d, 0x6c, 0xb0, 0x06, 0x87, 0x73,
};

struct Push {
    std::array<float, 12> view;
    std::array<float, 4> projection;
    std::array<float, 4> plane_normal;
    std::array<float, 2> jitter;
    std::array<u32, 2> extent;
    u32 count;
    u32 placed_mask;
};
using Tags = std::array<u32, 8>;

struct BufferInput {
    std::array<Pixel, PixelLimit> pixels;
    Tags tags;
};

struct BufferLayout {
    BufferInput input;
    Tags echoed;
    std::array<Sample, PixelLimit> samples;
};
static_assert(sizeof(Push) == 104 && offsetof(Push, count) == 96 &&
              offsetof(Push, placed_mask) == 100);
static_assert(PlacedSourceCount == 3 && PaletteWords == 24 && PaletteBytes == 96);
static_assert(sizeof(Pixel) == 16 && sizeof(Hit) == 48 && offsetof(Hit, distance) == 16);
static_assert(sizeof(Sample) == 320 && offsetof(Sample, receiver) == 80 &&
              offsetof(Sample, world) == 128 && offsetof(Sample, farther) == 224);
static_assert(sizeof(BufferInput) == 160 && offsetof(BufferInput, tags) == 128);
static_assert(offsetof(BufferLayout, echoed) == 160 && offsetof(BufferLayout, samples) == 192 &&
              sizeof(BufferLayout) == 2752);
static_assert(sizeof(vk::AccelerationStructureInstanceKHR) == 64);

struct Buffer {
    vk::Buffer handle{};
    VmaAllocation allocation{};
    vk::DeviceAddress address{};
    vk::DeviceSize bytes{};
    void* mapped{};
};

struct Structure {
    Buffer buffer{};
    vk::AccelerationStructureKHR handle{};
    vk::DeviceAddress address{};
};

struct AllocationUsage {
    std::atomic<vk::DeviceSize> bytes{};
    std::atomic<u32> allocations{};
};

struct CloneRecord {
    Member member{};
    u64 last_pass{};
    Structure blas{};
};

struct Placement {
    Stamp stamp{};
    Identity observed{};
    Identity build{};
    u64 cookie{};
    u64 build_cookie{};
};

enum class HeldPassMode { Off, Observe, Direct, Invalid };

HeldPassMode HeldMode() {
    static const auto mode = [] {
        const char* value = std::getenv("BB_REFLECTION_HELD_PASS_T205");
        if (!value || !*value || std::string_view{value} == "0") return HeldPassMode::Off;
        if (std::string_view{value} == "observe") return HeldPassMode::Observe;
        if (std::string_view{value} == "direct") return HeldPassMode::Direct;
        return HeldPassMode::Invalid;
    }();
    return mode;
}

// Shared between the existing placed-member admission and the held-pass receipt.
bool PlacedMemberMatches(const Placement& placement, const Member& member, const Stamp& submitted) {
    return placement.build == member.identity && placement.stamp.generation == submitted.generation &&
           placement.stamp.frame == member.last_submit_frame &&
           (member.current ? placement.stamp == submitted : member.identity.placed == PlacedSource::Fireplace);
}

struct HeldPassEvidence {
    bool stamp_matches{};
    bool image_checks_reached{};
    bool images_qualified{};
    bool cpu_ready{};
    bool placed_enabled{};
    u32 depth_format{}, cb0_format{};
    u32 retained_mask{}, current_mask{}, required_mask{};
};

struct Scene {
    Structure tlas{};
    u64 build_tick{};
    u64 serial{};
    std::vector<Identity> identities;
    bool searchable{};
};

struct Readback {
    Buffer buffer{};
    u64 tick{};
    u64 epoch{};
    std::optional<Report> pending;
};

bool ValidSource(const Identity& id) {
    if (id.surface == 0 || id.allocation == 0 || id.revision == 0 || id.placement == 0 || id.count < 3 ||
        id.count % 3 != 0) {
        return false;
    }
    const bool mirror_key = id.vs == 0x9da6aacb && id.ps == 0xca7226ec &&
                            id.count == ReceiverTriangles * 3 && id.first == 2440816;
    if (id.placed != PlacedSource::None) {
        switch (id.placed) {
        case PlacedSource::Mirror:
            if (!id.receiver) {
                return false;
            }
            break;
        case PlacedSource::Fireplace:
            if (id.receiver || id.wall_witness || id.vs != 0x9da6aacb || id.ps != 0xbb10e440 ||
                id.count != 18282 || id.first != 158744) {
                return false;
            }
            break;
        case PlacedSource::Wall:
            if (id.receiver || !id.wall_witness || id.vs != 0xc829ee58 || id.ps != 0xdbb222eb ||
                id.count != 42441 || id.first != 12368) {
                return false;
            }
            break;
        default:
            return false;
        }
    }
    return id.receiver ? mirror_key && id.topology_sha256 == MirrorTopology : !mirror_key;
}

bool Finite(float v) {
    return std::isfinite(v);
}

Tags ReportTags(const Report& report) {
    const auto request = report.request.serial;
    const auto generation = report.stamp.generation;
    const auto retained = report.scenes[u32(Arm::Retained)].serial;
    const auto current = report.scenes[u32(Arm::Current)].serial;
    return {u32(request), u32(request >> 32), u32(generation), u32(generation >> 32),
            u32(retained), u32(retained >> 32), u32(current), u32(current >> 32)};
}

bool ValidStamp(const Stamp& stamp) {
    return stamp.valid_native && stamp.pass && stamp.depth && stamp.cb0 && stamp.depth_uid &&
           stamp.cb0_uid && stamp.depth != stamp.cb0 && stamp.depth_image && stamp.cb0_image &&
           stamp.depth_image != stamp.cb0_image && stamp.extent[0] && stamp.extent[1] &&
           std::ranges::all_of(stamp.view, Finite) &&
           std::ranges::all_of(stamp.projection, Finite) &&
           std::abs(stamp.projection[0]) > 1e-6f && std::abs(stamp.projection[1]) > 1e-6f &&
           stamp.projection[3] != 0.f && std::abs(stamp.jitter[0]) <= 1.f &&
           std::abs(stamp.jitter[1]) <= 1.f;
}

bool NativeImage(const VideoCore::Image& image, const Stamp& stamp) {
    if (!image.backing || image.scene_proxy || image.info.num_samples != 1) {
        return false;
    }
    const auto& ci = image.backing->image.image_ci;
    return ci.imageType == vk::ImageType::e2D && ci.samples == vk::SampleCountFlagBits::e1 &&
           ci.extent == vk::Extent3D{stamp.extent[0], stamp.extent[1], 1} &&
           ci.mipLevels == 1 && ci.arrayLayers == 1 &&
           bool(ci.usage & vk::ImageUsageFlagBits::eSampled) && image.GetImage();
}

bool ValidHit(const Hit& hit, const SceneReceipt& scene, bool receiver) {
    if (hit.instance == InvalidId) {
        return hit.primitive == InvalidId && hit.geometry == InvalidId;
    }
    if (hit.instance >= scene.members.size()) {
        return false;
    }
    const auto& identity = scene.members[hit.instance].identity;
    return identity.receiver == receiver && hit.geometry == 0 && hit.primitive < identity.count / 3 &&
           std::ranges::all_of(hit.distance, Finite) && std::ranges::all_of(hit.world, Finite) &&
           hit.distance[0] >= 0.f;
}

bool ValidReport(const Report& report) {
    for (u32 i = 0; i < report.request.count; ++i) {
        const auto& pixel = report.request.pixels[i];
        const auto& sample = report.samples[i];
        if (sample.x != pixel.x || sample.y != pixel.y || sample.mode != pixel.mode ||
            sample.outcome < Outcome::Sampled || sample.outcome > Outcome::InvalidPlacement ||
            !ValidHit(sample.receiver, report.scenes[u32(Arm::Retained)], true)) {
            return false;
        }
        if (sample.outcome == Outcome::Sampled &&
            (sample.receiver.instance == InvalidId) != (pixel.mode == Mode::Direct)) {
            return false;
        }
        const bool refused = sample.outcome == Outcome::InvalidPlacement;
        if (refused && (!report.placed_mask || sample.receiver.instance != InvalidId)) {
            return false;
        }
        for (u32 arm = 0; arm < ArmCount; ++arm) {
            if ((refused && (sample.world[arm].instance != InvalidId || sample.farther[arm].instance != InvalidId)) ||
                !ValidHit(sample.world[arm], report.scenes[arm], false) ||
                !ValidHit(sample.farther[arm], report.scenes[arm], false)) {
                return false;
            }
            const u32 control = sample.farther[arm].instance;
            if (pixel.farther == 2 && control != InvalidId &&
                !report.scenes[arm].members[control].identity.wall_witness) {
                return false;
            }
        }
    }
    return true;
}

vk::AccelerationStructureGeometryKHR Instances(vk::DeviceAddress address) {
    return {
        .geometryType = vk::GeometryTypeKHR::eInstances,
        .geometry = {.instances = vk::AccelerationStructureGeometryInstancesDataKHR{
                         .data = {.deviceAddress = address}}},
    };
}

vk::AccelerationStructureBuildGeometryInfoKHR TlasBuild(
    const vk::AccelerationStructureGeometryKHR& geometry) {
    return {
        .type = vk::AccelerationStructureTypeKHR::eTopLevel,
        .flags = vk::BuildAccelerationStructureFlagBitsKHR::ePreferFastTrace,
        .mode = vk::BuildAccelerationStructureModeKHR::eBuild,
        .geometryCount = 1,
        .pGeometries = &geometry,
    };
}

void Free(VmaAllocator allocator, const std::shared_ptr<AllocationUsage>& usage, Buffer buffer) {
    vmaDestroyBuffer(allocator, buffer.handle, buffer.allocation);
    usage->bytes.fetch_sub(buffer.bytes);
    usage->allocations.fetch_sub(1);
}
} // namespace

bool On() {
    static const bool on = [] {
        const char* value = std::getenv("BB_REFLECTION_FIRST_HIT");
        return value && (std::strcmp(value, "1") == 0 || std::strcmp(value, "on") == 0);
    }();
    return on;
}

bool PlacedOn() {
    static const bool on = [] {
        const char* flag = std::getenv("BB_REFLECTION_PLACED_FIRST_HIT");
        return flag && std::strcmp(flag, "1") == 0;
    }();
    return on;
}

bool PlacedLifecycleOn() {
    static const bool on = [] {
        const char* flag = std::getenv("BB_REFLECTION_PLACED_LIFECYCLE");
        return flag && std::strcmp(flag, "1") == 0;
    }();
    return on && PlacedOn();
}

void TracePlacedLifecycle(PlacedSource role, std::string_view reason, u64 frame, u64 pass,
                          u64 allocation, u64 revision, u64 cookie, u64 a, u64 b) {
    ReflectionFirstRetire::Upstream(role, reason, frame, pass, allocation, revision, cookie, a, b);
    if (u32(role) >= PlacedSourceCount || !PlacedLifecycleOn()) {
        return;
    }
    // Both callers are on the render producer. Capture the first occurrence of a reason
    // with and without a resident revision. Never emit more than 64 rows per exact source.
    struct Key {
        std::string_view reason{};
        bool resident{};
        bool operator==(const Key&) const = default;
    };
    static std::array<std::array<Key, 64>, PlacedSourceCount> seen{};
    auto& keys = seen[u32(role)];
    const Key key{reason, revision != 0};
    const auto empty = std::ranges::find(keys, std::string_view{}, &Key::reason);
    if (empty == keys.end() || std::find(keys.begin(), empty, key) != empty) {
        return;
    }
    *empty = key;
    constexpr std::array names{"mirror", "fireplace", "wall"};
    const auto u = [](u64 value) { return static_cast<unsigned long long>(value); };
    std::printf("Reflection lifecycle target=%s event=%.*s frame=%llu pass=%llu allocation=%llu "
                "revision=%llu cookie=%llu value_a=%llu value_b=%llu\n",
                names[u32(role)], int(reason.size()), reason.data(), u(frame), u(pass),
                u(allocation), u(revision), u(cookie), u(a), u(b));
}

const char* StatusName(Status status) {
    switch (status) {
    case Status::Recorded: return "recorded";
    case Status::AlreadyCloned: return "already-cloned";
    case Status::Disabled: return "disabled";
    case Status::InvalidPass: return "invalid-pass";
    case Status::InvalidSource: return "invalid-source";
    case Status::InvalidRequest: return "invalid-request";
    case Status::AlreadyRequested: return "already-requested";
    case Status::MissingReceiver: return "missing-exact-current-receiver";
    case Status::MissingScene: return "missing-qualified-scene";
    case Status::MissingPlacedFixture: return "missing-exact-placed-fixture";
    case Status::InvalidImages: return "native-depth-or-cb0-unavailable";
    case Status::CloneLimit: return "clone-frame-budget";
    case Status::NoRoom: return "allocation-budget";
    case Status::BusyScene: return "previous-scene-build-pending";
    case Status::BusyReadback: return "readback-slots-busy";
    case Status::GpuUnavailable: return "pipeline-unavailable";
    case Status::StaleReadback: return "stale-load-epoch";
    case Status::InvalidReadback: return "invalid-readback-record";
    case Status::Pending: return "pending";
    case Status::HeldPassObserved: return "held-pass-observed-no-ray";
    case Status::HeldPassConsumed: return "held-pass-receipt-consumed";
    }
    return "unknown";
}

class Pass::State {
public:
    State(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& textures,
          Runtime& runtime);
    ~State();

    bool BeginPass(const Stamp& next);
    void CloseEpoch();
    bool Matches(const Stamp& candidate) const;
    bool Current(const CloneRecord& record) const;
    void Submitted(const Stamp& submitted, const Identity& id);
    void RejectReceiver(const Stamp& submitted);
    void InvalidateSurface(u64 surface);
    void ObserveSurface(u64 surface, u64 placement);
    void InvalidateAllocation(u64 allocation);
    void InvalidatePlaced(PlacedSource);
    bool ObservePlaced(const Stamp&, const Identity&, u64, const VideoCore::Buffer&, u64);
    bool BuildPlaced(const Stamp&, const Identity&, u64);
    bool CurrentPlaced(const Stamp&, const Identity&, u64) const;
    Status Clone(const Stamp&, const Identity&, vk::AccelerationStructureKHR, vk::DeviceSize);
    Status Submit(const Stamp&, const Request&);
    Status Poll(Report&);
    Usage GetUsage() const;

private:
    bool Allocate(Buffer&, vk::DeviceSize bytes, VkBufferUsageFlags flags, bool readback = false);
    bool Allocate(Structure&, vk::DeviceSize bytes, vk::AccelerationStructureTypeKHR type);
    void Retire(Buffer);
    void Retire(Structure);
    void Drop(std::vector<CloneRecord>::iterator, std::string_view reason);
    void Expire();
    void EvictNoncurrent();
    bool MakePipeline();
    Status EnsureScene(Scene&, SceneReceipt&);
    vk::ImageView View(const VideoCore::Image&, vk::ImageAspectFlagBits);
    void RecordSamples(Readback&, const Request&, const std::array<vk::ImageView, 2>&);
    void CopyPalette(vk::Buffer source, u64 source_offset, u64 destination_offset);
    void TraceHeldPass(const Stamp&, const Request&, HeldPassMode, const HeldPassEvidence&,
                       Status status, const char* gate) const;

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& textures;
    Runtime& runtime;
    const vk::Device device;
    const VmaAllocator allocator;
    const std::shared_ptr<AllocationUsage> allocations = std::make_shared<AllocationUsage>();
    vk::UniqueDescriptorSetLayout descriptors{};
    vk::UniquePipelineLayout layout{};
    vk::UniquePipeline pipeline{};
    bool pipeline_failed{};
    vk::DeviceSize scratch_alignment{};
    std::vector<CloneRecord> clones;
    std::array<Scene, ArmCount> scenes{};
    std::array<Readback, 2> readbacks{};
    Buffer placement_buffer{};
    std::array<Placement, PlacedSourceCount> placements{};
    std::array<std::optional<u64>, PlacedSourceCount> placement_copy_frame{};
    std::optional<Stamp> stamp;
    std::optional<Identity> submitted_receiver;
    u32 receiver_count{};
    bool receiver_rejected{};
    bool held_receipt_consumed{};
    u64 epoch{};
    u64 last_request{};
    u64 scene_serial{};
    u64 clone_frame{};
    u32 clone_count{};
    vk::DeviceSize clone_payload{};
    u64 expired{};
    u64 pressure_evicted{};
};

Pass::State::State(const Instance& instance_, Scheduler& scheduler_,
                   VideoCore::TextureCache& textures_, Runtime& runtime_)
    : instance{instance_}, scheduler{scheduler_}, textures{textures_}, runtime{runtime_},
      device{instance.GetDevice()}, allocator{instance.GetAllocator()} {
    clones.reserve(SceneLimit);
}

Pass::State::~State() {
    ReflectionFirstRetire::Stop(&scheduler, this);
    CloseEpoch();
    for (const auto& slot : readbacks) {
        Retire(slot.buffer);
    }
    Retire(placement_buffer);
    if (pipeline) {
        scheduler.DeferOperation(
            [descriptors = std::move(descriptors), layout = std::move(layout),
             pipeline = std::move(pipeline)]() mutable {
                pipeline.reset();
                layout.reset();
                descriptors.reset();
            },
            "reflection pipeline");
    }
}

bool Pass::State::Allocate(Buffer& out, vk::DeviceSize bytes, VkBufferUsageFlags flags,
                           bool readback) {
    const auto used = allocations->bytes.load();
    if (bytes == 0 || bytes > Budget - used || allocations->allocations.load() >= AllocationLimit ||
        !EffectPass::HasRoom(instance, bytes)) {
        return false;
    }
    const VkBufferCreateInfo ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = bytes,
        .usage = flags,
    };
    VmaAllocationCreateInfo ai{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (readback) {
        ai.usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST;
        ai.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    }
    VmaAllocationInfo info{};
    VkBuffer raw{};
    if (vmaCreateBuffer(allocator, &ci, &ai, &raw, &out.allocation, &info) != VK_SUCCESS) {
        return false;
    }
    out.handle = raw;
    out.bytes = info.size;
    out.mapped = info.pMappedData;
    if (flags & VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT) {
        out.address = device.getBufferAddress({.buffer = out.handle});
    }
    if (out.bytes > Budget - used || (readback && !out.mapped) ||
        ((flags & VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT) && !out.address)) {
        vmaDestroyBuffer(allocator, out.handle, out.allocation);
        out = {};
        return false;
    }
    allocations->bytes.fetch_add(out.bytes);
    allocations->allocations.fetch_add(1);
    return true;
}

bool Pass::State::Allocate(Structure& out, vk::DeviceSize bytes,
                           vk::AccelerationStructureTypeKHR type) {
    constexpr auto Usage = VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_STORAGE_BIT_KHR |
                           VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT;
    if (!Allocate(out.buffer, bytes, Usage)) {
        return false;
    }
    const auto [result, handle] = device.createAccelerationStructureKHR({
        .buffer = out.buffer.handle,
        .size = bytes,
        .type = type,
    });
    if (result == vk::Result::eSuccess) {
        out.handle = handle;
        out.address = device.getAccelerationStructureAddressKHR({.accelerationStructure = handle});
        if (out.address) {
            return true;
        }
        device.destroyAccelerationStructureKHR(handle);
    }
    Free(allocator, allocations, out.buffer);
    out = {};
    return false;
}

void Pass::State::Retire(Buffer buffer) {
    if (buffer.handle) {
        // The callback's destructor also runs for pending operations during the existing
        // drained Presenter teardown, when there will be no further scheduler submission.
        auto release = detail::MakeScopeGuard(
            [pool = allocations, allocator = allocator, buffer] { Free(allocator, pool, buffer); });
        scheduler.DeferOperation([release = std::move(release)] {}, "reflection buffer");
    }
}

void Pass::State::Retire(Structure structure) {
    if (structure.handle) {
        auto release = detail::MakeScopeGuard(
            [device = device, pool = allocations, allocator = allocator, structure] {
                device.destroyAccelerationStructureKHR(structure.handle);
                Free(allocator, pool, structure.buffer);
            });
        scheduler.DeferOperation([release = std::move(release)] {},
                                 "reflection acceleration structure");
    }
}

bool Pass::State::BeginPass(const Stamp& next) {
    if (BbEngine::Loading::ScreenUp() || next.generation != BbEngine::Loading::Generation()) {
        CloseEpoch();
        return false;
    }
    if (stamp && stamp->generation != next.generation) {
        CloseEpoch();
    }
    if (stamp && next.frame < stamp->frame) {
        return false;
    }
    if (!ValidStamp(next)) {
        CloseEpoch();
        return false;
    }
    if (stamp && next.frame == stamp->frame && next.pass == stamp->pass) {
        if (next != *stamp) {
            CloseEpoch();
            return false;
        }
        return true;
    }
    if (!stamp || next.frame != clone_frame) {
        clone_frame = next.frame;
        clone_payload = 0;
        clone_count = 0;
    }
    stamp = next;
    submitted_receiver.reset();
    receiver_count = 0;
    receiver_rejected = false;
    Expire();
    return true;
}

void Pass::State::CloseEpoch() {
    const u64 last_frame = stamp ? stamp->frame : 0;
    const u64 last_pass = stamp ? stamp->pass : 0;
    ++epoch;
    stamp.reset();
    submitted_receiver.reset();
    receiver_count = 0;
    receiver_rejected = false;
    for (auto& scene : scenes) {
        Retire(scene.tlas);
        scene = {.build_tick = scene.build_tick};
    }
    for (const auto& clone : clones) {
        const auto& id = clone.member.identity;

        if (u32(id.placed) < PlacedSourceCount && ReflectionFirstRetire::Owned(&scheduler, this)) {
            const auto& bank = placements[u32(id.placed)];
            ReflectionFirstRetire::Invalidate(&scheduler, this, id, epoch - 1,
                {"clone-drop-epoch", last_frame, last_pass}, bank.stamp, bank.cookie, bank.build_cookie,
                clone.member.last_submit_frame, clone.last_pass);
        }
        TracePlacedLifecycle(id.placed, "clone-drop-epoch", last_frame, last_pass, id.allocation, id.revision, 0,
                             clone.member.last_submit_frame, clone.last_pass);
        Retire(clone.blas);
    }
    for (const auto& placement : placements) {
        const auto& id = placement.build;

        if (ReflectionFirstRetire::Owned(&scheduler, this)) {
            ReflectionFirstRetire::Invalidate(&scheduler, this, id, epoch - 1,
                {"bank-clear-epoch", last_frame, last_pass}, placement.stamp,
                placement.cookie, placement.build_cookie);
        }
        TracePlacedLifecycle(id.placed, "bank-clear-epoch", last_frame, last_pass, id.allocation, id.revision,
                             placement.build_cookie, epoch, placement.stamp.frame);
    }
    clones.clear();
    placements = {};
    placement_copy_frame = {};
    ReflectionFirstRetire::FinishOperation(&scheduler, this);
}

bool Pass::State::Matches(const Stamp& candidate) const {
    return stamp && candidate == *stamp && candidate.generation == BbEngine::Loading::Generation() &&
           !BbEngine::Loading::ScreenUp();
}

bool Pass::State::Current(const CloneRecord& record) const {
    return stamp && record.member.last_submit_frame == stamp->frame && record.last_pass == stamp->pass;
}

void Pass::State::Submitted(const Stamp& submitted, const Identity& id) {
    if (!Matches(submitted)) {
        return;
    }
    if (!ValidSource(id)) {
        receiver_rejected |= id.receiver;
        return;
    }
    if (id.receiver) {
        receiver_count = std::min(receiver_count + 1, 2u);
        submitted_receiver = id;
    }
    const auto old = std::ranges::find_if(clones, [&](const CloneRecord& record) {
        return record.member.identity.surface == id.surface;
    });
    if (old != clones.end()) {
        if (old->member.identity == id) {
            old->member.last_submit_frame = submitted.frame;
            old->last_pass = submitted.pass;
        } else {
            Drop(old, "clone-drop-submitted-identity");
        }
    }
}

void Pass::State::RejectReceiver(const Stamp& submitted) {
    receiver_rejected |= Matches(submitted);
}

void Pass::State::Drop(std::vector<CloneRecord>::iterator old, std::string_view reason) {
    const auto& id = old->member.identity;

    if (u32(id.placed) < PlacedSourceCount && ReflectionFirstRetire::Owned(&scheduler, this)) {
        const auto& bank = placements[u32(id.placed)];
        const bool same = bank.build == id || bank.observed == id;
        const Stamp empty{};
        ReflectionFirstRetire::Invalidate(&scheduler, this, id, epoch,
            {reason, stamp ? stamp->frame : 0, stamp ? stamp->pass : 0},
            same ? bank.stamp : empty, same ? bank.cookie : 0, same ? bank.build_cookie : 0,
            old->member.last_submit_frame, old->last_pass);
    }
    TracePlacedLifecycle(id.placed, reason, stamp ? stamp->frame : 0, stamp ? stamp->pass : 0,
                         id.allocation, id.revision, 0, old->member.last_submit_frame, old->last_pass);
    for (auto& scene : scenes) {
        if (std::ranges::find(scene.identities, old->member.identity) != scene.identities.end()) {
            scene.searchable = false;
        }
    }
    Retire(old->blas);
    clones.erase(old);
    ReflectionFirstRetire::FinishOperation(&scheduler, this);
}

void Pass::State::InvalidateSurface(u64 surface) {
    const auto old = std::ranges::find_if(clones, [&](const CloneRecord& record) {
        return record.member.identity.surface == surface;
    });
    if (old != clones.end()) {
        Drop(old, "clone-drop-surface");
    }
}

void Pass::State::ObserveSurface(u64 surface, u64 placement) {
    const auto old = std::ranges::find_if(clones, [&](const CloneRecord& record) {
        const auto& id = record.member.identity;
        return id.surface == surface && id.placement != placement;
    });
    if (old != clones.end()) {
        Drop(old, "clone-drop-placement-change");
    }
}

void Pass::State::InvalidateAllocation(u64 allocation) {
    for (auto& placement : placements) {
        if (placement.build.allocation == allocation) {
            const auto& id = placement.build;

            if (ReflectionFirstRetire::Owned(&scheduler, this)) {
                ReflectionFirstRetire::Invalidate(&scheduler, this, id, epoch,
                    {"bank-clear-allocation", stamp ? stamp->frame : 0, stamp ? stamp->pass : 0},
                    placement.stamp, placement.cookie, placement.build_cookie);
            }
            TracePlacedLifecycle(id.placed, "bank-clear-allocation", stamp ? stamp->frame : 0,
                                 stamp ? stamp->pass : 0, allocation, id.revision,
                                 placement.build_cookie, placement.stamp.frame, placement.cookie);
            placement.build = {};
            placement.build_cookie = 0;
        }
    }
    for (std::size_t i = clones.size(); i > 0; --i) {
        if (clones[i - 1].member.identity.allocation == allocation) {
            Drop(clones.begin() + (i - 1), "clone-drop-allocation");
        }
    }
    ReflectionFirstRetire::FinishOperation(&scheduler, this);
}

void Pass::State::InvalidatePlaced(PlacedSource source) {
    auto& placement = placements[u32(source)];
    TracePlacedLifecycle(source, "bank-clear-source", stamp ? stamp->frame : 0,
                         stamp ? stamp->pass : 0, placement.observed.allocation,
                         placement.build.revision, placement.cookie,
                         placement.stamp.frame, placement.stamp.pass);
    if (placement.build.allocation) {
        InvalidateAllocation(placement.build.allocation);
    }
    placement = {};
}

void Pass::State::CopyPalette(vk::Buffer source, u64 source_offset, u64 destination_offset) {
    scheduler.EndRendering();
    runtime.FlushBarriers();
    scheduler.RecordCrumb({.name = "Reflection placed palette copy"},
        [source, target = placement_buffer.handle, source_offset, destination_offset](vk::CommandBuffer cb) {
            const std::array barriers{
                vk::BufferMemoryBarrier2{
                    .srcStageMask = All, .srcAccessMask = MemoryWrite,
                    .dstStageMask = Copy, .dstAccessMask = TransferRead,
                    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .buffer = source, .offset = source_offset, .size = PaletteBytes},
                vk::BufferMemoryBarrier2{
                    .srcStageMask = All, .srcAccessMask = MemoryRead | MemoryWrite,
                    .dstStageMask = Copy, .dstAccessMask = TransferWrite,
                    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .buffer = target, .offset = destination_offset, .size = PaletteBytes},
            };
            cb.pipelineBarrier2({.bufferMemoryBarrierCount = u32(barriers.size()),
                                 .pBufferMemoryBarriers = barriers.data()});
            cb.copyBuffer(source, target, {{source_offset, destination_offset, PaletteBytes}});
        });
}

bool Pass::State::ObservePlaced(const Stamp& submitted, const Identity& id, u64 cookie,
                                const VideoCore::Buffer& source, u64 offset) {
    if (!Matches(submitted) || u32(id.placed) >= PlacedSourceCount || !cookie || id.revision ||
        !source.Handle() || offset % alignof(u32) || offset > source.SizeBytes() ||
        PaletteBytes > source.SizeBytes() - offset) {
        TracePlacedLifecycle(id.placed, "palette-observe-source-refused", submitted.frame, submitted.pass,
                             id.allocation, 0, cookie, offset, source.SizeBytes());
        return false;
    }
    const u32 index = u32(id.placed);
    auto& placement = placements[index];
    if (placement_copy_frame[index] == submitted.frame) {
        // One capture per source per frame. A second distinct native pass cannot overwrite it.
        TracePlacedLifecycle(id.placed, "palette-observe-second-pass", submitted.frame, submitted.pass,
                             id.allocation, placement.build.revision, cookie,
                             placement.stamp.pass, placement.cookie);
        return false;
    }
    if (placement.observed != id) {
        TracePlacedLifecycle(id.placed, "palette-observed-identity", submitted.frame, submitted.pass,
                             id.allocation, placement.build.revision, cookie,
                             placement.observed.allocation, placement.observed.placement != id.placement);
        InvalidatePlaced(id.placed);
    }
    if (!placement_buffer.handle &&
        !Allocate(placement_buffer, PlacementBufferBytes, VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                      VK_BUFFER_USAGE_TRANSFER_DST_BIT | VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, false)) {
        TracePlacedLifecycle(id.placed, "palette-observe-no-room", submitted.frame, submitted.pass,
                             id.allocation, 0, cookie, 0, 0);
        return false;
    }
    CopyPalette(source.Handle(), offset, PaletteBankBytes + index * PaletteBytes);
    runtime.AccessBuffer(&source, offset, PaletteBytes, Copy, TransferRead);
    placement_copy_frame[index] = submitted.frame;
    placement.stamp = submitted;
    placement.observed = id;
    placement.cookie = cookie;
    return true;
}

bool Pass::State::BuildPlaced(const Stamp& submitted, const Identity& id, u64 confirmed_cookie) {
    if (!Matches(submitted) || u32(id.placed) >= PlacedSourceCount || !ValidSource(id)) {
        TracePlacedLifecycle(id.placed, "palette-build-invalid-source", submitted.frame, submitted.pass,
                             id.allocation, id.revision, confirmed_cookie, 0, 0);
        return false;
    }
    auto& placement = placements[u32(id.placed)];
    auto observed_id = id;
    observed_id.revision = 0;
    if (!placement_buffer.handle || !confirmed_cookie || placement.cookie != confirmed_cookie ||
        placement.stamp != submitted || placement.observed != observed_id) {
        const u32 failures = u32(!placement_buffer.handle) | (u32(!confirmed_cookie) << 1) |
                             (u32(placement.cookie != confirmed_cookie) << 2) |
                             (u32(placement.stamp != submitted) << 3) |
                             (u32(placement.observed != observed_id) << 4);
        TracePlacedLifecycle(id.placed, "palette-build-observation-refused", submitted.frame, submitted.pass,
                             id.allocation, id.revision, confirmed_cookie, failures, placement.cookie);
        return false;
    }
    const u64 offset = u32(id.placed) * PaletteBytes;
    CopyPalette(placement_buffer.handle, PaletteBankBytes + offset, offset);
    placement.build = id;
    placement.build_cookie = confirmed_cookie;
    return true;
}

bool Pass::State::CurrentPlaced(const Stamp& submitted, const Identity& id, u64 confirmed_cookie) const {
    if (u32(id.placed) >= PlacedSourceCount || !confirmed_cookie) {
        return false;
    }
    const auto& placement = placements[u32(id.placed)];
    const bool current = placement.build == id && placement.stamp == submitted &&
                         placement.cookie == confirmed_cookie;
    if (!current && PlacedLifecycleOn()) {
        const u32 failures = u32(placement.build != id) | (u32(placement.stamp != submitted) << 1) |
                             (u32(placement.cookie != confirmed_cookie) << 2);
        TracePlacedLifecycle(id.placed, "palette-current-refused", submitted.frame, submitted.pass,
                             id.allocation, id.revision, confirmed_cookie,
                             failures, placement.build.revision);
    }
    return current;
}

void Pass::State::Expire() {
    for (std::size_t i = clones.size(); i > 0; --i) {
        if (stamp->frame - clones[i - 1].member.last_submit_frame >= RetainFrames) {
            Drop(clones.begin() + (i - 1), "clone-drop-lease");
            ++expired;
        }
    }
}

void Pass::State::EvictNoncurrent() {
    auto oldest = clones.end();
    for (auto it = clones.begin(); it != clones.end(); ++it) {
        if (!Current(*it) && (oldest == clones.end() ||
            it->member.last_submit_frame < oldest->member.last_submit_frame)) {
            oldest = it;
        }
    }
    if (oldest != clones.end()) {
        Drop(oldest, "clone-drop-pressure");
        ++pressure_evicted;
    }
}

Status Pass::State::Clone(const Stamp& submitted, const Identity& id,
                          vk::AccelerationStructureKHR source, vk::DeviceSize bytes) {
    if (!Matches(submitted)) {
        return Status::InvalidPass;
    }
    if (!ValidSource(id) || !source || !bytes ||
        (id.receiver && (receiver_rejected || receiver_count != 1 || submitted_receiver != id)) ||
        (id.placed != PlacedSource::None && placements[u32(id.placed)].build != id)) {
        return Status::InvalidSource;
    }
    const auto old = std::ranges::find_if(clones, [&](const CloneRecord& record) {
        return record.member.identity.surface == id.surface;
    });
    if (old != clones.end()) {
        if (old->member.identity == id) {
            old->member.last_submit_frame = submitted.frame;
            old->last_pass = submitted.pass;
            return Status::AlreadyCloned;
        }
        Drop(old, "clone-drop-replacement");
    }
    if (clone_count >= CloneLimit || bytes > ClonePayloadLimit - clone_payload) {
        return Status::CloneLimit;
    }
    if (clones.size() == SceneLimit) {
        EvictNoncurrent();
    }
    Structure blas;
    if (clones.size() == SceneLimit) {
        return Status::NoRoom;
    }
    if (!Allocate(blas, bytes, vk::AccelerationStructureTypeKHR::eBottomLevel)) {
        EvictNoncurrent();
        return Status::NoRoom;
    }
    ++clone_count;
    clone_payload += bytes;
    clones.push_back({{id, submitted.frame, true}, submitted.pass, blas});
    scheduler.EndRendering();
    EffectPass::Mark(0x52454600, "reflection BLAS clone");
    scheduler.RecordCrumb(
        {.name = "Reflection BLAS clone"},
        [source, destination = blas.handle](vk::CommandBuffer cb) {
            // AllCommands covers AS copy with or without acceleration-structure maintenance1.
            EffectPass::MemoryBarrier(cb, AsBuild, AsWrite, All, AsRead);
            cb.copyAccelerationStructureKHR({.src = source, .dst = destination,
                                             .mode = vk::CopyAccelerationStructureModeKHR::eClone});
            EffectPass::MemoryBarrier(cb, All, AsRead | AsWrite, AsBuild | Compute,
                                      AsRead | AsWrite);
        });
    ReflectionFirstRetire::Clone(&scheduler, this, submitted, epoch, id);
    return Status::Recorded;
}

bool Pass::State::MakePipeline() {
    if (pipeline || pipeline_failed) {
        return bool(pipeline);
    }
    using enum vk::DescriptorType;
    pipeline_failed = !EffectPass::Create(
        instance, descriptors, layout, pipeline,
        {eAccelerationStructureKHR, eAccelerationStructureKHR, eSampledImage, eSampledImage,
         eStorageBuffer, eStorageBuffer},
        sizeof(Push), REFLECTION_FIRST_HIT_COMP, "Reflection first hit");
    return !pipeline_failed;
}

Status Pass::State::EnsureScene(Scene& scene, SceneReceipt& receipt) {
    const auto members = std::span{receipt.members};
    if (scene.searchable &&
        std::ranges::equal(scene.identities, members, std::equal_to<>{}, std::identity{},
                           &Member::identity)) {
        receipt.serial = scene.serial;
        return Status::Recorded;
    }
    scene.searchable = false;
    if (scene.build_tick && !scheduler.IsFree(scene.build_tick)) {
        return Status::BusyScene;
    }
    const u32 count = u32(members.size());
    const auto sizing_geometry = Instances(0);
    const auto sizing_info = TlasBuild(sizing_geometry);
    const auto sizes = device.getAccelerationStructureBuildSizesKHR(
        vk::AccelerationStructureBuildTypeKHR::eDevice, sizing_info, count);
    if (!scratch_alignment) {
        const auto props = instance.GetPhysicalDevice().getProperties2<
            vk::PhysicalDeviceProperties2, vk::PhysicalDeviceAccelerationStructurePropertiesKHR>();
        scratch_alignment = std::max<u64>(
            1, props.get<vk::PhysicalDeviceAccelerationStructurePropertiesKHR>()
                   .minAccelerationStructureScratchOffsetAlignment);
    }
    Structure tlas;
    Buffer instances, scratch;
    const auto instance_bytes = std::max(count, 1u) * sizeof(vk::AccelerationStructureInstanceKHR);
    constexpr auto Address = VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT;
    if (!Allocate(tlas, sizes.accelerationStructureSize, vk::AccelerationStructureTypeKHR::eTopLevel) ||
        !Allocate(instances, instance_bytes,
                  Address | VK_BUFFER_USAGE_TRANSFER_DST_BIT |
                      VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_BUILD_INPUT_READ_ONLY_BIT_KHR) ||
        !Allocate(scratch, sizes.buildScratchSize + scratch_alignment - 1,
                  Address | VK_BUFFER_USAGE_STORAGE_BUFFER_BIT) ||
        instances.address % 16 != 0) {
        if (tlas.handle) {
            device.destroyAccelerationStructureKHR(tlas.handle);
            Free(allocator, allocations, tlas.buffer);
        }
        for (const auto& unused : {instances, scratch}) {
            if (unused.handle) {
                Free(allocator, allocations, unused);
            }
        }
        Retire(scene.tlas);
        scene = {};
        EvictNoncurrent();
        return Status::NoRoom;
    }
    Retire(scene.tlas);
    scene = {.tlas = tlas, .build_tick = scheduler.CurrentTick(), .serial = ++scene_serial,
             .searchable = true};
    scene.identities.reserve(count);
    std::vector<vk::AccelerationStructureInstanceKHR> instance_data;
    instance_data.reserve(count);
    for (const auto& member : members) {
        // Receipt and instance order follow exactly the same indexed clone set.
        const auto found = std::ranges::find(clones, member.identity, [](const CloneRecord& record) {
            return record.member.identity;
        });
        ASSERT(found != clones.end());
        vk::AccelerationStructureInstanceKHR row{
            .instanceCustomIndex = u32(instance_data.size()),
            .mask = member.identity.receiver ? ReceiverMask :
                        u8(WorldMask | (member.identity.wall_witness ? WallMask : 0)),
            .accelerationStructureReference = found->blas.address,
        };
        std::memcpy(&row.transform, IdentityTransform.data(), sizeof(IdentityTransform));
        instance_data.push_back(row);
        scene.identities.push_back(member.identity);
    }
    receipt.serial = scene.serial;
    const auto scratch_address =
        (scratch.address + scratch_alignment - 1) & ~(scratch_alignment - 1);
    EffectPass::Mark(0x52454601, "reflection TLAS");
    scheduler.RecordCrumb(
        {.name = "Reflection world TLAS"},
        [instances, dst = tlas.handle, scratch_address, rows = std::move(instance_data)](
            vk::CommandBuffer cb) {
            if (!rows.empty()) {
                cb.updateBuffer(instances.handle, 0,
                                rows.size() * sizeof(vk::AccelerationStructureInstanceKHR),
                                rows.data());
                EffectPass::MemoryBarrier(cb, Transfer, TransferWrite, AsBuild,
                                          vk::AccessFlagBits2::eShaderRead);
            }
            const auto geometry = Instances(instances.address);
            auto info = TlasBuild(geometry);
            info.dstAccelerationStructure = dst;
            info.scratchData.deviceAddress = scratch_address;
            const vk::AccelerationStructureBuildRangeInfoKHR range{.primitiveCount = u32(rows.size())};
            const auto* range_pointer = &range;
            cb.buildAccelerationStructuresKHR(info, range_pointer);
            EffectPass::MemoryBarrier(cb, AsBuild, AsWrite, Compute, AsRead);
        });
    Retire(scratch);
    Retire(instances);
    return Status::Recorded;
}

vk::ImageView Pass::State::View(const VideoCore::Image& image, vk::ImageAspectFlagBits aspect) {
    const auto [status, view] = device.createImageView({
        .image = image.GetImage(),
        .viewType = vk::ImageViewType::e2D,
        .format = image.backing->image.image_ci.format,
        .subresourceRange = {aspect, 0, 1, 0, 1},
    });
    return status == vk::Result::eSuccess ? view : vk::ImageView{};
}

void Pass::State::TraceHeldPass(const Stamp& submitted, const Request& request, HeldPassMode mode,
                               const HeldPassEvidence& proof, Status status, const char* gate) const {
    const auto u = [](u64 value) { return static_cast<unsigned long long>(value); };
    const auto request_id = u(request.serial);
    const auto& view = submitted.view;
    const auto& proj = submitted.projection;
    const auto& jitter = submitted.jitter;
    std::printf("Reflection held pass (t205): request=%llu mode=%s status=%s first_gate=%s "
                "generation=%llu frame=%llu pass=%llu tick=%llu epoch=%llu loading_generation=%llu "
                "screen_up=%u native=%u stamp_match=%u size=%ux%u image_checks=%u images_qualified=%u "
                "depth=%llx/%llu/%u cb0=%llx/%llu/%u placed_on=%u retained_mask=%u current_mask=%u "
                "required_mask=%u receiver_count=%u receiver_rejected=%u cpu_ready=%u ray_recorded=%u\n",
                request_id, mode == HeldPassMode::Observe ? "observe" :
                            mode == HeldPassMode::Direct ? "direct" : "invalid",
                StatusName(status), gate, u(submitted.generation), u(submitted.frame), u(submitted.pass),
                u(scheduler.CurrentTick()), u(epoch), u(BbEngine::Loading::Generation()),
                u32(BbEngine::Loading::ScreenUp()), u32(submitted.valid_native), u32(proof.stamp_matches),
                submitted.extent[0], submitted.extent[1], u32(proof.image_checks_reached),
                u32(proof.images_qualified), u(std::bit_cast<u64>(submitted.depth_image)),
                u(submitted.depth_uid), proof.depth_format, u(std::bit_cast<u64>(submitted.cb0_image)),
                u(submitted.cb0_uid), proof.cb0_format, u32(proof.placed_enabled), proof.retained_mask,
                proof.current_mask, proof.required_mask, receiver_count, u32(receiver_rejected),
                u32(proof.cpu_ready), u32(status == Status::Recorded));
    const auto bits = [](float value) { return std::bit_cast<u32>(value); };
    std::printf("Reflection held camera (t205): request=%llu view_bits=%08x/%08x/%08x/%08x/%08x/%08x/"
                "%08x/%08x/%08x/%08x/%08x/%08x projection_bits=%08x/%08x/%08x/%08x jitter_bits=%08x/%08x\n",
                request_id, bits(view[0]), bits(view[1]), bits(view[2]), bits(view[3]), bits(view[4]),
                bits(view[5]), bits(view[6]), bits(view[7]), bits(view[8]), bits(view[9]), bits(view[10]),
                bits(view[11]), bits(proj[0]), bits(proj[1]), bits(proj[2]), bits(proj[3]),
                bits(jitter[0]), bits(jitter[1]));

    struct Role {
        const CloneRecord* record{};
        u32 count{}, current{}, eligible{}, eligible_current{};
    };
    std::array<Role, PlacedSourceCount> roles{};
    for (const auto& clone : clones) {
        auto member = clone.member;
        const u32 index = u32(member.identity.placed);
        if (index >= PlacedSourceCount) continue;
        auto& role = roles[index];
        member.current = Current(clone) && proof.stamp_matches;
        const bool eligible = PlacedMemberMatches(placements[index], member, submitted);
        ++role.count;
        role.current += member.current;
        role.eligible += eligible;
        role.eligible_current += eligible && member.current;
        if (!role.record || (member.current && !Current(*role.record))) role.record = &clone;
    }
    constexpr std::array names{"mirror", "fireplace", "wall"};
    for (u32 index = 0; index < roles.size(); ++index) {
        const auto& role = roles[index];
        const auto& placement = placements[index];
        const auto& draw = placement.observed;
        const auto& build = placement.build;
        auto draw_build = build;
        draw_build.revision = 0;
        const bool draw_current = placement.cookie && placement.stamp == submitted && proof.stamp_matches;
        const bool build_matches = ValidSource(build) && placement.build_cookie && draw == draw_build;
        const bool receiver_ok = index != u32(PlacedSource::Mirror) ||
                                 (!receiver_rejected && receiver_count == 1 && submitted_receiver == build);
        const char* reason = !draw_current ? "no-current-qualified-draw" :
                             !build_matches ? "no-matching-ordinary-build" :
                             !role.count ? "no-retained-clone" :
                             !role.current ? "clone-not-current" :
                             !role.eligible_current ? "clone-palette-mismatch" :
                             role.eligible > 1 ? "duplicate-placed-members" :
                             !receiver_ok ? "receiver-unqualified" : "current";
        const auto& member = role.record ? role.record->member : Member{};
        std::printf("Reflection held role (t205): request=%llu role=%s required=%u first_missing=%s "
                    "draw_current=%u draw=%llu/%llu/%llu/%llu/%llx/%llu draw_key=%08x/%08x/%u/%u "
                    "build=%llu/%llu/%llu/%llx clone=%llu/%llu/%llu/%llu counts=%u/%u/%u/%u\n",
                    request_id, names[index], u32((proof.required_mask & (1u << index)) != 0), reason,
                    u32(draw_current), u(placement.stamp.generation), u(placement.stamp.frame),
                    u(placement.stamp.pass), u(draw.allocation), u(draw.placement), u(placement.cookie),
                draw.vs, draw.ps, draw.count, draw.first,
                    u(build.allocation), u(build.revision), u(placement.build_cookie), u(build.placement),
                    u(member.identity.allocation), u(member.identity.revision), u(member.last_submit_frame),
                    u(role.record ? role.record->last_pass : 0), role.count, role.current, role.eligible,
                    role.eligible_current);
    }
}

Status Pass::State::Submit(const Stamp& submitted, const Request& request) {
    const auto held = HeldMode();
    if (held != HeldPassMode::Off && std::exchange(held_receipt_consumed, true)) {
        return Status::HeldPassConsumed;
    }
    HeldPassEvidence evidence;
    const auto finish = [&](Status status, const char* gate) {
        if (held != HeldPassMode::Off) TraceHeldPass(submitted, request, held, evidence, status, gate);
        return status;
    };
    if (!request.serial) {
        return finish(Status::InvalidRequest, "serial");
    }
    if (request.serial <= last_request) {
        return finish(Status::AlreadyRequested, "serial-repeat");
    }
    last_request = request.serial;
    evidence.stamp_matches = Matches(submitted);
    if (!evidence.stamp_matches) {
        return finish(Status::InvalidPass, "pass-stamp");
    }
    if (request.count == 0 || request.count > PixelLimit) {
        return finish(Status::InvalidRequest, "pixel-count");
    }
    if (held != HeldPassMode::Off) {
        if (held == HeldPassMode::Invalid || !HeldPassRequest(request) ||
            submitted.extent != std::array<u32, 2>{1920, 1080}) {
            return finish(Status::InvalidRequest, "held-request-shape");
        }
        evidence.placed_enabled = PlacedOn();
        evidence.required_mask = PlacedBit(PlacedSource::Wall) | PlacedBit(PlacedSource::Fireplace);
        if (!evidence.placed_enabled) {
            return finish(Status::MissingPlacedFixture, "placed-switch");
        }
    }
    bool needs_receiver = false;
    bool needs_direct = false;
    const auto& normal = request.receiver_plane_normal;
    for (const auto& pixel : std::span{request.pixels}.first(request.count)) {
        if (pixel.x >= submitted.extent[0] || pixel.y >= submitted.extent[1] ||
            pixel.mode > Mode::Direct || pixel.farther > 2) {
            return finish(Status::InvalidRequest, "pixel-input");
        }
        if (pixel.mode == Mode::Planar) {
            const float length = std::hypot(normal[0], normal[1], normal[2]);
            if (!(length >= .5f && length <= 1.5f)) {
                return finish(Status::InvalidRequest, "receiver-normal");
            }
        }
        needs_receiver |= pixel.mode != Mode::Direct;
        needs_direct |= pixel.mode == Mode::Direct;
    }
    if (needs_receiver && (receiver_rejected || receiver_count != 1 || !submitted_receiver)) {
        return finish(Status::MissingReceiver, "receiver-observation");
    }
    const auto slot = std::ranges::find_if(readbacks, [](const Readback& readback) {
        return !readback.pending;
    });
    if (slot == readbacks.end()) {
        return finish(Status::BusyReadback, "readback-slot");
    }
    auto* depth = textures.TryGetImage(submitted.depth, submitted.depth_uid);
    auto* cb0 = textures.TryGetImage(submitted.cb0, submitted.cb0_uid);
    if (held != HeldPassMode::Off) {
        evidence.image_checks_reached = true;
        if (depth && depth->backing) evidence.depth_format = u32(depth->backing->image.image_ci.format);
        if (cb0 && cb0->backing) evidence.cb0_format = u32(cb0->backing->image.image_ci.format);
    }
    if (!depth || !cb0 || !NativeImage(*depth, submitted) || !NativeImage(*cb0, submitted) ||
        depth->GetImage() != submitted.depth_image || cb0->GetImage() != submitted.cb0_image ||
        !(depth->aspect_mask & vk::ImageAspectFlagBits::eDepth) ||
        cb0->info.pixel_format != vk::Format::eR8G8B8A8Unorm ||
        cb0->backing->image.image_ci.format != vk::Format::eR8G8B8A8Unorm) {
        return finish(Status::InvalidImages, "native-images");
    }
    evidence.images_qualified = true;

    Report report{.stamp = submitted, .request = request};
    auto& retained = report.scenes[u32(Arm::Retained)];
    auto& current = report.scenes[u32(Arm::Current)];
    bool receiver_in_scene = false;
    u32 placed_current = 0;
    for (const auto& clone : clones) {
        Member member = clone.member;
        member.current = Current(clone);
        if (member.identity.receiver) {
            if (!needs_receiver || !member.current || member.identity != *submitted_receiver) {
                continue;
            }
            receiver_in_scene = true;
        }
        if (member.identity.placed != PlacedSource::None) {
            const auto source = member.identity.placed;
            const auto& placement = placements[u32(source)];
            // Only the fireplace can represent a last-observed offscreen snapshot.
            if (!PlacedMemberMatches(placement, member, submitted)) {
                continue;
            }
            const u32 bit = PlacedBit(source);
            if (report.placed_mask & bit) {
                return finish(Status::MissingPlacedFixture, "duplicate-placed-member");
            }
            report.placed_mask |= bit;
            if (member.current) {
                placed_current |= bit;
            }
            if (held != HeldPassMode::Off) {
                evidence.retained_mask = report.placed_mask;
                evidence.current_mask = placed_current;
            }
            member.placement_cookie = placement.cookie;
            member.placement_build_cookie = placement.build_cookie;
        }
        retained.members.push_back(member);
        if (member.current) {
            current.members.push_back(member);
        }
    }
    if (needs_receiver && !receiver_in_scene) {
        return finish(Status::MissingReceiver, "receiver-scene");
    }
    if (PlacedOn()) {
        const u32 wall = PlacedBit(PlacedSource::Wall);
        const u32 fireplace = PlacedBit(PlacedSource::Fireplace);
        const u32 required_current = wall | (needs_receiver ? PlacedBit(PlacedSource::Mirror) : 0u) |
                                     (needs_direct ? fireplace : 0u);
        if ((placed_current & required_current) != required_current || !(report.placed_mask & fireplace)) {
            return finish(Status::MissingPlacedFixture, "required-current-placements");
        }
    }
    if (retained.members.empty()) {
        return finish(Status::MissingScene, "retained-scene");
    }
    evidence.cpu_ready = true;
    if (held == HeldPassMode::Observe) {
        return finish(Status::HeldPassObserved, "none");
    }
    if (!MakePipeline()) {
        return finish(Status::GpuUnavailable, "query-pipeline");
    }
    if (!slot->buffer.handle && !Allocate(slot->buffer, sizeof(BufferLayout),
                                         VK_BUFFER_USAGE_TRANSFER_DST_BIT |
                                             VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, true)) {
        return finish(Status::NoRoom, "readback-allocation");
    }
    scheduler.EndRendering();
    for (u32 arm = 0; arm < ArmCount; ++arm) {
        const auto status = EnsureScene(scenes[arm], report.scenes[arm]);
        if (status != Status::Recorded) {
            return finish(status, arm == u32(Arm::Retained) ? "retained-tlas" : "current-tlas");
        }
    }
    const std::array views{View(*depth, vk::ImageAspectFlagBits::eDepth),
                           View(*cb0, vk::ImageAspectFlagBits::eColor)};
    if (!views[0] || !views[1]) {
        for (auto view : views) {
            if (view) {
                device.destroyImageView(view);
            }
        }
        return finish(Status::InvalidImages, "sampled-views");
    }
    runtime.Transit(depth, vk::ImageLayout::eGeneral, Compute, ImageRead);
    runtime.Transit(cb0, vk::ImageLayout::eGeneral, Compute, ImageRead);
    runtime.FlushBarriers();
    slot->tick = scheduler.CurrentTick();
    slot->epoch = epoch;
    slot->pending = std::move(report);
    RecordSamples(*slot, request, views);
    auto release = detail::MakeScopeGuard(
        [device = device, views] {
            for (auto view : views) {
                device.destroyImageView(view);
            }
        });
    scheduler.DeferOperation([release = std::move(release)] {}, "reflection sampled views");
    return finish(Status::Recorded, "none");
}

void Pass::State::RecordSamples(Readback& slot, const Request& request,
                                  const std::array<vk::ImageView, 2>& views) {
    const Push push{stamp->view,
                    stamp->projection,
                    {request.receiver_plane_normal[0], request.receiver_plane_normal[1],
                     request.receiver_plane_normal[2], 0.f},
                    stamp->jitter,
                    stamp->extent,
                    request.count,
                    slot.pending->placed_mask};
    const std::array handles{scenes[u32(Arm::Retained)].tlas.handle,
                             scenes[u32(Arm::Current)].tlas.handle};
    const BufferInput input{request.pixels, ReportTags(*slot.pending)};
    const vk::DescriptorBufferInfo palette{
        push.placed_mask ? placement_buffer.handle : slot.buffer.handle, 0, PlacementBufferBytes};
    EffectPass::Mark(0x52454602, "reflection first hit");
    scheduler.RecordCrumb(
        {.name = "Reflection first hit"},
        [push, handles, views, input, palette, buffer = slot.buffer.handle,
         pipeline = *pipeline, layout = *layout](vk::CommandBuffer cb) {
            cb.updateBuffer(buffer, 0, sizeof(input), &input);
            EffectPass::MemoryBarrier(cb, Transfer, TransferWrite, Compute, StorageRead);
            const std::array geometry{
                vk::WriteDescriptorSetAccelerationStructureKHR{.accelerationStructureCount = 1,
                                                               .pAccelerationStructures = &handles[0]},
                vk::WriteDescriptorSetAccelerationStructureKHR{.accelerationStructureCount = 1,
                                                               .pAccelerationStructures = &handles[1]},
            };
            const std::array images{
                vk::DescriptorImageInfo{.imageView = views[0], .imageLayout = vk::ImageLayout::eGeneral},
                vk::DescriptorImageInfo{.imageView = views[1], .imageLayout = vk::ImageLayout::eGeneral},
            };
            const vk::DescriptorBufferInfo io{buffer, 0, sizeof(BufferLayout)};
            using enum vk::DescriptorType;
            const std::array writes{
                vk::WriteDescriptorSet{.pNext = &geometry[0], .dstBinding = 0, .descriptorCount = 1,
                                       .descriptorType = eAccelerationStructureKHR},
                vk::WriteDescriptorSet{.pNext = &geometry[1], .dstBinding = 1, .descriptorCount = 1,
                                       .descriptorType = eAccelerationStructureKHR},
                vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1,
                                       .descriptorType = eSampledImage, .pImageInfo = &images[0]},
                vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1,
                                       .descriptorType = eSampledImage, .pImageInfo = &images[1]},
                vk::WriteDescriptorSet{.dstBinding = 4, .descriptorCount = 1,
                                       .descriptorType = eStorageBuffer, .pBufferInfo = &io},
                vk::WriteDescriptorSet{.dstBinding = 5, .descriptorCount = 1,
                                       .descriptorType = eStorageBuffer, .pBufferInfo = &palette},
            };
            cb.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cb.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cb.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cb.dispatch(1, 1, 1);
            EffectPass::MemoryBarrier(cb, Compute, StorageWrite, Host, HostRead);
        });
}

Status Pass::State::Poll(Report& report) {
    auto* oldest = static_cast<Readback*>(nullptr);
    for (auto& slot : readbacks) {
        if (slot.pending && (!oldest || slot.pending->request.serial < oldest->pending->request.serial)) {
            oldest = &slot;
        }
    }
    if (!oldest || !scheduler.IsFree(oldest->tick)) {
        return Status::Pending;
    }
    Report ready = std::move(*oldest->pending);
    oldest->pending.reset();
    if (oldest->epoch != epoch || ready.stamp.generation != BbEngine::Loading::Generation() ||
        BbEngine::Loading::ScreenUp()) {
        return Status::StaleReadback;
    }
    if (vmaInvalidateAllocation(allocator, oldest->buffer.allocation, 0, sizeof(BufferLayout)) !=
        VK_SUCCESS) {
        return Status::InvalidReadback;
    }
    const auto* bytes = static_cast<const std::byte*>(oldest->buffer.mapped);
    Tags echoed;
    std::memcpy(echoed.data(), bytes + offsetof(BufferLayout, echoed), sizeof(echoed));
    if (echoed != ReportTags(ready)) {
        return Status::InvalidReadback;
    }
    std::memcpy(ready.samples.data(), bytes + offsetof(BufferLayout, samples),
                ready.request.count * sizeof(Sample));
    if (!ValidReport(ready)) {
        return Status::InvalidReadback;
    }
    report = std::move(ready);
    return Status::Recorded;
}

Usage Pass::State::GetUsage() const {
    return {allocations->bytes.load(), u32(clones.size()), clone_count, clone_payload, expired,
            pressure_evicted};
}

Pass::Pass(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& textures,
           Runtime& runtime) {
    if (On() && instance.IsRayQuerySupported()) {
        state = std::make_unique<State>(instance, scheduler, textures, runtime);
    }
}

Pass::~Pass() = default;

bool Pass::BeginPass(const Stamp& stamp) {
    return state && state->BeginPass(stamp);
}

void Pass::CloseEpoch() {
    if (state) {
        state->CloseEpoch();
    }
}

void Pass::Submitted(const Stamp& stamp, const Identity& identity) {
    if (state) {
        state->Submitted(stamp, identity);
    }
}

void Pass::RejectReceiver(const Stamp& stamp) {
    if (state) {
        state->RejectReceiver(stamp);
    }
}

void Pass::InvalidateSurface(u64 surface) {
    if (state) {
        state->InvalidateSurface(surface);
    }
}

void Pass::ObserveSurface(u64 surface, u64 placement) {
    if (state) {
        state->ObserveSurface(surface, placement);
    }
}

void Pass::InvalidateAllocation(u64 allocation) {
    if (state) {
        state->InvalidateAllocation(allocation);
    }
}

void Pass::InvalidatePlaced(PlacedSource source) {
    if (state) {
        state->InvalidatePlaced(source);
    }
}

bool Pass::ObservePlaced(const Stamp& stamp, const Identity& identity, u64 cookie,
                         const VideoCore::Buffer& source, u64 offset) {
    return state && state->ObservePlaced(stamp, identity, cookie, source, offset);
}

bool Pass::BuildPlaced(const Stamp& stamp, const Identity& identity, u64 confirmed_cookie) {
    return state && state->BuildPlaced(stamp, identity, confirmed_cookie);
}

bool Pass::CurrentPlaced(const Stamp& stamp, const Identity& identity, u64 confirmed_cookie) const {
    return state && state->CurrentPlaced(stamp, identity, confirmed_cookie);
}

Status Pass::Clone(const Stamp& stamp, const Identity& identity, vk::AccelerationStructureKHR source,
                   vk::DeviceSize source_creation_size) {
    return state ? state->Clone(stamp, identity, source, source_creation_size) : Status::Disabled;
}

Status Pass::Submit(const Stamp& stamp, const Request& request) {
    return state ? state->Submit(stamp, request) : Status::Disabled;
}

Status Pass::Poll(Report& report) {
    return state ? state->Poll(report) : Status::Disabled;
}

Usage Pass::GetUsage() const {
    return state ? state->GetUsage() : Usage{};
}

} // namespace Vulkan::ReflectionFirstHit
