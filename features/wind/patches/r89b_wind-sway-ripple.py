# r89b_wind-sway-ripple: FEATURE patch (part of the wind work: "Foliage sway"). The owner on r89's
# 4K clip (verbatim): "Nice I like it, maybe the sway can ripple with wind instead of the whole
# thing moving?" r89 (S/r89_wind-foliage-sway.fixed.py, in the tree) bends each plant as one piece:
# a lean of 0.06 m and a swing of 0.06 m (0.7 Hz) along the wind and 0.025 m (1.3 Hz) across, the
# same direction for every vertex at one height, in a wave about 2 m long, times a gust factor that
# changes over tens of metres. r89b makes the motion ripple THROUGH the foliage. Off unless the
# sway is on (BB_WIND=1 and BB_WIND_SWAY above 0); then on by default (BB_WIND_SWAY_RIPPLE unset
# or 1); BB_WIND_SWAY_RIPPLE=0 gives r89's motion exactly (for a side by side clip), a number from
# 0.25 to 4 is the strength. BB_WIND_SWAY_SHOW=1 is a test view (fronts 2.5 times closer, the
# ripple 2.5 times stronger). Environment only, read once; no ini key.
#
# What r89 reads at its hook (both emitters, first in the vertex epilogue): the vertex's clip
# position only (it moves vertices in the vertex shader, per vertex; it does not shift whole draws),
# the draw's sway word (motion param word 7) and the sway words of the draw's view (camera rows,
# wind, gust table) and its mesh's base key. From the clip position it gets the world position
# relative to the camera (x, y, z). Weight signal used here, as r89: h = the vertex's world y minus
# the lowest world y any vertex of its mesh had (GPU atomic minimum per mesh), w = smoothstep(0,
# 0.75 m, h) times the 1 s ramp; the leaves' flutter takes w times min(h / 0.75 m, 1), so it grows
# more slowly from the roots. Not available: a vertex colour, a UV or a bone weight that marks the
# tips (the game's vertex attributes have no known meaning to the port, the input positions are bind
# pose, a mesh has no known up axis or ground height).
#
# The ripple (bbport_wind_sway.h: RippleOr, Envelope, Ripple, FillRipple; both emitters operation
# for operation):
#  1. Gust fronts: an envelope E = 2 smoothstep(-0.5, 0.5, n), n the mean of the sines of three
#     waves 9, 13 and 17 m long (along the wind, 35 and -50 degrees off it), advected by the wind
#     at its speed times its gust factor: fronts and calms travel through a bush and from plant to
#     plant downwind (up-wind plants move first). E is 0 in a calm (about a quarter of the time), up
#     to 2 in a front (about a third), mean 1. It multiplies r89's swing (r89's two waves, which
#     travel downwind at max(speed, 0.5 m/s)) and moves the lean by LeanGust x strength x (E - 1).
#     Everything is times r89's gust factor AT THE VERTEX (its gust table, which travels downwind
#     at the wind's mean speed), so a gust also reaches plants one after another (review fix: the
#     draft used the wind's gust factor now for every plant at once, which pulsed every plant in
#     step; CPU probe, plants 15 m apart downwind, 1 s means of the along-wind motion: correlation
#     0.40 with the draft, 0.14 now, 0.50 with r89).
#  2. Leaves: two flutter waves 0.9 m and 0.65 m long, fixed in the world (directions with an up
#     part, so the phase changes across, along and up a plant) at 1.9 and 2.7 Hz, 0.012 m x strength
#     x (0.5 + 0.5 E) along and across the wind, held to 0.08 m: neighbouring leaves are out of step.
#  3. The base stays: r89's weight (above) for the swing and lean, w t for the flutter.
#  4. No tearing: every term is a function of the vertex's world position (from its clip position)
#     and of the draw's words, never of the vertex index. No popping: the waves' phases are kept on
#     the CPU (Rasterizer::sway_ripple, BbWindSway::Ripple) at an anchor that moves with the camera
#     (exactly: psi += K . (camera - anchor), in double), are advanced by omega dt of wind time, and
#     then the waves take the wind's new direction, so a turning wind turns them about the camera.
#     The gust table's time at the camera is kept the same way (re-anchored by (camera - anchor) .
#     dir / speed, advanced by dt), and with the ripple on FillRipple writes r89's two swing phases
#     and the gust table from these (r89's shader code then reads them; BB_WIND_SWAY_RIPPLE=0
#     leaves r89's words as they were). r89's own formula takes its phases and its gust times from
#     world coordinates, so a turning wind (r82's direction
#     already wanders 15 degrees over minutes) sweeps them by k |position| per radian: far from the
#     world's origin that is a fast shimmer (wind-sway-test: per frame 0.15 m at 3900 m and 2
#     deg/s in the Python twin; the ripple 0.022 m, a steady wind 0.018 m). RIPPLE=0 keeps r89's.
#  5. Motion vectors and the ray traced shadows: unchanged hook (r89's: first in the epilogue,
#     before the motion store and the ray traced capture), so both take the rippled position, as
#     they take r89's: the motion store keeps each vertex's clip position and the next frame's
#     motion is the difference, so the upscaler gets the true motion of every leaf; the ray traced
#     scene refits plants from the captured positions at their draws as with r89. The flutter is
#     smooth at triangle scale (waves of 0.65-0.9 m against leaves of a few cm), not the leaf
#     probe's incoherent per-leaf noise; its effect on the refit's bounds is not measured.
#
# Shader binaries: a vertex shader with the Sway bit gets its own binary version
# (vk_pipeline_serialization.cpp, SwayShaderBinaryVersion 10), so a sway shader that a run with r89
# saved is built again (with the ripple code) instead of loaded. Every other shader keeps its
# version (no rebuild of anything else).
#
# Cost off (BB_WIND unset or BB_WIND_SWAY=0): nothing new runs. No pipeline has the Sway bit, so no
# new SPIR-V; WindSwayWord and the log are not reached; one Ripple member (352 bytes) in the
# Rasterizer. With the sway on: per plant vertex 5 more 16-byte loads (rows RippleA-D and the y row
# of T), 5 more sines (3 fronts, 2 leaf waves; the ripple's sin a1 and sin a2 repeat r89's on the
# same operands, 2 more if the driver's compiler does not merge them; r89's gust lookup is
# shared), about 110 more arithmetic operations (counted in the emitted code; r89's displacement is
# still computed and a select picks one); per new view
# a frame on the CPU 7 phase updates in double and 64 more BbWind::Gust calls (the table); the sway
# buffer 512 bytes longer (8192). Not measured; the plant draws are a few per frame.
#
# Review 2026-11-15 22:40 (r89b_wind-sway-ripple.fixed.py; the draft r89b_wind-sway-ripple.py is
# left as it was): the gust at the vertex (above), r89's swing angles shared instead of computed
# twice (2 wraps a vertex fewer), the once line's lean text, the README's rule and cost text, and
# checks for the gust table.
#
# Files: engine/gpu/shim/bbport_wind_sway.h (r89's header: layout, constants, knob, Ripple,
# FillRipple, Envelope, RippleOr, log texts, Displace calls RippleOr), emit_spirv_special.cpp
# (EmitVertexSway), lift_stage.cpp (Lift_::VertexSway), vk_rasterizer.h (member),
# vk_rasterizer_effects.cpp (WindSwayWord fills the words; the log lines), vk_pipeline_serialization
# .cpp (binary version), engine/tests/test_wind_sway.cpp (r89's test: one layout line changed, the
# ripple's checks added), README.md (two rows after BB_WIND_SWAY). No new files, no host shader.
#
# Log: once "Wind sway ripple (r89b, BB_WIND_SWAY_RIPPLE=1.00): ..." (or "Wind sway ripple (r89b):
# off (BB_WIND_SWAY_RIPPLE=0) ..."), and r89's line every 600 frames now starts "Wind sway (r89):
# ripple 1.00 (fronts 9.0 m apart, 1.50 m/s toward 225 deg, swing wave 2.1 m, N views); in 600
# frames ..." or "Wind sway (r89): ripple off (r89's one-piece motion); in 600 frames ...".
#
# Use: python -I -X utf8 r89b_wind-sway-ripple.py check | apply | revert (root from R89B_ROOT, else
# <tree>). Needs r89 applied; revert r89b before r89 (r89's own check reads "mixed" while
# r89b is applied, since r89b edits r89's new files and inserted texts). Files keep their line ends.
# Originals are kept in r89b_backup/ next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89b_backup")
ROOT = os.environ.get("R89B_ROOT") or "<tree>"
G = "engine/gpu/"
S = G + "shadps4/shader_recompiler/"
R = G + "shadps4/video_core/renderer_vulkan/"
L = G + "shim/lifter/"
HEADER = G + "shim/bbport_wind_sway.h"
TEST = "engine/tests/test_wind_sway.cpp"

