// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r107_caustics): water caustics from the sun or moon (vk_caustics.h; the knob and the
// numbers in caustics_params.h, the pass in host_shaders/caustics.comp).

#include "video_core/renderer_vulkan/vk_caustics.h"
#include "video_core/renderer_vulkan/vk_sewer_motion_observer.h"
#include <charconv>

#include <algorithm>
#include <bit>
#include <cstddef>
#include <iterator>
#include <span>

#include <fmt/format.h>
#include <cstdarg>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <utility>

#include "bbport_settings.h" // bbport (r107c_caustics-lamp-gain): the game's lamp curve
#include "bbport_toggles.h"
#if __has_include("bbport_live_knobs.h")
#include "bbport_live_knobs.h" // test tools (r84_live-test-knobs) only: BB_WATER_MOTION live; else it is read once
#endif
#include "engine/engine_state.h" // bbport (r130b_water-moves): the hunter's position
#include "engine/loading.h"
#include "video_core/renderer_vulkan/strength_knob.h" // bbport (r128b_lrt-caustics-water)
#include "video_core/host_shaders/caustics_bed_observer_comp.h"
#include "video_core/host_shaders/caustics_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_local_falloff.h" // r107c
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_point_shadow.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_workflow_present.h"
#include "video_core/renderer_vulkan/water_evidence.h"
#include "video_core/renderer_vulkan/water_wetness_probe.h"
#include "video_core/renderer_vulkan/volumetric_area_gate.h" // bbport (r107b_caustics-visible)
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
namespace BC = ::BbCaustics;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Host = vk::PipelineStageFlagBits2::eHost;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr auto StorageImage = vk::DescriptorType::eStorageImage;
constexpr auto SampledImage = vk::DescriptorType::eSampledImage;
constexpr auto StorageBuffer = vk::DescriptorType::eStorageBuffer;
constexpr u32 LineCalls = 600;
constexpr u32 FirstLineCalls = 120; ///< the first line comes sooner, for short test runs
constexpr u64 ProfileRow = 107;     ///< EffectPass::Mark: the row "Lighting: water caustics"
constexpr vk::DeviceSize SlotBytes = BC::SlotWords * sizeof(u32);
constexpr vk::DeviceSize CounterBytes = BC::Slots * SlotBytes;
/// bbport (r107b_caustics-visible): the counters, then a data block a slot (caustics_layout.h).
constexpr vk::DeviceSize BufferBytes = CounterBytes + BC::Slots * BC::DataWords * sizeof(u32) +
                                       BC::Slots * BC::Motion::Words * sizeof(u32); // r130b: the motion block a slot
/// bbport (r107f_caustics-world-anchored): the world map (caustics_layout.h): one word a cell.
constexpr vk::DeviceSize WorldBytes = BC::MapWords * sizeof(u32);

/// BB_CAUSTICS and BB_CAUSTICS_LAMPS, read once (the first caller: Wanted, at the rasterizer's
/// start). Set to something that is off, it says so.
const BC::Knobs& ReadKnobs() {
    static const BC::Knobs knobs = [] {
        const char* value = std::getenv("BB_CAUSTICS");
        BC::Knobs read = BC::Parse(value, std::getenv("BB_CAUSTICS_LAMPS"));
        read.world = BC::WorldOf(std::getenv("BB_CAUSTICS_WORLD")); // r107f
        if (read.unreadable) {
            std::printf("Water caustics (r107): BB_CAUSTICS=%.16s is neither a number nor show: off\n",
                        value);
        } else if (value != nullptr && value[0] != 0 && !(read.strength > 0.0f)) {
            std::printf("Water caustics (r107): BB_CAUSTICS=%.16s: off\n", value);
        }
        const char* lamps = std::getenv("BB_CAUSTICS_LAMPS");
        if (read.lamps_unreadable) {
            std::printf("Water caustics (r107b): BB_CAUSTICS_LAMPS=%.16s is neither a number nor "
                        "show: off\n",
                        lamps);
        } else if (lamps != nullptr && lamps[0] != 0 && !(read.lamp_strength > 0.0f)) {
            std::printf("Water caustics (r107b): BB_CAUSTICS_LAMPS=%.16s: off\n", lamps);
        }
        return read;
    }();
    return knobs;
}

// bbport (r128b_lrt-caustics-water): the strengths in force. A variable that is set and not empty
// decides for its channel (BB_CAUSTICS the sun and moon, BB_CAUSTICS_LAMPS the lamps; also with 0 or
// text: ReadKnobs read it once), else the lantern.ini setting, read at every call (a relaxed load).
bool EnvSet(const char* name) {
    const char* text = std::getenv(name);
    return text != nullptr && text[0] != '\0';
}

struct InForce {
    BC::Knobs knobs;
    bool sun_env = false, lamps_env = false;
};

InForce Current() {
    static const bool sun_env = EnvSet("BB_CAUSTICS"), lamps_env = EnvSet("BB_CAUSTICS_LAMPS");
    const auto& s = BbSettings::Get();
    return {BC::WithSettings(ReadKnobs(), sun_env, lamps_env,
                             s.graphics_water_caustics_sun_strength.load(std::memory_order_relaxed),
                             s.graphics_water_caustics_lamps_strength.load(std::memory_order_relaxed)),
            sun_env, lamps_env};
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet Write(u32 binding, vk::DescriptorType type,
                             const vk::DescriptorImageInfo* image) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type,
            .pImageInfo = image};
}

/// Four 8-bit channels (the game's screen shadow target, the G-buffer's material target).
bool FourBytes(const VideoCore::Image& image) {
    const auto f = image.info.pixel_format;
    return f == vk::Format::eR8G8B8A8Unorm || f == vk::Format::eB8G8R8A8Unorm ||
           f == vk::Format::eA8B8G8R8UnormPack32;
}
// bbport (r130b_water-moves): the strength of the moving water: BB_WATER_MOTION when set and not empty (live where the build has the
// live knobs header, else read once), else the lantern.ini setting graphics_water_motion_strength (a relaxed load).
struct MotionIn {
    float strength = 0.0f;
    bool from_env = false;
};

MotionIn MotionNow() {
#if __has_include("bbport_live_knobs.h")
    static BbLiveKnobs::Knob<float> knob{"BB_WATER_MOTION", BC::Motion::ParseEnv};
    const float env = knob.Get();
#else
    static const float env = BC::Motion::ParseEnv(std::getenv("BB_WATER_MOTION"));
#endif
    const float setting = BbSettings::Get().graphics_water_motion_strength.load(std::memory_order_relaxed);
    return {BC::Motion::Pick(env, setting), env >= 0.0f};
}

bool IndoorAmbient() {
    static const bool indoor = [] {
        const char* mode = std::getenv("BB_WATER_AMBIENT");
        return mode && std::strcmp(mode, "indoor") == 0;
    }();
    return indoor;
}

double AmbientRate() {
    static const double rate = BC::Motion::IndoorRate(std::getenv("BB_WATER_PHASE_RATE"));
    return rate;
}

static_assert(CAUSTICS_FLAG_AMBIENT == (CAUSTICS_FLAG_WARP << 1));
static_assert(sizeof(BC::Motion::Ambient) + sizeof(std::array<bool, BC::Slots>) <= 2048);

// t133a: scalar evidence only. All callers belong to the existing render thread.
namespace WE = BbWaterEvidence;
constexpr auto WaterEvidencePrefix = "Water evidence (t133a):";

const char* EvidenceLabel(const char* name, bool sha = false) {
    const char* text = std::getenv(name);
    if (!text) return "unavailable";
    const auto size = std::strlen(text);
    if (size == 0 || size > 64 || (sha && size != 64)) return "unavailable";
    for (const char* p = text; *p; ++p) {
        const bool digit = *p >= '0' && *p <= '9';
        const bool hex = digit || (*p >= 'a' && *p <= 'f') || (*p >= 'A' && *p <= 'F');
        const bool label = digit || (*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
                           *p == '-' || *p == '_';
        if (!(sha ? hex : label)) return "unavailable";
    }
    return text;
}

unsigned EvidenceSerial(const char* text) {
    unsigned serial = 0;
    if (!text) return 0;
    for (; *text; ++text) {
        if (*text < '0' || *text > '9' || serial > 99999) return 0;
        serial = serial * 10 + unsigned(*text - '0');
    }
    return serial;
}

struct RootEvidence {
    bool read = false, valid = false, jump = false;
    BC::Motion::Events events;
};

class WaterEvidence {
public:
    void Start(unsigned serial, WE::Clock::time_point now, u32 frame, const BC::Knobs& knobs, float strength) {
        serial_ = serial;
        window_ = {.started = now, .next_sample = now};
        previous_valid_ = false;
        clipped_lines_ = 0;
        text_.clear();
        text_.reserve((WE::Window::MaxSamples + WE::Window::MaxEvents + 2) * LineBytes);
        Line("%s begin serial=%u job=%s exe_sha256_supplied=%s tu_build=\"%s %s\" "
             "source=t133a/1 base_cpp_sha256=50b52e7af6b26d2bc3cd136ee89cfa5cec3fc84c990b463677fcf51975d8bf69 frame=%u host_ns=%llu "
             "strength_motion_sun_lamp=%.8g,%.8g,%.8g pose_time=unavailable\n",
             WaterEvidencePrefix, serial_, EvidenceLabel("BB_WATER_EVIDENCE_JOB"),
             EvidenceLabel("BB_WATER_EVIDENCE_EXE_SHA", true), __DATE__, __TIME__,
             frame, Ns(now), double(strength), double(knobs.strength), double(knobs.lamp_strength));
    }

    bool Open(WE::Clock::time_point now) const { return window_.Open(now); }

    void Finish(WE::Clock::time_point now, const char* reason) {
        Line("%s end serial=%u host_ns=%llu reason=%s apply_calls=%u same_frame_calls=%u "
             "samples=%u unsampled_calls=%u events=%u dropped_events=%u clipped_lines=%u "
             "sample_cap=%u apply_available=%u\n",
             WaterEvidencePrefix, serial_, Ns(now), reason, window_.calls, window_.same_frame_calls,
             window_.samples, window_.calls - window_.samples, window_.events, window_.dropped_events,
             clipped_lines_, unsigned(window_.samples == WE::Window::MaxSamples), unsigned(window_.calls != 0));
        // Reuse the stats writer. There is no render-thread file write, flush or GPU wait.
        if (const auto writer = BbReport::writer.load(std::memory_order_acquire)) {
            writer(std::move(text_));
        }
    }

    void Restart(u32 frame, float strength) {
        const auto now = WE::Clock::now();
        if (!Open(now)) return;
        previous_valid_ = false;
        if (window_.Event(now)) {
            Line("%s event serial=%u frame=%u pass=0 host_ns=%llu field_restart=1 motion=%.8g\n",
                 WaterEvidencePrefix, serial_, frame, Ns(now), double(strength));
        }
    }

    void Observe(WE::Clock::time_point now, u32 frame, double raw_dt, float strength,
                 const BC::Knobs& knobs, const std::array<float, 3>& wind, const BC::Motion::State& motion,
                 const RootEvidence& root, const float* xyz, VideoCore::ImageId depth_id,
                 VideoCore::TextureCache& cache, const CameraMotion::Matrices* camera,
                 bool plane, float plane_y, const BC::Motion::Ambient* ambient = nullptr,
                 bool legacy_drift = true) {
        if (!Open(now)) return;
        const bool sample = window_.Observe(now, frame);
        const double elapsed = std::chrono::duration<double>(now - previous_time_).count();
        const bool velocity_valid = root.valid && previous_valid_ && !root.jump && elapsed > 0.0;
        std::array<double, 3> velocity{};
        if (root.valid) {
            for (unsigned i = 0; i != 3; ++i) {
                if (velocity_valid) velocity[i] = (double(xyz[i]) - previous_root_[i]) / elapsed;
                previous_root_[i] = xyz[i];
            }
            previous_time_ = now;
        }
        previous_valid_ = root.valid;
        if ((root.events.steps || root.events.landings || root.jump) && window_.Event(now)) {
            Line("%s event serial=%u frame=%u pass=%u host_ns=%llu root=%.8g,%.8g,%.8g "
                 "step=%u landing=%u walker_jump_reset=%u rings=%u plane_valid=%u plane_y=%.8g\n",
                 WaterEvidencePrefix, serial_, frame, window_.pass, Ns(now), double(xyz[0]), double(xyz[1]),
                 double(xyz[2]), root.events.steps, root.events.landings, unsigned(root.jump), motion.count,
                 unsigned(plane), plane ? double(plane_y) : 0.0);
        }
        if (!sample) return;
        const bool camera_valid = camera && camera->valid;
        const auto* depth = depth_id ? cache.TryGetImage(depth_id, 0) : nullptr; // cached metadata, no TouchImage
        const double motion_dt = !ambient && strength > 0.0f ? BC::Motion::UsedDt(raw_dt) : 0.0;
        char detail[320]{};
        if (ambient) {
            const double dt = BC::Motion::UsedDt(ambient->raw_dt);
            std::snprintf(detail, sizeof(detail),
                          " mode=indoor ambient_frame=%u ambient_raw_dt_s=%.9g ambient_used_dt_s=%.9g "
                          "phase_rate=%.8g ambient_longest_step_rad=%.9g legacy_drift_used_dt_s=%.9g "
                          "agitation_observer=disabled",
                          ambient->frame, ambient->raw_dt, dt, AmbientRate(),
                          BC::Motion::Omega(BC::Motion::Wavelength[0]) * (dt * AmbientRate()),
                          legacy_drift ? BC::Motion::UsedDt(raw_dt) : 0.0);
        }
        Line("%s sample serial=%u frame=%u pass=%u apply=%u host_ns=%llu "
             "raw_dt_s=%.9g motion_used_dt_s=%.9g motion_advanced=%u strength_motion_sun_lamp=%.8g,%.8g,%.8g "
             "wind_xyz=%.8g,%.8g,%.8g wind_speed=%.8g heading_deg=%.8g steepness=%.8g phase_rad=%.9g,%.9g,%.9g,%.9g "
             "plane_observed=%u plane_valid=%u plane_y=%.8g camera_valid=%u camera=%.8g,%.8g,%.8g "
             "depth_id=%u depth_extent=%ux%u root_read=%u root_valid=%u root=%.8g,%.8g,%.8g "
             "estimated_velocity_valid=%u estimated_root_mps=%.8g,%.8g,%.8g "
             "rings=%u step=%u landing=%u walker_jump_reset=%u%s\n",
             WaterEvidencePrefix, serial_, frame, window_.pass, window_.calls, Ns(now),
             raw_dt, motion_dt, unsigned(!ambient && strength > 0.0f), double(strength), double(knobs.strength),
             double(knobs.lamp_strength), double(wind[0]), double(wind[1]), double(wind[2]), motion.wind_speed,
             BC::Motion::HeadingDeg(motion), double(motion.steep), motion.phase[0], motion.phase[1], motion.phase[2],
             motion.phase[3], unsigned(camera != nullptr), unsigned(plane), plane ? double(plane_y) : 0.0,
             unsigned(camera_valid), camera_valid ? double(camera->inv_view[3]) : 0.0,
             camera_valid ? double(camera->inv_view[7]) : 0.0, camera_valid ? double(camera->inv_view[11]) : 0.0,
             depth_id.index, depth ? depth->info.size.width : 0u, depth ? depth->info.size.height : 0u,
             unsigned(root.read), unsigned(root.valid), root.valid ? double(xyz[0]) : 0.0,
             root.valid ? double(xyz[1]) : 0.0, root.valid ? double(xyz[2]) : 0.0, unsigned(velocity_valid),
             velocity[0], velocity[1], velocity[2], motion.count, root.events.steps, root.events.landings,
             unsigned(root.jump), detail);
    }

private:
    static constexpr unsigned LineBytes = 1024;

    static unsigned long long Ns(WE::Clock::time_point now) {
        return static_cast<unsigned long long>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count());
    }

    __attribute__((format(printf, 2, 3))) void Line(const char* fmt, ...) {
        char line[LineBytes];
        va_list args;
        va_start(args, fmt);
        const int length = std::vsnprintf(line, sizeof(line), fmt, args);
        va_end(args);
        if (length < 0 || length >= int(sizeof(line))) {
            ++clipped_lines_;
            return;
        }
        text_.append(line, size_t(length));
    }

    WE::Window window_;
    unsigned serial_ = 0, clipped_lines_ = 0;
    bool previous_valid_ = false;
    WE::Clock::time_point previous_time_{};
    std::array<float, 3> previous_root_{};
    std::string text_;
};

WaterEvidence* active_water_evidence = nullptr;

void UpdateWaterEvidence(const BC::Knobs& knobs, float strength) {
    // Only an explicit startup opt-in enables the live serial reader. There is no off-path allocation.
    static const bool enabled = [] {
        const char* text = std::getenv("BB_WATER_EVIDENCE");
        return text && std::strcmp(text, "idle") == 0;
    }();
    if (!enabled) return;
#if __has_include("bbport_live_knobs.h")
    static BbLiveKnobs::Knob<unsigned> knob{"BB_WATER_EVIDENCE", EvidenceSerial};
    const unsigned serial = knob.Get();
#else
    const unsigned serial = 0; // no live capture in a build without the existing test knob reader
#endif
    static unsigned last_serial = 0;
    const auto now = WE::Clock::now();
    if (active_water_evidence && (serial != last_serial || !active_water_evidence->Open(now))) {
        active_water_evidence->Finish(now, !active_water_evidence->Open(now) ? "20s" : "serial_changed");
        active_water_evidence = nullptr;
    }
    if (serial != last_serial && serial != 0 && BbReport::writer.load(std::memory_order_acquire)) {
        static WaterEvidence capture;
        capture.Start(serial, now, BbStats::frame_number.load(std::memory_order_relaxed), knobs, strength);
        active_water_evidence = &capture;
    }
    last_serial = serial;
}

// bbport (r130e_sewer-water-moves): the copy image's one level
constexpr vk::ImageSubresourceRange WarpLevel{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
} // namespace

namespace WP = ::BbCaustics::WetnessProbe;

class Caustics::WetnessProbe {
public:
    WetnessProbe(const Instance& instance, Scheduler& scheduler)
        : instance{instance}, scheduler{scheduler},
          evidence_trigger{Enabled("BB_WATER_WETNESS_TRIGGER", "evidence")},
          measure_time{Enabled("BB_WATER_WETNESS_TIMESTAMPS")} {
        if (evidence_trigger) {
            std::printf("Water wetness t133f armed: waiting for the first t133a evidence serial\n");
        }
    }

    ~WetnessProbe() {
        if (state.started && !state.closed) {
            Close(WP::Clock::now(), "teardown");
        }
        Release();
    }

    static bool Enabled(const char* name, const char* wanted = "1") {
        const char* text = std::getenv(name);
        return text && std::strcmp(text, wanted) == 0;
    }

    void GBuffer(u32 frame, bool depth_changed) {
        if (state.closed) return;
        if (pass == 0 || frame != gbuffer_frame || depth_changed) {
            ++pass;
            if (pass == 0) ++pass;
            gbuffer_frame = frame;
        }
    }

    bool Due(WP::Time now, u32 frame) const { return state.Due(now, frame); }

    bool ObserveApply(u32 frame) {
        if (!state.started || state.closed) return false;
        const auto now = WP::Clock::now();
        if (!state.WindowOpen(now)) return false;
        if (refusal_frame && *refusal_frame != frame && now >= next_refusal) {
            ReportRefusal(now, frame);
        }
        last_apply = now;
        return Due(now, frame);
    }

    bool MatchingPass(u32 frame, VideoCore::ImageId depth, VideoCore::ImageId gbuffer,
                      VideoCore::ImageId camera) const {
        return pass != 0 && frame == gbuffer_frame && depth && depth == gbuffer && depth == camera;
    }

    void Refuse(u32 frame, const char* reason, int rank) {
        // Prefer the world pass's refusal over the earlier mirror pass of the same frame.
        if (refusal_frame != frame || rank >= refusal_rank) {
            refusal_frame = frame;
            refusal = reason;
            refusal_rank = rank;
        }
    }

    void Refresh(u32 frame) {
        if (state.closed && !buffer) return;
        const auto now = WP::Clock::now();
        if (!state.started) {
            if (evidence_trigger && !active_water_evidence) return;
            state.started = now;
            last_apply = now;
            next_refusal = now + WP::Interval;
            text.reserve(LogBytes);
            Line("Water wetness t133f begin frame=%u host_ns=%llu radius_m=%.9g locality_m=%.9g "
                 "predicate_m=%.9g+%.9g*view_z normal_y_min=%.9g view_z_max=%.9g "
                 "root_band_m=-0.60,-0.15 cpu_root_pose_time=unavailable host_object_bytes=%zu "
                 "host_slot_bytes=%zu log_capacity_bytes=%zu\n",
                 frame, Ns(now), double(WP::Radius), double(WP::Tolerance), double(CAUSTICS_WATER_M),
                 double(CAUSTICS_WATER_REL), double(CAUSTICS_PUDDLE_UP), double(CAUSTICS_FADE_END),
                 sizeof(*this), sizeof(state.slots), text.capacity());
        }
        if (!state.closed && !state.WindowOpen(now)) {
            Close(now, "20s");
        }
        state.Poll(frame, [&](u64 tick) { return scheduler.IsFree(tick); },
                   [&](u32 index, const WP::Slot& slot) {
                       if (!state.closed) Retire(frame, index, slot);
                   });
        if (state.closed && state.Pending() == 0) {
            Release();
        } else if (!state.closed && now >= next_refusal &&
                   (refusal_frame ? *refusal_frame != frame : now - last_apply >= WP::Interval)) {
            // A completed frame can report a missing prerequisite without consuming
            // the next world measurement's rate limit.
            ReportRefusal(now, frame);
        }
    }

    void Issue(WP::Source source, BC::Push geometry, float plane, vk::ImageView depth_view,
               vk::ImageView color_view, vk::Buffer standin, vk::Pipeline pipeline,
               vk::PipelineLayout layout) {
        const auto start = WP::Clock::now();
        if (!Due(start, source.frame)) return;
        state.Attempt(start, source.frame);
        refusal_frame.reset();
        const auto index = state.FreeSlot();
        if (!index) {
            ++busy;
            Line("Water wetness t133f unavailable frame=%u pass=%u host_ns=%llu reason=slots-busy\n",
                 source.frame, source.pass, Ns(start));
            return;
        }
        std::array<float, 3> root{};
        const bool read = BbEngine::world_player_position(root.data());
        const auto root_time = WP::Clock::now();
        if (!read || !WP::Finite(root)) {
            Line("Water wetness t133f unavailable frame=%u pass=%u host_ns=%llu reason=root-invalid\n",
                 source.frame, source.pass, Ns(root_time));
            return;
        }
        if (!buffer && !Allocate()) {
            Close(WP::Clock::now(), "mapped-allocation-failed");
            return;
        }
        auto& slot = state.slots[*index];
        if (BbStats::frame_number.load(std::memory_order_relaxed) != source.frame) {
            Line("Water wetness t133f unavailable frame=%u pass=%u host_ns=%llu reason=frame-advanced\n",
                 source.frame, source.pass, Ns(WP::Clock::now()));
            return;
        }
        const auto capture = WP::Clock::now();
        if (!state.WindowOpen(capture)) return;
        // Space recordings by the same interval even if the root read or first allocation took time.
        state.next_attempt = capture + WP::Interval;
        const auto push = WP::ProbePush(geometry, source, root, plane, ++state.sequence);
        const double displacement = previous_root_time
            ? std::hypot(double(root[0]) - previous_root[0], double(root[1]) - previous_root[1],
                         double(root[2]) - previous_root[2])
            : -1.0;
        slot.request = {source, push, root_time, capture, displacement,
                        previous_root_time ? Millis(root_time - *previous_root_time) : -1.0};
        previous_root = root;
        previous_root_time = root_time;
        const auto offset = *index * stride;
        scheduler.RecordCrumb(
            {.name = "water wetness t133f"},
            [push, depth_view, color_view, standin, pipeline, layout, offset, buffer = buffer,
             pool = timestamps, query = *index * 2u](vk::CommandBuffer cmd) {
                const auto color = Info(color_view);
                const auto depth = Info(depth_view);
                const vk::DescriptorBufferInfo result_info{buffer, offset, sizeof(WP::Result)};
                const vk::DescriptorBufferInfo unused_info{standin, 0, VK_WHOLE_SIZE};
                const std::array writes{
                    Write(0, StorageImage, &color), Write(1, SampledImage, &depth),
                    Write(2, SampledImage, &depth), Write(3, SampledImage, &depth),
                    vk::WriteDescriptorSet{.dstBinding = 4, .descriptorCount = 1,
                                           .descriptorType = StorageBuffer, .pBufferInfo = &result_info},
                    Write(5, SampledImage, &depth), Write(6, SampledImage, &depth),
                    vk::WriteDescriptorSet{.dstBinding = 7, .descriptorCount = 1,
                                           .descriptorType = StorageBuffer, .pBufferInfo = &unused_info},
                    Write(8, StorageImage, &color), Write(9, SampledImage, &depth),
                };
                cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
                cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
                cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
                if (pool) {
                    cmd.resetQueryPool(pool, query, 2);
                    cmd.writeTimestamp2(AllCommands, pool, query);
                }
                cmd.dispatch(1, 1, 1);
                if (pool) cmd.writeTimestamp2(AllCommands, pool, query + 1);
                const vk::BufferMemoryBarrier2 host{
                    .srcStageMask = Compute, .srcAccessMask = vk::AccessFlagBits2::eShaderStorageWrite,
                    .dstStageMask = Host, .dstAccessMask = vk::AccessFlagBits2::eHostRead,
                    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .buffer = buffer, .offset = offset, .size = sizeof(WP::Result),
                };
                cmd.pipelineBarrier2({.bufferMemoryBarrierCount = 1, .pBufferMemoryBarriers = &host});
            });
        slot.tick = scheduler.CurrentTick();
        Capture(*index, slot);
    }

