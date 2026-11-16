# r86e_glint-hit-distance: FEATURE patch (the glass glint r86b/r86c/r86d; off with the glint: every new
# statement of the shaders runs only in a pass the glint already makes, the glint itself is off by
# default behind BB_GLASS_GLINT, and the rasterizer makes no GlassGlint object when it is off).
#
# Why (b30: "8338 pane points, 907.2 m away, 0 sky, 0 nearer than 50 m", lamp pairs in reach 0):
# the code shows what the numbers mean, and it is NOT a wrong space, wrong units or a depth sign.
#  - The depth convention is the tree's (D3D 0..1, sky 1: rt_card_view.comp, heat_haze.comp, rt_shadow.comp
#    read it the same way; the ray, the depth point and the jitter match rt_card_view.comp line by line).
#  - hit.w is the committed ray t (metres, the TLAS being in the view space of the pass camera), not a
#    sentinel: a miss is -1 and never counted.
#  - The pane geometry the pair puts into the TLAS lies ~900 m away: the nearest pane on a camera ray is the
#    same thing for every pixel. Evidence in the tree: every pane draw of the 600-frame window is 29892
#    triangles (17935200 = 600 x 29892), ONE draw a frame, one entry ("1 instances"), a closed
#    back-culled mesh with 16x16 textures; the test view's blue (a pane only behind the depth) is a whole lower
#    band of the frame with a straight horizon-like edge, floor and hunter alike; the panes seen in front of
#    the depth are 8338 / 1996 pixels where the depth is the sky dome (a dome's depth is < 1.0 here, so the
#    sky test d >= 1 never fires: r86d's "0 sky" is that, not a reversed Z). A dome or sphere seen from inside
#    gives exactly that: every ray below the horizon hits it at 900 m or more, rays out of a window are the
#    only ones that end in front of the depth. So the draw the pair hooks at the dream house is the sky
#    dome (or a horizon sphere), not the bottles; the bottles are another pair (or not forward drawn).
# What this patch does:
#  1. A pane is taken only up to GLASS_GLINT_PANE_MAX = 50 m on a camera ray (COARSE, SHADE and the test
#     view's far ray): a far dome never counts as glass again, the test view's blue band goes, the cyan
#     shows real nearby panes only (and the rays are shorter). Lamps reach 8.5 m at most, so no glint is lost.
#  2. Raw values, as the task asked: a log of 8 pane pixels a pass (every 211th pixel on a pane: raw depth,
#     the depth's distance and view point, the pane's t and view and WORLD point, the nearest lamp's view and
#     world point and distance) and 12 fixed grid blocks (the nearest pane on the ray at any distance, with
#     the same raw values), the pane draw the pass follows (vertex and pixel shader hash, index count,
#     instances: a 89676-index draw is the 29892-triangle mesh) and the camera's world position. Lines
#     "Ray tracing glass glint (r86e): ...", twice a 600-frame report (the oldest passes still held).
# Files: host_shaders/glass_glint_layout.h, host_shaders/glass_glint.comp, renderer_vulkan/glass_glint.h,
# renderer_vulkan/vk_glass_glint.h, renderer_vulkan/vk_glass_glint.cpp, renderer_vulkan/vk_rasterizer_effects.cpp
# (the one call), README.md (the BB_GLASS_GLINT row). Memory: the counters buffer 6144 -> 27648 bytes.
# Use: python -I -X utf8 r86e_glint-hit-distance.py check | apply | revert
# Root: R86E_ROOT else <tree>. CRLF kept. Backups in r86e_backup next to this script.
import os, sys, io

ROOT = os.environ.get("R86E_ROOT") or "<tree>"
BK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r86e_backup")
V = "engine/gpu/shadps4/video_core/"

