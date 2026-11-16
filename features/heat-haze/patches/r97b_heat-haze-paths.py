# r97b_heat-haze-paths: FEATURE patch (fix and in-pass check of r97_heat-haze; apply AFTER r97 and
# revert BEFORE it). Off by default: nothing of it runs unless BB_HEAT_HAZE is above 0, as r97.
#
# Why: r97 logs "600 of 600 frames drew columns" in the slot games (quick 640x360 reduced scene and
# faithful 1080p 1:1) but no pixel of the test view shows there, although halation, written at the
# same place in the same way, does show in quick slot pictures. Reading the code (2026-11-15 22:40)
# finds the CPU side right and the shader's maths right; the one input the haze uses that halation
# does not is the scene depth (two depth tests per pixel) - and the shader can not tell anyone what it
# did. So this patch makes the haze pass report what became of its pixels, and gives two switches that
# show the haze without the depth tests:
#  - the haze pass counts, per workgroup in shared memory and then once into a 64-byte device buffer
#    (copied into a host buffer at the end of the frame's passes): pixels in the columns' rectangles,
#    outside the column's shape, dropped as nearer than the flame, dropped as taking a nearer pixel,
#    written; and where the depth puts the tested pixels (no view z in front, under half the flame's
#    distance, short of the test's limit, behind it, sky). The nearest column keeps its flame pixel's
#    depth, the view z it gives, the test's limit, its lamp's view z and the depth that view z gives.
#    Four short log lines (each under the slot runner's 300 characters) come with r97's line (after
#    the first 120 frames, then every 600), the third a verdict (heat_haze.h Verdict).
#  - BB_HEAT_HAZE_SHOW=2: the test view 1 (tint, 3x shimmer) plus each column's rectangle framed in
#    magenta (2 pixels wide), and the depth tests counted but not applied: a still shows where the
#    columns stand and that the pass reaches the picture on that output path.
# (Review 2026-11-15 23:2x, this .fixed copy: the frame 2 pixels wide, so a temporal upscaler does
# not average a 1-pixel jittering line away; the lamp's own view z kept and printed beside the
# depth's; a verdict for "written, but the depth tests drop or would drop 90% or more"; "distance"
# corrected to "view z" where the code uses view z.)
#  - BB_HEAT_HAZE_DEPTH=0: the plain look without the depth tests (what stands in front of a flame
#    shimmers too): the haze the owner can see on a path whose depth at this place is unusable.
# Off (BB_HEAT_HAZE unset or 0): the Rasterizer makes no HeatHaze (r97's Wanted), so no buffer, no
# count, no line; frames are as before, bit for bit. On, with the defaults (SHOW unset, DEPTH unset)
# the picture is r97's: the same pixels pass the same tests in the same order and write the same
# values (the counting adds shared-memory atomics and no image write).
#
# Files: host_shaders/heat_haze.comp (whole file: the counting, the flags, the outline; the haze's
# maths unchanged), host_shaders/heat_haze_layout.h (new: the words and flags both sides share),
# renderer_vulkan/heat_haze.h (include, Parse for "2", Knobs outline/depth, flags, DepthTests,
# PixelCounts, CountsBetween, Verdict), vk_heat_haze.h (vk_mem_alloc include, buffers, ReportPixels),
# vk_heat_haze.cpp (knob, binding 3, buffers, flags, zeroing, copy, the lines), tests/test_heat_haze.cpp
# (Parse "2", DepthTests, Verdict, CountsBetween), tests/test_effect_pipelines.cpp (r97's row: binding
# 3), gpu/CMakeLists.txt (one line after r97's add_host_shader: the shader's dependency on the layout
# header), README.md (r97's SHOW row; a row for BB_HEAT_HAZE_DEPTH after it).
#
# Use: python -I -X utf8 r97b_heat-haze-paths.fixed.py check | apply | revert
# Root: R97B_ROOT, else <tree>. Line ends kept (each file's own). apply backs the originals up
# in r97b_backup next to this script; revert puts back exactly what apply changed: inserted texts are
# found by themselves (exactly once), replaced texts are swapped back, the new file is removed.
import hashlib, os, sys

ROOT = os.environ.get("R97B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r97b_backup")
VC = "engine/gpu/shadps4/video_core/"
SH = VC + "host_shaders/heat_haze.comp"
LY = VC + "host_shaders/heat_haze_layout.h"
HH = VC + "renderer_vulkan/heat_haze.h"
VH = VC + "renderer_vulkan/vk_heat_haze.h"
VCPP = VC + "renderer_vulkan/vk_heat_haze.cpp"
UT = "engine/tests/test_heat_haze.cpp"
PT = "engine/tests/test_effect_pipelines.cpp"
CM = "engine/gpu/CMakeLists.txt"
RM = "README.md"

