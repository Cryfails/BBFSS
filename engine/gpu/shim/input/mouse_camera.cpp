// SPDX-License-Identifier: GPL-3.0-or-later
#include "mouse_camera.h"
#include "camera_orbit.h"
#include "camera_path.h"
#include "input.h"
#include "mouse_turn.h"
#include "../engine/camera.h"
#include "../engine/engine_hooks.h"
#include "../engine/loading.h"
#include "../engine/online_fixes.h"
#include "../bbport_overlay.h" // bbport (r102b_camera-clean-hud): MenuOpen, for BB_CAMERA_ORBIT
#include "../bbport_test_camera.h" // bbport (r120_test-camera-lookat, TOOL): BB_TEST_CAMERA's hold of the camera's fields
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iterator>
#include <mutex>
#include <string>
#include <vector>

#ifdef _WIN32
#define LANTERN_STUB_SYMBOL
#else
#define LANTERN_STUB_SYMBOL __attribute__((visibility("hidden")))
#endif

extern "C" {
LANTERN_STUB_SYMBOL std::uint64_t lantern_free_camera_resume = 0;
LANTERN_STUB_SYMBOL std::uint8_t lantern_free_camera_ran = 0;
LANTERN_STUB_SYMBOL __attribute__((sysv_abi)) void lantern_free_camera_turn(std::uint8_t* camera,
                                                                             std::uint8_t* had_input,
                                                                             float stick_pitch, float stick_yaw);
void lantern_free_camera_site();
void lantern_fast_turn_exit();
}

asm(R"(
    .text
    .p2align 4
    .globl lantern_free_camera_site
lantern_free_camera_site:
    vmovss      %xmm0, 0x140(%r13)
    vextractps  $1, %xmm1, 0x144(%r13)
    push        %rbx
    push        %rax
    push        %rcx
    push        %rdx
    push        %rsi
    push        %rdi
    push        %r8
    push        %r9
    push        %r10
    push        %r11
    mov         %rsp, %rbx
    and         $-32, %rsp
    sub         $512, %rsp
    vmovdqu     %ymm0, 0x000(%rsp)
    vmovdqu     %ymm1, 0x020(%rsp)
    vmovdqu     %ymm2, 0x040(%rsp)
    vmovdqu     %ymm3, 0x060(%rsp)
    vmovdqu     %ymm4, 0x080(%rsp)
    vmovdqu     %ymm5, 0x0a0(%rsp)
    vmovdqu     %ymm6, 0x0c0(%rsp)
    vmovdqu     %ymm7, 0x0e0(%rsp)
    vmovdqu     %ymm8, 0x100(%rsp)
    vmovdqu     %ymm9, 0x120(%rsp)
    vmovdqu     %ymm10, 0x140(%rsp)
    vmovdqu     %ymm11, 0x160(%rsp)
    vmovdqu     %ymm12, 0x180(%rsp)
    vmovdqu     %ymm13, 0x1a0(%rsp)
    vmovdqu     %ymm14, 0x1c0(%rsp)
    vmovdqu     %ymm15, 0x1e0(%rsp)
    mov         %r13, %rdi
    lea         -0x3c4(%rbp), %rsi
    vmovaps     %xmm10, %xmm0
    vmovshdup   %xmm10, %xmm1
    vzeroupper
    call        lantern_free_camera_turn
    vmovdqu     0x000(%rsp), %ymm0
    vmovdqu     0x020(%rsp), %ymm1
    vmovdqu     0x040(%rsp), %ymm2
    vmovdqu     0x060(%rsp), %ymm3
    vmovdqu     0x080(%rsp), %ymm4
    vmovdqu     0x0a0(%rsp), %ymm5
    vmovdqu     0x0c0(%rsp), %ymm6
    vmovdqu     0x0e0(%rsp), %ymm7
    vmovdqu     0x100(%rsp), %ymm8
    vmovdqu     0x120(%rsp), %ymm9
    vmovdqu     0x140(%rsp), %ymm10
    vmovdqu     0x160(%rsp), %ymm11
    vmovdqu     0x180(%rsp), %ymm12
    vmovdqu     0x1a0(%rsp), %ymm13
    vmovdqu     0x1c0(%rsp), %ymm14
    vmovdqu     0x1e0(%rsp), %ymm15
    mov         %rbx, %rsp
    pop         %r11
    pop         %r10
    pop         %r9
    pop         %r8
    pop         %rdi
    pop         %rsi
    pop         %rdx
    pop         %rcx
    pop         %rax
    pop         %rbx
    vmovss      0x140(%r13), %xmm0
    jmp         *lantern_free_camera_resume(%rip)

    .p2align 4
    .globl lantern_fast_turn_exit
lantern_fast_turn_exit:
    vmovss      %xmm0, 0x140(%r13)
    movb        $1, lantern_free_camera_ran(%rip)
    jmp         *lantern_free_camera_resume(%rip)
)");

