# r96_lamp-flicker-colour: FEATURE patch (order item 9, "Flicker and color tempature changes").
# Flame lamps (candles, lanterns, torches, street gas lamps) flicker gently with a matching colour
# temperature shift (dimmer is redder, brighter is yellower), each lamp with its own phase. Off by
# default behind BB_LAMP_FLICKER (strength 0..1, environment, read once); BB_LAMP_FLICKER_TEMP
# (colour shift 0..1, default 0.6), BB_LAMP_FLICKER_SHOW=1 (exaggerated, lamps listed in the log).
#
# Hook (proof in the context file bbfss-ctx-flicker-colour-temperature.md): the game lights its
# lamps in light draws whose pixel stage reads 16-word lamp records (view space place, 1/reach^2,
# colour in words 4-6) from its buffer 1. Rasterizer::EffectsBeforeBind runs for such a draw after
# BindResources and before the pipeline writes its descriptors; the new LampFlickerBind points
# dc.buffer_infos[n] (n = the pixel stage's buffer 1 in the numbering BindResources uses for both
# buffer_infos and the push offsets) at a stream buffer copy of the binding's bytes from guest
# memory (as OnLightDraw reads them; the constant ring is device memory mapped for writing and is
# never read by the CPU), with the flickering lamps' colours scaled, at the same push offset; a
# binding above 4096 bytes turns the flicker off for the session (bounds the copy cost).
# Review 2026-11-15 (this .fixed.py): ring reads removed (uncached reads of device memory, several
# ms a frame), copy size cap, reach changes also mark a game-flickered lamp, `near` renamed (a
# Windows macro), lampWeight's luminance weights tied (test i1 and a text check), README exact. The same patched records go to PointShadow::OnLightDraw
# (the ray traced lamp shadow weights read words 0-6, luminance with the same 0.299/0.587/0.114
# weights) and to VolumetricLight::AddPointLights (the lamp fog), so lit light, shadow weights and
# fog agree. Host writes only: no GPU command is recorded, no lamps-apart batch is ended.
# Game flicker: a lamp whose colour changes from one frame to the next is left alone (the hunter's
# lantern does: its luminance went 0.79-1.05 between 600-frame lamp lines, the street lamps beside
# it stayed constant), see lamp_flicker.h.
#
# Files:
#   NEW  engine/gpu/shadps4/video_core/renderer_vulkan/lamp_flicker.h   (header only, pure C++)
#   NEW  engine/tests/test_lamp_flicker.cpp                            (unit test, checks a-h)
#   HOOK engine/gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer_effects.cpp
#        (1 include, AnyWanted one term, 1 frame end line, LampFlickerBind before EffectsBeforeBind,
#         3 lines before OnLightDraw + its .lights word, the lamp fog's records argument)
#   HOOK engine/gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer.h (1 declaration)
#   HOOK engine/gpu/CMakeLists.txt (lamp-flicker-test), engine/build.sh (--test), README.md (section)
# No shader is added or changed.
#
# Off: LampFlicker::On() is a function-local static bool read once; with it false
# LampFlickerBind is never called, Fog returns its argument, FrameEnd returns, AnyWanted is as
# before, the tracker (Get) is never constructed: same descriptors, same bytes, no buffer, no pass.
#
# usage: python -I -X utf8 r96_lamp-flicker-colour.py check|apply|revert
#        root: env R96_ROOT, else <tree>. Backups of edited files next to this script
#        (r96_backup) on apply; revert takes this patch's text out again (inserted blocks removed,
#        replaced lines restored) so it also works with patches applied after it.
import os, sys

ROOT = os.environ.get("R96_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r96_backup")
R = "engine/gpu/shadps4/video_core/renderer_vulkan/"
EFF = R + "vk_rasterizer_effects.cpp"
RH = R + "vk_rasterizer.h"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
RM = "README.md"