# r97's heat_haze.comp as the tree holds it (LF; sha256 of its LF text), replaced whole.
OLD_SHADER_SHA = "60eddb7448d4cfa103278acfec4368a619a2053e4e3325493478bd10fa90389a"
OLD_SHADER = (
'// SPDX-License-Identifier: GPL-3.0-or-later\n'
"// bbport (r97_heat-haze): the heat haze above flames (BB_HEAT_HAZE; vk_heat_haze.cpp, the column's\n"
"// numbers from heat_haze.h). One dispatch a column and pass, over the column's rectangle:\n"
"//  - pass 0 (copy): the scene under the rectangle into the column's place in the atlas;\n"
'//  - pass 1 (haze): inside the column (from the flame up to its top, widening, fading in just\n'
"//    above the flame and out towards the top and the sides), each pixel takes the atlas's colour\n"
'//    a little beside it, moved by a noise that rises with time: a shimmer of a few pixels.\n'
"//    What is nearer the camera than the flame (by more than the column's radius and a margin)\n"
"//    is neither moved nor moved into a pixel behind the column. Alpha stays the pixel's own.\n"
'// The scene is written only where a pixel moves; the copy is read, so no pixel reads another\n'
'// one this pass has already written.\n'
'#version 450\n'
'#extension GL_EXT_samplerless_texture_functions : require\n'
'\n'
'layout(local_size_x = 8, local_size_y = 8) in;\n'
'\n'
'layout(binding = 0, rgba16f) uniform image2D scene_img;\n'
'layout(binding = 1, rgba16f) uniform image2D atlas_img;\n'
'layout(binding = 2) uniform texture2D depth_tex; // D32, depth 0..1 (D3D projection)\n'
'\n'
'// heat_haze.h Push, field for field.\n'
'layout(push_constant) uniform Push {\n'
'    ivec4 rect;  // x, y, width, height in the scene\n'
'    ivec4 atlas; // x, y in the atlas; pass (0 copy, 1 haze); flags (1 show)\n'
"    vec4 axis;   // the flame's x, y and the top's x, y (pixels)\n"
"    vec4 shape;  // half width at the flame (px), widening to the top, reach (px), flame's view z\n"
'    vec4 field;  // pixels a metre at the flame, depth margin (m), fade, seed\n'
'    vec4 clock;  // projection z scale, z offset, time (s), rise (m/s)\n'
'};\n'
'\n'
'uint Hash(uvec3 v) {\n'
'    v = v * 1664525u + 1013904223u;\n'
'    v.x += v.y * v.z;\n'
'    v.y += v.z * v.x;\n'
'    v.z += v.x * v.y;\n'
'    v ^= v >> 16u;\n'
'    v.x += v.y * v.z;\n'
'    return v.x;\n'
'}\n'
'\n'
'float Corner(ivec3 c) {\n'
'    return float(Hash(uvec3(c & 1023)) >> 8u) * (1.0 / 16777216.0);\n'
'}\n'
'\n'
"// Value noise in [0, 1), smooth (quintic) between the lattice's corners.\n"
'float Noise(vec3 p) {\n'
'    const vec3 f = floor(p);\n'
'    const ivec3 i = ivec3(f);\n'
'    const vec3 u = p - f;\n'
'    const vec3 s = u * u * u * (u * (u * 6.0 - 15.0) + 10.0);\n'
'    const float x00 = mix(Corner(i), Corner(i + ivec3(1, 0, 0)), s.x);\n'
'    const float x10 = mix(Corner(i + ivec3(0, 1, 0)), Corner(i + ivec3(1, 1, 0)), s.x);\n'
'    const float x01 = mix(Corner(i + ivec3(0, 0, 1)), Corner(i + ivec3(1, 0, 1)), s.x);\n'
'    const float x11 = mix(Corner(i + ivec3(0, 1, 1)), Corner(i + ivec3(1, 1, 1)), s.x);\n'
'    return mix(mix(x00, x10, s.y), mix(x01, x11, s.y), s.z);\n'
'}\n'
'\n'
'// The view z (m) of a scene pixel; the sky is far behind every flame.\n'
'float ViewZ(ivec2 p) {\n'
'    const float depth = texelFetch(depth_tex, p, 0).r;\n'
'    if (depth >= 1.0) {\n'
'        return 1e9;\n'
'    }\n'
'    return clock.y / min(depth - clock.x, -1e-8);\n'
'}\n'
'\n'
'vec4 Atlas(ivec2 t) {\n'
'    return imageLoad(atlas_img, clamp(t, atlas.xy, atlas.xy + rect.zw - 1));\n'
'}\n'
'\n'
'void main() {\n'
'    const ivec2 local = ivec2(gl_GlobalInvocationID.xy);\n'
'    if (any(greaterThanEqual(local, rect.zw))) {\n'
'        return;\n'
'    }\n'
'    const ivec2 p = rect.xy + local;\n'
'    const ivec2 own = atlas.xy + local;\n'
'    if (atlas.z == 0) {\n'
'        imageStore(atlas_img, own, imageLoad(scene_img, p));\n'
'        return;\n'
'    }\n'
'    const vec2 base = axis.xy;\n'
'    const vec2 along = axis.zw - base;\n'
'    const float len = max(length(along), 1.0);\n'
'    const vec2 dir = along / len;\n'
'    const vec2 across_dir = vec2(-dir.y, dir.x);\n'
'    const vec2 rel = vec2(p) + 0.5 - base;\n'
'    const float t = dot(rel, dir) / len;\n'
'    if (t <= 0.0 || t >= 1.0) {\n'
'        return;\n'
'    }\n'
'    const float half_width = shape.x * (1.0 + shape.y * t);\n'
'    const float across = dot(rel, across_dir);\n'
'    const float x = across / max(half_width, 0.5);\n'
'    if (abs(x) >= 1.0) {\n'
'        return;\n'
'    }\n'
'    const float side = 1.0 - x * x;\n'
'    const float weight = smoothstep(0.0, 0.12, t) * pow(1.0 - t, 1.5) * side * side * field.z;\n'
'    if (weight < 1.0 / 256.0) {\n'
'        return;\n'
'    }\n'
'    const float front = shape.w - field.y;\n'
'    if (ViewZ(p) < front) {\n'
'        return;\n'
'    }\n'
'    // The pattern in metres around the column (eddies of about 11 and 5 cm across, 17 and 7 cm\n'
'    // along it), rising at clock.w m/s and changing slowly as it goes.\n'
'    const float per_metre = max(field.x, 1e-3);\n'
'    const float time = clock.z;\n'
'    const vec3 q = vec3(across / per_metre * 9.0, (t * len / per_metre - time * clock.w) * 6.0,\n'
'                        field.w + time * 0.35);\n'
'    const float n1 = Noise(q) + 0.5 * Noise(q * 2.3 + vec3(7.1, 3.7, 1.3));\n'
'    const float n2 = Noise(q + vec3(19.7, 5.3, 11.1)) + 0.5 * Noise(q * 2.3 + vec3(2.9, 13.1, 4.7));\n'
'    const vec2 d = vec2(n1 - 0.75, 0.5 * (n2 - 0.75)) * (1.0 / 0.75);\n'
'    const vec2 offset = (across_dir * d.x + dir * d.y) * (shape.z * weight);\n'
'    const vec2 source = vec2(p) + 0.5 + offset;\n'
'    const ivec2 source_pixel = clamp(ivec2(floor(source)), rect.xy, rect.xy + rect.zw - 1);\n'
'    if (ViewZ(source_pixel) < front) {\n'
'        return;\n'
'    }\n'
'    // Between the four atlas texels around the source.\n'
'    const vec2 at = source - vec2(rect.xy) + vec2(atlas.xy) - 0.5;\n'
'    const ivec2 lo = ivec2(floor(at));\n'
'    const vec2 f = at - vec2(lo);\n'
'    const vec4 colour = mix(mix(Atlas(lo), Atlas(lo + ivec2(1, 0)), f.x),\n'
'                            mix(Atlas(lo + ivec2(0, 1)), Atlas(lo + ivec2(1, 1)), f.x), f.y);\n'
'    vec3 rgb = colour.rgb;\n'
'    if ((atlas.w & 1) != 0) {\n'
'        // Test view: the column tinted blue-green, its brightness kept but at least a tenth of\n'
"        // the flame's (the pixel at the flame, from the copy): at night the air above a flame\n"
'        // is often near black, where a tint alone would not show.\n'
'        const vec3 luma_weights = vec3(0.2126, 0.7152, 0.0722);\n'
'        const vec3 flame = Atlas(atlas.xy + ivec2(floor(axis.xy)) - rect.xy).rgb;\n'
'        const float luma = max(dot(rgb, luma_weights), 0.1 * dot(max(flame, vec3(0.0)), luma_weights));\n'
'        rgb = mix(rgb, luma * vec3(0.55, 0.95, 1.5), 0.6 * weight / max(field.z, 1e-3));\n'
'    }\n'
'    imageStore(scene_img, p, vec4(rgb, imageLoad(atlas_img, own).a));\n'
'}\n'
)