    u32 Pass() const { return pass; }

private:
    static unsigned long long Ns(WP::Time now) {
        return static_cast<unsigned long long>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count());
    }

    static double Millis(WP::Clock::duration d) {
        return std::chrono::duration<double, std::milli>(d).count();
    }

    __attribute__((format(printf, 2, 3))) void Line(const char* format, ...) {
        char line[768];
        va_list args;
        va_start(args, format);
        const int count = std::vsnprintf(line, sizeof(line), format, args);
        va_end(args);
        if (count > 0 && size_t(count) < sizeof(line) &&
            text.size() + size_t(count) <= LogBytes) {
            text.append(line, size_t(count));
        } else {
            ++clipped;
        }
    }

    void ReportRefusal(WP::Time now, u32 frame) {
        const u32 source = refusal_frame.value_or(frame);
        if (state.last_attempt_frame != source) {
            Line("Water wetness t133f unavailable frame=%u host_ns=%llu reason=%s\n",
                 source, Ns(now), refusal_frame ? refusal : "no-apply-pass");
        }
        refusal_frame.reset();
        next_refusal = now + WP::Interval;
    }

    bool Allocate() {
        stride = WP::SliceStride(instance.StorageMinAlignment(), instance.NonCoherentAtomSize());
        const VkBufferCreateInfo ci{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                                    .size = stride * WP::SlotCount,
                                    .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT};
        const VmaAllocationCreateInfo alloc_ci{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO,
        };
        VkBuffer raw{};
        VmaAllocationInfo info{};
        const auto vma = instance.GetAllocator();
        if (vmaCreateBuffer(vma, &ci, &alloc_ci, &raw, &allocation, &info) != VK_SUCCESS) return false;
        buffer = raw;
        mapped = static_cast<const std::byte*>(info.pMappedData);
        if (!mapped) {
            Release();
            return false;
        }
        VkMemoryPropertyFlags properties{};
        vmaGetAllocationMemoryProperties(vma, allocation, &properties);
        coherent = (properties & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT) != 0;
        if (measure_time) {
            const auto gpu = instance.GetPhysicalDevice();
            const auto families = gpu.getQueueFamilyProperties();
            const u32 family = instance.GetGraphicsQueueFamilyIndex();
            timestamp_bits = family < families.size() ? families[family].timestampValidBits : 0;
            timestamp_ns = gpu.getProperties().limits.timestampPeriod;
            if (timestamp_bits != 0 && timestamp_ns > 0.0) {
                auto pool = instance.GetDevice().createQueryPool(
                    {.queryType = vk::QueryType::eTimestamp, .queryCount = WP::SlotCount * 2u});
                if (pool.result == vk::Result::eSuccess) timestamps = pool.value;
            }
        }
        Line("Water wetness t133f memory result_bytes=%zu stride_bytes=%llu buffer_bytes=%llu "
             "vma_allocation_bytes=%llu coherent=%u timestamp_queries=%u\n",
             sizeof(WP::Result), static_cast<unsigned long long>(stride),
             static_cast<unsigned long long>(ci.size), static_cast<unsigned long long>(info.size),
             unsigned(coherent), timestamps ? WP::SlotCount * 2u : 0u);
        return true;
    }

    void Release() {
        if (!buffer) return;
        const auto destroy = [device = instance.GetDevice(), vma = instance.GetAllocator(),
                              buffer = buffer, allocation = allocation, pool = timestamps] {
            if (pool) device.destroyQueryPool(pool);
            vmaDestroyBuffer(vma, buffer, allocation);
        };
        // The normal presenter teardown is drained. In other cases the scheduler, which
        // already retires cached views/backings, owns the diagnostic resources until safe.
        const bool pending = std::ranges::any_of(state.slots, [&](const WP::Slot& slot) {
            return slot.tick && !scheduler.IsFree(*slot.tick);
        });
        if (pending) {
            scheduler.DeferOperation(destroy, "water wetness t133f release");
        } else {
            destroy();
        }
        buffer = nullptr;
        timestamps = nullptr;
        mapped = nullptr;
    }

    double GpuUs(u32 index) const {
        if (!timestamps) return -1.0;
        std::array<u64, 2> stamp{};
        const auto status = instance.GetDevice().getQueryPoolResults(
            timestamps, index * 2, 2, sizeof(stamp), stamp.data(), sizeof(u64),
            vk::QueryResultFlagBits::e64);
        if (status != vk::Result::eSuccess) return -1.0;
        const u64 mask = timestamp_bits >= 64 ? ~u64(0) : (u64(1) << timestamp_bits) - 1;
        return double((stamp[1] - stamp[0]) & mask) * timestamp_ns * 0.001;
    }

    void Capture(u32 index, const WP::Slot& slot) {
        const auto& [source, push, root_time, capture, root_m, root_ms] = slot.request;
        const double band_y = double(push.sun[1]) - double(push.sun[3]);
        Line("Water wetness t133f capture seq=%u capture_frame=%u pass=%u slot=%u tick=%llu "
             "depth_id=%u depth_uid=%llu image=0x%llx view=0x%llx reduced=%u proxy_generation=%llu "
             "size=%ux%u root=%.9g,%.9g,%.9g plane_y=%.9g root_plane_m=%.9g root_band=%u "
             "root_ns=%llu capture_ns=%llu root_to_record_us=%.3f previous_root_m=%.9g previous_root_ms=%.3f\n",
             push.slot, source.frame, source.pass, index, static_cast<unsigned long long>(*slot.tick),
             source.depth_id, static_cast<unsigned long long>(source.image_uid),
             static_cast<unsigned long long>(source.image), static_cast<unsigned long long>(source.view),
             unsigned(source.reduced), static_cast<unsigned long long>(source.proxy_generation),
             source.width, source.height, double(push.sun[0]), double(push.sun[1]), double(push.sun[2]),
             double(push.sun[3]), band_y, unsigned(band_y >= -0.60 && band_y <= -0.15), Ns(root_time),
             Ns(capture), Millis(capture - root_time) * 1000.0, root_m, root_ms);
        CameraLine(push.slot, "view", source.view_matrix);
        CameraLine(push.slot, "inverse_view", push.inv_view);
        Line("Water wetness t133f camera seq=%u proj=%.9g,%.9g,%.9g,%.9g jitter=%.9g,%.9g\n",
             push.slot, double(push.proj[0]), double(push.proj[1]), double(push.proj[2]),
             double(push.proj[3]), double(push.frame[2]), double(push.frame[3]));
    }

    void CameraLine(u32 seq, const char* name, const std::array<float, 12>& m) {
        Line("Water wetness t133f camera seq=%u %s=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,"
             "%.9g,%.9g,%.9g,%.9g,%.9g,%.9g\n",
             seq, name, double(m[0]), double(m[1]), double(m[2]), double(m[3]), double(m[4]),
             double(m[5]), double(m[6]), double(m[7]), double(m[8]), double(m[9]), double(m[10]),
             double(m[11]));
    }

    void Retire(u32 frame, u32 index, const WP::Slot& slot) {
        const u64 offset = index * stride;
        if (!coherent && vmaInvalidateAllocation(instance.GetAllocator(), allocation, offset,
                                                 sizeof(WP::Result)) != VK_SUCCESS) {
            Close(WP::Clock::now(), "invalidate-failed");
            return;
        }
        WP::Result result;
        std::memcpy(&result, mapped + offset, sizeof(result));
        const auto now = WP::Clock::now();
        const auto& req = slot.request;
        const auto verdict = WP::Validate(req, result, now);
        constexpr std::array verdicts{"water-candidate", "rejected", "unknown", "corrupt", "stale"};
        ++retired;
        stale += verdict == WP::Verdict::Stale;
        corrupt += verdict == WP::Verdict::Corrupt;
        Line("Water wetness t133f retire seq=%u capture_frame=%u retire_frame=%u frame_delta=%u "
             "slot=%u tick=%llu capture_ns=%llu retire_ns=%llu age_ms=%.3f verdict=%s "
             "four_visible_water=%u gpu_us=%.3f\n",
             req.push.slot, req.source.frame, frame, frame - req.source.frame, index,
             static_cast<unsigned long long>(*slot.tick), Ns(req.capture), Ns(now),
             Millis(now - req.capture), verdicts[static_cast<size_t>(verdict)],
             unsigned(verdict == WP::Verdict::Water), GpuUs(index));
        if (verdict == WP::Verdict::Corrupt) return;
        constexpr std::array reasons{"ok", "invalid-projection", "offscreen", "border",
                                     "coarse-projection", "invalid-depth", "sky", "occluded",
                                     "no-surface-at-point", "invalid-neighbour", "degenerate-normal",
                                     "water-predicate-rejected"};
        for (const auto& p : result.points) {
            const auto f = [](u32 word) { return double(std::bit_cast<float>(word)); };
            Line("Water wetness t133f point seq=%u index=%u status=%u reason=%s pixel=%d,%d "
                 "raw=%.9g expected_z=%.9g observed_z=%.9g world=%.9g,%.9g,%.9g normal_y=%.9g "
                 "plane_residual_m=%.9g xz_residual_m=%.9g view_z_residual_m=%.9g\n",
                 p.sequence, p.index, p.status, reasons[p.reason], std::bit_cast<s32>(p.x),
                 std::bit_cast<s32>(p.y), f(p.depth), f(p.expected_z), f(p.observed_z),
                 f(p.world[0]), f(p.world[1]), f(p.world[2]), f(p.normal_y), f(p.plane_residual),
                 f(p.xz_residual), f(p.z_residual));
        }
    }

    void Close(WP::Time now, const char* reason) {
        state.closed = true;
        Line("Water wetness t133f end host_ns=%llu reason=%s attempts=%u issued=%u retired=%u "
             "pending=%u busy=%u stale=%u corrupt=%u clipped=%u\n",
             Ns(now), reason, state.attempts, state.sequence, retired, state.Pending(), busy,
             stale, corrupt, clipped);
        if (const auto writer = BbReport::writer.load(std::memory_order_acquire)) {
            writer(std::move(text));
        } else {
            std::fputs(text.c_str(), stdout);
        }
        std::string{}.swap(text);
    }

    static constexpr size_t LogBytes = 256 * 1024;
    const Instance& instance;
    Scheduler& scheduler;
    const bool evidence_trigger, measure_time;
    WP::Session state;
    std::string text;
    vk::Buffer buffer{};
    VmaAllocation allocation{};
    const std::byte* mapped = nullptr;
    u64 stride = 0;
    bool coherent = false;
    vk::QueryPool timestamps{};
    u32 timestamp_bits = 0;
    double timestamp_ns = 0.0;
    u32 gbuffer_frame = 0, pass = 0;
    u32 busy = 0, retired = 0, stale = 0, corrupt = 0, clipped = 0;
    std::array<float, 3> previous_root{};
    std::optional<WP::Time> previous_root_time;
    std::optional<u32> refusal_frame;
    WP::Time next_refusal{}, last_apply{};
    const char* refusal = nullptr;
    int refusal_rank = 0;
};

// bbport (r128b_lrt-caustics-water): the setting's numbers are the header's (one maximum, off by default).
class Caustics::BedObserver {
public:
    static constexpr vk::DeviceSize TailBytes = BED_OBS_TAIL_WORDS * sizeof(u32);
    static constexpr vk::DeviceSize AllocBytes = BufferBytes + TailBytes;

    using PointSet = std::array<vk::Offset3D, BED_OBS_NPOINTS>;
    using PointWords = std::array<u32, 2 * BED_OBS_NPOINTS>;

    class Capture {
    public:
        struct Binding {
            VideoCore::ImageId id{};
            u64 uid{};
            vk::Image image{};
            vk::ImageView view{};

            static Binding Of(VideoCore::ImageId id, const VideoCore::Image* image,
                              vk::ImageView view) {
                return {id, image ? image->image_uid : 0,
                        image ? image->GetImage() : vk::Image{}, view};
            }

            std::string Print() const {
                return fmt::format("{}/{}:{:x}/{:x}", id.index, uid,
                                   std::bit_cast<u64>(VkImage(image)),
                                   std::bit_cast<u64>(VkImageView(view)));
            }
        };

        // The two scene colours either side of Shade are also the initial and pre-WARP colours.
        void Report(const void* mapped) const {
            const auto* p = static_cast<const u32*>(mapped);
            const auto colors = fmt::format("scene={} depth={} cb2={} bed={} fallback={} bed_resolved={} "
                                            "warp_image={:x}/{:x}",
                                            color.Print(), depth.Print(), cb2.Print(), bed.Print(),
                                            bed_fallback, bed_resolved,
                                            std::bit_cast<u64>(VkImage(warp_image)),
                                            std::bit_cast<u64>(VkImageView(warp_view)));
            const auto reduced_info = reduced ?
                fmt::format(" route=reduced enabled={} copy_seq={}", unsigned(enabled), copy_seq) :
                std::string{};
            std::printf("[sewer-bed-t196] event=bound frame=%u tick=%llu loading=%llu generation=%llu "
                        "extent=%ux%u slot=%u row0=%u shade=%u copy=%u warp=%u indoor=%u "
                        "warp_state=%s plane=%08x bed_stage=%u samples=%u sample_state=%s "
                        "lamp_count=%u %s%s\n", frame, Tick(), static_cast<unsigned long long>(loading),
                        static_cast<unsigned long long>(generation), width, height, push.slot, row0,
                        flags[0], flags[1], flags[2], unsigned(indoor), warp_state,
                        std::bit_cast<u32>(push.sun[3]), stage, snapshots,
                        sample_state, lamp_data[CAUSTICS_DATA_COUNT], colors.c_str(), reduced_info.c_str());
            const auto proj = FWords(push.proj);
            const auto inv = FWords(push.inv_view);
            const auto camera = FWords(view);
            const auto jitter = FWords(std::array{push.frame[2], push.frame[3]});
            std::printf("[sewer-bed-t196] event=camera frame=%u tick=%llu proj=%s inverse=%s view=%s jitter=%s\n",
                        frame, Tick(), proj.c_str(), inv.c_str(), camera.c_str(), jitter.c_str());
            const auto data = Words(lamp_data);
            std::printf("[sewer-bed-t196] event=lamp-data frame=%u tick=%llu words=%s\n",
                        frame, Tick(), data.c_str());
            u32 rows = 0;
            for (u32 dispatch = 0; dispatch < BED_OBS_NSTAGES; ++dispatch) {
                if (!flags[dispatch]) continue;
                for (u32 point = 0; point < points.size(); ++point) {
                    const auto& xy = points[point];
                    const u32 row_index = dispatch * BED_OBS_NPOINTS + point;
                    const u32* row = p + BED_OBS_BASE + row_index * BED_OBS_WORDS;
                    const bool outside = dispatch != BED_OBS_SHADE && u32(xy.y) < row0;
                    const auto words = Words(std::span<const u32, BED_OBS_WORDS>{row, BED_OBS_WORDS});
                    std::printf("[sewer-bed-t196] event=row frame=%u tick=%llu stage=%u point=%u "
                                "pixel=%d,%d outside=%u words=%s\n", frame, Tick(), dispatch, point,
                                xy.x, xy.y, unsigned(outside), words.c_str());
                    if (reduced && (flags[dispatch] & CAUSTICS_FLAG_BED_2X) && row[BED_OBS_ENTRY] == BED_OBS_MAGIC) {
                        for (u32 sample = 0; sample < BED_OBS_NTAPS; ++sample) {
                            if (!(row[BED_OBS_READS] & (1u << sample))) continue;
                            const auto* tap = p + BED_OBS_TAPS +
                                (row_index * BED_OBS_NTAPS + sample) * BED_OBS_TAP_WORDS;
                            std::printf("[sewer-bed-t196] event=bed-tap frame=%u tick=%llu stage=%u "
                                        "point=%u sample=%u q=%u,%u raw=%08x\n",
                                        frame, Tick(), dispatch, point, sample, tap[0], tap[1], tap[2]);
                        }
                    }
                    ++rows;
                }
            }
            for (u32 sample = 0; sample < snapshots; ++sample) {
                for (u32 point = 0; point < points.size(); ++point) {
                    const auto& xy = points[point];
                    std::array<u16, 4> halves;
                    std::memcpy(halves.data(), reinterpret_cast<const std::byte*>(mapped) +
                                Offset(sample, point), sizeof(halves));
                    std::printf("[sewer-bed-t196] event=hdr frame=%u tick=%llu sample=%u point=%u "
                                "pixel=%d,%d half=%04x,%04x,%04x,%04x\n", frame, Tick(), sample, point,
                                xy.x, xy.y, u32(halves[0]), u32(halves[1]), u32(halves[2]), u32(halves[3]));
                }
            }
            std::printf("[sewer-bed-t196] event=fenced frame=%u tick=%llu rows=%u snapshots=%u\n",
                        frame, Tick(), rows, snapshots);
            if (motion) ReportMotion(p);
        }

        std::shared_ptr<SewerMotion::Checkpoint> motion;
        std::array<u32, BC::Motion::Words> wave{};
        float motion_strength{}, motion_rate{};
        u64 tick{}, loading{}, generation{}, copy_seq{};
        u32 frame{}, width{}, height{}, row0{}, stage{}, snapshots{};
        bool indoor{}, bed_fallback{}, bed_resolved{}, reduced{}, enabled{};
        PointSet points = NativePoints;
        const char* warp_state = "unknown";
        const char* sample_state = "unknown";
        BC::Push push{};
        std::array<float, 12> view{};
        std::array<u32, BED_OBS_NSTAGES> flags{};
        std::array<u32, BC::DataWords> lamp_data{};
        Binding color, depth, cb2, bed;
        vk::Image warp_image{};
        vk::ImageView warp_view{};

    private:
        void ReportMotion(const u32* p) const {
            const auto request = static_cast<unsigned long long>(motion->key.request);
            const char checkpoint = motion->key.checkpoint;
            for (u32 i = 0; i < motion->post_warp.size(); ++i) {
                std::memcpy(motion->post_warp[i].data(),
                            reinterpret_cast<const std::byte*>(p) + Offset(2, i),
                            sizeof(SewerMotion::HalfPixel));
            }
            const auto block = Words(wave);
            std::printf("[sewer-motion] event=warp request=%llu checkpoint=%c frame=%u tick=%llu "
                        "band=%u strength=%.9g rate=%.9g wave=%s\n",
                        request, checkpoint, frame, Tick(), row0, double(motion_strength),
                        double(motion_rate), block.c_str());
            for (u32 i = 0; i < 2; ++i) {
                const auto* taps = p + BED_OBS_OPTICS + i * CAUSTICS_MAX_LAMPS * BED_OBS_OPTIC_WORDS;
                for (u32 lamp = 0; lamp < CAUSTICS_MAX_LAMPS; ++lamp) {
                    const auto* optic = taps + lamp * BED_OBS_OPTIC_WORDS;
                    if (optic[0] == BED_OBS_UNREAD) continue;
                    std::printf("[sewer-motion] event=crossing request=%llu checkpoint=%c frame=%u "
                                "point=%u lamp=%u world=%08x,%08x,%08x focus=%08x\n",
                                request, checkpoint, frame, i, lamp, optic[0], optic[1], optic[2], optic[3]);
                }
            }
        }
        unsigned long long Tick() const {
            return static_cast<unsigned long long>(tick);
        }

        static std::string Words(std::span<const u32> words) {
            std::string text;
            text.reserve(words.size() * 9);
            for (const u32 word : words) {
                if (!text.empty()) text += ',';
                fmt::format_to(std::back_inserter(text), "{:08x}", word);
            }
            return text;
        }

        template <size_t N>
        static std::string FWords(const std::array<float, N>& words) {
            return Words(std::bit_cast<std::array<u32, N>>(words));
        }
    };

    bool Make(const Instance& instance, vk::PipelineLayout layout) {
        const auto device = instance.GetDevice();
        const auto module = device.createShaderModuleUnique({
            .codeSize = sizeof(CAUSTICS_BED_OBSERVER_COMP),
            .pCode = CAUSTICS_BED_OBSERVER_COMP,
        });
        if (module.result != vk::Result::eSuccess) return false;
        auto made = device.createComputePipelineUnique({}, vk::ComputePipelineCreateInfo{
            .stage = {.stage = vk::ShaderStageFlagBits::eCompute, .module = *module.value,
                      .pName = "main"},
            .layout = layout,
        });
        if (made.result != vk::Result::eSuccess) return false;
        pipeline = std::move(made.value);
        return true;
    }

    static void SetPoints(vk::CommandBuffer cmd, vk::Buffer buffer, const PointSet& points,
                          bool motion) {
        PointWords coords{};
        for (u32 i = 0; i < points.size(); ++i) {
            coords[2 * i] = u32(points[i].x);
            coords[2 * i + 1] = u32(points[i].y);
        }
        cmd.updateBuffer<u32>(buffer, BED_OBS_POINTS * sizeof(u32), coords);
        if (motion) {
            constexpr std::array<u32, 1> armed{1};
            cmd.updateBuffer<u32>(buffer, BED_OBS_MOTION_SERIES * sizeof(u32), armed);
        }
    }

    static void Snapshot(vk::CommandBuffer cmd, vk::Image image, vk::Buffer buffer,
                         u32 sample, const PointSet& points, vk::DeviceSize base = Offset(0, 0)) {
        constexpr auto transfer = vk::PipelineStageFlagBits2::eAllTransfer;
        constexpr auto read = vk::AccessFlagBits2::eTransferRead;
        ImageBarrier(cmd, image, AllCommands, vk::AccessFlagBits2::eMemoryWrite, transfer, read);
        std::array<vk::BufferImageCopy, BED_OBS_NPOINTS> regions{};
        for (u32 point = 0; point < points.size(); ++point) {
            regions[point] = {
                .bufferOffset = base + Offset(sample, point) - Offset(0, 0),
                .imageSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
                .imageOffset = points[point],
                .imageExtent = {1, 1, 1},
            };
        }
        cmd.copyImageToBuffer(image, vk::ImageLayout::eGeneral, buffer, regions);
        ImageBarrier(cmd, image, transfer, read, Compute, ReadWrite);
    }

    static void Refused(u32 frame, u64 tick, VideoCore::ImageId depth, NativeBedStage stage,
                        bool plane, float plane_y, u32 lamps, const char* reason) {
        std::printf("[sewer-bed-t196] event=refused frame=%u tick=%llu depth=%u bed_stage=%u "
                    "has_plane=%u plane=%08x lamp_count=%u reason=%s\n", frame,
                    static_cast<unsigned long long>(tick), depth.index, u32(stage), unsigned(plane),
                    std::bit_cast<u32>(plane_y), lamps, reason);
    }

    vk::UniquePipeline pipeline;
    bool taken = false;
    bool scheduled = false;

private:
    static constexpr PointSet NativePoints{{
        {BED_OBS_X0, BED_OBS_Y0, 0}, {BED_OBS_X1, BED_OBS_Y1, 0}, {BED_OBS_X2, BED_OBS_Y2, 0},
    }};
    static constexpr vk::DeviceSize TexelBytes = 4 * sizeof(u16);
    static constexpr vk::DeviceSize ReadBytes = BED_OBS_READBACK * sizeof(u32);
    static_assert(BED_OBS_BASE * sizeof(u32) == BufferBytes);
    static_assert(ReadBytes % TexelBytes == 0 && TexelBytes == 8);
    static_assert(ReadBytes + BED_OBS_NSTAGES * BED_OBS_NPOINTS * TexelBytes ==
                  BED_OBS_POINTS * sizeof(u32));
    static_assert(BED_OBS_TAPS == BED_OBS_POINTS + sizeof(PointWords) / sizeof(u32));
    static_assert((BED_OBS_OPTICS + 2u * CAUSTICS_MAX_LAMPS * BED_OBS_OPTIC_WORDS) *
                   sizeof(u32) <= AllocBytes);
    static_assert(BED_OBS_STAMP + 1u == BED_OBS_WORDS && BED_OBS_NSTAGES == 3u);
    static_assert(BED_OBS_LAMPS + CAUSTICS_MAX_LAMPS == BED_OBS_INCIDENT);

    static constexpr vk::DeviceSize Offset(u32 sample, u32 point) {
        return ReadBytes + (sample * BED_OBS_NPOINTS + point) * TexelBytes;
    }

    static void ImageBarrier(vk::CommandBuffer cmd, vk::Image image,
                             vk::PipelineStageFlags2 from, vk::AccessFlags2 from_access,
                             vk::PipelineStageFlags2 to, vk::AccessFlags2 to_access) {
        const vk::ImageMemoryBarrier2 barrier{
            .srcStageMask = from, .srcAccessMask = from_access,
            .dstStageMask = to, .dstAccessMask = to_access,
            .oldLayout = vk::ImageLayout::eGeneral, .newLayout = vk::ImageLayout::eGeneral,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = image, .subresourceRange = WarpLevel,
        };
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
    }
};


static_assert(BbSettings::WaterCausticsStrengthMax == ::BbCaustics::MaxStrength &&
              BbSettings::WaterCausticsStrengthMin == 0.0f && BbSettings::WaterCausticsStrengthDefault == 0.0f);
// bbport (r130b_water-moves): the motion setting's numbers are the same (one maximum, off by default).
static_assert(BbSettings::WaterMotionStrengthMax == ::BbCaustics::MaxStrength && BbSettings::WaterMotionStrengthMin == 0.0f &&
              BbSettings::WaterMotionStrengthDefault == 0.0f);

