// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r120_test-camera-lookat, TOOL; test-tools branch): BB_TEST_CAMERA's text and arithmetic, the aim-and-place controller
// against a simulated follow camera, the hold, the capture gate and the driver's mailbox (gpu/shim/bbport_test_camera.h and
// bbport_test_camera_run.h). The twin in Python (r120_twin.py) holds the same scenes.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "gpu/shim/bbport_test_camera_run.h"

// The runtime's live knobs table, stood in (src/sys/live_knobs.c is not linked here).
extern "C" {
std::uint32_t runtime_live_knobs_generation = 0;
int runtime_live_knob(const char*, char*, std::size_t) {
    return 0;
}
}

namespace C = BbTestCamera;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

bool Near(float a, float b, float tol) {
    return std::fabs(a - b) <= tol;
}

bool Has(const std::string& text, const char* part) {
    return text.find(part) != std::string::npos;
}

// A camera pose as the engine's matrices (3x4 rows, world to view and back, z forward).
void Matrices(const float cam[3], const float f[3], float view[12], float inv[12]) {
    const float up[3] = {0.0f, 1.0f, 0.0f};
    float r[3] = {up[1] * f[2] - up[2] * f[1], up[2] * f[0] - up[0] * f[2], up[0] * f[1] - up[1] * f[0]};
    const float n = std::sqrt(r[0] * r[0] + r[1] * r[1] + r[2] * r[2]);
    for (float& v : r) {
        v /= n;
    }
    const float u[3] = {f[1] * r[2] - f[2] * r[1], f[2] * r[0] - f[0] * r[2], f[0] * r[1] - f[1] * r[0]};
    const float* rows[3] = {r, u, f};
    for (int i = 0; i < 3; ++i) {
        view[4 * i + 0] = rows[i][0];
        view[4 * i + 1] = rows[i][1];
        view[4 * i + 2] = rows[i][2];
        view[4 * i + 3] = -(rows[i][0] * cam[0] + rows[i][1] * cam[1] + rows[i][2] * cam[2]);
    }
    const float i0[12] = {r[0], u[0], f[0], cam[0], r[1], u[1], f[1], cam[1], r[2], u[2], f[2], cam[2]};
    std::memcpy(inv, i0, sizeof i0);
}

const float kProj[4] = {1.4f, -2.5f, 0.0f, 0.1f};

// The game's follow camera, simulated: the view's heading and pitch are linear in the two fields (signs and ratio as the test
// asks), the camera stands R metres behind the view's direction from a point 1.6 m over the hunter.
struct Plant {
    float sy, sp, rp = 0.8f, lo = -1.2f, hi = 1.4f;
    float yaw = 0.3f, pitch = 0.1f;
    float hunter[3] = {0.0f, 0.0f, 0.0f};
    float R = 3.0f, c_h = 25.0f, c_p = -4.0f;
    Plant(float sy_, float sp_) : sy(sy_), sp(sp_) {}
    float Heading() const {
        return sy * yaw * C::kDeg + c_h;
    }
    float Pitch() const {
        return sp * rp * pitch * C::kDeg + c_p;
    }
    void Fwd(float f[3]) const {
        const float h = Heading() * C::kRad, p = Pitch() * C::kRad;
        f[0] = std::cos(p) * std::sin(h);
        f[1] = std::sin(p);
        f[2] = std::cos(p) * std::cos(h);
    }
    void Cam(float c[3]) const {
        float f[3];
        Fwd(f);
        c[0] = hunter[0] - R * f[0];
        c[1] = hunter[1] + 1.6f - R * f[1];
        c[2] = hunter[2] - R * f[2];
    }
    virtual void Apply(const C::Session::Out& o) {
        if (o.cmd_valid) {
            yaw = C::WrapRad(o.cmd_yaw);
            pitch = std::fmax(lo, std::fmin(hi, o.cmd_pitch));
        }
    }
    virtual ~Plant() = default;
};

struct Dead : Plant {
    using Plant::Plant;
    void Apply(const C::Session::Out&) override {}
};

struct Run {
    int ready_frame = -1;
    bool yaw_remembered = false;
    float yaw = 0.0f;
    int posts = 0;              // r120b: walks the controller asked for
    bool engaged = false;       // r120b: the last frame's gate
    bool failed = false;
    std::string why;
    std::vector<std::string> said; // every log line the controller made
};

