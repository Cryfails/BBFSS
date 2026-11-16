# r112h_hang-not-the-hunter: FEATURE fix on top of r112g_hang-judge-settles (r112f, r112e, r112d, r112c,
# r112b, r112). Behind r112's own knob BB_WIND_HANG=1 (off by default); BB_WIND_HANG_ACTORS=0 leaves this
# patch's rules out again (r112g's behaviour). With BB_WIND_HANG unset nothing of this runs: the new
# Rasterizer code is reached only from WindSwayWord's GPU-judge branch (`judge`, set only by
# WindHangVerdict, which returns at its first line without the knob), the once-line and the report lines sit
# behind BbWindHang::KnobOnce().on, and the only line outside that is one compare per motion draw
# (`sway != 0 && ...`, false for every draw without a sway word). No shader changes: the SPIR-V is byte
# for byte the same.
#
# THE EVIDENCE (b42 reader report, slot_b42_result.txt): the GPU judge settles (graveyard 7 hang /
# 3074 pushed, alley 4 / 2400) but the do-nothing dark interior ALSO has 4 hang / 2400 pushed, and the hang
# meshes are the same four hashes in every place (c77a0097 0.22 m, b10c4f55 0.21/0.19 m, 3deaa573
# 0.44/0.20 m, a7450683 0.54 m) with their tops about 1.2 m above the hunter's feet (graveyard: hunter y
# -40.82, tops -39.2 .. -40.1): the hunter's own gear, 28 bone pieces, standing still while the hunter
# does. No lantern, chain or cage leans in any picture. 17-24 streams per place stay judging for good
# ("no key offered ... 7f7fffff").
#
# WHAT THIS DOES
#  (1) NEVER THE HUNTER OR A FIGURE. When a stream's box keys first read as still (the Still case of
#      WindSwayWord) Rasterizer::WindHangActorsClear tests it once per GPU-judge window
#      (BbWindHangActors::Judge, bbport_wind_hang_actors.h): more than BB_WIND_HANG_BONES (24) bones in
#      its palette = a figure's rig (the gear pieces have 28); its world box (the GPU's keys: world x, y,
#      z) within BB_WIND_HANG_NEAR (1.5 m) sideways of the hunter's position (BbEngine::
#      world_player_position, read once a frame, only here) and overlapping 1.5 m under to 2.5 m over it =
#      on him; the hunter's position unread = nothing is taken; no box keys = place unknown = nothing is
#      taken. A refused stream is held as moving (BoxBook::Reject, dev -2): 1800 frames for a figure or
#      something on him, 300 for the other reasons, then judged again with a new window. Logged: a totals
#      line and a kept / refused line with hashes, heights, tops, bone counts and the sideways distance.
#  (2) NEVER INDOORS. The camera's open share of the wind (r117's shelter field at the camera,
#      WindShelter::CameraOpen: 1 outside, 0 deep in a covered place) at or under BB_WIND_HANG_INDOOR
#      (0.1; 0 off) refuses a stream the same way. Without the field (BB_WIND_SHELTER off, no upscaler)
#      the rule does not run and the line says "no field: rule off". Things already hanging are not stopped
#      when the camera walks in: r117 scales every sway vertex's displacement by the field at the vertex
#      (hang vertices included). The r81 area gate and r76e roof rule are GPU passes with no CPU value to
#      read, so they are not used.
#  (3) KEYLESS STREAMS. Why the big streams never get a key cannot be seen from the CPU (the shader code
#      is the plants' and the small hangers' own, and those streams do get keys elsewhere). Two things
#      are done: (a) a give-up (no y key in 300 frames) holds the stream for 7200 frames, not 300, so a
#      keyless stream costs one window of judging words in 7500 frames and no longer one in 600
#      (BoxEntry::keyless, hold; BoxBook::SetKeylessHold); (b) the facts of the last judging draw of each
#      stream (the vertex shader's hash, the position bytes, the stride and so the vertex count, whether
#      the format is float, the slot, the word and its view, the view's camera and its distance from the
#      hunter) are kept, and the give-up note (r112g, at most 8 a window) is followed by a
#      "keyless stream" line with them, and a counter of sway words that got no motion parameter (the
#      parameter ring has 8192 entries a frame; a draw past it gets none, so its word never reaches the
#      shader: one of the causes the CPU can see) is in the totals line. Those lines name the cause or
#      rule out the CPU-side ones; the GPU-side one (a camera constant set that is not the camera) shows
#      as a camera far from the hunter.
#  (4) REPORT. Every 600 frames: "Wind sway hang (r112h): hunter ... tests: N kept, ..." and "Wind sway
#      hang (r112h): kept vs <hash> <h> m top y .. <bones>b side .. m; refused vs ... <reason>", up to 3
#      of each, tallest first, so the heights of what still hangs (and the reasons the rest was refused)
#      are in the log. r112's own "meshes" line still names what is pushed.
#
# Files: engine/gpu/shim/bbport_wind_hang_actors.h (new), bbport_wind_hang_still.h (BoxEntry hold and
# keyless, Due, GiveUp, Reject, SetKeylessHold, Keyless), vk_rasterizer.h (include, member, declaration),
# vk_rasterizer.cpp (one counter line after the motion draw), vk_rasterizer_effects.cpp (include, the Judging
# and Still cases, WindHangActorsClear, the once-line, the report lines), engine/tests/
# test_wind_hang_actors.cpp (new), engine/gpu/CMakeLists.txt and engine/build.sh (the test), README.md (a
# row). No shader, no new log pattern outside "Wind sway hang".
#
# Cost (estimate, nothing measured): CPU, per judging draw one hash insert of a 40-byte record (at most
# 256 streams); per Still transition (once per stream window) one hunter read of six pointer reads and a
# 12-byte read (once a frame at most), the shelter's counter word, a few compares; per motion draw with a
# sway word one compare. GPU: none; fewer judging words than r112g (keyless streams, refused ones).
# Memory: 2 maps of at most 256 small records.
#
# Use: python -I -X utf8 r112h_hang-not-the-hunter.py check | apply | revert
# Root: R112H_ROOT, else <tree>. CRLF kept. apply backs the originals up in r112h_backup next to
# this script; revert takes out exactly what apply put in (new files removed). Needs r112g applied.
import os, sys

