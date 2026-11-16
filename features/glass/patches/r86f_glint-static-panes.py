# r86f_glint-static-panes: FEATURE fix (glass, r83 chain; on top of r86e, r86d, r86c, r86b, r83c, r83b, r83).
#
# Why: build 35 (b35): the glass glint never draws at the Hunter's Dream house. The candidate bottle pairs
# (e94b5b06:5e4596f4; 8747a367:e96447c3 and 44072322:cfa96da9) log, in the r83b stage line,
# "static N | skin 0 pal 0 const 0 entry 0 note 0" and "vs bufs 1: 64/16" (or 16/16): their vertex
# shaders have NO 864-byte camera constants buffer (the dome pair has one: "vs bufs 5: 416/16 96/16 864/16
# 64/16 128/16", and it is the only pair that ever got an entry). RtShadow::PrepareDraw returns at
# "if (!draw.constants) { ++stats.no_camera; return 0; }", so a static pane draw is hooked (EffectsCaptureDraw
# sets Draw::glass) but never becomes an entry, never a pane record: the glint skips every draw "no pane".
# The captured positions of a forward draw are clip space of the frame's camera; what they need to become
# world points is that camera's projection (constants word 52) and view-to-world rows (word 180), which the
# G-buffer draws of the same frame hold in their 864-byte buffer.
#
# Fix: with BB_RT_GLASS on, PrepareDraw keeps a majority vote over the camera constants pointers of the
# frame's camera pass (G-buffer) draws (Boyer-Moore: one pointer, one count; no allocation), and a pane
# draw that has no constants of its own (EffectsCaptureDraw, glass block) takes the winner (RtShadow::
# GlassCamera). A pane with its own constants (the dome) keeps them. From there the draw is any static
# pane draw: key, entry, capture with its own transform and buffers, TLAS record under RtGlassMask, carry.
# If the frame has no camera pass draw yet, nothing is given and the draw is left out as before.
# Live test knob BB_GLASS_STATIC_PANES (default on; 0 = a pane without constants is left out as in b35;
# live only in a build with the test tools' bbport_live_knobs.h, else read as always on): one game can
# run the glint with and without the fix.
#
# Off: the vote and the lookup run only where RtGlassOn() (BB_RT_GLASS, a static bool) holds, and the
# lookup only for a pane draw without constants; knob off = one test of a static bool per camera pass
# draw, the same test the glass block already makes. Frame end: a branch on a count.
# Log (BB_RT_GLASS on): once "Ray tracing glass (r86f): ..." at the first pane draw that took the camera;
# every 600 frames of pane draws, with r83's line, "Ray tracing glass (r86f): ... given N, left without M".
# Files: renderer_vulkan/vk_rt_shadow.h, vk_rt_shadow.cpp, vk_rasterizer_effects.cpp, README.md (a row).
# Use: python -I -X utf8 r86f_glint-static-panes.py check | apply | revert
# Root: R86F_ROOT else <tree>. CRLF kept. Backups in r86f_backup next to this script.
import os, sys, io