NEW_SHADER = (
'// SPDX-License-Identifier: GPL-3.0-or-later\n'
"// bbport (r97_heat-haze): the heat haze above flames (BB_HEAT_HAZE; vk_heat_haze.cpp, the column's\n"
"// numbers from heat_haze.h). One dispatch a column and pass, over the column's rectangle:\n"
"//  - pass 0 (copy): the scene under the rectangle into the column's place in the atlas;\n"
'//  - pass 1 (haze): inside the column (from the flame up to its top, widening, fading in just\n'
"//    above the flame and out towards the top and the sides), each pixel takes the atlas's colour\n"
'//    a little beside it, moved by a noise that rises with time: a shimmer of a few pixels.\n'
"//    What is nearer the camera than the flame (by more than the column's radius and a margin)\n"
"//    is neither moved nor moved into a pixel behind the column. Alpha stays the pixel's own.\n"
'// The scene is written only where a pixel moves; the copy is read, so no pixel reads another\n'
'// one this pass has already written.\n'
'// bbport (r97b_heat-haze-paths): the haze pass counts what becomes of its pixels (outside the\n'
"// column's shape, dropped by either depth test, written) and where the depth puts them against\n"
'// the flame, into a small buffer the engine reads back for its log line (heat_haze_layout.h); the\n'
"// frame's nearest column keeps its flame pixel's depth there too. With HH_FLAG_NO_DEPTH the depth\n"
"// tests are counted but not applied; with HH_FLAG_OUTLINE the column's rectangle is framed.\n"
'#version 450\n'
'#extension GL_EXT_samplerless_texture_functions : require\n'
'#extension GL_GOOGLE_include_directive : require\n'
'\n'
'#include "heat_haze_layout.h"\n'
'\n'
'layout(local_size_x = 8, local_size_y = 8) in;\n'
'\n'
'layout(binding = 0, rgba16f) uniform image2D scene_img;\n'
'layout(binding = 1, rgba16f) uniform image2D atlas_img;\n'
'layout(binding = 2) uniform texture2D depth_tex; // D32, depth 0..1 (D3D projection)\n'
'layout(std430, binding = 3) buffer Counters {\n'
'    uint words[HH_WORDS];\n'
'};\n'
'\n'
'// heat_haze.h Push, field for field.\n'
'layout(push_constant) uniform Push {\n'
'    ivec4 rect;  // x, y, width, height in the scene\n'
'    ivec4 atlas; // x, y in the atlas; pass (0 copy, 1 haze); flags (HH_FLAG_*)\n'
"    vec4 axis;   // the flame's x, y and the top's x, y (pixels)\n"
"    vec4 shape;  // half width at the flame (px), widening to the top, reach (px), flame's view z\n"
'    vec4 field;  // pixels a metre at the flame, depth margin (m), fade, seed\n'
'    vec4 clock;  // projection z scale, z offset, time (s), rise (m/s)\n'
'};\n'
'\n'
'shared uint group_counts[HH_COUNTED];\n'
'\n'
'uint Hash(uvec3 v) {\n'
'    v = v * 1664525u + 1013904223u;\n'
'    v.x += v.y * v.z;\n'
'    v.y += v.z * v.x;\n'
'    v.z += v.x * v.y;\n'
'    v ^= v >> 16u;\n'
'    v.x += v.y * v.z;\n'
'    return v.x;\n'
'}\n'
'\n'
'float Corner(ivec3 c) {\n'
'    return float(Hash(uvec3(c & 1023)) >> 8u) * (1.0 / 16777216.0);\n'
'}\n'
'\n'
"// Value noise in [0, 1), smooth (quintic) between the lattice's corners.\n"
'float Noise(vec3 p) {\n'
'    const vec3 f = floor(p);\n'
'    const ivec3 i = ivec3(f);\n'
'    const vec3 u = p - f;\n'
'    const vec3 s = u * u * u * (u * (u * 6.0 - 15.0) + 10.0);\n'
'    const float x00 = mix(Corner(i), Corner(i + ivec3(1, 0, 0)), s.x);\n'
'    const float x10 = mix(Corner(i + ivec3(0, 1, 0)), Corner(i + ivec3(1, 1, 0)), s.x);\n'
'    const float x01 = mix(Corner(i + ivec3(0, 0, 1)), Corner(i + ivec3(1, 0, 1)), s.x);\n'
'    const float x11 = mix(Corner(i + ivec3(0, 1, 1)), Corner(i + ivec3(1, 1, 1)), s.x);\n'
'    return mix(mix(x00, x10, s.y), mix(x01, x11, s.y), s.z);\n'
'}\n'
'\n'
'// The view z (m) a depth gives; the sky is far behind every flame.\n'
'float ViewZOf(float depth) {\n'
'    if (depth >= 1.0) {\n'
'        return 1e9;\n'
'    }\n'
'    return clock.y / min(depth - clock.x, -1e-8);\n'
'}\n'
'\n'
'float ViewZ(ivec2 p) {\n'
'    return ViewZOf(texelFetch(depth_tex, p, 0).r);\n'
'}\n'
'\n'
'vec4 Atlas(ivec2 t) {\n'
'    return imageLoad(atlas_img, clamp(t, atlas.xy, atlas.xy + rect.zw - 1));\n'
'}\n'
'\n'
'void Count(uint word) {\n'
'    atomicAdd(group_counts[word], 1u);\n'
'}\n'
'\n'
'const vec3 luma_weights = vec3(0.2126, 0.7152, 0.0722);\n'
'\n'
"// One pixel of the haze pass, inside the column's rectangle.\n"
'void Haze(ivec2 local) {\n'
'    const ivec2 p = rect.xy + local;\n'
'    const ivec2 own = atlas.xy + local;\n'
'    const bool depth_tests = (atlas.w & HH_FLAG_NO_DEPTH) == 0;\n'
'    const float front = shape.w - field.y;\n'
'    Count(HH_WORD_RECT);\n'
"    // The frame's nearest column: its flame pixel's depth, before any test (the log's numbers).\n"
'    if ((atlas.w & HH_FLAG_PROBE) != 0 && p == ivec2(floor(axis.xy))) {\n'
'        const float depth = texelFetch(depth_tex, p, 0).r;\n'
'        words[HH_WORD_FLAME_DEPTH] = floatBitsToUint(depth);\n'
'        words[HH_WORD_FLAME_Z] = floatBitsToUint(ViewZOf(depth));\n'
'        words[HH_WORD_FLAME_FRONT] = floatBitsToUint(front);\n'
'        words[HH_WORD_FLAME_EXPECT] = floatBitsToUint(clock.x + clock.y / max(shape.w, 1e-3));\n'
'        words[HH_WORD_FLAME_LAMP_Z] = floatBitsToUint(shape.w);\n'
'        atomicAdd(words[HH_WORD_FLAME_SEEN], 1u);\n'
'    }\n'
"    // Test view 2: the rectangle's edge, 2 pixels wide (a temporal upscaler keeps it), magenta\n"
"    // (at least as bright as the flame's pixel).\n"
'    if ((atlas.w & HH_FLAG_OUTLINE) != 0 &&\n'
'        (any(lessThan(local, ivec2(2))) || any(greaterThanEqual(local, rect.zw - 2)))) {\n'
'        const vec3 flame = Atlas(atlas.xy + ivec2(floor(axis.xy)) - rect.xy).rgb;\n'
'        const float bright = max(dot(max(flame, vec3(0.0)), luma_weights), 1.0);\n'
'        imageStore(scene_img, p, vec4(bright * vec3(1.0, 0.0, 1.0), imageLoad(atlas_img, own).a));\n'
'    }\n'
'    const vec2 base = axis.xy;\n'
'    const vec2 along = axis.zw - base;\n'
'    const float len = max(length(along), 1.0);\n'
'    const vec2 dir = along / len;\n'
'    const vec2 across_dir = vec2(-dir.y, dir.x);\n'
'    const vec2 rel = vec2(p) + 0.5 - base;\n'
'    const float t = dot(rel, dir) / len;\n'
'    if (t <= 0.0 || t >= 1.0) {\n'
'        Count(HH_WORD_SHAPE);\n'
'        return;\n'
'    }\n'
'    const float half_width = shape.x * (1.0 + shape.y * t);\n'
'    const float across = dot(rel, across_dir);\n'
'    const float x = across / max(half_width, 0.5);\n'
'    if (abs(x) >= 1.0) {\n'
'        Count(HH_WORD_SHAPE);\n'
'        return;\n'
'    }\n'
'    const float side = 1.0 - x * x;\n'
'    const float weight = smoothstep(0.0, 0.12, t) * pow(1.0 - t, 1.5) * side * side * field.z;\n'
'    if (weight < 1.0 / 256.0) {\n'
'        Count(HH_WORD_SHAPE);\n'
'        return;\n'
'    }\n'
'    const float depth = texelFetch(depth_tex, p, 0).r;\n'
'    const float z = ViewZOf(depth);\n'
'    if (depth >= 1.0) {\n'
'        Count(HH_WORD_Z_SKY);\n'
'    } else if (!(z > 0.0) || isinf(z) || isnan(z)) {\n'
'        Count(HH_WORD_Z_BAD);\n'
'    } else if (z < 0.5 * shape.w) {\n'
'        Count(HH_WORD_Z_CLOSE);\n'
'    } else if (z < front) {\n'
'        Count(HH_WORD_Z_FRONT);\n'
'    } else {\n'
'        Count(HH_WORD_Z_BEHIND);\n'
'    }\n'
'    if (z < front) {\n'
'        Count(HH_WORD_NEAR);\n'
'        if (depth_tests) {\n'
'            return;\n'
'        }\n'
'    }\n'
'    // The pattern in metres around the column (eddies of about 11 and 5 cm across, 17 and 7 cm\n'
'    // along it), rising at clock.w m/s and changing slowly as it goes.\n'
'    const float per_metre = max(field.x, 1e-3);\n'
'    const float time = clock.z;\n'
'    const vec3 q = vec3(across / per_metre * 9.0, (t * len / per_metre - time * clock.w) * 6.0,\n'
'                        field.w + time * 0.35);\n'
'    const float n1 = Noise(q) + 0.5 * Noise(q * 2.3 + vec3(7.1, 3.7, 1.3));\n'
'    const float n2 = Noise(q + vec3(19.7, 5.3, 11.1)) + 0.5 * Noise(q * 2.3 + vec3(2.9, 13.1, 4.7));\n'
'    const vec2 d = vec2(n1 - 0.75, 0.5 * (n2 - 0.75)) * (1.0 / 0.75);\n'
'    const vec2 offset = (across_dir * d.x + dir * d.y) * (shape.z * weight);\n'
'    const vec2 source = vec2(p) + 0.5 + offset;\n'
'    const ivec2 source_pixel = clamp(ivec2(floor(source)), rect.xy, rect.xy + rect.zw - 1);\n'
'    if (ViewZ(source_pixel) < front) {\n'
'        Count(HH_WORD_SOURCE);\n'
'        if (depth_tests) {\n'
'            return;\n'
'        }\n'
'    }\n'
'    // Between the four atlas texels around the source.\n'
'    const vec2 at = source - vec2(rect.xy) + vec2(atlas.xy) - 0.5;\n'
'    const ivec2 lo = ivec2(floor(at));\n'
'    const vec2 f = at - vec2(lo);\n'
'    const vec4 colour = mix(mix(Atlas(lo), Atlas(lo + ivec2(1, 0)), f.x),\n'
'                            mix(Atlas(lo + ivec2(0, 1)), Atlas(lo + ivec2(1, 1)), f.x), f.y);\n'
'    vec3 rgb = colour.rgb;\n'
'    if ((atlas.w & HH_FLAG_SHOW) != 0) {\n'
'        // Test view: the column tinted blue-green, its brightness kept but at least a tenth of\n'
"        // the flame's (the pixel at the flame, from the copy): at night the air above a flame\n"
'        // is often near black, where a tint alone would not show.\n'
'        const vec3 flame = Atlas(atlas.xy + ivec2(floor(axis.xy)) - rect.xy).rgb;\n'
'        const float luma = max(dot(rgb, luma_weights), 0.1 * dot(max(flame, vec3(0.0)), luma_weights));\n'
'        rgb = mix(rgb, luma * vec3(0.55, 0.95, 1.5), 0.6 * weight / max(field.z, 1e-3));\n'
'    }\n'
'    imageStore(scene_img, p, vec4(rgb, imageLoad(atlas_img, own).a));\n'
'    Count(HH_WORD_WRITTEN);\n'
'}\n'
'\n'
'void main() {\n'
'    const ivec2 local = ivec2(gl_GlobalInvocationID.xy);\n'
'    const bool inside = all(lessThan(local, rect.zw));\n'
'    if (atlas.z == HH_PASS_COPY) {\n'
'        // (atlas.z is the same for the whole dispatch: this return is uniform)\n'
'        if (inside) {\n'
'            imageStore(atlas_img, atlas.xy + local, imageLoad(scene_img, rect.xy + local));\n'
'        }\n'
'        return;\n'
'    }\n'
'    if (gl_LocalInvocationIndex < HH_COUNTED) {\n'
'        group_counts[gl_LocalInvocationIndex] = 0u;\n'
'    }\n'
'    memoryBarrierShared();\n'
'    barrier();\n'
'    if (inside) {\n'
'        Haze(local);\n'
'    }\n'
'    memoryBarrierShared();\n'
'    barrier();\n'
'    if (gl_LocalInvocationIndex < HH_COUNTED) {\n'
'        const uint n = group_counts[gl_LocalInvocationIndex];\n'
'        if (n != 0u) {\n'
'            atomicAdd(words[gl_LocalInvocationIndex], n);\n'
'        }\n'
'    }\n'
'}\n'
)

