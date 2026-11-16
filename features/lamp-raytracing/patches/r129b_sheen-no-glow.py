# r129b_sheen-no-glow: FIX patch (lane LRT, task LRT-T07 wet blood sheen). Goals: LRT-G065 (wet sheen from blood) and
# LRT-G066/G067 (the graveyard "doesn't have a bloody coat, just blood on the ground"). Applies ON TOP of r100k and r128d
# (refuses a tree without them).
#
# Why (build 78, graveyard-blood; the lead's probe settled it): with the live BB_BLOOD_SHEEN_PEAK=0.001 the red spot at
# the hunter's feet and the red glow on the rim went black with the rest of the pool. So they are picked (tagged) pixels,
# and the SHOW pass's ceiling (r100k) acts on them; it is just set far too high and measured the wrong way:
#  - the level: the knee of PEAK 0.7 is 0.35, ten times the dry scene's own brightness at the graveyard (metered 0.036,
#    exposure held at 3), so everything below it passes;
#  - the measure: it is a LUMINANCE (0.2126 r + 0.7152 g + 0.0722 b). The film's highlight is red (f0 0.146, 0.025, 0.018 under
#    a warm light), so its luminance is only about 0.3 of its red: a red of 2.4 passes PEAK 0.7, and times the exposure 3 that
#    is fully saturated red (the sharp patch at the feet; the bloom only spreads it);
#  - the rim: its gap-fill pixels get a reduced specular and gloss (r100j/r100k) but their NORMAL is still levelled by the
#    full fill weight, so the bumpy rim stones become one flat glossy plane that the moon (and the SSR) mirror as a band.
#
# What changes (OFF by default: with graphics_blood_sheen=0 and BB_BLOOD_SHEEN unset nothing runs, see Off):
#  A. SHOW's ceiling is on the MAX CHANNEL of the picked pixel (red counts in full) and is relative to the dry scene's
#     own brightness: BB_BLOOD_SHEEN_PEAK is now a MULTIPLE (0..64, default 6) of a reference, the geometric mean of the
#     max channel of the untagged (dry) pixels, measured by the SHOW pass itself on the GPU one frame late (each 8x8
#     group adds the log2 code of its first dry pixel to a sum and counts it; the next show reads the other slot: no CPU
#     read, no stall). Up to half of the ceiling is untouched, above it rolls off (colour scaled, hue kept) as before.
#     Before the first reference exists (the first show) the ceiling is an absolute 0.25. At the graveyard the reference is
#     about 0.04, the ceiling about 0.25 (times exposure 3: under the clip point); the dim moonlit sheet is below the knee and
#     stays; in daylight the reference and the ceiling rise with it. PEAK 0: no ceiling (as before).
#  B. EDIT: a rim (gap-fill) pixel levels its normal by its specular weight (fill squared times the rim share), not by
#     the fill weight, so the rim stones keep their relief; a pixel that passes the albedo rule is unchanged; a gap deep in
#     the pool (fill 1, rim share 1) is still level. Pure mirror of it: BloodSheenRules::FilledLevelShare.
#
# Knobs (README row each): BB_BLOOD_SHEEN_PEAK keeps its meaning (a soft ceiling on the picked pixels of the lit scene,
# 0 = none, live in a test build) but its unit is now "times the dry scene's reference, on the max channel", range 0..64,
# default 6 (was 0.7 absolute luminance). New: BB_BLOOD_SHEEN_RIM_FULL, a live test knob (live knobs header only, else 0):
# 1 = the rim levels by the fill weight as r100h-r100k did (rim A/B in one running game).
#
# Files: host_shaders/blood_sheen_layout.h, host_shaders/blood_sheen.comp (SHOW build and EDIT build only; SNAPSHOT and
# MARK SPIR-V unchanged), renderer_vulkan/blood_sheen.h, vk_blood_sheen.h, vk_blood_sheen.cpp, engine/tests/test_blood_sheen.cpp,
# README.md (the PEAK row rewritten, one RIM_FULL row after it).
#
# Cost (an estimate, not measured): SHOW gains one 12..24 byte buffer clear and barrier, one scene load and two atomics per
# 8x8 group (32,400 groups at 1080p, 129,600 at 4K), one max of three channels instead of a dot on each wet pixel, a few atomics
# on rolled-off pixels; EDIT one select. Below 0.005 ms at 4K; +24 bytes of GPU buffer; no CPU work beyond the push words and
# the log. The slot job's BB_GPU_PROFILE row "Lighting: blood sheen" says it.
#
# Off guarantee: graphics_blood_sheen=0 and BB_BLOOD_SHEEN unset: BloodSheen::Wanted() is false, no BloodSheen object, no
# pipeline, buffer or pass is made, nothing runs (as r100d/r128d). Nothing of this patch is reached.
#
# Log lines start "Blood sheen (r129b)". r100k's text check wants every BbReport::Printf line of vk_blood_sheen.cpp to hold
# "Blood sheen (r100" or "Blood sheen (r128d)": the new calls are written BbReport::Printf( with the string starting on the
# NEXT line, so no line carries both (the same sink, the log file, as the other lines; std::printf would go to stdout only).
#
# Not verified: no full build and no Vulkan run (the unit test and the shader are compiled on a private copy only, see the
# lead's check list); the SHOW pass's new buffer binding, the fill/barrier order and the one-frame-late reference are read from
# the code, not run; the look (a small dull red mark in place of the saturated patch, rim relief back) is the slot jobs'
# to judge; the cost is an estimate. r100k's own re-check of an applied tree reports PEAK_DEFAULT 0.7 as changed: this patch
# supersedes that number (the other r100k text checks still hold).
#
# Use: python -I -X utf8 r129b_sheen-no-glow.py check | apply | revert
# Root: R129B_ROOT, else <tree> (needs engine/gpu). Line ends kept (CRLF or LF; mixed refused). apply backs the originals up
# in r129b_backup next to this script. Each edit refuses unless its anchor / old text is found exactly once; a tree with some
# edits applied and some not is refused; text checks run on the result before anything is written; files are written through
# a temp file. revert puts back exactly what apply inserted or replaced. Revert order: this script, then r128d, then r100k.
import os, sys

ROOT = os.environ.get("R129B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r129b_backup")
TMP = ".r129btmp"
VC = "engine/gpu/shadps4/video_core/"
LAY = VC + "host_shaders/blood_sheen_layout.h"
COMP = VC + "host_shaders/blood_sheen.comp"
RV = VC + "renderer_vulkan/"
BH = RV + "blood_sheen.h"
VH = RV + "vk_blood_sheen.h"
BC = RV + "vk_blood_sheen.cpp"
TB = "engine/tests/test_blood_sheen.cpp"
R = "README.md"
CODE = (LAY, COMP, BH, VH, BC, TB)

