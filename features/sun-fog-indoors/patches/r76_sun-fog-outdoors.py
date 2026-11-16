# r76_sun-fog-outdoors: the sun fog's ray traced gate on by default (mask 1, the sun's casters),
# on top of r51 and r51b; a probe line and a debug view to find out what the camera-pass mask hits.
#
# Why: the owner's rule (2026-11-15, verbatim): "The sun fog shouldn't go indoors at all", and
# (14:48) real sun shafts through windows stay. The engine's sun fog pass
# (effect_volumetric_light) marches the game's sun shadow atlas; where the atlas holds no roof (a
# lattice roof, a ceiling the game does not send as a sun caster) the fog fills closed rooms.
# r51b's ray traced gate (one sun ray per cell of a 160x90x32 grid through the frame's ray traced
# scene) was off unless BB_VOLUMETRIC_RT_GATE was set. Game tests of 2026-11-15 (rounds 1 and 2):
# mask 1 (the sun's casters) cleared the roofed library with the BB PC Remaster mod on and changed
# nothing at four outdoor places (graveyard-blood, church-puddles, lamp-test-spot, dark-alley;
# one small green mist patch at dark-alley not understood); masks 2 and 3 (the camera pass's
# geometry too) also cleared the mod-off veils indoors but removed the sun fog over the whole
# frame at graveyard-blood (a night save under a huge stone vault). So the default is 1; 2 and 3
# stay test values until the probe below tells why they shut open air there.
#
# What:
# 1. BB_VOLUMETRIC_RT_GATE unset (or text that names no mask) is 1, the sun's casters; "0" still
#    turns the gate off; "2" and "3" as before. The gate runs only while RtShadow builds a ray
#    traced scene (effect_ray_tracing on with the ray traced sun, ray traced lamps or bounced
#    light: RtShadow::SceneWanted); without one the mask in force is 0
#    (VolumetricOcclusion::GateInForce) and the march is r51's, as for every player before.
#    Log: the gate's once-line names the knob's value and whether it is the default; the
#    600-march line adds "(the default)" and is printed only once a gate was tried (a player
#    without ray tracing gets no line every 600 marches, first review finding 4); new once-lines
#    when the knob is 0 and when 600 marches in a row had no scene.
# 2. BB_VOLUMETRIC_OCCLUSION unset is 5 (bits 1 and 4), no longer 7. Bit 2 ("Darkest": the
#    darkest answer of every cascade holding the sample) doubled the march's time in the game:
#    "Lighting: volumetric sunlight" 0.199 ms at 5 against 0.430 ms at 7 in the library, 0.212
#    against 0.419 ms at an outdoor street lamp (one run each, mod off, ray traced sun on, gate
#    off; RTX 4090, 1080p internal, fog at 960x540), and 7 looked like 0 where the leak was found.
#    With the gate on, bit 2's case (a roof only a coarser cascade drew) is covered at the gate's
#    cell resolution (cells of 12x12 pixels at 1080p, filtered between cells) for the casters
#    RtShadow::PrepareDraw keeps: mask 1 holds every sun caster draw of the frame in any cascade
#    plus the casters r14 holds, as whole meshes in world space. Not covered: a caster PrepareDraw
#    leaves out (not solid, no index list, more instances than it takes, no constants); with bit 2
#    clear a light depth outside [0, 1] gives dark, never lit. Without ray tracing bit 2's case is
#    unguarded, as it showed no effect.
# 3. The march skips what the gate shuts: the gate's pass (workgroups now 2x2 columns of all 32
#    slices) also writes each column's first open slice; the GATE builds of the march start each
#    pixel at the first sample whose gate read can be non-zero (GateShutTo) and do not march a
#    pixel whose columns are shut all the way. The samples left out read a filtered mix of zeros,
#    so by the argument in the shader's comment they added exactly 0 and the picture is the same
#    (argued, not yet compared on the GPU).
# 4. GPU profile: the rows "Lighting: volumetric sun gate" and "Lighting: volumetric sunlight"
#    are pinned (EffectPass::Mark's new `pinned`, GpuProfiler::Pin): printed in every block they
#    have time in, also below the BB_GPU_PROFILE_ROWS cut (30 rows by default). The gate is
#    recorded after the lamp fog image's clear, so its row no longer holds that clear.
# 5. The light's direction (default, host only): the resolve's 32 shadow constants the gate's
#    rays take their direction from are read on the host (VolumetricOcclusion::LightDirection, the
#    gate shader's prepare() in double precision), turned to world space with the camera the ray
#    traced scene was placed with (CameraMotion::PassMatrices().inv_view), and said once at the
#    first march and again when it moved by more than 1 degree (at most one line in 60 marches,
#    at most 100 lines): "Volumetric lighting (r76): light direction world (x, y, z) elevation E
#    deg azimuth A deg ...". No GPU work.
# 6. BB_VOLUMETRIC_GATE_PROBE=1 (test only, read once, said once; off: nothing of it runs, the
#    gate and march builds are the ones of item 3): on a gated march every 600 (the first after
#    120) the gate's DIAG build (volumetric_rt_gate.comp DIAG=1) traces the same rays to their
#    nearest hit, counts the shut cells in front of the visible surface (the camera's depth at the
#    cell's column, as the march's limit: cells behind a wall or under the ground are not counted)
#    by the hit's distance (<5, 5-15, 15-40, 40-150, 150-800 m) and, of them, those whose hit
#    instance carries the camera pass's mask bit without the sun's ("camera-only"), and keeps the
#    centre column's 32 slices (distance, instance id) and its surface distance. The host
#    maps the instance id to RtShadow::GateTable (the TLAS records in order: the entry's key,
#    triangles and record mask) and prints "Volumetric lighting (r76): gate probe: light world
#    (x,y,z) elevation E deg azimuth A; shut cells in front of the surface <5/5-15/15-40/40-150/
#    150-800 m = a/b/c/d/e, camera-only a'/b'/c'/d'/e'; centre column (surface D) s:t
#    m:key:tris:mask ...".
# 7. BB_VOLUMETRIC_GATE_VIEW=1 (test only, read once, said once; off: nothing of it runs): the DIAG
#    build on every gated march writes each cell's distance band; the march's GATE_VIEW build
#    writes, per half-resolution pixel, the band of the first shut cell along its view ray before
#    the surface and the share of shut cells; the composite's GATE_VIEW build tints the picture
#    with it (red <5 m, yellow 5-15, green 15-40, cyan 40-150, magenta beyond); open: untouched.
# 8. Docs (README's environment variables, docs/renderer-performance-0.9.43.md's "Not restored
#    by the switch") and tests (volumetric-occlusion-test: the new defaults, "unset means 1 with a
#    scene, 0 without", the diagnostics' pure parts and the light's direction;
#    effect-pipelines-test: the march's two GATE builds and the two GATE_VIEW builds).
#
# Not changed here: what the camera-pass mask hits at graveyard-blood (the vault overhead, or far
# backdrop geometry along a low moon: the probe is there to tell), the mod-off interior veil that
# mask 1 leaves (the library, the church hall), cut-out cards (leaves) that mask 1 holds as whole
# polygons (first review finding 2: shafts under tree crowns may go; a game test place is asked
# for), and frames without a scene (first review finding 5: the march is r51's for that frame).
# A gate cell never turns fog on (it multiplies the atlas's answer by 0 or 1) and a ray that hits
# nothing leaves its cell open.
#
# Cost (NOT MEASURED for r76): the gate as measured with r51b now runs for every ray tracing
# player with mask 1: gate row 0.022 ms at lamp-test-spot (two rounds, mod off), 0.018-0.033 ms
# elsewhere (round 2, 1080p internal); the march saves most of its time where the gate is shut
# and adds four 2D gathers a pixel elsewhere (a 14 KB image); BB_VOLUMETRIC_OCCLUSION 5 saves
# about 0.2 ms against 7. Host: a 128-byte read of guest memory and a 4x4 inverse a frame. With
# the probe: one nearest-hit march in 600 plus a 312-byte copy back; with the view: a nearest-hit
# gate every march (more than the 0.022 ms first-hit gate), a 0.46 MB band image and a half
# resolution RGBA8 image. Memory by default: 14 KB more.
#
# Files: host_shaders/volumetric_rt_gate.comp, host_shaders/volumetric_light.comp,
# renderer_vulkan/volumetric_occlusion.h, vk_volumetric_light.h, vk_volumetric_light.cpp,
# vk_rasterizer_effects.cpp, vk_rt_shadow.h, vk_rt_shadow.cpp, vk_effect_pass.h,
# vk_effect_pass.cpp, vk_gpu_profiler.h, vk_gpu_profiler.cpp, engine/gpu/CMakeLists.txt (three
# shader builds), engine/tests/test_volumetric_occlusion.cpp, engine/tests/test_effect_pipelines.cpp,
# engine/docs/renderer-performance-0.9.43.md, README.md.
#
# Use: cd <tree> && python -I -X utf8 r76_sun-fog-outdoors.py check | apply | revert (root from
# R76_ROOT, else the current directory). Files keep their line ends (CRLF in the tree). Originals
# are kept in r76_backup/ next to this script. Needs r51 and r51b applied (the anchors hold their
# text).
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r76_backup")
ROOT = os.environ.get("R76_ROOT") or os.getcwd()
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"