NEW = {
    R + "lamp_flicker.h": '// SPDX-License-Identifier: GPL-3.0-or-later\n#pragma once\n\n// bbport (r96_lamp-flicker-colour): flame lamps flicker. BB_LAMP_FLICKER (environment, read once)\n// is the strength, 0 to 1; unset, 0 or not a number is off, and then nothing here runs: the\n// rasterizer tests On() (one static bool) before every call.\n//\n// Where: the game lights its lamps in light draws whose pixel stage reads the lamps\' records\n// (16 words each: view space position, 1 / reach squared, colour in words 4 to 6) from its buffer\n// 1, once for every screen tile a lamp reaches. The rasterizer hands each such draw\'s records to\n// Tracker::PatchDraw after the draw\'s buffers are bound; when a lamp of the draw flickers, the\n// draw\'s buffer 1 is bound to a copy with that lamp\'s colour scaled (vk_rasterizer_effects.cpp,\n// LampFlickerBind; the bytes come from guest memory, the constant ring is never read), and the\n// same patched records go to the ray traced lamp shadow pass\n// (PointShadow::OnLightDraw, which weighs each lamp by the luminance of the colour it reads) and\n// to the lamp fog (VolumetricLight::AddPointLights). Nothing else of the record changes.\n//\n// Which lamps: a record whose colour is flame-coloured (Flame: red the strongest, green between\n// 0.15 and 0.97 of red, blue at most 0.8 of red, reach at most MaxReach) and whose colour and\n// reach the game has kept the same, each word up to a relative ChangeRel, for SteadySeconds. A\n// lamp is followed from frame to frame by its place in the world (within MatchReach of where it\n// was, reach within 35%), so a carried lamp keeps its own flicker. The game flickers some lamps\n// itself: the hunter\'s lantern (its luminance went between 0.79 and 1.05 over the 600-frame lamp\n// lines of 2026-11-15, while the street lamps beside it kept 1.08 and 0.68 in every line); such a\n// lamp changes its colour (a torch might change its reach instead) from one frame to the next and\n// is left alone, so no flicker is doubled. A lamp that starts to change while it flickers loses\n// the flicker within RampOut seconds; one that has been steady for SteadySeconds gets it over\n// RampIn seconds (no pop when a lamp appears, nor when the camera cuts).\n//\n// How: the light is multiplied by f = 1 + A * amount * Wave(seed, t), A = Swing * strength (times\n// ShowScale with BB_LAMP_FLICKER_SHOW=1, at most MaxSwing), Wave a sum of three sines of\n// 0.37, 1.13 and 2.71 Hz (each scaled 0.85 to 1.15 per lamp, phases per lamp), |Wave| <= 1, so f\n// moves at most about 1.12 A / Swing per second (no strobing). The colour follows: channel c is\n// multiplied by f^(1 + T k_c), k = (-0.6, 0.35, 1.1), T = BB_LAMP_FLICKER_TEMP (default 0.6; times\n// 2 with SHOW, at most MaxTemp), then all three by the one number that gives the colour\'s\n// luminance (0.299, 0.587, 0.114) exactly f times the game\'s: dimmer is redder, brighter is\n// yellower, and the lamp\'s luminance, which point_shadow_ray.comp\'s lampWeight reads with the same\n// weights, is f times the game\'s. The seed comes from the lamp\'s place (0.5 m cells) where it was\n// first seen, so a lamp has the same flicker when it comes back.\n\n#include <algorithm>\n#include <array>\n#include <bit>\n#include <chrono>\n#include <cmath>\n#include <cstddef>\n#include <cstdint>\n#include <cstdlib>\n#include <mutex>\n#include <vector>\n\nnamespace LampFlicker {\n\ninline constexpr float DefaultTemp = 0.6f;  ///< BB_LAMP_FLICKER_TEMP when not set\ninline constexpr float Swing = 0.14f;       ///< light between 1 - Swing and 1 + Swing at strength 1\ninline constexpr float ShowScale = 3.0f;    ///< BB_LAMP_FLICKER_SHOW=1: swing times this\ninline constexpr float MaxSwing = 0.6f;     ///< the swing never goes past this\ninline constexpr float ShowTempScale = 2.0f; ///< BB_LAMP_FLICKER_SHOW=1: colour shift times this\ninline constexpr float MaxTemp = 2.0f;\ninline constexpr float MaxReach = 40.0f;      ///< m: a light reaching further is no flame\ninline constexpr float MatchReach = 0.5f;     ///< m: the same lamp as the frame before\ninline constexpr float MatchReachLog = 0.3f;  ///< |ln(reach / reach before)|: about 35%\ninline constexpr double SteadySeconds = 1.0;  ///< colour, reach unchanged this long: it flickers\ninline constexpr double RampIn = 1.0;         ///< s from no flicker to full\ninline constexpr double RampOut = 0.2;        ///< s from full flicker to none\ninline constexpr float ChangeRel = 2e-4f;     ///< colour or 1/reach^2 moved more: changed\ninline constexpr float SeedCell = 0.5f;       ///< m\ninline constexpr std::uint32_t MostLamps = 256; ///< lamps followed; more are left alone\ninline constexpr std::uint32_t FrameSlots = 1024; ///< distinct records a frame; more left alone\n/// A light draw\'s buffer 1 binding (records, and what the push offset skips) above this many\n/// bytes is not copied, and the flicker is off for the rest of the session (12 records are 768).\ninline constexpr std::uint64_t MostCopyBytes = 4096;\ninline constexpr std::uint32_t LineFrames = 600;  ///< the periodic log line\ninline constexpr std::uint32_t FirstLineFrames = 120; ///< its first one (short test runs see it)\ninline constexpr std::uint32_t ShowFrames = 120;  ///< BB_LAMP_FLICKER_SHOW=1: the lamps line\ninline constexpr std::array<float, 3> Luma{0.299f, 0.587f, 0.114f}; ///< lampWeight\'s weights\ninline constexpr std::array<float, 3> TempK{-0.6f, 0.35f, 1.1f};\ninline constexpr std::array<double, 3> WaveHz{0.37, 1.13, 2.71};\ninline constexpr std::array<float, 3> WaveWeight{0.45f, 0.35f, 0.20f};\nstatic_assert(WaveWeight[0] + WaveWeight[1] + WaveWeight[2] <= 1.0f + 1e-6f);\n\nstruct Params {\n    bool on = false;\n    float strength = 0.0f; ///< BB_LAMP_FLICKER, 0..1\n    float temp = 0.0f;     ///< BB_LAMP_FLICKER_TEMP, 0..1\n    bool show = false;     ///< BB_LAMP_FLICKER_SHOW=1\n    /// The swing and colour shift a pass uses.\n    [[nodiscard]] float Amplitude() const {\n        return std::min(MaxSwing, Swing * strength * (show ? ShowScale : 1.0f));\n    }\n    [[nodiscard]] float Temp() const {\n        return std::min(MaxTemp, temp * (show ? ShowTempScale : 1.0f));\n    }\n};\n\n/// The knobs from their texts (null: not set). A number that does not parse, is not finite or is\n/// not above 0 leaves the flicker off; the others are clamped to 0..1.\ninline Params ParseParams(const char* flicker, const char* temp, const char* show) {\n    const auto number = [](const char* text, float fallback) {\n        if (text == nullptr || text[0] == 0) {\n            return fallback;\n        }\n        char* end = nullptr;\n        const float value = std::strtof(text, &end);\n        return end != text && std::isfinite(value) ? value : fallback;\n    };\n    Params p;\n    const float strength = number(flicker, 0.0f);\n    p.on = strength > 0.0f;\n    p.strength = p.on ? std::min(strength, 1.0f) : 0.0f;\n    p.temp = std::clamp(number(temp, DefaultTemp), 0.0f, 1.0f);\n    p.show = show != nullptr && show[0] == \'1\';\n    return p;\n}\n\ninline const Params& Knobs() {\n    static const Params params = ParseParams(std::getenv("BB_LAMP_FLICKER"),\n                                             std::getenv("BB_LAMP_FLICKER_TEMP"),\n                                             std::getenv("BB_LAMP_FLICKER_SHOW"));\n    return params;\n}\n\ninline bool On() {\n    return Knobs().on;\n}\n\ninline std::uint32_t Hash(std::uint32_t x) {\n    x ^= x >> 16;\n    x *= 0x7FEB352Du;\n    x ^= x >> 15;\n    x *= 0x846CA68Bu;\n    x ^= x >> 16;\n    return x;\n}\n\ninline float Unit(std::uint32_t h) {\n    return float(h >> 8) * (1.0f / 16777216.0f);\n}\n\n/// The flicker of the lamp `seed` at `seconds`: three sines, |Wave| <= 1, smooth.\ninline float Wave(std::uint32_t seed, double seconds) {\n    constexpr double Tau = 6.283185307179586;\n    float sum = 0.0f;\n    for (std::uint32_t i = 0; i < 3; ++i) {\n        const std::uint32_t h = Hash(seed ^ (0x9E3779B9u * (i + 1u)));\n        const double hz = WaveHz[i] * (0.85 + 0.3 * double(Unit(h)));\n        const double phase = double(Unit(Hash(h))) + std::fmod(seconds * hz, 1.0);\n        sum += WaveWeight[i] * float(std::sin(Tau * phase));\n    }\n    return sum;\n}\n\n/// The three channel gains for intensity factor `factor` and colour shift `temp`: their\n/// luminance-weighted mean over `colour` is exactly `factor` (dimmer is redder).\ninline std::array<float, 3> Gains(float factor, float temp, const std::array<float, 3>& colour) {\n    const float f = std::max(factor, 0.05f);\n    std::array<float, 3> g{};\n    float lit = 0.0f, base = 0.0f;\n    for (std::size_t i = 0; i < 3; ++i) {\n        g[i] = std::pow(f, 1.0f + temp * TempK[i]);\n        lit += Luma[i] * colour[i] * g[i];\n        base += Luma[i] * colour[i];\n    }\n    if (!(lit > 0.0f) || !(base > 0.0f) || !std::isfinite(lit)) {\n        return {f, f, f};\n    }\n    const float scale = f * base / lit;\n    for (float& v : g) {\n        v *= scale;\n    }\n    return g;\n}\n\n/// A flame\'s colour: red the strongest, some green, little blue; a reach of at most MaxReach.\ninline bool Flame(const std::array<float, 3>& c, float inv_reach2) {\n    if (!(inv_reach2 > 0.0f) || !std::isfinite(inv_reach2) ||\n        1.0f / std::sqrt(inv_reach2) > MaxReach) {\n        return false;\n    }\n    if (!std::isfinite(c[0]) || !std::isfinite(c[1]) || !std::isfinite(c[2]) || !(c[0] > 0.0f)) {\n        return false;\n    }\n    return c[1] >= 0.15f * c[0] && c[1] <= 0.97f * c[0] && c[2] >= 0.0f && c[2] <= 0.8f * c[0];\n}\n\n/// What happened to a lamp this frame.\nenum class State : std::uint8_t { Flickers, Waiting, GameChanges };\n\n/// Why a light draw was left as the game made it (counted).\nenum class Skip : std::uint8_t { Binding, GpuWritten, Stream, Large };\n\nclass Tracker {\npublic:\n    explicit Tracker(const Params& p) : params{p} {\n        lamps.reserve(MostLamps);\n    }\n\n    /// A light draw\'s `count` records (16 words each) at `in`: the records with each flickering\n    /// lamp\'s colour scaled, or null when no word of them would change. `key`: the draw\'s records\n    /// in guest memory, for Fog. inv_view: the camera, view to world, 12 floats in rows of four;\n    /// null: unknown, nothing flickers. The pointer holds until the next call.\n    const std::uint32_t* PatchDraw(const void* key, const std::uint32_t* in, std::uint32_t count,\n                                   const float* inv_view) {\n        std::scoped_lock lock{mutex};\n        last_key = nullptr;\n        scratch.resize(std::size_t(count) * 16u);\n        if (!Patch(in, count, scratch.data(), inv_view)) {\n            ++window.draws_plain;\n            return nullptr;\n        }\n        last_key = key;\n        return scratch.data();\n    }\n\n    /// The draw PatchDraw last answered for was bound to the patched records.\n    void Bound() {\n        std::scoped_lock lock{mutex};\n        ++window.draws_bound;\n    }\n\n    /// The draw is left as it is. Skip::Large turns the flicker off for the session.\n    void Skipped(Skip why) {\n        std::scoped_lock lock{mutex};\n        last_key = nullptr;\n        ++window.skips[std::size_t(why)];\n        too_large = too_large || why == Skip::Large;\n    }\n\n    /// A binding was too large to copy (Skipped(Skip::Large)): nothing flickers any more.\n    [[nodiscard]] bool TooLarge() {\n        std::scoped_lock lock{mutex};\n        return too_large;\n    }\n\n    void Forget() {\n        std::scoped_lock lock{mutex};\n        last_key = nullptr;\n    }\n\n    /// The lamp fog\'s records of the draw whose records are at `raw` in guest memory: the ones\n    /// that draw was bound to (once), else `raw`.\n    const std::uint32_t* FogRecords(const std::uint32_t* raw) {\n        std::scoped_lock lock{mutex};\n        if (last_key != static_cast<const void*>(raw)) {\n            return raw;\n        }\n        last_key = nullptr;\n        return scratch.data();\n    }\n\n    /// The records of a draw, patched into `out`; true when a word differs from `in`.\n    bool Patch(const std::uint32_t* in, std::uint32_t count, std::uint32_t* out,\n               const float* inv_view) {\n        bool changed = false;\n        for (std::uint32_t k = 0; k < count; ++k) {\n            const std::uint32_t* record = in + std::size_t(k) * 16u;\n            std::uint32_t* to = out + std::size_t(k) * 16u;\n            std::copy_n(record, 16, to);\n            const Slot& slot = Look(record, inv_view);\n            if (slot.changes) {\n                std::copy_n(slot.colour.begin(), 3, to + 4);\n                changed = true;\n            }\n        }\n        window.records += count;\n        return changed;\n    }\n\n    /// Frame end: `seconds` is the time of the frame that starts. print(format, ...): the log.\n    template <typename Print>\n    void EndFrame(double seconds, Print&& print) {\n        std::scoped_lock lock{mutex};\n        ++window.frames;\n        window.no_camera += frame_blind ? 1u : 0u;\n        window.unique += frame_unique;\n        window.not_flame += frame_not_flame;\n        window.untracked += frame_untracked;\n        for (const Lamp& lamp : lamps) {\n            if (lamp.seen_frame != frame) {\n                continue;\n            }\n            ++window.states[std::size_t(lamp.state)];\n            if (lamp.state == State::Flickers) {\n                window.least = std::min(window.least, lamp.factor);\n                window.most = std::max(window.most, lamp.factor);\n            }\n        }\n        if (params.show && frame % ShowFrames == 0) {\n            ShowLine(print);\n        }\n        if (window.frames >= (lines_printed ? LineFrames : FirstLineFrames)) {\n            lines_printed = true;\n            const double f = double(window.frames);\n            print("Lamp flicker (r96): over %u frames, light draws bound to flickered lamp records "\n                  "%llu, with nothing to change %llu, left as the game made them (binding not "\n                  "copied %llu, GPU-written %llu, no stream room %llu, too large to copy %llu, "\n                  "then off for the session); records %llu; a frame: %.1f distinct records, %.1f "\n                  "not flame-coloured, %.1f flame lamps flickering, %.1f waiting (steady less "\n                  "than %.1f s), %.1f left alone (the game changes their colour or reach), %.1f "\n                  "not followed (more than %u); frames without a camera %u; light "\n                  "factor %.3f to %.3f, largest step from one frame to the next %.4f\\n",\n                  window.frames, (unsigned long long)window.draws_bound,\n                  (unsigned long long)window.draws_plain, (unsigned long long)window.skips[0],\n                  (unsigned long long)window.skips[1], (unsigned long long)window.skips[2],\n                  (unsigned long long)window.skips[3], (unsigned long long)window.records,\n                  double(window.unique) / f,\n                  double(window.not_flame) / f, double(window.states[0]) / f,\n                  double(window.states[1]) / f, SteadySeconds, double(window.states[2]) / f,\n                  double(window.untracked) / f, MostLamps, window.no_camera,\n                  double(window.least <= window.most ? window.least : 1.0f),\n                  double(window.least <= window.most ? window.most : 1.0f),\n                  double(window.step));\n            window = {};\n        }\n        ++frame;\n        now = seconds;\n        frame_unique = frame_not_flame = frame_untracked = 0;\n        frame_blind = false;\n    }\n\n    // For tests and the log.\n    [[nodiscard]] std::uint64_t Frame() const {\n        return frame;\n    }\n    [[nodiscard]] float LargestStep() const {\n        return window.step;\n    }\n    /// Lamps by State over the frames since the last periodic line.\n    [[nodiscard]] std::array<std::uint64_t, 3> States() const {\n        return window.states;\n    }\n\nprivate:\n    struct Lamp {\n        std::array<float, 3> world{};\n        float reach = 0.0f;\n        std::array<std::uint32_t, 3> raw{};\n        std::uint32_t raw_r2 = 0; ///< word 3 (1 / reach squared) as last seen\n        std::uint32_t seed = 0;\n        std::uint64_t seen_frame = 0;\n        double seen_at = 0.0, changed_at = 0.0, born_at = 0.0;\n        float amount = 0.0f;\n        float factor = 1.0f;\n        float away = 0.0f;\n        float luma = 0.0f;\n        State state = State::Waiting;\n    };\n    struct Slot {\n        std::uint64_t frame = 0;\n        std::array<std::uint32_t, 7> key{};\n        std::array<std::uint32_t, 3> colour{};\n        bool changes = false;\n    };\n    struct Window {\n        std::uint32_t frames = 0, no_camera = 0;\n        std::uint64_t draws_bound = 0, draws_plain = 0, records = 0;\n        std::array<std::uint64_t, 4> skips{};\n        std::uint64_t unique = 0, not_flame = 0, untracked = 0;\n        std::array<std::uint64_t, 3> states{};\n        float least = 2.0f, most = 0.0f, step = 0.0f;\n    };\n\n    static float F(std::uint32_t word) {\n        return std::bit_cast<float>(word);\n    }\n\n    /// The frame\'s answer for a record: one lamp is looked at once a frame, whatever the number\n    /// of tiles that list it, so all its records in the frame get the same colour.\n    const Slot& Look(const std::uint32_t* record, const float* inv_view) {\n        std::uint32_t h = 0x811C9DC5u;\n        for (std::uint32_t i = 0; i < 7; ++i) {\n            h = Hash(h ^ record[i]);\n        }\n        for (std::uint32_t tries = 0; tries < FrameSlots; ++tries) {\n            Slot& slot = slots[(h + tries) % FrameSlots];\n            if (slot.frame != frame) {\n                slot.frame = frame;\n                std::copy_n(record, 7, slot.key.begin());\n                slot.changes = Decide(record, inv_view, slot.colour);\n                return slot;\n            }\n            if (std::equal(slot.key.begin(), slot.key.end(), record)) {\n                return slot;\n            }\n        }\n        ++frame_untracked;\n        return none;\n    }\n\n    /// A record seen for the first time this frame: its lamp followed, its flicker advanced.\n    bool Decide(const std::uint32_t* record, const float* inv_view,\n                std::array<std::uint32_t, 3>& out) {\n        ++frame_unique;\n        const std::array<float, 3> colour{F(record[4]), F(record[5]), F(record[6])};\n        const float inv_r2 = F(record[3]);\n        if (!Flame(colour, inv_r2)) {\n            ++frame_not_flame;\n            return false;\n        }\n        if (inv_view == nullptr) {\n            frame_blind = true;\n            return false;\n        }\n        const std::array<float, 3> v{F(record[0]), F(record[1]), F(record[2])};\n        if (!std::isfinite(v[0]) || !std::isfinite(v[1]) || !std::isfinite(v[2])) {\n            return false;\n        }\n        std::array<float, 3> world{};\n        for (int r = 0; r < 3; ++r) {\n            world[r] = inv_view[r * 4] * v[0] + inv_view[r * 4 + 1] * v[1] +\n                       inv_view[r * 4 + 2] * v[2] + inv_view[r * 4 + 3];\n        }\n        const float reach = 1.0f / std::sqrt(inv_r2);\n        const int index = Find(world, reach);\n        if (index < 0) {\n            ++frame_untracked;\n            return false;\n        }\n        Lamp& lamp = lamps[std::size_t(index)];\n        const bool fresh = lamp.seen_frame == 0;\n        if (fresh) {\n            lamp.changed_at = now;\n            lamp.born_at = now;\n            std::copy_n(record + 4, 3, lamp.raw.begin());\n            lamp.raw_r2 = record[3];\n            lamp.seen_at = now;\n        } else {\n            for (std::size_t c = 0; c < 3; ++c) {\n                const float was = F(lamp.raw[c]);\n                if (std::abs(colour[c] - was) > ChangeRel * std::max(std::abs(was), 1e-6f)) {\n                    lamp.changed_at = now;\n                }\n            }\n            // A flame the game flickers by its reach changes too.\n            const float was_r2 = F(lamp.raw_r2);\n            if (std::abs(inv_r2 - was_r2) > ChangeRel * was_r2) {\n                lamp.changed_at = now;\n            }\n            std::copy_n(record + 4, 3, lamp.raw.begin());\n            lamp.raw_r2 = record[3];\n        }\n        const double dt = std::clamp(now - lamp.seen_at, 0.0, 0.1);\n        const bool steady = now - lamp.changed_at >= SteadySeconds;\n        lamp.amount = steady ? float(std::min(1.0, double(lamp.amount) + dt / RampIn))\n                             : float(std::max(0.0, double(lamp.amount) - dt / RampOut));\n        const float before = lamp.factor;\n        const bool followed = lamp.seen_frame + 1 == frame;\n        lamp.factor = 1.0f + params.Amplitude() * lamp.amount * Wave(lamp.seed, now);\n        if (followed) {\n            window.step = std::max(window.step, std::abs(lamp.factor - before));\n        }\n        // A lamp not yet steady for SteadySeconds is waiting, unless its colour or reach changed\n        // after it was first seen: then the game changes it.\n        lamp.state = !steady && lamp.changed_at > lamp.born_at ? State::GameChanges\n                     : steady && lamp.amount > 0.0f            ? State::Flickers\n                                                               : State::Waiting;\n        lamp.seen_frame = frame;\n        lamp.seen_at = now;\n        lamp.world = world;\n        lamp.reach = reach;\n        lamp.away = std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);\n        lamp.luma = Luma[0] * colour[0] + Luma[1] * colour[1] + Luma[2] * colour[2];\n        if (lamp.amount <= 0.0f || lamp.factor == 1.0f) {\n            return false;\n        }\n        const auto gains = Gains(lamp.factor, params.Temp(), colour);\n        bool changes = false;\n        for (std::size_t c = 0; c < 3; ++c) {\n            out[c] = std::bit_cast<std::uint32_t>(colour[c] * gains[c]);\n            changes = changes || out[c] != record[4 + c];\n        }\n        return changes;\n    }\n\n    /// The lamp at `world` with about `reach`: the nearest one not yet seen this frame within\n    /// MatchReach, else a new one (in a free place, or the longest unseen one\'s if it was not\n    /// seen for a second); -1 when all MostLamps were seen within the last second.\n    int Find(const std::array<float, 3>& world, float reach) {\n        int best = -1;\n        float best_cost = 0.0f;\n        for (std::size_t i = 0; i < lamps.size(); ++i) {\n            const Lamp& lamp = lamps[i];\n            if (lamp.seen_frame == frame) {\n                continue;\n            }\n            float d2 = 0.0f;\n            for (int c = 0; c < 3; ++c) {\n                d2 += (world[c] - lamp.world[c]) * (world[c] - lamp.world[c]);\n            }\n            const float lr = std::log(reach / std::max(lamp.reach, 1e-6f));\n            if (!(d2 <= MatchReach * MatchReach) || !(std::abs(lr) <= MatchReachLog)) {\n                continue;\n            }\n            const float cost = d2 + 0.0625f * lr * lr;\n            if (best < 0 || cost < best_cost) {\n                best = int(i);\n                best_cost = cost;\n            }\n        }\n        if (best >= 0) {\n            return best;\n        }\n        std::size_t at = lamps.size();\n        if (lamps.size() >= MostLamps) {\n            at = 0;\n            for (std::size_t i = 1; i < lamps.size(); ++i) {\n                if (lamps[i].seen_at < lamps[at].seen_at) {\n                    at = i;\n                }\n            }\n            if (lamps[at].seen_frame == frame || now - lamps[at].seen_at < 1.0) {\n                return -1;\n            }\n        } else {\n            lamps.emplace_back();\n        }\n        Lamp& lamp = lamps[at];\n        lamp = {};\n        std::uint32_t seed = 0x2545F491u;\n        for (int c = 0; c < 3; ++c) {\n            seed = Hash(seed ^ std::uint32_t(std::int32_t(std::floor(world[c] / SeedCell))));\n        }\n        lamp.seed = seed;\n        lamp.world = world;\n        lamp.reach = reach;\n        return int(at);\n    }\n\n    template <typename Print>\n    void ShowLine(Print& print) {\n        std::array<const Lamp*, 6> closest{};\n        std::size_t n = 0;\n        for (const Lamp& lamp : lamps) {\n            if (lamp.seen_frame != frame) {\n                continue;\n            }\n            const Lamp* item = &lamp;\n            for (std::size_t i = 0; i < closest.size() && item != nullptr; ++i) {\n                if (closest[i] == nullptr || item->away < closest[i]->away) {\n                    std::swap(closest[i], item);\n                }\n            }\n            n = std::min(closest.size(), n + 1);\n        }\n        print("Lamp flicker (r96 show): %zu nearest flame lamps (world x y z, reach, game "\n              "luminance, distance, state, light factor, share of the flicker):",\n              n);\n        static constexpr const char* Names[] = {"flickers", "waiting", "game changes it"};\n        for (std::size_t i = 0; i < n; ++i) {\n            const Lamp& l = *closest[i];\n            print(" (%.2f %.2f %.2f) %.1f m, %.2f, %.1f m, %s, %.3f, %.2f;", double(l.world[0]),\n                  double(l.world[1]), double(l.world[2]), double(l.reach), double(l.luma),\n                  double(l.away), Names[std::size_t(l.state)], double(l.factor),\n                  double(l.amount));\n        }\n        print("%s", "\\n");\n    }\n\n    Params params;\n    std::mutex mutex;\n    std::vector<Lamp> lamps;\n    std::array<Slot, FrameSlots> slots{};\n    Slot none{};\n    std::vector<std::uint32_t> scratch;\n    const void* last_key = nullptr;\n    bool too_large = false; ///< Skip::Large happened: off for the session\n    bool lines_printed = false; ///< the first periodic line went out\n    std::uint64_t frame = 1;\n    double now = 0.0;\n    std::uint32_t frame_unique = 0, frame_not_flame = 0, frame_untracked = 0;\n    bool frame_blind = false; ///< a flame lamp\'s record came without a camera this frame\n    Window window{};\n};\n\ninline Tracker& Get() {\n    static Tracker tracker{Knobs()};\n    return tracker;\n}\n\n/// The lamp fog\'s records of a light draw (see Tracker::FogRecords); with the knob off, `raw`.\ninline const std::uint32_t* Fog(const std::uint32_t* raw) {\n    return On() ? Get().FogRecords(raw) : raw;\n}\n\n/// Each frame end (EffectsOnFrameEnd). Off: one static bool test. On: the knobs\' line once, then\n/// the tracker\'s frame end with real time.\ntemplate <typename Print>\nvoid FrameEnd(Print&& print) {\n    if (!On()) {\n        return;\n    }\n    using Clock = std::chrono::steady_clock;\n    static const Clock::time_point start = [&] {\n        const Params& p = Knobs();\n        print("Lamp flicker (r96, BB_LAMP_FLICKER=%.2f): flame-coloured lamps whose colour and "\n              "reach the game keeps steady flicker by up to %.0f%% of their light, colour "\n              "shift %.2f "\n              "(BB_LAMP_FLICKER_TEMP)%s; lamps the game changes itself are left alone\\n",\n              double(p.strength), double(p.Amplitude()) * 100.0, double(p.Temp()),\n              p.show ? ", BB_LAMP_FLICKER_SHOW=1: exaggerated, lamps listed every 120 frames" : "");\n        return Clock::now();\n    }();\n    Get().EndFrame(std::chrono::duration<double>(Clock::now() - start).count(), print);\n}\n\n} // namespace LampFlicker\n',
    "engine/tests/test_lamp_flicker.cpp": '// SPDX-License-Identifier: GPL-3.0-or-later\n// bbport (r96_lamp-flicker-colour): the lamp flicker\'s knobs, wave, colour gains, flame test and\n// tracker (gpu/shadps4/video_core/renderer_vulkan/lamp_flicker.h).\n#include <algorithm>\n#include <array>\n#include <bit>\n#include <cmath>\n#include <cstdint>\n#include <cstdio>\n#include <vector>\n\n#include "gpu/shadps4/video_core/renderer_vulkan/lamp_flicker.h"\n#include "gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h"\n\nusing namespace LampFlicker;\n\nnamespace {\nint failures = 0;\n\nvoid Expect(bool ok, const char* what) {\n    if (!ok) {\n        std::printf("FAIL: %s\\n", what);\n        ++failures;\n    }\n}\n\nstd::uint32_t U(float f) {\n    return std::bit_cast<std::uint32_t>(f);\n}\n\nfloat Fl(std::uint32_t u) {\n    return std::bit_cast<float>(u);\n}\n\n/// One record: view space place, reach, colour; words 7 to 15 hold other things.\nstd::array<std::uint32_t, 16> Record(float x, float y, float z, float reach, float r, float g,\n                                     float b) {\n    std::array<std::uint32_t, 16> rec{};\n    rec[0] = U(x);\n    rec[1] = U(y);\n    rec[2] = U(z);\n    rec[3] = U(1.0f / (reach * reach));\n    rec[4] = U(r);\n    rec[5] = U(g);\n    rec[6] = U(b);\n    for (std::uint32_t i = 7; i < 16; ++i) {\n        rec[i] = 0xA5A50000u + i;\n    }\n    return rec;\n}\n\nfloat LumaOf(const std::uint32_t* rec) {\n    return Luma[0] * Fl(rec[4]) + Luma[1] * Fl(rec[5]) + Luma[2] * Fl(rec[6]);\n}\n\nint lines = 0;\nconst auto Count = [](const char*, auto&&...) { ++lines; };\n\n// The camera at the world origin looking down view -z: view space is world space.\nconstexpr std::array<float, 12> Identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};\n} // namespace\n\nint main() {\n    // a. knobs\n    {\n        const Params off = ParseParams(nullptr, nullptr, nullptr);\n        Expect(!off.on && off.strength == 0.0f, "a1 unset is off");\n        Expect(!ParseParams("0", nullptr, nullptr).on, "a2 0 is off");\n        Expect(!ParseParams("abc", nullptr, nullptr).on, "a3 text is off");\n        Expect(!ParseParams("-1", nullptr, nullptr).on, "a4 negative is off");\n        Expect(!ParseParams("nan", nullptr, nullptr).on, "a5 nan is off");\n        const Params one = ParseParams("1", nullptr, nullptr);\n        Expect(one.on && one.strength == 1.0f && one.temp == DefaultTemp && !one.show,\n               "a6 1 is full strength, default colour shift");\n        Expect(ParseParams("3", nullptr, nullptr).strength == 1.0f, "a7 clamped to 1");\n        Expect(ParseParams("0.5", "0", nullptr).temp == 0.0f, "a8 temp 0");\n        Expect(ParseParams("0.5", "7", nullptr).temp == 1.0f, "a9 temp clamped");\n        Expect(ParseParams("0.5", "x", nullptr).temp == DefaultTemp, "a10 temp text: default");\n        const Params show = ParseParams("1", nullptr, "1");\n        Expect(show.show && show.Amplitude() == std::min(MaxSwing, Swing * ShowScale),\n               "a11 show multiplies the swing");\n        Expect(one.Amplitude() == Swing, "a12 swing at 1");\n    }\n    // b. wave: bounded, smooth (step per 1/60 s within the bound of its derivative)\n    {\n        float most = 0.0f, step = 0.0f;\n        double bound = 0.0;\n        for (std::size_t i = 0; i < 3; ++i) {\n            bound += double(WaveWeight[i]) * WaveHz[i] * 1.15 * 6.283185307179586;\n        }\n        for (std::uint32_t seed : {1u, 77u, 0xDEADBEEFu, 123456789u}) {\n            float before = Wave(seed, 0.0);\n            for (int f = 1; f < 60 * 120; ++f) {\n                const float w = Wave(seed, f / 60.0);\n                most = std::max(most, std::abs(w));\n                step = std::max(step, std::abs(w - before));\n                before = w;\n            }\n        }\n        Expect(most <= 1.0f + 1e-5f, "b1 |wave| <= 1");\n        Expect(most > 0.5f, "b2 the wave moves");\n        Expect(double(step) <= bound / 60.0 + 1e-4, "b3 step per frame within the slope bound");\n        std::printf("wave: largest %.4f, largest step per 1/60 s %.4f (bound %.4f)\\n", double(most),\n                    double(step), bound / 60.0);\n        Expect(Wave(5u, 10.0) != Wave(6u, 10.0), "b4 seeds differ");\n        Expect(Wave(5u, 1000000.25) == Wave(5u, 1000000.25), "b5 deterministic");\n    }\n    // c. gains: luminance exactly f times, dimmer redder, brighter yellower, no shift at T 0\n    {\n        const std::array<float, 3> c{1.0f, 0.55f, 0.18f};\n        const float base = Luma[0] * c[0] + Luma[1] * c[1] + Luma[2] * c[2];\n        for (const float f : {0.4f, 0.86f, 1.0f, 1.14f, 1.6f}) {\n            for (const float t : {0.0f, 0.6f, 1.2f, 2.0f}) {\n                const auto g = Gains(f, t, c);\n                const float lit = Luma[0] * c[0] * g[0] + Luma[1] * c[1] * g[1] + Luma[2] * c[2] * g[2];\n                Expect(std::abs(lit - f * base) <= 1e-5f * f * base, "c1 luminance is f times");\n                if (t == 0.0f) {\n                    Expect(std::abs(g[0] - f) < 1e-5f && std::abs(g[1] - f) < 1e-5f &&\n                               std::abs(g[2] - f) < 1e-5f,\n                           "c2 no colour shift at T 0");\n                } else if (f < 1.0f) {\n                    Expect(g[0] > g[1] && g[1] > g[2], "c3 dimmer is redder");\n                } else if (f > 1.0f) {\n                    Expect(g[0] < g[1] && g[1] < g[2], "c4 brighter is yellower");\n                } else {\n                    Expect(g[0] == 1.0f && g[1] == 1.0f && g[2] == 1.0f, "c5 f 1 changes nothing");\n                }\n            }\n        }\n    }\n    // d. flame colours\n    {\n        Expect(Flame({1.0f, 0.55f, 0.18f}, 1.0f / 64.0f), "d1 orange flame");\n        Expect(Flame({1.2f, 0.9f, 0.5f}, 1.0f / 144.0f), "d2 yellow gas lamp");\n        Expect(!Flame({1.0f, 1.0f, 1.0f}, 1.0f / 64.0f), "d3 white is no flame");\n        Expect(!Flame({0.3f, 0.4f, 1.0f}, 1.0f / 64.0f), "d4 blue is no flame");\n        Expect(!Flame({-1.0f, -0.5f, -0.1f}, 1.0f / 64.0f), "d5 a light that darkens is no flame");\n        Expect(!Flame({1.0f, 0.55f, 0.18f}, 1.0f / (100.0f * 100.0f)), "d6 too far a reach");\n        Expect(!Flame({1.0f, 0.55f, 0.18f}, 0.0f), "d7 no reach");\n        Expect(!Flame({1.0f, 0.05f, 0.0f}, 1.0f / 64.0f), "d8 deep red is no flame");\n    }\n    // e. tracker: a still lamp in two tiles, a lamp the game flickers, a white light\n    {\n        Params p = ParseParams("1", nullptr, nullptr);\n        Tracker t{p};\n        const auto still = Record(1.0f, 0.5f, -6.0f, 8.0f, 1.0f, 0.55f, 0.18f);\n        const auto white = Record(-3.0f, 0.5f, -9.0f, 8.0f, 0.8f, 0.8f, 0.8f);\n        std::vector<std::uint32_t> in(48), out(48);\n        bool changed_early = false, changed_late = false, tiles_differ = false;\n        bool white_changed = false;\n        bool game_lamp_changed = false, luma_ok = true, rest_kept = true;\n        float least = 2.0f, most = 0.0f;\n        for (int f = 0; f < 60 * 6; ++f) {\n            const double s = f / 60.0;\n            // the game\'s own flicker: a new colour every frame\n            const float g = 0.9f + 0.1f * float(std::sin(f * 0.7));\n            const auto game = Record(0.2f, 1.4f, -2.0f, 5.2f, g, 0.5f * g, 0.15f * g);\n            std::copy(still.begin(), still.end(), in.begin());\n            std::copy(game.begin(), game.end(), in.begin() + 16);\n            std::copy(white.begin(), white.end(), in.begin() + 32);\n            const bool changed = t.Patch(in.data(), 3, out.data(), Identity.data());\n            // the same lamp in another tile, the same frame\n            std::vector<std::uint32_t> again(16);\n            t.Patch(still.data(), 1, again.data(), Identity.data());\n            tiles_differ = tiles_differ || !std::equal(again.begin(), again.end(), out.begin());\n            if (s < SteadySeconds) {\n                changed_early = changed_early || changed;\n            } else if (s > SteadySeconds + 0.5) {\n                changed_late = changed_late || changed;\n            }\n            game_lamp_changed = game_lamp_changed ||\n                                !std::equal(out.begin() + 16, out.begin() + 32, in.begin() + 16);\n            white_changed = white_changed ||\n                            !std::equal(out.begin() + 32, out.begin() + 48, in.begin() + 32);\n            const float factor = LumaOf(out.data()) / LumaOf(in.data());\n            least = std::min(least, factor);\n            most = std::max(most, factor);\n            luma_ok = luma_ok && factor >= 1.0f - Swing - 1e-4f && factor <= 1.0f + Swing + 1e-4f;\n            for (int w : {0, 1, 2, 3, 7, 8, 15}) {\n                rest_kept = rest_kept && out[std::size_t(w)] == in[std::size_t(w)];\n            }\n            t.EndFrame(s + 1.0 / 60.0, Count);\n        }\n        Expect(!changed_early, "e1 nothing changes in the first second");\n        Expect(changed_late, "e2 a steady flame flickers after it");\n        Expect(!tiles_differ, "e3 the same lamp gets the same colour in every tile of a frame");\n        Expect(!game_lamp_changed, "e4 a lamp the game changes is left alone");\n        Expect(!white_changed, "e5 a white light is left alone");\n        Expect(luma_ok, "e6 luminance within the swing");\n        Expect(least < 0.95f && most > 1.05f, "e7 the swing is used");\n        Expect(rest_kept, "e8 place, reach and the other words are kept");\n        // wave step (0.0186 at the full swing) plus the ramp\'s (Swing / 60 / RampIn)\n        Expect(t.LargestStep() <= 0.0186f + Swing / 60.0f + 1e-4f,\n               "e9 largest step per frame within the bound");\n        const auto states = t.States();\n        Expect(states[std::size_t(State::GameChanges)] > 0, "e10 the game\'s lamp is counted");\n        std::printf("tracker: factor %.3f to %.3f, largest step %.4f; lamp frames flickering %llu, "\n                    "waiting %llu, the game changes it %llu\\n",\n                    double(least), double(most), double(t.LargestStep()),\n                    (unsigned long long)states[0], (unsigned long long)states[1],\n                    (unsigned long long)states[2]);\n    }\n    // f. a lamp that starts to change loses the flicker within RampOut, a moving lamp keeps its\n    // phase (no jump), and nothing flickers without a camera\n    {\n        Tracker t{ParseParams("1", "0", nullptr)};\n        std::array<std::uint32_t, 16> out{};\n        float before = 1.0f, jump = 0.0f;\n        bool gone = false;\n        for (int f = 0; f < 60 * 8; ++f) {\n            const double s = f / 60.0;\n            const float x = 1.0f + 0.05f * float(f);              // walks 3 m/s\n            const float bright = f < 60 * 5 ? 1.0f : 1.0f + 0.02f * float(f % 7); // the game starts\n            const auto rec = Record(x, 1.0f, -5.0f, 6.0f, bright, 0.55f * bright, 0.18f * bright);\n            t.Patch(rec.data(), 1, out.data(), Identity.data());\n            const float factor = LumaOf(out.data()) / LumaOf(rec.data());\n            if (f > 60 * 3 && f < 60 * 5) {\n                jump = std::max(jump, std::abs(factor - before));\n            }\n            if (s > 5.0 + RampOut + 2.0 / 60.0) {\n                gone = gone || factor == 1.0f;\n                Expect(factor == 1.0f, "f1 no flicker once the game changes it");\n            }\n            before = factor;\n            t.EndFrame(s + 1.0 / 60.0, Count);\n        }\n        Expect(gone, "f2 the flicker went");\n        Expect(jump <= 0.0186f + 1e-4f, "f3 a walking lamp keeps its flicker (no jump)");\n        Tracker blind{ParseParams("1", nullptr, nullptr)};\n        bool changed = false;\n        for (int f = 0; f < 60 * 4; ++f) {\n            const auto rec = Record(1.0f, 1.0f, -5.0f, 6.0f, 1.0f, 0.55f, 0.18f);\n            changed = changed || blind.Patch(rec.data(), 1, out.data(), nullptr);\n            blind.EndFrame(f / 60.0, Count);\n        }\n        Expect(!changed, "f4 nothing without a camera");\n        // a lamp the game flickers by its reach only (colour kept) is left alone too\n        Tracker reach{ParseParams("1", nullptr, nullptr)};\n        bool reach_changed = false;\n        for (int f = 0; f < 60 * 4; ++f) {\n            const float r = 6.0f * (1.0f + 0.03f * float(f % 5));\n            const auto rec = Record(1.0f, 1.0f, -5.0f, r, 1.0f, 0.55f, 0.18f);\n            reach_changed =\n                reach_changed || reach.Patch(rec.data(), 1, out.data(), Identity.data());\n            reach.EndFrame(f / 60.0, Count);\n        }\n        Expect(!reach_changed, "f5 a lamp whose reach the game changes is left alone");\n    }\n    // g. the fog gets the records the draw was bound to, once, and only for that draw\n    {\n        Tracker t{ParseParams("1", nullptr, nullptr)};\n        const auto rec = Record(1.0f, 1.0f, -5.0f, 6.0f, 1.0f, 0.55f, 0.18f);\n        const std::uint32_t* patched = nullptr;\n        for (int f = 0; f < 60 * 3 && patched == nullptr; ++f) {\n            patched = t.PatchDraw(rec.data(), rec.data(), 1, Identity.data());\n            t.EndFrame(f / 60.0, Count);\n        }\n        Expect(patched != nullptr, "g1 patched after the ramp");\n        const auto other = Record(9.0f, 1.0f, -5.0f, 6.0f, 1.0f, 0.55f, 0.18f);\n        Expect(t.FogRecords(other.data()) == other.data(), "g2 another draw: its own records");\n        Expect(t.FogRecords(rec.data()) == patched, "g3 the draw\'s fog: the patched records");\n        Expect(t.FogRecords(rec.data()) == rec.data(), "g4 once");\n        t.PatchDraw(rec.data(), rec.data(), 1, Identity.data());\n        t.Skipped(Skip::Stream);\n        Expect(t.FogRecords(rec.data()) == rec.data(), "g5 a draw left as it was: raw records");\n        Expect(!t.TooLarge(), "g6 copies allowed at first");\n        t.Skipped(Skip::Large);\n        Expect(t.TooLarge(), "g7 a binding too large to copy turns the flicker off");\n    }\n    // i. the luminance weights are those of the lamp shadow pass\'s own copy (LampTrack, the r42\n    // log and lampWeight\'s numbers; point_shadow_ray.comp\'s are checked by the patch script)\n    {\n        Vulkan::LampTrack track;\n        track.Begin(Identity.data());\n        const auto rec = Record(1.0f, 0.5f, -6.0f, 8.0f, 1.0f, 0.55f, 0.18f);\n        const int at = track.Add(rec.data());\n        Expect(at == 0 && std::abs(track.Lamp(std::uint32_t(at)).luma - LumaOf(rec.data())) <=\n                              1e-6f * LumaOf(rec.data()),\n               "i1 the luminance weights are LampTrack\'s");\n    }\n    // h. the periodic line comes every LineFrames frames\n    {\n        Tracker t{ParseParams("1", nullptr, "1")};\n        lines = 0;\n        for (std::uint32_t f = 0; f < LineFrames; ++f) {\n            t.EndFrame(f / 60.0, Count);\n        }\n        Expect(lines >= 1, "h1 a line after LineFrames frames");\n    }\n    if (failures == 0) {\n        std::printf("lamp-flicker-test: all checks passed\\n");\n    }\n    return failures == 0 ? 0 : 1;\n}\n',
}

