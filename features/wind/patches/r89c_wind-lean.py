# r89c_wind-lean: FEATURE patch (wind, "Foliage sway"). Off unless the plant sway is on (BB_WIND=1
# and BB_WIND_SWAY above 0); then the default motion of the plants. Applies on top of r89 and r89b
# (S/r89_wind-foliage-sway.fixed.py, S/r89b_wind-sway-ripple.fixed.py); revert r89c before r89b.
#
# The owner, 2026-11-15 22:58, on the 4K clip of r89 (one-piece sway) beside r89b (ripple), verbatim:
# "The sway on the trees either should be removed or very subtle unless it's strong wind. The
# foliage moving should not wave but move in the direction of the wind and it should be not as fast
# unless the wind is really blowing"; 23:01: "The wave should just be very subtle".
#
# What r89c does (bbport_wind_sway.h: LeanAt, FillLean, Envelope, Displace; both shader emitters
# the same rule operation for operation):
#  1. The lean (BB_WIND_SWAY_STYLE unset or anything but "wave"): each plant bends DOWNWIND while a
#     gust front passes over it and eases back toward its rest pose when it has passed:
#       along = g (LeanRest D + D E + SA E sin a1),  cross = g SC E sin a2,
#     E being r89b's gust-front envelope (0 in a calm, up to 2 in a front, fronts travelling
#     downwind so neighbours bend one after the other) with each front's sine skewed,
#     sin(p + LeanSkew sin p): a front comes in about twice as fast as it goes (pushed over fast,
#     recovering slowly). g is r89's gust factor at the plant (0.3-2). SA <= 0.6 D, so along >= 0:
#     never back past rest. With BB_WIND_SWAY_WAVE=0 nothing moves across the wind at all.
#  2. Everything is a function of the wind speed v (BB_WIND_SPEED, 0-4 m/s), none a constant:
#     D = BendMax (v / 4 m/s)^2 x BB_WIND_SWAY (0.12 m at 4 m/s: drag goes with v^2); the subtle
#     wave SA = 0.15 D and SC = 0.075 D times BB_WIND_SWAY_WAVE (0 none, 1 default, up to 4) at
#     0.15 + 0.15 v Hz (0.375 Hz at 1.5 m/s) along, 1.5 times that across; the leaves flutter
#     (r89b's waves) only from 2.5 m/s, 0.012 m x WAVE in full at 4 m/s; the fronts pass every
#     9 m / v (6 s at 1.5 m/s). Zero wind: nothing moves.
#  3. Trees: r89 knows of a mesh only its lowest point (base key); r89c adds its highest (a crown
#     key per slot, the GPU's atomic minimum of the key of 8192 m - y, in the second half of r89's
#     1024 base keys: plant slots are now 512, the region keeps its 8192 bytes). A mesh whose
#     height (crown - base) is over 2 m is a tree by tau = smoothstep(2, 3.5 m, height): its weight
#     goes from r89's smoothstep(h / 0.75 m) to Ta smoothstep((h / height - 0.5) / 0.5): the lower
#     half of the mesh (trunk, main branches) still, the top of the crown up to Ta, and Ta =
#     smoothstep(1, 4 m/s, v) (0.07 at 1.5 m/s, 0.74 at 3, 1 at 4). A bush up to 2 m tall is a
#     bush; 2-3.5 m blends.
#  4. The tip dips as it bends (a stem keeps its length): y -= d^2 / (2 h), held to 0.4 m.
#  5. Kept: r89's hook (first in the vertex epilogue of both emitters, before the motion store and
#     the ray traced capture), r89b's re-anchored phases (Ripple: a turning camera or wind moves
#     nothing), the 1 s ramp, the do-nothing rule indoors (no lone plants), BB_WIND_SWAY as the
#     overall scale. BB_WIND_SWAY_STYLE=wave gives r89b's motion unchanged (FillRipple; then
#     BB_WIND_SWAY_RIPPLE=0 gives r89's one-piece motion), for side by side clips. With the lean,
#     BB_WIND_SWAY_RIPPLE=0 bends every plant in step, above 0 the fronts travel (their lengths
#     9, 13, 17 m divided by it). BB_WIND_SWAY_SHOW=1 still makes the motion 2.5x larger and the
#     fronts 2.5x closer.
#
# Cost off (BB_WIND unset or BB_WIND_SWAY=0): nothing new runs: no pipeline has the Sway bit, no
# view words are written, the knobs are read at the first sway view or log line only. With the
# sway on: per plant vertex 2 more loads (crown key, the RippleD row again), 3 more sines (the
# skew), about 45 more operations and one more test (the crown offer; its atomic only when a vertex
# is higher than the crown so far); the CPU writes 4 more words per view. No buffer grows.
# Shader binaries: SwayShaderBinaryVersion 10 -> 11 and HangShaderBinaryVersion 20 -> 21 (the sway
# SPIR-V changed, also in r112's hang pipelines), so cached sway and hang shaders are built again;
# no other shader changes.
#
# Depends on r112_wind-more-things (applied first): the dip is inserted before the position store
# and is zeroed for r112's hang draws (its hang_on / hang names); the Hang version line is r112's.
# Order: apply r112 then r89c; revert r89c before r112 (r112's check reads "3 of 4 edits applied"
# in vk_pipeline_serialization.cpp while r89c is on, because of the Hang version bump).
#
# Files: engine/gpu/shim/bbport_wind_sway.h, emit_spirv_special.cpp (EmitVertexSway),
# lifter/lift_stage.cpp (Lift_::VertexSway), vk_rasterizer_effects.cpp (FillLean or FillRipple,
# the crown key reset, the log lines), vk_pipeline_serialization.cpp (two binary versions),
# engine/tests/test_wind_sway.cpp (slot count, lean tests), README.md (two rows, two notes).
#
# Log (only with the sway on): once "Wind sway lean (r89c) at 0.5/1.5/3.0/4.0 m/s: tip bend up to
# ..." and "Wind sway lean (r89c, BB_WIND_SWAY_WAVE=1.00, RIPPLE=1.00): plants bend downwind ...";
# r89's line every 600 frames starts "Wind sway (r89): lean wave 1.00 (fronts 9.0 m apart, ...)".
#
# Use: python -I -X utf8 r89c_wind-lean.py check | apply | revert (root from R89C_ROOT, else
# <tree>). Files keep their line ends. Originals are kept in r89c_backup/ next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89c_backup")
ROOT = os.environ.get("R89C_ROOT") or "<tree>"
G = "engine/gpu/"
S = G + "shadps4/shader_recompiler/"
R = G + "shadps4/video_core/renderer_vulkan/"
L = G + "shim/lifter/"
HEADER = G + "shim/bbport_wind_sway.h"
EMIT = S + "backend/spirv/emit_spirv_special.cpp"
LIFT = L + "lift_stage.cpp"
EFFECTS = R + "vk_rasterizer_effects.cpp"
SERIAL = R + "vk_pipeline_serialization.cpp"
TEST = "engine/tests/test_wind_sway.cpp"
README = "README.md"

H_SLOTS = r'''/// bbport (r89c_wind-lean): the base keys' second half holds the crown keys: slot i's crown key
/// (CrownKey: the highest world y any vertex of its stream had) at CrownAt + i, so a stream's
/// slot is below PlantSlots (Slots) and the region keeps its size
inline constexpr std::uint32_t PlantSlots = BaseSlots / 2, CrownAt = BaseAt + PlantSlots;
'''

H_CONSTANTS = r'''
// bbport (r89c_wind-lean): the lean, the default motion with the sway (BB_WIND_SWAY_STYLE unset or
// anything but "wave"; the owner: plants should not wave but bend the way the wind blows, slowly
// unless it really blows, trees barely unless it is strong, a wave only very subtle). FillLean
// writes the ripple's words so that the shaders' ripple code (RippleOr, Envelope) gives
//   along = g (LeanRest D + D E + SA E sin a1), cross = g SC E sin a2, the leaves with LF,
// E the gust fronts' envelope with each front's sine skewed (sin(p + LeanSkew sin p): a front
// comes in in about a third of its time and goes in two thirds), so a plant is pushed downwind as
// a front passes and eases back, never past its rest (WaveRatio WaveMax < 1: along >= 0). Of the
// wind speed v: D = BendMax (v / BbWind::MaxSpeed)^2 x BB_WIND_SWAY; SA = WaveRatio D and SC =
// WaveCross D, each x BB_WIND_SWAY_WAVE, at WaveHz0 + WaveHzPerSpeed v Hz along (WaveCrossFactor
// times that across); LF = Leaf x the wave knob x smoothstep(LeafFrom, LeafFull, v). Trees: a mesh
// whose crown key (its highest point, CrownAt) is more than TreeLo m above its lowest point takes,
// by tau = smoothstep(TreeLo, TreeHi, its height), the weight Ta smoothstep((h / height -
// CrownLow) / (1 - CrownLow)) in place of r89's smoothstep(h / Height): the lower half (trunk and
// main branches) still, Ta = smoothstep(TreeCalm, TreeFull, v). The tip dips by d^2 / (2 h)
// (held to MaxAlong): a stem keeps its length. The view's RippleD.y (1 with the lean, 0 else)
// turns the skew, the trees and the dip on; RippleD.z holds Ta.
inline constexpr float BendMax = 0.12f;  ///< m: D at BbWind::MaxSpeed with BB_WIND_SWAY 1
inline constexpr float LeanRest = 0.25f; ///< the steady lean, a share of D
inline constexpr float LeanSkew = 0.6f;  ///< the fronts' skew: in fast, back slowly
inline constexpr float WaveRatio = 0.15f, WaveCross = 0.075f; ///< the wave's shares of D
inline constexpr float WaveHz0 = 0.15f, WaveHzPerSpeed = 0.15f, WaveCrossFactor = 1.5f;
inline constexpr float LeafFrom = 2.5f, LeafFull = 4.0f; ///< m/s: the leaves flutter from, in full
inline constexpr float TreeLo = 2.0f, TreeHi = 3.5f;     ///< m: a mesh this tall is (all) a tree
inline constexpr float TreeInv = 1.0f / (TreeHi - TreeLo);
inline constexpr float CrownLow = 0.5f; ///< the share of a tree's height that stays still
inline constexpr float CrownInv = 1.0f / (1.0f - CrownLow);
inline constexpr float TreeCalm = 1.0f, TreeFull = 4.0f; ///< m/s: trees still below, in full at
inline constexpr float MeshFloor = 0.1f, DipFloor = 0.05f; ///< m
inline constexpr float WaveDefault = 1.0f, WaveMax = 4.0f; ///< BB_WIND_SWAY_WAVE
static_assert(WaveRatio * WaveMax < 1.0f && WaveCross <= WaveRatio, "never back past rest");
'''