EDITS = {
    H + "volumetric_rt_gate.comp": [
        (r'''// sun into the fog under it.
#version 460
''', r'''// sun into the fog under it.
// bbport (r76_sun-fog-outdoors): a workgroup is a 2x2 block of columns with all their slices
// (local_size_z is GateSlices, 32, which vk_volumetric_light.cpp's static_assert assumes; nothing
// checks the shader's local size against it), so it also writes, for every column, the first
// slice whose ray left the scene into gate_first (32 where every ray of the column hit
// something). The march's GATE builds start each pixel at the first sample that can read an open
// cell (GateShutTo in volumetric_light.comp).
// bbport (r76_sun-fog-outdoors): the DIAG build (made only with BB_VOLUMETRIC_GATE_PROBE=1 or
// BB_VOLUMETRIC_GATE_VIEW=1) traces the same rays without TerminateOnFirstHit, so the hit it
// reports is the nearest (whether a cell is shut is the same), and as the push word's bits above
// the instance mask ask (GateDiagProbe 0x100, GateDiagBand 0x200 in volumetric_occlusion.h)
// counts the shut cells in front of the visible surface (depth_tex, the march's own limit) by the
// hit's distance into `probe` and writes each cell's band into gate_band for the march's view.
#version 460
'''),
        (r'''layout(local_size_x = 4, local_size_y = 4, local_size_z = 4) in;
''', r'''layout(local_size_x = 2, local_size_y = 2, local_size_z = 32) in;
'''),
        (r'''layout(binding = 3, r8) uniform writeonly image3D gate_out;
''', r'''layout(binding = 3, r8) uniform writeonly image3D gate_out;
// bbport (r76_sun-fog-outdoors): per column (the cells' x and y), (first open slice + 0.25) / 255
layout(binding = 4, r8) uniform writeonly image2D gate_first;
#ifdef DIAG
// bbport (r76_sun-fog-outdoors): each cell's band / 255: 0 open or not asked, 1 to 5 the nearest
// hit's distance below 5, 15, 40, 150 m and beyond (VolumetricOcclusion::GateBand)
layout(binding = 5, r8) uniform writeonly image3D gate_band;
// The probe's words (VolumetricOcclusion::GateProbe*; VolumetricLight reads the first 79): shut
// cells in front of the visible surface by band; of them those whose hit instance has mask bit 2
// and not bit 1 (camera pass only); the cells in front of the surface asked; the direction toward
// the light in view space; the centre column's 32 slices, two words each (the hit distance's bits,
// 0xFFFFFFFF open, 0xFFFFFFFE not asked; the instance id, 0xFFFFFFFF none), all of them, also
// those behind the surface; the centre column's surface distance (m; 1e30 sky, -1 none); then each
// instance's record mask, four to a word, which the host writes.
layout(scalar, binding = 6) buffer GateProbe {
    uint shut[5];
    uint camera_only[5];
    uint asked;
    float direction[3];
    uint column[64];
    float centre_surface;
    uint masks[];
} probe;
const uint DiagProbe = 0x100u, DiagBand = 0x200u;
// bbport (r76_sun-fog-outdoors): the camera's depth, as the march reads it (its depth_tex): the
// probe counts only cells nearer than the visible surface, the air the march walks through
layout(binding = 7) uniform sampler2D depth_tex;
#endif
'''),
        (r'''shared float shared_range;
shared uint shared_valid;
''', r'''shared float shared_range;
shared uint shared_valid;
shared uint shared_first[4]; // bbport (r76_sun-fog-outdoors): per column of the workgroup
#ifdef DIAG
shared uint shared_probe[11]; // bbport (r76_sun-fog-outdoors): the group's shut[], camera_only[], asked
#endif
'''),
        (r'''    if (gl_LocalInvocationIndex == 0u) prepare();
    barrier();

    ivec3 cell = ivec3(gl_GlobalInvocationID);
    ivec3 size = imageSize(gate_out);
    if (any(greaterThanEqual(cell, size))) return;
    // Open (1) where nothing can be asked: the march keeps the atlas's answer there.
    float open = 1.0;
    vec2 uv = (vec2(cell.xy) + 0.5) / vec2(size.xy);
    vec4 h = shared_inverse_projection * vec4(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, 0.5, 1.0);
    if (shared_valid != 0u && abs(h.w) >= 1e-8) {
''', r'''    if (gl_LocalInvocationIndex == 0u) prepare();
    // bbport (r76_sun-fog-outdoors): no open slice found yet in the workgroup's four columns
    if (gl_LocalInvocationIndex < 4u) shared_first[gl_LocalInvocationIndex] = gl_WorkGroupSize.z;
#ifdef DIAG
    if (gl_LocalInvocationIndex < 11u) shared_probe[gl_LocalInvocationIndex] = 0u;
#endif
    barrier();

    ivec3 cell = ivec3(gl_GlobalInvocationID);
    ivec3 size = imageSize(gate_out);
    // bbport (r76_sun-fog-outdoors): no early return, every invocation reaches the barrier below
    bool inside = all(lessThan(cell, size));
    // Open (1) where nothing can be asked: the march keeps the atlas's answer there.
    float open = 1.0;
#ifdef DIAG
    // bbport (r76_sun-fog-outdoors): the nearest hit's band (0: open or not asked), distance and
    // instance id, whether a ray was traced, and the column's visible surface (m; 1e30 sky, -1
    // none) and whether the cell lies in front of it
    uint band = 0u;
    float hit_t = 0.0;
    uint hit_instance = 0xFFFFFFFFu;
    bool asked = false;
    float surface = -1.0;
    bool front = false;
#endif
    vec2 uv = (vec2(cell.xy) + 0.5) / vec2(size.xy);
    vec4 h = shared_inverse_projection * vec4(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, 0.5, 1.0);
    if (inside && shared_valid != 0u && abs(h.w) >= 1e-8) {
'''),
        (r'''            rayQueryEXT query;
            rayQueryInitializeEXT(query, scene, gl_RayFlagsTerminateOnFirstHitEXT | gl_RayFlagsOpaqueEXT,
                                  mask, p, 0.02, shared_direction, max_distance);
            rayQueryProceedEXT(query);
            open = rayQueryGetIntersectionTypeEXT(query, true) ==
                           gl_RayQueryCommittedIntersectionNoneEXT
                       ? 1.0
                       : 0.0;
        }
''', r'''            rayQueryEXT query;
#ifdef DIAG
            // bbport (r76_sun-fog-outdoors): to the nearest hit (every instance is opaque, so one
            // proceed walks the whole ray); the instance mask is the push word's low 8 bits
            rayQueryInitializeEXT(query, scene, gl_RayFlagsOpaqueEXT, mask & 255u, p, 0.02,
                                  shared_direction, max_distance);
#else
            rayQueryInitializeEXT(query, scene, gl_RayFlagsTerminateOnFirstHitEXT | gl_RayFlagsOpaqueEXT,
                                  mask, p, 0.02, shared_direction, max_distance);
#endif
            rayQueryProceedEXT(query);
            open = rayQueryGetIntersectionTypeEXT(query, true) ==
                           gl_RayQueryCommittedIntersectionNoneEXT
                       ? 1.0
                       : 0.0;
#ifdef DIAG
            asked = true;
            // As the march's limit: depth 1 is sky (the whole column), a depth outside (0, 1] or a
            // surface not in front of the camera is no air the march walks through.
            float depth = textureLod(depth_tex, uv, 0.0).r;
            if (depth == 1.0) {
                surface = 1e30;
            } else if (depth > 0.0 && depth < 1.0) {
                vec4 q = shared_inverse_projection *
                         vec4(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, depth, 1.0);
                if (abs(q.w) >= 1e-8 && q.z / q.w > 0.0) surface = length(q.xyz / q.w);
            }
            front = shared_range * s * s < surface;
            if (open == 0.0) {
                hit_t = rayQueryGetIntersectionTEXT(query, true);
                hit_instance = uint(rayQueryGetIntersectionInstanceIdEXT(query, true));
                band = 1u + uint(hit_t >= 5.0) + uint(hit_t >= 15.0) + uint(hit_t >= 40.0) +
                       uint(hit_t >= 150.0);
            }
#endif
        }
'''),
        (r'''    imageStore(gate_out, cell, vec4(open));
}
''', r'''    if (inside) imageStore(gate_out, cell, vec4(open));
#ifdef DIAG
    // bbport (r76_sun-fog-outdoors): the band for the view (every cell: the march's view walks only
    // the cells in front of its surface); the probe's counts of the cells in front of the surface
    // (by group first) and the centre column (all its slices) with its surface
    if (inside && (mask & DiagBand) != 0u) imageStore(gate_band, cell, vec4(float(band) / 255.0));
    if ((mask & DiagProbe) != 0u) {
        if (asked && front) atomicAdd(shared_probe[10], 1u);
        if (band != 0u && front) {
            atomicAdd(shared_probe[band - 1u], 1u);
            uint at = hit_instance >> 2;
            uint m = at < uint(probe.masks.length())
                         ? (probe.masks[at] >> ((hit_instance & 3u) * 8u)) & 255u
                         : 0u;
            if ((m & 2u) != 0u && (m & 1u) == 0u) atomicAdd(shared_probe[4u + band], 1u);
        }
        if (inside && all(equal(cell.xy, size.xy / 2))) {
            probe.column[2 * cell.z] = band != 0u ? floatBitsToUint(hit_t)
                                                  : (asked ? 0xFFFFFFFFu : 0xFFFFFFFEu);
            probe.column[2 * cell.z + 1] = hit_instance;
            if (cell.z == 0) probe.centre_surface = surface;
        }
    }
#endif
    // bbport (r76_sun-fog-outdoors): the column's first open slice, stored by its slice 0; the
    // quarter keeps the store's rounding to the 8-bit value on F, whichever way it rounds
    uint column = gl_LocalInvocationID.x + 2u * gl_LocalInvocationID.y;
    if (inside && open != 0.0) atomicMin(shared_first[column], uint(cell.z));
    barrier();
    if (inside && gl_LocalInvocationID.z == 0u) {
        imageStore(gate_first, cell.xy, vec4((float(shared_first[column]) + 0.25) / 255.0));
    }
#ifdef DIAG
    if ((mask & DiagProbe) != 0u) {
        uint i = gl_LocalInvocationIndex;
        if (i < 11u && shared_probe[i] != 0u) {
            if (i < 5u) {
                atomicAdd(probe.shut[i], shared_probe[i]);
            } else if (i < 10u) {
                atomicAdd(probe.camera_only[i - 5u], shared_probe[i]);
            } else {
                atomicAdd(probe.asked, shared_probe[i]);
            }
        }
        if (all(equal(gl_GlobalInvocationID, uvec3(0u)))) {
            for (int k = 0; k < 3; ++k) {
                probe.direction[k] = shared_valid != 0u ? shared_direction[k] : 0.0;
            }
        }
    }
#endif
}
'''),
    ],
    H + "volumetric_light.comp": [
        (r'''#ifdef REPAIR
layout(binding = 7) uniform sampler3D sun_gate;
#else
layout(binding = 6) uniform sampler3D sun_gate;
#endif
#endif
''', r'''#ifdef REPAIR
layout(binding = 7) uniform sampler3D sun_gate;
#else
layout(binding = 6) uniform sampler3D sun_gate;
#endif
// bbport (r76_sun-fog-outdoors): per column of the gate, its first open slice ((F + 0.25) / 255;
// F is the slice count where every slice is shut), written by volumetric_rt_gate.comp
#ifdef REPAIR
layout(binding = 8) uniform sampler2D sun_gate_first;
#else
layout(binding = 7) uniform sampler2D sun_gate_first;
#endif
#ifdef GATE_VIEW
#ifdef REPAIR
#error GATE_VIEW is a build of INTEGRATE only
#endif
// bbport (r76_sun-fog-outdoors): BB_VOLUMETRIC_GATE_VIEW=1: the view at the march's resolution
// (rgb the band's colour of the first shut cell along the view ray, a the share of shut cells;
// 0 where none is shut), and each cell's band (volumetric_rt_gate.comp's DIAG build)
layout(binding = 8, rgba8) uniform writeonly image2D gate_view_out;
layout(binding = 9) uniform sampler3D sun_gate_band;
#endif
#endif
'''),
        (r'''float GateAt(vec2 uv, float t, float range) {
    return textureLod(sun_gate, vec3(uv, sqrt(clamp(t / range, 0.0, 1.0))), 0.0).r;
}
#endif
''', r'''float GateAt(vec2 uv, float t, float range) {
    return textureLod(sun_gate, vec3(uv, sqrt(clamp(t / range, 0.0, 1.0))), 0.0).r;
}

// bbport (r76_sun-fog-outdoors): how far along the pixel's ray (m) GateAt reads exactly 0. Its
// linear filter reads, at the depth coordinate w = sqrt(t / range), the slices floor(w N - 0.5)
// and the next one (N slices, clamped to the edge), and in x and y two neighbouring columns each.
// The four gathers take the first open slice of every column in the 4x4 block around uv, which
// holds any two-by-two footprint whose first column lies within one of the gather's, so the
// sampler's rounding of the footprint cannot reach a column not looked at. F is their least first
// open slice: every slice before F of those columns is 0, so while floor(w N - 0.5) + 1 < F, that
// is w < (F - 0.5) / N, GateAt filters zeros only and returns 0. The threshold is taken 1/16 slice
// lower, which keeps the sampler's sub-texel rounding of w N - 0.5 (8 bits) on the side of
// reading. F 0: nothing shut in front (0 m). F >= N: every slice of those columns is shut,
// whatever w: 1e30 m, farther than any march. (Argued here; not compared on the GPU.)
float GateShutTo(vec2 uv, float range) {
    vec4 a = textureGatherOffset(sun_gate_first, uv, ivec2(-1, -1));
    vec4 b = textureGatherOffset(sun_gate_first, uv, ivec2(1, -1));
    vec4 c = textureGatherOffset(sun_gate_first, uv, ivec2(-1, 1));
    vec4 d = textureGatherOffset(sun_gate_first, uv, ivec2(1, 1));
    vec4 m = min(min(a, b), min(c, d));
    float first = floor(min(min(m.x, m.y), min(m.z, m.w)) * 255.0 + 0.5);
    float slices = float(textureSize(sun_gate, 0).z);
    if (first >= slices) return 1e30;
    float w = max(first - 0.5625, 0.0) / slices;
    return range * w * w;
}

#ifdef GATE_VIEW
// bbport (r76_sun-fog-outdoors): the view's colour of a band: 1 (<5 m) red, 2 (5-15 m) yellow, 3
// (15-40 m) green, 4 (40-150 m) cyan, 5 (150-800 m) magenta
vec3 GateBandColour(uint band) {
    return band == 1u   ? vec3(1.0, 0.1, 0.1)
           : band == 2u ? vec3(1.0, 0.9, 0.1)
           : band == 3u ? vec3(0.1, 1.0, 0.2)
           : band == 4u ? vec3(0.1, 0.9, 1.0)
                        : vec3(1.0, 0.2, 1.0);
}

// bbport (r76_sun-fog-outdoors): the cells of the pixel's column (nearest, no filter) whose
// centres lie before the march's end: the band of the first shut one and the share shut
void GateView(ivec2 px, vec2 uv, float range, float limit) {
    ivec3 cells = textureSize(sun_gate_band, 0);
    ivec2 column = clamp(ivec2(uv * vec2(cells.xy)), ivec2(0), cells.xy - 1);
    uint first = 0u;
    float shut = 0.0, asked = 0.0;
    for (int k = 0; k < cells.z; ++k) {
        float s = (float(k) + 0.5) / float(cells.z);
        if (range * s * s >= limit) break;
        asked += 1.0;
        uint band = uint(texelFetch(sun_gate_band, ivec3(column, k), 0).r * 255.0 + 0.5);
        if (band != 0u) {
            shut += 1.0;
            if (first == 0u) first = band;
        }
    }
    if (first != 0u) imageStore(gate_view_out, px, vec4(GateBandColour(first), shut / asked));
}
#endif
#endif
'''),
        (r'''    if (any(greaterThanEqual(px, size))) return;
#ifndef REPAIR
    ivec2 depth_size = imageSize(depth_out);
''', r'''    if (any(greaterThanEqual(px, size))) return;
#ifdef GATE_VIEW
    // bbport (r76_sun-fog-outdoors): the view's pixel stays clear unless GateView finds a shut cell
    imageStore(gate_view_out, px, vec4(0.0));
#endif
#ifndef REPAIR
    ivec2 depth_size = imageSize(depth_out);
'''),
        (r'''#ifdef GATE
    float gate_range = GateRange();
#endif
    for (uint i = 0u; i < steps; ++i) {
        float t = (float(i) + jitter) * ds;
''', r'''#ifdef GATE
    float gate_range = GateRange();
#ifdef GATE_VIEW
    GateView(px, uv, gate_range, limit);
#endif
    // bbport (r76_sun-fog-outdoors): the samples nearer than GateShutTo add exactly 0 (their gate
    // is 0), so the march starts after them; a pixel whose columns are shut all the way (indoors
    // under a roof the ray traced scene holds) is not marched and keeps the 0 stored above. A
    // sample left out has t = (i + jitter) ds < shut_to; adding 0 never changed the sum.
    float shut_to = GateShutTo(uv, gate_range);
    uint first_step = 0u;
    if (shut_to > 0.0) {
        first_step = shut_to < limit ? uint(clamp(ceil(shut_to / ds - jitter), 0.0, float(steps)))
                                     : steps;
    }
    for (uint i = first_step; i < steps; ++i) {
#else
    for (uint i = 0u; i < steps; ++i) {
#endif
        float t = (float(i) + jitter) * ds;
'''),
        (r'''layout(binding = 5) uniform sampler2D point_tex;
''', r'''layout(binding = 5) uniform sampler2D point_tex;
#ifdef GATE_VIEW
// bbport (r76_sun-fog-outdoors): BB_VOLUMETRIC_GATE_VIEW=1: the march's view image (GateView)
layout(binding = 6) uniform sampler2D gate_view_tex;
#endif
'''),
        (r'''    vec4 color = imageLoad(scene, px);
    imageStore(scene, px, vec4(color.rgb + scattering * state.atmosphere.rgb +
                                   texelFetch(point_tex, px, 0).rgb, color.a));
}
''', r'''    vec4 color = imageLoad(scene, px);
#ifdef GATE_VIEW
    // bbport (r76_sun-fog-outdoors): the gate view over the finished fog: the band's colour at
    // the pixel's own brightness (at least 0.02), more of it the more cells along the view are shut
    vec3 rgb = color.rgb + scattering * state.atmosphere.rgb + texelFetch(point_tex, px, 0).rgb;
    vec4 view = textureLod(gate_view_tex, uv, 0.0);
    if (view.a > 0.0) {
        float luma = max(dot(rgb, vec3(0.2126, 0.7152, 0.0722)), 0.02);
        rgb = mix(rgb, view.rgb * luma * 2.0, 0.3 + 0.5 * view.a);
    }
    imageStore(scene, px, vec4(rgb, color.a));
#else
    imageStore(scene, px, vec4(color.rgb + scattering * state.atmosphere.rgb +
                                   texelFetch(point_tex, px, 0).rgb, color.a));
#endif
}
'''),
    ],
    R + "volumetric_occlusion.h": [
        (r'''// BB_VOLUMETRIC_OCCLUSION, a bit field read once at start (default 7, all on; 0: as before r51):
''', r'''// BB_VOLUMETRIC_OCCLUSION, a bit field read once at start (default 5 since r76_sun-fog-outdoors:
// bits 1 and 4; 7 all on; 0: as before r51):
'''),
        (r'''//     bridge drawn only into a coarser cascade); a light depth outside [0, 1] asks the next one
''', r'''//     bridge drawn only into a coarser cascade); a light depth outside [0, 1] asks the next one.
//     Not in the default since r76: in the game it doubled the march's time ("Lighting:
//     volumetric sunlight" 0.199 ms at 5 against 0.430 ms at 7 in a roofed library, 0.212 against
//     0.419 ms at an outdoor street lamp; one run each, ray traced sun on, no gate; RTX 4090,
//     1080p internal) and changed nothing visible where the leak was found. With a ray traced
//     scene the sun gate (BB_VOLUMETRIC_RT_GATE, mask 1, the default) holds every sun caster any
//     cascade drew this frame or r14 holds, whole and in world space (RtShadow::PrepareDraw,
//     PrepareScene): bit 2's case is covered at the gate's cell resolution (160x90x32 cells,
//     filtered between cells) for the casters PrepareDraw keeps; with bit 2 clear a light depth
//     outside [0, 1] is dark (no fog), never lit.
'''),
        (r'''#include <cstdint>
#include <cstdlib>
''', r'''#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <vector>
'''),
        (r'''inline constexpr std::uint32_t All = SkipEmpty | Darkest | Robust;

/// BB_VOLUMETRIC_OCCLUSION's text: a whole number 0..7; unset, empty or anything else gives All.
inline std::uint32_t Parse(const char* text) {
    if (!text || !*text) {
        return All;
    }
    char* end = nullptr;
    const unsigned long n = std::strtoul(text, &end, 10);
    return *end == '\0' && n <= All ? std::uint32_t(n) : All;
}
''', r'''inline constexpr std::uint32_t All = SkipEmpty | Darkest | Robust;
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
'''),
        (r'''/// bbport (r51b_volumetric-rt-check): BB_VOLUMETRIC_RT_GATE's text, the instance mask the ray
/// traced sun gate traces: "1" the sun's casters (rt_shadow.comp's mask), "2" the camera pass's
/// geometry, "3" both. "0", unset, empty or anything else: 0, no gate (stage A exactly).
inline std::uint32_t ParseRtGate(const char* text) {
    if (!text || text[0] < '0' || text[0] > '3' || text[1] != '\0') {
        return 0;
    }
    return std::uint32_t(text[0] - '0');
}

/// The gate's knob, read once.
inline std::uint32_t RtGateMask() {
    static const std::uint32_t mask = ParseRtGate(std::getenv("BB_VOLUMETRIC_RT_GATE"));
    return mask;
}
''', r'''/// bbport (r76_sun-fog-outdoors): the gate's mask when BB_VOLUMETRIC_RT_GATE is not set: 1, the
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

/// The gate's knob, read once.
inline std::uint32_t RtGateMask() {
    static const std::uint32_t mask = ParseRtGate(std::getenv("BB_VOLUMETRIC_RT_GATE"));
    return mask;
}

/// bbport (r76_sun-fog-outdoors): whether the gate's knob is the default (the variable not set,
/// or text that names no mask), for the log lines; read once.
inline bool RtGateByDefault() {
    static const bool by_default = !RtGateNamed(std::getenv("BB_VOLUMETRIC_RT_GATE"));
    return by_default;
}

/// bbport (r76_sun-fog-outdoors): the mask the march's gate traces in a frame: the knob's mask
/// when the rasterizer prepared a ray traced scene for it (RtShadow::PrepareScene), else 0: no
/// gate, the march of stage A, as for every player before r76.
constexpr std::uint32_t GateInForce(std::uint32_t mask, bool scene) {
    return scene ? mask : 0u;
}
'''),
        (r'''} // namespace Vulkan::VolumetricOcclusion
''', r'''// bbport (r76_sun-fog-outdoors): the gate's diagnostics, BB_VOLUMETRIC_GATE_PROBE=1 and
// BB_VOLUMETRIC_GATE_VIEW=1 (test only, off by default, read once). Off, nothing of them runs and
// the gate traces with its own build. On, the gate's DIAG build (volumetric_rt_gate.comp) traces
// the same rays to their nearest hit.

/// A knob that is on only as exactly "1".
inline bool ParseOn(const char* text) {
    return text && text[0] == '1' && text[1] == '\0';
}

/// BB_VOLUMETRIC_GATE_PROBE=1: the probe line every 600 gated marches; read once.
inline bool GateProbe() {
    static const bool on = ParseOn(std::getenv("BB_VOLUMETRIC_GATE_PROBE"));
    return on;
}

/// BB_VOLUMETRIC_GATE_VIEW=1: the gate's debug view; read once.
inline bool GateView() {
    static const bool on = ParseOn(std::getenv("BB_VOLUMETRIC_GATE_VIEW"));
    return on;
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
'''),
    ],
    R + "vk_volumetric_light.h": [
        (r'''#include "video_core/renderer_vulkan/vk_point_shadow.h"
''', r'''#include "video_core/renderer_vulkan/vk_point_shadow.h"
#include "video_core/renderer_vulkan/volumetric_occlusion.h" // bbport (r76_sun-fog-outdoors)
'''),
        (r'''    /// camera's view space) and the instance mask the sun gate traces (BB_VOLUMETRIC_RT_GATE),
    /// for the next Integrate. A null scene or mask 0: no gate, the march of stage A.
''', r'''    /// camera's view space) and the instance mask the sun gate traces (BB_VOLUMETRIC_RT_GATE;
    /// r76_sun-fog-outdoors: 1 when not set, 0 without a scene: VolumetricOcclusion::GateInForce),
    /// for the next Integrate. A null scene or mask 0: no gate, the march of stage A.
'''),
        (r'''    /// How far the last Integrate marched through the sun atlas (m); 0: it did not sample it.
''', r'''    /// bbport (r76_sun-fog-outdoors): the scene's instances in TLAS order (RtShadow::GateTable,
    /// filled only with BB_VOLUMETRIC_GATE_PROBE=1; null: no scene), for the next Integrate.
    void SetSunSceneTable(const std::vector<VolumetricOcclusion::GateInstance>* table) noexcept {
        sun_scene_table = table;
    }
    /// bbport (r76_sun-fog-outdoors): the light as the host reads it at this resolve
    /// (VolumetricOcclusion::MakeSunLight), for the next Integrate's line (SayLight).
    void SetSunLight(const VolumetricOcclusion::SunLight& light) noexcept {
        sun_light = light;
    }
    /// How far the last Integrate marched through the sun atlas (m); 0: it did not sample it.
'''),
        (r'''    bool GateReady();
    void RecordGate(const ContactShadow::Inputs& in, u32 offsets);
''', r'''    bool GateReady();
    void RecordGate(const ContactShadow::Inputs& in, u32 offsets, bool probing, bool viewing,
                    const vk::DescriptorImageInfo& depth);
    // bbport (r76_sun-fog-outdoors): BB_VOLUMETRIC_GATE_PROBE / BB_VOLUMETRIC_GATE_VIEW
    bool DiagReady();
    bool EnsureGateView();
    void ReadGateProbe();
    void SayLight();
'''),
        (r'''    VideoCore::UniqueImage gate;
    vk::UniqueImageView gate_view;
    u64 gate_marches = 0, gate_traced = 0;
    bool gate_tried = false, gate_failed = false;
''', r'''    VideoCore::UniqueImage gate;
    vk::UniqueImageView gate_view;
    // bbport (r76_sun-fog-outdoors): each column's first open slice (volumetric_rt_gate.comp)
    VideoCore::UniqueImage gate_first;
    vk::UniqueImageView gate_first_view;
    u64 gate_marches = 0, gate_traced = 0;
    bool gate_tried = false, gate_failed = false;
    bool gate_off_said = false; ///< bbport (r76_sun-fog-outdoors): the once-line of an ungated run
    // bbport (r76_sun-fog-outdoors): the gate's diagnostics (DiagReady, EnsureGateView, made only
    // with their knobs): the DIAG build of the gate and the GATE_VIEW builds of the march and the
    // composite; each cell's band; the view's image (the march's size); the probe's words on the
    // GPU and their copy for the host; the instances and light of the march probed
    Pass gate_diag, integrate_gated_view, composite_view;
    VideoCore::UniqueImage gate_band;
    vk::UniqueImageView gate_band_view;
    VideoCore::UniqueImage gate_view_image;
    vk::UniqueImageView gate_view_image_view;
    u32 gate_view_width = 0, gate_view_height = 0;
    std::unique_ptr<VideoCore::Buffer> probe_buffer, probe_readback;
    const std::vector<VolumetricOcclusion::GateInstance>* sun_scene_table = nullptr;
    std::vector<VolumetricOcclusion::GateInstance> probe_table;
    VolumetricOcclusion::SunLight sun_light{}, probe_light{};
    u32 probe_mask = 0;
    u64 probe_marches = 0, probe_due = 120, probe_tick = 0;
    bool probe_pending = false, diag_tried = false, diag_failed = false, diag_said = false;
    bool view_drawn = false; ///< this frame's march wrote the view's image (Composite reads it)
    // bbport (r76_sun-fog-outdoors): SayLight's last direction said, its march and the line count
    std::array<float, 3> light_said{};
    u64 light_marches = 0, light_said_at = 0;
    u32 light_lines = 0;
'''),
    ],
    R + "vk_volumetric_light.cpp": [
        (r'''#include <cstdlib>
#include <vector>
''', r'''#include <cstdlib>
#include <cstring> // bbport (r76_sun-fog-outdoors)
#include <string>  // bbport (r76_sun-fog-outdoors)
#include <vector>
'''),
        (r'''#include "video_core/host_shaders/volumetric_rt_gate_comp.h"
''', r'''#include "video_core/host_shaders/volumetric_rt_gate_comp.h"
// bbport (r76_sun-fog-outdoors): the gate's diagnostics (BB_VOLUMETRIC_GATE_PROBE / _VIEW)
#include "video_core/host_shaders/volumetric_light_composite_gate_view_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_gate_view_comp.h"
#include "video_core/host_shaders/volumetric_rt_gate_diag_comp.h"
'''),
        (r'''constexpr float GateMaxDistance = 800.0f;
''', r'''constexpr float GateMaxDistance = 800.0f;
// bbport (r76_sun-fog-outdoors): volumetric_rt_gate.comp's workgroup is a 2x2 block of columns with
// all their slices (local_size 2, 2, 32), so that it finds each column's first open slice; the
// shader's local size and RecordGate's dispatch hold only together with these sizes.
static_assert(GateSlices == 32 && GateWidth % 2 == 0 && GateHeight % 2 == 0);
// bbport (r76_sun-fog-outdoors): the gate probe's buffer: its words (volumetric_rt_gate.comp's
// block GateProbe, VolumetricOcclusion::GateProbe*), then the instances' masks, a byte each
static_assert(GateSlices == VolumetricOcclusion::GateProbeSlices);
constexpr u32 GateProbeHeaderBytes = VolumetricOcclusion::GateProbeWords * 4;
constexpr u32 GateProbeBytes = GateProbeHeaderBytes + VolumetricOcclusion::GateProbeInstancesMost;
static_assert(GateProbeBytes - GateProbeHeaderBytes <= 65536, "vkCmdUpdateBuffer takes at most 64 KiB");
'''),
        (r'''// bbport (r51b_volumetric-rt-check): made at the gate's first use, only with BB_VOLUMETRIC_RT_GATE
// and a ray traced scene, so a GPU without ray queries never makes them. Failing leaves the march
// as stage A left it.
''', r'''// bbport (r51b_volumetric-rt-check): made at the gate's first use: the first march with a ray
// traced scene while BB_VOLUMETRIC_RT_GATE is not 0 (r76_sun-fog-outdoors: not set is 1), so a GPU
// without ray queries never makes them. Failing leaves the march as stage A left it.
'''),
        (r'''        EffectPass::HasRoom(instance, u64(GateWidth) * GateHeight * GateSlices) &&
''', r'''        // bbport (r76_sun-fog-outdoors): and the column image, a byte a column
        EffectPass::HasRoom(instance, u64(GateWidth) * GateHeight * (GateSlices + 1)) &&
'''),
        (r'''        CreatePass(gate_volume, {eStorageBuffer, eStorageBuffer, eAccelerationStructureKHR, eStorageImage},
''', r'''        CreatePass(gate_volume, {eStorageBuffer, eStorageBuffer, eAccelerationStructureKHR, eStorageImage,
                                 eStorageImage}, // bbport (r76_sun-fog-outdoors): gate_first
'''),
        (r'''                    eStorageImage, eStorageImage, eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_INTEGRATE_GATE_COMP,''', r'''                    eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_INTEGRATE_GATE_COMP,'''),
        (r'''                    eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_REPAIR_GATE_COMP,''', r'''                    eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
                    eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_REPAIR_GATE_COMP,'''),
        (r'''    SetObjectName(device, vk::Image(gate), "Volumetric sun gate (ray traced)");
    std::printf("Volumetric lighting (r51b): ray traced sun gate, %ux%ux%u cells, one ray each, "
                "scene mask 0x%x (BB_VOLUMETRIC_RT_GATE)\n",
                GateWidth, GateHeight, GateSlices, sun_scene_mask);
''', r'''    SetObjectName(device, vk::Image(gate), "Volumetric sun gate (ray traced)");
    // bbport (r76_sun-fog-outdoors): each column's first open slice (volumetric_rt_gate.comp)
    gate_first = VideoCore::UniqueImage(device, instance.GetAllocator());
    gate_first.Create({
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR8Unorm,
        .extent = {GateWidth, GateHeight, 1}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    gate_first_view = Check<"create volumetric sun gate column view">(device.createImageViewUnique({
        .image = vk::Image(gate_first), .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR8Unorm, .subresourceRange = ColorRange,
    }));
    SetObjectName(device, vk::Image(gate_first), "Volumetric sun gate: first open slice");
    std::printf("Volumetric lighting (r51b): ray traced sun gate, %ux%ux%u cells, one ray each, "
                "scene mask 0x%x (BB_VOLUMETRIC_RT_GATE %u, %s); r76: a pixel's march starts at "
                "the first open cell of its columns\n",
                GateWidth, GateHeight, GateSlices, sun_scene_mask, VolumetricOcclusion::RtGateMask(),
                VolumetricOcclusion::RtGateByDefault() ? "the default" : "set");
'''),
        (r'''// the march (volumetric_rt_gate.comp).
void VolumetricLight::RecordGate(const ContactShadow::Inputs& in, u32 offsets) {
    const GateParams params{offsets, reach, sun_scene_mask, GateMaxDistance};
    const vk::DescriptorBufferInfo cb{in.constants, in.constants_offset, in.constants_range};
    const vk::DescriptorBufferInfo ub{in.uniforms, in.uniforms_offset, in.uniforms_range};
    const vk::DescriptorImageInfo out{{}, *gate_view, vk::ImageLayout::eGeneral};
    EffectPass::Mark(51, "volumetric sun gate");
    scheduler.RecordCrumb(
        {.name = "Volumetric sun gate (ray traced)"},
        [params, cb, ub, out, scene = sun_scene, image = vk::Image(gate),
         pipeline = *gate_volume.pipeline, layout = *gate_volume.layout](vk::CommandBuffer cmd) {
            Before(cmd);
''', r'''// the march (volumetric_rt_gate.comp). bbport (r76_sun-fog-outdoors): and each column's first open
// slice (gate_first); the gate's profile row is pinned (printed below the BB_GPU_PROFILE_ROWS cut).
// With `probing` or `viewing` (BB_VOLUMETRIC_GATE_PROBE / _VIEW) the DIAG build traces instead: the
// same cells, to the nearest hit; probing also writes this frame's instance masks before it and
// copies the probe's words to the host after it (ReadGateProbe once the GPU is past this tick).
// `depth`: the march's camera depth (its depth_tex), which the DIAG build reads so that the probe
// counts only the cells in front of the visible surface.
void VolumetricLight::RecordGate(const ContactShadow::Inputs& in, u32 offsets, bool probing,
                                 bool viewing, const vk::DescriptorImageInfo& depth) {
    const bool diag = probing || viewing;
    const u32 diag_bits = (probing ? VolumetricOcclusion::GateDiagProbe : 0u) |
                          (viewing ? VolumetricOcclusion::GateDiagBand : 0u);
    const GateParams params{offsets, reach, sun_scene_mask | diag_bits, GateMaxDistance};
    const vk::DescriptorBufferInfo cb{in.constants, in.constants_offset, in.constants_range};
    const vk::DescriptorBufferInfo ub{in.uniforms, in.uniforms_offset, in.uniforms_range};
    const vk::DescriptorImageInfo out{{}, *gate_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo first_out{{}, *gate_first_view, vk::ImageLayout::eGeneral};
    // bbport (r76_sun-fog-outdoors): the DIAG build's band image and probe words (bound whenever it
    // runs; DiagReady made both)
    const vk::DescriptorImageInfo band_out{{}, *gate_band_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorBufferInfo probe_info{diag ? probe_buffer->Handle() : vk::Buffer{}, 0,
                                              GateProbeBytes};
    std::vector<u32> masks =
        probing ? VolumetricOcclusion::PackGateMasks(probe_table) : std::vector<u32>{};
    const u32 mask_bytes = u32(masks.size() * sizeof(u32)); // before the capture moves `masks`
    EffectPass::Mark(51, "volumetric sun gate", true);
    scheduler.RecordCrumb(
        {.name = "Volumetric sun gate (ray traced)"},
        [params, cb, ub, out, first_out, band_out, probe_info, depth, diag, probing, mask_bytes,
         masks = std::move(masks), readback = probing ? probe_readback->Handle() : vk::Buffer{},
         scene = sun_scene, image = vk::Image(gate), first_image = vk::Image(gate_first),
         band_image = vk::Image(gate_band),
         pipeline = diag ? *gate_diag.pipeline : *gate_volume.pipeline,
         layout = diag ? *gate_diag.layout : *gate_volume.layout](vk::CommandBuffer cmd) {
            if (probing) {
                // bbport (r76_sun-fog-outdoors): the probe's words from 0 and this frame's masks
                // (after the last probe's copy; Before() orders the dispatch after these writes)
                EffectPass::MemoryBarrier(cmd, vk::PipelineStageFlagBits2::eAllCommands,
                                          vk::AccessFlagBits2::eMemoryRead |
                                              vk::AccessFlagBits2::eMemoryWrite,
                                          vk::PipelineStageFlagBits2::eTransfer,
                                          vk::AccessFlagBits2::eTransferWrite);
                cmd.fillBuffer(probe_info.buffer, 0, GateProbeHeaderBytes, 0);
                if (mask_bytes != 0) {
                    cmd.updateBuffer(probe_info.buffer, GateProbeHeaderBytes, mask_bytes,
                                     masks.data());
                }
            }
            Before(cmd);
'''),
        (r'''                .image = image, .subresourceRange = ColorRange,
            };
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
            const vk::WriteDescriptorSetAccelerationStructureKHR scene_info{
''', r'''                .image = image, .subresourceRange = ColorRange,
            };
            // bbport (r76_sun-fog-outdoors): the column image is written whole every frame too; the
            // DIAG build's band image as well (whole when the view asks; unread otherwise)
            auto first_barrier = barrier;
            first_barrier.image = first_image;
            auto band_barrier = barrier;
            band_barrier.image = band_image;
            const std::array<vk::ImageMemoryBarrier2, 3> barriers{barrier, first_barrier, band_barrier};
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = diag ? 3u : 2u,
                                  .pImageMemoryBarriers = barriers.data()});
            const vk::WriteDescriptorSetAccelerationStructureKHR scene_info{
'''),
        (r'''            const std::array<vk::WriteDescriptorSet, 4> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &cb},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &ub},
                {.pNext = &scene_info, .dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eAccelerationStructureKHR},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &out},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params), &params);
            cmd.dispatch((GateWidth + 3) / 4, (GateHeight + 3) / 4, (GateSlices + 3) / 4);
            After(cmd);
        });
}
''', r'''            const std::array<vk::WriteDescriptorSet, 8> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &cb},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &ub},
                {.pNext = &scene_info, .dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eAccelerationStructureKHR},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &out},
                {.dstBinding = 4, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &first_out},
                // bbport (r76_sun-fog-outdoors): the DIAG build's own three
                {.dstBinding = 5, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &band_out},
                {.dstBinding = 6, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &probe_info},
                {.dstBinding = 7, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &depth},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                                    std::span{writes.data(), diag ? 8u : 5u});
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params), &params);
            cmd.dispatch(GateWidth / 2, GateHeight / 2, GateSlices / 32); // (r76) 2x2x32 groups
            if (probing) {
                // bbport (r76_sun-fog-outdoors): the probe's words to the host
                EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite,
                                          vk::PipelineStageFlagBits2::eCopy,
                                          vk::AccessFlagBits2::eTransferRead);
                cmd.copyBuffer(probe_info.buffer, readback,
                               vk::BufferCopy{0, 0, GateProbeHeaderBytes});
                EffectPass::MemoryBarrier(cmd, vk::PipelineStageFlagBits2::eCopy,
                                          vk::AccessFlagBits2::eTransferWrite,
                                          vk::PipelineStageFlagBits2::eHost,
                                          vk::AccessFlagBits2::eHostRead);
            }
            After(cmd);
        });
    if (probing) {
        probe_pending = true;
        probe_tick = scheduler.CurrentTick();
    }
}

// bbport (r76_sun-fog-outdoors): BB_VOLUMETRIC_GATE_PROBE=1 or BB_VOLUMETRIC_GATE_VIEW=1 only, made
// at the first gated march with either set: the gate's DIAG build (ray queries, which the gate's
// own build has proven), its band image and the probe's buffers; with the view also the march's and
// the composite's GATE_VIEW builds. Failing leaves the gate as it is without them.
bool VolumetricLight::DiagReady() {
    if (diag_tried) {
        return !diag_failed;
    }
    diag_tried = true;
    using enum vk::DescriptorType;
    bool made =
        EffectPass::HasRoom(instance, u64(GateWidth) * GateHeight * GateSlices + GateProbeBytes +
                                          GateProbeHeaderBytes) &&
        CreatePass(gate_diag,
                   {eStorageBuffer, eStorageBuffer, eAccelerationStructureKHR, eStorageImage,
                    eStorageImage, eStorageImage, eStorageBuffer, eCombinedImageSampler},
                   VOLUMETRIC_RT_GATE_DIAG_COMP, sizeof(GateParams), "Volumetric sun gate (diag)");
    if (made && VolumetricOcclusion::GateView()) {
        made = EffectPass::StorageFormat(instance, vk::Format::eR8G8B8A8Unorm) &&
               CreatePass(integrate_gated_view,
                          {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                           eCombinedImageSampler, eStorageImage, eStorageImage,
                           eCombinedImageSampler, eCombinedImageSampler, eStorageImage,
                           eCombinedImageSampler},
                          VOLUMETRIC_LIGHT_INTEGRATE_GATE_VIEW_COMP, sizeof(Params),
                          "Volumetric integrate (gate view)") &&
               CreatePass(composite_view,
                          {eCombinedImageSampler, eCombinedImageSampler, eStorageImage,
                           eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                           eCombinedImageSampler},
                          VOLUMETRIC_LIGHT_COMPOSITE_GATE_VIEW_COMP, sizeof(u32),
                          "Volumetric composite (gate view)");
    }
    if (made) {
        probe_buffer = std::make_unique<VideoCore::Buffer>(
            instance, 0, GateProbeBytes, VideoCore::MemoryType::DeviceLocal,
            "Volumetric sun gate probe");
        probe_readback = std::make_unique<VideoCore::Buffer>(
            instance, 0, GateProbeHeaderBytes, VideoCore::MemoryType::HostCached,
            "Volumetric sun gate probe readback");
        made = probe_readback->mapped_data.size() >= GateProbeHeaderBytes;
    }
    if (!made) {
        diag_failed = true;
        std::printf("Volumetric lighting (r76): gate probe and view off - their passes or buffers "
                    "could not be made; the gate runs as without them\n");
        return false;
    }
    const auto device = instance.GetDevice();
    gate_band = VideoCore::UniqueImage(device, instance.GetAllocator());
    gate_band.Create({
        .imageType = vk::ImageType::e3D,
        .format = vk::Format::eR8Unorm,
        .extent = {GateWidth, GateHeight, GateSlices}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    gate_band_view = Check<"create volumetric sun gate band view">(device.createImageViewUnique({
        .image = vk::Image(gate_band), .viewType = vk::ImageViewType::e3D,
        .format = vk::Format::eR8Unorm, .subresourceRange = ColorRange,
    }));
    SetObjectName(device, vk::Image(gate_band), "Volumetric sun gate: hit distance band");
    std::printf("Volumetric lighting (r76): gate diagnostics made (nearest-hit gate build, %ux%ux%u "
                "band cells%s)\n",
                GateWidth, GateHeight, GateSlices,
                VolumetricOcclusion::GateView() ? ", the view's march and composite builds" : "");
    return true;
}

// bbport (r76_sun-fog-outdoors): BB_VOLUMETRIC_GATE_VIEW=1: the view's image at the march's size
// (RGBA8), made again when that changes. False: no room, no view this march.
bool VolumetricLight::EnsureGateView() {
    if (gate_view_image && gate_view_width == width && gate_view_height == height) {
        return true;
    }
    if (gate_view_image) {
        scheduler.DeferOperation([image = std::move(gate_view_image),
                                  view = std::move(gate_view_image_view)]() mutable {
            view.reset();
            image.Destroy();
        });
    }
    gate_view_width = gate_view_height = 0;
    if (width == 0 || height == 0 || !EffectPass::HasRoom(instance, 4ull * width * height)) {
        return false;
    }
    const auto device = instance.GetDevice();
    gate_view_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    gate_view_image.Create({
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR8G8B8A8Unorm,
        .extent = {width, height, 1}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    gate_view_image_view = Check<"create volumetric sun gate view image view">(
        device.createImageViewUnique({
            .image = vk::Image(gate_view_image), .viewType = vk::ImageViewType::e2D,
            .format = vk::Format::eR8G8B8A8Unorm, .subresourceRange = ColorRange,
        }));
    SetObjectName(device, vk::Image(gate_view_image), "Volumetric sun gate view");
    gate_view_width = width;
    gate_view_height = height;
    return true;
}

// bbport (r76_sun-fog-outdoors): the probe's line from the words the GPU copied back (the march
// RecordGate probed): the light's direction (the GPU's own, view space, turned to world with that
// frame's camera), the shut cells in front of the visible surface by the nearest hit's distance and
// of them the camera-only ones, and the centre column's surface and all its slices with the hit
// instance's key, triangles and record mask (the
// instance id is its index in the TLAS records, RtShadow::GateTable). Last, how far the host's
// copy of the direction (SetSunLight) lies from the GPU's.
void VolumetricLight::ReadGateProbe() {
    using namespace VolumetricOcclusion;
    probe_pending = false;
    std::array<u32, GateProbeWords> w{};
    probe_readback->Invalidate(0, sizeof(w));
    std::memcpy(w.data(), probe_readback->mapped_data.data(), sizeof(w));
    const std::array<float, 3> view{std::bit_cast<float>(w[GateProbeDirectionAt]),
                                    std::bit_cast<float>(w[GateProbeDirectionAt + 1]),
                                    std::bit_cast<float>(w[GateProbeDirectionAt + 2])};
    const std::array<float, 3> world =
        probe_light.camera ? ToWorld(probe_light.view_to_world, view) : std::array<float, 3>{};
    char light[160];
    if (world != std::array<float, 3>{}) {
        const auto angles = ElevationAzimuth(world);
        std::snprintf(light, sizeof(light), "light world (%.3f,%.3f,%.3f) elevation %.1f deg azimuth %.1f",
                      world[0], world[1], world[2], angles[0], angles[1]);
    } else {
        std::snprintf(light, sizeof(light), "light world unknown (view %.3f,%.3f,%.3f, camera %s)",
                      view[0], view[1], view[2], probe_light.camera ? "known" : "unknown");
    }
    std::string column;
    for (u32 s = 0; s < GateProbeSlices;) {
        const u32 t = w[GateProbeColumnAt + 2 * s];
        const u32 id = w[GateProbeColumnAt + 2 * s + 1];
        char part[96];
        if (t == GateColumnOpen || t == GateColumnNotAsked) {
            u32 end = s + 1;
            while (end < GateProbeSlices && w[GateProbeColumnAt + 2 * end] == t) {
                ++end;
            }
            const char* what = t == GateColumnOpen ? "open" : "-";
            if (end - s > 1) {
                std::snprintf(part, sizeof(part), " %u-%u:%s", s, end - 1, what);
            } else {
                std::snprintf(part, sizeof(part), " %u:%s", s, what);
            }
            s = end;
        } else {
            const float distance = std::bit_cast<float>(t);
            if (id < probe_table.size()) {
                const GateInstance& e = probe_table[id];
                std::snprintf(part, sizeof(part), " %u:%.1f m:%016llx:%u:0x%02x", s, distance,
                              static_cast<unsigned long long>(e.key), e.triangles, u32(e.mask));
            } else {
                std::snprintf(part, sizeof(part), " %u:%.1f m:instance %u not in the table", s,
                              distance, id);
            }
            ++s;
        }
        column += part;
    }
    char host[64];
    if (probe_light.valid && view != std::array<float, 3>{}) {
        std::snprintf(host, sizeof(host), "%.2f deg", AngleDeg(probe_light.view, view));
    } else {
        std::snprintf(host, sizeof(host), "unknown");
    }
    // The centre column's visible surface (its slices beyond it are not counted above)
    const float surface = std::bit_cast<float>(w[GateProbeSurfaceAt]);
    char surface_text[32];
    if (!(surface >= 0.0f)) {
        std::snprintf(surface_text, sizeof(surface_text), "none");
    } else if (surface >= 1e29f) {
        std::snprintf(surface_text, sizeof(surface_text), "sky");
    } else {
        std::snprintf(surface_text, sizeof(surface_text), "%.1f m", surface);
    }
    std::printf("Volumetric lighting (r76): gate probe: %s; shut cells in front of the surface "
                "<5/5-15/15-40/40-150/150-800 m = %u/%u/%u/%u/%u, camera-only %u/%u/%u/%u/%u; "
                "centre column (surface %s)%s; %u cells in front of the surface asked, "
                "mask 0x%x, %llu instances in the table; host light differs by %s\n",
                light, w[GateProbeShutAt], w[GateProbeShutAt + 1], w[GateProbeShutAt + 2],
                w[GateProbeShutAt + 3], w[GateProbeShutAt + 4], w[GateProbeCameraOnlyAt],
                w[GateProbeCameraOnlyAt + 1], w[GateProbeCameraOnlyAt + 2],
                w[GateProbeCameraOnlyAt + 3], w[GateProbeCameraOnlyAt + 4], surface_text,
                column.c_str(), w[GateProbeAskedAt], probe_mask,
                static_cast<unsigned long long>(probe_table.size()), host);
}

// bbport (r76_sun-fog-outdoors): the direction toward the sun or moon as the host read it at this
// resolve (SetSunLight), said at the first march that knows it and again when it moved by more
// than 1 degree from the one said last: at most one line in 60 marches and 100 lines in all (a
// fault in the turn to world space would show as a line at every camera turn).
void VolumetricLight::SayLight() {
    using namespace VolumetricOcclusion;
    ++light_marches;
    if (!sun_light.valid) {
        return;
    }
    float change = 0.0f;
    if (light_lines > 0) {
        change = AngleDeg(sun_light.world, light_said);
        if (!(change > 1.0f) || light_marches - light_said_at < 60) {
            return;
        }
        if (light_lines >= 100) {
            if (light_lines == 100) {
                ++light_lines;
                std::printf("Volumetric lighting (r76): light direction changed again; no more "
                            "lines of it\n");
            }
            return;
        }
    }
    ++light_lines;
    light_said = sun_light.world;
    light_said_at = light_marches;
    const auto angles = ElevationAzimuth(sun_light.world);
    char why[48];
    if (light_lines == 1) {
        std::snprintf(why, sizeof(why), "first march");
    } else {
        std::snprintf(why, sizeof(why), "moved by %.1f deg", change);
    }
    std::printf("Volumetric lighting (r76): light direction world (%.3f, %.3f, %.3f) elevation "
                "%.1f deg azimuth %.1f deg, toward the sun or moon (%s)\n",
                sun_light.world[0], sun_light.world[1], sun_light.world[2], angles[0], angles[1],
                why);
}
'''),
        (r'''    // bbport (r51b_volumetric-rt-check): with BB_VOLUMETRIC_RT_GATE and this frame's ray traced
    // scene (SetSunScene), one ray toward the sun from each cell of the gate first; the march then
    // multiplies its atlas answer by the gate. Without them the march is stage A's, unchanged.
    const bool gated = live_strength > 0.0f && sun_scene && sun_scene_mask != 0 && GateReady();
    if (live_strength > 0.0f && VolumetricOcclusion::RtGateMask() != 0) {
        gate_traced += gated ? 1 : 0;
        if (++gate_marches % 600 == 0) {
            std::printf("Volumetric lighting (r51b): ray traced sun gate on %llu of 600 marches, "
                        "BB_VOLUMETRIC_RT_GATE %u (0 of 600: no ray traced scene, stage A only)\n",
                        static_cast<unsigned long long>(gate_traced), sun_scene_mask);
            gate_traced = 0;
        }
    }
    if (gated) {
        RecordGate(in, in.constants_offset_word);
    }
    sun_scene = vk::AccelerationStructureKHR{};
    const vk::DescriptorImageInfo gi{*gate_sampler, *gate_view, vk::ImageLayout::eGeneral};
''', r'''    // bbport (r51b_volumetric-rt-check): with this frame's ray traced scene and a gate mask
    // (SetSunScene; r76_sun-fog-outdoors: the rasterizer passes BB_VOLUMETRIC_RT_GATE's mask, 1 when
    // not set, whenever it prepared a scene), one ray toward the sun from each cell of the gate
    // first; the march then multiplies its atlas answer by the gate. Without them the march is
    // stage A's, unchanged.
    const bool gated = live_strength > 0.0f && sun_scene && sun_scene_mask != 0 && GateReady();
    const u32 gate_knob = VolumetricOcclusion::RtGateMask();
    if (live_strength > 0.0f && gate_knob == 0 && !gate_off_said) {
        gate_off_said = true;
        std::printf("Volumetric lighting (r76): ray traced sun gate off (BB_VOLUMETRIC_RT_GATE=0): "
                    "the sun fog follows the sun atlas alone and can show indoors\n");
    }
    if (live_strength > 0.0f && gate_knob != 0) {
        gate_traced += gated ? 1 : 0;
        if (++gate_marches % 600 == 0) {
            // bbport (r76_sun-fog-outdoors): only once a gate was tried (a ray traced scene came at
            // least once); a player without ray tracing gets the once-line below and nothing more
            if (gate_traced != 0 || gate_tried) {
                std::printf("Volumetric lighting (r51b): ray traced sun gate on %llu of 600 marches, "
                            "BB_VOLUMETRIC_RT_GATE %u%s (0 of 600: no ray traced scene, stage A "
                            "only)\n",
                            static_cast<unsigned long long>(gate_traced), gate_knob,
                            VolumetricOcclusion::RtGateByDefault() ? " (the default)" : "");
            }
            // bbport (r76_sun-fog-outdoors): once, at the first 600 marches none of which had a
            // scene (marches during a load lack one too, so not at the first march without one)
            if (gate_traced == 0 && !gate_failed && !gate_off_said) {
                gate_off_said = true;
                std::printf("Volumetric lighting (r76): no ray traced scene in 600 marches "
                            "(effect_ray_tracing off, or the ray traced sun, lamps and bounced "
                            "light all off): the sun fog is not gated and can show indoors, as "
                            "before r76\n");
            }
            gate_traced = 0;
        }
    }
    // bbport (r76_sun-fog-outdoors): the light's direction (SayLight, host only); the probe's line
    // once the GPU is past its copy; BB_VOLUMETRIC_GATE_PROBE / _VIEW (read once, said once): the
    // gate's DIAG build runs on a probe march (the 120th gated march, then every 600th) and, with
    // the view, on every gated march. Both off: nothing below changes the gate or the march.
    const bool probe_knob = VolumetricOcclusion::GateProbe();
    const bool view_knob = VolumetricOcclusion::GateView();
    if (live_strength > 0.0f) {
        SayLight();
        if ((probe_knob || view_knob) && !diag_said) {
            diag_said = true;
            std::printf("Volumetric lighting (r76): gate probe %s (BB_VOLUMETRIC_GATE_PROBE), gate "
                        "view %s (BB_VOLUMETRIC_GATE_VIEW); they act only on marches the gate runs "
                        "on\n",
                        probe_knob ? "on" : "off", view_knob ? "on" : "off");
        }
    }
    if (probe_pending && scheduler.IsFree(probe_tick)) {
        ReadGateProbe();
    }
    const bool diag = gated && (probe_knob || view_knob) && DiagReady();
    bool probing = false;
    if (diag && probe_knob && !probe_pending && ++probe_marches >= probe_due) {
        probing = true;
        probe_marches = 0;
        probe_due = 600;
        if (sun_scene_table) {
            probe_table = *sun_scene_table;
        } else {
            probe_table.clear();
        }
        probe_light = sun_light;
        probe_mask = sun_scene_mask;
    }
    const bool viewing = diag && view_knob && EnsureGateView();
    view_drawn = viewing;
    const vk::DescriptorImageInfo gi{*gate_sampler, *gate_view, vk::ImageLayout::eGeneral};
    // bbport (r76_sun-fog-outdoors): each column's first open slice, read with four gathers
    const vk::DescriptorImageInfo gfi{*gate_sampler, *gate_first_view, vk::ImageLayout::eGeneral};
    // bbport (r76_sun-fog-outdoors): BB_VOLUMETRIC_GATE_VIEW=1: the view's image and the bands
    const vk::DescriptorImageInfo gvo{{}, *gate_view_image_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo gbi{*gate_sampler, *gate_band_view, vk::ImageLayout::eGeneral};
'''),
        (r'''        cmd.clearColorImage(image, vk::ImageLayout::eGeneral,
                            vk::ClearColorValue{std::array<float, 4>{}}, ColorRange);
    });
    for (u32 pass_index = 0; pass_index < 2; ++pass_index) {
''', r'''        cmd.clearColorImage(image, vk::ImageLayout::eGeneral,
                            vk::ClearColorValue{std::array<float, 4>{}}, ColorRange);
    });
    // bbport (r76_sun-fog-outdoors): the gate after the lamp fog image's clear (before it in r51b),
    // so that the gate's profile row holds the gate's work alone
    if (gated) {
        RecordGate(in, in.constants_offset_word, probing, viewing, di);
    }
    sun_scene = vk::AccelerationStructureKHR{};
    sun_scene_table = nullptr;
    for (u32 pass_index = 0; pass_index < 2; ++pass_index) {
'''),
        (r'''        const auto& pass = repairing ? (gated ? repair_gated : repair)
                                     : (gated ? integrate_gated : integrate);
''', r'''        const auto& pass = repairing ? (gated ? repair_gated : repair)
                                     : (gated ? (viewing ? integrate_gated_view : integrate_gated)
                                              : integrate);
'''),
        (r'''        EffectPass::Mark(7, "volumetric sunlight");
''', r'''        // bbport (r76_sun-fog-outdoors): pinned, so this row and the gate's always show together
        EffectPass::Mark(7, "volumetric sunlight", true);
'''),
        (r'''        [params, di, si, out, repaired, zout, in, repairing, gi, gated,
''', r'''        [params, di, si, out, repaired, zout, in, repairing, gi, gfi, gated,
         viewing = viewing && !repairing, gvo, gbi, view_image = vk::Image(gate_view_image),
'''),
        (r'''                cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1,
                                      .pImageMemoryBarriers = &depth_barrier});
            }
''', r'''                cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1,
                                      .pImageMemoryBarriers = &depth_barrier});
            }
            if (viewing) { // bbport (r76_sun-fog-outdoors): written whole by the march
                auto view_barrier = barrier;
                view_barrier.image = view_image;
                cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1,
                                      .pImageMemoryBarriers = &view_barrier});
            }
'''),
        (r'''            std::array<vk::WriteDescriptorSet, 8> writes{{
''', r'''            std::array<vk::WriteDescriptorSet, 10> writes{{
'''),
        (r'''                    .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &gi};
                ++count;
            }
''', r'''                    .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &gi};
                ++count;
                // bbport (r76_sun-fog-outdoors): and each column's first open slice
                writes[count] = vk::WriteDescriptorSet{
                    .dstBinding = count, .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &gfi};
                ++count;
            }
            if (viewing) { // bbport (r76_sun-fog-outdoors): the GATE_VIEW build's 8 and 9
                writes[count] = vk::WriteDescriptorSet{
                    .dstBinding = count, .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &gvo};
                ++count;
                writes[count] = vk::WriteDescriptorSet{
                    .dstBinding = count, .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &gbi};
                ++count;
            }
'''),
        (r'''    const bool has_tint = tinted;
    const auto seen_lights = fog_lights.Lights();
    Reset();
''', r'''    const bool has_tint = tinted;
    const auto seen_lights = fog_lights.Lights();
    // bbport (r76_sun-fog-outdoors): BB_VOLUMETRIC_GATE_VIEW=1 and this frame's march wrote the view
    const bool gate_viewed = std::exchange(view_drawn, false);
    Reset();
'''),
        (r'''    EffectPass::Mark(11, "volumetric composite");
    scheduler.RecordCrumb(
        {.name = "Directional volumetric composite"},
        [fi, di, out, repaired, points, state, w, h, pipeline = *composite.pipeline,
         layout = *composite.layout](vk::CommandBuffer cmd) {
            Before(cmd);
            const std::array<vk::WriteDescriptorSet, 6> writes{{
''', r'''    // bbport (r76_sun-fog-outdoors): the view's image, for the composite's GATE_VIEW build
    const vk::DescriptorImageInfo gvi{*sampler, *gate_view_image_view, vk::ImageLayout::eGeneral};
    EffectPass::Mark(11, "volumetric composite");
    scheduler.RecordCrumb(
        {.name = "Directional volumetric composite"},
        [fi, di, out, repaired, points, state, w, h, gate_viewed, gvi,
         pipeline = gate_viewed ? *composite_view.pipeline : *composite.pipeline,
         layout = gate_viewed ? *composite_view.layout : *composite.layout](vk::CommandBuffer cmd) {
            Before(cmd);
            const std::array<vk::WriteDescriptorSet, 7> writes{{
'''),
        (r'''                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &points},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
''', r'''                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &points},
                {.dstBinding = 6, .descriptorCount = 1, // bbport (r76_sun-fog-outdoors): GATE_VIEW
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &gvi},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                                    std::span{writes.data(), gate_viewed ? 7u : 6u});
'''),
    ],
    R + "vk_rasterizer_effects.cpp": [
        (r'''        // that build forward and the sun's call then returns at once. No scene: stage A's march.
        const u32 rt_gate = VolumetricOcclusion::RtGateMask();
        volumetric_light->SetSunScene(rt_gate != 0 && rt_shadow->PrepareScene()
                                          ? rt_shadow->Scene()
                                          : vk::AccelerationStructureKHR{},
                                      rt_gate);
''', r'''        // that build forward and the sun's call then returns at once. No scene: stage A's march.
        // bbport (r76_sun-fog-outdoors): unset is 1 (the sun's casters), so the gate runs whenever
        // RtShadow builds a scene (effect_ray_tracing on and RtShadow::SceneWanted: the ray traced
        // sun, lamps or bounced light); 0 turns it off. Without a scene the mask in force is 0
        // (GateInForce). With the ray traced sun off the next reader of the scene (the lamps)
        // builds or refits the TLAS again only if entries arrived since this call.
        const u32 rt_gate = VolumetricOcclusion::RtGateMask();
        const bool rt_scene = rt_gate != 0 && rt_shadow->PrepareScene();
        volumetric_light->SetSunScene(rt_scene ? rt_shadow->Scene() : vk::AccelerationStructureKHR{},
                                      VolumetricOcclusion::GateInForce(rt_gate, rt_scene));
        // bbport (r76_sun-fog-outdoors): the scene's instances in TLAS order (filled only with
        // BB_VOLUMETRIC_GATE_PROBE=1), and the direction toward the sun or moon as the host reads it
        // from this resolve's shadow constants (the 32 dwords the gate's rays take theirs from, at
        // the V# base as SunAtlasResolve reads the splits), turned to world space with this frame's
        // camera (the one PrepareScene placed the scene's instances with). A 128-byte read and a
        // 4x4 inverse; the march says it once and when it moves (VolumetricLight::SayLight).
        volumetric_light->SetSunSceneTable(rt_scene ? &rt_shadow->GateTable() : nullptr);
        {
            VolumetricOcclusion::SunLight light{};
            if (ps_info->buffers.size() >= 2 && !ps_info->buffers[0].IsSpecial()) {
                const VAddr rows = ps_info->buffers[0].GetSharp(*ps_info).base_address;
                std::array<float, 32> constants{};
                if (memory->IsValidGpuMapping(rows, 0) &&
                    memory->ClampRangeSize(rows, sizeof(constants)) == sizeof(constants)) {
                    std::memcpy(constants.data(), reinterpret_cast<const void*>(rows),
                                sizeof(constants));
                    const auto camera = camera_motion->PassMatrices();
                    light = VolumetricOcclusion::MakeSunLight(constants, camera.inv_view,
                                                              camera.valid);
                }
            }
            volumetric_light->SetSunLight(light);
        }
'''),
    ],
    R + "vk_rt_shadow.h": [
        (r'''#include "video_core/renderer_vulkan/rt_card_layers.h" // bbport (r62_leaf-stage3)
''', r'''#include "video_core/renderer_vulkan/rt_card_layers.h" // bbport (r62_leaf-stage3)
#include "video_core/renderer_vulkan/volumetric_occlusion.h" // bbport (r76_sun-fog-outdoors)
'''),
        (r'''    u8 probe_sun_path = 0;

private:
''', r'''    u8 probe_sun_path = 0;

    // bbport (r76_sun-fog-outdoors): with BB_VOLUMETRIC_GATE_PROBE=1 (read once; empty otherwise)
    // the instances of the TLAS last written, in record order: index i is the instance id a ray
    // query reports (rayQueryGetIntersectionInstanceIdEXT; the custom index is r62's card slot):
    // the entry's key (Entry::base, the draw's key from PrepareDraw: the surface probe's rt_key
    // for an entry that is neither a shared copy nor a promoted instance), its triangles and the
    // record's mask (1 sun, 2 camera pass, 4 lamps, 8 lamp cards). PrepareScene writes it with the
    // records; where PrepareScene keeps the TLAS as it was, the list stays with it.
    [[nodiscard]] const std::vector<VolumetricOcclusion::GateInstance>& GateTable() const noexcept {
        return gate_table;
    }

private:
'''),
        (r'''    std::vector<vk::AccelerationStructureInstanceKHR> r17_records, r17_tlas_records;
''', r'''    std::vector<vk::AccelerationStructureInstanceKHR> r17_records, r17_tlas_records;
    // bbport (r76_sun-fog-outdoors): GateTable, kept only with BB_VOLUMETRIC_GATE_PROBE=1
    const bool gate_table_on = VolumetricOcclusion::GateProbe();
    std::vector<VolumetricOcclusion::GateInstance> gate_table;
'''),
    ],
    R + "vk_rt_shadow.cpp": [
        (r'''constexpr u32 MaxInstances = 8192;
''', r'''constexpr u32 MaxInstances = 8192;
// bbport (r76_sun-fog-outdoors): the sun gate's probe takes every instance's mask
static_assert(VolumetricOcclusion::GateProbeInstancesMost >= MaxInstances);
'''),
        (r'''    u32 lamp_cards = 0, lamp_plants = 0, lamp_moving = 0, lamp_flips = 0;
    for (u32 i = 0; i < count; ++i) {
''', r'''    u32 lamp_cards = 0, lamp_plants = 0, lamp_moving = 0, lamp_flips = 0;
    if (gate_table_on) { // bbport (r76_sun-fog-outdoors): GateTable, with the records below
        gate_table.clear();
    }
    for (u32 i = 0; i < count; ++i) {
'''),
        (r'''        out[built++] = record;
''', r'''        out[built++] = record;
        if (gate_table_on) { // bbport (r76_sun-fog-outdoors): instance id built - 1
            gate_table.push_back({entry->base, entry->triangles, static_cast<u8>(record.mask)});
        }
'''),
    ],
    R + "vk_effect_pass.h": [
        (r'''void Mark(u64 key, const char* name);
''', r'''/// A GPU profile row "Lighting: <name>" from here on (BB_GPU_PROFILE=1). bbport
/// (r76_sun-fog-outdoors): `pinned` prints the row in every block it has time in, also below the
/// BB_GPU_PROFILE_ROWS cut (GpuProfiler::Pin).
void Mark(u64 key, const char* name, bool pinned = false);
'''),
    ],
    R + "vk_effect_pass.cpp": [
        (r'''void Mark(u64 key, const char* name) {
    if (auto* profiler = GpuProfiler::Get()) {
        profiler->Mark(0x4C49'0000ull | key, [name] { return std::string{"Lighting: "} + name; });
    }
}
''', r'''void Mark(u64 key, const char* name, bool pinned) {
    if (auto* profiler = GpuProfiler::Get()) {
        profiler->Mark(0x4C49'0000ull | key, [name] { return std::string{"Lighting: "} + name; });
        if (pinned) {
            profiler->Pin(0x4C49'0000ull | key); // bbport (r76_sun-fog-outdoors)
        }
    }
}
'''),
    ],
    R + "vk_gpu_profiler.h": [
        (r'''    void NoteDraw() {
        ++draws[current];
    }
''', r'''    void NoteDraw() {
        ++draws[current];
    }
    /// bbport (r76_sun-fog-outdoors): `key`'s row is printed in every block it has time in, also
    /// below the BB_GPU_PROFILE_ROWS cut, after the first rows and in the same form (a row of a
    /// few hundredths of a ms, as the volumetric sun gate's in a closed room, fell below it).
    void Pin(u64 key) {
        for (const u64 known : pinned) {
            if (known == key) {
                return;
            }
        }
        pinned.push_back(key);
    }
'''),
        (r'''    std::unordered_map<u64, u64> draws; ///< draws recorded under each label since the last print
''', r'''    std::unordered_map<u64, u64> draws; ///< draws recorded under each label since the last print
    std::vector<u64> pinned; ///< bbport (r76_sun-fog-outdoors): Pin
'''),
    ],
    R + "vk_gpu_profiler.cpp": [
        (r'''    for (size_t i = 0; i < std::min(sorted.size(), rows); ++i) {
        const auto& [key, total] = sorted[i];
        std::printf(''', r'''    for (size_t i = 0; i < sorted.size(); ++i) {
        const auto& [key, total] = sorted[i];
        // bbport (r76_sun-fog-outdoors): below the cut only the pinned rows (Pin)
        if (i >= rows && std::ranges::find(pinned, key) == pinned.end()) {
            continue;
        }
        std::printf('''),
    ],
    "engine/gpu/CMakeLists.txt": [
        (r'''# the gate's pass (ray queries); made only with BB_VOLUMETRIC_RT_GATE
''', r'''# the gate's pass (ray queries); made at the first march with a ray traced scene unless
# BB_VOLUMETRIC_RT_GATE=0 (r76_sun-fog-outdoors: unset is 1)
'''),
        (r'''add_host_shader(volumetric_rt_gate.comp volumetric_rt_gate_comp)
''', r'''add_host_shader(volumetric_rt_gate.comp volumetric_rt_gate_comp)
# bbport (r76_sun-fog-outdoors): the gate's diagnostics, made only with BB_VOLUMETRIC_GATE_PROBE=1
# or BB_VOLUMETRIC_GATE_VIEW=1: the gate to the nearest hit (DIAG), and with the view the march and
# the composite drawing it (GATE_VIEW); the builds above are unchanged
add_host_shader(volumetric_rt_gate.comp volumetric_rt_gate_diag_comp DIAG=1)
add_host_shader(volumetric_light.comp volumetric_light_integrate_gate_view_comp INTEGRATE=1 GATE=1 GATE_VIEW=1)
add_host_shader(volumetric_light.comp volumetric_light_composite_gate_view_comp COMPOSITE=1 GATE_VIEW=1)
'''),
    ],
    "engine/tests/test_volumetric_occlusion.cpp": [
        (r'''// the push word the shader takes apart.
''', r'''// the push word the shader takes apart. bbport (r76_sun-fog-outdoors): the defaults of both knobs,
// the gate's mask in force with and without a ray traced scene, the gate diagnostics' pure parts
// and the light's direction as the host makes it.
'''),
        (r'''#include <cassert>
#include <cstdint>
''', r'''#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <vector>
'''),
        (r'''    // The knob: a whole number 0..7, else everything on.
    assert(Parse(nullptr) == All && Parse("") == All && All == 7);
    assert(Parse("0") == 0 && Parse("1") == 1 && Parse("5") == 5 && Parse("7") == 7);
    assert(Parse("8") == All && Parse("-1") == All && Parse("3x") == All && Parse("on") == All);
''', r'''    // The knob: a whole number 0..7, else the default. bbport (r76_sun-fog-outdoors): the default
    // is 5, bits 1 and 4 (bit 2, the darkest answer of every cascade, left out); 7 is all on.
    assert(All == 7 && Default == 5 && (Default & Darkest) == 0);
    assert(Parse(nullptr) == Default && Parse("") == Default);
    assert(Parse("0") == 0 && Parse("1") == 1 && Parse("5") == 5 && Parse("7") == 7);
    assert(Parse("8") == Default && Parse("-1") == Default && Parse("3x") == Default &&
           Parse("on") == Default);

    // bbport (r76_sun-fog-outdoors): the ray traced sun gate's knob. Unset means 1 (the sun's
    // casters) with a ray traced scene and 0 (no gate) without one; "0" is off either way; 2 and 3
    // (the camera pass's geometry too) are test values.
    assert(RtGateDefault == 1);
    assert(ParseRtGate(nullptr) == 1 && ParseRtGate("") == 1);
    assert(ParseRtGate("0") == 0 && ParseRtGate("1") == 1 && ParseRtGate("2") == 2 &&
           ParseRtGate("3") == 3);
    assert(ParseRtGate("4") == 1 && ParseRtGate("on") == 1 && ParseRtGate("1x") == 1 &&
           ParseRtGate(" 1") == 1 && ParseRtGate("-1") == 1 && ParseRtGate("off") == 1);
    assert(!RtGateNamed(nullptr) && !RtGateNamed("") && !RtGateNamed("4") && !RtGateNamed("10") &&
           RtGateNamed("0") && RtGateNamed("3"));
    assert(GateInForce(ParseRtGate(nullptr), true) == 1);
    assert(GateInForce(ParseRtGate(nullptr), false) == 0);
    assert(GateInForce(ParseRtGate("0"), true) == 0 && GateInForce(ParseRtGate("0"), false) == 0);
    assert(GateInForce(ParseRtGate("3"), true) == 3 && GateInForce(ParseRtGate("2"), false) == 0);

    // bbport (r76_sun-fog-outdoors): the gate's diagnostics. Their knobs are on only as "1".
    assert(ParseOn("1") && !ParseOn(nullptr) && !ParseOn("") && !ParseOn("0") && !ParseOn("11") &&
           !ParseOn("on") && !ParseOn(" 1"));
    // The diagnostic bits lie above the 8 bits a ray takes as its instance mask.
    assert((GateDiagProbe & 0xFFu) == 0 && (GateDiagBand & 0xFFu) == 0 &&
           (GateDiagProbe & GateDiagBand) == 0 && ((3u | GateDiagProbe | GateDiagBand) & 0xFFu) == 3u);
    // The distance bands (m) as the DIAG build counts them.
    assert(GateBand(0.0f) == 1 && GateBand(4.99f) == 1 && GateBand(5.0f) == 2 &&
           GateBand(14.9f) == 2 && GateBand(15.0f) == 3 && GateBand(39.9f) == 3 &&
           GateBand(40.0f) == 4 && GateBand(149.9f) == 4 && GateBand(150.0f) == 5 &&
           GateBand(800.0f) == 5);
    // The probe's words: 5 + 5 + 1 + 3 + 64 + 1 (the centre column's surface).
    assert(GateProbeWords == 79 && GateProbeCameraOnlyAt == GateProbeShutAt + 5 &&
           GateProbeAskedAt == GateProbeCameraOnlyAt + 5 && GateProbeDirectionAt == GateProbeAskedAt + 1 &&
           GateProbeColumnAt + 2 * GateProbeSlices == GateProbeSurfaceAt &&
           GateProbeSurfaceAt + 1 == GateProbeWords);
    // The masks four to a word, instance i in byte i % 4; camera only = bit 2 without bit 1.
    {
        const std::vector<GateInstance> table{
            {1, 10, 0x05}, {2, 20, 0x06}, {3, 30, 0x07}, {4, 40, 0x02}, {5, 50, 0x0E}};
        const std::vector<std::uint32_t> words = PackGateMasks(table);
        assert(words.size() == 2 && words[0] == 0x02070605u && words[1] == 0x0Eu);
        assert(PackGateMasks({}).empty());
        assert(!GateCameraOnly(0x05) && GateCameraOnly(0x06) && !GateCameraOnly(0x07) &&
               GateCameraOnly(0x02) && GateCameraOnly(0x0E) && !GateCameraOnly(0x01));
    }
    // The light's direction as volumetric_rt_gate.comp's prepare() makes it. A projection P that
    // swaps z and w (inverse in rows 0-15) and a light matrix L (rows 16-31) chosen so that L P has
    // the rows a (0, 1, 0), b (0, 0, 1), z (1, 0, 0): a x b = (1, 0, 0) points along z, so the
    // direction toward the light is (-1, 0, 0) in view space.
    {
        const std::array<float, 32> c{0.5f, 0, 0, 0, 0, 0.25f, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0,
                                      0, 0.25f, 0, 0, 0, 0, 0, 1, 0.5f, 0, 0.5f, 0, 0, 0, 1, 0};
        std::array<float, 3> d{};
        assert(LightDirection(c, d));
        assert(std::fabs(d[0] + 1.0f) < 1e-6f && std::fabs(d[1]) < 1e-6f && std::fabs(d[2]) < 1e-6f);
        // A camera turned 90 degrees about y: view (-1, 0, 0) is world (0, 0, 1): level, azimuth 0.
        const std::array<float, 12> turned{0, 0, 1, 7, 0, 1, 0, 8, -1, 0, 0, 9};
        const SunLight light = MakeSunLight(c, turned, true);
        assert(light.valid && std::fabs(light.world[2] - 1.0f) < 1e-6f);
        const auto angles = ElevationAzimuth(light.world);
        assert(std::fabs(angles[0]) < 1e-4f && std::fabs(angles[1]) < 1e-4f);
        // Without the camera: the view direction only, not valid.
        const SunLight blind = MakeSunLight(c, turned, false);
        assert(!blind.valid && std::fabs(blind.view[0] + 1.0f) < 1e-6f);
        // No inverse projection (all zero): no direction.
        assert(!LightDirection(std::array<float, 32>{}, d));
        // Straight up is 90 degrees; +x is azimuth 90; the angle between them 90.
        assert(std::fabs(ElevationAzimuth({0, 1, 0})[0] - 90.0f) < 1e-4f);
        assert(std::fabs(ElevationAzimuth({1, 0, 0})[1] - 90.0f) < 1e-4f);
        assert(std::fabs(ElevationAzimuth({-1, 0, 0})[1] - 270.0f) < 1e-4f);
        assert(std::fabs(AngleDeg({1, 0, 0}, {0, 1, 0}) - 90.0f) < 1e-4f);
        assert(AngleDeg({1, 0, 0}, {0, 0, 0}) == 180.0f);
    }
'''),
    ],
    "engine/tests/test_effect_pipelines.cpp": [
        (r'''#include "video_core/host_shaders/volumetric_light_repair_comp.h"
''', r'''#include "video_core/host_shaders/volumetric_light_repair_comp.h"
// bbport (r76_sun-fog-outdoors): the march's builds that read the ray traced sun gate (r51b), and
// the gate view's march and composite builds
#include "video_core/host_shaders/volumetric_light_integrate_gate_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_gate_view_comp.h"
#include "video_core/host_shaders/volumetric_light_composite_gate_view_comp.h"
'''),
        (r'''        {"volumetric tint",
         VOLUMETRIC_LIGHT_TINT_COMP,
''', r'''        // bbport (r76_sun-fog-outdoors): as VolumetricLight::GateReady and DiagReady make them: the
        // pass's own bindings, then the gate (3D) and each column's first open slice; the view's
        // march adds its image and the cells' bands, its composite the view. The gate's own two
        // builds need ray queries, which this test's device does not turn on: not built here.
        {"volumetric integrate (gate)",
         VOLUMETRIC_LIGHT_INTEGRATE_GATE_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler},
         32},
        {"volumetric repair (gate)",
         VOLUMETRIC_LIGHT_REPAIR_GATE_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
          eCombinedImageSampler},
         32},
        {"volumetric integrate (gate view)",
         VOLUMETRIC_LIGHT_INTEGRATE_GATE_VIEW_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eCombinedImageSampler},
         32},
        {"volumetric composite (gate view)",
         VOLUMETRIC_LIGHT_COMPOSITE_GATE_VIEW_COMP,
         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage, eStorageBuffer,
          eCombinedImageSampler, eCombinedImageSampler, eCombinedImageSampler},
         4},
        {"volumetric tint",
         VOLUMETRIC_LIGHT_TINT_COMP,
'''),
    ],
    "engine/docs/renderer-performance-0.9.43.md": [
        (r'''- **Startup-only items.** The motion store size and thread pinning are read once at start.
''', r'''- **Sun fog kept out of interiors (r51, r51b, r76).** Environment only, read once at start; no
  experiment bit gates them, so the switch does not change them. `BB_VOLUMETRIC_OCCLUSION`
  (`VolumetricOcclusion::Parse` in `volumetric_occlusion.h`) defaults to 5 since r76 (7 before):
  the march skips sun atlas cascades that hold no casters (bit 1) and ends at the shadow distance
  (bit 4). Bit 2, the darkest answer of every cascade holding a sample, is left out of the default:
  in the game it doubled the march's time ("Lighting: volumetric sunlight" 0.199 against 0.430 ms
  in a roofed library, 0.212 against 0.419 ms at an outdoor street lamp, values 5 and 7, one run
  each, RTX 4090, 1080p internal) and changed nothing visible where the leak was found. 0 gives
  the march of before r51. `BB_VOLUMETRIC_RT_GATE` (`VolumetricOcclusion::ParseRtGate`) defaults
  to 1 since r76 (0 before): while `RtShadow` builds a ray traced scene (`RtShadow::SceneWanted`),
  `VolumetricLight::RecordGate` traces one ray toward the sun from each cell of a 160x90x32 grid in
  front of the camera through the sun's shadow casters in that scene (mask 1), and the march
  multiplies its atlas answer by the result, so the gate only removes light. 2 (the camera pass's
  geometry) and 3 (both) are test values: in the game test of 2026-11-15 they also cleared rooms
  whose roof only the camera pass holds, but removed the sun fog over the whole frame outdoors under
  a large stone vault. The gate's pass also writes each column's first open cell, and a pixel's
  march starts at the first sample that can read an open cell (`GateShutTo` in
  `volumetric_light.comp`); by the argument there the samples left out added exactly 0, so the
  picture does not change (not yet compared on the GPU), and a pixel whose cells are all shut is
  not marched. 0 turns the gate off. Without a scene the march is that of r51
  (`VolumetricOcclusion::GateInForce`) and the log says so once. Measured before r76 (r51b, gate
  set by hand, 1080p internal): the gate's row 0.022 ms with mask 1 at an outdoor street lamp (0.075
  ms with mask 3), 0.018 to 0.033 ms with mask 1 elsewhere. The early start of the march is not
  measured yet. With `BB_GPU_PROFILE=1` the rows "Lighting: volumetric sun gate" and "Lighting:
  volumetric sunlight" are pinned (`GpuProfiler::Pin`): printed in every block they have time in,
  also below the `BB_GPU_PROFILE_ROWS` cut (30 rows by default). The light's direction is read on
  the host from the shadow constants the gate's rays use (`VolumetricOcclusion::LightDirection`)
  and logged at the first march and when it moves by more than 1 degree. Test only, off by default:
  `BB_VOLUMETRIC_GATE_PROBE=1` (`VolumetricLight::ReadGateProbe`: where the gate's rays hit, every
  600 gated marches) and `BB_VOLUMETRIC_GATE_VIEW=1` (the gate's hits tinted by distance on
  screen); off, neither changes a shader or a pass.
- **Startup-only items.** The motion store size and thread pinning are read once at start.
'''),
    ],
    "README.md": [
        (r'''| `BB_LAMP_SHADOW_VIEW_GAIN` | Debug only: brightness gain of that view, 0.01 to 16 | `0.5` |

## Sponsors
''', r'''| `BB_LAMP_SHADOW_VIEW_GAIN` | Debug only: brightness gain of that view, 0.01 to 16 | `0.5` |

### Volumetric sunlight

The sun fog (`effect_volumetric_light`) follows the game's sun shadow atlas, which often holds no roof over a room. These environment variables are read once when the game starts; text that is not one of the values below leaves the default. They are for testing and are part of no look.

| Variable | What it does | Default |
|---|---|---|
| `BB_VOLUMETRIC_RT_GATE` | Before the fog is marched, one ray toward the sun from each of 160x90x32 cells in front of the camera through the frame's ray traced scene; the fog gets no sun where the ray hits something. `0` off; `1` the sun's shadow casters (whole meshes, also those only a far shadow cascade holds); `2` what the camera drew this frame; `3` both. `2` and `3` also clear rooms whose roof only the camera's geometry holds, but in a test they removed the fog outdoors under a large stone vault, so they are test values. It runs only while the ray traced scene is built (`effect_ray_tracing` on with the ray traced sun, ray traced lamps or bounced light); without it the fog follows the atlas alone and can show indoors | `1` |
| `BB_VOLUMETRIC_OCCLUSION` | Bit field: `1` a cascade of the atlas without casters counts as outside it; `2` the darkest answer of every cascade holding a sample (about 0.2 ms more at 1080p internal); `4` no fog for a fade rate that is not positive, and the march ends at the shadow distance; `0` as before r51 | `5` |
| `BB_VOLUMETRIC_GATE_PROBE` | Debug only: `1` logs, every 600 marches the gate runs on, where its rays hit: the cells in front of the visible surface it shuts, by the distance of the nearest hit (under 5, 15, 40, 150 and 800 m), how many of those hits are on geometry only the camera drew, the hits of the centre column with its surface distance, and the light's direction. Those marches trace to the nearest hit | off |
| `BB_VOLUMETRIC_GATE_VIEW` | Debug only: `1` tints the screen where the gate shuts the sun out along the view, by the distance of the nearest hit: red under 5 m, yellow 5 to 15 m, green 15 to 40 m, cyan 40 to 150 m, magenta beyond; where the gate is open the picture is untouched. While on, every gated march traces to the nearest hit | off |

## Sponsors
'''),
    ],
}

