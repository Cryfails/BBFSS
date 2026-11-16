# r130e_sewer-water-moves: patch script (lane LRT, task LRT-T05 water and caustics). Owner goal LRT-G089: "I think for the caustics the
# water like in the sewer need to move or at least have some kind of movement/physics. Maybe the puddles should ripple from steps
# and wind too?" Applies ON TOP of r130b_water-moves (refuses a tree without it: no `#define CAUSTICS_FLAG_MOTION 512u`).
#
# Draft: r130e_sewer-water-moves.draft.md. Evidence from build b80: at the sewer r130b at strength 4 changes the water floor over
# one second, but only faintly (whole-frame pair difference 0.95 against 0.52 with the motion off): it only changes the brightness of
# near-black water pixels. With the motion off the game's own sewer water does not move at all. The game draws its water BEFORE this
# pass (opaque, depth write on), so the pass sees the water's own colour and depth.
#
# What it does (only with graphics_water_motion_strength > 0 or BB_WATER_MOTION > 0; see Off):
#  A rippled reflection of the mirrored plane's water (the sewer): two more dispatches of caustics.comp inside Apply's existing
#  crumb, after its normal dispatch, only when the camera is above a mirrored plane. Both cover the band of rows from the first row
#  the plane can be water (WaterTopRow, a ray test from the host) down.
#   WARP_COPY: each band pixel that is water (depth on the plane within the tolerance, up-facing, nearer than CAUSTICS_FADE_END) stores
#              vec4(scene rgb, stamp) into the copy image (binding 8, RGBA16F, the scene's size). The stamp is the dispatch's number
#              (1 to 2047, exact in half float), so no clear a frame: a texel counts only when its alpha holds this stamp.
#   WARP:      each such pixel takes its colour from a place moved by the wave field's slope (the mirror image moves by
#              2 x CAUSTICS_MOTION_REFLECT_M x the slope on the plane, projected; the length is at most SHIFT_MAX x the frame's
#              height, faded out with distance), bilinear over the four copy texels that hold this stamp (walls, the hunter's legs and
#              stale texels never bleed in; under half the weight: the pixel keeps its own colour, counted "kept"). Then the glint:
#              the colour times 1 + t, t = GLINT x strength x (Focus - 1) x lum / (lum + KNEE), within +-GLINT_MAX and faded out:
#              the focus has mean 1, so light is moved, not added (LRT-D124). The glint FOLLOWS THE KNOB (strength 2 gives half of 4).
#  So the lantern's reflection in the water wobbles and breaks up, and bright reflections sparkle; r130b's brightness shimmer and
#  net still run underneath. A thread writes only its own scene pixel and reads sources from the copy image: no race.
#  Motion without the caustics: Wanted() is also true with motion > 0 and Apply runs a motion-only dispatch (kind 1, no net, no bed
#  light unless below) when there is a plane and the camera is above it.
#  Bed light from the ini: with motion > 0, lamps > 0 and BB_CAUSTICS_WORLD unset or empty, r107f's bed light (the lamps' light on the
#  floor under the water, with the moving net) runs at BedAuto 1.0 as if the variable were 1; a set variable wins (also 0).
#  The 256 KB world map is made the first frame it is needed.
#
# Deviations from the draft (all to keep r130b's own check passing, or from reading the code):
#  - The shader has no separate WarpMain with its own barriers: Shade() hands the two new flags to WarpPixel first, so main's
#    existing barriers, group counters and flush are used (r130b's text check wants exactly two barrier() calls in the file). The
#    stats go to the shared group_warp pair and the motion block words WARP_PX and WARP_KEPT.
#  - The motion-only dispatch is a block of its own in Apply (kind 1, the flag, the block write): r130b's FlagsOf and motion_kind
#    lines are NOT rewritten (r130b's check counts them). The early exits at three places (not one) take `motion_only` too.
#  - r130b's log line "the water caustics are off (both strengths 0): nothing moves" is NOT rewritten (r130b's check counts it); a
#    line of r130e after it says the reflection still ripples. No line of this patch holds the words of r130b's tag (its check
#    refuses any other line with them): the tag comes from caustics_params.h (Warp::LogTag).
#  - Glint: the strength is in the formula (GLINT 0.30 per unit of strength, within +-0.6, symmetric so the mean stays 1), and the
#    knee is 0.05 (the draft's flat 0.5 and knee 0.25 gave under 1% on near-black water, and did not follow the knob).
#  - The warp stats' read of the old block is a separate small block before r130b's block (r130b's block must stay in one piece).
#
# Knob: r130b's graphics_water_motion_strength (0..4, default 0, live) and BB_WATER_MOTION. No new key, no menu entry.
#
# Files (6): host_shaders/caustics_layout.h, host_shaders/caustics.comp, renderer_vulkan/caustics_params.h, vk_caustics.h,
# vk_caustics.cpp, engine/tests/test_caustics.cpp. New: this script and a slot job file. Not touched: README,
# CMakeLists, build.sh, bbport_settings, vk_rasterizer*, vk_effect_shaders.
#
# Off guarantee (graphics_water_motion_strength = 0 and BB_WATER_MOTION unset): the host's motion_strength is 0, so FlagsOf and
# Alone give 0/false: no motion flag, no warp flag, no copy image, no ROW0/STAMP write, no world auto (WorldFor returns the variable's
# own value, 0 when unset), no new log line, Wanted() unchanged in effect. In the shader every new statement sits under the two warp
# flags (push constants, uniform false); the only things left are one more descriptor (binding 8: the scene view as a stand-in, a
# storage image the shader never touches) in the existing push, two more shared uints and one live-knob read a frame in Wanted()
# while no Caustics object exists. The SPIR-V differs, the picture does not: bit for bit as before.
# Cost (estimate, not measured): COPY reads depth over the band (about 1.1 Mpx at 1080p) and writes about 83k px x 8 B; WARP repeats
# the water test and on water px does WaveAt (60-100 ALU), 4 copy loads and a projection. Both: about 0.02-0.04 ms at 1080p
# internal (0.08-0.15 ms at 4K). Bed light (new to the sewer): guess 0.01-0.03 ms. Host under 5 us. Memory: the copy image is 8 B x
# width x height: 16.6 MB at 1920x1080, 66 MB at 3840x2160 internal, made only when the first warp runs, remade on a size change;
# the world map 256 KB when the bed light starts. The profile row "Lighting: water caustics" holds all of it.
# Risk: no motion vectors for the warp, so the upscaler may soften it (SHIFT_MAX and MotionTimeScale are the levers).
#
# Log lines start "Water motion (r130e)": E1 first rippled reflection, E2 each report, E3 bed light with the motion (once), E4 the
# copy image could not be made (once), E5 the correction after r130b's "nothing moves" when both caustics strengths are 0.
#
# Not verified: no full build, no Vulkan run (the shader is compiled with glslangValidator + spirv-val, the unit test is built and run,
# vk_caustics.cpp is checked with clang++ -fsyntax-only with stand-in generated headers, all on a private copy); the shader's GLSL
# arithmetic is the C++ twins' by reading; the barriers and layout of the copy image are by reading, not by a validation layer; the
# look and the cost are the slot jobs' to judge.
#
# Use: python -I -X utf8 r130e_sewer-water-moves.py check | apply | revert
# Root: R130E_ROOT, else <tree> (needs engine/gpu). Line ends kept (CRLF or LF; mixed refused). apply backs the originals up in
# r130e_backup next to this script. Each edit refuses unless its anchor / old text is found exactly once; a tree with some edits
# applied and some not is refused; text checks run on the result before anything is written; files are written through a temp
# file. revert puts back exactly what apply inserted or replaced. r130b must stay applied (its own check still passes).
# .fixed (short review): the copy image's first clear (Undefined to General) moved to the start of the crumb, before the first
# dispatch that binds it at binding 8 (it was after the normal dispatch: a layout error for the validation layer).
import os, sys