namespace MouseCamera {
namespace {
using Clock = std::chrono::steady_clock;

constexpr std::size_t kUpdate = 0x143ac60;

constexpr std::uint8_t kUpdateEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55,
                                         0x41, 0x54, 0x53, 0x48, 0x81, 0xec, 0xd8, 0x03, 0x00, 0x00};
constexpr std::size_t kFreeStore = 0x143ce54, kAfterStore = 0x143ce67;

constexpr std::uint8_t kFreeStoreCode[] = {0xc4, 0xc1, 0x7a, 0x11, 0x85, 0x40, 0x01, 0x00, 0x00, 0xc4,
                                           0xc3, 0x79, 0x17, 0x8d, 0x44, 0x01, 0x00, 0x00, 0x01};
struct FastTurnExit {
    std::size_t at;
    std::uint8_t code[14];
};
constexpr FastTurnExit kFastTurnExits[] = {
    {0x143f9bc, {0xc4, 0xc1, 0x7a, 0x11, 0x85, 0x40, 0x01, 0x00, 0x00, 0xe9, 0x9d, 0xd4, 0xff, 0xff}},
    {0x143fabf, {0xc4, 0xc1, 0x7a, 0x11, 0x85, 0x40, 0x01, 0x00, 0x00, 0xe9, 0x9a, 0xd3, 0xff, 0xff}},
};
constexpr std::size_t kPitch = 0x140, kYaw = 0x144, kHighest = 0x1ec, kLowest = 0x1f0;
static_assert(BbTestCamera::kPitchAt == kPitch && BbTestCamera::kYawAt == kYaw && BbTestCamera::kHighestAt == kHighest &&
              BbTestCamera::kLowestAt == kLowest); // bbport (r120_test-camera-lookat, TOOL): the hold writes the same fields

struct AutoRotationStore {
    std::size_t at;
    std::uint8_t code[9];
    bool held_by_mouse;
};
constexpr AutoRotationStore kAutoRotation[] = {
    {0x143c6e8, {0xc4, 0xc1, 0x7a, 0x11, 0x85, 0x44, 0x01, 0x00, 0x00}, true},
    {0x143c870, {0xc4, 0xc1, 0x7a, 0x11, 0xad, 0x44, 0x01, 0x00, 0x00}, false},
    {0x143c984, {0xc4, 0xc1, 0x7a, 0x11, 0x8d, 0x30, 0x01, 0x00, 0x00}, true},
    {0x143dde6, {0xc4, 0xc1, 0x7a, 0x11, 0x85, 0x94, 0x02, 0x00, 0x00}, true},
};
constexpr std::uint8_t kNops[9] = {0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90};

constexpr float kFlickRate = 3000.0f, kFlickRearmRate = 1500.0f, kFlickCooldown = 0.5f;
constexpr auto kFlickShown = std::chrono::milliseconds(80);

std::uint8_t* g_image = nullptr;
bool g_installed = false;

std::mutex g_counts_lock;
float g_count_x = 0, g_count_y = 0;

std::atomic<float> g_degrees_per_count{MouseTurn::DegreesPerCount(5)};
std::atomic<bool> g_invert_x{false}, g_invert_y{false}, g_hold{false};

float g_update_x = 0, g_update_y = 0;
bool g_auto_rotation_nops = false;
bool g_patched_out = false;
bool g_store_is_games[std::size(kAutoRotation)] = {};
bool g_free_last_update = true;

std::mutex g_flick_lock;
float g_flick_x = 0, g_flick_y = 0;
unsigned g_flick_updates = 0;

Clock::time_point g_last_read{};
float g_cooldown = 0;
float g_shown_x = 0, g_shown_y = 0;
Clock::time_point g_shown_until{};

std::atomic<unsigned> g_turns{0}, g_flicks{0}, g_free_changes{0};

// Camera mode's orbit. The keys change g_orbit under g_orbit_lock (the window's thread); the
// follow camera's update (the game's thread) reads it while g_orbit_live is set and alone owns
// g_run. g_orbit_live stays set until a stop has eased out, g_orbit_drive only while the orbit is
// wanted. A loading screen or a cutscene (a new Loading::Generation) ends it: the camera update
// checks first thing, and OrbitFrame (the frame pacer's update) checks too, in case no camera
// update runs. Neither assumes the two share a thread: the radius factor is set only under
// g_orbit_lock, and only for the level (generation) it was meant for.
struct OrbitCommand {
    bool want = false;
    unsigned serial = 0; // one more at each start; 0 is never a start
    float speed = CameraOrbit::kSpeedStart;
    int height = 0; // steps from the pitch at the start
    CameraOrbit::HeightRange heights{-CameraOrbit::kHeightStepsMost, CameraOrbit::kHeightStepsMost};
    float radius = 1.0f;
    std::uint64_t generation = 0;
    bool path = false; // bbport (r102_camera-mode-3-4): a camera path plays (F6), not the orbit
};
constexpr unsigned kOrbitAwayUpdates = 30;
// A start needs a camera update with the follow camera's free path at most this long ago.
constexpr auto kFollowFresh = std::chrono::milliseconds(250);

std::mutex g_orbit_lock;
OrbitCommand g_orbit;
std::uint64_t g_distance_generation = 0; // under g_orbit_lock: the level the radius factor is for
std::atomic<bool> g_orbit_live{false}, g_orbit_drive{false}, g_distance_moved{false};
std::atomic<std::uint64_t> g_orbit_generation{0};
std::atomic<Clock::rep> g_follow_seen{0}; // steady clock: the last update after a free path

CameraOrbit::Run g_run;
unsigned g_run_serial = 0, g_run_away = 0;
bool g_run_tail = false; // after an early end g_run.radius alone eases back to 1
std::uint64_t g_run_generation = 0;
float g_run_base = 0, g_run_turned = 0;
Clock::time_point g_run_last{}, g_run_began{};

// bbport (r102_camera-mode-3-4): camera paths. g_path_keys are the keys F5 added (window thread
// only); F6 copies them into g_path_play under g_orbit_lock; the camera update copies g_path_play
// into g_run_path when a play starts, with the camera's pose of that moment as its first pose,
// and alone owns g_run_path, g_run_timing and g_run_seconds. g_seen_* are the follow camera's
// last pose (lantern_free_camera_turn) and the distance factor last set (SetDistanceLocked).
std::vector<CameraPath::Key> g_path_keys, g_path_play, g_run_path;
bool g_path_loaded = false; // window thread: the path file was read
CameraPath::Timing g_run_timing;
float g_run_seconds = 0;
std::atomic<float> g_seen_pitch{0.0f}, g_seen_yaw{0.0f}, g_seen_radius{1.0f};
float g_path_seconds = CameraPath::kSecondsDefault; // under g_orbit_lock: BB_CAMERA_PATH_S, given by F6
static_assert(CameraPath::kRadiusLeast == CameraOrbit::kRadiusLeast && CameraPath::kRadiusMost == CameraOrbit::kRadiusMost &&
              CameraPath::kRadiansPerDegree == CameraOrbit::kRadiansPerDegree);

std::uint8_t* At(std::size_t offset) { return g_image + offset; }

bool OrbitOn(const OrbitCommand& c) { return c.want && c.generation == BbEngine::Loading::Generation(); }

// g_orbit_lock held. The radius factor for the level `generation`; in any other level it is 1.
// False when the level changed meanwhile (then the factor is 1).
bool SetDistanceLocked(float factor, std::uint64_t generation) {
    const bool same = generation == BbEngine::Loading::Generation();
    if (!same) factor = 1.0f;
    BbEngine::Camera::SetOrbitDistance(factor);
    g_seen_radius.store(factor, std::memory_order_relaxed); // bbport (r102_camera-mode-3-4)
    g_distance_moved.store(factor != 1.0f, std::memory_order_relaxed);
    g_distance_generation = generation;
    return same;
}

bool SetDistance(float factor, std::uint64_t generation) {
    std::scoped_lock lock(g_orbit_lock);
    return SetDistanceLocked(factor, generation);
}

// g_orbit_lock held, any thread: the keys and the pad are done with the orbit. False if it was
// over already.
bool RetireLocked() {
    if (!g_orbit_live.load(std::memory_order_relaxed)) return false;
    g_orbit.want = false;
    g_orbit_drive = false;
    g_orbit_live = false;
    return true;
}

// The game's thread. serial 0 ends whichever orbit is live; why is null after a stop eased out.
// keep_radius (an early end): the yaw and the pitch are the game's at once, the radius eases home.
void OrbitEnd(unsigned serial, const char* why, bool keep_radius) {
    const float turned = g_run_turned / CameraOrbit::kRadiansPerDegree;
    const Clock::time_point now = Clock::now();
    const float seconds = std::chrono::duration<float>(now - g_run_began).count();
    const CameraOrbit::Spring radius = g_run.radius;
    g_run = {};
    g_run_serial = 0;
    g_run_away = 0;
    g_run_tail = keep_radius && !CameraOrbit::RadiusHome(radius);
    if (g_run_tail) {
        g_run.radius = radius;
        g_run_last = now;
    }
    std::scoped_lock lock(g_orbit_lock);
    if (!SetDistanceLocked(g_run.radius.value, g_run_generation)) {
        g_run_tail = false;
        g_run.radius = {1.0f, 0.0f};
    }
    if (serial && serial != g_orbit.serial) return; // started again meanwhile
    if (!RetireLocked()) return;                     // OrbitFrame saw the loading screen first
    if (why && !*why) return; // bbport (r102_camera-mode-3-4): a camera path printed its own line
    if (why) std::printf("Camera: %s off (%s)\n", g_orbit.path ? "path" : "orbit", why); // bbport (r102_camera-mode-3-4)
    else std::printf("Camera: orbit stopped, %.0f degrees in %.1f s\n", turned, seconds);
}

// The game's thread, each camera update while g_run_tail is set.
void RadiusTail() {
    if (g_orbit_live.load(std::memory_order_relaxed)) { // started again: OrbitTurn goes on from this radius
        g_run_tail = false;
        return;
    }
    const Clock::time_point now = Clock::now();
    const float dt = std::chrono::duration<float>(now - g_run_last).count();
    g_run_last = now;
    const bool home = CameraOrbit::EaseRadiusHome(g_run.radius, dt);
    if (!SetDistance(g_run.radius.value, g_run_generation) || home) {
        g_run_tail = false;
        g_run.radius = {1.0f, 0.0f};
    }
}

// bbport (r102_camera-mode-3-4): g_orbit_lock held, the game's thread, at the start of a play: the
// camera's pose of the moment (with the distance it has now) and then the keys, unwrapped.
void PathBegin(float pitch, float yaw, float seconds_per_key) {
    g_run_path.clear();
    g_run_path.push_back({yaw, pitch, g_run.radius.value});
    g_run_path.insert(g_run_path.end(), g_path_play.begin(), g_path_play.end());
    CameraPath::Unwrap(g_run_path.data(), g_run_path.size());
    g_run_timing = CameraPath::TimingFor(g_run_path.size(), seconds_per_key);
    g_run_seconds = 0;
}

// bbport (r102_camera-mode-3-4): a play's part of the follow camera's update. A stop (F6 again, F4,
// the menu) ends it at once, the camera staying where it is and the distance easing back; so does
// the end of the path.
bool PathTurn(const OrbitCommand& c, std::uint8_t* camera, std::uint8_t* had_input, float pitch, float lowest,
              float highest, Clock::time_point now) {
    if (!c.want) {
        OrbitEnd(c.serial, "", true);
        return false;
    }
    const float dt = std::clamp(std::chrono::duration<float>(now - g_run_last).count(), 0.0f, CameraOrbit::kLongestStep);
    g_run_last = now;
    g_run_seconds += dt;
    const CameraPath::Key k = CameraPath::Sample(g_run_path.data(), g_run_path.size(),
                                                 CameraPath::Progress(g_run_timing, g_run_seconds));
    const float new_pitch = lowest <= highest ? std::clamp(k.pitch, lowest, highest) : pitch;
    const float new_yaw = CameraOrbit::Wrap(k.yaw);
    std::memcpy(camera + kPitch, &new_pitch, 4);
    std::memcpy(camera + kYaw, &new_yaw, 4);
    *had_input = 1;
    g_run.radius = {k.radius, 0.0f};
    SetDistance(k.radius, c.generation);
    if (g_run_seconds >= g_run_timing.total) {
        std::printf("Camera: path done, %zu keys in %.1f s\n", g_run_path.size() - 1, double(g_run_seconds));
        OrbitEnd(c.serial, "", true);
    }
    return true;
}

// The orbit's part of the follow camera's update. False when the orbit ended here, so the
// stick and the mouse turn the camera in this update again.
bool OrbitTurn(std::uint8_t* camera, std::uint8_t* had_input, float stick_pitch, float stick_yaw) {
    OrbitCommand c;
    {
        std::scoped_lock lock(g_orbit_lock);
        c = g_orbit;
    }
    if (c.generation != BbEngine::Loading::Generation()) {
        OrbitEnd(c.serial, "a loading screen or a cutscene", false);
        return false;
    }
    float pitch, yaw, highest, lowest;
    std::memcpy(&pitch, camera + kPitch, 4);
    std::memcpy(&yaw, camera + kYaw, 4);
    std::memcpy(&highest, camera + kHighest, 4);
    std::memcpy(&lowest, camera + kLowest, 4);
    const Clock::time_point now = Clock::now();
    if (c.serial != g_run_serial) { // a start, or a start again while a stop or an early end eased out
        g_run_serial = c.serial;
        if (c.generation != g_run_generation) g_run = {}; // the last one ended unseen in another level
        g_run_generation = c.generation;
        g_run_tail = false;
        g_run.pitch = {pitch, 0.0f};
        g_run_base = pitch;
        g_run_turned = 0;
        g_run_last = g_run_began = now;
        // The height steps stay inside the game's pitch limits as they are at the start.
        const CameraOrbit::HeightRange heights = CameraOrbit::HeightRangeFrom(pitch, lowest, highest);
        std::scoped_lock lock(g_orbit_lock);
        if (g_orbit.serial == c.serial) {
            g_orbit.heights = heights;
            g_orbit.height = std::clamp(g_orbit.height, heights.least, heights.most);
        }
        c.height = std::clamp(c.height, heights.least, heights.most);
        if (c.path) PathBegin(pitch, yaw, g_path_seconds); // bbport (r102_camera-mode-3-4)
    }
    g_run_away = 0;
    if (!std::isfinite(pitch) || !std::isfinite(yaw)) {
        OrbitEnd(c.serial, "the camera's angles are not numbers", true);
        return false;
    }
    if (!c.want && (stick_pitch != 0 || stick_yaw != 0 || g_update_x != 0 || g_update_y != 0)) {
        OrbitEnd(c.serial, "the stick or the mouse turned the camera", true);
        return false;
    }
    if (c.path) return PathTurn(c, camera, had_input, pitch, lowest, highest, now); // bbport (r102_camera-mode-3-4)
    const float dt = std::chrono::duration<float>(now - g_run_last).count();
    g_run_last = now;
    const CameraOrbit::Targets t{c.want, c.speed,
                                 g_run_base + float(c.height) * CameraOrbit::kHeightStep * CameraOrbit::kRadiansPerDegree,
                                 c.radius};
    const CameraOrbit::Pose p = CameraOrbit::Step(g_run, t, dt, pitch, yaw, lowest, highest);
    g_run_turned += std::fabs(g_run.rate.value) * std::clamp(dt, 0.0f, CameraOrbit::kLongestStep);
    // bbport (r102b_camera-clean-hud): the orbit's periodic line, every 300 camera updates while one turns
    // (F4 or BB_CAMERA_ORBIT; the game's thread, so no orbit, no cost).
    static unsigned turning_updates = 0;
    if (++turning_updates % 300 == 0) {
        std::printf("Camera: orbit turning, %.0f degrees in %.1f s so far\n",
                    double(g_run_turned / CameraOrbit::kRadiansPerDegree),
                    double(std::chrono::duration<float>(now - g_run_began).count()));
    }
    std::memcpy(camera + kPitch, &p.pitch, 4);
    std::memcpy(camera + kYaw, &p.yaw, 4);
    *had_input = 1;
    SetDistance(g_run.radius.value, c.generation);
    if (!c.want && CameraOrbit::Settled(g_run)) OrbitEnd(c.serial, nullptr, false);
    return true;
}

void HoldAutoRotation(bool hold) {
    if (g_patched_out || hold == g_auto_rotation_nops) return;
    for (std::size_t i = 0; i < std::size(kAutoRotation); ++i) {
        const AutoRotationStore& s = kAutoRotation[i];
        if (s.held_by_mouse && g_store_is_games[i]) BbEngine::WriteCode(At(s.at), hold ? kNops : s.code, sizeof s.code);
    }
    g_auto_rotation_nops = hold;
}

std::int64_t __attribute__((sysv_abi)) OnCameraUpdate(std::uint64_t, const std::uint64_t*) {
    {
        std::scoped_lock lock(g_counts_lock);
        g_update_x = g_count_x;
        g_update_y = g_count_y;
        g_count_x = g_count_y = 0;
    }
    // A loading screen or a cutscene ends the orbit before this update does anything else.
    if (g_orbit_live.load(std::memory_order_relaxed) &&
        g_orbit_generation.load(std::memory_order_relaxed) != BbEngine::Loading::Generation())
        OrbitEnd(0, "a loading screen or a cutscene", false);
    // The orbit holds the game's auto-rotation like the mouse does, so it alone turns the camera.
    const bool mouse_holds = g_hold.load(std::memory_order_relaxed), orbit_live = g_orbit_live.load(std::memory_order_relaxed);
    HoldAutoRotation(mouse_holds || orbit_live || BbTestCamera::HoldWanted()); // bbport (r120_test-camera-lookat, TOOL): the held camera is not turned back
    if (!orbit_live) g_run_away = 0;
    const bool free = __atomic_exchange_n(&lantern_free_camera_ran, 0, __ATOMIC_RELAXED) != 0;
    if (free) {
        g_follow_seen.store(Clock::now().time_since_epoch().count(), std::memory_order_relaxed);
    } else {
        {
            std::scoped_lock lock(g_flick_lock);
            g_flick_x += g_update_x;
            g_flick_y += g_update_y;
            ++g_flick_updates;
        }
        if (orbit_live && ++g_run_away >= kOrbitAwayUpdates)
            OrbitEnd(0, "the game took the camera: locked on, or a scripted turn", true);
    }
    if (g_run_tail) RadiusTail();

    static unsigned updates = 0;
    if (++updates > 2 && free != g_free_last_update && g_free_changes.fetch_add(1, std::memory_order_relaxed) < 8)
        host_log("mouse camera: the free camera %s", free ? "is back" : "stopped (locked on, or the game turns it)");
    g_free_last_update = free;
    return 0;
}

bool JumpFrom(std::uint8_t* site, std::size_t size, void (*to)()) {
    std::uint8_t code[32];
    std::memset(code, 0xcc, sizeof code);
    const auto target = reinterpret_cast<std::uint64_t>(to);
    code[0] = 0xff;
    code[1] = 0x25;
    std::memset(code + 2, 0, 4);
    std::memcpy(code + 6, &target, 8);
    return size >= 14 && size <= sizeof code && BbEngine::WriteCode(site, code, size);
}
}