H_CROWN = r'''/// bbport (r89c_wind-lean): a world y as a crown key, the key of HeightBias - y: the smallest
/// key is the highest y (y below HeightBias; ResetKey is above every key a vertex offers).
[[nodiscard]] inline std::uint32_t CrownKey(float y) {
    return std::bit_cast<std::uint32_t>(std::max(HeightBias - y, 0.0f));
}

[[nodiscard]] inline float KeyCrown(std::uint32_t key) {
    return HeightBias - std::bit_cast<float>(key);
}

'''

H_LEAN = r'''/// bbport (r89c_wind-lean): BB_WIND_SWAY_STYLE and BB_WIND_SWAY_WAVE.
struct LeanKnob {
    bool lean = true;         ///< false: BB_WIND_SWAY_STYLE=wave (r89b's ripple, FillRipple)
    float wave = WaveDefault; ///< BB_WIND_SWAY_WAVE: the subtle wave's size, 0-WaveMax
};

[[nodiscard]] inline LeanKnob ParseLean(const char* style, const char* wave) {
    LeanKnob k;
    k.lean = !(style != nullptr && std::strcmp(style, "wave") == 0);
    k.wave = std::clamp(ParseNumber(wave, WaveDefault), 0.0f, WaveMax);
    return k;
}

/// Read once, at the first view filled or the first log line.
[[nodiscard]] inline const LeanKnob& LeanKnobOnce() {
    static const LeanKnob knob =
        ParseLean(std::getenv("BB_WIND_SWAY_STYLE"), std::getenv("BB_WIND_SWAY_WAVE"));
    return knob;
}

/// The lean's numbers at wind speed `speed` (m/s, held to 0-BbWind::MaxSpeed), BB_WIND_SWAY
/// `scale`, BB_WIND_SWAY_WAVE `wave` and the test view `show`: m at a full weight and a gust factor
/// of 1, before the limits (bend D, rest LeanRest D, the wave's along SA and across SC, the leaves
/// LF), Hz (the wave along and across) and the trees' Ta.
struct LeanCurve {
    float bend = 0.0f, rest = 0.0f, along = 0.0f, cross = 0.0f;
    float hz = 0.0f, cross_hz = 0.0f, leaf = 0.0f, tree = 0.0f;
};

[[nodiscard]] inline LeanCurve LeanAt(float speed, float scale, float wave, bool show) {
    const float v = std::isfinite(speed) ? std::clamp(speed, 0.0f, BbWind::MaxSpeed) : 0.0f;
    const float x = v / BbWind::MaxSpeed;
    const float gain = scale * (show ? ShowGain : 1.0f);
    LeanCurve c;
    c.bend = gain * BendMax * x * x;
    c.rest = LeanRest * c.bend;
    c.along = WaveRatio * wave * c.bend;
    c.cross = WaveCross * wave * c.bend;
    c.hz = WaveHz0 + WaveHzPerSpeed * v;
    c.cross_hz = WaveCrossFactor * c.hz;
    c.leaf = gain * wave * Leaf * BbWind::Smoothstep(LeafFrom, LeafFull, v);
    c.tree = BbWind::Smoothstep(TreeCalm, TreeFull, v);
    return c;
}

/// The lean's words of a view after FillView (in place of FillRipple's; always written): `ripple`
/// is updated for this view's camera with the wave's rates and the fronts' scale (BB_WIND_SWAY_RIPPLE
/// `knob.strength`: 0 every plant in step), the phases (RippleA, RippleB), r89's swing phases and
/// wave numbers (WindB.w, WindC.z, WindC.x, WindD.w) and gust table written from it, RippleB.w the
/// fronts' scale, RippleC (LeanRest D + D, SA, SC, LF), RippleD (D, 1: the lean, Ta, 1: the flag).
inline bool FillLean(Ripple& ripple, const Camera& cam, const BbWind::Snapshot& s, float gusts,
                     float scale, const RippleKnob& knob, const LeanKnob& lean, float* view) {
    const float speed = std::isfinite(s.speed) ? std::max(s.speed, 0.0f) : 0.0f;
    const LeanCurve c = LeanAt(speed, scale, lean.wave, knob.show);
    ripple.Update(s, cam.x, cam.y, cam.z, knob.show, c.hz, c.cross_hz, knob.strength);
    float* out = view + RippleAt;
    for (std::uint32_t i = 0; i < Ripple::Waves; ++i) {
        out[i] = float(ripple.Phase(i));
    }
    view[WindB + 3] = out[0];
    view[WindC + 2] = out[1];
    const double two_pi = 6.28318530717958647692;
    const double wave = std::max(double(speed), double(MinWaveSpeed));
    view[WindC] = float(two_pi * double(c.hz) / wave); // as Ripple's k of wave 0 and 1
    view[WindD + 3] = float(two_pi * double(c.cross_hz) / wave);
    for (std::uint32_t i = 0; i < GustSamples; ++i) {
        const double t = ripple.GustTime() + (double(i) - GustMid) * GustStep;
        view[TableAt + i] = BbWind::Gust(t, gusts);
    }
    out[7] = (knob.show ? ShowWave : 1.0f) * knob.strength;
    out[8] = c.rest + c.bend;
    out[9] = c.along;
    out[10] = c.cross;
    out[11] = c.leaf;
    out[12] = c.bend;
    out[13] = 1.0f;
    out[14] = c.tree;
    out[15] = 1.0f;
    return true;
}

/// The lean's once line (Rasterizer::WindSwayFrameEnd), under 300 characters.
inline void LeanOnceText(const LeanKnob& lean, const RippleKnob& k, float scale, char* out,
                         std::size_t size) {
    const LeanCurve c = LeanAt(BbWind::DefaultSpeed, scale, lean.wave, k.show);
    std::snprintf(out, size,
                  "Wind sway lean (r89c, BB_WIND_SWAY_WAVE=%.2f, RIPPLE=%.2f%s): plants bend "
                  "downwind as gust fronts pass (%s), in fast, back slowly, never past rest; wave "
                  "%.0f%% of the bend at %.2f Hz; trees (meshes %.1f-%.1f m tall) x%.2f at 1.5 m/s, "
                  "top half only; leaves from %.1f m/s; tips dip",
                  double(lean.wave), double(k.strength), k.show ? ", SHOW" : "",
                  k.strength > 0.0f ? "travelling downwind" : "every plant in step",
                  double(100.0f * WaveRatio * lean.wave), double(c.hz), double(TreeLo),
                  double(TreeHi), double(c.tree), double(LeafFrom));
}

/// The lean's numbers at 0.5, 1.5, 3 and 4 m/s, once, under 300 characters: a tip's bend at most
/// (a front's E of 2, a gust factor of 1), the time between the 9 m fronts, the wave's size (E 2)
/// and rate, the leaves, the trees' Ta.
inline void LeanTableText(const LeanKnob& lean, const RippleKnob& k, float scale, char* out,
                          std::size_t size) {
    const float at[4] = {0.5f, 1.5f, 3.0f, 4.0f};
    double tip[4], apart[4], wave[4], hz[4], leaf[4], tree[4];
    for (int i = 0; i < 4; ++i) {
        const LeanCurve c = LeanAt(at[i], scale, lean.wave, k.show);
        tip[i] = double((LeanRest + EnvScale) * c.bend);
        apart[i] = double(EnvWavelength[0] / (k.show ? ShowWave : 1.0f) / at[i]);
        wave[i] = double(EnvScale * c.along);
        hz[i] = double(c.hz);
        leaf[i] = double(c.leaf);
        tree[i] = double(c.tree);
    }
    std::snprintf(out, size,
                  "Wind sway lean (r89c) at 0.5/1.5/3.0/4.0 m/s: tip bend up to %.3f/%.3f/%.3f/%.3f "
                  "m x the gust, fronts %.1f/%.1f/%.1f/%.1f s apart, wave +-%.3f/%.3f/%.3f/%.3f m "
                  "at %.2f/%.2f/%.2f/%.2f Hz, leaves %.3f/%.3f/%.3f/%.3f m, trees "
                  "x%.2f/%.2f/%.2f/%.2f",
                  tip[0], tip[1], tip[2], tip[3], apart[0], apart[1], apart[2], apart[3], wave[0],
                  wave[1], wave[2], wave[3], hz[0], hz[1], hz[2], hz[3], leaf[0], leaf[1], leaf[2],
                  leaf[3], tree[0], tree[1], tree[2], tree[3]);
}

/// The lean's state at the front of r89's line every ReportFrames frames: the wave knob, the
/// fronts' spacing (m), the wind (m/s: speed times its gust now; degrees), a tip's bend at most
/// now (m), the wave's rate (Hz), the trees' Ta and the views that got the lean's words.
inline void LeanText(const LeanKnob& lean, const RippleKnob& k, const BbWind::Snapshot& s,
                     float scale, std::uint64_t views, char* out, std::size_t size) {
    const float speed = std::isfinite(s.speed) ? std::max(s.speed, 0.0f) : 0.0f;
    const float gust = std::isfinite(s.gust) ? s.gust : 1.0f;
    const LeanCurve c = LeanAt(speed, scale, lean.wave, k.show);
    char fronts[48];
    if (k.strength > 0.0f) {
        std::snprintf(fronts, sizeof(fronts), "fronts %.1f m apart",
                      double(EnvWavelength[0] / (k.strength * (k.show ? ShowWave : 1.0f))));
    } else {
        std::snprintf(fronts, sizeof(fronts), "fronts in step");
    }
    std::snprintf(out, size,
                  "lean wave %.2f (%s, %.2f m/s toward %.0f deg, tip bend up to %.3f m, wave "
                  "%.2f Hz, trees x%.2f, %llu views)",
                  double(lean.wave), fronts, double(speed * gust), double(s.direction_deg),
                  double((LeanRest + EnvScale) * c.bend), double(c.hz), double(c.tree),
                  static_cast<unsigned long long>(views));
}

'''

