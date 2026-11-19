// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <functional>

#include "video_core/renderer_vulkan/vk_sewer_motion_observer.h"

namespace Vulkan::SewerPresent {

inline constexpr vk::Extent2D Extent{3840, 2160};
inline constexpr auto Format = vk::Format::eB8G8R8A8Unorm;
inline constexpr auto Sdr = vk::ColorSpaceKHR::eSrgbNonlinear;
inline constexpr u32 Side = 25;
inline constexpr u32 MaxPatches = 7;
inline constexpr u32 PatchBytes = Side * Side * 4;
inline constexpr u32 MaxBytes = MaxPatches * PatchBytes;
static_assert(MaxBytes == 17500);

enum class Role : u8 { Wet0, Wet1, Dry, Vacated0, Vacated1, Opaque0, Opaque1 };

struct Point {
    Role role{};
    vk::Offset2D centre{};
};
struct Regions {
    std::array<Point, MaxPatches> points{};
    u32 count{};

    bool Valid(char checkpoint) const {
        if (count < 5 || count > MaxPatches) return false;
        unsigned mask = 0;
        for (u32 i = 0; i < count; ++i) {
            const auto [role, xy] = points[i];
            if (unsigned(role) >= MaxPatches) return false;
            constexpr s32 radius = Side / 2;
            if (xy.x < radius || xy.y < radius ||
                xy.x >= s32(Extent.width) - radius || xy.y >= s32(Extent.height) - radius) return false;
            const unsigned bit = 1u << unsigned(role);
            if (mask & bit) return false;
            mask |= bit;
        }
        constexpr unsigned vacated = (1u << unsigned(Role::Vacated0)) | (1u << unsigned(Role::Vacated1));
        constexpr unsigned current = ((1u << MaxPatches) - 1u) & ~vacated;
        return mask == current || (checkpoint != 'A' && mask == (current | vacated));
    }
};

struct Override {
    u64 address{};
    vk::Image image{};
    vk::Format format{};
    vk::Extent2D extent{};
    vk::Semaphore draw_timeline{};
    u64 draw_tick{};
};

struct Result {
    SewerMotion::Key key{};
    bool fenced{};
    const char* reason{};
    u64 present_serial{};
};
struct Lease {};

// Offer on the real render encoder, after the exact original tonemap and display draw have issued.
// The caller owns full native writer/UI coverage and a pending retirement for the key.
// consume_epoch rechecks the current one-use display entry under its owning mutex and consumes it.
// It validates the current scene generation and the actual display generation/write.
struct Issued {
    SewerMotion::MergeToken merge{};
    SewerMotion::Resource tonemap_input{}, tonemap_output{};
    u64 tonemap_input_write{}, tonemap_output_write{}, tonemap_tick{};
    Override display{};
    vk::ImageView display_attachment{};
    u64 display_generation{}, display_write{};
    Regions regions{};
    std::function<bool(const Override&, u64 generation, u64 write)> consume_epoch;
    std::function<void(Result)> complete;
    std::shared_ptr<const Lease> lease;
};

inline bool SameKey(const SewerMotion::Key& a, const SewerMotion::Key& b) {
    return a.request == b.request && a.scene == b.scene && a.loading == b.loading &&
           a.generation == b.generation && a.frame == b.frame && a.checkpoint == b.checkpoint &&
           a.enabled == b.enabled;
}
inline bool SameBacking(const SewerMotion::Resource& a, const SewerMotion::Resource& b) {
    return a.id == b.id && a.uid == b.uid && a.image == b.image && a.aspect == b.aspect;
}
inline bool SameMerge(const SewerMotion::MergeToken& a, const SewerMotion::MergeToken& b) {
    return SameKey(a.key, b.key) && SameBacking(a.destination, b.destination) &&
           a.destination.view == b.destination.view && a.output == b.output && a.output_view == b.output_view &&
           a.timeline == b.timeline && a.tick == b.tick && a.write == b.write && a.mode == b.mode &&
           a.alpha == b.alpha && a.sharpen == b.sharpen && a.folded == b.folded;
}
inline bool DisplayColor(vk::Format format) {
    return format == vk::Format::eB8G8R8A8Unorm || format == vk::Format::eB8G8R8A8Srgb ||
           format == vk::Format::eR8G8B8A8Unorm || format == vk::Format::eR8G8B8A8Srgb;
}
inline bool Valid(const Issued& proof, const SewerMotion::MergeToken& current) {
    const auto rgba = vk::ImageAspectFlagBits::eColor;
    const auto& key = current.key;
    return key.request && key.scene && key.frame && key.checkpoint >= 'A' && key.checkpoint <= 'C' &&
           SameMerge(proof.merge, current) && current.destination.image && current.destination.view &&
           current.destination.id && current.destination.uid && current.destination.aspect == rgba &&
           current.output && current.output_view && current.write && current.timeline && current.tick &&
           current.mode == 0 &&
           SameBacking(proof.tonemap_input, current.destination) && proof.tonemap_input.view &&
           proof.tonemap_input_write == current.write &&
           proof.tonemap_output.image && proof.tonemap_output.image != proof.tonemap_input.image &&
           proof.tonemap_output.uid && proof.tonemap_output.view && proof.tonemap_output.aspect == rgba &&
           proof.tonemap_output_write && proof.tonemap_tick >= current.tick &&
           proof.display.address && proof.display.image && proof.display_attachment &&
           DisplayColor(proof.display.format) && proof.display.extent == Extent &&
           proof.display.draw_timeline == current.timeline && proof.display.draw_tick >= proof.tonemap_tick &&
           proof.display_generation && proof.display_write && proof.regions.Valid(key.checkpoint) &&
           proof.consume_epoch && proof.complete;
}

inline void Finish(Issued& proof, bool fenced, const char* why, u64 serial = 0) {
    auto callback = std::exchange(proof.complete, {});
    proof.lease.reset();
    if (!fenced) {
        std::printf("[sewer-motion] event=final-refused request=%llu checkpoint=%c frame=%u why=%s\n",
                    static_cast<unsigned long long>(proof.merge.key.request), proof.merge.key.checkpoint,
                    proof.merge.key.frame, why);
    }
    if (callback) callback({proof.merge.key, fenced, why, serial});
}

class PendingProof {
public:
    bool Set(Issued proof, const SewerMotion::MergeToken& current) {
        if (!Valid(proof, current)) {
            Finish(proof, false, "unproved-tonemap-or-display");
            return false;
        }
        {
            std::lock_guard lock(mutex);
            const auto& key = current.key;
            const bool distinct = !offered_ || (offered_->request == key.request &&
                offered_->enabled == key.enabled && offered_->loading == key.loading &&
                offered_->generation == key.generation && key.frame > offered_->frame &&
                key.checkpoint > offered_->checkpoint);
            if (!proof_ && distinct && lease_.expired()) {
                proof.lease = std::make_shared<Lease>();
                lease_ = proof.lease;
                offered_ = key;
                proof_ = std::move(proof);
                return true;
            }
        }
        Finish(proof, false, "display-proof-repeat-or-already-pending");
        return false;
    }

