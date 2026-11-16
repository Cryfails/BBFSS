# r112q_hang-bracket-route (FEATURE fix + TOOL parts, behind BB_WIND_HANG=1; off with it): on top of r112p_hang-gpu-palette-lanterns, r120 and
# everything through build 64 (r112 ... r112p applied). Lane of wave 54; the other lane (r120b) touches the test camera / test goto code.
# GRADE: FEATURE = BB_WIND_HANG_BOX_RETRY (a box-judged hanging thing the GPU box found moving is judged again), the hang shader cache version
# of BB_WIND_HANG_PROOF; TOOL (test aids, they go to the test-tools branch with the survey knobs) = the route lines (BB_WIND_HANG_FIND=1),
# BB_WIND_HANG_FORCE, the writer watch's other paths. Nothing here runs without BB_WIND_HANG=1; the route lines need BB_WIND_HANG_FIND=1.
#
# WHAT b64 SHOWED (b64_s4.log, b64_s5.log, b64_reports.txt) AND WHAT THE CODE SAYS (read, nothing run)
#  - 35 refused streams, 33 judged by the GPU box; 763 / 6600 / 4149 draws got a push in the first three 600-frame windows (the camera
#    stands at the spawn), then 0 and 0 (the camera looks up after settle:25); 'GPU judge: 15 streams: 13 moved' at the end. The pictures are
#    taken after the look-up: no push of any box-judged stream at that time. A box that grew 0.25 m is 'a character for good' (BoxFinal,
#    BoxBook::Final: never judged again), and the box of a stream drawn at several places is the UNION of the places the camera sees: a camera
#    turn changes it by metres. So the first broken link for a box-judged lantern is plausibly its judge, which marks it a mover for good the
#    first time the camera turns. FIX: BB_WIND_HANG_BOX_RETRY (default 120 frames, 0 = r112p's rule): a stream with box_only set whose box
#    was found moving, even by 0.25 m or more, is due again that many frames after (BoxBook::DueSoft); r112h's holds (the hunter, indoors) and
#    r112e's rules for streams that are not box-judged are unchanged. NOT proven in the game: the route lines and BB_WIND_HANG_FORCE decide.
#  - The census does not name vertex shaders, the survey lists a stream only when the scene has a box of it that fits, so 'e859b6d9' was never
#    in a line (b63's survey lines put the e859b6d9 streams 1.2 m over the ground at the fence posts, not in the trees: the lantern in the
#    lower right of the looking-up picture may not be an e859b6d9 stream at all). FIX: the ROUTE LINES, one a stream group (vs:ps), see
#    bbport_wind_hang_route.h; the vs e859b6d9 always has a line; BB_WIND_TWIGS_PICK on the lantern's pixels (jobs) names the draw there.
#  - 'palette pages watched 8, writers found 0': the watch heard only the written storage bindings of BindBuffers. The buffer cache's GPU-modified
#    flag is set by every ObtainBuffer(.., is_written): also a DMA copy or fill destination (CopyBuffer, FillBuffer), a guest-memory write
#    (WriteGuestMemory) and a command write (WriteDataOnGpu, through the in-place write tick). FIX: the watch hears those four paths too (one hook
#    line each), a hit names 'a DMA copy destination (no shader)' instead of a shader; with no writer found a line says what that means.
#  - The proof's cyan never showed: BB_WIND_HANG_PROOF changes the lifter's SPIR-V but not the serialized shader's binary version, so a warm shader
#    cache gave back the shaders made with no tint (and the recompiler's shaders have no tint at all). FIX: with the proof on every sway vertex
#    shader's binary version gets 100000 (ProofBinaryAdd: a cached shader of a run without the proof is not loaded, the proof run's own are
#    saved under their version), and the pipeline cache now notes which emitter made each vertex shader with BB_WIND_HANG=1 too (the route line's
#    'shader lifted | RECOMPILED (no counters, no tint) | path not noted (shader from the cache)'). With the proof off the version is as before.
#  - BB_WIND_HANG_FORCE (TOOL): 'all' or up to four vertex shader hashes in hex, ':' between them: a skinned draw of such a sway pipeline that no
#    rule took gets a hang word with the live BB_WIND_HANG_STATIC_GAIN as its ramp, no judge, no census, no r112h rule. If the lantern leans with
#    it (and not with live BB_WIND_HANG_PUSH=0) the word-to-picture chain is sound and the judges are the break; if it does not, the break is
#    in the shader or the pipeline (the route line says which emitter made it).
#
# SHARED LINES TOUCHED (the lane r120b touches the test camera / test goto code only: none of these)
#  vk_rasterizer.h: one include after r112b's, one declaration block before r112b's, two members after hang_filled.
#  vk_rasterizer.cpp: two lines in the Motion block (mark before `const u32 sway =`, note before r112h's `no_param` line), one writer-watch line in each of
#   FillBuffer, CopyBuffer, WriteGuestMemory, WriteDataOnGpu.
#  vk_rasterizer_effects.cpp: WindSwayWord (the force: 2 edits), WindHangVerdict (the retry: 1 edit), new functions before the survey's report,
#   the report block (2 inserts before r112p's lines and before r112's clears).
#  vk_pipeline_cache.cpp: one condition. vk_pipeline_serialization.cpp: three edits. bbport_wind_hang.h / _gpu.h / _still.h: additions.
#  README.md (3 rows before BB_WIND_HANG_PROOF), gpu/CMakeLists.txt and build.sh (one test after r112p's).
#
# COST WHEN OFF: every new line is behind BB_WIND_HANG (the knob is read once) or BbWindHangRoute::On() (BB_WIND_HANG_FIND, a static bool); the
# Motion block pays one static bool test a draw; the watch hooks pay a relaxed load of a false atomic. No shader or SPIR-V change without
# BB_WIND_HANG_PROOF=1 (the version add), so a build with the knobs off is byte-identical.
#
# Use: python -I -X utf8 r112q_hang-bracket-route.py check | apply | revert
# Root: R112Q_ROOT, else <tree>. Line ends kept (the new files take the tree's: CRLF). apply backs the originals up in r112q_backup next to
# this script; revert takes out exactly what apply put in and removes the new files. Needs r112p (and everything before it) applied.
import os, re, sys

