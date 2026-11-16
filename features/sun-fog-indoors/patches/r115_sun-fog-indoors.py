# r115_sun-fog-indoors: FEATURE patch (sun fog indoors, the owner's rules of 2026-11-15: "The sun fog
# shouldn't go indoors at all", keep "the shafts from the sun through the window", and it must work
# without ray tracing). OFF by default: a new value `2` of the existing knob BB_VOLUMETRIC_AREA_GATE
# (r81, r85; unset, `0` and other text off, `1` exactly r85 as before). The knob is now read live
# (BbLiveKnobs, as AreaViewKnob and the wind's contrast already are), so one slot game can show
# off / 1 / 2 at the same spot. The live read is r84's TOOL (bbport_live_knobs.h, branch
# dev/test-tools): on the feature branch VolumetricLight::AreaMode reads the variable once, as
# VolumetricOcclusion's knobs do there.
#
# REVIEWED 2026-11-15 (adversarial review; this .fixed.py replaces the draft r115_sun-fog-indoors.py):
#  - the DUAL march split the open energy as e * GateOpenAt with e already multiplied by GateAt, so
#    every partly filtered cell counted the first gate twice (a one-cell-wide shaft kept about 2/3
#    of its light, at the cell edges less); now open = e * clamp(GateOpenAt / GateAt, 0, 1), which
#    is the atlas energy times the wider answer (the wider answer is never more open than the first);
#  - the camera pass's "every point near" fallback brought the hunter back exactly where the near
#    rule matters (looking up outdoors: the hunter and the sky only); now a grid with sky and no far
#    surface weighs 1 (r81's "no surface"), and only a grid of near surfaces without sky counts them;
#  - AREA_NEAR_METRES 4 -> 5: the hunter's carried lamp was measured 3.8 m from the camera
#    (dream-house) and the camera sits about 1.4 m above his feet, so 4 m left half of him and the
#    ground at his feet in the camera's light sets;
#  - comments, README and the 600-march line say the exact rule (the #error guard, the r85 fallback
#    cases, the cost of `1` and the sampler read of `2`).
#
# Why (data on file, S/slot_r81_result.txt, S/slot_r85_result.txt, context file sections r81-r85):
#  (1) the area gate's camera weight is pulled down OUTDOORS by grid points near the camera whose
#      light set has no sun in light 0 (lamp-test-spot 0.83 -> 0.43, church-puddles 0.91 -> 0.28 when
#      looking up, with 15-42 such points; graveyard 0.82): most likely the hunter himself (the
#      1 - depth weighting makes a point 3 m away count about ten times a wall at 30 m). That is the
#      outdoor fog loss of r81 (fog kept 71-92 %) and r85's 10 % dimming at the graveyard.
#  (2) with ray tracing, r85 weighs ALL lit air by the light sets, open sky included; r76's tests
#      showed that the ray traced scene WITH the camera's geometry (mask 3) knows exactly which air
#      is open (outdoors in the open, a real window beam) but also shuts outdoor air in a building's
#      shadow (graveyard), where the light sets have sun.
# What `2` changes (everything else is r81/r85 as it is):
#  (a) "near rule", with or without ray tracing: the march's AREA builds mark a surface nearer than
#      5 m (AREA_NEAR_METRES) by b's sign (b = -(b + 2^-14)); the camera pass leaves those grid points
#      out of the camera's weight (no far surface: 1 when the grid sees sky, else every point counts,
#      as before), and the apply pass weighs such a pixel's ray (the fog in front of the hunter) with
#      the camera's weight, not its own set.
#  (b) "dual gate", only on a march with the ray traced sun gate (and not with the fog noise, the
#      gate probe or the gate view, which keep r85's rule plus (a)): the gate pass's DUAL build traces
#      a second ray from each cell the first ray (BB_VOLUMETRIC_RT_GATE's mask, 1 by default) leaves
#      open, with the camera's geometry too (mask | 2), into a second 160x90x32 R8 image; the march's
#      DUAL build keeps the energy that this wider answer lets through in b (kept whole by the apply
#      pass: open air, beams through real openings), and only the energy it shuts (rooms whose roof
#      only the camera's geometry holds; outdoor air in a building's shadow) goes to r/g, which the
#      light sets weigh, without r81's beam test (the ray traced scene already says what is a beam).
# Expected (not seen): church hall like gate 3 (records weight 0), library (mod off) cleared further
# than r85, graveyard about as gate 1 (its sets have sun; the hunter no longer counts), outdoor open
# places (lamp-test-spot, church-puddles, dark-alley) unchanged exactly where the wider ray is open.
#
# Off and `1`: nothing new runs. The default builds (plain, GATE, NOISE, WIND, GATE_VIEW, DIAG, the
# gate's own, TINT, FILTER, COMPOSITE) compile to the same SPIR-V words (all new GLSL is inside
# #ifdef DUAL or #ifdef AREA); the AREA builds and the area gate's two passes change, but with `1`
# the push bit (AREA_NEAR_MARK, bit 24 of `cascades`) and the flags (FlagNear, FlagDual) are 0 and
# every changed expression reduces to the one before (argued in the comments; checked by hand).
# With `1` the camera pass also sums one vec4 more over its 256 points (one workgroup, well under a
# microsecond); off, nothing of it runs.
# Cost with `2`: CPU a few branches a march; GPU, with ray tracing, one more ray per cell the first
# leaves open (at most 460,800; the gate row was 0.022 ms with mask 1 and 0.075 ms with mask 3 at
# lamp-test-spot in round 2) and one more gate read per lit march sample, estimate +0.05 to 0.15 ms,
# not measured; memory 460,800 bytes (the image) plus three pipelines. Without ray tracing: nothing
# measurable (a few compares a pixel).
#
# Files: volumetric_rt_gate.comp (DUAL build), volumetric_light.comp (DUAL build, the near mark at
# the AREA store), volumetric_area_gate.comp (near rule, dual apply, probe), volumetric_area_layout.h,
# volumetric_area_gate.h (ParseMode, NearMarked, Unmarked, ApplyMode2), vk_volumetric_light.h/.cpp
# (AreaMode, DualReady, SayAreaMode, SayAreaNearProbe, RecordGate, Integrate, AreaGate,
# ReadAreaProbe), CMakeLists.txt (three builds after r85's), test_volumetric_area_gate.cpp,
# test_effect_pipelines.cpp (the two DUAL march builds), README.md (the knob's row).
#
# Use: python -I -X utf8 r115_sun-fog-indoors.py check | apply | revert
# Root: R115_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals
# up in r115_backup next to this script. Insert edits keep their anchor and are found by their own
# text on revert; replace edits swap an exact old text for an exact new one (each once).
import os, sys