ROOT = os.environ.get("R130E_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r130e_backup")
TMP = ".r130etmp"
VC = "engine/gpu/shadps4/video_core/"
LAY = VC + "host_shaders/caustics_layout.h"
COMP = VC + "host_shaders/caustics.comp"
RV = VC + "renderer_vulkan/"
PAR = RV + "caustics_params.h"
VH = RV + "vk_caustics.h"
VC_CPP = RV + "vk_caustics.cpp"
TC = "engine/tests/test_caustics.cpp"
CODE = (LAY, COMP, PAR, VH, VC_CPP, TC)


def L(text):
    # a block of lines: one leading newline dropped, a trailing newline ensured
    if text.startswith("\n"):
        text = text[1:]
    return text if text.endswith("\n") else text + "\n"


# ("ins", anchor, before, after): the anchor stays; `before` goes in front of it, `after` behind it.
# ("rep", old, new): old is replaced by new (new never holds old: the state test needs that).
# No edit splits an inserted block of r130b (its own state test counts each block whole).
EDITS = {}

# ---------------------------------------------------------------------------------------------------------------- layout
EDITS[LAY] = [
("ins", "#define CAUSTICS_FLAG_MOTION 512u\n", "",
 L(r"""
// bbport (r130e_sewer-water-moves): two more dispatches of this pass inside one Apply (the rippled reflection of a mirrored plane's
// water), both with CAUSTICS_FLAG_MOTION: WARP_COPY copies each water pixel's colour of the band into the copy image (binding 8),
// WARP takes it from a place moved along the wave field's slope and gives it a glint. Without these flags none of it runs.
#define CAUSTICS_FLAG_WARP_COPY 1024u
#define CAUSTICS_FLAG_WARP 2048u
""")),
("ins", "#define CAUSTICS_RING_R0 0.05\n", "",
 L(r"""
// bbport (r130e_sewer-water-moves): the rippled reflection. The four free words of the motion block: ROW0 the first row of the band
// (the host's WaterTopRow), WARP_PX and WARP_KEPT the water pixels the WARP dispatch took a colour for and those it left as they were
// (the shader adds, one atomicAdd a group; the host reads them before it rewrites the slot), STAMP the dispatch's number (1 to 2047,
// exact in half float): a copy texel counts only when its alpha holds it. The mirror image moves by 2 x REFLECT_M metres of the water
// plane for a slope of 1 (a look number: the physical 2 to 4 m would tear the image), projected, at most SHIFT_MAX x the frame's
// height in pixels. The glint: the colour times 1 + t, t = GLINT x strength x (Focus - 1) x lum / (lum + GLINT_KNEE) within
// +-GLINT_MAX (the focus has mean 1: light is moved, not added). The band starts ROW_MARGIN pixels above the first row the host's ray
// test puts water in (it steps ROW_STEP rows).
#define CAUSTICS_MOTION_ROW0 100
#define CAUSTICS_MOTION_WARP_PX 101
#define CAUSTICS_MOTION_WARP_KEPT 102
#define CAUSTICS_MOTION_STAMP 103
#define CAUSTICS_MOTION_REFLECT_M 0.25
#define CAUSTICS_MOTION_SHIFT_MAX 0.012
#define CAUSTICS_MOTION_GLINT 0.30
#define CAUSTICS_MOTION_GLINT_MAX 0.6
#define CAUSTICS_MOTION_GLINT_KNEE 0.05
#define CAUSTICS_MOTION_ROW_MARGIN 16
#define CAUSTICS_MOTION_ROW_STEP 8
""")),
]

# ---------------------------------------------------------------------------------------------------------------- shader
EDITS[COMP] = [
("ins", "// caustics_params.h Push, field for field (128 bytes).\n",
 L(r"""
// bbport (r130e_sewer-water-moves): the copy of the mirrored plane's water colours (the host binds the scene view as a stand-in
// when no warp runs; the shader touches it only under the two warp flags).
layout(binding = 8, rgba16f) uniform image2D warp_img;
"""), ""),
("ins", "shared uint group_ring; // r130b: the water pixels in this group a ring packet reached\n", "",
 L(r"""
shared uint group_warp[2]; // r130e: the water pixels this group's WARP threads took a colour for, and those they left as they were""")),
("ins", "void Shade(ivec2 p) {\n",
 L(r"""
// bbport (r130e_sewer-water-moves): the rippled reflection of a mirrored plane's water (see CAUSTICS_FLAG_WARP_COPY and _WARP).
// The pixel (centre, + 0.5) a view position projects to: ViewPos inverted.
vec2 PixelOf(vec3 v) {
    return (v.xy * proj.xy / max(v.z, 1e-4) + 1.0) * 0.5 * frame.xy + frame.zw;
}

// The game's water pixel at p: depth on the mirrored plane within the tolerance, up-facing, nearer than CAUSTICS_FADE_END (the water
// is drawn before this pass, so the plane test of the depth is its pixels). P, Pw: its view and world position.
bool WaterPixel(ivec2 p, out vec3 P, out vec3 Pw) {
    P = vec3(0.0);
    Pw = vec3(0.0);
    const float depth = texelFetch(depth_tex, p, 0).r;
    if (depth >= 1.0) {
        return false;
    }
    P = ViewPos(vec2(p) + 0.5, ViewZ(depth));
    if (!(P.z < CAUSTICS_FADE_END)) {
        return false;
    }
    Pw = ToWorld(P);
    if (abs(Pw.y - sun.w) > CAUSTICS_WATER_M + CAUSTICS_WATER_REL * P.z) {
        return false;
    }
    return DirToWorld(NormalAt(p, P)).y >= CAUSTICS_PUDDLE_UP;
}

// One thread of the WARP_COPY or WARP dispatch: g is its place in the band (the band starts at the block's ROW0).
void WarpPixel(ivec2 g) {
    const ivec2 p = ivec2(g.x, g.y + int(Motion(CAUSTICS_MOTION_ROW0)));
    if (any(greaterThanEqual(p, ivec2(frame.xy)))) {
        return;
    }
    vec3 P, Pw;
    if (!WaterPixel(p, P, Pw)) {
        return;
    }
    const float stamp = float(Motion(CAUSTICS_MOTION_STAMP));
    const vec4 s = imageLoad(scene_img, p);
    if ((flags & CAUSTICS_FLAG_WARP_COPY) != 0u) {
        imageStore(warp_img, p, vec4(s.rgb, stamp));
        return;
    }
    // The mirror image moves by 2 x REFLECT_M x the slope (a tilt t turns the reflected ray by 2 t): project the point and the point
    // moved on the plane, the difference is the shift (faded out with distance, at most SHIFT_MAX x the frame's height).
    vec2 slope;
    const float lap = WaveAt(Pw.xz, slope);
    const float fade = 1.0 - smoothstep(CAUSTICS_FADE_START, CAUSTICS_FADE_END, P.z);
    const vec3 V2 = ToView(Pw + (2.0 * CAUSTICS_MOTION_REFLECT_M) * vec3(slope.x, 0.0, slope.y));
    vec2 shift = V2.z > 0.05 ? (PixelOf(V2) - PixelOf(P)) * fade : vec2(0.0);
    const float lim = CAUSTICS_MOTION_SHIFT_MAX * frame.y;
    const float len = length(shift);
    if (len > lim) {
        shift *= lim / len;
    }
    // Bilinear over the four copy texels that hold this dispatch's stamp.
    const vec2 q = vec2(p) + shift;
    const ivec2 q0 = ivec2(floor(q));
    const vec2 f = q - vec2(q0);
    vec3 sum = vec3(0.0);
    float wsum = 0.0;
    for (int j = 0; j < 2; ++j) {
        for (int i = 0; i < 2; ++i) {
            const ivec2 t = q0 + ivec2(i, j);
            if (any(lessThan(t, ivec2(0))) || any(greaterThanEqual(t, ivec2(frame.xy)))) {
                continue;
            }
            const vec4 c = imageLoad(warp_img, t);
            if (abs(c.a - stamp) > 0.25) {
                continue;
            }
            const float w = (i == 0 ? 1.0 - f.x : f.x) * (j == 0 ? 1.0 - f.y : f.y);
            sum += w * c.rgb;
            wsum += w;
        }
    }
    vec3 rgb = s.rgb;
    atomicAdd(group_warp[0], 1u);
    if (wsum >= 0.5) {
        rgb = sum / wsum;
    } else {
        atomicAdd(group_warp[1], 1u); // kept: the source is not water
    }
    // The glint: bright reflections sparkle, dark water does not; the focus has mean 1 (light moved, not added); it follows the knob.
    const float lum = dot(max(rgb, vec3(0.0)), LUMA);
    const float strength = uintBitsToFloat(Motion(CAUSTICS_MOTION_STRENGTH));
    const float t = clamp(CAUSTICS_MOTION_GLINT * strength * (Focus(lap) - 1.0) * (lum / (lum + CAUSTICS_MOTION_GLINT_KNEE)),
                          -CAUSTICS_MOTION_GLINT_MAX, CAUSTICS_MOTION_GLINT_MAX) * fade;
    imageStore(scene_img, p, vec4(rgb * (1.0 + t), s.a));
}

"""),
 L(r"""
    if ((flags & (CAUSTICS_FLAG_WARP_COPY | CAUSTICS_FLAG_WARP)) != 0u) {
        WarpPixel(p); // r130e: the thread's place in the band
        return;
    }""")),
("ins", "    barrier();\n    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);\n",
 L(r"""
    if ((flags & (CAUSTICS_FLAG_WARP_COPY | CAUSTICS_FLAG_WARP)) != 0u && gl_LocalInvocationIndex == 0u) {
        group_warp[0] = 0u; // r130e
        group_warp[1] = 0u;
    }"""), ""),
("ins", "        atomicAdd(counts[CAUSTICS_MOTION_BASE + slot * CAUSTICS_MOTION_WORDS + CAUSTICS_MOTION_RING_PX], group_ring);\n    }\n",
 "",
 L(r"""
    if ((flags & CAUSTICS_FLAG_WARP) != 0u && gl_LocalInvocationIndex == 0u && (group_warp[0] | group_warp[1]) != 0u) {
        // r130e: the water pixels the warp took a colour for and those it kept, to the slot's motion block
        atomicAdd(counts[CAUSTICS_MOTION_BASE + slot * CAUSTICS_MOTION_WORDS + CAUSTICS_MOTION_WARP_PX], group_warp[0]);
        atomicAdd(counts[CAUSTICS_MOTION_BASE + slot * CAUSTICS_MOTION_WORDS + CAUSTICS_MOTION_WARP_KEPT], group_warp[1]);
    }""")),
]