H_ENVELOPE_OLD = r'''    const auto wave = [&](float phase, float ka, float kb) {
        return std::sin(Wrap(phase + ka * se + kb * qe));
    };
'''
H_ENVELOPE_NEW = r'''    // bbport (r89c_wind-lean): each front's sine skewed by RippleD.y x LeanSkew (0 but with the
    // lean, which leaves r89b's envelope as it was): a front comes in fast and goes slowly
    const float skew = p[13] * LeanSkew;
    const auto wave = [&](float phase, float ka, float kb) {
        const float a = Wrap(phase + ka * se + kb * qe);
        return std::sin(a + skew * std::sin(a));
    };
'''

H_KEY_CROWN = r'''    // bbport (r89c_wind-lean): the key the vertex offers its mesh's crown (`key_crown`, CrownKey;
    // the GPU keeps the smaller of it and `stored_crown`, the slot's crown key)
    if (key_crown != nullptr) {
        *key_crown = std::fabs(wy) < FiniteMost ? CrownKey(wy) : ResetKey;
    }
'''

H_W_OLD = "    const float w = t * t * (3.0f - 2.0f * t) * ramp;\n"
H_W_NEW = r'''    // bbport (r89c_wind-lean): with the lean (the view's RippleD.y 1) a tall mesh (its crown key
    // more than TreeLo m above its lowest point) takes the tree weight in place of r89's
    const float lean = view[RippleD + 1];
    const float mesh = KeyCrown(stored_crown) - KeyHeight(stored);
    const float tc = std::clamp((mesh - TreeLo) * TreeInv, 0.0f, 1.0f);
    const float tau = tc * tc * (3.0f - 2.0f * tc);
    const float tk = std::clamp((h / std::max(mesh, MeshFloor) - CrownLow) * CrownInv, 0.0f, 1.0f);
    const float wt = view[RippleD + 2] * (tk * tk * (3.0f - 2.0f * tk));
    const float wb = t * t * (3.0f - 2.0f * t);
    const float w = (wb + tau * lean * (wt - wb)) * ramp;
'''

H_OUT_OLD = r'''        out[r] = clip[r] + (view[ForwardAt + r * 4] * ddx + view[ForwardAt + r * 4 + 2] * ddz);
    }
'''
H_DIP = r'''    // bbport (r89c_wind-lean): with the lean the tip dips as it bends (a stem keeps its length):
    // d^2 / (2 h), held to MaxAlong; none without it (r89's and r89b's results stay bit for bit)
    if (0.0f < lean) {
        const float dip =
            std::min(0.5f * (ddx * ddx + ddz * ddz) / std::max(h, DipFloor), MaxAlong);
        for (std::uint32_t r = 0; r < 4; ++r) {
            out[r] -= view[ForwardAt + r * 4 + 1] * dip;
        }
    }
'''

# ---------------------------------------------------------------- the recompiler (EmitVertexSway)
E_STORED = "    const Id stored = ctx.OpLoad(u32_type, base_ptr, spv::MemoryAccessMask::Aligned, 4u);\n"
E_CROWN = r'''    // bbport (r89c_wind-lean): the mesh's crown key (W::CrownAt: its highest world y so far)
    const Id crown_ptr = ctx.OpConvertUToPtr(u32_ptr, scaled(at(region, u64(W::CrownAt) * 4u),
                                                             field(3u, 10u), 4u));
    const Id crown = ctx.OpLoad(u32_type, crown_ptr, spv::MemoryAccessMask::Aligned, 4u);
'''
E_W_OLD = "    const Id w = mul(mul(mul(t, t), sub(f(3.0f), mul(f(2.0f), t))), ramp);\n"
E_W_NEW = r'''    // bbport (r89c_wind-lean): with the lean (RippleD.y 1) a tall mesh takes the tree weight
    // (BbWindSway::Displace)
    const Id lean_d = row(W::RippleD);
    const Id lean = comp(lean_d, 1u);
    const Id mesh = sub(sub(f(W::HeightBias), ctx.OpBitcast(f32_type, crown)),
                        sub(ctx.OpBitcast(f32_type, stored), f(W::HeightBias)));
    const Id tc =
        ctx.OpFClamp(f32_type, mul(sub(mesh, f(W::TreeLo)), f(W::TreeInv)), zero, f(1.0f));
    const Id tau = mul(mul(tc, tc), sub(f(3.0f), mul(f(2.0f), tc)));
    const Id tk = ctx.OpFClamp(
        f32_type,
        mul(sub(ctx.OpFDiv(f32_type, h, ctx.OpFMax(f32_type, mesh, f(W::MeshFloor))),
                f(W::CrownLow)),
            f(W::CrownInv)),
        zero, f(1.0f));
    const Id wt = mul(comp(lean_d, 2u), mul(mul(tk, tk), sub(f(3.0f), mul(f(2.0f), tk))));
    const Id wb = mul(mul(t, t), sub(f(3.0f), mul(f(2.0f), t)));
    const Id w = mul(add(wb, mul(mul(tau, lean), sub(wt, wb))), ramp);
'''
E_FRONT_OLD = r'''    const auto front = [&](Id phase, float ka, float kb) {
        return ctx.OpSin(f32_type, wrap(add(add(phase, mul(f(ka), se)), mul(f(kb), qe))));
    };
'''
E_FRONT_NEW = r'''    // bbport (r89c_wind-lean): each front's sine skewed by RippleD.y x LeanSkew (BbWindSway::Envelope)
    const Id skew = mul(lean, f(W::LeanSkew));
    const auto front = [&](Id phase, float ka, float kb) {
        const Id p = wrap(add(add(phase, mul(f(ka), se)), mul(f(kb), qe)));
        return ctx.OpSin(f32_type, add(p, mul(skew, ctx.OpSin(f32_type, p))));
    };
'''
E_D_OLD = "    ctx.OpStore(ctx.output_position, ctx.OpCompositeConstruct(ctx.F32[4], moved));\n"
E_D_NEW = r'''    // bbport (r89c_wind-lean): with the lean a plant's tip dips as it bends (a stem keeps its
    // length): d^2 / (2 h), held to MaxAlong (BbWindSway::Displace); 0 without the lean and for a
    // hanging thing (r112's HangBit)
    const Id dip = ctx.OpFMin(
        f32_type,
        ctx.OpFDiv(f32_type, mul(f(0.5f), add(mul(ddx, ddx), mul(ddz, ddz))),
                   ctx.OpFMax(f32_type, h, f(W::DipFloor))),
        max_along);
    Id ddy = ctx.OpSelect(
        f32_type, ctx.OpLogicalAnd(bool_type, fin, ctx.OpFOrdLessThan(bool_type, zero, lean)),
        ctx.OpFNegate(f32_type, dip), zero);
    if (hang_on) {
        ddy = ctx.OpSelect(f32_type, hang, zero, ddy);
    }
    for (u32 r = 0; r < 4; ++r) {
        moved[r] = add(moved[r], mul(comp(row(W::ForwardAt + r * 4u), 1u), ddy));
    }
''' + E_D_OLD
E_END = "    ctx.OpBranch(sway_merge);\n    ctx.AddLabel(sway_merge);\n"
E_OFFER = r'''    // bbport (r89c_wind-lean): the vertex offers its world y to its mesh's crown key (CrownKey:
    // the key of HeightBias - y, an atomic minimum, only when lower)
    const Id crown_key =
        ctx.OpBitcast(u32_type, ctx.OpFMax(f32_type, sub(f(W::HeightBias), wy), zero));
    const Id offer_crown = ctx.OpLogicalAnd(
        bool_type, ctx.OpFOrdLessThan(bool_type, ctx.OpFAbs(f32_type, wy), f(W::FiniteMost)),
        ctx.OpULessThan(bool_type, crown_key, crown));
    const Id crown_label = ctx.OpLabel();
    const Id crown_merge = ctx.OpLabel();
    ctx.OpSelectionMerge(crown_merge, spv::SelectionControlMask::MaskNone);
    ctx.OpBranchConditional(offer_crown, crown_label, crown_merge);
    ctx.AddLabel(crown_label);
    ctx.OpAtomicUMin(u32_type, crown_ptr, ctx.ConstU32(static_cast<u32>(spv::Scope::Device)),
                     ctx.u32_zero_value, crown_key);
    ctx.OpBranch(crown_merge);
    ctx.AddLabel(crown_merge);
'''

