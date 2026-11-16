# r86h_glint-camera: FEATURE fix (glass, r83 chain; on top of r86g, r86f, r86e, r86d, r86c, r86b, r83c, r83b, r83).
#
# Why (found by reading the shader cache, <dev>/user/cache/CUSA03173, spirv-dis on the vertex shaders
# of the b43 find lines): the draws BB_RT_GLASS=auto took at the Hunter's Dream house as "bottle-sized glass"
# are not bottles. e94b5b06 (the likeliest, 2.3 draws a frame), 9957251, 17e76c08, 44072322, 24042a9b,
# 81d336ce, a334a845, bb4d5f8c, a400228b, 6dfebc16: every one of them stores the constant 0.0 as gl_Position.z
# and 1.0 as w (screen space: e94b5b06 multiplies a 2D attribute (x, y, 0, 1) by one 4x4 matrix of 64 bytes).
# They are the game's HUD/UI draws, made after the display pass (the frame end, vk_rasterizer.cpp: "the pass
# copying a finished frame to a display buffer"), where no camera pass has voted (r86f_camera is cleared at the
# frame end). That is why every verdict was "no camera" and "p12-15 0 0 0 0": there IS no 3D camera for them,
# and the fix of the task text (give them the frame's camera and unproject their vertices) would put 2D quads
# into the ray traced scene. The only other pairs of the 30 listed that have a computed clip z are b28f5a56
# (particles, discard) and 1ea84d9a (12 indices). So at the dream house nothing drawn alpha blended WITH depth
# write inside the scene's frame is glass; the bottles are drawn some other way.
#
# What this does:
#  1. AUTO takes only draws of the scene's 3D frame: a forward draw counts only while Rasterizer::scene_started
#     (the first G-buffer pass of the frame up to the display pass, the same flag the upscaler's raster scaling
#     uses), reads a texture, does not discard, and has BB_GLASS_AUTO_MIN (default 60) .. BB_GLASS_AUTO_INDICES
#     indices (the jobs pass 2016; the default of 12000 is kept so that older tests and runs read the same).
#     Draws left out are counted in the find table as verdicts "outside frame" and "shape". Listed pairs
#     (BB_RT_GLASS=1 or a pair list) are untouched. r86f's frame camera vote is unchanged: a 3D pane draw
#     inside the frame that has no constants of its own still takes the voted camera.
#  2. FIND (BB_GLASS_FIND=1, log only) says what the glass search needs next: per pair flags "in frame" /
#     "after frame" (Rasterizer::scene_started at the draw) and "camera voted" (RtShadow::GlassCameraKnown);
#     the report ranks pairs drawn in the frame first (glass-like first among them), shows 14 pairs instead of
#     10, and adds one line "Ray tracing glass find (r86h)": pairs in the frame, glass-like ones, pairs the new
#     auto rule takes. In-frame pairs without depth write (translucent glass does not write depth) now show
#     up at the top; they are the next candidates (taking them needs a capture variant per pair: not done
#     here, the lead decides after reading the lines). The vote also runs with BB_GLASS_FIND alone.
# Off: BB_RT_GLASS unset/0/list: nothing new runs (glass_ps is null, the new tests sit behind RtGlassAuto()).
# BB_GLASS_FIND unset: one test of a static bool per forward draw as before. Nothing is allocated, no lock taken.
# Files: renderer_vulkan/rt_glass.h, rt_glass_find.h, vk_rt_shadow.h, vk_rt_shadow.cpp, vk_rasterizer.cpp,
# vk_rasterizer_effects.cpp, README.md (1 row), tests/test_rt_glass.cpp. No shader touched.
# Use: python -I -X utf8 r86h_glint-camera.py check | apply | revert
# Root: R86H_ROOT else <tree>. Line ends kept per file. Backups in r86h_backup next to this script.
import os, sys, io

ROOT = os.environ.get("R86H_ROOT") or "<tree>"
BK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r86h_backup")
V = "engine/gpu/shadps4/video_core/renderer_vulkan/"

NEW = {}