# ---------------------------------------------------------------------------------------------------------------- params
EDITS[PAR] = [
("ins", "} // namespace BbCaustics\n",
 L(r"""
// bbport (r130e_sewer-water-moves): the rippled reflection of a mirrored plane's water (caustics.comp WarpPixel). The host's part:
// the band of rows (WaterTopRow), the dispatch's stamp, the bed light's rule and when the motion runs alone. The twins of the shader's
// shift (ShiftPx) and glint (GlintOf), in float, for the test. Off (strength 0): Alone is false, WorldFor is the variable's value.
namespace Motion::Warp {

inline constexpr std::uint32_t FlagCopy = CAUSTICS_FLAG_WARP_COPY, FlagWarp = CAUSTICS_FLAG_WARP;
inline constexpr std::uint32_t RowMargin = CAUSTICS_MOTION_ROW_MARGIN, RowStep = CAUSTICS_MOTION_ROW_STEP;
inline constexpr float ReflectM = CAUSTICS_MOTION_REFLECT_M, ShiftMax = CAUSTICS_MOTION_SHIFT_MAX;
inline constexpr float Glint = CAUSTICS_MOTION_GLINT, GlintMax = CAUSTICS_MOTION_GLINT_MAX, GlintKnee = CAUSTICS_MOTION_GLINT_KNEE;
/// The bed light's strength when the motion starts it (BB_CAUSTICS_WORLD unset), as the variable "1".
inline constexpr float BedAuto = 1.0f;
/// The stamps run 1 to StampCount: exact in half float (the copy image's alpha).
inline constexpr std::uint32_t StampCount = 2047;
/// The log lines' tag (kept out of vk_caustics.cpp's text: r130b's own check refuses any other line there that holds r130b's tag).
inline constexpr const char* LogTag = "Water motion (r130e)";
static_assert(FlagCopy == 1024u && FlagWarp == 2048u && ((FlagCopy | FlagWarp) & CAUSTICS_FLAG_MOTION) == 0u &&
              (FlagCopy & FlagWarp) == 0u);
static_assert(CAUSTICS_MOTION_RINGS_AT + CAUSTICS_MOTION_MAX_RINGS * CAUSTICS_MOTION_RING_WORDS <= CAUSTICS_MOTION_ROW0 &&
              CAUSTICS_MOTION_ROW0 < CAUSTICS_MOTION_WARP_PX && CAUSTICS_MOTION_WARP_PX < CAUSTICS_MOTION_WARP_KEPT &&
              CAUSTICS_MOTION_WARP_KEPT < CAUSTICS_MOTION_STAMP && CAUSTICS_MOTION_STAMP < CAUSTICS_MOTION_WORDS);
static_assert(StampCount <= 2048u && CAUSTICS_MOTION_GLINT_KNEE > 0.0 && CAUSTICS_MOTION_GLINT_MAX < 1.0);

/// The dispatch's stamp from its number: 1 to StampCount.
inline std::uint32_t Stamp(std::uint32_t dispatch) {
    return dispatch % StampCount + 1u;
}

/// The first row of the band: casts rays at x = 0, w / 2, w - 1 down the rows in RowStep steps and takes the first row where one
/// meets the water plane (world y `plane_y`) nearer than CAUSTICS_FADE_END, minus RowMargin; `h`: none (the camera is not above the
/// plane, or no ray meets it that near). The rays use the push's matrices as the shader's ViewPos and ToWorld.
inline std::uint32_t WaterTopRow(const Push& push, float plane_y, std::uint32_t w, std::uint32_t h) {
    const auto& m = push.inv_view;
    const float cam_y = m[7];
    if (w == 0 || h == 0 || !std::isfinite(plane_y) || !std::isfinite(cam_y) || !(cam_y > plane_y) || !(push.proj[0] != 0.0f) ||
        !(push.proj[1] != 0.0f)) {
        return h;
    }
    const std::array<float, 3> columns{0.5f, 0.5f * float(w), float(w) - 0.5f};
    for (std::uint32_t y = 0; y < h; y += RowStep) {
        const float ndc_y = ((float(y) + 0.5f) - push.frame[3]) / float(h) * 2.0f - 1.0f;
        for (const float cx : columns) {
            const float ndc_x = (cx - push.frame[2]) / float(w) * 2.0f - 1.0f;
            const float vx = ndc_x / push.proj[0], vy = ndc_y / push.proj[1]; // the ray in the view, view z 1
            const float dir_y = m[4] * vx + m[5] * vy + m[6];
            if (dir_y < -1e-6f && (plane_y - cam_y) / dir_y < float(CAUSTICS_FADE_END)) { // t = view z
                return y > RowMargin ? y - RowMargin : 0u;
            }
        }
    }
    return h;
}

inline float SmoothStep(float a, float b, float x) {
    const float t = std::clamp((x - a) / (b - a), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

/// World to view: the shader's ToView (the view to world rotation's transpose after taking off the camera's position).
inline std::array<float, 3> ToViewOf(const Push& push, const std::array<float, 3>& w) {
    const auto& m = push.inv_view;
    const float dx = w[0] - m[3], dy = w[1] - m[7], dz = w[2] - m[11];
    return {m[0] * dx + m[4] * dy + m[8] * dz, m[1] * dx + m[5] * dy + m[9] * dz, m[2] * dx + m[6] * dy + m[10] * dz};
}

/// The pixel (centre, + 0.5) a view position projects to: the shader's PixelOf.
inline std::array<float, 2> PixelOf(const Push& push, const std::array<float, 3>& v) {
    const float z = std::max(v[2], 1e-4f);
    return {(v[0] * push.proj[0] / z + 1.0f) * 0.5f * push.frame[0] + push.frame[2],
            (v[1] * push.proj[1] / z + 1.0f) * 0.5f * push.frame[1] + push.frame[3]};
}

/// The pixel shift of the reflection at the water point `world` (the shader's): the point moved on the plane by 2 x ReflectM x the
/// slope (gx, gz), projected, times the distance fade, its length at most ShiftMax x the frame's height. Zero behind the camera.
inline std::array<float, 2> ShiftPx(const Push& push, const std::array<float, 3>& world, float gx, float gz) {
    const auto v = ToViewOf(push, world);
    const auto v2 = ToViewOf(push, {world[0] + 2.0f * ReflectM * gx, world[1], world[2] + 2.0f * ReflectM * gz});
    if (!(v2[2] > 0.05f)) {
        return {0.0f, 0.0f};
    }
    const auto a = PixelOf(push, v), b = PixelOf(push, v2);
    const float fade = 1.0f - SmoothStep(float(CAUSTICS_FADE_START), float(CAUSTICS_FADE_END), v[2]);
    std::array<float, 2> s{(b[0] - a[0]) * fade, (b[1] - a[1]) * fade};
    const float lim = ShiftMax * push.frame[1], len = std::hypot(s[0], s[1]);
    if (len > lim) {
        s[0] *= lim / len;
        s[1] *= lim / len;
    }
    return s;
}

/// The glint's factor on a colour of luminance `lum` where the wave field's curvature is `lap` (the shader's): 1 + t, t = Glint x
/// strength x (Focus - 1) x lum / (lum + GlintKnee) within +-GlintMax, times `fade`. It follows the knob; the focus has mean 1.
inline float GlintOf(float lap, float lum, float strength, float fade = 1.0f) {
    const float l = std::max(lum, 0.0f);
    const float t = std::clamp(Glint * strength * (Focus(lap) - 1.0f) * (l / (l + GlintKnee)), -GlintMax, GlintMax) * fade;
    return 1.0f + t;
}

/// The bed light's strength (the world map): the variable's value when it is set and not empty (also 0), else BedAuto while the
/// motion and the lamps' strength are above 0, else the variable's value (0 when unset: nothing new).
inline float WorldFor(bool env_set, float env, float motion, float lamps) {
    if (env_set) {
        return env;
    }
    return motion > 0.0f && lamps > 0.0f ? BedAuto : env;
}

/// The motion runs alone (a dispatch of its own, kind 1) when it is on, a mirrored plane is found, the camera is above it and
/// neither caustics draw this pass.
inline bool Alone(float motion, bool plane, bool camera_above, bool draw, bool lamp_draw) {
    return motion > 0.0f && std::isfinite(motion) && plane && camera_above && !draw && !lamp_draw;
}

} // namespace Motion::Warp

"""), ""),
]

