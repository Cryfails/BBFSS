# r111i_prints-wet-church: FEATURE fix on top of r111 to r111h (b49: the graveyard's blood prints are dark red boot soles
# and the hat is clean; the church's wet prints were called invisible (off against on 0.73 = noise), gb1 showed only
# faint specks, and one small red mark by the hunter's leg may still be a stamp on the character). Still off unless
# BB_FOOTPRINTS is set and still costs nothing when off (every edit is inside Footprints, which is not made without
# the knob, or inside the post stamp's shader, which only that object dispatches). Branch: visual/footprints.
#
# WHAT THE b49 PICTURES SHOW (read before this patch): slot_r111h-cp1_back_post2.jpg against ..._back_off.jpg, cropped
# and enlarged: the wet prints ARE stamped on the lit slabs (dark blobs about 10 m behind the hunter, absent in the
# off picture); the near prints, 3 to 4 m behind the hunter, lie on near-black slabs where a multiply cannot show
# (a luminance of 0.005 times 0.45 is invisible); and the pixel-difference metric is blind to a few thousand pixels
# (0.1% of the picture). So the stamp reaches the church slabs; this patch makes it readable and proves it by number.
#
# WHAT CHANGES
#  (1) Wet and mud prints (footprints_flat.comp, footprints_layout.h): the weight is rounded as a blood print's already
#      is, 1 - (1 - w)^2 (a faded print of 0.4 reads 0.64, so the tail of a trail stays visible); the soft edge of the
#      wet sole starts at 70% of its radius (POST_WET_EDGE 0.70, was 0.55), a firmer boot outline; the darkening stays
#      55% (the lit luminance times 0.45 at full weight), a hard multiply with no gloss or specular. NEW PROOF: the
#      shader counts, for every stamped pixel (weight above 1/64), the lit luminance before and after the stamp
#      (fixed point, capped at 4), separately for wet or mud and for blood pixels, in six new counter words (36 to 41,
#      FLAT_WORDS 42). The log line "Footprints (r111i): lit luminance under the post stamp: wet or mud N px, mean X
#      before, Y after (xR); blood ..." (at construction as zeros, at frame 240 and every 600 frames) says what the
#      pass did where it wrote: on lit church slabs the ratio is about 0.45 to 0.6 (edge pixels count too), on near
#      black stone the means are both tiny (and that is the honest reason a print there cannot be seen).
#  (2) A stamp on the character (footprints_flat.comp): a pixel within SILHOUETTE_FRAC x the picture height (0.5%, 5 px
#      at 1080 lines, at least 2) to the left, right, above or below of a surface more than SILHOUETTE_M + SILHOUETTE_REL x
#      z (0.2 m + 3% of its view depth) NEARER than itself is next to something in front of it (the hunter's leg or
#      weapon beside the newest print): it is left out. r111h's rule (a pixel much nearer than the print) cannot see a
#      boot, which stands at the print's own depth; this one reads the depth buffer around the pixel. A cobble step
#      of 0.15 m or a taller slab edge 0.3 m away along the view is kept (the margin at 4 m is 0.32 m). Four more depth
#      reads, only for pixels that already carry a print weight above 1/64.
#  (3) Jobs (slot_jobs_r111i_prints-wet-church.json): graveyard-blood gb1 with ONE short walk (the coat picked up in the
#      pool gives 1, 0.8, 0.64 ... so the prints stay strong and 2 to 5 m from the camera), gbw = the same sequence with
#      the coat forced to WET (BB_FOOTPRINTS_COAT=wet, a test) so wet prints are judged on moonlit cobbles at 3 to 5 m
#      where the blood prints already read; cp1 church-puddles as before with the new log line; dh1 do-nothing. Every
#      pair is ONE game with live set: of BB_FOOTPRINTS_GAIN and NO pad action between the on and the off picture.
#
# How the code guarantees nothing runs when the feature is off: BB_FOOTPRINTS unset -> Footprints is not made, its hook
# is one null pointer test, and nothing here is reached (LogLuma is called only from its constructor and OnFrameEnd; the
# shader edits run only inside the post stamp's dispatch). Cost: four more depth reads for each pixel of a print box
# whose weight is above 1/64 (typically 3000 pixels), three more atomics a stamped pixel (same cache line as the
# existing one: the counters are 168 bytes); the counter buffer grows from 144 to 168 bytes. Memory: about 80 bytes.
#
# Files edited (the text r111h left; each old text found exactly once): footprints_layout.h, footprints_flat.comp,
# footprints.h, vk_footprints.h, vk_footprints.cpp, engine/tests/test_footprints.cpp, README.md.
# r111h's own `check` refuses after this patch (its text check wants the old wet edge text); revert r111i before r111h.
#
# Order: needs r111h applied (refused otherwise).
# Use: python -I -X utf8 r111i_prints-wet-church.py check | apply | revert
# Root: R111I_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r111i_backup next to this script; revert puts each old text back (each new text found by itself, exactly once).
import os, re, sys