E = {
 V + "rt_glass.h": [
  (r'''inline std::uint32_t RtGlassAutoIndices() {
    static const std::uint32_t most = RtGlassParseAutoIndices(std::getenv("BB_GLASS_AUTO_INDICES"));
    return most;
}
''',
   r'''inline std::uint32_t RtGlassAutoIndices() {
    static const std::uint32_t most = RtGlassParseAutoIndices(std::getenv("BB_GLASS_AUTO_INDICES"));
    return most;
}

// bbport (r86h_glint-camera): the shape rule of BB_RT_GLASS=auto on top of the state rule: at least
// BB_GLASS_AUTO_MIN indices (default 60: the 30-index quads and 6-index sprites are flares and
// markers), a pixel shader that reads a texture and does not discard (particles and leaves discard).
// The effects hook also asks for the scene's 3D frame (Rasterizer::scene_started): the draws the
// first auto run took were the HUD, drawn after the display pass.
inline constexpr std::uint32_t RtGlassAutoMinDefault = 60;

/// BB_GLASS_AUTO_MIN's text: 3 to 1000000 (digits only, at most 8 of them), else the default.
constexpr std::uint32_t RtGlassParseAutoMin(const char* text) {
    if (!text || text[0] == '\0') {
        return RtGlassAutoMinDefault;
    }
    std::uint64_t value = 0;
    for (std::size_t i = 0; text[i] != '\0'; ++i) {
        if (text[i] < '0' || text[i] > '9' || i >= 8) {
            return RtGlassAutoMinDefault;
        }
        value = value * 10 + std::uint64_t(text[i] - '0');
    }
    return value >= 3 && value <= 1000000 ? std::uint32_t(value) : RtGlassAutoMinDefault;
}

inline std::uint32_t RtGlassAutoMin() {
    static const std::uint32_t least = RtGlassParseAutoMin(std::getenv("BB_GLASS_AUTO_MIN"));
    return least;
}

constexpr bool RtGlassAutoShape(std::uint32_t index_count, std::uint32_t least, bool textured, bool discards) {
    return index_count >= least && textured && !discards;
}
'''),
 ],
 V + "rt_glass_find.h": [
  ("// No Vulkan here: tests/test_rt_glass.cpp runs this header's code.\n",
   "// bbport (r86h_glint-camera): the flags in frame / after frame / camera voted, the verdicts outside frame\n"
   "// and shape (BB_RT_GLASS=auto leaves out the HUD and draws of the wrong shape), pairs of the frame first.\n"
   "// No Vulkan here: tests/test_rt_glass.cpp runs this header's code.\n"),
  ("    Skinned,\n    Verdicts\n};",
   "    Skinned,\n    Outside, // bbport (r86h_glint-camera): auto, drawn after the scene's frame (the HUD)\n"
   "    Shape,   // bbport (r86h_glint-camera): auto, in the frame but too few indices, no texture or a discard\n"
   "    Verdicts\n};"),
  ('                                                                "no capture", "skinned"}};',
   '                                                                "no capture", "skinned", "outside frame",\n'
   '                                                                "shape"}};'),
  ("inline constexpr std::uint32_t FlagGeometry = 128; ///< ... and its motion geometry\n",
   "inline constexpr std::uint32_t FlagGeometry = 128; ///< ... and its motion geometry\n"
   "inline constexpr std::uint32_t FlagScene = 256;   ///< (r86h) a draw inside the scene's frame (scene_started)\n"
   "inline constexpr std::uint32_t FlagAfter = 512;   ///< (r86h) a draw after the frame's display pass (the HUD)\n"
   "inline constexpr std::uint32_t FlagVoted = 1024;  ///< (r86h) the frame camera was known at the draw\n"),
  ("inline constexpr std::size_t LinePairs = 10;", "inline constexpr std::size_t LinePairs = 14; // bbport (r86h_glint-camera): was 10"),
  ('''inline bool GlassLike(const Pair& p, std::uint32_t auto_most) {
    return (p.flags & FlagZWrite) != 0 && p.draws + p.idx_max != 0 && p.idx_max <= auto_most;
}
''',
   '''inline bool GlassLike(const Pair& p, std::uint32_t auto_most) {
    return (p.flags & FlagZWrite) != 0 && p.draws + p.idx_max != 0 && p.idx_max <= auto_most;
}

/// bbport (r86h_glint-camera): what BB_RT_GLASS=auto takes now: glass-like, drawn inside the scene's
/// frame, textured, no discard, at least `auto_min` indices (flags and index counts are ored and
/// maxed over the pair's draws, so this is a summary, the draws decide).
inline bool PaneLike(const Pair& p, std::uint32_t auto_most, std::uint32_t auto_min) {
    return GlassLike(p, auto_most) && (p.flags & FlagScene) != 0 && (p.flags & FlagTextured) != 0 &&
           (p.flags & FlagDiscard) == 0 && p.idx_max >= auto_min;
}
'''),
  ("inline void Report(std::uint64_t frame, std::uint32_t auto_most) {",
   "inline void Report(std::uint64_t frame, std::uint32_t auto_most, std::uint32_t auto_min = 0) {"),
  ("    const auto rank = [&](const Pair& p) { return GlassLike(p, auto_most) ? 2 : (p.flags & FlagListed) ? 1 : 0; };\n",
   "    // bbport (r86h_glint-camera): pairs drawn inside the scene's frame first, glass-like ones first among them\n"
   "    const auto rank = [&](const Pair& p) {\n"
   "        const bool frame_pair = (p.flags & FlagScene) != 0;\n"
   "        return GlassLike(p, auto_most) ? (frame_pair ? 4 : 2) : frame_pair ? 3 : (p.flags & FlagListed) ? 1 : 0;\n"
   "    };\n"),
  ('''    std::size_t like = 0, listed = 0;
    for (const Pair& p : rows) {
        like += GlassLike(p, auto_most) ? 1 : 0;
        listed += (p.flags & FlagListed) ? 1 : 0;
    }
''',
   '''    std::size_t like = 0, listed = 0, scene = 0, scene_like = 0, pane_like = 0;
    for (const Pair& p : rows) {
        like += GlassLike(p, auto_most) ? 1 : 0;
        listed += (p.flags & FlagListed) ? 1 : 0;
        scene += (p.flags & FlagScene) ? 1 : 0;                                        // bbport (r86h_glint-camera)
        scene_like += ((p.flags & FlagScene) && GlassLike(p, auto_most)) ? 1 : 0;      // bbport (r86h_glint-camera)
        pane_like += PaneLike(p, auto_most, auto_min) ? 1 : 0;                         // bbport (r86h_glint-camera)
    }
'''),
  ("                like, auto_most, listed, static_cast<unsigned long long>(overflow));\n",
   "                like, auto_most, listed, static_cast<unsigned long long>(overflow));\n"
   "    // bbport (r86h_glint-camera): which of them are the scene's own and which the HUD's\n"
   '    std::printf("Ray tracing glass find (r86h): %zu of the %zu pairs were drawn inside the scene\'s frame (after its first G-buffer pass, before the display pass), %zu of them glass-like; %zu pairs fit the auto rule (in the frame, blend + depth write, %u to %u indices, a texture, no discard). A pair drawn only after the frame is the HUD: no ray traced pane can come from it\\n",\n'
   "                scene, rows.size(), scene_like, pane_like, auto_min, auto_most);\n"),
  ('                          GlassLike(p, auto_most) ? "auto-yes" : "auto-no", double(p.draws) / frames,',
   '                          PaneLike(p, auto_most, auto_min) ? "auto-yes" : "auto-no", double(p.draws) / frames,'),
  ('                          (p.flags & FlagZTest) ? " ztest" : "", p.targets));\n',
   '                          (p.flags & FlagZTest) ? " ztest" : "", p.targets));\n'
   "        // bbport (r86h_glint-camera): where in the frame the pair is drawn\n"
   '        put(std::snprintf(line + at, sizeof(line) - at, " |%s%s", (p.flags & FlagScene) ? ((p.flags & FlagAfter) ? " in and after frame" : " in frame") : (p.flags & FlagAfter) ? " after frame" : "",\n'
   '                          (p.flags & FlagVoted) ? " camera voted" : ""));\n'),
 ],
 V + "vk_rt_shadow.h": [
  ("    [[nodiscard]] const float* GlassCamera();\n",
   "    [[nodiscard]] const float* GlassCamera();\n"
   "    // bbport (r86h_glint-camera): whether the frame's camera vote holds a candidate now (a camera pass draw\n"
   "    // with constants came since the last frame end; the HUD, drawn after it, finds none). No side effect.\n"
   "    [[nodiscard]] bool GlassCameraKnown() const noexcept {\n"
   "        return r86f_camera != nullptr;\n"
   "    }\n"),
 ],
 V + "vk_rt_shadow.cpp": [
  ("    if (draw.camera_pass && !draw.glass && draw.constants && RtGlassOn()) {\n",
   "    if (draw.camera_pass && !draw.glass && draw.constants && (RtGlassOn() || RtGlassFind::On())) { // (r86h: and the find alone)\n"),
  ('            std::printf("Ray tracing glass (r86g): BB_RT_GLASS=auto: a forward draw alpha blended on colour target 0 with depth write on and 1 to %u indices (BB_GLASS_AUTO_INDICES) is a window pane (a skinned one is left out); no shader pair list\\n",\n'
   "                        RtGlassAutoIndices());\n",
   '            std::printf("Ray tracing glass (r86g): BB_RT_GLASS=auto: a forward draw alpha blended on colour target 0 with depth write on and %u to %u indices (BB_GLASS_AUTO_MIN, BB_GLASS_AUTO_INDICES), a pixel shader that reads a texture and does not discard, drawn inside the scene\'s frame (r86h: not the HUD), is a window pane (a skinned one is left out); no shader pair list\\n",\n'
   "                        RtGlassAutoMin(), RtGlassAutoIndices());\n"),
  ("        RtGlassFind::Report(frame, RtGlassAutoIndices());",
   "        RtGlassFind::Report(frame, RtGlassAutoIndices(), RtGlassAutoMin());"),
 ],
 V + "vk_rasterizer.cpp": [
  ("                         (dc.motion_geometry != 0 ? RtGlassFind::FlagGeometry : 0u);\n            note.x0 = find_box.offset.x;\n",
   "                         (dc.motion_geometry != 0 ? RtGlassFind::FlagGeometry : 0u) |\n"
   "                         // bbport (r86h_glint-camera): inside the scene's frame or after it (the HUD), camera voted\n"
   "                         (scene_started ? RtGlassFind::FlagScene : RtGlassFind::FlagAfter) |\n"
   "                         (rt_shadow->GlassCameraKnown() ? RtGlassFind::FlagVoted : 0u);\n"
   "            note.x0 = find_box.offset.x;\n"),
 ],
 V + "vk_rasterizer_effects.cpp": [
  ('''    const bool glass_auto =
        glass_ps && !gbuffer_draw && RtGlassAuto() &&
        RtGlassAutoDraw(regs.blend_control[0].enable != 0, regs.depth_control.depth_write_enable != 0,
                        regs.num_indices, RtGlassAutoIndices());
''',
   '''    const bool glass_auto_state =
        glass_ps && !gbuffer_draw && RtGlassAuto() &&
        RtGlassAutoDraw(regs.blend_control[0].enable != 0, regs.depth_control.depth_write_enable != 0,
                        regs.num_indices, RtGlassAutoIndices());
    // bbport (r86h_glint-camera): the state rule took the HUD (screen space draws after the display pass:
    // clip z 0, no 3D camera). A pane also has the shape of a mesh (BB_GLASS_AUTO_MIN indices or more, a
    // texture, no discard) and is drawn while the scene's frame runs (scene_started: from the first
    // G-buffer pass to the display pass). Off: glass_ps is null, nothing of this is read.
    const bool glass_shape =
        glass_auto_state && RtGlassAutoShape(regs.num_indices, RtGlassAutoMin(),
                                             !glass_ps->images.empty(), glass_ps->has_discard);
    const bool glass_auto = glass_shape && scene_started;
'''),
  ('''    if (glass_hook) {
        RtGlassProbe::Add(RtGlassProbe::Hook);
    }
''',
   '''    if (glass_hook) {
        RtGlassProbe::Add(RtGlassProbe::Hook);
    }
    // bbport (r86h_glint-camera): an auto draw left out above, said in the find table (a listed pair stays in)
    if (glass_auto_state && !glass_auto && RtGlassFind::On() &&
        !RtGlassMatch(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash, glass_ps->pgm_hash)) {
        RtGlassFind::NoteVerdict(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash, glass_ps->pgm_hash,
                                 scene_started ? RtGlassFind::Shape : RtGlassFind::Outside, nullptr);
    }
'''),
 ],
 "README.md": [
  ("| `BB_GLASS_FIND` | `1` (r86g, a diagnosis, log only):",
   "| `BB_GLASS_AUTO_MIN` | Only with `BB_RT_GLASS=auto` (r86h). The fewest indices a draw may have to count as a pane: 3 to 1000000, default 60 (digits only, anything else is the default). With it `auto` also asks for a pixel shader that reads a texture and does not discard, and for a draw inside the scene's frame (after the first G-buffer pass, before the display pass): the draws the first `auto` run took at the Hunter's Dream house were HUD draws (clip z 0, drawn after the frame), not bottles. Draws left out are counted in the find table as `outside frame` and `shape`. In the find table (r86h) every pair also says `in frame`, `after frame` or `in and after frame` and `camera voted`, pairs of the frame come first (14 shown), and a line `Ray tracing glass find (r86h):` counts them. |\n"
   "| `BB_GLASS_FIND` | `1` (r86g, a diagnosis, log only):"),
 ],
 "engine/tests/test_rt_glass.cpp": [
  ('        static_assert(RtGlassParseAutoIndices("1000000") == 1000000);\n',
   '        static_assert(RtGlassParseAutoIndices("1000000") == 1000000);\n'
   "        // bbport (r86h_glint-camera): the shape rule and the least index count's text\n"
   "        static_assert(RtGlassAutoMinDefault == 60 && RtGlassParseAutoMin(nullptr) == 60 && RtGlassParseAutoMin(\"\") == 60);\n"
   '        static_assert(RtGlassParseAutoMin("90") == 90 && RtGlassParseAutoMin("3") == 3 && RtGlassParseAutoMin("2") == 60);\n'
   '        static_assert(RtGlassParseAutoMin("x") == 60 && RtGlassParseAutoMin("5x") == 60 && RtGlassParseAutoMin("1000001") == 60);\n'
   "        static_assert(RtGlassAutoShape(60, 60, true, false) && !RtGlassAutoShape(59, 60, true, false));\n"
   "        static_assert(!RtGlassAutoShape(400, 60, false, false) && !RtGlassAutoShape(400, 60, true, true));\n"),
  ("        assert(RtGlassFind::GlassLike(table.pairs[0], 12000) && !RtGlassFind::GlassLike(table.pairs[0], 200));\n",
   "        assert(RtGlassFind::GlassLike(table.pairs[0], 12000) && !RtGlassFind::GlassLike(table.pairs[0], 200));\n"
   "        // bbport (r86h_glint-camera): the pane rule's summary needs the frame flag, a texture, no discard, the least count\n"
   "        assert(!RtGlassFind::PaneLike(table.pairs[0], 12000, 60));\n"
   "        table.pairs[0].flags |= RtGlassFind::FlagScene | RtGlassFind::FlagTextured;\n"
   "        assert(RtGlassFind::PaneLike(table.pairs[0], 12000, 60) && !RtGlassFind::PaneLike(table.pairs[0], 12000, 400));\n"
   "        table.pairs[0].flags |= RtGlassFind::FlagDiscard;\n"
   "        assert(!RtGlassFind::PaneLike(table.pairs[0], 12000, 60));\n"
   "        table.pairs[0].flags &= ~(RtGlassFind::FlagScene | RtGlassFind::FlagTextured | RtGlassFind::FlagDiscard);\n"),
 ],
}