# ---------------------------------------------------------------- the lifter (Lift_::VertexSway)
L_STORED = "    const u32 stored = Emit(O(spv::Op::OpLoad), t_u32, Ty::U32, {base_ptr, aligned, 4}, 6);\n"
L_CROWN = r'''    // bbport (r89c_wind-lean): the mesh's crown key (W::CrownAt: its highest world y so far)
    const u32 crown_ptr = Emit(O(spv::Op::OpConvertUToPtr), ptr_u32, Ty::None, {scaled(at(region, u64(W::CrownAt) * 4u), field(3, 10), 4)});
    const u32 crown = Emit(O(spv::Op::OpLoad), t_u32, Ty::U32, {crown_ptr, aligned, 4}, 6);
'''
L_W_OLD = "    const u32 w = FMul(FMul(FMul(t, t), FSub(CF(3.0f), FMul(CF(2.0f), t))), ramp);\n"
L_W_NEW = r'''    // bbport (r89c_wind-lean): with the lean (RippleD.y 1) a tall mesh takes the tree weight
    // (BbWindSway::Displace)
    const u32 lean_d = row(W::RippleD);
    const u32 lean = comp(lean_d, 1);
    const u32 mesh = FSub(FSub(CF(W::HeightBias), Emit(O(spv::Op::OpBitcast), t_f32, Ty::F32, {crown})),
                          FSub(Emit(O(spv::Op::OpBitcast), t_f32, Ty::F32, {stored}), CF(W::HeightBias)));
    const u32 tc = clamp_f(FMul(FSub(mesh, CF(W::TreeLo)), CF(W::TreeInv)), zero, CF(1.0f));
    const u32 tau = FMul(FMul(tc, tc), FSub(CF(3.0f), FMul(CF(2.0f), tc)));
    const u32 mesh_floor = Ext(GLSLstd450FMax, t_f32, Ty::F32, {mesh, CF(W::MeshFloor)});
    const u32 tk = clamp_f(FMul(FSub(Emit(O(spv::Op::OpFDiv), t_f32, Ty::F32, {h, mesh_floor}), CF(W::CrownLow)), CF(W::CrownInv)), zero, CF(1.0f));
    const u32 wt = FMul(comp(lean_d, 2), FMul(FMul(tk, tk), FSub(CF(3.0f), FMul(CF(2.0f), tk))));
    const u32 wb = FMul(FMul(t, t), FSub(CF(3.0f), FMul(CF(2.0f), t)));
    const u32 w = FMul(FAdd(wb, FMul(FMul(tau, lean), FSub(wt, wb))), ramp);
'''
L_FRONT_OLD = "    const auto front = [&](u32 phase, float ka, float kb) { return sin_f(wrap(FAdd(FAdd(phase, FMul(CF(ka), se)), FMul(CF(kb), qe)))); };\n"
L_FRONT_NEW = r'''    // bbport (r89c_wind-lean): each front's sine skewed by RippleD.y x LeanSkew (BbWindSway::Envelope)
    const u32 skew = FMul(lean, CF(W::LeanSkew));
    const auto front = [&](u32 phase, float ka, float kb) {
        const u32 p = wrap(FAdd(FAdd(phase, FMul(CF(ka), se)), FMul(CF(kb), qe)));
        return sin_f(FAdd(p, FMul(skew, sin_f(p))));
    };
'''
L_D_OLD = "    EmitVoid(O(spv::Op::OpStore), {var_position, ComponentsF({moved[0], moved[1], moved[2], moved[3]})});\n"
L_D_NEW = r'''    // bbport (r89c_wind-lean): with the lean a plant's tip dips as it bends (a stem keeps its length): d^2 / (2 h),
    // held to MaxAlong (BbWindSway::Displace); 0 without the lean and for a hanging thing (r112's HangBit)
    const u32 dip = Ext(GLSLstd450FMin, t_f32, Ty::F32,
                        {Emit(O(spv::Op::OpFDiv), t_f32, Ty::F32, {FMul(CF(0.5f), FAdd(FMul(ddx, ddx), FMul(ddz, ddz))), Ext(GLSLstd450FMax, t_f32, Ty::F32, {h, CF(W::DipFloor)})}), max_along});
    u32 ddy = Select(Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool, {fin, FCmp(O(spv::Op::OpFOrdLessThan), zero, lean)}), FNeg(dip), zero);
    if (hang_on) {
        ddy = Select(hang, zero, ddy);
    }
    for (u32 r = 0; r < 4; ++r) {
        moved[r] = FAdd(moved[r], FMul(comp(row(W::ForwardAt + r * 4), 1), ddy));
    }
''' + L_D_OLD
L_END = "    EmitVoid(O(spv::Op::OpBranch), {sway_merge});\n    Open(sway_merge);\n"
L_OFFER = r'''    // bbport (r89c_wind-lean): the vertex offers its world y to its mesh's crown key (CrownKey:
    // the key of HeightBias - y, an atomic minimum, only when lower)
    const u32 crown_key = Emit(O(spv::Op::OpBitcast), t_u32, Ty::U32, {Ext(GLSLstd450FMax, t_f32, Ty::F32, {FSub(CF(W::HeightBias), wy), zero})});
    const u32 offer_crown = Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool,
                                 {FCmp(O(spv::Op::OpFOrdLessThan), abs_f(wy), CF(W::FiniteMost)), ICmp(O(spv::Op::OpULessThan), crown_key, crown)});
    const u32 crown_label = m.NewId();
    const u32 crown_merge = m.NewId();
    EmitVoid(O(spv::Op::OpSelectionMerge), {crown_merge, 0}, 2);
    EmitVoid(O(spv::Op::OpBranchConditional), {offer_crown, crown_label, crown_merge});
    Open(crown_label);
    const u32 prev_crown = Emit(O(spv::Op::OpAtomicUMin), t_u32, Ty::U32, {crown_ptr, CU(u32(spv::Scope::Device)), CU(0), crown_key});
    nodes[m.NodeOf(prev_crown)].effect = true;
    EmitVoid(O(spv::Op::OpBranch), {crown_merge});
    Open(crown_merge);
'''

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
F_FILL_OLD = r'''        if (BbWindSway::FillRipple(sway_ripple, camera, snapshot, knob.gusts, knob.scale,
                                   BbWindSway::RippleKnobOnce(), filled.data())) {
'''
F_FILL_NEW = r'''        // bbport (r89c_wind-lean): the lean's words (FillLean) unless BB_WIND_SWAY_STYLE=wave
        if (BbWindSway::LeanKnobOnce().lean
                ? BbWindSway::FillLean(sway_ripple, camera, snapshot, knob.gusts, knob.scale,
                                       BbWindSway::RippleKnobOnce(), BbWindSway::LeanKnobOnce(),
                                       filled.data())
                : BbWindSway::FillRipple(sway_ripple, camera, snapshot, knob.gusts, knob.scale,
                                         BbWindSway::RippleKnobOnce(), filled.data())) {
'''
F_RESET = "        words[BbWindSway::BaseAt + taken.slot] = BbWindSway::ResetKey;\n"
F_RESET_CROWN = "        words[BbWindSway::CrownAt + taken.slot] = BbWindSway::ResetKey; // bbport (r89c)\n"
F_ONCE_OLD = r'''            BbWindSway::RippleOnceText(BbWindSway::RippleKnobOnce(), knob.scale, ripple,
                                       sizeof(ripple));
'''
F_ONCE_NEW = r'''            if (BbWindSway::LeanKnobOnce().lean) { // bbport (r89c_wind-lean): its two lines
                char table[512];
                BbWindSway::LeanTableText(BbWindSway::LeanKnobOnce(), BbWindSway::RippleKnobOnce(),
                                          knob.scale, table, sizeof(table));
                BbReport::Printf("%s\n", table);
                BbWindSway::LeanOnceText(BbWindSway::LeanKnobOnce(), BbWindSway::RippleKnobOnce(),
                                         knob.scale, ripple, sizeof(ripple));
            } else {
                BbWindSway::RippleOnceText(BbWindSway::RippleKnobOnce(), knob.scale, ripple,
                                           sizeof(ripple));
            }
'''
F_LINE_OLD = r'''    BbWindSway::RippleText(BbWindSway::RippleKnobOnce(), wind.Get(), s.rippled_views, ripple,
                           sizeof(ripple));
'''
F_LINE_NEW = r'''    if (BbWindSway::LeanKnobOnce().lean) { // bbport (r89c_wind-lean): the lean's state
        BbWindSway::LeanText(BbWindSway::LeanKnobOnce(), BbWindSway::RippleKnobOnce(), wind.Get(),
                             BbWindSway::KnobOnce().scale, s.rippled_views, ripple,
                             sizeof(ripple));
    } else {
        BbWindSway::RippleText(BbWindSway::RippleKnobOnce(), wind.Get(), s.rippled_views, ripple,
                               sizeof(ripple));
    }
'''

# ---------------------------------------------------------------- the test
T_HELPERS = r'''
// bbport (r89c_wind-lean): a view of constants c in wind s with the lean (its phases kept in
// `ripple`, which each call updates for this camera and time).
std::array<float, ViewWords> LeanViewOf(const std::array<float, 216>& c, const BbWind::Snapshot& s,
                                        Ripple& ripple, const RippleKnob& knob,
                                        const LeanKnob& lean, float scale = 1.0f,
                                        float gusts = 0.5f) {
    Camera cam;
    const bool ok = CameraOf(c.data(), cam);
    Expect(ok, "the camera of the test constants");
    std::array<float, ViewWords> view{};
    FillView(cam, s, gusts, scale, view.data());
    Expect(FillLean(ripple, cam, s, gusts, scale, knob, lean, view.data()), "FillLean writes");
    return view;
}

// How the lean moves world point p of a mesh whose lowest point is at height `base` and highest
// at `crown` (a crown below the base: no crown key yet, ResetKey), in the world (x, y, z).
std::array<double, 3> LeanMoveOf(const float* view, const std::array<float, 216>& c,
                                 const std::array<double, 3>& p, float base, float crown) {
    const auto clip = ClipOf(c, p);
    const auto before = WorldOf(view, clip);
    const std::uint32_t crown_key = crown < base ? ResetKey : CrownKey(crown);
    const auto after =
        WorldOf(view, Displace(view, clip, HeightKey(base), 1.0f, nullptr, crown_key));
    return {after[0] - before[0], after[1] - before[1], after[2] - before[2]};
}

// The parts of a move along the wind (toward where it blows) and across it.
double AlongOf(const std::array<double, 3>& d, const BbWind::Snapshot& s) {
    return d[0] * s.dir_x + d[2] * s.dir_z;
}

double AcrossOf(const std::array<double, 3>& d, const BbWind::Snapshot& s) {
    return d[2] * s.dir_x - d[0] * s.dir_z;
}

// A wind as BbWind gives it: the gust factor at its time (BB_WIND_GUSTS `gusts`).
BbWind::Snapshot Gusty(double time, float deg, float speed, float gusts) {
    BbWind::Snapshot s = Wind(time, deg, speed);
    s.gust = BbWind::Gust(time, gusts);
    return s;
}
'''

