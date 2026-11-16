# r107c_caustics-lamp-gain: FEATURE follow-up to r107b_caustics-visible.py (applies ON TOP of r107 +
# r107b; branch when published: visual/glass-water). Context: bbfss-ctx-glass-water-caustics.md,
# section "2026-11-15 r107c".
#
# Why r107b's lamp caustics were invisible (slot batch b12, sewer-water, 2026-11-15 22:11: 35,969 px
# lit, "+0%"):
#  1. The light added was albedo x colour x (1 - d/r)^2 x facing x Schlick x pattern x 2.5. At the
#     angles a wall or pier beside the water takes the reflected light the reflectance is about
#     0.02 (the real angle was already used: the path's cosine to the plane's normal), so the
#     whole was about 5% of the lamp's own light at that distance; a lamp brighter than 4 a
#     channel was cut down further (the lamp fog's colour limit); and the log's ratio was summed
#     as whole 1/256ths a pixel, so anything below 0.4% a pixel counted 0.
#     Now a lamp adds its own direct light at the reflected path's length and angle (the game's
#     lamp curve: (1 - d/r)^2, or the inverse-square curve the game's lamp shaders are patched to,
#     with its core and intensity) x the water's share 1 - exp(-30 x strength x Schlick x pattern):
#     below 1, so never more than the lamp's own light at that distance; mean about 0.37 at
#     strength 1, 0.7 to 0.9 on the net's lines. The colour is the lamp's as drawn. The log gets
#     its own line (r107c): the light added over the pixel's own with one decimal (1/512ths,
#     rounded), and the lamps' direct light as modelled over the pixel's own (the check that the
#     model's units are the scene's).
#  2. The orange in the test view on the right walls was not dry ground: the sun's line had 0 dry
#     water points against 83,893 hidden, and the lamps' "dry paths" counted crossings off the
#     screen and hidden behind nearer surfaces together with dry ones. Now orange = dry ground
#     only, off the screen or hidden = grey, and the lamps' crossings are counted dry / unseen.
#     A hidden water point whose nearer surface lies on the plane (within the water height
#     tolerance) is the water itself and now counts as water.
#
# Files: r107's own only (host_shaders/caustics.comp, caustics_layout.h; renderer_vulkan/
# caustics_params.h, vk_caustics.h, vk_caustics.cpp; tests/test_caustics.cpp; README.md: r107's two
# rows). vk_caustics.cpp now includes bbport_settings.h and vk_local_falloff.h (read only). No
# new file, no new binding, the same buffer (2048 bytes).
#
# Off (BB_CAUSTICS and BB_CAUSTICS_LAMPS unset): as r107: the rasterizer makes no Caustics.
#
# Use: python -I -X utf8 r107c_caustics-lamp-gain.py check | apply | revert. Root from R107C_ROOT,
# R107B_ROOT or R107_ROOT, else <tree>. Each edit is an exact text (old -> new) found exactly
# once; "applied" = every new text once and its old one gone, "clean" = every old text once and no
# new one; anything else is refused (exit 1, nothing written). Line ends are kept (CRLF in the
# tree). apply keeps the touched files in r107c_backup/ next to this script. Revert r107c BEFORE
# r107b: r107b's script refuses its files while r107c is on them. Exit: 0 done, 1 refused, 2 usage.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r107c_backup")
ROOT = (os.environ.get("R107C_ROOT") or os.environ.get("R107B_ROOT") or os.environ.get("R107_ROOT")
        or "<tree>")
V = "engine/gpu/shadps4/video_core/"

