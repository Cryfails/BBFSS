# r128c_lrt-cutout-props: FEATURE (no tool part), on top of build 77 (r62o and the lamp cut-out chain r62..r62o, r63, r86 in the tree).
# THE SUN SIDE OF CUT-OUT SHADOWS: BB_RT_CARD_SUN=1 makes the ray traced sun (moon at night) cross the cut-out cards (leaves, weeds, bushes,
# and any hook, grille or chain the game draws as a textured card) where the game's alpha test drops the texel, and stop where it keeps it:
# the same card test the lamp rays have had since r63 (rt_cards.glsl cardTraceShadow), now in rt_shadow.comp.
#
# Owner goals (wiki features/lamp-raytracing/goals.md): LRT-G043 (2026-11-14 22:00: "make ray traced foliage an option. The should work for both
# sun ray tracing and lamp ray tracing"), LRT-G042 and LRT-G050 (leaf shaped shadows; "pretty good on foliage" at build 72, lamp side only),
# LRT-G046 (any cut-out shape, hook or chain: the sun side gives a static cut-out that the game's sun pass draws its true shape instead of a
# full polygon), LRT-G003/G004 (sun and every light get the same treatment). Status page tasks/lrt-t03.md: "no sun side" was the first open item.
#
# What the logs say that makes this the next item (b18 r46 line, b75 s1): 'rule 3 ... 458 instances left out of lamp rays as cut-out cards (4 known
# from the sun pass's texture, 458 from their own camera pass draw's discard ...)'. So nearly every cut-out card (plants, bushes, ivy) is known only
# to the CAMERA pass: the game's sun shadow pass draws almost none of them, so today the sun/moon casts NO shadow from any leaf, and a card the
# sun pass does draw is a full polygon in the ray traced sun (an opaque rectangle). With this knob both change: plants and static cut-outs cast
# leaf-shaped moon and sun shadows, and the self shadowing of a bush follows.
#
# HOW (all under CARDS / the knob; nothing runs with it off):
#  1. rt_shadow.comp, two new builds (CMake: rt_shadow_cards_comp = COVERAGE_SKIP CARDS, rt_shadow_half_cards_comp = COVERAGE_SKIP HALF CARDS; the five
#     builds there are byte-identical, proven below): the ray query of Shade becomes cardTraceShadow(scene, TerminateOnFirstHit, 0x01 | CARD_LAMP_MASK,
#     ...): solid casters (mask 1, opaque) end the ray at the first hit as before; a card instance (CARD_LAMP_MASK, built FORCE_NO_OPAQUE by RtShadow when
#     the lamp card path gives it the bit) is read at its texel with the game's rule and the lamp pass's tuning (reference x 0.6, the bilinear footprint's
#     largest texel, level 0), at most 16 candidates with data a ray. The card tables are bindings 6 to 9 of the SAME push set (no second set).
#  2. A card within max(0.03 m, reach) of the ray's start is the pixel's own surface and is passed (rt_cards.glsl: card_skip_below, CARD_SUN_SELF
#     only: the lamp builds do not define it, their SPIR-V is unchanged): the same idea as the lamp's CARD_TMIN 0.03 (r62h).
#  3. HALF build (graphics_rt_sun_half=1, the default of the dev install is 0): the second pass shares a block's first-pass answer when the nine
#     first-pass answers agree; a thin blade's shadow falls between the first-pass pixels (r62o found the same for the lamp pass). A first-pass pixel
#     whose rays met a card candidate therefore stores its answer 1/255 off (towards 0.5): its 3x3 neighbourhoods no longer agree, the fill pixels
#     there trace their own rays. No new bit, no new memory traffic; 1/255 on a filtered shadow term is below the 8-bit output step.
#  4. Counters: the r25 counter buffer's words 16 to 23 (CARD_SUN_FIRST_WORD; BB_RT_GLASS_LIGHT's words 16 to 21 are the same words, so the two are not
#     made together: with BB_RT_GLASS_LIGHT on the knob says so once and stays off). One counted sun trace in 8, as r25's. Every 600 frames one line
#     'Ray traced sun cut-outs (r128c): ...'; a once-line when the knob is read, one when each build is made, one at each live flip.
#  5. C++: RtShadow::CardSunWanted (env once: BB_RT_CARD_SUN exactly 1, needs BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1 because the instances take
#     CARD_LAMP_MASK only through the lamp card path, and not with BB_RT_GLASS_LIGHT); RtShadow::CardSunNow (per sun trace: calls NoteCardLampUser so
#     that the cards take the mask while the sun may read them, makes the two pipelines the first time, returns pipeline, layout and the card tables
#     CardLampReadersNow gives, or nothing); the sun trace's lambda captures that and pushes ten descriptors instead of six. With the test tools'
#     live knobs (the macro BB_R62N_LIVE_KNOBS this file already has when bbport_live_knobs.h exists) BB_RT_CARD_SUN is asked again at every sun trace
#     (a job's set:/unset: flips one running game; without the header the env value stands): this is not a tool, it is the same optional line r62n
#     and r86f carry.
#
# OFF BY DEFAULT, COST WHEN OFF: CardSunWanted() is a function-local static bool (one load a call; it also decides R25Words, which is r25's 16 as before).
# No CARDS pipeline is made, NoteCardLampUser is not called (so no card is made non-opaque for the sun), the sun trace pushes the six descriptors
# of before with the pipeline of before. The five existing rt_shadow builds are byte-identical (spirv compared before and after, below).
# COST ON (estimate, not measured; RTX 4090, 4K output DLSS Performance = 1080p internal): the sun trace casts `rays` (1 by default) a pixel at full
# resolution (about 2.07 M rays); a ray that meets no card costs what it cost (the TLAS already holds the cards non-opaque when BB_RT_CARD_LAMPS=1,
# lamp or not, so no TLAS cost is added), a ray through foliage reads up to 16 layer texels (the lamp pass measured +0.06 to +0.09 ms for its rays at
# 4K, r007). Expect +0.05 to +0.2 ms in a foliage scene, about 0 in an interior or on bare stone; one more GPU profile row is not added (the sun
# trace's own 'ray traced sun' row moves). Memory: none new (the card tables, 101 MiB with BB_RT_CARD_ALPHA=2, belong to the lamp feature; 8 counter
# words); two more compute pipelines made when first wanted (one hitch of a few ms at the first sun trace).
#
# NOT VERIFIED (no compiler here): the C++ spots a compiler could reject are named in the hand-off: vk::ArrayProxy built from (count, pointer),
# the init-capture list of the sun trace's lambda with a plain capture mixed in, BbLiveKnobs::Knob<bool> use, the ternaries of vk::Pipeline and
# vk::PipelineLayout values, and RT_SHADOW_CARDS_COMP / RT_SHADOW_HALF_CARDS_COMP names from the generated headers.
#
# Files: engine/gpu/shadps4/video_core/host_shaders/rt_shadow.comp, rt_cards.glsl, rt_card_sun_layout.h (new); .../renderer_vulkan/rt_card_sun.h (new),
# vk_rt_shadow.h, vk_rt_shadow.cpp; engine/gpu/CMakeLists.txt; README.md. Revert r128c before r62n (it only edits lines r62 and r86 left; it needs
# r62's rt_cards.glsl and the lamp card path).
#
# Use: python -I -X utf8 r128c_lrt-cutout-props.py check | apply | revert
# Root: R128C_LRT_CUTOUT_PROPS_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in r128c_backup. New files are removed by revert.
import os, sys