ROOT = os.environ.get("R112H_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112h_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RE = RV + "vk_rasterizer_effects.cpp"
RH = RV + "vk_rasterizer.h"
RC = RV + "vk_rasterizer.cpp"
NH = "engine/gpu/shim/bbport_wind_hang_still.h"
NA = "engine/gpu/shim/bbport_wind_hang_actors.h"
NT = "engine/tests/test_wind_hang_actors.cpp"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
RM = "README.md"

NEW_FILES = {
NA: r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r112h_hang-not-the-hunter): who may hang. b42's GPU judge settled (graveyard 7 hang, alley 4,
// and the do-nothing dark interior 4 too), but the hang meshes were the same four hashes in every place,
// 0.2-0.54 m tall, with their tops about 1.2 m above the hunter's position: his own gear (28 bone
// pieces) standing still passes a stillness test. This file holds the rules that keep a character, the
// hunter above all, and an indoor place out; they run once when a stream's box keys first read as still
// (the Still case of WindSwayWord, through Rasterizer::WindHangActorsClear), never per draw:
//  - BONES: a palette of more than BB_WIND_HANG_BONES bones (default 24) is a rig of a figure (the
//    hunter's gear pieces have 28), not a lantern on a chain. The log names the bone counts it refuses.
//  - NEAR: the mesh's world box (the GPU's x, y, z keys: world coordinates) lies within
//    BB_WIND_HANG_NEAR metres (default 1.5; 0 turns the rule off) of the hunter's position as the
//    game's physics keeps it (BbEngine::world_player_position) sideways, and overlaps the band from
//    1.5 m under to 2.5 m over his position: it is on him. The hunter's position unread: nothing is
//    taken (no level yet).
//  - INDOORS: the camera's open share of the wind (r117's shelter field at the camera, 1 outside, 0
//    deep in a covered place) is at or under BB_WIND_HANG_INDOOR (default 0.1; 0 turns the rule off).
//    Without the shelter field (BB_WIND_SHELTER off or no upscaler) there is no such number and the
//    rule does not run (the line says so). Things that already hang are not stopped when the camera
//    walks in: r117 scales every sway vertex's displacement by the field at the vertex (the sun fog
//    gate r81 and the roof rule r76e are GPU passes without a CPU value).
//  - UNPLACED: no box (the x and z keys never came): its place is not known, nothing is taken.
// A refused stream is held as moving for HoldFrames (1800 for a figure or something on the hunter,
// 300 for the other reasons) and then judged again with a new window. A stream that was cleared stays
// cleared for its window. Streams the GPU never offered a key to (BoxBook's give-up) are held
// KeylessHoldFrames (7200: about two minutes) instead of 300, so they cost one window of judging words
// in 7500 frames, not one in 600; the facts of the last judging draw of each (the vertex shader, the
// bytes and the vertex count, the stride, the slot, the view and its camera, the word) are kept for
// the give-up note (Facts) so that the log says what the draw had when the keys never came.
// BB_WIND_HANG_ACTORS=0 leaves all of it out (r112g's behaviour). Nothing here runs without
// BB_WIND_HANG=1.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <unordered_map>
#include <vector>

#include "bbport_wind_hang_still.h"

namespace BbWindHangActors {

inline constexpr unsigned BonesDefault = 24;
inline constexpr unsigned BonesMin = 1;
inline constexpr unsigned BonesMax = BbWindHangStill::CharacterBones;
inline constexpr float NearDefault = 1.5f, NearMax = 6.0f; ///< m sideways from the hunter
inline constexpr float IndoorDefault = 0.1f;               ///< open share at or under: indoors
inline constexpr float BandBelow = 1.5f, BandAbove = 2.5f; ///< m around the hunter's y
inline constexpr std::uint64_t FigureHoldFrames = 1800;
inline constexpr std::uint64_t PlaceHoldFrames = BbWindHangStill::RejudgeFrames;
inline constexpr std::uint64_t KeylessHoldFrames = 7200;
inline constexpr std::size_t SeenMost = 256, FactsMost = 256, ListMost = 3;
inline constexpr std::size_t LineChars = BbWindHangStill::LineChars;

struct Knobs {
    bool on = true;
    unsigned bones = BonesDefault;
    float near_m = NearDefault;
    float indoor = IndoorDefault;
};

[[nodiscard]] inline Knobs ParseKnobs(const char* actors, const char* bones, const char* near_m,
                                      const char* indoor) {
    Knobs k;
    k.on = !(actors != nullptr && actors[0] == '0');
    const float b = BbWindSway::ParseNumber(bones, float(BonesDefault));
    k.bones = unsigned(std::clamp(b, float(BonesMin), float(BonesMax)));
    k.near_m = std::clamp(BbWindSway::ParseNumber(near_m, NearDefault), 0.0f, NearMax);
    k.indoor = std::clamp(BbWindSway::ParseNumber(indoor, IndoorDefault), 0.0f, 1.0f);
    return k;
}

/// The knobs, read once.
[[nodiscard]] inline const Knobs& KnobOnce() {
    static const Knobs k =
        ParseKnobs(std::getenv("BB_WIND_HANG_ACTORS"), std::getenv("BB_WIND_HANG_BONES"),
                   std::getenv("BB_WIND_HANG_NEAR"), std::getenv("BB_WIND_HANG_INDOOR"));
    return k;
}

enum class Why : std::uint8_t { Ok, NoHunter, Near, Bones, Indoor, Unplaced, NoPalette };
inline constexpr std::size_t WhyCount = 7;

[[nodiscard]] inline const char* WhyName(Why w) {
    switch (w) {
    case Why::Ok:
        return "kept";
    case Why::NoHunter:
        return "no hunter";
    case Why::Near:
        return "on the hunter";
    case Why::Bones:
        return "too many bones";
    case Why::Indoor:
        return "indoors";
    case Why::Unplaced:
        return "unplaced";
    case Why::NoPalette:
        return "no palette";
    }
    return "?";
}

/// How long a refused stream is held as moving (frames).
[[nodiscard]] inline std::uint64_t HoldOf(Why w) {
    return w == Why::Near || w == Why::Bones ? FigureHoldFrames : PlaceHoldFrames;
}

struct Hunter {
    bool known = false;
    float x = 0.0f, y = 0.0f, z = 0.0f;
    std::uint64_t frame = ~std::uint64_t{0}; ///< the frame it was read for
};

[[nodiscard]] inline bool Finite3(const float p[3]) {
    return std::isfinite(p[0]) && std::isfinite(p[1]) && std::isfinite(p[2]);
}

/// The distance from `p` to the interval [lo, hi] (0 inside).
[[nodiscard]] inline float Gap(float lo, float hi, float p) {
    return std::max(std::max(lo - p, p - hi), 0.0f);
}

/// The sideways distance (m) from the hunter to a mesh's world box (0 when he stands inside it).
[[nodiscard]] inline float SideDistance(const BbWindHangStill::BoxMeasure& m, const Hunter& h) {
    const float dx = Gap(m.x_lo, m.x_hi, h.x), dz = Gap(m.z_lo, m.z_hi, h.z);
    return std::sqrt(dx * dx + dz * dz);
}

/// Does the box's height overlap the band around the hunter's position?
[[nodiscard]] inline bool InBand(const BbWindHangStill::BoxMeasure& m, const Hunter& h) {
    return m.crown >= h.y - BandBelow && m.base <= h.y + BandAbove;
}

/// May a stream hang? `box` its GPU judge entry (the first read of its keys: where it is), `bones`
/// its palette's bones (0: none known), `h` the hunter, `open` the camera's open share of the wind
/// (1 when the shelter field does not exist), `have_field` whether it does. `side` gets the sideways
/// distance from the hunter when it was worked out (else -1).
[[nodiscard]] inline Why Judge(const Knobs& k, const BbWindHangStill::BoxEntry* box,
                               unsigned bones, const Hunter& h, float open, bool have_field,
                               float* side) {
    if (side != nullptr) {
        *side = -1.0f;
    }
    if (box == nullptr || bones == 0) {
        return Why::NoPalette;
    }
    if (bones > k.bones) {
        return Why::Bones;
    }
    if (!box->snap.box_ok) {
        return Why::Unplaced;
    }
    if (!h.known) {
        return Why::NoHunter;
    }
    const float d = SideDistance(box->snap, h);
    if (side != nullptr) {
        *side = d;
    }
    if (k.near_m > 0.0f && d <= k.near_m && InBand(box->snap, h)) {
        return Why::Near;
    }
    if (k.indoor > 0.0f && have_field && open <= k.indoor) {
        return Why::Indoor;
    }
    return Why::Ok;
}

/// What the book keeps of a tested stream (for the log).
struct Seen {
    std::uint32_t vs = 0, bones = 0; ///< its vertex shader (low 32 bits), its palette's bones
    float height = 0.0f, top = 0.0f; ///< from the box keys (m)
    float side = -1.0f;              ///< sideways distance from the hunter (m), -1 unknown
    Why why = Why::Ok;
    std::uint64_t window = 0; ///< the GPU judge's window (BoxEntry::started) it was tested in
    std::uint64_t frame = 0;  ///< the frame it was tested
};

/// What the last judging draw of a stream had.
struct Facts {
    std::uint32_t vs = 0, size = 0, stride = 0, slot = 0, view = 0, views = 0, word = 0;
    float cam[3] = {0.0f, 0.0f, 0.0f};
    bool floats = false;
    std::uint64_t frame = 0;
};

class Book {
public:
    Hunter hunter;
    std::uint64_t hunter_read = 0, hunter_unread = 0;
    std::uint64_t no_param = 0; ///< sway words of draws that got no motion parameter (lost)
    std::array<std::uint64_t, WhyCount> by_why{};

    /// Was `stream` cleared in the window that began on `window`?
    [[nodiscard]] bool Cleared(std::uint64_t stream, std::uint64_t window) const {
        const auto found = seen.find(stream);
        return found != seen.end() && found->second.why == Why::Ok &&
               found->second.window == window;
    }

    void Note(std::uint64_t stream, const Seen& s) {
        if (seen.size() >= SeenMost && seen.find(stream) == seen.end()) {
            Prune(s.frame);
            if (seen.size() >= SeenMost) {
                return;
            }
        }
        seen[stream] = s;
        ++by_why[static_cast<std::size_t>(s.why)];
    }

    void Fact(std::uint64_t stream, const Facts& f) {
        if (facts.size() >= FactsMost && facts.find(stream) == facts.end()) {
            return;
        }
        facts[stream] = f;
    }

    [[nodiscard]] const Facts* FactsOf(std::uint64_t stream) const {
        const auto found = facts.find(stream);
        return found == facts.end() ? nullptr : &found->second;
    }

    /// The give-up's facts line (under LineChars characters); false when the stream has none.
    bool FactsText(std::uint64_t stream, std::string& out) const {
        const Facts* const f = FactsOf(stream);
        if (f == nullptr) {
            return false;
        }
        char buf[360];
        const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
        double from = -1.0;
        if (hunter.known) {
            const double dx = double(f->cam[0]) - double(hunter.x);
            const double dy = double(f->cam[1]) - double(hunter.y);
            const double dz = double(f->cam[2]) - double(hunter.z);
            from = std::sqrt(dx * dx + dy * dy + dz * dz);
        }
        std::snprintf(buf, sizeof(buf),
                      "Wind sway hang (r112h): keyless stream %llx: vs %08x, %u bytes of "
                      "positions at stride %u (%u vertices, %s), slot %u, last word %08x on view "
                      "%u of %u (camera %.1f %.1f %.1f, %.1f m from the hunter), frame %llu",
                      n(stream), f->vs, f->size, f->stride,
                      f->stride != 0 ? f->size / f->stride : 0u, f->floats ? "floats" : "not floats",
                      f->slot, f->word, f->view, f->views, double(f->cam[0]), double(f->cam[1]),
                      double(f->cam[2]), from, n(f->frame));
        out = buf;
        if (out.size() > LineChars) {
            out.resize(LineChars - 3);
            out += "...";
        }
        return true;
    }

    /// The two lines every 600 frames: the totals, then the meshes kept and refused (the most recent
    /// ListMost of each, tallest first). `have_field`: the shelter field exists; `keyless` the GPU
    /// judge's streams that gave up with no key (BoxBook::Keyless). Both under LineChars.
    void Lines(std::uint64_t frame, bool have_field, unsigned keyless, std::string& first,
               std::string& second) const {
        const Knobs& k = KnobOnce();
        const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
        char buf[360];
        char at[64];
        if (hunter.known) {
            std::snprintf(at, sizeof(at), "at %.1f %.1f %.1f", double(hunter.x), double(hunter.y),
                          double(hunter.z));
        } else {
            std::snprintf(at, sizeof(at), "unread");
        }
        const auto w = [&](Why why) { return n(by_why[static_cast<std::size_t>(why)]); };
        std::snprintf(buf, sizeof(buf),
                      "Wind sway hang (r112h): hunter %s (%llu reads, %llu unread); tests: %llu "
                      "kept, %llu on the hunter (%.1f m), %llu over %u bones, %llu indoors (%s), "
                      "%llu unplaced, %llu no hunter; %u keyless held; %llu sway words lost (no "
                      "motion parameter)",
                      at, n(hunter_read), n(hunter_unread), w(Why::Ok), w(Why::Near),
                      double(k.near_m), w(Why::Bones), k.bones, w(Why::Indoor),
                      have_field ? "field" : "no field: rule off", w(Why::Unplaced),
                      w(Why::NoHunter), keyless, n(no_param));
        first = buf;
        if (first.size() > LineChars) {
            first.resize(LineChars - 3);
            first += "...";
        }
        std::string kept = "Wind sway hang (r112h): kept";
        std::string refused = "; refused";
        unsigned kept_n = 0, refused_n = 0;
        std::vector<const Seen*> order;
        for (const auto& item : seen) {
            if (item.second.frame + BbWindHangStill::SeenFrames * 2 >= frame) {
                order.push_back(&item.second);
            }
        }
        std::sort(order.begin(), order.end(), [](const Seen* a, const Seen* b) {
            return a->height > b->height;
        });
        for (const Seen* s : order) {
            const bool ok = s->why == Why::Ok;
            if ((ok ? kept_n : refused_n) >= ListMost) {
                continue;
            }
            (ok ? kept_n : refused_n) += 1;
            std::snprintf(buf, sizeof(buf), " vs %08x %.2f m top y %.1f %ub side %.1f m%s%s",
                          s->vs, double(s->height), double(s->top), s->bones, double(s->side),
                          ok ? "" : " ", ok ? "" : WhyName(s->why));
            (ok ? kept : refused) += buf;
        }
        if (kept_n == 0) {
            kept += " none";
        }
        if (refused_n == 0) {
            refused += " none";
        }
        second = kept + refused;
        if (second.size() > LineChars) {
            second.resize(LineChars - 3);
            second += "...";
        }
    }

    [[nodiscard]] std::size_t Size() const {
        return seen.size();
    }

private:
    void Prune(std::uint64_t frame) {
        for (auto it = seen.begin(); it != seen.end();) {
            if (it->second.frame + BbWindHangStill::SeenFrames < frame) {
                it = seen.erase(it);
            } else {
                ++it;
            }
        }
    }

    std::unordered_map<std::uint64_t, Seen> seen;
    std::unordered_map<std::uint64_t, Facts> facts;
};

} // namespace BbWindHangActors
''',
NT: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112h_hang-not-the-hunter): who may hang (gpu/shim/bbport_wind_hang_actors.h): the knobs,
// the rule (the hunter's gear, figures, indoors, unplaced), the refusal's hold and the keyless hold
// in the GPU judge's book (gpu/shim/bbport_wind_hang_still.h), the book's lines.
// The twin in Python (r112h_twin.py) holds the same cases.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "gpu/shim/bbport_wind_hang_actors.h"

namespace A = BbWindHangActors;
namespace S = BbWindHangStill;
namespace W = BbWindSway;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

S::BoxEntry Box(float x0, float x1, float z0, float z1, float y0, float y1, bool placed) {
    S::BoxEntry e;
    e.snap.x_lo = x0;
    e.snap.x_hi = x1;
    e.snap.z_lo = z0;
    e.snap.z_hi = z1;
    e.snap.base = y0;
    e.snap.crown = y1;
    e.snap.y_ok = true;
    e.snap.box_ok = placed;
    e.started = 7;
    return e;
}
} // namespace

int main() {
    // the knobs: defaults, an off, out of range values, text that is no number
    const A::Knobs d = A::ParseKnobs(nullptr, nullptr, nullptr, nullptr);
    Expect(d.on && d.bones == 24 && d.near_m == 1.5f && d.indoor == 0.1f, "knobs: defaults");
    const A::Knobs off = A::ParseKnobs("0", nullptr, nullptr, nullptr);
    Expect(!off.on, "knobs: BB_WIND_HANG_ACTORS=0 is off");
    const A::Knobs wide = A::ParseKnobs("1", "500", "9", "2");
    Expect(wide.on && wide.bones == S::CharacterBones && wide.near_m == A::NearMax &&
               wide.indoor == 1.0f,
           "knobs: held to their ranges");
    const A::Knobs low = A::ParseKnobs("1", "0", "-3", "-1");
    Expect(low.bones == A::BonesMin && low.near_m == 0.0f && low.indoor == 0.0f,
           "knobs: held at the low end");
    const A::Knobs junk = A::ParseKnobs("1", "abc", "x", "nan");
    Expect(junk.bones == 24 && junk.near_m == 1.5f && junk.indoor == 0.1f,
           "knobs: text that is no number gives the defaults");

    // the rule
    A::Hunter hunter;
    hunter.known = true;
    hunter.x = 10.0f;
    hunter.y = -40.0f;
    hunter.z = 20.0f;
    float side = 0.0f;
    // the gear: a 0.6 m box on the hunter, 28 bones: too many bones
    const S::BoxEntry gear = Box(9.6f, 10.3f, 19.7f, 20.2f, -40.3f, -39.7f, true);
    Expect(A::Judge(d, &gear, 28, hunter, 1.0f, true, &side) == A::Why::Bones, "rule: 28 bones");
    Expect(side < 0.0f, "rule: no distance worked out for a refusal by bones");
    // the same box with 12 bones: on the hunter
    Expect(A::Judge(d, &gear, 12, hunter, 1.0f, true, &side) == A::Why::Near && side == 0.0f,
           "rule: on the hunter");
    // 1.4 m sideways is still near, 1.6 m is not; 6 m above his band is not
    const S::BoxEntry close = Box(11.4f, 11.6f, 19.9f, 20.1f, -40.2f, -39.4f, true);
    Expect(A::Judge(d, &close, 12, hunter, 1.0f, true, &side) == A::Why::Near &&
               std::fabs(side - 1.4f) < 1e-4f,
           "rule: 1.4 m sideways is near");
    const S::BoxEntry apart = Box(11.6f, 11.8f, 19.9f, 20.1f, -40.2f, -39.4f, true);
    Expect(A::Judge(d, &apart, 12, hunter, 1.0f, true, &side) == A::Why::Ok &&
               std::fabs(side - 1.6f) < 1e-4f,
           "rule: 1.6 m sideways is kept");
    const S::BoxEntry high = Box(10.0f, 10.4f, 20.0f, 20.4f, -34.0f, -33.0f, true);
    Expect(A::Judge(d, &high, 12, hunter, 1.0f, true, &side) == A::Why::Ok,
           "rule: 6 m over him is not on him");
    const S::BoxEntry ground = Box(10.0f, 10.4f, 20.0f, 20.4f, -43.0f, -42.0f, true);
    Expect(A::Judge(d, &ground, 12, hunter, 1.0f, true, &side) == A::Why::Ok,
           "rule: 2 m under his feet is not on him");
    // far away, 6 bones: kept
    const S::BoxEntry lantern = Box(40.0f, 40.4f, 50.0f, 50.4f, -38.0f, -36.0f, true);
    Expect(A::Judge(d, &lantern, 6, hunter, 1.0f, true, &side) == A::Why::Ok && side > 30.0f,
           "rule: a lantern far away is kept");
    // not placed, the hunter unread, no palette
    const S::BoxEntry unplaced = Box(0, 0, 0, 0, -38.0f, -36.0f, false);
    Expect(A::Judge(d, &unplaced, 6, hunter, 1.0f, true, &side) == A::Why::Unplaced,
           "rule: no box keys is unplaced");
    A::Hunter blind;
    Expect(A::Judge(d, &lantern, 6, blind, 1.0f, true, &side) == A::Why::NoHunter,
           "rule: the hunter unread: nothing is taken");
    Expect(A::Judge(d, &lantern, 0, hunter, 1.0f, true, &side) == A::Why::NoPalette &&
               A::Judge(d, nullptr, 6, hunter, 1.0f, true, &side) == A::Why::NoPalette,
           "rule: no palette or no entry");
    // indoors: the open share at or under the limit, only with the field
    Expect(A::Judge(d, &lantern, 6, hunter, 0.05f, true, &side) == A::Why::Indoor &&
               A::Judge(d, &lantern, 6, hunter, 0.1f, true, &side) == A::Why::Indoor &&
               A::Judge(d, &lantern, 6, hunter, 0.5f, true, &side) == A::Why::Ok &&
               A::Judge(d, &lantern, 6, hunter, 0.0f, false, &side) == A::Why::Ok,
           "rule: indoors by the open share, not without the field");
    // the rules off by their knobs
    const A::Knobs loose = A::ParseKnobs("1", "96", "0", "0");
    Expect(A::Judge(loose, &gear, 28, hunter, 0.0f, true, &side) == A::Why::Ok,
           "rule: near 0, indoor 0 and 96 bones leave the gear in (the old behaviour)");
    // the order: bones before place before hunter before near before indoors
    Expect(A::Judge(d, &unplaced, 28, blind, 0.0f, true, &side) == A::Why::Bones &&
               A::Judge(d, &unplaced, 6, blind, 0.0f, true, &side) == A::Why::Unplaced &&
               A::Judge(d, &gear, 12, hunter, 0.0f, true, &side) == A::Why::Near,
           "rule: the order of the reasons");
    Expect(A::HoldOf(A::Why::Near) == A::FigureHoldFrames &&
               A::HoldOf(A::Why::Bones) == A::FigureHoldFrames &&
               A::HoldOf(A::Why::Indoor) == S::RejudgeFrames &&
               A::HoldOf(A::Why::Unplaced) == S::RejudgeFrames &&
               A::HoldOf(A::Why::NoHunter) == S::RejudgeFrames,
           "holds by reason");
    const float good[3] = {1.0f, 2.0f, 3.0f}, bad[3] = {1.0f, NAN, 2.0f};
    Expect(A::Finite3(good) && !A::Finite3(bad), "finite position test");

    // the GPU judge's book: a refused stream is held, a keyless one is held long
    {
        std::vector<std::uint32_t> words(BbWindTwigs::TwigEnd, W::ResetKey);
        const auto offer = [&](std::uint32_t slot, float y0, float y1, float x0, float x1,
                               float z0, float z1) {
            const auto low = [&](std::uint32_t at, std::uint32_t key) {
                words[at] = std::min(words[at], key);
            };
            const std::uint32_t at = BbWindTwigs::TwigAt + slot * BbWindTwigs::TwigSlotWords;
            low(W::BaseAt + slot, W::HeightKey(y0));
            low(W::CrownAt + slot, W::CrownKey(y1));
            low(at + 0, W::HeightKey(x0));
            low(at + 1, W::CrownKey(x1));
            low(at + 2, W::HeightKey(z0));
            low(at + 3, W::CrownKey(z1));
        };
        S::BoxBook book;
        for (std::uint64_t f = 100; f < 200; ++f) {
            if (f >= 101) {
                offer(7, -40.3f, -39.7f, 9.6f, 10.3f, 19.7f, 20.2f);
            }
            book.Step(10, 4096, 7, f == 100, f, words.data());
        }
        const S::BoxEntry* const still = book.Find(10);
        Expect(still != nullptr && still->state == S::BoxState::Still && still->snap.box_ok,
               "book: still with its box read");
        Expect(A::Judge(d, still, 12, hunter, 1.0f, true, &side) == A::Why::Near,
               "book: the gear's box read from the keys is on the hunter");
        Expect(book.Reject(10, 200, A::FigureHoldFrames) && book.HoldsMoved(10) &&
                   !book.Final(10) && book.Find(10)->dev < -1.5f,
               "book: rejected: moved, not final, dev -2");
        Expect(!book.Due(10, 200 + A::FigureHoldFrames - 1) &&
                   book.Due(10, 200 + A::FigureHoldFrames),
               "book: due after the figure hold");
        Expect(book.Find(10) == nullptr, "book: forgotten when due");
        Expect(!book.Reject(99, 200, 1), "book: a stream it does not know cannot be rejected");
        // a refusal for a place (indoors): due after RejudgeFrames
        S::BoxBook place;
        for (std::uint64_t f = 100; f < 200; ++f) {
            if (f >= 101) {
                offer(8, -40.3f, -39.7f, 9.6f, 10.3f, 19.7f, 20.2f);
            }
            place.Step(11, 4096, 8, f == 100, f, words.data());
        }
        Expect(place.Reject(11, 200, A::HoldOf(A::Why::Indoor)) &&
                   !place.Due(11, 200 + S::RejudgeFrames - 1) &&
                   place.Due(11, 200 + S::RejudgeFrames),
               "book: a place refusal is due after RejudgeFrames");
        // a keyless stream: nothing offered; the give-up holds it as the knob says
        S::BoxBook none;
        none.SetKeylessHold(A::KeylessHoldFrames);
        for (std::uint64_t f = 100; f <= 100 + S::BoxGiveUpFrames; ++f) {
            none.Step(12, 4096, 20, f == 100, f, words.data());
        }
        const std::uint64_t gave = 100 + S::BoxGiveUpFrames;
        Expect(none.HoldsMoved(12) && none.Find(12)->keyless && none.Find(12)->dev == -1.0f,
               "book: gave up, keyless");
        Expect(none.Keyless(gave) == 1u && none.Keyless(gave + 1000000) == 0u,
               "book: keyless count, recent ones only");
        Expect(!none.Due(12, gave + S::RejudgeFrames) &&
                   !none.Due(12, gave + A::KeylessHoldFrames - 1) &&
                   none.Due(12, gave + A::KeylessHoldFrames),
               "book: a keyless stream is due only after the long hold");
        // the hold 0 (the knob off) is r112g: due after RejudgeFrames
        S::BoxBook plain;
        for (std::uint64_t f = 100; f <= 100 + S::BoxGiveUpFrames; ++f) {
            plain.Step(13, 4096, 21, f == 100, f, words.data());
        }
        Expect(plain.Due(13, gave + S::RejudgeFrames), "book: hold 0 keeps r112g's 300 frames");
    }

    // the actors' book: cleared per window, counts, lines
    {
        A::Book book;
        A::Seen s;
        s.vs = 0xc77a0097u;
        s.bones = 28;
        s.height = 0.22f;
        s.top = -39.2f;
        s.side = 0.4f;
        s.why = A::Why::Bones;
        s.window = 7;
        s.frame = 1000;
        book.Note(1, s);
        Expect(!book.Cleared(1, 7), "actors: a refused stream is not cleared");
        s.why = A::Why::Ok;
        s.bones = 6;
        s.height = 0.9f;
        s.side = 12.0f;
        book.Note(1, s);
        Expect(book.Cleared(1, 7) && !book.Cleared(1, 8) && !book.Cleared(2, 7),
               "actors: cleared in its window only");
        s.vs = 0xb10c4f55u;
        s.why = A::Why::Near;
        s.height = 0.21f;
        book.Note(2, s);
        Expect(book.by_why[static_cast<std::size_t>(A::Why::Ok)] == 1u &&
                   book.by_why[static_cast<std::size_t>(A::Why::Near)] == 1u &&
                   book.by_why[static_cast<std::size_t>(A::Why::Bones)] == 1u,
               "actors: counts by reason");
        book.hunter = hunter;
        book.hunter_read = 3;
        book.no_param = 5;
        std::string first, second;
        book.Lines(1200, true, 4, first, second);
        Expect(first.size() <= A::LineChars && second.size() <= A::LineChars,
               "actors: lines under the slot report's 300");
        Expect(first.find("1 kept") != std::string::npos &&
                   first.find("4 keyless") != std::string::npos &&
                   first.find("5 sway words lost") != std::string::npos,
               "actors: totals line");
        Expect(second.find("vs 00000000") == std::string::npos &&
                   second.find("kept vs") != std::string::npos &&
                   second.find("refused vs b10c4f55") != std::string::npos &&
                   second.find("on the hunter") != std::string::npos,
               "actors: lists");
        book.Lines(1000000, false, 0, first, second);
        Expect(second.find("kept none; refused none") != std::string::npos &&
                   first.find("no field: rule off") != std::string::npos,
               "actors: nothing recent, no field");
        // the facts of a judging draw
        A::Facts f;
        f.vs = 0x6a833138u;
        f.size = 1200000;
        f.stride = 12;
        f.slot = 41;
        f.view = 0;
        f.views = 1;
        f.word = 0x80010123u;
        f.cam[0] = 9.0f;
        f.cam[1] = -38.5f;
        f.cam[2] = 17.0f;
        f.floats = true;
        f.frame = 999;
        book.Fact(77, f);
        std::string text;
        Expect(book.FactsText(77, text) && !book.FactsText(78, text) &&
                   text.size() <= A::LineChars,
               "actors: facts line");
        book.FactsText(77, text);
        Expect(text.find("100000 vertices") != std::string::npos &&
                   text.find("slot 41") != std::string::npos &&
                   text.find("6a833138") != std::string::npos,
               "actors: facts text");
    }
    if (failures == 0) {
        std::printf("wind hang actors: all passed\n");
        return 0;
    }
    std::printf("wind hang actors: %d failed\n", failures);
    return 1;
}
''',
}

