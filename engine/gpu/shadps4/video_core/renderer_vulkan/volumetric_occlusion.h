// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r51_volumetric-leak): what the volumetric sunlight's march may take from the game's sun
// atlas, and which of its occlusion fixes run. No Vulkan here: tests/test_volumetric_occlusion.cpp
// builds this header alone.
//
// BB_VOLUMETRIC_OCCLUSION, a bit field read once at start (bbport (r84_live-test-knobs): and again
// after a change of the live knobs file, a test tool; default 5 since r76_sun-fog-outdoors:
// bits 1 and 4; 7 all on; 0: as before r51):
//   1 a cascade whose quadrant holds no casters (only the clear value, read as full sun) counts
//     as outside the atlas: the march asks the next cascade, and a sample no cascade with
//     casters holds is dark (cascade 0, 0-2 m, never gets a caster from the game)
//   2 the darkest answer of every cascade holding the sample, not the first one's (a roof or a
//     bridge drawn only into a coarser cascade); a light depth outside [0, 1] asks the next one.
//     Not in the default since r76: in the game it doubled the march's time ("Lighting:
//     volumetric sunlight" 0.199 ms at 5 against 0.430 ms at 7 in a roofed library, 0.212 against
//     0.419 ms at an outdoor street lamp; one run each, ray traced sun on, no gate; RTX 4090,
//     1080p internal) and changed nothing visible where the leak was found. With a ray traced
//     scene the sun gate (BB_VOLUMETRIC_RT_GATE, mask 1, the default) holds every sun caster any
//     cascade drew this frame or r14 holds, whole and in world space (RtShadow::PrepareDraw,
//     PrepareScene): bit 2's case is covered at the gate's cell resolution (160x90x32 cells,
//     filtered between cells) for the casters PrepareDraw keeps; with bit 2 clear a light depth
//     outside [0, 1] is dark (no fog), never lit.
//   4 no fog for a fade rate that is not positive and finite, and the march ends at the shadow
//     distance (past it the fade is 0)
// Bit 1 is the mask (Valid) the rasterizer builds; bits 2 and 4 the shader reads (Pack).

#include <algorithm>
#include <array>
#include <bit> // bbport (r76c_sun-fog-shells)
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <vector>

// bbport (r84_live-test-knobs): test tool, BbLiveKnobs::Knob (by its path from here, so that
// tests/test_volumetric_occlusion.cpp still builds this header with the engine folder alone)
#include "../../../shim/bbport_live_knobs.h"

