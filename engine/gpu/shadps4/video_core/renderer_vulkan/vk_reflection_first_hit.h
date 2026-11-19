// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <memory>
#include <vector>

#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
struct Buffer;
}

namespace Vulkan {
class Instance;
class Runtime;
class Scheduler;
}

namespace Vulkan::ReflectionFirstHit {

inline constexpr u32 PixelLimit = 8;
inline constexpr u32 SceneLimit = 256;
inline constexpr u32 ReceiverTriangles = 8;
inline constexpr u32 InvalidId = ~u32{0};

bool On(); // Startup-only BB_REFLECTION_FIRST_HIT.
bool PlacedOn(); // Also requires BB_REFLECTION_PLACED_FIRST_HIT.

enum class PlacedSource : u32 { Mirror, Fireplace, Wall, Count, None = InvalidId };
inline constexpr u32 PlacedSourceCount = u32(PlacedSource::Count);
inline constexpr u32 PaletteWords = 24;
inline constexpr u32 PaletteBytes = PaletteWords * sizeof(u32);

// One unreduced native camera G-buffer. Copy the same stamp into actual direct submissions.
struct Stamp {
    u64 generation{};
    u64 frame{};
    u64 pass{};
    VideoCore::ImageId depth{};
    VideoCore::ImageId cb0{};
    u64 depth_uid{};
    u64 cb0_uid{};
    vk::Image depth_image{};
    vk::Image cb0_image{};
    std::array<float, 12> view{}; // World to view, three orthonormal rows with translation.
    std::array<float, 4> projection{};
    std::array<float, 2> jitter{}; // Pixel units with the native G-buffer viewport signs.
    std::array<u32, 2> extent{};
    bool valid_native{}; // Caller attests main camera, current viewport, no proxy or preview.
    bool operator==(const Stamp&) const = default;
};

// Stable, placement-specific identity plus one attested ordinary world-BLAS generation.
struct Identity {
    u64 surface{};
    u64 allocation{};
    u64 revision{};
    u64 placement{}; // Verified non-camera vertex inputs and binding placement.
    u32 vs{};
    u32 ps{};
    u32 count{};
    u32 first{};
    std::array<u8, 32> topology_sha256{};
    bool receiver{};
    bool wall_witness{};
    PlacedSource placed = PlacedSource::None;
    bool operator==(const Identity&) const = default;
};

enum class Mode : u32 { Shaded, Planar, Direct };
enum class Arm : u32 { Retained, Current, Count };

struct Pixel {
    u32 x{};
    u32 y{};
    Mode mode{};
    u32 farther{}; // 1 continues 0.1 mm after first t. 2 is the fingerprinted wall-only control.
};

struct Request {
    u64 serial{}; // Positive and monotonically increasing, consumed on acceptance or refusal.
    u32 count{};
    std::array<Pixel, PixelLimit> pixels{};
    std::array<float, 3> receiver_plane_normal{}; // Required for Planar, from the qualified placement.
};

// The only request the held-pass diagnostic may observe or forward.
constexpr bool HeldPassRequest(const Request& request) {
    constexpr std::array<std::array<u32, 2>, 3> points{{{512, 538}, {510, 540}, {514, 536}}};
    if (!request.serial || request.count != points.size()) {
        return false;
    }
    for (u32 i = 0; i < points.size(); ++i) {
        const auto& pixel = request.pixels[i];
        if (pixel.x != points[i][0] || pixel.y != points[i][1] || pixel.mode != Mode::Direct || pixel.farther) {
            return false;
        }
    }
    return true;
}

enum class Outcome : u32 {
    Sampled = 1,
    InvalidDepth,
    OutsideReceiver,
    DepthMismatch,
    InvalidNormal,
    InvalidPlacement,
};

// std430 result ABI. An invalid instance represents a miss. Primitive and geometry are
// Vulkan committed triangle indices. Distance is {t, barycentric u, barycentric v, signed view z}.
struct alignas(16) Hit {
    u32 instance = InvalidId;
    u32 primitive = InvalidId;
    u32 geometry = InvalidId;
    u32 reserved{};
    std::array<float, 4> distance{};
    std::array<float, 4> world{};
};

struct alignas(16) Sample {
    Outcome outcome{};
    u32 x{};
    u32 y{};
    Mode mode{};
    std::array<u32, 4> cb0_bytes{};
    std::array<float, 4> native_point_depth{}; // xyz, raw device depth.
    std::array<float, 4> origin_t{}; // xyz, primary receiver t (0 for Direct).
    std::array<float, 4> direction_depth_delta{}; // xyz, native range minus receiver t.
    Hit receiver{};
    std::array<Hit, u32(Arm::Count)> world{};
    std::array<Hit, u32(Arm::Count)> farther{};
};

struct Member {
    Identity identity{};
    u64 last_submit_frame{};
    bool current{};
    u64 placement_build_cookie{};
    u64 placement_cookie{}; // Actual draw which copied this member's last observed palette.
};

struct SceneReceipt {
    u64 serial{};
    std::vector<Member> members; // Decodes private instanceCustomIndex, in this order.
};

struct Report {
    Stamp stamp{};
    Request request{};
    std::array<SceneReceipt, u32(Arm::Count)> scenes;
    std::array<Sample, PixelLimit> samples{};
    u32 placed_mask{};
};

enum class Status {
    Recorded,
    AlreadyCloned,
    Disabled,
    InvalidPass,
    InvalidSource,
    InvalidRequest,
    AlreadyRequested,
    MissingReceiver,
    MissingScene,
    MissingPlacedFixture,
    InvalidImages,
    CloneLimit,
    NoRoom,
    BusyScene,
    BusyReadback,
    GpuUnavailable,
    StaleReadback,
    InvalidReadback,
    Pending,
    HeldPassObserved,
    HeldPassConsumed,
};
const char* StatusName(Status);

struct Usage {
    vk::DeviceSize bytes{}; // Actual allocation bytes, including deferred frees.
    u32 records{};
    u32 clones_this_frame{};
    vk::DeviceSize cloned_payload_this_frame{};
    u64 expired{};
    u64 pressure_evicted{};
};

// Render producer only. The owning hooks establish source identity and direct-draw attestation.
class Pass {
public:
    Pass(const Instance&, Scheduler&, VideoCore::TextureCache&, Runtime&);
    ~Pass();
    Pass(const Pass&) = delete;
    Pass& operator=(const Pass&) = delete;