T_TESTS = r'''    // bbport (r89c_wind-lean): the style and the wave's knobs.
    {
        Expect(ParseLean(nullptr, nullptr).lean && ParseLean(nullptr, nullptr).wave == WaveDefault,
               "unset: the lean, wave 1");
        Expect(!ParseLean("wave", nullptr).lean && ParseLean("lean", nullptr).lean &&
                   ParseLean("x", nullptr).lean && ParseLean("", nullptr).lean,
               "BB_WIND_SWAY_STYLE=wave: r89b's ripple; anything else: the lean");
        Expect(ParseLean(nullptr, "0").wave == 0.0f && ParseLean(nullptr, "-1").wave == 0.0f &&
                   ParseLean(nullptr, "9").wave == WaveMax && ParseLean(nullptr, "2.5").wave == 2.5f &&
                   ParseLean(nullptr, "abc").wave == WaveDefault &&
                   ParseLean(nullptr, "nan").wave == WaveDefault,
               "BB_WIND_SWAY_WAVE: 0-4, unreadable 1");
    }

    // The lean's numbers are of the wind speed: none at 0 m/s, growing with it; calm at 1.5 m/s.
    {
        const LeanCurve calm = LeanAt(0.0f, 1.0f, 1.0f, false);
        Expect(calm.bend == 0.0f && calm.rest == 0.0f && calm.along == 0.0f && calm.cross == 0.0f &&
                   calm.leaf == 0.0f && calm.tree == 0.0f,
               "no wind: no bend, wave, flutter or tree");
        bool rising = true;
        LeanCurve last = calm;
        for (int i = 1; i <= 80; ++i) {
            const LeanCurve c = LeanAt(0.05f * float(i), 1.0f, 1.0f, false);
            rising = rising && c.bend > last.bend && c.along > last.along && c.hz > last.hz &&
                     c.leaf >= last.leaf && c.tree >= last.tree;
            last = c;
        }
        Expect(rising, "the bend, the wave, its rate, the flutter and the trees grow with the wind");
        Expect(Near(last.bend, BendMax, 1e-6) && last.tree == 1.0f && Near(last.leaf, Leaf, 1e-6),
               "at 4 m/s: BendMax, the trees in full, the leaves Leaf");
        const LeanCurve normal = LeanAt(BbWind::DefaultSpeed, 1.0f, 1.0f, false);
        Expect(normal.leaf == 0.0f && normal.tree < 0.1f && normal.hz < 0.5f &&
                   (LeanRest + EnvScale) * normal.bend < 0.04f,
               "at 1.5 m/s: no flutter, trees under a tenth, the wave under 0.5 Hz, a bend under 4 cm");
        Expect(EnvScale * normal.along * BbWind::GustMax < 0.0105f &&
                   Near(normal.along / normal.bend, WaveRatio, 1e-6),
               "at 1.5 m/s the wave is 15% of the bend and under about 1 cm");
        Expect(LeanAt(4.0f, 1.0f, 0.0f, false).along == 0.0f &&
                   LeanAt(4.0f, 1.0f, 0.0f, false).leaf == 0.0f,
               "BB_WIND_SWAY_WAVE=0: no wave, no flutter");
    }

    // The lean's words; zero wind moves nothing.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const auto s = Wind(5.0, 225.0f, 1.5f);
        const auto view = LeanViewOf(c, s, ripple, ParseRipple(nullptr, nullptr),
                                     ParseLean(nullptr, nullptr));
        const LeanCurve n = LeanAt(1.5f, 1.0f, 1.0f, false);
        Expect(view[RippleD + 3] == 1.0f && view[RippleD + 1] == 1.0f && view[RippleD] == n.bend &&
                   view[RippleC] == n.rest + n.bend && view[RippleC + 1] == n.along &&
                   view[RippleD + 2] == n.tree && view[RippleB + 3] == 1.0f &&
                   view[WindB + 3] == view[RippleA],
               "the lean's words at 1.5 m/s");
        Ripple still_ripple;
        double worst = 0.0;
        for (int i = 0; i < 300; ++i) {
            const auto still = LeanViewOf(c, Gusty(1.0 + 0.1 * i, 225.0f, 0.0f, 1.0f), still_ripple,
                                          ParseRipple(nullptr, nullptr), ParseLean(nullptr, "4"),
                                          MaxScale, BbWind::MaxGusts);
            const std::array<double, 3> p = {7.0 + 0.02 * i, 0.5 + 0.01 * i, 14.0 - 0.01 * i};
            const auto d = LeanMoveOf(still.data(), c, p, 0.5f, float(0.5 + 0.02 * i));
            worst = std::max(worst, std::fabs(d[0]) + std::fabs(d[1]) + std::fabs(d[2]));
        }
        Expect(worst == 0.0, "zero wind: nothing moves");
    }

    // Downwind only: the bend never points upwind, with the wave at 0 nothing moves across the
    // wind, and even BB_WIND_SWAY_WAVE=4 never swings a plant back past its rest; the wave's part
    // (the move with WAVE=1 minus the move with WAVE=0) stays within its bound at each speed.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        std::uint32_t seed = 4242u;
        const auto rnd = [&seed]() {
            seed = seed * 1664525u + 1013904223u;
            return double(seed >> 8) / 16777216.0;
        };
        const float speeds[4] = {0.5f, 1.5f, 3.0f, 4.0f};
        const RippleKnob fronts = ParseRipple(nullptr, nullptr);
        double low0 = 1.0, low4 = 1.0, across0 = 0.0;
        bool bounded = true;
        double wave15 = 0.0;
        for (int k = 0; k < 4; ++k) {
            Ripple r0, r1, r4;
            const LeanCurve n = LeanAt(speeds[k], 1.0f, 1.0f, false);
            const double bound =
                BbWind::GustMax * EnvScale * std::hypot(double(n.along), double(n.cross)) +
                BbWind::GustMax * double(n.leaf) * (LeafCalm + (1.0 - LeafCalm) * EnvScale) * 1.4143 +
                1e-4;
            double worst = 0.0;
            for (int i = 0; i < 1500; ++i) {
                const auto s = Gusty(0.2 * i, float(225.0 + 20.0 * std::sin(0.003 * i)), speeds[k],
                                     BbWind::MaxGusts);
                const auto v0 = LeanViewOf(c, s, r0, fronts, ParseLean(nullptr, "0"), 1.0f,
                                           BbWind::MaxGusts);
                const auto v1 = LeanViewOf(c, s, r1, fronts, ParseLean(nullptr, nullptr), 1.0f,
                                           BbWind::MaxGusts);
                const auto v4 = LeanViewOf(c, s, r4, fronts, ParseLean(nullptr, "4"), 1.0f,
                                           BbWind::MaxGusts);
                const std::array<double, 3> p = {10.0 - std::sin(0.3) * 6.0 + 6.0 * rnd() - 3.0,
                                                 0.5 + 2.5 * rnd(),
                                                 20.0 - std::cos(0.3) * 6.0 + 6.0 * rnd() - 3.0};
                const auto d0 = LeanMoveOf(v0.data(), c, p, 0.5f, 0.0f);
                const auto d1 = LeanMoveOf(v1.data(), c, p, 0.5f, 0.0f);
                const auto d4 = LeanMoveOf(v4.data(), c, p, 0.5f, 0.0f);
                low0 = std::min(low0, AlongOf(d0, s));
                low4 = std::min(low4, AlongOf(d4, s));
                across0 = std::max(across0, std::fabs(AcrossOf(d0, s)));
                worst = std::max(worst, std::hypot(d1[0] - d0[0], d1[2] - d0[2]));
            }
            bounded = bounded && worst <= bound;
            if (k == 1) {
                wave15 = worst;
            }
        }
        Expect(low0 > -5e-5, "BB_WIND_SWAY_WAVE=0: the bend never points upwind");
        Expect(across0 < 5e-5, "BB_WIND_SWAY_WAVE=0: nothing moves across the wind");
        Expect(low4 > -5e-5, "BB_WIND_SWAY_WAVE=4: never back past the rest");
        Expect(bounded, "the wave's part stays within its bound at 0.5, 1.5, 3 and 4 m/s");
        Expect(wave15 < 0.0115, "at 1.5 m/s the wave's part stays at about 1 cm (strongest gusts)");
    }

    // Trees: a mesh 6 m tall barely moves at 1.5 m/s (its lower half not at all) and moves as a
    // bush's top at 4 m/s; a 1.5 m bush is a bush.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        const std::array<double, 3> top = {10.0 - std::sin(0.3) * 7.0, 6.5,
                                           20.0 - std::cos(0.3) * 7.0};
        const std::array<double, 3> trunk = {top[0], 2.5, top[2]};
        const std::array<double, 3> bush_top = {top[0], 1.8, top[2]};
        const auto worst_of = [&](float speed, float crown, const std::array<double, 3>& p) {
            Ripple ripple;
            double worst = 0.0;
            for (int i = 0; i < 1200; ++i) {
                const auto view =
                    LeanViewOf(c, Gusty(0.1 * i, 225.0f, speed, BbWind::DefaultGusts), ripple,
                               ParseRipple(nullptr, nullptr), ParseLean(nullptr, nullptr));
                worst = std::max(worst, Length(LeanMoveOf(view.data(), c, p, 0.5f, crown)));
            }
            return worst;
        };
        const double tree15 = worst_of(1.5f, 6.5f, top), bush15 = worst_of(1.5f, 0.0f, top);
        const double tree4 = worst_of(4.0f, 6.5f, top), bush4 = worst_of(4.0f, 0.0f, top);
        Expect(tree15 < 0.008 && tree15 < 0.1 * bush15 && bush15 > 0.02,
               "a tree's top at 1.5 m/s: under 8 mm, under a tenth of a bush's");
        Expect(Near(tree4, bush4, 1e-4) && tree4 > 0.2, "a tree's top at 4 m/s moves as a bush's");
        Expect(worst_of(4.0f, 6.5f, trunk) < 1e-6, "a tree's lower half stays still");
        Expect(Near(worst_of(1.5f, 2.0f, bush_top), worst_of(1.5f, 0.0f, bush_top), 1e-9),
               "a bush 1.5 m tall sways as a bush");
    }

    // Faster wind, larger bend (at a point over 2 minutes, gusts 0); a front comes in faster than
    // it goes; the fronts travel downwind (with the skew); BB_WIND_SWAY_RIPPLE=0: in step.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        const std::array<double, 3> p = {10.0 - std::sin(0.3) * 6.0, 1.8, 20.0 - std::cos(0.3) * 6.0};
        double last = 0.0;
        bool larger = true;
        const float list[4] = {0.5f, 1.5f, 3.0f, 4.0f};
        for (const float speed : list) {
            Ripple ripple;
            double most = 0.0;
            for (int i = 0; i < 1200; ++i) {
                const auto view = LeanViewOf(c, Wind(0.1 * i, 225.0f, speed), ripple,
                                             ParseRipple(nullptr, nullptr),
                                             ParseLean(nullptr, nullptr), 1.0f, 0.0f);
                most = std::max(most, Length(LeanMoveOf(view.data(), c, p, 0.5f, 0.0f)));
            }
            larger = larger && most > last;
            last = most;
        }
        Expect(larger, "the faster the wind, the larger the bend");
        Ripple ripple;
        int rising = 0, falling = 0;
        float before = 0.0f;
        for (int i = 0; i <= 6000; ++i) {
            const auto view = LeanViewOf(c, Wind(0.05 * i, 225.0f, 1.5f), ripple,
                                         ParseRipple(nullptr, nullptr), ParseLean(nullptr, nullptr));
            const float e = Envelope(view.data(), 3.0f, -2.0f);
            if (i > 0 && e > before + 1e-4f) {
                ++rising;
            } else if (i > 0 && e < before - 1e-4f) {
                ++falling;
            }
            before = e;
        }
        Expect(rising * 10 < falling * 8, "a front comes in faster than it goes");
        Ripple travel;
        const RippleKnob on = ParseRipple(nullptr, nullptr);
        const auto first =
            LeanViewOf(c, Wind(100.0, 200.0f, 1.5f), travel, on, ParseLean(nullptr, nullptr));
        std::array<float, ViewWords> later{};
        double t = 100.0;
        for (int f = 0; f < 30; ++f) {
            t += 1.0 / 60.0;
            later = LeanViewOf(c, Wind(t, 200.0f, 1.5f), travel, on, ParseLean(nullptr, nullptr));
        }
        const double shift = 1.5 * (t - 100.0);
        double same = 0.0;
        for (int i = 0; i <= 80; ++i) {
            const float s = float(-20.0 + 0.5 * i);
            same = std::max(same, double(std::fabs(Envelope(later.data(), s, 1.3f) -
                                                   Envelope(first.data(), float(s - shift), 1.3f))));
        }
        Expect(same < 2e-3, "the lean's fronts move downwind at the wind's speed");
        Ripple in_step;
        const auto view = LeanViewOf(c, Wind(40.0, 225.0f, 1.5f), in_step,
                                     ParseRipple("0", nullptr), ParseLean(nullptr, nullptr));
        double spread = 0.0;
        for (int i = 0; i <= 40; ++i) {
            spread = std::max(spread, double(std::fabs(Envelope(view.data(), float(i - 20), float(20 - i)) -
                                                       Envelope(view.data(), 0.0f, 0.0f))));
        }
        Expect(spread < 1e-6, "BB_WIND_SWAY_RIPPLE=0 with the lean: every plant in step");
    }

    // A wind turning 2 deg/s, 3900 m from the world's origin: no jump with the lean either; its
    // strongest stays within the limits.
    {
        const auto largest_step = [](double turn, double base) {
            const std::array<double, 3> eye = {3000.0, 10.0, -2500.0};
            const auto c = Constants(0.4, -0.1, eye);
            Ripple ripple;
            const std::array<double, 3> p = {eye[0] - std::sin(0.4) * 8.0, 9.0,
                                             eye[2] - std::cos(0.4) * 8.0};
            std::array<double, 3> last{};
            double worst = 0.0;
            for (int f = 1; f <= 1200; ++f) {
                const double t = 10.0 + f / 60.0;
                const auto view = LeanViewOf(c, Wind(t, float(base + turn * (t - 10.0)), 3.0f),
                                             ripple, ParseRipple(nullptr, nullptr),
                                             ParseLean(nullptr, nullptr));
                const auto d = LeanMoveOf(view.data(), c, p, 7.5f, 0.0f);
                if (f > 1) {
                    worst = std::max(worst, std::hypot(d[0] - last[0], d[2] - last[2]));
                }
                last = d;
            }
            return worst;
        };
        // the steady wind's largest step at the directions the turning one passes (its largest
        // step over 20 s varies by itself with the direction)
        double steady = 0.0;
        for (int i = 0; i <= 4; ++i) {
            steady = std::max(steady, largest_step(0.0, 225.0 + 10.0 * i));
        }
        const double turning = largest_step(2.0, 225.0);
        Expect(steady > 1e-4 && turning <= 1.5 * steady + 1e-4, "the lean: a turning wind, no jump");
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        std::uint32_t seed = 99u;
        const auto rnd = [&seed]() {
            seed = seed * 1664525u + 1013904223u;
            return double(seed >> 8) / 16777216.0;
        };
        double worst = 0.0, dip = 0.0;
        for (int i = 0; i < 2000; ++i) {
            auto s = Wind(0.37 * i, float(225.0 + 40.0 * std::sin(0.01 * i)), BbWind::MaxSpeed);
            s.gust = BbWind::GustMax;
            const auto view = LeanViewOf(c, s, ripple, ParseRipple("4", "1"), ParseLean(nullptr, "4"),
                                         MaxScale, BbWind::MaxGusts);
            const std::array<double, 3> p = {10.0 - std::sin(0.3) * 6.0 + 6.0 * rnd() - 3.0,
                                             0.5 + 3.0 * rnd(),
                                             20.0 - std::cos(0.3) * 6.0 + 6.0 * rnd() - 3.0};
            const auto d = LeanMoveOf(view.data(), c, p, 0.5f, 0.0f);
            worst = std::max(worst, Length(d));
            dip = std::max(dip, -d[1]);
        }
        Expect(worst <= std::hypot(double(MaxAlong), double(MaxCross)) +
                            std::hypot(double(MaxLeaf), double(MaxLeaf)) + 3e-3 &&
                   worst > 0.3 && dip <= double(MaxAlong) + 3e-3 && dip > 0.01,
               "the strongest lean stays within its limits and dips");
    }

    // The crown keys: their order, back to a height, and the key a vertex offers.
    {
        Expect(CrownKey(3.0f) < CrownKey(2.0f) && CrownKey(-5.0f) > CrownKey(-4.0f) &&
                   CrownKey(-FiniteMost) < ResetKey && CrownKey(FiniteMost) < ResetKey,
               "CrownKey: higher is smaller, below ResetKey");
        bool back = true;
        const float heights[6] = {-120.5f, -1.0f, 0.0f, 0.25f, 7.0f, 300.0f};
        for (const float y : heights) {
            back = back && std::fabs(KeyCrown(CrownKey(y)) - y) < 2e-3f;
        }
        Expect(back, "KeyCrown undoes CrownKey");
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const auto view = LeanViewOf(c, Wind(5.0, 225.0f, 1.5f), ripple,
                                     ParseRipple(nullptr, nullptr), ParseLean(nullptr, nullptr));
        const auto clip = ClipOf(c, {10.0 - std::sin(0.3) * 6.0, 2.0, 20.0 - std::cos(0.3) * 6.0});
        std::uint32_t key = 0, key_crown = 0;
        (void)Displace(view.data(), clip, HeightKey(0.5f), 1.0f, &key, ResetKey, &key_crown);
        Expect(std::fabs(KeyCrown(key_crown) - 2.0f) < 2e-3f && std::fabs(KeyHeight(key) - 2.0f) < 2e-3f,
               "a vertex offers its height to the base and crown keys");
        Expect(PlantSlots * 2 == BaseSlots && CrownAt + PlantSlots == RegionWords,
               "the crown keys are the base keys' second half");
    }

    // The lean's log texts.
    {
        char text[512];
        LeanOnceText(ParseLean(nullptr, nullptr), ParseRipple(nullptr, nullptr), 1.0f, text,
                     sizeof(text));
        Expect(std::strncmp(text, "Wind sway lean (r89c, BB_WIND_SWAY_WAVE=1.00, RIPPLE=1.00)", 59) ==
                       0 &&
                   std::strlen(text) < 300,
               "the lean's once line, under 300 characters");
        LeanOnceText(ParseLean(nullptr, "4"), ParseRipple("4", "1"), MaxScale, text, sizeof(text));
        Expect(std::strlen(text) < 300, "the lean's once line at the strongest, under 300 characters");
        LeanTableText(ParseLean(nullptr, nullptr), ParseRipple(nullptr, nullptr), 1.0f, text,
                      sizeof(text));
        Expect(std::strncmp(text, "Wind sway lean (r89c) at 0.5/1.5/3.0/4.0 m/s: tip bend up to", 61) ==
                       0 &&
                   std::strlen(text) < 300,
               "the lean's numbers, under 300 characters");
        LeanTableText(ParseLean(nullptr, "4"), ParseRipple("4", "1"), MaxScale, text, sizeof(text));
        Expect(std::strlen(text) < 300, "the lean's numbers at the strongest, under 300 characters");
        LeanText(ParseLean(nullptr, nullptr), ParseRipple(nullptr, nullptr), Wind(10.0, 231.0f, 1.5f),
                 1.0f, 7, text, sizeof(text));
        Expect(std::strstr(text, "lean wave 1.00 (fronts 9.0 m apart, 1.50 m/s toward 231 deg") !=
                       nullptr &&
                   std::strstr(text, "7 views)") != nullptr,
               "the line's lean state");
        LeanText(ParseLean(nullptr, nullptr), ParseRipple("0", nullptr), Wind(10.0, 231.0f, 1.5f),
                 1.0f, 7, text, sizeof(text));
        Expect(std::strstr(text, "fronts in step") != nullptr, "the line's lean state, in step");
    }

'''