# ---------------------------------------------------------------------------------------------------------------- vk_caustics.h
EDITS[VH] = [
("ins", "    bool motion_env = false;\n", "",
 L(r"""
    // bbport (r130e_sewer-water-moves): the copy of the water's colours (RGBA16F, the scene's size; made at the first warp, remade
    // on a size change), whether the copy's contents were cleared, the world map's maker, the bed light's lines
    struct WarpImage {
        VideoCore::UniqueImage image;
        vk::UniqueImageView view;
        u32 width = 0, height = 0;
        bool cleared = false;
    } warp;
    bool world_env_set = false; ///< r130e: BB_CAUSTICS_WORLD is set and not empty (it decides the bed light, also 0)
    bool world_tried = false;   ///< r130e: the world map was tried (once)
    bool EnsureWarpImage(u32 width, u32 height);
    bool MakeWorldMap();""")),
("ins", "        bool hunter_read = false;                           ///< r130b: the last frame's position read worked\n", "",
 L(r"""
        u32 warp_dispatches = 0, motion_only = 0, warp_reads = 0; ///< r130e: warp dispatches, those alone, those whose counts were read
        u64 warp_px = 0, warp_kept = 0;                           ///< r130e: the water pixels warped and those kept, summed over the reads
        u64 warp_rows = 0, warp_height = 0;                       ///< r130e: the band's rows and the frames' rows, summed""")),
("ins", "    u32 motion_changes = 0;   ///< r130b: Refresh found another strength\n", "",
 L(r"""
    bool told_warp = false, told_bed = false, warp_failed = false; ///< r130e: the first warp, the bed light and a failed copy were said""")),
]

