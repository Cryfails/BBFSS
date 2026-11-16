# r92_lamp-shadow-colour: FEATURE patch (lamp work, owner's "layered shadows" photo, proposal R2 of
# the layered shadows study, steps A and B). Off by default behind BB_LAMP_SHADOW_COLOUR=1
# (environment, read once at start).
#
# Why: the owner's photo of a hand's shadow under a dim warm lamp with weak cool room light: soft
# layered bands, bluish inside the shadow. The ray traced lamp pass applied ONE grey ratio to the
# summed lamp light, so a blocked warm lamp left a darker copy of the mixed colour, never the cool
# lamp's colour. Owner (2026-11-15 20:08): "I would do all of those" (R1, R2, R3).
#
# What (point_shadow_ray.comp, only inside #ifdef COLOUR; the builds without COLOUR compile to the
# same SPIR-V words, proven on a copy):
#  - Per-channel weights: a lamp's weight times its record colour (words 4-6) over that colour's
#    luma (colourOf), so the luma of a lamp's channel weights is its grey weight. vec3 sums wsum_c
#    (first loop) and vsum_c; ratio per channel colour_rc = vsum_c / wsum_c (a channel without
#    weight: the grey ratio).
#  - Step A, the exact path (sharp, or LANTERN_RT_LAMPS_EXACT=1): every lamp its own ray; vsum_c
#    takes each lamp's part of vsum (vsum's step) in its colour. Without a history the answer goes
#    straight to the output.
#  - The pick (soft/softer, the default): the strongest lamp's part in its own colour, the picked
#    weaker lamp's answer for the summed channel weights of ALL weaker lamps (exact with one weaker
#    lamp, i.e. the photo's two lamps; with more, the weaker lamps' colours share the pick's
#    answer: bounded to 0..1 per channel and exactly 1 where every lamp lights the pixel; the
#    per-lamp unbiased form would let a channel swing far above 1 in one frame and put colour noise
#    into fully lit pixels).
#  - Step B, the history: the grey ratio stays what every guard takes (window, reject, follow,
#    trail, unsure); the colour is read at the SAME taps as the grey history (historyAt, both
#    places of the soft follow and their mix, or blendHistory for the vote) and blended with the
#    grey ratio's final share frames / (frames + 1) after every guard, so it is kept, shortened or
#    dropped where the grey history is; where the 5x5 window's bound moves the grey history (fitted),
#    the colour history is moved by the same amount in every channel (clamped to 0..1; r92 review:
#    the draft only shortened it, so a shadow the window had cleared kept its old hue for the frames
#    left, amplified by the output's rescale). The centred window's trace stores its colour answer for the
#    resolve; a half-resolution pixel that takes its block's ratio takes the block's colour (the
#    averaged one, or without averaging the first pass's answer); HalfAnswer also requires the 3x3
#    blocks' colours to agree within 1/64 as their ratios must, so the half build shows the colour
#    the full build shows (else blocks agreeing in grey but not in colour would carry one colour).
#  - Output: out = s + d * mix(1, colourScale(colour_rc, ratio, d0 + d1), strength * fade).
#    colourScale rescales colour_rc so the lamp light's luma (Rec. 601, weighted by the light) is
#    the grey ratio's, then moves it toward the grey ratio (same luma) until no channel exceeds 1.
#    So the luminance of the lamp light is exactly the grey pass's; only the hue changes, and only
#    where differently coloured lamps overlap with different visibility.
#  - One image (binding after each build's last: 11 plain, 12 centred/resolve, 13 half, 14 half
#    centred/half resolve), A2B10G10R10 unorm, three parts of the pass's size stacked: the colour
#    history pair (taken in turn with the history: history flags bit 16 HistoryColourOne) and the
#    pass's own colour answers (trace -> resolve; non-averaged half first pass -> second pass).
#    History flags bit 8 HistoryColourRead: the history read was written with its colour (a CARDS
#    pass or a resize in between: not read).
# Host (vk_point_shadow.cpp/.h): BB_LAMP_SHADOW_COLOUR=1 -> colour_mode at Ready: every lamp build
#   is made in its COLOUR form (6 new builds), the CARDS builds' layouts get the extra binding (so
#   set 0 stays compatible with the COLOUR resolve build), Flush makes the colour image (12 B/px),
#   sets tuning word 0 bit 25 (LampTuneColour) on a pass that runs a COLOUR build with the image
#   at its size, sets the two history flag bits, pushes the extra binding. CARDS passes stay grey.
# lamp_shadow_tune.h: LampShadowTune::colour, read in ReadLampShadowTune; LampTuneColour (bit 25,
#   static_assert free of every bit used and of r91's 24 and r93's 26); LampColourScale (the CPU
#   copy of colourScale). Test: test_lamp_shadow_tune.cpp. README row. CMakeLists: 6 builds.
#
# Off (default): the knob is 0 -> colour_mode false -> the same pipelines from the same SPIR-V
#   (byte-identical, the COLOUR builds are never made), no image, the same descriptor pushes and
#   data words: the picture is bit-identical. CPU: a few tests per pass and one 13-entry array copy.
# Log: once at start "Ray traced lamps (r92): coloured lamp shadows on|off - ..." (only with the
#   knob set); at each colour image make "Ray traced lamps (r92): the colour image, WxH ..."; right
#   after each 600-frame "Ray traced lamps (r42): ... lamp records ..." line, a short line of its own
#   "Ray traced lamps (r92): N ray traced lamp passes shadowed in colour since the last r42 line (M of
#   them read their colour history), K stayed grey (...)" (r92 review: the draft appended it to the
#   r42 line, whose text before its lamps is longer than the 300 characters a slot run keeps).
# Review (2026-11-15, r92_lamp-shadow-colour.fixed.py, 63 edits): the draft's 62 with one added (the
#   clamp's colour move, shader), the count moved to a line of its own (vk_point_shadow.cpp), the
#   start line no longer saying "on" when no ray traced lamp pass is made, and the README row and the
#   start line naming LANTERN_RT_LAMP_REUSE's passes, which stay grey.
#
# Apply order with its siblings: r91 (per-lamp radius), r93 (spatial filter), then this (the lead's
# order; since the review no anchor is shared with r91, r93 or r101, and every order of the four was
# applied, checked and reverted on a copy). Anchors are single lines or small blocks in this patch's
# own region (lampWeight's sums, the final write, the history taps, the builds, the descriptor
# pushes); every insertion leaves its anchor whole.
#
# Use: python -I -X utf8 r92_lamp-shadow-colour.py check | apply | revert   (root from R92_ROOT,
# else <tree>). Files keep their line ends (CRLF). Originals are kept in r92_backup/ next to
# this script at apply. Revert undoes the edits one by one (works with later patches applied
# elsewhere in the files). No new files.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r92_backup")
ROOT = os.environ.get("R92_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"
SHADER = H + "point_shadow_ray.comp"
CPP = R + "vk_point_shadow.cpp"
HDR = R + "vk_point_shadow.h"
TUNE = R + "lamp_shadow_tune.h"
TEST = "engine/tests/test_lamp_shadow_tune.cpp"
CMAKE = "engine/gpu/CMakeLists.txt"
README = "README.md"


def after(anchor, text):
    return (anchor, anchor + text)


def before(anchor, text):
    return (anchor, text + anchor)


EDITS = {}

# ---------------------------------------------------------------------------------------------
# point_shadow_ray.comp
# ---------------------------------------------------------------------------------------------
EDITS[SHADER] = [
    before("layout(push_constant) uniform Constants {\n", r'''#ifdef COLOUR
// bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1 only (the builds made with COLOUR: the
// plain, half, centred, half centred and the two resolve builds each have a COLOUR form; the builds
// without it are the pass as before, word for word, and the CARDS builds have none). Each lamp's
// share of a pixel's shadow keeps the lamp's colour: the weights are per channel (lampWeight times
// the record's colour over its luma, colourOf), and so are the sums (wsum_c, vsum_c) and the ratio
// (colour_rc). The grey ratio stays what every guard takes (the window, the reject, the follow,
// the half-resolution blocks' agreement); the colour rides beside it, is averaged in its own
// history with the grey ratio's share, and is rescaled so that the lamp light keeps the luma the
// grey ratio gives it (colourScale): only the hue of a lamp shadow changes, where differently
// coloured lamps overlap. colour_image: three parts of the pass's size stacked (rows [0, h),
// [h, 2h) and [2h, 3h), h the pass's height): the colour history pair, taken in turn with the
// history (HISTORY_COLOUR_ONE: the second part is this frame's), and this pass's own colour answers
// (the trace's, for its resolve; at half resolution without the averaging, the first pass's block
// colours, for the second). A texel: the shadow ratio of each channel, 0 to 1. The binding is the
// one after the build's last (vk_point_shadow.cpp pushes it there).
#ifdef HALF
#ifdef CENTRED
layout(set = 0, binding = 14, rgb10_a2) uniform image2D colour_image;
#else
layout(set = 0, binding = 13, rgb10_a2) uniform image2D colour_image;
#endif
#else
#ifdef CENTRED
layout(set = 0, binding = 12, rgb10_a2) uniform image2D colour_image;
#else
layout(set = 0, binding = 11, rgb10_a2) uniform image2D colour_image;
#endif
#endif
#endif

'''),
    after("float ray_left = -1.0;\n", r'''#ifdef COLOUR
// bbport (r92_lamp-shadow-colour): word 0 bit 25 (lamp_shadow_tune.h LampTuneColour; the host sets it
// only on a pass that binds a COLOUR build with the colour image at the pass's size): this pass
// shadows in colour; clear, the pass is as without COLOUR. The history block's flags (vk_point_
// shadow.cpp HistoryColourRead, HistoryColourOne; set only with HISTORY_BLEND): the other part holds
// the colour of the history this pass reads; this frame's part is the second (else the first).
bool t_colour = false;
const uint HISTORY_COLOUR_READ = 8u;
const uint HISTORY_COLOUR_ONE = 16u;
int colour_cur_row = 0;      // the colour image's first row of this frame's history part
int colour_prev_row = 0;     // of the part the frame before wrote
int colour_block_row = 0;    // of the part that holds a half-resolution block's colour (HalfAnswer)
bool colour_read = false;    // the colour history is read (at the grey history's taps)
vec3 wsum_c = vec3(0.0);     // the lamps' weights in each channel
vec3 vsum_c = vec3(0.0);     // what the rays let through of them
float vsum_seen = 0.0;       // the exact path: vsum as the lamp before left it
float vsum_top = -1.0;       // the pick: the strongest lamp's part of vsum (below 0: no pick)
vec3 colour_rc = vec3(1.0);  // the pixel's ratio in each channel (this frame's, then averaged)
vec3 colour_tap = vec3(0.0); // the colour history at the taps of the last look-up
vec3 colour_a = vec3(0.0), colour_f = vec3(0.0), colour_held = vec3(0.0);

// A lamp's colour over its luma (the luma lampWeight takes): its weight times this is its weight in
// each channel, whose luma is the weight. Called only for a lamp with weight (luma above 0).
vec3 colourOf(vec3 col) {
    const float l = dot(col, vec3(0.299, 0.587, 0.114));
    return l > 0.0 ? col / l : vec3(1.0);
}

vec3 colourLoad(ivec2 p, int row) {
    return imageLoad(colour_image, p + ivec2(0, row)).rgb;
}

// Only within the pass's size: a texel beyond it would land in the next part.
void colourStore(ivec2 p, int row, vec3 c) {
    if (all(greaterThanEqual(p, ivec2(0))) && all(lessThan(p, ivec2(size)))) {
        imageStore(colour_image, p + ivec2(0, row), vec4(c, 1.0));
    }
}

// The scale of each channel of the lamp light (light: d0 + d1) for the grey ratio and the channels'
// ratios rc: rc made to give the lamp light the luma the grey ratio gives it (the luma weighted by
// the light, so a channel without lamp light counts for nothing), then, where a channel would pass
// more than its whole light, moved toward the grey ratio (which keeps that luma) until none does.
// No light, or an rc that passes nothing of it: the grey ratio. (lamp_shadow_tune.h LampColourScale
// is the same in C++, for the test.)
vec3 colourScale(vec3 rc, float ratio, vec3 light) {
    const vec3 lw = light * vec3(0.299, 0.587, 0.114);
    const float whole = lw.r + lw.g + lw.b;
    const float got = dot(lw, rc);
    if (!(whole > 0.0) || !(got > 1e-6 * whole)) {
        return vec3(ratio);
    }
    vec3 x = rc * (ratio * whole / got);
    const float top = max(max(x.r, x.g), x.b);
    if (top > 1.0) {
        x = mix(vec3(ratio), x, (1.0 - ratio) / (top - ratio));
    }
    return x;
}
#endif
'''),
    after("    t_window = (f & (1u << 21u)) != 0u;      // bbport (r57_lamp-window)\n", r'''#ifdef COLOUR
    t_colour = (f & (1u << 25u)) != 0u;      // bbport (r92_lamp-shadow-colour)
#endif
'''),
    # blendHistory (the vote's look-up): the colour at the same taps, made whole as the ratio is
    after("    float found = 0.0;\n", r'''#ifdef COLOUR
    colour_tap = vec3(0.0); // bbport (r92_lamp-shadow-colour)
#endif
'''),
    ("                found += w;\n            }\n        }\n    }\n    if (!(found > 0.01)) {\n",
     r'''                found += w;
#ifdef COLOUR
                if (colour_read) { // bbport (r92_lamp-shadow-colour): the colour history at the same tap
                    colour_tap += w * colourLoad(q, colour_prev_row);
                }
#endif
            }
        }
    }
    if (!(found > 0.01)) {
'''),
    after("    fast = sum.z / found;\n", r'''#ifdef COLOUR
    colour_tap /= found; // bbport (r92_lamp-shadow-colour)
#endif
'''),
    # historyAt (the soft follow's look-ups): the colour at the same taps, not made whole
    after("    lam = 0.0;\n", r'''#ifdef COLOUR
    colour_tap = vec3(0.0); // bbport (r92_lamp-shadow-colour): as sum, at the same taps
#endif
'''),
    after("                lam += w * stateAt(q);\n", r'''#ifdef COLOUR
                if (colour_read) { // bbport (r92_lamp-shadow-colour)
                    colour_tap += w * colourLoad(q, colour_prev_row);
                }
#endif
'''),
    # HalfAnswer: the blocks' colours agree as their ratios must
    before("    // The block's pixel on the same surface: the history's depth tolerance, normals within\n",
           r'''#ifdef COLOUR
    // bbport (r92_lamp-shadow-colour): and their colours agree as their ratios must (a pixel that takes
    // its block's ratio takes its colour too; blocks that agree in the ratio but not in the colour,
    // another lamp blocked by the same share, are traced, as the full-resolution pass would show
    // them): the colour each block's pixel left in this pass (colour_block_row: the averaged one, or
    // without the averaging its answer).
    if (t_colour) {
        const vec3 c = colourLoad(block * 2, colour_block_row);
        for (int y = -1; y <= 1; ++y) {
            for (int x = -1; x <= 1; ++x) {
                const vec3 q = colourLoad(clamp(block + ivec2(x, y), lo, hi) * 2, colour_block_row);
                if (any(greaterThan(abs(q - c), vec3(HALF_AGREE)))) {
                    return HALF_DIFFER;
                }
            }
        }
    }
#endif
'''),
    after("    const uint history_flags = history_at != 0u ? data.d[history_at] : 0u;\n", r'''#ifdef COLOUR
    // bbport (r92_lamp-shadow-colour): the colour image's parts for this pass (colour_image)
    colour_cur_row = (history_flags & HISTORY_COLOUR_ONE) != 0u ? int(size.y) : 0;
    colour_prev_row = int(size.y) - colour_cur_row;
    colour_block_row = (history_flags & HISTORY_BLEND) != 0u ? colour_cur_row : 2 * int(size.y);
    colour_read = t_colour && (history_flags & (HISTORY_READ | HISTORY_BLEND | HISTORY_COLOUR_READ)) ==
                                  (HISTORY_READ | HISTORY_BLEND | HISTORY_COLOUR_READ);
#endif
'''),
    after("            wsum += w;\n", r'''#ifdef COLOUR
            if (t_colour) { // bbport (r92_lamp-shadow-colour): its weight in each channel
                wsum_c += w * colourOf(col);
            }
#endif
'''),
    after("            vsum = taken * wsum; // the block's answer, in place of this pixel's rays\n", r'''#ifdef COLOUR
            if (t_colour) { // bbport (r92_lamp-shadow-colour): its colour (averaging: the block's averaged one, below)
                vsum_c = (blend ? vec3(taken) : colourLoad(px & ~1, 2 * int(size.y))) * wsum_c;
            }
#endif
'''),
    before("                        if (at == top_at) {\n                            top_went = ray_went;\n", r'''#ifdef COLOUR
                        if (t_colour) { // bbport (r92_lamp-shadow-colour): this lamp's part of vsum, in its colour
                            vsum_c += colourOf(col) * (vsum - vsum_seen);
                            vsum_seen = vsum;
                        }
#endif
'''),
    before("            if (rest_w > 0.0) {\n", r'''#ifdef COLOUR
            vsum_top = vsum; // bbport (r92_lamp-shadow-colour): the strongest lamp's part
#endif
'''),
    after("        ratio = clamp(vsum / wsum, 0.0, 1.0);\n", r'''#ifdef COLOUR
        if (t_colour) {
            // bbport (r92_lamp-shadow-colour): this frame's answer in each channel. The pick: the
            // strongest lamp's part in its own colour, and the picked lamp's answer for the summed
            // channel weights of all the weaker lamps (exact with one weaker lamp; with more, their
            // colours share the picked one's answer, which keeps every channel within 0 and 1 and a
            // pixel every lamp lights at 1). A channel without weight: the grey ratio.
            if (vsum_top >= 0.0) {
                const vec3 top_c = colourOf(vec3(word(top_at + 4u), word(top_at + 5u), word(top_at + 6u)));
                vsum_c = top_c * vsum_top;
                if (0.0 < rest_w) {
                    vsum_c += max(wsum_c - top_w * top_c, vec3(0.0)) * ((vsum - vsum_top) / rest_w);
                }
            }
            colour_rc = clamp(mix(vec3(ratio), vsum_c / max(wsum_c, vec3(1e-30)), greaterThan(wsum_c, vec3(0.0))),
                              0.0, 1.0);
        }
#endif
'''),
    after("        if (trace_only) {\n", r'''#ifdef COLOUR
            if (t_colour && live) { // bbport (r92_lamp-shadow-colour): this frame's colour answer, for the resolve
                colourStore(px, 2 * int(size.y), colour_rc);
            }
#endif
'''),
    after("            imageStore(history_cur, px, vec4(ratio, P.z, h.b, h.a));\n", r'''#ifdef COLOUR
            if (t_colour) { // bbport (r92_lamp-shadow-colour): and the block's averaged colour
                colour_rc = colourLoad(px & ~1, colour_cur_row);
                colourStore(px, colour_cur_row, colour_rc);
            }
#endif
'''),
    after("                historyAt(P, history_at, vec3(0.0), sa, fa, la);\n", r'''#ifdef COLOUR
                colour_a = colour_tap; // bbport (r92_lamp-shadow-colour)
                colour_f = colour_tap;
#endif
'''),
    after("                    historyAt(P, history_at, top_moved, sf, ff, lf);\n", r'''#ifdef COLOUR
                    colour_f = colour_tap; // bbport (r92_lamp-shadow-colour)
#endif
'''),
    after("                    held_fast = both.z / got;\n", r'''#ifdef COLOUR
                    colour_held = ((1.0 - w_f) * colour_a + w_f * colour_f) / got; // bbport (r92_lamp-shadow-colour)
#endif
'''),
    after("                   blendHistory(P, history_at, follows ? top_moved : vec3(0.0), held_ratio, held_frames, held_fast);\n",
          r'''#ifdef COLOUR
            colour_held = colour_tap; // bbport (r92_lamp-shadow-colour): made whole there
#endif
'''),
    # (r92 review) the window clamp moves the colour history as it moves the ratio's
    before("                held_ratio = fitted;\n", r'''#ifdef COLOUR
                // bbport (r92_lamp-shadow-colour): the colour history moved by what the clamp moves the
                // ratio's, in every channel (0 to 1): the luma of a colour answer, by the lamps' channel
                // weights, is the ratio, so the colour history keeps the luma of the ratio's history and
                // the output's rescale (colourScale) does not magnify the hue it held before the clamp
                // (that hue's offsets between the channels stay, for the frames the guards leave).
                colour_held = clamp(colour_held + (fitted - held_ratio), 0.0, 1.0);
#endif
'''),
    after("        imageStore(history_cur, px, vec4(ratio, P.z, frames + 1.0, fast));\n", r'''#ifdef COLOUR
        if (t_colour) {
            // bbport (r92_lamp-shadow-colour): the colour rides beside the ratio. This frame's colour
            // answer (the resolve: the one its trace stored) goes into the colour history read at the
            // ratio's taps, with the ratio's share after every guard above (frames), so the colour's
            // history is kept, shortened or given up where the ratio's is.
#ifdef CENTRED
            if (resolve) {
                colour_rc = colourLoad(px, 2 * int(size.y));
            }
#endif
            if (held && colour_read) {
                colour_rc = mix(colour_rc, colour_held, frames / (frames + 1.0));
            }
            colourStore(px, colour_cur_row, colour_rc);
        }
#endif
'''),
    ("    vec3 out0 = s0 + d0 * scale, out1 = s1 + d1 * scale;\n", r'''#ifdef COLOUR
    // bbport (r92_lamp-shadow-colour): with bit 25, each channel its own scale, the lamp light's luma
    // that of the grey ratio (colourScale); without it, the grey ratio's scale in every channel.
    const vec3 scale_c = t_colour ? mix(vec3(1.0), colourScale(colour_rc, ratio, d0 + d1), strength * fade)
                                  : vec3(scale);
    vec3 out0 = s0 + d0 * scale_c, out1 = s1 + d1 * scale_c;
#else
    vec3 out0 = s0 + d0 * scale, out1 = s1 + d1 * scale;
#endif
'''),
    after("                   n == vec3(0.0) ? vec4(-1.0) : vec4(ratio, P.z, OctEncode(n)));\n", r'''#ifdef COLOUR
        if (t_colour && !blend) { // bbport (r92_lamp-shadow-colour): the block's colour, for the second pass
            colourStore(px, 2 * int(size.y), colour_rc);
        }
#endif
'''),
]

# ---------------------------------------------------------------------------------------------
# vk_point_shadow.cpp
# ---------------------------------------------------------------------------------------------
EDITS[CPP] = [
    after('#include "video_core/host_shaders/point_shadow_ray_resolve_comp.h"\n', r'''// bbport (r92_lamp-shadow-colour): the COLOUR builds of BB_LAMP_SHADOW_COLOUR=1
#include "video_core/host_shaders/point_shadow_ray_centred_colour_comp.h"
#include "video_core/host_shaders/point_shadow_ray_colour_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_centred_colour_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_colour_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_resolve_colour_comp.h"
#include "video_core/host_shaders/point_shadow_ray_resolve_colour_comp.h"
'''),
    after("constexpr u32 HistoryBlend = 4;\n", r'''// bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1: two more bits of the history block's
// flags, set only with HistoryBlend on a pass that shadows in colour (point_shadow_ray.comp
// HISTORY_COLOUR_READ, HISTORY_COLOUR_ONE): the colour image's part that holds the colour of the
// history this pass reads is to be read (the pass that wrote that history wrote its colour), and
// this frame's part is the second. The colour image: ColourParts parts of the pass's size stacked
// (the colour history pair and the pass's own answers), 4 bytes a pixel each.
constexpr u32 HistoryColourRead = 8, HistoryColourOne = 16;
static_assert(((HistoryColourRead | HistoryColourOne) & (HistoryRead | HistoryWrite | HistoryBlend)) == 0);
constexpr auto ColourFormat = vk::Format::eA2B10G10R10UnormPack32;
constexpr u32 ColourParts = 3;
'''),
    before("std::array<float, 16> Invert(const u32* words, bool& ok) {\n", r'''// bbport (r92_lamp-shadow-colour): a lamp build's SPIR-V, or its COLOUR form's (BB_LAMP_SHADOW_COLOUR=1)
std::span<const u32> ColourCode(bool colour, std::span<const u32> plain, std::span<const u32> coloured) {
    return colour ? coloured : plain;
}

'''),
    ("                   std::span<const u32> code, float texel_scale) {\n",
     "                   std::span<const u32> code, float texel_scale, u32 colour_images = 0) {\n"),
    after("        bindings.push_back({u32(bindings.size()), type, 1, vk::ShaderStageFlagBits::eCompute});\n    }\n",
          r'''    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1: the colour image's binding after the
    // last, in the layout only (a CARDS build has no COLOUR form and does not read it), so that set 0
    // is as the COLOUR builds have it and pushes of r61's resolve build do not disturb set 1
    for (u32 i = 0; i < colour_images; ++i) {
        bindings.push_back({u32(bindings.size()), vk::DescriptorType::eStorageImage, 1,
                            vk::ShaderStageFlagBits::eCompute});
    }
'''),
    before("    // bbport (r61_lamp-window-cost, r73_lamp-resolve-list-check): the centred build and the\n", r'''    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1 (read once, LampShadowTune::colour):
    // every lamp build below and in HalfReady is made in its COLOUR form (point_shadow_ray.comp
    // COLOUR: one binding more, the colour image, after the build's last), and the CARDS builds'
    // layouts get that binding too; a build that cannot be made falls back as the plain one would,
    // to the next build in its COLOUR form. Not on a device that cannot store the image's format.
    colour_mode = tune.colour && EffectPass::StorageFormat(instance, ColourFormat);
    if (tune.colour) {
        std::printf("Ray traced lamps (r92): coloured lamp shadows %s (BB_LAMP_SHADOW_COLOUR=1): each lamp's "
                    "share of a pixel's shadow keeps the lamp's colour, so where a warm and a cool lamp "
                    "overlap the shadow of one is lit in the other's colour; the lamp light keeps the luma "
                    "the grey ratio gives it, and the grey ratio is still what the history's guards take; "
                    "one image of 12 bytes a pixel (the colour history pair and the pass's own colour "
                    "answers); passes that run a CARDS build (BB_RT_CARD_LAMPS=1) or LANTERN_RT_LAMP_REUSE's "
                    "history stay grey\n",
                    !colour_mode              ? "off - this GPU cannot store A2B10G10R10 in a compute pass"
                    : rt_shadow.Capturing() ? "on"
                                            : "on, but no ray traced lamp pass is made (no ray tracing)");
    }
'''),
    after("\n                                  vk::UniquePipeline& pipe, std::span<const u32> code, const char* name) {\n",
          r'''        if (colour_mode) { // bbport (r92_lamp-shadow-colour): binding 12, the colour image
            return EffectPass::Create(instance, set, lay, pipe,
                                      {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                                       eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                                       eStorageImage, eStorageImage, eStorageImage, eStorageImage, eStorageImage},
                                      sizeof(Push), code, name, true);
        }
'''),
    ('        !make_centred(ray_set_layout, ray_layout, ray_pipeline, POINT_SHADOW_RAY_CENTRED_COMP, "Ray traced lamps")) {\n',
     r'''        !make_centred(ray_set_layout, ray_layout, ray_pipeline,
                      ColourCode(colour_mode, POINT_SHADOW_RAY_CENTRED_COMP, POINT_SHADOW_RAY_CENTRED_COLOUR_COMP), // r92
                      "Ray traced lamps")) {
'''),
    ('                                            POINT_SHADOW_RAY_RESOLVE_COMP, "Ray traced lamps (resolve)")) {\n',
     r'''                                            ColourCode(colour_mode, POINT_SHADOW_RAY_RESOLVE_COMP,
                                                       POINT_SHADOW_RAY_RESOLVE_COLOUR_COMP), // bbport (r92)
                                            "Ray traced lamps (resolve)")) {
'''),
    ("    // bbport (r52_follow-soft): bindings 9 and 10, the follow state\n    if (!centred && rt_shadow.Capturing() &&\n",
     r'''    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1: the plain build's COLOUR form, binding 11
    // the colour image (then not the plain build below)
    if (colour_mode && !centred && rt_shadow.Capturing() &&
        !EffectPass::Create(instance, ray_set_layout, ray_layout, ray_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                             eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                             eStorageImage, eStorageImage, eStorageImage, eStorageImage},
                            sizeof(Push), POINT_SHADOW_RAY_COLOUR_COMP, "Ray traced lamps (colour)", true)) {
        std::printf("Ray traced lamps: off - the pass could not be made (r92: its COLOUR form)\n");
    }
    // bbport (r52_follow-soft): bindings 9 and 10, the follow state
    if (!colour_mode && !centred && rt_shadow.Capturing() &&
'''),
    after("\n                                       vk::UniquePipeline& pipe, std::span<const u32> code, const char* name) {\n",
          r'''        if (colour_mode) { // bbport (r92_lamp-shadow-colour): binding 14, the colour image
            return EffectPass::Create(instance, set, lay, pipe,
                                      {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                                       eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                                       eStorageImage, eStorageImage, eStorageBuffer, eStorageImage, eStorageImage,
                                       eStorageImage, eStorageImage},
                                      sizeof(Push), code, name, true);
        }
'''),
    ("make_half_centred(half_set_layout, half_layout, half_pipeline, POINT_SHADOW_RAY_HALF_CENTRED_COMP,\n",
     r'''make_half_centred(half_set_layout, half_layout, half_pipeline,
                                     ColourCode(colour_mode, POINT_SHADOW_RAY_HALF_CENTRED_COMP,
                                                POINT_SHADOW_RAY_HALF_CENTRED_COLOUR_COMP), // bbport (r92)
'''),
    ('                           POINT_SHADOW_RAY_HALF_RESOLVE_COMP, "Ray traced lamps (half resolution, resolve)")) {\n',
     r'''                           ColourCode(colour_mode, POINT_SHADOW_RAY_HALF_RESOLVE_COMP,
                                      POINT_SHADOW_RAY_HALF_RESOLVE_COLOUR_COMP), // bbport (r92)
                           "Ray traced lamps (half resolution, resolve)")) {
'''),
    ("    const bool made =\n        ray_pipeline &&\n        (half_centred || EffectPass::Create(instance, half_set_layout, half_layout, half_pipeline,\n",
     r'''    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1: the plain half-resolution build's COLOUR
    // form, binding 13 the colour image (then not the plain one)
    const bool half_colour_made =
        ray_pipeline && !half_centred && colour_mode &&
        EffectPass::Create(instance, half_set_layout, half_layout, half_pipeline,
                           {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage,
                            eStorageImage, eAccelerationStructureKHR, eStorageImage, eStorageImage, eStorageImage,
                            eStorageBuffer, eStorageImage, eStorageImage, eStorageImage},
                           sizeof(Push), POINT_SHADOW_RAY_HALF_COLOUR_COMP, "Ray traced lamps (half resolution, colour)",
                           true);
    const bool made =
        ray_pipeline &&
        (half_centred || half_colour_made ||
         (!colour_mode && EffectPass::Create(instance, half_set_layout, half_layout, half_pipeline,
'''),
    ('                                            "Ray traced lamps (half resolution)", true));\n',
     '                                            "Ray traced lamps (half resolution)", true)));\n'),
    ("                             POINT_SHADOW_RAY_HALF_CENTRED_CARDS_COMP, card_texel_scale);\n",
     "                             POINT_SHADOW_RAY_HALF_CENTRED_CARDS_COMP, card_texel_scale,\n"
     "                             colour_mode ? 1u : 0u); // bbport (r92_lamp-shadow-colour)\n"),
    ("                             POINT_SHADOW_RAY_HALF_CARDS_COMP, card_texel_scale);\n",
     "                             POINT_SHADOW_RAY_HALF_CARDS_COMP, card_texel_scale,\n"
     "                             colour_mode ? 1u : 0u); // bbport (r92_lamp-shadow-colour)\n"),
    ("                             POINT_SHADOW_RAY_CENTRED_CARDS_COMP, card_texel_scale);\n",
     "                             POINT_SHADOW_RAY_CENTRED_CARDS_COMP, card_texel_scale,\n"
     "                             colour_mode ? 1u : 0u); // bbport (r92_lamp-shadow-colour)\n"),
    ("                             POINT_SHADOW_RAY_CARDS_COMP, card_texel_scale);\n",
     "                             POINT_SHADOW_RAY_CARDS_COMP, card_texel_scale,\n"
     "                             colour_mode ? 1u : 0u); // bbport (r92_lamp-shadow-colour)\n"),
    before("    track.ClearSteps();\n", r'''    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1: a short line of its own after the r42
    // line, at its times (the slot runs keep 300 characters of a log line; the r42 line is longer
    // than that before its lamps)
    if (colour_mode) {
        std::printf("Ray traced lamps (r92): %u ray traced lamp passes shadowed in colour since the last "
                    "r42 line (%u of them read their colour history), %u stayed grey (a CARDS build, "
                    "LANTERN_RT_LAMP_REUSE's history, the repair off, or no colour image of their size)\n",
                    line_colour, line_colour_read, line_colour_grey);
    }
    line_colour = line_colour_read = line_colour_grey = 0; // bbport (r92_lamp-shadow-colour)
'''),
    before("        // bbport (r60_lamp-centred-window): the centred window's answers (binding 11 of the full\n", r'''        // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1 (the COLOUR builds, Ready): the colour
        // image (point_shadow_ray.comp colour_image: ColourParts parts of this pass's size stacked, 4
        // bytes a pixel each), made at this pass's size as the history is. Without room for it: no
        // pass while there is none (the COLOUR builds read the binding), else this pass binds the one
        // there is and stays grey (bit 25 clear, below). Not cleared: a part is read only where this
        // pass, or the pass that wrote the history it reads (HistoryColourRead), wrote it first.
        if (colour_mode && (colour_image.width != width || colour_image.height != ColourParts * height)) {
            if (EffectPass::HasRoom(instance, 4ull * ColourParts * width * height) &&
                EnsureImage(colour_image, width, ColourParts * height, ColourFormat, "Ray traced lamp colour")) {
                colour_laid_out = false;
                colour_wrote_frame = ~0u;
                std::printf("Ray traced lamps (r92): the colour image, %ux%u (three parts of %ux%u), %.1f MB\n",
                            width, ColourParts * height, width, height, 4.0 * ColourParts * width * height / 1e6);
            } else if (!colour_image.image) {
                data.clear();
                return;
            }
        }
'''),
    before('    EffectPass::Mark(card_bind ? 64 : 6, card_bind ? "point shadows (leaf cards)" : "point shadows");\n', r'''    // bbport (r92_lamp-shadow-colour): this pass shadows in colour (tuning word 0 bit 25,
    // LampTuneColour) when its build is a COLOUR one (not a CARDS build), the repair's words are there,
    // the colour image has its size and its history is not LANTERN_RT_LAMP_REUSE's (a history without
    // HistoryBlend: its pixels that take the history's ratio in place of rays would be grey on the
    // frames between their rays). A pass that averages then also says which part of the image is
    // this frame's colour history (HistoryColourOne: history_index, as the history images are taken)
    // and whether the other part holds the colour of the history it reads (HistoryColourRead: the last
    // pass that wrote a history, the one read, wrote its colour too: colour_wrote_frame, set by every
    // pass that writes a history, ~0u by one that wrote it without colour and by a new colour image).
    // The image is bound to every ray traced pass while the COLOUR builds are made (their layouts
    // have the binding).
    const u32 colour_flags = history_at != 0 ? data[history_at] : 0u;
    const bool colour_pass = use_rays && colour_mode && repair && !card_bind &&
                             colour_image.width == width && colour_image.height == ColourParts * height &&
                             (colour_flags == 0u || (colour_flags & HistoryBlend) != 0);
    line_colour += colour_pass ? 1 : 0;
    line_colour_grey += use_rays && colour_mode && !colour_pass ? 1 : 0;
    if (colour_pass) {
        data[tune_at] |= LampTuneColour;
    }
    if (colour_mode && (colour_flags & HistoryWrite) != 0) {
        const bool colour_blend = colour_pass && (colour_flags & HistoryBlend) != 0;
        if (colour_blend) {
            const bool colour_read = (colour_flags & HistoryRead) != 0 && colour_wrote_frame != ~0u;
            data[history_at] |= (history_index != 0 ? HistoryColourOne : 0u) | (colour_read ? HistoryColourRead : 0u);
            line_colour_read += colour_read ? 1 : 0;
        }
        colour_wrote_frame = colour_blend ? frame_index : ~0u;
    }
    const vk::ImageView colour_view = use_rays && colour_mode ? *colour_image.view : vk::ImageView{};
    const vk::Image colour_vk_image = use_rays && colour_mode ? vk::Image(colour_image.image) : vk::Image{};
    const bool colour_lay_out = bool(colour_view) && !std::exchange(colour_laid_out, true);
'''),
    after("         card_bind, card_bind_layout, // bbport (r63_leaf-stage4)\n",
          "         colour_view, colour_vk_image, colour_lay_out, // bbport (r92_lamp-shadow-colour)\n"),
    before("                const vk::MemoryBarrier2 to_transfer{\n", r'''                if (colour_lay_out) { // bbport (r92_lamp-shadow-colour): on its first use
                    const vk::ImageMemoryBarrier2 to_general{
                        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                        .dstStageMask = Compute,
                        .dstAccessMask = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite,
                        .oldLayout = vk::ImageLayout::eUndefined,
                        .newLayout = vk::ImageLayout::eGeneral,
                        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .image = colour_vk_image,
                        .subresourceRange = ColorRange,
                    };
                    cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
                }
'''),
    ("                                       .pImageInfo = &answers_info}};\n            // bbport (r60_lamp-centred-window): between the trace and the resolve (and after the\n",
     r'''                                       .pImageInfo = &answers_info}};
            // bbport (r92_lamp-shadow-colour): with the COLOUR builds (and the CARDS builds' layouts
            // then), the colour image in the binding after the build's last (11; 12 with the centred
            // window's answers)
            const vk::DescriptorImageInfo colour_info{{}, colour_view, vk::ImageLayout::eGeneral};
            std::array<vk::WriteDescriptorSet, 13> colour_writes{};
            std::copy_n(ray_writes.begin(), ray_count, colour_writes.begin());
            colour_writes[ray_count] = vk::WriteDescriptorSet{.dstBinding = ray_count, .descriptorCount = 1,
                                                              .descriptorType = vk::DescriptorType::eStorageImage,
                                                              .pImageInfo = &colour_info};
            const u32 ray_pushed = colour_view ? ray_count + 1u : ray_count;
            const vk::WriteDescriptorSet* const ray_push = colour_view ? colour_writes.data() : ray_writes.data();
            // bbport (r60_lamp-centred-window): between the trace and the resolve (and after the
'''),
    ("                                           .pImageInfo = &answers_info}};\n                // bbport (r61_lamp-window-cost): a build and its bindings (the resolves' own build\n",
     r'''                                           .pImageInfo = &answers_info}};
                // bbport (r92_lamp-shadow-colour): the colour image after the build's last (13; 14 with
                // the centred window's answers), as for the full-resolution builds
                const u32 half_written = half_with_answers ? 14u : 13u;
                std::array<vk::WriteDescriptorSet, 15> half_colour_writes{};
                std::copy_n(half_writes.begin(), half_written, half_colour_writes.begin());
                half_colour_writes[half_written] = vk::WriteDescriptorSet{
                    .dstBinding = half_written, .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &colour_info};
                const u32 half_pushed = colour_view ? half_written + 1u : half_written;
                const vk::WriteDescriptorSet* const half_push =
                    colour_view ? half_colour_writes.data() : half_writes.data();
                // bbport (r61_lamp-window-cost): a build and its bindings (the resolves' own build
'''),
    ("vk::ArrayProxy<const vk::WriteDescriptorSet>(half_with_answers ? 14u : 13u, half_writes.data()));\n",
     "vk::ArrayProxy<const vk::WriteDescriptorSet>(half_pushed, half_push)); // bbport (r92)\n"),
    ("vk::ArrayProxy<const vk::WriteDescriptorSet>(ray_count, ray_writes.data()));\n",
     "vk::ArrayProxy<const vk::WriteDescriptorSet>(ray_pushed, ray_push)); // bbport (r92)\n"),
    ("\n                                                            ray_count, ray_writes.data()));\n",
     "\n                                                            ray_pushed, ray_push)); // bbport (r92)\n"),
]

# ---------------------------------------------------------------------------------------------
# vk_point_shadow.h
# ---------------------------------------------------------------------------------------------
EDITS[HDR] = [
    after("    vk::UniquePipeline resolve_pipeline, half_resolve_pipeline;\n", r'''    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1 (LampShadowTune::colour, read at start).
    // colour_mode: Ready and HalfReady made the lamp builds in their COLOUR form (and the CARDS builds'
    // layouts with its binding). colour_image: point_shadow_ray.comp's colour image, three parts of the
    // pass's size stacked (A2B10G10R10, 4 bytes a pixel each; made by Flush at the pass's size, laid
    // out on first use, never cleared). colour_wrote_frame: the frame of the last pass that wrote a
    // history, when it wrote that history's colour too (~0u: it did not, or none since the image).
    // For the r92 line after the lamp line (TrackLamps): passes shadowed in colour, those of them
    // that read their colour history, and passes with the COLOUR builds that stayed grey.
    bool colour_mode = false;
    OwnImage colour_image;
    bool colour_laid_out = false;
    u32 colour_wrote_frame = ~0u;
    u32 line_colour = 0, line_colour_read = 0, line_colour_grey = 0;
'''),
]

# ---------------------------------------------------------------------------------------------
# lamp_shadow_tune.h
# ---------------------------------------------------------------------------------------------
EDITS[TUNE] = [
    after("    bool weights = true;         ///< BB_LAMP_SHADOW_WEIGHTS: the game's falloff times N.L; 0: as before\n",
          r'''    bool colour = false;         ///< bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR: 1: each lamp's
                                 ///< share of a shadow keeps its colour (the COLOUR builds, picked at
                                 ///< start); 0: one grey ratio for all lamps
'''),
    # (r92 review) before the next declaration, not after the static_assert r93 also inserts after
    before("/// bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW as a number, 0 to 2.\n",
          r'''/// bbport (r92_lamp-shadow-colour): bit 25, the pass shadows in colour (point_shadow_ray.comp
/// t_colour). PointShadow::Flush sets it on a pass that binds a COLOUR build with its colour image;
/// LampTuneWords leaves it 0. Bits 24 and 26 (5u << 24) are r91's and r93's (per-lamp radius,
/// spatial filter).
inline constexpr std::uint32_t LampTuneColour = 1u << 25;
static_assert((LampTuneColour & (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft | LampTuneWindow |
                                 LampTuneCentred | (7u << LampTuneViewShift) | (0x3Fu << 12) | (5u << 24))) == 0);
'''),
    after('    tune.weights = Whole(get, "BB_LAMP_SHADOW_WEIGHTS", tune.weights ? 1u : 0u, 1u) != 0;\n',
          '    tune.colour = Whole(get, "BB_LAMP_SHADOW_COLOUR", tune.colour ? 1u : 0u, 1u) != 0; // bbport (r92)\n'),
    after("    return f * faced * luma;\n}\n", r'''
/// bbport (r92_lamp-shadow-colour): point_shadow_ray.comp's colourScale in C++ (BB_LAMP_SHADOW_COLOUR;
/// tests/test_lamp_shadow_tune.cpp): the scale of each channel of the lamp light `light` for the
/// grey ratio and the channels' ratios rc. rc is made to give the lamp light the luma (Rec. 601,
/// weighted by the light) the grey ratio gives it, then moved toward the grey ratio (which keeps
/// that luma) until no channel passes more than its whole light. No light, or an rc that passes
/// nothing of it: the grey ratio.
using LampRgb = std::array<float, 3>;
inline LampRgb LampColourScale(const LampRgb& rc, float ratio, const LampRgb& light) {
    constexpr LampRgb Luma{0.299f, 0.587f, 0.114f};
    float whole = 0.0f, got = 0.0f;
    for (int c = 0; c < 3; ++c) {
        whole += light[c] * Luma[c];
        got += light[c] * Luma[c] * rc[c];
    }
    if (!(whole > 0.0f) || !(got > 1e-6f * whole)) {
        return {ratio, ratio, ratio};
    }
    LampRgb x{};
    for (int c = 0; c < 3; ++c) {
        x[c] = rc[c] * (ratio * whole / got);
    }
    const float top = std::max({x[0], x[1], x[2]});
    if (top > 1.0f) {
        const float a = (1.0f - ratio) / (top - ratio);
        for (float& v : x) {
            v = ratio + (v - ratio) * a;
        }
    }
    return x;
}
'''),
]

# ---------------------------------------------------------------------------------------------
# test_lamp_shadow_tune.cpp
# ---------------------------------------------------------------------------------------------
EDITS[TEST] = [
    after("// 5x5 statistic: centred on every pixel it does not change as the workgroups' grid moves.\n",
          "// bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR, its bit in word 0 and the colour's rescale.\n"),
    # (r92 review) after the last test block, not before the closing puts that r93 also inserts before
    after("        assert(track.Lamp(1).followed && track.Step(1) == 0.0f);\n        track.End(false);\n    }\n",
          r'''    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR: off unless set, any whole number above 0
    // is on, text that is no number leaves it off; LampTuneWords never sets its bit (Flush does).
    {
        assert(!Read(std::array<Pair, 0>{}).colour);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_COLOUR", "1"}}}).colour);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_COLOUR", "0"}}}).colour);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_COLOUR", "7"}}}).colour);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_COLOUR", "-1"}}}).colour);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_COLOUR", "yes"}}}).colour);
        LampShadowTune on;
        on.colour = true;
        assert(LampTuneWords(on, true, 0.05f) == LampTuneWords(LampShadowTune{}, true, 0.05f));
        assert((LampTuneWords(on, true, 0.05f)[0] & LampTuneColour) == 0u && LampTuneColour == 1u << 25);
        // The rescale (the shader's colourScale). Lit by every lamp or by none, or one lamp's colour
        // only: the grey ratio in every channel.
        const auto luma = [](const LampRgb& light, const LampRgb& s) {
            return 0.299f * light[0] * s[0] + 0.587f * light[1] * s[1] + 0.114f * light[2] * s[2];
        };
        const LampRgb warm{1.0f, 0.6f, 0.3f}, cool{0.3f, 0.5f, 1.0f};
        for (const float r : {0.0f, 0.4f, 1.0f}) {
            const LampRgb x = LampColourScale({r, r, r}, r, warm);
            assert(std::abs(x[0] - r) < 1e-5f && std::abs(x[1] - r) < 1e-5f && std::abs(x[2] - r) < 1e-5f);
        }
        // The owner's photo: a warm and a cool lamp of equal weight, the warm one blocked. Their
        // channel weights are weight x colour / luma (point_shadow_ray.comp colourOf); the light is
        // their sum. The exact answer in each channel is the cool lamp's share; it already gives the
        // grey ratio's luma (0.5), so the rescale keeps it: bluish, as bright as the grey shadow.
        const float lw = luma({1.0f, 1.0f, 1.0f}, warm), lc = luma({1.0f, 1.0f, 1.0f}, cool);
        LampRgb light{}, rc{};
        for (int c = 0; c < 3; ++c) {
            light[c] = warm[c] / lw + cool[c] / lc;
            rc[c] = (cool[c] / lc) / light[c];
        }
        const LampRgb x = LampColourScale(rc, 0.5f, light);
        for (int c = 0; c < 3; ++c) {
            assert(std::abs(x[c] - rc[c]) < 1e-4f && x[c] >= 0.0f && x[c] <= 1.0f);
        }
        assert(x[2] > x[1] && x[1] > x[0]);
        assert(std::abs(luma(light, x) - 0.5f * luma(light, {1.0f, 1.0f, 1.0f})) < 1e-4f);
        // A history whose colour lies below the grey ratio: lifted to its luma and kept within 1.
        const LampRgb lifted = LampColourScale({0.2f, 0.5f, 0.9f}, 0.95f, light);
        for (const float v : lifted) {
            assert(v >= 0.0f && v <= 1.0f + 1e-6f);
        }
        assert(std::abs(luma(light, lifted) - 0.95f * luma(light, {1.0f, 1.0f, 1.0f})) < 1e-4f);
        assert(lifted[2] > lifted[0]);
        // A channel without lamp light counts for nothing; no light at all: the grey ratio.
        const LampRgb no_blue = LampColourScale({0.5f, 0.5f, 0.0f}, 0.5f, {1.0f, 1.0f, 0.0f});
        assert(std::abs(no_blue[0] - 0.5f) < 1e-5f && std::abs(no_blue[1] - 0.5f) < 1e-5f);
        const LampRgb dark = LampColourScale({0.1f, 0.9f, 0.3f}, 0.3f, {0.0f, 0.0f, 0.0f});
        assert(dark[0] == 0.3f && dark[1] == 0.3f && dark[2] == 0.3f);
    }
'''),
]

# ---------------------------------------------------------------------------------------------
# CMakeLists.txt, README.md
# ---------------------------------------------------------------------------------------------
EDITS[CMAKE] = [
    after("add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_cards_comp HALF=1 CENTRED=1 CARDS=1)\n",
          r'''# bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1: the COLOUR form of each lamp build without
# CARDS (one binding more, the colour image); the lamp pass's builds above are unchanged.
add_host_shader(point_shadow_ray.comp point_shadow_ray_colour_comp COLOUR=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_colour_comp HALF=1 COLOUR=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_centred_colour_comp CENTRED=1 COLOUR=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_colour_comp HALF=1 CENTRED=1 COLOUR=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_resolve_colour_comp CENTRED=1 RESOLVE=1 COLOUR=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_resolve_colour_comp HALF=1 CENTRED=1 RESOLVE=1 COLOUR=1)
'''),
]

EDITS[README] = [
    after("| `BB_LAMP_SHADOW_FLOOR` | Least facing factor, 0 to 1; 0 has none | `0.05` |\n",
          "| `BB_LAMP_SHADOW_COLOUR` | `1` (to try): each lamp's share of a shadow keeps the lamp's colour, so where a "
          "warm and a cool lamp overlap, the shadow of one is lit in the colour of the other; the lamp light keeps "
          "the brightness the grey shadow gives it. Read at start; one image of 12 bytes a pixel more (25 MB at "
          "1920x1080), a little more work where a pixel has lamp light; passes that trace leaf cards "
          "(`BB_RT_CARD_LAMPS=1`) or keep `LANTERN_RT_LAMP_REUSE`'s history stay grey. `0`: one grey shadow ratio "
          "for all lamps | `0` |\n"),
]

# Text checks on the patched result (counts of whole strings).
CHECKS = {
    SHADER: [("#ifdef COLOUR\n", 25), ("bbport (r92_lamp-shadow-colour)", 25), ("uniform image2D colour_image;", 4),
             ("(f & (1u << 25u))", 1), ("colour_held = clamp(colour_held + (fitted - held_ratio), 0.0, 1.0);", 1)],
    CPP: [("_COLOUR_COMP", 6), ("_colour_comp.h\"", 6), ("#include \"video_core/host_shaders/point_shadow_ray_", 16),
          ("colour_mode ? 1u : 0u); // bbport (r92_lamp-shadow-colour)", 4), ("(ray_pushed, ray_push))", 1),
          ("ray_pushed, ray_push)); // bbport (r92)", 2), ("(half_pushed, half_push))", 1),
          ("data[tune_at] |= LampTuneColour;", 1), ("Ray traced lamps (r92): %u ray traced lamp passes", 1),
          (" colour (r92): ", 0)],
    HDR: [("bool colour_mode = false;", 1)],
    TUNE: [('"BB_LAMP_SHADOW_COLOUR"', 1), ("inline constexpr std::uint32_t LampTuneColour = 1u << 25;", 1)],
    CMAKE: [(" COLOUR=1)", 6)],
    README: [("| `BB_LAMP_SHADOW_COLOUR` |", 1)],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def apply_edits(path, text):
    for i, (old, new) in enumerate(EDITS[path]):
        if text.count(old) != 1:
            raise SystemExit("REFUSED %s edit %d: anchor found %d times: %r" % (path, i, text.count(old), old[:90]))
        text = text.replace(old, new)
    return text


def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, s, texts[path].count(s), n))
    for path, eds in EDITS.items():
        for old, new in eds:
            if not all(ord(c) < 128 for c in new) or "\r" in new:
                raise SystemExit("%s: new text must be ASCII with LF in the script" % path)
    sh = texts[SHADER]
    if sh.count("#if") != sh.count("#endif"):
        raise SystemExit("shader: #if and #endif do not pair")
    # (r92 review) the colour count is a line of its own after the r42 line's end, before ClearSteps
    cs = texts[CPP]
    end42 = cs.find('    std::printf("\\n");\n    line_blend = line_read = line_cuts = line_beside = line_half = 0;\n')
    ours = cs.find('Ray traced lamps (r92): %u ray traced lamp passes')
    clear = cs.find("    track.ClearSteps();\n")
    if not (0 <= end42 < ours < clear):
        raise SystemExit("text check: the r92 count line is not between the r42 line's end and ClearSteps")
    # the clamp's colour move sits in the window bound, before the ratio's history is moved
    a, b = sh.find("colour_held = clamp(colour_held + (fitted - held_ratio)"), sh.find("                held_ratio = fitted;\n")
    if not (0 <= a < b and sh.find("const float fitted = clamp(held_ratio,") < a):
        raise SystemExit("text check: the clamp's colour move is not between `fitted` and `held_ratio = fitted`")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R92_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(new) == 1 for old, new in edits)
        clean = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits):
            state = "applied"
        elif clean == len(edits):
            state = "clean"
        else:
            raise SystemExit("%s: %d of %d edits applied, %d anchors found once (another patch changed an "
                             "anchor?)" % (path, done, len(edits), clean))
        plan.append((path, raw, eol, cur, state))
    states = {p[4] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[4]) for p in plan))
    state = states.pop()
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[3] for p in plan})
            print("applied (text checks pass)")
        else:
            texts = {path: apply_edits(path, cur) for path, raw, eol, cur, _ in plan}
            text_checks(texts)
            print("not applied; would apply (%d files, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(e) for e in EDITS.values())))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts, outs = {}, []
        for path, raw, eol, cur, _ in plan:
            texts[path] = apply_edits(path, cur)
            outs.append((path, texts[path].replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r92tmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(ROOT, path))
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r92tmp"
                if os.path.exists(tmp):
                    os.remove(tmp)
            for path, raw in written:
                open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied (%d files)" % len(outs))
        return
    if state != "applied":
        print("nothing to revert")
        return
    for path, raw, eol, cur, _ in plan:
        for old, new in reversed(EDITS[path]):
            if cur.count(new) != 1:
                raise SystemExit("revert: %s: an edit's text is not there once" % path)
            cur = cur.replace(new, old)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    print("reverted (%d files)" % len(plan))


main()
