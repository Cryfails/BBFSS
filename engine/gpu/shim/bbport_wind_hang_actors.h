// SPDX-License-Identifier: GPL-3.0-or-later
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