BIND = """// bbport (r96_lamp-flicker-colour): BB_LAMP_FLICKER (lamp_flicker.h). For a light draw whose pixel
// stage reads `count` lamp records at `lights` (its buffer 1), after the draw's buffers are bound
// (BindResources) and before the pipeline writes its descriptors (after EffectsBeforeBind): when a
// lamp of the draw flickers this frame, buffer 1 is bound to a copy in the stream buffer of the
// binding's bytes with the records patched, at the same push offset, and the patched records are
// returned for the lamp shadow pass and the lamp fog. The bytes come from guest memory, which
// PointShadow::OnLightDraw and the lamp fog read for these records too; the constant ring is never
// read by the CPU (device memory mapped for sequential writes: a read of it is uncached and slow)
// nor written here. A ring binding is copied only when it is stage A's copy of exactly these
// bytes. Host writes only: no command is recorded, so no lamps-apart batch is ended. Null: the
// draw stays as the game made it (nothing flickers in it, or the binding is not one this copies:
// counted in the "Lamp flicker (r96)" line; one that would take more than MostCopyBytes turns the
// flicker off for the session).
const u32* Rasterizer::LampFlickerBind(const GraphicsPipeline* pipeline, const Shader::Info& ps,
                                       VAddr lights, u32 count) {
    auto& flicker = LampFlicker::Get();
    auto& dc = Dc();
    // Buffer bindings are numbered across the stages in GetStages() order (BindResources, and
    // Info::AddBindings for the shaders); dc.buffer_infos and the push offsets use those numbers.
    u32 index = 0;
    bool found = false;
    for (const auto* stage : pipeline->GetStages()) {
        if (stage == &ps) {
            found = true;
            break;
        }
        index += stage ? u32(stage->buffers.size()) : 0u;
    }
    ++index; // the records are the pixel stage's buffer 1
    const u64 bytes = u64(count) * 64;
    if (!found || ps.buffers.size() < 2 || ps.buffers[1].IsSpecial() ||
        index >= dc.buffer_infos.size() || index >= dc.push_data.buf_offsets.size()) {
        flicker.Skipped(LampFlicker::Skip::Binding);
        return nullptr;
    }
    auto& info = dc.buffer_infos[index];
    const u64 adjust = dc.push_data.buf_offsets[index];
    const u64 range = info.range;
    const u64 size = ps.buffers[1].GetSharp(ps).GetSize();
    if (!info.buffer || range == VK_WHOLE_SIZE || range < adjust + bytes || range > size + adjust) {
        flicker.Skipped(LampFlicker::Skip::Binding);
        return nullptr;
    }
    if (range > LampFlicker::MostCopyBytes || flicker.TooLarge()) {
        flicker.Skipped(LampFlicker::Skip::Large);
        return nullptr;
    }
    const RingBinding* ring = dc.num_ring_stages ? FindRingBinding(ps, 1) : nullptr;
    if (ring && (info.buffer != constant_ring->Handle() || info.offset != ring->offset ||
                 adjust != 0 || ring->address != lights || range > ring->size)) {
        flicker.Skipped(LampFlicker::Skip::Binding);
        return nullptr;
    }
    if (memory->ClampRangeSize(lights, range - adjust) != range - adjust ||
        buffer_cache.IsRegionGpuModified(lights, range - adjust)) {
        flicker.Skipped(LampFlicker::Skip::GpuWritten);
        return nullptr;
    }
    const auto camera = camera_motion->PassMatrices();
    const u32* patched =
        flicker.PatchDraw(reinterpret_cast<const void*>(lights), reinterpret_cast<const u32*>(lights),
                          count, camera.valid ? camera.inv_view.data() : nullptr);
    if (!patched) {
        return nullptr;
    }
    const u64 alignment =
        std::max<u64>(instance.UniformMinAlignment(), instance.StorageMinAlignment());
    auto& stream = buffer_cache.GetStreamBuffer();
    const auto [data, at] = stream.Map(range, alignment);
    if (!data) {
        flicker.Skipped(LampFlicker::Skip::Stream);
        return nullptr;
    }
    std::memset(data, 0, adjust);
    memory->CopySparseMemory(lights, data + adjust, range - adjust);
    std::memcpy(data + adjust, patched, bytes);
    stream.Commit();
    info.buffer = stream.Handle();
    info.offset = at;
    info.range = range;
    flicker.Bound();
    return patched;
}

"""

