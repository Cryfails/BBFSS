# r130b_water-moves: patch script (lane LRT, task LRT-T05 water and caustics). Owner goal LRT-G089: "I think for the caustics the
# water like in the sewer need to move or at least have some kind of movement/physics. Maybe the puddles should ripple from steps
# and wind too?" Applies ON TOP of r107 to r107f and r128b (refuses a tree without them).
#
# Stage 1 of the draft r130b_water-moves.draft.md. The later stages (motion without the caustics, a menu slider, a true ripple of
# the game's own water: r130e; the game's water shader read offline: r130f) are NOT in this script.
#
# What it does (OFF by default: see Off):
#  One wave field eta(x, z, t) on the water plane, world anchored, evaluated in caustics.comp (WaveAt: slope and curvature,
#  analytic): 4 travelling waves (wavelengths 0.60, 0.38, 0.24, 0.15 m; capillary-gravity dispersion x 0.6; heading from the wind
#  when it is at least 0.2 m/s, else a slow 30 degree flow; low-passed over 2 s) and up to 16 rings from the hunter's steps and
#  landings (the walker of footprints.h copied, FTP's three numbers). The field
#   (a) bends every pattern lookup (the position moves by MOTION_WARP x slope) and focuses it (times 1 - MOTION_FOCUS x curvature,
#       clamped 0..3): both keep the pattern's mean 1, so light is moved, not added (LRT-D124); every caller (sun, bed, lamps,
#       puddle ripple) moves at once;
#   (b) shimmers the water pixels themselves (a mirrored plane's pixels, or a checked puddle plane's glossy ones): their colour times
#       1 + MOTION_SHIMMER x strength x clamp(8 x slope toward the camera, -0.6, 0.6) x the distance fade. Honest label: the tilt
#       brightens or darkens the pixel's own light (mean 1); it is not a true re-reflection (that is r130e).
#  Deviation from the draft: the 4 waves share the steepness by 1 / k (k A = steepness x wavelength / 0.60), not equally. With equal
#  steepness the curvature of the 0.15 m wave was 4 times that of the 0.60 m one and the focus clipped at 0 (its mean left 1);
#  with the 1 / k share each wave bends the light as much as another and the focus stays near mean 1 (the test says how near).
#
# Does the motion show at the sewer? Said plainly: LRT-R229 has the lamp net add only 0.3 to 0.8% of the light on its own pixels.
# Moving that net with the field changes it by at most about its own size, which is at the level of the slot noise (0.26 to 0.37 of
# 255): the warp and the focus alone would NOT show in a one second pair of captures. The visible part is the shimmer on the water
# pixels (b): at strength 2 it swings those pixels by tens of percent, a wave period (1 to 2 Hz) after the first picture it has
# another phase. The slot job asks for the difference in the water (lower part of the frame), not in the net.
#
# Knobs: lantern.ini graphics_water_motion_strength (0..4, default 0 = off, live: read every frame, clamp and non-finite rules as
# graphics_water_caustics_*); env BB_WATER_MOTION (0..4; set and not empty wins, also with 0 or text; read through the live knobs
# header when the build has it, else once) so one slot game can flip it with set:BB_WATER_MOTION=... No menu entry (r130e).
#
# Files: host_shaders/caustics_layout.h, host_shaders/caustics.comp, renderer_vulkan/caustics_params.h, vk_caustics.h,
# vk_caustics.cpp, engine/gpu/shim/bbport_settings.h, bbport_settings.cpp, engine/tests/test_caustics.cpp, test_settings.cpp,
# README.md (one row after the lamps row of the water caustics table, anchored on caustics text only).
#
# Off guarantee (graphics_water_motion_strength=0 and BB_WATER_MOTION unset): the host's motion_strength is 0, so FlagsOf gives 0:
# CAUSTICS_FLAG_MOTION is never set, the hunter is not read, no wave or ring is advanced, no motion block is written (the buffer
# grows by 3328 bytes, zeroed once with the rest). In the shader every new statement sits under `(flags & CAUSTICS_FLAG_MOTION) != 0u`
# (a push constant, uniform false) except two: Pattern's `c` stays 1.0 and `net * c` is an exact multiply by 1.0, and `xz` is not
# touched. So the picture is bit for bit as before (the SPIR-V differs, the result does not). Needs the caustics pass: with both
# caustics strengths 0 no Caustics object exists and motion does nothing (the log says so).
# Cost (an estimate, not measured): off: one relaxed load and one live-knob generation compare a frame. On: WaveAt about 60 to 100 ALU
# (4 sin and cos, up to 16 ring tests, most skipped) for each Pattern call (band pixels x up to 4 lamps) and once for each water
# pixel; host under 5 us (one position read, 16 rings, a 104 word write); +3.3 KB host-visible buffer. The slot job's BB_GPU_PROFILE
# row "Lighting: water caustics" says it (sw1 against sw0). The pattern has no motion vectors: the upscaler may soften 2 to 3 Hz
# shimmer (MotionTimeScale 0.6 is the lever).
#
# Log lines start "Water motion (r130b)": L1 the strength and where it came from, L2 the first moving dispatch, L3 each report.
#
# Not verified: no full build and no Vulkan run (the unit tests and the shader are compiled on a private copy only); the shader's
# GLSL arithmetic is the C++ twin's by reading, not by a GPU run; the look and the cost are the slot jobs' to judge.
#
# Use: python -I -X utf8 r130b_water-moves.py check | apply | revert
# Root: R130B_ROOT, else <tree> (needs engine/gpu). Line ends kept (CRLF or LF; mixed refused). apply backs the originals up
# in r130b_backup next to this script. Each edit refuses unless its anchor / old text is found exactly once; a tree with some
# edits applied and some not is refused; text checks run on the result before anything is written; files are written through
# a temp file. revert puts back exactly what apply inserted or replaced.
import os, sys

ROOT = os.environ.get("R130B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r130b_backup")
TMP = ".r130btmp"
VC = "engine/gpu/shadps4/video_core/"
LAY = VC + "host_shaders/caustics_layout.h"
COMP = VC + "host_shaders/caustics.comp"
RV = VC + "renderer_vulkan/"
PAR = RV + "caustics_params.h"
VH = RV + "vk_caustics.h"
VC_CPP = RV + "vk_caustics.cpp"
SH = "engine/gpu/shim/bbport_settings.h"
SC = "engine/gpu/shim/bbport_settings.cpp"
TC = "engine/tests/test_caustics.cpp"
TS = "engine/tests/test_settings.cpp"
R = "README.md"
CODE = (LAY, COMP, PAR, VH, VC_CPP, SH, SC, TC, TS)


def L(text):
    # a block of lines: one leading newline dropped, a trailing newline ensured
    if text.startswith("\n"):
        text = text[1:]
    return text if text.endswith("\n") else text + "\n"


# ("ins", anchor, before, after): the anchor stays; `before` goes in front of it, `after` behind it.
# ("rep", old, new): old is replaced by new (new never holds old: the state test needs that).
EDITS = {}

# ---------------------------------------------------------------------------------------------------------------- layout
EDITS[LAY] = [
("ins", "#define CAUSTICS_FLAG_WORLD 256u\n", "",
 L(r"""
// bbport (r130b_water-moves): BB_WATER_MOTION / graphics_water_motion_strength: the slot's motion block (CAUSTICS_MOTION_* below) is
// written and WaveAt bends and focuses every pattern lookup and shimmers the water pixels. Without the flag none of it runs.
#define CAUSTICS_FLAG_MOTION 512u
""")),
("ins", "#define CAUSTICS_W_BED_PUDDLE 38\n", "",
 L(r"""
// bbport (r130b_water-moves): 39 water pixels the shimmer changed (the free word).
#define CAUSTICS_W_MOTION_WATER 39
""")),
("ins", "#define CAUSTICS_EVOLVE2_SHIFT 17.0\n", "",
 L(r"""
// bbport (r130b_water-moves): the moving water. After the data blocks, a motion block of CAUSTICS_MOTION_WORDS words a slot (base
// CAUSTICS_MOTION_BASE), written by the host before a dispatch with CAUSTICS_FLAG_MOTION: word KIND the plane (0 none, 1 mirrored,
// 2 a checked puddle plane), RINGS the rings live, STRENGTH (float) the knob, RING_PX the water pixels a ring reached (the SHADER
// adds, one atomicAdd a group; the host reads it before it rewrites the slot), from WAVES_AT CAUSTICS_MOTION_WAVES waves of
// WAVE_WORDS (k x, k z, A, phase, 0 ...: eta = A sin(k . xz - phase)), from RINGS_AT up to MAX_RINGS rings of RING_WORDS (x, z,
// age s, amplitude m). Focus: the pattern times clamp(1 - FOCUS x curvature, 0, 3); warp: its position moves by WARP x slope; the
// shimmer: SHIMMER x strength x clamp(8 x slope toward the camera, -0.6, 0.6). A ring is a packet at radius RING_SPEED x age, width
// RING_WIDTH, wave number RING_K (rad/m), amplitude falling as exp(-age / RING_TAU) / sqrt(1 + r / RING_R0); it lives RING_LIFE s.
#define CAUSTICS_MOTION_WORDS 104
#define CAUSTICS_MOTION_BASE (CAUSTICS_SLOTS * (CAUSTICS_SLOT_WORDS + CAUSTICS_DATA_WORDS))
#define CAUSTICS_MOTION_KIND 0
#define CAUSTICS_MOTION_RINGS 1
#define CAUSTICS_MOTION_STRENGTH 2
#define CAUSTICS_MOTION_RING_PX 3
#define CAUSTICS_MOTION_WAVES_AT 4
#define CAUSTICS_MOTION_WAVE_WORDS 8
#define CAUSTICS_MOTION_WAVES 4
#define CAUSTICS_MOTION_RINGS_AT 36
#define CAUSTICS_MOTION_RING_WORDS 4
#define CAUSTICS_MOTION_MAX_RINGS 16
#define CAUSTICS_MOTION_FOCUS 0.25
#define CAUSTICS_MOTION_WARP 4.0
#define CAUSTICS_MOTION_SHIMMER 0.35
#define CAUSTICS_RING_SPEED 0.30
#define CAUSTICS_RING_WIDTH 0.05
#define CAUSTICS_RING_K 89.76
#define CAUSTICS_RING_TAU 0.9
#define CAUSTICS_RING_LIFE 2.5
#define CAUSTICS_RING_R0 0.05
""")),
]