ROOT = os.environ.get("R115_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r115_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
G = HS + "volumetric_rt_gate.comp"
L = HS + "volumetric_light.comp"
A = HS + "volumetric_area_gate.comp"
Y = HS + "volumetric_area_layout.h"
Q = RV + "volumetric_area_gate.h"
H = RV + "vk_volumetric_light.h"
C = RV + "vk_volumetric_light.cpp"
M = "engine/gpu/CMakeLists.txt"
T = "engine/tests/test_volumetric_area_gate.cpp"
P = "engine/tests/test_effect_pipelines.cpp"
R = "README.md"
FILES = (G, L, A, Y, Q, H, C, M, T, P, R)

def ins(anchor, before="", after=""):
    return ("ins", anchor, before, after)

def rep(old, new):
    # a replacement that only adds text around the old one is an insert (its state reads cleanly)
    if old in new:
        i = new.index(old)
        return ins(old, new[:i], new[i + len(old):])
    assert new not in old, old[:60]
    return ("rep", old, new)

EDITS = {}

# ---------------------------------------------------------------- volumetric_rt_gate.comp
EDITS[G] = [
ins("layout(binding = 4, r8) uniform writeonly image2D gate_first;\n", after=
"""#ifdef DUAL
// bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE=2 only (VolumetricLight::DualReady): the
// wider answer, a second ray from each cell the first ray leaves open, with the push word's bits
// 16-23 as its instance mask (the first one's mask and the camera's geometry): 1 where it too left
// the scene, 0 where either ray hit (the march's DUAL build keeps what it lets through whole)
#ifdef DIAG
#error DUAL is not built with DIAG
#endif
layout(binding = 5, r8) uniform writeonly image3D gate_open;
#endif
"""),
ins("    float open = 1.0;\n", after=
"""#ifdef DUAL
    float open_wider = 1.0; // bbport (r115_sun-fog-indoors): open where nothing can be asked too
#endif
"""),
ins("""            open = rayQueryGetIntersectionTypeEXT(query, true) ==
                           gl_RayQueryCommittedIntersectionNoneEXT
                       ? 1.0
                       : 0.0;
""", after=
"""#ifdef DUAL
            // bbport (r115_sun-fog-indoors): the wider ray only from a cell the first left open (a
            // cell the first shut is shut for both); the first ray's cull mask took the low 8 bits
            open_wider = open;
            if (open != 0.0) {
                rayQueryEXT wider;
                rayQueryInitializeEXT(wider, scene,
                                      gl_RayFlagsTerminateOnFirstHitEXT | gl_RayFlagsOpaqueEXT,
                                      (mask >> 16) & 255u, p, 0.02, shared_direction, max_distance);
                rayQueryProceedEXT(wider);
                open_wider = rayQueryGetIntersectionTypeEXT(wider, true) ==
                                     gl_RayQueryCommittedIntersectionNoneEXT
                                 ? 1.0
                                 : 0.0;
            }
#endif
"""),
ins("    if (inside) imageStore(gate_out, cell, vec4(open));\n", after=
"""#ifdef DUAL
    if (inside) imageStore(gate_open, cell, vec4(open_wider)); // bbport (r115_sun-fog-indoors)
#endif
"""),
]

# ---------------------------------------------------------------- volumetric_light.comp
EDITS[L] = [
ins("""#ifdef REPAIR
layout(binding = 8) uniform sampler2D sun_gate_first;
#else
layout(binding = 7) uniform sampler2D sun_gate_first;
#endif
""", after=
"""#ifdef DUAL
// bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE=2 on a march with the ray traced gate (a
// build of the GATE+AREA march, never with the fog noise): the gate's wider answer, 1 where a ray
// from the cell toward the sun left the scene with the camera's geometry in it too
// (volumetric_rt_gate.comp's DUAL build)
#if !(defined(GATE) && defined(AREA)) || defined(NOISE)
#error DUAL is a build of the GATE+AREA march without NOISE
#endif
#ifdef REPAIR
layout(binding = 9) uniform sampler3D sun_gate_open;
#else
layout(binding = 8) uniform sampler3D sun_gate_open;
#endif
#endif
"""),
ins("""// bbport (r51_volumetric-leak): the bits of BB_VOLUMETRIC_OCCLUSION the shader reads.
const uint OcclusionDarkest = 2u, OcclusionRobust = 4u;
""", before=
"""#ifdef DUAL
// bbport (r115_sun-fog-indoors): an INTEGRATE or REPAIR build with DUAL but without GATE (the GATE
// block above holds the test for those with GATE); TINT, FILTER and COMPOSITE never read DUAL
#if !(defined(GATE) && defined(AREA)) || defined(NOISE)
#error DUAL is a build of the GATE+AREA march without NOISE
#endif
#endif
"""),
ins("""float GateAt(vec2 uv, float t, float range) {
    return textureLod(sun_gate, vec3(uv, sqrt(clamp(t / range, 0.0, 1.0))), 0.0).r;
}
""", after=
"""#ifdef DUAL
// bbport (r115_sun-fog-indoors): the wider answer at the same place, filtered as GateAt
float GateOpenAt(vec2 uv, float t, float range) {
    return textureLod(sun_gate_open, vec3(uv, sqrt(clamp(t / range, 0.0, 1.0))), 0.0).r;
}
#endif
"""),
ins("        area_lit += v * (float(steps) / float(steps - first_step));\n",
 before="#ifndef DUAL // bbport (r115_sun-fog-indoors): r85's share in sun; a DUAL build keeps the open energy\n",
 after="#endif // (r115_sun-fog-indoors) not DUAL\n"),
rep("""        if (v > 0.0) v *= GateAt(uv, t, gate_range);
        float e = exp(-density * t) * density * ds * v;
#ifdef NOISE
        e *= fog_noise_weight(v, ray * t, t); // bbport (r94_fog-noise): m where lit
#endif
""", """#ifdef DUAL
        // bbport (r115_sun-fog-indoors): the first ray's answer kept for the split below (the same
        // multiply as the line in #else)
        const float gate_first_ray = v > 0.0 ? GateAt(uv, t, gate_range) : 0.0;
        v *= gate_first_ray;
#else
        if (v > 0.0) v *= GateAt(uv, t, gate_range);
#endif
        float e = exp(-density * t) * density * ds * v;
#ifdef DUAL
        // bbport (r115_sun-fog-indoors): the part of the sample the wider answer lets through (open
        // air, a beam through a real opening) in area_lit, kept whole; the rest (shut only by the
        // camera's geometry: a room, or outdoor air in a building's shadow) in near and far, which
        // the light sets weigh. e already holds the first answer, so the wider one enters as its
        // share of it (each cell of the wider answer is at most as open as the first's, so the
        // filtered share lies in 0..1; the clamp only guards the r105 clouds, which dim the first
        // answer alone): open = the atlas's energy times the wider answer. e > 0 implies a first
        // answer above 0.
        float open_e = e > 0.0 ? e * clamp(GateOpenAt(uv, t, gate_range) / gate_first_ray, 0.0, 1.0)
                               : 0.0;
        area_lit += open_e;
        e -= open_e;
#endif
#ifdef NOISE
        e *= fog_noise_weight(v, ray * t, t); // bbport (r94_fog-noise): m where lit
#endif
"""),
ins("""    imageStore(fog_out, px, vec4(strength * phase * area_near, strength * phase * area_far,
""", before=
"""#ifdef DUAL
    float area_b = strength * phase * area_lit; // bbport (r115_sun-fog-indoors): the open energy
#else
    float area_b = area_lit / float(steps);
#endif
    // bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE=2 (AREA_NEAR_MARK in `cascades`, 0
    // otherwise): a surface nearer than AREA_NEAR_METRES (the hunter, the ground at his feet) is
    // marked by b's sign, b = -(b + AREA_NEAR_FLOOR); volumetric_area_gate.comp leaves it out of the
    // camera's light sets and weighs its own ray with the camera's
    if ((cascades & AREA_NEAR_MARK) != 0u && !sky && distance_to_surface < float(AREA_NEAR_METRES)) {
        area_b = -(area_b + float(AREA_NEAR_FLOOR));
    }
"""),
rep("""                                 area_lit / float(steps), 1.0 - depth));
""", """                                 area_b, 1.0 - depth)); // (r115) b
"""),
]

# ---------------------------------------------------------------- volumetric_area_gate.comp
EDITS[A] = [
rep("""    s_a[id] = surface ? fog.a * here : 0.0;
    s_b[id] = surface ? fog.a : 0.0;
    if (probe && records && surface) atomicAdd(s_count[record], 1u);
    for (uint stride = AREA_GROUP / 2u; stride > 0u; stride >>= 1u) {
        barrier();
        if (id < stride) {
            s_a[id] += s_a[id + stride];
            s_b[id] += s_b[id + stride];
        }
    }
    barrier();
    if (id == 0u) {
        const float now = s_b[0] > AREA_CAMERA_EPS ? clamp(s_a[0] / s_b[0], 0.0, 1.0) : 1.0;
""", """    // bbport (r115_sun-fog-indoors): with AREA_FLAG_NEAR a point the march marked as near (b < 0:
    // the hunter, the ground at his feet) is left out; s_v keeps the sums over every surface, the
    // near points' count and the sky points' count. No surface left: 1 when the grid sees sky (as
    // r81's grid of sky alone; outdoors looking up, the hunter is then the only surface), else the
    // sums over every surface (a small room whose walls are all near). Without the flag nothing is
    // left out and s_v's sums equal s_a's and s_b's, so the weight is the one before.
    const bool near = (flags & AREA_FLAG_NEAR) != 0u && fog.b < 0.0;
    s_a[id] = surface && !near ? fog.a * here : 0.0;
    s_b[id] = surface && !near ? fog.a : 0.0;
    s_v[id] = vec4(surface ? fog.a * here : 0.0, surface ? fog.a : 0.0, surface && near ? 1.0 : 0.0,
                   fog.a == 0.0 ? 1.0 : 0.0);
    if (probe && records && surface) atomicAdd(s_count[record], 1u);
    for (uint stride = AREA_GROUP / 2u; stride > 0u; stride >>= 1u) {
        barrier();
        if (id < stride) {
            s_a[id] += s_a[id + stride];
            s_b[id] += s_b[id + stride];
            s_v[id] += s_v[id + stride];
        }
    }
    barrier();
    if (id == 0u) {
        const float now = s_b[0] > AREA_CAMERA_EPS ? clamp(s_a[0] / s_b[0], 0.0, 1.0)
                          : s_v[0].w < 0.5 && s_v[0].y > AREA_CAMERA_EPS
                              ? clamp(s_v[0].x / s_v[0].y, 0.0, 1.0)
                              : 1.0;
"""),
ins("        state.w[AREA_STATE_RECORD_COUNT] = records ? record_count : 0u;\n", after=
"        state.w[AREA_STATE_NEAR] = uint(s_v[0].z + 0.5); // bbport (r115_sun-fog-indoors)\n"),
rep("""    const float camera = s_camera;
    const float keep = BeamKeep(fog.b);
    const float end = fog.a == 0.0 ? camera : here;
    const float before = fog.r + fog.g;
    const float after = fog.r * Segment(camera, keep) + fog.g * Segment(end, keep);
    s_v[id] = vec4(before, after, fog.b * before, fog.a == 0.0 ? 1.0 : 0.0);
""", """    const float camera = s_camera;
    // bbport (r115_sun-fog-indoors): b without the near mark; after a DUAL march b is the energy the
    // wider answer keeps (counted before and after, and the lit share is then its share of the fog)
    const float lit_b = fog.b < 0.0 ? max(-fog.b - float(AREA_NEAR_FLOOR), 0.0) : fog.b;
    const bool dual = (flags & AREA_FLAG_DUAL) != 0u;
    const float keep = BeamKeep(lit_b);
    const float end = fog.a == 0.0 || near ? camera : here;
    const float before = fog.r + fog.g + (dual ? lit_b : 0.0);
    const float after = dual ? lit_b + fog.r * camera + fog.g * end
                             : fog.r * Segment(camera, keep) + fog.g * Segment(end, keep);
    s_v[id] = vec4(before, after, dual ? lit_b : lit_b * before, fog.a == 0.0 ? 1.0 : 0.0);
"""),
rep("""    float end = camera;
    if (v.a != 0.0 && (flags & AREA_FLAG_RECORDS) != 0u) {
        end = uintBitsToFloat(state.w[AREA_STATE_WEIGHTS +
                                      RecordAt(record_tex, (vec2(px) + 0.5) / vec2(size))]);
    }
    const float keep = BeamKeep(v.b);
    const float fog = v.r * Segment(camera, keep) + v.g * Segment(end, keep);
""", """    float end = camera;
    // bbport (r115_sun-fog-indoors): with AREA_FLAG_NEAR the ray to a near surface (b < 0: the
    // hunter, the ground at his feet) is weighed by the camera's light sets, not its own; b without
    // the mark (a b >= 0 is as it was)
    const bool near = (flags & AREA_FLAG_NEAR) != 0u && v.b < 0.0;
    const float b = v.b < 0.0 ? max(-v.b - float(AREA_NEAR_FLOOR), 0.0) : v.b;
    if (v.a != 0.0 && (flags & AREA_FLAG_RECORDS) != 0u && !near) {
        end = uintBitsToFloat(state.w[AREA_STATE_WEIGHTS +
                                      RecordAt(record_tex, (vec2(px) + 0.5) / vec2(size))]);
    }
    const float keep = BeamKeep(b);
    // bbport (r115_sun-fog-indoors): after a DUAL march b is the energy the ray traced gate's wider
    // answer lets through, kept whole, and the light sets weigh the rest without the beam test
    const float fog = (flags & AREA_FLAG_DUAL) != 0u
                          ? b + v.r * camera + v.g * end
                          : v.r * Segment(camera, keep) + v.g * Segment(end, keep);
"""),
]

# ---------------------------------------------------------------- volumetric_area_layout.h
EDITS[Y] = [
ins("#define AREA_FLAG_PROBE 2u\n", after=
"""// bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE=2. With bit AREA_NEAR_MARK of the march's
// push word `cascades` its AREA builds mark a surface nearer than AREA_NEAR_METRES by b's sign,
// b = -(b + AREA_NEAR_FLOOR) (the smallest normal half float, so a b of 0 stays negative in the fog
// image); with AREA_FLAG_NEAR the camera pass leaves those points out of the camera's weight (none
// left: 1 when the grid sees sky, else every point counts) and the apply pass weighs their rays
// with the camera's weight. 5 m: the hunter's carried lamp is 3.8 m from the camera and the camera
// about 1.4 m above his feet. AREA_FLAG_DUAL: the march was a DUAL build (b is the energy the ray
// traced gate's wider answer lets through, kept whole; no beam test).
#define AREA_FLAG_NEAR 4u
#define AREA_FLAG_DUAL 8u
#define AREA_NEAR_METRES 5.0
#define AREA_NEAR_FLOOR 6.103515625e-05
#define AREA_NEAR_MARK 0x1000000u
"""),
ins("#define AREA_STATE_RECORD_COUNT 8u  // uint: records weighed\n", after=
"#define AREA_STATE_NEAR 9u          // uint: grid surface points left out as near (r115, probe)\n"),
]

# ---------------------------------------------------------------- volumetric_area_gate.h
EDITS[Q] = [
rep("""// BB_VOLUMETRIC_AREA_GATE, read once (at the first march): "1" on, anything else (unset too) off. On, every
""", """// BB_VOLUMETRIC_AREA_GATE (bbport (r115_sun-fog-indoors): read live, VolumetricLight::AreaMode with
// ParseMode below): "1" r81's and r85's rule, "2" with r115's changes (ParseMode), anything else
// (unset too) off. On, every
"""),
ins("""inline float CameraWeight(float weighted, float sum) {
    return sum > CameraEps ? std::clamp(weighted / sum, 0.0f, 1.0f) : 1.0f;
}
""", after="""
/// bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE's text as the engine reads it (live):
/// "1" r81's and r85's rule; "2" the same with (a) surfaces nearer than NearMetres (the hunter, the
/// ground at his feet) left out of the camera's light sets and their rays weighed by the camera's,
/// and (b) on a march with the ray traced sun gate the gate's wider answer (a second ray that sees
/// the camera's geometry too) keeping what it lets through whole, the light sets weighing only the
/// rest; anything else 0 (off). Parse and On keep r81's reading ("1" only).
inline std::uint32_t ParseMode(const char* text) {
    if (!text || (text[0] != '1' && text[0] != '2') || text[1] != '\\0') {
        return 0;
    }
    return std::uint32_t(text[0] - '0');
}
inline constexpr float NearMetres = float(AREA_NEAR_METRES), NearFloor = float(AREA_NEAR_FLOOR);
inline constexpr std::uint32_t FlagNear = AREA_FLAG_NEAR, FlagDual = AREA_FLAG_DUAL;
inline constexpr std::uint32_t NearMark = AREA_NEAR_MARK, StateNear = AREA_STATE_NEAR;
static_assert(NearMark == 1u << 24, "above VolumetricOcclusion::Pack's 24 bits");
static_assert(((FlagRecords | FlagProbe) & (FlagNear | FlagDual)) == 0 && FlagNear != FlagDual);
static_assert(StateNear > AREA_STATE_RECORD_COUNT && StateNear < AREA_STATE_WEIGHTS);
static_assert(NearMetres > 0.0f && NearFloor > 0.0f && NearFloor < 1e-4f);

/// The march's near mark of b (volumetric_light.comp) and b without it (volumetric_area_gate.comp).
inline float NearMarked(float b) {
    return -(b + NearFloor);
}
inline float Unmarked(float b) {
    return b < 0.0f ? std::max(-b - NearFloor, 0.0f) : b;
}

/// The camera's weight with "2" (the camera pass): the far surfaces' sums (weight times 1 - depth,
/// and 1 - depth) when there are any; else 1 when the grid sees sky, else the sums over every
/// surface, near ones too (all_weighted, all_sum).
inline float CameraWeightNear(float weighted, float sum, float all_weighted, float all_sum,
                              bool sky) {
    if (sum > CameraEps) {
        return CameraWeight(weighted, sum);
    }
    return sky ? 1.0f : CameraWeight(all_weighted, all_sum);
}

/// The fog a pixel keeps with "2" (the apply pass): a marked b (a near surface) takes the camera's
/// weight for its whole ray; after a DUAL march b is kept whole and no beam test is made.
inline float ApplyMode2(float near_energy, float far_energy, float marked_b, float camera, float end,
                        bool dual) {
    const float b = Unmarked(marked_b);
    const float own = marked_b < 0.0f ? camera : end;
    return dual ? b + near_energy * camera + far_energy * own
                : Apply(near_energy, far_energy, b, camera, own);
}
"""),
]

# ---------------------------------------------------------------- vk_volumetric_light.h
EDITS[H] = [
rep("""    const Pass& AreaPass(bool gated, bool repairing) const {
        return gated ? (repairing ? repair_gated_area : integrate_gated_area)
""", """    const Pass& AreaPass(bool gated, bool repairing, bool dual = false) const {
        if (dual) { // bbport (r115_sun-fog-indoors): a DUAL march (DualReady made them)
            return repairing ? repair_dual : integrate_dual;
        }
        return gated ? (repairing ? repair_gated_area : integrate_gated_area)
"""),
ins("    bool area_probe_pending = false;\n", after=
"""    // bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE read live (AreaMode: 0 off, 1 r81 and
    // r85, 2 r115); DualReady makes at the first DUAL march the gate's DUAL build, the march's two
    // DUAL builds and the wider answer's image (160x90x32 bytes); RecordGate traces the DUAL build
    // while gate_dual_on; the flags the last Integrate left for AreaGate and the probe's; the mode
    // last said and the counts of the 600-march line (SayAreaMode); the probe's near line
    static u32 AreaMode();
    bool DualReady();
    void SayAreaMode(u32 mode, bool area, bool gated, bool dual);
    void SayAreaNearProbe(const u32* words);
    Pass gate_dual, integrate_dual, repair_dual;
    VideoCore::UniqueImage gate_open;
    vk::UniqueImageView gate_open_view;
    bool dual_tried = false, dual_failed = false, gate_dual_on = false;
    bool area_near_pending = false, area_dual_pending = false;
    u32 area_probe_flags = 0, area_mode_seen = ~0u;
    u64 r115_marches = 0, r115_area = 0, r115_dual = 0, r115_plain = 0;
"""),
]

# ---------------------------------------------------------------- vk_volumetric_light.cpp
DUAL_READY = r'''
// bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE as the engine reads it, live (the live
// knobs file of a test run may change it between two marches): 0 off, 1 r81's and r85's rule, 2 with
// r115's (VolumetricAreaGate::ParseMode). The live read is r84's TOOL (dev/test-tools); on the
// feature branch it is `static const u32 mode = ParseMode(std::getenv(...))`.
u32 VolumetricLight::AreaMode() {
    static BbLiveKnobs::Knob<u32> mode{"BB_VOLUMETRIC_AREA_GATE", VolumetricAreaGate::ParseMode};
    return mode.Get();
}

// bbport (r115_sun-fog-indoors): made at the first march of BB_VOLUMETRIC_AREA_GATE=2 with the ray
// traced gate and the area gate (after GateReady, AreaReady and AreaGatedReady): the gate's DUAL
// build (its own bindings, then the wider answer at binding 5), the march's two DUAL builds (the
// AREA+GATE bindings, then the wider answer) and the wider answer's image, as the gate's. Failing
// leaves those marches with r85's rule (and the near rule).
static_assert((VolumetricOcclusion::Pack(4u, 0xFu, 0xFFu) & VolumetricAreaGate::NearMark) == 0u,
              "the near mark lies above the march's cascade word");
bool VolumetricLight::DualReady() {
    if (dual_tried) {
        return !dual_failed;
    }
    dual_tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::HasRoom(instance, u64(GateWidth) * GateHeight * GateSlices) &&
        CreatePass(gate_dual,
                   {eStorageBuffer, eStorageBuffer, eAccelerationStructureKHR, eStorageImage,
                    eStorageImage, eStorageImage},
                   VOLUMETRIC_RT_GATE_DUAL_COMP, sizeof(GateParams), "Volumetric sun gate (dual)") &&
        CreatePass(integrate_dual,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler,
                    eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_INTEGRATE_GATE_AREA_DUAL_COMP, sizeof(Params),
                   "Volumetric integrate (gate, area gate, dual)") &&
        CreatePass(repair_dual,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
                    eCombinedImageSampler, eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_DUAL_COMP, sizeof(Params),
                   "Volumetric repair (gate, area gate, dual)");
    if (!made) {
        dual_failed = true;
        std::printf("Volumetric lighting (r115): the dual sun gate could not be made; marches with "
                    "the ray traced gate keep r85's rule with the near rule\n");
        return false;
    }
    const auto device = instance.GetDevice();
    gate_open = VideoCore::UniqueImage(device, instance.GetAllocator());
    gate_open.Create({
        .imageType = vk::ImageType::e3D,
        .format = vk::Format::eR8Unorm,
        .extent = {GateWidth, GateHeight, GateSlices}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    gate_open_view = Check<"create volumetric sun gate wider view">(device.createImageViewUnique({
        .image = vk::Image(gate_open), .viewType = vk::ImageViewType::e3D,
        .format = vk::Format::eR8Unorm, .subresourceRange = ColorRange,
    }));
    SetObjectName(device, vk::Image(gate_open), "Volumetric sun gate: wider answer (r115)");
    std::printf("Volumetric lighting (r115): dual sun gate made: a second ray from each of the "
                "%ux%ux%u cells the first leaves open, mask 0x%x, and the march's dual builds\n",
                GateWidth, GateHeight, GateSlices,
                VolumetricOcclusion::GateRayMask(sun_scene_mask | 2u,
                                                 VolumetricOcclusion::GateShells().on));
    return true;
}

// bbport (r115_sun-fog-indoors): once a march with the volumetric sunlight on: the mode when it
// changes (the rule once when it is 2), and while it is 2 every 600 marches how many were area gate
// marches and of them how many had the dual gate, no ray traced gate (light sets and the near rule)
// or the ray traced gate with r85's rule (fog noise or gate probe on, or the dual gate not made).
void VolumetricLight::SayAreaMode(u32 mode, bool area, bool gated, bool dual) {
    if (mode != area_mode_seen) {
        if (mode == 2) {
            std::printf("Volumetric lighting (r115): BB_VOLUMETRIC_AREA_GATE 2: surfaces nearer than "
                        "%.0f m leave the camera's light sets and take its weight; with the ray "
                        "traced gate a second ray per cell (camera geometry too) keeps open air and "
                        "window beams whole, the light sets weigh what it shuts\n",
                        double(VolumetricAreaGate::NearMetres));
        } else if (area_mode_seen != ~0u) {
            std::printf("Volumetric lighting (r115): BB_VOLUMETRIC_AREA_GATE now %u (live knobs)\n",
                        mode);
        }
        area_mode_seen = mode;
        r115_marches = r115_area = r115_dual = r115_plain = 0;
    }
    if (mode != 2) {
        return;
    }
    r115_area += area ? 1 : 0;
    r115_dual += dual ? 1 : 0;
    r115_plain += area && !gated ? 1 : 0;
    if (++r115_marches % 600 == 0) {
        std::printf("Volumetric lighting (r115): area gate 2 on %llu of 600 marches: %llu with the "
                    "dual ray traced gate, %llu without ray tracing, %llu with the ray traced gate "
                    "as r85 (fog noise, gate probe or no dual gate)\n",
                    static_cast<unsigned long long>(r115_area),
                    static_cast<unsigned long long>(r115_dual),
                    static_cast<unsigned long long>(r115_plain),
                    static_cast<unsigned long long>(r115_area - r115_dual - r115_plain));
        r115_area = r115_dual = r115_plain = 0;
    }
}

// bbport (r115_sun-fog-indoors): after r81's probe line of a march with the near mark: how many of
// the grid's surface points were near and left out of the camera's weight.
void VolumetricLight::SayAreaNearProbe(const u32* w) {
    std::printf("Volumetric lighting (r115): area gate probe: %u of %u surface points of the grid "
                "nearer than %.0f m left out of the camera's light sets (weight %.2f)%s\n",
                w[VolumetricAreaGate::StateNear], w[AREA_STATE_SURFACE],
                double(VolumetricAreaGate::NearMetres),
                double(std::bit_cast<float>(w[AREA_STATE_CAMERA])),
                (area_probe_flags & VolumetricAreaGate::FlagDual) != 0u
                    ? "; dual march: the sun share above is the share the wider ray keeps"
                    : "");
}
'''

EDITS[C] = [
ins('#include "video_core/host_shaders/volumetric_light_repair_area_comp.h"\n', after=
"""// bbport (r115_sun-fog-indoors): the gate's and the march's DUAL builds (BB_VOLUMETRIC_AREA_GATE=2)
#include "video_core/host_shaders/volumetric_light_integrate_gate_area_dual_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_area_dual_comp.h"
#include "video_core/host_shaders/volumetric_rt_gate_dual_comp.h"
"""),
rep("""                                diag_bits,
                            GateMaxDistance};
""", """                                diag_bits |
                                // bbport (r115_sun-fog-indoors): a DUAL gate's second mask in bits
                                // 16-23 (the first ray's cull mask takes the low 8 bits only)
                                (gate_dual_on ? VolumetricOcclusion::GateRayMask(
                                                    sun_scene_mask | 2u,
                                                    VolumetricOcclusion::GateShells().on)
                                                    << 16
                                              : 0u),
                            GateMaxDistance};
"""),
rep("""    const vk::DescriptorImageInfo band_out{{}, *gate_band_view, vk::ImageLayout::eGeneral};
""", """    // bbport (r115_sun-fog-indoors): a DUAL gate writes its wider answer at binding 5 instead
    const vk::DescriptorImageInfo band_out{{}, gate_dual_on ? *gate_open_view : *gate_band_view,
                                           vk::ImageLayout::eGeneral};
"""),
rep("""         band_image = vk::Image(gate_band),
""", """         band_image = gate_dual_on ? vk::Image(gate_open) : vk::Image(gate_band),
         dual = gate_dual_on, // bbport (r115_sun-fog-indoors)
"""),
rep("""         pipeline = diag ? *gate_diag.pipeline : *gate_volume.pipeline,
         layout = diag ? *gate_diag.layout : *gate_volume.layout](vk::CommandBuffer cmd) {
""", """         pipeline = diag           ? *gate_diag.pipeline
                    : gate_dual_on ? *gate_dual.pipeline // bbport (r115_sun-fog-indoors)
                                   : *gate_volume.pipeline,
         layout = diag           ? *gate_diag.layout
                  : gate_dual_on ? *gate_dual.layout
                                 : *gate_volume.layout](vk::CommandBuffer cmd) {
"""),
rep("""            cmd.pipelineBarrier2({.imageMemoryBarrierCount = diag ? 3u : 2u,
""", """            cmd.pipelineBarrier2({.imageMemoryBarrierCount = diag || dual ? 3u : 2u, // (r115)
"""),
rep("""                                    std::span{writes.data(), diag ? 9u : 5u});
""", """                                    std::span{writes.data(), diag ? 9u : dual ? 6u : 5u}); // (r115)
"""),
ins("""                     : "Volumetric lighting (r85): area light gate's builds for marches with the "
                       "ray traced sun gate could not be made; those marches stay without it\\n");
    return made;
}
""", after=DUAL_READY),
rep("""        (has_records ? FlagRecords : 0u) | (probing ? FlagProbe : 0u)};
""", """        (has_records ? FlagRecords : 0u) | (probing ? FlagProbe : 0u) |
            // bbport (r115_sun-fog-indoors): the last Integrate's near mark and DUAL build
            (area_near_pending ? FlagNear : 0u) | (area_dual_pending ? FlagDual : 0u)};
"""),
ins("        area_probe_light = sun_light;\n", after=
"        area_probe_flags = params.flags; // bbport (r115_sun-fog-indoors): SayAreaNearProbe\n"),
ins("    area_gated = area_marches = 0;\n", before=
"""    if ((area_probe_flags & VolumetricAreaGate::FlagNear) != 0u) {
        SayAreaNearProbe(w.data()); // bbport (r115_sun-fog-indoors)
    }
"""),
rep("""    const Params params{in.constants_offset_word, steps, reach, density, live_strength,
                        anisotropy, 0.02f,
                        VolumetricOcclusion::Pack(atlas_cascades, atlas_valid,
                                                  VolumetricOcclusion::Bits())};
""", """    // bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE as this march reads it (live), and with 2
    // the near mark for the AREA builds (bit 24 of `cascades`, which no other build reads)
    const u32 area_mode = AreaMode();
    const Params params{in.constants_offset_word, steps, reach, density, live_strength,
                        anisotropy, 0.02f,
                        VolumetricOcclusion::Pack(atlas_cascades, atlas_valid,
                                                  VolumetricOcclusion::Bits()) |
                            (area_mode == 2 ? VolumetricAreaGate::NearMark : 0u)};
"""),
rep("""    const bool area_view = VolumetricAreaGate::On() && AreaViewKnob();
    const bool area = live_strength > 0.0f && VolumetricAreaGate::On() && !(gated && area_view) &&
""", """    const bool area_view = area_mode != 0 && AreaViewKnob(); // (r115: the live mode)
    const bool area = live_strength > 0.0f && area_mode != 0 && !(gated && area_view) &&
"""),
rep("""        if (!area_said && !VolumetricAreaGate::On()) {
""", """        if (!area_said && area_mode == 0) {
"""),
rep("""                        "(BB_VOLUMETRIC_AREA_GATE not 1): without the ray traced sun gate "
""", """                        "(BB_VOLUMETRIC_AREA_GATE not 1 or 2): without the ray traced sun gate "
"""),
rep("""                        "(BB_VOLUMETRIC_AREA_GATE=1): a march without the ray traced sun gate "
                        "keeps its sun fog only where the game's light set has sun (the "
                        "surface's for the last %.0f m of each ray, those on screen for the "
                        "rest) or where the air along the view is mostly in the atlas's "
                        "shadow (a beam)\\n",
                        VolumetricAreaGate::FarMetres);
""", """                        "(BB_VOLUMETRIC_AREA_GATE=%u): a march without the ray traced sun gate "
                        "keeps its sun fog only where the game's light set has sun (the "
                        "surface's for the last %.0f m of each ray, those on screen for the "
                        "rest) or where the air along the view is mostly in the atlas's "
                        "shadow (a beam)\\n",
                        area_mode, VolumetricAreaGate::FarMetres); // (r115: the mode, 1 or 2)
"""),
rep("""                        "(BB_VOLUMETRIC_AREA_GATE=1) with the ray traced sun gate: a sample counts "
                        "only where the atlas and that gate let the sun through, then the game's "
                        "light sets weigh what is left as without that gate (the surface's for the "
                        "last %.0f m of each ray, those on screen for the rest)\\n",
                        VolumetricAreaGate::FarMetres);
""", """                        "(BB_VOLUMETRIC_AREA_GATE=%u) with the ray traced sun gate: a sample counts "
                        "only where the atlas and that gate let the sun through, then the game's "
                        "light sets weigh what is left as without that gate (the surface's for the "
                        "last %.0f m of each ray, those on screen for the rest)\\n",
                        area_mode, VolumetricAreaGate::FarMetres); // (r115: the mode, 1 or 2)
"""),
rep("""        if (VolumetricAreaGate::On()) {
            const bool view_off = gated && area_view;
""", """        if (area_mode != 0) {
            const bool view_off = gated && area_view;
"""),
ins("    const vk::DescriptorImageInfo gi{*gate_sampler, *gate_view, vk::ImageLayout::eGeneral};\n", before=
"""    // bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE=2 on an area gate march with the ray
    // traced gate: the DUAL builds (DualReady), not while the gate's probe or view runs (their DIAG
    // build has no wider answer) or the fog noise does (no DUAL build of it): r85's rule there
    const bool dual = area && !viewing && gated && area_mode == 2 && !diag && !noise && DualReady();
    gate_dual_on = dual;
    if (live_strength > 0.0f) {
        SayAreaMode(area_mode, area && !viewing, gated, dual);
    }
    const vk::DescriptorImageInfo goi{*gate_sampler, dual ? *gate_open_view : *gate_view,
                                      vk::ImageLayout::eGeneral};
"""),
rep("""        [wind_push, push_size, di, si, out, repaired, zout, in, repairing, gi, gfi, gated,
""", """        [wind_push, push_size, di, si, out, repaired, zout, in, repairing, gi, gfi, gated,
         dual, goi, // bbport (r115_sun-fog-indoors)
"""),
rep("""                      : area && !viewing ? AreaPass(gated, repairing)
                                         : pass).pipeline,
""", """                      : area && !viewing ? AreaPass(gated, repairing, dual)
                                         : pass).pipeline,
"""),
rep("""                    : area && !viewing ? AreaPass(gated, repairing)
                                       : pass).layout](
""", """                    : area && !viewing ? AreaPass(gated, repairing, dual)
                                       : pass).layout](
"""),
ins("""                    .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &gfi};
                ++count;
""", after=
"""                // bbport (r115_sun-fog-indoors): a DUAL build's wider answer (binding 8, repair 9)
                if (dual) {
                    writes[count] = vk::WriteDescriptorSet{
                        .dstBinding = count, .descriptorCount = 1,
                        .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                        .pImageInfo = &goi};
                    ++count;
                }
"""),
ins("    area_pending = area && !viewing;\n", after=
"""    area_near_pending = area_mode == 2; // bbport (r115_sun-fog-indoors): AreaGate's flags
    area_dual_pending = dual;
"""),
]

# ---------------------------------------------------------------- CMakeLists.txt
EDITS[M] = [
ins("add_host_shader(volumetric_light.comp volumetric_light_repair_gate_area_comp REPAIR=1 GATE=1 AREA=1)\n", after=
"""# bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE=2 on marches with the ray traced gate (made at
# the first such march): the gate with its wider answer and the AREA+GATE march reading it
add_host_shader(volumetric_light.comp volumetric_light_integrate_gate_area_dual_comp INTEGRATE=1 GATE=1 AREA=1 DUAL=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_gate_area_dual_comp REPAIR=1 GATE=1 AREA=1 DUAL=1)
add_host_shader(volumetric_rt_gate.comp volumetric_rt_gate_dual_comp DUAL=1)
"""),
]

# ---------------------------------------------------------------- test_volumetric_area_gate.cpp
EDITS[T] = [
ins('    std::printf("volumetric area gate: all checks passed\\n");\n', before=
"""    // bbport (r115_sun-fog-indoors): the knob as the engine reads it (live): "1" and "2", else 0
    // (r81's Parse above keeps "1" only).
    assert(ParseMode(nullptr) == 0 && ParseMode("") == 0 && ParseMode("0") == 0 &&
           ParseMode("3") == 0 && ParseMode("12") == 0 && ParseMode(" 2") == 0 &&
           ParseMode("2 ") == 0 && ParseMode("on") == 0);
    assert(ParseMode("1") == 1 && ParseMode("2") == 2);
    // The near mark: negative for every b >= 0 (0 too), and b back without it.
    const float marks[] = {0.0f, 1e-6f, 0.004f, 0.37f, 1.0f};
    for (const float b : marks) {
        assert(NearMarked(b) < 0.0f && Near(Unmarked(NearMarked(b)), b) && Unmarked(b) == b);
    }
    // "2"'s apply: without a mark and without dual r81's Apply; a marked (near) ray takes the
    // camera's weight; after a DUAL march b is kept whole and the sets weigh the rest, no beam test.
    assert(Near(ApplyMode2(0.2f, 0.3f, 0.5f, 1.0f, 0.0f, false), Apply(0.2f, 0.3f, 0.5f, 1.0f, 0.0f)));
    assert(Near(ApplyMode2(0.2f, 0.3f, NearMarked(0.5f), 1.0f, 0.0f, false),
                Apply(0.2f, 0.3f, 0.5f, 1.0f, 1.0f)));
    assert(Near(ApplyMode2(0.2f, 0.3f, 0.1f, 0.0f, 0.0f, true), 0.1f));
    assert(Near(ApplyMode2(0.2f, 0.3f, 0.1f, 0.5f, 1.0f, true), 0.1f + 0.1f + 0.3f));
    assert(Near(ApplyMode2(0.2f, 0.3f, NearMarked(0.1f), 0.5f, 0.0f, true), 0.1f + 0.1f + 0.15f));
    // "2"'s camera weight: the far surfaces when any; none left: 1 with sky (outdoors looking up,
    // the hunter alone near), else every surface (a small room, all walls near).
    assert(Near(CameraWeightNear(0.25f, 1.0f, 0.0f, 3.0f, true), 0.25f));
    assert(CameraWeightNear(0.0f, 0.0f, 0.0f, 0.5f, true) == 1.0f);
    assert(CameraWeightNear(0.0f, 0.0f, 0.0f, 0.5f, false) == 0.0f);
    assert(CameraWeightNear(0.0f, 0.0f, 0.0f, 0.0f, false) == 1.0f);
    assert(NearMark == (1u << 24) && FlagNear == 4u && FlagDual == 8u && NearMetres == 5.0f);
"""),
]

# ---------------------------------------------------------------- test_effect_pipelines.cpp
EDITS[P] = [
ins('#include "video_core/host_shaders/volumetric_light_repair_gate_area_comp.h"\n', after=
"""// bbport (r115_sun-fog-indoors): the march's DUAL builds
#include "video_core/host_shaders/volumetric_light_integrate_gate_area_dual_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_area_dual_comp.h"
"""),
ins("""        {"volumetric repair (gate, area gate)",
         VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
          eCombinedImageSampler},
         32},
""", after=
"""        // bbport (r115_sun-fog-indoors): as VolumetricLight::DualReady makes them: the AREA+GATE
        // bindings, then the gate's wider answer
        {"volumetric integrate (gate, area gate, dual)",
         VOLUMETRIC_LIGHT_INTEGRATE_GATE_AREA_DUAL_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler,
          eCombinedImageSampler},
         32},
        {"volumetric repair (gate, area gate, dual)",
         VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_DUAL_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
          eCombinedImageSampler, eCombinedImageSampler},
         32},
"""),
]

# ---------------------------------------------------------------- README.md
EDITS[R] = [
rep("only through the fog noise (`BB_FOG_NOISE`) | off |",
"only through the fog noise (`BB_FOG_NOISE`). `2` (r115; read live, so a test run's live knobs file "
"may change it): as `1`, and (a) a surface nearer than 5 m from the camera (the hunter, the ground at "
"his feet) is left out of the sets on screen (when no farther surface is on the grid: no weighing if "
"it shows sky, else all count), and the fog in front of it is weighed by the sets on screen instead "
"of its own set; (b) on "
"a march with the ray traced sun gate, each cell that gate leaves open gets a second ray toward the "
"sun that also sees what the camera drew (the knob's mask plus `2` of `BB_VOLUMETRIC_RT_GATE`): the "
"light of air that ray leaves open too (open sky, a beam through a real opening) is kept whole, and "
"only the light of air it shuts (a room whose roof only the camera's geometry holds, outdoor air in "
"a building's shadow) is weighed by the sets as above, without the beam test; not on a march with "
"the fog noise or the gate probe (`BB_VOLUMETRIC_GATE_PROBE=1`), which keep `1`'s rule with (a). "
"The log (lines starting `Volumetric lighting (r115)`) says the rule once, every 600 marches how "
"many had the second ray, and after each probe line how many grid points were left out as near. "
"Cost: the second ray only from cells the first leaves open (at most 460,800 rays; the gate's row "
"was 0.022 ms with mask 1 and 0.075 ms with mask 3 at one outdoor place) and one more gate read per "
"lit sample of the march, an estimate of 0.05 to 0.15 ms more at 1080p internal, not measured, on "
"the `Lighting: volumetric sun gate` and `Lighting: volumetric sunlight` rows; 460,800 bytes for its "
"image; with `1` a few more instructions in the area gate's passes, off nothing | off |"),
]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edit_state(cur, ed, path):
    if ed[0] == "ins":
        _, anchor, before, after = ed
        na, nw = cur.count(anchor), cur.count(before + anchor + after)
        parts = [t for t in (before, after) if t]
        counts = [cur.count(t) for t in parts]
        if na == 1 and nw == 1:
            return "applied"
        if na == 1 and all(k == 0 for k in counts):
            return "clean"
        raise SystemExit("REFUSED %s: anchor found %d times (wanted once), whole %d, inserted texts "
                         "%s times: %r" % (path, na, nw, counts, anchor[:80]))
    _, old, new = ed
    no, nn = cur.count(old), cur.count(new)
    if no == 1 and nn == 0:
        return "clean"
    if no == 0 and nn == 1:
        return "applied"
    raise SystemExit("REFUSED %s: old text %d times, new text %d times: %r" % (path, no, nn, old[:80]))


def state_of(cur, eds, path):
    st = [edit_state(cur, ed, path) for ed in eds]
    if all(s == "applied" for s in st):
        return "applied"
    if all(s == "clean" for s in st):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, st.count("applied"), len(eds)))