H_CONSTANTS = r'''
// bbport (r89b_wind-sway-ripple): the ripple (BB_WIND_SWAY_RIPPLE, on by default with the sway;
// RippleOr has the rule). The strength: unset, empty, unreadable or not finite is RippleDefault, 0
// or less is 0 (r89's one-piece motion), else held to RippleMin-RippleMax.
inline constexpr float RippleDefault = 1.0f, RippleMin = 0.25f, RippleMax = 4.0f;
inline constexpr float LeanGust = 0.03f; ///< m: a gust front's extra lean (a calm's less)
inline constexpr float Leaf = 0.012f;    ///< m: the leaves' flutter, either way, x strength
inline constexpr float MaxLeaf = 0.08f;  ///< m: the flutter's limit along and across the wind
inline constexpr float LeafCalm = 0.5f;  ///< the share of the flutter that stays in a calm
inline constexpr float LeafHz1 = 1.9f, LeafHz2 = 2.7f; ///< Hz of the two leaf waves
/// The gust envelope E = EnvScale smoothstep(EnvLo, -EnvLo, n) (EnvInv = 1 / (-2 EnvLo)), n the
/// mean of three waves' sines: 0 in a calm, EnvScale in a gust front; its mean is 1 because n is
/// symmetric about 0 (wind-sway-test).
inline constexpr float EnvLo = -0.5f, EnvInv = 1.0f, EnvScale = 2.0f;
/// The gust fronts' waves in the wind's frame (rad per m along the wind s and across it q):
/// EnvWavelength m long at EnvAngle degrees off the wind; the along parts are negative, so the
/// waves, carried by the wind, travel downwind (wind-sway-test ties the numbers).
inline constexpr float EnvWavelength[3] = {9.0f, 13.0f, 17.0f}, EnvAngle[3] = {0.0f, 35.0f, -50.0f};
inline constexpr float Env1S = -0.69813170f, Env1Q = 0.0f, Env2S = -0.39591416f,
                       Env2Q = 0.27722208f, Env3S = -0.23757374f, Env3Q = -0.28312936f;
/// The leaf waves, fixed in the world (rad per m along x, y, z): LeafWavelength m long toward
/// LeafDir (with an up part: the phase changes across, along and up a plant).
inline constexpr float LeafWavelength[2] = {0.9f, 0.65f};
inline constexpr float LeafDir[2][3] = {{0.74f, 0.42f, 0.52f}, {-0.55f, 0.58f, 0.60f}};
inline constexpr float Leaf1X = 5.18070091f, Leaf1Y = 2.94039782f, Leaf1Z = 3.64049253f,
                       Leaf2X = -5.31946793f, Leaf2Y = 5.60962072f, Leaf2Z = 5.80305592f;
/// BB_WIND_SWAY_SHOW=1 (a test view): the gust fronts ShowWave times closer, the travelling part
/// and the flutter ShowGain times stronger (the limits stay).
inline constexpr float ShowGain = 2.5f, ShowWave = 2.5f;
'''

H_FUNCTIONS = r'''// bbport (r89b_wind-sway-ripple): the ripple. With a strength above 0 (BB_WIND_SWAY_RIPPLE, the
// default 1) the shaders (and Displace) take, in place of r89's displacement (RippleOr):
//   along = clamp(G (L + LG (E - 1) + SA E sin a1), +-MaxAlong),
//   cross = clamp(G SC E sin a2, +-MaxCross),
//   leaf = G LF (LeafCalm + (1 - LeafCalm) E), la = clamp(leaf sin b1, +-MaxLeaf), lc = ... sin b2,
//   d = w (along, cross) + w t (la, lc) in the wind's frame (along = toward where it blows),
// with r89's t = clamp(h / Height, 0, 1) and w = smoothstep(t) times the ramp (h: the height above
// the mesh's lowest point), so the roots stay and the leaves flutter in full from Height up. E is
// the gust envelope at the vertex (Envelope: three waves carried by the wind, so fronts and calms
// pass through a bush and from plant to plant downwind at the wind's speed times its gust; up-wind
// plants move first). a1 and a2 are r89's swing waves (k, k2 and j of its words: they travel
// downwind at max(speed, MinWaveSpeed)), b1 and b2 the leaf waves (Leaf1, Leaf2: fixed in the world
// at LeafHz1 and LeafHz2), all from the phases Ripple keeps (FillRipple writes a1's and a2's into
// r89's words WindB.w and WindC.z, so the shaders' sin a1 and sin a2 serve both rules). G is r89's
// gust factor at the vertex (its gust table, which FillRipple writes from the gust time Ripple
// keeps: the gust that passed the camera, carried downwind at max(speed, 0.1 m/s)). L = Lean,
// LG = LeanGust, SA = Flutter, SC = Cross, LF = Leaf, the last four times the strength (and
// ShowGain with BB_WIND_SWAY_SHOW=1), each times r89's amp (BB_WIND_SWAY times min(speed,
// SpeedCap) / RefSpeed). Each term depends on the vertex's world position (through its clip
// position) and the draw's words, never on the vertex's index, so a vertex that two triangles
// share moves the same way in both.

/// BB_WIND_SWAY_RIPPLE and BB_WIND_SWAY_SHOW.
struct RippleKnob {
    float strength = RippleDefault; ///< 0: r89's one-piece motion
    bool show = false;              ///< the test view (only with a strength above 0)
};

[[nodiscard]] inline RippleKnob ParseRipple(const char* ripple, const char* show) {
    RippleKnob k;
    const float value = ParseNumber(ripple, RippleDefault);
    k.strength = value > 0.0f ? std::clamp(value, RippleMin, RippleMax) : 0.0f;
    k.show = k.strength > 0.0f && show != nullptr && show[0] == '1';
    return k;
}

/// Read once, at the first view filled or the first log line.
[[nodiscard]] inline const RippleKnob& RippleKnobOnce() {
    static const RippleKnob knob =
        ParseRipple(std::getenv("BB_WIND_SWAY_RIPPLE"), std::getenv("BB_WIND_SWAY_SHOW"));
    return knob;
}

/// The ripple's wave phases, kept on the CPU so that they never jump. Wave i's phase at the world
/// point p is psi_i + K_i . (p - anchor). Update moves the anchor to the camera of the view being
/// filled without changing the field (psi_i += K_i . (camera - anchor), in double), advances the
/// phases by omega_i times the wind time since the last update, and then takes the wind's direction
/// and speed now for K_i: a turning wind turns the waves about the camera, so a point d m away sees
/// its phase change by at most |K_i| d times the turn's angle. Waves: 0 and 1 r89's swing (K =
/// -k dir + j across and -k2 dir - j across; omega 2 pi SwayHz and 2 pi CrossHz), 2-4 the gust
/// fronts (Env1-Env3 in the wind's frame, ShowWave times with the test view; carried by the wind:
/// omega = -K . wind, the wind being speed times gust along dir), 5 and 6 the leaves (Leaf1, Leaf2,
/// fixed in the world; omega 2 pi LeafHz1 and 2 pi LeafHz2). The gust time is kept alike: r89's
/// gust table holds Gust(t - (p . dir) / v) of the world point p (v = max(speed, 0.1 m/s)); Ripple
/// keeps the time at the anchor (moved by -(camera - anchor) . dir / v, advanced by dt; at the
/// first view r89's own value), so the table FillRipple writes is r89's gust carried downwind, and
/// a turning wind turns it about the camera too.
class Ripple {
public:
    static constexpr std::uint32_t Waves = 7;

    void Update(const BbWind::Snapshot& s, float cx, float cy, float cz, bool show) {
        const double c[3] = {cx, cy, cz};
        if (ready) {
            for (std::uint32_t i = 0; i < Waves; ++i) {
                psi[i] += k[i][0] * (c[0] - anchor[0]) + k[i][1] * (c[1] - anchor[1]) +
                          k[i][2] * (c[2] - anchor[2]);
            }
            gust_time -= ((c[0] - anchor[0]) * gust_dir[0] + (c[2] - anchor[2]) * gust_dir[1]) /
                         gust_speed;
            const double dt = s.time - time;
            if (dt > 0.0 && std::isfinite(dt)) {
                for (std::uint32_t i = 0; i < Waves; ++i) {
                    psi[i] += omega[i] * dt;
                }
                gust_time += dt;
            }
        } else {
            psi = {0.0, 1.9, 0.6, 2.7, 4.1, 0.0, 3.0};
        }
        anchor = {c[0], c[1], c[2]};
        time = s.time;
        Take(s, show);
        if (!ready) {
            // r89's FillView: s.time - (camera . dir) / v
            gust_time = s.time - (c[0] * gust_dir[0] + c[2] * gust_dir[1]) / gust_speed;
        }
        for (double& p : psi) {
            p = WrapTwoPi(p);
        }
        ready = true;
    }

    [[nodiscard]] double Phase(std::uint32_t i) const {
        return psi[i];
    }

    /// The gust time at the camera of the last Update (r89's s.time - (camera . dir) / v).
    [[nodiscard]] double GustTime() const {
        return gust_time;
    }

private:
    void Take(const BbWind::Snapshot& s, bool show) {
        const double two_pi = 6.28318530717958647692;
        const double speed = std::isfinite(s.speed) ? std::max(double(s.speed), 0.0) : 0.0;
        const double gust = std::isfinite(s.gust) ? double(s.gust) : 1.0;
        const double dx = s.dir_x, dz = s.dir_z;
        const double wave = std::max(speed, double(MinWaveSpeed));
        const double k1 = two_pi * SwayHz / wave, k2 = two_pi * CrossHz / wave;
        const double j = two_pi / CrossWavelength;
        const double ks = show ? ShowWave : 1.0;
        const double ab[5][2] = {{-k1, j},
                                 {-k2, -j},
                                 {Env1S * ks, Env1Q * ks},
                                 {Env2S * ks, Env2Q * ks},
                                 {Env3S * ks, Env3Q * ks}};
        for (std::uint32_t i = 0; i < 5; ++i) {
            k[i] = {ab[i][0] * dx - ab[i][1] * dz, 0.0, ab[i][0] * dz + ab[i][1] * dx};
        }
        k[5] = {Leaf1X, Leaf1Y, Leaf1Z};
        k[6] = {Leaf2X, Leaf2Y, Leaf2Z};
        const double u = speed * gust;
        omega = {two_pi * SwayHz,  two_pi * CrossHz, -ab[2][0] * u,   -ab[3][0] * u,
                 -ab[4][0] * u,    two_pi * LeafHz1, two_pi * LeafHz2};
        gust_dir = {dx, dz};
        gust_speed = std::max(speed, 0.1); // r89's FillView floor
    }

    std::array<double, Waves> psi{}, omega{};
    std::array<std::array<double, 3>, Waves> k{};
    std::array<double, 3> anchor{};
    std::array<double, 2> gust_dir{};
    double gust_speed = 1.0, gust_time = 0.0;
    double time = 0.0;
    bool ready = false;
};

/// The ripple's RippleWords words of a view after FillView (which leaves them 0, r89's motion):
/// with a strength above 0, `ripple` is updated for this view's camera and the words are written
/// (RippleA: the phases of waves 0-3; RippleB: waves 4-6 and the fronts' wave scale; RippleC:
/// L, SA, SC, LF; RippleD: LG, 0, 0, the flag 1), and r89's swing phases (WindB.w, WindC.z) and
/// gust table (TableAt; BB_WIND_GUSTS `gusts`) are written again from the values Ripple keeps.
/// Returns whether it wrote them (with a strength of 0 the view stays FillView's, r89's).
inline bool FillRipple(Ripple& ripple, const Camera& cam, const BbWind::Snapshot& s, float gusts,
                       float scale, const RippleKnob& knob, float* view) {
    if (!(knob.strength > 0.0f)) {
        return false;
    }
    ripple.Update(s, cam.x, cam.y, cam.z, knob.show);
    const float speed = std::isfinite(s.speed) ? std::max(s.speed, 0.0f) : 0.0f;
    const float amp = scale * std::min(speed, SpeedCap) / RefSpeed;
    const float r = knob.strength * (knob.show ? ShowGain : 1.0f);
    float* out = view + RippleAt;
    for (std::uint32_t i = 0; i < Ripple::Waves; ++i) {
        out[i] = float(ripple.Phase(i));
    }
    view[WindB + 3] = out[0];
    view[WindC + 2] = out[1];
    for (std::uint32_t i = 0; i < GustSamples; ++i) {
        // as FillView's table, the time taken from `ripple`
        const double t = ripple.GustTime() + (double(i) - GustMid) * GustStep;
        view[TableAt + i] = BbWind::Gust(t, gusts);
    }
    out[7] = knob.show ? ShowWave : 1.0f;
    out[8] = Lean * amp;
    out[9] = r * Flutter * amp;
    out[10] = r * Cross * amp;
    out[11] = r * Leaf * amp;
    out[12] = r * LeanGust * amp;
    out[13] = 0.0f;
    out[14] = 0.0f;
    out[15] = 1.0f;
    return true;
}

/// The gust envelope E at s, q m along and across the wind from the view's camera (the shaders'
/// rule): 0 in a calm, up to EnvScale in a front.
[[nodiscard]] inline float Envelope(const float* view, float s, float q) {
    const float* p = view + RippleAt;
    const float se = s * p[7], qe = q * p[7];
    const auto wave = [&](float phase, float ka, float kb) {
        return std::sin(Wrap(phase + ka * se + kb * qe));
    };
    const float n =
        (wave(p[2], Env1S, Env1Q) + wave(p[3], Env2S, Env2Q) + wave(p[4], Env3S, Env3Q)) *
        (1.0f / 3.0f);
    const float tt = std::clamp((n - EnvLo) * EnvInv, 0.0f, 1.0f);
    return tt * tt * (3.0f - 2.0f * tt) * EnvScale;
}

/// What the shaders put in place of r89's (ddx_one, ddz_one): the ripple's displacement where the
/// view's flag word (RippleD + 3) is above 0, else (ddx_one, ddz_one) themselves. rx, rz: the
/// vertex relative to the camera; s, q: along and across the wind; t, w: r89's weights; g, a1, a2:
/// r89's gust factor at the vertex and swing angles (from the words FillRipple rewrote).
[[nodiscard]] inline std::array<float, 2> RippleOr(const float* view,
                                                   const std::array<float, 4>& clip, float rx,
                                                   float rz, float s, float q, float t, float w,
                                                   float g, float a1, float a2, float ddx_one,
                                                   float ddz_one) {
    const float* p = view + RippleAt;
    if (!(0.0f < p[15])) {
        return {ddx_one, ddz_one};
    }
    const float ry = view[ToWorldAt + 4] * clip[0] + view[ToWorldAt + 5] * clip[1] +
                     view[ToWorldAt + 6] * clip[2] + view[ToWorldAt + 7] * clip[3];
    const float env = Envelope(view, s, q);
    const auto leaf_wave = [&](float phase, float kx, float ky, float kz) {
        return std::sin(Wrap(phase + kx * rx + ky * ry + kz * rz));
    };
    const float b1 = leaf_wave(p[5], Leaf1X, Leaf1Y, Leaf1Z);
    const float b2 = leaf_wave(p[6], Leaf2X, Leaf2Y, Leaf2Z);
    const float dx = view[WindA], dz = view[WindA + 1];
    const float along = std::clamp(g * (p[8] + p[12] * (env - 1.0f) + p[9] * env * std::sin(a1)),
                                   -view[WindE], view[WindE]);
    const float cross =
        std::clamp(g * (p[10] * env * std::sin(a2)), -view[WindE + 1], view[WindE + 1]);
    const float leaf = g * (p[11] * (LeafCalm + (1.0f - LeafCalm) * env));
    const float la = std::clamp(leaf * b1, -MaxLeaf, MaxLeaf);
    const float lc = std::clamp(leaf * b2, -MaxLeaf, MaxLeaf);
    const float wf = w * t;
    return {w * (dx * along - dz * cross) + wf * (dx * la - dz * lc),
            w * (dz * along + dx * cross) + wf * (dz * la + dx * lc)};
}

/// The once line (Rasterizer::WindSwayFrameEnd), under 300 characters: the amplitudes at
/// RefSpeed and a gust factor of 1, before the limits it names.
inline void RippleOnceText(const RippleKnob& k, float scale, char* out, std::size_t size) {
    if (!(k.strength > 0.0f)) {
        std::snprintf(out, size,
                      "Wind sway ripple (r89b): off (BB_WIND_SWAY_RIPPLE=0); the plants sway as "
                      "one piece (r89's motion)");
        return;
    }
    const float ks = k.show ? ShowWave : 1.0f;
    const float r = k.strength * (k.show ? ShowGain : 1.0f) * scale;
    std::snprintf(out, size,
                  "Wind sway ripple (r89b, BB_WIND_SWAY_RIPPLE=%.2f%s): gust fronts (waves %.1f, "
                  "%.1f, %.1f m) travel downwind; at 1.5 m/s swing %.3f/%.3f m "
                  "x front 0-%.0f, lean %.3f +-%.3f m, leaves %.3f m at %.1f/%.1f Hz, all x the "
                  "gust at the plant (held to %.2f/%.2f/%.2f m); roots still",
                  double(k.strength), k.show ? ", SHOW" : "", double(EnvWavelength[0] / ks),
                  double(EnvWavelength[1] / ks), double(EnvWavelength[2] / ks),
                  double(Flutter * r), double(Cross * r), double(EnvScale), double(Lean * scale),
                  double(LeanGust * r), double(Leaf * r), double(LeafHz1), double(LeafHz2),
                  double(MaxAlong), double(MaxCross), double(MaxLeaf));
}

/// The ripple's state at the front of r89's line every ReportFrames frames: the strength, the
/// fronts' spacing (m), their speed (m/s: the wind's speed times its gust now), the direction
/// (degrees), the swing's wavelength (m) and how many views got the ripple's words.
inline void RippleText(const RippleKnob& k, const BbWind::Snapshot& s, std::uint64_t views,
                       char* out, std::size_t size) {
    if (!(k.strength > 0.0f)) {
        std::snprintf(out, size, "ripple off (r89's one-piece motion)");
        return;
    }
    const float speed = std::isfinite(s.speed) ? std::max(s.speed, 0.0f) : 0.0f;
    const float gust = std::isfinite(s.gust) ? s.gust : 1.0f;
    std::snprintf(out, size,
                  "ripple %.2f%s (fronts %.1f m apart, %.2f m/s toward %.0f deg, swing wave "
                  "%.1f m, %llu views)",
                  double(k.strength), k.show ? " SHOW" : "",
                  double(EnvWavelength[0] / (k.show ? ShowWave : 1.0f)), double(speed * gust),
                  double(s.direction_deg), double(std::max(speed, MinWaveSpeed) / SwayHz),
                  static_cast<unsigned long long>(views));
}

'''

