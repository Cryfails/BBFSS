# r112j_hang-static-verts: FEATURE fix on top of r112i_hang-find-lanterns (r112h, r112g, r112f, r112e, r112,
# all applied in the tree). Behind r112's own knob BB_WIND_HANG=1 (off by default), as r112i. No new files, no
# shader change: five files edited (the shim header of r112i, its test, vk_rasterizer.h, vk_rasterizer_effects.cpp,
# README.md).
#
# THE EVIDENCE (b47, slot_b47_result.txt, b47_reports.txt): r112i's survey works (graveyard: 455 scene boxes, 16
# fit, 6 hang free; static entries C = 1429 vertices 0.21 m and D = 2491 vertices 0.88 m, vs 97f2d384 / ps 0f54e5f9,
# 6.3 m above the ground), but the static path judged 17 of 17 (graveyard) and 50 of 52 (alley) streams "over 20000
# vertices" and kept the verdict: 3978 of 3995 draws refused. The test read positions_size / stride, and
# positions_size is the size of the buffer the stream's V# describes (the game binds a whole vertex heap, not the
# mesh), so every mesh looked huge. The survey's "verts" is the ray traced scene's own count (the index range of the
# draw, RtShadow Entry::vertices), and that one is right.
#
# WHAT THIS CHANGES
#  (1) THE VERTEX TEST. BbWindHangFind::Evaluate takes the vertex count from the scene's box of the stream
#      (Box::vertices = the survey's "verts") and compares THAT with BB_WIND_HANG_STATIC_VERTS. A stream with no
#      box is NoBox (asked again in 120 frames) whatever its buffer says: the buffer's number is no longer a reason
#      to refuse. The bytes over the stride stay in the Entry (stream_verts) for the log only. Every refusal says
#      what was compared: the survey's "book too big 21000v (stream said 90000v)", and the new r112j line: how many
#      streams were too big and the least and the most of their own counts.
#  (2) THE LANTERNS ARE LISTED. The new line "Wind sway hang (r112j): candidates N ... : vs <hash> <verts> verts
#      <h> m tall <up> m up;" names the streams the static path took as candidates (up to 6, newest), with their
#      vertex shader hash, so the log says which meshes (97f2d384 or others) went on to the GPU judge. Building
#      parts stay refused by the rules of r112i that did not fail: own count over 20000, box over 2 m tall or 3 m
#      wide, standing on the ground (under 1 m clear) or on a thin post.
#  (3) INDOORS: a static hanging thing's push is scaled by BB_WIND_HANG_STATIC_ROOF (default 0.1; 1 leaves it out)
#      while the camera is under r117's roof: x0.1 at or under the indoor share (BB_WIND_HANG_INDOOR, 0.1), rising
#      smoothly to x1 at 0.5 of the wind open (BbWindHangFind::RoofScale; the ramp byte of its sway word is scaled,
#      ScaleRamp, so a thing that was cleared outside and then seen from inside is near 0, not stopped with a pop).
#      r112h's indoor refusal (a stream first judged with the camera indoors is not taken) stays, so the dark
#      interior stays at 0 or near 0. This is the camera's share (the CPU has no field value at a mesh); the GPU
#      scales every vertex by r117's per-vertex field as before.
#  (4) The survey (BB_WIND_HANG_FIND=1, TOOL-grade) prints "scr x,y": an ESTIMATE of the candidate's screen
#      position from the camera's view and projection (z forward, x and y scales signed: ndc +y down, as footprints.h), so that a job can
#      aim. Unchecked against a picture.
#
# Off: all of it is behind BbWindHang::KnobOnce().on as r112i: BB_WIND_HANG unset leaves WindHangStaticAllowed,
# the roof scaling and the lines unreached (they sit in r112i's hang path and report blocks); BB_WIND_HANG_STATIC=0
# gives r112h again. BB_WIND_HANG_STATIC_ROOF=1 leaves (3) out; FIND unset leaves (4) out (no box read, no
# camera read). Cost of the change: per static candidate draw (a few per frame, only streams that passed the
# verdict) one read of the mapped shelter counter (CameraOpen) and a few flops; nothing per vertex, no GPU work.
#
# Use: python -I -X utf8 r112j_hang-static-verts.py check | apply | revert
# Root: R112J_ROOT, else <tree>. CRLF kept. apply backs the originals up in r112j_backup next to this
# script; revert takes out exactly what apply put in. Needs r112i applied.
import os, sys

