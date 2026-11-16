# r119h_clouds-freeze-sheet: TOOL (test aid; the live code is compiled only with the test tools' live knobs header, so a
# feature branch without it carries none of it; the pure parsers and the drift-source log line are tiny and harmless).
# On top of r119g_clouds-smear-and-cover.fixed.py (and r119 to r119f). BB_VOLUMETRIC_CLOUDS=1 only: nothing here runs
# without the CloudLayer object (made only with BB_VOLUMETRIC_CLOUDS starting with 1), and the two knobs below do nothing
# unless the live knobs file / the environment names them.
#
# Why (b52, owner's MORNING QUESTION sheet): the option set worked (every live knob taken in 0.3-0.6 s) but the cloud
# field kept moving during the sheet: BB_VOLUMETRIC_CLOUDS_SPEED=0.25 still logged 1.5 m/s and the covered share fell
# 0.228 -> 0.150 at unchanged cover, so default vs default 20 s later differed 11.0, as much as any option.
#
# WHY SPEED=0.25 DOES NOT FREEZE THE FIELD (read from the code, proven by the new r119h lines): there is no wind follower
# overriding the knob. The layer's offsets (layer_drift) move by LayerWind = DriftVelocity(heading, LayerSpeed, size):
#  (a) the advect: LayerSpeed = the one wind's cloud speed held to 2.5-8 m/s (here 6.0) x the SPEED knob, whose floor is
#      0.25: 6.0 x 0.25 = 1.5 m/s, the figure in the log; and
#  (b) the MORPH, which the knob does NOT scale: the lattice's third axis moves one cell of the biggest octave per 120 s
#      (800 m / 120 s = 6.7 m/s equivalent, the finer octaves 1.3 and 1.7 times faster per cell). That is 4x the advect at
#      SPEED 0.25 and is what changes the SHAPE of the field (covered share 0.228 -> 0.150 in 20 s).
# So no speed value stops the field. FIX (1): BB_VOLUMETRIC_CLOUDS_FREEZE=1 (a live knob): the layer's offsets get a zero
# wind (VolumetricFogNoise::Drift::Advance with {0, 0, 0} keeps its clock and leaves the cells exactly as they were: they
# are already in [0, Period), so WrapCells(x + 0) = x), advect and morph both. The follower / heading
# (CloudShadow state) is not an input of the offsets, so nothing else can move them. 0 or unset: the call is the very
# same arithmetic as before (byte for byte). A frozen field resumes from where it stopped; the clock is kept, so
# no jump (Drift clamps one step to 1 s anyway).
# LOG (the drift source): the periodic r119h line says the wind's cloud speed, its held range, the knob, the advect, the
# morph in m/s equivalent and octave 0's offset in cells; a change of the freeze says itself once.
# FIX (3): BB_VOLUMETRIC_CLOUDS_MARK=<n> (live, a whole number 1 to 999999, a change of it counts): after 4 drawn frames
# (the counters are a frame or two old) the next 12 frames' counters are summed apart and ONE line is said with the mark:
# "sheet mark n over F frames: sky px share, covered share, visible share, mean opacity; cover, contrast, tint, smear fix,
# frozen, octave 0 offset". The job sets the mark together with each option, so every picture of the sheet has its
# covered share line (and the offsets prove the field stood still: equal digits in every line). After 240 frame ends
# without the frames (no sky drawn) the line is said with what it has (0 frames).
# FIX (2): the sheet job (slot_jobs_r119h_clouds-freeze-sheet.json, job r119h-lt): the b49 lt-w6 walk, freeze on after the
# settle, then at ONE camera: off, cover 0.3, cover 0.5, cover 0.7, contrast 2.0, tint 0.5, tint 1.0, smear fix off,
# default again (d1 must match c05 within the noise floor, about 2-3), each 1 s apart. Default look unchanged,
# everything still off by default; the library does nothing.
#
# Files (5, no new file, no shared hook, no CMake, no shader change: the SPIR-V is untouched): cloud_layer_params.h
# (ParseFreeze, ParseMark, HeldSpeed, MarkSkipFrames/MarkFrames/MarkTimeoutFrames), vk_cloud_layer.cpp/.h, tests/test_cloud_layer.cpp
# (block o), README.md (two rows). Apply after r119g; revert BEFORE r119g (its check ties to text near these lines).
#
# COST: frozen: nothing less, nothing more (the same Advance call). Off (no CloudLayer): nothing. On: two more atomic
# loads a frame for the live reads (while the layer is on); the mark's Totals (136 bytes) are summed for 12 frames after a
# mark change only. No GPU change, no new memory.
#
# Use: python -I -X utf8 r119h_clouds-freeze-sheet.py check | apply | revert
# Root: R119H_ROOT, else <tree>. Line ends kept. Backups in r119h_backup next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r119h_backup")
ROOT = os.environ.get("R119H_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
TMP = ".r119htmp"

PARAMS = R + "cloud_layer_params.h"
CPP = R + "vk_cloud_layer.cpp"
HDR = R + "vk_cloud_layer.h"
TEST = "engine/tests/test_cloud_layer.cpp"
README = "README.md"

EDITS = [
    # ---- the pure part ---------------------------------------------------------------------------------------------
    (PARAMS,
     "inline bool ParseSmear(const char* text) {\n"
     "    return text == nullptr || text[0] != '0';\n"
     "}\n",
     "inline bool ParseSmear(const char* text) {\n"
     "    return text == nullptr || text[0] != '0';\n"
     "}\n"
     "// bbport (r119h_clouds-freeze-sheet): TOOL. BB_VOLUMETRIC_CLOUDS_FREEZE (a live knob with the test tools' header): 1\n"
     "// holds the layer's cloud offsets exactly (advect and morph), anything else lets them move. BB_VOLUMETRIC_CLOUDS_MARK:\n"
     "// a sheet mark, a whole number 1 to 999999 (else 0, none): a change of it makes the layer say one line with the\n"
     "// counters of the MarkFrames frames that follow MarkSkipFrames frames (the counters are a frame or two old); after\n"
     "// MarkTimeoutFrames frame ends it says what it has.\n"
     "inline bool ParseFreeze(const char* text) {\n"
     "    return text != nullptr && text[0] == '1';\n"
     "}\n"
     "inline constexpr std::uint32_t MarkMost = 999999u;\n"
     "inline constexpr std::uint32_t MarkSkipFrames = 4, MarkFrames = 12, MarkTimeoutFrames = 240;\n"
     "inline std::uint32_t ParseMark(const char* text) {\n"
     "    if (text == nullptr || text[0] == '\\0') return 0;\n"
     "    std::uint32_t v = 0;\n"
     "    for (const char* p = text; *p != '\\0'; ++p) {\n"
     "        if (*p < '0' || *p > '9') return 0;\n"
     "        v = v * 10u + std::uint32_t(*p - '0');\n"
     "        if (v > MarkMost) return 0;\n"
     "    }\n"
     "    return v;\n"
     "}\n"
     "/// The one wind's cloud speed (m/s) held between DriftFloor and DriftCeil (a speed that is not a number counts as the\n"
     "/// floor), before the SPEED knob: LayerSpeed(c, k) = HeldSpeed(c) * k.speed.\n"
     "inline float HeldSpeed(float cloud_speed) {\n"
     "    return cloud_speed > DriftFloor ? std::min(cloud_speed, DriftCeil) : DriftFloor;\n"
     "}\n"),
    # ---- the engine ---------------------------------------------------------------------------------------------------
    (CPP,
     "constexpr const char* LiveText = BB_CLOUD_LAYER_LIVE ? \"live knobs on\" : \"read at the start\";\n",
     "/// bbport (r119h_clouds-freeze-sheet): TOOL. BB_VOLUMETRIC_CLOUDS_FREEZE and _MARK now: live knobs with the test tools'\n"
     "/// header only; without it never frozen and no mark (the feature branch carries none of it).\n"
     "bool LiveFreeze() {\n"
     "#if BB_CLOUD_LAYER_LIVE\n"
     "    static BbLiveKnobs::Knob<bool> freeze{\"BB_VOLUMETRIC_CLOUDS_FREEZE\", CL::ParseFreeze};\n"
     "    return freeze.Get();\n"
     "#else\n"
     "    return false;\n"
     "#endif\n"
     "}\n"
     "\n"
     "u32 LiveMark() {\n"
     "#if BB_CLOUD_LAYER_LIVE\n"
     "    static BbLiveKnobs::Knob<u32> mark{\"BB_VOLUMETRIC_CLOUDS_MARK\", CL::ParseMark};\n"
     "    return mark.Get();\n"
     "#else\n"
     "    return 0;\n"
     "#endif\n"
     "}\n"
     "\n"
     "constexpr const char* LiveText = BB_CLOUD_LAYER_LIVE ? \"live knobs on\" : \"read at the start\";\n"),
    (CPP,
     "    layer_drift.Advance(true, Seconds(),\n"
     "                        CL::LayerWind(Direction(), ClockState().Velocity(ClockKnobs()), live), live.size);\n",
     "    // bbport (r119h_clouds-freeze-sheet): TOOL: BB_VOLUMETRIC_CLOUDS_FREEZE=1 (live) gives the offsets a zero wind: Advance\n"
     "    // keeps its clock and leaves the cells exactly as they are (advect and morph both stop). Not frozen: the call below\n"
     "    // is the one it always was.\n"
     "    frozen = LiveFreeze();\n"
     "    if (frozen != told_frozen) {\n"
     "        told_frozen = frozen;\n"
     "        const std::array<float, 3> o = layer_drift.Cells(0);\n"
     "        std::printf(\"Volumetric clouds (r119h): live knob BB_VOLUMETRIC_CLOUDS_FREEZE: %s; octave 0 offset %.4f %.4f %.4f cells\\n\",\n"
     "                    frozen ? \"on, the cloud offsets are held\" : \"off, the field moves again\", double(o[0]), double(o[1]),\n"
     "                    double(o[2]));\n"
     "    }\n"
     "    const u32 mark = LiveMark();\n"
     "    if (mark != mark_told) {\n"
     "        mark_told = mark;\n"
     "        mark_totals = {};\n"
     "        mark_skip = CL::MarkSkipFrames;\n"
     "        mark_age = 0;\n"
     "        mark_left = mark != 0 ? CL::MarkFrames : 0;\n"
     "    }\n"
     "    layer_drift.Advance(true, Seconds(),\n"
     "                        frozen ? std::array<float, 3>{0.0f, 0.0f, 0.0f}\n"
     "                               : CL::LayerWind(Direction(), ClockState().Velocity(ClockKnobs()), live),\n"
     "                        live.size);\n"),
    (CPP,
     "        totals.Add(words);\n"
     "    }\n"
     "    drew_this_frame = false;\n",
     "        totals.Add(words);\n"
     "        if (mark_left > 0) { // bbport (r119h_clouds-freeze-sheet): the sheet mark's own sum\n"
     "            if (mark_skip > 0) {\n"
     "                --mark_skip;\n"
     "            } else {\n"
     "                mark_totals.Add(words);\n"
     "                if (--mark_left == 0) {\n"
     "                    ReportMark(mark_told);\n"
     "                }\n"
     "            }\n"
     "        }\n"
     "    }\n"
     "    if (mark_left > 0 && ++mark_age >= CL::MarkTimeoutFrames) {\n"
     "        ReportMark(mark_told);\n"
     "    }\n"
     "    drew_this_frame = false;\n"),
    (CPP,
     "                     double(live.tint), live.smear ? \"on\" : \"off\"); // bbport (r119g_clouds-smear-and-cover)\n"
     "    stats = {};\n",
     "                     double(live.tint), live.smear ? \"on\" : \"off\"); // bbport (r119g_clouds-smear-and-cover)\n"
     "    {\n"
     "        // bbport (r119h_clouds-freeze-sheet): where the drift comes from (under 300 characters): the wind's cloud speed held to\n"
     "        // 2.5-8 m/s, times the SPEED knob (its floor 0.25), plus the morph, which the knob does not scale\n"
     "        const float cloud_speed = ClockState().Velocity(ClockKnobs());\n"
     "        const std::array<float, 3> o = layer_drift.Cells(0);\n"
     "        BbReport::Printf(\"Volumetric clouds (r119h): drift: wind cloud speed %.1f m/s held %.1f-%.1f = %.1f, x speed knob %.2f = \"\n"
     "                         \"%.2f m/s%s; morph one %.0f m cell per %.0f s (%.1f m/s equivalent, not scaled by the knob); \"\n"
     "                         \"octave 0 offset %.4f %.4f %.4f cells\\n\",\n"
     "                         double(cloud_speed), double(CL::DriftFloor), double(CL::DriftCeil),\n"
     "                         double(CL::HeldSpeed(cloud_speed)), double(live.speed),\n"
     "                         double(CL::LayerSpeed(cloud_speed, live)), frozen ? \" (FROZEN: held at 0)\" : \"\",\n"
     "                         double(live.size), double(CloudShadows::MorphSeconds),\n"
     "                         double(live.size) / double(CloudShadows::MorphSeconds), double(o[0]), double(o[1]), double(o[2]));\n"
     "    }\n"
     "    stats = {};\n"),
    (CPP,
     "void CloudLayer::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,\n"
     "                       std::array<float, 2> jitter) {\n",
     "/// bbport (r119h_clouds-freeze-sheet): the sheet mark's one line (under 300 characters): the shares of the frames since the\n"
     "/// mark changed, the look knobs now and octave 0's offset (equal digits in two lines: the field stood still).\n"
     "void CloudLayer::ReportMark(u32 mark) {\n"
     "    const CL::Shares s = CL::SharesOf(mark_totals);\n"
     "    const std::array<float, 3> o = layer_drift.Cells(0);\n"
     "    BbReport::Printf(\"Volumetric clouds (r119h): sheet mark %u over %llu frames: sky px share %.3f, covered share %.3f, \"\n"
     "                     \"visible share %.3f, mean opacity %.3f; cover %.2f, contrast %.2f, tint %.2f, smear fix %s, frozen %s, \"\n"
     "                     \"octave 0 offset %.4f %.4f %.4f\\n\",\n"
     "                     mark, static_cast<unsigned long long>(mark_totals.frames), s.sky, s.covered, s.visible, s.opacity,\n"
     "                     double(live.cover), double(live.contrast), double(live.tint), live.smear ? \"on\" : \"off\",\n"
     "                     frozen ? \"yes\" : \"no\", double(o[0]), double(o[1]), double(o[2]));\n"
     "    mark_left = 0;\n"
     "}\n"
     "\n"
     "void CloudLayer::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,\n"
     "                       std::array<float, 2> jitter) {\n"),
    (HDR,
     "    void ReadLive();\n",
     "    void ReadLive();\n"
     "    /// bbport (r119h_clouds-freeze-sheet): says the sheet mark's line (the frames summed since the mark changed).\n"
     "    void ReportMark(u32 mark);\n"),
    (HDR,
     "    int told_smear = -1;                             ///< bbport (r119g): the live smear fix said last (-1: none yet)\n",
     "    int told_smear = -1;                             ///< bbport (r119g): the live smear fix said last (-1: none yet)\n"
     "    bool frozen = false, told_frozen = false;        ///< bbport (r119h): BB_VOLUMETRIC_CLOUDS_FREEZE now and said last\n"
     "    u32 mark_told = 0, mark_skip = 0, mark_left = 0, mark_age = 0; ///< bbport (r119h): BB_VOLUMETRIC_CLOUDS_MARK said last, frames to skip / to sum, frame ends since\n"
     "    CloudLayerParams::Totals mark_totals;            ///< bbport (r119h): the counters of the frames of the mark\n"),
    # ---- the test --------------------------------------------------------------------------------------------------------
    (TEST,
     "    std::puts(\"cloud layer: ok\");\n",
     "    // o. (r119h_clouds-freeze-sheet) the freeze and mark parsers, HeldSpeed against LayerSpeed, and a zero wind holding the\n"
     "    //    drift's offsets exactly (clock kept, so no jump when it moves again).\n"
     "    {\n"
     "        assert(!ParseFreeze(nullptr) && !ParseFreeze(\"\") && !ParseFreeze(\"0\") && !ParseFreeze(\"x\") && ParseFreeze(\"1\"));\n"
     "        assert(ParseMark(nullptr) == 0u && ParseMark(\"\") == 0u && ParseMark(\"0\") == 0u && ParseMark(\"7\") == 7u &&\n"
     "               ParseMark(\"999999\") == 999999u);\n"
     "        assert(ParseMark(\"1000000\") == 0u && ParseMark(\"-1\") == 0u && ParseMark(\"1.5\") == 0u && ParseMark(\"9x\") == 0u &&\n"
     "               ParseMark(\" 3\") == 0u && ParseMark(\"99999999999999999999\") == 0u);\n"
     "        assert(MarkFrames > 0u && MarkSkipFrames > 0u && MarkTimeoutFrames > MarkSkipFrames + MarkFrames);\n"
     "        assert(HeldSpeed(1.0f) == DriftFloor && HeldSpeed(100.0f) == DriftCeil && HeldSpeed(5.0f) == 5.0f &&\n"
     "               HeldSpeed(std::nanf(\"\")) == DriftFloor);\n"
     "        const Knobs base = MakeKnobs(\"1\", nullptr, nullptr, nullptr, nullptr);\n"
     "        Knobs slow = base;\n"
     "        slow.speed = MinSpeed;\n"
     "        for (const float c : {1.0f, 3.0f, 6.0f, 20.0f, std::nanf(\"\")}) {\n"
     "            assert(LayerSpeed(c, base) == HeldSpeed(c) * base.speed && LayerSpeed(c, slow) == HeldSpeed(c) * MinSpeed);\n"
     "        }\n"
     "        // the speed knob's floor leaves a drift (6 x 0.25 = 1.5 m/s) and the morph does not scale with it: no speed stops the field\n"
     "        assert(Near(double(LayerSpeed(6.0f, slow)), 1.5, 1e-6));\n"
     "        const std::array<float, 3> moving = LayerWind(214.0f, 6.0f, slow);\n"
     "        assert(moving[1] > 0.0f && moving[1] == LayerWind(214.0f, 6.0f, base)[1]);\n"
     "        VolumetricFogNoise::Drift d;\n"
     "        d.Advance(true, 10.0, moving, slow.size);\n"
     "        d.Advance(true, 10.5, moving, slow.size);\n"
     "        d.Advance(true, 11.0, moving, slow.size);\n"
     "        std::array<std::array<float, 3>, 3> held{};\n"
     "        for (std::size_t k = 0; k < 3; ++k) held[k] = d.Cells(k);\n"
     "        bool moved = false;\n"
     "        for (std::size_t k = 0; k < 3; ++k) moved = moved || held[k][1] != 0.0f;\n"
     "        assert(moved);\n"
     "        const std::array<float, 3> zero{0.0f, 0.0f, 0.0f};\n"
     "        for (const double t : {11.5, 12.0, 14.0, 20.0}) { // a zero wind, including a long gap: nothing moves, bit for bit\n"
     "            d.Advance(true, t, zero, slow.size);\n"
     "            for (std::size_t k = 0; k < 3; ++k) {\n"
     "                const std::array<float, 3> now = d.Cells(k);\n"
     "                assert(now[0] == held[k][0] && now[1] == held[k][1] && now[2] == held[k][2]);\n"
     "            }\n"
     "        }\n"
     "        // moving again takes one step of the time since the last call (the clock was kept), not the whole pause\n"
     "        d.Advance(true, 20.5, moving, slow.size);\n"
     "        VolumetricFogNoise::Drift once;\n"
     "        once.Advance(true, 20.0, moving, slow.size);\n"
     "        once.Advance(true, 20.5, moving, slow.size);\n"
     "        for (std::size_t k = 0; k < 3; ++k) {\n"
     "            for (std::size_t i = 0; i < 3; ++i) {\n"
     "                const double gone = VolumetricFogNoise::WrapCells(double(d.Cells(k)[i]) - double(held[k][i]));\n"
     "                const double want = double(once.Cells(k)[i]);\n"
     "                const double gap = std::fabs(gone - want);\n"
     "                assert(gap < 2e-3 || std::fabs(gap - VolumetricFogNoise::Period) < 2e-3);\n"
     "            }\n"
     "        }\n"
     "    }\n"
     "    std::puts(\"cloud layer: ok\");\n"),
    # ---- the README ----------------------------------------------------------------------------------------------------------
    (README,
     "| `BB_VOLUMETRIC_CLOUDS_REPORT` | A test aid: the frames between",
     "| `BB_VOLUMETRIC_CLOUDS_FREEZE` | A test aid (a live knob with the test tools' knobs file; without it never frozen): `1` holds the layer's cloud field exactly where it is, so a look sheet differs only by its knob. No `BB_VOLUMETRIC_CLOUDS_SPEED` value does that: the speed knob scales the advect only (the one wind's cloud speed held to 2.5-8 m/s, times the knob, 0.25 at least: 1.5 m/s at the floor), while the morph of the field's third axis (one cell of the biggest octave per 120 s, 6.7 m/s equivalent at 800 m) runs whatever the speed and changes the clouds' shape. The periodic `Volumetric clouds (r119h)` line says both and octave 0's offset in cells | off |\n"
     "| `BB_VOLUMETRIC_CLOUDS_MARK` | A test aid (a live knob): a whole number 1 to 999999. A change of it makes the layer say one `Volumetric clouds (r119h): sheet mark n` line about 16 drawn frames later, with the sky, covered and visible shares and the mean opacity of 12 frames and the look knobs and the frozen offsets of that moment, so every picture of a sheet has its own covered share line (a line with 0 frames: no sky was drawn) | unset |\n"
     "| `BB_VOLUMETRIC_CLOUDS_REPORT` | A test aid: the frames between"),
]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    """Ties (rule 10): the README, the header, the code and the test agree."""
    params, cpp, hdr, readme, test = texts[PARAMS], texts[CPP], texts[HDR], texts[README], texts[TEST]
    for text in ("MarkSkipFrames = 4, MarkFrames = 12, MarkTimeoutFrames = 240;", "MarkMost = 999999u;"):
        if params.count(text) != 1:
            raise SystemExit("tie check: %s" % text)
    rows = [l for l in readme.split("\n") if l.startswith("| `BB_VOLUMETRIC_CLOUDS_MARK` |")]
    if len(rows) != 1 or "1 to 999999" not in rows[0] or "12 frames" not in rows[0] or "16 drawn frames" not in rows[0]:
        raise SystemExit("tie check: README MARK row against MarkMost, MarkFrames and MarkSkipFrames + MarkFrames")
    rows = [l for l in readme.split("\n") if l.startswith("| `BB_VOLUMETRIC_CLOUDS_FREEZE` |")]
    if len(rows) != 1 or "1.5 m/s" not in rows[0] or "120 s" not in rows[0] or "2.5-8 m/s" not in rows[0] or "0.25" not in rows[0]:
        raise SystemExit("tie check: README FREEZE row against MinSpeed, DriftFloor/Ceil and MorphSeconds")
    if "MinSpeed = 0.25f, MaxSpeed = 60.0f" not in params or "DriftFloor = 2.5f, DriftCeil = 8.0f" not in params:
        raise SystemExit("tie check: the README's 0.25 and 2.5-8 against the header")
    if "MorphSeconds = 120.0;" not in open(os.path.join(ROOT, R + "cloud_shadow_params.h"), "rb").read().decode("utf-8"):
        raise SystemExit("tie check: the README's 120 s against MorphSeconds")
    for name in ("BB_VOLUMETRIC_CLOUDS_FREEZE", "BB_VOLUMETRIC_CLOUDS_MARK"):
        if cpp.count('"%s"' % name) != 1:
            raise SystemExit("tie check: %s not read exactly once in the engine" % name)
    if "ParseMark(\"1000000\")" not in test or "HeldSpeed(std::nanf" not in test:
        raise SystemExit("tie check: the test")
    for text in ("void ReportMark(u32 mark);", "bool frozen = false, told_frozen = false;", "CloudLayerParams::Totals mark_totals;"):
        if hdr.count(text) != 1:
            raise SystemExit("tie check: header %s" % text)
    if not all(ord(c) < 128 for _, _, new in EDITS for c in new):
        raise SystemExit("new text must be ASCII")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R119H_ROOT)" % ROOT)
    files = []
    for path, _, _ in EDITS:
        if path not in files:
            files.append(path)
    plan, texts_now = {}, {}
    for path in files:
        raw, eol, cur = load(path)
        mine = [e for e in EDITS if e[0] == path]
        done = sum(cur.count(new) == 1 for _, old, new in mine)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for _, old, new in mine)
        if done == len(mine):
            state = "applied"
        elif todo == len(mine):
            state = "clean"
        else:
            bad = [old[:60] for _, old, new in mine if not (cur.count(new) == 1 or (cur.count(old) == 1 and cur.count(new) == 0))]
            raise SystemExit("%s: %d of %d edits in place, %d ready to apply (is r119g applied? "
                             "is another patch editing the same text?) first failing anchor: %r"
                             % (path, done, len(mine), todo, bad[:1]))
        plan[path] = (raw, eol, cur, state)
        texts_now[path] = cur
    states = {p[3] for p in plan.values()}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (k, v[3]) for k, v in plan.items()))
    state = states.pop()
    if cmd == "check":
        if state == "applied":
            text_checks(texts_now)
            print("applied (text checks pass)")
        else:
            after = {}
            for path in files:
                cur = plan[path][2]
                for p, old, new in EDITS:
                    if p == path:
                        cur = cur.replace(old, new, 1)
                after[path] = cur
            text_checks(after)
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(files), len(EDITS)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        outs, after = [], {}
        for path in files:
            raw, eol, cur, _ = plan[path]
            for p, old, new in EDITS:
                if p == path:
                    cur = cur.replace(old, new, 1)
            after[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(after)
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                full = os.path.join(ROOT, path)
                open(full + TMP, "wb").write(data)
                os.replace(full + TMP, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                if os.path.exists(os.path.join(ROOT, path) + TMP):
                    os.remove(os.path.join(ROOT, path) + TMP)
            for path, raw in written:
                open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied (%d files edited, %d edits)" % (len(files), len(EDITS)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    outs = []
    for path in files:
        raw, eol, cur, _ = plan[path]
        for p, old, new in reversed(EDITS):
            if p == path:
                if cur.count(new) != 1:
                    raise SystemExit("%s: edit not found exactly once: %r" % (path, new[:70]))
                cur = cur.replace(new, old, 1)
        outs.append((path, cur.replace("\n", eol).encode("utf-8")))
    for path, data in outs:
        open(os.path.join(ROOT, path), "wb").write(data)
    print("reverted (%d files)" % len(files))


if __name__ == "__main__":
    main()
