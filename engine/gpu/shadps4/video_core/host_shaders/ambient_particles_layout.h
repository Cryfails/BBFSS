// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r98_ambient-particles): the numbers the ambient motes' shaders (ambient_particles.vert,
// ambient_particles.frag) share with the engine (renderer_vulkan/ambient_particles.h, which ties
// them with static_asserts and tests/test_ambient_particles.cpp). Preprocessor only, so GLSL and
// C++ both include it.
#ifndef AMBIENT_PARTICLES_LAYOUT_H
#define AMBIENT_PARTICLES_LAYOUT_H

// The lattice: AP_NX x AP_NY x AP_NZ cells of AP_CELL m around the camera, one instance a cell (at
// most one mote), y up. A cell's hash takes its index modulo AP_PERIOD on each axis, so the field
// repeats every AP_PERIOD * AP_CELL = 768 m and the drift can wrap there without a jump.
#define AP_CELL 0.75
#define AP_NX 24
#define AP_NY 18
#define AP_NZ 24
#define AP_PERIOD 1024

// Fades (m): nearer than AP_NEAR0 view depth nothing, full from AP_NEAR1; full up to AP_FAR0 from
// the camera and nothing from AP_FAR1, vertical distances counted AP_FAR_Y times.
#define AP_NEAR0 0.45
#define AP_NEAR1 1.2
#define AP_FAR0 5.5
#define AP_FAR1 7.5
#define AP_FAR_Y 1.6
// A mote fades out over this distance (m) in front of the surface behind it (soft points).
#define AP_SOFT 0.25

// Motes (dust and ash, the one look) and embers: radius (m), life (s, from MIN to MAX by the
// cell's hash), vertical speed (m/s, + up) over the life, wobble amplitude (m).
#define AP_MOTE_RADIUS 0.010
#define AP_MOTE_LIFE_MIN 9.0
#define AP_MOTE_LIFE_MAX 15.0
#define AP_MOTE_RISE -0.05
#define AP_MOTE_WOBBLE 0.10
#define AP_EMBER_RADIUS 0.014
#define AP_EMBER_LIFE_MIN 4.0
#define AP_EMBER_LIFE_MAX 7.0
#define AP_EMBER_RISE 0.30
#define AP_EMBER_WOBBLE 0.22
// The wobble's vertical part is this share of the amplitude.
#define AP_WOBBLE_Y 0.6

// Drawn radius (output pixels): at least AP_MIN_PX (a smaller mote is drawn at this size with its
// light scaled by the area ratio), at most AP_MAX_PX_4K * output height / 2160 but not under
// AP_MAX_PX_FLOOR, both limits times the size scale (Push::look.z: 1, or BB_PARTICLES_SHOW's).
#define AP_MIN_PX 0.85
#define AP_MAX_PX_4K 8.0
#define AP_MAX_PX_FLOOR 3.0

// The light at a mote: the frame before the UI around it, 5 pixels (the centre counted twice,
// over 6); a mote's colour is at most
// AP_MAX_COLOUR a channel (display-encoded), its peak coverage AP_MOTE_PEAK / AP_EMBER_PEAK.
#define AP_MAX_COLOUR 0.6
#define AP_MOTE_PEAK 0.65
#define AP_EMBER_PEAK 0.85

// The push block (bytes) and its flag bit (Push::frame[3]): the frame before the UI is read
// through an sRGB view (its texels arrive decoded; the shader encodes them again).
#define AP_PUSH_BYTES 128
#define AP_FLAG_SCENE_SRGB 1
// bbport (r98b_particles-reduced-scene), Push::frame[3]: the frame before the UI has the output
// size and no jitter (the game's finished frame after an upscale before its post): its light is
// read at output pixels.
#define AP_FLAG_SCENE_OUTPUT 2