ROOT = os.environ.get("R112J_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112j_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RE = RV + "vk_rasterizer_effects.cpp"
RH = RV + "vk_rasterizer.h"
NF = "engine/gpu/shim/bbport_wind_hang_find.h"
NT = "engine/tests/test_wind_hang_find.cpp"
RM = "README.md"

# ---- bbport_wind_hang_find.h -----------------------------------------------------------------------
F1 = r"""struct Entry {
    std::uint32_t size = 0, verts = 0; ///< bytes bound at its address, vertices in them
"""
F1N = r"""struct Entry {
    // bbport (r112j_hang-static-verts): `verts` is the mesh's OWN vertex count (the ray traced scene's index
    // range of its draw: the survey's "verts"); `stream_verts` is what the bytes bound at the stream's address
    // over its stride say: the size of the buffer the mesh lies in, not of the mesh (r112i tested that one and
    // refused every mesh); kept for the log only
    std::uint32_t size = 0, verts = 0, stream_verts = 0; ///< bytes bound at its address; own vertices; bytes / stride
    std::uint64_t vs = 0;                                ///< its vertex shader's hash (for the log)
"""

F2 = r"""/// The verdict on a new static stream: `verts` its vertex count, `b` its box in the scene (null: none),
/// `all` the scene's boxes, `stream` its address.
[[nodiscard]] inline Entry Evaluate(const Knobs& k, std::uint32_t size, std::uint32_t verts,
                                    std::uint64_t stream, const Box* b, const std::vector<Box>& all,
                                    std::uint64_t frame) {
    Entry e;
    e.size = size;
    e.verts = verts;
    e.seen = frame;
    if (verts > k.verts) {
        e.why = Why::TooBig;
        e.until = frame + HoldBig;
        return e;
    }
    if (b == nullptr) {
        e.why = Why::NoBox;
        e.until = frame + HoldNoBox;
        return e;
    }
"""
F2N = r"""/// The verdict on a new static stream: `size` the bytes bound at its address and `stream_verts` those over its
/// stride (the buffer's, for the log only: r112j), `b` its box in the scene (null: none) and with it the mesh's
/// own vertex count, the number tested against Knobs::verts (r112j), `all` the scene's boxes, `stream` its address.
[[nodiscard]] inline Entry Evaluate(const Knobs& k, std::uint32_t size, std::uint32_t stream_verts,
                                    std::uint64_t stream, const Box* b, const std::vector<Box>& all,
                                    std::uint64_t frame) {
    Entry e;
    e.size = size;
    e.stream_verts = stream_verts;
    e.seen = frame;
    if (b == nullptr) {
        e.why = Why::NoBox;
        e.until = frame + HoldNoBox;
        return e;
    }
    e.verts = b->vertices; // bbport (r112j): the mesh's own count
    if (e.verts > k.verts) {
        e.why = Why::TooBig;
        e.until = frame + HoldBig;
        return e;
    }
"""

F3 = r"""    std::array<std::uint64_t, WhyCount> by_why{}; ///< verdicts made, by reason
"""
F3N = r"""    /// bbport (r112j_hang-static-verts): the streams refused as too big (how many, and the least and the most
    /// of their own vertex counts), and the candidates of the last verdicts (the newest TakenMost), for the log
    std::uint64_t big_n = 0;
    std::uint32_t big_least = 0, big_most = 0;
    struct Taken {
        std::uint64_t stream = 0;
        Entry e;
    };
    std::vector<Taken> taken;
"""

F4 = r"""        entries[stream] = e;
        ++by_why[static_cast<std::size_t>(e.why)];
    }
"""
F4N = r"""        entries[stream] = e;
        ++by_why[static_cast<std::size_t>(e.why)];
        if (e.why == Why::TooBig) { // bbport (r112j_hang-static-verts)
            big_least = big_n == 0 ? e.verts : std::min(big_least, e.verts);
            big_most = std::max(big_most, e.verts);
            ++big_n;
        } else if (e.why == Why::Ok) {
            const auto same = std::find_if(taken.begin(), taken.end(),
                                           [&](const Taken& t) { return t.stream == stream; });
            if (same != taken.end()) {
                same->e = e;
            } else {
                if (taken.size() >= TakenMost) {
                    taken.erase(taken.begin());
                }
                taken.push_back({stream, e});
            }
        }
    }
"""

F5 = r"""inline constexpr std::size_t LineChars = 380;
"""
F5N = r"""inline constexpr std::size_t TakenMost = 6, TakenChars = 300; // bbport (r112j_hang-static-verts)
"""

F6 = r"""/// Pure form of Wanted: a pipeline with the Sway bit whose pixel shader (null: none) does not discard.
"""
F6P = r"""// bbport (r112j_hang-static-verts): the push of a static hanging thing under a roof. BB_WIND_HANG_STATIC_ROOF
// (0 to 1, default 0.1, 1 = off): the scale of its push while the camera's open share of the wind (r117's
// field at the camera) is at or under the indoor share (BB_WIND_HANG_INDOOR), rising to 1 at RoofOpen (or
// RoofGap over the indoor share when that is higher): a smooth ramp, so nothing pops when the camera walks in.
inline constexpr float RoofDefault = 0.1f, RoofOpen = 0.5f, RoofGap = 0.05f;

[[nodiscard]] inline float ParseRoof(const char* text) {
    return std::clamp(BbWindSway::ParseNumber(text, RoofDefault), 0.0f, 1.0f);
}

/// The knob, read once.
[[nodiscard]] inline float RoofKnob() {
    static const float roof = ParseRoof(std::getenv("BB_WIND_HANG_STATIC_ROOF"));
    return roof;
}

/// The scale of the push at the camera's open share `open` (`indoor`: BB_WIND_HANG_INDOOR, `roof`: the knob).
[[nodiscard]] inline float RoofScale(float roof, float indoor, float open) {
    const float hi = std::max(RoofOpen, indoor + RoofGap);
    const float t = std::clamp((open - indoor) / (hi - indoor), 0.0f, 1.0f);
    return roof + (1.0f - roof) * t;
}

/// A sway word with its ramp byte (bits 16-23, BbWindSway::PackWord) scaled by `scale` (0 to 1).
[[nodiscard]] inline std::uint32_t ScaleRamp(std::uint32_t word, float scale) {
    const std::uint32_t ramp = (word >> 16) & 255u;
    const std::uint32_t scaled =
        std::uint32_t(std::lround(float(ramp) * std::clamp(scale, 0.0f, 1.0f)));
    return (word & ~(255u << 16)) | (scaled << 16);
}

"""

F7 = r"""    std::uint64_t judged = 0;    ///< a stream got a new verdict
"""
F7N = r"""    std::uint64_t roof_words = 0; ///< bbport (r112j): hang words of static things scaled down (camera under a roof)
    std::uint64_t full_words = 0; ///< bbport (r112j): and left whole
    float roof_least = 1.0f;      ///< bbport (r112j): the least scale given
"""

F8 = r"""                  "stream has at most %u vertices (BB_WIND_HANG_STATIC_VERTS) and the ray traced "
"""
F8N = r"""                  "mesh (its own count: r112j) has at most %u vertices (BB_WIND_HANG_STATIC_VERTS) and the ray traced "
"""

F9 = r"""/// The static path's line: this interval's counts and the verdicts made so far.
"""
F9P = r"""/// bbport (r112j_hang-static-verts): the once-line of the fix.
[[nodiscard]] inline std::string OnceTextJ(const Knobs& k, float roof, float indoor) {
    char buf[1024];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112j): the static path's vertex test compares the mesh's OWN count (the ray "
                  "traced scene's index range of its draw), at most %u, and no more the bytes bound at its "
                  "stream's address over the stride (the buffer's: r112i read that and refused 17 of 17 and 50 "
                  "of 52 streams); a static hanging thing's push is x%.2f while the camera's open share of the "
                  "wind is %.2f or less, rising to x1 at %.2f (BB_WIND_HANG_STATIC_ROOF=%.2f, 1 = off); the "
                  "survey's lines carry scr x,y (an estimate of the screen position)",
                  k.verts, double(roof), double(indoor), double(std::max(RoofOpen, indoor + RoofGap)),
                  double(roof));
    return std::string(buf);
}

"""

F10 = r"""/// The survey: a header line and up to ListMost candidate lines (a mesh of the scene of
"""
F10P = r"""/// bbport (r112j_hang-static-verts): where a world point lies on the screen, estimated from the camera's view
/// (3x4 rows, world to view, z forward) and projection (x and y scales signed by the G-buffer viewport: ndc +y down, footprints.h's rule) in pixels of
/// the render size. An estimate that no picture has checked: the survey prints it as "scr".
struct Screen {
    bool known = false; ///< the camera was read
    bool ok = false;    ///< and the point is in front of it
    float x = 0.0f, y = 0.0f;
};

[[nodiscard]] inline Screen ScreenOf(const BoxSet& set, float wx, float wy, float wz) {
    Screen s;
    if (!set.view_ok) {
        return s;
    }
    s.known = true;
    const std::array<float, 12>& v = set.view;
    const float vx = v[0] * wx + v[1] * wy + v[2] * wz + v[3];
    const float vy = v[4] * wx + v[5] * wy + v[6] * wz + v[7];
    const float vz = v[8] * wx + v[9] * wy + v[10] * wz + v[11];
    if (!(vz > 0.05f) || !std::isfinite(vx + vy + vz)) {
        return s;
    }
    s.ok = true;
    s.x = 0.5f * float(set.render[0]) * (1.0f + set.proj[0] * vx / vz);
    s.y = 0.5f * float(set.render[1]) * (1.0f + set.proj[1] * vy / vz); // (review) proj[1] carries the sign
    return s;
}

/// bbport (r112j_hang-static-verts): the second line of the static path: the numbers first (how many streams
/// were refused as too big and the least and the most of their OWN counts, the roof push), then the
/// candidates by vertex shader hash. Under TakenChars characters.
[[nodiscard]] inline std::string TakenLine(const StaticBook& book, const Knobs& k, const Stats& s) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    char buf[200];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112j): candidates %zu, too big %llu (own counts %u..%u, limit %u); roof "
                  "push %llu words (least x%.2f), %llu full:",
                  book.taken.size(), n(book.big_n), book.big_least, book.big_most, k.verts,
                  n(s.roof_words), double(s.roof_least), n(s.full_words));
    std::string out(buf);
    for (const StaticBook::Taken& t : book.taken) {
        std::snprintf(buf, sizeof(buf), " vs %08x %u verts %.2f m tall %.1f m up;",
                      static_cast<unsigned>(t.e.vs & 0xffffffffull), t.e.verts, double(t.e.height),
                      double(t.e.above));
        out += buf;
    }
    if (book.taken.empty()) {
        out += " none";
    }
    if (out.size() > TakenChars) {
        out.resize(TakenChars - 3);
        out += "...";
    }
    return out;
}

"""

F11 = r"""    bool camera_ok = false;
    std::array<float, 3> camera{};
"""
F11N = r"""    // bbport (r112j_hang-static-verts): the camera's view (3x4 rows) and projection (x, y scales, z scale, z
    // offset) and the render size, for the survey's screen estimate (ScreenOf)
    bool view_ok = false;
    std::array<float, 12> view{};
    std::array<float, 4> proj{};
    std::array<std::uint32_t, 2> render{};
"""

F12 = r"""        char vs[16], ps[16], dist[16], above[16], gap[16], idx[16];
"""
F12N = r"""        char vs[16], ps[16], dist[16], above[16], gap[16], idx[16], scr[24], book_text[64];
"""

F13 = r"""            std::snprintf(dist, sizeof(dist), "n/a");
        }
"""
F13N = r"""        // bbport (r112j_hang-static-verts): the screen estimate and the book's verdict with the numbers compared
        const Screen sc = ScreenOf(set, 0.5f * (c.b->box[0] + c.b->box[3]),
                                   0.5f * (c.b->box[1] + c.b->box[4]), 0.5f * (c.b->box[2] + c.b->box[5]));
        if (sc.ok) {
            std::snprintf(scr, sizeof(scr), "%.0f,%.0f", double(sc.x), double(sc.y));
        } else {
            std::snprintf(scr, sizeof(scr), "%s", sc.known ? "behind" : "n/a");
        }
        if (e != nullptr) {
            std::snprintf(book_text, sizeof(book_text), "%s %uv (stream said %uv)", WhyName(e->why),
                          e->verts, e->stream_verts);
        } else {
            std::snprintf(book_text, sizeof(book_text), "-");
        }
"""

F14 = r"""dist %s m: %s%s above %s m, "
"""
F14N = r"""dist %s m scr %s: %s%s above %s m, "
"""

F15 = r"""dist, c.g.free ? "FREE" : "held","""
F15N = r"""dist, scr, c.g.free ? "FREE" : "held","""

F16 = r"""c.b->dynamic ? 1 : 0, e != nullptr ? WhyName(e->why) : "-");"""
F16N = r"""c.b->dynamic ? 1 : 0, book_text);"""

# ---- test_wind_hang_find.cpp -----------------------------------------------------------------------
T1 = r"""    F::Entry e = F::Evaluate(k, 4096, 30000, 7, &lantern, ground_only, 100);
    Expect(e.why == F::Why::TooBig && e.until == 100 + F::HoldBig, "evaluate: too many vertices");
"""
T1N = r"""    F::Box heavy = lantern; // bbport (r112j): the mesh's own count is tested, not the buffer's
    heavy.vertices = 30000;
    F::Entry e = F::Evaluate(k, 4096, 500, 7, &heavy, ground_only, 100);
    Expect(e.why == F::Why::TooBig && e.until == 100 + F::HoldBig && e.verts == 30000 &&
               e.stream_verts == 500,
           "evaluate: too many vertices");
"""

T2 = r"""    Expect(e.why == F::Why::Ok && e.until == 100 + F::KeepCandidate && e.verts == 500 &&
"""
T2N = r"""    Expect(e.why == F::Why::Ok && e.until == 100 + F::KeepCandidate && e.verts == 100 &&
               e.stream_verts == 500 &&
"""

T3 = r"""    // the book
"""
T3P = r"""    // bbport (r112j_hang-static-verts): the number tested is the mesh's own, not the buffer's bytes over its stride
    F::Box lamp_c = lantern; // the graveyard's entry C: 1429 vertices, 0.21 m tall, 0.29 m wide
    lamp_c.vertices = 1429;
    lamp_c.box = {0.0f, -6.0f, 0.0f, 0.29f, -5.79f, 0.29f};
    F::Box lamp_d = lantern; // entry D: 2491 vertices, 0.88 m tall, 1.45 m wide
    lamp_d.stream = 8;
    lamp_d.vertices = 2491;
    lamp_d.box = {2.0f, -6.0f, 0.0f, 3.45f, -5.12f, 0.4f};
    F::Entry own = F::Evaluate(k, 3000000, 150000, 7, &lamp_c, ground_only, 100);
    Expect(own.why == F::Why::Ok && own.verts == 1429 && own.stream_verts == 150000 && own.size == 3000000,
           "r112j: a 1429-vertex lamp in a buffer of 150000 vertices is a candidate");
    F::Entry own_d = F::Evaluate(k, 3000000, 150000, 8, &lamp_d, ground_only, 100);
    Expect(own_d.why == F::Why::Ok && own_d.verts == 2491, "r112j: entry D too");
    F::Box wall = lantern;
    wall.vertices = 30000;
    e = F::Evaluate(k, 100, 100, 7, &wall, ground_only, 100);
    Expect(e.why == F::Why::TooBig && e.verts == 30000 && e.stream_verts == 100,
           "r112j: a big mesh in a small buffer is refused on its own count");
    e = F::Evaluate(k, 3000000, 150000, 7, nullptr, ground_only, 100);
    Expect(e.why == F::Why::NoBox && e.until == 100 + F::HoldNoBox,
           "r112j: no box: no verdict on the buffer's count, asked again");
    F::Box building = lamp_c;
    building.vertices = 5000;
    building.box = {0.0f, -6.0f, 0.0f, 6.0f, 0.5f, 6.0f}; // 6.5 m tall, 6 m wide
    e = F::Evaluate(k, 100, 100, 7, &building, ground_only, 100);
    Expect(e.why == F::Why::Shape, "r112j: a building part is refused by its shape");
    F::Box on_ground = lamp_c;
    on_ground.box = {0.0f, -9.9f, 0.0f, 0.29f, -9.69f, 0.29f};
    e = F::Evaluate(k, 100, 100, 7, &on_ground, ground_only, 100);
    Expect(e.why == F::Why::Grounded, "r112j: a small mesh on the ground is refused");
    F::StaticBook tally;
    F::Box over = lamp_c;
    over.vertices = 21000;
    F::Box more = lamp_c;
    more.vertices = 90000;
    tally.Set(5, F::Evaluate(k, 100, 100, 5, &over, ground_only, 100), 100);
    tally.Set(6, F::Evaluate(k, 100, 100, 6, &more, ground_only, 100), 100);
    own.vs = 0x97f2d384ull;
    own_d.vs = 0x97f2d384ull;
    tally.Set(10, own, 100);
    tally.Set(11, own_d, 100);
    tally.Set(10, own, 110);
    Expect(tally.big_n == 2 && tally.big_least == 21000 && tally.big_most == 90000 &&
               tally.taken.size() == 2,
           "r112j: the book counts the too big streams and keeps the candidates once");
    F::Stats roofed;
    roofed.roof_words = 5;
    roofed.roof_least = 0.1f;
    roofed.full_words = 2;
    const std::string taken_line = F::TakenLine(tally, k, roofed);
    Expect(Has(taken_line, "candidates 2") && Has(taken_line, "too big 2") &&
               Has(taken_line, "21000..90000") && Has(taken_line, "97f2d384") &&
               Has(taken_line, "1429 verts") && Has(taken_line, "5 words") &&
               taken_line.size() <= F::TakenChars,
           "r112j: the taken line");
    F::StaticBook many_taken;
    for (std::uint64_t s = 20; s < 30; ++s) {
        many_taken.Set(s, own, 100);
    }
    Expect(many_taken.taken.size() == F::TakenMost &&
               F::TakenLine(many_taken, k, F::Stats{}).size() <= F::TakenChars,
           "r112j: at most TakenMost candidates are kept, the line is capped");
    Expect(Has(F::TakenLine(F::StaticBook{}, k, F::Stats{}), "candidates 0") &&
               Has(F::TakenLine(F::StaticBook{}, k, F::Stats{}), "none"),
           "r112j: the taken line with none");
    // the roof
    Expect(F::ParseRoof(nullptr) == F::RoofDefault && F::ParseRoof("1") == 1.0f && F::ParseRoof("0.5") == 0.5f &&
               F::ParseRoof("7") == 1.0f && F::ParseRoof("-1") == 0.0f && F::ParseRoof("x") == F::RoofDefault,
           "r112j: the roof knob");
    Expect(std::fabs(F::RoofScale(0.1f, 0.1f, 0.0f) - 0.1f) < 1e-6f &&
               std::fabs(F::RoofScale(0.1f, 0.1f, 0.1f) - 0.1f) < 1e-6f &&
               std::fabs(F::RoofScale(0.1f, 0.1f, 0.3f) - 0.55f) < 1e-5f &&
               std::fabs(F::RoofScale(0.1f, 0.1f, 0.5f) - 1.0f) < 1e-6f &&
               std::fabs(F::RoofScale(0.1f, 0.1f, 1.0f) - 1.0f) < 1e-6f &&
               std::fabs(F::RoofScale(1.0f, 0.1f, 0.1f) - 1.0f) < 1e-6f &&
               std::fabs(F::RoofScale(0.1f, 0.0f, 0.0f) - 0.1f) < 1e-6f,
           "r112j: the roof scale ramps from the roof knob at the indoor share to 1 at 0.5 open");
    const std::uint32_t hang_word = BbWindHang::HangWord(2, 1, 77, 200);
    const BbWindSway::Unpacked half = BbWindSway::Unpack(F::ScaleRamp(hang_word, 0.5f));
    Expect(half.on && half.frame_slot == 2 && half.view == 1 && half.base_slot == 77 && half.ramp == 100 &&
               (F::ScaleRamp(hang_word, 0.5f) & BbWindHang::HangBit) != 0,
           "r112j: ScaleRamp scales the ramp byte and nothing else");
    Expect(F::ScaleRamp(0, 0.5f) == 0 && BbWindSway::Unpack(F::ScaleRamp(hang_word, 0.0f)).ramp == 0 &&
               F::ScaleRamp(hang_word, 1.0f) == hang_word && F::ScaleRamp(hang_word, 2.0f) == hang_word,
           "r112j: ScaleRamp: 0 stays 0, 1 and more change nothing");
    // the screen estimate
    F::BoxSet cam_set;
    Expect(!F::ScreenOf(cam_set, 0.0f, 0.0f, 10.0f).known, "r112j: no camera, no screen position");
    cam_set.view_ok = true;
    cam_set.view = {1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f};
    cam_set.proj = {1.428f, -2.5386f, 1.000017f, -0.050068f}; // (review) y scale signed: ndc +y down
    cam_set.render = {1280u, 720u};
    const F::Screen centre = F::ScreenOf(cam_set, 0.0f, 0.0f, 10.0f);
    Expect(centre.known && centre.ok && std::fabs(centre.x - 640.0f) < 1e-3f && std::fabs(centre.y - 360.0f) < 1e-3f,
           "r112j: straight ahead is the centre");
    const F::Screen right = F::ScreenOf(cam_set, 1.0f, 0.0f, 10.0f);
    const F::Screen up = F::ScreenOf(cam_set, 0.0f, 1.0f, 10.0f);
    Expect(right.ok && right.x > 700.0f && up.ok && up.y < 300.0f, "r112j: +x is right, +y is up");
    const F::Screen behind = F::ScreenOf(cam_set, 0.0f, 0.0f, -5.0f);
    Expect(behind.known && !behind.ok, "r112j: behind the camera");

"""

T4 = r"""    if (failures == 0) {
"""
T4P = r"""    // bbport (r112j_hang-static-verts): the survey with a camera read prints the screen estimate and the book's numbers
    {
        F::BoxSet seen_set;
        seen_set.Begin(0);
        seen_set.Add(Ground());
        F::Box lit = lantern;
        lit.vertices = 777;
        seen_set.Add(lit);
        seen_set.view_ok = true; // world y -6 .. -5.5 and z 0 .. 0.4 put 6 m up and 10 m ahead
        seen_set.view = {1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 6.0f, 0.0f, 0.0f, 1.0f, 10.0f};
        seen_set.proj = {1.428f, -2.5386f, 1.000017f, -0.050068f};
        seen_set.render = {1280u, 720u};
        F::StaticBook seen_book;
        seen_book.Set(7, F::Evaluate(k, 4096, 90000, 7, &lit, seen_set.All(), 0), 0);
        const std::vector<std::string> seen_lines = F::SurveyLines(k, seen_set, F::Draws{}, seen_book, 1200);
        Expect(seen_lines.size() == 2 && Has(seen_lines[1], " scr 658,338:") &&
                   Has(seen_lines[1], "book candidate 777v (stream said 90000v)"),
               "r112j: the survey line has the screen estimate and the numbers of the verdict");
    }

"""

# ---- vk_rasterizer.h -------------------------------------------------------------------------------
H1 = r"""    bool WindHangStaticAllowed(u64 positions, u32 positions_size, u32 stride, u64 frame);
"""
H1N = r"""    bool WindHangStaticAllowed(u64 positions, u32 positions_size, u32 stride, u64 frame, u64 vs = 0);
"""

# ---- vk_rasterizer_effects.cpp ---------------------------------------------------------------------
E1 = r"""bool Rasterizer::WindHangStaticAllowed(u64 positions, u32 positions_size, u32 stride, u64 frame) {
"""
E1N = r"""bool Rasterizer::WindHangStaticAllowed(u64 positions, u32 positions_size, u32 stride, u64 frame,
                                        u64 vs) {
"""

E2 = r"""        if (!WindHangStaticAllowed(positions, positions_size, stride, object_motion->Frame())) {
"""
E2N = r"""        if (!WindHangStaticAllowed(positions, positions_size, stride, object_motion->Frame(),
                                   pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash)) {
"""

E3 = r"""    const BbWindHangFind::Entry verdict = BbWindHangFind::Evaluate(
        BbWindHangFind::KnobOnce(), positions_size, positions_size / stride, positions,
        hang_find_boxes.Find(positions), hang_find_boxes.All(), frame);
    hang_static_book.Set(positions, verdict, frame);
"""
E3N = r"""    // bbport (r112j_hang-static-verts): the vertex test reads the mesh's own count from the scene's box (the
    // bytes over the stride are the buffer's); a stream with no box yet is NoBox and asked again
    BbWindHangFind::Entry verdict = BbWindHangFind::Evaluate(
        BbWindHangFind::KnobOnce(), positions_size, positions_size / stride, positions,
        hang_find_boxes.Find(positions), hang_find_boxes.All(), frame);
    verdict.vs = vs;
    hang_static_book.Set(positions, verdict, frame);
"""

E4 = r"""    hang_find_boxes.camera = camera;
    hang_find_boxes.camera_ok = camera_ok;
"""
E4N = r"""    if (camera_motion) { // bbport (r112j_hang-static-verts): the view and projection, for the survey's screen estimate
        const auto matrices = camera_motion->CameraMatrices();
        const auto size = camera_motion->RenderSize();
        hang_find_boxes.view = matrices.view;
        hang_find_boxes.proj = matrices.proj;
        hang_find_boxes.render = {size[0], size[1]};
        hang_find_boxes.view_ok = size[0] != 0 && size[1] != 0 && matrices.proj[0] != 0.0f &&
                                  matrices.proj[1] != 0.0f;
    }
"""

E5 = r"""    if (hang) { // bbport (r112_wind-more-things): its word (WindHangWord), counted in its lines
        return WindHangWord(words, frame_slot, view, taken.slot, taken.reset, positions, frame,
                            snapshot);
    }
"""
E5N = r"""    if (hang) { // bbport (r112_wind-more-things): its word (WindHangWord), counted in its lines
        u32 hang_word = WindHangWord(words, frame_slot, view, taken.slot, taken.reset, positions, frame,
                                     snapshot);
        // bbport (r112j_hang-static-verts): a static hanging thing's push is scaled while the camera is under a
        // roof by r117's field (BB_WIND_HANG_STATIC_ROOF; RoofScale: the roof knob at or under the indoor share,
        // 1 from 0.5 of the wind open); the GPU also scales every vertex by the field at the vertex
        if (hang_static && hang_word != 0 && wind_shelter != nullptr &&
            BbWindHangFind::RoofKnob() < 1.0f) {
            const float scale = BbWindHangFind::RoofScale(
                BbWindHangFind::RoofKnob(), BbWindHangActors::KnobOnce().indoor, wind_shelter->CameraOpen());
            if (scale < 1.0f) {
                ++hang_find_stats.roof_words;
                hang_find_stats.roof_least = std::min(hang_find_stats.roof_least, scale);
            } else {
                ++hang_find_stats.full_words;
            }
            hang_word = BbWindHangFind::ScaleRamp(hang_word, scale);
        }
        return hang_word;
    }
"""

E6 = r"""            BbReport::Printf("%s\n", static_line.c_str());
"""
E6N = r"""            // bbport (r112j_hang-static-verts): the candidates and the numbers the vertex test compared
            BbReport::Printf("%s\n",
                             BbWindHangFind::TakenLine(hang_static_book, BbWindHangFind::KnobOnce(),
                                                       hang_find_stats)
                                 .c_str());
"""

E7 = r"""        BbReport::Printf("%s\n", BbWindHangFind::OnceText(BbWindHangFind::KnobOnce()).c_str());
"""
E7N = r"""        BbReport::Printf("%s\n", BbWindHangFind::OnceTextJ(BbWindHangFind::KnobOnce(),
                                                           BbWindHangFind::RoofKnob(),
                                                           BbWindHangActors::KnobOnce().indoor)
                                     .c_str()); // bbport (r112j_hang-static-verts)
"""

# ---- README.md -------------------------------------------------------------------------------------
R1 = r"""its position stream has at most `BB_WIND_HANG_STATIC_VERTS` vertices (no building, no big batch)"""
R1N = r"""the mesh (its own vertex count: the ray traced scene's index range of its draw, r112j; not the bytes of the buffer its stream lies in) has at most `BB_WIND_HANG_STATIC_VERTS` vertices (no building, no big batch)"""
R2 = r"""the most vertices of a candidate's position stream (64 to 1000000, default 20000)"""
R2N = r"""the most vertices of a candidate mesh, its own count (r112j: the ray traced scene's index range of its draw; 64 to 1000000, default 20000)"""
R3 = r"""| `BB_WIND_HANG_FIND` |"""
R3P = r"""| `BB_WIND_HANG_STATIC_ROOF` | Part of `BB_WIND_HANG_STATIC` (r112j; 0 to 1, default `0.1`; text that is no number gives the default; `1` leaves it out). The push of a static hanging thing (a lantern, chain or cage) is scaled by this much while the camera is under a roof by r117's shelter field (`BB_WIND_SHELTER`): at or under the indoor share of `BB_WIND_HANG_INDOOR` (0.1) of the wind open it is this fraction, rising smoothly to the whole push at 0.5 open, so a lantern seen from inside is near still and nothing pops when the camera walks in or out. r112h's refusal of a stream first judged with the camera indoors stays. Without the shelter field nothing changes. The log says "Wind sway hang (r112j)" once and every 600 frames (the candidates, the vertex counts compared, the scaled words). |
"""

EDITS = {
NF: [
('rep', F1, "", F1N),
('rep', F2, "", F2N),
('ins', F3, "", F3N),
('rep', F4, "", F4N),
('ins', F5, "", F5N),
('ins', F6, F6P, ""),
('ins', F7, "", F7N),
('rep', F8, "", F8N),
('ins', F9, F9P, ""),
('ins', F10, F10P, ""),
('ins', F11, "", F11N),
('rep', F12, "", F12N),
('ins', F13, "", F13N),
('rep', F14, "", F14N),
('rep', F15, "", F15N),
('rep', F16, "", F16N),
],
NT: [
('rep', T1, "", T1N),
('rep', T2, "", T2N),
('ins', T3, T3P, ""),
('ins', T4, T4P, ""),
],
RH: [
('rep', H1, "", H1N),
],
RE: [
('rep', E1, "", E1N),
('rep', E2, "", E2N),
('rep', E3, "", E3N),
('ins', E4, "", E4N),
('rep', E5, "", E5N),
('ins', E6, "", E6N),
('ins', E7, "", E7N),
],
RM: [
('rep', R1, "", R1N),
('rep', R2, "", R2N),
('ins', R3, R3P, ""),
],
}

ORDER = (NF, NT, RH, RE, RM)


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


def text_checks(texts):
    """The ties a compiler cannot check."""
    nf, nt, re_, rh = texts[NF], texts[NT], texts[RE], texts[RH]
    for needle in ("e.verts = b->vertices;", "std::uint32_t stream_verts", "TakenLine(", "RoofScale(",
                   "ScaleRamp(", "ScreenOf(", "OnceTextJ("):
        if needle not in nf:
            raise SystemExit("text check: %s missing in the header" % needle)
    if "e.verts = verts;" in nf or "if (verts > k.verts)" in nf:
        raise SystemExit("text check: the stream's byte count is still tested")
    # the verdict compares the box's count: the NoBox return comes before the TooBig return
    ev = nf[nf.index("inline Entry Evaluate("):]
    if ev.index("Why::NoBox") > ev.index("Why::TooBig"):
        raise SystemExit("text check: Evaluate tests the count before the box")
    # the taken constants are defined before use (TakenMost in Set, TakenChars in TakenLine)
    if nf.index("TakenMost =") > nf.index("taken.size() >= TakenMost"):
        raise SystemExit("text check: TakenMost is used before its definition")
    if nf.index("struct Screen {") > nf.index("inline std::vector<std::string> SurveyLines("):
        raise SystemExit("text check: Screen comes after the survey")
    # the call chain in the rasterizer
    if "u64 frame, u64 vs = 0);" not in rh:
        raise SystemExit("text check: the declaration has no vs")
    if "u64 vs) {" not in re_ or "verdict.vs = vs;" not in re_:
        raise SystemExit("text check: the definition does not take or store vs")
    if re_.count("BbWindHangFind::TakenLine(") != 1 or re_.count("BbWindHangFind::OnceTextJ(") != 1:
        raise SystemExit("text check: the report lines are not hooked once")
    if "hang_find_stats = {};" not in re_:
        raise SystemExit("text check: the stats reset is missing")
    if re_.index("BbWindHangFind::TakenLine(") > re_.index("hang_find_stats = {};"):
        raise SystemExit("text check: the taken line must print before the stats reset")
    if re_.count("BbWindHangFind::ScaleRamp(") != 1:
        raise SystemExit("text check: the roof scaling is not hooked once")
    # the test calls Evaluate with its 7 arguments (no stale call with the old meaning)
    if nt.count("F::TakenLine(") < 4 or "r112j: the taken line" not in nt:
        raise SystemExit("text check: the tests of the taken line are missing")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112J_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == NF and "BbWindHangFind::Evaluate" not in cur and "inline Entry Evaluate(" not in cur:
            raise SystemExit("REFUSED: r112i_hang-find-lanterns must be applied (Evaluate)")
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

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
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
            tmp = full + ".r112jtmp"
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
        tmp = full + ".r112jtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


if __name__ == "__main__":
    main()
