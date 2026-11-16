// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112i_hang-find-lanterns): static meshes that hang (gpu/shim/bbport_wind_hang_find.h): the
// knobs, the pipeline test, the ground rule (Clearance), the verdict on a stream (Evaluate), the book,
// the box set, the draws' join and the survey's lines. The twin in Python (r112i_twin.py) holds the
// same scenes.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "gpu/shim/bbport_wind_hang_find.h"
#include "gpu/shim/bbport_test_goto_hang.h" // bbport (r112n_hang-teleport-camera)

namespace F = BbWindHangFind;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

struct Stage {
    bool has_discard = false;
};

F::Box MakeBox(std::uint64_t stream, float x0, float y0, float z0, float x1, float y1, float z1) {
    F::Box b;
    b.stream = stream;
    b.box = {x0, y0, z0, x1, y1, z1};
    b.src = 'c';
    b.vertices = 100;
    b.triangles = 150;
    return b;
}

// a 40 m square of ground (bottom -10, top -9.5)
F::Box Ground() {
    return MakeBox(1, -20.0f, -10.0f, -20.0f, 20.0f, -9.5f, 20.0f);
}

bool Has(const std::string& text, const char* part) {
    return text.find(part) != std::string::npos;
}
} // namespace

int main() {
    // the knobs: defaults, off, ranges, junk
    const F::Knobs d = F::ParseKnobs(nullptr, nullptr, nullptr, nullptr, nullptr);
    Expect(d.static_on && !d.find && d.verts == 20000 && d.height_hi == 2.0f && d.clear == 1.0f,
           "knobs: defaults");
    const F::Knobs off = F::ParseKnobs("0", "1", nullptr, nullptr, nullptr);
    Expect(!off.static_on && off.find, "knobs: STATIC=0 is off, FIND=1 is on");
    const F::Knobs odd = F::ParseKnobs("yes", "11", nullptr, nullptr, nullptr);
    Expect(odd.static_on && !odd.find, "knobs: other text is on for STATIC, FIND is exactly 1");
    const F::Knobs wide = F::ParseKnobs("1", nullptr, "9999999", "50", "900");
    Expect(wide.verts == F::VertsHigh && wide.height_hi == F::HeightHiMax && wide.clear == F::ClearMax,
           "knobs: held to their ranges");
    const F::Knobs low = F::ParseKnobs("1", nullptr, "1", "0", "-3");
    Expect(low.verts == F::VertsLow && low.height_hi == F::HeightLo && low.clear == 0.0f,
           "knobs: held at the low end");
    const F::Knobs junk = F::ParseKnobs("1", nullptr, "abc", "nan", "x");
    Expect(junk.verts == 20000 && junk.height_hi == 2.0f && junk.clear == 1.0f,
           "knobs: text that is no number gives the defaults");

    // the pipeline test
    const Stage solid{false}, cut{true};
    Expect(F::WantedWith(true, true, &solid), "wanted: opaque with the Sway bit");
    Expect(F::WantedWith(true, true, static_cast<const Stage*>(nullptr)), "wanted: no pixel shader");
    Expect(!F::WantedWith(true, true, &cut), "wanted: a cut-out is the twigs'");
    Expect(!F::WantedWith(true, false, &solid), "wanted: no Sway bit");
    Expect(!F::WantedWith(false, true, &solid), "wanted: the path is off");

    // the ground rule
    const F::Knobs k = d;
    std::vector<F::Box> scene{Ground()};
    const F::Box lantern = MakeBox(7, 0.0f, -6.0f, 0.0f, 0.4f, -5.5f, 0.4f);
    F::Ground g = F::Clearance(lantern.box, lantern.stream, scene, k.clear);
    Expect(g.known && g.free && std::fabs(g.above - 4.0f) < 1e-4f, "ground: a lantern 4 m up hangs");
    Expect(g.support && std::fabs(g.gap - 3.5f) < 1e-4f && !g.stands && !g.held,
           "ground: the ground under it is far, nothing touches it");
    const F::Box low_one = MakeBox(7, 0.0f, -9.9f, 0.0f, 0.4f, -9.4f, 0.4f);
    g = F::Clearance(low_one.box, 7, scene, k.clear);
    Expect(g.known && !g.free && std::fabs(g.above - 0.1f) < 1e-4f, "ground: 0.1 m up is no hanging");
    const F::Box at_clear = MakeBox(7, 0.0f, -9.0f, 0.0f, 0.4f, -8.5f, 0.4f);
    g = F::Clearance(at_clear.box, 7, scene, k.clear);
    Expect(!g.free, "ground: exactly the clearance does not hang");
    scene.push_back(MakeBox(2, 0.1f, -10.0f, 0.1f, 0.3f, -4.0f, 0.3f)); // a post through it
    g = F::Clearance(lantern.box, 7, scene, k.clear);
    Expect(g.stands && g.held && !g.free, "ground: a thin post through it holds it rigid");
    scene.pop_back();
    scene.push_back(MakeBox(3, -5.0f, -10.0f, -5.0f, 5.0f, 10.0f, 5.0f)); // a tree, 10 m wide
    g = F::Clearance(lantern.box, 7, scene, k.clear);
    Expect(g.free && !g.stands && !g.held, "ground: a lantern in a tree hangs (a wide box is no post)");
    scene.pop_back();
    scene.push_back(MakeBox(4, 0.0f, -6.5f, 0.0f, 0.4f, -6.1f, 0.4f)); // a shelf 0.1 m under it
    g = F::Clearance(lantern.box, 7, scene, k.clear);
    Expect(g.support && std::fabs(g.gap - 0.1f) < 1e-4f && !g.free, "ground: a box under it holds it");
    scene.pop_back();
    scene.push_back(MakeBox(7, 0.0f, -10.0f, 0.0f, 0.4f, 5.0f, 0.4f)); // its own stream's box
    g = F::Clearance(lantern.box, 7, scene, k.clear);
    Expect(g.free, "ground: the boxes of its own stream do not count");
    scene.pop_back();
    const std::vector<F::Box> none;
    g = F::Clearance(lantern.box, 7, none, k.clear);
    Expect(!g.known && !g.free, "ground: no box near gives no ground");
    const std::vector<F::Box> far_scene{MakeBox(5, 30.0f, -10.0f, 30.0f, 40.0f, -9.5f, 40.0f)};
    g = F::Clearance(lantern.box, 7, far_scene, k.clear);
    Expect(!g.known, "ground: a box 30 m away is no ground");
    const std::vector<F::Box> wide_scene{MakeBox(6, -50.0f, -10.0f, -50.0f, 50.0f, -9.5f, 50.0f)};
    g = F::Clearance(lantern.box, 7, wide_scene, k.clear);
    Expect(!g.known, "ground: a box over 60 m wide is no reference");

    // the verdict on a stream
    const std::vector<F::Box> ground_only{Ground()};
    F::Box heavy = lantern; // bbport (r112j): the mesh's own count is tested, not the buffer's
    heavy.vertices = 30000;
    F::Entry e = F::Evaluate(k, 4096, 500, 7, &heavy, ground_only, 100);
    Expect(e.why == F::Why::TooBig && e.until == 100 + F::HoldBig && e.verts == 30000 &&
               e.stream_verts == 500,
           "evaluate: too many vertices");
    e = F::Evaluate(k, 4096, 500, 7, nullptr, ground_only, 100);
    Expect(e.why == F::Why::NoBox && e.until == 100 + F::HoldNoBox, "evaluate: no box");
    const F::Box tall = MakeBox(7, 0.0f, -6.0f, 0.0f, 0.4f, -3.0f, 0.4f);
    e = F::Evaluate(k, 4096, 500, 7, &tall, ground_only, 100);
    Expect(e.why == F::Why::Shape, "evaluate: 3 m tall is no lantern");
    const F::Box flat = MakeBox(7, 0.0f, -6.0f, 0.0f, 0.4f, -5.95f, 0.4f);
    e = F::Evaluate(k, 4096, 500, 7, &flat, ground_only, 100);
    Expect(e.why == F::Why::Shape, "evaluate: 0.05 m tall is not either");
    const F::Box broad = MakeBox(7, 0.0f, -6.0f, 0.0f, 4.0f, -5.5f, 0.4f);
    e = F::Evaluate(k, 4096, 500, 7, &broad, ground_only, 100);
    Expect(e.why == F::Why::Shape, "evaluate: 4 m wide is a roof, not a lantern");
    e = F::Evaluate(k, 4096, 500, 7, &lantern, none, 100);
    Expect(e.why == F::Why::NoGround && e.until == 100 + F::HoldNoGround, "evaluate: no ground");
    e = F::Evaluate(k, 4096, 500, 7, &low_one, ground_only, 100);
    Expect(e.why == F::Why::Grounded && e.until == 100 + F::HoldGround, "evaluate: on the ground");
    e = F::Evaluate(k, 4096, 500, 7, &lantern, ground_only, 100);
    Expect(e.why == F::Why::Ok && e.until == 100 + F::KeepCandidate && e.verts == 100 &&
               e.stream_verts == 500 &&
               e.size == 4096 && std::fabs(e.height - 0.5f) < 1e-4f && std::fabs(e.above - 4.0f) < 1e-4f,
           "evaluate: a lantern 4 m up is a candidate");
    F::Knobs strict = k;
    strict.height_hi = 0.4f;
    e = F::Evaluate(strict, 4096, 500, 7, &lantern, ground_only, 100);
    Expect(e.why == F::Why::Shape, "evaluate: the height limit is a knob");

    // bbport (r112j_hang-static-verts): the number tested is the mesh's own, not the buffer's bytes over its stride
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

    // the book
    F::StaticBook book;
    Expect(!book.Peek(7, 4096, 100).known, "book: an unknown stream");
    book.Set(7, F::Evaluate(k, 4096, 500, 7, &lantern, ground_only, 100), 100);
    F::StaticBook::Look look = book.Peek(7, 4096, 150);
    Expect(look.known && look.pass, "book: a candidate stands");
    Expect(!book.Peek(7, 8192, 150).known, "book: another size at the address is another mesh");
    Expect(book.Peek(7, 0, 150).known, "book: size 0 is not known: the verdict stands");
    Expect(!book.Peek(7, 4096, 100 + F::KeepCandidate).known, "book: the verdict runs out");
    book.Set(8, F::Evaluate(k, 4096, 500, 8, &low_one, ground_only, 100), 100);
    look = book.Peek(8, 4096, 101);
    Expect(look.known && !look.pass, "book: a refusal stands");
    Expect(book.by_why[static_cast<std::size_t>(F::Why::Ok)] == 1 &&
               book.by_why[static_cast<std::size_t>(F::Why::Grounded)] == 1 && book.Size() == 2,
           "book: the verdicts are counted");
    F::StaticBook full;
    for (std::uint64_t s = 1; s <= F::BookMost; ++s) {
        F::Entry shortlived;
        shortlived.until = 10;
        full.Set(s, shortlived, 5);
    }
    Expect(full.Size() == F::BookMost, "book: filled to BookMost");
    F::Entry later;
    later.until = 1000;
    full.Set(F::BookMost + 100, later, 20); // the old ones have run out: they go
    Expect(full.Size() == 1, "book: expired verdicts go first");
    F::StaticBook crowded;
    for (std::uint64_t s = 1; s <= F::BookMost; ++s) {
        F::Entry standing;
        standing.until = 1000;
        crowded.Set(s, standing, 5);
    }
    crowded.Set(F::BookMost + 100, later, 20); // none has run out at frame 20: all go
    Expect(crowded.Size() == 1, "book: a full book of standing verdicts is cleared");

    // the box set
    F::BoxSet set;
    Expect(!set.Fresh(5), "boxes: none read");
    set.Begin(10);
    set.Add(MakeBox(7, 0.0f, 0.0f, 0.0f, 1.0f, 1.0f, 1.0f));
    set.Add(MakeBox(7, 5.0f, 0.0f, 0.0f, 6.0f, 1.0f, 1.0f));
    set.Add(MakeBox(0, 9.0f, 0.0f, 0.0f, 9.5f, 1.0f, 1.0f));
    Expect(set.Fresh(10) && set.Fresh(69) && !set.Fresh(70) && !set.Fresh(9), "boxes: fresh for 60 frames");
    Expect(set.All().size() == 3 && set.Find(7) != nullptr && set.Find(7)->box[0] == 0.0f &&
               set.Find(0) == nullptr && set.Find(9) == nullptr,
           "boxes: the first box of a stream is found, stream 0 is not");
    set.Begin(100);
    Expect(set.All().empty() && set.Find(7) == nullptr && set.Fresh(100), "boxes: begun again");

    // the draws
    F::Draws draws;
    F::Seen cam;
    cam.vs = 0xabc;
    cam.ps = 0xdef;
    cam.camera = true;
    cam.indices = 300;
    cam.frame = 5;
    F::Seen sun = cam;
    sun.vs = 0x111;
    sun.camera = false;
    sun.frame = 6;
    draws.Note(7, sun);
    Expect(draws.Find(7) != nullptr && draws.Find(7)->vs == 0x111, "draws: a sun pass draw is kept");
    draws.Note(7, cam);
    Expect(draws.Find(7)->vs == 0xabc, "draws: the camera pass's replaces it");
    draws.Note(7, sun);
    Expect(draws.Find(7)->vs == 0xabc && draws.Find(7)->frame == 6, "draws: and stays");
    draws.Note(0, cam);
    Expect(draws.Size() == 1, "draws: stream 0 is not noted");

    // the survey
    F::BoxSet world;
    world.Begin(0);
    world.Add(Ground());
    F::Box hung = lantern;
    hung.vertices = 777;
    hung.triangles = 900;
    world.Add(hung);
    world.Add(MakeBox(9, 6.0f, -10.0f, 6.0f, 6.4f, -7.0f, 6.4f)); // a 3 m post: no fit
    world.Add(MakeBox(8, 0.0f, -9.9f, 0.0f, 0.4f, -9.4f, 0.4f)); // on the ground: fits, not hanging
    world.camera_ok = true;
    world.camera = {0.0f, -6.0f, 5.0f};
    F::Draws seen_draws;
    seen_draws.Note(7, cam);
    F::StaticBook shown;
    shown.Set(7, F::Evaluate(k, 4096, 777, 7, &hung, world.All(), 0), 0);
    const std::vector<std::string> lines = F::SurveyLines(k, world, seen_draws, shown, 1200);
    Expect(lines.size() == 2, "survey: a header and the one that hangs");
    if (lines.size() == 2) {
        Expect(Has(lines[0], "survey at frame 1200") && Has(lines[0], "4 scene boxes") &&
                   Has(lines[0], "2 fit") && Has(lines[0], "1 hang free") &&
                   Has(lines[0], "camera read"),
               "survey: the header counts");
        Expect(Has(lines[1], "A stream 00000007") && Has(lines[1], "vs 00000abc") &&
                   Has(lines[1], "ps 00000def") && Has(lines[1], "static") &&
                   Has(lines[1], "idx 300") && Has(lines[1], "verts 777") &&
                   Has(lines[1], "FREE") && Has(lines[1], "above 4.00") &&
                   Has(lines[1], "book candidate"),
               "survey: the candidate's line");
        Expect(lines[0].size() <= F::LineCharsK && lines[1].size() <= F::LineCharsK, "survey: lines are capped");
    }
    world.camera = {500.0f, -6.0f, 500.0f};
    const std::vector<std::string> far_lines = F::SurveyLines(k, world, seen_draws, shown, 1200);
    Expect(far_lines.size() == 1 && Has(far_lines[0], "of them over 60 m away"),
           "survey: a candidate far from the camera is only counted");
    world.camera_ok = false;
    const std::vector<std::string> no_camera = F::SurveyLines(k, world, F::Draws{}, F::StaticBook{}, 1);
    Expect(no_camera.size() == 2 && Has(no_camera[0], "camera unread") && Has(no_camera[1], "vs n/a") &&
               Has(no_camera[1], "book -") && Has(no_camera[1], "dist n/a"),
           "survey: without the camera or the draws it still lists, with n/a");
    F::BoxSet many;
    many.Begin(0);
    many.Add(Ground());
    for (std::uint64_t i = 0; i < 40; ++i) {
        many.Add(MakeBox(100 + i, float(i) * 0.1f, -6.0f, 0.0f, float(i) * 0.1f + 0.2f, -5.5f, 0.2f));
    }
    const std::vector<std::string> capped = F::SurveyLines(k, many, F::Draws{}, F::StaticBook{}, 1);
    Expect(capped.size() == 1 + F::ListMost, "survey: at most ListMost candidate lines");

    // the once-line and the static line
    F::Stats stats;
    stats.draws = 12;
    stats.refused = 7;
    stats.passed = 3;
    stats.judged = 2;
    const std::string line = F::StaticLine(stats, book, k, 600);
    Expect(Has(line, "static draws in 600 frames: 12 asked, 7 refused") && Has(line, "3 candidate draws") &&
               Has(line, "1 candidate") && Has(line, "1 grounded") && Has(line, "2 in the book"),
           "static line: counts");
    const std::string once = F::OnceText(k);
    Expect(Has(once, "BB_WIND_HANG_STATIC=1") && Has(once, "20000 vertices") && Has(once, "survey") &&
               Has(once, "off"),
           "once line");

    // bbport (r112j_hang-static-verts): the survey with a camera read prints the screen estimate and the book's numbers
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

    // bbport (r112l_hang-discard-lanterns): cut-outs reach the static path, the static push gain, the tall rule
    {
        Expect(F::Cuts(&cut) && !F::Cuts(&solid) && !F::Cuts(static_cast<const Stage*>(nullptr)),
               "r112l: Cuts names a pixel shader that discards");
        Expect(F::WantedCutWith(true, true, true, &cut) && F::WantedCutWith(true, true, true, &solid) &&
                   !F::WantedCutWith(true, false, true, &cut) && F::WantedCutWith(true, false, true, &solid) &&
                   !F::WantedCutWith(true, true, false, &cut) && !F::WantedCutWith(false, true, true, &cut) &&
                   F::WantedCutWith(true, true, true, static_cast<const Stage*>(nullptr)),
               "r112l: a cut-out passes with the cut knob, an opaque one always; no Sway bit or no path: neither");
        Expect(F::ParseCut(nullptr) && F::ParseCut("1") && !F::ParseCut("0") && F::ParseCut("00") && F::ParseCut(""),
               "r112l: the cut knob is on unless exactly 0");
        Expect(F::ParseGain(nullptr) == F::GainDefault && F::ParseGain("0.5") == 0.5f && F::ParseGain("9") == 1.0f &&
                   F::ParseGain("-1") == 0.0f && F::ParseGain("x") == F::GainDefault,
               "r112l: the gain is held to 0..1");
        Expect(F::ParseTall(nullptr) == F::TallDefault && F::ParseTall("99") == F::UnionMax &&
                   F::ParseTall("0.01") == BbWindHang::MinExtent && F::ParseTall("x") == F::TallDefault &&
                   F::ParseTall("3") == 3.0f,
               "r112l: the tall limit is held to MinExtent..UnionMax");

        // the gain on a ramp byte
        Expect(F::GainRamp(255, 0.2f) == 51 && F::GainRamp(0, 0.2f) == 0 && F::GainRamp(255, 2.0f) == 255 &&
                   F::GainRamp(255, -1.0f) == 0 && F::GainRamp(100, 1.0f) == 100,
               "r112l: the gain scales the ramp byte");

        // the push at the strongest test wind: 3 to 10 cm at 4 m/s, less at 1.5 m/s
        const F::PushSource strong = F::PushSourceOf(true, 4.0f, 1.0f, 3.0f);
        const F::PushSource gale = F::PushSourceOf(true, 4.0f, 1.5f, 3.0f);
        const F::PushSource breeze = F::PushSourceOf(true, 1.5f, 1.0f, 3.0f);
        const F::PushSource breeze_gust = F::PushSourceOf(true, 1.5f, 1.5f, 3.0f);
        const float at_strong = F::StaticPush(strong, F::GainDefault);
        Expect(std::fabs(at_strong - 0.08f) < 1e-4f && std::fabs(F::StaticPush(gale, F::GainDefault) - 0.08f) < 1e-4f &&
                   at_strong >= 0.03f && at_strong <= 0.10f,
               "r112l: a static candidate is pushed 8 cm at 4 m/s, held by MaxAlong x gain also in the strongest gust");
        Expect(F::StaticPush(breeze, F::GainDefault) < 0.02f && F::StaticPush(breeze_gust, F::GainDefault) < 0.03f &&
                   F::StaticPush(breeze, F::GainDefault) < at_strong,
               "r112l: less at 1.5 m/s");
        Expect(F::StaticPush(strong, 1.0f) == strong.now && F::StaticPush(strong, 0.0f) == 0.0f &&
                   F::StaticPush(F::PushSourceOf(true, 0.0f, 1.0f, 3.0f), F::GainDefault) == 0.0f,
               "r112l: gain 1 is the old push, gain 0 and no wind none");

        // the tall rule: the b55 graveyard's candidates and a low one
        F::Entry e_graveyard; // stream E: 0.89 m scene box, 2.51 m over the ground
        e_graveyard.height = 0.89f;
        e_graveyard.above = 2.51f;
        F::Entry d_graveyard; // stream D: 0.94 m, 7.51 m up
        d_graveyard.height = 0.94f;
        d_graveyard.above = 7.51f;
        F::Entry low_place; // 1.2 m over the ground: a hook on a wall, a sign
        low_place.height = 0.9f;
        low_place.above = 1.2f;
        F::Entry big_place; // up to the 2 m the shape test allows
        big_place.height = 1.9f;
        big_place.above = 5.0f;
        Expect(F::ClearlyHanging(e_graveyard) && F::ClearlyHanging(d_graveyard) && !F::ClearlyHanging(low_place) &&
                   !F::ClearlyHanging(big_place),
               "r112l: a small mesh well over the ground clearly hangs");
        Expect(F::SpanLimitWith(12.0f, 2.5f, e_graveyard) == 12.0f && F::SpanLimitWith(12.0f, 2.5f, low_place) == 2.5f &&
                   F::SpanLimitWith(12.0f, 9.0f, low_place) == BbWindHang::MaxExtent &&
                   F::SpanLimitWith(12.0f, 2.5f, big_place) == 2.5f,
               "r112l: the union limit for a mesh that clearly hangs, the tall limit (held to 4 m) for the others");
        const std::uint32_t tall_base = BbWindSway::HeightKey(-39.48f);
        const std::uint32_t tall_top = BbWindHang::TopKey(-29.6f); // 9.88 m of keys: the union of the places of stream E
        const float lim_clear = F::SpanLimitWith(F::UnionDefault, F::TallDefault, e_graveyard);
        const float lim_low = F::SpanLimitWith(F::UnionDefault, F::TallDefault, low_place);
        BbWindHang::Entry kept;
        BbWindHang::Measure(kept, true, 100, &tall_base, &tall_top, 1.0, lim_clear);
        const BbWindHang::Measured kept_m =
            BbWindHang::Measure(kept, false, 100 + BbWindHang::JudgeFrames, &tall_base, &tall_top, 1.0, lim_clear);
        Expect(kept.judged && kept.fits && kept_m.swing && std::fabs(kept.top - kept.base - 9.88f) < 0.02f,
               "r112l: 9.88 m of keys of a clearly hanging lantern are the union of its places: kept");
        BbWindHang::Entry refused;
        BbWindHang::Measure(refused, true, 100, &tall_base, &tall_top, 1.0, lim_low);
        const BbWindHang::Measured refused_m =
            BbWindHang::Measure(refused, false, 100 + BbWindHang::JudgeFrames, &tall_base, &tall_top, 1.0, lim_low);
        Expect(refused.judged && !refused.fits && !refused_m.swing,
               "r112l: the same keys of a mesh that does not clearly hang: refused as too tall");

        // the lines
        BbWindHang::Book spans;
        spans.Note(7, 4096, 0, true, 100, 0x6a833138ull);
        spans.Note(8, 4096, 0, true, 100, 0x9da6aacbull);
        spans.Note(9, 4096, 0, true, 100, 0x63220f67ull);
        BbWindHang::Entry* const span_e = spans.Find(7);
        BbWindHang::Entry* const span_d = spans.Find(8);
        BbWindHang::Entry* const span_l = spans.Find(9);
        Expect(span_e != nullptr && span_d != nullptr && span_l != nullptr, "r112l: the test's book has its entries");
        if (span_e != nullptr && span_d != nullptr && span_l != nullptr) {
            const std::uint32_t d_base = BbWindSway::HeightKey(-34.78f);
            const std::uint32_t d_top = BbWindHang::TopKey(-33.84f);
            BbWindHang::Measure(*span_e, true, 100, &tall_base, &tall_top, 1.0, lim_clear);
            BbWindHang::Measure(*span_e, false, 100 + BbWindHang::JudgeFrames, &tall_base, &tall_top, 1.0, lim_clear);
            BbWindHang::Measure(*span_d, true, 100, &d_base, &d_top, 1.0, lim_clear);
            BbWindHang::Measure(*span_d, false, 100 + BbWindHang::JudgeFrames, &d_base, &d_top, 1.0, lim_clear);
            BbWindHang::Measure(*span_l, true, 100, &tall_base, &tall_top, 1.0, lim_low);
            BbWindHang::Measure(*span_l, false, 100 + BbWindHang::JudgeFrames, &tall_base, &tall_top, 1.0, lim_low);
            F::StaticBook shelf;
            F::Entry candidate = F::Evaluate(d, 4096, 500, 7, &lantern, ground_only, 100);
            candidate.vs = 0x6a833138ull;
            candidate.height = 0.89f;
            candidate.above = 2.51f;
            shelf.Set(7, candidate, 100);
            candidate.vs = 0x9da6aacbull;
            candidate.height = 0.94f;
            candidate.above = 7.51f;
            shelf.Set(8, candidate, 100);
            candidate.vs = 0x63220f67ull;
            candidate.height = 0.9f;
            candidate.above = 1.2f;
            shelf.Set(9, candidate, 100);
            const std::string tall_line = F::TallText(shelf, spans, F::UnionDefault, F::TallDefault);
            Expect(Has(tall_line, "vs 6a833138 keys 9.88 m (over it, kept: clearly hanging; scene 0.89 m, 2.51 m up, "
                                  "limit 12.0 m)") &&
                       Has(tall_line, "vs 9da6aacb keys 0.94 m (within the tall limit;") &&
                       Has(tall_line, "vs 63220f67 keys 9.88 m (refused: over it, not clearly hanging; scene 0.90 m, "
                                      "1.20 m up, limit 2.5 m)") &&
                       tall_line.size() <= 700,
                   "r112l: the keys' span line says kept, within and refused");
        }
        BbWindHang::Book unread;
        F::StaticBook none_taken;
        Expect(Has(F::TallText(none_taken, unread, F::UnionDefault, F::TallDefault), "none"), "r112l: no candidate");

        // the other lines and the survey's mark
        F::Stats cs;
        cs.gpu_asked = 300;
        cs.cut_asked = 120;
        cs.cut_passed = 40;
        const std::string cut_line = F::CutLine(cs, true, F::GainDefault, strong);
        Expect(Has(cut_line, "(r112l)") && Has(cut_line, "BB_WIND_HANG_STATIC_CUT=1") &&
                   Has(cut_line, "120 draws asked, 40 of a candidate stream") && Has(cut_line, "gain 0.20") &&
                   Has(cut_line, "pushed 0.080 m now") && Has(cut_line, "at most 0.080 m") &&
                   Has(F::CutLine(cs, false, 1.0f, breeze), "CUT=0"),
               "r112l: the counters line");
        const std::string once_l = F::OnceTextL(true, F::GainDefault, F::TallDefault);
        Expect(Has(once_l, "(r112l)") && Has(once_l, "'disc 1' with 'asked 0, book -'") &&
                   Has(once_l, "BB_WIND_HANG_STATIC_CUT=1") && Has(once_l, "0.20 of the sway's") &&
                   Has(once_l, "at most 0.080 m") && Has(once_l, "2.5 m (BB_WIND_HANG_STATIC_TALL") &&
                   Has(F::OnceTextL(false, 1.0f, 40.0f), "CUT=0"),
               "r112l: the once line");
        F::Routes cut_routes;
        cut_routes.Note(7, 'P', true, true, false, false, 1);
        cut_routes.Note(8, 'P', true, false, false, false, 1);
        Expect(F::CutNote(&cut_routes, 7, true) == " [cut-out: offered]" &&
                   Has(F::CutNote(&cut_routes, 7, false), "held back, CUT=0") && F::CutNote(&cut_routes, 8, true).empty() &&
                   F::CutNote(&cut_routes, 9, true).empty() && F::CutNote(nullptr, 7, true).empty(),
               "r112l: the survey marks a stream whose pixel shader discards");
        F::BoxSet cut_set;
        cut_set.Begin(0);
        cut_set.Add(Ground());
        F::Box cut_box = lantern;
        cut_box.stream = 7;
        cut_box.vertices = 777;
        cut_set.Add(cut_box);
        F::Draws cut_draws; // cam.vs is 0xabc
        cut_draws.Note(7, cam);
        F::StaticBook cut_book;
        const std::vector<std::string> cut_lines = F::SurveyLines(k, cut_set, cut_draws, cut_book, 10, &cut_routes);
        Expect(cut_lines.size() == 2 && Has(cut_lines[1], "route P bit 1 disc 1") &&
                   Has(cut_lines[1], "[cut-out: offered]") && cut_lines[1].size() <= F::LineCharsK,
               "r112l: the survey line of a cut-out stream carries the mark after its route");
    }

    // bbport (r112m_hang-close-proof): the candidates' state lines, the tall rule on the scene box, the same-bottom push
    {
        Expect(F::ParseSame(nullptr) && F::ParseSame("1") && !F::ParseSame("0") && F::ParseSame("00") && F::ParseSame(""),
               "r112m: the same-bottom knob is on unless exactly 0");
        Expect(BbWindHang::ParseProof("1") && !BbWindHang::ParseProof(nullptr) && !BbWindHang::ParseProof("0") &&
                   !BbWindHang::ParseProof("11") && !BbWindHang::ParseProof(""),
               "r112m: the proof knob is exactly 1");

        // the push of a short part against a long one (A 0.21 m and B 0.88 m of the graveyard lantern)
        const float scale_a = BbWindHang::HangScale(0.0f, 0.21f);
        const float scale_b = BbWindHang::HangScale(0.0f, 0.88f);
        Expect(std::fabs(scale_a - 0.175f) < 1e-4f && std::fabs(scale_b - 0.7333f) < 1e-3f && scale_b > scale_a,
               "r112m: the shaders' scales of the two parts");
        const float push_table = 0.285f; // the table's push at gust 0.8, 4 m/s, BB_WIND_SWAY 3
        const float old_a = F::BottomPush(push_table, F::GainDefault, scale_a, false);
        const float old_b = F::BottomPush(push_table, F::GainDefault, scale_b, false);
        const float new_a = F::BottomPush(push_table, F::GainDefault, scale_a, true);
        const float new_b = F::BottomPush(push_table, F::GainDefault, scale_b, true);
        Expect(old_a < 0.011f && old_b > 0.04f && std::fabs(new_b - 0.057f) < 1e-3f && std::fabs(new_a - 0.0499f) < 1e-3f &&
                   std::fabs(new_a - new_b) < 0.01f,
               "r112m: r112l moved the part a quarter of the cage, the same-bottom rule moves both alike");
        // the ramp byte gives that bottom in the shader's own product (ramp / 255 x scale x push)
        const float shader_b = scale_b * float(F::SameRamp(255, F::GainDefault, scale_b, true)) / 255.0f * push_table;
        const float shader_a = scale_a * float(F::SameRamp(255, F::GainDefault, scale_a, true)) / 255.0f * push_table;
        const float shader_old = scale_a * float(F::SameRamp(255, F::GainDefault, scale_a, false)) / 255.0f * push_table;
        Expect(std::fabs(shader_b - new_b) < 1e-3f && std::fabs(shader_a - new_a) < 1e-3f && std::fabs(shader_old - old_a) < 1e-3f,
               "r112m: SameRamp and BottomPush agree");
        Expect(F::SameRamp(255, 0.2f, 1.0f, true) == 51 && F::SameRamp(255, 0.2f, 1.0f, false) == 51 &&
                   F::SameRamp(255, 0.2f, scale_a, false) == F::GainRamp(255, 0.2f) &&
                   F::SameRamp(255, 0.2f, scale_a, true) == 255 && F::SameRamp(255, 1.0f, 0.1f, true) == 255 &&
                   F::SameRamp(255, 0.0f, 0.5f, true) == 0 && F::SameRamp(0, 0.2f, 0.5f, true) == 0 &&
                   F::SameRamp(255, 0.2f, std::nanf(""), true) == 51,
               "r112m: the ramp byte (scale 1 and a short part, SAME=0 is r112l's, gain 0, no number)");

        // the tall rule reads the scene box, not the keys
        F::Entry tall_e;
        tall_e.height = 2.6f;
        F::Entry edge_e;
        edge_e.height = 2.5f;
        F::Entry lantern_e;
        lantern_e.height = 0.89f;
        lantern_e.above = 10.49f;
        Expect(F::TooTall(tall_e, 2.5f) && !F::TooTall(edge_e, 2.5f) && !F::TooTall(lantern_e, 2.5f) &&
                   F::TooTall(lantern_e, 0.5f),
               "r112m: too tall is a scene box over the tall limit (the keys' union is no length)");

        // the lines: four candidates of one scene, one of them at two places
        struct JudgeEntry {
            enum class JState : std::uint8_t { Judging, Still, Moved } state = JState::Judging;
            float dev = 0.0f;
            std::uint64_t draws = 0;
        };
        struct OneJudge {
            std::uint64_t stream = 0;
            JudgeEntry e;
            const JudgeEntry* Find(std::uint64_t s) const {
                return s == stream && stream != 0 ? &e : nullptr;
            }
        };
        F::BoxSet set;
        set.Begin(0);
        set.camera_ok = true;
        set.camera = {-34.0f, -33.0f, 103.0f};
        set.Add(Ground());
        set.Add(MakeBox(7, -34.5f, -36.0f, 107.0f, -33.5f, -35.12f, 107.8f)); // B: 5.1 m away
        set.Add(MakeBox(7, -34.5f, -36.0f, 207.0f, -33.5f, -35.12f, 207.8f)); // a second place of B, 105 m away
        set.Add(MakeBox(8, -34.4f, -36.0f, 106.8f, -34.1f, -35.79f, 107.1f)); // A: 4.9 m away, never judged
        set.Add(MakeBox(9, -30.0f, -36.0f, 120.0f, -29.0f, -33.2f, 121.0f));  // 2.8 m tall: too tall
        set.Add(MakeBox(10, -30.0f, -36.0f, 130.0f, -29.5f, -35.5f, 130.5f)); // not a candidate (no verdict)
        F::StaticBook book;
        F::Entry cand;
        cand.why = F::Why::Ok;
        cand.until = 100000;
        cand.vs = 0x97f2d384ull;
        cand.verts = 2491;
        cand.height = 0.88f;
        cand.width = 1.0f;
        cand.above = 6.3f;
        book.Set(7, cand, 100);
        cand.verts = 1429;
        cand.height = 0.21f;
        cand.width = 0.3f;
        book.Set(8, cand, 100);
        cand.verts = 900;
        cand.height = 2.8f;
        cand.width = 1.0f;
        cand.above = 3.0f;
        book.Set(9, cand, 100);
        BbWindHang::Book heights;
        heights.Note(7, 4096, 0, true, 100, 0x97f2d384ull);
        BbWindHang::Entry* const hang_b = heights.Find(7);
        Expect(hang_b != nullptr, "r112m: the test's hang book has B");
        if (hang_b != nullptr) {
            const std::uint32_t b_base = BbWindSway::HeightKey(-36.0f);
            const std::uint32_t b_top = BbWindHang::TopKey(-35.12f);
            BbWindHang::Measure(*hang_b, true, 100, &b_base, &b_top, 1.0, 12.0f);
            BbWindHang::Measure(*hang_b, false, 100 + BbWindHang::JudgeFrames, &b_base, &b_top, 1.0, 12.0f);
        }
        OneJudge judge; // B: no judge entry; the judge knows stream 9 as moved with a growth of 60 mm
        judge.stream = 9;
        judge.e.state = JudgeEntry::JState::Moved;
        judge.e.dev = 0.06f;
        const std::vector<F::CandInfo> infos = F::GatherCands(set, book, heights, judge);
        Expect(infos.size() == 3 && infos[0].stream == 8 && infos[1].stream == 7 && infos[2].stream == 9,
               "r112m: the candidates of the scene nearest first, one per stream");
        if (infos.size() == 3) {
            Expect(infos[1].places == 2 && infos[0].places == 1 && std::fabs(infos[1].dist - 5.09f) < 0.1f &&
                       std::fabs(infos[0].dist - 4.9f) < 0.2f && infos[1].hang && infos[1].judged && infos[1].fits &&
                       std::fabs(infos[1].span - 0.88f) < 0.02f && !infos[0].hang && infos[0].judge == 0 &&
                       infos[2].judge == 3 && std::fabs(infos[2].dev - 0.06f) < 1e-5f,
                   "r112m: places, distances and states are gathered");
            Expect(F::ClassOf(infos[0], 2.5f) == F::CandClass::NoJudge && F::ClassOf(infos[1], 2.5f) == F::CandClass::Pushed &&
                       F::ClassOf(infos[2], 2.5f) == F::CandClass::Tall && F::ClassOf(infos[2], 3.0f) == F::CandClass::Other,
                   "r112m: the classes");
            F::Stats ms;
            ms.too_tall = 41;
            const std::vector<std::string> lines = F::CandLines(infos, ms, 2.5f, F::GainDefault, true, push_table, true, false);
            Expect(lines.size() == 4 && Has(lines[0], "(r112m)") && Has(lines[0], "candidates in the scene now 3 (1 pushed, 1 too tall, 1 with no GPU-judge entry, 0 other)") &&
                       Has(lines[0], "nearest 4.9 m (vs 97f2d384)") && Has(lines[0], "41 draws refused as too tall") &&
                       Has(lines[0], "proof tint off"),
                   "r112m: the header line");
            Expect(Has(lines[1], "A vs 97f2d384 (1 place, 1429 verts) dist 4.9 m: scene box 0.21 m tall") &&
                       Has(lines[1], "keys span not read") && Has(lines[1], "no GPU-judge entry") &&
                       Has(lines[2], "B vs 97f2d384 (2 places, 2491 verts)") && Has(lines[2], "keys span 0.88 m") &&
                       Has(lines[2], "PUSHED: scale 0.73") && Has(lines[2], "its bottom moves 0.057 m now") &&
                       Has(lines[3], "C vs 97f2d384") && Has(lines[3], "TOO TALL: its scene box is 2.80 m, over 2.5 m"),
                   "r112m: a line per candidate: the unjudged part, the pushed cage, the too tall one");
            Expect(F::CandLines(infos, ms, 2.5f, F::GainDefault, true, push_table, false, true).size() == 1 &&
                       Has(F::CandLines(infos, ms, 2.5f, F::GainDefault, true, push_table, false, true)[0], "proof tint ON"),
                   "r112m: no candidate lines without the survey knob");
            Expect(Has(F::CandState(infos[1], 2.5f, F::GainDefault, false, push_table), "its bottom moves 0.042 m now") &&
                       Has(F::CandState(infos[1], 2.5f, F::GainDefault, false, push_table), "scaled by its height"),
                   "r112m: SAME=0 prints r112l's push");
            for (const std::string& line : lines) {
                Expect(line.size() <= F::LineCharsK, "r112m: a line is capped");
            }
        }
        // the other states
        F::CandInfo state;
        state.e.height = 0.5f;
        state.hang = true;
        Expect(Has(F::CandState(state, 2.5f, 0.2f, true, 0.1f), "measuring"), "r112m: state: measuring");
        state.judged = true;
        state.span = 0.1f;
        Expect(Has(F::CandState(state, 2.5f, 0.2f, true, 0.1f), "unfit: its keys span 0.10 m, under 0.15 m"), "r112m: state: short");
        state.span = 20.0f;
        Expect(Has(F::CandState(state, 2.5f, 0.2f, true, 0.1f), "unfit: its keys span 20.00 m, over its limit"), "r112m: state: long");
        state.moving = true;
        Expect(Has(F::CandState(state, 2.5f, 0.2f, true, 0.1f), "held as moving by r112's book"), "r112m: state: moving");
        F::CandInfo refused;
        refused.judge = 3;
        refused.dev = -2.0f;
        Expect(Has(F::CandState(refused, 2.5f, 0.2f, true, 0.1f), "refused by r112h's rules"), "r112m: state: refused by r112h");
        F::CandInfo window;
        window.judge = 1;
        Expect(Has(F::CandState(window, 2.5f, 0.2f, true, 0.1f), "window is open"), "r112m: state: judging");
        F::CandInfo still_no_book;
        still_no_book.judge = 2;
        Expect(Has(F::CandState(still_no_book, 2.5f, 0.2f, true, 0.1f), "has no entry for it"), "r112m: state: still, no book entry");
        // bbport (r112n_hang-teleport-camera): why a stream is held as moving, the candidate lines' places, BB_TEST_GOTO
        {
            BbWindHang::Book moving_book;
            moving_book.Note(21, 4096, 7, true, 10, 0xe859b6d9ull);
            moving_book.Note(21, 4096, 8, true, 11, 0xe859b6d9ull); // other palette bytes at the same address
            moving_book.Note(21, 4096, 9, false, 12, 0xe859b6d9ull); // and then unreadable: the first reason stays
            moving_book.Note(22, 4096, 0, false, 10, 0x1234abcdull); // unreadable at once
            const BbWindHang::Entry* const changed = moving_book.Find(21);
            const BbWindHang::Entry* const unread = moving_book.Find(22);
            Expect(changed != nullptr && unread != nullptr && changed->moving && unread->moving &&
                       changed->why_moving == 2 && changed->moved_after == 1 && unread->why_moving == 1,
                   "r112n: the book records why a stream is held as moving (the first reason)");
            Expect(Has(F::MovingWhy(2, 1), "palette bytes changed after 1 frames") && Has(F::MovingWhy(2, 1), "never measured") &&
                       Has(F::MovingWhy(1, 0), "could not be read") && Has(F::MovingWhy(3, 0), "GPU judge") &&
                       Has(F::MovingWhy(4, 3), "r112h's rule refused it (a figure (bones))") &&
                       Has(F::MovingWhy(4, 99), "(?)") && Has(F::MovingWhy(0, 0), "not recorded"),
                   "r112n: the reasons in words");
            F::CandInfo held;
            held.e.height = 1.32f;
            held.hang = true;
            held.moving = true;
            held.moving_why = 2;
            held.moved_after = 4;
            Expect(Has(F::CandState(held, 2.5f, 0.2f, true, 0.1f), "held as moving by r112's book: its palette bytes changed after 4 frames"),
                   "r112n: the moving state carries its reason");
            const std::vector<std::string> place_lines =
                F::CandLines(infos, F::Stats{}, 2.5f, F::GainDefault, true, push_table, true, false);
            Expect(place_lines.size() == 4 && Has(place_lines[2], "6.30 m up (middle -34.00 -35.56 107.40, ground y -42.30)"),
                   "r112n: a candidate line names its middle and the ground under it");

            namespace G = BbTestGoto;
            std::uint32_t vs_value = 0;
            Expect(G::ParseVs("97f2d384", &vs_value) && vs_value == 0x97f2d384u && G::ParseVs("97F2D384", &vs_value) &&
                       !G::ParseVs("97f2d38", &vs_value) && !G::ParseVs("97f2d38g", &vs_value) && !G::ParseVs(nullptr, &vs_value) &&
                       !G::ParseVs("97f2d3844", &vs_value),
                   "r112n: the vs filter is exactly 8 hex digits");
            const G::Knobs hang_knobs = G::ParseKnobs("hang", "97F2D384", "3", nullptr);
            Expect(hang_knobs.on && hang_knobs.hang && hang_knobs.vs_set && hang_knobs.vs == 0x97f2d384u &&
                       std::fabs(hang_knobs.dist - 3.0f) < 1e-6f && std::fabs(hang_knobs.elev - G::ElevDefault) < 1e-6f,
                   "r112n: BB_TEST_GOTO=hang");
            const G::Knobs fixed_knobs = G::ParseKnobs("-34.2,-36,107", nullptr, "99", "70");
            Expect(fixed_knobs.on && !fixed_knobs.hang && std::fabs(fixed_knobs.pos[0] + 34.2f) < 1e-4f &&
                       std::fabs(fixed_knobs.pos[1] + 36.0f) < 1e-4f && std::fabs(fixed_knobs.pos[2] - 107.0f) < 1e-4f &&
                       std::fabs(fixed_knobs.dist - G::DistMost) < 1e-6f && std::fabs(fixed_knobs.elev - 70.0f) < 1e-6f &&
                       !fixed_knobs.vs_set,
                   "r112n: BB_TEST_GOTO=x,y,z, the distance and the elevation are clamped");
            Expect(!G::ParseKnobs(nullptr, nullptr, nullptr, nullptr).on && !G::ParseKnobs("", nullptr, nullptr, nullptr).on &&
                       !G::ParseKnobs("1,2", nullptr, nullptr, nullptr).on && !G::ParseKnobs("1,2,3x", nullptr, nullptr, nullptr).on &&
                       !G::ParseKnobs("nan,1,2", nullptr, nullptr, nullptr).on && !G::ParseKnobs("hang ", nullptr, nullptr, nullptr).on &&
                       !G::ParseKnobs("0", nullptr, nullptr, nullptr).on,
                   "r112n: a knob that is not understood is off");

            // the plan: the graveyard lantern B (middle -34.00 -35.56 107.40, ground y -42.30), the hunter 20 m away, the camera 3 m behind
            // him and 1.9 m up, looking (nearly) along -z
            const float target[3] = {-34.0f, -35.56f, 107.4f};
            const float hunter[3] = {-41.9f, -42.3f, 87.0f};
            const float cam[3] = {-40.81f, -40.4f, 90.0f};
            const float fwd[3] = {-0.3416f, 0.04998f, -0.9385f};
            const G::Plan plan = G::PlanStand(target, -42.3f, cam, fwd, hunter, 4.9f, 55.0f);
            Expect(plan.ok && std::fabs(plan.stand[0] + 34.003f) < 0.02f && std::fabs(plan.stand[1] + 42.0f) < 1e-3f &&
                       std::fabs(plan.stand[2] - 107.387f) < 0.02f && std::fabs(plan.horiz - 3.179f) < 0.01f &&
                       std::fabs(plan.move - 21.86f) < 0.05f,
                   "r112n: the stand point (look-up capped at 55 degrees: 3.18 m horizontally, 5.5 m in 3 D)");
            const G::Plan steep = G::PlanStand(target, -42.3f, cam, fwd, hunter, 4.9f, 80.0f);
            Expect(steep.ok && std::fabs(steep.horiz - 1.843f) < 0.01f && steep.horiz < plan.horiz,
                   "r112n: with a steep look-up allowed the camera is put at 4.9 m in 3 D");
            const float cam_after[3] = {plan.stand[0] + (cam[0] - hunter[0]), plan.stand[1] + (cam[1] - hunter[1]),
                                        plan.stand[2] + (cam[2] - hunter[2])};
            Expect(G::Converged(G::Horizontal(cam_after, target), plan.horiz, G::BearingOffDeg(cam_after, fwd, target)) &&
                       !G::Converged(G::Horizontal(cam, target), plan.horiz, G::BearingOffDeg(cam, fwd, target)) &&
                       std::fabs(G::ElevationDeg(cam_after, target) - 55.0f) < 0.2f,
                   "r112n: a camera that keeps its offset from the hunter is where the plan wants it");
            const float far_hunter[3] = {-41.9f, -42.3f, 20.0f};
            const float down[3] = {0.0f, -1.0f, 0.0f};
            const float far_target[3] = {-34.0f, -35.56f, 407.4f};
            Expect(!G::PlanStand(target, -42.3f, cam, fwd, far_hunter, 4.9f, 55.0f).ok &&
                       Has(G::PlanStand(target, -42.3f, cam, fwd, far_hunter, 4.9f, 55.0f).why, "disagree") &&
                       !G::PlanStand(target, -42.3f, cam, down, hunter, 4.9f, 55.0f).ok &&
                       !G::PlanStand(far_target, -42.3f, cam, fwd, hunter, 4.9f, 55.0f).ok &&
                       !G::PlanStand(target, std::nanf(""), cam, fwd, hunter, 4.9f, 55.0f).ok,
                   "r112n: no plan from frames that disagree, a camera looking down, a move over 150 m, a number that is none");

            // the mailbox between the threads
            const float spot[3] = {1.0f, 2.0f, 3.0f};
            G::Request taken;
            Expect(!G::Take(&taken), "r112n: nothing waits at first");
            const std::uint32_t seq = G::Post(spot);
            Expect(G::Pending() && G::Take(&taken) && taken.seq == seq && taken.pos[2] == 3.0f && !G::Pending() && !G::Take(&taken),
                   "r112n: a request is taken once");
            G::Done(seq, true);
            Expect(G::g_done_seq.load() == seq && G::g_done_ok.load(), "r112n: the answer");
            (void)G::Post(spot);
            G::Cancel();
            Expect(!G::Pending(), "r112n: a request can be withdrawn");

            // the machine: the scene of the lines above (B 5.1 m away is the nearest pushed mesh), a camera looking along +z
            F::BoxSet gset = set;
            gset.view_ok = true;
            gset.view = {1.0f, 0.0f, 0.0f, 34.0f, 0.0f, 1.0f, 0.0f, 33.0f, 0.0f, 0.0f, 1.0f, -103.0f};
            gset.proj = {1.5f, -2.6667f, 1.0f, 0.1f};
            gset.render = {1280u, 720u};
            const float gunter[3] = {-34.0f, -35.0f, 100.0f};
            G::Knobs gk;
            gk.on = true;
            G::Session gs;
            Expect(G::ObserveWith(G::Knobs{}, gs, gset, book, heights, judge, 2.5f, 0, gunter).empty(),
                   "r112n: off, nothing is observed");
            std::vector<std::string> gl = G::ObserveWith(gk, gs, gset, book, heights, judge, 2.5f, 0, gunter);
            Expect(gl.size() == 3 && Has(gl[0], "GLINT-PROOF hang goto (r112n): target locked: vs 97f2d384 (2491 verts, 2 places)") &&
                       Has(gl[1], "waiting f0: camera to target") && gs.phase == G::Phase::Wait && gs.locked,
                   "r112n: the first look locks the nearest pushed mesh and waits for the start frame");
            gl = G::ObserveWith(gk, gs, gset, book, heights, judge, 2.5f, 300, gunter);
            Expect(gs.phase == G::Phase::Moving && G::Pending() && gl.size() == 3 &&
                       Has(gl[0], "asked (try 1 of 4): hunter to -34.00 -42.00") && Has(gl[1], "warp asked f300"),
                   "r112n: the plan is posted");
            G::Request asked;
            Expect(G::Take(&asked) && std::fabs(asked.pos[1] + 42.0f) < 1e-3f, "r112n: the game thread takes the request");
            G::Done(asked.seq, true);
            gl = G::ObserveWith(gk, gs, gset, book, heights, judge, 2.5f, 310, gunter);
            Expect(gs.phase == G::Phase::Settling && Has(gl[0], "made by the game thread"), "r112n: the move is seen");
            gl = G::ObserveWith(gk, gs, gset, book, heights, judge, 2.5f, 310 + G::SettleFrames, gunter);
            Expect(gs.phase == G::Phase::Wait && Has(gl[0], "camera not there") && Has(gl[0], "another warp"),
                   "r112n: a camera that did not arrive is planned again");
            gset.camera = {-34.0f, -33.0f, 107.4f - gs.horiz_want};
            gset.view[11] = -(107.4f - gs.horiz_want);
            gset.view[3] = 34.0f;
            gset.view[7] = 33.0f;
            gs.phase = G::Phase::Settling;
            gs.phase_frame = 1000;
            gl = G::ObserveWith(gk, gs, gset, book, heights, judge, 2.5f, 1000 + G::SettleFrames, gunter);
            Expect(gs.phase == G::Phase::Holding && Has(gl[0], "READY after 1 warp") && Has(gl[1], "holding f1120") &&
                       Has(gl[1], "bearing off 0 deg") && Has(gl[1], "OUT OF VIEW") && Has(gl[1], "view pitch +0 deg"),
                   "r112n: ready, and the level view does not see a mesh 55 degrees up");
        }
        // bbport (r112o_hang-safe-goto): the hop walk against a floor that exists only near where the hunter has stood, the framing, the gate
        {
            namespace G = BbTestGoto;
            Expect(std::fabs(G::ParseHop(nullptr) - 5.0f) < 1e-6f && std::fabs(G::ParseHop("") - 5.0f) < 1e-6f &&
                       std::fabs(G::ParseHop("2.5") - 2.5f) < 1e-6f && std::fabs(G::ParseHop("0.1") - G::HopLeast) < 1e-6f &&
                       std::fabs(G::ParseHop("99") - G::HopMost) < 1e-6f && std::fabs(G::ParseHop("x") - 5.0f) < 1e-6f &&
                       std::fabs(G::ParseHop("3x") - 5.0f) < 1e-6f && std::fabs(G::ParseHop("nan") - 5.0f) < 1e-6f,
                   "r112o: BB_TEST_GOTO_HOP is 1 to 15, anything else is 5");
            // the world: y is 0 within `radius` of a place where the hunter stood still; everywhere else he falls 0.9 m a frame
            const auto walk = [&](float hop, float radius, unsigned* hops, unsigned* fails, std::string* last) -> int {
                G::WalkParams p;
                p.hop = hop;
                G::Walker w(p);
                const float goal[3] = {-33.55f, 0.0f, 107.65f};
                float at[3] = {-48.89f, 0.0f, 74.04f};
                std::vector<std::array<float, 2>> loaded;
                loaded.push_back({at[0], at[2]});
                w.Begin(goal);
                for (unsigned tick = 0; tick < 6000; ++tick) {
                    bool floor = false;
                    for (const std::array<float, 2>& l : loaded) {
                        if (std::hypot(at[0] - l[0], at[2] - l[1]) <= radius) {
                            floor = true;
                        }
                    }
                    if (floor) {
                        at[1] = std::max(0.0f, at[1] - 0.3f);
                    } else {
                        at[1] -= 0.9f;
                    }
                    const G::WalkOut o = w.Tick(at);
                    if (o.say[0] != 0) {
                        *last = o.say;
                    }
                    *hops = w.Hops();
                    *fails = w.Fails();
                    if (o.ev == G::WalkEv::Warp) {
                        std::memcpy(at, o.pos, sizeof at);
                    } else if (o.ev == G::WalkEv::Arrived) {
                        return 1;
                    } else if (o.ev == G::WalkEv::Failed) {
                        return 0;
                    }
                    if (floor && at[1] == 0.0f &&
                        std::hypot(at[0] - loaded.back()[0], at[2] - loaded.back()[1]) > 1.0f) {
                        loaded.push_back({at[0], at[2]});
                    }
                }
                return -1;
            };
            unsigned hops = 0, fails = 0;
            std::string last;
            Expect(walk(5.0f, 7.0f, &hops, &fails, &last) == 1 && hops == 8 && fails == 0 &&
                       Has(last, "GLINT-PROOF hang goto (r112o): walk done: arrived after 8 hops (0 failed)"),
                   "r112o: 5 m hops over ground that is loaded 7 m around a standing place: 8 hops, no failure");
            Expect(walk(15.0f, 7.0f, &hops, &fails, &last) == 1 && fails == 2 && hops >= 10 && Has(last, "arrived after"),
                   "r112o: 15 m hops fall twice (15 m, then 7.5 m is too far), halve to 3.75 m and arrive");
            Expect(walk(5.0f, 0.5f, &hops, &fails, &last) == 0 && fails == 5 && Has(last, "walk gave up after 5 failed hops (fell to y"),
                   "r112o: no floor beyond 0.5 m: five failures end the walk, and the line says why");
            // a hunter that never moves after a warp (the warp is not applied): each hop times out and goes back, and in the end the walk gives up
            {
                G::WalkParams p;
                G::Walker w(p);
                const float goal[3] = {10.0f, 0.0f, 0.0f};
                const float at[3] = {0.0f, 0.0f, 0.0f};
                w.Begin(goal);
                int ev_warp = 0;
                int ev_failed = 0;
                std::string text;
                for (unsigned tick = 0; tick < 5000 && ev_failed == 0; ++tick) {
                    const G::WalkOut o = w.Tick(at);
                    ev_warp += o.ev == G::WalkEv::Warp ? 1 : 0;
                    ev_failed += o.ev == G::WalkEv::Failed ? 1 : 0;
                    if (o.ev == G::WalkEv::Failed) {
                        text = o.say;
                    }
                }
                Expect(ev_failed == 1 && ev_warp == 9 && Has(text, "walk gave up after 5 failed hops (no rest in 240 frames"),
                       "r112o: a warp that is never applied times out five times (nine warps: five hops, four ways back) and gives up");
            }
            {
                G::Walker w;
                const float goal[3] = {1.0f, 0.0f, 0.0f};
                const float here[3] = {0.0f, 0.0f, 0.0f};
                Expect(!w.Active() && w.Tick(here).ev == G::WalkEv::None, "r112o: an idle walker does nothing");
                w.Begin(goal);
                w.Pause();
                w.Abort();
                Expect(!w.Active() && w.Tick(here).ev == G::WalkEv::None, "r112o: a walker that was aborted does nothing");
                const float nanpos[3] = {std::nanf(""), 0.0f, 0.0f};
                w.Begin(goal);
                Expect(w.Active() && w.Tick(nanpos).ev == G::WalkEv::None && w.Active(), "r112o: a position that is no number is ignored");
            }

            // the framing
            G::Session fs;
            fs.phase = G::Phase::Holding;
            fs.centre[0] = -34.0f;
            fs.centre[1] = -35.56f;
            fs.centre[2] = 107.4f;
            G::Reading fr;
            fr.cam_ok = true;
            fr.view_ok = true;
            fr.cam[0] = -34.0f;
            fr.cam[1] = -40.0f;
            fr.cam[2] = 104.0f;
            fr.sb.any = true;
            fr.sb.all = true;
            fr.sb.x0 = 600.0f;
            fr.sb.y0 = 300.0f;
            fr.sb.x1 = 650.0f;
            fr.sb.y1 = 340.0f;
            fr.width = 1280;
            fr.height = 720;
            G::Knobs fk;
            fk.on = true;
            const G::Framing in_view = G::FramingOf(fk, fs, fr, 900);
            Expect(in_view.framed && in_view.why.empty() && Has(in_view.text, "camera to target 5.6 m") &&
                       Has(in_view.text, "screen box 600,300 to 650,340 of 1280x720") && Has(in_view.line, "framing f900: FRAMED (") &&
                       Has(in_view.line, "captures taken 0, refused polls 0"),
                   "r112o: a target in the middle of the picture, 5.6 m away, is framed");
            G::Reading edge = fr;
            edge.sb.x0 = 1200.0f;
            edge.sb.x1 = 1250.0f;
            const G::Framing at_edge = G::FramingOf(fk, fs, edge, 900);
            Expect(!at_edge.framed && Has(at_edge.why, "outside the middle 80 percent") && Has(at_edge.line, "NOT FRAMED: the target's middle"),
                   "r112o: a target at the edge of the picture is not framed");
            G::Reading behind = fr;
            behind.sb.any = false;
            G::Reading tiny = fr;
            tiny.sb.x1 = 603.0f;
            tiny.sb.y1 = 303.0f;
            G::Reading far_cam = fr;
            far_cam.cam[2] = 80.0f;
            G::Reading blind = fr;
            blind.cam_ok = false;
            G::Session waiting = fs;
            waiting.phase = G::Phase::Settling;
            Expect(Has(G::FramingOf(fk, fs, behind, 1).why, "behind the camera") && Has(G::FramingOf(fk, fs, tiny, 1).why, "under 6 px") &&
                       Has(G::FramingOf(fk, fs, far_cam, 1).why, "more than 12 m") && Has(G::FramingOf(fk, fs, blind, 1).why, "not read") &&
                       Has(G::FramingOf(fk, waiting, fr, 1).why, "has not arrived (settling)") && !G::FramingOf(fk, waiting, fr, 1).framed,
                   "r112o: behind, tiny, far, unread and not arrived are all not framed, each with its reason");
            G::Knobs fixed = fk;
            fixed.hang = false;
            Expect(G::FramingOf(fixed, fs, blind, 1).framed && !G::FramingOf(fixed, waiting, fr, 1).framed,
                   "r112o: a fixed position is framed when the run holds");

            // the gate
            Expect(G::GateOf(false, false, false, 0.0) == G::Gate::Free && G::GateOf(false, true, true, 99.0) == G::Gate::Free &&
                       G::GateOf(true, true, true, 1.0) == G::Gate::Take && G::GateOf(true, true, false, 1.0) == G::Gate::HoldNotFramed &&
                       G::GateOf(true, true, true, 31.0) == G::Gate::HoldStale && G::GateOf(true, false, true, 0.0) == G::Gate::HoldStale,
                   "r112o: no target: free; framed and fresh: taken; not framed: held; an old or no observation: held");
            Expect(!G::CaptureHeld(nullptr) && !G::CaptureHeld("") && !G::CaptureHeld("no-such-trigger-file.r112o"),
                   "r112o: without BB_TEST_GOTO or a waiting trigger file the capture is never held");
        }
        const std::string once_m = F::OnceTextM(true, true, F::TallDefault);
        Expect(Has(once_m, "(r112m)") && Has(once_m, "newest 6 candidates") && Has(once_m, "BB_WIND_HANG_STATIC_SAME=1") &&
                   Has(once_m, "BB_WIND_HANG_PROOF=1") && Has(F::OnceTextM(false, false, 1.0f), "SAME=0") &&
                   once_m.size() < 1536,
               "r112m: the once line");
    }

    // bbport (r112k_hang-lantern-verdict): skinned streams stay out, the route's tail, the focus, the knobs, the union
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

    if (failures == 0) {
        std::printf("wind hang find: all passed\n");
        return 0;
    }
    std::printf("wind hang find: %d failed\n", failures);
    return 1;
}
