# r77_parallel-test-runs: engine switches for several test games at once from one install, in
# small windows, without the HUD in their pictures. Four parts; part 1 alone is the one the
# agreed design asks for before HUD-free slot pictures, parts 2-4 are "nicer only":
#
#   1. BB_CLEAN_SHOT=1 (start switch, off by default): the game's HUD and menus are left out of
#      every frame that draws the world. The renderer part of camera mode's clean shot (camera
#      mode commits aa02ee3, 04631ae, 99485ac: UiComposition::CleanShotSkip and
#      Rasterizer::CleanShotEarly, unchanged), set only at the start (BbSettings::Load). No F3 key,
#      no overlay hiding, no pad chords here. Tests: ui-composition-test (clean shot cases, now
#      also in build.sh --test), settings-test (the switch).
#   2. BB_RUN_DIR (start program): patches.bin, file-fixes.txt and wide-ui-movies.txt go to that
#      folder instead of engine/out, so slots started side by side do not read each other's copies
#      of these three files (<data>/engine-assets stays shared: slots still need equal values of
#      the settings that prepare it).
#   3. Mod overlay ownership (start program): a start's overlay is named mod-game-<its process
#      id>-<8 letters>; a later start keeps an overlay whose start program still runs instead of
#      removing it (a mod-on game beside a mod-off start). The junction test link is per process; a
#      later start removes one left by a start that no longer runs (and the old fixed name).
#   4. BB_WINDOW_RECT=x,y,w,h (renderer window): a windowed start opens its window at that place
#      and size instead of centred at 1920x1080.
#
# Nothing changes for players when none of the variables is set (part 3 changes only the overlay
# folder's name and keeps live overlays of other running starts).
#
# Use: cd <tree> && python -I -X utf8 r77_parallel-test-runs.py check | apply | revert
# (root from R77_ROOT, else the current directory; R77_PARTS=1 or 1,3 limits the run to those
# parts, default all; originals of the files a run writes are kept in R77_BACKUP, default
# r77_backup/ next to this script). Files keep their line ends. The parts' anchors do not
# overlap, so any subset applies and reverts on its own. The README anchors avoid r76's (which
# edits the text before "## Sponsors").
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.environ.get("R77_BACKUP") or os.path.join(HERE, "r77_backup")
ROOT = os.environ.get("R77_ROOT") or os.getcwd()
R = "engine/gpu/shadps4/video_core/renderer_vulkan/"

