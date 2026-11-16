// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r83_glass-water-stage1): window panes in the ray traced scene (BB_RT_GLASS). No Vulkan
// here: tests/test_rt_glass.cpp builds this header alone and runs the code the engine runs.
//
// The game draws its window panes FORWARD, after the G-buffer: one colour target (the scene
// colour), alpha blended, depth write on, and a pixel shader that discards (the surface probe of
// 2026-11-15 at eight places). The ray traced scene takes only draws with 0 colour targets (the
// sun shadow pass) or 5 and more (the G-buffer): capture variants exist only for them
// (PipelineCache::RefreshGraphicsKey), so no pane is in the scene and lamp and sun rays pass
// every window. Light through glass (a tint, the window's shape on the floor, glass reflections)
// needs the panes in the scene first, kept apart from what today's rays hit.
//
// With BB_RT_GLASS on, a forward draw (1 or 2 colour targets, a depth target, one sample,
// clipping on, plain VS stages) of a shader pair the knob names gets the capture variant too.
// RtShadow keeps it as an entry of its own (RtGlassKey) under RtGlassMask alone, which no ray
// of today traces; the bounced light's rays are built to leave it out (GLASS_SCENE). So the
// picture stays as it is; a later stage traces the mask.

#include <array>
#include <atomic> // bbport (r86l_glint-pick-glass)
#include <cstddef>
#include <cstdint>
#include <cstdlib>

#include "../host_shaders/rt_glass_layout.h"