# Text checks on the patched result (each string must occur exactly this often).
CHECKS = {
    H + "volumetric_rt_gate.comp": [("local_size_z = 32", 1), ("uniform writeonly image2D gate_first", 1),
                                    ("barrier();", 2), ("return;", 1), ("#ifdef DIAG", 8),
                                    ("gl_RayFlagsTerminateOnFirstHitEXT", 1),
                                    ("uint(hit_t >= 5.0) + uint(hit_t >= 15.0) + uint(hit_t >= 40.0) +", 1),
                                    ("uint(hit_t >= 150.0)", 1),
                                    ("const uint DiagProbe = 0x100u, DiagBand = 0x200u;", 1),
                                    ("layout(binding = 7) uniform sampler2D depth_tex;", 1),
                                    ("float centre_surface;", 1),
                                    ("if (asked && front) atomicAdd(shared_probe[10], 1u);", 1),
                                    ("if (band != 0u && front) {", 1)],
    H + "volumetric_light.comp": [("layout(binding = 7) uniform sampler2D sun_gate_first;", 1),
                                  ("layout(binding = 8) uniform sampler2D sun_gate_first;", 1),
                                  ("layout(binding = 8, rgba8) uniform writeonly image2D gate_view_out;", 1),
                                  ("layout(binding = 9) uniform sampler3D sun_gate_band;", 1),
                                  ("layout(binding = 6) uniform sampler2D gate_view_tex;", 1),
                                  ("GateShutTo(uv, gate_range)", 1), ("textureGatherOffset", 4),
                                  ("GateView(px, uv, gate_range, limit);", 1),
                                  ("for (uint i = first_step; i < steps; ++i)", 1),
                                  ("for (uint i = 0u; i < steps; ++i)", 1), ("#ifdef GATE\n", 4),
                                  ("#ifdef GATE_VIEW", 6)],
    R + "volumetric_occlusion.h": [("return Default;", 1), (": Default;", 1),
                                   ("GateProbeWords = GateProbeSurfaceAt + 1;", 1),
                                   ("inline constexpr std::uint32_t RtGateDefault = 1;", 1),
                                   ("RtGateNamed(text) ? std::uint32_t(text[0] - '0') : RtGateDefault", 1),
                                   ("inline constexpr std::array<float, 4> GateBandEdges{5.0f, 15.0f, 40.0f, 150.0f};", 1),
                                   ("GateDiagProbe = 0x100, GateDiagBand = 0x200;", 1)],
    R + "vk_volumetric_light.cpp": [("static_assert(GateSlices == 32", 1),
                                    ("cmd.dispatch(GateWidth / 2, GateHeight / 2, GateSlices / 32);", 1),
                                    ("EffectPass::Mark(51, \"volumetric sun gate\", true);", 1),
                                    ("EffectPass::Mark(7, \"volumetric sunlight\", true);", 1),
                                    ("RecordGate(in, in.constants_offset_word, probing, viewing, di);", 1),
                                    ("sun_scene = vk::AccelerationStructureKHR{};", 1),
                                    ("eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler},", 1),
                                    (".pImageInfo = &gfi};", 1), (".pImageInfo = &gvo};", 1),
                                    (".pImageInfo = &gbi};", 1),
                                    ("if (gate_traced != 0 || gate_tried) {", 1),
                                    ("std::span{writes.data(), diag ? 8u : 5u}", 1),
                                    ("eStorageImage, eStorageImage, eStorageBuffer, eCombinedImageSampler},", 1),
                                    ("{.dstBinding = 7, .descriptorCount = 1,\n                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &depth},", 1),
                                    ("std::span{writes.data(), gate_viewed ? 7u : 6u}", 1),
                                    ("VOLUMETRIC_RT_GATE_DIAG_COMP", 1),
                                    ("VOLUMETRIC_LIGHT_INTEGRATE_GATE_VIEW_COMP", 1),
                                    ("VOLUMETRIC_LIGHT_COMPOSITE_GATE_VIEW_COMP", 1),
                                    ("Volumetric lighting (r76): gate probe: %s; shut cells in front of the surface ", 1),
                                    ("Volumetric lighting (r76): light direction world (%.3f, %.3f, %.3f) elevation ", 1)],
    R + "vk_rasterizer_effects.cpp": [("VolumetricOcclusion::GateInForce(rt_gate, rt_scene)", 1),
                                      ("volumetric_light->SetSunScene(", 1),
                                      ("volumetric_light->SetSunSceneTable(", 1),
                                      ("volumetric_light->SetSunLight(light);", 1)],
    R + "vk_rt_shadow.cpp": [("gate_table.push_back({entry->base, entry->triangles, static_cast<u8>(record.mask)});", 1),
                             ("gate_table.clear();", 1)],
    R + "vk_gpu_profiler.cpp": [("std::ranges::find(pinned, key)", 1)],
    "engine/gpu/CMakeLists.txt": [("volumetric_rt_gate_diag_comp DIAG=1", 1),
                                  ("volumetric_light_integrate_gate_view_comp INTEGRATE=1 GATE=1 GATE_VIEW=1", 1),
                                  ("volumetric_light_composite_gate_view_comp COMPOSITE=1 GATE_VIEW=1", 1)],
    "engine/tests/test_volumetric_occlusion.cpp": [("assert(RtGateDefault == 1);", 1),
                                                   ("RtGateDefault == 3", 0)],
    "engine/tests/test_effect_pipelines.cpp": [("VOLUMETRIC_LIGHT_INTEGRATE_GATE_COMP,", 1),
                                               ("VOLUMETRIC_LIGHT_REPAIR_GATE_COMP,", 1),
                                               ("VOLUMETRIC_LIGHT_INTEGRATE_GATE_VIEW_COMP,", 1),
                                               ("VOLUMETRIC_LIGHT_COMPOSITE_GATE_VIEW_COMP,", 1)],
    "README.md": [("| `BB_VOLUMETRIC_RT_GATE` |", 1), ("| `BB_VOLUMETRIC_GATE_PROBE` |", 1),
                  ("| `BB_VOLUMETRIC_GATE_VIEW` |", 1)],
}

