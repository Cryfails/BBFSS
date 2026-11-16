# r97d_heat-haze-real-shimmer: FEATURE (instruments and a proof view) on top of r97, r97b and r97c
# (apply AFTER them, revert BEFORE them). Off by default as r97: nothing runs unless BB_HEAT_HAZE is
# above 0; BB_HEAT_HAZE_PROOF is a test view (needs the haze on), its flag bit is 0 without it.
#
# What this patch is (honest statement, 2026-11-16): reading the code again finds NO broken link on the
# way from the pass to the upscaler, so this patch does not guess a number. It measures, and it gives a
# still that proves where the written pixels land.
#  Read and found right (cites the tree at build 53):
#   - the scene colour the pass writes IS the image the upscaler reads: the Rasterizer hands
#     upscaler->SceneColor() to HeatHaze::Apply, and TemporalUpscaler::Run reads the same ImageId
#     (native image, or with reduced scene targets the proxy scene_targets.Read(scene_color), which is
#     what the haze pass writes through scene_targets.Read(color_id, ..., Compute, ReadWrite)); the
#     halation pass at the same hook writes the same way and shows.
#   - the reactive mask is opt-in (BbSettings reactive, off by default) and, when on, is recorded at
#     the fog composite (OnSceneComposite: mask_ready), BEFORE the haze: the haze changes nothing in it.
#     So with the mask off or on, the temporal upscaler (DLSS, DLAA) gets the haze as plain colour and
#     no motion vector (RecordMotion has the camera only): its history is the one place that can lower a
#     1-2 pixel wobble of smooth fog or wall; the SHOW view at 4K (3x, with a tint) did show.
#   - the offset code: bilinear atlas read at the float source, no rounding to whole pixels; the
#     amplitude in pixels is shape.z (10 px per 1080 rows at strength 1), the weight at most 0.94.
#  So the first thing to know is the real size of the applied offset and whether pixels land where the
#  CPU puts the column. This patch adds both:
#   1. the haze pass counts the offset of every written pixel (render pixels): 8 bins (under 0.25,
#      0.5, 1, 2, 4, 8, 16 px, more), the sum (1/16 px) and the largest (1/16 px) into the counter
#      buffer (words 16 to 25; 26 words, 104 bytes). The log line "Heat haze (r97d)" gives, from the
#      differences since the last line: mean, the bin the 95th percentile falls in (its upper edge) and
#      the largest since the pass was made, in render pixels and in OUTPUT pixels (render x
#      native width / scene width), and says the proof tint's state. Once, at the first drawing frame, a
#      line says which image the pass writes (ImageId, handle, format, native and scene size, reduced
#      or not) and that the upscaler's colour input is that image (same id; the reduced proxy as above).
#   2. BB_HEAT_HAZE_PROOF=1 (TOOL view, with BB_HEAT_HAZE above 0): every WRITTEN pixel is mixed 30%
#      towards magenta (brightness: the pixel's own luma, at least a tenth of the flame pixel's), so a
#      still at 4K shows where the haze lands on the picture the upscaler outputs, with the real offset
#      (no 3x gain, unlike SHOW), at the strength given. Unlike SHOW=2's rectangle it marks the pixels
#      that really move.
#  The decision rule for the lead (after the 4K run, strength 2, PROOF=1 and the log):
#   - magenta visible in the still, offsets (output px) mean >= 2: the pass works and the upscaler's
#     history or the dark smooth background hides the wobble: raise the amplitude (not a pipeline bug) or
#     feed the shimmer to the upscaler as motion (a motion pass, a larger change: ask the owner), and
#     judge the shimmer in a clip only.
#   - no magenta at 4K but the counts say written > 0: something after the pass overwrites the scene
#     colour (find the next pass writing it); the image line says which image.
#   - magenta but offsets mean < 0.5 px: the numbers (amplitude, weight, scale) are at fault: fix them.
#
# Files: host_shaders/heat_haze_layout.h, host_shaders/heat_haze.comp, heat_haze.h (FlagProof, Knobs.proof,
# OffsetsBetween), vk_heat_haze.h/.cpp, tests/test_heat_haze.cpp (block m), README.md (a row, a number).
# Cost: off zero. On: per written pixel 2 shared-memory atomics more, a bin count (one more shared add),
# at most 9 buffer adds and one atomicMax a workgroup; the copy is 104 bytes instead of 64. Memory +40 B x2.
# Unverified: the C++ compile, the game. (review: the handle print casts VkImage, a pointer on 64-bit,
# through reinterpret_cast<std::uintptr_t>; static_cast of a pointer to an integer does not compile.)
#
# Use: python -I -X utf8 r97d_heat-haze-real-shimmer.py check | apply | revert
# Root: R97D_ROOT, else <tree>. Line ends kept. apply backs the originals up in r97d_backup next
# to this script.
import os, sys