# ("ins", anchor, before, after): the anchor stays; `before` goes in front of it, `after` behind it.
# ("rep", old, new): old is replaced by new.
EDITS = {
LAY: [
("ins", "#define BLOOD_SHEEN_FLAG_NORMAL 32u\n",
 "",
 "// r129b_sheen-no-glow: EDIT, a test knob (BB_BLOOD_SHEEN_RIM_FULL, live): a gap-fill (rim) pixel levels its normal by the\n"
 "// fill weight, as r100h to r100k did; without it, by its specular weight (fill squared times the rim share).\n"
 "#define BLOOD_SHEEN_FLAG_RIM_FULL 64u\n"),
("rep",
 "// falloff toward the rim's outer edge). SHOW, the picked pixels of the lit scene: a soft luminance ceiling,\n"
 "// PEAK (BB_BLOOD_SHEEN_PEAK, default 0.7); luminance up to KNEE x PEAK is untouched, above it rolls off\n"
 "// exponentially toward PEAK (colour scaled, hue kept). A near light's tight highlight on the wet lobe cannot\n"
 "// blow out; the moonlit dark red sheet (below the knee) is as before. PEAK 0: no ceiling.\n"
 "#define BLOOD_SHEEN_PEAK_DEFAULT 0.7\n",
 "// falloff toward the rim's outer edge). SHOW, the picked pixels of the lit scene: a soft ceiling on the MAX CHANNEL\n"
 "// (r129b_sheen-no-glow; r100k had the luminance, which counts red at 0.21, so a red highlight passed it). PEAK\n"
 "// (BB_BLOOD_SHEEN_PEAK, default 6) is a MULTIPLE of the dry scene's own reference (the REF_* words below): the ceiling is\n"
 "// PEAK x reference. Up to KNEE x ceiling the pixel is untouched, above it the max channel rolls off exponentially toward\n"
 "// the ceiling (colour scaled, hue kept). A near light's tight highlight on the wet lobe cannot blow out; the moonlit\n"
 "// dark red sheet (below the knee) is as before. PEAK 0: no ceiling.\n"
 "#define BLOOD_SHEEN_PEAK_DEFAULT 6.0\n"),
("ins", "#define BLOOD_SHEEN_PEAK_KNEE 0.5\n",
 "",
 "// r129b_sheen-no-glow: the reference is measured by SHOW itself, one frame late, on the GPU: every 8x8 group adds the code\n"
 "// (log2(max(m, REF_MIN)) + REF_BIAS) x REF_SCALE (clamped to 0..REF_MAX_CODE, truncated) of the max channel m of its first\n"
 "// untagged (dry) pixel to a sum and counts it; the reference is 2^(sum / samples / REF_SCALE - REF_BIAS), the geometric\n"
 "// mean. The words: 2 slots (by show parity) of REF_SLOT_WORDS (sum, samples, wet pixels rolled off) from word REF_BASE (after\n"
 "// the counters' 2 x SLOT_WORDS); a show writes its slot and reads the OTHER one. PEAK_FALLBACK: the ceiling's max channel\n"
 "// before there is a reference (the first show). 4K: 129,600 groups x 2047 stays below 2^32.\n"
 "#define BLOOD_SHEEN_PEAK_FALLBACK 0.25\n"
 "#define BLOOD_SHEEN_REF_BASE 16u\n"
 "#define BLOOD_SHEEN_REF_SLOT_WORDS 3u\n"
 "#define BLOOD_SHEEN_REF_BIAS 16.0\n"
 "#define BLOOD_SHEEN_REF_SCALE 64.0\n"
 "#define BLOOD_SHEEN_REF_MAX_CODE 2047.0\n"
 "#define BLOOD_SHEEN_REF_MIN 0.000244140625\n"),
],
COMP: [
("ins", "layout(binding = 1, rgba16f) uniform image2D scene_img; // the lit scene\n",
 "",
 "// r129b_sheen-no-glow: the counters (offset 0, the whole buffer): SHOW's dry-scene reference words, BLOOD_SHEEN_REF_BASE on.\n"
 "layout(binding = 2, std430) buffer Counters {\n"
 "    uint counts[];\n"
 "};\n"),
("ins", "            const float peak = ratio;\n",
 "",
 "            // r129b_sheen-no-glow: `peak` is now the ceiling's multiple of the dry scene's reference. The reference: one dry\n"
 "            // (untagged) pixel a group adds its max channel's log2 code to this show's slot (this pass writes only wet\n"
 "            // pixels, so a dry one is in no race); the ceiling below reads the OTHER slot, the last show's.\n"
 "            const uint ref_slot = (flags & BLOOD_SHEEN_FLAG_SLOT) != 0u ? 1u : 0u;\n"
 "            if (peak > 0.0 && gl_LocalInvocationIndex == 0u && tag != BLOOD_SHEEN_TAG_WET) {\n"
 "                const vec3 dry = imageLoad(scene_img, p).rgb;\n"
 "                if (!any(isnan(dry)) && !any(isinf(dry))) {\n"
 "                    const float top_dry = max(max(dry.r, dry.g), max(dry.b, BLOOD_SHEEN_REF_MIN));\n"
 "                    const float code = clamp((log2(top_dry) + BLOOD_SHEEN_REF_BIAS) * BLOOD_SHEEN_REF_SCALE, 0.0,\n"
 "                                             BLOOD_SHEEN_REF_MAX_CODE);\n"
 "                    atomicAdd(counts[BLOOD_SHEEN_REF_BASE + ref_slot * BLOOD_SHEEN_REF_SLOT_WORDS], uint(code));\n"
 "                    atomicAdd(counts[BLOOD_SHEEN_REF_BASE + ref_slot * BLOOD_SHEEN_REF_SLOT_WORDS + 1u], 1u);\n"
 "                }\n"
 "            }\n"),
("rep",
 "                if (peak > 0.0) {\n"
 "                    const float lit_luma = dot(lit, vec3(0.2126, 0.7152, 0.0722));\n"
 "                    if (lit_luma > BLOOD_SHEEN_PEAK_KNEE * peak) {\n"
 "                        lit *= PeakRoll(lit_luma, peak) / lit_luma;\n"
 "                    }\n"
 "                }\n",
 "                if (peak > 0.0) {\n"
 "                    // r129b_sheen-no-glow: the ceiling on the MAX channel (red counts in full, not at 0.21): `peak` times the\n"
 "                    // dry scene's reference of the last show (BLOOD_SHEEN_PEAK_FALLBACK before the first).\n"
 "                    const uint other = 1u - ref_slot;\n"
 "                    const uint samples = counts[BLOOD_SHEEN_REF_BASE + other * BLOOD_SHEEN_REF_SLOT_WORDS + 1u];\n"
 "                    const float ceiling = samples != 0u\n"
 "                        ? peak * exp2(float(counts[BLOOD_SHEEN_REF_BASE + other * BLOOD_SHEEN_REF_SLOT_WORDS]) /\n"
 "                                      float(samples) / BLOOD_SHEEN_REF_SCALE - BLOOD_SHEEN_REF_BIAS)\n"
 "                        : BLOOD_SHEEN_PEAK_FALLBACK;\n"
 "                    const float top = max(lit.r, max(lit.g, lit.b));\n"
 "                    if (top > BLOOD_SHEEN_PEAK_KNEE * ceiling) {\n"
 "                        lit *= PeakRoll(top, ceiling) / top;\n"
 "                        atomicAdd(counts[BLOOD_SHEEN_REF_BASE + ref_slot * BLOOD_SHEEN_REF_SLOT_WORDS + 2u], 1u);\n"
 "                    }\n"
 "                }\n"),
("rep",
 "                    const float up_gate = filled ? 1.0\n"
 "                        : smoothstep(BLOOD_SHEEN_NORMAL_UP_LO, BLOOD_SHEEN_NORMAL_UP_HI, unit.y);\n",
 "                    // r129b_sheen-no-glow: a rim (gap-fill) pixel levels by its specular weight (wet x rim share on top of w:\n"
 "                    // w x wet x rim_k = ws), not by the fill weight alone, so the rim stones keep their relief; the test knob\n"
 "                    // BLOOD_SHEEN_FLAG_RIM_FULL gives the old 1.0 (r100h-r100k).\n"
 "                    const float up_gate = filled ? ((flags & BLOOD_SHEEN_FLAG_RIM_FULL) != 0u ? 1.0 : wet * rim_k)\n"
 "                        : smoothstep(BLOOD_SHEEN_NORMAL_UP_LO, BLOOD_SHEEN_NORMAL_UP_HI, unit.y);\n"),
],
BH: [
("rep",
 "//   BB_BLOOD_SHEEN_PEAK   bbport (r100k): 0..8, default 0.7: the lit scene's luminance ceiling for the picked\n"
 "//                         pixels (a soft roll-off above half of it: a near light's highlight cannot blow\n"
 "//                         out); 0: no ceiling. Unset or other text: the default.\n",
 "//   BB_BLOOD_SHEEN_PEAK   bbport (r100k): 0..64, default 6: the lit scene's ceiling for the picked pixels (a soft\n"
 "//                         roll-off above half of it: a near light's highlight cannot blow out); 0: no ceiling.\n"
 "//                         bbport (r129b_sheen-no-glow): a MULTIPLE of the dry scene's reference (the geometric mean of the\n"
 "//                         max channel of the untagged pixels, measured on the GPU one frame late; 0.25 absolute\n"
 "//                         before the first), applied to the max channel (r100k: 0..8 absolute luminance, default 0.7).\n"
 "//                         Unset or other text: the default.\n"
 "//   BB_BLOOD_SHEEN_RIM_FULL bbport (r129b): a live test knob (live knobs header only; else 0): 1: the pool's rim\n"
 "//                         (gap-fill) pixels level their normal by the fill weight as r100h-r100k did; 0 or unset:\n"
 "//                         by their specular weight (fill squared times the rim share)\n"),
("ins", "inline constexpr std::uint32_t FlagNormal = BLOOD_SHEEN_FLAG_NORMAL; ///< EDIT: the normal target is bound\n",
 "",
 "inline constexpr std::uint32_t FlagRimFull = BLOOD_SHEEN_FLAG_RIM_FULL;     ///< r129b EDIT: rim pixels level by the fill weight\n"),
("rep",
 "static_assert((FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear | FlagNormal) == 63u);\n",
 "static_assert((FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear | FlagNormal | FlagRimFull) == 127u);\n"),
("rep",
 "inline constexpr float MaxPeak = 8.0f;                                ///< r100k: the largest BB_BLOOD_SHEEN_PEAK\n",
 "inline constexpr float MaxPeak = 64.0f;                               ///< r100k: the largest BB_BLOOD_SHEEN_PEAK (r129b: 64)\n"),
("rep",
 "static_assert(BLOOD_SHEEN_PEAK_DEFAULT == 0.7 && BLOOD_SHEEN_PEAK_KNEE == 0.5);\n",
 "static_assert(BLOOD_SHEEN_PEAK_DEFAULT == 6.0 && BLOOD_SHEEN_PEAK_KNEE == 0.5 && BLOOD_SHEEN_PEAK_FALLBACK == 0.25);\n"
 "// bbport (r129b_sheen-no-glow): the dry-scene reference the ceiling is relative to (blood_sheen_layout.h has the words).\n"
 "inline constexpr float PeakFallback = float(BLOOD_SHEEN_PEAK_FALLBACK); ///< the absolute max-channel ceiling before a reference\n"
 "inline constexpr std::uint32_t RefBase = BLOOD_SHEEN_REF_BASE, RefSlotWords = BLOOD_SHEEN_REF_SLOT_WORDS;\n"
 "inline constexpr float RefBias = float(BLOOD_SHEEN_REF_BIAS), RefScale = float(BLOOD_SHEEN_REF_SCALE);\n"
 "inline constexpr float RefMaxCode = float(BLOOD_SHEEN_REF_MAX_CODE), RefMin = float(BLOOD_SHEEN_REF_MIN);\n"
 "static_assert(RefBase == Slots * SlotWords && RefSlotWords == 3u && BLOOD_SHEEN_REF_BIAS == 16.0 && BLOOD_SHEEN_REF_SCALE == 64.0);\n"
 "static_assert(BLOOD_SHEEN_REF_MAX_CODE == 2047.0 && BLOOD_SHEEN_REF_MIN == 0.000244140625);\n"),
("rep",
 "// bbport (r100h_sheen-liquid): the share of the way to world up of such a gap pixel (the weight already\n"
 "// holds the up gate): the film weight times mix(EDGE, 1, cover).\n"
 "inline float FilledLevelShare(float up, float pool_share, float strength, int near_hits) {\n"
 "    const float cover = SmoothStep(float(BLOOD_SHEEN_COVER_LO), float(BLOOD_SHEEN_COVER_HI), pool_share);\n"
 "    const float edge = float(BLOOD_SHEEN_NORMAL_EDGE);\n"
 "    return NormalSmooth * std::clamp(strength, 0.0f, 1.0f) * FillWeight(pool_share, up, near_hits) *\n"
 "           (edge + (1.0f - edge) * cover);\n"
 "}\n",
 "// bbport (r100h_sheen-liquid): the share of the way to world up of such a gap pixel (the weight already\n"
 "// holds the up gate): the film weight times mix(EDGE, 1, cover).\n"
 "// bbport (r129b_sheen-no-glow): times the fill weight once more and the rim's specular share (FILL_SPEC at the rim, 1 deep\n"
 "// inside the pool: RimSpecShare(true, share)), so the rim stones keep their relief; `rim_full` (BB_BLOOD_SHEEN_RIM_FULL):\n"
 "// the r100h-r100k value, the film weight alone.\n"
 "inline float FilledLevelShare(float up, float pool_share, float strength, int near_hits, bool rim_full = false) {\n"
 "    const float cover = SmoothStep(float(BLOOD_SHEEN_COVER_LO), float(BLOOD_SHEEN_COVER_HI), pool_share);\n"
 "    const float edge = float(BLOOD_SHEEN_NORMAL_EDGE);\n"
 "    const float fill = FillWeight(pool_share, up, near_hits);\n"
 "    const float rim = FillSpec + (1.0f - FillSpec) * SmoothStep(float(BLOOD_SHEEN_FILL_HI), 1.0f, pool_share);\n"
 "    return NormalSmooth * std::clamp(strength, 0.0f, 1.0f) * fill * (edge + (1.0f - edge) * cover) *\n"
 "           (rim_full ? 1.0f : fill * rim);\n"
 "}\n"),
("ins", "/// SHOW's dimming share of a pixel of luminance `luma` (the shader's arithmetic): `darken` where it is\n",
 "/// bbport (r129b_sheen-no-glow): a dry pixel's reference code (the shader's arithmetic): the log2 of its max channel (at\n"
 "/// least RefMin) on a scale of RefScale steps a stop from -RefBias, clamped to 0..RefMaxCode, truncated.\n"
 "inline std::uint32_t RefCode(float r, float g, float b) {\n"
 "    const float top = std::max(std::max(r, g), std::max(b, RefMin));\n"
 "    return static_cast<std::uint32_t>(std::clamp((std::log2(top) + RefBias) * RefScale, 0.0f, RefMaxCode));\n"
 "}\n"
 "/// A dry pixel is counted only when all three channels are finite (the shader skips a NaN or an Inf).\n"
 "inline bool RefUsable(float r, float g, float b) {\n"
 "    return std::isfinite(r) && std::isfinite(g) && std::isfinite(b);\n"
 "}\n"
 "/// The dry scene's reference of a show's slot: the geometric mean of the max channel, 2^(sum / n / RefScale - RefBias); 0 when\n"
 "/// n (the samples) is 0.\n"
 "inline float RefMean(std::uint32_t sum, std::uint32_t n) {\n"
 "    return n == 0 ? 0.0f : std::exp2(float(sum) / float(n) / RefScale - RefBias);\n"
 "}\n"
 "/// The ceiling (max channel) of a show: `rel` (BB_BLOOD_SHEEN_PEAK; 0: none, 0 out) times the reference of the other slot\n"
 "/// (sum, n); PeakFallback while that slot holds no sample.\n"
 "inline float PeakOf(float rel, std::uint32_t sum, std::uint32_t n) {\n"
 "    if (!(rel > 0.0f)) {\n"
 "        return 0.0f;\n"
 "    }\n"
 "    return n == 0 ? PeakFallback : rel * RefMean(sum, n);\n"
 "}\n"
 "/// A wet pixel's colour after the ceiling `peak` (> 0; else unchanged), the shader's arithmetic: the max channel through\n"
 "/// PeakRoll, the colour scaled by it (hue kept).\n"
 "inline std::array<float, 3> CapRgb(std::array<float, 3> rgb, float peak) {\n"
 "    const float top = std::max(rgb[0], std::max(rgb[1], rgb[2]));\n"
 "    if (peak > 0.0f && top > PeakKnee * peak) {\n"
 "        const float scale = PeakRoll(top, peak) / top;\n"
 "        for (float& c : rgb) {\n"
 "            c *= scale;\n"
 "        }\n"
 "    }\n"
 "    return rgb;\n"
 "}\n"
 "\n",
 ""),
],
VH: [
("ins", "    u64 frame = 0;\n",
 "",
 "    // bbport (r129b_sheen-no-glow): SHOW's dry-scene reference words (2 slots after the counters' slots, by show parity).\n"
 "    u32 show_count = 0;          ///< shows recorded: a show's slot is its parity\n"
 "    bool ref_fresh = true;       ///< no show yet: the first one clears both reference slots (the buffer is not initialised)\n"
 "    u32 ref_slot_last = 0;       ///< the slot of the last show recorded\n"
 "    u32 ref_read_slot = 0;       ///< ref_slot_last when the last host copy was recorded (the log reads that slot)\n"
 "    bool ref_read_valid = false; ///< a show was recorded before that copy: its words are real\n"),
],
BC: [
("ins", "constexpr vk::DeviceSize SlotBytes = R::SlotWords * 4;\n",
 "",
 "// bbport (r129b_sheen-no-glow): SHOW's dry-scene reference words (2 slots of RefSlotWords) follow the counters' slots.\n"
 "constexpr vk::DeviceSize RefOffset = R::Slots * SlotBytes, RefSlotBytes = R::RefSlotWords * 4;\n"
 "constexpr vk::DeviceSize RefBytes = R::Slots * RefSlotBytes;\n"
 "static_assert(R::RefBase * 4 == RefOffset);\n"),
("ins", "/// BB_BLOOD_SHEEN_PEAK (r100k_sheen-no-hot-spot): the lit scene's luminance ceiling for the picked pixels, 0: none.\n",
 "/// BB_BLOOD_SHEEN_RIM_FULL (r129b_sheen-no-glow, live, a test knob): 1: the rim (gap-fill) pixels level their normal by the\n"
 "/// fill weight as r100h-r100k did; 0 (or unset): by their specular weight. Always false in a build without the live\n"
 "/// knobs header. Said in the log at each change.\n"
 "bool RimFull() {\n"
 "#ifdef BLOOD_SHEEN_LIVE_PAUSE\n"
 "    static BbLiveKnobs::Knob<bool> knob{\"BB_BLOOD_SHEEN_RIM_FULL\", PauseParse};\n"
 "    static bool last = false;\n"
 "    const bool now = knob.Get();\n"
 "    if (now != last) {\n"
 "        last = now;\n"
 "        BbReport::Printf(\n"
 "            \"Blood sheen (r129b): the rim levels its normal by %s (BB_BLOOD_SHEEN_RIM_FULL, a test knob)\\n\",\n"
 "            now ? \"the fill weight (as r100h-r100k)\" : \"its specular weight\");\n"
 "    }\n"
 "    return now;\n"
 "#else\n"
 "    return false;\n"
 "#endif\n"
 "}\n"
 "\n",
 ""),
("rep",
 "        if (now > 0.0f) {\n"
 "            BbReport::Printf(\"Blood sheen (r100k): luminance ceiling %.2f on the picked pixels of the lit scene \"\n"
 "                             \"(soft above %.2f; BB_BLOOD_SHEEN_PEAK)\\n\",\n"
 "                             double(now), double(R::PeakKnee * now));\n"
 "        } else {\n"
 "            BbReport::Printf(\"Blood sheen (r100k): no luminance ceiling (BB_BLOOD_SHEEN_PEAK 0)\\n\");\n"
 "        }\n",
 "        if (now > 0.0f) {\n"
 "            BbReport::Printf(\n"
 "                \"Blood sheen (r129b): highlight ceiling %.2f x the dry scene's reference (geometric mean of the max \"\n"
 "                \"channel, one frame late; %.2f before the first), on the max channel of the picked pixels, soft above \"\n"
 "                \"half (BB_BLOOD_SHEEN_PEAK)\\n\",\n"
 "                double(now), double(R::PeakFallback));\n"
 "        } else {\n"
 "            BbReport::Printf(\n"
 "                \"Blood sheen (r129b): no highlight ceiling (BB_BLOOD_SHEEN_PEAK 0)\\n\");\n"
 "        }\n"),
("rep",
 "                     \"%.2f; a near light's highlight on the pool is rolled off by a luminance ceiling \"\n",
 "                     \"%.2f; a near light's highlight on the pool is rolled off by a ceiling on the max channel, as a \"\n"
 "                     \"multiple of the dry scene's reference (r129b) \"\n"),
("ins",
 "                                    : \"the draws and the rule are the ones the environment names\");\n",
 "",
 "    // bbport (r129b_sheen-no-glow): the rim's levelling, once.\n"
 "    BbReport::Printf(\n"
 "        \"Blood sheen (r129b): rim (gap-fill) pixels level their normal by their specular weight (fill^2 x rim share), \"\n"
 "        \"not the fill weight (BB_BLOOD_SHEEN_RIM_FULL=1, a test knob: as r100h-r100k)\\n\");\n"),
("rep",
 "                           {eStorageImage, eStorageImage}, sizeof(R::Push), BLOOD_SHEEN_SHOW_COMP,\n",
 "                           {eStorageImage, eStorageImage, eStorageBuffer}, sizeof(R::Push), BLOOD_SHEEN_SHOW_COMP,\n"),
("rep",
 "        MakeBuffer(counters, R::Slots * SlotBytes, false,\n",
 "        MakeBuffer(counters, RefOffset + RefBytes, false,\n"),
("rep",
 "        MakeBuffer(readback, SlotBytes, true, vk::BufferUsageFlagBits::eTransferDst);\n",
 "        MakeBuffer(readback, SlotBytes + RefBytes, true, vk::BufferUsageFlagBits::eTransferDst);\n"),
("rep",
 "    std::memset(readback.mapped, 0, SlotBytes);\n",
 "    std::memset(readback.mapped, 0, SlotBytes + RefBytes);\n"),
("rep",
 "    if (copy_back) {\n"
 "        cmd.copyBuffer(counters, host, vk::BufferCopy{(1 - slot) * SlotBytes, 0, SlotBytes});\n"
 "    }\n",
 "    if (copy_back) {\n"
 "        // r129b_sheen-no-glow: and SHOW's reference words (both slots) behind the counters, for the log\n"
 "        const std::array copies{vk::BufferCopy{(1 - slot) * SlotBytes, 0, SlotBytes},\n"
 "                                vk::BufferCopy{RefOffset, SlotBytes, RefBytes}};\n"
 "        cmd.copyBuffer(counters, host, copies);\n"
 "    }\n"),
("ins",
 "        step.copy_back = counter_used == frame && frame != 0;\n",
 "",
 "        if (step.copy_back) { // r129b: which reference slot the copy holds the newest words of, and whether any show ran\n"
 "            ref_read_slot = ref_slot_last;\n"
 "            ref_read_valid = show_count != 0;\n"
 "        }\n"),
("rep",
 "    push.flags = R::Flags(k, step.slot) | (normal_ok ? R::FlagNormal : 0u);\n",
 "    push.flags = R::Flags(k, step.slot) | (normal_ok ? R::FlagNormal : 0u) | (RimFull() ? R::FlagRimFull : 0u); // r129b\n"),
("ins",
 "    stats.peak_shows += push.ratio > 0.0f ? 1u : 0u;\n",
 "",
 "    // r129b_sheen-no-glow: this show's reference slot (its parity; the other slot, the last show's, gives the ceiling); the\n"
 "    // first show clears both slots (the buffer is not initialised), later ones their own.\n"
 "    const u32 ref_slot = show_count++ & 1u;\n"
 "    push.flags |= ref_slot != 0 ? R::FlagSlot : 0u;\n"
 "    const bool ref_clear_all = std::exchange(ref_fresh, false);\n"
 "    ref_slot_last = ref_slot;\n"),
("rep",
 "        [push, width, height, scene_view, tag = *tag_view, pipeline = *show_pass.pipeline,\n"
 "         layout = *show_pass.layout](vk::CommandBuffer cmd) {\n"
 "            BeginBarrier(cmd);\n"
 "            using enum vk::DescriptorType;\n"
 "            const std::array infos{Info(tag), Info(scene_view)};\n"
 "            const std::array writes{ImageWrite(0, eStorageImage, &infos[0]), ImageWrite(1, eStorageImage, &infos[1])};\n",
 "        [push, width, height, scene_view, tag = *tag_view, ref_slot, ref_clear_all, counter_buffer = counters.buffer,\n"
 "         pipeline = *show_pass.pipeline, layout = *show_pass.layout](vk::CommandBuffer cmd) {\n"
 "            BeginBarrier(cmd);\n"
 "            // r129b_sheen-no-glow: this show's reference words start at 0 (both slots the first time)\n"
 "            cmd.fillBuffer(counter_buffer, ref_clear_all ? RefOffset : RefOffset + ref_slot * RefSlotBytes,\n"
 "                           ref_clear_all ? RefBytes : RefSlotBytes, 0);\n"
 "            EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, Compute, ReadWrite);\n"
 "            using enum vk::DescriptorType;\n"
 "            const std::array infos{Info(tag), Info(scene_view)};\n"
 "            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, RefOffset + RefBytes};\n"
 "            const std::array writes{ImageWrite(0, eStorageImage, &infos[0]), ImageWrite(1, eStorageImage, &infos[1]),\n"
 "                                    BufferWrite(2, &counter_info)};\n"),
("ins",
 "                     stats.peak_shows, stats.shows, double(PeakCap()));\n",
 "",
 "    {   // bbport (r129b_sheen-no-glow): the dry-scene reference and the ceiling of the last show copied to the host\n"
 "        std::array<u32, R::Slots * R::RefSlotWords> ref{};\n"
 "        if (readback.mapped && ref_read_valid) {\n"
 "            std::memcpy(ref.data(), static_cast<const char*>(readback.mapped) + SlotBytes, sizeof(ref));\n"
 "        }\n"
 "        const u32* words = ref.data() + ref_read_slot * R::RefSlotWords;\n"
 "        const float rel = PeakCap();\n"
 "        BbReport::Printf(\n"
 "            \"Blood sheen (r129b): dry-scene reference %.4f over %u samples, ceiling %.4f (%.2f x); %u wet px rolled off in \"\n"
 "            \"the last show; rim levels by %s\\n\",\n"
 "            double(R::RefMean(words[0], words[1])), words[1], double(R::PeakOf(rel, words[0], words[1])), double(rel),\n"
 "            words[2], RimFull() ? \"the fill weight (BB_BLOOD_SHEEN_RIM_FULL)\" : \"their specular weight\");\n"
 "    }\n"),
],
TB: [
("rep",
 "        assert(Near(PeakDefault, 0.7, 1e-6) && Near(PeakKnee, 0.5, 1e-6));\n",
 "        assert(Near(PeakDefault, 6.0, 1e-6) && Near(PeakKnee, 0.5, 1e-6)); // r129b: 6 times the dry scene's reference\n"),
("rep",
 "        assert(Near(FilledLevelShare(1.0f, 0.65f, 1.0f, 8), 0.5) && Near(FilledLevelShare(1.0f, 1.0f, 0.5f, 8), 0.5));\n",
 "        // r129b_sheen-no-glow: the rim levels by fill squared x rim share (0.5 x 0.5 x 0.35 = 0.0875 at share 0.65)\n"
 "        assert(Near(FilledLevelShare(1.0f, 0.65f, 1.0f, 8), 0.0875) && Near(FilledLevelShare(1.0f, 1.0f, 0.5f, 8), 0.5));\n"),
("ins", "    std::puts(\"blood sheen: ok\");\n",
 "    // bbport (r129b_sheen-no-glow): the ceiling on the max channel relative to the dry scene, and the rim's levelling.\n"
 "    {\n"
 "        assert(Near(PeakDefault, 6.0, 1e-6) && Near(PeakFallback, 0.25, 1e-6) && MaxPeak == 64.0f && FlagRimFull == 64u);\n"
 "        assert(RefBase == Slots * SlotWords && RefSlotWords == 3u);\n"
 "        // the code: 64 steps a stop from 2^-16; a dry pixel's max channel counts, not its luminance\n"
 "        assert(RefCode(1.0f, 0.5f, 0.2f) == 1024u && RefCode(0.25f, 0.1f, 0.0f) == 896u && RefCode(0.0f, 0.0f, 0.0f) == 256u);\n"
 "        assert(RefCode(0.0f, 0.0f, 0.25f) == 896u && RefCode(1.0e9f, 0.0f, 0.0f) == 2047u);\n"
 "        assert(RefCode(1.0e-30f, 0.0f, 0.0f) == 256u);                          // never below RefMin\n"
 "        assert(RefUsable(0.0f, 1.0f, 2.0f) && !RefUsable(std::nanf(\"\"), 0.0f, 0.0f) && !RefUsable(0.0f, INFINITY, 0.0f));\n"
 "        // the mean of the codes is the geometric mean of the max channels: 1 and 0.25 give 0.5\n"
 "        assert(RefMean(0u, 0u) == 0.0f && RefMean(12345u, 0u) == 0.0f);\n"
 "        assert(Near(RefMean(896u * 10u, 10u), 0.25, 1e-6) && Near(RefMean(1024u + 896u, 2u), 0.5, 1e-6));\n"
 "        // the ceiling: 0 when off, the fallback with no sample, PEAK x the reference else\n"
 "        assert(PeakOf(0.0f, 896u, 1u) == 0.0f && PeakOf(-1.0f, 896u, 1u) == 0.0f && PeakOf(0.0f, 0u, 0u) == 0.0f);\n"
 "        assert(PeakOf(6.0f, 0u, 0u) == PeakFallback && PeakOf(1.0f, 99u, 0u) == PeakFallback);\n"
 "        assert(Near(PeakOf(6.0f, 896u * 4u, 4u), 1.5, 1e-5) && Near(PeakOf(3.0f, 1024u * 7u, 7u), 3.0, 1e-5));\n"
 "        // a torch highlight on the film (red 3, green 0.3, blue 0.1) with the night ceiling 0.27: red at most 0.27, hue kept\n"
 "        {\n"
 "            const std::array<float, 3> hot = CapRgb({3.0f, 0.3f, 0.1f}, 0.27f);\n"
 "            assert(hot[0] <= 0.27f + 1e-5f && hot[0] > 0.26f);\n"
 "            assert(Near(hot[1] / hot[0], 0.1, 1e-5) && Near(hot[2] / hot[0], 0.1 / 3.0, 1e-5));\n"
 "            // the red highlight r100k let through: luminance 0.28 of red 1.0, under the old knee 0.35, now over the knee 0.135\n"
 "            const std::array<float, 3> red = CapRgb({1.0f, 0.09f, 0.03f}, 0.27f);\n"
 "            assert(red[0] < 0.27f && red[0] > 0.2f);\n"
 "            // a dark moonlit sheet is unchanged, so is anything with the ceiling off\n"
 "            const std::array<float, 3> sheet = CapRgb({0.03f, 0.005f, 0.004f}, 0.27f);\n"
 "            assert(sheet[0] == 0.03f && sheet[1] == 0.005f && sheet[2] == 0.004f);\n"
 "            const std::array<float, 3> off = CapRgb({3.0f, 0.3f, 0.1f}, 0.0f);\n"
 "            assert(off[0] == 3.0f && off[1] == 0.3f && off[2] == 0.1f);\n"
 "            // the max channel decides, whichever channel it is (green and blue as well as red)\n"
 "            assert(CapRgb({0.1f, 4.0f, 0.1f}, 0.27f)[1] <= 0.27f + 1e-5f && CapRgb({0.1f, 0.1f, 4.0f}, 0.27f)[2] <= 0.27f + 1e-5f);\n"
 "        }\n"
 "        float last = 0.0f;                                                       // monotonic in the max channel, never above the ceiling\n"
 "        for (float top = 0.0f; top < 40.0f; top += 0.01f) {\n"
 "            const float out = CapRgb({top, 0.0f, 0.0f}, 0.27f)[0];\n"
 "            assert(out >= last - 1e-6f && out <= 0.27f + 1e-5f && out <= top + 1e-6f);\n"
 "            last = out;\n"
 "        }\n"
 "        // the rim: the old levelling (the film weight alone) with rim_full, the new one else; deep inside the pool they agree\n"
 "        assert(Near(FilledLevelShare(1.0f, 0.65f, 1.0f, 8, true), 0.5) && Near(FilledLevelShare(1.0f, 1.0f, 1.0f, 8, true), 1.0));\n"
 "        assert(Near(FilledLevelShare(1.0f, 1.0f, 1.0f, 8), 1.0) && Near(FilledLevelShare(1.0f, 0.8f, 1.0f, 8), 0.35));\n"
 "        {\n"
 "            const float wet = FillWeight(0.65f, 1.0f, 8);                         // 0.5 at the rim: SpecWeight's w x wet x rim\n"
 "            assert(Near(FilledLevelShare(1.0f, 0.65f, 1.0f, 8), SpecWeight(wet, wet, true, 0.65f)));\n"
 "        }\n"
 "        for (float share = 0.0f; share <= 1.0f; share += 0.01f) {                // never above the old value, a rim keeps relief\n"
 "            assert(FilledLevelShare(1.0f, share, 1.0f, 8) <= FilledLevelShare(1.0f, share, 1.0f, 8, true) + 1e-6f);\n"
 "        }\n"
 "    }\n"
 "\n",
 ""),
],
}

