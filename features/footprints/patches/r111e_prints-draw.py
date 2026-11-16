# r111e_prints-draw: FEATURE fix on top of r111_footprints, r111b, r111c and r111d (b35: the church's wet
# prints were placed (8 of them, 42 frames on glossy ground) but both read-backs "found 0 print pixels"
# and no picture showed a print; the graveyard jobs placed none because the hunter never moved).
# Still off unless BB_FOOTPRINTS is set, still costs nothing when off. Branch: visual/footprints.
#
# WHAT THE b35 LOGS AND PICTURES SAY (read before the changes)
#  - "0 print pixels" is NOT a draw that reaches nothing. The read-back line the b35 report quoted is the
#    LAST one of the run, taken after the job's twin step set BB_FOOTPRINTS_GAIN=0 (live knob): gain 0
#    draws no print, so 0 is right. The r111c line of the same run says what the pass did while the gain
#    was 1: church cp1 "466 passes, 1216 prints sent, 1.38 to 4.56 m from the camera ... read-backs 600,
#    378 of them with print pixels, the most 2193 px; gain 0.00". So footprints.comp finds 2193 print
#    pixels in a frame, 63% of the read-backs find some, and the G-buffer is changed there. Earlier runs
#    agree: b25w cp 3161, b28 cp1 1094, b30 gb1 1716 and cp1 1145 print pixels.
#  - The G-buffer path reaches the picture: b24's show picture (slot_r111-cps_down.jpg) shows the ring, the
#    yellow ground band and a cyan print at the picture's lower edge, lit by the game's lights. A
#    brightened crop of b30's gb1 back2 against its gone picture (22 s later) shows the cobbles near his
#    feet a little darker and browner; nothing like a red print. Nothing in the logs says "wrong depth
#    test, reversed Z, blend or write mask": the pass is a compute pass that reads the depth and writes
#    the albedo, gloss and specular targets before the game's lights read them (the show picture proves
#    the order).
#  - So the prints exist and are drawn into the G-buffer, and they are too faint to see: a dark red albedo
#    (0.03 to 0.085 red, 0.006 green, 0.005 blue) lit by the graveyard's blue moon (a little red in it)
#    is a bluish black, the same dark as the shadows next to it; the church stone is already at 20 to 30
#    sRGB levels, and a wet print darkens it by 0.35 in albedo. The graveyard walk of b35 never moved
#    (a test fault: see the job file; b28 and b30 walked there).
#
# WHAT CHANGES (all inside the footprints files; nothing else but one hook line and one CMake line)
#  - Test view BB_FOOTPRINTS_SHOW=1 (a live knob where the test tools' header exists, else read once):
#    every live print is drawn as a flat saturated red rectangle (0.28 x 0.11 m, a white dot at its centre)
#    on the horizontal plane of its height straight onto the scene colour, after the lighting and before
#    the upscaler, ignoring depth, lighting and the G-buffer. It proves the placement on screen whatever
#    the G-buffer path does. The pass counts the red pixels it drew (log).
#  - The post stamp, BB_FOOTPRINTS_POST (0 to 2, default 1, live): the same pass in its normal mode, depth
#    tested (world point from the depth, up-facing share, the print's height band and sole shape), after
#    the lighting: a blood print recolours the lit pixel dark red at the pixel's own luminance (so the
#    stone's texture and the game's shading stay, and the hue no longer depends on the light's colour), a
#    wet or mud print darkens the lit pixel a further 25%. It multiplies the print weight (strength x
#    shape x facing) by BB_FOOTPRINTS_GAIN and the post strength, so BB_FOOTPRINTS_GAIN=0 still draws no
#    print at all and BB_FOOTPRINTS_POST=0 gives r111d's picture (G-buffer change alone) back. The G-buffer
#    change (albedo, gloss, specular colour) is unchanged: wet prints stay glossy, blood prints glossy.
#    The post stamp's look is a model (a blood hue at the lit luminance), NOT measured: the jobs show the
#    same view with the stamp, with the flat red view, with the G-buffer change alone and with no print.
#  - Logs: a once-line (r111e) in the constructor, the first pass over the picture, and a line per 600 frames
#    (passes, prints sent, red and stamped pixels of the last pass and the most seen).
#
# Off (BB_FOOTPRINTS unset or 0): Footprints is not made, so DrawOver (new) is one null pointer test in
# Rasterizer::EffectsBeforeUpscaler and nothing else of r111e runs; no pipeline, buffer or shader is made
# (the second pipeline and its three buffers are made at the first pass over the picture, never when the
# feature is on but SHOW is off and POST is 0). On with defaults: one extra compute pass a frame over the
# smallest rectangle holding the prints' boxes (the G-buffer pass's rectangle for the same prints), only
# in frames where a print is live and on screen; its cost is about the G-buffer pass's (0.02 to 0.08 ms
# at 1080p, an estimate), 4 ALU-light taps for the up-facing share per pixel inside a print's sole
# (the early-out leaves the pixels outside every sole with one depth tap and the print loop). Memory: three
# small buffers (1.5 KB prints, 8 B counters, 8 B host copy); no image.
#
# Files edited (r111d's text; each old text found exactly once): renderer_vulkan/footprints.h,
# vk_footprints.h, vk_footprints.cpp, host_shaders/footprints_layout.h, engine/tests/test_footprints.cpp,
# engine/gpu/CMakeLists.txt (one add_host_shader line), renderer_vulkan/vk_rasterizer_effects.cpp (one hook
# at the top of EffectsBeforeUpscaler), README.md (two rows). New file: host_shaders/footprints_flat.comp.
# footprints.comp is NOT changed (its compiled words stay identical).
#
# Order: needs r111, r111b, r111c and r111d applied (refused otherwise). To take r111d out again, revert
# r111e first.
# Use: python -I -X utf8 r111e_prints-draw.py check | apply | revert
# Root: R111E_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r111e_backup next to this script; revert puts each old text back (each new text found by itself, exactly
# once) and removes the new file.
import os, re, sys

