// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r98_ambient-particles): ambient motes (dust and ash, a few embers), drawn after the
// upscale into the output-size frame before the UI (renderer_vulkan/vk_ambient_particles.cpp).
// One instance a lattice cell around the camera (ambient_particles_layout.h), six vertices a
// quad; everything comes from a hash of the cell, the time and the drift in the push block, so
// there is no buffer and no simulation. A cell without a mote, or a mote outside the view, behind
// a surface or faded out, sends all six vertices to one point outside the view (no area, nothing
// drawn). The mote's light is the frame before the UI around it (5 pixels of it, the centre
// counted twice; at the render size, or at the output size after an upscale before the game's
// post, AP_FLAG_SCENE_OUTPUT): it
// carries the sun or moon light on the surfaces behind it, the sun fog and lamp fog in front of
// them and the lamps' light, so a mote shows where there is light and fades in the dark. That
// is the light behind the mote, not the light at its own place.
// bbport (r98c_particles-visible): with lamp_info.z above 0 (BB_PARTICLES_LAMPS) a dust mote is
// also lit by the frame's lamps (the Lamps block, binding 2: scattered toward the camera), the
// lattice's embers stay near flames, and the instances after the lattice's are embers the flames
// throw (ambient_particles_layout.h has the numbers).
#version 450
#extension GL_GOOGLE_include_directive : require
#extension GL_EXT_samplerless_texture_functions : require

#include "ambient_particles_layout.h"

layout(binding = 0) uniform texture2D depth_tex; // scene depth, 0 near .. 1 far, render size
layout(binding = 1) uniform texture2D scene_tex; // the frame before the UI: render size, or
                                                 // output size (AP_FLAG_SCENE_OUTPUT)
// bbport (r98c_particles-visible): the frame's lamps (renderer_vulkan/ambient_particles_lamps.h
// LampBlock, the same order).
layout(std140, binding = 2) uniform Lamps {
    vec4 lamp_info;                 // x: lamps, y: flames (the first of them), z: lamp gain (0:
                                    // off), w: an ember slot's chance to burn a life
    vec4 lamp_wind;                 // xyz: the embers' drift (m/s), w: the indoor shade 0..1
                                    // (r98d_particles-still-indoors: 0 in the open)
    vec4 lamp_place[AP_MAX_LAMPS];  // world xyz (m), reach (m)
    vec4 lamp_colour[AP_MAX_LAMPS]; // rgb as the lamp pass drew it (at most 4), w: weight 0..1
    vec4 flame_seed[AP_MAX_FLAMES]; // x: seed (24 bits over 2^24), y: share of its slots burning
};

layout(push_constant) uniform Push {
    vec4 view_row[3]; // world to view, rows (view z forward)
    vec4 proj;        // x scale, y scale (ndc +y down the screen), z scale, z offset
    vec4 camera;      // xyz: the camera in the world (m); w: time (s)
    vec4 drift;       // xyz: the lattice's drift (m); w: the chance a cell holds a mote
    vec4 look;        // x: light gain, y: ember share, z: size scale, w: colour floor
    uvec4 frame;      // x: output w | h << 16, y: render w | h << 16, z: jitter (snorm16 x, y),
                      // w: flags (AP_FLAG_SCENE_SRGB, AP_FLAG_SCENE_OUTPUT)
};

layout(location = 0) out vec2 v_local;       // the corner in drawn radii
layout(location = 1) out vec2 v_render;      // the corner in the depth image (render pixels)
layout(location = 2) flat out vec3 v_colour; // premultiplied colour at the centre
layout(location = 3) flat out float v_z;     // the mote's view depth (m)

const vec2 CORNERS[6] = vec2[6](vec2(-1.0, -1.0), vec2(1.0, -1.0), vec2(1.0, 1.0),
                                vec2(-1.0, -1.0), vec2(1.0, 1.0), vec2(-1.0, 1.0));

// PCG3D (two rounds).
uvec3 ap_hash(uvec3 v) {
    v = v * 1664525u + 1013904223u;
    v.x += v.y * v.z;
    v.y += v.z * v.x;
    v.z += v.x * v.y;
    v ^= v >> 16u;
    v.x += v.y * v.z;
    v.y += v.z * v.x;
    v.z += v.x * v.y;
    return v;
}

