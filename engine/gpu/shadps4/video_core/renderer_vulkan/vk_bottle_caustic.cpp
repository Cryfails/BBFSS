// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_bottle_caustic.h"
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
#include "video_core/renderer_vulkan/vk_bottle_raw_apply_b180.h"
#endif
#include "video_core/renderer_vulkan/vk_bottle_motion_t198.h"

#include <algorithm>
#include <atomic>
#include <bit>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstddef>
#include <memory>
#include <optional>
#include <string_view>
#include <utility>

#if __has_include("bbport_live_knobs.h")
#include "bbport_live_knobs.h"
#endif
#include "video_core/host_shaders/bottle_caustic_comp.h"
#include "video_core/renderer_vulkan/bottle_caustic_topology.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_point_shadow.h"
#include "video_core/renderer_vulkan/vk_rt_shadow.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/texture_cache/texture_cache.h"
#include "video_core/renderer_vulkan/vk_workflow_present.h"
#include "bbport_toggles.h"

namespace Vulkan::BottleCaustic {
namespace {
constexpr u32 LampLimit = 64;
constexpr u32 Rays = 1024;
constexpr u32 Buckets = 4096;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto All = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Read = vk::AccessFlagBits2::eShaderRead;
constexpr auto Write = vk::AccessFlagBits2::eShaderWrite;
constexpr auto ReadWrite = Read | Write;
constexpr auto Mem = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;

struct Lamp {
    std::array<float, 4> position_radius;
    std::array<float, 4> color;
};
struct Data {
    std::array<Lamp, LampLimit> lamps;
    std::array<float, 24> setup;
    std::array<u32, 8> commands;
    std::array<u32, Buckets> heads;
    std::array<std::array<u32, 8>, Rays> records;
};
struct Push {
    std::array<float, 12> view;
    std::array<float, 4> proj;
    std::array<float, 2> jitter;
    std::array<u32, 2> size;
    u32 ordinal;
    u32 lamp_count;
    u32 phase;
    float ior;
    float emitter_clearance;
};
static_assert(sizeof(Push) == 100 && offsetof(Push, emitter_clearance) == 96);
static_assert(sizeof(Data) == 51328);
static_assert(offsetof(Data, commands) == 2144 && offsetof(Data, heads) == 2176 && offsetof(Data, records) == 18560);

bool Enabled(const char* text) {
    return text && (std::strcmp(text, "1") == 0 || std::strcmp(text, "on") == 0);
}

// Test tool t176. Keep the regular scratch usage and dispatch path when the tool is off.
bool StoreProofFlag(const char* text) {
    return text && std::strcmp(text, "1") == 0;
}
bool StoreProofEnabled() {
    static const bool enabled = StoreProofFlag(std::getenv("BB_GLASS_CAUSTIC_STORE_PROOF"));
    return enabled;
}
bool ClaimStoreProof() {
    static std::atomic<bool> claimed{false};
    if (!StoreProofEnabled() || claimed.load(std::memory_order_relaxed)) {
        return false;
    }
#if __has_include("bbport_live_knobs.h")
    static BbLiveKnobs::Knob<bool> arm{"BB_GLASS_CAUSTIC_STORE_ARM", StoreProofFlag};
    const bool armed = arm.Get();
#else
    const bool armed = StoreProofFlag(std::getenv("BB_GLASS_CAUSTIC_STORE_ARM"));
#endif
    return armed && !claimed.exchange(true, std::memory_order_relaxed);
}

constexpr u32 StoreWidth = 1920, StoreHeight = 1080, StoreSide = 13;
constexpr std::array<vk::Offset3D, 2> StoreOrigins{{{1634, 557, 0}, {1199, 535, 0}}};
constexpr std::array StoreNames{"receiver", "moulding"};
constexpr auto StoreTexels = StoreSide * StoreSide;
using StoreTexel = std::array<u16, 4>;
constexpr vk::DeviceSize StoreRegionBytes = StoreTexels * sizeof(StoreTexel);
constexpr vk::DeviceSize StoreImageBytes = StoreRegionBytes * StoreOrigins.size() * 2;
struct StoreSetup {
    std::array<float, 4> center_active;
    std::array<float, 4> source_radius;
    std::array<float, 4> color_distance;
    std::array<float, 8> aperture;
    std::array<float, 4> bounds;
    std::array<u32, 8> commands;
};
static_assert(sizeof(StoreSetup) == sizeof(Data::setup) + sizeof(Data::commands));
constexpr vk::DeviceSize StoreBytes = StoreImageBytes + sizeof(StoreSetup);
static_assert(StoreImageBytes == 5408 && StoreBytes == 5536 && StoreRegionBytes % 8 == 0);

float StoreHalf(u16 word) {
    const int exponent = (word >> 10) & 31;
    const int fraction = word & 1023;
    const float magnitude = std::ldexp(float(exponent ? 1024 + fraction : fraction),
                                       exponent ? exponent - 25 : -24);
    return (word & 0x8000) ? -magnitude : magnitude;
}

struct StoreStats {
    std::array<double, 4> net{};
    std::array<float, 4> max_abs{};
    double positive_red_sum = 0;
    float max_red_added = 0;
    u32 pixels_changed = 0, rgb_changed = 0, alpha_changed = 0;
    u32 red_up = 0, red_down = 0, nonfinite_pairs = 0;

    void Add(const StoreTexel& before, const StoreTexel& after) {
        pixels_changed += before != after;
        rgb_changed += before[0] != after[0] || before[1] != after[1] || before[2] != after[2];
        alpha_changed += before[3] != after[3];
        for (u32 channel = 0; channel < before.size(); ++channel) {
            if ((before[channel] & 0x7c00) == 0x7c00 || (after[channel] & 0x7c00) == 0x7c00) {
                ++nonfinite_pairs;
                continue;
            }
            const float delta = StoreHalf(after[channel]) - StoreHalf(before[channel]);
            net[channel] += delta;
            max_abs[channel] = std::max(max_abs[channel], std::abs(delta));
            if (channel == 0) {
                red_up += delta > 0;
                red_down += delta < 0;
                positive_red_sum += std::max(0.f, delta);
                max_red_added = std::max(max_red_added, delta);
            }
        }
    }
};

struct StoreReadback {
    VmaAllocator allocator{};
    VkBuffer buffer{};
    VmaAllocation allocation{};
    const u8* mapped{};

    ~StoreReadback() {
        if (buffer) {
            vmaDestroyBuffer(allocator, buffer, allocation);
        }
    }

    bool Allocate(vk::DeviceSize bytes) {
        const VkBufferCreateInfo ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = bytes,
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        const VmaAllocationCreateInfo ai{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
        };
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(allocator, &ci, &ai, &buffer, &allocation, &info) != VK_SUCCESS) {
            return false;
        }
        mapped = static_cast<const u8*>(info.pMappedData);
        return mapped != nullptr;
    }

};

struct StoreProof : StoreReadback {
    vk::Image image{};
    u64 frame{}, tick{}, uid{}, generation{};
    u32 image_id{}, width{}, height{}, image_width{}, image_height{}, ordinal{}, lamps{};
    std::array<float, 2> jitter{};
    float ior{}, clearance{};
    bool proxy{};