R89_DISPLACE = r'''
// bbport (r89b_wind-sway-ripple): r89's Displace before the ripple, word for word but for its name
// and the key it can return (not needed here), for the check that BB_WIND_SWAY_RIPPLE=0 is r89's
// motion bit for bit.
std::array<float, 4> R89Displace(const float* view, const std::array<float, 4>& clip,
                                 std::uint32_t stored, float ramp) {
    const auto dot = [&](std::uint32_t at) {
        return view[at] * clip[0] + view[at + 1] * clip[1] + view[at + 2] * clip[2] +
               view[at + 3] * clip[3];
    };
    const float rx = dot(ToWorldAt), rz = dot(ToWorldAt + 8);
    const float wy = dot(ToWorldAt + 4) + view[WindA + 2];
    const float h = wy - KeyHeight(stored);
    const bool fin = std::fabs(h) + std::fabs(rx) + std::fabs(rz) < FiniteMost;
    if (!fin) {
        return clip;
    }
    const float t = std::clamp(h * view[WindD], 0.0f, 1.0f);
    const float w = t * t * (3.0f - 2.0f * t) * ramp;
    const float dx = view[WindA], dz = view[WindA + 1];
    const float s = rx * dx + rz * dz;
    const float q = rz * dx - rx * dz;
    const float u = std::clamp(view[WindD + 1] - s * view[WindC + 3], 0.0f, view[WindD + 2]);
    const std::uint32_t i = std::min(std::uint32_t(std::floor(u)), GustSamples - 2);
    const float f = u - float(i);
    const float g0 = view[TableAt + i], g1 = view[TableAt + i + 1];
    const float g = g0 + (g1 - g0) * f;
    const float a1 = Wrap(view[WindB + 3] - view[WindC] * s + view[WindC + 1] * q);
    const float a2 = Wrap(view[WindC + 2] - view[WindD + 3] * s - view[WindC + 1] * q);
    const float along =
        std::clamp(g * (view[WindB] + view[WindB + 1] * std::sin(a1)), -view[WindE], view[WindE]);
    const float cross = std::clamp(g * (view[WindB + 2] * std::sin(a2)), -view[WindE + 1],
                                   view[WindE + 1]);
    const float ddx = w * (dx * along - dz * cross);
    const float ddz = w * (dz * along + dx * cross);
    std::array<float, 4> out = clip;
    for (std::uint32_t r = 0; r < 4; ++r) {
        out[r] = clip[r] + (view[ForwardAt + r * 4] * ddx + view[ForwardAt + r * 4 + 2] * ddz);
    }
    return out;
}

// bbport (r89b_wind-sway-ripple): a view of constants c in wind s with the ripple of `knob` (its
// phases kept in `ripple`, which each call updates for this camera and time).
std::array<float, ViewWords> RippleViewOf(const std::array<float, 216>& c,
                                          const BbWind::Snapshot& s, Ripple& ripple,
                                          const RippleKnob& knob, float scale = 1.0f,
                                          float gusts = 0.5f) {
    Camera cam;
    const bool ok = CameraOf(c.data(), cam);
    Expect(ok, "the camera of the test constants");
    std::array<float, ViewWords> view{};
    FillView(cam, s, gusts, scale, view.data());
    (void)FillRipple(ripple, cam, s, gusts, scale, knob, view.data());
    return view;
}

// How the sway moves world point p (its mesh's lowest point at height `base`), in the world.
std::array<double, 3> MoveOf(const float* view, const std::array<float, 216>& c,
                             const std::array<double, 3>& p, float base, float ramp = 1.0f) {
    const auto clip = ClipOf(c, p);
    const auto before = WorldOf(view, clip);
    const auto after = WorldOf(view, Displace(view, clip, HeightKey(base), ramp));
    return {after[0] - before[0], after[1] - before[1], after[2] - before[2]};
}

double Length(const std::array<double, 3>& d) {
    return std::hypot(d[0], d[2]);
}

double Correlation(const std::vector<double>& a, const std::vector<double>& b) {
    double ma = 0.0, mb = 0.0;
    for (std::size_t i = 0; i < a.size(); ++i) {
        ma += a[i];
        mb += b[i];
    }
    ma /= double(a.size());
    mb /= double(b.size());
    double ab = 0.0, aa = 0.0, bb = 0.0;
    for (std::size_t i = 0; i < a.size(); ++i) {
        ab += (a[i] - ma) * (b[i] - mb);
        aa += (a[i] - ma) * (a[i] - ma);
        bb += (b[i] - mb) * (b[i] - mb);
    }
    return ab / std::sqrt(aa * bb);
}
'''