ROOT = os.environ.get("R97D_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r97d_backup")
VC = "engine/gpu/shadps4/video_core/"
LAY = VC + "host_shaders/heat_haze_layout.h"
SH = VC + "host_shaders/heat_haze.comp"
HH = VC + "renderer_vulkan/heat_haze.h"
VH = VC + "renderer_vulkan/vk_heat_haze.h"
VCPP = VC + "renderer_vulkan/vk_heat_haze.cpp"
UT = "engine/tests/test_heat_haze.cpp"
RM = "README.md"

EDITS = {
LAY: [
("insert", "#define HH_FLAG_PROBE 8    // the frame's nearest column: its flame pixel's depth is kept\n", "",
 "#define HH_FLAG_PROOF 16   // BB_HEAT_HAZE_PROOF=1 (r97d): every written pixel mixed 30% towards magenta\n"),
("replace", "#define HH_WORDS 16u\n",
 "// (r97d) the offset of every written pixel, in render pixels: 8 bins (upper edges 0.25, 0.5, 1, 2, 4,\n"
 "// 8, 16 px, then more), their sum in 1/16 px, and the largest in 1/16 px (a running maximum).\n"
 "// Words 16 to 24 are counted per workgroup in shared memory like words 0 to 9.\n"
 "#define HH_WORD_OFF_BIN0 16u\n"
 "#define HH_OFF_BINS 8u\n"
 "#define HH_WORD_OFF_SUM 24u\n"
 "#define HH_WORD_OFF_MAX 25u\n"
 "#define HH_SHARED 25u // the shared counters: words 0 to 24 (10 to 15 stay zero there)\n"
 "#define HH_WORDS 26u\n"),
],
SH: [
("replace", "shared uint group_counts[HH_COUNTED];\n",
 "shared uint group_counts[HH_SHARED]; // (r97d: HH_COUNTED before)\nshared uint group_max;\n"),
("insert",
 "    imageStore(scene_img, p, vec4(rgb, imageLoad(atlas_img, own).a));\n    Count(HH_WORD_WRITTEN);\n",
 "    // (r97d) the offset this pixel took, in render pixels: bins, sum and largest, for the log\n"
 "    const float moved = length(offset);\n"
 "    const uint moved16 = uint(min(moved, 4000.0) * 16.0 + 0.5);\n"
 "    const uint bin = moved < 0.25 ? 0u : moved < 0.5 ? 1u : moved < 1.0 ? 2u : moved < 2.0 ? 3u\n"
 "                   : moved < 4.0 ? 4u : moved < 8.0 ? 5u : moved < 16.0 ? 6u : 7u;\n"
 "    Count(HH_WORD_OFF_BIN0 + bin);\n"
 "    atomicAdd(group_counts[HH_WORD_OFF_SUM], moved16);\n"
 "    atomicMax(group_max, moved16);\n"
 "    if ((atlas.w & HH_FLAG_PROOF) != 0) {\n"
 "        // Proof view: the written pixel 30% towards magenta, its own brightness (at least a tenth\n"
 "        // of the flame's), the real offset kept.\n"
 "        const vec3 flame_px = Atlas(atlas.xy + ivec2(floor(axis.xy)) - rect.xy).rgb;\n"
 "        const float proof_luma = max(dot(max(rgb, vec3(0.0)), luma_weights),\n"
 "                                     0.1 * dot(max(flame_px, vec3(0.0)), luma_weights));\n"
 "        rgb = mix(rgb, proof_luma * vec3(1.0, 0.0, 1.0), 0.3);\n"
 "    }\n", ""),
("replace",
 "    if (gl_LocalInvocationIndex < HH_COUNTED) {\n        group_counts[gl_LocalInvocationIndex] = 0u;\n    }\n",
 "    if (gl_LocalInvocationIndex < HH_SHARED) {\n        group_counts[gl_LocalInvocationIndex] = 0u;\n    }\n"
 "    if (gl_LocalInvocationIndex == 0u) {\n        group_max = 0u;\n    }\n"),
("replace",
 "    if (gl_LocalInvocationIndex < HH_COUNTED) {\n        const uint n = group_counts[gl_LocalInvocationIndex];\n"
 "        if (n != 0u) {\n            atomicAdd(words[gl_LocalInvocationIndex], n);\n        }\n    }\n",
 "    if (gl_LocalInvocationIndex < HH_SHARED) {\n        const uint n = group_counts[gl_LocalInvocationIndex];\n"
 "        if (n != 0u) {\n            atomicAdd(words[gl_LocalInvocationIndex], n);\n        }\n    }\n"
 "    if (gl_LocalInvocationIndex == 0u && group_max != 0u) { // (r97d) the largest offset\n"
 "        atomicMax(words[HH_WORD_OFF_MAX], group_max);\n    }\n"),
],
HH: [
("replace",
 "static_assert((FlagShow | FlagOutline | FlagNoDepth | FlagProbe) == 15, \"one bit each\");\n",
 "// bbport (r97d_heat-haze-real-shimmer)\n"
 "inline constexpr std::int32_t FlagProof = HH_FLAG_PROOF; ///< BB_HEAT_HAZE_PROOF=1: written pixels magenta\n"
 "static_assert((FlagShow | FlagOutline | FlagNoDepth | FlagProbe | FlagProof) == 31, \"one bit each\");\n"
 "static_assert(HH_WORD_OFF_BIN0 + HH_OFF_BINS == HH_WORD_OFF_SUM && HH_WORD_OFF_MAX == HH_WORD_OFF_SUM + 1 &&\n"
 "                  HH_WORD_OFF_MAX < HH_WORDS && HH_SHARED == HH_WORD_OFF_SUM + 1 && HH_SHARED <= 64 &&\n"
 "                  HH_WORD_FLAME_LAMP_Z < HH_WORD_OFF_BIN0,\n"
 "              \"the offset words follow the flame words; the shared counters fit one workgroup\");\n"),
("insert",
 "    bool depth = true;    ///< the depth tests (vk_heat_haze.cpp: DepthTests and not SHOW=2)\n", "",
 "    bool proof = false;   ///< (r97d) BB_HEAT_HAZE_PROOF=1 with a strength above 0: written pixels magenta\n"),
("insert", "/// What the counts say about a column that the CPU drew and the picture may not show.\n",
 "/// (r97d) The offsets of the written pixels between two reads of the counter words, in render pixels:\n"
 "/// the mean, the upper edge of the bin the 95th percentile falls in, and the largest since the pass\n"
 "/// was made (a running maximum).\n"
 "struct OffsetStats {\n"
 "    std::uint64_t pixels = 0;\n"
 "    double mean = 0.0, p95_below = 0.0, largest = 0.0;\n"
 "};\n"
 "inline OffsetStats OffsetsBetween(const std::uint32_t* now, const std::uint32_t* before) {\n"
 "    constexpr double Edge[HH_OFF_BINS] = {0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 4000.0};\n"
 "    OffsetStats s;\n"
 "    std::uint64_t bins[HH_OFF_BINS]{};\n"
 "    for (std::uint32_t i = 0; i < HH_OFF_BINS; ++i) {\n"
 "        bins[i] = std::uint32_t(now[HH_WORD_OFF_BIN0 + i] - before[HH_WORD_OFF_BIN0 + i]);\n"
 "        s.pixels += bins[i];\n"
 "    }\n"
 "    if (s.pixels != 0) {\n"
 "        s.mean = double(std::uint32_t(now[HH_WORD_OFF_SUM] - before[HH_WORD_OFF_SUM])) / 16.0 /\n"
 "                 double(s.pixels);\n"
 "        std::uint64_t seen = 0;\n"
 "        for (std::uint32_t i = 0; i < HH_OFF_BINS; ++i) {\n"
 "            seen += bins[i];\n"
 "            if (seen * 100 >= s.pixels * 95) {\n"
 "                s.p95_below = Edge[i];\n"
 "                break;\n"
 "            }\n"
 "        }\n"
 "    }\n"
 "    s.largest = double(now[HH_WORD_OFF_MAX]) / 16.0;\n"
 "    return s;\n"
 "}\n\n",
 ""),
],
VH: [
("insert", "    bool told_size = false;\n", "",
 "    // bbport (r97d_heat-haze-real-shimmer)\n"
 "    float out_scale = 1.0f;    ///< native width / scene width: render pixels -> output pixels\n"
 "    bool told_image = false;   ///< the line about the image the pass writes went out\n"),
],
VCPP: [
("insert",
 "        read.depth = BbHeatHaze::DepthTests(std::getenv(\"BB_HEAT_HAZE_DEPTH\")) && !read.outline;\n", "",
 "        // bbport (r97d_heat-haze-real-shimmer): BB_HEAT_HAZE_PROOF=1 (TOOL view): written pixels magenta\n"
 "        const char* proof = std::getenv(\"BB_HEAT_HAZE_PROOF\");\n"
 "        read.proof = read.strength > 0.0f && proof != nullptr && proof[0] == '1' && proof[1] == 0;\n"),
("insert",
 "                double(BbHeatHaze::AmplitudeM), double(BbHeatHaze::MaxAmplitudePx));\n", "",
 "    // bbport (r97d_heat-haze-real-shimmer)\n"
 "    std::printf(\"Heat haze (r97d): the log also counts the applied offset of every written pixel; proof \"\n"
 "                \"view (BB_HEAT_HAZE_PROOF=1, written pixels 30%% magenta) %s\\n\",\n"
 "                knobs.proof ? \"on\" : \"off\");\n"),
("replace",
 "                              (i + 1 == count ? BbHeatHaze::FlagProbe : 0);\n",
 "                              (i + 1 == count ? BbHeatHaze::FlagProbe : 0) |\n"
 "                              (knobs.proof ? BbHeatHaze::FlagProof : 0); // r97d\n"),
("insert", "    // Real time (wrapped, for the floats), so the shimmer rises at its speed at any frame rate.\n",
 "    // bbport (r97d_heat-haze-real-shimmer): render pixels -> output pixels, and once which image\n"
 "    // the pass writes: the one the upscaler is handed (Rasterizer: upscaler->SceneColor()), which\n"
 "    // TemporalUpscaler::Run reads by the same id (its reduced proxy when the scene is reduced).\n"
 "    out_scale = float(color.info.size.width) / float(width);\n"
 "    if (!told_image) {\n"
 "        told_image = true;\n"
 "        std::printf(\"Heat haze (r97d): the pass writes scene colour image id %u (handle %llx, format %d, \"\n"
 "                    \"native %ux%u, scene %ux%u, %s): the upscaler's colour input is that same id (%s), \"\n"
 "                    \"1 render pixel = %.2f output pixels\\n\",\n"
 "                    u32(color_id.index), static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(VkImage(color.GetImage()))),\n"
 "                    int(color.info.pixel_format), color.info.size.width, color.info.size.height, width,\n"
 "                    height, reduced ? \"through the reduced proxy\" : \"the native image\",\n"
 "                    reduced ? \"Run reads scene_targets.Read(scene_color) too\" : \"Run reads it directly\",\n"
 "                    double(out_scale));\n"
 "    }\n",
 ""),
("insert", "    counters_seen = now;\n",
 "    const auto previous = counters_seen; // bbport (r97d)\n", ""),
("insert",
 "                         word(HH_WORD_FLAME_FRONT));\n    }\n", "",
 "    // bbport (r97d_heat-haze-real-shimmer): the offsets the written pixels really took\n"
 "    const auto o = BbHeatHaze::OffsetsBetween(now.data(), previous.data());\n"
 "    const double k = double(out_scale);\n"
 "    BbReport::Printf(\"Heat haze (r97d): offset of %llu written pixels, render px: mean %.2f, 95%% under \"\n"
 "                     \"%.2f, largest since start %.2f; output px (x%.2f): mean %.2f, 95%% under %.2f, \"\n"
 "                     \"largest %.2f; proof view %s\\n\",\n"
 "                     ull(o.pixels), o.mean, o.p95_below, o.largest, k, o.mean * k, o.p95_below * k,\n"
 "                     o.largest * k, knobs.proof ? \"on\" : \"off\");\n"),
],
UT: [
("insert", "    std::printf(\"heat-haze-test: all checks passed\\n\");\n",
 "    // m. bbport (r97d_heat-haze-real-shimmer): the offset counters, the flag and the report.\n"
 "    {\n"
 "        static_assert(CounterWords == HH_WORD_OFF_MAX + 1);\n"
 "        std::array<std::uint32_t, CounterWords> before{}, now{};\n"
 "        const auto none = OffsetsBetween(now.data(), before.data());\n"
 "        assert(none.pixels == 0 && none.mean == 0.0 && none.p95_below == 0.0 && none.largest == 0.0);\n"
 "        now[HH_WORD_OFF_BIN0 + 2] = 90; // 90 pixels of 0.5 to 1 px\n"
 "        now[HH_WORD_OFF_BIN0 + 4] = 10; // 10 of 2 to 4 px\n"
 "        now[HH_WORD_OFF_SUM] = 16u * 100u; // 100 px in all\n"
 "        now[HH_WORD_OFF_MAX] = 16u * 3u;   // largest 3 px\n"
 "        const auto s = OffsetsBetween(now.data(), before.data());\n"
 "        assert(s.pixels == 100 && Near(float(s.mean), 1.0f, 1e-4f) && s.p95_below == 4.0 &&\n"
 "               Near(float(s.largest), 3.0f, 1e-4f));\n"
 "        before = now; // a second read with nothing new: the counts are differences, the maximum is not\n"
 "        const auto again = OffsetsBetween(now.data(), before.data());\n"
 "        assert(again.pixels == 0 && Near(float(again.largest), 3.0f, 1e-4f));\n"
 "        before[HH_WORD_OFF_BIN0] = 0xfffffff0u; // a total that wrapped\n"
 "        now[HH_WORD_OFF_BIN0] = 0x10u;\n"
 "        assert(OffsetsBetween(now.data(), before.data()).pixels == 0x20u);\n"
 "        assert((FlagProof & (FlagShow | FlagOutline | FlagNoDepth | FlagProbe)) == 0);\n"
 "        assert(!Parse(\"1\", nullptr).proof); // read in vk_heat_haze.cpp, off in Parse\n"
 "    }\n", ""),
],
RM: [
("replace", "one 64-byte copy a frame that draws columns | on |\n",
 "one 104-byte copy a frame that draws columns (r97d: 64 before; it also counts the offset every written pixel took) | on |\n"
 "| `BB_HEAT_HAZE_PROOF` | Test view (r97d), with `BB_HEAT_HAZE` above 0: `1` mixes every pixel the haze really writes 30% towards magenta (its own brightness, at least a tenth of the flame's), at the real shimmer (no 3 times gain as `BB_HEAT_HAZE_SHOW`), so a still at any output size shows where the haze lands on the picture the upscaler gives. The log's `Heat haze (r97d)` lines say which image the pass writes, and, after the first 120 frames and then every 600, the mean, the 95th percentile (its bin's upper edge) and the largest offset of the written pixels, in render and in output pixels | off |\n"),
],
}
PATHS = (LAY, SH, HH, VH, VCPP, UT, RM)


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        raise SystemExit("%s is missing (are r97, r97b and r97c applied?)" % path)
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    done = todo = 0
    for ed in eds:
        if ed[0] == "insert":
            _, anchor, before, after = ed
            parts = [t for t in (before, after) if t]
            na, counts = cur.count(anchor), [cur.count(t) for t in parts]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                                 % (path, na, counts, anchor[:70]))
        else:
            _, old, new = ed
            no, nn = cur.count(old), cur.count(new)
            if no == 0 and nn == 1:
                done += 1
            elif no == 1 and nn == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times, its new text %d times: %r"
                                 % (path, no, nn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_edits(cur, eds):
    for ed in eds:
        if ed[0] == "insert":
            _, anchor, before, after = ed
            cur = cur.replace(anchor, before + anchor + after, 1)
        else:
            cur = cur.replace(ed[1], ed[2], 1)
    return cur


def revert_edits(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "insert":
            _, anchor, before, after = ed
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        else:
            cur = cur.replace(ed[2], ed[1], 1)
    return cur


def text_checks(t):
    if "HH_FLAG_PROOF" not in t[LAY] or "#define HH_WORDS 26u" not in t[LAY]:
        raise SystemExit("text check: layout")
    if t[SH].count("HH_FLAG_PROOF") != 1 or t[SH].count("group_max") < 4:
        raise SystemExit("text check: shader")
    c = t[VCPP]
    if c.find("Heat haze (r97c): shimmer up to") > c.find("Heat haze (r97d): the log also counts"):
        raise SystemExit("text check: the once-line is not after r97c's")
    if t[UT].find("// l. bbport (r97c") > t[UT].find("// m. bbport (r97d"):
        raise SystemExit("text check: the unit test block is out of place")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R97D_ROOT)" % ROOT)
    plan, states = [], []
    for path in PATHS:
        raw, eol, cur = load(path)
        if path == VCPP and "Heat haze (r97c)" not in cur:
            raise SystemExit("%s: r97c is not applied" % path)
        states.append((path, state_of(cur, EDITS[path], path)))
        plan.append((path, EDITS[path], raw, eol, cur))
    kinds = {s for _, s in states}
    if len(kinds) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % p for p in states))
    state = kinds.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur in plan:
            res = apply_edits(cur, eds)
            if state_of(res, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = res
        return out

    def write(items):
        for path, data in items:
            full = os.path.join(ROOT, path)
            tmp = full + ".r97dtmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, full)

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        write([(p[0], texts[p[0]].replace("\n", p[3]).encode("utf-8")) for p in plan])
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = []
    for path, eds, raw, eol, cur in plan:
        res = revert_edits(cur, eds)
        if state_of(res, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out.append((path, res.replace("\n", eol).encode("utf-8")))
    write(out)
    print("reverted")


main()
