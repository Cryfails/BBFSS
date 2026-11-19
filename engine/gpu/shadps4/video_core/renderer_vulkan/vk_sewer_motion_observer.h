// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <mutex>
#include <optional>
#include <utility>

#include "../../../bbgpu.h"
#include "bbport_live_knobs.h"
#include "bbport_test_camera_run.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"

namespace BbEngine { bool world_player_position(float pos[3]); }

namespace Vulkan::SewerMotion {

using Vec2 = std::array<float, 2>;
using Vec3 = std::array<float, 3>;
using Pixels = std::array<Vec2, 3>;
using HalfPixel = std::array<u16, 4>;
using Samples = std::array<HalfPixel, 3>;
using Patches = std::array<std::array<HalfPixel, 9>, 3>;

inline bool Enabled() {
    static const bool enabled = [] {
        const char* mode = std::getenv("BB_SEWER_MOTION_SERIES");
        return mode && mode[0] == '1' && mode[1] == '\0';
    }();
    return enabled;
}

inline bool FinalEnabled() {
    static const bool enabled = [] {
        const char* mode = std::getenv("BB_SEWER_MOTION_FINAL");
        return Enabled() && mode && mode[0] == '1' && mode[1] == '\0';
    }();
    return enabled;
}

inline bool PanEnabled() {
    static const bool enabled = [] {
        const char* mode = std::getenv("BB_SEWER_MOTION_PAN");
        return Enabled() && mode && mode[0] == '1' && mode[1] == '\0';
    }();
    return enabled;
}
inline bool PoseFeedEnabled() {
    static const bool enabled = [] {
        const char* mode = std::getenv("BB_SEWER_MOTION_POSE_FEED");
        return PanEnabled() && mode && mode[0] == '1' && mode[1] == '\0';
    }();
    return enabled;
}

inline bool PadLatchEnabled() {
    static const bool enabled = [] {
        const char* mode = std::getenv("BB_SEWER_PAD_LATCH");
        return PanEnabled() && mode && std::strcmp(mode, "1") == 0;
    }();
    return enabled;
}

inline bool WarpAdmissionEnabled() {
    static const bool enabled = [] {
        const char* mode = std::getenv("BB_SEWER_MOTION_WARP_ADMISSION");
        return PanEnabled() && mode && std::strcmp(mode, "1") == 0;
    }();
    return enabled;
}

inline bool SampleArcEnabled() {
    static const bool enabled = [] {
        const char* mode = std::getenv("BB_SEWER_WARP_SAMPLE_ARC");
        return WarpAdmissionEnabled() && mode && std::strcmp(mode, "1") == 0;
    }();
    return enabled;
}

inline bool PadBoundaryEnabled() {
    static const bool enabled = [] {
        const char* mode = std::getenv("BB_SEWER_PAD_BOUNDARY");
        return PadLatchEnabled() && mode && std::strcmp(mode, "1") == 0;
    }();
    return enabled;
}

inline u64 PadHex(const char* text) {
    if (std::strspn(text, "0123456789abcdef") != 16) return 0;
    u64 value{};
    const auto parsed = std::from_chars(text, text + 16, value, 16);
    return parsed.ec == std::errc{} && parsed.ptr == text + 16 ? value : 0;
}

inline u64 PadLatchCommand() {
    static const u64 command = [] {
        const char* text = std::getenv("BB_SEWER_PAD_LATCH_COMMAND");
        return text && std::strlen(text) == 16 ? PadHex(text) : 0;
    }();
    return command;
}

inline constexpr std::array<Vec3, 3> Anchors{{
    {17.39343f, -29.98707f, 104.08517f},
    {16.77602f, -29.93734f, 105.27851f},
    {16.67675f, -29.00756f, 101.85579f},
}};
inline constexpr std::array<Vec3, 2> EndpointEyes{{
    {13.569f, -27.301f, 108.482f},
    {13.76346f, -27.300787f, 108.166962f},
}};

inline bool Project(const CameraMotion::Matrices& camera, Pixels& output) {
    if (!camera.valid || std::abs(camera.proj[0] - 1.428f) > 0.03f ||
        std::abs(camera.proj[1] + 2.539f) > 0.03f || !(camera.proj[2] > 0.f) ||
        !(camera.proj[3] < 0.f)) return false;
    for (u32 i = 0; i < Anchors.size(); ++i) {
        const auto& p = Anchors[i];
        const auto axis = [&](u32 row) {
            const auto* m = &camera.view[4 * row];
            return p[0] * m[0] + p[1] * m[1] + p[2] * m[2] + m[3];
        };
        const float z = axis(2);
        if (!(z > 0.1f && z < 45.f)) return false;
        const float x = (axis(0) * camera.proj[0] / z + 1.f) * 1920.f;
        const float y = (axis(1) * camera.proj[1] / z + 1.f) * 1080.f;
        if (!(x >= 4.f && x < 3836.f && y >= 4.f && y < 2156.f)) return false;
        output[i] = {x, y};
    }
    return true;
}

inline float Distance(Vec3 a, Vec3 b) {
    return std::hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}
inline float Distance(Vec2 a, Vec2 b) {
    return std::hypot(a[0] - b[0], a[1] - b[1]);
}
inline Vec3 Eye(const CameraMotion::Matrices& m) {
    return {m.inv_view[3], m.inv_view[7], m.inv_view[11]};
}

struct Pose {
    u64 scene{};
    u32 frame{};
    CameraMotion::Matrices camera{};
    Pixels output{};

