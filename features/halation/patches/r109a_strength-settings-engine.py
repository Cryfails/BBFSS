# r109a_strength-settings-engine: FEATURE patch (the engine half of r109; the menu rows, the eight
# translation tables, the launchers, IniFile defaults and the look knob lists are r109b, written on
# top of this one). Owner, 2026-11-15 22:10, verbatim: "The default halation should be strength 1 but
# should have a slider to adjust the strength. I think the same for light flicker as well, default to
# off on already flickering lamps but then we can turn it on with a strength slider".
#
# What it does:
#  - Three lantern.ini keys (bbport_settings.h/.cpp: Min/Max/Default constants, std::atomic<float>
#    members, Set with a clamp and an isfinite fallback, Save with two decimals), live:
#      graphics_halation_strength              0..2, default 1 (HalationStrengthDefault)
#      graphics_lamp_flicker_strength          0..1, default 1 (LampFlickerSteadyDefault, one constant)
#      graphics_lamp_flicker_on_game_strength  0..1, default 0 (LampFlickerOnGameDefault)
#    A missing key is the default (Load leaves a key it does not find at the member's initializer).
#  - Halation: the strength is read each frame (Halation::Strength: BB_HALATION when set and not
#    empty, read once, by r95's rule; else the setting). The Halation object is made at the first
#    frame whose strength is above 0 (EffectsBeforeUpscaler; before, only when Halation::Wanted() held
#    at the rasterizer's start) and kept; at 0 nothing is drawn. Radius, threshold and the test view
#    stay environment-only, read once (HalationParams::Load, now first called when the object is made).
#  - Lamp flicker: the two strengths are resolved at every frame end for the next frame
#    (LampFlicker::Update, called right before AnyWanted asks LampFlicker::On()); BB_LAMP_FLICKER and
#    BB_LAMP_FLICKER_ON_GAME (a number 0..1; "1" as before) win when set. A steady lamp flickers at the
#    steady strength exactly as r96 did (same statements on the same values when the lamp has no
#    on-game share). A lamp the game changes (r96's GameChanges rule, unchanged) gets, with the
#    on-game strength above 0, a share of its own (game_amount, in over RampIn while the game changes
#    it, out over RampOut once the game has kept it steady for SteadySeconds, when the steady share
#    fades in as for any steady lamp): f = 1 + (A(steady) * amount + A(on_game) * game_amount) * Wave.
#    At on-game strength 0 game_amount stays exactly 0, so such a lamp takes today's left-alone path
#    and its records stay bit for bit as the game made them. This replaces r96b's static bool (which
#    made every lamp count as steady, so new lamps flickered at once): this script applies on the tree
#    with r96b applied, and r96b's revert REFUSES until this one is reverted (revert this one first).
#    The 1 s steady rule, the ramps, the state names and the 4096-byte session cut-off stay.
#  - Log: "Halation (r109a): strength S from the setting|environment (key or variable)" and "Lamp
#    flicker (r109a): steady ... strength S from the ..., ... the game changes itself ... strength S
#    from the ..." at the first frame end, again after a change at most once every 600 frames
#    (StrengthKnob::Line), also when a strength is 0. The 600-frame lines of r95 and r96 stay (counters).
#
# Default ON now (the owner's decision), so the cost reaches every player: halation an estimated
# 0.05-0.1 ms GPU at 1080p internal (about 4x at 2160p), 2.1 MB; flicker an estimated 0.2-1 ms of
# render thread CPU a frame; neither measured. At strength 0 (both flicker strengths 0): no Halation
# object, pipeline, image or pass (one relaxed atomic load at the trigger dispatch and one at the frame
# end); LampFlicker::On() false (one relaxed atomic load per light draw), nothing of the flicker runs.
#
# New file: renderer_vulkan/strength_knob.h (pure: Env/ReadEnv, Value/Pick, Line). Edited:
# bbport_settings.h/.cpp, halation_params.h, vk_halation.h/.cpp, vk_rasterizer.cpp (the start-time
# make removed), vk_rasterizer.h (a comment), vk_rasterizer_effects.cpp (the lazy make + Apply's
# strength, the strength line, Update before AnyWanted, a comment), lamp_flicker.h, tests
# test_settings.cpp, test_halation.cpp, test_lamp_flicker.cpp (all three already in build.sh --test
# and CMake), README.md (rows and the sections' text).
#
# REVIEWED COPY (r109a_strength-settings-engine.fixed.py, 2026-11-15 adversarial review). Apply THIS
# one, not the draft. Where the draft (r109a_strength-settings-engine.py) is applied, revert it first
# (python -I -X utf8 r109a_strength-settings-engine.py revert; r109b on top must be reverted before
# that), then apply this one; this script refuses on a tree that holds the draft and says so.
# Changes against the draft:
#  - Halation: a pass after more than KeyStaleFrames (30) frame ends without one (the strength was 0
#    for a while, or menu previews) clears both key slots as the first pass does
#    (HalationParams::ClearsKey; Halation counts its frame ends). The draft keyed that pass with the
#    key of the last pass, from a scene possibly long gone: a frame whose threshold came from a dark
#    room drew a near full-screen orange flash when the slider went 0 -> 1 outdoors. Now that one
#    frame has no glow, as the very first frame. Unit test h7-h9.
#  - Lamp flicker: when a strength goes above 0 again after frame ends with both at 0, the tracker
#    forgets its lamps (Tracker::SetStrengths(..., resumed)), so every lamp starts as a new one: it
#    waits SteadySeconds and fades in over RampIn. The draft kept each lamp's amount while off (no
#    lamp was looked at), so steady lamps jumped to the full swing in one frame and lamps the game
#    changes counted as steady for a frame. Unit test j15.
#  - README: "text that does not begin with a number counts as 0" was said of all the flicker's
#    variables, but BB_LAMP_FLICKER_TEMP then takes 0.6; the two new rules are written down.
#  - Backups in r109a_fixed_backup (the draft's r109a_backup is left alone).
#
# Use: python -I -X utf8 r109a_strength-settings-engine.fixed.py check | apply | revert
# Root: R109A_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in
# r109a_fixed_backup next to this script. Each edit replaces an old text found exactly once with a new one
# (an insertion keeps its anchor whole inside the new text); revert puts each old text back where its
# new text is found exactly once; the new file is removed.
import os, sys

ROOT = os.environ.get("R109A_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r109a_fixed_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
SH = "engine/gpu/shim/"
TS = "engine/tests/"

NEW_FILES = {}
NEW_FILES[RV + "strength_knob.h"] = r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r109a_strength-settings-engine): a feature's strength that is a lantern.ini setting (the
// renderer reads it every frame, so a slider acts at once) and that an environment variable
// overrides for tests (read once by the caller). Used by the halation (graphics_halation_strength,
// BB_HALATION) and the lamp flicker (graphics_lamp_flicker_strength, BB_LAMP_FLICKER;
// graphics_lamp_flicker_on_game_strength, BB_LAMP_FLICKER_ON_GAME). Pure: the unit tests build it
// alone (tests/test_halation.cpp, tests/test_lamp_flicker.cpp).

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>

namespace StrengthKnob {

/// An environment variable's text as a strength.
struct Env {
    bool set = false;   ///< not null and not empty: it decides, whatever the setting says
    float value = 0.0f; ///< 0..max; a text that does not begin with a number, or whose number is
                        ///< not finite or not above 0, is 0
};

inline Env ReadEnv(const char* text, float max) {
    Env env;
    if (text == nullptr || text[0] == '\0') {
        return env;
    }
    env.set = true;
    char* end = nullptr;
    const float v = std::strtof(text, &end);
    env.value = end != text && std::isfinite(v) && v > 0.0f ? std::min(v, max) : 0.0f;
    return env;
}

/// A strength and where it came from.
struct Value {
    float value = 0.0f;
    bool from_env = false;
};

/// The variable's strength when it is set, else the setting's clamped to 0..max (a setting that is
/// not finite: `fallback`, the setting's default).
inline Value Pick(const Env& env, float setting, float max, float fallback) {
    if (env.set) {
        return {env.value, true};
    }
    return {std::clamp(std::isfinite(setting) ? setting : fallback, 0.0f, max), false};
}

/// "environment" or "setting".
inline const char* SourceName(const Value& v) {
    return v.from_env ? "environment" : "setting";
}

/// When a feature's strength line is due. Due is called once a frame with the frame's strengths
/// (one or two): true at the first call, then when a value or its source differs from those of the
/// last line and at least `every` calls have passed since that line (so a slider being dragged
/// gives one line, with the value it stopped at, at most `every` frames after the last one).
class Line {
public:
    bool Due(std::uint32_t every, const Value& a, const Value& b = {}) {
        if (since < every) {
            ++since;
        }
        const bool same = said && Same(a, last_a) && Same(b, last_b);
        if (same || (said && since < every)) {
            return false;
        }
        said = true;
        last_a = a;
        last_b = b;
        since = 0;
        return true;
    }

private:
    static bool Same(const Value& x, const Value& y) {
        return x.value == y.value && x.from_env == y.from_env;
    }

