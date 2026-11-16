# r94b_fog-noise-visible: FEATURE patch (fix of r94_fog-noise, order item 5 "Fog noise"). Off by
# default: nothing changes unless BB_FOG_NOISE_BANKS=1 is set WITH the fog noise on (BB_FOG_NOISE
# above 0 or BB_FOG_NOISE_SHOW=1). Needs r94_fog-noise.fixed (and r105_cloud-shadows, whose
# FOG_NOISE_VALUE_ONLY block it keeps whole) in the tree.
#
# REVIEWED 2026-11-15 (.fixed): the draft's periodic count ("N of those 600 marches with the banks
# look") could only ever say 600 (the knob is read once), so the 600-march line now says how far
# the banks moved (net, metres) since the last line, the evidence that they drift; <cmath> is
# included where std::fmod / std::sqrt are used; the README row states the knob's real rule (text
# starting with 1) and BB_FOG_NOISE_SCALE's row its 14 m default with the banks.
#
# Why: r94 was built and acts at the graveyard (on vs off 6.3/8.6 of 255) but is too even to see in a
# still or a standing clip. A CPU probe of a graveyard-like view (scratch r94b_probe.py: Python twin of
# fog_noise.glsl and of the 32-step march, camera 1.7 m above flat ground, 16:9, 50 deg vertical
# field, every sample lit, six places) shows why: a 40 m ray averages several 10 m cells, so across
# the upper half of the picture r94's fog light at strength 1 varies by only 0.15 of its mean (sd;
# 10-90 % range 0.40 wide), 0.24 at SHOW, and a pixel changes by 0.21 of the mean in 6 s of 1.5 m/s
# wind. There is no temporal pass on the sun fog (half-resolution march with a FIXED per-pixel jitter,
# 3x3 depth-weighted filter, added to the HDR scene before the upscaler), so nothing of the pattern is
# lost there; the upscaler (DLSS/FSR, temporal) sees a pattern that moves 2.5 cm a frame at 1.5 m/s,
# far below what its history clamp rejects, so the low-frequency banks pass through it whole; only
# sub-metre grain would be smoothed. The limit is the look's own contrast and size, so this patch
# changes those.
#
# What it does, BB_FOG_NOISE_BANKS=1 only: the shaping m = 1 + a clamp(2 g d, -1, 1) is replaced by
# banks: m = A + B smoothstep(-0.01, 0.11, d) (d the same octave sum, sd 0.13), A = 1 - 0.85 a (the
# clear air: 0.15 at a = min(s, 1) = 1), B = 0.85 a / 0.36 (0.36 = the world mean of the smoothstep,
# CPU sample of 300000 points; 0.357 past the finest octave's fade), so the mean of m stays 1 and a
# bank's core is 2.51. About a third of space is in banks. Banks are 2.5x wider than tall (r94: 1.6x)
# and 14 m across unless BB_FOG_NOISE_SCALE is set. Probe at that design (six places, level view):
# upper-half spread 0.36 of the mean (2.4x r94's), 10-90 % range 0.99 wide, change in 6 s of wind 0.50
# (2.4x); a place's haze is brighter or darker than the knob-off picture by 0.26 on average. The
# drift is r94's: only with BB_WIND=1, toward the one wind of the tree (BbWind: BB_WIND_DIR with its
# wander, speed and gusts), the direction r105's cloud shadows also take with BB_WIND=1 unless
# BB_CLOUDS_DIR is set; the finer octaves 1.3x and 1.7x faster, so the bank edges change as they pass.
#
# How (no new push word, no new build): the NOISE builds' tail keeps its six vec4. With the banks look
# MakeTail puts A in noise_off0.w and -B in noise_off1.w; r94's gain there is 2 or more, so the
# shader's `noise_off1.w < 0.0` marks the look (a uniform branch). The flatter banks come from the
# CPU: MakeTail multiplies the up row of the view to world matrix (row 1) by 2.5 / 1.6. The wind has
# no up part, so the drift needs nothing.
#
# r94 exactly: BB_FOG_NOISE_BANKS missing, 0 or any text not starting with 1: MakeKnobs gives the
# knobs r94 gave (test k), MakeTail the same 24 words, the shader takes r94's line with the same
# numbers. Off path: BB_FOG_NOISE off -> no NOISE march at all (r94's guarantee, unchanged); noise
# on without banks -> one compare of a push constant per lit sample more than r94.
# Cost with banks (estimate, not measured): a compare and a smoothstep per lit sample (about 6 ALU
# beside r94's ~400) and, at the 14 m default scale, the finest octave is kept to 34 m instead of 24 m
# (about 8% more hashed corners): about 10% over r94's 0.1-0.4 ms at 1080p internal. No memory.
#
# Files: host_shaders/fog_noise_layout.h (5 defines), host_shaders/fog_noise.glsl (the banks line in
# fog_noise_m, inside r105's #ifndef FOG_NOISE_VALUE_ONLY, so cloud_shadow builds keep their SPIR-V),
# renderer_vulkan/volumetric_fog_noise.h (constants, Knobs::banks, 4-text MakeKnobs, BankClear,
# BankGain, BankFactor, MakeTail's banks words), renderer_vulkan/vk_volumetric_fog_noise.cpp (reads
# BB_FOG_NOISE_BANKS with the other knobs; once-line; the banks' travel in the 600-march line),
# tests/test_volumetric_fog_noise.cpp (check k, with a C++ copy of the noise for the mean),
# README.md (a row after BB_FOG_NOISE_SHOW). No CMake or build.sh change (fog_noise.glsl and the
# layout header are already INCLUDES of every volumetric_light build; the test target exists).
#
# Use: python -I -X utf8 r94b_fog-noise-visible.py check | apply | revert
# Root: R94B_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r94b_backup next to this script; revert takes out exactly what apply put in (inserted texts are found
# by themselves, exactly once; the one replaced line is put back).
import os, sys