# ---- vk_rasterizer.h -------------------------------------------------------------------------------
H1 = r'''#include "bbport_wind_hang_still.h" // bbport (r112d_hang-still-test)
'''
H2 = r'''#include "bbport_wind_hang_actors.h" // bbport (r112h_hang-not-the-hunter)
'''
H3 = r'''    bool hang_judge = false; // set by WindHangVerdict: this draw's stream wants the judging word
'''
H4 = r'''    /// bbport (r112h_hang-not-the-hunter): who may hang: the tests, the hunter, the facts of the judging
    /// draws, the sway words lost for want of a motion parameter
    BbWindHangActors::Book hang_actors;
'''
H5 = r'''    bool WindHangVerdict(const GraphicsPipeline* pipeline, u64 positions, u32 positions_size);
'''
H6 = r'''    /// bbport (r112h_hang-not-the-hunter): a stream whose box keys read as still: may it hang (not the
    /// hunter's gear, not a figure, not indoors, placed)? False: it is refused and held as moving.
    bool WindHangActorsClear(u64 positions, u64 frame);
'''

# ---- vk_rasterizer.cpp -----------------------------------------------------------------------------
C1 = r'''            .sway = sway,     // bbport (r89_wind-foliage-sway)
        });
'''
C2 = r'''        if (sway != 0 && dc.push_data.motion_param == 0) { // bbport (r112h_hang-not-the-hunter)
            ++hang_actors.no_param; // the word got no motion parameter: it never reaches the shader
        }
'''

