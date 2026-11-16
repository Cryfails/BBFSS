// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r51_volumetric-leak): the volumetric march's cascades (volumetric_occlusion.h): the
// knob's text, the mask in every mode (r14 kept quadrants on and off, r7, cascades left out) and
// the push word the shader takes apart. bbport (r76_sun-fog-outdoors): the defaults of both knobs,
// the gate's mask in force with and without a ray traced scene, the gate diagnostics' pure parts
// and the light's direction as the host makes it.
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <vector>
#include <cstdio>
#include <initializer_list>
#include "gpu/shadps4/video_core/renderer_vulkan/volumetric_occlusion.h"

using namespace Vulkan::VolumetricOcclusion;

int main() {
    // The knob: a whole number 0..7, else the default. bbport (r76_sun-fog-outdoors): the default
    // is 5, bits 1 and 4 (bit 2, the darkest answer of every cascade, left out); 7 is all on.
    assert(All == 7 && Default == 5 && (Default & Darkest) == 0);
    assert(Parse(nullptr) == Default && Parse("") == Default);
    assert(Parse("0") == 0 && Parse("1") == 1 && Parse("5") == 5 && Parse("7") == 7);
    assert(Parse("8") == Default && Parse("-1") == Default && Parse("3x") == Default &&
           Parse("on") == Default);

    // bbport (r76_sun-fog-outdoors): the ray traced sun gate's knob. Unset means 1 (the sun's
    // casters) with a ray traced scene and 0 (no gate) without one; "0" is off either way; 2 and 3
    // (the camera pass's geometry too) are test values.
    assert(RtGateDefault == 1);
    assert(ParseRtGate(nullptr) == 1 && ParseRtGate("") == 1);
    assert(ParseRtGate("0") == 0 && ParseRtGate("1") == 1 && ParseRtGate("2") == 2 &&
           ParseRtGate("3") == 3);
    assert(ParseRtGate("4") == 1 && ParseRtGate("on") == 1 && ParseRtGate("1x") == 1 &&
           ParseRtGate(" 1") == 1 && ParseRtGate("-1") == 1 && ParseRtGate("off") == 1);
    assert(!RtGateNamed(nullptr) && !RtGateNamed("") && !RtGateNamed("4") && !RtGateNamed("10") &&
           RtGateNamed("0") && RtGateNamed("3"));
    assert(GateInForce(ParseRtGate(nullptr), true) == 1);
    assert(GateInForce(ParseRtGate(nullptr), false) == 0);
    assert(GateInForce(ParseRtGate("0"), true) == 0 && GateInForce(ParseRtGate("0"), false) == 0);
    assert(GateInForce(ParseRtGate("3"), true) == 3 && GateInForce(ParseRtGate("2"), false) == 0);

    // bbport (r76_sun-fog-outdoors): the gate's diagnostics. Their knobs are on only as "1".
    assert(ParseOn("1") && !ParseOn(nullptr) && !ParseOn("") && !ParseOn("0") && !ParseOn("11") &&
           !ParseOn("on") && !ParseOn(" 1"));
    // The diagnostic bits lie above the 8 bits a ray takes as its instance mask.
    assert((GateDiagProbe & 0xFFu) == 0 && (GateDiagBand & 0xFFu) == 0 &&
           (GateDiagProbe & GateDiagBand) == 0 && ((3u | GateDiagProbe | GateDiagBand) & 0xFFu) == 3u);
    // The distance bands (m) as the DIAG build counts them.
    assert(GateBand(0.0f) == 1 && GateBand(4.99f) == 1 && GateBand(5.0f) == 2 &&
           GateBand(14.9f) == 2 && GateBand(15.0f) == 3 && GateBand(39.9f) == 3 &&
           GateBand(40.0f) == 4 && GateBand(149.9f) == 4 && GateBand(150.0f) == 5 &&
           GateBand(800.0f) == 5);
    // The probe's words: 5 + 5 + 1 + 3 + 64 + 1 (the centre column's surface).
    assert(GateProbeWords == 79 && GateProbeCameraOnlyAt == GateProbeShutAt + 5 &&
           GateProbeAskedAt == GateProbeCameraOnlyAt + 5 && GateProbeDirectionAt == GateProbeAskedAt + 1 &&
           GateProbeColumnAt + 2 * GateProbeSlices == GateProbeSurfaceAt &&
           GateProbeSurfaceAt + 1 == GateProbeWords);
    // The masks four to a word, instance i in byte i % 4; camera only = bit 2 without bit 1.
    {
        const std::vector<GateInstance> table{
            {1, 10, 0x05}, {2, 20, 0x06}, {3, 30, 0x07}, {4, 40, 0x02}, {5, 50, 0x0E}};
        const std::vector<std::uint32_t> words = PackGateMasks(table);
        assert(words.size() == 2 && words[0] == 0x02070605u && words[1] == 0x0Eu);
        assert(PackGateMasks({}).empty());
        assert(!GateCameraOnly(0x05) && GateCameraOnly(0x06) && !GateCameraOnly(0x07) &&
               GateCameraOnly(0x02) && GateCameraOnly(0x0E) && !GateCameraOnly(0x01));
    }
    // bbport (r76c_sun-fog-shells): the probe's words per instance, the shell rule's text and
    // tests, the gate bits, the probe cadence.
    {
        // Ordered bits compare as the floats; a minimum as the largest complement; zeros are empty.
        const float values[] = {-500.0f, -5.0f, -0.25f, 0.0f, 0.25f, 5.0f, 500.0f};
        for (std::size_t i = 0; i + 1 < sizeof(values) / sizeof(values[0]); ++i) {
            assert(GateOrdered(values[i]) < GateOrdered(values[i + 1]));
            assert(GateFromOrdered(GateOrdered(values[i])) == values[i]);
            assert(GateMinOrdered(~GateOrdered(values[i])) == values[i]);
        }
        assert(GateMinFloat(0) == -1.0f && GateMinOrdered(0) == 0.0f);
        assert(GateMinFloat(~std::bit_cast<std::uint32_t>(27.5f)) == 27.5f &&
               GateMaxFloat(std::bit_cast<std::uint32_t>(27.5f)) == 27.5f);
        assert(GateStatWords == 10 && GateStatBytes == GateProbeInstancesMost * 40);
        // The most shut cells first, ties by instance, empty ones left out, at most `most`.
        std::vector<std::uint32_t> stats(5 * GateStatWords, 0u);
        stats[0 * GateStatWords] = 7;
        stats[1 * GateStatWords] = 0;
        stats[2 * GateStatWords] = 9;
        stats[3 * GateStatWords] = 7;
        stats[4 * GateStatWords] = 1;
        assert((GateTopInstances(stats, 8) == std::vector<std::uint32_t>{2, 0, 3, 4}));
        assert((GateTopInstances(stats, 2) == std::vector<std::uint32_t>{2, 0}));
        assert(GateTopInstances({}, 8).empty());
    }
    {
        // The shell rule's text.
        assert(!ParseGateShells(nullptr).on && !ParseGateShells(nullptr).bad);
        assert(!ParseGateShells("").on && !ParseGateShells("").bad);
        const GateShellRule all = ParseGateShells("far,notest,nocull,1a2B:3c,ff:*");
        assert(all.on && !all.bad && all.far_depth && all.no_test && all.no_cull && all.pairs == 2 &&
               all.vs[0] == 0x1a2b && all.ps[0] == 0x3c && all.vs[1] == 0xff && all.ps[1] == 0);
        // "+" separates as "," does (the slot workers split env values at commas)
        const GateShellRule plus = ParseGateShells("far+notest+1a2b:*");
        assert(plus.on && !plus.bad && plus.far_depth && plus.no_test && !plus.no_cull &&
               plus.pairs == 1 && plus.vs[0] == 0x1a2b && plus.ps[0] == 0);
        assert(ParseGateShells("far+").bad && ParseGateShells("+far").bad &&
               ParseGateShells("far,+notest").bad);
        for (const char* wrong : {"bogus", "far,", ",far", "far,,notest", "Far", " far", "1a2b",
                                  "1a2b:", ":3c", "0:3c", "1a:0", "g1:2", "1:2:3",
                                  "11111111111111111:1"}) {
            const GateShellRule rule = ParseGateShells(wrong);
            assert(!rule.on && rule.bad);
        }
        assert(ParseGateShells("1:1,2:2,3:3,4:4,5:5,6:6,7:7,8:8").pairs == 8);
        assert(ParseGateShells("1:1,2:2,3:3,4:4,5:5,6:6,7:7,8:8,9:9").bad);
        // Its tests on described draws.
        GateCapture c;
        c.known = true;
        c.vs = 0x1a2b;
        c.ps = 0x3c;
        c.depth = GateDepthBits(true, true, 3);
        c.raster = GateRasterBits(false, true, false, true, true);
        assert(GateDepthFunc(c.depth) == 3 && c.raster == (GateCullBack | GateZclip | GateDepthClamp));
        assert(!GateFarDepth(c));
        assert(GateShell(ParseGateShells("1a2b:3c"), c) && GateShell(ParseGateShells("1a2b:*"), c));
        assert(!GateShell(ParseGateShells("1a2b:3d"), c) && !GateShell(ParseGateShells("far"), c) &&
               !GateShell(ParseGateShells("notest"), c) && !GateShell(ParseGateShells("nocull"), c));
        GateCapture sky = c;
        sky.dmin = 1.0f;
        sky.dmax = 1.0f;
        assert(GateFarDepth(sky) && GateShell(ParseGateShells("far"), sky));
        sky = c;
        sky.zmin = 0.9995f;
        sky.zmax = 1.0f;
        assert(GateFarDepth(sky));
        sky.raster = GateRasterBits(false, true, false, true, false); // clamp off: bounds unused
        assert(!GateFarDepth(sky));
        sky = c;
        sky.depth = GateDepthBits(true, true, 7);
        assert(GateShell(ParseGateShells("notest"), sky));
        sky.depth = GateDepthBits(false, true, 3);
        assert(GateShell(ParseGateShells("notest"), sky));
        sky.raster = GateRasterBits(false, false, true, true, true);
        assert(GateShell(ParseGateShells("nocull"), sky));
        GateCapture unknown = sky;
        unknown.known = false;
        assert(!GateShell(ParseGateShells("far,notest,nocull"), unknown));
        assert(!GateShell(ParseGateShells("bogus"), sky));
        // The gate bits: other rays see the same instances; the gate traces only the new bits.
        assert(GateSolidBits(0x07, false) == 0x60 && GateSolidBits(0x05, false) == 0x20 &&
               GateSolidBits(0x06, false) == 0x40 && GateSolidBits(0x04, false) == 0 &&
               GateSolidBits(0x07, true) == 0 && GateSolidBits(0x10, false) == 0);
        assert(GateRayMask(1, true) == 0x20 && GateRayMask(2, true) == 0x40 &&
               GateRayMask(3, true) == 0x60 && GateRayMask(0, true) == 0);
        assert(GateRayMask(1, false) == 1 && GateRayMask(3, false) == 3 && GateRayMask(0, false) == 0);
        for (std::uint32_t record : {0x01u, 0x02u, 0x03u, 0x05u, 0x06u, 0x07u, 0x0Fu}) {
            for (std::uint32_t knob : {1u, 2u, 3u}) {
                // without a shell the gate hits a record with the rule exactly when without it
                const bool before = (record & knob) != 0;
                const bool after = ((record | GateSolidBits(record, false)) & GateRayMask(knob, true)) != 0;
                assert(before == after);
                assert(((record | GateSolidBits(record, true)) & GateRayMask(knob, true)) == 0);
                for (std::uint32_t other : {0x01u, 0x04u, 0x0Cu, 0xEFu, 0xFFu}) {
                    assert((((record | GateSolidBits(record, false)) & other) != 0) ==
                           ((record & other) != 0));
                }
            }
        }
        // The probe cadence.
        assert(ParseProbeEvery(nullptr) == 600 && ParseProbeEvery("") == 600 &&
               ParseProbeEvery("120") == 120 && ParseProbeEvery("30") == 30 &&
               ParseProbeEvery("6000") == 6000 && ParseProbeEvery("29") == 600 &&
               ParseProbeEvery("6001") == 600 && ParseProbeEvery("12x") == 600 &&
               ParseProbeEvery("-120") == 600 && ParseProbeEvery(" 120") == 600);
    }
    // The light's direction as volumetric_rt_gate.comp's prepare() makes it. A projection P that
    // swaps z and w (inverse in rows 0-15) and a light matrix L (rows 16-31) chosen so that L P has
    // the rows a (0, 1, 0), b (0, 0, 1), z (1, 0, 0): a x b = (1, 0, 0) points along z, so the
    // direction toward the light is (-1, 0, 0) in view space.
    {
        const std::array<float, 32> c{0.5f, 0, 0, 0, 0, 0.25f, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0,
                                      0, 0.25f, 0, 0, 0, 0, 0, 1, 0.5f, 0, 0.5f, 0, 0, 0, 1, 0};
        std::array<float, 3> d{};
        assert(LightDirection(c, d));
        assert(std::fabs(d[0] + 1.0f) < 1e-6f && std::fabs(d[1]) < 1e-6f && std::fabs(d[2]) < 1e-6f);
        // A camera turned 90 degrees about y: view (-1, 0, 0) is world (0, 0, 1): level, azimuth 0.
        const std::array<float, 12> turned{0, 0, 1, 7, 0, 1, 0, 8, -1, 0, 0, 9};
        const SunLight light = MakeSunLight(c, turned, true);
        assert(light.valid && std::fabs(light.world[2] - 1.0f) < 1e-6f);
        const auto angles = ElevationAzimuth(light.world);
        assert(std::fabs(angles[0]) < 1e-4f && std::fabs(angles[1]) < 1e-4f);
        // Without the camera: the view direction only, not valid.
        const SunLight blind = MakeSunLight(c, turned, false);
        assert(!blind.valid && std::fabs(blind.view[0] + 1.0f) < 1e-6f);
        // No inverse projection (all zero): no direction.
        assert(!LightDirection(std::array<float, 32>{}, d));
        // Straight up is 90 degrees; +x is azimuth 90; the angle between them 90.
        assert(std::fabs(ElevationAzimuth({0, 1, 0})[0] - 90.0f) < 1e-4f);
        assert(std::fabs(ElevationAzimuth({1, 0, 0})[1] - 90.0f) < 1e-4f);
        assert(std::fabs(ElevationAzimuth({-1, 0, 0})[1] - 270.0f) < 1e-4f);
        assert(std::fabs(AngleDeg({1, 0, 0}, {0, 1, 0}) - 90.0f) < 1e-4f);
        assert(AngleDeg({1, 0, 0}, {0, 0, 0}) == 180.0f);
    }

    // Bit 1 clear: the first `count` cascades, as before r51, whatever the quadrants hold.
    for (std::uint32_t count = 0; count <= 5; ++count) {
        const std::uint32_t first = count >= 4 ? 0xFu : (1u << count) - 1u;
        for (std::uint32_t m = 0; m < 16; ++m) {
            for (const bool tracked : {false, true}) {
                const Quadrants q{.count = count, .drawn = m, .spread = (m & 1u) != 0,
                                  .held = m ^ 5u, .held_lost = m ^ 6u, .kept_tracked = tracked,
                                  .kept_drawn = m ^ 3u, .kept_cleared = m, .kept_blank = m ^ 9u};
                for (const std::uint32_t bits : {0u, 2u, 4u, 6u}) {
                    assert(Valid(q, bits) == first);
                }
                // Bit 1 set: never a cascade the count leaves out.
                assert((Valid(q, All) & ~first) == 0);
            }
        }
    }

    // r14 off (the game clears the whole atlas every frame): the cascades with draws. The log's
    // frames: c0 never drawn, c1 every frame, c2 and c3 now and then.
    assert(Valid({.drawn = 0xEu}, All) == 0xEu);
    assert(Valid({.drawn = 0x2u}, All) == 0x2u);
    // No casters anywhere (an interior the game draws no sun casters for): nothing to read.
    assert(Valid({.drawn = 0}, All) == 0);
    // Cascades left out from c2 on (ray traced sun): not read, drawn or not.
    assert(Valid({.count = 2, .drawn = 0xEu}, All) == 0x2u);
    // r7 (BB_SUN_CASCADE_EVERY): a kept cascade has no draws this frame and holds its depth.
    assert(Valid({.drawn = 0x2u, .held = 0xCu}, All) == 0xEu);
    // r7 lost c3's kept depth (the atlas image changed, a whole clear it could not narrow, an
    // indirect draw): stale, cleared or owed a clear; confirmed stays set. Not read unless drawn.
    assert(Valid({.drawn = 0x2u, .held = 0xCu, .held_lost = 0x8u}, All) == 0x6u);
    assert(Valid({.drawn = 0xAu, .held = 0xCu, .held_lost = 0xCu}, All) == 0xAu);
    // A draw across quadrants or without a single viewport: all four, as r14 counts it.
    assert(Valid({.drawn = 0x2u, .spread = true}, All) == 0xFu);
    assert(Valid({.count = 2, .spread = true}, All) == 0x3u);

    // r14 on, the user's log ("quadrant clears by cascade 0 600 75 75; kept 600 0 525 525"):
    // a frame drawing c1 only. c1 cleared before its first draw; c0 blank since the mode began;
    // c2 and c3 keep their last drawing.
    const Quadrants kept{.kept_tracked = true, .kept_drawn = 0x2u, .kept_cleared = 0x2u, .kept_blank = 0x1u};
    assert(Valid(kept, All) == 0xEu);
    // r14's record wins over the frame's draws (it holds the atlas frame; the r19 path may not
    // have counted them).
    assert(Valid({.drawn = 0xFu, .spread = true, .held = 0xFu, .kept_tracked = true,
                  .kept_drawn = 0x2u, .kept_cleared = 0x2u, .kept_blank = 0x1u}, All) == 0xEu);
    // r14 found the kept depth untrustworthy within its atlas frame (SunKeepBeforePass: all four
    // cleared again, drawn reset since r51): only the draws after that hold casters.
    assert(Valid({.kept_tracked = true, .kept_drawn = 0x4u, .kept_cleared = 0xFu, .kept_blank = 0x1u}, All) == 0x4u);
    // A frame drawing c1, c2 and c3.
    assert(Valid({.kept_tracked = true, .kept_drawn = 0xEu, .kept_cleared = 0xEu, .kept_blank = 0x1u}, All) == 0xEu);
    // c3 kept too long (cleared with this pass, no draw): only the clear value.
    assert(Valid({.kept_tracked = true, .kept_drawn = 0x2u, .kept_cleared = 0xAu, .kept_blank = 0x1u}, All) == 0x6u);
    // An owed clear counts as cleared (SunKeepInPass: pending is always within cleared).
    assert(Valid({.kept_tracked = true, .kept_drawn = 0x2u, .kept_cleared = 0x6u, .kept_blank = 0x1u}, All) == 0xAu);
    // The atlas cleared whole in the mode (the first clear, a DB clear draw, ...): cleared 0xF,
    // only this atlas frame's draws hold casters.
    assert(Valid({.kept_tracked = true, .kept_drawn = 0x2u, .kept_cleared = 0xFu, .kept_blank = 0}, All) == 0x2u);
    // A quadrant blank at the start and still undrawn: not read.
    assert(Valid({.kept_tracked = true, .kept_drawn = 0x2u, .kept_cleared = 0x2u, .kept_blank = 0xDu}, All) == 0x2u);
    // A blank quadrant drawn again: read.
    assert(Valid({.kept_tracked = true, .kept_drawn = 0x3u, .kept_cleared = 0x3u, .kept_blank = 0x1u}, All) == 0xFu);

    // The push word: count (at most 4) in bits 0-3, the mask in 8-11, the knob in 16-23.
    assert(Pack(4, 0xEu, 7) == (4u | 0xE00u | 0x70000u));
    assert(Pack(9, 0x1Fu, 0x1FFu) == (4u | 0xF00u | 0xFF0000u));
    assert(Pack(0, 0, 0) == 0);
    const std::uint32_t word = Pack(3, Valid({.count = 3, .drawn = 0xEu}, 5), 5);
    assert((word & 15u) == 3 && ((word >> 8) & 15u) == 0x6u && ((word >> 16) & Darkest) == 0 &&
           ((word >> 16) & Robust) != 0);

    std::printf("volumetric occlusion: all checks passed\n");
    return 0;
}
