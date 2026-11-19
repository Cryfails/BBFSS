// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#ifdef BB_TEST_BOTTLE_CUT_SOURCE
#include <cstdio>
#include <optional>
#include "video_core/renderer_vulkan/vk_bottle_cut_source.h"
#include <vk_mem_alloc.h>

namespace VideoCore { class TextureCache; }

namespace Vulkan {
class CameraMotion;
class ObjectMotion;
class Rasterizer;
class RtShadow;
class SceneTargets;
class Scheduler;
class TemporalUpscaler;

namespace BottleColdSource177 {
namespace Source = BottleCaustic::CutSource;

struct Frame {
    const void* owner{};
    u32 request{}, draw_frame{};
    u64 load{}, targets{}, rt_frame{}, object_frame{};
    vk::Semaphore timeline{};
    bool loading{};
    bool operator==(const Frame&) const = default;
    explicit operator bool() const {
        return owner && request && load && targets && timeline && !loading;
    }
};

struct Image {
    u32 id{};
    u64 uid{};
    vk::Image handle{};
    VmaAllocation allocation{};
    bool operator==(const Image&) const = default;
    explicit operator bool() const { return uid && handle && allocation; }
    bool Distinct(const Image& other) const {
        return *this && other && uid != other.uid && handle != other.handle && allocation != other.allocation;
    }
    bool Owns(const Source::Backing& backing) const {
        return backing.id == id && backing.uid == uid && backing.parent == handle;
    }
};

struct Primary {
    Image depth{}, normal{}, albedo{};
    bool operator==(const Primary&) const = default;
    explicit operator bool() const {
        return depth.Distinct(normal) && depth.Distinct(albedo) && normal.Distinct(albedo);
    }
};

enum class State : u8 { Unknown, Off, On, Mixed };

struct OrdinaryView {
    vk::Image image{};
    vk::ImageView view{};
    u64 incarnation{};
    explicit operator bool() const { return image && view && incarnation; }
};

struct OrdinaryRead {
    u64 tick{}, opportunity{};
    OrdinaryView color{}, depth{};
};

struct Closed {
    Frame frame{};
    Source::SceneSource source{};
    Image depth{}, color{};
    std::optional<Source::Camera> camera;
    u64 first_epoch{}, last_epoch{};
    u32 cold_null{}, warm_off{}, on{}, unknown{}, missing_bindings{};
    State state{};
    bool before_display{};
    const char* reason{};
    State raw_state{};
    std::optional<OrdinaryRead> ordinary_read;
    const char* raw_refusal{};

    bool Ready() const {
        return before_display && !reason && (state == State::Off || state == State::On);
    }
};

inline void Report(const Closed&);

class Capture {
public:
    // These are owned renderer observation sites, not Vulkan issue/submission order.
    static constexpr u32 MaxOpportunities = 64;

    void GBuffer(const Frame& frame, const Primary& targets, u64 tick, Source::MasterRead master) {
        if (closed_frame == frame || !frame) return;
        Open(frame);
        if (!targets || !tick || !master) {
            current.incomplete = raw_bad = true;
            return;
        }
        if (!current.key) {
            primary = targets;
            current.key = {frame.request, ++scene, frame.load, frame.targets, frame.rt_frame,
                           frame.object_frame, draw + 1};
        } else if (primary != targets) {
            current.incomplete = true;
            ambiguous = true;
            return;
        }
        gbuffer = {current.key, {frame.timeline, tick, ++draw}, master};
        Epoch(master);
    }

    std::optional<Source::Opportunity> Observe(const Frame& frame, Image depth, Image color,
                                              u64 tick, Source::Camera camera,
                                              Source::Backing color_backing,
                                              Source::Backing depth_backing, Source::Guard guard,
                                              Source::MasterRead latest,
                                              const void* reader = nullptr) {
        if (!frame || closed_frame == frame) return {};
        Open(frame);
        if (reader) {
            if (raw_reader && raw_reader != reader) raw_bad = true;
            raw_reader = reader;
        }
        if (!current.key || ambiguous || primary.depth != depth || !color.Distinct(depth) ||
            (scene_color && scene_color != color)) {
            current.incomplete = raw_bad = true;
            return {};
        }
        scene_color = color;
        if (current.last_sequence >= MaxOpportunities) {
            current.incomplete = true;
            overflow = true;
            return {};
        }
        if (camera.Valid()) {
            if (scene_camera && !SamePose(*scene_camera, camera)) current.incomplete = raw_bad = true;
            scene_camera = camera;
        } else {
            raw_bad = true;
        }
        if (!tick) raw_bad = true;
        if (!color.Owns(color_backing)) color_backing = {};
        if (!depth.Owns(depth_backing)) depth_backing = {};
        const Source::DrawOrder order{frame.timeline, tick, ++draw};
        using enum Source::Guard::Branch;
        const bool cold = guard.branch == NoPassObject && !guard.read && gbuffer.master &&
                          !gbuffer.master.on && gbuffer.scene == current.key && order &&
                          gbuffer.order.timeline == order.timeline && gbuffer.order.tick <= order.tick &&
                          gbuffer.order.draw < order.draw && latest && !latest.on &&
                          latest.epoch == gbuffer.master.epoch && latest.read >= gbuffer.master.read;
        if (cold) {
            ++cold_null;
        } else if (guard.read && guard.branch == MasterOff && !guard.read.on) {
            ++warm_off;
        } else if (guard.read && guard.branch == MasterOn && guard.read.on) {
            ++on;
        } else {
            ++unknown;
        }
        Epoch(cold ? gbuffer.master : guard.read);
        if (!color_backing.Valid(frame.targets, false) || !depth_backing.Valid(frame.targets, true)) {
            ++missing_bindings;
        }
        return Source::Opportunity::Observe(current.key, order, camera, color_backing, depth_backing,
                                            guard, gbuffer, latest, current.last_sequence + 1,
                                            current.last_phase2);
    }