SHADER_HELPERS = r'''// bbport (r86e_glint-hit-distance): raw values for the log (glass_glint_layout.h GLASS_GLINT_DBG_*):
// where this slot's records start in the counters buffer
uint DbgBase() {
    return GLASS_GLINT_SLOTS * GLASS_GLINT_SLOT_WORDS + GLASS_GLINT_SLOTS * GLASS_GLINT_DATA_WORDS +
           pc.info.z * GLASS_GLINT_DBG_WORDS;
}

// The view-space point the depth `raw` gives at pixel `p`, as DepthT builds it (0 for the sky).
vec3 DepthPoint(ivec2 p, float raw) {
    if (!(raw < 1.0)) {
        return vec3(0.0);
    }
    const float z = pc.proj.w / min(raw - pc.proj.z, -1e-8);
    const vec2 ndc = (vec2(p) + 0.5 - pc.frame.zw) / pc.frame.xy * 2.0 - 1.0;
    return vec3(ndc.x * z / pc.proj.x, ndc.y * z / pc.proj.y, z);
}

// The pass's lamp nearest to `pos` (as the host wrote them): its view position, distance, reach; d -1: none.
void NearestLamp(vec3 pos, out vec3 lamp_pos, out float d, out float reach) {
    const uint data = DataBase();
    const uint n = min(counters[data + GLASS_GLINT_DATA_COUNT], GLASS_GLINT_MAX_LAMPS);
    lamp_pos = vec3(0.0);
    d = -1.0;
    reach = 0.0;
    for (uint k = 0u; k < n; ++k) {
        const uint w = data + GLASS_GLINT_DATA_LAMPS + k * 8u;
        const vec4 lamp = uintBitsToFloat(uvec4(counters[w], counters[w + 1u], counters[w + 2u], counters[w + 3u]));
        const float dd = length(lamp.xyz - pos);
        if (d < 0.0 || dd < d) {
            lamp_pos = lamp.xyz;
            d = dd;
            reach = lamp.w;
        }
    }
}

// One record of 16 words at `at` (see GLASS_GLINT_DBG_* in glass_glint_layout.h).
void DbgRecord(uint at, uint kind, ivec2 p, float t_pane, vec3 pane_pos) {
    const float raw = texelFetch(depth_tex, p, 0).r;
    const vec3 depth_point = DepthPoint(p, raw);
    vec3 lamp_pos;
    float lamp_d, lamp_reach;
    NearestLamp(t_pane >= 0.0 ? pane_pos : depth_point, lamp_pos, lamp_d, lamp_reach);
    counters[at] = kind;
    counters[at + 1u] = uint(p.x) | (uint(p.y) << 16);
    counters[at + 2u] = floatBitsToUint(raw);
    counters[at + 3u] = floatBitsToUint(DepthT(p));
    counters[at + 4u] = floatBitsToUint(depth_point.x);
    counters[at + 5u] = floatBitsToUint(depth_point.y);
    counters[at + 6u] = floatBitsToUint(depth_point.z);
    counters[at + 7u] = floatBitsToUint(t_pane);
    counters[at + 8u] = floatBitsToUint(pane_pos.x);
    counters[at + 9u] = floatBitsToUint(pane_pos.y);
    counters[at + 10u] = floatBitsToUint(pane_pos.z);
    counters[at + 11u] = floatBitsToUint(lamp_pos.x);
    counters[at + 12u] = floatBitsToUint(lamp_pos.y);
    counters[at + 13u] = floatBitsToUint(lamp_pos.z);
    counters[at + 14u] = floatBitsToUint(lamp_d);
    counters[at + 15u] = floatBitsToUint(lamp_reach);
}

#ifdef COARSE
shared uint group_blocks, group_flagged, group_behind;
'''

COARSE_GRID = r'''        // bbport (r86e_glint-hit-distance): 12 fixed blocks (4 across, 3 down): the nearest pane on the
        // camera ray at any distance, with the raw depth and the nearest lamp, for the log
        const uint gx = pc.info.x / 4u, gy = pc.info.y / 3u;
        if (gx != 0u && gy != 0u && b.x % gx == gx / 2u && b.y % gy == gy / 2u && b.x / gx < 4u &&
            b.y / gy < 3u) {
            const float t_far = PaneT(dir, float(GLASS_GLINT_FAR), false);
            DbgRecord(DbgBase() + GLASS_GLINT_DBG_FIRST +
                          (GLASS_GLINT_DBG_PANE_MAX + b.x / gx + 4u * (b.y / gy)) * GLASS_GLINT_DBG_RECORD,
                      2u, p, t_far, dir * max(t_far, 0.0));
        }
        block_flags[b.y * pc.info.x + b.x] = flag;
'''

