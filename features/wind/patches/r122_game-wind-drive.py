# r122_game-wind-drive: FEATURE patch (wind, "one wind for everything"). Off by default behind BB_WIND_GAME=1.
#
# Owner decision (2026-11-16 08:12): "No we should cut the vanilla foliage movement and particle direction to
# make it match our wind not the otherway around".
#
# What it does: with BB_WIND_GAME=1 (and BB_WIND=1 with the plant sway on, its default) the vertex shaders of the
# plant sway pipelines (MotionVectors::Sway) are built with a new bit, MotionVectors::GameCut (16), and then every
# v_sin_f32 of the GAME'S code in them (Lifter V_SIN_F32 in lift_alu.cpp, the recompiler's EmitFPSin) gives -1
# instead of the sine. The game's skinned cut-out foliage vertex shaders (vs 3eaa5555 and four more with 16 sines)
# are a bank of 16 wave emitters (phase from a time word of the draw's constants); with the sine at its trough
# every emitter's weight is 0, so the vanilla travelling foliage wave stops and our wind (sway, lean, gusts,
# shelter) is the only motion. Our own sway shaders use their own sine emitters and are untouched.
# NOT cut: the game's particles (CPU made, pass-through vertex shader; no term to cut) and bone-palette trees
# (their vertex shaders have no time term; the game writes the palette). See the context file.
#
# Off (BB_WIND_GAME unset, the default): BbWindGame::CutOn() is false, so the key bit and the info bit are never
# set, no shader is built differently, the serialized stages and keys are as before; the draw hook tests a key
# mask that is 0; nothing allocates.
#
# Files: new gpu/shim/bbport_wind_game.h, new tests/test_wind_game.cpp; edits: runtime_info.h (GameCut),
# vk_pipeline_cache.cpp (include, the stage info bit, the key bit + once-line), vk_pipeline_serialization.cpp
# (include, a saved key with the bit is not loaded when the knob is off), vk_rasterizer.h (include),
# vk_rasterizer.cpp (draw count), vk_rasterizer_effects.cpp (the periodic line in WindOnFrameEnd), lifter
# bridge.cpp/lift.h/lift_alu.cpp, recompiler spirv_emit_context.h / emit_spirv_floating_point.cpp,
# CMakeLists.txt + build.sh (the test), README.md (a row after BB_WIND_SHELTER_SHOW).
#
# Usage: python -I -X utf8 r122_game-wind-drive.py check | apply | revert   (root: env R122_ROOT, else <tree>)
import os
import sys

ROOT = os.environ.get("R122_ROOT", "<tree>")
HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r122_backup")