# ---------------------------------------------------------------------------------------------------------------- shader
EDITS[COMP] = [
("ins", "shared uint group_counts[CAUSTICS_SLOT_WORDS];\n", "",
 L(r"""
shared uint group_ring; // r130b: the water pixels in this group a ring packet reached""")),
("ins", "// The caustic pattern at a point of the water (world x, z), mean 1 (CAUSTICS_PATTERN_MEAN).\n",
 L(r"""
// bbport (r130b_water-moves): the moving water. The slot's motion block (caustics_layout.h CAUSTICS_MOTION_*), written by the host.
uint Motion(uint i) {
    return counts[CAUSTICS_MOTION_BASE + slot * CAUSTICS_MOTION_WORDS + i];
}

bool ring_hit = false; // WaveAt evaluated a ring packet (its last call)

// The wave field at a point of the water (world x, z): returns its curvature (the Laplacian of eta), `g` its slope (the gradient).
// 4 waves eta = A sin(k . xz - phase) and the rings' packets f(s) of the radius: f = G E C, G = a exp(-age / tau) / sqrt(1 + r / r0),
// E = exp(-s^2 / 2 w^2), C = cos(K s), s = r - speed x age; f' and f'' analytic (G' = -G / (2 (r0 + r)), G'' = 0.75 G / (r0 + r)^2).
float WaveAt(vec2 xz, out vec2 g) {
    g = vec2(0.0);
    float lap = 0.0;
    ring_hit = false;
    for (uint i = 0u; i < uint(CAUSTICS_MOTION_WAVES); ++i) {
        const uint at = uint(CAUSTICS_MOTION_WAVES_AT) + i * uint(CAUSTICS_MOTION_WAVE_WORDS);
        const vec2 kv = vec2(uintBitsToFloat(Motion(at)), uintBitsToFloat(Motion(at + 1u)));
        const float amp = uintBitsToFloat(Motion(at + 2u));
        const float th = dot(kv, xz) - uintBitsToFloat(Motion(at + 3u));
        g += (amp * cos(th)) * kv;
        lap -= amp * dot(kv, kv) * sin(th);
    }
    const uint rings = min(Motion(CAUSTICS_MOTION_RINGS), uint(CAUSTICS_MOTION_MAX_RINGS));
    for (uint j = 0u; j < rings; ++j) {
        const uint at = uint(CAUSTICS_MOTION_RINGS_AT) + j * uint(CAUSTICS_MOTION_RING_WORDS);
        const float age = uintBitsToFloat(Motion(at + 2u));
        const vec2 d = xz - vec2(uintBitsToFloat(Motion(at)), uintBitsToFloat(Motion(at + 1u)));
        const float r = length(d);
        const float s = r - CAUSTICS_RING_SPEED * age;
        if (abs(s) >= 3.0 * CAUSTICS_RING_WIDTH || r < 1e-4 || age >= CAUSTICS_RING_LIFE) {
            continue;
        }
        const float w2 = CAUSTICS_RING_WIDTH * CAUSTICS_RING_WIDTH;
        const float gain = uintBitsToFloat(Motion(at + 3u)) * exp(-age / CAUSTICS_RING_TAU) * inversesqrt(1.0 + r / CAUSTICS_RING_R0);
        const float e = exp(-0.5 * s * s / w2);
        const float c = cos(CAUSTICS_RING_K * s), sn = sin(CAUSTICS_RING_K * s);
        const float h0 = e * c;
        const float h1 = e * (-(s / w2) * c - CAUSTICS_RING_K * sn);
        const float h2 = e * (c * (s * s / (w2 * w2) - 1.0 / w2 - CAUSTICS_RING_K * CAUSTICS_RING_K) +
                              2.0 * s * CAUSTICS_RING_K * sn / w2);
        const float g1 = -0.5 * gain / (CAUSTICS_RING_R0 + r);
        const float g2 = 0.75 * gain / ((CAUSTICS_RING_R0 + r) * (CAUSTICS_RING_R0 + r));
        const float f1 = g1 * h0 + gain * h1;
        const float f2 = g2 * h0 + 2.0 * g1 * h1 + gain * h2;
        g += f1 * (d / r);
        lap += f2 + f1 / max(r, 0.02);
        ring_hit = true;
    }
    return lap;
}

// The caustic brightness the curvature gives (mean 1: a hollow focuses, a crest spreads).
float Focus(float lap) {
    return clamp(1.0 - CAUSTICS_MOTION_FOCUS * lap, 0.0, 3.0);
}

"""), ""),
("ins", "    const vec2 a = (xz + drift.xy * speed) * (1.0 / CAUSTICS_LAMBDA1);\n",
 L(r"""
    // bbport (r130b_water-moves): with the flag the wave field bends the position (the light moves) and focuses the pattern; both
    // keep its mean 1. Without it `c` stays 1.0 and `xz` is not touched.
    float c = 1.0;
    if ((flags & CAUSTICS_FLAG_MOTION) != 0u) {
        vec2 slope;
        const float lap = WaveAt(xz, slope);
        xz += CAUSTICS_MOTION_WARP * slope;
        c = Focus(lap);
    }"""), ""),
("rep",
 "    return 0.5 * (pow(r1, CAUSTICS_SHARP) + pow(r2, CAUSTICS_SHARP)) * (1.0 / CAUSTICS_PATTERN_MEAN);\n",
 L(r"""
    const float net = 0.5 * (pow(r1, CAUSTICS_SHARP) + pow(r2, CAUSTICS_SHARP)) * (1.0 / CAUSTICS_PATTERN_MEAN);
    return net * c; // r130b: c is 1.0 without the motion flag""")),
("ins", "    vec3 added = vec3(0.0), direct = vec3(0.0); // r107c: direct, the lamps' own light (the model)\n",
 L(r"""
    // bbport (r130b_water-moves): the surface shimmer. A water pixel (up-facing, on the mirrored plane within the tolerance, or a
    // glossy one on the checked puddle plane) closer than CAUSTICS_FADE_END has its own light times 1 + SHIMMER x strength x the
    // wave field's slope toward the camera (clamped, mean 1, faded out with distance). Not a true re-reflection: the tilt
    // brightens or darkens the light the pixel has. The host sets the plane's kind (0 none, 1 mirrored, 2 puddle plane).
    if ((flags & CAUSTICS_FLAG_MOTION) != 0u) {
        const uint mo_kind = Motion(CAUSTICS_MOTION_KIND);
        if (mo_kind != 0u && P.z < CAUSTICS_FADE_END && abs(height) <= CAUSTICS_WATER_M + CAUSTICS_WATER_REL * P.z &&
            (mo_kind == 1u ||
             ((flags & CAUSTICS_FLAG_MATERIAL) != 0u &&
              texelFetch(material_tex, TexelOf(material_tex, p, vec2(p) + 0.5), 0).r >= CAUSTICS_PUDDLE_GLOSS))) {
            if (!have_n) {
                n = NormalAt(p, P);
                have_n = true;
            }
            const vec2 mo_to_camera = vec2(inv0.w, inv2.w) - Pw.xz;
            const float mo_len = length(mo_to_camera);
            if (DirToWorld(n).y >= CAUSTICS_PUDDLE_UP && mo_len > 1e-3) {
                vec2 mo_slope;
                WaveAt(Pw.xz, mo_slope);
                const float mo_tilt = clamp(dot(mo_slope, mo_to_camera / mo_len) * 8.0, -0.6, 0.6) *
                                      (1.0 - smoothstep(CAUSTICS_FADE_START, CAUSTICS_FADE_END, P.z));
                factor *= 1.0 + CAUSTICS_MOTION_SHIMMER * uintBitsToFloat(Motion(CAUSTICS_MOTION_STRENGTH)) * mo_tilt;
                atomicAdd(group_counts[CAUSTICS_W_MOTION_WATER], 1u);
                if (ring_hit) {
                    atomicAdd(group_ring, 1u);
                }
            }
        }
    }
"""), ""),
("ins", "    barrier();\n    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);\n",
 L(r"""
    if ((flags & CAUSTICS_FLAG_MOTION) != 0u && gl_LocalInvocationIndex == 0u) {
        group_ring = 0u; // r130b
    }"""), ""),
("ins", "            atomicAdd(counts[slot * CAUSTICS_SLOT_WORDS + i], v);\n        }\n    }\n", "",
 L(r"""
    if ((flags & CAUSTICS_FLAG_MOTION) != 0u && gl_LocalInvocationIndex == 0u && group_ring != 0u) {
        // r130b: the water pixels a ring reached, to the slot's motion block (the host reads it before it rewrites the slot)
        atomicAdd(counts[CAUSTICS_MOTION_BASE + slot * CAUSTICS_MOTION_WORDS + CAUSTICS_MOTION_RING_PX], group_ring);
    }""")),
]

