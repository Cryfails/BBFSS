// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r45_drawn-look): shared by the drawn look's passes (paint_prep.comp, paint_stats.comp,
// paint_key.comp, paint_strokes.comp and paint_lock.comp, recorded by
// renderer_vulkan/vk_drawn_look.cpp). The look lays brush strokes ("dabs") on the scene's solid
// surfaces. A dab belongs to a place in the world, not to a place on the screen: every pixel finds its dabs from its own world position with the frame's jitter
// taken out, and nothing here depends on the frame's number. So a dab stays on its wall while
// the camera moves, and the upscaler and frame generation see it as they see a texture.
//
// The words of the block are made by DrawnLookParams::Make (renderer_vulkan/drawn_look_params.h).

layout(push_constant) uniform Constants {
    vec4 inv_view[3]; // view to world, rows (3x4): CameraMotion::PassMatrices
    vec4 proj;        // x scale, y scale, z scale, z offset (as camera_motion.comp)
    vec2 size;        // the scene in pixels
    vec2 jitter;      // this frame's viewport shift in pixels (x right, y down)
    float strength;   // graphics_drawn_look_strength, 0..1
    float brush;      // graphics_drawn_look_texture, 0..1.2: the brush's marks in a stroke
    float outlines;   // graphics_drawn_look_outlines, 0..1 (ink)
    float ink_world;  // graphics_drawn_look_ink_world, 0..1 (ink)
    float characters; // graphics_drawn_look_characters, 0..1: the strength on what moves by itself
    float cell_bold;  // the cell of a bold stroke on the screen, pixels of the scene
    float cell_fine;  // the cell of a fine stroke
    uint flags;       // FLAG_*; bits 8..10: the test view (VIEW_*)
};

const uint FLAG_NORMALS = 1u; // normal_tex holds the G-buffer's world normals
const uint FLAG_MOTION = 2u;  // motion_tex holds this frame's object motion
const uint VIEW_STROKES = 1u; // every stroke in a flat colour of its own, sizes as the look mixes them
const uint VIEW_FINE = 2u;    // the same, every stroke at the fine size
const uint VIEW_BOLD = 4u;    // the same, every stroke at the bold size

const float PI = 3.14159265358979;
const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722); // Rec.709
// Brightness below this share of the frame's key counts as black: differences down there do
// not show once the game has exposed the picture, and are not taken for detail.
const float BLACK_SHARE = 0.03;
// The frame's key (paint_key.comp): how bright the scene's surfaces are, as one number. It is
// the mean tone of the surfaces (toneOf, over blocks of the picture), cubed, times this. A plain
// mean of the picture would follow the sky and the lamps: a few of them outweigh a street of
// dark stone, and what counts as black would change with where the camera looks. The picture
// the look's numbers were set on (a night street with fog and a torch) had a plain mean this
// many times its mean tone cubed: with this factor the numbers mean there what they meant.
const float KEY_GAIN = 2.5;

// A dab in cells of its octave: one dab a cell, its centre in the cell's middle half, 1.2 cells
// from the middle to an end, a flat brush 0.35 to 0.45 as wide as long, its sides feathered over
// the outer FEATHER of the width, turned up to ANGLE_JITTER away from its plane's direction.
const float DAB_HALF_LENGTH = 1.2;
const float DAB_FEATHER = 0.25;
// The square of the farthest a dab reaches from its centre: half its length and half its
// greatest width (0.45 of the length), at right angles.
const float DAB_REACH2 = DAB_HALF_LENGTH * DAB_HALF_LENGTH * (1.0 + 0.45 * 0.45);
const float ANGLE_JITTER = 0.349; // 20 degrees
// On floors the strokes follow a slow field of directions: one turn of it is this many metres.
const float FLOW_METRES = 3.0;
// A second plane joins in where the surface leans this near to it (the ratio of the normal's
// second largest part to its largest); at 1 the two planes share the pixel half and half. A hard
// choice of one plane flickers where normal maps and the jitter move the normal across the line.
const float PLANE_BAND = 0.7;
// A plane seen at a flat angle (a floor far away) shows its strokes squashed: its cells grow by
// 1 / the square root of how squarely it is seen, so a stroke gets longer on the screen as it
// gets thinner, and no thinner than this would make it.
const float LEAN_MIN = 0.04;

