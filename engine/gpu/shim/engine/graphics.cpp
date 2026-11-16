// SPDX-License-Identifier: GPL-3.0-or-later
#include "graphics.h"
#include "engine_hooks.h"
#include "native_sss.h"
#include "bbport_platform.h"
#include "bbport_settings.h"
#include "bbport_toggles.h"
#include "bbport_sun_cascades.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>

namespace BbEngine::Graphics {
namespace {
#define GUEST_ABI __attribute__((sysv_abi))

constexpr std::size_t kRenderView = 0x229e990;
constexpr std::uint8_t kRenderViewEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55,
                                             0x41, 0x54, 0x53, 0x48, 0x81, 0xec, 0xa8, 0x0e, 0x00, 0x00};
constexpr std::size_t kSsaoSwitch = 0x2968, kBlurSwitch = 0x2969, kAaSwitch = 0x296a;

constexpr std::size_t kSsaoDraw = 0xe669d0;
constexpr std::uint8_t kSsaoDrawEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55,
                                           0x41, 0x54, 0x53, 0x48, 0x81, 0xec, 0xa8, 0x02, 0x00, 0x00};
constexpr std::size_t kSsaoScale = 0x14c + 0x44, kSsaoOffset = 0x14c + 0x48;

constexpr std::size_t kShadowSetup = 0xeac210;
constexpr std::uint8_t kShadowSetupEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x41, 0x56, 0x53, 0x48,
                                              0x83, 0xec, 0x18, 0x49, 0x89, 0xf6, 0x48, 0x89, 0xfb};
constexpr std::size_t kShadowDistances[] = {0x38, 0x3c, 0x44, 0x48};
constexpr std::size_t kCascadeRange = 0xeac540, kCascadeRangeTail = 0xeac657;
constexpr std::uint8_t kCascadeRangeEntry[] = {
    0xc5, 0xf8, 0x28, 0x02, 0xc5, 0xf8, 0x29, 0x06, 0xc5, 0xf8, 0x28, 0x42, 0x10,
    0xc5, 0xf8, 0x29, 0x46, 0x10};
constexpr std::uint8_t kCascadeRangeStores[] = {
    0xc5, 0xfa, 0x11, 0x46, 0x54, 0xc5, 0xf2, 0x5d, 0x42, 0x58, 0xc5, 0xfa, 0x11, 0x46, 0x58};
constexpr float kCascadeBlend = 0.1f;
constexpr std::size_t kDirectionalSizeTable = 0x48a9668, kDirectionalSizeDefault = 0xeac238;
constexpr std::uint32_t kDirectionalSizes[] = {2048, 1024, 2048, 4096};
constexpr std::uint8_t kDirectionalSizeCode[] = {
    0xb8, 0x00, 0x08, 0x00, 0x00, 0x48, 0x83, 0xf9, 0x03, 0x77, 0x0a,
    0x48, 0x8d, 0x05, 0x1e, 0xd4, 0x9f, 0x03, 0x8b, 0x04, 0x88};
std::atomic<bool> g_cascade_overlap{false};
// bbport (r14_cascade-rotate): the top of the game's cascade loop (in 0x229cb70): r14d is the
// cascade, r15 the shadow object, [rbp-0x998] the camera block, [rbp-0x960] the light direction.
// A cascade left out runs "inc r14d" and jumps to the exit test "cmp r14d,4; jne top", so the
// game neither draws it nor touches its matrices (they stay as when it last drew).
constexpr std::size_t kCascadeLoopTop = 0x229cfc0, kCascadeLoopTest = 0x229d263;
constexpr std::uint8_t kCascadeLoopTopCode[] = {0x48, 0x8b, 0x95, 0x68, 0xf6, 0xff, 0xff, 0xc5, 0xf8, 0x28,
                                                0x02, 0xc5, 0xf8, 0x29, 0x85, 0x40, 0xff, 0xff, 0xff};
constexpr std::uint8_t kCascadeLoopTestCode[] = {0x41, 0x83, 0xfe, 0x04, 0x0f, 0x85, 0x53, 0xfd, 0xff, 0xff};
constexpr std::uint8_t kNextCascade[] = {0x41, 0xff, 0xc6}; // inc r14d
constexpr std::uint64_t kLoopCamera = 0x998, kLoopLight = 0x960; // below rbp
constexpr std::size_t kSunDistances = 0x6d0, kShadowAtlasWidth = 0x860;    // in the shadow object
constexpr std::size_t kCascadeParams = 0x550, kCascadeParamSize = 0x50, kParamStable = 0x31;
constexpr unsigned kSunWarmup = 4, kSunLogRuns = 600;
constexpr float kSunMarginTexels = 8;
std::array<unsigned, 4> g_sun_every{1, 1, 1, 1}, g_sun_phase{};
unsigned g_sun_period = 0; ///< BbSunCascades::skip_period while the experiment bit is clear
bool g_sun_rotate = false; ///< four periods given (else the first N cascades every frame)
// bbport (r15_far-shadow-setting): the schedule of each graphics_sun_far_shadows value, as
// BB_SUN_CASCADES would give it; "game" installs nothing.
constexpr const char* kSunFarPatterns[] = {nullptr, "1 1 2 2", "1 1 8 8"};
static_assert(sizeof(kSunFarPatterns) / sizeof(kSunFarPatterns[0]) == BbSettings::SunFarShadowsCount);
char g_sun_from[48] = "BB_SUN_CASCADES"; ///< what chose the schedule, for the log

constexpr std::size_t kLocalShadowPool = 0x22440b0, kLocalShadowSize = 0x224443f;
constexpr std::uint8_t kLocalShadowPoolEntry[] = {
    0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41, 0x54, 0x53,
    0x48, 0x81, 0xe4, 0xe0, 0xff, 0xff, 0xff, 0x48, 0x81, 0xec, 0x20, 0x01, 0x00, 0x00};