NEW_LAYOUT = (
'// SPDX-License-Identifier: GPL-3.0-or-later\n'
"// bbport (r97b_heat-haze-paths): what the heat haze's shader (heat_haze.comp) and the engine\n"
'// (renderer_vulkan/heat_haze.h, which ties these to its constants with static_asserts) share.\n'
'// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and\n'
'// C++ includes it as it is, so one text holds every number both sides use.\n'
'#ifndef HEAT_HAZE_LAYOUT_H\n'
'#define HEAT_HAZE_LAYOUT_H\n'
'\n'
'// The pass, by the push word atlas.z (BbHeatHaze::PassCopy, PassHaze).\n'
'#define HH_PASS_COPY 0\n'
'#define HH_PASS_HAZE 1\n'
'// The flags, by the push word atlas.w (BbHeatHaze::Flag*).\n'
'#define HH_FLAG_SHOW 1     // BB_HEAT_HAZE_SHOW=1 or 2: the column tinted\n'
"#define HH_FLAG_OUTLINE 2  // BB_HEAT_HAZE_SHOW=2: the column's rectangle framed (2 pixels)\n"
'#define HH_FLAG_NO_DEPTH 4 // BB_HEAT_HAZE_DEPTH=0 or BB_HEAT_HAZE_SHOW=2: no depth test\n'
"#define HH_FLAG_PROBE 8    // the frame's nearest column: its flame pixel's depth is kept\n"
"// The counter buffer's words (BbHeatHaze::Word*): totals since the pass was made, never cleared.\n"
'// Words 0 to 9 are counted per workgroup in shared memory and added once a workgroup.\n'
"#define HH_WORD_RECT 0u     // haze pass pixels inside a column's rectangle\n"
"#define HH_WORD_SHAPE 1u    // of them outside the column's shape (or too weak to move)\n"
'#define HH_WORD_NEAR 2u     // tested pixels nearer the camera than the flame (the depth test)\n'
'#define HH_WORD_SOURCE 3u   // tested pixels whose source pixel is nearer (the second depth test)\n'
'#define HH_WORD_WRITTEN 4u  // pixels written\n'
'#define HH_WORD_Z_BAD 5u    // tested pixels whose depth gives no view z in front of the camera\n'
"#define HH_WORD_Z_CLOSE 6u  // ... a view z under half the flame's\n"
"#define HH_WORD_Z_FRONT 7u  // ... from half the flame's up to the depth test's limit\n"
'#define HH_WORD_Z_BEHIND 8u // ... behind that limit (not the sky)\n'
'#define HH_WORD_Z_SKY 9u    // ... the sky (depth 1)\n'
'#define HH_COUNTED 10u\n'
"// The nearest column's flame pixel, last frame it was seen (float bits): its depth, the view z\n"
"// that depth gives, the depth test's limit (m), the depth the lamp's own view z would give, how\n"
"// many times they were written, and the lamp's view z (m).\n"
'#define HH_WORD_FLAME_DEPTH 10u\n'
'#define HH_WORD_FLAME_Z 11u\n'
'#define HH_WORD_FLAME_FRONT 12u\n'
'#define HH_WORD_FLAME_EXPECT 13u\n'
'#define HH_WORD_FLAME_SEEN 14u\n'
'#define HH_WORD_FLAME_LAMP_Z 15u\n'
'#define HH_WORDS 16u\n'
'\n'
'#endif\n'
)

