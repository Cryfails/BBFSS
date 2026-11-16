# r102b_camera-clean-hud: FEATURE patch (camera mode, order item 2). On top of r77 (clean shot rule),
# r102_camera-mode-1-2 and r102_camera-mode-3-4.fixed. Everything new is off by default.
#
# REVIEWED 2026-11-15 22:55: this .fixed.py replaces the draft r102b_camera-clean-hud.py (apply this one,
# never both; each refuses the other's applied state). Changes against the draft:
#   - OrbitAuto gives up at once, with one log line, when the follow camera's hook is not installed
#     (pc_controls=0 or not the 1.09 game) instead of polling every frame for the whole run; the
#     knob's speed is logged with one decimal (7.5 was printed as +8).
#   - A periodic counter for the orbit (rule: a feature has one): every 300 camera updates while an
#     orbit turns (F4 or BB_CAMERA_ORBIT), "Camera: orbit turning, N degrees in T s so far" (game
#     thread, inside OrbitTurn: zero cost while no orbit runs). The slot jobs' log now proves the turn.
#   - The draws-onto-the-picture count also counts the scene's own late passes onto the tonemapped
#     picture (any draw onto that target after the first one in World), so it is not zero in a
#     normal frame: comment and README now say so and that only a rise against plain standing means
#     a HUD piece drawn before the first movie draw.
#   - README: the BB_CAMERA_ORBIT row says values outside -45..45 are clamped, names clean shot by
#     its key (BB_CLEAN_SHOT is a test-tool knob, not in the feature branch) and the F4 bullet names
#     the periodic line.
#
# Finding (code reading of the tree at 22:35 plus the 20:48 slot pictures): the clean shot already
# leaves out every game HUD draw it can see. In a frame that draws the world, from the game's first
# menu-movie (Scaleform) draw onto the finished picture (or its clip mask) to the display pass, every
# draw onto that picture or its clip masks is left out whatever shader draws it: bars, item slots,
# numbers, subtitles, prompts, the lock-on marker, enemy gauges and area names are layers of the same
# movie viewport (ui_composition.h, widescreen.cpp), so they fall under the rule. The engine's ImGui
# overlay draws only what takes input (menu, text prompt, co-op panel) while clean shot is on
# (BbOverlay::Visible/Render); the presenter draws nothing else over the frame. What can still survive:
#   (a) a draw onto the finished picture BEFORE the first movie draw of the frame (README already says
#       it stays). Nobody knows whether any HUD piece is drawn that way: no capture of a lock-on, a
#       prompt or an area name exists. This patch counts such draws (probe numbers below).
#   (b) the co-op panel, closed by clean shot, did not come back when clean shot ended: fixed (F3 or
#       L3 + D-pad Left off opens it again when clean shot had closed it).
# Stages 2-4 checked against the code for what stops a clip: nobody can start the orbit without a key
# (the lead's slot and 4K runs cannot press F-keys, so stages 2-4 were never checked in the build tree).
# New knob BB_CAMERA_ORBIT=<degrees a second> starts the orbit by itself once a run, so the lead can make
# the turntable clip and the slot runs can prove stage 2 without hands.
#
# Changes, file by file:
#   vk_rasterizer.cpp: CleanShotCounts / CleanShotTally next to the clean shot rule; CleanShotEarly
#     counts the draws left out and the draws onto the finished picture before the UI; the display
#     pass tallies the frame's phase. Log, every 300 frames while clean shot is on:
#     "Camera: clean shot, last 300 frames: A with the UI left out (D draws), B with the world and no
#      UI found, C without the world; E draws onto the finished picture before the UI".
#   bbport_overlay.cpp: ToggleCleanShot reopens the co-op panel it closed.
#   camera_orbit.h: AutoSpeedFrom (BB_CAMERA_ORBIT's parse, pure) and <cstdlib>.
#   mouse_camera.cpp: BB_CAMERA_ORBIT (OrbitAuto, called first thing in OrbitFrame), include of
#     bbport_overlay.h for MenuOpen.
#   test_camera_orbit.cpp: AutoSpeedFromEnv cases.
#   README.md: the F3 bullet (co-op panel, the log line), the camera table's sentence and a
#     BB_CAMERA_ORBIT row, the F4 bullet points at it.
#
# Cost. Off (no BB_CLEAN_SHOT, no F3; no BB_CAMERA_ORBIT): per display pass one more test of the plain
# bool clean_shot_frame (it is already tested per draw); per frame in OrbitFrame one test of a plain
# bool (g_auto_orbit_pending is false after the first frame when the knob is unset). No GPU work, no
# memory. Clean shot on: per draw it already inspects, one u64 copy, two compares and two adds; per
# frame one increment, a printf every 300 frames. BB_CAMERA_ORBIT set: until the orbit starts, per frame
# one relaxed atomic load, a steady clock read and MenuOpen's atomic load; after it, as with F4.
#
# Use: python -I -X utf8 r102b_camera-clean-hud.py check | apply | revert
# Root: R102B_ROOT, else <tree>. Line ends kept per file. apply backs the originals up in
# r102b_camera-clean-hud_backup next to this script. Edits are (anchor, before, after) inserts or
# (old, new) replacements; each anchor / old text must be found exactly once, and the inserted or new
# text found once after apply; revert takes out exactly what apply put in.
import os, sys