constexpr std::uint8_t kLocalShadowSizeRead[] = {
    0x41, 0x8b, 0x44, 0x24, 0x14, 0x4d, 0x89, 0xe6, 0x4c, 0x89, 0x74, 0x24, 0x58,
    0x89, 0x44, 0x24, 0x44};
constexpr std::size_t kLocalShadowTier = 0x2244cb0;
constexpr std::uint8_t kLocalShadowTierCode[] = {
    0x41, 0xd1, 0xed, 0x48, 0xff, 0xc1, 0x48, 0x83, 0xf9, 0x04};
constexpr std::size_t kSpotShadowSize = 0x22440ed, kSpotShadowTier = 0x224442a;
constexpr std::uint8_t kSpotShadowSizeRead[] = {
    0x41, 0x8b, 0x04, 0x24, 0x89, 0x44, 0x24, 0x68, 0x48, 0x8d, 0x4b, 0x10,
    0x48, 0x89, 0x4c, 0x24, 0x50, 0x49, 0x89, 0xdd, 0x45, 0x31, 0xff, 0x89, 0x44, 0x24, 0x60};
constexpr std::uint8_t kSpotShadowTierCode[] = {
    0xd1, 0x6c, 0x24, 0x68, 0xd1, 0x6c, 0x24, 0x60, 0x49, 0xff, 0xc7, 0x49, 0x83, 0xff, 0x04};
constexpr std::size_t kPointShadowRadius = 0x4929c80, kSpotShadowRadius = 0x4929c84;
constexpr std::size_t kPointShadowRadiusLoad = 0x22b7011;
constexpr std::uint8_t kPointShadowRadiusCode[] = {0xc5, 0xfa, 0x10, 0x05, 0x67, 0x2c, 0x67, 0x02};
constexpr std::size_t kSpotShadowRadiusLoad = 0x22b7220, kSpotShadowRadiusLoadFallback = 0x22b7298;
constexpr std::uint8_t kSpotShadowRadiusCode[] = {0xc5, 0xfa, 0x10, 0x05, 0x5c, 0x2a, 0x67, 0x02};
constexpr std::uint8_t kSpotShadowRadiusFallbackCode[] = {0xc5, 0xfa, 0x10, 0x05, 0xe4, 0x29, 0x67, 0x02};
constexpr float kOriginalLocalShadowRadius = 3.2f;

int LocalShadowQuality() {
    return std::clamp(BbSettings::Get().graphics_local_shadow_resolution.load(std::memory_order_relaxed), 0, 2);
}

constexpr std::size_t kYebisRecord = 0x21d4860;
constexpr std::uint8_t kYebisRecordEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55,
                                              0x41, 0x54, 0x53, 0x48, 0x83, 0xec, 0x28, 0x4d, 0x89, 0xcd};
constexpr std::size_t kYebisBlockLoad = 0x21d4888;
constexpr std::uint8_t kLeaRax[] = {0x48, 0x8d, 0x05};
constexpr std::size_t kHue = 0xc4, kSaturation = 0xc8, kValue = 0xcc, kVignette = 0xd0, kGlare = 0xdc,
                      kContrast = 0x248;

constexpr std::size_t kFogRebuild = 0x22da690;
constexpr std::uint8_t kFogRebuildEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x41, 0x56, 0x41,
                                             0x55, 0x41, 0x54, 0x53, 0x48, 0x83, 0xec, 0x68};
constexpr std::size_t kFogJump = 0x22daadf, kFogPadding = 0x22daaf3, kTableUpload = 0xe2e6b0;
constexpr std::uint8_t kPadding[] = {0x66, 0x66, 0x66, 0x66, 0x2e, 0x0f, 0x1f, 0x84, 0, 0, 0, 0, 0};
constexpr std::size_t kFogMap = 0x248, kFogTable = 0x250, kFogCount = 0x258, kFogStride = 0x60 / 4;
constexpr int kFogOpacities[] = {0, 8, 12};

bool g_enabled = false;
std::uint8_t* g_post_block = nullptr;
thread_local std::uint64_t t_fog_manager = 0;

template <typename T> bool Peek(std::uint64_t at, T* out) {
    return at && BbPlatform::ReadProcessMemory(reinterpret_cast<const void*>(at), out, sizeof(T));
}
template <typename T> void Poke(std::uint64_t at, T value) {
    std::memcpy(reinterpret_cast<void*>(at), &value, sizeof value);
}
bool On() { return BbSettings::Get().graphics_controls.load(std::memory_order_relaxed); }
float Setting(const std::atomic<float>& v, float lo, float hi) {
    const float f = v.load(std::memory_order_relaxed);
    return std::isfinite(f) ? std::clamp(f, lo, hi) : 1.0f;
}

struct Written {
    std::uint64_t at = 0;
    float source = 0, value = 0;
};
std::array<Written, 256> g_written;
std::mutex g_written_mutex;

template <typename F> void Tune(std::uint64_t at, bool active, F&& f) {
    float now = 0;
    if (!at || !Peek(at, &now) || !std::isfinite(now)) return;
    std::scoped_lock lock(g_written_mutex);
    Written* own = nullptr;
    Written* empty = nullptr;
    for (auto& w : g_written) {
        if (w.at == at) { own = &w; break; }
        if (!empty && !w.at) empty = &w;
    }
    const bool ours = own && now == own->value;
    if (!active) {
        if (ours) Poke(at, own->source);
        if (own) *own = {};
        return;
    }
    const float source = ours ? own->source : now;
    const float value = f(source);
    Poke(at, value);
    if (Written* slot = own ? own : empty) *slot = {at, source, value};
}

struct Renderer {
    std::uint64_t at = 0;
    std::uint8_t ssao = 0, blur = 0, aa = 0;
};
std::array<Renderer, 8> g_renderers;
std::mutex g_renderer_mutex;
int g_blur_said = -1;