ROOT = os.environ.get("R112Q_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112q_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RH = RV + "vk_rasterizer.h"
RC = RV + "vk_rasterizer.cpp"
EF = RV + "vk_rasterizer_effects.cpp"
PC = RV + "vk_pipeline_cache.cpp"
PS = RV + "vk_pipeline_serialization.cpp"
SH = "engine/gpu/shim/"
HH = SH + "bbport_wind_hang.h"
HG = SH + "bbport_wind_hang_gpu.h"
HS = SH + "bbport_wind_hang_still.h"
HR = SH + "bbport_wind_hang_route.h"
TR = "engine/tests/test_wind_hang_route.cpp"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
RM = "README.md"

# ---- the new files -----------------------------------------------------------------------------------
NEW_FILES = {
    HR: r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r112q_hang-bracket-route): what becomes of every draw of a hanging thing's pipeline, by stream group (the vertex
// shader : pixel shader pair), and why the lantern in the graveyard trees does not lean. FEATURE part (BB_WIND_HANG=1 only):
// BB_WIND_HANG_BOX_RETRY (BoxRetry in bbport_wind_hang_gpu.h). TOOL parts: the route lines (BB_WIND_HANG_FIND=1) and
// BB_WIND_HANG_FORCE. Pure: no Vulkan; tested by tests/test_wind_hang_route.cpp.
//
// THE ROUTE LINES (b64: no line named the vertex shader of the lantern, e859b6d9 was only in the startup line)
//   The rasterizer notes every draw of the Motion block with its pair of shaders (vs hash : ps hash), its kind (S skinned,
//   P GPU palette, O static), whether its pipeline has the Sway bit and discards, the stream it draws (the position attribute's
//   address), the sway word WindSwayWord gave it and whether the word reached the draw's motion parameter. What happened
//   inside WindSwayWord is read from the counters it moves (Mark before and after the call), so that none of its return
//   paths needs a hook: Exit says where the draw left the chain. Every 600 frames, with r112's lines, one line a group:
//   the draws, kinds, how they left, the words (pushed = a hang word with a ramp above 0, keys only = ramp 0), whether
//   they were delivered, which emitter made the vertex shader (the pipeline cache notes it: lifted / recompiled / cache),
//   up to StreamsMost streams of the group with their scene box height, GPU judge state and r112's reason, and FIRST BREAK:
//   the first link of the chain that most draws of the group fail. The vertex shader e859b6d9 (BracketVs) always has a line:
//   with its groups, or with the words 'no draw reached the Motion block'.
//
// BB_WIND_HANG_FORCE (TOOL, needs BB_WIND_HANG=1): 'all' or up to four vertex shader hashes in hex, ':' between them. A skinned
//   draw of a sway pipeline of such a shader gets a hang word at once, with no judge and no rule (the hunter and the trees too,
//   when 'all'): its ramp is the live BB_WIND_HANG_STATIC_GAIN (BB_WIND_HANG_PUSH=0 live gives no motion), so a lantern that
//   leans with it and not without it proves the shader chain, and then only the judges stand between the word and the picture.

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <string>
#include <unordered_map>
#include <vector>

#include "bbport_wind_hang.h"
#include "bbport_wind_hang_actors.h"
#include "bbport_wind_hang_find.h"
#include "bbport_wind_sway.h"

namespace BbWindHangRoute {

namespace H = BbWindHang;
namespace F = BbWindHangFind;
namespace A = BbWindHangActors;

inline constexpr std::uint32_t BracketVs = 0xe859b6d9u; ///< the vertex shader the b50 to b63 surveys named for the bracket lanterns
inline constexpr std::size_t GroupsMost = 192;          ///< groups kept a window
inline constexpr std::size_t StreamsMost = 4;           ///< streams of a group told apart
inline constexpr std::size_t LinesMost = 14;            ///< group lines of one report (the focus and bracket groups come first)
inline constexpr std::size_t LineChars = 760;
inline constexpr std::size_t ForceMost = 4;

/// The route lines are on: BB_WIND_HANG on and BB_WIND_HANG_FIND=1 (the survey's knob).
[[nodiscard]] inline bool On() {
    return F::FindOn();
}

// ---- BB_WIND_HANG_FORCE ------------------------------------------------------------------------------------------------

struct Force {
    bool all = false;
    std::array<std::uint32_t, ForceMost> vs{};
    std::size_t n = 0;
};

[[nodiscard]] inline Force ParseForce(const char* text) {
    Force f;
    if (text == nullptr || text[0] == 0) {
        return f;
    }
    if (std::string(text) == "all") {
        f.all = true;
        return f;
    }
    const char* p = text;
    while (*p != 0 && f.n < ForceMost) {
        char* end = nullptr;
        const unsigned long v = std::strtoul(p, &end, 16);
        if (end == p) {
            break;
        }
        f.vs[f.n++] = static_cast<std::uint32_t>(v & 0xffffffffu);
        p = end;
        if (*p == ':') {
            ++p;
        } else {
            break;
        }
    }
    return f;
}

/// BB_WIND_HANG_FORCE, read once; nothing without BB_WIND_HANG=1.
[[nodiscard]] inline const Force& ForceOnce() {
    static const Force force = H::KnobOnce().on ? ParseForce(std::getenv("BB_WIND_HANG_FORCE")) : Force{};
    return force;
}

[[nodiscard]] inline bool ForceMatchesWith(const Force& f, std::uint32_t vs) {
    if (f.all) {
        return true;
    }
    for (std::size_t i = 0; i < f.n; ++i) {
        if (f.vs[i] == vs) {
            return true;
        }
    }
    return false;
}

/// Is a skinned draw of the vertex shader `vs` (low 32 bits of its hash) forced? One test of two fields while the knob is off.
[[nodiscard]] inline bool ForceMatches(std::uint32_t vs) {
    const Force& f = ForceOnce();
    return (f.all || f.n != 0) && ForceMatchesWith(f, vs);
}

[[nodiscard]] inline bool ForceOn() {
    const Force& f = ForceOnce();
    return f.all || f.n != 0;
}

// ---- where a draw left the chain ----------------------------------------------------------------------------------------

/// The counters WindSwayWord and r112's verdict move, copied before and after a draw's word.
struct Mark {
    std::uint64_t called = 0;     ///< BbWindSway::Stats::draws: WindSwayWord was called
    std::uint64_t no_region = 0, no_rt = 0, no_camera = 0, no_slot = 0, plants = 0;
    std::uint64_t no_sun = 0, settled = 0, waiting = 0, moving = 0, unfit = 0; ///< BbWindHang::Stats
    std::uint64_t forced = 0;     ///< forced words so far (BB_WIND_HANG_FORCE)
    std::array<std::uint64_t, A::WhyCount> why{}; ///< r112h's tests so far, by Why
};

enum class Exit : std::uint8_t {
    NoWord,    ///< WindSwayWord was not called: the pipeline has no Sway bit or the kind is not asked
    NoRegion,  ///< no sway words (BB_WIND_SWAY 0, no region)
    NoRt,      ///< no ray traced scene wanted
    NoCamera,  ///< no 864-byte camera constants
    NoSlot,    ///< the views are full or no base slot
    Plant,     ///< taken as a plant
    NoSun,     ///< no sun shadow pass draws the stream (RtShadow::SunSkinned)
    Settled,   ///< a standing verdict: moving, out of height, a character
    Waiting,   ///< the palette book waits for StillFrames frames
    Moving,    ///< found moving now (the palette's content or the GPU box)
    Unfit,     ///< measured out of height
    Refused,   ///< r112h: the hunter's, a figure, indoors, unplaced
    Other,     ///< called, no word, no counter moved
    OtherWord, ///< a word with no hang bit (a plant's or a tree's)
    Keys,      ///< a hang word with ramp 0: the keys fill (judging, measuring)
    Pushed,    ///< a hang word with a ramp above 0
    Forced,    ///< BB_WIND_HANG_FORCE's word
};
inline constexpr std::size_t ExitCount = 17;

[[nodiscard]] inline const char* ExitName(Exit e) {
    switch (e) {
    case Exit::NoWord:
        return "no word asked";
    case Exit::NoRegion:
        return "no sway words";
    case Exit::NoRt:
        return "no ray tracing";
    case Exit::NoCamera:
        return "no camera";
    case Exit::NoSlot:
        return "no slot or views full";
    case Exit::Plant:
        return "plant";
    case Exit::NoSun:
        return "no sun pass";
    case Exit::Settled:
        return "settled";
    case Exit::Waiting:
        return "waiting";
    case Exit::Moving:
        return "moving";
    case Exit::Unfit:
        return "unfit";
    case Exit::Refused:
        return "refused by r112h";
    case Exit::Other:
        return "other";
    case Exit::OtherWord:
        return "plant or tree word";
    case Exit::Keys:
        return "keys only";
    case Exit::Pushed:
        return "pushed";
    case Exit::Forced:
        return "forced";
    }
    return "?";
}

[[nodiscard]] inline bool Rose(std::uint64_t after, std::uint64_t before) {
    return after > before;
}

/// Where a draw left the chain. `word` the sway word WindSwayWord returned; `why` set to r112h's test (A::Why) for Refused.
[[nodiscard]] inline Exit Classify(const Mark& before, const Mark& after, std::uint32_t word, std::uint8_t& why) {
    why = 0;
    if (word != 0) {
        if (Rose(after.forced, before.forced)) {
            return Exit::Forced;
        }
        if ((word & H::HangBit) == 0) {
            return Exit::OtherWord;
        }
        return BbWindSway::Unpack(word).ramp > 0 ? Exit::Pushed : Exit::Keys;
    }
    if (!Rose(after.called, before.called)) {
        return Exit::NoWord;
    }
    if (Rose(after.no_region, before.no_region)) {
        return Exit::NoRegion;
    }
    if (Rose(after.no_rt, before.no_rt)) {
        return Exit::NoRt;
    }
    if (Rose(after.no_camera, before.no_camera)) {
        return Exit::NoCamera;
    }
    if (Rose(after.no_slot, before.no_slot)) {
        return Exit::NoSlot;
    }
    if (Rose(after.plants, before.plants)) {
        return Exit::Plant;
    }
    if (Rose(after.no_sun, before.no_sun)) {
        return Exit::NoSun;
    }
    if (Rose(after.settled, before.settled)) {
        return Exit::Settled;
    }
    if (Rose(after.moving, before.moving)) {
        return Exit::Moving;
    }
    if (Rose(after.unfit, before.unfit)) {
        return Exit::Unfit;
    }
    if (Rose(after.waiting, before.waiting)) {
        return Exit::Waiting;
    }
    for (std::size_t k = 1; k < A::WhyCount; ++k) { // 0 is Why::Ok: kept, which gets a word
        if (Rose(after.why[k], before.why[k])) {
            why = static_cast<std::uint8_t>(k);
            return Exit::Refused;
        }
    }
    return Exit::Other;
}

// ---- the groups ----------------------------------------------------------------------------------------------------------

struct Group {
    std::uint64_t vs = 0, ps = 0;                 ///< the full hashes
    std::uint64_t draws = 0, bit = 0, discards = 0, delivered = 0, lost = 0;
    std::array<std::uint64_t, 3> kinds{};         ///< skinned, GPU palette, static
    std::array<std::uint64_t, ExitCount> exits{};
    std::array<std::uint64_t, A::WhyCount> refused{};
    std::array<std::uint64_t, StreamsMost> streams{};
    std::size_t stream_n = 0;
    std::uint64_t more_streams = 0;               ///< draws of a stream past the first StreamsMost
};

/// What the report knows of one stream (the rasterizer fills it from its books).
struct StreamInfo {
    bool scene = false;                    ///< the ray traced scene has a box of it
    float height = 0.0f, width = 0.0f;     ///< m
    std::uint32_t verts = 0;
    bool box = false;                      ///< the GPU judge has an entry
    std::uint8_t box_state = 0;            ///< 0 judging, 1 still, 2 moved (BbWindHangStill::BoxState)
    float dev = 0.0f;                      ///< the judge's greatest change (m); -1 no key; -2 refused by r112h
    bool book = false;                     ///< r112's book has an entry
    bool moving = false, judged = false, fits = false;
    std::uint8_t why_moving = 0, box_only = 0;
};

using Lookup = std::function<StreamInfo(std::uint64_t)>;
using PathOf = std::function<const char*(std::uint64_t)>;

class Book {
public:
    std::uint64_t forced_total = 0;  ///< forced words so far (never reset: Mark compares it)
    std::uint64_t dropped = 0;       ///< groups not kept for want of room

    /// A Motion block draw of the pipeline (vs, ps), of `kind` ('S', 'P' or 'O'), that drew `stream`.
    void Note(std::uint64_t vs, std::uint64_t ps, char kind, bool sway_bit, bool discards, std::uint64_t stream,
              std::uint32_t word, bool delivered, const Mark& before, const Mark& after) {
        const std::uint64_t key = ((vs & 0xffffffffu) << 32) | (ps & 0xffffffffu);
        auto found = groups.find(key);
        if (found == groups.end()) {
            if (groups.size() >= GroupsMost) {
                ++dropped;
                return;
            }
            found = groups.emplace(key, Group{}).first;
            found->second.vs = vs;
            found->second.ps = ps;
        }
        Group& g = found->second;
        ++g.draws;
        g.bit += sway_bit ? 1u : 0u;
        g.discards += discards ? 1u : 0u;
        g.kinds[kind == 'S' ? 0u : (kind == 'P' ? 1u : 2u)] += 1u;
        std::uint8_t why = 0;
        const Exit exit = Classify(before, after, word, why);
        ++g.exits[static_cast<std::size_t>(exit)];
        if (exit == Exit::Refused) {
            ++g.refused[why];
        }
        if (delivered) {
            ++g.delivered;
        } else if (word != 0) {
            ++g.lost;
        }
        if (stream != 0) {
            bool known = false;
            for (std::size_t i = 0; i < g.stream_n; ++i) {
                known = known || g.streams[i] == stream;
            }
            if (!known) {
                if (g.stream_n < StreamsMost) {
                    g.streams[g.stream_n++] = stream;
                } else {
                    ++g.more_streams;
                }
            }
        }
    }

    [[nodiscard]] std::size_t Size() const {
        return groups.size();
    }

    [[nodiscard]] const Group* Find(std::uint64_t vs, std::uint64_t ps) const {
        const auto found = groups.find(((vs & 0xffffffffu) << 32) | (ps & 0xffffffffu));
        return found == groups.end() ? nullptr : &found->second;
    }

    /// The window's groups, most words first (pushed, forced, keys), then most draws; a group of `focus` or BracketVs first.
    [[nodiscard]] std::vector<const Group*> Sorted(std::uint32_t focus) const {
        std::vector<const Group*> out;
        out.reserve(groups.size());
        for (const auto& item : groups) {
            out.push_back(&item.second);
        }
        const auto special = [&](const Group* g) {
            const auto vs = static_cast<std::uint32_t>(g->vs & 0xffffffffu);
            return vs == BracketVs || (focus != 0 && vs == focus);
        };
        const auto words = [](const Group* g) {
            return g->exits[static_cast<std::size_t>(Exit::Pushed)] + g->exits[static_cast<std::size_t>(Exit::Forced)] +
                   g->exits[static_cast<std::size_t>(Exit::Keys)];
        };
        std::sort(out.begin(), out.end(), [&](const Group* a, const Group* b) {
            if (special(a) != special(b)) {
                return special(a);
            }
            if (words(a) != words(b)) {
                return words(a) > words(b);
            }
            if (a->draws != b->draws) {
                return a->draws > b->draws;
            }
            return a->vs < b->vs || (a->vs == b->vs && a->ps < b->ps);
        });
        return out;
    }

    void Clear() {
        groups.clear();
    }

private:
    std::unordered_map<std::uint64_t, Group> groups;
};

// ---- the text ------------------------------------------------------------------------------------------------------------

[[nodiscard]] inline std::string Cap(std::string text) {
    if (text.size() > LineChars) {
        text.resize(LineChars - 3);
        text += "...";
    }
    return text;
}

[[nodiscard]] inline std::uint64_t Count(const Group& g, Exit e) {
    return g.exits[static_cast<std::size_t>(e)];
}

/// The first link of the chain most of the group's draws fail (one sentence).
[[nodiscard]] inline std::string FirstBreak(const Group& g, const char* path) {
    if (g.draws == 0) {
        return "none: no draw";
    }
    const std::uint64_t pushed = Count(g, Exit::Pushed) + Count(g, Exit::Forced);
    if (pushed > 0) {
        if (g.lost > 0 || g.delivered < pushed) {
            return "the word is lost: a pushed word got no motion parameter, the shader never sees it";
        }
        char buf[220];
        std::snprintf(buf, sizeof(buf),
                      "none up to the shader: %llu pushed words were delivered; look at the shader (%s) and the picture",
                      static_cast<unsigned long long>(pushed), path != nullptr ? path : "?");
        return std::string(buf);
    }
    // the exit most draws took (the word-less ones first), by the chain's order on a tie
    Exit best = Exit::NoWord;
    std::uint64_t most = 0;
    for (std::size_t i = 0; i < ExitCount; ++i) {
        if (static_cast<Exit>(i) == Exit::Pushed || static_cast<Exit>(i) == Exit::Forced) {
            continue;
        }
        if (g.exits[i] > most) {
            most = g.exits[i];
            best = static_cast<Exit>(i);
        }
    }
    switch (best) {
    case Exit::NoWord:
        if (g.bit == 0) {
            return "the pipeline has no Sway bit (SwayWanted: its vertex shader reads no stride-16 skeleton palette, or it is no motion pipeline): no word can exist";
        }
        if (g.kinds[0] == 0) {
            return "no skinned draw: static and GPU-palette draws ask for a word only through WantedCut and WindHangGpuStatic (BB_WIND_HANG_STATIC, _STATIC_GPU, _STATIC_CUT)";
        }
        return "WindSwayWord was not called for a skinned draw of a pipeline with the Sway bit";
    case Exit::NoRegion:
        return "no sway words region (BB_WIND_SWAY is 0, or ObjectMotion has none)";
    case Exit::NoRt:
        return "the ray traced scene is not wanted (RtShadow::Wanted): no sun shadow scene, no hang";
    case Exit::NoCamera:
        return "no draw constants of 864 bytes were found: no camera for the word";
    case Exit::NoSlot:
        return "no base slot or the views are full";
    case Exit::Plant:
        return "taken as a plant (a cut-out plant sway), not as a hanging thing";
    case Exit::NoSun:
        return "no sun shadow pass draws this stream (RtShadow::SunSkinned is false): r112 takes only streams the sun draws";
    case Exit::Settled:
        return "a standing verdict holds the stream as moving or out of height (r112/r112e/r112g books): see the judge state of its streams";
    case Exit::Waiting:
        return "the palette book is still waiting (StillFrames frames of the same palette)";
    case Exit::Moving:
        return "judged moving (the palette's content or the GPU box): see the streams' judge state and deviation";
    case Exit::Unfit:
        return "measured outside the hanging heights (0.15 to 4 m) by its keys";
    case Exit::Refused: {
        std::size_t top = 1;
        for (std::size_t k = 1; k < A::WhyCount; ++k) {
            top = g.refused[k] > g.refused[top] ? k : top;
        }
        return std::string("refused by r112h: ") + A::WhyName(static_cast<A::Why>(top));
    }
    case Exit::Other:
        return "WindSwayWord gave no word and moved no counter: a tree or limb word is not asked here, so the judge's window or a held stream";
    case Exit::OtherWord:
        return "the word is a plant's or a tree's, not a hanging thing's";
    case Exit::Keys:
        return "keys-only words (the ramp stays 0): the GPU judge's window is open (about 70 frames) or Measure refuses the height; see the streams' judge state and book";
    case Exit::Pushed:
    case Exit::Forced:
        break;
    }
    return "unknown";
}

[[nodiscard]] inline const char* StateName(const StreamInfo& s) {
    if (!s.box) {
        return "none";
    }
    return s.box_state == 0 ? "judging" : (s.box_state == 1 ? "still" : "moved");
}

[[nodiscard]] inline const char* BookName(const StreamInfo& s) {
    if (!s.book) {
        return "none";
    }
    if (s.moving) {
        return "moving";
    }
    return s.judged ? (s.fits ? "hang" : "out of height") : "waiting";
}

/// One group's line (under LineChars characters).
[[nodiscard]] inline std::string GroupLine(const Group& g, std::uint32_t focus, const Lookup& look, const char* path,
                                           unsigned frames) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    const auto vs32 = static_cast<std::uint32_t>(g.vs & 0xffffffffu);
    char head[560];
    std::snprintf(head, sizeof(head),
                  "Wind sway hang route (r112q): vs:ps %08x:%08x%s, shader %s: %llu draws in %u frames (skinned %llu, GPU palette %llu, "
                  "static %llu), Sway bit on %llu, discard %llu; words: pushed %llu, forced %llu, keys only %llu, plant or tree %llu, "
                  "delivered to the motion parameter %llu, lost %llu; left the chain:",
                  vs32, static_cast<std::uint32_t>(g.ps & 0xffffffffu),
                  vs32 == BracketVs ? " [bracket]" : (focus != 0 && vs32 == focus ? " [focus]" : ""), path != nullptr ? path : "?",
                  n(g.draws), frames, n(g.kinds[0]), n(g.kinds[1]), n(g.kinds[2]), n(g.bit), n(g.discards), n(Count(g, Exit::Pushed)),
                  n(Count(g, Exit::Forced)), n(Count(g, Exit::Keys)), n(Count(g, Exit::OtherWord)), n(g.delivered), n(g.lost));
    std::string out = head;
    bool any = false;
    for (std::size_t i = 0; i < ExitCount; ++i) {
        const Exit e = static_cast<Exit>(i);
        if (e == Exit::Pushed || e == Exit::Forced || e == Exit::Keys || e == Exit::OtherWord || g.exits[i] == 0) {
            continue;
        }
        char one[96];
        std::snprintf(one, sizeof(one), "%s %s %llu", any ? "," : "", ExitName(e), n(g.exits[i]));
        out += one;
        any = true;
    }
    if (!any) {
        out += " none";
    }
    if (Count(g, Exit::Refused) > 0) {
        out += " (r112h:";
        for (std::size_t k = 1; k < A::WhyCount; ++k) {
            if (g.refused[k] > 0) {
                char one[64];
                std::snprintf(one, sizeof(one), " %s %llu", A::WhyName(static_cast<A::Why>(k)), n(g.refused[k]));
                out += one;
            }
        }
        out += ")";
    }
    out += "; streams:";
    if (g.stream_n == 0) {
        out += " none noted";
    }
    for (std::size_t i = 0; i < g.stream_n; ++i) {
        const StreamInfo s = look ? look(g.streams[i]) : StreamInfo{};
        char one[240];
        if (s.scene) {
            std::snprintf(one, sizeof(one),
                          " %#llx scene %.2f m tall %.2f m wide %u verts, judge %s dev %.0f mm, book %s (why %u, box %u);",
                          n(g.streams[i]), static_cast<double>(s.height), static_cast<double>(s.width), static_cast<unsigned>(s.verts),
                          StateName(s), static_cast<double>(s.dev) * 1000.0, BookName(s), static_cast<unsigned>(s.why_moving),
                          static_cast<unsigned>(s.box_only));
        } else {
            std::snprintf(one, sizeof(one), " %#llx no scene box, judge %s dev %.0f mm, book %s (why %u, box %u);", n(g.streams[i]),
                          StateName(s), static_cast<double>(s.dev) * 1000.0, BookName(s), static_cast<unsigned>(s.why_moving),
                          static_cast<unsigned>(s.box_only));
        }
        out += one;
    }
    if (g.more_streams > 0) {
        char one[64];
        std::snprintf(one, sizeof(one), " +%llu draws of other streams;", n(g.more_streams));
        out += one;
    }
    out += " FIRST BREAK: " + FirstBreak(g, path);
    return Cap(out);
}

/// The report: the header line, then the groups' lines (LinesMost at most; the bracket vertex shader's and the focus' always).
/// `focus` BB_WIND_HANG_FOCUS' hash (0: none). Empty when the window held no draw.
[[nodiscard]] inline std::vector<std::string> Lines(const Book& book, std::uint32_t focus, const Lookup& look, const PathOf& path_of,
                                                    unsigned frames) {
    std::vector<std::string> out;
    const std::vector<const Group*> groups = book.Sorted(focus);
    std::uint64_t draws = 0, words = 0;
    bool bracket = false;
    for (const Group* g : groups) {
        draws += g->draws;
        words += Count(*g, Exit::Pushed) + Count(*g, Exit::Forced);
        bracket = bracket || static_cast<std::uint32_t>(g->vs & 0xffffffffu) == BracketVs;
    }
    char head[480];
    std::snprintf(head, sizeof(head),
                  "Wind sway hang route (r112q): %zu stream groups (vs:ps), %llu Motion block draws in %u frames, %llu with a pushed or "
                  "forced hang word; the first %zu groups follow (the bracket lanterns' vs %08x and the focus %08x first, then by words)%s",
                  groups.size(), static_cast<unsigned long long>(draws), frames, static_cast<unsigned long long>(words), LinesMost,
                  BracketVs, focus, book.dropped > 0 ? " (groups dropped: the table was full)" : "");
    out.emplace_back(head);
    if (!bracket) {
        char none[420];
        std::snprintf(none, sizeof(none),
                      "Wind sway hang route (r112q): vs %08x (the bracket lanterns of the b50 to b63 surveys): NO draw of it reached the "
                      "Motion block in this window: it is not drawn here, or the lantern in view has another vertex shader (name it with "
                      "BB_WIND_TWIGS_PICK on its pixels)",
                      BracketVs);
        out.emplace_back(none);
    }
    std::size_t listed = 0;
    for (const Group* g : groups) {
        if (listed >= LinesMost) {
            break;
        }
        const auto vs32 = static_cast<std::uint32_t>(g->vs & 0xffffffffu);
        const bool special = vs32 == BracketVs || (focus != 0 && vs32 == focus);
        // a group no hang code can touch is told only when it is special: skinned draws with the bit, or any word
        const bool interesting = special || (g->kinds[0] > 0 && g->bit > 0) || Count(*g, Exit::Pushed) + Count(*g, Exit::Forced) +
                                                                                 Count(*g, Exit::Keys) > 0;
        if (!interesting) {
            continue;
        }
        out.push_back(GroupLine(*g, focus, look, path_of ? path_of(g->vs) : nullptr, frames));
        ++listed;
    }
    return out;
}

/// The once line.
[[nodiscard]] inline std::string OnceText(unsigned retry, bool force_on, bool force_all) {
    char buf[900];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112q): route lines every %u frames (BB_WIND_HANG_FIND=1): one a stream group (vs:ps) with the draws, "
                  "how they left the chain, the pushed words, whether they were delivered, the vertex shader's emitter, its streams' "
                  "scene height and GPU judge state, and FIRST BREAK; a box-judged stream the box found moving is judged again %u frames "
                  "after (BB_WIND_HANG_BOX_RETRY, 0 = as r112p: a box that grew 0.25 m was final); BB_WIND_HANG_FORCE (TOOL): %s",
                  BbWindSway::ReportFrames, retry,
                  force_on ? (force_all ? "ON for every skinned draw of a sway pipeline (no judge, no rule)"
                                        : "ON for the named vertex shaders (no judge, no rule)")
                           : "off");
    return std::string(buf);
}

} // namespace BbWindHangRoute
''',
    TR: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112q_hang-bracket-route): the route lines, BB_WIND_HANG_FORCE, BB_WIND_HANG_BOX_RETRY, the proof's binary version add and
// the GPU judge's DueSoft (gpu/shim/bbport_wind_hang_route.h, _gpu.h, _still.h, bbport_wind_hang.h). The twin in Python
// (r112q_twin.py) holds the same cases.
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "gpu/shim/bbport_wind_hang_gpu.h"
#include "gpu/shim/bbport_wind_hang_route.h"
#include "gpu/shim/bbport_wind_hang_still.h"

namespace R = BbWindHangRoute;
namespace G = BbWindHangGpu;
namespace S = BbWindHangStill;
namespace H = BbWindHang;
namespace A = BbWindHangActors;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

bool Has(const std::string& text, const char* needle) {
    return text.find(needle) != std::string::npos;
}

bool AnyHas(const std::vector<std::string>& lines, const char* needle) {
    for (const std::string& line : lines) {
        if (Has(line, needle)) {
            return true;
        }
    }
    return false;
}
} // namespace

int main() {
    // BB_WIND_HANG_FORCE
    {
        const R::Force none = R::ParseForce(nullptr);
        Expect(!none.all && none.n == 0 && !R::ForceMatchesWith(none, 0xe859b6d9u), "force: unset forces nothing");
        Expect(R::ParseForce("").n == 0 && !R::ParseForce("").all, "force: empty forces nothing");
        Expect(R::ParseForce("all").all && R::ForceMatchesWith(R::ParseForce("all"), 0x12345678u), "force: all");
        Expect(!R::ParseForce("ALL").all, "force: only the exact word all");
        const R::Force one = R::ParseForce("e859b6d9");
        Expect(!one.all && one.n == 1 && one.vs[0] == 0xe859b6d9u && R::ForceMatchesWith(one, 0xe859b6d9u) &&
                   !R::ForceMatchesWith(one, 0x97f2d384u),
               "force: one hash");
        const R::Force many = R::ParseForce("e859b6d9:97f2d384:6a833138:9da6aacb:c829ee58");
        Expect(many.n == R::ForceMost && many.vs[3] == 0x9da6aacbu && !R::ForceMatchesWith(many, 0xc829ee58u),
               "force: at most four hashes");
        Expect(R::ParseForce("zz").n == 0, "force: text that is no hex forces nothing");
        Expect(R::ParseForce("e859b6d9:zz").n == 1, "force: a bad second hash is left out");
    }
    // BB_WIND_HANG_BOX_RETRY
    {
        Expect(G::ParseRetry(nullptr) == 120 && G::ParseRetry("") == 120 && G::ParseRetry("abc") == 120, "retry: default 120");
        Expect(G::ParseRetry("0") == 0, "retry: 0 gives r112p's rule");
        Expect(G::ParseRetry("5") == 30 && G::ParseRetry("99999") == 3600 && G::ParseRetry("200") == 200, "retry: 30 to 3600");
    }
    // the proof's binary version add
    {
        static_assert(H::ProofBinaryAdd == 100000u, "the add is a number no sway version reaches");
        static_assert(H::ProofBinaryAdd > 22u + 1000u + 2000u + 100u + 10u + 20u + 400u + 40u + 4000u + 8000u + 400u, "no clash");
    }
    // where a draw leaves the chain
    {
        const std::uint32_t keys_word = H::HangWord(0, 0, 5, 0);
        const std::uint32_t push_word = H::HangWord(0, 0, 5, 200);
        const std::uint32_t plant_word = BbWindSway::PackWord(0, 0, 5, 100);
        R::Mark before;
        std::uint8_t why = 9;
        Expect(R::Classify(before, before, 0, why) == R::Exit::NoWord, "exit: WindSwayWord not called");
        R::Mark after = before;
        after.called = 1;
        Expect(R::Classify(before, after, 0, why) == R::Exit::Other && why == 0, "exit: called, nothing moved");
        R::Mark m = after;
        m.no_sun = 1;
        Expect(R::Classify(before, m, 0, why) == R::Exit::NoSun, "exit: no sun pass");
        m = after;
        m.settled = 1;
        m.moving = 1;
        Expect(R::Classify(before, m, 0, why) == R::Exit::Settled, "exit: settled comes before moving in the chain");
        m = after;
        m.moving = 1;
        Expect(R::Classify(before, m, 0, why) == R::Exit::Moving, "exit: moving");
        m = after;
        m.why[static_cast<std::size_t>(A::Why::Near)] = 1;
        Expect(R::Classify(before, m, 0, why) == R::Exit::Refused && why == static_cast<std::uint8_t>(A::Why::Near),
               "exit: refused by r112h's near rule");
        m = after;
        m.why[0] = 1;
        Expect(R::Classify(before, m, 0, why) == R::Exit::Other, "exit: a kept stream (Why::Ok) is no refusal");
        Expect(R::Classify(before, after, keys_word, why) == R::Exit::Keys, "exit: a hang word with ramp 0 is keys only");
        Expect(R::Classify(before, after, push_word, why) == R::Exit::Pushed, "exit: a hang word with a ramp is pushed");
        Expect(R::Classify(before, after, plant_word, why) == R::Exit::OtherWord, "exit: a plant word has no hang bit");
        m = after;
        m.forced = 1;
        Expect(R::Classify(before, m, push_word, why) == R::Exit::Forced, "exit: a forced word");
    }
    // the groups and their lines
    {
        const std::uint32_t push_word = H::HangWord(0, 0, 5, 200);
        R::Book book;
        R::Mark before;
        R::Mark after = before;
        after.called = 1;
        for (int i = 0; i < 6; ++i) { // 6 pushed, delivered draws of the bracket shader
            book.Note(0xe859b6d9u, 0xe21e283au, 'S', true, false, 0x1000, push_word, true, before, after);
        }
        R::Mark sun = after;
        sun.no_sun = 1;
        for (int i = 0; i < 4; ++i) { // 4 draws of another shader that no sun pass draws
            book.Note(0x63220f67u, 0xdbb222ebu, 'S', true, false, 0x2000 + i, 0, true, before, sun);
        }
        for (int i = 0; i < 3; ++i) { // a pipeline with no bit
            book.Note(0x11111111u, 0x22222222u, 'O', false, false, 0x3000, 0, true, before, before);
        }
        Expect(book.Size() == 3 && book.Find(0xe859b6d9u, 0xe21e283au)->draws == 6, "book: one group a pair of shaders");
        const R::Lookup look = [](std::uint64_t) {
            R::StreamInfo s;
            s.scene = true;
            s.height = 1.32f;
            s.width = 0.88f;
            s.verts = 1907;
            s.box = true;
            s.box_state = 2;
            s.dev = 0.31f;
            s.book = true;
            s.moving = true;
            s.why_moving = 3;
            s.box_only = 1;
            return s;
        };
        const R::PathOf path = [](std::uint64_t) { return "lifted"; };
        const std::vector<std::string> lines = R::Lines(book, 0, look, path, 600);
        Expect(AnyHas(lines, "3 stream groups") && AnyHas(lines, "vs:ps e859b6d9:e21e283a [bracket]"), "lines: the header and the bracket group");
        Expect(!AnyHas(lines, "NO draw of it reached"), "lines: no 'no draw' line while the bracket shader was drawn");
        Expect(AnyHas(lines, "none up to the shader: 6 pushed words were delivered"), "lines: FIRST BREAK of a pushed, delivered group");
        Expect(AnyHas(lines, "vs:ps 63220f67:dbb222eb") && AnyHas(lines, "no sun shadow pass draws this stream"),
               "lines: a skinned group with the bit and no sun pass");
        Expect(!AnyHas(lines, "vs:ps 11111111:22222222"), "lines: a group no hang code can touch is not told");
        Expect(AnyHas(lines, "scene 1.32 m tall 0.88 m wide 1907 verts, judge moved dev 310 mm, book moving (why 3, box 1)"),
               "lines: a stream's scene box, judge state and book");
        R::Book other;
        other.Note(0x63220f67u, 0xdbb222ebu, 'S', true, false, 0x2000, 0, true, before, sun);
        const std::vector<std::string> none = R::Lines(other, 0, look, path, 600);
        Expect(AnyHas(none, "vs e859b6d9") && AnyHas(none, "NO draw of it reached the Motion block"),
               "lines: the bracket shader always has a line");
        // FIRST BREAK of a pipeline with no bit, of lost words
        R::Group g;
        g.draws = 5;
        g.exits[static_cast<std::size_t>(R::Exit::NoWord)] = 5;
        Expect(Has(R::FirstBreak(g, "lifted"), "no Sway bit"), "break: no bit");
        g.bit = 5;
        g.kinds[2] = 5;
        Expect(Has(R::FirstBreak(g, "lifted"), "no skinned draw"), "break: a static group");
        R::Group lost;
        lost.draws = 3;
        lost.exits[static_cast<std::size_t>(R::Exit::Pushed)] = 3;
        lost.lost = 3;
        Expect(Has(R::FirstBreak(lost, "lifted"), "the word is lost"), "break: pushed words with no motion parameter");
        R::Group keys;
        keys.draws = 3;
        keys.bit = 3;
        keys.kinds[0] = 3;
        keys.exits[static_cast<std::size_t>(R::Exit::Keys)] = 3;
        Expect(Has(R::FirstBreak(keys, "lifted"), "ramp stays 0"), "break: keys only");
        Expect(Has(R::OnceText(120, true, true), "BB_WIND_HANG_BOX_RETRY") && Has(R::OnceText(120, false, false), "FORCE (TOOL): off"),
               "once line");
        R::Book full;
        for (std::uint64_t i = 0; i < R::GroupsMost + 5; ++i) {
            full.Note(0x1000u + i, 0x2000u, 'S', true, false, 1, 0, true, before, after);
        }
        Expect(full.Size() == R::GroupsMost && full.dropped == 5, "book: at most GroupsMost groups");
        for (const std::string& line : lines) {
            Expect(line.size() <= R::LineChars + 4, "lines: under LineChars");
        }
    }
    // the judge's DueSoft: a box that grew 0.25 m is due again after `retry` frames, a small mover as Due says
    {
        std::vector<std::uint32_t> words(BbWindTwigs::TwigEnd, BbWindSway::ResetKey);
        namespace W = BbWindSway;
        const auto offer = [&](std::uint32_t slot, float y0, float y1, float x0, float x1, float z0, float z1) {
            const auto low = [&](std::uint32_t at, std::uint32_t key) { words[at] = std::min(words[at], key); };
            const std::uint32_t box = BbWindTwigs::TwigAt + slot * BbWindTwigs::TwigSlotWords;
            low(W::BaseAt + slot, W::HeightKey(y0));
            low(W::CrownAt + slot, W::CrownKey(y1));
            low(box + 0, W::HeightKey(x0));
            low(box + 1, W::CrownKey(x1));
            low(box + 2, W::HeightKey(z0));
            low(box + 3, W::CrownKey(z1));
        };
        S::BoxBook mover;
        for (std::uint64_t f = 100; f < 170; ++f) {
            if (f >= 101) {
                offer(9, 0.0f, f < 120 ? 2.0f : 2.5f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            mover.Step(12, 4096, 9, f == 100, f, words.data());
        }
        Expect(mover.Final(12) && !mover.Due(12, 100000), "soft: r112p's rule: final, never due");
        const std::uint64_t at = mover.Find(12)->settled;
        Expect(!mover.DueSoft(12, at + 119, 120), "soft: not due before retry frames");
        Expect(mover.DueSoft(12, at + 120, 120) && mover.Find(12) == nullptr, "soft: due after retry frames, forgotten");
        Expect(!mover.DueSoft(99, 1000000, 120), "soft: an unknown stream is not due (the caller asks only for held ones)");
        S::BoxBook small;
        for (std::uint64_t f = 100; f < 170; ++f) {
            if (f >= 101) {
                offer(10, 0.0f, f < 120 ? 2.0f : 2.05f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            small.Step(13, 4096, 10, f == 100, f, words.data());
        }
        const std::uint64_t small_at = small.Find(13)->settled;
        Expect(!small.Final(13) && !small.DueSoft(13, small_at + S::RejudgeFrames - 1, 30) && small.DueSoft(13, small_at + S::RejudgeFrames, 30),
               "soft: a small mover is due as Due says, not sooner");
        S::BoxBook rejected;
        rejected.Step(14, 4096, 11, true, 100, words.data());
        Expect(rejected.Reject(14, 100, 7200) && !rejected.DueSoft(14, 100 + 7199, 30) && rejected.DueSoft(14, 100 + 7200, 30),
               "soft: r112h's hold stands");
    }
    // the writer watch hears the other paths
    {
        G::Watch watch;
        Expect(watch.Add(0x7f0000001100ull, 4032, 84, 0x55), "writers: a palette is watched");
        watch.Written(0, G::WriterCopy, 0x7f0000001000ull, 0x4000);
        watch.Written(0, G::WriterFill, 0x7f0000009000ull, 0x1000); // elsewhere
        watch.Written(0, G::WriterGuest, 0x7f0000002000ull, 0x10);   // shares the page of the palette's end
        const std::vector<std::string> lines = watch.TakeLines();
        Expect(watch.Hits() == 2 && lines.size() == 2 && Has(lines[0], "a DMA copy destination (no shader) writes") &&
                   Has(lines[0], "lies INSIDE that range") && Has(lines[1], "a guest-memory write (no shader)") &&
                   Has(lines[1], "only SHARES a page"),
               "writers: a copy and a guest write are named, no shader hash");
        Expect(Has(G::NoWriterText(8), "8 watched palette pages") && Has(G::NoWriterText(8), "r112q"), "writers: the explanation line");
    }
    if (failures == 0) {
        std::printf("wind-hang-route-test: all passed\n");
    }
    return failures == 0 ? 0 : 1;
}
''',
}