# ---------------------------------------------------------------------------------------------------------------- params
EDITS[PAR] = [
("ins", "inline float Pattern(float x, float z, const std::array<float, 4>& drift, float evolve) {\n",
 L(r"""
// bbport (r130b_water-moves): the moving water (BB_WATER_MOTION, graphics_water_motion_strength). One wave field on the water plane,
// world anchored: 4 travelling waves (heading from the wind, else a slow flow) and rings from the hunter's steps and landings. The
// host keeps its state (the phases summed in double) and writes it to the slot's motion block (WriteBlock); caustics.comp WaveAt
// reads it: it bends and focuses every pattern lookup (mean 1: light is moved, not added) and shimmers the water pixels. Off
// (strength 0): FlagsOf is 0, so no flag, no block, no hunter read, no update. Eval is the C++ twin of WaveAt (in double), for the test.
namespace Motion {

inline constexpr double Pi = 3.14159265358979323846;
inline constexpr std::uint32_t FlagMotion = CAUSTICS_FLAG_MOTION;
inline constexpr std::uint32_t Waves = CAUSTICS_MOTION_WAVES, MaxRings = CAUSTICS_MOTION_MAX_RINGS;
inline constexpr std::uint32_t Words = CAUSTICS_MOTION_WORDS, Base = CAUSTICS_MOTION_BASE;
static_assert(FlagMotion == 512u && CAUSTICS_W_MOTION_WATER < CAUSTICS_W_HEIGHTS && CAUSTICS_W_MOTION_WATER > CAUSTICS_W_BED_PUDDLE);
static_assert(CAUSTICS_MOTION_WAVES_AT + CAUSTICS_MOTION_WAVES * CAUSTICS_MOTION_WAVE_WORDS == CAUSTICS_MOTION_RINGS_AT);
static_assert(CAUSTICS_MOTION_RINGS_AT + CAUSTICS_MOTION_MAX_RINGS * CAUSTICS_MOTION_RING_WORDS <= CAUSTICS_MOTION_WORDS);
static_assert(4 + 4 * 8 + 16 * 4 <= CAUSTICS_MOTION_WORDS && CAUSTICS_MOTION_WAVES == 4 && CAUSTICS_MOTION_MAX_RINGS == 16);
static_assert(CAUSTICS_MOTION_BASE == CAUSTICS_SLOTS * (CAUSTICS_SLOT_WORDS + CAUSTICS_DATA_WORDS) &&
              CAUSTICS_MOTION_RING_PX < CAUSTICS_MOTION_WAVES_AT);

/// The waves: wavelengths (m) and directions from the heading (degrees); capillary-gravity dispersion w^2 = g k + (sigma / rho) k^3,
/// times TimeScale (calmer than open water, and kinder to the upscaler). The heading follows the wind (WindMin m/s or more) or
/// CalmDeg, low-passed with HeadingTau seconds. The steepness k A of the longest wave is SteepPerStrength x strength x the wind's
/// amplitude factor (0.6 calm, 1 at WindFull m/s, 1.4 at most), at most SteepMax; each shorter wave has its share Wavelength / 0.60.
inline constexpr std::array<double, 4> Wavelength{0.60, 0.38, 0.24, 0.15};
inline constexpr std::array<double, 4> DirectionDeg{0.0, 25.0, -40.0, 100.0};
inline constexpr double Gravity = 9.81, Tension = 7.4e-5, TimeScale = 0.6;
inline constexpr double HeadingTau = 2.0, CalmDeg = 30.0, WindMin = 0.2, WindFull = 1.5;
inline constexpr float SteepPerStrength = 0.05f, SteepMax = 0.15f;
/// A ring's amplitude (m) at strength 1; a landing is LandingTimes as much; a drop of LandMinM to DropM in one frame is a landing.
inline constexpr float RingAmp = 0.0008f, LandingTimes = 2.0f, LandMinM = 0.3f;
/// The footprints' walker (footprints.h: StrideM, GaitHalfM, JumpM, DropM, TurnMinM, Walk), copied: that header is on another branch
/// (it pulls the live knobs and blood headers). Keep the numbers the same.
inline constexpr float StrideM = 0.75f, GaitHalfM = 0.11f, JumpM = 2.0f, DropM = 1.0f, TurnMinM = 0.05f;

inline double Omega(double wavelength) {
    const double k = 2.0 * Pi / wavelength;
    return std::sqrt(Gravity * k + Tension * k * k * k) * TimeScale;
}

inline double WrapPi(double a) {
    a = std::fmod(a + Pi, 2.0 * Pi);
    return (a < 0.0 ? a + 2.0 * Pi : a) - Pi;
}

/// BB_WATER_MOTION's text: unset or empty is -1 (the setting decides); else 0..MaxStrength (text that is not a finite number, or
/// not above 0, is 0: the variable decides, as BB_CAUSTICS does).
inline float ParseEnv(const char* text) {
    if (text == nullptr || text[0] == 0) {
        return -1.0f;
    }
    char* end = nullptr;
    const float v = std::strtof(text, &end);
    while (end != nullptr && (*end == ' ' || *end == '\t')) {
        ++end;
    }
    if (end == text || end == nullptr || *end != 0 || !std::isfinite(v)) {
        return 0.0f;
    }
    return v > 0.0f ? std::min(v, MaxStrength) : 0.0f;
}

/// The strength in force: the variable's (ParseEnv, 0 or more) when it names one, else the setting's (SettingOf).
inline float Pick(float env, float setting) {
    return env >= 0.0f ? (std::isfinite(env) ? std::min(env, MaxStrength) : 0.0f) : SettingOf(setting);
}

/// The push flag: only for a strength above 0 and a dispatch that runs. Strength 0 (or not finite): never.
inline std::uint32_t FlagsOf(float strength, bool dispatching) {
    return dispatching && std::isfinite(strength) && strength > 0.0f ? FlagMotion : 0u;
}

inline bool Finite3(const float* v) {
    return std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]);
}

/// The hunter's path since the last step (footprints.h Walk, copied).
struct Walker {
    bool have = false;
    float last[3]{};
    float acc = 0.0f; ///< path across since the last step
    float anchor_x = 0.0f, anchor_z = 0.0f;
    float dir_x = 0.0f, dir_z = 1.0f;
    float side = 1.0f; ///< the next step's side (+1, -1 in turn)
    std::uint32_t jumps = 0;
};

struct Step {
    bool step = false;
    float x = 0.0f, y = 0.0f, z = 0.0f;
};

/// One frame's position: a step when the path since the last one reached StrideM; it stands GaitHalfM to the side. A move of more
/// than JumpM across or DropM up or down in one frame starts the path anew.
inline Step Walk(Walker& w, const float pos[3]) {
    Step s;
    if (!w.have) {
        w.have = true;
        std::copy(pos, pos + 3, w.last);
        w.acc = 0.0f;
        w.anchor_x = pos[0];
        w.anchor_z = pos[2];
        return s;
    }
    const float dx = pos[0] - w.last[0], dy = pos[1] - w.last[1], dz = pos[2] - w.last[2];
    const float across = std::sqrt(dx * dx + dz * dz);
    std::copy(pos, pos + 3, w.last);
    if (!(across <= JumpM) || !(std::fabs(dy) <= DropM)) { // (a NaN fails both)
        ++w.jumps;
        w.acc = 0.0f;
        w.anchor_x = pos[0];
        w.anchor_z = pos[2];
        return s;
    }
    w.acc += across;
    if (w.acc < StrideM) {
        return s;
    }
    const float ax = pos[0] - w.anchor_x, az = pos[2] - w.anchor_z;
    const float along = std::sqrt(ax * ax + az * az);
    if (along >= TurnMinM) {
        w.dir_x = ax / along;
        w.dir_z = az / along;
    }
    w.acc = w.acc >= 2.0f * StrideM ? 0.0f : w.acc - StrideM; // a run's frame may pass two strides: one step
    w.anchor_x = pos[0];
    w.anchor_z = pos[2];
    s.step = true;
    s.y = pos[1];
    s.x = pos[0] - w.side * GaitHalfM * w.dir_z;
    s.z = pos[2] + w.side * GaitHalfM * w.dir_x;
    w.side = -w.side;
    return s;
}

struct Ring {
    float x = 0.0f, z = 0.0f, age = 0.0f, amp = 0.0f;
};

/// Everything the host keeps: the waves' heading and phases, the rings and the walker.
struct State {
    bool started = false;
    double heading = 0.0;           ///< rad: the waves travel toward (cos, sin) in world (x, z)
    std::array<double, 4> phase{};  ///< rad, 0 to 2 pi, summed in double so floats never grow
    double wind_speed = 0.0;        ///< m/s, horizontal, at the last Advance
    float amp = 0.6f;               ///< the wind's amplitude factor at the last Advance
    float steep = 0.0f;             ///< k A of the longest wave at the last Advance
    std::array<Ring, 16> rings{};
    std::uint32_t count = 0;        ///< rings live (the first `count` of `rings`)
    Walker walker;
};

/// A ring at (x, z): the 17th replaces the oldest.
inline void AddRing(State& s, float x, float z, float amp) {
    std::uint32_t at = s.count;
    if (s.count >= MaxRings) {
        at = 0;
        for (std::uint32_t i = 1; i < MaxRings; ++i) {
            if (s.rings[i].age > s.rings[at].age) {
                at = i;
            }
        }
    } else {
        ++s.count;
    }
    s.rings[at] = {x, z, 0.0f, amp};
}

/// The field's time, by real seconds (clamped to MaxStep, as Drift): the heading toward the wind's (low-passed), the phases, the
/// wind's amplitude factor and the steepness, the rings' ages (a ring of CAUSTICS_RING_LIFE s is gone).
inline void Advance(State& s, double seconds, const std::array<float, 3>& wind, float strength) {
    const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;
    const double wx = std::isfinite(wind[0]) ? double(wind[0]) : 0.0, wz = std::isfinite(wind[2]) ? double(wind[2]) : 0.0;
    const double speed = std::sqrt(wx * wx + wz * wz);
    const double target = speed >= WindMin ? std::atan2(wz, wx) : CalmDeg * Pi / 180.0;
    if (!s.started) {
        s.started = true;
        s.heading = target;
    } else {
        s.heading = WrapPi(s.heading + WrapPi(target - s.heading) * (1.0 - std::exp(-dt / HeadingTau)));
    }
    s.wind_speed = speed;
    s.amp = float(0.6 + 0.4 * std::min(speed / WindFull, 2.0));
    const float st = std::isfinite(strength) ? std::max(strength, 0.0f) : 0.0f;
    s.steep = std::min(SteepPerStrength * st * s.amp, SteepMax);
    for (std::uint32_t i = 0; i < Waves; ++i) {
        s.phase[i] = std::fmod(s.phase[i] + Omega(Wavelength[i]) * dt, 2.0 * Pi);
    }
    std::uint32_t live = 0;
    for (std::uint32_t i = 0; i < s.count; ++i) {
        Ring r = s.rings[i];
        r.age += float(dt);
        if (r.age < float(CAUSTICS_RING_LIFE)) {
            s.rings[live++] = r;
        }
    }
    s.count = live;
}

struct Events {
    std::uint32_t steps = 0, landings = 0;
};

/// The hunter's position this frame (world x, y, z; y up): a ring at each step (RingAmp x strength) and, for a drop of LandMinM to
/// DropM in one frame (not a jump), one at the position at LandingTimes the amplitude.
inline Events Observe(State& s, const float pos[3], float strength) {
    Events e;
    const float amp = RingAmp * (std::isfinite(strength) ? std::max(strength, 0.0f) : 0.0f);
    if (s.walker.have) {
        const float dx = pos[0] - s.walker.last[0], dz = pos[2] - s.walker.last[2];
        const float drop = s.walker.last[1] - pos[1];
        if (std::sqrt(dx * dx + dz * dz) <= JumpM && drop >= LandMinM && drop <= DropM) {
            AddRing(s, pos[0], pos[2], amp * LandingTimes);
            ++e.landings;
        }
    }
    const Step st = Walk(s.walker, pos);
    if (st.step) {
        AddRing(s, st.x, st.z, amp);
        ++e.steps;
    }
    return e;
}

/// The waves' heading in degrees, 0 to 360.
inline double HeadingDeg(const State& s) {
    const double d = s.heading * 180.0 / Pi;
    return d < 0.0 ? d + 360.0 : d;
}

/// The motion block of a slot (caustics_layout.h), whole: kind (0 none, 1 mirrored plane, 2 checked puddle plane), the rings, the
/// strength, the waves and the rings. The ring pixel word (the shader's) is 0: the host reads it before this.
inline void WriteBlock(std::uint32_t* b, const State& s, std::uint32_t kind, float strength) {
    std::memset(b, 0, Words * sizeof(std::uint32_t));
    const auto put = [b](std::uint32_t at, float v) { std::memcpy(&b[at], &v, sizeof(float)); };
    b[CAUSTICS_MOTION_KIND] = kind;
    b[CAUSTICS_MOTION_RINGS] = s.count;
    put(CAUSTICS_MOTION_STRENGTH, strength);
    for (std::uint32_t i = 0; i < Waves; ++i) {
        const double k = 2.0 * Pi / Wavelength[i];
        const double dir = s.heading + DirectionDeg[i] * Pi / 180.0;
        const double share = Wavelength[i] / Wavelength[0];
        const std::uint32_t at = CAUSTICS_MOTION_WAVES_AT + i * CAUSTICS_MOTION_WAVE_WORDS;
        put(at, float(k * std::cos(dir)));
        put(at + 1, float(k * std::sin(dir)));
        put(at + 2, float(double(s.steep) * share / k)); // A = (k A) / k
        put(at + 3, float(s.phase[i]));
    }
    for (std::uint32_t i = 0; i < s.count && i < MaxRings; ++i) {
        const std::uint32_t at = CAUSTICS_MOTION_RINGS_AT + i * CAUSTICS_MOTION_RING_WORDS;
        put(at, s.rings[i].x);
        put(at + 1, s.rings[i].z);
        put(at + 2, s.rings[i].age);
        put(at + 3, s.rings[i].amp);
    }
}

/// What the field is at a point: the height, its slope and curvature (the shader's WaveAt, in double); `ring`: a ring packet counted.
struct Sample {
    double eta = 0.0, gx = 0.0, gz = 0.0, lap = 0.0;
    bool ring = false;
};

inline float BitsToFloat(std::uint32_t u) {
    float f = 0.0f;
    std::memcpy(&f, &u, sizeof(f));
    return f;
}

inline Sample Eval(const std::uint32_t* b, double x, double z) {
    Sample r;
    for (std::uint32_t i = 0; i < Waves; ++i) {
        const std::uint32_t at = CAUSTICS_MOTION_WAVES_AT + i * CAUSTICS_MOTION_WAVE_WORDS;
        const double kx = BitsToFloat(b[at]), kz = BitsToFloat(b[at + 1]), amp = BitsToFloat(b[at + 2]);
        const double th = kx * x + kz * z - double(BitsToFloat(b[at + 3]));
        r.eta += amp * std::sin(th);
        r.gx += amp * std::cos(th) * kx;
        r.gz += amp * std::cos(th) * kz;
        r.lap -= amp * (kx * kx + kz * kz) * std::sin(th);
    }
    const std::uint32_t rings = std::min(b[CAUSTICS_MOTION_RINGS], MaxRings);
    const double w = CAUSTICS_RING_WIDTH, w2 = w * w, kk = CAUSTICS_RING_K, r0 = CAUSTICS_RING_R0;
    for (std::uint32_t j = 0; j < rings; ++j) {
        const std::uint32_t at = CAUSTICS_MOTION_RINGS_AT + j * CAUSTICS_MOTION_RING_WORDS;
        const double age = BitsToFloat(b[at + 2]);
        const double dx = x - double(BitsToFloat(b[at])), dz = z - double(BitsToFloat(b[at + 1]));
        const double rr = std::sqrt(dx * dx + dz * dz);
        const double s = rr - CAUSTICS_RING_SPEED * age;
        if (std::fabs(s) >= 3.0 * w || rr < 1e-4 || age >= CAUSTICS_RING_LIFE) {
            continue;
        }
        const double gain = double(BitsToFloat(b[at + 3])) * std::exp(-age / CAUSTICS_RING_TAU) / std::sqrt(1.0 + rr / r0);
        const double e = std::exp(-0.5 * s * s / w2), c = std::cos(kk * s), sn = std::sin(kk * s);
        const double h0 = e * c;
        const double h1 = e * (-(s / w2) * c - kk * sn);
        const double h2 = e * (c * (s * s / (w2 * w2) - 1.0 / w2 - kk * kk) + 2.0 * s * kk * sn / w2);
        const double g1 = -0.5 * gain / (r0 + rr), g2 = 0.75 * gain / ((r0 + rr) * (r0 + rr));
        const double f1 = g1 * h0 + gain * h1, f2 = g2 * h0 + 2.0 * g1 * h1 + gain * h2;
        r.eta += gain * h0;
        r.gx += f1 * dx / rr;
        r.gz += f1 * dz / rr;
        r.lap += f2 + f1 / std::max(rr, 0.02);
        r.ring = true;
    }
    return r;
}

/// The caustic brightness the curvature gives (the shader's Focus; mean 1), and the position the slope moves the net to.
inline float Focus(float lap) {
    return std::clamp(1.0f - float(CAUSTICS_MOTION_FOCUS) * lap, 0.0f, 3.0f);
}

} // namespace Motion

"""), ""),
]