RIPPLE_TESTS = r'''    // bbport (r89b_wind-sway-ripple): the ripple's knob.
    {
        Expect(ParseRipple(nullptr, nullptr).strength == RippleDefault &&
                   !ParseRipple(nullptr, nullptr).show,
               "BB_WIND_SWAY_RIPPLE unset: the ripple at 1, no test view");
        Expect(ParseRipple("1", nullptr).strength == 1.0f, "1: the ripple");
        Expect(ParseRipple("0", "1").strength == 0.0f && !ParseRipple("0", "1").show,
               "0: r89's motion, and no test view");
        Expect(ParseRipple("-2", nullptr).strength == 0.0f, "below 0: 0");
        Expect(ParseRipple("0.1", nullptr).strength == RippleMin &&
                   ParseRipple("9", nullptr).strength == RippleMax,
               "a strength is held to 0.25-4");
        Expect(ParseRipple("2.5", nullptr).strength == 2.5f, "a strength is read");
        Expect(ParseRipple("abc", nullptr).strength == RippleDefault &&
                   ParseRipple("nan", nullptr).strength == RippleDefault &&
                   ParseRipple("", nullptr).strength == RippleDefault,
               "unreadable, not finite or empty: the default");
        Expect(ParseRipple(nullptr, "1").show && !ParseRipple(nullptr, "0").show,
               "BB_WIND_SWAY_SHOW=1");
    }

    // The ripple's constants are their wavelengths and angles; the envelope's mean is 1.
    {
        const double pi = 3.14159265358979323846;
        const float env[3][2] = {{Env1S, Env1Q}, {Env2S, Env2Q}, {Env3S, Env3Q}};
        bool tied = true;
        for (int i = 0; i < 3; ++i) {
            const double k = 2.0 * pi / EnvWavelength[i], a = EnvAngle[i] * pi / 180.0;
            tied &= Near(env[i][0], -k * std::cos(a), 1e-6) &&
                    Near(env[i][1], k * std::sin(a), 1e-6);
        }
        const float leaf[2][3] = {{Leaf1X, Leaf1Y, Leaf1Z}, {Leaf2X, Leaf2Y, Leaf2Z}};
        for (int i = 0; i < 2; ++i) {
            const double len = std::sqrt(double(LeafDir[i][0]) * LeafDir[i][0] +
                                         double(LeafDir[i][1]) * LeafDir[i][1] +
                                         double(LeafDir[i][2]) * LeafDir[i][2]);
            for (int d = 0; d < 3; ++d) {
                tied &= Near(leaf[i][d], 2.0 * pi / LeafWavelength[i] * LeafDir[i][d] / len, 1e-5);
            }
        }
        Expect(tied, "the waves' numbers are their wavelengths and directions");
        Expect(Near(EnvInv, 1.0 / (-2.0 * double(EnvLo)), 1e-7), "EnvInv = 1 / (-2 EnvLo)");
        std::array<float, ViewWords> view{};
        view[RippleB + 3] = 1.0f;
        double sum = 0.0;
        const int n = 40;
        for (int a = 0; a < n; ++a) {
            for (int b = 0; b < n; ++b) {
                for (int c = 0; c < n; ++c) {
                    view[RippleA + 2] = float(2.0 * pi * (a + 0.5) / n);
                    view[RippleA + 3] = float(2.0 * pi * (b + 0.5) / n);
                    view[RippleB] = float(2.0 * pi * (c + 0.5) / n);
                    sum += Envelope(view.data(), 0.0f, 0.0f);
                }
            }
        }
        Expect(Near(sum / (n * n * n), 1.0, 0.01), "the gust envelope's mean over its phases is 1");
    }

    // BB_WIND_SWAY_RIPPLE=0: no ripple words, and r89's displacement bit for bit.
    {
        std::uint32_t seed = 12345u;
        const auto rnd = [&seed]() {
            seed = seed * 1664525u + 1013904223u;
            return double(seed >> 8) / 16777216.0;
        };
        const RippleKnob off = ParseRipple("0", nullptr);
        bool same = true, zero = true, filled = false;
        int moved = 0;
        for (int i = 0; i < 400; ++i) {
            const double yaw = 6.28 * rnd(), pitch = -0.4 * rnd();
            const std::array<double, 3> eye = {400.0 * rnd() - 200.0, 20.0 * rnd(),
                                               400.0 * rnd() - 200.0};
            const auto c = Constants(yaw, pitch, eye);
            const auto s = Wind(1000.0 * rnd(), float(360.0 * rnd()), float(4.0 * rnd()));
            auto view = ViewOf(c, s, float(rnd()), float(3.0 * rnd()));
            Camera cam;
            Ripple ripple;
            Expect(CameraOf(c.data(), cam), "a camera");
            filled |= FillRipple(ripple, cam, s, 0.5f, 1.0f, off, view.data());
            zero &= std::all_of(view.begin() + RippleAt, view.end(),
                                [](float v) { return v == 0.0f; });
            const double ahead = 2.0 + 20.0 * rnd();
            const std::array<double, 3> p = {eye[0] - std::sin(yaw) * ahead + rnd() - 0.5,
                                             eye[1] - 1.5 + 2.0 * rnd(),
                                             eye[2] - std::cos(yaw) * ahead + rnd() - 0.5};
            const auto clip = ClipOf(c, p);
            const std::uint32_t stored = HeightKey(float(eye[1] - 1.6));
            const float ramp = float(rnd());
            const auto a = Displace(view.data(), clip, stored, ramp);
            const auto b = R89Displace(view.data(), clip, stored, ramp);
            same &= std::memcmp(a.data(), b.data(), sizeof(a)) == 0;
            moved += std::memcmp(a.data(), clip.data(), sizeof(a)) != 0 ? 1 : 0;
        }
        Expect(!filled && zero, "BB_WIND_SWAY_RIPPLE=0: no ripple words");
        Expect(same, "BB_WIND_SWAY_RIPPLE=0: r89's displacement bit for bit");
        Expect(moved > 200, "and those vertices moved");
    }

    // The ripple: still at weight 0, the same for the same world point, horizontal.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const RippleKnob on = ParseRipple(nullptr, nullptr);
        const auto s = Wind(5.0, 225.0f, 1.5f);
        const auto view = RippleViewOf(c, s, ripple, on);
        Expect(view[RippleD + 3] == 1.0f && view[RippleC] == Lean && view[RippleC + 1] == Flutter &&
                   view[RippleC + 3] == Leaf && view[RippleB + 3] == 1.0f,
               "the ripple's words at 1.5 m/s, gust 1, strength 1");
        const auto at = [](double up) {
            return std::array<double, 3>{10.0 - std::sin(0.3) * 6.0, 0.5 + up,
                                         20.0 - std::cos(0.3) * 6.0};
        };
        const auto top = ClipOf(c, at(1.2));
        const auto a = Displace(view.data(), top, HeightKey(0.5f), 1.0f);
        const auto b = Displace(view.data(), top, HeightKey(0.5f), 1.0f);
        Expect(std::memcmp(a.data(), b.data(), sizeof(a)) == 0, "the same vertex: the same result");
        const auto still = Displace(view.data(), top, HeightKey(0.5f), 0.0f);
        Expect(std::memcmp(still.data(), top.data(), sizeof(top)) == 0,
               "weight 0 (ramp 0): unchanged");
        Expect(Length(MoveOf(view.data(), c, at(0.0), 0.5f)) < 1e-4, "ripple: the roots stay");
        Expect(Length(MoveOf(view.data(), c, at(-0.3), 0.5f)) < 1e-4,
               "ripple: below the lowest point, still");
        const auto moved = MoveOf(view.data(), c, at(1.2), 0.5f);
        Expect(std::fabs(moved[1]) < 2e-3 && Length(moved) > 1e-3,
               "the ripple is horizontal and moves the top");
        // the same world points through a second view of the same frame, with its own camera
        const auto c2 = Constants(1.4, -0.3, {14.0, 3.0, 13.0});
        const auto view2 = RippleViewOf(c2, s, ripple, on);
        const auto view1 = RippleViewOf(c, s, ripple, on);
        double worst = 0.0;
        for (int i = 0; i < 40; ++i) {
            const std::array<double, 3> p = {8.0 + 0.1 * i, 1.4, 14.0 + 0.07 * i};
            const auto d1 = MoveOf(view1.data(), c, p, 0.5f);
            const auto d2 = MoveOf(view2.data(), c2, p, 0.5f);
            worst = std::max(worst, std::hypot(d1[0] - d2[0], d1[2] - d2[2]));
        }
        Expect(worst < 2e-3, "a world point moves alike in two views (a function of its position)");
    }

    // The ripple's amplitude is bounded: the strongest wind, scale, strength and test view.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const RippleKnob strongest = ParseRipple("4", "1");
        std::uint32_t seed = 777u;
        const auto rnd = [&seed]() {
            seed = seed * 1664525u + 1013904223u;
            return double(seed >> 8) / 16777216.0;
        };
        double worst = 0.0;
        for (int i = 0; i < 2000; ++i) {
            auto s = Wind(0.37 * i, float(225.0 + 40.0 * std::sin(0.01 * i)), BbWind::MaxSpeed);
            s.gust = BbWind::GustMax;
            const auto view = RippleViewOf(c, s, ripple, strongest, MaxScale, BbWind::MaxGusts);
            const std::array<double, 3> p = {10.0 - std::sin(0.3) * 6.0 + 6.0 * rnd() - 3.0, 2.0,
                                             20.0 - std::cos(0.3) * 6.0 + 6.0 * rnd() - 3.0};
            worst = std::max(worst, Length(MoveOf(view.data(), c, p, 0.5f)));
        }
        const double bound = std::hypot(double(MaxAlong), double(MaxCross)) +
                             std::hypot(double(MaxLeaf), double(MaxLeaf));
        Expect(worst <= bound + 3e-3, "the strongest ripple stays within its limits");
        Expect(worst > 0.3, "the strongest ripple reaches them");
    }

    // The gust fronts and the swing's wave move downwind with the wind (the crests too).
    {
        const auto c = Constants(0.7, -0.2, {120.0, 5.0, -310.0});
        Ripple ripple;
        const RippleKnob on = ParseRipple(nullptr, nullptr);
        const float speed = 1.5f;
        const auto first = RippleViewOf(c, Wind(100.0, 200.0f, speed), ripple, on);
        double t = 100.0;
        std::array<float, ViewWords> later{};
        for (int f = 0; f < 30; ++f) {
            t += 1.0 / 60.0;
            later = RippleViewOf(c, Wind(t, 200.0f, speed), ripple, on);
        }
        // the gust factor is 1 (Wind leaves it so): the fronts travel at the wind's speed, and the
        // swing's wave at max(speed, 0.5 m/s), the same here
        const double shift = speed * (t - 100.0);
        double same = 0.0, back = 0.0, swing = 0.0;
        for (int i = 0; i <= 80; ++i) {
            const float s = float(-20.0 + 0.5 * i), q = 1.3f;
            const float e = Envelope(later.data(), s, q);
            const float down = Envelope(first.data(), float(s - shift), q);
            const float up = Envelope(first.data(), float(s + shift), q);
            same = std::max(same, double(std::fabs(e - down)));
            back = std::max(back, double(std::fabs(e - up)));
            // the swing's phase as the shaders read it (r89's word, written by FillRipple)
            const float a_later = later[WindB + 3] - later[WindC] * s + later[WindC + 1] * q;
            const float a_first = first[WindB + 3] - first[WindC] * float(s - shift) +
                                  first[WindC + 1] * q;
            swing = std::max(swing, double(std::fabs(Wrap(a_later - a_first))));
        }
        Expect(same < 2e-3, "the gust fronts move downwind at the wind's speed");
        Expect(back > 0.05, "and not upwind");
        Expect(swing < 2e-3, "the swing's crests move downwind too");
        Expect(later[WindB + 3] == later[RippleA] && later[WindC + 2] == later[RippleA + 1],
               "r89's swing phases are the ripple's");
    }

    // The gust at the vertex: the first view's gust table is r89's; then it moves one sample
    // (GustStep s) per GustStep s of wind time, so a gust is carried downwind as with r89.
    {
        const auto c = Constants(0.7, -0.2, {120.0, 5.0, -310.0});
        Ripple ripple;
        const RippleKnob on = ParseRipple(nullptr, nullptr);
        const auto s0 = Wind(100.0, 200.0f, 1.5f);
        const auto first = RippleViewOf(c, s0, ripple, on);
        const auto plain = ViewOf(c, s0, 0.5f, 1.0f);
        double r89 = 0.0, moved = 0.0, still = 0.0;
        for (std::uint32_t i = 0; i < GustSamples; ++i) {
            r89 = std::max(r89, double(std::fabs(first[TableAt + i] - plain[TableAt + i])));
        }
        std::array<float, ViewWords> later{};
        for (int f = 1; f <= 60; ++f) {
            later = RippleViewOf(c, Wind(100.0 + f / 60.0, 200.0f, 1.5f), ripple, on);
        }
        for (std::uint32_t i = 0; i + 1 < GustSamples; ++i) {
            moved = std::max(moved, double(std::fabs(later[TableAt + i] - first[TableAt + i + 1])));
            still = std::max(still, double(std::fabs(later[TableAt + i] - first[TableAt + i])));
        }
        Expect(r89 < 1e-6, "the ripple's first gust table is r89's");
        Expect(moved < 1e-4 && still > 1e-3, "the ripple's gust table moves with the wind time");
    }

    // Calm moments and gust fronts at one point; the envelope's mean there is about 1.
    {
        const auto c = Constants(0.7, -0.2, {120.0, 5.0, -310.0});
        Ripple ripple;
        const RippleKnob on = ParseRipple(nullptr, nullptr);
        double sum = 0.0;
        int calm = 0, front = 0;
        const int steps = 6000;
        for (int i = 1; i <= steps; ++i) {
            const auto view = RippleViewOf(c, Wind(0.1 * i, 225.0f, 1.5f), ripple, on);
            const float e = Envelope(view.data(), 3.0f, -2.0f);
            sum += e;
            calm += e < 0.25f ? 1 : 0;
            front += e > 1.5f ? 1 : 0;
        }
        Expect(Near(sum / steps, 1.0, 0.15), "the gust envelope's mean at a point is about 1");
        Expect(calm > steps / 10 && front > steps / 10,
               "calm moments and gust fronts, each over a tenth of the time");
    }

    // Neighbouring leaves are out of step: the flutter of two points 0.3 m apart.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const RippleKnob on = ParseRipple(nullptr, nullptr);
        const std::array<double, 3> pa = {10.0 - std::sin(0.3) * 4.0, 1.6,
                                          20.0 - std::cos(0.3) * 4.0};
        const std::array<double, 3> pb = {pa[0] + 0.18, 1.6, pa[2] + 0.24};
        std::vector<double> fa, fb;
        for (int i = 1; i <= 600; ++i) {
            const auto view = RippleViewOf(c, Wind(50.0 + i / 60.0, 225.0f, 1.5f), ripple, on);
            auto calm = view;
            calm[RippleC + 3] = 0.0f; // no flutter
            fa.push_back(MoveOf(view.data(), c, pa, 0.5f)[0] - MoveOf(calm.data(), c, pa, 0.5f)[0]);
            fb.push_back(MoveOf(view.data(), c, pb, 0.5f)[0] - MoveOf(calm.data(), c, pb, 0.5f)[0]);
        }
        double rms = 0.0;
        for (const double v : fa) {
            rms += v * v;
        }
        rms = std::sqrt(rms / double(fa.size()));
        Expect(std::fabs(Correlation(fa, fb)) < 0.5 && rms > 2e-3,
               "leaves 0.3 m apart flutter out of step");
    }

    // A wind turning 2 deg/s, 3900 m from the world's origin: no jump (the steps from frame to
    // frame stay those of a steady wind).
    {
        const auto largest_step = [](double turn) {
            const std::array<double, 3> eye = {3000.0, 10.0, -2500.0};
            const auto c = Constants(0.4, -0.1, eye);
            Ripple ripple;
            const RippleKnob on = ParseRipple(nullptr, nullptr);
            const std::array<double, 3> p = {eye[0] - std::sin(0.4) * 8.0, 9.0,
                                             eye[2] - std::cos(0.4) * 8.0};
            std::array<double, 3> last{};
            double worst = 0.0;
            for (int f = 1; f <= 1200; ++f) {
                const double t = 10.0 + f / 60.0;
                const auto view =
                    RippleViewOf(c, Wind(t, float(225.0 + turn * (t - 10.0)), 1.5f), ripple, on);
                const auto d = MoveOf(view.data(), c, p, 7.5f);
                if (f > 1) {
                    worst = std::max(worst, std::hypot(d[0] - last[0], d[2] - last[2]));
                }
                last = d;
            }
            return worst;
        };
        const double steady = largest_step(0.0), turning = largest_step(2.0);
        Expect(steady > 1e-3 && turning <= 1.5 * steady + 1e-4, "a turning wind: no jump");
    }

    // The log's texts.
    {
        char text[512];
        const auto s = Wind(10.0, 231.0f, 1.5f);
        RippleText(ParseRipple("0", nullptr), s, 0, text, sizeof(text));
        Expect(std::strstr(text, "ripple off") != nullptr, "the line says the ripple is off");
        RippleText(ParseRipple(nullptr, nullptr), s, 7, text, sizeof(text));
        Expect(std::strstr(text, "ripple 1.00 (fronts 9.0 m apart, 1.50 m/s toward 231 deg") !=
                       nullptr &&
                   std::strstr(text, "7 views)") != nullptr,
               "the line's ripple state");
        RippleOnceText(ParseRipple("0", nullptr), 1.0f, text, sizeof(text));
        Expect(std::strncmp(text, "Wind sway ripple (r89b): off", 28) == 0, "the once line, off");
        RippleOnceText(ParseRipple("4", "1"), MaxScale, text, sizeof(text));
        const char* on_text = "Wind sway ripple (r89b, BB_WIND_SWAY_RIPPLE=4.00, SHOW";
        Expect(std::strncmp(text, on_text, std::strlen(on_text)) == 0 && std::strlen(text) < 300,
               "the once line, on, under 300 characters");
    }

'''