ROOT = os.environ.get("R102B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r102b_camera-clean-hud_backup")
V = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer.cpp"
O = "engine/gpu/shim/bbport_overlay.cpp"
H = "engine/gpu/shim/input/camera_orbit.h"
M = "engine/gpu/shim/input/mouse_camera.cpp"
T = "engine/tests/test_camera_orbit.cpp"
R = "README.md"
FILES = (V, O, H, M, T, R)

TAG = "bbport (r102b_camera-clean-hud)"

# ---- vk_rasterizer.cpp -------------------------------------------------------------------------
V_COUNTS = """\
// """ + TAG + """: what clean shot did, one log line every 300 frames while it is on
// (CleanShotTally at the display pass): frames whose UI it found and left out, frames that drew the
// world but in which it found no UI (no HUD on screen then, or a HUD drawn without a menu-movie draw:
// that one stays), frames without the world (loading screens keep their UI), the draws left out, and
// the draws onto the finished picture before the UI (in World, onto the target an earlier frame-size
// RGBA8 draw of the same frame wrote). That last count includes the scene's own passes onto the
// tonemapped picture, so it is not 0 in a normal frame; a rise per frame in some state (a prompt, a
// lock-on) over plain standing is a HUD piece drawn before the first movie draw, which stays in the
// picture. Counted only while clean shot is on; recording is single-threaded (as clean_shot_state).
struct CleanShotCounts {
    u32 frames[3] = {}; // by UiComposition::CleanShotPhase at the display pass
    u32 left_out = 0, onto_frame = 0;
};
static_assert(static_cast<u32>(UiComposition::CleanShotPhase::NoWorld) == 0 &&
              static_cast<u32>(UiComposition::CleanShotPhase::World) == 1 &&
              static_cast<u32>(UiComposition::CleanShotPhase::Ui) == 2);
static CleanShotCounts clean_shot_counts;
static void CleanShotTally(UiComposition::CleanShotPhase phase) {
    CleanShotCounts& c = clean_shot_counts;
    ++c.frames[static_cast<u32>(phase)];
    const u32 total = c.frames[0] + c.frames[1] + c.frames[2];
    if (total < 300) {
        return;
    }
    std::printf("Camera: clean shot, last %u frames: %u with the UI left out (%u draws), %u with the "
                "world and no UI found, %u without the world; %u draws onto the finished picture "
                "before the UI\\n",
                total, c.frames[2], c.left_out, c.frames[1], c.frames[0], c.onto_frame);
    c = {};
}
"""
V_SKIP_OLD = "    return UiComposition::CleanShotSkip(clean_shot_state, draw);\n"
V_SKIP_NEW = """\
    // """ + TAG + """: counted for CleanShotTally
    const u64 ldr_before = clean_shot_state.ldr;
    const bool skip = UiComposition::CleanShotSkip(clean_shot_state, draw);
    clean_shot_counts.left_out += skip ? 1u : 0u;
    if (!skip && ldr_before != 0 && draw.color == ldr_before &&
        clean_shot_state.phase == UiComposition::CleanShotPhase::World) {
        ++clean_shot_counts.onto_frame;
    }
    return skip;
"""
V_TALLY = """\
        if (clean_shot_frame) {
            CleanShotTally(clean_shot_state.phase); // """ + TAG + """
        }
"""