# ---- vk_rasterizer_effects.cpp ---------------------------------------------------------------------
E1 = r'''#include <xxhash.h>
'''
E2 = r'''#include "engine/engine_state.h" // bbport (r112h_hang-not-the-hunter): the hunter's position
'''
E3 = r'''        switch (hang_box.Step(positions, positions_size, taken.slot, taken.reset, frame, words)) {
        case BbWindHangStill::BoxState::Judging: // a hang word with no motion: the keys fill
            return BbWindHang::HangWord(frame_slot, view, taken.slot, 0);
        case BbWindHangStill::BoxState::Still:
            ++hang_stats.still;
            hang = true;
            break;
'''
E4 = r'''        // bbport (r112h_hang-not-the-hunter): a give-up holds the stream for a long time (0: r112g's)
        hang_box.SetKeylessHold(BbWindHangActors::KnobOnce().on
                                    ? BbWindHangActors::KeylessHoldFrames
                                    : std::uint64_t{0});
        switch (hang_box.Step(positions, positions_size, taken.slot, taken.reset, frame, words)) {
        case BbWindHangStill::BoxState::Judging: { // a hang word with no motion: the keys fill
            const u32 word = BbWindHang::HangWord(frame_slot, view, taken.slot, 0);
            if (BbWindHangActors::KnobOnce().on) {
                // bbport (r112h_hang-not-the-hunter): what this draw had, for the give-up's facts
                const u32* const view_words = words + BbWindSway::ViewAt(frame_slot, view);
                BbWindHangActors::Facts facts;
                facts.vs = static_cast<u32>(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash &
                                            0xffffffffu);
                facts.size = positions_size;
                facts.stride = positions_stride;
                facts.slot = taken.slot;
                facts.view = view;
                facts.views = sway_views;
                facts.word = word;
                facts.cam[0] = std::bit_cast<float>(view_words[BbWindSway::WindE + 2]);
                facts.cam[1] = std::bit_cast<float>(view_words[BbWindSway::WindA + 2]);
                facts.cam[2] = std::bit_cast<float>(view_words[BbWindSway::WindE + 3]);
                facts.floats = positions_floats;
                facts.frame = frame;
                hang_actors.Fact(positions, facts);
            }
            return word;
        }
        case BbWindHangStill::BoxState::Still:
            if (!WindHangActorsClear(positions, frame)) { // bbport (r112h_hang-not-the-hunter)
                return 0;
            }
            ++hang_stats.still;
            hang = true;
            break;
'''
E5 = r'''// bbport (r112b_hang-probe, TOOL): the first bone palette (stride 16, Skeleton size: the buffer
'''
E6 = r'''// bbport (r112h_hang-not-the-hunter): a stream whose box keys first read as still in this GPU-judge
// window (once a window: its answer is kept): may it hang? Not when its palette has more bones than a
// lantern's (a figure's rig: the hunter's gear pieces have 28), not when its world box lies on the hunter
// (BbEngine::world_player_position), not when it is not placed (no box keys) or the hunter is unread, not
// when the camera is indoors by r117's field (CameraOpen). A refused stream is held as moving
// (BoxBook::Reject), judged again later with a new window. See bbport_wind_hang_actors.h. On the thread
// recording draws; BB_WIND_HANG_ACTORS=0: true at once (r112g).
bool Rasterizer::WindHangActorsClear(u64 positions, u64 frame) {
    namespace A = BbWindHangActors;
    const A::Knobs& knobs = A::KnobOnce();
    if (!knobs.on) {
        return true;
    }
    const BbWindHangStill::BoxEntry* const box = hang_box.Find(positions);
    if (box != nullptr && hang_actors.Cleared(positions, box->started)) {
        return true;
    }
    A::Hunter& hunter = hang_actors.hunter;
    if (hunter.frame != frame) { // the hunter, once a frame at most, only when a stream is tested
        hunter.frame = frame;
        float pos[3] = {};
        hunter.known = BbEngine::world_player_position(pos) && A::Finite3(pos);
        if (hunter.known) {
            hunter.x = pos[0];
            hunter.y = pos[1];
            hunter.z = pos[2];
            ++hang_actors.hunter_read;
        } else {
            ++hang_actors.hunter_unread;
        }
    }
    const BbWindHangStill::Entry* const palette = hang_still.Find(positions);
    const unsigned bones = palette != nullptr ? palette->bones : 0u;
    const bool have_field = wind_shelter != nullptr;
    const float open = have_field ? wind_shelter->CameraOpen() : 1.0f;
    float side = -1.0f;
    const A::Why why = A::Judge(knobs, box, bones, hunter, open, have_field, &side);
    BbWindHang::Entry* const entry = hang_book.Find(positions);
    A::Seen seen;
    seen.vs = entry != nullptr ? static_cast<u32>(entry->vs & 0xffffffffu) : 0u;
    seen.bones = bones;
    if (box != nullptr) {
        seen.height = box->snap.crown - box->snap.base;
        seen.top = box->snap.crown;
        seen.window = box->started;
    }
    seen.side = side;
    seen.why = why;
    seen.frame = frame;
    hang_actors.Note(positions, seen);
    if (why == A::Why::Ok) {
        return true;
    }
    hang_box.Reject(positions, frame, A::HoldOf(why));
    if (entry != nullptr) {
        entry->moving = true;
    }
    return false;
}

'''
E7 = r'''    // bbport (r112g_hang-judge-settles): its line once (BB_WIND_HANG on)
'''
E8 = r'''    // bbport (r112h_hang-not-the-hunter): its line once (BB_WIND_HANG on)
    static bool hang_actors_said = false;
    if (!hang_actors_said && BbWindHang::KnobOnce().on) {
        hang_actors_said = true;
        const BbWindHangActors::Knobs& actors = BbWindHangActors::KnobOnce();
        if (actors.on) {
            BbReport::Printf("Wind sway hang (r112h): not on the hunter (within %.1f m, "
                             "BB_WIND_HANG_NEAR), not a figure (over %u bones, BB_WIND_HANG_BONES), "
                             "not indoors (open wind share at the camera %.2f or less, "
                             "BB_WIND_HANG_INDOOR), placed; keyless streams held %u frames; lines "
                             "every %u frames\n",
                             double(actors.near_m), actors.bones, double(actors.indoor),
                             static_cast<unsigned>(BbWindHangActors::KeylessHoldFrames),
                             BbWindSway::ReportFrames);
        } else {
            BbReport::Printf("Wind sway hang (r112h): OFF (BB_WIND_HANG_ACTORS=0): as r112g\n");
        }
    }
'''
E9 = r'''        hang_box.ClearNotes();
'''
E10 = r'''        if (BbWindHangActors::KnobOnce().on) {
            // bbport (r112h_hang-not-the-hunter): the facts of each keyless give-up, then its lines
            std::string fact_line;
            for (const BbWindHangStill::GiveUpNote& note : hang_box.Notes()) {
                if (hang_actors.FactsText(note.stream, fact_line)) {
                    BbReport::Printf("%s\n", fact_line.c_str());
                }
            }
            std::string first_line, second_line;
            hang_actors.Lines(object_motion->Frame(), wind_shelter != nullptr,
                              hang_box.Keyless(object_motion->Frame()), first_line, second_line);
            BbReport::Printf("%s\n%s\n", first_line.c_str(), second_line.c_str());
        }
'''