namespace Vulkan::VolumetricOcclusion {

inline constexpr std::uint32_t SkipEmpty = 1, Darkest = 2, Robust = 4;
inline constexpr std::uint32_t All = SkipEmpty | Darkest | Robust;
/// bbport (r76_sun-fog-outdoors): the value when the knob is not set: bit 2 left out.
inline constexpr std::uint32_t Default = SkipEmpty | Robust;

/// BB_VOLUMETRIC_OCCLUSION's text: a whole number 0..7; unset, empty or anything else gives
/// Default (All before r76).
inline std::uint32_t Parse(const char* text) {
    if (!text || !*text) {
        return Default;
    }
    char* end = nullptr;
    const unsigned long n = std::strtoul(text, &end, 10);
    return *end == '\0' && n <= All ? std::uint32_t(n) : Default;
}

/// The knob, read once; bbport (r84_live-test-knobs): and again after a change of the live knobs
/// file (BB_LIVE_KNOBS_FILE, test tool). Nothing is made with it: the rasterizer's mask and the
/// march's push word take it every frame.
inline std::uint32_t Bits() {
    static BbLiveKnobs::Knob<std::uint32_t> bits{"BB_VOLUMETRIC_OCCLUSION", Parse};
    return bits.Get();
}

/// bbport (r76_sun-fog-outdoors): the gate's mask when BB_VOLUMETRIC_RT_GATE is not set: 1, the
/// sun's casters (rt_shadow.comp's mask). In the game test of 2026-11-15 it cleared the roofed
/// library with the BB PC Remaster mod on and changed nothing at four outdoor places; 2 and 3 (the
/// camera pass's geometry too) also cleared the mod-off veils indoors but removed the sun fog over
/// the whole frame outdoors under a large stone vault (graveyard-blood), so they are test values.
inline constexpr std::uint32_t RtGateDefault = 1;

/// bbport (r76_sun-fog-outdoors): whether BB_VOLUMETRIC_RT_GATE's text names a mask: exactly one
/// character, "0" to "3".
inline bool RtGateNamed(const char* text) {
    return text && text[0] >= '0' && text[0] <= '3' && text[1] == '\0';
}

/// bbport (r51b_volumetric-rt-check): BB_VOLUMETRIC_RT_GATE's text, the instance mask the ray
/// traced sun gate traces: "0" no gate (stage A exactly), "1" the sun's casters (rt_shadow.comp's
/// mask), "2" the camera pass's geometry, "3" both. bbport (r76_sun-fog-outdoors): unset, empty or
/// anything else gives RtGateDefault (0 before r76).
inline std::uint32_t ParseRtGate(const char* text) {
    return RtGateNamed(text) ? std::uint32_t(text[0] - '0') : RtGateDefault;
}

/// The gate's knob, read once; bbport (r84_live-test-knobs): and again after a change of the live
/// knobs file. The rasterizer asks it at every shadow resolve; the gate's passes are made at the
/// first gated march whatever the mask (VolumetricLight::GateReady); Integrate says a change.
inline std::uint32_t RtGateMask() {
    static BbLiveKnobs::Knob<std::uint32_t> mask{"BB_VOLUMETRIC_RT_GATE", ParseRtGate};
    return mask.Get();
}

/// bbport (r76_sun-fog-outdoors): whether the gate's knob is the default (the variable not set,
/// or text that names no mask), for the log lines; read once (bbport (r84_live-test-knobs): and
/// again after a change of the live knobs file).
inline bool RtGateByDefault() {
    static BbLiveKnobs::Knob<bool> by_default{"BB_VOLUMETRIC_RT_GATE",
                                              [](const char* text) { return !RtGateNamed(text); }};
    return by_default.Get();
}

/// bbport (r76_sun-fog-outdoors): the mask the march's gate traces in a frame: the knob's mask
/// when the rasterizer prepared a ray traced scene for it (RtShadow::PrepareScene), else 0: no
/// gate, the march of stage A, as for every player before r76.
constexpr std::uint32_t GateInForce(std::uint32_t mask, bool scene) {
    return scene ? mask : 0u;
}

/// The sun atlas at the game's shadow resolve, bit c for cascade c (Rasterizer::sun_atlas,
/// sun_keep, sun_hold).
struct Quadrants {
    std::uint32_t count = 4;      ///< cascades before the first one with draws left out
    std::uint32_t drawn = 0;      ///< with draws this frame (sun_atlas.drawn_mask)
    bool spread = false;          ///< a draw across quadrants or without a single viewport this
                                  ///< frame (sun_atlas.mask_spread): all four, as r14 counts it
    std::uint32_t held = 0;       ///< r7: kept from a full drawing (sun_hold.confirmed)
    std::uint32_t held_lost = 0;  ///< r7: kept depth lost or owed a clear (sun_hold.stale,
                                  ///< pending_clear): only the clear value, or soon
    bool kept_tracked = false;    ///< r14 keeps quadrants in this atlas frame (sun_keep.tracked)
    std::uint32_t kept_drawn = 0; ///< r14: with draws in it (sun_keep.drawn)
    std::uint32_t kept_cleared = 0; ///< r14: cleared or owed a clear in it (sun_keep.cleared)
    std::uint32_t kept_blank = 0; ///< r14: only the clear value when it began (sun_keep.blank)
};

/// The cascades the march may read: the first `count`, with SkipEmpty only those holding casters
/// (drawn this frame, or depth kept from an earlier drawing). r14's own record covers its atlas
/// frame (a quadrant neither drawn nor cleared in it keeps what it held, blank or not); without
/// it the atlas is cleared whole every frame, but for the quadrants r7 keeps (and has not lost).
/// A draw whose quadrant is not known counts for all four in both (r14's rule).
constexpr std::uint32_t Valid(const Quadrants& q, std::uint32_t bits) {
    const std::uint32_t first = q.count >= 4 ? 0xFu : (1u << q.count) - 1u;
    if ((bits & SkipEmpty) == 0) {
        return first;
    }
    const std::uint32_t data =
        q.kept_tracked ? q.kept_drawn | (~q.kept_cleared & ~q.kept_blank)
                       : q.drawn | (q.spread ? 0xFu : 0u) | (q.held & ~q.held_lost);
    return data & first;
}

/// volumetric_light.comp's push word `cascades`: bits 0-3 the count, 8-11 Valid, 16-23 the knob.
constexpr std::uint32_t Pack(std::uint32_t count, std::uint32_t valid, std::uint32_t bits) {
    return (count < 4 ? count : 4u) | (valid & 0xFu) << 8 | (bits & 0xFFu) << 16;
}

// bbport (r76_sun-fog-outdoors): the gate's diagnostics, BB_VOLUMETRIC_GATE_PROBE=1 and
// BB_VOLUMETRIC_GATE_VIEW=1 (test only, off by default, read once; bbport (r84_live-test-knobs): and
// again after a change of the live knobs file). Off, nothing of them runs and
// the gate traces with its own build. On, the gate's DIAG build (volumetric_rt_gate.comp) traces
// the same rays to their nearest hit.

/// A knob that is on only as exactly "1".
inline bool ParseOn(const char* text) {
    return text && text[0] == '1' && text[1] == '\0';
}

/// BB_VOLUMETRIC_GATE_PROBE=1: the probe line every 600 gated marches; read once.
/// bbport (r84_live-test-knobs): and again after a change of the live knobs file; RtShadow reads
/// it at every records write (GateTable), and a probe that comes on probes after 120 gated marches.
inline bool GateProbe() {
    static BbLiveKnobs::Knob<bool> on{"BB_VOLUMETRIC_GATE_PROBE", ParseOn};
    return on.Get();
}

/// BB_VOLUMETRIC_GATE_VIEW=1: the gate's debug view; read once.
inline bool GateView() {
    // bbport (r84_live-test-knobs): and again after a change of the live knobs file; the view's
    // builds are made with the probe's (DiagReady), its image at its first draw (EnsureGateView)
    static BbLiveKnobs::Knob<bool> on{"BB_VOLUMETRIC_GATE_VIEW", ParseOn};
    return on.Get();
}

/// Bits of the gate's push word `mask` above the instance mask (a ray takes its low 8 bits), read
/// by the DIAG build only: count this march into the probe's words; write each cell's band.
inline constexpr std::uint32_t GateDiagProbe = 0x100, GateDiagBand = 0x200;

/// The distance bands of a shut cell's nearest hit (m): 1 below 5, 2 below 15, 3 below 40, 4 below
/// 150, 5 beyond (the rays end at 800 m). volumetric_rt_gate.comp's DIAG build writes the same
/// edges as literals (GLSL cannot include this header).
inline constexpr std::array<float, 4> GateBandEdges{5.0f, 15.0f, 40.0f, 150.0f};
constexpr std::uint32_t GateBand(float t) {
    std::uint32_t band = 1;
    for (const float edge : GateBandEdges) {
        band += t >= edge ? 1u : 0u;
    }
    return band;
}

/// The probe's words as the DIAG build's block GateProbe lays them out: shut cells by band (5)
/// and of them camera-only (5), both of the cells nearer than the visible surface (the camera's
/// depth at the cell's column, as the march's limit), those cells asked, the direction toward the
/// light in view space (3 floats), the centre column (all 32 slices, two words each: the
/// distance's bits or GateColumnOpen / GateColumnNotAsked, and the instance id), the centre
/// column's surface distance (a float, m: 1e30 sky, -1 none), then the instances' masks, four to a
/// word.
inline constexpr std::uint32_t GateProbeShutAt = 0, GateProbeCameraOnlyAt = 5,
                               GateProbeAskedAt = 10, GateProbeDirectionAt = 11,
                               GateProbeColumnAt = 14, GateProbeSlices = 32,
                               GateProbeSurfaceAt = GateProbeColumnAt + 2 * GateProbeSlices,
                               GateProbeWords = GateProbeSurfaceAt + 1;
inline constexpr std::uint32_t GateColumnOpen = 0xFFFFFFFFu, GateColumnNotAsked = 0xFFFFFFFEu;
/// The most instances whose masks the probe takes (RtShadow's MaxInstances: a static_assert there).
inline constexpr std::uint32_t GateProbeInstancesMost = 8192;
static_assert(GateProbeWords == 79 && GateProbeDirectionAt + 3 == GateProbeColumnAt);
static_assert(GateProbeInstancesMost % 4 == 0);

/// One instance of the ray traced scene, in TLAS record order (RtShadow::GateTable): the entry's
/// key (Entry::base), its triangles and the record's mask.
struct GateInstance {
    std::uint64_t key = 0;
    std::uint32_t triangles = 0;
    std::uint8_t mask = 0;
};

/// The instances' masks as the probe's words hold them: instance i in byte i % 4 of word i / 4.
inline std::vector<std::uint32_t> PackGateMasks(const std::vector<GateInstance>& table) {
    const std::size_t n = std::min<std::size_t>(table.size(), GateProbeInstancesMost);
    std::vector<std::uint32_t> words((n + 3) / 4, 0u);
    for (std::size_t i = 0; i < n; ++i) {
        words[i / 4] |= std::uint32_t(table[i].mask) << (8 * (i % 4));
    }
    return words;
}

/// Camera only, as the DIAG build counts it: the camera pass's bit (2) without the sun's (1).
constexpr bool GateCameraOnly(std::uint32_t mask) {
    return (mask & 2u) != 0 && (mask & 1u) == 0;
}

// bbport (r76c_sun-fog-shells): which instances shut the gate's cells, what the capture knew of
// them, and a test rule that leaves some of them (sky, fog or backdrop shells) out of the gate's
// rays. Test only: BB_VOLUMETRIC_GATE_PROBE=1 (the probe's second line), BB_VOLUMETRIC_GATE_
// PROBE_EVERY, BB_VOLUMETRIC_GATE_PROBE_FILE, BB_VOLUMETRIC_GATE_SHELLS; none set: as r76.

/// The DIAG build's words per instance of the scene, with the probe (volumetric_rt_gate.comp
/// writes them by these offsets as literals, StatWords 10): shut cells in front of the visible
/// surface; of them hit on a front face; nearest and farthest hit (m); lowest and highest hit point
/// above the camera (world y, m); nearest and farthest hit point from the camera (m); cells whose
/// ray straight up hit the instance first; the nearest such hit (m). A minimum is kept as the
/// largest complement of the bits (GateMinFloat, GateMinOrdered read it back), so zeros are empty.
inline constexpr std::uint32_t GateStatCount = 0, GateStatFront = 1, GateStatNear = 2,
                               GateStatFar = 3, GateStatLow = 4, GateStatHigh = 5,
                               GateStatEyeNear = 6, GateStatEyeFar = 7, GateStatUp = 8,
                               GateStatUpNear = 9, GateStatWords = 10;
inline constexpr std::uint32_t GateStatBytes = GateProbeInstancesMost * GateStatWords * 4;
static_assert(GateStatWords == 10 && GateStatUpNear + 1 == GateStatWords);
/// How many instances the probe's second line lists (the most shut cells first).
inline constexpr std::size_t GateTopMost = 8;

/// A float's bits in an order that compares as the floats do (negative ones too; not NaN), as
/// the DIAG build's Ordered(); and back.
constexpr std::uint32_t GateOrdered(float f) {
    const std::uint32_t b = std::bit_cast<std::uint32_t>(f);
    return (b & 0x80000000u) != 0 ? ~b : (b | 0x80000000u);
}
constexpr float GateFromOrdered(std::uint32_t u) {
    return std::bit_cast<float>((u & 0x80000000u) != 0 ? (u & 0x7FFFFFFFu) : ~u);
}
/// A minimum word: a non-negative float kept as the complement of its bits; 0: none (-1).
constexpr float GateMinFloat(std::uint32_t word) {
    return word != 0 ? std::bit_cast<float>(~word) : -1.0f;
}
/// A maximum word of a non-negative float.
constexpr float GateMaxFloat(std::uint32_t word) {
    return std::bit_cast<float>(word);
}
/// A minimum word of an ordered float (heights); 0: none (0).
constexpr float GateMinOrdered(std::uint32_t word) {
    return word != 0 ? GateFromOrdered(~word) : 0.0f;
}

/// The instances with shut cells, the most first (ties: the lower instance first), at most `most`.
inline std::vector<std::uint32_t> GateTopInstances(const std::vector<std::uint32_t>& stats,
                                                   std::size_t most) {
    std::vector<std::uint32_t> order;
    const std::size_t n = stats.size() / GateStatWords;
    for (std::size_t i = 0; i < n; ++i) {
        if (stats[i * GateStatWords + GateStatCount] != 0) {
            order.push_back(std::uint32_t(i));
        }
    }
    const auto more = [&](std::uint32_t a, std::uint32_t b) {
        const std::uint32_t ca = stats[std::size_t(a) * GateStatWords + GateStatCount];
        const std::uint32_t cb = stats[std::size_t(b) * GateStatWords + GateStatCount];
        return ca != cb ? ca > cb : a < b;
    };
    if (order.size() > most) {
        std::partial_sort(order.begin(),
                          order.begin() + std::vector<std::uint32_t>::difference_type(most),
                          order.end(), more);
        order.resize(most);
    } else {
        std::sort(order.begin(), order.end(), more);
    }
    return order;
}

/// What the capture knew of an entry's last draw (Rasterizer::EffectsCaptureDraw, RtShadow::
/// PrepareDraw), kept only while GateCaptureOn: its shaders and pass; depth (bit 0 test, bit 1
/// write, bits 2-4 the compare function as the guest's CompareFunc: 0 never, 1 less, 2 equal,
/// 3 less or equal, 4 greater, 5 not equal, 6 greater or equal, 7 always); raster (bit 0 front
/// faces culled, 1 back faces culled, 2 clockwise is the front, 3 z clip on, 4 the viewport depth
/// clamp on); the depth range its viewport maps to (dmin, dmax: zoffset and zscale where enabled,
/// as the rasterizer sets the Vulkan viewport) and the depth clamp bounds (zmin, zmax); its place
/// among the frame's capture draws that reached an entry; the camera's world position at the
/// entry's last and first camera pass draw (eye_known: one was recorded; a sun pass draw's
/// constants hold the light's camera, so it does not count); whether the entry's ray traced copy
/// is moving (Entry::dynamic, filled when the probe's table is made).
struct GateCapture {
    std::uint64_t vs = 0;
    std::uint64_t ps = 0;
    std::uint32_t order = 0;
    std::uint8_t depth = 0;
    std::uint8_t raster = 0;
    bool camera_pass = false;
    bool known = false;
    float dmin = 0.0f;
    float dmax = 1.0f;
    float zmin = 0.0f;
    float zmax = 1.0f;
    std::array<float, 3> camera{};
    std::array<float, 3> first_camera{};
    bool eye_known = false;
    bool moving = false;
};
inline constexpr std::uint8_t GateDepthTest = 1, GateDepthWrite = 2;
inline constexpr std::uint8_t GateCullFront = 1, GateCullBack = 2, GateClockwise = 4, GateZclip = 8,
                              GateDepthClamp = 16;
constexpr std::uint8_t GateDepthBits(bool test, bool write, std::uint32_t func) {
    return std::uint8_t((test ? GateDepthTest : 0u) | (write ? GateDepthWrite : 0u) | ((func & 7u) << 2));
}
constexpr std::uint32_t GateDepthFunc(std::uint8_t depth) {
    return (depth >> 2) & 7u;
}
constexpr std::uint8_t GateRasterBits(bool cull_front, bool cull_back, bool clockwise, bool zclip,
                                      bool depth_clamp) {
    return std::uint8_t((cull_front ? GateCullFront : 0u) | (cull_back ? GateCullBack : 0u) |
                        (clockwise ? GateClockwise : 0u) | (zclip ? GateZclip : 0u) |
                        (depth_clamp ? GateDepthClamp : 0u));
}
/// "far": every depth the draw writes lies at the far end (0.999 or more): its viewport maps the
/// whole range there, or the viewport depth clamp is on and both its bounds are there.
constexpr bool GateFarDepth(const GateCapture& c) {
    return (c.dmin >= 0.999f && c.dmax >= 0.999f) ||
           ((c.raster & GateDepthClamp) != 0 && c.zmin >= 0.999f && c.zmax >= 0.999f);
}

/// BB_VOLUMETRIC_GATE_SHELLS: the tests, any of which makes an instance a shell (see
/// ParseGateShells). on: the text named at least one test and was understood; bad: text was given
/// and not understood (the rule is off then).
inline constexpr std::uint32_t GateShellPairsMost = 8;
struct GateShellRule {
    bool on = false;
    bool bad = false;
    bool far_depth = false; ///< "far"
    bool no_test = false;   ///< "notest": no depth test, or compare always
    bool no_cull = false;   ///< "nocull": neither face culled
    std::uint32_t pairs = 0;
    std::array<std::uint64_t, GateShellPairsMost> vs{}; ///< "<vs>:<ps>" in hex
    std::array<std::uint64_t, GateShellPairsMost> ps{}; ///< 0: "*", any pixel shader
};

/// The knob's text: tests separated by "," or "+" (the slot workers split env values at commas, so
/// jobs use "+"), no spaces: "far", "notest", "nocull", or a pair of
/// program hashes "<vs hex>:<ps hex>" / "<vs hex>:*" (1 to 16 hex digits, not 0; at most
/// GateShellPairsMost). Not set or empty: off. Anything else (an unknown word, an empty test, a
/// ninth pair): off and bad.
inline GateShellRule ParseGateShells(const char* text) {
    GateShellRule rule;
    if (!text || text[0] == '\0') {
        return rule;
    }
    GateShellRule bad;
    bad.bad = true;
    const auto hex = [](const char* from, const char* to, std::uint64_t& out) {
        if (to <= from || to - from > 16) {
            return false;
        }
        std::uint64_t value = 0;
        for (const char* c = from; c < to; ++c) {
            const int digit = *c >= '0' && *c <= '9'   ? *c - '0'
                              : *c >= 'a' && *c <= 'f' ? *c - 'a' + 10
                              : *c >= 'A' && *c <= 'F' ? *c - 'A' + 10
                                                       : -1;
            if (digit < 0) {
                return false;
            }
            value = value << 4 | std::uint64_t(digit);
        }
        out = value;
        return true;
    };
    const char* at = text;
    while (true) {
        const char* end = at;
        while (*end != '\0' && *end != ',' && *end != '+') {
            ++end;
        }
        const auto is = [&](const char* word) {
            const char* c = at;
            while (*word != '\0' && c < end && *word == *c) {
                ++word;
                ++c;
            }
            return *word == '\0' && c == end;
        };
        if (is("far")) {
            rule.far_depth = true;
        } else if (is("notest")) {
            rule.no_test = true;
        } else if (is("nocull")) {
            rule.no_cull = true;
        } else {
            const char* colon = at;
            while (colon < end && *colon != ':') {
                ++colon;
            }
            std::uint64_t vs = 0, ps = 0;
            const bool any_ps = colon < end && end - colon == 2 && colon[1] == '*';
            if (colon == end || rule.pairs >= GateShellPairsMost || !hex(at, colon, vs) || vs == 0 ||
                !(any_ps || (hex(colon + 1, end, ps) && ps != 0))) {
                return bad;
            }
            rule.vs[rule.pairs] = vs;
            rule.ps[rule.pairs] = any_ps ? 0 : ps;
            ++rule.pairs;
        }
        if (*end == '\0') {
            break;
        }
        at = end + 1;
    }
    rule.on = true;
    return rule;
}

/// The rule, read once.
inline const GateShellRule& GateShells() {
    static const GateShellRule rule = ParseGateShells(std::getenv("BB_VOLUMETRIC_GATE_SHELLS"));
    return rule;
}

/// Whether the rule takes a draw so captured for a shell (never one the capture did not describe).
inline bool GateShell(const GateShellRule& rule, const GateCapture& c) {
    if (!rule.on || !c.known) {
        return false;
    }
    if (rule.far_depth && GateFarDepth(c)) {
        return true;
    }
    if (rule.no_test && ((c.depth & GateDepthTest) == 0 || GateDepthFunc(c.depth) == 7u)) {
        return true;
    }
    if (rule.no_cull && (c.raster & (GateCullFront | GateCullBack)) == 0) {
        return true;
    }
    for (std::uint32_t i = 0; i < rule.pairs && i < GateShellPairsMost; ++i) {
        if (c.vs == rule.vs[i] && (rule.ps[i] == 0 || c.ps == rule.ps[i])) {
            return true;
        }
    }
    return false;
}

/// While the rule is on: the bits a TLAS record also gets, so that the gate can trace without its
/// shells: GateSunSolid with the sun's bit 1, GateCameraSolid with the camera pass's bit 2, none
/// for a shell. No other ray traces these bits, and a record keeps its own, so every other ray
/// sees the same instances (glass is 0x10 alone, r83; cards 8; lamps 4).
inline constexpr std::uint32_t GateSunSolid = 0x20, GateCameraSolid = 0x40;
static_assert(((GateSunSolid | GateCameraSolid) & 0x1Fu) == 0);
constexpr std::uint32_t GateSolidBits(std::uint32_t record_mask, bool shell) {
    return shell ? 0u
                 : ((record_mask & 1u) != 0 ? GateSunSolid : 0u) |
                       ((record_mask & 2u) != 0 ? GateCameraSolid : 0u);
}
/// The instance mask the gate's rays trace for its knob's mask: the knob's own without the rule.
constexpr std::uint32_t GateRayMask(std::uint32_t knob_mask, bool rule_on) {
    return rule_on ? ((knob_mask & 1u) != 0 ? GateSunSolid : 0u) |
                         ((knob_mask & 2u) != 0 ? GateCameraSolid : 0u)
                   : knob_mask;
}

/// Whether draws are described for their entries (the probe's line or the rule needs them).
inline bool GateCaptureOn() {
    static const bool on = GateProbe() || GateShells().on;
    return on;
}

/// BB_VOLUMETRIC_GATE_PROBE_EVERY's text: marches between two probes, 30 to 6000; else 600.
inline std::uint32_t ParseProbeEvery(const char* text) {
    if (!text || text[0] < '0' || text[0] > '9') {
        return 600;
    }
    char* end = nullptr;
    const unsigned long n = std::strtoul(text, &end, 10);
    return *end == '\0' && n >= 30 && n <= 6000 ? std::uint32_t(n) : 600u;
}
inline std::uint32_t GateProbeEvery() {
    static const std::uint32_t every = ParseProbeEvery(std::getenv("BB_VOLUMETRIC_GATE_PROBE_EVERY"));
    return every;
}

/// The inverse of a 4x4 matrix (16 values, either order); false when it has none.
inline bool Invert4(const double m[16], double inv[16]) {
    inv[0] = m[5] * m[10] * m[15] - m[5] * m[11] * m[14] - m[9] * m[6] * m[15] +
             m[9] * m[7] * m[14] + m[13] * m[6] * m[11] - m[13] * m[7] * m[10];
    inv[4] = -m[4] * m[10] * m[15] + m[4] * m[11] * m[14] + m[8] * m[6] * m[15] -
             m[8] * m[7] * m[14] - m[12] * m[6] * m[11] + m[12] * m[7] * m[10];
    inv[8] = m[4] * m[9] * m[15] - m[4] * m[11] * m[13] - m[8] * m[5] * m[15] +
             m[8] * m[7] * m[13] + m[12] * m[5] * m[11] - m[12] * m[7] * m[9];
    inv[12] = -m[4] * m[9] * m[14] + m[4] * m[10] * m[13] + m[8] * m[5] * m[14] -
              m[8] * m[6] * m[13] - m[12] * m[5] * m[10] + m[12] * m[6] * m[9];
    inv[1] = -m[1] * m[10] * m[15] + m[1] * m[11] * m[14] + m[9] * m[2] * m[15] -
             m[9] * m[3] * m[14] - m[13] * m[2] * m[11] + m[13] * m[3] * m[10];
    inv[5] = m[0] * m[10] * m[15] - m[0] * m[11] * m[14] - m[8] * m[2] * m[15] +
             m[8] * m[3] * m[14] + m[12] * m[2] * m[11] - m[12] * m[3] * m[10];
    inv[9] = -m[0] * m[9] * m[15] + m[0] * m[11] * m[13] + m[8] * m[1] * m[15] -
             m[8] * m[3] * m[13] - m[12] * m[1] * m[11] + m[12] * m[3] * m[9];
    inv[13] = m[0] * m[9] * m[14] - m[0] * m[10] * m[13] - m[8] * m[1] * m[14] +
              m[8] * m[2] * m[13] + m[12] * m[1] * m[10] - m[12] * m[2] * m[9];
    inv[2] = m[1] * m[6] * m[15] - m[1] * m[7] * m[14] - m[5] * m[2] * m[15] +
             m[5] * m[3] * m[14] + m[13] * m[2] * m[7] - m[13] * m[3] * m[6];
    inv[6] = -m[0] * m[6] * m[15] + m[0] * m[7] * m[14] + m[4] * m[2] * m[15] -
             m[4] * m[3] * m[14] - m[12] * m[2] * m[7] + m[12] * m[3] * m[6];
    inv[10] = m[0] * m[5] * m[15] - m[0] * m[7] * m[13] - m[4] * m[1] * m[15] +
              m[4] * m[3] * m[13] + m[12] * m[1] * m[7] - m[12] * m[3] * m[5];
    inv[14] = -m[0] * m[5] * m[14] + m[0] * m[6] * m[13] + m[4] * m[1] * m[14] -
              m[4] * m[2] * m[13] - m[12] * m[1] * m[6] + m[12] * m[2] * m[5];
    inv[3] = -m[1] * m[6] * m[11] + m[1] * m[7] * m[10] + m[5] * m[2] * m[11] -
             m[5] * m[3] * m[10] - m[9] * m[2] * m[7] + m[9] * m[3] * m[6];
    inv[7] = m[0] * m[6] * m[11] - m[0] * m[7] * m[10] - m[4] * m[2] * m[11] +
             m[4] * m[3] * m[10] + m[8] * m[2] * m[7] - m[8] * m[3] * m[6];
    inv[11] = -m[0] * m[5] * m[11] + m[0] * m[7] * m[9] + m[4] * m[1] * m[11] -
              m[4] * m[3] * m[9] - m[8] * m[1] * m[7] + m[8] * m[3] * m[5];
    inv[15] = m[0] * m[5] * m[10] - m[0] * m[6] * m[9] - m[4] * m[1] * m[10] +
              m[4] * m[2] * m[9] + m[8] * m[1] * m[6] - m[8] * m[2] * m[5];
    const double det = m[0] * inv[0] + m[1] * inv[4] + m[2] * inv[8] + m[3] * inv[12];
    if (det == 0.0 || !std::isfinite(det)) {
        return false;
    }
    for (int i = 0; i < 16; ++i) {
        inv[i] /= det;
    }
    return true;
}

/// The direction toward the sun (the moon at night) that the gate's rays and the march take, made
/// on the host from the same 32 shadow constants (dword i at the constants' base + 4 i) as
/// volumetric_rt_gate.comp's prepare(), in double precision: rows 0-15 the camera's inverse
/// projection P^-1, rows 16-31 cascade 0's light matrix L; with M = L P, the cross product of M's
/// first two rows (xyz), negated when it points along M's third row. View space. False where the
/// shader's would be invalid (P^-1 not invertible, not finite, squared length below 1e-16).
inline bool LightDirection(const std::array<float, 32>& c, std::array<float, 3>& out) {
    double inverse_projection[16], projection[16], m[3][3];
    for (int i = 0; i < 16; ++i) {
        inverse_projection[i] = c[i];
    }
    if (!Invert4(inverse_projection, projection)) {
        return false;
    }
    for (int r = 0; r < 3; ++r) {
        for (int k = 0; k < 3; ++k) {
            double sum = 0.0;
            for (int j = 0; j < 4; ++j) {
                sum += double(c[16 + 4 * r + j]) * projection[4 * j + k];
            }
            m[r][k] = sum;
        }
    }
    double d[3] = {m[0][1] * m[1][2] - m[0][2] * m[1][1], m[0][2] * m[1][0] - m[0][0] * m[1][2],
                   m[0][0] * m[1][1] - m[0][1] * m[1][0]};
    const double length2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2];
    if (!std::isfinite(length2) || length2 < 1e-16) {
        return false;
    }
    const double scale = (m[2][0] * d[0] + m[2][1] * d[1] + m[2][2] * d[2] > 0.0 ? -1.0 : 1.0) /
                         std::sqrt(length2);
    for (int i = 0; i < 3; ++i) {
        out[i] = float(d[i] * scale);
    }
    return true;
}