ROOT = os.environ.get("R128C_LRT_CUTOUT_PROPS_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r128c_backup")
V = "engine/gpu/shadps4/video_core/"
HS = V + "host_shaders/"
RV = V + "renderer_vulkan/"
SH = HS + "rt_shadow.comp"
GL = HS + "rt_cards.glsl"
LAYOUT = HS + "rt_card_sun_layout.h"
CXXH = RV + "rt_card_sun.h"
H = RV + "vk_rt_shadow.h"
C = RV + "vk_rt_shadow.cpp"
CM = "engine/gpu/CMakeLists.txt"
R = "README.md"

NEW = {
LAYOUT: r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r128c_lrt-cutout-props) FEATURE: BB_RT_CARD_SUN's numbers, shared by rt_shadow.comp's CARDS builds and renderer_vulkan/rt_card_sun.h. Plain
// #define lines only, as rt_glass_light_layout.h: GLSL includes this file and C++ includes it as it is.
#ifndef RT_CARD_SUN_LAYOUT_H
#define RT_CARD_SUN_LAYOUT_H

// The CARDS builds' counters: words 16 to 23 of the sun trace's counters (r25_buf), the words BB_RT_GLASS_LIGHT uses (the two are not made together).
// 0 pixels that cast rays, 1 of them with a ray that met a card candidate, 2 layer reads, 3 rays a kept texel stopped, 4 pixels with such a ray,
// 5 candidates passed as the pixel's own surface, 6 rays stopped at the candidate cap, 7 first-pass pixels marked (the half build only).
#define CARD_SUN_FIRST_WORD 16u
#define CARD_SUN_WORDS 8u
// The most card candidates with data one sun ray reads (the lamp rays' default, CARD_RAY_CAP_DEFAULT).
#define CARD_SUN_CAP 16u
// A card nearer than this many metres (or the ray's reach, if more) to the ray's start is the pixel's own surface: passed.
#define CARD_SUN_SELF_M 0.03
// The reference of an "above the reference" rule is scaled by this for the sun's reads (the lamp pass's CARD_REF_SCALE default).
#define CARD_SUN_REF 0.6

#endif
""",
CXXH: r"""// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r128c_lrt-cutout-props) FEATURE: BB_RT_CARD_SUN. No Vulkan here.
//
// The ray traced sun (rt_shadow.comp) crosses the cut-out cards of the ray traced scene as the lamp rays do (rt_cards.glsl cardTraceShadow): a
// leaf's, a weed's or a static cut-out's texel the game's alpha test keeps stops the sun, a dropped texel lets it through. Off by default; it needs
// BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1 (the instances take CARD_LAMP_MASK through the lamp card path) and is not made with BB_RT_GLASS_LIGHT
// (the two share the sun trace's counter words 16 and up).

#include <cstdint>

#include "../host_shaders/rt_card_sun_layout.h"