SPIRV_RIPPLE = r'''    const Id ddx_one =
        ctx.OpSelect(f32_type, fin, mul(w, sub(mul(dx, along), mul(dz, cross))), zero);
    const Id ddz_one =
        ctx.OpSelect(f32_type, fin, mul(w, add(mul(dz, along), mul(dx, cross))), zero);
    // bbport (r89b_wind-sway-ripple): the ripple (bbport_wind_sway.h: BbWindSway::RippleOr and
    // Envelope are this code in C++, operation for operation). Its flag word (RippleD's w) 0, as
    // FillView leaves it with BB_WIND_SWAY_RIPPLE=0, selects the two lines above (r89's motion).
    // With the ripple FillRipple has written r89's swing phases and gust table, so a1, a2 and g
    // above serve both.
    const Id rip_a = row(W::RippleA);
    const Id rip_b = row(W::RippleB);
    const Id rip_c = row(W::RippleC);
    const Id rip_d = row(W::RippleD);
    const Id ry = ctx.OpDot(f32_type, row(W::ToWorldAt + 4), position);
    const Id se = mul(s, comp(rip_b, 3u));
    const Id qe = mul(q, comp(rip_b, 3u));
    const auto front = [&](Id phase, float ka, float kb) {
        return ctx.OpSin(f32_type, wrap(add(add(phase, mul(f(ka), se)), mul(f(kb), qe))));
    };
    const Id n = mul(add(add(front(comp(rip_a, 2u), W::Env1S, W::Env1Q),
                             front(comp(rip_a, 3u), W::Env2S, W::Env2Q)),
                         front(comp(rip_b, 0u), W::Env3S, W::Env3Q)),
                     f(1.0f / 3.0f));
    const Id tt = ctx.OpFClamp(f32_type, mul(sub(n, f(W::EnvLo)), f(W::EnvInv)), zero, f(1.0f));
    const Id env = mul(mul(mul(tt, tt), sub(f(3.0f), mul(f(2.0f), tt))), f(W::EnvScale));
    const auto leaf_wave = [&](Id phase, float kx, float ky, float kz) {
        return ctx.OpSin(
            f32_type, wrap(add(add(add(phase, mul(f(kx), rx)), mul(f(ky), ry)), mul(f(kz), rz))));
    };
    const Id b1 = leaf_wave(comp(rip_b, 1u), W::Leaf1X, W::Leaf1Y, W::Leaf1Z);
    const Id b2 = leaf_wave(comp(rip_b, 2u), W::Leaf2X, W::Leaf2Y, W::Leaf2Z);
    const Id r_along = ctx.OpFClamp(
        f32_type,
        mul(g, add(add(comp(rip_c, 0u), mul(comp(rip_d, 0u), sub(env, f(1.0f)))),
                   mul(mul(comp(rip_c, 1u), env), ctx.OpSin(f32_type, a1)))),
        ctx.OpFNegate(f32_type, max_along), max_along);
    const Id r_cross =
        ctx.OpFClamp(f32_type, mul(g, mul(mul(comp(rip_c, 2u), env), ctx.OpSin(f32_type, a2))),
                     ctx.OpFNegate(f32_type, max_cross), max_cross);
    const Id leaf =
        mul(g, mul(comp(rip_c, 3u), add(f(W::LeafCalm), mul(f(1.0f - W::LeafCalm), env))));
    const Id la = ctx.OpFClamp(f32_type, mul(leaf, b1), f(-W::MaxLeaf), f(W::MaxLeaf));
    const Id lc = ctx.OpFClamp(f32_type, mul(leaf, b2), f(-W::MaxLeaf), f(W::MaxLeaf));
    const Id wf = mul(w, t);
    const Id ddx_rip = ctx.OpSelect(f32_type, fin,
                                    add(mul(w, sub(mul(dx, r_along), mul(dz, r_cross))),
                                        mul(wf, sub(mul(dx, la), mul(dz, lc)))),
                                    zero);
    const Id ddz_rip = ctx.OpSelect(f32_type, fin,
                                    add(mul(w, add(mul(dz, r_along), mul(dx, r_cross))),
                                        mul(wf, add(mul(dz, la), mul(dx, lc)))),
                                    zero);
    const Id rippled = ctx.OpFOrdLessThan(bool_type, zero, comp(rip_d, 3u));
    const Id ddx = ctx.OpSelect(f32_type, rippled, ddx_rip, ddx_one);
    const Id ddz = ctx.OpSelect(f32_type, rippled, ddz_rip, ddz_one);
'''