# ---------------------------------------------------------------------------------------------
# Part 1: BB_CLEAN_SHOT=1, the HUD-free start (needed for routine HUD-free slot pictures)
# ---------------------------------------------------------------------------------------------
PART1 = {
    R + "ui_composition.h": [(r'''           (mrt_mask == 0 && has_stencil && MovieShader(vs_hash));
}

struct FitTransform {''', r'''           (mrt_mask == 0 && has_stencil && MovieShader(vs_hash));
}

// Clean shot (BbSettings clean_shot): where the frame being recorded is, as its draws show it.
enum class CleanShotPhase : uint8_t {
    NoWorld, ///< no G-buffer pass since the display pass (shadow passes; a loading screen)
    World,   ///< a G-buffer pass was drawn: the scene, its post passes, the tonemap
    Ui,      ///< the game's UI over the finished frame, up to the next display pass
};
// A G-buffer pass: 5 or more colour targets with a depth target.
constexpr bool WorldPass(uint32_t mrt_mask, bool depth_target) {
    return std::popcount(mrt_mask & 0xff) >= 5 && depth_target;
}
// One draw as clean shot sees it. Sizes are the guest targets' (the render size in a scaled
// session, as the upscaler's RenderTarget).
struct CleanShotDraw {
    bool world_pass = false;   ///< WorldPass
    bool movie = false;        ///< a Scaleform draw (MovieShader)
    uint64_t color = 0;        ///< colour target 0's guest address when the draw writes it, else 0
    bool rgba8 = false;        ///< that target is RGBA8
    bool display = false;      ///< that target is a display buffer
    uint32_t width = 0, height = 0;               ///< that target's size
    uint64_t stencil = 0;      ///< the stencil buffer's guest address when stencil is on, else 0
    uint32_t stencil_width = 0, stencil_height = 0; ///< that buffer's size
};
// Where the frame being recorded is. The display pass (the copy of a finished frame into a
// display buffer, the first pass of the next frame's work) starts every frame with a new one.
struct CleanShotFrame {
    CleanShotPhase phase = CleanShotPhase::NoWorld;
    uint32_t world_width = 0, world_height = 0; ///< the largest G-buffer target since NoWorld
    uint64_t ldr = 0;      ///< the last frame-size RGBA8 target drawn in World (the tonemap's)
    uint64_t ui_color = 0; ///< the UI's target (the frame the UI is drawn over)
    uint64_t ui_stencil = 0; ///< the UI's stencil buffer (its clip masks)
};
// Within 8 pixels: the game aligns its targets a few pixels larger than the scene (as
// TargetViewport).
constexpr bool CleanShotNear(uint32_t width, uint32_t height, uint32_t world_width,
                             uint32_t world_height) {
    const auto near = [](uint32_t a, uint32_t b) { return (a > b ? a - b : b - a) <= 8; };
    return world_width != 0 && near(width, world_width) && near(height, world_height);
}
// A draw into the frame: an RGBA8 colour target of the G-buffer's size that is not a display
// buffer (the upscaler's LdrFrame).
constexpr bool CleanShotFrameTarget(const CleanShotFrame& frame, const CleanShotDraw& draw) {
    return draw.color != 0 && draw.rgba8 && !draw.display &&
           CleanShotNear(draw.width, draw.height, frame.world_width, frame.world_height);
}
// Clean shot's rule for one draw (true: leave it out).
// - A G-buffer pass sets World (a new frame's after a display pass gone unseen) and is drawn.
// - In World the UI starts at the first Scaleform draw that is either an image into the frame
//   (CleanShotFrameTarget) or a clip mask (no colour target) on a stencil buffer of the G-buffer's
//   size; the UI's target is that image's, or for a clip mask the last frame-size RGBA8 target
//   drawn in World. A Scaleform draw into any other target does not start it.
// - In Ui a draw is left out when it writes the UI's target, whatever its shader (Scaleform's
//   images, text, the item icons drawn through the clip masks, the gauges' backgrounds), or when it
//   writes no colour and has stencil on with the UI's stencil buffer (the clip masks). The UI's
//   target or stencil buffer, when the draw that started the UI did not show it, is taken from the
//   first later Scaleform image into the frame and from the first draw into the UI's target with
//   stencil on. Every draw into another target is drawn (Scaleform's own caches, the next frame's
//   passes).
// A frame without a G-buffer pass (a loading screen) keeps its UI.
constexpr bool CleanShotSkip(CleanShotFrame& frame, const CleanShotDraw& draw) {
    if (draw.world_pass) {
        if (frame.phase != CleanShotPhase::World) {
            frame = {};
            frame.phase = CleanShotPhase::World;
        }
        frame.world_width = std::max(frame.world_width, draw.width);
        frame.world_height = std::max(frame.world_height, draw.height);
        return false;
    }
    if (frame.phase == CleanShotPhase::World) {
        const bool frame_target = CleanShotFrameTarget(frame, draw);
        const bool mask =
            draw.color == 0 && draw.stencil != 0 &&
            CleanShotNear(draw.stencil_width, draw.stencil_height, frame.world_width,
                          frame.world_height);
        if (!draw.movie || !(frame_target || mask)) {
            if (frame_target) frame.ldr = draw.color;
            return false;
        }
        frame.phase = CleanShotPhase::Ui;
        frame.ui_color = frame_target ? draw.color : frame.ldr;
        frame.ui_stencil = draw.stencil;
        return true;
    }
    if (frame.phase != CleanShotPhase::Ui) {
        return false;
    }
    if (frame.ui_color == 0 && draw.movie && CleanShotFrameTarget(frame, draw)) {
        frame.ui_color = draw.color;
    }
    if (draw.color != 0) {
        if (draw.color != frame.ui_color) return false;
        if (frame.ui_stencil == 0) frame.ui_stencil = draw.stencil;
        return true;
    }
    return draw.stencil != 0 && draw.stencil == frame.ui_stencil;
}

struct FitTransform {''')],
    R + "vk_rasterizer.h": [
        (r'''#include "video_core/renderer_vulkan/vk_temporal_upscaler.h"
#include "video_core/renderer_vulkan/vk_pipeline_cache.h"
''', r'''#include "video_core/renderer_vulkan/vk_temporal_upscaler.h"
#include "video_core/renderer_vulkan/ui_composition.h"
#include "video_core/renderer_vulkan/vk_pipeline_cache.h"
'''),
        (r'''    void NotifyUiDraw(const GraphicsPipeline* pipeline);
    RenderState BeginRendering(const GraphicsPipeline* pipeline);
''', r'''    void NotifyUiDraw(const GraphicsPipeline* pipeline);
    /// bbport (r77_parallel-test-runs): clean shot leaves this draw of the game's UI out.
    bool CleanShotEarly(const GraphicsPipeline* pipeline);
    RenderState BeginRendering(const GraphicsPipeline* pipeline);
'''),
        (r'''    } sun_keep;
    bool scene_started = false;
    /// bbport: the scene depth of the frame before (SkipUncompiledDraw).
''', r'''    } sun_keep;
    bool scene_started = false;
    /// bbport (r77_parallel-test-runs): clean shot as the last display pass read it, for the
    /// whole frame (a change never splits a frame's UI), and where that frame is and its UI's
    /// targets (CleanShotEarly).
    bool clean_shot_frame = false;
    UiComposition::CleanShotFrame clean_shot_state;
    /// bbport: the scene depth of the frame before (SkipUncompiledDraw).
'''),
    ],
    R + "vk_rasterizer.cpp": [
        (r'''                     UiComposition::WidenedUiViewport(viewport.xscale * 2, viewport.yscale * 2));
}

static std::pair<u32, u32> GetDrawOffsets(''', r'''                     UiComposition::WidenedUiViewport(viewport.xscale * 2, viewport.yscale * 2));
}

// bbport (r77_parallel-test-runs): clean shot (BbSettings clean_shot, set at the start by
// BB_CLEAN_SHOT=1, latched per frame at the display pass into clean_shot_frame). In a frame that
// drew the world, from its first UI draw (a Scaleform draw into the frame or a clip mask on a
// stencil buffer of the G-buffer's size, after the G-buffer pass) up to the display pass, every
// draw into the UI's target or onto its stencil buffer is left out before its targets, bindings
// and pass (UiComposition::CleanShotSkip has the exact rule): Scaleform's images and clip masks
// and the UI draws of other shaders (text, the item icons drawn through the masks, the gauges'
// backgrounds). Draws into other targets stay (Scaleform's own caches, the next frame's passes).
// The frame reaches its display pass as one without UI, as with the HUD hidden in the game's
// options; by reading the code the upscale, frame generation's HUD-less image and native HDR's
// map take their existing no-UI paths. A frame without a G-buffer pass (loading screens) keeps
// its UI. Off: one plain bool test per draw. On: a popcount per draw, a few register reads and
// address compares per draw after the world; fewer draws recorded.
static const std::atomic<bool>& clean_shot = BbSettings::Get().clean_shot; // read once a frame
bool Rasterizer::CleanShotEarly(const GraphicsPipeline* pipeline) {
    const auto& regs = Regs();
    const auto& key = pipeline->GetGraphicsKey();
    UiComposition::CleanShotDraw draw;
    draw.world_pass = UiComposition::WorldPass(
        key.mrt_mask, regs.depth_control.depth_enable && regs.depth_buffer.DepthValid());
    if (!draw.world_pass && clean_shot_state.phase == UiComposition::CleanShotPhase::NoWorld) {
        return false;
    }
    const auto& cb = regs.color_buffers[0];
    if ((key.mrt_mask & 1) && cb) {
        const auto extent = CbExtent(0);
        draw.color = cb.Address();
        draw.rgba8 = cb.GetDataFmt() == AmdGpu::DataFormat::Format8_8_8_8;
        draw.display = FrameCapture::IsDisplayBuffer(draw.color);
        draw.width = extent.Valid() ? extent.width : cb.Pitch();
        draw.height = extent.Valid() ? extent.height : cb.Height();
    }
    if (!draw.world_pass) {
        draw.movie = UiComposition::MovieShader(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash);
        const auto& db = regs.depth_buffer;
        if (regs.depth_control.stencil_enable && db.StencilValid()) {
            const auto extent = DbExtent();
            draw.stencil = db.StencilAddress();
            draw.stencil_width = extent.Valid() ? extent.width : db.Pitch();
            draw.stencil_height = extent.Valid() ? extent.height : db.Height();
        }
    }
    return UiComposition::CleanShotSkip(clean_shot_state, draw);
}

static std::pair<u32, u32> GetDrawOffsets('''),
        (r'''        FrameCapture::IsDisplayBuffer(regs.color_buffers[0].Address())) {
        depth_of_field->Reset();
    }
''', r'''        FrameCapture::IsDisplayBuffer(regs.color_buffers[0].Address())) {
        depth_of_field->Reset();
        // bbport (r77_parallel-test-runs): clean shot is taken for the whole next frame, whose
        // world is not drawn yet
        clean_shot_frame = clean_shot.load(std::memory_order_relaxed);
        clean_shot_state = {};
    }
'''),
        (r'''    if (sun_hold.active && SunHoldEarly(pipeline)) {
        return;
    }
    dc.bind_prepared = used_prepared;
''', r'''    if (sun_hold.active && SunHoldEarly(pipeline)) {
        return;
    }
    // bbport (r77_parallel-test-runs): clean shot leaves the game's HUD and menus out the same
    // way. Off: one test of a plain bool per draw.
    if (clean_shot_frame && CleanShotEarly(pipeline)) {
        return;
    }
    dc.bind_prepared = used_prepared;
'''),
        (r'''    dc.motion_geometry = 0;
    if (sun_hold.active) { // r7_cascades
''', r'''    dc.motion_geometry = 0;
    if (clean_shot_frame && CleanShotEarly(pipeline)) {
        return; // bbport (r77_parallel-test-runs): as in DrawRecord
    }
    if (sun_hold.active) { // r7_cascades
'''),
    ],
    "engine/gpu/shim/bbport_settings.h": [(r'''    std::atomic<bool> show_fps{false};
    std::atomic<bool> voice_enabled{true}, voice_push_to_talk{true}, voice_mic_muted{false};
''', r'''    std::atomic<bool> show_fps{false};
    // bbport (r77_parallel-test-runs): clean shot: in every frame that draws the world the
    // renderer leaves out the game's HUD and menus, from the first UI draw onto the finished frame
    // to the display pass (Rasterizer::CleanShotEarly, UiComposition::CleanShotSkip); loading
    // screens keep theirs, the engine's own overlay is not hidden. Set only at the start, by
    // BB_CLEAN_SHOT=1 (Load): no ini key, never saved, no key or menu row changes it.
    std::atomic<bool> clean_shot{false};
    std::atomic<bool> voice_enabled{true}, voice_push_to_talk{true}, voice_mic_muted{false};
''')],
    "engine/gpu/shim/bbport_settings.cpp": [(r'''    if (std::getenv("BB_HDR_PEAK")) {
        v.hdr_peak_auto = false;
    }
    v.startup_preset = v.preset;
''', r'''    if (std::getenv("BB_HDR_PEAK")) {
        v.hdr_peak_auto = false;
    }
    // bbport (r77_parallel-test-runs): BB_CLEAN_SHOT=1 starts with clean shot on (test runs in
    // small windows, whose pictures must not carry the HUD); any other value or none: off.
    {
        const char* clean = std::getenv("BB_CLEAN_SHOT");
        v.clean_shot.store(clean && std::strcmp(clean, "1") == 0, std::memory_order_relaxed);
        if (v.clean_shot.load(std::memory_order_relaxed)) {
            std::printf("Settings: BB_CLEAN_SHOT=1: the game's HUD and menus are left out of every "
                        "frame that draws the world\n");
        }
    }
    v.startup_preset = v.preset;
''')],
    "engine/tests/test_settings.cpp": [(r'''    unsetenv("BB_DLSS_PRESET");
#endif
''', r'''    unsetenv("BB_DLSS_PRESET");
#endif
    // bbport (r77_parallel-test-runs): BB_CLEAN_SHOT=1 starts with clean shot on; another value
    // or none leaves it off.
#ifdef _WIN32
    _putenv_s("BB_CLEAN_SHOT", "1");
#else
    setenv("BB_CLEAN_SHOT", "1", 1);
#endif
    BbSettings::Load();
    assert(s.clean_shot.load());
#ifdef _WIN32
    _putenv_s("BB_CLEAN_SHOT", "yes");
#else
    setenv("BB_CLEAN_SHOT", "yes", 1);
#endif
    BbSettings::Load();
    assert(!s.clean_shot.load());
#ifdef _WIN32
    _putenv_s("BB_CLEAN_SHOT", "");
#else
    unsetenv("BB_CLEAN_SHOT");
#endif
    BbSettings::Load();
    assert(!s.clean_shot.load());
''')],
    "engine/tests/test_ui_composition.cpp": [(r'''    assert(!SceneHasUiViewportSize(3440, 1440, ParseUiSize("3360x1440")));
    std::puts("UI composition: PASS (menu without camera, HUD, FSR off, viewport scaling)");
''', r'''    assert(!SceneHasUiViewportSize(3440, 1440, ParseUiSize("3360x1440")));
    // Clean shot (BB_CLEAN_SHOT=1): from the first Scaleform draw into the frame (or clip mask)
    // after the world (a G-buffer pass) up to the display pass every draw into the UI's target or
    // onto its stencil buffer is left out, the UI draws of other shaders too; other targets stay.
    assert(WorldPass(0x1f, true) && WorldPass(0xff, true));
    assert(!WorldPass(0x1f, false) && !WorldPass(0x0f, true) && !WorldPass(0x1, true));
    assert(CleanShotNear(1920, 1088, 1920, 1080) && !CleanShotNear(1920, 1089, 1920, 1080));
    assert(!CleanShotNear(1920, 1080, 0, 0));
    {
        constexpr uint64_t gbuffer = 0x1000, hdr = 0x2000, ui = 0x3000, aa = 0x4000,
                           shadow = 0x5000, cache = 0x6000, ui_stencil = 0x7000,
                           cache_stencil = 0x8000, display = 0x9000;
        const auto target = [](uint64_t color, bool rgba8, uint32_t w, uint32_t h) {
            CleanShotDraw d;
            d.color = color;
            d.rgba8 = rgba8;
            d.width = w;
            d.height = h;
            return d;
        };
        const auto movie = [](CleanShotDraw d) { d.movie = true; return d; };
        const auto stencil = [](CleanShotDraw d, uint64_t address, uint32_t w, uint32_t h) {
            d.stencil = address;
            d.stencil_width = w;
            d.stencil_height = h;
            return d;
        };
        CleanShotDraw world = target(gbuffer, false, 1920, 1080);
        world.world_pass = true;
        const CleanShotDraw shadow_pass = {}; // depth only
        const auto mask = stencil(movie({}), ui_stencil, 1920, 1088);
        const auto icon = stencil(target(ui, true, 1920, 1088), ui_stencil, 1920, 1088);
        const auto text = target(ui, true, 1920, 1088);
        {
            // A world frame: shadow pass, G-buffer, an RGBA8 target of another size drawn by
            // Scaleform (left alone: it does not start the UI), the HDR scene, the tonemap into the
            // UI target, then the HUD: a clip mask, an item icon of another shader through it,
            // text, a Scaleform image, a Scaleform cache fill into another target.
            CleanShotFrame frame;
            assert(!CleanShotSkip(frame, shadow_pass) && frame.phase == CleanShotPhase::NoWorld);
            assert(!CleanShotSkip(frame, world) && frame.phase == CleanShotPhase::World);
            assert(frame.world_width == 1920 && frame.world_height == 1080);
            assert(!CleanShotSkip(frame, movie(target(cache, true, 512, 512))));
            assert(!CleanShotSkip(frame, stencil(movie({}), cache_stencil, 512, 512)));
            assert(frame.phase == CleanShotPhase::World);
            assert(!CleanShotSkip(frame, target(hdr, false, 1920, 1080)));
            assert(!CleanShotSkip(frame, text) && frame.ldr == ui); // the tonemap
            assert(CleanShotSkip(frame, mask) && frame.phase == CleanShotPhase::Ui);
            assert(frame.ui_color == ui && frame.ui_stencil == ui_stencil);
            assert(CleanShotSkip(frame, icon) && CleanShotSkip(frame, text));
            assert(CleanShotSkip(frame, movie(text)) && CleanShotSkip(frame, mask));
            assert(!CleanShotSkip(frame, movie(target(cache, true, 512, 512))));
            assert(!CleanShotSkip(frame, stencil(movie({}), cache_stencil, 512, 512)));
            assert(!CleanShotSkip(frame, stencil(target(shadow, false, 1024, 1024), shadow, 1024, 1024)));
            assert(!CleanShotSkip(frame, shadow_pass));
            // The display pass starts a new frame (Rasterizer::DrawRecord); the next frame's
            // passes are drawn.
            frame = {};
            assert(!CleanShotSkip(frame, shadow_pass) && !CleanShotSkip(frame, text));
        }
        {
            // The UI started by a Scaleform image into the frame (the game's AA wrote another
            // target last), its stencil buffer from the first draw into it with stencil on.
            CleanShotFrame frame;
            assert(!CleanShotSkip(frame, world));
            assert(!CleanShotSkip(frame, target(aa, true, 1920, 1088)) && frame.ldr == aa);
            assert(CleanShotSkip(frame, movie(text)) && frame.ui_color == ui && !frame.ui_stencil);
            assert(!CleanShotSkip(frame, mask)); // stencil buffer not known yet: a mask only
            assert(CleanShotSkip(frame, icon) && frame.ui_stencil == ui_stencil);
            assert(CleanShotSkip(frame, mask) && !CleanShotSkip(frame, target(aa, true, 1920, 1088)));
            // Not the frame: a display buffer, another format, another size.
            CleanShotFrame other;
            CleanShotSkip(other, world);
            auto shown = text;
            shown.color = display;
            shown.display = true;
            assert(!CleanShotSkip(other, movie(shown)));
            assert(!CleanShotSkip(other, movie(target(ui, false, 1920, 1080))));
            assert(!CleanShotSkip(other, movie(target(ui, true, 960, 540))));
            assert(other.phase == CleanShotPhase::World);
        }
        {
            // A clip mask before any frame-size RGBA8 target: the UI's target comes from the
            // first Scaleform image into the frame.
            CleanShotFrame frame;
            CleanShotSkip(frame, world);
            assert(CleanShotSkip(frame, mask) && frame.ui_color == 0);
            assert(!CleanShotSkip(frame, text));
            assert(CleanShotSkip(frame, movie(text)) && frame.ui_color == ui);
            assert(CleanShotSkip(frame, text));
        }
        {
            // A loading screen: no G-buffer pass, its UI stays.
            CleanShotFrame frame;
            assert(!CleanShotSkip(frame, mask) && !CleanShotSkip(frame, movie(text)));
            assert(!CleanShotSkip(frame, text) && frame.phase == CleanShotPhase::NoWorld);
        }
        {
            // A display pass gone unseen: the next frame's passes into other targets are drawn,
            // and its G-buffer pass starts a new frame.
            CleanShotFrame frame;
            CleanShotSkip(frame, world);
            CleanShotSkip(frame, text);
            assert(CleanShotSkip(frame, mask));
            assert(!CleanShotSkip(frame, shadow_pass) && !CleanShotSkip(frame, world));
            assert(frame.phase == CleanShotPhase::World && frame.ui_color == 0 && frame.ldr == 0);
            assert(!CleanShotSkip(frame, text));
        }
        {
            // A start with the guest targets at a 1280x720 output (upscale_before_post=1 with
            // DLSS Performance at 1280x720): the same rule at that size.
            CleanShotFrame frame;
            auto small_world = target(gbuffer, false, 1280, 720);
            small_world.world_pass = true;
            const auto small_text = target(ui, true, 1280, 720);
            assert(!CleanShotSkip(frame, small_world) && !CleanShotSkip(frame, small_text));
            assert(CleanShotSkip(frame, stencil(movie({}), ui_stencil, 1280, 720)));
            assert(CleanShotSkip(frame, small_text) && frame.ui_color == ui);
            assert(!CleanShotSkip(frame, movie(target(cache, true, 1920, 1080))));
        }
    }
    std::puts("UI composition: PASS (menu without camera, HUD, FSR off, viewport scaling, clean shot)");
''')],
    "engine/build.sh": [(r'''    out/online-gate-test
''', r'''    out/online-gate-test
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_ui_composition.cpp -o out/ui-composition-test
    out/ui-composition-test
''')],
    "README.md": [(r'''without writing it to the ini.
''', r'''without writing it to the ini. `BB_CLEAN_SHOT=1` starts the game with clean shot on, for test runs whose pictures must not carry the HUD: in every frame that draws the world, from the game's first menu-movie (Scaleform) draw onto the finished picture or onto its clip mask after the scene to the end of the frame, every draw onto that picture or its clip masks is left out, whatever draws it (the HUD, menus and subtitles, and dims and fades drawn there too); draws into other images stay, and a frame that draws no world (a loading screen) keeps its UI. The engine's own overlay (FPS counter, notes) is not hidden. The log says `Settings: BB_CLEAN_SHOT=1: ...`; any other value, or none, leaves it off, and it is never saved.
''')],
}