    int Endpoint() const {
        for (int i = 0; i < 2; ++i) if (Distance(Eye(camera), EndpointEyes[i]) < .09f) return i;
        return -1;
    }
    bool InCorridor() const {
        const auto eye = Eye(camera);
        return eye[0] >= 13.43f && eye[0] <= 13.91f && eye[1] >= -27.42f && eye[1] <= -27.18f &&
               eye[2] >= 108.02f && eye[2] <= 108.63f &&
               std::abs(camera.inv_view[2] - .51247f) < .025f &&
               std::abs(camera.inv_view[6] + .33134f) < .025f &&
               std::abs(camera.inv_view[10] + .79221f) < .025f;
    }
    bool Consecutive(const Pose& other) const {
        return scene + 1 == other.scene && frame + 1 == other.frame;
    }
    bool RestedTo(const Pose& other) const {
        if (!Consecutive(other)) return false;
        for (u32 i = 0; i < output.size(); ++i) {
            if (!(Distance(output[i], other.output[i]) < .5f)) return false;
        }
        return true;
    }
    bool WetDisjoint(const Pixels& other) const {
        return Distance(output[0], other[0]) > 25.f && Distance(output[1], other[1]) > 25.f;
    }
};

inline constexpr float Degrees = 57.29577951308232f;
inline Vec3 Forward(const Pose& p) {
    return {p.camera.inv_view[2], p.camera.inv_view[6], p.camera.inv_view[10]};
}
inline float Heading(const Pose& pose) {
    const auto f = Forward(pose);
    return std::atan2(f[0], f[2]) * Degrees;
}
inline float Pitch(const Pose& pose) {
    return std::asin(Forward(pose)[1]) * Degrees;
}
inline float RelativeYaw(const Pose& a, const Pose& p) {
    return std::remainder(Heading(p) - Heading(a), 360.f);
}
inline bool MatchPoint(Vec3 a, Vec3 b, float tolerance) {
    for (u32 i = 0; i < a.size(); ++i) {
        if (!(std::abs(a[i] - b[i]) <= tolerance)) return false;
    }
    return true;
}
inline bool PanEyeFits(const Pose& a, const Pose& p, Vec3 hunter, float yaw) {
    const Vec3 origin = Eye(a.camera), candidate = Eye(p.camera);
    const float cos = std::cos(yaw / Degrees), sin = std::sin(yaw / Degrees);
    const float x = origin[0] - hunter[0], z = origin[2] - hunter[2];
    const Vec3 sweep{cos * x + sin * z - x, 0.f, -sin * x + cos * z - z};
    float min_fraction = 0.f, max_fraction = 1.f;
    for (u32 i = 0; i < origin.size(); ++i) {
        constexpr float tolerance = .01f;
        const float offset = candidate[i] - origin[i];
        if (std::abs(sweep[i]) < .00001f) {
            if (!(std::abs(offset) <= tolerance)) return false;
            continue;
        }
        const float l = (offset - tolerance) / sweep[i], r = (offset + tolerance) / sweep[i];
        min_fraction = std::max(min_fraction, std::min(l, r));
        max_fraction = std::min(max_fraction, std::max(l, r));
    }
    return min_fraction <= max_fraction;
}
inline float WetForward(const Pose& from, const Pose& to) {
    return std::min(to.output[0][0] - from.output[0][0], to.output[1][0] - from.output[1][0]);
}

inline bool Continuous(const Pose& from, const Pose& to) {
    return from.Consecutive(to) && Distance(Eye(from.camera), Eye(to.camera)) < .10f &&
           Distance(from.output[0], to.output[0]) < 45.f && Distance(from.output[1], to.output[1]) < 45.f;
}

// Reduced-WARP samples use the actual registered ground pose. The full optical arc keeps its own bounds.
struct SampleArc {
    static constexpr float Begin = 4.f, End = 5.f, Step = .04f, StopA = 8.f, StopB = 4.f, Cap = 10.f;

    static bool Moving(const Pose& from, const Pose& to, float previous_yaw, float yaw) {
        return Continuous(from, to) && yaw < previous_yaw && WetForward(from, to) > Step;
    }

    static bool Settled(const Pose& from, const Pose& to, float previous_yaw, float yaw) {
        return from.RestedTo(to) && std::abs(yaw - previous_yaw) <= .002f &&
               Distance(from.output[0], to.output[0]) < .03f && Distance(from.output[1], to.output[1]) < .03f;
    }

    static bool InBand(float from_a) { return from_a >= Begin && from_a <= End; }
    static bool StopAt(float from_a, float from_b) { return from_a >= StopA && from_b >= StopB; }
};

inline bool MovingToward(const Pose& from, const Pose& to, const Pixels& destination) {
    if (!Continuous(from, to) || !(Distance(Eye(from.camera), Eye(to.camera)) > .0001f)) return false;
    for (u32 i = 0; i < 2; ++i) {
        const auto& a = from.output[i];
        const auto& b = to.output[i];
        const auto& c = destination[i];
        const float dot = (b[0] - a[0]) * (c[0] - a[0]) + (b[1] - a[1]) * (c[1] - a[1]);
        if (Distance(a, b) <= 1.f || !(dot > 0.f)) return false;
    }
    return true;
}

inline bool Reversed(const Pose& from, const Pose& to, const Pixels& destination) {
    return Distance(to.output[0], destination[0]) - Distance(from.output[0], destination[0]) > 1.f &&
           Distance(to.output[1], destination[1]) - Distance(from.output[1], destination[1]) > 1.f;
}

inline bool Coherent(const Pose& before, const Pose& current, const Pose& after, const Pixels& destination) {
    if (!MovingToward(before, current, destination) || !MovingToward(current, after, destination)) return false;
    const auto a = Eye(before.camera), b = Eye(current.camera), c = Eye(after.camera);
    const float eye_dot = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) +
                          (b[2] - a[2]) * (c[2] - b[2]);
    if (!(eye_dot > 0.f)) return false;
    for (u32 i = 0; i < 2; ++i) {
        const auto x = before.output[i], y = current.output[i], z = after.output[i];
        if (!((y[0] - x[0]) * (z[0] - y[0]) + (y[1] - x[1]) * (z[1] - y[1]) > 0.f)) return false;
    }
    return true;
}

struct Key {
    u64 request{}, scene{}, loading{}, generation{};
    u32 frame{};
    char checkpoint{};
    bool enabled{};
};

struct Resource {
    u32 id{};
    u64 uid{};
    vk::Image image{};
    vk::ImageView view{};
    vk::ImageAspectFlags aspect{};
};

struct WarpStamp {
    Resource color, depth, cb2, bed;
    vk::Semaphore timeline{};
    u64 tick{}, copy_write{};
    std::array<vk::Offset2D, 3> px{};
    Vec2 jitter{};
};

// The view and write are those actually bound by the ordinary merge. A later consumer
// needs its own writer coverage and lifetime proof before it may publish a prepared frame.
struct MergeToken {
    Key key{};
    Resource destination{};
    vk::Image output{};
    vk::ImageView output_view{};
    vk::Semaphore timeline{};
    u64 tick{}, write{};
    u32 mode{}, alpha{};
    float sharpen{};
    bool folded{};
};

enum Retired : unsigned { Transport = 1, Warp = 2, Vendor = 4, All = 7, Presenter = 8 };

struct Checkpoint {
    Checkpoint(Key stamp, Pose selected) : key(stamp), pose(selected), needs_present(FinalEnabled()) {}
    const Key key;
    const Pose pose;
    const bool needs_present;

    WarpStamp warp;
    MergeToken merge;
    Samples post_warp{};
    Samples vendor_input{};
    Patches vendor_output{};
    bool vendor_values{}, has_merge{};
    bool vendor_claimed{}; // render owner only
    const char* vendor_error{};
    std::atomic<unsigned> retired{};
    std::atomic<const char*> refusal{};
    std::atomic<bool> present_claimed{};
    std::atomic<const char*> presentation{};