Run Go(C::Session& sess, Plant& pl, const C::Goal& goal, int frames, std::uint64_t start_frame, const float* kept, const float* centre,
       const char* text, const float* kept_yaw = nullptr, int fall_at = -1, const float* hang = nullptr) {
    std::vector<std::string> lines;
    sess.Begin(goal, start_frame, text, lines);
    Run run;
    int posted_at = -1;
    std::uint32_t seq = 10, done_seq = 0, posted_seq = 0;
    float stand[3] = {};
    for (int k = 0; k < frames; ++k) {
        const std::uint64_t fr = start_frame + static_cast<std::uint64_t>(k);
        if (k == fall_at) {
            pl.hunter[1] = -7.9f; // r120b: the hunter falls through the floor
        }
        C::Session::Frame in;
        in.frame = fr;
        float cam[3], fwd[3];
        pl.Cam(cam);
        pl.Fwd(fwd);
        std::memcpy(in.cam, cam, sizeof cam);
        std::memcpy(in.fwd, fwd, sizeof fwd);
        float inv[12];
        Matrices(cam, fwd, in.view, inv);
        std::memcpy(in.proj, kProj, sizeof in.proj);
        in.cam_ok = in.view_ok = true;
        in.width = 1920.0f;
        in.height = 1080.0f;
        in.hunter_ok = true;
        std::memcpy(in.hunter, pl.hunter, sizeof in.hunter);
        in.seen_ok = true;
        in.seen_yaw = pl.yaw;
        in.seen_pitch = pl.pitch;
        in.seen_lowest = pl.lo;
        in.seen_highest = pl.hi;
        in.done_seq = done_seq;
        in.done_ok = true;
        if (kept != nullptr) {
            in.kept_ok = true;
            std::memcpy(in.kept, kept, sizeof in.kept);
        }
        if (centre != nullptr) {
            in.centre_ready = true;
            std::memcpy(in.centre, centre, sizeof in.centre);
        }
        if (kept_yaw != nullptr) {
            in.kept_yaw_ok = true;
            in.kept_yaw = *kept_yaw;
        }
        if (hang != nullptr) { // r120c: BB_TEST_GOTO=hang's locked mesh
            in.hang_ok = true;
            std::memcpy(in.hang_centre, hang, sizeof in.hang_centre);
        }
        const C::Session::Out o = sess.Tick(in);
        if (o.remember_yaw) {
            run.yaw_remembered = true;
            run.yaw = o.remember_yaw_deg;
        }
        pl.Apply(o);
        run.engaged = o.engaged;
        run.failed = o.failed;
        if (o.failed || o.engaged) {
            run.why = o.why;
        }
        for (const std::string& l : o.lines) {
            run.said.push_back(l);
        }
        if (o.post) {
            ++run.posts;
            ++seq;
            sess.Posted(seq, fr);
            posted_seq = seq;
            posted_at = static_cast<int>(fr) + 12;
            std::memcpy(stand, o.stand, sizeof stand);
        }
        if (posted_at >= 0 && static_cast<int>(fr) >= posted_at) {
            pl.hunter[0] = stand[0];
            pl.hunter[1] = 0.0f;
            pl.hunter[2] = stand[2];
            done_seq = posted_seq;
            posted_at = -1;
        }
        if (o.framed && run.ready_frame < 0) {
            run.ready_frame = static_cast<int>(fr);
        }
    }
    return run;
}
} // namespace