SHADE_SAMPLE = r'''            d_near = hit.w < 50.0 ? 1u : 0u;
            // bbport (r86e_glint-hit-distance): every 211th pane pixel, the first 8 of the pass: raw values
            if (((uint(first.x) * 7u + uint(first.y) * 13u) % 211u) == 0u) {
                const uint taken = atomicAdd(counters[DbgBase()], 1u);
                if (taken < GLASS_GLINT_DBG_PANE_MAX) {
                    DbgRecord(DbgBase() + GLASS_GLINT_DBG_FIRST + taken * GLASS_GLINT_DBG_RECORD, 1u, first, hit.w,
                              hit.xyz);
                }
            }
'''

PRINT_HELPER = r'''static_assert(BufferBytes == 27648); // 16 x 24 + 16 x 84 + 16 x 324 words (r86e)

/// bbport (r86e_glint-hit-distance): the raw-value records of a slot (log lines "(r86e)"): the pane
/// draw and the camera the pass had, the pane-pixel records, and with `grid` the 12 fixed blocks.
void PrintSlot(const u32* words, u32 slot, bool grid) {
    const u32* data = words + BG::Slots * BG::SlotWords + slot * BG::DataWords;
    const u32* dbg =
        words + BG::Slots * BG::SlotWords + BG::Slots * BG::DataWords + slot * BG::DbgWords;
    const auto flt = [](u32 w) { return std::bit_cast<float>(w); };
    float v[12];
    std::memcpy(v, data + BG::DataView, sizeof(v));
    // world = R^T (view - t), the pass camera's view matrix being world to view (3x4, rows)
    const auto world = [&v](float x, float y, float z, float* out) {
        for (int c = 0; c < 3; ++c) {
            out[c] = v[c] * (x - v[3]) + v[4 + c] * (y - v[7]) + v[8 + c] * (z - v[11]);
        }
    };
    float cam[3];
    world(0.0f, 0.0f, 0.0f, cam);
    const u64 vs = u64(data[BG::DataDraw]) | (u64(data[BG::DataDraw + 1]) << 32);
    const u64 ps = u64(data[BG::DataDraw + 2]) | (u64(data[BG::DataDraw + 3]) << 32);
    BbReport::Printf("Ray tracing glass glint (r86e): a pass (slot %u): pane draw %llx:%llx, %u indices, %u "
                     "instances; camera in the world (%.2f %.2f %.2f); pane pixels sampled %u (every 211th "
                     "pixel on a pane, the first %u shown); depth 'raw' is the depth buffer's value (sky 1)\n",
                     slot, static_cast<unsigned long long>(vs), static_cast<unsigned long long>(ps),
                     data[BG::DataDraw + 4], data[BG::DataDraw + 5], double(cam[0]), double(cam[1]),
                     double(cam[2]), dbg[0], BG::DbgPaneMax);
    const u32 records = BG::DbgPaneMax + (grid ? BG::DbgGridMax : 0u);
    for (u32 i = 0; i < records; ++i) {
        const u32* r = dbg + BG::DbgFirst + i * BG::DbgRecord;
        if (r[0] == 0) {
            continue;
        }
        float hit[3], lamp[3];
        world(flt(r[8]), flt(r[9]), flt(r[10]), hit);
        world(flt(r[11]), flt(r[12]), flt(r[13]), lamp);
        BbReport::Printf(
            "Ray tracing glass glint (r86e):   %s px (%u,%u): raw depth %.7f, depth distance %.2f m at view "
            "(%.2f %.2f %.2f); pane t %.2f m (-1: none) at view (%.2f %.2f %.2f) world (%.2f %.2f %.2f); "
            "nearest lamp %.2f m away (-1: none), reach %.1f, view (%.2f %.2f %.2f) world (%.2f %.2f %.2f)\n",
            r[0] == 1 ? "pane pixel" : "grid block", r[1] & 0xFFFFu, r[1] >> 16, double(flt(r[2])),
            double(flt(r[3])), double(flt(r[4])), double(flt(r[5])), double(flt(r[6])), double(flt(r[7])),
            double(flt(r[8])), double(flt(r[9])), double(flt(r[10])), double(hit[0]), double(hit[1]),
            double(hit[2]), double(flt(r[14])), double(flt(r[15])), double(flt(r[11])), double(flt(r[12])),
            double(flt(r[13])), double(lamp[0]), double(lamp[1]), double(lamp[2]));
    }
}

/// The records of the slots that are long done: up to two passes that sampled pane pixels (else the
/// first with grid blocks), the grid shown with the first. Only the 4 oldest slots (15 to 12 passes,
/// at MaxPasses 2 a frame 6 frames or more ago), so no slot still in flight on the GPU is read.
void PrintSamples(const u32* words, u64 passes) {
    if (words == nullptr || passes < BG::Slots) {
        return;
    }
    u32 chosen[2] = {0, 0};
    u32 count = 0, grid_slot = BG::Slots;
    for (u32 k = 1; k <= 4; ++k) {
        const u32 slot = u32((passes + k) % BG::Slots);
        const u32* dbg =
            words + BG::Slots * BG::SlotWords + BG::Slots * BG::DataWords + slot * BG::DbgWords;
        if (dbg[0] != 0 && count < 2) {
            chosen[count++] = slot;
        }
        if (grid_slot == BG::Slots && dbg[BG::DbgFirst + BG::DbgPaneMax * BG::DbgRecord] != 0) {
            grid_slot = slot;
        }
    }
    if (count == 0 && grid_slot != BG::Slots) {
        chosen[count++] = grid_slot;
    }
    for (u32 i = 0; i < count; ++i) {
        PrintSlot(words, chosen[i], i == 0);
    }
}
} // namespace
'''
# (the helper above replaces the static_assert line and the namespace close; see the edit)

