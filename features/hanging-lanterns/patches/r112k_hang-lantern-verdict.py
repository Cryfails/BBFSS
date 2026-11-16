# r112k_hang-lantern-verdict: FEATURE fix on top of r112j_hang-static-verts (r112i, r112h, r112g, r112f, r112e, r112 and
# r89i, all applied in the tree), behind r112's own knob BB_WIND_HANG=1 (off by default). Parts marked TOOL are test
# aids of the survey (BB_WIND_HANG_FIND=1) and a live knob guarded by the test tools' header (as r89d's twig knob):
# they go to dev/test-tools; the rest is the feature. No new file, no shader change: seven files edited
# (bbport_wind_hang_find.h, bbport_wind_hang.h, test_wind_hang_find.cpp, vk_rasterizer.h, vk_rasterizer.cpp,
# vk_rasterizer_effects.cpp, README.md).
#
# THE EVIDENCE (b50: slot_b50_result.txt, b50_s5.log graveyard, b50_s2.log alley, b50_reports.txt)
#  - The survey lists the 97f2d384 lanterns (graveyard C 1429 verts 0.21 m, D 2491 verts 0.88 m, both FREE 6.3 m up) with
#    "book -": NO verdict of the static book exists for them. A "standing refusal" cannot be what keeps them out; the
#    book holds an entry only for a stream the static path was ASKED about (WindHangStaticAllowed), so no draw of those
#    streams ever reached the static path. The route to the path is the rasterizer's Motion block: only a draw of
#    Motion::Kind::Other (a small bone palette the CPU reads) with the sway bit and no discard was offered (r112i). b48's
#    census line says what the other draws are: 65 draws a frame of sway pipelines in the graveyard are
#    Motion::Kind::GpuPalette (a small bone palette in memory the GPU writes: the game's per-instance data), which only
#    r89i's twig rule saw. The survey's lanterns carry a palette (pal 1), the book's candidates are the few that read a
#    palette on the CPU. Most likely cause (NOT proven by a log: the route tail below proves it in the next run): the
#    lanterns' draws are Kind::GpuPalette.
#  - The one static candidate (vs 6a833138, 1338 verts, scene box 0.89 m) reached the GPU judge and was kept by r112h, then
#    refused by the height rule: "left out by height vs 6a833138 4.68 m (top y -29.6)", "1 over 4.0 m". The keys of a slot
#    are the least and greatest world y of every draw of the stream: a mesh drawn at several places (instances) spans the
#    union of them. r112 stops a hanging thing at 4 m: 4.68 m is the union of the lantern's places, not its own height.
#  - A SKINNED stream (63220f67, "SKINNED idx 9615 verts 4421", 1.57 m, drawn at many places) is in the static book as a
#    candidate: its scene entry carries the skinned flag (a skeleton draws it in another pass; sticky), which Evaluate
#    never looked at.
#  - "push 0.000 m" in r112's line is not a wind speed: it prints the follower's last table sample (hang_push.Now()), and
#    that table is filled only by the first PUSHED draw of a frame (WindHangWord). With 0 pushed it is its initial 0. The
#    amplitude source is fine (BB_WIND_SWAY 3 x 0.15 m x (4/4)^2 x gust^2 = 0.45 m at gust 1, held to 0.4 m, scaled by the
#    lantern's own height / 1.2 m).
#
# WHAT THIS CHANGES
#  (1) THE ROUTE (feature, BB_WIND_HANG_STATIC_GPU, default 1; 0 = r112j): vk_rasterizer.cpp's routing clause of the static
#      path offers a Kind::GpuPalette draw too, when its pipeline passes Wanted (sway bit, no discard) AND its stream has a
#      standing static-book verdict "candidate" or gets one now (Rasterizer::WindHangGpuStatic: the position attribute's
#      stream, a Peek of the book, else WindHangStaticAllowed: box, size, ground rules as for any static stream). A GPU-
#      palette draw that is no candidate falls through to r89i's twig rule as before (nothing is taken from the twigs
#      unless its stream is a hanging candidate).
#  (2) SKINNED STREAMS STAY OUT: Why::Skinned (new reason "skinned"): Evaluate refuses a stream whose scene box says a
#      skeleton draws it (Box::skinned, held 1800 frames); the box set's refresh (every 60 frames, now asked on every
#      static draw, a lookup when fresh) takes a standing candidate back when its box has the flag since
#      (StaticBook::DropSkinned: also off the candidates list).
#  (3) THE UNION: a static candidate's keys may span up to BB_WIND_HANG_STATIC_UNION m (default 12, 4 to 40) instead of
#      r112's 4 m: BbWindHang::Measure got max_extent (default MaxExtent: every other caller is as before) and
#      WindHangWord passes the union limit for a stream the static book holds as a candidate. The shaders are not
#      changed: their scale and still top come from the same keys (a union taller than 1.2 m: scale 1).
#  (4) THE PUSH LINE: "Wind sway hang (r112k)" prints the push's source (wind speed, gust, drive, amplitude at gust 1, the
#      amplitude now held to MaxAlong, a 0.9 m lantern's bottom) from the wind snapshot, with the note that r112's "push"
#      stays 0 until a table is filled (nothing pushed yet); and the candidates' measures (scene height, keys' extent,
#      fits or not).
#  (5) TOOL: the survey (BB_WIND_HANG_FIND=1) prints after each line the stream's ROUTE in the Motion block: kind
#      (S skinned, P GPU palette, O other), sway bit, discard, draws, swayed (got a word), delivered (the word reached the
#      motion parameter), asked (reached the static path), passed (a candidate); "route none" = no draw of it reached the
#      Motion block at all (only passes without it draw it). BB_WIND_HANG_FOCUS=<hex vertex shader hash> (the survey's
#      "vs", e.g. 97f2d384) lists its meshes first, hanging or not ("[focus]"). Lines may be 480 characters (LineCharsK).
#      TOOL: a live knob BB_WIND_HANG_PUSH (the test tools' set:/unset:; guarded by the same header test as r89d's twig
#      knob): "0" gives every hang word a ramp of 0 at once (nothing pushed, nothing else changes), unset: back to normal:
#      the same-camera A/B in one game. BB_WIND_HANG itself is read once (it decides pipeline keys and shaders) and
#      cannot be live.
#
# Off: BB_WIND_HANG unset: every new path sits behind BbWindHangFind::GpuOn()/FindOn() or in the hang path that only runs
# with BB_WIND_HANG=1 (the routing clause's new arm tests the draw's kind and Wanted first, then GpuOn inside
# WindHangGpuStatic; the survey hook is `if (FindOn())` = one static bool; the report lines are inside the hang blocks;
# the live knob is read only in WindHangWord). BB_WIND_HANG_STATIC_GPU=0 gives r112j's routing; UNION is only read for a
# candidate; FOCUS/FIND unset leave the tool parts out.
# Cost: a GPU-palette sway draw (65 a frame in the graveyard, hang on only) does one fetch walk and one hash lookup in
# the static book (the verdict path of a new stream as before); the box set is refreshed every 60 frames at most (a read
# of the ray traced scene's entries as for a new stream, a few hundred, ~50 us) and swept for skinned boxes (a lookup per
# skinned box); the survey hook (TOOL) one map lookup a Motion-block draw. GPU: none added (the same pipelines). Memory: the
# routes (TOOL) 4096 x 40 bytes at most.
#
# Use: python -I -X utf8 r112k_hang-lantern-verdict.py check | apply | revert
# Root: R112K_ROOT, else <tree>. CRLF kept. apply backs the originals up in r112k_backup next to this script;
# revert takes out exactly what apply put in. Needs r112j applied (and r89i: the routing clause below it).
import os, re, sys