bool Install(std::uint8_t* image, std::size_t size) {
    g_image = image;
    const auto matches = [&](std::size_t at, const std::uint8_t* code, std::size_t n) {
        return at + n <= size && std::memcmp(image + at, code, n) == 0;
    };
    if (!matches(kFreeStore, kFreeStoreCode, sizeof kFreeStoreCode)) {
        host_log("mouse camera: off, the follow camera's store is not 1.09's");
        return false;
    }
    for (const FastTurnExit& exit : kFastTurnExits) {
        if (!matches(exit.at, exit.code, sizeof exit.code)) {
            host_log("mouse camera: off, the follow camera's fast turn is not 1.09's");
            return false;
        }
    }

    bool patched = false;
    for (std::size_t i = 0; i < std::size(kAutoRotation); ++i) {
        const AutoRotationStore& s = kAutoRotation[i];
        g_store_is_games[i] = matches(s.at, s.code, sizeof s.code);
        patched = patched || matches(s.at, kNops, sizeof kNops);
    }
    BbEngine::Hook entry;
    if (!BbEngine::Prepare(entry, image, size, kUpdate, kUpdateEntry, OnCameraUpdate)) {
        host_log("mouse camera: off, the follow camera's update is not 1.09's");
        return false;
    }
    g_patched_out = patched;
    lantern_free_camera_resume = reinterpret_cast<std::uint64_t>(At(kAfterStore));
    bool placed = JumpFrom(At(kFreeStore), sizeof kFreeStoreCode, lantern_free_camera_site);
    for (const FastTurnExit& exit : kFastTurnExits) placed = placed && JumpFrom(At(exit.at), sizeof exit.code, lantern_fast_turn_exit);
    if (!placed) {

        BbEngine::WriteCode(At(kFreeStore), kFreeStoreCode, sizeof kFreeStoreCode);
        for (const FastTurnExit& exit : kFastTurnExits) BbEngine::WriteCode(At(exit.at), exit.code, sizeof exit.code);
        BbEngine::Discard(entry);
        host_log("mouse camera: off, the follow camera's code could not be written");
        return false;
    }
    BbEngine::Commit(std::span(&entry, 1));
    g_installed = true;
    host_log("mouse camera: %.3f degrees a count at sensitivity 5, after the stick and only without it; a flick "
             "switches the lock-on target%s",
             MouseTurn::DegreesPerCount(5), g_patched_out ? "; a patch holds the camera's auto-rotation already" : "");
    return true;
}