# ---- the edits: ('ins', anchor, pre, post) puts pre before and post after the anchor; ('rep', old, '', new) replaces old ----
# bbport_wind_hang.h: the proof's binary version add
H1 = r'''/// Bytes of the sway words ObjectMotion makes when the plant sway is on: r89's region, and with'''
H1P = r'''// bbport (r112q_hang-bracket-route): the proof's tint is part of the lifter's SPIR-V and the serialized shader's binary version did not say so:
// a run with BB_WIND_HANG_PROOF=1 loaded the warm cache's sway shaders (made with no tint) and showed no cyan (b64). With the proof on, every
// sway vertex shader's binary version gets ProofBinaryAdd: a cached shader of a run without the proof is not loaded, and the proof run's own
// shaders are saved and loaded under their version. Off: 0, as before.
inline constexpr std::uint32_t ProofBinaryAdd = 100000;

[[nodiscard]] inline std::uint32_t ProofBinaryOffset() {
    return ProofOn() ? ProofBinaryAdd : 0u;
}

/// A saved version with the proof's add taken out (only while the proof is on and the version carries it).
[[nodiscard]] inline std::uint32_t StripProofVersion(std::uint32_t version) {
    return ProofOn() && version >= ProofBinaryAdd ? version - ProofBinaryAdd : version;
}

'''

