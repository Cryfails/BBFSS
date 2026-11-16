# r86j_glint-same-game: FEATURE fix (glass, r83 chain; on top of r86i, r86h, r86g, r86f, r86e, r86d, r86c, r86b, r83c, r83b, r83).
#
# Why (b49, 2026-11-16): the r86i box lines never reached the kept log. The slot runner keeps the first and last of
# each KIND of feature line and at most 30 kinds; the find's pair rows (r86g) differ by their hex ids, so each is its
# own kind and they filled the 30 places before the box lines. The three dream-house jobs were also three games, so
# their cameras differed (diff 30) and the box clipped only the left edge of the bottle cabinet.
#
# What this does:
#  1. KEPT PREFIX. Every line the box and the glint chain print for this test starts with "GLINT-PROOF " (the slot
#     runner, Test-BBFSSSlot.ps1, keeps those lines first, up to 40): the box set line (listed at frame F), the box
#     report with "mesh keys taken N (+K)" also when N is 0 (and, new, how many entries the ray traced scene holds
#     in all, and how many camera pass draws PrepareDraw refused for no camera constants: the bottles may not be
#     entries at all), the 12 best box entries, a CHAIN line every 300 frames (G-buffer draws of the taken meshes,
#     pane records made / not made, glint noted, glint passes asked for after the blended draws or at the fog
#     composite), a GATE line at each change of the glint setting and a GLINT line with the glint pass counts
#     (passes, skips by reason, pane points, glass px, lamp pairs in reach, glint px) printed at every change of
#     the setting and every 600 frames.
#  2. SAME GAME. BB_GLASS_GLINT and BB_GLASS_BOX_PANES are read again while the game runs when the build has the
#     test tools' live knobs (bbport_live_knobs.h; a job's set:/unset: actions): one game can take the glass off
#     (set:BB_GLASS_GLINT=0), put a box on the bottles, switch the glint on (=1) or to the test view (=show), and
#     take the box away again, all at one camera. The glint's pipelines are made at the start from the environment
#     value (it must be above 0 there); the live value is only the switch and the strength. Without the live knobs
#     the build is as r86i. A change of any live knob lists the box again 90 frames later (r86i).
#  3. FALLBACK. The glint of a G-buffer pane waits for the lit scene (EffectsBlendedScene at the first blended draw
#     with more than 6 indices). If no such draw comes before the fog composite, EffectsSceneComposite runs it
#     (counted apart in the chain line), so a frame without that first draw does not lose it.
# Off: BB_GLASS_FIND unset: the chain counters are touched only in code that BB_GLASS_BOX_PANES, a taken box or the
# glint already guard (GlassBoxMatch returns at its first test with no keys; the no-constants count is behind
# RtGlassFind::On()); the glint's live gate is one atomic load a frame and one a G-buffer pane draw, and only exists
# with BB_GLASS_GLINT above 0 at the start (no GlassGlint object otherwise). No shader touched, nothing allocated.
# Files: rt_glass_find.h, glass_glint.h, vk_glass_glint.h/.cpp, vk_rt_shadow.cpp, vk_rasterizer_effects.cpp,
# README.md, tests/test_rt_glass.cpp, tests/test_glass_glint.cpp.
# Use: python -I -X utf8 r86j_glint-same-game.py check | apply | revert
# Root: R86J_ROOT else <tree>. Line ends kept per file. Backups in r86j_backup next to this script.
import os, sys, io

ROOT = os.environ.get("R86J_ROOT") or "<tree>"
BK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r86j_backup")
V = "engine/gpu/shadps4/video_core/renderer_vulkan/"