GUEST_ABI std::int64_t BeforeRenderView(std::uint64_t, const std::uint64_t* saved) {
    const std::uint64_t r = saved[0];
    Sss::BeforeRender(r);
    if (!r) return 0;
    std::scoped_lock lock(g_renderer_mutex);
    Renderer* own = nullptr;
    for (auto& x : g_renderers) if (x.at == r) { own = &x; break; }
    if (!own) {
        for (auto& x : g_renderers) {
            if (x.at) continue;
            if (!Peek(r + kSsaoSwitch, &x.ssao) || !Peek(r + kBlurSwitch, &x.blur) || !Peek(r + kAaSwitch, &x.aa)) return 0;
            x.at = r;
            own = &x;
            break;
        }
        if (!own) return 0;
    }
    const auto& s = BbSettings::Get();
    Poke<std::uint8_t>(r + kSsaoSwitch, own->ssao && s.effects[3].load(std::memory_order_relaxed));
    Poke<std::uint8_t>(r + kAaSwitch, own->aa && s.effects[4].load(std::memory_order_relaxed));
    const bool held = s.motion_blur_held.load(std::memory_order_relaxed);
    Poke<std::uint8_t>(r + kBlurSwitch, held ? 0 : own->blur);
    if (own->blur && g_blur_said != int(held)) {
        g_blur_said = int(held);
        std::printf(held ? "Engine: motion blur held off while the upscaler takes the finished frame (output "
                           "other than 1080p), the setting unchanged (BB_UPSCALER_NO_BLUR)\n"
                         : "Engine: motion blur on (the game's own)\n");
    }
    return 0;
}

GUEST_ABI std::int64_t BeforeSsaoDraw(std::uint64_t, const std::uint64_t* saved) {
    const std::uint64_t object = saved[5];
    if (!object) return 0;
    const float k = Setting(BbSettings::Get().graphics_ao_strength, 0.0f, 5.0f);
    const bool active = On() && k != 1;
    Tune(object + kSsaoScale, active, [k](float v) { return v * k; });
    Tune(object + kSsaoOffset, active, [k](float v) { return v * k + (1 - k); });
    return 0;
}

/// bbport (r14_cascade-rotate): which sun cascades the game draws in a run of its cascade loop.
using SunVec = std::array<float, 3>;
struct SunCamera { ///< the camera block the cascade loop copies ([rbp-0x998]; 0x2291c30 reads it)
    float world[16];            ///< view to world, row vectors (what the fit moves the corners by)
    float other[4];
    float fov, clip_near, clip_far; ///< vertical field of view (radians), clip distances
    std::uint32_t width, height;
};
static_assert(offsetof(SunCamera, fov) == 0x50 && offsetof(SunCamera, width) == 0x5c && sizeof(SunCamera) == 0x64,
              "the game's camera block");
struct SunBox { ///< what a cascade covered when it last drew, in the light axes it was fitted in
    std::array<SunVec, 3> axis{};
    SunVec light{}; ///< the sun's direction then (unit length)
    float centre[3]{}, half[3]{}, margin[3]{};
    bool valid = false;
};
/// A kept cascade is drawn again once the sun has turned more than 0.25 degrees since it drew
/// (cos 0.25 deg): its map would show shadows cast from the old direction.
constexpr float kSunLightKeep = 0.9999905f;
struct SunTrack { ///< one shadow object (one view's sun shadows)
    std::uint64_t object = 0;
    std::uint32_t runs = 0, warm = 0, atlas = 0;
    std::chrono::steady_clock::time_point last{};
    std::array<SunBox, 4> box{};
    std::array<bool, 4> draw{};
};
std::mutex g_sun_mutex;
std::array<SunTrack, 4> g_sun_tracks;
std::array<std::array<unsigned, 4>, 3> g_sun_counts{}; ///< left out, drawn as the camera left, other early draws
unsigned g_sun_runs = 0;
int g_sun_said = -1;
bool g_sun_fit_said = false;