// bbport (r98c_particles-visible): the frame's lamps (binding 2 of ambient_particles.vert, the
// Lamps block; renderer_vulkan/ambient_particles_lamps.h fills it). At most AP_MAX_LAMPS lamps
// light the dust, the first of them at most AP_MAX_FLAMES flames that throw embers: AP_FLAME_SLOTS
// instances a flame, after the lattice's AP_LATTICE.
#define AP_LATTICE (AP_NX * AP_NY * AP_NZ)
#define AP_MAX_LAMPS 16
#define AP_MAX_FLAMES 8
#define AP_FLAME_SLOTS 16
#define AP_LAMP_BLOCK_BYTES 928 // bbport (r98e_moths-at-lamps): was 672, plus 16 vec4 (the moths)
// Dust lit by a lamp: the lamp pass's colour x the game's curve (1 - d / reach)^2 x a halo
// 1 / (1 + (d / AP_LAMP_HALO)^2) (d in m) x forward scattering (Henyey-Greenstein with AP_PHASE_G,
// 1 seen from the side, at most AP_PHASE_MAX) x AP_LAMP_EXPOSURE x the lamp gain; its largest
// channel L is taken to 1 - exp(-L) with the hue kept (all channels times (1 - exp(-L)) / L), then
// display-encoded (power 1 / 2.2); it twinkles slowly down to 1 - AP_TWINKLE.
// The light of the picture behind a dust mote then counts mix(1, AP_BACK_WITH_LAMPS, its lamp
// light's largest channel / AP_BACK_LAMP_FULL, at most 1) times (no lamp light: as before), and a
// lit mote's colour is scaled down, hue kept, until no channel is above AP_MAX_LIT.
#define AP_LAMP_HALO 1.5
#define AP_PHASE_G 0.45
#define AP_PHASE_MAX 3.0
#define AP_LAMP_EXPOSURE 1.5
#define AP_TWINKLE 0.35
#define AP_BACK_WITH_LAMPS 0.5
#define AP_BACK_LAMP_FULL 0.5
#define AP_MAX_LIT 0.85
// Embers a burning flame throws (a warm lamp with one channel at least AP_SPARK_BRIGHT and blue at
// most AP_SPARK_BLUE of red): a slot burns lives of AP_SPARK_LIFE_MIN..MAX s, each with the chance
// AP_SPARK_BIRTH x density x the flame's share (none at a reach of AP_SPARK_REACH0 m or less, all
// from AP_SPARK_REACH1 m). An ember starts on a disc of AP_SPARK_SPREAD x reach (AP_SPARK_SPREAD_MIN
// to MAX m) around the lamp, rises at AP_SPARK_RISE_MIN..MAX m/s (its height: rise x seconds x
// (1 - 0.35 x age)), swirls up to AP_SPARK_SWIRL m, goes with the drift (the wind with BB_WIND=1),
// cools from orange to red (glow AP_SPARK_GLOW), radius AP_SPARK_RADIUS m; seen up to AP_SPARK_FAR1
// m from the camera (in full to AP_SPARK_FAR0). With the lamps on, the lattice's own embers are
// only near such flames: in full within AP_EMBER_NEAR0 m of one, none beyond AP_EMBER_NEAR1.
#define AP_SPARK_BIRTH 0.5
#define AP_SPARK_LIFE_MIN 1.2
#define AP_SPARK_LIFE_MAX 2.6
#define AP_SPARK_BRIGHT 1.2
#define AP_SPARK_BLUE 0.45
#define AP_SPARK_REACH0 4.0
#define AP_SPARK_REACH1 8.0
#define AP_SPARK_SPREAD 0.02
#define AP_SPARK_SPREAD_MIN 0.05
#define AP_SPARK_SPREAD_MAX 0.25
#define AP_SPARK_RISE_MIN 0.45
#define AP_SPARK_RISE_MAX 0.95
#define AP_SPARK_SWIRL 0.12
#define AP_SPARK_GLOW 0.95
#define AP_SPARK_RADIUS 0.009
#define AP_SPARK_FAR0 10.0
#define AP_SPARK_FAR1 16.0
#define AP_EMBER_NEAR0 1.5
#define AP_EMBER_NEAR1 4.0

// bbport (r98d_particles-still-indoors): with the camera sheltered (the wind shelter field, shade
// lamp_wind.w above 0) a dust mote's picture-behind light counts by smoothstep(AP_DARK_LO,
// AP_DARK_HI, the luma of the light behind it, display-encoded) mixed in by the shade: nothing in a
// picture darker than AP_DARK_LO, in full from AP_DARK_HI. A lamp's own light on the mote is not
// faded.
#define AP_DARK_LO 0.12
#define AP_DARK_HI 0.40

// bbport (r98e_moths-at-lamps): moths round the lit lamps (renderer_vulkan/ambient_particles_moths.h
// decides which lamps, ambient_particles.vert flies them: the Lamps block's moth_info, one vec4 a lamp
// slot: x moths (0 to AP_MOTH_SLOTS), y seed, z loop scale, w calm). AP_MOTH_SLOTS instances a lamp slot
// of the block, after the flames' ember instances (AP_MOTH_INSTANCES in all); at most AP_MOTH_LAMPS lamps
// carry moths at once. A moth is a point of radius AP_MOTH_RADIUS m (the lamp's light on it, flickering
// with the wing beat), seen in full up to AP_MOTH_FAR0 m from the camera and not from AP_MOTH_FAR1 m,
// and not nearer than AP_NEAR0 as every mote. Its flight: a loop of AP_MOTH_ORBIT_MIN to
// AP_MOTH_ORBIT_MAX m (times the lamp's scale) round the lamp, turning AP_MOTH_TURN_MIN to
// AP_MOTH_TURN_MAX rad/s either way, with surges of AP_MOTH_SURGE rad and a jitter of AP_MOTH_JITTER m;
// in shelter (w = 1) all of it AP_MOTH_CALM of the way slower (time x (1 - AP_MOTH_CALM)); it leans
// downwind by AP_MOTH_LEAN s x the horizontal drift (lamp_wind.xyz), at most AP_MOTH_LEAN_MAX m.
#define AP_MOTH_SLOTS 6
#define AP_MOTH_LAMPS 6
#define AP_MOTH_INSTANCES (AP_MAX_LAMPS * AP_MOTH_SLOTS)
#define AP_MOTH_RADIUS 0.012
#define AP_MOTH_FAR0 8.0
#define AP_MOTH_FAR1 13.0
#define AP_MOTH_ORBIT_MIN 0.20
#define AP_MOTH_ORBIT_MAX 0.55
#define AP_MOTH_TURN_MIN 1.2
#define AP_MOTH_TURN_MAX 2.4
#define AP_MOTH_SURGE 0.6
#define AP_MOTH_JITTER 0.06
#define AP_MOTH_CALM 0.45
#define AP_MOTH_LEAN 0.08
#define AP_MOTH_LEAN_MAX 0.35

#endif