    void Refuse(const char* why) {
        const char* empty = nullptr;
        if (refusal.compare_exchange_strong(empty, why)) {
            std::printf("[sewer-motion] event=refused request=%llu checkpoint=%c frame=%u why=%s\n",
                        static_cast<unsigned long long>(key.request), key.checkpoint, key.frame, why);
        }
    }
    void Retire(Retired part) { retired.fetch_or(part, std::memory_order_acq_rel); }
    bool ValidWarpScope() const {
        // These bindings are published by the qualified reduced Shade/COPY/WARP path.
        // Check them only after both existing transport and WARP readbacks have retired.
        const auto valid = [](const Resource& r, vk::ImageAspectFlags aspect) {
            return r.uid && r.image && r.view && r.aspect == aspect;
        };
        constexpr auto color = vk::ImageAspectFlagBits::eColor;
        constexpr auto depth = vk::ImageAspectFlagBits::eDepth;
        if (key.scene != pose.scene || key.frame != pose.frame || !pose.camera.valid ||
            !warp.timeline || !warp.tick || !warp.copy_write ||
            !valid(warp.color, color) || !valid(warp.cb2, color) || !valid(warp.depth, depth) ||
            !valid(warp.bed, key.enabled ? color : depth)) return false;
        if (key.enabled)
            return warp.bed.image != warp.depth.image && warp.bed.image != warp.color.image &&
                   warp.bed.image != warp.cb2.image;
        return warp.bed.id == warp.depth.id && warp.bed.uid == warp.depth.uid &&
               warp.bed.image == warp.depth.image && warp.bed.view == warp.depth.view;
    }
    bool PresentationRetired() const { return presentation.load(std::memory_order_acquire) != nullptr; }
    void FinishPresentation(bool ok, const char* why, bool log = true) {
        const char* prior = nullptr;
        if (!presentation.compare_exchange_strong(prior, ok ? "fenced" : "unavailable")) return;
        if (!ok && log) {
            std::printf("[sewer-motion] event=final-refused request=%llu checkpoint=%c frame=%u why=%s\n",
                        static_cast<unsigned long long>(key.request), key.checkpoint, key.frame, why);
        }
        Retire(Presenter);
    }
    void VendorRefused(const char* why) {
        vendor_claimed = true;
        vendor_error = why;
        Retire(Vendor);
    }
};

inline std::mutex pending_mutex;
inline std::weak_ptr<Checkpoint> pending_checkpoint;

inline void Publish(const std::shared_ptr<Checkpoint>& checkpoint) {
    std::lock_guard lock(pending_mutex);
    pending_checkpoint = checkpoint;
}

inline std::shared_ptr<Checkpoint> Find(vk::Semaphore timeline, u32 frame, u64 loading, u64 generation) {
    if (!Enabled()) return {};
    std::lock_guard lock(pending_mutex);
    auto pending = pending_checkpoint.lock();
    if (!pending || pending->refusal.load() || pending->warp.timeline != timeline ||
        pending->key.frame != frame || pending->key.loading != loading ||
        pending->key.generation != generation) return {};
    return pending;
}

// Call on the render encoder, before any subsequent write to the merge destination.
inline std::optional<MergeToken> CurrentMerge(vk::Semaphore timeline, u32 frame, u64 loading, u64 generation) {
    const auto checkpoint = Find(timeline, frame, loading, generation);
    if (!checkpoint || !checkpoint->has_merge) return std::nullopt;
    return checkpoint->merge;
}

namespace Alternate {

inline bool Enabled() {
    static const bool enabled = [] {
        const char* value = std::getenv("BB_SEWER_ALT_SUPPORT");
        return value && std::strcmp(value, "1") == 0;
    }();
    return enabled && BbTestCamera::SewerEpochEnabled() && !SewerMotion::Enabled();
}

inline constexpr std::array<Vec3, 3> Supports{{
    {17.39343f, -29.98707f, 104.08517f},
    {16.8225578f, -29.9221569f, 105.2329826f},
    {16.67675f, -29.00756f, 101.85579f},
}};

// Exact vertex values from the two retained placed local meshes. The wet
// triangles are 16345 and 16674 in m007300 and the dry is 1047 in m007340.
inline constexpr std::array<std::array<Vec3, 3>, 3> Triangles{{
    {{{17.36204338f,-29.97734451f,104.64297485f}, {17.04206657f,-29.98824883f,104.11105347f},
      {17.44341660f,-29.98819160f,104.00776672f}}},
    {{{16.67854881f,-29.97530365f,105.24823761f}, {16.84255028f,-29.91571999f,105.21176910f},
      {16.78735733f,-29.93007469f,105.33962250f}}},
    {{{16.81847382f,-28.93480110f,102.23667145f}, {16.86531067f,-29.02526283f,102.21366882f},
      {16.34358215f,-29.02529335f,101.15969086f}}},
}};
using Cells = std::array<std::array<vk::Offset2D, 5>, 3>;
using Depth = std::array<std::array<u32, 5>, 3>;
using DVec = std::array<double, 3>;

inline DVec Cross(DVec a, DVec b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}
inline double Dot(DVec a, DVec b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}
inline DVec Difference(Vec3 a, Vec3 b) {
    return {double(a[0]) - b[0], double(a[1]) - b[1], double(a[2]) - b[2]};
}
inline double DepthAt(vk::Offset2D p, const CameraMotion::Matrices& camera, Vec2 jitter,
                      unsigned point, double plane, double& final) {
    const auto& v = camera.view;
    const double x = (2. * (p.x + .5 - jitter[0]) / 1920. - 1.) / camera.proj[0];
    const double y = (2. * (p.y + .5 - jitter[1]) / 1080. - 1.) / camera.proj[1];
    const DVec dir{x*v[0] + y*v[4] + v[8], x*v[1] + y*v[5] + v[9], x*v[2] + y*v[6] + v[10]};
    const auto eye = Eye(camera);
    const auto& tri = Triangles[point];
    const auto e1 = Difference(tri[1], tri[0]);
    const auto e2 = Difference(tri[2], tri[0]);
    const auto to_eye = Difference(eye, tri[0]);
    const auto det_axis = Cross(dir, e2);
    const auto v_axis = Cross(to_eye, e1);
    const double det = Dot(e1, det_axis);
    if (!(std::abs(det) > 1e-8)) return 0.;
    const double u = Dot(to_eye, det_axis) / det;
    const double w = Dot(dir, v_axis) / det;
    const double z = Dot(e2, v_axis) / det;
    if (!(u > 0. && w > 0. && u + w < 1. && z > .1 && z < 45.)) return 0.;
    final = point < 2 ? (plane - eye[1]) / dir[1] : z;
    return final > .1 && final <= z && (point == 2 || final < z) ? z : 0.;
}

inline bool Register(const CameraMotion::Matrices& camera, Vec2 jitter, Cells& cells) {
    constexpr Vec3 eye{16.0994836f,-27.5170894f,108.7680394f};
    constexpr Vec3 fwd{-0.119071089f,-0.273823947f,-0.954380691f};
    constexpr std::array<Vec2, 5> offsets{{{0,0}, {-1.75f,-1.75f}, {-1.75f,1.75f},
                                          {1.75f,-1.75f}, {1.75f,1.75f}}};
    if (!camera.valid || !(Distance(Eye(camera), eye) <= .06f) ||
        !(Distance(Vec3{camera.view[8], camera.view[9], camera.view[10]}, fwd) <= .0045f) ||
        !(std::abs(camera.proj[0] - 1.428f) <= .03f) || !(std::abs(camera.proj[1] + 2.539f) <= .03f) ||
        !(camera.proj[2] > 0.f && camera.proj[3] < 0.f) ||
        !(std::abs(jitter[0]) <= .5f && std::abs(jitter[1]) <= .5f)) return false;
    for (u32 i = 0; i < Supports.size(); ++i) {
        const auto w = Supports[i];
        const auto axis = [&](u32 row) {
            const float* m = camera.view.data() + row * 4;
            return w[0]*m[0] + w[1]*m[1] + w[2]*m[2] + m[3];
        };
        const float z = axis(2);
        if (!(z > .1f && z < 45.f)) return false;
        const float x = (axis(0) * camera.proj[0] / z + 1.f) * 960.f;
        const float y = (axis(1) * camera.proj[1] / z + 1.f) * 540.f;
        // Unchanged 112px display crop plus the retained even-grid alignment.
        if (!(x >= 29.f && x < 1893.f && y >= 29.f && y < 1053.f)) return false;
        for (u32 j = 0; j < offsets.size(); ++j) {
            cells[i][j] = {int(std::floor(x + jitter[0] + offsets[j][0])),
                           int(std::floor(y + jitter[1] + offsets[j][1]))};
            double final{};
            if (DepthAt(cells[i][j], camera, jitter, i, -29.59665, final) == 0.) return false;
            for (u32 k = 0; k < j; ++k) if (cells[i][j] == cells[i][k]) return false;
        }
    }
    return cells[0][0] != cells[1][0] && cells[0][0] != cells[2][0] && cells[1][0] != cells[2][0];
}

inline bool RawMatches(u32 raw, double expected, const CameraMotion::Matrices& camera) {
    const float value = std::bit_cast<float>(raw);
    return value > 0.f && value < 1.f && std::isfinite(expected) &&
           std::abs(double(camera.proj[3]) / (double(value) - camera.proj[2]) - expected) <= .025;
}
inline const char* DepthVerdict(const Depth& before, const Depth& after, const std::array<u32, 3>& native,
                               const Cells& cells, const CameraMotion::Matrices& camera, Vec2 jitter, float plane) {
    for (u32 i = 0; i < cells.size(); ++i) {
        if (before[i][0] != native[i]) return "native-r32f-center";
        for (u32 j = 0; j < cells[i].size(); ++j) {
            double final{};
            const double ground = DepthAt(cells[i][j], camera, jitter, i, plane, final);
            if (!ground || !RawMatches(before[i][j], ground, camera)) return "opaque-ground-depth";
            if (!RawMatches(after[i][j], final, camera)) return "water-or-dry-depth";
            if (i == 2 && before[i][j] != after[i][j]) return "dry-depth-rewrite";
        }
    }
    return nullptr;
}

inline const char* HdrVerdict(const std::array<Samples, 3>& hdr) {
    for (u32 i = 0; i < hdr[0].size(); ++i) {
        for (const auto& sample : hdr) {
            for (const auto half : sample[i]) if ((half & 0x7c00) == 0x7c00) return "nonfinite-hdr";
            if (sample[i][3] != hdr[0][i][3]) return "alpha-rewrite";
        }
        if (i == 2) {
            if (hdr[0][i] != hdr[1][i] || hdr[1][i] != hdr[2][i]) return "dry-hdr-rewrite";
        } else if (hdr[1][i] == hdr[2][i]) {
            return "wet-warp-no-measured-change";
        }
    }
    return nullptr;
}

struct Proof {
    Key key{};
    CameraMotion::Matrices camera{};
    Vec2 jitter{};
    Vec3 hunter{};
    Cells cells{};
    u64 original{}, alternate{}, depth_uid{};
    u32 depth_id{};
    // Render-thread facts, set before registering the readback retirement.
    bool commands{}, frame_end_seen{};
    u64 warp_tick{};
    std::atomic<bool> joined{}, fenced{}, terminal{};