E = {
 V + "rt_glass_find.h": [
  ("#include <algorithm>\n#include <array>\n#include <cstddef>\n",
   "#include <algorithm>\n#include <array>\n#include <atomic> // bbport (r86j_glint-same-game)\n#include <cstddef>\n"),
  ("} // namespace Vulkan::RtGlassFind\n",
   r'''// ---- bbport (r86j_glint-same-game) ------------------------------------------------------------------------
// The links of the box panes' chain, counted since the start (relaxed atomics: the capture hook and the frame end
// may run on other threads). The log line "GLINT-PROOF chain ..." (RtShadow::GlassFindBox) shows the first link
// that stays at 0.
struct BoxChain {
    std::atomic<std::uint64_t> matched{0};         ///< G-buffer draws of a mesh the box rule took
    std::atomic<std::uint64_t> recorded{0};        ///< of them: a pane record was made (RtGlassProbe::Note)
    std::atomic<std::uint64_t> not_recorded{0};    ///< of them: none (PrepareDraw refused, over budget)
    std::atomic<std::uint64_t> no_constants{0};    ///< camera pass draws PrepareDraw refused: no 864-byte constants
    std::atomic<std::uint64_t> noted{0};           ///< glint noted for the lit scene (the glint is on)
    std::atomic<std::uint64_t> after_blended{0};   ///< its pass asked for at the first blended draw
    std::atomic<std::uint64_t> after_composite{0}; ///< ... at the fog composite, when no blended draw came first
};

inline BoxChain& Chain() {
    static BoxChain chain;
    return chain;
}

} // namespace Vulkan::RtGlassFind
'''),
 ],
 V + "glass_glint.h": [
  ("/// The knobs, read once (the first caller).\n",
   "/// bbport (r86j_glint-same-game): BB_GLASS_GLINT's text read again while the game runs (the test tools' live\n"
   "/// knobs): the strength, negative for the test view (\"show\", strength 1); 0 for off, empty or unreadable text.\n"
   "inline float ParseLive(const char* text) {\n"
   "    bool show = false, unreadable = false;\n"
   "    const float strength = ParseStrength(text, show, unreadable);\n"
   "    return show ? -strength : strength;\n"
   "}\n\n"
   "/// The knobs, read once (the first caller).\n"),
 ],
 V + "vk_glass_glint.h": [
  ("        u32 no_pane = 0, other_camera = 0, no_lamps = 0, lamps_open = 0, shape = 0, cap = 0;\n",
   "        u32 no_pane = 0, other_camera = 0, no_lamps = 0, lamps_open = 0, shape = 0, cap = 0;\n"
   "        u32 gate_off = 0; // bbport (r86j_glint-same-game): pane draws asked while the live setting was 0\n"),
  ("    bool told_first = false;\n};\n",
   "    bool told_first = false;\n"
   "    /// bbport (r86j_glint-same-game): the live strength seen at the last frame end (negative: test view);\n"
   "    /// -2 before the first frame. A change prints the GLINT-PROOF gate line and the counts so far.\n"
   "    float gate_last = -2.0f;\n};\n"),
 ],
 V + "vk_glass_glint.cpp": [
  ('#include "bbport_toggles.h"\n',
   '#include "bbport_toggles.h"\n'
   '// bbport (r86j_glint-same-game): the test tools\' live knobs (branch dev/test-tools) when the build has them\n'
   '#if __has_include("bbport_live_knobs.h")\n'
   '#include "bbport_live_knobs.h"\n'
   '#define BB_GLINT_LIVE 1\n'
   '#else\n'
   '#define BB_GLINT_LIVE 0\n'
   '#endif\n'),
  ("namespace BG = ::BbGlassGlint;\n",
   "namespace BG = ::BbGlassGlint;\n"
   "/// bbport (r86j_glint-same-game): the glint's strength now, negative for the test view; 0: off. With the live\n"
   "/// knobs BB_GLASS_GLINT is asked again (a job's set:BB_GLASS_GLINT=0|1|show); the pipelines exist only when the\n"
   "/// start value was above 0. Without them: the start value.\n"
   "float LiveStrength([[maybe_unused]] const BG::Knobs& start) {\n"
   "#if BB_GLINT_LIVE\n"
   "    static BbLiveKnobs::Knob<float> knob{\"BB_GLASS_GLINT\", [](const char* text) { return BG::ParseLive(text); }};\n"
   "    return knob.Get();\n"
   "#else\n"
   "    return start.show ? -start.strength : start.strength;\n"
   "#endif\n"
   "}\n"),
  ('                RtGlassCarryOn() ? "on" : "off", RtGlassOn() ? "on" : "off");\n}\n',
   '                RtGlassCarryOn() ? "on" : "off", RtGlassOn() ? "on" : "off");\n'
   '    // bbport (r86j_glint-same-game): the line the slot runner keeps\n'
   '    std::printf("GLINT-PROOF glint made: %s, start strength %.2f, live setting BB_GLASS_GLINT %s\\n",\n'
   '                made ? "yes" : "no (the passes could not be made)", double(knobs.strength),\n'
   '                BB_GLINT_LIVE ? "read again every frame (the test tools\' live knobs)" : "read once");\n}\n'),
  ("                                const BG::PaneDraw& pane) {\n    ++stats.glass_draws;\n",
   "                                const BG::PaneDraw& pane) {\n"
   "    // bbport (r86j_glint-same-game): the live switch first; off: a counter and nothing else\n"
   "    const float live = LiveStrength(knobs);\n"
   "    if (!(live != 0.0f)) {\n"
   "        ++stats.gate_off;\n"
   "        return;\n"
   "    }\n"
   "    ++stats.glass_draws;\n"),
  ("    push.info = {blocks_x, blocks_y, slot, knobs.show ? BG::FlagShow : 0u};\n"
   "    push.params = {knobs.strength, float(knobs.sharp), BG::Normalisation(float(knobs.sharp)), 0.0f};\n",
   "    push.info = {blocks_x, blocks_y, slot, live < 0.0f ? BG::FlagShow : 0u}; // bbport (r86j): the live value\n"
   "    push.params = {live < 0.0f ? -live : live, float(knobs.sharp), BG::Normalisation(float(knobs.sharp)), 0.0f};\n"),
  ("void GlassGlint::OnFrameEnd() {\n    frame_passes = 0;\n",
   "void GlassGlint::OnFrameEnd() {\n"
   "    // bbport (r86j_glint-same-game): a change of the live setting: what the old setting did, then the new one\n"
   "    if (const float live = LiveStrength(knobs); live != gate_last) {\n"
   "        if (gate_last != -2.0f && stats.frames > 0) {\n"
   "            Report();\n"
   "        }\n"
   "        std::printf(\"GLINT-PROOF gate: BB_GLASS_GLINT now %s (strength %.2f) at frame %llu\\n\",\n"
   "                    live < 0.0f ? \"show\" : live > 0.0f ? \"on\" : \"off\", double(live < 0.0f ? -live : live),\n"
   "                    static_cast<unsigned long long>(BbStats::frame_number.load(std::memory_order_relaxed)));\n"
   "        gate_last = live;\n"
   "    }\n"
   "    frame_passes = 0;\n"),
  ("    PrintSamples(static_cast<const u32*>(counters.mapped), passes);\n    stats = {};\n",
   "    // bbport (r86j_glint-same-game): the line the slot runner keeps, the chain's last link in one place\n"
   "    std::printf(\"GLINT-PROOF glint: %u frames, %u pane draws asked, %u of them while the setting was off, %u passes (skipped %u no pane, %u other camera, %u no lamps, %u lamps open, %u shape, %u cap); a pass: pane points %.0f (%.2f m away), glass px %.0f, lamp pairs in reach %.0f, facing %.0f, glint px %.0f, max add %.2f, lamps %.1f\\n\",\n"
   "                stats.frames, stats.glass_draws, stats.gate_off, stats.passes, stats.no_pane, stats.other_camera,\n"
   "                stats.no_lamps, stats.lamps_open, stats.shape, stats.cap, per(GLASS_GLINT_W_UNITS),\n"
   "                double(stats.words[GLASS_GLINT_W_T_SUM]) / units * 0.01, per(GLASS_GLINT_W_GLASS),\n"
   "                per(GLASS_GLINT_W_PAIRS), per(GLASS_GLINT_W_FACING), per(GLASS_GLINT_W_GLINT), double(stats.max_add),\n"
   "                double(stats.lamps) / std::max(1.0, double(stats.passes)));\n"
   "    PrintSamples(static_cast<const u32*>(counters.mapped), passes);\n    stats = {};\n"),
 ],
 V + "vk_rt_shadow.cpp": [
  ("void RtShadow::GlassFindBox() {\n#if BB_GLASS_STATIC_LIVE\n    const u32 generation = BbLiveKnobs::Generation();\n",
   "void RtShadow::GlassFindBox() {\n"
   "    // bbport (r86j_glint-same-game): BB_GLASS_BOX_PANES asked again with the live knobs (a job's set:), else once\n"
   "#if BB_GLASS_STATIC_LIVE\n"
   "    static BbLiveKnobs::Knob<bool> take_knob{\"BB_GLASS_BOX_PANES\", [](const char* text) {\n"
   "                                                 return text != nullptr && text[0] == '1' && text[1] == '\\0';\n"
   "                                             }};\n"
   "    const bool take = take_knob.Get();\n"
   "#else\n"
   "    const bool take = RtGlassFind::BoxPanes();\n"
   "#endif\n"
   "#if BB_GLASS_STATIC_LIVE\n    const u32 generation = BbLiveKnobs::Generation();\n"),
  ("        if (box.valid != glass_box_valid ||\n",
   "        if (!take || box.valid != glass_box_valid || // bbport (r86j): panes switched off: the keys go\n"),
  ('            std::printf("Ray tracing glass find (r86i): BB_GLASS_FIND_BOX %d,%d-%d,%d of the 1920x1080',
   '            std::printf("GLINT-PROOF box set: BB_GLASS_FIND_BOX %d,%d-%d,%d of the 1920x1080'),
  ('            std::printf("Ray tracing glass find (r86i): BB_GLASS_FIND_BOX \'%s\' is not x0:y0:x1:y1',
   '            std::printf("GLINT-PROOF box set: BB_GLASS_FIND_BOX \'%s\' is not x0:y0:x1:y1'),
  ('        std::printf("Ray tracing glass find (r86i): box at frame %llu: no camera pass matrices yet\\n",',
   '        std::printf("GLINT-PROOF box at frame %llu: no camera pass matrices yet\\n",'),
  ("    static const bool take = RtGlassFind::BoxPanes();\n    static const float size_max",
   "    // bbport (r86j_glint-same-game): `take` is read at the top of the function (live)\n    static const float size_max"),
  ("    if (!glass_box_valid) {\n        return;\n    }\n    if (!RtGlassFind::ReportFrame(frame) && !(glass_box_due != 0",
   "    // bbport (r86j_glint-same-game): every 300 frames, once the box is set or a box pane was drawn: the chain\n"
   "    {\n"
   "        static u64 chain_last = 0;\n"
   "        RtGlassFind::BoxChain& chain = RtGlassFind::Chain();\n"
   "        const auto load_of = [](const std::atomic<std::uint64_t>& v) {\n"
   "            return static_cast<unsigned long long>(v.load(std::memory_order_relaxed));\n"
   "        };\n"
   "        if ((glass_box_valid || load_of(chain.matched) != 0) && frame / 300 != chain_last / 300) {\n"
   "            chain_last = frame;\n"
   "            std::printf(\"GLINT-PROOF chain at frame %llu: box %s, mesh keys %u | G-buffer draws of those meshes %llu: pane record made %llu, none made %llu | camera pass draws without camera constants %llu | glint noted %llu, run after the blended draws %llu, at the fog composite %llu (all since the start)\\n\",\n"
   "                        static_cast<unsigned long long>(frame), glass_box_valid ? \"set\" : \"not set\", glass_box_count,\n"
   "                        load_of(chain.matched), load_of(chain.recorded), load_of(chain.not_recorded),\n"
   "                        load_of(chain.no_constants), load_of(chain.noted), load_of(chain.after_blended),\n"
   "                        load_of(chain.after_composite));\n"
   "        }\n"
   "    }\n"
   "    if (!glass_box_valid) {\n        return;\n    }\n    if (!RtGlassFind::ReportFrame(frame) && !(glass_box_due != 0"),
  ('    std::printf("Ray tracing glass find (r86i): box %d,%d-%d,%d at frame %llu: %zu entries overlap it, %u of them mostly inside and under %.2f m across (%s); of %u entries the camera pass drew in the last %u frames, %u have bounds, %u of those are behind or at the camera; mesh keys taken %u (+%u)\\n",\n                picture.x0, picture.y0, picture.x1, picture.y1, static_cast<unsigned long long>(frame),\n                rows.size(), small_inside, size_max, take ? "BB_GLASS_BOX_PANES takes them" : "BB_GLASS_BOX_PANES off: log only",\n                drawn, StillNearFrames, bounded, behind, glass_box_count, taken_now);\n    for (std::size_t n = 0; n < rows.size() && n < 24; ++n) {\n',
   '    std::printf("GLINT-PROOF box %d,%d-%d,%d at frame %llu: mesh keys taken %u (+%u), %zu entries overlap it, %u of them mostly inside and under %.2f m across (%s); the scene holds %zu entries in all, the camera pass drew %u of them in the last %u frames, %u have bounds, %u of those are behind or at the camera; camera pass draws left out for no camera constants %llu so far\\n",\n                picture.x0, picture.y0, picture.x1, picture.y1, static_cast<unsigned long long>(frame),\n                glass_box_count, taken_now, rows.size(), small_inside, size_max,\n                take ? "BB_GLASS_BOX_PANES takes them" : "BB_GLASS_BOX_PANES off: log only", entries.size(), drawn,\n                StillNearFrames, bounded, behind,\n                static_cast<unsigned long long>(RtGlassFind::Chain().no_constants.load(std::memory_order_relaxed)));\n    // bbport (r86j): the report a new box asked for lists 12 entries, the periodic ones 3 (the log keeps few)\n    for (std::size_t n = 0; n < rows.size() && n < (due_report ? std::size_t{12} : std::size_t{3}); ++n) {\n'),
  ("    glass_box_due = 0;\n    const auto camera = camera_motion.PassMatrices();\n",
   "    const bool due_report = glass_box_due != 0 && frame >= glass_box_due; // bbport (r86j_glint-same-game)\n"
   "    glass_box_due = 0;\n    const auto camera = camera_motion.PassMatrices();\n"),
  ('        std::printf("Ray tracing glass find (r86i): box entry %llx:%llx key',
   '        std::printf("GLINT-PROOF box entry %llx:%llx key'),
  ("        ++stats.no_camera;\n        return 0;\n    }\n    if (draw.glass) { // bbport (r83b_glass-pane-probe): a pane draw had the camera constants\n",
   "        ++stats.no_camera;\n"
   "        if (draw.camera_pass && RtGlassFind::On()) { // bbport (r86j_glint-same-game): the bottles may be here\n"
   "            RtGlassFind::Chain().no_constants.fetch_add(1, std::memory_order_relaxed);\n"
   "        }\n"
   "        return 0;\n    }\n    if (draw.glass) { // bbport (r83b_glass-pane-probe): a pane draw had the camera constants\n"),
 ],
 V + "vk_rasterizer_effects.cpp": [
  ("    const bool box_pane = draw.camera_pass && ps && RtGlassOn() && rt_shadow->GlassBoxMatch(draw);\n",
   "    const bool box_pane = draw.camera_pass && ps && RtGlassOn() && rt_shadow->GlassBoxMatch(draw);\n"
   "    u32 box_notes = 0; // bbport (r86j_glint-same-game): the pane records counted before PrepareDraw\n"
   "    if (box_pane) {\n"
   "        RtGlassFind::Chain().matched.fetch_add(1, std::memory_order_relaxed);\n"
   "        box_notes = RtGlassProbe::Get().counts[RtGlassProbe::Note].load(std::memory_order_relaxed);\n"
   "    }\n"),
  ("                glint_gpane_on = true;\n            }\n",
   "                glint_gpane_on = true;\n"
   "                RtGlassFind::Chain().noted.fetch_add(1, std::memory_order_relaxed); // bbport (r86j)\n"
   "            }\n"),
  ("    const u32 param = rt_shadow->PrepareDraw(draw);\n    prepare_scope.End();\n",
   "    const u32 param = rt_shadow->PrepareDraw(draw);\n    prepare_scope.End();\n"
   "    if (box_pane) { // bbport (r86j_glint-same-game): did the box pane get its record\n"
   "        const bool made = RtGlassProbe::Get().counts[RtGlassProbe::Note].load(std::memory_order_relaxed) != box_notes;\n"
   "        (made ? RtGlassFind::Chain().recorded : RtGlassFind::Chain().not_recorded)\n"
   "            .fetch_add(1, std::memory_order_relaxed);\n"
   "    }\n"),
  ("        glint_gpane_on = false;\n"
   "        glass_glint->AfterGlassDraw(cb_descs[0].first, db_desc.first, upscaler->Jitter(), point_shadow->Pending(),\n"
   "                                    glint_gpane);\n"
   "    }\n}\n",
   "        glint_gpane_on = false;\n"
   "        RtGlassFind::Chain().after_blended.fetch_add(1, std::memory_order_relaxed); // bbport (r86j)\n"
   "        glass_glint->AfterGlassDraw(cb_descs[0].first, db_desc.first, upscaler->Jitter(), point_shadow->Pending(),\n"
   "                                    glint_gpane);\n"
   "    }\n}\n"),
  ("void Rasterizer::EffectsSceneComposite(const GraphicsPipeline* pipeline) {\n",
   "void Rasterizer::EffectsSceneComposite(const GraphicsPipeline* pipeline) {\n"
   "    // bbport (r86j_glint-same-game): no blended draw came after the pane's G-buffer draw: its glint runs here\n"
   "    // (still over the lit scene, under the drawn look's strokes). Off: one bool.\n"
   "    if (glass_glint && glint_gpane_on) {\n"
   "        glint_gpane_on = false;\n"
   "        RtGlassFind::Chain().after_composite.fetch_add(1, std::memory_order_relaxed);\n"
   "        glass_glint->AfterGlassDraw(cb_descs[0].first, db_desc.first, upscaler->Jitter(), point_shadow->Pending(),\n"
   "                                    glint_gpane);\n"
   "    }\n"),
 ],
 "README.md": [
  ("Nothing is taken while no box is set. |",
   "Nothing is taken while no box is set. With the test tools' live knobs a job's `set:BB_GLASS_BOX_PANES=0|1` and `set:BB_GLASS_GLINT=0|1|show` work while the game runs (r86j; the glint's pipelines are made at the start, so `BB_GLASS_GLINT` must be above 0 in the environment, and `set:BB_GLASS_GLINT=0` is then the switch): one game can have the glass off, then a box and the glint, then the test view, then no box, at one camera. The log lines starting `GLINT-PROOF` are the ones the slot runner keeps: the box set line, the box report (`mesh keys taken N`, also for 0), the best box entries, a `chain` line every 300 frames (G-buffer draws of the taken meshes, pane records made or not, glint noted and run), a `gate` line at each change of the glint setting and a `glint` line with the pass counts (pane points, glint pixels). |"),
 ],
 "engine/tests/test_rt_glass.cpp": [
  ("        RtGlassFind::AreaReport(300); // prints, starts a new window\n"
   "        assert(area.rows[0].draws == 0 && area.last_frame == 300);\n"
   "    }\n",
   "        RtGlassFind::AreaReport(300); // prints, starts a new window\n"
   "        assert(area.rows[0].draws == 0 && area.last_frame == 300);\n"
   "    }\n"
   "    // bbport (r86j_glint-same-game): the chain's counters start at 0 and count\n"
   "    {\n"
   "        RtGlassFind::BoxChain& chain = RtGlassFind::Chain();\n"
   "        assert(chain.matched.load() == 0 && chain.no_constants.load() == 0 && chain.after_composite.load() == 0);\n"
   "        chain.matched.fetch_add(2, std::memory_order_relaxed);\n"
   "        chain.recorded.fetch_add(1, std::memory_order_relaxed);\n"
   "        chain.not_recorded.fetch_add(1, std::memory_order_relaxed);\n"
   "        assert(chain.matched.load() == chain.recorded.load() + chain.not_recorded.load());\n"
   "    }\n"),
 ],
 "engine/tests/test_glass_glint.cpp": [
  ('    assert(Parse("show", nullptr).strength == 1.0f && Parse("show", nullptr).show);\n',
   '    assert(Parse("show", nullptr).strength == 1.0f && Parse("show", nullptr).show);\n'
   "    // bbport (r86j_glint-same-game): the live setting: 0 off, strength on, negative for the test view\n"
   '    assert(ParseLive(nullptr) == 0.0f && ParseLive("") == 0.0f && ParseLive("0") == 0.0f && ParseLive("x") == 0.0f);\n'
   '    assert(ParseLive("1") == 1.0f && ParseLive("2.5") == 2.5f && ParseLive("show") == -1.0f);\n'
   '    assert(ParseLive("9") == MaxStrength && ParseLive("0.1") == MinStrength);\n'),
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
