// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string_view>

namespace Vulkan::BottleMotionSetup {

enum class Mode { Setup, Sweep };
enum class StageResult { Staged, Repeated, Busy, Stale, Foreign, Invalid };
enum class EventKind { None, Ack, Select, Refusal };
enum class Phase { Setup, Early, Middle, Late, Settle };

struct Arm {
    std::uint16_t run{};
    std::uint32_t serial{};
    Mode mode{Mode::Setup};
    bool on{};
    bool operator==(const Arm&) const = default;
};

template <class T>
bool Decimal(std::string_view text, T& out) {
    if (text.empty()) return false;
    const auto* end = text.data() + text.size();
    const auto result = std::from_chars(text.data(), end, out);
    return result.ptr == end && result.ec == std::errc{};
}

inline bool ParseArm(std::string_view text, Arm& result) {
    if (text.empty() || text.size() > 32) return false;
    const auto next = [&] {
        const auto slash = text.find('/');
        if (slash == text.npos) return std::string_view{};
        const auto field = text.substr(0, slash);
        text.remove_prefix(slash + 1);
        return field;
    };
    Arm parsed{};
    if (!Decimal(next(), parsed.run) || !parsed.run ||
        !Decimal(next(), parsed.serial) || !parsed.serial ||
        parsed.serial > 99'999'999) return false;
    const auto mode = next();
    if ((mode != "setup" && mode != "sweep") || (text != "0" && text != "1")) return false;
    parsed.mode = mode == "setup" ? Mode::Setup : Mode::Sweep;
    parsed.on = text == "1";
    result = parsed;
    return true;
}

// Supply actual camera/render state once per eligible main scene. qpc_ns must be the
// WorkflowPresent/host monotonic QPC clock. Fixtures stay 1920x1080 DLSS -> 3840x2160.
struct NativeFrame {
    std::uint64_t scene{}, qpc_ns{};
    std::array<float, 12> view{};
    std::array<float, 4> projection{};
    std::array<float, 2> jitter{};
    std::uint32_t input_width{}, input_height{}, output_width{}, output_height{};
    bool view_valid{}, effective_master{}, exposure_locked{};
};

struct Observation {
    EventKind kind{};
    Arm arm{};
    NativeFrame frame{};
    Phase phase{Phase::Setup};
    std::uint32_t ordinal{};
    bool complete{};
    std::array<double, 2> receiver{}, opaque{}; // continuous unjittered 4K pixel edges
    double left_travel{};
    const char* why{};
};

inline constexpr std::array<double, 3> Receiver{1.042861220, .608998623, .523141301};
inline constexpr std::array<double, 3> Opaque{-1.127544597, .523989407, 2.428067142};

class Scheduler {
public:
    explicit Scheduler(std::uint16_t run) : run_{run} {}

    StageResult Stage(const Arm& arm, std::uint64_t qpc_ns) {
        if (!arm.run || !arm.serial || arm.serial > 99'999'999 || !qpc_ns ||
            (arm.mode != Mode::Setup && arm.mode != Mode::Sweep)) return StageResult::Invalid;
        if (arm.run != run_) return StageResult::Foreign;
        if (arm == arm_) return StageResult::Repeated;
        if (arm.serial <= arm_.serial || qpc_ns < last_qpc_) return StageResult::Stale;
        if (active_) return StageResult::Busy;
        if (arm.mode == Mode::Setup && setup_taken_[arm.on ? 1 : 0]) return StageResult::Stale;
        arm_ = arm;
        staged_ns_ = qpc_ns;
        ack_ns_ = 0;
        phase_ = phase_samples_ = stable_frames_ = 0;
        last_receiver_ = last_opaque_ = base_receiver_ = base_opaque_ = {};
        previous_selected_scene_ = 0;
        active_ = true;
        return StageResult::Staged;
    }