bool Caustics::Wanted() {
    const BC::Knobs k = Current().knobs;
    return k.strength > 0.0f || k.lamp_strength > 0.0f || MotionNow().strength > 0.0f; // r130e: the motion alone
}

void Caustics::StrengthLine() {
    static StrengthKnob::Line line;
    const InForce now = Current();
    const StrengthKnob::Value sun{now.knobs.strength, now.sun_env};
    const StrengthKnob::Value lamps{now.knobs.lamp_strength, now.lamps_env};
    if (line.Due(LineCalls, sun, lamps)) {
        std::printf("Water caustics (r128b): sun and moon strength %.2f from the %s (%s), lamps strength "
                    "%.2f from the %s (%s)%s\n",
                    double(sun.value), StrengthKnob::SourceName(sun),
                    sun.from_env ? "BB_CAUSTICS" : "graphics_water_caustics_sun_strength",
                    double(lamps.value), StrengthKnob::SourceName(lamps),
                    lamps.from_env ? "BB_CAUSTICS_LAMPS" : "graphics_water_caustics_lamps_strength",
                    sun.value > 0.0f || lamps.value > 0.0f ? "" : "; both 0: nothing is made or drawn");
    }
    // bbport (r130b_water-moves): the moving water's strength (first frame, after a change, at most once every 600)
    static StrengthKnob::Line motion_line;
    const MotionIn moving = MotionNow();
    UpdateWaterEvidence(now.knobs, moving.strength);
    const StrengthKnob::Value motion_value{moving.strength, moving.from_env};
    if (IndoorAmbient()) {
        if (motion_line.Due(LineCalls, motion_value)) {
            std::printf("Water ambient (r133c): indoor strength %.2f from the %s, phase rate %.3f, "
                        "water wind 0, glint 0, raw agitation disabled\n",
                        double(moving.strength), StrengthKnob::SourceName(motion_value), AmbientRate());
        }
        return;
    }
    if (motion_line.Due(LineCalls, motion_value)) {
        std::printf("Water motion (r130b): strength %.2f from the %s (%s)%s\n", double(moving.strength),
                    StrengthKnob::SourceName(motion_value),
                    moving.from_env ? "BB_WATER_MOTION" : "graphics_water_motion_strength",
                    !(moving.strength > 0.0f) ? "; 0: off, nothing runs"
                    : sun.value > 0.0f || lamps.value > 0.0f
                        ? ""
                        : "; the water caustics are off (both strengths 0): nothing moves");
    }
    // bbport (r130e_sewer-water-moves): with the motion on and both caustics strengths 0 the line above (r130b's) says nothing moves:
    // the reflection still ripples, only the net is not drawn
    static StrengthKnob::Line warp_line;
    if (moving.strength > 0.0f && !(sun.value > 0.0f || lamps.value > 0.0f) && warp_line.Due(LineCalls, motion_value)) {
        std::printf("%s: strength %.2f with both caustics strengths 0: no net is drawn, but the water's reflection still ripples "
                    "(warp, glint, shimmer); the line above that says nothing moves is out of date\n",
                    BC::Motion::Warp::LogTag, double(moving.strength));
    }
}

void Caustics::Refresh() {
    if (sewer_motion) RefreshSewerMotion();
    const bool indoor = IndoorAmbient();
    {   // bbport (r130b_water-moves): the moving water's strength; a start from 0 starts the field anew
        const MotionIn in = MotionNow();
        if (in.strength != motion_strength) {
            ++motion_changes;
            if (!indoor && motion_strength <= 0.0f) {
                motion = {};
                if (active_water_evidence) {
                    active_water_evidence->Restart(BbStats::frame_number.load(std::memory_order_relaxed), in.strength);
                }
            }
            motion_strength = in.strength;
        }
        motion_env = in.from_env;
    }
    if (indoor) {
        ambient.Tick(BbStats::frame_number.load(std::memory_order_relaxed),
                     BC::Motion::Ambient::Clock::now(), motion_strength, AmbientRate());
    }
    const BC::Knobs now = Current().knobs;
    if (now.strength != knobs.strength || now.lamp_strength != knobs.lamp_strength) {
        ++strength_changes;
        knobs.strength = now.strength;
        knobs.lamp_strength = now.lamp_strength;
    }
    {   // bbport (r130e_sewer-water-moves): the bed light follows the motion (a set BB_CAUSTICS_WORLD wins); the map is made when first needed
        knobs.world = BC::Motion::Warp::WorldFor(world_env_set, ReadKnobs().world, motion_strength, knobs.lamp_strength);
        if (knobs.world > 0.0f && knobs.lamp_strength > 0.0f && made && !world_map.buffer && !world_tried) {
            const bool made_map = MakeWorldMap();
            if (!told_bed && !world_env_set) {
                told_bed = true;
                std::printf("%s: the lamps' light on the bed under the water (r107f) runs with the motion; world map %u KB %s\n",
                            BC::Motion::Warp::LogTag, unsigned(WorldBytes / 1024), made_map ? "made" : "could not be made");
            }
        }
    }
    if (wetness_probe) {
        wetness_probe->Refresh(BbStats::frame_number.load(std::memory_order_relaxed));
    }
}

Caustics::Caustics(const Instance& instance_, Scheduler& scheduler_,
                   VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                   SceneTargets& scene_targets_, CameraMotion& camera_motion_,
                   PointShadow& point_shadow_, bool upscaler_on)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_}, point_shadow{point_shadow_},
      knobs{Current().knobs} { // bbport (r128b_lrt-caustics-water): setting or variable
    const char* native_bed_env = std::getenv("BB_CAUSTICS_NATIVE_BED");
    const char* reduced_probe = std::getenv("BB_SEWER_REDUCED_TRANSPORT");
    sewer_reduced_master = reduced_probe && std::string_view(reduced_probe) == "1";
    native_bed_enabled = native_bed_env && std::strcmp(native_bed_env, "1") == 0;
    if (WetnessProbe::Enabled("BB_WATER_WETNESS_PROBE")) {
        wetness_probe = std::make_unique<WetnessProbe>(instance, scheduler);
    }
    // The pipeline and the counters are made here, at the start or, with the setting, at the
    // first frame a strength is above 0 (r128b; as the heat haze, r97e).
    made = EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
           EffectPass::Create(instance, set_layout, layout, pipeline,
                              {StorageImage, SampledImage, SampledImage, SampledImage, StorageBuffer,
                               SampledImage, SampledImage, StorageBuffer, StorageImage,
                               SampledImage}, // 8: warp copy, 9: native bed depth
                              sizeof(BC::Push), CAUSTICS_COMP, "Water caustics");
    static const bool bed_observer_enabled = [] {
        const char* value = std::getenv("BB_SEWER_BED_OBSERVER");
        return value && std::strcmp(value, "1") == 0;
    }();
    if (bed_observer_enabled || (SewerMotion::Enabled() && !sewer_reduced_master)) {
        if (made) {
            bed_observer = std::make_unique<BedObserver>();
            if (!bed_observer->Make(instance, *layout)) bed_observer.reset();
        }
        if (!bed_observer) std::puts("[sewer-bed-t196] event=unavailable reason=pipeline");
    }
    if (made) {
        const auto allocate = [&](vk::DeviceSize size) {
            const VkBufferCreateInfo buffer_ci{
                .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                .size = size,
                .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
            };
            VmaAllocationCreateInfo alloc_ci{};
            alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
            alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
            alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
            VkBuffer raw{};
            VmaAllocationInfo info{};
            if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw,
                                &counters.allocation, &info) != VK_SUCCESS) {
                return false;
            }
            if (!info.pMappedData) {
                vmaDestroyBuffer(instance.GetAllocator(), raw, counters.allocation);
                counters.allocation = nullptr;
                return false;
            }
            counters.buffer = raw;
            counters.mapped = info.pMappedData;
            std::memset(counters.mapped, 0, BufferBytes);
            return true;
        };
        if (bed_observer && !allocate(BedObserver::AllocBytes)) {
            std::puts("[sewer-bed-t196] event=unavailable reason=counter-tail-allocation");
            bed_observer.reset();
        }
        made = bed_observer || allocate(BufferBytes);
    }
    world_env_set = EnvSet("BB_CAUSTICS_WORLD"); // r130e
    if (made && knobs.world > 0.0f && knobs.lamp_strength > 0.0f) {
        MakeWorldMap(); // r107f, from the variable (r130e: the body is in MakeWorldMap)
    }
    std::printf("Water caustics (r107b, BB_CAUSTICS=%s%.2f, LAMPS=%.2f): %s; gain %.2f, lamps %.2f, "
                "test view %s; the light of the sun or moon (where the light set has it) and of up "
                "to %u lamps a water plane reflects (the game's mirrored passes), as a moving net\n",
                knobs.show ? "show, " : "", double(knobs.strength), double(knobs.lamp_strength),
                made ? "on" : "off - the pass could not be made", double(BC::GainOf(knobs)),
                double(BC::LampGainOf(knobs)), knobs.show ? "on" : "off", BC::MaxLamps);
    if (knobs.world > 0.0f) {
        std::printf("Water caustics (r107f, BB_CAUSTICS_WORLD=%.2f): %s; a world map of what the water is "
                    "(%u x %u cells of %.2f m, %u KB), the lamps kept from pass to pass, the lamps' light "
                    "on the bed under a mirrored plane's water, puddles that ripple\n",
                    double(knobs.world),
                    world_map.buffer ? "on"
                                     : "off - it needs BB_CAUSTICS_LAMPS and the pass made, and the map did not fit",
                    unsigned(CAUSTICS_MAP_SIZE), unsigned(CAUSTICS_MAP_SIZE), 1.0 / CAUSTICS_MAP_CELLS_PER_M,
                    unsigned(WorldBytes / 1024));
    }
    if (!upscaler_on) {
        std::printf("Water caustics (r107): not drawn - the upscaler is not available (BB_UPSCALER=none, "
                    "or this GPU cannot run it), and the pass runs at its first blended draw\n");
    }
}

// bbport (r107f_caustics-world-anchored), moved here by r130e_sewer-water-moves: the world map, device local; the first dispatch that
// uses it clears it. Without it the knob does nothing (the log says so). Tried once.
bool Caustics::MakeWorldMap() {
    world_tried = true;
    if (!made || world_map.buffer) {
        return bool(world_map.buffer);
    }
    const VkBufferCreateInfo map_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = WorldBytes,
        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
    };
    VmaAllocationCreateInfo map_alloc{};
    map_alloc.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE;
    VkBuffer map_raw{};
    if (vmaCreateBuffer(instance.GetAllocator(), &map_ci, &map_alloc, &map_raw, &world_map.allocation, nullptr) == VK_SUCCESS) {
        world_map.buffer = map_raw;
    }
    return bool(world_map.buffer);
}

// bbport (r130e_sewer-water-moves): the copy of the water's colours: RGBA16F, the scene's size (8 B a pixel), storage and clear use,
// device local, in General; made at the first warp and remade on a size change (the old one goes when the GPU is done with it).
// False: no room or no storage use of the format (the warp is off, r130b's shimmer still runs).
bool Caustics::EnsureWarpImage(u32 width, u32 height) {
    if (warp.image && warp.width == width && warp.height == height) {
        return true;
    }
    if (warp.image) {
        scheduler.DeferOperation([image = std::move(warp.image), view = std::move(warp.view)]() mutable {
            view.reset();
            image.Destroy();
        });
    }
    warp.width = warp.height = 0;
    warp.cleared = false;
    if (!EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) || !EffectPass::HasRoom(instance, 8ull * width * height)) {
        return false;
    }
    const auto device = instance.GetDevice();
    const vk::ImageCreateInfo image_ci{
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eTransferDst,
        .initialLayout = vk::ImageLayout::eUndefined,
    };
    warp.image = VideoCore::UniqueImage(device, instance.GetAllocator());
    warp.image.Create(image_ci);
    SetObjectName(device, vk::Image(warp.image), "Water warp copy");
    warp.view = Check<"create water warp copy view">(device.createImageViewUnique({
        .image = vk::Image(warp.image),
        .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .subresourceRange = WarpLevel,
    }));
    warp.width = width;
    warp.height = height;
    return true;
}

Caustics::~Caustics() {
    wetness_probe.reset();
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    if (world_map.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), world_map.buffer, world_map.allocation); // r107f
    }
    if (bed_observer && bed_observer->scheduled) {
        // The tap callback reads this same mapped allocation after its tick. Retire it in queue
        // order as t187 does, including any ordinary caustics recorded after the observed frame.
        scheduler.DeferOperation([allocator = instance.GetAllocator(), buffer = counters.buffer,
                                  allocation = counters.allocation,
                                  observer_pipeline = std::move(bed_observer->pipeline)]() mutable {
            observer_pipeline.reset();
            vmaDestroyBuffer(allocator, buffer, allocation);
        }, "sewer bed observer buffer");
    } else if (counters.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), counters.buffer, counters.allocation);
    }
}

void Caustics::NativeBedPass::Ground() {
    stage = stage == NativeBedStage::Empty ? NativeBedStage::Ground : NativeBedStage::Closed;
}

void Caustics::NativeBedPass::Copied() {
    stage = stage == NativeBedStage::Ground ? NativeBedStage::Copy : NativeBedStage::Closed;
}

void Caustics::NativeBedPass::Water() {
    if (stage != NativeBedStage::Water) {
        stage = stage == NativeBedStage::Copy ? NativeBedStage::Water : NativeBedStage::Closed;
    }
}

Caustics::NativeBedImage Caustics::NativeBedImage::Of(VideoCore::ImageId id,
                                                     const VideoCore::Image& image) {
    return {id, image.image_uid, image.backing ? image.GetImage() : vk::Image{},
            image.backing, image.guest_begin, image.guest_end};
}

struct Caustics::JoinedBedBind {
    enum Gate : unsigned {
        WaterStage, Current, PlaneRange, EyeAbove, Extent, GBufferDepth, Camera, DepthView,
        AlbedoView, AlbedoPresent, ColorFits, DepthFits, AlbedoFits, DepthIdentity, AlbedoIdentity,
        WaterWrite, DepthSampled, AlbedoSampled, CopyRegistered, CopyFits, CopyIdentity, CopyWrite,
        DownloadSafe, CopyBegin, CopyRange, TrackBegin, TrackEnd, CopyBytes, CopyFormat,
        CopyAspect, CopySampled, BackingFormat, BackingSampled, WholeBacking, Layout,
        ColorIdDistinct, DepthIdDistinct, AlbedoIdDistinct, ColorDisjoint, DepthDisjoint,
        AlbedoDisjoint, NoCacheOverlap,
    };
    static_assert(NoCacheOverlap < 64);
    std::string stamp, before;
    std::string color = "?", depth = "?", albedo = "?", candidate = "?";
    u64 tested = 0, passed = 0;
    bool attempted = false, reported = false;
    u32 width = 0, height = 0;
    vk::ImageView depth_view{}, albedo_view{};

    bool Check(Gate gate, bool pass) {
        const u64 bit = u64{1} << gate;
        tested |= bit;
        if (pass) passed |= bit;
        return pass;
    }

    static std::string Describe(VideoCore::ImageId id, const VideoCore::Image* image) {
        if (!image) return "?";
        const auto base = fmt::format("{}/{}/{:x}/{:x},{},{},{},{},{},{:x},{},{},"
                                      "{:x},{:x},{:x},{:x},{:x},{}",
                                      id.index, image->image_uid,
                                      image->backing ? std::bit_cast<u64>(VkImage(image->GetImage())) : 0u,
                                      reinterpret_cast<std::uintptr_t>(image->backing), image->write_seq,
                                      u32(image->info.pixel_format), image->info.size.width,
                                      image->info.size.height, image->info.num_samples,
                                      u32(VkImageUsageFlags(image->usage_flags)),
                                      int(image->binding.needs_rebind), int(image->scene_proxy),
                                      image->guest_begin, image->guest_end,
                                      image->info.stencil_addr, image->info.stencil_size,
                                      image->track_addr, image->track_addr_end);
        if (!image->backing) return base + ",?";
        const auto& backing = *image->backing;
        const auto& ci = backing.image.image_ci;
        return fmt::format("{},{},{},{},{},{},{},{:x},{},{},{:x},{:x},{}",
                           base, u32(ci.format), ci.extent.width, ci.extent.height, ci.extent.depth,
                           u32(ci.samples), ci.mipLevels, u32(VkImageUsageFlags(ci.usage)),
                           ci.arrayLayers, u32(ci.imageType),
                           reinterpret_cast<std::uintptr_t>(backing.image.allocation),
                           u32(VkImageAspectFlags(image->aspect_mask)),
                           fmt::format("{}/{}", u32(backing.state.layout), backing.subresource_states.size()));
    }

    void Report(const NativeBedPass& pass, const char* reason, u64 tick, bool plane_found, float plane,
                bool lamp_draw, u32 lamps, bool reduced, float eye, vk::ImageView selected,
                vk::ImageView fallback) {
        if (std::exchange(reported, true)) return;
        const auto identity = [](const NativeBedImage& image) {
            return fmt::format("{}/{}/{:x}/{:x}", image.id.index, image.uid,
                               std::bit_cast<u64>(VkImage(image.handle)),
                               reinterpret_cast<std::uintptr_t>(image.backing));
        };
        std::printf("[sewer-joined-t202] event=consumer %s tick=%llu status=%s pre=%s "
                    "returned=%u entered=%u tested=%llx passed=%llx extent=%ux%u plane_found=%u "
                    "plane=%08x eye=%08x tracked_eye=%08x lamp_draw=%u lamps=%u reduced=%u "
                    "depth_view=%llx cb2_view=%llx selected9=%llx fallback9=%llx "
                    "expected_depth=%s expected_cb2=%s expected_copy=%s "
                    "expected_writes=%llu,%llu,%llu copy_bytes=%llu "
                    "color=%s depth_image=%s cb2=%s candidate=%s\n",
                    stamp.c_str(), static_cast<unsigned long long>(tick), reason, before.c_str(),
                    u32(pass.stage), unsigned(attempted), static_cast<unsigned long long>(tested),
                    static_cast<unsigned long long>(passed), width, height, unsigned(plane_found),
                    std::bit_cast<u32>(plane), std::bit_cast<u32>(eye),
                    std::bit_cast<u32>(pass.inv_view[7]), unsigned(lamp_draw), lamps, unsigned(reduced),
                    static_cast<unsigned long long>(std::bit_cast<u64>(VkImageView(depth_view))),
                    static_cast<unsigned long long>(std::bit_cast<u64>(VkImageView(albedo_view))),
                    static_cast<unsigned long long>(std::bit_cast<u64>(VkImageView(selected))),
                    static_cast<unsigned long long>(std::bit_cast<u64>(VkImageView(fallback))),
                    identity(pass.depth).c_str(), identity(pass.albedo).c_str(), identity(pass.copy).c_str(),
                    static_cast<unsigned long long>(pass.copy_write),
                    static_cast<unsigned long long>(pass.copied_source_write),
                    static_cast<unsigned long long>(pass.water_write),
                    static_cast<unsigned long long>(pass.copy_bytes),
                    color.c_str(), depth.c_str(), albedo.c_str(), candidate.c_str());
    }
};

std::string Caustics::JoinedBedStamp() const {
    return fmt::format("frame={} scene={} pass={} expected_depth={}", bed_trace.frame, bed_trace.scene,
                       bed_trace.pass, bed_trace.depth.index);
}

std::string Caustics::JoinedBedState() const {
    const auto camera = camera_motion.PassMatrices();
    const auto jitter = camera_motion.Jitter();
    const bool tracked_camera = native_bed.depth.id && camera.valid;
    const auto camera_compare = tracked_camera ?
        fmt::format("/{},{},{},{}", camera.view == native_bed.view,
                    camera.inv_view == native_bed.inv_view, camera.proj == native_bed.proj,
                    jitter == native_bed.jitter) : "/?,?,?,?";
    return fmt::format("{},{},{:x},{:x},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},"
                       "{:08x},{:08x},{:08x},{:08x},{:08x},{:08x},{:08x},{}/"
                       "{},{},{},{},{},{},{},{},{}{}",
                       armed, native_bed_enabled, std::bit_cast<u32>(knobs.world),
                       std::bit_cast<u32>(knobs.lamp_strength), made, bool(world_map.buffer),
                       BbEngine::Loading::ScreenUp(), BbEngine::Loading::Generation(),
                       scene_targets.Generation(), camera_motion.Depth().index, gbuffer_depth.index,
                       gbuffer_albedo.index, native_bed_pass_serial, u32(native_bed.stage),
                       native_bed.serial, native_bed.frame, native_bed.loading, native_bed.generation,
                       native_bed.depth.id.index, native_bed.albedo.id.index,
                       std::bit_cast<u32>(jitter[0]), std::bit_cast<u32>(jitter[1]),
                       std::bit_cast<u32>(camera.proj[0]), std::bit_cast<u32>(camera.proj[1]),
                       std::bit_cast<u32>(camera.proj[2]), std::bit_cast<u32>(camera.proj[3]),
                       std::bit_cast<u32>(camera.inv_view[7]), camera.valid,
                       native_bed.depth.uid, native_bed.albedo.uid, native_bed.copy.id.index,
                       native_bed.copy.uid, native_bed.copy_write, native_bed.copied_source_write,
                       native_bed.water_write, native_bed.extent.width, native_bed.extent.height,
                       camera_compare);
}


void Caustics::StartNativeBedTrace(u64 frame, u64 scene, u32 pass, VideoCore::ImageId depth) {
    static const bool enabled = [] {
        const char* mode = std::getenv("BB_SEWER_FIRST_GATE");
        return mode && std::strcmp(mode, "1") == 0;
    }();
    if (!enabled || bed_trace.used) return;
    static const bool joined_enabled = [] {
        const char* mode = std::getenv("BB_SEWER_JOINED_GATES");
        return mode && std::strcmp(mode, "1") == 0;
    }();
    bed_trace = {.active = true, .used = true, .frame = frame, .scene = scene,
                 .pass = pass, .depth = depth, .joined_enabled = joined_enabled};
    NativeBedTraceEvent("start", "ground", "t180-before");
}

bool Caustics::ClaimNativeBedDrawTrace(bool ground) noexcept {
    return !std::exchange(ground ? bed_trace.draw_ground : bed_trace.draw_water, true);
}

void Caustics::NativeBedTraceEvent(const char* event, const char* path, const char* detail) const {
    if (!bed_trace.active || bed_trace.rows >= 18) return;
    ++bed_trace.rows;
    std::printf("[sewer-first-gate-t200] event=%s path=%s detail=%s frame=%llu scene=%llu pass=%u "
                "tick=%llu expected_depth=%u tracker_depth=%u tracker_stage=%u "
                "tracker_frame=%llu tracker_serial=%llu serial=%llu\n",
                event, path, detail, static_cast<unsigned long long>(bed_trace.frame),
                static_cast<unsigned long long>(bed_trace.scene), bed_trace.pass,
                static_cast<unsigned long long>(scheduler.CurrentTick()), bed_trace.depth.index,
                native_bed.depth.id.index, u32(native_bed.stage),
                static_cast<unsigned long long>(native_bed.frame),
                static_cast<unsigned long long>(native_bed.serial),
                static_cast<unsigned long long>(native_bed_pass_serial));
}

bool Caustics::NativeBedTraceGate(bool accepted, const char* path, const char* predicate) const {
    if (!accepted && path && bed_trace.active) {
        if (!bed_trace.first_failure) {
            bed_trace.first_path = path;
            bed_trace.first_failure = predicate;
        }
        NativeBedTraceEvent("refused", path, predicate);
    }
    return accepted;
}

bool Caustics::TraceNativeBedWanted(const char* path) const {
    if (!path || !bed_trace.active) return NativeBedWanted();
    return NativeBedTraceGate(native_bed_enabled, path, "startup-native-bed-off") &&
           NativeBedTraceGate(made, path, "ordinary-pipeline-unavailable") &&
           NativeBedTraceGate(knobs.world > 0.0f, path, "world-strength-off") &&
           NativeBedTraceGate(LampsWanted(), path, "lamps-strength-off") &&
           NativeBedTraceGate(bool(world_map.buffer), path, "world-map-unavailable");
}

void Caustics::NativeBedTraceClose(const char* path, const char* detail) const {
    if (bed_trace.active && !bed_trace.first_reset) {
        bed_trace.first_reset = true;
        NativeBedTraceEvent("first-close-or-reset", path, detail);
    }
}

void Caustics::FinishNativeBedTrace(bool joined, VideoCore::ImageId depth, NativeBedStage returned) {
    if (!bed_trace.active) return;
    bed_trace.active = false;
    std::printf("[sewer-first-gate-t200] event=end frame=%llu scene=%llu pass=%u tick=%llu "
                "joined=%u expected_depth=%u effect_depth=%u returned_stage=%u rows=%u "
                "first_path=%s first_failure=%s\n",
                static_cast<unsigned long long>(bed_trace.frame),
                static_cast<unsigned long long>(bed_trace.scene), bed_trace.pass,
                static_cast<unsigned long long>(scheduler.CurrentTick()), unsigned(joined),
                bed_trace.depth.index, depth.index, u32(returned), bed_trace.rows,
                bed_trace.first_path ? bed_trace.first_path : "none",
                bed_trace.first_failure ? bed_trace.first_failure : "none");
}

