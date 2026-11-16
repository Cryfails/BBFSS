# r98b_particles-reduced-scene: FIX for r98_ambient-particles (apply r98 first; revert this before
# reverting r98). The ambient motes drew nothing in the owner's configuration.
#
# Cause (read in the tree 2026-11-15): the launcher's upscale_before_post=1 (engine/start/main.cpp
# sets BB_RENDER_RES = BB_OUTPUT_RES and BB_UPSCALE_EARLY=1) makes TemporalUpscaler::early_upscale
# true (scaled_session true, render size = output size; the log says "Upscaler: runs on the scene
# before post-processing, game targets 3840x2160"). SceneResolution::Native() is then the output
# size, so a DLSS Performance scene of 1920x1080 is a reduced scene. In that mode the upscale is
# TemporalUpscaler::Run(), called by OnDispatch at the trigger compute shader (the condition
# `!Scaled() || early_upscale`): DLSS writes the HDR scene colour at the output size before the
# game's post. The game then runs its post at the output size; at its first UI draw OnDraw's
# UiComposition::Choose gets fsr_active = Active() && !failed && !early_upscale = false, so it
# takes Background::Copy = RunUiOnly (the output-size copy of the game's finished frame into
# ui_image, "UI: native composition 3840x2160"); OnDisplayPass skips RunScaled (`!early_upscale`).
# RunScaled, the only caller of after_upscale, never runs: Draw is never called. The slot games
# (BB_RENDER_RES 1280x720 + early, scene 640x360) take the same path.
#
# Fix: RunUiOnly calls after_upscale after its copy, for a frame of the world that Run upscaled
# this frame (world, dispatched_last_frame, camera ready), before any UI pixel. The light is read
# from the game's finished frame (output size, no jitter: new flag AP_FLAG_SCENE_OUTPUT, the
# vertex shader reads it at output pixels), the depth from the scene depth as Run read it (its
# reduced proxy at the scene size, jittered: unchanged maths). A frame without UI (HUD hidden,
# BB_CLEAN_SHOT) makes that copy at its display pass, only while after_upscale is set, as the
# first UI draw would (the display pass then reads it, as for a frame with UI). RunScaled's two
# hooks stay and now name their path; the once-line, the first-draw line (names the path taken),
# comments and the README say where it draws. Knob off: after_upscale is empty and both new
# places test it first: nothing created, nothing called.
#
# Files (each edit's text found exactly once, else nothing is written):
#  - vk_temporal_upscaler.h: UpscaledFrame gets scene_at_output and path; after_upscale's comment;
#  - vk_temporal_upscaler.cpp: RunScaled's two calls pass false and their path; OnDisplayPass makes
#    the copy of a frame without UI (early upscale, motes on); RunUiOnly calls after_upscale;
#  - vk_ambient_particles.cpp: once-line, first-draw line, the flag set in Draw, a comment;
#  - vk_ambient_particles.h: comments;
#  - host_shaders/ambient_particles_layout.h: AP_FLAG_SCENE_OUTPUT 2;
#  - host_shaders/ambient_particles.vert: the light read at output pixels with that flag;
#  - README.md: where it draws, the light's pixels, the first-draw line.
# r98's own check reports a mixed state while this is applied (it edits r98's text): revert r98b
# before reverting r98.
#
# Use: python -I -X utf8 r98b_particles-reduced-scene.py check | apply | revert. Root from
# R98_ROOT, else <tree>. Line ends of each file kept (CRLF in the tree). Originals of the
# edited files are copied to r98b_backup/ next to this script at apply.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r98b_backup")
ROOT = os.environ.get("R98_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"
TAG = "r98b_particles-reduced-scene"

# ---------------------------------------------------------------- vk_temporal_upscaler.h
UH_OLD = r'''        std::array<float, 2> jitter{};
    };
    /// Called by RunScaled (outputs other than 1920x1080) after a successful upscale, before
    /// any UI pixel; empty unless a pass set it (the Rasterizer, BB_PARTICLES above 0 only).
'''
UH_NEW = r'''        std::array<float, 2> jitter{};
        /// bbport (r98b_particles-reduced-scene): `scene` is the game's finished frame at the
        /// output size, without jitter (the upscale ran before the game's post: Run), not the
        /// render-size frame the upscaler read; its light is read at output pixels.
        bool scene_at_output = false;
        /// Where the frame comes from, for the log (a string literal).
        const char* path = "";
    };
    /// Called after a successful upscale, before any UI pixel: by RunScaled (the upscale of the
    /// game's finished frame, outputs other than 1920x1080) and, with the upscale before the
    /// game's post (Run; upscale_before_post=1, BB_UPSCALE_EARLY=1), by RunUiOnly after its
    /// output-size copy of the game's finished frame, for a frame of the world Run upscaled (at
    /// the first UI draw, or at the display pass of a frame without UI). Empty unless a pass set
    /// it (the Rasterizer, BB_PARTICLES above 0 only).
'''

# ---------------------------------------------------------------- vk_temporal_upscaler.cpp
SCALED1_OLD = r'''        if (ok4 && after_upscale) { // bbport (r98_ambient-particles): before the UI
            after_upscale({UiStorageView(vk::Image(ui_image)), depth_view, color_view,
                           color.info.pixel_format, ow, oh, w, h, jitter});
'''
SCALED1_NEW = r'''        if (ok4 && after_upscale) { // bbport (r98_ambient-particles): before the UI
            after_upscale({UiStorageView(vk::Image(ui_image)), depth_view, color_view,
                           color.info.pixel_format, ow, oh, w, h, jitter, false,
                           "after RunScaled's upscale of the game's finished frame (DLSS, FSR 4, "
                           "XeSS or TAA)"});
'''
SCALED2_OLD = r'''    if (ok && after_upscale) { // bbport (r98_ambient-particles): before the UI
        after_upscale({UiStorageView(vk::Image(ui_image)), depth_view, color_view,
                       color.info.pixel_format, ow, oh, w, h, jitter});
'''
SCALED2_NEW = r'''    if (ok && after_upscale) { // bbport (r98_ambient-particles): before the UI
        after_upscale({UiStorageView(vk::Image(ui_image)), depth_view, color_view,
                       color.info.pixel_format, ow, oh, w, h, jitter, false,
                       "after RunScaled's upscale of the game's finished frame (FSR 3)"});
'''
DISPLAY_ANCHOR = "    // bbport: frame generation: a frame without UI is its own frame without UI.\n"
DISPLAY_BLOCK = r'''    // bbport (r98b_particles-reduced-scene): with the upscale before the game's post (Run) a
    // frame without UI (the HUD hidden, BB_CLEAN_SHOT) reaches its display pass with no
    // output-size copy of its frame. Only while after_upscale is set (the ambient motes on) the
    // copy is made here as the first UI draw would make it (RunUiOnly, which calls
    // after_upscale), and the display pass reads it as it does a frame with UI.
    if (after_upscale && early_upscale && !ui_phase && LdrFrame(ldr_target) &&
        dispatched_last_frame && camera_motion.Ready() && Active() && !failed) {
        RunUiOnly(ldr_target, camera_motion.Depth(), true);
        if (ui_phase && hdr_native.WantsUiStart() && HdrNative::Wanted()) {
            hdr_native.OnUiStart(HdrUiImage());
        }
    }
'''
UIONLY_ANCHOR = "    if (!early_upscale || !dispatched_last_frame) {\n"
UIONLY_BLOCK = r'''    // bbport (r98b_particles-reduced-scene): with the upscale before the game's post (Run, at
    // the trigger dispatch) RunScaled never runs: the output-size frame before the UI is this
    // copy of the game's finished frame. Only for a frame of the world Run upscaled this frame.
    // The light is read from the game's frame (output size, no jitter), the depth from the scene
    // depth as Run read it (its reduced proxy at the scene size, jittered by `jitter`).
    if (after_upscale && early_upscale && world && dispatched_last_frame &&
        camera_motion.Ready()) {
        auto& frame = texture_cache.GetImage(color_id);
        auto& scene_depth = texture_cache.GetImage(camera_motion.Depth());
        const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(scene_depth);
        const u32 dw = reduced ? scene_targets.Size().width : scene_depth.info.size.width;
        const u32 dh = reduced ? scene_targets.Size().height : scene_depth.info.size.height;
        // Output pixels address the game's frame: it must have the output size (else the call
        // has no view and counts as a skipped frame).
        const bool fits = frame.info.size.width == ui_width &&
                          frame.info.size.height == ui_height &&
                          scene_depth.info.size.width == ui_width &&
                          scene_depth.info.size.height == ui_height;
        vk::ImageView depth_view{}, frame_view{};
        if (fits) {
            if (reduced) {
                VideoCore::ImageViewInfo di;
                di.format = scene_depth.info.pixel_format;
                depth_view = scene_targets.Read(camera_motion.Depth(), di).view;
            } else {
                depth_view = CachedView(scene_depth, scene_depth.info.pixel_format,
                                        vk::ImageAspectFlagBits::eDepth);
                runtime.Transit(&scene_depth, vk::ImageLayout::eGeneral,
                                vk::PipelineStageFlagBits2::eVertexShader |
                                    vk::PipelineStageFlagBits2::eFragmentShader,
                                vk::AccessFlagBits2::eShaderSampledRead);
            }
            frame_view =
                CachedView(frame, frame.info.pixel_format, vk::ImageAspectFlagBits::eColor);
            runtime.Transit(&frame, vk::ImageLayout::eGeneral,
                            vk::PipelineStageFlagBits2::eVertexShader,
                            vk::AccessFlagBits2::eShaderSampledRead);
            runtime.FlushBarriers();
        }
        after_upscale({fits ? UiStorageView(vk::Image(ui_image)) : vk::ImageView{}, depth_view,
                       frame_view, frame.info.pixel_format, ui_width, ui_height, dw, dh, jitter,
                       true,
                       "into RunUiOnly's output-size copy of the game's finished frame (upscaled "
                       "before its post by Run)"});
    }
'''

# ---------------------------------------------------------------- vk_ambient_particles.cpp
ONCE_OLD = r'''                "after the upscale into the output frame before the UI, on outputs other than "
                "1080p only; drifting with %s\n",
'''
ONCE_NEW = r'''                "into the output-size frame before the UI, after the upscale: right after "
                "RunScaled's upscale of the game's finished frame (by default at outputs other "
                "than 1920x1080), "
                "or, with the upscale before the game's post (upscale_before_post=1 or "
                "BB_UPSCALE_EARLY=1), into RunUiOnly's output-size copy of the game's finished "
                "frame (at its first UI draw, or at the display pass of a frame without UI); "
                "nothing at a 1920x1080 output; drifting with %s\n",
'''
PUSH_OLD = r'''        const AmbientMotes::Push push = AmbientMotes::MakePush(
            knobs, drift, camera.view, camera.inv_view, camera.proj, frame.width, frame.height,
            frame.render_width, frame.render_height, frame.jitter, srgb);
'''
PUSH_NEW = r'''        AmbientMotes::Push push = AmbientMotes::MakePush(
            knobs, drift, camera.view, camera.inv_view, camera.proj, frame.width, frame.height,
            frame.render_width, frame.render_height, frame.jitter, srgb);
        // bbport (r98b_particles-reduced-scene): the frame before the UI has the output size and
        // no jitter (the game's finished frame after an upscale before its post): its light is
        // read at output pixels.
        static_assert((AP_FLAG_SCENE_OUTPUT & AP_FLAG_SCENE_SRGB) == 0, "two flag bits");
        if (frame.scene_at_output) {
            push.frame[3] |= u32(AP_FLAG_SCENE_OUTPUT);
        }
'''
FIRST_OLD = r'''            std::printf("Ambient particles (r98): first draw into %ux%u after the upscale (scene "
                        "%ux%u, frame before the UI read %s)\n",
                        frame.width, frame.height, frame.render_width, frame.render_height,
                        srgb ? "through an sRGB view" : "as stored");
'''
FIRST_NEW = r'''            std::printf("Ambient particles (r98): first draw into %ux%u %s (scene depth %ux%u; "
                        "the frame before the UI at the %s size, read %s)\n",
                        frame.width, frame.height,
                        frame.path && frame.path[0] ? frame.path : "after the upscale",
                        frame.render_width, frame.render_height,
                        frame.scene_at_output ? "output" : "render",
                        srgb ? "through an sRGB view" : "as stored");
'''
BARRIER_OLD = "                // output image's last barrier (RunScaled) already ends at colour attachment use.\n"
BARRIER_NEW = ("                // output image's last barrier (RunScaled, or RunUiOnly's copy) already ends at\n"
               "                // colour attachment use.\n")

# ---------------------------------------------------------------- vk_ambient_particles.h
APH1_OLD = r'''// path (outputs other than 1080p: TemporalUpscaler::RunScaled calls after_upscale). Made by the
'''
APH1_NEW = r'''// path (outputs other than 1080p: TemporalUpscaler::RunScaled calls after_upscale; with the
// upscale before the game's post, r98b_particles-reduced-scene, RunUiOnly calls it after its
// output-size copy of the game's finished frame). Made by the
'''
APH2_OLD = r'''// mote's place (the jitter added back), the light the render-size frame before the UI.
'''
APH2_NEW = r'''// mote's place (the jitter added back), the light the frame before the UI (the render-size
// frame the upscaler read, or the game's output-size frame after an upscale before its post).
'''

# ---------------------------------------------------------------- shaders
LAYOUT_ANCHOR = "#define AP_FLAG_SCENE_SRGB 1\n"
LAYOUT_BLOCK = r'''// bbport (r98b_particles-reduced-scene), Push::frame[3]: the frame before the UI has the output
// size and no jitter (the game's finished frame after an upscale before its post): its light is
// read at output pixels.
#define AP_FLAG_SCENE_OUTPUT 2
'''
VERT_HEAD_OLD = r'''// drawn). The mote's light is the frame before the UI around it (5 pixels at the render size, the
// centre counted twice): it
'''
VERT_HEAD_NEW = r'''// drawn). The mote's light is the frame before the UI around it (5 pixels of it, the centre
// counted twice; at the render size, or at the output size after an upscale before the game's
// post, AP_FLAG_SCENE_OUTPUT): it
'''
VERT_BIND_OLD = "layout(binding = 1) uniform texture2D scene_tex; // the frame before the UI, render size\n"
VERT_BIND_NEW = ("layout(binding = 1) uniform texture2D scene_tex; // the frame before the UI: render size, or\n"
                 "                                                 // output size (AP_FLAG_SCENE_OUTPUT)\n")
VERT_FLAGS_OLD = "                      // w: flags (AP_FLAG_SCENE_SRGB)\n"
VERT_FLAGS_NEW = "                      // w: flags (AP_FLAG_SCENE_SRGB, AP_FLAG_SCENE_OUTPUT)\n"
VERT_LIGHT_OLD = r'''    // Light: the frame before the UI around the mote.
    const int tap = int(max(3.0, 2.0 * drawn * render.y / out_size.y));
    vec3 light = 2.0 * scene_at(centre, last) + scene_at(centre + ivec2(tap, 0), last) +
                 scene_at(centre - ivec2(tap, 0), last) + scene_at(centre + ivec2(0, tap), last) +
                 scene_at(centre - ivec2(0, tap), last);
'''
VERT_LIGHT_NEW = r'''    // Light: the frame before the UI around the mote: at the render size with the depth's jitter,
    // or (AP_FLAG_SCENE_OUTPUT: the game's finished frame after an upscale before its post) at the
    // output size without jitter. The taps lie 2 drawn radii away (at least 3 of its pixels).
    const bool scene_out = (frame.w & uint(AP_FLAG_SCENE_OUTPUT)) != 0u;
    const vec2 scene_size = scene_out ? out_size : render;
    const ivec2 scene_last = ivec2(scene_size) - 1;
    const ivec2 spot =
        scene_out ? clamp(ivec2((ndc * 0.5 + 0.5) * out_size), ivec2(0), scene_last) : centre;
    const int tap = int(max(3.0, 2.0 * drawn * scene_size.y / out_size.y));
    vec3 light = 2.0 * scene_at(spot, scene_last) + scene_at(spot + ivec2(tap, 0), scene_last) +
                 scene_at(spot - ivec2(tap, 0), scene_last) +
                 scene_at(spot + ivec2(0, tap), scene_last) +
                 scene_at(spot - ivec2(0, tap), scene_last);
'''

# ---------------------------------------------------------------- README.md
README_WHERE_OLD = ("The motes are drawn after the upscaler (DLSS, FSR, XeSS or TAA) into the output-size frame, "
                    "before the game's UI, so they need no motion vectors and stay sharp; that place exists only "
                    "when the output is not 1920x1080: with a 1920x1080 output, or with `BB_UPSCALER=none`, "
                    "nothing is drawn.")
README_WHERE_NEW = ("The motes are drawn after the upscaler (DLSS, FSR, XeSS or TAA) into the output-size frame, "
                    "before the game's UI, so they need no motion vectors and stay sharp. Where: by default an "
                    "output other than 1920x1080 is upscaled from the game's finished frame, and the motes are "
                    "drawn right after that upscale; with `upscale_before_post=1` (or `BB_UPSCALE_EARLY=1`) it upscales "
                    "the scene before the game's post-processing, the game finishes the frame at the output size, "
                    "and the motes are drawn into the output-size copy of that finished frame the UI is drawn "
                    "over (made at the first UI draw, or at the display pass of a frame without UI), only in a "
                    "frame of the world the upscaler took. With a 1920x1080 output, or with `BB_UPSCALER=none`, "
                    "nothing is drawn.")
README_LIGHT_OLD = "Its colour is the frame before the UI around it (5 pixels of the render-size frame, the centre counted twice) times 1.5"
README_LIGHT_NEW = ("Its colour is the frame before the UI around it (5 pixels of it, of the render-size frame the "
                    "upscaler read or, with the upscale before the post, of the game's output-size frame, the "
                    "centre counted twice) times 1.5")
README_LOG_OLD = "The log says the knobs once when on, the first draw once,"
README_LOG_NEW = "The log says the knobs once when on, the first draw once (with where it drew),"

# (kind, old or anchor, new or block): "replace" old by new; "after"/"before": the block goes
# right after/before the anchor.
EDITS = {
    R + "vk_temporal_upscaler.h": [("replace", UH_OLD, UH_NEW)],
    R + "vk_temporal_upscaler.cpp": [
        ("before", DISPLAY_ANCHOR, DISPLAY_BLOCK),
        ("before", UIONLY_ANCHOR, UIONLY_BLOCK),
        ("replace", SCALED1_OLD, SCALED1_NEW),
        ("replace", SCALED2_OLD, SCALED2_NEW),
    ],
    R + "vk_ambient_particles.cpp": [
        ("replace", ONCE_OLD, ONCE_NEW),
        ("replace", PUSH_OLD, PUSH_NEW),
        ("replace", FIRST_OLD, FIRST_NEW),
        ("replace", BARRIER_OLD, BARRIER_NEW),
    ],
    R + "vk_ambient_particles.h": [
        ("replace", APH1_OLD, APH1_NEW),
        ("replace", APH2_OLD, APH2_NEW),
    ],
    H + "ambient_particles_layout.h": [("after", LAYOUT_ANCHOR, LAYOUT_BLOCK)],
    H + "ambient_particles.vert": [
        ("replace", VERT_HEAD_OLD, VERT_HEAD_NEW),
        ("replace", VERT_BIND_OLD, VERT_BIND_NEW),
        ("replace", VERT_FLAGS_OLD, VERT_FLAGS_NEW),
        ("replace", VERT_LIGHT_OLD, VERT_LIGHT_NEW),
    ],
    "README.md": [
        ("replace", README_WHERE_OLD, README_WHERE_NEW),
        ("replace", README_LIGHT_OLD, README_LIGHT_NEW),
        ("replace", README_LOG_OLD, README_LOG_NEW),
    ],
}

# After apply each file holds these texts this many times.
CHECKS = {
    R + "vk_temporal_upscaler.cpp": [("after_upscale(", 3), (TAG, 2),
                                     ("RunUiOnly(ldr_target, camera_motion.Depth(), true);", 1),
                                     ("jitter, false,", 2), ("jitter,\n                       true,", 1)],
    R + "vk_temporal_upscaler.h": [("bool scene_at_output = false;", 1), ('const char* path = "";', 1)],
    R + "vk_ambient_particles.cpp": [("on outputs other than", 0), ("AP_FLAG_SCENE_OUTPUT", 2),
                                     ("frame.path", 3), ("frame.scene_at_output", 2)],
    H + "ambient_particles_layout.h": [("#define AP_FLAG_SCENE_OUTPUT 2\n", 1)],
    H + "ambient_particles.vert": [("AP_FLAG_SCENE_OUTPUT", 5), ("scene_at(centre", 0)],
    "README.md": [("exists only when the output is not 1920x1080", 0), ("upscale_before_post=1` (or", 1)],
}
# Texts that must come in this order.
ORDER = {
    R + "vk_temporal_upscaler.cpp": [
        "void TemporalUpscaler::OnDisplayPass(", "        RunScaled();\n",
        "RunUiOnly(ldr_target, camera_motion.Depth(), true);",
        "    // bbport: frame generation: a frame without UI is its own frame without UI.",
        "void TemporalUpscaler::RunUiOnly(", "cmd.blitImage(source, source_layout, ui,",
        "if (after_upscale && early_upscale && world && dispatched_last_frame &&",
        "    if (!early_upscale || !dispatched_last_frame) {",
        "    done_this_frame = ui_phase = true;",
        "void TemporalUpscaler::RunScaled()", "if (ok4 && after_upscale)",
        "        done_this_frame = true;\n        if (ok4) {",
        "if (ok && after_upscale)", "    done_this_frame = true; // the UI is not jittered"],
    R + "vk_ambient_particles.cpp": [
        "AmbientParticles::AmbientParticles(", "RunUiOnly's output-size copy",
        "void AmbientParticles::Draw(", "push.frame[3] |= u32(AP_FLAG_SCENE_OUTPUT);",
        "first draw into", "scheduler.RecordCrumb("],
    H + "ambient_particles.vert": ["const ivec2 centre =", "const bool scene_out =",
                                   "vec3 light = 2.0 * scene_at(spot"],
}


def pairs(path):
    out = []
    for kind, a, b in EDITS[path]:
        if kind == "replace":
            out.append((a, b))
        elif kind == "after":
            out.append((a, a + b))
        else:
            out.append((a, b + a))
    return out


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d"
                                 % (path, s, texts[path].count(s), n))
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                raise SystemExit("order check: %s: %r not after the one before" % (path, s))
            at = i
    for path in EDITS:
        for old, new in pairs(path):
            if not all(ord(c) < 128 for c in new) or "\r" in new:
                raise SystemExit("%s: text must be ASCII with LF in the script" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R98_ROOT)" % ROOT)
    plan, states = [], set()
    for path in EDITS:
        if not os.path.exists(os.path.join(ROOT, path)):
            raise SystemExit("%s missing: apply r98_ambient-particles first" % path)
        raw, eol, cur = load(path)
        ps = pairs(path)
        done = sum(cur.count(new) == 1 for old, new in ps)
        todo = sum(cur.count(new) == 0 and cur.count(old) == 1 for old, new in ps)
        if done == len(ps):
            state = "applied"
        elif todo == len(ps):
            state = "clean"
        else:
            raise SystemExit("%s: %d of %d edits present, %d could be made (mixed or changed)"
                             % (path, done, len(ps), todo))
        plan.append((path, ps, raw, eol, cur))
        states.add(state)
    if len(states) != 1:
        raise SystemExit("mixed state: some files have this patch, some not")
    state = states.pop()
    if cmd in ("check", "apply"):
        texts = {}
        for path, ps, raw, eol, cur in plan:
            if state == "clean":
                for old, new in ps:
                    if cur.count(old) != 1 or cur.count(new) != 0:
                        raise SystemExit("%s: edit text not found once: %r" % (path, old[:70]))
                    cur = cur.replace(old, new, 1)
                for old, new in ps:
                    if cur.count(new) != 1:
                        raise SystemExit("%s: edits overlap: %r" % (path, new[:70]))
            texts[path] = cur
        text_checks(texts)
        if cmd == "check":
            if state == "applied":
                print("applied (text checks pass)")
            else:
                print("not applied; would apply (%d files edited, %d edits; text checks on the "
                      "result pass)" % (len(plan), sum(len(p[1]) for p in plan)))
            return
        if state == "applied":
            print("already applied")
            return
        outs = [(path, texts[path].replace("\n", eol).encode("utf-8"), raw)
                for path, ps, raw, eol, cur in plan]
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                full = os.path.join(ROOT, path)
                tmp = full + ".r98btmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r98btmp"
                if os.path.exists(tmp):
                    os.remove(tmp)
            for path, raw in written:
                open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied (%d files edited)" % len(plan))
        return
    if state != "applied":
        print("nothing to revert")
        return
    outs = []
    for path, ps, raw, eol, cur in plan:
        for old, new in reversed(ps):
            if cur.count(new) != 1:
                raise SystemExit("%s: edited text not found once" % path)
            cur = cur.replace(new, old, 1)
        outs.append((path, cur.replace("\n", eol).encode("utf-8")))
    for path, data in outs:
        open(os.path.join(ROOT, path), "wb").write(data)
    print("reverted")


main()
