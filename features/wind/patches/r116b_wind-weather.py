# r116b_wind-weather: FEATURE patch (wind work, owner 2026-11-15 23:55-23:58, after a 4K clip of
# 1.5 m/s against 4 m/s: "Actually never mind on the wind speed change, we just need the wind to
# change dynamically based on clouds or something"; standing rules 22:58 "the sway ... very subtle
# unless it's strong wind", 23:08 "everything follows one wind, or maybe the clouds cause the wind").
# Builds on r116 (one heading, one snapshot) and r117 (the shelter's `open` argument of Advance); both
# are in the tree. Off with the wind: it only does anything with BB_WIND=1. With BB_WIND=1 the weather
# is ON by default (BB_WIND_WEATHER=0 or a set BB_WIND_SPEED gives r116's constant speed, bit for bit).
#
# What it does:
#  1. THE WEATHER. One slow signal of the wind's own world time (the clock the heading's wander and
#     the gusts already use; one value per frame for every follower, continuous, no jump on load or
#     camera moves) makes the MEAN wind speed: WeatherSpeed(clock) = 0.4 + 3.5 u^4 m/s with
#     u = (Noise1(clock / 120 s) + 1) / 2. Over one noise period (30720 s) it is calm (< 0.7 m/s)
#     55.9% of the time, light (0.7-1.5) 22.8%, in-between (1.5-3.0, building or easing, 2-2.5 is the
#     typical plateau) 17.3%, strong (>= 3.0) 4.0% (about 2 strong spells an hour of 68 s, the top
#     3.84 m/s, 3.5 and over 1% of the time), at most 0.09 m/s change per second. clock = BB_WIND_WEATHER_AT
#     + BB_WIND_WEATHER_RATE x wind time (rate 1 is real time; 20 makes a calm-to-strong cycle fit a
#     short clip). Snapshot::speed IS this speed, so every consumer that reads the snapshot (plant
#     lean r89c, hanging things r112, fog drift and banks, particles, sparks, haze, caustics, shelter
#     r117, the next twigs r89d and cloud layer r119) gets it with no private copy.
#  2. THE GUSTS FOLLOW IT. GustWeather(t, g, level): the strength is g x (0.3 + level) (level 0-1 =
#     the speed's place between 0.4 and 3.9), and the burst threshold moves with the level (rare when
#     calm: 2.6% of the time above x1.15, 39% when strong, mean 0.99 - 1.12), BbWind::GustOf(s, t) is
#     the one function that gives a gust factor at wind time t (the plant sway's and the hanging things'
#     tables, WindAt for the motes, haze and sparks), at the weather's level of THAT time.
#  3. THE CLOUDS FOLLOW IT. Snapshot::cloud_speed = CloudRatio x speed (r116's tie); the cloud shadows'
#     drift uses the snapshot's speed each frame (CloudShadows::State::Advance's wind_speed) and their
#     edges move with the level (cover: denser clouds when it is up, CoverGain 0.06 x (level - 0.3), at
#     most 0.042 lower edges, 0.018 higher; the cover value is Snapshot::weather for the cloud layer).
#  4. PROOF LINE. Each WeatherLine (60 s of weather clock; at rate 20 every 3 s): "Wind (r116b):
#     weather W (clock .., x..), speed now .. m/s (mean .., range ..-..), gust strength .. (x.. now),
#     clouds .. m/s, cover ..". W is calm / light / building / easing / strong. The r116 follower line
#     still prints what each follower read: the clouds' gust factor stays 1.00 whatever the speed, the
#     plants' is the gust factor, all headings agree.
#
# Knobs: BB_WIND_WEATHER (default on with BB_WIND=1; 0: constant), BB_WIND_SPEED (set: pins the speed
# and turns the weather off, as every test and clip needs it repeatable), BB_WIND_WEATHER_RATE (x1;
# 0.05-100), BB_WIND_WEATHER_AT (weather clock at wind time 0, s; -1e6..1e6; 0). The wind's time
# starts at the first frame with BB_WIND=1, so at a clip's start the clock is AT + RATE x (wind time
# then): the proof line prints the clock.
#
# Files (no host shader, CMake or build.sh: every shader build is byte-identical): gpu/shim/
# bbport_wind.h (the weather, Params/Snapshot fields, Advance, GustOf/GustAtSnap/WindAt, WeatherWindow,
# WeatherText), bbport_wind_sway.h (3 gust-table lines read GustOf), bbport_wind_hang.h (Push::Extend
# reads GustOf and keeps its grid while the speed moves), cloud_shadow_params.h (State::Advance's wind
# speed and cover shift, Velocity, MakePush's edges), vk_cloud_shadow.h/.cpp (OnFrameEnd's two
# arguments), vk_rasterizer_effects.cpp (the knobs, the once-line, the proof line, the cloud hook),
# tests/test_wind.cpp (block s), tests/test_wind_hang.cpp, tests/test_cloud_shadows.cpp, README.md.
#
# Off (BB_WIND unset): WindOnFrameEnd returns before any new line; the cloud shadows get speed -1 and
# shift 0 (their Velocity() is knobs.Velocity(), the edges x - 0.0f). Weather off with the wind on
# (BB_WIND_WEATHER=0 / BB_WIND_SPEED): Advance takes p.speed and Gust exactly as r116, GustOf is Gust,
# the hang follower's `same` test is r112's; the new Snapshot fields are weather_on false, 0. Cost
# on: a Noise1 per Advance (speed), GustWeather instead of Gust (3 Noise1), the sway tables 2 more
# Noise1 per sample (GustSamples a view a frame), the hang grid the same per new sample: well under
# 0.01 ms a frame on the CPU; no GPU cost, no memory. The hang follower no longer restarts when the
# speed (its time constants) moves.
#
# Use: python -I -X utf8 r116b_wind-weather.py check | apply | revert
# Root: R116B_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up
# in r116b_backup next to this script; revert takes out exactly what apply put in. check also runs a
# Python copy of the weather against the numbers tests/test_wind.cpp asserts.
import math, os, re, sys

