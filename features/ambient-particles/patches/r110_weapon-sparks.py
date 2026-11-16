# r110_weapon-sparks: FEATURE patch (goes to its own feature branch; off by default).
# .fixed (adversarial review 2026-11-15 about 23:20): falling copies only for pairs marked "*" (default
# the particle batches only), README states the rule exactly (independent of BB_PARTICLES, the key
# memory, copies on the draw at first and ending without a fade), the counter line says "additive".
# Work order item 6, ambient particles stage 2 (owner, verbatim: "Ambient particles and maybe metal
# sparks from transforming weapons").
#
# Facts it builds on (r108 spark probe, slot batch b8, 2026-11-15 21:47; lamp-test-spot and
# dark-alley, one L1 press each): the GAME ALREADY DRAWS its own transform effect. About 460-500 ms
# after the press, new additive draws (source alpha, one; depth test LessEqual, no depth write) go
# into the scene's HDR target at both places: vs 41ae600f ps 5e224cb6 (triangle-strip quads, 4
# vertices), vs df0f1658 ps 41d3ce4b (patch primitives, 3 control points, no texture, 2 targets) and
# vs 4cd21a0f ps 71c96598 (patch primitives of 1, 2 and 10 points: particle batches, the game's
# generic particle shader, with textures not drawn in the second before). The probe's pictures show a
# glowing streak along the Saw Cleaver during the transform. So r110 makes THOSE richer instead of
# spawning its own sparks at a weapon position the renderer does not know.
#
# What it does: BB_WEAPON_SPARKS=1|2 (read once at start; unset or anything else is off). The pad
# hook (scePadReadState, as r108's) notes each press of the transform button (L1). For 1500 ms after a
# press, a draw of one of the listed vertex:pixel shader pairs (default the three above;
# BB_WEAPON_SPARKS_PAIRS) that blends additively into colour target 0 (dst factor One, Add), writes no
# depth, is not in a UI pass and whose pair + bound textures were NOT drawn in the 1000 ms before the
# press ("new", as the probe judged them; a key found new stays a transform key while it is drawn) is
# drawn again right after itself, inside the same render pass with the same pipeline and bindings:
#  - BB_WEAPON_SPARKS_GAIN more times (default 2: the additive effect is 3 times as bright, which the
#    game's own bloom then spreads: a hotter core and a bigger glow);
#  - with BB_WEAPON_SPARKS=2 also BB_WEAPON_SPARKS_COPIES (default 4) falling copies of each such draw
#    of at most 64 vertices OF A PAIR MARKED "*" in the list (default: only 4cd21a0f:71c96598*, the
#    game's particle batches; review 2026-11-15: a copy moves the WHOLE draw, so copies of the glint
#    quad or of the 3-point patch draws, which may be the streak along the blade, would fly off as
#    ghost streaks; mark them with "*" in BB_WEAPON_SPARKS_PAIRS to try): the same draw with the
#    viewport moved by a throw (hashed per key and copy: sideways up to +-0.45, upwards 0.2-0.7
#    viewport heights a second, falling at 2.2 viewport heights a second squared) since the first such
#    draw of that press, each copy for its own 0.18-0.55 s (at the start they lie on the draw itself).
#    The copies keep the game's depth test against the scene depth (hidden behind walls), no bounce,
#    no fade (they end at once).
# Lines (all start with "Particles: weapon sparks (r110", so the slot runner's evidence pattern
# "^(...|Particles|...)" collects them): a once-line at start, one line per press when its window
# closes (draws of the pairs, how many new, how many drawn again, copies, first one at +ms), and every
# 10 s a counter line (presses, draws of the pairs, drawn again, extra draws, copies).
#
# Off: Rasterizer::DrawRecord tests the const member weapon_sparks_on (one test of a bool a draw);
# bbgpu_weapon_sparks_pad returns after a function-local static's mode test (one call a pad read,
# about one a frame). Nothing is recorded, no state, table or lock of the new file is touched. GPU 0,
# memory 0. On but no press: per draw one relaxed atomic load + compare, then a loop over at most 8
# shader pairs; matched draws (the listed pairs only) take a lock, a clock read, a texture hash and a
# lookup in a 512-slot table (about 0.2 us each). GPU: only in the 1.5 s after a press, about 2-6 extra
# tiny additive draws per matched draw.
#
# Files: new renderer_vulkan/vk_weapon_sparks.cpp (gpu/CMakeLists.txt's GLOB_RECURSE picks it up);
# hooks: engine/src/sys/pad.c (one call before ++reads, under the pad lock, next to r108's), bbgpu.h
# (declaration before the extern "C" block's end), tests/sys_test_host.c (WEAK stub, so build.sh
# --test's sys tests link without the GPU library), vk_rasterizer.h (3 members, before the "Lamps
# apart" line, where r108's block also goes), vk_rasterizer.cpp (one call after the draw command, at
# the start of the after-draw section), README.md (4 rows after the BB_PARTICLES_SHOW row). No shader,
# no CMake or build.sh line. Independent of r108 (a TOOL): each anchor is original text, and r108
# applies and reverts before or after r110 (proved on a copy).
#
# Use: python -I -X utf8 r110_weapon-sparks.py check | apply | revert
# Root: R110_ROOT, else <tree>. Line ends kept (CRLF in the tree; the new file is written with
# the line ends of vk_rasterizer.cpp). apply backs the edited originals up in r110_backup next to this
# script; revert takes out exactly what apply inserted and removes the new file (only when its content
# is exactly this script's).
import os, re, sys