# ---------------------------------------------------------------------------------------------------------------- vk_caustics.h
EDITS[VH] = [
("ins", "    ::BbCaustics::Drift drift;\n", "",
 L(r"""
    // bbport (r130b_water-moves): the moving water: its state, the strength in force (0: nothing runs) and where it came from
    ::BbCaustics::Motion::State motion;
    float motion_strength = 0.0f;
    bool motion_env = false;""")),
("ins", "        u32 world_changes = 0; ///< r107f: new plane generations (the map starts again)\n", "",
 L(r"""
        u32 motion_dispatches = 0, steps = 0, landings = 0; ///< r130b: dispatches with the motion, the hunter's steps and landings
        u64 ring_px = 0;                                    ///< r130b: the water pixels the rings reached, summed
        bool hunter_read = false;                           ///< r130b: the last frame's position read worked""")),
("ins", "    bool told_first = false;\n", "",
 L(r"""
    bool told_motion = false; ///< r130b: the first moving dispatch was said
    u32 motion_changes = 0;   ///< r130b: Refresh found another strength""")),
]

# ---------------------------------------------------------------------------------------------------------------- vk_caustics.cpp
EDITS[VC_CPP] = [
("ins", '#include "bbport_toggles.h"\n', "",
 L(r"""
#if __has_include("bbport_live_knobs.h")
#include "bbport_live_knobs.h" // test tools (r84_live-test-knobs) only: BB_WATER_MOTION live; else it is read once
#endif
#include "engine/engine_state.h" // bbport (r130b_water-moves): the hunter's position""")),
("rep",
 "constexpr vk::DeviceSize BufferBytes = CounterBytes + BC::Slots * BC::DataWords * sizeof(u32);\n",
 L(r"""
constexpr vk::DeviceSize BufferBytes = CounterBytes + BC::Slots * BC::DataWords * sizeof(u32) +
                                       BC::Slots * BC::Motion::Words * sizeof(u32); // r130b: the motion block a slot""")),
("ins", "} // namespace\n\n// bbport (r128b_lrt-caustics-water): the setting's numbers are the header's",
 L(r"""
// bbport (r130b_water-moves): the strength of the moving water: BB_WATER_MOTION when set and not empty (live where the build has the
// live knobs header, else read once), else the lantern.ini setting graphics_water_motion_strength (a relaxed load).
struct MotionIn {
    float strength = 0.0f;
    bool from_env = false;
};

MotionIn MotionNow() {
#if __has_include("bbport_live_knobs.h")
    static BbLiveKnobs::Knob<float> knob{"BB_WATER_MOTION", BC::Motion::ParseEnv};
    const float env = knob.Get();
#else
    static const float env = BC::Motion::ParseEnv(std::getenv("BB_WATER_MOTION"));
#endif
    const float setting = BbSettings::Get().graphics_water_motion_strength.load(std::memory_order_relaxed);
    return {BC::Motion::Pick(env, setting), env >= 0.0f};
}
"""), ""),
("ins", "BbSettings::WaterCausticsStrengthMin == 0.0f && BbSettings::WaterCausticsStrengthDefault == 0.0f);\n", "",
 L(r"""
// bbport (r130b_water-moves): the motion setting's numbers are the same (one maximum, off by default).
static_assert(BbSettings::WaterMotionStrengthMax == ::BbCaustics::MaxStrength && BbSettings::WaterMotionStrengthMin == 0.0f &&
              BbSettings::WaterMotionStrengthDefault == 0.0f);""")),
("ins", "void Caustics::Refresh() {\n", "",
 L(r"""
    {   // bbport (r130b_water-moves): the moving water's strength; a start from 0 starts the field anew
        const MotionIn in = MotionNow();
        if (in.strength != motion_strength) {
            ++motion_changes;
            if (motion_strength <= 0.0f) {
                motion = {};
            }
            motion_strength = in.strength;
        }
        motion_env = in.from_env;
    }""")),
("ins", "    drift.Advance(std::chrono::duration<double>(now - last_time).count(), wind);\n", "",
 L(r"""
    if (motion_strength > 0.0f) { // bbport (r130b_water-moves): the field's time and the hunter's steps (nothing at 0)
        BC::Motion::Advance(motion, std::chrono::duration<double>(now - last_time).count(), wind, motion_strength);
        float feet[3] = {};
        stats.hunter_read = BbEngine::world_player_position(feet) && BC::Motion::Finite3(feet);
        if (stats.hunter_read) {
            const auto seen = BC::Motion::Observe(motion, feet, motion_strength);
            stats.steps += seen.steps;
            stats.landings += seen.landings;
        }
    }""")),
("ins", "    slot_camera_y[push.slot] = camera.inv_view[7];\n",
 L(r"""
    // bbport (r130b_water-moves): the moving water: this slot's motion block (its last reader, Slots dispatches ago, is long done;
    // its ring pixel word is read first) and the flag. Only with a strength above 0 and a dispatch that draws or measures.
    if (const u32 motion_flag = BC::Motion::FlagsOf(motion_strength, draw || lamp_draw || puddle_pass); motion_flag != 0u) {
        const u32 motion_kind = plane && (draw || lamp_draw) ? 1u : (puddle_pass && puddle_found && puddle_checked ? 2u : 0u);
        u32* block = static_cast<u32*>(counters.mapped) + BC::Motion::Base + push.slot * BC::Motion::Words;
        stats.ring_px += block[CAUSTICS_MOTION_RING_PX];
        BC::Motion::WriteBlock(block, motion, motion_kind, motion_strength);
        push.flags |= motion_flag;
        ++stats.motion_dispatches;
        if (!told_motion) {
            told_motion = true;
            std::printf("Water motion (r130b): first moving dispatch at frame %llu: %s plane at y %.2f; 4 waves 0.15-0.60 m toward "
                        "%.0f deg, steepness %.3f, wind %.2f m/s (%s)\n",
                        static_cast<unsigned long long>(BbStats::frame_number.load(std::memory_order_relaxed)),
                        motion_kind == 1 ? "mirrored" : motion_kind == 2 ? "puddle" : "no", double(plane_y),
                        BC::Motion::HeadingDeg(motion), double(motion.steep), motion.wind_speed,
                        motion_env ? "environment" : "setting");
        }
    }
"""), ""),
("ins", '"; both 0: nothing is made or drawn");\n    }\n', "",
 L(r"""
    // bbport (r130b_water-moves): the moving water's strength (first frame, after a change, at most once every 600)
    static StrengthKnob::Line motion_line;
    const MotionIn moving = MotionNow();
    const StrengthKnob::Value motion_value{moving.strength, moving.from_env};
    if (motion_line.Due(LineCalls, motion_value)) {
        std::printf("Water motion (r130b): strength %.2f from the %s (%s)%s\n", double(moving.strength),
                    StrengthKnob::SourceName(motion_value),
                    moving.from_env ? "BB_WATER_MOTION" : "graphics_water_motion_strength",
                    !(moving.strength > 0.0f) ? "; 0: off, nothing runs"
                    : sun.value > 0.0f || lamps.value > 0.0f
                        ? ""
                        : "; the water caustics are off (both strengths 0): nothing moves");
    }""")),
("ins", "    // bbport (r128b_lrt-caustics-water): the strengths now and how often the setting moved them\n",
 L(r"""
    // bbport (r130b_water-moves): the moving water (a moving dispatch: means over the dispatches that had the flag)
    if (motion_strength > 0.0f || stats.motion_dispatches != 0) {
        const double moving = std::max(1.0, double(stats.motion_dispatches));
        BbReport::Printf("Water motion (r130b): %u dispatches moved; waves toward %.0f deg, amplitude x%.2f, wind %.2f m/s; "
                         "hunter %s, %u steps, %u landings, %u rings live; water px moved %.0f, ring px %.0f a dispatch; "
                         "%u strength changes\n",
                         stats.motion_dispatches, BC::Motion::HeadingDeg(motion), double(motion.amp), motion.wind_speed,
                         stats.hunter_read ? "read" : "not read", stats.steps, stats.landings, motion.count,
                         double(stats.pixels[CAUSTICS_W_MOTION_WATER]) / moving, double(stats.ring_px) / moving, motion_changes);
    }
"""), ""),
]

