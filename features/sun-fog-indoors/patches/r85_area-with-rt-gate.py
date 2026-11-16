# r85_area-with-rt-gate: FEATURE patch. r81's area light gate (BB_VOLUMETRIC_AREA_GATE=1, off by
# default) also on marches that use the ray traced sun gate, so that both rules apply together. On
# top of r51b, r76, r81 and r82 (and r83, r80, r76c, r84, which it does not touch).
#
# Why: the owner's rule (2026-11-15, verbatim): "The sun fog shouldn't go indoors at all". In the
# slot tests the ray traced gate (r51b/r76, BB_VOLUMETRIC_RT_GATE, default 1) cleared the library
# (dark-interior) only with the BB PC Remaster mod on, and the church hall (church-candles) not at
# all; r81's area gate, without ray tracing, cleared the church hall (fog kept 16-19 %). r81 runs
# only on marches WITHOUT the ray traced gate (its AREA builds refused GATE and Integrate kept
# `!gated`), so a ray tracing player never had it. Ray rules tried after that (r76c shells, r76d
# faces, r76e roof) cannot tell the graveyard from an interior; the game's light sets can.
#
# What (BB_VOLUMETRIC_AREA_GATE=1; knob off: nothing changes):
# 1. volumetric_light.comp: AREA+GATE builds of INTEGRATE and REPAIR. Their sample is the GATE
#    builds' (the atlas's answer, then the ray traced gate's, from the gate's first open step
#    first_step), kept apart as r81's AREA builds keep the plain one: r the energy nearer the
#    camera, g the energy of the march's last AREA_FAR_METRES, both of what the gate lets through;
#    b stays r81's measure, the atlas's own share in sun, over the samples marched (those before
#    first_step, which the gate shut from the camera, left out). So the area gate decides as it
#    does without the ray traced gate, on the fog that gate left. AREA with GATE_VIEW is refused
#    (#error), as AREA with WIND already is (r82).
# 2. vk_volumetric_light.cpp: `area` no longer needs `!gated`; on a gated march it also needs the
#    AREA+GATE pipelines, made lazily at the first gated march while the knob is on
#    (AreaGatedReady; the GATE builds' descriptor layout and the plain 32-byte push constants).
#    A march the gate view draws (BB_VOLUMETRIC_GATE_VIEW=1) stays without the area gate (no AREA
#    build of GATE_VIEW; that view shows the ray traced gate alone): `area` leaves out gated marches
#    while the view knob is on, and the pipeline choice and the AreaGate debt take `area &&
#    !viewing`, so a change of the live knobs file between the two reads cannot bind an AREA build
#    to the view's bindings. Pipeline choice by (area, gated, repairing) through AreaPass. r82's
#    drift test `!area` is untouched and now also keeps gated area marches from drifting.
#    AreaGate (CAMERA and APPLY) and the r81 probe are unchanged; they read only the fog images.
# 3. Log: knob off, r81's off line at the first march (unchanged text); knob on, r81's on line at
#    the first area march without the ray traced gate (unchanged text), "Volumetric lighting
#    (r85): area light gate on (BB_VOLUMETRIC_AREA_GATE=1) with the ray traced sun gate: ..." at
#    the first one with it, "Volumetric lighting (r85): area light gate's builds for marches with
#    the ray traced sun gate made" once, and "Volumetric lighting (r85): area light gate off on
#    marches the gate view draws ..." when the view keeps it off (again after the view was off).
#    The r81 probe's "on N of M marches" now counts gated area marches too.
# 4. CMake: two add_host_shader lines (INTEGRATE=1 GATE=1 AREA=1, REPAIR=1 GATE=1 AREA=1; the r81
#    INCLUDES rule already covers volumetric_light.comp); effect-pipelines-test builds both with
#    the GATE builds' bindings. README row of BB_VOLUMETRIC_AREA_GATE. Comments of r81 that said
#    "without the ray traced gate" (vk_volumetric_light.h, AreaReady, volumetric_area_gate.h,
#    volumetric_area_gate.comp) say the new case.
#
# Expected (not seen): with ray tracing on, the library with the mod on as r76 alone (the gate
# clears it), the church hall as r81 without ray tracing (16-19 %), the graveyard as r81 (81 % /
# 100 % without ray tracing); weak spot the library with the mod off (r81 kept 36-73 % there).
#
# Cost (estimates, NOT measured): knob off: nothing (every build that exists today gives
# byte-identical SPIR-V, no new pipeline, a few bool tests a march). Knob on, gated march: the
# AREA+GATE march does the GATE march's taps plus an add and a compare a sample; AreaGate's two
# passes as r81 (about 0.01-0.03 ms); two more pipelines (r81's two ungated AREA builds are also
# made, by AreaReady, even if no ungated march comes).
#
# Layering: r85 rewrites r81's `area` line, once-lines, pipeline capture and AreaGate debt, and
# r81's comments: revert r85 before r81 or r82. Proven on a copy of the tree of 19:10: with r85
# applied, r76c's, r80's and r84's `check` still pass; r82's fails only on its text check of
# r81's pipeline capture line (which r85 replaces; every r82 edit is still found); r51b's, r76's,
# r81's and r83's checks already fail on the tree without r85 (later patches rewrote their text).
# r82's README row still says "(`BB_VOLUMETRIC_AREA_GATE=1` without the ray traced gate)": left
# so; the BB_VOLUMETRIC_AREA_GATE row says the full rule.
#
# Files: host_shaders/volumetric_light.comp, host_shaders/volumetric_area_gate.comp (comment),
# renderer_vulkan/vk_volumetric_light.h, renderer_vulkan/vk_volumetric_light.cpp,
# renderer_vulkan/volumetric_area_gate.h (comment), engine/gpu/CMakeLists.txt,
# engine/tests/test_effect_pipelines.cpp, README.md. No new files.
#
# Use: cd <tree> && python -I -X utf8 r85_area-with-rt-gate.py check | apply | revert (root from
# R85_ROOT, else the current directory). check is read-only. Files keep their line ends (CRLF in
# the tree). Originals are kept in r85_backup/ next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r85_backup")
ROOT = os.environ.get("R85_ROOT") or os.getcwd()
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"