float viewZ(float depth) {
    return proj.w / min(depth - proj.z, -1e-8);
}

// The luminance that counts as black in a frame with this key (the last level of the copy:
// paint_key.comp). The scene is linear and has not had the game's exposure yet: no fixed number
// would do.
float blackLevel(float key) {
    return BLACK_SHARE * key + 1e-9;
}

// A scene colour as the look's means take it: one that is no number, or below 0, would spread
// through every mean it is part of, so it is black.
vec3 soundColour(vec3 rgb) {
    return clamp(mix(rgb, vec3(0.0), isnan(rgb)), 0.0, 60000.0);
}

// A texel of the object motion image (rg pixels, b 1 where a draw with vectors of its own wrote
// it, a the depth it wrote at) says the pixel at `depth` moves by itself: a character, or
// whatever else has a bone buffer, and nothing was drawn over it since (the test
// camera_motion.comp makes).
bool ownMotion(vec4 motion, float depth) {
    return motion.b > 0.99 && abs(motion.a - depth) < max(2e-7, (proj.z - depth) * 0.01);
}

// The view position seen at a pixel (its centre: pixel + 0.5) at view depth z. The scene was
// drawn through a viewport shifted by the jitter: taken out here (camera_motion.comp).
vec3 viewPos(vec2 pixel, float z) {
    const vec2 ndc = (pixel - jitter) / size * 2.0 - 1.0;
    return vec3(ndc.x * z / proj.x, ndc.y * z / proj.y, z);
}

// Where a view position lies on the screen, in pixels of this frame (jitter put back).
vec2 viewToPixel(vec3 v) {
    const vec2 ndc = vec2(v.x * proj.x, v.y * proj.y) / max(v.z, 1e-4);
    return (ndc * 0.5 + 0.5) * size + jitter;
}

vec3 dirToWorld(vec3 v) {
    return vec3(dot(inv_view[0].xyz, v), dot(inv_view[1].xyz, v), dot(inv_view[2].xyz, v));
}

vec3 dirToView(vec3 w) {
    return inv_view[0].xyz * w.x + inv_view[1].xyz * w.y + inv_view[2].xyz * w.z;
}

vec3 cameraPos() {
    return vec3(inv_view[0].w, inv_view[1].w, inv_view[2].w);
}

// Metres one pixel covers in the middle of the screen at this distance, on a surface that faces
// the camera.
float metresPerPixel(float distance) {
    return 2.0 * distance / (abs(proj.y) * size.y);
}

uint pcg(uint v) {
    v = v * 747796405u + 2891336453u;
    const uint w = ((v >> ((v >> 28u) + 4u)) ^ v) * 277803737u;
    return (w >> 22u) ^ w;
}

uint cellHash(ivec2 cell, uint salt) {
    return pcg(uint(cell.x) + pcg(uint(cell.y) + pcg(salt)));
}

// 0..1 from a hash.
float unit(uint h) {
    return float(h >> 8u) * (1.0 / 16777216.0);
}

// What the look measures brightness in: the cube root of the luminance. Even steps of it are
// about even steps to the eye, and it needs no floor at black as a logarithm does.
float toneOf(vec3 rgb) {
    return pow(max(dot(rgb, LUMA), 0.0), 1.0 / 3.0);
}

// Value noise, 0..1, one cell a unit.
float vnoise(vec2 p) {
    const vec2 f = floor(p);
    const ivec2 c = ivec2(f);
    vec2 t = p - f;
    t = t * t * (3.0 - 2.0 * t);
    const float a = unit(cellHash(c, 977u));
    const float b = unit(cellHash(c + ivec2(1, 0), 977u));
    const float d = unit(cellHash(c + ivec2(0, 1), 977u));
    const float e = unit(cellHash(c + ivec2(1, 1), 977u));
    return mix(mix(a, b, t.x), mix(d, e, t.x), t.y);
}

