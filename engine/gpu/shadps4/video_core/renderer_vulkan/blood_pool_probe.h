// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r100c_blood-pool-probe, r100d_blood-pool-draws): TOOL (branch dev/test-tools; never a
// feature branch or a pull request). Which draws put what is on screen inside a box of the scene, for finding how the game
// draws the blood pool at the graveyard (r100 marked the draw 1ea84d9a:bd1d09f0, which the r100b run
// showed to be a small object at the hunter's hip, not the pool).
//
// Knob BB_BLOOD_POOL_PROBE (read at start, and again through the live knobs file, BB_LIVE_KNOBS_FILE,
// when that file changes):
//   unset, empty, "0" or "off" at start: off. No BloodPoolProbe is made: its hooks are null pointer
//                 tests and nothing of it runs.
//   "on" or "1":  made, idle until a box comes (a job's set:BB_BLOOD_POOL_PROBE=x0:y0:x1:y1).
//   "x0:y0:x1:y1" a box in scene pixels, both corners inside (x0 <= x1, y0 <= y1, decimal); a side over
//                 MaxSide pixels is cut to MaxSide (said in the log). Each new box arms the probe: it
//                 waits for ArmFramesStart frames in a row with a G-buffer pass when the box came at
//                 start (the level loads first), ArmFramesLive when it came through the live file,
//                 then probes CaptureFrames frames, then logs when the GPU is past them.
//   other text:   no box (said once); the probe stays as it is.
// While probing, every draw whose targets have the scene's size (the G-buffer pass's depth), outside
// a lamps-apart batch, gets a print of each of its targets (colour 0-7, depth) in the box and at
// every Stride-th pixel of the frame each way right before it, and a compare right after it.
// r100d: after the pair lines, the draws of the pair that owns the most box albedo, one line each
// for every draw owning at least 1/DrawLineShare of the box (index count, first index and index
// buffer, the first textures bound, its own, box and frame counts), and a self-check line.
// No Vulkan here: the static_asserts below are the parse's tests (they run at every compile).

#include <cstdint>

#include "../host_shaders/blood_pool_probe_layout.h"