ROOT = os.environ.get("R111E_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r111e_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RULES = RV + "footprints.h"
VKH = RV + "vk_footprints.h"
VKC = RV + "vk_footprints.cpp"
LAYOUT = HS + "footprints_layout.h"
TEST = "engine/tests/test_footprints.cpp"
CMAKE = "engine/gpu/CMakeLists.txt"
EFFECTS = RV + "vk_rasterizer_effects.cpp"
README = "README.md"
FLAT = HS + "footprints_flat.comp"
ORDER = [RULES, VKH, VKC, LAYOUT, TEST, CMAKE, EFFECTS, README]

FLAT_TEXT = r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r111e_prints-draw): the footprints drawn over the finished scene colour, after the lighting and
// before the upscaler (renderer_vulkan/vk_footprints.cpp, Footprints::DrawOver; footprints.h has the rules).
// Two modes, one dispatch over the pixels of the prints' boxes (dispatched with a base: gl_GlobalInvocationID
// is the pixel):
//  - FOOTPRINTS_FLAG_SHOW (BB_FOOTPRINTS_SHOW=1, a test view): the ray of each pixel is cut with the
//    horizontal plane of each print's height; where it falls inside the print's sole rectangle the pixel
//    becomes flat saturated red (a white dot at the print's centre). No depth test, no lighting, no
//    G-buffer: it shows where the engine put the prints and whether the picture's camera agrees.
//  - otherwise (the post stamp, BB_FOOTPRINTS_POST): the pixel's world point from the depth (as
//    footprints.comp), its up-facing share from the depth of two neighbours, the strongest print of each
//    kind by the sole's shape within FOOTPRINTS_PRINT_BAND_M of the point's height; a blood print
//    recolours the lit pixel dark red at its own luminance (the stone's texture and light stay, the hue
//    does not depend on the light's colour), a wet or mud print darkens it a further share. The G-buffer
//    change of footprints.comp (albedo, gloss, specular colour) stays as it was; this adds the part of
//    the look the game's light may leave out (a dark red albedo under a blue moon is black, not red).
// Counters (FOOTPRINTS_FLAT_WORDS words, one atomic a drawn pixel): red pixels, stamped pixels.
#version 450
#extension GL_GOOGLE_include_directive : require
#extension GL_EXT_samplerless_texture_functions : require
#include "footprints_layout.h"

layout(local_size_x = FOOTPRINTS_GROUP, local_size_y = FOOTPRINTS_GROUP, local_size_z = 1) in;

// FootprintRules::Push, word for word (28 words, 112 bytes, as footprints.comp): `gain` is the stamp's
// strength here (BB_FOOTPRINTS_GAIN times BB_FOOTPRINTS_POST); `hunter` and `stamp` are not used.
layout(push_constant) uniform Push {
    vec4 inv_view[3]; // this pass's view to world, rows
    vec4 proj;        // x scale, y scale (signed: ndc +y down), z scale, z offset
    vec2 size;        // pixels
    vec2 jitter;      // render pixels
    vec4 hunter;
    uint print_count;
    uint flags;       // FOOTPRINTS_FLAG_SHOW
    uint stamp;
    float gain;
};

layout(binding = 0, rgba16f) uniform image2D color_img; // the scene colour (HDR, before the tonemap)
layout(binding = 1) uniform texture2D depth_tex;        // the scene's depth
struct Print {
    vec4 a; // x, y, z, strength
    vec4 b; // dir x, dir z, side, kind
};
layout(binding = 2, std430) readonly buffer Prints {
    Print prints[];
};
layout(binding = 3, std430) buffer Counts {
    uint counts[];
};

// View depth (metres, in front: positive) from a depth value, as footprints.comp.
float ViewZ(float depth) {
    if (!(depth > 0.0) || depth >= 1.0) {
        return 0.0;
    }
    return proj.w / min(depth - proj.z, -1e-8);
}

// The world point of pixel `p` at view depth `z`.
vec3 World(ivec2 p, float z) {
    const vec2 uv = (vec2(p) + 0.5) / size - jitter / size;
    const vec2 ndc = uv * 2.0 - 1.0;
    const vec4 view = vec4(ndc.x * z / proj.x, ndc.y * z / proj.y, z, 1.0);
    return vec3(dot(inv_view[0], view), dot(inv_view[1], view), dot(inv_view[2], view));
}

// The world point of a neighbour pixel; false for the sky.
bool Neighbour(ivec2 q, out vec3 w) {
    const float z = ViewZ(texelFetch(depth_tex, q, 0).x);
    w = World(q, z);
    return z > 0.0;
}

// 0..1: the sole's shape at (u along the step, v across it), as footprints.comp.
float Ellipse(vec2 d, vec2 r) {
    return 1.0 - smoothstep(FOOTPRINTS_EDGE, 1.0, length(d / r));
}
float Sole(float u, float v) {
    const float fore = Ellipse(vec2(u - FOOTPRINTS_FORE_U, v), vec2(FOOTPRINTS_FORE_RU, FOOTPRINTS_FORE_RV));
    const float heel = Ellipse(vec2(u - FOOTPRINTS_HEEL_U, v), vec2(FOOTPRINTS_HEEL_RU, FOOTPRINTS_HEEL_RV));
    const float waist = Ellipse(vec2(u - FOOTPRINTS_WAIST_U, v), vec2(FOOTPRINTS_WAIST_RU, FOOTPRINTS_WAIST_RV));
    return max(max(fore, heel), waist);
}