    bool BeginPass(const Stamp&);
    void CloseEpoch();

    // Once per actual, qualified direct G-buffer draw. RejectReceiver poisons the pass when
    // an exact-key receiver draw could not be qualified, even if another occurrence qualifies.
    void Submitted(const Stamp&, const Identity&);
    void RejectReceiver(const Stamp&);
    void InvalidateSurface(u64 surface);
    void ObserveSurface(u64 surface, u64 placement);
    void InvalidateAllocation(u64 allocation);
    void InvalidatePlaced(PlacedSource source);

    bool ObservePlaced(const Stamp&, const Identity&, u64 cookie, const VideoCore::Buffer&, u64 offset);
    bool BuildPlaced(const Stamp&, const Identity&, u64 confirmed_cookie);
    bool CurrentPlaced(const Stamp&, const Identity&, u64 confirmed_cookie) const;

    // Call outside rendering, after the real ordinary BLAS build is recorded, before any
    // conflicting refit/destruction. Only pass a revision attested to the confirmed direct draw.
    Status Clone(const Stamp&, const Identity&, vk::AccelerationStructureKHR source,
                 vk::DeviceSize source_creation_size);

    // Call in the matching EffectsBlendedScene after ending any apart pass.
    Status Submit(const Stamp&, const Request&);
    // At frame end, after updating the load epoch. Emits a result only after its fence.
    Status Poll(Report&);
    [[nodiscard]] Usage GetUsage() const;

private:
    class State;
    std::unique_ptr<State> state;
};

} // namespace Vulkan::ReflectionFirstHit