# Order checks on the patched result: each string after the one before it (first occurrence).
ORDER = {
    R + "vk_volumetric_light.cpp": ["const bool gated =", "const bool diag = gated",
                                    "cmd.clearColorImage(image,",
                                    "        RecordGate(in, in.constants_offset_word, probing, viewing, di);",
                                    "    sun_scene = vk::AccelerationStructureKHR{};",
                                    "for (u32 pass_index = 0; pass_index < 2; ++pass_index)"],
    H + "volumetric_rt_gate.comp": ["shared_first[gl_LocalInvocationIndex] = gl_WorkGroupSize.z;",
                                    "barrier();", "atomicAdd(shared_probe[band - 1u], 1u);",
                                    "atomicMin(shared_first[column]",
                                    "barrier();\n    if (inside && gl_LocalInvocationID.z == 0u)",
                                    "atomicAdd(probe.shut[i], shared_probe[i]);"],
    H + "volumetric_light.comp": ["float GateShutTo(", "void GateView(", "GateView(px, uv, gate_range, limit);",
                                  "float shut_to = GateShutTo(uv, gate_range);",
                                  "for (uint i = first_step; i < steps; ++i)"],
}

def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")

def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d"
                                 % (path, s, texts[path].count(s), n))
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                raise SystemExit("order check: %s: %r not after the one before" % (path, s))
            at = i

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R76_ROOT)" % ROOT)
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
            print("not applied; would apply (%d files edited; text checks on the result pass)" % len(plan))
        return
    if cmd == "apply":
        if state == "applied": print("already applied"); return
        texts, outs = {}, []
        for path, edits, raw, eol, cur, _ in plan:
            for old, new in edits: cur = cur.replace(old, new)
            texts[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r76tmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(ROOT, path))
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r76tmp"
                if os.path.exists(tmp): os.remove(tmp)
            for path, raw in written:
                open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    for path, edits, raw, eol, cur, _ in plan:
        for old, new in reversed(edits): cur = cur.replace(new, old)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    print("reverted")

main()
