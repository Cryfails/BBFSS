// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r112n_hang-teleport-camera, TOOL; goes to the test-tools branch): the render side of BB_TEST_GOTO
// (bbport_test_goto.h has the knobs, the mailbox and the plan's arithmetic). Every time the hang survey's box set is read
// (WindHangFindRefresh: every 60 frames at most, only with BB_WIND_HANG=1) Observe is asked once:
//   1. it waits for the target (hang mode: the nearest PUSHED hanging mesh of the scene, BB_TEST_GOTO_VS narrows it) and
//      locks its box;
//   2. it plans where the hunter must stand so that the follow camera, which keeps its heading, ends BB_TEST_GOTO_DIST metres
//      from the mesh with the mesh straight ahead, and posts the request (the game thread moves the hunter);
//   3. 120 frames after the move it measures the camera again (the camera is read from the ray traced scene, not guessed) and,
//      when it is not there (BB_TEST_GOTO_DIST, 10 degrees of bearing), plans another move, at most 4 warps;
//   4. from then on it only reports: the numbers of every observation are one line each (the slot runner keeps the lines
//      that start with GLINT-PROOF: the first 24 and the last 24 of a run): the camera's 3 D and horizontal distance to the
//      mesh, the camera's pitch and the target's elevation (how much more look-up the stick must give), the mesh's
//      screen box (the survey's ScreenOf of its 8 corners) and whether its middle lies in the picture, the hunter, the target.
// Fixed position mode (BB_TEST_GOTO=x,y,z) does only step 2 with that position and the reports.
//
// Off (BB_TEST_GOTO unset or not understood): Observe returns at its first line. Nothing here runs without BB_WIND_HANG=1.

#include <array>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "bbport_test_goto.h"
#include "bbport_wind_hang_find.h"
#include "bbport_test_goto_walk.h" // bbport (r112o_hang-safe-goto, TOOL)