    void Report() const {
        if (vmaInvalidateAllocation(allocator, allocation, 0, StoreBytes) != VK_SUCCESS) {
            std::printf("[bottle-store-t176] event=refused why=host-invalidate\n");
            return;
        }
        const auto stamp = [](u64 value) { return static_cast<unsigned long long>(value); };
        const auto handle = std::bit_cast<u64>(static_cast<VkImage>(image));
        StoreSetup setup{};
        std::memcpy(&setup, mapped + StoreImageBytes, sizeof(setup));
        std::printf("[bottle-store-t176] event=completed frame=%llu tick=%llu image_id=%u uid=%llu image=%llx "
                    "domain=%s generation=%llu width=%u height=%u image_width=%u image_height=%u "
                    "format=RGBA16F ordinal=%u candidates=%u "
                    "ior=%.3f clearance=%.6f jitter=(%.7g,%.7g) bytes=%llu\n",
                    stamp(frame), stamp(tick), image_id, stamp(uid), stamp(handle), proxy ? "proxy" : "native",
                    stamp(generation), width, height, image_width, image_height, ordinal, lamps,
                    ior, clearance, jitter[0], jitter[1],
                    stamp(StoreBytes));
        const bool dispatched = setup.commands[4] && setup.commands[5] && setup.commands[6];
        if (setup.center_active[3] > 0.f) {
            std::printf("[bottle-store-t176] event=lamp position=(%.8g,%.8g,%.8g) radius=%.8g "
                        "rgb=(%.8g,%.8g,%.8g) distance=%.8g phase2_groups=(%u,%u,%u) bounds=(%.0f,%.0f,%.0f,%.0f)\n",
                        setup.source_radius[0], setup.source_radius[1], setup.source_radius[2], setup.source_radius[3],
                        setup.color_distance[0], setup.color_distance[1], setup.color_distance[2],
                        setup.color_distance[3], setup.commands[4], setup.commands[5], setup.commands[6],
                        setup.bounds[0], setup.bounds[1], setup.bounds[2], setup.bounds[3]);
        } else {
            std::printf("[bottle-store-t176] event=lamp selected=unconfirmed phase2_groups=(%u,%u,%u)\n",
                        setup.commands[4], setup.commands[5], setup.commands[6]);
        }
        for (u32 roi = 0; roi < StoreOrigins.size(); ++roi) {
            StoreStats stats{};
            for (u32 row = 0; row < StoreSide; ++row) {
                std::array<char, 34 * StoreSide + 1> raw{};
                for (u32 column = 0; column < StoreSide; ++column) {
                    const auto offset = roi * StoreRegionBytes + (row * StoreSide + column) * sizeof(StoreTexel);
                    StoreTexel before{}, after{};
                    std::memcpy(&before, mapped + offset, sizeof(before));
                    std::memcpy(&after, mapped + offset + StoreImageBytes / 2, sizeof(after));
                    stats.Add(before, after);
                    std::snprintf(raw.data() + 34 * column, 35,
                                  "%04x%04x%04x%04x/%04x%04x%04x%04x ",
                                  u32(before[0]), u32(before[1]), u32(before[2]), u32(before[3]),
                                  u32(after[0]), u32(after[1]), u32(after[2]), u32(after[3]));
                }
                std::printf("[bottle-store-t176] event=raw roi=%s y=%d x=%d rgba16f_before_after=%s\n",
                            StoreNames[roi], StoreOrigins[roi].y + s32(row), StoreOrigins[roi].x, raw.data());
            }
            const char* result = stats.pixels_changed ? "changed" : "unchanged-inconclusive";
            if (!dispatched) {
                result = "phase2-empty";
            }
            std::printf("[bottle-store-t176] event=summary roi=%s result=%s pixels=%u changed=%u rgb_changed=%u "
                        "alpha_changed=%u red_up=%u red_down=%u nonfinite_pairs=%u positive_red_sum=%.9g "
                        "max_red_added=%.9g net_rgba=(%.9g,%.9g,%.9g,%.9g) max_abs_rgba=(%.9g,%.9g,%.9g,%.9g)\n",
                        StoreNames[roi], result, StoreTexels, stats.pixels_changed, stats.rgb_changed,
                        stats.alpha_changed, stats.red_up,
                        stats.red_down, stats.nonfinite_pairs, stats.positive_red_sum, stats.max_red_added,
                        stats.net[0], stats.net[1], stats.net[2], stats.net[3],
                        stats.max_abs[0], stats.max_abs[1], stats.max_abs[2], stats.max_abs[3]);
        }
    }
};

// t185 captures the ordinary phase-1 spatial hash once, after the same fence as t176.
bool FootprintEnabled() {
    static const bool enabled = StoreProofFlag(std::getenv("BB_GLASS_CAUSTIC_FOOTPRINT_PROOF"));
    return enabled;
}

bool ClaimFootprint() {
    static std::atomic<bool> claimed{false};
    if (!FootprintEnabled() || claimed.load(std::memory_order_relaxed)) {
        return false;
    }
#if __has_include("bbport_live_knobs.h")
    static BbLiveKnobs::Knob<bool> arm{"BB_GLASS_CAUSTIC_FOOTPRINT_ARM", StoreProofFlag};
    const bool armed = arm.Get();
#else
    const bool armed = StoreProofFlag(std::getenv("BB_GLASS_CAUSTIC_FOOTPRINT_ARM"));
#endif
    return armed && !claimed.exchange(true, std::memory_order_relaxed);
}

struct FootprintRecord {
    std::array<float, 3> point;
    u32 normal;
    std::array<float, 3> flux;
    u32 next;
};
struct FootprintSnapshot {
    StoreSetup setup;
    std::array<u32, Buckets> heads;
    std::array<FootprintRecord, Rays> records;
};
constexpr auto FootprintOffset = offsetof(Data, setup);
constexpr auto FootprintHashBytes = sizeof(Data::heads) + sizeof(Data::records);
constexpr auto FootprintBytes = sizeof(FootprintSnapshot);
constexpr float FootprintKernel = 0.018f; // bottle_caustic.comp phase 1 and phase 2
constexpr u32 FootprintChainLimit = 48;   // ordinary phase 2's per-bucket traversal limit
static_assert(sizeof(FootprintRecord) == 32 && offsetof(FootprintRecord, normal) == 12 &&
              offsetof(FootprintRecord, flux) == 16 && offsetof(FootprintRecord, next) == 28);
static_assert(FootprintHashBytes == 48 * 1024 && FootprintBytes == FootprintHashBytes + 128 &&
              offsetof(FootprintSnapshot, heads) + FootprintOffset == offsetof(Data, heads) &&
              offsetof(FootprintSnapshot, records) + FootprintOffset == offsetof(Data, records) &&
              FootprintOffset + FootprintBytes == sizeof(Data));

template <std::size_t N>
bool FootprintFinite(const std::array<float, N>& values) {
    return std::ranges::all_of(values, [](float v) { return std::isfinite(v); });
}

struct FootprintHit {
    const FootprintRecord* record{};
    std::array<float, 3> normal{};
    std::array<float, 2> projected{};
    std::array<u32, 2> texel{};
    u32 id{}, bucket{}, ordinal{};
};

float FootprintDot(const std::array<float, 3>& a, const std::array<float, 3>& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

bool FootprintProjection(const Push& args, const std::array<float, 3>& world,
                         std::array<float, 2>& screen) {
    std::array<float, 3> p{};
    for (u32 i = 0; i < p.size(); ++i) {
        const auto* row = args.view.data() + i * 4;
        p[i] = row[0] * world[0] + row[1] * world[1] + row[2] * world[2] + row[3];
    }
    if (!FootprintFinite(p) || p[2] <= 0.1f) {
        return false;
    }
    for (u32 i = 0; i < screen.size(); ++i) {
        screen[i] = (p[i] * args.proj[i] / p[2] * 0.5f + 0.5f) * float(args.size[i]) + args.jitter[i];
        if (!(screen[i] >= 0.f && screen[i] < float(args.size[i]))) {
            return false;
        }
    }
    return true;
}

const char* FootprintDecode(const Push& args, const FootprintSnapshot& capture,
                            std::array<FootprintHit, Rays>& hits, u32& count, u32& buckets,
                            u32& over_phase2_limit, u32& longest) {
    const auto& setup = capture.setup;
    const auto& command = setup.commands;
    if ((command[0] != 0 && command[0] != Rays / 64) || command[1] != 1 || command[2] != 1 ||
        command[3] != 0 || command[6] != 1 || command[7] != 0) {
        return "indirect-command";
    }
    if (!command[0]) {
        return setup.center_active[3] == 0.f && command[4] == 0 && command[5] == 0 &&
               std::ranges::none_of(capture.heads, [](u32 head) { return head != 0; })
            ? nullptr : "inactive-with-heads-or-phase2";
    }
    if (!FootprintFinite(setup.center_active) ||
        !(setup.center_active[3] > 0.01f && setup.center_active[3] < 0.35f) ||
        !FootprintFinite(setup.source_radius) || !(setup.source_radius[3] > 0.f) ||
        !FootprintFinite(setup.color_distance) || !(setup.color_distance[3] > 0.f) ||
        setup.color_distance[0] < 0.f || setup.color_distance[1] < 0.f ||
        setup.color_distance[2] < 0.f || !FootprintFinite(setup.bounds)) {
        return "active-setup";
    }
    for (u32 i = 0; i < 2; ++i) {
        const float lo = setup.bounds[i], hi = setup.bounds[i + 2];
        if (lo < 0.f || hi < lo || hi > float(args.size[i]) || std::floor(lo) != lo ||
            std::floor(hi) != hi || command[i + 4] != (u32(hi - lo) + 7) / 8) {
            return "phase2-bounds";
        }
    }

    std::array<bool, Rays> seen{};
    for (u32 bucket = 0; bucket < Buckets; ++bucket) {
        u32 ptr = capture.heads[bucket], ordinal = 0;
        buckets += ptr != 0;
        while (ptr != 0) {
            if (ptr > Rays || seen[ptr - 1]) {
                return ptr > Rays ? "record-id-out-of-range" : "record-linked-more-than-once";
            }
            seen[ptr - 1] = true;
            const auto& record = capture.records[ptr - 1];
            if (!FootprintFinite(record.point) || !FootprintFinite(record.flux) ||
                std::ranges::any_of(record.flux, [](float v) { return v < 0.f; }) ||
                (record.normal >> 24) != 0) {
                return "record-payload";
            }

            std::array<u32, 3> cell{};
            for (u32 i = 0; i < cell.size(); ++i) {
                const float index = std::floor((record.point[i] - setup.center_active[i]) / FootprintKernel);
                if (!(index >= -2147483648.f && index < 2147483648.f)) {
                    return "record-cell";
                }
                cell[i] = u32(s32(index));
            }
            if (((cell[0] * 73856093u ^ cell[1] * 19349663u ^ cell[2] * 83492791u) &
                 (Buckets - 1)) != bucket) {
                return "record-bucket";
            }

            auto& hit = hits[count++];
            hit.record = &record;
            hit.id = ptr;
            hit.bucket = bucket;
            hit.ordinal = ++ordinal;
            over_phase2_limit += ordinal > FootprintChainLimit;
            longest = std::max(longest, ordinal);
            for (u32 i = 0; i < hit.normal.size(); ++i) {
                const int lane = int((record.normal >> (i * 8)) & 255);
                if (lane == 128) {
                    return "record-normal-encoding";
                }
                hit.normal[i] = float(lane > 127 ? lane - 256 : lane) / 127.f;
            }
            // The input is normalized and the worst three-axis packing error is sqrt(3)/254.
            if (std::abs(std::sqrt(FootprintDot(hit.normal, hit.normal)) - 1.f) > 0.00683f) {
                return "record-normal-length";
            }
            if (!FootprintProjection(args, record.point, hit.projected)) {
                return "record-projection";
            }
            hit.texel = {u32(hit.projected[0]), u32(hit.projected[1])};
            ptr = record.next;
        }
    }
    return nullptr;
}

struct FootprintRanking {
    const FootprintHit* raw_peak{};
    const FootprintHit* seed{};
    std::array<double, 3> total{};
    std::array<double, 3> seed_flux{};
    std::array<u32, 4> texel_bounds{};
};

double FootprintLuma(const std::array<double, 3>& value) {
    return value[0] * 0.2126 + value[1] * 0.7152 + value[2] * 0.0722;
}

FootprintRanking RankFootprint(const FootprintHit* hits, u32 count, const StoreSetup& setup) {
    FootprintRanking result{};
    result.texel_bounds = {hits[0].texel[0], hits[0].texel[1], hits[0].texel[0], hits[0].texel[1]};
    double best_raw = -1, best_seed = 0;
    for (u32 i = 0; i < count; ++i) {
        const auto& hit = hits[i];
        const auto& raw = hit.record->flux;
        const double raw_luma = FootprintLuma({raw[0], raw[1], raw[2]});
        if (raw_luma > best_raw || (raw_luma == best_raw && hit.id < result.raw_peak->id)) {
            best_raw = raw_luma;
            result.raw_peak = &hit;
        }
        for (u32 axis = 0; axis < 2; ++axis) {
            result.texel_bounds[axis] = std::min(result.texel_bounds[axis], hit.texel[axis]);
            result.texel_bounds[axis + 2] = std::max(result.texel_bounds[axis + 2], hit.texel[axis]);
        }
        for (u32 channel = 0; channel < 3; ++channel) {
            result.total[channel] += raw[channel];
        }

        // A measured hit is a search seed. Phase 2 evaluates the depth-reconstructed pixel
        // centre and unpacked G-buffer normal, and multiplies by albedo, none of which are copied.
        const auto& b = setup.bounds;
        if (float(hit.texel[0]) < b[0] || float(hit.texel[0]) > b[2] ||
            float(hit.texel[1]) < b[1] || float(hit.texel[1]) > b[3] ||
            hit.texel[0] - u32(b[0]) >= setup.commands[4] * 8 ||
            hit.texel[1] - u32(b[1]) >= setup.commands[5] * 8) {
            continue;
        }
        const std::array<float, 3> from_bottle{hit.record->point[0] - setup.center_active[0],
                                               hit.record->point[1] - setup.center_active[1],
                                               hit.record->point[2] - setup.center_active[2]};
        const float receiver_bound = setup.center_active[3] + 0.45f + FootprintKernel * 2.f;
        if (FootprintDot(from_bottle, from_bottle) > receiver_bound * receiver_bound) {
            continue;
        }
        const float normal_length = std::sqrt(FootprintDot(hit.normal, hit.normal));
        const std::array<float, 3> normal{hit.normal[0] / normal_length, hit.normal[1] / normal_length,
                                          hit.normal[2] / normal_length};
        std::array<double, 3> rgb{};
        for (u32 j = 0; j < count; ++j) {
            const auto& other = hits[j];
            if (other.ordinal > FootprintChainLimit) {
                continue;
            }
            const std::array<float, 3> delta{hit.record->point[0] - other.record->point[0],
                                             hit.record->point[1] - other.record->point[1],
                                             hit.record->point[2] - other.record->point[2]};
            const float distance2 = FootprintDot(delta, delta);
            if (!(distance2 < FootprintKernel * FootprintKernel) ||
                FootprintDot(other.normal, normal) <= 0.88f ||
                std::abs(FootprintDot(delta, other.normal)) >= 0.0035f) {
                continue;
            }
            const double weight = (1.0 - std::sqrt(distance2) / FootprintKernel) * 3.0 /
                                  (3.1415926536 * FootprintKernel * FootprintKernel);
            for (u32 channel = 0; channel < 3; ++channel) {
                rgb[channel] += double(other.record->flux[channel]) * weight;
            }
        }
        const auto luma = FootprintLuma(rgb);
        if (luma > best_seed || (result.seed && luma == best_seed && hit.id < result.seed->id)) {
            best_seed = luma;
            result.seed = &hit;
            result.seed_flux = rgb;
        }
    }
    return result;
}

void PrintFootprintHit(const char* name, const FootprintHit& hit) {
    const auto& r = *hit.record;
    std::printf("[bottle-footprint-t185] event=%s id=%u ray_index=%u grid=(%u,%u) bucket=%u "
                "chain_rank=%u world=(%.9g,%.9g,%.9g) projected=(%.9g,%.9g) texel=(%u,%u) "
                "normal=(%.9g,%.9g,%.9g) packed_normal=%08x flux=(%.9g,%.9g,%.9g)\n",
                name, hit.id, hit.id - 1, (hit.id - 1) % 32, (hit.id - 1) / 32, hit.bucket,
                hit.ordinal, r.point[0], r.point[1], r.point[2], hit.projected[0], hit.projected[1],
                hit.texel[0], hit.texel[1], hit.normal[0], hit.normal[1], hit.normal[2],
                r.normal, r.flux[0], r.flux[1], r.flux[2]);
}

struct FootprintProof : StoreReadback {
    Push args{};
    std::array<u64, 4> uids{};
    std::array<u32, 4> ids{};
    std::array<u64, 4> views{};
    u64 frame{}, tick{}, draw_timeline{}, qpc_ns{}, app_frames_at_record{}, generation{};
    bool proxy{};

    void Report() const {
        if (vmaInvalidateAllocation(allocator, allocation, 0, FootprintBytes) != VK_SUCCESS) {
            std::printf("[bottle-footprint-t185] event=refused why=host-invalidate\n");
            return;
        }
        const auto stamp = [](u64 v) { return static_cast<unsigned long long>(v); };
        std::printf("[bottle-footprint-t185] event=sample frame=%llu draw_tick=%llu draw_timeline=%llx "
                    "qpc_ns=%llu app_frames_at_record=%llu "
                    "domain=%s generation=%llu input=(%u,%u) ordinal=%u lamp_candidates=%u "
                    "ior=%.9g clearance=%.9g hash_bytes=%zu payload_bytes=%zu\n",
                    stamp(frame), stamp(tick), stamp(draw_timeline), stamp(qpc_ns),
                    stamp(app_frames_at_record), proxy ? "proxy" : "native", stamp(generation),
                    args.size[0], args.size[1], args.ordinal, args.lamp_count, args.ior,
                    args.emitter_clearance, FootprintHashBytes, FootprintBytes);
        constexpr std::array names{"hdr", "depth", "normal", "albedo"};
        for (u32 i = 0; i < names.size(); ++i) {
            std::printf("[bottle-footprint-t185] event=binding role=%s id=%u uid=%llu view=%llx\n",
                        names[i], ids[i], stamp(uids[i]), stamp(views[i]));
        }
        for (u32 i = 0; i < 3; ++i) {
            const auto* r = args.view.data() + 4 * i;
            std::printf("[bottle-footprint-t185] event=view row=%u value=(%.9g,%.9g,%.9g,%.9g)\n",
                        i, r[0], r[1], r[2], r[3]);
        }
        std::printf("[bottle-footprint-t185] event=projection proj=(%.9g,%.9g,%.9g,%.9g) jitter=(%.9g,%.9g)\n",
                    args.proj[0], args.proj[1], args.proj[2], args.proj[3], args.jitter[0], args.jitter[1]);

        FootprintSnapshot capture;
        std::memcpy(&capture, mapped, sizeof(capture));
        std::array<FootprintHit, Rays> hits{};
        u32 count = 0, buckets = 0, over_limit = 0, longest = 0;
        if (const char* why = FootprintDecode(args, capture, hits, count, buckets, over_limit, longest)) {
            std::printf("[bottle-footprint-t185] event=refused why=%s\n", why);
            return;
        }
        const auto& setup = capture.setup;
        if (!setup.commands[0]) {
            std::printf("[bottle-footprint-t185] event=empty why=no-phase1\n");
            return;
        }
        std::printf("[bottle-footprint-t185] event=lamp position=(%.9g,%.9g,%.9g) radius=%.9g "
                    "rgb=(%.9g,%.9g,%.9g) distance=%.9g phase2_groups=(%u,%u,%u) bounds=(%.0f,%.0f,%.0f,%.0f)\n",
                    setup.source_radius[0], setup.source_radius[1], setup.source_radius[2],
                    setup.source_radius[3], setup.color_distance[0], setup.color_distance[1],
                    setup.color_distance[2], setup.color_distance[3], setup.commands[4], setup.commands[5],
                    setup.commands[6], setup.bounds[0], setup.bounds[1], setup.bounds[2], setup.bounds[3]);
        if (!count) {
            std::printf("[bottle-footprint-t185] event=empty why=no-reachable-hits\n");
            return;
        }
        const auto result = RankFootprint(hits.data(), count, setup);
        const auto bounds = result.texel_bounds;
        std::printf("[bottle-footprint-t185] event=summary hits=%u occupied_buckets=%u max_chain=%u "
                    "past_phase2_limit=%u texel_bounds=(%u,%u,%u,%u) total_raw_flux=(%.9g,%.9g,%.9g)\n",
                    count, buckets, longest, over_limit, bounds[0], bounds[1], bounds[2], bounds[3],
                    result.total[0], result.total[1], result.total[2]);
        PrintFootprintHit("strongest_raw_hit", *result.raw_peak);
        if (result.seed) {
            PrintFootprintHit("estimated_kernel_seed", *result.seed);
            std::printf("[bottle-footprint-t185] event=estimated_kernel_flux rgb=(%.9g,%.9g,%.9g)\n",
                        result.seed_flux[0], result.seed_flux[1], result.seed_flux[2]);
        }
    }
};


constexpr auto StoreTransfer = vk::PipelineStageFlagBits2::eAllTransfer;
constexpr auto StoreTransferRead = vk::AccessFlagBits2::eTransferRead;
constexpr auto StoreTransferWrite = vk::AccessFlagBits2::eTransferWrite;
// t190 reads ordinary b161 depth, with no new engine rays or depth rendering.
constexpr u32 DepthTapMax = 8;
struct DepthTapRequest {
    u64 serial{}, uid{}, view{}, generation{};
    u32 image_id{}, count{};
    std::array<std::array<u32, 2>, DepthTapMax> pixels{};
};

template <typename T>
bool TapNumber(std::string_view text, T& value, int base = 10) {
    if (text.empty()) {
        return false;
    }
    const auto* end = text.data() + text.size();
    const auto [ptr, ec] = std::from_chars(text.data(), end, value, base);
    return ec == std::errc{} && ptr == end;
}

bool ParseDepthTap(std::string_view text, DepthTapRequest& request) {
    if (text.size() > 127 || !text.ends_with('!')) {
        return false;
    }
    text.remove_suffix(1);
    auto pop = [&](char delimiter) {
        const auto pos = text.find(delimiter);
        if (pos == std::string_view::npos) {
            return std::string_view{};
        }
        const auto part = text.substr(0, pos);
        text.remove_prefix(pos + 1);
        return part;
    };
    if (!TapNumber(pop('/'), request.serial) || !TapNumber(pop('/'), request.uid) ||
        !TapNumber(pop('/'), request.view, 16) || !TapNumber(pop('/'), request.generation) ||
        !TapNumber(pop(':'), request.image_id) || !request.serial || !request.uid ||
        !request.view || !request.generation || !request.image_id || text.empty()) {
        return false;
    }

    while (!text.empty()) {
        if (request.count == DepthTapMax) {
            return false;
        }
        const auto semi = text.find(';');
        const auto pair = text.substr(0, semi);
        const auto slash = pair.find('/');
        auto& p = request.pixels[request.count];
        if (slash == std::string_view::npos || !TapNumber(pair.substr(0, slash), p[0]) ||
            !TapNumber(pair.substr(slash + 1), p[1])) {
            return false;
        }
        if (std::find(request.pixels.begin(), request.pixels.begin() + request.count, p) !=
            request.pixels.begin() + request.count) {
            return false;
        }
        ++request.count;
        if (semi == std::string_view::npos) {
            return true;
        }
        text.remove_prefix(semi + 1);
    }
    return false;
}

std::optional<DepthTapRequest> ClaimDepthTap() {
    static const bool enabled = StoreProofFlag(std::getenv("BB_GLASS_CAUSTIC_DEPTH_PROOF"));
    static std::atomic<bool> claimed{false};
    if (!enabled || claimed.load(std::memory_order_relaxed)) {
        return std::nullopt;
    }
#if __has_include("bbport_live_knobs.h")
    static std::atomic<u32> last_generation{~0u};
    const u32 generation = BbLiveKnobs::Generation();
    if (last_generation.load(std::memory_order_relaxed) == generation ||
        last_generation.exchange(generation, std::memory_order_relaxed) == generation) {
        return std::nullopt;
    }
    const auto value = BbLiveKnobs::Lookup("BB_GLASS_CAUSTIC_DEPTH_TAPS");
    const char* read = value.Get();
#else
    const char* read = std::getenv("BB_GLASS_CAUSTIC_DEPTH_TAPS");
#endif
    if (!read || !*read || claimed.exchange(true, std::memory_order_relaxed)) {
        return std::nullopt;
    }
    DepthTapRequest request{};
    if (!ParseDepthTap(read, request)) {
        std::printf("[bottle-depth-t190] event=refused why=request-format\n");
        return std::nullopt;
    }
    return request;
}

struct DepthTapProof : StoreReadback {
    Push args{};
    DepthTapRequest request{};
    vk::Image image{};
    vk::ImageAspectFlags barrier_aspects{};
    u64 frame{}, tick{}, timeline{}, qpc_ns{}, app_frames{};

    vk::DeviceSize Bytes() const {
        return request.count * sizeof(u32);
    }

    void Copy(vk::CommandBuffer cb) const {
        const vk::ImageMemoryBarrier2 before{
            .srcStageMask = All, .srcAccessMask = Mem, .dstStageMask = StoreTransfer, .dstAccessMask = StoreTransferRead,
            .oldLayout = vk::ImageLayout::eGeneral, .newLayout = vk::ImageLayout::eGeneral,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = image, .subresourceRange = {barrier_aspects, 0, 1, 0, 1},
        };
        cb.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &before});
        std::array<vk::BufferImageCopy, DepthTapMax> regions{};
        for (u32 i = 0; i < request.count; ++i) {
            const auto [x, y] = request.pixels[i];
            regions[i] = {
                .bufferOffset = i * sizeof(u32), .imageSubresource = {vk::ImageAspectFlagBits::eDepth, 0, 0, 1},
                .imageOffset = {s32(x), s32(y), 0}, .imageExtent = {1, 1, 1},
            };
        }
        cb.copyImageToBuffer(image, vk::ImageLayout::eGeneral, buffer,
                             vk::ArrayProxy<const vk::BufferImageCopy>{request.count, regions.data()});

        auto after = before;
        after.srcStageMask = StoreTransfer;
        after.srcAccessMask = StoreTransferRead;
        after.dstStageMask = All;
        after.dstAccessMask = Mem;
        const vk::MemoryBarrier2 to_host{
            .srcStageMask = StoreTransfer, .srcAccessMask = StoreTransferWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eHost, .dstAccessMask = vk::AccessFlagBits2::eHostRead,
        };
        cb.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_host,
                             .imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &after});
    }

    void Report() const {
        const auto stamp = [](u64 v) { return static_cast<unsigned long long>(v); };
        if (vmaInvalidateAllocation(allocator, allocation, 0, Bytes()) != VK_SUCCESS) {
            std::printf("[bottle-depth-t190] event=refused serial=%llu why=host-invalidate\n", stamp(request.serial));
            return;
        }
        std::printf("[bottle-depth-t190] event=sample serial=%llu frame=%llu draw_tick=%llu draw_timeline=%llx "
                    "qpc_ns=%llu app_frames_at_record=%llu id=%u uid=%llu view=%llx image=%llx "
                    "domain=proxy generation=%llu extent=%ux%u mip=0 layer=0 aspect=depth count=%u\n",
                    stamp(request.serial), stamp(frame), stamp(tick), stamp(timeline), stamp(qpc_ns),
                    stamp(app_frames), request.image_id, stamp(request.uid), stamp(request.view),
                    stamp(std::bit_cast<u64>(static_cast<VkImage>(image))), stamp(request.generation),
                    args.size[0], args.size[1], request.count);
        for (u32 i = 0; i < 3; ++i) {
            const auto* row = args.view.data() + 4 * i;
            std::printf("[bottle-depth-t190] event=view row=%u value=(%.9g,%.9g,%.9g,%.9g)\n",
                        i, row[0], row[1], row[2], row[3]);
        }
        std::printf("[bottle-depth-t190] event=projection proj=(%.9g,%.9g,%.9g,%.9g) jitter=(%.9g,%.9g)\n",
                    args.proj[0], args.proj[1], args.proj[2], args.proj[3], args.jitter[0], args.jitter[1]);
        u32 finite = 0;
        for (u32 i = 0; i < request.count; ++i) {
            u32 word{};
            std::memcpy(&word, mapped + i * sizeof(word), sizeof(word));
            const auto [x,y] = request.pixels[i];
            const float depth = std::bit_cast<float>(word);
            const bool valid = std::isfinite(depth) && depth > 0.f && depth < 1.f;
            finite += valid;
            std::printf("[bottle-depth-t190] event=tap x=%u y=%u d32=%08x finite=%u\n", x, y, word, u32(valid));
        }
        std::printf("[bottle-depth-t190] event=completed serial=%llu valid=%u count=%u\n",
                    stamp(request.serial), finite, request.count);
    }
};