# ---- bbport_wind_hang_still.h ----------------------------------------------------------------------
N1 = r'''    float dev = 0.0f; ///< the greatest change from `snap` seen (m); -1 when no key was ever offered
'''
N2 = r'''    // bbport (r112h_hang-not-the-hunter): -2 above when refused as the hunter's, a figure's, indoors
    std::uint64_t hold = 0; ///< frames it is held as moving before Due says so; 0: RejudgeFrames
    bool keyless = false;   ///< it gave up with no key offered
'''
N3 = r'''            found->second.dev >= BoxFinal || found->second.settled + RejudgeFrames > frame) {
'''
N4 = r'''            found->second.dev >= BoxFinal ||
            found->second.settled +
                    (found->second.hold != 0 ? found->second.hold : RejudgeFrames) > frame) {
'''
N5 = r'''        e.dev = -1.0f;
        Settle(e, frame);
        ++stats.gave_up;
'''
N6 = r'''        e.dev = -1.0f;
        e.keyless = true; // bbport (r112h_hang-not-the-hunter): held keyless_hold frames (0: as before)
        e.hold = keyless_hold;
        Settle(e, frame);
        ++stats.gave_up;
'''
N7 = r'''    /// The notes of give-ups since the last ClearNotes (at most NotesMost; Counts().gave_up counts
'''
N8 = r'''    /// bbport (r112h_hang-not-the-hunter): `stream` may not hang (the hunter's gear, a figure,
    /// indoors, unplaced): moved at once (dev -2, not final), judged again `hold` frames later (Due).
    /// False when the stream is not known.
    bool Reject(std::uint64_t stream, std::uint64_t frame, std::uint64_t hold) {
        const auto found = entries.find(stream);
        if (found == entries.end()) {
            return false;
        }
        found->second.dev = -2.0f;
        found->second.hold = hold;
        Settle(found->second, frame);
        return true;
    }

    /// bbport (r112h_hang-not-the-hunter): the frames a give-up holds its stream (0: RejudgeFrames,
    /// as r112g).
    void SetKeylessHold(std::uint64_t frames) {
        keyless_hold = frames;
    }

    /// bbport (r112h_hang-not-the-hunter): the streams drawn within SeenFrames that gave up with no key
    /// offered and are still held.
    [[nodiscard]] unsigned Keyless(std::uint64_t frame) const {
        unsigned count = 0;
        for (const auto& item : entries) {
            const BoxEntry& e = item.second;
            count += e.keyless && e.state == BoxState::Moved && e.seen + SeenFrames >= frame ? 1u : 0u;
        }
        return count;
    }

'''
N9 = r'''    std::vector<GiveUpNote> notes; // bbport (r112g_hang-judge-settles): at most NotesMost
'''
N10 = r'''    std::uint64_t keyless_hold = 0; // bbport (r112h_hang-not-the-hunter): see SetKeylessHold
'''