E = {
 V + "host_shaders/glass_glint_layout.h": [
  ("#define GLASS_GLINT_DATA_WORDS 72u\n",
   "#define GLASS_GLINT_DATA_WORDS 84u\n"
   "// bbport (r86e_glint-hit-distance): the data block's words 1 to 6 hold the pane draw the pass follows\n"
   "// (vertex shader hash low, high, pixel shader hash low, high, index count, instances) and words 72 to\n"
   "// 83 the pass's camera (world to view, 3x4, row by row), both for the log (host-written).\n"
   "#define GLASS_GLINT_DATA_DRAW 1u\n#define GLASS_GLINT_DATA_VIEW 72u\n"
   "// After the data blocks, a raw-value area of GLASS_GLINT_DBG_WORDS words a slot (the GPU clears it\n"
   "// with the slot's counters): word 0 the pane samples taken (atomic; at most DBG_PANE_MAX are\n"
   "// written), then from GLASS_GLINT_DBG_FIRST records of GLASS_GLINT_DBG_RECORD words: DBG_PANE_MAX\n"
   "// pane-pixel records, then DBG_GRID_MAX records of fixed blocks (4 across, 3 down). A record: 0 kind\n"
   "// (0 empty, 1 pane pixel, 2 grid block), 1 pixel x | y << 16, 2 raw depth, 3 the depth's distance\n"
   "// (m; the sky 1000), 4 to 6 the point the depth gives (view space), 7 the pane's t (m; -1 none; a\n"
   "// grid block's is the nearest pane on its ray at any distance), 8 to 10 that point, 11 to 13 the\n"
   "// nearest lamp (view space), 14 its distance to the pane point (to the depth's point when there is\n"
   "// no pane; -1: no lamps), 15 its reach (m).\n"
   "#define GLASS_GLINT_DBG_PANE_MAX 8u\n#define GLASS_GLINT_DBG_GRID_MAX 12u\n"
   "#define GLASS_GLINT_DBG_RECORD 16u\n#define GLASS_GLINT_DBG_FIRST 4u\n"
   "#define GLASS_GLINT_DBG_WORDS 324u\n"),
  ("#define GLASS_GLINT_FAR 1000.0\n",
   "#define GLASS_GLINT_FAR 1000.0\n"
   "// bbport (r86e_glint-hit-distance): a pane is only taken up to this distance (m) on a camera ray:\n"
   "// the dream house's pair draws one 29892-triangle mesh a frame that lies 900 m and more away (a\n"
   "// dome: every ray below the horizon met it), which is not glass; a lamp reaches 8.5 m at most.\n"
   "#define GLASS_GLINT_PANE_MAX 50.0\n"),
 ],
 V + "renderer_vulkan/glass_glint.h": [
  ("inline constexpr std::uint32_t DataWords = GLASS_GLINT_DATA_WORDS;\n",
   "inline constexpr std::uint32_t DataWords = GLASS_GLINT_DATA_WORDS;\n"
   "// bbport (r86e_glint-hit-distance): the pane draw's words and the camera's in the data block, and the\n"
   "// raw-value records after the data blocks (glass_glint_layout.h)\n"
   "inline constexpr std::uint32_t DataDraw = GLASS_GLINT_DATA_DRAW, DataView = GLASS_GLINT_DATA_VIEW;\n"
   "inline constexpr std::uint32_t DbgWords = GLASS_GLINT_DBG_WORDS, DbgFirst = GLASS_GLINT_DBG_FIRST;\n"
   "inline constexpr std::uint32_t DbgRecord = GLASS_GLINT_DBG_RECORD;\n"
   "inline constexpr std::uint32_t DbgPaneMax = GLASS_GLINT_DBG_PANE_MAX, DbgGridMax = GLASS_GLINT_DBG_GRID_MAX;\n"
   "inline constexpr float PaneMax = float(GLASS_GLINT_PANE_MAX);\n"
   "/// The pane draw a pass follows (the log says which pair and how many indices).\n"
   "struct PaneDraw {\n    std::uint64_t vs = 0, ps = 0;\n    std::uint32_t indices = 0, instances = 0;\n};\n"),
  ("static_assert(DataLamps + MaxLamps * LampWords <= DataWords && DataCount < DataLamps);\n",
   "static_assert(DataLamps + MaxLamps * LampWords <= DataWords && DataCount < DataLamps);\n"
   "// bbport (r86e_glint-hit-distance)\n"
   "static_assert(DataDraw + 6 <= DataLamps && DataView >= DataLamps + MaxLamps * LampWords &&\n"
   "                  DataView + 12 <= DataWords,\n"
   "              \"the data block: count, the pane draw, the lamps, the camera\");\n"
   "static_assert(DbgFirst + (DbgPaneMax + DbgGridMax) * DbgRecord == DbgWords && DbgRecord == 16 &&\n"
   "                  DbgFirst >= 1,\n"
   "              \"the raw-value area: a count, then the records\");\n"),
 ],
 V + "renderer_vulkan/vk_glass_glint.h": [
  ("    void AfterGlassDraw(VideoCore::ImageId color, VideoCore::ImageId depth,\n"
   "                        std::array<float, 2> jitter, bool lamps_open);\n",
   "    void AfterGlassDraw(VideoCore::ImageId color, VideoCore::ImageId depth,\n"
   "                        std::array<float, 2> jitter, bool lamps_open,\n"
   "                        const ::BbGlassGlint::PaneDraw& pane); // bbport (r86e_glint-hit-distance)\n"),
 ],
 V + "renderer_vulkan/vk_glass_glint.cpp": [
  ("static_assert(BufferBytes == 6144); // 16 x 24 + 16 x 72 words\n} // namespace\n",
   PRINT_HELPER),
  ("    BG::Slots * SlotBytes + BG::Slots * BG::DataWords * sizeof(u32);\n",
   "    BG::Slots * SlotBytes + BG::Slots * BG::DataWords * sizeof(u32) +\n"
   "    BG::Slots * BG::DbgWords * sizeof(u32); // bbport (r86e_glint-hit-distance): the raw-value area\n"),
  ("void GlassGlint::AfterGlassDraw(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,\n"
   "                                std::array<float, 2> jitter, bool lamps_open) {\n",
   "void GlassGlint::AfterGlassDraw(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,\n"
   "                                std::array<float, 2> jitter, bool lamps_open,\n"
   "                                const BG::PaneDraw& pane) {\n"),
  ("    data[BG::DataCount] = picked.count;\n",
   "    data[BG::DataCount] = picked.count;\n"
   "    // bbport (r86e_glint-hit-distance): the pane draw and the camera of this pass, for the log\n"
   "    data[BG::DataDraw] = u32(pane.vs);\n"
   "    data[BG::DataDraw + 1] = u32(pane.vs >> 32);\n"
   "    data[BG::DataDraw + 2] = u32(pane.ps);\n"
   "    data[BG::DataDraw + 3] = u32(pane.ps >> 32);\n"
   "    data[BG::DataDraw + 4] = pane.indices;\n"
   "    data[BG::DataDraw + 5] = pane.instances;\n"
   "    std::memcpy(&data[BG::DataView], camera.view.data(), sizeof(camera.view));\n"),
  ("            cmdbuf.fillBuffer(counter_buffer, push.info[2] * SlotBytes, SlotBytes, 0);\n",
   "            cmdbuf.fillBuffer(counter_buffer, push.info[2] * SlotBytes, SlotBytes, 0);\n"
   "            // bbport (r86e_glint-hit-distance): the slot's raw-value records, cleared with its counters\n"
   "            cmdbuf.fillBuffer(counter_buffer,\n"
   "                              (BG::Slots * BG::SlotWords + BG::Slots * BG::DataWords +\n"
   "                               push.info[2] * BG::DbgWords) * sizeof(u32),\n"
   "                              BG::DbgWords * sizeof(u32), 0);\n"),
  ("                     per(GLASS_GLINT_W_SKY), per(GLASS_GLINT_W_NEAR));\n    stats = {};\n",
   "                     per(GLASS_GLINT_W_SKY), per(GLASS_GLINT_W_NEAR));\n"
   "    // bbport (r86e_glint-hit-distance): the raw values of the oldest passes still held\n"
   "    PrintSamples(static_cast<const u32*>(counters.mapped), passes);\n"
   "    stats = {};\n"),
 ],
 V + "host_shaders/glass_glint.comp": [
  ("#ifdef COARSE\nshared uint group_blocks, group_flagged, group_behind;\n", SHADER_HELPERS),
  ("        if (PaneT(dir, Reach(DepthT(p)), true) >= 0.0) {\n",
   "        if (PaneT(dir, min(Reach(DepthT(p)), float(GLASS_GLINT_PANE_MAX)), true) >= 0.0) { // bbport (r86e)\n"),
  ("        } else if (Show() && PaneT(dir, float(GLASS_GLINT_FAR), true) >= 0.0) {\n",
   "        } else if (Show() && PaneT(dir, float(GLASS_GLINT_PANE_MAX), true) >= 0.0) { // bbport (r86e)\n"),
  ("        block_flags[b.y * pc.info.x + b.x] = flag;\n", COARSE_GRID),
  ("            const float t = PaneT(dir, Reach(t_depth), false);\n",
   "            const float t = PaneT(dir, min(Reach(t_depth), float(GLASS_GLINT_PANE_MAX)), false); // bbport (r86e)\n"),
  ("            behind = PaneT(RayDir(vec2(first) + 0.5 * float(scale)), float(GLASS_GLINT_FAR), true) >= 0.0;\n",
   "            behind = PaneT(RayDir(vec2(first) + 0.5 * float(scale)), float(GLASS_GLINT_PANE_MAX), true) >= 0.0; // bbport (r86e)\n"),
  ("            d_near = hit.w < 50.0 ? 1u : 0u;\n", SHADE_SAMPLE),
 ],
 V + "renderer_vulkan/vk_rasterizer_effects.cpp": [
  ("            glass_glint->AfterGlassDraw(cb_descs[0].first, db_desc.first, upscaler->Jitter(),\n"
   "                                        point_shadow->Pending());\n",
   "            const auto* pane_ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)]; // bbport (r86e)\n"
   "            glass_glint->AfterGlassDraw(cb_descs[0].first, db_desc.first, upscaler->Jitter(),\n"
   "                                        point_shadow->Pending(),\n"
   "                                        {.vs = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,\n"
   "                                         .ps = pane_ps ? pane_ps->pgm_hash : 0,\n"
   "                                         .indices = num_indices, .instances = num_instances});\n"),
 ],
 "README.md": [
  ("and 6144 bytes of counters and lamps | off |",
   "and 27648 bytes (6144 before r86e) of counters, lamps and raw samples. r86e: a pane is only taken up to 50 m "
   "on a camera ray (the pair of the Hunter's Dream house `e30b0480:8a6c7657` draws one 29892-triangle mesh a frame "
   "that lies 900 m and more away, a dome, which is not glass: every ray below the horizon met it, so the test view "
   "showed a blue band and the glints never had a pane near a lamp); the log's `Ray tracing glass glint (r86e)` "
   "lines, twice a report, give the pane draw's shader pair and index count, the camera's world position and, "
   "for up to 8 pane pixels and 12 fixed screen blocks, the raw depth, the depth's distance and point, the pane's "
   "distance and view and world point and the nearest lamp | off |"),
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