NEW_FILES = {
    "engine/gpu/shim/bbport_wind_game.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r122_game-wind-drive, FEATURE): one wind for everything. The owner's rule (2026-11-16 08:12):
// "we should cut the vanilla foliage movement and particle direction to make it match our wind not the
// other way around". BB_WIND_GAME=1 (read once; any other value is off; it needs BB_WIND=1 and the plant
// sway, BB_WIND_SWAY above 0, which is its default) cuts the game's own foliage waves.
//
// What the game does (read from the vertex shaders the engine saved in user/cache, spirv-dis, nothing
// run): the big tree vertex shaders (vs 6a833138, 9da6aacb, c829ee58, 7620368b, 803b9d24) are plain
// skinning with no time, no sine and no wind in them, so whatever moves such a tree is in its bone
// palette, which the game writes (not cut here). The skinned cut-out vertex shaders of the plants and
// leaves (vs 3eaa5555, 15382148, a666c443, bc03d90c, f68743cf: 16 sines each) are a bank of 16 wave
// emitters: per emitter a falloff 1 - distance / radius, a phase (k r + a time word of the draw's
// constants) / 360 turns, w = 0.5 sin(2 pi phase) + 0.5, the smoother step w^3 (6 w^2 - 15 w + 10), and a
// displacement along the emitter's direction of min + (max - min) times that. That is the vanilla
// foliage motion of the graveyard (a travelling wave that is not our wind's).
//
// The cut: a vertex shader of a motion pipeline with the plant sway bit (MotionVectors::Sway) is built
// with MotionVectors::GameCut (16, in the pipeline key and the stage's runtime info, so the cut and the
// uncut shader are different cache entries; no binary version offset is needed) and then every v_sin_f32
// of the game's code (Lifter V_SIN_F32, recompiler EmitFPSin) gives CutLevel (-1: the wave at its trough,
// w = 0, so the emitter adds only its base `min`, a constant: the displacement stops moving; whether that
// constant is 0 in the game's data is NOT known, a non-zero one is a fixed lean). Our own sway code (VertexSway, EmitVertexSway) uses its own sine
// emitters and is not touched. Where the pipeline has no sine, nothing changes. The cut is per pipeline
// (every draw of a plant pipeline loses the game's waves, also a draw our sway does not move), and it
// applies to the camera pass pipelines only (the game's sun shadow maps still draw the vanilla wave;
// with ray tracing the ray traced shadows use the camera pass's positions, as the sway itself does).
//
// The game's own particles are NOT changed here: their vertex shader (vs 4cd21a0f, ps 71c96598, additive
// points, 1-21 a draw) is a pass-through of a 28-float record per point, so their positions are made by
// the game's CPU every frame; the engine has no shader term to cut (see the context file).
//
// Off (BB_WIND_GAME unset, the default): CutOn() is false, the key bit and the info bit are never set,
// no shader differs, the pipeline hash and the cache are as before; the draw hook tests a mask of the
// key that is 0. Pure: no Vulkan; tests/test_wind_game.cpp.

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "bbport_wind_sway.h"

namespace BbWindGame {

/// What a cut v_sin_f32 gives: -1 puts the emitter's wave at its trough (0.5 sin + 0.5 = 0, the smoother
/// step 0), where the displacement is the emitter's base only.
inline constexpr float CutLevel = -1.0f;
/// The bit of Shader::MotionVectors::GameCut (runtime_info.h); the patch's text check ties the two.
inline constexpr std::uint32_t GameCutBit = 16;

/// BB_WIND_GAME: exactly "1" is on, anything else (unset, empty, "0", "11") is off.
[[nodiscard]] inline bool ParseOn(const char* text) {
    return text != nullptr && text[0] == '1' && text[1] == 0;
}

/// Read once, at the first use (the pipeline cache's first key). On needs the plant sway too: nothing
/// else would move the foliage the cut holds still.
[[nodiscard]] inline bool CutOn() {
    static const bool on = BbWindSway::KnobOnce().on && ParseOn(std::getenv("BB_WIND_GAME"));
    return on;
}

/// The pipeline selection says plant sway and the cut is on.
[[nodiscard]] inline bool CutWanted(bool sway_wanted) {
    return sway_wanted && CutOn();
}

struct Counters {
    std::atomic<std::uint64_t> sines{0}; ///< v_sin_f32 instructions replaced (per shader built)
    std::atomic<std::uint64_t> draws{0}; ///< draws of pipelines that have the GameCut bit
};

[[nodiscard]] inline Counters& Count() {
    static Counters counters;
    return counters;
}

/// The once-line, printed by the first caller that has the cut on (the pipeline key).
inline void Announce() {
    static const bool told = [] {
        std::printf("Wind game (r122, BB_WIND_GAME=1): the game's own plant waves are cut so that only our "
                    "wind moves foliage: in the vertex shaders of the plant sway pipelines (MotionVectors::"
                    "GameCut) every v_sin_f32 of the game's code gives %.0f (the wave at its trough); our sway "
                    "is not touched; the game's particles and bone-palette trees are not changed; a Wind game "
                    "line every 600 wind steps counts the sines cut and the draws\n",
                    double(CutLevel));
        return true;
    }();
    (void)told;
}

/// The periodic line (totals since the start).
inline int ReportText(char* out, std::size_t size) {
    const Counters& c = Count();
    return std::snprintf(out, size,
                         "Wind game (r122): %llu sines of the game's vertex shaders cut (per shader built), "
                         "%llu draws on pipelines with the cut, since the start",
                         static_cast<unsigned long long>(c.sines.load(std::memory_order_relaxed)),
                         static_cast<unsigned long long>(c.draws.load(std::memory_order_relaxed)));
}

static_assert(GameCutBit == 16 && (GameCutBit & 3u) == 0, "Kind() looks at bits 0 and 1 only");
static_assert(CutLevel >= -1.0f && CutLevel <= 1.0f, "a sine's range");

} // namespace BbWindGame
''',
    "engine/tests/test_wind_game.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r122_game-wind-drive): the game-wind cut's knob text, level, bit and counters
// (gpu/shim/bbport_wind_game.h). The shader rewrite itself (Lifter V_SIN_F32, EmitFPSin) is checked by
// compiling and by the game, not here (the patch's proof rewrote a saved shader and validated it).
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "gpu/shim/bbport_wind_game.h"

using namespace BbWindGame;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}
} // namespace

int main() {
    // BB_WIND_GAME: exactly "1"
    Expect(ParseOn("1"), "1 is on");
    Expect(!ParseOn(nullptr), "unset is off");
    Expect(!ParseOn(""), "empty is off");
    Expect(!ParseOn("0"), "0 is off");
    Expect(!ParseOn("11"), "11 is off");
    Expect(!ParseOn("1 "), "1 and a blank is off");
    Expect(!ParseOn("true"), "true is off");

    // the cut needs the sway wanted
    Expect(!CutWanted(false), "no sway wanted: no cut (also with the knob on)");

    // level and bit
    Expect(CutLevel == -1.0f, "the cut gives a sine's trough");
    Expect(GameCutBit == 16u && (GameCutBit & 3u) == 0u, "bit 16, outside Kind()'s two bits");

    // counters and the periodic text
    Counters& c = Count();
    Expect(c.sines.load() == 0 && c.draws.load() == 0, "counters start at 0");
    c.sines.fetch_add(16, std::memory_order_relaxed);
    c.draws.fetch_add(3, std::memory_order_relaxed);
    char text[256];
    const int n = ReportText(text, sizeof(text));
    Expect(n > 0 && n < int(sizeof(text)), "the line fits 256 characters");
    Expect(std::strstr(text, "16 sines") != nullptr && std::strstr(text, "3 draws") != nullptr,
           "the line says 16 sines and 3 draws");
    Expect(std::strncmp(text, "Wind game (r122):", 17) == 0, "the line starts as the log reader looks for it");
    char tiny[8];
    Expect(ReportText(tiny, sizeof(tiny)) > 0 && std::strlen(tiny) == sizeof(tiny) - 1,
           "a short buffer is cut, not overrun");

    if (failures != 0) {
        std::printf("wind game: %d failures\n", failures);
        return 1;
    }
    std::printf("wind game: ok\n");
    return 0;
}
''',
}