# ---- build files and README ------------------------------------------------------------------------
M1 = r'''target_include_directories(wind-hang-still-test PRIVATE ..)
'''
M2 = r'''# bbport (r112h_hang-not-the-hunter): who may hang (shim/bbport_wind_hang_actors.h); also built and run
# by engine/build.sh --test.
add_executable(wind-hang-actors-test EXCLUDE_FROM_ALL ../tests/test_wind_hang_actors.cpp)
target_compile_options(wind-hang-actors-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-hang-actors-test PRIVATE ..)
'''
B1 = r'''    out/wind-hang-still-test
'''
B2 = r'''    # bbport (r112h_hang-not-the-hunter): who may hang (the hunter's gear, figures, indoors, keyless)
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_wind_hang_actors.cpp -o out/wind-hang-actors-test
    out/wind-hang-actors-test
'''
R1 = r'''| `BB_WIND_HANG_BOX_TOL` | A TEST setting'''
R2 = r'''| `BB_WIND_HANG_ACTORS` | Part of `BB_WIND_HANG` (r112h; `0` leaves it out and gives back r112g's rule, any other text or unset is on; it does nothing without `BB_WIND_HANG=1`). A stream the GPU judge found standing still may hang only if it is not the hunter's own gear or a figure (more than 24 bones in its palette, `BB_WIND_HANG_BONES` 1 to 96: the hunter's gear pieces have 28), not on the hunter (its world box within `BB_WIND_HANG_NEAR` metres, default 1.5, 0 turns it off, of his position as the game keeps it, and overlapping 1.5 m under to 2.5 m over it; the position unread: nothing hangs), placed (the box keys came) and not indoors (the open share of the wind at the camera, r117's field, at or under `BB_WIND_HANG_INDOOR`, default 0.1, 0 turns it off; the rule needs `BB_WIND_SHELTER` on and an upscaler). It is tested once per judging window of a stream; a refused stream is held as moving for 1800 frames (a figure, on the hunter) or 300 and then judged again. A stream the GPU never gave a key (the `no key offered` notes) is held 7200 frames after a give-up instead of 300, and the notes are followed by a `keyless stream` line with the draw's vertex shader, vertex count, stride, slot, view and camera. Two `Wind sway hang (r112h)` lines every 600 frames: the hunter, the tests by reason, the keyless streams, the sway words lost for want of a motion parameter, and the meshes kept and refused (up to three of each: hash, height, top y, bones, sideways distance from the hunter, reason). Cost: nothing with `BB_WIND_HANG` unset; on, one small record per judging draw, one test per stream window, one compare per motion draw. |
'''

