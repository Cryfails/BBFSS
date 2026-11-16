# r86d_glint-pane-depth: FEATURE patch (a diagnostic step of the glass glint, r86b/r86c; off with the glint:
# every new statement runs only where the glint's SHADE pass already found a pane point, and the glint
# itself is off by default behind BB_GLASS_GLINT).
#
# Why: build 28 logged "pane points 8321 (100.00 m away ...)". 100.00 is r86c's own log clamp (each
# pane point's t is put into 100 m before it is summed): the mean says every pane point lies at t >=
# 100 m. The nearest pane hit on a camera ray does not depend on the depth (the depth only sets how far
# the ray may go), so no pane lies nearer than 100 m on those rays whatever the depth reads. This patch
# adds the numbers that separate the two readings: what the depth says under the pane points, and how
# many pane points lie nearer than 50 m.
# Adds counter words 21 (sum of the pane points' own distance, whole metres, each put into
# GLASS_GLINT_FAR = 1000 m; review fix: a pane hit is <= Reach(depth), so at >= 100 m the depth is
# >= ~99.8 m and a 100 m-clamped depth sum could only read 100.00),
# 22 (pane points whose depth is the sky, depth >= 1), 23 (pane points nearer than 50 m); slot size
# stays 24 words. Log: a third line "Ray tracing glass glint (r86d): ...".
# Files: host_shaders/glass_glint_layout.h, host_shaders/glass_glint.comp, renderer_vulkan/glass_glint.h
# (static_assert), renderer_vulkan/vk_glass_glint.cpp (log line).
# Use: python -I -X utf8 r86d_glint-pane-depth.py check | apply | revert
# Root: R86D_ROOT else <tree>. CRLF kept. Backups in r86d_backup next to this script.
import os, sys, io

ROOT = os.environ.get("R86D_ROOT") or "<tree>"
BK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r86d_backup")
V = "engine/gpu/shadps4/video_core/"
E = {
 V + "host_shaders/glass_glint_layout.h": [
  ("#define GLASS_GLINT_W_T_SUM 20u\n#define GLASS_GLINT_W_COUNT 21u\n",
   "#define GLASS_GLINT_W_T_SUM 20u\n"
   "// bbport (r86d_glint-pane-depth): summed: 21 the pane points' own distance (whole metres, each put\n"
   "// into GLASS_GLINT_FAR), 22 pane points whose depth is the sky, 23 pane points nearer than 50 m.\n"
   "#define GLASS_GLINT_W_FAR_SUM 21u\n#define GLASS_GLINT_W_SKY 22u\n#define GLASS_GLINT_W_NEAR 23u\n"
   "#define GLASS_GLINT_W_COUNT 24u\n"),
 ],
 V + "renderer_vulkan/glass_glint.h": [
  ("GLASS_GLINT_W_T_SUM + 1 == GLASS_GLINT_W_COUNT &&",
   "GLASS_GLINT_W_T_SUM + 1 == GLASS_GLINT_W_FAR_SUM && GLASS_GLINT_W_NEAR + 1 == GLASS_GLINT_W_COUNT &&"),
 ],
 V + "host_shaders/glass_glint.comp": [
  ("    uint units = 0u, curved = 0u, t_sum = 0u; // bbport (r86c_glass-glint-visible)\n",
   "    uint units = 0u, curved = 0u, t_sum = 0u; // bbport (r86c_glass-glint-visible)\n"
   "    uint d_far_sum = 0u, d_sky = 0u, d_near = 0u; // bbport (r86d_glint-pane-depth)\n"),
  ("            t_sum = uint(min(hit.w, 100.0) * 100.0);\n",
   "            t_sum = uint(min(hit.w, 100.0) * 100.0);\n"
   "            // bbport (r86d_glint-pane-depth): how far the pane really is; is the depth the sky\n"
   "            d_far_sum = max(uint(min(hit.w, float(GLASS_GLINT_FAR))), 1u);\n"
   "            d_sky = texelFetch(depth_tex, first, 0).r < 1.0 ? 0u : 1u;\n"
   "            d_near = hit.w < 50.0 ? 1u : 0u;\n"),
  ("    if (d_pairs != 0u) {\n        atomicAdd(group_count[GLASS_GLINT_W_PAIRS], d_pairs);\n",
   "    // bbport (r86d_glint-pane-depth)\n"
   "    if (d_far_sum != 0u) {\n        atomicAdd(group_count[GLASS_GLINT_W_FAR_SUM], d_far_sum);\n    }\n"
   "    if (d_sky != 0u) {\n        atomicAdd(group_count[GLASS_GLINT_W_SKY], d_sky);\n    }\n"
   "    if (d_near != 0u) {\n        atomicAdd(group_count[GLASS_GLINT_W_NEAR], d_near);\n    }\n"
   "    if (d_pairs != 0u) {\n        atomicAdd(group_count[GLASS_GLINT_W_PAIRS], d_pairs);\n"),
  ("        // bbport (r86c_glass-glint-visible): the log's second line (sums, then the largest)\n",
   "        // bbport (r86d_glint-pane-depth): the log's third line (sums)\n"
   "        for (uint w = GLASS_GLINT_W_FAR_SUM; w <= GLASS_GLINT_W_NEAR; ++w) {\n"
   "            if (group_count[w] != 0u) {\n                atomicAdd(counters[base + w], group_count[w]);\n            }\n        }\n"
   "        // bbport (r86c_glass-glint-visible): the log's second line (sums, then the largest)\n"),
 ],
 V + "renderer_vulkan/vk_glass_glint.cpp": [
  ("        double(stats.best_max), double(stats.lamp_colour_max), double(stats.reach_min),\n"
   "        double(stats.reach_max));\n    stats = {};\n",
   "        double(stats.best_max), double(stats.lamp_colour_max), double(stats.reach_min),\n"
   "        double(stats.reach_max));\n"
   "    // bbport (r86d_glint-pane-depth): the third line: what the depth says under the pane points\n"
   "    BbReport::Printf(\"Ray tracing glass glint (r86d): a pass: pane points %.0f, %.1f m away on average \"\n"
   "                     \"(each put into 1000 m), %.0f of them where the depth is the sky, %.0f \"\n"
   "                     \"nearer than 50 m\\n\",\n"
   "                     per(GLASS_GLINT_W_UNITS), double(stats.words[GLASS_GLINT_W_FAR_SUM]) / units,\n"
   "                     per(GLASS_GLINT_W_SKY), per(GLASS_GLINT_W_NEAR));\n"
   "    stats = {};\n"),
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
            wr(os.path.join(ROOT, f), rd(b)); os.remove(b); print("restored", f)  # review fix: no stale backup
    sys.exit(0)
if mode not in ("check", "apply"):
    print(__doc__ if False else "usage: check | apply | revert"); sys.exit(2)
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
