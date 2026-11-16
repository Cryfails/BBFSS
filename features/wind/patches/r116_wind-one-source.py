# r116_wind-one-source: FEATURE patch (wind work, owner 2026-11-15 23:08: "didn't we decide that fog,
# particles, foliage, cloth, hair, etc should follow wind including the clouds, or maybe the clouds
# cause the wind? Then the wind goes broke or stopped by objects and walls"). Off with the wind: it
# only does anything with BB_WIND=1 (the weapon sparks' falling copies, the motes, the haze all read
# a zero wind otherwise, as before).
#
# What it does (audit by reading: see the context file's 2026-11-15 r116 section):
#  1. ONE HEADING. bbport_wind.h's heading (Snapshot::direction_deg) is declared to be the cloud
#     layer's: the cloud shadows travel toward it (they already read it with BB_WIND=1), the ground wind
#     blows toward it, gusts come from behind it (GustAt). New knob BB_WIND_WANDER: how far it wanders
#     either way, 0 (fixed) to MaxWander 45 deg, default Wander (15 deg, the old constant, so nothing
#     changes unless it is set). Fixed relation: the clouds move at CloudRatio (4) x the mean ground
#     speed; the cloud shadows' SpeedRatio is now that constant itself (was a second 4.0f).
#  2. ONE API. BbWind::WindAt(snapshot, x, z): the wind vector at a world point with the gust front
#     GustAt gives (zero without the wind); Felt(follower, snapshot, inv_view): that at the camera,
#     counted for the log line; ScreenVelocity: a world velocity as pixels a second.
#  3. FOLLOWERS THAT WERE NOT ON THE SHARED GUST: the ambient motes (and the embers the flames throw)
#     and the heat haze read the wind at the camera with the gust front (they read the uniform gust
#     of the origin's time before: plants and motes did not gust together); the weapon sparks'
#     falling copies (r110) drift downwind (they had no wind at all).
#  4. PROOF LINE. Every 600 wind steps: "Wind (r116): heading H deg (wanders +-W), speed S m/s, gusts
#     G, gust now xN, clouds x4; followers heading/gust: fog H/g noise H/g clouds H/g plants H/g motes
#     H/g haze H/g sparks H/g" (a follower that read nothing in the window: "-"). Every follower prints
#     the heading of the vector it was handed and its speed over the mean speed (the gust factor it
#     felt; the clouds' is 1.00 by design); they must all show the same H.
#
# Files (no host shader, CMake or build.sh file: every shader build is byte-identical, nothing to
# recompile there): gpu/shim/bbport_wind.h (Params::wander, Sanitize, WanderDeg overload, Snapshot
# gusts/wander/cloud_speed, WindAt, Follower, Use, UseHeading, Felt, HeadingDeg, ScreenVelocity,
# FollowersText), vk_rasterizer_effects.cpp (BB_WIND_WANDER read, once-line, the 600-step line, five
# Use lines at the followers' reads, the haze's wind argument), vk_rasterizer.cpp (the motes' wind
# argument), vk_weapon_sparks.cpp (r110's file: the copies' wind drift), vk_cloud_shadow.h (two getters),
# cloud_shadow_params.h (SpeedRatio = BbWind::CloudRatio), tests/test_wind.cpp (block r), README.md (a row).
#
# Off (BB_WIND unset): WindOnFrameEnd returns before the new line (it never reaches it); the Use calls
# return on !snapshot.on after one test; Felt returns {0,0,0}, the same floats as Snapshot::wind has
# without the wind; the sparks' drift is added only under w.on. WanderDeg with p.wander = Wander is the
# 2-argument function (same operation). Cost on: per follower read a few relaxed atomic stores (one per
# frame for each, the plants once per view); the motes and the haze one GustAt (one Noise1x2) a frame.
#
# Use: python -I -X utf8 r116_wind-one-source.py check | apply | revert
# Root: R116_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r116_backup next to this script; revert takes out exactly what apply put in (each inserted text is
# found by itself, so check and revert also work after a later patch inserted next to it).
import os, re, sys