# Edits of existing files, in order: (path, anchor text, its replacement). Each anchor must occur
# exactly once before, each replacement exactly once after.
EDITS = [
    (H + "volumetric_light.comp",
r'''#if defined(GATE) || !(defined(INTEGRATE) || defined(REPAIR))
#error AREA is a build of INTEGRATE or REPAIR without GATE
#endif
''',
r'''#if !(defined(INTEGRATE) || defined(REPAIR))
#error AREA is a build of INTEGRATE or REPAIR
#endif
// bbport (r85_area-with-rt-gate): and with GATE (BB_VOLUMETRIC_AREA_GATE=1 on a march with the ray
// traced sun gate: the gated sample, kept apart the same way), never with GATE_VIEW (a march the
// gate view draws stays without the area gate: VolumetricLight::Integrate)
#ifdef GATE_VIEW
#error AREA is not built with GATE_VIEW
#endif
'''),
    (H + "volumetric_light.comp",
r'''        float t = (float(i) + jitter) * ds;
#ifdef GATE
        // bbport (r51b_volumetric-rt-check): the atlas's answer, then the ray traced gate's
''',
r'''        float t = (float(i) + jitter) * ds;
#if defined(GATE) && defined(AREA)
        // bbport (r85_area-with-rt-gate): the GATE builds' sample (the atlas's answer, then the ray
        // traced gate's), kept apart as r81's AREA builds keep the plain one: near and far energy of
        // what the gate lets through, and in `area_lit` the atlas's own answer, so that the share in
        // sun (b, the beam test) stays r81's measure, over the samples marched: those before
        // first_step (shut by the gate from the camera) are left out, and each counts
        // steps / (steps - first_step) so that the store's area_lit / steps is the mean of those
        // marched (the loop runs only while first_step < steps)
        float v = visibility(ray * t, texel);
        area_lit += v * (float(steps) / float(steps - first_step));
        if (v > 0.0) v *= GateAt(uv, t, gate_range);
        float e = exp(-density * t) * density * ds * v;
        if (t < area_far_from) {
            area_near += e;
        } else {
            area_far += e;
        }
#elif defined(GATE)
        // bbport (r51b_volumetric-rt-check): the atlas's answer, then the ray traced gate's
'''),
    (H + "volumetric_area_gate.comp",
r'''// bbport (r81_sun-fog-no-rt): the sun fog's area light gate, for marches without the ray traced
// gate (BB_VOLUMETRIC_AREA_GATE=1; VolumetricLight::AreaGate, right after the fog's tint at the
''',
r'''// bbport (r81_sun-fog-no-rt): the sun fog's area light gate, for marches without the ray traced
// gate (bbport (r85_area-with-rt-gate): and with it, whose AREA+GATE builds keep in r and g only
// the samples it lets through; these two passes are the same for both)
// (BB_VOLUMETRIC_AREA_GATE=1; VolumetricLight::AreaGate, right after the fog's tint at the
'''),
    (R + "volumetric_area_gate.h",
r'''// without ray queries, BB_VOLUMETRIC_RT_GATE=0, or a frame without a scene) keeps near and far
// energy and the lit share apart (the AREA builds of volumetric_light.comp), and right after the
''',
r'''// without ray queries, BB_VOLUMETRIC_RT_GATE=0, or a frame without a scene) keeps near and far
// energy and the lit share apart (the AREA builds of volumetric_light.comp; bbport
// (r85_area-with-rt-gate): every march WITH it too, through the AREA+GATE builds, keeping only the
// samples that gate lets through, except a march the gate view draws), and right after the
'''),
    (R + "vk_volumetric_light.h",
r'''    /// bbport (r81_sun-fog-no-rt): BB_VOLUMETRIC_AREA_GATE=1: after a march without the ray traced
    /// sun gate, weighs its fog with the game's light sets (volumetric_area_gate.comp). `lighting`
''',
r'''    /// bbport (r81_sun-fog-no-rt): BB_VOLUMETRIC_AREA_GATE=1: after a march (bbport
    /// (r85_area-with-rt-gate): with the ray traced sun gate or without it, not one the gate view
    /// draws), weighs its fog with the game's light sets (volumetric_area_gate.comp). `lighting`
'''),
    (R + "vk_volumetric_light.h",
r'''    // bbport (r81_sun-fog-no-rt): the area light gate (BB_VOLUMETRIC_AREA_GATE=1), made at the first
    // march without the ray traced gate while the knob is on: the march's AREA builds, its two
    // passes, its state (volumetric_area_layout.h, 35 KB) and the probe's copy of it for the host
    bool AreaReady();
    void ReadAreaProbe();
    Pass integrate_area, repair_area, area_camera, area_apply;
''',
r'''    // bbport (r81_sun-fog-no-rt): the area light gate (BB_VOLUMETRIC_AREA_GATE=1), made at the first
    // march while the knob is on (bbport (r85_area-with-rt-gate): with the ray traced gate or
    // without it): the march's AREA builds, its two passes, its state (volumetric_area_layout.h,
    // 35 KB) and the probe's copy of it for the host
    bool AreaReady();
    void ReadAreaProbe();
    Pass integrate_area, repair_area, area_camera, area_apply;
    // bbport (r85_area-with-rt-gate): the march's AREA+GATE builds (the GATE builds' bindings), made
    // at the first march with the ray traced gate while the knob is on (AreaGatedReady; failing
    // leaves such marches without the area gate); AreaPass: the build an area gate march binds, by
    // (gated, repairing); AreaViewKnob: BB_VOLUMETRIC_GATE_VIEW as Integrate's area decision reads
    // it (once a march, only while the knob is on); the flags of the once-lines that say which
    // case acts (Integrate)
    bool AreaGatedReady();
    const Pass& AreaPass(bool gated, bool repairing) const {
        return gated ? (repairing ? repair_gated_area : integrate_gated_area)
                     : (repairing ? repair_area : integrate_area);
    }
    static bool AreaViewKnob() { return VolumetricOcclusion::GateView(); }
    Pass integrate_gated_area, repair_gated_area;
    bool area_rt_tried = false, area_rt_failed = false;
    bool area_said_plain = false, area_said_traced = false, area_said_view = false;
'''),
    (R + "vk_volumetric_light.cpp",
r'''#include "video_core/host_shaders/volumetric_area_gate_camera_comp.h"
''',
r'''#include "video_core/host_shaders/volumetric_area_gate_camera_comp.h"
// bbport (r85_area-with-rt-gate): the march's AREA+GATE builds
#include "video_core/host_shaders/volumetric_light_integrate_gate_area_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_area_comp.h"
'''),
    (R + "vk_volumetric_light.cpp",
r'''// bbport (r81_sun-fog-no-rt): made at the first march without the ray traced gate while
// BB_VOLUMETRIC_AREA_GATE=1: the march's AREA builds (the bindings and push constants of the plain
// ones), the gate's CAMERA and APPLY passes, its state and the probe's copy of it. Failing leaves
// the march as without the gate.
bool VolumetricLight::AreaReady() {
''',
r'''// bbport (r81_sun-fog-no-rt): made at the first march while BB_VOLUMETRIC_AREA_GATE=1 (bbport
// (r85_area-with-rt-gate): with the ray traced gate or without it; with it AreaGatedReady then
// makes the AREA+GATE builds): the march's AREA builds (the bindings and push constants of the
// plain ones), the gate's CAMERA and APPLY passes, its state and the probe's copy of it. Failing
// leaves the march as without the gate.
bool VolumetricLight::AreaReady() {
'''),
    (R + "vk_volumetric_light.cpp",
r'''                GridX, GridY, Records, FarMetres);
    return true;
}
''',
r'''                GridX, GridY, Records, FarMetres);
    return true;
}

// bbport (r85_area-with-rt-gate): made at the first march with the ray traced gate while
// BB_VOLUMETRIC_AREA_GATE=1, after AreaReady (the gate's passes and state): the march's AREA+GATE
// builds, with the GATE builds' bindings (the pass's own, then the gate and each column's first
// open slice) and push constants (Params, 32 bytes). Failing leaves marches with the ray traced
// gate as without the area gate; those without it keep it.
bool VolumetricLight::AreaGatedReady() {
    if (area_rt_tried) {
        return !area_rt_failed;
    }
    area_rt_tried = true;
    using enum vk::DescriptorType;
    const bool made =
        CreatePass(integrate_gated_area,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_INTEGRATE_GATE_AREA_COMP, sizeof(Params),
                   "Volumetric integrate (gate, area gate)") &&
        CreatePass(repair_gated_area,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
                    eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_COMP, sizeof(Params),
                   "Volumetric repair (gate, area gate)");
    area_rt_failed = !made;
    std::printf(made ? "Volumetric lighting (r85): area light gate's builds for marches with the "
                       "ray traced sun gate made\n"
                     : "Volumetric lighting (r85): area light gate's builds for marches with the "
                       "ray traced sun gate could not be made; those marches stay without it\n");
    return made;
}
'''),
    (R + "vk_volumetric_light.cpp",
r'''    // bbport (r81_sun-fog-no-rt): BB_VOLUMETRIC_AREA_GATE=1 (read once, said once at the first
    // march): a march without the ray traced gate keeps the AREA layout, which AreaGate weighs at
    // the directional light draw. Off: nothing of it is made or run.
    const bool area = live_strength > 0.0f && !gated && VolumetricAreaGate::On() && AreaReady();
    if (live_strength > 0.0f) {
        if (!area_said) {
            area_said = true;
            if (VolumetricAreaGate::On()) {
                std::printf("Volumetric lighting (r81): area light gate on "
                            "(BB_VOLUMETRIC_AREA_GATE=1): a march without the ray traced sun gate "
                            "keeps its sun fog only where the game's light set has sun (the "
                            "surface's for the last %.0f m of each ray, those on screen for the "
                            "rest) or where the air along the view is mostly in the atlas's "
                            "shadow (a beam)\n",
                            VolumetricAreaGate::FarMetres);
            } else {
                std::printf("Volumetric lighting (r81): area light gate off "
                            "(BB_VOLUMETRIC_AREA_GATE not 1): without the ray traced sun gate "
                            "the sun fog follows the atlas alone and can show indoors\n");
            }
        }
        ++area_marches;
        area_gated += area ? 1 : 0;
    }
''',
r'''    // bbport (r81_sun-fog-no-rt): BB_VOLUMETRIC_AREA_GATE=1 (read once, said once at the first
    // march): a march without the ray traced gate keeps the AREA layout, which AreaGate weighs at
    // the directional light draw. Off: nothing of it is made or run.
    // bbport (r85_area-with-rt-gate): and a march with the ray traced gate too, through its
    // AREA+GATE builds (AreaGatedReady, made at the first such march): a sample counts only where
    // the atlas and the gate let the sun through, and AreaGate then weighs what is left. Not a
    // march the gate view draws (BB_VOLUMETRIC_GATE_VIEW=1): the GATE_VIEW build has no AREA
    // variant, and that view shows the gate alone. `viewing` below is that test once the view's
    // passes and image exist; the march binds an AREA build and owes AreaGate only with
    // `area && !viewing`, which stays consistent if the live knobs file turns the view on between
    // the two reads.
    const bool area_view = VolumetricAreaGate::On() && AreaViewKnob();
    const bool area = live_strength > 0.0f && VolumetricAreaGate::On() && !(gated && area_view) &&
                      AreaReady() && (!gated || AreaGatedReady());
    if (live_strength > 0.0f) {
        // bbport (r85_area-with-rt-gate): the once-lines say which case acts: off (r81's line, at
        // the first march); on, r81's line at the first area gate march without the ray traced
        // gate, r85's at the first one with it, and r85's line when the gate view keeps it off
        // (again after the view was off)
        if (!area_said && !VolumetricAreaGate::On()) {
            area_said = true;
            std::printf("Volumetric lighting (r81): area light gate off "
                        "(BB_VOLUMETRIC_AREA_GATE not 1): without the ray traced sun gate "
                        "the sun fog follows the atlas alone and can show indoors\n");
        }
        if (area && !gated && !area_said_plain) {
            area_said_plain = true;
            std::printf("Volumetric lighting (r81): area light gate on "
                        "(BB_VOLUMETRIC_AREA_GATE=1): a march without the ray traced sun gate "
                        "keeps its sun fog only where the game's light set has sun (the "
                        "surface's for the last %.0f m of each ray, those on screen for the "
                        "rest) or where the air along the view is mostly in the atlas's "
                        "shadow (a beam)\n",
                        VolumetricAreaGate::FarMetres);
        }
        if (area && gated && !area_said_traced) {
            area_said_traced = true;
            std::printf("Volumetric lighting (r85): area light gate on "
                        "(BB_VOLUMETRIC_AREA_GATE=1) with the ray traced sun gate: a sample counts "
                        "only where the atlas and that gate let the sun through, then the game's "
                        "light sets weigh what is left as without that gate (the surface's for the "
                        "last %.0f m of each ray, those on screen for the rest)\n",
                        VolumetricAreaGate::FarMetres);
        }
        if (VolumetricAreaGate::On()) {
            const bool view_off = gated && area_view;
            if (view_off && !area_said_view) {
                std::printf("Volumetric lighting (r85): area light gate off on marches the gate "
                            "view draws (BB_VOLUMETRIC_GATE_VIEW=1): that view shows the ray traced "
                            "sun gate alone\n");
            }
            area_said_view = view_off || (area_said_view && area_view);
        }
        ++area_marches;
        area_gated += area ? 1 : 0;
    }
'''),
    (R + "vk_volumetric_light.cpp",
r'''         // bbport (r81_sun-fog-no-rt): the AREA builds on an area gate march (same bindings)
         pipeline = *(area ? (repairing ? repair_area : integrate_area) : pass).pipeline,
         layout = *(area ? (repairing ? repair_area : integrate_area) : pass).layout](
''',
r'''         // bbport (r81_sun-fog-no-rt): the AREA builds on an area gate march (same bindings);
         // bbport (r85_area-with-rt-gate): by (gated, repairing), with the ray traced gate the
         // AREA+GATE builds (the GATE builds' bindings, which `gated` writes below); never on a
         // march the gate view draws (`viewing` in these initializers is Integrate's)
         pipeline = *(area && !viewing ? AreaPass(gated, repairing) : pass).pipeline,
         layout = *(area && !viewing ? AreaPass(gated, repairing) : pass).layout](
'''),
    (R + "vk_volumetric_light.cpp",
r'''    area_pending = area; // bbport (r81_sun-fog-no-rt): AreaGate is owed at the directional draw
''',
r'''    // bbport (r81_sun-fog-no-rt): AreaGate is owed at the directional draw; bbport
    // (r85_area-with-rt-gate): not after a march the gate view drew (it bound no AREA build)
    area_pending = area && !viewing;
'''),
    ("engine/gpu/CMakeLists.txt",
r'''add_host_shader(volumetric_light.comp volumetric_light_repair_area_comp REPAIR=1 AREA=1)
''',
r'''add_host_shader(volumetric_light.comp volumetric_light_repair_area_comp REPAIR=1 AREA=1)
# bbport (r85_area-with-rt-gate): BB_VOLUMETRIC_AREA_GATE=1 on marches with the ray traced gate:
# the AREA builds reading the gate (made at the first such march); the builds above are unchanged
add_host_shader(volumetric_light.comp volumetric_light_integrate_gate_area_comp INTEGRATE=1 GATE=1 AREA=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_gate_area_comp REPAIR=1 GATE=1 AREA=1)
'''),
    ("engine/tests/test_effect_pipelines.cpp",
r'''#include "video_core/host_shaders/volumetric_light_repair_area_comp.h"
''',
r'''#include "video_core/host_shaders/volumetric_light_repair_area_comp.h"
// bbport (r85_area-with-rt-gate): the march's AREA+GATE builds
#include "video_core/host_shaders/volumetric_light_integrate_gate_area_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_area_comp.h"
'''),
    ("engine/tests/test_effect_pipelines.cpp",
r'''        {"volumetric area gate (apply)",
         VOLUMETRIC_AREA_GATE_APPLY_COMP,
         {eStorageBuffer, eCombinedImageSampler, eStorageImage},
         16},
''',
r'''        {"volumetric area gate (apply)",
         VOLUMETRIC_AREA_GATE_APPLY_COMP,
         {eStorageBuffer, eCombinedImageSampler, eStorageImage},
         16},
        // bbport (r85_area-with-rt-gate): as VolumetricLight::AreaGatedReady makes them: the
        // AREA+GATE builds take the GATE builds' bindings
        {"volumetric integrate (gate, area gate)",
         VOLUMETRIC_LIGHT_INTEGRATE_GATE_AREA_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler},
         32},
        {"volumetric repair (gate, area gate)",
         VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
          eCombinedImageSampler},
         32},
'''),
    ("README.md",
r'''| `BB_VOLUMETRIC_AREA_GATE` | Sun fog indoors without ray tracing: `1` keeps the sun fog of every march without the ray traced sun gate (`effect_ray_tracing` off, no ray traced scene this frame, or `BB_VOLUMETRIC_RT_GATE=0`) only where''',
r'''| `BB_VOLUMETRIC_AREA_GATE` | Sun fog indoors, with or without ray tracing: `1` keeps the sun fog of every march (without the ray traced sun gate: `effect_ray_tracing` off, no ray traced scene this frame, or `BB_VOLUMETRIC_RT_GATE=0`; and with it, see the end) only where'''),
    ("README.md",
r'''the four light sets seen most | off |''',
r'''the four light sets seen most. With the ray traced sun gate both apply: a sample counts only where that gate lets the sun through, then this gate weighs what is left (the share in sun is then taken over the part of the ray that gate does not shut from the camera); not on a march the gate view (`BB_VOLUMETRIC_GATE_VIEW=1`) draws, which shows that gate alone. A march of this gate never drifts with the wind (`BB_WIND`) | off |'''),
]