void StoreImageBarrier(vk::CommandBuffer cb, vk::Image image, vk::PipelineStageFlags2 from,
                       vk::AccessFlags2 from_access, vk::PipelineStageFlags2 to, vk::AccessFlags2 to_access) {
    // GENERAL is valid for the copy and keeps the ordinary scene target's tracked layout intact.
    const vk::ImageMemoryBarrier2 barrier{
        .srcStageMask = from, .srcAccessMask = from_access, .dstStageMask = to, .dstAccessMask = to_access,
        .oldLayout = vk::ImageLayout::eGeneral, .newLayout = vk::ImageLayout::eGeneral,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .image = image, .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    };
    cb.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
}

void StoreCopy(vk::CommandBuffer cb, vk::Image image, vk::Buffer readback, bool after) {
    std::array<vk::BufferImageCopy, StoreOrigins.size()> regions{};
    for (u32 i = 0; i < regions.size(); ++i) {
        regions[i] = {
            .bufferOffset = (after ? StoreImageBytes / 2 : 0) + i * StoreRegionBytes,
            .imageSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
            .imageOffset = StoreOrigins[i], .imageExtent = {StoreSide, StoreSide, 1},
        };
    }
    cb.copyImageToBuffer(image, vk::ImageLayout::eGeneral, readback, regions);
}