void main() {
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    if (p.x >= int(size.x) || p.y >= int(size.y)) {
        return;
    }
    const uint count = min(print_count, FOOTPRINTS_MAX_PRINTS);
    if ((flags & FOOTPRINTS_FLAG_SHOW) != 0u) {
        // The pixel's ray (the inverse of the pixel to view rule of World with z = 1), in the world.
        const vec2 uv = (vec2(p) + 0.5) / size - jitter / size;
        const vec2 ndc = uv * 2.0 - 1.0;
        const vec3 vdir = vec3(ndc.x / proj.x, ndc.y / proj.y, 1.0);
        const vec3 dir = vec3(dot(inv_view[0].xyz, vdir), dot(inv_view[1].xyz, vdir), dot(inv_view[2].xyz, vdir));
        const vec3 origin = vec3(inv_view[0].w, inv_view[1].w, inv_view[2].w);
        bool red = false;
        bool centre = false;
        for (uint i = 0u; i < count; ++i) {
            const Print pr = prints[i];
            if (abs(dir.y) < 1e-6) {
                continue;
            }
            const float t = (pr.a.y - origin.y) / dir.y;
            if (t <= 0.0) {
                continue;
            }
            const vec3 l = origin + dir * t - pr.a.xyz;
            const vec2 along = pr.b.xy;
            const float u = dot(l.xz, along);
            const float v = dot(l.xz, vec2(-along.y, along.x)) * pr.b.z;
            if (u >= (FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU) * FOOTPRINTS_SOLE_SCALE &&
                u <= (FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU) * FOOTPRINTS_SOLE_SCALE &&
                abs(v) <= FOOTPRINTS_FORE_RV * FOOTPRINTS_SOLE_SCALE) {
                red = true;
                centre = centre || length(vec2(u, v)) < 0.02;
            }
        }
        if (red) {
            imageStore(color_img, p, centre ? vec4(4.0, 4.0, 4.0, 1.0) : vec4(FOOTPRINTS_FLAT_RED, 0.0, 0.0, 1.0));
            atomicAdd(counts[FOOTPRINTS_FLAT_WORD_RED_PX], 1u);
        }
        return;
    }
    // The post stamp.
    const float z = ViewZ(texelFetch(depth_tex, p, 0).x);
    if (z <= 0.0) {
        return;
    }
    const vec3 w = World(p, z);
    float weight[FOOTPRINTS_KINDS] = float[FOOTPRINTS_KINDS](0.0, 0.0, 0.0);
    for (uint i = 0u; i < count; ++i) {
        const Print pr = prints[i];
        const vec3 l = w - pr.a.xyz;
        if (abs(l.y) > FOOTPRINTS_PRINT_BAND_M) {
            continue;
        }
        const vec2 along = pr.b.xy;
        const float u = dot(l.xz, along);
        const float v = dot(l.xz, vec2(-along.y, along.x)) * pr.b.z;
        const float s = Sole(u / FOOTPRINTS_SOLE_SCALE, v / FOOTPRINTS_SOLE_SCALE) * pr.a.w;
        const uint kind = min(uint(pr.b.w + 0.5), FOOTPRINTS_KINDS - 1u);
        weight[kind] = max(weight[kind], s);
    }
    if (max(weight[FOOTPRINTS_KIND_WET], max(weight[FOOTPRINTS_KIND_MUD], weight[FOOTPRINTS_KIND_BLOOD])) *
            gain <= 1.0 / 64.0) {
        return;
    }
    // The up-facing share from two neighbours (the right or left one, the lower or upper one).
    const ivec2 last = ivec2(size) - 1;
    const ivec2 qx = ivec2(p.x < last.x ? p.x + 1 : p.x - 1, p.y);
    const ivec2 qy = ivec2(p.x, p.y < last.y ? p.y + 1 : p.y - 1);
    vec3 wx, wy;
    float up = 0.0;
    if (Neighbour(qx, wx) && Neighbour(qy, wy)) {
        const vec3 c = cross(wx - w, wy - w);
        const float l = length(c);
        up = l > 1e-12 ? abs(c.y) / l : 0.0;
    }
    const float face = smoothstep(FOOTPRINTS_UP_MIN, FOOTPRINTS_UP_FULL, up);
    const float wet = clamp(weight[FOOTPRINTS_KIND_WET] * face * gain, 0.0, 1.0);
    const float mud = clamp(weight[FOOTPRINTS_KIND_MUD] * face * gain, 0.0, 1.0);
    const float blood = clamp(weight[FOOTPRINTS_KIND_BLOOD] * face * gain, 0.0, 1.0);
    if (max(wet, max(mud, blood)) <= 1.0 / 64.0) {
        return;
    }
    const vec4 c = imageLoad(color_img, p);
    const float lum = dot(c.rgb, vec3(0.2126, 0.7152, 0.0722));
    vec3 rgb = c.rgb * (1.0 - FOOTPRINTS_POST_WET_DARKEN * max(wet, mud));
    const vec3 dark_red = vec3(FOOTPRINTS_POST_BLOOD_TINT_R, FOOTPRINTS_POST_BLOOD_TINT_G, FOOTPRINTS_POST_BLOOD_TINT_B) *
                          (lum * FOOTPRINTS_POST_BLOOD_LUM);
    rgb = mix(rgb, dark_red, FOOTPRINTS_POST_BLOOD_COVER * blood);
    imageStore(color_img, p, vec4(rgb, c.a));
    atomicAdd(counts[FOOTPRINTS_FLAT_WORD_POST_PX], 1u);
}
'''

# (path, old, new): `old` found exactly once; `new` replaces it. Applied when `new` is found exactly once.
EDITS = {
    LAYOUT: [
        (r'''#define FOOTPRINTS_RING_OUT_M 0.34