ROOT = os.environ.get("R110_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r110_backup")
P = "engine/src/sys/pad.c"
B = "engine/gpu/bbgpu.h"
T = "engine/tests/sys_test_host.c"
H = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer.h"
C = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer.cpp"
D = "README.md"
N = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_weapon_sparks.cpp"

README_ROWS = (
    "| `BB_WEAPON_SPARKS` | Metal sparks from transforming weapons, made from the game's own transform "
    "effect (r110); independent of `BB_PARTICLES`. `1`: for 1500 ms after each press of the transform "
    "button (L1, as the game reads it) "
    "the game's draws of the listed shader pairs that blend additively into the first colour target "
    "(source alpha, one), write no depth, are not part of the UI and whose pair and bound textures were "
    "not drawn in the 1000 ms before the press are drawn again right after themselves, so the "
    "transform's sparks and glint are brighter (the game's own bloom spreads them). A pair and textures "
    "found new once count again at later presses until a check every 4 s finds them not drawn for 2 s. "
    "`2`: also, for such "
    "draws of at most 64 vertices of a pair marked `*`, falling copies, each the same whole draw moved on "
    "screen along its own "
    "throw (sideways up to 0.45 and upwards 0.2 to 0.7 viewport heights a second, falling at 2.2 viewport "
    "heights a second squared) from the press's first such draw, each for 0.18 to 0.55 s (at the start "
    "they lie on the draw itself, then they end at once, without a fade); the scene "
    "hides them behind walls as it hides the game's sparks; they do not bounce. Unset or any other value "
    "is off: then nothing of it runs. Read once at start | off |\n"
    "| `BB_WEAPON_SPARKS_GAIN` | With `BB_WEAPON_SPARKS`: how many times more such a draw is drawn, 0 to "
    "6 (`2` makes the effect 3 times as bright) | `2` |\n"
    "| `BB_WEAPON_SPARKS_COPIES` | With `BB_WEAPON_SPARKS=2`: falling copies of each such draw, 1 to 8 | `4` |\n"
    "| `BB_WEAPON_SPARKS_PAIRS` | With `BB_WEAPON_SPARKS`: the vertex:pixel shader pairs whose draws "
    "count (hexadecimal program hashes), joined by `+`, at most 8; a `*` right after a pair also gives "
    "its draws falling copies with `2`; a list that does not read whole "
    "keeps the default (the start line says so) | `41ae600f:5e224cb6+df0f1658:41d3ce4b+4cd21a0f:71c96598*` |\n")

# (anchor, before, after): the anchor stays as it is; `before` goes in front of it, `after` behind it.
# README's anchor is the whole BB_PARTICLES_SHOW row (found by its first cell; see readme_edits).
EDITS = {
P: [
("    ++reads;\n    host_unlock(&lock);\n",
 "    bbgpu_weapon_sparks_pad(pad->buttons); /* bbport (r110_weapon-sparks): BB_WEAPON_SPARKS only */\n",
 ""),
],
B: [
("#ifdef __cplusplus\n}\n#endif\n",
 "/* bbport (r110_weapon-sparks): the pad buttons the game was just given (scePadReadState);\n"
 " * BB_WEAPON_SPARKS takes the transform button's presses from them, otherwise it returns at once. */\n"
 "void bbgpu_weapon_sparks_pad(uint32_t buttons);\n",
 ""),
],
T: [
("WEAK int runtime_block_begin(int kind, uintptr_t object) { (void)kind; (void)object; return 0; }\n",
 "WEAK void bbgpu_weapon_sparks_pad(uint32_t buttons) { (void)buttons; }\n",
 ""),
],
H: [
("    /// Lamps apart (vk_point_shadow.h): something that is not a draw may touch the light targets.\n",
 "    /// bbport (r110_weapon-sparks): BB_WEAPON_SPARKS=1|2 (read once at start, off by default) draws\n"
 "    /// the game's own trick weapon transform effect again for 1.5 s after each press of the transform\n"
 "    /// button (L1): brighter, and with 2 also falling copies (vk_weapon_sparks.cpp). Called only\n"
 "    /// while weapon_sparks_on, right after the draw command.\n"
 "    static bool WeaponSparksWanted();\n"
 "    void WeaponSparksAfterDraw(const GraphicsPipeline* pipeline, bool is_indexed, u32 num_indices,\n"
 "                               u32 num_instances, u32 first_vertex, u32 first_instance);\n"
 "    const bool weapon_sparks_on = WeaponSparksWanted(); ///< bbport (r110_weapon-sparks)\n",
 ""),
],
C: [
("    BbSections::Scope after_draw_scope{BbSections::AfterDraw};\n",
 "",
 "    if (weapon_sparks_on) { // bbport (r110_weapon-sparks): BB_WEAPON_SPARKS only\n"
 "        WeaponSparksAfterDraw(pipeline, is_indexed, num_indices, num_instances, first_vertex,\n"
 "                              first_instance);\n"
 "    }\n"),
],
}

ORDER = (P, B, T, H, C, D)