struct Caustics::SewerReducedReceipt {
    static constexpr vk::Extent3D ProxyExtent{1920, 1080, 1};
    static constexpr vk::Extent3D NativeExtent{3840, 2160, 1};
    static constexpr std::array<std::array<float, 3>, 3> Anchors{{
        {17.39343f, -29.98707f, 104.08517f},
        {16.77602f, -29.93734f, 105.27851f},
        {16.67675f, -29.00756f, 101.85579f},
    }};
    std::array<vk::Offset2D, Anchors.size()> points{};
    std::shared_ptr<SewerMotion::Checkpoint> motion;
    static constexpr unsigned Bytes = 88;
    static constexpr unsigned CornerBytes = 48;
    static constexpr unsigned FinalCorners = Bytes + CornerBytes;
    static constexpr unsigned HdrBase = FinalCorners + CornerBytes;
    static constexpr unsigned AlternateBytes = HdrBase + 72;
    static_assert(AlternateBytes == 256);
    // Coordinates and scoped frame-end admission retained separately from the draw state.
    std::shared_ptr<SewerMotion::Alternate::Proof> alternate;
    enum Stage { Waiting, Ground, CopyPending, Copy, Water };

    VmaAllocator allocator{};
    VmaAllocation allocation{};
    VkBuffer buffer{};
    const std::byte* mapped{};
    Stage stage{Waiting};
    u32 frame{};
    u64 scene{}, loading{}, generation{}, ground_tick{}, copy_tick{}, water_tick{};
    NativeBedImage depth{}, cb2{}, destination{};
    vk::Image depth_proxy{}, cb2_proxy{};
    vk::ImageView ground_view{}, ground_cb2_view{}, water_view{}, sampled_view{}, written_view{};
    u64 previous_write{}, copy_write{};
    CameraMotion::Matrices camera{};
    std::array<float, 2> jitter{};

    ~SewerReducedReceipt() {
        if (buffer) vmaDestroyBuffer(allocator, buffer, allocation);
    }

    bool RegisterPoints(const CameraMotion::Matrices& camera, std::array<float, 2> draw_jitter) {
        for (u32 i = 0; i < Anchors.size(); ++i) {
            const auto& world = Anchors[i];
            const auto view_axis = [&](u32 row) {
                const float* m = camera.view.data() + 4 * row;
                return m[0] * world[0] + m[1] * world[1] + m[2] * world[2] + m[3];
            };
            const float z = view_axis(2);
            if (!std::isfinite(z) || z <= 0.1f || z > 45.f) return false;
            const float px = (view_axis(0) * camera.proj[0] / z + 1.f) * 960.f + draw_jitter[0];
            const float py = (view_axis(1) * camera.proj[1] / z + 1.f) * 540.f + draw_jitter[1];
            if (!std::isfinite(px) || !std::isfinite(py) || px < 1.f || px >= 1919.f ||
                py < 1.f || py >= 1079.f) return false;
            points[i] = {static_cast<s32>(px), static_cast<s32>(py)};
        }
        return points[0] != points[1] && points[0] != points[2] && points[1] != points[2];
    }

    bool Allocate(VmaAllocator vma) {
        allocator = vma;
        const VkBufferCreateInfo ci{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = alternate ? AlternateBytes : Bytes,
                                    .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
        const VmaAllocationCreateInfo ai{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO,
        };
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(vma, &ci, &ai, &buffer, &allocation, &info) != VK_SUCCESS) return false;
        mapped = static_cast<const std::byte*>(info.pMappedData);
        return mapped != nullptr;
    }

    void CopyTaps(Scheduler& scheduler, vk::Image image, vk::ImageLayout layout,
                  vk::ImageAspectFlags image_aspects, vk::ImageAspectFlagBits copy_aspect,
                  u32 offset, u32 texel_bytes, bool mapped_native = false,
                  u32 corners_offset = 0) const {
        const auto alt = corners_offset ? alternate : nullptr;
        scheduler.Record([=, taps = points, out = vk::Buffer{buffer}](vk::CommandBuffer cmd) {
            constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
            constexpr auto TransferRead = vk::AccessFlagBits2::eTransferRead;
            constexpr auto TransferLayout = vk::ImageLayout::eTransferSrcOptimal;
            const vk::ImageMemoryBarrier2 before{
                .srcStageMask = AllCommands, .srcAccessMask = MemoryAll,
                .dstStageMask = Transfer, .dstAccessMask = TransferRead,
                .oldLayout = layout, .newLayout = TransferLayout,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = image, .subresourceRange = {image_aspects, 0, 1, 0, 1},
            };
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &before});
            std::array<vk::BufferImageCopy, 15> regions{};
            for (u32 i = 0; i < Anchors.size(); ++i) {
                const auto [x, y] = taps[i];
                regions[i] = {
                    .bufferOffset = offset + i * texel_bytes,
                    .imageSubresource = {copy_aspect, 0, 0, 1},
                    .imageOffset = {mapped_native ? 2 * x + 1 : x, mapped_native ? 2 * y + 1 : y, 0},
                    .imageExtent = {1, 1, 1},
                };
            }
            u32 count = u32(Anchors.size());
            if (alt) {
                for (const auto& group : alt->cells) {
                    for (u32 j = 1; j < group.size(); ++j) {
                        const auto [x, y] = group[j];
                        const u32 index = count++;
                        regions[index] = {
                            .bufferOffset = corners_offset + (index - Anchors.size()) * sizeof(u32),
                            .imageSubresource = {copy_aspect, 0, 1, 1},
                            .imageOffset = {x, y, 0},
                            .imageExtent = {1, 1, 1},
                        };
                    }
                }
            }
            cmd.copyImageToBuffer(image, TransferLayout, out, std::span(regions).first(count));
            auto after = before;
            after.srcStageMask = Transfer;
            after.srcAccessMask = TransferRead;
            after.dstStageMask = AllCommands;
            after.dstAccessMask = MemoryAll;
            after.oldLayout = TransferLayout;
            after.newLayout = layout;
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &after});
        });
    }

    u32 Word(u32 offset) const {
        u32 word;
        std::memcpy(&word, mapped + offset, sizeof(word));
        return word;
    }

    bool Report() const {
        if (vmaInvalidateAllocation(allocator, allocation, 0, Bytes) != VK_SUCCESS) {
            fmt::print("[sewer-reduced] event=refused why=host-invalidate frame={}\n", frame);
            return false;
        }
        for (u32 i = 0; i < Anchors.size(); ++i) {
            const auto [x, y] = points[i];
            fmt::print("[sewer-reduced] event=tap frame={} point={} p={},{} q={},{} "
                       "before_depth={:08x} before_cb2={:08x} r32f={:08x} final_depth={:08x} "
                       "final_cb2={:08x} hdr_raw={:08x},{:08x}\n",
                       frame, i, x, y, 2 * x + 1, 2 * y + 1, Word(4 * i), Word(12 + 4 * i),
                       Word(24 + 4 * i), Word(36 + 4 * i), Word(48 + 4 * i),
                       Word(64 + 8 * i), Word(68 + 8 * i));
        }
        fmt::print("[sewer-reduced] event=fenced frame={} bytes={} taps={}\n", frame, Bytes, Anchors.size());
        return true;
    }

    void ReportAlternate(float plane) {
        using namespace SewerMotion::Alternate;
        if (vmaInvalidateAllocation(allocator, allocation, 0, AlternateBytes) != VK_SUCCESS) {
            return alternate->Refuse("host-invalidate");
        }
        Depth before{}, after{};
        std::array<u32, 3> native{};
        std::array<SewerMotion::Samples, 3> hdr{};
        for (u32 i = 0; i < points.size(); ++i) {
            before[i][0] = Word(4 * i);
            after[i][0] = Word(36 + 4 * i);
            native[i] = Word(24 + 4 * i);
            for (u32 j = 1; j < before[i].size(); ++j) {
                const u32 o = 4 * (4 * i + j - 1);
                before[i][j] = Word(Bytes + o);
                after[i][j] = Word(FinalCorners + o);
            }
            for (u32 j = 0; j < hdr.size(); ++j) {
                std::memcpy(hdr[j][i].data(), mapped + HdrBase + 8 * (3 * j + i), 8);
            }
            for (u32 j = 0; j < before[i].size(); ++j) {
                const auto [x, y] = alternate->cells[i][j];
                fmt::print("[sewer-alt-support] event=depth frame={} scene={} point={} cell={} p={},{} "
                           "ground={:08x} final={:08x}\n", frame, scene, i, j, x, y, before[i][j], after[i][j]);
            }
            const auto [x, y] = points[i];
            fmt::print("[sewer-alt-support] event=center frame={} scene={} point={} p={},{} q={},{} "
                       "r32f={:08x}\n", frame, scene, i, x, y, 2*x+1, 2*y+1, native[i]);
            for (u32 j = 0; j < hdr.size(); ++j) {
                const auto& sample = hdr[j][i];
                fmt::print("[sewer-alt-support] event=hdr frame={} scene={} point={} sample={} "
                           "rgba={:04x},{:04x},{:04x},{:04x}\n",
                           frame, scene, i, j, sample[0], sample[1], sample[2], sample[3]);
            }
        }
        if (const char* why = DepthVerdict(before, after, native, alternate->cells, camera, jitter, plane)) {
            return alternate->Refuse(why);
        }
        if (const char* why = HdrVerdict(hdr)) return alternate->Refuse(why);
        alternate->fenced.store(true);
        alternate->Finish();
    }

    static bool SourceFits(const SceneTargets::SewerProxy& proxy, bool depth) {
        const auto format = proxy.format;
        const bool kind = depth ? (format == vk::Format::eD32Sfloat || format == vk::Format::eD32SfloatS8Uint)
                                : format == vk::Format::eR8G8B8A8Srgb;
        return proxy.valid && proxy.dirty && proxy.target.image && proxy.extent == ProxyExtent && kind;
    }
};

static u64 SewerMotionNonce() {
    const char* request = nullptr;
#if __has_include("bbport_live_knobs.h")
    const auto held = BbLiveKnobs::Lookup("BB_SEWER_MOTION_REQUEST");
    request = held.Get();
#else
    request = std::getenv("BB_SEWER_MOTION_REQUEST");
#endif
    if (!request) return 0;
    u64 number{};
    const char* end = request + std::strlen(request);
    const auto parsed = std::from_chars(request, end, number);
    return parsed.ec == std::errc{} && parsed.ptr == end ? number : 0;
}

void Caustics::RefreshSewerMotion() {
    if (!sewer_motion->Active()) return;
    if (BbEngine::Loading::ScreenUp() || BbEngine::Loading::Generation() != sewer_motion->loading ||
        scene_targets.Generation() != sewer_motion->generation || !scene_targets.Reduced() ||
        SewerMotionNonce() != sewer_motion->request) {
        sewer_motion->Stop("request-loading-or-scene-generation-changed");
        if (sewer_reduced && sewer_reduced->motion) SewerReducedRefused("motion-request-invalidated");
        return;
    }
    sewer_motion->Poll(BbStats::frame_number.load(std::memory_order_relaxed));
}

bool Caustics::SewerReducedArmed(bool ground) {
    if (SewerMotion::Enabled() && !sewer_reduced_master) {
        if (sewer_motion) {
            RefreshSewerMotion();
            return sewer_motion->Active() && (ground || bool(sewer_reduced));
        }
        if (!ground || BbEngine::Loading::ScreenUp()) return false;
        const auto request = SewerMotionNonce();
        if (!request) return false;
        const auto frame = BbStats::frame_number.load(std::memory_order_relaxed);
        sewer_motion = std::make_unique<SewerMotion::Series>(
            request, BbEngine::Loading::Generation(), scene_targets.Generation(), frame,
            native_bed_enabled);
        if (!bed_observer) {
            sewer_motion->Stop("bed-observer-pipeline-or-tail");
            return false;
        }
        return true;
    }
    if (SewerMotion::Alternate::Enabled() && !sewer_reduced_master && !native_bed_enabled &&
        !BbEngine::Loading::ScreenUp()) {
        return sewer_reduced || (ground && !SewerMotion::Alternate::pending && BbTestCamera::HoldWanted());
    }
    if (!sewer_reduced_master || sewer_reduced_claimed || BbEngine::Loading::ScreenUp()) return false;
    if (sewer_reduced) return true;
    if (!ground) return false;
    const char* request = nullptr;
#if __has_include("bbport_live_knobs.h")
    const auto value = BbLiveKnobs::Lookup("BB_SEWER_REDUCED_REQUEST");
    request = value.Get();
#else
    request = std::getenv("BB_SEWER_REDUCED_REQUEST");
#endif
    if (!request || std::string_view(request) != "1") return false;
    sewer_reduced = std::make_shared<SewerReducedReceipt>();
    return true;
}

void Caustics::SewerReducedRefused(const char* reason) {
    if (!sewer_reduced) return;
    if (sewer_reduced->motion) sewer_reduced->motion->Refuse(reason);
    else if (sewer_reduced->alternate) sewer_reduced->alternate->Refuse(reason);
    else sewer_reduced_claimed = true;
    fmt::print("[sewer-reduced] event=refused why={} frame={} scene={} stage={}\n", reason,
               sewer_reduced->frame, sewer_reduced->scene, unsigned(sewer_reduced->stage));
    auto receipt = std::exchange(sewer_reduced, {});
    if (receipt->buffer) {
        scheduler.DeferOperation([receipt = std::move(receipt)] {}, "sewer reduced refused disposal");
    }
}

void Caustics::CloseReducedBed(const char* reason) {
    native_bed.reduced = true;
    native_bed.stage = NativeBedStage::Closed;
    if (!reduced_bed_refusal) reduced_bed_refusal = reason;
}

void Caustics::RefuseReducedBedDraw(bool product, const char* reason) {
    if (product) CloseReducedBed(reason);
    SewerReducedRefused(reason);
}

void Caustics::SewerReducedDraw(bool ground, bool product, u64 scene, VideoCore::ImageId depth_id,
                               vk::ImageView depth_view, VideoCore::ImageId cb2_id,
                               vk::ImageView cb2_view, std::array<float, 2> jitter) {
    using R = SewerReducedReceipt;
    // An armed request can see the tail of a preceding frame first.
    if (product && (native_bed.stage == NativeBedStage::Closed ||
                    BbEngine::Loading::ScreenUp() ||
                    (!ground && native_bed.stage == NativeBedStage::Empty))) product = false;
    const bool motion_ground = ground && sewer_motion && sewer_motion->Active();
    const auto frame = BbStats::frame_number.load(std::memory_order_relaxed);
    const auto camera = camera_motion.PassMatrices();
    if (motion_ground && !sewer_reduced) {
        if (auto selected = sewer_motion->Observe({scene, frame, camera, {}})) {
            sewer_reduced = std::make_shared<R>();
            sewer_reduced->motion = std::move(selected);
        }
    }
    namespace Alt = SewerMotion::Alternate;
    if (ground && !product && !sewer_reduced && !sewer_reduced_master && !native_bed_enabled &&
        Alt::Enabled() && !Alt::pending && scene > 0 && !BbEngine::Loading::ScreenUp()) {
        // Previous READY only bounds optional diagnostic work. Exact current READY is joined after R120 Tick.
        BbTestCamera::SewerEpochReceipt prior;
        if (BbTestCamera::ReadSewerEpoch(scene - 1, prior)) {
            auto proof = std::make_shared<Alt::Proof>();
            proof->key = {.scene = scene, .loading = BbEngine::Loading::Generation(),
                          .generation = scene_targets.Generation(), .frame = frame};
            proof->camera = camera;
            proof->jitter = jitter;
            proof->original = prior.original.epoch;
            proof->alternate = prior.alternate.epoch;
            Alt::pending = proof;
            if (!BbEngine::world_player_position(proof->hunter.data()) ||
                !(SewerMotion::Distance(proof->hunter, prior.hunter) <= .01f) ||
                !Alt::Register(camera, jitter, proof->cells)) {
                return proof->Refuse("ground-camera-hunter-or-footprint");
            }
            sewer_reduced = std::make_shared<R>();
            sewer_reduced->alternate = std::move(proof);
        }
    }
    const bool observe = sewer_reduced && (ground || sewer_reduced->stage != R::Waiting);
    if (!product && !observe) return;
    const auto* depth = texture_cache.TryGetImage(depth_id, 0);
    const auto proxy = depth ? scene_targets.InspectSewerProxy(depth_id, depth->image_uid, depth_view)
                             : SceneTargets::SewerProxy{};
    if (!depth_view || !camera.valid || camera_motion.Depth() != depth_id ||
        !R::SourceFits(proxy, true) || proxy.target.layout != vk::ImageLayout::eDepthStencilAttachmentOptimal) {
        return RefuseReducedBedDraw(product, "draw-camera-or-actual-d32-proxy");
    }
    if (!ground) {
        if (product) {
            auto& pass = native_bed;
            if (pass.stage == NativeBedStage::Copy && pass.reduced && CurrentNativeBed(pass) &&
                NativeBedCamera(pass, jitter) && pass.scene == scene &&
                pass.depth == NativeBedImage::Of(depth_id, *depth) && pass.depth_proxy == proxy.target.image) {
                pass.stage = NativeBedStage::Water;
            } else {
                CloseReducedBed("product-water-order-camera-or-depth-proxy");
            }
        }
        if (!observe) return;
        auto& r = *sewer_reduced;
        if (r.stage != R::Copy || r.frame != frame || r.scene != scene || r.jitter != jitter ||
            r.loading != BbEngine::Loading::Generation() || r.generation != scene_targets.Generation() ||
            r.depth != NativeBedImage::Of(depth_id, *depth) || r.depth_proxy != proxy.target.image ||
            r.camera.proj != camera.proj || r.camera.inv_view != camera.inv_view || r.camera.view != camera.view) {
            return SewerReducedRefused("water-order-or-camera-proxy-changed");
        }
        r.stage = R::Water;
        r.water_view = depth_view;
        r.water_tick = scheduler.CurrentTick();
        fmt::print("[sewer-reduced] event=water frame={} scene={} tick={} uid={} image={:x} view={:x}\n",
                   frame, scene, r.water_tick, r.depth.uid, std::bit_cast<u64>(VkImage(r.depth_proxy)),
                   std::bit_cast<u64>(VkImageView(r.water_view)));
        return;
    }
    const auto* cb2 = texture_cache.TryGetImage(cb2_id, 0);
    const auto albedo = cb2 ? scene_targets.InspectSewerProxy(cb2_id, cb2->image_uid, cb2_view)
                            : SceneTargets::SewerProxy{};
    if (!cb2_view || !R::SourceFits(albedo, false) ||
        albedo.target.layout != vk::ImageLayout::eColorAttachmentOptimal) {
        return RefuseReducedBedDraw(product, "draw-ground-actual-cb2-proxy");
    }
    if (product) {
        BC::Push geometry{};
        geometry.proj = camera.proj;
        geometry.inv_view = camera.inv_view;
        geometry.frame = {float(R::ProxyExtent.width), float(R::ProxyExtent.height), jitter[0], jitter[1]};
        if (native_bed.stage != NativeBedStage::Empty) {
            CloseReducedBed("product-duplicate-ground");
        } else if (!armed || depth_id != gbuffer_depth || cb2_id != gbuffer_albedo ||
                   proxy.target.image == albedo.target.image ||
                   !WP::ProjectionValid(geometry, camera.view)) {
            CloseReducedBed("product-ground-pass-proxy-or-projection");
        } else {
            native_bed = {
                .stage = NativeBedStage::Ground, .reduced = true, .serial = native_bed_pass_serial,
                .frame = frame, .loading = BbEngine::Loading::Generation(),
                .generation = scene_targets.Generation(),
                .depth = NativeBedImage::Of(depth_id, *depth), .albedo = NativeBedImage::Of(cb2_id, *cb2),
                .extent = {R::ProxyExtent.width, R::ProxyExtent.height}, .scene = scene,
                .depth_proxy = proxy.target.image, .albedo_proxy = albedo.target.image,
                .ground_view = depth_view, .ground_albedo_view = cb2_view,
                .proj = camera.proj, .view = camera.view, .inv_view = camera.inv_view, .jitter = jitter,
            };
        }
    }
    if (!observe) return;
    auto& r = *sewer_reduced;
    if (r.stage != R::Waiting) return SewerReducedRefused("duplicate-ground-or-actual-cb2-proxy");
    if (!r.motion && !r.alternate) {
    // Match the retained native waypoint pose before allocating any readback work.
    // The retained one-walk and two-walk routes bound this held sewer fixture.
    constexpr std::array eye_min{13.49f, -27.38f, 108.08f};
    constexpr std::array eye_max{13.84f, -27.20f, 108.56f};
    constexpr std::array reference_direction{0.51247f, -0.33134f, -0.79221f};
    for (u32 i = 0; i < 3; ++i) {
        if (!std::isfinite(camera.inv_view[i * 4 + 2]) ||
            std::abs(camera.inv_view[i * 4 + 2] - reference_direction[i]) > 0.025f) {
            return SewerReducedRefused("held-camera-direction");
        }
    }
    if (!std::ranges::all_of(camera.proj, [](float x) { return std::isfinite(x); }) ||
        std::abs(camera.proj[0] - 1.428f) > 0.03f ||
        std::abs(camera.proj[1] + 2.539f) > 0.03f || camera.proj[2] <= 0.f || camera.proj[3] >= 0.f) {
        return SewerReducedRefused("held-camera-projection");
    }
    for (u32 i = 0; i < 3; ++i) {
        const float eye = camera.inv_view[i * 4 + 3];
        if (!std::isfinite(eye) || eye < eye_min[i] || eye > eye_max[i]) {
            return SewerReducedRefused("held-camera-origin");
        }
    }
    }
    if (r.alternate) {
        for (u32 i = 0; i < r.points.size(); ++i) r.points[i] = r.alternate->cells[i][0];
    } else if (!r.RegisterPoints(camera, jitter)) {
        return SewerReducedRefused("same-frame-anchor-projection");
    }
    WorkflowProbeConfig workflow{};
    const auto qpc_ns = WorkflowPresent::Now();
    if (!qpc_ns || !workflow_capture_root_read(&workflow)) {
        return SewerReducedRefused("present-session-unavailable");
    }
    r.stage = R::Ground;
    r.frame = frame;
    r.scene = scene;
    r.loading = BbEngine::Loading::Generation();
    r.generation = scene_targets.Generation();
    r.ground_tick = scheduler.CurrentTick();
    r.depth = NativeBedImage::Of(depth_id, *depth);
    r.cb2 = NativeBedImage::Of(cb2_id, *cb2);
    if (r.alternate) {
        r.alternate->depth_id = depth_id.index;
        r.alternate->depth_uid = r.depth.uid;
    }
    r.depth_proxy = proxy.target.image;
    r.cb2_proxy = albedo.target.image;
    r.ground_view = depth_view;
    r.ground_cb2_view = cb2_view;
    r.camera = camera;
    r.jitter = jitter;
    fmt::print("[sewer-reduced] event=ground anchors={} frame={} scene={} tick={} gen={} loading={} session={} qpc_ns={} "
               "depth={}/{}:{:x}/{:x} cb2={}/{}:{:x}/{:x} jitter={},{}\n",
               r.alternate ? "r821" : "world-v1", frame, scene, r.ground_tick, r.generation, r.loading, workflow.session, qpc_ns,
               r.depth.id.index, r.depth.uid, std::bit_cast<u64>(VkImage(r.depth_proxy)),
               std::bit_cast<u64>(VkImageView(depth_view)), r.cb2.id.index, r.cb2.uid,
               std::bit_cast<u64>(VkImage(r.cb2_proxy)), std::bit_cast<u64>(VkImageView(cb2_view)),
               jitter[0], jitter[1]);
}

void Caustics::TrackReducedBedCopy(VideoCore::ImageId source, const VideoCore::Image& src,
                                    VideoCore::ImageId destination, const VideoCore::Image& dst,
                                    u64 bytes, std::array<float, 2> jitter) {
    auto& pass = native_bed;
    if (!pass.reduced || pass.stage == NativeBedStage::Closed || source != pass.depth.id) return;
    if (pass.stage != NativeBedStage::Ground) return CloseReducedBed("product-copy-out-of-order");
    if (!CurrentNativeBed(pass) || !NativeBedCamera(pass, jitter)) {
        return CloseReducedBed("product-copy-pass-or-camera-changed");
    }
    if (!texture_cache.IsRegisteredImage(source, src.image_uid) ||
        pass.depth != NativeBedImage::Of(source, src)) {
        return CloseReducedBed("product-copy-source-identity");
    }
    // CanCopyDepthProxyToColor already checked the depth format, sample count and usage.
    // Its recorder samples the level zero proxy keyed by this exact source UID.
    const auto proxy = scene_targets.InspectSewerProxy(source, src.image_uid, pass.ground_view);
    const auto cb2 = scene_targets.InspectSewerProxy(pass.albedo.id, pass.albedo.uid,
                                                    pass.ground_albedo_view);
    constexpr auto sampled = vk::ImageUsageFlagBits::eSampled;
    if (!SewerReducedReceipt::SourceFits(proxy, true) ||
        !SewerReducedReceipt::SourceFits(cb2, false) || proxy.target.image != pass.depth_proxy ||
        cb2.target.image != pass.albedo_proxy || !(proxy.target.usage & sampled)) {
        return CloseReducedBed("product-copy-source-proxy-changed");
    }
    const vk::Extent2D extent{2 * pass.extent.width, 2 * pass.extent.height};
    if (!texture_cache.IsRegisteredImage(destination, dst.image_uid) ||
        !NativeBedImageFits(&dst, extent) || dst.info.pixel_format != vk::Format::eR32Sfloat ||
        dst.backing->image.image_ci.format != vk::Format::eR32Sfloat ||
        dst.aspect_mask != vk::ImageAspectFlagBits::eColor ||
        !(dst.usage_flags & sampled) || !(dst.backing->image.image_ci.usage & sampled) ||
        src.info.size.width != extent.width || src.info.size.height != extent.height) {
        return CloseReducedBed("product-copy-destination-registration-format-or-extent");
    }
    if (!dst.guest_begin || dst.guest_begin >= dst.guest_end ||
        dst.track_addr != dst.guest_begin || dst.track_addr_end != dst.guest_end ||
        bytes < dst.guest_end - dst.guest_begin) {
        return CloseReducedBed("product-copy-destination-range");
    }
    if (source == destination || src.GetImage() == dst.GetImage() ||
        src.backing->image.allocation == dst.backing->image.allocation ||
        proxy.target.image == dst.GetImage() || cb2.target.image == dst.GetImage() ||
        src.Overlaps(dst.guest_begin, dst.guest_end - dst.guest_begin) ||
        (src.info.stencil_size && dst.Overlaps(src.info.stencil_addr, src.info.stencil_size))) {
        return CloseReducedBed("product-copy-source-destination-alias");
    }
    pass.copy = NativeBedImage::Of(destination, dst);
    pass.copy_extent = extent;
    pass.copy_bytes = bytes;
    pass.copy_write = dst.write_seq; // Replaced by the completed write's sequence.
    pass.stage = NativeBedStage::CopyPending;
}