namespace Vulkan {

/// BB_RT_CARD_SUN's text: exactly "1" is on; unset, empty, "0" or anything else is off.
constexpr bool CardSunText(const char* text) {
    return text != nullptr && text[0] == '1' && text[1] == '\0';
}
static_assert(CardSunText("1") && !CardSunText("0") && !CardSunText("") && !CardSunText("11") && !CardSunText("on") &&
              !CardSunText(nullptr));

inline constexpr std::uint32_t CardSunFirstWord = CARD_SUN_FIRST_WORD;
inline constexpr std::uint32_t CardSunWords = CARD_SUN_WORDS;
/// The sun trace's counters with the knob on (r25's 16 words, then these).
inline constexpr std::uint32_t CardSunCounterWords = CardSunFirstWord + CardSunWords;
static_assert(CardSunWords == 8 && CardSunCounterWords == 24);

} // namespace Vulkan
""",
}

ROW = ("| `BB_RT_CARD_SUN` | FEATURE (r128c), the sun side of the cut-out shadows. `1`: the ray traced sun (and the moon at night, which is the "
       "game's directional light) crosses the cut-out cards of the ray traced scene as the lamp rays do (`BB_RT_CARD_LAMPS` row): a leaf's, a weed's or "
       "a bush's texel that the game's alpha test keeps stops the light, a dropped texel lets it through, so plants and static cut-outs (a grille, a "
       "hook or a chain the game draws as a textured card) cast shadows of their true shape. Nearly every cut-out card is known only to the camera pass "
       "(the game's own sun shadow pass draws almost none): today the sun casts no shadow from any leaf, and a card the sun pass does draw is a full "
       "polygon in the ray traced sun; with this knob both have the leaf's shape, and a bush shades itself. It needs `BB_RT_CARD_ALPHA=2` and "
       "`BB_RT_CARD_LAMPS=1` (a card is in the sun's scene only through that path; with either missing the knob says so once and stays off), and it is "
       "not made with `BB_RT_GLASS_LIGHT` (the two use the same counter words). A card within 3 cm (or the ray's reach) of the ray's start is the pixel's "
       "own surface and is passed; at most 16 candidates with data are read a ray; the texel rule is the lamp pass's (reference x 0.6, the largest of the "
       "bilinear footprint's four texels, level 0). With `graphics_rt_sun_half=1` a first-pass pixel whose ray met a card stores its answer 1/255 off, so "
       "the fill pixels around it trace their own rays instead of sharing a block's answer. Read once at start (exactly `1` is on); with the test tools' "
       "live knobs file a job's `set:BB_RT_CARD_SUN=0` and `unset:BB_RT_CARD_SUN` flip it in one running game. Log: a once-line, one when each pipeline "
       "is made, and every 600 frames `Ray traced sun cut-outs (r128c)`: the sun traces that ran the cut-out build and those that ran the plain one, and "
       "per counted frame the pixels traced, those with a ray that met a card, the layer reads, the rays and pixels a kept texel stopped, the candidates "
       "passed as the pixel's own surface, the rays stopped at the cap and the marked first-pass pixels. Cost: off, none (no pipeline is made, no card "
       "takes the sun's use, the sun trace pushes the descriptors of before); on, a ray that meets no card costs what it did and a ray through foliage "
       "reads up to 16 texels: an estimate of 0.05 to 0.2 ms in a foliage scene at 4K with DLSS Performance, about 0 on bare stone and in interiors, not "
       "measured; no new memory (the card tables belong to `BB_RT_CARD_ALPHA=2`, 101 MiB; 8 counter words) | off |\n")

# (anchor, before, after): the text goes before / after the anchor, which must be in the file exactly once.
# REP: (old, new): old once and new absent = clean; old absent and new once = applied.
EDITS = {
GL: [
("uint card_housing_skips = 0u;\n",
 "",
 r"""// bbport (r128c_lrt-cutout-props) FEATURE (CARD_SUN_SELF is defined by rt_shadow.comp's CARDS builds only; the lamp builds do not define it, so
// their SPIR-V is unchanged): card_skip_below: a card met at a hit nearer than this many metres along the ray is the pixel's own surface and is passed
// untested (0: none); card_self_skips: the cards passed that way (the sun trace counts them and the pass zeroes nothing: one value a pixel).
#ifdef CARD_SUN_SELF
float card_skip_below = 0.0;
uint card_self_skips = 0u;
#endif
"""),
("                ++card_housing_skips;\n                continue;\n            }\n",
 "",
 r"""#ifdef CARD_SUN_SELF
            if (t < card_skip_below) { // bbport (r128c_lrt-cutout-props) FEATURE: the pixel's own surface
                ++card_self_skips;
                continue;
            }
#endif
"""),
],
SH: [
("layout(local_size_x = 8, local_size_y = 8) in;\n",
 r"""#ifdef CARDS
// bbport (r128c_lrt-cutout-props) FEATURE: the CARDS builds (rt_shadow_cards_comp and rt_shadow_half_cards_comp, made only with BB_RT_CARD_SUN=1,
// renderer_vulkan/rt_card_sun.h): the sun's rays cross the cut-out cards (leaves, weeds, a hook or a grille drawn as a textured card) where the
// game's alpha test drops the texel and stop where it keeps it, as the lamp rays of point_shadow_ray.comp's CARDS builds do (cardTraceShadow in
// rt_cards.glsl). The card tables are bindings 6 to 9 of the same push set (renderer_vulkan/vk_rt_shadow.cpp CardSunNow). The builds without CARDS
// are the pass as before, word for word.
#ifdef GLASS_LIGHT
#error "CARDS is not made with GLASS_LIGHT (the two share the counter words 16 and up)"
#endif
#ifndef COVERAGE_SKIP
#error "CARDS needs COVERAGE_SKIP (its r25 flags and counters)"
#endif
#extension GL_GOOGLE_include_directive : require
#define CARD_SET 0
#define CARD_BINDING_ROWS 6
#define CARD_BINDING_POOL 7
#define CARD_BINDING_LAYER_INFO 8
#define CARD_BINDING_ALPHA 9
#define CARD_TRACE_SHADOW
#define CARD_SUN_SELF
#include "rt_cards.glsl"
#include "rt_card_sun_layout.h"
// What this invocation's ray(s) met (Shade adds to them, once a pixel): rays that met a card candidate, layer reads, rays a kept texel stopped, rays
// stopped at the cap. r128_n: the workgroup's counters (CARD_SUN_WORDS), flushed into r25_buf at CARD_SUN_FIRST_WORD by main.
uint sun_rays_met = 0u;
uint sun_reads = 0u;
uint sun_rays_kept = 0u;
uint sun_rays_cap = 0u;
shared uint r128_n[CARD_SUN_WORDS];
#endif