# The new file, renderer_vulkan/vk_weapon_sparks.cpp (LF here; written with the tree's line ends).
NEW_TEXT = r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r110_weapon-sparks, FEATURE): metal sparks from transforming weapons, made from the game's
// own transform effect (work order item 6, ambient particles stage 2).
// The r108 spark probe found that the game draws its own effect for a trick weapon transform, about
// half a second after the press: additive draws (source alpha, one; no depth write) of three
// vertex:pixel shader pairs into the scene's HDR target (a quad glint, a 3-point patch draw and small
// particle batches of the game's particle shader). BB_WEAPON_SPARKS=1 draws those again, right after
// themselves, inside the same render pass with the same pipeline and bindings, for 1.5 s after each
// press of the transform button (L1): GAIN more times, so the effect is brighter and the game's own
// bloom spreads it. BB_WEAPON_SPARKS=2 also draws small ones (at most 64 vertices) of the pairs marked
// for it (default only the particle batches: a copy moves the whole draw, so a copied streak would fly
// off as a ghost streak) as falling copies: the same draw with the viewport moved along a throw with
// gravity, hashed per draw key and copy.
// Only draws whose pair and bound textures were not drawn in the second before the press count
// ("new", as the probe judged them), so a lamp's fire drawn with the same particle shader is left as
// it is; a key found new stays a transform key while it keeps being drawn (a second transform soon
// after the first is richer too).
// Off (BB_WEAPON_SPARKS unset or anything but 1 or 2, the default): the rasterizer calls
// WeaponSparksAfterDraw only while its const member weapon_sparks_on is true (one test of a bool a
// draw), and bbgpu_weapon_sparks_pad returns after a function-local static's mode test (one call a
// pad read). No state of this file is made, nothing is recorded: GPU 0, memory 0.
// On: per draw one relaxed atomic load and compare (once a frame the window end, the table sweep and
// the lines) and a loop over at most 8 shader pairs; a draw of a listed pair takes a lock, a clock
// read, a hash of its textures' guest addresses and a lookup in a 512-slot table. Extra GPU work only
// in the 1.5 s after a press: GAIN repeats and (2) up to COPIES copies of each new effect draw.
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>

#include "../bbgpu.h"
#include "bbport_toggles.h"
#include "input/pad.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"

namespace {

/// The transform button: L1, the bit the game reads (PAD_L1 of engine/src/sys/pad.h is the same
/// 0x400; the patch script checks it), Transform in the game's own controls (input/bindings.cpp).
constexpr std::uint32_t SparksButton = PadBits::kL1;
constexpr std::uint64_t SparksWindowNs = 1'500'000'000ull; ///< effect draws count this long after a press
constexpr std::uint64_t SparksBeforeNs = 1'000'000'000ull; ///< new: not drawn this long before the press
constexpr std::uint64_t SparksForgetNs = 2'000'000'000ull; ///< table keys not drawn this long are dropped
constexpr std::uint64_t SparksSweepNs = 4'000'000'000ull;
constexpr std::uint64_t SparksReportNs = 10'000'000'000ull; ///< the counter line
constexpr std::uint32_t SparksMaxPairs = 8;
constexpr std::uint32_t SparksTableBits = 9;
constexpr std::uint32_t SparksTableSize = 1u << SparksTableBits; ///< 512 keys
constexpr std::uint32_t SparksProbeLength = 16;
constexpr std::uint32_t SparksDefaultGain = 2, SparksMaxGain = 6;
constexpr std::uint32_t SparksDefaultCopies = 4, SparksMaxCopies = 8;
constexpr std::uint64_t SparksCopyMaxVertices = 64; ///< falling copies only of small draws
// The throw of a falling copy, in viewport heights (and seconds): sideways up to +-SideSpeed/2,
// upwards UpMin to UpMin + UpRange, falling at Gravity; each copy lives LifeMin to LifeMin + LifeRange.
constexpr float SparksSideSpeed = 0.9f;
constexpr float SparksUpMin = 0.2f, SparksUpRange = 0.5f;
constexpr float SparksGravity = 2.2f;
constexpr float SparksLifeMin = 0.18f, SparksLifeRange = 0.37f;

struct SparksPair {
    std::uint64_t vs = 0, ps = 0;
    bool copies = false; ///< "*" in the list: with BB_WEAPON_SPARKS=2 its small draws get falling copies
};

/// The pairs the r108 probe found new after a transform press at two places (21:47). Only the
/// particle batches get falling copies by default (a copy moves the whole draw).
constexpr SparksPair SparksDefaultPairs[] = {
    {0x41ae600full, 0x5e224cb6ull, false}, // triangle-strip quads (a glint)
    {0xdf0f1658ull, 0x41d3ce4bull, false}, // 3-point patch draws, no texture, 2 targets
    {0x4cd21a0full, 0x71c96598ull, true},  // the game's particle batches (1, 2, 10 points)
};

struct SparksConfig {
    std::uint32_t mode = 0; ///< 0 off, 1 brighter, 2 brighter and falling copies
    std::uint32_t gain = SparksDefaultGain;
    std::uint32_t copies = SparksDefaultCopies;
    std::uint32_t pair_count = 0;
    std::array<SparksPair, SparksMaxPairs> pairs{};
    bool pairs_from_env = false;
    bool pairs_unread = false; ///< BB_WEAPON_SPARKS_PAIRS was set but did not read whole
};

std::uint32_t SparksNumber(const char* name, std::uint32_t fallback, std::uint32_t lo, std::uint32_t hi) {
    const char* value = std::getenv(name);
    if (value == nullptr || value[0] == '\0') {
        return fallback;
    }
    char* end = nullptr;
    const long number = std::strtol(value, &end, 10);
    if (end == value) {
        return fallback;
    }
    return std::uint32_t(std::clamp<long>(number, long(lo), long(hi)));
}

const SparksConfig& SparksGet() {
    static const SparksConfig config = [] {
        SparksConfig c;
        const char* mode = std::getenv("BB_WEAPON_SPARKS");
        if (mode != nullptr && (mode[0] == '1' || mode[0] == '2') && mode[1] == '\0') {
            c.mode = std::uint32_t(mode[0] - '0');
        }
        if (c.mode == 0) {
            return c;
        }
        c.gain = SparksNumber("BB_WEAPON_SPARKS_GAIN", SparksDefaultGain, 0, SparksMaxGain);
        c.copies = SparksNumber("BB_WEAPON_SPARKS_COPIES", SparksDefaultCopies, 1, SparksMaxCopies);
        for (const SparksPair& pair : SparksDefaultPairs) {
            c.pairs[c.pair_count++] = pair;
        }
        if (const char* list = std::getenv("BB_WEAPON_SPARKS_PAIRS"); list != nullptr && list[0] != '\0') {
            std::array<SparksPair, SparksMaxPairs> read{};
            std::uint32_t count = 0;
            const char* at = list;
            while (*at != '\0' && count < SparksMaxPairs) {
                char* end = nullptr;
                const unsigned long long vs = std::strtoull(at, &end, 16);
                if (end == at || *end != ':') {
                    break;
                }
                const char* ps_at = end + 1;
                const unsigned long long ps = std::strtoull(ps_at, &end, 16);
                if (end == ps_at) {
                    break;
                }
                const bool copies = *end == '*';
                read[count++] = {std::uint64_t(vs), std::uint64_t(ps), copies};
                at = copies ? end + 1 : end;
                while (*at == '+' || *at == ';' || *at == ' ') {
                    ++at;
                }
            }
            if (count != 0 && *at == '\0') {
                c.pairs = read;
                c.pair_count = count;
                c.pairs_from_env = true;
            } else {
                c.pairs_unread = true;
            }
        }
        return c;
    }();
    return config;
}

std::uint64_t SparksNowNs() {
    return std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(
                             std::chrono::steady_clock::now().time_since_epoch())
                             .count());
}

