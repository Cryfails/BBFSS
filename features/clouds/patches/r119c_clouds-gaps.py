# r119c_clouds-gaps: FEATURE fix on top of r119b_clouds-visible.fixed.py and r119 (BB_VOLUMETRIC_CLOUDS=1 only;
# still off by default, still costs nothing when off: nothing here runs without the CloudLayer object, which
# Rasterizer makes only when BB_VOLUMETRIC_CLOUDS starts with 1).
#
# What was wrong (build 35, jobs r119b-lt / r119b-lts): the layer drew where the sky shows (sky px share 0.105,
# march steps 11.8) but "covered share 0.992" at cover 0.50: one uniform dark grey-brown blanket that dimmed the
# dusk glow, no distinct clouds, no drift to see between captures.
# Cause (read from the code and reproduced with scratch r119c_sim.py, a pure python port of the march):
#  - SCALE. The layer read the cloud shadows' field at the shadows' size, 100 m for the biggest octave (43 m and
#    19 m for the others). A sky ray crosses the slab over 400 to 1200 m, the march step is 35 to 100 m, and the
#    sky seen through an arch spans some hundred metres at the slab: a few hundred cells. The shader's lod rule
#    (an octave fades out as the march step nears its cell) then dropped octave 1 and 2 completely (step 100 m =
#    1.0 cell of 100 m: lod 0.60, 0.00, 0.00) and left octave 0 faded: n stayed near its mean 0.5, c =
#    smoothstep(0.47, 0.59, 0.5) = 0.22 everywhere: a thin even blanket. (Sim, size 100 m: 88% of the sky
#    covered; the game said 99%.) The shadows' 100 m cells are right for ground shadows, wrong for a sky.
#  - EDGES. The shadows' edges 0.47 / 0.59 give 59% of the field some cloud and a quarter full; seen from below
#    through a 300 m slab that is a mostly overcast sky even with the right scale.
#  - DRIFT. 6 m/s at the layer is 0.23 degrees a second at 1500 m: two stills 1 to 2 s apart cannot show it.
#  - LOOK. Ambient 0.65 of the sky tint everywhere made the whole cloud darker than the glow it covers, with the
#    lit rim only 1.3 times the sky: no contrast between a rim and a base.
# Fix (all inside r119's own files):
#  1. The layer gets its own size, BB_VOLUMETRIC_CLOUDS_SIZE (m, 100 to 8000, default 800: octaves 800, 344 and
#     152 m) and its own edges (LayerLow 0.49, LayerHigh 0.65, moved by the cover as before). Sim (scratch
#     r119c_sim.py, 10 random offset sets, whole sky above 15 degrees): 52 percent of the sky has any cloud, 45
#     percent an opacity of 0.10 or more, 50 percent clear gaps (opacity under 0.03), sd 0.14 between offset
#     sets; of 60 random 30 x 40 degree windows (an arch) 51 hold both cloud and clear sky. The octaves keep their
#     detail: the lod rule is unchanged but the step is now 0.12 cell (lod 1.0, 1.0, 0.94 at a step of 100 m).
#  2. The layer's own drift: a VolumetricFogNoise::Drift of its own (layer_drift) in cells of its size, advanced
#     each frame at the one wind's heading and cloud speed (the shadows' State when the shadows are on, else the
#     layer's own State: r116's "clouds lead the wind", unchanged) times BB_VOLUMETRIC_CLOUDS_SPEED (0.25 to 60,
#     default 1). The morph through the lattice's third axis is one cell of the biggest octave in 120 s whatever
#     the speed. So the layer no longer shares the shadows' offsets or size: its clouds and the ground shadows no
#     longer line up one for one (the README says so; BB_CLOUD_SHADOWS_SCALE=800 would give the shadows the same
#     cell size but not the same offsets or edges).
#  3. Look: base of the cloud 0.3 of the ambient (was 0.4), Ambient 0.65 -> 0.50, LightGain 1.4 -> 2.2, Forward
#     2.0 -> 2.5, forward lobe 0.7 cos^4 + 0.3 cos^32 (broader glow near the moon or sun, a bright core).
#     Guesses (constants in cloud_layer_params.h and the shader); the picture decides.
#  4. A counter "visible" (word 13: sky pixels with an opacity of 0.25 or more) and the share in the 600 frame
#     line: covered (1/64 or more) says almost nothing about gaps, visible does.
# Cost: all three octaves now run in the march (before, octaves 1 and 2 had faded out and were skipped): up to
# 3 times the hashes per cloudy step, estimate 0.2 to 0.4 ms at 1080p internal with half the picture sky (was
# 0.2 to 0.3), 0.03 ms with no sky. Not measured. No new memory (the counter buffer already has 16 words).
#
# TOOL or FEATURE: FEATURE (same lane as r119).
# Edits r119's own files: cloud_layer_params.h, cloud_layer.comp, cloud_layer_layout.h, vk_cloud_layer.cpp,
# vk_cloud_layer.h, tests/test_cloud_layer.cpp, README.md (the block and the rows). No new file, no hook line in a
# shared file, no CMake change (the shader's file list is unchanged).
# Apply after r119 and r119b (it needs their text); revert BEFORE r119b (r119b's check ties its constants to
# text this patch changes: run r119c revert first).
#
# Use: python -I -X utf8 r119c_clouds-gaps.py check | apply | revert
# Root: R119C_ROOT, else <tree>. Line ends kept. Backups in r119c_backup next to this script.
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r119c_backup")
ROOT = os.environ.get("R119C_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"
TMP = ".r119ctmp"

PARAMS = R + "cloud_layer_params.h"
SHADER = H + "cloud_layer.comp"
LAYOUT = H + "cloud_layer_layout.h"
CPP = R + "vk_cloud_layer.cpp"
HDR = R + "vk_cloud_layer.h"
TEST = "engine/tests/test_cloud_layer.cpp"
README = "README.md"

PARAMS_CONSTS = '''// bbport (r119c_clouds-gaps): the layer's own size, speed and edges (the shadows' 100 m cells and edges made one
// even blanket of a sky: the r119c script's header says why).
inline constexpr float DefaultSize = 800.0f;  ///< m: BB_VOLUMETRIC_CLOUDS_SIZE, the biggest octave's cell
inline constexpr float MinSize = 100.0f, MaxSize = 8000.0f; ///< BB_VOLUMETRIC_CLOUDS_SIZE's clamp
inline constexpr float DefaultSpeed = 1.0f;   ///< BB_VOLUMETRIC_CLOUDS_SPEED: times the one wind's cloud speed
inline constexpr float MinSpeed = 0.25f, MaxSpeed = 60.0f; ///< BB_VOLUMETRIC_CLOUDS_SPEED's clamp
inline constexpr float LayerLow = 0.49f, LayerHigh = 0.65f; ///< n's edges at cover 0.5 (clear below, full above)
'''

LOD_AND_WIND = '''// ---- the size, the drift and the octaves' lod (r119c) --------------------------------------------

/// cloud_layer.comp's octave lod: an octave fades out as the march's step (in cells of the biggest octave)
/// nears its own cell (Ratio[octave] of that). At the shadows' 100 m size a 100 m step gave 0.60, 0.00, 0.00
/// (an even blanket); at the layer's 800 m it gives 1.00, 1.00, 0.94.
inline float Lod(float step_cells, std::size_t octave) {
    return std::clamp(1.6f - step_cells / VolumetricFogNoise::Ratio[octave], 0.0f, 1.0f);
}

/// The layer's drift "wind" for VolumetricFogNoise::Drift::Advance: the one wind's cloud speed (m/s) times
/// BB_VOLUMETRIC_CLOUDS_SPEED toward `heading_deg`, with the morph of the lattice's third axis for the layer's
/// size (one cell of the biggest octave in CloudShadows::MorphSeconds, whatever the speed).
inline std::array<float, 3> LayerWind(float heading_deg, float cloud_speed, const Knobs& k) {
    return CloudShadows::DriftVelocity(heading_deg, cloud_speed * k.speed, k.size);
}

'''

SHADER_NOTE = '''// bbport (r119c_clouds-gaps): the field is read at the layer's own size (Params.cloud_off0.w: 800 m for the biggest
// octave by default; the cloud shadows' 100 m cells averaged out over a sky ray into one grey blanket and made
// the lod rule below drop the finer octaves), with the layer's own edges and offsets (a drift of its own), so
// it is no longer the shadows' field. Gaps of clear sky between masses, the base 0.3 of the ambient, a brighter
// lit rim and a forward glow toward the light.
'''

TEST_BLOCK = '''    // j. (r119c) the layer's own size, speed, edges and drift: separate masses with gaps, not a blanket.
    {
        const Knobs d = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr);
        assert(d.size == DefaultSize && d.size == 800.0f && d.speed == DefaultSpeed && d.speed == 1.0f);
        const Knobs c = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "1", "999");
        assert(c.size == MinSize && c.speed == MaxSpeed);
        const Knobs e = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "99999", "0");
        assert(e.size == MaxSize && e.speed == MinSpeed);
        const Knobs f = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "abc", "nan");
        assert(f.size == DefaultSize && f.speed == DefaultSpeed);
        // the edges at cover 0.5 are the layer's own (not the shadows')
        const Edges same = CoverEdges(LayerLow, LayerHigh, DefaultCover);
        assert(same.low == LayerLow && same.high == LayerHigh && LayerHigh > LayerLow);
        // the lod: a 100 m step is one cell of a 100 m size (octaves 1 and 2 gone: the blanket), 0.125 cell of 800 m
        assert(Near(Lod(1.0f, 0), 0.6, 1e-6) && Lod(1.0f, 1) == 0.0f && Lod(1.0f, 2) == 0.0f);
        assert(Lod(100.0f / DefaultSize, 0) == 1.0f && Lod(100.0f / DefaultSize, 1) == 1.0f &&
               Near(Lod(100.0f / DefaultSize, 2), 1.6 - 0.125 / 0.19, 1e-4));
        // the field at the default size and edges (zero offsets), 3600 points over 24 km: python port of the
        // march's noise gives clear 0.461, in between 0.353, full 0.186 (the shadows' 100 m size: the same
        // shares, but a sky ray averages them out)
        const Offsets zero{};
        int clear = 0, partial = 0, full = 0;
        for (int i = 0; i < 60; ++i) {
            for (int j = 0; j < 60; ++j) {
                const std::array<float, 3> x{float(i) * 397.0f / DefaultSize, 0.0f, float(j) * 311.0f / DefaultSize};
                const float cover = Smoothstep(LayerLow, LayerHigh, FieldN(x, zero));
                if (cover <= 0.0f) {
                    ++clear;
                } else if (cover >= 0.99f) {
                    ++full;
                } else {
                    ++partial;
                }
            }
        }
        assert(clear + partial + full == 3600);
        assert(clear > 1260 && clear < 2090 && full > 360 && full < 1080 && partial > 720);
        // the drift: the wind's cloud speed times the knob moves the layer's offsets, the morph does not scale
        const Knobs fast = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "2");
        assert(LayerWind(0.0f, 6.0f, fast)[1] == LayerWind(0.0f, 6.0f, d)[1]);
        assert(Near(LayerWind(0.0f, 6.0f, d)[0], 6.0, 1e-5) && Near(LayerWind(0.0f, 6.0f, fast)[0], 12.0, 1e-5));
        VolumetricFogNoise::Drift one, two;
        one.Advance(true, 10.0, LayerWind(0.0f, 6.0f, d), d.size);
        one.Advance(true, 10.5, LayerWind(0.0f, 6.0f, d), d.size);
        two.Advance(true, 10.0, LayerWind(0.0f, 6.0f, fast), fast.size);
        two.Advance(true, 10.5, LayerWind(0.0f, 6.0f, fast), fast.size);
        const std::array<float, 3> a = one.Cells(0), b = two.Cells(0);
        assert(a[0] > 0.0f && a[2] > 0.0f && Near(b[0], 2.0 * a[0], 1e-5) && Near(b[2], 2.0 * a[2], 1e-5));
        assert(Near(a[0] / a[2], VolumetricFogNoise::YawCos[0] / VolumetricFogNoise::YawSin[0], 1e-3));
        // the visible share of the counters
        Totals t;
        std::array<std::uint32_t, CL_WORDS> frame{};
        frame[CL_WORD_SKY] = 400;
        frame[CL_WORD_VISIBLE] = 100;
        t.Add(frame);
        assert(Near(SharesOf(t).visible, 0.25, 1e-9) && SharesOf(Totals{}).visible == 0.0);
        assert(CL_WORD_VISIBLE == 13u && CL_VISIBLE_ALPHA == 0.25);
    }
'''

README_DENSITY_OLD = ("The density is the cloud shadows' own field (`BB_CLOUD_SHADOWS`, r105b): the same noise, size, edges, "
                      "offsets, direction and drift, so a shadow sweeping the ground belongs to the cloud overhead (exact "
                      "for a point of the layer's reference height, 35% of the slab's thickness up; the top of a full "
                      "cloud, 195 m higher, would cast its shadow about 480 m further along the light with the light 22 "
                      "degrees up). While")
README_DENSITY_NEW = ("The density is the cloud shadows' kind of field (`BB_CLOUD_SHADOWS`, r105b: the same three octaves "
                      "of value noise) at the layer's own size and with its own edges (r119c: `BB_VOLUMETRIC_CLOUDS_SIZE`, "
                      "800 m for the biggest octave, so a cloud is some hundred metres to a kilometre across with clear "
                      "sky between the masses; the shadows' 100 m cells averaged out over a sky ray into one grey "
                      "blanket; edges smoothstep(0.49, 0.65, n) at cover 0.5, about half of the sky covered). The "
                      "layer drifts offsets of its own, so its clouds and the ground shadows no longer line up one for "
                      "one. The heading and speed are the one wind's cloud heading and speed (times "
                      "`BB_VOLUMETRIC_CLOUDS_SPEED`). While")
README_LOG_OLD = "the share of the sky that is covered, the mean opacity,"
README_LOG_NEW = ("the share of the sky that is covered, the share that is visible (an opacity of 0.25 or more), the "
                  "mean opacity,")
README_COST_OLD = "an estimate of 0.2 to 0.3 ms at 1080p internal"
README_COST_NEW = ("an estimate of 0.2 to 0.4 ms at 1080p internal (r119c: all three noise octaves now run in the march, "
                   "where at 100 m cells the finer two had faded out and were skipped)")
README_COVER_OLD = ("| `BB_VOLUMETRIC_CLOUDS_COVER` | 0 to 1. At `0.5` the layer uses the cloud shadows' own edges "
                    "(smoothstep(0.47, 0.59, n) of the same n), so the two agree; each 0.1 more or less moves both edges "
                    "of n by 0.03 (lower edges, more and wider cloud, with more cover; higher edges, less, with less). "
                    "The shadows keep their own edges | `0.5` |")
README_COVER_NEW = ("| `BB_VOLUMETRIC_CLOUDS_COVER` | 0 to 1. At `0.5` the layer's edges are smoothstep(0.49, 0.65, n): about "
                    "half of the sky has cloud and half is clear gaps; each 0.1 more or less moves both edges of n by 0.03 "
                    "(lower edges, more and wider cloud, with more cover; higher edges, less, with less). The shadows keep "
                    "their own edges | `0.5` |\n"
                    "| `BB_VOLUMETRIC_CLOUDS_SIZE` | The cell of the biggest noise octave in metres, 100 to 8000 (the finer "
                    "octaves are 0.43 and 0.19 of it): the size of the cloud masses. At the shadows' 100 m the clouds "
                    "average out into an even blanket | `800` |\n"
                    "| `BB_VOLUMETRIC_CLOUDS_SPEED` | 0.25 to 60: times the one wind's cloud speed (`BB_WIND_SPEED` x 4, 6 m/s "
                    "at the wind's default 1.5 m/s: 0.2 degrees a second at 1500 m, too slow to see in two stills). The "
                    "heading is the wind's; the shapes morph slowly whatever the speed | `1` |")

# (file, old, new): each old found exactly once before, each new exactly once after.
EDITS = [
    # ---- the layout: the visible counter
    (LAYOUT, "#define CL_Z_EDGE4 100.0\n#define CL_WORDS 16u\n",
     "#define CL_Z_EDGE4 100.0\n"
     "// bbport (r119c_clouds-gaps): the sky pixels with an opacity of CL_VISIBLE_ALPHA or more (a cloud that shows)\n"
     "#define CL_WORD_VISIBLE 13u\n"
     "#define CL_VISIBLE_ALPHA 0.25\n"
     "#define CL_WORDS 16u\n"),
    # ---- the shader: look, glow, the counter, the note
    (SHADER, "// 0.35 + 0.65 c of it from the flat base up, with a rounded top.\n",
     "// 0.35 + 0.65 c of it from the flat base up, with a rounded top.\n" + SHADER_NOTE),
    (SHADER, "    float forward = pow(max(cos_l, 0.0), 6.0);\n",
     "    float cl = max(cos_l, 0.0); // bbport (r119c_clouds-gaps): a broad glow and a bright core toward the light\n"
     "    float forward = 0.7 * pow(cl, 4.0) + 0.3 * pow(cl, 32.0);\n"),
    (SHADER, "        float lam = tone.x * mix(0.4, 1.0, v);\n", "        float lam = tone.x * mix(0.3, 1.0, v);\n"),
    (SHADER, "    if (alpha >= 1.0 / 64.0) atomicAdd(group_counts[CL_WORD_COVERED], 1u);\n",
     "    if (alpha >= 1.0 / 64.0) atomicAdd(group_counts[CL_WORD_COVERED], 1u);\n"
     "    if (alpha >= float(CL_VISIBLE_ALPHA)) atomicAdd(group_counts[CL_WORD_VISIBLE], 1u); // bbport (r119c)\n"),
    # ---- the params header
    (PARAMS, "inline constexpr float DefaultSkyZ = 500.0f; ///< m: view z beyond which a pixel is sky (the dome: 1500 m and more)\n",
     "inline constexpr float DefaultSkyZ = 500.0f; ///< m: view z beyond which a pixel is sky (the dome: 1500 m and more)\n"
     + PARAMS_CONSTS),
    (PARAMS, "inline constexpr float Ambient = 0.65f;      ///< the sky's brightness x this at a cloud's top (0.4 of it at its base)",
     "inline constexpr float Ambient = 0.50f;      ///< the sky's brightness x this at a cloud's top (0.3 of it at its base)"),
    (PARAMS, "inline constexpr float LightGain = 1.4f;", "inline constexpr float LightGain = 2.2f;"),
    (PARAMS, "inline constexpr float Forward = 2.0f;       ///< the forward scatter's gain (phase: 0.45 + this x cos^6)",
     "inline constexpr float Forward = 2.5f;       ///< the forward scatter's gain (phase: 0.45 + this x (0.7 cos^4 + 0.3 cos^32))"),
    (PARAMS, "    float sky_z = DefaultSkyZ; ///< view z (m) beyond which a pixel counts as sky too; 0: depth 1 only\n",
     "    float sky_z = DefaultSkyZ; ///< view z (m) beyond which a pixel counts as sky too; 0: depth 1 only\n"
     "    float size = DefaultSize;   ///< m: the biggest octave's cell (r119c)\n"
     "    float speed = DefaultSpeed; ///< times the one wind's cloud speed (r119c)\n"),
    (PARAMS, "                       const char* sky_z = nullptr) {\n",
     "                       const char* sky_z = nullptr, const char* size = nullptr,\n"
     "                       const char* speed = nullptr) {\n"),
    (PARAMS, "    k.sky_z = std::clamp(CloudShadows::Number(sky_z, DefaultSkyZ), 0.0f, MaxSkyZ);\n",
     "    k.sky_z = std::clamp(CloudShadows::Number(sky_z, DefaultSkyZ), 0.0f, MaxSkyZ);\n"
     "    k.size = std::clamp(CloudShadows::Number(size, DefaultSize), MinSize, MaxSize); // bbport (r119c)\n"
     "    k.speed = std::clamp(CloudShadows::Number(speed, DefaultSpeed), MinSpeed, MaxSpeed);\n"),
    (PARAMS, "[7], [11]); `proj`: x scale, y scale (signed), z scale, z offset; `state` and `shadow`: the\n"
             "/// cloud shadows' State and Knobs (the drift, size and edges); `slope`: Slope(L) of the last light\n",
     "[7], [11]); `proj`: x scale, y scale (signed), z scale, z offset; `drift`: the layer's own\n"
     "/// offsets (r119c; its size and edges are the knobs' and LayerLow / LayerHigh); `slope`: Slope(L) of the last light\n"),
    (PARAMS, "                         const CloudShadows::State& state, const CloudShadows::Knobs& shadow,\n"
             "                         const Knobs& knobs, const std::array<float, 3>& light, bool light_valid,\n",
     "                         const VolumetricFogNoise::Drift& drift,\n"
     "                         const Knobs& knobs, const std::array<float, 3>& light, bool light_valid,\n"),
    (PARAMS, "    const Edges edges = CoverEdges(shadow.LowEdge(), shadow.HighEdge(), knobs.cover);\n"
             "    const auto c0 = state.Offsets().Cells(0), c1 = state.Offsets().Cells(1),\n"
             "               c2 = state.Offsets().Cells(2);\n"
             "    p.off0 = {c0[0], c0[1], c0[2], 1.0f / shadow.scale};\n",
     "    const Edges edges = CoverEdges(LayerLow, LayerHigh, knobs.cover); // bbport (r119c_clouds-gaps)\n"
     "    const auto c0 = drift.Cells(0), c1 = drift.Cells(1), c2 = drift.Cells(2);\n"
     "    p.off0 = {c0[0], c0[1], c0[2], 1.0f / knobs.size};\n"),
    (PARAMS, "    double steps = 0.0;   ///< march steps a marched sky pixel took, on average\n",
     "    double steps = 0.0;   ///< march steps a marched sky pixel took, on average\n"
     "    double visible = 0.0; ///< sky pixels with an opacity of CL_VISIBLE_ALPHA or more / sky pixels (r119c)\n"),
    (PARAMS, "    s.steps = hit > 0.0 ? double(t.words[CL_WORD_STEPS]) / hit : 0.0;\n",
     "    s.steps = hit > 0.0 ? double(t.words[CL_WORD_STEPS]) / hit : 0.0;\n"
     "    s.visible = sky > 0.0 ? double(t.words[CL_WORD_VISIBLE]) / sky : 0.0;\n"),
    (PARAMS, "CL_Z_EDGE1 == 1000.0 && CL_Z_EDGE2 == 500.0 && CL_Z_EDGE3 == 250.0 && CL_Z_EDGE4 == 100.0);",
     "CL_Z_EDGE1 == 1000.0 && CL_Z_EDGE2 == 500.0 && CL_Z_EDGE3 == 250.0 && CL_Z_EDGE4 == 100.0);\n"
     "static_assert(CL_WORD_VISIBLE == CL_WORD_Z_LAST + 1u && CL_WORD_VISIBLE < CL_WORDS && CL_VISIBLE_ALPHA == 0.25);"),
    (PARAMS, "} // namespace CloudLayerParams", LOD_AND_WIND + "} // namespace CloudLayerParams"),
    # ---- the header of the class
    (HDR, "// BB_CLOUDS_DIR, BB_WIND_DIR, BB_WIND_SPEED, and the wind's direction with BB_WIND=1).\n#pragma once\n",
     "// BB_CLOUDS_DIR, BB_WIND_DIR, BB_WIND_SPEED, and the wind's direction with BB_WIND=1).\n"
     "//\n"
     "// bbport (r119c_clouds-gaps): the layer now reads the noise at its own size (BB_VOLUMETRIC_CLOUDS_SIZE, 800 m)\n"
     "// with its own edges and its own drift (layer_drift, advanced at that heading and speed times\n"
     "// BB_VOLUMETRIC_CLOUDS_SPEED), so it is no longer the cloud shadows' field and its clouds and the ground\n"
     "// shadows no longer line up one for one; the heading and speed are still the one wind's.\n"
     "#pragma once\n"),
    (HDR, "    CloudShadows::State own_state;         ///< the layer's clock when they are off\n",
     "    CloudShadows::State own_state;         ///< the layer's clock when they are off\n"
     "    VolumetricFogNoise::Drift layer_drift; ///< (r119c) the layer's own cloud offsets, in cells of its size\n"),
    # ---- the engine
    (CPP, '        std::getenv("BB_VOLUMETRIC_CLOUDS_STEPS"), std::getenv("BB_VOLUMETRIC_CLOUDS_SKYZ"));\n',
     '        std::getenv("BB_VOLUMETRIC_CLOUDS_STEPS"), std::getenv("BB_VOLUMETRIC_CLOUDS_SKYZ"),\n'
     '        std::getenv("BB_VOLUMETRIC_CLOUDS_SIZE"), std::getenv("BB_VOLUMETRIC_CLOUDS_SPEED"));\n'),
    (CPP, "                     CL_DIV, double(clk.scale), double(clk.Velocity()),\n",
     "                     CL_DIV, double(knobs.size), double(clk.Velocity() * knobs.speed),\n"),
    (CPP, "    ++stats.frames;\n",
     "    // bbport (r119c_clouds-gaps): the layer's own offsets move at the one wind's cloud heading and speed (the\n"
     "    // weather's speed of this frame included) times BB_VOLUMETRIC_CLOUDS_SPEED; Drift clamps a long gap\n"
     "    layer_drift.Advance(true, Seconds(),\n"
     "                        CL::LayerWind(Direction(), ClockState().Velocity(ClockKnobs()), knobs), knobs.size);\n"
     "    ++stats.frames;\n"),
    (CPP, "    const CloudShadows::Knobs& clk = ClockKnobs();\n"
          "    // two lines, each under 300 characters\n"
          '    BbReport::Printf("Volumetric clouds (r119): sky px share %.3f, covered share %.3f, mean opacity "\n'
          '                     "%.3f, march steps %.1f, heading %.0f deg, drift %.1f m/s (same as the cloud "\n'
          '                     "shadows: %s)\\n",\n'
          "                     s.sky, s.covered, s.opacity, s.steps, double(state.Direction()),\n"
          "                     double(clk.Velocity()),\n",
     "    // two lines, each under 300 characters (r119c: the first has the visible share, the size and the speed)\n"
     '    BbReport::Printf("Volumetric clouds (r119): sky px share %.3f, covered share %.3f, visible share %.3f, "\n'
     '                     "mean opacity %.3f, march steps %.1f, heading %.0f deg, drift %.1f m/s, size %.0f m "\n'
     '                     "(heading and speed same as the cloud shadows\': %s)\\n",\n'
     "                     s.sky, s.covered, s.visible, s.opacity, s.steps, double(state.Direction()),\n"
     "                     double(ClockState().Velocity(ClockKnobs()) * knobs.speed), double(knobs.size),\n"),
    (CPP, "    const CL::Params params = CL::MakeParams(camera.inv_view, camera.proj, ClockState(),\n"
          "                                             ClockKnobs(), knobs, light, light_known, slope, jitter);\n",
     "    const CL::Params params = CL::MakeParams(camera.inv_view, camera.proj, layer_drift, knobs, light,\n"
     "                                             light_known, slope, jitter); // bbport (r119c): own drift\n"),
    # ---- the test
    (TEST, "        const CloudShadows::Knobs shadow = CloudShadows::MakeKnobs(\"1\", \"120\", nullptr, \"45\");\n"
           "        CloudShadows::State state;\n"
           "        const Knobs knobs = MakeKnobs(\"1\", \"0.7\", \"1.5\", \"800\", nullptr, \"250\", \"16\", \"4000\");\n",
     "        VolumetricFogNoise::Drift drift; // bbport (r119c_clouds-gaps): the layer's own offsets\n"
     "        const Knobs knobs = MakeKnobs(\"1\", \"0.7\", \"1.5\", \"800\", nullptr, \"250\", \"16\", \"4000\", \"1200\", \"3\");\n"),
    (TEST, "        const Params p = MakeParams(rows, proj, state, shadow, knobs, light, true, slope, {0.25f, -0.5f});\n",
     "        const Params p = MakeParams(rows, proj, drift, knobs, light, true, slope, {0.25f, -0.5f});\n"),
    (TEST, "        assert(Near(p.off0[3], 1.0 / 120.0, 1e-7));\n"
           "        const Edges e = CoverEdges(shadow.LowEdge(), shadow.HighEdge(), 0.7f);\n",
     "        assert(Near(p.off0[3], 1.0 / 1200.0, 1e-7));\n"
     "        const Edges e = CoverEdges(LayerLow, LayerHigh, 0.7f);\n"),
    (TEST, "p.off2[2] == 0.0f); // a fresh State\n", "p.off2[2] == 0.0f); // a fresh Drift\n"),
    (TEST, "        const Params dark = MakeParams(rows, proj, state, shadow, knobs, {1.0f, 0.0f, 0.0f}, false,\n",
     "        const Params dark = MakeParams(rows, proj, drift, knobs, {1.0f, 0.0f, 0.0f}, false,\n"),
    (TEST, '    std::puts("cloud layer: ok");', TEST_BLOCK + '    std::puts("cloud layer: ok");'),
    # ---- the README
    (README, README_DENSITY_OLD, README_DENSITY_NEW),
    (README, README_LOG_OLD, README_LOG_NEW),
    (README, README_COST_OLD, README_COST_NEW),
    (README, README_COVER_OLD, README_COVER_NEW),
]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    """Ties (rule 10): the README, the layout, the header and the shader agree."""
    params, layout, shader, readme = texts[PARAMS], texts[LAYOUT], texts[SHADER], texts[README]
    rows = {k: [l for l in readme.split("\n") if l.startswith("| `%s` |" % k)]
            for k in ("BB_VOLUMETRIC_CLOUDS_SIZE", "BB_VOLUMETRIC_CLOUDS_SPEED", "BB_VOLUMETRIC_CLOUDS_COVER")}
    if any(len(v) != 1 for v in rows.values()):
        raise SystemExit("tie check: one README row each for SIZE, SPEED and COVER")
    if "100 to 8000" not in rows["BB_VOLUMETRIC_CLOUDS_SIZE"][0] or "| `800` |" not in rows["BB_VOLUMETRIC_CLOUDS_SIZE"][0]:
        raise SystemExit("tie check: README SIZE row against DefaultSize / MinSize / MaxSize")
    if "0.25 to 60" not in rows["BB_VOLUMETRIC_CLOUDS_SPEED"][0] or "| `1` |" not in rows["BB_VOLUMETRIC_CLOUDS_SPEED"][0]:
        raise SystemExit("tie check: README SPEED row against DefaultSpeed / MinSpeed / MaxSpeed")
    if "smoothstep(0.49, 0.65, n)" not in rows["BB_VOLUMETRIC_CLOUDS_COVER"][0] or "smoothstep(0.49, 0.65, n) at cover" not in readme:
        raise SystemExit("tie check: README's edges 0.49, 0.65")
    for text in ("DefaultSize = 800.0f;", "MinSize = 100.0f, MaxSize = 8000.0f;", "DefaultSpeed = 1.0f;",
                 "MinSpeed = 0.25f, MaxSpeed = 60.0f;", "LayerLow = 0.49f, LayerHigh = 0.65f;",
                 "Ambient = 0.50f;", "LightGain = 2.2f;", "Forward = 2.5f;"):
        if params.count(text) != 1:
            raise SystemExit("tie check: %s" % text)
    if "800 m for the biggest octave" not in readme:
        raise SystemExit("tie check: README's 800 m")
    for define in ("#define CL_WORD_VISIBLE 13u\n", "#define CL_VISIBLE_ALPHA 0.25\n", "#define CL_WORDS 16u\n",
                   "#define CL_WORD_Z_LAST 12u\n"):
        if layout.count(define) != 1:
            raise SystemExit("tie check: layout %s" % define.strip())
    if "CL_WORD_VISIBLE" not in shader or shader.count("mix(0.3, 1.0, v)") != 1:
        raise SystemExit("tie check: shader's visible counter and base")
    if "visible (an opacity of 0.25 or more)" not in readme:
        raise SystemExit("tie check: README's visible share against CL_VISIBLE_ALPHA")
    if not all(ord(c) < 128 for _, _, new in EDITS for c in new):
        raise SystemExit("new text must be ASCII")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R119C_ROOT)" % ROOT)
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
            raise SystemExit("%s: %d of %d edits in place, %d ready to apply (are r119 and r119b applied? "
                             "is another patch editing the same text?)" % (path, done, len(mine), todo))
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
    print("reverted (%d files edited back)" % len(files))


main()