    void Add(const Source::Opportunity& opportunity) {
        if (!current.Add(opportunity)) raw_bad = true;
    }

    void ReadOrdinary(const void* reader, u32 request, u32 frame, u64 load, u64 targets,
                      vk::Semaphore timeline, u64 tick, const Source::Camera& camera,
                      Image depth, Image color, OrdinaryView color_read, OrdinaryView depth_read) {
        if (!reader || reader != raw_reader) return;
        if (!active || active == closed_frame || active.request != request ||
            active.draw_frame != frame || active.load != load || active.targets != targets ||
            active.timeline != timeline) return;
        if (raw_read || raw_bad || !current.key || !current.last_order || !current.last_sequence ||
            !gbuffer.order || gbuffer.order.draw >= current.last_order.draw ||
            current.last_order.tick > tick || !scene_camera || camera != *scene_camera ||
            depth != primary.depth || color != scene_color || !color_read || !depth_read ||
            color_read.image == depth_read.image || color_read.image == color.handle ||
            depth_read.image == depth.handle || color_read.view == depth_read.view ||
            color_read.incarnation == depth_read.incarnation) {
            raw_bad = true;
            return;
        }
        raw_read = OrdinaryRead{tick, current.last_sequence, color_read, depth_read};
    }

    const OrdinaryRead* ReadFor(const Frame& frame) const {
        return raw_read && frame == active && frame != closed_frame ? &*raw_read : nullptr;
    }

    // Also used at the old post-Display frame hook to report the raw scope. That fallback
    // cannot enrol an already prepared frame. Foreign calls cannot consume an active owner.
    std::optional<Closed> Close(const Frame& frame, Image depth, Image color,
                                Source::Camera camera, bool before_display,
                                bool read_backing_current = false) {
        if (!active || active.owner != frame.owner || active == closed_frame) return {};
        const bool exact_frame = active == frame;
        const bool exact_source = exact_frame && depth && color && primary.depth == depth &&
                                  scene_color == color && scene_camera && camera.Valid() &&
                                  SamePose(*scene_camera, camera);
        const bool gap = current.last_order && gbuffer.order.draw >= current.last_order.draw;
        const bool full = exact_frame && current.key && current.last_sequence && !ambiguous &&
                          !overflow && !gap && (!before_display || exact_source);
        current.Close(full);
        State state = State::Unknown;
        const char* reason = nullptr;
        if (first_epoch && last_epoch > first_epoch) state = State::Mixed;
        if (!exact_frame) reason = "frame-scope";
        else if (ambiguous) reason = "primary-ambiguous";
        else if (!current.key) reason = "primary-unavailable";
        else if (overflow) reason = "opportunity-cap";
        else if (!current.last_sequence) reason = "opportunity-unavailable";
        else if (gap) reason = "opportunity-gap";
        else if (before_display && !exact_source) reason = "display-source";
        else if (state == State::Mixed) reason = "master-mixed";
        else if (missing_bindings) reason = "source-bindings";
        else if (current.incomplete || !first_epoch) reason = "opportunity-incomplete";
        else if (!before_display) reason = "after-display";
        else if (current.CleanOff()) state = State::Off;
        else if (current.saw_on && !current.saw_off) state = State::On;
        else reason = "master-unavailable";
        State raw_state{};
        const char* raw_refusal = nullptr;
        if (raw_reader) {
            const auto off = cold_null + warm_off;
            if (!before_display || !full || raw_bad || !first_epoch || first_epoch != last_epoch ||
                unknown || on + off != current.last_sequence || (on && off)) {
                raw_refusal = "raw-ordinary-scope";
            } else if (!raw_read) {
                raw_refusal = "raw-ordinary-run-read-unavailable";
            } else if (raw_read->opportunity != current.last_sequence) {
                raw_refusal = "raw-ordinary-opportunity-after-read";
            } else if (!read_backing_current) {
                raw_refusal = "raw-ordinary-read-rebound";
            } else if (off && current.last_phase2) {
                raw_refusal = "raw-off-phase2";
            } else {
                raw_state = on ? State::On : State::Off;
            }
        }
        closed_frame = active;
        return Closed{active, current, primary.depth, scene_color, scene_camera, first_epoch,
                      last_epoch, cold_null, warm_off, on, unknown, missing_bindings, state,
                      before_display, reason, raw_state, raw_state != State::Unknown ? raw_read : std::nullopt,
                      raw_refusal};
    }

private:
    static bool SamePose(const Source::Camera& a, const Source::Camera& b) {
        return a.view == b.view && a.projection == b.projection;
    }