# ---------------------------------------------------------------------------------------------
# Part 2: BB_RUN_DIR (nicer only: the three per-start files no longer shared)
# ---------------------------------------------------------------------------------------------
PART2 = {
    "engine/start/main.cpp": [
        (r'''    fs::create_directories(out);
    if (Lower(Utf8(folders.package)).find("onedrive") != std::string::npos)
''', r'''    fs::create_directories(out);
    // bbport (r77_parallel-test-runs): BB_RUN_DIR, when set, is the folder of the three files this
    // start writes for its game to read when the game starts (patches.bin, file-fixes.txt,
    // wide-ui-movies.txt) instead of out, so games started side by side from one install do not
    // read each other's copies of them (what is prepared in <data>/engine-assets stays shared).
    // Made absolute here, because the game runs in another folder (RunProbe). Not set: out.
    const std::string run_dir = Env("BB_RUN_DIR", "");
    fs::path run = out;
    if (!run_dir.empty()) {
        std::error_code run_error;
        run = fs::absolute(Path(run_dir), run_error);
        if (!run.empty()) fs::create_directories(run, run_error);
        if (run.empty() || !fs::is_directory(run, run_error)) {
            Log("Run files: BB_RUN_DIR is not a folder and cannot be made: %s", run_dir.c_str());
            return 1;
        }
        Log("Run files for this run (BB_RUN_DIR): %s", Utf8(run).c_str());
    }
    if (Lower(Utf8(folders.package)).find("onedrive") != std::string::npos)
'''),
        (r'''        WriteText(out / "file-fixes.txt", list);
        SetEnv("BB_FILE_FIXES", Utf8(out / "file-fixes.txt"));
''', r'''        WriteText(run / "file-fixes.txt", list);
        SetEnv("BB_FILE_FIXES", Utf8(run / "file-fixes.txt"));
'''),
        (r'''            .output_res = Env("BB_OUTPUT_RES", ""),
        });
''', r'''            .output_res = Env("BB_OUTPUT_RES", ""),
            .run = run,
        });
'''),
        (r'''                WriteText(out / "wide-ui-movies.txt", list);
                SetEnv("BB_WIDE_UI_MOVIES", Utf8(out / "wide-ui-movies.txt"));
''', r'''                WriteText(run / "wide-ui-movies.txt", list);
                SetEnv("BB_WIDE_UI_MOVIES", Utf8(run / "wide-ui-movies.txt"));
'''),
        (r'''                                      L"--patches", (out / "patches.bin").native(), L"--app0", merged.native(), L"--user",
''', r'''                                      L"--patches", (run / "patches.bin").native(), L"--app0", merged.native(), L"--user",
'''),
    ],
    "engine/start/patches.h": [(r'''    std::string fps, extra, render_res, output_res;
};
''', r'''    std::string fps, extra, render_res, output_res;
    /// bbport (r77_parallel-test-runs): the folder patches.bin is written to (BB_RUN_DIR);
    /// empty: out.
    fs::path run;
};
''')],
    "engine/start/patches.cpp": [(r'''    WriteFile(request.out / "patches.bin", blob);
''', r'''    WriteFile((request.run.empty() ? request.out : request.run) / "patches.bin", blob);
''')],
    "README.md": [(r'''
## In-game menu / ini-only graphics settings
''', r'''
## Several games from one install (test runs)

On Windows the start program (`engine/out/bb-start.exe`) takes `BB_RUN_DIR=<folder>`: the files it writes at every start for the game to read when the game starts (`patches.bin`, `file-fixes.txt`, `wide-ui-movies.txt`) go to that folder instead of `engine/out`, so games started side by side from one install do not read each other's copies of these three files. What the start prepares in the data folder's `engine-assets` (among them the PC menus, the widened menu movies, the mirror, Lamp2Lamp and the effect, player-lamp and jump-key fixes) stays one shared set that a start may rewrite for its own settings, so games started side by side still need the same values of the settings that change it. A relative path counts from the folder bb-start is started in. The folder is made when missing; one that cannot be made stops the start (`Run files: BB_RUN_DIR is not a folder and cannot be made: <path>`, bb-start returns 1). The log says `Run files for this run (BB_RUN_DIR): <path>`. Not set: `engine/out`, as before. Each game also needs its own `BB_CONFIG`, `BB_LOG_FILE`, `BB_GPU_USER_DIR` and saves folder.

## In-game menu / ini-only graphics settings
''')],
}

