// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#ifdef BB_TEST_BOTTLE_CUT_SOURCE
#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <mutex>
#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

namespace Vulkan::BottleCaustic::CutSource {

struct MasterRead {
    u64 epoch{}, read{};
    bool on{};
    explicit operator bool() const { return epoch && read; }
};

// Hold the lock across the actual getter and publication so another reader cannot publish a
// stale effective value after a newer value. File updates with the same bool keep this epoch.
class MasterHistory {
public:
    template <typename Getter>
    MasterRead Read(Getter&& get) {
        const std::scoped_lock guard(lock);
        const bool value = get();
        last.epoch += !last.read || last.on != value;
        ++last.read;
        last.on = value;
        return last;
    }

    MasterRead Latest() {
        const std::scoped_lock guard(lock);
        return last;
    }

private:
    std::mutex lock;
    MasterRead last{};
};

struct SceneKey {
    u32 request{};
    u64 scene{}, load{}, target_generation{}, rt_frame{}, object_frame{}, primary_pass{};
    explicit operator bool() const {
        return request && scene && load && target_generation && primary_pass;
    }
    bool operator==(const SceneKey&) const = default;
};

struct DrawOrder {
    vk::Semaphore timeline{};
    u64 tick{}, draw{};
    explicit operator bool() const { return timeline && tick && draw; }
};

struct Camera {
    std::array<float, 12> view{};
    std::array<float, 4> projection{};
    std::array<float, 2> jitter{};
    bool Valid() const {
        const auto finite = [](float value) { return std::isfinite(value); };
        return std::ranges::all_of(view, finite) && std::ranges::all_of(projection, finite) &&
               projection[0] != 0.f && projection[1] != 0.f &&
               std::ranges::all_of(jitter, [](float value) { return std::abs(value) <= 1.f; });
    }
    bool operator==(const Camera&) const = default;
};

struct Backing {
    u32 id{};
    u64 uid{}, generation{}, parent_write{}, guest_begin{}, guest_end{};
    vk::Image parent{}, proxy{};
    vk::ImageView view{};
    vk::Extent3D extent{};
    vk::Format format{};
    vk::ImageSubresourceRange range{};
    vk::ImageLayout layout{};
    vk::ImageUsageFlags usage{};
    vk::PipelineStageFlags2 stages{};
    vk::AccessFlags2 access{};

    bool Valid(u64 target_generation, bool depth) const {
        using enum vk::Format;
        using enum vk::ImageAspectFlagBits;
        return uid && generation == target_generation && guest_begin && guest_end > guest_begin &&
               parent && proxy && parent != proxy && view && extent == vk::Extent3D{1920, 1080, 1} &&
               (depth ? (format == eD32Sfloat || format == eD32SfloatS8Uint)
                      : format == eR16G16B16A16Sfloat) &&
               range == vk::ImageSubresourceRange{depth ? eDepth : eColor, 0, 1, 0, 1} &&
               layout != vk::ImageLayout::eUndefined && stages && access;
    }

    bool SameVersion(const Backing& other) const {
        return id == other.id && uid == other.uid && generation == other.generation &&
               parent_write == other.parent_write && guest_begin == other.guest_begin &&
               guest_end == other.guest_end && parent == other.parent && proxy == other.proxy &&
               extent == other.extent && format == other.format && range == other.range;
    }
};

struct GBufferDecision {
    SceneKey scene{};
    DrawOrder order{};
    MasterRead master{}; // Stamp returned by the actual EffectsAfterTargets read.
};

struct Guard {
    enum class Branch { NoPassObject, MasterOff, MasterOn };
    Branch branch{};
    MasterRead read{}; // Empty when the pass pointer short-circuited the ordinary expression.
};

enum class Outcome { Unproven, OffBypass, OnNoPhase2, Phase2Unjoined, Phase2Queued };

struct Opportunity {
    SceneKey scene{};
    DrawOrder order{};
    Camera camera{};
    Backing color{}, depth{};
    Guard guard{};
    GBufferDecision gbuffer{};
    MasterRead latest{};
    MasterRead effective{};
    u64 sequence{}, earlier_phase2{};
    Outcome outcome{};