ROOT = os.environ.get("R86F_ROOT") or "<tree>"
BK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r86f_backup")
V = "engine/gpu/shadps4/video_core/renderer_vulkan/"
E = {
 V + "vk_rt_shadow.h": [
  ("        return {glass_instances, glass_frame == frame, glass_view};\n    }\n",
   "        return {glass_instances, glass_frame == frame, glass_view};\n    }\n"
   "    // bbport (r86f_glass-static-panes): BB_RT_GLASS on: the camera constants (the 864-byte buffer's\n"
   "    // words, as a G-buffer draw holds them) a pane draw without constants of its own takes: the\n"
   "    // frame's main camera (the pointer most of its camera pass draws held). nullptr: none seen yet\n"
   "    // this frame, or BB_GLASS_STATIC_PANES 0.\n"
   "    [[nodiscard]] const float* GlassCamera();\n"),
  ("    void NoteGlassDraw(const Entry& entry);\n",
   "    void NoteGlassDraw(const Entry& entry);\n"
   "    // bbport (r86f_glass-static-panes): GlassCamera's vote (Boyer-Moore over the camera pass draws'\n"
   "    // constants pointers, cleared at the frame's end) and its counts for the log\n"
   "    const float* r86f_camera = nullptr;\n"
   "    u32 r86f_votes = 0;\n"
   "    u64 r86f_given = 0, r86f_none = 0;\n"
   "    bool r86f_said = false;\n"
   "    void GlassCameraVote(const float* constants);\n"),
 ],
 V + "vk_rt_shadow.cpp": [
  ('#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)\n',
   '#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)\n'
   "// bbport (r86f_glass-static-panes): the test tools' live knobs (branch dev/test-tools) when the build has\n"
   "// them: BB_GLASS_STATIC_PANES is then asked again at every use; without them it is always on.\n"
   '#if __has_include("bbport_live_knobs.h")\n'
   '#include "bbport_live_knobs.h"\n'
   "#define BB_GLASS_STATIC_LIVE 1\n"
   "#else\n"
   "#define BB_GLASS_STATIC_LIVE 0\n"
   "#endif\n"),
  ("    if (!draw.shadow_pass && !draw.camera_pass) {\n        return 0;\n    }\n"
   "    r19_stats.calls += r19 ? 1u : 0u;\n",
   "    if (!draw.shadow_pass && !draw.camera_pass) {\n        return 0;\n    }\n"
   "    r19_stats.calls += r19 ? 1u : 0u;\n"
   "    // bbport (r86f_glass-static-panes): the vote for GlassCamera (BB_RT_GLASS on only)\n"
   "    if (draw.camera_pass && !draw.glass && draw.constants && RtGlassOn()) {\n"
   "        GlassCameraVote(draw.constants);\n"
   "    }\n"),
  ("    if (say != 0) {\n        RtGlassWindowNext(glass_stats, frame);\n    }\n}\n",
   "    // bbport (r86f_glass-static-panes): with r83's window line, what the static panes got\n"
   "    if (say == 2 && (r86f_given != 0 || r86f_none != 0)) {\n"
   '        std::printf("Ray tracing glass (r86f): pane draws without camera constants of their own (static '
   'panes): the frame camera was given to %llu, none was known for %llu (all since the start)\\n",\n'
   "                    static_cast<unsigned long long>(r86f_given),\n"
   "                    static_cast<unsigned long long>(r86f_none));\n"
   "    }\n"
   "    if (say != 0) {\n        RtGlassWindowNext(glass_stats, frame);\n    }\n}\n"
   "\n"
   "// bbport (r86f_glass-static-panes): one vote of a camera pass draw's constants (Boyer-Moore: the\n"
   "// pointer most draws hold is left when it has more than half; no allocation, no search).\n"
   "void RtShadow::GlassCameraVote(const float* constants) {\n"
   "    if (r86f_votes == 0) {\n"
   "        r86f_camera = constants;\n"
   "        r86f_votes = 1;\n"
   "    } else if (r86f_camera == constants) {\n"
   "        ++r86f_votes;\n"
   "    } else {\n"
   "        --r86f_votes;\n"
   "    }\n"
   "}\n"
   "\n"
   "// bbport (r86f_glass-static-panes): the constants a pane draw without its own takes (see the header).\n"
   "const float* RtShadow::GlassCamera() {\n"
   "#if BB_GLASS_STATIC_LIVE\n"
   "    // 1 unless the text starts with 0 (a test knob: flips the fix in one running game)\n"
   "    static BbLiveKnobs::Knob<bool> on{\"BB_GLASS_STATIC_PANES\",\n"
   "                                      [](const char* text) { return text == nullptr || text[0] != '0'; }};\n"
   "    if (!on.Get()) {\n"
   "        return nullptr;\n"
   "    }\n"
   "#endif\n"
   "    if (r86f_camera == nullptr) {\n"
   "        ++r86f_none;\n"
   "        return nullptr;\n"
   "    }\n"
   "    ++r86f_given;\n"
   "    if (!r86f_said) {\n"
   "        r86f_said = true;\n"
   '        std::printf("Ray tracing glass (r86f): a pane draw without camera constants of its own (a '
   'static pane: the bottles, jars and windows) took the constants of the frame\'s main camera, at '
   'frame %llu (BB_GLASS_STATIC_PANES 0 leaves such panes out, as before)\\n",\n'
   "                    static_cast<unsigned long long>(frame));\n"
   "    }\n"
   "    return r86f_camera;\n"
   "}\n"),
  ("    frame_cameras.clear();\n    occurrences.clear();\n",
   "    frame_cameras.clear();\n"
   "    // bbport (r86f_glass-static-panes): the vote ends with the frame, its candidate too (a vote\n"
   "    // that fell to 0 keeps its last pointer, which must not reach the next frame's panes)\n"
   "    r86f_camera = nullptr;\n"
   "    r86f_votes = 0;\n"
   "    occurrences.clear();\n"),
 ],
 V + "vk_rasterizer_effects.cpp": [
  ("            glint_pending = glass_glint ? pipeline : nullptr; // bbport (r86b_glass-visible)\n",
   "            // bbport (r86f_glass-static-panes): a static pane (the bottles, jars, windows: a vertex shader\n"
   "            // without the 864-byte camera constants) takes the frame's main camera's constants, so that\n"
   "            // PrepareDraw gives it an entry; a pane with constants of its own keeps them\n"
   "            if (!draw.constants) {\n"
   "                draw.constants = rt_shadow->GlassCamera();\n"
   "            }\n"
   "            glint_pending = glass_glint ? pipeline : nullptr; // bbport (r86b_glass-visible)\n"),
 ],
 "README.md": [
  ("| `BB_GLASS_GLINT_SHARP` | Only with `BB_GLASS_GLINT` on:",
   "| `BB_GLASS_STATIC_PANES` | Only with `BB_RT_GLASS` on (r86f). Glass that is not a window pane with its own camera buffer (the Hunter's Dream house bottles and jars: their vertex shaders have no 864-byte camera constants, so the ray traced scene never got them and the glint saw no pane) takes the camera constants of the frame's main camera (the one most of the frame's G-buffer draws use). On by default with `BB_RT_GLASS`; `0` leaves such panes out as before. Only a test build can flip it while the game runs (the test tools' live knobs file); otherwise it is on. Log: `Ray tracing glass (r86f):` lines. |\n"
   "| `BB_GLASS_GLINT_SHARP` | Only with `BB_GLASS_GLINT` on:"),
 ],
}