    Observation Observe(const NativeFrame& frame) {
        if (!active_) return {};
        if (!frame.scene || !frame.qpc_ns || frame.qpc_ns < staged_ns_ ||
            frame.qpc_ns <= last_qpc_ || frame.scene <= last_scene_) {
            return Refuse(frame, "stale-or-repeated-native-frame");
        }
        last_qpc_ = frame.qpc_ns;
        last_scene_ = frame.scene;

        const auto deadline = ack_ns_ ? ack_ns_ + SweepTimeoutNs : staged_ns_ + AckTimeoutNs;
        if (frame.qpc_ns > deadline) return Refuse(frame, ack_ns_ ? "motion-timeout" : "native-ack-timeout");
        std::array<double, 2> receiver{}, opaque{};
        const bool suitable = Fixture(frame) && Project(frame, Receiver, receiver) &&
                              Project(frame, Opaque, opaque);
        if (!ack_ns_) {
            if (!suitable || frame.effective_master != arm_.on || !frame.exposure_locked) return {};
            ack_ns_ = frame.qpc_ns;
            last_receiver_ = base_receiver_ = receiver;
            last_opaque_ = base_opaque_ = opaque;
            return {EventKind::Ack, arm_, frame, Phase::Setup, 0, false, receiver, opaque, 0};
        }
        if (!suitable || !frame.exposure_locked || frame.effective_master != arm_.on)
            return Refuse(frame, "effective-view-master-or-exposure-changed");

        const double travel = base_receiver_[0] - receiver[0];
        const double control_travel = base_opaque_[0] - opaque[0];
        const double receiver_step = Displacement(receiver, last_receiver_);
        const double opaque_step = Displacement(opaque, last_opaque_);
        const double forward = last_receiver_[0] - receiver[0];
        last_receiver_ = receiver;
        last_opaque_ = opaque;
        if (arm_.mode == Mode::Setup) {
            if (frame.qpc_ns > ack_ns_ + SetupTimeoutNs ||
                Displacement(receiver, base_receiver_) > HeldTolerance ||
                Displacement(opaque, base_opaque_) > HeldTolerance)
                return Refuse(frame, "setup-hold-changed");
            setup_taken_[arm_.on ? 1 : 0] = true;
            active_ = false;
            return {EventKind::Select, arm_, frame, Phase::Setup, 1, true, receiver, opaque, travel};
        }

        if (travel < -1.5 || std::abs(travel - control_travel) > 5.0 ||
            std::abs(receiver[1] - base_receiver_[1]) > 8.0 ||
            std::abs(opaque[1] - base_opaque_[1]) > 8.0)
            return Refuse(frame, "pan-direction-or-control-departure");
        if (phase_ < 3) {
            const auto threshold = Windows[phase_];
            if (travel > threshold[1]) return Refuse(frame, "missed-travel-window");
            if (travel < threshold[0] || forward < .12) {
                if (phase_samples_) return Refuse(frame, "motion-pair-broken");
                return {};
            }
        } else {
            stable_frames_ = receiver_step <= .25 && opaque_step <= .25 ? stable_frames_ + 1 : 0;
            if (stable_frames_ < 3) {
                if (phase_samples_) return Refuse(frame, "settle-pair-broken");
                return {};
            }
        }
        if (phase_samples_ && frame.scene != previous_selected_scene_ + 1)
            return Refuse(frame, "selected-scenes-not-consecutive");
        previous_selected_scene_ = frame.scene;
        const auto phase = static_cast<Phase>(phase_ + 1);
        const auto ordinal = ++phase_samples_;
        if (phase_samples_ == 2) {
            ++phase_;
            phase_samples_ = 0;
        }
        if (phase_ == 4) active_ = false;
        return {EventKind::Select, arm_, frame, phase, ordinal, !active_, receiver, opaque, travel};
    }

    // Use if eligible camera input stops completely. Native clocks still advance on
    // the scheduler path. Repeated/foreign file contents cannot renew the deadline.
    Observation Expire(std::uint64_t qpc_ns) {
        if (!active_) return {};
        const auto deadline = ack_ns_ ? ack_ns_ +
            (arm_.mode == Mode::Setup ? SetupTimeoutNs : SweepTimeoutNs) : staged_ns_ + AckTimeoutNs;
        if (qpc_ns <= deadline) return {};
        NativeFrame stamp{.scene=last_scene_, .qpc_ns=qpc_ns};
        return Refuse(stamp, ack_ns_ ? "observation-timeout" : "native-ack-timeout");
    }

    static constexpr std::uint64_t AckTimeoutNs = 1'500'000'000;
    static constexpr std::uint64_t SweepTimeoutNs = 3'000'000'000;
    static constexpr std::uint64_t SetupTimeoutNs = 250'000'000;
    static constexpr double HeldTolerance = 1.25;

private:
    static constexpr std::array<std::array<double, 2>, 3> Windows{{{8, 14}, {17, 23}, {26, 35}}};