# ---------------------------------------------------------------------------------------------------------------- settings
EDITS[SH] = [
("ins", "                       WaterCausticsStrengthDefault = 0.0f;\n", "",
 L(r"""
// bbport (r130b_water-moves): the moving water's strength (graphics_water_motion_strength): 0 off, up to the caustics' maximum.
inline constexpr float WaterMotionStrengthMin = 0.0f, WaterMotionStrengthMax = 4.0f, WaterMotionStrengthDefault = 0.0f;""")),
("ins", "    std::atomic<float> graphics_water_caustics_lamps_strength{WaterCausticsStrengthDefault}; // 0..4, bbport (r128b): lamps; 0: off\n", "",
 L(r"""
    std::atomic<float> graphics_water_motion_strength{WaterMotionStrengthDefault}; // 0..4, bbport (r130b): moving water; 0: off""")),
]
EDITS[SC] = [
("ins", '    } else if (key == "graphics_heat_haze_strength") { // bbport (r97e_heat-haze-option)\n',
 L(r"""
    } else if (key == "graphics_water_motion_strength") { // bbport (r130b_water-moves)
        v.graphics_water_motion_strength =
            Clamp(std::isfinite(f) ? f : WaterMotionStrengthDefault, WaterMotionStrengthMin, WaterMotionStrengthMax);"""), ""),
("ins", '    put("graphics_water_caustics_lamps_strength", fixed(v.graphics_water_caustics_lamps_strength, 2));\n', "",
 L(r"""
    put("graphics_water_motion_strength", fixed(v.graphics_water_motion_strength, 2)); // bbport (r130b)""")),
]