EDITS = {
RH: [
('ins', H1, "", H2),
('ins', H3, "", H4),
('ins', H5, "", H6),
],
RC: [
('ins', C1, "", C2),
],
RE: [
('ins', E1, "", E2),
('rep', E3, "", E4),
('ins', E5, E6, ""),
('ins', E7, E8, ""),
('ins', E9, E10, ""),
],
NH: [
('ins', N1, "", N2),
('rep', N3, "", N4),
('rep', N5, "", N6),
('ins', N7, N8, ""),
('ins', N9, "", N10),
],
CM: [
('ins', M1, "", M2),
],
BS: [
('ins', B1, "", B2),
],
RM: [
('ins', R1, R2, ""),
],
}

ORDER = (RH, RC, RE, NH, CM, BS, RM)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def parts_of(ed):
    if ed[0] == "rep":
        return ed[1], [ed[3]], [ed[1]]
    return ed[1], [t for t in (ed[2], ed[3]) if t], []


def state_of(cur, eds, path):
    done = todo = 0
    for ed in eds:
        anchor, present, absent = parts_of(ed)
        if ed[0] == "rep":
            n_old, n_new = cur.count(anchor), cur.count(present[0])
            if n_new == 1 and n_old == 0:
                done += 1
            elif n_old == 1 and n_new == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times (wanted once), new text %d "
                                 "times: %r" % (path, n_old, n_new, anchor[:70]))
            continue
        na, counts = cur.count(anchor), [cur.count(t) for t in present]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s "
                             "times: %r" % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_edits(cur, eds):
    for ed in eds:
        if ed[0] == "rep":
            cur = cur.replace(ed[1], ed[3], 1)
        else:
            cur = cur.replace(ed[1], ed[2] + ed[1] + ed[3], 1)
    return cur