""",
 ""),
("    barrier();\n    invMat = shared_inverse;\n#ifdef HALF\n",
 r"""#ifdef CARDS
    if (count && gl_LocalInvocationIndex < CARD_SUN_WORDS) { // bbport (r128c_lrt-cutout-props)
        r128_n[gl_LocalInvocationIndex] = 0u;
    }
#endif
""",
 ""),
("    }\n}\n#else\nvoid main() {\n",
 r"""#ifdef CARDS
        // bbport (r128c_lrt-cutout-props): R25Count's barrier made the group's counts whole
        if (gl_LocalInvocationIndex < CARD_SUN_WORDS && r128_n[gl_LocalInvocationIndex] != 0u) {
            atomicAdd(r25_buf.n[CARD_SUN_FIRST_WORD + gl_LocalInvocationIndex], r128_n[gl_LocalInvocationIndex]);
        }
#endif
""",
 ""),
],
CM: [
("add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_cards_comp HALF=1 CENTRED=1 CARDS=1)\n",
 "",
 r"""# bbport (r128c_lrt-cutout-props): BB_RT_CARD_SUN=1: the sun trace's two builds with the cut-out cards in its rays (CARDS; the five builds of
# rt_shadow.comp above are unchanged). They include the card test and the sun side's numbers.
add_host_shader(rt_shadow.comp rt_shadow_cards_comp COVERAGE_SKIP=1 CARDS=1)
add_host_shader(rt_shadow.comp rt_shadow_half_cards_comp COVERAGE_SKIP=1 HALF=1 CARDS=1)
add_custom_command(OUTPUT ${SHADER_DIR}/rt_shadow_cards_comp.h APPEND DEPENDS ${SHADER_SRC}/rt_cards.glsl
    ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_card_uv_layout.h ${SHADER_SRC}/rt_card_sun_layout.h)
add_custom_command(OUTPUT ${SHADER_DIR}/rt_shadow_half_cards_comp.h APPEND DEPENDS ${SHADER_SRC}/rt_cards.glsl
    ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_card_uv_layout.h ${SHADER_SRC}/rt_card_sun_layout.h)
"""),
],
H: [
('#include "video_core/renderer_vulkan/rt_card_skinned.h" // bbport (r62n_cutout-skinned-blocker)\n',
 "",
 '#include "video_core/renderer_vulkan/rt_card_sun.h" // bbport (r128c_lrt-cutout-props)\n'),
("    static_assert(RtGlassLightFirstWord >= R25Slots);\n",
 "",
 "    static_assert(CardSunFirstWord >= R25Slots); // bbport (r128c_lrt-cutout-props)\n"),
("    vk::UniquePipeline r25_half_pipeline;\n",
 "",
 r"""    // bbport (r128c_lrt-cutout-props) FEATURE: BB_RT_CARD_SUN=1 (needs BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1; not with BB_RT_GLASS_LIGHT): the sun's
    // rays cross the cut-out cards as the lamp rays do (rt_shadow.comp's CARDS builds, rt_shadow_cards_comp and its half form, made when first
    // wanted by CardSunNow). CardSunNow also tells the scene that a reader of the cards exists (NoteCardLampUser), and returns the build for this
    // sun trace with the card tables, or nothing (the plain build is pushed as before).
    struct CardSunUse {
        vk::Pipeline pipeline;
        vk::PipelineLayout layout;
        vk::Buffer rows, pool, info;
        vk::ImageView layers;
        vk::Sampler sampler;
    };
    [[nodiscard]] static bool CardSunWanted();
    [[nodiscard]] CardSunUse CardSunNow(bool half);
    vk::UniqueDescriptorSetLayout card_sun_set, card_sun_half_set;
    vk::UniquePipelineLayout card_sun_layout, card_sun_half_layout;
    vk::UniquePipeline card_sun_pipeline, card_sun_half_pipeline;
    bool card_sun_tried = false, card_sun_half_tried = false;
    u32 card_sun_cards = 0, card_sun_plain = 0; ///< sun traces since the last line that ran the cut-out build / the plain one
    std::array<u32, CardSunWords> card_sun_last{}; ///< the counters' values at the last line
"""),
],
C: [
('#include "video_core/host_shaders/rt_card_guard_comp.h" // bbport (r62e_leaf-cards-usable)\n',
 "",
 '#include "video_core/host_shaders/rt_shadow_cards_comp.h"      // bbport (r128c_lrt-cutout-props)\n'
 '#include "video_core/host_shaders/rt_shadow_half_cards_comp.h" // bbport (r128c_lrt-cutout-props)\n'),
("// The mask's hold (CardLampHold): an entry's instance takes CardLampMask when its row has data\n",
 r"""// bbport (r128c_lrt-cutout-props) FEATURE: BB_RT_CARD_SUN, read once: exactly 1 turns on the sun side of the cut-out shadows (rt_card_sun.h). It needs
// the cards in the scene (BB_RT_CARD_ALPHA=2 with BB_RT_CARD_LAMPS=1: the lamp card path gives an instance CARD_LAMP_MASK) and is not made with
// BB_RT_GLASS_LIGHT (the sun trace's counter words 16 and up). Said once when the variable is set, with the reason when it stays off.
bool RtShadow::CardSunWanted() {
    static const bool wanted = [] {
        const char* const env = std::getenv("BB_RT_CARD_SUN");
        if (env == nullptr || *env == '\0') {
            return false;
        }
        const bool one = CardSunText(env);
        const bool cards = one && CardLampsWanted();
        const bool glass = RtGlassLightOn();
        std::printf("Ray traced sun cut-outs (r128c): BB_RT_CARD_SUN=%s: %s\n", env,
                    !one      ? "off (only 1 turns it on)"
                    : !cards  ? "off - it needs BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1 (the cards in the scene)"
                    : glass   ? "off - it is not made with BB_RT_GLASS_LIGHT (the two share the sun trace's counter words)"
                              : "the sun's rays cross the cut-out cards where the game's alpha test drops the texel and stop where it "
                                "keeps it (rt_shadow.comp CARDS builds; the lamp rays' rule; a card within 3 cm of the ray's start is the "
                                "pixel's own surface)");
        return one && cards && !glass;
    }();
    return wanted;
}

