// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r96_lamp-flicker-colour): flame lamps flicker. The strengths (bbport r109a), 0 to 1, are
// taken at every frame end for the next frame (Update): for lamps the game keeps steady the
// setting graphics_lamp_flicker_strength (DefaultSteady 1), or BB_LAMP_FLICKER when it is set; for
// lamps the game changes itself graphics_lamp_flicker_on_game_strength (DefaultOnGame 0: left
// alone), or BB_LAMP_FLICKER_ON_GAME when it is set. The variables are read once; set means not
// empty; a text that is not a number above 0 is 0. Both 0: off, and nothing here runs: the
// rasterizer tests On() (one relaxed atomic load) before every call.
//
// Where: the game lights its lamps in light draws whose pixel stage reads the lamps' records
// (16 words each: view space position, 1 / reach squared, colour in words 4 to 6) from its buffer
// 1, once for every screen tile a lamp reaches. The rasterizer hands each such draw's records to
// Tracker::PatchDraw after the draw's buffers are bound; when a lamp of the draw flickers, the
// draw's buffer 1 is bound to a copy with that lamp's colour scaled (vk_rasterizer_effects.cpp,
// LampFlickerBind; the bytes come from guest memory, the constant ring is never read), and the
// same patched records go to the ray traced lamp shadow pass
// (PointShadow::OnLightDraw, which weighs each lamp by the luminance of the colour it reads) and
// to the lamp fog (VolumetricLight::AddPointLights). Nothing else of the record changes.
//
// Which lamps: a record whose colour is flame-coloured (Flame: red the strongest, green between
// 0.15 and 0.97 of red, blue at most 0.8 of red, reach at most MaxReach) and whose colour and
// reach the game has kept the same, each word up to a relative ChangeRel, for SteadySeconds. A
// lamp is followed from frame to frame by its place in the world (within MatchReach of where it
// was, reach within 35%), so a carried lamp keeps its own flicker. The game flickers some lamps
// itself: the hunter's lantern (its luminance went between 0.79 and 1.05 over the 600-frame lamp
// lines of 2026-11-15, while the street lamps beside it kept 1.08 and 0.68 in every line); such a
// lamp changes its colour (a torch might change its reach instead) from one frame to the next and
// is left alone, so no flicker is doubled. A lamp that starts to change while it flickers loses
// the flicker within RampOut seconds; one that has been steady for SteadySeconds gets it over
// RampIn seconds (no pop when a lamp appears, nor when the camera cuts).
// With the on-game strength above 0 (r109a) a lamp the game changes (its colour or reach moved
// after it was first seen, within the last SteadySeconds) gets a flicker of its own on top of the
// game's: its share game_amount fades in over RampIn while the game changes it and out over
// RampOut once the game has kept it steady for SteadySeconds, when the steady share (amount)
// fades in as for any steady lamp. At on-game strength 0 game_amount stays 0 and such a lamp is
// left alone: its records stay as the game made them.
//
// How: the light is multiplied by f = 1 + (A(steady) * amount + A(on_game) * game_amount) *
// Wave(seed, t), A(s) = Swing * s (times ShowScale with BB_LAMP_FLICKER_SHOW=1, at most MaxSwing;
// a lamp has only one share above 0 except while the other fades out), Wave a sum of three sines of
// 0.37, 1.13 and 2.71 Hz (each scaled 0.85 to 1.15 per lamp, phases per lamp), |Wave| <= 1, so f
// moves at most about 1.12 A / Swing per second (no strobing). The colour follows: channel c is
// multiplied by f^(1 + T k_c), k = (-0.6, 0.35, 1.1), T = BB_LAMP_FLICKER_TEMP (default 0.6; times
// 2 with SHOW, at most MaxTemp), then all three by the one number that gives the colour's
// luminance (0.299, 0.587, 0.114) exactly f times the game's: dimmer is redder, brighter is
// yellower, and the lamp's luminance, which point_shadow_ray.comp's lampWeight reads with the same
// weights, is f times the game's. The seed comes from the lamp's place (0.5 m cells) where it was
// first seen, so a lamp has the same flicker when it comes back.

#include <algorithm>
#include <array>
#include <atomic> // bbport (r109a)
#include <bit>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <mutex>
#include <vector>