# ---- bbport_overlay.cpp ------------------------------------------------------------------------
O_OLD = """\
    if (on) {
        coop_open = false;
    }
    std::printf("Camera: clean shot %s (%s)\\n", on ? "on" : "off", key);
"""
O_NEW = """\
    // """ + TAG + """: the co-op panel it closed opens again when this key ends it
    // (not when the settings menu ends it).
    static bool coop_closed = false;
    if (on) {
        coop_closed = coop_open.exchange(false);
    } else if (coop_closed) {
        coop_closed = false;
        coop_open = true;
    }
    std::printf("Camera: clean shot %s (%s)\\n", on ? "on" : "off", key);
"""

# ---- camera_orbit.h ----------------------------------------------------------------------------
H_INCLUDE = "#include <cstdlib> // " + TAG + ": AutoSpeedFrom\n"
H_PARSE = """\
// """ + TAG + """: BB_CAMERA_ORBIT's speed in degrees a second: a number, clamped to
// +-kSpeedMost (below 0 the other way round). 0 (off) for none, an empty value, text after the
// number, or a value that is not a finite number.
inline float AutoSpeedFrom(const char* value) {
    if (!value || !*value) return 0.0f;
    char* end = nullptr;
    const float v = std::strtof(value, &end);
    if (end == value || *end || !std::isfinite(v)) return 0.0f;
    return std::clamp(v, -kSpeedMost, kSpeedMost);
}

"""

# ---- mouse_camera.cpp --------------------------------------------------------------------------
M_INCLUDE = '#include "../bbport_overlay.h" // ' + TAG + ': MenuOpen, for BB_CAMERA_ORBIT\n'
M_AUTO = """\
// """ + TAG + """: BB_CAMERA_ORBIT=<degrees a second> starts the orbit by itself once a run,
// as F4 does, when the follow camera has run for 2 s (no gap over 0.25 s, no loading screen up) with
// the settings menu closed; at that speed (CameraOrbit::AutoSpeedFrom). Everything after the start is
// F4's orbit (the keys change it; F4, the menu, a loading screen or lock-on end it; it does not start
// again). For clips and test runs without a key. Unset (or 0, or not a number), or the follow
// camera's hook not installed: after the first frame OrbitFrame's one more cost is the test of a
// plain bool. The frame pacer's thread only.
namespace {
const char* FollowMissing(); // below, with the camera paths
bool g_auto_orbit_pending = true;
void OrbitAuto() {
    static const float speed = CameraOrbit::AutoSpeedFrom(std::getenv("BB_CAMERA_ORBIT"));
    if (speed == 0.0f) {
        g_auto_orbit_pending = false;
        return;
    }
    if (!g_installed) { // Install ran at the image's install, before the game's first frame
        g_auto_orbit_pending = false;
        std::printf("Camera: BB_CAMERA_ORBIT=%+.1f: unavailable, the follow camera's hook is off (PC controls "
                    "off, or not the 1.09 game)\\n",
                    double(speed));
        return;
    }
    static bool said = false;
    if (!said) {
        said = true;
        std::printf("Camera: BB_CAMERA_ORBIT=%+.1f: the orbit starts by itself once a run, when the follow "
                    "camera has run for 2 s with the settings menu closed\\n",
                    double(speed));
    }
    static Clock::time_point since{};
    const Clock::time_point now = Clock::now();
    if (FollowMissing() || BbOverlay::MenuOpen()) {
        since = {};
        return;
    }
    if (since == Clock::time_point{}) since = now;
    if (now - since < std::chrono::seconds(2)) return;
    g_auto_orbit_pending = false;
    std::scoped_lock lock(g_orbit_lock);
    OrbitCommand& c = g_orbit;
    if (OrbitOn(c)) return; // F4 or F6 came first
    // As OrbitToggle's start, at the knob's speed.
    c.want = true;
    c.serial = c.serial + 1 ? c.serial + 1 : 1;
    c.speed = speed;
    c.height = 0;
    c.heights = {-CameraOrbit::kHeightStepsMost, CameraOrbit::kHeightStepsMost};
    c.radius = 1.0f;
    c.path = false;
    c.generation = BbEngine::Loading::Generation();
    g_orbit_generation = c.generation;
    g_orbit_drive = true;
    g_orbit_live = true;
    std::printf("Camera: orbit on (BB_CAMERA_ORBIT): %+.1f degrees a second, radius x%.1f\\n", double(c.speed),
                double(c.radius));
}
}

"""
M_CALL = "    if (g_auto_orbit_pending) OrbitAuto(); // " + TAG + ": BB_CAMERA_ORBIT\n"
M_TURNED_ANCHOR = ("    g_run_turned += std::fabs(g_run.rate.value) * std::clamp(dt, 0.0f, "
                   "CameraOrbit::kLongestStep);\n")