// bbport (r128c_lrt-cutout-props) FEATURE: the cut-out build of the sun trace for this sun trace, or nothing (the plain build is pushed). While the
// knob is on the scene is told that a reader of the cards exists (NoteCardLampUser, as the lamp pass does) so that the cards take CARD_LAMP_MASK; the
// pipelines are made the first time (the full and the half form apart); nothing is returned while the live knob (test tools' knobs file) says off,
// the pipeline could not be made, or the scene holds no card with the mask yet (CardLampReadersNow).
RtShadow::CardSunUse RtShadow::CardSunNow(bool half) {
    CardSunUse use{};
    if (!CardSunWanted()) {
        return use;
    }
    NoteCardLampUser();
#ifdef BB_R62N_LIVE_KNOBS
    static BbLiveKnobs::Knob<bool> live{"BB_RT_CARD_SUN", [](const char* text) -> bool { return CardSunText(text); }};
    static bool told_on = true;
    const bool on = live.Get();
    if (on != told_on) {
        told_on = on;
        std::printf("Ray traced sun cut-outs (r128c): the cut-out build is now %s (live)\n", on ? "on" : "off");
    }
    if (!on) {
        ++card_sun_plain;
        return use;
    }
#endif
    bool& tried = half ? card_sun_half_tried : card_sun_tried;
    if (!tried) {
        tried = true;
        using enum vk::DescriptorType;
        const bool made =
            half ? EffectPass::Create(instance, card_sun_half_set, card_sun_half_layout, card_sun_half_pipeline,
                                      {eStorageBuffer, eCombinedImageSampler, eStorageImage, eAccelerationStructureKHR,
                                       eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer,
                                       eCombinedImageSampler},
                                      sizeof(TracePush), std::span<const u32>{RT_SHADOW_HALF_CARDS_COMP},
                                      "Ray traced shadows (cut-outs, half resolution)")
                 : EffectPass::Create(instance, card_sun_set, card_sun_layout, card_sun_pipeline,
                                      {eStorageBuffer, eCombinedImageSampler, eStorageImage, eAccelerationStructureKHR,
                                       eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer,
                                       eCombinedImageSampler},
                                      sizeof(TracePush), std::span<const u32>{RT_SHADOW_CARDS_COMP},
                                      "Ray traced shadows (cut-outs)");
        std::printf("Ray traced sun cut-outs (r128c): the %s build %s\n", half ? "half resolution" : "full resolution",
                    made ? "made" : "could not be made: the sun trace runs its plain build");
    }
    const vk::Pipeline pipeline = half ? *card_sun_half_pipeline : *card_sun_pipeline;
    const auto readers = CardLampReadersNow();
    if (!pipeline || readers.instances == 0 || !readers.rows || !readers.pool || !readers.info || !readers.layers ||
        !readers.sampler) {
        ++card_sun_plain;
        return use;
    }
    ++card_sun_cards;
    use.pipeline = pipeline;
    use.layout = half ? *card_sun_half_layout : *card_sun_layout;
    use.rows = readers.rows;
    use.pool = readers.pool;
    use.info = readers.info;
    use.layers = readers.layers;
    use.sampler = readers.sampler;
    return use;
}

""",
 ""),
("    r25_half = R25HalfWanted(); // bbport (r37_menu-options)\n",
 "",
 "    const CardSunUse card_sun = CardSunNow(r25_half); // bbport (r128c_lrt-cutout-props): empty unless BB_RT_CARD_SUN=1\n"),
("        r25_frames = 0;\n",
 r"""        // bbport (r128c_lrt-cutout-props) FEATURE: BB_RT_CARD_SUN=1: its counters, means per counted frame as r25's (u32 differences survive the wrap)
        if (CardSunWanted()) {
            std::array<u32, CardSunWords> got{};
            std::memcpy(got.data(), static_cast<const u32*>(r25_readback.mapped) + CardSunFirstWord, sizeof(got));
            std::array<double, CardSunWords> m{};
            for (u32 i = 0; i < CardSunWords && counted != 0; ++i) {
                m[i] = double(u32(got[i] - card_sun_last[i])) / double(counted);
            }
            card_sun_last = got;
            std::printf("Ray traced sun cut-outs (r128c): %u sun traces ran the cut-out build, %u the plain one (cut-out cards in the scene %u); a counted "
                        "frame (%u): pixels traced %.0f, with a ray that met a card %.0f, layer reads %.0f, rays stopped by a kept texel %.0f (pixels "
                        "%.0f), candidates passed as the pixel's own surface %.0f, rays stopped at the cap %.0f, first-pass pixels marked %.0f\n",
                        card_sun_cards, card_sun_plain, card_lamp_instances, counted, m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7]);
            card_sun_cards = card_sun_plain = 0;
        }