/// Written by the pad side (the game's scePadReadState, under the pad lock), read by the draws.
std::atomic<std::uint64_t> sparks_press_ns{0}; ///< the last press (steady clock), 0: none yet
std::atomic<std::uint32_t> sparks_presses{0};  ///< presses since the start
std::atomic<std::uint32_t> sparks_frame{~0u};  ///< the frame number the once-a-frame work last ran for

struct SparksSeen {
    std::uint32_t key = 0;    ///< 0: an empty slot
    std::uint32_t window = 0; ///< the press window it was last judged in
    std::uint64_t last_ns = 0;
    bool fresh = false;     ///< new in that window: drawn again
    bool transform = false; ///< found new once; stays so while it is drawn (dropped after 2 s unseen)
};

struct SparksState {
    std::mutex lock; // draws are recorded on the GPU command thread or on stage B
    std::array<SparksSeen, SparksTableSize> seen{};
    std::uint64_t handled_press = 0; ///< the last press taken
    std::uint64_t open_press = 0;    ///< the open window's press, 0: none open
    std::uint64_t burst_ns = 0;      ///< the open window's first draw drawn again, 0: none yet
    std::uint32_t window = 0;        ///< windows opened since the start
    std::uint32_t press_number = 0;
    std::uint64_t last_sweep_ns = 0, report_ns = 0;
    std::uint32_t reported_presses = 0;
    // The open window's counts (for its line)
    std::uint64_t w_draws = 0, w_new = 0, w_keys = 0, w_extra = 0, w_copies = 0;
    // Counts since the last counter line
    std::uint64_t matched = 0, boosted = 0, extra = 0, copies = 0;
};

SparksState& SparksStateGet() {
    static SparksState state;
    return state;
}

std::uint32_t SparksHash(std::uint32_t a, std::uint32_t b) {
    std::uint32_t h = a * 0x9e3779b1u ^ (b + 0x7f4a7c15u) * 0x85ebca6bu;
    h ^= h >> 15;
    h *= 0x2c1b3c6du;
    h ^= h >> 12;
    h *= 0x297a2d39u;
    h ^= h >> 15;
    return h;
}

float SparksUnit(std::uint32_t h, std::uint32_t shift) {
    return float((h >> shift) & 0xffu) * (1.0f / 255.0f);
}

/// The key's slot: the whole probe run is searched first (a sweep leaves holes in it), then an
/// empty slot or the least recently drawn one of the run is taken.
SparksSeen& SparksFind(SparksState& s, std::uint32_t key) {
    const std::uint32_t start = (key * 0x9e3779b1u) >> (32 - SparksTableBits);
    SparksSeen* spare = nullptr;
    for (std::uint32_t i = 0; i < SparksProbeLength; ++i) {
        SparksSeen& e = s.seen[(start + i) & (SparksTableSize - 1)];
        if (e.key == key) {
            return e;
        }
        if (spare == nullptr || (spare->key != 0 && (e.key == 0 || e.last_ns < spare->last_ns))) {
            spare = &e;
        }
    }
    *spare = SparksSeen{};
    spare->key = key;
    return *spare;
}

void SparksOpen(SparksState& s, std::uint64_t press) {
    s.open_press = press;
    s.burst_ns = 0;
    ++s.window;
    s.press_number = sparks_presses.load(std::memory_order_relaxed);
    s.w_draws = s.w_new = s.w_keys = s.w_extra = s.w_copies = 0;
}