bool Installed() { return g_installed; }

void AddCounts(float dx, float dy) {
    std::scoped_lock lock(g_counts_lock);
    g_count_x += dx;
    g_count_y += dy;
}

void Reset() {
    {
        std::scoped_lock lock(g_counts_lock);
        g_count_x = g_count_y = 0;
    }
    std::scoped_lock lock(g_flick_lock);
    g_flick_x = g_flick_y = 0;
    g_flick_updates = 0;
}

void Publish(int sensitivity, bool invert_x, bool invert_y, bool hold_auto_rotation) {
    g_degrees_per_count.store(MouseTurn::DegreesPerCount(sensitivity), std::memory_order_relaxed);
    g_invert_x.store(invert_x, std::memory_order_relaxed);
    g_invert_y.store(invert_y, std::memory_order_relaxed);

    static unsigned changes = 0;
    if (g_hold.exchange(hold_auto_rotation, std::memory_order_relaxed) != hold_auto_rotation && changes++ < 6)
        host_log("mouse camera: auto-rotation %s",
                 hold_auto_rotation ? "held (the keyboard and mouse in use)" : "the game's own");
}

void OrbitToggle(const char* key) {
    if (!g_installed) {
        std::printf("Camera: orbit unavailable (%s): the follow camera's hook is off (PC controls off, or not the "
                    "1.09 game)\n", key);
        return;
    }
    std::scoped_lock lock(g_orbit_lock);
    OrbitCommand& c = g_orbit;
    if (OrbitOn(c)) {
        c.want = false;
        g_orbit_drive = false;
        std::printf("Camera: %s off (%s)\n", c.path ? "path" : "orbit", key); // bbport (r102_camera-mode-3-4)
        return;
    }
    // Only while no loading screen is up and the follow camera's free path ran in the last 0.25 s;
    // expected to rule out the title screen, cutscenes and lock-on, where a neutral pad would only
    // block the game (not seen in a game run yet).
    const Clock::rep seen = g_follow_seen.load(std::memory_order_relaxed);
    const bool follow = seen && Clock::now() - Clock::time_point(Clock::duration(seen)) <= kFollowFresh;
    if (BbEngine::Loading::ScreenUp() || !follow) {
        std::printf("Camera: orbit unavailable (%s): the follow camera is not running (%s)\n", key,
                    BbEngine::Loading::ScreenUp() ? "a loading screen is up"
                                                  : "no camera update with its free path in the last 0.25 s");
        return;
    }
    // Every start begins at 12 degrees a second, height 0 and radius x1.0.
    c.want = true;
    c.serial = c.serial + 1 ? c.serial + 1 : 1;
    c.speed = CameraOrbit::kSpeedStart;
    c.height = 0;
    c.heights = {-CameraOrbit::kHeightStepsMost, CameraOrbit::kHeightStepsMost};
    c.radius = 1.0f;
    c.path = false; // bbport (r102_camera-mode-3-4)
    c.generation = BbEngine::Loading::Generation();
    g_orbit_generation = c.generation;
    g_orbit_drive = true;
    g_orbit_live = true;
    std::printf("Camera: orbit on (%s): %+.0f degrees a second, radius x%.1f\n", key, c.speed, c.radius);
}