""",
 ""),
],
}

REPS = {
C: [
("         sampler = *sampler, trace_pipeline = *trace_pipeline, trace_layout = *trace_layout,\n",
 "         sampler = *sampler, card_sun, // bbport (r128c_lrt-cutout-props): the cut-out build, or nothing\n"
 "         trace_pipeline = card_sun.pipeline ? card_sun.pipeline : *trace_pipeline,\n"
 "         trace_layout = card_sun.pipeline ? card_sun.layout : *trace_layout,\n"),
("         half_pipeline = r25_half ? *r25_half_pipeline : vk::Pipeline{},\n"
 "         half_layout = r25_half ? *r25_half_layout : vk::PipelineLayout{},\n",
 "         half_pipeline = r25_half ? (card_sun.pipeline ? card_sun.pipeline : *r25_half_pipeline) : vk::Pipeline{},\n"
 "         half_layout = r25_half ? (card_sun.pipeline ? card_sun.layout : *r25_half_layout) : vk::PipelineLayout{},\n"),
("            const std::array<vk::WriteDescriptorSet, 6> trace_writes{{\n",
 "            // bbport (r128c_lrt-cutout-props): bindings 6 to 9 are the cut-out build's card tables (pushed only with it)\n"
 "            const vk::DescriptorBufferInfo cs_rows{card_sun.rows, 0, VK_WHOLE_SIZE};\n"
 "            const vk::DescriptorBufferInfo cs_pool{card_sun.pool, 0, VK_WHOLE_SIZE};\n"
 "            const vk::DescriptorBufferInfo cs_info{card_sun.info, 0, VK_WHOLE_SIZE};\n"
 "            const vk::DescriptorImageInfo cs_alpha{card_sun.sampler, card_sun.layers, vk::ImageLayout::eGeneral};\n"
 "            const std::array<vk::WriteDescriptorSet, 10> trace_writes{{\n"),
("                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &r25_info},\n"
 "            }};\n"
 "            if (!use_vsm) {\n"
 "                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, trace_pipeline);\n"
 "                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, trace_layout, 0,\n"
 "                                            trace_writes);\n",
 "                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &r25_info},\n"
 "                {.dstBinding = 6, .descriptorCount = 1, // r128c: the cut-out cards (rt_shadow_cards_comp)\n"
 "                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &cs_rows},\n"
 "                {.dstBinding = 7, .descriptorCount = 1,\n"
 "                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &cs_pool},\n"
 "                {.dstBinding = 8, .descriptorCount = 1,\n"
 "                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &cs_info},\n"
 "                {.dstBinding = 9, .descriptorCount = 1,\n"
 "                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &cs_alpha},\n"
 "            }};\n"
 "            // the plain build has six bindings, the cut-out build ten (a count and a pointer: no copy)\n"
 "            const vk::ArrayProxy<const vk::WriteDescriptorSet> trace_push(card_sun.pipeline ? 10u : 6u, trace_writes.data());\n"
 "            if (!use_vsm) {\n"
 "                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, trace_pipeline);\n"
 "                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, trace_layout, 0,\n"
 "                                            trace_push);\n"),
("                    cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, half_layout, 0,\n"
 "                                                trace_writes);\n",
 "                    cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, half_layout, 0,\n"
 "                                                trace_push);\n"),
],
H: [
("        return RtGlassLightOn() ? RtGlassLightCounterWords : R25Slots;\n",
 "        // bbport (r128c_lrt-cutout-props): BB_RT_CARD_SUN=1 (not made with BB_RT_GLASS_LIGHT): the counters hold CardSunWords words more, from\n"
 "        // CardSunFirstWord\n"
 "        return RtGlassLightOn() ? RtGlassLightCounterWords : CardSunWanted() ? CardSunCounterWords : R25Slots;\n"),
],
SH: [
("""        rayQueryEXT query;
        rayQueryInitializeEXT(query, scene,
                              gl_RayFlagsTerminateOnFirstHitEXT | gl_RayFlagsOpaqueEXT, 0x01u,
                              origin, reach * 0.5, ray, max_distance);
        rayQueryProceedEXT(query);
        if (rayQueryGetIntersectionTypeEXT(query, true) ==
            gl_RayQueryCommittedIntersectionNoneEXT) {
            ++lit;
        }
    }
#ifdef GLASS_LIGHT
    // bbport (r86_glass-light-stage2a): the panes along the sun's direction, where it was reached
""",
 """#ifdef CARDS
        // bbport (r128c_lrt-cutout-props) FEATURE: the ray crosses the cut-out cards of the scene (mask CARD_LAMP_MASK, built FORCE_NO_OPAQUE: a leaf,
        // a weed, a hook or a grille drawn as a card) where the game's alpha test drops the texel and stops where it keeps it, as the lamp rays do
        // (cardTraceShadow, rt_cards.glsl). The solid casters (mask 1, opaque) end the ray at the first hit as before. The reading is the lamp
        // pass's default: the reference of an above-the-reference rule times CARD_SUN_REF and the largest texel of the bilinear footprint (a thin
        // blade keeps its shadow), level 0 (no footprint: the sun's soft edge comes from the rays' disc and the filter), at most CARD_SUN_CAP
        // candidates with data. A card within max(CARD_SUN_SELF_M, reach) of the ray's start is the pixel's own surface: passed.
        card_ref_scale = CARD_SUN_REF;
        card_dilate = true;
        card_skip_below = max(CARD_SUN_SELF_M, reach);
        const CardRay sun_hit = cardTraceShadow(scene, gl_RayFlagsTerminateOnFirstHitEXT, 0x01u | CARD_LAMP_MASK, origin,
                                                reach * 0.5, ray, max_distance, CARD_SUN_CAP, 0.0, 0.0);
        card_ref_scale = 1.0;
        card_dilate = false;
        sun_rays_met += sun_hit.seen != 0u ? 1u : 0u;
        sun_reads += sun_hit.tested;
        sun_rays_kept += sun_hit.how == CARD_RAY_KEPT ? 1u : 0u;
        sun_rays_cap += sun_hit.how == CARD_RAY_CAP ? 1u : 0u;
        if (sun_hit.t < 0.0) {
            ++lit;
        }
    }