EDITS = {
    'engine/gpu/shadps4/video_core/host_shaders/caustics.comp': [
        ('// crossings are not water (none lit) orange too.\n#version 450\n',
         "// crossings are not water (none lit) orange too.\n// bbport (r107c_caustics-lamp-gain): a lamp's light added is its own direct light at the reflected\n// path's length and angle (the game's lamp curve, CAUSTICS_DATA_CORE2) x the water's share\n// 1 - exp(-gain x Schlick x pattern), below 1. Orange only where the water point or crossing is on\n// dry ground; off the screen or hidden behind something nearer: grey (the screen cannot tell).\n#version 450\n"),
        ('const vec3 TINT_LAMP = vec3(0.2, 1.0, 0.15);\n// Water(): what the screen shows at a point of the plane.\n',
         'const vec3 TINT_LAMP = vec3(0.2, 1.0, 0.15);\nconst vec3 TINT_UNSEEN = vec3(0.5); // r107c: grey (Tinted keeps the brightness)\n// Water(): what the screen shows at a point of the plane.\n'),
        ("    const float zq = ViewZ(dq);\n    if (zq < Wv.z - (CAUSTICS_SEEN_M + CAUSTICS_SEEN_REL * Wv.z)) {\n        return AT_HIDDEN;\n    }\n    const float above = ToWorld(ViewPos(vec2(qi) + 0.5, zq)).y - sun.w;\n    const float tolerance = CAUSTICS_WATER_M + CAUSTICS_WATER_REL * zq;\n    return above > tolerance ? AT_DRY : above >= -tolerance ? AT_WATER : AT_BELOW;\n}\n\n// A texel of `tex` at the scene's pixel `qi` (`q` its position), at the texture's own size when it\n// is not the scene's.\nivec2 TexelOf(texture2D tex, ivec2 qi, vec2 q) {\n    const ivec2 size = textureSize(tex, 0);\n    ivec2 t = qi;\n    if (any(greaterThanEqual(t, size))) {\n        t = ivec2(q / frame.xy * vec2(size));\n    }\n    return min(t, size - 1);\n}\n\nuint Data(uint i) {\n    return counts[CAUSTICS_SLOTS * CAUSTICS_SLOT_WORDS + slot * CAUSTICS_DATA_WORDS + i];\n}\n",
         "    const float zq = ViewZ(dq);\n    const float above = ToWorld(ViewPos(vec2(qi) + 0.5, zq)).y - sun.w;\n    const float tolerance = CAUSTICS_WATER_M + CAUSTICS_WATER_REL * zq;\n    // r107c: a nearer surface on the plane is the water itself (nearer only by the plane's error).\n    if (zq < Wv.z - (CAUSTICS_SEEN_M + CAUSTICS_SEEN_REL * Wv.z) && abs(above) > tolerance) {\n        return AT_HIDDEN;\n    }\n    return above > tolerance ? AT_DRY : above >= -tolerance ? AT_WATER : AT_BELOW;\n}\n\n// A texel of `tex` at the scene's pixel `qi` (`q` its position), at the texture's own size when it\n// is not the scene's.\nivec2 TexelOf(texture2D tex, ivec2 qi, vec2 q) {\n    const ivec2 size = textureSize(tex, 0);\n    ivec2 t = qi;\n    if (any(greaterThanEqual(t, size))) {\n        t = ivec2(q / frame.xy * vec2(size));\n    }\n    return min(t, size - 1);\n}\n\nuint Data(uint i) {\n    return counts[CAUSTICS_SLOTS * CAUSTICS_SLOT_WORDS + slot * CAUSTICS_DATA_WORDS + i];\n}\n\n// bbport (r107c_caustics-lamp-gain): the game's lamp curve at x = d / reach (below 1): the\n// inverse-square curve its lamp shaders are patched to, or its own (1 - x)^2 (core squared < 0).\nfloat LampCurve(float x) {\n    const float core2 = uintBitsToFloat(Data(CAUSTICS_DATA_CORE2));\n    if (core2 < 0.0) {\n        return (1.0 - x) * (1.0 - x);\n    }\n    return uintBitsToFloat(Data(CAUSTICS_DATA_ENERGY)) *\n           max(1.0 / max(x * x + core2, 1e-6) - 1.0 / (1.0 + core2), 0.0);\n}\n"),
        ('                if (show) {\n                    tint = TINT_DRY;\n                    tint_k = 0.25;\n',
         '                if (show) {\n                    tint = at == AT_DRY ? TINT_DRY : TINT_UNSEEN; // r107c\n                    tint_k = 0.25;\n'),
        ('    }\n    vec3 added = vec3(0.0);\n    if ((flags & CAUSTICS_FLAG_LAMPS) != 0u && height > CAUSTICS_MIN_HEIGHT &&\n',
         "    }\n    vec3 added = vec3(0.0), direct = vec3(0.0); // r107c: direct, the lamps' own light (the model)\n    if ((flags & CAUSTICS_FLAG_LAMPS) != 0u && height > CAUSTICS_MIN_HEIGHT &&\n"),
        ('        const uint lamps = min(Data(CAUSTICS_DATA_COUNT), uint(CAUSTICS_MAX_LAMPS));\n        bool tried = false, dry = false;\n        for (uint k = 0u; k < lamps; ++k) {\n',
         '        const uint lamps = min(Data(CAUSTICS_DATA_COUNT), uint(CAUSTICS_MAX_LAMPS));\n        bool tried = false, dry = false, unseen = false;\n        const float lamp_gain = uintBitsToFloat(Data(CAUSTICS_DATA_GAIN)); // r107c\n        for (uint k = 0u; k < lamps; ++k) {\n'),
        ("            const float reach = uintBitsToFloat(Data(at + 3u));\n            const float lamp_height = L.y - sun.w; // above the plane (the host's test)\n",
         "            const float reach = uintBitsToFloat(Data(at + 3u));\n            const vec3 colour = uintBitsToFloat(uvec3(Data(at + 4u), Data(at + 5u), Data(at + 6u)));\n            // r107c: the lamp's own direct light here (no shadow), for the log's model.\n            const float dl = length(L - Pw);\n            if (!(dl < reach)) {\n                continue; // the reflected path is longer still\n            }\n            direct += colour * (LampCurve(dl / reach) * max(dot(nw, L - Pw) / max(dl, 1e-4), 0.0));\n            const float lamp_height = L.y - sun.w; // above the plane (the host's test)\n"),
        ('            vec2 xq;\n            if (Water(X, xi, xq) > AT_BELOW) {\n                atomicAdd(group_counts[CAUSTICS_W_LAMP_DRY], 1u);\n                dry = true;\n                continue;\n            }\n            const float cosine = (lamp_height + height) / d;\n',
         "            vec2 xq;\n            const int crossing = Water(X, xi, xq);\n            if (crossing > AT_BELOW) {\n                atomicAdd(group_counts[crossing == AT_DRY ? CAUSTICS_W_LAMP_DRY : CAUSTICS_W_LAMP_UNSEEN], 1u);\n                dry = dry || crossing == AT_DRY;\n                unseen = unseen || crossing != AT_DRY;\n                continue;\n            }\n            // The cosine of the path's angle to the plane's normal at X: the real incidence.\n            const float cosine = (lamp_height + height) / d;\n"),
        ('                CAUSTICS_WATER_F0 + (1.0 - CAUSTICS_WATER_F0) * pow(1.0 - clamp(cosine, 0.0, 1.0), 5.0);\n            const float falloff = (1.0 - d / reach) * (1.0 - d / reach);\n            const vec3 colour = uintBitsToFloat(uvec3(Data(at + 4u), Data(at + 5u), Data(at + 6u)));\n            added += colour * (falloff * facing * reflectance * Pattern(X.xz));\n        }\n',
         "                CAUSTICS_WATER_F0 + (1.0 - CAUSTICS_WATER_F0) * pow(1.0 - clamp(cosine, 0.0, 1.0), 5.0);\n            // r107c: the lamp's own light at d and this facing, times the water's share (below 1).\n            added += colour * (LampCurve(d / reach) * facing *\n                               (1.0 - exp(-lamp_gain * reflectance * Pattern(X.xz))));\n        }\n"),
        ('                                                 : vec3(0.5);\n        added *= albedo * uintBitsToFloat(Data(CAUSTICS_DATA_GAIN)) *\n                 (1.0 - smoothstep(CAUSTICS_FADE_START, CAUSTICS_FADE_END, P.z));\n        if (dot(added, LUMA) > 0.0) {\n',
         '                                                 : vec3(0.5);\n        added *= albedo * (1.0 - smoothstep(CAUSTICS_FADE_START, CAUSTICS_FADE_END, P.z));\n        direct *= albedo; // r107c\n        if (dot(added, LUMA) > 0.0) {\n'),
        ("            added = vec3(0.0);\n            if (show && dry && tint_k <= 0.0) {\n                tint = TINT_DRY; // a lamp's light reaches it, but not across water\n                tint_k = 0.25;\n",
         "            added = vec3(0.0);\n            if (show && (dry || unseen) && tint_k <= 0.0) {\n                // a lamp's light reaches it, but not across water: dry ground orange, else grey (r107c)\n                tint = dry ? TINT_DRY : TINT_UNSEEN;\n                tint_k = 0.25;\n"),
        ('        atomicAdd(group_counts[CAUSTICS_W_LAMP_RATIO],\n                  uint(min(dot(added, LUMA) / own, CAUSTICS_RATIO_MAX) * CAUSTICS_RATIO_SCALE));\n        rgb += added;\n',
         '        atomicAdd(group_counts[CAUSTICS_W_LAMP_RATIO],\n                  uint(min(dot(added, LUMA) / own, CAUSTICS_RATIO_MAX) * CAUSTICS_RATIO_SCALE + 0.5));\n        atomicAdd(group_counts[CAUSTICS_W_LAMP_MODEL],\n                  uint(min(dot(direct, LUMA) / own, CAUSTICS_MODEL_MAX) * CAUSTICS_MODEL_SCALE + 0.5));\n        rgb += added;\n'),
    ],
    'engine/gpu/shadps4/video_core/host_shaders/caustics_layout.h': [
        ("// pixel's own (luminance ratio, clamped to 4, x 256), summed over word 11.\n#define CAUSTICS_SLOT_WORDS 16\n",
         "// pixel's own (luminance ratio, clamped to 4, x 256), summed over word 11.\n// bbport (r107c_caustics-lamp-gain): 12 only the crossings on dry ground; 14 those off the screen or\n// hidden; 13 clamped to CAUSTICS_RATIO_MAX, x CAUSTICS_RATIO_SCALE, rounded; 15 the lamps' own\n// direct light there (the pass's model of it: albedo x colour x curve x facing, no shadow) over\n// the pixel's own, clamped to CAUSTICS_MODEL_MAX, x CAUSTICS_MODEL_SCALE, rounded, summed over\n// word 11. At most 1024 a pixel each: 4 million lit pixels a dispatch fit in a word.\n#define CAUSTICS_SLOT_WORDS 16\n"),
        ('#define CAUSTICS_W_LAMP_RATIO 13\n#define CAUSTICS_RATIO_SCALE 256.0\n#define CAUSTICS_RATIO_MAX 4.0\n\n',
         '#define CAUSTICS_W_LAMP_RATIO 13\n#define CAUSTICS_W_LAMP_UNSEEN 14\n#define CAUSTICS_W_LAMP_MODEL 15\n#define CAUSTICS_RATIO_SCALE 512.0\n#define CAUSTICS_RATIO_MAX 2.0\n#define CAUSTICS_MODEL_SCALE 128.0\n#define CAUSTICS_MODEL_MAX 8.0\n\n'),
        ('// lamps of CAUSTICS_LAMP_WORDS words: world x, y, z, reach (m), colour r, g, b, 0.\n#define CAUSTICS_DATA_WORDS 48\n',
         "// lamps of CAUSTICS_LAMP_WORDS words: world x, y, z, reach (m), colour r, g, b, 0.\n// bbport (r107c_caustics-lamp-gain): CAUSTICS_DATA_CORE2 and CAUSTICS_DATA_ENERGY the game's lamp\n// curve (floats): core squared and energy of the inverse-square curve the game's lamp shaders are\n// patched to (startup_local_inverse_square), or -1 and 1 for its own (1 - d / reach)^2.\n#define CAUSTICS_DATA_WORDS 48\n"),
        ('#define CAUSTICS_DATA_GAIN 9\n#define CAUSTICS_DATA_LAMPS 16\n',
         '#define CAUSTICS_DATA_GAIN 9\n#define CAUSTICS_DATA_CORE2 10\n#define CAUSTICS_DATA_ENERGY 11\n#define CAUSTICS_DATA_LAMPS 16\n'),
        ('// under it seen through it. bbport (r107b_caustics-visible): was "the depth lies on the plane".\n#define CAUSTICS_WATER_M 0.04\n',
         '// under it seen through it. bbport (r107b_caustics-visible): was "the depth lies on the plane".\n// bbport (r107c_caustics-lamp-gain): a surface the depth shows on the plane (within that height)\n// is the water, also when it is nearer than the point.\n#define CAUSTICS_WATER_M 0.04\n'),
        ('// strength.\n#define CAUSTICS_LAMP_MIN_HEIGHT 0.05\n',
         '// strength.\n// bbport (r107c_caustics-lamp-gain): that was far too faint (the log\'s "+0%"): 2.5 x a reflectance\n// of about 0.02 (the angles a wall beside the water takes its light at) is about 5% of the lamp\'s\n// own light at that distance, less where its colour was limited. Now: albedo x colour x the\n// game\'s lamp curve at d (CAUSTICS_DATA_CORE2) x facing (the lamp\'s own direct light at the\n// reflected path\'s length and angle) x the water\'s share 1 - exp(-CAUSTICS_LAMP_GAIN x strength x\n// reflectance x the pattern): always below 1, so never more than that direct light; at strength 1\n// and near normal incidence its mean is about 0.37, on the net\'s lines about 0.7 to 0.9.\n#define CAUSTICS_LAMP_MIN_HEIGHT 0.05\n'),
        ('#define CAUSTICS_WATER_F0 0.02\n#define CAUSTICS_LAMP_GAIN 2.5\n\n',
         '#define CAUSTICS_WATER_F0 0.02\n#define CAUSTICS_LAMP_GAIN 30.0\n\n'),
    ],
    'engine/gpu/shadps4/video_core/renderer_vulkan/caustics_params.h': [
        ("// w its weight (caustics.comp): light moved, not added. The lamps' caustics add light (LampGain).\n\n",
         "// w its weight (caustics.comp): light moved, not added. The lamps' caustics add light (LampGain).\n// bbport (r107c_caustics-lamp-gain): a lamp adds its own direct light at the reflected path's\n// length and angle times the water's share LampShare (below 1; caustics_layout.h).\n\n"),
        ('static_assert(CAUSTICS_W_LAMP_RATIO < CAUSTICS_SLOT_WORDS && CAUSTICS_DATA_COUNT >= 8);\n\n',
         'static_assert(CAUSTICS_W_LAMP_RATIO < CAUSTICS_SLOT_WORDS && CAUSTICS_DATA_COUNT >= 8);\n// bbport (r107c_caustics-lamp-gain): the new counter and data words fit; a pixel adds at most 1024\n// to a sum.\nstatic_assert(CAUSTICS_W_LAMP_UNSEEN < CAUSTICS_SLOT_WORDS && CAUSTICS_W_LAMP_MODEL < CAUSTICS_SLOT_WORDS);\nstatic_assert(CAUSTICS_DATA_CORE2 > CAUSTICS_DATA_GAIN && CAUSTICS_DATA_ENERGY < CAUSTICS_DATA_LAMPS);\nstatic_assert(CAUSTICS_RATIO_MAX * CAUSTICS_RATIO_SCALE <= 1024.0 &&\n              CAUSTICS_MODEL_MAX * CAUSTICS_MODEL_SCALE <= 1024.0);\n\n'),
        ('/// bbport (r107b_caustics-visible): a lamp the pass lights the water with: world position, reach\n/// (m), colour (limited as the lamp fog limits it: past 4 only the hue counts).\nstruct Lamp {\n',
         '/// bbport (r107b_caustics-visible): a lamp the pass lights the water with: world position, reach\n/// (m), colour (r107c: as drawn; only its ranking limits it as the lamp fog does: past 4 only the\n/// hue counts).\nstruct Lamp {\n'),
        ("        const float over = std::max(1.0f, top / 4.0f);\n        lamp.colour = {std::max(w[4], 0.0f) / over, std::max(w[5], 0.0f) / over,\n                       std::max(w[6], 0.0f) / over};\n        const float luminance =\n            0.2126f * lamp.colour[0] + 0.7152f * lamp.colour[1] + 0.0722f * lamp.colour[2];\n        const float dx = lamp.world[0] - m[3], dy = lamp.world[1] - m[7], dz = lamp.world[2] - m[11];\n        const float share = 1.0f - height / lamp.reach;\n        lamp.importance = luminance * share * share * lamp.reach /\n                          (lamp.reach + std::sqrt(dx * dx + dy * dy + dz * dz));\n        if (!(lamp.importance > 0.0f)) {\n            continue;\n        }\n        // Insert by importance (stable: an equal one goes after those already in).\n        std::uint32_t at = n;\n        while (at > 0 && out[at - 1].importance < lamp.importance) {\n            --at;\n        }\n        if (at >= MaxLamps) {\n            continue;\n        }\n        for (std::uint32_t k = std::min<std::uint32_t>(n, MaxLamps - 1); k > at; --k) {\n            out[k] = out[k - 1];\n        }\n        out[at] = lamp;\n        n = std::min<std::uint32_t>(n + 1, MaxLamps);\n    }\n    return n;\n}\n\n/// bbport (r107b_caustics-visible): the C++ twin of the shader's water reflectance (Schlick,\n/// CAUSTICS_WATER_F0 at normal incidence; `cosine` of the angle to the vertical).\ninline float Reflectance(float cosine) {\n    const float c = std::clamp(cosine, 0.0f, 1.0f);\n    return float(CAUSTICS_WATER_F0) + (1.0f - float(CAUSTICS_WATER_F0)) * std::pow(1.0f - c, 5.0f);\n}\n",
         "        const float over = std::max(1.0f, top / 4.0f);\n        lamp.colour = {std::max(w[4], 0.0f), std::max(w[5], 0.0f), std::max(w[6], 0.0f)};\n        const float luminance =\n            (0.2126f * lamp.colour[0] + 0.7152f * lamp.colour[1] + 0.0722f * lamp.colour[2]) / over;\n        const float dx = lamp.world[0] - m[3], dy = lamp.world[1] - m[7], dz = lamp.world[2] - m[11];\n        const float share = 1.0f - height / lamp.reach;\n        lamp.importance = luminance * share * share * lamp.reach /\n                          (lamp.reach + std::sqrt(dx * dx + dy * dy + dz * dz));\n        if (!(lamp.importance > 0.0f)) {\n            continue;\n        }\n        // Insert by importance (stable: an equal one goes after those already in).\n        std::uint32_t at = n;\n        while (at > 0 && out[at - 1].importance < lamp.importance) {\n            --at;\n        }\n        if (at >= MaxLamps) {\n            continue;\n        }\n        for (std::uint32_t k = std::min<std::uint32_t>(n, MaxLamps - 1); k > at; --k) {\n            out[k] = out[k - 1];\n        }\n        out[at] = lamp;\n        n = std::min<std::uint32_t>(n + 1, MaxLamps);\n    }\n    return n;\n}\n\n/// bbport (r107b_caustics-visible): the C++ twin of the shader's water reflectance (Schlick,\n/// CAUSTICS_WATER_F0 at normal incidence; `cosine` of the angle to the vertical).\ninline float Reflectance(float cosine) {\n    const float c = std::clamp(cosine, 0.0f, 1.0f);\n    return float(CAUSTICS_WATER_F0) + (1.0f - float(CAUSTICS_WATER_F0)) * std::pow(1.0f - c, 5.0f);\n}\n\n/// bbport (r107c_caustics-lamp-gain): the C++ twins of the shader's lamp curve (x = d / reach,\n/// below 1; `core2` < 0: (1 - x)^2, else `energy` x (1 / (x^2 + core2) - 1 / (1 + core2))) and of\n/// the water's share of a lamp's own light, 1 - exp(-gain x reflectance x pattern): below 1 (in\n/// floats at most 1).\ninline float LampCurve(float x, float core2, float energy) {\n    if (core2 < 0.0f) {\n        return (1.0f - x) * (1.0f - x);\n    }\n    return energy * std::max(1.0f / std::max(x * x + core2, 1e-6f) - 1.0f / (1.0f + core2), 0.0f);\n}\n\ninline float LampShare(float gain, float reflectance, float pattern) {\n    return 1.0f - std::exp(-gain * reflectance * pattern);\n}\n"),
    ],
    'engine/gpu/shadps4/video_core/renderer_vulkan/vk_caustics.h': [
        ("        u64 lamps_used = 0; ///< r107b: their lamps, summed\n        std::array<u64, ::BbCaustics::SlotWords> pixels{}; ///< the shader's counts, read back late\n",
         "        u64 lamps_used = 0; ///< r107b: their lamps, summed\n        float colour_top = 0.0f; ///< r107c: the largest colour channel of those lamps\n        std::array<u64, ::BbCaustics::SlotWords> pixels{}; ///< the shader's counts, read back late\n"),
    ],
    'engine/gpu/shadps4/video_core/renderer_vulkan/vk_caustics.cpp': [
        ('#include <utility>\n\n#include "bbport_toggles.h"\n',
         '#include <utility>\n\n#include "bbport_settings.h" // bbport (r107c_caustics-lamp-gain): the game\'s lamp curve\n#include "bbport_toggles.h"\n'),
        ('#include "video_core/renderer_vulkan/vk_instance.h"\n#include "video_core/renderer_vulkan/vk_platform.h"\n',
         '#include "video_core/renderer_vulkan/vk_instance.h"\n#include "video_core/renderer_vulkan/vk_local_falloff.h" // r107c\n#include "video_core/renderer_vulkan/vk_platform.h"\n'),
        ('        std::memcpy(&data[CAUSTICS_DATA_GAIN], &lamp_gain, sizeof(float));\n        for (u32 k = 0; k < lamp_count; ++k) {\n',
         "        std::memcpy(&data[CAUSTICS_DATA_GAIN], &lamp_gain, sizeof(float));\n        // r107c: the game's lamp curve, as LocalFalloff::Patch makes it (read at the start).\n        const auto& settings = BbSettings::Get();\n        const float core = std::isfinite(settings.startup_local_light_core) &&\n                                   settings.startup_local_light_core > 0.0f\n                               ? settings.startup_local_light_core\n                               : 0.0f;\n        const bool inverse_square = settings.startup_local_inverse_square;\n        const float core2 = inverse_square ? core * core : -1.0f;\n        const float energy = inverse_square ? settings.startup_local_light_intensity *\n                                                  LocalFalloff::EnergyScale(core)\n                                            : 1.0f;\n        std::memcpy(&data[CAUSTICS_DATA_CORE2], &core2, sizeof(float));\n        std::memcpy(&data[CAUSTICS_DATA_ENERGY], &energy, sizeof(float));\n        for (u32 k = 0; k < lamp_count; ++k) {\n"),
        ('            std::memcpy(&data[CAUSTICS_DATA_LAMPS + k * BC::LampWords], words.data(), sizeof(words));\n        }\n',
         '            std::memcpy(&data[CAUSTICS_DATA_LAMPS + k * BC::LampWords], words.data(), sizeof(words));\n            stats.colour_top = std::max({stats.colour_top, lamp.colour[0], lamp.colour[1], lamp.colour[2]});\n        }\n'),
        ('        "Water caustics (r107b): a dispatch: sun water pt %.0f off scr, %.0f hidden, %.0f dry, %.0f "\n        "on plane, %.0f below it, %.0f sunless set; lamps %.2f, %.0f px tried, %.0f lit (+%.0f%%), "\n        "%.0f dry paths; skipped %u no sets, %u no lamps; sets %u, %u sunny, best %.2f\\n",\n        px(CAUSTICS_W_OFF), px(CAUSTICS_W_HIDDEN), px(CAUSTICS_W_DRY), px(CAUSTICS_W_ON_PLANE),\n        px(CAUSTICS_W_BELOW), px(CAUSTICS_W_NO_SUN_SET),\n        double(stats.lamps_used) / std::max(1.0, double(stats.lamp_draws)), px(CAUSTICS_W_LAMP_TRIED),\n        px(CAUSTICS_W_LAMP_LIT),\n        100.0 * double(stats.pixels[CAUSTICS_W_LAMP_RATIO]) / CAUSTICS_RATIO_SCALE /\n            std::max(1.0, double(stats.pixels[CAUSTICS_W_LAMP_LIT])),\n        px(CAUSTICS_W_LAMP_DRY), stats.no_sets, stats.no_lamps, sets_count, sets_sunny,\n        double(sets_best));\n    stats = {};\n',
         '        "Water caustics (r107b): a dispatch: sun water pt %.0f off scr, %.0f hidden, %.0f dry, %.0f "\n        "on plane, %.0f below it, %.0f sunless set; skipped %u no sets; sets %u, %u sunny, best "\n        "%.2f\\n",\n        px(CAUSTICS_W_OFF), px(CAUSTICS_W_HIDDEN), px(CAUSTICS_W_DRY), px(CAUSTICS_W_ON_PLANE),\n        px(CAUSTICS_W_BELOW), px(CAUSTICS_W_NO_SUN_SET), stats.no_sets, sets_count, sets_sunny,\n        double(sets_best));\n    // r107c: the lamps (a dispatch with lamps; the light added and the lamps\' own direct light as\n    // the pass models it, each over the pixel\'s own, means over the lit pixels)\n    const double lit = std::max(1.0, double(stats.pixels[CAUSTICS_W_LAMP_LIT]));\n    BbReport::Printf(\n        "Water caustics (r107c): a dispatch: lamps %.2f (colour up to %.1f, %s curve), %.0f px tried, "\n        "%.0f lit (+%.1f%% of their own, lamp model %.2f of it), crossings %.0f dry, %.0f unseen; "\n        "skipped %u no lamps\\n",\n        double(stats.lamps_used) / std::max(1.0, double(stats.lamp_draws)), double(stats.colour_top),\n        BbSettings::Get().startup_local_inverse_square ? "inverse-square" : "(1-d/r)^2",\n        px(CAUSTICS_W_LAMP_TRIED), px(CAUSTICS_W_LAMP_LIT),\n        100.0 * double(stats.pixels[CAUSTICS_W_LAMP_RATIO]) / CAUSTICS_RATIO_SCALE / lit,\n        double(stats.pixels[CAUSTICS_W_LAMP_MODEL]) / CAUSTICS_MODEL_SCALE / lit, px(CAUSTICS_W_LAMP_DRY),\n        px(CAUSTICS_W_LAMP_UNSEEN), stats.no_lamps);\n    stats = {};\n'),
    ],
    'engine/tests/test_caustics.cpp': [
        ('        put(2, 0.0f, -2.5f, 5.0f, 6.0f, 1.0f, 1.0f, 1.0f);  // under the plane: does not\n        put(3, 4.0f, 0.0f, 9.0f, 4.0f, 8.0f, 0.0f, 0.0f);   // 2 m above, red, limited to 4\n        put(4, 0.0f, 1.0f, 5.0f, 6.0f, 1.0f, 0.8f, 0.5f);   // as record 0 (ties: the first stays first)\n',
         '        put(2, 0.0f, -2.5f, 5.0f, 6.0f, 1.0f, 1.0f, 1.0f);  // under the plane: does not\n        put(3, 4.0f, 0.0f, 9.0f, 4.0f, 8.0f, 0.0f, 0.0f);   // 2 m above, red (ranked as 4; r107c: kept)\n        put(4, 0.0f, 1.0f, 5.0f, 6.0f, 1.0f, 0.8f, 0.5f);   // as record 0 (ties: the first stays first)\n'),
        ('        assert(Near(out[1].world[1], 3.0f, 1e-5f) && out[0].importance == out[1].importance);\n        assert(Near(out[2].colour[0], 4.0f, 1e-5f) && Near(out[2].reach, 4.0f, 1e-4f));\n        assert(out[0].importance >= out[2].importance);\n',
         '        assert(Near(out[1].world[1], 3.0f, 1e-5f) && out[0].importance == out[1].importance);\n        assert(Near(out[2].colour[0], 8.0f, 1e-5f) && Near(out[2].reach, 4.0f, 1e-4f));\n        assert(out[0].importance >= out[2].importance);\n'),
        ("    assert(Reflectance(0.5f) > Reflectance(0.8f));\n\n    // The pattern's mean is 1 (PatternMean), its values from 0 to 1 / PatternMean.\n    double sum = 0.0;\n    float most = 0.0f, least = 1e9f;\n",
         "    assert(Reflectance(0.5f) > Reflectance(0.8f));\n    // bbport (r107c_caustics-lamp-gain): the game's lamp curves; the water's share is never above 1.\n    assert(Near(LampCurve(0.5f, -1.0f, 1.0f), 0.25f, 1e-6f) && LampCurve(0.999f, -1.0f, 1.0f) < 1e-5f);\n    const float c2 = 0.05f * 0.05f, e = 1.0f / (30.0f * (1.0f - 0.05f * std::atan(20.0f) - 1.0f / (3.0f * (1.0f + c2))));\n    assert(Near(LampCurve(0.5f, c2, e), e * (1.0f / (0.25f + c2) - 1.0f / (1.0f + c2)), 1e-5f));\n    assert(LampCurve(1.0f, c2, e) == 0.0f && LampCurve(0.1f, c2, e) > LampCurve(0.2f, c2, e));\n    assert(LampShare(LampGain, Reflectance(1.0f), 1.0f / PatternMean) < 1.0f && LampShare(LampGain, 0.02f, 0.0f) == 0.0f);\n    assert(LampShare(4.0f * LampGain * ShowGain, 1.0f, 1.0f / PatternMean) <= 1.0f);\n\n    // The pattern's mean is 1 (PatternMean), its values from 0 to 1 / PatternMean.\n    double sum = 0.0, share = 0.0; // r107c: share, the water's mean share at strength 1, 0.02\n    float most = 0.0f, least = 1e9f;\n"),
        ('            sum += c;\n            most = std::max(most, c);\n',
         '            sum += c;\n            share += LampShare(LampGain, Reflectance(1.0f), c);\n            most = std::max(most, c);\n'),
        ('    assert(least >= 0.0f && most <= 1.0f / PatternMean + 1e-3f);\n    std::printf("caustics: ok (pattern mean %.4f over %d points, %.3f to %.3f)\\n", mean, n, double(least),\n                double(most));\n    return 0;\n',
         '    assert(least >= 0.0f && most <= 1.0f / PatternMean + 1e-3f);\n    // r107c: about 0.37 (the README\'s "about 0.37"): the lamps\' net at strength 1, straight down.\n    assert(share / n > 0.33 && share / n < 0.41);\n    std::printf("caustics: ok (pattern mean %.4f over %d points, %.3f to %.3f; lamp share %.3f)\\n", mean, n,\n                double(least), double(most), share / n);\n    return 0;\n'),
    ],
    'README.md': [
        ("| `BB_CAUSTICS` | `1`: on; a number above 0 is the strength, up to 4 (0, unset, a negative number or text other than `show` is off). The water plane's height is the midpoint of the heights of the first and the last camera of a frame whose G-buffer passes are the world and its mirror image; drawn only in a pass whose camera is above that plane (not into the mirror image). A surface point 0.03 to 4 m above the plane whose normal (from the depth) faces the sun's light reflected off the plane (cosine above 0.05) is traced back along that light to its water point, at most 8 m away. When that point is on the screen and is water (nothing the depth shows there stands in front of it by more than 5 cm plus 3% of its view depth, and that surface is not above the plane by more than 4 cm plus 0.2% of its view depth: the water itself, or the ground under it seen through it), the game's light set at that pixel has the sun, and the alpha of the game's screen shadow target at that pixel says it is lit, the point's colour is multiplied by 1 + 0.3 x strength x w x (c - 1). c is the pattern at the water point: two layers of ridged value noise on the water, cells of 0.9 m and 0.55 m, turned 37 degrees to each other, each layer's ridge to the 8th power (thin lines), the two averaged and scaled so that the mean is 1 (it runs from 0 to 5.17): light is moved, not added. w = facing x lit x exp(-path / 2.5 m), faded out between 30 m and 45 m of view depth. The pattern drifts (layer 1 by 0.05 m/s in world x and 0.02 m/s in z, layer 2 by -0.03 and 0.04 m/s) and changes over time (0.3 noise cells a second); with `BB_WIND=1` the two layers also drift with 0.15 and 0.1 of the wind's velocity. The sun or moon must stand above the horizon (the y of its direction above 0.02); its direction and the shadow target are taken at the game's shadow resolve, which the engine watches only while one of its effects is on (indirect light, contact shadows, PCSS, volumetric light, lamp fog, point shadows, ray tracing, Froyok bloom, GTAO, SSR or lamp flicker; otherwise every call counts as no sun). The light sets: those of the game's directional light draw in the same frame (a table of up to 256; the alpha byte of the draw's texture 0 names each pixel's set, and that texture must be the G-buffer's specular target); a set has the sun when its light 0 is at least half as bright as the brightest set's (the rule of `BB_VOLUMETRIC_AREA_GATE`, luminance of the colour scaled to at most 1 a channel); the white fallback set has none; a frame without them draws no sun caustics. The game lights a roofed place with a set without the sun, while its sun shadow there can say lit (a roof that casts no sun shadow): the light set keeps the sun out. Drawn once after each G-buffer pass at its first blended draw, after the indirect light, before the drawn look, the transparents and the fog; only with the upscaler on (`BB_UPSCALER=none`: not drawn); a lamps-apart batch still open is ended first (the pass reads the camera depth). `show`: the test view at strength 1 (`BB_CAUSTICS_LAMPS=show` turns it on too, for the lamps): the pattern 3 times as strong (the lamps' light too), pixels the sun's caustics drew tinted cyan, pixels in the band whose water point is not water orange, those whose water point is in shadow or in a light set without the sun blue, pixels the lamps' caustics lit green, pixels a lamp's reflected light reaches (facing it) that no lamp lit and where a crossing is not water orange too, and surfaces facing up (world normal y above 0.85) tinted magenta by their gloss (the G-buffer's material target, from 0.5 to 0.95), in every frame: the puddle candidates, which are NOT lit. The log (lines starting `Water caustics (r107`): the knob at the start, the first frame drawn, and after 120 calls, then every 600, the calls that drew, why the others did not (no water plane, mirror image, no sun, no shadow target, no scene) and, a dispatch, the pixels facing, on water, drawn and puddle candidates (read back 7 dispatches late); then a line starting `Water caustics (r107b)`: a dispatch, the sun's water points off the screen (or at the sky), hidden, dry, on the plane (the water is in the depth), below it (the ground under the water is) and in a light set without the sun; the lamps a dispatch with lamps, the pixels a lamp's reflected light reaches facing it, those lit by lamp caustics (with the light added over their own, in percent) and the lamp paths whose crossing is not water; the calls without light sets and those without a lamp reaching the water; the light sets read, those with the sun and the brightest light 0's luminance as stored. Cost: an estimate of 0.02 to 0.08 ms at 1080p internal where a water plane is drawn (one depth read a pixel outside the band; up to six depth reads, a light set read, one shadow read and the pattern inside it), none elsewhere (no dispatch); not measured; it is the `Lighting: water caustics` row of `BB_GPU_PROFILE=1`. Memory: 2048 bytes of counters and data | off |\n",
         "| `BB_CAUSTICS` | `1`: on; a number above 0 is the strength, up to 4 (0, unset, a negative number or text other than `show` is off). The water plane's height is the midpoint of the heights of the first and the last camera of a frame whose G-buffer passes are the world and its mirror image; drawn only in a pass whose camera is above that plane (not into the mirror image). A surface point 0.03 to 4 m above the plane whose normal (from the depth) faces the sun's light reflected off the plane (cosine above 0.05) is traced back along that light to its water point, at most 8 m away. When that point is on the screen and is water (nothing the depth shows there stands in front of it by more than 5 cm plus 3% of its view depth, unless that surface lies on the plane within the height below (then it is the water), and that surface is not above the plane by more than 4 cm plus 0.2% of its view depth: the water itself, or the ground under it seen through it), the game's light set at that pixel has the sun, and the alpha of the game's screen shadow target at that pixel says it is lit, the point's colour is multiplied by 1 + 0.3 x strength x w x (c - 1). c is the pattern at the water point: two layers of ridged value noise on the water, cells of 0.9 m and 0.55 m, turned 37 degrees to each other, each layer's ridge to the 8th power (thin lines), the two averaged and scaled so that the mean is 1 (it runs from 0 to 5.17): light is moved, not added. w = facing x lit x exp(-path / 2.5 m), faded out between 30 m and 45 m of view depth. The pattern drifts (layer 1 by 0.05 m/s in world x and 0.02 m/s in z, layer 2 by -0.03 and 0.04 m/s) and changes over time (0.3 noise cells a second); with `BB_WIND=1` the two layers also drift with 0.15 and 0.1 of the wind's velocity. The sun or moon must stand above the horizon (the y of its direction above 0.02); its direction and the shadow target are taken at the game's shadow resolve, which the engine watches only while one of its effects is on (indirect light, contact shadows, PCSS, volumetric light, lamp fog, point shadows, ray tracing, Froyok bloom, GTAO, SSR or lamp flicker; otherwise every call counts as no sun). The light sets: those of the game's directional light draw in the same frame (a table of up to 256; the alpha byte of the draw's texture 0 names each pixel's set, and that texture must be the G-buffer's specular target); a set has the sun when its light 0 is at least half as bright as the brightest set's (the rule of `BB_VOLUMETRIC_AREA_GATE`, luminance of the colour scaled to at most 1 a channel); the white fallback set has none; a frame without them draws no sun caustics. The game lights a roofed place with a set without the sun, while its sun shadow there can say lit (a roof that casts no sun shadow): the light set keeps the sun out. Drawn once after each G-buffer pass at its first blended draw, after the indirect light, before the drawn look, the transparents and the fog; only with the upscaler on (`BB_UPSCALER=none`: not drawn); a lamps-apart batch still open is ended first (the pass reads the camera depth). `show`: the test view at strength 1 (`BB_CAUSTICS_LAMPS=show` turns it on too, for the lamps): the pattern 3 times as strong (the lamps' light too), pixels the sun's caustics drew tinted cyan, pixels in the band whose water point is on dry ground orange, off the screen or hidden behind something nearer grey, those whose water point is in shadow or in a light set without the sun blue, pixels the lamps' caustics lit green, pixels a lamp's reflected light reaches (facing it) that no lamp lit orange too where a crossing is on dry ground, else grey where one is off the screen or hidden, and surfaces facing up (world normal y above 0.85) tinted magenta by their gloss (the G-buffer's material target, from 0.5 to 0.95), in every frame: the puddle candidates, which are NOT lit. The log (lines starting `Water caustics (r107`): the knob at the start, the first frame drawn, and after 120 calls, then every 600, the calls that drew, why the others did not (no water plane, mirror image, no sun, no shadow target, no scene) and, a dispatch, the pixels facing, on water, drawn and puddle candidates (read back 7 dispatches late); then a line starting `Water caustics (r107b)`: a dispatch, the sun's water points off the screen (or at the sky), hidden, dry, on the plane (the water is in the depth), below it (the ground under the water is) and in a light set without the sun; the calls without light sets; the light sets read, those with the sun and the brightest light 0's luminance as stored; then a line starting `Water caustics (r107c)`: the lamps a dispatch with lamps (their largest colour channel, and the lamp curve used), the pixels a lamp's reflected light reaches facing it, those lit by lamp caustics with, as means over them, the light added over their own (in percent with one decimal; each pixel's ratio clamped at 2) and the lamps' own direct light as the pass models it (albedo x colour x curve x facing, no shadow) over their own (clamped at 8; about 1 where those lamps light the pixel and the model is right), the lamp crossings on dry ground and those off the screen or hidden, and the calls without a lamp reaching the water. Cost: an estimate of 0.02 to 0.08 ms at 1080p internal where a water plane is drawn (one depth read a pixel outside the band; up to six depth reads, a light set read, one shadow read and the pattern inside it), none elsewhere (no dispatch); not measured; it is the `Lighting: water caustics` row of `BB_GPU_PROFILE=1`. Memory: 2048 bytes of counters and data | off |\n"),
        ("| `BB_CAUSTICS_LAMPS` | The lamps' caustics, with or without `BB_CAUSTICS`: `1`: on; a number above 0 is the strength, up to 4; `show`: the test view at strength 1 (0, unset, a negative number or other text is off). In the passes `BB_CAUSTICS` draws in (a water plane, not the mirror image), up to 4 lamps of the game's light grid light the water: the lamps of the last G-buffer pass (each kept once), taken at the light grid's draws (watched only while one of the engine's effects is on, as `BB_CAUSTICS` says), with their colour as drawn (with `BB_LAMP_FLICKER`); of those 0.05 m or more above the plane and less than their reach above it, the 4 that count most (colour luminance, past 4 only the hue counts, x (1 - height / reach)^2 x reach / (reach + distance to the camera)). The water's light reaches a surface point as from the lamp mirrored in the plane: to a point 0.03 to 8 m above the plane, nearer than the lamp's reach to the mirrored lamp, whose normal (from the depth) faces the mirrored lamp (cosine above 0.05), where that path crosses the plane on water (the rule of `BB_CAUSTICS`), the pass adds the albedo (the G-buffer's albedo target; 0.5 without it) x the lamp's colour x (1 - d / reach)^2 (the game's lamp curve, d the reflected path's length) x facing x the water's reflectance (Schlick: 0.02 straight down, 1 at grazing) x the pattern at the crossing (`BB_CAUSTICS`'s) x 2.5 (the net's lines gather the reflected light; a look choice) x strength (x 3 in the test view), faded out between 30 m and 45 m of view depth. Each frame anew: a carried light moves its net with it. No lamp shadow is read: a wall between the lamp and the water, or between the water and the point, does not stop it. Cost: an estimate (not measured) of up to 4 lamp tests a pixel 0.03 to 8 m above the plane, each a depth read and the pattern where a lamp reaches it: up to about 0.1 to 0.3 ms at 1080p internal with 4 lamps over the whole screen; no dispatch where no lamp reaches a water plane | off |\n",
         "| `BB_CAUSTICS_LAMPS` | The lamps' caustics, with or without `BB_CAUSTICS`: `1`: on; a number above 0 is the strength, up to 4; `show`: the test view at strength 1 (0, unset, a negative number or other text is off). In the passes `BB_CAUSTICS` draws in (a water plane, not the mirror image), up to 4 lamps of the game's light grid light the water: the lamps of the last G-buffer pass (each kept once), taken at the light grid's draws (watched only while one of the engine's effects is on, as `BB_CAUSTICS` says), with their colour as drawn (with `BB_LAMP_FLICKER`); of those 0.05 m or more above the plane and less than their reach above it, the 4 that count most (colour luminance, past 4 only the hue counts in this ranking, x (1 - height / reach)^2 x reach / (reach + distance to the camera)). The water's light reaches a surface point as from the lamp mirrored in the plane: to a point 0.03 to 8 m above the plane, nearer than the lamp's reach to the mirrored lamp, whose normal (from the depth) faces the mirrored lamp (cosine above 0.05), where that path crosses the plane on water (the rule of `BB_CAUSTICS`), the pass adds the albedo (the G-buffer's albedo target; 0.5 without it) x the lamp's colour as drawn x the game's lamp curve at d, the reflected path's length ((1 - d / reach)^2, or with `graphics_local_inverse_square` the inverse-square curve the game's lamp shaders are patched to, with `graphics_local_light_core` and `graphics_local_light_intensity`, as read at the start) x facing (that is the lamp's own light at that distance and angle) x the water's share 1 - exp(-30 x strength (x 3 in the test view) x the water's reflectance (Schlick at the path's angle at the crossing: 0.02 straight down, 1 at grazing) x the pattern at the crossing (`BB_CAUSTICS`'s)). The share stays below 1: never more than the lamp's own light at that distance; at strength 1 and near normal incidence its mean is about 0.37 and on the net's lines about 0.7 to 0.9 (30: a look choice, the net's lines gather the reflected light). Faded out between 30 m and 45 m of view depth. Each frame anew: a carried light moves its net with it. No lamp shadow is read: a wall between the lamp and the water, or between the water and the point, does not stop it. Cost: an estimate (not measured) of up to 4 lamp tests a pixel 0.03 to 8 m above the plane, each a depth read and the pattern where a lamp reaches it: up to about 0.1 to 0.3 ms at 1080p internal with 4 lamps over the whole screen; no dispatch where no lamp reaches a water plane | off |\n"),
    ],
}


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        print("REFUSED %s: missing (are r107 and r107b applied?)" % path)
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
    for want in ("#define CAUSTICS_SLOT_WORDS 16\n", "#define CAUSTICS_SLOTS 8\n", "#define CAUSTICS_DATA_WORDS 48\n",
                 "#define CAUSTICS_MAX_LAMPS 4\n", "#define CAUSTICS_WATER_F0 0.02\n",
                 "#define CAUSTICS_LAMP_GAIN 30.0\n", "#define CAUSTICS_W_LAMP_UNSEEN 14\n",
                 "#define CAUSTICS_W_LAMP_MODEL 15\n", "#define CAUSTICS_RATIO_SCALE 512.0\n",
                 "#define CAUSTICS_RATIO_MAX 2.0\n", "#define CAUSTICS_MODEL_SCALE 128.0\n",
                 "#define CAUSTICS_MODEL_MAX 8.0\n", "#define CAUSTICS_DATA_CORE2 10\n",
                 "#define CAUSTICS_DATA_ENERGY 11\n", "#define CAUSTICS_WATER_M 0.04\n",
                 "#define CAUSTICS_WATER_REL 0.002\n", "#define CAUSTICS_SEEN_M 0.05\n",
                 "#define CAUSTICS_SEEN_REL 0.03\n"):
        if layout.count(want) != 1:
            raise SystemExit("text check: caustics_layout.h lacks %r" % want)
    sec = readme[readme.find("### Water caustics (in development)"):readme.find("## Sponsors")]
    for want in ("2048 bytes", "1 - exp(-30 x strength (x 3 in the test view)", "0.02 straight down",
                 "about 0.37", "0.7 to 0.9", "clamped at 2", "clamped at 8", "Water caustics (r107c)",
                 "Water caustics (r107b)", "on dry ground orange", "grey", "5 cm plus 3%", "4 cm plus 0.2%",
                 "unless that surface lies on the plane", "up to 4 lamps", "the lamp's colour as drawn",
                 "`graphics_local_inverse_square`", "one decimal"):
        if want not in sec:
            raise SystemExit("text check: README section lacks %r" % want)
    for gone in ("x 2.5 (the", "(1 - d / reach)^2 (the game's lamp curve, d the reflected",
                 "whose water point is not water orange", "where a crossing is not water orange",
                 "the lamp paths whose crossing is not water"):
        if gone in sec:
            raise SystemExit("text check: README section still says %r" % gone)
    if test.count("share / n > 0.33 && share / n < 0.41") != 1:
        raise SystemExit("text check: the test does not hold the README's mean share (about 0.37)")
    for want in ("1.0 - exp(-lamp_gain * reflectance * Pattern(X.xz))", "CAUSTICS_W_LAMP_UNSEEN",
                 "CAUSTICS_W_LAMP_MODEL", "TINT_UNSEEN"):
        if want not in shader:
            raise SystemExit("text check: the shader lacks %r" % want)
    if shader.count("layout(binding = ") != 7:
        raise SystemExit("text check: the shader does not have 7 bindings")
    if "uintBitsToFloat(Data(CAUSTICS_DATA_GAIN)) *" in shader:
        raise SystemExit("text check: the shader still multiplies the gain outside the share")
    for want in ('"Water caustics (r107c): a dispatch: lamps', "(+%.1f%% of their own",
                 "&data[CAUSTICS_DATA_CORE2]", "&data[CAUSTICS_DATA_ENERGY]"):
        if want not in cpp:
            raise SystemExit("text check: vk_caustics.cpp lacks %r" % want)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        print("%s is not a source tree root (set R107C_ROOT)" % ROOT)
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
            tmp = full + ".r107ctmp"
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