# bbport_wind_hang_gpu.h: the retry knob, the writer codes, the no-writer text; StageName; the writers' lines
G1 = r'''/// What the CPU palette test said of one draw's palette.'''
G1P = r'''/// bbport (r112q_hang-bracket-route): BB_WIND_HANG_BOX_RETRY: the frames after which a box-judged stream (Entry::box_only) that the GPU box
/// found moving, even by 0.25 m or more (BoxFinal: 'a character for good'), is judged again with a new window (BoxBook::DueSoft). A camera turn
/// brings places of a mesh into view (or takes them out) and the union box its keys span grows with them; 0.25 m of that was final in r112p: a
/// lantern pushed while the camera stood still lost its push for good at the first turn (b64: pushes counted before the look-up, none after it,
/// 13 of 15 judged streams moved). 0: r112p's rule. 30 to 3600, default 120; text that is no number gives the default.
inline constexpr std::uint64_t BoxRetryDefault = 120, BoxRetryMin = 30, BoxRetryMax = 3600;

[[nodiscard]] inline std::uint64_t ParseRetry(const char* text) {
    const float v = BbWindSway::ParseNumber(text, static_cast<float>(BoxRetryDefault));
    if (v < 0.5f) {
        return 0;
    }
    return static_cast<std::uint64_t>(std::clamp(v, static_cast<float>(BoxRetryMin), static_cast<float>(BoxRetryMax)));
}

[[nodiscard]] inline std::uint64_t BoxRetry() {
    static const std::uint64_t frames = ParseRetry(std::getenv("BB_WIND_HANG_BOX_RETRY"));
    return frames;
}

/// bbport (r112q_hang-bracket-route): the writer watch hears more than the written storage bindings of BindBuffers: the other paths that mark
/// pages GPU-modified (ObtainBuffer with is_written: a DMA copy or fill destination, a guest-memory write, a command write) pass one of these
/// codes in place of a shader stage (a stage is 0 to 5).
inline constexpr std::uint32_t WriterCopy = 100, WriterFill = 101, WriterGuest = 102, WriterCommand = 103;

[[nodiscard]] inline const char* WriterName(std::uint32_t code) {
    switch (code) {
    case WriterCopy:
        return "DMA copy destination";
    case WriterFill:
        return "DMA fill destination";
    case WriterGuest:
        return "guest-memory write";
    case WriterCommand:
        return "command write";
    default:
        break;
    }
    return "writer ?";
}

/// The line that says what 'writers found 0' means (printed with the periodic line while pages are watched and no writer is found).
[[nodiscard]] inline std::string NoWriterText(std::size_t watched) {
    char buf[900];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112q): no writer found for %zu watched palette pages although the buffer cache calls them GPU-modified: its flag is "
                  "set by every ObtainBuffer(.., is_written): a shader's written storage binding (BindBuffers: the only path r112p watched, so 'writers "
                  "found 0' said that no such binding ever touched those pages) and, heard since r112q, a DMA copy or fill destination, a guest-memory "
                  "write and a command write; none of the four here either: the flag comes from a neighbour in the same page or from the in-place write "
                  "tick (a GPU write not yet finished counts as modified)",
                  watched);
    return std::string(buf);
}

'''
G2 = r'''[[nodiscard]] inline const char* StageName(std::uint32_t stage) {
    switch (stage) { // Shader::SwStage's order'''