ROOT = os.environ.get("R112K_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112k_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RE = RV + "vk_rasterizer_effects.cpp"
RH = RV + "vk_rasterizer.h"
RC = RV + "vk_rasterizer.cpp"
NF = "engine/gpu/shim/bbport_wind_hang_find.h"
NH = "engine/gpu/shim/bbport_wind_hang.h"
NT = "engine/tests/test_wind_hang_find.cpp"
RM = "README.md"

# ---- bbport_wind_hang_find.h -----------------------------------------------------------------------
F1 = r"""enum class Why : std::uint8_t { Ok, TooBig, NoBox, Shape, NoGround, Grounded };
inline constexpr std::size_t WhyCount = 6;
"""
F1N = r"""enum class Why : std::uint8_t { Ok, TooBig, NoBox, Shape, NoGround, Grounded, Skinned };
inline constexpr std::size_t WhyCount = 7; // bbport (r112k_hang-lantern-verdict): Skinned
"""

F2 = r"""    case Why::Grounded:
        return "grounded";
    }
"""
F2N = r"""    case Why::Grounded:
        return "grounded";
    case Why::Skinned: // bbport (r112k_hang-lantern-verdict)
        return "skinned";
    }
"""

F3 = r"""inline constexpr std::size_t TakenMost = 6, TakenChars = 300; // bbport (r112j_hang-static-verts)
"""
F3N = r"""// bbport (r112k_hang-lantern-verdict): the survey's lines may be this long (the route's tail needs more than r112j's
// LineChars), the routes kept at most, how long a skinned refusal stands (frames), the most a static candidate's keys
// may span by default (m: the union of the places a mesh is drawn at) and at most
inline constexpr std::size_t LineCharsK = 480, RoutesMost = 4096;
inline constexpr std::uint64_t HoldSkinned = 1800;
inline constexpr float UnionDefault = 12.0f, UnionMax = 40.0f;
"""

F4 = r"""    float clear = ClearDefault;
};
"""
F4N = r"""    float clear = ClearDefault;
    std::uint32_t focus = 0; ///< bbport (r112k): BB_WIND_HANG_FOCUS: a vertex shader hash (hex) the survey lists first
};
"""

F5 = r"""/// The knobs, read once.
[[nodiscard]] inline const Knobs& KnobOnce() {
    static const Knobs k =
        ParseKnobs(std::getenv("BB_WIND_HANG_STATIC"), std::getenv("BB_WIND_HANG_FIND"),
                   std::getenv("BB_WIND_HANG_STATIC_VERTS"),
                   std::getenv("BB_WIND_HANG_STATIC_HEIGHT"),
                   std::getenv("BB_WIND_HANG_STATIC_CLEAR"));
    return k;
}
"""
F5N = r"""/// bbport (r112k_hang-lantern-verdict): BB_WIND_HANG_FOCUS: a vertex shader hash in hex (the survey's "vs"); 0 (no
/// text, an empty one or one that is no hex number) lists none first.
[[nodiscard]] inline std::uint32_t ParseFocus(const char* text) {
    if (text == nullptr || text[0] == 0) {
        return 0;
    }
    char* end = nullptr;
    const unsigned long value = std::strtoul(text, &end, 16);
    if (end == text || *end != 0) {
        return 0;
    }
    return static_cast<std::uint32_t>(value & 0xffffffffu);
}

[[nodiscard]] inline Knobs WithFocus(Knobs k, const char* focus) {
    k.focus = ParseFocus(focus);
    return k;
}

/// The knobs, read once.
[[nodiscard]] inline const Knobs& KnobOnce() {
    static const Knobs k = WithFocus(
        ParseKnobs(std::getenv("BB_WIND_HANG_STATIC"), std::getenv("BB_WIND_HANG_FIND"),
                   std::getenv("BB_WIND_HANG_STATIC_VERTS"),
                   std::getenv("BB_WIND_HANG_STATIC_HEIGHT"),
                   std::getenv("BB_WIND_HANG_STATIC_CLEAR")),
        std::getenv("BB_WIND_HANG_FOCUS"));
    return k;
}
"""

F6 = r"""/// The survey is on: BB_WIND_HANG on and BB_WIND_HANG_FIND=1.
"""
F6P = r"""// bbport (r112k_hang-lantern-verdict): BB_WIND_HANG_STATIC_GPU (default on; exactly 0 = r112j): a draw of an opaque
// pipeline with the Sway bit whose small bone palette the GPU writes (Motion::Kind::GpuPalette) goes to the static path
// too, when its stream's standing verdict is a candidate (r112i and r112j offered only Kind::Other draws, the ones whose
// palette the CPU reads: the lanterns of the graveyard were never asked).
[[nodiscard]] inline bool ParseGpu(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == 0);
}

[[nodiscard]] inline bool GpuKnob() {
    static const bool on = ParseGpu(std::getenv("BB_WIND_HANG_STATIC_GPU"));
    return on;
}

/// The GPU-palette route is on: the static path is, and BB_WIND_HANG_STATIC_GPU is not 0.
[[nodiscard]] inline bool GpuOn() {
    return StaticOn() && GpuKnob();
}

// bbport (r112k): BB_WIND_HANG_STATIC_UNION (m, UnionDefault, held to MaxExtent..UnionMax): the most the keys of a static
// candidate may span (a mesh drawn at several places spans the union of them; r112 stopped every hanging thing at 4 m).
[[nodiscard]] inline float ParseUnion(const char* text) {
    return std::clamp(BbWindSway::ParseNumber(text, UnionDefault), H::MaxExtent, UnionMax);
}

[[nodiscard]] inline float UnionKnob() {
    static const float span = ParseUnion(std::getenv("BB_WIND_HANG_STATIC_UNION"));
    return span;
}

"""

F7 = r"""    std::uint64_t judged = 0;    ///< a stream got a new verdict
"""
F7N = r"""    std::uint64_t gpu_asked = 0;  ///< bbport (r112k): draws of GPU-palette streams of opaque sway pipelines asked about
    std::uint64_t gpu_passed = 0; ///< bbport (r112k): and those of a candidate stream (sent on to the static path)
"""

F8 = r"""/// Counts of the static path's draws since the last line.
"""
F8P = r"""/// bbport (r112k_hang-lantern-verdict, TOOL grade with BB_WIND_HANG_FIND=1): what the rasterizer's Motion block made
/// of the draws of a stream (by the address of its position attribute): the kind of the draws (S skinned, P GPU
/// palette, O other), whether the pipeline has the Sway bit and a pixel shader that discards, how many draws, how many
/// got a sway word, how many of those words reached the motion parameter, and how many were asked of the static path
/// and passed as a candidate. The survey prints it after the stream's line: a stream with no route was drawn by no pass
/// that has the Motion block.
struct Route {
    char kind = '?';
    bool sway_bit = false, discards = false;
    std::uint32_t draws = 0, swayed = 0, delivered = 0, asked = 0, passed = 0;
    std::uint64_t frame = 0;
};

class Routes {
public:
    std::uint64_t dropped = 0; ///< streams not kept for want of room

    void Note(std::uint64_t stream, char kind, bool sway_bit, bool discards, bool swayed, bool delivered,
              std::uint64_t frame) {
        Route* const r = Slot(stream);
        if (r == nullptr) {
            return;
        }
        r->kind = kind;
        r->sway_bit = sway_bit;
        r->discards = discards;
        ++r->draws;
        r->swayed += swayed ? 1u : 0u;
        r->delivered += delivered ? 1u : 0u;
        r->frame = frame;
    }

    /// The static path judged a draw of the stream: `pass` = a candidate.
    void Asked(std::uint64_t stream, bool pass) {
        Route* const r = Slot(stream);
        if (r == nullptr) {
            return;
        }
        ++r->asked;
        r->passed += pass ? 1u : 0u;
    }

    [[nodiscard]] const Route* Find(std::uint64_t stream) const {
        const auto found = routes.find(stream);
        return found == routes.end() ? nullptr : &found->second;
    }

    [[nodiscard]] std::size_t Size() const {
        return routes.size();
    }

private:
    Route* Slot(std::uint64_t stream) {
        if (stream == 0) {
            return nullptr;
        }
        const auto found = routes.find(stream);
        if (found != routes.end()) {
            return &found->second;
        }
        if (routes.size() >= RoutesMost) {
            ++dropped;
            return nullptr;
        }
        return &routes[stream];
    }

    std::unordered_map<std::uint64_t, Route> routes;
};

"""

F9 = r"""    e.height = HeightOf(b->box);
"""
F9P = r"""    if (b->skinned) { // bbport (r112k_hang-lantern-verdict): a skeleton draws it (r112's path); never the static book's
        e.why = Why::Skinned;
        e.until = frame + HoldSkinned;
        return e;
    }
"""

F10 = r"""    [[nodiscard]] const Entry* Find(std::uint64_t stream) const {
        const auto found = entries.find(stream);
        return found == entries.end() ? nullptr : &found->second;
    }
"""
F10P = r"""    /// bbport (r112k_hang-lantern-verdict): a standing candidate whose box in the scene carries the skinned flag (a
    /// verdict made before a skeleton draw of the stream was seen) is refused from now on and leaves the list.
    void DropSkinned(const std::vector<Box>& boxes, std::uint64_t frame) {
        for (const Box& b : boxes) {
            if (!b.skinned || b.stream == 0) {
                continue;
            }
            const auto found = entries.find(b.stream);
            if (found == entries.end() || found->second.why != Why::Ok) {
                continue;
            }
            found->second.why = Why::Skinned;
            found->second.until = frame + HoldSkinned;
            ++skinned_dropped;
            ++by_why[static_cast<std::size_t>(Why::Skinned)];
            const std::uint64_t stream = b.stream;
            taken.erase(std::remove_if(taken.begin(), taken.end(),
                                       [stream](const Taken& t) { return t.stream == stream; }),
                        taken.end());
        }
    }

    std::uint64_t skinned_dropped = 0; ///< bbport (r112k): candidates taken back by DropSkinned

"""

F11 = r"""    if (out.size() > LineChars) {
        out.resize(LineChars - 3);
"""
F11N = r"""    if (out.size() > LineCharsK) { // bbport (r112k): was LineChars
        out.resize(LineCharsK - 3);
"""

F12 = r"""/// The survey: a header line and up to ListMost candidate lines (a mesh of the scene of
"""
F12P = r"""/// bbport (r112k_hang-lantern-verdict, TOOL grade): the route text after a survey line: what the Motion block made of
/// the draws of the stream (Routes), "[focus]" when its vertex shader is BB_WIND_HANG_FOCUS's. Only the focus mark
/// without routes (the tests' calls).
[[nodiscard]] inline std::string RouteText(const Routes* routes, std::uint64_t stream, bool focus) {
    if (routes == nullptr) {
        return focus ? std::string(" [focus]") : std::string();
    }
    char buf[200];
    const Route* const r = routes->Find(stream);
    if (r == nullptr) {
        std::snprintf(buf, sizeof(buf), "%s; route none (no draw of it reached the Motion block)",
                      focus ? " [focus]" : "");
    } else {
        std::snprintf(buf, sizeof(buf),
                      "%s; route %c bit %d disc %d draws %u swayed %u delivered %u asked %u passed %u",
                      focus ? " [focus]" : "", r->kind, r->sway_bit ? 1 : 0, r->discards ? 1 : 0,
                      static_cast<unsigned>(r->draws), static_cast<unsigned>(r->swayed),
                      static_cast<unsigned>(r->delivered), static_cast<unsigned>(r->asked),
                      static_cast<unsigned>(r->passed));
    }
    return std::string(buf);
}

/// bbport (r112k_hang-lantern-verdict): where the push of a hanging thing comes from, from the wind snapshot: r112's
/// "push" prints the follower's last table sample, which stays 0 until a table is filled (the first pushed draw).
struct PushSource {
    bool wind_on = false;
    float speed = 0.0f, gust = 1.0f, drive = 1.0f; ///< m/s, the gust factor now, its square (what drives the push)
    float amp = 0.0f;     ///< m at gust 1 (BB_WIND_SWAY x PushFull x (speed / FullSpeed)^2)
    float now = 0.0f;     ///< m: amp x drive, held to MaxAlong
    float lantern = 0.0f; ///< m: now x the scale of a 0.9 m thing: its bottom, at most
};

[[nodiscard]] inline PushSource PushSourceOf(bool wind_on, float speed, float gust, float scale) {
    PushSource p;
    p.wind_on = wind_on;
    p.speed = speed;
    p.gust = gust;
    p.drive = H::Drive(gust);
    p.amp = H::Amp(speed, scale);
    p.now = std::clamp(p.amp * p.drive, 0.0f, BbWindSway::MaxAlong);
    p.lantern = p.now * H::HangScale(0.0f, 0.9f);
    return p;
}

/// bbport (r112k): the once-line of the fix.
[[nodiscard]] inline std::string OnceTextK(const Knobs& k, bool gpu, bool live, float union_m) {
    char focus[16];
    if (k.focus != 0) {
        std::snprintf(focus, sizeof(focus), "%08x", static_cast<unsigned>(k.focus));
    } else {
        std::snprintf(focus, sizeof(focus), "none");
    }
    char buf[1024];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112k): a draw whose small bone palette the GPU writes is a static candidate too "
                  "(BB_WIND_HANG_STATIC_GPU=%d); a stream a skeleton draws is refused (skinned); a static "
                  "candidate's keys may span %.1f m, the union of the places it is drawn at (BB_WIND_HANG_STATIC_UNION; "
                  "r112 stopped at %.1f m); survey focus (BB_WIND_HANG_FOCUS): %s, and a route tail on the survey's "
                  "lines; live knob BB_WIND_HANG_PUSH=0 (set:/unset:) stops the push at once: %s",
                  gpu ? 1 : 0, double(union_m), double(H::MaxExtent), focus, live ? "available" : "not built in");
    return std::string(buf);
}

/// bbport (r112k): the candidates' measures: for each (the newest TakenMost) the scene box's height, then what the
/// keys of its slot measured (r112's book): fits or not. Under 400 characters.
[[nodiscard]] inline std::string MeasureText(const StaticBook& book, H::Book& heights) {
    std::string out = "Wind sway hang (r112k): candidates measured:";
    char buf[128];
    for (const StaticBook::Taken& t : book.taken) {
        const H::Entry* const h = heights.Find(t.stream);
        const unsigned vs = static_cast<unsigned>(t.e.vs & 0xffffffffull);
        if (h == nullptr || !h->judged) {
            std::snprintf(buf, sizeof(buf), " vs %08x scene %.2f m, keys not read;", vs, double(t.e.height));
        } else {
            std::snprintf(buf, sizeof(buf), " vs %08x scene %.2f m, keys %.2f m (%s);", vs, double(t.e.height),
                          double(h->top - h->base), h->fits ? "fits" : "does not fit");
        }
        out += buf;
    }
    if (book.taken.empty()) {
        out += " none";
    }
    if (out.size() > 400) {
        out.resize(397);
        out += "...";
    }
    return out;
}

/// bbport (r112k): the line of the fix every ReportFrames frames: the GPU-palette draws asked and passed, the routes
/// kept, the skinned refusals, the push's source.
[[nodiscard]] inline std::string KLine(const Stats& s, const StaticBook& book, const Routes& routes, bool gpu,
                                       const PushSource& p) {
    char buf[1024];
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112k): GPU-palette static draws (BB_WIND_HANG_STATIC_GPU=%d): %llu asked, %llu of "
                  "a candidate stream; streams with a route %zu (%llu not kept); skinned refused %llu (%llu taken back "
                  "from a standing candidate); push source: wind %s, speed %.2f m/s, gust %.2f (drive %.2f), "
                  "amplitude %.3f m at gust 1, %.3f m now, the bottom of a 0.9 m lantern %.3f m at most (r112's "
                  "'push' prints 0 until a table is filled: nothing pushed yet)",
                  gpu ? 1 : 0, n(s.gpu_asked), n(s.gpu_passed), routes.Size(), n(routes.dropped),
                  n(book.by_why[static_cast<std::size_t>(Why::Skinned)]), n(book.skinned_dropped),
                  p.wind_on ? "on" : "off", double(p.speed), double(p.gust), double(p.drive), double(p.amp),
                  double(p.now), double(p.lantern));
    return std::string(buf);
}

"""

F13 = r"""                                                          std::uint64_t frame) {
    struct Cand {
"""
F13N = r"""                                                          std::uint64_t frame,
                                                          const Routes* routes = nullptr) {
    struct Cand {
"""

F14 = r"""        float height = 0.0f, width = 0.0f, dist = -1.0f;
    };
"""
F14N = r"""        float height = 0.0f, width = 0.0f, dist = -1.0f;
        bool focus = false; // bbport (r112k): its vertex shader is BB_WIND_HANG_FOCUS's
    };
"""

F15 = r"""        if (c.g.free || c.g.held) {
            list.push_back(c);
        }
"""
F15N = r"""        // bbport (r112k_hang-lantern-verdict): the focus shader's meshes are listed first, hanging or not
        const Seen* const noted = draws.Find(b.stream);
        c.focus = k.focus != 0 && noted != nullptr &&
                  static_cast<std::uint32_t>(noted->vs & 0xffffffffull) == k.focus;
        if (c.g.free || c.g.held || c.focus) {
            list.push_back(c);
        }
"""

F16 = r"""        if (a.g.free != b.g.free) {
            return a.g.free;
        }
"""
F16P = r"""        if (a.focus != b.focus) { // bbport (r112k)
            return a.focus;
        }
"""

F17 = r"""        out.push_back(Cap(buf));
    }
    return out;
}

} // namespace BbWindHangFind
"""
F17N = r"""        std::string text(buf); // bbport (r112k): the stream's route and focus mark after the line
        text += RouteText(routes, c.b->stream, c.focus);
        out.push_back(Cap(text.c_str()));
    }
    return out;
}

} // namespace BbWindHangFind
"""

# ---- bbport_wind_hang.h ----------------------------------------------------------------------------
M1 = r"""inline Measured Measure(Entry& e, bool reset, std::uint64_t frame, const std::uint32_t* base_key,
                        const std::uint32_t* top_key, double time) {
"""
M1N = r"""inline Measured Measure(Entry& e, bool reset, std::uint64_t frame, const std::uint32_t* base_key,
                        const std::uint32_t* top_key, double time,
                        float max_extent = MaxExtent) { // bbport (r112k): a static candidate's union
"""
M2 = r"""        e.fits = std::isfinite(extent) && extent >= MinExtent && extent <= MaxExtent;
"""
M2N = r"""        e.fits = std::isfinite(extent) && extent >= MinExtent && extent <= max_extent;
"""

# ---- test_wind_hang_find.cpp -----------------------------------------------------------------------
T1 = r"""        Expect(lines[0].size() <= F::LineChars && lines[1].size() <= F::LineChars, "survey: lines are capped");
"""
T1N = r"""        Expect(lines[0].size() <= F::LineCharsK && lines[1].size() <= F::LineCharsK, "survey: lines are capped");
"""

T2 = r"""    if (failures == 0) {
"""
T2P = r"""    // bbport (r112k_hang-lantern-verdict): skinned streams stay out, the route's tail, the focus, the knobs, the union
    {
        F::Box skinned_box = lantern; // stream 7, a skeleton draws it
        skinned_box.skinned = true;
        const F::Entry sk = F::Evaluate(k, 4096, 500, 7, &skinned_box, ground_only, 100);
        Expect(sk.why == F::Why::Skinned && sk.until == 100 + F::HoldSkinned, "r112k: a skinned mesh is refused");
        Expect(std::string(F::WhyName(F::Why::Skinned)) == "skinned", "r112k: the new reason's name");
        F::StaticBook late; // two candidates; the scene then says a skeleton draws stream 7
        late.Set(7, F::Evaluate(k, 4096, 500, 7, &lantern, ground_only, 100), 100);
        late.Set(8, F::Evaluate(k, 4096, 500, 8, &lantern, ground_only, 100), 100);
        Expect(late.taken.size() == 2, "r112k: two candidates");
        const std::vector<F::Box> flagged{Ground(), skinned_box, F::Box{}};
        late.DropSkinned(flagged, 200);
        Expect(late.skinned_dropped == 1 && late.Peek(7, 4096, 201).known && !late.Peek(7, 4096, 201).pass &&
                   late.Peek(8, 4096, 201).pass && late.taken.size() == 1 && late.taken[0].stream == 8 &&
                   late.by_why[static_cast<std::size_t>(F::Why::Skinned)] == 1,
               "r112k: a standing candidate with a skeleton draw is taken back and leaves the list");
        late.DropSkinned(flagged, 300);
        Expect(late.skinned_dropped == 1, "r112k: a refusal is not taken back twice");

        F::Routes routes; // the Motion block's route of a stream
        routes.Note(0, 'P', true, false, true, true, 1);
        Expect(routes.Size() == 0, "r112k: stream 0 has no route");
        routes.Note(7, 'P', true, false, false, false, 5);
        routes.Note(7, 'P', true, false, true, true, 6);
        routes.Asked(7, false);
        routes.Asked(7, true);
        routes.Asked(9, true);
        const F::Route* r7 = routes.Find(7);
        Expect(r7 != nullptr && r7->kind == 'P' && r7->sway_bit && !r7->discards && r7->draws == 2 &&
                   r7->swayed == 1 && r7->delivered == 1 && r7->asked == 2 && r7->passed == 1 && r7->frame == 6,
               "r112k: the route counts draws, words, asks and candidates");
        Expect(routes.Find(9) != nullptr && routes.Find(9)->asked == 1 && routes.Find(9)->draws == 0 &&
                   routes.Find(8) == nullptr,
               "r112k: an ask before the first draw makes the route");
        F::Routes crowded_routes;
        for (std::uint64_t s = 1; s <= F::RoutesMost; ++s) {
            crowded_routes.Note(s, 'O', false, false, false, false, 1);
        }
        crowded_routes.Note(F::RoutesMost + 1, 'O', false, false, false, false, 1);
        crowded_routes.Note(3, 'O', false, false, false, false, 2);
        Expect(crowded_routes.Size() == F::RoutesMost && crowded_routes.dropped == 1 &&
                   crowded_routes.Find(3)->draws == 2,
               "r112k: at most RoutesMost routes, known ones go on counting");

        // the survey: route tail, focus first (hanging or not), route none
        F::BoxSet rs;
        rs.Begin(0);
        rs.Add(Ground());
        F::Box listed = lantern;
        listed.vertices = 777;
        rs.Add(listed);
        F::Box low_listed = MakeBox(8, 0.0f, -9.9f, 0.0f, 0.4f, -9.4f, 0.4f); // on the ground: only a focus lists it
        rs.Add(low_listed);
        F::Draws rd; // cam.vs is 0xabc
        rd.Note(7, cam);
        rd.Note(8, cam);
        F::StaticBook rb;
        F::Routes rr;
        rr.Note(7, 'P', true, false, false, false, 1);
        F::Knobs kf = k;
        kf.focus = 0xabcu;
        const std::vector<std::string> focused = F::SurveyLines(kf, rs, rd, rb, 10, &rr);
        Expect(focused.size() == 3 && Has(focused[1], "A stream 00000007") && Has(focused[1], "[focus]") &&
                   Has(focused[1], "route P bit 1 disc 0 draws 1 swayed 0 delivered 0 asked 0 passed 0") &&
                   Has(focused[2], "B stream 00000008") && Has(focused[2], "[focus]") &&
                   Has(focused[2], "route none") && focused[2].size() <= F::LineCharsK,
               "r112k: the survey lists the focus shader's meshes, hanging or not, with their routes");
        const std::vector<std::string> unfocused = F::SurveyLines(k, rs, rd, rb, 10, &rr);
        Expect(unfocused.size() == 2 && !Has(unfocused[1], "[focus]") && Has(unfocused[1], "route P bit 1"),
               "r112k: without a focus only what hangs is listed");
        const std::vector<std::string> bare = F::SurveyLines(k, rs, rd, rb, 10);
        Expect(bare.size() == 2 && !Has(bare[1], "route") && !Has(bare[1], "[focus]"),
               "r112k: without routes the line is as before");
        Expect(F::RouteText(nullptr, 7, true) == " [focus]" && F::RouteText(nullptr, 7, false).empty(),
               "r112k: the route text without routes");

        // the knobs
        Expect(F::ParseFocus("97f2d384") == 0x97f2d384u && F::ParseFocus("0x1f") == 0x1fu &&
                   F::ParseFocus(nullptr) == 0 && F::ParseFocus("") == 0 && F::ParseFocus("zz") == 0 &&
                   F::ParseFocus("12 ") == 0 && F::WithFocus(k, "abc").focus == 0xabcu && k.focus == 0,
               "r112k: the focus knob");
        Expect(F::ParseGpu(nullptr) && F::ParseGpu("1") && !F::ParseGpu("0") && F::ParseGpu("00") &&
                   F::ParseGpu(""),
               "r112k: the GPU route knob is on unless exactly 0");
        Expect(F::ParseUnion(nullptr) == F::UnionDefault && F::ParseUnion("100") == F::UnionMax &&
                   F::ParseUnion("1") == BbWindHang::MaxExtent && F::ParseUnion("x") == F::UnionDefault &&
                   F::ParseUnion("8") == 8.0f,
               "r112k: the union knob is held to MaxExtent..UnionMax");

        // r112's height rule with the union: 4.68 m of keys (the b50 lantern's) does not fit 4 m, fits the union
        const std::uint32_t base_key = BbWindSway::HeightKey(-34.28f);
        const std::uint32_t top_key = BbWindHang::TopKey(-29.6f);
        BbWindHang::Entry plain;
        BbWindHang::Measure(plain, true, 100, &base_key, &top_key, 1.0);
        const BbWindHang::Measured judged = BbWindHang::Measure(plain, false, 100 + BbWindHang::JudgeFrames,
                                                                &base_key, &top_key, 1.0);
        Expect(plain.judged && !plain.fits && !judged.swing && std::fabs(plain.top - plain.base - 4.68f) < 0.01f,
               "r112k: 4.68 m of keys is over r112's 4 m");
        BbWindHang::Entry unioned;
        BbWindHang::Measure(unioned, true, 100, &base_key, &top_key, 1.0, F::UnionDefault);
        const BbWindHang::Measured union_judged = BbWindHang::Measure(
            unioned, false, 100 + BbWindHang::JudgeFrames, &base_key, &top_key, 1.0, F::UnionDefault);
        Expect(unioned.judged && unioned.fits && union_judged.swing && !union_judged.measuring,
               "r112k: and within the union limit of a static candidate");

        // the push's source: r112's push line stays 0 until a table is filled; this one reads the wind
        const F::PushSource p = F::PushSourceOf(true, 4.0f, 1.0f, 3.0f);
        Expect(p.wind_on && p.amp == BbWindHang::Amp(4.0f, 3.0f) && p.drive == 1.0f &&
                   std::fabs(p.now - std::min(p.amp, BbWindSway::MaxAlong)) < 1e-6f &&
                   std::fabs(p.lantern - p.now * 0.75f) < 1e-5f && p.amp > 0.0f,
               "r112k: the push's source at the strongest test wind");
        const F::PushSource calm = F::PushSourceOf(true, 0.0f, 1.0f, 3.0f);
        Expect(calm.amp == 0.0f && calm.now == 0.0f && calm.lantern == 0.0f, "r112k: no wind, no push");
        const F::PushSource lull = F::PushSourceOf(true, 4.0f, 0.2f, 3.0f);
        Expect(std::fabs(lull.drive - 0.04f) < 1e-6f && lull.now < p.now, "r112k: a lull drives the push by its square");

        // the lines
        F::Stats ks;
        ks.gpu_asked = 65;
        ks.gpu_passed = 3;
        F::StaticBook kb = late;
        const std::string kline = F::KLine(ks, kb, routes, true, p);
        Expect(Has(kline, "(r112k)") && Has(kline, "65 asked, 3 of a candidate stream") &&
                   Has(kline, "streams with a route 2") && Has(kline, "skinned refused 1 (1 taken back") &&
                   Has(kline, "wind on, speed 4.00 m/s") && Has(kline, "nothing pushed yet"),
               "r112k: the line");
        const std::string once_k = F::OnceTextK(kf, true, true, F::UnionDefault);
        Expect(Has(once_k, "BB_WIND_HANG_STATIC_GPU=1") && Has(once_k, "12.0 m") && Has(once_k, "00000abc") &&
                   Has(once_k, "available") && Has(F::OnceTextK(k, false, false, 8.0f), "none") &&
                   Has(F::OnceTextK(k, false, false, 8.0f), "not built in"),
               "r112k: the once line");
        BbWindHang::Book heights;
        const std::string measured_none = F::MeasureText(F::StaticBook{}, heights);
        Expect(Has(measured_none, "candidates measured: none"), "r112k: the measure line with no candidate");
        F::StaticBook with_taken;
        F::Entry e1 = F::Evaluate(k, 4096, 500, 7, &lantern, ground_only, 100);
        e1.vs = 0x6a833138ull;
        with_taken.Set(7, e1, 100);
        const std::string unread = F::MeasureText(with_taken, heights);
        Expect(Has(unread, "vs 6a833138 scene 0.50 m, keys not read") && unread.size() <= 400,
               "r112k: a candidate whose keys were not read");
    }

"""

# ---- vk_rasterizer.h -------------------------------------------------------------------------------
H1 = r"""    void WindHangFindReport();
"""
H1N = r"""    /// bbport (r112k_hang-lantern-verdict): whether a GPU-palette draw's stream is a static candidate
    /// (BB_WIND_HANG_STATIC_GPU), and, for the survey (BB_WIND_HANG_FIND), what the Motion block made of a draw
    bool WindHangGpuStatic(const GraphicsPipeline* pipeline);
    void WindHangFindRoute(const GraphicsPipeline* pipeline, char kind, u32 sway, bool delivered);
"""
H2 = r"""    BbWindHangFind::Draws hang_find_draws;
"""
H2N = r"""    BbWindHangFind::Routes hang_find_routes; // bbport (r112k_hang-lantern-verdict, TOOL grade): the survey's routes
"""

# ---- vk_rasterizer.cpp -----------------------------------------------------------------------------
C1 = r"""                : (r34_kind == Motion::Kind::Other &&
                   BbWindHangFind::Wanted((pipeline->GetGraphicsKey().motion_vectors &
                                           Shader::MotionVectors::Sway) != 0,
                                          pipeline->GetStages()[u32(Shader::SwStage::Fragment)]))
                    ? WindSwayWord(pipeline, palette != 0 ? 1 : 0, true)
"""
C1N = r"""                : ((r34_kind == Motion::Kind::Other || r34_kind == Motion::Kind::GpuPalette) &&
                   BbWindHangFind::Wanted((pipeline->GetGraphicsKey().motion_vectors &
                                           Shader::MotionVectors::Sway) != 0,
                                          pipeline->GetStages()[u32(Shader::SwStage::Fragment)]) &&
                   // bbport (r112k_hang-lantern-verdict): a GPU-palette draw only when its stream is a hanging
                   // candidate (BB_WIND_HANG_STATIC_GPU); any other falls to the twig rule below as before
                   (r34_kind == Motion::Kind::Other || WindHangGpuStatic(pipeline)))
                    ? WindSwayWord(pipeline, palette != 0 ? 1 : 0, true)
"""
C2 = r"""        if (sway != 0 && dc.push_data.motion_param == 0) { // bbport (r112h_hang-not-the-hunter)
"""
C2P = r"""        if (BbWindHangFind::FindOn()) { // bbport (r112k_hang-lantern-verdict, TOOL grade): the survey's route
            WindHangFindRoute(pipeline,
                              r34_kind == Motion::Kind::Skinned
                                  ? 'S'
                                  : (r34_kind == Motion::Kind::GpuPalette ? 'P' : 'O'),
                              sway, dc.push_data.motion_param != 0);
        }
"""

# ---- vk_rasterizer_effects.cpp ---------------------------------------------------------------------
E1 = r"""// bbport (r89g_twigs-proof, TOOL): the draws of each twig-taken stream since the last proof lines: how many, how
"""
E1P = r"""// bbport (r112k_hang-lantern-verdict, TOOL): BB_WIND_HANG_PUSH with the test tools' live knobs (r84): "0" gives
// every hang word a ramp of 0 (nothing pushed; the shaders and everything else as they are), anything else or no
// text the push as it is. Read in WindHangWord only. Without the tools' header: always on. BB_WIND_HANG itself is
// read once (it decides pipeline keys and shaders) and cannot be live.
#if BB_WIND_TWIGS_LIVE
static bool HangPushParseLive(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == 0);
}

static bool WindHangLiveOn() {
    static BbLiveKnobs::Knob<bool> knob{"BB_WIND_HANG_PUSH", HangPushParseLive};
    return knob.Get();
}
#else
static bool WindHangLiveOn() {
    return true;
}
#endif

"""
E2 = r"""    return BbWindHang::HangWord(frame_slot, view, slot, m.ramp);
"""
E2N = r"""    // bbport (r112k): BB_WIND_HANG_PUSH=0 (live) gives the word no motion
    return BbWindHang::HangWord(frame_slot, view, slot, WindHangLiveOn() ? m.ramp : 0u);
"""
E3 = r"""    const BbWindHang::Measured m =
        BbWindHang::Measure(*entry, reset, frame, words + BbWindSway::BaseAt + slot,
                            words + BbWindHang::TopAt + slot, now.time);
"""
E3N = r"""    // bbport (r112k_hang-lantern-verdict): a static candidate (a standing verdict of the static book) is a mesh drawn
    // at several places: the keys of its slot span the union of them, up to BB_WIND_HANG_STATIC_UNION
    const BbWindHangFind::Entry* const placed = hang_static_book.Find(positions);
    const float max_extent = placed != nullptr && placed->why == BbWindHangFind::Why::Ok
                                 ? BbWindHangFind::UnionKnob()
                                 : BbWindHang::MaxExtent;
    const BbWindHang::Measured m =
        BbWindHang::Measure(*entry, reset, frame, words + BbWindSway::BaseAt + slot,
                            words + BbWindHang::TopAt + slot, now.time, max_extent);
"""
E4 = r"""    hang_find_boxes.camera = camera;
"""
E4P = r"""    hang_static_book.DropSkinned(hang_find_boxes.All(), frame); // bbport (r112k_hang-lantern-verdict)
"""
E5 = r"""        ++stats.no_stream;
        return false;
    }
"""
E5N = r"""    WindHangFindRefresh(frame); // bbport (r112k_hang-lantern-verdict): the scene's boxes every 60 frames, even for known streams
"""
E6 = r"""        return look.pass;
"""
E6P = r"""        if (BbWindHangFind::FindOn()) { // bbport (r112k_hang-lantern-verdict, TOOL grade)
            hang_find_routes.Asked(positions, look.pass);
        }
"""
E7 = r"""    return verdict.why == BbWindHangFind::Why::Ok;
"""
E7P = r"""    if (BbWindHangFind::FindOn()) { // bbport (r112k_hang-lantern-verdict, TOOL grade)
        hang_find_routes.Asked(positions, verdict.why == BbWindHangFind::Why::Ok);
    }
"""
E8 = r"""// bbport (r112i_hang-find-lanterns, TOOL grade; BB_WIND_HANG_FIND=1): the survey's lines (the header and the
"""
E8P = r"""// bbport (r112k_hang-lantern-verdict): may a draw whose small bone palette the GPU writes (Motion::Kind::GpuPalette,
// an opaque pipeline with the Sway bit: the caller tested both) go to the static path: its position stream (the
// pipeline's fetch, semantic 0) is a hanging candidate by the book's standing verdict, or gets a verdict now
// (WindHangStaticAllowed: box, size, ground rules). Only with BB_WIND_HANG_STATIC_GPU (default) and what the static
// path needs (the box keys, the sway words, ray tracing). False: the draw falls to the twig rule. On the thread
// recording draws.
bool Rasterizer::WindHangGpuStatic(const GraphicsPipeline* pipeline) {
    if (!BbWindHangFind::GpuOn() || !BbWindHangStill::BoxAvailable() ||
        object_motion->SwayWords() == nullptr || !rt_shadow->Wanted()) {
        return false;
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto& fetch = pipeline->GetFetchShader();
    if (!fetch) {
        return false;
    }
    u64 positions = 0;
    u32 positions_size = 0;
    u32 stride = 0;
    for (const auto& attribute : fetch->attributes) {
        if (attribute.semantic == 0) {
            const auto stream = attribute.GetSharp(vs);
            positions = stream.base_address;
            positions_size = stream.GetSize();
            stride = stream.GetStride();
            break;
        }
    }
    BbWindHangFind::Stats& stats = hang_find_stats;
    ++stats.gpu_asked;
    if (positions == 0 || positions_size == 0 || stride == 0) {
        return false;
    }
    const u64 frame = object_motion->Frame();
    const BbWindHangFind::StaticBook::Look look =
        hang_static_book.Peek(positions, positions_size, frame);
    const bool pass = look.known ? look.pass
                                 : WindHangStaticAllowed(positions, positions_size, stride, frame,
                                                         vs.pgm_hash);
    if (pass) {
        ++stats.gpu_passed;
    }
    return pass;
}

// bbport (r112k_hang-lantern-verdict, TOOL grade; BB_WIND_HANG_FIND=1): what the Motion block made of a draw of the
// stream at the pipeline's position attribute: its kind ('S' skinned, 'P' GPU palette, 'O' other), whether its
// pipeline has the Sway bit and a pixel shader that discards, whether it got a sway word and whether the word
// reached the motion parameter (BbWindHangFind::Routes; the survey prints it after the stream's line).
void Rasterizer::WindHangFindRoute(const GraphicsPipeline* pipeline, char kind, u32 sway,
                                   bool delivered) {
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto& fetch = pipeline->GetFetchShader();
    if (!fetch) {
        return;
    }
    for (const auto& attribute : fetch->attributes) {
        if (attribute.semantic == 0) {
            const auto stream = attribute.GetSharp(vs);
            const auto fragment = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
            hang_find_routes.Note(stream.base_address, kind,
                                  (pipeline->GetGraphicsKey().motion_vectors &
                                   Shader::MotionVectors::Sway) != 0,
                                  fragment != nullptr && fragment->has_discard, sway != 0, delivered,
                                  object_motion->Frame());
            return;
        }
    }
}

"""
E9 = r"""hang_static_book, frame)) {"""
E9N = r"""hang_static_book, frame, &hang_find_routes)) {"""
E10 = r"""            hang_find_stats = {};
"""
E10P = r"""            // bbport (r112k_hang-lantern-verdict): the GPU-palette draws, skinned refusals, the push's source and
            // the candidates' measures
            const BbWind::Snapshot hang_snap = wind.Get();
            const auto& hang_knob = BbWindSway::KnobOnce();
            const BbWindHangFind::PushSource hang_source = BbWindHangFind::PushSourceOf(
                hang_snap.on, hang_snap.speed,
                BbWind::GustOf(hang_snap, hang_snap.time, hang_knob.gusts), hang_knob.scale);
            BbReport::Printf("%s\n", BbWindHangFind::KLine(hang_find_stats, hang_static_book,
                                                           hang_find_routes, BbWindHangFind::GpuOn(),
                                                           hang_source)
                                         .c_str());
            BbReport::Printf("%s\n",
                             BbWindHangFind::MeasureText(hang_static_book, hang_book).c_str());
"""
E11 = r"""    }
    // bbport (r112g_hang-judge-settles): its line once (BB_WIND_HANG on)
"""
E11P = r"""        BbReport::Printf("%s\n", BbWindHangFind::OnceTextK(BbWindHangFind::KnobOnce(),
                                                           BbWindHangFind::GpuOn(),
                                                           BB_WIND_TWIGS_LIVE != 0,
                                                           BbWindHangFind::UnionKnob())
                                     .c_str()); // bbport (r112k_hang-lantern-verdict)
"""

# ---- README.md -------------------------------------------------------------------------------------
R1 = r"""| `BB_WIND_HANG_FIND` |"""
R1P = r"""| `BB_WIND_HANG_STATIC_GPU` | Part of `BB_WIND_HANG_STATIC` (r112k; default on, exactly `0` gives r112j's routing). A draw of an opaque pipeline with the sway bit whose small bone palette the GPU writes (the game's per-instance data: the graveyard's lanterns) is offered to the static path too, when its mesh is a hanging candidate by the same box rules (r112i and r112j offered only the draws whose palette the CPU reads). A GPU-palette draw that is no candidate stays with the twig rule. A mesh a skeleton draws (its ray traced scene entry says so) is refused for good ("skinned"). Log: "Wind sway hang (r112k)" once and every 600 frames. |
| `BB_WIND_HANG_STATIC_UNION` | Part of `BB_WIND_HANG_STATIC` (r112k; metres, 4 to 40, default `12`; text that is no number gives the default). A mesh that is drawn at several places spans the union of them in the keys the GPU judge reads (the b50 lantern: 4.68 m, r112 refuses 4 m): a static candidate's keys may span this much. Every other hanging thing keeps r112's 4 m. |
| `BB_WIND_HANG_FOCUS` | A TEST aid for `BB_WIND_HANG_FIND` (r112k; a vertex shader hash in hex as the survey prints it as "vs", for example `97f2d384`; anything else gives none). The survey lists that shader's meshes first, hanging or not (marked "[focus]"). The survey's lines end with the route of the stream in the rasterizer's Motion block: its kind (S skinned, P GPU palette, O other), the sway bit, the discard flag and the counts of draws, sway words, delivered words, asks of the static path and candidates; "route none" when no draw of it reached the Motion block. |
| `BB_WIND_HANG_PUSH` | A TEST aid of the test tools' live knobs (r112k; guarded like `BB_WIND_TWIGS`): `set:BB_WIND_HANG_PUSH=0` gives every hanging thing's word no motion at once, `unset:BB_WIND_HANG_PUSH` brings it back: the same-camera A/B in one game (`BB_WIND_HANG` itself is read once and cannot be live). |
"""

EDITS = {
NF: [
('rep', F1, "", F1N),
('rep', F2, "", F2N),
('ins', F3, "", F3N),
('rep', F4, "", F4N),
('rep', F5, "", F5N),
('ins', F6, F6P, ""),
('ins', F7, "", F7N),
('ins', F8, F8P, ""),
('ins', F9, F9P, ""),
('ins', F10, F10P, ""),
('rep', F11, "", F11N),
('ins', F12, F12P, ""),
('rep', F13, "", F13N),
('rep', F14, "", F14N),
('rep', F15, "", F15N),
('ins', F16, F16P, ""),
('rep', F17, "", F17N),
],
NH: [
('rep', M1, "", M1N),
('rep', M2, "", M2N),
],
NT: [
('rep', T1, "", T1N),
('ins', T2, T2P, ""),
],
RH: [
('ins', H1, "", H1N),
('ins', H2, "", H2N),
],
RC: [
('rep', C1, "", C1N),
('ins', C2, C2P, ""),
],
RE: [
('ins', E1, E1P, ""),
('rep', E2, "", E2N),
('rep', E3, "", E3N),
('ins', E4, E4P, ""),
('ins', E5, "", E5N),
('ins', E6, E6P, ""),
('ins', E7, E7P, ""),
('ins', E8, E8P, ""),
('rep', E9, "", E9N),
('ins', E10, E10P, ""),
('ins', E11, E11P, ""),
],
RM: [
('ins', R1, R1P, ""),
],
}

ORDER = (NF, NH, NT, RH, RC, RE, RM)


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


def balance(text):
    """(braces, parens, brackets) net of a C++ text without comments, strings and char literals."""
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', text)
    text = re.sub(r"'(?:\\.|[^'\\\n])'", "' '", text)
    return (text.count("{") - text.count("}"), text.count("(") - text.count(")"),
            text.count("[") - text.count("]"))


def text_checks(texts, olds):
    """The ties a compiler cannot check."""
    nf, nh, nt, rh, rc, re_ = texts[NF], texts[NH], texts[NT], texts[RH], texts[RC], texts[RE]
    for path in ORDER:
        if path == RM:
            continue
        if balance(texts[path]) != balance(olds[path]):
            raise SystemExit("text check: %s: braces, parens or brackets changed by %r" %
                             (path, tuple(a - b for a, b in zip(balance(texts[path]), balance(olds[path])))))
    for needle in ("Why::Skinned", "DropSkinned(", "class Routes", "RouteText(", "PushSourceOf(", "KLine(",
                   "MeasureText(", "OnceTextK(", "GpuOn()", "UnionKnob()", "ParseFocus(", "WithFocus("):
        if needle not in nf:
            raise SystemExit("text check: %s missing in the header" % needle)
    # the survey and the book: Routes before SurveyLines, the constants before their first use
    if nf.index("class Routes") > nf.index("inline std::vector<std::string> SurveyLines("):
        raise SystemExit("text check: Routes comes after the survey")
    if nf.index("inline std::string RouteText(") > nf.index("inline std::vector<std::string> SurveyLines("):
        raise SystemExit("text check: RouteText comes after the survey")
    if nf.index("LineCharsK =") > nf.index("if (out.size() > LineCharsK)"):
        raise SystemExit("text check: LineCharsK is used before its definition")
    if nf.index("HoldSkinned =") > nf.index("e.until = frame + HoldSkinned;"):
        raise SystemExit("text check: HoldSkinned is used before its definition")
    if nf.index("UnionDefault =") > nf.index("inline float ParseUnion("):
        raise SystemExit("text check: UnionDefault is used before its definition")
    if nf.index("inline Knobs WithFocus(") > nf.index("inline const Knobs& KnobOnce()"):
        raise SystemExit("text check: WithFocus comes after KnobOnce")
    ev = nf[nf.index("inline Entry Evaluate("):]
    if not (ev.index("Why::NoBox") < ev.index("Why::Skinned") < ev.index("Why::Shape")):
        raise SystemExit("text check: the skinned refusal belongs between the box test and the shape test")
    if "StaticBook::Taken" not in nf or nf.count("std::remove_if(") != 1:
        raise SystemExit("text check: DropSkinned's list removal")
    if nf.index("class StaticBook") > nf.index("void DropSkinned(") or \
            nf.index("struct Box {") > nf.index("class StaticBook"):
        raise SystemExit("text check: Box must be defined before the book that uses it")
    if "max_extent" not in nh or nh.count("extent <= MaxExtent") != 0:
        raise SystemExit("text check: Measure still tests MaxExtent")
    # the call chain in the rasterizer
    if "bool WindHangGpuStatic(const GraphicsPipeline* pipeline);" not in rh or \
            "void WindHangFindRoute(const GraphicsPipeline* pipeline, char kind, u32 sway, bool delivered);" not in rh:
        raise SystemExit("text check: the declarations")
    if "BbWindHangFind::Routes hang_find_routes;" not in rh:
        raise SystemExit("text check: the routes member")
    if rc.count("WindHangGpuStatic(pipeline)") != 1 or rc.count("WindHangFindRoute(pipeline,") != 1:
        raise SystemExit("text check: the rasterizer hooks")
    if rc.index("WindHangGpuStatic(pipeline)") < rc.index("BbWindHangFind::Wanted("):
        raise SystemExit("text check: Wanted must be tested before the GPU route's verdict")
    for needle in ("bool Rasterizer::WindHangGpuStatic(", "void Rasterizer::WindHangFindRoute(",
                   "static bool WindHangLiveOn()", "WindHangLiveOn() ? m.ramp : 0u", "BbWindHangFind::KLine(",
                   "BbWindHangFind::MeasureText(", "BbWindHangFind::OnceTextK(", "DropSkinned(hang_find_boxes.All()",
                   "now.time, max_extent);", "&hang_find_routes)) {"):
        if needle not in re_:
            raise SystemExit("text check: %s missing in the effects file" % needle)
    if re_.index("static bool WindHangLiveOn()") > re_.index("WindHangLiveOn() ? m.ramp : 0u"):
        raise SystemExit("text check: WindHangLiveOn is used before its definition")
    if re_.count("static bool WindHangLiveOn()") != 2:  # the guarded pair
        raise SystemExit("text check: WindHangLiveOn must be defined in both branches of the guard")
    if re_.index("BbWindHangFind::KLine(") > re_.index("hang_find_stats = {};"):
        raise SystemExit("text check: the r112k line must print before the stats reset")
    if "Why::Skinned" not in nt or "r112k: a skinned mesh is refused" not in nt:
        raise SystemExit("text check: the tests of the skinned refusal are missing")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112K_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == NF and "OnceTextJ(" not in cur:
            raise SystemExit("REFUSED: r112j_hang-static-verts must be applied (OnceTextJ)")
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
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

    olds = {p[0]: p[4] for p in plan}
    if cmd == "check":
        if state == "applied":
            text_checks(olds, {p[0]: revert_edits(p[4], p[1]) for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts(), olds)
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts, olds)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r112ktmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
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
        tmp = full + ".r112ktmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


if __name__ == "__main__":
    main()