bool Caustics::SewerReducedBeforeCopy(VideoCore::ImageId source, const VideoCore::Image& src,
                                     VideoCore::ImageId destination, const VideoCore::Image& dst,
                                     u64 bytes, std::array<float, 2> jitter) {
    TrackReducedBedCopy(source, src, destination, dst, bytes, jitter);
    using R = SewerReducedReceipt;
    if (!sewer_reduced || source != sewer_reduced->depth.id) return false;
    auto& r = *sewer_reduced;
    const auto fail = [&](const char* reason) { SewerReducedRefused(reason); return false; };
    if (r.stage != R::Ground || src.image_uid != r.depth.uid ||
        r.frame != BbStats::frame_number.load(std::memory_order_relaxed) ||
        r.generation != scene_targets.Generation() || r.loading != BbEngine::Loading::Generation() ||
        r.depth != NativeBedImage::Of(source, src) || BbEngine::Loading::ScreenUp()) {
        return fail("copy-duplicate-or-source-identity");
    }
    const auto proxy = scene_targets.InspectSewerProxy(source, src.image_uid, r.ground_view);
    const auto cb2 = scene_targets.InspectSewerProxy(r.cb2.id, r.cb2.uid, r.ground_cb2_view);
    constexpr auto Transfer = vk::ImageUsageFlagBits::eTransferSrc;
    if (!R::SourceFits(proxy, true) || !R::SourceFits(cb2, false) ||
        proxy.target.image != r.depth_proxy || cb2.target.image != r.cb2_proxy ||
        !(proxy.target.usage & Transfer) || !(cb2.target.usage & Transfer)) {
        return fail("pre-copy-proxy-authority-identity-or-transfer");
    }
    const auto& ci = dst.backing->image.image_ci; // CanCopyDepthProxyToColor has already passed.
    if (ci.extent != R::NativeExtent || ci.format != vk::Format::eR32Sfloat ||
        !(ci.usage & Transfer) || !(ci.usage & vk::ImageUsageFlagBits::eSampled) ||
        dst.scene_proxy || scene_targets.Tracks(dst.image_uid) || dst.binding.needs_rebind ||
        !texture_cache.IsRegisteredImage(destination, dst.image_uid)) {
        return fail("copy-destination-format-extent-authority-or-transfer");
    }
    if (!r.Allocate(instance.GetAllocator())) return fail("staging-allocation");
    r.previous_write = dst.write_seq;
    r.destination = NativeBedImage::Of(destination, dst);
    r.stage = R::CopyPending;
    scheduler.EndRendering(); // The ordinary optimized copy already ends rendering here.
    r.CopyTaps(scheduler, proxy.target.image, proxy.target.layout, proxy.aspects,
               vk::ImageAspectFlagBits::eDepth, 0, 4, false, r.alternate ? R::Bytes : 0);
    r.CopyTaps(scheduler, cb2.target.image, cb2.target.layout, cb2.aspects,
               vk::ImageAspectFlagBits::eColor, 12, 4);
    return true;
}

void Caustics::SewerReducedFallbackCopy(VideoCore::ImageId source) {
    if (native_bed.reduced && source == native_bed.depth.id) {
        CloseReducedBed("product-copy-used-native-fallback");
    }
    if (sewer_reduced && source == sewer_reduced->depth.id) {
        SewerReducedRefused("depth-copy-used-native-fallback");
    }
}

void Caustics::SewerReducedAfterCopy(VideoCore::ImageId source, VideoCore::ImageId destination,
                                    const VideoCore::Image& dst, vk::ImageView sampled, vk::ImageView written) {
    auto& pass = native_bed;
    if (pass.reduced && pass.stage == NativeBedStage::CopyPending && source == pass.depth.id) {
        const auto proxy = scene_targets.InspectSewerProxy(source, pass.depth.uid, pass.ground_view);
        if (CurrentNativeBed(pass) && proxy.valid && proxy.dirty && proxy.target.image == pass.depth_proxy &&
            proxy.target.layout == vk::ImageLayout::eShaderReadOnlyOptimal &&
            texture_cache.IsRegisteredImage(destination, dst.image_uid) &&
            pass.copy == NativeBedImage::Of(destination, dst) && dst.write_seq > pass.copy_write) {
            pass.stage = NativeBedStage::Copy;
            pass.copy_write = dst.write_seq;
        } else {
            CloseReducedBed("product-copy-source-changed-or-destination-not-written");
        }
    }
    if (!sewer_reduced || source != sewer_reduced->depth.id) return;
    using R = SewerReducedReceipt;
    auto& r = *sewer_reduced;
    if (r.stage != R::CopyPending || !sampled || !written || dst.write_seq <= r.previous_write ||
        r.destination != NativeBedImage::Of(destination, dst)) {
        return SewerReducedRefused("copy-destination-not-written-or-replaced");
    }
    r.stage = R::Copy;
    r.copy_tick = scheduler.CurrentTick();
    r.copy_write = dst.write_seq;
    r.sampled_view = sampled;
    r.written_view = written;
    fmt::print("[sewer-reduced] event=copy frame={} scene={} tick={} source_image={:x} "
               "source_view={:x} dst={}/{}:{:x}/{:x} seq={}/{} native=3840x2160\n",
               r.frame, r.scene, r.copy_tick, std::bit_cast<u64>(VkImage(r.depth_proxy)),
               std::bit_cast<u64>(VkImageView(sampled)), destination.index, dst.image_uid,
               std::bit_cast<u64>(VkImage(dst.GetImage())), std::bit_cast<u64>(VkImageView(written)),
               r.previous_write, r.copy_write);
}

bool Caustics::SewerReducedConsume(VideoCore::ImageId color_id, vk::ImageView color_view,
                                  vk::Image color_image, VideoCore::ImageId depth_id,
                                  vk::ImageView depth_view, vk::Image depth_image,
                                  VideoCore::ImageId cb2_id, vk::ImageView cb2_view, vk::Image cb2_image,
                                  const BC::Push& push, vk::ImageView bed_view, bool observe_bed) {
    using R = SewerReducedReceipt;
    auto& r = *sewer_reduced;
    if (r.stage == R::Waiting) return false;
    const auto fail = [this](const char* reason) {
        SewerReducedRefused(reason);
        return false;
    };
    const bool mapped_bed = (push.flags & CAUSTICS_FLAG_BED_2X) != 0;
    if (observe_bed && native_bed_enabled && !mapped_bed) {
        return fail(reduced_bed_refusal ? reduced_bed_refusal : "product-binding-unavailable");
    }
    if (r.stage != R::Water || r.frame != applied_frame || r.depth.id != depth_id ||
        r.cb2.id != cb2_id || r.generation != scene_targets.Generation() ||
        r.loading != BbEngine::Loading::Generation() || BbEngine::Loading::ScreenUp() ||
        gbuffer_depth != depth_id || camera_motion.Depth() != depth_id ||
        push.frame != std::array{1920.f, 1080.f, r.jitter[0], r.jitter[1]} ||
        push.proj != r.camera.proj || push.inv_view != r.camera.inv_view ||
        !std::isfinite(push.sun[3]) || !(push.inv_view[7] > push.sun[3]) ||
        !(push.flags & BC::FlagLamps) || !(push.flags & BC::FlagAlbedo) ||
        (observe_bed && !(push.flags & BC::FlagWorld)) ||
        (mapped_bed != ((push.flags & CAUSTICS_FLAG_NATIVE_BED) != 0)) ||
        (mapped_bed ? !bed_view || bed_view == depth_view : bed_view != depth_view) ||
        (observe_bed && mapped_bed != native_bed_enabled)) {
        return fail("apply-order-camera-plane-or-ordinary-bindings");
    }
    auto* dst = texture_cache.TryGetImage(r.destination.id, r.destination.uid);
    if (!dst || !dst->backing || r.destination != NativeBedImage::Of(r.destination.id, *dst) ||
        dst->write_seq != r.copy_write || dst->binding.needs_rebind || !dst->SafeToDownload() ||
        dst->track_addr != dst->guest_begin || dst->track_addr_end != dst->guest_end ||
        dst->scene_proxy || scene_targets.Tracks(dst->image_uid) || !dst->backing->subresource_states.empty() ||
        dst->backing->state.layout == vk::ImageLayout::eUndefined) {
        return fail("apply-destination-rewritten-rebound-or-new-owner");
    }
    if (mapped_bed && !std::ranges::any_of(view_cache, [&](const auto& entry) {
            return entry.view == bed_view && entry.image == dst->GetImage() &&
                   entry.uid == dst->image_uid && entry.aspect == vk::ImageAspectFlagBits::eColor;
        })) {
        return fail("apply-binding9-not-the-transport-destination");
    }
    const auto* hdr = texture_cache.TryGetImage(color_id, 0);
    const auto depth = scene_targets.InspectSewerProxy(depth_id, r.depth.uid, depth_view);
    const auto cb2 = scene_targets.InspectSewerProxy(cb2_id, r.cb2.uid, cb2_view);
    const auto color = hdr ? scene_targets.InspectSewerProxy(color_id, hdr->image_uid, color_view)
                           : SceneTargets::SewerProxy{};
    constexpr auto TransferSrc = vk::ImageUsageFlagBits::eTransferSrc;
    constexpr auto Sampled = vk::ImageUsageFlagBits::eSampled;
    const auto binding = [](const SceneTargets::SewerProxy& proxy, vk::Image image, vk::ImageView view,
                            vk::ImageUsageFlags usage) {
        return image && view && proxy.target.image == image && proxy.target.view == view && proxy.valid &&
               proxy.extent == R::ProxyExtent && proxy.target.layout == vk::ImageLayout::eGeneral &&
               (proxy.target.usage & usage) == usage;
    };
    if (depth_image != r.depth_proxy || cb2_image != r.cb2_proxy ||
        !R::SourceFits(depth, true) || !R::SourceFits(cb2, false) ||
        !binding(depth, depth_image, depth_view, TransferSrc | Sampled) ||
        !binding(cb2, cb2_image, cb2_view, TransferSrc | Sampled) ||
        !binding(color, color_image, color_view, TransferSrc | vk::ImageUsageFlagBits::eStorage) ||
        color.format != vk::Format::eR16G16B16A16Sfloat) {
        return fail("apply-actual-proxy-image-view-layout-usage");
    }
    r.CopyTaps(scheduler, dst->GetImage(), dst->backing->state.layout, vk::ImageAspectFlagBits::eColor,
               vk::ImageAspectFlagBits::eColor, 24, 4, true);
    r.CopyTaps(scheduler, depth_image, depth.target.layout, depth.aspects,
               vk::ImageAspectFlagBits::eDepth, 36, 4, false, r.alternate ? R::FinalCorners : 0);
    r.CopyTaps(scheduler, cb2_image, cb2.target.layout, cb2.aspects,
               vk::ImageAspectFlagBits::eColor, 48, 4);
    r.CopyTaps(scheduler, color_image, color.target.layout, color.aspects,
               vk::ImageAspectFlagBits::eColor, 64, 8);
    scheduler.Record([](vk::CommandBuffer cmd) {
        EffectPass::MemoryBarrier(cmd, vk::PipelineStageFlagBits2::eTransfer, vk::AccessFlagBits2::eTransferWrite,
                                  Host, vk::AccessFlagBits2::eHostRead);
    });
    fmt::print("[sewer-reduced] event=apply frame={} scene={} tick={} seq={} "
               "depth={:x}/{:x} cb2={:x}/{:x} hdr={}/{}:{:x}/{:x} binding9={:x} plane={:.9g}"
               " product={} bed_enabled={} shade={}\n",
               r.frame, r.scene, scheduler.CurrentTick(), dst->write_seq,
               std::bit_cast<u64>(VkImage(depth_image)), std::bit_cast<u64>(VkImageView(depth_view)),
               std::bit_cast<u64>(VkImage(cb2_image)), std::bit_cast<u64>(VkImageView(cb2_view)),
               color_id.index, hdr->image_uid, std::bit_cast<u64>(VkImage(color_image)),
               std::bit_cast<u64>(VkImageView(color_view)), std::bit_cast<u64>(VkImageView(bed_view)), push.sun[3],
               unsigned(observe_bed), unsigned(native_bed_enabled), push.flags);
    for (u32 row = 0; row < 3; ++row) {
        const auto* m = push.inv_view.data() + 4 * row;
        fmt::print("[sewer-reduced] event=inverse frame={} row={} value={:.9g},{:.9g},{:.9g},{:.9g}\n",
                   r.frame, row, m[0], m[1], m[2], m[3]);
        const auto* v = r.camera.view.data() + 4 * row;
        fmt::print("[sewer-reduced] event=view frame={} row={} value={:.9g},{:.9g},{:.9g},{:.9g}\n",
                   r.frame, row, v[0], v[1], v[2], v[3]);
    }
    fmt::print("[sewer-reduced] event=projection frame={} value={:.9g},{:.9g},{:.9g},{:.9g}\n",
               r.frame, push.proj[0], push.proj[1], push.proj[2], push.proj[3]);
    if (r.alternate) {
        // The caller retains this same buffer and attaches ownership to actual Shade/COPY/WARP.
        sewer_reduced.reset();
        return true;
    }
    if (!r.motion) sewer_reduced_claimed = true;
    scheduler.DeferOperation([receipt = std::exchange(sewer_reduced, {})]() mutable {
        auto motion = receipt->motion;
        const bool ok = receipt->Report();
        receipt.reset();
        if (motion) {
            if (!ok) motion->Refuse("transport-host-invalidate");
            motion->Retire(SewerMotion::Transport);
        }
    }, "sewer reduced receiver proof");
    return true;
}




void Caustics::ResetNativeBedPass() {
    if (sewer_reduced) SewerReducedRefused("gbuffer-depth-or-frame-reset");
    if (bed_trace.active && bed_trace.frame != BbStats::frame_number.load(std::memory_order_relaxed)) {
        NativeBedTraceClose("pass-reset", "frame-ended-without-matched-apply");
        FinishNativeBedTrace(false, {}, NativeBedStage::Empty);
    }
    if (native_bed_enabled) {
        NativeBedTraceClose("pass-reset", "frame-or-camera-depth-change");
        ++native_bed_pass_serial;
        native_bed = {};
        reduced_bed_refusal = nullptr;
    }
}

bool Caustics::CurrentNativeBed(const NativeBedPass& pass, const char* trace) const {
    return TraceNativeBedWanted(trace) &&
           NativeBedTraceGate(scene_targets.Reduced() == pass.reduced, trace, "reduced-scene") &&
           NativeBedTraceGate(!BbEngine::Loading::ScreenUp(), trace, "loading-screen") &&
           NativeBedTraceGate(pass.serial == native_bed_pass_serial, trace, "pass-serial-changed") &&
           NativeBedTraceGate(pass.frame == BbStats::frame_number.load(std::memory_order_relaxed),
                              trace, "frame-changed") &&
           NativeBedTraceGate(pass.loading == BbEngine::Loading::Generation(), trace, "loading-generation-changed") &&
           NativeBedTraceGate(pass.generation == scene_targets.Generation(), trace, "scene-generation-changed") &&
           NativeBedTraceGate(bool(pass.depth.id), trace, "no-tracked-depth") &&
           NativeBedTraceGate(pass.depth.id == camera_motion.Depth(), trace, "camera-depth-changed");
}

bool Caustics::NativeBedCamera(const NativeBedPass& pass, std::array<float, 2> jitter,
                             const char* trace) const {
    const auto camera = camera_motion.PassMatrices();
    return NativeBedTraceGate(camera.valid, trace, "camera-invalid") &&
           NativeBedTraceGate(camera.view == pass.view, trace, "view-changed") &&
           NativeBedTraceGate(camera.inv_view == pass.inv_view, trace, "inverse-view-changed") &&
           NativeBedTraceGate(camera.proj == pass.proj, trace, "projection-changed") &&
           NativeBedTraceGate(jitter == pass.jitter, trace, "jitter-changed");
}

bool Caustics::NativeBedImageFits(const VideoCore::Image* image, vk::Extent2D extent,
                                const char* trace) const {
    const auto gate = [&](bool accepted, const char* predicate) {
        return NativeBedTraceGate(accepted, trace, predicate);
    };
    if (!gate(image, "image-missing") || !gate(image->backing, "backing-missing") ||
        !gate(bool(image->GetImage()), "image-handle-missing") ||
        !gate(!image->binding.needs_rebind, "image-rebind") ||
        !gate(!image->scene_proxy, "image-proxy") ||
        !gate(!scene_targets.Tracks(image->image_uid), "image-proxy-tracked")) {
        return false;
    }
    const auto& ci = image->backing->image.image_ci;
    return gate(image->info.size.width == extent.width, "guest-width") &&
           gate(image->info.size.height == extent.height, "guest-height") &&
           gate(image->info.num_samples == 1, "guest-sample-count") &&
           gate(image->info.resources == VideoCore::SubresourceExtent{1, 1}, "guest-mip-layer-count") &&
           gate(ci.imageType == vk::ImageType::e2D, "backing-image-type") &&
           gate(ci.extent == vk::Extent3D{extent.width, extent.height, 1}, "backing-extent") &&
           gate(ci.samples == vk::SampleCountFlagBits::e1, "backing-sample-count") &&
           gate(ci.mipLevels == 1, "backing-mip-count") &&
           gate(ci.arrayLayers == 1, "backing-layer-count");
}

void Caustics::NoteNativeBedGround(VideoCore::ImageId depth_id, VideoCore::ImageId albedo_id,
                                   vk::Extent2D extent, std::array<float, 2> jitter) {
    const bool trace = TracingNativeBed(depth_id);
    const auto gate = [&](bool accepted, const char* predicate) {
        return NativeBedTraceGate(accepted, trace ? "ground-track" : nullptr, predicate);
    };
    if (!gate(armed, "caustics-not-armed") || !gate(bool(depth_id), "depth-id-missing") ||
        !gate(bool(albedo_id), "cb2-id-missing") || !gate(depth_id == gbuffer_depth, "gbuffer-depth-id") ||
        !gate(albedo_id == gbuffer_albedo, "gbuffer-cb2-id") ||
        !gate(!BbEngine::Loading::ScreenUp(), "loading-visible")) {
        return;
    }
    if (!CurrentNativeBed(native_bed)) {
        if (native_bed.stage != NativeBedStage::Empty) {
            NativeBedTraceClose("ground-track", "previous-pass-out-of-date");
        }
        native_bed = {};
    }
    if (native_bed.stage != NativeBedStage::Empty) {
        NativeBedTraceClose("ground-track", "duplicate-current-ground");
    }
    native_bed.Ground();
    if (!gate(native_bed.stage == NativeBedStage::Ground, "duplicate-current-ground")) return;
    const auto* depth = texture_cache.TryGetImage(depth_id, 0);
    const auto* albedo = texture_cache.TryGetImage(albedo_id, 0);
    const auto camera = camera_motion.PassMatrices();
    BC::Push geometry{};
    geometry.proj = camera.proj;
    geometry.inv_view = camera.inv_view;
    geometry.frame = {float(extent.width), float(extent.height), jitter[0], jitter[1]};
    if (!NativeBedImageFits(depth, extent, trace ? "ground-depth" : nullptr) ||
        !NativeBedImageFits(albedo, extent, trace ? "ground-cb2" : nullptr) ||
        !gate(depth->info.pixel_format == vk::Format::eD32Sfloat ||
              depth->info.pixel_format == vk::Format::eD32SfloatS8Uint, "depth-format") ||
        !gate(bool(depth->aspect_mask & vk::ImageAspectFlagBits::eDepth), "depth-aspect") ||
        !gate(albedo->info.pixel_format == vk::Format::eR8G8B8A8Srgb, "cb2-format") ||
        !gate(albedo->aspect_mask == vk::ImageAspectFlagBits::eColor, "cb2-aspect") ||
        !gate(camera.valid, "camera-invalid") ||
        !gate(WP::ProjectionValid(geometry, camera.view), "projection-domain")) {
        NativeBedTraceClose("ground-track", "failed-ground-image-or-camera");
        native_bed = {};
        return;
    }
    native_bed = {
        .stage = NativeBedStage::Ground, .serial = native_bed_pass_serial,
        .frame = BbStats::frame_number.load(std::memory_order_relaxed),
        .loading = BbEngine::Loading::Generation(), .generation = scene_targets.Generation(),
        .depth = NativeBedImage::Of(depth_id, *depth), .albedo = NativeBedImage::Of(albedo_id, *albedo),
        .extent = extent, .proj = camera.proj, .view = camera.view, .inv_view = camera.inv_view,
        .jitter = jitter,
    };
    if (trace) NativeBedTraceEvent("latched", "ground-track", "ground");
}

bool Caustics::WantsNativeBedCopy(VideoCore::ImageId source) const {
    const char* trace = TracingNativeBed(source) ? "copy-wanted" : nullptr;
    return !native_bed.reduced &&
           NativeBedTraceGate(source == native_bed.depth.id, trace, "source-depth-id") &&
           NativeBedTraceGate(native_bed.stage != NativeBedStage::Empty, trace, "empty-stage") &&
           NativeBedTraceGate(native_bed.stage != NativeBedStage::Closed, trace, "closed-stage") &&
           CurrentNativeBed(native_bed, trace);
}

void Caustics::NoteNativeBedCopy(VideoCore::ImageId source_id, const VideoCore::Image& source,
                                 VideoCore::ImageId dest_id, const VideoCore::Image& dest, u64 bytes,
                                 u64 previous_write, std::array<float, 2> jitter) {
    const bool trace = TracingNativeBed(source_id);
    const auto gate = [&](bool accepted, const char* predicate) {
        return NativeBedTraceGate(accepted, trace ? "copy-track" : nullptr, predicate);
    };
    if (!WantsNativeBedCopy(source_id) ||
        !gate(NativeBedImage::Of(source_id, source) == native_bed.depth, "source-identity") ||
        !NativeBedCamera(native_bed, jitter, trace ? "copy-camera" : nullptr) ||
        !NativeBedImageFits(&dest, native_bed.extent, trace ? "copy-destination" : nullptr) ||
        !gate(dest.write_seq > previous_write, "destination-write-sequence") ||
        !gate(dest.info.pixel_format == vk::Format::eR32Sfloat, "destination-format")) {
        NativeBedTraceClose("copy-track", "failed-copy-predicate");
        native_bed.stage = NativeBedStage::Closed;
        return;
    }
    if (native_bed.stage != NativeBedStage::Ground) {
        NativeBedTraceClose("copy-track", "copy-out-of-order");
    }
    native_bed.Copied();
    if (!gate(native_bed.stage == NativeBedStage::Copy, "copy-out-of-order")) return;
    native_bed.copy = NativeBedImage::Of(dest_id, dest);
    native_bed.copy_bytes = bytes;
    native_bed.copy_write = dest.write_seq;
    native_bed.copied_source_write = source.write_seq;
    if (trace) NativeBedTraceEvent("latched", "copy-track", "copy");
}

void Caustics::NoteNativeBedWater(VideoCore::ImageId depth_id, vk::Extent2D extent,
                                  std::array<float, 2> jitter) {
    const bool trace = TracingNativeBed(depth_id);
    const auto gate = [&](bool accepted, const char* predicate) {
        return NativeBedTraceGate(accepted, trace ? "water-track" : nullptr, predicate);
    };
    if (!gate(AwaitsNativeBedWater(), "not-awaiting-water") ||
        !CurrentNativeBed(native_bed, trace ? "water-current" : nullptr) ||
        !gate(depth_id == native_bed.depth.id, "depth-id")) {
        return;
    }
    const auto* depth = texture_cache.TryGetImage(depth_id, native_bed.depth.uid);
    if (!gate(depth, "depth-not-registered") ||
        !gate(native_bed.depth == NativeBedImage::Of(depth_id, *depth), "depth-identity") ||
        !gate(extent == native_bed.extent, "depth-extent") ||
        !NativeBedCamera(native_bed, jitter, trace ? "water-camera" : nullptr) ||
        !gate(depth->write_seq > native_bed.copied_source_write, "depth-write-sequence")) {
        NativeBedTraceClose("water-track", "failed-water-predicate");
        native_bed.stage = NativeBedStage::Closed;
        return;
    }
    if (native_bed.stage != NativeBedStage::Copy && native_bed.stage != NativeBedStage::Water) {
        NativeBedTraceClose("water-track", "water-out-of-order");
    }
    native_bed.Water();
    native_bed.water_write = depth->write_seq;
    if (trace && gate(native_bed.stage == NativeBedStage::Water, "water-out-of-order")) {
        NativeBedTraceEvent("latched", "water-track", "water");
    }
}