# Edits: ("insert", anchor, before, after) keeps the anchor and puts `before` in front of it and `after`
# behind it; ("replace", old, new) swaps one text for another.
EDITS = {
HH: [
("insert", "#include <vector>\n", "",
 '#include "../host_shaders/heat_haze_layout.h" // bbport (r97b_heat-haze-paths): the shader\'s numbers\n'),
("insert", "    bool unreadable = false; ///< BB_HEAT_HAZE held text that is not a number: off\n", "",
 "    // bbport (r97b_heat-haze-paths)\n"
 "    bool outline = false; ///< BB_HEAT_HAZE_SHOW=2: the test view with rectangles, no depth test\n"
 "    bool depth = true;    ///< the depth tests (vk_heat_haze.cpp: DepthTests and not SHOW=2)\n"),
("replace",
 '/// the look as designed, 0 is off); any other text is off. BB_HEAT_HAZE_SHOW: exactly "1".\n',
 '/// the look as designed, 0 is off); any other text is off. BB_HEAT_HAZE_SHOW: exactly "1", or\n'
 '/// (r97b) exactly "2": the test view 1 with each column\'s rectangle outlined and no depth test.\n'),
("replace",
 "    knobs.show = knobs.strength > 0.0f && show != nullptr && show[0] == '1' && show[1] == 0;\n",
 "    knobs.show = knobs.strength > 0.0f && show != nullptr && (show[0] == '1' || show[0] == '2') &&\n"
 "                 show[1] == 0;\n"
 "    knobs.outline = knobs.show && show[0] == '2'; // bbport (r97b_heat-haze-paths)\n"),
("insert", "inline constexpr std::int32_t FlagShow = 1; ///< BB_HEAT_HAZE_SHOW=1: the column tinted too\n", "",
 r'''// bbport (r97b_heat-haze-paths): the other flags, the haze pass's pixel counters and what they
// say. The numbers are heat_haze_layout.h's, the text the shader includes too.
inline constexpr std::int32_t FlagOutline = HH_FLAG_OUTLINE; ///< BB_HEAT_HAZE_SHOW=2: rectangles
inline constexpr std::int32_t FlagNoDepth = HH_FLAG_NO_DEPTH; ///< the depth tests counted only
inline constexpr std::int32_t FlagProbe = HH_FLAG_PROBE; ///< the nearest column: its flame pixel
static_assert(PassCopy == HH_PASS_COPY && PassHaze == HH_PASS_HAZE && FlagShow == HH_FLAG_SHOW);
static_assert((FlagShow | FlagOutline | FlagNoDepth | FlagProbe) == 15, "one bit each");
inline constexpr std::uint32_t CounterWords = HH_WORDS; ///< the counter buffer: 4 bytes a word
static_assert(HH_COUNTED == HH_WORD_Z_SKY + 1 && HH_WORD_FLAME_DEPTH == HH_COUNTED &&
              HH_WORD_FLAME_SEEN < HH_WORDS && HH_WORD_FLAME_LAMP_Z < HH_WORDS && HH_COUNTED <= 64,
              "the counted words fit one 8x8 workgroup's first invocations");

/// BB_HEAT_HAZE_DEPTH: exactly "0" turns the depth tests off (what is nearer the camera than the
/// flame shimmers too); unset or any other text keeps them.
inline bool DepthTests(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == 0);
}

/// The haze pass's pixel counts between two reads of the counter words (heat_haze_layout.h).
struct PixelCounts {
    std::uint64_t rect = 0;    ///< pixels in the columns' rectangles
    std::uint64_t shape = 0;   ///< of them outside the column's shape (or too weak to move)
    std::uint64_t nearer = 0;  ///< tested pixels nearer the camera than the depth test's limit
    std::uint64_t source = 0;  ///< tested pixels whose source pixel is nearer than it
    std::uint64_t written = 0; ///< pixels written
    std::uint64_t z_bad = 0, z_close = 0, z_front = 0, z_behind = 0, sky = 0; ///< see the layout
    [[nodiscard]] std::uint64_t Tested() const {
        return rect > shape ? rect - shape : 0;
    }
};

/// The counts since `before` (the words are 32-bit totals; the difference wraps as they do).
inline PixelCounts CountsBetween(const std::uint32_t* now, const std::uint32_t* before) {
    const auto d = [&](std::uint32_t word) {
        return std::uint64_t(std::uint32_t(now[word] - before[word]));
    };
    PixelCounts c;
    c.rect = d(HH_WORD_RECT);
    c.shape = d(HH_WORD_SHAPE);
    c.nearer = d(HH_WORD_NEAR);
    c.source = d(HH_WORD_SOURCE);
    c.written = d(HH_WORD_WRITTEN);
    c.z_bad = d(HH_WORD_Z_BAD);
    c.z_close = d(HH_WORD_Z_CLOSE);
    c.z_front = d(HH_WORD_Z_FRONT);
    c.z_behind = d(HH_WORD_Z_BEHIND);
    c.sky = d(HH_WORD_Z_SKY);
    return c;
}

/// What the counts say about a column that the CPU drew and the picture may not show.
/// "Unusable" depth: no view z in front of the camera, or a view z under half the flame's, for 90%
/// or more of the tested pixels (the columns stand above a flame, where the scene is seldom that
/// much nearer the camera than the flame). "Covered": the depth tests drop 90% or more of them, or
/// would where they are counted only (BB_HEAT_HAZE_DEPTH=0, BB_HEAT_HAZE_SHOW=2).
inline const char* Verdict(const PixelCounts& c) {
    const std::uint64_t tested = c.Tested();
    if (c.rect == 0) {
        return "no pixel of a column reached the haze pass since the last line";
    }
    if (tested == 0) {
        return "every pixel fell outside the columns' shape: the column's numbers are at fault";
    }
    const bool unusable = (c.z_bad + c.z_close) * 10 >= tested * 9;
    if (c.written == 0) {
        return unusable ? "nothing written: the depth tests drop every pixel, and the depth read "
                          "here puts 90% or more of them under half the flame's view z or "
                          "nowhere: the depth image before the upscaler is not this view's depth"
                        : "nothing written: the depth tests drop every pixel; the depth puts "
                          "something nearer than the flame over the columns";
    }
    if (unusable) {
        return "pixels written (depth tests off or passed), but the depth read here puts 90% or "
               "more of them under half the flame's view z or nowhere: the depth image before "
               "the upscaler is not this view's depth";
    }
    if ((c.nearer + c.source) * 10 >= tested * 9) {
        return "pixels written, but the depth tests drop (or, counted only, would drop) 90% or "
               "more: the depth puts something nearer than the flame over the columns (compare "
               "the flame pixel's view z with its lamp's)";
    }
    return "pixels written: if the picture shows no column, the write is lost after this pass";
}
'''),
],
VH: [
("insert", '#include "video_core/renderer_vulkan/vk_common.h"\n', "",
 "#include <vk_mem_alloc.h> // bbport (r97b_heat-haze-paths): after vk_common.h (its configuration)\n"),
("insert", "    std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();\n", "",
 r'''    // bbport (r97b_heat-haze-paths): the haze pass's pixel counters (heat_haze_layout.h): 32-bit
    // totals in device memory, copied into the host buffer after each frame's haze passes; the log
    // reads the host copy (a frame or two old, as the GPU left it) and prints the differences.
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    void ReportPixels();
    Buffer counter_buffer, counter_host;
    bool counters_zeroed = false; ///< the first drawing frame's pass filled them with zeros
    std::array<u32, ::BbHeatHaze::CounterWords> counters_seen{}; ///< as the last line read them
'''),
],
VCPP: [
("insert", "#include <cstdlib>\n", "",
 "#include <cstring> // bbport (r97b_heat-haze-paths)\n#include <utility>\n"),
("replace",
 '        const BbHeatHaze::Knobs read = BbHeatHaze::Parse(haze, std::getenv("BB_HEAT_HAZE_SHOW"));\n',
 '        BbHeatHaze::Knobs read = BbHeatHaze::Parse(haze, std::getenv("BB_HEAT_HAZE_SHOW"));\n'
 '        // bbport (r97b_heat-haze-paths): BB_HEAT_HAZE_DEPTH=0, or the test view 2, drops the\n'
 '        // depth tests\n'
 '        read.depth = BbHeatHaze::DepthTests(std::getenv("BB_HEAT_HAZE_DEPTH")) && !read.outline;\n'),
("replace",
 "                              {StorageImage, StorageImage, SampledImage},\n"
 '                              sizeof(BbHeatHaze::Push), HEAT_HAZE_COMP, "Heat haze");\n',
 "                              {StorageImage, StorageImage, SampledImage,\n"
 "                               vk::DescriptorType::eStorageBuffer}, // r97b: the counters\n"
 '                              sizeof(BbHeatHaze::Push), HEAT_HAZE_COMP, "Heat haze") &&\n'
 "           // bbport (r97b_heat-haze-paths): the pixel counters, 64 bytes on the GPU and 64 in\n"
 "           // host memory\n"
 "           MakeBuffer(counter_buffer, BbHeatHaze::CounterWords * 4, false,\n"
 "                      vk::BufferUsageFlagBits::eStorageBuffer |\n"
 "                          vk::BufferUsageFlagBits::eTransferSrc |\n"
 "                          vk::BufferUsageFlagBits::eTransferDst) &&\n"
 "           MakeBuffer(counter_host, BbHeatHaze::CounterWords * 4, true,\n"
 "                      vk::BufferUsageFlagBits::eTransferDst);\n"
 "    if (made) {\n"
 "        std::memset(counter_host.mapped, 0, BbHeatHaze::CounterWords * 4);\n"
 "    }\n"),
("replace",
 '                knobs.show ? "on (BB_HEAT_HAZE_SHOW=1: 3 times the shimmer, the columns tinted)"\n'
 '                           : "off");\n',
 '                knobs.show ? "on (BB_HEAT_HAZE_SHOW=1 or 2: 3 times the shimmer, the columns tinted)"\n'
 '                           : "off");\n'
 r'''    // bbport (r97b_heat-haze-paths)
    std::printf("Heat haze (r97b): depth tests %s; test view 2 (rectangles outlined, no depth test) "
                "%s; the haze pass counts its pixels for the log\n",
                knobs.depth ? "on" : "off (BB_HEAT_HAZE_DEPTH=0 or BB_HEAT_HAZE_SHOW=2)",
                knobs.outline ? "on" : "off");
'''),
("insert", "HeatHaze::~HeatHaze() {\n    const auto device = instance.GetDevice();\n", "",
 "    FreeBuffer(counter_buffer); // bbport (r97b_heat-haze-paths)\n    FreeBuffer(counter_host);\n"),
("insert", "void HeatHaze::NoSceneHooks() {\n",
 r'''// bbport (r97b_heat-haze-paths): a buffer of the pixel counters (as Halation::MakeBuffer).
bool HeatHaze::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host,
                          vk::BufferUsageFlags usage) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = static_cast<VkBufferUsageFlags>(usage),
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (host) {
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags =
            VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    }
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &out.allocation,
                        &info) != VK_SUCCESS) {
        return false;
    }
    out.buffer = raw;
    out.mapped = info.pMappedData;
    return !host || out.mapped;
}

void HeatHaze::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

// bbport (r97b_heat-haze-paths): what the haze pass did with its pixels since the last line, and the
// nearest column's flame pixel: the numbers that say why a column the CPU drew shows nothing (the
// column's shape, the depth image read before the upscaler, or a write lost after this pass).
void HeatHaze::ReportPixels() {
    if (!counter_host.mapped) {
        return;
    }
    std::array<u32, BbHeatHaze::CounterWords> now{};
    std::memcpy(now.data(), counter_host.mapped, sizeof(now));
    const auto c = BbHeatHaze::CountsBetween(now.data(), counters_seen.data());
    const bool flame_seen = now[HH_WORD_FLAME_SEEN] != counters_seen[HH_WORD_FLAME_SEEN];
    counters_seen = now;
    const auto ull = [](u64 v) { return static_cast<unsigned long long>(v); };
    BbReport::Printf("Heat haze (r97b): of %llu column pixels %llu tested (depth tests %s): %llu "
                     "written, %llu nearer than the flame, %llu taking a nearer pixel; %llu outside "
                     "the column's shape\n",
                     ull(c.rect), ull(c.Tested()), knobs.depth ? "on" : "off, counted only",
                     ull(c.written), ull(c.nearer), ull(c.source), ull(c.shape));
    BbReport::Printf("Heat haze (r97b): the depth puts the tested pixels %llu nowhere, %llu under "
                     "half the flame's view z, %llu short of the test's limit, %llu behind it, "
                     "%llu at the sky\n",
                     ull(c.z_bad), ull(c.z_close), ull(c.z_front), ull(c.z_behind), ull(c.sky));
    BbReport::Printf("Heat haze (r97b): %s\n", BbHeatHaze::Verdict(c));
    if (flame_seen) {
        const auto word = [&](u32 w) { return double(std::bit_cast<float>(now[w])); };
        BbReport::Printf("Heat haze (r97b): nearest flame's pixel: depth %.6f = view z %.2f m; its "
                         "lamp's view z %.2f m would read %.6f; the depth test's limit %.2f m\n",
                         word(HH_WORD_FLAME_DEPTH), word(HH_WORD_FLAME_Z),
                         word(HH_WORD_FLAME_LAMP_Z), word(HH_WORD_FLAME_EXPECT),
                         word(HH_WORD_FLAME_FRONT));
    }
}

''', ""),
("insert", "        pushes[i].clock[2] = time;\n", "",
 "        // bbport (r97b_heat-haze-paths): the test view 2, the depth tests' switch and the nearest\n"
 "        // column (the last one: they come farthest first) keeping its flame pixel's depth\n"
 "        pushes[i].atlas[3] |= (knobs.outline ? BbHeatHaze::FlagOutline : 0) |\n"
 "                              (knobs.depth ? 0 : BbHeatHaze::FlagNoDepth) |\n"
 "                              (i + 1 == count ? BbHeatHaze::FlagProbe : 0);\n"),
("insert", '    EffectPass::Mark(ProfileRow, "heat haze");\n',
 "    // bbport (r97b_heat-haze-paths): the counters start at zero (filled at the first drawing frame)\n"
 "    const bool zero_counters = !std::exchange(counters_zeroed, true);\n", ""),
("replace",
 "         pass_layout = *layout](vk::CommandBuffer cmdbuf) {\n",
 "         pass_layout = *layout, counters = counter_buffer.buffer, host = counter_host.buffer,\n"
 "         zero_counters](vk::CommandBuffer cmdbuf) {\n"),
("insert",
 "            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,\n"
 "                                      Compute, ReadWrite);\n", "",
 "            if (zero_counters) { // bbport (r97b_heat-haze-paths)\n"
 "                cmdbuf.fillBuffer(counters, 0, VK_WHOLE_SIZE, 0);\n"
 "                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,\n"
 "                                          vk::AccessFlagBits2::eTransferWrite, Compute, ReadWrite);\n"
 "            }\n"),
("replace",
 "            const std::array writes{Write(0, StorageImage, &infos[0]),\n"
 "                                    Write(1, StorageImage, &infos[1]),\n"
 "                                    Write(2, SampledImage, &infos[2])};\n",
 "            // bbport (r97b_heat-haze-paths): binding 3, the pixel counters\n"
 "            const vk::DescriptorBufferInfo counter_info{counters, 0, VK_WHOLE_SIZE};\n"
 "            const std::array writes{Write(0, StorageImage, &infos[0]),\n"
 "                                    Write(1, StorageImage, &infos[1]),\n"
 "                                    Write(2, SampledImage, &infos[2]),\n"
 "                                    vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1,\n"
 "                                                           .descriptorType =\n"
 "                                                               vk::DescriptorType::eStorageBuffer,\n"
 "                                                           .pBufferInfo = &counter_info}};\n"),
("insert",
 "            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,\n"
 "                                      AllCommands, MemoryAll);\n", "",
 "            // bbport (r97b_heat-haze-paths): the counters' totals into the host copy\n"
 "            cmdbuf.copyBuffer(counters, host, vk::BufferCopy{0, 0, BbHeatHaze::CounterWords * 4});\n"
 "            EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,\n"
 "                                      vk::AccessFlagBits2::eTransferWrite,\n"
 "                                      vk::PipelineStageFlagBits2::eHost,\n"
 "                                      vk::AccessFlagBits2::eHostRead);\n"),
("insert", "    stats = {};\n", "    ReportPixels(); // bbport (r97b_heat-haze-paths)\n", ""),
],
UT: [
("replace",
 '        assert(!Parse("1", "2").show && !Parse("1", "11").show && !Parse("1", "").show);\n',
 r'''        // bbport (r97b_heat-haze-paths): "2" is the test view with rectangles and no depth test
        assert(Parse("1", "2").show && Parse("1", "2").outline && !Parse("1", "1").outline);
        assert(!Parse("0", "2").show && !Parse("0", "2").outline && !Parse("1", nullptr).outline);
        assert(!Parse("1", "3").show && !Parse("1", "11").show && !Parse("1", "").show &&
               !Parse("1", "22").outline);
        assert(Parse("1", nullptr).depth && DepthTests(nullptr) && DepthTests("") &&
               DepthTests("1") && DepthTests("00") && !DepthTests("0"));
'''),
("insert", '    std::printf("heat-haze-test: all checks passed\\n");\n',
 r'''    // k. bbport (r97b_heat-haze-paths): the pass's counters and what the log line makes of them.
    {
        std::array<std::uint32_t, CounterWords> before{}, now{};
        before[HH_WORD_RECT] = 0xfffffff0u; // a total that wrapped since the last line
        now[HH_WORD_RECT] = 0x10u;
        now[HH_WORD_WRITTEN] = 7u;
        PixelCounts c = CountsBetween(now.data(), before.data());
        assert(c.rect == 0x20u && c.written == 7u && c.shape == 0u && c.Tested() == 0x20u);
        PixelCounts none;
        assert(std::string_view(Verdict(none)).starts_with("no pixel"));
        PixelCounts shape_only;
        shape_only.rect = shape_only.shape = 100;
        assert(std::string_view(Verdict(shape_only)).starts_with("every pixel fell outside"));
        PixelCounts zero_depth; // a depth of 0: every view z at the near plane
        zero_depth.rect = 1000;
        zero_depth.shape = 400;
        zero_depth.z_close = 600;
        zero_depth.nearer = 600;
        assert(std::string_view(Verdict(zero_depth)).find("not this view's depth") !=
               std::string_view::npos);
        PixelCounts covered = zero_depth; // a real wall in front of the flame
        covered.z_close = 0;
        covered.z_front = 600;
        assert(std::string_view(Verdict(covered)).find("something nearer") != std::string_view::npos);
        PixelCounts shown = covered;
        shown.z_front = 100;
        shown.z_behind = 500;
        shown.nearer = 100;
        shown.written = 500;
        assert(std::string_view(Verdict(shown)).starts_with("pixels written: if"));
        PixelCounts forced = zero_depth; // depth tests off: written, the depth still unusable
        forced.written = 600;
        assert(std::string_view(Verdict(forced)).find("not this view's depth") !=
               std::string_view::npos);
        PixelCounts hidden = covered; // depth tests counted only: written, all would be dropped
        hidden.written = 600;
        assert(std::string_view(Verdict(hidden)).find("counted only, would drop) 90% or more") !=
               std::string_view::npos);
        hidden.written = 30; // depth tests on: 570 dropped, 30 written
        hidden.nearer = 570;
        assert(std::string_view(Verdict(hidden)).find("counted only, would drop) 90% or more") !=
               std::string_view::npos);
        for (const PixelCounts& v : {none, shape_only, zero_depth, covered, shown, forced, hidden}) {
            assert(std::string_view(Verdict(v)).size() < 250); // a slot log keeps 300 characters
        }
    }
''', ""),
("insert", "#include <cstdio>\n", "", "#include <string_view> // bbport (r97b_heat-haze-paths)\n"),
],
PT: [
("replace",
 '        {"heat haze", HEAT_HAZE_COMP, {eStorageImage, eStorageImage, eSampledImage}, 96},\n',
 '        {"heat haze", HEAT_HAZE_COMP,\n'
 '         {eStorageImage, eStorageImage, eSampledImage, eStorageBuffer}, // r97b: the counters\n'
 '         96},\n'),
],
CM: [
("insert", "add_host_shader(heat_haze.comp heat_haze_comp)\n", "",
 "add_custom_command(OUTPUT ${SHADER_DIR}/heat_haze_comp.h APPEND DEPENDS ${SHADER_SRC}/heat_haze_layout.h)"
 " # bbport (r97b_heat-haze-paths): the shader's include\n"),
],
}