#include "strength_knob.h" // bbport (r109a_strength-settings-engine)

namespace LampFlicker {

inline constexpr float DefaultTemp = 0.6f;  ///< BB_LAMP_FLICKER_TEMP when not set
/// bbport (r109a): the strengths' defaults and largest value (graphics_lamp_flicker_strength,
/// graphics_lamp_flicker_on_game_strength; tied to bbport_settings.h by static_asserts in
/// vk_rasterizer_effects.cpp)
inline constexpr float DefaultSteady = 1.0f, DefaultOnGame = 0.0f, MaxStrength = 1.0f;
inline constexpr float Swing = 0.14f;       ///< light between 1 - Swing and 1 + Swing at strength 1
inline constexpr float ShowScale = 3.0f;    ///< BB_LAMP_FLICKER_SHOW=1: swing times this
inline constexpr float MaxSwing = 0.6f;     ///< the swing never goes past this
inline constexpr float ShowTempScale = 2.0f; ///< BB_LAMP_FLICKER_SHOW=1: colour shift times this
inline constexpr float MaxTemp = 2.0f;
inline constexpr float MaxReach = 40.0f;      ///< m: a light reaching further is no flame
inline constexpr float MatchReach = 0.5f;     ///< m: the same lamp as the frame before
inline constexpr float MatchReachLog = 0.3f;  ///< |ln(reach / reach before)|: about 35%
inline constexpr double SteadySeconds = 1.0;  ///< colour, reach unchanged this long: it flickers
inline constexpr double RampIn = 1.0;         ///< s from no flicker to full
inline constexpr double RampOut = 0.2;        ///< s from full flicker to none
inline constexpr float ChangeRel = 2e-4f;     ///< colour or 1/reach^2 moved more: changed
inline constexpr float SeedCell = 0.5f;       ///< m
inline constexpr std::uint32_t MostLamps = 256; ///< lamps followed; more are left alone
inline constexpr std::uint32_t FrameSlots = 1024; ///< distinct records a frame; more left alone
/// A light draw's buffer 1 binding (records, and what the push offset skips) above this many
/// bytes is not copied, and the flicker is off for the rest of the session (12 records are 768).
inline constexpr std::uint64_t MostCopyBytes = 4096;
inline constexpr std::uint32_t LineFrames = 600;  ///< the periodic log line
inline constexpr std::uint32_t FirstLineFrames = 120; ///< its first one (short test runs see it)
inline constexpr std::uint32_t ShowFrames = 120;  ///< BB_LAMP_FLICKER_SHOW=1: the lamps line
inline constexpr std::array<float, 3> Luma{0.299f, 0.587f, 0.114f}; ///< lampWeight's weights
inline constexpr std::array<float, 3> TempK{-0.6f, 0.35f, 1.1f};
inline constexpr std::array<double, 3> WaveHz{0.37, 1.13, 2.71};
inline constexpr std::array<float, 3> WaveWeight{0.45f, 0.35f, 0.20f};
static_assert(WaveWeight[0] + WaveWeight[1] + WaveWeight[2] <= 1.0f + 1e-6f);

struct Params {
    bool on = false;
    float strength = 0.0f; ///< steady lamps, 0..1 (r109a: the frame's, Tracker::SetStrengths)
    float temp = 0.0f;     ///< BB_LAMP_FLICKER_TEMP, 0..1
    bool show = false;     ///< BB_LAMP_FLICKER_SHOW=1
    float on_game = 0.0f;  ///< r109a: lamps the game changes itself, 0..1; 0: left alone
    /// The swing and colour shift a pass uses.
    [[nodiscard]] float Amplitude() const {
        return Amplitude(strength);
    }
    /// r109a: the swing at strength `s`.
    [[nodiscard]] float Amplitude(float s) const {
        return std::min(MaxSwing, Swing * s * (show ? ShowScale : 1.0f));
    }
    [[nodiscard]] float Temp() const {
        return std::min(MaxTemp, temp * (show ? ShowTempScale : 1.0f));
    }
};

/// The knobs from their texts (null: not set). A number that does not parse, is not finite or is
/// not above 0 leaves the flicker off; the others are clamped to 0..1.
inline Params ParseParams(const char* flicker, const char* temp, const char* show) {
    const auto number = [](const char* text, float fallback) {
        if (text == nullptr || text[0] == 0) {
            return fallback;
        }
        char* end = nullptr;
        const float value = std::strtof(text, &end);
        return end != text && std::isfinite(value) ? value : fallback;
    };
    Params p;
    const float strength = number(flicker, 0.0f);
    p.on = strength > 0.0f;
    p.strength = p.on ? std::min(strength, 1.0f) : 0.0f;
    p.temp = std::clamp(number(temp, DefaultTemp), 0.0f, 1.0f);
    p.show = show != nullptr && show[0] == '1';
    return p;
}

/// The environment's knobs, read once: BB_LAMP_FLICKER_TEMP and BB_LAMP_FLICKER_SHOW (r109a: the
/// strengths a frame uses come from Update; `on` and `strength` here are BB_LAMP_FLICKER's own).
inline const Params& Knobs() {
    static const Params params = ParseParams(std::getenv("BB_LAMP_FLICKER"),
                                             std::getenv("BB_LAMP_FLICKER_TEMP"),
                                             std::getenv("BB_LAMP_FLICKER_SHOW"));
    return params;
}

/// bbport (r109a_strength-settings-engine): the two strengths of a frame and where each came from.
struct Strengths {
    StrengthKnob::Value steady, on_game;
    [[nodiscard]] bool On() const {
        return steady.value > 0.0f || on_game.value > 0.0f;
    }
};

/// The strengths from the variables as read once (`steady_env`: BB_LAMP_FLICKER, `on_game_env`:
/// BB_LAMP_FLICKER_ON_GAME; each wins when set) and the settings' values.
inline Strengths Resolve(const StrengthKnob::Env& steady_env, const StrengthKnob::Env& on_game_env,
                         float steady_setting, float on_game_setting) {
    return {StrengthKnob::Pick(steady_env, steady_setting, MaxStrength, DefaultSteady),
            StrengthKnob::Pick(on_game_env, on_game_setting, MaxStrength, DefaultOnGame)};
}

namespace Detail {
inline std::atomic<bool> on{false}; ///< Strengths::On() of the frame that runs
inline Strengths now{};             ///< written by Update, read by FrameEnd (the frame end only)
} // namespace Detail

/// Each frame end, before anything asks On() for the next frame: that frame's strengths, from the
/// settings' values (the caller loads them) unless a variable is set. Returns On().
inline bool Update(float steady_setting, float on_game_setting) {
    static const StrengthKnob::Env steady_env =
        StrengthKnob::ReadEnv(std::getenv("BB_LAMP_FLICKER"), MaxStrength);
    static const StrengthKnob::Env on_game_env =
        StrengthKnob::ReadEnv(std::getenv("BB_LAMP_FLICKER_ON_GAME"), MaxStrength);
    Detail::now = Resolve(steady_env, on_game_env, steady_setting, on_game_setting);
    const bool on = Detail::now.On();
    Detail::on.store(on, std::memory_order_relaxed);
    return on;
}

/// A strength above 0 this frame (one relaxed atomic load; false before the first frame end).
inline bool On() {
    return Detail::on.load(std::memory_order_relaxed);
}

inline std::uint32_t Hash(std::uint32_t x) {
    x ^= x >> 16;
    x *= 0x7FEB352Du;
    x ^= x >> 15;
    x *= 0x846CA68Bu;
    x ^= x >> 16;
    return x;
}

inline float Unit(std::uint32_t h) {
    return float(h >> 8) * (1.0f / 16777216.0f);
}

/// The flicker of the lamp `seed` at `seconds`: three sines, |Wave| <= 1, smooth.
inline float Wave(std::uint32_t seed, double seconds) {
    constexpr double Tau = 6.283185307179586;
    float sum = 0.0f;
    for (std::uint32_t i = 0; i < 3; ++i) {
        const std::uint32_t h = Hash(seed ^ (0x9E3779B9u * (i + 1u)));
        const double hz = WaveHz[i] * (0.85 + 0.3 * double(Unit(h)));
        const double phase = double(Unit(Hash(h))) + std::fmod(seconds * hz, 1.0);
        sum += WaveWeight[i] * float(std::sin(Tau * phase));
    }
    return sum;
}

/// The three channel gains for intensity factor `factor` and colour shift `temp`: their
/// luminance-weighted mean over `colour` is exactly `factor` (dimmer is redder).
inline std::array<float, 3> Gains(float factor, float temp, const std::array<float, 3>& colour) {
    const float f = std::max(factor, 0.05f);
    std::array<float, 3> g{};
    float lit = 0.0f, base = 0.0f;
    for (std::size_t i = 0; i < 3; ++i) {
        g[i] = std::pow(f, 1.0f + temp * TempK[i]);
        lit += Luma[i] * colour[i] * g[i];
        base += Luma[i] * colour[i];
    }
    if (!(lit > 0.0f) || !(base > 0.0f) || !std::isfinite(lit)) {
        return {f, f, f};
    }
    const float scale = f * base / lit;
    for (float& v : g) {
        v *= scale;
    }
    return g;
}

/// A flame's colour: red the strongest, some green, little blue; a reach of at most MaxReach.
inline bool Flame(const std::array<float, 3>& c, float inv_reach2) {
    if (!(inv_reach2 > 0.0f) || !std::isfinite(inv_reach2) ||
        1.0f / std::sqrt(inv_reach2) > MaxReach) {
        return false;
    }
    if (!std::isfinite(c[0]) || !std::isfinite(c[1]) || !std::isfinite(c[2]) || !(c[0] > 0.0f)) {
        return false;
    }
    return c[1] >= 0.15f * c[0] && c[1] <= 0.97f * c[0] && c[2] >= 0.0f && c[2] <= 0.8f * c[0];
}

/// What happened to a lamp this frame.
enum class State : std::uint8_t { Flickers, Waiting, GameChanges };

/// Why a light draw was left as the game made it (counted).
enum class Skip : std::uint8_t { Binding, GpuWritten, Stream, Large };

class Tracker {
public:
    explicit Tracker(const Params& p) : params{p} {
        lamps.reserve(MostLamps);
    }