M_TURNED = """\
    // """ + TAG + """: the orbit's periodic line, every 300 camera updates while one turns
    // (F4 or BB_CAMERA_ORBIT; the game's thread, so no orbit, no cost).
    static unsigned turning_updates = 0;
    if (++turning_updates % 300 == 0) {
        std::printf("Camera: orbit turning, %.0f degrees in %.1f s so far\\n",
                    double(g_run_turned / CameraOrbit::kRadiansPerDegree),
                    double(std::chrono::duration<float>(now - g_run_began).count()));
    }
"""

# ---- test_camera_orbit.cpp ---------------------------------------------------------------------
T_FUNC = """\

// """ + TAG + """: BB_CAMERA_ORBIT's speed.
void AutoSpeedFromEnv() {
    assert(AutoSpeedFrom(nullptr) == 0.0f && AutoSpeedFrom("") == 0.0f);
    assert(AutoSpeedFrom("12") == 12.0f && AutoSpeedFrom("-20") == -20.0f && AutoSpeedFrom("7.5") == 7.5f);
    assert(AutoSpeedFrom("90") == kSpeedMost && AutoSpeedFrom("-90") == -kSpeedMost);
    assert(AutoSpeedFrom("0") == 0.0f && AutoSpeedFrom("x") == 0.0f && AutoSpeedFrom("12x") == 0.0f);
    assert(AutoSpeedFrom("nan") == 0.0f && AutoSpeedFrom("inf") == 0.0f);
}
"""
T_CALL = "    AutoSpeedFromEnv(); // " + TAG + "\n"

# ---- README.md ---------------------------------------------------------------------------------
R_F3_ANCHOR = ("draws into other images are kept. It hides them until pressed again or the settings menu "
               "opens.")
R_F3_AFTER = (" Turning it on closes the co-op menu (F2); when this key turns it off again, the co-op menu "
              "opens again if clean shot closed it. While it is on, the log has every 300 frames `Camera: "
              "clean shot, last 300 frames: ...`: frames whose UI it found and left out, frames that drew "
              "the world with no UI found, frames without the world, the draws left out, and the draws onto "
              "the finished picture before the UI (the scene's own late passes count there too, so it is "
              "not 0; more of them per frame in some state than when standing is a HUD piece drawn before "
              "the first movie draw, which stays).")
R_F4_OLD = ("when the follow camera has not run in the last 0.25 s. Needs PC controls on. Not saved: off "
            "at every start.\n")
R_F4_NEW = ("when the follow camera has not run in the last 0.25 s. Needs PC controls on. Not saved: off "
            "at every start. While it turns, the log has every 300 camera updates `Camera: orbit turning, "
            "N degrees in T s so far`. `BB_CAMERA_ORBIT` (below) starts it without a key.\n")
R_SENT_OLD = ("Camera mode reads two environment variables, each once, when its key is first used (no ini "
              "key); `Camera: path on` shows the seconds a key, `Camera: freeze held` the longest freeze:")
R_SENT_NEW = ("Camera mode reads three environment variables, each once (no ini key): `BB_CAMERA_ORBIT` at "
              "the first frame, the other two when their key is first used; `Camera: path on` shows the "
              "seconds a key, `Camera: freeze held` the longest freeze:")