# ---------------------------------------------------------------------------------------------------------------- vk_caustics.cpp
EDITS[VC_CPP] = [
("ins", "} // namespace\n\n// bbport (r128b_lrt-caustics-water): the setting's numbers are the header's",
 L(r"""
// bbport (r130e_sewer-water-moves): the copy image's one level
constexpr vk::ImageSubresourceRange WarpLevel{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
"""), ""),
("rep",
 "                               SampledImage, SampledImage, StorageBuffer},\n",
 "                               SampledImage, SampledImage, StorageBuffer, StorageImage}, // r130e: binding 8, the copy\n"),
("rep",
 "    return k.strength > 0.0f || k.lamp_strength > 0.0f;\n",
 "    return k.strength > 0.0f || k.lamp_strength > 0.0f || MotionNow().strength > 0.0f; // r130e: the motion alone\n"),
("ins", "}\n\nvoid Caustics::Refresh() {\n",
 L(r"""
    // bbport (r130e_sewer-water-moves): with the motion on and both caustics strengths 0 the line above (r130b's) says nothing moves:
    // the reflection still ripples, only the net is not drawn
    static StrengthKnob::Line warp_line;
    if (moving.strength > 0.0f && !(sun.value > 0.0f || lamps.value > 0.0f) && warp_line.Due(LineCalls, motion_value)) {
        std::printf("%s: strength %.2f with both caustics strengths 0: no net is drawn, but the water's reflection still ripples "
                    "(warp, glint, shimmer); the line above that says nothing moves is out of date\n",
                    BC::Motion::Warp::LogTag, double(moving.strength));
    }"""), ""),
("ins", "        knobs.lamp_strength = now.lamp_strength;\n    }\n", "",
 L(r"""
    {   // bbport (r130e_sewer-water-moves): the bed light follows the motion (a set BB_CAUSTICS_WORLD wins); the map is made when first needed
        knobs.world = BC::Motion::Warp::WorldFor(world_env_set, ReadKnobs().world, motion_strength, knobs.lamp_strength);
        if (knobs.world > 0.0f && knobs.lamp_strength > 0.0f && made && !world_map.buffer && !world_tried) {
            const bool made_map = MakeWorldMap();
            if (!told_bed && !world_env_set) {
                told_bed = true;
                std::printf("%s: the lamps' light on the bed under the water (r107f) runs with the motion; world map %u KB %s\n",
                            BC::Motion::Warp::LogTag, unsigned(WorldBytes / 1024), made_map ? "made" : "could not be made");
            }
        }
    }""")),
("rep",
 L(r"""
    if (made && knobs.world > 0.0f && knobs.lamp_strength > 0.0f) {
        // bbport (r107f_caustics-world-anchored): the world map, device local; the first dispatch
        // that uses it clears it. Without it the knob does nothing (the log says so).
        const VkBufferCreateInfo map_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = WorldBytes,
            .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        VmaAllocationCreateInfo map_alloc{};
        map_alloc.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE;
        VkBuffer map_raw{};
        if (vmaCreateBuffer(instance.GetAllocator(), &map_ci, &map_alloc, &map_raw,
                            &world_map.allocation, nullptr) == VK_SUCCESS) {
            world_map.buffer = map_raw;
        }
    }
"""),
 L(r"""
    world_env_set = EnvSet("BB_CAUSTICS_WORLD"); // r130e
    if (made && knobs.world > 0.0f && knobs.lamp_strength > 0.0f) {
        MakeWorldMap(); // r107f, from the variable (r130e: the body is in MakeWorldMap)
    }
""")),
("ins", "Caustics::~Caustics() {\n",
 L(r"""
// bbport (r107f_caustics-world-anchored), moved here by r130e_sewer-water-moves: the world map, device local; the first dispatch that
// uses it clears it. Without it the knob does nothing (the log says so). Tried once.
bool Caustics::MakeWorldMap() {
    world_tried = true;
    if (!made || world_map.buffer) {
        return bool(world_map.buffer);
    }
    const VkBufferCreateInfo map_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = WorldBytes,
        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
    };
    VmaAllocationCreateInfo map_alloc{};
    map_alloc.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE;
    VkBuffer map_raw{};
    if (vmaCreateBuffer(instance.GetAllocator(), &map_ci, &map_alloc, &map_raw, &world_map.allocation, nullptr) == VK_SUCCESS) {
        world_map.buffer = map_raw;
    }
    return bool(world_map.buffer);
}

// bbport (r130e_sewer-water-moves): the copy of the water's colours: RGBA16F, the scene's size (8 B a pixel), storage and clear use,
// device local, in General; made at the first warp and remade on a size change (the old one goes when the GPU is done with it).
// False: no room or no storage use of the format (the warp is off, r130b's shimmer still runs).
bool Caustics::EnsureWarpImage(u32 width, u32 height) {
    if (warp.image && warp.width == width && warp.height == height) {
        return true;
    }
    if (warp.image) {
        scheduler.DeferOperation([image = std::move(warp.image), view = std::move(warp.view)]() mutable {
            view.reset();
            image.Destroy();
        });
    }
    warp.width = warp.height = 0;
    warp.cleared = false;
    if (!EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) || !EffectPass::HasRoom(instance, 8ull * width * height)) {
        return false;
    }
    const auto device = instance.GetDevice();
    const vk::ImageCreateInfo image_ci{
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eTransferDst,
        .initialLayout = vk::ImageLayout::eUndefined,
    };
    warp.image = VideoCore::UniqueImage(device, instance.GetAllocator());
    warp.image.Create(image_ci);
    SetObjectName(device, vk::Image(warp.image), "Water warp copy");
    warp.view = Check<"create water warp copy view">(device.createImageViewUnique({
        .image = vk::Image(warp.image),
        .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .subresourceRange = WarpLevel,
    }));
    warp.width = width;
    warp.height = height;
    return true;
}

"""), ""),
("rep",
 "    if (!SunWanted() && !LampsWanted() && !knobs.show) { // bbport (r128b_lrt-caustics-water)\n",
 "    if (!SunWanted() && !LampsWanted() && !knobs.show && !(motion_strength > 0.0f)) { // bbport (r128b_lrt-caustics-water), r130e: the motion alone\n"),
("rep",
 "    if (!draw && !lamp_draw && !knobs.show && !puddle) { // r107e: puddles measure every pass\n",
 L(r"""
    // bbport (r130e_sewer-water-moves): the motion alone: a plane, the camera above it, neither caustics drawing: a dispatch of its own
    const bool motion_only = BC::Motion::Warp::Alone(motion_strength, plane, camera.valid && camera.inv_view[7] >= plane_y, draw, lamp_draw);
    if (!draw && !lamp_draw && !knobs.show && !puddle && !motion_only) { // r107e: puddles measure every pass
""")),
("rep",
 "    if ((!draw && !lamp_draw && !material) || width < 16 || height < 16) {\n",
 "    if ((!draw && !lamp_draw && !material && !motion_only) || width < 16 || height < 16) { // r130e: motion_only\n"),
("rep",
 "    if (!draw && !lamp_draw && !material_view) {\n",
 "    if (!draw && !lamp_draw && !material_view && !motion_only) { // r130e: motion_only\n"),
("ins", "        stats.puddle_lamps += lamp_draw ? 1 : 0;\n    }\n", "",
 L(r"""
    if (motion_strength > 0.0f && (draw || lamp_draw || puddle_pass || motion_only)) {
        // bbport (r130e_sewer-water-moves): the last use of this slot's warp counts (the motion block is rewritten below)
        const u32* last = static_cast<const u32*>(counters.mapped) + BC::Motion::Base + push.slot * BC::Motion::Words;
        if (last[CAUSTICS_MOTION_WARP_PX] != 0u) {
            stats.warp_px += last[CAUSTICS_MOTION_WARP_PX];
            stats.warp_kept += last[CAUSTICS_MOTION_WARP_KEPT];
            ++stats.warp_reads;
        }
    }""")),
("ins", "    slot_camera_y[push.slot] = camera.inv_view[7];\n",
 L(r"""
    // bbport (r130e_sewer-water-moves): the rippled reflection. A motion-only dispatch writes its own motion block (kind 1: r130b's
    // block above ran only for a dispatch that draws or measures); a mirrored plane's moving dispatch then gets its band, the copy
    // image and the stamp (the block's ROW0 and STAMP words). Nothing of this runs with the motion off (the flag is 0).
    bool warp_on = false, warp_clear = false;
    u32 warp_row0 = 0;
    if (motion_only) {
        u32* block = static_cast<u32*>(counters.mapped) + BC::Motion::Base + push.slot * BC::Motion::Words;
        stats.ring_px += block[CAUSTICS_MOTION_RING_PX];
        BC::Motion::WriteBlock(block, motion, 1u, motion_strength);
        push.flags |= BC::Motion::FlagMotion;
        ++stats.motion_dispatches;
        ++stats.motion_only;
    }
    if ((push.flags & BC::Motion::FlagMotion) != 0u && plane && (draw || lamp_draw || motion_only)) {
        const u32 row0 = BC::Motion::Warp::WaterTopRow(push, plane_y, width, height);
        if (row0 < height && !warp_failed) {
            warp_on = EnsureWarpImage(width, height);
            if (!warp_on) {
                warp_failed = true;
                std::printf("%s: the copy image %ux%u could not be made: no rippled reflection (the shimmer still runs)\n",
                            BC::Motion::Warp::LogTag, width, height);
            }
        }
        if (warp_on) {
            u32* block = static_cast<u32*>(counters.mapped) + BC::Motion::Base + push.slot * BC::Motion::Words;
            block[CAUSTICS_MOTION_ROW0] = row0;
            block[CAUSTICS_MOTION_STAMP] = BC::Motion::Warp::Stamp(dispatches);
            warp_row0 = row0;
            warp_clear = !warp.cleared;
            warp.cleared = true;
            ++stats.warp_dispatches;
            stats.warp_rows += height - row0;
            stats.warp_height += height;
            if (!told_warp) {
                told_warp = true;
                std::printf("%s: first rippled reflection at frame %llu: plane y %.2f, rows %u-%u of %u (%.0f%%), copy %ux%u RGBA16F "
                            "(%.1f MB), reflect %.2f m, shift at most %.1f px, glint %.2f a unit of strength (now %.2f)\n",
                            BC::Motion::Warp::LogTag,
                            static_cast<unsigned long long>(BbStats::frame_number.load(std::memory_order_relaxed)), double(plane_y),
                            row0, height, height, 100.0 * double(height - row0) / double(height), width, height,
                            8.0 * double(width) * double(height) / 1048576.0, double(BC::Motion::Warp::ReflectM),
                            double(BC::Motion::Warp::ShiftMax) * double(height), double(BC::Motion::Warp::Glint),
                            double(motion_strength));
            }
        }
    }
"""), ""),
("rep",
 "    stats.shown += draw || lamp_draw || puddle_pass ? 0 : 1; // r107e: a puddle pass is no test view\n",
 "    stats.shown += draw || lamp_draw || puddle_pass || motion_only ? 0 : 1; // r107e: a puddle pass is no test view; r130e: nor a lone motion\n"),
("rep",
 "         pass_layout = *layout](vk::CommandBuffer cmdbuf) {\n",
 L(r"""
         pass_layout = *layout, warp_on, warp_clear, warp_row0, // r130e: the copy image of the rippled reflection
         warp_handle = warp_on ? vk::Image(warp.image) : vk::Image{},
         warp_bound = warp_on ? *warp.view : color_view](vk::CommandBuffer cmdbuf) {
""")),
("rep",
 "                                   Info(bound_material), Info(bound_albedo), Info(bound_records)};\n",
 "                                   Info(bound_material), Info(bound_albedo), Info(bound_records), Info(warp_bound)};\n"),
("rep",
 "                                                           .pBufferInfo = &world_info}};\n",
 L(r"""
                                                           .pBufferInfo = &world_info},
                                    Write(8, StorageImage, &infos[6])}; // r130e: the copy image (the scene view as a stand-in)
""")),
("ins", "            if (clear_map) {\n",
 L(r"""
            if (warp_clear) { // bbport (r130e_sewer-water-moves): the copy image's first use (made or remade): General and a clear
                              // to 0 (no stamp is 0) before the first dispatch binds it (binding 8); the barrier below orders it
                const vk::ImageMemoryBarrier2 to_clear{
                    .srcStageMask = vk::PipelineStageFlagBits2::eTopOfPipe,
                    .dstStageMask = vk::PipelineStageFlagBits2::eAllTransfer,
                    .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
                    .oldLayout = vk::ImageLayout::eUndefined, .newLayout = vk::ImageLayout::eGeneral,
                    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .image = warp_handle, .subresourceRange = WarpLevel};
                cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_clear});
                cmdbuf.clearColorImage(warp_handle, vk::ImageLayout::eGeneral,
                                       vk::ClearColorValue{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}}, WarpLevel);
            }"""), ""),
("ins", "(height + BC::Group - 1) / BC::Group,\n                            1);\n", "",
 L(r"""
            if (warp_on) { // bbport (r130e_sewer-water-moves): the copy, then the warp, over the band of rows
                // the normal dispatch's writes before the copy reads the scene
                EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute, ReadWrite);
                const u32 band_rows = height - warp_row0;
                BC::Push warp_push = push;
                warp_push.flags = BC::Motion::FlagMotion | BC::Motion::Warp::FlagCopy;
                cmdbuf.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(warp_push), &warp_push);
                cmdbuf.dispatch((width + BC::Group - 1) / BC::Group, (band_rows + BC::Group - 1) / BC::Group, 1);
                EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite, Compute, ReadWrite);
                warp_push.flags = BC::Motion::FlagMotion | BC::Motion::Warp::FlagWarp;
                cmdbuf.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(warp_push), &warp_push);
                cmdbuf.dispatch((width + BC::Group - 1) / BC::Group, (band_rows + BC::Group - 1) / BC::Group, 1);
            }""")),
("ins", "    // bbport (r128b_lrt-caustics-water): the strengths now and how often the setting moved them\n",
 L(r"""
    // bbport (r130e_sewer-water-moves): the rippled reflection (means over the dispatches whose counts were read)
    if (motion_strength > 0.0f || stats.warp_dispatches != 0) {
        const double warps = std::max(1.0, double(stats.warp_reads));
        char bed[80];
        if (world_env_set) {
            std::snprintf(bed, sizeof(bed), "from BB_CAUSTICS_WORLD=%.2f", double(knobs.world));
        } else {
            std::snprintf(bed, sizeof(bed), "%s", knobs.world > 0.0f ? "on with the motion (BB_CAUSTICS_WORLD unset)" : "off");
        }
        BbReport::Printf("%s: %u warp dispatches, %u motion-only; a dispatch: %.0f water px warped, %.0f kept (source not water), "
                         "band %.0f%% of rows; bed light %s\n",
                         BC::Motion::Warp::LogTag, stats.warp_dispatches, stats.motion_only, double(stats.warp_px) / warps,
                         double(stats.warp_kept) / warps,
                         100.0 * double(stats.warp_rows) / std::max(1.0, double(stats.warp_height)), bed);
    }
"""), ""),
]

