# r86k_glint-box-gbuffer: FEATURE fix (glass, r83 chain; on top of r86j, r86i, r86h, r86g, r86f, r86e, r86d, r86c, r86b, r83c, r83b, r83).
#
# Why (b52, 2026-11-16, gsg-dh): the box was set on the jars of the right-hand cabinet and every "box at frame" line said
# "no camera pass matrices yet"; the chain read mesh keys 0 / G-buffer draws 0 / glint 0 px.
#  CAUSE 1 (found by reading): RtShadow::GlassFindBox runs from OnFrameEnd, which the rasterizer calls AFTER
#   CameraMotion::OnDisplayPass; OnDisplayPass commits the frame's camera (current = pass_camera) and then sets
#   pass_has_camera = false, so PassMatrices().valid is false at every frame end. The box listing could never run.
#  CAUSE 2 (found by reading): PrepareDraw returns at once for a camera pass draw with a discard and no skeleton or
#   palette (stats.alpha) and for one that is not solid (blended, no depth write): such a draw never becomes an entry of
#   the ray traced scene, so the box listing (which lists entries) cannot see it and the box rule cannot take its mesh.
#   (b28f5a56:765450df is a forward pair of the find table with a discard, 96-600 indices: possibly dust, not jars; this
#   patch logs whether it is in the box.)
#
# What this does (all behind BB_GLASS_FIND=1 / BB_GLASS_BOX_PANES, a TEST path; off costs nothing, see below):
#  1. CAMERA. GlassFindBox uses the frame's committed camera (CameraMotion::CameraMatrices(): the last G-buffer pass's
#     view and projection, the ones the pass had) when the pass camera is closed. A once-line says so.
#  2. PROBE ENTRIES. With a box set and BB_GLASS_BOX_PANES on (live too), a G-buffer (camera pass) draw that PrepareDraw
#     would leave out (a discard, or blended / no depth write), with no skeleton or palette, 24 to 3000 indices, gets an
#     entry anyway, as a window pane (Draw::glass, the r83 path: its own key, RtGlassMask alone, so no sun or lamp
#     shadow caster is added), at most 48 such draws a frame, never one whose mesh was judged outside the box. The entry's
#     bounds come from the capture as for every entry; the box listing treats such an entry like a solid one: mostly
#     inside the box, small, 8 triangles: its mesh key is taken, and later draws of it are box panes (r86i/r86j chain,
#     with discard and blend allowed: the pane draw is solid and whole). Entries judged outside the box (bounds known,
#     in front of the camera, not overlapping or not taken) are remembered (128 keys) and are not probed again until the
#     box or BB_GLASS_BOX_PANES changes.
#  3. LISTING. The "box entry" lines (12 on a new box, 3 later) gain the draw's index count and blend / zwrite / nozwrite /
#     discard and "probe entry" for a probe. A new "box pair" line (BB_GLASS_BOX_PAIR=vs:ps in hex, e.g. b28f5a56:765450df)
#     says how many G-buffer draws of that pair the hook saw, how many of its entries have bounds, are in front of the
#     camera, overlap the box, are mostly inside it, and the rects of the first four: "is that pair in the box".
#     A second chain line says how many probe entries were made.
# Off: BB_GLASS_FIND unset: the hook block is behind the static bool glass_find (the same one that guards the r86g/r86i
# blocks); GlassBoxCandidate is not called; the Draw gets two default fields; the Entry assignments sit in the
# `if (draw.camera_pass && RtGlassFind::On())` block of r86i. BB_GLASS_FIND=1 without a box: GlassBoxCandidate returns at
# its first test (glass_box_valid). No shader touched, no allocation beyond 128 u64 and a few counters.
# Files: rt_glass_find.h, vk_rt_shadow.h, vk_rt_shadow.cpp, vk_rasterizer_effects.cpp, README.md, tests/test_rt_glass.cpp.
# Use: python -I -X utf8 r86k_glint-box-gbuffer.py check | apply | revert
# Root: R86K_ROOT else <tree>. Line ends kept per file. Backups in r86k_backup next to this script.
import os, sys, io