# ---------------------------------------------------------------------------------------------
# Part 3: mod overlay ownership (nicer only: a mod-on game can run beside other starts)
# ---------------------------------------------------------------------------------------------
PART3 = {
    "engine/start/mods.cpp": [
        (r'''    const fs::path probe = folder / L"mod-junction-test";
''', r'''    // bbport (r77_parallel-test-runs): one per start, so two starts side by side do not remove
    // each other's test link
    const fs::path probe = folder / (L"mod-junction-test-" + std::to_wstring(GetCurrentProcessId()));
'''),
        (r'''void RemoveStaleOverlays(const fs::path& out) {
    for (const fs::path& entry : Entries(out)) {
        if (!StartsWith(Utf8(entry.filename()), "mod-game-") || !IsDir(entry) || IsLink(entry)) continue;
        try {
''', r'''// bbport (r77_parallel-test-runs): a start names its overlay mod-game-<its process id>-<8
// letters> (MakeTemporary). The id of an overlay whose start program still runs (a process of this
// program's file name with that id, not this one): a game started beside this one from the same
// install reads it. Any other overlay, also one named before r77 (no id), is a leftover.
std::optional<DWORD> RunningOwner(const std::string& name) {
    constexpr std::string_view prefix = "mod-game-";
    std::uint64_t id = 0;
    std::size_t at = prefix.size();
    while (at < name.size() && at - prefix.size() < 10 && name[at] >= '0' && name[at] <= '9')
        id = id * 10 + std::uint64_t(name[at++] - '0');
    if (at == prefix.size() || at >= name.size() || name[at] != '-' || id == 0 || id > 0xffffffffull ||
        DWORD(id) == GetCurrentProcessId())
        return std::nullopt;
    HANDLE process = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, DWORD(id));
    if (!process) return std::nullopt;
    std::wstring theirs(32768, L'\0'), ours(32768, L'\0');
    DWORD their_size = DWORD(theirs.size()), our_size = DWORD(ours.size());
    const bool running = WaitForSingleObject(process, 0) == WAIT_TIMEOUT &&
                         QueryFullProcessImageNameW(process, 0, theirs.data(), &their_size) &&
                         QueryFullProcessImageNameW(GetCurrentProcess(), 0, ours.data(), &our_size) &&
                         Fold(fs::path(theirs.substr(0, their_size)).filename().native()) ==
                             Fold(fs::path(ours.substr(0, our_size)).filename().native());
    CloseHandle(process);
    if (!running) return std::nullopt;
    return DWORD(id);
}

void RemoveStaleOverlays(const fs::path& out) {
    for (const fs::path& entry : Entries(out)) {
        const std::string name = Utf8(entry.filename());
        // a junction test link (JunctionsWork; it points at out itself) of a start that ended
        // inside JunctionsWork, or one of the fixed name earlier builds used: removed; the link of
        // a start still running stays
        if (StartsWith(name, "mod-junction-test") && IsLink(entry)) {
            const std::string id = name.size() > 18 ? name.substr(18) : std::string();
            if (!RunningOwner("mod-game-" + id + "-")) RemoveDirectoryW(entry.c_str());
            continue;
        }
        if (!StartsWith(name, "mod-game-") || !IsDir(entry) || IsLink(entry)) continue;
        if (const auto owner = RunningOwner(name)) {
            Log("Mods: kept %s: its start (process %lu) is still running", name.c_str(),
                static_cast<unsigned long>(*owner));
            continue;
        }
        try {
'''),
        (r'''        std::string name = "mod-game-";
''', r'''        std::string name = "mod-game-" + std::to_string(GetCurrentProcessId()) + "-";
'''),
    ],
    "engine/docs/MODS.md": [(r'''tree is removed. After SIGKILL or a power loss it may remain; such folders are not used by the next
start.
''', r'''tree is removed. After SIGKILL or a power loss it may remain; such folders are not used by the next
start. On Windows the tree's name carries the process id of the start program (bb-start) that made
it, `mod-game-<id>-*` (in `out`, or in `.bbport-overlays` next to the game folder when the game is
on another drive). A start removes the trees left by earlier starts but keeps one whose maker still
runs (a running program with that id and the same file name as this start program); the log then
says `Mods: kept mod-game-<id>-...: its start (process <id>) is still running`. Trees named before
this change (`mod-game-` and 8 letters) are removed as before, also while their game runs, and an
older start program or the Python start (`scripts/mods.py`) still removes every tree. The list of
the next paragraph, `mod-files.txt`, is still one file per folder.
''')],
}