# Text checks on the patched result (each string must occur exactly this often).
CHECKS = {
    H + "volumetric_light.comp": [
        ('#error AREA is a build of INTEGRATE or REPAIR\n', 1),
        ('#error AREA is not built with GATE_VIEW', 1),
        ('#if defined(GATE) || !(defined(INTEGRATE) || defined(REPAIR))', 0),
        ('#if defined(GATE) && defined(AREA)\n', 1),
        ('#elif defined(GATE)\n', 1),
        ('#elif defined(AREA)\n', 1),
        ('#error WIND is not built with AREA', 1),
        ('area_lit += v * (float(steps) / float(steps - first_step));', 1),
        ('area_lit += v;', 1),
        ('if (v > 0.0) v *= GateAt(uv, t, gate_range);', 2),
        ('area_lit / float(steps), 1.0 - depth));', 1),
        ('    for (uint i = first_step; i < steps; ++i) {', 1)],
    H + "volumetric_area_gate.comp": [('(r85_area-with-rt-gate)', 1)],
    R + "volumetric_area_gate.h": [('(r85_area-with-rt-gate)', 1)],
    R + "vk_volumetric_light.h": [
        ('bool AreaGatedReady();', 1),
        ('const Pass& AreaPass(bool gated, bool repairing) const {', 1),
        ('Pass integrate_gated_area, repair_gated_area;', 1),
        ('bool area_rt_tried = false, area_rt_failed = false;', 1),
        ('bool area_said_plain = false, area_said_traced = false, area_said_view = false;', 1),
        ('bool area_tried = false, area_failed = false, area_said = false;', 1)],
    R + "vk_volumetric_light.cpp": [
        ('#include "video_core/host_shaders/volumetric_light_integrate_gate_area_comp.h"', 1),
        ('#include "video_core/host_shaders/volumetric_light_repair_gate_area_comp.h"', 1),
        ('bool VolumetricLight::AreaGatedReady() {', 1),
        ('VOLUMETRIC_LIGHT_INTEGRATE_GATE_AREA_COMP, sizeof(Params),', 1),
        ('VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_COMP, sizeof(Params),', 1),
        ('const bool area = live_strength > 0.0f && !gated', 0),
        ('const bool area_view = VolumetricAreaGate::On() && AreaViewKnob();', 1),
        ('!(gated && area_view) &&', 1),
        ('AreaReady() && (!gated || AreaGatedReady());', 1),
        ('VolumetricOcclusion::GateView()', 1),
        ('pipeline = *(area && !viewing ? AreaPass(gated, repairing) : pass).pipeline,', 1),
        ('layout = *(area && !viewing ? AreaPass(gated, repairing) : pass).layout](', 1),
        ('repair_area : integrate_area) : pass)', 0),
        ('area_pending = area && !viewing;', 1),
        ('area_pending = area;', 0),
        ('const bool drift = wind_wanted && !viewing && !area && WindPasses(gated);', 1),
        ('Volumetric lighting (r81): area light gate on "', 1),
        ('Volumetric lighting (r81): area light gate off "', 1),
        ('Volumetric lighting (r85): area light gate on "', 1),
        ('Volumetric lighting (r85): area light gate off on marches the gate "', 1),
        ('Volumetric lighting (r81): area gate probe: on %llu of %llu marches', 1)],
    "engine/gpu/CMakeLists.txt": [
        ('volumetric_light_integrate_gate_area_comp INTEGRATE=1 GATE=1 AREA=1)', 1),
        ('volumetric_light_repair_gate_area_comp REPAIR=1 GATE=1 AREA=1)', 1),
        ('volumetric_light_integrate_area_comp INTEGRATE=1 AREA=1)', 1),
        ('volumetric_light_repair_area_comp REPAIR=1 AREA=1)', 1),
        ('if (FILENAME MATCHES "^volumetric_(light|area_gate)")', 1)],
    "engine/tests/test_effect_pipelines.cpp": [
        ('VOLUMETRIC_LIGHT_INTEGRATE_GATE_AREA_COMP,', 1),
        ('VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_COMP,', 1),
        ('#include "video_core/host_shaders/volumetric_light_integrate_gate_area_comp.h"', 1),
        ('#include "video_core/host_shaders/volumetric_light_repair_gate_area_comp.h"', 1)],
    "README.md": [('| `BB_VOLUMETRIC_AREA_GATE` |', 1), ('With the ray traced sun gate both apply', 1)],
}