float Index(const char* text) {
    return text && (std::strcmp(text, "1") == 0 || std::strcmp(text, "1.0") == 0) ? 1.f : 1.5f;
}
float Ior() {
#if __has_include("bbport_live_knobs.h")
    static BbLiveKnobs::Knob<float> knob{"BB_GLASS_CAUSTICS_IOR", Index};
    return knob.Get();
#else
    static const float value = Index(std::getenv("BB_GLASS_CAUSTICS_IOR"));
    return value;
#endif
}

bool NormalFormat(vk::Format f) {
    return f == vk::Format::eR8G8B8A8Unorm || f == vk::Format::eB8G8R8A8Unorm ||
           f == vk::Format::eA8B8G8R8UnormPack32;
}
} // namespace

struct Pass::MotionProof : StoreReadback {
    static constexpr std::array<std::array<u32,2>,2> Sides{{{40,20},{12,12}}};
    static constexpr std::array<u32,2> Offsets{0,6400};
    static constexpr u32 ImageBytes=7552, NativeBytes=15240;
    static_assert(2*ImageBytes+sizeof(StoreSetup)+2*sizeof(u32)==NativeBytes);
    BottleMotion::Mark mark{};
    Push push{};
    u64 generation{}, color_uid{}, depth_uid{}, tick{};
    vk::Image color{},depth{};
    vk::ImageView color_view{},depth_view{};
    vk::ImageAspectFlags depth_aspects{};
    std::array<vk::Offset3D,2> origins{}, anchors{};

    bool Regions(const Push& args, bool have_prior, std::array<float,2> prior) {
        const std::array world{BottleMotion::Receiver,BottleMotion::Opaque};
        for (u32 i=0;i<world.size();++i) {
            std::array<float,2> xy{};
            if (!FootprintProjection(args,world[i],xy)) return false;
            const s32 x=s32(std::floor(xy[0])),y=s32(std::floor(xy[1]));
            const s32 old_x=i==0&&have_prior?s32(std::floor(prior[0])):x;
            const s32 old_y=i==0&&have_prior?s32(std::floor(prior[1])):y;
            const auto [w,h]=Sides[i];
            const s32 x0=(x+old_x-s32(w))/2,y0=(y+old_y-s32(h))/2;
            const s32 margin=i==0?7:4;
            if (x0<0 || y0<0 || u32(x0)+w>args.size[0] || u32(y0)+h>args.size[1] ||
                std::min(x,old_x)-margin<x0 || std::max(x,old_x)+margin>=x0+s32(w) ||
                std::min(y,old_y)-margin<y0 || std::max(y,old_y)+margin>=y0+s32(h)) return false;
            origins[i]={x0,y0,0};
            anchors[i]={x,y,0};
        }
        return true;
    }

    void CopyColor(vk::CommandBuffer cb, bool after) const {
        std::array<vk::BufferImageCopy,2> regions{};
        for (u32 i=0;i<regions.size();++i) {
            regions[i]={.bufferOffset=Offsets[i]+(after?ImageBytes:0),
                        .imageSubresource={vk::ImageAspectFlagBits::eColor,0,0,1},
                        .imageOffset=origins[i],.imageExtent={Sides[i][0],Sides[i][1],1}};
        }
        cb.copyImageToBuffer(color,vk::ImageLayout::eGeneral,buffer,regions);
    }

    void Before(vk::CommandBuffer cb) const {
        StoreImageBarrier(cb,color,All,Mem,StoreTransfer,StoreTransferRead);
        CopyColor(cb,false);
        StoreImageBarrier(cb,color,StoreTransfer,StoreTransferRead,Compute,ReadWrite);
    }

    void After(vk::CommandBuffer cb,vk::Buffer scratch) const {
        StoreImageBarrier(cb,color,Compute,Write,StoreTransfer,StoreTransferRead);
        CopyColor(cb,true);
        EffectPass::MemoryBarrier(cb,Compute,Write,StoreTransfer,StoreTransferRead);
        cb.copyBuffer(scratch,buffer,vk::BufferCopy{offsetof(Data,setup),2*ImageBytes,sizeof(StoreSetup)});
        StoreImageBarrier(cb,color,StoreTransfer,StoreTransferRead,All,Mem);
        vk::ImageMemoryBarrier2 b{
            .srcStageMask=All,.srcAccessMask=Mem,.dstStageMask=StoreTransfer,.dstAccessMask=StoreTransferRead,
            .oldLayout=vk::ImageLayout::eGeneral,.newLayout=vk::ImageLayout::eGeneral,
            .srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,
            .image=depth,.subresourceRange={depth_aspects,0,1,0,1},
        };
        cb.pipelineBarrier2({.imageMemoryBarrierCount=1,.pImageMemoryBarriers=&b});
        std::array<vk::BufferImageCopy,2> taps{};
        for (u32 i=0;i<2;++i) {
            taps[i]={.bufferOffset=2*ImageBytes+sizeof(StoreSetup)+i*sizeof(u32),
                     .imageSubresource={vk::ImageAspectFlagBits::eDepth,0,0,1},
                     .imageOffset=anchors[i],.imageExtent={1,1,1}};
        }
        cb.copyImageToBuffer(depth,vk::ImageLayout::eGeneral,buffer,taps);
        b.srcStageMask=StoreTransfer;b.srcAccessMask=StoreTransferRead;b.dstStageMask=All;b.dstAccessMask=Mem;
        const vk::MemoryBarrier2 to_host{.srcStageMask=StoreTransfer,.srcAccessMask=StoreTransferWrite,
            .dstStageMask=vk::PipelineStageFlagBits2::eHost,.dstAccessMask=vk::AccessFlagBits2::eHostRead};
        cb.pipelineBarrier2({.memoryBarrierCount=1,.pMemoryBarriers=&to_host,
                             .imageMemoryBarrierCount=1,.pImageMemoryBarriers=&b});
    }

    void Report() const {
        using BottleMotion::P;
        if (vmaInvalidateAllocation(allocator,allocation,0,NativeBytes)!=VK_SUCCESS) {
            std::printf("[bottle-motion-t198] event=depth-store-refused id=%u why=host-invalidate\n",u32(mark.id));
            return;
        }
        StoreSetup setup{};
        std::memcpy(&setup,mapped+2*ImageBytes,sizeof(setup));
        std::printf("[bottle-motion-t198] event=setup run=%u id=%u scene=%llu tick=%llu proxy=%llu ordinal=%u "
                    "color_uid=%llu depth_uid=%llu color_view=%llx depth_view=%llx lamp=(%.9g,%.9g,%.9g,%.9g) "
                    "rgb=(%.9g,%.9g,%.9g) groups=(%u,%u,%u)/(%u,%u,%u) bounds=(%.0f,%.0f,%.0f,%.0f)\n",
                    u32(mark.run),u32(mark.id),P(mark.scene),P(tick),P(generation),push.ordinal,
                    P(color_uid),P(depth_uid),P(std::bit_cast<u64>(VkImageView(color_view))),
                    P(std::bit_cast<u64>(VkImageView(depth_view))),
                    setup.source_radius[0],setup.source_radius[1],setup.source_radius[2],setup.source_radius[3],
                    setup.color_distance[0],setup.color_distance[1],setup.color_distance[2],
                    setup.commands[0],setup.commands[1],setup.commands[2],
                    setup.commands[4],setup.commands[5],setup.commands[6],
                    setup.bounds[0],setup.bounds[1],setup.bounds[2],setup.bounds[3]);
        bool valid=FootprintFinite(setup.source_radius)&&FootprintFinite(setup.color_distance)&&
            FootprintFinite(setup.bounds)&&setup.center_active[3]>0&&setup.commands[0]==16&&
            setup.commands[4]&&setup.commands[5]&&setup.commands[6]==1;
        for (u32 i=0;i<2;++i) {
            u32 depth_word{};
            std::memcpy(&depth_word,mapped+2*ImageBytes+sizeof(StoreSetup)+i*sizeof(u32),sizeof(u32));
            const float d=std::bit_cast<float>(depth_word);
            valid &= std::isfinite(d)&&d>0&&d<1;
            std::printf("[bottle-motion-t198] event=roi id=%u roi=%u x=%d y=%d width=%u height=%u tap=%d/%d depth=%08x\n",
                        u32(mark.id),i,origins[i].x,origins[i].y,Sides[i][0],Sides[i][1],anchors[i].x,anchors[i].y,depth_word);
            for (u32 row=0;row<Sides[i][1];++row) {
                std::array<char,34*40+1> raw{};
                for (u32 col=0;col<Sides[i][0];++col) {
                    const auto off=Offsets[i]+(row*Sides[i][0]+col)*sizeof(StoreTexel);
                    StoreTexel a{},b{};
                    std::memcpy(&a,mapped+off,sizeof(a));std::memcpy(&b,mapped+off+ImageBytes,sizeof(b));
                    valid &= a[3]==b[3];
                    for (u32 c=0;c<4;++c) valid &= (a[c]&0x7c00)!=0x7c00 && (b[c]&0x7c00)!=0x7c00;
                    std::snprintf(raw.data()+34*col,35,"%04x%04x%04x%04x/%04x%04x%04x%04x ",
                        u32(a[0]),u32(a[1]),u32(a[2]),u32(a[3]),u32(b[0]),u32(b[1]),u32(b[2]),u32(b[3]));
                }
                std::printf("[bottle-motion-t198] event=words id=%u roi=%u y=%u rgba16f=%s\n",u32(mark.id),i,row,raw.data());
            }
        }
        std::printf("[bottle-motion-t198] event=depth-store-completed run=%u id=%u valid=%u bytes=%u\n",
                    u32(mark.run),u32(mark.id),u32(valid),NativeBytes);
    }
};

