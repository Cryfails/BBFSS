// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r111_footprints): the footprints' knobs, walk, coat, fade and screen boxes (footprints.h).
// Pure: no Vulkan. Built and run by engine/build.sh --test and the CMake target footprints-test.
#undef NDEBUG
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include "gpu/shadps4/video_core/renderer_vulkan/footprints.h"

using namespace Vulkan::FootprintRules;

namespace {
bool Near(double a, double b, double eps = 1e-4) {
    return std::abs(a - b) <= eps;
}
} // namespace

int main() {
    // Knobs.
    {
        assert(!Read(nullptr, nullptr).on);
        assert(!Read("", nullptr).on && !Read("0", nullptr).on && !Read("yes", nullptr).on);
        assert(!Read("11", nullptr).on && !Read("shows", nullptr).on);
        const Knobs on = Read(" 1 ", nullptr);
        assert(on.on && !on.show && !on.coat_forced && !on.coat_bad);
        const Knobs show = Read("show", "");
        assert(show.on && show.show && !show.coat_forced && !show.coat_bad);
        const Knobs blood = Read("1", "blood");
        assert(blood.coat_forced && blood.coat == Kind::Blood);
        assert(Read("1", " mud").coat == Kind::Mud && Read("1", "wet ").coat_forced);
        const Knobs bad = Read("1", "lava");
        assert(!bad.coat_forced && bad.coat_bad);
        // BB_FOOTPRINTS_GAIN (r111c): a number from 0.25 to 4; anything else is 1 and says so.
        assert(on.gain == 1.0f && !on.gain_bad);
        assert(Near(Read("1", nullptr, "2").gain, 2.0) && Near(Read("1", nullptr, " 0.25 ").gain, 0.25));
        assert(Near(Read("1", nullptr, "4").gain, 4.0) && !Read("1", nullptr, "4").gain_bad);
        assert(Read("1", nullptr, "").gain == 1.0f && !Read("1", nullptr, "").gain_bad);
        assert(Read("1", nullptr, "-0.1").gain_bad && Read("1", nullptr, "5").gain_bad);
        // (r111d) 0 is a gain: no print is drawn; the live knob's parser gives the same number.
        assert(Read("1", nullptr, "0").gain == 0.0f && !Read("1", nullptr, "0").gain_bad);
        assert(Read("1", nullptr, "0.2").gain == 0.2f && !Read("1", nullptr, "0.2").gain_bad);
        assert(GainOfText(nullptr) == 1.0f && GainOfText("0") == 0.0f && GainOfText(" 3 ") == 3.0f);
        assert(GainOfText("lots") == 1.0f && GainOfText("") == 1.0f && GainOfText("4.5") == 1.0f);
        assert(Read("1", nullptr, "x").gain_bad && Read("1", nullptr, "2x").gain_bad);
        assert(Read("1", nullptr, "nan").gain_bad && Read("1", nullptr, "inf").gain_bad);
        assert(Read("1", nullptr, "9").gain == 1.0f && Read("1", nullptr, "-1").gain == 1.0f);
        const Push gain_push{};
        assert(gain_push.gain == 1.0f && sizeof(Push) == 112);
        assert(Flags(show, true, 1, false) == (FlagShow | FlagSlot | FlagHunter));
        assert(Flags(on, false, 0, false) == 0u);
        assert(Flags(on, false, 0, true) == FlagSrgb);
    }
    // The walk: straight along +z at 5 cm a frame, a print each 0.75 m, sides in turn.
    {
        Walker w;
        float pos[3] = {1.0f, 2.0f, 3.0f};
        assert(!Walk(w, pos).step); // the first position starts the path
        std::array<Step, 8> steps{};
        int n = 0;
        for (int f = 1; f <= 64; ++f) { // 3.2 m: strides end near 0.75, 1.5, 2.25 and 3 m
            pos[2] = 3.0f + 0.05f * float(f);
            const Step s = Walk(w, pos);
            if (s.step) {
                assert(n < 8);
                steps[std::size_t(n++)] = s;
            }
        }
        assert(n == 4);
        for (int i = 0; i < n; ++i) {
            const Step& s = steps[std::size_t(i)];
            assert(Near(s.dir_x, 0.0) && Near(s.dir_z, 1.0));
            assert(Near(s.side, i % 2 == 0 ? 1.0 : -1.0));
            // to the side (-dir_z, dir_x) * side: x moves by -side * GaitHalfM
            assert(Near(s.x, 1.0 - s.side * GaitHalfM) && Near(s.y, 2.0));
            assert(Near(s.z, 3.0 + 0.75 * (i + 1), 0.051)); // (a float sum may take one frame more)
        }
        // A warp starts the path anew: no print, the walk counts on from there.
        pos[0] += 50.0f;
        assert(!Walk(w, pos).step && w.jumps == 1);
        pos[2] += 0.7f; // under a stride since the warp
        assert(!Walk(w, pos).step);
        // A fall of more than DropM in one frame too.
        pos[1] -= 1.5f;
        assert(!Walk(w, pos).step && w.jumps == 2);
        // A NaN position.
        float bad[3] = {NAN, 0.0f, 0.0f};
        assert(!Walk(w, bad).step && w.jumps == 3);
    }
    // A fast frame (two strides at once) places one print and counts on from 0.
    {
        Walker w;
        float pos[3] = {0.0f, 0.0f, 0.0f};
        Walk(w, pos);
        pos[0] = 1.6f;
        const Step s = Walk(w, pos);
        assert(s.step && Near(s.dir_x, 1.0) && Near(s.dir_z, 0.0) && w.acc == 0.0f);
    }
    // The coat: water or a puddle soak the feet; each step leaves DryPerStep; dry below MinCoat.
    {
        const Knobs k = Read("1", nullptr);
        Coat c;
        Kind kind = Kind::Blood;
        assert(TakeStep(c, k, false, kind) == 0.0f); // dry from the start
        Soak(c, k, true, false);
        assert(c.amount == 1.0f && c.kind == Kind::Wet);
        assert(TakeStep(c, k, true, kind) == 0.0f && c.amount == 1.0f); // in the water: nothing
        int prints = 0;
        float last = 2.0f;
        for (int i = 0; i < 40; ++i) {
            const float s = TakeStep(c, k, false, kind);
            if (s == 0.0f) {
                break;
            }
            assert(kind == Kind::Wet && s <= last);
            last = s;
            ++prints;
        }
        // r111d: 3 full prints, then 0.75^n >= 0.06 (n <= 9.8): 12 prints (1, 1, 1, 0.75, ..., 0.75^9 = 0.0751)
        assert(prints == 12 && c.amount == 0.0f && prints == int(CoatPrints(Kind::Wet)));
        Soak(c, k, false, true);
        assert(c.amount == 1.0f);
        // InWater and GlossyGround.
        assert(InWater(true, 5.0f, 4.9f) && !InWater(true, 5.0f, 4.98f) && !InWater(false, 5.0f, 0.0f));
        assert(!GlossyGround(23, 23) && GlossyGround(24, 8) && !GlossyGround(100, 29) && GlossyGround(100, 30));
    }
    // Pickup (r111b): blood on the ground under the feet, and what a blood coat does.
    {
        const Knobs k = Read("1", nullptr);
        assert(!InBlood(23, 23) && InBlood(24, 6) && !InBlood(24, 5) && !InBlood(100, 24));
        assert(InBlood(100, 25) && !InBlood(0, 0));
        assert(Near(BloodAmount(100, 25), 0.5) && Near(BloodAmount(100, 50), 1.0));
        assert(BloodAmount(100, 100) == 1.0f && BloodAmount(0, 0) == 0.0f);
        Coat c;
        Kind kind = Kind::Wet;
        // 5% of the disc: no pickup. 60%: a blood coat at full strength.
        assert(!Soak(c, k, false, false, 200, 10) && c.amount == 0.0f && c.source == Source::None);
        assert(Soak(c, k, false, false, 200, 120));
        assert(c.kind == Kind::Blood && c.amount == 1.0f && c.source == Source::Blood && c.full == 1u);
        assert(!Soak(c, k, false, false, 200, 120)); // still in it: no new pickup
        // The feet leave the blood (nothing under them: the coat is kept): (r111h) the first print full, then 0.8
        // of the amount a step, dry after 13 prints in all (r111d: 4 full, then 0.75, also 13).
        assert(!Soak(c, k, false, false, 200, 0) && c.amount == 1.0f && c.source == Source::None);
        float strength[24] = {};
        int prints = 0;
        while (prints < 24) {
            const float s = TakeStep(c, k, false, kind);
            if (s == 0.0f) {
                break;
            }
            assert(kind == Kind::Blood);
            strength[prints++] = s;
        }
        assert(prints == 13 && c.amount == 0.0f && prints == int(CoatPrints(Kind::Blood)));
        assert(strength[0] == 1.0f && Near(strength[1], 0.8) && Near(strength[2], 0.64) && Near(strength[6], 0.2621, 1e-3) &&
               Near(strength[12], 0.0687, 1e-3));
        // (r111h) the first print is the strongest and each one is weaker than the one before: 1 full print and 12
        // more fading over a long walk (a wet coat: 3 full and 9)
        assert(CoatPrints(Kind::Blood) - BloodFullPrints == 12u && CoatPrints(Kind::Wet) - WetFullPrints == 9u);
        // A weaker pickup: 30% of the disc is 0.6 of the strength.
        assert(Soak(c, k, false, false, 100, 30) && Near(c.amount, 0.6));
        // The newest pickup wins: a puddle after blood is wet at full; blood on a puddle is blood
        // (a different source than the frame before); water beats blood.
        assert(Soak(c, k, false, true, 100, 0) && c.kind == Kind::Wet && c.amount == 1.0f);
        assert(c.source == Source::Puddle && c.full == WetFullPrints);
        assert(!Soak(c, k, false, true, 100, 0));
        assert(Soak(c, k, false, true, 200, 120) && c.kind == Kind::Blood && c.source == Source::Blood);
        assert(Soak(c, k, true, false, 200, 120) && c.kind == Kind::Wet && c.source == Source::Water);
        // Too few ground pixels in the disc (23 of 23 blood): not blood.
        Coat few;
        assert(!Soak(few, k, false, false, 23, 23) && few.amount == 0.0f);
        // A forced coat is no pickup.
        const Knobs forced = Read("1", "mud");
        Coat f;
        assert(!Soak(f, forced, false, false, 200, 120) && f.kind == Kind::Mud && f.amount == 1.0f);
        // Blood and wet coats as a table (r111h): blood 1 full then 0.8; wet 3 full then 0.75.
        assert(RuleOf(Kind::Blood).full == 1u && Near(RuleOf(Kind::Blood).keep, 0.8));
        assert(RuleOf(Kind::Wet).full == 3u && Near(RuleOf(Kind::Wet).keep, 0.75));
        assert(std::string(SourceName(Source::Blood)) == "blood");
    }
    // A forced coat never dries; the test view prints every step at full.
    {
        const Knobs k = Read("1", "blood");
        Coat c;
        Soak(c, k, false, false);
        Kind kind = Kind::Wet;
        for (int i = 0; i < 50; ++i) {
            assert(TakeStep(c, k, false, kind) == 1.0f && kind == Kind::Blood);
        }
        const Knobs show = Read("show", nullptr);
        Coat dry;
        assert(TakeStep(dry, show, false, kind) == 1.0f && kind == Kind::Wet);
        assert(TakeStep(dry, show, true, kind) == 0.0f);
    }
    // Fade: full at 0, half at LifeS / 2, none from LifeS on (r111d: LifeS 30).
    {
        assert(LifeS == 30.0f);
        assert(Near(Fade(0.0), 1.0) && Near(Fade(15.0), 0.5) && Near(Fade(30.0), 0.0) && Near(Fade(99.0), 0.0));
        assert(Fade(2.0) > 0.98 && Fade(5.0) > Fade(15.0) && Fade(10.0) > 0.7);
    }
    // (r111k) The trail rules: a soft start and end, a held pickup, a print that fades in; the knobs.
    {
        // BB_FOOTPRINTS_TRAIL: "0" is r111j's rules, unset, empty, "1" or other text the trail rules; Read(on, coat) alone is r111j's.
        assert(!Read("1", nullptr).trail && !Read("1", nullptr, nullptr, "0").trail && !Read("1", nullptr, nullptr, " 0 ").trail);
        assert(Read("1", nullptr, nullptr, nullptr).trail && Read("1", nullptr, nullptr, "").trail &&
               Read("1", nullptr, nullptr, "1").trail && Read("1", nullptr, nullptr, "x").trail);
        assert(TrailOfText(nullptr) && TrailOfText("1") && !TrailOfText("0") && !TrailOfText(" 0 ") && TrailOfText("00"));
        assert(LookOfText(nullptr) && LookOfText("") && !LookOfText("0") && LookOfText("1"));
        const Knobs on = Read("1", nullptr, nullptr, nullptr);
        const Knobs old = Read("1", nullptr);
        // The profile: the first TrailFull prints whole, then a smooth taper to a hair; nothing from `total` on.
        assert(TrailPrints(Kind::Wet) == 14u && TrailPrints(Kind::Blood) == 16u && TrailPrints(Kind::Mud) == 14u);
        for (const std::uint32_t total : {TrailWetPrints, TrailBloodPrints}) {
            assert(TrailProfile(0, total) == 1.0f && TrailProfile(1, total) == 1.0f && TrailProfile(total, total) == 0.0f);
            assert(TrailProfile(TrailFull, total) > 0.97f); // no step after the whole prints
            float prev = 1.0f;
            for (std::uint32_t i = 0; i < total; ++i) {
                const float s = TrailProfile(i, total);
                assert(s <= prev && s > 0.0f);
                prev = s;
            }
            assert(prev < 0.02f); // the last print is about 1% of the coat
        }
        // A wet trail after the water: 14 prints, each no stronger than the one before, then dry.
        {
            Coat c;
            Kind kind = Kind::Blood;
            Soak(c, on, true, false);
            assert(c.kind == Kind::Wet && c.amount == 1.0f && c.step_n == 0u);
            int prints = 0;
            float before = 2.0f;
            for (int i = 0; i < 40; ++i) {
                const float s = TakeStep(c, on, false, kind);
                if (s == 0.0f) {
                    break;
                }
                assert(kind == Kind::Wet && s <= before && Near(s, TrailProfile(std::uint32_t(i), TrailWetPrints)));
                before = s;
                ++prints;
            }
            assert(prints == int(TrailWetPrints) && c.amount == 0.0f && TakeStep(c, on, false, kind) == 0.0f);
            // Standing in a source starts the trail over.
            Soak(c, on, true, false);
            TakeStep(c, on, false, kind);
            TakeStep(c, on, false, kind);
            assert(c.step_n == 2u);
            Soak(c, on, true, false);
            assert(c.step_n == 0u && c.amount == 1.0f);
        }
        // Blood: the share to step in, the share to stay, the coat's strength.
        assert(InBloodTrail(100, BloodEnterPercent, false) && !InBloodTrail(100, BloodEnterPercent - 1u, false));
        assert(InBloodTrail(100, BloodStayPercent, true) && !InBloodTrail(100, BloodStayPercent - 1u, true));
        assert(!InBloodTrail(MinPickPixels - 1u, MinPickPixels - 1u, true) && !InBloodTrail(0, 0, true));
        assert(Near(BloodAmountTrail(100, 30), 1.0) && Near(BloodAmountTrail(100, 15), 0.5) && BloodAmountTrail(0, 0) == 0.0f);
        assert(GlossyGroundStay(100, PuddleStayPercent) && !GlossyGroundStay(100, PuddleStayPercent - 1u));
        assert(!GlossyGroundStay(MinGroundPixels - 1u, MinGroundPixels - 1u));
        {
            Coat b;
            assert(!Soak(b, on, false, false, 100, 14) && b.source == Source::None); // 14%: not enough to step into it
            assert(Soak(b, on, false, false, 100, 20) && b.kind == Kind::Blood && b.source == Source::Blood);
            assert(Near(b.amount, 0.2 / 0.3));
            // 9% of the disc: held by the stay share (no new pickup), and the strongest share of the visit is kept
            assert(!Soak(b, on, false, false, 100, 9) && b.source == Source::Blood && Near(b.amount, 0.2 / 0.3));
            assert(!Soak(b, on, false, false, 100, 5) && b.source == Source::None && b.amount > 0.6f); // left: coat kept
            // r111j's rules: 20% is not blood and nothing is held
            Coat o;
            assert(!Soak(o, old, false, false, 100, 20) && o.source == Source::None);
            assert(Soak(o, old, false, false, 100, 60) && !Soak(o, old, false, false, 100, 9) && o.source == Source::None);
            // A puddle: held while the stay rule holds, only with the trail rules.
            Coat p;
            assert(Soak(p, on, false, true, 100, 0, true) && p.source == Source::Puddle);
            assert(!Soak(p, on, false, false, 0, 0, true) && p.source == Source::Puddle);
            assert(!Soak(p, on, false, false, 0, 0, false) && p.source == Source::None);
            Coat q;
            assert(Soak(q, old, false, true, 0, 0, true) && !Soak(q, old, false, false, 0, 0, true) && q.source == Source::None);
        }
        // A new print fades in: 0 at birth, half at half the time, whole from FadeInS on; never negative or above 1.
        assert(FadeIn(0.0) == 0.0f && Near(FadeIn(double(FadeInS) / 2.0), 0.5) && FadeIn(double(FadeInS)) == 1.0f);
        assert(FadeIn(5.0) == 1.0f && FadeIn(-1.0) == 0.0f);
    }
    // Screen boxes: a camera at the origin looking along +z (view = identity), 90 degrees.
    {
        const std::array<float, 12> view = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const std::array<float, 4> proj = {1.0f, 1.0f, 0.0f, 0.0f};
        const std::array<float, 2> jitter = {0.0f, 0.0f};
        // A point straight ahead lands in the middle of a 100 x 100 screen.
        const float lo[3] = {-0.01f, -0.01f, 4.99f}, hi[3] = {0.01f, 0.01f, 5.01f};
        const Rect r = Project(view, proj, 100.0f, 100.0f, jitter, lo, hi);
        assert(!r.Empty() && r.x0 <= 49 && r.x1 >= 51 && r.y0 <= 49 && r.y1 >= 51);
        assert(r.x1 - r.x0 <= 2 + 2 * MarginPx + 2);
        // Behind the camera: empty; across the camera plane: the whole screen.
        const float blo[3] = {-1.0f, -1.0f, -3.0f}, bhi[3] = {1.0f, 1.0f, -2.0f};
        assert(Project(view, proj, 100.0f, 100.0f, jitter, blo, bhi).Empty());
        const float xlo[3] = {-1.0f, -1.0f, -1.0f}, xhi[3] = {1.0f, 1.0f, 1.0f};
        const Rect all = Project(view, proj, 100.0f, 100.0f, jitter, xlo, xhi);
        assert(all.x0 == 0 && all.y0 == 0 && all.x1 == 100 && all.y1 == 100);
        // Off to the side: empty.
        const float slo[3] = {20.0f, -0.1f, 4.9f}, shi[3] = {20.2f, 0.1f, 5.1f};
        assert(Project(view, proj, 100.0f, 100.0f, jitter, slo, shi).Empty());
        // A jitter of +2 px moves the box by 2 px.
        const Rect j = Project(view, proj, 100.0f, 100.0f, {2.0f, 0.0f}, lo, hi);
        assert(j.x0 == r.x0 + 2 && j.x1 == r.x1 + 2 && j.y0 == r.y0);
        // Union.
        const Rect u = Union(r, Rect{});
        assert(u.x0 == r.x0 && u.x1 == r.x1);
        const Rect v = Union(Rect{1, 2, 3, 4}, Rect{10, 0, 12, 3});
        assert(v.x0 == 1 && v.y0 == 0 && v.x1 == 12 && v.y1 == 4);
    }
    // (r111e) BB_FOOTPRINTS_SHOW and BB_FOOTPRINTS_POST.
    {
        assert(ShowFlatOfText("1") && ShowFlatOfText(" 1 ") && !ShowFlatOfText(nullptr));
        assert(!ShowFlatOfText("") && !ShowFlatOfText("0") && !ShowFlatOfText("show") && !ShowFlatOfText("11"));
        assert(PostOfText(nullptr) == 1.0f && PostOfText("") == 1.0f && PostOfText("0") == 0.0f);
        assert(Near(PostOfText(" 0.5 "), 0.5) && Near(PostOfText("2"), 2.0));
        assert(PostOfText("2.5") == 1.0f && PostOfText("-1") == 1.0f && PostOfText("x") == 1.0f);
        assert(PostOfText("1 x") == 1.0f);
        // (r111j) BB_FOOTPRINTS_SHEEN: off unless a number from 0 to 4; the roll-off keeps the floor under the ceiling
        assert(SheenOfText(nullptr) == 0.0f && SheenOfText("") == 0.0f && SheenOfText("0") == 0.0f);
        assert(SheenOfText("1") == 1.0f && Near(SheenOfText(" 0.5 "), 0.5) && Near(SheenOfText("4"), 4.0));
        assert(SheenOfText("5") == 0.0f && SheenOfText("-1") == 0.0f && SheenOfText("x") == 0.0f);
        assert(SheenOfText("1 x") == 0.0f);
        assert(SheenFloor(0.0f) == 0.0f && Near(SheenFloor(1.0f), FOOTPRINTS_SHEEN_SKY));
        {
            const double peak = FOOTPRINTS_SHEEN_PEAK, knee = FOOTPRINTS_SHEEN_KNEE * FOOTPRINTS_SHEEN_PEAK;
            assert(Near(PeakRoll(float(knee) * 0.5f, float(peak)), knee * 0.5)); // under the knee: as it is
            assert(Near(PeakRoll(float(knee), float(peak)), knee));              // continuous at the knee
            float last = 0.0f;
            for (int i = 0; i <= 40; ++i) { // increasing, never above the ceiling
                const float v = PeakRoll(float(i) * 0.005f, float(peak));
                assert(v >= last && v <= float(peak));
                last = v;
            }
            assert(SheenFloor(float(SheenMax)) < float(peak) && SheenFloor(float(SheenMax)) > SheenFloor(1.0f));
            // the floor over near-black ground: a print on 0.005 stone reads at 0.012 (the dark red), under the 0.02
            // readable boundary; a print on the lit church slab (0.077 x 0.25) is above the floor and not lifted
            assert(SheenFloor(1.0f) > 0.005f * 0.25f * 4.0f && 0.077f * 0.25f > SheenFloor(1.0f));
        }
        // the view verdicts
        assert(ViewVerdict(0u, 500u, 0.5) == 0u && ViewVerdict(3u, 0u, 0.0) == 1u);
        assert(ViewVerdict(3u, 500u, 0.01) == 2u && ViewVerdict(3u, 500u, 0.05) == 3u);
        assert(FlatWords == 43u && WordFlatRedPx != WordFlatPostPx); // (r111i) six luminance words, (r111j) a sheen word
        // the blood tint's luminance is 1 (so the stamp keeps the lit pixel's luminance)
        const double lum = 0.2126 * FOOTPRINTS_POST_BLOOD_TINT_R + 0.7152 * FOOTPRINTS_POST_BLOOD_TINT_G +
                           0.0722 * FOOTPRINTS_POST_BLOOD_TINT_B;
        assert(Near(lum, 1.0, 2e-3));
    }
    // (r111f) ProjectPoint: the rule of Project and of the shaders, for one point.
    {
        const std::array<float, 12> view{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const std::array<float, 4> proj{1.0f, 2.0f, 1.0f, 0.0f};
        const std::array<float, 2> none{0.0f, 0.0f};
        // on the axis, 2 m in front: the middle of a 100 x 50 picture (pixel centres at integers)
        ScreenPoint a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 0.0f, 0.0f, 2.0f);
        assert(a.state == 1 && Near(a.x, 49.5) && Near(a.y, 24.5) && Near(a.z, 2.0));
        // 1 m to the right at 2 m: ndc 0.5, pixel 75 - 0.5; 0.5 m down with y scale 2: ndc 0.5, 37
        a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 1.0f, 0.0f, 2.0f);
        assert(a.state == 1 && Near(a.x, 74.5));
        a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 0.0f, 0.5f, 2.0f);
        assert(a.state == 1 && Near(a.y, 37.0));
        // outside the picture (state 0), behind the camera and on the near plane (state 2, x and y 0)
        a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 10.0f, 0.0f, 1.0f);
        assert(a.state == 0 && a.x > 99.0f);
        a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 0.0f, 0.0f, -3.0f);
        assert(a.state == 2 && a.x == 0.0f && a.y == 0.0f && Near(a.z, -3.0));
        a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 0.0f, 0.0f, NearZ);
        assert(a.state == 2);
        // the jitter moves the pixel
        a = ProjectPoint(view, proj, 100.0f, 50.0f, {0.5f, -0.5f}, 0.0f, 0.0f, 2.0f);
        assert(Near(a.x, 50.0) && Near(a.y, 24.0));
        // the box of Project around a point holds the point's pixel
        const float lo[3] = {-0.1f, -0.1f, 1.9f}, hi[3] = {0.1f, 0.1f, 2.1f};
        const Rect r = Project(view, proj, 100.0f, 50.0f, none, lo, hi);
        a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 0.0f, 0.0f, 2.0f);
        assert(!r.Empty() && a.x >= float(r.x0) && a.x <= float(r.x1) && a.y >= float(r.y0) && a.y <= float(r.y1));
    }
    // (r111g) The look: a deeper, more saturated red at less than the pixel's luminance, firmer cover, a stronger
    // wet darken; the blood trail's strengths never rise (the first prints, at the pool, are the strongest); the
    // stamp's arithmetic (the shader's, in doubles) turns a lit grey pixel into a dark red one.
    {
        const double tr = FOOTPRINTS_POST_BLOOD_TINT_R, tg = FOOTPRINTS_POST_BLOOD_TINT_G,
                     tb = FOOTPRINTS_POST_BLOOD_TINT_B;
        assert(Near(0.2126 * tr + 0.7152 * tg + 0.0722 * tb, 1.0, 2e-3));
        assert((tr - std::max(tg, tb)) / tr > 0.92); // r111f: 0.88
        assert(FOOTPRINTS_POST_BLOOD_LUM < 0.5 && FOOTPRINTS_POST_BLOOD_LUM > 0.1); // (r111h) deep, not bright
        assert(FOOTPRINTS_POST_BLOOD_COVER > 0.9 && FOOTPRINTS_POST_BLOOD_COVER <= 1.0);
        assert(FOOTPRINTS_POST_WET_DARKEN > 0.45 && FOOTPRINTS_POST_WET_DARKEN < 0.6); // (r111h) 55%
        // a lit grey pixel (0.2) under a full blood print: darker than before, red by more than 8 to 1
        const double lum = 0.2, w = 1.0;
        const double dark = lum * FOOTPRINTS_POST_BLOOD_LUM;
        const double r = 0.2 * (1.0 - FOOTPRINTS_POST_BLOOD_COVER * w) + tr * dark * FOOTPRINTS_POST_BLOOD_COVER * w;
        const double g = 0.2 * (1.0 - FOOTPRINTS_POST_BLOOD_COVER * w) + tg * dark * FOOTPRINTS_POST_BLOOD_COVER * w;
        const double b = 0.2 * (1.0 - FOOTPRINTS_POST_BLOOD_COVER * w) + tb * dark * FOOTPRINTS_POST_BLOOD_COVER * w;
        const double out_lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        assert(out_lum < lum * 0.8 && r > 8.0 * g && r > 8.0 * b);
        // the rounded weight: 1 stays 1, 0.42 reads 0.66, order kept
        const auto round_w = [](double v) { return 1.0 - (1.0 - v) * (1.0 - v); };
        assert(Near(round_w(1.0), 1.0) && Near(round_w(0.42), 0.6636, 1e-3) && round_w(0.3) < round_w(0.4));
        // the trail of a full blood coat: no print is stronger than the one before
        const Knobs k = Read("1", nullptr);
        Coat c;
        Kind kind = Kind::Wet;
        assert(Soak(c, k, false, false, 200, 120));
        float last = 2.0f;
        int n = 0;
        while (n < 24) {
            const float s = TakeStep(c, k, false, kind);
            if (s == 0.0f) {
                break;
            }
            assert(s < last && kind == Kind::Blood); // (r111h) strictly weaker with each print
            last = s;
            ++n;
        }
        assert(n == 13);
    }
    // (r111h) The look in numbers: the stamp's red channel at a full blood print stays under the stone's own
    // (a dark red, never a bright one), the surface rules' numbers, the wet soft edge wider than the blood one.
    {
        const double tr = FOOTPRINTS_POST_BLOOD_TINT_R, tg = FOOTPRINTS_POST_BLOOD_TINT_G;
        const double red_over_stone = tr * FOOTPRINTS_POST_BLOOD_LUM, green_over_stone = tg * FOOTPRINTS_POST_BLOOD_LUM;
        assert(red_over_stone > 0.7 && red_over_stone < 1.1 && green_over_stone < 0.1);
        assert(FOOTPRINTS_POST_WET_EDGE < FOOTPRINTS_EDGE && FOOTPRINTS_POST_WET_EDGE > 0.3);
        assert(FOOTPRINTS_POST_NEAR_FRAC > 0.8 && FOOTPRINTS_POST_NEAR_FRAC < 0.95);
        // the near end of a sole at a 1.5 m close-up (0.14 m nearer than its centre, 0.093) is kept; a hunter 2.7 m
        // from the camera in front of a print 8.65 m away is left out
        const auto left_out = [](double z, double pz) {
            return z < FOOTPRINTS_POST_NEAR_FRAC * pz && pz - z > FOOTPRINTS_POST_NEAR_M;
        };
        assert(!left_out(1.5 - 0.14, 1.5) && left_out(2.68, 8.65) && !left_out(8.65, 8.65) && !left_out(2.5, 2.6));
        assert(FOOTPRINTS_POST_NORMAL_PX >= 2 && FOOTPRINTS_POST_NEIGHBOUR_M > 0.05 && FOOTPRINTS_POST_NEIGHBOUR_REL < 0.2);
        // (r111i) the wet look: a firmer edge than r111h's 0.55 but softer than the blood edge; the rounded weight
        // of a faded wet print (0.4 reads 0.64); the silhouette rule: the margin at 4 m is 0.32 m, so a cobble step
        // of 0.15 m is kept and a hunter's leg 0.5 m nearer is left out; the pixel offset is 5 at 1080 lines, at
        // least 2 at 360
        assert(FOOTPRINTS_POST_WET_EDGE > 0.55 && FOOTPRINTS_POST_WET_EDGE < FOOTPRINTS_EDGE);
        assert(Near(1.0 - (1.0 - 0.4) * (1.0 - 0.4), 0.64));
        const auto next_to_nearer = [](double z, double zq) {
            return zq < z - (FOOTPRINTS_POST_SILHOUETTE_M + FOOTPRINTS_POST_SILHOUETTE_REL * z);
        };
        assert(!next_to_nearer(4.0, 3.85) && next_to_nearer(4.0, 3.5) && !next_to_nearer(4.0, 4.5));
        assert(next_to_nearer(10.0, 9.4) && !next_to_nearer(10.0, 9.6));
        const auto tap_px = [](double height) {
            const int v = int(height * FOOTPRINTS_POST_SILHOUETTE_FRAC + 0.5);
            return v > 2 ? v : 2;
        };
        assert(tap_px(1080.0) == 5 && tap_px(360.0) == 2 && tap_px(720.0) == 4);
        // the luminance counters: six words after the probes, fixed point whose cap fits 65536 pixels in 32 bits
        assert(FOOTPRINTS_FLAT_WORD_LUM == FOOTPRINTS_FLAT_WORD_PROBE + FOOTPRINTS_FLAT_PROBES * FOOTPRINTS_FLAT_PROBE_WORDS);
        assert(FOOTPRINTS_FLAT_WORD_SHEEN == FOOTPRINTS_FLAT_WORD_LUM + FOOTPRINTS_FLAT_LUM_WORDS &&
               FOOTPRINTS_FLAT_WORDS == FOOTPRINTS_FLAT_WORD_SHEEN + 1u);
        assert(FOOTPRINTS_FLAT_LUM_CAP * FOOTPRINTS_FLAT_LUM_SCALE * 65536.0 <= 4294967296.0);
    }
    // Pack.
    {
        float out[PrintFloats];
        Pack(1, 2, 3, 0.5f, 0, 1, -1, Kind::Blood, out);
        assert(out[3] == 0.5f && out[6] == -1.0f && out[7] == 2.0f);
    }
    std::puts("footprints: ok");
    return 0;
}