# ---------------------------------------------------------------------------------------------
# Part 4: BB_WINDOW_RECT (nicer only: no centred window first)
# ---------------------------------------------------------------------------------------------
PART4 = {
    "engine/gpu/shim/window.cpp": [(r'''    SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_WIDTH_NUMBER, width_);
    SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_HEIGHT_NUMBER, height_);
    SDL_SetBooleanProperty(props, SDL_PROP_WINDOW_CREATE_RESIZABLE_BOOLEAN, true);
    SDL_SetBooleanProperty(props, SDL_PROP_WINDOW_CREATE_VULKAN_BOOLEAN, true);
    const char* fullscreen = std::getenv("BB_FULLSCREEN");
    SDL_SetBooleanProperty(props, SDL_PROP_WINDOW_CREATE_FULLSCREEN_BOOLEAN,
                           fullscreen ? fullscreen[0] == '1' : BbSettings::Get().fullscreen.load());
''', r'''    const char* fullscreen = std::getenv("BB_FULLSCREEN");
    const bool start_fullscreen =
        fullscreen ? fullscreen[0] == '1' : BbSettings::Get().fullscreen.load();
    s32 create_width = width_, create_height = height_;
    // bbport (r77_parallel-test-runs): BB_WINDOW_RECT=x,y,w,h opens a windowed start's window with
    // its client area (the picture, without title bar and frame) at x,y and w x h in size (SDL's
    // window coordinates, as BB_MONITOR_BOUNDS; x and y -100000 to 100000, w and h 64 to 16384)
    // instead of centred at the size asked for. The title bar and frame lie outside it: a runner
    // that tiles outer window rectangles (SetWindowPos) converts with AdjustWindowRectEx. Read
    // once here. A fullscreen start ignores it.
    bool rect_placed = false;
    if (const char* rect = std::getenv("BB_WINDOW_RECT"); rect && *rect) {
        int x, y, w, h;
        char trailing;
        if (start_fullscreen) {
            std::printf("Display: BB_WINDOW_RECT ignored: the window starts fullscreen\n");
        } else if (SDL_sscanf(rect, "%d,%d,%d,%d%c", &x, &y, &w, &h, &trailing) == 4 &&
                   x >= -100000 && x <= 100000 && y >= -100000 && y <= 100000 && w >= 64 &&
                   w <= 16384 && h >= 64 && h <= 16384) {
            SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_X_NUMBER, x);
            SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_Y_NUMBER, y);
            create_width = w;
            create_height = h;
            rect_placed = true;
            std::printf("Display: window at %d,%d, %dx%d (BB_WINDOW_RECT)\n", x, y, w, h);
        } else {
            std::printf("Display: BB_WINDOW_RECT '%s' is not x,y,w,h (x and y -100000 to 100000, w and "
                        "h 64 to 16384); the window is centred\n", rect);
        }
    }
    SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_WIDTH_NUMBER, create_width);
    SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_HEIGHT_NUMBER, create_height);
    SDL_SetBooleanProperty(props, SDL_PROP_WINDOW_CREATE_RESIZABLE_BOOLEAN, true);
    SDL_SetBooleanProperty(props, SDL_PROP_WINDOW_CREATE_VULKAN_BOOLEAN, true);
    SDL_SetBooleanProperty(props, SDL_PROP_WINDOW_CREATE_FULLSCREEN_BOOLEAN, start_fullscreen);
'''),
        (r'''    UpdateDisplayPeak(window);
    LOG_INFO(Frontend, "Window {}x{} on {}", w, h, driver);
}
''', r'''    UpdateDisplayPeak(window);
    LOG_INFO(Frontend, "Window {}x{} on {}", w, h, driver);
    if (rect_placed) {
        // bbport (r77_parallel-test-runs): where BB_WINDOW_RECT's window landed and its client
        // area in pixels (differs from the asked size under display scaling)
        int placed_x = 0, placed_y = 0;
        SDL_GetWindowPosition(window, &placed_x, &placed_y);
        std::printf("Display: window placed at %d,%d (window coordinates), client area %dx%d pixels\n",
                    placed_x, placed_y, w, h);
    }
}
''')],
    "README.md": [(r'''disabled with `BB_SKY_SEAM_FIX=0`. ''', r'''disabled with `BB_SKY_SEAM_FIX=0`. `BB_WINDOW_RECT=x,y,w,h` opens a windowed start's window with its client area (the picture, without title bar and frame) at x,y and w x h in size (SDL's window coordinates, as `BB_MONITOR_BOUNDS`; x and y -100000 to 100000, w and h 64 to 16384) instead of centred at 1920x1080, so a test runner can tile several games; the title bar and frame lie outside that rectangle. The log says `Display: window at x,y, wxh (BB_WINDOW_RECT)` and then `Display: window placed at x,y (window coordinates), client area wxh pixels`; a value that is not four numbers in those ranges is logged and the window is centred, and a fullscreen start ignores it. ''')],
}

