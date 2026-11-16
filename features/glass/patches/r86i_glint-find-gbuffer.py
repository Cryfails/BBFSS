# r86i_glint-find-gbuffer: FEATURE fix (glass, r83 chain; on top of r86h, r86g, r86f, r86e, r86d, r86c, r86b, r83c, r83b, r83).
#
# Why (b46, 2026-11-16): r86h removed the "no camera" verdicts, but still 0 pairs fit the auto rule at the
# Hunter's Dream house: every in-frame blended pair is a 4-index quad or a 1-57 index draw without depth write
# (flares, light volumes, sprites); the depth-writing 30-2016 index pairs are the HUD, drawn after the frame.
# So the bottles and jars are NOT forward blended draws with depth write. They are G-buffer draws (solid or
# cut-out) with a glossy material, or blended draws without depth write. Nothing so far looked at the G-buffer.
#
# What this does:
#  1. AREA TABLE (BB_GLASS_FIND=1, log only): every other draw of the scene's frame (all G-buffer draws, and
#     forward draws that are not blended) is counted by its shader pair with the facts the glass search needs:
#     G-buffer or forward, blended, depth write / test, discard, textured, capture pipeline, index range,
#     instances, image count and whether the pixel shader reads a CUBE map (the material hint: the game's
#     glossy surfaces read the environment cube). Lines "Ray tracing glass find (r86i): area ..." at the find's
#     report frames: a header (G-buffer pairs, cut-outs, cube readers, forward unblended pairs) and up to 16
#     rows, cut-outs that read a cube map first.
#  2. BOX LINES (BB_GLASS_FIND=1 and BB_GLASS_FIND_BOX=x0:y0:x1:y1): the solid camera pass entries (the meshes
#     of the ray traced scene) whose world bounds project into a box of the 1920x1080 picture (the bottle
#     shelf, taken from the test picture; a live job action set:BB_GLASS_FIND_BOX=... works too and is
#     reported 90 frames later, when the camera has stopped). The bounds are the camera pass capture's
#     (BB_RT_STILL's first look), else the sun VSM's, else the sun pass's; projected with the pass camera
#     (CameraMotion::PassMatrices). One line per entry: its vertex:pixel shader pair (kept on the entry),
#     mesh key, share of its screen rectangle inside the box, size, triangles, instances. This is the "every
#     in-frame draw whose screen box overlaps the shelf" list for everything that has an entry; draws that never
#     become entries (cut-outs, blended) are the area table's.
#  3. BOX PANES (BB_GLASS_BOX_PANES=1, needs BB_RT_GLASS on, e.g. =auto): the entries of that report that lie
#     mostly (60 %) inside the box, are at most BB_GLASS_BOX_SIZE metres across (default 1.2) and have 8
#     triangles or more are taken BY MESH KEY (the position key PrepareDraw makes; at most 64 keys; a bottle
#     mesh is then a pane wherever the game draws it, a shelf or table that shares only the shader pair is not).
#     From then on a G-buffer draw of such a mesh (static, not skinned) is a window pane like a forward one
#     (draw.glass: its own entry under RtGlassMask), and the glint of its panes runs once a frame in
#     EffectsBlendedScene, over the lit scene, instead of right after the draw (a G-buffer draw's target 0 is
#     the normal target). The G-buffer draw itself is unchanged: the picture differs only by the glints.
# Off: BB_GLASS_FIND unset: the static bool tests as before; BB_RT_GLASS unset: RtGlassOn() is false before
# GlassBoxMatch is asked; the box keys are empty without BB_GLASS_BOX_PANES: GlassBoxMatch returns at its first
# test. No shader touched. Nothing is allocated; the area table is a static array (192 rows) behind a mutex that
# is taken only with the find on.
# Files: renderer_vulkan/rt_glass_find.h, vk_rt_shadow.h, vk_rt_shadow.cpp, vk_rasterizer.cpp, vk_rasterizer.h,
# vk_rasterizer_effects.cpp, README.md (3 rows), tests/test_rt_glass.cpp.
# Use: python -I -X utf8 r86i_glint-find-gbuffer.py check | apply | revert
# Root: R86I_ROOT else <tree>. Line ends kept per file. Backups in r86i_backup next to this script.
import os, sys, io

ROOT = os.environ.get("R86I_ROOT") or "<tree>"
BK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r86i_backup")
V = "engine/gpu/shadps4/video_core/renderer_vulkan/"