README_BLOCK = """### Lamp flicker (in development)

Candles, lanterns, torches and street gas lamps flicker gently, and their light warms as it dims. Off unless `BB_LAMP_FLICKER` is set above 0. These environment variables are read once, at the end of the first frame; text that does not begin with a number leaves the flicker off. The engine scales the colour of a lamp in the game's light draws, and the same way in the weights of the ray traced lamp shadows and in the lamp fog; nothing else is drawn. A lamp flickers when its colour is flame-coloured (red the strongest, green between 0.15 and 0.97 of red, blue at most 0.8 of red, a reach of at most 40 m) and the game kept its colour and reach unchanged for 1 s; the flicker then fades in over 1 s. A lamp whose colour or reach the game changes from frame to frame (the hunter's lantern flickers already) is left alone, and one that starts to change loses an added flicker within 0.2 s. A light draw whose lamp records would take more than 4096 bytes to copy turns the flicker off for the rest of the session. After the first 120 frames and then every 600 frames the log has a `Lamp flicker (r96):` line with the counts. Cost: no GPU pass; a light draw with a flickering lamp reads its lamp records from a copy in the stream buffer that the CPU writes from guest memory (an estimate of 0.2 to 1 ms of render thread time a frame with 600 to 1,500 light draws, not measured).

| Variable | What it does | Default |
|---|---|---|
| `BB_LAMP_FLICKER` | Strength, 0 to 1: the light of a flickering lamp moves between 1 - 0.14 times the strength and 1 + 0.14 times the strength of the game's, as three slow waves (0.37, 1.13 and 2.71 Hz, each up to 15% faster or slower for each lamp, with phases of its own); 0 or not set is off | off |
| `BB_LAMP_FLICKER_TEMP` | Colour shift, 0 to 1: at light factor f the red, green and blue of a lamp are multiplied by f^(1 - 0.6 T), f^(1 + 0.35 T) and f^(1 + 1.1 T), then all three by the one number that keeps its luminance at f times the game's; 0 keeps the colour | `0.6` |
| `BB_LAMP_FLICKER_SHOW` | Debug only: `1` makes the flicker three times as strong (at most 0.6) with twice the colour shift, and prints the nearest flame lamps every 120 frames (`Lamp flicker (r96 show):`) | off |

"""