G2N = r'''[[nodiscard]] inline const char* StageName(std::uint32_t stage) {
    if (stage >= WriterCopy) { // bbport (r112q_hang-bracket-route): not a shader stage: a copy, fill or write path
        return WriterName(stage);
    }
    switch (stage) { // Shader::SwStage's order'''
G3 = r'''            out.emplace_back(buf);'''
G3P = r'''            if (h.stage >= WriterCopy) { // bbport (r112q_hang-bracket-route): a copy, fill or write path, no shader
                std::snprintf(buf, sizeof(buf),
                              "GLINT-PROOF hang box (r112p): palette writer %zu: a %s (no shader) writes %#llx+%llu; the palette %#llx+%u (%u bones, "
                              "stream %#llx) %s that range (4 KiB pages assumed)",
                              printed + 1, StageName(h.stage), static_cast<unsigned long long>(h.at),
                              static_cast<unsigned long long>(h.size), static_cast<unsigned long long>(h.palette), h.bytes, h.bones,
                              static_cast<unsigned long long>(h.stream), h.inside ? "lies INSIDE" : "only SHARES a page with");
            }
'''

# bbport_wind_hang_still.h: DueSoft
S1 = r'''    /// bbport (r112g_hang-judge-settles): the judge holds `stream` as moving (a verdict, a
    /// give-up): then its own Due decides when it is judged again, not the palette book's.'''
S1P = r'''    /// bbport (r112q_hang-bracket-route): as Due, but a stream whose box grew BoxFinal or more (a character for good: Due never says yes)
    /// is due too, `retry` frames after it was found moving (BB_WIND_HANG_BOX_RETRY): the caller asks it of a box-judged stream only,
    /// whose union box a camera turn changes. A smaller mover and a stream r112h rejected follow Due's rules (RejudgeFrames, its hold).
    bool DueSoft(std::uint64_t stream, std::uint64_t frame, std::uint64_t retry) {
        const auto found = entries.find(stream);
        if (found == entries.end() || found->second.state != BoxState::Moved) {
            return false;
        }
        if (found->second.dev < BoxFinal) {
            return Due(stream, frame);
        }
        if (found->second.settled + retry > frame) {
            return false;
        }
        entries.erase(found);
        ++stats.again;
        return true;
    }

'''

# vk_rasterizer.h
V1 = r'''#include "bbport_wind_hang_probe.h" // bbport (r112b_hang-probe, TOOL)'''
V1P = r'''#include "bbport_wind_hang_route.h" // bbport (r112q_hang-bracket-route)
'''
V2 = r'''    /// bbport (r112b_hang-probe, TOOL; BB_WIND_HANG_PROBE=1): a skinned sway draw's first bone'''
V2P = r'''    /// bbport (r112q_hang-bracket-route, TOOL; BB_WIND_HANG_FIND=1): the counters a draw's sway word moves, the draw's note (its pair of
    /// shaders, kind, word and delivery), the report every 600 frames, and the word of BB_WIND_HANG_FORCE
    BbWindHangRoute::Mark WindHangRouteMark();
    void WindHangRouteNote(const GraphicsPipeline* pipeline, char kind, u32 word, bool delivered);
    void WindHangRouteReport();
    u32 WindHangForceWord(u32* words, u32 frame_slot, u32 view, u32 slot, const BbWind::Snapshot& now);
'''
V3 = r'''    std::array<bool, BbWindSway::Views> hang_filled{};'''
V3P = r'''
    BbWindHangRoute::Book hang_route; // bbport (r112q_hang-bracket-route, TOOL): the stream groups' routes
    BbWindHangRoute::Mark hang_route_before; // the counters before the draw's word'''