# ---------------------------------------------------------------------------------------------------------------- tests
EDITS[TS] = [
("ins", "    // bbport (r109a_strength-settings-engine): the halation's and the lamp flicker's strengths.",
 L(r"""
    // bbport (r130b_water-moves): the moving water's strength. The default 0 (off); written back; read; saved after a change; a value
    // outside 0..4 is the nearest end; a text that is no number is 0; a value that is not finite is the default.
    static_assert(BbSettings::WaterMotionStrengthMin == 0.0f && BbSettings::WaterMotionStrengthMax == 4.0f &&
                  BbSettings::WaterMotionStrengthDefault == 0.0f);
    assert(s.graphics_water_motion_strength == BbSettings::WaterMotionStrengthDefault);
    BbSettings::Save();
    assert(Read(path).find("graphics_water_motion_strength=0.00\n") != std::string::npos);
    { std::ofstream file(path); file << "graphics_water_motion_strength=2.25\n"; }
    BbSettings::Load();
    assert(s.graphics_water_motion_strength == 2.25f);
    s.graphics_water_motion_strength = 4.0f;
    BbSettings::Save();
    assert(Read(path).find("graphics_water_motion_strength=4.00\n") != std::string::npos);
    { std::ofstream file(path); file << "graphics_water_motion_strength=-1\n"; }
    BbSettings::Load();
    assert(s.graphics_water_motion_strength == 0.0f);
    { std::ofstream file(path); file << "graphics_water_motion_strength=9\n"; }
    BbSettings::Load();
    assert(s.graphics_water_motion_strength == BbSettings::WaterMotionStrengthMax);
    { std::ofstream file(path); file << "graphics_water_motion_strength=abc\n"; }
    BbSettings::Load();
    assert(s.graphics_water_motion_strength == 0.0f);
    { std::ofstream file(path); file << "graphics_water_motion_strength=inf\n"; }
    s.graphics_water_motion_strength = 3.0f; // not the default before this Load
    BbSettings::Load();
    assert(s.graphics_water_motion_strength == BbSettings::WaterMotionStrengthDefault);
    BbSettings::Save();
"""), ""),
]

