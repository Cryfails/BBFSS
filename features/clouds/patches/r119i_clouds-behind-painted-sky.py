# r119i_clouds-behind-painted-sky: FEATURE fix on r119 to r119h (BB_VOLUMETRIC_CLOUDS=1 only: nothing here exists or runs without the
# CloudLayer object, which is made only with BB_VOLUMETRIC_CLOUDS starting with 1; with the layer on, each new knob has an
# off value that gives the r119h arithmetic back).
#
# Why (owner, build 72, 4K DLSS, "The clouds look weird and maybe clip with skybox. Image 8" = owner_pic6): the layer is a soft
# smear drawn over the painted sky dome and across its painted shapes (a dark painted ridge, the horizon glow). Read from the
# log of that run and the picture:
#  (1) The sky the layer covers is not depth 1: the r119b depth line says depth 1 share 0.000 and the sky blocks lie at a view
#      z of 500 to 1000 m ("from 500" 0.03 to 0.09, rest 0.86 to 0.99 is the world), so it is the dome MESH, with its painted
#      ridge and glow, that gets clouds drawn over it. The layer knew nothing of what the painting shows.
#  (2) The cloud colour is the block's mean sky colour pulled 55% to grey and cooled (tint 0), over a warm orange dome: a grey
#      cream smear that does not belong to it; and its lit rim reaches 3 x the sky's brightness.
#  (3) The layer fades in over only 3 to 13 degrees of elevation, so the painted horizon region (the dome's own painted
#      horizon clouds) is covered whole.
#  (4) The drift is 48 m/s (wind cloud speed held to 8 m/s x speed knob 6): 3 to 4 degrees a second overhead.
#
# FIX (all in cloud_layer.comp's MARCH build, the Params block and the knobs; the COMPOSITE build's SPIR-V is untouched):
#  A. BB_VOLUMETRIC_CLOUDS_PAINTED (0 to 1, default 0.8, live with the test tools' file; 0 = off, the r119h look): each march
#     block (2 x 2 scene pixels) compares its sky colour (brightness) and its view z with 12 sky pixels round it, 8 at 12
#     pixels and 4 at 40 pixels (a 1080 line scene; scaled with the scene's height), the worst of them decides:
#       - brightness: |l - l_block| / (l + l_block): 0.08 starts, 0.38 is whole (a painted ridge against the sky is 0.33 and
#         more, a painted cloud's rim 0.1 to 0.2);
#       - view z: ln(z / z_block) 0.15 starts, 0.5 is whole (a ridge mesh in front of the dome, depth 1 against the dome).
#     The cloud's opacity is multiplied by (1 - PAINTED x that): the clouds thin out where the painting has shapes of its own and
#     stay in the smooth open dome. A ring pixel that is not sky is skipped (the world's own edges do not take clouds back).
#  B. BB_VOLUMETRIC_CLOUDS_GLOWMAX (0 to 8, default 1.6, live; 0 = off): the cloud's own colour (premultiplied rgb / opacity) is
#     at most this times the brightness of the sky behind it, so a rim cannot out-shine the painting (it was 3 x).
#  C. BB_VOLUMETRIC_CLOUDS_HORIZON (degrees 0 to 60, default 30, live; 0 = off, the old fade over 0.05 to 0.22 of the ray's slope):
#     the clouds are in full from this elevation up and fade in over the lowest 0.4 of it (12 to 30 degrees at the default): the
#     painted horizon keeps its own look.
#  D. BB_VOLUMETRIC_CLOUDS_TINT default 0 -> 0.7: the clouds take the dome's colour (the shade and lit colours are 70% the
#     sky's own, 30% the old grey / cool) so they match the dome around them.
#  E. BB_VOLUMETRIC_CLOUDS_SPEED default 6 -> 1.5: 3.75 to 12 m/s (was 15 to 48): 0.2 to 0.7 degrees a second overhead.
#  The look constants (0.8 / 12 / 40 / 0.08 / 0.38 / 1.6 / 30 / 0.7 / 1.5) are guesses until the 4K clips judge them.
#
# LOG: once-line "Volumetric clouds (r119i, ...)" with the values; a live change of one prints "Volumetric clouds (r119i): live
# knobs: ..."; the periodic r119i line says them and the painted share (counter word 16: marched sky blocks of which the painted
# sky took 25% or more of the opacity).
#
# Files (8 edits sets, no new file, no shared hook, no CMake change): host_shaders/cloud_layer.comp (MARCH only: a Params vec4
# `paint` after `extra`, painted_share(), the counter, the glow cap), host_shaders/cloud_layer_layout.h (CL_WORD_PAINTED 16,
# CL_WORDS 17), renderer_vulkan/cloud_layer_params.h, vk_cloud_layer.cpp/.h, tests/test_cloud_layer.cpp (new block p and the
# default-dependent asserts), README.md (rows and the speed / tint rows). Apply after r119h; revert BEFORE r119h.
#
# COST: nothing without BB_VOLUMETRIC_CLOUDS=1 (the CloudLayer is not made). On: the Params block grows 224 -> 240 bytes (no new
# buffer; the counter buffer 64 -> 68 bytes); the march pass does per SKY march block 12 depth fetches and up to 12 image loads
# when PAINTED > 0 (a uniform branch, skipped at 0), one more atomic when the fade is 25%+. Estimate +0.05 to 0.15 ms at 1080p
# internal with a mostly sky picture (518k march blocks x 24 reads), 0 with no sky in view (the loop is after the early-outs
# and the sky test). No new memory. Unmeasured.
#
# Use: python -I -X utf8 r119i_clouds-behind-painted-sky.py check | apply | revert
# Root: R119I_ROOT, else <tree>. Line ends kept. Backups in r119i_backup next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r119i_backup")
ROOT = os.environ.get("R119I_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
TMP = ".r119itmp"

COMP = V + "host_shaders/cloud_layer.comp"
LAYOUT = V + "host_shaders/cloud_layer_layout.h"
PARAMS = R + "cloud_layer_params.h"
CPP = R + "vk_cloud_layer.cpp"
HDR = R + "vk_cloud_layer.h"
TEST = "engine/tests/test_cloud_layer.cpp"
README = "README.md"

EDITS = [
    # ---- the layout: the counter word ----------------------------------------------------------------------------------------
    (LAYOUT,
     r'''#define CL_BRIGHT_RATIO 1.4
#define CL_WORDS 16u
''',
     r'''#define CL_BRIGHT_RATIO 1.4
// bbport (r119i_clouds-behind-painted-sky): the marched sky blocks of which the painted sky took CL_PAINTED_SHARE or more of the opacity
#define CL_WORD_PAINTED 16u
#define CL_PAINTED_SHARE 0.25
#define CL_WORDS 17u
'''),
    # ---- the shader (MARCH build only) --------------------------------------------------------------------------------------
    (COMP,
     r'''// one tap at 0.5, base 0.25, no floor); extra.x is the tint (0: the sky's tint desaturated and cooled, 1: the sky's own).
#version 450''',
     r'''// one tap at 0.5, base 0.25, no floor); extra.x is the tint (0: the sky's tint desaturated and cooled, 1: the sky's own).
// bbport (r119i_clouds-behind-painted-sky): the clouds sit behind the painting (Params.paint, MARCH only): paint.x takes back
// the share of a block's opacity where the painted sky has shapes of its own (painted_share: the block's brightness and view z
// against 12 sky pixels on two rings round it); paint.w caps the cloud's colour at this times the sky's brightness behind it.
// paint.x = 0 and paint.w = 0 give the r119h arithmetic.
#version 450'''),
    (COMP,
     r'''shared uint group_counts[CL_WORDS];

#ifdef MARCH
''',
     r'''// bbport (r119i): the composite does not count (its build keeps its old 16 words, so its SPIR-V does not change)
#ifdef MARCH
shared uint group_counts[CL_WORDS];
#else
shared uint group_counts[16];
#endif

#ifdef MARCH
'''),
    (COMP,
     r'''    vec4 extra;            // r119g: tint (0..1), light taps, shade base (at a cloud's base, of its top's), horizon glow
#endif
};''',
     r'''    vec4 extra;            // r119g: tint (0..1), light taps, shade base (at a cloud's base, of its top's), horizon glow
    vec4 paint;            // r119i: painted share taken back (0: off), ring near / far (px at 1080 lines), glow cap (0: off)
#endif
};'''),
    (COMP,
     r'''const vec3 SHADE_COOL = vec3(0.88, 0.94, 1.06); // the shade side is cooler than the sky
#endif''',
     r'''const vec3 SHADE_COOL = vec3(0.88, 0.94, 1.06); // the shade side is cooler than the sky
// bbport (r119i): the painted sky's shapes: the 8 directions of the rings (the first 4, the axes, are also the far ring's)
const ivec2 PAINT_DIRS[8] = ivec2[8](ivec2(1, 0), ivec2(-1, 0), ivec2(0, 1), ivec2(0, -1), ivec2(1, 1), ivec2(-1, 1),
                                     ivec2(1, -1), ivec2(-1, -1));
const float PAINT_LO = 0.08, PAINT_SPAN = 0.30; // |l - l0| / (l + l0): a shape starts at the first, is whole at the sum
#endif'''),
    (COMP,
     r'''    uint words[CL_WORDS];
};

vec4 march(ivec2 hp) {''',
     r'''    uint words[CL_WORDS];
};

// bbport (r119i_clouds-behind-painted-sky): the share (0..1) of a march block's cloud the painted sky takes back where it has shapes
// of its own. The block's sky brightness (lum_c) and view z (z_c) are compared with the sky pixels on two rings round the block
// (paint.y and paint.z pixels at a 1080 line scene, scaled with the scene's height; 8 samples near, the 4 axes far): a brightness that
// differs (a painted ridge, a painted cloud's rim) or a view z that jumps (a ridge mesh before the dome, depth 1 against the dome)
// counts, the worst of the 12 decides, times paint.x. A ring pixel that is not sky is skipped: the world's own edges take nothing back.
float painted_share(ivec2 centre, float lum_c, float z_c) {
    float worst = 0.0;
    float k_scale = float(scene.y) / 1080.0;
    int near_px = max(int(paint.y * k_scale + 0.5), 2);
    int far_px = max(int(paint.z * k_scale + 0.5), 4);
    for (int k = 0; k < 12; ++k) {
        ivec2 q = centre + PAINT_DIRS[k & 7] * (k < 8 ? near_px : far_px);
        if (any(lessThan(q, ivec2(0))) || any(greaterThanEqual(q, ivec2(scene)))) continue;
        float d = texelFetch(depth_tex, q, 0).r;
        if (!is_sky(d)) continue;
        vec3 c = imageLoad(scene_img, q).rgb;
        if (any(isnan(c)) || any(isinf(c))) continue;
        float l = dot(clamp(c, vec3(0.0), vec3(10000.0)), LUMA_W);
        float by_light = smoothstep(PAINT_LO, PAINT_LO + PAINT_SPAN, abs(l - lum_c) / max(l + lum_c, LUM_FLOOR));
        float zq = d >= 1.0 ? 100000.0 : view_z(d);
        float by_depth = smoothstep(0.15, 0.5, abs(log(max(zq, 1.0) / max(z_c, 1.0))));
        worst = max(worst, max(by_light, by_depth));
    }
    return clamp(worst * paint.x, 0.0, 1.0);
}

vec4 march(ivec2 hp) {'''),
    (COMP,
     r'''    vec3 sky_sum = vec3(0.0);
    float sky_n = 0.0;
''',
     r'''    vec3 sky_sum = vec3(0.0);
    float sky_n = 0.0;
    float sky_z0 = 100000.0; // bbport (r119i): the view z of the block's first sky pixel
'''),
    (COMP,
     r'''            if (is_sky(texelFetch(depth_tex, p, 0).r)) {
                vec3 c = imageLoad(scene_img, p).rgb;''',
     r'''            float dp = texelFetch(depth_tex, p, 0).r;
            if (is_sky(dp)) {
                if (sky_n == 0.0) sky_z0 = dp >= 1.0 ? 100000.0 : view_z(dp); // bbport (r119i)
                vec3 c = imageLoad(scene_img, p).rgb;'''),
    (COMP,
     r'''    float scale = fade * look.y;
    float alpha = (1.0 - T) * scale;
    vec3 rgb = (shade_col * acc_amb + lit_col * acc_lit) * scale;
''',
     r'''    // bbport (r119i_clouds-behind-painted-sky): the painted sky takes back its shapes (paint.x = 0: nothing)
    float taken_back = paint.x > 0.0 ? painted_share(base + ivec2(CL_DIV / 2), sky_lum, sky_z0) : 0.0;
    float scale = fade * look.y * (1.0 - taken_back);
    float alpha = (1.0 - T) * scale;
    vec3 rgb = (shade_col * acc_amb + lit_col * acc_lit) * scale;
    if (paint.w > 0.0 && alpha > 1.0 / 4096.0) {
        // the cloud's own colour (rgb / alpha) is at most paint.w times the brightness of the sky behind it
        float own = dot(rgb, LUMA_W) / alpha;
        float cap = paint.w * sky_lum;
        if (own > cap) rgb *= cap / own;
    }
'''),
    (COMP,
     r'''    atomicAdd(group_counts[CL_WORD_HIT], 1u);
    atomicAdd(group_counts[CL_WORD_STEPS], taken);''',
     r'''    atomicAdd(group_counts[CL_WORD_HIT], 1u);
    if (taken_back >= float(CL_PAINTED_SHARE)) atomicAdd(group_counts[CL_WORD_PAINTED], 1u); // bbport (r119i)
    atomicAdd(group_counts[CL_WORD_STEPS], taken);'''),
    # ---- the knobs, the Params block, the counters ----------------------------------------------------------------------------
    (PARAMS,
     r'''DefaultSpeed = 6.0f;   ///< BB_VOLUMETRIC_CLOUDS_SPEED: times the one wind's cloud speed (r119d: was 1)''',
     r'''DefaultSpeed = 1.5f;   ///< BB_VOLUMETRIC_CLOUDS_SPEED: times the one wind's cloud speed (r119d: was 1; r119i: was 6, 15 to 48 m/s read too fast: 3.75 to 12 m/s now)'''),
    (PARAMS,
     r'''inline constexpr float DefaultTint = 0.0f;''',
     r'''inline constexpr float DefaultTint = 0.7f; // bbport (r119i_clouds-behind-painted-sky): was 0 (grey, cool clouds over a warm dome)'''),
    (PARAMS,
     r'''inline constexpr float HorizonGlow = 0.30f; ///< the shade floor x opacity for rays near the horizon, with the fix on
''',
     r'''inline constexpr float HorizonGlow = 0.30f; ///< the shade floor x opacity for rays near the horizon, with the fix on
// bbport (r119i_clouds-behind-painted-sky): the clouds sit behind the painted sky's own shapes (cloud_layer.comp's header says how).
// BB_VOLUMETRIC_CLOUDS_PAINTED (0 to 1: how much of the opacity a painted shape takes back; 0 = off), _GLOWMAX (0 to 8: the
// cloud's own colour at most this times the sky's brightness behind it; 0 = off) and _HORIZON (degrees 0 to 60: the clouds are in
// full from this elevation up; 0 = off, the fade over 0.05 to 0.22 of the ray's slope) are live knobs with the test tools' file.
inline constexpr float DefaultPainted = 0.8f;
inline constexpr float RingNear = 12.0f, RingFar = 40.0f; ///< pixels at a 1080 line scene: the two rings' radii
inline constexpr float DefaultGlow = 1.6f, MaxGlow = 8.0f;
inline constexpr float DefaultHorizon = 30.0f, MaxHorizon = 60.0f;
inline constexpr float HorizonFromShare = 0.4f; ///< the fade-in starts at this share of the full elevation
inline float ParsePainted(const char* text) {
    return std::clamp(CloudShadows::Number(text, DefaultPainted), 0.0f, 1.0f);
}
inline float ParseGlow(const char* text) {
    return std::clamp(CloudShadows::Number(text, DefaultGlow), 0.0f, MaxGlow);
}
inline float ParseHorizon(const char* text) {
    return std::clamp(CloudShadows::Number(text, DefaultHorizon), 0.0f, MaxHorizon);
}
'''),
    (PARAMS,
     r'''inline constexpr float HorizonFrom = 0.05f, HorizonTo = 0.22f; ///< |ray y| the clouds fade in over
''',
     r'''inline constexpr float HorizonFrom = 0.05f, HorizonTo = 0.22f; ///< |ray y| the clouds fade in over
/// bbport (r119i): the |ray y| the clouds fade in over for a full elevation of `degrees` (from sin(0.4 x it) to sin(it)); 0 (or
/// not a number): the old HorizonFrom to HorizonTo.
inline std::array<float, 2> HorizonEdges(float degrees) {
    if (!(degrees > 0.0f)) {
        return {HorizonFrom, HorizonTo};
    }
    const float rad = degrees * 0.017453292519943295f;
    return {std::sin(HorizonFromShare * rad), std::sin(rad)};
}
'''),
    (PARAMS,
     r'''    bool smear = true;                ///< bbport (r119g): the smear fix (two light taps, shade base, horizon glow)
''',
     r'''    bool smear = true;                ///< bbport (r119g): the smear fix (two light taps, shade base, horizon glow)
    float painted = DefaultPainted;   ///< bbport (r119i): the share of the opacity a painted shape takes back (0: off)
    float horizon = DefaultHorizon;   ///< bbport (r119i): degrees up where the clouds are in full (0: the old fade)
    float glow = DefaultGlow;         ///< bbport (r119i): the cloud's colour at most this x the sky's brightness (0: off)
'''),
    (PARAMS,
     r'''const char* tint = nullptr, const char* smear = nullptr) {''',
     r'''const char* tint = nullptr, const char* smear = nullptr,
                       const char* painted = nullptr, const char* horizon = nullptr,
                       const char* glow = nullptr) {'''),
    (PARAMS,
     r'''    k.smear = ParseSmear(smear);
''',
     r'''    k.smear = ParseSmear(smear);
    k.painted = ParsePainted(painted); // bbport (r119i_clouds-behind-painted-sky)
    k.horizon = ParseHorizon(horizon);
    k.glow = ParseGlow(glow);
'''),
    (PARAMS,
     r'''    std::array<float, 4> extra{};                ///< bbport (r119g): tint, light taps, shade base, horizon glow
};
static_assert(sizeof(Params) == 14 * 16 && offsetof(Params, off0) == 64 &&
                  offsetof(Params, light) == 112 && offsetof(Params, tone) == 192 &&
                  offsetof(Params, extra) == 208,
              "cloud_layer.comp's Params block: 14 vec4");''',
     r'''    std::array<float, 4> extra{};                ///< bbport (r119g): tint, light taps, shade base, horizon glow
    std::array<float, 4> paint{};                ///< bbport (r119i): painted share taken back, ring near, ring far (px at 1080 lines), glow cap
};
static_assert(sizeof(Params) == 15 * 16 && offsetof(Params, off0) == 64 &&
                  offsetof(Params, light) == 112 && offsetof(Params, tone) == 192 &&
                  offsetof(Params, extra) == 208 && offsetof(Params, paint) == 224,
              "cloud_layer.comp's Params block: 15 vec4 (r119i: paint)");'''),
    (PARAMS,
     r'''CL_WORD_BRIGHT < CL_WORDS && CL_DARK_RATIO == 0.7 && CL_BRIGHT_RATIO == 1.4); // bbport (r119d)
''',
     r'''CL_WORD_BRIGHT < CL_WORDS && CL_DARK_RATIO == 0.7 && CL_BRIGHT_RATIO == 1.4); // bbport (r119d)
static_assert(CL_WORD_PAINTED == CL_WORD_BRIGHT + 1u && CL_WORD_PAINTED < CL_WORDS && CL_WORDS == 17u &&
              CL_PAINTED_SHARE == 0.25); // bbport (r119i_clouds-behind-painted-sky)
'''),
    (PARAMS,
     r'''    p.look = {float(knobs.steps), OpacityCap, HorizonFrom, HorizonTo};''',
     r'''    const std::array<float, 2> horizon = HorizonEdges(knobs.horizon); // bbport (r119i_clouds-behind-painted-sky)
    p.look = {float(knobs.steps), OpacityCap, horizon[0], horizon[1]};'''),
    (PARAMS,
     r'''               knobs.smear ? HorizonGlow : 0.0f};
    return p;''',
     r'''               knobs.smear ? HorizonGlow : 0.0f};
    p.paint = {knobs.painted, RingNear, RingFar, knobs.glow}; // bbport (r119i)
    return p;'''),
    (PARAMS,
     r'''    double bright = 0.0;  ///< of the visible ones: picture brighter than CL_BRIGHT_RATIO of the sky behind (r119d)
''',
     r'''    double bright = 0.0;  ///< of the visible ones: picture brighter than CL_BRIGHT_RATIO of the sky behind (r119d)
    double painted = 0.0; ///< of the marched sky pixels: those whose opacity the painted sky took CL_PAINTED_SHARE or more of (r119i)
'''),
    (PARAMS,
     r'''    s.bright = vis > 0.0 ? double(t.words[CL_WORD_BRIGHT]) / vis : 0.0;
''',
     r'''    s.bright = vis > 0.0 ? double(t.words[CL_WORD_BRIGHT]) / vis : 0.0;
    s.painted = hit > 0.0 ? double(t.words[CL_WORD_PAINTED]) / hit : 0.0; // bbport (r119i_clouds-behind-painted-sky)
'''),
    # ---- the engine ----------------------------------------------------------------------------------------------------------
    (CPP,
     r'''std::getenv("BB_VOLUMETRIC_CLOUDS_TINT"), std::getenv("BB_VOLUMETRIC_CLOUDS_SMEAR")); // bbport (r119g)''',
     r'''std::getenv("BB_VOLUMETRIC_CLOUDS_TINT"), std::getenv("BB_VOLUMETRIC_CLOUDS_SMEAR"), // bbport (r119g)
        std::getenv("BB_VOLUMETRIC_CLOUDS_PAINTED"), std::getenv("BB_VOLUMETRIC_CLOUDS_HORIZON"),
        std::getenv("BB_VOLUMETRIC_CLOUDS_GLOWMAX")); // bbport (r119i_clouds-behind-painted-sky)'''),
    (CPP,
     r'''/// bbport (r119h_clouds-freeze-sheet): TOOL. BB_VOLUMETRIC_CLOUDS_FREEZE and _MARK now: live knobs with the test tools'
''',
     r'''/// bbport (r119i_clouds-behind-painted-sky): BB_VOLUMETRIC_CLOUDS_PAINTED, _HORIZON and _GLOWMAX now (live knobs with the test
/// tools' header, asked again at every use), else the start's value.
float LivePainted([[maybe_unused]] float at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<float> painted{"BB_VOLUMETRIC_CLOUDS_PAINTED", CL::ParsePainted};
    return painted.Get();
#else
    return at_start;
#endif
}

float LiveHorizon([[maybe_unused]] float at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<float> horizon{"BB_VOLUMETRIC_CLOUDS_HORIZON", CL::ParseHorizon};
    return horizon.Get();
#else
    return at_start;
#endif
}

float LiveGlow([[maybe_unused]] float at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<float> glow{"BB_VOLUMETRIC_CLOUDS_GLOWMAX", CL::ParseGlow};
    return glow.Get();
#else
    return at_start;
#endif
}

/// bbport (r119h_clouds-freeze-sheet): TOOL. BB_VOLUMETRIC_CLOUDS_FREEZE and _MARK now: live knobs with the test tools'
'''),
    (CPP,
     r'''    if (ReportFrames() != 0) { // bbport (r119f_clouds-open-sky)
''',
     r'''    // bbport (r119i_clouds-behind-painted-sky): under 300 characters
    BbReport::Printf("Volumetric clouds (r119i, BB_VOLUMETRIC_CLOUDS=1): behind the painted sky: shapes take back %.2f of the opacity (rings %.0f and %.0f px "
                     "at 1080 lines), full cloud from %.0f deg up, colour cap %.2f x the sky, speed x%.2f, tint %.2f; "
                     "BB_VOLUMETRIC_CLOUDS_PAINTED, _HORIZON, _GLOWMAX (%s)\n",
                     double(knobs.painted), double(CL::RingNear), double(CL::RingFar), double(knobs.horizon),
                     double(knobs.glow), double(knobs.speed), double(knobs.tint), LiveText);
    if (ReportFrames() != 0) { // bbport (r119f_clouds-open-sky)
'''),
    (CPP,
     r'''    live.smear = LiveSmear(knobs.smear);
''',
     r'''    live.smear = LiveSmear(knobs.smear);
    // bbport (r119i_clouds-behind-painted-sky): the painted fade, the horizon and the glow cap, said once per change
    live.painted = LivePainted(knobs.painted);
    live.horizon = LiveHorizon(knobs.horizon);
    live.glow = LiveGlow(knobs.glow);
    if (told_paint[0] < 0.0f) {
        told_paint = {live.painted, live.horizon, live.glow};
    } else if (live.painted != told_paint[0] || live.horizon != told_paint[1] || live.glow != told_paint[2]) {
        told_paint = {live.painted, live.horizon, live.glow};
        std::printf("Volumetric clouds (r119i): live knobs: painted fade %.2f, full cloud from %.0f deg up, colour cap %.2f\n",
                    double(live.painted), double(live.horizon), double(live.glow));
    }
'''),
    (CPP,
     r'''    BbReport::Printf("Volumetric clouds (r119g): cover %.2f, tint %.2f, smear fix %s\n", double(live.cover),
                     double(live.tint), live.smear ? "on" : "off"); // bbport (r119g_clouds-smear-and-cover)
''',
     r'''    BbReport::Printf("Volumetric clouds (r119g): cover %.2f, tint %.2f, smear fix %s\n", double(live.cover),
                     double(live.tint), live.smear ? "on" : "off"); // bbport (r119g_clouds-smear-and-cover)
    // bbport (r119i_clouds-behind-painted-sky): under 300 characters
    BbReport::Printf("Volumetric clouds (r119i): painted fade %.2f, full cloud from %.0f deg up, colour cap %.2f; painted share %.3f "
                     "(of the marched sky pixels, those whose opacity the painted sky took %.0f%% or more of), drift %.1f m/s\n",
                     double(live.painted), double(live.horizon), double(live.glow), s.painted,
                     double(CL_PAINTED_SHARE) * 100.0, double(CL::LayerSpeed(ClockState().Velocity(ClockKnobs()), live)));
'''),
    (HDR,
     r'''    int told_smear = -1;''',
     r'''    std::array<float, 3> told_paint{-1.0f, -1.0f, -1.0f}; ///< bbport (r119i): the live painted fade, horizon and glow cap said last (below 0: none yet)
    int told_smear = -1;'''),
    # ---- the test ----------------------------------------------------------------------------------------------------------
    (TEST,
     r'''        assert(p.look[0] == 16.0f && p.look[1] == OpacityCap && p.look[2] == HorizonFrom &&
               p.look[3] == HorizonTo);''',
     r'''        assert(p.look[0] == 16.0f && p.look[1] == OpacityCap && p.look[2] == HorizonEdges(knobs.horizon)[0] &&
               p.look[3] == HorizonEdges(knobs.horizon)[1]); // bbport (r119i): the default horizon is no longer the old edges'''),
    (TEST,
     r'''        assert(p.tone[0] == Ambient && p.tone[1] == LightGain && p.tone[2] == Desaturate &&
               p.tone[3] == Forward);''',
     r'''        assert(p.tone[0] == Ambient && p.tone[1] == LightGain &&
               Near(p.tone[2], double(Desaturate) * (1.0 - double(knobs.tint)), 1e-6) && p.tone[3] == Forward); // bbport (r119i): tint default 0.7'''),
    (TEST,
     r'''d.speed == DefaultSpeed && d.speed == 6.0f);''',
     r'''d.speed == DefaultSpeed && d.speed == 1.5f);'''),
    # review fix (r119i): block j's drift asserts assumed the default speed 6 (6 m/s x 6 = 36, and `fast` 12 = twice it);
    # at 1.5 they would fail: `fast` is 3 (twice 1.5), 9 and 18 m/s
    (TEST,
     r'''        const Knobs fast = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "12");''',
     r'''        const Knobs fast = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "3"); // r119i: twice the default 1.5'''),
    (TEST,
     r'''Near(LayerWind(0.0f, 6.0f, d)[0], 36.0, 1e-4) && Near(LayerWind(0.0f, 6.0f, fast)[0], 72.0, 1e-4)''',
     r'''Near(LayerWind(0.0f, 6.0f, d)[0], 9.0, 1e-4) && Near(LayerWind(0.0f, 6.0f, fast)[0], 18.0, 1e-4)'''),
    (TEST,
     r'''        assert(Near(LayerSpeed(6.0f, d), 36.0, 1e-4) && LayerSpeed(15.0f, d) == DriftCeil * d.speed);''',
     r'''        assert(Near(LayerSpeed(6.0f, d), 9.0, 1e-4) && LayerSpeed(15.0f, d) == DriftCeil * d.speed); // bbport (r119i): speed 1.5'''),
    (TEST,
     r'''        // at the slowest default a cloud 1000 m away moves more than 1.5 degrees in 2 s (about 20 px at 1280x720)
        assert(LayerSpeed(0.0f, d) * 2.0f / 1000.0f * 57.29578f > 1.5f);''',
     r'''        // at the slowest default a cloud 1000 m away moves more than 0.4 degrees in 2 s (r119i: speed 1.5, was 1.5 degrees at 6)
        assert(LayerSpeed(0.0f, d) * 2.0f / 1000.0f * 57.29578f > 0.4f);'''),
    (TEST,
     r'''LayerSpeed(6.0f, slow) < LayerSpeed(6.0f, d) / 20.0f''',
     r'''LayerSpeed(6.0f, slow) < LayerSpeed(6.0f, d) / 5.0f'''),
    (TEST,
     r'''ParseTint("x") == DefaultTint && DefaultTint == 0.0f);''',
     r'''ParseTint("x") == DefaultTint && DefaultTint == 0.7f);'''),
    (TEST,
     r'''        assert(d.tint == 0.0f && d.smear);''',
     r'''        assert(d.tint == DefaultTint && d.smear);'''),
    (TEST,
     r'''        assert(on.extra[0] == 0.0f && on.extra[1] == float(LightTaps) && on.extra[2] == ShadeBase &&
               on.extra[3] == HorizonGlow && on.tone[2] == Desaturate);''',
     r'''        assert(on.extra[0] == DefaultTint && on.extra[1] == float(LightTaps) && on.extra[2] == ShadeBase &&
               on.extra[3] == HorizonGlow && Near(on.tone[2], double(Desaturate) * (1.0 - double(DefaultTint)), 1e-6));'''),
    (TEST,
     r'''    std::puts("cloud layer: ok");
''',
     r'''    // p. (r119i_clouds-behind-painted-sky) the painted fade, the colour cap and the horizon: parsing, defaults, the Params slots, the counter.
    {
        assert(ParsePainted(nullptr) == DefaultPainted && ParsePainted("0") == 0.0f && ParsePainted("0.5") == 0.5f &&
               ParsePainted("9") == 1.0f && ParsePainted("-1") == 0.0f && ParsePainted("x") == DefaultPainted);
        assert(ParseGlow(nullptr) == DefaultGlow && ParseGlow("0") == 0.0f && ParseGlow("99") == MaxGlow &&
               ParseGlow("x") == DefaultGlow);
        assert(ParseHorizon(nullptr) == DefaultHorizon && ParseHorizon("0") == 0.0f && ParseHorizon("99") == MaxHorizon &&
               ParseHorizon("-5") == 0.0f && ParseHorizon("x") == DefaultHorizon);
        // the horizon: 0 (or no number) is the old edges; 30 degrees is the slope sin 30 = 0.5, the fade starting at sin 12 degrees
        const std::array<float, 2> old_edges = HorizonEdges(0.0f);
        assert(old_edges[0] == HorizonFrom && old_edges[1] == HorizonTo && HorizonEdges(std::nanf(""))[0] == HorizonFrom);
        const std::array<float, 2> edges = HorizonEdges(DefaultHorizon);
        assert(DefaultHorizon == 30.0f && Near(edges[1], 0.5, 1e-5) &&
               Near(edges[0], std::sin(12.0 * 3.14159265358979 / 180.0), 1e-5) && edges[0] < edges[1]);
        assert(HorizonEdges(60.0f)[1] > HorizonEdges(30.0f)[1] && HorizonEdges(10.0f)[1] < HorizonEdges(30.0f)[1]);
        // the speed: the default is 1.5 (3.75 to 12 m/s from the held wind speed)
        assert(DefaultSpeed == 1.5f && Near(HeldSpeed(0.0f) * DefaultSpeed, 3.75, 1e-6) && Near(HeldSpeed(99.0f) * DefaultSpeed, 12.0, 1e-6));
        const Knobs d = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr);
        assert(d.painted == DefaultPainted && d.horizon == DefaultHorizon && d.glow == DefaultGlow && d.tint == 0.7f);
        const Knobs off = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr,
                                    nullptr, nullptr, nullptr, "0", "0", "0");
        assert(off.painted == 0.0f && off.horizon == 0.0f && off.glow == 0.0f);
        const std::array<float, 12> rows{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const std::array<float, 4> proj{1.0f, -1.0f, 1.0f, 0.1f};
        const VolumetricFogNoise::Drift drift;
        const std::array<float, 3> light = Unit(0.0f, 0.8f, 0.6f);
        const std::array<float, 2> slope = CloudShadows::Slope(light);
        const Params on = MakeParams(rows, proj, drift, d, light, true, slope, {0.0f, 0.0f});
        assert(on.paint[0] == DefaultPainted && on.paint[1] == RingNear && on.paint[2] == RingFar && on.paint[3] == DefaultGlow);
        assert(on.look[2] == edges[0] && on.look[3] == edges[1]);
        // everything off gives the r119h look in the block: no painted fade, no cap, the old horizon edges
        const Params none = MakeParams(rows, proj, drift, off, light, true, slope, {0.0f, 0.0f});
        assert(none.paint[0] == 0.0f && none.paint[3] == 0.0f && none.look[2] == HorizonFrom && none.look[3] == HorizonTo);
        assert(RingNear < RingFar && RingNear >= 4.0f);
        // the counter: the painted share is of the marched (hit) sky pixels
        Totals t;
        std::array<std::uint32_t, CL_WORDS> frame{};
        frame[CL_WORD_HIT] = 200;
        frame[CL_WORD_PAINTED] = 50;
        t.Add(frame);
        assert(Near(SharesOf(t).painted, 0.25, 1e-9) && SharesOf(Totals{}).painted == 0.0);
        assert(CL_WORD_PAINTED == 16u && CL_WORDS == 17u && CL_WORD_PAINTED < CL_WORDS);
    }
    std::puts("cloud layer: ok");
'''),
    # ---- the README ----------------------------------------------------------------------------------------------------------
    (README,
     r'''(a ray rising less steeply than 0.05 is not clouded, one above 0.22 is in full)''',
     r'''(r119i: by default a ray rising less than 12 degrees is not clouded and one above 30 degrees is in full, `BB_VOLUMETRIC_CLOUDS_HORIZON=0` gives the older fade, a ray's slope 0.05 to 0.22; and they sit behind the painting: where the painted dome has shapes of its own, a ridge, the rim of a painted cloud, the opacity is taken back, `BB_VOLUMETRIC_CLOUDS_PAINTED`, and a cloud's colour is at most 1.6 times the sky's brightness behind it, `BB_VOLUMETRIC_CLOUDS_GLOWMAX`)'''),
    (README,
     r'''so 15 to 48 m/s at the default: 0.8 to 2.6 degrees a second at 1000 m, 20 to 60 pixels in 2 s at 1280x720 (at 1 the layer drifted 1.6 to 15 m/s: too slow to see in two stills).''',
     r'''so 3.75 to 12 m/s at the default 1.5 (r119i; it was 15 to 48 m/s at 6, 0.8 to 2.6 degrees a second at 1000 m, too fast): 0.2 to 0.7 degrees a second at 1000 m (at 1 the layer drifted 2.5 to 8 m/s).'''),
    (README,
     r'''with the test tools' live knobs file it can be changed in a running game | `6` |''',
     r'''with the test tools' live knobs file it can be changed in a running game | `1.5` |'''),
    (README,
     r'''(the look before this knob: grey and cream clouds); at `1` both are the sky's own colour, so over a dusk glow the clouds are dusk coloured and blend with it. A live knob with the test tools' live knobs file | `0` |''',
     r'''(the look before this knob: grey and cream clouds); at `1` both are the sky's own colour, so over a dusk glow the clouds are dusk coloured and blend with it. At the default 0.7 (r119i; it was 0, grey clouds over a warm dome) they are 70% the sky's own. A live knob with the test tools' live knobs file | `0.7` |'''),
    (README,
     r'''| `BB_VOLUMETRIC_CLOUDS_DENSITY` |''',
     r'''| `BB_VOLUMETRIC_CLOUDS_PAINTED` | 0 to 1: how much of the clouds' opacity the painted sky's own shapes take back (r119i). The sky dome is a painted mesh with a ridge, a horizon glow and painted clouds; each march block (2 x 2 pixels) compares its sky brightness and view z with 12 sky pixels round it (8 at 12 pixels and 4 at 40 pixels on a 1080 line scene, scaled with the scene's height): a brightness that differs (a difference over the sum of 0.08 starts, 0.38 is whole) or a view z that jumps (a ratio of 1.16 starts, 1.65 is whole) takes that share back, times this knob, so the clouds thin out at the painting's edges and stay in its smooth open parts. A ring pixel that is not sky is skipped. `0` is off (the older look); a live knob with the test tools' live knobs file. Cost: 12 depth reads and up to 12 colour reads for each sky march block, about 0.05 to 0.15 ms at 1080p internal (unmeasured). The log line `Volumetric clouds (r119i)` says the share of the marched sky pixels that lost a quarter of their opacity or more | `0.8` |
| `BB_VOLUMETRIC_CLOUDS_GLOWMAX` | 0 to 8: the most a cloud's own colour (its premultiplied colour over its opacity) may be, as a multiple of the brightness of the sky behind it (r119i): a lit rim was up to 3 times the sky and out-shone the painting. `0` is off; a live knob with the test tools' live knobs file | `1.6` |
| `BB_VOLUMETRIC_CLOUDS_HORIZON` | 0 to 60: the elevation in degrees from which the clouds are in full; they fade in over the lowest 0.4 of it (12 to 30 degrees at the default), so the painted horizon keeps its own look (r119i). `0` is off: the older fade over a ray slope of 0.05 to 0.22 (3 to 13 degrees). A live knob with the test tools' live knobs file | `30` |
| `BB_VOLUMETRIC_CLOUDS_DENSITY` |'''),
]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    """Ties (rule 10): the README, the shader, the header, the code and the test agree."""
    params, cpp, hdr, readme, test = texts[PARAMS], texts[CPP], texts[HDR], texts[README], texts[TEST]
    comp, layout = texts[COMP], texts[LAYOUT]
    for text in ("DefaultPainted = 0.8f;", "RingNear = 12.0f, RingFar = 40.0f;", "DefaultGlow = 1.6f, MaxGlow = 8.0f;",
                 "DefaultHorizon = 30.0f, MaxHorizon = 60.0f;", "HorizonFromShare = 0.4f;", "DefaultSpeed = 1.5f;",
                 "DefaultTint = 0.7f;", "sizeof(Params) == 15 * 16"):
        if params.count(text) != 1:
            raise SystemExit("tie check: %s" % text)
    # the README rows against the header's numbers
    def row(name):
        rows = [l for l in readme.split("\n") if l.startswith("| `%s` |" % name)]
        if len(rows) != 1:
            raise SystemExit("tie check: README row %s" % name)
        return rows[0]
    r = row("BB_VOLUMETRIC_CLOUDS_PAINTED")
    for text in ("8 at 12 pixels and 4 at 40 pixels", "0.08 starts, 0.38 is whole", "ratio of 1.16 starts, 1.65 is whole", "| `0.8` |"):
        if text not in r:
            raise SystemExit("tie check: README PAINTED row lacks %r" % text)
    r = row("BB_VOLUMETRIC_CLOUDS_GLOWMAX")
    if "0 to 8" not in r or not r.endswith("| `1.6` |"):
        raise SystemExit("tie check: README GLOWMAX row against DefaultGlow / MaxGlow")
    r = row("BB_VOLUMETRIC_CLOUDS_HORIZON")
    if "0 to 60" not in r or "12 to 30 degrees" not in r or not r.endswith("| `30` |"):
        raise SystemExit("tie check: README HORIZON row against DefaultHorizon / MaxHorizon / HorizonFromShare")
    r = row("BB_VOLUMETRIC_CLOUDS_SPEED")
    if "3.75 to 12 m/s" not in r or not r.endswith("| `1.5` |"):
        raise SystemExit("tie check: README SPEED row against DefaultSpeed x DriftFloor / DriftCeil")
    r = row("BB_VOLUMETRIC_CLOUDS_TINT")
    if "0.7" not in r or not r.endswith("| `0.7` |"):
        raise SystemExit("tie check: README TINT row against DefaultTint")
    # the shader's constants against the README's numbers (0.08 / 0.30 span = 0.38; ln 0.15 = ratio 1.16, ln 0.5 = ratio 1.65)
    for text in ("const float PAINT_LO = 0.08, PAINT_SPAN = 0.30;", "smoothstep(0.15, 0.5, abs(log("):
        if comp.count(text) != 1:
            raise SystemExit("tie check: shader %s" % text)
    if "#define CL_WORD_PAINTED 16u" not in layout or "#define CL_WORDS 17u" not in layout:
        raise SystemExit("tie check: layout")
    for name in ("BB_VOLUMETRIC_CLOUDS_PAINTED", "BB_VOLUMETRIC_CLOUDS_HORIZON", "BB_VOLUMETRIC_CLOUDS_GLOWMAX"):
        if cpp.count('"%s"' % name) != 2:
            raise SystemExit("tie check: %s must be read twice in the engine (start and live), found %d" % (name, cpp.count('"%s"' % name)))
    if "told_paint" not in hdr or "ParsePainted(\"-1\")" not in test or "SharesOf(t).painted" not in test:
        raise SystemExit("tie check: header / test")
    if "paint.x = 0 and paint.w = 0 give the r119h arithmetic." not in comp:
        raise SystemExit("tie check: shader header")
    # a log line stays under 300 characters: the formats with their widest numbers
    for fmt in (
        "Volumetric clouds (r119i, BB_VOLUMETRIC_CLOUDS=1): behind the painted sky: shapes take back 1.00 of the opacity (rings 12 and 40 px "
        "at 1080 lines), full cloud from 60 deg up, colour cap 8.00 x the sky, speed x60.00, tint 1.00; "
        "BB_VOLUMETRIC_CLOUDS_PAINTED, _HORIZON, _GLOWMAX (read at the start)\n",
        "Volumetric clouds (r119i): painted fade 1.00, full cloud from 60 deg up, colour cap 8.00; painted share 1.000 "
        "(of the marched sky pixels, those whose opacity the painted sky took 25% or more of), drift 480.0 m/s\n"):
        if len(fmt) >= 300:
            raise SystemExit("tie check: a log line of %d characters" % len(fmt))
    if not all(ord(c) < 128 for _, _, new in EDITS for c in new):
        raise SystemExit("new text must be ASCII")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R119I_ROOT)" % ROOT)
    files = []
    for path, _, _ in EDITS:
        if path not in files:
            files.append(path)
    plan, texts_now = {}, {}
    for path in files:
        raw, eol, cur = load(path)
        mine = [e for e in EDITS if e[0] == path]
        done = sum(cur.count(new) == 1 for _, old, new in mine)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for _, old, new in mine)
        if done == len(mine):
            state = "applied"
        elif todo == len(mine):
            state = "clean"
        else:
            bad = [old[:60] for _, old, new in mine if not (cur.count(new) == 1 or (cur.count(old) == 1 and cur.count(new) == 0))]
            raise SystemExit("%s: %d of %d edits in place, %d ready to apply (is r119h applied? "
                             "is another patch editing the same text?) first failing anchor: %r"
                             % (path, done, len(mine), todo, bad[:1]))
        plan[path] = (raw, eol, cur, state)
        texts_now[path] = cur
    states = {p[3] for p in plan.values()}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (k, v[3]) for k, v in plan.items()))
    state = states.pop()
    if cmd == "check":
        if state == "applied":
            text_checks(texts_now)
            print("applied (text checks pass)")
        else:
            after = {}
            for path in files:
                cur = plan[path][2]
                for p, old, new in EDITS:
                    if p == path:
                        cur = cur.replace(old, new, 1)
                after[path] = cur
            text_checks(after)
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(files), len(EDITS)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        outs, after = [], {}
        for path in files:
            raw, eol, cur, _ = plan[path]
            for p, old, new in EDITS:
                if p == path:
                    cur = cur.replace(old, new, 1)
            after[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(after)
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                full = os.path.join(ROOT, path)
                open(full + TMP, "wb").write(data)
                os.replace(full + TMP, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                if os.path.exists(os.path.join(ROOT, path) + TMP):
                    os.remove(os.path.join(ROOT, path) + TMP)
            for path, raw in written:
                open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied (%d files edited, %d edits)" % (len(files), len(EDITS)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    outs = []
    for path in files:
        raw, eol, cur, _ = plan[path]
        for p, old, new in reversed(EDITS):
            if p == path:
                if cur.count(new) != 1:
                    raise SystemExit("%s: edit not found exactly once: %r" % (path, new[:70]))
                cur = cur.replace(new, old, 1)
        outs.append((path, cur.replace("\n", eol).encode("utf-8")))
    for path, data in outs:
        open(os.path.join(ROOT, path), "wb").write(data)
    print("reverted (%d files)" % len(files))


if __name__ == "__main__":
    main()