SHOW_ROW_START = "| `BB_HEAT_HAZE_SHOW` | Test view, with `BB_HEAT_HAZE` above 0: `1` makes the shimmer 3 times"
SHOW_ROW_TAIL = " it draws the same columns as without it | off |"
SHOW_ROW_NEW_TAIL = (" it draws the same columns as without it. `2` (r97b) does the same, frames each column's"
                     " rectangle in magenta, 2 pixels wide (at least as bright as the flame), and turns the depth"
                     " tests off, so"
                     " a still shows where the columns stand and that the haze reaches the picture on that"
                     " output path | off |")
DEPTH_ROW = ("| `BB_HEAT_HAZE_DEPTH` | `0` turns the heat haze's two depth tests off: what stands nearer the"
             " camera than the flame (by more than the column's radius and 0.15 m) shimmers too; the test"
             " view `2` turns them off as well. Unset or any other value keeps them. Either way the haze"
             " pass counts its pixels (r97b), and the log says with the heat haze's own line (after the"
             " first 120 frames, then every 600): how many pixels of the columns were tested, written and"
             " dropped by each depth test, where the depth puts them against the flame (nowhere, under"
             " half its view z, short of the test's limit, behind it, sky), what that means, and the"
             " depth read at the nearest flame's pixel with its view z against the lamp's own view z."
             " Cost of the count: shared-memory adds in the haze pass, at most 10 buffer adds a workgroup"
             " and one 64-byte copy a frame that draws columns | on |\n")