EDITS[TC] = [
("ins", '    std::printf("caustics: ok',
 L(r"""
    // bbport (r130b_water-moves): the moving water: the knob, the flag, the waves, the rings, the walker, the block, the twin's maths.
    {
        namespace M = Motion;
        // the knob: unset or empty -1 (the setting decides); else 0..4, text and not above 0 are 0
        assert(M::ParseEnv(nullptr) == -1.0f && M::ParseEnv("") == -1.0f);
        assert(M::ParseEnv("0") == 0.0f && M::ParseEnv("2.5") == 2.5f && M::ParseEnv("9") == MaxStrength);
        assert(M::ParseEnv("-1") == 0.0f && M::ParseEnv("abc") == 0.0f && M::ParseEnv("nan") == 0.0f && M::ParseEnv("1x") == 0.0f);
        assert(M::ParseEnv("1 ") == 1.0f);
        assert(M::Pick(-1.0f, 2.0f) == 2.0f && M::Pick(0.0f, 2.0f) == 0.0f && M::Pick(3.0f, 0.0f) == 3.0f);
        assert(M::Pick(-1.0f, 9.0f) == MaxStrength && M::Pick(-1.0f, NAN) == 0.0f && M::Pick(-1.0f, -2.0f) == 0.0f);
        // off: strength 0 (or not finite, or no dispatch) never gives the flag; a strength above 0 does
        assert(M::FlagsOf(0.0f, true) == 0u && M::FlagsOf(-1.0f, true) == 0u && M::FlagsOf(NAN, true) == 0u);
        assert(M::FlagsOf(1.0f, false) == 0u && M::FlagsOf(0.01f, true) == CAUSTICS_FLAG_MOTION && M::FlagMotion == 512u);
        assert(M::Words == 104u && M::Base == Slots * (SlotWords + DataWords) && M::Base * 4 == 8 * (168 + 48) * 4);
        // the dispersion of the 0.15 m wave: sqrt(g k + (sigma / rho) k^3) x 0.6, within 1% (k = 2 pi / 0.15)
        {
            const double k = 2.0 * M::Pi / 0.15, w = std::sqrt(9.81 * k + 7.4e-5 * k * k * k) * 0.6;
            assert(std::fabs(M::Omega(0.15) - w) < 0.01 * w && std::fabs(M::Omega(0.15) - 12.24) < 0.1);
            assert(M::Omega(0.60) < M::Omega(0.38) && M::Omega(0.38) < M::Omega(0.24) && M::Omega(0.24) < M::Omega(0.15));
        }
        // the heading follows the wind, low-passed: 63% of a step in 2 s; calm: 30 degrees; wind under 0.2 m/s is calm
        {
            M::State s;
            M::Advance(s, 0.1, {0.0f, 0.0f, 0.0f}, 2.0f);
            assert(std::fabs(M::HeadingDeg(s) - 30.0) < 1e-6 && s.amp == 0.6f);
            M::State t = s;
            for (int i = 0; i < 20; ++i) {
                M::Advance(t, 0.1, {0.0f, 0.0f, 3.0f}, 2.0f); // wind toward +z: 90 degrees
            }
            const double moved = (M::HeadingDeg(t) - 30.0) / (90.0 - 30.0);
            assert(std::fabs(moved - (1.0 - std::exp(-1.0))) < 1e-6);
            M::State u = s;
            M::Advance(u, 0.1, {0.1f, 0.0f, 0.1f}, 2.0f);
            assert(std::fabs(M::HeadingDeg(u) - 30.0) < 1e-6);
            for (int i = 0; i < 400; ++i) {
                M::Advance(t, 0.1, {0.0f, 0.0f, 3.0f}, 2.0f);
            }
            assert(std::fabs(M::HeadingDeg(t) - 90.0) < 1e-3 && t.amp == 1.4f); // the cap, wind 3 m/s
            M::State v;
            M::Advance(v, 0.1, {NAN, 0.0f, INFINITY}, 2.0f); // not finite: calm
            assert(std::fabs(M::HeadingDeg(v) - 30.0) < 1e-6);
            // the amplitude factor: 0.6 calm, 1.0 at 1.5 m/s, 1.4 from 3 m/s; the steepness 0.05 x strength x it, at most 0.15
            M::State a;
            M::Advance(a, 0.1, {1.5f, 0.0f, 0.0f}, 2.0f);
            assert(Near(a.amp, 1.0f, 1e-6f) && Near(a.steep, 0.1f, 1e-6f));
            M::Advance(a, 0.1, {1.5f, 0.0f, 0.0f}, 4.0f);
            assert(a.steep == M::SteepMax);
            M::Advance(a, 0.1, {0.0f, 0.0f, 0.0f}, 0.0f);
            assert(a.steep == 0.0f);
            // the phases stay in 0..2 pi however long it runs
            for (int i = 0; i < 100000; ++i) {
                M::Advance(a, 0.1, {0.0f, 0.0f, 0.0f}, 1.0f);
            }
            for (const double p : a.phase) {
                assert(p >= 0.0 && p < 2.0 * M::Pi);
            }
        }
        // the walker (footprints.h's cases): a step every 0.75 m of path, to the side in turn; a 2 m jump or a 1 m drop starts anew
        {
            M::Walker w;
            const float p0[3] = {0.0f, 0.0f, 0.0f};
            assert(!M::Walk(w, p0).step);
            int steps = 0;
            float side_sum = 0.0f;
            for (int i = 1; i <= 100; ++i) {
                const float p[3] = {0.1f * float(i), 0.0f, 0.0f};
                const M::Step st = M::Walk(w, p);
                steps += st.step ? 1 : 0;
                if (st.step) {
                    side_sum += st.z; // +0.11, -0.11 in turn: the sum stays within one
                    assert(Near(std::fabs(st.z), M::GaitHalfM, 1e-5f) && Near(st.x, p[0], 1e-5f));
                }
            }
            assert(steps == 13 && std::fabs(side_sum) <= M::GaitHalfM + 1e-5f); // 10 m / 0.75 m
            const float far[3] = {50.0f, 0.0f, 0.0f};
            assert(!M::Walk(w, far).step && w.jumps == 1 && w.acc == 0.0f);
            const float down[3] = {50.0f, -1.5f, 0.0f};
            assert(!M::Walk(w, down).step && w.jumps == 2);
            const float nan3[3] = {NAN, 0.0f, 0.0f};
            assert(!M::Walk(w, nan3).step && w.jumps == 3);
        }
        // steps and landings make rings (Observe); a drop of 0.3 to 1 m is a landing at twice the amplitude; a ring lives 2.5 s
        {
            M::State s;
            const float a[3] = {0.0f, 0.0f, 0.0f}, b[3] = {0.8f, 0.0f, 0.0f}, c[3] = {0.8f, -0.5f, 0.0f}, d[3] = {0.8f, -2.0f, 0.0f};
            assert(M::Observe(s, a, 2.0f).steps == 0 && s.count == 0);
            const M::Events one = M::Observe(s, b, 2.0f);
            assert(one.steps == 1 && one.landings == 0 && s.count == 1 && Near(s.rings[0].amp, 0.0016f, 1e-7f));
            const M::Events two = M::Observe(s, c, 2.0f);
            assert(two.landings == 1 && two.steps == 0 && s.count == 2 && Near(s.rings[1].amp, 0.0032f, 1e-7f));
            const M::Events three = M::Observe(s, d, 2.0f); // 1.5 m drop: a warp, no ring
            assert(three.steps == 0 && three.landings == 0 && s.count == 2);
            for (int i = 0; i < 24; ++i) {
                M::Advance(s, 0.1, {0.0f, 0.0f, 0.0f}, 2.0f);
            }
            assert(s.count == 2); // 2.4 s
            M::Advance(s, 0.1, {0.0f, 0.0f, 0.0f}, 2.0f);
            M::Advance(s, 0.1, {0.0f, 0.0f, 0.0f}, 2.0f);
            assert(s.count == 0); // 2.6 s (the ages are floats: 25 steps of 0.1 may stay just under 2.5): gone
            // 20 rings: the oldest is replaced, 16 stay
            for (int i = 0; i < 20; ++i) {
                M::AddRing(s, float(i), 0.0f, 0.001f);
                M::Advance(s, 0.01, {0.0f, 0.0f, 0.0f}, 2.0f);
            }
            assert(s.count == 16);
        }
        // a ring is zero outside |s| < 3 w and after its life; its slope and curvature are the height's derivatives
        {
            M::State s;
            M::AddRing(s, 1.0f, 2.0f, 0.002f);
            for (int i = 0; i < 10; ++i) {
                M::Advance(s, 0.1, {0.0f, 0.0f, 0.0f}, 0.0f); // strength 0: no waves, the ring alone; age 1.0 s: radius 0.30 m
            }
            std::uint32_t block[M::Words];
            M::WriteBlock(block, s, 1, 2.0f);
            const double band = 3.0 * CAUSTICS_RING_WIDTH;
            for (int i = 0; i < 400; ++i) {
                const double r = 0.0125 * double(i); // 0 to 5 m from the ring's centre, along x
                const M::Sample v = M::Eval(block, 1.0 + r, 2.0);
                const bool inside = std::fabs(r - CAUSTICS_RING_SPEED * 1.0) < band + 0.002 || r < 1e-3; // (a margin: the age is a float)
                if (!inside) {
                    assert(v.eta == 0.0 && v.gx == 0.0 && v.gz == 0.0 && v.lap == 0.0 && !v.ring);
                }
            }
            double most = 0.0;
            for (int i = 0; i < 2000; ++i) {
                const double x = 1.0 + 0.2 + 0.0001 * double(i), z = 2.0 + 0.05; // across the packet
                const M::Sample v = M::Eval(block, x, z);
                const double h = 1e-6;
                const M::Sample xp = M::Eval(block, x + h, z), xm = M::Eval(block, x - h, z);
                const M::Sample zp = M::Eval(block, x, z + h), zm = M::Eval(block, x, z - h);
                if (std::fabs(std::sqrt((x - 1.0) * (x - 1.0) + 0.0025) - 0.3) > band - 0.01) {
                    continue; // near the cut: the packet is cut off at 3 w (a step of about 1% of its peak)
                }
                const double gx = (xp.eta - xm.eta) / (2 * h), gz = (zp.eta - zm.eta) / (2 * h);
                const double lap = (xp.eta + xm.eta + zp.eta + zm.eta - 4.0 * v.eta) / (h * h);
                assert(std::fabs(gx - v.gx) < 1e-5 * (1.0 + std::fabs(v.gx)) && std::fabs(gz - v.gz) < 1e-5 * (1.0 + std::fabs(v.gz)));
                assert(std::fabs(lap - v.lap) < 1e-4 * (1.0 + std::fabs(v.lap)));
                most = std::max(most, std::fabs(v.lap));
            }
            assert(most > 1.0); // the ring bends the light (curvature of the order a k^2 / sqrt(1 + r / r0): a few per metre)
            for (int i = 0; i < 16; ++i) {
                M::Advance(s, 0.1, {0.0f, 0.0f, 0.0f}, 0.0f); // 2.6 s in all: gone
            }
            M::WriteBlock(block, s, 1, 2.0f);
            assert(block[CAUSTICS_MOTION_RINGS] == 0u && !M::Eval(block, 1.3, 2.0).ring);
        }
        // the waves' slope and curvature are the height's derivatives, and the block is the layout's (kind, rings, strength, 0 ring px)
        {
            M::State s;
            for (int i = 0; i < 37; ++i) {
                M::Advance(s, 0.05, {1.0f, 0.0f, 0.5f}, 2.0f);
            }
            std::uint32_t block[M::Words];
            std::memset(block, 0xAB, sizeof(block));
            M::WriteBlock(block, s, 2, 2.0f);
            assert(block[CAUSTICS_MOTION_KIND] == 2u && block[CAUSTICS_MOTION_RINGS] == 0u && block[CAUSTICS_MOTION_RING_PX] == 0u);
            assert(M::BitsToFloat(block[CAUSTICS_MOTION_STRENGTH]) == 2.0f);
            for (std::uint32_t i = CAUSTICS_MOTION_RINGS_AT; i < M::Words; ++i) {
                assert(block[i] == 0u);
            }
            double worst = 0.0;
            for (int i = 0; i < 200; ++i) {
                const double x = -3.0 + 0.0613 * double(i), z = 4.0 - 0.0471 * double(i);
                const M::Sample v = M::Eval(block, x, z);
                const double h = 1e-5;
                const M::Sample xp = M::Eval(block, x + h, z), xm = M::Eval(block, x - h, z);
                const M::Sample zp = M::Eval(block, x, z + h), zm = M::Eval(block, x, z - h);
                assert(std::fabs((xp.eta - xm.eta) / (2 * h) - v.gx) < 1e-5 && std::fabs((zp.eta - zm.eta) / (2 * h) - v.gz) < 1e-5);
                worst = std::max(worst, std::fabs((xp.eta + xm.eta + zp.eta + zm.eta - 4.0 * v.eta) / (h * h) - v.lap));
            }
            assert(worst < 0.05);
        }
        // the focus keeps the light's mean at 1 (4 x 4 m, strength 4, windy, rings alive, four moments); the slope stays moderate
        {
            double worst = 0.0, top_slope = 0.0, top_warp = 0.0, sum_all = 0.0;
            int moments = 0;
            M::State s;
            const float feet[6][3] = {{0.0f, 0.0f, 0.0f}, {0.8f, 0.0f, 0.1f}, {1.6f, 0.0f, 0.0f},
                                      {2.4f, 0.0f, 0.1f}, {3.2f, 0.0f, 0.0f}, {4.0f, 0.0f, 0.1f}};
            for (int step = 0; step < 6; ++step) {
                M::Observe(s, feet[step], 4.0f);
                for (int i = 0; i < 8; ++i) {
                    M::Advance(s, 0.05, {1.5f, 0.0f, 0.4f}, 4.0f);
                }
            }
            for (int moment = 0; moment < 4; ++moment) {
                for (int i = 0; i < 17; ++i) {
                    M::Advance(s, 0.05, {1.5f, 0.0f, 0.4f}, 4.0f);
                }
                std::uint32_t block[M::Words];
                M::WriteBlock(block, s, 1, 4.0f);
                double sum = 0.0;
                int n = 0;
                for (int i = 0; i < 200; ++i) {
                    for (int j = 0; j < 200; ++j) {
                        const M::Sample v = M::Eval(block, 0.0207 * i, 0.0203 * j);
                        sum += M::Focus(float(v.lap));
                        ++n;
                        top_slope = std::max(top_slope, std::hypot(v.gx, v.gz));
                        top_warp = std::max(top_warp, 4.0 * std::hypot(v.gx, v.gz));
                    }
                }
                worst = std::max(worst, std::fabs(sum / n - 1.0));
                sum_all += sum / n;
                ++moments;
            }
            std::printf("water motion: focus mean %.4f (worst moment %.4f), top slope %.3f, top warp %.2f m\n", sum_all / moments,
                        worst, top_slope, top_warp);
            assert(worst < 0.03);
            assert(top_slope < 0.8);
        }
    }
"""), ""),
]

