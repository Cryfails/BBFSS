// SPDX-License-Identifier: GPL-3.0-or-later
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

// ---- bbport (r112r_hang-bracket-judge, TOOL): which pairs of shaders got a hang word, the proof's tint --------------------------------

inline constexpr std::size_t SeenMost = 384;     ///< pairs of shaders kept (never cleared: the pick reads them a minute later)
inline constexpr std::size_t TintLinesMost = 10; ///< pairs a report names

/// What the Motion block did with the draws of one pair of shaders since the start.
struct Seen {
    std::uint64_t vs = 0, ps = 0;
    std::uint64_t draws = 0;              ///< Motion block draws of the pair
    std::uint64_t words = 0;              ///< of them, draws whose hang word reached the motion parameter: the draws the proof tints
    std::array<std::uint64_t, 3> kinds{}; ///< of those, skinned, GPU palette, static
    std::uint64_t pushed = 0;             ///< of those, a ramp above 0
    std::uint64_t hidden = 0;             ///< of those, left out of the picture (BB_WIND_HANG_PROOF_HIDE)
    std::uint64_t first = 0, last = 0;    ///< the frames of the first and of the last of those
};

/// BB_WIND_HANG_PROOF_HIDE (live): exactly 1.
[[nodiscard]] inline bool ParseHide(const char* text) {
    return text != nullptr && text[0] == '1' && text[1] == 0;
}

class TintBook {
public:
    std::uint64_t dropped = 0; ///< pairs not kept for want of room

    /// A Motion block draw of the pair (vs, ps) of `kind` ('S', 'P' or 'O') with the sway word `word`; `delivered` it reached the motion
    /// parameter, `hidden` the draw is left out of the picture. Only a delivered word with the hang bit counts as a word (the proof's
    /// shaders tint the vertices of such a word whatever its ramp).
    void Note(std::uint64_t vs, std::uint64_t ps, char kind, std::uint32_t word, bool delivered, bool hidden, std::uint64_t frame) {
        const std::uint64_t key = ((vs & 0xffffffffu) << 32) | (ps & 0xffffffffu);
        auto found = seen.find(key);
        if (found == seen.end()) {
            if (seen.size() >= SeenMost) {
                ++dropped;
                return;
            }
            found = seen.emplace(key, Seen{}).first;
            found->second.vs = vs;
            found->second.ps = ps;
        }
        Seen& s = found->second;
        ++s.draws;
        if (!delivered || word == 0 || (word & H::HangBit) == 0) {
            return;
        }
        if (s.words == 0) {
            s.first = frame;
        }
        ++s.words;
        s.last = frame;
        s.kinds[kind == 'S' ? 0u : (kind == 'P' ? 1u : 2u)] += 1u;
        s.pushed += BbWindSway::Unpack(word).ramp > 0 ? 1u : 0u;
        s.hidden += hidden ? 1u : 0u;
    }

    [[nodiscard]] const Seen* Find(std::uint64_t vs, std::uint64_t ps) const {
        const auto found = seen.find(((vs & 0xffffffffu) << 32) | (ps & 0xffffffffu));
        return found == seen.end() ? nullptr : &found->second;
    }

    [[nodiscard]] std::size_t Pairs() const {
        return seen.size();
    }

    /// The report: a header (pairs seen, pairs and draws that got a hang word) and one line for each of the `most` pairs with the most
    /// words (ties by vs:ps).
    [[nodiscard]] std::vector<std::string> Lines(std::size_t most) const {
        std::vector<std::string> out;
        std::vector<const Seen*> order;
        std::uint64_t draws = 0, words = 0;
        for (const auto& item : seen) {
            draws += item.second.draws;
            words += item.second.words;
            if (item.second.words > 0) {
                order.push_back(&item.second);
            }
        }
        std::sort(order.begin(), order.end(), [](const Seen* a, const Seen* b) {
            if (a->words != b->words) {
                return a->words > b->words;
            }
            return a->vs < b->vs || (a->vs == b->vs && a->ps < b->ps);
        });
        char head[560];
        std::snprintf(head, sizeof(head),
                      "Wind sway hang proof (r112r): since the start %zu pairs of shaders drew %llu Motion block draws, %zu pairs and %llu draws "
                      "with a hang word delivered to the motion parameter (BB_WIND_HANG_PROOF tints every vertex of such a draw, whatever its "
                      "ramp)%s%s",
                      seen.size(), static_cast<unsigned long long>(draws), order.size(), static_cast<unsigned long long>(words),
                      order.empty() ? ": NO draw got a hang word, nothing is tinted" : "; most draws first:",
                      dropped > 0 ? " (pairs dropped: the table was full)" : "");
        out.emplace_back(head);
        for (std::size_t i = 0; i < order.size() && i < most; ++i) {
            const Seen& s = *order[i];
            char one[400];
            std::snprintf(one, sizeof(one),
                          "Wind sway hang proof (r112r): tinted vs:ps %08x:%08x: %llu draws (skinned %llu, GPU palette %llu, static %llu), ramp "
                          "above 0 in %llu, hidden %llu, frames %llu to %llu, of %llu Motion block draws of the pair",
                          static_cast<unsigned>(s.vs & 0xffffffffu), static_cast<unsigned>(s.ps & 0xffffffffu),
                          static_cast<unsigned long long>(s.words), static_cast<unsigned long long>(s.kinds[0]),
                          static_cast<unsigned long long>(s.kinds[1]), static_cast<unsigned long long>(s.kinds[2]),
                          static_cast<unsigned long long>(s.pushed), static_cast<unsigned long long>(s.hidden),
                          static_cast<unsigned long long>(s.first), static_cast<unsigned long long>(s.last),
                          static_cast<unsigned long long>(s.draws));
            out.emplace_back(one);
        }
        return out;
    }