    void Refuse(const char* why) {
        if (!terminal.exchange(true)) {
            std::printf("[sewer-alt-support] event=refused frame=%u scene=%llu tick=%llu why=%s\n",
                        key.frame, static_cast<unsigned long long>(key.scene),
                        static_cast<unsigned long long>(warp_tick), why);
        }
    }
    void Finish() {
        if (!joined.load() || !fenced.load() || terminal.exchange(true)) return;
        std::printf("[sewer-alt-support] event=held-fenced frame=%u scene=%llu tick=%llu loading=%llu generation=%llu "
                    "original=%llu alternate=%llu product=0 pixels=3 support=15\n", key.frame,
                    static_cast<unsigned long long>(key.scene), static_cast<unsigned long long>(warp_tick),
                    static_cast<unsigned long long>(key.loading), static_cast<unsigned long long>(key.generation),
                    static_cast<unsigned long long>(original), static_cast<unsigned long long>(alternate));
    }
};

inline std::shared_ptr<Proof> pending; // one lifetime per diagnostic process; accessed only on render thread

inline void Close(const CameraMotion::Matrices& camera, u64 scene, u32 frame, u64 loading,
                  u64 generation, bool reduced, u32 depth_id, u64 depth_uid) {
    const auto& sample = pending;
    if (!sample || std::exchange(sample->frame_end_seen, true)) return;
    const bool camera_same = camera.valid && camera.view == sample->camera.view &&
                             camera.inv_view == sample->camera.inv_view && camera.proj == sample->camera.proj;
    std::printf("[sewer-alt-support] event=frame-end frame=%u observed_present_frame=%u scene=%llu "
                "active_scene=%llu ground_depth=%u/%llu active_depth=%u/%llu camera_same=%u\n",
                sample->key.frame, frame, static_cast<unsigned long long>(sample->key.scene),
                static_cast<unsigned long long>(scene),
                sample->depth_id, static_cast<unsigned long long>(sample->depth_uid), depth_id,
                static_cast<unsigned long long>(depth_uid), unsigned(camera_same));
    if (!sample->commands || sample->key.scene != scene || sample->key.loading != loading ||
        sample->key.generation != generation || !reduced) {
        return sample->Refuse("frame-end-scope-or-commands");
    }
    if (!depth_uid || depth_id != sample->depth_id || depth_uid != sample->depth_uid)
        return sample->Refuse("frame-end-active-depth");
    BbTestCamera::SewerEpochReceipt epoch;
    if (!BbTestCamera::ReadSewerEpoch(scene, epoch) || epoch.original.epoch != sample->original ||
        epoch.alternate.epoch != sample->alternate || !(Distance(epoch.hunter, sample->hunter) <= .01f)) {
        return sample->Refuse("frame-end-r120-epoch-or-hunter");
    }
    if (!camera_same ||
        epoch.eye != Eye(camera) ||
        epoch.forward != Vec3{camera.view[8], camera.view[9], camera.view[10]}) {
        return sample->Refuse("frame-end-signed-camera");
    }
    sample->joined.store(true);
    sample->Finish();
}

} // namespace Alternate