Caustics::NativeBedPass Caustics::TakeNativeBed() {
    const char* trace = bed_trace.active ? "take" : nullptr;
    if (!NativeBedTraceGate(native_bed.stage == NativeBedStage::Water, trace, "stage-is-not-water") ||
        !CurrentNativeBed(native_bed, trace)) {
        NativeBedTraceClose("take", "unusable-pass");
        if (native_bed.reduced) CloseReducedBed("product-take-stage-or-pass-out-of-date");
        native_bed.stage = NativeBedStage::Closed;
        return {};
    }
    NativeBedPass pass = native_bed;
    NativeBedTraceClose("take", "consumed-pass");
    native_bed.stage = NativeBedStage::Closed;
    return pass;
}

vk::ImageView Caustics::BindNativeBed(const NativeBedPass& pass, VideoCore::ImageId color_id,
                                      const VideoCore::Image& color, VideoCore::ImageId depth_id,
                                      const VideoCore::Image& depth, const VideoCore::Image* albedo,
                                      vk::ImageView depth_view, vk::ImageView albedo_view,
                                      vk::Extent2D extent, std::array<float, 2> jitter, float plane,
                                      JoinedBedBind* joined) {
    if (joined) joined->attempted = true;
    const auto check = [joined](JoinedBedBind::Gate gate, bool passed) {
        return joined ? joined->Check(gate, passed) : passed;
    };
    using J = JoinedBedBind;
    constexpr auto sampled = vk::ImageUsageFlagBits::eSampled;
    constexpr float sewer_plane = -29.59665f;
    if (!check(J::WaterStage, pass.stage == NativeBedStage::Water) ||
        !check(J::Current, CurrentNativeBed(pass)) ||
        !check(J::PlaneRange, std::abs(plane - sewer_plane) <= 0.05f) ||
        !check(J::EyeAbove, pass.inv_view[7] > plane) ||
        !check(J::Extent, extent == pass.extent) || !check(J::GBufferDepth, depth_id == gbuffer_depth) ||
        !check(J::Camera, NativeBedCamera(pass, jitter)) ||
        !check(J::DepthView, bool(depth_view)) || !check(J::AlbedoView, bool(albedo_view)) ||
        !check(J::AlbedoPresent, albedo) || !check(J::ColorFits, NativeBedImageFits(&color, extent)) ||
        !check(J::DepthFits, NativeBedImageFits(&depth, extent)) ||
        !check(J::AlbedoFits, NativeBedImageFits(albedo, extent)) ||
        !check(J::DepthIdentity, NativeBedImage::Of(depth_id, depth) == pass.depth) ||
        !check(J::AlbedoIdentity, NativeBedImage::Of(gbuffer_albedo, *albedo) == pass.albedo) ||
        !check(J::WaterWrite, depth.write_seq >= pass.water_write) ||
        !check(J::DepthSampled, bool(depth.usage_flags & sampled)) ||
        !check(J::AlbedoSampled, bool(albedo->usage_flags & sampled))) {
        return {};
    }
    return BindBedCopy(pass, color_id, color, depth_id, depth, *albedo, nullptr, joined);
}

struct Caustics::ReducedBedTargets {
    SceneTargets::Target color{}, depth{}, albedo{};
};

vk::ImageView Caustics::BindReducedBed(const NativeBedPass& pass, VideoCore::ImageId color_id,
                                       const VideoCore::Image& color, VideoCore::ImageId depth_id,
                                       const VideoCore::Image& depth, const VideoCore::Image* albedo,
                                       const ReducedBedTargets& targets, vk::Extent2D extent,
                                       std::array<float, 2> jitter, float plane) {
    const auto fail = [&](const char* reason) {
        CloseReducedBed(reason);
        return vk::ImageView{};
    };
    constexpr float sewer_plane = -29.59665f;
    if (pass.stage != NativeBedStage::Water || !pass.reduced || !CurrentNativeBed(pass) ||
        !NativeBedCamera(pass, jitter) || depth_id != gbuffer_depth ||
        std::abs(plane - sewer_plane) > 0.05f || !(pass.inv_view[7] > plane)) {
        return fail("product-apply-pass-camera-or-plane");
    }
    if (extent != pass.extent || extent != vk::Extent2D{1920, 1080} ||
        pass.copy_extent != vk::Extent2D{3840, 2160}) {
        return fail("product-apply-extent");
    }
    if (!color.backing || !albedo ||
        pass.depth != NativeBedImage::Of(depth_id, depth) ||
        pass.albedo != NativeBedImage::Of(gbuffer_albedo, *albedo)) {
        return fail("product-apply-parent-identity");
    }
    const auto current = [&](VideoCore::ImageId id, u64 uid, const SceneTargets::Target& target,
                             vk::ImageUsageFlagBits usage) {
        auto proxy = scene_targets.InspectSewerProxy(id, uid, target.view);
        if (!target.image || !target.view || !proxy.valid || proxy.target.image != target.image ||
            proxy.extent != SewerReducedReceipt::ProxyExtent || target.layout != vk::ImageLayout::eGeneral ||
            proxy.target.layout != target.layout || !(target.usage & usage) || !(proxy.target.usage & usage)) {
            return SceneTargets::SewerProxy{};
        }
        return proxy;
    };
    constexpr auto sampled = vk::ImageUsageFlagBits::eSampled;
    const auto depth_proxy = current(depth_id, depth.image_uid, targets.depth, sampled);
    const auto cb2_proxy = current(gbuffer_albedo, albedo->image_uid, targets.albedo, sampled);
    const auto hdr_proxy = current(color_id, color.image_uid, targets.color, vk::ImageUsageFlagBits::eStorage);
    if (!SewerReducedReceipt::SourceFits(depth_proxy, true) ||
        !SewerReducedReceipt::SourceFits(cb2_proxy, false) ||
        targets.depth.image != pass.depth_proxy || targets.albedo.image != pass.albedo_proxy) {
        return fail("product-apply-depth-or-cb2-binding");
    }
    if (!hdr_proxy.valid || hdr_proxy.format != vk::Format::eR16G16B16A16Sfloat ||
        hdr_proxy.aspects != vk::ImageAspectFlagBits::eColor ||
        targets.color.image == targets.depth.image || targets.color.image == targets.albedo.image ||
        targets.depth.image == targets.albedo.image) {
        return fail("product-apply-hdr-binding");
    }
    const auto view = BindBedCopy(pass, color_id, color, depth_id, depth, *albedo, &targets, nullptr);
    if (view) runtime.FlushBarriers();
    return view;
}

vk::ImageView Caustics::BindBedCopy(const NativeBedPass& pass, VideoCore::ImageId color_id,
                                     const VideoCore::Image& color, VideoCore::ImageId depth_id,
                                     const VideoCore::Image& depth, const VideoCore::Image& albedo,
                                     const ReducedBedTargets* targets, JoinedBedBind* joined) {
    using J = JoinedBedBind;
    const auto check = [&](J::Gate gate, bool passed) {
        if (!passed && targets) {
            static constexpr const char* reasons[] = {
                "product-copy-registration", "product-copy-backing", "product-copy-identity",
                "product-copy-write-sequence", "product-copy-download-safety", "product-copy-guest-begin",
                "product-copy-guest-range", "product-copy-track-begin", "product-copy-track-end",
                "product-copy-hle-byte-count", "product-copy-format", "product-copy-aspect",
                "product-copy-sampled-usage", "product-copy-backing-format", "product-copy-backing-sampled",
                "product-copy-subresource-states", "product-copy-layout", "product-copy-hdr-id-alias",
                "product-copy-depth-id-alias", "product-copy-cb2-id-alias", "product-copy-hdr-alias",
                "product-copy-depth-alias", "product-copy-cb2-alias", "product-copy-range-cache-alias",
            };
            static_assert(std::size(reasons) == J::NoCacheOverlap - J::CopyRegistered + 1);
            CloseReducedBed(reasons[gate - J::CopyRegistered]);
        }
        return joined ? joined->Check(gate, passed) : passed;
    };
    constexpr auto sampled = vk::ImageUsageFlagBits::eSampled;
    if (!check(J::CopyRegistered, texture_cache.IsRegisteredImage(pass.copy.id, pass.copy.uid))) return {};
    auto* dst = texture_cache.TryGetImage(pass.copy.id, pass.copy.uid);
    if (joined) joined->candidate = J::Describe(pass.copy.id, dst);
    if (!check(J::CopyFits, NativeBedImageFits(dst, pass.reduced ? pass.copy_extent : pass.extent)) ||
        !check(J::CopyIdentity, NativeBedImage::Of(pass.copy.id, *dst) == pass.copy) ||
        !check(J::CopyWrite, dst->write_seq == pass.copy_write) ||
        !check(J::DownloadSafe, dst->SafeToDownload()) ||
        !check(J::CopyBegin, dst->guest_begin) || !check(J::CopyRange, dst->guest_begin < dst->guest_end) ||
        !check(J::TrackBegin, dst->track_addr == dst->guest_begin) ||
        !check(J::TrackEnd, dst->track_addr_end == dst->guest_end) ||
        !check(J::CopyBytes, pass.copy_bytes >= dst->guest_end - dst->guest_begin) ||
        !check(J::CopyFormat, dst->info.pixel_format == vk::Format::eR32Sfloat) ||
        !check(J::CopyAspect, dst->aspect_mask == vk::ImageAspectFlagBits::eColor) ||
        !check(J::CopySampled, bool(dst->usage_flags & sampled)) ||
        !check(J::BackingFormat, dst->backing->image.image_ci.format == vk::Format::eR32Sfloat) ||
        !check(J::BackingSampled, bool(dst->backing->image.image_ci.usage & sampled)) ||
        !check(J::WholeBacking, dst->backing->subresource_states.empty()) ||
        !check(J::Layout, dst->backing->state.layout != vk::ImageLayout::eUndefined)) {
        return {};
    }
    const auto aliases = [&](const VideoCore::Image& image) {
        return dst->GetImage() == image.GetImage() ||
               dst->backing->image.allocation == image.backing->image.allocation ||
               image.Overlaps(dst->guest_begin, dst->guest_end - dst->guest_begin) ||
               (image.info.stencil_size && dst->Overlaps(image.info.stencil_addr, image.info.stencil_size));
    };
    if (!check(J::ColorIdDistinct, pass.copy.id != color_id) ||
        !check(J::DepthIdDistinct, pass.copy.id != depth_id) ||
        !check(J::AlbedoIdDistinct, pass.copy.id != gbuffer_albedo) ||
        !check(J::ColorDisjoint, !aliases(color)) || !check(J::DepthDisjoint, !aliases(depth)) ||
        !check(J::AlbedoDisjoint, !aliases(albedo))) {
        return {};
    }
    if (targets && (dst->GetImage() == targets->color.image || dst->GetImage() == targets->depth.image ||
                    dst->GetImage() == targets->albedo.image)) {
        CloseReducedBed("product-apply-copy-aliases-proxy");
        return {};
    }
    bool overlap = false;
    texture_cache.ForEachImageInRegion(dst->guest_begin, pass.copy_bytes,
        [&](VideoCore::ImageId id, VideoCore::Image&) { return overlap = id != pass.copy.id; });
    if (!check(J::NoCacheOverlap, !overlap)) return {};
    const auto view = CachedView(*dst, vk::ImageAspectFlagBits::eColor);
    runtime.Transit(dst, vk::ImageLayout::eGeneral, Compute, ShaderRead);
    return view;
}

void Caustics::OnGBufferDraw(VideoCore::ImageId depth, VideoCore::ImageId material,
                             VideoCore::ImageId albedo, VideoCore::ImageId records) {
    if (wetness_probe) {
        wetness_probe->GBuffer(BbStats::frame_number.load(std::memory_order_relaxed),
                               gbuffer_depth != depth);
    }
    gbuffer_depth = depth;
    gbuffer_material = material;
    gbuffer_albedo = albedo;
    gbuffer_records = records;
    lamps.Clear(); // r107b: the lamps of this pass only (they are in its view space)
    armed = armed || depth != applied_depth ||
            BbStats::frame_number.load(std::memory_order_relaxed) != applied_frame;
}

void Caustics::OnShadowResolve(VideoCore::ImageId target, const std::array<float, 3>& toward,
                               bool valid) {
    std::array<float, 3> unit{};
    const bool above = valid && BC::SunUsable(toward, unit);
    if (valid) {
        last_sun_y = unit[1];
    }
    shadow_target = target;
    sun = unit;
    sun_valid = above;
    resolved = true;
}

// bbport (r107b_caustics-visible)
void Caustics::AddLights(const u32* records, u32 count) {
    if (knobs.lamp_strength > 0.0f) {
        lamps.Add(records, count);
    }
}

// bbport (r107b_caustics-visible): the r81 area gate's rule (volumetric_area_gate.h): a set has the
// sun when its light 0 is at least half as bright (weight 0.5 or more) as the brightest set's;
// the white fallback set counts as without sun (fail closed: no sun indoors).
void Caustics::OnLightSets(const float* table, u32 floats, VAddr texture0) {
    namespace AG = VolumetricAreaGate;
    const u32 count = std::min(floats / AG::RecordFloats, AG::Records);
    float best = 0.0f, best_raw = 0.0f;
    for (u32 i = 0; i < count; ++i) {
        const float* set = table + i * AG::RecordFloats;
        if (!AG::IsFallback(set)) {
            best = std::max(best, AG::SunLuminance(set + AG::RecordColour));
            best_raw = std::max(best_raw, AG::RawLuminance(set + AG::RecordColour));
        }
    }
    sun_mask = {};
    sets_sunny = 0;
    for (u32 i = 0; best > 0.0f && i < count; ++i) {
        const float* set = table + i * AG::RecordFloats;
        if (!AG::IsFallback(set) &&
            AG::SunWeight(AG::SunLuminance(set + AG::RecordColour), best) >= 0.5f) {
            sun_mask[i >> 5] |= 1u << (i & 31u);
            ++sets_sunny;
        }
    }
    sets_count = count;
    sets_best = best_raw;
    sets_address = texture0;
    sets_fresh = true;
}

