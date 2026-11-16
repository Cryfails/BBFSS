# r86b_glass-visible (reviewed: r86b_glass-visible.fixed.py, 2026-11-15; the draft r86b_glass-visible.py
# is superseded). FEATURE "glass materials" (branch when published: visual/glass-water). A glass
# result the owner can see in the Hunter's Dream house: the lamps (torch, candles, fireplace) put
# small sharp glints on the bottles and jars (the pane pair e30b0480:8a6c7657 BB_RT_GLASS puts into
# the ray traced scene). Context: bbfss-ctx-glass-water-caustics.md, section "2026-11-15 r86b".
#
# How: right after a pane's forward draw (the game draws them after the sun trace and the lamp
# pass), two compute passes ask the ray traced scene's panes (RT_GLASS_MASK 0x10) along camera rays:
# COARSE one ray a 4x4 block, SHADE one ray a pixel (a 2x2 quad above 10 % flagged blocks) near the
# flagged blocks; the normal from neighbouring pane points; normalised Blinn-Phong + Schlick from up
# to 8 lamps of the light grid; one shadow ray (lamp mask 0x04) to the brightest; added to target 0.
# The rules: renderer_vulkan/glass_glint.h; the numbers: host_shaders/glass_glint_layout.h.
#
# New files: host_shaders/glass_glint.comp (COARSE and SHADE builds), glass_glint_layout.h;
# renderer_vulkan/glass_glint.h, vk_glass_glint.h, vk_glass_glint.cpp; tests/test_glass_glint.cpp.
# Edits (each a hook of one or two lines next to its own kind):
#  - rt_glass_light.h: RtGlassCarryOn() = RtGlassLightOn() || BbGlassGlint::On(); vk_rt_shadow.cpp's
#    three r86 carry sites take it (only the condition changes); a static_assert ties LampMask.
#  - vk_rt_shadow.h/.cpp: GlassScene() (pane records, written this frame, the records' camera);
#    the frame stamp and camera written right after `glass_instances = glass_records;`.
#  - vk_rasterizer.h/.cpp: the member, the note of a pane draw, made when Wanted.
#  - vk_rasterizer_effects.cpp: the note in EffectsCaptureDraw's pane admission; AfterGlassDraw
#    next to the blood sheen's AfterDraw (before the effects_wanted return); AddLights right
#    after the lamp draw's point_shadow->OnLightDraw call; ClearLights beside the heat haze's; the
#    frame end beside the blood sheen's.
#  - gpu/CMakeLists.txt (include rule, two shader builds, the test target), build.sh --test, README.
# test_effect_pipelines.cpp gets NO rows: its device has only the push-descriptor extension (no
# ray query, no acceleration structures), so a ray-query pipeline cannot be made there.
#
# Off (BB_GLASS_GLINT unset or 0, or BB_RT_GLASS off): the rasterizer makes no GlassGlint, every
# hook is one null pointer test, RtGlassCarryOn() is RtGlassLightOn() || false (a static bool), so
# RtShadow carries nothing more; two stores a scene write (the stamp) are the only new work. No
# existing shader changes: the two builds are new SPIR-V headers.
#
# Review changes (see the context file): the glint is in the game's lamp units ((n + 8) / 8, not
# / (8 pi): the game's lamp light has no 1/pi, so the draft's glints were pi times too faint); the
# profile row is pinned (a cheap row falls under BB_GPU_PROFILE_ROWS' cut of 30 and the cost run
# would not show it); a menu preview frame counts as "camera"; the CMake include rule and the two
# shader builds sit after r86's own lines and AddLights right after the lamp draw's OnLightDraw
# (the draft's anchors were shared with the r100c/r111 drafts and r107/r107b's inserted texts);
# Decide's ?: conditions in parentheses; README: the exact normal and size rules.
#
# Use: python -I -X utf8 r86b_glass-visible.fixed.py check | apply | revert. Root from R86B_ROOT, else
# <tree>. Each edit is an exact text (old -> new; an insertion's old text is its anchor) found
# exactly once; "applied" = every new text once and every new file present as written here;
# "clean" = every old text once, no new text, no new file; anything else is refused (exit 1,
# nothing written). Line ends are kept (CRLF in the tree; new files are written CRLF).
# apply keeps the touched files in r86b_backup/ next to this script; revert removes the new files.
# Exit: 0 done, 1 refused, 2 usage.
import hashlib, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r86b_backup")
ROOT = os.environ.get("R86B_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
RV = V + "renderer_vulkan/"
HS = V + "host_shaders/"

# The anchors in CMakeLists.txt: r86's own lines (this patch needs r86: RtGlassCarryOn is its carry).
CMAKE_R86_RULE = ("    if (FILENAME MATCHES \"^rt_shadow\\\\.comp$\")\n"
                  "        list(APPEND INCLUDES ${SHADER_SRC}/rt_glass_layout.h ${SHADER_SRC}/rt_glass_light_layout.h)\n"
                  "    endif()\n")
CMAKE_R86_BUILD = "add_host_shader(rt_shadow.comp rt_shadow_half_glass_comp COVERAGE_SKIP=1 HALF=1 GLASS_LIGHT=1)\n"

EDITS = {
    RV + "rt_glass_light.h": [
        ('#include "rt_glass.h"\n',
         '#include "rt_glass.h"\n#include "glass_glint.h" // bbport (r86b_glass-visible)\n'),
        ("inline bool RtGlassLightOn() {\n    return RtGlassLight() != RtGlassLightMode::Off;\n}\n",
         "inline bool RtGlassLightOn() {\n    return RtGlassLight() != RtGlassLightMode::Off;\n}\n\n"
         "// bbport (r86b_glass-visible): RtShadow carries the panes drawn in a frame into the next frame's\n"
         "// scene and builds their waiting captures at the frame end while BB_RT_GLASS_LIGHT or\n"
         "// BB_GLASS_GLINT (glass_glint.h) is on; both off: false, as before.\n"
         "inline bool RtGlassCarryOn() {\n    return RtGlassLightOn() || ::BbGlassGlint::On();\n}\n"),
    ],
    RV + "vk_rt_shadow.h": [
        ("    [[nodiscard]] vk::AccelerationStructureKHR Scene() const noexcept {\n        return tlas;\n    }\n",
         "    [[nodiscard]] vk::AccelerationStructureKHR Scene() const noexcept {\n        return tlas;\n    }\n"
         "    // bbport (r86b_glass-visible): BB_GLASS_GLINT: the pane records of the TLAS last written,\n"
         "    // whether PrepareScene wrote them this frame, and the camera (world to view, 3x4 rows) they\n"
         "    // were placed with (the TLAS's view space)\n"
         "    struct GlassSceneView {\n        u32 instances = 0;\n        bool this_frame = false;\n"
         "        std::array<float, 12> view{};\n    };\n"
         "    [[nodiscard]] GlassSceneView GlassScene() const noexcept {\n"
         "        return {glass_instances, glass_frame == frame, glass_view};\n    }\n"),
        ("    std::array<u32, RtGlassLightWords> r86_last{};\n",
         "    std::array<u32, RtGlassLightWords> r86_last{};\n"
         "    // bbport (r86b_glass-visible): the frame whose PrepareScene last wrote the TLAS records, and\n"
         "    // its camera (GlassScene)\n"
         "    u64 glass_frame = 0;\n    std::array<float, 12> glass_view{};\n"),
    ],
    RV + "vk_rt_shadow.cpp": [
        ("static_assert(CardLampMask == CARD_LAMP_MASK && (CardLampMask & (ShadowMask | CameraMask | LampMask)) == 0);\n",
         "static_assert(CardLampMask == CARD_LAMP_MASK && (CardLampMask & (ShadowMask | CameraMask | LampMask)) == 0);\n"
         "static_assert(LampMask == GLASS_GLINT_LAMP_MASK); // bbport (r86b_glass-visible): its shadow rays\n"),
        ("        if (RtGlassLightOn()) { // bbport (r86_glass-light-stage2a): carried into the next frame\n"
         "            glass_drawn.push_back(entry_key);\n",
         "        if (RtGlassCarryOn()) { // bbport (r86_glass-light-stage2a, r86b): carried into the next frame\n"
         "            glass_drawn.push_back(entry_key);\n"),
        ("    glass_instances = glass_records; // bbport (r86_glass-light-stage2a)\n",
         "    glass_instances = glass_records; // bbport (r86_glass-light-stage2a)\n"
         "    glass_frame = frame;             // bbport (r86b_glass-visible): GlassScene\n"
         "    glass_view = camera.view;\n"),
        ("    if (RtGlassLightOn() && need_scene &&\n        std::ranges::any_of(builds,",
         "    if (RtGlassCarryOn() && need_scene && // bbport (r86b_glass-visible): or BB_GLASS_GLINT on\n"
         "        std::ranges::any_of(builds,"),
        ("    if (RtGlassLightOn()) {\n        glass_carry.swap(glass_drawn);\n",
         "    if (RtGlassCarryOn()) { // bbport (r86b_glass-visible): or BB_GLASS_GLINT on\n"
         "        glass_carry.swap(glass_drawn);\n"),
    ],
    RV + "vk_rasterizer.h": [
        ('#include "video_core/renderer_vulkan/vk_blood_sheen.h" // bbport (r100_blood-sheen)\n',
         '#include "video_core/renderer_vulkan/vk_blood_sheen.h" // bbport (r100_blood-sheen)\n'
         '#include "video_core/renderer_vulkan/vk_glass_glint.h" // bbport (r86b_glass-visible)\n'),
        ("    std::unique_ptr<BloodSheen> blood_sheen;\n",
         "    std::unique_ptr<BloodSheen> blood_sheen;\n"
         "    /// bbport (r86b_glass-visible): made only with BB_GLASS_GLINT and BB_RT_GLASS on\n"
         "    /// (GlassGlint::Wanted), else null: its hooks are null pointer tests. glint_pending: the\n"
         "    /// pipeline of the pane draw EffectsCaptureDraw admitted, for its EffectsAfterDraw.\n"
         "    std::unique_ptr<GlassGlint> glass_glint;\n"
         "    const GraphicsPipeline* glint_pending = nullptr;\n"),
    ],
    RV + "vk_rasterizer.cpp": [
        ("    if (BloodSheen::Wanted()) {\n"
         "        blood_sheen = std::make_unique<BloodSheen>(instance, scheduler, texture_cache, runtime,\n"
         "                                                   *scene_targets, *camera_motion);\n    }\n",
         "    if (BloodSheen::Wanted()) {\n"
         "        blood_sheen = std::make_unique<BloodSheen>(instance, scheduler, texture_cache, runtime,\n"
         "                                                   *scene_targets, *camera_motion);\n    }\n"
         "    // bbport (r86b_glass-visible): BB_GLASS_GLINT and BB_RT_GLASS on only (GlassGlint::Wanted,\n"
         "    // read once); otherwise no GlassGlint is made and nothing of it runs.\n"
         "    if (GlassGlint::Wanted()) {\n"
         "        glass_glint = std::make_unique<GlassGlint>(instance, scheduler, texture_cache, runtime,\n"
         "                                                   *scene_targets, *camera_motion, *rt_shadow);\n"
         "    }\n"),
    ],
    RV + "vk_rasterizer_effects.cpp": [
        ("            draw.glass = true;\n            draw.camera_pass = true;\n"
         "            draw.solid = true;\n            draw.alpha = false;\n",
         "            draw.glass = true;\n            draw.camera_pass = true;\n"
         "            draw.solid = true;\n            draw.alpha = false;\n"
         "            glint_pending = glass_glint ? pipeline : nullptr; // bbport (r86b_glass-visible)\n"),
        ("    if (blood_sheen) { // bbport (r100_blood-sheen): the glint right after the pool's draw\n"
         "        blood_sheen->AfterDraw();\n    }\n",
         "    if (blood_sheen) { // bbport (r100_blood-sheen): the glint right after the pool's draw\n"
         "        blood_sheen->AfterDraw();\n    }\n"
         "    if (glass_glint) { // bbport (r86b_glass-visible): right after a pane's draw it noted\n"
         "        if (glint_pending == pipeline) {\n"
         "            glass_glint->AfterGlassDraw(cb_descs[0].first, db_desc.first, upscaler->Jitter(),\n"
         "                                        point_shadow->Pending());\n"
         "        }\n"
         "        glint_pending = nullptr;\n    }\n"),
        ("                                           .mrt_mask = pipeline->GetGraphicsKey().mrt_mask});\n",
         "                                           .mrt_mask = pipeline->GetGraphicsKey().mrt_mask});\n"
         "                if (glass_glint) { // bbport (r86b_glass-visible): the lamps of its glints (as drawn)\n"
         "                    glass_glint->AddLights(flickered ? flickered : reinterpret_cast<const u32*>(lights),\n"
         "                                           tile_lights);\n"
         "                }\n"),
        ("        if (heat_haze) { // bbport (r97_heat-haze): the lamps of the last G-buffer pass only\n"
         "            heat_haze->ClearLights();\n        }\n",
         "        if (heat_haze) { // bbport (r97_heat-haze): the lamps of the last G-buffer pass only\n"
         "            heat_haze->ClearLights();\n        }\n"
         "        if (glass_glint) { // bbport (r86b_glass-visible): the same rule\n"
         "            glass_glint->ClearLights();\n        }\n"),
        ("    if (blood_sheen) { // bbport (r100_blood-sheen)\n        blood_sheen->OnFrameEnd();\n    }\n",
         "    if (blood_sheen) { // bbport (r100_blood-sheen)\n        blood_sheen->OnFrameEnd();\n    }\n"
         "    if (glass_glint) { // bbport (r86b_glass-visible); a noted pane draw never made is forgotten\n"
         "        glass_glint->OnFrameEnd();\n        glint_pending = nullptr;\n    }\n"),
    ],
    "engine/gpu/CMakeLists.txt": [
        (CMAKE_R86_RULE,
         CMAKE_R86_RULE +
         "    # bbport (r86b_glass-visible): the glass glint's numbers and the panes' mask, shared with C++\n"
         "    # (glass_glint.h)\n"
         "    if (FILENAME MATCHES \"^glass_glint\")\n"
         "        list(APPEND INCLUDES ${SHADER_SRC}/glass_glint_layout.h ${SHADER_SRC}/rt_glass_layout.h)\n"
         "    endif()\n"),
        (CMAKE_R86_BUILD,
         CMAKE_R86_BUILD +
         "# bbport (r86b_glass-visible): BB_GLASS_GLINT only: the glass glint's two passes\n"
         "# (renderer_vulkan/vk_glass_glint.cpp)\n"
         "add_host_shader(glass_glint.comp glass_glint_coarse_comp COARSE=1)\n"
         "add_host_shader(glass_glint.comp glass_glint_shade_comp SHADE=1)\n"),
        ("# bbport (r54_leaf-stage2): the card UVs' pure parts (renderer_vulkan/rt_card_uv.h)\n",
         "# bbport (r86b_glass-visible): the glass glint's knobs, lamps, gate and numbers (glass_glint.h);\n"
         "# also built and run by engine/build.sh --test.\n"
         "add_executable(glass-glint-test EXCLUDE_FROM_ALL ../tests/test_glass_glint.cpp)\n"
         "target_compile_options(glass-glint-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
         "target_include_directories(glass-glint-test PRIVATE ..)\n"
         "# bbport (r54_leaf-stage2): the card UVs' pure parts (renderer_vulkan/rt_card_uv.h)\n"),
    ],
    "engine/build.sh": [
        ("    out/rt-glass-test\n",
         "    out/rt-glass-test\n"
         "    # bbport (r86b_glass-visible): the glass glint's knobs, lamps, gate and numbers\n"
         "    \"${CXX:-clang++}\" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_glass_glint.cpp -o out/glass-glint-test\n"
         "    out/glass-glint-test\n"),
    ],
    "README.md": [],  # readme_edit: the two rows after the BB_RT_GLASS_LIGHT row
}

README_ROW_PREFIX = "| `BB_RT_GLASS_LIGHT` | "
README_ROWS = (
    "| `BB_GLASS_GLINT` | Needs `BB_RT_GLASS` on and the ray traced sun's scene (ray tracing on with the ray traced sun). "
    "Glints of the lamps on glass: the window panes and glass `BB_RT_GLASS` puts into the ray traced scene (in the Hunter's Dream "
    "house the bottles and jars on the shelves, pair `e30b0480:8a6c7657`) catch small sharp highlights of the torch, the candles "
    "and the fireplace. `1`: on, strength 1; a number above 0 is the strength, put into 0.25 to 4; `show`: strength 1 and a test "
    "view, half of a pixel's colour (as bright as the pixel, at least 0.1) cyan where a pane lies in front of the depth, blue where "
    "the camera ray meets a pane only behind it, magenta where the glint's largest channel is above 0.02. Unset, empty, `0`, a "
    "negative number or other text: off, and nothing of it is made. On, the panes drawn in a frame are carried into the next "
    "frame's ray traced scene and their waiting captures built at the frame end, as with `BB_RT_GLASS_LIGHT`. Right after a pane's "
    "forward draw, at most 2 times a frame and once a depth, two passes run when the ray traced scene was written this frame, "
    "holds a pane and has this draw's camera, a lamp of the last G-buffer pass's light grid can shine (up to 8, those that show "
    "most, as drawn, with `BB_LAMP_FLICKER`), no lamps-apart batch is open (the passes read the camera depth; they are skipped, "
    "the batch is not ended) and the draw's target 0 is a writable RGBA16F image of its depth's size (not the reduced scene), "
    "at least 16 pixels each way; "
    "otherwise the draw is counted by the first reason that holds (no pane, camera: another camera or a menu's preview frame, "
    "no lamps, lamps open, shape, cap). The "
    "first pass: one camera ray a 4x4 block of pixels that meets only the panes, up to the depth's distance + 2 cm + 0.2 %; a "
    "hit flags the block. The second, where a flagged block lies under a tile or its border of one pixel (one ray a 2x2 quad when "
    "more than 10 % of the blocks are flagged; each pixel of a quad is still tested against its own depth): one such ray a pixel; "
    "the normal from the pane points of the neighbouring units (pixels, or quads), central differences 2 units apart, or 1 "
    "unit to one side when the other neighbour is left out (one whose distance differs from the centre's by more than "
    "3 cm + 1 %; none on an axis: no glint), turned toward the camera (on a faceted mesh the normal is the facet's except "
    "within a unit of its edges); each lamp gives Blinn-Phong with the exponent `BB_GLASS_GLINT_SHARP` and "
    "(n + 8) / 8 (the game's lamp units: its lamp light has no 1/pi), Schlick from 0.04, the lamp's colour x "
    "(1 - d / reach)^2 x the cosine at the pane; where the brightest "
    "lamp's term x strength is above 1/255, one shadow ray toward it (the lamps' instance mask, which the panes are not in, from "
    "3 cm to 10 cm short of the lamp) removes it when it meets something; the sum x strength, each channel put into 0 to 8, is "
    "added to the scene colour. Untinted: no glass colour yet. Glass that writes no depth is found in front of what lies behind "
    "it; glass behind a wall is left out. These environment variables are read once when the game starts; they are for testing, "
    "no ini key yet. The log (lines starting `Ray tracing glass glint (r86b)`): the knobs once, the first pass, and every 600 "
    "frames the pane draws (draws), the passes and the frame of the first, the skips by reason and, a pass (read back 15 passes late), "
    "the blocks flagged of all, the pixels on glass, those whose pane lay only behind the depth (the test view only), the glint "
    "pixels, the shadow rays that met something of all, the largest channel added and the lamps. Cost: an estimate of 0.03 to 0.1 "
    "ms a pass at 1920x1080 internal with glass on a small part of the screen (one ray a 16 pixels everywhere, about 1.6 rays and "
    "up to one shadow ray a pixel near glass); the quad mode keeps a screen full of glass to about a quarter of the pixel rays; "
    "not measured; it is the `Lighting: glass glint` row of `BB_GPU_PROFILE=1` (pinned: shown however small). Memory: a 4-byte "
    "word a 4x4 block (518 KB at "
    "1920x1080 internal, 2.1 MB at 3840x2160) and 5632 bytes of counters and lamps | off |\n"
    "| `BB_GLASS_GLINT_SHARP` | Only with `BB_GLASS_GLINT` on: the glints' Blinn-Phong exponent, a whole number put into 16 to "
    "4096 (higher: smaller, sharper glints; the normalisation keeps their total light). Unset or empty: 256; other text: 256, said "
    "once in the log | 256 |\n"
)

# The new files, as written (LF here; written CRLF, as the tree's files).
NEW = {
    'engine/gpu/shadps4/video_core/host_shaders/glass_glint_layout.h': (
        '// SPDX-License-Identifier: GPL-3.0-or-later\n'
        "// bbport (r86b_glass-visible): the glass glint's numbers, shared by host_shaders/glass_glint.comp\n"
        '// (its COARSE and SHADE builds) and renderer_vulkan/glass_glint.h (which ties them to its C++\n'
        '// names with static_asserts and the test). Plain #define lines only: GLSL and C++ both read this\n'
        '// file.\n'
        '#ifndef GLASS_GLINT_LAYOUT_H\n'
        '#define GLASS_GLINT_LAYOUT_H\n'
        '\n'
        '// One workgroup: 8x8 threads. COARSE: a thread a block of GLASS_GLINT_BLOCK x GLASS_GLINT_BLOCK\n'
        '// pixels; SHADE: a thread a pixel (or a 2x2 quad, see GLASS_GLINT_QUAD_PERCENT).\n'
        '#define GLASS_GLINT_GROUP 8\n'
        '#define GLASS_GLINT_BLOCK 4\n'
        '\n'
        '// Push word info.w.\n'
        '#define GLASS_GLINT_FLAG_SHOW 1u // the test view (BB_GLASS_GLINT=show)\n'
        '\n'
        "// The shadow ray to a lamp traces the lamps' instance mask (RtShadow's LampMask, tied there by a\n"
        '// static_assert); the panes are under RT_GLASS_MASK alone, so a pane never shadows its own glint.\n'
        '#define GLASS_GLINT_LAMP_MASK 0x04u\n'
        '\n'
        '// The counters buffer: GLASS_GLINT_SLOTS slots of GLASS_GLINT_SLOT_WORDS counter words (one slot a\n'
        '// pass, in turn), then GLASS_GLINT_SLOTS data blocks of GLASS_GLINT_DATA_WORDS words (the same\n'
        "// slot's): word GLASS_GLINT_DATA_COUNT the lamp count, from GLASS_GLINT_DATA_LAMPS\n"
        '// GLASS_GLINT_LAMP_WORDS words a lamp: view x, y, z, reach (m), colour r, g, b, 0.\n'
        '#define GLASS_GLINT_SLOTS 16u\n'
        '#define GLASS_GLINT_SLOT_WORDS 16u\n'
        '#define GLASS_GLINT_MAX_LAMPS 8u\n'
        '#define GLASS_GLINT_LAMP_WORDS 8u\n'
        '#define GLASS_GLINT_DATA_COUNT 0u\n'
        '#define GLASS_GLINT_DATA_LAMPS 8u\n'
        '#define GLASS_GLINT_DATA_WORDS 72u\n'
        '\n'
        '// Counter words of a slot. COARSE: 0 blocks traced, 1 blocks whose centre ray meets a pane in\n'
        '// front of the depth (within GLASS_GLINT_TOL_*), 2 blocks whose ray meets a pane only behind it\n'
        '// (the test view only). SHADE: 3 pixels on a pane in front of the depth, 4 pixels whose ray meets\n'
        "// a pane only behind the depth (the test view only), 5 pixels whose glint's largest channel is\n"
        '// above GLASS_GLINT_GLINT_LEVEL, 6 shadow rays, 7 of them that met something, 8 the largest added\n'
        '// channel (float bits; atomicMax of non-negative floats), 9 workgroups that ran, 10 of them in the\n'
        '// quad mode, 11 pane points without a normal (no neighbour on the same surface).\n'
        '#define GLASS_GLINT_W_BLOCKS 0u\n'
        '#define GLASS_GLINT_W_FLAGGED 1u\n'
        '#define GLASS_GLINT_W_BEHIND 2u\n'
        '#define GLASS_GLINT_W_GLASS 3u\n'
        '#define GLASS_GLINT_W_REJECTED 4u\n'
        '#define GLASS_GLINT_W_GLINT 5u\n'
        '#define GLASS_GLINT_W_SHADOW_RAYS 6u\n'
        '#define GLASS_GLINT_W_SHADOWED 7u\n'
        '#define GLASS_GLINT_W_MAX_ADD 8u\n'
        '#define GLASS_GLINT_W_TILES 9u\n'
        '#define GLASS_GLINT_W_QUAD_TILES 10u\n'
        '#define GLASS_GLINT_W_NO_NORMAL 11u\n'
        '#define GLASS_GLINT_W_COUNT 12u\n'
        '\n'
        "// A pane is in front of the depth when its distance t along the camera ray is at most the depth's\n"
        '// distance d + GLASS_GLINT_TOL_ABS (m) + GLASS_GLINT_TOL_REL x d (a pane that writes its depth\n'
        '// lies on it). The sky (depth 1) is GLASS_GLINT_FAR away.\n'
        '#define GLASS_GLINT_TOL_ABS 0.02\n'
        '#define GLASS_GLINT_TOL_REL 0.002\n'
        '#define GLASS_GLINT_FAR 1000.0\n'
        '// The normal: central differences of the pane points of the neighbours one unit (a pixel, or a\n'
        "// quad) to each side; a neighbour counts when its t differs from the centre's by at most\n"
        '// GLASS_GLINT_NEAR_ABS (m) + GLASS_GLINT_NEAR_REL x t (else one side; neither: no normal).\n'
        '#define GLASS_GLINT_NEAR_ABS 0.03\n'
        '#define GLASS_GLINT_NEAR_REL 0.01\n'
        "// Shading: Blinn-Phong with (n + 8) / 8 (the game's lamp units: its lamp light is colour x falloff\n"
        "// x N.L with no 1/pi, so the BRDF's 1/pi is left out too), Schlick from GLASS_GLINT_F0, each channel\n"
        '// of the sum put into 0 to GLASS_GLINT_ADD_MAX. One shadow ray, to the lamp with the largest term,\n'
        '// when that term x strength is above GLASS_GLINT_SHADOW_LEVEL: from GLASS_GLINT_SHADOW_TMIN (m) to the\n'
        "// lamp's distance less GLASS_GLINT_LAMP_STOP (m).\n"
        '#define GLASS_GLINT_F0 0.04\n'
        '#define GLASS_GLINT_ADD_MAX 8.0\n'
        '#define GLASS_GLINT_SHADOW_LEVEL (1.0 / 255.0)\n'
        '#define GLASS_GLINT_SHADOW_TMIN 0.03\n'
        '#define GLASS_GLINT_LAMP_STOP 0.1\n'
        '#define GLASS_GLINT_GLINT_LEVEL 0.02\n'
        '// More than this percentage of the blocks on a pane: SHADE traces one ray a 2x2 quad (the cost\n'
        '// cap of a screen full of glass); each pixel of a quad still takes its own depth test.\n'
        '#define GLASS_GLINT_QUAD_PERCENT 10u\n'
        '\n'
        '#endif\n'
    ),
    'engine/gpu/shadps4/video_core/host_shaders/glass_glint.comp': (
        '#version 460\n'
        '// SPDX-License-Identifier: GPL-3.0-or-later\n'
        "// bbport (r86b_glass-visible): the lamps' glints on the window panes and the glass (bottles, jars)\n"
        '// that BB_RT_GLASS puts into the ray traced scene under RT_GLASS_MASK (GlassGlint, right after a\n'
        "// pane's forward draw; renderer_vulkan/glass_glint.h has the rules, glass_glint_layout.h the\n"
        '// numbers). Two builds:\n'
        "//  - COARSE: a thread a block of 4x4 pixels: one camera ray through the block's centre pixel that\n"
        "//    meets only panes, up to the depth's distance + 2 cm + 0.2 %. A hit flags the block (1); in the\n"
        '//    test view a second ray to the far distance flags a block whose pane lies only behind the depth\n'
        '//    (2).\n'
        '//  - SHADE: a workgroup an 8x8 tile of pixels (or, when more than 10 % of the blocks are flagged,\n'
        '//    of 2x2 quads: a 16x16 tile) runs only when a block under the tile or its one-unit border is\n'
        '//    flagged. One pane ray a unit (pixel or quad) of the tile and its border; the normal from the\n'
        '//    pane points of the neighbours (central differences 2 units apart, a neighbour farther from the\n'
        "//    centre's t than 3 cm + 1 % left out), turned toward the camera; each lamp of the pass a\n"
        "//    normalised Blinn-Phong term with Schlick's Fresnel and the lamp's falloff (1 - d / reach)^2;\n"
        '//    one shadow ray (lamp mask) to the brightest lamp when its term counts; the sum x strength, put\n'
        '//    into 0 to 8 a channel, added to the scene colour. No tint: untinted specular.\n'
        "// The ray traced scene is in the view space of CameraMotion's pass camera (the TLAS's instance\n"
        '// transform); the camera is at its origin. Ray direction from the pixel as rt_card_view.comp\n'
        '// reconstructs it: ndc +y down, the jitter taken out; view z = proj.w / (depth - proj.z).\n'
        '#extension GL_EXT_ray_query : require\n'
        '#extension GL_EXT_samplerless_texture_functions : require\n'
        '#extension GL_GOOGLE_include_directive : require\n'
        '\n'
        '#include "rt_glass_layout.h"\n'
        '#include "glass_glint_layout.h"\n'
        '\n'
        '#if defined(COARSE) == defined(SHADE)\n'
        '#error "glass_glint.comp: build it with exactly one of COARSE and SHADE"\n'
        '#endif\n'
        '\n'
        'layout(local_size_x = GLASS_GLINT_GROUP, local_size_y = GLASS_GLINT_GROUP) in;\n'
        '\n'
        'layout(set = 0, binding = 0) uniform accelerationStructureEXT scene;\n'
        "layout(set = 0, binding = 1) uniform texture2D depth_tex; // the pane draw's depth, 0..1\n"
        "layout(set = 0, binding = 2, rgba16f) uniform image2D scene_img; // the pane draw's target 0\n"
        'layout(set = 0, binding = 3, std430) buffer Work {\n'
        '    uint block_flags[]; // a word a block, row by row: 0 none, 1 a pane in front, 2 only behind\n'
        '};\n'
        'layout(set = 0, binding = 4, std430) buffer Counters {\n'
        '    uint counters[]; // GLASS_GLINT_SLOTS counter slots, then their data blocks\n'
        '};\n'
        '\n'
        'layout(push_constant) uniform Push {\n'
        "    vec4 proj;   // CameraMotion's: x scale, y scale, z scale, z offset\n"
        '    vec4 frame;  // width, height (render pixels), jitter x, y (pixels)\n'
        '    uvec4 info;  // blocks across, blocks down, slot, flags\n'
        "    vec4 params; // strength, exponent, (exponent + 8) / 8 (the game's lamp units), 0\n"
        '} pc;\n'
        '\n'
        'uint SlotBase() {\n'
        '    return pc.info.z * GLASS_GLINT_SLOT_WORDS;\n'
        '}\n'
        '\n'
        'uint DataBase() {\n'
        '    return GLASS_GLINT_SLOTS * GLASS_GLINT_SLOT_WORDS + pc.info.z * GLASS_GLINT_DATA_WORDS;\n'
        '}\n'
        '\n'
        'ivec2 Size() {\n'
        '    return ivec2(pc.frame.xy);\n'
        '}\n'
        '\n'
        'bool Show() {\n'
        '    return (pc.info.w & GLASS_GLINT_FLAG_SHOW) != 0u;\n'
        '}\n'
        '\n'
        "// The unit camera ray through `pos` (render pixels, continuous: a pixel's centre is + 0.5).\n"
        'vec3 RayDir(vec2 pos) {\n'
        '    const vec2 ndc = (pos - pc.frame.zw) / pc.frame.xy * 2.0 - 1.0;\n'
        '    // view z = proj.w / (depth - proj.z) with depth - proj.z below 0: z has the sign of -proj.w\n'
        '    const float z_sign = pc.proj.w < 0.0 ? 1.0 : -1.0;\n'
        '    return normalize(vec3(ndc.x / pc.proj.x, ndc.y / pc.proj.y, 1.0) * z_sign);\n'
        '}\n'
        '\n'
        '// The distance from the camera to the point the depth holds at pixel `p`; the sky is FAR away.\n'
        'float DepthT(ivec2 p) {\n'
        '    const float depth = texelFetch(depth_tex, p, 0).r;\n'
        '    if (!(depth < 1.0)) {\n'
        '        return float(GLASS_GLINT_FAR);\n'
        '    }\n'
        '    const float z = pc.proj.w / min(depth - pc.proj.z, -1e-8);\n'
        '    const vec2 ndc = (vec2(p) + 0.5 - pc.frame.zw) / pc.frame.xy * 2.0 - 1.0;\n'
        '    return length(vec3(ndc.x * z / pc.proj.x, ndc.y * z / pc.proj.y, z));\n'
        '}\n'
        '\n'
        '// How far a pane may lie and still be in front of the depth at distance `t`.\n'
        'float Reach(float t) {\n'
        '    return t + float(GLASS_GLINT_TOL_ABS) + float(GLASS_GLINT_TOL_REL) * t;\n'
        '}\n'
        '\n'
        '// The nearest pane on the camera ray along `dir` up to `tmax` (`any`: the first found), or -1.\n'
        'float PaneT(vec3 dir, float tmax, bool any) {\n'
        '    rayQueryEXT query;\n'
        '    rayQueryInitializeEXT(query, scene,\n'
        '                          gl_RayFlagsOpaqueEXT | (any ? gl_RayFlagsTerminateOnFirstHitEXT : 0u),\n'
        '                          RT_GLASS_MASK, vec3(0.0), 0.0, dir, tmax);\n'
        '    while (rayQueryProceedEXT(query)) {\n'
        '    }\n'
        '    return rayQueryGetIntersectionTypeEXT(query, true) == gl_RayQueryCommittedIntersectionTriangleEXT\n'
        '               ? rayQueryGetIntersectionTEXT(query, true)\n'
        '               : -1.0;\n'
        '}\n'
        '\n'
        '#ifdef COARSE\n'
        'shared uint group_blocks, group_flagged, group_behind;\n'
        '\n'
        'void main() {\n'
        '    if (gl_LocalInvocationIndex == 0u) {\n'
        '        group_blocks = 0u;\n'
        '        group_flagged = 0u;\n'
        '        group_behind = 0u;\n'
        '    }\n'
        '    barrier();\n'
        '    const uvec2 b = gl_GlobalInvocationID.xy;\n'
        '    if (b.x < pc.info.x && b.y < pc.info.y) {\n'
        '        const ivec2 p = min(ivec2(b) * GLASS_GLINT_BLOCK + GLASS_GLINT_BLOCK / 2, Size() - 1);\n'
        '        const vec3 dir = RayDir(vec2(p) + 0.5);\n'
        '        uint flag = 0u;\n'
        '        if (PaneT(dir, Reach(DepthT(p)), true) >= 0.0) {\n'
        '            flag = 1u;\n'
        '        } else if (Show() && PaneT(dir, float(GLASS_GLINT_FAR), true) >= 0.0) {\n'
        '            flag = 2u;\n'
        '        }\n'
        '        block_flags[b.y * pc.info.x + b.x] = flag;\n'
        '        atomicAdd(group_blocks, 1u);\n'
        '        if (flag == 1u) {\n'
        '            atomicAdd(group_flagged, 1u);\n'
        '        } else if (flag == 2u) {\n'
        '            atomicAdd(group_behind, 1u);\n'
        '        }\n'
        '    }\n'
        '    barrier();\n'
        '    if (gl_LocalInvocationIndex == 0u && group_blocks != 0u) {\n'
        '        const uint base = SlotBase();\n'
        '        atomicAdd(counters[base + GLASS_GLINT_W_BLOCKS], group_blocks);\n'
        '        if (group_flagged != 0u) {\n'
        '            atomicAdd(counters[base + GLASS_GLINT_W_FLAGGED], group_flagged);\n'
        '        }\n'
        '        if (group_behind != 0u) {\n'
        '            atomicAdd(counters[base + GLASS_GLINT_W_BEHIND], group_behind);\n'
        '        }\n'
        '    }\n'
        '}\n'
        '#endif\n'
        '\n'
        '#ifdef SHADE\n'
        "const uint GRID = uint(GLASS_GLINT_GROUP) + 2u; // the tile's units and a border of one\n"
        'const uint CELLS = GRID * GRID;\n'
        'const uint THREADS = uint(GLASS_GLINT_GROUP * GLASS_GLINT_GROUP);\n'
        'const uint SPAN = 6u; // blocks across the widest unit range (20 px in the quad mode)\n'
        '\n'
        "// A unit's pane point (view space) and its t; w below 0: no pane in front of the depth.\n"
        'shared vec4 group_hit[CELLS];\n'
        'shared vec4 group_lamp[GLASS_GLINT_MAX_LAMPS * 2u]; // position, reach | colour, 0\n'
        'shared uint group_live;\n'
        'shared uint group_count[GLASS_GLINT_W_COUNT];\n'
        '\n'
        'bool Near(vec4 a, vec4 centre) {\n'
        '    return a.w >= 0.0 &&\n'
        '           abs(a.w - centre.w) <= float(GLASS_GLINT_NEAR_ABS) + float(GLASS_GLINT_NEAR_REL) * centre.w;\n'
        '}\n'
        '\n'
        '// The difference across the centre on one axis: both neighbours, else one side, else none.\n'
        'bool Across(vec4 lo, vec4 hi, vec4 centre, out vec3 d) {\n'
        '    const bool l = Near(lo, centre), h = Near(hi, centre);\n'
        '    d = l && h ? hi.xyz - lo.xyz : h ? hi.xyz - centre.xyz : l ? centre.xyz - lo.xyz : vec3(0.0);\n'
        '    return l || h;\n'
        '}\n'
        '\n'
        'bool GridNormal(uint c, vec4 centre, out vec3 n) {\n'
        '    n = vec3(0.0);\n'
        '    vec3 dx, dy;\n'
        '    if (!Across(group_hit[c - 1u], group_hit[c + 1u], centre, dx) ||\n'
        '        !Across(group_hit[c - GRID], group_hit[c + GRID], centre, dy)) {\n'
        '        return false;\n'
        '    }\n'
        '    const vec3 m = cross(dx, dy);\n'
        '    const float len = length(m);\n'
        '    if (!(len > 1e-12)) {\n'
        '        return false;\n'
        '    }\n'
        '    n = m / len;\n'
        '    if (dot(n, centre.xyz) > 0.0) { // toward the camera at the origin\n'
        '        n = -n;\n'
        '    }\n'
        '    return true;\n'
        '}\n'
        '\n'
        "// The glint at pane point `p` with normal `n` from the pass's lamps (x strength).\n"
        'vec3 Glint(vec3 p, vec3 n, uint lamp_count, inout uint shadow_rays, inout uint shadowed) {\n'
        '    const vec3 v = normalize(-p);\n'
        '    vec3 sum = vec3(0.0), best_term = vec3(0.0), best_l = vec3(0.0);\n'
        '    float best = 0.0, best_d = 0.0;\n'
        '    for (uint k = 0u; k < lamp_count; ++k) {\n'
        '        const vec4 lamp = group_lamp[2u * k];\n'
        '        const vec3 to = lamp.xyz - p;\n'
        '        const float d = length(to);\n'
        '        if (!(d < lamp.w) || d < 1e-4) {\n'
        '            continue;\n'
        '        }\n'
        '        const vec3 l = to / d;\n'
        '        const float nl = dot(n, l);\n'
        '        if (!(nl > 0.0)) {\n'
        '            continue;\n'
        '        }\n'
        '        const vec3 h = normalize(l + v);\n'
        '        const float nh = max(dot(n, h), 0.0);\n'
        '        const float vh = clamp(dot(v, h), 0.0, 1.0);\n'
        '        const float fresnel =\n'
        '            float(GLASS_GLINT_F0) + (1.0 - float(GLASS_GLINT_F0)) * pow(1.0 - vh, 5.0);\n'
        '        const float fall = 1.0 - d / lamp.w;\n'
        '        const vec3 term = group_lamp[2u * k + 1u].rgb *\n'
        '                          (fall * fall * nl * fresnel * pc.params.z * pow(nh, pc.params.y));\n'
        '        sum += term;\n'
        '        const float m = max(term.r, max(term.g, term.b));\n'
        '        if (m > best) {\n'
        '            best = m;\n'
        '            best_term = term;\n'
        '            best_l = l;\n'
        '            best_d = d;\n'
        '        }\n'
        '    }\n'
        '    if (best * pc.params.x > float(GLASS_GLINT_SHADOW_LEVEL)) {\n'
        '        ++shadow_rays;\n'
        '        rayQueryEXT query;\n'
        '        rayQueryInitializeEXT(query, scene,\n'
        '                              gl_RayFlagsOpaqueEXT | gl_RayFlagsTerminateOnFirstHitEXT,\n'
        '                              GLASS_GLINT_LAMP_MASK, p, float(GLASS_GLINT_SHADOW_TMIN), best_l,\n'
        '                              max(best_d - float(GLASS_GLINT_LAMP_STOP),\n'
        '                                  float(GLASS_GLINT_SHADOW_TMIN) * 2.0));\n'
        '        while (rayQueryProceedEXT(query)) {\n'
        '        }\n'
        '        if (rayQueryGetIntersectionTypeEXT(query, true) != gl_RayQueryCommittedIntersectionNoneEXT) {\n'
        '            ++shadowed;\n'
        '            sum -= best_term;\n'
        '        }\n'
        '    }\n'
        '    const vec3 add = sum * pc.params.x;\n'
        '    if (any(isnan(add)) || any(isinf(add))) {\n'
        '        return vec3(0.0);\n'
        '    }\n'
        '    return clamp(add, vec3(0.0), vec3(float(GLASS_GLINT_ADD_MAX)));\n'
        '}\n'
        '\n'
        'void main() {\n'
        '    const uint lid = gl_LocalInvocationIndex;\n'
        '    const uint blocks = pc.info.x * pc.info.y;\n'
        "    // COARSE's count (a barrier lies between the two dispatches): the same for every group\n"
        '    const bool quads =\n'
        '        counters[SlotBase() + GLASS_GLINT_W_FLAGGED] * 100u > blocks * GLASS_GLINT_QUAD_PERCENT;\n'
        '    const int scale = quads ? 2 : 1;\n'
        '    const ivec2 size = Size();\n'
        '    const ivec2 tile0 = ivec2(gl_WorkGroupID.xy) * (GLASS_GLINT_GROUP * scale);\n'
        '    // The dispatch is sized for 8x8 pixel tiles: in the quad mode its far half has none.\n'
        '    if (tile0.x >= size.x || tile0.y >= size.y) {\n'
        '        return; // the whole group: before any barrier\n'
        '    }\n'
        '    if (lid == 0u) {\n'
        '        group_live = 0u;\n'
        '    }\n'
        '    if (lid < GLASS_GLINT_W_COUNT) {\n'
        '        group_count[lid] = 0u;\n'
        '    }\n'
        '    barrier();\n'
        '    // Live: a block under the units of the tile and its border is flagged (1; also 2 in the test\n'
        '    // view, for its blue).\n'
        '    const ivec2 lo = max(tile0 - scale, ivec2(0)) / GLASS_GLINT_BLOCK;\n'
        '    const ivec2 hi =\n'
        '        (min(tile0 + (GLASS_GLINT_GROUP + 1) * scale, size) - 1) / GLASS_GLINT_BLOCK;\n'
        '    const ivec2 b = lo + ivec2(int(lid % SPAN), int(lid / SPAN));\n'
        '    if (lid < SPAN * SPAN && b.x <= hi.x && b.y <= hi.y && b.x < int(pc.info.x) &&\n'
        '        b.y < int(pc.info.y)) {\n'
        '        const uint flag = block_flags[uint(b.y) * pc.info.x + uint(b.x)];\n'
        '        if ((flag & (Show() ? 3u : 1u)) != 0u) {\n'
        '            atomicOr(group_live, 1u);\n'
        '        }\n'
        '    }\n'
        '    const uint data = DataBase();\n'
        '    const uint lamp_count = min(counters[data + GLASS_GLINT_DATA_COUNT], GLASS_GLINT_MAX_LAMPS);\n'
        '    if (lid < lamp_count * 2u) {\n'
        '        const uint w = data + GLASS_GLINT_DATA_LAMPS + lid * 4u;\n'
        '        group_lamp[lid] = uintBitsToFloat(\n'
        '            uvec4(counters[w], counters[w + 1u], counters[w + 2u], counters[w + 3u]));\n'
        '    }\n'
        '    barrier();\n'
        '    if (group_live == 0u) {\n'
        '        return; // the same for the whole group (shared, after the barrier)\n'
        '    }\n'
        '    // One pane ray a unit of the tile and its border.\n'
        '    for (uint c = lid; c < CELLS; c += THREADS) {\n'
        '        const ivec2 u = ivec2(int(c % GRID), int(c / GRID)) - 1;\n'
        '        const ivec2 first = tile0 + u * scale;\n'
        '        vec4 hit = vec4(0.0, 0.0, 0.0, -1.0);\n'
        '        if (all(greaterThanEqual(first, ivec2(0))) && all(lessThan(first, size))) {\n'
        '            const vec3 dir = RayDir(vec2(first) + 0.5 * float(scale));\n'
        '            float t_depth = DepthT(first);\n'
        "            if (quads) { // the farthest of the quad's pixels; each still tests its own below\n"
        '                const ivec2 last = min(first + 1, size - 1);\n'
        '                t_depth = max(max(t_depth, DepthT(ivec2(last.x, first.y))),\n'
        '                              max(DepthT(ivec2(first.x, last.y)), DepthT(last)));\n'
        '            }\n'
        '            const float t = PaneT(dir, Reach(t_depth), false);\n'
        '            if (t >= 0.0) {\n'
        '                hit = vec4(dir * t, t);\n'
        '            }\n'
        '        }\n'
        '        group_hit[c] = hit;\n'
        '    }\n'
        '    barrier();\n'
        '    const ivec2 lu = ivec2(gl_LocalInvocationID.xy);\n'
        '    const uint c = uint(lu.y + 1) * GRID + uint(lu.x + 1);\n'
        '    const ivec2 first = tile0 + lu * scale;\n'
        '    const vec4 hit = group_hit[c];\n'
        '    uint glass = 0u, rejected = 0u, glints = 0u, shadow_rays = 0u, shadowed = 0u, no_normal = 0u;\n'
        '    float max_add = 0.0;\n'
        '    if (first.x < size.x && first.y < size.y) {\n'
        '        vec3 add = vec3(0.0);\n'
        '        bool behind = false;\n'
        '        if (hit.w >= 0.0) {\n'
        '            vec3 n;\n'
        '            if (GridNormal(c, hit, n)) {\n'
        '                add = Glint(hit.xyz, n, lamp_count, shadow_rays, shadowed);\n'
        '            } else {\n'
        '                ++no_normal;\n'
        '            }\n'
        '        } else if (Show()) {\n'
        '            behind = PaneT(RayDir(vec2(first) + 0.5 * float(scale)), float(GLASS_GLINT_FAR), true) >= 0.0;\n'
        '        }\n'
        '        const float peak = max(add.r, max(add.g, add.b));\n'
        '        for (int j = 0; j < scale; ++j) {\n'
        '            for (int i = 0; i < scale; ++i) {\n'
        '                const ivec2 p = first + ivec2(i, j);\n'
        '                if (p.x >= size.x || p.y >= size.y) {\n'
        '                    continue;\n'
        '                }\n'
        '                const bool on = hit.w >= 0.0 && (!quads || hit.w <= Reach(DepthT(p)));\n'
        '                if (!on && !behind) {\n'
        '                    continue;\n'
        '                }\n'
        '                glass += on ? 1u : 0u;\n'
        '                rejected += on ? 0u : 1u;\n'
        '                const bool glint = on && peak > float(GLASS_GLINT_GLINT_LEVEL);\n'
        '                glints += glint ? 1u : 0u;\n'
        '                max_add = on ? max(max_add, peak) : max_add;\n'
        '                const vec4 colour = imageLoad(scene_img, p);\n'
        '                if (Show()) {\n'
        '                    // cyan: a pane in front of the depth; blue: only behind it; magenta: a glint\n'
        '                    const vec3 tint = glint ? vec3(1.0, 0.0, 1.0)\n'
        '                                      : on  ? vec3(0.0, 1.0, 1.0)\n'
        '                                            : vec3(0.0, 0.25, 1.0);\n'
        '                    const float level = max(max(colour.r, max(colour.g, colour.b)), 0.1);\n'
        '                    imageStore(scene_img, p, vec4(mix(colour.rgb, tint * level, 0.5) + add, colour.a));\n'
        '                } else if (peak > 0.0 && on) {\n'
        '                    imageStore(scene_img, p, vec4(colour.rgb + add, colour.a));\n'
        '                }\n'
        '            }\n'
        '        }\n'
        '    }\n'
        '    if (glass != 0u) {\n'
        '        atomicAdd(group_count[GLASS_GLINT_W_GLASS], glass);\n'
        '    }\n'
        '    if (rejected != 0u) {\n'
        '        atomicAdd(group_count[GLASS_GLINT_W_REJECTED], rejected);\n'
        '    }\n'
        '    if (glints != 0u) {\n'
        '        atomicAdd(group_count[GLASS_GLINT_W_GLINT], glints);\n'
        '    }\n'
        '    if (shadow_rays != 0u) {\n'
        '        atomicAdd(group_count[GLASS_GLINT_W_SHADOW_RAYS], shadow_rays);\n'
        '    }\n'
        '    if (shadowed != 0u) {\n'
        '        atomicAdd(group_count[GLASS_GLINT_W_SHADOWED], shadowed);\n'
        '    }\n'
        '    if (no_normal != 0u) {\n'
        '        atomicAdd(group_count[GLASS_GLINT_W_NO_NORMAL], no_normal);\n'
        '    }\n'
        '    if (max_add > 0.0) {\n'
        '        atomicMax(group_count[GLASS_GLINT_W_MAX_ADD], floatBitsToUint(max_add));\n'
        '    }\n'
        '    barrier();\n'
        '    if (lid == 0u) {\n'
        '        const uint base = SlotBase();\n'
        '        atomicAdd(counters[base + GLASS_GLINT_W_TILES], 1u);\n'
        '        if (quads) {\n'
        '            atomicAdd(counters[base + GLASS_GLINT_W_QUAD_TILES], 1u);\n'
        '        }\n'
        '        for (uint w = GLASS_GLINT_W_GLASS; w <= GLASS_GLINT_W_SHADOWED; ++w) {\n'
        '            if (group_count[w] != 0u) {\n'
        '                atomicAdd(counters[base + w], group_count[w]);\n'
        '            }\n'
        '        }\n'
        '        if (group_count[GLASS_GLINT_W_NO_NORMAL] != 0u) {\n'
        '            atomicAdd(counters[base + GLASS_GLINT_W_NO_NORMAL], group_count[GLASS_GLINT_W_NO_NORMAL]);\n'
        '        }\n'
        '        if (group_count[GLASS_GLINT_W_MAX_ADD] != 0u) {\n'
        '            atomicMax(counters[base + GLASS_GLINT_W_MAX_ADD], group_count[GLASS_GLINT_W_MAX_ADD]);\n'
        '        }\n'
        '    }\n'
        '}\n'
        '#endif\n'
    ),
    'engine/gpu/shadps4/video_core/renderer_vulkan/glass_glint.h': (
        '// SPDX-License-Identifier: GPL-3.0-or-later\n'
        '#pragma once\n'
        '\n'
        "// bbport (r86b_glass-visible): the lamps' glints on the glass BB_RT_GLASS puts into the ray traced\n"
        "// scene (the Hunter's Dream house's bottles and jars: the pane pair e30b0480:8a6c7657, drawn\n"
        '// forward after the lamp pass). No Vulkan here: the knobs, the lamps a pass takes, the order of\n'
        "// the reasons a pass is skipped and the shader's numbers in C++ (engine/tests/test_glass_glint.cpp\n"
        '// checks them). The pass is GlassGlint (vk_glass_glint.h), the shader host_shaders/glass_glint.comp.\n'
        '//\n'
        '// The rules:\n'
        '//  - BB_GLASS_GLINT, read once: unset, empty, 0 or a negative number: off; `1`: strength 1; a\n'
        '//    number above 0: the strength, put into 0.25 to 4; `show`: strength 1 and the test view (cyan a\n'
        '//    pane in front of the depth, blue a pane only behind it, magenta a glint); other text: off,\n'
        '//    said once. BB_GLASS_GLINT_SHARP: the Blinn-Phong exponent, 16 to 4096 (default 256; other\n'
        '//    text: the default, said once). Off also while BB_RT_GLASS is off (no pane in the scene).\n'
        "//  - On, RtShadow carries the panes drawn in a frame into the next frame's scene and builds their\n"
        '//    waiting captures at the frame end, as BB_RT_GLASS_LIGHT does (RtGlassCarryOn).\n'
        "//  - A pass runs right after a pane's forward draw (at most MaxPasses a frame, once a depth), when\n"
        '//    in this order: the TLAS was written this frame and holds a pane (else "no pane"), with the\n'
        '//    camera of this draw, not in a menu\'s preview frame (else "camera"), a lamp of the last\n'
        '//    G-buffer pass\'s light grid can\n'
        '//    shine (else "no lamps"), no lamps-apart batch is open (else "lamps open": the pass reads the\n'
        '//    camera depth and is skipped, not made to end it), target 0 is a writable RGBA16F image of the\n'
        '//    depth\'s size and the game\'s own scene (not the reduced one) (else "shape"), and fewer than\n'
        '//    MaxPasses passes ran this frame and none on this depth (else "cap").\n'
        '//  - Lamps: of the lights of the last G-buffer pass (each kept once, as drawn, with\n'
        "//    BB_LAMP_FLICKER's colour), LampFog::Select's MaxLamps that show most; a channel below 0 is 0,\n"
        '//    a colour over LampColourMost is scaled down to it (bad guest data only).\n'
        '#include <algorithm>\n'
        '#include <array>\n'
        '#include <bit>\n'
        '#include <cmath>\n'
        '#include <cstddef>\n'
        '#include <cstdint>\n'
        '#include <cstdlib>\n'
        '#include <cstring>\n'
        '#include <span>\n'
        '\n'
        '#include "../host_shaders/glass_glint_layout.h"\n'
        '#include "../host_shaders/rt_glass_layout.h"\n'
        '#include "lamp_fog_lights.h"\n'
        '#include "rt_glass.h"\n'
        '\n'
        'namespace BbGlassGlint {\n'
        '\n'
        'inline constexpr float MinStrength = 0.25f, MaxStrength = 4.0f;\n'
        'inline constexpr std::uint32_t SharpDefault = 256, SharpMin = 16, SharpMax = 4096;\n'
        'inline constexpr std::uint32_t MaxPasses = 2;\n'
        'inline constexpr float LampColourMost = 16.0f;\n'
        '\n'
        'inline constexpr std::uint32_t Group = GLASS_GLINT_GROUP, Block = GLASS_GLINT_BLOCK;\n'
        'inline constexpr std::uint32_t FlagShow = GLASS_GLINT_FLAG_SHOW;\n'
        'inline constexpr std::uint32_t LampMask = GLASS_GLINT_LAMP_MASK;\n'
        'inline constexpr std::uint32_t Slots = GLASS_GLINT_SLOTS, SlotWords = GLASS_GLINT_SLOT_WORDS;\n'
        'inline constexpr std::uint32_t MaxLamps = GLASS_GLINT_MAX_LAMPS, LampWords = GLASS_GLINT_LAMP_WORDS;\n'
        'inline constexpr std::uint32_t DataCount = GLASS_GLINT_DATA_COUNT, DataLamps = GLASS_GLINT_DATA_LAMPS;\n'
        'inline constexpr std::uint32_t DataWords = GLASS_GLINT_DATA_WORDS;\n'
        'inline constexpr std::uint32_t CounterWords = GLASS_GLINT_W_COUNT;\n'
        'inline constexpr std::uint32_t QuadPercent = GLASS_GLINT_QUAD_PERCENT;\n'
        'inline constexpr float F0 = float(GLASS_GLINT_F0), AddMax = float(GLASS_GLINT_ADD_MAX);\n'
        'inline constexpr float TolAbs = float(GLASS_GLINT_TOL_ABS), TolRel = float(GLASS_GLINT_TOL_REL);\n'
        'inline constexpr float ShadowLevel = float(GLASS_GLINT_SHADOW_LEVEL);\n'
        '\n'
        'static_assert(Group == 8 && Block == 4, "glass_glint.comp\'s SPAN (6 blocks) is for these");\n'
        'static_assert((Group + 2) * 2 / Block + 1 <= 6 && 6 * 6 <= Group * Group,\n'
        '              "SHADE: the blocks under a quad tile and its border, one a thread");\n'
        'static_assert(MaxLamps * 2 <= Group * Group, "SHADE: two vec4 a lamp, one a thread");\n'
        'static_assert(DataLamps + MaxLamps * LampWords <= DataWords && DataCount < DataLamps);\n'
        'static_assert(CounterWords <= SlotWords && GLASS_GLINT_W_MAX_ADD < CounterWords &&\n'
        '              GLASS_GLINT_W_NO_NORMAL < CounterWords);\n'
        'static_assert(GLASS_GLINT_W_GLASS < GLASS_GLINT_W_SHADOWED &&\n'
        '              GLASS_GLINT_W_SHADOWED + 1 == GLASS_GLINT_W_MAX_ADD,\n'
        '              "SHADE flushes words W_GLASS to W_SHADOWED with atomicAdd, W_MAX_ADD with atomicMax");\n'
        'static_assert(LampMask == 0x04u && (LampMask & RT_GLASS_MASK) == 0,\n'
        '              "a shadow ray never meets a pane (the panes are under RT_GLASS_MASK alone)");\n'
        'static_assert(Slots >= 4, "a slot is read back Slots - 1 passes after its pass");\n'
        '\n'
        'struct Knobs {\n'
        '    float strength = 0.0f;\n'
        '    bool show = false;\n'
        '    bool unreadable = false;\n'
        '    std::uint32_t sharp = SharpDefault;\n'
        '    bool sharp_unreadable = false;\n'
        '};\n'
        '\n'
        "/// BB_GLASS_GLINT's text (see the rules above).\n"
        'inline float ParseStrength(const char* text, bool& show, bool& unreadable) {\n'
        '    if (text == nullptr || text[0] == 0) {\n'
        '        return 0.0f;\n'
        '    }\n'
        '    if (std::strcmp(text, "show") == 0) {\n'
        '        show = true;\n'
        '        return 1.0f;\n'
        '    }\n'
        '    char* end = nullptr;\n'
        '    const float v = std::strtof(text, &end);\n'
        "    while (end != nullptr && (*end == ' ' || *end == '\\t')) {\n"
        '        ++end;\n'
        '    }\n'
        '    if (end == text || end == nullptr || *end != 0 || !std::isfinite(v)) {\n'
        '        unreadable = true;\n'
        '        return 0.0f;\n'
        '    }\n'
        '    return v > 0.0f ? std::clamp(v, MinStrength, MaxStrength) : 0.0f;\n'
        '}\n'
        '\n'
        "/// BB_GLASS_GLINT_SHARP's text: unset or empty is SharpDefault; a whole number is put into SharpMin\n"
        '/// to SharpMax; other text is SharpDefault and unreadable.\n'
        'inline std::uint32_t ParseSharp(const char* text, bool& unreadable) {\n'
        '    if (text == nullptr || text[0] == 0) {\n'
        '        return SharpDefault;\n'
        '    }\n'
        '    char* end = nullptr;\n'
        '    const long v = std::strtol(text, &end, 10);\n'
        "    while (end != nullptr && (*end == ' ' || *end == '\\t')) {\n"
        '        ++end;\n'
        '    }\n'
        '    if (end == text || end == nullptr || *end != 0) {\n'
        '        unreadable = true;\n'
        '        return SharpDefault;\n'
        '    }\n'
        '    return v < long(SharpMin) ? SharpMin : v > long(SharpMax) ? SharpMax : std::uint32_t(v);\n'
        '}\n'
        '\n'
        'inline Knobs Parse(const char* glint, const char* sharp) {\n'
        '    Knobs k;\n'
        '    k.strength = ParseStrength(glint, k.show, k.unreadable);\n'
        '    k.sharp = ParseSharp(sharp, k.sharp_unreadable);\n'
        '    return k;\n'
        '}\n'
        '\n'
        '/// The knobs, read once (the first caller).\n'
        'inline const Knobs& Load() {\n'
        '    static const Knobs knobs =\n'
        '        Parse(std::getenv("BB_GLASS_GLINT"), std::getenv("BB_GLASS_GLINT_SHARP"));\n'
        '    return knobs;\n'
        '}\n'
        '\n'
        '/// On: a strength above 0 and BB_RT_GLASS on. Off, nothing of the glint is made or run.\n'
        'inline bool On() {\n'
        '    static const bool on = Load().strength > 0.0f && Vulkan::RtGlassOn();\n'
        '    return on;\n'
        '}\n'
        '\n'
        '/// The push words of glass_glint.comp, field for field.\n'
        'struct Push {\n'
        '    std::array<float, 4> proj{};          ///< x scale, y scale, z scale, z offset\n'
        '    std::array<float, 4> frame{};         ///< width, height, jitter x, jitter y (pixels)\n'
        '    std::array<std::uint32_t, 4> info{};  ///< blocks across, blocks down, slot, flags\n'
        '    std::array<float, 4> params{};        ///< strength, exponent, Normalisation(exponent), 0\n'
        '};\n'
        'static_assert(sizeof(Push) == 64);\n'
        '\n'
        "/// Blinn-Phong's normalisation for exponent `n` in the game's lamp units: (n + 8) / 8. The game's\n"
        '/// lamp light is colour x (1 - d / reach)^2 x N.L, times albedo, with no 1/pi (Lambert as albedo /\n'
        "/// pi, so the colour is pi x the radiance factor); the BRDF's (n + 8) / (8 pi) times that pi.\n"
        'constexpr float Normalisation(float n) {\n'
        '    return (n + 8.0f) / 8.0f;\n'
        '}\n'
        '\n'
        "/// Schlick's Fresnel from F0 at cos(view, half) `vh`.\n"
        'inline float Fresnel(float vh) {\n'
        '    return F0 + (1.0f - F0) * std::pow(1.0f - std::clamp(vh, 0.0f, 1.0f), 5.0f);\n'
        '}\n'
        '\n'
        "/// One lamp's term before its colour and the strength (glass_glint.comp's Glint): 0 at or past the\n"
        '/// reach or facing away.\n'
        'inline float Term(float d, float reach, float nl, float nh, float vh, float n) {\n'
        '    if (!(d < reach) || !(nl > 0.0f)) {\n'
        '        return 0.0f;\n'
        '    }\n'
        '    const float fall = 1.0f - d / reach;\n'
        '    return fall * fall * nl * Fresnel(vh) * Normalisation(n) * std::pow(std::max(nh, 0.0f), n);\n'
        '}\n'
        '\n'
        "/// A pane at distance `t` is in front of the depth at distance `depth_t` (the shader's Reach).\n"
        'constexpr bool InFront(float t, float depth_t) {\n'
        '    return t <= depth_t + TolAbs + TolRel * depth_t;\n'
        '}\n'
        '\n'
        "/// More than QuadPercent of the blocks flagged: SHADE's quad mode (the shader's 32-bit words).\n"
        'constexpr bool Quads(std::uint32_t flagged, std::uint32_t blocks) {\n'
        '    return flagged * 100u > blocks * QuadPercent;\n'
        '}\n'
        '\n'
        'constexpr std::uint32_t BlocksOf(std::uint32_t pixels) {\n'
        '    return (pixels + Block - 1) / Block;\n'
        '}\n'
        '\n'
        'constexpr std::uint32_t GroupsOf(std::uint32_t units) {\n'
        '    return (units + Group - 1) / Group;\n'
        '}\n'
        '\n'
        '/// A lamp of a pass, in view space.\n'
        'struct Lamp {\n'
        '    std::array<float, 3> view{};\n'
        '    float reach = 0.0f;\n'
        '    std::array<float, 3> colour{};\n'
        '};\n'
        '\n'
        'struct Picked {\n'
        '    std::array<Lamp, MaxLamps> lamps{};\n'
        '    std::uint32_t count = 0;\n'
        '};\n'
        '\n'
        "/// The pass's lamps from the light grid's records (lamp_fog_lights.h: view x, y, z, inverse reach\n"
        '/// squared, colour r, g, b, ...).\n'
        'inline Picked PickLamps(std::span<const LampFog::Light> lights) {\n'
        '    Picked picked;\n'
        '    const auto chosen = LampFog::Select(lights, MaxLamps);\n'
        '    for (const auto& light : chosen.lights) {\n'
        '        const auto word = [&](std::size_t i) { return std::bit_cast<float>(light[i]); };\n'
        '        const float reach = 1.0f / std::sqrt(word(3));\n'
        '        if (!std::isfinite(reach) || !(reach > 0.0f) || picked.count >= MaxLamps) {\n'
        '            continue;\n'
        '        }\n'
        '        Lamp lamp{{word(0), word(1), word(2)}, reach,\n'
        '                  {std::max(word(4), 0.0f), std::max(word(5), 0.0f), std::max(word(6), 0.0f)}};\n'
        '        const float most = std::max({lamp.colour[0], lamp.colour[1], lamp.colour[2]});\n'
        '        if (most > LampColourMost) {\n'
        '            for (float& c : lamp.colour) {\n'
        '                c *= LampColourMost / most;\n'
        '            }\n'
        '        }\n'
        '        picked.lamps[picked.count++] = lamp;\n'
        '    }\n'
        '    return picked;\n'
        '}\n'
        '\n'
        "/// A lamp's words in the data block.\n"
        'inline std::array<float, LampWords> Words(const Lamp& lamp) {\n'
        '    return {lamp.view[0],   lamp.view[1],   lamp.view[2],   lamp.reach,\n'
        '            lamp.colour[0], lamp.colour[1], lamp.colour[2], 0.0f};\n'
        '}\n'
        '\n'
        '/// The same camera (world to view, 3x4 rows): each entry within 1e-4 of the larger of 1 and its\n'
        '/// size.\n'
        'inline bool SameCamera(const std::array<float, 12>& a, const std::array<float, 12>& b) {\n'
        '    for (std::size_t i = 0; i < a.size(); ++i) {\n'
        '        if (!(std::fabs(a[i] - b[i]) <= 1e-4f * std::max(1.0f, std::fabs(a[i])))) {\n'
        '            return false;\n'
        '        }\n'
        '    }\n'
        '    return true;\n'
        '}\n'
        '\n'
        '/// Why a pass does not run, in the order the gate asks.\n'
        'enum class Skip : std::uint32_t { None, NoPane, OtherCamera, NoLamps, LampsOpen, Shape, Cap };\n'
        '\n'
        'struct Gate {\n'
        '    bool panes = false;       ///< the TLAS holds a pane record\n'
        '    bool this_frame = false;  ///< and was written this frame\n'
        "    bool same_camera = false; ///< with this draw's camera\n"
        '    bool lamps = false;       ///< a lamp of the pass can shine\n'
        '    bool lamps_open = false;  ///< a lamps-apart batch is open\n'
        '    bool shape = false;       ///< target 0 and the depth fit\n'
        '    std::uint32_t passes = 0; ///< passes run this frame\n'
        '    bool depth_done = false;  ///< a pass ran on this depth this frame\n'
        '};\n'
        '\n'
        'constexpr Skip Decide(const Gate& g) {\n'
        '    return (!g.panes || !g.this_frame)             ? Skip::NoPane\n'
        '           : !g.same_camera                        ? Skip::OtherCamera\n'
        '           : !g.lamps                              ? Skip::NoLamps\n'
        '           : g.lamps_open                          ? Skip::LampsOpen\n'
        '           : !g.shape                              ? Skip::Shape\n'
        '           : (g.passes >= MaxPasses || g.depth_done) ? Skip::Cap\n'
        '                                                     : Skip::None;\n'
        '}\n'
        '\n'
        '} // namespace BbGlassGlint\n'
    ),
    'engine/gpu/shadps4/video_core/renderer_vulkan/vk_glass_glint.h': (
        '// SPDX-License-Identifier: GPL-3.0-or-later\n'
        "// bbport (r86b_glass-visible): the lamps' glints on the glass BB_RT_GLASS puts into the ray traced\n"
        '// scene (glass_glint.h has the knobs and the rules, host_shaders/glass_glint.comp the passes).\n'
        '//\n'
        '// Where (hooks in vk_rasterizer_effects.cpp, each a null pointer test while it is off):\n'
        '//  - EffectsAfterTargets, at a G-buffer draw (ClearLights): the lamps of the last G-buffer pass\n'
        '//    only (they are in its view space).\n'
        '//  - EffectsBeforeBind, at a lamp draw of the light grid (AddLights, after its OnLightDraw):\n'
        '//    its records, as drawn.\n'
        '//  - EffectsCaptureDraw notes a pane draw it admitted (its pipeline); EffectsAfterDraw, right after\n'
        '//    that draw (AfterGlassDraw): the passes COARSE and SHADE, once the gate lets them (glass_glint.h).\n'
        '//    A pane draw left out before it is made (an uncompiled pipeline) never reaches AfterDraw: the\n'
        '//    note names the pipeline, AfterDraw compares it and always clears it, the frame end too.\n'
        '//  - EffectsOnFrameEnd (OnFrameEnd): the counters, and every LineFrames frames the log line.\n'
        "// Each pass ends the game's render pass (the next draw begins a new one), as the engine's other\n"
        '// passes between draws do.\n'
        '//\n'
        '// Off (BB_GLASS_GLINT unset or 0, or BB_RT_GLASS off): the rasterizer makes no GlassGlint\n'
        '// (Wanted), so nothing of this is made or run, and RtShadow carries no pane (RtGlassCarryOn is\n'
        "// BB_RT_GLASS_LIGHT's own test then); the frame is as before. On: two pipelines and a 5.5 KB host\n"
        '// buffer (counters and lamps) are made at the start; a buffer of a word per 4x4 block (518 KB at\n'
        '// 1920x1080, 2.1 MB at 3840x2160) at the first pass, and anew when the scene grows. A pass that\n'
        '// cannot get that buffer is counted as "shape".\n'
        '#pragma once\n'
        '\n'
        '#include <array>\n'
        '\n'
        '#include "common/types.h"\n'
        '#include "video_core/renderer_vulkan/glass_glint.h"\n'
        '#include "video_core/renderer_vulkan/lamp_fog_lights.h"\n'
        '#include "video_core/renderer_vulkan/vk_common.h"\n'
        '\n'
        '#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first\n'
        '#include "video_core/texture_cache/image.h"\n'
        '\n'
        'namespace VideoCore {\n'
        'class TextureCache;\n'
        '}\n'
        '\n'
        'namespace Vulkan {\n'
        'class CameraMotion;\n'
        'class Instance;\n'
        'class RtShadow;\n'
        'class Runtime;\n'
        'class SceneTargets;\n'
        'class Scheduler;\n'
        '\n'
        'class GlassGlint {\n'
        'public:\n'
        '    /// BB_GLASS_GLINT names a strength above 0 or "show", and BB_RT_GLASS is on (read once).\n'
        '    [[nodiscard]] static bool Wanted();\n'
        '    /// Makes the pipelines and the counters; says the knobs once.\n'
        '    GlassGlint(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,\n'
        '               Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion,\n'
        '               RtShadow& rt_shadow);\n'
        '    ~GlassGlint();\n'
        '    GlassGlint(const GlassGlint&) = delete;\n'
        '    GlassGlint& operator=(const GlassGlint&) = delete;\n'
        '\n'
        "    /// A lamp draw of the game's light grid: `count` records of 16 words (lamp_fog_lights.h).\n"
        '    void AddLights(const u32* records, u32 count);\n'
        "    /// A G-buffer draw: the lamps gathered so far are another pass's.\n"
        '    void ClearLights();\n'
        "    /// Right after a pane's forward draw: its target 0 (`color`) and depth; `jitter` this frame's\n"
        '    /// viewport shift; `lamps_open` a lamps-apart batch is still open (PointShadow::Pending).\n'
        '    void AfterGlassDraw(VideoCore::ImageId color, VideoCore::ImageId depth,\n'
        '                        std::array<float, 2> jitter, bool lamps_open);\n'
        "    /// Every frame end: the frame's counts, and every LineFrames frames the log line.\n"
        '    void OnFrameEnd();\n'
        '\n'
        'private:\n'
        '    struct Buffer {\n'
        '        vk::Buffer buffer{};\n'
        '        VmaAllocation allocation{};\n'
        '        void* mapped = nullptr;\n'
        '    };\n'
        '    struct Pass {\n'
        '        vk::UniqueDescriptorSetLayout set_layout;\n'
        '        vk::UniquePipelineLayout layout;\n'
        '        vk::UniquePipeline pipeline;\n'
        '    };\n'
        '    struct ViewEntry {\n'
        '        vk::Image image{};\n'
        '        u64 uid = 0;\n'
        '        vk::ImageAspectFlags aspect{};\n'
        '        vk::ImageView view{};\n'
        '        u64 last_use = 0;\n'
        '    };\n'
        '    vk::ImageView CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect);\n'
        "    /// The block flags' buffer holds at least `bytes` (the old one is freed after the GPU is done).\n"
        '    bool EnsureWork(vk::DeviceSize bytes);\n'
        '    void Count(::BbGlassGlint::Skip skip);\n'
        '    void Report();\n'
        '\n'
        '    static constexpr u32 LineFrames = 600;\n'
        '\n'
        '    const Instance& instance;\n'
        '    Scheduler& scheduler;\n'
        '    VideoCore::TextureCache& texture_cache;\n'
        '    Runtime& runtime;\n'
        '    SceneTargets& scene_targets;\n'
        '    CameraMotion& camera_motion;\n'
        '    RtShadow& rt_shadow;\n'
        '\n'
        '    const ::BbGlassGlint::Knobs& knobs;\n'
        '    Pass coarse, shade;\n'
        '    Buffer counters;    ///< host coherent: Slots counter slots, then their data blocks\n'
        '    Buffer work;        ///< device local: a word a block\n'
        '    vk::DeviceSize work_bytes = 0;\n'
        '    bool made = false;\n'
        '    std::array<ViewEntry, 4> view_cache{};\n'
        '    u64 view_uses = 0;\n'
        '    LampFog::FrameLights lights;\n'
        '\n'
        '    // This frame.\n'
        '    u32 frame_passes = 0;\n'
        '    std::array<VideoCore::ImageId, ::BbGlassGlint::MaxPasses> frame_depths{};\n'
        '    u64 passes = 0; ///< all passes: the slot is passes % Slots\n'
        '\n'
        '    struct Stats {\n'
        '        u32 frames = 0, glass_draws = 0, passes = 0;\n'
        '        u32 no_pane = 0, other_camera = 0, no_lamps = 0, lamps_open = 0, shape = 0, cap = 0;\n'
        '        u32 read = 0; ///< passes whose counts were read (Slots - 1 passes late)\n'
        '        u64 lamps = 0;\n'
        '        std::array<u64, ::BbGlassGlint::CounterWords> words{};\n'
        '        float max_add = 0.0f;\n'
        '    } stats;\n'
        '    u64 first_pass_frame = 0; ///< BbStats::frame_number of the first pass, + 1; 0: none yet\n'
        '    bool told_first = false;\n'
        '};\n'
        '\n'
        '} // namespace Vulkan\n'
    ),
    'engine/gpu/shadps4/video_core/renderer_vulkan/vk_glass_glint.cpp': (
        '// SPDX-License-Identifier: GPL-3.0-or-later\n'
        "// bbport (r86b_glass-visible): the lamps' glints on the glass BB_RT_GLASS puts into the ray traced\n"
        '// scene (vk_glass_glint.h; the knobs and the rules in glass_glint.h, the passes in\n'
        '// host_shaders/glass_glint.comp).\n'
        '\n'
        '#include "video_core/renderer_vulkan/vk_glass_glint.h"\n'
        '\n'
        '#include <algorithm>\n'
        '#include <bit>\n'
        '#include <cstdio>\n'
        '#include <cstdlib>\n'
        '#include <cstring>\n'
        '\n'
        '#include "bbport_toggles.h"\n'
        '#include "video_core/host_shaders/glass_glint_coarse_comp.h"\n'
        '#include "video_core/host_shaders/glass_glint_shade_comp.h"\n'
        '#include "video_core/renderer_vulkan/rt_glass_light.h"\n'
        '#include "video_core/renderer_vulkan/vk_camera_motion.h"\n'
        '#include "video_core/renderer_vulkan/vk_effect_pass.h"\n'
        '#include "video_core/renderer_vulkan/vk_instance.h"\n'
        '#include "video_core/renderer_vulkan/vk_platform.h"\n'
        '#include "video_core/renderer_vulkan/vk_rt_shadow.h"\n'
        '#include "video_core/renderer_vulkan/vk_runtime.h"\n'
        '#include "video_core/renderer_vulkan/vk_scene_resolution.h"\n'
        '#include "video_core/renderer_vulkan/vk_scheduler.h"\n'
        '#include "video_core/texture_cache/texture_cache.h"\n'
        '\n'
        'namespace Vulkan {\n'
        'namespace {\n'
        'namespace BG = ::BbGlassGlint;\n'
        'constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;\n'
        'constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;\n'
        'constexpr auto Host = vk::PipelineStageFlagBits2::eHost;\n'
        'constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;\n'
        'constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;\n'
        'constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;\n'
        'constexpr u64 ProfileRow = 86; ///< EffectPass::Mark: the row "Lighting: glass glint"\n'
        'constexpr vk::DeviceSize SlotBytes = BG::SlotWords * sizeof(u32);\n'
        '/// The counters, then a data block a slot (glass_glint_layout.h).\n'
        'constexpr vk::DeviceSize BufferBytes =\n'
        '    BG::Slots * SlotBytes + BG::Slots * BG::DataWords * sizeof(u32);\n'
        'static_assert(BufferBytes == 5632);\n'
        '} // namespace\n'
        '\n'
        'bool GlassGlint::Wanted() {\n'
        '    static const bool wanted = [] {\n'
        '        const BG::Knobs& k = BG::Load();\n'
        '        const char* text = std::getenv("BB_GLASS_GLINT");\n'
        '        if (k.unreadable) {\n'
        '            std::printf("Ray tracing glass glint (r86b): BB_GLASS_GLINT=%.16s is neither a number "\n'
        '                        "nor show: off\\n",\n'
        '                        text);\n'
        '        } else if (text != nullptr && text[0] != 0 && !(k.strength > 0.0f)) {\n'
        '            std::printf("Ray tracing glass glint (r86b): BB_GLASS_GLINT=%.16s: off\\n", text);\n'
        '        } else if (k.strength > 0.0f && !RtGlassOn()) {\n'
        '            std::printf("Ray tracing glass glint (r86b): BB_GLASS_GLINT=%.16s: off, needs "\n'
        '                        "BB_RT_GLASS (off)\\n",\n'
        '                        text);\n'
        '        }\n'
        '        if (k.sharp_unreadable) {\n'
        '            std::printf("Ray tracing glass glint (r86b): BB_GLASS_GLINT_SHARP=%.16s is not a whole "\n'
        '                        "number: %u\\n",\n'
        '                        std::getenv("BB_GLASS_GLINT_SHARP"), k.sharp);\n'
        '        }\n'
        '        return BG::On();\n'
        '    }();\n'
        '    return wanted;\n'
        '}\n'
        '\n'
        'GlassGlint::GlassGlint(const Instance& instance_, Scheduler& scheduler_,\n'
        '                       VideoCore::TextureCache& texture_cache_, Runtime& runtime_,\n'
        '                       SceneTargets& scene_targets_, CameraMotion& camera_motion_,\n'
        '                       RtShadow& rt_shadow_)\n'
        '    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},\n'
        '      scene_targets{scene_targets_}, camera_motion{camera_motion_}, rt_shadow{rt_shadow_},\n'
        '      knobs{BG::Load()} {\n'
        '    using enum vk::DescriptorType;\n'
        '    // The pipelines and the counters are made here, at the start (no compile in play).\n'
        '    made = instance.IsRayQuerySupported() &&\n'
        '           EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&\n'
        '           EffectPass::Create(instance, coarse.set_layout, coarse.layout, coarse.pipeline,\n'
        '                              {eAccelerationStructureKHR, eSampledImage, eStorageImage,\n'
        '                               eStorageBuffer, eStorageBuffer},\n'
        '                              sizeof(BG::Push), GLASS_GLINT_COARSE_COMP, "Glass glint coarse") &&\n'
        '           EffectPass::Create(instance, shade.set_layout, shade.layout, shade.pipeline,\n'
        '                              {eAccelerationStructureKHR, eSampledImage, eStorageImage,\n'
        '                               eStorageBuffer, eStorageBuffer},\n'
        '                              sizeof(BG::Push), GLASS_GLINT_SHADE_COMP, "Glass glint shade");\n'
        '    if (made) {\n'
        '        const VkBufferCreateInfo buffer_ci{\n'
        '            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,\n'
        '            .size = BufferBytes,\n'
        '            .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,\n'
        '        };\n'
        '        VmaAllocationCreateInfo alloc_ci{};\n'
        '        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;\n'
        '        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;\n'
        '        alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;\n'
        '        VkBuffer raw{};\n'
        '        VmaAllocationInfo info{};\n'
        '        if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw,\n'
        '                            &counters.allocation, &info) == VK_SUCCESS) {\n'
        '            counters.buffer = raw;\n'
        '            counters.mapped = info.pMappedData;\n'
        '        }\n'
        '        made = counters.mapped != nullptr;\n'
        '        if (made) {\n'
        '            std::memset(counters.mapped, 0, BufferBytes);\n'
        '        }\n'
        '    }\n'
        '    const char* text = std::getenv("BB_GLASS_GLINT");\n'
        '    std::printf("Ray tracing glass glint (r86b): BB_GLASS_GLINT=%.16s: %s, strength %.2f, sharp %u, "\n'
        '                "lamps up to %u, carry %s, needs BB_RT_GLASS (%s)\\n",\n'
        '                text ? text : "", made ? (knobs.show ? "on, test view" : "on")\n'
        '                                       : "off - the passes could not be made",\n'
        '                double(knobs.strength), knobs.sharp, BG::MaxLamps,\n'
        '                RtGlassCarryOn() ? "on" : "off", RtGlassOn() ? "on" : "off");\n'
        '}\n'
        '\n'
        'GlassGlint::~GlassGlint() {\n'
        '    const auto device = instance.GetDevice();\n'
        '    for (const auto& entry : view_cache) {\n'
        '        if (entry.view) {\n'
        '            device.destroyImageView(entry.view);\n'
        '        }\n'
        '    }\n'
        '    if (counters.buffer) {\n'
        '        vmaDestroyBuffer(instance.GetAllocator(), counters.buffer, counters.allocation);\n'
        '    }\n'
        '    if (work.buffer) {\n'
        '        vmaDestroyBuffer(instance.GetAllocator(), work.buffer, work.allocation);\n'
        '    }\n'
        '}\n'
        '\n'
        'void GlassGlint::AddLights(const u32* records, u32 count) {\n'
        '    lights.Add(records, count);\n'
        '}\n'
        '\n'
        'void GlassGlint::ClearLights() {\n'
        '    lights.Clear();\n'
        '}\n'
        '\n'
        'vk::ImageView GlassGlint::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {\n'
        '    const vk::Image handle = image.GetImage();\n'
        '    ViewEntry* oldest = &view_cache[0];\n'
        '    for (auto& entry : view_cache) {\n'
        '        if (entry.view && entry.image == handle && entry.uid == image.image_uid &&\n'
        '            entry.aspect == aspect) {\n'
        '            entry.last_use = ++view_uses;\n'
        '            return entry.view;\n'
        '        }\n'
        '        if (entry.last_use < oldest->last_use) {\n'
        '            oldest = &entry;\n'
        '        }\n'
        '    }\n'
        '    const auto device = instance.GetDevice();\n'
        '    if (oldest->view) {\n'
        '        scheduler.DeferOperation([device, view = oldest->view] { device.destroyImageView(view); });\n'
        '    }\n'
        '    *oldest = {\n'
        '        .image = handle,\n'
        '        .uid = image.image_uid,\n'
        '        .aspect = aspect,\n'
        '        .view = Check<"create glass glint view">(device.createImageView({\n'
        '            .image = handle,\n'
        '            .viewType = vk::ImageViewType::e2D,\n'
        '            .format = image.info.pixel_format,\n'
        '            .subresourceRange = {aspect, 0, 1, 0, 1},\n'
        '        })),\n'
        '        .last_use = ++view_uses,\n'
        '    };\n'
        '    return oldest->view;\n'
        '}\n'
        '\n'
        'bool GlassGlint::EnsureWork(vk::DeviceSize bytes) {\n'
        '    if (work.buffer && work_bytes >= bytes) {\n'
        '        return true;\n'
        '    }\n'
        '    if (work.buffer) {\n'
        '        scheduler.DeferOperation([allocator = instance.GetAllocator(), buffer = work.buffer,\n'
        '                                  allocation = work.allocation] {\n'
        '            vmaDestroyBuffer(allocator, buffer, allocation);\n'
        '        });\n'
        '        work = {};\n'
        '        work_bytes = 0;\n'
        '    }\n'
        '    const VkBufferCreateInfo buffer_ci{\n'
        '        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,\n'
        '        .size = bytes,\n'
        '        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,\n'
        '    };\n'
        '    VmaAllocationCreateInfo alloc_ci{};\n'
        '    alloc_ci.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE;\n'
        '    VkBuffer raw{};\n'
        '    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &work.allocation,\n'
        '                        nullptr) != VK_SUCCESS) {\n'
        '        work = {};\n'
        '        return false;\n'
        '    }\n'
        '    work.buffer = raw;\n'
        '    work_bytes = bytes;\n'
        '    return true;\n'
        '}\n'
        '\n'
        'void GlassGlint::Count(BG::Skip skip) {\n'
        '    switch (skip) {\n'
        '    case BG::Skip::NoPane:\n'
        '        ++stats.no_pane;\n'
        '        break;\n'
        '    case BG::Skip::OtherCamera:\n'
        '        ++stats.other_camera;\n'
        '        break;\n'
        '    case BG::Skip::NoLamps:\n'
        '        ++stats.no_lamps;\n'
        '        break;\n'
        '    case BG::Skip::LampsOpen:\n'
        '        ++stats.lamps_open;\n'
        '        break;\n'
        '    case BG::Skip::Shape:\n'
        '        ++stats.shape;\n'
        '        break;\n'
        '    case BG::Skip::Cap:\n'
        '        ++stats.cap;\n'
        '        break;\n'
        '    case BG::Skip::None:\n'
        '        break;\n'
        '    }\n'
        '}\n'
        '\n'
        'void GlassGlint::AfterGlassDraw(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,\n'
        '                                std::array<float, 2> jitter, bool lamps_open) {\n'
        '    ++stats.glass_draws;\n'
        "    // The gate, in glass_glint.h's order (Decide names the first reason that holds).\n"
        '    const RtShadow::GlassSceneView glass = rt_shadow.GlassScene();\n'
        '    const vk::AccelerationStructureKHR tlas = rt_shadow.Scene();\n'
        '    const auto camera = camera_motion.PassMatrices();\n'
        '    BG::Gate gate{};\n'
        '    gate.panes = made && glass.instances > 0 && bool(tlas);\n'
        '    gate.this_frame = glass.this_frame;\n'
        "    // A menu's preview frame (several G-buffer passes, not the world) counts as another camera.\n"
        '    gate.same_camera = camera.valid && !camera_motion.PreviewFrame() &&\n'
        '                       BG::SameCamera(glass.view, camera.view);\n'
        '    BG::Picked picked{};\n'
        '    if (gate.panes && gate.this_frame && gate.same_camera) {\n'
        '        picked = BG::PickLamps(lights.Lights());\n'
        '        gate.lamps = picked.count > 0;\n'
        '    }\n'
        '    gate.lamps_open = lamps_open;\n'
        '    VideoCore::Image* color = nullptr;\n'
        '    VideoCore::Image* depth = nullptr;\n'
        '    u32 width = 0, height = 0;\n'
        '    if (gate.lamps && !lamps_open && color_id && depth_id) {\n'
        '        color = &texture_cache.GetImage(color_id);\n'
        '        depth = &texture_cache.GetImage(depth_id);\n'
        '        width = color->info.size.width;\n'
        '        height = color->info.size.height;\n'
        "        // The game's render size (its targets may be allocated larger).\n"
        '        if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {\n'
        '            width = std::min(width, render[0]);\n'
        '            height = std::min(height, render[1]);\n'
        '        }\n'
        '        gate.shape = color->info.pixel_format == vk::Format::eR16G16B16A16Sfloat &&\n'
        '                     bool(color->usage_flags & vk::ImageUsageFlagBits::eStorage) &&\n'
        '                     color->info.size.width == depth->info.size.width &&\n'
        '                     color->info.size.height == depth->info.size.height &&\n'
        '                     !(scene_targets.Reduced() && scene_targets.EligibleScene(*color)) &&\n'
        '                     width >= 16 && height >= 16;\n'
        '    }\n'
        '    gate.passes = frame_passes;\n'
        '    gate.depth_done = std::find(frame_depths.begin(), frame_depths.begin() + frame_passes,\n'
        '                                depth_id) != frame_depths.begin() + frame_passes;\n'
        '    const BG::Skip skip = BG::Decide(gate);\n'
        '    const u32 blocks_x = BG::BlocksOf(width), blocks_y = BG::BlocksOf(height);\n'
        '    const vk::DeviceSize work_size = vk::DeviceSize(blocks_x) * blocks_y * sizeof(u32);\n'
        '    if (skip != BG::Skip::None || !EnsureWork(work_size)) {\n'
        '        Count(skip != BG::Skip::None ? skip : BG::Skip::Shape);\n'
        '        return;\n'
        '    }\n'
        '    // The pass reads the camera depth: with a lamps-apart batch open it was skipped above\n'
        '    // (lamps open), so no batch is ended here.\n'
        '    const SceneUseScope scene_use{"glass glint"};\n'
        '    scheduler.EndRendering();\n'
        '    const vk::ImageView color_view = CachedView(*color, vk::ImageAspectFlagBits::eColor);\n'
        '    const vk::ImageView depth_view = CachedView(*depth, vk::ImageAspectFlagBits::eDepth);\n'
        '    runtime.Transit(color, vk::ImageLayout::eGeneral, Compute, ReadWrite);\n'
        '    runtime.Transit(depth, vk::ImageLayout::eGeneral, Compute, ShaderRead);\n'
        '    runtime.FlushBarriers();\n'
        '    scheduler.EndRendering();\n'
        '\n'
        '    const u32 slot = u32(passes % BG::Slots);\n'
        '    u32* const words = static_cast<u32*>(counters.mapped);\n'
        '    // The counts of the pass Slots - 1 before this one (its work is long done; the slot is\n'
        '    // cleared on the GPU before its next use, the next pass).\n'
        '    if (passes + 1 >= BG::Slots) {\n'
        '        const u32* done = words + ((passes + 1) % BG::Slots) * BG::SlotWords;\n'
        '        for (u32 i = 0; i < BG::CounterWords; ++i) {\n'
        '            if (i == GLASS_GLINT_W_MAX_ADD) {\n'
        '                stats.max_add = std::max(stats.max_add, std::bit_cast<float>(done[i]));\n'
        '            } else {\n'
        '                stats.words[i] += done[i];\n'
        '            }\n'
        '        }\n'
        '        ++stats.read;\n'
        '    }\n'
        "    // This slot's lamps (the slot's last reader, Slots passes ago, is long done).\n"
        '    u32* const data = words + BG::Slots * BG::SlotWords + slot * BG::DataWords;\n'
        '    std::memset(data, 0, BG::DataWords * sizeof(u32));\n'
        '    data[BG::DataCount] = picked.count;\n'
        '    for (u32 k = 0; k < picked.count; ++k) {\n'
        '        const auto lamp = BG::Words(picked.lamps[k]);\n'
        '        std::memcpy(&data[BG::DataLamps + k * BG::LampWords], lamp.data(), sizeof(lamp));\n'
        '    }\n'
        '    BG::Push push{};\n'
        '    push.proj = camera.proj;\n'
        '    push.frame = {float(width), float(height), jitter[0], jitter[1]};\n'
        '    push.info = {blocks_x, blocks_y, slot, knobs.show ? BG::FlagShow : 0u};\n'
        '    push.params = {knobs.strength, float(knobs.sharp), BG::Normalisation(float(knobs.sharp)), 0.0f};\n'
        '\n'
        '    frame_depths[frame_passes++] = depth_id;\n'
        '    ++passes;\n'
        '    ++stats.passes;\n'
        '    stats.lamps += picked.count;\n'
        '    if (first_pass_frame == 0) {\n'
        '        first_pass_frame = u64(BbStats::frame_number.load(std::memory_order_relaxed)) + 1;\n'
        '    }\n'
        '    if (!told_first) {\n'
        '        told_first = true;\n'
        '        std::printf("Ray tracing glass glint (r86b): first pass: %u pane records, %u lamps, scene "\n'
        '                    "%ux%u, %ux%u blocks\\n",\n'
        '                    glass.instances, picked.count, width, height, blocks_x, blocks_y);\n'
        '    }\n'
        "    // Pinned: a row this cheap falls under BB_GPU_PROFILE_ROWS' cut (30 rows) and the cost run\n"
        "    // would not show it.\n"
        '    EffectPass::Mark(ProfileRow, "glass glint", true);\n'
        '    scheduler.RecordCrumb(\n'
        '        {.name = "glass glint"},\n'
        '        [push, width, height, blocks_x, blocks_y, tlas, color_view, depth_view, work_size,\n'
        '         counter_buffer = counters.buffer, work_buffer = work.buffer,\n'
        '         coarse_pipeline = *coarse.pipeline, coarse_layout = *coarse.layout,\n'
        '         shade_pipeline = *shade.pipeline, shade_layout = *shade.layout](vk::CommandBuffer cmdbuf) {\n'
        '            using enum vk::DescriptorType;\n'
        '            cmdbuf.fillBuffer(counter_buffer, push.info[2] * SlotBytes, SlotBytes, 0);\n'
        '            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,\n'
        '                                      Compute, ReadWrite);\n'
        '            const vk::WriteDescriptorSetAccelerationStructureKHR as_info{\n'
        '                .accelerationStructureCount = 1, .pAccelerationStructures = &tlas};\n'
        '            const vk::DescriptorImageInfo depth_info{{}, depth_view, vk::ImageLayout::eGeneral};\n'
        '            const vk::DescriptorImageInfo color_info{{}, color_view, vk::ImageLayout::eGeneral};\n'
        '            const vk::DescriptorBufferInfo work_info{work_buffer, 0, work_size};\n'
        '            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, BufferBytes};\n'
        '            const std::array writes{\n'
        '                vk::WriteDescriptorSet{.pNext = &as_info, .dstBinding = 0, .descriptorCount = 1,\n'
        '                                       .descriptorType = eAccelerationStructureKHR},\n'
        '                vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,\n'
        '                                       .descriptorType = eSampledImage, .pImageInfo = &depth_info},\n'
        '                vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1,\n'
        '                                       .descriptorType = eStorageImage, .pImageInfo = &color_info},\n'
        '                vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1,\n'
        '                                       .descriptorType = eStorageBuffer, .pBufferInfo = &work_info},\n'
        '                vk::WriteDescriptorSet{.dstBinding = 4, .descriptorCount = 1,\n'
        '                                       .descriptorType = eStorageBuffer,\n'
        '                                       .pBufferInfo = &counter_info},\n'
        '            };\n'
        '            const auto run = [&](vk::Pipeline pipeline, vk::PipelineLayout layout, u32 x, u32 y) {\n'
        '                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);\n'
        '                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);\n'
        '                cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push),\n'
        '                                     &push);\n'
        '                cmdbuf.dispatch(x, y, 1);\n'
        '            };\n'
        '            // COARSE a thread a block; SHADE a group an 8x8 pixel tile (in the quad mode the\n'
        '            // groups past the 16x16 tiles return at once).\n'
        '            run(coarse_pipeline, coarse_layout, BG::GroupsOf(blocks_x), BG::GroupsOf(blocks_y));\n'
        '            EffectPass::ComputeBarrier(cmdbuf);\n'
        '            run(shade_pipeline, shade_layout, BG::GroupsOf(width), BG::GroupsOf(height));\n'
        '            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,\n'
        '                                      AllCommands | Host, MemoryAll | vk::AccessFlagBits2::eHostRead);\n'
        '        });\n'
        '}\n'
        '\n'
        'void GlassGlint::OnFrameEnd() {\n'
        '    frame_passes = 0;\n'
        '    frame_depths = {};\n'
        '    lights.Clear();\n'
        '    if (++stats.frames >= LineFrames) {\n'
        '        Report();\n'
        '    }\n'
        '}\n'
        '\n'
        'void GlassGlint::Report() {\n'
        '    const double reads = std::max(1.0, double(stats.read));\n'
        '    const auto per = [&](u32 word) { return double(stats.words[word]) / reads; };\n'
        '    char first[24] = "-";\n'
        '    if (first_pass_frame != 0) {\n'
        '        std::snprintf(first, sizeof(first), "%llu", (unsigned long long)(first_pass_frame - 1));\n'
        '    }\n'
        '    BbReport::Printf(\n'
        '        "Ray tracing glass glint (r86b): %u frames, %u draws, %u passes (first at %s); skipped "\n'
        '        "%u no pane, %u camera, %u no lamps, %u lamps open, %u shape, %u cap; a pass: blocks "\n'
        '        "%.0f/%.0f, glass px %.0f, depth-rejected %.0f, glint px %.0f, shadowed %.0f/%.0f, max add "\n'
        '        "%.2f, lamps %.1f\\n",\n'
        '        stats.frames, stats.glass_draws, stats.passes, first, stats.no_pane, stats.other_camera,\n'
        '        stats.no_lamps, stats.lamps_open, stats.shape, stats.cap, per(GLASS_GLINT_W_FLAGGED),\n'
        '        per(GLASS_GLINT_W_BLOCKS), per(GLASS_GLINT_W_GLASS), per(GLASS_GLINT_W_REJECTED),\n'
        '        per(GLASS_GLINT_W_GLINT), per(GLASS_GLINT_W_SHADOWED), per(GLASS_GLINT_W_SHADOW_RAYS),\n'
        '        double(stats.max_add), double(stats.lamps) / std::max(1.0, double(stats.passes)));\n'
        '    stats = {};\n'
        '}\n'
        '\n'
        '} // namespace Vulkan\n'
    ),
    'engine/tests/test_glass_glint.cpp': (
        '// SPDX-License-Identifier: GPL-3.0-or-later\n'
        "// bbport (r86b_glass-visible): the glass glint's knobs, lamps, gate, push words and shading\n"
        '// numbers (renderer_vulkan/glass_glint.h). Built by engine/build.sh --test (C++20, -Werror) and by\n'
        '// the CMake target glass-glint-test.\n'
        '#include <array>\n'
        '#include <bit>\n'
        '#include <cassert>\n'
        '#include <cmath>\n'
        '#include <cstddef>\n'
        '#include <cstdint>\n'
        '#include <cstdio>\n'
        '#include <vector>\n'
        '\n'
        '#include "gpu/shadps4/video_core/renderer_vulkan/glass_glint.h"\n'
        '\n'
        'using namespace BbGlassGlint;\n'
        '\n'
        'static bool Near(float a, float b, float tol) {\n'
        '    return std::fabs(a - b) <= tol;\n'
        '}\n'
        '\n'
        'static LampFog::Light MakeLight(float x, float y, float z, float reach, float r, float g, float b) {\n'
        '    LampFog::Light light{};\n'
        '    const std::array<float, 7> words{x, y, z, 1.0f / (reach * reach), r, g, b};\n'
        '    for (std::size_t i = 0; i < words.size(); ++i) {\n'
        '        light[i] = std::bit_cast<std::uint32_t>(words[i]);\n'
        '    }\n'
        '    return light;\n'
        '}\n'
        '\n'
        'int main() {\n'
        '    // BB_GLASS_GLINT: off unless a strength above 0 or "show"; a strength is put into 0.25 to 4.\n'
        '    assert(Parse(nullptr, nullptr).strength == 0.0f && !Parse(nullptr, nullptr).unreadable);\n'
        '    assert(Parse("", nullptr).strength == 0.0f && !Parse("", nullptr).unreadable);\n'
        '    assert(Parse("0", nullptr).strength == 0.0f && !Parse("0", nullptr).unreadable);\n'
        '    assert(Parse("-1", nullptr).strength == 0.0f);\n'
        '    assert(Parse("1", nullptr).strength == 1.0f && !Parse("1", nullptr).show);\n'
        '    assert(Parse("1 ", nullptr).strength == 1.0f);\n'
        '    assert(Parse("2.5", nullptr).strength == 2.5f);\n'
        '    assert(Parse("9", nullptr).strength == MaxStrength);\n'
        '    assert(Parse("0.1", nullptr).strength == MinStrength);\n'
        '    assert(Parse("show", nullptr).strength == 1.0f && Parse("show", nullptr).show);\n'
        '    assert(Parse("shows", nullptr).strength == 0.0f && Parse("shows", nullptr).unreadable);\n'
        '    assert(Parse("1x", nullptr).strength == 0.0f && Parse("1x", nullptr).unreadable);\n'
        '    assert(Parse("nan", nullptr).strength == 0.0f && Parse("nan", nullptr).unreadable);\n'
        '    // BB_GLASS_GLINT_SHARP: 16 to 4096, default 256.\n'
        '    assert(Parse("1", nullptr).sharp == SharpDefault && SharpDefault == 256);\n'
        '    assert(Parse("1", "").sharp == 256 && !Parse("1", "").sharp_unreadable);\n'
        '    assert(Parse("1", "512").sharp == 512);\n'
        '    assert(Parse("1", "4").sharp == SharpMin && Parse("1", "-3").sharp == SharpMin);\n'
        '    assert(Parse("1", "100000").sharp == SharpMax);\n'
        '    assert(Parse("1", "soft").sharp == 256 && Parse("1", "soft").sharp_unreadable);\n'
        '    assert(Parse("1", "64.5").sharp == 256 && Parse("1", "64.5").sharp_unreadable);\n'
        '\n'
        '    // The push words: 64 bytes, as glass_glint.comp declares them.\n'
        '    static_assert(offsetof(Push, proj) == 0 && offsetof(Push, frame) == 16);\n'
        '    static_assert(offsetof(Push, info) == 32 && offsetof(Push, params) == 48);\n'
        '\n'
        "    // Shading: the normalisation, Fresnel and one lamp's term.\n"
        "    // In the game's lamp units (no 1/pi): (n + 8) / 8.\n"
        '    assert(Near(Normalisation(256.0f), 33.0f, 1e-5f) && Near(Normalisation(16.0f), 3.0f, 1e-6f));\n'
        '    assert(Near(Fresnel(1.0f), 0.04f, 1e-6f) && Near(Fresnel(0.0f), 1.0f, 1e-6f));\n'
        '    assert(Fresnel(0.5f) > 0.04f && Fresnel(0.5f) < 0.1f);\n'
        '    assert(Term(1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 256.0f) == 0.0f); // at the reach\n'
        '    assert(Term(0.5f, 1.0f, 0.0f, 1.0f, 1.0f, 256.0f) == 0.0f); // facing away\n'
        '    // A mirror direction at half the reach: (1/2)^2 x 1 x 0.04 x 33 = 0.33\n'
        '    assert(Near(Term(0.5f, 1.0f, 1.0f, 1.0f, 1.0f, 256.0f), 0.25f * 0.04f * Normalisation(256.0f),\n'
        '                1e-5f));\n'
        '    // Sharp: 5 degrees off the half vector is far below the peak at 256.\n'
        '    assert(Term(0.5f, 1.0f, 1.0f, std::cos(0.0873f), 1.0f, 256.0f) <\n'
        '           0.5f * Term(0.5f, 1.0f, 1.0f, 1.0f, 1.0f, 256.0f));\n'
        '    // The peak of a torch of colour 2 at 1 m of 4 m reach, strength 1, is a visible glint:\n'
        "    // 2 x 0.5625 x 0.04 x 33 = 1.49, well above the log's glint level and the shadow ray's.\n"
        '    assert(2.0f * Term(1.0f, 4.0f, 1.0f, 1.0f, 1.0f, 256.0f) > float(GLASS_GLINT_GLINT_LEVEL));\n'
        '    assert(2.0f * Term(1.0f, 4.0f, 1.0f, 1.0f, 1.0f, 256.0f) > ShadowLevel);\n'
        '\n'
        '    // The depth test: 2 cm + 0.2 % past the depth.\n'
        '    assert(InFront(1.0f, 1.0f) && InFront(1.021f, 1.0f) && !InFront(1.023f, 1.0f));\n'
        '    assert(InFront(9.0f, 10.0f) && InFront(10.039f, 10.0f) && !InFront(10.041f, 10.0f));\n'
        '\n'
        '    // The quad mode: more than 10 % of the blocks.\n'
        '    assert(!Quads(0, 100) && !Quads(10, 100) && Quads(11, 100));\n'
        '    assert(BlocksOf(3840) == 960 && BlocksOf(2160) == 540 && BlocksOf(1918) == 480);\n'
        '    assert(!Quads(51840, 960 * 540) && Quads(51841, 960 * 540)); // 4K: no 32-bit overflow\n'
        '    assert(GroupsOf(BlocksOf(1920)) == 60 && GroupsOf(1920) == 240 && GroupsOf(1) == 1);\n'
        '\n'
        "    // Lamps: LampFog::Select's MaxLamps that show most; behind the camera left out; colour.\n"
        '    {\n'
        '        std::vector<LampFog::Light> lights;\n'
        '        lights.push_back(MakeLight(0.0f, 0.0f, 2.0f, 4.0f, 1.0f, 0.5f, 0.2f));\n'
        '        lights.push_back(MakeLight(0.0f, 0.0f, -9.0f, 4.0f, 1.0f, 1.0f, 1.0f)); // behind: z + r <= 0\n'
        '        lights.push_back(MakeLight(1.0f, 0.0f, 3.0f, 2.0f, 64.0f, -1.0f, 32.0f));\n'
        '        const Picked picked = PickLamps(lights);\n'
        '        assert(picked.count == 2);\n'
        '        bool saw_bright = false, saw_torch = false;\n'
        '        for (std::uint32_t i = 0; i < picked.count; ++i) {\n'
        '            const Lamp& lamp = picked.lamps[i];\n'
        '            assert(lamp.view[2] > 0.0f);\n'
        '            if (Near(lamp.reach, 2.0f, 1e-4f)) {\n'
        '                saw_bright = true;\n'
        '                assert(Near(lamp.colour[0], LampColourMost, 1e-4f));\n'
        '                assert(lamp.colour[1] == 0.0f);\n'
        '                assert(Near(lamp.colour[2], LampColourMost * 0.5f, 1e-4f));\n'
        '            } else {\n'
        '                saw_torch = Near(lamp.reach, 4.0f, 1e-4f) && Near(lamp.colour[0], 1.0f, 1e-6f);\n'
        '            }\n'
        '        }\n'
        '        assert(saw_bright && saw_torch);\n'
        '        const auto words = Words(picked.lamps[0]);\n'
        '        assert(words.size() == LampWords && words[3] == picked.lamps[0].reach && words[7] == 0.0f);\n'
        '        // More than MaxLamps: MaxLamps.\n'
        '        std::vector<LampFog::Light> many;\n'
        '        for (int i = 0; i < 20; ++i) {\n'
        '            many.push_back(MakeLight(float(i) * 0.1f, 0.0f, 1.0f + float(i), 3.0f, 1.0f, 1.0f, 1.0f));\n'
        '        }\n'
        '        assert(PickLamps(many).count == MaxLamps);\n'
        '        assert(PickLamps({}).count == 0);\n'
        '    }\n'
        '\n'
        '    // The camera: each entry within 1e-4 of the larger of 1 and its size.\n'
        '    {\n'
        '        std::array<float, 12> a{1.0f, 0.0f, 0.0f, 100.0f, 0.0f, 1.0f, 0.0f, -5.0f, 0.0f, 0.0f, 1.0f, 3.0f};\n'
        '        auto b = a;\n'
        '        assert(SameCamera(a, b));\n'
        '        b[0] += 5e-5f;\n'
        '        b[3] += 5e-3f;\n'
        '        assert(SameCamera(a, b));\n'
        '        b[7] += 1e-3f;\n'
        '        assert(!SameCamera(a, b));\n'
        '        b = a;\n'
        '        b[2] = std::nanf("");\n'
        '        assert(!SameCamera(a, b));\n'
        '    }\n'
        '\n'
        '    // The gate: its order.\n'
        '    {\n'
        '        const Gate good{.panes = true, .this_frame = true, .same_camera = true, .lamps = true,\n'
        '                        .lamps_open = false, .shape = true, .passes = 0, .depth_done = false};\n'
        '        assert(Decide(good) == Skip::None);\n'
        '        Gate g = good;\n'
        '        g.passes = MaxPasses - 1;\n'
        '        assert(Decide(g) == Skip::None);\n'
        '        g.passes = MaxPasses;\n'
        '        assert(Decide(g) == Skip::Cap);\n'
        '        g = good;\n'
        '        g.depth_done = true;\n'
        '        assert(Decide(g) == Skip::Cap);\n'
        '        g.shape = false;\n'
        '        assert(Decide(g) == Skip::Shape);\n'
        '        g.lamps_open = true;\n'
        '        assert(Decide(g) == Skip::LampsOpen);\n'
        '        g.lamps = false;\n'
        '        assert(Decide(g) == Skip::NoLamps);\n'
        '        g.same_camera = false;\n'
        '        assert(Decide(g) == Skip::OtherCamera);\n'
        '        g.this_frame = false;\n'
        '        assert(Decide(g) == Skip::NoPane);\n'
        '        g = good;\n'
        '        g.panes = false;\n'
        '        assert(Decide(g) == Skip::NoPane);\n'
        '        assert(Decide(Gate{}) == Skip::NoPane);\n'
        '    }\n'
        '\n'
        '    std::printf("glass glint test: all passed\\n");\n'
        '    return 0;\n'
        '}\n'
    ),
}


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        print("REFUSED %s: missing" % path)
        sys.exit(1)
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        print("REFUSED %s: mixed line ends" % path)
        sys.exit(1)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def readme_edit(cur):
    """The README rows go after the BB_RT_GLASS_LIGHT row (one line, found by its start)."""
    lines = [l for l in cur.split("\n") if l.startswith(README_ROW_PREFIX)]
    if len(lines) != 1:
        print("REFUSED README.md: the BB_RT_GLASS_LIGHT row found %d times" % len(lines))
        sys.exit(1)
    anchor = lines[0] + "\n"
    return [(anchor, anchor + README_ROWS)]


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


def new_state(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    raw = open(full, "rb").read()
    if raw == NEW[path].replace("\n", "\r\n").encode("utf-8"):
        return "applied"
    print("REFUSED %s: a file of that name exists and is not this patch's" % path)
    sys.exit(1)


def text_checks(t):
    """The ties a compiler cannot check, on the texts as they are once applied."""
    layout = t[HS + "glass_glint_layout.h"]
    shader = t[HS + "glass_glint.comp"]
    rules = t[RV + "glass_glint.h"]
    cpp = t[RV + "vk_glass_glint.cpp"]
    eff = t[RV + "vk_rasterizer_effects.cpp"]
    readme = t["README.md"]
    cmake = t["engine/gpu/CMakeLists.txt"]
    for want in ("#define GLASS_GLINT_GROUP 8\n", "#define GLASS_GLINT_BLOCK 4\n", "#define GLASS_GLINT_SLOTS 16u\n",
                 "#define GLASS_GLINT_SLOT_WORDS 16u\n", "#define GLASS_GLINT_DATA_WORDS 72u\n",
                 "#define GLASS_GLINT_MAX_LAMPS 8u\n", "#define GLASS_GLINT_TOL_ABS 0.02\n",
                 "#define GLASS_GLINT_TOL_REL 0.002\n", "#define GLASS_GLINT_NEAR_ABS 0.03\n",
                 "#define GLASS_GLINT_NEAR_REL 0.01\n", "#define GLASS_GLINT_F0 0.04\n",
                 "#define GLASS_GLINT_ADD_MAX 8.0\n", "#define GLASS_GLINT_SHADOW_TMIN 0.03\n",
                 "#define GLASS_GLINT_LAMP_STOP 0.1\n", "#define GLASS_GLINT_GLINT_LEVEL 0.02\n",
                 "#define GLASS_GLINT_QUAD_PERCENT 10u\n", "#define GLASS_GLINT_LAMP_MASK 0x04u\n"):
        if layout.count(want) != 1:
            raise SystemExit("text check: glass_glint_layout.h lacks %r" % want)
    # 16 slots x (16 + 72) words x 4 bytes = 5632, the README's and vk_glass_glint.cpp's
    if "static_assert(BufferBytes == 5632);" not in cpp or "5632 bytes" not in readme:
        raise SystemExit("text check: the counters' size is not 5632 bytes in both")
    for want in ("0.25 to 4", "2 cm + 0.2 %", "3 cm + 1 %", "(n + 8) / 8 (the game's lamp units", "Schlick from 0.04", "(1 - d / reach)^2",
                 "1/255", "3 cm to 10 cm", "0 to 8", "more than 10 %", "4x4 block", "up to 8", "at most 2 times a frame",
                 "16 to 4096", "| 256 |", "Ray tracing glass glint (r86b)", "Lighting: glass glint", "15 passes late",
                 "above 0.02"):
        if want not in readme:
            raise SystemExit("text check: README rows lack %r" % want)
    if "return (n + 8.0f) / 8.0f;" not in rules:
        raise SystemExit("text check: glass_glint.h's normalisation is not the README's (n + 8) / 8")
    if "MaxPasses = 2;" not in rules or "SharpDefault = 256, SharpMin = 16, SharpMax = 4096;" not in rules:
        raise SystemExit("text check: glass_glint.h's numbers are not the README's")
    if "MinStrength = 0.25f, MaxStrength = 4.0f;" not in rules:
        raise SystemExit("text check: glass_glint.h's strength range is not the README's")
    # five bindings in the shader, in both Create lists and in the descriptor writes
    if shader.count("layout(set = 0, binding = ") != 5:
        raise SystemExit("text check: the shader does not have 5 bindings")
    lists = cpp.count("{eAccelerationStructureKHR, eSampledImage, eStorageImage,\n"
                      "                               eStorageBuffer, eStorageBuffer},")
    if lists != 2:
        raise SystemExit("text check: vk_glass_glint.cpp's two Create lists are not the 5 bindings")
    for i in range(5):
        if (".dstBinding = %d," % i) not in cpp:
            raise SystemExit("text check: vk_glass_glint.cpp writes no binding %d" % i)
    # the profile row is this pass's alone
    if "constexpr u64 ProfileRow = 86;" not in cpp or 'EffectPass::Mark(ProfileRow, "glass glint", true);' not in cpp:
        raise SystemExit("text check: the profile row is not 86")
    for name in sorted(os.listdir(os.path.join(ROOT, RV))):
        if name.endswith(".cpp") and name != "vk_glass_glint.cpp":
            text = open(os.path.join(ROOT, RV, name), "rb").read().decode("utf-8", "replace")
            if "ProfileRow = 86;" in text or "Mark(86," in text:
                raise SystemExit("text check: profile row 86 is used by %s too" % name)
    # the hooks where they belong
    b = eff.find("point_shadow->OnLightDraw(cb_descs[0].first")
    a = eff.find("glass_glint->AddLights(")
    c = eff.find(".mrt_mask = pipeline->GetGraphicsKey().mrt_mask});\n", b)
    if not (0 <= b < c < a < c + 200):
        raise SystemExit("text check: AddLights is not right after the lamp draw's OnLightDraw call")
    a, b = eff.find("glass_glint->AfterGlassDraw("), eff.find("    if (!effects_wanted) {\n        return;\n    }\n",
                                                             eff.find("void Rasterizer::EffectsAfterDraw("))
    if not (0 <= a < b):
        raise SystemExit("text check: AfterGlassDraw is not before EffectsAfterDraw's effects_wanted return")
    a, b = eff.find("glass_glint->ClearLights();"), eff.find("heat_haze->ClearLights();")
    if not (0 <= b < a < b + 200):
        raise SystemExit("text check: ClearLights is not beside the heat haze's")
    if cmake.count("COARSE=1)") != 1 or cmake.count("glass_glint_shade_comp SHADE=1)") != 1:
        raise SystemExit("text check: CMake does not build both shader variants once")
    if "GLASS_GLINT_COARSE_COMP" not in cpp or "GLASS_GLINT_SHADE_COMP" not in cpp:
        raise SystemExit("text check: vk_glass_glint.cpp does not use both builds")
    # the once-line and the 600-frame line: their prefix, and short enough
    for want in ("Ray tracing glass glint (r86b): BB_GLASS_GLINT=%.16s: %s, strength %.2f, sharp %u, ",
                 "\"lamps up to %u, carry %s, needs BB_RT_GLASS (%s)\\n\"",
                 "\"Ray tracing glass glint (r86b): %u frames, %u draws, %u passes (first at %s); skipped \""):
        if want not in cpp:
            raise SystemExit("text check: vk_glass_glint.cpp lacks %r" % want)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        print("%s is not a source tree root (set R86B_ROOT)" % ROOT)
        sys.exit(1)
    plan = []
    for path, eds in EDITS.items():
        raw, eol, cur = load(path)
        if path == "README.md":
            eds = readme_edit(cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    news = [(path, new_state(path)) for path in NEW]
    states = {p[5] for p in plan} | {s for _, s in news}
    if len(states) != 1:
        print("REFUSED mixed state: " + ", ".join(["%s %s" % (p[0], p[5]) for p in plan] +
                                                 ["%s %s" % n for n in news]))
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
        out.update(NEW)
        return out

    if cmd == "check":
        if state == "applied":
            texts = {p[0]: p[4] for p in plan}
            texts.update(NEW)
            text_checks(texts)
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files, %d edits, %d new files; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        manifest = []
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
            manifest.append("%s %s" % (hashlib.sha256(raw).hexdigest(), path))
        open(os.path.join(BACKUP, "MANIFEST.txt"), "w", encoding="utf-8", newline="\n").write(
            "r86b_glass-visible: the touched files before apply (sha256, path)\n" + "\n".join(manifest) + "\n")
        out = {p[0]: texts[p[0]].replace("\n", p[3]).encode("utf-8") for p in plan}
        for path in NEW:
            out[path] = NEW[path].replace("\n", "\r\n").encode("utf-8")
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
        for path in NEW:
            out[path] = None
    written = []
    try:
        for path in out:
            full = os.path.join(ROOT, path)
            before = open(full, "rb").read() if os.path.exists(full) else None
            if out[path] is None:
                os.remove(full)
            else:
                tmp = full + ".r86btmp"
                open(tmp, "wb").write(out[path])
                os.replace(tmp, full)
            written.append((full, before))
    except OSError as err:
        for full, before in reversed(written):
            if before is None:
                if os.path.exists(full):
                    os.remove(full)
            else:
                open(full, "wb").write(before)
        print("REFUSED: write failed (%s); everything written was put back" % err)
        sys.exit(1)
    print("applied" if cmd == "apply" else "reverted")


main()