namespace BbTestGoto {

enum class Phase : std::uint8_t { Wait, Moving, Settling, Holding, GaveUp };

[[nodiscard]] inline const char* PhaseName(Phase p) {
    switch (p) {
    case Phase::Wait:
        return "waiting";
    case Phase::Moving:
        return "warp asked";
    case Phase::Settling:
        return "settling";
    case Phase::Holding:
        return "holding";
    case Phase::GaveUp:
        return "gave up";
    }
    return "?";
}

struct Session {
    Phase phase = Phase::Wait;
    unsigned tries = 0, calls = 0, mismatches = 0;
    std::uint32_t seq = 0;
    std::uint64_t phase_frame = 0;
    bool locked = false;
    std::uint64_t stream = 0;
    std::uint32_t vs = 0;
    std::array<float, 6> box{};
    float centre[3] = {};
    float ground_y = 0.0f;
    float horiz_want = 0.0f;
    unsigned lines = 0;
};

[[nodiscard]] inline Session& Sess() {
    static Session s;
    return s;
}

struct ScreenBox {
    bool any = false; ///< at least one corner is in front of the camera
    bool all = false; ///< all 8
    float x0 = 0.0f, y0 = 0.0f, x1 = 0.0f, y1 = 0.0f;
};

/// The screen rectangle of a world box (the survey's ScreenOf of its 8 corners that lie in front of the camera).
[[nodiscard]] inline ScreenBox ScreenBoxOf(const BbWindHangFind::BoxSet& set, const std::array<float, 6>& b) {
    ScreenBox r;
    int in_front = 0;
    for (int i = 0; i < 8; ++i) {
        const BbWindHangFind::Screen s = BbWindHangFind::ScreenOf(set, (i & 1) ? b[3] : b[0], (i & 2) ? b[4] : b[1],
                                                                  (i & 4) ? b[5] : b[2]);
        if (!s.ok) {
            continue;
        }
        if (in_front == 0) {
            r.x0 = r.x1 = s.x;
            r.y0 = r.y1 = s.y;
        } else {
            r.x0 = std::min(r.x0, s.x);
            r.x1 = std::max(r.x1, s.x);
            r.y0 = std::min(r.y0, s.y);
            r.y1 = std::max(r.y1, s.y);
        }
        ++in_front;
    }
    r.any = in_front > 0;
    r.all = in_front == 8;
    return r;
}

/// What one observation read.
struct Reading {
    bool cam_ok = false, fwd_ok = false, hunter_ok = false, view_ok = false;
    float cam[3] = {}, fwd[3] = {}, hunter[3] = {};
    ScreenBox sb;
    std::uint32_t width = 0, height = 0;
};

[[nodiscard]] inline Reading ReadingOf(const BbWindHangFind::BoxSet& set, const std::array<float, 6>& box,
                                       const float* hunter) {
    Reading r;
    r.cam_ok = set.camera_ok && Finite3(set.camera.data());
    if (r.cam_ok) {
        std::memcpy(r.cam, set.camera.data(), sizeof r.cam);
    }
    r.view_ok = set.view_ok;
    if (set.view_ok) {
        r.fwd[0] = set.view[8];
        r.fwd[1] = set.view[9];
        r.fwd[2] = set.view[10];
        r.fwd_ok = Finite3(r.fwd);
        r.sb = ScreenBoxOf(set, box);
        r.width = set.render[0];
        r.height = set.render[1];
    }
    if (hunter != nullptr && Finite3(hunter)) {
        r.hunter_ok = true;
        std::memcpy(r.hunter, hunter, sizeof r.hunter);
    }
    return r;
}

/// The report line of one observation: numbers first.
[[nodiscard]] inline std::string LineOf(const Session& s, const Reading& r, std::uint64_t frame) {
    char part[240];
    std::string out;
    std::snprintf(part, sizeof(part), "GLINT-PROOF hang goto (r112n): %s f%llu: ", PhaseName(s.phase),
                  static_cast<unsigned long long>(frame));
    out += part;
    if (r.cam_ok) {
        const float d3 = std::sqrt(std::pow(s.centre[0] - r.cam[0], 2.0f) + std::pow(s.centre[1] - r.cam[1], 2.0f) +
                                   std::pow(s.centre[2] - r.cam[2], 2.0f));
        std::snprintf(part, sizeof(part), "camera to target %.1f m (horizontal %.1f m, %+.1f m up)", double(d3),
                      double(Horizontal(r.cam, s.centre)), double(s.centre[1] - r.cam[1]));
        out += part;
        std::snprintf(part, sizeof(part), ", target elevation %+.0f deg", double(ElevationDeg(r.cam, s.centre)));
        out += part;
    } else {
        out += "camera not read";
    }
    if (r.fwd_ok) {
        std::snprintf(part, sizeof(part), ", view pitch %+.0f deg", double(PitchDeg(r.fwd)));
        out += part;
        if (r.cam_ok) {
            std::snprintf(part, sizeof(part), ", bearing off %.0f deg", double(BearingOffDeg(r.cam, r.fwd, s.centre)));
            out += part;
        }
    }
    if (r.view_ok && r.sb.any) {
        const float cx = 0.5f * (r.sb.x0 + r.sb.x1), cy = 0.5f * (r.sb.y0 + r.sb.y1);
        const bool in_view = cx >= 0.0f && cy >= 0.0f && cx < float(r.width) && cy < float(r.height);
        std::snprintf(part, sizeof(part), "; screen box %.0f,%.0f to %.0f,%.0f of %ux%u (middle %.0f,%.0f: %s%s)",
                      double(r.sb.x0), double(r.sb.y0), double(r.sb.x1), double(r.sb.y1),
                      static_cast<unsigned>(r.width), static_cast<unsigned>(r.height), double(cx), double(cy),
                      in_view ? "IN VIEW" : "OUT OF VIEW", r.sb.all ? "" : ", partly behind the camera");
        out += part;
    } else if (r.view_ok) {
        out += "; screen box: behind the camera";
    } else {
        out += "; screen box: the view is not read";
    }
    if (r.hunter_ok) {
        std::snprintf(part, sizeof(part), "; hunter %.2f %.2f %.2f", double(r.hunter[0]), double(r.hunter[1]),
                      double(r.hunter[2]));
        out += part;
    } else {
        out += "; hunter not read";
    }
    std::snprintf(part, sizeof(part), "; target vs %08x middle %.2f %.2f %.2f ground y %.2f; warps %u",
                  static_cast<unsigned>(s.vs), double(s.centre[0]), double(s.centre[1]), double(s.centre[2]),
                  double(s.ground_y), s.tries);
    out += part;
    return out;
}

/// bbport (r112o_hang-safe-goto): whether a picture taken now would show the target. Phase holding (the run arrived), the camera and
/// its view read, the target's screen box in front of the camera with its middle in the middle 80 percent of the picture, the box
/// 6 px or more and the camera 12 m or less from it (3 D). A fixed position (BB_TEST_GOTO=x,y,z) is framed when the run holds.
struct Framing {
    bool framed = false;
    std::string why;   ///< what is wrong (empty when framed)
    std::string text;  ///< camera to target and the screen box, for the capture lines
    std::string line;  ///< the observation's own log line
};

[[nodiscard]] inline Framing FramingOf(const Knobs& k, const Session& s, const Reading& r, std::uint64_t frame) {
    Framing f;
    char part[240];
    float d3 = 0.0f;
    if (r.cam_ok) {
        d3 = std::sqrt(std::pow(s.centre[0] - r.cam[0], 2.0f) + std::pow(s.centre[1] - r.cam[1], 2.0f) +
                       std::pow(s.centre[2] - r.cam[2], 2.0f));
        std::snprintf(part, sizeof(part), "camera to target %.1f m (horizontal %.1f m)", double(d3),
                      double(Horizontal(r.cam, s.centre)));
        f.text = part;
    } else {
        f.text = "camera not read";
    }
    const float w = float(r.width), h = float(r.height);
    const float cx = 0.5f * (r.sb.x0 + r.sb.x1), cy = 0.5f * (r.sb.y0 + r.sb.y1);
    if (r.view_ok && r.sb.any) {
        std::snprintf(part, sizeof(part), ", screen box %.0f,%.0f to %.0f,%.0f of %ux%u", double(r.sb.x0), double(r.sb.y0),
                      double(r.sb.x1), double(r.sb.y1), static_cast<unsigned>(r.width), static_cast<unsigned>(r.height));
        f.text += part;
    } else if (r.view_ok) {
        f.text += ", screen box behind the camera";
    }
    if (s.phase != Phase::Holding) {
        f.why = std::string("the run has not arrived (") + PhaseName(s.phase) + ")";
    } else if (!k.hang) {
        f.framed = true;
    } else if (!r.cam_ok || !r.view_ok) {
        f.why = "the camera or its view is not read";
    } else if (!r.sb.any) {
        f.why = "the target is behind the camera";
    } else if (!(w > 0.0f && h > 0.0f)) {
        f.why = "the render size is not read";
    } else if (cx < FramedMargin * w || cx > (1.0f - FramedMargin) * w || cy < FramedMargin * h ||
               cy > (1.0f - FramedMargin) * h) {
        f.why = "the target's middle is outside the middle 80 percent of the picture (the pad's ry=0 looks up)";
    } else if (std::max(r.sb.x1 - r.sb.x0, r.sb.y1 - r.sb.y0) < FramedMinPx) {
        f.why = "the target's screen box is under 6 px";
    } else if (d3 > FramedMaxDist) {
        f.why = "the target is more than 12 m from the camera";
    } else {
        f.framed = true;
    }
    unsigned taken = 0, refused = 0;
    Counts(&taken, &refused);
    std::snprintf(part, sizeof(part), "GLINT-PROOF hang goto (r112o): framing f%llu: %s%s%s (", static_cast<unsigned long long>(frame),
                  f.framed ? "FRAMED" : "NOT FRAMED", f.framed ? "" : ": ", f.why.c_str());
    f.line = part;
    f.line += f.text;
    std::snprintf(part, sizeof(part), "); captures taken %u, refused polls %u", taken, refused);
    f.line += part;
    return f;
}

/// One observation of the hang survey's box set, with the knobs and the session given (the tests' entry). Returns the lines
/// to print (the caller prints them). `hunter` is the game's physics position (null: not read). `frame` counts the effects'
/// frames.
template <class JudgeBook>
[[nodiscard]] inline std::vector<std::string> ObserveWith(const Knobs& k, Session& s, const BbWindHangFind::BoxSet& set,
                                                          const BbWindHangFind::StaticBook& book,
                                                          BbWindHang::Book& heights, const JudgeBook& judge,
                                                          float tall_m, std::uint64_t frame, const float* hunter) {
    std::vector<std::string> out;
    if (!k.on || s.phase == Phase::GaveUp) {
        return out;
    }
    const auto say = [&](const std::string& text) {
        if (s.lines < LinesMost) {
            ++s.lines;
            out.push_back(BbWindHangFind::Cap(text.c_str()));
        }
    };
    char buf[400];
    ++s.calls;
    if (!s.locked) { // the target: the nearest pushed mesh (the survey's own classes), once
        const std::vector<BbWindHangFind::CandInfo> cands = BbWindHangFind::GatherCands(set, book, heights, judge);
        const BbWindHangFind::CandInfo* target = nullptr;
        for (const BbWindHangFind::CandInfo& c : cands) {
            if (BbWindHangFind::ClassOf(c, tall_m) != BbWindHangFind::CandClass::Pushed) {
                continue;
            }
            if (k.vs_set && static_cast<std::uint32_t>(c.e.vs & 0xffffffffull) != k.vs) {
                continue;
            }
            target = &c;
            break;
        }
        if (target != nullptr) {
            s.locked = true;
            s.stream = target->stream;
            s.vs = static_cast<std::uint32_t>(target->e.vs & 0xffffffffull);
            s.box = target->box;
            s.centre[0] = 0.5f * (s.box[0] + s.box[3]);
            s.centre[1] = 0.5f * (s.box[1] + s.box[4]);
            s.centre[2] = 0.5f * (s.box[2] + s.box[5]);
            s.ground_y = s.box[1] - target->e.above;
            std::snprintf(buf, sizeof(buf),
                          "GLINT-PROOF hang goto (r112n): target locked: vs %08x (%u verts, %u place%s), box %.2f m tall "
                          "%.2f m wide, %.2f m up, middle %.2f %.2f %.2f, ground y %.2f, %.1f m from the camera now; "
                          "mode %s, camera distance wanted %.1f m",
                          static_cast<unsigned>(s.vs), target->e.verts, target->places, target->places == 1 ? "" : "s",
                          double(target->e.height), double(target->e.width), double(target->e.above),
                          double(s.centre[0]), double(s.centre[1]), double(s.centre[2]), double(s.ground_y),
                          double(target->dist), k.hang ? "hang" : "fixed position", double(k.dist));
            say(buf);
        } else if (k.hang) {
            if (s.calls % 10 == 1) {
                std::snprintf(buf, sizeof(buf),
                              "GLINT-PROOF hang goto (r112n): waiting: no pushed candidate%s in the scene yet (%zu "
                              "candidates; call %u)",
                              k.vs_set ? " with that vs" : "", cands.size(), s.calls);
                say(buf);
            }
            return out;
        }
    }
    if (!s.locked) { // fixed position without a target: the centre of the position, for the report's numbers only
        std::memcpy(s.centre, k.pos, sizeof s.centre);
        s.box = {k.pos[0], k.pos[1], k.pos[2], k.pos[0], k.pos[1], k.pos[2]};
        s.ground_y = k.pos[1];
        s.locked = true;
    }
    const Reading r = ReadingOf(set, s.box, hunter);
    const std::uint64_t since = frame >= s.phase_frame ? frame - s.phase_frame : 0;

    if (s.phase == Phase::Wait && frame >= StartFrame) {
        float stand[3] = {};
        const char* why = nullptr;
        if (!r.hunter_ok) {
            why = "the hunter's position is not read yet";
        } else if (!k.hang) {
            std::memcpy(stand, k.pos, sizeof stand);
        } else if (!r.cam_ok || !r.fwd_ok) {
            why = "the camera or its view is not read yet";
        } else {
            const Plan p = PlanStand(s.centre, s.ground_y, r.cam, r.fwd, r.hunter, k.dist, k.elev);
            if (p.ok) {
                std::memcpy(stand, p.stand, sizeof stand);
                s.horiz_want = p.horiz;
            } else {
                why = p.why;
                if (++s.mismatches >= 3) {
                    s.phase = Phase::GaveUp;
                    std::snprintf(buf, sizeof(buf), "GLINT-PROOF hang goto (r112n): gave up: %s", p.why);
                    say(buf);
                    return out;
                }
            }
        }
        if (why == nullptr) {
            s.seq = Post(stand);
            s.phase = Phase::Moving;
            s.phase_frame = frame;
            ++s.tries;
            std::snprintf(buf, sizeof(buf),
                          "GLINT-PROOF hang goto (r112n): warp %u asked (try %u of %u): hunter to %.2f %.2f %.2f from "
                          "%.2f %.2f %.2f, %.1f m horizontally; camera horizontal distance wanted %.1f m",
                          s.seq, s.tries, TriesMost, double(stand[0]), double(stand[1]), double(stand[2]),
                          double(r.hunter[0]), double(r.hunter[1]), double(r.hunter[2]),
                          double(Horizontal(stand, r.hunter)), double(s.horiz_want));
            say(buf);
        } else if (s.calls % 5 == 1) {
            std::snprintf(buf, sizeof(buf), "GLINT-PROOF hang goto (r112n): waiting: %s", why);
            say(buf);
        }
    } else if (s.phase == Phase::Moving) {
        if (g_done_seq.load(std::memory_order_acquire) == s.seq) {
            const bool ok = g_done_ok.load(std::memory_order_relaxed);
            s.phase_frame = frame;
            if (ok) {
                s.phase = Phase::Settling;
                std::snprintf(buf, sizeof(buf),
                              "GLINT-PROOF hang goto (r112n): warp %u made by the game thread; settling %llu frames",
                              s.seq, static_cast<unsigned long long>(SettleFrames));
            } else {
                s.phase = Phase::GaveUp; // bbport (r112o_hang-safe-goto): a walk that failed is final, no chasing
                std::snprintf(buf, sizeof(buf), "GLINT-PROOF hang goto (r112n): warp %u refused by the game thread%s", s.seq,
                              s.phase == Phase::GaveUp ? ": gave up" : ": asking again");
            }
            say(buf);
        } else if (since > WaitFrames && !Walking()) { // bbport (r112o_hang-safe-goto): a walk in progress is waited for
            Cancel();
            s.phase_frame = frame;
            s.phase = s.tries >= TriesMost ? Phase::GaveUp : Phase::Wait;
            std::snprintf(buf, sizeof(buf),
                          "GLINT-PROOF hang goto (r112n): warp %u not served in %llu frames (a loading screen, no "
                          "hunter, or the engine hook is missing)%s",
                          s.seq, static_cast<unsigned long long>(WaitFrames),
                          s.phase == Phase::GaveUp ? ": gave up" : ": asking again");
            say(buf);
        }
    } else if (s.phase == Phase::Settling && since >= SettleFrames) {
        if (r.hunter_ok && r.hunter[1] < s.ground_y - FallGuard) { // bbport (r112o_hang-safe-goto): no second warp from a fallen hunter
            s.phase = Phase::GaveUp;
            PublishFraming(true, false, "gave up", "the hunter fell");
            std::snprintf(buf, sizeof(buf),
                          "GLINT-PROOF hang goto (r112o): gave up: the hunter is %.1f m under the ground under the target "
                          "(y %.2f, ground y %.2f): he fell; no second warp from there",
                          double(s.ground_y - r.hunter[1]), double(r.hunter[1]), double(s.ground_y));
            say(buf);
            return out;
        } else if (!k.hang) {
            s.phase = Phase::Holding;
            say("GLINT-PROOF hang goto (r112n): READY at the fixed position (hunter read in the next lines)");
        } else if (r.cam_ok && r.fwd_ok) {
            const float horiz = Horizontal(r.cam, s.centre);
            const float off = BearingOffDeg(r.cam, r.fwd, s.centre);
            if (Converged(horiz, s.horiz_want, off)) {
                s.phase = Phase::Holding;
                std::snprintf(buf, sizeof(buf),
                              "GLINT-PROOF hang goto (r112n): READY after %u warp%s: camera %.1f m horizontally from "
                              "the target (wanted %.1f), bearing off %.0f deg",
                              s.tries, s.tries == 1 ? "" : "s", double(horiz), double(s.horiz_want), double(off));
            } else if (s.tries >= TriesMost) {
                s.phase = Phase::GaveUp;
                std::snprintf(buf, sizeof(buf),
                              "GLINT-PROOF hang goto (r112n): gave up after %u warps: camera %.1f m horizontally from "
                              "the target (wanted %.1f), bearing off %.0f deg",
                              s.tries, double(horiz), double(s.horiz_want), double(off));
            } else {
                s.phase = Phase::Wait;
                s.phase_frame = frame;
                std::snprintf(buf, sizeof(buf),
                              "GLINT-PROOF hang goto (r112n): camera not there: %.1f m horizontally from the target "
                              "(wanted %.1f), bearing off %.0f deg: another warp",
                              double(horiz), double(s.horiz_want), double(off));
            }
            say(buf);
        }
    }
    const Framing framing = FramingOf(k, s, r, frame); // bbport (r112o_hang-safe-goto): the capture trigger asks this
    PublishFraming(s.locked, framing.framed, framing.text, framing.why);
    if (s.phase != Phase::GaveUp) {
        const bool quiet = s.phase == Phase::Wait && !k.hang;
        if (!quiet) {
            say(LineOf(s, r, frame));
            say(framing.line);
        }
    }
    return out;
}

/// The run's observation: BB_TEST_GOTO's knobs and the one session.
template <class JudgeBook>
[[nodiscard]] inline std::vector<std::string> Observe(const BbWindHangFind::BoxSet& set,
                                                      const BbWindHangFind::StaticBook& book,
                                                      BbWindHang::Book& heights, const JudgeBook& judge, float tall_m,
                                                      std::uint64_t frame, const float* hunter) {
    return ObserveWith(KnobsOnce(), Sess(), set, book, heights, judge, tall_m, frame, hunter);
}

} // namespace BbTestGoto