ROOT = os.environ.get("R94B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r94b_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
L = HS + "fog_noise_layout.h"
G = HS + "fog_noise.glsl"
P = RV + "volumetric_fog_noise.h"
C = RV + "vk_volumetric_fog_noise.cpp"
U = "engine/tests/test_volumetric_fog_noise.cpp"
R = "README.md"

# Insert edits: (anchor, before, after); the anchor stays. Replace edits: ("REPLACE", old, new).
EDITS = {
L: [
("#define FOG_NOISE_SEED 0x9E3779B9u\n",
 "",
 """// bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS=1, the banks look: m = A + B w with w =
// smoothstep(FOG_NOISE_BANK_FROM, FOG_NOISE_BANK_TO, d), d the octaves' sum above (its sd is about
// 0.13), so banks of fog (w near 1, about a third of space) with clearer air between them.
// FOG_NOISE_BANK_MEAN is the mean of w over the world (a CPU sample of 300000 points: 0.360, and
// 0.357 past the finest octave's fade), FOG_NOISE_BANK_CLEAR the m of the clear air at strength 1,
// FOG_NOISE_BANK_SQUASH how many times wider than tall a bank is (in place of FOG_NOISE_SQUASH).
#define FOG_NOISE_BANK_FROM (-0.01)
#define FOG_NOISE_BANK_TO 0.11
#define FOG_NOISE_BANK_MEAN 0.36
#define FOG_NOISE_BANK_CLEAR 0.15
#define FOG_NOISE_BANK_SQUASH 2.5
"""),
],
G: [
("    return 1.0 + noise_off0.w * clamp(2.0 * noise_off1.w * d, -1.0, 1.0);\n",
 """    // bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS=1 (marked by a gain below 0; r94's
    // gain is 2 or more): banks, m = A + B smoothstep(FOG_NOISE_BANK_FROM, FOG_NOISE_BANK_TO, d)
    // with A = noise_off0.w (the clear air's m) and B = -noise_off1.w (C++: BankFactor)
    if (noise_off1.w < 0.0) {
        return noise_off0.w -
               noise_off1.w * smoothstep(float(FOG_NOISE_BANK_FROM), float(FOG_NOISE_BANK_TO), d);
    }
""",
 ""),
],
P: [
("// plain march's (a CPU probe of 2500 rays of 32 steps over 40 m: 1.00 +- 0.01 at strength 1 and 3).\n",
 "",
 """//
// bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS=1 swaps that shaping for banks of fog with
// clearer air between them (BankFactor); MakeTail marks it with a gain below 0.
"""),
("inline constexpr std::array<float, 3> Speed{1.0f, 1.3f, 1.7f};\n",
 "",
 """/// bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS=1, the banks look (fog_noise_layout.h): w =
/// smoothstep(BankFrom, BankTo, d), m = BankClear(s) + BankGain(s) w (BankFactor), so about a third
/// of space holds banks (m 2.51 in a bank's core at strength 1) and the clear air between them has
/// m = BankClearShare (0.15); the mean of m over the world is 1, w's mean being BankMean. The banks
/// are BankSquash times wider than tall and, unless BB_FOG_NOISE_SCALE says otherwise, BankScale m
/// across. A CPU probe of a graveyard-like view (six places, every sample lit) gave the fog
/// light of the upper half of the picture a spread (sd) of 0.36 of its mean (0.15 with r94's
/// look at strength 1), and a pixel's fog light changed by 0.50 of the mean in 6 s of 1.5 m/s
/// wind (0.21).
inline constexpr float BankFrom = float(FOG_NOISE_BANK_FROM), BankTo = float(FOG_NOISE_BANK_TO);
inline constexpr float BankMean = float(FOG_NOISE_BANK_MEAN);
inline constexpr float BankClearShare = float(FOG_NOISE_BANK_CLEAR);
inline constexpr float BankSquash = float(FOG_NOISE_BANK_SQUASH);
inline constexpr float BankScale = 14.0f; ///< m: BB_FOG_NOISE_SCALE's default with the banks look
"""),
("    bool show = false;\n",
 "",
 "    bool banks = false; ///< bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS=1\n"),
("    knobs.scale = ParseScale(scale);\n    return knobs;\n}\n",
 "",
 """
/// bbport (r94b_fog-noise-visible): the knobs with BB_FOG_NOISE_BANKS's text too (null: not set).
/// Starting with 1 it turns the banks look on (it acts only while the noise is on) and the scale
/// then defaults to BankScale; anything else leaves the knobs exactly as the three-text MakeKnobs
/// makes them (r94's look).
inline Knobs MakeKnobs(const char* strength, const char* scale, const char* show,
                       const char* banks) {
    Knobs knobs = MakeKnobs(strength, scale, show);
    knobs.banks = banks != nullptr && banks[0] == '1';
    if (knobs.banks) {
        knobs.scale = std::clamp(Number(scale, BankScale), MinScale, MaxScale);
    }
    return knobs;
}
"""),
("    return 1.0f + amplitude * std::clamp(2.0f * gain * d, -1.0f, 1.0f);\n}\n",
 "",
 """
/// bbport (r94b_fog-noise-visible): the banks look's m of the clear air (w = 0) at strength s:
/// 1 - a (1 - BankClearShare), a = Amplitude(s), so strengths above 1 count as 1.
inline float BankClear(float strength) {
    return 1.0f - Amplitude(strength) * (1.0f - BankClearShare);
}

/// The banks look's gain B = a (1 - BankClearShare) / BankMean: the mean of m is then 1.
inline float BankGain(float strength) {
    return Amplitude(strength) * (1.0f - BankClearShare) / BankMean;
}

/// m of the banks look from d: clear + gain smoothstep(BankFrom, BankTo, d) (fog_noise.glsl's
/// banks line).
inline float BankFactor(float d, float clear, float gain) {
    const float t = std::clamp((d - BankFrom) / (BankTo - BankFrom), 0.0f, 1.0f);
    return clear + gain * (t * t * (3.0f - 2.0f * t));
}
"""),
("    tail.off2 = {c2[0], c2[1], c2[2], 1.0f / knobs.scale};\n",
 "",
 """    // bbport (r94b_fog-noise-visible): the banks look: w of off0 is the clear air's m, w of off1
    // minus the gain (below 0: the shader's mark of the look), and the up row of the matrix (row 1)
    // is times BankSquash / Squash, so the shader's up times Squash comes out times BankSquash. The
    // wind has no up part, so the drift's offsets need nothing.
    if (knobs.banks) {
        tail.off0[3] = BankClear(knobs.strength);
        tail.off1[3] = -BankGain(knobs.strength);
        for (std::size_t i = 4; i < 8; ++i) {
            tail.view_to_world[i] *= BankSquash / Squash;
        }
    }
"""),
],
C: [
("// and pushes what it did before.\n",
 "",
 """// bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS=1 picks the banks look (MakeTail in
// volumetric_fog_noise.h); it is read with the other knobs, once, and does nothing while the
// noise is off.
"""),
("#include <cstdio>\n",
 "#include <cmath> // bbport (r94b_fog-noise-visible)\n",
 ""),
("REPLACE",
 '            std::getenv("BB_FOG_NOISE_SHOW"));\n',
 '            std::getenv("BB_FOG_NOISE_SHOW"), std::getenv("BB_FOG_NOISE_BANKS")); // bbport r94b\n'),
("        return k;\n    }();\n",
 r"""        // bbport (r94b_fog-noise-visible): the look, said once while the noise is on
        if (k.On() && k.banks) {
            const float clear = VolumetricFogNoise::BankClear(k.strength);
            const float gain = VolumetricFogNoise::BankGain(k.strength);
            std::printf("Volumetric lighting (r94b): fog noise look: banks (BB_FOG_NOISE_BANKS=1), "
                        "%.1f m across, %.1f times wider than tall; m %.2f in the clear air, "
                        "%.2f in a bank's core (%.2f + %.2f smoothstep(%.2f, %.2f, d), mean 1); "
                        "drifting only with BB_WIND=1\n",
                        double(k.scale), double(VolumetricFogNoise::BankSquash), double(clear),
                        double(clear + gain), double(clear), double(gain),
                        double(VolumetricFogNoise::BankFrom), double(VolumetricFogNoise::BankTo));
        } else if (k.On()) {
            std::printf("Volumetric lighting (r94b): fog noise look: r94's soft patches "
                        "(BB_FOG_NOISE_BANKS not 1)\n");
        }
""",
 ""),
("} // namespace\n\nbool VolumetricLight::FogNoiseKnob() {\n",
 """// bbport (r94b_fog-noise-visible): the largest octave's offset (cells) at the last 600-march line,
// for the banks' travel since then
std::array<float, 3> banks_last{};

""",
 ""),
("        fog_noise.gated = fog_noise.area = fog_noise.drifted = 0;\n",
 r"""        // bbport (r94b_fog-noise-visible): with the banks look, how far they moved since the last
        // line: the largest octave's offset across the ground (x, z; the wind has no up part),
        // each axis wrapped the short way, in cells of the scale (its ratio is 1), so metres
        if (FogNoiseKnobs().banks) {
            const double period = VolumetricFogNoise::Period;
            double moved = 0.0;
            for (std::size_t i = 0; i < 3; i += 2) {
                const double gap =
                    std::fmod(double(cells[i]) - double(banks_last[i]) + 1.5 * period, period) -
                    0.5 * period;
                moved += gap * gap;
            }
            banks_last = cells;
            std::printf("Volumetric lighting (r94b): banks look on those 600 marches; the banks "
                        "moved %.1f m (net) since the last line\n",
                        std::sqrt(moved) * double(FogNoiseKnobs().scale));
        }
""",
 ""),
],
U: [
("//  j. The push tail holds the rows, the offsets, the amplitude, the gain and 1 / scale.\n",
 "",
 """//  k. bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS: the knobs (off unless it starts with 1;
//     then the scale's default is 14 m), the tail without it equal to r94's, with it the mark (gain
//     below 0), the clear air's m and the flatter up row; the banks' m from 0.15 to 2.51, and its
//     mean over a grid of world points (a C++ copy of fog_noise.glsl's noise) within 0.03 of 1.
"""),
("#include <initializer_list>\n",
 "",
 "#include <cstdint> // bbport (r94b_fog-noise-visible)\n"),
("} // namespace\n\nint main() {\n",
 """// bbport (r94b_fog-noise-visible): a copy of host_shaders/fog_noise.glsl's corner hash and value
// noise, for check k's mean of the banks look.
float CornerValue(std::uint32_t packed) {
    std::uint32_t h = packed + std::uint32_t(FOG_NOISE_SEED);
    h ^= h >> 16u;
    h *= 0x7feb352du;
    h ^= h >> 15u;
    h *= 0x846ca68bu;
    h ^= h >> 16u;
    return float(h >> 8u) * (1.0f / 16777216.0f);
}

float ValueNoise(const std::array<float, 3>& x) {
    const auto fade = [](float u) { return u * u * u * (u * (u * 6.0f - 15.0f) + 10.0f); };
    const auto mix = [](float a, float b, float t) { return a * (1.0f - t) + b * t; };
    const std::uint32_t mask = std::uint32_t(FOG_NOISE_PERIOD - 1);
    std::array<std::uint32_t, 3> a{}, b{};
    std::array<float, 3> u{};
    for (std::size_t i = 0; i < 3; ++i) {
        const float f = std::floor(x[i]);
        u[i] = fade(x[i] - f);
        a[i] = std::uint32_t(int(f)) & mask;
        b[i] = (a[i] + 1u) & mask;
    }
    const std::uint32_t y0 = a[1] << 8u, y1 = b[1] << 8u, z0 = a[2] << 16u, z1 = b[2] << 16u;
    const float x00 = mix(CornerValue(a[0] | y0 | z0), CornerValue(b[0] | y0 | z0), u[0]);
    const float x10 = mix(CornerValue(a[0] | y1 | z0), CornerValue(b[0] | y1 | z0), u[0]);
    const float x01 = mix(CornerValue(a[0] | y0 | z1), CornerValue(b[0] | y0 | z1), u[0]);
    const float x11 = mix(CornerValue(a[0] | y1 | z1), CornerValue(b[0] | y1 | z1), u[0]);
    return mix(mix(x00, x10, u[1]), mix(x01, x11, u[1]), u[2]);
}

""",
 ""),
("    std::printf(\"volumetric-fog-noise-test: ok\\n\");\n",
 """    // k (bbport r94b_fog-noise-visible)
    {
        for (const char* off : {static_cast<const char*>(nullptr), "", "0", "yes"}) {
            const Knobs a = MakeKnobs("1", nullptr, nullptr, off);
            const Knobs b = MakeKnobs("1", nullptr, nullptr);
            assert(!a.banks && a.strength == b.strength && a.scale == b.scale && a.show == b.show);
        }
        const Knobs banks = MakeKnobs("1", nullptr, nullptr, "1");
        assert(banks.On() && banks.banks && banks.scale == BankScale);
        assert(MakeKnobs("1", "20", nullptr, "1").scale == 20.0f);
        assert(MakeKnobs("1", "x", nullptr, "1").scale == BankScale);
        assert(MakeKnobs("1", "500", nullptr, "1").scale == MaxScale);
        assert(!MakeKnobs(nullptr, nullptr, nullptr, "1").On()); // the banks alone: still off
        assert(MakeKnobs("0", nullptr, "1", "1").strength == ShowStrength);

        // the tail: without the banks r94's words, with them the mark and the flatter up row
        Drift drift;
        drift.Advance(true, 0.0, {1.0f, 0.0f, 0.5f}, 10.0f);
        drift.Advance(true, 0.5, {1.0f, 0.0f, 0.5f}, 10.0f);
        std::array<float, 12> rows{};
        for (std::size_t i = 0; i < rows.size(); ++i) {
            rows[i] = 0.25f * float(i) - 1.0f;
        }
        const Tail r94 = MakeTail(rows, drift, MakeKnobs("1", "10", nullptr));
        const Tail same = MakeTail(rows, drift, MakeKnobs("1", "10", nullptr, "0"));
        assert(r94.view_to_world == same.view_to_world && r94.off0 == same.off0);
        assert(r94.off1 == same.off1 && r94.off2 == same.off2);
        for (const float s : {0.25f, 1.0f, MaxStrength, ShowStrength}) {
            assert(Gain(s) > 0.0f); // r94's tail never carries the mark
        }
        const Tail bt = MakeTail(rows, drift, MakeKnobs("1", "10", nullptr, "1"));
        assert(bt.off1[3] < 0.0f && Near(-bt.off1[3], BankGain(1.0f), 1e-7));
        assert(bt.off0[3] == BankClear(1.0f) && bt.off2 == r94.off2);
        for (std::size_t i = 0; i < 3; ++i) {
            assert(bt.off0[i] == r94.off0[i] && bt.off1[i] == r94.off1[i]);
        }
        for (std::size_t i = 0; i < rows.size(); ++i) {
            if (i >= 4 && i < 8) {
                assert(Near(bt.view_to_world[i], rows[i] * BankSquash / Squash, 1e-6));
            } else {
                assert(bt.view_to_world[i] == rows[i]);
            }
        }

        // the shaping: 0.15 in the clear air, 2.51 in a bank's core, mean 1 over the world
        assert(BankFrom < BankTo && BankMean > 0.0f && BankMean < 1.0f && BankSquash > Squash);
        const float clear = BankClear(1.0f), gain = BankGain(1.0f);
        assert(Near(clear, BankClearShare, 1e-6) && Near(clear + gain, 2.5111, 1e-3));
        assert(BankFactor(-1.0f, clear, gain) == clear && Near(BankFactor(1.0f, clear, gain),
                                                                clear + gain, 1e-6));
        assert(BankClear(ShowStrength) == clear && BankClear(0.5f) > clear);
        assert(Near(BankClear(0.5f) + BankGain(0.5f) * BankMean, 1.0, 1e-6));
        double sum_w = 0.0, sum_m = 0.0;
        constexpr int n = 48;
        for (int i = 0; i < n; ++i) {
            for (int j = 0; j < n; ++j) {
                for (int l = 0; l < n; ++l) {
                    // as the shader sees it: the banks' up row is times BankSquash / Squash
                    const std::array<float, 3> p{(float(i) + 0.37f) * 7.31f,
                                                 (float(j) + 0.37f) * 7.31f * 0.53f *
                                                     (BankSquash / Squash),
                                                 (float(l) + 0.37f) * 7.31f};
                    float d = 0.0f;
                    for (std::size_t k = 0; k < 3; ++k) {
                        d += Weight[k] * (ValueNoise(LatticePoint(p, k, BankScale)) - 0.5f);
                    }
                    sum_w += BankFactor(d, 0.0f, 1.0f);
                    sum_m += BankFactor(d, clear, gain);
                }
            }
        }
        const double count = double(n) * n * n;
        assert(Near(sum_w / count, BankMean, 0.01) && Near(sum_m / count, 1.0, 0.03));
    }

""",
 ""),
],
# README.md: readme_edit (a row after the BB_FOG_NOISE_SHOW row)
}

ROW = ("| `BB_FOG_NOISE_BANKS` | `1` (any text starting with `1`): with the noise on (`BB_FOG_NOISE` above 0 or `BB_FOG_NOISE_SHOW=1`), banks of fog "
       "with clearer air between them in place of the soft patches: m = A + B smoothstep(-0.01, 0.11, d), d as above, "
       "A = 1 - 0.85 a (the clear air; 0.15 at a = min(s, 1) = 1) and B = 0.85 a / 0.36 (0.36 being the mean of the "
       "smoothstep over the world, from a sample of the noise), so the mean of m stays 1 and a bank's core has m = 2.51 at "
       "strength 1; strengths above 1 count as 1. About a third of space lies in banks. The banks are 2.5 times wider than "
       "tall (in place of 1.6) and, unless `BB_FOG_NOISE_SCALE` is set, 14 m across. They drift as the patches do, only "
       "with `BB_WIND=1`, toward the wind's direction (the one the cloud shadows also take with `BB_WIND=1` when "
       "`BB_CLOUDS_DIR` is not set). A CPU probe of a graveyard-like view (every sample lit, six places) gave the fog "
       "light of the upper half of the picture a spread (sd) of 0.36 of its mean (0.15 without this knob at strength 1) "
       "and a pixel's fog light changed by 0.50 of the mean in 6 s of 1.5 m/s wind (0.21 without); a place's haze as a "
       "whole can be brighter or darker than the knob-off picture, by 0.26 of it on average, as the banks fall. The log "
       "says the look once (`Volumetric lighting (r94b): fog noise look: ...`) and, after each of the noise's 600-march "
       "lines, how far the banks moved (net, in metres; 0 without wind) since the line before. Cost: an estimate of about 10% over the noise's own (a compare and a smoothstep "
       "per lit sample; at 14 m the finest octave is kept to 34 m from the camera instead of 24 m), not measured. "
       "Missing, `0` or any text not starting with `1`: r94's look exactly (the march takes the same numbers; one compare of a push "
       "constant per lit sample) | off |\n")


SCALE_OLD = "| `BB_FOG_NOISE_SCALE` | Size of the largest patches in metres, 2 to 100 | `10` |\n"
SCALE_NEW = ("| `BB_FOG_NOISE_SCALE` | Size of the largest patches in metres, 2 to 100 | `10` (`14` with "
             "`BB_FOG_NOISE_BANKS=1`) |\n")


def readme_edit(text):
    lines = [l for l in text.split("\n") if l.startswith("| `BB_FOG_NOISE_SHOW` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_FOG_NOISE_SHOW row is there %d times, wanted 1" % len(lines))
    return (lines[0] + "\n", "", ROW)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    if path == R:
        return [("REPLACE", SCALE_OLD, SCALE_NEW), readme_edit(text)]
    return EDITS[path]


def text_checks(texts):
    """Ties a compiler cannot check: the numbers in the README and the C++ comments equal the layout's,
    the banks line sits inside r105's FOG_NOISE_VALUE_ONLY guard, after the octave sum."""
    lay = texts[L]
    vals = {}
    for name in ("FROM", "TO", "MEAN", "CLEAR", "SQUASH"):
        want = "#define FOG_NOISE_BANK_%s " % name
        hits = [l for l in lay.split("\n") if l.startswith(want)]
        if len(hits) != 1:
            raise SystemExit("text check: %s holds %r %d times" % (L, want, len(hits)))
        vals[name] = float(hits[0][len(want):].strip().strip("()"))
    core = vals["CLEAR"] + (1.0 - vals["CLEAR"]) / vals["MEAN"]
    row = [l for l in texts[R].split("\n") if l.startswith("| `BB_FOG_NOISE_BANKS` |")]
    if len(row) != 1:
        raise SystemExit("text check: README BB_FOG_NOISE_BANKS row %d times" % len(row))
    for want in ("smoothstep(%g, %g, d)" % (vals["FROM"], vals["TO"]), "1 - %g a" % (1 - vals["CLEAR"]),
                 "B = %g a / %g" % (1 - vals["CLEAR"], vals["MEAN"]), "m = %.2f at" % core,
                 "%g times wider than tall" % vals["SQUASH"], "%g at a = min(s, 1) = 1" % vals["CLEAR"],
                 "14 m across", "34 m"):
        if want not in row[0]:
            raise SystemExit("text check: README row lacks %r" % want)
    p = texts[P]
    for want in ("inline constexpr float BankScale = 14.0f;", "(m 2.51 in a bank's core",
                 "m = BankClearShare (0.15)", "tail.off1[3] = -BankGain(knobs.strength);"):
        if p.count(want) != 1:
            raise SystemExit("text check: %s holds %r %d times" % (P, want, p.count(want)))
    # the finest octave reaches FineTo scales: 2.4 x 14 = 33.6 m, the README's "34 m"
    if abs(2.4 * 14.0 - 33.6) > 1e-9 or "#define FOG_NOISE_FINE_TO 2.4" not in lay:
        raise SystemExit("text check: FOG_NOISE_FINE_TO is not 2.4")
    if abs(core - 2.5111) > 1e-3 or "Near(clear + gain, 2.5111, 1e-3)" not in texts[U]:
        raise SystemExit("text check: the bank core's m and the test disagree")
    g = texts[G]
    a = g.find("#ifndef FOG_NOISE_VALUE_ONLY")
    b = g.find("if (noise_off1.w < 0.0) {")
    c = g.find("float fine = clamp(")
    d = g.find("#endif // FOG_NOISE_VALUE_ONLY")
    if not (0 <= a < c < b < d) or g.count("if (noise_off1.w < 0.0) {") != 1:
        raise SystemExit("text check: the banks line is not after the octave sum inside FOG_NOISE_VALUE_ONLY")
    cs = texts[C]
    if cs.count('std::getenv("BB_FOG_NOISE_BANKS")') != 1 or cs.count("banks_last") != 3:
        raise SystemExit("text check: %s reads BB_FOG_NOISE_BANKS %d times, banks_last %d times"
                         % (C, cs.count('std::getenv("BB_FOG_NOISE_BANKS")'), cs.count("banks_last")))
    # the banks' travel line reads the r94 600-march block's `cells` (octave 0's offset), declared
    # before it in the same block
    blk = cs.find("const std::array<float, 3> cells = fog_noise.drift.Cells(0);")
    use = cs.find("double(cells[i]) - double(banks_last[i])")
    end = cs.find("        fog_noise.gated = fog_noise.area = fog_noise.drifted = 0;")
    if not (0 <= blk < use < end) or "#include <cmath>" not in cs:
        raise SystemExit("text check: the banks' travel line is not inside the 600-march block")
    r = texts[R]
    if r.count(SCALE_NEW) != 1 or r.find(SCALE_NEW) > r.find("| `BB_FOG_NOISE_BANKS` |"):
        raise SystemExit("text check: README scale row")
    if "inline constexpr float BankScale = 14.0f;" not in texts[P] or "(`14` with" not in SCALE_NEW:
        raise SystemExit("text check: the 14 m default and the scale row disagree")


def state_of(cur, eds, path):
    """'applied' or 'clean' for every edit alike, else refuse. An insert edit is applied when its anchor
    is there once and each inserted text once, clean when the anchor is there once and none of them;
    a replace edit is applied when the new line is there once and the old one not, clean the other
    way round."""
    done = todo = 0
    for anchor, before, after in eds:
        if anchor == "REPLACE":
            old, new = before, after
            no, nn = cur.count(old), cur.count(new)
            if nn == 1 and no == 0:
                done += 1
            elif no == 1 and nn == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced line found %d times, its new text %d times: %r"
                                 % (path, no, nn, old[:70]))
            continue
        parts = [t for t in (before, after) if t]
        na, counts = cur.count(anchor), [cur.count(t) for t in parts]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                             % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R94B_ROOT)" % ROOT)
    plan = []
    for path in (L, G, P, C, U, R):
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for anchor, before, after in eds:
                if anchor == "REPLACE":
                    cur = cur.replace(before, after)
                else:
                    cur = cur.replace(anchor, before + anchor + after)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
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
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r94btmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for anchor, before, after in reversed(eds):
            if anchor == "REPLACE":
                cur = cur.replace(after, before, 1)
                continue
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r94btmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