def rd(p): return io.open(p, encoding="utf-8", newline="").read()
def wr(p, s): io.open(p, "w", encoding="utf-8", newline="").write(s)

def plan():
    out, state = {}, []
    for f, eds in E.items():
        s = rd(os.path.join(ROOT, f)); crlf = "\r\n" in s; t = s.replace("\r\n", "\n")
        for a, b in eds:
            if t.count(b) == 1 and b != a:
                state.append("done"); continue
            if t.count(a) != 1:
                print("REFUSED", f, "anchor count", t.count(a), repr(a[:70])); sys.exit(1)
            t = t.replace(a, b); state.append("todo")
        out[f] = (s, t.replace("\n", "\r\n") if crlf else t)
    if "done" in state and "todo" in state:
        print("REFUSED: mixed state (%d done, %d todo)" % (state.count("done"), state.count("todo"))); sys.exit(1)
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
    print("applied" if "todo" not in state else "not applied; would apply (%d edits in %d files)" % (len(state), len(E))); sys.exit(0)
if "todo" not in state:
    print("already applied"); sys.exit(0)
os.makedirs(BK, exist_ok=True)
for f, (s, t) in out.items():
    if s != t:
        b = os.path.join(BK, f.replace("/", "__"))
        if not os.path.exists(b): wr(b, s)
        wr(os.path.join(ROOT, f), t)
print("applied")