// Each component's top 24 bits as a float in [0, 1).
vec3 ap_unit(uvec3 h) {
    return vec3(h >> 8u) * (1.0 / 16777216.0);
}

// View depth (m) of a depth value; the sky (1) is far away.
float scene_z(float depth) {
    if (depth >= 1.0) {
        return 1e9;
    }
    return proj.w / min(depth - proj.z, -1e-8);
}

vec3 scene_at(ivec2 p, ivec2 last) {
    return texelFetch(scene_tex, clamp(p, ivec2(0), last), 0).rgb;
}

// bbport (r98c_particles-visible): the lamps' light scattered by dust at `world` toward the
// camera (linear, in the lamp pass's units; ambient_particles_layout.h).
vec3 lamp_light(vec3 world) {
    vec3 sum = vec3(0.0);
    const int lamps = min(int(lamp_info.x), AP_MAX_LAMPS);
    const vec3 eye = normalize(camera.xyz - world);
    const float g = AP_PHASE_G;
    const float side = pow(1.0 + g * g, 1.5);
    for (int i = 0; i < lamps; ++i) {
        const vec3 d = world - lamp_place[i].xyz;
        const float dist = length(d);
        const float reach = lamp_place[i].w;
        if (!(dist < reach)) {
            continue;
        }
        const float x = 1.0 - dist / reach;
        const float halo = 1.0 / (1.0 + dist * dist * (1.0 / (AP_LAMP_HALO * AP_LAMP_HALO)));
        // The light goes from the lamp through the mote (d); forward is toward the camera.
        const float c = dot(d, eye) / max(dist, 1e-3);
        const float phase = min(side / pow(max(1.0 + g * g - 2.0 * g * c, 1e-4), 1.5), AP_PHASE_MAX);
        sum += lamp_colour[i].rgb * (lamp_colour[i].w * x * x * halo * phase);
    }
    return sum;
}

// bbport (r98c_particles-visible): 0..1, how near `p` is to a flame that throws embers (in full
// within AP_EMBER_NEAR0 m, none beyond AP_EMBER_NEAR1 m), times that flame's share.
float flame_near(vec3 p) {
    float near = 0.0;
    const int flames = min(int(lamp_info.y), AP_MAX_FLAMES);
    for (int f = 0; f < flames; ++f) {
        near = max(near, (1.0 - smoothstep(AP_EMBER_NEAR0, AP_EMBER_NEAR1,
                                            distance(p, lamp_place[f].xyz))) * flame_seed[f].y);
    }
    return near;
}

// bbport (r98c_particles-visible): slot `slot` of flame `f` (ambient_particles_layout.h): false
// while it burns no life (or there is no such flame).
bool flame_ember(int f, int slot, out vec3 world, out float life_fade, out float heat,
                 out float seed) {
    world = vec3(0.0);
    life_fade = 0.0;
    heat = 0.0;
    seed = 0.0;
    if (f >= min(int(lamp_info.y), AP_MAX_FLAMES)) {
        return false;
    }
    const vec4 flame = lamp_place[f];
    const uint key = uint(flame_seed[f].x * 16777216.0);
    const vec3 u = ap_unit(ap_hash(uvec3(key, uint(slot), 0x5bd1e995u)));
    const float life = mix(AP_SPARK_LIFE_MIN, AP_SPARK_LIFE_MAX, u.z);
    const float cycle = camera.w / life + u.x;
    const float lives = floor(cycle);
    const float age = cycle - lives;
    const uvec3 h = ap_hash(uvec3(key, uint(slot), uint(lives) * 747796405u + 1u));
    const vec3 v = ap_unit(h);
    if (v.z >= lamp_info.w * flame_seed[f].y) {
        return false; // this life burns nothing
    }
    const vec3 w = ap_unit(ap_hash(h));
    const float secs = age * life;
    const float spread = clamp(AP_SPARK_SPREAD * flame.w, AP_SPARK_SPREAD_MIN, AP_SPARK_SPREAD_MAX);
    const float angle = 6.2831853 * v.x;
    const vec3 start = flame.xyz + vec3(cos(angle), 0.0, sin(angle)) * (spread * sqrt(v.y));
    const float rise = mix(AP_SPARK_RISE_MIN, AP_SPARK_RISE_MAX, w.x);
    const float t = camera.w;
    const vec3 swirl = (AP_SPARK_SWIRL * age) *
                       vec3(sin(t * (2.1 + w.y) + 6.2831853 * w.z),
                            0.4 * sin(t * 3.3 + 6.2831853 * w.y),
                            cos(t * (1.7 + w.z) + 6.2831853 * w.x));
    world = start + vec3(0.0, rise * secs * (1.0 - 0.35 * age), 0.0) + lamp_wind.xyz * secs + swirl;
    life_fade = smoothstep(0.0, 0.06, age) * (1.0 - smoothstep(0.5, 1.0, age));
    heat = 1.0 - 0.7 * age;
    seed = w.y;
    return true;
}