/// A view space direction in world space: the 3x3 part of the camera's view-to-world rows (3x4,
/// CameraMotion::Matrices::inv_view), normalised; zero when that gives no direction.
inline std::array<float, 3> ToWorld(const std::array<float, 12>& view_to_world,
                                    const std::array<float, 3>& v) {
    double w[3];
    for (int i = 0; i < 3; ++i) {
        w[i] = double(view_to_world[4 * i]) * v[0] + double(view_to_world[4 * i + 1]) * v[1] +
               double(view_to_world[4 * i + 2]) * v[2];
    }
    const double length = std::sqrt(w[0] * w[0] + w[1] * w[1] + w[2] * w[2]);
    if (!std::isfinite(length) || length < 1e-8) {
        return {};
    }
    return {float(w[0] / length), float(w[1] / length), float(w[2] / length)};
}

/// Elevation (degrees above the horizon, world y taken as up) and azimuth (degrees from world +z
/// toward +x, 0 to 360) of a world direction.
inline std::array<float, 2> ElevationAzimuth(const std::array<float, 3>& w) {
    constexpr double Degrees = 57.29577951308232;
    const double elevation = std::asin(std::clamp(double(w[1]), -1.0, 1.0)) * Degrees;
    double azimuth = std::atan2(double(w[0]), double(w[2])) * Degrees;
    if (azimuth < 0.0) {
        azimuth += 360.0;
    }
    return {float(elevation), float(azimuth)};
}