ROOT = os.environ.get("R116B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r116b_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
W = "engine/gpu/shim/bbport_wind.h"
SW = "engine/gpu/shim/bbport_wind_sway.h"
HG = "engine/gpu/shim/bbport_wind_hang.h"
CP = RV + "cloud_shadow_params.h"
CH = RV + "vk_cloud_shadow.h"
CC = RV + "vk_cloud_shadow.cpp"
E = RV + "vk_rasterizer_effects.cpp"
T = "engine/tests/test_wind.cpp"
TH = "engine/tests/test_wind_hang.cpp"
TC = "engine/tests/test_cloud_shadows.cpp"
R = "README.md"
ORDER = (W, SW, HG, CP, CH, CC, E, T, TH, TC, R)

# ---------------------------------------------------------------------------------------------
# bbport_wind.h
# ---------------------------------------------------------------------------------------------
W_CONSTS = r'''/// bbport (r116b_wind-weather): the weather. One slow signal of the wind's world time sets the mean speed:
/// WeatherSpeed(clock) = WeatherMin + (WeatherMax - WeatherMin) u^4, u = (Noise1(clock / WeatherCell) + 1) / 2,
/// clock = Params::weather_at + Params::weather_rate x wind time. Over one noise period it is below CalmBelow
/// 56% of the time, below LightBelow 79%, below StrongFrom 96% (r116b's Python copy; tests/test_wind.cpp block
/// s). WeatherLine: the proof line's period (weather clock s). The gusts follow the level (0-1, the speed's
/// place in WeatherMin-WeatherMax): their strength is g x (GustGainMin + GustGainSpan x level) and their burst
/// threshold moves GustEdgeShift x (GustNeutral - level). The cloud cover moves CoverGain x (level -
/// CoverNeutral) (CoverShift: the cloud shadows' edges go that much lower).
inline constexpr double WeatherCell = 120.0; ///< s of weather clock per noise cell
inline constexpr float WeatherMin = 0.4f, WeatherMax = 3.9f; ///< m/s
inline constexpr float CalmBelow = 0.7f, LightBelow = 1.5f, StrongFrom = 3.0f; ///< m/s: the states
inline constexpr double WeatherRateMin = 0.05, WeatherRateMax = 100.0, WeatherAtLimit = 1.0e6;
inline constexpr double WeatherLine = 60.0; ///< s of weather clock between the proof lines
inline constexpr float GustGainMin = 0.3f, GustGainSpan = 1.0f, GustEdgeShift = 0.45f, GustNeutral = 0.35f;
inline constexpr float CoverGain = 0.06f, CoverNeutral = 0.3f;
static_assert(WeatherMin > 0.0f && WeatherMin < CalmBelow && CalmBelow < LightBelow && LightBelow < StrongFrom &&
                  StrongFrom < WeatherMax && WeatherMax <= MaxSpeed,
              "the weather's speeds sit inside 0-MaxSpeed");
'''

W_PARAM = r'''    bool weather = false;                   ///< r116b: the speed is the weather's (WeatherSpeed), not `speed`
    double weather_rate = 1.0;              ///< r116b: weather clock seconds per wind second (0.05-100)
    double weather_at = 0.0;                ///< r116b: the weather clock at wind time 0 (s)
'''

W_SAN = r'''    p.weather_rate = std::isfinite(p.weather_rate) ? std::clamp(p.weather_rate, WeatherRateMin, WeatherRateMax) : 1.0;
    p.weather_at = std::isfinite(p.weather_at) ? std::clamp(p.weather_at, -WeatherAtLimit, WeatherAtLimit) : 0.0;
'''

W_FUNCS = r'''// bbport (r116b_wind-weather): the weather and what follows it. All pure CPU functions of the wind's world
// time; see the constants above.

/// The weather's mean speed (m/s) at weather clock `clock` (s): WeatherMin-WeatherMax, continuous.
inline float WeatherSpeed(double clock) {
    const float u = std::clamp(0.5f * (Noise1(clock / WeatherCell) + 1.0f), 0.0f, 1.0f);
    const float u2 = u * u;
    return WeatherMin + (WeatherMax - WeatherMin) * (u2 * u2);
}

/// A speed's place between WeatherMin (0) and WeatherMax (1); 0 for a value that is not finite.
inline float WeatherLevel(float speed) {
    if (!std::isfinite(speed)) {
        return 0.0f;
    }
    return std::clamp((speed - WeatherMin) / (WeatherMax - WeatherMin), 0.0f, 1.0f);
}

/// The gust strength Gust gets at weather level `level` for BB_WIND_GUSTS g: g x (0.3 + level), 0-MaxGusts.
inline float GustStrength(float g, float level) {
    return std::clamp(g * (GustGainMin + GustGainSpan * level), 0.0f, MaxGusts);
}

/// Gust with the weather's level: stronger gusts, and bursts above a lower threshold (so more often),
/// when the weather is up; weaker and rarer when it is calm. Exactly 1 at g = 0; the clamp is Gust's.
inline float GustWeather(double t, float g, float level) {
    if (g == 0.0f) {
        return 1.0f;
    }
    const float shift = GustEdgeShift * (GustNeutral - level);
    const float slow = 0.4f * Noise1(t / SlowPeriod + 3.1);
    const float burst = 1.2f * Smoothstep(0.25f + shift, 0.75f + shift, Noise1(t / BurstPeriod + 17.3));
    return std::clamp(1.0f + GustStrength(g, level) * (slow + burst - GustCentre), GustMin, GustMax);
}

/// The cloud cover's shift at weather level `level`: positive means denser (the cloud shadows' edges
/// go that much lower); 0 at CoverNeutral.
inline float CoverShift(float level) {
    return CoverGain * (level - CoverNeutral);
}

/// The weather's states: calm below CalmBelow, light below LightBelow, strong from StrongFrom, between
/// them building (the speed is rising) or easing (falling).
enum class Sky : std::size_t { Calm, Light, Building, Easing, Strong };

inline const char* SkyName(Sky s) {
    return s == Sky::Calm       ? "calm"
           : s == Sky::Light    ? "light"
           : s == Sky::Building ? "building"
           : s == Sky::Easing   ? "easing"
                                : "strong";
}

/// The state at weather clock `clock`.
inline Sky SkyAt(double clock) {
    const float v = WeatherSpeed(clock);
    if (v < CalmBelow) {
        return Sky::Calm;
    }
    if (v < LightBelow) {
        return Sky::Light;
    }
    if (v >= StrongFrom) {
        return Sky::Strong;
    }
    return WeatherSpeed(clock + 2.0) >= WeatherSpeed(clock - 2.0) ? Sky::Building : Sky::Easing;
}

'''

W_ADV_OLD = '''        const float gust = Gust(snapshot.time, p.gusts);
        const float u = p.speed * gust;
'''
W_ADV_NEW = '''        // bbport (r116b_wind-weather): with the weather the mean speed is the weather's at this clock and
        // the gusts follow its level; without it p.speed and Gust, the same floats as before
        const float speed = p.weather ? WeatherSpeed(p.weather_at + p.weather_rate * snapshot.time) : p.speed;
        const float level = p.weather ? WeatherLevel(speed) : 0.0f;
        const float gust = p.weather ? GustWeather(snapshot.time, p.gusts, level) : Gust(snapshot.time, p.gusts);
        const float u = speed * gust;
'''
W_SPEED_OLD = "        snapshot.speed = p.speed;\n"
W_SPEED_NEW = "        snapshot.speed = speed; // bbport (r116b): the weather's, or p.speed\n"
W_CLOUD_OLD = "        snapshot.cloud_speed = CloudRatio * p.speed;\n"
W_CLOUD_NEW = '''        snapshot.cloud_speed = CloudRatio * speed;
        snapshot.weather_on = p.weather;
        snapshot.weather = level;
        snapshot.gust_strength = p.weather ? GustStrength(p.gusts, level) : p.gusts;
        snapshot.weather_rate = p.weather_rate;
        snapshot.weather_at = p.weather_at;
'''

W_SNAP = r'''    bool weather_on = false;      ///< r116b: the speed is the weather's
    float weather = 0.0f;         ///< r116b: the weather level, 0 (WeatherMin) to 1 (WeatherMax); 0 without the weather
    float gust_strength = 0.0f;   ///< r116b: the gust strength in use (Params::gusts, or GustStrength with the weather)
    double weather_rate = 1.0;    ///< r116b: Params::weather_rate after Sanitize
    double weather_at = 0.0;      ///< r116b: Params::weather_at after Sanitize
'''

W_GUSTOF = r'''/// bbport (r116b_wind-weather): the weather clock at wind time t (s): the clock the weather runs on with
/// the weather, t itself without it.
inline double ClockOf(const Snapshot& s, double t) {
    return s.weather_on ? s.weather_at + s.weather_rate * t : t;
}

/// The ONE gust factor at wind time t (s) for BB_WIND_GUSTS `gusts`: Gust(t, gusts) without the weather,
/// with it GustWeather at the weather's level of THAT time. The plant sway's and the hanging things' gust
/// tables and WindAt (with s.gusts) read it.
inline float GustOf(const Snapshot& s, double t, float gusts) {
    if (!s.weather_on) {
        return Gust(t, gusts);
    }
    return GustWeather(t, gusts, WeatherLevel(WeatherSpeed(s.weather_at + s.weather_rate * t)));
}

/// GustAt for a snapshot: the gust at world point (x, z) for a front travelling with the wind, taken at
/// the time the front passed the origin (as GustAt, so the same floats without the weather).
inline float GustAtSnap(const Snapshot& s, float x, float z) {
    const float floored = std::isfinite(s.speed) ? std::max(s.speed, 0.1f) : 0.1f;
    return GustOf(s, s.time - double(x * s.dir_x + z * s.dir_z) / double(floored), s.gusts);
}

'''

W_WIND_OLD = "    const float u = s.speed * GustAt(s.time, s.gusts, x, z, s.dir_x, s.dir_z, s.speed);\n"
W_WIND_NEW = "    const float u = s.speed * GustAtSnap(s, x, z); // bbport (r116b): the weather's gust\n"

W_TEXT = r'''/// bbport (r116b_wind-weather): the speeds seen since the last proof line: the sum and count (the mean)
/// and the lowest and highest.
struct WeatherWindow {
    double sum = 0.0;
    std::uint32_t count = 0;
    float lowest = 0.0f, highest = 0.0f;

    void Add(float v) {
        if (!std::isfinite(v)) {
            return;
        }
        lowest = count == 0 ? v : std::min(lowest, v);
        highest = count == 0 ? v : std::max(highest, v);
        sum += double(v);
        ++count;
    }
    float Mean() const {
        return count != 0 ? float(sum / double(count)) : 0.0f;
    }
};

/// The weather's proof line (under 300 characters): the state, the clock, the speed now with its mean and
/// range since the last line, the gust strength, the clouds' speed (`clouds`, m/s: what the cloud layer
/// moves at) and the cover shift. Empties `w`. Returns snprintf's result for `out`.
inline int WeatherText(const Snapshot& s, WeatherWindow& w, float clouds, char* out, std::size_t size) {
    const float mean = w.count != 0 ? w.Mean() : s.speed;
    const float lo = w.count != 0 ? w.lowest : s.speed;
    const float hi = w.count != 0 ? w.highest : s.speed;
    w = WeatherWindow{};
    if (!s.weather_on) {
        return std::snprintf(out, size,
                             "Wind (r116b): weather off (constant speed), speed now %.2f m/s (mean %.2f, range "
                             "%.2f-%.2f), gust strength %.2f (x%.2f now), clouds %.2f m/s",
                             double(s.speed), double(mean), double(lo), double(hi), double(s.gust_strength),
                             double(s.gust), double(clouds));
    }
    const double clock = ClockOf(s, s.time);
    return std::snprintf(out, size,
                         "Wind (r116b): weather %s (clock %.0f s, x%.2f), speed now %.2f m/s (mean %.2f, range "
                         "%.2f-%.2f), gust strength %.2f (x%.2f now), clouds %.2f m/s, cover %+.3f",
                         SkyName(SkyAt(clock)), clock, s.weather_rate, double(s.speed), double(mean), double(lo),
                         double(hi), double(s.gust_strength), double(s.gust), double(clouds),
                         double(CoverShift(s.weather)));
}

'''

# ---------------------------------------------------------------------------------------------
# bbport_wind_sway.h
# ---------------------------------------------------------------------------------------------
SW_VIEW_OLD = "        out[TableAt + i] = BbWind::Gust(t, gusts);\n"
SW_VIEW_NEW = "        out[TableAt + i] = BbWind::GustOf(s, t, gusts); // bbport (r116b): the weather's gusts\n"
SW_RIP_OLD = '''        // as FillView's table, the time taken from `ripple`
        const double t = ripple.GustTime() + (double(i) - GustMid) * GustStep;
        view[TableAt + i] = BbWind::Gust(t, gusts);
'''
SW_RIP_NEW = '''        // as FillView's table, the time taken from `ripple`
        const double t = ripple.GustTime() + (double(i) - GustMid) * GustStep;
        view[TableAt + i] = BbWind::GustOf(s, t, gusts); // bbport (r116b)
'''
SW_LEAN_OLD = '''    view[WindD + 3] = float(two_pi * double(c.cross_hz) / wave);
    for (std::uint32_t i = 0; i < GustSamples; ++i) {
        const double t = ripple.GustTime() + (double(i) - GustMid) * GustStep;
        view[TableAt + i] = BbWind::Gust(t, gusts);
'''
SW_LEAN_NEW = '''    view[WindD + 3] = float(two_pi * double(c.cross_hz) / wave);
    for (std::uint32_t i = 0; i < GustSamples; ++i) {
        const double t = ripple.GustTime() + (double(i) - GustMid) * GustStep;
        view[TableAt + i] = BbWind::GustOf(s, t, gusts); // bbport (r116b)
'''

# ---------------------------------------------------------------------------------------------
# bbport_wind_hang.h
# ---------------------------------------------------------------------------------------------
HG_CALL_OLD = "        Extend(k_first, k_last, gusts, times);\n"
HG_CALL_NEW = "        Extend(k_first, k_last, gusts, times, s); // bbport (r116b): the weather's gusts and speed\n"
HG_SIG_OLD = '''    void Extend(std::int64_t k_first, std::int64_t k_last, float gusts, const Times& times) {
        const bool same = !grid.empty() && gusts == grid_gusts && times.rise == grid_times.rise &&
                          times.release == grid_times.release;
'''
HG_SIG_NEW = '''    void Extend(std::int64_t k_first, std::int64_t k_last, float gusts, const Times& times,
                const BbWind::Snapshot& s) {
        // bbport (r116b_wind-weather): with the weather the speed, so the times, change every frame: the
        // grid is kept and extended with the times of now (the samples it holds were followed at the
        // speed of their own time), not started again
        const bool same = !grid.empty() && gusts == grid_gusts &&
                          (s.weather_on || (times.rise == grid_times.rise && times.release == grid_times.release));
'''
HG_G0_OLD = "                grid.push_back(Drive(BbWind::Gust(double(k0) * PushStep, gusts)));\n"
HG_G0_NEW = "                grid.push_back(Drive(BbWind::GustOf(s, double(k0) * PushStep, gusts))); // bbport (r116b)\n"
HG_G1_OLD = "            const float x = Drive(BbWind::Gust(double(k) * PushStep, gusts));\n"
HG_G1_NEW = "            const float x = Drive(BbWind::GustOf(s, double(k) * PushStep, gusts)); // bbport (r116b)\n"

# ---------------------------------------------------------------------------------------------
# cloud_shadow_params.h
# ---------------------------------------------------------------------------------------------
CP_ADV_OLD = '''    void Advance(const Knobs& knobs, bool wind_on, float wind_deg, bool light_valid,
                 const std::array<float, 3>& light, double seconds) {
'''
CP_ADV_NEW = '''    /// bbport (r116b_wind-weather): `wind_speed` (m/s, the wind's mean speed this frame; below 0 or not
    /// finite: the knobs') and `cover_shift` (BbWind::CoverShift: the edges go that much lower) come
    /// from the wind's weather; with the wind off they are ignored.
    void Advance(const Knobs& knobs, bool wind_on, float wind_deg, bool light_valid,
                 const std::array<float, 3>& light, double seconds, float wind_speed = -1.0f,
                 float cover_shift = 0.0f) {
'''
CP_DRIFT_OLD = '''        drift.Advance(true, time, DriftVelocity(direction, knobs.Velocity(), knobs.scale),
                      knobs.scale);
'''
CP_DRIFT_NEW = '''        // bbport (r116b_wind-weather): the clouds' speed is the ratio times the wind's mean speed of this frame
        const bool weather = wind_on && std::isfinite(wind_speed) && wind_speed >= 0.0f;
        speed_now = weather ? wind_speed * (knobs.show ? ShowSpeedRatio : SpeedRatio) : knobs.Velocity();
        cover_shift_now = weather && std::isfinite(cover_shift) ? cover_shift : 0.0f;
        drift.Advance(true, time, DriftVelocity(direction, speed_now, knobs.scale), knobs.scale);
'''
CP_ACC = '''    /// bbport (r116b_wind-weather): m/s the clouds move at now (the knobs' before the first Advance)
    float Velocity(const Knobs& knobs) const {
        return speed_now >= 0.0f ? speed_now : knobs.Velocity();
    }
    /// The edges' shift of the cloud cover now (0: none)
    float CoverShift() const {
        return cover_shift_now;
    }
'''
CP_MEM = '''    float speed_now = -1.0f;       ///< r116b: Advance's speed (below 0: none yet)
    float cover_shift_now = 0.0f;  ///< r116b: Advance's cover shift
'''
CP_LOW_OLD = "    push.off2 = {c2[0], c2[1], c2[2], knobs.LowEdge()};\n"
CP_LOW_NEW = "    push.off2 = {c2[0], c2[1], c2[2], knobs.LowEdge() - state.CoverShift()}; // bbport (r116b)\n"
CP_HIGH_OLD = "    push.high = knobs.HighEdge();\n"
CP_HIGH_NEW = "    push.high = knobs.HighEdge() - state.CoverShift(); // bbport (r116b)\n"

# ---------------------------------------------------------------------------------------------
# vk_cloud_shadow.h / .cpp
# ---------------------------------------------------------------------------------------------
CH_SIG_OLD = "    void OnFrameEnd(bool wind_on, float wind_deg);\n"
CH_SIG_NEW = '''    /// bbport (r116b_wind-weather): `wind_speed` (m/s) and `cover_shift` are the wind's weather this frame
    /// (CloudShadows::State::Advance); the defaults leave the knobs' speed and the edges.
    void OnFrameEnd(bool wind_on, float wind_deg, float wind_speed = -1.0f, float cover_shift = 0.0f);
'''
CH_VEL_OLD = '''    float Velocity() const {
        return knobs.Velocity();
    }
'''
CH_VEL_NEW = '''    float Velocity() const {
        return state.Velocity(knobs); // bbport (r116b): follows the wind's weather
    }
'''
CC_SIG_OLD = "void CloudShadow::OnFrameEnd(bool wind_on, float wind_deg) {\n"
CC_SIG_NEW = "void CloudShadow::OnFrameEnd(bool wind_on, float wind_deg, float wind_speed, float cover_shift) {\n"
CC_ADV_OLD = "    state.Advance(knobs, wind_on, wind_deg, light_valid, light, seconds);\n"
CC_ADV_NEW = "    state.Advance(knobs, wind_on, wind_deg, light_valid, light, seconds, wind_speed, cover_shift);\n"

# ---------------------------------------------------------------------------------------------
# vk_rasterizer_effects.cpp
# ---------------------------------------------------------------------------------------------
E_PRE = '''        // bbport (r116b_wind-weather): the weather is on with the wind unless BB_WIND_WEATHER=0 or
        // BB_WIND_SPEED is set (a pinned speed for repeatable tests and clips)
        const char* weather_env = std::getenv("BB_WIND_WEATHER");
        const char* speed_env = std::getenv("BB_WIND_SPEED");
        const bool weather_wanted = !(weather_env != nullptr && weather_env[0] == '0') &&
                                    !(speed_env != nullptr && speed_env[0] != 0);
'''
E_FIELDS = '''            .weather = on != nullptr && on[0] == '1' && weather_wanted,
            .weather_rate = double(number("BB_WIND_WEATHER_RATE", 1.0f)),
            .weather_at = double(number("BB_WIND_WEATHER_AT", 0.0f)),
'''
E_ONCE = '''            if (p.weather) {
                BbReport::Printf("Wind (r116b, BB_WIND_WEATHER=1): the speed is the weather's, %.1f-%.1f m/s: "
                                 "mostly calm or light, now and then in-between (2-2.5), rarely strong; a new "
                                 "state about every %.0f s, clock x%.2f from %.0f s; gusts and the clouds "
                                 "follow; BB_WIND_SPEED or BB_WIND_WEATHER=0 pins it\\n",
                                 double(BbWind::WeatherMin), double(BbWind::WeatherMax),
                                 BbWind::WeatherCell, p.weather_rate, p.weather_at);
            } else {
                BbReport::Printf("Wind (r116b): weather off (BB_WIND_WEATHER=0 or BB_WIND_SPEED set): the speed "
                                 "stays %.2f m/s\\n", double(p.speed));
            }
'''
E_LINE = '''    // bbport (r116b_wind-weather): one line each WeatherLine of weather clock (a minute of weather; at
    // BB_WIND_WEATHER_RATE=20 every 3 s): the state, the speed now with its mean and range, the gust
    // strength, the clouds' speed
    static BbWind::WeatherWindow weather_window;
    weather_window.Add(s.speed);
    if (std::floor(BbWind::ClockOf(s, s.time) / BbWind::WeatherLine) !=
        std::floor(BbWind::ClockOf(s, before) / BbWind::WeatherLine)) {
        char weather[320];
        BbWind::WeatherText(s, weather_window, cloud_shadow ? cloud_shadow->Velocity() : s.cloud_speed, weather,
                            sizeof(weather));
        BbReport::Printf("%s\\n", weather);
    }
'''
E_CLOUD_OLD = "        cloud_shadow->OnFrameEnd(w.on, w.direction_deg);\n"
E_CLOUD_NEW = '''        // bbport (r116b_wind-weather): the clouds move at the weather's speed and their cover follows its level
        cloud_shadow->OnFrameEnd(w.on, w.direction_deg, w.weather_on ? w.speed : -1.0f,
                                 w.weather_on ? BbWind::CoverShift(w.weather) : 0.0f);
'''

# ---------------------------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------------------------
T_BLOCK = r'''    // s. r116b_wind-weather: the weather's range, steps and shares of time, the knobs that must do nothing,
    // continuity of the speed and the gust, the gusts' coupling, the clouds' speed, WindAt, the line.
    {
        const float qnan = std::numeric_limits<float>::quiet_NaN();
        // One noise period of weather (Period x WeatherCell s): the numbers r116b's Python copy prints
        // (calm 55.9%, light 22.8%, in-between 17.3%, strong 4.0%, 3.5 m/s and over 1.05%, top 3.84,
        // at most 0.088 m/s a second).
        const double span = Period * WeatherCell;
        std::size_t calm = 0, light = 0, band = 0, strong = 0, high = 0, total = 0;
        float lo = 1e9f, hi = 0.0f, step = 0.0f, prev = WeatherSpeed(0.0);
        for (double tw = 0.0; tw < span; tw += 1.0) {
            const float v = WeatherSpeed(tw);
            lo = std::min(lo, v);
            hi = std::max(hi, v);
            step = std::max(step, std::fabs(v - prev));
            prev = v;
            ++total;
            if (v < CalmBelow) {
                ++calm;
            } else if (v < LightBelow) {
                ++light;
            } else if (v < StrongFrom) {
                ++band;
            } else {
                ++strong;
            }
            high += v >= 3.5f ? 1 : 0;
        }
        const auto share = [&](std::size_t n) { return double(n) / double(total); };
        Expect(lo >= WeatherMin && hi <= WeatherMax && lo < 0.45f && hi > 3.6f,
               "the weather's speed stays within 0.4-3.9 m/s and reaches both ends over a period");
        Expect(step <= 0.15f, "the weather's speed changes at most 0.15 m/s each second");
        Expect(share(calm) > 0.50 && share(calm) < 0.62, "calm (below 0.7 m/s) about 56% of the time");
        Expect(share(light) > 0.18 && share(light) < 0.28, "light (0.7-1.5) about 23% of the time");
        Expect(share(band) > 0.12 && share(band) < 0.22, "in-between (1.5-3) about 17% of the time");
        Expect(share(strong) > 0.025 && share(strong) < 0.055, "strong (3 and over) about 4% of the time");
        Expect(share(calm) + share(light) > 0.74, "calm or light more than 74% of the time");
        Expect(share(high) > 0.003 && share(high) < 0.03, "3.5 m/s and over about 1% of the time");
        std::array<bool, 5> seen{};
        for (double tw = 0.0; tw < span; tw += 7.0) {
            seen[std::size_t(SkyAt(tw))] = true;
        }
        Expect(seen[0] && seen[1] && seen[2] && seen[3] && seen[4],
               "every state shows over a period: calm, light, building, easing, strong");
        Expect(std::strcmp(SkyName(Sky::Calm), "calm") == 0 && std::strcmp(SkyName(Sky::Light), "light") == 0 &&
                   std::strcmp(SkyName(Sky::Building), "building") == 0 &&
                   std::strcmp(SkyName(Sky::Easing), "easing") == 0 && std::strcmp(SkyName(Sky::Strong), "strong") == 0,
               "the states' names");
        Expect(WeatherLevel(WeatherMin) == 0.0f && WeatherLevel(WeatherMax) == 1.0f && WeatherLevel(qnan) == 0.0f &&
                   WeatherLevel(100.0f) == 1.0f,
               "WeatherLevel: 0 at the lowest speed, 1 at the highest, 0 for NaN");
        Expect(WeatherSpeed(std::numeric_limits<double>::quiet_NaN()) >= WeatherMin, "WeatherSpeed of NaN is a speed");

        // Sanitize.
        Expect(Sanitize({.on = true, .weather_rate = 1000.0}).weather_rate == WeatherRateMax &&
                   Sanitize({.on = true, .weather_rate = 0.0}).weather_rate == WeatherRateMin &&
                   Sanitize({.on = true, .weather_rate = double(qnan)}).weather_rate == 1.0 &&
                   Sanitize({.on = true, .weather_rate = 20.0}).weather_rate == 20.0,
               "Sanitize: the weather's rate 0.05-100, NaN is 1");
        Expect(Sanitize({.on = true, .weather_at = 1e9}).weather_at == WeatherAtLimit &&
                   Sanitize({.on = true, .weather_at = -1e9}).weather_at == -WeatherAtLimit &&
                   Sanitize({.on = true, .weather_at = double(qnan)}).weather_at == 0.0 &&
                   Sanitize({.on = true, .weather_at = 123.0}).weather_at == 123.0,
               "Sanitize: the weather's start is limited, NaN is 0");
        Expect(!Params{}.weather && Params{}.weather_rate == 1.0 && Params{}.weather_at == 0.0,
               "defaults: the weather is a knob of the environment, off in Params");

        // The weather off: the rate and the start do nothing (bit for bit r116's snapshots, 10 s).
        {
            Params inert = On;
            inert.weather_rate = 7.0;
            inert.weather_at = 99.0;
            State a, b;
            bool same_all = true;
            for (int i = 0; i < 600; ++i) {
                a.Advance(On, 1.0 / 60.0);
                b.Advance(inert, 1.0 / 60.0);
                const Snapshot sa = a.Get(), sb = b.Get();
                same_all = same_all && Same(sa, sb) && SameBits(sa.cloud_speed, sb.cloud_speed) &&
                           SameBits(sa.gust_strength, sb.gust_strength) && sa.speed == DefaultSpeed &&
                           !sa.weather_on && sa.weather == 0.0f && sa.gust_strength == On.gusts &&
                           ClockOf(sa, 10.0) == 10.0;
            }
            Expect(same_all, "weather off: the rate and the start change nothing; speed, gust strength and clock are r116's");
        }

        // The weather on: Snapshot::speed is the weather at the clock; the speed and the gust are continuous
        // between frames; the clouds' speed is CloudRatio x it and covers a wide range.
        Params wp = On;
        wp.weather = true;
        wp.weather_rate = 20.0;
        wp.weather_at = 500.0;
        State st;
        Snapshot sn{};
        float prev_speed = 0.0f, prev_gust = 1.0f, max_dv = 0.0f, max_dg = 0.0f, c_lo = 1e9f, c_hi = 0.0f;
        bool follows = true, cloud_ties = true, levels = true;
        for (int i = 0; i < 36000; ++i) { // 600 s at 60 Hz: 12000 s of weather
            st.Advance(wp, 1.0 / 60.0);
            sn = st.Get();
            follows = follows && sn.weather_on && sn.speed == WeatherSpeed(500.0 + 20.0 * sn.time) &&
                      sn.weather_rate == 20.0 && sn.weather_at == 500.0;
            cloud_ties = cloud_ties && sn.cloud_speed == CloudRatio * sn.speed;
            levels = levels && sn.weather == WeatherLevel(sn.speed) &&
                     sn.gust_strength == GustStrength(wp.gusts, sn.weather);
            c_lo = std::min(c_lo, sn.cloud_speed);
            c_hi = std::max(c_hi, sn.cloud_speed);
            if (i > 0) {
                max_dv = std::max(max_dv, std::fabs(sn.speed - prev_speed));
                max_dg = std::max(max_dg, std::fabs(sn.gust - prev_gust));
            }
            prev_speed = sn.speed;
            prev_gust = sn.gust;
        }
        Expect(follows, "weather on: Snapshot::speed is WeatherSpeed(start + rate x wind time) at every step");
        Expect(levels, "weather on: Snapshot::weather and gust_strength are the level's");
        Expect(max_dv <= 0.04f, "weather on, rate 20, 60 Hz: the speed moves at most 0.04 m/s a frame (no jumps)");
        Expect(max_dg <= 0.06f, "weather on: the gust factor moves at most 0.06 a frame (no jumps)");
        Expect(cloud_ties, "the clouds' speed is CloudRatio x the weather's speed at every step");
        Expect(c_hi > 2.0f * c_lo && c_lo >= CloudRatio * WeatherMin && c_hi <= CloudRatio * WeatherMax,
               "the clouds' speed follows the weather over a wide range (calm clouds drift slowly, strong ones fast)");

        // The gusts follow the level: weaker and rarer when calm, stronger and more often when up, the
        // mean near 1 (the rates are the Python copy's: level 0: mean 0.99, 2.6% above 1.15; level 0.35:
        // 1.00; level 1: mean 1.13, 39% above 1.15).
        const auto gust_run = [](float level) {
            double sum = 0.0;
            std::size_t over = 0, n = 0;
            for (double t = 0.0; t < 8000.0; t += 0.5) {
                const float g = GustWeather(t, 0.5f, level);
                sum += double(g);
                over += g > 1.15f ? 1 : 0;
                ++n;
            }
            return std::array<double, 2>{sum / double(n), double(over) / double(n)};
        };
        const auto g0 = gust_run(0.0f), gn = gust_run(GustNeutral), g1 = gust_run(1.0f);
        Expect(g0[1] < 0.08 && g1[1] > 0.25 && g1[1] > 3.0 * g0[1],
               "gusts: rare when calm (under 8% above x1.15), frequent when strong (over 25%)");
        Expect(g0[0] > 0.95 && g0[0] < 1.02 && gn[0] > 0.97 && gn[0] < 1.03 && g1[0] > 1.05 && g1[0] < 1.2,
               "gusts: the mean factor stays near 1 and rises with the level");
        Expect(GustWeather(12.3, 0.0f, 0.7f) == 1.0f && std::fabs(GustStrength(0.5f, 0.0f) - 0.15f) <= 1e-6f &&
                   std::fabs(GustStrength(0.5f, 1.0f) - 0.65f) <= 1e-6f && GustStrength(1.0f, 1.0f) == MaxGusts,
               "gust strength: 0 gusts is a steady wind, g x (0.3 + level), held to MaxGusts");
        Expect(std::fabs(CoverShift(CoverNeutral)) <= 1e-7f && CoverShift(1.0f) > 0.04f && CoverShift(0.0f) < 0.0f &&
                   CoverShift(1.0f) < 0.05f,
               "cover shift: 0 at the neutral level, denser (positive) when up, thinner when calm");

        // WindAt and GustOf with the weather: at the origin the snapshot's wind (bit for bit), elsewhere the
        // gust of the time the front passed the origin at the weather level of THAT time.
        Expect(SameBits(WindAt(sn, 0.0f, 0.0f), sn.wind), "weather on: WindAt at the origin is the snapshot's wind");
        const float ax = 12.0f * sn.dir_x, az = 12.0f * sn.dir_z;
        const double t_front = sn.time - double(ax * sn.dir_x + az * sn.dir_z) / double(std::max(sn.speed, 0.1f));
        const float want_gust = GustWeather(t_front, sn.gusts, WeatherLevel(WeatherSpeed(500.0 + 20.0 * t_front)));
        const auto along = WindAt(sn, ax, az);
        Expect(GustOf(sn, t_front, sn.gusts) == want_gust && std::fabs(std::hypot(along[0], along[2]) - sn.speed * want_gust) <= 1e-4f,
               "weather on: GustOf and WindAt take the weather level of the front's time");
        Snapshot constant = sn;
        constant.weather_on = false;
        Expect(GustOf(constant, 100.0, constant.gusts) == Gust(100.0, constant.gusts) &&
                   SameBits(WindAt(constant, 3.0f, -2.0f),
                            std::array<float, 3>{constant.speed * GustAt(constant.time, constant.gusts, 3.0f, -2.0f, constant.dir_x, constant.dir_z, constant.speed) * constant.dir_x,
                                                 0.0f,
                                                 constant.speed * GustAt(constant.time, constant.gusts, 3.0f, -2.0f, constant.dir_x, constant.dir_z, constant.speed) * constant.dir_z}),
               "weather off: GustOf is Gust and WindAt is r116's (GustAt)");
        Expect(ClockOf(sn, 10.0) == 500.0 + 20.0 * 10.0, "ClockOf: the start plus the rate x wind time");

        // The proof line.
        WeatherWindow ww;
        ww.Add(1.0f);
        ww.Add(2.0f);
        ww.Add(3.0f);
        ww.Add(qnan);
        char line[400];
        const int n = WeatherText(sn, ww, sn.cloud_speed, line, sizeof(line));
        Expect(n > 0 && n < 300, "the weather line is under 300 characters");
        Expect(std::strstr(line, "Wind (r116b): weather ") == line && std::strstr(line, "(clock ") != nullptr &&
                   std::strstr(line, ", speed now ") != nullptr && std::strstr(line, "(mean 2.00, range 1.00-3.00)") != nullptr &&
                   std::strstr(line, "gust strength ") != nullptr && std::strstr(line, ", clouds ") != nullptr &&
                   std::strstr(line, SkyName(SkyAt(ClockOf(sn, sn.time)))) != nullptr,
               "the weather line names the state, the clock, the speed with mean and range, the gusts and the clouds");
        WeatherText(sn, ww, sn.cloud_speed, line, sizeof(line));
        Expect(ww.count == 0 && std::strstr(line, "range ") != nullptr, "the weather line empties its window");
        State off_state;
        off_state.Advance(On, 0.05);
        WeatherWindow empty;
        WeatherText(off_state.Get(), empty, 6.0f, line, sizeof(line));
        Expect(std::strstr(line, "weather off") != nullptr && std::strstr(line, "clouds 6.00 m/s") != nullptr,
               "weather off: the line says so");
    }

'''

TH_BLOCK = r'''    // r116b_wind-weather: the weather moves the speed (and with it the follower's times) every frame: the
    // follower is kept, started once, and the tables do not jump between frames.
    {
        BbWind::Params p;
        p.on = true;
        p.weather = true;
        p.weather_rate = 30.0;
        p.weather_at = 1850.0;
        BbWind::State state;
        H::Push push;
        std::array<float, W::GustSamples> table{}, last{};
        float jump = 0.0f, most = 0.0f;
        for (int n = 0; n < 2400; ++n) { // 40 s at 60 Hz: 1200 s of weather through the 1990-2210 s spell
            state.Advance(p, 1.0 / 60.0);
            push.Fill(state.Get(), 3.0f, 4.0f, 0.5f, 1.0f, table.data());
            for (std::uint32_t i = 0; i < W::GustSamples; ++i) {
                most = std::max(most, table[i]);
                if (n > 0) {
                    jump = std::max(jump, std::fabs(table[i] - last[i]));
                }
            }
            last = table;
        }
        Expect(push.Restarts() == 1, "the weather: the follower started once, not at each change of the speed");
        Expect(jump < 0.05f, "the weather: the push tables move less than 5 cm between frames");
        Expect(most > 0.0f && most <= W::MaxAlong, "the weather: the push is positive and held");
    }

'''

TC_BLOCK = r'''    // m. (r116b) the wind's weather moves the clouds: their speed is the ratio times the wind's mean speed
    // of the frame, their cover shifts the edges; without the wind, or without a speed, nothing changes.
    {
        const Knobs k = MakeKnobs("1", nullptr, nullptr, nullptr);
        const std::array<float, 3> light{0.6f, 0.8f, 0.0f};
        const std::array<float, 12> rows{};
        State s;
        assert(Near(s.Velocity(k), k.Velocity(), 1e-6) && s.CoverShift() == 0.0f);
        s.Advance(k, true, 200.0f, false, light, 0.1);
        assert(Near(s.Velocity(k), k.Velocity(), 1e-6) && s.CoverShift() == 0.0f);
        s.Advance(k, true, 200.0f, false, light, 0.1, 0.8f, 0.01f);
        assert(Near(s.Velocity(k), 0.8 * SpeedRatio, 1e-5) && s.CoverShift() == 0.01f);
        const Push calm = MakePush(rows, s, k, light, 0u, 0.0f);
        assert(Near(calm.off2[3], Low - 0.01, 1e-6) && Near(calm.high, High - 0.01, 1e-6));
        s.Advance(k, true, 200.0f, false, light, 0.1, 3.2f, -0.02f);
        assert(Near(s.Velocity(k), 3.2 * SpeedRatio, 1e-5) && s.CoverShift() == -0.02f);
        s.Advance(k, true, 200.0f, false, light, 0.1, -1.0f, 0.03f); // no speed: the knobs'; no weather: no shift
        assert(Near(s.Velocity(k), k.Velocity(), 1e-6) && s.CoverShift() == 0.0f);
        State off;
        off.Advance(k, false, 200.0f, false, light, 0.1, 3.0f, 0.03f); // wind off: both ignored
        assert(Near(off.Velocity(k), k.Velocity(), 1e-6) && off.CoverShift() == 0.0f);
        const Push plain_push = MakePush(rows, off, k, light, 0u, 0.0f);
        assert(plain_push.off2[3] == Low && plain_push.high == High);
        const Knobs show = MakeKnobs(nullptr, nullptr, "1", nullptr);
        State sh;
        sh.Advance(show, true, 200.0f, false, light, 0.1, 2.0f);
        assert(Near(sh.Velocity(show), 2.0 * ShowSpeedRatio, 1e-5));
        // the weather's speed range gives the clouds 1.6 to 15.6 m/s (4 x 0.4 to 4 x 3.9)
        assert(Near(BbWind::CloudRatio * BbWind::WeatherMin, 1.6, 1e-6) && Near(BbWind::CloudRatio * BbWind::WeatherMax, 15.6, 1e-5));
    }
'''

# ---------------------------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------------------------
README_SPEED_OLD = "| `BB_WIND_SPEED` | Mean speed, 0 to 4 m/s (the fog patches"
README_SPEED_NEW = ("| `BB_WIND_SPEED` | Mean speed, 0 to 4 m/s. Set, it pins the speed and turns the weather (`BB_WIND_WEATHER`, r116b) off: tests and "
                    "clips repeat); unset, the weather sets it (the fog patches")
README_ROWS = (
    "| `BB_WIND_WEATHER` | The wind's strength changes with a slow weather (r116b), on with `BB_WIND=1` unless this is "
    "`0` or `BB_WIND_SPEED` is set. One signal of the wind's own time (the clock the heading's wander uses, the same for "
    "every follower in a frame, continuous) sets the mean speed between 0.4 and 3.9 m/s: calm (under 0.7) 56% of the "
    "time, light (0.7-1.5) 23%, in-between (1.5-3, building over a minute or two to about 2-2.5 and easing again) 17%, "
    "strong (3 and over) 4%, a new state about every 2 minutes. The gusts follow it (rare and weak when calm, frequent "
    "and strong when up), the clouds move at 4 times its speed (the cloud shadows and the cloud layer) and, with "
    "`BB_CLOUD_SHADOWS`, their cover follows it (denser when up). The plant lean, hanging things, fog drift and banks, "
    "particles, sparks, haze, caustics and the shelter all read the one snapshot. A `Wind (r116b):` line each "
    "weather minute says the state, the speed now with mean and range, the gust strength and the clouds' speed | `1` |\n"
    "| `BB_WIND_WEATHER_RATE` | Weather seconds per real second (r116b), 0.05 to 100: `1` is real time, `20` makes a "
    "calm-to-strong cycle fit a short clip. The proof line then comes every `60 / rate` s | `1` |\n"
    "| `BB_WIND_WEATHER_AT` | The weather clock, in seconds, at the wind's time 0 (the first frame with `BB_WIND=1`; "
    "r116b), -1000000 to 1000000. The clock at a moment is this plus the rate times the wind time, and the "
    "`Wind (r116b):` line prints it (`clock`); the weather repeats every 30720 clock seconds | `0` |\n"
)

# ---------------------------------------------------------------------------------------------
# The edit lists (as r116's: after / before / afterblock / rep).
# ---------------------------------------------------------------------------------------------
EDITS = {
    W: [
        ("after", "inline constexpr float MaxSpeed = 4.0f, MaxGusts = 1.0f, MaxContrast = 2.0f;", W_CONSTS),
        ("after", "float wander = Wander;", W_PARAM),
        ("after", "p.wander = std::clamp(FiniteOr(p.wander, Wander), 0.0f, MaxWander);", W_SAN),
        ("before", "/// The unit vector (x, z) the wind blows toward at deg: (cos, sin).", W_FUNCS),
        ("rep", W_ADV_OLD, W_ADV_NEW),
        ("rep", W_SPEED_OLD, W_SPEED_NEW),
        ("rep", W_CLOUD_OLD, W_CLOUD_NEW),
        ("after", "float cloud_speed = 0.0f;", W_SNAP),
        ("before", "/// The wind (m/s) at world point (x, z): speed x GustAt", W_GUSTOF),
        ("rep", W_WIND_OLD, W_WIND_NEW),
        ("before", "} // namespace BbWind", W_TEXT),
    ],
    SW: [
        ("rep", SW_VIEW_OLD, SW_VIEW_NEW),
        ("rep", SW_RIP_OLD, SW_RIP_NEW),
        ("rep", SW_LEAN_OLD, SW_LEAN_NEW),
    ],
    HG: [
        ("rep", HG_CALL_OLD, HG_CALL_NEW),
        ("rep", HG_SIG_OLD, HG_SIG_NEW),
        ("rep", HG_G0_OLD, HG_G0_NEW),
        ("rep", HG_G1_OLD, HG_G1_NEW),
    ],
    CP: [
        ("rep", CP_ADV_OLD, CP_ADV_NEW),
        ("rep", CP_DRIFT_OLD, CP_DRIFT_NEW),
        ("before", "    const VolumetricFogNoise::Drift& Offsets() const {", CP_ACC),
        ("after", "bool auto_known = false;", CP_MEM),
        ("rep", CP_LOW_OLD, CP_LOW_NEW),
        ("rep", CP_HIGH_OLD, CP_HIGH_NEW),
    ],
    CH: [
        ("rep", CH_SIG_OLD, CH_SIG_NEW),
        ("rep", CH_VEL_OLD, CH_VEL_NEW),
    ],
    CC: [
        ("rep", CC_SIG_OLD, CC_SIG_NEW),
        ("rep", CC_ADV_OLD, CC_ADV_NEW),
    ],
    E: [
        ("after", 'const char* on = std::getenv("BB_WIND");', E_PRE),
        ("after", '.wander = number("BB_WIND_WANDER", BbWind::Wander),', E_FIELDS),
        ("after", "double(p.direction_deg), double(p.wander), double(BbWind::CloudRatio));", E_ONCE),
        ("before", "if (show && std::floor(s.time / 2.0) != std::floor(before / 2.0)) {", E_LINE),
        ("rep", E_CLOUD_OLD, E_CLOUD_NEW),
    ],
    T: [("before", "if (failures) {", T_BLOCK)],
    TH: [("before", "if (failures != 0) {", TH_BLOCK)],
    TC: [("before", 'std::puts("cloud shadows: ok");', TC_BLOCK)],
    R: [
        ("rep", README_SPEED_OLD, README_SPEED_NEW),
        ("after", "| `BB_WIND_WANDER` |", README_ROWS),
    ],
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
        if kind == "after":
            out.append(("ins", line_of(cur, a, path), "", b))
        elif kind == "before":
            out.append(("ins", line_of(cur, a, path), b, ""))
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


# ---------------------------------------------------------------------------------------------
# The Python copy of the weather (the numbers tests/test_wind.cpp block s asserts)
# ---------------------------------------------------------------------------------------------
M32 = 0xFFFFFFFF


def hash1(i):
    state = ((i & 255) * 747796405 + 2891336453) & M32
    word = (((state >> ((state >> 28) + 4)) ^ state) * 277803737) & M32
    return ((word >> 22) ^ word) & M32


def noise1(x):
    whole = math.floor(x)
    u = x - whole
    u = u * u * u * (u * (u * 6.0 - 15.0) + 10.0)
    i = int(math.fmod(whole, 256.0))
    a = 2.0 * ((hash1(i) >> 8) * (1.0 / 16777216.0)) - 1.0
    b = 2.0 * ((hash1(i + 1) >> 8) * (1.0 / 16777216.0)) - 1.0
    return a + (b - a) * u


CELL, VMIN, VMAX = 120.0, 0.4, 3.9


def weather_speed(clock):
    u = min(max(0.5 * (noise1(clock / CELL) + 1.0), 0.0), 1.0)
    return VMIN + (VMAX - VMIN) * u ** 4


def smoothstep(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def gust_weather(t, g, level):
    if g == 0:
        return 1.0
    ge = min(max(g * (0.3 + 1.0 * level), 0.0), 1.0)
    shift = 0.45 * (0.35 - level)
    slow = 0.4 * noise1(t / 11.0 + 3.1)
    burst = 1.2 * smoothstep(0.25 + shift, 0.75 + shift, noise1(t / 4.3 + 17.3))
    return min(max(1.0 + ge * (slow + burst - 0.25), 0.3), 2.0)


def model_numbers():
    span = int(256 * CELL)
    vs = [weather_speed(float(t)) for t in range(span)]
    n = len(vs)
    calm = sum(1 for v in vs if v < 0.7) / n
    light = sum(1 for v in vs if 0.7 <= v < 1.5) / n
    band = sum(1 for v in vs if 1.5 <= v < 3.0) / n
    strong = sum(1 for v in vs if v >= 3.0) / n
    high = sum(1 for v in vs if v >= 3.5) / n
    step = max(abs(vs[i + 1] - vs[i]) for i in range(n - 1))
    gusts = {}
    for level in (0.0, 0.35, 1.0):
        gs = [gust_weather(k * 0.5, 0.5, level) for k in range(16000)]
        gusts[level] = (sum(gs) / len(gs), sum(1 for g in gs if g > 1.15) / len(gs))
    return dict(calm=calm, light=light, band=band, strong=strong, high=high, step=step, lo=min(vs), hi=max(vs),
                gusts=gusts)


def model_check():
    m = model_numbers()
    ok = (0.50 < m["calm"] < 0.62 and 0.18 < m["light"] < 0.28 and 0.12 < m["band"] < 0.22 and
          0.025 < m["strong"] < 0.055 and m["calm"] + m["light"] > 0.74 and 0.003 < m["high"] < 0.03 and
          m["step"] <= 0.15 and m["lo"] < 0.45 and m["hi"] > 3.6 and m["hi"] <= 3.9)
    g0, gn, g1 = m["gusts"][0.0], m["gusts"][0.35], m["gusts"][1.0]
    ok = ok and g0[1] < 0.08 and g1[1] > 0.25 and g1[1] > 3.0 * g0[1] and 0.95 < g0[0] < 1.02 and \
        0.97 < gn[0] < 1.03 and 1.05 < g1[0] < 1.2
    if not ok:
        raise SystemExit("model check: the Python copy of the weather does not meet the test's numbers: %r" % (m,))
    return m


def const(text, name):
    m = re.search(r"inline constexpr (?:double|float) %s = ([0-9.e+-]+)f?;" % name, text)
    if not m:
        raise SystemExit("text check: %s not found" % name)
    return float(m.group(1))


def text_checks(texts):
    """The ties a compiler cannot check."""
    w = texts[W]
    if const(w, "WeatherCell") != 120.0 or             "inline constexpr float CalmBelow = 0.7f, LightBelow = 1.5f, StrongFrom = 3.0f;" not in w:
        raise SystemExit("text check: the weather's constants are not the model's")
    if "inline constexpr float WeatherMin = 0.4f, WeatherMax = 3.9f;" not in w or \
            "GustGainMin = 0.3f, GustGainSpan = 1.0f, GustEdgeShift = 0.45f, GustNeutral = 0.35f;" not in w or \
            "CoverGain = 0.06f, CoverNeutral = 0.3f;" not in w or \
            "return WeatherMin + (WeatherMax - WeatherMin) * (u2 * u2);" not in w:
        raise SystemExit("text check: the weather's constants or formula are not the model's")
    a, b, c = w.find("class State {"), w.find("inline float GustOf("), w.rfind("} // namespace BbWind")
    f = w.find("inline float WeatherSpeed(")
    if not (0 <= f < a < b < c) or w.count("inline float GustOf(") != 1 or w.count("struct WeatherWindow {") != 1:
        raise SystemExit("text check: the r116b pieces are out of order in bbport_wind.h")
    # the weather's pieces must be defined before Advance uses them and the Snapshot before GustOf
    if not (w.find("struct Snapshot {") < b):
        raise SystemExit("text check: GustOf must follow Snapshot")
    # every Gust table of the sway and the hang follower reads GustOf, none reads Gust
    for path in (SW, HG):
        t = texts[path]
        if "BbWind::Gust(" in t:
            raise SystemExit("text check: %s still calls BbWind::Gust" % path)
    if texts[SW].count("BbWind::GustOf(s, t, gusts)") != 3 or texts[HG].count("BbWind::GustOf(s, double(k") != 2:
        raise SystemExit("text check: the sway has 3 and the hang follower 2 reads of GustOf")
    for want in ("push.off2 = {c2[0], c2[1], c2[2], knobs.LowEdge() - state.CoverShift()};",
                 "push.high = knobs.HighEdge() - state.CoverShift();"):
        if want not in texts[CP]:
            raise SystemExit("text check: %s lacks %r" % (CP, want))
    if texts[CH].count("state.Velocity(knobs)") != 1 or "return knobs.Velocity();" in texts[CH]:
        raise SystemExit("text check: the cloud shadows' velocity getter does not follow the state")
    e = texts[E]
    for want in ('.weather_rate = double(number("BB_WIND_WEATHER_RATE", 1.0f)),',
                 '.weather_at = double(number("BB_WIND_WEATHER_AT", 0.0f)),',
                 "BbWind::WeatherText(s, weather_window,", "w.weather_on ? w.speed : -1.0f"):
        if e.count(want) != 1:
            raise SystemExit("text check: %s holds %r %d times" % (E, want, e.count(want)))
    # the README rows and the constants agree
    rows = [l for l in texts[R].split("\n") if l.startswith(("| `BB_WIND_WEATHER` |", "| `BB_WIND_WEATHER_RATE` |",
                                                            "| `BB_WIND_WEATHER_AT` |"))]
    if len(rows) != 3 or "0.4 and 3.9 m/s" not in rows[0] or "56%" not in rows[0] or "30720" not in rows[2] or \
            not rows[0].rstrip().endswith("| `1` |") or not rows[2].rstrip().endswith("| `0` |"):
        raise SystemExit("text check: README rows and the constants disagree")
    # nothing of this patch is a shader, a CMake file or a build script
    for p in ORDER:
        if p.endswith((".comp", ".glsl", ".vert", ".frag", "CMakeLists.txt", "build.sh")):
            raise SystemExit("text check: %s is a build input" % p)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R116B_ROOT)" % ROOT)
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
        m = model_check()
        note = ("model: calm %.1f%% light %.1f%% in-between %.1f%% strong %.1f%% (3.5+ %.2f%%), top %.2f, "
                "max step %.3f m/s per s; gusts level 0: mean %.3f above1.15 %.1f%%, level 1: mean %.3f above1.15 %.1f%%"
                % (100 * m["calm"], 100 * m["light"], 100 * m["band"], 100 * m["strong"], 100 * m["high"], m["hi"],
                   m["step"], m["gusts"][0.0][0], 100 * m["gusts"][0.0][1], m["gusts"][1.0][0], 100 * m["gusts"][1.0][1]))
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks and the model's numbers pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files, %d edits; text checks on the result and the model pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        print(note)
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        model_check()
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r116btmp"
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
        tmp = full + ".r116btmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