# vk_rasterizer.cpp
C1 = r'''        // bbport (r89_wind-foliage-sway): a plant's sway word (WindSwayWord); 0 for every other'''
C1P = r'''        if (BbWindHangRoute::On()) { // bbport (r112q_hang-bracket-route, TOOL): the counters the word below moves
            hang_route_before = WindHangRouteMark();
        }
'''
C2 = r'''        if (sway != 0 && dc.push_data.motion_param == 0) { // bbport (r112h_hang-not-the-hunter)'''
C2P = r'''        if (BbWindHangRoute::On()) { // bbport (r112q_hang-bracket-route, TOOL): this draw's pair of shaders, kind, word and delivery
            WindHangRouteNote(pipeline,
                              r34_kind == Motion::Kind::Skinned
                                  ? 'S'
                                  : (r34_kind == Motion::Kind::GpuPalette ? 'P' : 'O'),
                              sway, dc.push_data.motion_param != 0);
        }
'''
C3 = r'''    const auto [buffer, offset] = [&] -> std::pair<const VideoCore::Buffer*, u64> {
        if (is_gds) {
            return {buffer_cache.GetGdsBuffer(), address};'''
C3P = r'''    if (!is_gds) { // bbport (r112q_hang-bracket-route): the palette writer watch hears the fill
        hang_gpu_watch.Written(0, BbWindHangGpu::WriterFill, address, num_bytes);
    }
'''
C4 = r'''    const auto* gds_buffer = buffer_cache.GetGdsBuffer();
    const auto [src_buffer, src_offset] = [&] -> std::pair<const VideoCore::Buffer*, u64> {'''
C4P = r'''    if (!dst_gds) { // bbport (r112q_hang-bracket-route): the palette writer watch hears the copy
        hang_gpu_watch.Written(0, BbWindHangGpu::WriterCopy, dst, num_bytes);
    }
'''
C5 = r'''    const auto [buffer, offset] = buffer_cache.ObtainBuffer(address, size, true);
    if (!buffer_cache.IsInPlace(address, size)) {'''
C5P = r'''    hang_gpu_watch.Written(0, BbWindHangGpu::WriterGuest, address, size); // bbport (r112q_hang-bracket-route): the palette writer watch
'''
C6 = r'''    const auto target = buffer_cache.CommandWriteTarget(address, size);'''
C6P = r'''    hang_gpu_watch.Written(0, BbWindHangGpu::WriterCommand, address, size); // bbport (r112q_hang-bracket-route): the palette writer watch
'''

# vk_rasterizer_effects.cpp
E1 = r'''    const bool judge = hang_judge && !hang && !plant && !tree; // (r112f) its keys decide
    if (!plant && !hang && !tree && !judge) {
        return 0;
    }'''
E1N = r'''    const bool judge = hang_judge && !hang && !plant && !tree; // (r112f) its keys decide
    // bbport (r112q_hang-bracket-route, TOOL): BB_WIND_HANG_FORCE: a skinned draw of a named vertex shader (or all) that no rule took is given a
    // hang word all the same, with no judge (WindHangForceWord): the proof of the shader chain, whatever the judges say
    const bool force = !plant && !tree && !hang && !judge && small_palette < 0 &&
                       BbWindHangRoute::ForceMatches(static_cast<u32>(vs.pgm_hash & 0xffffffffu));
    if (!plant && !hang && !tree && !judge && !force) {
        return 0;
    }'''
E2 = r'''    if (judge) { // bbport (r112f_hang-gpu-judge): the GPU's keys say whether it stands still'''
E2P = r'''    if (force) { // bbport (r112q_hang-bracket-route, TOOL): the word of BB_WIND_HANG_FORCE
        return WindHangForceWord(words, frame_slot, view, taken.slot, snapshot);
    }
'''
E3 = r'''        if (by_height || hang_box.Final(positions) ||
            (hang_box.HoldsMoved(positions) ? !hang_box.Due(positions, frame)
                                            : !hang_still.Due(positions, frame))) {'''
E3N = r'''        // bbport (r112q_hang-bracket-route): a stream the GPU box judges in place of its palette (box_only) is no character for good when its box
        // grew 0.25 m: a camera turn brings places of the mesh into view and the union its keys span grows (b64: pushes before the look-up, none
        // after it). It is judged again BB_WIND_HANG_BOX_RETRY frames after it was found moving (0: r112p's rule)
        const std::uint64_t retry = BbWindHangGpu::BoxRetry();
        const bool soft = retry != 0 && known != nullptr && known->box_only != 0;
        if (by_height || (!soft && hang_box.Final(positions)) ||
            (hang_box.HoldsMoved(positions)
                 ? !(soft ? hang_box.DueSoft(positions, frame, retry) : hang_box.Due(positions, frame))
                 : !hang_still.Due(positions, frame))) {'''
E4 = r'''// bbport (r112i_hang-find-lanterns, TOOL grade; BB_WIND_HANG_FIND=1): the survey's lines (the header and the'''
E4P = r'''// bbport (r112q_hang-bracket-route, TOOL): the counters a draw's sway word and r112's verdict move, copied before and after the word
// (BbWindHangRoute::Classify says from them where the draw left the chain). Only with BB_WIND_HANG_FIND=1. On the thread recording draws.
BbWindHangRoute::Mark Rasterizer::WindHangRouteMark() {
    BbWindHangRoute::Mark mark;
    mark.called = sway_stats.draws;
    mark.no_region = sway_stats.no_region;
    mark.no_rt = sway_stats.no_rt;
    mark.no_camera = sway_stats.no_camera;
    mark.no_slot = sway_stats.no_slot + sway_stats.views_full;
    mark.plants = sway_stats.plants;
    mark.no_sun = hang_stats.no_sun;
    mark.settled = hang_stats.settled;
    mark.waiting = hang_stats.waiting;
    mark.moving = hang_stats.moving;
    mark.unfit = hang_stats.unfit;
    mark.forced = hang_route.forced_total;
    mark.why = hang_actors.by_why;
    return mark;
}

// bbport (r112q_hang-bracket-route, TOOL): a Motion block draw of the pipeline, with its kind ('S' skinned, 'P' GPU palette, 'O' static),
// the sway word it got and whether the word reached the draw's motion parameter: noted by its pair of shaders (the stream group).
void Rasterizer::WindHangRouteNote(const GraphicsPipeline* pipeline, char kind, u32 word, bool delivered) {
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto* const fragment = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    u64 stream = 0;
    const auto& fetch = pipeline->GetFetchShader();
    if (fetch) {
        for (const auto& attribute : fetch->attributes) {
            if (attribute.semantic == 0) {
                stream = attribute.GetSharp(vs).base_address;
                break;
            }
        }
    }
    const bool sway_bit = (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::Sway) != 0;
    hang_route.Note(vs.pgm_hash, fragment != nullptr ? fragment->pgm_hash : u64{0}, kind, sway_bit,
                    fragment != nullptr && fragment->has_discard, stream, word, delivered, hang_route_before,
                    WindHangRouteMark());
}

// bbport (r112q_hang-bracket-route, TOOL): BB_WIND_HANG_FORCE's word: a hang word with the live BB_WIND_HANG_STATIC_GAIN as its ramp (0 with
// the live BB_WIND_HANG_PUSH=0), no judge, no rule; the view's push table is filled as WindHangWord fills it. On the thread recording draws.
u32 Rasterizer::WindHangForceWord(u32* words, u32 frame_slot, u32 view, u32 slot, const BbWind::Snapshot& now) {
    const u64 frame = object_motion->Frame();
    if (frame != hang_frame) {
        hang_frame = frame;
        hang_filled = {};
    }
    if (!hang_filled[view]) {
        const u32* const words_of_view = words + BbWindSway::ViewAt(frame_slot, view);
        const auto& knob = BbWindSway::KnobOnce();
        std::array<float, BbWindSway::GustSamples> table{};
        hang_push.Fill(now, std::bit_cast<float>(words_of_view[BbWindSway::WindE + 2]),
                       std::bit_cast<float>(words_of_view[BbWindSway::WindE + 3]), knob.gusts,
                       knob.scale, table.data());
        std::memcpy(words + BbWindHang::PushAt +
                        (frame_slot * BbWindSway::Views + view) * BbWindSway::GustSamples,
                    table.data(), sizeof(table));
        hang_filled[view] = true;
    }
    ++hang_route.forced_total;
    const u32 ramp = WindHangLiveOn() ? BbWindHangFind::SameRamp(255u, WindHangGainNow(), 1.0f, true) : 0u;
    return BbWindHang::HangWord(frame_slot, view, slot, ramp);
}

// bbport (r112q_hang-bracket-route, TOOL): the window's route lines (BbWindHangRoute::Lines): one a stream group, then the books are cleared.
// On the thread recording draws, with r112's lines.
void Rasterizer::WindHangRouteReport() {
    static bool said = false;
    if (!said) {
        said = true;
        BbReport::Printf("%s\n", BbWindHangRoute::OnceText(static_cast<unsigned>(BbWindHangGpu::BoxRetry()),
                                                           BbWindHangRoute::ForceOn(), BbWindHangRoute::ForceOnce().all)
                                     .c_str());
    }
    WindHangFindRefresh(object_motion->Frame());
    const BbWindHangRoute::Lookup look = [this](u64 stream) {
        BbWindHangRoute::StreamInfo info;
        if (const BbWindHangFind::Box* const box = hang_find_boxes.Find(stream)) {
            info.scene = true;
            info.height = BbWindHangFind::HeightOf(box->box);
            info.width = BbWindHangFind::WidthOf(box->box);
            info.verts = box->vertices;
        }
        if (const BbWindHangStill::BoxEntry* const judged = hang_box.Find(stream)) {
            info.box = true;
            info.box_state = static_cast<std::uint8_t>(judged->state);
            info.dev = judged->dev;
        }
        if (const BbWindHang::Entry* const book = hang_book.Find(stream)) {
            info.book = true;
            info.moving = book->moving;
            info.judged = book->judged;
            info.fits = book->fits;
            info.why_moving = book->why_moving;
            info.box_only = book->box_only;
        }
        return info;
    };
    const BbWindHangRoute::PathOf path = [](u64 vs) {
        return BbWindTwigs::PathName(BbWindTwigs::ShaderPathOf(vs));
    };
    for (const std::string& line : BbWindHangRoute::Lines(hang_route, BbWindHangFind::KnobOnce().focus, look, path,
                                                          BbWindSway::ReportFrames)) {
        BbReport::Printf("%s\n", line.c_str());
    }
    hang_route.Clear();
}

'''
E5 = r'''        // bbport (r112p_hang-gpu-palette-lanterns): the refused streams' census and the palette writers (each when new), then'''
E5P = r'''        if (BbWindHangRoute::On()) { // bbport (r112q_hang-bracket-route, TOOL): one line a stream group (vs:ps), FIRST BREAK in each
            WindHangRouteReport();
        }
'''
E6 = r'''        hang_gpu_stats = {};'''
E6P = r'''        if (hang_gpu_watch.Watched() > 0 && hang_gpu_watch.Hits() == 0) { // bbport (r112q_hang-bracket-route): what 'writers found 0' means
            BbReport::Printf("%s\n", BbWindHangGpu::NoWriterText(hang_gpu_watch.Watched()).c_str());
        }
'''