    /// r109a: the strengths of the frame that starts (FrameEnd, from Update). `resumed`: the
    /// frame end before had both strengths at 0, so no lamp was looked at since: every lamp is
    /// forgotten and starts again as a new one (it waits SteadySeconds and fades in over RampIn).
    void SetStrengths(float steady, float on_game, bool resumed = false) {
        std::scoped_lock lock{mutex};
        params.strength = steady;
        params.on_game = on_game;
        params.on = steady > 0.0f || on_game > 0.0f;
        if (resumed) {
            lamps.clear();
        }
    }

    /// A light draw's `count` records (16 words each) at `in`: the records with each flickering
    /// lamp's colour scaled, or null when no word of them would change. `key`: the draw's records
    /// in guest memory, for Fog. inv_view: the camera, view to world, 12 floats in rows of four;
    /// null: unknown, nothing flickers. The pointer holds until the next call.
    const std::uint32_t* PatchDraw(const void* key, const std::uint32_t* in, std::uint32_t count,
                                   const float* inv_view) {
        std::scoped_lock lock{mutex};
        last_key = nullptr;
        scratch.resize(std::size_t(count) * 16u);
        if (!Patch(in, count, scratch.data(), inv_view)) {
            ++window.draws_plain;
            return nullptr;
        }
        last_key = key;
        return scratch.data();
    }