void OrbitStop(const char* why) {
    std::scoped_lock lock(g_orbit_lock);
    if (!OrbitOn(g_orbit)) return;
    g_orbit.want = false;
    g_orbit_drive = false;
    std::printf("Camera: %s off (%s)\n", g_orbit.path ? "path" : "orbit", why); // bbport (r102_camera-mode-3-4)
}

void OrbitAdjust(int speed, int height, int radius, const char* keys) {
    std::scoped_lock lock(g_orbit_lock);
    OrbitCommand& c = g_orbit;
    if (!OrbitOn(c) || c.path) return; // bbport (r102_camera-mode-3-4): not while a path plays
    c.speed = CameraOrbit::NextSpeed(c.speed, speed);
    const int was = c.height;
    c.height = std::clamp(CameraOrbit::NextHeight(c.height, height), c.heights.least, c.heights.most);
    const bool held = height && c.height == was;
    if (radius && !BbEngine::Camera::Active()) {
        std::printf("Camera: orbit radius stays x1.0: it needs PC Camera Controls (camera_controls=1) at start\n");
    } else {
        c.radius = CameraOrbit::NextRadius(c.radius, radius);
    }
    std::printf("Camera: orbit %+.0f degrees a second, height %+d (%+.0f degrees%s), radius x%.1f (%s)\n", c.speed,
                c.height, float(c.height) * CameraOrbit::kHeightStep,
                held ? ", no further: the game's pitch limit or 8 steps" : "", c.radius, keys);
}