# Each edit: ("after", anchor, block) inserts block after anchor; ("before", anchor, block) before
# it; ("replace", old, new). Texts use LF here; the file's own line ends are kept.
EDITS = {
    EFF: [
        ("after", '#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)\n',
         '#include "video_core/renderer_vulkan/lamp_flicker.h" // bbport (r96_lamp-flicker-colour)\n'),
        ("replace",
         "           EffectShaders::GtaoActive() || EffectShaders::SsrActive();\n}\n",
         "           EffectShaders::GtaoActive() || EffectShaders::SsrActive() ||\n"
         "           LampFlicker::On(); // bbport (r96_lamp-flicker-colour): its light draws are looked at\n}\n"),
        ("after", "    ssr_temporal->OnFrameEnd();\n",
         "    LampFlicker::FrameEnd(BbReport::Printf); // bbport (r96_lamp-flicker-colour): BB_LAMP_FLICKER only\n"),
        ("before", "void Rasterizer::EffectsBeforeBind(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline,\n",
         BIND),
        ("before", "                point_shadow->OnLightDraw(cb_descs[0].first, cb_descs[1].first,\n",
         "                // bbport (r96_lamp-flicker-colour): BB_LAMP_FLICKER only (off: one bool test)\n"
         "                const u32* flickered =\n"
         "                    LampFlicker::On() ? LampFlickerBind(pipeline, ps, lights, tile_lights) : nullptr;\n"),
        ("replace", "                                           .lights = reinterpret_cast<const u32*>(lights),\n",
         "                                           .lights = flickered ? flickered\n"
         "                                                               : reinterpret_cast<const u32*>(lights),\n"),
        ("replace",
         "            volumetric_light->AddPointLights(reinterpret_cast<const u32*>(constants),\n"
         "                                             reinterpret_cast<const u32*>(lights), count);\n",
         "            volumetric_light->AddPointLights(reinterpret_cast<const u32*>(constants),\n"
         "                                             // bbport (r96_lamp-flicker-colour): as drawn\n"
         "                                             LampFlicker::Fog(reinterpret_cast<const u32*>(lights)),\n"
         "                                             count);\n"),
    ],
    RH: [
        ("after",
         "    void EffectsBeforeBind(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline, bool is_indexed,\n"
         "                           u32 index_offset, u32 first_vertex);\n",
         "    /// bbport (r96_lamp-flicker-colour): BB_LAMP_FLICKER: a light draw's records with its flame\n"
         "    /// lamps flickered, its buffer 1 bound to them (null: the draw is left as it is).\n"
         "    const u32* LampFlickerBind(const GraphicsPipeline* pipeline, const Shader::Info& ps,\n"
         "                               VAddr lights, u32 count);\n"),
    ],
    CM: [
        ("after", "target_include_directories(lamp-fog-shafts-test PRIVATE ..)\n",
         "# bbport (r96_lamp-flicker-colour): the lamp flicker's knobs, wave, colour gains, flame test and\n"
         "# tracker (lamp_flicker.h); also built and run by engine/build.sh --test.\n"
         "add_executable(lamp-flicker-test EXCLUDE_FROM_ALL ../tests/test_lamp_flicker.cpp)\n"
         "target_compile_options(lamp-flicker-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
         "target_include_directories(lamp-flicker-test PRIVATE ..)\n"),
    ],
    BS: [
        ("after", "    out/wind-test\n",
         "    # bbport (r96_lamp-flicker-colour): the lamp flicker's knobs, wave, colour gains and tracker\n"
         '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror "${threads[@]}" -I. tests/test_lamp_flicker.cpp -o out/lamp-flicker-test\n'
         "    out/lamp-flicker-test\n"),
    ],
    RM: [
        ("before", "### Lamp fog shafts\n", README_BLOCK),
    ],
}