# ---------------------------------------------------------------- README
README_ROWS = (
    "| `BB_WIND_SWAY_STYLE` | How the plants move with the sway on (`BB_WIND_SWAY`). Unset (or any "
    "text but `wave`): the lean, the default. `wave`: r89b's motion of the `BB_WIND_SWAY_RIPPLE` row, "
    "unchanged (with `BB_WIND_SWAY_RIPPLE=0` the `BB_WIND_SWAY` row's), for side by side clips. The "
    "lean: each plant bends downwind while a gust front passes over it and eases back when it has "
    "passed, never back past its rest. Along the wind it moves by G (0.25 D + D E + W E sin a), "
    "across by G (W / 2) E sin b; E is the gust fronts' envelope (0 in a calm, up to 2 in a front; "
    "three waves 9, 13 and 17 m long carried downwind at the wind's speed, so neighbours bend one "
    "after the other; each front's sine skewed by 0.6, so a front comes in in about a third of its "
    "time and goes in two thirds), G the gust factor at the plant (0.3 to 2). All of it is of the "
    "wind speed v (`BB_WIND_SPEED`): D = 0.12 m x (v / 4 m/s)^2 x the `BB_WIND_SWAY` scale, so 0.002, "
    "0.017, 0.068 and 0.12 m at 0.5, 1.5, 3 and 4 m/s, and nothing at 0; W = 0.15 D x "
    "`BB_WIND_SWAY_WAVE` (the subtle wave, at 0.15 + 0.15 v Hz along and 1.5 times that across); "
    "the leaves flutter (as with `wave`, 1.9 and 2.7 Hz) only from 2.5 m/s, 0.012 m x the wave knob "
    "in full at 4 m/s. The fronts pass a plant every 9 m / v (6 s at 1.5 m/s). Trees: a mesh whose "
    "highest point (kept by the GPU as its lowest point is) is more than 2 m above its lowest point "
    "is a tree by smoothstep(2, 3.5 m, its height): its lower half stays still and only its top half "
    "moves, times smoothstep(1, 4 m/s, v) (0.07 at 1.5 m/s, 0.74 at 3, 1 at 4); a bush up to 2 m "
    "tall is a bush. The tip dips as it bends (by d^2 / (2 h), held to 0.4 m), so a stem keeps its "
    "length. Roots, weights, limits (0.4 m along, 0.15 m across, 0.08 m for the leaves), the 1 s "
    "ramp and the motion vectors and ray traced scene are as with `wave`. With the lean "
    "`BB_WIND_SWAY_RIPPLE=0` bends every plant in step and a number above 0 divides the fronts' "
    "lengths; `BB_WIND_SWAY_SHOW=1` makes the bend 2.5 times larger and the fronts 2.5 times closer. "
    "The log says once `Wind sway lean (r89c) at 0.5/1.5/3.0/4.0 m/s: ...` (the numbers) and "
    "`Wind sway lean (r89c, BB_WIND_SWAY_WAVE=...)`, and the `Wind sway (r89)` line every 600 frames "
    "starts `lean wave ...`. Plant slots are 512 (the other half of the 1024 keys holds the crowns). "
    "Limits: a tree drawn as separate meshes (a crown mesh up in the air) is judged mesh by mesh. "
    "Cost: with the sway on about 45 more operations, 3 more sines and 2 more loads per plant "
    "vertex than `wave`; not measured | unset (the lean) |\n"
    "| `BB_WIND_SWAY_WAVE` | The lean's subtle back and forth (`BB_WIND_SWAY_STYLE` row): 0 none "
    "(the plants only bend downwind and ease back, nothing across the wind), 1 the default (0.15 "
    "of the bend along, half that across: at 1.5 m/s at most about 1 cm at a tip, at 0.375 Hz), up "
    "to 4; it also scales the leaves' flutter from 2.5 m/s. Text that is not a number is 1, below 0 "
    "is 0. No effect with `BB_WIND_SWAY_STYLE=wave` | `1` |\n")

