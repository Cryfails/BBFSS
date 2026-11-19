// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r55_drawn-look-lines): the drawn look's rules that need no GPU, from
// renderer_vulkan/drawn_look_params.h: when the look is wanted (DrawnLook::Wanted), which passes
// a painted frame records (PassesFor), the ink pass's words (MakeInk), BB_DRAWN_LOOK_LINE
// (LineScaleOf) and the factor on the upscaler's extra sharpening (InkSharpen). The passes
// themselves run in drawn-look-test, which needs a Vulkan GPU.
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include "gpu/shadps4/video_core/renderer_vulkan/drawn_look_params.h"

namespace Look = Vulkan::DrawnLookParams;

namespace {
Look::Knobs KnobsOf(float strength, float ink_world, int view) {
    Look::Knobs knobs;
    knobs.strength = strength;
    knobs.ink_world = ink_world;
    knobs.view = view;
    return knobs;
}

bool SameBits(float a, float b) {
    return std::memcmp(&a, &b, sizeof(float)) == 0;
}
} // namespace

int main() {
    // Wanted: the switch, and strokes or ink lines to draw.
    static_assert(!Look::Wanted(false, 1.0f, 1.0f));
    static_assert(!Look::Wanted(true, 0.0f, 0.0f));
    static_assert(Look::Wanted(true, 0.0f, 0.35f));
    static_assert(Look::Wanted(true, 0.6f, 0.0f));
    static_assert(Look::Wanted(true, 0.6f, 0.35f));
    static_assert(!Look::Wanted(false, 0.0f, 0.0f));
    assert(!Look::Wanted(true, NAN, NAN));

    // The defaults: the look's own and the ink's.
    static_assert(Look::Knobs{}.ink_world == 0.35f && Look::Knobs{}.line_scale == 1.0f &&
                  Look::Knobs{}.view == Look::ViewOff);

    // PassesFor: strokes with a strength or in a stroke test view; the lock after the strokes
    // without a test view; ink with ink lines or in the ink page, never right before the
    // upscaler; the ink page lays no strokes.
    for (const bool late : {false, true}) {
        for (const int view : {int(Look::ViewOff), int(Look::ViewStrokes), int(Look::ViewFine),
                               int(Look::ViewInk), int(Look::ViewBold)}) {
            for (const float strength : {0.0f, 0.6f}) {
                for (const float ink : {0.0f, 0.35f}) {
                    const Look::Passes p = Look::PassesFor(KnobsOf(strength, ink, view), late);
                    const bool page = view == Look::ViewInk;
                    assert(p.strokes == (!page && (strength > 0.0f || view != Look::ViewOff)));
                    assert(p.lock == (p.strokes && view == Look::ViewOff));
                    assert(p.ink == (!late && (ink > 0.0f || page)));
                }
            }
        }
    }
    // The cases the menu gives: strokes alone, lines alone, both; the frame painted right
    // before the upscaler with lines alone records nothing.
    {
        const auto strokes = Look::PassesFor(KnobsOf(0.6f, 0.0f, Look::ViewOff), false);
        assert(strokes.strokes && strokes.lock && !strokes.ink);
        const auto lines = Look::PassesFor(KnobsOf(0.0f, 0.35f, Look::ViewOff), false);
        assert(!lines.strokes && !lines.lock && lines.ink);
        const auto both = Look::PassesFor(KnobsOf(0.6f, 0.35f, Look::ViewOff), false);
        assert(both.strokes && both.lock && both.ink);
        const auto late = Look::PassesFor(KnobsOf(0.0f, 0.35f, Look::ViewOff), true);
        assert(!late.strokes && !late.lock && !late.ink);
        const auto page = Look::PassesFor(KnobsOf(0.6f, 0.0f, Look::ViewInk), false);
        assert(!page.strokes && !page.lock && page.ink);
        // A view outside the range is clamped as Make clamps it.
        const auto high = Look::PassesFor(KnobsOf(0.0f, 0.0f, 9), false);
        assert(high.strokes && !high.lock && !high.ink);
        const auto low = Look::PassesFor(KnobsOf(0.6f, 0.0f, -2), false);
        assert(low.strokes && low.lock);
    }

    // MakeInk: ink_world, outlines and the line scale in strength, brush and characters; every
    // other word as the frame's (the block is the other passes' block).
    {
        Look::Knobs knobs = KnobsOf(0.6f, 0.35f, Look::ViewOff);
        const std::array<float, 12> inv_view{1, 0, 0, 0.3f, 0, 1, 0, 1.6f, 0, 0, 1, -1.0f};
        const std::array<float, 4> proj{1.2f, 2.1f, 1.0f, -0.1f};
        const Look::Params look =
            Look::Make(knobs, inv_view, proj, 1920, 1080, {0.25f, -0.5f}, true, true);
        const Look::Params ink = Look::MakeInk(look, 0.35f, 0.8f, 1.6f);
        assert(ink.strength == 0.35f && ink.brush == 0.8f && ink.characters == 1.6f);
        Look::Params rest = ink;
        rest.strength = look.strength;
        rest.brush = look.brush;
        rest.characters = look.characters;
        assert(std::memcmp(&rest, &look, sizeof(Look::Params)) == 0);
        assert(ink.flags == look.flags && SameBits(ink.cell_fine, look.cell_fine) &&
               SameBits(ink.cell_bold, look.cell_bold));
        // The view stays in the flags: the ink page is read from them, and draws every line at
        // weight 1 whatever ink_world is (0 included).
        knobs.view = Look::ViewInk;
        for (const float ink_world : {0.0f, 0.35f}) {
            const Look::Params page = Look::MakeInk(
                Look::Make(knobs, inv_view, proj, 1920, 1080, {0.0f, 0.0f}, true, false),
                ink_world, 0.35f, 1.0f);
            assert(Look::ViewOf(page.flags) == std::uint32_t(Look::ViewInk) &&
                   page.strength == 1.0f);
        }
        static_assert(sizeof(Look::Params) == 128);
    }

    // BB_DRAWN_LOOK_LINE: 1 without it or without a number in it, else clamped to 0.5..2.
    assert(Look::LineScaleOf(nullptr) == 1.0f);
    assert(Look::LineScaleOf("") == 1.0f && Look::LineScaleOf("bold") == 1.0f);
    assert(Look::LineScaleOf("nan") == 1.0f && Look::LineScaleOf("inf") == 1.0f);
    assert(Look::LineScaleOf("0.6") == 0.6f && Look::LineScaleOf("1.6") == 1.6f);
    assert(Look::LineScaleOf("0.1") == Look::LineScaleMin &&
           Look::LineScaleOf("9") == Look::LineScaleMax);
    assert(Look::LineScaleOf("-3") == 0.5f && Look::LineScaleOf("2") == 2.0f);
    static_assert(Look::LineScaleMin == 0.5f && Look::LineScaleMax == 2.0f);

    // InkSharpen: 1 - 0.5 x the weight of the ink lines the frame recorded, 1 on a frame without
    // them (weight 0).
    static_assert(Look::InkSharpen(0.0f) == 1.0f && Look::InkSharpen(-1.0f) == 1.0f);
    static_assert(Look::InkSharpen(1.0f) == 0.5f && Look::InkSharpen(0.5f) == 0.75f);
    static_assert(Look::InkSharpen(7.0f) == 0.5f);
    assert(std::abs(Look::InkSharpen(0.35f) - 0.825f) < 1e-6f);
    assert(Look::InkSharpen(NAN) == 1.0f);

    std::puts("PASS: drawn look rules");
    return 0;
}