void main() {
    const vec2 corner = CORNERS[gl_VertexIndex % 6];
    gl_Position = vec4(-4.0, -4.0, 0.0, 1.0);
    v_local = vec2(0.0);
    v_render = vec2(0.0);
    v_colour = vec3(0.0);
    v_z = 0.0;

    const float t = camera.w;
    // bbport (r98c_particles-visible): the lamps' light and the flames' embers while lamp_info.z
    // is above 0 (BB_PARTICLES_LAMPS); else the look of r98 and r98b.
    const bool lamps_on = lamp_info.z > 0.0;
    vec3 world;
    float life_fade;
    float heat = 1.0;
    float seed;
    bool ember;
    bool thrown = false; // an ember a flame threw (the instances after the lattice's)
    vec3 place = vec3(0.5);
    vec3 phase = vec3(0.0);
    if (gl_InstanceIndex >= AP_LATTICE) {
        const int slot = gl_InstanceIndex - AP_LATTICE;
        if (!flame_ember(slot / AP_FLAME_SLOTS, slot % AP_FLAME_SLOTS, world, life_fade, heat,
                         seed)) {
            return;
        }
        ember = true;
        thrown = true;
    } else {
        // The cell: the lattice is carried by the drift, its box centred on the camera.
        const int index = gl_InstanceIndex;
        const ivec3 local = ivec3(index % AP_NX, (index / AP_NX) % AP_NY, index / (AP_NX * AP_NY));
        const vec3 lattice_camera = camera.xyz - drift.xyz;
        const ivec3 cell = ivec3(floor(lattice_camera / AP_CELL)) -
                           ivec3(AP_NX / 2, AP_NY / 2, AP_NZ / 2) + local;
        const uvec3 key = uvec3(cell) & uvec3(AP_PERIOD - 1);
        const vec3 u = ap_unit(ap_hash(key));
        if (u.x >= drift.w) {
            return; // no mote in this cell
        }
        // With the lamps on, the cell's mote is an ember only near a flame that throws embers.
        const float share =
            lamps_on ? look.y * flame_near((vec3(cell) + 0.5) * AP_CELL + drift.xyz) : look.y;
        ember = u.y < share;
        const float life = ember ? mix(AP_EMBER_LIFE_MIN, AP_EMBER_LIFE_MAX, u.z)
                                 : mix(AP_MOTE_LIFE_MIN, AP_MOTE_LIFE_MAX, u.z);
        // Each life of the cell's mote has its own place in the cell (a new hash at each life).
        const float cycle = camera.w / life + fract(u.x * 13.7 + u.z * 5.3);
        const float lives = floor(cycle);
        const float age = cycle - lives;
        const uvec3 h = ap_hash(key ^ uvec3(uint(lives) * 747796405u));
        place = ap_unit(h);
        phase = ap_unit(ap_hash(h)) * 6.2831853;
        const float rise = ember ? AP_EMBER_RISE : AP_MOTE_RISE;
        const float wobble = ember ? AP_EMBER_WOBBLE : AP_MOTE_WOBBLE;
        const vec3 sway = wobble * vec3(sin(t * 0.83 + phase.x), AP_WOBBLE_Y * sin(t * 0.61 + phase.y),
                                        cos(t * 0.71 + phase.z));
        world = (vec3(cell) + place) * AP_CELL + drift.xyz +
                vec3(0.0, rise * (age - 0.5) * life, 0.0) + sway;
        life_fade = smoothstep(0.0, 0.2, age) * (1.0 - smoothstep(0.75, 1.0, age));
        seed = place.x;
    }

    const vec4 at = vec4(world, 1.0);
    const vec3 view = vec3(dot(view_row[0], at), dot(view_row[1], at), dot(view_row[2], at));
    const float z = view.z;
    if (z < AP_NEAR0) {
        return;
    }
    const vec3 rel = world - camera.xyz;
    // An ember a flame threw is seen further (AP_SPARK_FAR0/1), heights counted as they are.
    const float reach = thrown ? length(rel) : length(vec3(rel.x, rel.y * AP_FAR_Y, rel.z));
    const float far0 = thrown ? AP_SPARK_FAR0 : AP_FAR0;
    const float far1 = thrown ? AP_SPARK_FAR1 : AP_FAR1;
    const float fade = life_fade * smoothstep(AP_NEAR0, AP_NEAR1, z) *
                       (1.0 - smoothstep(far0, far1, reach));
    if (fade <= 0.0) {
        return;
    }
    const vec2 ndc = view.xy * proj.xy / z;
    if (abs(ndc.x) > 1.02 || abs(ndc.y) > 1.02) {
        return;
    }
    const vec2 out_size = vec2(frame.x & 0xffffu, frame.x >> 16u);
    const vec2 render = vec2(frame.y & 0xffffu, frame.y >> 16u);
    const vec2 jitter = unpackSnorm2x16(frame.z);
    const ivec2 last = ivec2(render) - 1;
    const ivec2 centre = clamp(ivec2((ndc * 0.5 + 0.5) * render + jitter), ivec2(0), last);
    if (scene_z(texelFetch(depth_tex, centre, 0).r) < z - AP_SOFT) {
        return; // behind a surface (the pixels' own test softens the edges)
    }

    // Size: a mote smaller than AP_MIN_PX is drawn at that size with its light scaled down by the
    // area, so far motes get fainter instead of flickering.
    const float radius_px =
        (thrown ? AP_SPARK_RADIUS : ember ? AP_EMBER_RADIUS : AP_MOTE_RADIUS) * look.z *
        abs(proj.y) * 0.5 * out_size.y / z;
    const float most = max(AP_MAX_PX_FLOOR, AP_MAX_PX_4K * out_size.y / 2160.0) * look.z;
    const float drawn = clamp(radius_px, AP_MIN_PX * look.z, most);
    const float energy = min(radius_px * radius_px / (drawn * drawn), 1.0);

    // Light: the frame before the UI around the mote: at the render size with the depth's jitter,
    // or (AP_FLAG_SCENE_OUTPUT: the game's finished frame after an upscale before its post) at the
    // output size without jitter. The taps lie 2 drawn radii away (at least 3 of its pixels).
    const bool scene_out = (frame.w & uint(AP_FLAG_SCENE_OUTPUT)) != 0u;
    const vec2 scene_size = scene_out ? out_size : render;
    const ivec2 scene_last = ivec2(scene_size) - 1;
    const ivec2 spot =
        scene_out ? clamp(ivec2((ndc * 0.5 + 0.5) * out_size), ivec2(0), scene_last) : centre;
    const int tap = int(max(3.0, 2.0 * drawn * scene_size.y / out_size.y));
    vec3 light = 2.0 * scene_at(spot, scene_last) + scene_at(spot + ivec2(tap, 0), scene_last) +
                 scene_at(spot - ivec2(tap, 0), scene_last) +
                 scene_at(spot + ivec2(0, tap), scene_last) +
                 scene_at(spot - ivec2(0, tap), scene_last);
    light *= 1.0 / 6.0;
    if ((frame.w & uint(AP_FLAG_SCENE_SRGB)) != 0u) {
        light = pow(max(light, vec3(0.0)), vec3(1.0 / 2.2));
    }
    const float luma = dot(light, vec3(0.2126, 0.7152, 0.0722));
    const vec3 hue = mix(vec3(luma), light, 0.7);
    vec3 colour;
    float peak;
    if (thrown) {
        // bbport (r98c_particles-visible): it glows by itself, orange cooling to red as it rises,
        // and flickers.
        const float flicker = 0.7 + 0.3 * sin(t * (7.0 + 6.0 * seed) + 6.2831853 * seed);
        colour = min(vec3(1.0, 0.30 + 0.25 * heat, 0.05 + 0.08 * heat) *
                         (AP_SPARK_GLOW * heat * flicker),
                     vec3(AP_MAX_LIT));
        peak = AP_EMBER_PEAK;
    } else if (ember) {
        // An ember glows by itself, more where the light around it is warm (fire, lamps).
        const float warm = clamp((light.r - light.b) * 4.0 + 0.25, 0.25, 1.0);
        const float flicker = 0.65 + 0.35 * sin(t * (6.0 + 5.0 * place.x) + phase.y);
        colour = vec3(1.0, 0.42, 0.10) * (0.6 * warm * flicker) + 0.3 * hue;
        colour = min(colour * look.x + look.w, vec3(AP_MAX_COLOUR));
        peak = AP_EMBER_PEAK;
    } else {
        // bbport (r98c_particles-visible): the lamps' light on it, twinkling slowly (display-
        // encoded). v_colour is flat: only the provoking vertex (the first of each triangle, 0 and
        // 3 of the quad) is used, so the others skip the lamps' loop.
        vec3 lamp_lit = vec3(0.0);
        const int quad_vertex = gl_VertexIndex % 6;
        if (lamps_on && (quad_vertex == 0 || quad_vertex == 3)) {
            const float twinkle =
                1.0 - AP_TWINKLE * (0.5 + 0.5 * sin(t * (1.1 + 1.6 * place.y) + phase.x));
            const vec3 lit = lamp_light(world) * (lamp_info.z * AP_LAMP_EXPOSURE * twinkle);
            // The largest channel takes the curve, the others keep their share of it: a channel
            // by channel curve turned torch light white (slot b23's pictures).
            const float strongest = max(lit.r, max(lit.g, lit.b));
            if (strongest > 1e-6) {
                lamp_lit = pow(lit * ((1.0 - exp(-strongest)) / strongest), vec3(1.0 / 2.2)) *
                           vec3(1.0, 0.97, 0.92);
            }
        }
        // The picture behind counts less only as far as lamp light is on the mote (none: r98b's).
        const float back =
            mix(1.0, AP_BACK_WITH_LAMPS,
                clamp(max(lamp_lit.r, max(lamp_lit.g, lamp_lit.b)) / AP_BACK_LAMP_FULL, 0.0, 1.0));
        // bbport (r98d_particles-still-indoors): with the camera sheltered (lamp_wind.w above 0) the
        // picture behind the mote counts only as far as it is lit (exactly 1 in the open).
        const float dark = mix(1.0, smoothstep(AP_DARK_LO, AP_DARK_HI, luma), lamp_wind.w);
        colour = min(hue * vec3(1.0, 0.96, 0.9) * (look.x * back * dark) + look.w, vec3(AP_MAX_COLOUR));
        if (lamps_on) {
            // At most AP_MAX_LIT a channel, the hue kept (r98b's colour, at most AP_MAX_COLOUR,
            // is left as it is when no lamp light is on the mote).
            colour += lamp_lit;
            colour *= min(1.0, AP_MAX_LIT / max(max(colour.r, colour.g), max(colour.b, 1e-6)));
        }
        peak = AP_MOTE_PEAK;
    }
    v_colour = colour * (peak * fade * energy);
    v_z = z;

    const vec2 pos = ndc + corner * ((drawn + 1.0) * 2.0 / out_size);
    v_local = corner * ((drawn + 1.0) / drawn);
    v_render = (pos * 0.5 + 0.5) * render + jitter;
    gl_Position = vec4(pos, 0.0, 1.0);
}