bool OrbitDriving() {
    return g_orbit_drive.load(std::memory_order_relaxed) &&
           g_orbit_generation.load(std::memory_order_relaxed) == BbEngine::Loading::Generation();
}

// bbport (r102b_camera-clean-hud): BB_CAMERA_ORBIT=<degrees a second> starts the orbit by itself once a run,
// as F4 does, when the follow camera has run for 2 s (no gap over 0.25 s, no loading screen up) with
// the settings menu closed; at that speed (CameraOrbit::AutoSpeedFrom). Everything after the start is
// F4's orbit (the keys change it; F4, the menu, a loading screen or lock-on end it; it does not start
// again). For clips and test runs without a key. Unset (or 0, or not a number), or the follow
// camera's hook not installed: after the first frame OrbitFrame's one more cost is the test of a
// plain bool. The frame pacer's thread only.
namespace {
const char* FollowMissing(); // below, with the camera paths
bool g_auto_orbit_pending = true;
void OrbitAuto() {
    static const float speed = CameraOrbit::AutoSpeedFrom(std::getenv("BB_CAMERA_ORBIT"));
    if (speed == 0.0f) {
        g_auto_orbit_pending = false;
        return;
    }
    if (!g_installed) { // Install ran at the image's install, before the game's first frame
        g_auto_orbit_pending = false;
        std::printf("Camera: BB_CAMERA_ORBIT=%+.1f: unavailable, the follow camera's hook is off (PC controls "
                    "off, or not the 1.09 game)\n",
                    double(speed));
        return;
    }
    static bool said = false;
    if (!said) {
        said = true;
        std::printf("Camera: BB_CAMERA_ORBIT=%+.1f: the orbit starts by itself once a run, when the follow "
                    "camera has run for 2 s with the settings menu closed\n",
                    double(speed));
    }
    static Clock::time_point since{};
    const Clock::time_point now = Clock::now();
    if (FollowMissing() || BbOverlay::MenuOpen()) {
        since = {};
        return;
    }
    if (since == Clock::time_point{}) since = now;
    if (now - since < std::chrono::seconds(2)) return;
    g_auto_orbit_pending = false;
    std::scoped_lock lock(g_orbit_lock);
    OrbitCommand& c = g_orbit;
    if (OrbitOn(c)) return; // F4 or F6 came first
    // As OrbitToggle's start, at the knob's speed.
    c.want = true;
    c.serial = c.serial + 1 ? c.serial + 1 : 1;
    c.speed = speed;
    c.height = 0;
    c.heights = {-CameraOrbit::kHeightStepsMost, CameraOrbit::kHeightStepsMost};
    c.radius = 1.0f;
    c.path = false;
    c.generation = BbEngine::Loading::Generation();
    g_orbit_generation = c.generation;
    g_orbit_drive = true;
    g_orbit_live = true;
    std::printf("Camera: orbit on (BB_CAMERA_ORBIT): %+.1f degrees a second, radius x%.1f\n", double(c.speed),
                double(c.radius));
}
}