    static bool Fixture(const NativeFrame& f) {
        if (!f.view_valid || f.input_width != 1920 || f.input_height != 1080 ||
            f.output_width != 3840 || f.output_height != 2160 ||
            f.projection[0] == 0 || f.projection[1] == 0) return false;
        for (float v : f.view) if (!std::isfinite(v)) return false;
        for (float v : f.projection) if (!std::isfinite(v)) return false;
        for (float v : f.jitter) if (!std::isfinite(v) || std::abs(v) > .5) return false;
        return true;
    }

    static bool Project(const NativeFrame& f, const std::array<double, 3>& point,
                        std::array<double, 2>& xy) {
        std::array<double, 3> v{};
        for (std::size_t r = 0; r < v.size(); ++r) {
            v[r] = f.view[r * 4 + 3];
            for (std::size_t c = 0; c < point.size(); ++c) v[r] += f.view[r * 4 + c] * point[c];
        }
        if (!(v[2] > .1)) return false;
        xy = {(v[0] * f.projection[0] / v[2] * .5 + .5) * f.output_width,
              (v[1] * f.projection[1] / v[2] * .5 + .5) * f.output_height};
        return xy[0] >= 56 && xy[0] < f.output_width - 56 &&
               xy[1] >= 56 && xy[1] < f.output_height - 56;
    }

    static double Displacement(const std::array<double, 2>& a, const std::array<double, 2>& b) {
        return std::hypot(a[0] - b[0], a[1] - b[1]);
    }

    Observation Refuse(const NativeFrame& f, const char* reason) {
        active_ = false;
        return {.kind=EventKind::Refusal, .arm=arm_, .frame=f, .complete=true, .why=reason};
    }

    const std::uint16_t run_;
    Arm arm_{};
    std::array<bool, 2> setup_taken_{};
    bool active_{};
    std::uint64_t staged_ns_{}, ack_ns_{}, last_scene_{}, last_qpc_{}, previous_selected_scene_{};
    std::uint32_t phase_{}, phase_samples_{}, stable_frames_{};
    std::array<double, 2> base_receiver_{}, base_opaque_{}, last_receiver_{}, last_opaque_{};
};

inline void Log(const Observation& o) {
    if (o.kind == EventKind::None) return;
    const auto mode = o.arm.mode == Mode::Setup ? "setup" : "sweep";
    const auto stamp = [](std::uint64_t n) { return static_cast<unsigned long long>(n); };
    const auto event = o.kind == EventKind::Ack ? "arm-effective" :
                       o.kind == EventKind::Select ? "selected" : "refused";
    const char* const names[]{"setup", "early", "middle", "late", "settle"};
    std::printf("[bottle-motion-t203] event=%s run=%u serial=%u mode=%s on=%u scene=%llu "
                "qpc_ns=%llu phase=%s ordinal=%u complete=%u travel_px=%.6f why=%s\n",
                event, unsigned(o.arm.run), unsigned(o.arm.serial), mode, unsigned(o.arm.on),
                stamp(o.frame.scene), stamp(o.frame.qpc_ns), names[unsigned(o.phase)],
                unsigned(o.ordinal), unsigned(o.complete), o.left_travel, o.why ? o.why : "-");
    if (o.kind != EventKind::Select) return;
    std::printf("[bottle-motion-t203] event=projection run=%u serial=%u scene=%llu "
                "receiver=(%.6f,%.6f) opaque=(%.6f,%.6f) jitter=(%.9g,%.9g) "
                "proj=(%.9g,%.9g,%.9g,%.9g) input=%ux%u output=%ux%u exposure_locked=%u\n",
                unsigned(o.arm.run), unsigned(o.arm.serial), stamp(o.frame.scene),
                o.receiver[0], o.receiver[1], o.opaque[0], o.opaque[1], o.frame.jitter[0],
                o.frame.jitter[1], o.frame.projection[0], o.frame.projection[1],
                o.frame.projection[2], o.frame.projection[3], o.frame.input_width, o.frame.input_height,
                o.frame.output_width, o.frame.output_height, unsigned(o.frame.exposure_locked));
    for (std::size_t row=0; row<3; ++row) {
        const auto* f=o.frame.view.data()+row*4;
        std::printf("[bottle-motion-t203] event=view run=%u serial=%u scene=%llu row=%zu "
                    "value=(%.9g,%.9g,%.9g,%.9g)\n", unsigned(o.arm.run), unsigned(o.arm.serial),
                    stamp(o.frame.scene), row, f[0],f[1],f[2],f[3]);
    }
}
} // namespace Vulkan::BottleMotionSetup

