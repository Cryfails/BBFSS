# r76c_sun-fog-shells: FEATURE patch (part of the sun fog gate r51b + r76; on top of r76, after
# r76b was reverted). Test knobs only: with none of them set the picture, every shader build the
# game runs without the probe, and every ray traced record are as with r76.
#
# Why: game runs of 2026-11-15 17:45-18:00. Gate 2/3 (the camera pass's geometry in the gate's
# rays) shut the cells over the whole frame at the outdoor places too: graveyard-blood (night) in
# the 15-40 m band, nearly all on camera-pass-only instances (the centre column on one instance of
# 7182 triangles at 27.1 m), lamp-test-spot (open sky in view) all in the 150-800 m band. r76b (a
# cell shut only when a ray straight up within 150 m is blocked too) changed nothing anywhere. The
# lead's reading, to be tested: the camera pass holds sky, fog or backdrop SHELLS (geometry around
# the play area drawn as solid), so no ray can tell outdoors from indoors until they are left out.
# Read for this patch: the up vector r76b used (row 1 of the view-to-world rows) IS world +y in
# the gate's view space (for a rigid camera the transpose of the rotation is its inverse, and row 1
# is what ToWorld turns into world y; the logged light directions agree across places), and r76b's
# test sat in code both gate builds run; so its null result says that every shut cell had
# something within 150 m straight above it, which a shell around the camera (or a vault) gives.
#
# What:
# 1. BB_VOLUMETRIC_GATE_PROBE=1 also logs a second line, "gate instances" (VolumetricLight::
#    ReadGateInstances): the 8 instances that shut the most cells in front of the visible surface,
#    plus the one most rays straight up hit first when it is not among them. Per instance from the
#    DIAG build (GPU, per instance words GateStat*): cells shut, share hit on a front face, nearest
#    and farthest hit (m), nearest and farthest hit point from the camera (m), lowest and highest
#    hit point above the camera (world y, m), cells whose ray straight up (world +y, from the
#    instance's world-to-object rows) hit it first and the nearest such hit; from the capture of its
#    last draw (host, RtShadow::GateCaptures): pass, vertex and pixel shader hashes, depth test,
#    write and compare function, culled faces and z clip, the depth range its viewport maps to and
#    the depth clamp bounds, its place among the frame's capture draws, how far the camera was at
#    its first recorded draw; and whether the shell rule (3) takes it. Header: camera position and
#    pitch, light elevation, the band counts, the ray mask, how many instances shut cells. About
#    330 characters plus about 230 per instance: about 2,400 at most (9 instances).
# 2. BB_VOLUMETRIC_GATE_PROBE_EVERY=<marches> (30 to 6000; else 600 as r76): marches between two
#    probes after the first (the 120th gated march, as r76). BB_VOLUMETRIC_GATE_PROBE_FILE=<path>:
#    the instance line also goes to that file (written anew at the run's first probe, appended
#    after), because the slot runner keeps only 300 characters of a log line.
# 3. BB_VOLUMETRIC_GATE_SHELLS=<tests> (separated by "," or "+"; not set: off): instances whose last
#    draw matches any test are left out of the gate's rays: "far" (the viewport maps every depth to
#    0.999 or more, or the viewport clamp is on and both its bounds are 0.999 or more), "notest" (no depth test, or
#    compare Always), "nocull" (neither face culled), "<vs hex>:<ps hex>" or "<vs hex>:*" (program
#    hashes as the probe prints them; at most 8). How: while set, every TLAS record with the sun's
#    bit 1 also gets 0x20 and with the camera pass's bit 2 also 0x40, except a shell
#    (VolumetricOcclusion::GateSolidBits); the gate traces 0x20 / 0x40 for its knob's 1 / 2
#    (GateRayMask). No other ray traces those bits and every record keeps its own bits, so the sun
#    (1), lamps (4, 8), bounced light (0xff) and glass (0x10, r83) see exactly the instances they
#    saw. Text not understood: off, said once. A line every 600 scenes: shells in the last scene.
#
# Cost: knobs unset: one test of a static bool per capture draw (rasterizer and PrepareDraw) and
# per TLAS record; no shader change outside the DIAG build. Probe on: per probe march 2 x 320 KB
# buffers (zero fill and copy back of the used part), up to 8 atomics per shut cell on per-instance
# words (heavy contention on one instance: about a millisecond on that frame, a guess, not
# measured) and one more ray (straight up) per shut cell in front of the surface. Shell rule on:
# records gain bits (a TLAS rebuild only when a record's bits change, as for any mask change).
#
# Files and anchors (exact texts below; each must match once): volumetric_rt_gate.comp (3 anchors
# under #ifdef DIAG + the probe block), volumetric_occlusion.h (include list, after
# GateCameraOnly), vk_rt_shadow.h (after GateTable(), Entry's base/instance pair, after
# gate_table), vk_rt_shadow.cpp (entry.stream line in PrepareDraw, gate_table.clear block, the
# record memcpy/out/gate_table block in PrepareScene), vk_rasterizer_effects.cpp (after the
# r19_palette block in EffectsCaptureDraw, after SetSunSceneTable), vk_volumetric_light.h (after
# SetSunSceneTable, after ReadGateProbe(), after probe_table), vk_volumetric_light.cpp (RecordGate
# params, probe_info, capture list, fillBuffer, writes array size, binding 7 write, push count,
# copyBuffer; DiagReady pass types + room, probe buffers; Integrate probe block, scene reset; end of
# ReadGateProbe), engine/tests/test_volumetric_occlusion.cpp (after the PackGateMasks block),
# README.md (after the BB_VOLUMETRIC_GATE_VIEW row).
#
# Review fixes (r76c_sun-fog-shells.fixed.py, 2026-11-15 18:4x; the draft is kept unchanged):
# (a) the slot workers (Test-BBFSSSlot.ps1 and .live.ps1) split every env value at commas, so a
#     job's BB_VOLUMETRIC_GATE_SHELLS=far,notest reached the game as "far": tests are now separated
#     by "," or "+" (jobs use "far+notest"); (b) "far" takes the depth clamp bounds only while the
#     viewport clamp is on (DB_RENDER_OVERRIDE.DISABLE_VIEWPORT_CLAMP clear, as the pipeline key's
#     depth_clamp_enable); (c) cam0 is measured from camera pass draws only (a sun pass draw's
#     constants hold the light's camera, not the player's), and the line says whether the entry's
#     ray traced copy is moving (Entry::dynamic, "dyn"): the only capture-time sign of a shell that
#     follows the camera when the camera itself moves.
# Use: R76C_ROOT=<tree> python -I -X utf8 r76c_sun-fog-shells.fixed.py check | apply | revert
# (root: R76C_ROOT, else the current directory). Line ends kept (CRLF in the tree); originals are
# copied into r76c_backup next to this script at apply.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r76c_backup")
ROOT = os.environ.get("R76C_ROOT") or os.getcwd()
VC = "engine/gpu/shadps4/video_core/"
H = VC + "host_shaders/"
R = VC + "renderer_vulkan/"