# vk_pipeline_cache.cpp
P1 = r'''    if (BbWindTwigs::ProofOn() && info.hw_stage == HwStage::Vertex) { // bbport (r89l_twigs-palette-move, TOOL)'''
P1N = r'''    // bbport (r112q_hang-bracket-route): with BB_WIND_HANG=1 too (the route lines name the emitter of each vertex shader)
    if ((BbWindTwigs::ProofOn() || BbWindHang::KnobOnce().on) && info.hw_stage == HwStage::Vertex) { // bbport (r89l_twigs-palette-move, TOOL)'''

# vk_pipeline_serialization.cpp
Z1 = r'''BbWindTwigs::BinaryOffset() // (r89d_tree-twigs: 2000 with the twigs)'''
Z1N = r'''BbWindTwigs::BinaryOffset() + // (r89d_tree-twigs: 2000 with the twigs)
                     BbWindHang::ProofBinaryOffset() // (r112q_hang-bracket-route: 100000 with BB_WIND_HANG_PROOF=1, its tint is in the SPIR-V)'''
Z2 = r'''    u32 binary_version{};
    meta.Read(binary_version);
    if (binary_version != Serialization::ShaderBinaryVersion &&'''
Z2N = r'''    u32 binary_version{};
    meta.Read(binary_version);
    // bbport (r112q_hang-bracket-route): the version as saved (it may carry the hang proof's add: the check at the end of this function compares
    // it with the current one); the known-version tests below see it with that add taken out
    const u32 binary_saved = binary_version;
    binary_version = BbWindHang::StripProofVersion(binary_version);
    if (binary_version != Serialization::ShaderBinaryVersion &&'''
Z3 = r'''    if (binary_version != SwayOr(vertex_capture ? Serialization::CaptureShaderBinaryVersion'''
Z3N = r'''    if (binary_saved != SwayOr(vertex_capture ? Serialization::CaptureShaderBinaryVersion'''

# README.md
R1 = r'''| `BB_WIND_HANG_PROOF` |'''
R1P = r'''| `BB_WIND_HANG_BOX_RETRY` | Part of `BB_WIND_HANG_BOXJUDGE` (r112q; frames, 30 to 3600, default `120`, exactly `0` gives r112p's rule, text that is no number gives the default). A skinned stream the GPU box judges in place of its palette (a bracket lantern) whose box grew 0.25 m or more was "a character for good" and never judged again; but the box of a mesh drawn at several places is the union of the places the camera sees, and a camera turn changes it (b64: pushes before the look-up, none after it). Such a stream is now judged again this many frames after it was found moving, with a new window (about 70 frames), and is pushed again when it stands still. A real mover that stands still for those frames is pushed while it does (at most 0.08 m); the hunter's gear and indoor rules (r112h) are unchanged. |
| `BB_WIND_HANG_FORCE` | TOOL (r112q; test-tools branch; needs `BB_WIND_HANG=1`; off by default). `all`, or up to four vertex shader hashes in hex with `:` between them (as the route lines print them). A skinned draw of a sway pipeline of such a shader is given a hang word with no judge and no rule (the hunter and the trees too with `all`): its ramp is the live `BB_WIND_HANG_STATIC_GAIN` (the live `BB_WIND_HANG_PUSH=0` gives no motion), so that a picture shows whether the word reaches the shader and moves the mesh; if it does and the same lantern does not lean without the force, the judges are the break. Logged in the once line of the route lines. |
'''

# gpu/CMakeLists.txt, build.sh
M1 = r'''# bbport (r82_wind-stage1): the shared wind state and the CPU copy of the fog noise and march step'''
M1P = r'''# bbport (r112q_hang-bracket-route): the route lines, BB_WIND_HANG_FORCE, BB_WIND_HANG_BOX_RETRY and the judge's DueSoft
# (shim/bbport_wind_hang_route.h); also built and run by engine/build.sh --test.
add_executable(wind-hang-route-test EXCLUDE_FROM_ALL ../tests/test_wind_hang_route.cpp)
target_compile_options(wind-hang-route-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-hang-route-test PRIVATE ..)
'''
B1 = r'''    # bbport (r82_wind-stage1): the shared wind state, the fog noise and the march step'''
B1P = r'''    # bbport (r112q_hang-bracket-route): the route lines, BB_WIND_HANG_FORCE, BB_WIND_HANG_BOX_RETRY and the judge's DueSoft
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_wind_hang_route.cpp -o out/wind-hang-route-test
    out/wind-hang-route-test
'''

EDITS = {
HH: [
('ins', H1, H1P, ""),
],
HG: [
('ins', G1, G1P, ""),
('rep', G2, "", G2N),
('ins', G3, G3P, ""),
],
HS: [
('ins', S1, S1P, ""),
],
RH: [
('ins', V1, V1P, ""),
('ins', V2, V2P, ""),
('ins', V3, "", V3P),
],
RC: [
('ins', C1, C1P, ""),
('ins', C2, C2P, ""),
('ins', C3, C3P, ""),
('ins', C4, C4P, ""),
('ins', C5, C5P, ""),
('ins', C6, C6P, ""),
],
EF: [
('rep', E1, "", E1N),
('ins', E2, E2P, ""),
('rep', E3, "", E3N),
('ins', E4, E4P, ""),
('ins', E5, E5P, ""),
('ins', E6, E6P, ""),
],
PC: [
('rep', P1, "", P1N),
],
PS: [
('rep', Z1, "", Z1N),
('rep', Z2, "", Z2N),
('rep', Z3, "", Z3N),
],
RM: [
('ins', R1, R1P, ""),
],
CM: [
('ins', M1, M1P, ""),
],
BS: [
('ins', B1, B1P, ""),
],
}

ORDER = (HH, HG, HS, RH, RC, EF, PC, PS, RM, CM, BS)
NEW_ORDER = (HR, TR)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def parts_of(ed):
    if ed[0] == "rep":
        return ed[1], [ed[3]], [ed[1]]
    return ed[1], [t for t in (ed[2], ed[3]) if t], []


def state_of(cur, eds, path):
    done = todo = 0
    for ed in eds:
        anchor, present, absent = parts_of(ed)
        if ed[0] == "rep":
            n_old, n_new = cur.count(anchor), cur.count(present[0])
            if n_new == 1 and n_old == 0:
                done += 1
            elif n_old == 1 and n_new == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times (wanted once), new text %d "
                                 "times: %r" % (path, n_old, n_new, anchor[:70]))
            continue
        na, counts = cur.count(anchor), [cur.count(t) for t in present]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s "
                             "times: %r" % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_edits(cur, eds):
    for ed in eds:
        if ed[0] == "rep":
            cur = cur.replace(ed[1], ed[3], 1)
        else:
            cur = cur.replace(ed[1], ed[2] + ed[1] + ed[3], 1)
    return cur