struct Series {
    const u64 request, loading, generation;
    const u32 first_frame;
    const bool enabled;
    std::shared_ptr<Checkpoint> pending;
    std::array<std::shared_ptr<const Checkpoint>, 3> completed{};
    Pose older{}, last{};
    Pixels expected_end{};
    unsigned next{};
    int start_endpoint = -1;
    bool b_followed{}, failed{}, traveled{};
    std::optional<Pose> pan_a, pan_b;
    Vec3 pan_hunter{};
    bool pan_neutral_requested{};
    bool pad_release_seen{}, pad_armed{}, pad_return_logged{}, warp_a_admitted{};
    unsigned pad_neutral_before{}, pad_neutral_after{};
    BbSewerPadKey pad_key{};
    unsigned pad_boundary_calls{};
    BbSewerPadStatus pad_boundary_last{};
    bool pad_boundary_held{}, pad_boundary_reported{};
    u32 sample_arc_arm_frame{};
    bool sample_arc_refusal_logged{};
    BbSewerPadStatus sample_arc_status{};

    void SampleArcLog(const char* event, const char* reason, const Pose& prior, const Pose& current,
                      bool projected) const {
        if (!pan_a) return;
        const auto a = Eye(prior.camera), b = Eye(current.camera);
        const auto f = Forward(prior), g = Forward(current);
        const float yaw = RelativeYaw(*pan_a, current), previous_yaw = RelativeYaw(*pan_a, prior);
        const auto dx = [](const Pose& from, const Pose& to, unsigned i) {
            return double(to.output[i][0] - from.output[i][0]);
        };
        const unsigned elapsed = current.frame - first_frame;
        std::printf("[sewer-sample-arc] event=%s reason=%s request=%llu checkpoint=%c loading=%llu generation=%llu "
                    "frame=%u scene=%llu prior_frame=%u prior_scene=%llu arm_frame=%u projected=%u "
                    "eye=%.9g,%.9g,%.9g prior_eye=%.9g,%.9g,%.9g forward=%.9g,%.9g,%.9g "
                    "prior_forward=%.9g,%.9g,%.9g wet_a=%.9g,%.9g wet_b=%.9g,%.9g "
                    "step=%.9g,%.9g wet_distance=%.9g,%.9g min_a=%.9g min_b=%.9g min_step=%.9g "
                    "yaw=%.9g prior_yaw=%.9g yaw_delta=%.9g continuous=%u "
                    "budget_left=%u native_phase=%d native_fault=%d stop_cause=%d stop_scene=%llu "
                    "stop_after=%llu first_read=%llu inherited=%d settled=%u\n",
                    event, reason, static_cast<unsigned long long>(request), char('A' + next),
                    static_cast<unsigned long long>(loading), static_cast<unsigned long long>(generation),
                    current.frame, static_cast<unsigned long long>(current.scene),
                    prior.frame, static_cast<unsigned long long>(prior.scene), sample_arc_arm_frame, unsigned(projected),
                    double(b[0]), double(b[1]), double(b[2]), double(a[0]), double(a[1]), double(a[2]),
                    double(g[0]), double(g[1]), double(g[2]), double(f[0]), double(f[1]), double(f[2]),
                    dx(*pan_a, current, 0), dx(*pan_a, current, 1),
                    pan_b ? dx(*pan_b, current, 0) : 0., pan_b ? dx(*pan_b, current, 1) : 0.,
                    dx(prior, current, 0), dx(prior, current, 1), double(Distance(prior.output[0], current.output[0])),
                    double(Distance(prior.output[1], current.output[1])), double(WetForward(*pan_a, current)),
                    pan_b ? double(WetForward(*pan_b, current)) : 0., double(WetForward(prior, current)),
                    double(yaw), double(previous_yaw), double(yaw - previous_yaw),
                    unsigned(projected && Continuous(prior, current)), elapsed < 600u ? 600u - elapsed : 0u,
                    int(sample_arc_status.phase), int(sample_arc_status.fault), int(sample_arc_status.stop_cause),
                    static_cast<unsigned long long>(sample_arc_status.stop_scene),
                    static_cast<unsigned long long>(sample_arc_status.after_read),
                    static_cast<unsigned long long>(sample_arc_status.first_read),
                    sample_arc_status.first_inherited, pad_neutral_after);
    }

    void PadBoundaryLog(const char* event, const char* reason, u32 frame, u64 scene) const {
        std::printf("[sewer-motion-probe] event=%s request=%llu command=%016llx loading=%llu generation=%llu "
                    "frame=%u scene=%llu reason=%s observed_hold=%u released=%u rest=%u calls=%u "
                    "native_phase=%d native_fault=%d heartbeat=%016llx native_owner=%u "
                    "call_frame=%u call_scene=%llu warp_admitted=%u arm=%u\n",
                    event, static_cast<unsigned long long>(request), static_cast<unsigned long long>(PadLatchCommand()),
                    static_cast<unsigned long long>(loading), static_cast<unsigned long long>(generation),
                    frame, static_cast<unsigned long long>(scene), reason, unsigned(pad_boundary_held),
                    unsigned(pad_release_seen), pad_neutral_before, pad_boundary_calls, int(pad_boundary_last.phase),
                    int(pad_boundary_last.fault), static_cast<unsigned long long>(pad_boundary_last.heartbeat),
                    pad_boundary_last.owner, pad_key.frame, static_cast<unsigned long long>(pad_key.scene),
                    unsigned(warp_a_admitted), unsigned(enabled));
    }

    void PadBoundarySummary(const char* reason) {
        if (!PadBoundaryEnabled() || std::exchange(pad_boundary_reported, true)) return;
        PadBoundaryLog("summary", reason, last.frame, last.scene);
    }

    void CancelPadLatch() const {
        if (pad_key.scene) bbgpu_sewer_pad_latch(BB_SEWER_PAD_CANCEL, &pad_key);
    }

    ~Series() {
        PadBoundarySummary("destructor");
        if (!failed && next < completed.size()) CancelPadLatch();
    }

    BbSewerPadStatus PadAction(BbSewerPadAction action, const Pose& pose) {
        pad_key = {request, loading, generation, PadLatchCommand(), pose.scene, pose.frame};
        return bbgpu_sewer_pad_latch(action, &pad_key);
    }

    void PadLog(const char* stage, const BbSewerPadStatus& status) const {
        std::printf("[sewer-pad-latch] event=%s request=%llu loading=%llu generation=%llu command=%016llx "
                    "frame=%u scene=%llu owner=%u phase=%d stop=%llu stop_cause=%d fault=%d "
                    "after_read=%llu first_read=%llu first_inherited=%d heartbeat=%016llx\n", stage,
                    static_cast<unsigned long long>(request), static_cast<unsigned long long>(loading),
                    static_cast<unsigned long long>(generation), static_cast<unsigned long long>(pad_key.command),
                    status.stop_serial ? status.stop_frame : pad_key.frame,
                    static_cast<unsigned long long>(status.stop_serial ? status.stop_scene : pad_key.scene),
                    status.owner, int(status.phase), static_cast<unsigned long long>(status.stop_serial),
                    int(status.stop_cause), int(status.fault), static_cast<unsigned long long>(status.after_read),
                    static_cast<unsigned long long>(status.first_read), status.first_inherited,
                    static_cast<unsigned long long>(status.heartbeat));
    }