EDITS = {
    # ------------------------------------------------------------------------------------------
    H + "volumetric_rt_gate.comp": [
        (r'''layout(binding = 7) uniform sampler2D depth_tex;
#endif
''', r'''layout(binding = 7) uniform sampler2D depth_tex;
// bbport (r76c_sun-fog-shells): with the probe, ten words per instance of the scene (GateStat* in
// volumetric_occlusion.h, GateStatWords): shut cells in front of the surface, of them hit on a
// front face, the nearest and farthest hit (m), the lowest and highest hit point above the camera
// (world y, m), the nearest and farthest hit point from the camera (m), the cells whose ray
// straight up hit this instance first, and the nearest such hit (m). A minimum is kept as the
// largest complement, so a buffer of zeros starts every word empty.
layout(scalar, binding = 8) buffer GateProbeStats { uint s[]; } stats;
const uint StatWords = 10u;
// A float's bits in an order that compares as the floats do (VolumetricOcclusion::GateOrdered)
uint Ordered(float f) {
    uint b = floatBitsToUint(f);
    return (b & 0x80000000u) != 0u ? ~b : (b | 0x80000000u);
}
#endif
'''),
        (r'''    float surface = -1.0;
    bool front = false;
#endif
''', r'''    float surface = -1.0;
    bool front = false;
    // bbport (r76c_sun-fog-shells): the probe's hit point (height above the camera in world y,
    // distance from it), the face hit, and the nearest hit of the ray straight up from the cell
    float hit_height = 0.0;
    float hit_eye = 0.0;
    bool hit_front = false;
    uint up_instance = 0xFFFFFFFFu;
    float up_t = 0.0;
#endif
'''),
        (r'''                band = 1u + uint(hit_t >= 5.0) + uint(hit_t >= 15.0) + uint(hit_t >= 40.0) +
                       uint(hit_t >= 150.0);
            }
#endif
''', r'''                band = 1u + uint(hit_t >= 5.0) + uint(hit_t >= 15.0) + uint(hit_t >= 40.0) +
                       uint(hit_t >= 150.0);
                // bbport (r76c_sun-fog-shells): with the probe, for a cell in front of the surface:
                // the instance's world-to-object rows (its object space is the world: the scene's
                // records place world space meshes with the camera's view), whose row y read across
                // the columns is world +y in this view space; the hit point's height above the
                // camera and distance from it, the face, and one ray straight up (same mask)
                if ((mask & DiagProbe) != 0u && front) {
                    mat4x3 to_world = rayQueryGetIntersectionWorldToObjectEXT(query, true);
                    vec3 up = vec3(to_world[0][1], to_world[1][1], to_world[2][1]);
                    vec3 hit = p + shared_direction * hit_t;
                    hit_height = dot(up, hit);
                    hit_eye = length(hit);
                    hit_front = rayQueryGetIntersectionFrontFaceEXT(query, true);
                    if (dot(up, up) > 0.25) {
                        rayQueryEXT above;
                        rayQueryInitializeEXT(above, scene, gl_RayFlagsOpaqueEXT, mask & 255u, p, 0.02,
                                              normalize(up), max_distance);
                        rayQueryProceedEXT(above);
                        if (rayQueryGetIntersectionTypeEXT(above, true) !=
                            gl_RayQueryCommittedIntersectionNoneEXT) {
                            up_t = rayQueryGetIntersectionTEXT(above, true);
                            up_instance = uint(rayQueryGetIntersectionInstanceIdEXT(above, true));
                        }
                    }
                }
            }
#endif
'''),
        (r'''            if ((m & 2u) != 0u && (m & 1u) == 0u) atomicAdd(shared_probe[4u + band], 1u);
        }
''', r'''            if ((m & 2u) != 0u && (m & 1u) == 0u) atomicAdd(shared_probe[4u + band], 1u);
            // bbport (r76c_sun-fog-shells): the hit instance's words, and the up ray's instance's
            uint at_stat = hit_instance * StatWords;
            if (at_stat + StatWords <= uint(stats.s.length())) {
                atomicAdd(stats.s[at_stat], 1u);
                if (hit_front) atomicAdd(stats.s[at_stat + 1u], 1u);
                atomicMax(stats.s[at_stat + 2u], ~floatBitsToUint(hit_t));
                atomicMax(stats.s[at_stat + 3u], floatBitsToUint(hit_t));
                atomicMax(stats.s[at_stat + 4u], ~Ordered(hit_height));
                atomicMax(stats.s[at_stat + 5u], Ordered(hit_height));
                atomicMax(stats.s[at_stat + 6u], ~floatBitsToUint(hit_eye));
                atomicMax(stats.s[at_stat + 7u], floatBitsToUint(hit_eye));
            }
            if (up_instance != 0xFFFFFFFFu) {
                uint up_stat = up_instance * StatWords;
                if (up_stat + StatWords <= uint(stats.s.length())) {
                    atomicAdd(stats.s[up_stat + 8u], 1u);
                    atomicMax(stats.s[up_stat + 9u], ~floatBitsToUint(up_t));
                }
            }
        }
'''),
    ],
    # ------------------------------------------------------------------------------------------
    R + "volumetric_occlusion.h": [
        (r'''#include <array>
#include <cmath>
''', r'''#include <array>
#include <bit> // bbport (r76c_sun-fog-shells)
#include <cmath>
'''),
        (r'''/// Camera only, as the DIAG build counts it: the camera pass's bit (2) without the sun's (1).
constexpr bool GateCameraOnly(std::uint32_t mask) {
    return (mask & 2u) != 0 && (mask & 1u) == 0;
}
''', r'''/// Camera only, as the DIAG build counts it: the camera pass's bit (2) without the sun's (1).
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
'''),
    ],
    # ------------------------------------------------------------------------------------------
    R + "vk_rt_shadow.h": [
        (r'''    [[nodiscard]] const std::vector<VolumetricOcclusion::GateInstance>& GateTable() const noexcept {
        return gate_table;
    }
''', r'''    [[nodiscard]] const std::vector<VolumetricOcclusion::GateInstance>& GateTable() const noexcept {
        return gate_table;
    }
    // bbport (r76c_sun-fog-shells): with VolumetricOcclusion::GateCaptureOn (the gate probe or the
    // shell rule) the rasterizer describes each capture draw just before PrepareDraw, which keeps it
    // on the entry the draw reached (Entry::gate_cap). GateCaptures: those of GateTable's
    // instances, in the same order (filled only with BB_VOLUMETRIC_GATE_PROBE=1).
    void SetGateCapture(const VolumetricOcclusion::GateCapture& capture) noexcept {
        gate_next = capture;
    }
    [[nodiscard]] const std::vector<VolumetricOcclusion::GateCapture>& GateCaptures() const noexcept {
        return gate_caps;
    }
'''),
        (r'''        u64 base = 0;
        bool instance = false;
''', r'''        u64 base = 0;
        bool instance = false;
        // bbport (r76c_sun-fog-shells): its last draw as the capture described it (GateCaptureOn)
        VolumetricOcclusion::GateCapture gate_cap{};
'''),
        (r'''    std::vector<VolumetricOcclusion::GateInstance> gate_table;
''', r'''    std::vector<VolumetricOcclusion::GateInstance> gate_table;
    // bbport (r76c_sun-fog-shells): GateCaptures; the next draw's description (SetGateCapture); the
    // capture draws of the frame so far that reached an entry; the shell rule (read once) and its
    // counts for the line every 600 scenes
    const bool gate_cap_on = VolumetricOcclusion::GateCaptureOn();
    const VolumetricOcclusion::GateShellRule gate_shell_rule = VolumetricOcclusion::GateShells();
    std::vector<VolumetricOcclusion::GateCapture> gate_caps;
    VolumetricOcclusion::GateCapture gate_next{};
    u64 gate_order_frame = 0;
    u32 gate_order = 0;
    u64 gate_shell_scenes = 0;
    u32 gate_shells_now = 0, gate_shells_sun = 0, gate_shell_records = 0;
    bool gate_shell_bad_said = false;
'''),
    ],
    # ------------------------------------------------------------------------------------------
    R + "vk_rt_shadow.cpp": [
        (r'''    entry.stream = draw.positions; // bbport (r46b_plant-rule): the same at every draw of the key
''', r'''    entry.stream = draw.positions; // bbport (r46b_plant-rule): the same at every draw of the key
    // bbport (r76c_sun-fog-shells): with the gate probe or the shell rule on (GateCaptureOn), this
    // draw as the rasterizer described it just before (SetGateCapture), its place among the frame's
    // capture draws that reached an entry, and, from camera pass draws only (a sun pass draw's
    // constants hold the light's camera), the camera's world position (the draw's view-to-world
    // rows at word 180, as ToWorld reads them) now and at the entry's first camera pass draw
    if (gate_cap_on) {
        if (gate_order_frame != frame) {
            gate_order_frame = frame;
            gate_order = 0;
        }
        const bool eye_known = entry.gate_cap.known && entry.gate_cap.eye_known;
        const std::array<float, 3> last_eye = entry.gate_cap.camera;
        const std::array<float, 3> first_eye = entry.gate_cap.first_camera;
        entry.gate_cap = gate_next;
        entry.gate_cap.order = gate_order++;
        entry.gate_cap.eye_known = eye_known;
        entry.gate_cap.camera = last_eye;
        entry.gate_cap.first_camera = first_eye;
        if (draw.camera_pass) {
            const std::array<float, 3> eye{draw.constants[183], draw.constants[187],
                                           draw.constants[191]};
            entry.gate_cap.camera = eye;
            entry.gate_cap.first_camera = eye_known ? first_eye : eye;
            entry.gate_cap.eye_known = true;
        }
    }
'''),
        (r'''    if (gate_table_on) { // bbport (r76_sun-fog-outdoors): GateTable, with the records below
        gate_table.clear();
    }
''', r'''    if (gate_table_on) { // bbport (r76_sun-fog-outdoors): GateTable, with the records below
        gate_table.clear();
        gate_caps.clear(); // bbport (r76c_sun-fog-shells): GateCaptures, beside it
    }
'''),
        (r'''        std::memcpy(&record.transform, camera.view.data(), sizeof(camera.view));
        out[built++] = record;
        if (gate_table_on) { // bbport (r76_sun-fog-outdoors): instance id built - 1
            gate_table.push_back({entry->base, entry->triangles, static_cast<u8>(record.mask)});
        }
''', r'''        std::memcpy(&record.transform, camera.view.data(), sizeof(camera.view));
        // bbport (r76c_sun-fog-shells): BB_VOLUMETRIC_GATE_SHELLS (test only, read once). At the
        // scene's first record: the line every 600 scenes (the last scene's shells), or once that
        // the text was not understood. While on, every record the sun gate may hit gets its gate
        // bits (GateSolidBits: 0x20 with the sun's 1, 0x40 with the camera pass's 2) unless the rule
        // takes its entry's last draw for a shell; the gate traces those bits alone (GateRayMask),
        // and every other ray sees the records as without the rule. Not set: nothing here.
        if (built == 0 && (gate_shell_rule.on || gate_shell_rule.bad)) {
            if (gate_shell_rule.bad && !gate_shell_bad_said) {
                gate_shell_bad_said = true;
                std::printf("Volumetric lighting (r76c): BB_VOLUMETRIC_GATE_SHELLS not understood "
                            "(tests: far, notest, nocull, <vs hex>:<ps hex>, <vs hex>:*, separated "
                            "by , or +, at most %u pairs): no shells left out\n",
                            VolumetricOcclusion::GateShellPairsMost);
            }
            if (gate_shell_rule.on && gate_shell_scenes++ % 600 == 1) {
                std::printf("Volumetric lighting (r76c): gate shells (BB_VOLUMETRIC_GATE_SHELLS%s%s%s, "
                            "%u pairs): %u of %u records the gate may hit were left out of its rays "
                            "in the last scene (%u of them sun casters); the gate traces mask bits "
                            "0x20 and 0x40\n",
                            gate_shell_rule.far_depth ? " far" : "",
                            gate_shell_rule.no_test ? " notest" : "",
                            gate_shell_rule.no_cull ? " nocull" : "", gate_shell_rule.pairs,
                            gate_shells_now, gate_shell_records, gate_shells_sun);
            }
            gate_shells_now = gate_shells_sun = gate_shell_records = 0;
        }
        if (gate_shell_rule.on) {
            const u32 bits = record.mask;
            const bool shell =
                (bits & 3u) != 0 && VolumetricOcclusion::GateShell(gate_shell_rule, entry->gate_cap);
            record.mask = u8(bits | VolumetricOcclusion::GateSolidBits(bits, shell));
            gate_shell_records += (bits & 3u) != 0 ? 1 : 0;
            gate_shells_now += shell ? 1 : 0;
            gate_shells_sun += shell && (bits & 1u) != 0 ? 1 : 0;
        }
        out[built++] = record;
        if (gate_table_on) { // bbport (r76_sun-fog-outdoors): instance id built - 1
            gate_table.push_back({entry->base, entry->triangles, static_cast<u8>(record.mask)});
            gate_caps.push_back(entry->gate_cap); // bbport (r76c_sun-fog-shells)
            gate_caps.back().moving = entry->dynamic;
        }
'''),
    ],
    # ------------------------------------------------------------------------------------------
    R + "vk_rasterizer_effects.cpp": [
        (r'''    if (r19_palette) { // bbport (r19_draw-cost)
        draw.palette = r19_motion.palette;
        ++r19_stats.motion_palettes;
    }
''', r'''    if (r19_palette) { // bbport (r19_draw-cost)
        draw.palette = r19_motion.palette;
        ++r19_stats.motion_palettes;
    }
    // bbport (r76c_sun-fog-shells): with BB_VOLUMETRIC_GATE_PROBE=1 or BB_VOLUMETRIC_GATE_SHELLS set
    // (VolumetricOcclusion::GateCaptureOn, read once), what the guest registers say of this draw,
    // for the entry PrepareDraw takes it into: its shaders and pass, depth test, write and compare
    // function, culled faces, front face, z clip and whether the viewport depth clamp is on (as
    // the pipeline key's depth_clamp_enable), the depth range its viewport maps to (as the
    // rasterizer sets the Vulkan viewport: zoffset and zscale where enabled) and the depth clamp
    // bounds. Off: one test of a static bool.
    static const bool gate_capture = VolumetricOcclusion::GateCaptureOn();
    if (gate_capture) {
        VolumetricOcclusion::GateCapture cap;
        cap.vs = vs.pgm_hash;
        cap.ps = ps ? ps->pgm_hash : 0;
        cap.depth = VolumetricOcclusion::GateDepthBits(regs.depth_control.depth_enable != 0,
                                                       regs.depth_control.depth_write_enable != 0,
                                                       u32(regs.depth_control.depth_func));
        cap.raster = VolumetricOcclusion::GateRasterBits(
            regs.polygon_control.cull_front != 0, regs.polygon_control.cull_back != 0,
            regs.polygon_control.front_face == AmdGpu::FrontFace::Clockwise,
            regs.clipper_control.ZclipEnable(),
            !regs.depth_render_override.disable_viewport_clamp);
        const auto& viewport = regs.viewports[0];
        const float zoffset = regs.viewport_control.zoffset_enable ? viewport.zoffset : 0.0f;
        const float zscale = regs.viewport_control.zscale_enable ? viewport.zscale : 1.0f;
        cap.dmin = regs.clipper_control.clip_space == AmdGpu::ClipSpace::MinusWToW ? zoffset - zscale
                                                                                  : zoffset;
        cap.dmax = zoffset + zscale;
        cap.zmin = regs.viewport_depths[0].zmin;
        cap.zmax = regs.viewport_depths[0].zmax;
        cap.camera_pass = draw.camera_pass;
        cap.known = true;
        rt_shadow->SetGateCapture(cap);
    }
'''),
        (r'''        volumetric_light->SetSunSceneTable(rt_scene ? &rt_shadow->GateTable() : nullptr);
''', r'''        volumetric_light->SetSunSceneTable(rt_scene ? &rt_shadow->GateTable() : nullptr);
        // bbport (r76c_sun-fog-shells): and what the capture knew of each (probe only)
        volumetric_light->SetSunSceneCaptures(rt_scene ? &rt_shadow->GateCaptures() : nullptr);
'''),
    ],
    # ------------------------------------------------------------------------------------------
    R + "vk_volumetric_light.h": [
        (r'''    void SetSunSceneTable(const std::vector<VolumetricOcclusion::GateInstance>* table) noexcept {
        sun_scene_table = table;
    }
''', r'''    void SetSunSceneTable(const std::vector<VolumetricOcclusion::GateInstance>* table) noexcept {
        sun_scene_table = table;
    }
    /// bbport (r76c_sun-fog-shells): what the capture knew of those instances, in the same order
    /// (RtShadow::GateCaptures; probe only; null: none), for the next Integrate.
    void SetSunSceneCaptures(const std::vector<VolumetricOcclusion::GateCapture>* captures) noexcept {
        sun_scene_captures = captures;
    }
'''),
        (r'''    void ReadGateProbe();
''', r'''    void ReadGateProbe();
    void ReadGateInstances(const std::array<u32, VolumetricOcclusion::GateProbeWords>& words); // (r76c)
'''),
        (r'''    std::vector<VolumetricOcclusion::GateInstance> probe_table;
''', r'''    std::vector<VolumetricOcclusion::GateInstance> probe_table;
    // bbport (r76c_sun-fog-shells): the instances' captures (SetSunSceneCaptures) and those of the
    // march probed; the DIAG build's words per instance and their copy for the host, and how many
    // instances that copy holds; whether the probe's file was begun this run
    const std::vector<VolumetricOcclusion::GateCapture>* sun_scene_captures = nullptr;
    std::vector<VolumetricOcclusion::GateCapture> probe_caps;
    std::unique_ptr<VideoCore::Buffer> probe_stats, probe_stats_readback;
    std::size_t probe_stats_count = 0;
    bool probe_file_begun = false;
'''),
    ],
    # ------------------------------------------------------------------------------------------
    R + "vk_volumetric_light.cpp": [
        (r'''    const GateParams params{offsets, reach, sun_scene_mask | diag_bits, GateMaxDistance};
''', r'''    // bbport (r76c_sun-fog-shells): with BB_VOLUMETRIC_GATE_SHELLS the records' gate bits for the
    // knob's mask (GateRayMask: 0x20 for the sun's casters, 0x40 for the camera pass's geometry,
    // shells left out); without it the knob's mask, as before
    const GateParams params{offsets, reach,
                            VolumetricOcclusion::GateRayMask(sun_scene_mask,
                                                             VolumetricOcclusion::GateShells().on) |
                                diag_bits,
                            GateMaxDistance};
'''),
        (r'''    const vk::DescriptorBufferInfo probe_info{diag ? probe_buffer->Handle() : vk::Buffer{}, 0,
                                              GateProbeBytes};
''', r'''    const vk::DescriptorBufferInfo probe_info{diag ? probe_buffer->Handle() : vk::Buffer{}, 0,
                                              GateProbeBytes};
    // bbport (r76c_sun-fog-shells): the DIAG build's words per instance (binding 8), zeroed before a
    // probe and, for the instances of the table, copied for the host after it
    const vk::DescriptorBufferInfo stats_info{diag ? probe_stats->Handle() : vk::Buffer{}, 0,
                                              VolumetricOcclusion::GateStatBytes};
    const std::size_t stats_instances =
        probing ? std::min<std::size_t>(probe_table.size(), VolumetricOcclusion::GateProbeInstancesMost)
                : 0;
    const u32 stats_bytes = u32(stats_instances * VolumetricOcclusion::GateStatWords * sizeof(u32));
    const vk::Buffer stats_back = probing ? probe_stats_readback->Handle() : vk::Buffer{};
    if (probing) {
        probe_stats_count = stats_instances;
    }
'''),
        (r'''        [params, cb, ub, out, first_out, band_out, probe_info, depth, diag, probing, mask_bytes,
''', r'''        [params, cb, ub, out, first_out, band_out, probe_info, depth, diag, probing, mask_bytes,
         stats_info, stats_bytes, stats_back, // bbport (r76c_sun-fog-shells)
'''),
        (r'''                cmd.fillBuffer(probe_info.buffer, 0, GateProbeHeaderBytes, 0);
''', r'''                cmd.fillBuffer(probe_info.buffer, 0, GateProbeHeaderBytes, 0);
                cmd.fillBuffer(stats_info.buffer, 0, VolumetricOcclusion::GateStatBytes, 0); // (r76c)
'''),
        (r'''            const std::array<vk::WriteDescriptorSet, 8> writes{{
''', r'''            const std::array<vk::WriteDescriptorSet, 9> writes{{ // (r76c: 9 with binding 8)
'''),
        (r'''                {.dstBinding = 7, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &depth},
            }};
''', r'''                {.dstBinding = 7, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &depth},
                // bbport (r76c_sun-fog-shells): the words per instance
                {.dstBinding = 8, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &stats_info},
            }};
'''),
        (r'''                                    std::span{writes.data(), diag ? 8u : 5u});
''', r'''                                    std::span{writes.data(), diag ? 9u : 5u});
'''),
        (r'''                cmd.copyBuffer(probe_info.buffer, readback,
                               vk::BufferCopy{0, 0, GateProbeHeaderBytes});
''', r'''                cmd.copyBuffer(probe_info.buffer, readback,
                               vk::BufferCopy{0, 0, GateProbeHeaderBytes});
                if (stats_bytes != 0) { // bbport (r76c_sun-fog-shells)
                    cmd.copyBuffer(stats_info.buffer, stats_back, vk::BufferCopy{0, 0, stats_bytes});
                }
'''),
        (r'''        EffectPass::HasRoom(instance, u64(GateWidth) * GateHeight * GateSlices + GateProbeBytes +
                                          GateProbeHeaderBytes) &&
        CreatePass(gate_diag,
                   {eStorageBuffer, eStorageBuffer, eAccelerationStructureKHR, eStorageImage,
                    eStorageImage, eStorageImage, eStorageBuffer, eCombinedImageSampler},
                   VOLUMETRIC_RT_GATE_DIAG_COMP, sizeof(GateParams), "Volumetric sun gate (diag)");
''', r'''        EffectPass::HasRoom(instance, u64(GateWidth) * GateHeight * GateSlices + GateProbeBytes +
                                          GateProbeHeaderBytes +
                                          2ull * VolumetricOcclusion::GateStatBytes) &&
        CreatePass(gate_diag,
                   {eStorageBuffer, eStorageBuffer, eAccelerationStructureKHR, eStorageImage,
                    eStorageImage, eStorageImage, eStorageBuffer, eCombinedImageSampler,
                    eStorageBuffer}, // bbport (r76c_sun-fog-shells): binding 8, words per instance
                   VOLUMETRIC_RT_GATE_DIAG_COMP, sizeof(GateParams), "Volumetric sun gate (diag)");
'''),
        (r'''        made = probe_readback->mapped_data.size() >= GateProbeHeaderBytes;
    }
''', r'''        made = probe_readback->mapped_data.size() >= GateProbeHeaderBytes;
        // bbport (r76c_sun-fog-shells): the DIAG build's words per instance and their host copy
        probe_stats = std::make_unique<VideoCore::Buffer>(
            instance, 0, VolumetricOcclusion::GateStatBytes, VideoCore::MemoryType::DeviceLocal,
            "Volumetric sun gate probe instances");
        probe_stats_readback = std::make_unique<VideoCore::Buffer>(
            instance, 0, VolumetricOcclusion::GateStatBytes, VideoCore::MemoryType::HostCached,
            "Volumetric sun gate probe instances readback");
        made = made && probe_stats_readback->mapped_data.size() >= VolumetricOcclusion::GateStatBytes;
    }
'''),
        (r'''        probe_marches = 0;
        probe_due = 600;
        if (sun_scene_table) {
            probe_table = *sun_scene_table;
        } else {
            probe_table.clear();
        }
''', r'''        probe_marches = 0;
        // bbport (r76c_sun-fog-shells): 600 unless BB_VOLUMETRIC_GATE_PROBE_EVERY says otherwise
        probe_due = VolumetricOcclusion::GateProbeEvery();
        if (sun_scene_table) {
            probe_table = *sun_scene_table;
        } else {
            probe_table.clear();
        }
        // bbport (r76c_sun-fog-shells): their captures, when they match the table
        if (sun_scene_captures && sun_scene_captures->size() == probe_table.size()) {
            probe_caps = *sun_scene_captures;
        } else {
            probe_caps.clear();
        }
'''),
        (r'''    sun_scene = vk::AccelerationStructureKHR{};
    sun_scene_table = nullptr;
''', r'''    sun_scene = vk::AccelerationStructureKHR{};
    sun_scene_table = nullptr;
    sun_scene_captures = nullptr; // bbport (r76c_sun-fog-shells)
'''),
        (r'''                column.c_str(), w[GateProbeAskedAt], probe_mask,
                static_cast<unsigned long long>(probe_table.size()), host);
}
''', r'''                column.c_str(), w[GateProbeAskedAt], probe_mask,
                static_cast<unsigned long long>(probe_table.size()), host);
    ReadGateInstances(w); // bbport (r76c_sun-fog-shells)
}

// bbport (r76c_sun-fog-shells): the probe's second line, "gate instances": the instances of the
// scene that shut the most cells in front of the visible surface (GateTopMost, the DIAG build's
// words per instance), and the one most rays straight up hit first when it is not among them
// ("above"). Per instance: n cells shut, ff the share hit on a front face, t the nearest and
// farthest hit (m), eye the nearest and farthest hit point from the camera (m), dy the lowest and
// highest hit point above the camera (world y, m), up the cells whose ray straight up hit it first
// with the nearest such hit (m), tri its triangles, m its record mask; then from the capture of its
// last draw: pass (cam or sun), vs and ps program hashes, z (t test, w write, compare function),
// vp the depth range its viewport maps to, clamp the depth clamp bounds ("off": the viewport
// clamp is off), cull (and zc: z clip on), ord its place among the frame's capture draws, cam0 how
// far (m) the camera moved between the first and last camera pass draw recorded for it ("-": none),
// dyn 1 when its ray traced copy is moving, and "shell" when BB_VOLUMETRIC_GATE_SHELLS takes it. With
// BB_VOLUMETRIC_GATE_PROBE_FILE the line also goes to that file (written anew at the run's first
// probe, appended after).
void VolumetricLight::ReadGateInstances(
    const std::array<u32, VolumetricOcclusion::GateProbeWords>& w) {
    using namespace VolumetricOcclusion;
    const std::size_t n = std::min<std::size_t>(probe_stats_count, probe_table.size());
    std::vector<u32> stats(n * GateStatWords, 0u);
    if (!stats.empty()) {
        const std::size_t bytes = stats.size() * sizeof(u32);
        probe_stats_readback->Invalidate(0, bytes);
        std::memcpy(stats.data(), probe_stats_readback->mapped_data.data(), bytes);
    }
    std::vector<u32> top = GateTopInstances(stats, GateTopMost);
    const std::size_t listed = top.size();
    u32 above = 0xFFFFFFFFu, above_cells = 0, shutting = 0;
    for (std::size_t i = 0; i < n; ++i) {
        shutting += stats[i * GateStatWords + GateStatCount] != 0 ? 1 : 0;
        const u32 up = stats[i * GateStatWords + GateStatUp];
        if (up > above_cells) {
            above_cells = up;
            above = u32(i);
        }
    }
    if (above != 0xFFFFFFFFu && std::ranges::find(top, above) == top.end()) {
        top.push_back(above);
    }
    const auto& m = probe_light.view_to_world;
    char part[384];
    std::string line = "Volumetric lighting (r76c): gate instances: ";
    if (probe_light.camera) {
        // (the view looks along +z, as the gate's cells take it: its world y is row 1, column 2)
        std::snprintf(part, sizeof(part), "camera world (%.1f,%.1f,%.1f) looking %+.0f deg up",
                      m[3], m[7], m[11], std::asin(std::clamp(m[6], -1.0f, 1.0f)) * 57.29578f);
    } else {
        std::snprintf(part, sizeof(part), "camera unknown");
    }
    line += part;
    if (probe_light.valid) {
        std::snprintf(part, sizeof(part), ", light elevation %.1f deg",
                      ElevationAzimuth(probe_light.world)[0]);
        line += part;
    }
    std::snprintf(part, sizeof(part),
                  "; shut <5/5-15/15-40/40-150/150-800 m = %u/%u/%u/%u/%u of %u asked; ray mask "
                  "0x%x%s; %u of %llu instances shut cells; marches %llu",
                  w[GateProbeShutAt], w[GateProbeShutAt + 1], w[GateProbeShutAt + 2],
                  w[GateProbeShutAt + 3], w[GateProbeShutAt + 4], w[GateProbeAskedAt],
                  GateRayMask(probe_mask, GateShells().on),
                  GateShells().on ? " (shell rule on)" : "", shutting,
                  static_cast<unsigned long long>(probe_table.size()),
                  static_cast<unsigned long long>(light_marches));
    line += part;
    static constexpr std::array<const char*, 8> Funcs{"N", "L", "E", "LE", "G", "NE", "GE", "A"};
    static constexpr std::array<const char*, 4> Culls{"none", "front", "back", "both"};
    for (std::size_t k = 0; k < top.size(); ++k) {
        const u32 i = top[k];
        const u32* s = &stats[std::size_t(i) * GateStatWords];
        const GateInstance& e = probe_table[i];
        const u32 count = s[GateStatCount];
        std::snprintf(part, sizeof(part), " | %s%llu id=%u n=%u", k < listed ? "#" : "above #",
                      static_cast<unsigned long long>(k + 1), i, count);
        line += part;
        if (count != 0) {
            std::snprintf(part, sizeof(part),
                          " ff=%u%% t=%.1f-%.1f eye=%.1f-%.1f dy=%+.1f..%+.1f",
                          u32(u64(s[GateStatFront]) * 100 / count), GateMinFloat(s[GateStatNear]),
                          GateMaxFloat(s[GateStatFar]), GateMinFloat(s[GateStatEyeNear]),
                          GateMaxFloat(s[GateStatEyeFar]), GateMinOrdered(s[GateStatLow]),
                          GateFromOrdered(s[GateStatHigh]));
            line += part;
        }
        std::snprintf(part, sizeof(part), " up=%u@%.1f tri=%u m=0x%02x", s[GateStatUp],
                      GateMinFloat(s[GateStatUpNear]), e.triangles, u32(e.mask));
        line += part;
        if (i < probe_caps.size() && probe_caps[i].known) {
            const GateCapture& c = probe_caps[i];
            char moved[24] = "-";
            if (c.eye_known) {
                std::snprintf(moved, sizeof(moved), "%.1f",
                              std::hypot(c.camera[0] - c.first_camera[0],
                                         c.camera[1] - c.first_camera[1],
                                         c.camera[2] - c.first_camera[2]));
            }
            std::snprintf(part, sizeof(part),
                          " %s vs=%016llx ps=%016llx z=%s%s/%s vp=%.3f-%.3f clamp=%.3f-%.3f%s "
                          "cull=%s%s ord=%u cam0=%s dyn=%d%s",
                          c.camera_pass ? "cam" : "sun", static_cast<unsigned long long>(c.vs),
                          static_cast<unsigned long long>(c.ps),
                          (c.depth & GateDepthTest) != 0 ? "t" : "-",
                          (c.depth & GateDepthWrite) != 0 ? "w" : "-", Funcs[GateDepthFunc(c.depth)],
                          c.dmin, c.dmax, c.zmin, c.zmax,
                          (c.raster & GateDepthClamp) != 0 ? "" : "(off)",
                          Culls[c.raster & (GateCullFront | GateCullBack)],
                          (c.raster & GateZclip) != 0 ? "/zc" : "", c.order, moved,
                          c.moving ? 1 : 0, GateShell(GateShells(), c) ? " shell" : "");
        } else {
            std::snprintf(part, sizeof(part), " capture unknown");
        }
        line += part;
    }
    std::printf("%s\n", line.c_str());
    if (const char* path = std::getenv("BB_VOLUMETRIC_GATE_PROBE_FILE"); path && path[0] != '\0') {
        if (std::FILE* file = std::fopen(path, probe_file_begun ? "a" : "w")) {
            probe_file_begun = true;
            std::fputs(line.c_str(), file);
            std::fputc('\n', file);
            std::fclose(file);
        }
    }
}
'''),
    ],
    # ------------------------------------------------------------------------------------------
    "engine/tests/test_volumetric_occlusion.cpp": [
        (r'''        assert(!GateCameraOnly(0x05) && GateCameraOnly(0x06) && !GateCameraOnly(0x07) &&
               GateCameraOnly(0x02) && GateCameraOnly(0x0E) && !GateCameraOnly(0x01));
    }
''', r'''        assert(!GateCameraOnly(0x05) && GateCameraOnly(0x06) && !GateCameraOnly(0x07) &&
               GateCameraOnly(0x02) && GateCameraOnly(0x0E) && !GateCameraOnly(0x01));
    }
    // bbport (r76c_sun-fog-shells): the probe's words per instance, the shell rule's text and
    // tests, the gate bits, the probe cadence.
    {
        // Ordered bits compare as the floats; a minimum as the largest complement; zeros are empty.
        const float values[] = {-500.0f, -5.0f, -0.25f, 0.0f, 0.25f, 5.0f, 500.0f};
        for (std::size_t i = 0; i + 1 < sizeof(values) / sizeof(values[0]); ++i) {
            assert(GateOrdered(values[i]) < GateOrdered(values[i + 1]));
            assert(GateFromOrdered(GateOrdered(values[i])) == values[i]);
            assert(GateMinOrdered(~GateOrdered(values[i])) == values[i]);
        }
        assert(GateMinFloat(0) == -1.0f && GateMinOrdered(0) == 0.0f);
        assert(GateMinFloat(~std::bit_cast<std::uint32_t>(27.5f)) == 27.5f &&
               GateMaxFloat(std::bit_cast<std::uint32_t>(27.5f)) == 27.5f);
        assert(GateStatWords == 10 && GateStatBytes == GateProbeInstancesMost * 40);
        // The most shut cells first, ties by instance, empty ones left out, at most `most`.
        std::vector<std::uint32_t> stats(5 * GateStatWords, 0u);
        stats[0 * GateStatWords] = 7;
        stats[1 * GateStatWords] = 0;
        stats[2 * GateStatWords] = 9;
        stats[3 * GateStatWords] = 7;
        stats[4 * GateStatWords] = 1;
        assert((GateTopInstances(stats, 8) == std::vector<std::uint32_t>{2, 0, 3, 4}));
        assert((GateTopInstances(stats, 2) == std::vector<std::uint32_t>{2, 0}));
        assert(GateTopInstances({}, 8).empty());
    }
    {
        // The shell rule's text.
        assert(!ParseGateShells(nullptr).on && !ParseGateShells(nullptr).bad);
        assert(!ParseGateShells("").on && !ParseGateShells("").bad);
        const GateShellRule all = ParseGateShells("far,notest,nocull,1a2B:3c,ff:*");
        assert(all.on && !all.bad && all.far_depth && all.no_test && all.no_cull && all.pairs == 2 &&
               all.vs[0] == 0x1a2b && all.ps[0] == 0x3c && all.vs[1] == 0xff && all.ps[1] == 0);
        // "+" separates as "," does (the slot workers split env values at commas)
        const GateShellRule plus = ParseGateShells("far+notest+1a2b:*");
        assert(plus.on && !plus.bad && plus.far_depth && plus.no_test && !plus.no_cull &&
               plus.pairs == 1 && plus.vs[0] == 0x1a2b && plus.ps[0] == 0);
        assert(ParseGateShells("far+").bad && ParseGateShells("+far").bad &&
               ParseGateShells("far,+notest").bad);
        for (const char* wrong : {"bogus", "far,", ",far", "far,,notest", "Far", " far", "1a2b",
                                  "1a2b:", ":3c", "0:3c", "1a:0", "g1:2", "1:2:3",
                                  "11111111111111111:1"}) {
            const GateShellRule rule = ParseGateShells(wrong);
            assert(!rule.on && rule.bad);
        }
        assert(ParseGateShells("1:1,2:2,3:3,4:4,5:5,6:6,7:7,8:8").pairs == 8);
        assert(ParseGateShells("1:1,2:2,3:3,4:4,5:5,6:6,7:7,8:8,9:9").bad);
        // Its tests on described draws.
        GateCapture c;
        c.known = true;
        c.vs = 0x1a2b;
        c.ps = 0x3c;
        c.depth = GateDepthBits(true, true, 3);
        c.raster = GateRasterBits(false, true, false, true, true);
        assert(GateDepthFunc(c.depth) == 3 && c.raster == (GateCullBack | GateZclip | GateDepthClamp));
        assert(!GateFarDepth(c));
        assert(GateShell(ParseGateShells("1a2b:3c"), c) && GateShell(ParseGateShells("1a2b:*"), c));
        assert(!GateShell(ParseGateShells("1a2b:3d"), c) && !GateShell(ParseGateShells("far"), c) &&
               !GateShell(ParseGateShells("notest"), c) && !GateShell(ParseGateShells("nocull"), c));
        GateCapture sky = c;
        sky.dmin = 1.0f;
        sky.dmax = 1.0f;
        assert(GateFarDepth(sky) && GateShell(ParseGateShells("far"), sky));
        sky = c;
        sky.zmin = 0.9995f;
        sky.zmax = 1.0f;
        assert(GateFarDepth(sky));
        sky.raster = GateRasterBits(false, true, false, true, false); // clamp off: bounds unused
        assert(!GateFarDepth(sky));
        sky = c;
        sky.depth = GateDepthBits(true, true, 7);
        assert(GateShell(ParseGateShells("notest"), sky));
        sky.depth = GateDepthBits(false, true, 3);
        assert(GateShell(ParseGateShells("notest"), sky));
        sky.raster = GateRasterBits(false, false, true, true, true);
        assert(GateShell(ParseGateShells("nocull"), sky));
        GateCapture unknown = sky;
        unknown.known = false;
        assert(!GateShell(ParseGateShells("far,notest,nocull"), unknown));
        assert(!GateShell(ParseGateShells("bogus"), sky));
        // The gate bits: other rays see the same instances; the gate traces only the new bits.
        assert(GateSolidBits(0x07, false) == 0x60 && GateSolidBits(0x05, false) == 0x20 &&
               GateSolidBits(0x06, false) == 0x40 && GateSolidBits(0x04, false) == 0 &&
               GateSolidBits(0x07, true) == 0 && GateSolidBits(0x10, false) == 0);
        assert(GateRayMask(1, true) == 0x20 && GateRayMask(2, true) == 0x40 &&
               GateRayMask(3, true) == 0x60 && GateRayMask(0, true) == 0);
        assert(GateRayMask(1, false) == 1 && GateRayMask(3, false) == 3 && GateRayMask(0, false) == 0);
        for (std::uint32_t record : {0x01u, 0x02u, 0x03u, 0x05u, 0x06u, 0x07u, 0x0Fu}) {
            for (std::uint32_t knob : {1u, 2u, 3u}) {
                // without a shell the gate hits a record with the rule exactly when without it
                const bool before = (record & knob) != 0;
                const bool after = ((record | GateSolidBits(record, false)) & GateRayMask(knob, true)) != 0;
                assert(before == after);
                assert(((record | GateSolidBits(record, true)) & GateRayMask(knob, true)) == 0);
                for (std::uint32_t other : {0x01u, 0x04u, 0x0Cu, 0xEFu, 0xFFu}) {
                    assert((((record | GateSolidBits(record, false)) & other) != 0) ==
                           ((record & other) != 0));
                }
            }
        }
        // The probe cadence.
        assert(ParseProbeEvery(nullptr) == 600 && ParseProbeEvery("") == 600 &&
               ParseProbeEvery("120") == 120 && ParseProbeEvery("30") == 30 &&
               ParseProbeEvery("6000") == 6000 && ParseProbeEvery("29") == 600 &&
               ParseProbeEvery("6001") == 600 && ParseProbeEvery("12x") == 600 &&
               ParseProbeEvery("-120") == 600 && ParseProbeEvery(" 120") == 600);
    }
'''),
    ],
    # ------------------------------------------------------------------------------------------
    "README.md": [
        (r'''| `BB_VOLUMETRIC_GATE_VIEW` | Debug only: `1` tints the screen where the gate shuts the sun out along the view, by the distance of the nearest hit: red under 5 m, yellow 5 to 15 m, green 15 to 40 m, cyan 40 to 150 m, magenta beyond; where the gate is open the picture is untouched. While on, every gated march traces to the nearest hit | off |
''', r'''| `BB_VOLUMETRIC_GATE_VIEW` | Debug only: `1` tints the screen where the gate shuts the sun out along the view, by the distance of the nearest hit: red under 5 m, yellow 5 to 15 m, green 15 to 40 m, cyan 40 to 150 m, magenta beyond; where the gate is open the picture is untouched. While on, every gated march traces to the nearest hit | off |
| `BB_VOLUMETRIC_GATE_SHELLS` | Test only: leaves out of the gate's rays (and of no other ray) the instances whose last draw passes any of these tests, separated by `,` or `+`: `far` (its viewport maps every depth to 0.999 or more, or the viewport depth clamp is on and both its bounds are 0.999 or more), `notest` (no depth test, or compare always), `nocull` (neither face culled), `<vs>:<ps>` or `<vs>:*` (program hashes in hex as the probe prints them; at most 8). While set, the gate traces instance mask bits 0x20 (sun casters) and 0x40 (camera pass), which every other instance gets. Text not understood leaves nothing out (said once) | not set |
| `BB_VOLUMETRIC_GATE_PROBE_EVERY` | Debug only, with `BB_VOLUMETRIC_GATE_PROBE=1`: gated marches between two probes after the first (the 120th), 30 to 6000. Each probe also logs a line "gate instances": the 8 instances that shut the most cells (their hits' distances, heights above the camera, front faces, rays straight up from those cells) with their shaders, pass, depth, cull and viewport depth state, how far the camera moved between their first and last camera pass draw and whether their ray traced copy is moving; those probe marches also trace one ray straight up per shut cell | `600` |
| `BB_VOLUMETRIC_GATE_PROBE_FILE` | Debug only, with `BB_VOLUMETRIC_GATE_PROBE=1`: a file the "gate instances" lines also go to (written anew at the run's first probe, then appended) | not set |
'''),
    ],
}