def revert_edits(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "rep":
            cur = cur.replace(ed[3], ed[1], 1)
        else:
            for part in (ed[3], ed[2]):
                if part:
                    cur = cur.replace(part, "", 1)
    return cur


def new_state(path):
    """clean: the file is absent; applied: it is there with the patch's text; anything else refuses."""
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    have = open(full, "rb").read().decode("utf-8").replace("\r\n", "\n")
    if have != NEW_FILES[path]:
        raise SystemExit("REFUSED %s: the file exists and is not this patch's" % path)
    return "applied"


def balance(text):
    """(braces, parens, brackets) net of a C++ text without comments, strings and char literals."""
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', text)
    text = re.sub(r"'(?:\\.|[^'\\\n])'", "' '", text)
    return (text.count("{") - text.count("}"), text.count("(") - text.count(")"),
            text.count("[") - text.count("]"))


CPP = (HH, HG, HS, RH, RC, EF, PC, PS)


def text_checks(texts, olds):
    """The ties a compiler cannot check."""
    hh, hg, hs, rh, rc, ef, pc, ps = (texts[p] for p in CPP)
    hr, tr = NEW_FILES[HR], NEW_FILES[TR]
    for path in CPP:
        if balance(texts[path]) != balance(olds[path]):
            raise SystemExit("text check: %s: braces, parens or brackets changed by %r" %
                             (path, tuple(a - b for a, b in zip(balance(texts[path]), balance(olds[path])))))
    for path, text in ((HR, hr), (TR, tr)):
        if balance(text) != (0, 0, 0):
            raise SystemExit("text check: %s: braces, parens or brackets do not balance: %r" % (path, balance(text)))
        if "\t" in text:
            raise SystemExit("text check: a tab in %s" % path)
        try:
            text.encode("ascii")
        except UnicodeEncodeError:
            raise SystemExit("text check: %s is not ASCII" % path)
    for name in (H1P, G1P, G3P, S1P, V2P, V3P, C1P, C2P, C3P, C4P, E2P, E4P, E5P, E6P):
        if balance(name) != (0, 0, 0) and name not in (V3P,):
            raise SystemExit("text check: an inserted block does not balance: %r" % name[:60])
        try:
            name.encode("ascii")
        except UnicodeEncodeError:
            raise SystemExit("text check: a non-ASCII character in an inserted block: %r" % name[:60])
    # the new header: names, order, every switch names every value
    for needle in ("inline bool On()", "inline Force ParseForce(", "inline const Force& ForceOnce()", "inline bool ForceMatches(", "inline Exit Classify(",
                   "class Book {", "inline std::string FirstBreak(", "inline std::string GroupLine(", "inline std::vector<std::string> Lines(",
                   "inline std::string OnceText(", "BracketVs = 0xe859b6d9u"):
        if needle not in hr:
            raise SystemExit("text check: %s missing in the new header" % needle)
    exits = ["NoWord", "NoRegion", "NoRt", "NoCamera", "NoSlot", "Plant", "NoSun", "Settled", "Waiting", "Moving", "Unfit", "Refused", "Other",
             "OtherWord", "Keys", "Pushed", "Forced"]
    m = re.search(r"enum class Exit : std::uint8_t \{(.*?)\n\};", hr, re.S)
    names = [x.strip() for x in re.sub(r"///[^\n]*", "", m.group(1)).replace("\n", " ").split(",") if x.strip()]
    if names != exits or "ExitCount = %d;" % len(exits) not in hr:
        raise SystemExit("text check: Exit has %r, ExitCount must be %d" % (names, len(exits)))
    for fn in ("inline const char* ExitName(", "inline std::string FirstBreak("):
        seg = hr[hr.index(fn):hr.index(fn) + 6000]
        for v in exits:
            if "case Exit::%s:" % v not in seg:
                raise SystemExit("text check: %s misses Exit::%s" % (fn, v))
    for first, second in (("inline const Force& ForceOnce()", "inline bool ForceMatches("), ("struct Mark {", "inline Exit Classify("),
                          ("enum class Exit", "inline Exit Classify("), ("struct Group {", "class Book {"), ("struct StreamInfo {", "class Book {"),
                          ("class Book {", "inline std::string FirstBreak("), ("inline std::string FirstBreak(", "inline std::string GroupLine("),
                          ("inline const char* BookName(", "inline std::string GroupLine("), ("inline std::string GroupLine(", "inline std::vector<std::string> Lines(")):
        if hr.index(first) > hr.index(second):
            raise SystemExit("text check: %s must precede %s in the new header" % (first, second))
    # the real enums and constants the header assumes
    actors = open(os.path.join(ROOT, SH + "bbport_wind_hang_actors.h"), "rb").read().decode("utf-8")
    m = re.search(r"enum class Why : std::uint8_t \{(.*?)\};", actors, re.S)
    why = [x.strip() for x in m.group(1).split(",") if x.strip()]
    if why != ["Ok", "NoHunter", "Near", "Bones", "Indoor", "Unplaced", "NoPalette"] or "WhyCount = 7;" not in actors:
        raise SystemExit("text check: BbWindHangActors::Why changed: %r" % why)
    still = open(os.path.join(ROOT, SH + "bbport_wind_hang_still.h"), "rb").read().decode("utf-8")
    if not re.search(r"enum class BoxState : std::uint8_t \{\s*Judging,[^\n]*\n\s*Still,[^\n]*\n\s*Moved,", still):
        raise SystemExit("text check: BoxState's order (judging, still, moved) is what the route line assumes")
    if "std::array<std::uint64_t, WhyCount> by_why{};" not in actors:
        raise SystemExit("text check: by_why")
    # the proof's version add
    if hh.count("inline constexpr std::uint32_t ProofBinaryAdd = 100000;") != 1 or hh.index("inline bool ProofOn()") > hh.index("inline std::uint32_t ProofBinaryOffset()"):
        raise SystemExit("text check: the proof's add comes after ProofOn")
    if ps.count("BbWindHang::ProofBinaryOffset()") != 1 or ps.count("binary_saved") != 2 or ps.count("BbWindHang::StripProofVersion(binary_version)") != 1:
        raise SystemExit("text check: the serialization edits")
    load_at = ps.index("bool LoadShaderMeta(")
    if not (load_at < ps.index("const u32 binary_saved = binary_version;") < ps.index("if (binary_saved != SwayOr(")):
        raise SystemExit("text check: binary_saved is declared before it is used, inside LoadShaderMeta")
    # the gpu header: retry knob, writer codes, StageName, TakeLines
    for needle in ("inline std::uint64_t BoxRetry()", "WriterCopy = 100, WriterFill = 101, WriterGuest = 102, WriterCommand = 103;", "inline std::string NoWriterText(",
                   "if (stage >= WriterCopy) {", "if (h.stage >= WriterCopy) {"):
        if needle not in hg:
            raise SystemExit("text check: %s missing in the gpu header" % needle)
    if hg.index("WriterCopy = 100") > hg.index("inline const char* StageName(") or hg.index("inline const char* WriterName(") > hg.index("inline const char* StageName("):
        raise SystemExit("text check: the writer codes come before StageName")
    if hg.index("h.stage >= WriterCopy") > hg.index("out.emplace_back(buf);"):
        raise SystemExit("text check: the writers' branch comes before the line is emitted")
    if hs.count("bool DueSoft(") != 1 or hs.index("bool DueSoft(") < hs.index("bool Due(std::uint64_t stream, std::uint64_t frame) {"):
        raise SystemExit("text check: DueSoft calls Due: Due comes first")
    # the rasterizer: declarations, members, includes
    for needle in ("BbWindHangRoute::Mark WindHangRouteMark();", "void WindHangRouteNote(const GraphicsPipeline* pipeline, char kind, u32 word, bool delivered);",
                   "void WindHangRouteReport();", "u32 WindHangForceWord(u32* words, u32 frame_slot, u32 view, u32 slot, const BbWind::Snapshot& now);",
                   "BbWindHangRoute::Book hang_route;", "BbWindHangRoute::Mark hang_route_before;"):
        if rh.count(needle) != 1:
            raise SystemExit("text check: rasterizer.h lacks %r" % needle)
    if not (rh.index('#include "bbport_wind_hang_find.h"') < rh.index('#include "bbport_wind_hang_route.h"') and
            rh.index('#include "bbport_wind_hang_actors.h"') < rh.index('#include "bbport_wind_hang_route.h"') and
            rh.index('#include "bbport_wind_hang_route.h"') < rh.index("BbWindHangRoute::Book hang_route;")):
        raise SystemExit("text check: the route header is included after its dependencies and before its members")
    # the Motion block: the mark before the word, the note after the Draw call, both inside the block
    mark_at = rc.index("hang_route_before = WindHangRouteMark();")
    sway_at = rc.index("const u32 sway =")
    note_at = rc.index("WindHangRouteNote(pipeline,")
    draw_at = rc.index("dc.push_data.motion_param = object_motion->Draw({")
    if not (mark_at < sway_at < draw_at < note_at) or rc.count("hang_route_before = WindHangRouteMark();") != 1 or rc.count("WindHangRouteNote(pipeline,") != 1:
        raise SystemExit("text check: the Motion block's mark and note")
    if rc.index("if (sway != 0 && dc.push_data.motion_param == 0) {") < note_at:
        raise SystemExit("text check: the note comes before r112h's no_param line")
    for fn, hook in (("void Rasterizer::FillBuffer(", "BbWindHangGpu::WriterFill"), ("void Rasterizer::CopyBuffer(", "BbWindHangGpu::WriterCopy"),
                     ("bool Rasterizer::WriteGuestMemory(", "BbWindHangGpu::WriterGuest"), ("bool Rasterizer::WriteDataOnGpu(", "BbWindHangGpu::WriterCommand")):
        a = rc.index(fn)
        b = rc.index(hook)
        end = rc.find("\n}\n", a)
        if rc.count(hook) != 1 or not (a < b < end):
            raise SystemExit("text check: the watch hook of %s is not inside it" % fn)
    # the effects file: the force, the retry, the new functions, the report
    w0 = ef.index("u32 Rasterizer::WindSwayWord(")
    w1 = ef.index("// bbport (r112_wind-more-things): BB_WIND_HANG=1 (bbport_wind_hang.h): a skinned draw of a sway")
    word = ef[w0:w1]
    order = ["const bool plant =", "const bool tree =", "hang_judge = false;", "bool hang = !plant", "const bool judge =", "const bool force =",
             "if (!plant && !hang && !tree && !judge && !force) {", "const auto taken = sway_slots.Take(", "if (tree) {", "if (force) {", "if (judge) {", "if (hang) {"]
    last = -1
    for needle in order:
        k = word.find(needle)
        if k < 0 or k < last:
            raise SystemExit("text check: WindSwayWord: %r missing or out of order" % needle)
        last = k
    if "const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);" not in word[:word.index("const bool force =")]:
        raise SystemExit("text check: vs is declared before the force uses it")
    v0 = ef.index("bool Rasterizer::WindHangVerdict(")
    v1 = ef.index("bool Rasterizer::WindHangActorsClear(")
    verdict = ef[v0:v1]
    if verdict.index("const BbWindHang::Entry* const known =") > verdict.index("const bool soft =") or verdict.count("DueSoft(positions, frame, retry)") != 1:
        raise SystemExit("text check: the retry uses known after it is declared")
    if verdict.index("hang_box.Forget(positions);") < verdict.index("const bool soft ="):
        raise SystemExit("text check: the retry's test comes before the stream is forgotten")
    for fn in ("BbWindHangRoute::Mark Rasterizer::WindHangRouteMark()", "void Rasterizer::WindHangRouteNote(", "u32 Rasterizer::WindHangForceWord(",
               "void Rasterizer::WindHangRouteReport()"):
        if ef.count(fn) != 1:
            raise SystemExit("text check: %s defined %d times" % (fn, ef.count(fn)))
    if ef.index("static float WindHangGainNow()") > ef.index("u32 Rasterizer::WindHangForceWord(") or ef.index("static bool WindHangLiveOn()") > ef.index("u32 Rasterizer::WindHangForceWord("):
        raise SystemExit("text check: the live knob helpers are defined before the force word")
    r0 = ef.index("WindHangRouteReport();\n        }\n        // bbport (r112p_hang-gpu-palette-lanterns): the refused streams' census")
    if not (ef.index("hang_box.ClearNotes();") > r0 and ef.index("hang_stats = {};", r0) > r0):
        raise SystemExit("text check: the report hook sits before r112's clears")
    if ef.index("BbWindHangGpu::NoWriterText(") > ef.index("hang_gpu_stats = {};" + chr(10) + "        hang_box.ClearNotes();") or ef.index("BbWindHangGpu::NoWriterText(") < r0:
        raise SystemExit("text check: the no-writer line is printed before r112p's stats are cleared")
    # the knob names and the log prefixes the lead greps for
    for needle in ("BB_WIND_HANG_BOX_RETRY", "BB_WIND_HANG_FORCE", "Wind sway hang route (r112q)", "FIRST BREAK", "Wind sway hang (r112q)"):
        if needle not in hr + hg:
            raise SystemExit("text check: %s missing in the headers" % needle)
    rm = texts[RM]
    if rm.count("| `BB_WIND_HANG_BOX_RETRY` |") != 1 or rm.count("| `BB_WIND_HANG_FORCE` |") != 1 or \
            rm.index("| `BB_WIND_HANG_FORCE` |") > rm.index("| `BB_WIND_HANG_PROOF` |"):
        raise SystemExit("text check: the README rows")
    if texts[CM].count("wind-hang-route-test") != 3 or texts[BS].count("wind-hang-route-test") != 2:
        raise SystemExit("text check: the test registrations")
    if "int main()" not in tr or "wind-hang-route-test: all passed" not in tr:
        raise SystemExit("text check: the test's main")
    # the test's strings are what the header prints
    for needle in ("none up to the shader: 6 pushed words were delivered", "scene 1.32 m tall 0.88 m wide 1907 verts, judge moved dev 310 mm, book moving (why 3, box 1)",
                   "NO draw of it reached the Motion block", "vs:ps e859b6d9:e21e283a [bracket]", "3 stream groups"):
        if needle not in tr:
            raise SystemExit("text check: the test lacks %r" % needle)
    for needle in ("none up to the shader: %llu pushed words were delivered", "scene %.2f m tall %.2f m wide %u verts, judge %s dev %.0f mm, book %s (why %u, box %u);",
                   "NO draw of it reached the", "vs:ps %08x:%08x%s", "%zu stream groups (vs:ps)", "[bracket]"):
        if needle not in hr:
            raise SystemExit("text check: the header lacks %r" % needle)
    for needle in ("a DMA copy destination (no shader) writes", "lies INSIDE that range", "a guest-memory write (no shader)"):
        pass
    for needle in ("palette writer %zu: a %s (no shader) writes", "DMA copy destination", "guest-memory write"):
        if needle not in hg:
            raise SystemExit("text check: the gpu header lacks %r" % needle)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112Q_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == EF and "hang_gpu_census" not in cur:
            raise SystemExit("REFUSED: r112p must be applied")
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    news = [(path, new_state(path)) for path in NEW_ORDER]
    states = {p[5] for p in plan} | {n[1] for n in news}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) + ", " +
                         ", ".join("%s %s" % n for n in news))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_edits(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    olds = {p[0]: p[4] for p in plan}
    if cmd == "check":
        if state == "applied":
            text_checks(olds, {p[0]: revert_edits(p[4], p[1]) for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts(), olds)
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW_ORDER)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts, olds)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r112qtmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path in NEW_ORDER:
            open(os.path.join(ROOT, path), "wb").write(NEW_FILES[path].replace("\n", "\r\n").encode("utf-8"))
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_edits(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r112qtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_ORDER:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


if __name__ == "__main__":
    main()