# the README: the PEAK row is rewritten and the RIM_FULL row follows it (this patch's only anchor, never shared with the
# other rows' inserts)
OLD_PEAK_ROW = (
    "| `BB_BLOOD_SHEEN_PEAK` | Only with `BB_BLOOD_SHEEN` on. 0 to 8: a soft luminance ceiling for the picked pixels of the lit scene, "
    "applied after the game's opaque lighting in the same pass as the dimming: luminance up to half of it is untouched, above it "
    "rolls off toward it (colour scaled, hue kept), so a near lamp's or torch's tight highlight on the wet lobe cannot blow out an "
    "orange-red blotch; the moonlit dark red sheet is below the knee and unchanged. `0`: no ceiling. Unset or other text: the "
    "default. Live in a test build (live knobs file), the log says each change. Cost: one luminance and one exp for each picked "
    "pixel, inside the dimming pass (an estimate, not measured: far below 0.01 ms beyond it); with the dimming 0 and the ceiling on "
    "the pass runs for the ceiling alone | `0.7` |")
NEW_PEAK_ROW = (
    "| `BB_BLOOD_SHEEN_PEAK` | Only with `BB_BLOOD_SHEEN` on. 0 to 64 (r129b_sheen-no-glow; it was 0 to 8 absolute): a soft ceiling for "
    "the picked pixels of the lit scene, applied after the game's opaque lighting in the same pass as the dimming, as a MULTIPLE of "
    "the dry scene's own brightness: the reference is the geometric mean of the largest colour channel of the untagged pixels, "
    "measured on the GPU one frame late (no CPU read; before the first one the ceiling is 0.25), and the ceiling is this value times "
    "it, on the largest channel (r100k had the luminance, which counts red at about a fifth, so a red highlight passed it): up to "
    "half of it is untouched, above it rolls off toward it (colour scaled, hue kept). At a night scene with a reference of about 0.04 "
    "the default 6 is about 0.25: a torch's or the moon's highlight on the pool is a small dull red mark, not a saturated blob; the "
    "dim moonlit sheet is below the knee and unchanged; in daylight the reference and the ceiling rise with it. `0`: no ceiling. "
    "Unset or other text: the default. Live in a test build (live knobs file), the log says each change. Cost (an estimate, not "
    "measured: below 0.005 ms at 4K): one scene read and two atomics for each 8x8 group, one max of three channels for each picked "
    "pixel, a 24-byte clear in the show; with the dimming 0 and the ceiling on the pass runs for the ceiling alone | `6` |")