E = {
 V + "rt_glass_find.h": [
  ("inline constexpr std::uint32_t FlagVoted = 1024;  ///< (r86h) the frame camera was known at the draw\n",
   "inline constexpr std::uint32_t FlagVoted = 1024;  ///< (r86h) the frame camera was known at the draw\n"
   "inline constexpr std::uint32_t FlagGBuffer = 2048; ///< (r86i) a G-buffer draw (five or more targets)\n"
   "inline constexpr std::uint32_t FlagBlend = 4096;   ///< (r86i) blended on colour target 0\n"
   "inline constexpr std::uint32_t FlagCube = 8192;    ///< (r86i) the pixel shader reads a cube map\n"),
  ("} // namespace Vulkan::RtGlassFind\n",
   r'''// ---- bbport (r86i_glint-find-gbuffer) ---------------------------------------------------------------------
// The draws the pair table above leaves out (G-buffer draws, forward draws that are not blended), and the box
// rule: which solid mesh of the camera pass lies in a box of the picture. The bottles and jars of the Hunter's
// Dream house are neither blended forward draws with depth write (r86h: those are the HUD) nor listed, so the
// search goes to what the camera pass drew and where it put it on the screen.
// BB_GLASS_FIND_BOX=x0:y0:x1:y1 is a box of the 1920x1080 picture, whatever the internal size is (the bounds
// are projected with the camera's own matrices and scaled to that picture).

inline constexpr std::int32_t PictureWidth = 1920, PictureHeight = 1080;

struct PictureBox {
    std::int32_t x0 = 0, y0 = 0, x1 = 0, y1 = 0;
    bool valid = false;
};

/// BB_GLASS_FIND_BOX's text: four decimal numbers (at most 4 digits each) joined by ':', x0 < x1 <= 1920 and
/// y0 < y1 <= 1080. Anything else (no text, three or five numbers, a letter): not valid.
constexpr PictureBox ParseBox(const char* text) {
    PictureBox box;
    if (text == nullptr) {
        return box;
    }
    std::int32_t v[4] = {0, 0, 0, 0};
    std::size_t field = 0, digits = 0;
    for (std::size_t i = 0;; ++i) {
        const char c = text[i];
        if (c >= '0' && c <= '9') {
            if (digits >= 4) {
                return box;
            }
            v[field] = v[field] * 10 + (c - '0');
            ++digits;
        } else if (c == ':' || c == '\0') {
            if (digits == 0 || (c == ':' && field == 3) || (c == '\0' && field != 3)) {
                return box;
            }
            if (c == '\0') {
                break;
            }
            ++field;
            digits = 0;
        } else {
            return box;
        }
    }
    if (!(v[0] < v[2] && v[1] < v[3] && v[2] <= PictureWidth && v[3] <= PictureHeight)) {
        return box;
    }
    box.x0 = v[0];
    box.y0 = v[1];
    box.x1 = v[2];
    box.y1 = v[3];
    box.valid = true;
    return box;
}

/// BB_GLASS_BOX_SIZE: the most metres across (the diagonal of the world bounds) a mesh the box rule takes may
/// be; 0.1 to 20 with up to 8 characters (digits and one point), else the default.
inline constexpr float BoxSizeDefault = 1.2f;
constexpr float ParseBoxSize(const char* text) {
    if (text == nullptr || text[0] == '\0') {
        return BoxSizeDefault;
    }
    float value = 0.0f, scale = 0.0f;
    for (std::size_t i = 0; text[i] != '\0'; ++i) {
        if (i >= 8) {
            return BoxSizeDefault;
        }
        if (text[i] == '.') {
            if (scale != 0.0f) {
                return BoxSizeDefault;
            }
            scale = 0.1f;
            continue;
        }
        if (text[i] < '0' || text[i] > '9') {
            return BoxSizeDefault;
        }
        const float digit = float(text[i] - '0');
        if (scale == 0.0f) {
            value = value * 10.0f + digit;
        } else {
            value += digit * scale;
            scale *= 0.1f;
        }
    }
    return value >= 0.1f && value <= 20.0f ? value : BoxSizeDefault;
}

/// BB_GLASS_BOX_PANES=1, read once: the meshes the box report takes become panes.
inline bool BoxPanes() {
    static const bool on = [] {
        const char* text = std::getenv("BB_GLASS_BOX_PANES");
        return text && text[0] == '1' && text[1] == '\0';
    }();
    return on;
}

struct ScreenPoint {
    float x = 0.0f, y = 0.0f;
    bool front = false; ///< in front of the camera
};

/// A world point in the 1920x1080 picture. `view`: world to view, 3x4 rows; `proj`: CameraMotion's x scale,
/// y scale, z scale, z offset (the view z has the sign of -proj.w: glass_glint.comp reads it so; ndc +y down).
inline ScreenPoint ProjectToPicture(const std::array<float, 12>& view, const std::array<float, 4>& proj, float wx,
                                    float wy, float wz) {
    ScreenPoint out;
    const float vx = view[0] * wx + view[1] * wy + view[2] * wz + view[3];
    const float vy = view[4] * wx + view[5] * wy + view[6] * wz + view[7];
    const float vz = view[8] * wx + view[9] * wy + view[10] * wz + view[11];
    const float forward = proj[3] < 0.0f ? 1.0f : -1.0f;
    if (!(vz * forward > 0.05f)) {
        return out;
    }
    out.x = (vx * proj[0] / vz * 0.5f + 0.5f) * float(PictureWidth);
    out.y = (vy * proj[1] / vz * 0.5f + 0.5f) * float(PictureHeight);
    out.front = true;
    return out;
}

struct BoxHit {
    bool seen = false;   ///< all 8 corners of the bounds are in front of the camera
    float inside = 0.0f; ///< the share (0 to 1) of the bounds' screen rectangle that lies inside the box
    float x0 = 0.0f, y0 = 0.0f, x1 = 0.0f, y1 = 0.0f; ///< the rectangle, in picture pixels
};

/// World bounds (least x, y, z, greatest x, y, z) against a box of the picture.
inline BoxHit BoxOfBounds(const std::array<float, 12>& view, const std::array<float, 4>& proj,
                          const std::array<float, 6>& bounds, const PictureBox& box) {
    BoxHit hit;
    float lo_x = 1e30f, lo_y = 1e30f, hi_x = -1e30f, hi_y = -1e30f;
    for (std::uint32_t corner = 0; corner < 8; ++corner) {
        const ScreenPoint p = ProjectToPicture(view, proj, bounds[(corner & 1u) != 0 ? 3 : 0],
                                               bounds[(corner & 2u) != 0 ? 4 : 1],
                                               bounds[(corner & 4u) != 0 ? 5 : 2]);
        if (!p.front) {
            return hit;
        }
        lo_x = std::min(lo_x, p.x);
        lo_y = std::min(lo_y, p.y);
        hi_x = std::max(hi_x, p.x);
        hi_y = std::max(hi_y, p.y);
    }
    hit.seen = true;
    hit.x0 = lo_x;
    hit.y0 = lo_y;
    hit.x1 = hi_x;
    hit.y1 = hi_y;
    const float width = hi_x - lo_x, height = hi_y - lo_y;
    const float across_x = std::min(hi_x, float(box.x1)) - std::max(lo_x, float(box.x0));
    const float across_y = std::min(hi_y, float(box.y1)) - std::max(lo_y, float(box.y0));
    if (width > 0.0f && height > 0.0f && across_x > 0.0f && across_y > 0.0f) {
        hit.inside = std::min(1.0f, (across_x * across_y) / (width * height));
    }
    return hit;
}

/// What the box rule takes: the bounds seen, mostly (60 %) inside the box, at most `size_max` metres across,
/// at least 8 triangles.
inline bool BoxTakes(const BoxHit& hit, float diagonal, float size_max, std::uint32_t triangles) {
    return hit.seen && hit.inside >= 0.6f && diagonal <= size_max && triangles >= 8;
}

/// One row of the area table: a shader pair of the G-buffer (FlagGBuffer) or of the forward draws.
struct AreaRow {
    std::uint64_t vs = 0, ps = 0, draws = 0; ///< draws since the last report
    std::uint32_t idx_min = 0xffffffffu, idx_max = 0, inst_max = 0, flags = 0, targets = 0, images = 0;
};

inline constexpr std::size_t AreaMost = 192;
inline constexpr std::size_t AreaLines = 16;

struct AreaState {
    std::mutex lock;
    std::array<AreaRow, AreaMost> rows{};
    std::size_t used = 0;
    std::uint64_t overflow = 0;   ///< draws of pairs past AreaMost
    std::uint64_t last_frame = 0; ///< of the last report
};

inline AreaState& Area() {
    static AreaState state;
    return state;
}

/// One draw of the scene's frame that the pair table leaves out. `images`: the pixel shader's image count.
inline void NoteArea(const DrawNote& d, std::uint32_t images) {
    AreaState& s = Area();
    std::scoped_lock guard{s.lock};
    AreaRow* row = nullptr;
    for (std::size_t i = 0; i < s.used; ++i) {
        if (s.rows[i].vs == d.vs && s.rows[i].ps == d.ps && ((s.rows[i].flags ^ d.flags) & FlagGBuffer) == 0) {
            row = &s.rows[i];
            break;
        }
    }
    if (row == nullptr) {
        if (s.used == AreaMost) {
            ++s.overflow;
            return;
        }
        row = &s.rows[s.used++];
        row->vs = d.vs;
        row->ps = d.ps;
    }
    ++row->draws;
    row->idx_min = std::min(row->idx_min, d.index_count);
    row->idx_max = std::max(row->idx_max, d.index_count);
    row->inst_max = std::max(row->inst_max, d.instances);
    row->flags |= d.flags;
    row->targets = d.targets;
    row->images = images;
}

/// The area lines at the find's report frames (ReportFrame): a header and the rows worth looking at first.
inline void AreaReport(std::uint64_t frame) {
    if (!ReportFrame(frame)) {
        return;
    }
    AreaState& s = Area();
    std::vector<AreaRow> rows;
    std::uint64_t from = 0, overflow = 0;
    {
        std::scoped_lock guard{s.lock};
        if (frame == s.last_frame) {
            return;
        }
        from = s.last_frame;
        s.last_frame = frame;
        overflow = s.overflow;
        rows.assign(s.rows.begin(), s.rows.begin() + static_cast<std::ptrdiff_t>(s.used));
        for (std::size_t i = 0; i < s.used; ++i) {
            s.rows[i].draws = 0;
        }
    }
    const double frames = double(frame - from > 0 ? frame - from : 1);
    std::erase_if(rows, [](const AreaRow& r) { return r.draws == 0; });
    std::size_t g_pairs = 0, g_cut = 0, g_cube = 0, f_pairs = 0, f_cube = 0;
    for (const AreaRow& r : rows) {
        if ((r.flags & FlagGBuffer) != 0) {
            ++g_pairs;
            g_cut += (r.flags & FlagDiscard) != 0 ? 1 : 0;
            g_cube += (r.flags & FlagCube) != 0 ? 1 : 0;
        } else {
            ++f_pairs;
            f_cube += (r.flags & FlagCube) != 0 ? 1 : 0;
        }
    }
    // cut-outs that read a cube map first, then cube readers, then cut-outs, then the rest; the rarer pair first
    const auto rank = [](const AreaRow& r) {
        const bool cube = (r.flags & FlagCube) != 0, cut = (r.flags & FlagDiscard) != 0;
        return cube && cut ? 4 : cube ? 3 : cut ? 2 : 1;
    };
    std::stable_sort(rows.begin(), rows.end(), [&](const AreaRow& a, const AreaRow& b) {
        return rank(a) != rank(b) ? rank(a) > rank(b) : a.draws < b.draws;
    });
    std::printf("Ray tracing glass find (r86i): area, frames %llu-%llu: %zu G-buffer pairs (%zu cut-outs that discard, %zu read a cube map), %zu forward pairs not blended (%zu read a cube map), %llu draws of pairs past the table; below: cut-outs that read a cube map first, then cube readers, then cut-outs\n",
                static_cast<unsigned long long>(from), static_cast<unsigned long long>(frame), g_pairs, g_cut,
                g_cube, f_pairs, f_cube, static_cast<unsigned long long>(overflow));
    for (std::size_t n = 0; n < rows.size() && n < AreaLines; ++n) {
        const AreaRow& r = rows[n];
        std::printf("Ray tracing glass find (r86i): area %llx:%llx %s: %.1f draws a frame, indices %u-%u, instances %u | images %u%s targets %u |%s%s%s%s%s%s%s\n",
                    static_cast<unsigned long long>(r.vs), static_cast<unsigned long long>(r.ps),
                    (r.flags & FlagGBuffer) != 0 ? "G-buffer" : "forward", double(r.draws) / frames,
                    r.idx_min == 0xffffffffu ? 0u : r.idx_min, r.idx_max, r.inst_max, r.images,
                    (r.flags & FlagCube) != 0 ? " (cube map)" : "", r.targets,
                    (r.flags & FlagBlend) != 0 ? " blend" : "", (r.flags & FlagZWrite) != 0 ? " zwrite" : "",
                    (r.flags & FlagNoZWrite) != 0 ? " nozwrite" : "", (r.flags & FlagZTest) != 0 ? " ztest" : "",
                    (r.flags & FlagDiscard) != 0 ? " discard" : "", (r.flags & FlagTextured) != 0 ? " textured" : "",
                    (r.flags & FlagCapture) != 0 ? " capture" : "");
    }
}

} // namespace Vulkan::RtGlassFind
'''),
 ],
 V + "vk_rt_shadow.h": [
  ("    [[nodiscard]] u32 GlassVerdict(const Draw& draw, bool own_constants, char* sample,\n"
   "                                   std::size_t size) const;\n",
   "    [[nodiscard]] u32 GlassVerdict(const Draw& draw, bool own_constants, char* sample,\n"
   "                                   std::size_t size) const;\n"
   "    // bbport (r86i_glint-find-gbuffer): BB_GLASS_FIND=1: called at every frame end. With BB_GLASS_FIND_BOX\n"
   "    // (x0:y0:x1:y1 of the 1920x1080 picture; also live through a job's set:) it lists, at the find's report\n"
   "    // frames and 90 frames after a new box, the camera pass entries whose world bounds project into the\n"
   "    // box, and with BB_GLASS_BOX_PANES=1 takes the small ones inside it by their mesh key.\n"
   "    void GlassFindBox();\n"
   "    // bbport (r86i_glint-find-gbuffer): whether this G-buffer draw is of a mesh the box rule took (the key\n"
   "    // PrepareDraw gives a draw with a position stream); false at once while none was taken.\n"
   "    [[nodiscard]] bool GlassBoxMatch(const Draw& draw) const;\n"),
  ("        LampLoneState lone = LampLoneState::None;\n        u32 lone_gen = 0;\n",
   "        LampLoneState lone = LampLoneState::None;\n        u32 lone_gen = 0;\n"
   "        // bbport (r86i_glint-find-gbuffer): the shader pair of its last camera pass draw (BB_GLASS_FIND only)\n"
   "        u64 find_vs = 0, find_ps = 0;\n"),
  ("    u64 glass_frame = 0;\n    std::array<float, 12> glass_view{};\n",
   "    u64 glass_frame = 0;\n    std::array<float, 12> glass_view{};\n"
   "    // bbport (r86i_glint-find-gbuffer): the box (x0, y0, x1, y1 of the 1920x1080 picture) and whether it is\n"
   "    // valid, the live knobs generation it was read at, the frame its report is due (0: none), and the mesh\n"
   "    // keys the box rule took (glass_box_count of them)\n"
   "    std::array<s32, 4> glass_box_px{};\n"
   "    bool glass_box_valid = false;\n"
   "    u32 glass_box_gen = 0xffffffffu;\n"
   "    u64 glass_box_due = 0;\n"
   "    std::array<u64, 64> glass_box_keys{};\n"
   "    u32 glass_box_count = 0;\n"),
 ],
 V + "vk_rt_shadow.cpp": [
  ("    return RtGlassFind::Pane;\n}\n\nu32 RtShadow::PrepareDraw(const Draw& draw) {\n",
   r'''    return RtGlassFind::Pane;
}

// bbport (r86i_glint-find-gbuffer): see the declaration. The key is the one PrepareDraw makes of a draw with a
// position stream (position_key there): the stream, the index list, the count and first vertex, the instances.
bool RtShadow::GlassBoxMatch(const Draw& draw) const {
    if (glass_box_count == 0 || draw.skinned || draw.positions == 0) {
        return false;
    }
    const std::array<u64, 4> parts{draw.positions, draw.indices,
                                   (u64(draw.index_count) << 32) | draw.first_vertex, draw.instances};
    const u64 key = XXH3_64bits(parts.data(), sizeof(parts));
    for (u32 i = 0; i < glass_box_count; ++i) {
        if (glass_box_keys[i] == key) {
            return true;
        }
    }
    return false;
}

// bbport (r86i_glint-find-gbuffer): see the declaration. The entries are those of the ray traced scene (solid
// draws): a cut-out or blended draw has none, the area lines are for those. Their world bounds: the camera
// pass capture's first look (BB_RT_STILL), else the sun VSM's, else the sun pass's; the pass camera projects
// them (CameraMotion::PassMatrices: world to view and the projection's scales).
void RtShadow::GlassFindBox() {
#if BB_GLASS_STATIC_LIVE
    const u32 generation = BbLiveKnobs::Generation();
#else
    const u32 generation = 0;
#endif
    if (generation != glass_box_gen) {
        glass_box_gen = generation;
#if BB_GLASS_STATIC_LIVE
        const BbLiveKnobs::Text text = BbLiveKnobs::Lookup("BB_GLASS_FIND_BOX");
        const char* box_text = text.Get();
#else
        const char* box_text = std::getenv("BB_GLASS_FIND_BOX");
#endif
        const RtGlassFind::PictureBox box = RtGlassFind::ParseBox(box_text);
        // (review) another box or none: the meshes the old box took are forgotten (an unrelated live
        // knob that leaves the box as it was keeps them)
        if (box.valid != glass_box_valid ||
            (box.valid && glass_box_px != std::array<s32, 4>{box.x0, box.y0, box.x1, box.y1})) {
            glass_box_count = 0;
        }
        glass_box_valid = box.valid;
        glass_box_px = {box.x0, box.y0, box.x1, box.y1};
        if (box.valid) {
            glass_box_due = frame + 90;
            std::printf("Ray tracing glass find (r86i): BB_GLASS_FIND_BOX %d,%d-%d,%d of the 1920x1080 picture: the camera pass entries in it are listed at frame %llu (and at every find report frame)\n",
                        box.x0, box.y0, box.x1, box.y1, static_cast<unsigned long long>(glass_box_due));
        } else if (box_text != nullptr && box_text[0] != '\0') {
            std::printf("Ray tracing glass find (r86i): BB_GLASS_FIND_BOX '%s' is not x0:y0:x1:y1 (x0 < x1 <= 1920, y0 < y1 <= 1080): ignored\n",
                        box_text);
        }
    }
    if (!glass_box_valid) {
        return;
    }
    if (!RtGlassFind::ReportFrame(frame) && !(glass_box_due != 0 && frame >= glass_box_due)) {
        return;
    }
    glass_box_due = 0;
    const auto camera = camera_motion.PassMatrices();
    if (!camera.valid) {
        std::printf("Ray tracing glass find (r86i): box at frame %llu: no camera pass matrices yet\n",
                    static_cast<unsigned long long>(frame));
        return;
    }
    static const bool take = RtGlassFind::BoxPanes();
    static const float size_max = RtGlassFind::ParseBoxSize(std::getenv("BB_GLASS_BOX_SIZE"));
    const RtGlassFind::PictureBox picture{glass_box_px[0], glass_box_px[1], glass_box_px[2], glass_box_px[3], true};
    struct Row {
        const Entry* entry;
        const std::array<float, 6>* bounds;
        RtGlassFind::BoxHit hit;
        float diagonal;
        bool pane;
    };
    std::vector<Row> rows;
    u32 drawn = 0, bounded = 0, behind = 0;
    for (const auto& item : entries) {
        const Entry* e = item.second.get();
        if (e == nullptr || e->gone || e->skinned || e->vertices == 0 ||
            e->still_camera_frame + StillNearFrames < frame) {
            continue;
        }
        ++drawn;
        const std::array<float, 6>* bounds = e->still_has_ref[0] ? &e->still_ref[0]
                                             : e->has_box          ? &e->box
                                             : e->still_has_ref[1] ? &e->still_ref[1]
                                                                   : nullptr;
        if (bounds == nullptr || !((*bounds)[0] <= (*bounds)[3] && (*bounds)[1] <= (*bounds)[4] &&
                                   (*bounds)[2] <= (*bounds)[5])) {
            continue;
        }
        ++bounded;
        const RtGlassFind::BoxHit hit = RtGlassFind::BoxOfBounds(camera.view, camera.proj, *bounds, picture);
        if (!hit.seen) {
            ++behind;
            continue;
        }
        if (!(hit.inside > 0.0f)) {
            continue;
        }
        const float dx = (*bounds)[3] - (*bounds)[0], dy = (*bounds)[4] - (*bounds)[1],
                    dz = (*bounds)[5] - (*bounds)[2];
        rows.push_back({e, bounds, hit, std::sqrt(dx * dx + dy * dy + dz * dz), (e->mask & RtGlassMask) != 0});
    }
    std::sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) {
        return a.hit.inside != b.hit.inside ? a.hit.inside > b.hit.inside : a.diagonal < b.diagonal;
    });
    u32 small_inside = 0, taken_now = 0;
    for (const Row& r : rows) {
        if (r.pane || !RtGlassFind::BoxTakes(r.hit, r.diagonal, size_max, r.entry->triangles)) {
            continue;
        }
        ++small_inside;
        if (!take || r.entry->base == 0) {
            continue;
        }
        bool known = false;
        for (u32 i = 0; i < glass_box_count; ++i) {
            known = known || glass_box_keys[i] == r.entry->base;
        }
        if (!known && glass_box_count < glass_box_keys.size()) {
            glass_box_keys[glass_box_count++] = r.entry->base;
            ++taken_now;
        }
    }
    std::printf("Ray tracing glass find (r86i): box %d,%d-%d,%d at frame %llu: %zu entries overlap it, %u of them mostly inside and under %.2f m across (%s); of %u entries the camera pass drew in the last %u frames, %u have bounds, %u of those are behind or at the camera; mesh keys taken %u (+%u)\n",
                picture.x0, picture.y0, picture.x1, picture.y1, static_cast<unsigned long long>(frame),
                rows.size(), small_inside, size_max, take ? "BB_GLASS_BOX_PANES takes them" : "BB_GLASS_BOX_PANES off: log only",
                drawn, StillNearFrames, bounded, behind, glass_box_count, taken_now);
    for (std::size_t n = 0; n < rows.size() && n < 24; ++n) {
        const Row& r = rows[n];
        const Entry& e = *r.entry;
        const std::array<float, 6>& b = *r.bounds;
        std::printf("Ray tracing glass find (r86i): box entry %llx:%llx key %llx: %.0f%% inside, %.2f m (%.2f x %.2f x %.2f), rect %.0f,%.0f-%.0f,%.0f, %u triangles %u vertices %u instances%s%s%s%s\n",
                    static_cast<unsigned long long>(e.find_vs), static_cast<unsigned long long>(e.find_ps),
                    static_cast<unsigned long long>(e.base), double(r.hit.inside) * 100.0, r.diagonal,
                    b[3] - b[0], b[4] - b[1], b[5] - b[2], r.hit.x0, r.hit.y0, r.hit.x1, r.hit.y1, e.triangles,
                    e.vertices, e.instances, r.pane ? " pane" : "", e.palette != 0 ? " palette" : "",
                    e.shadow ? " sun pass too" : "", e.dynamic ? " moving" : "");
    }
}

u32 RtShadow::PrepareDraw(const Draw& draw) {
'''),
  ("    entry.stream = draw.positions; // bbport (r46b_plant-rule): the same at every draw of the key\n",
   "    entry.stream = draw.positions; // bbport (r46b_plant-rule): the same at every draw of the key\n"
   "    if (draw.camera_pass && RtGlassFind::On()) { // bbport (r86i_glint-find-gbuffer): the box lines name the pair\n"
   "        entry.find_vs = draw.shader;\n"
   "        entry.find_ps = draw.pixel_shader;\n"
   "    }\n"),
  ("    if (RtGlassFind::On()) {\n        RtGlassFind::Report(frame, RtGlassAutoIndices(), RtGlassAutoMin());\n",
   "    if (RtGlassFind::On()) {\n        RtGlassFind::Report(frame, RtGlassAutoIndices(), RtGlassAutoMin());\n"
   "        RtGlassFind::AreaReport(frame); // bbport (r86i_glint-find-gbuffer)\n"
   "        GlassFindBox();                 // bbport (r86i_glint-find-gbuffer)\n"),
 ],
 V + "vk_rasterizer.cpp": [
  ("            RtGlassFind::NoteDraw(note);\n        }\n    }\n",
   "            RtGlassFind::NoteDraw(note);\n        }\n    }\n"
   "    // bbport (r86i_glint-find-gbuffer): BB_GLASS_FIND=1: the draws of the scene's frame the block above leaves\n"
   "    // out (every G-buffer draw, forward draws that are not blended), counted by shader pair with what the pixel\n"
   "    // shader reads: the area lines (rt_glass_find.h). Off: the static bool above.\n"
   "    if (glass_find && scene_started &&\n"
   "        (gbuffer_draw || !(regs.depth_buffer.DepthValid() && regs.depth_buffer.Pitch() == regs.depth_buffer.Height() &&\n"
   "                           regs.depth_buffer.Height() >= 1024))) {\n"
   "        const auto* area_ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];\n"
   "        if (area_ps && (gbuffer_draw || !regs.blend_control[0].enable)) {\n"
   "            bool area_cube = false; // the material hint: the game's glossy surfaces read an environment cube map\n"
   "            for (const auto& image : area_ps->images) {\n"
   "                area_cube = area_cube || image.post_op == Shader::SharpFetchPostOp::ConvertCubeTo2DArray ||\n"
   "                            image.GetSharp(*area_ps).IsCube();\n"
   "            }\n"
   "            RtGlassFind::DrawNote area_note;\n"
   "            area_note.vs = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;\n"
   "            area_note.ps = area_ps->pgm_hash;\n"
   "            area_note.index_count = regs.num_indices;\n"
   "            area_note.instances = regs.num_instances.NumInstances();\n"
   "            area_note.targets = u32(std::popcount(pipeline->GetGraphicsKey().mrt_mask));\n"
   "            area_note.flags = (gbuffer_draw ? RtGlassFind::FlagGBuffer : 0u) |\n"
   "                              (regs.blend_control[0].enable ? RtGlassFind::FlagBlend : 0u) |\n"
   "                              (regs.depth_control.depth_write_enable != 0 ? RtGlassFind::FlagZWrite\n"
   "                                                                          : RtGlassFind::FlagNoZWrite) |\n"
   "                              (regs.depth_control.depth_enable != 0 ? RtGlassFind::FlagZTest : 0u) |\n"
   "                              (area_ps->has_discard ? RtGlassFind::FlagDiscard : 0u) |\n"
   "                              (!area_ps->images.empty() ? RtGlassFind::FlagTextured : 0u) |\n"
   "                              (area_cube ? RtGlassFind::FlagCube : 0u) |\n"
   "                              (dc.capture_draw ? RtGlassFind::FlagCapture : 0u);\n"
   "            RtGlassFind::NoteArea(area_note, u32(area_ps->images.size()));\n"
   "        }\n"
   "    }\n"),
 ],
 V + "vk_rasterizer.h": [
  ("    const GraphicsPipeline* glint_pending = nullptr;\n",
   "    const GraphicsPipeline* glint_pending = nullptr;\n"
   "    /// bbport (r86i_glint-find-gbuffer): a pane drawn by the G-buffer (BB_GLASS_BOX_PANES): its glint waits\n"
   "    /// for the lit scene (EffectsBlendedScene); the draw's pair and counts for the log; cleared at the frame end.\n"
   "    ::BbGlassGlint::PaneDraw glint_gpane{};\n"
   "    bool glint_gpane_on = false;\n"),
 ],
 V + "vk_rasterizer_effects.cpp": [
  ("    if (!draw.camera_pass && !draw.shadow_pass && RtGlassOn()) {\n"
   "        // bbport (r83b_glass-pane-probe): the named pair's draw at the test below (a skeleton,\n",
   "    // bbport (r86i_glint-find-gbuffer): BB_GLASS_BOX_PANES=1: a G-buffer draw of a mesh the box rule took (static,\n"
   "    // not skinned) is a pane too. Off: RtGlassOn() is false first, or no mesh was taken and GlassBoxMatch returns\n"
   "    // at its first test.\n"
   "    const bool box_pane = draw.camera_pass && ps && RtGlassOn() && rt_shadow->GlassBoxMatch(draw);\n"
   "    if (((!draw.camera_pass && !draw.shadow_pass) || box_pane) && RtGlassOn()) {\n"
   "        // bbport (r83b_glass-pane-probe): the named pair's draw at the test below (a skeleton,\n"),
  ("        if (ps && (RtGlassMatch(vs.pgm_hash, ps->pgm_hash) || glass_auto) && !draw.skinned) {\n",
   "        if (ps && (RtGlassMatch(vs.pgm_hash, ps->pgm_hash) || glass_auto || box_pane) && !draw.skinned) {\n"),
  ("            glint_pending = glass_glint ? pipeline : nullptr; // bbport (r86b_glass-visible)\n",
   "            glint_pending = glass_glint && !box_pane ? pipeline : nullptr; // bbport (r86b_glass-visible)\n"
   "            if (box_pane && glass_glint) { // bbport (r86i_glint-find-gbuffer): its glint runs after the lighting\n"
   "                glint_gpane = {.vs = vs.pgm_hash,\n"
   "                               .ps = ps->pgm_hash,\n"
   "                               .indices = regs.num_indices,\n"
   "                               .instances = regs.num_instances.NumInstances()};\n"
   "                glint_gpane_on = true;\n"
   "            }\n"),
  ("        glass_glint->OnFrameEnd();\n        glint_pending = nullptr;\n",
   "        glass_glint->OnFrameEnd();\n        glint_pending = nullptr;\n"
   "        glint_gpane_on = false; // bbport (r86i_glint-find-gbuffer)\n"),
  ("        drawn_look->OnBlendedScene(cb_descs[0].first, db_desc.first, upscaler->Jitter());\n    }\n}\n",
   "        drawn_look->OnBlendedScene(cb_descs[0].first, db_desc.first, upscaler->Jitter());\n    }\n"
   "    // bbport (r86i_glint-find-gbuffer): the glint of a pane the G-buffer drew (BB_GLASS_BOX_PANES), once a\n"
   "    // frame, over the lit scene (the pane's own draw has the normal target as target 0). Off: one bool.\n"
   "    if (glass_glint && glint_gpane_on) {\n"
   "        glint_gpane_on = false;\n"
   "        glass_glint->AfterGlassDraw(cb_descs[0].first, db_desc.first, upscaler->Jitter(), point_shadow->Pending(),\n"
   "                                    glint_gpane);\n"
   "    }\n}\n"),
 ],
 "README.md": [
  ("| `BB_GLASS_FIND` | `1` (r86g, a diagnosis, log only):",
   "| `BB_GLASS_FIND_BOX` | Only with `BB_GLASS_FIND=1` (r86i, log only). `x0:y0:x1:y1`, a box of the 1920x1080 picture (whatever the internal size is), for example the bottle shelf of the Hunter's Dream house. At the find's report frames, and 90 frames after a new box (with the test tools' live knobs a job's `set:BB_GLASS_FIND_BOX=...` also works), the camera pass entries of the ray traced scene whose world bounds project into the box are listed (`Ray tracing glass find (r86i): box entry vs:ps key ...`: share of the screen rectangle inside the box, size, triangles, instances). The draws that never become an entry (cut-outs, blended) are in the area lines: with `BB_GLASS_FIND=1` every other draw of the scene's frame (all G-buffer draws, forward draws not blended) is counted by shader pair with its depth/blend/discard flags and whether its pixel shader reads a cube map; the report prints the cut-outs that read one first. |\n"
   "| `BB_GLASS_BOX_PANES` | `1`, with `BB_GLASS_FIND=1`, `BB_GLASS_FIND_BOX` and `BB_RT_GLASS` on (for example `auto`) (r86i, off by default). The entries of the box report that lie mostly (60 %) inside the box, are at most `BB_GLASS_BOX_SIZE` metres across (0.1 to 20, default 1.2) and have 8 triangles or more are taken by their mesh key (at most 64). A G-buffer draw of such a mesh (static, not skinned) is then a window pane like a forward one (its own entry under the glass mask; the G-buffer draw itself is unchanged), and the glint of its panes (`BB_GLASS_GLINT`) runs once a frame over the lit scene instead of right after the pane's draw. Nothing is taken while no box is set. |\n"
   "| `BB_GLASS_FIND` | `1` (r86g, a diagnosis, log only):"),
 ],
 "engine/tests/test_rt_glass.cpp": [
  ('    std::printf("rt glass: ok (mask 0x%x, bounce mask 0x%x, %zu built-in pairs, at most %zu listed)\\n",\n',
   "    // bbport (r86i_glint-find-gbuffer): the box's text, the projection of world bounds into the picture, the area table\n"
   "    {\n"
   '        static_assert(RtGlassFind::ParseBox("1630:400:1770:680").valid && RtGlassFind::ParseBox("1630:400:1770:680").x1 == 1770);\n'
   '        static_assert(!RtGlassFind::ParseBox(nullptr).valid && !RtGlassFind::ParseBox("").valid);\n'
   '        static_assert(!RtGlassFind::ParseBox("1:2:3").valid && !RtGlassFind::ParseBox("1:2:3:4:5").valid);\n'
   '        static_assert(!RtGlassFind::ParseBox("5:5:5:9").valid && !RtGlassFind::ParseBox("0:0:1921:10").valid);\n'
   '        static_assert(!RtGlassFind::ParseBox("a:0:9:9").valid && !RtGlassFind::ParseBox("1:2:3:").valid);\n'
   '        static_assert(RtGlassFind::ParseBoxSize(nullptr) == RtGlassFind::BoxSizeDefault && RtGlassFind::ParseBoxSize("0.8") > 0.79f);\n'
   '        static_assert(RtGlassFind::ParseBoxSize("0.8") < 0.81f && RtGlassFind::ParseBoxSize("30") == RtGlassFind::BoxSizeDefault);\n'
   '        static_assert(RtGlassFind::ParseBoxSize("1.2.3") == RtGlassFind::BoxSizeDefault && RtGlassFind::ParseBoxSize("x") == RtGlassFind::BoxSizeDefault);\n'
   "        // a camera at the origin looking along +z: identity view rows, x and y scale 1, z offset -1 (so z > 0 is in front)\n"
   "        const std::array<float, 12> view{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};\n"
   "        const std::array<float, 4> proj{1.0f, 1.0f, 0.0f, -1.0f};\n"
   "        const RtGlassFind::ScreenPoint centre = RtGlassFind::ProjectToPicture(view, proj, 0.0f, 0.0f, 5.0f);\n"
   "        assert(centre.front && centre.x > 959.9f && centre.x < 960.1f && centre.y > 539.9f && centre.y < 540.1f);\n"
   "        assert(!RtGlassFind::ProjectToPicture(view, proj, 0.0f, 0.0f, -5.0f).front);\n"
   "        const RtGlassFind::PictureBox box = RtGlassFind::ParseBox(\"1000:500:1100:580\");\n"
   "        const RtGlassFind::BoxHit in = RtGlassFind::BoxOfBounds(view, proj, {0.4f, -0.2f, 4.9f, 0.6f, 0.2f, 5.1f}, box);\n"
   "        assert(in.seen && in.inside > 0.99f && RtGlassFind::BoxTakes(in, 0.5f, 1.2f, 12));\n"
   "        assert(!RtGlassFind::BoxTakes(in, 2.0f, 1.2f, 12) && !RtGlassFind::BoxTakes(in, 0.5f, 1.2f, 4));\n"
   "        const RtGlassFind::BoxHit out = RtGlassFind::BoxOfBounds(view, proj, {-3.0f, -0.2f, 4.9f, -2.9f, 0.2f, 5.1f}, box);\n"
   "        assert(out.seen && out.inside == 0.0f && !RtGlassFind::BoxTakes(out, 0.5f, 1.2f, 12));\n"
   "        assert(!RtGlassFind::BoxOfBounds(view, proj, {0.4f, -0.2f, -5.1f, 0.6f, 0.2f, -4.9f}, box).seen);\n"
   "        RtGlassFind::DrawNote area_note;\n"
   "        area_note.vs = 1;\n"
   "        area_note.ps = 2;\n"
   "        area_note.index_count = 300;\n"
   "        area_note.instances = 1;\n"
   "        area_note.flags = RtGlassFind::FlagGBuffer | RtGlassFind::FlagDiscard;\n"
   "        RtGlassFind::NoteArea(area_note, 3);\n"
   "        area_note.index_count = 90;\n"
   "        RtGlassFind::NoteArea(area_note, 3);\n"
   "        area_note.flags = 0; // the same pair drawn forward: a row of its own\n"
   "        RtGlassFind::NoteArea(area_note, 1);\n"
   "        RtGlassFind::AreaState& area = RtGlassFind::Area();\n"
   "        assert(area.used == 2 && area.rows[0].draws == 2 && area.rows[0].idx_min == 90 && area.rows[0].idx_max == 300);\n"
   "        assert(area.rows[1].draws == 1 && (area.rows[0].flags & RtGlassFind::FlagDiscard) != 0);\n"
   "        RtGlassFind::AreaReport(299); // not a report frame\n"
   "        assert(area.rows[0].draws == 2);\n"
   "        RtGlassFind::AreaReport(300); // prints, starts a new window\n"
   "        assert(area.rows[0].draws == 0 && area.last_frame == 300);\n"
   "    }\n"
   '    std::printf("rt glass: ok (mask 0x%x, bounce mask 0x%x, %zu built-in pairs, at most %zu listed)\\n",\n'),
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