# Text checks on the patched result (each text must appear the given number of times).
CHECKS = {
    H + "volumetric_rt_gate.comp": [("layout(scalar, binding = 8) buffer GateProbeStats", 1),
                                    ("rayQueryGetIntersectionWorldToObjectEXT", 1),
                                    ("const uint StatWords = 10u;", 1)],
    R + "volumetric_occlusion.h": [("GateStatWords = 10", 1), ("inline GateShellRule ParseGateShells(", 1),
                                   ("constexpr std::uint32_t GateRayMask(", 1),
                                   ("*end != ',' && *end != '+'", 1), ("GateDepthClamp = 16", 1)],
    R + "vk_rt_shadow.cpp": [("VolumetricOcclusion::GateSolidBits(bits, shell)", 1),
                             ("entry.gate_cap = gate_next;", 1), ("gate_caps.push_back(entry->gate_cap);", 1)],
    R + "vk_rasterizer_effects.cpp": [("rt_shadow->SetGateCapture(cap);", 1),
                                      ("!regs.depth_render_override.disable_viewport_clamp);", 1),
                                      ("volumetric_light->SetSunSceneCaptures(", 1)],
    R + "vk_volumetric_light.cpp": [("std::array<vk::WriteDescriptorSet, 9> writes", 1), ("diag ? 9u : 5u", 1),
                                    ("void VolumetricLight::ReadGateInstances(", 1), ("ReadGateInstances(w);", 1),
                                    ("VolumetricOcclusion::GateProbeEvery()", 1)],
}

def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")

def text_checks(texts):
    for path, items in CHECKS.items():
        for text, n in items:
            got = texts[path].count(text)
            if got != n:
                raise SystemExit("text check failed: %s holds %r %d times, not %d" % (path, text, got, n))

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R76C_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(new) == 1 for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): state = "applied"
        elif todo == len(edits): state = "clean"
        else: raise SystemExit("%s: %d of %d edits applied, %d anchors found once" % (path, done, len(edits), todo))
        plan.append((path, edits, raw, eol, cur, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            texts = {}
            for path, edits, raw, eol, cur, _ in plan:
                for old, new in edits: cur = cur.replace(old, new)
                texts[path] = cur
            text_checks(texts)
            print("not applied; would apply (%d files, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied": print("already applied"); return
        texts = {}
        for path, edits, raw, eol, cur, _ in plan:
            for old, new in edits: cur = cur.replace(old, new)
            texts[path] = cur
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, edits, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, edits, raw, eol, cur, _ in plan:
            open(os.path.join(ROOT, path), "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    for path, edits, raw, eol, cur, _ in plan:
        for old, new in reversed(edits): cur = cur.replace(new, old)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    print("reverted")

main()
