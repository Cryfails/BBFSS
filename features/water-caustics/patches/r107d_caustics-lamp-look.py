# r107d_caustics-lamp-look: FEATURE follow-up to r107c_caustics-lamp-gain.py (applies ON TOP of r107,
# r107b and r107c; branch when published: visual/glass-water). Context:
# bbfss-ctx-glass-water-caustics.md, section "2026-11-15 r107d".
#
# r107c at the sewer (batch b17): one lamp, colour up to 0.2, 13,726 px lit, +0.9% of their own,
# lamp model 0.05 of it. This step:
#  1. MEASURE units or dominance: 7 bins of the lamps' modelled direct light (2 stops a bin) over
#     every band pixel it reaches, each with the mean of that light over the pixel's own, and the
#     same over the brightest tenth (new log line "Water caustics (r107d)"). The game's lamp shader
#     (0x7cc2c044, decompiled from the shader cache) writes diffuse light = colour (record words
#     4-6) x (1 - d/r)^2 (the curve LocalFalloff patches) x N.L x its shadow mask x (1 - spec^2 / 2)
#     into a light buffer without albedo: the model's form is the game's; the combine that applies
#     the albedo was not read.
#  2. LOOK control: BB_CAUSTICS_LAMPS above 1 keeps the lamps' light at strength 1 and multiplies ALL
#     the light of a receiver near lit water by the pattern's contrast (mean 1, capped: 1 - look to
#     1 + 1.69 x look, look 0.6 at 4); crossings hidden behind something nearer count for it.
#
# Files: r107's own only (host_shaders/caustics.comp, caustics_layout.h; renderer_vulkan/
# caustics_params.h, vk_caustics.cpp; tests/test_caustics.cpp; README.md: r107's two rows). The
# counter slots grow from 16 to 32 words (buffer 2048 -> 2560 bytes). No new file, no new binding.
#
# Off (BB_CAUSTICS and BB_CAUSTICS_LAMPS unset): as r107: the rasterizer makes no Caustics.
#
# Use: python -I -X utf8 r107d_caustics-lamp-look.py check | apply | revert. Root from R107D_ROOT,
# R107C_ROOT, R107B_ROOT or R107_ROOT, else <tree>. Each edit is an exact text (old -> new)
# found exactly once; "applied" = every new text once and its old one gone, "clean" = every old
# text once and no new one; anything else is refused (exit 1, nothing written). Line ends are kept
# (CRLF in the tree). apply keeps the touched files in r107d_backup/ next to this script. Revert
# r107d BEFORE r107c (r107b's and r107c's checks fail on r107d's 32-word slots). Exit: 0 done,
# 1 refused, 2 usage.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r107d_backup")
ROOT = (os.environ.get("R107D_ROOT") or os.environ.get("R107C_ROOT") or os.environ.get("R107B_ROOT")
        or os.environ.get("R107_ROOT") or "<tree>")
V = "engine/gpu/shadps4/video_core/"