vk::ImageView Caustics::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid &&
            entry.aspect == aspect) {
            entry.last_use = ++view_uses;
            return entry.view;
        }
        if (entry.last_use < oldest->last_use) {
            oldest = &entry;
        }
    }
    const auto device = instance.GetDevice();
    if (oldest->view) {
        scheduler.DeferOperation([device, view = oldest->view] { device.destroyImageView(view); });
    }
    *oldest = {
        .image = handle,
        .uid = image.image_uid,
        .aspect = aspect,
        .view = Check<"create water caustics view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

void Caustics::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                     std::array<float, 2> jitter, const std::array<float, 3>& wind,
                     Rasterizer* sewer_witness) {
    // Once after each G-buffer pass: the rasterizer calls at every blended draw of the scene.
    if (!armed) {
        return;
    }
    std::optional<JoinedBedBind> joined;
    if (TracingJoinedBed(depth_id)) {
        joined.emplace();
        joined->stamp = JoinedBedStamp();
        joined->before = JoinedBedState();
    }
    armed = false;
    applied_depth = gbuffer_depth;
    applied_frame = BbStats::frame_number.load(std::memory_order_relaxed);
    const NativeBedPass bed_pass = native_bed_enabled ? TakeNativeBed() : NativeBedPass{};
    const bool sewer_compare = sewer_witness && sewer_witness->SewerReceiverApply(applied_frame, depth_id);
    if (!sewer_compare) joined.reset();
    if (TracingNativeBed(depth_id) && sewer_compare) {
        FinishNativeBedTrace(true, depth_id, bed_pass.stage);
    }
    const bool reduced_request = sewer_reduced && sewer_reduced->depth.id == depth_id;
    const auto motion_sample = reduced_request ? sewer_reduced->motion : nullptr;
    auto alternate_receipt = reduced_request && sewer_reduced->alternate ? sewer_reduced : nullptr;
    const bool observe_bed = !alternate_receipt && bed_observer && (motion_sample ||
        ((sewer_compare || reduced_request) && !sewer_motion && !std::exchange(bed_observer->taken, true)));
    const bool observe_reduced_bed = observe_bed && reduced_request;
    const auto refuse_bed = [&](const char* why, bool plane = false, float y = 0.0f, u32 lamps = 0) {
        if (sewer_reduced && sewer_reduced->depth.id == depth_id) SewerReducedRefused(why);
        if (joined) joined->Report(bed_pass, why, scheduler.CurrentTick(), plane, y,
                                   false, lamps, false, 0.0f, {}, {});
        if (motion_sample) motion_sample->Refuse(why);
        if (observe_bed) BedObserver::Refused(applied_frame, scheduler.CurrentTick(), depth_id,
                                             bed_pass.stage, plane, y, lamps, why);
    };
    auto* probe = wetness_probe.get();
    if (probe && !probe->ObserveApply(applied_frame)) probe = nullptr;
    if (!SunWanted() && !LampsWanted() && !knobs.show && !(motion_strength > 0.0f)) { // bbport (r128b_lrt-caustics-water), r130e: the motion alone
        if (probe) probe->Refuse(applied_frame, "water-strength-off", 1);
        refuse_bed("water-strength-off");
        ++idle_passes; // both strengths went to 0 (the slider): no counts, no dispatch, no line
        return;
    }
    ++stats.calls;
    // Real time (clamped steps), so the pattern drifts at its speed at any frame rate.
    const auto now = std::chrono::steady_clock::now();
    const bool indoor = IndoorAmbient();
    const bool legacy_drift = !indoor || SunWanted() || LampsWanted() || knobs.show;
    const double raw_dt = legacy_drift ? std::chrono::duration<double>(now - last_time).count() : 0.0;
    if (legacy_drift) {
        drift.Advance(raw_dt, wind);
    }
    auto* evidence = active_water_evidence;
    RootEvidence root;
    float feet[3] = {};
    if (!indoor && motion_strength > 0.0f) { // bbport (r130b_water-moves): the field's time and the hunter's steps (nothing at 0)
        BC::Motion::Advance(motion, raw_dt, wind, motion_strength);
        const bool read = BbEngine::world_player_position(feet);
        stats.hunter_read = read && BC::Motion::Finite3(feet);
        if (evidence) {
            root.read = read;
            root.valid = stats.hunter_read;
        }
        if (stats.hunter_read) {
            const auto jumps_before = evidence ? motion.walker.jumps : 0u;
            const auto seen = BC::Motion::Observe(motion, feet, motion_strength);
            stats.steps += seen.steps;
            stats.landings += seen.landings;
            if (evidence) {
                root.events = seen;
                root.jump = motion.walker.jumps != jumps_before;
            }
        }
    }
    if (legacy_drift) {
        last_time = now;
    }
    const auto observe_water = [&](const CameraMotion::Matrices* camera, bool plane, float plane_y) {
        if (evidence) {
            evidence->Observe(now, applied_frame, raw_dt, motion_strength, knobs,
                              indoor ? std::array<float, 3>{} : wind, indoor ? ambient.state : motion,
                              root, feet, depth_id, texture_cache, camera, plane, plane_y,
                              indoor ? &ambient : nullptr, legacy_drift);
        }
    };
    const auto done = [&] {
        if (stats.calls >= (reported ? LineCalls : FirstLineCalls)) {
            reported = true;
            Report();
        }
    };
    if (!made || !color_id || !depth_id) {
        if (probe) probe->Refuse(applied_frame, !made ? "pipeline-unavailable" :
                                !color_id ? "no-scene-color" : "no-depth", 1);
        refuse_bed(!made ? "pipeline-unavailable" : !color_id ? "no-scene-color" : "no-depth");
        observe_water(nullptr, false, 0.0f);
        done();
        return;
    }
    float plane_y = 0.0f;
    const bool plane = camera_motion.MirrorPlane(plane_y) && std::isfinite(plane_y);
    const auto camera = camera_motion.PassMatrices();
    if (probe) {
        const char* reason = nullptr;
        if (!indoor || !ambient.active || !(motion_strength > 0.0f)) reason = "indoor-ambient-inactive";
        else if (!plane) reason = "no-mirror-plane";
        else if (!camera.valid || !WP::Finite(camera.inv_view)) reason = "no-pass-camera";
        else if (!(camera.inv_view[7] > plane_y)) reason = "below-or-on-plane";
        else if (!probe->MatchingPass(applied_frame, depth_id, gbuffer_depth, camera_motion.Depth())) {
            reason = "camera-gbuffer-depth-or-frame-mismatch";
        }
        if (reason) {
            probe->Refuse(applied_frame, reason, 2);
            probe = nullptr;
        }
    }
    observe_water(&camera, plane, plane_y);
    // r107b: `draw` is the sun's caustics (BB_CAUSTICS), `lamp_draw` the lamps' (BB_CAUSTICS_LAMPS).
    bool draw = plane && knobs.strength > 0.0f;
    bool lamp_draw = plane && knobs.lamp_strength > 0.0f;
    bool sets_ok = false;
    std::array<BC::Lamp, BC::MaxLamps> chosen{};
    u32 chosen_count = 0;
    // r107e: puddles stand in for the water plane in frames without a mirrored water pass.
    calls_since_mirror = plane ? 0u : calls_since_mirror + 1u;
    const bool puddle = !plane && knobs.lamp_strength > 0.0f && camera.valid &&
                        calls_since_mirror > BC::PuddleQuietCalls;
    if (!plane) {
        // The first pass of a mirrored frame (the mirror image) comes here too: it leaves the
        // shadow resolve's news for the pass the plane is found in.
        ++stats.no_plane;
        if (puddle && puddle_found) {
            plane_y = puddle_y;
            if (puddle_checked) {
                const auto& seen = lamps.Lights();
                chosen_count = BC::ChooseLamps(seen.empty() ? nullptr : seen.front().data(),
                                               seen.size(), camera.inv_view, plane_y, chosen,
                                               knobs.world > 0.0f ? &last_lamps : nullptr, last_lamp_count);
                lamp_draw = chosen_count > 0;
            } else {
                ++stats.puddle_floor;
            }
        } else if (puddle) {
            ++stats.puddle_none;
        }
    } else {
        // The sun and its shadow target are this frame's only when a resolve came since the last
        // call that found a plane; so are the light sets (r107b).
        const bool fresh = resolved;
        resolved = false;
        sets_ok = std::exchange(sets_fresh, false);
        if (camera.valid && camera.inv_view[7] < plane_y) {
            // The camera is below the water: this pass is the mirror image, not the world.
            ++stats.mirror;
            draw = lamp_draw = false;
        } else {
            if (draw && (!fresh || !sun_valid)) {
                ++stats.no_sun;
                draw = false;
            }
            if (lamp_draw && camera.valid) {
                const auto& seen = lamps.Lights();
                chosen_count = BC::ChooseLamps(seen.empty() ? nullptr : seen.front().data(),
                                               seen.size(), camera.inv_view, plane_y, chosen,
                                               knobs.world > 0.0f ? &last_lamps : nullptr, last_lamp_count);
            }
            if (lamp_draw && chosen_count == 0) {
                ++stats.no_lamps;
                lamp_draw = false;
            }
        }
    }
    if (knobs.world > 0.0f && chosen_count > 0) {
        last_lamps = chosen; // r107f: the lamps of this pass count more in the next one
        last_lamp_count = chosen_count;
    }
    // bbport (r130e_sewer-water-moves): the motion alone: a plane, the camera above it, neither caustics drawing: a dispatch of its own
    const bool motion_only = BC::Motion::Warp::Alone(motion_strength, plane, camera.valid && camera.inv_view[7] >= plane_y, draw, lamp_draw);
    if (!draw && !lamp_draw && !knobs.show && !puddle && !motion_only) { // r107e: puddles measure every pass
        if (probe) probe->Refuse(applied_frame, "no-water-pass", 3);
        refuse_bed("no-water-pass", plane, plane_y, chosen_count);
        done();
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    auto& depth = texture_cache.GetImage(depth_id);
    if (!camera.valid || color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat) {
        if (probe) probe->Refuse(applied_frame, "unsupported-scene-color", 3);
        refuse_bed("unsupported-scene-color", plane, plane_y, chosen_count);
        ++stats.no_scene;
        done();
        return;
    }
    VideoCore::Image* shadow = nullptr;
    if (draw && shadow_target) {
        shadow = &texture_cache.GetImage(shadow_target);
        if (!FourBytes(*shadow)) {
            shadow = nullptr;
        }
    }
    VideoCore::Image* material = nullptr;
    if ((knobs.show || puddle) && gbuffer_material && gbuffer_depth == depth_id) { // r107e
        material = &texture_cache.GetImage(gbuffer_material);
        if (!FourBytes(*material)) {
            material = nullptr;
        }
    }
    // r107b: the sun only where the light set at the water point has it: the sets of this frame's
    // directional draw, whose texture 0 must be the G-buffer's specular target.
    VideoCore::Image* records = nullptr;
    if (draw && sets_ok && gbuffer_records && gbuffer_depth == depth_id) {
        records = &texture_cache.GetImage(gbuffer_records);
        if (!FourBytes(*records) || records->info.guest_address != sets_address) {
            records = nullptr;
        }
    }
    if (draw && !records) {
        ++stats.no_sets;
        draw = false;
    }
    VideoCore::Image* albedo = nullptr;
    if (lamp_draw && gbuffer_albedo && gbuffer_depth == depth_id) {
        albedo = &texture_cache.GetImage(gbuffer_albedo);
        const auto f = albedo->info.pixel_format;
        if (!FourBytes(*albedo) && f != vk::Format::eR8G8B8A8Srgb && f != vk::Format::eB8G8R8A8Srgb) {
            albedo = nullptr;
        }
    }
    // The scene's size is the reduced one while a preset renders below the game's own size,
    // else the game's render size (its targets may be allocated larger).
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
        // Only scene-sized images have a reduced proxy: the others are left out.
        if (shadow && !scene_targets.EligibleScene(*shadow)) {
            shadow = nullptr;
        }
        if (material && !scene_targets.EligibleScene(*material)) {
            material = nullptr;
        }
        if (records && !scene_targets.EligibleScene(*records)) {
            records = nullptr; // r107b
        }
        if (albedo && !scene_targets.EligibleScene(*albedo)) {
            albedo = nullptr; // r107b
        }
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    if (draw && !shadow) {
        ++stats.no_shadow;
        draw = false;
    }
    if (draw && !records) {
        ++stats.no_sets; // r107b
        draw = false;
    }
    if ((!draw && !lamp_draw && !material && !motion_only) || width < 16 || height < 16) { // r130e: motion_only
        if (probe) probe->Refuse(applied_frame, width < 16 || height < 16 ? "invalid-dimensions" :
                                "no-water-pass", 3);
        refuse_bed(width < 16 || height < 16 ? "invalid-dimensions" : "no-water-pass", plane, plane_y, chosen_count);
        done();
        return;
    }
    // The pass reads the camera depth: a lamps-apart batch still open ends first (only here,
    // right before a dispatch, so it is never split for nothing).
    if (point_shadow.Apart()) {
        point_shadow.EndApart(jitter[0] != 0.0f || jitter[1] != 0.0f);
        ++stats.lamp_ends;
    }
    const SceneUseScope scene_use{"water caustics"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{}, shadow_view{}, material_view{};
    vk::ImageView records_view{}, albedo_view{}, native_bed_view{}; // r107b
    vk::Image probe_depth_image{};
    ReducedBedTargets reduced_targets{};
    bool probe_sampled = false;
    if (reduced) {
        VideoCore::ImageViewInfo color_info, depth_info;
        color_info.format = color.info.pixel_format;
        depth_info.format = depth.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, color_info, Compute, ReadWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            if (probe) probe->Refuse(applied_frame, "scene-proxy-storage-unavailable", 4);
            refuse_bed("scene-proxy-storage-unavailable", plane, plane_y, chosen_count);
            ++stats.no_scene;
            done();
            return;
        }
        color_view = proxy.view;
        reduced_targets.color = proxy;
        const auto depth_proxy = scene_targets.ReadNext(depth_id, depth_info);
        depth_view = depth_proxy.view;
        reduced_targets.depth = depth_proxy;
        if (probe) {
            probe_depth_image = depth_proxy.image;
            probe_sampled = bool(depth_proxy.usage & vk::ImageUsageFlagBits::eSampled) &&
                            depth_proxy.layout == vk::ImageLayout::eGeneral;
        }
        if (shadow) {
            VideoCore::ImageViewInfo info;
            info.format = shadow->info.pixel_format;
            shadow_view = scene_targets.ReadNext(shadow_target, info).view;
        }
        if (material) {
            VideoCore::ImageViewInfo info;
            info.format = material->info.pixel_format;
            material_view = scene_targets.ReadNext(gbuffer_material, info).view;
        }
        if (draw && records) { // r107b
            VideoCore::ImageViewInfo info;
            info.format = records->info.pixel_format;
            records_view = scene_targets.ReadNext(gbuffer_records, info).view;
        }
        if (lamp_draw && albedo) { // r107b
            VideoCore::ImageViewInfo info;
            info.format = albedo->info.pixel_format;
            const auto cb2_proxy = scene_targets.ReadNext(gbuffer_albedo, info);
            albedo_view = cb2_proxy.view;
            reduced_targets.albedo = cb2_proxy;
        }
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            if (probe) probe->Refuse(applied_frame, "native-scene-storage-unavailable", 4);
            refuse_bed("native-scene-storage-unavailable", plane, plane_y, chosen_count);
            ++stats.no_scene;
            done();
            return;
        }
        color_view = CachedView(color, vk::ImageAspectFlagBits::eColor);
        depth_view = CachedView(depth, vk::ImageAspectFlagBits::eDepth);
        if (probe) {
            probe_depth_image = depth.GetImage();
            probe_sampled = bool(depth.usage_flags & vk::ImageUsageFlagBits::eSampled);
        }
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        if (shadow) {
            shadow_view = CachedView(*shadow, vk::ImageAspectFlagBits::eColor);
            runtime.Transit(shadow, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        }
        if (material) {
            material_view = CachedView(*material, vk::ImageAspectFlagBits::eColor);
            runtime.Transit(material, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        }
        if (draw && records) { // r107b
            records_view = CachedView(*records, vk::ImageAspectFlagBits::eColor);
            runtime.Transit(records, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        }
        if (lamp_draw && albedo) { // r107b
            albedo_view = CachedView(*albedo, vk::ImageAspectFlagBits::eColor);
            runtime.Transit(albedo, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        }
        if (joined) {
            joined->width = width;
            joined->height = height;
            joined->color = JoinedBedBind::Describe(color_id, &color);
            joined->depth = JoinedBedBind::Describe(depth_id, &depth);
            joined->albedo = JoinedBedBind::Describe(gbuffer_albedo, albedo);
            joined->depth_view = depth_view;
            joined->albedo_view = albedo_view;
        }
        if (bed_pass.stage == NativeBedStage::Water && plane && lamp_draw) {
            native_bed_view = BindNativeBed(bed_pass, color_id, color, depth_id, depth, albedo,
                                           depth_view, albedo_view, {width, height}, jitter, plane_y,
                                           joined ? &*joined : nullptr);
        }
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();
    if (probe) {
        BC::Push geometry{};
        geometry.proj = camera.proj;
        geometry.frame = {float(width), float(height), jitter[0], jitter[1]};
        geometry.inv_view = camera.inv_view;
        const auto& backing = depth.backing->image.image_ci;
        const auto proxy_size = reduced ? scene_targets.ProxySize(depth) : SceneResolution::Size{};
        const u32 sampled_width = reduced ? proxy_size.width : backing.extent.width;
        const u32 sampled_height = reduced ? proxy_size.height : backing.extent.height;
        if (!depth_view || !color_view || !probe_depth_image || !probe_sampled ||
            !depth.info.props.is_depth || backing.imageType != vk::ImageType::e2D ||
            (reduced && !scene_targets.EligibleScene(depth))) {
            probe->Refuse(applied_frame, "unsupported-depth-view", 5);
        } else if (!WP::ExtentMatches(width, height, sampled_width, sampled_height,
                                      static_cast<u32>(backing.samples)) ||
                   depth.info.num_samples != 1) {
            probe->Refuse(applied_frame, "depth-extent-or-samples-mismatch", 5);
        } else if (!WP::ProjectionValid(geometry, camera.view)) {
            probe->Refuse(applied_frame, "invalid-camera-projection", 5);
        } else {
            const WP::Source source{
                .image_uid = depth.image_uid,
                .image = std::bit_cast<u64>(static_cast<VkImage>(probe_depth_image)),
                .view = std::bit_cast<u64>(static_cast<VkImageView>(depth_view)),
                .proxy_generation = reduced ? scene_targets.Generation() : 0,
                .frame = applied_frame, .pass = probe->Pass(), .depth_id = depth_id.index,
                .width = width, .height = height, .reduced = reduced, .view_matrix = camera.view,
            };
            // Ordered behind the same depth transition the ordinary water pass uses.
            probe->Issue(source, geometry, plane_y, depth_view, color_view, counters.buffer,
                         *pipeline, *layout);
        }
    }
    if (draw && !shadow_view) {
        ++stats.no_shadow;
        draw = false;
    }
    if (draw && !records_view) {
        ++stats.no_sets; // r107b
        draw = false;
    }
    if (puddle && !material_view) {
        lamp_draw = false; // r107e: lamps over puddles need the gloss (a crossing must be a candidate)
    }
    if (!draw && !lamp_draw && !material_view && !motion_only) { // r130e: motion_only
        refuse_bed("no-usable-input-views", plane, plane_y, chosen_count);
        done();
        return;
    }
    BC::Push push{};
    push.proj = camera.proj;
    push.frame = {float(width), float(height), jitter[0], jitter[1]};
    push.inv_view = camera.inv_view;
    push.sun = {sun[0], sun[1], sun[2], plane_y};
    push.drift = drift.Offsets();
    push.gain = BC::GainOf(knobs);
    push.evolve = drift.EvolveCells();
    push.flags = (knobs.show ? BC::FlagShow : 0u) | (draw ? BC::FlagPlane | BC::FlagRecords : 0u) |
                 (material_view ? BC::FlagMaterial : 0u) | (lamp_draw ? BC::FlagLamps : 0u) |
                 (lamp_draw && albedo_view ? BC::FlagAlbedo : 0u);
    // r107f: the world map is used with the lamps' caustics; a plane more than WorldKeep m from the
    // last one starts a new generation (the old cells read as unknown); the first use clears it.
    const bool world_on = knobs.world > 0.0f && lamp_draw && world_map.buffer;
    bool clear_map = false;
    if (world_on) {
        if (world_gen == 0 || std::fabs(plane_y - world_plane) > BC::WorldKeep) {
            ++world_gen;
            world_plane = plane_y;
            ++stats.world_changes;
        }
        push.flags |= BC::FlagWorld;
        ++stats.world_draws;
        clear_map = !world_cleared;
        world_cleared = true;
    }
    push.slot = dispatches % BC::Slots;
    // r107e: puddles: measured with the G-buffer's gloss; the plane found goes in sun.w.
    const bool puddle_pass = puddle && material_view;
    if (puddle_pass) {
        push.flags |= BC::FlagPuddle | (puddle_found ? BC::FlagPuddlePlane : 0u);
        ++stats.puddle_measured;
        stats.puddle_lamps += lamp_draw ? 1 : 0;
    }
    if (!indoor && motion_strength > 0.0f && (draw || lamp_draw || puddle_pass || motion_only)) {
        // bbport (r130e_sewer-water-moves): the last use of this slot's warp counts (the motion block is rewritten below)
        const u32* last = static_cast<const u32*>(counters.mapped) + BC::Motion::Base + push.slot * BC::Motion::Words;
        if (last[CAUSTICS_MOTION_WARP_PX] != 0u) {
            stats.warp_px += last[CAUSTICS_MOTION_WARP_PX];
            stats.warp_kept += last[CAUSTICS_MOTION_WARP_KEPT];
            ++stats.warp_reads;
        }
    }
    // bbport (r130b_water-moves): the moving water: this slot's motion block (its last reader, Slots dispatches ago, is long done;
    // its ring pixel word is read first) and the flag. Only with a strength above 0 and a dispatch that draws or measures.
    if (const u32 motion_flag = BC::Motion::FlagsOf(motion_strength, draw || lamp_draw || puddle_pass);
        !indoor && motion_flag != 0u) {
        const u32 motion_kind = plane && (draw || lamp_draw) ? 1u : (puddle_pass && puddle_found && puddle_checked ? 2u : 0u);
        u32* block = static_cast<u32*>(counters.mapped) + BC::Motion::Base + push.slot * BC::Motion::Words;
        stats.ring_px += block[CAUSTICS_MOTION_RING_PX];
        BC::Motion::WriteBlock(block, motion, motion_kind, motion_strength);
        push.flags |= motion_flag;
        ++stats.motion_dispatches;
        if (!told_motion) {
            told_motion = true;
            std::printf("Water motion (r130b): first moving dispatch at frame %llu: %s plane at y %.2f; 4 waves 0.15-0.60 m toward "
                        "%.0f deg, steepness %.3f, wind %.2f m/s (%s)\n",
                        static_cast<unsigned long long>(BbStats::frame_number.load(std::memory_order_relaxed)),
                        motion_kind == 1 ? "mirrored" : motion_kind == 2 ? "puddle" : "no", double(plane_y),
                        BC::Motion::HeadingDeg(motion), double(motion.steep), motion.wind_speed,
                        motion_env ? "environment" : "setting");
        }
    }
    // Allow the existing warp gate to retry after a transient copy-image failure.
    if (warp_failed && now >= warp_retry_at) {
        warp_failed = false;
    }
    // bbport (r130e_sewer-water-moves): the rippled reflection. A motion-only dispatch writes its own motion block (kind 1: r130b's
    // block above ran only for a dispatch that draws or measures); a mirrored plane's moving dispatch then gets its band, the copy
    // image and the stamp (the block's ROW0 and STAMP words). Nothing of this runs with the motion off (the flag is 0).
    bool warp_on = false, warp_clear = false;
    u32 warp_row0 = 0;
    const char* warp_state = "motion-off";
    if (observe_bed && motion_strength > 0.0f) warp_state = "scope";
    if (!indoor && motion_only) {
        u32* block = static_cast<u32*>(counters.mapped) + BC::Motion::Base + push.slot * BC::Motion::Words;
        stats.ring_px += block[CAUSTICS_MOTION_RING_PX];
        BC::Motion::WriteBlock(block, motion, 1u, motion_strength);
        push.flags |= BC::Motion::FlagMotion;
        ++stats.motion_dispatches;
        ++stats.motion_only;
    }
    const bool ambient_wanted = indoor && ambient.active && motion_strength > 0.0f &&
                                plane && camera.inv_view[7] >= plane_y && (draw || lamp_draw || motion_only);
    if (ambient_wanted ||
        ((push.flags & BC::Motion::FlagMotion) != 0u && plane && (draw || lamp_draw || motion_only))) {
        const u32 row0 = BC::Motion::Warp::WaterTopRow(push, plane_y, width, height);
        if (observe_bed) warp_state = row0 < height ? "warp-image-unavailable" : "empty-band";
        if (row0 < height && !warp_failed) {
            warp_on = EnsureWarpImage(width, height);
            if (!warp_on) {
                warp_failed = true;
                std::printf("%s: the copy image %ux%u could not be made: no rippled reflection%s\n",
                            BC::Motion::Warp::LogTag, width, height,
                            indoor ? "" : " (the shimmer still runs)");
            }
        }
        if (warp_on) {
            if (observe_bed) warp_state = "issued";
            u32* block = static_cast<u32*>(counters.mapped) + BC::Motion::Base + push.slot * BC::Motion::Words;
            warp_row0 = row0;
            warp_clear = !warp.cleared;
            warp.cleared = true;
            ++stats.warp_dispatches;
            stats.warp_rows += height - row0;
            stats.warp_height += height;
            if (!indoor) {
                block[CAUSTICS_MOTION_ROW0] = row0;
                block[CAUSTICS_MOTION_STAMP] = BC::Motion::Warp::Stamp(dispatches);
            }
            if (!indoor && !told_warp) {
                told_warp = true;
                std::printf("%s: first rippled reflection at frame %llu: plane y %.2f, rows %u-%u of %u (%.0f%%), copy %ux%u RGBA16F "
                            "(%.1f MB), reflect %.2f m, shift at most %.1f px, glint %.2f a unit of strength (now %.2f)\n",
                            BC::Motion::Warp::LogTag,
                            static_cast<unsigned long long>(BbStats::frame_number.load(std::memory_order_relaxed)), double(plane_y),
                            row0, height, height, 100.0 * double(height - row0) / double(height), width, height,
                            8.0 * double(width) * double(height) / 1048576.0, double(BC::Motion::Warp::ReflectM),
                            double(BC::Motion::Warp::ShiftMax) * double(height), double(BC::Motion::Warp::Glint),
                            double(motion_strength));
            }
        }
    }
    // A failed attempt starts a new cooldown. Calls within it leave the deadline alone.
    if (warp_failed && now >= warp_retry_at) {
        warp_retry_at = now + std::chrono::seconds{1};
    }
    const bool ambient_only = indoor && motion_only && !knobs.show && !puddle_pass;
    if (ambient_only && !warp_on) {
        refuse_bed(warp_state, plane, plane_y, chosen_count);
        done();
        return;
    }
    if (indoor) {
        u32* block = static_cast<u32*>(counters.mapped) + BC::Motion::Base + push.slot * BC::Motion::Words;
        if (slot_ambient_warp[push.slot]) {
            stats.warp_px += block[CAUSTICS_MOTION_WARP_PX];
            stats.warp_kept += block[CAUSTICS_MOTION_WARP_KEPT];
            ++stats.warp_reads;
        }
        slot_ambient_warp[push.slot] = warp_on;
        if (warp_on) {
            BC::Motion::WriteBlock(block, ambient.state, 1u, motion_strength);
            block[CAUSTICS_MOTION_ROW0] = warp_row0;
            block[CAUSTICS_MOTION_STAMP] = BC::Motion::Warp::Stamp(dispatches);
            stats.motion_only += ambient_only ? 1 : 0;
        }
    }
    slot_camera_y[push.slot] = camera.inv_view[7];
    slot_puddle_y[push.slot] = plane_y;
    slot_puddle[push.slot] = puddle_pass ? (puddle_found ? 2 : 1) : 0;
    // r107b: the slot's data block (the slot's last reader, Slots dispatches ago, is long done):
    // the light sets' sun mask, the lamps and their gain.
    {
        u32* data = static_cast<u32*>(counters.mapped) + BC::Slots * BC::SlotWords +
                    push.slot * BC::DataWords;
        std::memset(data, 0, BC::DataWords * sizeof(u32));
        std::memcpy(data, sun_mask.data(), sizeof(sun_mask));
        const u32 lamp_count = lamp_draw ? chosen_count : 0u;
        data[CAUSTICS_DATA_COUNT] = lamp_count;
        const float lamp_gain = BC::LampGainOf(knobs);
        std::memcpy(&data[CAUSTICS_DATA_GAIN], &lamp_gain, sizeof(float));
        // r107c: the game's lamp curve, as LocalFalloff::Patch makes it (read at the start).
        const auto& settings = BbSettings::Get();
        const float core = std::isfinite(settings.startup_local_light_core) &&
                                   settings.startup_local_light_core > 0.0f
                               ? settings.startup_local_light_core
                               : 0.0f;
        const bool inverse_square = settings.startup_local_inverse_square;
        const float core2 = inverse_square ? core * core : -1.0f;
        const float energy = inverse_square ? settings.startup_local_light_intensity *
                                                  LocalFalloff::EnergyScale(core)
                                            : 1.0f;
        std::memcpy(&data[CAUSTICS_DATA_CORE2], &core2, sizeof(float));
        std::memcpy(&data[CAUSTICS_DATA_ENERGY], &energy, sizeof(float));
        const float look = lamp_count > 0 ? BC::LookOf(knobs) : 0.0f; // r107d
        std::memcpy(&data[CAUSTICS_DATA_LOOK], &look, sizeof(float));
        // r107f: the world map's generation and the bed's strength (0 and 0 without BB_CAUSTICS_WORLD)
        data[CAUSTICS_DATA_WORLD_GEN] = world_on ? world_gen : 0u;
        const float bed_strength = world_on ? knobs.world : 0.0f;
        std::memcpy(&data[CAUSTICS_DATA_BED], &bed_strength, sizeof(float));
        for (u32 k = 0; k < lamp_count; ++k) {
            const auto& lamp = chosen[k];
            const std::array<float, BC::LampWords> words{lamp.world[0],  lamp.world[1],
                                                        lamp.world[2],  lamp.reach,
                                                        lamp.colour[0], lamp.colour[1],
                                                        lamp.colour[2], 0.0f};
            std::memcpy(&data[CAUSTICS_DATA_LAMPS + k * BC::LampWords], words.data(), sizeof(words));
            stats.colour_top = std::max({stats.colour_top, lamp.colour[0], lamp.colour[1], lamp.colour[2]});
        }
        stats.lamp_draws += lamp_draw ? 1 : 0;
        stats.lamps_used += lamp_count;
    }
    // The shader's counts of the dispatch Slots - 1 before this one (its work is long done; the
    // slot is cleared on the GPU before its next use, which is the next dispatch).
    if (dispatches + 1 >= BC::Slots) {
        const auto* words = static_cast<const u32*>(counters.mapped) +
                            ((dispatches + 1) % BC::Slots) * BC::SlotWords;
        for (u32 i = 0; i < BC::SlotWords; ++i) {
            stats.pixels[i] += words[i];
        }
        ++stats.read;
        // r107e: that dispatch's puddle candidates give the plane; its counts on the plane it was
        // given check it (only the same plane, within PuddleKeep).
        const u32 slot = (dispatches + 1) % BC::Slots;
        if (slot_puddle[slot] != 0) {
            const auto e = BC::EstimatePuddle(words + CAUSTICS_W_HEIGHTS, slot_camera_y[slot], width * height);
            if (!e.found) {
                puddle_found = puddle_checked = false;
            } else if (!puddle_found || std::fabs(e.height - puddle_y) > BC::PuddleKeep) {
                puddle_found = true;
                puddle_checked = false;
                puddle_y = e.height;
            }
            if (puddle_found && slot_puddle[slot] == 2 &&
                std::fabs(slot_puddle_y[slot] - puddle_y) <= BC::PuddleKeep) {
                const u32 ground = words[CAUSTICS_W_PUDDLE_GROUND], wet = words[CAUSTICS_W_PUDDLE_WET];
                puddle_checked = BC::PuddlesNotFloor(ground, wet);
                stats.puddle_ground = ground;
                stats.puddle_wet = wet;
            }
        }
    }
    ++dispatches;
    stats.drawn += draw || lamp_draw ? 1 : 0;
    stats.shown += draw || lamp_draw || puddle_pass || motion_only ? 0 : 1; // r107e: a puddle pass is no test view; r130e: nor a lone motion
    last_plane = plane || puddle_found ? plane_y : last_plane;
    if (!told_first && (draw || lamp_draw)) {
        told_first = true;
        std::printf("Water caustics (r107b): first caustics drawn: water plane at y %.2f, sun or moon "
                    "%.2f up (%s), %u lamps, scene %ux%u (%s)\n",
                    double(plane_y), double(sun[1]), draw ? "drawn" : "not drawn",
                    lamp_draw ? chosen_count : 0u, width, height,
                    reduced ? "reduced scene" : "the game's scene");
    }
    if (reduced && bed_pass.reduced) {
        if (!ambient_only && plane && (push.flags & (BC::FlagWorld | BC::FlagLamps | BC::FlagAlbedo)) ==
                                         (BC::FlagWorld | BC::FlagLamps | BC::FlagAlbedo)) {
            native_bed_view = BindReducedBed(bed_pass, color_id, color, depth_id, depth, albedo,
                                             reduced_targets, {width, height}, jitter, plane_y);
        } else {
            CloseReducedBed("product-apply-world-plane-lamp-or-cb2-unavailable");
        }
    }
    if (native_bed_view) {
        push.flags |= CAUSTICS_FLAG_NATIVE_BED;
        if (reduced) push.flags |= CAUSTICS_FLAG_BED_2X;
        if (warp_on) push.flags |= CAUSTICS_FLAG_BED_IN_WARP;
    }
    // Unbound inputs take the depth's view (the shader reads them only under their flag).
    const vk::ImageView bound_bed = native_bed_view ? native_bed_view : depth_view;
    const vk::ImageView bound_shadow = shadow_view ? shadow_view : depth_view;
    const vk::ImageView bound_material = material_view ? material_view : depth_view;
    const vk::ImageView bound_albedo = albedo_view ? albedo_view : depth_view;   // r107b
    const vk::ImageView bound_records = records_view ? records_view : depth_view; // r107b
    BedObserver::PointSet reduced_points{};
    u64 reduced_copy_write = 0;
    bool observed_reduced_apply = false;
    if (sewer_reduced) {
        if (observe_reduced_bed) {
            for (u32 i = 0; i < reduced_points.size(); ++i) {
                const auto [x, y] = sewer_reduced->points[i];
                reduced_points[i] = vk::Offset3D{x, y, 0};
            }
            reduced_copy_write = sewer_reduced->copy_write;
        }
        observed_reduced_apply = SewerReducedConsume(
            color_id, color_view, reduced_targets.color.image, depth_id, depth_view,
            reduced_targets.depth.image, gbuffer_albedo, bound_albedo, reduced_targets.albedo.image,
            push, bound_bed, observe_reduced_bed || bool(alternate_receipt));
    }
    if (alternate_receipt &&
        (!observed_reduced_apply || !warp_on || !indoor || motion_strength != .5f ||
         std::abs(AmbientRate() - .2) > .0001 || !plane || ambient_only || knobs.show ||
         width != 1920 || height != 1080 || !(std::abs(plane_y + 29.59665f) <= .002f) ||
         (push.flags & (CAUSTICS_FLAG_NATIVE_BED | CAUSTICS_FLAG_BED_2X | CAUSTICS_FLAG_BED_IN_WARP)) ||
         bound_bed != depth_view ||
         std::ranges::any_of(alternate_receipt->points, [&](auto p) { return u32(p.y) < warp_row0; }))) {
        alternate_receipt->alternate->Refuse("ordinary-warp-or-fallback-scope");
        // Some ground/final copies may already have been recorded. Keep the staging buffer alive.
        scheduler.DeferOperation([keep = std::move(alternate_receipt)] {}, "sewer alternate scope refusal");
    }
    const auto native_view = [&](const VideoCore::Image* image, vk::ImageView view,
                                 vk::ImageAspectFlags aspect) {
        return image && view && std::ranges::any_of(view_cache, [&](const auto& entry) {
            return entry.view == view && entry.image == image->GetImage() &&
                   entry.uid == image->image_uid && entry.aspect == aspect;
        });
    };
    if (sewer_compare) {
        const bool native_inputs = !reduced && !ambient_only && plane &&
            native_view(&depth, depth_view, vk::ImageAspectFlagBits::eDepth) &&
            native_view(albedo, bound_albedo, vk::ImageAspectFlagBits::eColor);
        sewer_witness->SewerReceiverConsumer(applied_frame, depth_id, gbuffer_albedo, depth, albedo,
                                             depth_view, bound_albedo, push, camera.view, native_inputs);
    }
    if (joined) {
        const char* status = native_bed_view ? "bound" : reduced ? "reduced" :
                             bed_pass.stage != NativeBedStage::Water ? "not-water" :
                             !plane ? "no-plane" : !lamp_draw ? "no-lamps" : "bind-refused";
        joined->Report(bed_pass, status, scheduler.CurrentTick(), plane, plane_y, lamp_draw,
                       chosen_count, reduced, camera.inv_view[7], bound_bed, depth_view);
    }
    const u32 warp_flags = BC::Motion::FlagMotion | (indoor ? CAUSTICS_FLAG_AMBIENT : 0u);
    const u32 copy_dispatch_flags = warp_flags | BC::Motion::Warp::FlagCopy;
    const u32 warp_dispatch_flags = warp_flags | BC::Motion::Warp::FlagWarp |
        ((push.flags & CAUSTICS_FLAG_BED_IN_WARP) != 0u ?
            push.flags & (CAUSTICS_FLAG_NATIVE_BED | CAUSTICS_FLAG_BED_2X | BC::FlagAlbedo) : 0u);
    vk::Image observed_scene{};
    std::unique_ptr<BedObserver::Capture> receipt;
    if (observe_bed) {
        if (motion_sample && (!warp_on || !indoor || motion_strength != .5f ||
                              std::abs(AmbientRate() - .2) > .0001 ||
                              std::ranges::any_of(reduced_points, [&](auto p) { return u32(p.y) < warp_row0; }))) {
            refuse_bed("motion-series-ordinary-warp-scope", plane, plane_y, chosen_count);
        } else if (!plane || knobs.show || width != 1920 || height != 1080 || ambient_only ||
                   (reduced && !observed_reduced_apply)) {
            refuse_bed(reduced ? "unregistered-reduced-shade-scope" : "unregistered-native-shade-scope",
                       plane, plane_y, chosen_count);
        } else {
            using Binding = BedObserver::Capture::Binding;
            receipt = std::make_unique<BedObserver::Capture>();
            receipt->frame = applied_frame;
            receipt->tick = scheduler.CurrentTick();
            receipt->loading = BbEngine::Loading::Generation();
            receipt->generation = scene_targets.Generation();
            receipt->width = width;
            receipt->height = height;
            receipt->row0 = warp_row0;
            receipt->stage = u32(bed_pass.stage);
            receipt->indoor = indoor;
            if (reduced) {
                receipt->reduced = true;
                receipt->enabled = native_bed_enabled;
                receipt->copy_seq = reduced_copy_write;
                receipt->points = reduced_points;
            }
            receipt->warp_state = warp_state;
            receipt->push = push;
            receipt->view = camera.view;
            receipt->flags = {push.flags, warp_on ? copy_dispatch_flags : 0u,
                              warp_on ? warp_dispatch_flags : 0u};
            const auto* data = static_cast<const u32*>(counters.mapped) +
                               BC::Slots * BC::SlotWords + push.slot * BC::DataWords;
            std::ranges::copy_n(data, BC::DataWords, receipt->lamp_data.begin());
            receipt->color = Binding::Of(color_id, &color, color_view);
            receipt->depth = Binding::Of(depth_id, &depth, depth_view);
            receipt->cb2 = bound_albedo == depth_view ? receipt->depth :
                           Binding::Of(gbuffer_albedo, albedo, bound_albedo);
            if (reduced) {
                receipt->color.image = reduced_targets.color.image;
                receipt->depth.image = reduced_targets.depth.image;
                receipt->cb2.image = reduced_targets.albedo.image;
            }
            receipt->bed_fallback = bound_bed == depth_view;
            if (receipt->bed_fallback) {
                receipt->bed = receipt->depth;
            } else {
                const auto* bed_image = texture_cache.TryGetImage(bed_pass.copy.id, bed_pass.copy.uid);
                receipt->bed = Binding::Of(bed_pass.copy.id, bed_image, bound_bed);
                receipt->bed_resolved = native_view(bed_image, bound_bed, vk::ImageAspectFlagBits::eColor) &&
                    NativeBedImage::Of(bed_pass.copy.id, *bed_image) == bed_pass.copy &&
                    bed_image->info.pixel_format == vk::Format::eR32Sfloat &&
                    bed_image->aspect_mask == vk::ImageAspectFlagBits::eColor;
            }
            if (warp_on) {
                receipt->warp_image = vk::Image(warp.image);
                receipt->warp_view = *warp.view;
            }
            constexpr auto transfer_source = vk::ImageUsageFlagBits::eTransferSrc;
            receipt->sample_state = reduced ? "unjoined-reduced-scene" : "unjoined-native-scene";
            if (reduced && observed_reduced_apply) {
                // The reduced receipt checked the actual colour view, General and transfer source.
                observed_scene = reduced_targets.color.image;
                receipt->snapshots = warp_on ? 3 : 2;
                receipt->sample_state = "rgba16f-color-mip0-layer0";
            } else if (!reduced && native_view(&color, color_view, vk::ImageAspectFlagBits::eColor) &&
                NativeBedImageFits(&color, {width, height}) &&
                texture_cache.IsRegisteredImage(color_id, color.image_uid) &&
                color.aspect_mask == vk::ImageAspectFlagBits::eColor &&
                color.backing->subresource_states.empty() &&
                color.backing->state.layout == vk::ImageLayout::eGeneral &&
                color.backing->image.image_ci.format == vk::Format::eR16G16B16A16Sfloat) {
                receipt->sample_state = "scene-transfer-source-missing";
                if ((color.usage_flags & transfer_source) &&
                    (color.backing->image.image_ci.usage & transfer_source)) {
                    observed_scene = color.GetImage();
                    receipt->snapshots = warp_on ? 3 : 2;
                    receipt->sample_state = "rgba16f-color-mip0-layer0";
                }
            }
        }
    }
    if (receipt && motion_sample) {
        receipt->motion = motion_sample;
        receipt->motion_strength = motion_strength;
        receipt->motion_rate = float(AmbientRate());
        const auto* wave = static_cast<const u32*>(counters.mapped) + BC::Motion::Base +
                           push.slot * BC::Motion::Words;
        std::ranges::copy_n(wave, receipt->wave.size(), receipt->wave.begin());
        const auto resource = [](const BedObserver::Capture::Binding& b, vk::ImageAspectFlags aspect) {
            return SewerMotion::Resource{b.id.index, b.uid, b.image, b.view, aspect};
        };
        auto& stamp = motion_sample->warp;
        constexpr auto color_aspect = vk::ImageAspectFlagBits::eColor;
        constexpr auto depth_aspect = vk::ImageAspectFlagBits::eDepth;
        stamp.color = resource(receipt->color, color_aspect);
        stamp.depth = resource(receipt->depth, depth_aspect);
        stamp.cb2 = resource(receipt->cb2, color_aspect);
        stamp.bed = resource(receipt->bed, receipt->bed_fallback ? depth_aspect : color_aspect);
        stamp.timeline = scheduler.GetWorkSemaphore()->Handle();
        stamp.tick = receipt->tick;
        stamp.copy_write = receipt->copy_seq;
        stamp.jitter = jitter;
        for (u32 i = 0; i < stamp.px.size(); ++i) {
            stamp.px[i] = vk::Offset2D{receipt->points[i].x, receipt->points[i].y};
        }
        SewerMotion::Publish(motion_sample);
    }
    const bool instrumented = bool(receipt);
    BedObserver::PointSet alternate_points{};
    if (alternate_receipt) {
        auto& proof = *alternate_receipt->alternate;
        proof.warp_tick = scheduler.CurrentTick();
        proof.commands = true;
        for (u32 i = 0; i < alternate_points.size(); ++i) {
            const auto [x, y] = alternate_receipt->points[i];
            alternate_points[i] = {x, y, 0};
        }
        fmt::print("[sewer-alt-support] event=ordinary-command frame={} scene={} tick={} seq={} "
                   "band={} flags={},{},{} bed=fallback product=0 indoor={} extent={}x{} "
                   "strength={:.9g} rate={:.9g} plane={:.9g} hdr=rgba16f-color-mip0-layer0 "
                   "depth=d32-depth-mip0-layer0 bed_ancestry=unmeasured\n",
                   alternate_receipt->frame, alternate_receipt->scene, proof.warp_tick,
                   alternate_receipt->copy_write, warp_row0, push.flags, copy_dispatch_flags, warp_dispatch_flags,
                   unsigned(indoor), width, height, motion_strength, float(AmbientRate()), plane_y);
    }
    EffectPass::Mark(ProfileRow, "water caustics");
    scheduler.RecordCrumb(
        {.name = "water caustics"},
        [push, width, height, color_view, depth_view, bound_shadow, bound_material, bound_albedo,
         bound_records, bound_bed,
         counter_buffer = counters.buffer,
         world_buffer = world_map.buffer ? world_map.buffer : counters.buffer, clear_map, // r107f
         pass_pipeline = instrumented ? *bed_observer->pipeline : *pipeline,
         pass_layout = *layout, warp_on, warp_clear, warp_row0, ambient_only, instrumented,
         observed_scene, points = receipt ? receipt->points : BedObserver::PointSet{},
         alternate_points, alternate_color = alternate_receipt ? reduced_targets.color.image : vk::Image{},
         alternate_buffer = alternate_receipt ? vk::Buffer{alternate_receipt->buffer} : vk::Buffer{},
         motion_probe = receipt && bool(receipt->motion),
         copy_dispatch_flags, warp_dispatch_flags, // r130e: the copy image of the rippled reflection
         warp_handle = warp_on ? vk::Image(warp.image) : vk::Image{},
         warp_bound = warp_on ? *warp.view : color_view](vk::CommandBuffer cmdbuf) {
            if (warp_clear) { // bbport (r130e_sewer-water-moves): the copy image's first use (made or remade): General and a clear
                              // to 0 (no stamp is 0) before the first dispatch binds it (binding 8); the barrier below orders it
                const vk::ImageMemoryBarrier2 to_clear{
                    .srcStageMask = vk::PipelineStageFlagBits2::eTopOfPipe,
                    .dstStageMask = vk::PipelineStageFlagBits2::eAllTransfer,
                    .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
                    .oldLayout = vk::ImageLayout::eUndefined, .newLayout = vk::ImageLayout::eGeneral,
                    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .image = warp_handle, .subresourceRange = WarpLevel};
                cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_clear});
                cmdbuf.clearColorImage(warp_handle, vk::ImageLayout::eGeneral,
                                       vk::ClearColorValue{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}}, WarpLevel);
            }
            if (clear_map) {
                cmdbuf.fillBuffer(world_buffer, 0, WorldBytes, 0); // r107f: the first use
            }
            cmdbuf.fillBuffer(counter_buffer, push.slot * SlotBytes, SlotBytes, 0);
            if (instrumented) {
                cmdbuf.fillBuffer(counter_buffer, BufferBytes, BedObserver::TailBytes, BED_OBS_UNREAD);
                // The tail clear overlaps both the coordinate words and the HDR snapshot slots.
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eAllTransfer,
                                          vk::AccessFlagBits2::eTransferWrite,
                                          vk::PipelineStageFlagBits2::eAllTransfer,
                                          vk::AccessFlagBits2::eTransferWrite);
                BedObserver::SetPoints(cmdbuf, counter_buffer, points, motion_probe);
                if (observed_scene) BedObserver::Snapshot(cmdbuf, observed_scene, counter_buffer, 0, points);
            }
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute, ReadWrite);
            if (alternate_buffer) BedObserver::Snapshot(cmdbuf, alternate_color, alternate_buffer, 0,
                                                       alternate_points, SewerReducedReceipt::HdrBase);
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            const std::array infos{Info(color_view),     Info(depth_view),   Info(bound_shadow),
                                   Info(bound_material), Info(bound_albedo), Info(bound_records),
                                   Info(warp_bound), Info(bound_bed)};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0,
                instrumented ? BedObserver::AllocBytes : BufferBytes};
            const vk::DescriptorBufferInfo world_info{world_buffer, 0, VK_WHOLE_SIZE}; // r107f
            const std::array writes{Write(0, StorageImage, &infos[0]),
                                    Write(1, SampledImage, &infos[1]),
                                    Write(2, SampledImage, &infos[2]),
                                    Write(3, SampledImage, &infos[3]),
                                    vk::WriteDescriptorSet{.dstBinding = 4,
                                                           .descriptorCount = 1,
                                                           .descriptorType = StorageBuffer,
                                                           .pBufferInfo = &counter_info},
                                    Write(5, SampledImage, &infos[4]),
                                    Write(6, SampledImage, &infos[5]),
                                    vk::WriteDescriptorSet{.dstBinding = 7,
                                                           .descriptorCount = 1,
                                                           .descriptorType = StorageBuffer,
                                                           .pBufferInfo = &world_info},
                                    Write(8, StorageImage, &infos[6]), // r130e: warp copy
                                    Write(9, SampledImage, &infos[7])};
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            if (!ambient_only) {
                cmdbuf.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push),
                                     &push);
                cmdbuf.dispatch((width + BC::Group - 1) / BC::Group, (height + BC::Group - 1) / BC::Group,
                                1);
            }
            if (observed_scene) BedObserver::Snapshot(cmdbuf, observed_scene, counter_buffer, 1, points);
            if (alternate_buffer) BedObserver::Snapshot(cmdbuf, alternate_color, alternate_buffer, 1,
                                                       alternate_points, SewerReducedReceipt::HdrBase);
            if (warp_on) { // bbport (r130e_sewer-water-moves): the copy, then the warp, over the band of rows
                // the normal dispatch's writes before the copy reads the scene
                EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute, ReadWrite);
                const u32 band_rows = height - warp_row0;
                BC::Push warp_push = push;
                warp_push.flags = copy_dispatch_flags;
                cmdbuf.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(warp_push), &warp_push);
                cmdbuf.dispatch((width + BC::Group - 1) / BC::Group, (band_rows + BC::Group - 1) / BC::Group, 1);
                EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite, Compute, ReadWrite);
                warp_push.flags = warp_dispatch_flags;
                cmdbuf.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(warp_push), &warp_push);
                cmdbuf.dispatch((width + BC::Group - 1) / BC::Group, (band_rows + BC::Group - 1) / BC::Group, 1);
            }
            if (observed_scene && warp_on) {
                BedObserver::Snapshot(cmdbuf, observed_scene, counter_buffer, 2, points);
            }
            if (alternate_buffer) {
                BedObserver::Snapshot(cmdbuf, alternate_color, alternate_buffer, 2,
                                      alternate_points, SewerReducedReceipt::HdrBase);
            }
            if (instrumented || alternate_buffer) {
                EffectPass::MemoryBarrier(cmdbuf, Compute | vk::PipelineStageFlagBits2::eAllTransfer,
                                          vk::AccessFlagBits2::eShaderWrite | vk::AccessFlagBits2::eTransferWrite,
                                          AllCommands | Host, MemoryAll | vk::AccessFlagBits2::eHostRead);
            } else {
                EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                          AllCommands | Host, MemoryAll | vk::AccessFlagBits2::eHostRead);
            }
        });
    if (alternate_receipt) {
        scheduler.DeferOperation([sample = std::move(alternate_receipt), plane_y] {
            sample->ReportAlternate(plane_y);
        }, "sewer alternate ordinary WARP readback");
    }
    if (receipt) {
        bed_observer->scheduled = true;
        scheduler.DeferOperation([receipt = std::move(receipt), mapped = counters.mapped]() mutable {
            auto motion = receipt->motion;
            receipt->Report(mapped);
            receipt.reset();
            if (motion) motion->Retire(SewerMotion::Warp);
        }, "sewer bed observer readback");
    }
    done();
}