float SunDot(const SunVec& a, const SunVec& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
SunVec SunCross(const SunVec& a, const SunVec& b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}
bool SunUnit(SunVec& v) {
    const float l = std::sqrt(SunDot(v, v));
    if (!(l > 1e-6f) || !std::isfinite(l)) return false;
    for (float& x : v) x /= l;
    return true;
}

/// The light axes of the game's fit (0xeb1ef0): z = -light as it is (not normalised), x across
/// "up" ((0,1,0), or (1,0,0) for a light within 2.6 degrees of vertical), y across both. Signs do
/// not matter here.
bool SunAxes(const float* light, std::array<SunVec, 3>& axis) {
    axis[2] = {-light[0], -light[1], -light[2]};
    const SunVec up = std::fabs(axis[2][1]) > 0.999f ? SunVec{1, 0, 0} : SunVec{0, 1, 0};
    axis[0] = SunCross(up, axis[2]);
    axis[1] = SunCross(axis[2], axis[0]);
    return SunUnit(axis[0]) && SunUnit(axis[1]) && std::isfinite(SunDot(axis[2], axis[2]));
}

/// The corners of cascade c's slice of the camera's view in world space as the game's fit builds
/// them: near and far as 0xeac540 picks them (BeforeCascadeRangeStores moves near), the corners as
/// 0x22926f0 (far plane first, x sign alternating), moved to world space by the camera matrix
/// (0x2291c30 inverts it twice; 0xeb1ef0 uses the result as is). Returns why it cannot, or null.
const char* SunWorldCorners(std::uint64_t object, const SunCamera& cam, unsigned c, std::array<SunVec, 8>& out) {
    float s[6]; // near, far, fade, ends of c0..c2: 0xeac210 writes them right before the loop
    std::memcpy(s, reinterpret_cast<const void*>(object + kSunDistances), sizeof s);
    const float lo[] = {s[0], s[3], s[4], s[5]}, hi[] = {s[3], s[4], s[5], s[1] + s[2]};
    float from = lo[c], to = hi[c];
    if (!(to - from > 1e-5f)) to = from + 0.001f;
    to = std::min(to, cam.clip_far);
    if (c > 0 && g_cascade_overlap.load(std::memory_order_relaxed)) {
        const float previous = c > 1 ? s[1 + c] : 0.0f;
        if (from > previous && cam.clip_near <= from)
            from = std::max(cam.clip_near, from - kCascadeBlend * (from - previous));
    }
    const float t = std::tan(cam.fov * 0.5f);
    const float aspect = cam.height ? float(cam.width) / float(cam.height) : 0.0f;
    if (!std::isfinite(from) || !std::isfinite(to) || !(to > from) || !std::isfinite(t) || !(t > 0) ||
        !std::isfinite(aspect) || !(aspect > 0)) return "the camera or the cascade distances look wrong";
    const float* m = cam.world;
    if (std::fabs(m[3]) > 1e-3f || std::fabs(m[7]) > 1e-3f || std::fabs(m[11]) > 1e-3f || std::fabs(m[15] - 1) > 1e-3f)
        return "the camera matrix is not a row-vector affine one";
    for (unsigned i = 0; i < 8; ++i) {
        const float z = i < 4 ? to : from;
        const float x = ((i & 1) ? -z : z) * t * aspect, y = ((i & 2) ? -z : z) * t;
        for (unsigned j = 0; j < 3; ++j) out[i][j] = x * m[j] + y * m[4 + j] + z * m[8 + j] + m[12 + j];
        if (!std::isfinite(out[i][0]) || !std::isfinite(out[i][1]) || !std::isfinite(out[i][2]))
            return "the camera matrix looks wrong";
    }
    return nullptr;
}

/// What cascade c covers as the game fits it now (0xeb1ef0): with the cascade's "stable" switch a
/// cube of the slice's diameter around the middle of its light-space bounds, moved by whole texels;
/// without it the bounds themselves. kSunMarginTexels are kept back for that texel move and the
/// filters. Returns why it cannot tell, or null.
const char* SunFit(SunBox& box, std::uint64_t object, const SunCamera& cam, unsigned c, const float* light) {
    box.valid = false;
    const std::uint64_t params = object + kCascadeParams + c * kCascadeParamSize;
    std::uint32_t fit = 0, atlas = 0;
    std::uint8_t stable = 0;
    std::memcpy(&fit, reinterpret_cast<const void*>(params), sizeof fit);
    std::memcpy(&stable, reinterpret_cast<const void*>(params + kParamStable), sizeof stable);
    std::memcpy(&atlas, reinterpret_cast<const void*>(object + kShadowAtlasWidth), sizeof atlas);
    if (!fit) return "the cascade uses the game's other light fit (0xeb1030)";
    if (!SunAxes(light, box.axis)) return "the light direction looks wrong";
    box.light = {light[0], light[1], light[2]};
    if (!SunUnit(box.light)) return "the light direction looks wrong";
    std::array<SunVec, 8> w;
    if (const char* why = SunWorldCorners(object, cam, c, w)) return why;
    std::array<SunVec, 8> q;
    SunVec lo{}, hi{};
    for (unsigned i = 0; i < 8; ++i) {
        for (unsigned k = 0; k < 3; ++k) {
            q[i][k] = SunDot(w[i], box.axis[k]);
            lo[k] = i ? std::min(lo[k], q[i][k]) : q[i][k];
            hi[k] = i ? std::max(hi[k], q[i][k]) : q[i][k];
        }
    }
    const auto apart = [&q](unsigned a, unsigned b) {
        const SunVec d{q[a][0] - q[b][0], q[a][1] - q[b][1], q[a][2] - q[b][2]};
        return std::sqrt(SunDot(d, d));
    };
    const float diameter = std::max(apart(0, 3), apart(0, 7)); // the game's two diagonals
    const float texels = float(std::max(atlas / 2, 1u));
    for (unsigned k = 0; k < 3; ++k) {
        box.centre[k] = 0.5f * (lo[k] + hi[k]);
        box.half[k] = stable ? 0.5f * diameter : 0.5f * (hi[k] - lo[k]);
        box.margin[k] = kSunMarginTexels * 2 * box.half[k] / texels;
        if (!std::isfinite(box.centre[k]) || !std::isfinite(box.half[k]) || !(box.half[k] > 0))
            return "the fit came out empty";
    }
    box.valid = true;
    return nullptr;
}

/// Whether the camera's slice for cascade c still lies inside what the cascade covered when it
/// last drew, with the sun where it was then. The game's resolve does not check: a lookup
/// outside reads the next quadrant.
bool SunCovered(const SunBox& box, std::uint64_t object, const SunCamera& cam, unsigned c, const float* light) {
    std::array<SunVec, 8> w;
    SunVec sun{light[0], light[1], light[2]};
    if (!box.valid || !SunUnit(sun) || !(SunDot(sun, box.light) >= kSunLightKeep) ||
        SunWorldCorners(object, cam, c, w)) return false;
    for (const SunVec& p : w) {
        for (unsigned k = 0; k < 3; ++k) {
            if (!(std::fabs(SunDot(p, box.axis[k]) - box.centre[k]) <= box.half[k] - box.margin[k])) return false;
        }
    }
    return true;
}

void SunSay(bool off) {
    if (off) {
        std::printf("Engine: sun cascades: the game draws all four every frame (experiment bit set)\n");
    } else if (!g_sun_rotate) {
        std::printf("Engine: sun cascades: the game draws the first %u of 4 every frame (%s)\n",
                    unsigned(std::count(g_sun_every.begin(), g_sun_every.end(), 1u)), g_sun_from);
    } else {
        std::printf("Engine: sun cascades: the game draws c0..c3 every %u/%u/%u/%u frames (0 never, "
                    "%s), a left-out one sooner when the camera leaves what it covers; skip period %u\n",
                    g_sun_every[0], g_sun_every[1], g_sun_every[2], g_sun_every[3], g_sun_from, g_sun_period);
    }
}

/// BB_SUN_CASCADES: "N" (1-4) draws the first N cascades every frame (r13's meaning), or
/// "e0 e1 e2 e3" draws cascade c every e_c frames (1 every frame, 0 never, at most 60). e0 must
/// be 1: c0's first command (0xeb0d90, its 0x118 flag) clears the whole atlas, so a frame
/// without c0 would draw the other cascades over last frame's depth.
bool SunParse(const char* text) {
    std::array<unsigned long, 5> n{};
    unsigned count = 0;
    for (const char* p = text; *p;) {
        if (*p == ' ' || *p == ',' || *p == '\t') { ++p; continue; }
        char* end = nullptr;
        const unsigned long v = std::strtoul(p, &end, 10);
        if (end == p || count == n.size()) return false;
        n[count++] = v;
        p = end;
    }
    if (count == 1 && n[0] >= 1 && n[0] <= 4) {
        for (unsigned c = 0; c < 4; ++c) g_sun_every[c] = c < n[0] ? 1 : 0;
        g_sun_rotate = false;
        g_sun_period = 0;
        return true;
    }
    if (count != 4 || n[0] != 1 ||
        std::any_of(n.begin(), n.begin() + 4, [](unsigned long v) { return v > 60; })) return false;
    g_sun_rotate = true;
    g_sun_period = 0;
    unsigned rotating = 0;
    for (int c = 3; c >= 0; --c) { // farthest first: c3 and c2 at period 2 take turns
        g_sun_every[c] = unsigned(n[c]);
        if (g_sun_every[c] > 1) g_sun_phase[c] = rotating++ % g_sun_every[c];
        if (g_sun_every[c] > 1) g_sun_period = std::max(g_sun_period, g_sun_every[c]);
    }
    return true;
}

SunTrack& SunTrackFor(std::uint64_t object) {
    SunTrack* slot = &g_sun_tracks[0];
    for (SunTrack& t : g_sun_tracks) {
        if (t.object == object) return t;
        if (t.last < slot->last) slot = &t; // a new view takes the slot used longest ago
    }
    *slot = {};
    slot->object = object;
    slot->draw.fill(true);
    return *slot;
}

/// The plan for one run of the loop, made when it reaches cascade 0.
void SunPlan(SunTrack& t, std::uint64_t rbp, std::uint64_t object) {
    const bool off = BbToggle::Experiment(BbSunCascades::kOffBit);
    if (g_sun_said != int(off)) {
        g_sun_said = int(off);
        BbSunCascades::skip_period.store(off ? 0 : g_sun_period, std::memory_order_relaxed);
        SunSay(off);
    }
    t.draw.fill(true);
    const auto now = std::chrono::steady_clock::now();
    std::uint32_t atlas = 0;
    std::memcpy(&atlas, reinterpret_cast<const void*>(object + kShadowAtlasWidth), sizeof atlas);
    // The experiment bit, a new atlas (0xeac210 reallocates it) or a pause of the loop (loading):
    // every cascade is drawn again for kSunWarmup runs before any is left out.
    if (off || atlas != t.atlas || now - t.last > std::chrono::milliseconds(500)) {
        t.warm = 0;
        for (SunBox& b : t.box) b.valid = false;
    }
    t.last = now;
    t.atlas = atlas;
    if (off) return;
    ++t.runs;
    const bool warm = t.warm < kSunWarmup;
    if (warm) ++t.warm;
    SunCamera cam{};
    float light[4] = {};
    std::uint64_t camera = 0;
    std::memcpy(&camera, reinterpret_cast<const void*>(rbp - kLoopCamera), sizeof camera);
    std::memcpy(light, reinterpret_cast<const void*>(rbp - kLoopLight), sizeof light);
    if (camera) std::memcpy(&cam, reinterpret_cast<const void*>(camera), sizeof cam);
    bool any = false;
    for (unsigned c = 0; c < 4; ++c) {
        const unsigned every = g_sun_every[c];
        bool draw = every == 1 || (every > 1 && t.runs % every == g_sun_phase[c]);
        if (every > 1 && !draw) {
            const int why =
                warm || !camera || !t.box[c].valid ? 2 : SunCovered(t.box[c], object, cam, c, light) ? 0 : 1;
            draw = why != 0;
            ++g_sun_counts[why][c];
        }
        t.draw[c] = draw;
        any = any || draw;
    }
    // A run that draws nothing would leave the game's shadow constants unwritten for the frame.
    for (unsigned c = 0; c < 4 && !any; ++c) {
        if (!g_sun_every[c]) continue;
        t.draw[c] = any = true;
        --g_sun_counts[0][c];
        ++g_sun_counts[2][c];
    }
    for (unsigned c = 0; c < 4; ++c) {
        if (!t.draw[c] || g_sun_every[c] < 2) continue;
        const char* why = camera ? SunFit(t.box[c], object, cam, c, light) : "no camera block";
        if (why && !g_sun_fit_said) {
            g_sun_fit_said = true;
            std::printf("Engine: sun cascades: c%u is drawn every frame while this lasts: %s\n", c, why);
        }
    }
    if (++g_sun_runs % kSunLogRuns == 0) {
        const auto& n = g_sun_counts;
        std::printf("Engine: sun cascades: in %u loop runs c0..c3 left out %u %u %u %u times, drawn early as the "
                    "camera left what they cover %u %u %u %u, for a (re)start or without a record %u %u %u %u\n",
                    kSunLogRuns, n[0][0], n[0][1], n[0][2], n[0][3], n[1][0], n[1][1], n[1][2], n[1][3], n[2][0],
                    n[2][1], n[2][2], n[2][3]);
        g_sun_counts = {};
    }
}

/// At the loop top, once per cascade (r14d) on the game's render thread: non-zero leaves the
/// cascade out (the stub runs "inc r14d" and jumps to the exit test).
GUEST_ABI std::int64_t AtCascadeLoopTop(std::uint64_t, const std::uint64_t* saved) {
    const std::uint64_t cascade = saved[kSavedR14] & 0xffffffffu, rbp = saved[kSavedRbp], object = saved[kSavedR15];
    if (cascade > 3 || !rbp || !object) return 0;
    std::scoped_lock lock(g_sun_mutex);
    SunTrack& t = SunTrackFor(object);
    if (cascade == 0) SunPlan(t, rbp, object);
    return t.draw[cascade] ? 0 : 1;
}

GUEST_ABI std::int64_t BeforeShadowSetup(std::uint64_t, const std::uint64_t* saved) {
    const std::uint64_t block = saved[4];
    if (!block) return 0;
    const float k = Setting(BbSettings::Get().graphics_shadow_scale, 0.25f, 8.0f);
    const bool active = On() && k != 1;
    for (const std::size_t at : kShadowDistances) Tune(block + at, active, [k](float v) { return v * k; });
    return 0;
}

GUEST_ABI std::int64_t BeforeCascadeRangeStores(std::uint64_t, const std::uint64_t* saved) {
    const unsigned cascade = unsigned(saved[1]);
    if (cascade == 0 || cascade > 3 || !saved[5] || !saved[3]) return 0;
    float near = 0, previous = 0, camera_near = 0;
    std::memcpy(&near, SavedXmm(saved, 0), sizeof near);
    if (cascade > 1 && !Peek(saved[5] + 0x6dc + 4 * (cascade - 2), &previous)) return 0;
    if (!Peek(saved[3] + 0x54, &camera_near) ||
        !std::isfinite(near) || !std::isfinite(previous) || !std::isfinite(camera_near) ||
        near <= previous || camera_near > near) return 0;
    near = std::max(camera_near, near - kCascadeBlend * (near - previous));
    std::memcpy(const_cast<std::uint8_t*>(SavedXmm(saved, 0)), &near, sizeof near);
    return 0;
}

GUEST_ABI std::int64_t BeforeYebisRecord(std::uint64_t, const std::uint64_t*) {
    if (!g_post_block) return 0;
    const bool on = On();
    const auto& s = BbSettings::Get();
    const auto block = reinterpret_cast<std::uint64_t>(g_post_block);
    const float bloom = Setting(s.graphics_bloom, 0.0f, 10.0f), saturation = Setting(s.graphics_saturation, 0.0f, 5.0f);
    const float bright = Setting(s.graphics_brightness, 0.0f, 5.0f), contrast = Setting(s.graphics_contrast, 0.5f, 1.5f);
    const float hue = std::clamp(std::isfinite(s.graphics_hue.load()) ? s.graphics_hue.load() : 0.0f, -180.0f, 180.0f);
    const bool vignette = s.graphics_vignette.load(std::memory_order_relaxed);
    Tune(block + kGlare, on && bloom != 1, [bloom](float v) { return v * bloom; });
    Tune(block + kSaturation, on && saturation != 1, [saturation](float v) { return v * saturation; });
    Tune(block + kValue, on && bright != 1, [bright](float v) { return v * bright; });
    Tune(block + kContrast, on && contrast != 1, [contrast](float v) { return v * contrast; });
    Tune(block + kHue, on && hue != 0, [hue](float v) { return v + hue; });
    Tune(block + kVignette, on && !vignette, [](float) { return 0.0f; });
    return 0;
}

GUEST_ABI std::int64_t BeforeFogRebuild(std::uint64_t, const std::uint64_t* saved) {
    t_fog_manager = saved[5];
    return 0;
}

GUEST_ABI std::int64_t BeforeFogUpload(std::uint64_t, const std::uint64_t* saved) {
    const std::uint64_t manager = t_fog_manager;
    t_fog_manager = 0;
    const float k = Setting(BbSettings::Get().graphics_fog, 0.0f, 5.0f);
    std::uint64_t map = 0, table = 0;
    std::uint32_t count = 0;
    if (!On() || k == 1 || !Peek(manager + kFogMap, &map) || !Peek(manager + kFogTable, &table) ||
        !Peek(manager + kFogCount, &count) || map != saved[5] || table != saved[3] || !table || !count ||
        count > 4096) return 0;
    auto* fog = reinterpret_cast<float*>(table);
    for (std::uint32_t i = 0; i < count; ++i) {
        for (const int o : kFogOpacities) {
            float& a = fog[i * kFogStride + o];
            a = k > 1 ? std::min(a * k, std::max(a, 1.0f)) : a * k;
        }
    }
    return 0;
}

bool Matches(const std::uint8_t* image, std::size_t size, std::size_t at, const std::uint8_t* bytes, std::size_t n) {
    return at <= size && n <= size - at && std::memcmp(image + at, bytes, n) == 0;
}

bool RedirectFogUpload(std::uint8_t* image, std::size_t size, std::uint8_t** stub) {
    *stub = nullptr;
    if (!Matches(image, size, kFogPadding, kPadding, sizeof kPadding) || image[kFogJump] != 0xe9) return false;
    std::int32_t rel = 0;
    std::memcpy(&rel, image + kFogJump + 1, 4);
    if (std::int64_t(kFogJump + 5) + rel != std::int64_t(kTableUpload)) return false;
    *stub = TailStub(BeforeFogUpload, reinterpret_cast<std::uint64_t>(image + kTableUpload));
    return *stub != nullptr;
}
void CommitFogUpload(std::uint8_t* image, std::uint8_t* stub) {
    std::uint8_t* p = image + kFogPadding;
    const auto to = reinterpret_cast<std::uint64_t>(stub);
    *p++ = 0x49;
    *p++ = 0xbb;
    std::memcpy(p, &to, 8);
    p += 8;
    *p++ = 0x41;
    *p++ = 0xff;
    *p = 0xe3;
    const auto rel = std::int32_t(std::int64_t(kFogPadding) - std::int64_t(kFogJump + 5));
    std::memcpy(image + kFogJump + 1, &rel, 4);
}
}