    /// The draw PatchDraw last answered for was bound to the patched records.
    void Bound() {
        std::scoped_lock lock{mutex};
        ++window.draws_bound;
    }

    /// The draw is left as it is. Skip::Large turns the flicker off for the session.
    void Skipped(Skip why) {
        std::scoped_lock lock{mutex};
        last_key = nullptr;
        ++window.skips[std::size_t(why)];
        too_large = too_large || why == Skip::Large;
    }

    /// A binding was too large to copy (Skipped(Skip::Large)): nothing flickers any more.
    [[nodiscard]] bool TooLarge() {
        std::scoped_lock lock{mutex};
        return too_large;
    }

    void Forget() {
        std::scoped_lock lock{mutex};
        last_key = nullptr;
    }

    /// The lamp fog's records of the draw whose records are at `raw` in guest memory: the ones
    /// that draw was bound to (once), else `raw`.
    const std::uint32_t* FogRecords(const std::uint32_t* raw) {
        std::scoped_lock lock{mutex};
        if (last_key != static_cast<const void*>(raw)) {
            return raw;
        }
        last_key = nullptr;
        return scratch.data();
    }

    /// The records of a draw, patched into `out`; true when a word differs from `in`.
    bool Patch(const std::uint32_t* in, std::uint32_t count, std::uint32_t* out,
               const float* inv_view) {
        bool changed = false;
        for (std::uint32_t k = 0; k < count; ++k) {
            const std::uint32_t* record = in + std::size_t(k) * 16u;
            std::uint32_t* to = out + std::size_t(k) * 16u;
            std::copy_n(record, 16, to);
            const Slot& slot = Look(record, inv_view);
            if (slot.changes) {
                std::copy_n(slot.colour.begin(), 3, to + 4);
                changed = true;
            }
        }
        window.records += count;
        return changed;
    }