#ifdef BB_TEST_BOTTLE_CUT_SOURCE
namespace {
CutSource::MasterHistory& MasterHistory() {
    static CutSource::MasterHistory history;
    return history;
}

template <typename Handle>
auto HandleWord(Handle handle) {
    static_assert(sizeof(Handle) == sizeof(u64));
    return BottleMotion::P(std::bit_cast<u64>(handle));
}

void ReportCutBacking(const char* boundary, const char* role, const CutSource::Opportunity& o,
                      const CutSource::Backing& b) {
    using BottleMotion::P;
    std::printf("[bottle-cut-source] event=backing request=%u scene=%llu app=%llu boundary=%s role=%s "
                "id=%u uid=%llu generation=%llu parent_write=%llu guest=%llx/%llx parent=%llx proxy=%llx "
                "view=%llx size=%ux%ux%u aspect=%x mip=%u/%u layer=%u/%u format=%d layout=%d "
                "usage=%x stages=%llx access=%llx\n",
                o.scene.request, P(o.scene.scene), P(o.sequence), boundary, role, b.id, P(b.uid),
                P(b.generation), P(b.parent_write), P(b.guest_begin), P(b.guest_end),
                HandleWord(b.parent), HandleWord(b.proxy), HandleWord(b.view),
                b.extent.width, b.extent.height, b.extent.depth, u32(VkImageAspectFlags(b.range.aspectMask)),
                b.range.baseMipLevel, b.range.levelCount, b.range.baseArrayLayer, b.range.layerCount,
                int(b.format), int(b.layout), u32(VkImageUsageFlags(b.usage)),
                P(VkPipelineStageFlags2(b.stages)), P(VkAccessFlags2(b.access)));
}

struct CutPhaseNotice {
    u32 request{};
    u64 scene{}, sequence{}, tick{};
};
} // namespace

u32 CutSource::Run() {
    static const u32 run = [] {
        if (const char* env = std::getenv("BB_BOTTLE_CUT_SOURCE")) {
            u32 value{};
            if (BottleMotion::Number(env, value)) return value;
        }
        return 0u;
    }();
    return run;
}

void CutSource::ReportOpportunity(const Opportunity& o) {
    if (!Run() || Run() != o.scene.request) return;
    using BottleMotion::P;
    std::printf("[bottle-cut-source] event=opportunity request=%u scene=%llu load=%llu rt=%llu object=%llu "
                "generation=%llu primary_pass=%llu timeline=%llx tick=%llu draw=%llu app=%llu "
                "earlier_phase2=%llu branch=%u guard_read=%llu epoch=%llu effective_read=%llu "
                "master=%u outcome=%u\n",
                o.scene.request, P(o.scene.scene), P(o.scene.load), P(o.scene.rt_frame),
                P(o.scene.object_frame), P(o.scene.target_generation), P(o.scene.primary_pass),
                HandleWord(o.order.timeline), P(o.order.tick), P(o.order.draw), P(o.sequence),
                P(o.earlier_phase2), u32(o.guard.branch), P(o.guard.read.read),
                P(o.effective.epoch), P(o.effective.read), u32(o.effective.on), u32(o.outcome));
    if (o.guard.branch == Guard::Branch::NoPassObject) {
        const auto& g = o.gbuffer;
        std::printf("[bottle-cut-source] event=cold-guard request=%u scene=%llu app=%llu "
                    "gbuffer_scene=%llu gbuffer_tick=%llu gbuffer_draw=%llu gbuffer_epoch=%llu "
                    "gbuffer_read=%llu gbuffer_on=%u latest_epoch=%llu latest_read=%llu latest_on=%u\n",
                    o.scene.request, P(o.scene.scene), P(o.sequence), P(g.scene.scene), P(g.order.tick),
                    P(g.order.draw), P(g.master.epoch), P(g.master.read), u32(g.master.on),
                    P(o.latest.epoch), P(o.latest.read), u32(o.latest.on));
    }
    ReportCutBacking("opportunity", "color", o, o.color);
    ReportCutBacking("opportunity", "depth", o, o.depth);
    for (u32 i = 0; i < 3; ++i) {
        const auto* row = o.camera.view.data() + 4 * i;
        std::printf("[bottle-cut-source] event=view request=%u scene=%llu app=%llu row=%u "
                    "values=%.9g/%.9g/%.9g/%.9g\n",
                    o.scene.request, P(o.scene.scene), P(o.sequence), i, row[0], row[1], row[2], row[3]);
    }
    const auto& p = o.camera.projection;
    const auto& j = o.camera.jitter;
    std::printf("[bottle-cut-source] event=projection request=%u scene=%llu app=%llu "
                "projection=%.9g/%.9g/%.9g/%.9g jitter=%.9g/%.9g\n",
                o.scene.request, P(o.scene.scene), P(o.sequence), p[0], p[1], p[2], p[3], j[0], j[1]);
}

CutSource::Backing ObserveCutBacking(const SceneTargets& targets, VideoCore::ImageId id,
                                     const VideoCore::Image& parent, vk::ImageView view,
                                     vk::PipelineStageFlags2 stages, vk::AccessFlags2 access) {
    if (!id || !view || !parent.backing || parent.info.num_samples != 1 || parent.backing->num_samples != 1) {
        return {};
    }
    const auto proxy = targets.InspectSewerProxy(id, parent.image_uid, view);
    if (!proxy.valid || !proxy.target.image) return {};
    const auto aspect = parent.info.props.is_depth ? vk::ImageAspectFlagBits::eDepth
                                                   : vk::ImageAspectFlagBits::eColor;
    if (!(proxy.aspects & aspect)) return {};
    return {.id = id.index, .uid = parent.image_uid, .generation = targets.Generation(),
            .parent_write = parent.write_seq, .guest_begin = parent.guest_begin, .guest_end = parent.guest_end,
            .parent = parent.GetImage(), .proxy = proxy.target.image, .view = proxy.target.view,
            .extent = proxy.extent, .format = proxy.format, .range = {aspect, 0, 1, 0, 1},
            .layout = proxy.target.layout, .usage = proxy.target.usage, .stages = stages, .access = access};
}

struct Pass::CutProof : MotionProof {
    CutPhaseNotice stamp{};

    bool Regions(const Push& args) {
        if (!MotionProof::Regions(args, false, {})) return false;
        const bool overlap_x = origins[0].x < origins[1].x + s32(Sides[1][0]) &&
                               origins[1].x < origins[0].x + s32(Sides[0][0]);
        const bool overlap_y = origins[0].y < origins[1].y + s32(Sides[1][1]) &&
                               origins[1].y < origins[0].y + s32(Sides[0][1]);
        return !overlap_x || !overlap_y;
    }

    void Report() const {
        using BottleMotion::P;
        if (vmaInvalidateAllocation(allocator, allocation, 0, NativeBytes) != VK_SUCCESS) {
            std::printf("[bottle-cut-source] event=store-refused request=%u scene=%llu app=%llu why=host-invalidate\n",
                        stamp.request, P(stamp.scene), P(stamp.sequence));
            return;
        }
        StoreSetup setup{};
        std::memcpy(&setup, mapped + 2 * ImageBytes, sizeof(setup));
        CutSource::StoreEvidence evidence{.groups = {setup.commands[4], setup.commands[5], setup.commands[6]}};
        std::printf("[bottle-cut-source] event=setup request=%u scene=%llu app=%llu "
                    "groups1=%u/%u/%u groups2=%u/%u/%u lamp=%.9g/%.9g/%.9g/%.9g rgb=%.9g/%.9g/%.9g "
                    "bounds=%.9g/%.9g/%.9g/%.9g active=%.9g\n",
                    stamp.request, P(stamp.scene), P(stamp.sequence),
                    setup.commands[0], setup.commands[1], setup.commands[2],
                    evidence.groups[0], evidence.groups[1], evidence.groups[2],
                    setup.source_radius[0], setup.source_radius[1], setup.source_radius[2],
                    setup.source_radius[3], setup.color_distance[0], setup.color_distance[1],
                    setup.color_distance[2], setup.bounds[0], setup.bounds[1], setup.bounds[2],
                    setup.bounds[3], setup.center_active[3]);
        for (u32 i = 0; i < Sides.size(); ++i) {
            u32 depth_word{};
            std::memcpy(&depth_word, mapped + 2 * ImageBytes + sizeof(setup) + i * sizeof(u32), sizeof(u32));
            const float d = std::bit_cast<float>(depth_word);
            evidence.valid &= std::isfinite(d) && d > 0.f && d < 1.f;
            const auto [width, height] = Sides[i];
            std::printf("[bottle-cut-source] event=roi request=%u scene=%llu app=%llu roi=%u "
                        "x=%d y=%d width=%u height=%u tap=%d/%d depth=%08x\n",
                        stamp.request, P(stamp.scene), P(stamp.sequence), i, origins[i].x, origins[i].y,
                        width, height, anchors[i].x, anchors[i].y, depth_word);
            for (u32 row = 0; row < height; ++row) {
                std::array<char, 34 * Sides[0][0] + 1> words{};
                for (u32 col = 0; col < width; ++col) {
                    const auto offset = Offsets[i] + (row * width + col) * sizeof(StoreTexel);
                    StoreTexel before{}, after{};
                    std::memcpy(&before, mapped + offset, sizeof(before));
                    std::memcpy(&after, mapped + offset + ImageBytes, sizeof(after));
                    evidence.Add(i == 1, before, after);
                    std::snprintf(words.data() + 34 * col, 35, "%04x%04x%04x%04x/%04x%04x%04x%04x ",
                                  u32(before[0]), u32(before[1]), u32(before[2]), u32(before[3]),
                                  u32(after[0]), u32(after[1]), u32(after[2]), u32(after[3]));
                }
                std::printf("[bottle-cut-source] event=words request=%u scene=%llu app=%llu roi=%u y=%u rgba16f=%s\n",
                            stamp.request, P(stamp.scene), P(stamp.sequence), i, row, words.data());
            }
        }
        if (evidence.groups[0] && evidence.groups[1] && evidence.groups[2]) {
            evidence.valid &= FootprintFinite(setup.center_active) && setup.center_active[3] > 0.f &&
                              FootprintFinite(setup.source_radius) && FootprintFinite(setup.color_distance) &&
                              FootprintFinite(setup.bounds) && setup.commands[0] == 16;
        }
        std::printf("[bottle-cut-source] event=store-fenced request=%u scene=%llu app=%llu tick=%llu "
                    "verdict=%u receiver=%u opaque=%u alpha=%u bytes=%u\n",
                    stamp.request, P(stamp.scene), P(stamp.sequence), P(stamp.tick), u32(evidence.Verdict()),
                    evidence.receiver_changed, evidence.opaque_changed, evidence.alpha_changed, NativeBytes);
    }
};
#endif