PARTS = [(1, "BB_CLEAN_SHOT start switch", PART1), (2, "BB_RUN_DIR", PART2),
         (3, "mod overlay ownership", PART3), (4, "BB_WINDOW_RECT", PART4)]

def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")

def part_state(edits_by_file, texts):
    states = set()
    for path, edits in edits_by_file.items():
        cur = texts[path][2]
        done = sum(cur.count(new) == 1 for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): states.add("applied")
        elif todo == len(edits): states.add("clean")
        else: raise SystemExit("%s: %d of %d edits applied, %d anchors found" % (path, done, len(edits), todo))
    if len(states) != 1:
        raise SystemExit("a part is half applied")
    return states.pop()

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    wanted = os.environ.get("R77_PARTS", "")
    wanted = {int(p) for p in wanted.split(",") if p.strip()} or {n for n, _, _ in PARTS}
    parts = [p for p in PARTS if p[0] in wanted]
    if len(parts) != len(wanted):
        raise SystemExit("R77_PARTS names a part that does not exist (1 to %d)" % len(PARTS))
    texts = {}
    for _, _, edits_by_file in parts:
        for path in edits_by_file:
            if path not in texts: texts[path] = load(path)
    states = [(n, name, edits_by_file, part_state(edits_by_file, texts)) for n, name, edits_by_file in parts]
    if cmd == "check":
        for n, name, _, state in states:
            print("part %d (%s): %s" % (n, name, "applied" if state == "applied" else "not applied"))
        every = {s[3] for s in states}
        print("applied" if every == {"applied"} else "not applied; would apply (%d files)" % len(texts)
              if every == {"clean"} else "partly applied")
        return
    todo = [s for s in states if s[3] == ("clean" if cmd == "apply" else "applied")]
    if not todo:
        print("already applied" if cmd == "apply" else "nothing to revert"); return
    if cmd == "revert": todo = todo[::-1]
    touched = {}
    for n, name, edits_by_file, _ in todo:
        for path, edits in edits_by_file.items():
            raw, eol, cur = texts[path]
            touched.setdefault(path, raw)
            for old, new in (edits if cmd == "apply" else edits[::-1]):
                cur = cur.replace(old, new) if cmd == "apply" else cur.replace(new, old)
            texts[path] = (raw, eol, cur)
    if cmd == "apply":
        os.makedirs(BACKUP, exist_ok=True)
        for path, raw in touched.items():
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
    for path in touched:
        raw, eol, cur = texts[path]
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    print("%s: parts %s" % ("applied" if cmd == "apply" else "reverted", ", ".join(str(s[0]) for s in todo)))

main()