R_ROW_ANCHOR_PREFIX = "| `BB_CAMERA_FREEZE_S` |"
R_ROW = ("| `BB_CAMERA_ORBIT` | Starts the orbit (F4) by itself once a run, at this speed in degrees a "
         "second (clamped to -45 to 45, below 0 the other way round), when the follow camera has run for 2 s "
         "with no loading screen up and the settings menu closed; from then on it is F4's orbit (the keys "
         "change it; F4, the settings menu, a loading screen or lock-on end it, and it does not start "
         "again). For clips and test runs without a key press; with clean shot on (F3) the picture has no "
         "HUD. The log says `Camera: BB_CAMERA_ORBIT=...` once (with `unavailable` when PC controls are "
         "off), then `Camera: orbit on (BB_CAMERA_ORBIT)`. Unset, `0` or not a number: off | unset |\n")


def readme_row(text):
    lines = [l for l in text.split("\n") if l.startswith(R_ROW_ANCHOR_PREFIX)]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_CAMERA_FREEZE_S row is there %d times, wanted 1" % len(lines))
    return ("ins", lines[0] + "\n", "", R_ROW)


# Each edit: ("ins", anchor, before, after) or ("rep", old, new).
def edits_for(path, text):
    if path == V:
        return [
            ("ins", "static const std::atomic<bool>& clean_shot = BbSettings::Get().clean_shot; // read once a frame\n",
             "", V_COUNTS),
            ("rep", V_SKIP_OLD, V_SKIP_NEW),
            ("ins", "        clean_shot_frame = clean_shot.load(std::memory_order_relaxed);\n", V_TALLY, ""),
        ]
    if path == O:
        return [("rep", O_OLD, O_NEW)]
    if path == H:
        return [
            ("ins", "#include <cmath>\n", "", H_INCLUDE),
            ("ins", "// After an early end (the stick or the mouse, or the game took the camera) the yaw and the pitch\n",
             H_PARSE, ""),
        ]
    if path == M:
        return [
            ("ins", '#include "../engine/online_fixes.h"\n', "", M_INCLUDE),
            ("ins", "void OrbitFrame() {\n", M_AUTO, M_CALL),
            ("ins", M_TURNED_ANCHOR, "", M_TURNED),
        ]
    if path == T:
        return [
            ("ins", "}\n\nint main() {\n", T_FUNC, ""),
            ("ins", '    std::puts("camera orbit test passed");\n', T_CALL, ""),
        ]
    if path == R:
        return [
            ("ins", R_F3_ANCHOR, "", R_F3_AFTER),
            ("rep", R_F4_OLD, R_F4_NEW),
            ("rep", R_SENT_OLD, R_SENT_NEW),
            readme_row(text),
        ]
    raise SystemExit("no edits for " + path)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edit_state(cur, ed, path):
    """'applied', 'clean' or refuse. An insert's texts and a replacement's new text are found by themselves."""
    if ed[0] == "ins":
        _, anchor, before, after = ed
        parts = [t for t in (before, after) if t]
        na, counts = cur.count(anchor), [cur.count(t) for t in parts]
        if na == 1 and all(k == 1 for k in counts):
            return "applied"
        if na == 1 and all(k == 0 for k in counts):
            return "clean"
        raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                         % (path, na, counts, anchor[:70]))
    _, old, new = ed
    no, nn = cur.count(old), cur.count(new)
    if nn == 1 and (old not in new and no == 0 or old in new and no == 1):
        return "applied"
    if no == 1 and nn == 0:
        return "clean"
    raise SystemExit("REFUSED %s: old text found %d times, new text %d times: %r" % (path, no, nn, old[:70]))


def state_of(cur, eds, path):
    states = [edit_state(cur, ed, path) for ed in eds]
    if all(s == "applied" for s in states):
        return "applied"
    if all(s == "clean" for s in states):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, states.count("applied"), len(eds)))


def apply_eds(cur, eds):
    for ed in eds:
        if ed[0] == "ins":
            _, anchor, before, after = ed
            cur = cur.replace(anchor, before + anchor + after, 1)
        else:
            cur = cur.replace(ed[1], ed[2], 1)
    return cur