EDITS = {
    'engine/gpu/shadps4/video_core/host_shaders/caustics.comp': [
        ('// dry ground; off the screen or hidden behind something nearer: grey (the screen cannot tell).\n#version 450\n',
         "// dry ground; off the screen or hidden behind something nearer: grey (the screen cannot tell).\n// bbport (r107d_caustics-lamp-look): the look (CAUSTICS_DATA_LOOK, BB_CAUSTICS_LAMPS above 1)\n// multiplies all the light a receiver near lit water has by the pattern's contrast (mean 1;\n// caustics_layout.h); the log's bins of the modelled lamp light over the pixel's own.\n#version 450\n"),
        ('        const float lamp_gain = uintBitsToFloat(Data(CAUSTICS_DATA_GAIN)); // r107c\n        for (uint k = 0u; k < lamps; ++k) {\n',
         '        const float lamp_gain = uintBitsToFloat(Data(CAUSTICS_DATA_GAIN)); // r107c\n        const float look = uintBitsToFloat(Data(CAUSTICS_DATA_LOOK));     // r107d\n        float look_w = 0.0, look_c = 0.0;\n        for (uint k = 0u; k < lamps; ++k) {\n'),
        ('                unseen = unseen || crossing != AT_DRY;\n                continue;\n            }\n',
         "                unseen = unseen || crossing != AT_DRY;\n                if (!(look > 0.0 && crossing == AT_HIDDEN)) {\n                    continue;\n                }\n            }\n            const float pattern = Pattern(X.xz);\n            if (look > 0.0) {\n                // r107d: the look's weight and the pattern's contrast of this lamp's crossing.\n                const float w = facing * exp(-length(X - Pw) / CAUSTICS_PATH_FALLOFF);\n                look_w += w;\n                look_c += w * (1.0 - exp(-CAUSTICS_LAMP_GAIN * CAUSTICS_WATER_F0 * pattern));\n            }\n            if (crossing > AT_BELOW) {\n                continue; // hidden: the look only\n            }\n"),
        ('            added += colour * (LampCurve(d / reach) * facing *\n                               (1.0 - exp(-lamp_gain * reflectance * Pattern(X.xz))));\n        }\n',
         '            added += colour * (LampCurve(d / reach) * facing *\n                               (1.0 - exp(-lamp_gain * reflectance * pattern)));\n        }\n        if (look_w > 0.0) {\n            // r107d: all the light here, moved by the pattern (mean 1, capped by its range).\n            factor *= 1.0 + look * min(look_w, 1.0) *\n                                (1.0 - smoothstep(CAUSTICS_FADE_START, CAUSTICS_FADE_END, P.z)) *\n                                (look_c / (look_w * CAUSTICS_LOOK_MEAN) - 1.0);\n            atomicAdd(group_counts[CAUSTICS_W_LOOK], 1u);\n        }\n'),
        ('    }\n    if (factor == 1.0 && tint_k <= 0.0 && !(dot(added, LUMA) > 0.0)) {\n        return;\n',
         '    }\n    const bool measure = dot(direct, LUMA) > 0.0; // r107d: the bins\n    if (factor == 1.0 && tint_k <= 0.0 && !(dot(added, LUMA) > 0.0) && !measure) {\n        return;\n'),
        ('    const vec4 s = imageLoad(scene_img, p);\n    vec3 rgb = s.rgb * factor;\n',
         '    const vec4 s = imageLoad(scene_img, p);\n    if (measure) {\n        const float model = dot(direct, LUMA);\n        const int bin = clamp(int(floor(0.5 * log2(model))) + 6, 0, CAUSTICS_BINS - 1);\n        atomicAdd(group_counts[CAUSTICS_W_BIN_COUNT + bin], 1u);\n        atomicAdd(group_counts[CAUSTICS_W_BIN_RATIO + bin],\n                  uint(min(model / max(dot(max(s.rgb, vec3(0.0)), LUMA), 1e-4), CAUSTICS_MODEL_MAX) *\n                           CAUSTICS_MODEL_SCALE + 0.5));\n        if (factor == 1.0 && tint_k <= 0.0 && !(dot(added, LUMA) > 0.0)) {\n            return;\n        }\n    }\n    vec3 rgb = s.rgb * factor;\n'),
    ],
    'engine/gpu/shadps4/video_core/host_shaders/caustics_layout.h': [
        ('// word 11. At most 1024 a pixel each: 4 million lit pixels a dispatch fit in a word.\n#define CAUSTICS_SLOT_WORDS 16\n#define CAUSTICS_SLOTS 8\n',
         "// word 11. At most 1024 a pixel each: 4 million lit pixels a dispatch fit in a word.\n// bbport (r107d_caustics-lamp-look): CAUSTICS_BINS bins of the lamps' own direct light as modelled\n// (luminance, albedo included; bin 0 below 2^-10, then 2 stops a bin, the last 1 and above), over\n// every pixel in the band the modelled light reaches: from CAUSTICS_W_BIN_COUNT their counts, from\n// CAUSTICS_W_BIN_RATIO that light over the pixel's own as word 15 sums it (the log's check of the\n// model's units: near 1 where the lamps light a pixel); CAUSTICS_W_LOOK pixels the look changed.\n#define CAUSTICS_SLOT_WORDS 32\n#define CAUSTICS_SLOTS 8\n"),
        ('#define CAUSTICS_MODEL_MAX 8.0\n\n',
         '#define CAUSTICS_MODEL_MAX 8.0\n#define CAUSTICS_BINS 7\n#define CAUSTICS_W_BIN_COUNT 16\n#define CAUSTICS_W_BIN_RATIO 23\n#define CAUSTICS_W_LOOK 30\n\n'),
        ('#define CAUSTICS_DATA_ENERGY 11\n#define CAUSTICS_DATA_LAMPS 16\n',
         "#define CAUSTICS_DATA_ENERGY 11\n// bbport (r107d_caustics-lamp-look): the look's amount (float; 0: off).\n#define CAUSTICS_DATA_LOOK 12\n#define CAUSTICS_DATA_LAMPS 16\n"),
        ('#define CAUSTICS_LAMP_GAIN 30.0\n\n',
         "#define CAUSTICS_LAMP_GAIN 30.0\n// bbport (r107d_caustics-lamp-look): BB_CAUSTICS_LAMPS above 1 adds a look control: the lamps'\n// light above stays at strength 1, and ALL the light a receiver has (the scene's colour, whatever\n// lit it) is multiplied by 1 + look x min(w, 1) x fade x (c - 1). look = CAUSTICS_LOOK_MAX x\n// (strength - 1) / 3 (strength 4: CAUSTICS_LOOK_MAX); w = the sum over the lamps whose path crosses\n// water of facing x exp(-the crossing's distance / CAUSTICS_PATH_FALLOFF) (here a crossing hidden\n// behind something nearer counts as water: the screen cannot tell); c = their weighted mean of\n// (1 - exp(-CAUSTICS_LAMP_GAIN x CAUSTICS_WATER_F0 x the pattern)) / CAUSTICS_LOOK_MEAN, mean 1,\n// from 0 to 2.69: light is moved, not added; the factor stays from 1 - look to 1 + 1.69 x look.\n#define CAUSTICS_LOOK_MAX 0.6\n#define CAUSTICS_LOOK_MEAN 0.372\n\n"),
    ],
    'engine/gpu/shadps4/video_core/renderer_vulkan/caustics_params.h': [
        ("//   BB_CAUSTICS_LAMPS   bbport (r107b_caustics-visible): the lamps' caustics, as BB_CAUSTICS reads\n//                       its text (show: the test view at strength 1); on without BB_CAUSTICS too\n//\n",
         "//   BB_CAUSTICS_LAMPS   bbport (r107b_caustics-visible): the lamps' caustics, as BB_CAUSTICS reads\n//                       its text (show: the test view at strength 1); on without BB_CAUSTICS too.\n//                       r107d: above 1 the lamps' light stays at 1 and the rest is the look\n//                       (LookOf; caustics_layout.h CAUSTICS_LOOK_MAX)\n//\n"),
        ('static_assert(FlagShow == 1u && FlagPlane == 2u && FlagMaterial == 4u);\nstatic_assert(SlotWords == 16u && Slots >= 4u && Group == 8u);\nstatic_assert(CAUSTICS_MIN_HEIGHT < CAUSTICS_MAX_HEIGHT && CAUSTICS_FADE_START < CAUSTICS_FADE_END);\n',
         "static_assert(FlagShow == 1u && FlagPlane == 2u && FlagMaterial == 4u);\nstatic_assert(SlotWords == 32u && Slots >= 4u && Group == 8u); // r107d: 32 (was 16)\nstatic_assert(SlotWords <= Group * Group); // a workgroup's threads clear and add its words\nstatic_assert(CAUSTICS_MIN_HEIGHT < CAUSTICS_MAX_HEIGHT && CAUSTICS_FADE_START < CAUSTICS_FADE_END);\n"),
        ('              CAUSTICS_MODEL_MAX * CAUSTICS_MODEL_SCALE <= 1024.0);\n\n',
         "              CAUSTICS_MODEL_MAX * CAUSTICS_MODEL_SCALE <= 1024.0);\n// bbport (r107d_caustics-lamp-look): the bins and the look's words fit after word 15.\nstatic_assert(CAUSTICS_W_BIN_COUNT > CAUSTICS_W_LAMP_MODEL &&\n              CAUSTICS_W_BIN_RATIO == CAUSTICS_W_BIN_COUNT + CAUSTICS_BINS &&\n              CAUSTICS_W_LOOK == CAUSTICS_W_BIN_RATIO + CAUSTICS_BINS && CAUSTICS_W_LOOK < CAUSTICS_SLOT_WORDS);\nstatic_assert(CAUSTICS_DATA_LOOK > CAUSTICS_DATA_ENERGY && CAUSTICS_DATA_LOOK < CAUSTICS_DATA_LAMPS);\ninline constexpr std::uint32_t Bins = CAUSTICS_BINS;\n\n"),
        ("/// bbport (r107b_caustics-visible): the lamps' gain: LampGain x lamp strength, x ShowGain in the\n/// test view.\ninline float LampGainOf(const Knobs& k) {\n    return LampGain * k.lamp_strength * (k.show ? ShowGain : 1.0f);\n}\n",
         "/// bbport (r107b_caustics-visible): the lamps' gain: LampGain x lamp strength, x ShowGain in the\n/// test view. r107d: the strength counts up to 1 (above it: LookOf).\ninline float LampGainOf(const Knobs& k) {\n    return LampGain * std::min(k.lamp_strength, 1.0f) * (k.show ? ShowGain : 1.0f);\n}\n\n/// bbport (r107d_caustics-lamp-look): the look's amount: 0 up to lamp strength 1, then\n/// CAUSTICS_LOOK_MAX x (strength - 1) / (MaxStrength - 1).\ninline float LookOf(const Knobs& k) {\n    return float(CAUSTICS_LOOK_MAX) * std::clamp((k.lamp_strength - 1.0f) / (MaxStrength - 1.0f), 0.0f, 1.0f);\n}\n\n/// bbport (r107d_caustics-lamp-look): the bin of the lamps' modelled light (luminance) the shader\n/// counts a pixel in: below 2^-10 bin 0, then 2 stops a bin, 1 and above the last.\ninline std::uint32_t BinOf(float light) {\n    const int bin = int(std::floor(0.5f * std::log2(std::max(light, 1e-30f)))) + 6;\n    return std::uint32_t(std::clamp(bin, 0, int(Bins) - 1));\n}\n"),
    ],
    'engine/gpu/shadps4/video_core/renderer_vulkan/vk_caustics.cpp': [
        ('        std::memcpy(&data[CAUSTICS_DATA_ENERGY], &energy, sizeof(float));\n        for (u32 k = 0; k < lamp_count; ++k) {\n',
         '        std::memcpy(&data[CAUSTICS_DATA_ENERGY], &energy, sizeof(float));\n        const float look = lamp_count > 0 ? BC::LookOf(knobs) : 0.0f; // r107d\n        std::memcpy(&data[CAUSTICS_DATA_LOOK], &look, sizeof(float));\n        for (u32 k = 0; k < lamp_count; ++k) {\n'),
        ('        px(CAUSTICS_W_LAMP_UNSEEN), stats.no_lamps);\n    stats = {};\n',
         '        px(CAUSTICS_W_LAMP_UNSEEN), stats.no_lamps);\n    // r107d: the modelled lamp light over the pixel\'s own, by bins of that light (2 stops a bin),\n    // and over the brightest tenth of those pixels (whole bins from the top, at least a tenth).\n    char bins[BC::Bins * 24] = {};\n    size_t used = 0;\n    double all = 0.0, top_n = 0.0, top_sum = 0.0;\n    for (u32 b = 0; b < BC::Bins; ++b) {\n        all += double(stats.pixels[CAUSTICS_W_BIN_COUNT + b]);\n    }\n    for (u32 b = 0; b < BC::Bins; ++b) {\n        const double n = double(stats.pixels[CAUSTICS_W_BIN_COUNT + b]);\n        const double ratio = double(stats.pixels[CAUSTICS_W_BIN_RATIO + b]) / CAUSTICS_MODEL_SCALE / std::max(1.0, n);\n        used += size_t(std::max(0, std::snprintf(bins + used, sizeof(bins) - used, "%s%.0f %.2f",\n                                                 b ? ", " : "", n / reads, ratio)));\n        used = std::min(used, sizeof(bins) - 1);\n        const u32 from_top = BC::Bins - 1 - b;\n        if (top_n < 0.1 * all) {\n            top_n += double(stats.pixels[CAUSTICS_W_BIN_COUNT + from_top]);\n            top_sum += double(stats.pixels[CAUSTICS_W_BIN_RATIO + from_top]) / CAUSTICS_MODEL_SCALE;\n        }\n    }\n    BbReport::Printf("Water caustics (r107d): a dispatch: lamp model over own by modelled light (px ratio, "\n                     "<2^-10, 2 stops a bin, >=1): %s; brightest tenth (%.0f px) %.2f; look %.2f, %.0f px\\n",\n                     bins, top_n / reads, top_sum / std::max(1.0, top_n), double(BC::LookOf(knobs)),\n                     px(CAUSTICS_W_LOOK));\n    stats = {};\n'),
    ],
    'engine/tests/test_caustics.cpp': [
        ('    assert(Near(LampGainOf(lamp_show), LampGain * ShowGain, 1e-6f) && GainOf(lamp_show) == 0.0f);\n    assert(Near(LampGainOf(Parse("show", "2")), 2.0f * LampGain * ShowGain, 1e-6f));\n\n',
         '    assert(Near(LampGainOf(lamp_show), LampGain * ShowGain, 1e-6f) && GainOf(lamp_show) == 0.0f);\n    // r107d: above 1 the lamps\' light stays at strength 1 and the look grows to CAUSTICS_LOOK_MAX.\n    assert(Near(LampGainOf(Parse("show", "2")), LampGain * ShowGain, 1e-6f));\n    assert(Near(LampGainOf(Parse(nullptr, "0.5")), 0.5f * LampGain, 1e-6f));\n    assert(LookOf(Parse(nullptr, "1")) == 0.0f && LookOf(Parse(nullptr, "0.5")) == 0.0f && LookOf(lamp_show) == 0.0f);\n    assert(Near(LookOf(Parse(nullptr, "4")), float(CAUSTICS_LOOK_MAX), 1e-6f) &&\n           Near(LookOf(Parse(nullptr, "2.5")), 0.5f * float(CAUSTICS_LOOK_MAX), 1e-6f));\n    // r107d: the bins of the modelled lamp light.\n    assert(BinOf(0.0f) == 0 && BinOf(0.0009f) == 0 && BinOf(0.001f) == 1 && BinOf(0.24f) == 4 &&\n           BinOf(0.25f) == 5 && BinOf(1.0f) == Bins - 1 && BinOf(50.0f) == Bins - 1);\n\n'),
        ('    assert(share / n > 0.33 && share / n < 0.41);\n    std::printf("caustics: ok (pattern mean %.4f over %d points, %.3f to %.3f; lamp share %.3f)\\n", mean, n,\n',
         '    assert(share / n > 0.33 && share / n < 0.41);\n    // r107d: the look divides by that mean (CAUSTICS_LOOK_MEAN), so its contrast\'s mean is 1.\n    assert(std::fabs(share / n - CAUSTICS_LOOK_MEAN) < 0.01);\n    std::printf("caustics: ok (pattern mean %.4f over %d points, %.3f to %.3f; lamp share %.3f)\\n", mean, n,\n'),
    ],
    'README.md': [
        ("| `BB_CAUSTICS` | `1`: on; a number above 0 is the strength, up to 4 (0, unset, a negative number or text other than `show` is off). The water plane's height is the midpoint of the heights of the first and the last camera of a frame whose G-buffer passes are the world and its mirror image; drawn only in a pass whose camera is above that plane (not into the mirror image). A surface point 0.03 to 4 m above the plane whose normal (from the depth) faces the sun's light reflected off the plane (cosine above 0.05) is traced back along that light to its water point, at most 8 m away. When that point is on the screen and is water (nothing the depth shows there stands in front of it by more than 5 cm plus 3% of its view depth, unless that surface lies on the plane within the height below (then it is the water), and that surface is not above the plane by more than 4 cm plus 0.2% of its view depth: the water itself, or the ground under it seen through it), the game's light set at that pixel has the sun, and the alpha of the game's screen shadow target at that pixel says it is lit, the point's colour is multiplied by 1 + 0.3 x strength x w x (c - 1). c is the pattern at the water point: two layers of ridged value noise on the water, cells of 0.9 m and 0.55 m, turned 37 degrees to each other, each layer's ridge to the 8th power (thin lines), the two averaged and scaled so that the mean is 1 (it runs from 0 to 5.17): light is moved, not added. w = facing x lit x exp(-path / 2.5 m), faded out between 30 m and 45 m of view depth. The pattern drifts (layer 1 by 0.05 m/s in world x and 0.02 m/s in z, layer 2 by -0.03 and 0.04 m/s) and changes over time (0.3 noise cells a second); with `BB_WIND=1` the two layers also drift with 0.15 and 0.1 of the wind's velocity. The sun or moon must stand above the horizon (the y of its direction above 0.02); its direction and the shadow target are taken at the game's shadow resolve, which the engine watches only while one of its effects is on (indirect light, contact shadows, PCSS, volumetric light, lamp fog, point shadows, ray tracing, Froyok bloom, GTAO, SSR or lamp flicker; otherwise every call counts as no sun). The light sets: those of the game's directional light draw in the same frame (a table of up to 256; the alpha byte of the draw's texture 0 names each pixel's set, and that texture must be the G-buffer's specular target); a set has the sun when its light 0 is at least half as bright as the brightest set's (the rule of `BB_VOLUMETRIC_AREA_GATE`, luminance of the colour scaled to at most 1 a channel); the white fallback set has none; a frame without them draws no sun caustics. The game lights a roofed place with a set without the sun, while its sun shadow there can say lit (a roof that casts no sun shadow): the light set keeps the sun out. Drawn once after each G-buffer pass at its first blended draw, after the indirect light, before the drawn look, the transparents and the fog; only with the upscaler on (`BB_UPSCALER=none`: not drawn); a lamps-apart batch still open is ended first (the pass reads the camera depth). `show`: the test view at strength 1 (`BB_CAUSTICS_LAMPS=show` turns it on too, for the lamps): the pattern 3 times as strong (the lamps' light too), pixels the sun's caustics drew tinted cyan, pixels in the band whose water point is on dry ground orange, off the screen or hidden behind something nearer grey, those whose water point is in shadow or in a light set without the sun blue, pixels the lamps' caustics lit green, pixels a lamp's reflected light reaches (facing it) that no lamp lit orange too where a crossing is on dry ground, else grey where one is off the screen or hidden, and surfaces facing up (world normal y above 0.85) tinted magenta by their gloss (the G-buffer's material target, from 0.5 to 0.95), in every frame: the puddle candidates, which are NOT lit. The log (lines starting `Water caustics (r107`): the knob at the start, the first frame drawn, and after 120 calls, then every 600, the calls that drew, why the others did not (no water plane, mirror image, no sun, no shadow target, no scene) and, a dispatch, the pixels facing, on water, drawn and puddle candidates (read back 7 dispatches late); then a line starting `Water caustics (r107b)`: a dispatch, the sun's water points off the screen (or at the sky), hidden, dry, on the plane (the water is in the depth), below it (the ground under the water is) and in a light set without the sun; the calls without light sets; the light sets read, those with the sun and the brightest light 0's luminance as stored; then a line starting `Water caustics (r107c)`: the lamps a dispatch with lamps (their largest colour channel, and the lamp curve used), the pixels a lamp's reflected light reaches facing it, those lit by lamp caustics with, as means over them, the light added over their own (in percent with one decimal; each pixel's ratio clamped at 2) and the lamps' own direct light as the pass models it (albedo x colour x curve x facing, no shadow) over their own (clamped at 8; about 1 where those lamps light the pixel and the model is right), the lamp crossings on dry ground and those off the screen or hidden, and the calls without a lamp reaching the water. Cost: an estimate of 0.02 to 0.08 ms at 1080p internal where a water plane is drawn (one depth read a pixel outside the band; up to six depth reads, a light set read, one shadow read and the pattern inside it), none elsewhere (no dispatch); not measured; it is the `Lighting: water caustics` row of `BB_GPU_PROFILE=1`. Memory: 2048 bytes of counters and data | off |\n",
         "| `BB_CAUSTICS` | `1`: on; a number above 0 is the strength, up to 4 (0, unset, a negative number or text other than `show` is off). The water plane's height is the midpoint of the heights of the first and the last camera of a frame whose G-buffer passes are the world and its mirror image; drawn only in a pass whose camera is above that plane (not into the mirror image). A surface point 0.03 to 4 m above the plane whose normal (from the depth) faces the sun's light reflected off the plane (cosine above 0.05) is traced back along that light to its water point, at most 8 m away. When that point is on the screen and is water (nothing the depth shows there stands in front of it by more than 5 cm plus 3% of its view depth, unless that surface lies on the plane within the height below (then it is the water), and that surface is not above the plane by more than 4 cm plus 0.2% of its view depth: the water itself, or the ground under it seen through it), the game's light set at that pixel has the sun, and the alpha of the game's screen shadow target at that pixel says it is lit, the point's colour is multiplied by 1 + 0.3 x strength x w x (c - 1). c is the pattern at the water point: two layers of ridged value noise on the water, cells of 0.9 m and 0.55 m, turned 37 degrees to each other, each layer's ridge to the 8th power (thin lines), the two averaged and scaled so that the mean is 1 (it runs from 0 to 5.17): light is moved, not added. w = facing x lit x exp(-path / 2.5 m), faded out between 30 m and 45 m of view depth. The pattern drifts (layer 1 by 0.05 m/s in world x and 0.02 m/s in z, layer 2 by -0.03 and 0.04 m/s) and changes over time (0.3 noise cells a second); with `BB_WIND=1` the two layers also drift with 0.15 and 0.1 of the wind's velocity. The sun or moon must stand above the horizon (the y of its direction above 0.02); its direction and the shadow target are taken at the game's shadow resolve, which the engine watches only while one of its effects is on (indirect light, contact shadows, PCSS, volumetric light, lamp fog, point shadows, ray tracing, Froyok bloom, GTAO, SSR or lamp flicker; otherwise every call counts as no sun). The light sets: those of the game's directional light draw in the same frame (a table of up to 256; the alpha byte of the draw's texture 0 names each pixel's set, and that texture must be the G-buffer's specular target); a set has the sun when its light 0 is at least half as bright as the brightest set's (the rule of `BB_VOLUMETRIC_AREA_GATE`, luminance of the colour scaled to at most 1 a channel); the white fallback set has none; a frame without them draws no sun caustics. The game lights a roofed place with a set without the sun, while its sun shadow there can say lit (a roof that casts no sun shadow): the light set keeps the sun out. Drawn once after each G-buffer pass at its first blended draw, after the indirect light, before the drawn look, the transparents and the fog; only with the upscaler on (`BB_UPSCALER=none`: not drawn); a lamps-apart batch still open is ended first (the pass reads the camera depth). `show`: the test view at strength 1 (`BB_CAUSTICS_LAMPS=show` turns it on too, for the lamps): the pattern 3 times as strong (the lamps' light too), pixels the sun's caustics drew tinted cyan, pixels in the band whose water point is on dry ground orange, off the screen or hidden behind something nearer grey, those whose water point is in shadow or in a light set without the sun blue, pixels the lamps' caustics lit green, pixels a lamp's reflected light reaches (facing it) that no lamp lit orange too where a crossing is on dry ground, else grey where one is off the screen or hidden, and surfaces facing up (world normal y above 0.85) tinted magenta by their gloss (the G-buffer's material target, from 0.5 to 0.95), in every frame: the puddle candidates, which are NOT lit. The log (lines starting `Water caustics (r107`): the knob at the start, the first frame drawn, and after 120 calls, then every 600, the calls that drew, why the others did not (no water plane, mirror image, no sun, no shadow target, no scene) and, a dispatch, the pixels facing, on water, drawn and puddle candidates (read back 7 dispatches late); then a line starting `Water caustics (r107b)`: a dispatch, the sun's water points off the screen (or at the sky), hidden, dry, on the plane (the water is in the depth), below it (the ground under the water is) and in a light set without the sun; the calls without light sets; the light sets read, those with the sun and the brightest light 0's luminance as stored; then a line starting `Water caustics (r107c)`: the lamps a dispatch with lamps (their largest colour channel, and the lamp curve used), the pixels a lamp's reflected light reaches facing it, those lit by lamp caustics with, as means over them, the light added over their own (in percent with one decimal; each pixel's ratio clamped at 2) and the lamps' own direct light as the pass models it (albedo x colour x curve x facing, no shadow) over their own (clamped at 8; about 1 where those lamps light the pixel and the model is right), the lamp crossings on dry ground and those off the screen or hidden, and the calls without a lamp reaching the water; then a line starting `Water caustics (r107d)`: the pixels in the band the lamps' modelled direct light reaches, a dispatch, in 7 bins of that light's luminance (below 2^-10, then 2 stops a bin, the last 1 and above), each with the mean of that light over the pixel's own (clamped at 8); the same mean over the brightest tenth of them (whole bins from the top until at least a tenth); the look's amount and the pixels it changed. Near 1 in the top bins (the walls the lamp lights): the model is in the scene's units and a low mean elsewhere means other light dominates there; far below 1 in the top bins too: the units differ. Cost: an estimate of 0.02 to 0.08 ms at 1080p internal where a water plane is drawn (one depth read a pixel outside the band; up to six depth reads, a light set read, one shadow read and the pattern inside it), none elsewhere (no dispatch); not measured; it is the `Lighting: water caustics` row of `BB_GPU_PROFILE=1`. Memory: 2560 bytes of counters and data | off |\n"),
        ("| `BB_CAUSTICS_LAMPS` | The lamps' caustics, with or without `BB_CAUSTICS`: `1`: on; a number above 0 is the strength, up to 4; `show`: the test view at strength 1 (0, unset, a negative number or other text is off). In the passes `BB_CAUSTICS` draws in (a water plane, not the mirror image), up to 4 lamps of the game's light grid light the water: the lamps of the last G-buffer pass (each kept once), taken at the light grid's draws (watched only while one of the engine's effects is on, as `BB_CAUSTICS` says), with their colour as drawn (with `BB_LAMP_FLICKER`); of those 0.05 m or more above the plane and less than their reach above it, the 4 that count most (colour luminance, past 4 only the hue counts in this ranking, x (1 - height / reach)^2 x reach / (reach + distance to the camera)). The water's light reaches a surface point as from the lamp mirrored in the plane: to a point 0.03 to 8 m above the plane, nearer than the lamp's reach to the mirrored lamp, whose normal (from the depth) faces the mirrored lamp (cosine above 0.05), where that path crosses the plane on water (the rule of `BB_CAUSTICS`), the pass adds the albedo (the G-buffer's albedo target; 0.5 without it) x the lamp's colour as drawn x the game's lamp curve at d, the reflected path's length ((1 - d / reach)^2, or with `graphics_local_inverse_square` the inverse-square curve the game's lamp shaders are patched to, with `graphics_local_light_core` and `graphics_local_light_intensity`, as read at the start) x facing (that is the lamp's own light at that distance and angle) x the water's share 1 - exp(-30 x strength (x 3 in the test view) x the water's reflectance (Schlick at the path's angle at the crossing: 0.02 straight down, 1 at grazing) x the pattern at the crossing (`BB_CAUSTICS`'s)). The share stays below 1: never more than the lamp's own light at that distance; at strength 1 and near normal incidence its mean is about 0.37 and on the net's lines about 0.7 to 0.9 (30: a look choice, the net's lines gather the reflected light). Faded out between 30 m and 45 m of view depth. Each frame anew: a carried light moves its net with it. No lamp shadow is read: a wall between the lamp and the water, or between the water and the point, does not stop it. Cost: an estimate (not measured) of up to 4 lamp tests a pixel 0.03 to 8 m above the plane, each a depth read and the pattern where a lamp reaches it: up to about 0.1 to 0.3 ms at 1080p internal with 4 lamps over the whole screen; no dispatch where no lamp reaches a water plane | off |\n",
         "| `BB_CAUSTICS_LAMPS` | The lamps' caustics, with or without `BB_CAUSTICS`: `1`: on; a number above 0 is the strength, up to 1 the lamps' light below; above 1, up to 4, that light stays at strength 1 and a look control is added (below); `show`: the test view at strength 1 (0, unset, a negative number or other text is off). In the passes `BB_CAUSTICS` draws in (a water plane, not the mirror image), up to 4 lamps of the game's light grid light the water: the lamps of the last G-buffer pass (each kept once), taken at the light grid's draws (watched only while one of the engine's effects is on, as `BB_CAUSTICS` says), with their colour as drawn (with `BB_LAMP_FLICKER`); of those 0.05 m or more above the plane and less than their reach above it, the 4 that count most (colour luminance, past 4 only the hue counts in this ranking, x (1 - height / reach)^2 x reach / (reach + distance to the camera)). The water's light reaches a surface point as from the lamp mirrored in the plane: to a point 0.03 to 8 m above the plane, nearer than the lamp's reach to the mirrored lamp, whose normal (from the depth) faces the mirrored lamp (cosine above 0.05), where that path crosses the plane on water (the rule of `BB_CAUSTICS`), the pass adds the albedo (the G-buffer's albedo target; 0.5 without it) x the lamp's colour as drawn x the game's lamp curve at d, the reflected path's length ((1 - d / reach)^2, or with `graphics_local_inverse_square` the inverse-square curve the game's lamp shaders are patched to, with `graphics_local_light_core` and `graphics_local_light_intensity`, as read at the start) x facing (that is the lamp's own light at that distance and angle) x the water's share 1 - exp(-30 x strength (x 3 in the test view) x the water's reflectance (Schlick at the path's angle at the crossing: 0.02 straight down, 1 at grazing) x the pattern at the crossing (`BB_CAUSTICS`'s)). The share stays below 1: never more than the lamp's own light at that distance; at strength 1 and near normal incidence its mean is about 0.37 and on the net's lines about 0.7 to 0.9 (30: a look choice, the net's lines gather the reflected light). Faded out between 30 m and 45 m of view depth. The look control (strength above 1; NOT physical, a way to see the net where the lamps' own light is small): all the light a receiver has, whatever lit it, is multiplied by 1 + look x min(w, 1) x the same fade x (c - 1), look = 0.6 x (strength - 1) / 3 (0.6 at 4), w = the sum over the lamps whose path crosses water, or crosses a point hidden behind something nearer (the screen cannot tell; the light above leaves those out), of facing x exp(-the crossing's distance / 2.5 m), c = their weighted mean of (1 - exp(-0.6 x the pattern)) / 0.372: mean 1, from 0 to 2.69, so light is moved, not added, and the factor stays between 1 - look and 1 + 1.69 x look. Each frame anew: a carried light moves its net with it. No lamp shadow is read: a wall between the lamp and the water, or between the water and the point, does not stop it. Cost: an estimate (not measured) of up to 4 lamp tests a pixel 0.03 to 8 m above the plane, each a depth read and the pattern where a lamp reaches it: up to about 0.1 to 0.3 ms at 1080p internal with 4 lamps over the whole screen; no dispatch where no lamp reaches a water plane | off |\n"),
    ],
}


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        print("REFUSED %s: missing (are r107, r107b and r107c applied?)" % path)
        sys.exit(1)
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        print("REFUSED %s: mixed line ends" % path)
        sys.exit(1)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    done = todo = 0
    for old, new in eds:
        no, nn = cur.count(old), cur.count(new)
        if nn == 1 and no == (1 if old in new else 0):
            done += 1
        elif no == 1 and nn == 0:
            todo += 1
        else:
            print("REFUSED %s: old text found %d times, new text %d times: %r" % (path, no, nn, old[:70]))
            sys.exit(1)
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    print("REFUSED %s: %d of %d edits applied" % (path, done, len(eds)))
    sys.exit(1)