''',
         r'''#define FOOTPRINTS_RING_OUT_M 0.34
// (r111e) The draw over the finished picture (footprints_flat.comp). Counter words, one atomic a drawn
// pixel: the flat red test view's pixels and the post stamp's pixels. The test view's red (scene colour,
// before the tonemap; the print's centre dot is white, 4). The post stamp: a wet or mud print darkens the
// lit pixel a further POST_WET_DARKEN; a blood print recolours it toward a dark red of the pixel's own
// luminance (the tint has luminance 1: (1.00 0.12 0.10) over 0.3056), cover POST_BLOOD_COVER at full
// weight, scaled by POST_BLOOD_LUM.
#define FOOTPRINTS_FLAT_WORDS 2u
#define FOOTPRINTS_FLAT_WORD_RED_PX 0u
#define FOOTPRINTS_FLAT_WORD_POST_PX 1u
#define FOOTPRINTS_FLAT_RED 3.0
#define FOOTPRINTS_POST_WET_DARKEN 0.25
#define FOOTPRINTS_POST_BLOOD_TINT_R 3.272
#define FOOTPRINTS_POST_BLOOD_TINT_G 0.393
#define FOOTPRINTS_POST_BLOOD_TINT_B 0.327
#define FOOTPRINTS_POST_BLOOD_LUM 1.0
#define FOOTPRINTS_POST_BLOOD_COVER 0.85
'''),
    ],
    RULES: [
        (r'''//                       the test tools' live knobs a running game asks again every pass (Gain()).
''',
         r'''//                       the test tools' live knobs a running game asks again every pass (Gain()).
//   BB_FOOTPRINTS_SHOW  (r111e) 1: a test view over the finished picture: each live print a flat saturated red
//                       rectangle on its ground plane, no depth, no light (ShowFlat(); live like the gain).
//   BB_FOOTPRINTS_POST  (r111e) a number from 0 to 2, default 1: the post stamp's strength, a pass on the
//                       scene colour after the lighting (blood recoloured dark red at the lit pixel's
//                       luminance, wet and mud darkened a further 25%); 0: the G-buffer change alone (Post()).
'''),
        (r'''inline constexpr std::uint32_t WordBloodN = FOOTPRINTS_WORD_BLOOD_N;
''',
         r'''inline constexpr std::uint32_t WordBloodN = FOOTPRINTS_WORD_BLOOD_N;
// (r111e) the draw over the picture: its counter words
inline constexpr std::uint32_t FlatWords = FOOTPRINTS_FLAT_WORDS;
inline constexpr std::uint32_t WordFlatRedPx = FOOTPRINTS_FLAT_WORD_RED_PX;
inline constexpr std::uint32_t WordFlatPostPx = FOOTPRINTS_FLAT_WORD_POST_PX;
static_assert(FlatWords == 2u && WordFlatRedPx == 0u && WordFlatPostPx == 1u);
'''),
        (r'''    return Load().gain;
#endif
}
''',
         r'''    return Load().gain;
#endif
}

/// (r111e) BB_FOOTPRINTS_SHOW's text: "1" (blanks around allowed) draws the flat red test view; anything else
/// (unset, empty, 0, other text) does not.
inline bool ShowFlatOfText(const char* text) {
    return Detail::Is(text, "1");
}

/// (r111e) The test view now: with the live knobs asked again every call, else read once.
inline bool ShowFlat() {
#if BB_FOOTPRINTS_LIVE
    static BbLiveKnobs::Knob<bool> knob{"BB_FOOTPRINTS_SHOW", ShowFlatOfText};
    return knob.Get();
#else
    static const bool on = ShowFlatOfText(std::getenv("BB_FOOTPRINTS_SHOW"));
    return on;
#endif
}

/// (r111e) BB_FOOTPRINTS_POST: the accepted range, 0 (no post stamp) to PostMax.
inline constexpr double PostMax = 2.0;

/// (r111e) BB_FOOTPRINTS_POST's text: a number from 0 to PostMax; unset, empty, other text or a number out of
/// range: 1.
inline float PostOfText(const char* text) {
    const char* t = Detail::Trim(text);
    if (t == nullptr || *t == '\0') {
        return 1.0f;
    }
    char* end = nullptr;
    const double g = std::strtod(t, &end);
    if (end != t && *Detail::Trim(end) == '\0' && g >= 0.0 && g <= PostMax) {
        return float(g);
    }
    return 1.0f;
}

/// (r111e) The post stamp's strength now (live like the gain).
inline float Post() {
#if BB_FOOTPRINTS_LIVE
    static BbLiveKnobs::Knob<float> knob{"BB_FOOTPRINTS_POST", PostOfText};
    return knob.Get();
#else
    static const float strength = PostOfText(std::getenv("BB_FOOTPRINTS_POST"));
    return strength;
#endif
}
'''),
    ],
    VKH: [
        (r'''    void OnFrameEnd();
''',
         r'''    void OnFrameEnd();
    /// (r111e) Once a frame at the upscaler's trigger, after the lighting: the prints over the scene
    /// colour `color` (the flat red test view BB_FOOTPRINTS_SHOW, or the post stamp BB_FOOTPRINTS_POST),
    /// depth tested against the scene's depth. Nothing when both are off or no print is on screen.
    void DrawOver(VideoCore::ImageId color, std::array<float, 2> jitter);