def revert_eds(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "ins":
            for part in (ed[3], ed[2]):
                if part:
                    cur = cur.replace(part, "", 1)
        else:
            cur = cur.replace(ed[2], ed[1], 1)
    return cur


def text_checks(texts):
    v = texts[V]
    for want in ("static void CleanShotTally(UiComposition::CleanShotPhase phase) {",
                 "CleanShotTally(clean_shot_state.phase);", "++clean_shot_counts.onto_frame;",
                 "const bool skip = UiComposition::CleanShotSkip(clean_shot_state, draw);"):
        if v.count(want) != 1:
            raise SystemExit("text check: %s holds %r %d times" % (V, want, v.count(want)))
    # the counts are defined before CleanShotEarly uses them, the tally before the display pass calls it
    if not (0 <= v.find("static CleanShotCounts clean_shot_counts;") < v.find("bool Rasterizer::CleanShotEarly(")
            < v.find("CleanShotTally(clean_shot_state.phase);")):
        raise SystemExit("text check: clean shot counts out of order in " + V)
    # the tally runs before the latch resets clean_shot_state
    a, b = v.find("CleanShotTally(clean_shot_state.phase);"), v.find("        clean_shot_state = {};\n")
    if not (0 <= a < b):
        raise SystemExit("text check: the tally is not before clean_shot_state = {}")
    m = texts[M]
    if not (0 <= m.find("const char* FollowMissing(); // below") < m.find("void OrbitFrame() {")
            < m.find("const char* FollowMissing() {")):
        raise SystemExit("text check: FollowMissing declaration/definition order in " + M)
    if m.count("g_auto_orbit_pending") != 5:
        raise SystemExit("text check: g_auto_orbit_pending used %d times" % m.count("g_auto_orbit_pending"))
    # OrbitAuto reads g_installed (defined earlier in the same unnamed namespace) and the periodic line
    # sits in OrbitTurn after the turned angle and before OrbitTurn's end
    if not (0 <= m.find("bool g_installed = false;") < m.find("    if (!g_installed) { // Install ran")):
        raise SystemExit("text check: g_installed before OrbitAuto")
    t1, t2 = m.find("bool OrbitTurn(std::uint8_t* camera"), m.find("static unsigned turning_updates = 0;")
    if not (0 <= t1 < m.find(M_TURNED_ANCHOR) < t2 < m.find("void HoldAutoRotation(bool hold) {")):
        raise SystemExit("text check: the orbit's periodic line is not inside OrbitTurn")
    # the knob's start sets the same fields as OrbitToggle's start
    for field in ("c.want = true;", "c.height = 0;", "c.radius = 1.0f;", "c.path = false;",
                  "c.heights = {-CameraOrbit::kHeightStepsMost, CameraOrbit::kHeightStepsMost};",
                  "g_orbit_generation = c.generation;", "g_orbit_drive = true;", "g_orbit_live = true;"):
        if m.count(field) < 2:
            raise SystemExit("text check: %r not in both starts" % field)
    r = texts[R]
    row = [l for l in r.split("\n") if l.startswith("| `BB_CAMERA_ORBIT` |")]
    if len(row) != 1 or "-45 to 45" not in row[0] or "2 s" not in row[0]:
        raise SystemExit("text check: README row")
    if "kSpeedMost = 45.0f" not in texts[H]:
        raise SystemExit("text check: kSpeedMost is not 45")
    if "std::chrono::seconds(2)" not in m:
        raise SystemExit("text check: the 2 s wait")
    if "if (total < 300)" not in v or "last 300 frames" not in r:
        raise SystemExit("text check: 300 frames")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R102B_ROOT)" % ROOT)
    plan = []
    for path in FILES:
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_eds(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            if revert_eds(cur, eds) != plan_cur[path]:
                raise SystemExit("%s: revert of the result would not give the file back" % path)
            out[path] = cur
        return out

    plan_cur = {p[0]: p[4] for p in plan}
    if cmd == "check":
        if state == "applied":
            text_checks(plan_cur)
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
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__") + ".before_apply"), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r102btmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_eds(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    os.makedirs(BACKUP, exist_ok=True)
    for path, eds, raw, eol, cur, _ in plan:
        open(os.path.join(BACKUP, path.replace("/", "__") + ".before_revert"), "wb").write(raw)
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r102btmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