# ---------------------------------------------------------------------------------------------------------------- tests
EDITS[TC] = [
("ins", '    std::printf("caustics: ok',
 L(r"""
    // bbport (r130e_sewer-water-moves): the rippled reflection: the band, the shift, the glint, the stamp, the bed light's rule, the
    // lone motion.
    {
        namespace M = Motion;
        namespace W = Motion::Warp;
        static_assert(W::FlagCopy == 1024u && W::FlagWarp == 2048u && W::StampCount == 2047u);
        static_assert(CAUSTICS_MOTION_ROW0 == 100 && CAUSTICS_MOTION_STAMP == 103 && CAUSTICS_MOTION_WORDS == 104);
        // a camera (1080p, 60 degrees vertical, view y up on screen: proj y < 0 as the engine's) `above` the plane y = 0, pitched down
        const auto camera = [](float above, float pitch_deg) {
            Push p{};
            const float rad = pitch_deg * 3.14159265f / 180.0f, c = std::cos(rad), s = std::sin(rad);
            p.proj = {0.974f, -1.732f, 0.0f, 0.0f};
            p.frame = {1920.0f, 1080.0f, 0.0f, 0.0f};
            p.inv_view = {1.0f, 0.0f, 0.0f, 0.0f, 0.0f, c, -s, above, 0.0f, s, c, 0.0f};
            return p;
        };
        // WaterTopRow: level, 1.07 m above the plane: the plane is within 45 m from 1.07 / 45 below the horizon (row 540 + 22),
        // minus the margin 16, on the 8 row grid
        {
            const std::uint32_t level = W::WaterTopRow(camera(1.07f, 0.0f), 0.0f, 1920, 1080);
            const double expect = 540.0 + 540.0 * (1.07 / 45.0) * 1.732 - 16.0;
            assert(std::fabs(double(level) - expect) <= 12.0 && (level + 16u) % 8u == 0u);
            assert(W::WaterTopRow(camera(1.07f, 60.0f), 0.0f, 1920, 1080) == 0u);      // looking down: every row is in range
            assert(W::WaterTopRow(camera(-1.0f, 0.0f), 0.0f, 1920, 1080) == 1080u);    // the plane above the camera: none
            assert(W::WaterTopRow(camera(1.07f, -40.0f), 0.0f, 1920, 1080) == 1080u);  // looking up 40 degrees: all above the horizon
            assert(W::WaterTopRow(camera(1.07f, 0.0f), NAN, 1920, 1080) == 1080u);
            assert(W::WaterTopRow(camera(1.07f, 0.0f), 0.0f, 0, 1080) == 1080u);
            assert(W::WaterTopRow(camera(40.0f, 0.0f), 0.0f, 1920, 1080) == 1080u);    // 40 m up, level: no ray meets it within 45 m
        }
        // ShiftPx: slope 0 none; 0.05 along x at z 3 m: 2 x 0.25 x 0.05 = 0.025 m across, f 0.974 x 960 px: 7.79 px, under the clamp;
        // along z it moves the point away (a small step on screen); 1: clamped to 0.012 x 1080 px; 50 m away: faded out
        {
            const Push level = camera(1.07f, 0.0f);
            const auto none = W::ShiftPx(level, {0.0f, 0.0f, 3.0f}, 0.0f, 0.0f);
            assert(none[0] == 0.0f && none[1] == 0.0f);
            const auto across = W::ShiftPx(level, {0.0f, 0.0f, 3.0f}, 0.05f, 0.0f);
            assert(Near(across[0], 0.974f * 0.025f / 3.0f * 960.0f, 0.01f) && std::fabs(across[1]) < 1e-3f);
            const auto back = W::ShiftPx(level, {0.0f, 0.0f, 3.0f}, 0.0f, 0.05f);
            const float y0 = (1.07f * 1.732f / 3.0f + 1.0f) * 540.0f, y1 = (1.07f * 1.732f / 3.025f + 1.0f) * 540.0f;
            assert(std::fabs(back[0]) < 1e-3f && Near(back[1], y1 - y0, 0.01f) && back[1] < 0.0f);
            const auto big = W::ShiftPx(level, {0.0f, 0.0f, 3.0f}, 1.0f, 0.0f);
            assert(Near(std::hypot(big[0], big[1]), W::ShiftMax * 1080.0f, 1e-3f) && big[0] > 0.0f);
            const auto distant = W::ShiftPx(level, {0.0f, 0.0f, 50.0f}, 0.05f, 0.0f);
            assert(distant[0] == 0.0f && distant[1] == 0.0f);
            const auto behind = W::ShiftPx(level, {0.0f, 0.0f, -3.0f}, 0.05f, 0.0f);
            assert(behind[0] == 0.0f && behind[1] == 0.0f);
        }
        // Stamp: 1 to 2047, wraps; exact in half float (integers to 2048)
        {
            assert(W::Stamp(0) == 1u && W::Stamp(2046) == 2047u && W::Stamp(2047) == 1u && W::Stamp(4294967295u) >= 1u);
            for (std::uint32_t d = 0; d < 5000; ++d) {
                assert(W::Stamp(d) >= 1u && W::Stamp(d) <= 2047u && W::Stamp(d) != W::Stamp(d + 1u));
            }
        }
        // WorldFor: a set variable wins (also 0); else the bed starts with the motion and the lamps; else the variable's own value
        {
            assert(W::WorldFor(false, 0.0f, 2.0f, 4.0f) == W::BedAuto && W::WorldFor(false, 0.0f, 0.0f, 4.0f) == 0.0f);
            assert(W::WorldFor(false, 0.0f, 2.0f, 0.0f) == 0.0f && W::WorldFor(false, 0.0f, NAN, 4.0f) == 0.0f);
            assert(W::WorldFor(true, 0.0f, 2.0f, 4.0f) == 0.0f && W::WorldFor(true, 2.5f, 0.0f, 0.0f) == 2.5f);
            assert(W::WorldFor(true, 0.5f, 2.0f, 4.0f) == 0.5f && W::WorldFor(false, 1.5f, 0.0f, 0.0f) == 1.5f);
        }
        // Alone: only with motion, a plane, the camera above it and nothing else drawing
        {
            assert(W::Alone(2.0f, true, true, false, false));
            assert(!W::Alone(0.0f, true, true, false, false) && !W::Alone(-1.0f, true, true, false, false) &&
                   !W::Alone(NAN, true, true, false, false) && !W::Alone(INFINITY, true, true, false, false));
            assert(!W::Alone(2.0f, false, true, false, false) && !W::Alone(2.0f, true, false, false, false));
            assert(!W::Alone(2.0f, true, true, true, false) && !W::Alone(2.0f, true, true, false, true));
        }
        // GlintOf: 1 with no strength, no luminance, no curvature; follows the knob; symmetric clamp; faded
        {
            assert(W::GlintOf(1.0f, 1.0f, 0.0f) == 1.0f && W::GlintOf(1.0f, 0.0f, 4.0f) == 1.0f && W::GlintOf(0.0f, 1.0f, 4.0f) == 1.0f);
            assert(W::GlintOf(-1.0f, 1.0f, 2.0f) > 1.0f && W::GlintOf(1.0f, 1.0f, 2.0f) < 1.0f); // a hollow brightens, a crest dims
            assert(W::GlintOf(-1.0f, 1.0f, 4.0f) - 1.0f > 1.9f * (W::GlintOf(-1.0f, 1.0f, 2.0f) - 1.0f));
            assert(W::GlintOf(-100.0f, 1.0f, 4.0f) == 1.0f + W::GlintMax && W::GlintOf(100.0f, 1.0f, 4.0f) == 1.0f - W::GlintMax);
            assert(W::GlintOf(-1.0f, 1.0f, 4.0f, 0.0f) == 1.0f);
            assert(std::fabs(W::GlintOf(-1.0f, 0.01f, 4.0f) - 1.0f) < std::fabs(W::GlintOf(-1.0f, 1.0f, 4.0f) - 1.0f)); // dark: less
        }
        // The glint's mean over a 4 x 4 m grid of the wave field (calm, windy, rings, four moments) stays 1 at strength 2 and 4, and
        // the swing on a bright reflection is clearly there: its rms at strength 2 and 4 (the calm field, the weakest)
        {
            double worst = 0.0, rms2 = 0.0, rms4 = 0.0, top = 0.0;
            for (const float strength : {2.0f, 4.0f}) {
                for (const float wind : {0.0f, 1.5f}) {
                    M::State s;
                    const float feet[6][3] = {{0.0f, 0.0f, 0.0f}, {0.8f, 0.0f, 0.1f}, {1.6f, 0.0f, 0.0f},
                                              {2.4f, 0.0f, 0.1f}, {3.2f, 0.0f, 0.0f}, {4.0f, 0.0f, 0.1f}};
                    for (int step = 0; step < 6; ++step) {
                        M::Observe(s, feet[step], strength);
                        for (int i = 0; i < 8; ++i) {
                            M::Advance(s, 0.05, {wind, 0.0f, 0.4f * wind}, strength);
                        }
                    }
                    for (int moment = 0; moment < 4; ++moment) {
                        for (int i = 0; i < 17; ++i) {
                            M::Advance(s, 0.05, {wind, 0.0f, 0.4f * wind}, strength);
                        }
                        std::uint32_t block[M::Words];
                        M::WriteBlock(block, s, 1, strength);
                        double sum = 0.0, sq = 0.0;
                        int n = 0;
                        for (int i = 0; i < 200; ++i) {
                            for (int j = 0; j < 200; ++j) {
                                const M::Sample v = M::Eval(block, 0.0207 * i, 0.0203 * j);
                                const double g = double(W::GlintOf(float(v.lap), 1.0f, strength)) - 1.0;
                                sum += g;
                                sq += g * g;
                                top = std::max(top, std::fabs(g));
                                ++n;
                            }
                        }
                        worst = std::max(worst, std::fabs(sum / n));
                        if (wind == 0.0f) {
                            (strength == 2.0f ? rms2 : rms4) += std::sqrt(sq / n) / 4.0;
                        }
                    }
                }
            }
            std::printf("water warp: glint mean off 1 by at most %.4f; swing on a bright reflection, calm field: rms %.3f at strength 2, "
                        "%.3f at 4, at most %.2f\n", worst, rms2, rms4, top);
            assert(worst < 0.03);
            assert(rms2 > 0.06 && rms4 > 1.5 * rms2 && top <= double(W::GlintMax) + 1e-6);
        }
    }
"""), ""),
]