# README numbers tied to the header's constants (rule 10: defaults written twice).
TIES = [("inline constexpr float Swing = 0.14f;", "0.14 times the strength"),
        ("inline constexpr float DefaultTemp = 0.6f;", "| `BB_LAMP_FLICKER_TEMP` |"),
        ("inline constexpr float DefaultTemp = 0.6f;", "| `0.6` |"),
        ("inline constexpr float MaxReach = 40.0f;", "a reach of at most 40 m"),
        ("inline constexpr double SteadySeconds = 1.0;", "unchanged for 1 s"),
        ("inline constexpr std::uint64_t MostCopyBytes = 4096;", "more than 4096 bytes"),
        ("inline constexpr double RampIn = 1.0;", "fades in over 1 s"),
        ("inline constexpr double RampOut = 0.2;", "within 0.2 s"),
        ("inline constexpr std::uint32_t LineFrames = 600;", "then every 600 frames"),
        ("inline constexpr std::uint32_t FirstLineFrames = 120;", "After the first 120 frames"),
        ("inline constexpr std::uint32_t ShowFrames = 120;", "every 120 frames"),
        ("inline constexpr float ShowScale = 3.0f;", "three times as strong"),
        ("inline constexpr float MaxSwing = 0.6f;", "(at most 0.6)"),
        ("inline constexpr float ShowTempScale = 2.0f;", "twice the colour shift"),
        ("inline constexpr std::array<float, 3> TempK{-0.6f, 0.35f, 1.1f};", "f^(1 - 0.6 T), f^(1 + 0.35 T) and f^(1 + 1.1 T)"),
        ("inline constexpr std::array<double, 3> WaveHz{0.37, 1.13, 2.71};", "(0.37, 1.13 and 2.71 Hz"),
        ("return c[1] >= 0.15f * c[0] && c[1] <= 0.97f * c[0] && c[2] >= 0.0f && c[2] <= 0.8f * c[0];",
         "green between 0.15 and 0.97 of red, blue at most 0.8 of red")]