    /// Frame end: `seconds` is the time of the frame that starts. print(format, ...): the log.
    template <typename Print>
    void EndFrame(double seconds, Print&& print) {
        std::scoped_lock lock{mutex};
        ++window.frames;
        window.no_camera += frame_blind ? 1u : 0u;
        window.unique += frame_unique;
        window.not_flame += frame_not_flame;
        window.untracked += frame_untracked;
        for (const Lamp& lamp : lamps) {
            if (lamp.seen_frame != frame) {
                continue;
            }
            ++window.states[std::size_t(lamp.state)];
            if (lamp.state == State::Flickers) {
                window.least = std::min(window.least, lamp.factor);
                window.most = std::max(window.most, lamp.factor);
            }
        }
        if (params.show && frame % ShowFrames == 0) {
            ShowLine(print);
        }
        if (window.frames >= (lines_printed ? LineFrames : FirstLineFrames)) {
            lines_printed = true;
            const double f = double(window.frames);
            print("Lamp flicker (r96): over %u frames, light draws bound to flickered lamp records "
                  "%llu, with nothing to change %llu, left as the game made them (binding not "
                  "copied %llu, GPU-written %llu, no stream room %llu, too large to copy %llu, "
                  "then off for the session); records %llu; a frame: %.1f distinct records, %.1f "
                  "not flame-coloured, %.1f flame lamps flickering, %.1f waiting (steady less "
                  "than %.1f s), %.1f left alone (the game changes their colour or reach), %.1f "
                  "not followed (more than %u); frames without a camera %u; light "
                  "factor %.3f to %.3f, largest step from one frame to the next %.4f\n",
                  window.frames, (unsigned long long)window.draws_bound,
                  (unsigned long long)window.draws_plain, (unsigned long long)window.skips[0],
                  (unsigned long long)window.skips[1], (unsigned long long)window.skips[2],
                  (unsigned long long)window.skips[3], (unsigned long long)window.records,
                  double(window.unique) / f,
                  double(window.not_flame) / f, double(window.states[0]) / f,
                  double(window.states[1]) / f, SteadySeconds, double(window.states[2]) / f,
                  double(window.untracked) / f, MostLamps, window.no_camera,
                  double(window.least <= window.most ? window.least : 1.0f),
                  double(window.least <= window.most ? window.most : 1.0f),
                  double(window.step));
            window = {};
        }
        ++frame;
        now = seconds;
        frame_unique = frame_not_flame = frame_untracked = 0;
        frame_blind = false;
    }

    // For tests and the log.
    [[nodiscard]] std::uint64_t Frame() const {
        return frame;
    }
    [[nodiscard]] float LargestStep() const {
        return window.step;
    }
    /// Lamps by State over the frames since the last periodic line.
    [[nodiscard]] std::array<std::uint64_t, 3> States() const {
        return window.states;
    }

private:
    struct Lamp {
        std::array<float, 3> world{};
        float reach = 0.0f;
        std::array<std::uint32_t, 3> raw{};
        std::uint32_t raw_r2 = 0; ///< word 3 (1 / reach squared) as last seen
        std::uint32_t seed = 0;
        std::uint64_t seen_frame = 0;
        double seen_at = 0.0, changed_at = 0.0, born_at = 0.0;
        float amount = 0.0f;
        float game_amount = 0.0f; ///< r109a: the share of the on-game flicker
        float factor = 1.0f;
        float away = 0.0f;
        float luma = 0.0f;
        State state = State::Waiting;
    };
    struct Slot {
        std::uint64_t frame = 0;
        std::array<std::uint32_t, 7> key{};
        std::array<std::uint32_t, 3> colour{};
        bool changes = false;
    };
    struct Window {
        std::uint32_t frames = 0, no_camera = 0;
        std::uint64_t draws_bound = 0, draws_plain = 0, records = 0;
        std::array<std::uint64_t, 4> skips{};
        std::uint64_t unique = 0, not_flame = 0, untracked = 0;
        std::array<std::uint64_t, 3> states{};
        float least = 2.0f, most = 0.0f, step = 0.0f;
    };