README_SWAY_OLD = "Each vertex of a plant moves sideways in the world, along the wind by G (0.06 + 0.06 sin a) m"
README_SWAY_NEW = ("With `BB_WIND_SWAY_STYLE=wave` and `BB_WIND_SWAY_RIPPLE=0` (the default motion is the lean of "
                   "the `BB_WIND_SWAY_STYLE` row) each vertex of a plant moves sideways in the world, along the "
                   "wind by G (0.06 + 0.06 sin a) m")
README_RIPPLE_OLD = "| `BB_WIND_SWAY_RIPPLE` | How the plant sway (`BB_WIND_SWAY`) moves. "
README_RIPPLE_NEW = ("| `BB_WIND_SWAY_RIPPLE` | How the plant sway (`BB_WIND_SWAY`) moves with "
                     "`BB_WIND_SWAY_STYLE=wave` (with the default lean see that row). ")
README_SHOW = "| `BB_WIND_SWAY_SHOW` | Test view:"

EDITS = {
    HEADER: [
        ("inline constexpr std::uint32_t BaseSlots = 1024;\n",
         "inline constexpr std::uint32_t BaseSlots = 1024;\n" + H_SLOTS),
        ("inline constexpr float ShowGain = 2.5f, ShowWave = 2.5f;\n",
         "inline constexpr float ShowGain = 2.5f, ShowWave = 2.5f;\n" + H_CONSTANTS),
        ("/// The camera of a draw's 864-byte constants: projection (4x4 rows) at word 52, view to world\n",
         H_CROWN + "/// The camera of a draw's 864-byte constants: projection (4x4 rows) at word 52, view to world\n"),
        ("    void Update(const BbWind::Snapshot& s, float cx, float cy, float cz, bool show) {\n",
         "    // bbport (r89c_wind-lean): `sway_hz` and `cross_hz` the rates of waves 0 and 1 (r89's\n"
         "    // swing; the lean's wave), `fronts` the fronts' lengths' divisor (0: in step)\n"
         "    void Update(const BbWind::Snapshot& s, float cx, float cy, float cz, bool show,\n"
         "                double sway_hz = SwayHz, double cross_hz = CrossHz, double fronts = 1.0) {\n"),
        ("        Take(s, show);\n",
         "        Take(s, show, sway_hz, cross_hz, fronts);\n"),
        ("    void Take(const BbWind::Snapshot& s, bool show) {\n",
         "    void Take(const BbWind::Snapshot& s, bool show, double sway_hz, double cross_hz,\n"
         "              double fronts) {\n"),
        ("        const double k1 = two_pi * SwayHz / wave, k2 = two_pi * CrossHz / wave;\n",
         "        const double k1 = two_pi * sway_hz / wave, k2 = two_pi * cross_hz / wave;\n"),
        ("            k[i] = {ab[i][0] * dx - ab[i][1] * dz, 0.0, ab[i][0] * dz + ab[i][1] * dx};\n",
         "            // bbport (r89c_wind-lean): the fronts' lengths divided by `fronts` (their rate kept)\n"
         "            const double sc = i >= 2 ? fronts : 1.0;\n"
         "            k[i] = {sc * (ab[i][0] * dx - ab[i][1] * dz), 0.0, sc * (ab[i][0] * dz + ab[i][1] * dx)};\n"),
        ("        omega = {two_pi * SwayHz,  two_pi * CrossHz, -ab[2][0] * u,   -ab[3][0] * u,\n",
         "        omega = {two_pi * sway_hz, two_pi * cross_hz, -ab[2][0] * u,   -ab[3][0] * u,\n"),
        ("/// The gust envelope E at s, q m along and across the wind from the view's camera (the shaders'\n",
         H_LEAN + "/// The gust envelope E at s, q m along and across the wind from the view's camera (the shaders'\n"),
        (H_ENVELOPE_OLD, H_ENVELOPE_NEW),
        ("                                                   std::uint32_t* key = nullptr) {\n",
         "                                                   std::uint32_t* key = nullptr,\n"
         "                                                   std::uint32_t stored_crown = ResetKey, // r89c\n"
         "                                                   std::uint32_t* key_crown = nullptr) {\n"),
        ("    if (key != nullptr) {\n        *key = std::fabs(wy) < FiniteMost ? HeightKey(wy) : ResetKey;\n    }\n",
         H_KEY_CROWN + "    if (key != nullptr) {\n        *key = std::fabs(wy) < FiniteMost ? HeightKey(wy) : ResetKey;\n    }\n"),
        (H_W_OLD, H_W_NEW),
        (H_OUT_OLD, H_OUT_OLD + H_DIP),
        ("        std::uint32_t best = BaseSlots;\n",
         "        std::uint32_t best = PlantSlots; // bbport (r89c_wind-lean): the plant slots\n"),
        ("        for (std::uint32_t i = 0; i < BaseSlots; ++i) {\n            const Slot& slot = slots[i];\n",
         "        for (std::uint32_t i = 0; i < PlantSlots; ++i) {\n            const Slot& slot = slots[i];\n"),
        ("        if (best == BaseSlots) {\n",
         "        if (best == PlantSlots) {\n"),
        ("    std::array<Slot, BaseSlots> slots{};\n",
         "    std::array<Slot, PlantSlots> slots{}; // bbport (r89c_wind-lean): CrownAt's half is crowns\n"),
    ],
    EMIT: [
        (E_STORED, E_STORED + E_CROWN),
        (E_W_OLD, E_W_NEW),
        (E_FRONT_OLD, E_FRONT_NEW),
        (E_D_OLD, E_D_NEW),
        (E_END, E_OFFER + E_END),
    ],
    LIFT: [
        (L_STORED, L_STORED + L_CROWN),
        (L_W_OLD, L_W_NEW),
        (L_FRONT_OLD, L_FRONT_NEW),
        (L_D_OLD, L_D_NEW),
        (L_END, L_OFFER + L_END),
    ],
    EFFECTS: [
        (F_FILL_OLD, F_FILL_NEW),
        (F_RESET, F_RESET_CROWN + F_RESET),
        (F_ONCE_OLD, F_ONCE_NEW),
        (F_LINE_OLD, F_LINE_NEW),
        ("                     sway_slots.InUse(sway_frame), BbWindSway::BaseSlots);\n",
         "                     sway_slots.InUse(sway_frame), BbWindSway::PlantSlots); // (r89c)\n"),
    ],
    SERIAL: [
        ("static constexpr u32 SwayShaderBinaryVersion = 10u;\n",
         "static constexpr u32 SwayShaderBinaryVersion = 11u; // bbport (r89c_wind-lean): the lean\n"),
        ("static constexpr u32 HangShaderBinaryVersion = 20u;\n",
         "static constexpr u32 HangShaderBinaryVersion = 21u; // bbport (r89c_wind-lean): the lean\n"),
    ],
    TEST: [
        ("    return ab / std::sqrt(aa * bb);\n}\n} // namespace\n",
         "    return ab / std::sqrt(aa * bb);\n}\n" + T_HELPERS + "} // namespace\n"),
        ("        for (std::uint64_t i = 1; i < BaseSlots; ++i) {\n",
         "        for (std::uint64_t i = 1; i < PlantSlots; ++i) { // bbport (r89c_wind-lean)\n"),
        ("        Expect(all && slots.InUse(41) == BaseSlots, \"every slot taken\");\n",
         "        Expect(all && slots.InUse(41) == PlantSlots, \"every slot taken\");\n"),
        ("    // The log's texts.\n",
         T_TESTS + "    // The log's texts.\n"),
    ],
    README: [
        (README_SWAY_OLD, README_SWAY_NEW),
        (README_RIPPLE_OLD, README_RIPPLE_NEW),
        (README_SHOW, README_ROWS + README_SHOW),
    ],
}