def readme_edits(text):
    rows = [l for l in text.split("\n") if l.startswith(SHOW_ROW_START)]
    if len(rows) != 1:
        raise SystemExit("README.md: the BB_HEAT_HAZE_SHOW row is there %d times, wanted 1" % len(rows))
    row = rows[0]
    if row.endswith(SHOW_ROW_NEW_TAIL):
        new_row = row
        old_row = row[: -len(SHOW_ROW_NEW_TAIL)] + SHOW_ROW_TAIL
    elif row.endswith(SHOW_ROW_TAIL):
        old_row = row
        new_row = row[: -len(SHOW_ROW_TAIL)] + SHOW_ROW_NEW_TAIL
    else:
        raise SystemExit("README.md: the BB_HEAT_HAZE_SHOW row ends in an unknown way")
    # the DEPTH row goes right after the SHOW row: one replace of the row (+ the new row behind it)
    return [("replace", old_row + "\n", new_row + "\n" + DEPTH_ROW)]


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return None, "\n", None
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def state_of(cur, eds, path):
    """'applied' or 'clean' when every edit reads so; anything else refuses."""
    done = todo = 0
    for ed in eds:
        if ed[0] == "insert":
            _, anchor, before, after = ed
            parts = [t for t in (before, after) if t]
            na, counts = cur.count(anchor), [cur.count(t) for t in parts]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s "
                                 "times: %r" % (path, na, counts, anchor[:70]))
        else:
            _, old, new = ed
            no, nn = cur.count(old), cur.count(new)
            if no == 0 and nn == 1:
                done += 1
            elif no == 1 and nn == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times, its new text %d times: %r"
                                 % (path, no, nn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_edits(cur, eds):
    for ed in eds:
        if ed[0] == "insert":
            _, anchor, before, after = ed
            cur = cur.replace(anchor, before + anchor + after, 1)
        else:
            cur = cur.replace(ed[1], ed[2], 1)
    return cur


def revert_edits(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "insert":
            _, anchor, before, after = ed
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        else:
            cur = cur.replace(ed[2], ed[1], 1)
    return cur


# Text checks on the result: ties no compiler checks.
def text_checks(t):
    s = t[SH]
    for want, n in (('#include "heat_haze_layout.h"', 1), ("layout(std430, binding = 3) buffer Counters", 1),
                    ("(atlas.w & HH_FLAG_NO_DEPTH) == 0", 1), ("(atlas.w & HH_FLAG_OUTLINE) != 0", 1),
                    ("(atlas.w & HH_FLAG_PROBE) != 0", 1), ("(atlas.w & HH_FLAG_SHOW) != 0", 1),
                    ("    barrier();", 2), ("imageStore(scene_img", 2), ("Count(HH_WORD_WRITTEN);", 1),
                    ("words[HH_WORD_FLAME_LAMP_Z] = floatBitsToUint(shape.w);", 1),
                    ("any(lessThan(local, ivec2(2)))", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (SH, want, s.count(want), n))
    # the haze's maths is r97's: every line of r97's main body from `const vec2 base` to the colour
    # mix is in the new shader too
    old_body = OLD_SHADER[OLD_SHADER.index("    const vec2 base = axis.xy;"):OLD_SHADER.index("    vec3 rgb = colour.rgb;")]
    for line in old_body.split("\n"):
        st = line.strip()
        if st and not st.startswith("if (") and not st.startswith("return") and st != "}" and st not in s:
            raise SystemExit("text check: r97's shader line is not in the new shader: %r" % st)
    lay = t[LY]
    for name, value in (("HH_PASS_COPY", "0"), ("HH_PASS_HAZE", "1"), ("HH_FLAG_SHOW", "1"),
                        ("HH_WORDS", "16u"), ("HH_COUNTED", "10u"), ("HH_WORD_FLAME_LAMP_Z", "15u")):
        if "#define %s %s" % (name, value) not in lay:
            raise SystemExit("text check: the layout header lacks #define %s %s" % (name, value))
    if "binding = 3" not in s or "vk::DescriptorType::eStorageBuffer}, // r97b: the counters" not in t[VCPP]:
        raise SystemExit("text check: binding 3 is not made")
    if "{eStorageImage, eStorageImage, eSampledImage, eStorageBuffer}, // r97b: the counters" not in t[PT]:
        raise SystemExit("text check: the pipeline test's row lacks the counters")
    # the descriptor writes and the layout name the same 4 bindings in order
    c = t[VCPP]
    if not (c.find("Write(0, StorageImage") < c.find("Write(1, StorageImage") < c.find("Write(2, SampledImage")
            < c.find(".dstBinding = 3")):
        raise SystemExit("text check: the descriptor writes are out of order")
    if c.count("ReportPixels();") != 1 or c.find("ReportPixels();") > c.find("    stats = {};\n"):
        raise SystemExit("text check: ReportPixels is not called before Report resets the stats")
    rm = t[RM]
    i, j = rm.find("| `BB_HEAT_HAZE_SHOW` |"), rm.find("| `BB_HEAT_HAZE_DEPTH` |")
    if not (0 <= i < j) or rm[i:j].count("\n") != 1:
        raise SystemExit("text check: the README's DEPTH row is not right after the SHOW row")
    cm = t[CM]
    a, b = cm.find("add_host_shader(heat_haze.comp heat_haze_comp)\n"), cm.find("heat_haze_comp.h APPEND")
    if not (0 <= a < b) or cm.find("function(add_host_shader") > a:
        raise SystemExit("text check: the CMake dependency line is not after r97's shader line")


# An interim copy of this script was applied to <tree> at 2026-11-15 23:14:09 while the review
# was still running: it differs from this one only in two lines of engine/tests/test_heat_haze.cpp
# (a search string the unit test would not find, so heat-haze-test would fail there). Those two
# lines are read as this script's own (check says so; apply corrects them in place, without touching
# the backups of the originals; revert removes the block as usual).
INTERIM_UT_LINE = '        assert(std::string_view(Verdict(hidden)).find("would drop 90% or more") !=\n'
FIXED_UT_LINE = ('        assert(std::string_view(Verdict(hidden)).find("counted only, would drop) 90% or more")'
                 ' !=\n')


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R97B_ROOT)" % ROOT)
    if sha(OLD_SHADER) != OLD_SHADER_SHA:
        raise SystemExit("the script's copy of r97's shader is damaged")
    plan, states = [], []
    interim = None  # (eol, corrected text) of test_heat_haze.cpp when it holds the interim lines
    for path in (HH, VH, VCPP, UT, PT, CM, RM):
        raw, eol, cur = load(path)
        if cur is None:
            raise SystemExit("%s is missing (is r97 applied?)" % path)
        if path == UT and INTERIM_UT_LINE in cur:
            if cur.count(INTERIM_UT_LINE) != 2 or FIXED_UT_LINE in cur:
                raise SystemExit("REFUSED %s: the interim test lines are there in an unknown way" % UT)
            cur = cur.replace(INTERIM_UT_LINE, FIXED_UT_LINE)
            interim = (eol, cur)
        eds = readme_edits(cur) if path == RM else EDITS[path]
        st = state_of(cur, eds, path)
        plan.append((path, eds, raw, eol, cur))
        states.append((path, st))
    # the shader, replaced whole
    raw, eol_sh, cur = load(SH)
    if cur is None:
        raise SystemExit("%s is missing (is r97 applied?)" % SH)
    if cur == NEW_SHADER:
        states.append((SH, "applied"))
    elif cur == OLD_SHADER:
        states.append((SH, "clean"))
    else:
        raise SystemExit("REFUSED %s: neither r97's text nor r97b's (sha256 %s)" % (SH, sha(cur)[:16]))
    sh_raw = raw
    # the new layout header
    lraw, _, lcur = load(LY)
    if lcur is None:
        states.append((LY, "clean"))
    elif lcur == NEW_LAYOUT:
        states.append((LY, "applied"))
    else:
        raise SystemExit("REFUSED %s exists with other content" % LY)
    kinds = {s for _, s in states}
    if len(kinds) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % p for p in states))
    state = kinds.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur in plan:
            res = apply_edits(cur, eds)
            if state_of(res, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = res
        out[SH] = NEW_SHADER
        out[LY] = NEW_LAYOUT
        return out

    if cmd == "check":
        if state == "applied":
            t = {p[0]: p[4] for p in plan}
            t[SH], t[LY] = NEW_SHADER, NEW_LAYOUT
            text_checks(t)
            print("applied (text checks pass)" + (
                "; but %s holds the 2 interim test lines (23:14 copy): apply corrects them" % UT
                if interim else ""))
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, 1 shader replaced, 1 new file; "
                  "text checks on the result pass)" % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            if interim:  # the two interim lines only; the backups of the originals stay as they are
                full = os.path.join(ROOT, UT)
                tmp = full + ".r97btmp"
                open(tmp, "wb").write(interim[1].replace("\n", interim[0]).encode("utf-8"))
                os.replace(tmp, full)
                print("already applied; corrected the 2 interim test lines in %s" % UT); return
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        open(os.path.join(BACKUP, SH.replace("/", "__")), "wb").write(sh_raw)
        writes = [(p[0], texts[p[0]].replace("\n", p[3]).encode("utf-8")) for p in plan]
        writes.append((SH, NEW_SHADER.replace("\n", eol_sh).encode("utf-8")))
        writes.append((LY, NEW_LAYOUT.replace("\n", eol_sh).encode("utf-8")))  # as its neighbour
        for path, data in writes:
            full = os.path.join(ROOT, path)
            tmp = full + ".r97btmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = []
    for path, eds, raw, eol, cur in plan:
        res = revert_edits(cur, eds)
        if state_of(res, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out.append((path, res.replace("\n", eol).encode("utf-8")))
    out.append((SH, OLD_SHADER.replace("\n", eol_sh).encode("utf-8")))
    for path, data in out:
        full = os.path.join(ROOT, path)
        tmp = full + ".r97btmp"
        open(tmp, "wb").write(data)
        os.replace(tmp, full)
    os.remove(os.path.join(ROOT, LY))
    print("reverted")


main()