ROOT = os.environ.get("R116_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r116_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
W = "engine/gpu/shim/bbport_wind.h"
E = RV + "vk_rasterizer_effects.cpp"
V = RV + "vk_rasterizer.cpp"
K = RV + "vk_weapon_sparks.cpp"
CH = RV + "vk_cloud_shadow.h"
CP = RV + "cloud_shadow_params.h"
T = "engine/tests/test_wind.cpp"
R = "README.md"
ORDER = (W, E, V, K, CH, CP, T, R)

# ---------------------------------------------------------------------------------------------
# bbport_wind.h
# ---------------------------------------------------------------------------------------------
W_CONSTS = r'''/// bbport (r116_wind-one-source): the heading is the cloud layer's and the ground wind's. MaxWander:
/// the most it may wander (BB_WIND_WANDER, deg either way; the default is Wander, 15). CloudRatio: the
/// clouds move at this many times the mean ground wind speed (the ground wind blows at 1 / CloudRatio of
/// the cloud speed, toward the same heading; the clouds feel no gusts).
inline constexpr float MaxWander = 45.0f;
inline constexpr float CloudRatio = 4.0f;
'''

W_PARAM = r'''    float wander = Wander;                  ///< deg: the heading wanders this far either way (0-MaxWander; 0: fixed)
'''

W_SAN = r'''    p.wander = std::clamp(FiniteOr(p.wander, Wander), 0.0f, MaxWander);
'''

W_WANDER_OLD = r'''inline float WanderDeg(double t, float base_deg) {
    return base_deg + Wander * Noise1(t / WanderPeriod);
}
'''

W_WANDER_NEW = r'''
/// bbport (r116_wind-one-source): the same with the wander set (BB_WIND_WANDER); at Wander it is the
/// function above.
inline float WanderDeg(double t, float base_deg, float wander) {
    return base_deg + wander * Noise1(t / WanderPeriod);
}
'''

W_ADV_OLD = "        const float deg = WanderDeg(snapshot.time, p.direction_deg);\n"
W_ADV_NEW = "        const float deg = WanderDeg(snapshot.time, p.direction_deg, p.wander);\n"

W_ADV_FIELDS = r'''        snapshot.gusts = p.gusts;
        snapshot.wander = p.wander;
        snapshot.cloud_speed = CloudRatio * p.speed;
'''

W_SNAP = r'''    float gusts = 0.0f;       ///< Params::gusts after Sanitize (r116: GustAt needs it)
    float wander = 0.0f;      ///< Params::wander after Sanitize: the heading wanders this far either way
    float cloud_speed = 0.0f; ///< m/s: CloudRatio x speed, how fast the clouds move toward the heading
'''

W_API = r'''// bbport (r116_wind-one-source): ONE wind for everything that moves with air. The heading
// (Snapshot::direction_deg) is the cloud layer's: the cloud shadows travel toward it, the ground wind
// blows toward it and the gusts come from behind it (GustAt: a gust front reaches the plants upwind first).
// It wanders by slow noise (a new cell every WanderPeriod = 120 s of wind time) at most
// Snapshot::wander deg either way; wind time is the sum of the frame steps (0 at the first frame with
// BB_WIND=1), one value per frame for every follower, so it is the same for all of them and continuous.
// The speeds are tied: the clouds CloudRatio x the mean speed, the ground wind 1 / CloudRatio of that,
// the gust factor at a point GustAt (the clouds feel none). Followers read it through Snapshot or WindAt,
// never through a wind of their own.

/// The wind (m/s) at world point (x, z): speed x GustAt x the heading's vector (y 0); zero without the
/// wind. At (0, 0) it is Snapshot::wind (the same floats).
inline std::array<float, 3> WindAt(const Snapshot& s, float x, float z) {
    if (!s.on) {
        return {0.0f, 0.0f, 0.0f};
    }
    const float u = s.speed * GustAt(s.time, s.gusts, x, z, s.dir_x, s.dir_z, s.speed);
    return {u * s.dir_x, 0.0f, u * s.dir_z};
}

/// The things that read the shared wind and are named in the 600-step line.
enum class Follower : std::size_t { Fog, FogNoise, Clouds, Plants, Motes, Haze, Sparks, Count };
inline constexpr std::size_t FollowerCount = std::size_t(Follower::Count);
inline constexpr std::array<const char*, FollowerCount> FollowerNames{"fog",   "noise", "clouds", "plants",
                                                                      "motes", "haze",  "sparks"};
static_assert(FollowerNames[FollowerCount - 1] != nullptr, "a name for every follower");

/// The heading (deg, 0 = +x, 90 = +z, in [0, 360)) of the vector (x, z); 0 for the zero vector or a
/// value that is not finite.
inline float HeadingDeg(float x, float z) {
    if (!std::isfinite(x) || !std::isfinite(z)) {
        return 0.0f;
    }
    double deg = std::atan2(double(z), double(x)) * (180.0 / 3.14159265358979323846);
    if (deg < 0.0) {
        deg += 360.0;
    }
    const float f = float(deg);
    return f >= 360.0f ? 0.0f : f;
}

/// What a follower last read: its heading, the gust factor (its speed over share x the mean speed), how
/// many reads since the last line. Relaxed atomics: followers run on several threads.
struct FollowerNote {
    std::atomic<float> heading{0.0f};
    std::atomic<float> gust{0.0f};
    std::atomic<std::uint32_t> uses{0};
};

inline std::array<FollowerNote, FollowerCount>& Notes() {
    static std::array<FollowerNote, FollowerCount> notes;
    return notes;
}

/// A follower read the wind with heading `heading_deg` and speed `speed` (m/s), of which `share` is
/// its own constant (the clouds: CloudRatio; the others 1). Nothing without the wind, without a speed
/// or with values that are not finite.
inline void UseHeading(Follower f, const Snapshot& s, float heading_deg, float speed, float share) {
    if (!s.on || !std::isfinite(heading_deg) || !std::isfinite(speed) || !(speed > 0.0f) ||
        !(share > 0.0f) || !(s.speed > 0.0f)) {
        return;
    }
    FollowerNote& n = Notes()[std::size_t(f)];
    n.heading.store(heading_deg, std::memory_order_relaxed);
    n.gust.store(speed / (share * s.speed), std::memory_order_relaxed);
    n.uses.fetch_add(1, std::memory_order_relaxed);
}

/// A follower was handed the wind vector v (m/s).
inline void Use(Follower f, const Snapshot& s, const std::array<float, 3>& v) {
    UseHeading(f, s, HeadingDeg(v[0], v[2]), std::sqrt(v[0] * v[0] + v[2] * v[2]), 1.0f);
}

/// The wind at the camera (`inv_view`: 3x4 rows, translation in [3], [7], [11]), counted for `f`.
inline std::array<float, 3> Felt(Follower f, const Snapshot& s, const std::array<float, 12>& inv_view) {
    const std::array<float, 3> v = WindAt(s, inv_view[3], inv_view[11]);
    Use(f, s, v);
    return v;
}

/// A world velocity v (m/s) as the pixels a second it moves a point `depth` m in front of the camera
/// in a width x height viewport: the rotation of the view rows (3x4, world to view), then
/// ndc = view.xy x proj.xy / depth (proj as CameraMotion::Matrices::proj, the particles' convention),
/// ndc 1 = half the viewport. {0, 0} for a depth that is not above 0.
inline std::array<float, 2> ScreenVelocity(const std::array<float, 12>& view,
                                           const std::array<float, 4>& proj,
                                           const std::array<float, 3>& v, float depth, float width,
                                           float height) {
    if (!(depth > 0.0f)) {
        return {0.0f, 0.0f};
    }
    const float vx = view[0] * v[0] + view[1] * v[1] + view[2] * v[2];
    const float vy = view[4] * v[0] + view[5] * v[1] + view[6] * v[2];
    return {vx * proj[0] / depth * 0.5f * width, vy * proj[1] / depth * 0.5f * height};
}

/// The 600-step line (at most about 250 characters: the slot runs keep 300): the shared heading, speed
/// and gusts, then each follower's heading and gust factor as read since the last line ("-": it read
/// nothing). Resets the counts. Returns snprintf's result for `out`.
inline int FollowersText(const Snapshot& s, char* out, std::size_t size) {
    char list[256];
    std::size_t at = 0;
    list[0] = '\0';
    for (std::size_t i = 0; i < FollowerCount; ++i) {
        FollowerNote& n = Notes()[i];
        const bool read = n.uses.exchange(0, std::memory_order_relaxed) != 0;
        const int w =
            read ? std::snprintf(list + at, sizeof(list) - at, " %s %.1f/%.2f", FollowerNames[i],
                                 double(n.heading.load(std::memory_order_relaxed)),
                                 double(n.gust.load(std::memory_order_relaxed)))
                 : std::snprintf(list + at, sizeof(list) - at, " %s -", FollowerNames[i]);
        if (w < 0 || std::size_t(w) >= sizeof(list) - at) {
            break;
        }
        at += std::size_t(w);
    }
    return std::snprintf(out, size,
                         "Wind (r116): heading %.1f deg (wanders +-%.0f), speed %.2f m/s, gusts %.2f, "
                         "gust now x%.2f, clouds x%.0f; followers heading/gust:%s",
                         double(s.direction_deg), double(s.wander), double(s.speed), double(s.gusts),
                         double(s.gust), double(CloudRatio), list);
}

'''

# ---------------------------------------------------------------------------------------------
# vk_rasterizer_effects.cpp
# ---------------------------------------------------------------------------------------------
E_WANDER = '''            .wander = number("BB_WIND_WANDER", BbWind::Wander),
'''

E_ONCE = r'''            BbReport::Printf("Wind (r116, BB_WIND=1): one heading for the clouds and the wind: toward "
                             "%.0f deg, wandering at most %.0f deg either way (BB_WIND_WANDER); the "
                             "clouds move at %.0fx the mean speed, gusts come from upwind; a Wind "
                             "(r116) line every 600 frames says what each follower read\n",
                             double(p.direction_deg), double(p.wander), double(BbWind::CloudRatio));
'''

E_LINE = r'''    // bbport (r116_wind-one-source): every 600 wind steps one line: the shared heading and what each
    // follower read since the last one
    static std::uint32_t follower_steps = 0;
    if (++follower_steps % 600u == 0) {
        char followers[320];
        BbWind::FollowersText(s, followers, sizeof(followers));
        BbReport::Printf("%s\n", followers);
    }
'''

E_CLOUD = '''        BbWind::UseHeading(BbWind::Follower::Clouds, w, cloud_shadow->Direction(),
                           cloud_shadow->Velocity(), BbWind::CloudRatio); // bbport (r116)
'''
E_PLANTS = '''        BbWind::Use(BbWind::Follower::Plants, snapshot, snapshot.wind); // bbport (r116)
'''
E_FOG = '''            BbWind::Use(BbWind::Follower::Fog, w, w.wind); // bbport (r116)
'''
E_NOISE = '''            BbWind::Use(BbWind::Follower::FogNoise, w, w.wind); // bbport (r116)
'''
E_HAZE_OLD = '''        heat_haze->Apply(upscaler->SceneColor(), camera_motion->Depth(), upscaler->Jitter(),
                         wind.Get().wind);
'''
E_HAZE_NEW = '''        heat_haze->Apply(upscaler->SceneColor(), camera_motion->Depth(), upscaler->Jitter(),
                         BbWind::Felt(BbWind::Follower::Haze, wind.Get(),
                                      camera_motion->CameraMatrices().inv_view)); // bbport (r116)
'''

# ---------------------------------------------------------------------------------------------
# vk_rasterizer.cpp (the motes)
# ---------------------------------------------------------------------------------------------
V_OLD = '''                ambient_particles->Draw(frame, camera_motion->CameraMatrices(), w.on, w.wind);
'''
V_NEW = '''                // bbport (r116_wind-one-source): the wind at the camera, gust front included
                const CameraMotion::Matrices cam = camera_motion->CameraMatrices();
                ambient_particles->Draw(frame, cam, w.on,
                                        BbWind::Felt(BbWind::Follower::Motes, w, cam.inv_view));
'''

# ---------------------------------------------------------------------------------------------
# vk_weapon_sparks.cpp (r110's file)
# ---------------------------------------------------------------------------------------------
K_CONST = r'''// bbport (r116_wind-one-source): with BB_WIND=1 a falling copy also drifts downwind: SparksWindFollow
// of the wind at the camera (gust front included), as a point SparksWindDepth m in front of the camera
// would move on the screen.
constexpr float SparksWindFollow = 0.3f;
constexpr float SparksWindDepth = 3.0f;
'''
K_BREEZE = r'''        // bbport (r116_wind-one-source): BB_WIND=1 only: the copies drift downwind (pixels a second)
        std::array<float, 2> breeze{};
        if (const BbWind::Snapshot w = wind.Get(); w.on) {
            const CameraMotion::Matrices cam = camera_motion->CameraMatrices();
            if (cam.valid) {
                const std::array<float, 3> v = BbWind::Felt(BbWind::Follower::Sparks, w, cam.inv_view);
                breeze = BbWind::ScreenVelocity(cam.view, cam.proj, v, SparksWindDepth,
                                                std::abs(viewports[0].width), height);
                breeze[0] *= SparksWindFollow;
                breeze[1] *= SparksWindFollow;
            }
        }
'''
K_OFF_OLD = '''            offsets[copy_count++] = {side * t * height,
                                     (0.5f * SparksGravity * t * t - up * t) * height};
'''
K_OFF_NEW = '''            offsets[copy_count++] = {side * t * height + breeze[0] * t,
                                     (0.5f * SparksGravity * t * t - up * t) * height + breeze[1] * t};
'''

# ---------------------------------------------------------------------------------------------
# vk_cloud_shadow.h, cloud_shadow_params.h
# ---------------------------------------------------------------------------------------------
CH_GET = r'''    /// bbport (r116_wind-one-source): the heading (deg) and speed (m/s) the clouds move at now, for the
    /// wind's follower line.
    float Direction() const {
        return state.Direction();
    }
    float Velocity() const {
        return knobs.Velocity();
    }
'''
CP_OLD = "inline constexpr float SpeedRatio = 4.0f;\n"
CP_NEW = "inline constexpr float SpeedRatio = BbWind::CloudRatio; // bbport (r116_wind-one-source): one ratio\n"

# ---------------------------------------------------------------------------------------------
# tests/test_wind.cpp
# ---------------------------------------------------------------------------------------------
T_BLOCK = r'''    // r. r116_wind-one-source: the heading's wander knob, the wind at a point, the followers' line.
    {
        const float qnan = std::numeric_limits<float>::quiet_NaN();
        // WanderDeg with the wander set: at Wander it is the 2-argument function, at 0 the base heading,
        // at MaxWander still within MaxWander of it (an hour of wind time, odd steps).
        bool same = true, fixed = true, bounded = true;
        for (int i = 0; i <= 3600; ++i) {
            same = same && std::fabs(WanderDeg(double(i), 225.0f, Wander) - WanderDeg(double(i), 225.0f)) <= 1e-5f;
            fixed = fixed && WanderDeg(double(i), 225.0f, 0.0f) == 225.0f;
            const float deg = WanderDeg(double(i) * 7.3, 100.0f, MaxWander);
            bounded = bounded && deg >= 100.0f - MaxWander && deg <= 100.0f + MaxWander;
        }
        Expect(same, "WanderDeg at Wander is the 2-argument WanderDeg");
        Expect(fixed, "WanderDeg with wander 0 is the base heading");
        Expect(bounded, "WanderDeg stays within MaxWander of the base heading");
        Expect(Params{}.wander == Wander && MaxWander >= Wander && CloudRatio == 4.0f,
               "defaults: wander 15, ratio 4");
        // Sanitize: not finite is the default, negative 0, above MaxWander MaxWander.
        Expect(Sanitize({.on = true, .wander = qnan}).wander == Wander, "Sanitize: wander not finite is Wander");
        Expect(Sanitize({.on = true, .wander = -3.0f}).wander == 0.0f, "Sanitize: wander below 0 is 0");
        Expect(Sanitize({.on = true, .wander = 99.0f}).wander == MaxWander, "Sanitize: wander above the maximum");
        // The state: wander 0 holds the heading at its base for 120 s; the snapshot carries the knobs.
        Params p = On;
        p.direction_deg = 100.0f;
        p.wander = 0.0f;
        State fixed_state;
        bool held = true;
        for (int i = 0; i < 1200; ++i) {
            fixed_state.Advance(p, 0.1);
            held = held && fixed_state.Get().direction_deg == 100.0f;
        }
        Expect(held, "wander 0: the heading is the base heading at every step");
        const Snapshot f = fixed_state.Get();
        Expect(f.gusts == p.gusts && f.wander == 0.0f && f.cloud_speed == CloudRatio * p.speed,
               "the snapshot carries the gusts, the wander and the cloud speed");
        // The default wander is r82's: the same heading as WanderDeg(time, base) says.
        State moving;
        for (int i = 0; i < 600; ++i) {
            moving.Advance(On, 0.1);
        }
        const Snapshot m = moving.Get();
        float want = std::fmod(WanderDeg(m.time, DefaultDirection), 360.0f);
        if (want < 0.0f) {
            want += 360.0f;
        }
        Expect(std::fabs(m.direction_deg - want) <= 1e-4f && m.wander == Wander,
               "the default wander gives the heading r82 gave");
        // WindAt: zero without the wind; at the origin the snapshot's wind (bit for bit); downwind the
        // gust the origin had that much earlier (a front reaches the upwind side first).
        Expect(WindAt(Snapshot{}, 5.0f, 5.0f) == std::array<float, 3>{0.0f, 0.0f, 0.0f}, "WindAt without the wind is zero");
        Params g = On;
        g.gusts = 1.0f;
        g.speed = 2.0f;
        g.direction_deg = 30.0f;
        g.wander = 0.0f;
        State gs;
        for (int i = 0; i < 900; ++i) {
            gs.Advance(g, 0.1);
        }
        const Snapshot w = gs.Get();
        Expect(SameBits(WindAt(w, 0.0f, 0.0f), w.wind), "WindAt at the origin is the snapshot's wind");
        const float dx = 12.0f * w.dir_x, dz = 12.0f * w.dir_z;
        const auto down = WindAt(w, dx, dz);
        const float want_speed = w.speed * Gust(w.time - double(dx * w.dir_x + dz * w.dir_z) / double(std::max(w.speed, 0.1f)), w.gusts);
        Expect(std::fabs(std::hypot(down[0], down[2]) - want_speed) <= 1e-4f && down[1] == 0.0f,
               "WindAt 12 m downwind has the gust the origin had 6 s earlier");
        Expect(down[0] * w.dir_z - down[2] * w.dir_x <= 1e-5f * want_speed + 1e-6f &&
                   down[0] * w.dir_x + down[2] * w.dir_z >= 0.0f,
               "WindAt points along the heading");
        // HeadingDeg and ScreenVelocity.
        Expect(HeadingDeg(1.0f, 0.0f) == 0.0f && std::fabs(HeadingDeg(0.0f, 1.0f) - 90.0f) <= 1e-4f &&
                   std::fabs(HeadingDeg(-1.0f, 0.0f) - 180.0f) <= 1e-4f &&
                   std::fabs(HeadingDeg(-0.7071068f, -0.7071068f) - 225.0f) <= 1e-3f &&
                   HeadingDeg(0.0f, 0.0f) == 0.0f && HeadingDeg(qnan, 1.0f) == 0.0f,
               "HeadingDeg");
        const std::array<float, 12> identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const auto sx = ScreenVelocity(identity, {2.0f, -3.0f, 1.0f, 0.0f}, {1.0f, 0.0f, 0.0f}, 2.0f, 100.0f, 50.0f);
        const auto sy = ScreenVelocity(identity, {2.0f, -3.0f, 1.0f, 0.0f}, {0.0f, 1.0f, 0.0f}, 2.0f, 100.0f, 50.0f);
        Expect(std::fabs(sx[0] - 50.0f) <= 1e-4f && sx[1] == 0.0f && sy[0] == 0.0f && std::fabs(sy[1] + 37.5f) <= 1e-4f,
               "ScreenVelocity: x scale 2, y scale -3, depth 2, 100 x 50");
        const auto none = ScreenVelocity(identity, {2.0f, -3.0f, 1.0f, 0.0f}, {1.0f, 0.0f, 0.0f}, 0.0f, 100.0f, 50.0f);
        Expect(none[0] == 0.0f && none[1] == 0.0f, "ScreenVelocity at depth 0 is zero");
        // The followers' line: a follower that read prints its heading and gust, the others "-"; the
        // counts reset with each line; a read without the wind counts for nothing.
        char text[400];
        FollowersText(w, text, sizeof(text)); // clears whatever came before
        Use(Follower::Fog, w, w.wind);
        UseHeading(Follower::Clouds, w, w.direction_deg, w.cloud_speed, CloudRatio);
        Felt(Follower::Motes, w, identity);
        Use(Follower::Haze, Snapshot{}, w.wind);
        const FollowerNote& fog = Notes()[std::size_t(Follower::Fog)];
        const FollowerNote& clouds = Notes()[std::size_t(Follower::Clouds)];
        Expect(std::fabs(fog.heading.load() - w.direction_deg) <= 1e-3f && std::fabs(fog.gust.load() - w.gust) <= 1e-4f,
               "Use: the heading of the vector and the gust factor it holds");
        Expect(std::fabs(clouds.heading.load() - w.direction_deg) <= 1e-6f && std::fabs(clouds.gust.load() - 1.0f) <= 1e-5f,
               "UseHeading: the clouds' factor is 1 (no gusts, speed CloudRatio x the mean)");
        const int length = FollowersText(w, text, sizeof(text));
        Expect(length > 0 && length < 300, "the followers' line is under 300 characters");
        Expect(std::strstr(text, "Wind (r116): heading") == text && std::strstr(text, " fog ") != nullptr &&
                   std::strstr(text, " clouds ") != nullptr && std::strstr(text, " motes ") != nullptr &&
                   std::strstr(text, " noise -") != nullptr && std::strstr(text, " plants -") != nullptr &&
                   std::strstr(text, " haze -") != nullptr && std::strstr(text, " sparks -") != nullptr,
               "the followers' line names the readers and marks the others");
        FollowersText(w, text, sizeof(text));
        Expect(std::strstr(text, " fog -") != nullptr && std::strstr(text, " clouds -") != nullptr,
               "the counts reset with each line");
    }

'''

# ---------------------------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------------------------
README_ROW = ("| `BB_WIND_WANDER` | One heading for the clouds and the wind (r116): how far it wanders, degrees either "
              "way, 0 (fixed) to 45. The cloud shadows travel toward it, the ground wind blows toward it, the sun "
              "fog and lamp fog drift, the fog patches, the plants, the ambient motes and the embers the flames "
              "throw, the heat haze column and the falling copies of the weapon sparks all go the same way, and "
              "gusts come from behind it (a gust front reaches the upwind plants first; the motes, the haze and "
              "the sparks read the gust at the camera). It wanders by slow noise, one new value every 120 s of "
              "wind time, so over minutes and never past this bound; it is one number per frame for every "
              "follower, continuous, and wind time starts at 0 with the game, so a run repeats. The clouds move "
              "at 4 times the mean speed (`BB_WIND_SPEED`), the ground wind at a quarter of that, and the clouds "
              "feel no gusts. Needs `BB_WIND=1` (with it off the cloud shadows keep their own 15 degrees). Every "
              "600 frames a `Wind (r116):` line prints the heading, speed and gusts and, for each follower, the "
              "heading and gust factor it read since the last line (`-`: none); the headings must agree | `15` |\n")

# ---------------------------------------------------------------------------------------------
# The edit lists. ("after", needle, text): text goes after the one line that holds needle;
# ("before", needle, text): before it; ("afterblock", exact text, text): after that text;
# ("rep", old, new).
# ---------------------------------------------------------------------------------------------
EDITS = {
    W: [
        ("after", "inline constexpr float DefaultGusts = 0.5f;", W_CONSTS),
        ("after", "float gusts = DefaultGusts;", W_PARAM),
        ("after", "p.gusts = std::clamp(FiniteOr(p.gusts, DefaultGusts), 0.0f, MaxGusts);", W_SAN),
        ("afterblock", W_WANDER_OLD, W_WANDER_NEW),
        ("rep", W_ADV_OLD, W_ADV_NEW),
        ("after", "snapshot.gust = gust;", W_ADV_FIELDS),
        ("after", "std::array<float, 3> off2{}; ///< octave 2's offset, noise cells, each in [0, 256)", W_SNAP),
        ("before", "} // namespace BbWind", W_API),
        ("after", "#include <array>", "#include <atomic>\n"),
        ("after", "#include <cstdint>", "#include <cstdio>\n"),
    ],
    E: [
        ("after", '.gusts = number("BB_WIND_GUSTS", BbWind::DefaultGusts),', E_WANDER),
        ("after", "double(p.direction_deg), double(p.speed), double(p.gusts));", E_ONCE),
        ("before", "if (show && std::floor(s.time / 2.0) != std::floor(before / 2.0)) {", E_LINE),
        ("after", "cloud_shadow->OnFrameEnd(w.on, w.direction_deg);", E_CLOUD),
        ("after", "BbWindSway::FillView(camera, snapshot, knob.gusts, knob.scale, filled.data());", E_PLANTS),
        ("after", "volumetric_light->SetWind(w.off1, w.off2, camera.inv_view, camera.valid, WindShow());", E_FOG),
        ("after", "volumetric_light->SetFogNoise(w.on, w.time, w.wind, camera.inv_view, camera.valid);", E_NOISE),
        ("rep", E_HAZE_OLD, E_HAZE_NEW),
    ],
    V: [("rep", V_OLD, V_NEW)],
    K: [
        ("after", "constexpr float SparksLifeMin = 0.18f, SparksLifeRange = 0.37f;", K_CONST),
        ("after", "const float height = std::abs(viewports[0].height);", K_BREEZE),
        ("rep", K_OFF_OLD, K_OFF_NEW),
    ],
    CH: [("after", "void OnFrameEnd(bool wind_on, float wind_deg);", CH_GET)],
    CP: [("rep", CP_OLD, CP_NEW)],
    T: [("before", 'std::printf("wind-test: %d failure(s)\\n", failures);', None)],  # resolved below
    R: [("after", "| `BB_WIND_GUSTS` |", README_ROW)],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def line_of(cur, needle, path):
    """The one whole line (with its newline) that holds needle."""
    hits = [l for l in cur.split("\n") if needle in l]
    if len(hits) != 1:
        raise SystemExit("REFUSED %s: %d lines hold %r (wanted exactly 1)" % (path, len(hits), needle[:70]))
    return hits[0] + "\n"


def resolve(path, cur):
    """The edits as ('ins', anchor, before, after) or ('rep', old, new)."""
    out = []
    for kind, a, b in EDITS[path]:
        if path == T and b is None:
            # the test block goes before the `if (failures) {` that holds this printf
            anchor = "    if (failures) {\n"
            if cur.count(anchor) != 1:
                raise SystemExit("REFUSED %s: `if (failures) {` found %d times" % (path, cur.count(anchor)))
            out.append(("ins", anchor, T_BLOCK, ""))
        elif kind == "after":
            out.append(("ins", line_of(cur, a, path), "", b))
        elif kind == "before":
            out.append(("ins", line_of(cur, a, path), b, ""))
        elif kind == "afterblock":
            out.append(("ins", a, "", b))
        else:
            out.append(("rep", a, b))
    return out


def state_of(cur, eds, path):
    done = todo = 0
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            parts = [t for t in (before, after) if t]
            na, counts = cur.count(anchor), [cur.count(t) for t in parts]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                                 % (path, na, counts, anchor[:70]))
        else:
            _, old, new = e
            no, nn = cur.count(old), cur.count(new)
            if no == 0 and nn == 1:
                done += 1
            elif no == 1 and nn == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: old text %d times, new text %d times (wanted 1/0 or 0/1): %r"
                                 % (path, no, nn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_edits(cur, eds):
    for e in eds:
        if e[0] == "ins":
            cur = cur.replace(e[1], e[2] + e[1] + e[3], 1)
        else:
            cur = cur.replace(e[1], e[2], 1)
    return cur


def revert_edits(cur, eds):
    for e in reversed(eds):
        if e[0] == "ins":
            for part in (e[3], e[2]):
                if part:
                    cur = cur.replace(part, "", 1)
        else:
            cur = cur.replace(e[2], e[1], 1)
    return cur


def const(text, name):
    m = re.search(r"inline constexpr float %s = ([0-9.]+)f;" % name, text)
    if not m:
        raise SystemExit("text check: %s not found" % name)
    return float(m.group(1))


def text_checks(texts):
    """The ties a compiler cannot check."""
    w = texts[W]
    wander, maxw, ratio = const(w, "Wander"), const(w, "MaxWander"), const(w, "CloudRatio")
    if (wander, maxw, ratio) != (15.0, 45.0, 4.0):
        raise SystemExit("text check: Wander/MaxWander/CloudRatio are %r" % ((wander, maxw, ratio),))
    if "inline constexpr double WanderPeriod = 120.0;" not in w:
        raise SystemExit("text check: WanderPeriod is not 120 s")
    # the API sits after State (it reads Snapshot and GustAt) and before the namespace's end
    a, b, c = w.find("class State {"), w.find("inline std::array<float, 3> WindAt("), w.rfind("} // namespace BbWind")
    if not (0 <= a < b < c):
        raise SystemExit("text check: the r116 API is out of order in bbport_wind.h")
    if w.count("inline std::array<float, 3> WindAt(") != 1 or w.count("struct FollowerNote {") != 1:
        raise SystemExit("text check: the r116 API is there more than once")
    for inc in ("#include <atomic>", "#include <cstdio>"):
        if w.count(inc) != 1:
            raise SystemExit("text check: %s found %d times" % (inc, w.count(inc)))
    # one ratio: the cloud shadows' SpeedRatio is BbWind::CloudRatio and nothing else
    cp = texts[CP]
    if cp.count("inline constexpr float SpeedRatio = BbWind::CloudRatio;") != 1 or "SpeedRatio = 4.0f" in cp:
        raise SystemExit("text check: SpeedRatio is not tied to BbWind::CloudRatio")
    # the README row names the constants
    row = [l for l in texts[R].split("\n") if l.startswith("| `BB_WIND_WANDER` |")]
    if len(row) != 1 or "0 (fixed) to 45" not in row[0] or "4 times the mean speed" not in row[0] or \
            "every 120 s" not in row[0] or not row[0].rstrip().endswith("| `15` |"):
        raise SystemExit("text check: README row and the constants disagree")
    # the effects file: the knob is read next to its three neighbours, and every follower has its line
    e = texts[E]
    for want in ('.wander = number("BB_WIND_WANDER", BbWind::Wander),',
                 "BbWind::FollowersText(s, followers, sizeof(followers));",
                 "BbWind::Use(BbWind::Follower::Fog,", "BbWind::Use(BbWind::Follower::FogNoise,",
                 "BbWind::UseHeading(BbWind::Follower::Clouds,", "BbWind::Use(BbWind::Follower::Plants,",
                 "BbWind::Felt(BbWind::Follower::Haze,"):
        if e.count(want) != 1:
            raise SystemExit("text check: %s holds %r %d times" % (E, want, e.count(want)))
    if texts[V].count("BbWind::Felt(BbWind::Follower::Motes,") != 1:
        raise SystemExit("text check: the motes' read is not there once")
    k = texts[K]
    if k.count("BbWind::Felt(BbWind::Follower::Sparks,") != 1 or k.count("breeze[0] * t") != 1 or \
            k.count("breeze[1] * t") != 1:
        raise SystemExit("text check: the sparks' drift is not there once")
    # every Follower has a name and a read site (the names are in the header's array, the reads above)
    for name in ("Fog", "FogNoise", "Clouds", "Plants", "Motes", "Haze", "Sparks"):
        if w.count(name) < 1:
            raise SystemExit("text check: follower %s" % name)
    # nothing of this patch is a shader, a CMake file or a build script
    for p in ORDER:
        if p.endswith((".comp", ".glsl", ".vert", ".frag", "CMakeLists.txt", "build.sh")):
            raise SystemExit("text check: %s is a build input" % p)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R116_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        eds = resolve(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            new = apply_edits(cur, eds)
            if state_of(new, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = new
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r116tmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        new = revert_edits(cur, eds)
        if state_of(new, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = new.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r116tmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


# T_BLOCK is used through resolve(); the placeholder entry above only marks the test file's edit.
main()
