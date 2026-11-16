// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r98_ambient-particles): a mote's pixels (ambient_particles.vert): a soft round point,
// fading out over AP_SOFT m in front of the surface behind the pixel (the scene depth at the
// pixel's place in the render-size depth image). The colour is premultiplied; the pipeline
// screens it over the frame (colour + frame * (1 - colour)), alpha untouched.
#version 450
#extension GL_GOOGLE_include_directive : require
#extension GL_EXT_samplerless_texture_functions : require

#include "ambient_particles_layout.h"

layout(binding = 0) uniform texture2D depth_tex;

layout(push_constant) uniform Push {
    vec4 view_row[3];
    vec4 proj;
    vec4 camera;
    vec4 drift;
    vec4 look;
    uvec4 frame;
};

layout(location = 0) in vec2 v_local;
layout(location = 1) in vec2 v_render;
layout(location = 2) flat in vec3 v_colour;
layout(location = 3) flat in float v_z;

layout(location = 0) out vec4 out_colour;

float scene_z(float depth) {
    if (depth >= 1.0) {
        return 1e9;
    }
    return proj.w / min(depth - proj.z, -1e-8);
}

void main() {
    const float d2 = dot(v_local, v_local);
    const vec2 render = vec2(frame.y & 0xffffu, frame.y >> 16u);
    const ivec2 p = clamp(ivec2(v_render), ivec2(0), ivec2(render) - 1);
    const float behind = scene_z(texelFetch(depth_tex, p, 0).r) - v_z;
    const float a = exp(-3.0 * d2) * clamp(behind / AP_SOFT, 0.0, 1.0);
    out_colour = vec4(v_colour * a, 0.0);
}