    void Stop(const char* why) {
        if (failed || next == completed.size()) return;
        failed = true;
        if (SampleArcEnabled() && !sample_arc_refusal_logged)
            SampleArcLog("refused", why, older, last, last.scene != 0);
        PadBoundarySummary(why);
        CancelPadLatch();
        if (pending) {
            pending->Refuse(why);
        } else {
            std::printf("[sewer-motion] event=refused request=%llu checkpoint=%c why=%s\n",
                        static_cast<unsigned long long>(request), 'A' + next, why);
        }
    }

    bool Active() const { return !failed && next < completed.size(); }

    void Poll(u32 frame) {
        if (!Active()) return;
        if (frame - first_frame > 600u) return Stop("scene-frame-budget");
        if (!pending) return;
        if (pending->refusal.load()) return Stop("checkpoint-refused");
        if (!pending->vendor_claimed && frame > pending->key.frame + 1u) {
            pending->VendorRefused("no-actual-dlss-evaluate");
        }
        if (pending->needs_present && !pending->present_claimed.load() && frame > pending->key.frame + 1u)
            pending->FinishPresentation(false, "no-issued-tonemap-display-offer");
        const bool warp_only = WarpAdmissionEnabled();
        const unsigned required = warp_only ? Transport | Warp : All | (pending->needs_present ? Presenter : 0u);
        const unsigned retired = pending->retired.load(std::memory_order_acquire);
        if ((retired & required) != required || (next == 1 && !b_followed)) return;
        if (warp_only && !pending->ValidWarpScope()) return Stop("reduced-warp-retirement-scope");
        if (SampleArcEnabled()) {
            // These are the actual registered, retired proxy centres, including native draw jitter.
            for (unsigned i = 0; i < next; ++i)
                for (unsigned point = 0; point < pending->warp.px.size(); ++point)
                    if (pending->warp.px[point] == completed[i]->warp.px[point])
                        return Stop("sample-arc-reused-proxy-centre");
        }
        const bool vendor_retired = (retired & Vendor) != 0;
        const bool vendor_values = vendor_retired && pending->vendor_values;
        const bool match = vendor_values && pending->post_warp == pending->vendor_input;
        const auto* presentation = pending->presentation.load(std::memory_order_acquire);
        std::printf("[sewer-motion] event=retired request=%llu checkpoint=%c frame=%u scene=%llu "
                    "input_values=%s vendor=%s vendor_error=%s merge=%u writer_lineage=unknown presentation=%s\n",
                    static_cast<unsigned long long>(request), pending->key.checkpoint, pending->key.frame,
                    static_cast<unsigned long long>(pending->key.scene),
                    vendor_values ? (match ? "equal" : "changed") : "unavailable",
                    !vendor_retired ? "pending" : (vendor_values ? "dlss" : "unavailable"),
                    vendor_retired && pending->vendor_error ? pending->vendor_error : "none",
                    unsigned(pending->has_merge), pending->needs_present && presentation ? presentation : "pending");
        completed[next++] = std::move(pending);
        if (next == completed.size()) PadBoundarySummary("completed");
    }

    bool TryAdmitWarpA() {
        // The host checks the original renderer qualification and fenced pixel and source controls
        // before it offers this exact A. An environment value cannot stand in for its live permit.
        const auto permit = BbLiveKnobs::Lookup("BB_SEWER_MOTION_WARP_A");
        if (!permit.in_file || !*permit.file) return true;
        if (next != 1 || !completed[0]) return false;
        const auto& a = *completed[0];
        const auto& key = a.key;
        if (key.request != request || key.loading != loading || key.generation != generation ||
            key.checkpoint != 'A' || key.enabled != enabled || a.refusal.load()) return false;
        const auto nonce = static_cast<unsigned long long>(key.request);
        const auto load = static_cast<unsigned long long>(key.loading);
        const auto gen = static_cast<unsigned long long>(key.generation);
        const auto scene = static_cast<unsigned long long>(key.scene);
        const auto tick = static_cast<unsigned long long>(a.warp.tick);
        char expected[LIVE_KNOB_VALUE_MAX];
        const int length = std::snprintf(expected, sizeof(expected), "%llu:%llu:%llu:%u:%llu:%llu:%u",
                                         nonce, load, gen, key.frame, scene, tick, unsigned(enabled));
        if (length <= 0 || size_t(length) >= sizeof(expected) || std::strcmp(permit.file, expected)) return false;
        warp_a_admitted = true;
        std::printf("[sewer-motion] event=warp-admitted request=%llu checkpoint=A frame=%u scene=%llu "
                    "loading=%llu generation=%llu tick=%llu arm=%u\n",
                    nonce, key.frame, scene, load, gen, tick, unsigned(enabled));
        return true;
    }

    void Adjacent(const Pose& sample, const char* relation) const {
        const auto eye = Eye(sample.camera);
        std::printf("[sewer-motion] event=adjacent request=%llu checkpoint=%c relation=%s frame=%u scene=%llu "
                    "eye=%.9g,%.9g,%.9g forward=%.9g,%.9g,%.9g p0=%.9g,%.9g p1=%.9g,%.9g p2=%.9g,%.9g\n",
                    static_cast<unsigned long long>(request), 'A' + next, relation, sample.frame,
                    static_cast<unsigned long long>(sample.scene), double(eye[0]), double(eye[1]),
                    double(eye[2]), double(sample.camera.inv_view[2]),
                    double(sample.camera.inv_view[6]), double(sample.camera.inv_view[10]),
                    double(sample.output[0][0]), double(sample.output[0][1]),
                    double(sample.output[1][0]), double(sample.output[1][1]), double(sample.output[2][0]),
                    double(sample.output[2][1]));
    }

    void PoseFeed(const Pose& p, const Vec3& hunter, char phase, float yaw, bool selected) const {
        const auto eye = Eye(p.camera), forward = Forward(p);
        std::printf("[sewer-motion] event=%s request=%llu checkpoint=%c frame=%u scene=%llu yaw=%.9g arm=%u "
                    "eye=%.9g,%.9g,%.9g forward=%.9g,%.9g,%.9g hunter=%.9g,%.9g,%.9g "
                    "p0=%.9g,%.9g p1=%.9g,%.9g p2=%.9g,%.9g\n",
                    selected ? "selected" : "pose", static_cast<unsigned long long>(request), phase,
                    p.frame, static_cast<unsigned long long>(p.scene), double(yaw), unsigned(enabled),
                    double(eye[0]), double(eye[1]), double(eye[2]), double(forward[0]), double(forward[1]),
                    double(forward[2]), double(hunter[0]), double(hunter[1]), double(hunter[2]),
                    double(p.output[0][0]), double(p.output[0][1]), double(p.output[1][0]),
                    double(p.output[1][1]), double(p.output[2][0]), double(p.output[2][1]));
    }