bool Enabled() { return g_enabled; }

float DirectionalShadowBlend() {
    return g_cascade_overlap.load(std::memory_order_relaxed) ? kCascadeBlend : 0.0f;
}

bool InstallDirectionalShadowResolution(std::uint8_t* image, std::size_t size) {
    if (!image ||
        !Matches(image, size, kDirectionalSizeTable,
                 reinterpret_cast<const std::uint8_t*>(kDirectionalSizes), sizeof kDirectionalSizes) ||
        !Matches(image, size, kDirectionalSizeDefault, kDirectionalSizeCode, sizeof kDirectionalSizeCode)) {
        std::printf("Engine: directional shadow resolution unavailable: allocation code differs from 1.09\n");
        return false;
    }
    const int quality = std::clamp(
        BbSettings::Get().graphics_shadow_resolution.load(std::memory_order_relaxed), 0, 2);
    if (quality == 0) return false;
    const std::uint32_t atlas = 2048u << quality;
    const std::array<std::uint32_t, 4> sizes{atlas, atlas, atlas, atlas};
    if (!WriteCode(image + kDirectionalSizeTable, sizes.data(), sizeof sizes) ||
        !WriteCode(image + kDirectionalSizeDefault + 1, &atlas, sizeof atlas)) {
        std::printf("Engine: directional shadow resolution incomplete: cannot write native allocation settings\n");
        return false;
    }
    std::printf("Engine: directional shadow atlas %ux%u, four %ux%u cascades (restart to change)\n",
                atlas, atlas, atlas / 2, atlas / 2);
    return true;
}