#else
        rayQueryEXT query;
        rayQueryInitializeEXT(query, scene,
                              gl_RayFlagsTerminateOnFirstHitEXT | gl_RayFlagsOpaqueEXT, 0x01u,
                              origin, reach * 0.5, ray, max_distance);
        rayQueryProceedEXT(query);
        if (rayQueryGetIntersectionTypeEXT(query, true) ==
            gl_RayQueryCommittedIntersectionNoneEXT) {
            ++lit;
        }
    }
#endif
#ifdef GLASS_LIGHT
    // bbport (r86_glass-light-stage2a): the panes along the sun's direction, where it was reached
"""),
("""#else
    imageStore(raw_img, pixel, vec4(float(lit) * radius_scale));
#endif
    return fill ? CLS_FILL_RAY : CLS_RAY;
""",
 """#else
#ifdef CARDS
    // bbport (r128c_lrt-cutout-props) FEATURE: the answer. In the half-resolution build a first-pass pixel whose ray met a card candidate stores
    // it 1/255 towards 0.5: the second pass shares a block's first-pass answer only where the nine first-pass answers around it are one value
    // (HalfAnswer), so the pixels around a marked one trace their own rays (a thin blade's shadow lies between the first-pass pixels, r62o). The
    // filter reads the value: 1/255 of the shadow term is below the output's 8-bit step.
    float sun_vis = float(lit) * radius_scale;
#ifdef HALF
    const bool sun_marked = !fill && sun_rays_met != 0u;
    if (sun_marked) {
        sun_vis += sun_vis >= 0.5 ? -(1.0 / 255.0) : (1.0 / 255.0);
    }
#endif
    imageStore(raw_img, pixel, vec4(sun_vis));
    if ((r25_flags & R25_COUNT) != 0u) { // counted sun traces only (one in 8): CARD_SUN_FIRST_WORD + 0 to 7 of the r25 counters
        atomicAdd(r128_n[0], 1u);
        atomicAdd(r128_n[1], sun_rays_met != 0u ? 1u : 0u);
        atomicAdd(r128_n[2], sun_reads);
        atomicAdd(r128_n[3], sun_rays_kept);
        atomicAdd(r128_n[4], sun_rays_kept != 0u ? 1u : 0u);
        atomicAdd(r128_n[5], card_self_skips);
        atomicAdd(r128_n[6], sun_rays_cap);
#ifdef HALF
        atomicAdd(r128_n[7], sun_marked ? 1u : 0u);
#endif
    }
#else
    imageStore(raw_img, pixel, vec4(float(lit) * radius_scale));
#endif
#endif
    return fill ? CLS_FILL_RAY : CLS_RAY;