ROOT = os.environ.get("R86K_ROOT") or "<tree>"
BK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r86k_backup")
V = "engine/gpu/shadps4/video_core/renderer_vulkan/"

E = {
 V + "rt_glass_find.h": [
  ("    std::atomic<std::uint64_t> after_composite{0}; ///< ... at the fog composite, when no blended draw came first\n};\n",
   "    std::atomic<std::uint64_t> after_composite{0}; ///< ... at the fog composite, when no blended draw came first\n"
   "    std::atomic<std::uint64_t> probes{0};          ///< (r86k) G-buffer draws made probe entries (left out by PrepareDraw)\n"
   "    std::atomic<std::uint64_t> pair_draws{0};      ///< (r86k) G-buffer draws of the BB_GLASS_BOX_PAIR pair seen with a box set\n};\n"),
  ("inline BoxChain& Chain() {\n    static BoxChain chain;\n    return chain;\n}\n",
   r'''inline BoxChain& Chain() {
    static BoxChain chain;
    return chain;
}

// ---- bbport (r86k_glint-box-gbuffer) ----------------------------------------------------------------------
/// BB_GLASS_BOX_PAIR=vs:ps (both hex, as the find lines print them): the shader pair the box report says
/// something of. Not set: `set` false.
struct BoxPairSpec {
    std::uint64_t vs = 0, ps = 0;
    bool set = false;
};

constexpr int HexDigitOf(char c) {
    return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}

constexpr BoxPairSpec ParseBoxPair(const char* text) {
    BoxPairSpec none;
    if (text == nullptr) {
        return none;
    }
    std::uint64_t a = 0, b = 0;
    int digits_a = 0, digits_b = 0;
    const char* p = text;
    for (; *p != '\0' && *p != ':'; ++p) {
        const int d = HexDigitOf(*p);
        if (d < 0 || ++digits_a > 16) {
            return none;
        }
        a = (a << 4) | std::uint64_t(d);
    }
    if (*p != ':' || digits_a == 0) {
        return none;
    }
    for (++p; *p != '\0'; ++p) {
        const int d = HexDigitOf(*p);
        if (d < 0 || ++digits_b > 16) {
            return none;
        }
        b = (b << 4) | std::uint64_t(d);
    }
    if (digits_b == 0) {
        return none;
    }
    BoxPairSpec spec;
    spec.vs = a;
    spec.ps = b;
    spec.set = true;
    return spec;
}
'''),
 ],
 V + "vk_rt_shadow.h": [
  ("        bool glass = false;\n    };\n    u32 PrepareDraw(const Draw& draw);\n",
   "        bool glass = false;\n"
   "        // bbport (r86k_glint-box-gbuffer): BB_GLASS_FIND=1 with a box set: a G-buffer draw PrepareDraw would leave\n"
   "        // out (a discard, blended) given an entry as a pane to see whether the box holds it (EffectsCaptureDraw sets\n"
   "        // it with `glass`); and the draw's blend / depth write / discard as RtGlassFind::Flag* bits (find only)\n"
   "        bool box_candidate = false;\n"
   "        u32 find_flags = 0;\n"
   "    };\n    u32 PrepareDraw(const Draw& draw);\n"),
  ("    [[nodiscard]] bool GlassBoxMatch(const Draw& draw) const;\n",
   "    [[nodiscard]] bool GlassBoxMatch(const Draw& draw) const;\n"
   "    // bbport (r86k_glint-box-gbuffer): BB_GLASS_FIND=1: whether this G-buffer draw (`left_out`: PrepareDraw would\n"
   "    // give it no entry: a discard or not solid) is made a probe entry so the box listing can see it (see the patch\n"
   "    // header). Counts per frame; false at once while no box is set or BB_GLASS_BOX_PANES is off.\n"
   "    [[nodiscard]] bool GlassBoxCandidate(const Draw& draw, u64 vs, u64 ps, bool left_out);\n"),
  ("        u64 find_vs = 0, find_ps = 0;\n",
   "        u64 find_vs = 0, find_ps = 0;\n"
   "        // bbport (r86k_glint-box-gbuffer): the last draw's index count and RtGlassFind::Flag* bits; a probe entry\n"
   "        u32 find_indices = 0, find_flags = 0;\n"
   "        bool box_candidate = false;\n"),
  ("    std::array<u64, 64> glass_box_keys{};\n    u32 glass_box_count = 0;\n",
   "    std::array<u64, 64> glass_box_keys{};\n    u32 glass_box_count = 0;\n"
   "    // bbport (r86k_glint-box-gbuffer): BB_GLASS_BOX_PANES as the last listing read it, the probe entries made in\n"
   "    // the frame `glass_cand_frame`, and the keys of probe meshes judged outside the box\n"
   "    bool glass_box_take = false;\n"
   "    u64 glass_cand_frame = 0;\n"
   "    u32 glass_cand_used = 0;\n"
   "    std::array<u64, 128> glass_box_rejected{};\n"
   "    u32 glass_box_rejected_count = 0;\n"),
 ],
 V + "vk_rt_shadow.cpp": [
  # GlassBoxCandidate + the pair spec, before GlassFindBox's comment
  ("// bbport (r86i_glint-find-gbuffer): see the declaration. The entries are those of the ray traced scene (solid\n",
   r'''// bbport (r86k_glint-box-gbuffer): BB_GLASS_BOX_PAIR, read once.
static const RtGlassFind::BoxPairSpec& BoxPairOfEnv() {
    static const RtGlassFind::BoxPairSpec spec = RtGlassFind::ParseBoxPair(std::getenv("BB_GLASS_BOX_PAIR"));
    return spec;
}

constexpr u32 GlassCandidatesMost = 48; // bbport (r86k): probe entries a frame

// bbport (r86k_glint-box-gbuffer): see the declaration.
bool RtShadow::GlassBoxCandidate(const Draw& draw, u64 vs, u64 ps, bool left_out) {
    if (!glass_box_valid || !glass_box_take) {
        return false;
    }
    const RtGlassFind::BoxPairSpec& pair = BoxPairOfEnv();
    if (pair.set && vs == pair.vs && ps == pair.ps) {
        RtGlassFind::Chain().pair_draws.fetch_add(1, std::memory_order_relaxed);
    }
    if (!left_out || draw.skinned || draw.palette != 0 || draw.positions == 0 || draw.index_count < 24 ||
        draw.index_count > 3000) {
        return false;
    }
    if (frame != glass_cand_frame) {
        glass_cand_frame = frame;
        glass_cand_used = 0;
    }
    if (glass_cand_used >= GlassCandidatesMost) {
        return false;
    }
    const std::array<u64, 4> parts{draw.positions, draw.indices,
                                   (u64(draw.index_count) << 32) | draw.first_vertex, draw.instances};
    const u64 key = XXH3_64bits(parts.data(), sizeof(parts));
    for (u32 i = 0; i < glass_box_count; ++i) {
        if (glass_box_keys[i] == key) {
            return false; // taken: GlassBoxMatch makes it a box pane
        }
    }
    for (u32 i = 0; i < glass_box_rejected_count; ++i) {
        if (glass_box_rejected[i] == key) {
            return false;
        }
    }
    ++glass_cand_used;
    RtGlassFind::Chain().probes.fetch_add(1, std::memory_order_relaxed);
    return true;
}

// bbport (r86i_glint-find-gbuffer): see the declaration. The entries are those of the ray traced scene (solid
'''),
  ("    const bool take = RtGlassFind::BoxPanes();\n#endif\n",
   "    const bool take = RtGlassFind::BoxPanes();\n#endif\n"
   "    glass_box_take = take; // bbport (r86k_glint-box-gbuffer): GlassBoxCandidate reads it\n"),
  ("            glass_box_count = 0;\n        }\n        glass_box_valid = box.valid;\n",
   "            glass_box_count = 0;\n"
   "            glass_box_rejected_count = 0; // bbport (r86k_glint-box-gbuffer)\n"
   "        }\n        glass_box_valid = box.valid;\n"),
  ("                        load_of(chain.after_composite));\n",
   "                        load_of(chain.after_composite));\n"
   "            // bbport (r86k_glint-box-gbuffer): the probe entries\n"
   '            std::printf("GLINT-PROOF chain probes at frame %llu: G-buffer draws made probe entries %llu (a cut-out or not solid, which PrepareDraw gives no entry; at most %u a frame), probe meshes judged outside the box %u; draws of the BB_GLASS_BOX_PAIR pair seen with a box set %llu (all since the start)\\n",\n'
   "                        static_cast<unsigned long long>(frame), load_of(chain.probes), GlassCandidatesMost,\n"
   "                        glass_box_rejected_count, load_of(chain.pair_draws));\n"),
  ("    glass_box_due = 0;\n    const auto camera = camera_motion.PassMatrices();\n    if (!camera.valid) {\n"
   '        std::printf("GLINT-PROOF box at frame %llu: no camera pass matrices yet\\n",\n'
   "                    static_cast<unsigned long long>(frame));\n        return;\n    }\n",
   "    glass_box_due = 0;\n"
   "    // bbport (r86k_glint-box-gbuffer): this runs at the frame end, after CameraMotion::OnDisplayPass committed the\n"
   "    // frame's camera and closed the pass camera (pass_has_camera false): PassMatrices() was never valid here (b52:\n"
   '    // "no camera pass matrices yet" at every report). The committed camera is the last G-buffer pass\'s: the view and\n'
   "    // projection the pass had.\n"
   "    auto camera = camera_motion.PassMatrices();\n"
   "    bool committed_camera = false;\n"
   "    if (!camera.valid) {\n"
   "        camera = camera_motion.CameraMatrices();\n"
   "        camera.valid = camera.proj[0] != 0.0f && camera.proj[1] != 0.0f && std::isfinite(camera.proj[0]) &&\n"
   "                       std::isfinite(camera.proj[1]) &&\n"
   "                       std::ranges::all_of(camera.view, [](float v) { return std::isfinite(v); });\n"
   "        committed_camera = camera.valid;\n"
   "    }\n"
   "    if (!camera.valid) {\n"
   '        std::printf("GLINT-PROOF box at frame %llu: no camera matrices yet (the scene holds %zu entries)\\n",\n'
   "                    static_cast<unsigned long long>(frame), entries.size());\n        return;\n    }\n"
   "    static bool committed_said = false;\n"
   "    if (committed_camera && !committed_said) {\n"
   "        committed_said = true;\n"
   '        std::printf("GLINT-PROOF box camera: the pass camera is closed at the frame end (r86j read it there: never valid); the frame\'s committed camera is used, from frame %llu\\n",\n'
   "                    static_cast<unsigned long long>(frame));\n"
   "    }\n"),
  ("    std::vector<Row> rows;\n    u32 drawn = 0, bounded = 0, behind = 0;\n",
   "    std::vector<Row> rows;\n    u32 drawn = 0, bounded = 0, behind = 0;\n"
   "    // bbport (r86k_glint-box-gbuffer): a probe mesh seen outside the box is not probed again; the pair the\n"
   "    // report says something of (BB_GLASS_BOX_PAIR)\n"
   "    const auto reject = [&](const Entry& e) {\n"
   "        const u64 key = RtGlassKey(e.base); // a probe entry is a glass entry: its base carries the salt\n"
   "        for (u32 i = 0; i < glass_box_rejected_count; ++i) {\n"
   "            if (glass_box_rejected[i] == key) {\n"
   "                return;\n"
   "            }\n"
   "        }\n"
   "        if (glass_box_rejected_count < glass_box_rejected.size()) {\n"
   "            glass_box_rejected[glass_box_rejected_count++] = key;\n"
   "        }\n"
   "    };\n"
   "    const RtGlassFind::BoxPairSpec& pair = BoxPairOfEnv();\n"
   "    u32 pair_drawn = 0, pair_bounded = 0, pair_front = 0, pair_overlap = 0, pair_inside = 0, pair_shown = 0;\n"
   "    std::array<RtGlassFind::BoxHit, 4> pair_hit{};\n"
   "    std::array<float, 4> pair_diag{};\n"),
  ("        ++drawn;\n        const std::array<float, 6>* bounds = e->still_has_ref[0]",
   "        ++drawn;\n"
   "        const bool pair_entry = pair.set && e->find_vs == pair.vs && e->find_ps == pair.ps; // bbport (r86k)\n"
   "        pair_drawn += pair_entry ? 1u : 0u;\n"
   "        const std::array<float, 6>* bounds = e->still_has_ref[0]"),
  ("        const RtGlassFind::BoxHit hit = RtGlassFind::BoxOfBounds(camera.view, camera.proj, *bounds, picture);\n"
   "        if (!hit.seen) {\n",
   "        const RtGlassFind::BoxHit hit = RtGlassFind::BoxOfBounds(camera.view, camera.proj, *bounds, picture);\n"
   "        if (pair_entry) { // bbport (r86k_glint-box-gbuffer)\n"
   "            ++pair_bounded;\n"
   "            if (hit.seen) {\n"
   "                ++pair_front;\n"
   "                pair_overlap += hit.inside > 0.0f ? 1u : 0u;\n"
   "                pair_inside += hit.inside >= 0.6f ? 1u : 0u;\n"
   "                if (pair_shown < pair_hit.size()) {\n"
   "                    pair_hit[pair_shown] = hit;\n"
   "                    pair_diag[pair_shown++] = std::sqrt(((*bounds)[3] - (*bounds)[0]) * ((*bounds)[3] - (*bounds)[0]) +\n"
   "                                                       ((*bounds)[4] - (*bounds)[1]) * ((*bounds)[4] - (*bounds)[1]) +\n"
   "                                                       ((*bounds)[5] - (*bounds)[2]) * ((*bounds)[5] - (*bounds)[2]));\n"
   "                }\n"
   "            }\n"
   "        }\n"
   "        if (!hit.seen) {\n"),
  ("        if (!(hit.inside > 0.0f)) {\n            continue;\n        }\n        const float dx",
   "        if (!(hit.inside > 0.0f)) {\n"
   "            if (e->box_candidate && take) { // bbport (r86k_glint-box-gbuffer): seen, bounds known, outside the box\n"
   "                reject(*e);\n"
   "            }\n"
   "            continue;\n        }\n        const float dx"),
  ("        float diagonal;\n        bool pane;\n    };\n",
   "        float diagonal;\n        bool pane;\n        bool cand; // bbport (r86k_glint-box-gbuffer): a probe entry\n    };\n"),
  ("        rows.push_back({e, bounds, hit, std::sqrt(dx * dx + dy * dy + dz * dz), (e->mask & RtGlassMask) != 0});\n",
   "        rows.push_back({e, bounds, hit, std::sqrt(dx * dx + dy * dy + dz * dz), (e->mask & RtGlassMask) != 0,\n"
   "                        e->box_candidate});\n"),
  ("        if (r.pane || !RtGlassFind::BoxTakes(r.hit, r.diagonal, size_max, r.entry->triangles)) {\n            continue;\n        }\n",
   "        if ((r.pane && !r.cand) || !RtGlassFind::BoxTakes(r.hit, r.diagonal, size_max, r.entry->triangles)) {\n"
   "            if (r.cand && take) { // bbport (r86k_glint-box-gbuffer): a probe mesh the box rule does not take\n"
   "                reject(*r.entry);\n"
   "            }\n"
   "            continue;\n        }\n"),
  # the key of a taken glass entry is the plain position key
  ("        bool known = false;\n        for (u32 i = 0; i < glass_box_count; ++i) {\n            known = known || glass_box_keys[i] == r.entry->base;\n        }\n"
   "        if (!known && glass_box_count < glass_box_keys.size()) {\n            glass_box_keys[glass_box_count++] = r.entry->base;\n",
   "        // bbport (r86k_glint-box-gbuffer): a probe entry is a glass entry (its base has RtGlassKey's salt); the\n"
   "        // box keys are the plain position keys GlassBoxMatch makes of a draw\n"
   "        const u64 take_key = r.cand ? RtGlassKey(r.entry->base) : r.entry->base;\n"
   "        bool known = false;\n        for (u32 i = 0; i < glass_box_count; ++i) {\n            known = known || glass_box_keys[i] == take_key;\n        }\n"
   "        if (!known && glass_box_count < glass_box_keys.size()) {\n            glass_box_keys[glass_box_count++] = take_key;\n"),
  ("%u triangles %u vertices %u instances%s%s%s%s\\n\",",
   "%u triangles %u vertices %u instances%s%s%s%s | draw: %u indices%s%s%s%s\\n\","),
  ('                    e.shadow ? " sun pass too" : "", e.dynamic ? " moving" : "");\n    }\n}\n',
   '                    e.shadow ? " sun pass too" : "", e.dynamic ? " moving" : "", e.find_indices,\n'
   '                    (e.find_flags & RtGlassFind::FlagBlend) != 0 ? " blend" : "",\n'
   '                    (e.find_flags & RtGlassFind::FlagZWrite) != 0 ? " zwrite" : (e.find_flags & RtGlassFind::FlagNoZWrite) != 0 ? " nozwrite" : "",\n'
   '                    (e.find_flags & RtGlassFind::FlagDiscard) != 0 ? " discard" : "",\n'
   '                    e.box_candidate ? " (probe entry: PrepareDraw gives such a draw none)" : "");\n'
   "    }\n"
   "    // bbport (r86k_glint-box-gbuffer): is the BB_GLASS_BOX_PAIR pair in the box\n"
   "    if (pair.set) {\n"
   r'''        std::printf("GLINT-PROOF box pair %llx:%llx at frame %llu: G-buffer draws of it seen with a box set %llu; entries of it the camera pass drew in the last %u frames %u (%u with bounds, %u in front of the camera, %u overlap the box, %u mostly inside it)%s\n",
'''
   "                    static_cast<unsigned long long>(pair.vs), static_cast<unsigned long long>(pair.ps),\n"
   "                    static_cast<unsigned long long>(frame),\n"
   "                    static_cast<unsigned long long>(RtGlassFind::Chain().pair_draws.load(std::memory_order_relaxed)),\n"
   "                    StillNearFrames, pair_drawn, pair_bounded, pair_front, pair_overlap, pair_inside,\n"
   '                    pair_drawn == 0 ? " (no entry: the pair is not a solid G-buffer draw, or is blended, or is a forward draw)" : "");\n'
   "        for (u32 n = 0; n < pair_shown; ++n) {\n"
   r'''            std::printf("GLINT-PROOF box pair entry %u: rect %.0f,%.0f-%.0f,%.0f, %.0f%% inside the box, %.2f m across\n",
'''
   "                        n, pair_hit[n].x0, pair_hit[n].y0, pair_hit[n].x1, pair_hit[n].y1,\n"
   "                        double(pair_hit[n].inside) * 100.0, double(pair_diag[n]));\n"
   "        }\n"
   "    }\n}\n"),
  ("        entry.find_ps = draw.pixel_shader;\n",
   "        entry.find_ps = draw.pixel_shader;\n"
   "        entry.find_indices = draw.index_count; // bbport (r86k_glint-box-gbuffer)\n"
   "        entry.find_flags = draw.find_flags;\n"
   "        entry.box_candidate = entry.box_candidate || draw.box_candidate;\n"),
 ],
 V + "vk_rasterizer_effects.cpp": [
  ("    const bool box_pane = draw.camera_pass && ps && RtGlassOn() && rt_shadow->GlassBoxMatch(draw);\n",
   "    // bbport (r86k_glint-box-gbuffer): BB_GLASS_FIND=1 with a box set (RtShadow::GlassBoxCandidate): a G-buffer\n"
   "    // draw PrepareDraw would give no entry (a discard, blended or without depth write) is given one as a pane, so\n"
   "    // that the box listing sees it. Off: glass_find is false, nothing of this runs.\n"
   "    bool box_cand = false;\n"
   "    if (glass_find && draw.camera_pass && ps) {\n"
   "        draw.find_flags = RtGlassFind::FlagGBuffer | (regs.blend_control[0].enable ? RtGlassFind::FlagBlend : 0u) |\n"
   "                          (regs.depth_control.depth_write_enable != 0 ? RtGlassFind::FlagZWrite\n"
   "                                                                      : RtGlassFind::FlagNoZWrite) |\n"
   "                          (ps->has_discard ? RtGlassFind::FlagDiscard : 0u);\n"
   "        box_cand = RtGlassOn() && rt_shadow->GlassBoxCandidate(draw, vs.pgm_hash, ps->pgm_hash,\n"
   "                                                                draw.alpha || !draw.solid);\n"
   "    }\n"
   "    const bool box_pane = draw.camera_pass && ps && RtGlassOn() && rt_shadow->GlassBoxMatch(draw);\n"),
  ("    if (((!draw.camera_pass && !draw.shadow_pass) || box_pane) && RtGlassOn()) {\n",
   "    if (((!draw.camera_pass && !draw.shadow_pass) || box_pane || box_cand) && RtGlassOn()) {\n"),
  ("        if (ps && (RtGlassMatch(vs.pgm_hash, ps->pgm_hash) || glass_auto || box_pane) && !draw.skinned) {\n",
   "        if (ps && (RtGlassMatch(vs.pgm_hash, ps->pgm_hash) || glass_auto || box_pane || box_cand) && !draw.skinned) {\n"),
  ("            draw.solid = true;\n            draw.alpha = false;\n",
   "            draw.solid = true;\n            draw.alpha = false;\n"
   "            draw.box_candidate = box_cand; // bbport (r86k_glint-box-gbuffer)\n"),
  ("            glint_pending = glass_glint && !box_pane ? pipeline : nullptr; // bbport (r86b_glass-visible)\n",
   "            glint_pending = glass_glint && !box_pane && !box_cand ? pipeline : nullptr; // bbport (r86b_glass-visible; r86k)\n"),
 ],
 "README.md": [
  ("a `glint` line with the pass counts (pane points, glint pixels). |",
   "a `glint` line with the pass counts (pane points, glint pixels). r86k: the box listing now runs (it read the pass camera at the frame end, closed since the display pass; it uses the frame's committed camera), and with a box set and `BB_GLASS_BOX_PANES=1` a G-buffer draw with a discard or without solid output (which the scene gives no entry) is given a pane entry to be judged by the box rule; `BB_GLASS_BOX_PAIR=vs:ps` (hex) adds a `box pair` line saying whether that shader pair is in the box; the `box entry` lines name the draw's indices and blend / zwrite / discard. |"),
 ],
 "engine/tests/test_rt_glass.cpp": [
  ("        assert(chain.matched.load() == chain.recorded.load() + chain.not_recorded.load());\n    }\n",
   "        assert(chain.matched.load() == chain.recorded.load() + chain.not_recorded.load());\n    }\n"
   "    // bbport (r86k_glint-box-gbuffer): BB_GLASS_BOX_PAIR and the probe counters\n"
   "    {\n"
   '        constexpr RtGlassFind::BoxPairSpec pair = RtGlassFind::ParseBoxPair("b28f5a56:765450df");\n'
   "        static_assert(pair.set && pair.vs == 0xb28f5a56ull && pair.ps == 0x765450dfull);\n"
   '        static_assert(RtGlassFind::ParseBoxPair("1A:ff").set && RtGlassFind::ParseBoxPair("1A:ff").vs == 0x1a);\n'
   "        static_assert(!RtGlassFind::ParseBoxPair(nullptr).set && !RtGlassFind::ParseBoxPair(\"\").set);\n"
   '        static_assert(!RtGlassFind::ParseBoxPair("12").set && !RtGlassFind::ParseBoxPair("1:").set);\n'
   '        static_assert(!RtGlassFind::ParseBoxPair(":1").set && !RtGlassFind::ParseBoxPair("x:1").set);\n'
   '        static_assert(!RtGlassFind::ParseBoxPair("12345678901234567:1").set);\n'
   "        RtGlassFind::BoxChain& chain = RtGlassFind::Chain();\n"
   "        assert(chain.probes.load() == 0 && chain.pair_draws.load() == 0);\n"
   "        chain.probes.fetch_add(3, std::memory_order_relaxed);\n"
   "        assert(chain.probes.load() == 3);\n"
   "    }\n"),
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
                print("REFUSED", f, "anchor count", t.count(a), repr(a[:90])); sys.exit(1)
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