'''),
        (r'''    std::array<u32, FootprintRules::SlotWords> sense{}; ///< the last fresh host copy
    bool sense_fresh = false;
};
''',
         r'''    std::array<u32, FootprintRules::SlotWords> sense{}; ///< the last fresh host copy
    bool sense_fresh = false;

    // (r111e) The draw over the picture: its pipeline and buffers are made at its first pass.
    bool FlatReady();
    vk::UniqueDescriptorSetLayout flat_set_layout;
    vk::UniquePipelineLayout flat_layout;
    vk::UniquePipeline flat_pipeline;
    Buffer flat_prints, flat_counts, flat_host;
    bool flat_tried = false, flat_failed = false, told_flat = false;
    struct Flat {
        u32 frames = 0, passes = 0, off_screen = 0, no_camera = 0, cannot = 0, sent = 0;
        u32 red_last = 0, red_max = 0, post_last = 0, post_max = 0; ///< pixels of the last pass read back
        u64 rect_px = 0;
    } flat;
};
'''),
    ],
    VKC: [
        (r'''#include "video_core/host_shaders/footprints_comp.h"
''',
         r'''#include "video_core/host_shaders/footprints_comp.h"
#include "video_core/host_shaders/footprints_flat_comp.h"
'''),
        (r'''constexpr vk::DeviceSize PrintBytes = R::PrintFloats * 4;
''',
         r'''constexpr vk::DeviceSize PrintBytes = R::PrintFloats * 4;