namespace Vulkan::BloodPoolProbeRules {

inline constexpr std::uint32_t Group = BLOOD_POOL_PROBE_GROUP;
inline constexpr std::uint32_t Targets = BLOOD_POOL_PROBE_TARGETS;
inline constexpr std::uint32_t DepthTarget = BLOOD_POOL_PROBE_DEPTH;
inline constexpr std::uint32_t RecordWords = BLOOD_POOL_PROBE_RECORD_WORDS;
inline constexpr std::uint32_t WordBox = BLOOD_POOL_PROBE_WORD_BOX;
inline constexpr std::uint32_t WordFrame = BLOOD_POOL_PROBE_WORD_FRAME;
inline constexpr std::uint32_t WordTarget0 = BLOOD_POOL_PROBE_WORD_TARGET0;
inline constexpr std::uint32_t WordSeenBox = BLOOD_POOL_PROBE_WORD_SEEN_BOX;
inline constexpr std::uint32_t WordSeenFrame = BLOOD_POOL_PROBE_WORD_SEEN_FRAME;
inline constexpr std::uint32_t OwnerMaps = BLOOD_POOL_PROBE_OWNER_MAPS;
inline constexpr std::uint32_t NoTarget = BLOOD_POOL_PROBE_NO_TARGET;
inline constexpr std::uint32_t OwnDepth = BLOOD_POOL_PROBE_OWN_DEPTH;
static_assert(Group == 8u && Targets == 9u && DepthTarget == Targets - 1u);
static_assert(WordBox == 0u && WordFrame == 1u && WordTarget0 == 2u && WordSeenBox == WordTarget0 + Targets &&
              WordSeenFrame == WordSeenBox + 1u && RecordWords == WordSeenFrame + 1u);
static_assert(OwnerMaps == 3u && NoTarget == 255u && OwnDepth == 65536u);
static_assert(BLOOD_POOL_PROBE_PRINTS_BINDING == Targets && BLOOD_POOL_PROBE_COUNTS_BINDING == Targets + 1u &&
              BLOOD_POOL_PROBE_OWNERS_BINDING == Targets + 2u);

/// A box side is at most this many pixels (the owner maps and the box prints are sized by it).
inline constexpr std::uint32_t MaxSide = 256;
/// Frames in a row with a G-buffer pass before probing: a box given at start (the level loads
/// first), one given through the live knobs file (the camera has stopped).
inline constexpr std::uint32_t ArmFramesStart = 600, ArmFramesLive = 30;
/// Frames probed after that, and draws a frame looked at (the rest are counted "over the cap").
inline constexpr std::uint32_t CaptureFrames = 2, MaxDraws = 4096;
/// The frame is sampled at every Stride-th pixel each way (its counts are times Stride squared).
inline constexpr std::uint32_t Stride = 4;
/// Frame ends to wait for the GPU after the last probed frame before logging what is there.
inline constexpr std::uint32_t WaitFrames = 240;
/// Pair lines at most (sorted by box pixels owned, then by box pixels changed); the rest are summed
/// in one line. Draw lines (r100d) at most, for draws owning at least 1/DrawLineShare of the box's
/// albedo. 8 + 8 keep a box's lines inside the slot runner's 30 evidence lines of a job.
inline constexpr std::uint32_t MaxLines = 8, MaxDrawLines = 8, DrawLineShare = 100;
/// Textures a draw line names (address:WxH:format), of those bound after the draw's own targets.
inline constexpr std::uint32_t DrawTextures = 3;
/// Owner values: (capture frame + 1) << OwnerFrameShift | draw number in that frame.
inline constexpr std::uint32_t OwnerFrameShift = 16;
static_assert(MaxDraws <= (1u << OwnerFrameShift) && CaptureFrames < 255u);
static_assert(MaxSide * MaxSide * Targets < (1u << 24), "the box prints stay small");

/// BloodPoolProbeRules::Push, word for word with blood_pool_probe.comp's push block.
struct Push {
    std::int32_t box[4];  ///< x0, y0, width, height
    std::int32_t grid[4]; ///< frame sample columns, rows, stride, 0
    std::uint32_t mask = 0;
    std::uint32_t record = 0;
    std::uint32_t owner = 0;
    std::uint32_t owner_targets = 0;
};
static_assert(sizeof(Push) == 48);

enum class Kind : std::uint8_t { Off, On, Box, Bad };
struct Knob {
    Kind kind = Kind::Off;
    std::uint32_t x0 = 0, y0 = 0, x1 = 0, y1 = 0; ///< both corners inside the box
    bool cut = false;                              ///< a side was cut to MaxSide
    [[nodiscard]] constexpr std::uint32_t Width() const { return x1 - x0 + 1; }
    [[nodiscard]] constexpr std::uint32_t Height() const { return y1 - y0 + 1; }
    [[nodiscard]] constexpr bool SameBox(const Knob& o) const {
        return kind == Kind::Box && o.kind == Kind::Box && x0 == o.x0 && y0 == o.y0 && x1 == o.x1 &&
               y1 == o.y1;
    }
};

/// The knob's text (nullptr: not set). Spaces and tabs around it are left out.
constexpr Knob Parse(const char* text) {
    Knob k{};
    if (!text) {
        return k;
    }
    while (*text == ' ' || *text == '\t') {
        ++text;
    }
    const char* end = text;
    while (*end) {
        ++end;
    }
    while (end > text && (end[-1] == ' ' || end[-1] == '\t')) {
        --end;
    }
    if (end == text || (end - text == 1 && *text == '0') ||
        (end - text == 3 && text[0] == 'o' && text[1] == 'f' && text[2] == 'f')) {
        return k; // off
    }
    if ((end - text == 1 && *text == '1') || (end - text == 2 && text[0] == 'o' && text[1] == 'n')) {
        k.kind = Kind::On;
        return k;
    }
    std::uint32_t v[4]{};
    int n = 0;
    const char* c = text;
    while (n < 4) {
        if (c == end || *c < '0' || *c > '9') {
            k.kind = Kind::Bad;
            return k;
        }
        std::uint32_t x = 0;
        while (c != end && *c >= '0' && *c <= '9') {
            x = x * 10u + std::uint32_t(*c - '0');
            if (x > 16383u) {
                k.kind = Kind::Bad;
                return k;
            }
            ++c;
        }
        v[n++] = x;
        if (n < 4) {
            if (c == end || *c != ':') {
                k.kind = Kind::Bad;
                return k;
            }
            ++c;
        }
    }
    if (c != end || v[2] < v[0] || v[3] < v[1]) {
        k.kind = Kind::Bad;
        return k;
    }
    k.kind = Kind::Box;
    k.x0 = v[0];
    k.y0 = v[1];
    k.x1 = v[2];
    k.y1 = v[3];
    if (k.Width() > MaxSide) {
        k.x1 = k.x0 + MaxSide - 1;
        k.cut = true;
    }
    if (k.Height() > MaxSide) {
        k.y1 = k.y0 + MaxSide - 1;
        k.cut = true;
    }
    return k;
}

static_assert(Parse(nullptr).kind == Kind::Off && Parse("").kind == Kind::Off && Parse(" 0 ").kind == Kind::Off &&
              Parse("off").kind == Kind::Off);
static_assert(Parse("on").kind == Kind::On && Parse("1").kind == Kind::On);
static_assert(Parse("1150:620:1329:799").kind == Kind::Box && Parse("1150:620:1329:799").Width() == 180 &&
              Parse("1150:620:1329:799").Height() == 180 && !Parse("1150:620:1329:799").cut);
static_assert(Parse("895:661:930:706").x1 == 930 && Parse("5:5:5:5").Width() == 1);
static_assert(Parse("0:0:1919:1079").cut && Parse("0:0:1919:1079").Width() == MaxSide &&
              Parse("0:0:1919:1079").Height() == MaxSide);
static_assert(Parse("10:10:5:20").kind == Kind::Bad && Parse("1:2:3").kind == Kind::Bad &&
              Parse("1:2:3:4:5").kind == Kind::Bad && Parse("a:b:c:d").kind == Kind::Bad &&
              Parse("1,2,3,4").kind == Kind::Bad && Parse("99999:0:99999:1").kind == Kind::Bad &&
              Parse("on please").kind == Kind::Bad);
static_assert(Parse("1:2:3:4").SameBox(Parse(" 1:2:3:4 ")) && !Parse("1:2:3:4").SameBox(Parse("1:2:3:5")));

/// Phases of a draw in its frame, one bit each (the log prints the letters PGBLA).
enum Phase : std::uint8_t {
    BeforeGbuffer = 1, ///< P: before the frame's first G-buffer pass
    Gbuffer = 2,       ///< G: a G-buffer pass's draw (5 or more colour targets and a depth)
    BeforeLight = 4,   ///< B: after a G-buffer pass, before its first light draw
    Light = 8,         ///< L: a light draw (shadow resolve, sun or moon, a lamp of the grid)
    AfterLight = 16,   ///< A: after the light draws began
};

/// The owner value of draw `ordinal` of capture frame `frame`; 0 is "no owner".
constexpr std::uint32_t OwnerValue(std::uint32_t frame, std::uint32_t ordinal) {
    return ((frame + 1u) << OwnerFrameShift) | ordinal;
}
static_assert(OwnerValue(0, 0) != 0 && (OwnerValue(1, 7) >> OwnerFrameShift) == 2u &&
              (OwnerValue(1, 4095) & 0xffffu) == 4095u);

} // namespace Vulkan::BloodPoolProbeRules