LIFT_RIPPLE = r'''    const u32 ddx_one = Select(fin, FMul(w, FSub(FMul(dx, along), FMul(dz, cross))), zero);
    const u32 ddz_one = Select(fin, FMul(w, FAdd(FMul(dz, along), FMul(dx, cross))), zero);
    // bbport (r89b_wind-sway-ripple): the ripple, as the recompiler's EmitVertexSway (and
    // BbWindSway::RippleOr in C++); its flag word 0 (BB_WIND_SWAY_RIPPLE=0) selects the two above.
    // a1, a2 and g above serve both (FillRipple wrote r89's swing phases and gust table).
    const u32 rip_a = row(W::RippleA);
    const u32 rip_b = row(W::RippleB);
    const u32 rip_c = row(W::RippleC);
    const u32 rip_d = row(W::RippleD);
    const u32 ry = dot(row(W::ToWorldAt + 4), position);
    const u32 se = FMul(s, comp(rip_b, 3));
    const u32 qe = FMul(q, comp(rip_b, 3));
    const auto front = [&](u32 phase, float ka, float kb) { return sin_f(wrap(FAdd(FAdd(phase, FMul(CF(ka), se)), FMul(CF(kb), qe)))); };
    const u32 n = FMul(FAdd(FAdd(front(comp(rip_a, 2), W::Env1S, W::Env1Q), front(comp(rip_a, 3), W::Env2S, W::Env2Q)),
                            front(comp(rip_b, 0), W::Env3S, W::Env3Q)), CF(1.0f / 3.0f));
    const u32 tt = clamp_f(FMul(FSub(n, CF(W::EnvLo)), CF(W::EnvInv)), zero, CF(1.0f));
    const u32 env = FMul(FMul(FMul(tt, tt), FSub(CF(3.0f), FMul(CF(2.0f), tt))), CF(W::EnvScale));
    const auto leaf_wave = [&](u32 phase, float kx, float ky, float kz) {
        return sin_f(wrap(FAdd(FAdd(FAdd(phase, FMul(CF(kx), rx)), FMul(CF(ky), ry)), FMul(CF(kz), rz))));
    };
    const u32 b1 = leaf_wave(comp(rip_b, 1), W::Leaf1X, W::Leaf1Y, W::Leaf1Z);
    const u32 b2 = leaf_wave(comp(rip_b, 2), W::Leaf2X, W::Leaf2Y, W::Leaf2Z);
    const u32 r_along = clamp_f(FMul(g, FAdd(FAdd(comp(rip_c, 0), FMul(comp(rip_d, 0), FSub(env, CF(1.0f)))), FMul(FMul(comp(rip_c, 1), env), sin_f(a1)))),
                                FNeg(max_along), max_along);
    const u32 r_cross = clamp_f(FMul(g, FMul(FMul(comp(rip_c, 2), env), sin_f(a2))), FNeg(max_cross), max_cross);
    const u32 leaf = FMul(g, FMul(comp(rip_c, 3), FAdd(CF(W::LeafCalm), FMul(CF(1.0f - W::LeafCalm), env))));
    const u32 la = clamp_f(FMul(leaf, b1), CF(-W::MaxLeaf), CF(W::MaxLeaf));
    const u32 lc = clamp_f(FMul(leaf, b2), CF(-W::MaxLeaf), CF(W::MaxLeaf));
    const u32 wf = FMul(w, t);
    const u32 ddx_rip = Select(fin, FAdd(FMul(w, FSub(FMul(dx, r_along), FMul(dz, r_cross))), FMul(wf, FSub(FMul(dx, la), FMul(dz, lc)))), zero);
    const u32 ddz_rip = Select(fin, FAdd(FMul(w, FAdd(FMul(dz, r_along), FMul(dx, r_cross))), FMul(wf, FAdd(FMul(dz, la), FMul(dx, lc)))), zero);
    const u32 rippled = FCmp(O(spv::Op::OpFOrdLessThan), zero, comp(rip_d, 3));
    const u32 ddx = Select(rippled, ddx_rip, ddx_one);
    const u32 ddz = Select(rippled, ddz_rip, ddz_one);
'''

README_ROWS = (
    "| `BB_WIND_SWAY_RIPPLE` | How the plant sway (`BB_WIND_SWAY`) moves. `0` is the motion the "
    "`BB_WIND_SWAY` row describes (each plant bends as one piece, in a wave about 2 m long at "
    "1.5 m/s). Unset or `1` (the default): the ripple; a number is its strength, held to 0.25 to 4 "
    "(0 or less is `0`; text that is not a number or not finite is `1`). The ripple: gust fronts "
    "(three waves 9, 13 and 17 m long, along the wind and 35 and -50 degrees off it, carried by the "
    "wind at its speed times its gust factor) pass through the plants downwind, so up-wind plants "
    "move first; their envelope E (0 in a calm, up to 2 in a front, mean 1) multiplies the swing "
    "(0.06 m along at 0.7 Hz and 0.025 m across at 1.3 Hz, times the strength) and moves the lean "
    "(0.06 m) by 0.03 m x strength x (E - 1). The leaves flutter by 0.012 m x strength x (0.5 + 0.5 "
    "E) along and across the wind at 1.9 and 2.7 Hz, in two waves 0.9 m and 0.65 m long fixed in "
    "the world (so leaves a few cm apart and up a stem are out of step), held to 0.08 m. All of it "
    "is times the scale, min(speed, 2.5) / 1.5 m/s and the gust factor at the plant (as with `0`: "
    "the gust that passed the camera, carried downwind at the wind's speed, so a gust reaches the "
    "plants one after another); the swing and lean are held to 0.4 m and 0.15 m and weighted "
    "by smoothstep(0, 0.75 m, h) and the ramp as with `0`, the flutter by that times min(h / 0.75 m, "
    "1), so the roots stay. Each term depends only on the vertex's world position and the time, so "
    "shared vertices move together; the phases and the gust's time are kept on the CPU so that a "
    "turning wind turns the waves about the camera without a jump. The motion vectors and the ray "
    "traced scene take the "
    "moved positions, as with `0`. The once line `Wind sway ripple (r89b...)` says which runs, and "
    "the `Wind sway (r89)` line every 600 frames starts with the ripple's state (strength, the "
    "fronts' spacing in m, their speed in m/s, the direction in degrees, the swing's wavelength, the "
    "views that got the ripple) or `ripple off`. Cost: none with the sway off; with it on about 110 "
    "more operations, 5 sines and 5 loads per plant vertex; not measured. A leaf tip moves up to "
    "about twice as far a frame as with `0` in a gust front (CPU estimate), which the motion "
    "vectors carry; `0.5` brings it back near `0` | `1` |\n"
    "| `BB_WIND_SWAY_SHOW` | Test view: `1` brings the gust fronts 2.5 times closer (3.6 m) and "
    "makes the travelling part and the flutter 2.5 times stronger (the limits stay), so a short "
    "clip shows the waves travel; no effect with `BB_WIND_SWAY_RIPPLE=0` | unset |\n")