/// The angle between two directions (degrees); 180 when either is zero.
inline float AngleDeg(const std::array<float, 3>& a, const std::array<float, 3>& b) {
    const double la = std::sqrt(double(a[0]) * a[0] + double(a[1]) * a[1] + double(a[2]) * a[2]);
    const double lb = std::sqrt(double(b[0]) * b[0] + double(b[1]) * b[1] + double(b[2]) * b[2]);
    if (!(la > 0.0) || !(lb > 0.0)) {
        return 180.0f;
    }
    const double cosine = (double(a[0]) * b[0] + double(a[1]) * b[1] + double(a[2]) * b[2]) / (la * lb);
    return float(std::acos(std::clamp(cosine, -1.0, 1.0)) * 57.29577951308232);
}

/// The light as the host knows it at the shadow resolve (the rasterizer's SetSunLight): the
/// direction toward it in view and world space, and the camera's view-to-world rows of the frame.
struct SunLight {
    std::array<float, 3> view{};
    std::array<float, 3> world{};
    std::array<float, 12> view_to_world{};
    bool camera = false; ///< view_to_world is this frame's camera (CameraMotion's pass matrices)
    bool valid = false;  ///< view and world are known
};

inline SunLight MakeSunLight(const std::array<float, 32>& constants,
                             const std::array<float, 12>& view_to_world, bool camera) {
    SunLight light;
    light.view_to_world = view_to_world;
    light.camera = camera;
    if (LightDirection(constants, light.view) && camera) {
        light.world = ToWorld(view_to_world, light.view);
        light.valid = light.world != std::array<float, 3>{};
    }
    return light;
}

} // namespace Vulkan::VolumetricOcclusion