ROOT = os.environ.get("R111I_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r111i_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RULES = RV + "footprints.h"
VKH = RV + "vk_footprints.h"
VKC = RV + "vk_footprints.cpp"
LAYOUT = HS + "footprints_layout.h"
FLAT = HS + "footprints_flat.comp"
TEST = "engine/tests/test_footprints.cpp"
README = "README.md"
ORDER = [LAYOUT, FLAT, RULES, VKH, VKC, TEST, README]

# (old, new): `old` found exactly once and `new` not at all (clean), or `new` exactly once (applied).
EDITS = {
    LAYOUT: [
        (r'''#define FOOTPRINTS_FLAT_WORDS 36u
''',
         r'''// (r111i) Six more counter words after the probes, for every stamped pixel (weight above 1/64): the number of
// pixels, the sum of the lit luminance before the stamp and the sum after it, each times LUM_SCALE with the
// luminance capped at LUM_CAP (the sums wrap past 65536 pixels a pass), for wet and mud prints (words LUM + 0 to 2)
// and for blood prints (LUM + 3 to 5): the proof of what the stamp did where it wrote. A pixel counts as blood
// where the blood weight is above the wet and mud ones.
#define FOOTPRINTS_FLAT_WORD_LUM 36u
#define FOOTPRINTS_FLAT_LUM_WORDS 6u
#define FOOTPRINTS_FLAT_LUM_SCALE 16384.0
#define FOOTPRINTS_FLAT_LUM_CAP 4.0
#define FOOTPRINTS_FLAT_WORDS 42u
'''),
        (r'''#define FOOTPRINTS_POST_WET_EDGE 0.55
''',
         r'''// (r111i) a firmer wet outline: the soft edge starts at 70% of the radius (was 55%); blood keeps EDGE (82%).
#define FOOTPRINTS_POST_WET_EDGE 0.70
'''),
        (r'''#define FOOTPRINTS_POST_BLOOD_COVER 0.95
''',
         r'''#define FOOTPRINTS_POST_BLOOD_COVER 0.95
// (r111i) Next to something in front: a pixel with a surface more than SILHOUETTE_M + SILHOUETTE_REL x its own view
// z NEARER at SILHOUETTE_FRAC x the picture height (at least 2 pixels) to its left, right, above or below is beside
// the hunter's leg or weapon (or a plant), not on the print: it is left out.
#define FOOTPRINTS_POST_SILHOUETTE_FRAC 0.005
#define FOOTPRINTS_POST_SILHOUETTE_M 0.2
#define FOOTPRINTS_POST_SILHOUETTE_REL 0.03
'''),
    ],
    FLAT: [
        (r'''    // The up-facing share from two neighbours (the right or left one, the lower or upper one).
    const ivec2 last = ivec2(size) - 1;
''',
         r'''    const ivec2 last = ivec2(size) - 1;
    { // (r111i) next to something much nearer (the hunter's leg or weapon, a plant): not on the print
        const int sp = max(2, int(size.y * FOOTPRINTS_POST_SILHOUETTE_FRAC + 0.5));
        const float lim = FOOTPRINTS_POST_SILHOUETTE_M + FOOTPRINTS_POST_SILHOUETTE_REL * z;
        const ivec2 taps[4] = ivec2[4](ivec2(sp, 0), ivec2(-sp, 0), ivec2(0, sp), ivec2(0, -sp));
        float zt[4];
        for (int k = 0; k < 4; ++k) {
            const float zq = ViewZ(texelFetch(depth_tex, clamp(p + taps[k], ivec2(0), last), 0).x);
            zt[k] = zq > 0.0 ? zq : z; // the sky or off the picture: no step
        }
        // (review) against the straight line through both opposite taps (2z - a - b), not one tap alone: a level
        // floor's own depth slope (about 0.6 m over 5 px at 13 m) is not a step and must not erase far prints
        if (2.0 * z - zt[0] - zt[1] > lim || 2.0 * z - zt[2] - zt[3] > lim) {
            return;
        }
    }
    // The up-facing share from two neighbours (the right or left one, the lower or upper one).
'''),
        (r'''    const float wet = clamp(weight[FOOTPRINTS_KIND_WET] * face * gain, 0.0, 1.0);
    const float mud = clamp(weight[FOOTPRINTS_KIND_MUD] * face * gain, 0.0, 1.0);
''',
         r'''    // (r111i) wet and mud weights are rounded as the blood weight is, 1 - (1 - w)^2: a faded print stays readable
    const float wet_w = clamp(weight[FOOTPRINTS_KIND_WET] * face * gain, 0.0, 1.0);
    const float mud_w = clamp(weight[FOOTPRINTS_KIND_MUD] * face * gain, 0.0, 1.0);
    const float wet = 1.0 - (1.0 - wet_w) * (1.0 - wet_w);
    const float mud = 1.0 - (1.0 - mud_w) * (1.0 - mud_w);
'''),
        (r'''    imageStore(color_img, p, vec4(rgb, c.a));
    atomicAdd(counts[FOOTPRINTS_FLAT_WORD_POST_PX], 1u);
}
''',
         r'''    imageStore(color_img, p, vec4(rgb, c.a));
    atomicAdd(counts[FOOTPRINTS_FLAT_WORD_POST_PX], 1u);
    { // (r111i) the lit luminance before and after the stamp, by kind: what the pass did where it wrote
        const uint lw = FOOTPRINTS_FLAT_WORD_LUM + (blood > max(wet, mud) ? 3u : 0u);
        const float after = dot(rgb, vec3(0.2126, 0.7152, 0.0722));
        atomicAdd(counts[lw], 1u);
        atomicAdd(counts[lw + 1u], uint(clamp(lum, 0.0, FOOTPRINTS_FLAT_LUM_CAP) * FOOTPRINTS_FLAT_LUM_SCALE + 0.5));
        atomicAdd(counts[lw + 2u], uint(clamp(after, 0.0, FOOTPRINTS_FLAT_LUM_CAP) * FOOTPRINTS_FLAT_LUM_SCALE + 0.5));
    }
}
'''),
    ],
    RULES: [
        (r'''static_assert(WordFlatRedPx == 0u && WordFlatPostPx == 1u && WordFlatGroups == 2u && WordFlatStamp == 3u &&
              WordFlatProbe == 4u && FlatWords == WordFlatProbe + FlatProbes * FlatProbeWords);
''',
         r'''// (r111i) six more words after the probes: pixels, luminance before, luminance after, for wet or mud, then blood
inline constexpr std::uint32_t WordFlatLum = FOOTPRINTS_FLAT_WORD_LUM;
inline constexpr std::uint32_t FlatLumWords = FOOTPRINTS_FLAT_LUM_WORDS;
static_assert(WordFlatRedPx == 0u && WordFlatPostPx == 1u && WordFlatGroups == 2u && WordFlatStamp == 3u &&
              WordFlatProbe == 4u && WordFlatLum == WordFlatProbe + FlatProbes * FlatProbeWords &&
              FlatLumWords == 6u && FlatWords == WordFlatLum + FlatLumWords);
'''),
    ],
    VKH: [
        (r'''        u64 stamp_px_sum = 0; ///< (r111h) the post stamp's pixels, summed over the read-backs
''',
         r'''        u64 stamp_px_sum = 0; ///< (r111h) the post stamp's pixels, summed over the read-backs
        /// (r111i) over the read-backs, [0] wet or mud pixels, [1] blood pixels: their number and the summed lit
        /// luminance before and after the stamp (times FOOTPRINTS_FLAT_LUM_SCALE)
        std::array<u64, 2> lum_px{}, lum_before{}, lum_after{};
'''),
        (r'''    void LogTotals() const; // (r111h)
''',
         r'''    void LogTotals() const; // (r111h)
    void LogLuma() const;   // (r111i)
'''),
    ],
    VKC: [
        (r'''        LogTotals();                               // (r111h) a zero copy
''',
         r'''        LogTotals();                               // (r111h) a zero copy
        LogLuma();                                 // (r111i) a zero copy
'''),
        (r'''                     double(FOOTPRINTS_POST_NEAR_FRAC) * 100.0, int(FOOTPRINTS_POST_NORMAL_PX));
''',
         r'''                     double(FOOTPRINTS_POST_NEAR_FRAC) * 100.0, int(FOOTPRINTS_POST_NORMAL_PX));
    BbReport::Printf("Footprints (r111i): wet and mud weights rounded 1 - (1 - w)^2, wet edge from %.2f of the radius; a "
                     "pixel next to a surface more than %.2f m + %.0f%% of its depth nearer (%.1f%% of the picture "
                     "height away) is left out\n",
                     double(FOOTPRINTS_POST_WET_EDGE), double(FOOTPRINTS_POST_SILHOUETTE_M),
                     double(FOOTPRINTS_POST_SILHOUETTE_REL) * 100.0, double(FOOTPRINTS_POST_SILHOUETTE_FRAC) * 100.0);
'''),
        (r'''void Footprints::FlatProbeRead(const std::array<u32, R::FlatWords>& counts) {
''',
         r'''/// (r111i) What the post stamp did to the pixels it wrote: the mean lit luminance before and after, by kind
/// (summed over the read-backs; fixed point, FOOTPRINTS_FLAT_LUM_SCALE). A place where nothing is stamped says 0 px.
void Footprints::LogLuma() const {
    const auto mean = [](u64 sum, u64 px) {
        return px != 0u ? double(sum) / (double(px) * FOOTPRINTS_FLAT_LUM_SCALE) : 0.0;
    };
    const auto ratio = [](u64 before, u64 after) {
        return before != 0u ? double(after) / double(before) : 0.0;
    };
    BbReport::Printf("Footprints (r111i): lit luminance under the post stamp: wet or mud %llu px, mean %.4f before, "
                     "%.4f after (x%.2f); blood %llu px, mean %.4f before, %.4f after (x%.2f)\n",
                     static_cast<unsigned long long>(stats.lum_px[0]), mean(stats.lum_before[0], stats.lum_px[0]),
                     mean(stats.lum_after[0], stats.lum_px[0]), ratio(stats.lum_before[0], stats.lum_after[0]),
                     static_cast<unsigned long long>(stats.lum_px[1]), mean(stats.lum_before[1], stats.lum_px[1]),
                     mean(stats.lum_after[1], stats.lum_px[1]), ratio(stats.lum_before[1], stats.lum_after[1]));
}

void Footprints::FlatProbeRead(const std::array<u32, R::FlatWords>& counts) {
'''),
        (r'''        stats.stamp_px_sum += px; // (r111h)
''',
         r'''        stats.stamp_px_sum += px; // (r111h)
        for (u32 k = 0; k < 2; ++k) { // (r111i) wet or mud, then blood: pixels, luminance before, after
            const u32* lw = counts.data() + R::WordFlatLum + k * 3u;
            stats.lum_px[k] += lw[0];
            stats.lum_before[k] += lw[1];
            stats.lum_after[k] += lw[2];
        }
'''),
        (r'''        LogTotals(); // (r111h)
''',
         r'''        LogTotals(); // (r111h)
        LogLuma();   // (r111i)
'''),
    ],
    TEST: [
        (r'''        assert(FlatWords == 36u && WordFlatRedPx != WordFlatPostPx);
''',
         r'''        assert(FlatWords == 42u && WordFlatRedPx != WordFlatPostPx); // (r111i) six luminance words
'''),
        (r'''        assert(FOOTPRINTS_POST_NORMAL_PX >= 2 && FOOTPRINTS_POST_NEIGHBOUR_M > 0.05 && FOOTPRINTS_POST_NEIGHBOUR_REL < 0.2);
''',
         r'''        assert(FOOTPRINTS_POST_NORMAL_PX >= 2 && FOOTPRINTS_POST_NEIGHBOUR_M > 0.05 && FOOTPRINTS_POST_NEIGHBOUR_REL < 0.2);
        // (r111i) the wet look: a firmer edge than r111h's 0.55 but softer than the blood edge; the rounded weight
        // of a faded wet print (0.4 reads 0.64); the silhouette rule: the margin at 4 m is 0.32 m, so a cobble step
        // of 0.15 m is kept and a hunter's leg 0.5 m nearer is left out; the pixel offset is 5 at 1080 lines, at
        // least 2 at 360
        assert(FOOTPRINTS_POST_WET_EDGE > 0.55 && FOOTPRINTS_POST_WET_EDGE < FOOTPRINTS_EDGE);
        assert(Near(1.0 - (1.0 - 0.4) * (1.0 - 0.4), 0.64));
        const auto next_to_nearer = [](double z, double zq) {
            return zq < z - (FOOTPRINTS_POST_SILHOUETTE_M + FOOTPRINTS_POST_SILHOUETTE_REL * z);
        };
        assert(!next_to_nearer(4.0, 3.85) && next_to_nearer(4.0, 3.5) && !next_to_nearer(4.0, 4.5));
        assert(next_to_nearer(10.0, 9.4) && !next_to_nearer(10.0, 9.6));
        const auto tap_px = [](double height) {
            const int v = int(height * FOOTPRINTS_POST_SILHOUETTE_FRAC + 0.5);
            return v > 2 ? v : 2;
        };
        assert(tap_px(1080.0) == 5 && tap_px(360.0) == 2 && tap_px(720.0) == 4);
        // the luminance counters: six words after the probes, fixed point whose cap fits 65536 pixels in 32 bits
        assert(FOOTPRINTS_FLAT_WORD_LUM == FOOTPRINTS_FLAT_WORD_PROBE + FOOTPRINTS_FLAT_PROBES * FOOTPRINTS_FLAT_PROBE_WORDS);
        assert(FOOTPRINTS_FLAT_WORDS == FOOTPRINTS_FLAT_WORD_LUM + FOOTPRINTS_FLAT_LUM_WORDS);
        assert(FOOTPRINTS_FLAT_LUM_CAP * FOOTPRINTS_FLAT_LUM_SCALE * 65536.0 <= 4294967296.0);
'''),
    ],
    README: [
        (r'''and the facing is read from points 3 pixels away; times''',
         r'''and the facing is read from points 3 pixels away; (r111i) a wet or mud print's weight is rounded like a blood print's, 1 - (1 - w)^2, its soft edge starts at 70% of the sole's radius, and a pixel next to a surface much nearer than itself (more than 0.2 m + 3% of its depth, 0.5% of the picture height to its left, right, above or below: the hunter's leg or weapon beside the print) is left out; the log says what the stamp did to the lit luminance of the pixels it wrote, by kind; times'''),
    ],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    """'applied' (each new text once), 'clean' (each old text once, no new text), else refuse."""
    done = todo = 0
    for old, new in eds:
        co, cn = cur.count(old), cur.count(new)
        if cn == 1 and (co == 0 or new.find(old) >= 0 and co == 1):
            done += 1
        elif cn == 0 and co == 1:
            todo += 1
        else:
            raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1 and 0, or 0 or 1 "
                             "and 1; is r111h applied, and is this patch's own earlier version reverted?): %r" %
                             (path, co, cn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, done, len(eds)))


def split_args(text):
    """The top-level comma separated arguments of a call's text after its format string."""
    out, depth, cur, quote = [], 0, "", False
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            cur += ch
            if ch == "\\":
                cur += text[i + 1]
                i += 1
            elif ch == '"':
                quote = False
        elif ch == '"':
            quote = True
            cur += ch
        elif ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    if cur.strip():
        out.append(cur.strip())
    return out


def define(lay, name):
    m = re.search(r"#define %s ([0-9.]+)u?\n" % name, lay)
    if not m:
        raise SystemExit("text check: layout lacks %s" % name)
    return float(m.group(1))


def text_checks(texts):
    """Ties a compiler cannot check, on the full result."""
    cpp = texts[VKC]
    n_new = 0
    for m in re.finditer(r'BbReport::Printf\(((?:\s*"(?:[^"\\]|\\.)*")+)(.*?)\);\n', cpp, re.S):
        fmt = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))).replace("\\n", "")
        if not fmt.startswith("Footprints (r111"):
            raise SystemExit("text check: a log line without its prefix: %r" % fmt[:60])
        if not fmt.startswith("Footprints (r111i)"):
            continue
        n_new += 1
        convs = re.findall(r"%(?!%)[-+ 0-9.]*(?:ll)?[udfs]", fmt.replace("%%", ""))
        args = split_args(m.group(2).lstrip().lstrip(",")) if m.group(2).strip() else []
        if len(convs) != len(args):
            raise SystemExit("text check: %d conversions, %d arguments: %r" % (len(convs), len(args), fmt[:70]))
        if "%s" in fmt:
            raise SystemExit("text check: a %%s in an r111i line (kinds fold on digits only): %r" % fmt[:60])
        wide = re.sub(r"%[-+]?[0-9]*\.[0-9]+f", "X" * 9, fmt)
        wide = re.sub(r"%(?:ll)?[ud]", "X" * 10, wide)
        wide = wide.replace("%%", "%")
        print("  r111i log line (wide %d, %d conversions): %s..." % (len(wide), len(convs), fmt[:50]))
        if len(wide) > 300:
            raise SystemExit("text check: a log line may pass 300 characters (%d): %r" % (len(wide), fmt[:60]))
    if n_new != 2:
        raise SystemExit("text check: %d r111i log lines (2 expected)" % n_new)
    if cpp.count("LogLuma()") < 3:
        raise SystemExit("text check: LogLuma calls missing")
    lay = texts[LAYOUT]
    wd = define(lay, "FOOTPRINTS_POST_WET_DARKEN")
    we = define(lay, "FOOTPRINTS_POST_WET_EDGE")
    if not (0.45 < wd < 0.6) or not (0.55 < we < define(lay, "FOOTPRINTS_EDGE")):
        raise SystemExit("text check: wet darken %.2f or wet edge %.2f out of range" % (wd, we))
    print("  wet multiply at full weight %.2f, edge from %.2f of the radius" % (1.0 - wd, we))
    probe = define(lay, "FOOTPRINTS_FLAT_WORD_PROBE")
    lum = define(lay, "FOOTPRINTS_FLAT_WORD_LUM")
    words = define(lay, "FOOTPRINTS_FLAT_WORDS")
    n_probe = define(lay, "FOOTPRINTS_FLAT_PROBES") * define(lay, "FOOTPRINTS_FLAT_PROBE_WORDS")
    if lum != probe + n_probe or define(lay, "FOOTPRINTS_FLAT_LUM_WORDS") != 6 or words != lum + 6:
        raise SystemExit("text check: the counter words do not tie (probe %d, lum %d, words %d)" % (probe, lum, words))
    cap, scale = define(lay, "FOOTPRINTS_FLAT_LUM_CAP"), define(lay, "FOOTPRINTS_FLAT_LUM_SCALE")
    if cap * scale * 65536.0 > 4294967296.0:
        raise SystemExit("text check: the luminance counters can wrap under 65536 pixels")
    for name in ("FOOTPRINTS_POST_SILHOUETTE_FRAC", "FOOTPRINTS_POST_SILHOUETTE_M", "FOOTPRINTS_POST_SILHOUETTE_REL"):
        define(lay, name)
    # the shader uses every new define; the sums are three atomics a stamped pixel
    flat = texts[FLAT]
    for needle in ("FOOTPRINTS_POST_SILHOUETTE_FRAC", "FOOTPRINTS_POST_SILHOUETTE_M", "FOOTPRINTS_POST_SILHOUETTE_REL",
                   "FOOTPRINTS_FLAT_WORD_LUM", "FOOTPRINTS_FLAT_LUM_CAP", "FOOTPRINTS_FLAT_LUM_SCALE",
                   "const float wet = 1.0 - (1.0 - wet_w) * (1.0 - wet_w);"):
        if needle not in flat:
            raise SystemExit("text check: footprints_flat.comp lacks %r" % needle)
    if flat.count("atomicAdd(counts[lw") != 3:
        raise SystemExit("text check: the shader should add three luminance words")
    if "FlatWords == WordFlatLum + FlatLumWords" not in texts[RULES]:
        raise SystemExit("text check: footprints.h does not tie the counter words")
    if "std::array<u64, 2> lum_px{}" not in texts[VKH] or "void LogLuma() const;" not in texts[VKH]:
        raise SystemExit("text check: vk_footprints.h lacks the luminance totals")
    if "stats.lum_before[k] += lw[1];" not in cpp:
        raise SystemExit("text check: the luminance sums are not collected")
    if "next_to_nearer(4.0, 3.5)" not in texts[TEST]:
        raise SystemExit("text check: the unit test lacks the silhouette model")
    if texts[README].count("(r111i) a wet or mud print's weight is rounded") != 1:
        raise SystemExit("text check: README lacks the r111i text once")
    for path, eds in EDITS.items():
        for old, new in eds:
            if "\t" in new or "\r" in new:
                raise SystemExit("text check: an edit of %s has a tab or a CR" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 r111i_prints-wet-church.py check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R111I_ROOT)" % ROOT)
    if "(r111h) a pixel much nearer the camera than the print" not in load(FLAT)[2]:
        raise SystemExit("REFUSED: r111h is not applied (%s lacks its nearer-pixel rule)" % FLAT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in eds:
                cur = cur.replace(old, new, 1)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (%d files edited; text checks pass)" % len(plan))
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)" %
                  (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r111itmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied (%d files edited)" % len(plan))
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for old, new in reversed(eds):
            if cur.count(new) != 1:
                raise SystemExit("%s: new text found %d times in the revert: %r" % (path, cur.count(new), new[:70]))
            cur = cur.replace(new, old, 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r111itmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted (%d files edited back)" % len(plan))


main()