def revert_edits(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "rep":
            cur = cur.replace(ed[3], ed[1], 1)
        else:
            for part in (ed[3], ed[2]):
                if part:
                    cur = cur.replace(part, "", 1)
    return cur


def new_state():
    states = set()
    for path, text in NEW_FILES.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            states.add("clean")
            continue
        got = open(full, "rb").read().decode("utf-8").replace("\r\n", "\n")
        if got != text:
            raise SystemExit("REFUSED: %s exists and is not this patch's file" % path)
        states.add("applied")
    if len(states) != 1:
        raise SystemExit("mixed state: some of the new files exist")
    return states.pop()


def text_checks(texts):
    """The ties a compiler cannot check."""
    re_ = texts[RE]
    a = re_.find("bool Rasterizer::WindHangVerdict(")
    j = re_.find("hang_box.SetKeylessHold(")
    s = re_.find("WindHangActorsClear(positions, frame)")
    if not (0 <= j < s):
        raise SystemExit("text check: the Judging/Still edits are not in order")
    d = re_.find("bool Rasterizer::WindHangActorsClear(")
    p = re_.find("// bbport (r112b_hang-probe, TOOL): the first bone palette")
    if not (0 <= a < d < p):
        raise SystemExit("text check: WindHangActorsClear is not between WindHangVerdict and the probe")
    o = re_.find("hang_actors_said = true;")
    r = re_.find("if (!on || ++sway_frames % BbWindSway::ReportFrames != 0) {", o)
    if not (0 <= o < r):
        raise SystemExit("text check: the once-line is not before the report's frame test")
    n = re_.find("for (const BbWindHangStill::GiveUpNote& note : hang_box.Notes()) {")
    f = re_.find("hang_actors.FactsText(note.stream, fact_line)")
    c = re_.find("hang_box.ClearNotes();")
    if not (0 <= n < f < c):
        raise SystemExit("text check: the facts loop is not between the notes loop and ClearNotes")
    for path in (RH, RC, RE, NH, CM, BS):
        for ed in EDITS[path]:
            for part in (ed[3:] if ed[0] == "rep" else ed[2:]):
                for line in part.split("\n"):
                    if len(line) > 106 and path not in (CM, BS):
                        raise SystemExit("text check: %s: a new line over 106 columns: %r" %
                                         (path, line[:60]))
    for path, text in NEW_FILES.items():
        if not text.isascii() or "\t" in text or "\r" in text:
            raise SystemExit("text check: %s is not plain ASCII without tabs" % path)
        if text.count("{") != text.count("}") or text.count("(") != text.count(")"):
            raise SystemExit("text check: %s: braces or parentheses do not balance" % path)
    for path in (RH, RC, RE, NH):
        # the edits' own net change in braces and parentheses must be zero (the files hold comments
        # with unbalanced ones, so only the difference between the new and the old text counts)
        for ed in EDITS[path]:
            added = "".join(ed[2:]) if ed[0] == "ins" else ed[3]
            gone = ed[1] if ed[0] == "rep" else ""
            for open_, close in (("{", "}"), ("(", ")")):
                if added.count(open_) - added.count(close) != gone.count(open_) - gone.count(close):
                    raise SystemExit("text check: %s: an edit changes the balance of %s%s: %r" %
                                     (path, open_, close, (ed[1] if ed[0] == "rep" else added)[:60]))
    for want in ("bool Reject(", "void SetKeylessHold(", "unsigned Keyless(", "bool keyless = false;",
                 "std::uint64_t keyless_hold = 0;"):
        if want not in texts[NH]:
            raise SystemExit("text check: %r is missing in the judge's header" % want)
    if texts[RM].count("| `BB_WIND_HANG_ACTORS` |") != 1:
        raise SystemExit("text check: README's BB_WIND_HANG_ACTORS row is not there once")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112H_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == NH and "bool HoldsMoved(" not in cur:
            raise SystemExit("REFUSED: r112g_hang-judge-settles is not applied (no HoldsMoved)")
        if path == RE and "hang_box.HoldsMoved(positions)" not in cur:
            raise SystemExit("REFUSED: r112g_hang-judge-settles is not applied (WindHangVerdict)")
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
    states.add(new_state())
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_edits(cur, eds)
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
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the "
                  "result pass)" % (len(plan), sum(len(p[1]) for p in plan), len(NEW_FILES)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r112htmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path, text in NEW_FILES.items():
            full = os.path.join(ROOT, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            tmp = full + ".r112htmp"
            open(tmp, "wb").write(text.replace("\n", "\r\n").encode("utf-8"))
            os.replace(tmp, full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_edits(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r112htmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


if __name__ == "__main__":
    main()