RT = "engine/gpu/shadps4/shader_recompiler/runtime_info.h"
PC = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_pipeline_cache.cpp"
SER = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_pipeline_serialization.cpp"
RH = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer.h"
RC = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer.cpp"
RE = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer_effects.cpp"
BR = "engine/gpu/shim/lifter/bridge.cpp"
LH = "engine/gpu/shim/lifter/lift.h"
LA = "engine/gpu/shim/lifter/lift_alu.cpp"
FP = "engine/gpu/shadps4/shader_recompiler/backend/spirv/emit_spirv_floating_point.cpp"
EC = "engine/gpu/shadps4/shader_recompiler/backend/spirv/spirv_emit_context.h"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
RD = "README.md"

SWAY_INCLUDE = '#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)\n'
GAME_INCLUDE = '#include "bbport_wind_game.h" // bbport (r122_game-wind-drive)\n'

# path -> [(anchor, text before the anchor, text after the anchor)]; the anchor must be there exactly once
EDITS = {
    RT: [
        ("    static constexpr u8 Sway = 8;\n", "",
         "    /// bbport (r122_game-wind-drive): with BB_WIND_GAME=1 a vertex shader that has the plant sway (Sway) also has\n"
         "    /// this bit: the game's own sine terms (the foliage waves of its vertex shaders) are replaced by a constant\n"
         "    /// (bbport_wind_game.h; Lifter V_SIN_F32, EmitFPSin). Never set with the knob off: keys and SPIR-V are then as\n"
         "    /// before. Bit 16: Kind() looks at bits 0 and 1 only.\n"
         "    static constexpr u8 GameCut = 16;\n"),
    ],
    PC: [
        (SWAY_INCLUDE, "", GAME_INCLUDE),
        ("               (SwayWanted(sel) ? Shader::MotionVectors::Sway : 0)); // bbport (r89_wind-foliage-sway)\n",
         "               (BbWindGame::CutWanted(SwayWanted(sel)) ? Shader::MotionVectors::GameCut : 0) | // bbport (r122_game-wind-drive)\n",
         ""),
        ("            key.motion_vectors |= Shader::MotionVectors::Sway;\n", "",
         "            if (BbWindGame::CutOn()) { // bbport (r122_game-wind-drive): the game's own plant waves are cut\n"
         "                key.motion_vectors |= Shader::MotionVectors::GameCut;\n"
         "                BbWindGame::Announce();\n"
         "            }\n"),
    ],
    SER: [
        (SWAY_INCLUDE, "", GAME_INCLUDE),
        ("        !BbWindSway::KnobOnce().on) {\n        return false;\n    }\n", "",
         "    // bbport (r122_game-wind-drive): nor a key with the game-wind cut when this run's knob is off\n"
         "    if ((sel.graphics_key.motion_vectors & Shader::MotionVectors::GameCut) != 0 && !BbWindGame::CutOn()) {\n"
         "        return false;\n"
         "    }\n"),
    ],
    RH: [
        (SWAY_INCLUDE, "", GAME_INCLUDE),
    ],
    RC: [
        ("        // bbport (r89_wind-foliage-sway): a plant's sway word (WindSwayWord); 0 for every other\n",
         "        if ((pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::GameCut) != 0) { // bbport (r122_game-wind-drive)\n"
         "            BbWindGame::Count().draws.fetch_add(1, std::memory_order_relaxed);\n"
         "        }\n",
         ""),
    ],
    RE: [
        ('        BbWind::FollowersText(s, followers, sizeof(followers));\n        BbReport::Printf("%s\\n", followers);\n', "",
         "        if (BbWindGame::CutOn()) { // bbport (r122_game-wind-drive)\n"
         "            char game[256];\n"
         "            BbWindGame::ReportText(game, sizeof(game));\n"
         '            BbReport::Printf("%s\\n", game);\n'
         "        }\n"),
    ],
    BR: [
        ("        in.vertex_sway = in.vertex_motion && (vs.motion_vectors & Shader::MotionVectors::Sway) != 0;\n", "",
         "        // bbport (r122_game-wind-drive): the game's own sine terms give a constant (Lift_::LiftVop, V_SIN_F32)\n"
         "        in.vertex_game_cut = in.vertex_sway && (vs.motion_vectors & Shader::MotionVectors::GameCut) != 0;\n"),
    ],
    LH: [
        ("    bool vertex_sway{}; // bbport (r89_wind-foliage-sway): MotionVectors::Sway, VertexSway\n", "",
         "    bool vertex_game_cut{}; // bbport (r122_game-wind-drive): MotionVectors::GameCut, V_SIN_F32 gives BbWindGame::CutLevel\n"),
    ],
    LA: [
        ('#include "lifter/lift_core.h"\n', "", GAME_INCLUDE),
        ("        return SetDstF(inst, ext_f(GLSLstd450Sin, Emit(O(spv::Op::OpFMul), t_f32, Ty::F32, {CF(6.2831853f), f(0)})));\n",
         "        if (in.vertex_game_cut) { // bbport (r122_game-wind-drive): the game's own foliage wave of a plant pipeline: its trough\n"
         "            BbWindGame::Count().sines.fetch_add(1, std::memory_order_relaxed);\n"
         "            return SetDstF(inst, CF(BbWindGame::CutLevel));\n"
         "        }\n",
         ""),
    ],
    FP: [
        ('#include "shader_recompiler/backend/spirv/spirv_emit_context.h"\n', "", GAME_INCLUDE),
        ("    return ctx.OpSin(ctx.F32[1], ctx.OpFMul(ctx.F32[1], ctx.pi_x2, value));\n",
         "    if (ctx.GameWindCut()) { // bbport (r122_game-wind-drive): the game's own foliage wave of a plant pipeline: its trough\n"
         "        BbWindGame::Count().sines.fetch_add(1, std::memory_order_relaxed);\n"
         "        return ctx.ConstF32(BbWindGame::CutLevel);\n"
         "    }\n",
         ""),
    ],
    EC: [
        ("    [[nodiscard]] bool FragmentMotion() const {\n",
         "    /// bbport (r122_game-wind-drive): a vertex shader built with MotionVectors::GameCut (the plant sway pipelines with\n"
         "    /// BB_WIND_GAME=1): the game's own v_sin_f32 terms give a constant (EmitFPSin)\n"
         "    [[nodiscard]] bool GameWindCut() const {\n"
         "        return VertexMotion() && (runtime_info.hw.vs.motion_vectors & MotionVectors::GameCut) != 0;\n"
         "    }\n",
         ""),
    ],
    CM: [
        ("target_include_directories(wind-shelter-test PRIVATE ..)\n", "",
         "# bbport (r122_game-wind-drive): the game-wind cut's knob, level, bit and counters (shim/bbport_wind_game.h);\n"
         "# also built and run by engine/build.sh --test.\n"
         "add_executable(wind-game-test EXCLUDE_FROM_ALL ../tests/test_wind_game.cpp)\n"
         "target_compile_options(wind-game-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
         "target_include_directories(wind-game-test PRIVATE ..)\n"),
    ],
    BS: [
        ("    out/wind-shelter-test\n", "",
         "    # bbport (r122_game-wind-drive): the game-wind cut's knob, level, bit and counters\n"
         '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_wind_game.cpp -o out/wind-game-test\n'
         "    out/wind-game-test\n"),
    ],
}