ORDER = (LAY, COMP, PAR, VH, VC_CPP, TC)


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
    # r130b (on r107f and r128b) must be in the tree this patch is laid on
    need(LAY, texts[LAY], "#define CAUSTICS_FLAG_MOTION 512u\n")
    need(LAY, texts[LAY], "#define CAUSTICS_RING_R0 0.05\n")
    need(LAY, texts[LAY], "#define CAUSTICS_MOTION_WORDS 104\n")
    need(COMP, texts[COMP], "float WaveAt(vec2 xz, out vec2 g) {\n")
    need(COMP, texts[COMP], "shared uint group_ring;")
    need(PAR, texts[PAR], "namespace Motion {\n")
    need(VH, texts[VH], "::BbCaustics::Motion::State motion;")
    need(VC_CPP, texts[VC_CPP], "MotionIn MotionNow() {")
    need(VC_CPP, texts[VC_CPP], "BC::Motion::FlagsOf(motion_strength, draw || lamp_draw || puddle_pass)")
    need(TC, texts[TC], "bbport (r130b_water-moves): the moving water")


def texts_check(texts):
    lay, comp, par, vh, cpp, tc = (texts[p] for p in ORDER)
    # layout
    need(LAY, lay, "#define CAUSTICS_FLAG_WARP_COPY 1024u\n")
    need(LAY, lay, "#define CAUSTICS_FLAG_WARP 2048u\n")
    need(LAY, lay, "#define CAUSTICS_MOTION_ROW0 100\n")
    need(LAY, lay, "#define CAUSTICS_MOTION_STAMP 103\n")
    need(LAY, lay, "#define CAUSTICS_MOTION_WORDS 104\n")
    need(LAY, lay, "#define CAUSTICS_FLAG_MOTION 512u\n")
    # the shader: the binding, the helpers, the hand-over, the counters; r130b's counts of its own text stay (its check is run too)
    need(COMP, comp, "layout(binding = 8, rgba16f) uniform image2D warp_img;")
    need(COMP, comp, "shared uint group_warp[2];")
    need(COMP, comp, "void WarpPixel(ivec2 g) {\n")
    need(COMP, comp, "bool WaterPixel(ivec2 p, out vec3 P, out vec3 Pw) {\n")
    need(COMP, comp, "vec2 PixelOf(vec3 v) {\n")
    need(COMP, comp, "        WarpPixel(p); // r130e")
    need(COMP, comp, "(CAUSTICS_FLAG_WARP_COPY | CAUSTICS_FLAG_WARP)) != 0u", 2)
    need(COMP, comp, "CAUSTICS_FLAG_MOTION) != 0u", 4)   # r130b's four, none added
    need(COMP, comp, "barrier()", 2)                      # r130b's two, none added
    if not (0 <= comp.find("void Shade(ivec2 p) {") and comp.find("void WarpPixel(") < comp.find("void Shade(ivec2 p) {")
            < comp.find("WarpPixel(p); // r130e") < comp.find("void main() {")):
        raise SystemExit("text check: WarpPixel, Shade and the hand-over are out of order in caustics.comp")
    if not (0 <= comp.find("float WaveAt(") < comp.find("float Focus(") < comp.find("void WarpPixel(")):
        raise SystemExit("text check: WaveAt and Focus must come before WarpPixel in caustics.comp")
    if not (0 <= comp.find("group_ring = 0u; // r130b") < comp.find("group_warp[0] = 0u; // r130e") < comp.find("const ivec2 p = ivec2(gl_GlobalInvocationID")):
        raise SystemExit("text check: the group_warp clear is not between r130b's clear and the pixel in caustics.comp")
    # the params header
    need(PAR, par, "namespace Motion::Warp {\n")
    need(PAR, par, "} // namespace Motion::Warp\n")
    need(PAR, par, "inline std::uint32_t WaterTopRow(const Push& push, float plane_y, std::uint32_t w, std::uint32_t h) {")
    need(PAR, par, "inline bool Alone(")
    need(PAR, par, "inline float WorldFor(")
    need(PAR, par, "inline float GlintOf(")
    need(PAR, par, "inline std::array<float, 2> ShiftPx(")
    need(PAR, par, 'inline constexpr const char* LogTag = "Water motion (r130e)";')
    if not (0 <= par.find("} // namespace Motion\n") < par.find("namespace Motion::Warp {") < par.find("} // namespace BbCaustics")):
        raise SystemExit("text check: Warp is not between Motion and the end of the namespace in caustics_params.h")
    # the host
    need(VH, vh, "bool EnsureWarpImage(u32 width, u32 height);")
    need(VH, vh, "bool MakeWorldMap();")
    need(VH, vh, "bool told_warp = false, told_bed = false, warp_failed = false;")
    need(VC_CPP, cpp, "bool Caustics::EnsureWarpImage(u32 width, u32 height) {")
    need(VC_CPP, cpp, "bool Caustics::MakeWorldMap() {")
    need(VC_CPP, cpp, "StorageBuffer, StorageImage}")
    need(VC_CPP, cpp, "Write(8, StorageImage, &infos[6])")
    need(VC_CPP, cpp, "const bool motion_only = BC::Motion::Warp::Alone(")
    need(VC_CPP, cpp, "!motion_only", 3)
    need(VC_CPP, cpp, "BC::Motion::Warp::LogTag", 5)
    need(VC_CPP, cpp, "|| MotionNow().strength > 0.0f")
    need(VC_CPP, cpp, "world_env_set = EnvSet(")
    need(VC_CPP, cpp, "vmaCreateBuffer(instance.GetAllocator(), &map_ci", 1)
    # no line of vk_caustics.cpp may hold r130b's words except r130b's own three (its check refuses it); ours come from LogTag
    for line in cpp.split("\n"):
        if "Water motion" in line and "Water motion (r130b)" not in line:
            raise SystemExit("text check: a line holds the words of r130b's tag without it: %r" % line)
    if cpp.count("Water motion (r130e)") != 0:
        raise SystemExit("text check: vk_caustics.cpp must take its tag from LogTag")
    # the order of the Apply edits r130b's own check relies on, and the new block after r130b's
    if not (0 <= cpp.find("push.slot = dispatches % BC::Slots;") < cpp.find("last[CAUSTICS_MOTION_WARP_PX]")
            < cpp.find("push.flags |= motion_flag;") < cpp.find("bool warp_on = false, warp_clear = false;")
            < cpp.find("slot_camera_y[push.slot] = camera.inv_view[7];")):
        raise SystemExit("text check: the r130e blocks are not around r130b's motion block in vk_caustics.cpp")
    if not (cpp.find("const bool motion_only = ") < cpp.find("if (!draw && !lamp_draw && !knobs.show && !puddle && !motion_only)")
            < cpp.find("bool warp_on = false")):
        raise SystemExit("text check: motion_only must be defined before its first use in vk_caustics.cpp")
    if not (cpp.find("MakeWorldMap();") < cpp.find("bool Caustics::MakeWorldMap() {")):
        raise SystemExit("text check: MakeWorldMap must be defined after the constructor that calls it")
    # tests
    need(TC, tc, "bbport (r130e_sewer-water-moves): the rippled reflection")
    need(TC, tc, "bbport (r130b_water-moves): the moving water")
    if not (tc.find("bbport (r130b_water-moves): the moving water") < tc.find("bbport (r130e_sewer-water-moves)")
            < tc.find('std::printf("caustics: ok')):
        raise SystemExit("text check: the r130e test is not between r130b's and the final line")


def new_lines_check():
    # every new C++/GLSL line: no tab, ASCII, no em dash, at most 150 columns
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
        raise SystemExit("%s is not a source tree root (no engine/gpu; set R130E_ROOT)" % ROOT)
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