    std::shared_ptr<Checkpoint> ObservePan(Pose now) {
        Poll(now.frame);
        if (!Active() || now.scene == last.scene) return {};
        const bool sample_arc = SampleArcEnabled();
        const Pose prior = last;
        bool projected = false;
        const auto fail = [&](const char* reason) -> std::shared_ptr<Checkpoint> {
            if (sample_arc) {
                SampleArcLog("refused", reason, prior, now, projected);
                sample_arc_refusal_logged = true;
            }
            Stop(reason);
            return {};
        };
        const bool latch = PadLatchEnabled();
        const bool warp_only = WarpAdmissionEnabled();
        const bool held = latch && BbTestCamera::g_gate_engaged.load(std::memory_order_relaxed);
        if (warp_only && !latch) return fail("pan-pad-latch-configuration");
        if (sample_arc && PadLatchCommand() != 6) return fail("sample-arc-latch-command");
        if (latch) {
            if ((enabled && !warp_only) || !FinalEnabled() || !PoseFeedEnabled() || !PadLatchCommand())
                return fail("pan-pad-latch-configuration");
            if (held) {
                if (pad_release_seen) return fail("pan-pad-hold-reengaged");
                auto& gate = BbTestCamera::Gate();
                bool ready;
                {
                    std::lock_guard lock(gate.m);
                    ready = gate.framed && !gate.failed && BbTestCamera::HoldWanted();
                }
                if (!ready) {
                    if (pan_a) return fail("pan-pad-a-lost-camera-hold");
                    return {};
                }
                if (PadBoundaryEnabled() && !std::exchange(pad_boundary_held, true))
                    PadBoundaryLog("held", "framed-hold", now.frame, now.scene);
            }
        }
        if (now.frame - first_frame >= 600u) return fail("pan-scene-budget");
        if (!Project(now.camera, now.output)) return fail("pan-view-projection");
        projected = true;
        Vec3 hunter{};
        if (!BbEngine::world_player_position(hunter.data()) ||
            !std::isfinite(hunter[0]) || !std::isfinite(hunter[1]) || !std::isfinite(hunter[2]))
            return fail("pan-native-hunter-unavailable");
        const char phase = char('A' + next);
        const bool rested = older.RestedTo(last) && last.RestedTo(now);
        const Pose& preceding = prior;
        const Pose two_before = older;
        older = last;
        last = now;
        float yaw = 0.f;
        bool select = false;
        if (!pan_a) {
            if (!MatchPoint(Eye(now.camera), EndpointEyes[1], .01f) ||
                !(std::abs(Heading(now) - 147.10172f) <= .10f) ||
                !(std::abs(Pitch(now) + 19.40754f) <= .10f)) return fail("pan-a-retained-pose");
            if (!rested || (latch && !held)) return {};
            pan_a = now;
            pan_hunter = hunter;
            select = true;
        } else {
            yaw = RelativeYaw(*pan_a, now);
            const float previous_yaw = RelativeYaw(*pan_a, preceding);
            if (!(yaw >= -6.f && yaw <= .0001f) ||
                !(std::abs(Pitch(now) - Pitch(*pan_a)) <= .10f) ||
                !MatchPoint(hunter, pan_hunter, .01f) || !PanEyeFits(*pan_a, now, pan_hunter, yaw))
                return fail("signed-pan-corridor");
            if (!Continuous(preceding, now) || yaw > previous_yaw + .0001f ||
                WetForward(preceding, now) <= -.5f) return fail("pan-cut-gap-or-reversal");
            const float from_a = WetForward(*pan_a, now);
            if (sample_arc && from_a > SampleArc::Cap) return fail("sample-arc-safety-cap");
            if (next == 0 && (std::abs(yaw) > .015f || std::abs(from_a) >= .5f))
                return fail("pan-before-a-retired");
            if (latch && !pad_armed) {
                if (std::abs(yaw) > .015f) return fail("pan-pad-movement-before-arm");
                for (u32 i = 0; i < now.output.size(); ++i) {
                    if (!(Distance(now.output[i], pan_a->output[i]) < .5f))
                        return fail("pan-pad-movement-before-arm");
                }
                if (warp_only && held && !warp_a_admitted && !TryAdmitWarpA())
                    return fail("pan-pad-a-warp-permit-scope");
                if (!held) {
                    if (next == 0) return fail("pan-pad-hold-released-before-a-retired");
                    if (warp_only && !warp_a_admitted) return fail("pan-pad-a-warp-not-admitted");
                    if (!pad_release_seen) {
                        const auto goal = BbLiveKnobs::Lookup("BB_TEST_CAMERA");
                        const char* value = goal.Get();
                        if ((value && *value) || BbTestCamera::HoldWanted())
                            return fail("pan-pad-hold-not-released");
                        pad_release_seen = true;
                        if (PadBoundaryEnabled())
                            PadBoundaryLog("release", "gate-clear-and-unset", now.frame, now.scene);
                    }
                    if (!warp_only) {
                        const auto& a = *completed[0];
                        const auto* presentation = a.presentation.load(std::memory_order_acquire);
                        if (!a.vendor_values || a.post_warp != a.vendor_input || !presentation ||
                            std::strcmp(presentation, "fenced") != 0)
                            return fail("pan-pad-a-not-fenced");
                    }
                    pad_neutral_before = preceding.RestedTo(now) ? pad_neutral_before + 1 : 0;
                    if (pad_neutral_before >= 3) {
                        const bool trace = PadBoundaryEnabled();
                        const auto status = PadAction(BB_SEWER_PAD_ARM, now);
                        if (trace) {
                            pad_boundary_last = status;
                            ++pad_boundary_calls;
                            if (pad_neutral_before == 3)
                                PadBoundaryLog("rest-three", "threshold-at-call", now.frame, now.scene);
                            if (pad_boundary_calls == 1)
                                PadBoundaryLog("arm-first", "returned", now.frame, now.scene);
                        }
                        if (sample_arc) sample_arc_status = status;
                        if (status.phase == BB_SEWER_PAD_REFUSED) {
                            PadLog("refused", status);
                            return fail("pan-pad-native-arm-refused");
                        }
                        pad_armed = status.phase == BB_SEWER_PAD_ARMED;
                        if (sample_arc && pad_armed) sample_arc_arm_frame = now.frame;
                        if (pad_armed) PadLog("armed", status);
                    }
                }
            }
            if (next == 1 && pending && !b_followed) {
                const bool moving = sample_arc ? SampleArc::Moving(*pan_b, now, previous_yaw, yaw)
                                               : yaw < previous_yaw && WetForward(*pan_b, now) > 1.f;
                if (!moving) return fail("pan-b-later-camera");
                b_followed = true;
                Adjacent(now, "after");
                if (sample_arc) SampleArcLog("followed-b", "consecutive-forward", preceding, now, true);
            }
            if (next == 1 && !pending && !pan_b) {
                if (from_a > (sample_arc ? SampleArc::End : 35.f)) return fail("pan-b-selection-window-missed");
                if (sample_arc ? SampleArc::InBand(from_a)
                               : from_a >= 26.f && yaw < previous_yaw && WetForward(preceding, now) > 1.f) {
                    if (sample_arc && !SampleArc::Moving(preceding, now, previous_yaw, yaw))
                        return fail("sample-arc-b-incoming-step");
                    pan_b = now;
                    select = true;
                    if (sample_arc) SampleArcLog("selected-b", "first-in-band", preceding, now, true);
                }
            }
            const float from_b = pan_b ? WetForward(*pan_b, now) : 0.f;
            const bool enough = pan_b && b_followed &&
                (sample_arc ? SampleArc::StopAt(from_a, from_b) : from_a >= 52.f && from_b >= 26.f);
            const bool requesting_stop = enough && !pan_neutral_requested;
            if (latch && pad_armed && pad_key.scene != now.scene) {
                const auto status = PadAction(requesting_stop ? BB_SEWER_PAD_STOP : BB_SEWER_PAD_FEEDBACK, now);
                if (sample_arc) sample_arc_status = status;
                if (status.phase == BB_SEWER_PAD_REFUSED ||
                    (requesting_stop && (status.phase != BB_SEWER_PAD_CUT ||
                                         status.stop_cause != BB_SEWER_PAD_PROJECTION))) {
                    PadLog("refused", status);
                    return fail("pan-pad-native-stop-refused");
                }
                if (sample_arc && requesting_stop &&
                    (status.stop_serial != 1 || status.stop_scene != now.scene || status.stop_frame != now.frame ||
                     status.stop_loading != loading || status.stop_generation != generation ||
                     status.fault != BB_SEWER_PAD_NONE || !status.after_read || status.first_read))
                    return fail("sample-arc-native-projection-identity");
                if (requesting_stop) {
                    PadLog("projected-stop", status);
                    if (sample_arc) SampleArcLog("projected-stop", "native-projection", preceding, now, true);
                }
                if (status.first_read && now.scene > status.stop_scene) {
                    if (sample_arc && (status.phase != BB_SEWER_PAD_CUT || status.stop_cause != BB_SEWER_PAD_PROJECTION ||
                        status.stop_serial != 1 || status.stop_loading != loading || status.stop_generation != generation ||
                        !status.after_read || status.first_read != status.after_read + 1 || !status.first_inherited))
                        return fail("sample-arc-first-native-neutral");
                    const bool first = !pad_return_logged;
                    if (first) {
                        PadLog("returned-after-stop", status);
                        pad_return_logged = true;
                    }
                    const bool settled = sample_arc ? !first && SampleArc::Settled(preceding, now, previous_yaw, yaw)
                                                    : preceding.RestedTo(now);
                    if (settled) ++pad_neutral_after;
                    else pad_neutral_after = 0;
                }
            }
            if (requesting_stop) {
                if (latch && !pad_armed) return fail("pan-pad-no-armed-owner");
                pan_neutral_requested = true;
                std::printf("[sewer-motion] event=neutral-request request=%llu checkpoint=B frame=%u scene=%llu yaw=%.9g\n",
                            static_cast<unsigned long long>(request), now.frame,
                            static_cast<unsigned long long>(now.scene), double(yaw));
            }
            if (next == 2 && !pending && enough && rested && pan_neutral_requested &&
                (!latch || pad_neutral_after >= 3)) {
                select = true;
                if (sample_arc) SampleArcLog("selected-c", "three-settled-after-native-neutral", preceding, now, true);
            }
        }
        if ((!enabled || warp_only) && PoseFeedEnabled()) PoseFeed(now, hunter, phase, yaw, false);
        if (!select) return {};
        pending = std::make_shared<Checkpoint>(
            Key{request, now.scene, loading, generation, now.frame, phase, enabled}, now);
        Adjacent(preceding, "before");
        if (next != 1) Adjacent(two_before, "two-before");
        PoseFeed(now, hunter, phase, yaw, true);
        return pending;
    }