    std::optional<Issued> Take(const Override& actual, u32 frame) {
        std::optional<Issued> selected;
        {
            std::lock_guard lock(mutex);
            if (!proof_ || proof_->merge.key.frame > frame) return {};
            selected = std::exchange(proof_, std::nullopt);
        }
        auto& proof = *selected;
        if (proof.merge.key.frame != frame || actual.address != proof.display.address ||
            actual.image != proof.display.image || actual.format != proof.display.format ||
            actual.extent != proof.display.extent ||
            actual.draw_timeline != proof.display.draw_timeline ||
            actual.draw_tick < proof.display.draw_tick) {
            Finish(proof, false, "prepared-display-replaced-or-stale");
            return {};
        }
        if (!proof.consume_epoch(actual, proof.display_generation, proof.display_write)) {
            Finish(proof, false, "prepared-display-write-epoch");
            return {};
        }
        proof.consume_epoch = {};
        return selected;
    }

    void Cancel(const char* why) {
        std::optional<Issued> selected;
        {
            std::lock_guard lock(mutex);
            selected = std::exchange(proof_, std::nullopt);
        }
        if (selected) Finish(*selected, false, why);
    }

private:
    std::mutex mutex;
    std::optional<Issued> proof_;
    std::optional<SewerMotion::Key> offered_;
    std::weak_ptr<const Lease> lease_;
};

inline PendingProof pending;

inline bool OfferIssuedDisplay(Issued proof) {
    if (!SewerMotion::Enabled()) return false;
    const auto& key = proof.merge.key;
    const auto current = SewerMotion::CurrentMerge(proof.merge.timeline, key.frame, key.loading, key.generation);
    if (!current) {
        Finish(proof, false, "no-matching-ordinary-merge-token");
        return false;
    }
    const auto sample = SewerMotion::Find(proof.merge.timeline, key.frame, key.loading, key.generation);
    if (!sample || !proof.regions.Valid(key.checkpoint)) {
        Finish(proof, false, "present-region-registration");
        return false;
    }
    for (u32 i = 0; i < proof.regions.count; ++i) {
        const auto [role, xy] = proof.regions.points[i];
        const u32 index = unsigned(role);
        if (index > unsigned(Role::Dry)) continue;
        const auto& q = sample->pose.output[index];
        if (xy != vk::Offset2D{s32(q[0]), s32(q[1])}) {
            Finish(proof, false, "present-current-anchor-mismatch");
            return false;
        }
    }
    return pending.Set(std::move(proof), *current);
}

struct PresentSource {
    vk::Image image{};
    vk::ImageView view{};
    vk::Fence fence{};
    vk::Semaphore ready{};
    u64 ready_tick{}, frame_generation{}, swap_generation{};
    vk::Extent2D extent{};
    vk::Format format{};
};

inline bool SameSource(const PresentSource& a, const PresentSource& b) {
    return a.image && a.view && a.fence && a.ready && a.ready_tick && a.frame_generation && a.swap_generation &&
           a.image == b.image && a.view == b.view && a.fence == b.fence && a.ready == b.ready &&
           a.ready_tick == b.ready_tick && a.frame_generation == b.frame_generation &&
           a.swap_generation == b.swap_generation && a.extent == Extent && a.extent == b.extent &&
           a.format == Format && a.format == b.format;
}
struct Gate {
    bool real{}, blank{}, reused{}, generated{}, hdr{}, overlays{}, secondary{}, full_cover{};
    vk::Extent2D output{};
    vk::SurfaceFormatKHR surface{};
};

inline bool Ordinary(const Gate& gate) {
    return gate.real && !gate.blank && !gate.reused && !gate.generated && !gate.hdr &&
           !gate.overlays && !gate.secondary && gate.full_cover && gate.output == Extent &&
           gate.surface.format == Format && gate.surface.colorSpace == Sdr;
}

struct Capture;
} // namespace Vulkan::SewerPresent