#ifdef BB_TEST_BOTTLE_CUT_SOURCE
static bool ReadOrdinaryMaster() {
#else
bool On() {
#endif
#if __has_include("bbport_live_knobs.h")
    static BbLiveKnobs::Knob<bool> knob{"BB_GLASS_CAUSTICS", Enabled};
    return knob.Get();
#else
    static const bool on = Enabled(std::getenv("BB_GLASS_CAUSTICS"));
    return on;
#endif
}

#ifdef BB_TEST_BOTTLE_CUT_SOURCE
CutSource::MasterRead ReadCutMaster() {
    if (CutSource::Run()) return MasterHistory().Read(ReadOrdinaryMaster);
    return {.on = ReadOrdinaryMaster()};
}

CutSource::MasterRead LatestCutMaster() {
    return CutSource::Run() ? MasterHistory().Latest() : CutSource::MasterRead{};
}

bool On() {
    return ReadCutMaster().on;
}
#endif

bool LogNow() {
    static const bool on = Enabled(std::getenv("BB_GLASS_CAUSTICS_LOG"));
    return on;
}

Pass::Pass(const Instance& instance_, Scheduler& scheduler_, VideoCore::TextureCache& textures_,
           Runtime& runtime_, SceneTargets& targets_, CameraMotion& camera_, PointShadow& shadow_, RtShadow& rt_)
    : instance{instance_}, scheduler{scheduler_}, textures{textures_}, runtime{runtime_},
      targets{targets_}, camera{camera_}, point_shadow{shadow_}, rt{rt_} {}

Pass::~Pass() {
    const auto device = instance.GetDevice();
    for (const auto& item : views) {
        if (item.view) {
            device.destroyImageView(item.view);
        }
    }
    if (data) {
        vmaDestroyBuffer(instance.GetAllocator(), data, allocation);
    }
}

bool Pass::Make() {
    if (data || failed) {
        return bool(data);
    }
    failed = true;
    using enum vk::DescriptorType;
    if (!EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) ||
        !EffectPass::Create(instance, descriptors, layout, pipeline,
                            {eAccelerationStructureKHR, eStorageBuffer, eStorageBuffer, eStorageImage,
                             eSampledImage, eSampledImage, eSampledImage},
                            sizeof(Push), BOTTLE_CAUSTIC_COMP, "Bottle caustics")) {
        return false;
    }
    const VkBufferCreateInfo ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = sizeof(Data),
        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT |
                 VK_BUFFER_USAGE_INDIRECT_BUFFER_BIT |
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
                  (CutSource::Run() ? VkBufferUsageFlags{VK_BUFFER_USAGE_TRANSFER_SRC_BIT} : 0u) |
#endif
                  ((StoreProofEnabled() || FootprintEnabled() || BottleMotion::Run()) ? VkBufferUsageFlags{VK_BUFFER_USAGE_TRANSFER_SRC_BIT} : 0u),
    };
    const VmaAllocationCreateInfo ai{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    VkBuffer raw{};
    if (vmaCreateBuffer(instance.GetAllocator(), &ci, &ai, &raw, &allocation, nullptr) != VK_SUCCESS) {
        return false;
    }
    data = raw;
    if (BottleMotion::Run()) {
        for (auto& slot : motion_slots) {
            auto made = std::make_shared<MotionProof>();
            made->allocator = instance.GetAllocator();
            if (made->Allocate(MotionProof::NativeBytes)) slot = std::move(made);
        }
    }
    failed = false;
    return true;
}

void Pass::OnTargets(VideoCore::ImageId depth, VideoCore::ImageId normal, VideoCore::ImageId albedo) {
    const std::array input{depth, normal, albedo};
    const u64 frame = rt.WindowDiagnosticFrame();
    if (frame == captured_frame && captured == input) {
        return;
    }
    captured_frame = frame;
    lamps.Clear();
    captured = input;
    armed = !failed && !camera.PreviewFrame();
    uids = {};
    for (u32 i = 0; armed && i < captured.size(); ++i) {
        const auto* image = captured[i] ? textures.TryGetImage(captured[i], 0) : nullptr;
        if (image) {
            uids[i] = image->image_uid;
        } else {
            armed = false;
        }
    }
    rt.ResetBottlePass(armed ? uids : std::array<u64, 3>{});
}

bool Pass::Capturing(VideoCore::ImageId depth) const noexcept {
    return armed && depth == captured[0] && captured_frame == rt.WindowDiagnosticFrame();
}

vk::ImageView Pass::View(const VideoCore::Image& image, vk::ImageAspectFlagBits aspect) {
    auto* oldest = &views.front();
    for (auto& item : views) {
        if (item.view && item.image == image.GetImage() && item.uid == image.image_uid && item.aspect == aspect) {
            item.use = ++uses;
            return item.view;
        }
        if (item.use < oldest->use) {
            oldest = &item;
        }
    }
    const auto device = instance.GetDevice();
    if (oldest->view) {
        scheduler.DeferOperation([device, view = oldest->view] { device.destroyImageView(view); });
    }
    const auto [status, view] = device.createImageView({
        .image = image.GetImage(),
        .viewType = vk::ImageViewType::e2D,
        .format = image.info.pixel_format,
        .subresourceRange = {aspect, 0, 1, 0, 1},
    });
    *oldest = {image.GetImage(), image.image_uid, aspect,
               status == vk::Result::eSuccess ? view : vk::ImageView{}, ++uses};
    return oldest->view;
}

#ifdef BB_TEST_BOTTLE_CUT_SOURCE
void Pass::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id, std::array<float, 2> jitter,
                 CutSource::Opportunity* cut_opportunity
#if defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
                 , std::shared_ptr<BottleRawApply180::Receipt> raw_phase