CHECKS = {
    HEADER: [("PlantSlots = BaseSlots / 2, CrownAt = BaseAt + PlantSlots;", 1), ("inline bool FillLean(", 1),
             ("inline bool FillRipple(", 1), ("std::uint32_t stored_crown = ResetKey", 1),
             ("RegionBytes == 8192", 1), ("i < BaseSlots", 0), ("std::array<Slot, PlantSlots>", 1),
             ("p[13] * LeanSkew", 1), ("view[RippleD + 1]", 1), ("Take(s, show, sway_hz, cross_hz, fronts);", 1),
             ("two_pi * sway_hz / wave", 1), ("two_pi * sway_hz, two_pi * cross_hz", 1), ("CrownKey(wy)", 1)],
    EMIT: [("u64(W::CrownAt)", 1), ("row(W::RippleD)", 2), ("OpAtomicUMin", 3),
           ("moved[r] = add(moved[r], mul(comp(row(W::ForwardAt + r * 4u), 1u), ddy));", 1),
           ("W::LeanSkew", 1), ("W::TreeLo", 1), ("W::DipFloor", 1), ("EmitVertexSway(ctx);", 1)],
    LIFT: [("u64(W::CrownAt)", 1), ("row(W::RippleD)", 2), ("OpAtomicUMin", 3),
           ("moved[r] = FAdd(moved[r], FMul(comp(row(W::ForwardAt + r * 4), 1), ddy));", 1),
           ("W::LeanSkew", 1), ("W::TreeLo", 1), ("W::DipFloor", 1), ("VertexSway();", 1)],
    EFFECTS: [("BbWindSway::FillLean(", 1), ("BbWindSway::FillRipple(", 1), ("LeanTableText(", 1),
              ("LeanOnceText(", 1), ("LeanText(", 1), ("RippleText(", 1), ("RippleOnceText(", 1),
              ("BbWindSway::CrownAt + taken.slot", 1), ("BbWindSway::BaseSlots", 0),
              ('            BbReport::Printf("%s\\n", ripple);\n', 1)],
    SERIAL: [("SwayShaderBinaryVersion = 11u;", 1), ("SwayShaderBinaryVersion = 10u;", 0),
             ("HangShaderBinaryVersion = 21u;", 1)],
    TEST: [("LeanViewOf(", 15), ("LeanMoveOf(", 9), ("wind-sway-test: ok", 1), ("i < BaseSlots", 0)],
    README: [("| `BB_WIND_SWAY_STYLE` |", 1), ("| `BB_WIND_SWAY_WAVE` |", 1), ("| `BB_WIND_SWAY_SHOW` |", 1),
             ("| `BB_WIND_SWAY_RIPPLE` |", 1)],
}

ORDER = {
    HEADER: ["inline constexpr std::uint32_t BaseSlots = 1024;", "PlantSlots = BaseSlots / 2",
             "ShowGain = 2.5f, ShowWave = 2.5f", "BendMax = 0.12f", "inline float KeyHeight(",
             "inline std::uint32_t CrownKey(", "struct Camera {", "class Ripple {",
             "inline bool FillRipple(", "struct LeanKnob {", "inline bool FillLean(",
             "inline float Envelope(", "p[13] * LeanSkew", "inline std::array<float, 4> Displace(",
             "if (key_crown != nullptr)", "if (key != nullptr)", "const float lean = view[RippleD + 1];",
             "RippleOr(view, clip,", "if (0.0f < lean) {", "class Slots {"],
    EMIT: ["static void EmitVertexSway(", "const Id stored =", "const Id crown_ptr", "const Id h = ",
           "const Id t = ", "const Id lean_d", "const Id w = ", "const Id ddx_one", "const Id skew",
           "const Id d =", "const Id dip", "ctx.OpStore(ctx.output_position", "ctx.AddLabel(offer_merge);", "const Id crown_key",
           "ctx.OpBranch(sway_merge);", "void EmitEpilogue("],
    LIFT: ["void Lift_::VertexSway() {", "const u32 stored =", "const u32 crown_ptr", "const u32 h = ",
           "const u32 t = ", "const u32 lean_d", "const u32 w = ", "const u32 ddx_one", "const u32 skew",
           "const u32 d = ", "const u32 dip", "EmitVoid(O(spv::Op::OpStore), {var_position", "Open(offer_merge);", "const u32 crown_key",
           "EmitVoid(O(spv::Op::OpBranch), {sway_merge});", "void Lift_::VertexMotion() {"],
    EFFECTS: ["u32 Rasterizer::WindSwayWord(", "BbWindSway::FillLean(", "BbWindSway::FillRipple(",
              "BbWindSway::CrownAt + taken.slot", "BbWindSway::BaseAt + taken.slot",
              "void Rasterizer::WindSwayFrameEnd()", "LeanTableText(", "RippleOnceText(", "LeanText(",
              "RippleText(", "BbWindSway::PlantSlots); // (r89c)"],
    TEST: ["std::array<float, ViewWords> LeanViewOf(", "BbWind::Snapshot Gusty(", "} // namespace", "int main() {",
           "i < PlantSlots", "the style and the wave's knobs", "The lean's log texts", "// The log's texts.",
           "wind-sway-test: ok"],
    README: ["| `BB_WIND_SWAY` |", "With `BB_WIND_SWAY_STYLE=wave` and `BB_WIND_SWAY_RIPPLE=0`",
             "| `BB_WIND_SWAY_RIPPLE` |", "| `BB_WIND_SWAY_STYLE` |", "| `BB_WIND_SWAY_WAVE` |",
             "| `BB_WIND_SWAY_SHOW` |"],
}

# Numbers written twice (rule 10): the header's constant and the README rows' text.
TIES = [("BendMax = 0.12f", "D = 0.12 m x (v / 4 m/s)^2"), ("LeanRest = 0.25f", "G (0.25 D + D E"),
        ("LeanSkew = 0.6f", "skewed by 0.6"), ("WaveRatio = 0.15f, WaveCross = 0.075f", "W = 0.15 D x"),
        ("WaveHz0 = 0.15f, WaveHzPerSpeed = 0.15f, WaveCrossFactor = 1.5f", "at 0.15 + 0.15 v Hz along and 1.5 times"),
        ("LeafFrom = 2.5f, LeafFull = 4.0f", "only from 2.5 m/s, 0.012 m x the wave knob in full at 4 m/s"),
        ("TreeLo = 2.0f, TreeHi = 3.5f", "smoothstep(2, 3.5 m, its height)"),
        ("CrownLow = 0.5f", "its lower half stays still"),
        ("TreeCalm = 1.0f, TreeFull = 4.0f", "smoothstep(1, 4 m/s, v)"),
        ("WaveDefault = 1.0f, WaveMax = 4.0f", "1 the default (0.15"),
        ("ShowGain = 2.5f, ShowWave = 2.5f", "bend 2.5 times larger and the fronts 2.5 times closer")]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, s, texts[path].count(s), n))
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                raise SystemExit("order check: %s: %r not after the one before" % (path, s))
            at = i
    rows = "\n".join(l for l in texts[README].split("\n") if l.startswith("| `BB_WIND_SWAY_"))
    for const, value in TIES:
        if texts[HEADER].count(const) != 1 or value not in rows:
            raise SystemExit("tie check: %r against the README rows (%r)" % (const, value))
    for edits in EDITS.values():
        for old, new in edits:
            if not all(ord(c) < 128 for c in new) or "\r" in new:
                raise SystemExit("new text must be ASCII with LF in the script")
            if any(x in new for x in ("C:/", "G:/", "<user>", "Temp/claude")):
                raise SystemExit("a local path in the patch's text")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R89C_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = todo = 0
        for old, new in edits:
            if cur.count(new) == 1:
                done += 1
            elif cur.count(old) == 1 and cur.count(new) == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once): %r"
                                 % (path, cur.count(old), old.split("\n")[0][:80]))
        if done == len(edits):
            state = "applied"
        elif todo == len(edits):
            state = "clean"
        else:
            raise SystemExit("%s: %d of %d edits applied" % (path, done, len(edits)))
        plan.append((path, edits, raw, eol, cur, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, edits, raw, eol, cur, _ in plan:
            for old, new in edits:
                if cur.count(old) != 1:
                    raise SystemExit("REFUSED %s: anchor not once after the edits before it: %r"
                                     % (path, old.split("\n")[0][:80]))
                cur = cur.replace(old, new)
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
        for path, edits, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, edits, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r89ctmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, edits, raw, eol, cur, _ in plan:
        for old, new in reversed(edits):
            if cur.count(new) != 1:
                raise SystemExit("%s: an edit's text is not there once; nothing written" % path)
            cur = cur.replace(new, old)
        for old, new in edits:
            if cur.count(old) != 1 or cur.count(new) != 0:
                raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, edits, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r89ctmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