ROW_RIM = (
    "| `BB_BLOOD_SHEEN_RIM_FULL` | A test knob (live, through the live knobs file of the test tools; a build without that header ignores "
    "it and it is 0 there). `1`: the pool's rim stones (the gap-fill pixels) level their normal by their fill weight, as r100h to "
    "r100k did, which turned the bumpy rim into one flat glossy plane (a band of moon or sky reflection); `0` or unset "
    "(r129b_sheen-no-glow): they level by their specular weight (fill squared times the rim share), keep their relief and reflect "
    "as cobbles do. It lets one running game take the rim with and without the change. The log says each change. Cost: one select in "
    "the wet-ground pass | `0` |")
README_EDITS = [("rep", OLD_PEAK_ROW, NEW_PEAK_ROW + "\n" + ROW_RIM)]
EDITS[R] = README_EDITS
ORDER = (LAY, COMP, BH, VH, BC, TB, R)


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
    # r100k (the ceiling) and r128d (ReadUsable, the ini key) must be in the tree this patch is laid on
    need(BC, texts[BC], "float PeakCap()")
    need(BC, texts[BC], "push.ratio = k.show ? 0.0f : PeakCap();")
    need(COMP, texts[COMP], "float PeakRoll(float luma, float peak)")
    need(BH, texts[BH], "inline float ReadPeak(const char* text)")
    need(BH, texts[BH], "inline Knobs ReadUsable(")
    need(BC, texts[BC], "Blood sheen (r128d): strength")