namespace Vulkan {

/// The instance mask of a window pane's entry, and of its TLAS record, alone.
inline constexpr std::uint8_t RtGlassMask = RT_GLASS_MASK;
static_assert(RtGlassMask != 0 && (RtGlassMask & (RtGlassMask - 1)) == 0, "one bit");

/// A pane's shader pair: the vertex and pixel shader's pgm_hash.
struct RtGlassPair {
    std::uint64_t vs = 0;
    std::uint64_t ps = 0;
};

/// BB_RT_GLASS=1: the pairs the surface probe of 2026-11-15 took for window glass (likely, not
/// proven: the probe cannot tell which draw made which pixel). c6cdba2b:c31bd920 is the only
/// glass-like pair at church-candles (one draw a frame, 360 indices, a tall sRGB albedo) and draws
/// the house windows at graveyard-blood; c6cdba2b:6720ae0d is its sibling at lamp-test-spot,
/// church-puddles, graveyard-blood and dark-alley.
inline constexpr std::array<RtGlassPair, 2> RtGlassBuiltIn{{
    {0xc6cdba2bull, 0xc31bd920ull},
    {0xc6cdba2bull, 0x6720ae0dull},
}};

/// Pairs the knob's text may name.
inline constexpr std::size_t RtGlassPairsMost = 8;

struct RtGlassKnob {
    bool on = false;
    bool listed = false; ///< the pairs are the text's, not RtGlassBuiltIn
    bool automatic = false; ///< "auto" (r86g_glint-find-bottles): no pairs, the draw's state decides
    std::uint32_t count = 0;
    std::array<RtGlassPair, RtGlassPairsMost> pairs{};
};

/// A hex digit's value, or -1.
constexpr int RtGlassHexDigit(char c) {
    return c >= '0' && c <= '9'   ? c - '0'
           : c >= 'a' && c <= 'f' ? c - 'a' + 10
           : c >= 'A' && c <= 'F' ? c - 'A' + 10
                                  : -1;
}

/// Reads a hex number at text[at] (an optional 0x first, 1 to 16 digits) into value and moves at
/// past it; false (at and value as they were) when there is none or it has more than 16 digits.
constexpr bool RtGlassReadHex(const char* text, std::size_t& at, std::uint64_t& value) {
    std::size_t i = at;
    if (text[i] == '0' && (text[i + 1] == 'x' || text[i + 1] == 'X')) {
        i += 2;
    }
    std::size_t digits = 0;
    std::uint64_t v = 0;
    while (RtGlassHexDigit(text[i]) >= 0) {
        if (++digits > 16) {
            return false;
        }
        v = v * 16 + std::uint64_t(RtGlassHexDigit(text[i]));
        ++i;
    }
    if (digits == 0) {
        return false;
    }
    at = i;
    value = v;
    return true;
}

/// BB_RT_GLASS's text. Unset, empty or "0": off. "1": the built-in pairs. Otherwise a list of
/// "vs:ps" pairs (hex, each 1 to 16 digits, an optional 0x, neither 0), at most RtGlassPairsMost,
/// separated by ',', ';' or ' ' (leading and trailing ones too): those pairs. Anything else (a
/// malformed pair, a zero hash, more than RtGlassPairsMost pairs): off, nothing half read.
constexpr RtGlassKnob ParseRtGlass(const char* text) {
    RtGlassKnob off{};
    if (!text || text[0] == '\0' || (text[0] == '0' && text[1] == '\0')) {
        return off;
    }
    if (text[0] == '1' && text[1] == '\0') {
        RtGlassKnob knob{};
        knob.on = true;
        for (const RtGlassPair& pair : RtGlassBuiltIn) {
            knob.pairs[knob.count++] = pair;
        }
        return knob;
    }
    // bbport (r86g_glint-find-bottles): "auto": glass by state (RtGlassAutoDraw), no pair list
    if (text[0] == 'a' && text[1] == 'u' && text[2] == 't' && text[3] == 'o' && text[4] == '\0') {
        RtGlassKnob automatic{};
        automatic.on = true;
        automatic.automatic = true;
        return automatic;
    }
    RtGlassKnob listed{};
    listed.listed = true;
    std::size_t at = 0;
    const auto skip = [&] {
        while (text[at] == ',' || text[at] == ';' || text[at] == ' ') {
            ++at;
        }
    };
    skip();
    while (text[at] != '\0') {
        std::uint64_t vs = 0, ps = 0;
        if (!RtGlassReadHex(text, at, vs) || text[at] != ':') {
            return off;
        }
        ++at;
        if (!RtGlassReadHex(text, at, ps) || vs == 0 || ps == 0 ||
            listed.count == RtGlassPairsMost) {
            return off;
        }
        if (text[at] != '\0' && text[at] != ',' && text[at] != ';' && text[at] != ' ') {
            return off;
        }
        listed.pairs[listed.count++] = {vs, ps};
        skip();
    }
    listed.on = listed.count != 0;
    return listed.on ? listed : off;
}

/// Whether the knob names the pair (off: never).
constexpr bool RtGlassMatches(const RtGlassKnob& knob, std::uint64_t vs, std::uint64_t ps) {
    for (std::uint32_t i = 0; knob.on && i < knob.count; ++i) {
        if (knob.pairs[i].vs == vs && knob.pairs[i].ps == ps) {
            return true;
        }
    }
    return false;
}

/// The colour targets a forward pane draw may have (bound with writes on): the scene colour,
/// and one more at most. The G-buffer (5 and more) and the shadow pass (0) have capture variants
/// of their own.
constexpr bool RtGlassTargetsFit(std::uint32_t bound) {
    return bound == 1 || bound == 2;
}

/// A pane's entry key: apart from any pass's entry of the same mesh (a sun shadow pass may draw
/// the same vertices, and its entry keeps the sun and lamp bits). Never the key itself.
inline constexpr std::uint64_t RtGlassKeySalt = 0x6a09e667f3bcc909ull;
constexpr std::uint64_t RtGlassKey(std::uint64_t key) {
    return key ^ RtGlassKeySalt;
}

/// Whether an entry's mask is a pane's.
constexpr bool RtGlassEntry(std::uint8_t entry_mask) {
    return (entry_mask & RtGlassMask) != 0;
}

/// A TLAS record's mask: RtGlassMask alone for a pane's entry, else the record of before.
constexpr std::uint8_t RtGlassRecordMask(std::uint8_t entry_mask, std::uint8_t record_mask) {
    return RtGlassEntry(entry_mask) ? RtGlassMask : record_mask;
}

/// The bounced light's instance mask in its GLASS_SCENE build (ssgi_gather_ray.comp).
inline constexpr std::uint32_t RtGlassBounceMask = 0xffu & ~std::uint32_t(RT_GLASS_MASK);

/// The pane draws since the last line (RtShadow::NoteGlassDraw).
inline constexpr std::uint64_t RtGlassWindowFrames = 600;
struct RtGlassStats {
    std::uint64_t window_start = 0; ///< 0: no pane drawn yet
    std::uint64_t draws = 0;
    std::uint64_t triangles = 0;
};

/// What a pane draw at `frame` with `triangles` says: counted, then 1 for the very first pane
/// draw (a line now, the window starts), 2 once RtGlassWindowFrames frames passed since the
/// window started (the window's line, then RtGlassWindowNext), 0 otherwise.
constexpr int RtGlassNote(RtGlassStats& stats, std::uint64_t frame, std::uint32_t triangles) {
    ++stats.draws;
    stats.triangles += triangles;
    if (stats.window_start == 0) {
        stats.window_start = frame == 0 ? 1 : frame;
        return 1;
    }
    return frame >= stats.window_start + RtGlassWindowFrames ? 2 : 0;
}

/// A new window from `frame`.
constexpr void RtGlassWindowNext(RtGlassStats& stats, std::uint64_t frame) {
    stats.window_start = frame == 0 ? 1 : frame;
    stats.draws = 0;
    stats.triangles = 0;
}

/// The knob, read once.
inline const RtGlassKnob& RtGlass() {
    static const RtGlassKnob knob = ParseRtGlass(std::getenv("BB_RT_GLASS"));
    return knob;
}

inline bool RtGlassOn() {
    return RtGlass().on;
}

// bbport (r86l_glint-pick-glass, TOOL): shader pairs the glass pick took at run time (BB_GLASS_PICK_PANES: a forward draw is
// taken by its pair). A fixed table of relaxed atomics: written by the frame end, read by every draw and by the pipeline
// key; empty while no pane is picked (one load). RtGlassMatch reads it after the knob's list, so a picked pair is a listed one.
inline constexpr std::size_t RtGlassPickPairsMost = 16;
struct RtGlassPickTable {
    std::atomic<std::uint32_t> count{0};
    std::array<std::atomic<std::uint64_t>, RtGlassPickPairsMost> vs{};
    std::array<std::atomic<std::uint64_t>, RtGlassPickPairsMost> ps{};
};

inline RtGlassPickTable& RtGlassPicked() {
    static RtGlassPickTable table;
    return table;
}

inline bool RtGlassPickPair(std::uint64_t vs, std::uint64_t ps) {
    const RtGlassPickTable& table = RtGlassPicked();
    const std::uint32_t n = table.count.load(std::memory_order_acquire);
    for (std::uint32_t i = 0; i < n; ++i) {
        if (table.vs[i].load(std::memory_order_relaxed) == vs && table.ps[i].load(std::memory_order_relaxed) == ps) {
            return true;
        }
    }
    return false;
}

/// Adds a pair: false when it is zero, known, or the table is full.
inline bool RtGlassPickAdd(std::uint64_t vs, std::uint64_t ps) {
    if (vs == 0 || ps == 0 || RtGlassPickPair(vs, ps)) {
        return false;
    }
    RtGlassPickTable& table = RtGlassPicked();
    const std::uint32_t n = table.count.load(std::memory_order_relaxed);
    if (n >= RtGlassPickPairsMost) {
        return false;
    }
    table.vs[n].store(vs, std::memory_order_relaxed);
    table.ps[n].store(ps, std::memory_order_relaxed);
    table.count.store(n + 1, std::memory_order_release);
    return true;
}

inline bool RtGlassMatch(std::uint64_t vs, std::uint64_t ps) {
    return RtGlassMatches(RtGlass(), vs, ps) || RtGlassPickPair(vs, ps);
}

// bbport (r86g_glint-find-bottles): BB_RT_GLASS=auto: a forward draw is a pane when it is alpha blended
// on colour target 0 with depth write on (the r83 header's description of the game's panes) and has
// 1 to BB_GLASS_AUTO_INDICES indices (default 12000: the sky dome's 89676 is out, bottles and window
// panes are a few hundred to a few thousand). The pipeline key knows the state only (RtGlassAutoKey),
// the draw also its index count (RtGlassAutoDraw).
inline constexpr std::uint32_t RtGlassAutoIndicesDefault = 12000;

constexpr bool RtGlassAutoKey(bool blend, bool depth_write) {
    return blend && depth_write;
}

constexpr bool RtGlassAutoDraw(bool blend, bool depth_write, std::uint32_t index_count, std::uint32_t most) {
    return RtGlassAutoKey(blend, depth_write) && index_count != 0 && index_count <= most;
}

/// BB_GLASS_AUTO_INDICES's text: 3 to 1000000 (digits only, at most 8 of them), else the default.
constexpr std::uint32_t RtGlassParseAutoIndices(const char* text) {
    if (!text || text[0] == '\0') {
        return RtGlassAutoIndicesDefault;
    }
    std::uint64_t value = 0;
    for (std::size_t i = 0; text[i] != '\0'; ++i) {
        if (text[i] < '0' || text[i] > '9' || i >= 8) {
            return RtGlassAutoIndicesDefault;
        }
        value = value * 10 + std::uint64_t(text[i] - '0');
    }
    return value >= 3 && value <= 1000000 ? std::uint32_t(value) : RtGlassAutoIndicesDefault;
}

/// BB_RT_GLASS=auto, read once (with the knob).
inline bool RtGlassAuto() {
    return RtGlass().on && RtGlass().automatic;
}

inline std::uint32_t RtGlassAutoIndices() {
    static const std::uint32_t most = RtGlassParseAutoIndices(std::getenv("BB_GLASS_AUTO_INDICES"));
    return most;
}

// bbport (r86h_glint-camera): the shape rule of BB_RT_GLASS=auto on top of the state rule: at least
// BB_GLASS_AUTO_MIN indices (default 60: the 30-index quads and 6-index sprites are flares and
// markers), a pixel shader that reads a texture and does not discard (particles and leaves discard).
// The effects hook also asks for the scene's 3D frame (Rasterizer::scene_started): the draws the
// first auto run took were the HUD, drawn after the display pass.
inline constexpr std::uint32_t RtGlassAutoMinDefault = 60;

/// BB_GLASS_AUTO_MIN's text: 3 to 1000000 (digits only, at most 8 of them), else the default.
constexpr std::uint32_t RtGlassParseAutoMin(const char* text) {
    if (!text || text[0] == '\0') {
        return RtGlassAutoMinDefault;
    }
    std::uint64_t value = 0;
    for (std::size_t i = 0; text[i] != '\0'; ++i) {
        if (text[i] < '0' || text[i] > '9' || i >= 8) {
            return RtGlassAutoMinDefault;
        }
        value = value * 10 + std::uint64_t(text[i] - '0');
    }
    return value >= 3 && value <= 1000000 ? std::uint32_t(value) : RtGlassAutoMinDefault;
}

inline std::uint32_t RtGlassAutoMin() {
    static const std::uint32_t least = RtGlassParseAutoMin(std::getenv("BB_GLASS_AUTO_MIN"));
    return least;
}

constexpr bool RtGlassAutoShape(std::uint32_t index_count, std::uint32_t least, bool textured, bool discards) {
    return index_count >= least && textured && !discards;
}

} // namespace Vulkan