bool InstallDirectionalShadows(std::uint8_t* image, std::size_t size) {
    const auto& settings = BbSettings::Get();
    if (!settings.startup_effects[BbSettings::EffectPcss] &&
        !settings.startup_effects[BbSettings::EffectContactShadows]) {
        return false;
    }
    Hook hook;
    if (!image || !Matches(image, size, kCascadeRange, kCascadeRangeEntry, sizeof kCascadeRangeEntry) ||
        !Prepare(hook, image, size, kCascadeRangeTail, kCascadeRangeStores, BeforeCascadeRangeStores)) {
        std::printf("Engine: directional overlap off: cascade code does not match 1.09 or hook unavailable\n");
        return false;
    }
    Commit(std::span<Hook>{&hook, 1});
    g_cascade_overlap.store(true, std::memory_order_relaxed);
    std::printf("Engine: directional cascades overlap by 10%%; authored splits and atlas size retained\n");
    return true;
}

bool InstallLocalShadowSoftness(std::uint8_t* image, std::size_t size, bool point, bool spot) {
    if ((!point && !spot) || LocalShadowQuality() == 0) return true;
    const auto radius_matches = [&](std::size_t at) {
        return Matches(image, size, at, reinterpret_cast<const std::uint8_t*>(&kOriginalLocalShadowRadius),
                       sizeof kOriginalLocalShadowRadius);
    };
    if (!image ||
        (point && (!radius_matches(kPointShadowRadius) ||
                   !Matches(image, size, kPointShadowRadiusLoad, kPointShadowRadiusCode,
                            sizeof kPointShadowRadiusCode))) ||
        (spot && (!radius_matches(kSpotShadowRadius) ||
                  !Matches(image, size, kSpotShadowRadiusLoad, kSpotShadowRadiusCode,
                           sizeof kSpotShadowRadiusCode) ||
                  !Matches(image, size, kSpotShadowRadiusLoadFallback, kSpotShadowRadiusFallbackCode,
                           sizeof kSpotShadowRadiusFallbackCode)))) {
        std::printf("Engine: local-shadow filter tuning unavailable: the filter code is not 1.09's\n");
        return false;
    }
    const float radius = LocalShadowQuality() == 1 ? 3.2f : 6.4f;
    for (const auto at : {point ? kPointShadowRadius : 0, spot ? kSpotShadowRadius : 0}) {
        if (at && !WriteCode(image + at, &radius, sizeof radius)) {
            std::printf("Engine: local-shadow filter tuning incomplete: cannot write filter radius at %zx\n", at);
            return false;
        }
    }
    std::printf("Engine: local-shadow filter radius %.1f texels (point %s, spotlight %s); high-resolution maps kept\n",
                radius, point ? "on" : "unchanged", spot ? "on" : "unchanged");
    return true;
}