    static float F(std::uint32_t word) {
        return std::bit_cast<float>(word);
    }

    /// The frame's answer for a record: one lamp is looked at once a frame, whatever the number
    /// of tiles that list it, so all its records in the frame get the same colour.
    const Slot& Look(const std::uint32_t* record, const float* inv_view) {
        std::uint32_t h = 0x811C9DC5u;
        for (std::uint32_t i = 0; i < 7; ++i) {
            h = Hash(h ^ record[i]);
        }
        for (std::uint32_t tries = 0; tries < FrameSlots; ++tries) {
            Slot& slot = slots[(h + tries) % FrameSlots];
            if (slot.frame != frame) {
                slot.frame = frame;
                std::copy_n(record, 7, slot.key.begin());
                slot.changes = Decide(record, inv_view, slot.colour);
                return slot;
            }
            if (std::equal(slot.key.begin(), slot.key.end(), record)) {
                return slot;
            }
        }
        ++frame_untracked;
        return none;
    }

    /// A record seen for the first time this frame: its lamp followed, its flicker advanced.
    bool Decide(const std::uint32_t* record, const float* inv_view,
                std::array<std::uint32_t, 3>& out) {
        ++frame_unique;
        const std::array<float, 3> colour{F(record[4]), F(record[5]), F(record[6])};
        const float inv_r2 = F(record[3]);
        if (!Flame(colour, inv_r2)) {
            ++frame_not_flame;
            return false;
        }
        if (inv_view == nullptr) {
            frame_blind = true;
            return false;
        }
        const std::array<float, 3> v{F(record[0]), F(record[1]), F(record[2])};
        if (!std::isfinite(v[0]) || !std::isfinite(v[1]) || !std::isfinite(v[2])) {
            return false;
        }
        std::array<float, 3> world{};
        for (int r = 0; r < 3; ++r) {
            world[r] = inv_view[r * 4] * v[0] + inv_view[r * 4 + 1] * v[1] +
                       inv_view[r * 4 + 2] * v[2] + inv_view[r * 4 + 3];
        }
        const float reach = 1.0f / std::sqrt(inv_r2);
        const int index = Find(world, reach);
        if (index < 0) {
            ++frame_untracked;
            return false;
        }
        Lamp& lamp = lamps[std::size_t(index)];
        const bool fresh = lamp.seen_frame == 0;
        if (fresh) {
            lamp.changed_at = now;
            lamp.born_at = now;
            std::copy_n(record + 4, 3, lamp.raw.begin());
            lamp.raw_r2 = record[3];
            lamp.seen_at = now;
        } else {
            for (std::size_t c = 0; c < 3; ++c) {
                const float was = F(lamp.raw[c]);
                if (std::abs(colour[c] - was) > ChangeRel * std::max(std::abs(was), 1e-6f)) {
                    lamp.changed_at = now;
                }
            }
            // A flame the game flickers by its reach changes too.
            const float was_r2 = F(lamp.raw_r2);
            if (std::abs(inv_r2 - was_r2) > ChangeRel * was_r2) {
                lamp.changed_at = now;
            }
            std::copy_n(record + 4, 3, lamp.raw.begin());
            lamp.raw_r2 = record[3];
        }
        const double dt = std::clamp(now - lamp.seen_at, 0.0, 0.1);
        const bool steady = now - lamp.changed_at >= SteadySeconds; // r96's 1 s rule
        // A lamp not yet steady for SteadySeconds whose colour or reach changed after it was first
        // seen: the game changes it. r109a (replaces r96b's BB_LAMP_FLICKER_ON_GAME=1 rule, which
        // counted every lamp as steady): with the on-game strength above 0 such a lamp gets a
        // share of its own (game_amount); at 0 that share stays 0 and the lamp is left alone.
        const bool game_changes = !steady && lamp.changed_at > lamp.born_at;
        const bool on_game = game_changes && params.on_game > 0.0f;
        lamp.amount = steady ? float(std::min(1.0, double(lamp.amount) + dt / RampIn))
                             : float(std::max(0.0, double(lamp.amount) - dt / RampOut));
        lamp.game_amount = on_game
                               ? float(std::min(1.0, double(lamp.game_amount) + dt / RampIn))
                               : float(std::max(0.0, double(lamp.game_amount) - dt / RampOut));
        const float before = lamp.factor;
        const bool followed = lamp.seen_frame + 1 == frame;
        float swing = params.Amplitude() * lamp.amount;
        if (lamp.game_amount > 0.0f) {
            swing += params.Amplitude(params.on_game) * lamp.game_amount;
        }
        lamp.factor = 1.0f + swing * Wave(lamp.seed, now);
        if (followed) {
            window.step = std::max(window.step, std::abs(lamp.factor - before));
        }
        // A lamp not yet steady for SteadySeconds is waiting, unless the game changes it; such a
        // lamp flickers only by the on-game strength.
        lamp.state = game_changes ? (on_game && lamp.game_amount > 0.0f ? State::Flickers
                                                                        : State::GameChanges)
                     : steady && lamp.amount > 0.0f ? State::Flickers
                                                    : State::Waiting;
        lamp.seen_frame = frame;
        lamp.seen_at = now;
        lamp.world = world;
        lamp.reach = reach;
        lamp.away = std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
        lamp.luma = Luma[0] * colour[0] + Luma[1] * colour[1] + Luma[2] * colour[2];
        if (!(swing > 0.0f) || lamp.factor == 1.0f) {
            return false;
        }
        const auto gains = Gains(lamp.factor, params.Temp(), colour);
        bool changes = false;
        for (std::size_t c = 0; c < 3; ++c) {
            out[c] = std::bit_cast<std::uint32_t>(colour[c] * gains[c]);
            changes = changes || out[c] != record[4 + c];
        }
        return changes;
    }