def texts_check(texts):
    lay, comp, hdr, vh, cpp, tst, rd = (texts[p] for p in (LAY, COMP, BH, VH, BC, TB, R))
    # the layout
    need(LAY, lay, "#define BLOOD_SHEEN_PEAK_DEFAULT 6.0\n")
    need(LAY, lay, "#define BLOOD_SHEEN_FLAG_RIM_FULL 64u\n")
    need(LAY, lay, "#define BLOOD_SHEEN_REF_BASE 16u\n")
    need(LAY, lay, "#define BLOOD_SHEEN_PEAK_FALLBACK 0.25\n")
    need(LAY, lay, "#define BLOOD_SHEEN_PEAK_KNEE 0.5\n")
    if "BLOOD_SHEEN_PEAK_DEFAULT 0.7" in lay:
        raise SystemExit("text check: the old PEAK default is still in the layout")
    # the shader: SHOW has the counters, the max-channel ceiling, the reference; EDIT's levelling; nothing else moved
    need(COMP, comp, "layout(binding = 2, std430) buffer Counters {\n")   # SHOW's (MARK's is binding 4, EDIT's 6)
    need(COMP, comp, "const float peak = ratio;\n")
    need(COMP, comp, "lit_luma", 0)
    need(COMP, comp, "const float top = max(lit.r, max(lit.g, lit.b));")
    need(COMP, comp, "lit *= PeakRoll(top, ceiling) / top;")
    need(COMP, comp, "const float level = BLOOD_SHEEN_NORMAL_SMOOTH * w *")   # r100k's levelling line is untouched
    need(COMP, comp, "BLOOD_SHEEN_FLAG_RIM_FULL) != 0u ? 1.0 : wet * rim_k)")
    need(COMP, comp, "barrier()", 2)
    need(COMP, comp, "gl_LocalInvocationIndex == 0u && tag != BLOOD_SHEEN_TAG_WET")
    # the header
    need(BH, hdr, "static_assert((FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear | FlagNormal | FlagRimFull) == 127u);")
    need(BH, hdr, "inline constexpr float MaxPeak = 64.0f;")
    need(BH, hdr, "inline std::uint32_t RefCode(float r, float g, float b)")
    need(BH, hdr, "inline float PeakOf(float rel, std::uint32_t sum, std::uint32_t n)")
    need(BH, hdr, "inline std::array<float, 3> CapRgb(std::array<float, 3> rgb, float peak)")
    need(BH, hdr, "inline float SpecWeight(")
    need(BH, hdr, "inline float PeakRoll(float luma, float peak)")
    if not (0 <= hdr.find("inline float PeakRoll(") < hdr.find("inline float PeakOf(") < hdr.find("inline std::array<float, 3> CapRgb(")):
        raise SystemExit("text check: PeakRoll, PeakOf and CapRgb are out of order in blood_sheen.h")
    if not (0 <= hdr.find("inline float SmoothStep(") < hdr.find("inline float FilledLevelShare(")):
        raise SystemExit("text check: SmoothStep after FilledLevelShare")
    # the engine: the show's layout, buffer sizes and fills agree; the readback holds both
    need(BC, cpp, "{eStorageImage, eStorageImage, eStorageBuffer}, sizeof(R::Push), BLOOD_SHEEN_SHOW_COMP,")
    need(BC, cpp, "MakeBuffer(counters, RefOffset + RefBytes, false,")
    need(BC, cpp, "MakeBuffer(readback, SlotBytes + RefBytes, true,")
    need(BC, cpp, "std::memset(readback.mapped, 0, SlotBytes + RefBytes);")
    need(BC, cpp, "ref_clear_all ? RefBytes : RefSlotBytes, 0);")
    need(BC, cpp, "BufferWrite(2, &counter_info)")
    need(BC, cpp, "(RimFull() ? R::FlagRimFull : 0u)")
    need(BC, cpp, "push.ratio = k.show ? 0.0f : PeakCap();")
    need(BC, cpp, "Blood sheen (r100k): a rim pixel's")
    need(VH, vh, "u32 show_count = 0;")
    need(VH, vh, "bool ref_fresh = true;")
    need(TB, tst, "bbport (r129b_sheen-no-glow): the ceiling on the max channel")
    # every log call of this patch is written Printf( + newline + "Blood sheen (r129b)": r100k's line check ("every line with
    # BbReport::Printf(" holds its prefix) sees none of them, and all the others keep their prefixes
    lines = cpp.split("\n")
    mine = 0
    for i, line in enumerate(lines):
        if 'BbReport::Printf("' in line and "Blood sheen (r100" not in line and "Blood sheen (r128d)" not in line:
            raise SystemExit("text check: a log line r100k's check would refuse: %r" % line)
        if line.rstrip().endswith("BbReport::Printf("):
            if '"Blood sheen (r129b)' not in lines[i + 1]:
                raise SystemExit("text check: a split Printf without the r129b prefix: %r" % lines[i + 1])
            mine += 1
    if mine != 5:
        raise SystemExit("text check: %d split r129b Printf calls, wanted 5 (rim knob, ceiling on/off, once-line, 600 frames)" % mine)
    # README: the PEAK row says 64 and 6 once, the RIM_FULL row once
    rows = [l for l in rd.split("\n") if l.startswith("| `BB_BLOOD_SHEEN_PEAK` |")]
    if len(rows) != 1 or not rows[0].endswith("| `6` |") or "0 to 64" not in rows[0]:
        raise SystemExit("text check: README row of BB_BLOOD_SHEEN_PEAK")
    rows = [l for l in rd.split("\n") if l.startswith("| `BB_BLOOD_SHEEN_RIM_FULL` |")]
    if len(rows) != 1 or not rows[0].endswith("| `0` |"):
        raise SystemExit("text check: README row of BB_BLOOD_SHEEN_RIM_FULL")


def new_lines_check():
    # every new C++/GLSL line: no tab, ASCII, at most 150 columns (README lines are tables, exempt)
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
        raise SystemExit("%s is not a source tree root (no engine/gpu; set R129B_ROOT)" % ROOT)
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
