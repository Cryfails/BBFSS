// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100_blood-sheen, r100d_blood-sheen-gbuffer): the blood sheen's knobs, draw key, albedo
// rule and wet film (blood_sheen.h).
// Pure: no Vulkan. Built and run by engine/build.sh --test and the CMake target blood-sheen-test.
#undef NDEBUG
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include "gpu/shadps4/video_core/renderer_vulkan/blood_sheen.h"

using namespace Vulkan::BloodSheenRules;

namespace {
bool Near(double a, double b, double eps = 1e-5) {
    return std::abs(a - b) <= eps;
}
} // namespace

int main() {
    // a. BB_BLOOD_SHEEN: off unless a strength above 0 or "show"; numbers put into 0.25..4.
    assert(ReadStrength(nullptr).strength == 0.0f);
    assert(ReadStrength("").strength == 0.0f);
    assert(ReadStrength("0").strength == 0.0f);
    assert(ReadStrength("-1").strength == 0.0f);
    assert(ReadStrength("yes").strength == 0.0f);
    assert(ReadStrength("1x").strength == 0.0f);
    assert(ReadStrength("nan").strength == 0.0f);
    assert(ReadStrength("1").strength == 1.0f && !ReadStrength("1").show);
    assert(ReadStrength(" 2 ").strength == 2.0f);
    assert(ReadStrength("0.1").strength == MinStrength);
    assert(ReadStrength("9").strength == MaxStrength);
    const Knobs show = ReadStrength("show");
    assert(show.strength == 1.0f && show.show);
    assert(ReadStrength("shows").strength == 0.0f && ReadStrength("sh").strength == 0.0f);

    // b. BB_BLOOD_SHEEN_DRAW: no default (r100's 1ea84d9a:bd1d09f0 is gone); a pair, or a pair and
    // an index count.
    {
        const Knobs none = Read("1", nullptr, nullptr);
        assert(none.key_count == 0 && none.keys_bad == 0 && !CanPick(none));
        assert(!Matches(none, 0x1ea84d9a, 0xbd1d09f0, 1266));
        const Knobs pair = Read("1", "c829ee58:dbb222eb", nullptr);
        assert(pair.key_count == 1 && pair.keys[0].indices == 0 && CanPick(pair));
        assert(Matches(pair, 0xc829ee58, 0xdbb222eb, 468) && Matches(pair, 0xc829ee58, 0xdbb222eb, 117870));
        assert(!Matches(pair, 0x7620368b, 0x8aba0ecd, 468));
        const Knobs counted = Read("1", "0xC829EE58:dbb222eb:468 , 1:2", nullptr);
        assert(counted.key_count == 2 && counted.keys_bad == 0);
        assert(counted.keys[0].vs == 0xc829ee58ull && counted.keys[0].indices == 468);
        assert(Matches(counted, 0xc829ee58, 0xdbb222eb, 468) && !Matches(counted, 0xc829ee58, 0xdbb222eb, 469));
        assert(Matches(counted, 1, 2, 7));
        const Knobs bad = Read("1", "zz:1;12;1:2:0;1:2:x;1:2:3:4;1:2:99999999999", nullptr);
        assert(bad.key_count == 0 && bad.keys_bad == 6);
        const Knobs many = Read("1", "1:1;2:2;3:3;4:4;5:5", nullptr);
        assert(many.key_count == MaxKeys && many.keys_bad == 1);
        assert(Read("1", " ; ", nullptr).key_count == 0);
        assert(Read("1", "12345678901234567:1", nullptr).keys_bad == 1); // 17 digits
    }

    // c. BB_BLOOD_SHEEN_RULE: "draw" (default), "albedo" with its two numbers.
    {
        const Knobs d = Read("1", nullptr, nullptr);
        assert(d.rule == Rule::Draw && !d.rule_bad);
        assert(Read("1", nullptr, " draw ").rule == Rule::Draw && !Read("1", nullptr, "draw").rule_bad);
        const Knobs a = Read("1", nullptr, "albedo");
        assert(a.rule == Rule::Albedo && a.ratio == DefaultRatio && a.lum_max == DefaultLumMax && CanPick(a));
        const Knobs b = Read("1", nullptr, "albedo:3");
        assert(b.rule == Rule::Albedo && b.ratio == 3.0f && b.lum_max == DefaultLumMax);
        const Knobs c = Read("1", nullptr, "albedo:1.5:0.1");
        assert(c.rule == Rule::Albedo && c.ratio == 1.5f && Near(c.lum_max, 0.1));
        for (const char* wrong : {"albedos", "albedo:", "albedo:0.5", "albedo:17", "albedo:2:0", "albedo:2:2",
                                  "albedo:2:0.1:3", "albedo:x", "red", "drawn"}) {
            const Knobs w = Read("1", nullptr, wrong);
            assert(w.rule == Rule::Draw && w.rule_bad && w.ratio == DefaultRatio);
        }
    }

    // d. The albedo rule: dark red blood passes; grey stone, brown dirt, bright red cloth do not.
    {
        const Knobs k = Read("1", nullptr, "albedo");
        assert(DarkRed(k, 0.045f, 0.003f, 0.003f));   // sRGB about (60, 10, 10)
        assert(DarkRed(k, 0.02f, 0.008f, 0.005f));
        assert(!DarkRed(k, 0.05f, 0.05f, 0.05f));     // grey
        assert(!DarkRed(k, 0.10f, 0.06f, 0.03f));     // brown: red under twice the green
        assert(!DarkRed(k, 0.60f, 0.02f, 0.02f));     // bright red: luminance over 0.06
        assert(!DarkRed(k, 0.005f, 0.0f, 0.0f));      // near black: red under RedMin
        assert(DarkRed(k, 0.008f, 0.004f, 0.004f) && !DarkRed(k, 0.008f, 0.0041f, 0.0f));
        const Knobs loose = Read("1", nullptr, "albedo:1.5:0.1");
        assert(DarkRed(loose, 0.10f, 0.06f, 0.03f));  // the brown passes the looser rule
    }

    // e. The wet film (r100h_sheen-liquid): the gloss goes TO the film's (a glossier ground comes down), the
    // root is never lowered; strength 1 reaches gloss 0.86 and root 0.45 (r100i_sheen-blood-tint; the root
    // before the tint); above 1 the root grows with the square root, at most 0.65; below 1 a share of the way;
    // a weight below 1 is a share again.
    {
        const Film f = Wet(0.3f, 0.1f, 1.0f);
        assert(Near(f.gloss, WetGloss) && Near(f.root, WetSpecRoot));
        const Film keep = Wet(0.95f, 0.7f, 1.0f);
        assert(Near(keep.gloss, 0.86) && Near(keep.root, 0.7)); // the gloss comes down, the root is kept
        assert(Near(Wet(0.5f, 0.0f, 1.0f, 0.5f).gloss, 0.5 + 0.36 * 0.5) && Near(Wet(0.5f, 0.0f, 1.0f, 0.0f).gloss, 0.5));
        assert(Near(Wet(0.95f, 0.0f, 1.0f, 0.5f).gloss, 0.95 - 0.09 * 0.5));
        const Film half = Wet(0.3f, 0.1f, 0.5f);
        assert(Near(half.gloss, 0.58) && Near(half.root, 0.275));
        assert(Near(Wet(0.0f, 0.0f, 4.0f).root, SpecRootMax) &&
               Near(Wet(0.0f, 0.0f, 2.0f).root, WetSpecRoot * std::sqrt(2.0)));
        assert(Near(WetGloss, 0.86) && Near(WetSpecRoot, 0.45) && Near(SpecRootMax, 0.65));
        assert(Near(Wet(0.0f, 0.0f, 2.0f).root, 0.45 * std::sqrt(2.0)) && Wet(0.0f, 0.0f, 2.0f).root < SpecRootMax);
        assert(Near(Wet(0.0f, 0.0f, 4.0f).gloss, WetGloss));
        // bbport (r100i_sheen-blood-tint): the tint. Intensity kept (f0 = root squared) is red 0.6..0.8 of the
        // untinted film, green and blue far less; red is never lowered; green and blue come down on a pale ground.
        assert(Near(TintR, 0.85, 1e-6) && Near(TintG, 0.35, 1e-6) && Near(TintB, 0.30, 1e-6));
        assert(TintR * TintR >= 0.6f && TintR * TintR <= 0.8f && TintG * TintG < 0.2f && TintB * TintB < 0.2f);
        {
            const SpecRoot s = WetSpec(0.0f, 0.0f, 0.0f, 1.0f);
            assert(Near(s.r, 0.45 * 0.85, 1e-4) && Near(s.g, 0.45 * 0.35, 1e-4) && Near(s.b, 0.45 * 0.30, 1e-4));
            assert(s.r > s.g && s.g >= s.b);
            const SpecRoot s2 = WetSpec(0.0f, 0.0f, 0.0f, 2.0f);        // brighter at strength 2
            assert(s2.r > s.r && s2.g > s.g && Near(s2.r, 0.45 * std::sqrt(2.0) * 0.85, 1e-4));
            const SpecRoot hi = WetSpec(0.7f, 0.5f, 0.5f, 1.0f);        // a bright grey ground: red kept, g and b down
            assert(Near(hi.r, 0.7, 1e-6) && Near(hi.g, 0.45 * 0.35, 1e-4) && Near(hi.b, 0.45 * 0.30, 1e-4));
            const SpecRoot rim = WetSpec(0.2f, 0.2f, 0.2f, 1.0f, 0.5f); // half weight: half the way
            assert(Near(rim.g, 0.2 + (0.45 * 0.35 - 0.2) * 0.5, 1e-4) && rim.r > 0.2f);
            const SpecRoot none = WetSpec(0.2f, 0.2f, 0.2f, 1.0f, 0.0f); // weight 0: untouched
            assert(Near(none.r, 0.2, 1e-6) && Near(none.g, 0.2, 1e-6) && Near(none.b, 0.2, 1e-6));
            assert(Near(WetSpec(0.3f, 0.3f, 0.3f, 0.0f).g, 0.3, 1e-6));    // strength 0: untouched
        }
    }

    // f. The push block and the flags as the shader reads them.
    {
        static_assert(sizeof(Push) == 8 * 4);
        static_assert(offsetof(Push, strength) == 8 && offsetof(Push, ratio) == 12);
        static_assert(offsetof(Push, lum_max) == 16 && offsetof(Push, red_min) == 20);
        static_assert(offsetof(Push, flags) == 24 && offsetof(Push, darken) == 28);
        assert(Flags(Read("show", "1:2", "albedo"), 1) == (FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo));
        assert(Flags(Read("1", nullptr, nullptr), 2) == 0u);
        assert(Flags(Read("1", "1:2", nullptr), 3) == (FlagSlot | FlagKeyed));
        assert((Flags(Read("show", "1:2", "albedo"), 1) & FlagClear) == 0u); // only SNAPSHOT adds it
    }

    // g. bbport (r100e_blood-sheen-visible): BB_BLOOD_SHEEN_DARKEN and the dimming's arithmetic.
    {
        assert(ReadDarken(nullptr) == DefaultDarken && ReadDarken("") == DefaultDarken);
        assert(ReadDarken("0") == 0.0f && ReadDarken("1") == 1.0f && ReadDarken(" 0.25") == 0.25f);
        assert(ReadDarken("7") == 1.0f && ReadDarken("-3") == 0.0f);
        assert(ReadDarken("x") == DefaultDarken && ReadDarken("0.5x") == DefaultDarken);
        assert(ReadDarken("nan") == DefaultDarken);
        assert(Read("1", nullptr, nullptr).darken == DefaultDarken); // Load() sets it from its own knob
        // a dark pixel gets the whole share, a bright one none, in between smoothly
        assert(Near(DimShare(0.02f, 0.5f), 0.5) && Near(DimShare(0.1f, 0.5f), 0.5));
        assert(Near(DimShare(0.6f, 0.5f), 0.0) && Near(DimShare(5.0f, 1.0f), 0.0));
        assert(Near(DimShare(0.35f, 1.0f), 0.5));
        assert(DimShare(0.2f, 1.0f) > DimShare(0.4f, 1.0f) && DimShare(0.3f, 0.0f) == 0.0f);
        // the pool's dim diffuse (luminance 0.02) at strength 1 and darken 0.5 loses a quarter of its
        // red and 30% of its green and blue
        const double share = DimShare(0.02f, 0.5f);
        assert(Near(1.0 - share + share * DarkenRed, 0.85) && Near(1.0 - share + share * DarkenOther, 0.7));
        assert(Flags(Read("1", nullptr, nullptr), 0) == 0u); // the flags the engine adds (normal) are its own
        assert((FlagNormal & (FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear)) == 0u);
        // h. bbport (r100g_sheen-sheets): the level share: all the way (1) deep in the pool, EDGE (0.3) at its
        // rim, none for a pixel that does not face up (a wall); the strength scales it up to 1.
        assert(Near(LevelShare(1.0f, 1.0f, 1.0f), 1.0) && Near(LevelShare(0.6f, 1.0f, 1.0f), 1.0));
        assert(LevelShare(0.35f, 1.0f, 1.0f) == 0.0f && LevelShare(0.0f, 1.0f, 1.0f) == 0.0f && LevelShare(-1.0f, 1.0f, 1.0f) == 0.0f);
        assert(Near(LevelShare(0.475f, 1.0f, 1.0f), 0.5));                 // the up gate's middle
        assert(Near(LevelShare(1.0f, 0.0f, 1.0f), 0.3) && Near(LevelShare(1.0f, 0.25f, 1.0f), 0.3));
        assert(Near(LevelShare(1.0f, 0.65f, 1.0f), 1.0) && Near(LevelShare(1.0f, 0.45f, 1.0f), 0.3 + 0.7 * 0.5));
        assert(Near(LevelShare(1.0f, 1.0f, 0.5f), 0.5) && Near(LevelShare(1.0f, 1.0f, 3.0f), 1.0));
        assert(LevelShare(1.0f, 1.0f, 0.0f) == 0.0f);
        for (float y = 0.0f; y < 1.0f; y += 0.01f) { // never decreases as the pixel faces up more
            assert(LevelShare(y + 0.01f, 0.8f, 1.0f) >= LevelShare(y, 0.8f, 1.0f));
        }
        for (float f = 0.0f; f < 1.0f; f += 0.01f) { // never decreases as more of its surroundings is pool
            assert(LevelShare(1.0f, f + 0.01f, 1.0f) >= LevelShare(1.0f, f, 1.0f));
        }
        // i. bbport (r100h_sheen-liquid): the 24-tap share and the filling of the pool's gaps.
        assert(Near(PoolShareOf(8, 8, 8), 1.0) && Near(PoolShareOf(0, 0, 0), 0.0) && Near(PoolShareOf(4, 6, 8), 0.75));
        assert(FillWeight(1.0f, 1.0f, 8) == 1.0f && FillWeight(0.5f, 1.0f, 8) == 0.0f && FillWeight(0.2f, 1.0f, 8) == 0.0f);
        assert(Near(FillWeight(0.65f, 1.0f, 8), 0.5) && Near(FillWeight(0.8f, 1.0f, 2), 1.0));
        assert(FillWeight(1.0f, 1.0f, 1) == 0.0f && FillWeight(1.0f, 1.0f, 0) == 0.0f); // the early out
        assert(FillWeight(1.0f, 0.35f, 8) == 0.0f && FillWeight(1.0f, -1.0f, 8) == 0.0f);  // a wall or a side
        assert(Near(FillWeight(1.0f, 0.475f, 8), 0.5));                                      // the up gate's middle
        assert(Near(FilledLevelShare(1.0f, 1.0f, 1.0f, 8), 1.0) && FilledLevelShare(1.0f, 1.0f, 0.0f, 8) == 0.0f);
        // r129b_sheen-no-glow: the rim levels by fill squared x rim share (0.5 x 0.5 x 0.35 = 0.0875 at share 0.65)
        assert(Near(FilledLevelShare(1.0f, 0.65f, 1.0f, 8), 0.0875) && Near(FilledLevelShare(1.0f, 1.0f, 0.5f, 8), 0.5));
        for (float f = 0.0f; f < 1.0f; f += 0.01f) { // never decreases as more of its surroundings is pool
            assert(FilledLevelShare(1.0f, f + 0.01f, 1.0f, 8) >= FilledLevelShare(1.0f, f, 1.0f, 8));
        }
        // j. bbport (r100j_sheen-clean-rim): the rim's share of the body's specular. A pixel that passes the
        // albedo rule is the body (1); a gap-fill pixel gets 0.35 (r100k) at the rim and in the fill's range up to
        // FILL_HI, then climbs smoothly to 1 at share 1; it never decreases with the share, never steps.
        assert(Near(FillSpec, 0.35, 1e-6));
        assert(RimSpecShare(false, 0.0f) == 1.0f && RimSpecShare(false, 0.6f) == 1.0f && RimSpecShare(false, 1.0f) == 1.0f);
        assert(Near(RimSpecShare(true, 0.5f), 0.35) && Near(RimSpecShare(true, 0.65f), 0.35) && Near(RimSpecShare(true, 0.8f), 0.35));
        assert(Near(RimSpecShare(true, 0.9f), 0.675) && Near(RimSpecShare(true, 1.0f), 1.0));
        for (float f = 0.0f; f < 1.0f; f += 0.005f) {
            const float a = RimSpecShare(true, f), b = RimSpecShare(true, f + 0.005f);
            assert(b >= a && b - a < 0.03f && a >= 0.35f - 1e-6f && b <= 1.0f + 1e-6f);
        }
        {
            // the rim: a gap pixel at share 0.8, full fill weight (up 1), strength 1: tint and gloss 0.35 of the body's (r100k).
            const float fill = FillWeight(0.8f, 1.0f, 8);
            const float k = RimSpecShare(true, 0.8f);
            const SpecRoot body = WetSpec(0.2f, 0.2f, 0.2f, 1.0f);
            const SpecRoot rim = WetSpec(0.2f, 0.2f, 0.2f, 1.0f, fill * k);
            assert(Near(fill, 1.0) && Near(k, 0.35));
            assert(Near(rim.g, 0.2 + (body.g - 0.2) * 0.35, 1e-4) && Near(rim.b, 0.2 + (body.b - 0.2) * 0.35, 1e-4));
            assert(rim.r >= 0.2f && Near(Wet(0.3f, 0.2f, 1.0f, fill * k).gloss, 0.3 + (WetGloss - 0.3) * 0.35, 1e-4));
            // deep inside (share 1) a gap pixel is the body exactly; strength 2: the rim stays at half of its body.
            const SpecRoot deep = WetSpec(0.2f, 0.2f, 0.2f, 1.0f, FillWeight(1.0f, 1.0f, 8) * RimSpecShare(true, 1.0f));
            assert(Near(deep.g, body.g, 1e-6) && Near(deep.b, body.b, 1e-6) && Near(deep.r, body.r, 1e-6));
            const SpecRoot body2 = WetSpec(0.0f, 0.0f, 0.0f, 2.0f);
            const SpecRoot rim2 = WetSpec(0.0f, 0.0f, 0.0f, 2.0f, 0.5f);
            assert(Near(rim2.g, body2.g * 0.5, 1e-4) && Near(rim2.r, body2.r * 0.5, 1e-4));
        }
        // k. bbport (r100k_sheen-no-hot-spot): the rim's squared falloff and the luminance ceiling.
        assert(Near(PeakDefault, 6.0, 1e-6) && Near(PeakKnee, 0.5, 1e-6)); // r129b: 6 times the dry scene's reference
        assert(SpecWeight(0.6f, 1.0f, false, 0.7f) == 0.6f && SpecWeight(1.0f, 1.0f, false, 0.0f) == 1.0f);
        assert(Near(SpecWeight(0.5f, 0.5f, true, 0.65f), 0.5 * 0.5 * 0.35));        // half fill at the rim: 0.0875
        assert(Near(SpecWeight(1.0f, 1.0f, true, 0.8f), 0.35));                      // full fill at the rim: the cap
        assert(Near(SpecWeight(1.0f, 1.0f, true, 1.0f), 1.0));                       // deep inside: the body
        for (float share = 0.0f; share <= 0.8f; share += 0.01f) {                  // the rim never above the cap
            for (float wet = 0.0f; wet <= 1.0f; wet += 0.1f) {
                assert(SpecWeight(wet, wet, true, share) <= 0.35f * wet + 1e-6f);
                assert(SpecWeight(wet, wet, true, share) <= SpecWeight(wet, 1.0f, false, share) + 1e-6f);
            }
        }
        for (float wet = 0.0f; wet < 1.0f; wet += 0.01f) {                         // never decreases with the fill weight
            assert(SpecWeight(wet + 0.01f, wet + 0.01f, true, 0.7f) >= SpecWeight(wet, wet, true, 0.7f));
        }
        assert(PeakRoll(0.0f, 0.7f) == 0.0f && PeakRoll(0.1f, 0.7f) == 0.1f && PeakRoll(0.35f, 0.7f) == 0.35f);
        assert(Near(PeakRoll(0.36f, 0.7f), 0.36, 2e-3));                            // slope 1 at the knee: no step
        for (float l = 0.0f; l < 40.0f; l += 0.01f) {
            const float a = PeakRoll(l, 0.7f), b = PeakRoll(l + 0.01f, 0.7f);
            assert(b >= a && b - a <= 0.01f + 1e-6f && a <= 0.7f + 1e-6f && a <= l + 1e-6f);
        }
        assert(PeakRoll(1.0e4f, 0.7f) <= 0.7f + 1e-6f && PeakRoll(1.0e4f, 0.7f) > 0.69f);
        assert(PeakRoll(5.0f, 0.7f) < 0.7f && PeakRoll(5.0f, 0.7f) > 0.69f);       // a hot spot of luminance 5 reads 0.7
        assert(PeakRoll(0.5f, 0.7f) > 0.45f && PeakRoll(0.5f, 0.7f) < 0.5f);       // a bright sheet is only touched a little
        assert(ReadPeak(nullptr) == PeakDefault && ReadPeak("") == PeakDefault && ReadPeak("x") == PeakDefault);
        assert(ReadPeak("0") == 0.0f && ReadPeak("1.5") == 1.5f && ReadPeak(" 2") == 2.0f);
        assert(ReadPeak("99") == MaxPeak && ReadPeak("-1") == 0.0f && ReadPeak("0.5x") == PeakDefault);
        assert(ReadPeak("nan") == PeakDefault && ReadPeak("inf") == PeakDefault);
    }

    // bbport (r128d_lrt-sheen-interior): ReadUsable, the ini strength and the default pick.
    {
        // neither draw nor rule set: the pool's draw and the albedo rule
        const Knobs d = ReadUsable("1", nullptr, nullptr, 0.0f);
        assert(d.strength == 1.0f && d.key_count == 1 && d.keys[0].vs == 0xc829ee58ull &&
               d.keys[0].ps == 0xdbb222ebull && d.keys[0].indices == 0 && d.keys_bad == 0);
        assert(d.rule == Rule::Albedo && !d.rule_bad && d.default_pick && !d.from_ini && CanPick(d));
        assert(Flags(d, 0) == (FlagKeyed | FlagRuleAlbedo));
        // one of them set, even empty: exactly Read
        const Knobs e = ReadUsable("1", "", nullptr, 0.0f);
        assert(e.key_count == 0 && e.rule == Rule::Draw && !e.default_pick && !CanPick(e));
        const Knobs r = ReadUsable("1", nullptr, "draw", 0.0f);
        assert(r.key_count == 0 && r.rule == Rule::Draw && !r.default_pick);
        const Knobs a = ReadUsable("1", nullptr, "albedo", 0.0f);
        assert(a.key_count == 0 && a.rule == Rule::Albedo && !a.default_pick);
        const Knobs p = ReadUsable("1", "1:2", nullptr, 0.0f);
        assert(p.key_count == 1 && p.keys[0].vs == 1 && p.rule == Rule::Draw && !p.default_pick);
        assert(ReadUsable("1", "", "", 0.0f).key_count == 0 && !ReadUsable("1", "", "", 0.0f).default_pick);
        // the sheen's own text, the test view and off
        assert(ReadUsable("show", nullptr, nullptr, 0.0f).show && ReadUsable("show", nullptr, nullptr, 0.0f).default_pick);
        assert(ReadUsable("2.5", nullptr, nullptr, 0.0f).strength == 2.5f);
        for (const char* off : {static_cast<const char*>(nullptr), "", "0", "-1", "yes", "nan"}) {
            const Knobs k = ReadUsable(off, nullptr, nullptr, 0.0f);
            assert(k.strength == 0.0f && !k.default_pick && !k.from_ini); // nothing to pick for
        }
        // the ini strength: only when BB_BLOOD_SHEEN is unset or empty
        const Knobs i = ReadUsable(nullptr, nullptr, nullptr, 2.0f);
        assert(i.strength == 2.0f && i.from_ini && i.default_pick && i.key_count == 1 && !i.show);
        assert(ReadUsable("", nullptr, nullptr, 2.0f).from_ini && ReadUsable("", nullptr, nullptr, 2.0f).strength == 2.0f);
        assert(ReadUsable(nullptr, nullptr, nullptr, 0.1f).strength == MinStrength);
        assert(ReadUsable(nullptr, nullptr, nullptr, 9.0f).strength == MaxStrength);
        for (const float no : {0.0f, -1.0f, std::nanf(""), INFINITY}) {
            const Knobs k = ReadUsable(nullptr, nullptr, nullptr, no);
            assert(k.strength == 0.0f && !k.from_ini && !k.default_pick);
        }
        // set and not empty: the environment wins, 0 and text turn it off whatever the key says
        assert(ReadUsable("3", nullptr, nullptr, 2.0f).strength == 3.0f && !ReadUsable("3", nullptr, nullptr, 2.0f).from_ini);
        assert(ReadUsable("0", nullptr, nullptr, 2.0f).strength == 0.0f && !ReadUsable("0", nullptr, nullptr, 2.0f).default_pick);
        assert(ReadUsable("off", nullptr, nullptr, 2.0f).strength == 0.0f);
        assert(ReadUsable("show", nullptr, nullptr, 2.0f).show && !ReadUsable("show", nullptr, nullptr, 2.0f).from_ini);
        // ini with a named draw: the draw is kept, no default taken
        const Knobs n = ReadUsable(nullptr, "1:2", nullptr, 1.0f);
        assert(n.from_ini && !n.default_pick && n.key_count == 1 && n.rule == Rule::Draw);
        // Read itself is unchanged: nothing named, nothing picked
        assert(!CanPick(Read("1", nullptr, nullptr)));
        assert(IniStrength() == 0.0f);
    }

    // bbport (r129b_sheen-no-glow): the ceiling on the max channel relative to the dry scene, and the rim's levelling.
    {
        assert(Near(PeakDefault, 6.0, 1e-6) && Near(PeakFallback, 0.25, 1e-6) && MaxPeak == 64.0f && FlagRimFull == 64u);
        assert(RefBase == Slots * SlotWords && RefSlotWords == 3u);
        // the code: 64 steps a stop from 2^-16; a dry pixel's max channel counts, not its luminance
        assert(RefCode(1.0f, 0.5f, 0.2f) == 1024u && RefCode(0.25f, 0.1f, 0.0f) == 896u && RefCode(0.0f, 0.0f, 0.0f) == 256u);
        assert(RefCode(0.0f, 0.0f, 0.25f) == 896u && RefCode(1.0e9f, 0.0f, 0.0f) == 2047u);
        assert(RefCode(1.0e-30f, 0.0f, 0.0f) == 256u);                          // never below RefMin
        assert(RefUsable(0.0f, 1.0f, 2.0f) && !RefUsable(std::nanf(""), 0.0f, 0.0f) && !RefUsable(0.0f, INFINITY, 0.0f));
        // the mean of the codes is the geometric mean of the max channels: 1 and 0.25 give 0.5
        assert(RefMean(0u, 0u) == 0.0f && RefMean(12345u, 0u) == 0.0f);
        assert(Near(RefMean(896u * 10u, 10u), 0.25, 1e-6) && Near(RefMean(1024u + 896u, 2u), 0.5, 1e-6));
        // the ceiling: 0 when off, the fallback with no sample, PEAK x the reference else
        assert(PeakOf(0.0f, 896u, 1u) == 0.0f && PeakOf(-1.0f, 896u, 1u) == 0.0f && PeakOf(0.0f, 0u, 0u) == 0.0f);
        assert(PeakOf(6.0f, 0u, 0u) == PeakFallback && PeakOf(1.0f, 99u, 0u) == PeakFallback);
        assert(Near(PeakOf(6.0f, 896u * 4u, 4u), 1.5, 1e-5) && Near(PeakOf(3.0f, 1024u * 7u, 7u), 3.0, 1e-5));
        // a torch highlight on the film (red 3, green 0.3, blue 0.1) with the night ceiling 0.27: red at most 0.27, hue kept
        {
            const std::array<float, 3> hot = CapRgb({3.0f, 0.3f, 0.1f}, 0.27f);
            assert(hot[0] <= 0.27f + 1e-5f && hot[0] > 0.26f);
            assert(Near(hot[1] / hot[0], 0.1, 1e-5) && Near(hot[2] / hot[0], 0.1 / 3.0, 1e-5));
            // the red highlight r100k let through: luminance 0.28 of red 1.0, under the old knee 0.35, now over the knee 0.135
            const std::array<float, 3> red = CapRgb({1.0f, 0.09f, 0.03f}, 0.27f);
            assert(red[0] < 0.27f && red[0] > 0.2f);
            // a dark moonlit sheet is unchanged, so is anything with the ceiling off
            const std::array<float, 3> sheet = CapRgb({0.03f, 0.005f, 0.004f}, 0.27f);
            assert(sheet[0] == 0.03f && sheet[1] == 0.005f && sheet[2] == 0.004f);
            const std::array<float, 3> off = CapRgb({3.0f, 0.3f, 0.1f}, 0.0f);
            assert(off[0] == 3.0f && off[1] == 0.3f && off[2] == 0.1f);
            // the max channel decides, whichever channel it is (green and blue as well as red)
            assert(CapRgb({0.1f, 4.0f, 0.1f}, 0.27f)[1] <= 0.27f + 1e-5f && CapRgb({0.1f, 0.1f, 4.0f}, 0.27f)[2] <= 0.27f + 1e-5f);
        }
        float last = 0.0f;                                                       // monotonic in the max channel, never above the ceiling
        for (float top = 0.0f; top < 40.0f; top += 0.01f) {
            const float out = CapRgb({top, 0.0f, 0.0f}, 0.27f)[0];
            assert(out >= last - 1e-6f && out <= 0.27f + 1e-5f && out <= top + 1e-6f);
            last = out;
        }
        // the rim: the old levelling (the film weight alone) with rim_full, the new one else; deep inside the pool they agree
        assert(Near(FilledLevelShare(1.0f, 0.65f, 1.0f, 8, true), 0.5) && Near(FilledLevelShare(1.0f, 1.0f, 1.0f, 8, true), 1.0));
        assert(Near(FilledLevelShare(1.0f, 1.0f, 1.0f, 8), 1.0) && Near(FilledLevelShare(1.0f, 0.8f, 1.0f, 8), 0.35));
        {
            const float wet = FillWeight(0.65f, 1.0f, 8);                         // 0.5 at the rim: SpecWeight's w x wet x rim
            assert(Near(FilledLevelShare(1.0f, 0.65f, 1.0f, 8), SpecWeight(wet, wet, true, 0.65f)));
        }
        for (float share = 0.0f; share <= 1.0f; share += 0.01f) {                // never above the old value, a rim keeps relief
            assert(FilledLevelShare(1.0f, share, 1.0f, 8) <= FilledLevelShare(1.0f, share, 1.0f, 8, true) + 1e-6f);
        }
    }

    // bbport (r130a_sheen-colour): the film colour knobs: parsing, the packed shares, the clear film, the redness.
    {
        assert(ReadTint(nullptr) == 1 && ReadTint("") == 1 && ReadTint("1") == 1 && ReadTint("0") == 0 && ReadTint("2") == 2);
        assert(ReadTint("7") == 1 && ReadTint("x") == 1 && ReadTint(" 2 ") == 2 && ReadTint("20") == 1 && ReadTint("2x") == 1);
        // bbport (r131b_lrt-settings): the tint variable (unset or empty: -1, the setting decides) and the setting rule
        assert(ReadTintEnv(nullptr) == -1 && ReadTintEnv("") == -1 && ReadTintEnv("2") == 2 && ReadTintEnv("0") == 0);
        assert(ReadTintEnv("x") == 1 && ReadTintEnv("7") == 1 && ReadTintEnv(" 2 ") == 2);
        assert(TintOf(-1, 2) == 2 && TintOf(0, 2) == 0 && TintOf(-1, 9) == 2 && TintOf(-1, -4) == 0 && TintOf(2, 0) == 2);
        static_assert(TintOf(-1, 1) == 1 && TintOf(0, 1) == 0 && TintOf(1, 2) == 1);
        assert(ReadShare(nullptr) == 1.0f && ReadShare("") == 1.0f && ReadShare("x") == 1.0f && ReadShare("0.5x") == 1.0f);
        assert(ReadShare("0") == 0.0f && ReadShare("0.25") == 0.25f && ReadShare(" 0.5 ") == 0.5f);
        assert(ReadShare("7") == 1.0f && ReadShare("-3") == 0.0f && ReadShare("nan") == 1.0f);
        assert(PackScales(1.0f, 1.0f) == 0xFFFFFFFFu && PackScales(0.0f, 1.0f) == 0xFFFF0000u);
        assert(PackScales(1.0f, 0.0f) == 0x0000FFFFu && PackScales(0.0f, 0.0f) == 0u && PackScales(9.0f, -1.0f) == 0x0000FFFFu);
        assert(FlagTintOff == 128u && FlagTintClear == 256u && Near(ClearRoot, 0.15, 1e-6));
        // the clear film: grey at weight 1 (strength 1), untouched at weight 0, and it may go down
        {
            const SpecRoot grey = ClearSpec(0.3f, 0.1f, 0.05f, 1.0f, 1.0f);
            assert(Near(grey.r, 0.15) && Near(grey.g, 0.15) && Near(grey.b, 0.15));
            const SpecRoot none = ClearSpec(0.3f, 0.1f, 0.05f, 1.0f, 0.0f);
            assert(none.r == 0.3f && none.g == 0.1f && none.b == 0.05f);
            assert(ClearSpec(0.6f, 0.6f, 0.6f, 1.0f).r < 0.6f);
        }
        // WetSpec: the default is r100i's; tint_off is grey (the same root in all channels)
        {
            const SpecRoot tinted = WetSpec(0.1f, 0.1f, 0.1f, 1.0f);
            assert(Near(tinted.r, 0.45 * 0.85) && Near(tinted.g, 0.45 * 0.35) && Near(tinted.b, 0.45 * 0.30));
            const SpecRoot same = WetSpec(0.1f, 0.1f, 0.1f, 1.0f, 1.0f, false);
            assert(same.r == tinted.r && same.g == tinted.g && same.b == tinted.b);
            const SpecRoot untinted = WetSpec(0.1f, 0.1f, 0.1f, 1.0f, 1.0f, true);
            assert(Near(untinted.r, 0.45) && Near(untinted.g, 0.45) && Near(untinted.b, 0.45));
        }
        // the redness: a moonlit highlight (blue at least red) has none, the red body most of it
        assert(RedShare(0.3f, 0.35f, 0.45f) == 0.0f && RedShare(0.5f, 0.5f, 0.5f) == 0.0f);
        assert(Near(RedShare(0.05f, 0.005f, 0.005f), 0.9) && RedShare(0.0f, 0.0f, 0.0f) == 0.0f && Near(RedShare(1.0f, 0.0f, 0.0f), 1.0));
    }

    std::puts("blood sheen: ok");
    return 0;
}