def apply_text(cur, eds):
    for ed in eds:
        if ed[0] == "ins":
            _, anchor, before, after = ed
            cur = cur.replace(anchor, before + anchor + after, 1)
        else:
            _, old, new = ed
            cur = cur.replace(old, new, 1)
    return cur


def revert_text(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "ins":
            _, anchor, before, after = ed
            cur = cur.replace(before + anchor + after, anchor, 1)
        else:
            _, old, new = ed
            cur = cur.replace(new, old, 1)
    return cur


def conditions(text):
    """For each line, the stack of the #if conditions around it (the line's own #if excluded)."""
    stack, out = [], []
    for line in text.split("\n"):
        st = line.strip()
        if st.startswith("#if"):
            out.append((line, list(stack)))
            stack.append(st)
        elif st.startswith("#elif") or st.startswith("#else"):
            out.append((line, list(stack[:-1])))
            stack[-1] = stack[-1] + " | " + st
        elif st.startswith("#endif"):
            stack.pop()
            out.append((line, list(stack)))
        else:
            out.append((line, list(stack)))
    return out


def text_checks(texts):
    g, l, a = texts[G], texts[L], texts[A]
    # The gate shader: every r115 line inside #ifdef DUAL (its default and DIAG builds keep their words)
    for line, stack in conditions(g):
        if ("r115" in line or "open_wider" in line or "gate_open" in line or "wider" in line) and \
                not any(s.startswith("#ifdef DUAL") for s in stack) and line.strip() != "#ifdef DUAL":
            raise SystemExit("text check: %s line outside #ifdef DUAL: %r" % (G, line))
    # The march: every r115 line inside #ifdef DUAL, #ifndef DUAL or #ifdef AREA (non-AREA builds keep
    # their words)
    for line, stack in conditions(l):
        if ("r115" in line or "DUAL" in line or "AREA_NEAR" in line or "area_b" in line or
                "GateOpenAt" in line or "sun_gate_open" in line) and \
                not any(("DUAL" in s or "AREA" in s) for s in stack) and \
                line.strip() not in ("#ifdef DUAL",):
            raise SystemExit("text check: %s line outside the AREA/DUAL builds: %r" % (L, line))
    for want, n in (("GateOpenAt(", 2), ("layout(binding = 9) uniform sampler3D sun_gate_open;", 1),
                    ("layout(binding = 8) uniform sampler3D sun_gate_open;", 1),
                    ("area_b, 1.0 - depth)); // (r115) b", 1), ("float area_b = ", 2),
                    ("(cascades & AREA_NEAR_MARK) != 0u", 1)):
        if l.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (L, want, l.count(want), n))
    # the DUAL split sits after the gate's multiply in the GATE+AREA block, before r94's noise line
    i_gate_area = l.find("#if defined(GATE) && defined(AREA)\n        // bbport (r85")
    i_split = l.find("float open_e = e > 0.0 ?")
    i_r81 = l.find("#elif defined(GATE)\n        // bbport (r51b")
    if not (0 <= i_gate_area < i_split < i_r81):
        raise SystemExit("text check: the DUAL split is not in r85's GATE+AREA block")
    for want, n in (("& AREA_FLAG_NEAR) != 0u", 2), ("& AREA_FLAG_DUAL) != 0u", 2), ("AREA_STATE_NEAR", 1),
                    ("float(AREA_NEAR_FLOOR)", 2)):
        if a.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (A, want, a.count(want), n))
    c, h, m = texts[C], texts[H], texts[M]
    if "VolumetricAreaGate::On()" in c:
        raise SystemExit("text check: the engine still reads the knob through On()")
    for want, n in (("AreaPass(gated, repairing, dual)", 2), ("SayAreaMode(area_mode,", 1),
                    ("const u32 area_mode = AreaMode();", 1), ("gate_dual_on = dual;", 1),
                    ("VOLUMETRIC_RT_GATE_DUAL_COMP", 1), ("area_dual_pending = dual;", 1),
                    ("diag ? 9u : dual ? 6u : 5u", 1), ("diag || dual ? 3u : 2u", 1)):
        if c.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (C, want, c.count(want), n))
    # `dual` is decided after `noise` and `diag` and before the gate is recorded and the passes bound
    order = [c.find(s) for s in ("    const bool diag = gated && (probe_knob || view_knob) && DiagReady();",
                                 "    const bool noise = FogNoiseMarch(",
                                 "    const bool dual = area && !viewing && gated && area_mode == 2",
                                 "        RecordGate(in, in.constants_offset_word, probing, viewing, di);",
                                 "    area_dual_pending = dual;")]
    if not all(0 <= x for x in order) or order != sorted(order):
        raise SystemExit("text check: dual is not decided between noise and RecordGate: %r" % order)
    for name in ("volumetric_light_integrate_gate_area_dual_comp INTEGRATE=1 GATE=1 AREA=1 DUAL=1",
                 "volumetric_light_repair_gate_area_dual_comp REPAIR=1 GATE=1 AREA=1 DUAL=1",
                 "volumetric_rt_gate_dual_comp DUAL=1"):
        if m.count(name) != 1:
            raise SystemExit("text check: CMakeLists lacks %r" % name)
    if "repair_dual : integrate_dual" not in h or "static u32 AreaMode();" not in h:
        raise SystemExit("text check: header")
    row = [x for x in texts[R].split("\n") if x.startswith("| `BB_VOLUMETRIC_AREA_GATE` |")]
    if len(row) != 1 or "nearer than 5 m" not in row[0] or "`2` (r115" not in row[0]:
        raise SystemExit("text check: README row")
    y = texts[Y]
    if "#define AREA_NEAR_METRES 5.0" not in y or "#define AREA_NEAR_MARK 0x1000000u" not in y:
        raise SystemExit("text check: layout numbers")
    # (review) the DUAL split takes the wider answer as its share of the first one, and the camera
    # pass's no-far-surface case asks for sky; the guard sits before r51's comment line
    if l.count("clamp(GateOpenAt(uv, t, gate_range) / gate_first_ray, 0.0, 1.0)") != 1 or \
            l.count("const float gate_first_ray = v > 0.0 ? GateAt(uv, t, gate_range) : 0.0;") != 1:
        raise SystemExit("text check: the DUAL split")
    if a.count("s_v[0].w < 0.5 && s_v[0].y > AREA_CAMERA_EPS") != 1 or \
            a.count("surface && near ? 1.0 : 0.0,\n                   fog.a == 0.0 ? 1.0 : 0.0);") != 1:
        raise SystemExit("text check: the camera pass's sky case")
    if l.count("#endif\n// bbport (r51_volumetric-leak): the bits of BB_VOLUMETRIC_OCCLUSION") != 1:
        raise SystemExit("text check: the DUAL guard's place")
    if "CameraWeightNear(" not in texts[Q] or "CameraWeightNear(" not in texts[T]:
        raise SystemExit("text check: the host's camera weight with the near rule")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R115_ROOT)" % ROOT)
    # (review) the draft r115_sun-fog-indoors.py was applied to the build tree at 23:14 before its
    # review: this script then refuses with a clear word instead of an anchor message
    if "float open_e = e > 0.0 ? e * GateOpenAt(uv, t, gate_range) : 0.0;" in load(L)[2]:
        raise SystemExit("the DRAFT r115_sun-fog-indoors.py is applied here: first `python -I -X utf8 "
                         "r115_sun-fog-indoors.py revert`, then this script's apply (nothing written)")
    plan = []
    for path in FILES:
        raw, eol, cur = load(path)
        eds = EDITS[path]
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            new = apply_text(cur, eds)
            if state_of(new, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            if revert_text(new, eds) != cur:
                raise SystemExit("%s: revert of the result would not give the original" % path)
            out[path] = new
        return out

    nedits = sum(len(p[1]) for p in plan)
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files, %d edits; text checks on the result pass)"
                  % (len(plan), nedits))
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
            tmp = full + ".r115tmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied (%d files, %d edits)" % (len(plan), nedits)); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        new = revert_text(cur, eds)
        if state_of(new, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = new.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r115tmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