# README: one row after the lamps row of the water caustics table, anchored on caustics text only
ROW = (
    "| `graphics_water_motion_strength`, `BB_WATER_MOTION` | The moving water (r130b_water-moves), `lantern.ini` key 0 to 4, default `0` "
    "(off, read every frame; a value outside the range is the nearest end, one that is not a finite number is `0`, text that is no "
    "number is `0`); `BB_WATER_MOTION` wins over it when set and not empty (also with `0` or text; live in a test build, else read "
    "once). It needs the water caustics (a strength above 0): with both at 0 nothing moves. One wave field on the water, world "
    "anchored: 4 travelling waves (0.15 to 0.60 m, toward the wind, else a slow flow) and rings from the hunter's steps and "
    "landings (a puddle or the sewer water ripples where he walks). It bends and focuses the caustics' net (light moved, not added) "
    "and shimmers the water's own pixels (the mirrored plane in the sewers, a puddle plane under lamps): their light times 1 plus "
    "0.35 x strength x the slope toward the camera, clamped to 0.6, faded out by 45 m; the tilt brightens or darkens the light the "
    "pixel has, it is not a true re-reflection. The net alone changes by less than the picture's noise (it adds 0.3 to 0.8% of the "
    "light on its pixels); the shimmer is the visible part. Cost (an estimate, not measured): about 0.02 to 0.05 ms GPU at the "
    "sewer at 4K, 3.3 KB of buffer; with `0` nothing of it runs and the picture is as before | `0` |")
EDITS[R] = [("ins", "| `BB_CAUSTICS` | `1`: on; a number above 0 is the strength, up to 4 (0, unset,", ROW + "\n", "")]
ORDER = (LAY, COMP, PAR, VH, VC_CPP, SH, SC, TC, TS, R)


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.isfile(full):
        raise SystemExit("REFUSED %s: missing" % path)
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    done = todo = 0
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            parts = [t for t in (before, after) if t]
            na, counts = cur.count(anchor), [cur.count(t) for t in parts]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                                 % (path, na, counts, anchor[:80]))
        else:
            _, old, new = e
            no, nn = cur.count(old), cur.count(new)
            if no == 1 and nn == 0:
                todo += 1
            elif no == 0 and nn == 1:
                done += 1
            else:
                raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1/0 or 0/1): %r"
                                 % (path, no, nn, old[:80]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, done, len(eds)))


def apply_text(cur, eds):
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            cur = cur.replace(anchor, before + anchor + after)
        else:
            cur = cur.replace(e[1], e[2])
    return cur


def revert_text(cur, eds):
    for e in reversed(eds):
        if e[0] == "ins":
            _, anchor, before, after = e
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        else:
            cur = cur.replace(e[2], e[1])
    return cur


def need(path, text, want, n=1):
    if text.count(want) != n:
        raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, want[:90], text.count(want), n))


def prereq(texts):
    # r107f/r128b must be in the tree this patch is laid on
    need(LAY, texts[LAY], "#define CAUSTICS_FLAG_WORLD 256u\n")
    need(LAY, texts[LAY], "#define CAUSTICS_W_BED_PUDDLE 38\n")
    need(COMP, texts[COMP], "float Pattern(vec2 xz, float speed) {\n")
    need(VC_CPP, texts[VC_CPP], "Water caustics (r128b): sun and moon strength")
    need(VC_CPP, texts[VC_CPP], "void Caustics::Refresh() {")
    need(SH, texts[SH], "graphics_water_caustics_lamps_strength")


def texts_check(texts):
    lay, comp, par, vh, cpp, sh, sc, tc, ts, rd = (texts[p] for p in ORDER)
    # layout
    need(LAY, lay, "#define CAUSTICS_FLAG_MOTION 512u\n")
    need(LAY, lay, "#define CAUSTICS_W_MOTION_WATER 39\n")
    need(LAY, lay, "#define CAUSTICS_MOTION_WORDS 104\n")
    need(LAY, lay, "#define CAUSTICS_SLOT_WORDS 168\n")
    # the shader: every use of the flag, the pattern's two lines, the shared counter, the shimmer
    need(COMP, comp, "CAUSTICS_FLAG_MOTION) != 0u", 4)  # Pattern, shimmer, group_ring clear, flush
    need(COMP, comp, "float WaveAt(vec2 xz, out vec2 g) {\n")
    need(COMP, comp, "float Focus(float lap) {\n")
    need(COMP, comp, "    return net * c;")
    need(COMP, comp, "    return 0.5 * (pow(r1", 0)
    need(COMP, comp, "float Pattern(vec2 xz, float speed) {\n")
    need(COMP, comp, "shared uint group_ring;")
    need(COMP, comp, "const uint mo_kind = Motion(CAUSTICS_MOTION_KIND);")
    need(COMP, comp, "group_ring = 0u;")
    need(COMP, comp, "atomicAdd(group_counts[CAUSTICS_W_MOTION_WATER], 1u);")
    need(COMP, comp, "barrier()", 2)
    if not (0 <= comp.find("float WaveAt(") < comp.find("float Pattern(") < comp.find("vec3 added = vec3(0.0)")):
        raise SystemExit("text check: WaveAt, Pattern and the shimmer are out of order in caustics.comp")
    if not (0 <= comp.find("uint Motion(uint i)") < comp.find("float WaveAt(") < comp.find("float Focus(")):
        raise SystemExit("text check: Motion, WaveAt, Focus out of order in caustics.comp")
    # the params header
    need(PAR, par, "namespace Motion {\n")
    need(PAR, par, "} // namespace Motion\n")
    need(PAR, par, "inline std::uint32_t FlagsOf(float strength, bool dispatching) {")
    need(PAR, par, "inline void WriteBlock(std::uint32_t* b, const State& s, std::uint32_t kind, float strength) {")
    need(PAR, par, "inline Sample Eval(const std::uint32_t* b, double x, double z) {")
    if not (0 <= par.find("inline float SettingOf(") < par.find("namespace Motion {") < par.find("inline float Pattern(float x, float z")):
        raise SystemExit("text check: Motion is not between SettingOf and Pattern in caustics_params.h")
    # the host
    need(VH, vh, "::BbCaustics::Motion::State motion;")
    need(VH, vh, "bool told_motion = false;")
    need(VC_CPP, cpp, "BC::Slots * BC::Motion::Words * sizeof(u32);")
    need(VC_CPP, cpp, "MotionIn MotionNow() {")
    need(VC_CPP, cpp, "BC::Motion::FlagsOf(motion_strength, draw || lamp_draw || puddle_pass)")
    need(VC_CPP, cpp, "if (motion_strength > 0.0f) { // bbport (r130b_water-moves)")
    need(VC_CPP, cpp, "BbEngine::world_player_position(feet)")
    need(VC_CPP, cpp, "Water motion (r130b)", 3)
    for i, line in enumerate(cpp.split("\n")):
        if "Water motion" in line and "Water motion (r130b)" not in line:
            raise SystemExit("text check: a Water motion log line without the prefix: %r" % line)
    need(VC_CPP, cpp, "push.flags |= motion_flag;")
    if not (0 <= cpp.find("push.slot = dispatches % BC::Slots;") < cpp.find("push.flags |= motion_flag;")
            < cpp.find("slot_camera_y[push.slot] = camera.inv_view[7];")):
        raise SystemExit("text check: the motion block is not between the slot and the camera y")
    # settings
    need(SH, sh, "std::atomic<float> graphics_water_motion_strength{WaterMotionStrengthDefault};")
    need(SC, sc, 'key == "graphics_water_motion_strength"')
    need(SC, sc, 'put("graphics_water_motion_strength"')
    # tests
    need(TC, tc, "bbport (r130b_water-moves): the moving water")
    need(TS, ts, "bbport (r130b_water-moves): the moving water's strength.")
    # README: one row
    rows = [l for l in rd.split("\n") if l.startswith("| `graphics_water_motion_strength`")]
    if len(rows) != 1 or not rows[0].endswith("| `0` |"):
        raise SystemExit("text check: README row of graphics_water_motion_strength")


def new_lines_check():
    # every new C++/GLSL line: no tab, ASCII, at most 150 columns (README lines are tables, exempt)
    for path in CODE:
        for e in EDITS[path]:
            for text in (e[1:] if e[0] == "ins" else e[2:]):
                for line in text.split("\n"):
                    if "\t" in line or any(ord(ch) > 127 for ch in line) or len(line) > 150:
                        raise SystemExit("new line check: %s: %r" % (path, line[:100]))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (no engine/gpu; set R130B_ROOT)" % ROOT)
    new_lines_check()
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state, nothing written: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    if state == "clean":
        prereq({p[0]: p[4] for p in plan})

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_text(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            texts_check({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            texts_check(applied_texts())
            print("not applied; would apply (%d files, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        texts_check(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(ROOT, path) + TMP, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            os.replace(full + TMP, full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_text(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path in out:
        open(os.path.join(ROOT, path) + TMP, "wb").write(out[path])
    for path in out:
        full = os.path.join(ROOT, path)
        os.replace(full + TMP, full)
    print("reverted")


main()