bool InstallLocalShadows(std::uint8_t* image, std::size_t size) {
    const int quality = LocalShadowQuality();
    if (quality == 0) return false;
    if (!image ||
        !Matches(image, size, kLocalShadowPool, kLocalShadowPoolEntry, sizeof kLocalShadowPoolEntry) ||
        !Matches(image, size, kLocalShadowSize, kLocalShadowSizeRead, sizeof kLocalShadowSizeRead) ||
        !Matches(image, size, kLocalShadowTier, kLocalShadowTierCode, sizeof kLocalShadowTierCode)) {
        std::printf("Engine: higher-resolution point shadows off: the pool code is not 1.09's\n");
        return false;
    }
    const std::uint32_t base = quality == 1 ? 1024u : 2048u;
    std::array<std::uint8_t, 5> resolution{0xb8};
    std::memcpy(resolution.data() + 1, &base, sizeof base);
    if (!WriteCode(image + kLocalShadowSize, resolution.data(), resolution.size())) {
        std::printf("Engine: higher-resolution point shadows off: cannot write the pool size\n");
        return false;
    }
    std::printf("Engine: native point-shadow faces %u/%u/%u/%u; other pools untouched by point patch\n",
                base, base / 2, base / 4, base / 8);
    return true;
}

bool InstallSpotShadows(std::uint8_t* image, std::size_t size) {
    const int quality = LocalShadowQuality();
    if (quality == 0) return false;
    if (!image ||
        !Matches(image, size, kLocalShadowPool, kLocalShadowPoolEntry, sizeof kLocalShadowPoolEntry) ||
        !Matches(image, size, kSpotShadowSize, kSpotShadowSizeRead, sizeof kSpotShadowSizeRead) ||
        !Matches(image, size, kSpotShadowTier, kSpotShadowTierCode, sizeof kSpotShadowTierCode)) {
        std::printf("Engine: higher-resolution spotlight shadows off: the pool code is not 1.09's\n");
        return false;
    }
    const std::uint8_t resolution[] = {0x31, 0xc0, 0xb4, std::uint8_t(quality == 1 ? 8 : 16)};
    if (!WriteCode(image + kSpotShadowSize, resolution, sizeof resolution)) {
        std::printf("Engine: higher-resolution spotlight shadows off: cannot write the pool size\n");
        return false;
    }
    const unsigned base = quality == 1 ? 2048u : 4096u;
    std::printf("Engine: native spotlight shadow maps %u/%u/%u/%u; directional pool unchanged\n",
                base, base / 2, base / 4, base / 8);
    return true;
}