EDITS = {
    HEADER: [
        ("#include <cstdint>\n#include <cstdlib>\n",
         "#include <cstdint>\n#include <cstdio> // bbport (r89b_wind-sway-ripple): the ripple's log texts\n"
         "#include <cstdlib>\n"),
        ("// k2), WindE (MaxAlong, MaxCross, camera x and z, unread), the gust table at TableAt), then\n",
         "// k2), WindE (MaxAlong, MaxCross, camera x and z, unread), the gust table at TableAt, the\n"
         "// ripple's words at RippleAt: bbport r89b_wind-sway-ripple, FillRipple), then\n"),
        ("inline constexpr float InvTwoPi = 0.15915494309189533577f;\n",
         "inline constexpr float InvTwoPi = 0.15915494309189533577f;\n" + H_CONSTANTS),
        ("inline constexpr std::uint32_t ViewWords = TableAt + GustSamples;\n",
         "/// bbport (r89b_wind-sway-ripple): the ripple's RippleWords words (rows RippleA-RippleD) after\n"
         "/// the gust table; FillRipple writes them, FillView leaves them 0 (r89's motion)\n"
         "inline constexpr std::uint32_t RippleAt = TableAt + GustSamples, RippleWords = 16;\n"
         "inline constexpr std::uint32_t RippleA = RippleAt, RippleB = RippleAt + 4, RippleC = RippleAt + 8,\n"
         "                               RippleD = RippleAt + 12;\n"
         "inline constexpr std::uint32_t ViewWords = RippleAt + RippleWords;\n"),
        ("static_assert(ViewWords == 112 && ViewWords % 4 == 0 && TableAt % 4 == 0 && WindE % 4 == 0);\n"
         "static_assert(BaseAt % 4 == 0 && RegionBytes == 7680);\n",
         "// bbport (r89b_wind-sway-ripple): 128 words a view (r89: 112) and 8192 bytes (r89: 7680)\n"
         "static_assert(ViewWords == 128 && ViewWords % 4 == 0 && TableAt % 4 == 0 && WindE % 4 == 0 &&\n"
         "              RippleAt % 4 == 0);\n"
         "static_assert(BaseAt % 4 == 0 && RegionBytes == 8192);\n"),
        ("/// What the shaders do to one vertex: `view` its ViewWords floats, `clip` the clip position,\n",
         H_FUNCTIONS +
         "/// What the shaders do to one vertex: `view` its ViewWords floats, `clip` the clip position,\n"),
        ("    const float ddx = w * (dx * along - dz * cross);\n"
         "    const float ddz = w * (dz * along + dx * cross);\n",
         "    // bbport (r89b_wind-sway-ripple): the ripple's displacement where its flag word is above 0;\n"
         "    // with it 0 (BB_WIND_SWAY_RIPPLE=0: FillView alone) these two of r89's, unchanged\n"
         "    const std::array<float, 2> moved = RippleOr(view, clip, rx, rz, s, q, t, w, g, a1, a2,\n"
         "                                                w * (dx * along - dz * cross),\n"
         "                                                w * (dz * along + dx * cross));\n"
         "    const float ddx = moved[0], ddz = moved[1];\n"),
        ("    std::uint64_t no_rt = 0, no_camera = 0, views_full = 0, no_slot = 0, no_region = 0;\n",
         "    std::uint64_t no_rt = 0, no_camera = 0, views_full = 0, no_slot = 0, no_region = 0;\n"
         "    std::uint64_t rippled_views = 0; ///< bbport (r89b_wind-sway-ripple): views given the ripple\n"),
    ],
    S + "backend/spirv/emit_spirv_special.cpp": [
        ("    const Id ddx = ctx.OpSelect(f32_type, fin, mul(w, sub(mul(dx, along), mul(dz, cross))), zero);\n"
         "    const Id ddz = ctx.OpSelect(f32_type, fin, mul(w, add(mul(dz, along), mul(dx, cross))), zero);\n",
         SPIRV_RIPPLE),
    ],
    L + "lift_stage.cpp": [
        ("    const u32 ddx = Select(fin, FMul(w, FSub(FMul(dx, along), FMul(dz, cross))), zero);\n"
         "    const u32 ddz = Select(fin, FMul(w, FAdd(FMul(dz, along), FMul(dx, cross))), zero);\n",
         LIFT_RIPPLE),
    ],
    R + "vk_rasterizer.h": [
        ("    BbWindSway::Stats sway_stats;\n",
         "    BbWindSway::Stats sway_stats;\n"
         "    /// bbport (r89b_wind-sway-ripple): the ripple's wave phases (BB_WIND_SWAY_RIPPLE above 0)\n"
         "    BbWindSway::Ripple sway_ripple;\n"),
    ],
    R + "vk_rasterizer_effects.cpp": [
        ("        BbWindSway::FillView(camera, snapshot, knob.gusts, knob.scale, filled.data());\n",
         "        BbWindSway::FillView(camera, snapshot, knob.gusts, knob.scale, filled.data());\n"
         "        // bbport (r89b_wind-sway-ripple): the ripple's words (left 0 with BB_WIND_SWAY_RIPPLE=0)\n"
         "        if (BbWindSway::FillRipple(sway_ripple, camera, snapshot, knob.gusts, knob.scale,\n"
         "                                   BbWindSway::RippleKnobOnce(), filled.data())) {\n"
         "            ++sway_stats.rippled_views;\n"
         "        }\n"),
        ("                double(BbWindSway::CrossHz));\n"
         "        } else if (knob.wind) {\n",
         "                double(BbWindSway::CrossHz));\n"
         "            char ripple[512]; // bbport (r89b_wind-sway-ripple): which motion runs\n"
         "            BbWindSway::RippleOnceText(BbWindSway::RippleKnobOnce(), knob.scale, ripple,\n"
         "                                       sizeof(ripple));\n"
         "            BbReport::Printf(\"%s\\n\", ripple);\n"
         "        } else if (knob.wind) {\n"),
        ("    const BbWindSway::Stats& s = sway_stats;\n"
         "    BbReport::Printf(\"Wind sway (r89): in %u frames %llu draws of sway pipelines with a skeleton, \"\n",
         "    const BbWindSway::Stats& s = sway_stats;\n"
         "    char ripple[256]; // bbport (r89b_wind-sway-ripple): the ripple's state, first in the line\n"
         "    BbWindSway::RippleText(BbWindSway::RippleKnobOnce(), wind.Get(), s.rippled_views, ripple,\n"
         "                           sizeof(ripple));\n"
         "    BbReport::Printf(\"Wind sway (r89): %s; in %u frames %llu draws of sway pipelines with a \"\n"
         "                     \"skeleton, \"\n"),
        ("                     BbWindSway::ReportFrames, n(s.draws), n(s.plants), n(s.swayed), n(s.ramping),\n",
         "                     ripple, BbWindSway::ReportFrames, n(s.draws), n(s.plants), n(s.swayed),\n"
         "                     n(s.ramping),\n"),
    ],
    R + "vk_pipeline_serialization.cpp": [
        ("static constexpr u32 PipelineKeyVersion = 6u; // pointer-free pipeline state + generated fragment\n",
         "static constexpr u32 PipelineKeyVersion = 6u; // pointer-free pipeline state + generated fragment\n"
         "// bbport (r89b_wind-sway-ripple): a vertex shader with the plant sway (MotionVectors::Sway): its\n"
         "// code changed with the ripple, so a sway shader saved by a build before it is built again\n"
         "static constexpr u32 SwayShaderBinaryVersion = 10u;\n"),
        ("std::vector<u8> SerializeShaderMeta(const Shader::Info& info, const Shader::StageSpecialization& spec,\n",
         "// bbport (r89b_wind-sway-ripple): the binary version of a stage: SwayShaderBinaryVersion for a\n"
         "// vertex shader with MotionVectors::Sway, `version` (as before) for every other\n"
         "static u32 SwayOr(u32 version, bool vertex_motion, const Shader::StageSpecialization& spec) {\n"
         "    return vertex_motion &&\n"
         "                   (spec.runtime_info.hw.vs.motion_vectors & Shader::MotionVectors::Sway) != 0\n"
         "               ? Serialization::SwayShaderBinaryVersion\n"
         "               : version;\n"
         "}\n"
         "\n"
         "std::vector<u8> SerializeShaderMeta(const Shader::Info& info, const Shader::StageSpecialization& spec,\n"),
        ("    meta.Write(vertex_capture ? Serialization::CaptureShaderBinaryVersion\n"
         "                             : vertex_motion ? Serialization::MotionShaderBinaryVersion\n"
         "                             : Serialization::ShaderBinaryVersion);\n"
         "    meta.Write(perm_hash);\n",
         "    meta.Write(SwayOr(vertex_capture ? Serialization::CaptureShaderBinaryVersion\n"
         "                             : vertex_motion ? Serialization::MotionShaderBinaryVersion\n"
         "                             : Serialization::ShaderBinaryVersion,\n"
         "                      vertex_motion, spec)); // bbport (r89b_wind-sway-ripple)\n"
         "    meta.Write(perm_hash);\n"),
        ("    meta.Write(vertex_capture ? Serialization::CaptureShaderBinaryVersion\n"
         "                             : vertex_motion ? Serialization::MotionShaderBinaryVersion\n"
         "                             : Serialization::ShaderBinaryVersion);\n"
         "\n"
         "    meta.Write(perm_hash);\n",
         "    meta.Write(SwayOr(vertex_capture ? Serialization::CaptureShaderBinaryVersion\n"
         "                             : vertex_motion ? Serialization::MotionShaderBinaryVersion\n"
         "                             : Serialization::ShaderBinaryVersion,\n"
         "                      vertex_motion, spec)); // bbport (r89b_wind-sway-ripple)\n"
         "\n"
         "    meta.Write(perm_hash);\n"),
        ("        binary_version != Serialization::CaptureShaderBinaryVersion) {\n",
         "        binary_version != Serialization::CaptureShaderBinaryVersion &&\n"
         "        binary_version != Serialization::SwayShaderBinaryVersion) { // bbport (r89b)\n"),
        ("    if (binary_version != (vertex_capture ? Serialization::CaptureShaderBinaryVersion\n"
         "                             : vertex_motion ? Serialization::MotionShaderBinaryVersion\n"
         "                                        : Serialization::ShaderBinaryVersion)) {\n",
         "    if (binary_version != SwayOr(vertex_capture ? Serialization::CaptureShaderBinaryVersion\n"
         "                             : vertex_motion ? Serialization::MotionShaderBinaryVersion\n"
         "                                        : Serialization::ShaderBinaryVersion,\n"
         "                                 vertex_motion, spec)) { // bbport (r89b_wind-sway-ripple)\n"),
    ],
    TEST: [
        ("        Expect(TableAt + GustSamples == ViewWords && ToWorldAt == ForwardAt + 16 &&\n",
         "        Expect(TableAt + GustSamples == RippleAt && RippleAt + RippleWords == ViewWords && // r89b\n"
         "                   ToWorldAt == ForwardAt + 16 &&\n"),
        ("double Horizontal(const std::array<double, 3>& a, const std::array<double, 3>& b) {\n"
         "    return std::hypot(a[0] - b[0], a[2] - b[2]);\n"
         "}\n",
         "double Horizontal(const std::array<double, 3>& a, const std::array<double, 3>& b) {\n"
         "    return std::hypot(a[0] - b[0], a[2] - b[2]);\n"
         "}\n" + R89_DISPLACE),
        ("    if (failures == 0) {\n        std::printf(\"wind-sway-test: ok\\n\");\n",
         RIPPLE_TESTS + "    if (failures == 0) {\n        std::printf(\"wind-sway-test: ok\\n\");\n"),
    ],
    "README.md": [
        ("lookups per plant draw; an estimate under 0.05 ms, not measured | `1` |\n",
         "lookups per plant draw; an estimate under 0.05 ms, not measured | `1` |\n" + README_ROWS),
    ],
}