    // 'latest' is only a snapshot of observed master reads. In the cold case the actual false
    // G-buffer read owns the evidence and an intervening observed activation invalidates it.
    static Opportunity Observe(SceneKey scene, DrawOrder order, Camera camera, Backing color,
                               Backing depth, Guard guard, GBufferDecision gbuffer,
                               MasterRead latest, u64 sequence, u64 earlier_phase2) {
        Opportunity result{scene, order, camera, color, depth, guard, gbuffer, latest,
                           {}, sequence, earlier_phase2};
        if (!scene || !order || !camera.Valid() || !color.Valid(scene.target_generation, false) ||
            !depth.Valid(scene.target_generation, true) || color.proxy == depth.proxy ||
            !sequence || earlier_phase2 >= sequence) {
            return result;
        }
        if (guard.branch == Guard::Branch::NoPassObject) {
            if (guard.read || !gbuffer.master || gbuffer.master.on || gbuffer.scene != scene ||
                !gbuffer.order || gbuffer.order.timeline != order.timeline ||
                gbuffer.order.tick > order.tick || gbuffer.order.draw >= order.draw ||
                !latest || latest.on || latest.epoch != gbuffer.master.epoch ||
                latest.read < gbuffer.master.read) {
                return result;
            }
            result.effective = gbuffer.master;
            result.outcome = Outcome::OffBypass;
        } else if (guard.read &&
                   ((guard.branch == Guard::Branch::MasterOn && guard.read.on) ||
                    (guard.branch == Guard::Branch::MasterOff && !guard.read.on))) {
            result.effective = guard.read;
            result.outcome = guard.read.on ? Outcome::OnNoPhase2 : Outcome::OffBypass;
        }
        return result;
    }

    bool MatchesPhase(u64 captured_frame, u64 rt_frame, vk::Semaphore timeline, u64 tick,
                      const Camera& actual_camera, const Backing& actual_color,
                      const Backing& actual_depth) const {
        return outcome == Outcome::OnNoPhase2 && effective && effective.on &&
               scene.rt_frame == captured_frame && scene.rt_frame == rt_frame &&
               order.timeline == timeline && order.tick <= tick && camera == actual_camera &&
               actual_color.Valid(scene.target_generation, false) &&
               actual_depth.Valid(scene.target_generation, true) &&
               color.SameVersion(actual_color) && depth.SameVersion(actual_depth) &&
               actual_color.layout == vk::ImageLayout::eGeneral &&
               actual_depth.layout == vk::ImageLayout::eGeneral;
    }
};

// Whole-scene classification retains previously observed on work when the guard later turns off.
// The owner of the primary scene calls Add for every opportunity in order and declares gaps.
struct SceneSource {
    SceneKey key{};
    u64 last_sequence{}, last_phase2{};
    DrawOrder last_order{};
    bool saw_on{}, saw_off{}, incomplete{}, closed{};

    bool Add(const Opportunity& opportunity) {
        if (closed || opportunity.scene != key || opportunity.sequence <= last_sequence ||
            opportunity.earlier_phase2 != last_phase2 ||
            (last_order && (opportunity.order.timeline != last_order.timeline ||
                            opportunity.order.tick < last_order.tick ||
                            opportunity.order.draw <= last_order.draw))) {
            incomplete = true;
            return false;
        }
        last_sequence = opportunity.sequence;
        last_order = opportunity.order;
        switch (opportunity.outcome) {
        case Outcome::Unproven:
            incomplete = true;
            break;
        case Outcome::OffBypass:
            saw_off = true;
            break;
        case Outcome::Phase2Unjoined:
            incomplete = true;
            [[fallthrough]];
        case Outcome::Phase2Queued:
            last_phase2 = opportunity.sequence;
            [[fallthrough]];
        case Outcome::OnNoPhase2:
            saw_on = true;
            break;
        }
        return true;
    }

    void Close(bool complete) {
        incomplete |= !complete;
        closed = true;
    }

    bool CleanOff() const { return closed && saw_off && !saw_on && !last_phase2 && !incomplete; }
};

using Texel = std::array<u16, 4>;
enum class StoreVerdict { Invalid, NoIndirectWork, NoReceiverDelta, ReceiverChanged };

struct StoreEvidence {
    std::array<u32, 3> groups{};
    u32 receiver_changed{}, opaque_changed{}, alpha_changed{};
    bool valid{true};

    void Add(bool opaque, const Texel& before, const Texel& after) {
        const auto finite = [](u16 word) { return (word & 0x7c00) != 0x7c00; };
        valid &= std::ranges::all_of(before, finite) && std::ranges::all_of(after, finite);
        alpha_changed += before[3] != after[3];
        const bool rgb = !std::equal(before.begin(), before.begin() + 3, after.begin(), [](u16 a, u16 b) {
            return a == b || ((a | b) & 0x7fff) == 0;
        });
        if (opaque) opaque_changed += before != after;
        else receiver_changed += rgb;
    }

    StoreVerdict Verdict() const {
        if (!valid || opaque_changed || alpha_changed || groups[0] > 240 || groups[1] > 135 ||
            groups[2] != 1) {
            return StoreVerdict::Invalid;
        }
        if (!groups[0] || !groups[1]) {
            return receiver_changed ? StoreVerdict::Invalid : StoreVerdict::NoIndirectWork;
        }
        return receiver_changed ? StoreVerdict::ReceiverChanged : StoreVerdict::NoReceiverDelta;
    }
};

u32 Run();
void ReportOpportunity(const Opportunity&);

} // namespace Vulkan::BottleCaustic::CutSource
#endif