    /// The line under a glass pick row: what the pair of the draw that wrote the pixel got from the Motion block (`proof_on`: the proof's
    /// shaders tint those draws).
    [[nodiscard]] std::string PickText(int x, int y, std::uint32_t vs, std::uint32_t ps, bool proof_on) const {
        const Seen* const s = Find(vs, ps);
        char buf[700];
        if (s == nullptr) {
            std::snprintf(buf, sizeof(buf),
                          "Wind sway hang route (r112r): pick pixel %d,%d vs:ps %08x:%08x: no Motion block draw of this pair of shaders was seen "
                          "since the start: the draw that wrote the pixel does not go through the Motion block (no motion pipeline, or a pass it "
                          "is not asked in), so no hang word can reach it",
                          x, y, static_cast<unsigned>(vs), static_cast<unsigned>(ps));
        } else if (s->words == 0) {
            std::snprintf(buf, sizeof(buf),
                          "Wind sway hang route (r112r): pick pixel %d,%d vs:ps %08x:%08x: %llu Motion block draws of this pair, NONE with a hang "
                          "word delivered to the motion parameter (the route line of the pair says where its draws leave the chain); nothing "
                          "is tinted or hidden",
                          x, y, static_cast<unsigned>(vs), static_cast<unsigned>(ps), static_cast<unsigned long long>(s->draws));
        } else {
            std::snprintf(buf, sizeof(buf),
                          "Wind sway hang route (r112r): pick pixel %d,%d vs:ps %08x:%08x: %llu Motion block draws of this pair, %llu with a hang "
                          "word delivered (skinned %llu, GPU palette %llu, static %llu; ramp above 0 in %llu; hidden %llu; frames %llu to %llu): %s",
                          x, y, static_cast<unsigned>(vs), static_cast<unsigned>(ps), static_cast<unsigned long long>(s->draws),
                          static_cast<unsigned long long>(s->words), static_cast<unsigned long long>(s->kinds[0]),
                          static_cast<unsigned long long>(s->kinds[1]), static_cast<unsigned long long>(s->kinds[2]),
                          static_cast<unsigned long long>(s->pushed), static_cast<unsigned long long>(s->hidden),
                          static_cast<unsigned long long>(s->first), static_cast<unsigned long long>(s->last),
                          proof_on ? "the proof tints these draws: cyan on the pixel = this pair, no cyan = the tint does not run"
                                   : "BB_WIND_HANG_PROOF is off: nothing is tinted");
        }
        return std::string(buf);
    }

private:
    std::unordered_map<std::uint64_t, Seen> seen;
};

/// The once line of the proof (BB_WIND_HANG_PROOF=1): `share` ProofShare, `add` ProofBinaryAdd.
[[nodiscard]] inline std::string ProofOnceText(float share, std::uint32_t add) {
    char buf[1000];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang proof (r112r, TOOL): BB_WIND_HANG_PROOF=1: every vertex shader of a sway pipeline, lifted AND recompiled, tints all "
                  "its float outputs %.0f percent toward cyan for every vertex whose motion word has the hang bit, whatever its ramp (r112m tinted "
                  "only a ramp above 0 and the recompiler never); the draws whose hang word reached the motion parameter are counted by vs:ps "
                  "(lines every 600 frames with BB_WIND_HANG_FIND=1, and under each row of the glass pick, BB_GLASS_PICK); "
                  "BB_WIND_HANG_PROOF_HIDE=1 (live) leaves those draws out of the picture; the hang shaders have their own cache version (+%u), "
                  "so they are compiled again for this proof",
                  static_cast<double>(share) * 100.0, static_cast<unsigned>(add));
    return std::string(buf);
}

} // namespace BbWindHangRoute