ROW = ("| `BB_WIND_GAME` | `1` cuts the game's own plant motion so that only our wind moves foliage (needs `BB_WIND=1` and the plant sway, "
       "`BB_WIND_SWAY` above 0, its default; the sway itself needs ray tracing): the vertex shaders of the plant sway pipelines are built "
       "with every sine of the game's own code (the 16 wave emitters of its skinned cut-out foliage shaders, whose phase runs on a time "
       "word of the draw's constants) fixed at the wave's trough, so the game's travelling foliage wave stops and the sway, lean and gusts "
       "of `BB_WIND_SWAY` (with the shelter) are the only motion, downwind. It cuts per pipeline (every draw of a plant pipeline) and in "
       "the camera pass only; the game's own particles (embers and ash at the graveyard and the alley: made by the game's CPU) and trees "
       "that move by bone palette are not changed. The log says `Wind game (r122, BB_WIND_GAME=1)` once and gives a `Wind game (r122)` "
       "line every 600 wind steps with the sines cut and the draws counted. Tip: with `BB_WIND_SPEED=0` the foliage should stand still "
       "if the cut holds. `0` or unset: as before | off |\n")


def readme_edit(text):
    lines = [l for l in text.split("\n") if l.startswith("| `BB_WIND_SHELTER_SHOW` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_WIND_SHELTER_SHOW row is there %d times, wanted 1" % len(lines))
    return (lines[0] + "\n", "", ROW)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    if path == RD:
        return [readme_edit(text)]
    return EDITS[path]


def text_checks(texts):
    rt = texts[RT]
    if rt.count("static constexpr u8 GameCut = 16;") != 1:
        raise SystemExit("text check: GameCut is not bit 16 once in runtime_info.h")
    for other in ("= 16;", "= 0x10;", "= 1u << 4;"):
        # no other u8 motion bit may use 16 (Sway = 8, CaptureUv = 4, VertexCapture = 2, VertexOutputs = 1)
        for line in rt.split("\n"):
            if "static constexpr u8" in line and other in line and "GameCut" not in line:
                raise SystemExit("text check: another u8 constant uses 16 in runtime_info.h: %r" % line)
    if "GameCutBit = 16;" not in NEW_FILES["engine/gpu/shim/bbport_wind_game.h"]:
        raise SystemExit("text check: bbport_wind_game.h GameCutBit is not 16")
    pc = texts[PC]
    if pc.count("BbWindGame::CutWanted(SwayWanted(sel))") != 1 or pc.count("BbWindGame::CutOn()") != 1 or \
            pc.count("BbWindGame::Announce();") != 1:
        raise SystemExit("text check: vk_pipeline_cache.cpp hooks")
    # the info bit comes inside the u8(...) chain, before the Sway term (the line above ends with '|')
    a = pc.find("BbWindGame::CutWanted(SwayWanted(sel))")
    b = pc.find("(SwayWanted(sel) ? Shader::MotionVectors::Sway : 0)); // bbport (r89_wind-foliage-sway)")
    if not (0 < a < b):
        raise SystemExit("text check: the info bit is not inside the u8(...) chain before the Sway term")
    la = texts[LA]
    if la.count("in.vertex_game_cut") != 1 or la.count("BbWindGame::CutLevel") != 1:
        raise SystemExit("text check: lift_alu.cpp hook")
    # the cut sits in the V_SIN case only (the V_COS line is not touched)
    i = la.find("case Op::V_SIN_F32:")
    j = la.find("in.vertex_game_cut")
    k = la.find("case Op::V_COS_F32:")
    if not (0 < i < j < k):
        raise SystemExit("text check: the lifter cut is not inside V_SIN_F32")
    fp = texts[FP]
    i = fp.find("Id EmitFPSin(")
    j = fp.find("ctx.GameWindCut()")
    k = fp.find("Id EmitFPCos(")
    if not (0 < i < j < k):
        raise SystemExit("text check: the recompiler cut is not inside EmitFPSin")
    if texts[EC].count("GameWindCut() const") != 1:
        raise SystemExit("text check: spirv_emit_context.h")
    if texts[BR].count("in.vertex_game_cut = in.vertex_sway &&") != 1 or texts[LH].count("bool vertex_game_cut{}") != 1:
        raise SystemExit("text check: bridge.cpp / lift.h")
    row = [l for l in texts[RD].split("\n") if l.startswith("| `BB_WIND_GAME` |")]
    if len(row) != 1 or "BB_WIND_SPEED=0" not in row[0]:
        raise SystemExit("text check: README row")
    for p in (RH, SER, RC, RE, CM, BS):
        if "r122" not in texts[p]:
            raise SystemExit("text check: %s has no r122 text" % p)


def state_of(cur, eds, path):
    done = todo = 0
    for anchor, before, after in eds:
        parts = [t for t in (before, after) if t]
        na, counts = cur.count(anchor), [cur.count(t) for t in parts]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                             % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R122_ROOT)" % ROOT)
    plan = []
    for path in list(EDITS) + [RD]:
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    newstate = []
    for path, text in NEW_FILES.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            newstate.append("clean")
        elif open(full, "rb").read().decode("utf-8").replace("\r\n", "\n") == text:
            newstate.append("applied")
        else:
            raise SystemExit("REFUSED %s exists with other content" % path)
    states = {p[5] for p in plan} | set(newstate)
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) + " new: " + ",".join(newstate))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for anchor, before, after in eds:
                cur = cur.replace(anchor, before + anchor + after)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW_FILES)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r122tmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path, text in NEW_FILES.items():  # new files are written with CRLF as the tree's files are
            full = os.path.join(ROOT, path)
            open(full, "wb").write(text.replace("\n", "\r\n").encode("utf-8"))
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for anchor, before, after in reversed(eds):
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r122tmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