# Order checks on the patched result: each string after the one before it.
ORDER = {
    H + "volumetric_light.comp": ['#error AREA is a build of INTEGRATE or REPAIR', '#error AREA is not built with GATE_VIEW',
                                  '#error WIND is not built with AREA', 'float area_near = 0.0',
                                  'uint first_step = 0u;', 'float t = (float(i) + jitter) * ds;',
                                  '#if defined(GATE) && defined(AREA)', '#elif defined(GATE)',
                                  '#elif defined(WIND)', '#elif defined(AREA)', 'area_lit / float(steps)'],
    R + "vk_volumetric_light.cpp": ['bool VolumetricLight::AreaReady() {', 'bool VolumetricLight::AreaGatedReady() {',
                                    'void VolumetricLight::AreaGate(', 'const bool gated = live_strength',
                                    'const bool area = live_strength', 'const bool viewing =',
                                    'const bool drift =', 'pipeline = *(area && !viewing ?',
                                    'area_pending = area && !viewing;', '    ready = true;'],
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
        raise SystemExit("%s is not a source tree root (set R85_ROOT)" % ROOT)
    plan = {}
    for path, old, new in EDITS:
        if path not in plan:
            raw, eol, cur = load(path)
            plan[path] = [raw, eol, cur, []]
        plan[path][3].append((old, new))
    states = set()
    for path, (raw, eol, cur, edits) in plan.items():
        done = sum(cur.count(new) == 1 for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): states.add("applied")
        elif todo == len(edits): states.add("clean")
        else: raise SystemExit("%s: %d of %d edits applied, %d anchors found once" % (path, done, len(edits), todo))
    if len(states) != 1:
        raise SystemExit("mixed state: some files applied, some not (%s)" % ", ".join(sorted(states)))
    state = states.pop()
    if state == "applied":
        texts = {p: v[2] for p, v in plan.items()}
        if cmd == "check":
            text_checks(texts)
            print("applied (text checks pass)"); return
        if cmd == "apply":
            print("already applied"); return
        outs = []
        for path, (raw, eol, cur, edits) in plan.items():
            for old, new in reversed(edits): cur = cur.replace(new, old)
            outs.append((path, cur.replace("\n", eol).encode("utf-8")))
        for path, data in outs:
            open(os.path.join(ROOT, path), "wb").write(data)
        print("reverted"); return
    texts, outs = {}, []
    for path, (raw, eol, cur, edits) in plan.items():
        for old, new in edits: cur = cur.replace(old, new)
        texts[path] = cur
        outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
    text_checks(texts)
    if cmd == "check":
        print("not applied; would apply (%d files, %d edits; text checks on the result pass)"
              % (len(plan), len(EDITS))); return
    if cmd == "revert":
        print("nothing to revert"); return
    os.makedirs(BACKUP, exist_ok=True)
    for path, data, raw in outs:
        open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
    written = []
    try:
        for path, data, raw in outs:
            tmp = os.path.join(ROOT, path) + ".r85tmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, os.path.join(ROOT, path))
            written.append((path, raw))
    except Exception:
        for path, data, raw in outs:
            tmp = os.path.join(ROOT, path) + ".r85tmp"
            if os.path.exists(tmp): os.remove(tmp)
        for path, raw in written:
            open(os.path.join(ROOT, path), "wb").write(raw)
        raise
    print("applied"); return

main()