def rd(p): return io.open(p, encoding="utf-8", newline="").read()
def wr(p, s): io.open(p, "w", encoding="utf-8", newline="").write(s)

def plan():
    out, state = {}, []
    for f, eds in E.items():
        s = rd(os.path.join(ROOT, f)); crlf = "\r\n" in s; t = s.replace("\r\n", "\n")
        for a, b in eds:
            if b in t and t.count(b) == 1:
                state.append("done"); continue
            if t.count(a) != 1:
                print("REFUSED", f, "anchor count", t.count(a), repr(a[:70])); sys.exit(1)
            t = t.replace(a, b); state.append("todo")
        out[f] = (s, t.replace("\n", "\r\n") if crlf else t)
    if "done" in state and "todo" in state:
        print("REFUSED: mixed state"); sys.exit(1)
    return out, state

mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode == "revert":
    for f in E:
        b = os.path.join(BK, f.replace("/", "__"))
        if os.path.exists(b):
            wr(os.path.join(ROOT, f), rd(b)); os.remove(b); print("restored", f)
    sys.exit(0)
if mode not in ("check", "apply"):
    print("usage: check | apply | revert"); sys.exit(2)
out, state = plan()
if mode == "check":
    print("applied" if "todo" not in state else "not applied; would apply (%d edits)" % len(state)); sys.exit(0)
os.makedirs(BK, exist_ok=True)
for f, (s, t) in out.items():
    if s != t:
        b = os.path.join(BK, f.replace("/", "__"))
        if not os.path.exists(b): wr(b, s)
        wr(os.path.join(ROOT, f), t)
print("applied")