bool Install(std::uint8_t* image, std::size_t size) {
    const std::size_t lea_end = kYebisBlockLoad + sizeof kLeaRax + 4;
    if (!Matches(image, size, kYebisBlockLoad, kLeaRax, sizeof kLeaRax)) {
        std::printf("Engine: picture tuning off: the game's code is not 1.09's\n");
        return false;
    }
    std::int32_t d = 0;
    std::memcpy(&d, image + kYebisBlockLoad + sizeof kLeaRax, 4);
    const std::size_t block = std::size_t(std::int64_t(lea_end) + d);
    if (block > size - (kContrast + 4)) return false;

    std::array<Hook, 5> hooks;
    const bool ready = Prepare(hooks[0], image, size, kRenderView, kRenderViewEntry, BeforeRenderView) &&
                       Prepare(hooks[1], image, size, kYebisRecord, kYebisRecordEntry, BeforeYebisRecord) &&
                       Prepare(hooks[2], image, size, kSsaoDraw, kSsaoDrawEntry, BeforeSsaoDraw) &&
                       Prepare(hooks[3], image, size, kShadowSetup, kShadowSetupEntry, BeforeShadowSetup);
    if (!ready) {
        for (auto& h : hooks) Discard(h);
        std::printf("Engine: picture tuning off: the game's code is not 1.09's\n");
        return false;
    }
    std::uint8_t* fog_stub = nullptr;
    const bool fog = Prepare(hooks[4], image, size, kFogRebuild, kFogRebuildEntry, BeforeFogRebuild) &&
                     RedirectFogUpload(image, size, &fog_stub);
    if (!fog) {
        Discard(hooks[4]);
        FreeStub(fog_stub);
    }
    g_post_block = image + block;
    // bbport (r14_cascade-rotate, r15_far-shadow-setting): the cascade loop is hooked only with
    // BB_SUN_CASCADES or when lantern.ini's graphics_sun_far_shadows asks for fewer far cascade
    // draws. The start value is used: the hook is installed once, a change applies at restart.
    // The variable wins over the ini: test runs drive the schedule with it.
    Hook loop;
    const int far_shadows =
        std::clamp(BbSettings::Get().startup_sun_far_shadows, 0, BbSettings::SunFarShadowsCount - 1);
    const char* v = std::getenv("BB_SUN_CASCADES");
    if (v && *v) {
        if (far_shadows != BbSettings::SunFarGame) {
            std::printf("Engine: sun cascades: BB_SUN_CASCADES is set and decides; graphics_sun_far_shadows=%s "
                        "is not used\n", BbSettings::SunFarShadowsNames[far_shadows]);
        }
    } else {
        v = kSunFarPatterns[far_shadows];
        std::snprintf(g_sun_from, sizeof g_sun_from, "graphics_sun_far_shadows=%s",
                      BbSettings::SunFarShadowsNames[far_shadows]);
    }
    if (v && *v) {
        if (!SunParse(v)) {
            std::printf("Engine: BB_SUN_CASCADES='%s' ignored: give N (1-4, the first N cascades) or four periods "
                        "'1 e1 e2 e3' (1 every frame, 0 never, at most 60; c0 every frame, its pass clears the "
                        "whole atlas)\n", v);
        } else if (!Matches(image, size, kCascadeLoopTest, kCascadeLoopTestCode, sizeof kCascadeLoopTestCode) ||
                   !PrepareBranch(loop, image, size, kCascadeLoopTop, kCascadeLoopTopCode, AtCascadeLoopTop,
                                  kNextCascade, kCascadeLoopTest)) {
            std::printf("Engine: %s ignored: the cascade loop is not 1.09's\n", g_sun_from);
        } else {
            const bool off = BbToggle::Experiment(BbSunCascades::kOffBit);
            g_sun_said = int(off);
            BbSunCascades::skip_period.store(off ? 0 : g_sun_period, std::memory_order_relaxed);
            SunSay(off);
        }
    }
    Sss::Install(image, size);
    Commit(hooks);
    if (loop.site) Commit(std::span<Hook>{&loop, 1});
    if (fog) CommitFogUpload(image, fog_stub);
    g_enabled = true;
    std::printf("Engine: picture tuning ready (%s, live): AA, SSAO, AO strength, shadow distance, bloom, saturation, "
                "vignette, brightness, contrast, hue%s\n",
                On() ? "on" : "off", fog ? " and fog" : "; fog left alone, its code is not 1.09's");
    return true;
}
}