int main() {
    // ---- the knob's text
    {
        const C::Goal g = C::ParseGoal("lookat:1,2,3,1.5,90,20");
        Expect(g.kind == C::Kind::LookAt && g.point[0] == 1.0f && g.point[1] == 2.0f && g.point[2] == 3.0f && g.dist == 1.5f &&
                   g.yaw_set && g.yaw == 90.0f && g.elev == 20.0f && !g.bad,
               "lookat with every value");
        const C::Goal s = C::ParseGoal("lookat/centre/1.5/0/30");
        Expect(s.kind == C::Kind::LookAt && s.centre && s.dist == 1.5f && s.yaw_set && s.yaw == 0.0f && s.elev == 30.0f,
               "slashes (a slot job cannot hold commas) and the centre keyword");
        const C::Goal k = C::ParseGoal("lookat:kept,2,auto,40");
        Expect(k.kept && k.dist == 2.0f && !k.yaw_set && k.elev == 40.0f, "kept, a distance, auto yaw, an elevation");
        const C::Goal h = C::ParseGoal("hang");
        Expect(h.kind == C::Kind::Hang && h.dist == 4.0f && h.elev == 30.0f && !h.bad, "hang: 4 m, 30 degrees");
        const C::Goal p = C::ParseGoal("pose:1,2,3,200,-100");
        Expect(p.kind == C::Kind::Pose && Near(p.pose_yaw, -160.0f, 1e-3f) && p.pose_pitch == -80.0f, "pose wraps the yaw, clamps the pitch");
        Expect(C::ParseGoal("").kind == C::Kind::Off && !C::ParseGoal("").bad && C::ParseGoal(nullptr).kind == C::Kind::Off, "empty is off");
        Expect(C::ParseGoal("lookat:1,2").bad && C::ParseGoal("dance").bad && C::ParseGoal("lookat:1,2,x").bad &&
                   C::ParseGoal("lookat:centre,1,2,3,4").bad && C::ParseGoal("pose:1,2,3").bad,
               "texts that are not understood are bad and off");
        Expect(C::ParseGoal("lookat:1,2,3,100").dist == 30.0f && C::ParseGoal("lookat:1,2,3,0.1").dist == 0.5f, "distance clamped");
        const C::PixelList px = C::ParsePixels("1395,624;1426,624;1600,300");
        Expect(px.n == 3 && !px.bad && px.px[0].x == 1395 && px.px[0].y == 624 && px.px[2].x == 1600 && px.px[2].y == 300, "three pixels");
        const C::PixelList clamped = C::ParsePixels("1395/624;2500/-5");
        Expect(clamped.n == 2 && clamped.px[1].x == 1919 && clamped.px[1].y == 0, "pixels clamped into the picture");
        Expect(C::ParsePixels("1,2,3").bad && C::ParsePixels("").n == 0 && !C::ParsePixels("").bad, "odd count is bad, empty is none");
    }
    // ---- the arithmetic
    {
        const float cam[3] = {3.0f, 1.6f, -2.0f};
        const float f[3] = {std::cos(0.2f) * std::sin(0.5f), std::sin(0.2f), std::cos(0.2f) * std::cos(0.5f)};
        float view[12], inv[12];
        Matrices(cam, f, view, inv);
        const float point[3] = {4.0f, 1.4f, 2.5f};
        const C::Screen s = C::ScreenOf(view, kProj, 1920.0f, 1080.0f, point);
        Expect(s.ok, "a point in front is on the screen");
        const float depth = C::DepthOf(kProj, s.z);
        float back[3];
        float vz = 0.0f;
        const bool ok = C::WorldFromDepth(inv, kProj, depth, 2.0f * s.x / 1920.0f - 1.0f, 2.0f * s.y / 1080.0f - 1.0f, back, &vz);
        Expect(ok && C::Dist3(back, point) < 1e-3f && Near(vz, s.z, 1e-3f), "world to screen to depth to world gives the point back");
        float none[3];
        Expect(!C::WorldFromDepth(inv, kProj, 0.0f, 0.0f, 0.0f, none, nullptr), "a depth that gives no z in front (the far plane's 0) is no point");
        Expect(Near(C::HeadingDeg(f), 0.5f * C::kDeg, 1e-2f) && Near(BbTestGoto::PitchDeg(f), 0.2f * C::kDeg, 1e-2f), "heading and pitch of a view");
        Expect(Near(C::WrapDeg(190.0f), -170.0f, 1e-3f) && Near(C::WrapDeg(-190.0f), 170.0f, 1e-3f) && Near(C::WrapRad(4.0f), 4.0f - 2.0f * C::kPi, 1e-4f),
               "angles wrap");
        const float box[6] = {3.5f, 1.0f, 2.0f, 4.5f, 2.0f, 3.0f};
        const C::Box b = C::BoxOf(view, kProj, 1920.0f, 1080.0f, box);
        Expect(b.any && b.x1 > b.x0 && b.y1 > b.y0, "a box in front has a screen rectangle");
    }
    // ---- the hold
    {
        std::uint8_t camera[0x200] = {};
        const float pitch = 0.1f, yaw = 0.2f, highest = 0.9f, lowest = -0.5f;
        std::memcpy(camera + C::kPitchAt, &pitch, 4);
        std::memcpy(camera + C::kYawAt, &yaw, 4);
        std::memcpy(camera + C::kHighestAt, &highest, 4);
        std::memcpy(camera + C::kLowestAt, &lowest, 4);
        std::uint8_t had = 0;
        Expect(!C::HoldWanted(), "no hold at the start");
        C::g_cmd_valid.store(false);
        const std::uint64_t before = C::g_updates.load();
        Expect(!C::HoldApply(camera, &had) && had == 0 && C::g_updates.load() == before + 1, "no command: the fields are published, nothing written");
        Expect(Near(C::g_seen_yaw.load(), 0.2f, 1e-6f) && Near(C::g_seen_highest.load(), 0.9f, 1e-6f) && Near(C::g_seen_lowest.load(), -0.5f, 1e-6f),
               "the game's fields and limits are published");
        C::g_cmd_pitch.store(2.0f);
        C::g_cmd_yaw.store(4.0f);
        C::g_cmd_valid.store(true);
        const bool wrote = C::HoldApply(camera, &had);
        float np, ny;
        std::memcpy(&np, camera + C::kPitchAt, 4);
        std::memcpy(&ny, camera + C::kYawAt, 4);
        Expect(wrote && had == 1 && Near(np, 0.9f, 1e-6f) && Near(ny, 4.0f - 2.0f * C::kPi, 1e-4f), "the command is written: pitch clamped to the limit, yaw wrapped");
        C::g_cmd_valid.store(false);
    }
    // ---- the controller on simulated cameras
    {
        const float target[3] = {10.0f, 1.5f, 5.0f};
        const float sign[4][2] = {{1, 1}, {-1, -1}, {-1, 1}, {1, -1}};
        for (const auto& sg : sign) {
            Plant pl(sg[0], sg[1]);
            C::Session sess;
            const C::Goal goal = C::ParseGoal("lookat:10,1.5,5,3,40,30");
            const Run run = Go(sess, pl, goal, 2400, 0, nullptr, nullptr, "lookat:10,1.5,5,3,40,30");
            float cam[3], fwd[3];
            pl.Cam(cam);
            pl.Fwd(fwd);
            const float dy = target[1] - cam[1];
            const float horiz = std::hypot(target[0] - cam[0], target[2] - cam[2]);
            const float h2 = 9.0f - dy * dy;
            float want = h2 > 1.0f ? std::sqrt(h2) : 1.0f;
            want = std::fmax(want, std::hypot(cam[0] - pl.hunter[0], cam[2] - pl.hunter[2]) + C::kBehind); // the hunter stands kBehind in front
            Expect(run.ready_frame >= 0, "the camera gets READY and framed on every sign of the fields");
            Expect(Near(C::WrapDeg(pl.Heading() - 40.0f), 0.0f, 1.5f), "the heading ends within 1.5 degrees of the asked one");
            Expect(Near(horiz, want, 0.5f), "the horizontal distance ends where dist and the camera's height put it");
            float view[12], inv[12];
            Matrices(cam, fwd, view, inv);
            const C::Screen s = C::ScreenOf(view, kProj, 1920.0f, 1080.0f, target);
            Expect(s.ok && s.x > 192.0f && s.x < 1728.0f && s.y > 108.0f && s.y < 972.0f, "the target ends in the middle 80 percent of the picture");
            Expect(Near(sess.RatioYaw(), sg[0] * 1.0f, 0.05f) && Near(sess.RatioPitch(), sg[1] * 0.8f, 0.05f), "the probe learns the signs and the ratios");
        }
        // a target higher than the game's pitch limit lets the camera look: the cap on the look-up is lowered, the camera backs off
        Plant pl(-1, -1);
        pl.lo = -0.5f;
        pl.hi = 0.5f;
        C::Session sess;
        const Run run = Go(sess, pl, C::ParseGoal("lookat:0,6.3,12,4,0,30"), 2400, 0, nullptr, nullptr, "lookat:0,6.3,12,4,0,30");
        Expect(run.ready_frame >= 0, "a high target is framed after the look-up cap follows the game's pitch limit");
        // the same place twice, with the kept point and the learned signs
        Plant again(-1, 1);
        C::Session twice;
        const float kept[3] = {2.0f, 1.0f, 6.0f};
        const Run first = Go(twice, again, C::ParseGoal("lookat:kept,1.5,0,30"), 2400, 0, kept, nullptr, "lookat:kept,1.5,0,30");
        float cam1[3], cam2[3];
        again.Cam(cam1);
        const float heading1 = again.Heading();
        again.yaw += 0.6f; // the game's own camera after the release
        again.pitch = 0.4f;
        std::vector<std::string> lines;
        twice.Release(lines, "test");
        Expect(lines.size() == 1 && Has(lines[0], "released (test)"), "a release is logged once");
        const Run second = Go(twice, again, C::ParseGoal("lookat:kept,1.5,0,30"), 1200, 5000, kept, nullptr, "lookat:kept,1.5,0,30");
        again.Cam(cam2);
        Expect(first.ready_frame >= 0 && second.ready_frame >= 0 && C::Dist3(cam1, cam2) < 0.5f && Near(C::WrapDeg(again.Heading() - heading1), 0.0f, 1.5f),
               "set again after an unset: the camera comes back to the same place");
        // lookat:centre fixes the heading it aims with (auto: the bearing from where the camera is); lookat:kept with auto yaw takes it again
        Plant centre_plant(1, 1);
        C::Session centre_session;
        const float centre_point[3] = {5.0f, 1.2f, 8.0f};
        const Run c1 = Go(centre_session, centre_plant, C::ParseGoal("lookat/centre/2/auto/30"), 2400, 0, nullptr, centre_point, "lookat/centre/2/auto/30");
        float ccam1[3];
        centre_plant.Cam(ccam1);
        const float cheading1 = centre_plant.Heading();
        Expect(c1.ready_frame >= 0 && c1.yaw_remembered && Near(C::WrapDeg(cheading1 - c1.yaw), 0.0f, 1.5f), "centre: READY, and the heading it chose is remembered");
        centre_plant.yaw += 1.1f;
        centre_plant.pitch = -0.3f;
        std::vector<std::string> centre_lines;
        centre_session.Release(centre_lines, "test");
        const Run c2 = Go(centre_session, centre_plant, C::ParseGoal("lookat/kept/2/auto/30"), 2400, 5000, centre_point, nullptr, "lookat/kept/2/auto/30", &c1.yaw);
        float ccam2[3];
        centre_plant.Cam(ccam2);
        Expect(c2.ready_frame >= 0 && C::Dist3(ccam1, ccam2) < 0.5f && Near(C::WrapDeg(centre_plant.Heading() - cheading1), 0.0f, 1.5f),
               "kept with auto yaw: the same heading and place as the centre read gave");
        // a camera that takes no command fails, and says so
        Dead dead(1, 1);
        C::Session failing;
        (void)Go(failing, dead, C::ParseGoal("lookat:1,1,1"), 900, 0, nullptr, nullptr, "lookat:1,1,1");
        Expect(failing.GetPhase() == C::Session::Phase::Failed && !failing.Busy(), "a camera that takes no command fails");
        // pose: the camera at x,z with a heading and pitch
        Plant pp(1, 1);
        C::Session pose;
        const Run pr = Go(pose, pp, C::ParseGoal("pose:4,0,-3,70,-10"), 2400, 0, nullptr, nullptr, "pose:4,0,-3,70,-10");
        float pcam[3];
        pp.Cam(pcam);
        Expect(pr.ready_frame >= 0 && Near(pcam[0], 4.0f, 0.5f) && Near(pcam[2], -3.0f, 0.5f) && Near(C::WrapDeg(pp.Heading() - 70.0f), 0.0f, 1.5f) &&
                   Near(pp.Pitch(), -10.0f, 1.5f),
               "pose: the camera ends at x,z with the asked heading and pitch");
    }
    // ---- r120b: aim (turn only), the reach rule, the fall guard, FAILED holds the picture
    {
        const C::Goal a = C::ParseGoal("aim:10,1.5,5");
        Expect(a.kind == C::Kind::Aim && !a.bad && a.point[0] == 10.0f && a.point[1] == 1.5f && a.point[2] == 5.0f, "aim:x,y,z");
        Expect(C::ParseGoal("aim/centre").kind == C::Kind::Aim && C::ParseGoal("aim/centre").centre && C::ParseGoal("aim:kept").kept &&
                   C::ParseGoal("aim:hang").from_hang,
               "aim:centre, aim:kept and aim:hang");
        Expect(C::ParseGoal("aim:1,2").bad && C::ParseGoal("aim:centre,1").bad && C::ParseGoal("aim").bad && C::ParseGoal("aim:1,2").kind == C::Kind::Off,
               "aim texts that are not understood are bad and off");
        Expect(C::ParseGoal("hang").from_hang && !C::ParseGoal("hang").dist_set && C::ParseGoal("hang/4/auto/45").dist_set &&
                   !C::ParseGoal("lookat:1,2,3").dist_set && C::ParseGoal("lookat/centre/1.5/auto/30").dist_set,
               "dist_set says whether a distance was asked");
        const auto said = [](const Run& r, const char* part) {
            for (const std::string& l : r.said) {
                if (Has(l, part)) {
                    return true;
                }
            }
            return false;
        };
        const float tg[3] = {10.0f, 1.5f, 5.0f};
        const float sign[4][2] = {{1, 1}, {-1, -1}, {-1, 1}, {1, -1}};
        const float starts[3][3] = {{0.0f, 0.0f, 0.0f}, {3.0f, 0.0f, -4.0f}, {9.0f, 0.0f, 4.5f}};
        for (const auto& sg : sign) {
            for (const auto& st : starts) {
                Plant pl(sg[0], sg[1]);
                std::memcpy(pl.hunter, st, sizeof pl.hunter);
                C::Session sess;
                const Run run = Go(sess, pl, C::ParseGoal("aim:10,1.5,5"), 2400, 0, nullptr, nullptr, "aim:10,1.5,5");
                float cam[3], fwd[3], view[12], inv[12];
                pl.Cam(cam);
                pl.Fwd(fwd);
                Matrices(cam, fwd, view, inv);
                const C::Screen s = C::ScreenOf(view, kProj, 1920.0f, 1080.0f, tg);
                Expect(run.ready_frame >= 0 && run.posts == 0 && pl.hunter[0] == st[0] && pl.hunter[2] == st[2] && s.ok && s.x > 192.0f && s.x < 900.0f &&
                           Near(s.y, 540.0f, 108.0f),
                       "aim: READY on every sign of the fields from three places, no walk, the hunter never moved, the target level and left of the middle (r120c: off the hunter)");
            }
        }
        {
            Plant pl(1, 1);
            C::Session sess;
            const float near_t[3] = {1.5f, 1.4f, 1.0f};
            const Run run = Go(sess, pl, C::ParseGoal("aim:1.5,1.4,1"), 2400, 0, nullptr, nullptr, "aim:1.5,1.4,1");
            float cam[3], fwd[3], view[12], inv[12];
            pl.Cam(cam);
            pl.Fwd(fwd);
            Matrices(cam, fwd, view, inv);
            const C::Screen s = C::ScreenOf(view, kProj, 1920.0f, 1080.0f, near_t);
            Expect(run.ready_frame >= 0 && run.posts == 0 && s.ok && s.x > 192.0f && s.x < 960.0f, "aim at a target nearer than the camera's stand: along the line from the pivot");
        }
        {
            Plant pl(-1, -1);
            pl.lo = -0.5f;
            pl.hi = 0.5f;
            C::Session sess;
            const Run run = Go(sess, pl, C::ParseGoal("aim:0,12,6"), 1500, 0, nullptr, nullptr, "aim:0,12,6");
            Expect(sess.GetPhase() == C::Session::Phase::Failed && run.failed && run.engaged && run.posts == 0 && Has(run.why, "FAILED:") &&
                       Has(run.why, "pitch limit"),
                   "aim at a target above the game's pitch limit fails with the reason, no walk, and the picture stays held");
        }
        {
            Plant pl(1, 1);
            C::Session sess;
            const Run run = Go(sess, pl, C::ParseGoal("lookat:10,1.5,5"), 2400, 0, nullptr, nullptr, "lookat:10,1.5,5");
            Expect(run.ready_frame >= 0 && run.posts == 0 && said(run, "within reach of the camera as it stands"),
                   "lookat with no distance asked and the target within reach only turns, and says so");
            Plant pl2(1, 1);
            C::Session sess2;
            const Run placed = Go(sess2, pl2, C::ParseGoal("lookat:10,1.5,5,3,auto,30"), 2400, 0, nullptr, nullptr, "lookat:10,1.5,5,3,auto,30");
            Expect(placed.ready_frame >= 0 && placed.posts > 0 && !said(placed, "within reach"), "lookat with a distance asked 5 m from the camera is placed by walking, as in r120");
            Plant pl3(1, 1);
            float c0[3];
            pl3.Cam(c0);
            char text[64];
            std::snprintf(text, sizeof text, "lookat:10,1.5,5,%.2f,auto,30", double(C::Dist3(c0, tg) - 0.4f));
            C::Session sess3;
            const Run close = Go(sess3, pl3, C::ParseGoal(text), 2400, 0, nullptr, nullptr, text);
            Expect(close.ready_frame >= 0 && close.posts == 0 && said(close, "within reach"), "a distance under a metre from where the camera stands turns only: no hop for it");
        }
        {
            Plant pl(1, 1);
            C::Session sess;
            const Run run = Go(sess, pl, C::ParseGoal("lookat:10,1.5,5,3,40,30"), 1500, 0, nullptr, nullptr, "lookat:10,1.5,5,3,40,30", nullptr, 400);
            Expect(sess.GetPhase() == C::Session::Phase::Failed && run.failed && run.engaged && Has(run.why, "fell"),
                   "a hunter who falls through the floor ends the hold at once, and the picture stays held with the reason");
        }
        {
            Plant pl(1, 1);
            pl.hunter[0] = -11.0f;
            pl.hunter[1] = -8.0f;
            pl.hunter[2] = -28.0f;
            const float kept_far[3] = {-4.57f, 0.33f, 2.93f};
            const float ky = 10.0f;
            C::Session sess;
            const Run run = Go(sess, pl, C::ParseGoal("lookat:kept/1.5/auto/30"), 400, 0, kept_far, nullptr, "lookat:kept/1.5/auto/30", &ky);
            Expect(sess.GetPhase() == C::Session::Phase::Failed && run.posts == 0 && run.ready_frame < 0 && Has(run.why, "place"),
                   "lookat:kept from a camera that has fallen with the hunter plans no long walk: it fails, nothing is held");
        }
    }
    // ---- r120c: the centre read skips the hunter, aim at a point 5 to 30 m away, the hunter beside the line of sight, aim:hang backs away from a target
    // above the game's pitch limit
    {
        C::CentreCandidate cand[C::kCentreCount] = {};
        bool far_enough = false;
        cand[0].ok = true;
        cand[0].view_z = 2.73f;
        cand[1].ok = true;
        cand[1].view_z = 5.49f;
        cand[2].ok = true;
        cand[2].view_z = 5.78f;
        Expect(C::PickCentre(cand, C::kCentreCount, C::kCentreMinView, &far_enough) == 1 && far_enough,
               "the centre read skips the hunter (the middle, 2.7 m) and takes the first pixel 5 m or more away");
        cand[1].ok = false;
        cand[2].ok = false;
        cand[3].ok = true;
        cand[3].view_z = 3.9f;
        Expect(C::PickCentre(cand, C::kCentreCount, C::kCentreMinView, &far_enough) == 3 && !far_enough,
               "nothing 5 m away: the farthest valid pixel, and it says so");
        for (C::CentreCandidate& c : cand) {
            c.ok = false;
        }
        Expect(C::PickCentre(cand, C::kCentreCount, C::kCentreMinView, &far_enough) == -1 && !far_enough, "no valid pixel: none");
        Expect(C::ParseGoal("aim:hang").stepback && !C::ParseGoal("aim:centre").stepback && !C::ParseGoal("hang").stepback, "only aim:hang may step back");
        const auto said2 = [](const Run& r, const char* part) {
            for (const std::string& l : r.said) {
                if (Has(l, part)) {
                    return true;
                }
            }
            return false;
        };
        const auto hunter_covers = [](const Plant& pl, const float tg[3]) {
            float cam[3], fwd[3], view[12], inv[12];
            pl.Cam(cam);
            pl.Fwd(fwd);
            Matrices(cam, fwd, view, inv);
            const C::Screen s = C::ScreenOf(view, kProj, 1920.0f, 1080.0f, tg);
            const float hb[6] = {pl.hunter[0] - C::kHunterBoxHalf, pl.hunter[1] - C::kHunterBoxDown, pl.hunter[2] - C::kHunterBoxHalf,
                                 pl.hunter[0] + C::kHunterBoxHalf, pl.hunter[1] + C::kHunterBoxUp, pl.hunter[2] + C::kHunterBoxHalf};
            const C::Box box = C::BoxOf(view, kProj, 1920.0f, 1080.0f, hb);
            return s.ok && box.any && s.x >= box.x0 && s.x <= box.x1 && s.y >= box.y0 && s.y <= box.y1;
        };
        {
            // the dark alley's lamp: the world point the b65 depth read gave, 10 m from the camera
            const float lamp[3] = {-23.96f, -28.33f, 109.53f};
            Plant pl(1, 1);
            pl.hunter[0] = -10.2f;
            pl.hunter[1] = -32.4f;
            pl.hunter[2] = 108.7f;
            C::Session sess;
            const Run run = Go(sess, pl, C::ParseGoal("aim:-23.96,-28.33,109.53"), 2400, 0, nullptr, nullptr, "aim:-23.96,-28.33,109.53");
            float cam[3], fwd[3], view[12], inv[12];
            pl.Cam(cam);
            pl.Fwd(fwd);
            Matrices(cam, fwd, view, inv);
            const C::Screen s = C::ScreenOf(view, kProj, 1920.0f, 1080.0f, lamp);
            Expect(run.ready_frame >= 0 && run.posts == 0 && pl.hunter[0] == -10.2f && s.ok && s.x > 192.0f && s.x < 760.0f && !hunter_covers(pl, lamp),
                   "aim at the alley lamp 10 m away: READY, no walk, the hunter beside the line of sight, the lamp in the middle 80 percent and not covered");
        }
        {
            // a target that the pitch limit would stop at (the view's look-up ends at 0.8 * 0.7 * 57.3 - 4 = 28 degrees): back away, then aim
            const float lantern[3] = {6.0f, 7.0f, 0.0f};
            Plant pl(1, 1);
            pl.hi = 0.7f;
            C::Session sess;
            const Run run = Go(sess, pl, C::ParseGoal("aim:hang"), 3000, 0, nullptr, nullptr, "aim:hang", nullptr, -1, lantern);
            const float back = std::hypot(lantern[0] - pl.hunter[0], lantern[2] - pl.hunter[2]);
            float end_fwd[3];
            pl.Fwd(end_fwd);
            Expect(run.ready_frame >= 0 && run.posts >= 1 && run.posts <= static_cast<int>(C::kTriesMost) && said2(run, "step back 1:") && back > 11.0f &&
                       BbTestGoto::PitchDeg(end_fwd) < 24.5f && !hunter_covers(pl, lantern),
                   "aim:hang above the pitch limit: the hunter backs away along the ground, then the look is under the limit less 5 degrees, not covered");
            Plant pl2(1, 1);
            pl2.hi = 0.7f;
            C::Session sess2;
            const Run refused = Go(sess2, pl2, C::ParseGoal("aim:6,7,0"), 1500, 0, nullptr, nullptr, "aim:6,7,0");
            Expect(sess2.GetPhase() == C::Session::Phase::Failed && refused.posts == 0, "aim:x,y,z at the same target still fails with the numbers: no step back");
        }
    }

    // ---- r120b: the capture gate's owner and a failed camera
    {
        const char* name = "test-camera-r120b.trigger";
        { std::ofstream f(name); f << "x"; }
        C::PublishGate(false, false, std::string(), std::string());
        Expect(!C::OwnsGate(), "no camera held: r112o's gate is not bypassed");
        C::PublishGate(true, true, "camera to target 3.00 m", "");
        Expect(C::OwnsGate() && !C::CaptureHeld(name), "a READY, framed camera owns the gate and takes the picture");
        C::PublishGate(true, true, "camera to target 3.00 m", "FAILED: the hunter fell", true);
        Expect(C::OwnsGate() && C::CaptureHeld(name), "a FAILED camera still owns the gate and never takes a picture, even if it says framed");
        C::PublishGate(false, false, std::string(), std::string());
        Expect(!C::OwnsGate() && !C::CaptureHeld(name), "released: the gate is free again");
        std::remove(name);
    }
    // ---- the lines
    {
        C::Session sess;
        std::vector<std::string> lines;
        sess.Begin(C::ParseGoal("lookat:1,2,3,1.5,90,20"), 0, "lookat:1,2,3,1.5,90,20", lines);
        Expect(lines.size() == 1 && Has(lines[0], "GLINT-PROOF test camera (r120): BB_TEST_CAMERA=lookat:1,2,3,1.5,90,20: lookat: 1.5 m from the target") &&
                   Has(lines[0], "heading as asked") && Has(lines[0], "at most 20 degrees of look-up"),
               "the first line says what was asked");
    }
    // ---- the driver and the mailbox
    {
        C::Driver& d = C::TheDriver();
        d.Refresh("lookat:centre/1.5/0/30", "1395/624;1426/624;1600/300");
        Expect(d.goal.kind == C::Kind::LookAt && d.goal.centre && d.goal_changed && C::WorldWanted() && d.Needed(),
               "both knobs are taken: a goal and a pixel list to read");
        C::WorldJob job;
        Expect(C::TakeWorldJob(&job) && job.n == 3 && job.user == 3 && !job.centre && !C::WorldWanted(), "the world-at pass takes the three pixels once");
        Expect(!C::TakeWorldJob(&job), "nothing is left to read");
        std::vector<std::string> lines;
        C::TickIn tick;
        tick.frame = 100;
        d.Tick(tick, lines);
        Expect(!lines.empty() && Has(lines[0], "BB_TEST_CAMERA=lookat:centre/1.5/0/30") && d.session.Busy() && C::WorldWanted(),
               "the goal begins and asks for the picture's middle");
        Expect(C::TakeWorldJob(&job) && job.n == C::kCentreCount && job.centre && job.user == 0, "the centre read is the middle and four pixels around it");
        Expect(job.px[0].x == 960 && job.px[0].y == 540, "the first of them is the middle of the 1920x1080 picture");
        const float world[3] = {1.0f, 2.0f, 3.0f};
        C::PublishCentre(job.centre_serial, true, world, "");
        lines.clear();
        tick.frame = 101;
        d.Tick(tick, lines);
        Expect(d.session.GetPhase() == C::Session::Phase::Seen && Near(d.session.Target()[2], 3.0f, 1e-6f), "the middle's world point becomes the target");
        d.Refresh("", "1395/624;1426/624;1600/300");
        lines.clear();
        tick.frame = 102;
        d.Tick(tick, lines);
        Expect(!d.session.Busy() && !C::HoldWanted() && !C::g_gate_engaged.load() && !lines.empty() && Has(lines[0], "released (BB_TEST_CAMERA unset)"),
               "unset releases the camera, the hold and the gate");
        d.Refresh("lookat:1,2", "");
        lines.clear();
        d.Tick(tick, lines);
        Expect(!d.session.Busy() && !lines.empty() && Has(lines.back(), "is not understood"), "a text that is not understood is said and holds nothing");
        d.Refresh("", "");
        d.Tick(tick, lines);
        Expect(!d.Needed(), "with both knobs unset nothing is needed");
    }
    // ---- the capture gate
    {
        Expect(!C::CaptureHeld("no-such-trigger.r120") && !C::CaptureHeld(nullptr), "off: never held");
        const char* name = "test-camera-r120.trigger";
        { std::ofstream f(name); f << "x"; }
        C::PublishGate(true, false, "camera to target 3.00 m", "the camera is not at its place yet");
        Expect(C::CaptureHeld(name), "engaged and not framed: the trigger is held");
        C::PublishGate(true, true, "camera to target 1.50 m", "");
        Expect(!C::CaptureHeld(name), "framed and fresh: the trigger is taken");
        C::PublishGate(false, false, std::string(), std::string());
        Expect(!C::CaptureHeld(name), "disengaged: never held");
        std::remove(name);
    }
    if (failures == 0) {
        std::printf("test camera: ok\n");
    }
    return failures == 0 ? 0 : 1;
}