    std::shared_ptr<Checkpoint> Observe(Pose now) {
        if (PanEnabled()) return ObservePan(now);
        Poll(now.frame);
        if (!Active() || now.scene == last.scene) return {};
        if (!now.InCorridor() || !Project(now.camera, now.output)) {
            Stop("scene-camera-outside-registered-corridor");
            return {};
        }
        const bool continuous = Continuous(last, now);
        if (next == 1 && pending && !b_followed) {
            if (!Coherent(older, pending->pose, now, expected_end)) {
                Stop("moving-camera-needs-later-coherent-scene");
                return {};
            }
            b_followed = true;
            Adjacent(now, "after");
        }
        if (next == 0 && pending && now.WetDisjoint(pending->pose.output)) {
            Stop("camera-left-before-a-retired");
            return {};
        }
        const bool departed = next > 0 && Distance(Eye(completed[0]->pose.camera), Eye(now.camera)) > .10f;
        if ((departed || traveled) && (!continuous || Reversed(last, now, expected_end))) {
            Stop("moving-camera-cut-or-missing-scene");
            return {};
        }
        traveled |= departed;
        const bool rested = older.RestedTo(last) && last.RestedTo(now);
        const int end = now.Endpoint();
        if (next == 1 && !pending && traveled && end == 1 - start_endpoint && rested) {
            Stop("moving-checkpoint-window-missed");
            return {};
        }
        const bool at_start = next == 0 && end >= 0 && rested;
        const bool underway = next == 1 && !pending && end == -1 &&
            now.WetDisjoint(completed[0]->pose.output) && now.WetDisjoint(expected_end) &&
            MovingToward(last, now, expected_end);
        const bool at_end = next == 2 && end == 1 - start_endpoint && rested &&
                            now.WetDisjoint(completed[1]->pose.output);
        const Pose two_before = older;
        older = last;
        last = now;
        if (pending || (!at_start && !underway && !at_end)) return {};
        if (at_start) {
            start_endpoint = end;
            auto expected = now.camera;
            const auto eye = Eye(now.camera);
            const auto target = EndpointEyes[1 - end];
            for (u32 row = 0; row < 3; ++row) {
                auto* m = &expected.view[4 * row];
                m[3] -= m[0] * (target[0] - eye[0]) + m[1] * (target[1] - eye[1]) +
                        m[2] * (target[2] - eye[2]);
            }
            if (!Project(expected, expected_end)) {
                Stop("opposite-endpoint-projection");
                return {};
            }
        }
        pending = std::make_shared<Checkpoint>(
            Key{request, now.scene, loading, generation, now.frame, char('A' + next), enabled}, now);
        Adjacent(older, "before");
        if (next != 1) Adjacent(two_before, "two-before");
        std::printf("[sewer-motion] event=selected request=%llu checkpoint=%c frame=%u scene=%llu arm=%u "
                    "eye=%.9g,%.9g,%.9g p0=%.9g,%.9g p1=%.9g,%.9g p2=%.9g,%.9g\n",
                    static_cast<unsigned long long>(request), pending->key.checkpoint, now.frame,
                    static_cast<unsigned long long>(now.scene), unsigned(enabled),
                    double(now.camera.inv_view[3]), double(now.camera.inv_view[7]), double(now.camera.inv_view[11]),
                    double(now.output[0][0]), double(now.output[0][1]), double(now.output[1][0]),
                    double(now.output[1][1]), double(now.output[2][0]), double(now.output[2][1]));
        return pending;
    }
};

} // namespace Vulkan::SewerMotion