// The two world axes a plane's strokes are laid out along; plane 0 faces world x, 1 world y
// (floors and ceilings: the world is y-up), 2 world z. On walls the second axis is world up.
vec2 planeAxes(vec3 p, int plane) {
    return plane == 0 ? p.zy : plane == 1 ? p.xz : p.xy;
}

// The planes a normal n asks for: `first` always, `second` with the share `second_share` (0
// away from the band, up to 0.5).
void strokePlanes(vec3 n, out int first, out int second, out float second_share) {
    const vec3 m = abs(n);
    first = m.x >= m.y ? (m.x >= m.z ? 0 : 2) : (m.y >= m.z ? 1 : 2);
    const vec3 rest = vec3(first == 0 ? -1.0 : m.x, first == 1 ? -1.0 : m.y,
                           first == 2 ? -1.0 : m.z);
    second = rest.x >= rest.y ? (rest.x >= rest.z ? 0 : 2) : (rest.y >= rest.z ? 1 : 2);
    second_share = 0.5 * smoothstep(PLANE_BAND, 1.0, rest[second] / max(m[first], 1e-4));
}

// The share of each plane in a pixel's strokes. `n` is the G-buffer's normal where there is one:
// smooth over a round column, where the depth's normal `flat_n` goes in steps from one flat side
// to the next, but with the bumps of a normal map in it. A bump that leans 40 degrees on a flat
// floor would hand a part of the floor to a wall's plane, whose strokes run across a floor as
// stripes: a plane gets no more than the surface itself (flat_n) leans toward it, and what a
// bump may not give goes to the surface's own plane. Where n and flat_n agree nothing changes:
// a plane that n gives a share is leant toward by PLANE_BAND or more.
vec3 planeShares(vec3 n, vec3 flat_n) {
    int first, second;
    float second_share;
    strokePlanes(n, first, second, second_share);
    vec3 shares = vec3(0.0);
    shares[first] = 1.0 - second_share;
    shares[second] = second_share;
    const vec3 m = abs(flat_n);
    const int own = m.x >= m.y ? (m.x >= m.z ? 0 : 2) : (m.y >= m.z ? 1 : 2);
    shares *= smoothstep(PLANE_BAND - 0.3, PLANE_BAND, m / max(m[own], 1e-4));
    shares[own] += max(1.0 - (shares.x + shares.y + shares.z), 0.0);
    return shares;
}

// The octaves a point takes its strokes from. A stroke keeps about the same size on the screen
// (cell_bold pixels a cell where `detail` is 0, cell_fine where it is 1), so its cell in the
// world grows with the distance: cells of 2^octave metres, the two octaves around the wanted
// size, `upper_share` of the larger one. Between a quarter and three quarters of the way the two
// cross over; outside that only one is there.
// `distance` is the point's distance from the camera, not its view depth: the depth of a point
// changes when the camera turns, and its strokes would cross over while nothing moved. (For it,
// a stroke near the screen's corners is larger by 1 / the cosine of the angle from the middle.)
// `lean`: how squarely the strokes' plane is seen from the camera, 0..1 (planeLean): it too
// depends on where the point lies and not on where the camera looks.
void strokeOctaves(float distance, float detail, float lean, out int octave,
                   out float upper_share) {
    const float cell_px = cell_bold * pow(cell_fine / cell_bold, detail);
    const float level =
        log2(cell_px * inversesqrt(max(lean, LEAN_MIN)) * metresPerPixel(distance));
    const float low = floor(level);
    octave = int(clamp(low, -14.0, 8.0));
    upper_share = smoothstep(0.25, 0.75, level - low);
}

// How squarely a plane's strokes are seen at a point `rel` from the camera: 1 face on, 0 edge on.
float planeLean(vec3 rel, int plane) {
    return abs(rel[plane]) / max(length(rel), 1e-6);
}

// A step along a plane's two axes (planeAxes) as a step in the world that stays on the surface
// with normal n: along the plane's own axis it follows the surface (a surface nearly edge on to
// the plane is followed as one that leans a little more to it).
vec3 planeStep(vec2 along, vec3 n, int plane) {
    vec3 move = plane == 0   ? vec3(0.0, along.y, along.x)
                : plane == 1 ? vec3(along.x, 0.0, along.y)
                             : vec3(along.x, along.y, 0.0);
    const float facing = max(abs(n[plane]), 0.2) * (n[plane] < 0.0 ? -1.0 : 1.0);
    move[plane] = -dot(n, move) / facing;
    return move;
}

