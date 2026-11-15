// SPDX-License-Identifier: GPL-2.0-or-later
#include <cassert>
#include <cstdio>
#include "gpu/shadps4/video_core/renderer_vulkan/ui_composition.h"

int main() {
    using namespace Vulkan::UiComposition;
    assert(Choose(true, true, false, true) == Background::Copy);
    assert(Choose(true, true, false, false) == Background::Copy);
    assert(Choose(true, true, true, true) == Background::Temporal);
    assert(Choose(true, true, true, false) == Background::Copy);
    assert(Choose(true, false, true, true) == Background::None);
    assert(Choose(false, true, true, true) == Background::None);
    assert(NativeViewport(1920, -1080));
    assert(!NativeViewport(960, -540));
    constexpr std::array<float, 2> ui4k{3840.0f, 2160.0f};
    assert(WidenedUiViewport(3840, -2160, ui4k));
    assert(!WidenedUiViewport(1920, -1080, ui4k));
    assert(!WidenedUiViewport(1920, -1080));
    assert(SceneHasUiViewportSize(1916, 1076, ui4k) && !SceneNearUiSize(1916, 1076, ui4k));
    assert(SceneNearUiSize(3840, 2160, ui4k));
    assert(MovieShader(0x34e8a281) && MovieShader(0x24042a9b));
    assert(!MovieShader(0x0b0acf50));
    assert(!MovieShader(0x6c62a79f));
    assert(ObserveDraw(0, 0xa400228b, true));
    assert(ObserveDraw(0, 0x34e8a281, true));
    assert(ObserveDraw(1, 0x44072322, true));
    assert(!ObserveDraw(0, 0x6c62a79f, true));
    assert(!ObserveDraw(0, 0xa400228b, false));
    assert(!ObserveDraw(3, 0xa400228b, true));
    const auto display = Scale(960, 540, 1920, 1080, false);
    assert(display[0] == 2 && display[1] == 2);
    const auto ui = Scale(960, 540, 1920, 1080, true);
    assert(ui[0] == 1 && ui[1] == 1);
    const auto larger = Scale(960, 540, 3840, 2160, true);
    assert(larger[0] == 2 && larger[1] == 2);
    for(auto size: {std::array<uint32_t,2>{1920,1080},{2560,1440},{3840,2160},{3440,1440},{5120,1440}}) {
        auto f=Fit(size[0],size[1]);
        assert(f.scale[0]==f.scale[1]);
        assert(f.offset[0]>=0 && f.offset[1]>=0);
        assert(std::abs(1920*f.scale[0]+2*f.offset[0]-size[0])<.01f);
        assert(std::abs(1080*f.scale[1]+2*f.offset[1]-size[1])<.01f);
    }
    assert(Fit(1920,1080).offset==(std::array<float,2>{0,0}));
    assert(std::abs(Fit(3440,1440).offset[0]-440)<.01f);
    assert(std::abs(Fit(5120,1440).offset[0]-1280)<.01f);
    const auto wide = ParseUiSize("2520x1080");
    assert(wide[0] == 2520 && wide[1] == 1080);
    assert(ParseUiSize(nullptr)[0] == 1920 && ParseUiSize("800x600")[0] == 1920 && ParseUiSize("junk")[1] == 1080);
    assert(NativeViewport(2520, -1080, wide) && NativeViewport(1920, 1080, wide) && !NativeViewport(2560, 1080, wide));
    const auto w = Fit(3360, 1440, wide);
    assert(w.scale[0] == w.scale[1] && std::abs(w.offset[0]) < .01f && std::abs(w.offset[1]) < .01f);
    assert(std::abs((300 * w.scale[0] + w.offset[0]) - Fit(3360, 1440).offset[0]) < .01f);
    const auto t = Fit(1920, 1200, ParseUiSize("1920x1200"));
    assert(t.scale[0] == 1 && t.offset[1] == 0);
    const auto sharp = ParseUiSize("3840x2160");
    assert(TargetViewport(1916, -1076, 1920, 1080) && TargetViewport(1708, 960, 1712, 960));
    assert(!TargetViewport(128, 128, 1920, 1080));
    assert(InnerViewport(128, -128, 1920, 1080, sharp) && InnerViewport(2560, 1440, 1712, 960, sharp));
    assert(!InnerViewport(3840, 2160, 1920, 1080, sharp) && !InnerViewport(1920, 1080, 1920, 1080, sharp));
    assert(!InnerViewport(1916, 1076, 1920, 1080, sharp) && !InnerViewport(4096, 2160, 1920, 1080, sharp));
    assert(!InnerViewport(0, 0, 1920, 1080, sharp));
    assert(SceneHasUiViewportSize(2560, 1440, ParseUiSize("2560x1440")));
    assert(SceneHasUiViewportSize(1920, 1080, sharp) && SceneHasUiViewportSize(1924, 1084, sharp));
    assert(!SceneHasUiViewportSize(1708, 960, ParseUiSize("2560x1440")));
    assert(!SceneHasUiViewportSize(2560, 1440, ParseUiSize(nullptr)));
    assert(!SceneHasUiViewportSize(2296, 960, ParseUiSize("3360x1440")));
    assert(!SceneHasUiViewportSize(3440, 1440, ParseUiSize("3360x1440")));
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
}