constexpr vk::DeviceSize FlatBytes = R::FlatWords * 4; ///< (r111e) the draw over the picture's counters
'''),
        (r'''    if (!camera_motion.Enabled()) {
        Fail("it needs the upscaler's camera (BB_UPSCALER=none)");
''',
         r'''    BbReport::Printf("Footprints (r111e): after the lighting, on the scene colour: post stamp %.2f "
                     "(BB_FOOTPRINTS_POST: blood prints recoloured dark red at the lit pixel's luminance, wet "
                     "and mud %.0f%% darker still; 0 off); test view %s (BB_FOOTPRINTS_SHOW=1: flat red "
                     "quads, no depth, no light)\n",
                     double(R::Post()), double(FOOTPRINTS_POST_WET_DARKEN) * 100.0,
                     R::ShowFlat() ? "on" : "off");
    if (!camera_motion.Enabled()) {
        Fail("it needs the upscaler's camera (BB_UPSCALER=none)");
'''),
        (r'''    FreeBuffer(readback);
}
''',
         r'''    FreeBuffer(readback);
    FreeBuffer(flat_prints);
    FreeBuffer(flat_counts);
    FreeBuffer(flat_host);
}
'''),
        (r'''void Footprints::Place(const R::Step& s, R::Kind kind, float strength, double now) {
''',
         r'''bool Footprints::FlatReady() {
    if (flat_tried) {
        return !flat_failed;
    }
    flat_tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
        EffectPass::Create(instance, flat_set_layout, flat_layout, flat_pipeline,
                           {eStorageImage, eSampledImage, eStorageBuffer, eStorageBuffer},
                           sizeof(R::Push), FOOTPRINTS_FLAT_COMP, "Footprints flat", true) &&
        MakeBuffer(flat_prints, R::MaxPrints * PrintBytes, false,
                   vk::BufferUsageFlagBits::eStorageBuffer | vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(flat_counts, FlatBytes, false,
                   vk::BufferUsageFlagBits::eStorageBuffer | vk::BufferUsageFlagBits::eTransferSrc |
                       vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(flat_host, FlatBytes, true, vk::BufferUsageFlagBits::eTransferDst);
    if (!made) {
        flat_failed = true;
        BbReport::Printf("Footprints (r111e): the draw over the picture is off - this GPU cannot run its pass\n");
        return false;
    }
    std::memset(flat_host.mapped, 0, FlatBytes);
    return true;
}

void Footprints::DrawOver(VideoCore::ImageId color_id, std::array<float, 2> jitter) {
    if (failed || flat_failed) {
        return;
    }
    const bool show = R::ShowFlat();
    const float strength = R::Gain() * R::Post();
    if (!show && !(strength > 0.0f)) {
        return;
    }
    ++flat.frames;
    if (flat_host.mapped) { // the last pass's counts (a frame or two old; the host copy needs no fence)
        std::array<u32, R::FlatWords> c{};
        std::memcpy(c.data(), flat_host.mapped, sizeof(c));
        flat.red_last = c[R::WordFlatRedPx];
        flat.post_last = c[R::WordFlatPostPx];
        flat.red_max = std::max(flat.red_max, flat.red_last);
        flat.post_max = std::max(flat.post_max, flat.post_last);
    }
    if (placed_count == 0 || !color_id) {
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    if (camera_motion.PreviewFrame() || !camera.valid || camera.proj[0] == 0.0f || camera.proj[1] == 0.0f) {
        ++flat.no_camera;
        return;
    }
    const VideoCore::ImageId depth_id = camera_motion.Depth();
    if (!depth_id || texture_cache.GetImage(color_id).info.pixel_format != vk::Format::eR16G16B16A16Sfloat) {
        ++flat.cannot;
        return;
    }
    u32 width = 0, height = 0;
    bool reduced = false;
    if (!SceneSize(color_id, width, height, reduced)) {
        ++flat.cannot;
        return;
    }
    { // the depth must stand where the colour does (reduced alike, and covering the scene), as Edit asks
        const auto& depth_image = texture_cache.GetImage(depth_id);
        if ((scene_targets.Reduced() && scene_targets.EligibleScene(depth_image)) != reduced ||
            (!reduced && (depth_image.info.size.width < width || depth_image.info.size.height < height))) {
            ++flat.cannot;
            return;
        }
    }
    // The prints on screen (their boxes) as Edit takes them.
    const float fw = float(width), fh = float(height);
    const float cam_x = camera.inv_view[3], cam_y = camera.inv_view[7], cam_z = camera.inv_view[11];
    std::array<float, R::MaxPrints * R::PrintFloats> packed{};
    u32 count = 0;
    R::Rect rect{};
    for (u32 i = 0; i < placed_count; ++i) {
        const Placed& p = placed[i];
        const float dx = p.x - cam_x, dy = p.y - cam_y, dz = p.z - cam_z;
        if (p.now <= 0.0f || dx * dx + dy * dy + dz * dz > R::MaxDistanceM * R::MaxDistanceM) {
            continue;
        }
        const float lo[3] = {p.x - R::PrintBoxAcrossM, p.y - R::PrintBoxUpM, p.z - R::PrintBoxAcrossM};
        const float hi[3] = {p.x + R::PrintBoxAcrossM, p.y + R::PrintBoxUpM, p.z + R::PrintBoxAcrossM};
        const R::Rect r = R::Project(camera.view, camera.proj, fw, fh, jitter, lo, hi);
        if (r.Empty()) {
            continue;
        }
        rect = R::Union(rect, r);
        R::Pack(p.x, p.y, p.z, p.now, p.dir_x, p.dir_z, p.side, p.kind,
                packed.data() + std::size_t(count) * R::PrintFloats);
        ++count;
    }
    if (count == 0 || rect.Empty()) {
        ++flat.off_screen;
        return;
    }
    if (!FlatReady()) {
        return;
    }
    const SceneUseScope scene_use{"footprints"};
    scheduler.EndRendering();
    const vk::ImageView color_view =
        ViewOf(color_id, vk::Format::eR16G16B16A16Sfloat, vk::ImageAspectFlagBits::eColor, true, true);
    const vk::ImageView depth_view =
        ViewOf(depth_id, texture_cache.GetImage(depth_id).info.pixel_format,
               vk::ImageAspectFlagBits::eDepth, false, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!color_view || !depth_view) {
        ++flat.cannot;
        return;
    }
    R::Push push{};
    push.inv_view = camera.inv_view;
    push.proj = camera.proj;
    push.size = {fw, fh};
    push.jitter = jitter;
    push.count = count;
    push.flags = show ? R::FlagShow : 0u;
    push.stamp = u32(frame + 1);
    push.gain = strength;
    const u32 gx0 = u32(rect.x0) / R::Group, gy0 = u32(rect.y0) / R::Group;
    const u32 gx1 = (u32(rect.x1) + R::Group - 1) / R::Group;
    const u32 gy1 = (u32(rect.y1) + R::Group - 1) / R::Group;
    ++flat.passes;
    flat.sent += count;
    flat.rect_px += u64(rect.x1 - rect.x0) * u64(rect.y1 - rect.y0);
    if (!told_flat) {
        told_flat = true;
        BbReport::Printf("Footprints (r111e): first pass over the picture at frame %llu: %s, %u prints, "
                         "rectangle %d x %d px of a %ux%u scene%s\n",
                         static_cast<unsigned long long>(frame),
                         show ? "flat red test view" : "post stamp", count, int(rect.x1 - rect.x0),
                         int(rect.y1 - rect.y0), width, height, reduced ? " (reduced)" : "");
    }
    EffectPass::Mark(ProfileRow, "footprints", true);
    scheduler.RecordCrumb(
        {.name = "footprints over"},
        [push, packed, count, gx0, gy0, gx1, gy1, color_view, depth_view,
         prints = flat_prints.buffer, counts = flat_counts.buffer, host = flat_host.buffer,
         pass_pipeline = *flat_pipeline, pass_layout = *flat_layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            cmd.fillBuffer(counts, 0, FlatBytes, 0);
            cmd.updateBuffer(prints, 0, vk::DeviceSize(count) * PrintBytes, packed.data());
            EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, Compute,
                                      ReadWrite);
            using enum vk::DescriptorType;
            const std::array infos{Info(color_view), Info(depth_view)};
            const vk::DescriptorBufferInfo prints_info{prints, 0, R::MaxPrints * PrintBytes};
            const vk::DescriptorBufferInfo counts_info{counts, 0, FlatBytes};
            const std::array writes{ImageWrite(0, eStorageImage, &infos[0]),
                                    ImageWrite(1, eSampledImage, &infos[1]),
                                    BufferWrite(2, &prints_info), BufferWrite(3, &counts_info)};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            cmd.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
            EndBarrier(cmd);
            cmd.copyBuffer(counts, host, vk::BufferCopy{0, 0, FlatBytes});
            EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                                      vk::PipelineStageFlagBits2::eHost,
                                      vk::AccessFlagBits2::eHostRead);
        });
}

void Footprints::Place(const R::Step& s, R::Kind kind, float strength, double now) {
'''),
        (r'''                     stats.print_px_frames, stats.print_px_max, double(R::Gain()));
    stats = {};
''',
         r'''                     stats.print_px_frames, stats.print_px_max, double(R::Gain()));
    BbReport::Printf("Footprints (r111e): over the picture: %u frames, %u passes (%s), %u prints sent, "
                     "%.0f px a pass; the last pass drew %u flat red px (most %u) and %u stamped px (most "
                     "%u); skipped %u off screen, %u no camera, %u cannot; post %.2f\n",
                     flat.frames, flat.passes, R::ShowFlat() ? "flat red view" : "post stamp", flat.sent,
                     flat.passes ? double(flat.rect_px) / double(flat.passes) : 0.0, flat.red_last,
                     flat.red_max, flat.post_last, flat.post_max, flat.off_screen, flat.no_camera,
                     flat.cannot, double(R::Post()));
    flat = {};
    stats = {};
'''),
    ],
    TEST: [
        (r'''    // Pack.
    {
''',
         r'''    // (r111e) BB_FOOTPRINTS_SHOW and BB_FOOTPRINTS_POST.
    {
        assert(ShowFlatOfText("1") && ShowFlatOfText(" 1 ") && !ShowFlatOfText(nullptr));
        assert(!ShowFlatOfText("") && !ShowFlatOfText("0") && !ShowFlatOfText("show") && !ShowFlatOfText("11"));
        assert(PostOfText(nullptr) == 1.0f && PostOfText("") == 1.0f && PostOfText("0") == 0.0f);
        assert(Near(PostOfText(" 0.5 "), 0.5) && Near(PostOfText("2"), 2.0));
        assert(PostOfText("2.5") == 1.0f && PostOfText("-1") == 1.0f && PostOfText("x") == 1.0f);
        assert(PostOfText("1 x") == 1.0f);
        assert(FlatWords == 2u && WordFlatRedPx != WordFlatPostPx);
        // the blood tint's luminance is 1 (so the stamp keeps the lit pixel's luminance)
        const double lum = 0.2126 * FOOTPRINTS_POST_BLOOD_TINT_R + 0.7152 * FOOTPRINTS_POST_BLOOD_TINT_G +
                           0.0722 * FOOTPRINTS_POST_BLOOD_TINT_B;
        assert(Near(lum, 1.0, 2e-3));
    }
    // Pack.
    {
'''),
    ],
    CMAKE: [
        (r'''add_host_shader(footprints.comp footprints_comp)
''',
         r'''add_host_shader(footprints.comp footprints_comp)
# bbport (r111e_prints-draw): the footprints over the finished picture (flat red test view, post stamp)
add_host_shader(footprints_flat.comp footprints_flat_comp)
'''),
    ],
    EFFECTS: [
        (r'''void Rasterizer::EffectsBeforeUpscaler(u64 compute_hash) {
''',
         r'''void Rasterizer::EffectsBeforeUpscaler(u64 compute_hash) {
    // bbport (r111e_prints-draw): BB_FOOTPRINTS on only (off: one null pointer test): the footprints
    // over the scene colour, the flat red test view or the post stamp (vk_footprints.h).
    if (footprints && compute_hash == upscaler->TriggerHash()) {
        footprints->DrawOver(upscaler->SceneColor(), upscaler->Jitter());
    }
'''),
    ],
    README: [
        (r'''running game asks again every pass, so one game can show a view with its prints and the same view without them | `1` |
''',
         r'''running game asks again every pass, so one game can show a view with its prints and the same view without them | `1` |
| `BB_FOOTPRINTS_SHOW` | Only with `BB_FOOTPRINTS` on. `1`: a test view of where the prints are: every live print is drawn as a flat saturated red rectangle (0.28 by 0.11 m, a white dot at its centre) on the horizontal plane of its height, straight onto the scene colour after the lighting and before the upscaler, ignoring depth, light and the G-buffer, so a still shows whether the prints lie where the hunter walked and the picture's camera agrees; the post stamp is not drawn then (the G-buffer change still is). Unset, empty, `0` or other text: off. In a build with the test tools' live knobs (`BB_LIVE_KNOBS_FILE`) it is asked again every frame. Cost, only while on: one pass over the smallest screen rectangle holding the prints' boxes | unset |
| `BB_FOOTPRINTS_POST` | Only with `BB_FOOTPRINTS` on. A number from 0 to 2: the strength of the post stamp, a pass over the scene colour after the lighting (the same place as `BB_FOOTPRINTS_SHOW`, depth tested) that keeps prints legible where the game's light is dim or blue: on up-facing ground within 0.16 m of a print's height and inside its sole, a blood print recolours the lit pixel to a dark red of the pixel's own luminance (the stone's texture and the game's shading stay), a wet or mud print darkens the lit pixel a further 25%; times the print's weight, this strength and `BB_FOOTPRINTS_GAIN` (so a gain of 0 still draws nothing). 0: no stamp, only the G-buffer change. Unset or empty: 1; other text or a number out of range: 1. Cost: one pass per frame over the prints' screen rectangle, about the G-buffer pass's (an estimate of 0.02 to 0.08 ms at 1080p internal), only in frames with a live print on screen; memory three small buffers (about 1.5 KB). In a build with the test tools' live knobs it is asked again every frame | `1` |
'''),
    ],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    """'applied' (each new text once), 'clean' (each old text once, no new text), else refuse."""
    done = todo = 0
    for old, new in eds:
        co, cn = cur.count(old), cur.count(new)
        if cn == 1 and (co == 0 or new.find(old) >= 0 and co == 1):
            done += 1
        elif cn == 0 and co == 1:
            todo += 1
        else:
            raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1 and 0, or 0 or 1 "
                             "and 1; are r111 to r111d applied, and is this patch's own earlier version "
                             "reverted?): %r" % (path, co, cn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, done, len(eds)))


def split_args(text):
    """The top-level comma separated arguments of a call's text after its format string."""
    out, depth, cur, quote = [], 0, "", False
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            cur += ch
            if ch == "\\":
                cur += text[i + 1]
                i += 1
            elif ch == '"':
                quote = False
        elif ch == '"':
            quote = True
            cur += ch
        elif ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    if cur.strip():
        out.append(cur.strip())
    return out


def text_checks(texts):
    """Ties a compiler cannot check, on the full result."""
    cpp = texts[VKC]
    # Log lines: prefix, under 300 characters with wide numbers, conversions equal to arguments.
    n_new = 0
    for m in re.finditer(r'BbReport::Printf\(((?:\s*"(?:[^"\\]|\\.)*")+)(.*?)\);\n', cpp, re.S):
        fmt = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))).replace("\\n", "")
        if not fmt.startswith("Footprints (r111"):
            raise SystemExit("text check: a log line without its prefix: %r" % fmt[:60])
        if "(r111e)" not in fmt:
            continue
        n_new += 1
        convs = re.findall(r"%(?!%)[-+ 0-9.]*(?:ll)?[udfs]", fmt.replace("%%", ""))
        args = split_args(m.group(2).lstrip().lstrip(",")) if m.group(2).strip() else []
        if len(convs) != len(args):
            raise SystemExit("text check: %d conversions, %d arguments: %r" % (len(convs), len(args), fmt[:70]))
        wide = re.sub(r"%[-+]?[0-9]*\.[0-9]+f", "X" * 9, fmt)
        wide = re.sub(r"%(?:ll)?[ud]", "X" * 7, wide)
        wide = re.sub(r"%s", "X" * 12, wide)
        wide = wide.replace("%%", "%")
        print("  r111e log line (wide %d, %d conversions): %s..." % (len(wide), len(convs), fmt[:50]))
        if len(wide) > 300:
            raise SystemExit("text check: a log line may pass 300 characters (%d): %r" % (len(wide), fmt[:60]))
    if n_new != 4:
        raise SystemExit("text check: %d r111e log lines (4 expected)" % n_new)
    # The shader's push block is the C++ one word for word (names aside), the layout has the words.
    flat = texts[FLAT]
    for need in ("layout(binding = 0, rgba16f) uniform image2D color_img;", "FOOTPRINTS_FLAG_SHOW",
                 "FOOTPRINTS_FLAT_WORD_RED_PX", "FOOTPRINTS_FLAT_WORD_POST_PX", "float gain;"):
        if need not in flat:
            raise SystemExit("text check: the shader lacks %r" % need)
    if "#include \"footprints_layout.h\"" not in flat:
        raise SystemExit("text check: the shader does not include the layout")
    lay = texts[LAYOUT]
    for name in ("FOOTPRINTS_FLAT_WORDS", "FOOTPRINTS_FLAT_RED", "FOOTPRINTS_POST_WET_DARKEN",
                 "FOOTPRINTS_POST_BLOOD_COVER", "FOOTPRINTS_POST_BLOOD_LUM", "FOOTPRINTS_POST_BLOOD_TINT_R"):
        if lay.count("#define " + name + " ") != 1:
            raise SystemExit("text check: layout does not define %s once" % name)
    if texts[EFFECTS].count("footprints->DrawOver(") != 1 or texts[VKC].count("void Footprints::DrawOver(") != 1:
        raise SystemExit("text check: the DrawOver hook or definition is not there exactly once")
    if "footprints_flat" not in texts[CMAKE]:
        raise SystemExit("text check: CMake does not build the new shader")
    for name in ("BB_FOOTPRINTS_SHOW", "BB_FOOTPRINTS_POST"):
        if texts[README].count("| `%s` |" % name) != 1:
            raise SystemExit("text check: README lacks the %s row" % name)
    # No tab, no CR in the edit texts.
    for path, eds in EDITS.items():
        for old, new in eds:
            if "\t" in new or "\r" in new:
                raise SystemExit("text check: an edit of %s has a tab or a CR" % path)
    if "\t" in FLAT_TEXT or "\r" in FLAT_TEXT:
        raise SystemExit("text check: the shader has a tab or a CR")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 r111e_prints-draw.py check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R111E_ROOT)" % ROOT)
    for need_path in (RULES, HS + "blood_albedo_layout.h", HS + "footprints.comp"):
        if not os.path.exists(os.path.join(ROOT, need_path)):
            raise SystemExit("REFUSED: r111 to r111d are not applied (%s is missing)" % need_path)
    if "FOOTPRINTS_WAIST_U" not in load(LAYOUT)[2] and not os.path.exists(os.path.join(ROOT, FLAT)):
        raise SystemExit("REFUSED: r111d is not applied (no boot sole in the layout)")
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    flat_full = os.path.join(ROOT, FLAT)
    flat_here = os.path.exists(flat_full)
    if state == "clean" and flat_here:
        raise SystemExit("REFUSED: %s exists although the edits are not applied" % FLAT)
    if state == "applied" and not flat_here:
        raise SystemExit("REFUSED: the edits are applied but %s is missing" % FLAT)
    eol_new = plan[0][3]

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in eds:
                cur = cur.replace(old, new, 1)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        out[FLAT] = FLAT_TEXT
        return out

    if cmd == "check":
        if state == "applied":
            texts = {p[0]: p[4] for p in plan}
            on_disk = open(flat_full, "rb").read().decode("utf-8").replace("\r\n", "\n")
            if on_disk != FLAT_TEXT:
                raise SystemExit("%s differs from this script's text" % FLAT)
            texts[FLAT] = on_disk
            text_checks(texts)
            print("applied (%d files edited, 1 file new; text checks pass)" % len(plan))
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, 1 file new; text checks on the result "
                  "pass)" % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r111etmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        tmp = flat_full + ".r111etmp"
        open(tmp, "wb").write(FLAT_TEXT.replace("\n", eol_new).encode("utf-8"))
        os.replace(tmp, flat_full)
        print("applied (%d files edited, 1 file new)" % len(plan))
        return
    if state != "applied":
        print("nothing to revert")
        return
    on_disk = open(flat_full, "rb").read().decode("utf-8").replace("\r\n", "\n")
    if on_disk != FLAT_TEXT:
        raise SystemExit("REFUSED: %s differs from this script's text; nothing reverted" % FLAT)
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for old, new in reversed(eds):
            if cur.count(new) != 1:
                raise SystemExit("%s: new text found %d times in the revert: %r" % (path, cur.count(new), new[:70]))
            cur = cur.replace(new, old, 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r111etmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    os.remove(flat_full)
    print("reverted (%d files edited back, 1 file removed)" % len(plan))


main()