struct Dab {
    float cover; // 0 outside, 1 inside, between on the feathered sides
    float s;     // along the dab, -1..1
    float t;     // across it, -1..1
    float idv;   // the dab's own random value, -0.5..0.5
    uint id;     // the dab's hash: the same for all its pixels, on every frame
    vec2 offset; // from the asked point to the dab's centre, along the plane's axes, metres
    vec2 reach;  // from the dab's centre to its end, along the plane's axes, metres
    float cell;  // the dab's cell in metres
};

// The dab on top at a world point, in one plane and one octave. `rel` is the point from the
// camera (world axes). The point's cell is found as whole cells of the camera plus the rest: a
// world coordinate of a kilometre has no bits left for a cell of a few millimetres.
// Each of the nine cells around the point has one dab; where several cover the point the one
// with the highest rank (a random number of its own) lies on top.
Dab findDab(vec3 rel, int plane, int octave) {
    const float cell_m = exp2(float(octave));
    const vec2 camera = planeAxes(cameraPos(), plane) / cell_m;
    const vec2 camera_cell = floor(camera);
    const vec2 q = (camera - camera_cell) + planeAxes(rel, plane) / cell_m;
    const vec2 q_cell = floor(q);
    const ivec2 base = ivec2(camera_cell) + ivec2(q_cell);
    const vec2 local = q - q_cell;
    const uint salt = uint(plane) + 3u * uint(octave + 64);
    Dab best;
    best.cover = 0.0;
    best.s = best.t = best.idv = 0.0;
    best.id = 0u;
    best.offset = best.reach = vec2(0.0);
    best.cell = cell_m;
    float best_rank = -1.0;
    for (int y = -1; y <= 1; ++y) {
        for (int x = -1; x <= 1; ++x) {
            const ivec2 cell = base + ivec2(x, y);
            const uint h0 = cellHash(cell, salt);
            const uint h1 = pcg(h0);
            const vec2 in_cell = 0.25 + 0.5 * vec2(unit(h0), unit(h1));
            const vec2 d = local - (vec2(x, y) + in_cell);
            // Farther from the dab's centre than its far corner: not in it, whichever way it is
            // turned (most of the nine cells end here, before their dab's angle is worked out).
            if (dot(d, d) >= DAB_REACH2) {
                continue;
            }
            const uint h2 = pcg(h1);
            const uint h3 = pcg(h2);
            // Walls: along world up. Floors: along the flow field where the dab's centre is.
            float angle = 0.5 * PI;
            if (plane == 1) {
                angle = PI * vnoise((vec2(cell) + in_cell) * (cell_m / FLOW_METRES));
            }
            angle += (unit(h2) * 2.0 - 1.0) * ANGLE_JITTER;
            const vec2 axis = vec2(cos(angle), sin(angle));
            const float s = dot(d, axis) / DAB_HALF_LENGTH;
            if (abs(s) >= 1.0) {
                continue;
            }
            const float half_width = DAB_HALF_LENGTH * mix(0.35, 0.45, unit(h3));
            const float t = dot(d, vec2(-axis.y, axis.x)) / half_width;
            // A flat brush: straight sides, ends rounded off over the last part of the length.
            const float s2 = s * s;
            const float e = t * t / (1.0 - s2 * s2);
            const float cover = 1.0 - smoothstep(1.0 - DAB_FEATHER, 1.0, e);
            const float rank = unit(h3 ^ 0x9e3779b9u);
            if (cover > 0.0 && rank > best_rank) {
                best_rank = rank;
                best.cover = cover;
                best.s = s;
                best.t = t;
                best.idv = unit(h1 ^ 0x85ebca6bu) - 0.5;
                best.id = h0;
                best.offset = -d * cell_m;
                best.reach = axis * (DAB_HALF_LENGTH * cell_m);
            }
        }
    }
    return best;
}