CHECKS = {
    HEADER: [("inline constexpr std::uint32_t ViewWords = RippleAt + RippleWords;", 1),
             ("class Ripple {", 1), ("inline bool FillRipple(", 1), ("RippleOr(view, clip,", 1),
             ("RippleOr(view, clip, rx, rz, s, q, t, w, g, a1, a2,", 1), ("view[TableAt + i] = BbWind::Gust(t, gusts);", 1),
             ("view[WindB + 3] = out[0];", 1), ("amp * gust;", 0),
             ("static_assert(ViewWords == 112", 0), ("RegionBytes == 8192", 1), ("rippled_views", 1)],
    S + "backend/spirv/emit_spirv_special.cpp": [("ddx_one", 2), ("ddz_one", 2), ("W::RippleD", 1), ("r_a1", 0),
                                                 ("ctx.OpSin(f32_type, a1)", 2), ("ctx.OpSin(f32_type, a2)", 2),
                                                 ("EmitVertexSway(ctx);", 1)],
    L + "lift_stage.cpp": [("ddx_one", 2), ("ddz_one", 2), ("W::RippleD", 1), ("VertexSway();", 1), ("r_a1", 0),
                           ("sin_f(a1)", 2), ("sin_f(a2)", 2)],
    R + "vk_rasterizer.h": [("BbWindSway::Ripple sway_ripple;", 1)],
    R + "vk_rasterizer_effects.cpp": [("FillRipple(sway_ripple, camera, snapshot, knob.gusts, knob.scale,", 1), ("RippleOnceText(", 1),
                                      ("RippleText(", 1), ("\"Wind sway (r89): %s; in %u frames", 1)],
    R + "vk_pipeline_serialization.cpp": [("SwayOr(", 4), ("SwayShaderBinaryVersion", 4)],
    TEST: [("R89Displace(", 2), ("RippleViewOf(", 12), ("the ripple's gust table moves with the wind time", 1), ("wind-sway-test: ok", 1)],
    "README.md": [("| `BB_WIND_SWAY_RIPPLE` |", 1), ("| `BB_WIND_SWAY_SHOW` |", 1), ("| `BB_WIND_SWAY` |", 1)],
}

ORDER = {
    HEADER: ["RippleAt = TableAt", "ViewWords = RippleAt + RippleWords", "inline constexpr float InvTwoPi",
             "RippleDefault = 1.0f", "inline float Wrap(float a)", "struct RippleKnob",
             "class Ripple {", "inline bool FillRipple(", "inline float Envelope(", "RippleOr(const float* view",
             "inline std::array<float, 4> Displace(", "RippleOr(view, clip,", "class Slots {"],
    S + "backend/spirv/emit_spirv_special.cpp": ["static void EmitVertexSway(", "const Id ddx_one", "const Id ddx =",
                                                 "std::array<Id, 4>{ddx, zero, ddz, zero}", "void EmitEpilogue("],
    L + "lift_stage.cpp": ["void Lift_::VertexSway() {", "const u32 ddx_one", "const u32 ddx =",
                           "ComponentsF({ddx, zero, ddz, zero})", "void Lift_::VertexMotion() {"],
    R + "vk_rasterizer_effects.cpp": ["u32 Rasterizer::WindSwayWord(", "FillRipple(sway_ripple,",
                                      "void Rasterizer::WindSwayFrameEnd()", "RippleOnceText(", "RippleText(",
                                      "sway_stats = {};"],
    R + "vk_pipeline_serialization.cpp": ["SwayShaderBinaryVersion = 10u", "static u32 SwayOr(",
                                          "std::vector<u8> SerializeShaderMeta(", "void RegisterShaderMeta(",
                                          "bool LoadShaderMeta("],
    TEST: ["double Horizontal(", "std::array<float, 4> R89Displace(", "} // namespace", "int main() {",
           "the ripple's knob", "wind-sway-test: ok"],
    "README.md": ["| `BB_WIND_SWAY` |", "| `BB_WIND_SWAY_RIPPLE` |", "| `BB_WIND_SWAY_SHOW` |", "| `BB_WIND_FOG` |"],
}

# Numbers written twice (rule 10): the header's constant and the README rows' text.
TIES = [("RippleDefault = 1.0f, RippleMin = 0.25f, RippleMax = 4.0f", "held to 0.25 to 4"),
        ("EnvWavelength[3] = {9.0f, 13.0f, 17.0f}, EnvAngle[3] = {0.0f, 35.0f, -50.0f}",
         "three waves 9, 13 and 17 m long, along the wind and 35 and -50 degrees off it"),
        ("EnvLo = -0.5f, EnvInv = 1.0f, EnvScale = 2.0f", "(0 in a calm, up to 2 in a front, mean 1)"),
        ("LeanGust = 0.03f", "by 0.03 m x strength x (E - 1)"),
        ("Leaf = 0.012f", "flutter by 0.012 m x strength x (0.5 + 0.5 "),
        ("LeafCalm = 0.5f", "x (0.5 + 0.5 E)"), ("MaxLeaf = 0.08f", "held to 0.08 m"),
        ("LeafHz1 = 1.9f, LeafHz2 = 2.7f", "at 1.9 and 2.7 Hz"),
        ("LeafWavelength[2] = {0.9f, 0.65f}", "two waves 0.9 m and 0.65 m long"),
        ("ShowGain = 2.5f, ShowWave = 2.5f", "2.5 times closer (3.6 m) and makes the travelling part and the flutter 2.5 times"),
        ("Lean = 0.06f", "moves the lean (0.06 m)"), ("Flutter = 0.06f", "(0.06 m along at 0.7 Hz"),
        ("Cross = 0.025f", "0.025 m across at 1.3 Hz"), ("MaxAlong = 0.4f, MaxCross = 0.15f", "held to 0.4 m and 0.15 m"),
        ("Height = 0.75f", "min(h / 0.75 m, 1)"), ("SpeedCap = 2.5f", "min(speed, 2.5) / 1.5 m/s")]


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
    rows = [l for l in texts["README.md"].split("\n") if l.startswith("| `BB_WIND_SWAY_")]
    both = "\n".join(rows)
    for const, value in TIES:
        if texts[HEADER].count(const) != 1 or value not in both:
            raise SystemExit("tie check: %r against the README rows (%r)" % (const, value))
    added = [new for edits in EDITS.values() for old, new in edits]
    for text in added:
        if not all(ord(c) < 128 for c in text) or "\r" in text:
            raise SystemExit("new text must be ASCII with LF in the script")
        if any(x in text for x in ("C:/", "G:/", "<user>", "Temp/claude")):
            raise SystemExit("a local path in the patch's text")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R89B_ROOT)" % ROOT)
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
            tmp = full + ".r89btmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, edits, raw, eol, cur, _ in plan:
        for old, new in reversed(edits):
            cur = cur.replace(new, old)
        for old, new in edits:
            if cur.count(old) != 1 or cur.count(new) != 0:
                raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, edits, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r89btmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