    /// The lamp at `world` with about `reach`: the nearest one not yet seen this frame within
    /// MatchReach, else a new one (in a free place, or the longest unseen one's if it was not
    /// seen for a second); -1 when all MostLamps were seen within the last second.
    int Find(const std::array<float, 3>& world, float reach) {
        int best = -1;
        float best_cost = 0.0f;
        for (std::size_t i = 0; i < lamps.size(); ++i) {
            const Lamp& lamp = lamps[i];
            if (lamp.seen_frame == frame) {
                continue;
            }
            float d2 = 0.0f;
            for (int c = 0; c < 3; ++c) {
                d2 += (world[c] - lamp.world[c]) * (world[c] - lamp.world[c]);
            }
            const float lr = std::log(reach / std::max(lamp.reach, 1e-6f));
            if (!(d2 <= MatchReach * MatchReach) || !(std::abs(lr) <= MatchReachLog)) {
                continue;
            }
            const float cost = d2 + 0.0625f * lr * lr;
            if (best < 0 || cost < best_cost) {
                best = int(i);
                best_cost = cost;
            }
        }
        if (best >= 0) {
            return best;
        }
        std::size_t at = lamps.size();
        if (lamps.size() >= MostLamps) {
            at = 0;
            for (std::size_t i = 1; i < lamps.size(); ++i) {
                if (lamps[i].seen_at < lamps[at].seen_at) {
                    at = i;
                }
            }
            if (lamps[at].seen_frame == frame || now - lamps[at].seen_at < 1.0) {
                return -1;
            }
        } else {
            lamps.emplace_back();
        }
        Lamp& lamp = lamps[at];
        lamp = {};
        std::uint32_t seed = 0x2545F491u;
        for (int c = 0; c < 3; ++c) {
            seed = Hash(seed ^ std::uint32_t(std::int32_t(std::floor(world[c] / SeedCell))));
        }
        lamp.seed = seed;
        lamp.world = world;
        lamp.reach = reach;
        return int(at);
    }