/// The open window's line (written on bb:Stats, not on this draw thread), then it is closed.
void SparksClose(SparksState& s) {
    const BbReport::Capture lines;
    const unsigned long long first =
        s.burst_ns != 0 ? (s.burst_ns - std::min(s.burst_ns, s.open_press)) / 1'000'000ull : 0ull;
    BbReport::Printf("Particles: weapon sparks (r110): press %u (transform, L1): in the %llu ms after it "
                     "%llu draws of the listed shader pairs (additive, no depth write), %llu of them "
                     "(%llu keys) new against the %llu ms before the press, drawn again %llu times "
                     "and as %llu falling copies%s%llu ms\n",
                     s.press_number, (unsigned long long)(SparksWindowNs / 1'000'000ull),
                     (unsigned long long)s.w_draws, (unsigned long long)s.w_new,
                     (unsigned long long)s.w_keys, (unsigned long long)(SparksBeforeNs / 1'000'000ull),
                     (unsigned long long)s.w_extra, (unsigned long long)s.w_copies,
                     s.burst_ns != 0 ? "; the first at +" : "; none drawn again, window ",
                     s.burst_ns != 0 ? first : (unsigned long long)(SparksWindowNs / 1'000'000ull));
    s.open_press = 0;
    s.burst_ns = 0;
}

/// Once a frame: a press no listed draw has seen yet opens its window, an expired window is closed,
/// old keys are dropped, and every 10 s the counter line.
void SparksFrame(const SparksConfig& cfg) {
    SparksState& s = SparksStateGet();
    const std::uint64_t now = SparksNowNs();
    const std::scoped_lock guard{s.lock};
    if (const std::uint64_t press = sparks_press_ns.load(std::memory_order_acquire);
        press != s.handled_press) {
        s.handled_press = press;
        if (s.open_press != 0) {
            SparksClose(s);
        }
        SparksOpen(s, press);
    }
    if (s.open_press != 0 && now >= s.open_press + SparksWindowNs) {
        SparksClose(s);
    }
    if (now - s.last_sweep_ns >= SparksSweepNs) {
        s.last_sweep_ns = now;
        for (SparksSeen& e : s.seen) {
            if (e.key != 0 && e.last_ns + SparksForgetNs < now) {
                e = SparksSeen{};
            }
        }
    }
    if (s.report_ns == 0) {
        s.report_ns = now;
        return;
    }
    if (now - s.report_ns < SparksReportNs) {
        return;
    }
    const std::uint32_t presses = sparks_presses.load(std::memory_order_relaxed);
    const BbReport::Capture lines;
    BbReport::Printf("Particles: weapon sparks (r110, BB_WEAPON_SPARKS=%u): in the last %.1f s %u "
                     "transform presses, %llu additive draws of the listed shader pairs, %llu of them drawn "
                     "again (%llu extra draws, %llu falling copies)\n",
                     cfg.mode, double(now - s.report_ns) * 1e-9, presses - s.reported_presses,
                     (unsigned long long)s.matched, (unsigned long long)s.boosted,
                     (unsigned long long)s.extra, (unsigned long long)s.copies);
    s.reported_presses = presses;
    s.report_ns = now;
    s.matched = s.boosted = s.extra = s.copies = 0;
}

} // namespace

// The pad side: engine/src/sys/pad.c, pad_read_state, after the pad is sampled (under its lock).
extern "C" void bbgpu_weapon_sparks_pad(uint32_t buttons) {
    if (SparksGet().mode == 0) {
        return;
    }
    static std::uint32_t held = 0; // only touched under the pad lock
    if ((buttons & SparksButton) != 0 && (held & SparksButton) == 0) {
        sparks_press_ns.store(SparksNowNs(), std::memory_order_release);
        sparks_presses.fetch_add(1, std::memory_order_relaxed);
    }
    held = buttons;
}

namespace Vulkan {

bool Rasterizer::WeaponSparksWanted() {
    const SparksConfig& cfg = SparksGet();
    if (cfg.mode == 0) {
        return false;
    }
    char copies[128];
    u32 copy_pairs = 0;
    for (u32 i = 0; i < cfg.pair_count; ++i) {
        copy_pairs += cfg.pairs[i].copies ? 1u : 0u;
    }
    if (cfg.mode == 2) {
        std::snprintf(copies, sizeof(copies),
                      "; those of at most %llu vertices of the %u pairs marked * also as %u falling "
                      "copies (BB_WEAPON_SPARKS_COPIES)",
                      (unsigned long long)SparksCopyMaxVertices, copy_pairs, cfg.copies);
    } else {
        std::snprintf(copies, sizeof(copies), "; no falling copies (they need BB_WEAPON_SPARKS=2)");
    }
    std::printf("Particles: weapon sparks (r110, BB_WEAPON_SPARKS=%u): for %llu ms after each press of "
                "the transform button (L1, pad bit 0x%x, as the game reads it) the game's draws of %u "
                "shader pairs (%s) that blend additively into colour target 0, write no depth, are not "
                "UI and were not drawn in the %llu ms before the press are drawn %u times more "
                "(BB_WEAPON_SPARKS_GAIN)%s. Nothing else changes\n",
                cfg.mode, (unsigned long long)(SparksWindowNs / 1'000'000ull), SparksButton,
                cfg.pair_count,
                cfg.pairs_from_env ? "BB_WEAPON_SPARKS_PAIRS"
                : cfg.pairs_unread ? "the default list: BB_WEAPON_SPARKS_PAIRS did not read whole"
                                   : "the default list",
                (unsigned long long)(SparksBeforeNs / 1'000'000ull), cfg.gain, copies);
    return true;
}

void Rasterizer::WeaponSparksAfterDraw(const GraphicsPipeline* pipeline, bool is_indexed,
                                       u32 num_indices, u32 num_instances, u32 first_vertex,
                                       u32 first_instance) {
    const SparksConfig& cfg = SparksGet();
    const u32 frame = BbStats::frame_number.load(std::memory_order_relaxed);
    if (sparks_frame.load(std::memory_order_relaxed) != frame) {
        sparks_frame.store(frame, std::memory_order_relaxed);
        SparksFrame(cfg);
    }
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    if (ps == nullptr || num_indices == 0 || num_instances == 0) {
        return;
    }
    const u64 vs_hash = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
    u32 pair = 0;
    while (pair < cfg.pair_count &&
           (cfg.pairs[pair].vs != vs_hash || cfg.pairs[pair].ps != ps->pgm_hash)) {
        ++pair;
    }
    if (pair == cfg.pair_count) {
        return;
    }
    // Additive into colour target 0 (dst factor One, Add), no depth write, not a UI pass.
    const auto& regs = Regs();
    const auto& blend = regs.blend_control[0];
    const u32 mrt_mask = pipeline->GetGraphicsKey().mrt_mask;
    if ((mrt_mask & 1u) == 0 || !cb_descs[0].first || !blend.enable ||
        regs.color_buffers[0].info.blend_bypass ||
        blend.color_dst_factor != AmdGpu::BlendControl::BlendFactor::One ||
        blend.color_func != AmdGpu::BlendControl::BlendFunc::Add ||
        regs.depth_control.depth_write_enable || ui_pass.active) {
        return;
    }
    // The key: the pair and the guest addresses of the textures it reads. dc.bound_images lists the
    // draw's colour targets, then its depth target, then every stage's images (as the probe reads it).
    auto& dc = Dc();
    u32 targets = 0;
    for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
        targets += (((mrt_mask >> cb) & 1u) != 0 && cb_descs[cb].first) ? 1u : 0u;
    }
    const std::size_t own = targets + (db_desc.first ? 1u : 0u);
    u64 texture_hash = 0xcbf29ce484222325ull ^ (u64(pair) << 56);
    for (std::size_t i = own; i < dc.bound_images.size(); ++i) {
        texture_hash = (texture_hash ^ texture_cache.GetImage(dc.bound_images[i]).info.guest_address) *
                       0x100000001b3ull;
    }
    const u32 key = u32(texture_hash ^ (texture_hash >> 32)) | 1u;
    const u64 now = SparksNowNs();

