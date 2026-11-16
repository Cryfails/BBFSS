# r91_lamp-radius-per-lamp: FEATURE patch (lamp work; the owner's layered-shadow photo, proposal R1
# of the layered shadows study, approved 2026-11-15 20:08 "I would do all of those").
#
# What: each ray traced lamp gets a disc of its own size, so a lamp of long reach (a big street or
# church lamp) throws wide soft penumbrae and a lamp of short reach (a candle) keeps tight ones.
# Off by default behind BB_LAMP_SHADOW_RADIUS_PER_LAMP = k (per metre of reach, 0 to 1; 0 or not
# set: off, one radius for every lamp as before). Read once at start (ReadLampShadowTune).
#
# The rule (lamp_shadow_tune.h LampDiscRadius):
#   radius = clamp(k x reach, 0.03 m, 0.3 m) x (softness radius / 0.1 m), at most 0.5 m
#   reach = 1 / sqrt(record word 3). The softness setting stays the base: soft (0.1 m) gives the
#   clamp as written, softer (0.2 m) twice it, BB_LAMP_SHADOW_SOFT scales it the same way, and sharp
#   (0) has no disc (point lamps, exact path, no history): there the knob changes nothing.
#   Reach, not luminance: reach is the only size-like number a record holds and it is steady (the
#   hand torch 8.4-8.5 m between log lines), while the luminance of the same torch read 1.04 and
#   1.91 in two lines and its units are not known. So the torch (8.5 m) gets a WIDER disc than the
#   hand lantern (5.2 m) and the wall lamps (6.0 m): reach cannot tell a bright small flame from a
#   big dim fitting. k 0.02: 5 m -> 0.10 m (the soft radius), 8.5 m -> 0.17 m, 12 m -> 0.24 m,
#   1.5 m or less -> 0.03 m; k 0.0125 keeps the torch at about the soft radius.
#   Its rays' blind distance: LampPassClearance at the lamp's radius = max(BB_LAMP_SHADOW_CLEARANCE,
#   radius + 0.05 m) (r90's rule, per lamp; a small lamp in the softer setting gets 0.18 m, not
#   the pass's 0.25 m).
#   Steady for a flickering flame (reviewed fix: the draft held a disc only while the new value was
#   within 10 %, so a flame whose reach flickers more, 5 m and 6.6 m in turn as the tree's own
#   LampTrack test has it, got a new disc every frame): a lamp LampTrack follows moves its disc 1/16
#   of the way to the value of its reach each frame (LampDiscKeep, LampTrack::Disc, worked out once
#   a frame for all its records), so a flickering reach gives a steady disc near its mean (5 / 6.6 m:
#   0.116 m +- 0.5 mm at k 0.02); a value 1.6 times larger or smaller (another softness, another
#   lamp in its place) is taken at once and counted. A lamp not followed (beyond the 64 told apart,
#   or a frame with no history to read) takes the value of its reach, rounded to 1 mm in the word.
#
# How:
#  1. lamp_shadow_tune.h: LampShadowTune::disc_each (the knob), read in ReadLampShadowTune;
#     LampTuneDiscEach = tune word 0 bit 24 (static_assert: free); LampDiscRadius, LampDiscKeep,
#     LampDiscWord (word 10 = radius in mm, low 16 bits | blind distance in mm rounded up, high 16
#     bits); LampSeen::disc and disc_moves, carried by Follow, disc_moves cleared by ClearSteps;
#     LampTrack::Disc. LampTuneWords is NOT changed: it never sets bit 24.
#  2. vk_point_shadow.cpp: TrackLamps writes word 10 of every record of the pass that averages, in
#     the loop that writes words 12-15 (only with the knob on; the pass's own copy of the records,
#     `data`); Flush sets bit 24 in that pass's tune word 0 right after that TrackLamps call (never
#     in another pass, whose word 10 is the game's); a once-line at start; each near lamp in the
#     periodic "Ray traced lamps (r42): ... lamp records in the pass" line shows its disc and how
#     often it changed since the line before.
#  3. point_shadow_ray.comp (the existing builds, no new build): bit 24 -> t_disc_each. lampVisibility
#     takes the radius and the blind distance from word 10 of the traced lamp's record when the bit
#     is set and the pass has a disc (t_radius > 0); ray() uses that blind distance (ray_clear, 0:
#     t_clear as before). The record: the exact path's loop sets lamp_rec; the pick path keeps
#     pick_top / pick_cand / pick_rest beside top_l / cand_l / rest_l (only with the bit), and
#     lampRecord takes pick_top for the first lampVisibility call of the pick path (the strongest
#     lamp, traced first) and pick_rest for the second (pick_calls). (Reviewed fix: the draft told
#     them apart by place, so a second light at the strongest one's place, a torch made of two lights
#     with different reach, was traced with the strongest one's disc: a biased pick.)
#  4. tests/test_lamp_shadow_tune.cpp: the knob, the rule, the word, the hold, the bit not in
#     LampTuneWords. README.md: a row after BB_LAMP_SHADOW_SOFT.
#
# Off (knob 0 or not set): bit 24 is never set (LampTuneWords does not set it; Flush sets it only
# with disc_each > 0), so t_disc_each stays false: lampVisibility's radius is t_radius, ray_clear is
# never written and stays 0, so ray() uses t_clear: the same numbers as before. Word 10 is not
# written. The SPIR-V of the existing builds changes (the code is there, behind the bit).
# History: history_radius_m still keys the pass's history on the base radius (the menu change
# still restarts it). A lamp whose disc changes (a jump, a new lamp) does not restart
# the history; its penumbra settles over the history's frames like any change of light. The knob
# is read at start only, so no history mixes "off" and "on".
#
# Distinct resources (three patches drafted together; apply order r91, r93, r92): tune word 0 bit
# 24 (verified free: bits 0, 1, 8-10, 12-17, 20-22 are taken); record word 10 (word 11 is left to
# r69). Anchors are single lines kept intact (new lines go before or after them), so later patches
# that anchor on the same lines still find them, except where two patches add lines on the same
# side of the same anchor. Lines of point_shadow_ray.comp that r92 (coloured visibility) may anchor
# on and next to which this patch adds a line: "if (w > view_top) {" (a guarded block before it),
# "rest_l = cand_l;" (a line after it), the exact loop's "const uint at = lights_at + k * 16u;"
# (a line after it). No line of lampWeight, the vsum/wsum sums, the lampVisibility calls or the
# output write is changed.
#
# Use: python -I -X utf8 r91_lamp-radius-per-lamp.py check | apply | revert
# (root from R91_ROOT, else <tree>). Line ends kept (CRLF in the tree). Originals of the
# files touched are kept in r91_backup/ next to this script; revert undoes the edits one by one
# (new text back to old), so it works with patches applied after this one that left these lines
# alone. No new files.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r91_backup")
ROOT = os.environ.get("R91_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"
TAG = "bbport (r91_lamp-radius-per-lamp)"

def after(anchor, added):
    return (anchor, anchor + "\n" + added)

def before(anchor, added):
    return (anchor, added + "\n" + anchor)

EDITS = {
 R + "lamp_shadow_tune.h": [
  after("                                 ///< (LampSoftnessRadius)",
r'''    float disc_each = 0.0f;      ///< bbport (r91_lamp-radius-per-lamp): BB_LAMP_SHADOW_RADIUS_PER_LAMP,
                                 ///< 0..1 per metre of reach: each lamp's own disc (LampDiscRadius) in
                                 ///< the pass that averages; 0: off, radius_m for every lamp'''),
  after("    tune.radius_m = tune.radius_set ? soft : tune.radius_m;",
r'''    // bbport (r91_lamp-radius-per-lamp): 0 or below, or not a number: off
    tune.disc_each = Number(get, "BB_LAMP_SHADOW_RADIUS_PER_LAMP", tune.disc_each, 0.0f, 1.0f);'''),
  after("    return std::max(tune.clearance_m, tune.radius_m + LampClearanceOverRadius);\n}",
r'''
/// bbport (r91_lamp-radius-per-lamp): BB_LAMP_SHADOW_RADIUS_PER_LAMP (disc_each = k, per metre of
/// reach; 0: off). In the pass that averages (the one whose TrackLamps writes the records' word 10,
/// vk_point_shadow.cpp), each lamp's disc has its own radius in place of radius_m:
///   clamp(k x reach, LampDiscLeast, LampDiscMost) x (radius_m / 0.1 m), at most LampDiscCap,
/// reach = 1 / sqrt(word 3). So the softness setting stays the base: soft (0.1 m) gives the clamp as
/// written, softer (0.2 m) twice it, BB_LAMP_SHADOW_SOFT scales it alike, and sharp (0) has no disc
/// (point lamps without a history, every lamp traced: the knob changes nothing there). From the
/// reach, not the luminance: the reach is the one size-like number of a record and steady; the
/// luminance of a flame swings and its units are not known. k 0.02: 5 m of reach keeps 0.1 m,
/// 12 m gets 0.24 m, 15 m or more 0.3 m, 1.5 m or less 0.03 m. The pass reads the disc only with
/// tune word 0 bit 24 (LampTuneDiscEach), which LampTuneWords never sets: Flush sets it after
/// TrackLamps wrote word 10.
inline constexpr std::uint32_t LampTuneDiscEach = 1u << 24;
// (Bit 24 is free: none of bits 0, 1, the view's 8-10, the card cap's 12-17, 20, 21 or 22.)
static_assert((LampTuneDiscEach & (LampTuneNewWeights | LampTuneInverseSquare | (7u << LampTuneViewShift) |
                                   (LampTuneCardCapMask << LampTuneCardCapShift) | LampTuneFollowSoft |
                                   LampTuneWindow | LampTuneCentred)) == 0);
inline constexpr float LampDiscLeast = 0.03f, LampDiscMost = 0.3f, LampDiscCap = 0.5f;
/// A followed lamp's disc moves this share of the way to the one its reach gives now, each frame
/// (LampDiscKeep), unless that one is LampDiscJump times larger or smaller: then it is taken at once.
inline constexpr float LampDiscFollow = 0.0625f, LampDiscJump = 1.6f;
inline float LampDiscRadius(const LampShadowTune& tune, float inv_r2) {
    const float reach = inv_r2 > 0.0f && std::isfinite(inv_r2) ? 1.0f / std::sqrt(inv_r2) : 0.0f;
    const float soft = std::clamp(tune.disc_each * reach, LampDiscLeast, LampDiscMost);
    return std::min(soft * (tune.radius_m / LampSoftnessRadii[1]), LampDiscCap);
}

/// bbport (r91_lamp-radius-per-lamp): the disc a followed lamp has this frame: `held` (its disc of
/// the frame before; 0: none) moved LampDiscFollow of the way to `wanted` (LampDiscRadius now), so
/// that a flame whose reach flickers (5 m and 6.6 m in turn) keeps a steady disc near the mean of
/// its values. `wanted` itself where there is none, or where it is LampDiscJump times larger or
/// smaller than `held` (another softness, or another lamp in its place).
inline float LampDiscKeep(float held, float wanted) {
    if (!(held > 0.0f) || !(wanted < held * LampDiscJump) || !(wanted * LampDiscJump > held)) {
        return wanted;
    }
    return held + (wanted - held) * LampDiscFollow;
}

/// bbport (r91_lamp-radius-per-lamp): word 10 of a lamp record, as point_shadow_ray.comp
/// lampVisibility unpacks it: the disc's radius in millimetres, rounded (low 16 bits), and the
/// blind distance of a ray to it in millimetres, rounded up (high 16 bits): LampPassClearance at
/// that radius, BB_LAMP_SHADOW_CLEARANCE but at least the radius plus LampClearanceOverRadius.
inline std::uint32_t LampDiscWord(const LampShadowTune& tune, float radius_m) {
    LampShadowTune at = tune;
    at.radius_m = radius_m;
    const auto mm = [](float m, bool up) {
        const float v = std::clamp(m * 1000.0f, 0.0f, 65535.0f);
        return std::uint32_t(up ? std::ceil(v - 0.01f) : std::round(v));
    };
    return mm(radius_m, false) | mm(LampPassClearance(at), true) << 16;
}'''),
  after("    float step_sum = 0.0f, step_most = 0.0f;",
r'''    /// bbport (r91_lamp-radius-per-lamp): its disc this frame, m (LampTrack::Disc; 0: none yet),
    /// its disc of the frame before (set by Follow; 0: none), and how often it jumped (LampDiscKeep
    /// took the new one at once) along the frames it was followed since LampTrack::ClearSteps
    float disc = 0.0f, disc_was = 0.0f;
    std::uint32_t disc_moves = 0;'''),
  after("            lamp.followed = true;",
r'''            lamp.disc_was = was.disc; // bbport (r91_lamp-radius-per-lamp)
            lamp.disc_moves = was.disc_moves;'''),
  before("    /// The up to four brightest lamps within Near of the camera (the nearer first among equals),",
r'''    /// bbport (r91_lamp-radius-per-lamp): the disc of lamp `index` this frame for the radius its
    /// record asks for now (`wanted`, LampDiscRadius): worked out at its first record of the frame
    /// from the disc it had in the frame before (LampDiscKeep; none when it is not followed), kept
    /// for the next frame, and the same for its other records. No lamp (-1, or beyond Most):
    /// `wanted`.
    float Disc(int index, float wanted) {
        if (index < 0 || std::uint32_t(index) >= count) {
            return wanted;
        }
        LampSeen& lamp = lamps[std::uint32_t(index)];
        if (!(lamp.disc > 0.0f)) {
            lamp.disc = LampDiscKeep(lamp.disc_was, wanted);
            // (a jump: LampDiscKeep took the new one at once)
            lamp.disc_moves += lamp.disc_was > 0.0f && lamp.disc == wanted && wanted != lamp.disc_was ? 1u : 0u;
        }
        return lamp.disc;
    }
'''),
  after("            lamps[i].step_sum = lamps[i].step_most = 0.0f;",
        "            lamps[i].disc_moves = 0; // bbport (r91_lamp-radius-per-lamp)"),
 ],
 R + "vk_point_shadow.cpp": [
  after('                    tune.follow_soft ? "yes" : "no");',
r'''        // bbport (r91_lamp-radius-per-lamp): said once, when on
        if (tune.disc_each > 0.0f) {
            std::printf("Ray traced lamps (r91): BB_LAMP_SHADOW_RADIUS_PER_LAMP=%.4f: in the pass that averages "
                        "each lamp has a disc of its own, clamp(%.4f x its reach, %.2f m, %.2f m) x the softness "
                        "radius / %.1f m, at most %.1f m (sharp: none, the knob changes nothing); a followed "
                        "lamp's disc moves %.4f of the way to that each frame (%.1f times larger or smaller: at "
                        "once, a jump); its rays are blind within the larger of BB_LAMP_SHADOW_CLEARANCE and its "
                        "radius + %.2f m; the lamp line shows each near lamp's disc and its jumps since the line "
                        "before\n",
                        tune.disc_each, tune.disc_each, LampDiscLeast, LampDiscMost, LampSoftnessRadii[1],
                        LampDiscCap, LampDiscFollow, LampDiscJump, LampClearanceOverRadius);
        }'''),
  after("            record[15] = std::bit_cast<u32>(step);",
r'''            // bbport (r91_lamp-radius-per-lamp): word 10, the lamp's own disc and its rays' blind
            // distance (LampDiscWord), read by the pass only with tune word 0 bit 24, which Flush
            // sets after this call
            if (tune.disc_each > 0.0f) {
                const float disc = track.Disc(track_index[k], LampDiscRadius(tune, std::bit_cast<float>(record[3])));
                record[10] = LampDiscWord(tune, disc);
            }'''),
  after("                    lamp.world[2], lamp.radius, lamp.luma, lamp.away, lamp.records);",
r'''        if (tune.disc_each > 0.0f) { // bbport (r91_lamp-radius-per-lamp)
            std::printf(", disc %.3f m (%u jumps)", lamp.disc, lamp.disc_moves);
        }'''),
  after("                TrackLamps(table, blend, (flags & HistoryRead) != 0, line);",
r'''                // bbport (r91_lamp-radius-per-lamp): the records hold their discs now (word 10):
                // the bit that has the pass read them. Not in a pass that averages after this
                // frame's TrackLamps (below) or one that does not average: their word 10 is the
                // game's.
                if (blend && tune.disc_each > 0.0f) {
                    data[tune_at] |= LampTuneDiscEach;
                }'''),
 ],
 H + "point_shadow_ray.comp": [
  after("float t_radius = 0.0;           // the lamp's radius, m; 0: a point",
r'''// bbport (r91_lamp-radius-per-lamp): tune word 0 bit 24 (BB_LAMP_SHADOW_RADIUS_PER_LAMP): each
// lamp's disc from word 10 of its record (lampVisibility). lamp_rec: the record main's exact loop
// is at; pick_top, pick_cand, pick_rest: the records of top_l, cand_l and rest_l in its pick loop
// (kept only with the bit), pick_calls: lampRecord's calls in the pick path; ray_clear: the blind
// distance of the lamp ray() aims at (0: t_clear).
bool t_disc_each = false;
uint lamp_rec = 0u, pick_top = 0u, pick_cand = 0u, pick_rest = 0u, pick_calls = 0u;
float ray_clear = 0.0;'''),
  after("    t_radius = word(at + 2u);",
        "    t_disc_each = (f & (1u << 24u)) != 0u; // bbport (r91_lamp-radius-per-lamp)"),
  ("    const float tmax = ray_len - t_clear;",
   "    const float tmax = ray_len - (ray_clear > 0.0 ? ray_clear : t_clear); // bbport (r91): the lamp's own"),
  before("// bbport (r41_lamp-shadows, r42_lamp-soft): whether the lamp at L lights the surface at P, by",
r'''// bbport (r91_lamp-radius-per-lamp): the record of the lamp lampVisibility traces: in the exact path
// (steps 0) the one main's loop is at; else main's pick path traces the strongest lamp first
// (pick_top) and the picked one second (pick_rest), each with one call.
uint lampRecord() {
    if (steps == 0u) {
        return lamp_rec;
    }
    return pick_calls++ == 0u ? pick_top : pick_rest;
}
'''),
  ("    vec3 target = L;\n    if (t_radius > 0.0) {",
r'''    vec3 target = L;
    // bbport (r91_lamp-radius-per-lamp): with tune word 0 bit 24 and a disc in this pass (t_radius
    // above 0; a point lamp stays a point), the lamp's own disc: word 10 of its record, the radius
    // in millimetres (low 16 bits) and the blind distance of its rays (high 16 bits), for ray()
    // (lamp_shadow_tune.h LampDiscWord). Without the bit: t_radius, and ray() keeps t_clear.
    float radius = t_radius;
    if (t_disc_each && t_radius > 0.0) {
        const uint disc = data.d[lampRecord() + 10u];
        radius = float(disc & 0xFFFFu) * 0.001;
        ray_clear = float(disc >> 16u) * 0.001;
    }
    if (radius > 0.0) {'''),
  ("            target += (t_radius * sqrt(xi.x)) * (cos(a) * u + sin(a) * v);",
   "            target += (radius * sqrt(xi.x)) * (cos(a) * u + sin(a) * v); // bbport (r91): was t_radius"),
  before("            if (w > view_top) {",
r'''            if (t_disc_each) { // bbport (r91_lamp-radius-per-lamp): the records of top_l and cand_l below
                pick_cand = w > view_top ? pick_top : at;
                pick_top = w > view_top ? at : pick_top;
            }'''),
  after("                    rest_l = cand_l;",
        "                    pick_rest = pick_cand; // bbport (r91_lamp-radius-per-lamp)"),
  after("                        const uint at = lights_at + k * 16u;",
        "                        lamp_rec = at; // bbport (r91_lamp-radius-per-lamp): lampVisibility's record"),
 ],
 "engine/tests/test_lamp_shadow_tune.cpp": [
  before("    // Two lamps a few centimetres apart that move together (a hand torch made of two lights):",
r'''    // bbport (r91_lamp-radius-per-lamp): BB_LAMP_SHADOW_RADIUS_PER_LAMP, each lamp's disc from its
    // reach (LampDiscRadius), word 10 (LampDiscWord), the disc a followed lamp keeps (LampDiscKeep,
    // LampTrack::Disc), and its bit, which LampTuneWords never sets (Flush does).
    {
        const LampShadowTune d;
        assert(d.disc_each == 0.0f);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_RADIUS_PER_LAMP", "0.02"}}}).disc_each == 0.02f);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_RADIUS_PER_LAMP", "-1"}}}).disc_each == 0.0f);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_RADIUS_PER_LAMP", "5"}}}).disc_each == 1.0f);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_RADIUS_PER_LAMP", "wide"}}}).disc_each == 0.0f);
        LampShadowTune on = d;
        on.disc_each = 0.02f;
        // The knob is no tuning word: the words, word 0 included, are those of the knob off.
        assert(LampTuneWords(on, false, 0.05f) == LampTuneWords(d, false, 0.05f));
        assert((LampTuneWords(on, true, 0.05f)[0] & LampTuneDiscEach) == 0u);
        const auto inv = [](float reach) { return 1.0f / (reach * reach); };
        // Soft (0.1 m): clamp(k x reach, 0.03 m, 0.3 m).
        assert(std::abs(LampDiscRadius(on, inv(5.0f)) - 0.1f) < 1e-6f);
        assert(std::abs(LampDiscRadius(on, inv(12.0f)) - 0.24f) < 1e-6f);
        assert(LampDiscRadius(on, inv(40.0f)) == LampDiscMost && LampDiscRadius(on, inv(0.5f)) == LampDiscLeast);
        assert(LampDiscRadius(on, 0.0f) == LampDiscLeast && LampDiscRadius(on, std::nanf("")) == LampDiscLeast);
        // The softness is the base: softer twice (at most LampDiscCap), sharp no disc.
        LampShadowTune softer = on;
        softer.radius_m = LampSoftnessRadii[2];
        assert(std::abs(LampDiscRadius(softer, inv(5.0f)) - 0.2f) < 1e-6f);
        assert(LampDiscRadius(softer, inv(40.0f)) == LampDiscCap);
        LampShadowTune sharp = on;
        sharp.radius_m = LampSoftnessRadii[0];
        assert(LampDiscRadius(sharp, inv(5.0f)) == 0.0f);
        // Word 10: radius and blind distance in millimetres (BB_LAMP_SHADOW_CLEARANCE, at least the
        // radius + 0.05 m), as point_shadow_ray.comp lampVisibility unpacks it.
        assert(LampDiscWord(on, 0.1f) == (100u | 180u << 16));
        assert(LampDiscWord(on, 0.3f) == (300u | 350u << 16));
        assert(LampDiscWord(on, 0.03f) == (30u | 180u << 16));
        LampShadowTune far = on;
        far.clearance_m = 2.0f;
        assert(LampDiscWord(far, 0.5f) == (500u | 2000u << 16));
        for (const float r : {0.03f, 0.1f, 0.17f, 0.24f, 0.3f, 0.5f}) {
            const std::uint32_t w = LampDiscWord(on, r);
            assert(std::abs(float(w & 0xFFFFu) * 0.001f - r) <= 0.0005f);
            assert(float(w >> 16) * 0.001f >= std::max(on.clearance_m, r + LampClearanceOverRadius) - 1e-5f);
        }
        // A followed lamp's disc moves a sixteenth of the way to the new one each frame (a flame's
        // flickering reach); one 1.6 times larger or smaller is taken at once and counted; a
        // record of no lamp takes its own.
        assert(LampDiscKeep(0.0f, 0.1f) == 0.1f && std::abs(LampDiscKeep(0.1f, 0.132f) - 0.102f) < 1e-6f);
        assert(LampDiscKeep(0.1f, 0.2f) == 0.2f && LampDiscKeep(0.2f, 0.1f) == 0.1f);
        assert(LampDiscKeep(0.1f, 0.1f) == 0.1f);
        constexpr std::array<float, 12> Same{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        LampTrack track;
        assert(track.Disc(-1, 0.07f) == 0.07f);
        // A carried flame whose reach is 5 m and 6.6 m in turn (0.1 m and 0.132 m): a steady disc
        // near their mean, at most 2 mm from one frame to the next, no jump; then 12 m: a jump.
        float held = 0.0f;
        for (int f = 0; f < 97; ++f) {
            const float reach = f == 96 ? 12.0f : (f % 2 == 1 ? 6.6f : 5.0f);
            const auto a = Record(0.0f, 1.0f, 2.0f, reach);
            track.Begin(Same.data());
            const int i = track.Add(a.data());
            track.Follow();
            const float disc = track.Disc(i, LampDiscRadius(on, F(a[3])));
            assert(track.Disc(i, LampDiscRadius(on, F(a[3]))) == disc); // its other records
            const LampSeen& lamp = track.Lamp(std::uint32_t(i));
            if (f == 0) {
                assert(!lamp.followed && std::abs(disc - 0.1f) < 1e-6f);
            } else if (f < 96) {
                assert(lamp.followed && disc >= 0.1f - 1e-6f && disc <= 0.132f + 1e-6f);
                assert(std::abs(disc - held) <= 0.0021f && lamp.disc_moves == 0u);
            } else {
                assert(std::abs(held - 0.116f) < 0.002f);
                assert(lamp.followed && std::abs(disc - 0.24f) < 1e-6f && lamp.disc_moves == 1u);
                track.ClearSteps();
                assert(lamp.disc_moves == 0u && lamp.disc == disc);
            }
            held = disc;
            track.End(true);
        }
    }'''),
 ],
 "README.md": [
  after("| `BB_LAMP_SHADOW_SOFT` | The lamp's radius in metres, 0 to 0.5 (0 is a point lamp). A number here wins over `graphics_lamp_shadow_softness`; text that is not a number does not | not set |",
        "| `BB_LAMP_SHADOW_RADIUS_PER_LAMP` | Each lamp gets a disc of its own size from its reach, in the pass that averages over frames: radius = clamp(value x reach, 0.03 m, 0.3 m) x the softness radius / 0.1 m, at most 0.5 m; a lamp followed from frame to frame moves its disc 1/16 of the way to that each frame, so a flickering flame keeps a steady one (1.6 times larger or smaller: at once); its rays are blind within the larger of `BB_LAMP_SHADOW_CLEARANCE` and that radius + 0.05 m. Sharp has no disc, so it changes nothing there. 0 to 1 per metre of reach; 0 is off (one radius for every lamp); 0.02 keeps a lamp of 5 m reach at the soft radius | `0` |"),
 ],
}

# Order checks on the patched result: each string after the one before it (first occurrence).
ORDER = {
    H + "point_shadow_ray.comp": ["float t_radius = 0.0;", "bool t_disc_each = false;", "float ray_clear = 0.0;",
                                  "    t_radius = word(at + 2u);", "    t_disc_each = (f & (1u << 24u))",
                                  "float ray(vec3 origin,", "(ray_clear > 0.0 ? ray_clear : t_clear)",
                                  "uint lampRecord()", "float lampVisibility(", "float radius = t_radius;",
                                  "if (radius > 0.0) {", "target += (radius * sqrt(xi.x))",
                                  "pick_cand = w > view_top ? pick_top : at;", "            if (w > view_top) {",
                                  "                    rest_l = cand_l;\n                    pick_rest = pick_cand;",
                                  "                        const uint at = lights_at + k * 16u;\n                        lamp_rec = at;"],
    R + "vk_point_shadow.cpp": ["Ray traced lamps (r91): BB_LAMP_SHADOW_RADIUS_PER_LAMP",
                                "void PointShadow::TrackLamps(", "record[15] = std::bit_cast<u32>(step);",
                                "record[10] = LampDiscWord(tune, disc);", ", disc %.3f m (%u jumps)",
                                "TrackLamps(table, blend,", "data[tune_at] |= LampTuneDiscEach;"],
    R + "lamp_shadow_tune.h": ["float disc_each = 0.0f;", "inline LampShadowTune ReadLampShadowTune(",
                               "BB_LAMP_SHADOW_RADIUS_PER_LAMP\", tune.disc_each", "inline float LampPassClearance(",
                               "LampTuneDiscEach = 1u << 24;", "inline float LampDiscRadius(", "inline float LampDiscKeep(",
                               "inline std::uint32_t LampDiscWord(", "struct LampSeen", "float disc = 0.0f, disc_was = 0.0f;",
                               "class LampTrack", "lamp.disc_was = was.disc;", "float Disc(int index, float wanted)",
                               "lamps[i].disc_moves = 0;"],
}
# Exact counts on the patched result.
CHECKS = {
    H + "point_shadow_ray.comp": [("t_radius * sqrt", 0), ("ray_len - t_clear", 0), ("lampRecord(", 2),
                                  ("(1u << 24u)", 1), ("ray_clear = ", 2), ("lamp_rec = at;", 1),
                                  ("pick_rest = pick_cand;", 1), (TAG, 7)],
    R + "vk_point_shadow.cpp": [("LampTuneDiscEach", 1), ("LampDiscWord(", 1), ("track.Disc(", 1), (TAG, 4)],
    R + "lamp_shadow_tune.h": [("1u << 24", 1), ("BB_LAMP_SHADOW_RADIUS_PER_LAMP", 3), (TAG, 9)],
    "engine/tests/test_lamp_shadow_tune.cpp": [("BB_LAMP_SHADOW_RADIUS_PER_LAMP", 5), (TAG, 1)],
    "README.md": [("| `BB_LAMP_SHADOW_RADIUS_PER_LAMP` |", 1)],
}

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
                raise SystemExit("text check: %s holds %r %d times, wanted %d"
                                 % (path, s, texts[path].count(s), n))
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                raise SystemExit("order check: %s: %r not after the one before" % (path, s))
            at = i
    for path, edits in EDITS.items():
        for old, new in edits:
            if not all(ord(c) < 128 for c in new) or "\r" in new:
                raise SystemExit("%s: new text must be ASCII with LF in the script" % path)

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R91_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(new) == 1 for old, new in edits)
        # Each anchor once, checked in order on the text the edits before it made (as apply does).
        todo, work = 0, cur
        for old, new in edits:
            if work.count(old) == 1 and work.count(new) == 0:
                todo += 1
                work = work.replace(old, new)
        if done == len(edits): state = "applied"
        elif todo == len(edits): state = "clean"
        else:
            bad = [old[:70] for old, new in edits if cur.count(new) != 1 and cur.count(old) != 1]
            raise SystemExit("%s: %d of %d edits applied, %d anchors found once in order; refused (%r)"
                             % (path, done, len(edits), todo, bad))
        plan.append((path, edits, raw, eol, cur, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            texts = {}
            for path, edits, raw, eol, cur, _ in plan:
                for old, new in edits: cur = cur.replace(old, new)
                texts[path] = cur
            text_checks(texts)
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied": print("already applied"); return
        texts, outs = {}, []
        for path, edits, raw, eol, cur, _ in plan:
            for old, new in edits:
                if cur.count(old) != 1:
                    raise SystemExit("%s: anchor not found exactly once: %r" % (path, old[:70]))
                cur = cur.replace(old, new)
            texts[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r91tmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(ROOT, path))
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r91tmp"
                if os.path.exists(tmp): os.remove(tmp)
            for path, raw in written:
                open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    outs = []
    for path, edits, raw, eol, cur, _ in plan:
        for old, new in reversed(edits):
            if cur.count(new) != 1:
                raise SystemExit("%s: edit not found exactly once, nothing reverted: %r" % (path, new[:70]))
            cur = cur.replace(new, old)
        outs.append((path, cur.replace("\n", eol).encode("utf-8")))
    for path, data in outs:
        open(os.path.join(ROOT, path), "wb").write(data)
    print("reverted")

main()