void Caustics::Report() {
    const double reads = std::max(1.0, double(stats.read));
    BbReport::Printf(
        "Water caustics (r107): %u calls, %u drew, %u test view only; skipped: %u no water plane, %u "
        "mirror image, %u no sun, %u no shadow target, %u no scene; plane y %.2f, sun %.2f up; a "
        "dispatch: %.0f px facing, %.0f on water, %.0f drawn, %.0f puddle cand.; %u lamp batch ends\n",
        stats.calls, stats.drawn, stats.shown, stats.no_plane, stats.mirror, stats.no_sun,
        stats.no_shadow, stats.no_scene, double(last_plane), double(last_sun_y),
        double(stats.pixels[0]) / reads,
        double(stats.pixels[1]) / reads, double(stats.pixels[2]) / reads,
        double(stats.pixels[3]) / reads, stats.lamp_ends);
    // r107b: why water points are not water, what the depth holds at those that are, the light
    // sets, the lamps (a dispatch, as above)
    const auto px = [&](int word) { return double(stats.pixels[word]) / reads; };
    BbReport::Printf(
        "Water caustics (r107b): a dispatch: sun water pt %.0f off scr, %.0f hidden, %.0f dry, %.0f "
        "on plane, %.0f below it, %.0f sunless set; skipped %u no sets; sets %u, %u sunny, best "
        "%.2f\n",
        px(CAUSTICS_W_OFF), px(CAUSTICS_W_HIDDEN), px(CAUSTICS_W_DRY), px(CAUSTICS_W_ON_PLANE),
        px(CAUSTICS_W_BELOW), px(CAUSTICS_W_NO_SUN_SET), stats.no_sets, sets_count, sets_sunny,
        double(sets_best));
    // r107c: the lamps (a dispatch with lamps; the light added and the lamps' own direct light as
    // the pass models it, each over the pixel's own, means over the lit pixels)
    const double lit = std::max(1.0, double(stats.pixels[CAUSTICS_W_LAMP_LIT]));
    BbReport::Printf(
        "Water caustics (r107c): a dispatch: lamps %.2f (colour up to %.1f, %s curve), %.0f px tried, "
        "%.0f lit (+%.1f%% of their own, lamp model %.2f of it), crossings %.0f dry, %.0f unseen; "
        "skipped %u no lamps\n",
        double(stats.lamps_used) / std::max(1.0, double(stats.lamp_draws)), double(stats.colour_top),
        BbSettings::Get().startup_local_inverse_square ? "inverse-square" : "(1-d/r)^2",
        px(CAUSTICS_W_LAMP_TRIED), px(CAUSTICS_W_LAMP_LIT),
        100.0 * double(stats.pixels[CAUSTICS_W_LAMP_RATIO]) / CAUSTICS_RATIO_SCALE / lit,
        double(stats.pixels[CAUSTICS_W_LAMP_MODEL]) / CAUSTICS_MODEL_SCALE / lit, px(CAUSTICS_W_LAMP_DRY),
        px(CAUSTICS_W_LAMP_UNSEEN), stats.no_lamps);
    // r107d: the modelled lamp light over the pixel's own, by bins of that light (2 stops a bin),
    // and over the brightest tenth of those pixels (whole bins from the top, at least a tenth).
    char bins[BC::Bins * 24] = {};
    size_t used = 0;
    double all = 0.0, top_n = 0.0, top_sum = 0.0;
    for (u32 b = 0; b < BC::Bins; ++b) {
        all += double(stats.pixels[CAUSTICS_W_BIN_COUNT + b]);
    }
    for (u32 b = 0; b < BC::Bins; ++b) {
        const double n = double(stats.pixels[CAUSTICS_W_BIN_COUNT + b]);
        const double ratio = double(stats.pixels[CAUSTICS_W_BIN_RATIO + b]) / CAUSTICS_MODEL_SCALE / std::max(1.0, n);
        used += size_t(std::max(0, std::snprintf(bins + used, sizeof(bins) - used, "%s%.0f %.2f",
                                                 b ? ", " : "", n / reads, ratio)));
        used = std::min(used, sizeof(bins) - 1);
        const u32 from_top = BC::Bins - 1 - b;
        if (top_n < 0.1 * all) {
            top_n += double(stats.pixels[CAUSTICS_W_BIN_COUNT + from_top]);
            top_sum += double(stats.pixels[CAUSTICS_W_BIN_RATIO + from_top]) / CAUSTICS_MODEL_SCALE;
        }
    }
    BbReport::Printf("Water caustics (r107d): a dispatch: lamp model over own by modelled light (px ratio, "
                     "<2^-10, 2 stops a bin, >=1): %s; brightest tenth (%.0f px) %.2f; look %.2f, %.0f px\n",
                     bins, top_n / reads, top_sum / std::max(1.0, top_n), double(BC::LookOf(knobs)),
                     px(CAUSTICS_W_LOOK));
    // r107e: the puddles (a dispatch: means over every dispatch read)
    double candidates = 0.0;
    for (u32 i = 0; i < BC::HeightBins; ++i) {
        candidates += double(stats.pixels[CAUSTICS_W_HEIGHTS + i]);
    }
    BbReport::Printf("Water caustics (r107e): puddles: %u passes measured, %u with lamps; %.0f candidates "
                     "a dispatch; plane %s y %.2f; guard: %llu up-facing on it, %llu wet (%.2f, refused "
                     "above %.2f); %u calls no plane, %u unchecked or refused\n",
                     stats.puddle_measured, stats.puddle_lamps, candidates / reads,
                     puddle_found ? (puddle_checked ? "checked" : "unchecked") : "none", double(puddle_y),
                     static_cast<unsigned long long>(stats.puddle_ground),
                     static_cast<unsigned long long>(stats.puddle_wet),
                     double(stats.puddle_wet) / std::max(1.0, double(stats.puddle_ground)),
                     double(BC::PuddleMaxWet), stats.puddle_none, stats.puddle_floor);
    if (knobs.world > 0.0f) {
        // r107f: the world map and the light under the water (a dispatch: means over every dispatch read)
        BbReport::Printf("Water caustics (r107f): world map (bed %.2f): %u dispatches with it, %u new plane "
                         "generations (now %u, plane y %.2f); a dispatch: %.0f cells written as water, %.0f "
                         "as dry; lamp crossings the screen cannot see taken from the map: %.0f as water, "
                         "%.0f as dry; light through the water %.0f px (mirrored plane), ripple on %.0f px "
                         "(puddles)\n",
                         double(knobs.world), stats.world_draws, stats.world_changes, world_gen,
                         double(world_plane), px(CAUSTICS_W_MAP_WATER), px(CAUSTICS_W_MAP_DRY),
                         px(CAUSTICS_W_MAP_RESCUED_WATER), px(CAUSTICS_W_MAP_RESCUED_DRY), px(CAUSTICS_W_BED),
                         px(CAUSTICS_W_BED_PUDDLE));
    }
    // bbport (r130b_water-moves): the moving water (a moving dispatch: means over the dispatches that had the flag)
    const bool indoor = IndoorAmbient();
    if (indoor) {
        const double dt = BC::Motion::UsedDt(ambient.raw_dt);
        BbReport::Printf("Water ambient (r133c): indoor strength %.2f, steepness %.5f, frame %u, "
                         "dt raw %.6f used %.6f s, rate %.3f, longest phase %.6f step %.6f rad, "
                         "water wind 0, glint 0, rings %u, raw agitation observer disabled, plane %.3f "
                         "(no-plane %u), warp dispatches %u (%u ambient-only), readbacks %u, "
                         "eligible px %llu, kept px %llu in the readbacks\n",
                         double(motion_strength), double(ambient.state.steep), ambient.frame, ambient.raw_dt,
                         dt, AmbientRate(), ambient.state.phase[0],
                         BC::Motion::Omega(BC::Motion::Wavelength[0]) * (dt * AmbientRate()),
                         ambient.state.count, double(last_plane), stats.no_plane,
                         stats.warp_dispatches, stats.motion_only, stats.warp_reads,
                         static_cast<unsigned long long>(stats.warp_px),
                         static_cast<unsigned long long>(stats.warp_kept));
    } else if (motion_strength > 0.0f || stats.motion_dispatches != 0) {
        const double moving = std::max(1.0, double(stats.motion_dispatches));
        BbReport::Printf("Water motion (r130b): %u dispatches moved; waves toward %.0f deg, amplitude x%.2f, wind %.2f m/s; "
                         "hunter %s, %u steps, %u landings, %u rings live; water px moved %.0f, ring px %.0f a dispatch; "
                         "%u strength changes\n",
                         stats.motion_dispatches, BC::Motion::HeadingDeg(motion), double(motion.amp), motion.wind_speed,
                         stats.hunter_read ? "read" : "not read", stats.steps, stats.landings, motion.count,
                         double(stats.pixels[CAUSTICS_W_MOTION_WATER]) / moving, double(stats.ring_px) / moving, motion_changes);
    }
    // bbport (r130e_sewer-water-moves): the rippled reflection (means over the dispatches whose counts were read)
    if (!indoor && (motion_strength > 0.0f || stats.warp_dispatches != 0)) {
        const double warps = std::max(1.0, double(stats.warp_reads));
        char bed[80];
        if (world_env_set) {
            std::snprintf(bed, sizeof(bed), "from BB_CAUSTICS_WORLD=%.2f", double(knobs.world));
        } else {
            std::snprintf(bed, sizeof(bed), "%s", knobs.world > 0.0f ? "on with the motion (BB_CAUSTICS_WORLD unset)" : "off");
        }
        BbReport::Printf("%s: %u warp dispatches, %u motion-only; a dispatch: %.0f water px warped, %.0f kept (source not water), "
                         "band %.0f%% of rows; bed light %s\n",
                         BC::Motion::Warp::LogTag, stats.warp_dispatches, stats.motion_only, double(stats.warp_px) / warps,
                         double(stats.warp_kept) / warps,
                         100.0 * double(stats.warp_rows) / std::max(1.0, double(stats.warp_height)), bed);
    }
    // bbport (r128b_lrt-caustics-water): the strengths now and how often the setting moved them
    BbReport::Printf("Water caustics (r128b): strengths now sun %.2f, lamps %.2f; %u changes of them since the "
                     "start, %u passes skipped with both at 0\n",
                     double(knobs.strength), double(knobs.lamp_strength), strength_changes, idle_passes);
    stats = {};
}

} // namespace Vulkan