void OrbitFrame() {
    if (g_auto_orbit_pending) OrbitAuto(); // bbport (r102b_camera-clean-hud): BB_CAMERA_ORBIT
    if (!g_orbit_live.load(std::memory_order_relaxed) && !g_distance_moved.load(std::memory_order_relaxed)) return;
    const std::uint64_t generation = BbEngine::Loading::Generation();
    std::scoped_lock lock(g_orbit_lock);
    if (g_orbit_live.load(std::memory_order_relaxed) && g_orbit.generation != generation && RetireLocked())
        std::printf("Camera: %s off (a loading screen or a cutscene)\n", g_orbit.path ? "path" : "orbit"); // bbport (r102)
    if (g_distance_moved.load(std::memory_order_relaxed) && g_distance_generation != generation)
        SetDistanceLocked(1.0f, generation);
}

// bbport (r102_camera-mode-3-4): camera paths, the window's thread.
namespace {
// The path file: camera_path.txt in the engine's user folder (BB_GPU_USER_DIR), else in the working
// folder. Read at the first F5 or F6 of a run, written again at every F5 and Shift+F5.
std::string PathFile() {
    const char* dir = std::getenv("BB_GPU_USER_DIR");
    return dir && *dir ? std::string(dir) + "/camera_path.txt" : std::string("camera_path.txt");
}

float PathSeconds() {
    static const float seconds = CameraPath::SecondsFrom(std::getenv("BB_CAMERA_PATH_S"));
    return seconds;
}

void LoadPath() {
    if (g_path_loaded) return;
    g_path_loaded = true;
    std::FILE* f = std::fopen(PathFile().c_str(), "r");
    if (!f) return;
    char line[256];
    CameraPath::Key k;
    while (g_path_keys.size() < CameraPath::kKeysMost && std::fgets(line, sizeof line, f))
        if (CameraPath::Parse(line, k)) g_path_keys.push_back(k);
    std::fclose(f);
    std::printf("Camera: path file read, %zu keys, %.1f s a key (BB_CAMERA_PATH_S)\n", g_path_keys.size(),
                double(PathSeconds()));
}

void SavePath() {
    std::FILE* f = std::fopen(PathFile().c_str(), "w");
    if (!f) {
        std::printf("Camera: the path file could not be written\n");
        return;
    }
    std::fputs("# camera mode path (F5 adds a key, Shift+F5 clears, F6 plays): yaw and pitch in degrees, "
               "then the distance factor\n", f);
    char line[96];
    for (const CameraPath::Key& k : g_path_keys) {
        CameraPath::Format(k, line, sizeof line);
        std::fprintf(f, "%s\n", line);
    }
    std::fclose(f);
}

// The follow camera ran its free path in the last 0.25 s and no loading screen is up (as for F4).
const char* FollowMissing() {
    if (BbEngine::Loading::ScreenUp()) return "a loading screen is up";
    const Clock::rep seen = g_follow_seen.load(std::memory_order_relaxed);
    const bool follow = seen && Clock::now() - Clock::time_point(Clock::duration(seen)) <= kFollowFresh;
    return follow ? nullptr : "no camera update with its free path in the last 0.25 s";
}
}

void PathKey(const char* key) {
    if (!g_installed) {
        std::printf("Camera: path key unavailable (%s): the follow camera's hook is off\n", key);
        return;
    }
    if (const char* why = FollowMissing()) {
        std::printf("Camera: path key unavailable (%s): the follow camera is not running (%s)\n", key, why);
        return;
    }
    LoadPath();
    if (g_path_keys.size() >= CameraPath::kKeysMost) {
        std::printf("Camera: path key refused (%s): %zu keys already (Shift+F5 clears)\n", key, g_path_keys.size());
        return;
    }
    const CameraPath::Key k{g_seen_yaw.load(std::memory_order_relaxed), g_seen_pitch.load(std::memory_order_relaxed),
                            std::clamp(g_seen_radius.load(std::memory_order_relaxed), CameraPath::kRadiusLeast,
                                       CameraPath::kRadiusMost)};
    if (!std::isfinite(k.yaw) || !std::isfinite(k.pitch)) return;
    g_path_keys.push_back(k);
    SavePath();
    std::printf("Camera: path key %zu: yaw %+.1f, pitch %+.1f degrees, radius x%.2f (%s)\n", g_path_keys.size(),
                double(k.yaw / CameraPath::kRadiansPerDegree), double(k.pitch / CameraPath::kRadiansPerDegree),
                double(k.radius), key);
}

void PathClear(const char* key) {
    g_path_loaded = true;
    const std::size_t had = g_path_keys.size();
    g_path_keys.clear();
    SavePath();
    std::printf("Camera: path cleared, %zu keys (%s)\n", had, key);
}