def text_checks(t):
    """The ties a compiler cannot check, on the texts as they are once applied."""
    layout = t[V + "host_shaders/caustics_layout.h"]
    shader = t[V + "host_shaders/caustics.comp"]
    cpp = t[V + "renderer_vulkan/vk_caustics.cpp"]
    test = t["engine/tests/test_caustics.cpp"]
    readme = t["README.md"]
    for name in ("SLOT_WORDS 32", "SLOTS 8", "DATA_WORDS 48", "BINS 7", "W_BIN_COUNT 16", "W_BIN_RATIO 23",
                 "W_LOOK 30", "DATA_LOOK 12", "LOOK_MAX 0.6", "LOOK_MEAN 0.372", "LAMP_GAIN 30.0", "WATER_F0 0.02",
                 "PATH_FALLOFF 2.5", "MODEL_MAX 8.0", "FADE_START 30.0"):
        want = "#define CAUSTICS_" + name + chr(10)
        if layout.count(want) != 1:
            raise SystemExit("text check: caustics_layout.h lacks %r" % want)
    sec = readme[readme.find("### Water caustics (in development)"):readme.find("## Sponsors")]
    # 8 slots x (32 + 48) words x 4 bytes; 0.6 = LAMP_GAIN x WATER_F0; 1 / 0.372 = 2.69
    for want in ("2560 bytes", "Water caustics (r107d)", "7 bins", "below 2^-10, then 2 stops a bin",
                 "clamped at 8", "brightest tenth", "look = 0.6 x (strength - 1) / 3", "exp(-0.6 x the pattern)) / 0.372",
                 "from 0 to 2.69", "1 + 1.69 x look", "2.5 m", "up to 1 the lamps' light below", "NOT physical",
                 "1 - exp(-30 x strength (x 3 in the test view)"):
        if want not in sec:
            raise SystemExit("text check: README section lacks %r" % want)
    for gone in ("2048 bytes", "a number above 0 is the strength, up to 4; `show`"):
        if gone in sec:
            raise SystemExit("text check: README section still says %r" % gone)
    if "std::fabs(share / n - CAUSTICS_LOOK_MEAN) < 0.01" not in test:
        raise SystemExit("text check: the test does not tie CAUSTICS_LOOK_MEAN to the share's mean")
    for want in ("CAUSTICS_W_BIN_COUNT + bin", "CAUSTICS_W_BIN_RATIO + bin", "CAUSTICS_W_LOOK",
                 "Data(CAUSTICS_DATA_LOOK)", "CAUSTICS_LAMP_GAIN * CAUSTICS_WATER_F0 * pattern",
                 "look_c / (look_w * CAUSTICS_LOOK_MEAN) - 1.0", "int(floor(0.5 * log2(model))) + 6"):
        if want not in shader:
            raise SystemExit("text check: the shader lacks %r" % want)
    if shader.count("layout(binding = ") != 7:
        raise SystemExit("text check: the shader does not have 7 bindings")
    for want in ('"Water caustics (r107d): a dispatch:', "&data[CAUSTICS_DATA_LOOK]", "BC::LookOf(knobs)"):
        if want not in cpp:
            raise SystemExit("text check: vk_caustics.cpp lacks %r" % want)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        print("%s is not a source tree root (set R107D_ROOT)" % ROOT)
        sys.exit(1)
    plan = []
    for path, eds in EDITS.items():
        raw, eol, cur = load(path)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        print("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
        sys.exit(1)
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in eds:
                cur = cur.replace(old, new, 1)
            if state_of(cur, eds, path) != "applied":
                print("REFUSED %s: the result does not read as applied" % path)
                sys.exit(1)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
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
        out = {p[0]: texts[p[0]].replace("\n", p[3]).encode("utf-8") for p in plan}
    else:
        if state != "applied":
            print("nothing to revert")
            return
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in reversed(eds):
                cur = cur.replace(new, old, 1)
            if state_of(cur, eds, path) != "clean":
                print("REFUSED %s: the revert does not read as clean; nothing written" % path)
                sys.exit(1)
            out[path] = cur.replace("\n", eol).encode("utf-8")
    written = []
    try:
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r107dtmp"
            open(tmp, "wb").write(out[path])
            os.replace(tmp, full)
            written.append((full, raw))
    except OSError as err:
        for full, raw in reversed(written):
            open(full, "wb").write(raw)
        print("REFUSED: write failed (%s); everything written was put back" % err)
        sys.exit(1)
    print("applied" if cmd == "apply" else "reverted")


main()