    Value last_a{}, last_b{};
    std::uint32_t since = 0;
    bool said = false;
};

} // namespace StrengthKnob
'''

# (path, old, new, block). A replacement (block None): old found exactly once is replaced by new
# (apply); new found exactly once is replaced by old (revert). An insertion: block goes right after
# or before its anchor (old, found exactly once, kept whole; new = the two together at apply);
# revert takes the block out where it is found by itself (exactly once), so lines another patch
# put between it and its anchor stay. Texts here are LF; files keep their own line ends.
EDITS = []


def E(path, old, new):
    EDITS.append((path, old, new, None))


def INS_AFTER(path, anchor, block):
    EDITS.append((path, anchor, anchor + block, block))


def INS_BEFORE(path, anchor, block):
    EDITS.append((path, anchor, block + anchor, block))


# ---- bbport_settings.h: constants and members
INS_AFTER(SH + "bbport_settings.h",
    "inline constexpr float LocalLightCoreMin = 0.0f, LocalLightCoreMax = 0.35f, LocalLightCoreDefault = 0.05f;\n",
    "// bbport (r109a_strength-settings-engine): the halation's and the lamp flicker's strengths (live;\n"
    "// a set BB_HALATION, BB_LAMP_FLICKER or BB_LAMP_FLICKER_ON_GAME wins). Tied to HalationParams and\n"
    "// LampFlicker by static_asserts in vk_halation.cpp and vk_rasterizer_effects.cpp.\n"
    "inline constexpr float HalationStrengthMin = 0.0f, HalationStrengthMax = 2.0f, HalationStrengthDefault = 1.0f;\n"
    "inline constexpr float LampFlickerStrengthMin = 0.0f, LampFlickerStrengthMax = 1.0f;\n"
    "inline constexpr float LampFlickerSteadyDefault = 1.0f, LampFlickerOnGameDefault = 0.0f;\n")
INS_AFTER(SH + "bbport_settings.h",
    "    std::atomic<const char*> drawn_look_problem{nullptr};\n",
    "    // bbport (r109a_strength-settings-engine): live, the renderer reads them every frame; a set\n"
    "    // BB_HALATION, BB_LAMP_FLICKER or BB_LAMP_FLICKER_ON_GAME wins over its key.\n"
    "    std::atomic<float> graphics_halation_strength{HalationStrengthDefault}; // 0..2; 0: nothing drawn\n"
    "    std::atomic<float> graphics_lamp_flicker_strength{LampFlickerSteadyDefault}; // 0..1, flame lamps the game keeps steady\n"
    "    std::atomic<float> graphics_lamp_flicker_on_game_strength{LampFlickerOnGameDefault}; // 0..1, flame lamps the game changes; 0: left alone\n")

# ---- bbport_settings.cpp: Set and Save
INS_AFTER(SH + "bbport_settings.cpp",
    "    } else if (key == \"graphics_drawn_look_debug\") {\n"
    "        v.graphics_drawn_look_debug = std::clamp(i, 0, DrawnLookDebugMax);\n",
    "    } else if (key == \"graphics_halation_strength\") { // bbport (r109a_strength-settings-engine)\n"
    "        v.graphics_halation_strength =\n"
    "            Clamp(std::isfinite(f) ? f : HalationStrengthDefault, HalationStrengthMin, HalationStrengthMax);\n"
    "    } else if (key == \"graphics_lamp_flicker_strength\") {\n"
    "        v.graphics_lamp_flicker_strength =\n"
    "            Clamp(std::isfinite(f) ? f : LampFlickerSteadyDefault, LampFlickerStrengthMin, LampFlickerStrengthMax);\n"
    "    } else if (key == \"graphics_lamp_flicker_on_game_strength\") {\n"
    "        v.graphics_lamp_flicker_on_game_strength =\n"
    "            Clamp(std::isfinite(f) ? f : LampFlickerOnGameDefault, LampFlickerStrengthMin, LampFlickerStrengthMax);\n")
INS_AFTER(SH + "bbport_settings.cpp",
    "    put(\"graphics_drawn_look_debug\",\n"
    "        std::to_string(std::clamp(v.graphics_drawn_look_debug.load(), 0, DrawnLookDebugMax)));\n",
    "    put(\"graphics_halation_strength\", fixed(v.graphics_halation_strength, 2)); // bbport (r109a)\n"
    "    put(\"graphics_lamp_flicker_strength\", fixed(v.graphics_lamp_flicker_strength, 2));\n"
    "    put(\"graphics_lamp_flicker_on_game_strength\", fixed(v.graphics_lamp_flicker_on_game_strength, 2));\n")

# ---- halation_params.h
E(RV + "halation_params.h",
    "// Knobs (environment, read once at the first use; Load):\n"
    "//   BB_HALATION            strength 0..2; unset, empty, 0, a negative or non-numeric text: off\n"
    "//                          (the rasterizer makes no Halation: no pipeline, image, buffer or pass)\n",
    "// The strength a frame uses (bbport r109a_strength-settings-engine; StrengthOf): BB_HALATION when\n"
    "// it is set and not empty (read once; a text that is not a number above 0 is 0, more than 2 is 2),\n"
    "// else the setting graphics_halation_strength (0..2, DefaultStrength 1, read every frame). At 0\n"
    "// nothing is drawn; the rasterizer makes its Halation at the first frame above 0 and keeps it.\n"
    "// Knobs (environment, read once at the first use; Load):\n"
    "//   BB_HALATION            Knobs::strength by the same rule (the frame's strength replaces it)\n")
INS_AFTER(RV + "halation_params.h",
    "#include \"../host_shaders/halation_layout.h\"\n",
    "#include \"strength_knob.h\" // bbport (r109a_strength-settings-engine)\n")
INS_AFTER(RV + "halation_params.h",
    "inline constexpr float MaxStrength = 2.0f;\n",
    "/// bbport (r109a_strength-settings-engine): graphics_halation_strength's default (tied to\n"
    "/// BbSettings::HalationStrengthDefault by a static_assert in vk_halation.cpp).\n"
    "inline constexpr float DefaultStrength = 1.0f;\n")
INS_BEFORE(RV + "halation_params.h",
    "/// The quarter image's side for a scene side (a texel per 4x4 pixels, the last one partial).\n",
    "/// bbport (r109a_strength-settings-engine): the strength a frame uses: BB_HALATION's (`env`,\n"
    "/// StrengthKnob::ReadEnv(BB_HALATION's text, MaxStrength), read once by the caller) when it is\n"
    "/// set, else `setting` (graphics_halation_strength) clamped to 0..MaxStrength (not finite:\n"
    "/// DefaultStrength).\n"
    "inline StrengthKnob::Value StrengthOf(const StrengthKnob::Env& env, float setting) {\n"
    "    return StrengthKnob::Pick(env, setting, MaxStrength, DefaultStrength);\n"
    "}\n"
    "\n"
    "/// bbport (r109a_strength-settings-engine): a pass clears both key slots, as the first one does,\n"
    "/// when it is the first (`runs` 0) or when more than KeyStaleFrames frame ends went by since the\n"
    "/// last pass (`frame_ends` now, `ran_at_end` then; the strength was 0, or menu previews): the\n"
    "/// frame before's key would be that of a scene long gone, so that frame draws no glow instead.\n"
    "inline constexpr std::uint64_t KeyStaleFrames = 30;\n"
    "inline constexpr bool ClearsKey(std::uint64_t runs, std::uint64_t frame_ends,\n"
    "                                std::uint64_t ran_at_end) {\n"
    "    return runs == 0 || frame_ends - ran_at_end > KeyStaleFrames;\n"
    "}\n"
    "\n")

# ---- vk_halation.h
E(RV + "vk_halation.h",
    "// Off (BB_HALATION unset or 0): the rasterizer makes no Halation (Wanted), so nothing of this is\n"
    "// made or run; the frame is as before, bit for bit. On: the pipeline, the sampler and two small\n"
    "// buffers are made at the first frame it runs; two quarter-size RGBA16F images (2.1 MB at a\n"
    "// 1920x1080 scene) are made then and anew when the scene's size changes.\n",
    "// The strength (bbport r109a_strength-settings-engine): Strength(), read every frame (the setting\n"
    "// graphics_halation_strength, or BB_HALATION when it is set; halation_params.h, StrengthOf). At 0\n"
    "// nothing is drawn. Until the first frame above 0 the rasterizer makes no Halation, so nothing of\n"
    "// this is made or run and the frame is as before, bit for bit. At that frame the rasterizer makes\n"
    "// it and keeps it, also when the strength goes back to 0: the pipeline, the sampler and two small\n"
    "// buffers are made then; two quarter-size RGBA16F images (2.1 MB at a 1920x1080 scene) are made\n"
    "// then and anew when the scene's size changes.\n")
E(RV + "vk_halation.h",
    "    /// BB_HALATION names a strength above 0 (HalationParams::Load, read once).\n"
    "    [[nodiscard]] static bool Wanted();\n",
    "    /// bbport (r109a_strength-settings-engine): this frame's strength and its source: BB_HALATION\n"
    "    /// when it is set (read once), else the setting graphics_halation_strength (read each call).\n"
    "    [[nodiscard]] static StrengthKnob::Value Strength();\n"
    "    /// Each frame end: the \"Halation (r109a):\" line with the strength and its source, at the\n"
    "    /// first frame and after a change (at most once every LineFrames frames).\n"
    "    static void StrengthLine();\n")
E(RV + "vk_halation.h",
    "    /// The upscaler's trigger: the glow into the scene colour `color` (once a frame).\n"
    "    void Apply(VideoCore::ImageId color);\n",
    "    /// The upscaler's trigger: the glow at `strength` (above 0, at most\n"
    "    /// HalationParams::MaxStrength) into the scene colour `color` (once a frame).\n"
    "    void Apply(VideoCore::ImageId color, float strength);\n")
INS_AFTER(RV + "vk_halation.h",
    "    u64 runs = 0;         ///< passes recorded; the key slot is runs & 1\n",
    "    u64 frame_ends = 0;   ///< bbport (r109a): OnFrameEnd calls (HalationParams::ClearsKey)\n"
    "    u64 ran_at_end = 0;   ///< bbport (r109a): frame_ends at the last pass\n")

# ---- vk_halation.cpp
INS_AFTER(RV + "vk_halation.cpp",
    "#include \"bbport_toggles.h\"\n",
    "#include \"bbport_settings.h\" // bbport (r109a_strength-settings-engine)\n")
E(RV + "vk_halation.cpp",
    "bool Halation::Wanted() {\n"
    "    return HP::Load().strength > 0.0f;\n"
    "}\n",
    "// bbport (r109a_strength-settings-engine): the setting's numbers are the header's (one default).\n"
    "static_assert(BbSettings::HalationStrengthDefault == HP::DefaultStrength &&\n"
    "              BbSettings::HalationStrengthMax == HP::MaxStrength &&\n"
    "              BbSettings::HalationStrengthMin == 0.0f);\n"
    "\n"
    "StrengthKnob::Value Halation::Strength() {\n"
    "    static const StrengthKnob::Env env =\n"
    "        StrengthKnob::ReadEnv(std::getenv(\"BB_HALATION\"), HP::MaxStrength);\n"
    "    return HP::StrengthOf(\n"
    "        env, BbSettings::Get().graphics_halation_strength.load(std::memory_order_relaxed));\n"
    "}\n"
    "\n"
    "void Halation::StrengthLine() {\n"
    "    static StrengthKnob::Line line;\n"
    "    const StrengthKnob::Value s = Strength();\n"
    "    if (line.Due(LineFrames, s)) {\n"
    "        BbReport::Printf(\"Halation (r109a): strength %.2f from the %s (%s)%s\\n\", double(s.value),\n"
    "                         StrengthKnob::SourceName(s),\n"
    "                         s.from_env ? \"BB_HALATION\" : \"graphics_halation_strength\",\n"
    "                         s.value > 0.0f ? \"\" : \"; 0: nothing is drawn\");\n"
    "    }\n"
    "}\n")
E(RV + "vk_halation.cpp",
    "    const auto& k = HP::Load();\n"
    "    BbReport::Printf(\"Halation (r95, BB_HALATION=%.2f): radius %.2f (a blur of sigma %.1f pixels \"\n"
    "                     \"at 1080 lines), threshold %.2f stops over the frame's key, glow gain %.3f, \"\n"
    "                     \"show %u; on the scene before the upscaler, at its render size\\n\",\n"
    "                     double(k.strength), double(k.radius), double(HP::SigmaAt1080 * k.radius),\n"
    "                     double(HP::ThresholdStops(k)), double(HP::GainOf(k)), k.show);\n",
    "    // bbport (r109a_strength-settings-engine): the strength comes with each frame (Apply); the\n"
    "    // line gives the gain at strength 1.\n"
    "    HP::Knobs k = HP::Load();\n"
    "    k.strength = 1.0f;\n"
    "    BbReport::Printf(\"Halation (r95): made at the first frame with a strength above 0, kept from \"\n"
    "                     \"now on: radius %.2f (a blur of sigma %.1f pixels at 1080 lines), threshold \"\n"
    "                     \"%.2f stops over the frame's key, glow gain %.3f at strength 1, show %u; on \"\n"
    "                     \"the scene before the upscaler, at its render size\\n\",\n"
    "                     double(k.radius), double(HP::SigmaAt1080 * k.radius),\n"
    "                     double(HP::ThresholdStops(k)), double(HP::GainOf(k)), k.show);\n")
E(RV + "vk_halation.cpp",
    "void Halation::Apply(VideoCore::ImageId color_id) {\n",
    "void Halation::Apply(VideoCore::ImageId color_id, float strength) {\n")
E(RV + "vk_halation.cpp",
    "    const auto& k = HP::Load();\n"
    "    const u32 slot = u32(runs & 1);\n"
    "    const bool first = runs == 0;\n",
    "    HP::Knobs k = HP::Load();\n"
    "    k.strength = strength; // bbport (r109a_strength-settings-engine): this frame's\n"
    "    const u32 slot = u32(runs & 1);\n"
    "    // bbport (r109a): also after a long gap (strength 0, menu previews) both slots are cleared\n"
    "    const bool first = HP::ClearsKey(runs, frame_ends, ran_at_end);\n"
    "    ran_at_end = frame_ends;\n")
E(RV + "vk_halation.cpp",
    "void Halation::OnFrameEnd() {\n"
    "    applied = false;\n",
    "void Halation::OnFrameEnd() {\n"
    "    applied = false;\n"
    "    ++frame_ends; // bbport (r109a_strength-settings-engine): HalationParams::ClearsKey\n")

# ---- vk_rasterizer.h (comment only)
E(RV + "vk_rasterizer.h",
    "    /// bbport (r95_halation): made only with BB_HALATION above 0 (Halation::Wanted), else null.\n",
    "    /// bbport (r95_halation, r109a): null until the first frame with a strength above 0\n"
    "    /// (Halation::Strength), then made (EffectsBeforeUpscaler) and kept.\n")

# ---- vk_rasterizer.cpp: no start-time make
E(RV + "vk_rasterizer.cpp",
    "    // bbport (r95_halation): BB_HALATION above 0 only (Halation::Wanted, read once); otherwise\n"
    "    // no Halation is made and nothing of it runs. Its pipeline, buffers and images are made at\n"
    "    // the first frame it runs (EffectsBeforeUpscaler); without the upscaler it has no place.\n"
    "    if (Halation::Wanted()) {\n"
    "        halation = std::make_unique<Halation>(instance, scheduler, texture_cache, runtime,\n"
    "                                              *scene_targets, *camera_motion,\n"
    "                                              upscaler->Enabled());\n"
    "    }\n",
    "    // bbport (r95_halation, r109a_strength-settings-engine): no Halation is made here; it is made\n"
    "    // at the first frame whose strength is above 0 (EffectsBeforeUpscaler) and kept. Its\n"
    "    // pipeline, buffers and images are made at that frame; without the upscaler it has no place.\n")

# ---- vk_rasterizer_effects.cpp
E(RV + "vk_rasterizer_effects.cpp",
    "    // bbport (r95_halation): BB_HALATION above 0: the film halation into the scene colour, after\n"
    "    // the drawn look and the fog; the HUD is drawn later, on the upscaler's output.\n"
    "    if (halation && compute_hash == upscaler->TriggerHash()) {\n"
    "        halation->Apply(upscaler->SceneColor());\n"
    "    }\n",
    "    // bbport (r95_halation, r109a_strength-settings-engine): the film halation into the scene\n"
    "    // colour at this frame's strength (Halation::Strength: the setting, or BB_HALATION when set),\n"
    "    // after the drawn look and the fog; the HUD is drawn later, on the upscaler's output. At 0\n"
    "    // nothing is drawn; the Halation is made at the first frame above 0 and kept.\n"
    "    if (compute_hash == upscaler->TriggerHash()) {\n"
    "        if (const float strength = Halation::Strength().value; strength > 0.0f) {\n"
    "            if (!halation) {\n"
    "                halation = std::make_unique<Halation>(instance, scheduler, texture_cache, runtime,\n"
    "                                                      *scene_targets, *camera_motion,\n"
    "                                                      upscaler->Enabled());\n"
    "            }\n"
    "            halation->Apply(upscaler->SceneColor(), strength);\n"
    "        }\n"
    "    }\n")
INS_BEFORE(RV + "vk_rasterizer_effects.cpp",
    "    if (halation) { // bbport (r95_halation)\n"
    "        halation->OnFrameEnd();\n",
    "    Halation::StrengthLine(); // bbport (r109a_strength-settings-engine): the strength's line\n")
INS_BEFORE(RV + "vk_rasterizer_effects.cpp",
    "    effects_wanted = AnyWanted();\n",
    "    // bbport (r109a_strength-settings-engine): the lamp flicker's two strengths for the next\n"
    "    // frame, before AnyWanted asks LampFlicker::On(): the settings (each frame), or\n"
    "    // BB_LAMP_FLICKER and BB_LAMP_FLICKER_ON_GAME when set; both 0: nothing of the flicker runs.\n"
    "    static_assert(BbSettings::LampFlickerSteadyDefault == LampFlicker::DefaultSteady &&\n"
    "                  BbSettings::LampFlickerOnGameDefault == LampFlicker::DefaultOnGame &&\n"
    "                  BbSettings::LampFlickerStrengthMax == LampFlicker::MaxStrength &&\n"
    "                  BbSettings::LampFlickerStrengthMin == 0.0f);\n"
    "    LampFlicker::Update(\n"
    "        BbSettings::Get().graphics_lamp_flicker_strength.load(std::memory_order_relaxed),\n"
    "        BbSettings::Get().graphics_lamp_flicker_on_game_strength.load(std::memory_order_relaxed));\n")
E(RV + "vk_rasterizer_effects.cpp",
    "    LampFlicker::FrameEnd(BbReport::Printf); // bbport (r96_lamp-flicker-colour): BB_LAMP_FLICKER only\n",
    "    // bbport (r96_lamp-flicker-colour, r109a): the strengths' line; the tracker's frame end while a\n"
    "    // strength is above 0\n"
    "    LampFlicker::FrameEnd(BbReport::Printf);\n")

# ---- lamp_flicker.h
L = RV + "lamp_flicker.h"
E(L,
    "// bbport (r96_lamp-flicker-colour): flame lamps flicker. BB_LAMP_FLICKER (environment, read once)\n"
    "// is the strength, 0 to 1; unset, 0 or not a number is off, and then nothing here runs: the\n"
    "// rasterizer tests On() (one static bool) before every call.\n",
    "// bbport (r96_lamp-flicker-colour): flame lamps flicker. The strengths (bbport r109a), 0 to 1, are\n"
    "// taken at every frame end for the next frame (Update): for lamps the game keeps steady the\n"
    "// setting graphics_lamp_flicker_strength (DefaultSteady 1), or BB_LAMP_FLICKER when it is set; for\n"
    "// lamps the game changes itself graphics_lamp_flicker_on_game_strength (DefaultOnGame 0: left\n"
    "// alone), or BB_LAMP_FLICKER_ON_GAME when it is set. The variables are read once; set means not\n"
    "// empty; a text that is not a number above 0 is 0. Both 0: off, and nothing here runs: the\n"
    "// rasterizer tests On() (one relaxed atomic load) before every call.\n")
INS_AFTER(L,
    "// RampIn seconds (no pop when a lamp appears, nor when the camera cuts).\n",
    "// With the on-game strength above 0 (r109a) a lamp the game changes (its colour or reach moved\n"
    "// after it was first seen, within the last SteadySeconds) gets a flicker of its own on top of the\n"
    "// game's: its share game_amount fades in over RampIn while the game changes it and out over\n"
    "// RampOut once the game has kept it steady for SteadySeconds, when the steady share (amount)\n"
    "// fades in as for any steady lamp. At on-game strength 0 game_amount stays 0 and such a lamp is\n"
    "// left alone: its records stay as the game made them.\n")
E(L,
    "// How: the light is multiplied by f = 1 + A * amount * Wave(seed, t), A = Swing * strength (times\n"
    "// ShowScale with BB_LAMP_FLICKER_SHOW=1, at most MaxSwing), Wave a sum of three sines of\n",
    "// How: the light is multiplied by f = 1 + (A(steady) * amount + A(on_game) * game_amount) *\n"
    "// Wave(seed, t), A(s) = Swing * s (times ShowScale with BB_LAMP_FLICKER_SHOW=1, at most MaxSwing;\n"
    "// a lamp has only one share above 0 except while the other fades out), Wave a sum of three sines of\n")
E(L,
    "#include <array>\n"
    "#include <bit>\n",
    "#include <array>\n"
    "#include <atomic> // bbport (r109a)\n"
    "#include <bit>\n")
E(L,
    "#include <vector>\n"
    "\n"
    "namespace LampFlicker {\n",
    "#include <vector>\n"
    "\n"
    "#include \"strength_knob.h\" // bbport (r109a_strength-settings-engine)\n"
    "\n"
    "namespace LampFlicker {\n")
INS_AFTER(L,
    "inline constexpr float DefaultTemp = 0.6f;  ///< BB_LAMP_FLICKER_TEMP when not set\n",
    "/// bbport (r109a): the strengths' defaults and largest value (graphics_lamp_flicker_strength,\n"
    "/// graphics_lamp_flicker_on_game_strength; tied to bbport_settings.h by static_asserts in\n"
    "/// vk_rasterizer_effects.cpp)\n"
    "inline constexpr float DefaultSteady = 1.0f, DefaultOnGame = 0.0f, MaxStrength = 1.0f;\n")
E(L,
    "    float strength = 0.0f; ///< BB_LAMP_FLICKER, 0..1\n"
    "    float temp = 0.0f;     ///< BB_LAMP_FLICKER_TEMP, 0..1\n"
    "    bool show = false;     ///< BB_LAMP_FLICKER_SHOW=1\n"
    "    /// The swing and colour shift a pass uses.\n"
    "    [[nodiscard]] float Amplitude() const {\n"
    "        return std::min(MaxSwing, Swing * strength * (show ? ShowScale : 1.0f));\n"
    "    }\n",
    "    float strength = 0.0f; ///< steady lamps, 0..1 (r109a: the frame's, Tracker::SetStrengths)\n"
    "    float temp = 0.0f;     ///< BB_LAMP_FLICKER_TEMP, 0..1\n"
    "    bool show = false;     ///< BB_LAMP_FLICKER_SHOW=1\n"
    "    float on_game = 0.0f;  ///< r109a: lamps the game changes itself, 0..1; 0: left alone\n"
    "    /// The swing and colour shift a pass uses.\n"
    "    [[nodiscard]] float Amplitude() const {\n"
    "        return Amplitude(strength);\n"
    "    }\n"
    "    /// r109a: the swing at strength `s`.\n"
    "    [[nodiscard]] float Amplitude(float s) const {\n"
    "        return std::min(MaxSwing, Swing * s * (show ? ShowScale : 1.0f));\n"
    "    }\n")
E(L,
    "inline const Params& Knobs() {\n"
    "    static const Params params = ParseParams(std::getenv(\"BB_LAMP_FLICKER\"),\n"
    "                                             std::getenv(\"BB_LAMP_FLICKER_TEMP\"),\n"
    "                                             std::getenv(\"BB_LAMP_FLICKER_SHOW\"));\n"
    "    return params;\n"
    "}\n"
    "\n"
    "inline bool On() {\n"
    "    return Knobs().on;\n"
    "}\n",
    "/// The environment's knobs, read once: BB_LAMP_FLICKER_TEMP and BB_LAMP_FLICKER_SHOW (r109a: the\n"
    "/// strengths a frame uses come from Update; `on` and `strength` here are BB_LAMP_FLICKER's own).\n"
    "inline const Params& Knobs() {\n"
    "    static const Params params = ParseParams(std::getenv(\"BB_LAMP_FLICKER\"),\n"
    "                                             std::getenv(\"BB_LAMP_FLICKER_TEMP\"),\n"
    "                                             std::getenv(\"BB_LAMP_FLICKER_SHOW\"));\n"
    "    return params;\n"
    "}\n"
    "\n"
    "/// bbport (r109a_strength-settings-engine): the two strengths of a frame and where each came from.\n"
    "struct Strengths {\n"
    "    StrengthKnob::Value steady, on_game;\n"
    "    [[nodiscard]] bool On() const {\n"
    "        return steady.value > 0.0f || on_game.value > 0.0f;\n"
    "    }\n"
    "};\n"
    "\n"
    "/// The strengths from the variables as read once (`steady_env`: BB_LAMP_FLICKER, `on_game_env`:\n"
    "/// BB_LAMP_FLICKER_ON_GAME; each wins when set) and the settings' values.\n"
    "inline Strengths Resolve(const StrengthKnob::Env& steady_env, const StrengthKnob::Env& on_game_env,\n"
    "                         float steady_setting, float on_game_setting) {\n"
    "    return {StrengthKnob::Pick(steady_env, steady_setting, MaxStrength, DefaultSteady),\n"
    "            StrengthKnob::Pick(on_game_env, on_game_setting, MaxStrength, DefaultOnGame)};\n"
    "}\n"
    "\n"
    "namespace Detail {\n"
    "inline std::atomic<bool> on{false}; ///< Strengths::On() of the frame that runs\n"
    "inline Strengths now{};             ///< written by Update, read by FrameEnd (the frame end only)\n"
    "} // namespace Detail\n"
    "\n"
    "/// Each frame end, before anything asks On() for the next frame: that frame's strengths, from the\n"
    "/// settings' values (the caller loads them) unless a variable is set. Returns On().\n"
    "inline bool Update(float steady_setting, float on_game_setting) {\n"
    "    static const StrengthKnob::Env steady_env =\n"
    "        StrengthKnob::ReadEnv(std::getenv(\"BB_LAMP_FLICKER\"), MaxStrength);\n"
    "    static const StrengthKnob::Env on_game_env =\n"
    "        StrengthKnob::ReadEnv(std::getenv(\"BB_LAMP_FLICKER_ON_GAME\"), MaxStrength);\n"
    "    Detail::now = Resolve(steady_env, on_game_env, steady_setting, on_game_setting);\n"
    "    const bool on = Detail::now.On();\n"
    "    Detail::on.store(on, std::memory_order_relaxed);\n"
    "    return on;\n"
    "}\n"
    "\n"
    "/// A strength above 0 this frame (one relaxed atomic load; false before the first frame end).\n"
    "inline bool On() {\n"
    "    return Detail::on.load(std::memory_order_relaxed);\n"
    "}\n")
INS_AFTER(L,
    "    explicit Tracker(const Params& p) : params{p} {\n"
    "        lamps.reserve(MostLamps);\n"
    "    }\n",
    "\n"
    "    /// r109a: the strengths of the frame that starts (FrameEnd, from Update). `resumed`: the\n"
    "    /// frame end before had both strengths at 0, so no lamp was looked at since: every lamp is\n"
    "    /// forgotten and starts again as a new one (it waits SteadySeconds and fades in over RampIn).\n"
    "    void SetStrengths(float steady, float on_game, bool resumed = false) {\n"
    "        std::scoped_lock lock{mutex};\n"
    "        params.strength = steady;\n"
    "        params.on_game = on_game;\n"
    "        params.on = steady > 0.0f || on_game > 0.0f;\n"
    "        if (resumed) {\n"
    "            lamps.clear();\n"
    "        }\n"
    "    }\n")
E(L,
    "        // r96b: BB_LAMP_FLICKER_ON_GAME=1 (read once) also flickers lamps the game changes itself.\n"
    "        static const bool on_game = [] {\n"
    "            const char* text = std::getenv(\"BB_LAMP_FLICKER_ON_GAME\");\n"
    "            return text != nullptr && text[0] == '1' && text[1] == '\\0';\n"
    "        }();\n"
    "        const bool steady = on_game || now - lamp.changed_at >= SteadySeconds;\n"
    "        lamp.amount = steady ? float(std::min(1.0, double(lamp.amount) + dt / RampIn))\n"
    "                             : float(std::max(0.0, double(lamp.amount) - dt / RampOut));\n"
    "        const float before = lamp.factor;\n"
    "        const bool followed = lamp.seen_frame + 1 == frame;\n"
    "        lamp.factor = 1.0f + params.Amplitude() * lamp.amount * Wave(lamp.seed, now);\n"
    "        if (followed) {\n"
    "            window.step = std::max(window.step, std::abs(lamp.factor - before));\n"
    "        }\n"
    "        // A lamp not yet steady for SteadySeconds is waiting, unless its colour or reach changed\n"
    "        // after it was first seen: then the game changes it.\n"
    "        lamp.state = !steady && lamp.changed_at > lamp.born_at ? State::GameChanges\n"
    "                     : steady && lamp.amount > 0.0f            ? State::Flickers\n"
    "                                                               : State::Waiting;\n",
    "        const bool steady = now - lamp.changed_at >= SteadySeconds; // r96's 1 s rule\n"
    "        // A lamp not yet steady for SteadySeconds whose colour or reach changed after it was first\n"
    "        // seen: the game changes it. r109a (replaces r96b's BB_LAMP_FLICKER_ON_GAME=1 rule, which\n"
    "        // counted every lamp as steady): with the on-game strength above 0 such a lamp gets a\n"
    "        // share of its own (game_amount); at 0 that share stays 0 and the lamp is left alone.\n"
    "        const bool game_changes = !steady && lamp.changed_at > lamp.born_at;\n"
    "        const bool on_game = game_changes && params.on_game > 0.0f;\n"
    "        lamp.amount = steady ? float(std::min(1.0, double(lamp.amount) + dt / RampIn))\n"
    "                             : float(std::max(0.0, double(lamp.amount) - dt / RampOut));\n"
    "        lamp.game_amount = on_game\n"
    "                               ? float(std::min(1.0, double(lamp.game_amount) + dt / RampIn))\n"
    "                               : float(std::max(0.0, double(lamp.game_amount) - dt / RampOut));\n"
    "        const float before = lamp.factor;\n"
    "        const bool followed = lamp.seen_frame + 1 == frame;\n"
    "        float swing = params.Amplitude() * lamp.amount;\n"
    "        if (lamp.game_amount > 0.0f) {\n"
    "            swing += params.Amplitude(params.on_game) * lamp.game_amount;\n"
    "        }\n"
    "        lamp.factor = 1.0f + swing * Wave(lamp.seed, now);\n"
    "        if (followed) {\n"
    "            window.step = std::max(window.step, std::abs(lamp.factor - before));\n"
    "        }\n"
    "        // A lamp not yet steady for SteadySeconds is waiting, unless the game changes it; such a\n"
    "        // lamp flickers only by the on-game strength.\n"
    "        lamp.state = game_changes ? (on_game && lamp.game_amount > 0.0f ? State::Flickers\n"
    "                                                                        : State::GameChanges)\n"
    "                     : steady && lamp.amount > 0.0f ? State::Flickers\n"
    "                                                    : State::Waiting;\n")
E(L,
    "        if (lamp.amount <= 0.0f || lamp.factor == 1.0f) {\n",
    "        if (!(swing > 0.0f) || lamp.factor == 1.0f) {\n")
E(L,
    "        float amount = 0.0f;\n",
    "        float amount = 0.0f;\n"
    "        float game_amount = 0.0f; ///< r109a: the share of the on-game flicker\n")
E(L,
    "/// Each frame end (EffectsOnFrameEnd). Off: one static bool test. On: the knobs' line once, then\n"
    "/// the tracker's frame end with real time.\n"
    "template <typename Print>\n"
    "void FrameEnd(Print&& print) {\n"
    "    if (!On()) {\n"
    "        return;\n"
    "    }\n"
    "    using Clock = std::chrono::steady_clock;\n"
    "    static const Clock::time_point start = [&] {\n"
    "        const Params& p = Knobs();\n"
    "        print(\"Lamp flicker (r96, BB_LAMP_FLICKER=%.2f): flame-coloured lamps whose colour and \"\n"
    "              \"reach the game keeps steady flicker by up to %.0f%% of their light, colour \"\n"
    "              \"shift %.2f \"\n"
    "              \"(BB_LAMP_FLICKER_TEMP)%s; lamps the game changes itself are left alone\\n\",\n"
    "              double(p.strength), double(p.Amplitude()) * 100.0, double(p.Temp()),\n"
    "              p.show ? \", BB_LAMP_FLICKER_SHOW=1: exaggerated, lamps listed every 120 frames\" : \"\");\n"
    "        return Clock::now();\n"
    "    }();\n"
    "    Get().EndFrame(std::chrono::duration<double>(Clock::now() - start).count(), print);\n"
    "}\n",
    "/// Each frame end (EffectsOnFrameEnd), after Update. r109a: the strengths' line at the first frame\n"
    "/// end and after a change (at most once every LineFrames frames), also while both are 0. Off:\n"
    "/// nothing more. On: the tracker takes the strengths (and forgets its lamps when the frame end\n"
    "/// before was off) and ends its frame with real time.\n"
    "template <typename Print>\n"
    "void FrameEnd(Print&& print) {\n"
    "    static StrengthKnob::Line line;\n"
    "    static bool ran = false; ///< the tracker's frame end ran at the frame end before\n"
    "    const Strengths& s = Detail::now;\n"
    "    if (line.Due(LineFrames, s.steady, s.on_game)) {\n"
    "        const Params& p = Knobs();\n"
    "        print(\"Lamp flicker (r109a): flame lamps the game keeps steady: strength %.2f from the %s \"\n"
    "              \"(%s), up to %.0f%% of their light; flame lamps the game changes itself: strength \"\n"
    "              \"%.2f from the %s (%s)%s; colour shift %.2f (BB_LAMP_FLICKER_TEMP)%s%s\\n\",\n"
    "              double(s.steady.value), StrengthKnob::SourceName(s.steady),\n"
    "              s.steady.from_env ? \"BB_LAMP_FLICKER\" : \"graphics_lamp_flicker_strength\",\n"
    "              double(p.Amplitude(s.steady.value)) * 100.0, double(s.on_game.value),\n"
    "              StrengthKnob::SourceName(s.on_game),\n"
    "              s.on_game.from_env ? \"BB_LAMP_FLICKER_ON_GAME\" : \"graphics_lamp_flicker_on_game_strength\",\n"
    "              s.on_game.value > 0.0f ? \", this flicker on top of their own\" : \", left alone\",\n"
    "              double(p.Temp()),\n"
    "              p.show ? \", BB_LAMP_FLICKER_SHOW=1: exaggerated, lamps listed every 120 frames\" : \"\",\n"
    "              s.On() ? \"\" : \"; both 0: off, nothing of it runs\");\n"
    "    }\n"
    "    if (!On()) {\n"
    "        ran = false;\n"
    "        return;\n"
    "    }\n"
    "    using Clock = std::chrono::steady_clock;\n"
    "    static const Clock::time_point start = Clock::now();\n"
    "    Tracker& tracker = Get();\n"
    "    tracker.SetStrengths(s.steady.value, s.on_game.value, !ran);\n"
    "    ran = true;\n"
    "    tracker.EndFrame(std::chrono::duration<double>(Clock::now() - start).count(), print);\n"
    "}\n")

# ---- tests/test_settings.cpp
INS_BEFORE(TS + "test_settings.cpp",
    "    // bbport (r39_master-debug): engine_previous_paths and the debug_* keys. Nothing above sets\n",
    "    // bbport (r109a_strength-settings-engine): the halation's and the lamp flicker's strengths.\n"
    "    // Nothing above sets them: the defaults; written back; read; saved after a change; a value\n"
    "    // outside its range is the nearest end; a text that is no number is 0; a value that is not\n"
    "    // finite is the default.\n"
    "    static_assert(BbSettings::HalationStrengthMin == 0.0f && BbSettings::HalationStrengthMax == 2.0f &&\n"
    "                  BbSettings::HalationStrengthDefault == 1.0f);\n"
    "    static_assert(BbSettings::LampFlickerStrengthMin == 0.0f && BbSettings::LampFlickerStrengthMax == 1.0f &&\n"
    "                  BbSettings::LampFlickerSteadyDefault == 1.0f && BbSettings::LampFlickerOnGameDefault == 0.0f);\n"
    "    assert(s.graphics_halation_strength == BbSettings::HalationStrengthDefault &&\n"
    "           s.graphics_lamp_flicker_strength == BbSettings::LampFlickerSteadyDefault &&\n"
    "           s.graphics_lamp_flicker_on_game_strength == BbSettings::LampFlickerOnGameDefault);\n"
    "    BbSettings::Save();\n"
    "    {\n"
    "        const std::string text = Read(path);\n"
    "        for (const char* line : {\"graphics_halation_strength=1.00\\n\", \"graphics_lamp_flicker_strength=1.00\\n\",\n"
    "                                 \"graphics_lamp_flicker_on_game_strength=0.00\\n\"}) {\n"
    "            assert(text.find(line) != std::string::npos);\n"
    "        }\n"
    "    }\n"
    "    { std::ofstream file(path); file << \"graphics_halation_strength=0.25\\ngraphics_lamp_flicker_strength=0.5\\n\"\n"
    "                                        \"graphics_lamp_flicker_on_game_strength=0.75\\n\"; }\n"
    "    BbSettings::Load();\n"
    "    assert(s.graphics_halation_strength == 0.25f && s.graphics_lamp_flicker_strength == 0.5f &&\n"
    "           s.graphics_lamp_flicker_on_game_strength == 0.75f);\n"
    "    s.graphics_halation_strength = 1.5f;\n"
    "    s.graphics_lamp_flicker_strength = 0.0f;\n"
    "    s.graphics_lamp_flicker_on_game_strength = 1.0f;\n"
    "    BbSettings::Save();\n"
    "    {\n"
    "        const std::string text = Read(path);\n"
    "        for (const char* line : {\"graphics_halation_strength=1.50\\n\", \"graphics_lamp_flicker_strength=0.00\\n\",\n"
    "                                 \"graphics_lamp_flicker_on_game_strength=1.00\\n\"}) {\n"
    "            assert(text.find(line) != std::string::npos);\n"
    "        }\n"
    "    }\n"
    "    s.graphics_halation_strength = 1.0f;\n"
    "    s.graphics_lamp_flicker_strength = 1.0f;\n"
    "    s.graphics_lamp_flicker_on_game_strength = 0.0f;\n"
    "    BbSettings::Load();\n"
    "    assert(s.graphics_halation_strength == 1.5f && s.graphics_lamp_flicker_strength == 0.0f &&\n"
    "           s.graphics_lamp_flicker_on_game_strength == 1.0f);\n"
    "    { std::ofstream file(path); file << \"graphics_halation_strength=9\\ngraphics_lamp_flicker_strength=-1\\n\"\n"
    "                                        \"graphics_lamp_flicker_on_game_strength=3\\n\"; }\n"
    "    BbSettings::Load();\n"
    "    assert(s.graphics_halation_strength == BbSettings::HalationStrengthMax &&\n"
    "           s.graphics_lamp_flicker_strength == 0.0f &&\n"
    "           s.graphics_lamp_flicker_on_game_strength == BbSettings::LampFlickerStrengthMax);\n"
    "    { std::ofstream file(path); file << \"graphics_halation_strength=-2\\ngraphics_lamp_flicker_strength=abc\\n\"\n"
    "                                        \"graphics_lamp_flicker_on_game_strength=-0.5\\n\"; }\n"
    "    BbSettings::Load();\n"
    "    assert(s.graphics_halation_strength == 0.0f && s.graphics_lamp_flicker_strength == 0.0f &&\n"
    "           s.graphics_lamp_flicker_on_game_strength == 0.0f);\n"
    "    { std::ofstream file(path); file << \"graphics_halation_strength=nan\\ngraphics_lamp_flicker_strength=inf\\n\"\n"
    "                                        \"graphics_lamp_flicker_on_game_strength=-inf\\n\"; }\n"
    "    s.graphics_lamp_flicker_on_game_strength = 0.5f; // not the default before this Load\n"
    "    BbSettings::Load();\n"
    "    assert(s.graphics_halation_strength == BbSettings::HalationStrengthDefault &&\n"
    "           s.graphics_lamp_flicker_strength == BbSettings::LampFlickerSteadyDefault &&\n"
    "           s.graphics_lamp_flicker_on_game_strength == BbSettings::LampFlickerOnGameDefault);\n"
    "    BbSettings::Save();\n")

# ---- tests/test_halation.cpp
INS_BEFORE(TS + "test_halation.cpp",
    "    std::printf(\"halation-test: all checks passed\\n\");\n",
    "    // h. bbport (r109a_strength-settings-engine): the strength a frame uses: BB_HALATION when it\n"
    "    // is set (by Read's rule), else the setting, clamped; and when the strength's line is due.\n"
    "    {\n"
    "        using StrengthKnob::ReadEnv;\n"
    "        const StrengthKnob::Env unset = ReadEnv(nullptr, MaxStrength);\n"
    "        assert(!unset.set && !ReadEnv(\"\", MaxStrength).set);\n"
    "        const StrengthKnob::Value d = StrengthOf(unset, DefaultStrength);\n"
    "        assert(DefaultStrength == 1.0f && d.value == 1.0f && !d.from_env);\n"
    "        assert(StrengthOf(unset, 0.0f).value == 0.0f && StrengthOf(unset, 1.5f).value == 1.5f);\n"
    "        assert(StrengthOf(unset, 9.0f).value == MaxStrength && StrengthOf(unset, -1.0f).value == 0.0f);\n"
    "        assert(StrengthOf(unset, NAN).value == DefaultStrength &&\n"
    "               StrengthOf(unset, INFINITY).value == DefaultStrength);\n"
    "        assert(StrengthOf(ReadEnv(\"\", MaxStrength), 0.5f).value == 0.5f); // empty: the setting\n"
    "        for (const char* text : {\"0\", \"-1\", \"on\", \"nan\", \"inf\", \"1\", \"0.5\", \"7\"}) {\n"
    "            const StrengthKnob::Value e = StrengthOf(ReadEnv(text, MaxStrength), 1.25f);\n"
    "            assert(e.from_env && e.value == Read(text, nullptr, nullptr, nullptr).strength);\n"
    "        }\n"
    "        StrengthKnob::Line line;\n"
    "        const StrengthKnob::Value one{1.0f, false}, half{0.5f, false}, env_half{0.5f, true};\n"
    "        assert(line.Due(600, one));  // the first frame\n"
    "        assert(!line.Due(600, one)); // unchanged\n"
    "        int at = -1;\n"
    "        for (int f = 2; f < 2000 && at < 0; ++f) {\n"
    "            at = line.Due(600, half) ? f : -1;\n"
    "        }\n"
    "        assert(at == 600); // a change: 600 frames after the last line\n"
    "        assert(!line.Due(600, half));\n"
    "        int changes = 0;\n"
    "        for (int f = 0; f < 599; ++f) {\n"
    "            changes += line.Due(600, f % 2 ? one : half) ? 1 : 0; // dragged and back\n"
    "        }\n"
    "        assert(changes == 0 && !line.Due(600, half)); // back where it was: no line\n"
    "        at = -1;\n"
    "        for (int f = 0; f < 2000 && at < 0; ++f) {\n"
    "            at = line.Due(600, env_half) ? f : -1;\n"
    "        }\n"
    "        assert(at >= 0); // the source counts as a change\n"
    "        // The key slots: cleared at the first pass and after more than KeyStaleFrames frame ends\n"
    "        // without one; kept from one frame to the next, also with two frame ends a pass.\n"
    "        static_assert(KeyStaleFrames == 30);\n"
    "        assert(ClearsKey(0, 0, 0) && ClearsKey(0, 500, 0));\n"
    "        assert(!ClearsKey(1, 1, 0) && !ClearsKey(7, 12, 11) && !ClearsKey(7, 13, 11));\n"
    "        assert(!ClearsKey(7, 11 + KeyStaleFrames, 11) && ClearsKey(7, 12 + KeyStaleFrames, 11));\n"
    "    }\n"
    "\n")

# ---- tests/test_lamp_flicker.cpp
INS_BEFORE(TS + "test_lamp_flicker.cpp",
    "    if (failures == 0) {\n"
    "        std::printf(\"lamp-flicker-test: all checks passed\\n\");\n",
    "    // j. bbport (r109a_strength-settings-engine): the two strengths\n"
    "    {\n"
    "        using StrengthKnob::ReadEnv;\n"
    "        const StrengthKnob::Env unset = ReadEnv(nullptr, MaxStrength);\n"
    "        Expect(!unset.set && !ReadEnv(\"\", MaxStrength).set, \"j1 unset or empty: the setting\");\n"
    "        const Strengths d = Resolve(unset, unset, DefaultSteady, DefaultOnGame);\n"
    "        Expect(d.steady.value == 1.0f && d.on_game.value == 0.0f && !d.steady.from_env &&\n"
    "                   !d.on_game.from_env && d.On(),\n"
    "               \"j2 defaults: steady lamps 1, lamps the game changes 0, from the settings\");\n"
    "        const Strengths e = Resolve(ReadEnv(\"0\", MaxStrength), ReadEnv(\"1\", MaxStrength), 0.7f, 0.0f);\n"
    "        Expect(e.steady.value == 0.0f && e.steady.from_env && e.on_game.value == 1.0f &&\n"
    "                   e.on_game.from_env && e.On(),\n"
    "               \"j3 a set variable wins over the setting, 0 too\");\n"
    "        for (const char* text : {\"0\", \"abc\", \"-1\", \"nan\", \"1\", \"3\", \"0.5\"}) {\n"
    "            Expect(ReadEnv(text, MaxStrength).value == ParseParams(text, nullptr, nullptr).strength,\n"
    "                   \"j4 BB_LAMP_FLICKER's text is read by r96's rule\");\n"
    "        }\n"
    "        const Strengths c = Resolve(unset, unset, 7.0f, -1.0f);\n"
    "        const Strengths n = Resolve(unset, unset, NAN, INFINITY);\n"
    "        Expect(c.steady.value == 1.0f && c.on_game.value == 0.0f && n.steady.value == DefaultSteady &&\n"
    "                   n.on_game.value == DefaultOnGame,\n"
    "               \"j5 settings clamped to 0..1, not finite: the default\");\n"
    "        Expect(!Resolve(unset, unset, 0.0f, 0.0f).On(), \"j6 both 0: off\");\n"
    "\n"
    "        // A steady flame and a lamp the game flickers (a new colour every frame), 6 s.\n"
    "        struct Run {\n"
    "            std::vector<std::uint32_t> in, out;\n"
    "            std::array<std::uint64_t, 3> states{};\n"
    "        };\n"
    "        const auto run = [](Tracker& t, float steady, float on_game, int on_game_until) {\n"
    "            Run r;\n"
    "            std::vector<std::uint32_t> in(32), out(32);\n"
    "            const auto still = Record(1.0f, 0.5f, -6.0f, 8.0f, 1.0f, 0.55f, 0.18f);\n"
    "            for (int f = 0; f < 60 * 6; ++f) {\n"
    "                if (steady >= 0.0f) { // below 0: the strengths the tracker was made with\n"
    "                    t.SetStrengths(steady, f < on_game_until ? on_game : 0.0f);\n"
    "                }\n"
    "                const float g = 0.9f + 0.1f * float(std::sin(f * 0.7));\n"
    "                const auto game = Record(0.2f, 1.4f, -2.0f, 5.2f, g, 0.5f * g, 0.15f * g);\n"
    "                std::copy(still.begin(), still.end(), in.begin());\n"
    "                std::copy(game.begin(), game.end(), in.begin() + 16);\n"
    "                t.Patch(in.data(), 2, out.data(), Identity.data());\n"
    "                r.in.insert(r.in.end(), in.begin(), in.end());\n"
    "                r.out.insert(r.out.end(), out.begin(), out.end());\n"
    "                t.EndFrame(f / 60.0 + 1.0 / 60.0, Count);\n"
    "            }\n"
    "            r.states = t.States();\n"
    "            return r;\n"
    "        };\n"
    "        const Params base = ParseParams(nullptr, nullptr, nullptr); // the default colour shift\n"
    "        Tracker t96{ParseParams(\"1\", nullptr, nullptr)}, t0{base}, t1{base}, thalf{base}, tback{base};\n"
    "        const Run r96 = run(t96, -1.0f, 0.0f, 0);\n"
    "        const Run r0 = run(t0, 1.0f, 0.0f, 1 << 30);\n"
    "        const Run r1 = run(t1, 1.0f, 1.0f, 1 << 30);\n"
    "        const Run rhalf = run(thalf, 0.5f, 0.0f, 1 << 30);\n"
    "        const Run rback = run(tback, 1.0f, 1.0f, 60 * 3);\n"
    "        const std::size_t frames = r0.out.size() / 32;\n"
    "        bool game_kept = true, game_changed = false, game_in_swing = true, steady_same = true;\n"
    "        bool back_kept = true, half_ok = true;\n"
    "        float most = 0.0f;\n"
    "        for (std::size_t f = 0; f < frames; ++f) {\n"
    "            const std::size_t at = f * 32;\n"
    "            game_kept = game_kept && std::equal(r0.out.begin() + at + 16, r0.out.begin() + at + 32,\n"
    "                                                r0.in.begin() + at + 16);\n"
    "            game_changed = game_changed || !std::equal(r1.out.begin() + at + 16,\n"
    "                                                       r1.out.begin() + at + 32, r1.in.begin() + at + 16);\n"
    "            const float gf = LumaOf(r1.out.data() + at + 16) / LumaOf(r1.in.data() + at + 16);\n"
    "            game_in_swing = game_in_swing && gf >= 1.0f - Swing - 1e-4f && gf <= 1.0f + Swing + 1e-4f;\n"
    "            steady_same = steady_same && std::equal(r1.out.begin() + at, r1.out.begin() + at + 16,\n"
    "                                                    r0.out.begin() + at);\n"
    "            if (f >= std::size_t(60 * 3)) {\n"
    "                back_kept = back_kept && std::equal(rback.out.begin() + at + 16,\n"
    "                                                    rback.out.begin() + at + 32,\n"
    "                                                    rback.in.begin() + at + 16);\n"
    "            }\n"
    "            const float full = LumaOf(r0.out.data() + at) / LumaOf(r0.in.data() + at) - 1.0f;\n"
    "            const float part = LumaOf(rhalf.out.data() + at) / LumaOf(rhalf.in.data() + at) - 1.0f;\n"
    "            half_ok = half_ok && std::abs(part - 0.5f * full) <= 2e-5f;\n"
    "            most = std::max(most, std::abs(full));\n"
    "        }\n"
    "        Expect(r0.out == r96.out, \"j7 strengths 1 and 0 from the setting: bit for bit r96's path\");\n"
    "        Expect(game_kept, \"j8 on-game strength 0: the game's lamp stays bit for bit as the game made it\");\n"
    "        Expect(r0.states[std::size_t(State::GameChanges)] > 0, \"j9 and it is counted as left alone\");\n"
    "        Expect(game_changed && game_in_swing, \"j10 on-game strength 1: the game's lamp flickers within the swing\");\n"
    "        Expect(r1.states[std::size_t(State::GameChanges)] == 0 && r1.states[std::size_t(State::Flickers)] > 0,\n"
    "               \"j11 and it is counted as flickering, none left alone\");\n"
    "        Expect(steady_same, \"j12 the steady lamp does not depend on the on-game strength\");\n"
    "        Expect(half_ok && most > 0.05f, \"j13 strength 0.5: half the swing of strength 1\");\n"
    "        Expect(back_kept, \"j14 the on-game strength back to 0: the game's lamp left alone at once\");\n"
    "        // Back on after frame ends with both strengths 0 (FrameEnd passes resumed): t0's steady\n"
    "        // lamp, flickering at full share before, is a new lamp again and waits SteadySeconds.\n"
    "        bool resumed_kept = true;\n"
    "        {\n"
    "            std::vector<std::uint32_t> one(16);\n"
    "            const auto still = Record(1.0f, 0.5f, -6.0f, 8.0f, 1.0f, 0.55f, 0.18f);\n"
    "            t0.SetStrengths(1.0f, 0.0f, true); // the frame end that turns it on again,\n"
    "            t0.EndFrame(6.0 + 2.0, Count);     // 2 s after its last one\n"
    "            for (int f = 0; f < 30; ++f) {\n"
    "                t0.SetStrengths(1.0f, 0.0f);\n"
    "                t0.Patch(still.data(), 1, one.data(), Identity.data());\n"
    "                resumed_kept = resumed_kept && std::equal(one.begin(), one.end(), still.begin());\n"
    "                t0.EndFrame(8.0 + (f + 1) / 60.0, Count);\n"
    "            }\n"
    "        }\n"
    "        Expect(resumed_kept && r0.out != r0.in, \"j15 back on after both 0: no lamp jumps to its swing\");\n"
    "    }\n")

# ---- README.md
RM = "README.md"
E(RM,
    "Off unless `BB_LAMP_FLICKER` is set above 0. These environment variables are read once, at the end of the first frame; text that does not begin with a number leaves the flicker off.",
    "On by default for flame lamps the game keeps steady, off for flame lamps the game changes itself: the strengths are the `lantern.ini` keys `graphics_lamp_flicker_strength` (steady lamps, 0 to 1, default `1`) and `graphics_lamp_flicker_on_game_strength` (lamps the game changes itself, 0 to 1, default `0`), taken at the end of every frame for the next one. `BB_LAMP_FLICKER` and `BB_LAMP_FLICKER_ON_GAME`, when set and not empty, win over them. These environment variables are read once, at the end of the first frame; in `BB_LAMP_FLICKER` or `BB_LAMP_FLICKER_ON_GAME`, text that does not begin with a number is a strength of 0 (in `BB_LAMP_FLICKER_TEMP` it gives the default `0.6`). With both strengths at 0 nothing of the flicker runs; when a strength goes above 0 again after that, every lamp starts as a new one (it waits 1 s, then its flicker fades in over 1 s). The log has a `Lamp flicker (r109a):` line with both strengths and where each came from (setting or environment) at the end of the first frame, and again after a change, at most once every 600 frames.")
E(RM,
    "is left alone, and one that starts to change loses an added flicker within 0.2 s.",
    "is left alone while the on-game strength is 0 (its lamp records stay exactly as the game made them), and one that starts to change loses an added flicker within 0.2 s. With the on-game strength above 0 such a lamp gets a flicker of its own on top of the game's, with a swing of 0.14 times the on-game strength, fading in over 1 s while the game changes it; once the game has kept it steady for 1 s that flicker fades out within 0.2 s and the steady lamps' flicker fades in over 1 s.")
INS_BEFORE(RM,
    "| `BB_LAMP_FLICKER` | Strength, 0 to 1:",
    "| `graphics_lamp_flicker_strength` | `lantern.ini` key: the strength for flame lamps the game keeps steady, 0 to 1, taken every frame, with the swing `BB_LAMP_FLICKER` describes; `BB_LAMP_FLICKER` wins over it when set. A value outside the range is the nearest end, one that is not a finite number is `1`, text that is no number is `0` | `1` |\n"
    "| `graphics_lamp_flicker_on_game_strength` | `lantern.ini` key: the strength for flame lamps whose colour or reach the game changes itself, 0 to 1, taken every frame: their light then also moves by up to 0.14 times it on top of the game's own flicker; `0` leaves them as the game made them; `BB_LAMP_FLICKER_ON_GAME` wins over it when set. A value outside the range is the nearest end, one that is not a finite number is `0`, text that is no number is `0` | `0` |\n")
E(RM,
    "as three slow waves (0.37, 1.13 and 2.71 Hz, each up to 15% faster or slower for each lamp, with phases of its own); 0 or not set is off | off |",
    "as three slow waves (0.37, 1.13 and 2.71 Hz, each up to 15% faster or slower for each lamp, with phases of its own). Set and not empty, it wins over `graphics_lamp_flicker_strength`; `0` or text that does not begin with a number is then 0 (no flicker for steady lamps) | unset |")
E(RM,
    "| `BB_LAMP_FLICKER_ON_GAME` | `1`: the flicker also acts on flame lamps whose colour or reach the game changes itself (its own flicker stays, this one is multiplied on top); such lamps are otherwise left alone | off |",
    "| `BB_LAMP_FLICKER_ON_GAME` | Strength for flame lamps whose colour or reach the game changes itself, 0 to 1 (`1` the full swing; their own flicker stays, this one is multiplied on top). Set and not empty, it wins over `graphics_lamp_flicker_on_game_strength`; `0` or text that does not begin with a number is then 0 (left alone) | unset |")
E(RM,
    "Off unless `BB_HALATION` names a strength above 0; then a few lines of the session log (with the Windows launcher, `last_session.log` in the `logs` folder) start with `Halation (r95`, among them one every 600 frames with the frames it drew on and the share of pixels over the threshold. These environment variables are read once when the game starts; a missing or unreadable number takes the default, then the range is applied. They are for testing and are part of no look; no ini key yet.",
    "On by default at strength 1: the strength is the `lantern.ini` key `graphics_halation_strength`, 0 to 2, read every frame; `BB_HALATION`, when it is set and not empty, wins over the key (read once, at the first frame). At strength 0 nothing is drawn; the pass's pipeline, buffers and images are made at the first frame with a strength above 0 and kept until the game ends, also when the strength goes back to 0. The session log (with the Windows launcher, `last_session.log` in the `logs` folder) has a `Halation (r109a):` line with the strength and where it came from (setting or environment) at the first frame, and again after a change, at most once every 600 frames; lines that start with `Halation (r95` follow once the glow is drawn, among them one every 600 frames with the frames it drew on and the share of pixels over the threshold. `BB_HALATION_RADIUS`, `BB_HALATION_THRESHOLD` and `BB_HALATION_SHOW` are for testing and are part of no look; they are read once, at the first frame with a strength above 0; a missing or unreadable number takes the default, then the range is applied.")
INS_BEFORE(RM,
    "| `BB_HALATION` | Strength, 0 to 2 (`1` the intended look).",
    "| `graphics_halation_strength` | `lantern.ini` key: the strength, 0 to 2, read every frame, with the glow `BB_HALATION` describes; `BB_HALATION` wins over it when set. A value outside the range is the nearest end, one that is not a finite number is `1`, text that is no number is `0` | `1` |\n")
E(RM,
    "The first frame draws no glow (no key yet).",
    "The first frame draws no glow (no key yet), nor does the first pass after more than 30 frames without one (the strength was 0, or menu previews), whose key would be that of a scene long gone.")
E(RM,
    "Unset, `0`, a negative number or text that is not a number: off, and nothing of it is made.",
    "Set and not empty, it wins over `graphics_halation_strength`; `0`, a negative number or text that is not a number is then 0: nothing drawn. Unset or empty: the key decides. Nothing of the pass is made before the first frame with a strength above 0.")
E(RM,
    "It is the `Lighting: halation` row of `BB_GPU_PROFILE=1` | off |",
    "It is the `Lighting: halation` row of `BB_GPU_PROFILE=1` | unset |")


# README defaults written twice, tied to the constants (checked on the result).
TIES = [
    (SH + "bbport_settings.h", "HalationStrengthMax = 2.0f, HalationStrengthDefault = 1.0f",
     "| `graphics_halation_strength` |", ["0 to 2", "| `1` |"]),
    (SH + "bbport_settings.h", "LampFlickerSteadyDefault = 1.0f, LampFlickerOnGameDefault = 0.0f",
     "| `graphics_lamp_flicker_strength` |", ["0 to 1", "| `1` |"]),
    (SH + "bbport_settings.h", "LampFlickerSteadyDefault = 1.0f, LampFlickerOnGameDefault = 0.0f",
     "| `graphics_lamp_flicker_on_game_strength` |", ["0 to 1", "| `0` |"]),
    (L, "inline constexpr float Swing = 0.14f;", "| `graphics_lamp_flicker_on_game_strength` |",
     ["0.14 times it"]),
    (RV + "halation_params.h", "inline constexpr std::uint64_t KeyStaleFrames = 30;", "| `BB_HALATION` |",
     ["more than 30 frames without one"]),
]
# Texts other applied patches check that must stay exactly once (r95b's check), and texts that
# must be gone.
KEEP = [(RV + "halation_params.h", "inline constexpr float Gain = 0.40f;"),
        (RM, "0.40 of the blurred excess at strength 1"),
        (RV + "halation_params.h", "inline constexpr float MaxStrength = 2.0f;")]
GONE = [(RV + "vk_rasterizer.cpp", "Halation::Wanted"), (RV + "vk_halation.h", "Wanted()"),
        (RV + "vk_halation.cpp", "Wanted()"), (L, "static const bool on_game"),
        (RV + "vk_halation.cpp", "const bool first = runs == 0;"),
        (RV + "vk_rasterizer_effects.cpp", "halation->Apply(upscaler->SceneColor());")]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def files():
    out = []
    for path, _, _, _ in EDITS:
        if path not in out:
            out.append(path)
    return out


def mark(old, new, block):
    """The text whose single presence says the edit is in."""
    return new if block is None else block


def text_checks(texts):
    for path, old, new, block in EDITS:
        found = texts[path].count(new) if block is None else min(texts[path].count(block), texts[path].count(old))
        if found != 1 or (block is not None and max(texts[path].count(block), texts[path].count(old)) != 1):
            raise SystemExit("text check: %s: new text not found exactly once: %r" % (path, new[:70]))
    for path, const, row, values in TIES:
        src = texts[path] if path in texts else load(path)[2]
        lines = [l for l in texts[RM].split("\n") if l.startswith(row)]
        if src.count(const) != 1 or len(lines) != 1 or not all(v in lines[0] for v in values):
            raise SystemExit("tie check: %r against README row %r (%r)" % (const, row, values))
    for path, text in KEEP:
        if texts[path].count(text) != 1:
            raise SystemExit("keep check: %s must hold %r once" % (path, text))
    for path, text in GONE:
        if text in texts[path]:
            raise SystemExit("gone check: %s still holds %r" % (path, text))
    for path, old, new, block in EDITS:
        if not all(ord(c) < 128 for c in new) or "\r" in new:
            raise SystemExit("%s: new text must be ASCII with LF in the script" % path)
    for path, text in NEW_FILES.items():
        if not all(ord(c) < 128 for c in text) or "\r" in text:
            raise SystemExit("%s: new file must be ASCII with LF in the script" % path)


def state_of(path, text):
    eds = [e for e in EDITS if e[0] == path]
    done = sum(text.count(mark(*e[1:])) == 1 for e in eds)
    todo = sum(text.count(mark(*e[1:])) == 0 and text.count(e[1]) == 1 for e in eds)
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    bad = [e[1][:60] for e in eds
           if text.count(mark(*e[1:])) != 1 and not (text.count(mark(*e[1:])) == 0 and text.count(e[1]) == 1)]
    raise SystemExit("REFUSED: %s: %d of %d edits applied, %d would apply; anchor or new text not "
                     "found once: %r" % (path, done, len(eds), todo, bad))


def apply_text(path, text):
    for p, old, new, block in EDITS:
        if p != path:
            continue
        if text.count(old) != 1 or text.count(mark(old, new, block)) != 0:
            raise SystemExit("REFUSED: %s: anchor found %d times: %r" % (path, text.count(old), old[:60]))
        text = text.replace(old, new, 1)
    return text


def revert_text(path, text):
    for p, old, new, block in reversed(EDITS):
        if p != path:
            continue
        m = mark(old, new, block)
        if text.count(m) != 1:
            raise SystemExit("REFUSED: %s: new text found %d times: %r" % (path, text.count(m), m[:60]))
        text = text.replace(m, old if block is None else "", 1)
    return text


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R109A_ROOT)" % ROOT)
    hal = load(RV + "vk_halation.cpp")[2]
    if "k.strength = strength; // bbport (r109a" in hal and "HP::ClearsKey" not in hal:
        raise SystemExit("REFUSED: the draft r109a_strength-settings-engine.py is applied in %s: revert it "
                         "first (and r109b before it), then apply this reviewed copy" % ROOT)
    plan = []
    for path in files():
        raw, eol, cur = load(path)
        plan.append((path, raw, eol, cur, state_of(path, cur)))
    for path, text in NEW_FILES.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            st = "clean"
        elif open(full, "rb").read() == text.replace("\n", "\r\n").encode("utf-8"):
            st = "applied"
        else:
            raise SystemExit("REFUSED: %s exists and is not this patch's file" % path)
        plan.append((path, None, None, None, st))
    states = {p[4] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED: mixed state: " + ", ".join("%s %s" % (p[0], p[4]) for p in plan))
    state = states.pop()
    edited = [p for p in plan if p[1] is not None]
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[3] for p in edited})
            print("applied (text checks pass)")
        else:
            text_checks({p[0]: apply_text(p[0], p[3]) for p in edited})
            print("not applied; would apply (%d files edited, %d edits, %d new; every anchor found "
                  "once; text checks on the result pass)" % (len(edited), len(EDITS), len(NEW_FILES)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts, outs = {}, []
        for path, raw, eol, cur, _ in edited:
            texts[path] = apply_text(path, cur)
            outs.append((path, texts[path].replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        for path, text in NEW_FILES.items():
            outs.append((path, text.replace("\n", "\r\n").encode("utf-8"), None))
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                full = os.path.join(ROOT, path)
                tmp = full + ".r109aftmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r109aftmp"
                if os.path.exists(tmp):
                    os.remove(tmp)
            for path, raw in written:
                if raw is None:
                    os.remove(os.path.join(ROOT, path))
                else:
                    open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied (%d files edited, %d edits, %d new)" % (len(edited), len(EDITS), len(NEW_FILES)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    outs = []
    for path, raw, eol, cur, _ in edited:
        outs.append((path, revert_text(path, cur).replace("\n", eol).encode("utf-8")))
    for path, data in outs:
        open(os.path.join(ROOT, path), "wb").write(data)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted (%d files edited back, %d removed)" % (len(edited), len(NEW_FILES)))


main()