void PathToggle(const char* key) {
    if (!g_installed) {
        std::printf("Camera: path unavailable (%s): the follow camera's hook is off\n", key);
        return;
    }
    LoadPath();
    std::scoped_lock lock(g_orbit_lock);
    OrbitCommand& c = g_orbit;
    if (OrbitOn(c)) {
        if (!c.path) {
            std::printf("Camera: path not started (%s): the orbit is on (F4 stops it)\n", key);
            return;
        }
        c.want = false;
        g_orbit_drive = false;
        std::printf("Camera: path off (%s)\n", key);
        return;
    }
    if (g_path_keys.empty()) {
        std::printf("Camera: path has no keys (%s): F5 adds the camera's pose as one\n", key);
        return;
    }
    if (const char* why = FollowMissing()) {
        std::printf("Camera: path unavailable (%s): the follow camera is not running (%s)\n", key, why);
        return;
    }
    g_path_play = g_path_keys;
    g_path_seconds = PathSeconds();
    c.path = true;
    c.want = true;
    c.serial = c.serial + 1 ? c.serial + 1 : 1;
    c.generation = BbEngine::Loading::Generation();
    g_orbit_generation = c.generation;
    g_orbit_drive = true;
    g_orbit_live = true;
    const CameraPath::Timing t = CameraPath::TimingFor(g_path_play.size() + 1, PathSeconds());
    std::printf("Camera: path on (%s): %zu keys, %.1f s a key, about %.1f s\n", key, g_path_play.size(),
                double(PathSeconds()), double(t.total));
}

bool Flick(float& x, float& y) {
    const Clock::time_point now = Clock::now();
    float dt = g_last_read == Clock::time_point{} ? 0.0f : std::chrono::duration<float>(now - g_last_read).count();
    dt = std::min(dt, 0.25f);
    g_last_read = now;
    float dx, dy;
    unsigned updates;
    {
        std::scoped_lock lock(g_flick_lock);
        dx = g_flick_x;
        dy = g_flick_y;
        updates = g_flick_updates;
        g_flick_x = g_flick_y = 0;
        g_flick_updates = 0;
    }
    if (updates && dt > 0) {
        const float distance = std::hypot(dx, dy);
        const float rate = distance / dt;
        g_cooldown = rate < kFlickRearmRate ? 0.0f : std::max(0.0f, g_cooldown - dt);
        if (g_cooldown <= 0 && rate > kFlickRate) {
            g_shown_x = dx / distance;
            g_shown_y = dy / distance;
            g_shown_until = now + kFlickShown;
            g_cooldown = kFlickCooldown;
            if (g_flicks.fetch_add(1, std::memory_order_relaxed) < 4)
                host_log("mouse camera: a flick of %.0f counts (%.0f a second) switches the lock-on target toward "
                         "%+.2f,%+.2f", distance, rate, g_shown_x, g_shown_y);
        }
    }
    if (now >= g_shown_until) return false;
    x = g_shown_x;
    y = g_shown_y;
    return true;
}
}

extern "C" __attribute__((sysv_abi)) void lantern_free_camera_turn(std::uint8_t* camera, std::uint8_t* had_input,
                                                                    float stick_pitch, float stick_yaw) {
    using namespace MouseCamera;
    __atomic_store_n(&lantern_free_camera_ran, 1, __ATOMIC_RELAXED);
    {
        float seen;
        std::memcpy(&seen, camera + kYaw, 4);
        BbEngine::OnlineFixes::SetCameraYaw(seen);
        // bbport (r102_camera-mode-3-4): the pose F5 adds to a camera path.
        float seen_pitch;
        std::memcpy(&seen_pitch, camera + kPitch, 4);
        g_seen_yaw.store(seen, std::memory_order_relaxed);
        g_seen_pitch.store(seen_pitch, std::memory_order_relaxed);
    }
    // Camera mode's orbit owns the camera while it runs; off, this is the one check it costs.
    if (g_orbit_live.load(std::memory_order_relaxed) && OrbitTurn(camera, had_input, stick_pitch, stick_yaw)) return;
    // bbport (r120_test-camera-lookat, TOOL): BB_TEST_CAMERA holds the camera's fields (after the orbit, which owns the camera
    // while it runs; before the mouse's turn); off, this is one relaxed load of a false flag
    if (BbTestCamera::HoldWanted() && BbTestCamera::HoldApply(camera, had_input)) return;
    if (g_update_x == 0 && g_update_y == 0) return;
    if (stick_pitch != 0 || stick_yaw != 0) return;
    float pitch, yaw, highest, lowest;
    std::memcpy(&pitch, camera + kPitch, 4);
    std::memcpy(&yaw, camera + kYaw, 4);
    std::memcpy(&highest, camera + kHighest, 4);
    std::memcpy(&lowest, camera + kLowest, 4);
    const float was_pitch = pitch, was_yaw = yaw;
    const MouseTurn::Settings s{g_degrees_per_count.load(std::memory_order_relaxed),
                                g_invert_x.load(std::memory_order_relaxed), g_invert_y.load(std::memory_order_relaxed)};
    if (!MouseTurn::Turn(g_update_x, g_update_y, s, pitch, yaw, lowest, highest)) return;
    std::memcpy(camera + kPitch, &pitch, 4);
    std::memcpy(camera + kYaw, &yaw, 4);
    *had_input = 1;
    if (g_turns.fetch_add(1, std::memory_order_relaxed) == 0)
        host_log("mouse camera: first turn, %+.0f,%+.0f counts: pitch %.4f -> %.4f, yaw %.4f -> %.4f", g_update_x,
                 g_update_y, was_pitch, pitch, was_yaw, yaw);
}