    template <typename Print>
    void ShowLine(Print& print) {
        std::array<const Lamp*, 6> closest{};
        std::size_t n = 0;
        for (const Lamp& lamp : lamps) {
            if (lamp.seen_frame != frame) {
                continue;
            }
            const Lamp* item = &lamp;
            for (std::size_t i = 0; i < closest.size() && item != nullptr; ++i) {
                if (closest[i] == nullptr || item->away < closest[i]->away) {
                    std::swap(closest[i], item);
                }
            }
            n = std::min(closest.size(), n + 1);
        }
        print("Lamp flicker (r96 show): %zu nearest flame lamps (world x y z, reach, game "
              "luminance, distance, state, light factor, share of the flicker):",
              n);
        static constexpr const char* Names[] = {"flickers", "waiting", "game changes it"};
        for (std::size_t i = 0; i < n; ++i) {
            const Lamp& l = *closest[i];
            print(" (%.2f %.2f %.2f) %.1f m, %.2f, %.1f m, %s, %.3f, %.2f;", double(l.world[0]),
                  double(l.world[1]), double(l.world[2]), double(l.reach), double(l.luma),
                  double(l.away), Names[std::size_t(l.state)], double(l.factor),
                  double(l.amount));
        }
        print("%s", "\n");
    }

    Params params;
    std::mutex mutex;
    std::vector<Lamp> lamps;
    std::array<Slot, FrameSlots> slots{};
    Slot none{};
    std::vector<std::uint32_t> scratch;
    const void* last_key = nullptr;
    bool too_large = false; ///< Skip::Large happened: off for the session
    bool lines_printed = false; ///< the first periodic line went out
    std::uint64_t frame = 1;
    double now = 0.0;
    std::uint32_t frame_unique = 0, frame_not_flame = 0, frame_untracked = 0;
    bool frame_blind = false; ///< a flame lamp's record came without a camera this frame
    Window window{};
};

inline Tracker& Get() {
    static Tracker tracker{Knobs()};
    return tracker;
}

/// The lamp fog's records of a light draw (see Tracker::FogRecords); with the knob off, `raw`.
inline const std::uint32_t* Fog(const std::uint32_t* raw) {
    return On() ? Get().FogRecords(raw) : raw;
}

/// Each frame end (EffectsOnFrameEnd), after Update. r109a: the strengths' line at the first frame
/// end and after a change (at most once every LineFrames frames), also while both are 0. Off:
/// nothing more. On: the tracker takes the strengths (and forgets its lamps when the frame end
/// before was off) and ends its frame with real time.
template <typename Print>
void FrameEnd(Print&& print) {
    static StrengthKnob::Line line;
    static bool ran = false; ///< the tracker's frame end ran at the frame end before
    const Strengths& s = Detail::now;
    if (line.Due(LineFrames, s.steady, s.on_game)) {
        const Params& p = Knobs();
        print("Lamp flicker (r109a): flame lamps the game keeps steady: strength %.2f from the %s "
              "(%s), up to %.0f%% of their light; flame lamps the game changes itself: strength "
              "%.2f from the %s (%s)%s; colour shift %.2f (BB_LAMP_FLICKER_TEMP)%s%s\n",
              double(s.steady.value), StrengthKnob::SourceName(s.steady),
              s.steady.from_env ? "BB_LAMP_FLICKER" : "graphics_lamp_flicker_strength",
              double(p.Amplitude(s.steady.value)) * 100.0, double(s.on_game.value),
              StrengthKnob::SourceName(s.on_game),
              s.on_game.from_env ? "BB_LAMP_FLICKER_ON_GAME" : "graphics_lamp_flicker_on_game_strength",
              s.on_game.value > 0.0f ? ", this flicker on top of their own" : ", left alone",
              double(p.Temp()),
              p.show ? ", BB_LAMP_FLICKER_SHOW=1: exaggerated, lamps listed every 120 frames" : "",
              s.On() ? "" : "; both 0: off, nothing of it runs");
    }
    if (!On()) {
        ran = false;
        return;
    }
    using Clock = std::chrono::steady_clock;
    static const Clock::time_point start = Clock::now();
    Tracker& tracker = Get();
    tracker.SetStrengths(s.steady.value, s.on_game.value, !ran);
    ran = true;
    tracker.EndFrame(std::chrono::duration<double>(Clock::now() - start).count(), print);
}

} // namespace LampFlicker