# Order checks on the patched result: each string after the one before it (first occurrence).
ORDER = {
    EFF: ['#include "video_core/renderer_vulkan/lamp_flicker.h"', "LampFlicker::On(); // bbport (r96",
          "void Rasterizer::EffectsOnFrameEnd()", "LampFlicker::FrameEnd(BbReport::Printf);",
          "const u32* Rasterizer::LampFlickerBind(", "void Rasterizer::EffectsBeforeBind(",
          "const u32* flickered =", "point_shadow->OnLightDraw(cb_descs[0].first",
          ".lights = flickered ? flickered", "void Rasterizer::EffectsAfterDraw(",
          "LampFlicker::Fog(reinterpret_cast<const u32*>(lights))"],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def marker(kind, a, b):
    """The text this edit leaves in the file."""
    return b if kind == "replace" else (a + b if kind == "after" else b + a)


def edit_state(text, kind, a, b):
    if kind == "replace":
        if text.count(b) == 1 and text.count(a) == 0:
            return "applied"
        if text.count(a) == 1 and text.count(b) == 0:
            return "clean"
        return "broken (old %d, new %d)" % (text.count(a), text.count(b))
    if text.count(b) == 1:
        return "applied"
    if text.count(b) == 0 and text.count(a) == 1:
        return "clean"
    return "broken (anchor %d, block %d)" % (text.count(a), text.count(b))


def do(text, kind, a, b):
    if kind == "replace":
        return text.replace(a, b)
    return text.replace(a, marker(kind, a, b))


def undo(text, kind, a, b):
    if kind == "replace":
        return text.replace(b, a)
    return text.replace(b, "", 1)


def text_checks(texts):
    header = NEW[R + "lamp_flicker.h"]
    readme = texts[RM]
    at = readme.find("### Lamp flicker (in development)")
    section = readme[at:readme.find("### Lamp fog shafts", at)] if at >= 0 else ""
    for const, words in TIES:
        if header.count(const) != 1 or words not in section:
            raise SystemExit("tie check: %r against README text %r" % (const, words))
    for path, items in ORDER.items():
        pos = -1
        for s in items:
            i = texts[path].find(s, pos + 1)
            if i < 0:
                raise SystemExit("order check: %s: %r not after the one before" % (path, s))
            pos = i
    # Rule 10 (lists that must agree): the shader's lampWeight weighs the record colour with the
    # header's Luma (the C++ copy in LampTrack is tied by the unit test, check i1).
    comp = os.path.join(ROOT, "engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp")
    if ("dot(col, vec3(0.299, 0.587, 0.114))" not in open(comp, encoding="utf-8").read() or
            "Luma{0.299f, 0.587f, 0.114f}" not in header):
        raise SystemExit("tie check: point_shadow_ray.comp lampWeight and LampFlicker::Luma differ")
    for path, text in NEW.items():
        if not all(ord(c) < 128 for c in text) or "\r" in text:
            raise SystemExit("%s: new text must be ASCII with LF in the script" % path)
    if not all(ord(c) < 128 for c in README_BLOCK + BIND):
        raise SystemExit("inserted text must be ASCII")


def new_bytes(text):
    return text.replace("\n", "\r\n").encode("utf-8")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R96_ROOT)" % ROOT)
    plan, states = [], set()
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        st = [edit_state(cur, *e) for e in edits]
        for e, s in zip(edits, st):
            if s.startswith("broken"):
                raise SystemExit("REFUSED %s: %s at %r" % (path, s, e[1][:70]))
        states |= set(st)
        plan.append((path, edits, raw, eol, cur))
    for path, text in NEW.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            states.add("clean")
        elif open(full, "rb").read() == new_bytes(text):
            states.add("applied")
        else:
            raise SystemExit("REFUSED %s exists and is not this patch's file" % path)
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: some edits applied, some not")
    state = states.pop()
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            texts = {}
            for path, edits, raw, eol, cur in plan:
                for e in edits:
                    cur = do(cur, *e)
                texts[path] = cur
            text_checks(texts)
            print("not applied; would apply (%d files edited, %d new; every anchor found once; "
                  "text checks on the result pass)" % (len(plan), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts, outs = {}, []
        for path, edits, raw, eol, cur in plan:
            for e in edits:
                cur = do(cur, *e)
            texts[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        for path, text in NEW.items():
            outs.append((path, new_bytes(text), None))
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r96tmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(ROOT, path))
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r96tmp"
                if os.path.exists(tmp):
                    os.remove(tmp)
            for path, raw in written:
                if raw is None:
                    os.remove(os.path.join(ROOT, path))
                else:
                    open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    for path, edits, raw, eol, cur in plan:
        for e in reversed(edits):
            cur = undo(cur, *e)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