    void Open(const Frame& frame) {
        if (active == frame) return;
        const bool drift = active && active != closed_frame;
        if (drift) {
            auto gap = Close(active, {}, {}, {}, false);
            gap->source.incomplete = true;
            gap->reason = "display-boundary-missing";
            Report(*gap);
        }
        active = frame;
        current = {};
        current.incomplete = raw_bad = drift;
        raw_reader = nullptr;
        raw_read.reset();
        primary = {};
        scene_color = {};
        scene_camera.reset();
        gbuffer = {};
        first_epoch = last_epoch = 0;
        cold_null = warm_off = on = unknown = missing_bindings = 0;
        ambiguous = overflow = false;
    }

    void Epoch(Source::MasterRead master) {
        if (!master) return;
        if (!first_epoch) first_epoch = master.epoch;
        if (master.epoch < last_epoch) {
            current.incomplete = raw_bad = true;
            return;
        }
        last_epoch = master.epoch;
    }

    Frame active{}, closed_frame{};
    Primary primary{};
    Image scene_color{};
    std::optional<Source::Camera> scene_camera;
    Source::SceneSource current{};
    Source::GBufferDecision gbuffer{};
    u64 scene{}, draw{}, first_epoch{}, last_epoch{};
    u32 cold_null{}, warm_off{}, on{}, unknown{}, missing_bindings{};
    bool ambiguous{}, overflow{}, raw_bad{};
    const void* raw_reader{};
    std::optional<OrdinaryRead> raw_read;
};

inline Capture& Current() {
    static thread_local Capture capture;
    return capture;
}

inline void Report(const Closed& closed) {
    const auto& key = closed.source.key;
    static thread_local u32 reports;
    if (reports >= 128) {
        if (reports == 128) {
            ++reports;
            std::printf("[bottle-cold-source] event=report-cap request=%u\n", closed.frame.request);
        }
        return;
    }
    ++reports;
    std::printf("[bottle-cold-source] event=scene request=%u frame=%u scene=%llu load=%llu "
                "targets=%llu rt_frame=%llu object_frame=%llu primary=%llu first_epoch=%llu "
                "last_epoch=%llu opportunities=%llu cold_null=%u master_off=%u master_on=%u "
                "master_unknown=%u missing_bindings=%u phase2=%llu before_display=%u "
                "state=%u reason=%s\n",
                closed.frame.request, closed.frame.draw_frame, static_cast<unsigned long long>(key.scene),
                static_cast<unsigned long long>(closed.frame.load),
                static_cast<unsigned long long>(closed.frame.targets),
                static_cast<unsigned long long>(closed.frame.rt_frame),
                static_cast<unsigned long long>(closed.frame.object_frame),
                static_cast<unsigned long long>(key.primary_pass),
                static_cast<unsigned long long>(closed.first_epoch),
                static_cast<unsigned long long>(closed.last_epoch),
                static_cast<unsigned long long>(closed.source.last_sequence), closed.cold_null,
                closed.warm_off, closed.on, closed.unknown, closed.missing_bindings,
                static_cast<unsigned long long>(closed.source.last_phase2), unsigned(closed.before_display),
                unsigned(closed.state), closed.reason ? closed.reason : "source-ready");
}

// Call on the original renderer producer before OnDisplayPass. Effects revalidates the
// current camera and physical target owners. The registered region/window owner enrols.
std::optional<Closed> CloseBeforeDisplay(const Rasterizer&, Scheduler&, const SceneTargets&,
                                         const RtShadow&, const ObjectMotion&, const CameraMotion&,
                                         const TemporalUpscaler&, VideoCore::TextureCache&);
} // namespace BottleColdSource177
} // namespace Vulkan
#endif