"""),
],
}


def readme_edit(text):
    """The README row goes after the BB_RT_CARD_LAMP_SKINNED row (the whole line is the anchor)."""
    lines = [l for l in text.split("\n") if l.startswith("| `BB_RT_CARD_LAMP_SKINNED`, `BB_RT_CARD_LAMP_BONES`, `BB_RT_CARD_LAMP_HOUSING` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_RT_CARD_LAMP_SKINNED row is there %d times, wanted 1" % len(lines))
    return (lines[0] + "\n", "", ROW)


ORDER = [GL, SH, CM, H, C, R]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    return [readme_edit(text)] if path == R else EDITS.get(path, [])


def new_bytes(path):
    return NEW[path].replace("\n", "\r\n").encode("utf-8")


def new_state(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    return "applied" if open(full, "rb").read() == new_bytes(path) else "other"


def state_of(cur, eds, reps, path):
    """'applied', 'clean', else refuse. Inserted texts are found by themselves (a later patch may have put its text between)."""
    done = todo = 0
    for anchor, before, after in eds:
        parts = [t for t in (before, after) if t]
        na, counts = cur.count(anchor), [cur.count(t) for t in parts]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                             % (path, na, counts, anchor[:70]))
    for old, new in reps:
        no, nn = cur.count(old), cur.count(new)
        if no == 0 and nn == 1:
            done += 1
        elif no == 1 and nn == 0:
            todo += 1
        else:
            raise SystemExit("REFUSED %s: replaced text found %d times and its new form %d times (wanted 1 and 0, or 0 and 1): %r"
                             % (path, no, nn, old[:70]))
    if done == len(eds) + len(reps):
        return "applied"
    if todo == len(eds) + len(reps):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds) + len(reps)))


def text_checks(texts, new_texts):
    """The ties a compiler cannot check."""
    s, g, c, h, cm, rd = texts[SH], texts[GL], texts[C], texts[H], texts[CM], texts[R]
    lay, cxx = new_texts[LAYOUT], new_texts[CXXH]
    for want, n in (("#define CARD_BINDING_ROWS 6\n", 1), ("#define CARD_BINDING_POOL 7\n", 1), ("#define CARD_BINDING_LAYER_INFO 8\n", 1),
                    ("#define CARD_BINDING_ALPHA 9\n", 1), ("#define CARD_SUN_SELF\n", 1), ("shared uint r128_n[CARD_SUN_WORDS];", 1),
                    ("card_skip_below = max(CARD_SUN_SELF_M, reach);", 1), ("0x01u | CARD_LAMP_MASK", 1),
                    ("atomicAdd(r128_n[7], sun_marked ? 1u : 0u);", 1), ("r25_buf.n[CARD_SUN_FIRST_WORD + gl_LocalInvocationIndex]", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (SH, want, s.count(want), n))
    # the counters 0..7 are each added once
    for i in range(8):
        if s.count("atomicAdd(r128_n[%d]," % i) != 1:
            raise SystemExit("text check: counter word %d is not added exactly once" % i)
    # every r128c line of the shader lies inside #ifdef CARDS (the five other builds keep their SPIR-V)
    for path, txt in ((SH, s), (GL, g)):
        stack = []
        for line in txt.split("\n"):
            st = line.strip()
            if st.startswith("//"):
                continue
            if st.startswith("#if"):
                stack.append(st)
            elif st.startswith("#endif"):
                stack.pop()
            elif st.startswith("#else") and stack:
                stack[-1] = "#else of " + stack[-1]
            elif ("r128" in line or "sun_vis" in line or "card_self_skips" in line or "card_skip_below" in line or "sun_rays" in line) \
                    and not any(x in ("#ifdef CARDS", "#ifdef CARD_SUN_SELF") for x in stack):
                raise SystemExit("text check: %s: an r128c line outside #ifdef CARDS / CARD_SUN_SELF: %r" % (path, line))
    # the C++ counters and the layout agree: 8 words, first word 16, the log prints m[0] to m[7]
    if "#define CARD_SUN_WORDS 8u" not in lay or "#define CARD_SUN_FIRST_WORD 16u" not in lay:
        raise SystemExit("text check: the layout header's counter words changed")
    if "m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7]" not in c:
        raise SystemExit("text check: the r128c log does not print the eight words")
    if "CardSunWords == 8 && CardSunCounterWords == 24" not in cxx:
        raise SystemExit("text check: rt_card_sun.h's word count")
    # the push set of the card build has ten bindings, in the order of rt_cards.glsl's four and the shader's six
    for want in ("{.dstBinding = 6,", "{.dstBinding = 7,", "{.dstBinding = 8,", "{.dstBinding = 9,", "std::array<vk::WriteDescriptorSet, 10> trace_writes",
                 "card_sun.pipeline ? 10u : 6u", "trace_push);"):
        if want not in c:
            raise SystemExit("text check: %s lacks %r" % (C, want))
    if c.count("trace_push);") != 2:
        raise SystemExit("text check: both push sites use trace_push")
    if c.count("eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer,") != 2:
        raise SystemExit("text check: the two pipelines' binding lists")
    # CMake builds and headers
    for want in ("rt_shadow_cards_comp COVERAGE_SKIP=1 CARDS=1", "rt_shadow_half_cards_comp COVERAGE_SKIP=1 HALF=1 CARDS=1"):
        if cm.count(want) != 1:
            raise SystemExit("text check: CMakeLists lacks %r" % want)
    if "RT_SHADOW_CARDS_COMP" not in c or "RT_SHADOW_HALF_CARDS_COMP" not in c:
        raise SystemExit("text check: the generated shader symbols")
    # README row: the numbers it states are the shader's
    row = [l for l in rd.split("\n") if l.startswith("| `BB_RT_CARD_SUN` |")]
    if len(row) != 1 or "3 cm" not in row[0] or "at most 16 candidates" not in row[0] or "reference x 0.6" not in row[0] or "1/255" not in row[0]:
        raise SystemExit("text check: README row and shader constants disagree")
    if "#define CARD_SUN_CAP 16u" not in lay or "#define CARD_SUN_REF 0.6" not in lay or "#define CARD_SUN_SELF_M 0.03" not in lay:
        raise SystemExit("text check: layout constants vs the README row")
    # the live knob, the record order: CardSunNow is called after R25HalfWanted and before the lambda that captures it
    a, b, d = c.find("r25_half = R25HalfWanted(); // bbport (r37_menu-options)"), c.find("const CardSunUse card_sun = CardSunNow(r25_half);"), \
        c.find("sampler = *sampler, card_sun,")
    if not (0 <= a < b < d):
        raise SystemExit("text check: R25HalfWanted, CardSunNow and the capture are out of order")
    if h.count("CardSunWanted()") < 2:
        raise SystemExit("text check: R25Words does not ask CardSunWanted")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R128C_LRT_CUTOUT_PROPS_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        eds, reps = edits_for(path, cur), REPS.get(path, [])
        plan.append((path, eds, reps, raw, eol, cur, state_of(cur, eds, reps, path)))
    states = {p[6] for p in plan} | {new_state(p) for p in NEW}
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[6]) for p in plan) + "; " +
                         ", ".join("%s %s" % (p, new_state(p)) for p in NEW))
    state = states.pop()
    new_texts = {p: NEW[p] for p in NEW}

    def applied_texts():
        out = {}
        for path, eds, reps, raw, eol, cur, _ in plan:
            for old, new in reps:
                cur = cur.replace(old, new)
            for anchor, before, after in eds:
                cur = cur.replace(anchor, before + anchor + after)
            if state_of(cur, eds, reps, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[5] for p in plan}, new_texts)
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts(), new_texts)
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) + len(p[2]) for p in plan), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts, new_texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, reps, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, eds, reps, raw, eol, cur, _ in plan:
                full = os.path.join(ROOT, path)
                tmp = full + ".r128ctmp"
                open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
                os.replace(tmp, full)
                written.append((full, raw))
            for path in NEW:
                full = os.path.join(ROOT, path)
                tmp = full + ".r128ctmp"
                open(tmp, "wb").write(new_bytes(path))
                os.replace(tmp, full)
                written.append((full, None))
        except OSError as err:
            for full, raw in reversed(written):
                if raw is None:
                    os.remove(full)
                else:
                    open(full, "wb").write(raw)
            raise SystemExit("REFUSED: write failed (%s); everything written was put back" % err)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, reps, raw, eol, cur, _ in plan:
        for anchor, before, after in reversed(eds):
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        for old, new in reps:
            cur = cur.replace(new, old, 1)
        if state_of(cur, eds, reps, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, reps, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r128ctmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