#endif
                 ) {
#else
void Pass::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id, std::array<float, 2> jitter) {
#endif
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
#define BB_BOTTLE_RAW_APPLY_REFUSE(stage) do { if (raw_phase) raw_phase->Refuse(stage); } while (false)
#else
#define BB_BOTTLE_RAW_APPLY_REFUSE(stage) ((void)0)
#endif
    if (!Capturing(depth_id)) {
        BB_BOTTLE_RAW_APPLY_REFUSE("not-capturing");
        return;
    }
    armed = false;
    if (!color_id || lamps.Empty() || !rt.BottleObserved() || camera.PreviewFrame() ||
        camera.Depth() != depth_id) {
        BB_BOTTLE_RAW_APPLY_REFUSE("original-color-camera-light");
        return;
    }
    const auto matrices = camera.PassMatrices();
    if (!matrices.valid || !std::isfinite(jitter[0]) || !std::isfinite(jitter[1]) ||
        std::abs(jitter[0]) > 1.f || std::abs(jitter[1]) > 1.f) {
        BB_BOTTLE_RAW_APPLY_REFUSE("invalid-camera-or-jitter");
        return;
    }
    auto* color = textures.TryGetImage(color_id, 0);
    auto* depth = textures.TryGetImage(depth_id, uids[0]);
    auto* normal = textures.TryGetImage(captured[1], uids[1]);
    auto* albedo = textures.TryGetImage(captured[2], uids[2]);
    if (!color || !depth || !normal || !albedo || !NormalFormat(normal->info.pixel_format) ||
        color->info.pixel_format != vk::Format::eR16G16B16A16Sfloat ||
        (!NormalFormat(albedo->info.pixel_format) && albedo->info.pixel_format != vk::Format::eR8G8B8A8Srgb &&
         albedo->info.pixel_format != vk::Format::eB8G8R8A8Srgb)) {
        BB_BOTTLE_RAW_APPLY_REFUSE("resource-or-format");
        return;
    }
    std::vector<Lamp> selected;
    selected.reserve(LampLimit);
    for (const auto& light : lamps.Lights()) {
        if (!LampFog::Readable(light)) {
            continue;
        }
        // Refuse an oversubscribed light list; arbitrary first-N would be camera-order dependent.
        if (selected.size() == LampLimit) {
            BB_BOTTLE_RAW_APPLY_REFUSE("light-cap");
            return;
        }
        selected.push_back({{std::bit_cast<float>(light[0]), std::bit_cast<float>(light[1]),
                              std::bit_cast<float>(light[2]), std::bit_cast<float>(light[3])},
                             {std::bit_cast<float>(light[4]), std::bit_cast<float>(light[5]),
                              std::bit_cast<float>(light[6]), 0.f}});
    }
    if (selected.empty() || !Make()) {
        BB_BOTTLE_RAW_APPLY_REFUSE(selected.empty() ? "no-readable-light" : "make");
        return;
    }
    if (point_shadow.Apart()) {
        point_shadow.EndApart(jitter[0] != 0.f || jitter[1] != 0.f);
    }
    scheduler.EndRendering();
    if (!rt.PrepareScene()) {
        BB_BOTTLE_RAW_APPLY_REFUSE("prepare-scene");
        return;
    }
    const auto scene = rt.BottleScene(matrices.view);
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    if (raw_phase) raw_phase->ObserveTopology(bool(scene.tlas), bool(scene.corners), scene.ordinal);
#endif
    if (!scene.tlas || !scene.corners) {
        BB_BOTTLE_RAW_APPLY_REFUSE("scene-geometry");
        return;
    }
    const SceneUseScope use{"bottle caustics"};
    const bool reduced = targets.Reduced();
    u32 width = color->info.size.width;
    u32 height = color->info.size.height;
    std::array<vk::ImageView, 4> image_views{};
    SceneTargets::Target writable{};
    SceneTargets::Target bound_depth{};
    if (reduced) {
        if (!targets.EligibleScene(*color) || !targets.EligibleScene(*normal) || !targets.EligibleScene(*albedo)) {
            BB_BOTTLE_RAW_APPLY_REFUSE("scene-target-eligibility");
            return;
        }
        width = targets.Size().width;
        height = targets.Size().height;
        VideoCore::ImageViewInfo info{};
        info.format = color->info.pixel_format;
        writable = targets.Read(color_id, info, Compute, ReadWrite);
        if (!(writable.usage & vk::ImageUsageFlagBits::eStorage)) {
            BB_BOTTLE_RAW_APPLY_REFUSE("color-storage-usage");
            return;
        }
        image_views[0] = writable.view;
        for (u32 i = 0; i < captured.size(); ++i) {
            const std::array<const VideoCore::Image*, 3> images{depth, normal, albedo};
            info.format = images[i]->info.pixel_format;
            const auto input = targets.ReadNext(captured[i], info);
            image_views[i + 1] = input.view;
            if (i == 0) {
                bound_depth = input;
            }
        }
    } else {
        if (!(color->usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            BB_BOTTLE_RAW_APPLY_REFUSE("color-storage-usage");
            return;
        }
        const auto render = camera.RenderSize();
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
        image_views = {View(*color, vk::ImageAspectFlagBits::eColor), View(*depth, vk::ImageAspectFlagBits::eDepth),
                       View(*normal, vk::ImageAspectFlagBits::eColor), View(*albedo, vk::ImageAspectFlagBits::eColor)};
        runtime.Transit(color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        for (auto* image : {depth, normal, albedo}) {
            runtime.Transit(image, vk::ImageLayout::eGeneral, Compute, Read);
        }
        runtime.FlushBarriers();
    }
    if (!width || !height || !std::ranges::all_of(image_views, [](auto view) { return bool(view); })) {
        BB_BOTTLE_RAW_APPLY_REFUSE("extent-or-view");
        return;
    }

    const Push args{matrices.view, matrices.proj, jitter, {width, height}, scene.ordinal,
                    u32(selected.size()), 0, Ior(), PointShadow::EmitterClearance()};
    std::unique_ptr<StoreProof> proof;
#undef BB_BOTTLE_RAW_APPLY_REFUSE
    std::unique_ptr<FootprintProof> footprint;
    if (ClaimStoreProof()) {
        const auto image = reduced ? writable.image : color->GetImage();
        const auto usage = reduced ? writable.usage : color->usage_flags;
        const auto image_layout = reduced ? writable.layout : vk::ImageLayout::eGeneral;
        const auto extent = reduced ? targets.ProxySize(*color) :
            SceneResolution::Size{color->info.size.width, color->info.size.height};
        if (width != StoreWidth || height != StoreHeight || args.ior != 1.5f ||
            extent.width < width || extent.height < height ||
            !image || !(usage & vk::ImageUsageFlagBits::eTransferSrc) ||
            color->info.num_samples != 1 || image_layout != vk::ImageLayout::eGeneral) {
            std::printf("[bottle-store-t176] event=refused why=fixture-or-image width=%u height=%u ior=%.3f "
                        "domain=%s transfer_source=%d samples=%u layout=%d\n",
                        width, height, args.ior, reduced ? "proxy" : "native",
                        bool(usage & vk::ImageUsageFlagBits::eTransferSrc), color->info.num_samples,
                        int(image_layout));
        } else {
            proof = std::make_unique<StoreProof>();
            proof->allocator = instance.GetAllocator();
            if (!proof->Allocate(StoreBytes)) {
                std::printf("[bottle-store-t176] event=refused why=host-allocation\n");
                proof.reset();
            } else {
                proof->image = image;
                proof->frame = captured_frame;
                proof->tick = scheduler.CurrentTick();
                proof->uid = color->image_uid;
                proof->generation = reduced ? targets.Generation() : 0;
                proof->image_id = color_id.index;
                proof->width = width;
                proof->height = height;
                proof->image_width = extent.width;
                proof->image_height = extent.height;
                proof->ordinal = args.ordinal;
                proof->lamps = args.lamp_count;
                proof->jitter = args.jitter;
                proof->ior = args.ior;
                proof->clearance = args.emitter_clearance;
                proof->proxy = reduced;
            }
        }
    }
    if (!proof && ClaimFootprint()) {
        if (!FootprintFinite(args.view) || !FootprintFinite(args.proj) ||
            args.proj[0] == 0.f || args.proj[1] == 0.f) {
            std::printf("[bottle-footprint-t185] event=refused why=invalid-transform\n");
        } else {
            footprint = std::make_unique<FootprintProof>();
            footprint->allocator = instance.GetAllocator();
            if (!footprint->Allocate(FootprintBytes)) {
                std::printf("[bottle-footprint-t185] event=refused why=host-allocation\n");
                footprint.reset();
            } else {
                footprint->args = args;
                footprint->ids = {color_id.index, captured[0].index, captured[1].index, captured[2].index};
                footprint->uids = {color->image_uid, uids[0], uids[1], uids[2]};
                for (u32 i = 0; i < image_views.size(); ++i) {
                    footprint->views[i] = std::bit_cast<u64>(static_cast<VkImageView>(image_views[i]));
                }
                footprint->frame = captured_frame;
                footprint->tick = scheduler.CurrentTick();
                footprint->draw_timeline = std::bit_cast<u64>(
                    static_cast<VkSemaphore>(scheduler.GetWorkSemaphore()->Handle()));
                footprint->qpc_ns = WorkflowPresent::Now();
                footprint->app_frames_at_record = BbStats::frame_number.load(std::memory_order_relaxed);
                footprint->generation = reduced ? targets.Generation() : 0;
                footprint->proxy = reduced;
            }
        }
    }
    std::unique_ptr<DepthTapProof> tap;
    if (const auto request = ClaimDepthTap()) {
        const auto format = depth->backing ? depth->backing->image.image_ci.format : vk::Format::eUndefined;
        const auto bound_view = std::bit_cast<u64>(static_cast<VkImageView>(image_views[1]));
        const auto generation = reduced ? targets.Generation() : 0;
        const auto stamp = [](u64 v) { return static_cast<unsigned long long>(v); };
        const auto reject = [&](const char* why) {
            std::printf("[bottle-depth-t190] event=refused serial=%llu why=%s actual_id=%u actual_uid=%llu "
                        "actual_view=%llx actual_generation=%llu domain=%s extent=%ux%u\n",
                        stamp(request->serial), why, depth_id.index, stamp(depth->image_uid), stamp(bound_view),
                        stamp(generation), reduced ? "proxy" : "native", width, height);
        };
        const auto extent = reduced ? targets.ProxySize(*depth) : SceneResolution::Size{};
        const bool all_inside = std::ranges::all_of(
            std::span(request->pixels).first(request->count),
            [width,height](auto p) { return p[0] < width && p[1] < height; });
        if (!reduced || width != 1920 || height != 1080 || extent.width != width || extent.height != height ||
            args.ior != 1.5f) {
            reject("proxy-fixture-or-extent");
        } else if (request->image_id != depth_id.index || request->uid != depth->image_uid ||
                   request->view != bound_view || request->generation != generation ||
                   bound_depth.view != image_views[1]) {
            reject("depth-source-identity");
        } else if (!bound_depth.image || bound_depth.layout != vk::ImageLayout::eGeneral ||
                   !(bound_depth.usage & vk::ImageUsageFlagBits::eTransferSrc) ||
                   !depth->backing || depth->info.num_samples != 1 || depth->backing->num_samples != 1 ||
                   depth->info.resources != VideoCore::SubresourceExtent{1, 1} ||
                   (format != vk::Format::eD32Sfloat && format != vk::Format::eD32SfloatS8Uint) ||
                   !(depth->aspect_mask & vk::ImageAspectFlagBits::eDepth)) {
            reject("depth-source-format-or-transfer");
        } else if (!all_inside || !FootprintFinite(args.view) || !FootprintFinite(args.proj) ||
                   args.proj[0] == 0.f || args.proj[1] == 0.f) {
            reject("tap-or-transform-invalid");
        } else {
            tap = std::make_unique<DepthTapProof>();
            tap->request = *request;
            tap->allocator = instance.GetAllocator();
            if (!tap->Allocate(tap->Bytes())) {
                reject("host-allocation");
                tap.reset();
            } else {
                tap->args = args;
                tap->image = bound_depth.image;
                tap->barrier_aspects = depth->aspect_mask;
                tap->frame = captured_frame;
                tap->tick = scheduler.CurrentTick();
                tap->timeline = std::bit_cast<u64>(
                    static_cast<VkSemaphore>(scheduler.GetWorkSemaphore()->Handle()));
                tap->qpc_ns = WorkflowPresent::Now();
                tap->app_frames = BbStats::frame_number.load(std::memory_order_relaxed);
            }
        }
    }
    std::shared_ptr<MotionProof> motion;
    if (BottleMotion::Run()) {
        auto& s = BottleMotion::Scene();
        if (s.mark && !s.bad) {
            if (!s.mark.on || s.bottle || proof || footprint || tap) {
                BottleMotion::Refuse(s,"duplicate-or-other-composite-probe");
            } else {
                const auto slot=std::ranges::find_if(motion_slots,[](const auto& p) { return p && p.use_count()==1; });
                const auto w = reduced ? targets.ProxySize(*color) : SceneResolution::Size{};
                const auto h = reduced ? targets.ProxySize(*depth) : SceneResolution::Size{};
                const auto format = depth->backing ? depth->backing->image.image_ci.format : vk::Format::eUndefined;
                if (slot==motion_slots.end()) {
                    BottleMotion::Refuse(s,"motion-readback-slots-busy-or-unavailable");
                } else if (!reduced || !targets.Generation() || width!=1920 || height!=1080 ||
                    args.ior!=1.5f || w.width!=width || w.height!=height || h.width!=width || h.height!=height ||
                    !writable.image || writable.view!=image_views[0] || bound_depth.view!=image_views[1] ||
                    !bound_depth.image || writable.layout!=vk::ImageLayout::eGeneral ||
                    bound_depth.layout!=vk::ImageLayout::eGeneral ||
                    !(writable.usage & vk::ImageUsageFlagBits::eTransferSrc) ||
                    !(bound_depth.usage & vk::ImageUsageFlagBits::eTransferSrc) ||
                    color->info.resources != VideoCore::SubresourceExtent{1,1} ||
                    depth->info.resources != VideoCore::SubresourceExtent{1,1} ||
                    color->info.num_samples!=1 || depth->info.num_samples!=1 ||
                    !color->backing || color->backing->num_samples!=1 ||
                    color->backing->image.image_ci.format!=vk::Format::eR16G16B16A16Sfloat ||
                    !depth->backing || depth->backing->num_samples!=1 ||
                    (format!=vk::Format::eD32Sfloat && format!=vk::Format::eD32SfloatS8Uint) ||
                    !(depth->aspect_mask & vk::ImageAspectFlagBits::eDepth)) {
                    BottleMotion::Refuse(s,"proxy-footprint-source");
                } else if (!(*slot)->Regions(args,s.have_receiver,s.last_receiver)) {
                    BottleMotion::Refuse(s,"roi-union-or-anchor-outside");
                } else if (scheduler.GetWorkSemaphore()->Handle()!=s.mark.timeline) {
                    BottleMotion::Refuse(s,"composite-timeline");
                } else {
                    motion=*slot;
                    motion->mark=s.mark;
                    motion->push=args;
                    motion->color=writable.image;
                    motion->depth=bound_depth.image;
                    motion->color_view=writable.view;
                    motion->depth_view=bound_depth.view;
                    motion->depth_aspects=depth->aspect_mask;
                    motion->generation=targets.Generation();
                    motion->color_uid=color->image_uid;
                    motion->depth_uid=depth->image_uid;
                    motion->tick=scheduler.CurrentTick();
                    s.bottle=true;
                    s.bottle_tick=motion->tick;
                    s.generation=motion->generation;
                    s.color_uid=motion->color_uid;s.depth_uid=motion->depth_uid;
                    s.color_id=color_id.index;s.depth_id=depth_id.index;s.ordinal=args.ordinal;
                    s.color=motion->color;s.depth=motion->depth;
                    s.color_view=motion->color_view;s.depth_view=motion->depth_view;
                    s.view=args.view;s.proj=args.proj;s.jitter=args.jitter;
                    s.have_receiver=FootprintProjection(args,BottleMotion::Receiver,s.last_receiver);
                }
            }
        }
    }
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    std::shared_ptr<CutProof> cut;
    CutPhaseNotice cut_notice{};
    if (cut_opportunity && cut_opportunity->outcome == CutSource::Outcome::OnNoPhase2 &&
        CutSource::Run() && CutSource::Run() == cut_opportunity->scene.request) {
        auto& o = *cut_opportunity;
        const auto tick = scheduler.CurrentTick();
        cut_notice = {o.scene.request, o.scene.scene, o.sequence, tick};
        const auto actual_color = ObserveCutBacking(targets, color_id, *color, image_views[0], Compute, ReadWrite);
        const auto actual_depth = ObserveCutBacking(targets, depth_id, *depth, image_views[1], Compute, Read);
        ReportCutBacking("phase2", "color", o, actual_color);
        ReportCutBacking("phase2", "depth", o, actual_depth);
        const bool joined =
            reduced && o.MatchesPhase(captured_frame, rt.WindowDiagnosticFrame(),
                                      scheduler.GetWorkSemaphore()->Handle(), tick,
                                      {args.view, args.proj, args.jitter}, actual_color, actual_depth) &&
            actual_color.proxy == writable.image && actual_depth.proxy == bound_depth.image &&
            actual_color.view == writable.view && actual_depth.view == bound_depth.view &&
            actual_color.layout == writable.layout && actual_depth.layout == bound_depth.layout &&
            width == actual_color.extent.width && height == actual_color.extent.height && args.ior == 1.5f;
        const char* refusal = nullptr;
        if (!joined) {
            o.outcome = CutSource::Outcome::Phase2Unjoined;
            refusal = "native-scope";
        } else {
            o.outcome = CutSource::Outcome::Phase2Queued;
            if (proof || footprint || tap || BottleMotion::Run()) {
                refusal = "other-composite-probe";
            } else if (!(actual_color.usage & vk::ImageUsageFlagBits::eTransferSrc) ||
                       !(actual_depth.usage & vk::ImageUsageFlagBits::eTransferSrc)) {
                refusal = "no-transfer-src";
            } else {
                const auto slot = std::ranges::find_if(cut_slots, [](const auto& entry) {
                    return !entry || entry.use_count() == 1;
                });
                if (slot == cut_slots.end()) {
                    refusal = "readback-slots-busy";
                } else {
                    if (!*slot) {
                        auto made = std::make_shared<CutProof>();
                        made->allocator = instance.GetAllocator();
                        if (made->Allocate(CutProof::NativeBytes)) *slot = std::move(made);
                    }
                    if (!*slot) {
                        refusal = "host-allocation";
                    } else if (!(*slot)->Regions(args)) {
                        refusal = "roi-or-anchor-outside";
                    } else {
                        cut = *slot;
                        cut->stamp = cut_notice;
                        cut->color = writable.image;
                        cut->depth = bound_depth.image;
                        cut->depth_aspects = depth->aspect_mask;
                    }
                }
            }
        }
        if (refusal) {
            using BottleMotion::P;
            std::printf("[bottle-cut-source] event=store-refused request=%u scene=%llu app=%llu why=%s\n",
                        cut_notice.request, P(cut_notice.scene), P(cut_notice.sequence), refusal);
        }
    }
#endif
    if (LogNow() && !told) {
        told = true;
        std::printf("Bottle caustics: fresh exact guest/BLAS topology, TLAS ordinal %u, %u point records, IOR %.2f\n",
                    args.ordinal, args.lamp_count, double(args.ior));
    }
    EffectPass::Mark(135, "bottle caustics");
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    if (raw_phase) {
        using BottleRawApply180::Bind;
        const auto describe = [&](VideoCore::ImageId id, const VideoCore::Image& image,
                                  SceneTargets::Target selected,
                                  vk::ImageView actual_view, bool depth_input) {
            Bind result{
                .parent = {id.index, image.image_uid, image.GetImage(), image.backing->image.allocation},
                .proxy = reduced ? selected.image : image.GetImage(),
                .view = actual_view, .layout = vk::ImageLayout::eGeneral,
                .parent_write_hint = image.write_seq};
            if (reduced) {
                const auto actual = targets.InspectSewerProxy(id, image.image_uid, actual_view);
                const auto aspect = depth_input ? vk::ImageAspectFlagBits::eDepth : vk::ImageAspectFlagBits::eColor;
                using enum vk::Format;
                const bool format = depth_input ? (actual.format == eD32Sfloat || actual.format == eD32SfloatS8Uint)
                                                : actual.format == eR16G16B16A16Sfloat;
                if (actual.valid && actual.target.image == selected.image &&
                    actual.target.view == selected.view && selected.view == actual_view &&
                    selected.layout == vk::ImageLayout::eGeneral && actual.target.layout == selected.layout &&
                    actual.extent == vk::Extent3D{1920, 1080, 1} && (actual.aspects & aspect) && format) {
                    result.incarnation = actual.incarnation;
                }
            }
            return result;
        };
        raw_phase->Queue({scheduler.GetWorkSemaphore()->Handle(), scheduler.CurrentTick(), captured_frame,
                          rt.WindowDiagnosticFrame(), targets.Generation(), {args.view, args.proj, args.jitter},
                          describe(color_id, *color, writable, image_views[0], false),
                          describe(depth_id, *depth, bound_depth, image_views[1], true),
                          cut_opportunity && cut_opportunity->outcome == CutSource::Outcome::Phase2Queued});
    }
#endif
    scheduler.RecordCrumb(
        {.name = "Bottle caustics"},
        [args, scene, image_views, selected = std::move(selected), buffer = data, pass_pipeline = *pipeline,
         pass_layout = *layout, proof = proof.get(), footprint = footprint.get(),
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
         tap = tap.get(), motion = motion.get(), cut = cut.get(), cut_notice
#if defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
         , raw_phase
#endif
        ](vk::CommandBuffer cb) mutable {
#else
         tap = tap.get(), motion = motion.get()](vk::CommandBuffer cb) mutable {
#endif
            constexpr auto Transfer = vk::PipelineStageFlagBits2::eAllTransfer;
            constexpr auto TransferWrite = vk::AccessFlagBits2::eTransferWrite;
            EffectPass::MemoryBarrier(cb, All, Mem, Transfer | Compute, TransferWrite | ReadWrite);
            cb.updateBuffer(buffer, 0, selected.size() * sizeof(Lamp), selected.data());
            cb.fillBuffer(buffer, offsetof(Data, heads), Buckets * sizeof(u32), 0);
            EffectPass::MemoryBarrier(cb, Transfer, TransferWrite, Compute, ReadWrite);

            const auto info = [](vk::ImageView view) -> vk::DescriptorImageInfo {
                return {.imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
            };
            const std::array images{info(image_views[0]), info(image_views[1]), info(image_views[2]), info(image_views[3])};
            const vk::DescriptorBufferInfo vertices{scene.corners, 0, BottleCorners * 16};
            const vk::DescriptorBufferInfo scratch{buffer, 0, sizeof(Data)};
            const vk::WriteDescriptorSetAccelerationStructureKHR as{
                .accelerationStructureCount = 1, .pAccelerationStructures = &scene.tlas,
            };
            using enum vk::DescriptorType;
            const std::array writes{
                vk::WriteDescriptorSet{.pNext = &as, .dstBinding = 0, .descriptorCount = 1, .descriptorType = eAccelerationStructureKHR},
                vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1, .descriptorType = eStorageBuffer, .pBufferInfo = &vertices},
                vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1, .descriptorType = eStorageBuffer, .pBufferInfo = &scratch},
                vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1, .descriptorType = eStorageImage, .pImageInfo = &images[0]},
                vk::WriteDescriptorSet{.dstBinding = 4, .descriptorCount = 1, .descriptorType = eSampledImage, .pImageInfo = &images[1]},
                vk::WriteDescriptorSet{.dstBinding = 5, .descriptorCount = 1, .descriptorType = eSampledImage, .pImageInfo = &images[2]},
                vk::WriteDescriptorSet{.dstBinding = 6, .descriptorCount = 1, .descriptorType = eSampledImage, .pImageInfo = &images[3]},
            };
            cb.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            cb.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            Push push = args;
            auto phase = [&](u32 value) {
                push.phase = value;
                cb.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            };
            phase(0);
            cb.dispatch(1, 1, 1);
            EffectPass::MemoryBarrier(cb, Compute, Write, Compute | vk::PipelineStageFlagBits2::eDrawIndirect,
                                      ReadWrite | vk::AccessFlagBits2::eIndirectCommandRead);
            phase(1);
            cb.dispatchIndirect(buffer, offsetof(Data, commands));
            EffectPass::MemoryBarrier(cb, Compute, Write, Compute, ReadWrite);
            if (footprint) {
                // Include the transfer that clears heads even for an empty phase-1 dispatch.
                EffectPass::MemoryBarrier(cb, Compute | Transfer, Write | TransferWrite,
                                          StoreTransfer, StoreTransferRead);
                cb.copyBuffer(buffer, footprint->buffer, vk::BufferCopy{FootprintOffset, 0, FootprintBytes});
                EffectPass::MemoryBarrier(cb, StoreTransfer, StoreTransferWrite,
                                          vk::PipelineStageFlagBits2::eHost, vk::AccessFlagBits2::eHostRead);
            }
            phase(2);
            if (motion) motion->Before(cb);
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
            if (cut) cut->Before(cb);
#endif
            if (proof) {
                StoreImageBarrier(cb, proof->image, All, Mem, StoreTransfer, StoreTransferRead);
                StoreCopy(cb, proof->image, proof->buffer, false);
                StoreImageBarrier(cb, proof->image, StoreTransfer, StoreTransferRead, Compute, ReadWrite);
            }
            cb.dispatchIndirect(buffer, offsetof(Data, commands) + sizeof(u32) * 4);
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
            if (raw_phase) raw_phase->Encoded(cb);
#endif
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
            if (cut_notice.request) {
                using BottleMotion::P;
                std::printf("[bottle-cut-source] event=phase2-encoded request=%u scene=%llu app=%llu tick=%llu "
                            "cb=%llx pipeline=%llx scratch=%llx indirect_offset=%zu ordinal=%u lamps=%u "
                            "ior=%.9g tlas=%llx corners=%llx views=%llx/%llx/%llx/%llx\n",
                            cut_notice.request, P(cut_notice.scene), P(cut_notice.sequence), P(cut_notice.tick),
                            HandleWord(cb), HandleWord(pass_pipeline), HandleWord(buffer),
                            offsetof(Data, commands) + sizeof(u32) * 4, push.ordinal, push.lamp_count,
                            push.ior, HandleWord(scene.tlas), HandleWord(scene.corners),
                            HandleWord(image_views[0]), HandleWord(image_views[1]),
                            HandleWord(image_views[2]), HandleWord(image_views[3]));
            }
#endif
            EffectPass::MemoryBarrier(cb, Compute, Write, All, Mem);
            if (tap) {
                tap->Copy(cb);
            }
            if (motion) motion->After(cb,buffer);
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
            if (cut) cut->After(cb, buffer);
#endif
            if (proof) {
                StoreImageBarrier(cb, proof->image, Compute, Write, StoreTransfer, StoreTransferRead);
                StoreCopy(cb, proof->image, proof->buffer, true);
                // Copy the actual lamp selection and indirect groups written by ordinary phase 0.
                cb.copyBuffer(buffer, proof->buffer, vk::BufferCopy{offsetof(Data, setup), StoreImageBytes,
                                                                  sizeof(StoreSetup)});
                StoreImageBarrier(cb, proof->image, StoreTransfer, StoreTransferRead, All, Mem);
                EffectPass::MemoryBarrier(cb, StoreTransfer, StoreTransferWrite,
                                          vk::PipelineStageFlagBits2::eHost, vk::AccessFlagBits2::eHostRead);
            }
        });
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    if (raw_phase) raw_phase->Recorded();
#endif
    if (proof) {
        scheduler.DeferOperation([proof = std::move(proof)] { proof->Report(); }, "bottle HDR store proof");
    }
    if (footprint) {
        scheduler.DeferOperation([proof = std::move(footprint)] { proof->Report(); }, "bottle footprint proof");
    }
    if (tap) {
        scheduler.DeferOperation([tap = std::move(tap)] { tap->Report(); }, "bottle bound depth tap");
    }
    if (motion) {
        scheduler.DeferOperation([motion = std::move(motion)] { motion->Report(); }, "bottle motion proof");
    }
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    if (cut) {
        scheduler.DeferOperation([cut = std::move(cut)] { cut->Report(); }, "bottle cut source proof");
    }
#endif
}
} // namespace Vulkan::BottleCaustic