    SparksState& s = SparksStateGet();
    std::unique_lock guard{s.lock};
    ++s.matched;
    if (const u64 press = sparks_press_ns.load(std::memory_order_acquire); press != s.handled_press) {
        s.handled_press = press;
        if (s.open_press != 0) {
            SparksClose(s);
        }
        SparksOpen(s, press);
    }
    if (s.open_press != 0 && now >= s.open_press + SparksWindowNs) {
        SparksClose(s);
    }
    SparksSeen& e = SparksFind(s, key);
    const bool known = e.last_ns != 0;
    bool again = false;
    if (s.open_press != 0) {
        ++s.w_draws;
        if (e.window != s.window) {
            e.window = s.window;
            const bool drawn_before = known && e.last_ns + SparksBeforeNs >= s.open_press;
            e.fresh = e.transform || !drawn_before;
            e.transform = e.fresh;
            s.w_keys += e.fresh ? 1u : 0u;
        }
        again = e.fresh;
    }
    e.last_ns = now;
    if (!again) {
        return;
    }
    if (s.burst_ns == 0) {
        s.burst_ns = now;
    }
    // Falling copies (BB_WEAPON_SPARKS=2): small draws of the pairs marked "*" only, not screen-space
    // ones (their viewport is the 16K window, not the target).
    std::array<std::array<float, 2>, SparksMaxCopies> offsets{};
    u32 copy_count = 0;
    const auto& viewports = scheduler.GetDynamicState().viewports;
    if (cfg.mode == 2 && cfg.pairs[pair].copies && !regs.IsClipDisabled() && !viewports.empty() &&
        u64(num_indices) * num_instances <= SparksCopyMaxVertices) {
        const float height = std::abs(viewports[0].height);
        const float t = float(now - s.burst_ns) * 1e-9f;
        for (u32 i = 0; i < cfg.copies; ++i) {
            const u32 h = SparksHash(key, i);
            if (t > SparksLifeMin + SparksLifeRange * SparksUnit(h, 24)) {
                continue;
            }
            const float side = (SparksUnit(h, 0) - 0.5f) * SparksSideSpeed;
            const float up = SparksUpMin + SparksUpRange * SparksUnit(h, 8);
            offsets[copy_count++] = {side * t * height,
                                     (0.5f * SparksGravity * t * t - up * t) * height};
        }
    }
    const u32 gain = cfg.gain;
    ++s.w_new;
    ++s.boosted;
    s.w_extra += gain;
    s.extra += gain;
    s.w_copies += copy_count;
    s.copies += copy_count;
    guard.unlock();
    if (gain == 0 && copy_count == 0) {
        return;
    }
    // Right after the game's draw: same pass, pipeline, bindings and dynamic state. The copies move
    // the viewport (all of them, as the draw has them) and put it back after.
    const Scheduler::R21Neutral r21_neutral{scheduler};
    if (copy_count == 0) {
        scheduler.Record([=](vk::CommandBuffer cmdbuf) {
            for (u32 i = 0; i < gain; ++i) {
                if (is_indexed) {
                    cmdbuf.drawIndexed(num_indices, num_instances, 0, s32(first_vertex), first_instance);
                } else {
                    cmdbuf.draw(num_indices, num_instances, first_vertex, first_instance);
                }
            }
        });
        return;
    }
    const Viewports original = viewports;
    scheduler.Record([=](vk::CommandBuffer cmdbuf) {
        for (u32 i = 0; i < gain + copy_count; ++i) {
            if (i >= gain) {
                Viewports moved = original;
                for (vk::Viewport& viewport : moved) {
                    viewport.x += offsets[i - gain][0];
                    viewport.y += offsets[i - gain][1];
                }
                cmdbuf.setViewportWithCount(moved);
            }
            if (is_indexed) {
                cmdbuf.drawIndexed(num_indices, num_instances, 0, s32(first_vertex), first_instance);
            } else {
                cmdbuf.draw(num_indices, num_instances, first_vertex, first_instance);
            }
        }
        cmdbuf.setViewportWithCount(original);
    });
}

} // namespace Vulkan
'''


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def readme_edits(cur):
    """README: the anchor is the BB_PARTICLES_SHOW row as it is now (found by its first cell, once)."""
    rows = [l for l in cur.split("\n") if l.startswith("| `BB_PARTICLES_SHOW` |")]
    if len(rows) != 1:
        raise SystemExit("REFUSED %s: the BB_PARTICLES_SHOW row is there %d times (wanted once)" % (D, len(rows)))
    return [(rows[0] + "\n", "", README_ROWS)]


# Text checks on the result: the ties a compiler cannot check.
def text_checks(texts):
    n = texts[N]
    pad_h = load("engine/src/sys/pad.h")[2]
    kl1 = load("engine/gpu/shim/input/pad.h")[2]
    if "PAD_L1 = 0x400," not in pad_h or "kL1 = 0x400" not in kl1 or "namespace PadBits {" not in kl1 or \
            n.count("constexpr std::uint32_t SparksButton = PadBits::kL1;") != 1:
        raise SystemExit("text check: the transform button is not L1 = 0x400 in pad.h, input/pad.h and r110")
    if '{"transform", "Transform", "L1.' not in load("engine/gpu/shim/input/bindings.cpp")[2]:
        raise SystemExit("text check: input/bindings.cpp no longer names L1 the transform button")
    toggles = load("engine/gpu/shim/bbport_toggles.h")[2]
    if "class Capture {" not in toggles or "inline void Printf(const char* format, ...)" not in toggles or \
            "inline std::atomic<std::uint32_t> frame_number{0};" not in toggles:
        raise SystemExit("text check: BbReport::Capture/Printf or BbStats::frame_number changed")
    sched = load("engine/gpu/shadps4/video_core/renderer_vulkan/vk_scheduler.h")[2]
    for want in ("using Viewports = boost::container::static_vector<vk::Viewport, AmdGpu::NUM_VIEWPORTS>;",
                 "    Viewports viewports{};", "    DynamicState& GetDynamicState() {", "    class R21Neutral {",
                 "emit([v = viewports](vk::CommandBuffer c) { c.setViewportWithCount(v); });"):
        if sched.count(want) != 1:
            raise SystemExit("text check: vk_scheduler.h no longer holds %r once" % want)
    regs = load("engine/gpu/shadps4/video_core/amdgpu/regs_color.h")[2]
    if "    enum class BlendFactor : u32 {\n        Zero = 0,\n        One = 1," not in regs or \
            "    enum class BlendFunc : u32 {\n        Add = 0," not in regs:
        raise SystemExit("text check: BlendControl's One/Add changed")
    for path, want, k in ((B, "void bbgpu_weapon_sparks_pad(uint32_t buttons);", 1),
                          (N, 'extern "C" void bbgpu_weapon_sparks_pad(uint32_t buttons) {', 1),
                          (T, "WEAK void bbgpu_weapon_sparks_pad(uint32_t buttons) { (void)buttons; }", 1),
                          (P, "bbgpu_weapon_sparks_pad(pad->buttons);", 1),
                          (P, '#include "gpu/bbgpu.h"', 1),
                          (H, "    static bool WeaponSparksWanted();", 1),
                          (H, "    void WeaponSparksAfterDraw(const GraphicsPipeline* pipeline, bool is_indexed, u32 num_indices,\n"
                              "                               u32 num_instances, u32 first_vertex, u32 first_instance);", 1),
                          (H, "    const bool weapon_sparks_on = WeaponSparksWanted();", 1),
                          (N, "bool Rasterizer::WeaponSparksWanted() {", 1),
                          (N, "void Rasterizer::WeaponSparksAfterDraw(const GraphicsPipeline* pipeline, bool is_indexed,\n"
                              "                                       u32 num_indices, u32 num_instances, u32 first_vertex,\n"
                              "                                       u32 first_instance) {", 1),
                          (C, "WeaponSparksAfterDraw(pipeline, is_indexed, num_indices, num_instances, first_vertex,", 1),
                          (N, "std::printf(", 1),  # the once-line only; the others go through BbReport
                          (N, "BbReport::Printf(", 2),
                          (D, "| `BB_WEAPON_SPARKS` |", 1)):
        if texts[path].count(want) != k:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, want[:60], texts[path].count(want), k))
    # every line starts with "Particles: weapon sparks (r110" (the slot runner's evidence pattern)
    if len(re.findall(r'"Particles: weapon sparks \(r110', n)) != 3:
        raise SystemExit("text check: not 3 lines starting 'Particles: weapon sparks (r110'")
    # the pad call sits under the pad lock, after the pad is sampled, in pad_read_state
    p = texts[P]
    a, b, c, d = (p.find("static SYS_ABI int32_t pad_read_state("), p.find("    host_lock(&lock);\n    sample(pad);\n"),
                  p.find("bbgpu_weapon_sparks_pad(pad->buttons);"), p.find("    ++reads;\n    host_unlock(&lock);\n"))
    if not (0 <= a < b < c < d):
        raise SystemExit("text check: the pad call is not between sample(pad) and ++reads under the lock")
    # the draw hook: in DrawRecord, after the draw command, before the after-draw effects
    cs = texts[C]
    order = [cs.find(x) for x in ("void Rasterizer::DrawRecord(", "    const u32 num_indices = regs.num_indices;\n",
                                  "    const u32 first_instance = instance_offset;\n",
                                  "    scheduler.RecordCrumb(crumb, [=](vk::CommandBuffer cmdbuf) {",
                                  "WeaponSparksAfterDraw(pipeline, is_indexed,",
                                  "EffectsAfterDraw(regs, pipeline, is_indexed, num_indices, num_instances, first_vertex);",
                                  "void Rasterizer::DrawIndirect(")]
    if not all(0 <= x < y for x, y in zip(order, order[1:])):
        raise SystemExit("text check: the draw hook is not in DrawRecord between the draw and the after-draw effects")
    # README numbers tied to the code
    row = [l for l in texts[D].split("\n") if l.startswith("| `BB_WEAPON_SPARKS` |")][0]
    ties = [("constexpr std::uint64_t SparksWindowNs = 1'500'000'000ull;", row, "for 1500 ms after"),
            ("constexpr std::uint64_t SparksBeforeNs = 1'000'000'000ull;", row, "in the 1000 ms before"),
            ("constexpr std::uint64_t SparksCopyMaxVertices = 64;", row, "at most 64 vertices"),
            ("constexpr float SparksSideSpeed = 0.9f;", row, "sideways up to 0.45"),
            ("constexpr float SparksUpMin = 0.2f, SparksUpRange = 0.5f;", row, "upwards 0.2 to 0.7"),
            ("constexpr float SparksGravity = 2.2f;", row, "falling at 2.2"),
            ("constexpr float SparksLifeMin = 0.18f, SparksLifeRange = 0.37f;", row, "for 0.18 to 0.55 s"),
            ("constexpr std::uint32_t SparksDefaultGain = 2, SparksMaxGain = 6;",
             [l for l in texts[D].split("\n") if l.startswith("| `BB_WEAPON_SPARKS_GAIN` |")][0], "0 to 6 (`2` makes the effect 3 times as bright) | `2` |"),
            ("constexpr std::uint32_t SparksDefaultCopies = 4, SparksMaxCopies = 8;",
             [l for l in texts[D].split("\n") if l.startswith("| `BB_WEAPON_SPARKS_COPIES` |")][0], "1 to 8 | `4` |"),
            ("constexpr std::uint32_t SparksMaxPairs = 8;",
             [l for l in texts[D].split("\n") if l.startswith("| `BB_WEAPON_SPARKS_PAIRS` |")][0], "at most 8"),
            ("    {0x41ae600full, 0x5e224cb6ull, false}, // triangle-strip quads (a glint)\n"
             "    {0xdf0f1658ull, 0x41d3ce4bull, false}, // 3-point patch draws, no texture, 2 targets\n"
             "    {0x4cd21a0full, 0x71c96598ull, true},  // the game's particle batches (1, 2, 10 points)\n",
             [l for l in texts[D].split("\n") if l.startswith("| `BB_WEAPON_SPARKS_PAIRS` |")][0],
             "`41ae600f:5e224cb6+df0f1658:41d3ce4b+4cd21a0f:71c96598*`"),
            # copies only of the pairs marked "*" (review 2026-11-15)
            ("    if (cfg.mode == 2 && cfg.pairs[pair].copies && !regs.IsClipDisabled() && !viewports.empty() &&",
             row, "of a pair marked `*`"),
            ("                const bool copies = *end == '*';",
             [l for l in texts[D].split("\n") if l.startswith("| `BB_WEAPON_SPARKS_PAIRS` |")][0],
             "a `*` right after a pair also gives its draws falling copies"),
            ("constexpr std::uint64_t SparksForgetNs = 2'000'000'000ull;", row, "not drawn for 2 s"),
            ("constexpr std::uint64_t SparksSweepNs = 4'000'000'000ull;", row, "a check every 4 s")]
    for code, line, words in ties:
        if n.count(code) != 1 or words not in line:
            raise SystemExit("text check: README and code disagree on %r / %r" % (code[:50], words))


def state_of(cur, eds, path):
    """'applied' (anchor once, every inserted text once), 'clean' (anchor once, none of them), else refuse."""
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


def new_state(eol):
    full = os.path.join(ROOT, N)
    if not os.path.exists(full):
        return "clean"
    if open(full, "rb").read() == NEW_TEXT.replace("\n", eol).encode("utf-8"):
        return "applied"
    raise SystemExit("REFUSED %s exists with other content" % N)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R110_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        eds = readme_edits(cur) if path == D else EDITS[path]
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    new_eol = [p[3] for p in plan if p[0] == C][0]
    states = {p[5] for p in plan} | {new_state(new_eol)}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) +
                         ", %s %s" % (N, new_state(new_eol)))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for anchor, before, after in eds:
                cur = cur.replace(anchor, before + anchor + after)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        out[N] = NEW_TEXT
        return out

    if cmd == "check":
        if state == "applied":
            texts = {p[0]: p[4] for p in plan}
            texts[N] = NEW_TEXT
            text_checks(texts)
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, 1 new file; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
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
            tmp = full + ".r110tmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        full = os.path.join(ROOT, N)
        open(full + ".r110tmp", "wb").write(NEW_TEXT.replace("\n", new_eol).encode("utf-8"))
        os.replace(full + ".r110tmp", full)
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
        tmp = full + ".r110tmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    os.remove(os.path.join(ROOT, N))
    print("reverted")


main()
