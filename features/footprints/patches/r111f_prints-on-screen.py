# r111f_prints-on-screen: FEATURE fix on top of r111_footprints, r111b, r111c, r111d and r111e (b40: the walk
# worked, 7 blood prints placed and the hunter moved -48.89 -> -43.04, church 8 wet prints; but the
# BB_FOOTPRINTS_SHOW flat red quads never showed in any picture). Still off unless BB_FOOTPRINTS is set and
# still costs nothing when off (r111e's DrawOver is behind the `footprints` null pointer test; r111f adds
# only code inside DrawOver and the shader of that pass, and the counters of one pass). Branch:
# visual/footprints.
#
# WHAT THE b40 LOGS AND PICTURES SAY (read before the changes)
#  - The pass is recorded and runs. Slot logs b40_s1/s3/s4: "306 passes (post stamp) ... 0 stamped px (most
#    1563)", "395 passes ... most 1046", "304 passes (flat red view) ... 1280315 px a pass". The post stamp
#    counted 1046 to 1563 pixels in a frame, so the shader runs, the depth, the camera matrices and the print
#    positions agree (a stamp that hits 1000 pixels cannot do it with a wrong matrix). The runner's cap
#    (Test-BBFSSSlot.ps1: the first 30 feature lines, first and last of each kind) cut the 600-frame r111e line
#    out of the result file; it is in the full slot logs.
#  - The flat red view counted 0 red pixels while it was on. Reading the picture (slot_r111e-gbc_down_flat.jpg)
#    with the numbers: the camera stands 2.9 to 4.6 m behind the hunter and 1.4 m above the ground, looking
#    about 5 degrees down with a vertical half-angle of 21.5 degrees (proj y 2.5386): the lowest row of the
#    picture sees the ground at 1.42 / tan(26.5 deg) = 2.85 m, the hunter's feet (3 m) stand at row ~1040. The
#    prints lie 0.75 m apart BEHIND the hunter, that is between him and the camera and behind it: every one is
#    nearer than 2.85 m, below the lowest row or behind the camera. The r111c line says it too: "the largest
#    box 1920 x 1080 px" (Project returns the whole screen for a box partly behind the near plane: a print
#    under the camera) and "1.42 to 4.54 m from the camera". So the flat quads were drawn where they
#    could be (0 pixels): the camera framing of the jobs hid every print. The stamp's 1046 to 1563 pixels
#    were the first prints, seen while the camera was still further behind.
#  - So: not a wrong matrix, space, cull, target or order (the stamp proves those four). The jobs' framing
#    was wrong, and the pass left no trace that would have told the difference between "off the
#    screen" and "not reaching it". r111f adds that proof and fixes the framing.
#
# WHAT CHANGES (footprints files only; no new file)
#  - footprints_flat.comp (the pass of r111e), one workgroup thread each group: the number of groups that ran,
#    the frame's stamp, and for the first FOOTPRINTS_FLAT_PROBES (8) prints the pixel where the shader finds the
#    print's centre (from the pushed inverse view, no copy of the CPU's number) and the scene's depth and view z
#    there. In the flat view every print also gets a hollow 15 pixel square at its projected centre: magenta
#    where the centre is on the screen, cyan clamped to the screen's edge where it is off the screen, yellow
#    clamped where it is behind the camera; and a solid 24 pixel green square in the picture's top left corner
#    whenever the pass ran: if the beacon is in the picture the pass reaches the screen, and prints without
#    markers are the framing. The flat view now covers the whole picture (it sends every live print, on the
#    screen or not).
#  - footprints.h: ProjectPoint (one world point to its pixel, the rule of Project and the shaders; the state
#    inside / outside / behind) with unit tests; the counter words; footprints_layout.h the words.
#  - vk_footprints.cpp/.h: Footprints::LogFlat (the 600-frame line, numbers only so the runner's first/last
#    folding keeps it, and ONE copy of it with zeros at construction so it is early in the log: the
#    runner keeps the first 30 feature lines by first appearance), Footprints::LogProbe (a summary line and a
#    line per probed print: world position, camera position, projected pixel by the CPU and by the GPU, state,
#    the print's view z and the scene's view z and depth at that pixel; same trick: one zero copy at
#    construction), Footprints::FlatProbeRead (a snapshot of the pass is kept for 4 frames and matched to the
#    counters by the frame's stamp). Logged from the 6th pass of every mode (post stamp / flat view) and
#    every 120 passes after it, at most 20 times.
#  - jobs: after the walk the camera turns about 180 degrees (rx=255 0.9 s) and tilts down (ry=255 0.2 s):
#    the trail is seen from its front, behind the hunter.
#
# How the code guarantees nothing runs when the feature is off: BB_FOOTPRINTS unset -> Footprints is not made
# -> r111e's hook is one null pointer test and nothing of r111f is reached (it is inside Footprints). With
# BB_FOOTPRINTS on and SHOW and the post stamp off (BB_FOOTPRINTS_POST=0, SHOW=0) DrawOver returns at its
# first test before any of the new code. The new shader code runs only in the pass that already exists; the
# markers and the corner beacon only with SHOW. Memory: the counter buffer 8 B -> 144 B (and its host copy).
# Cost: one thread a workgroup reads <= 8 depths and writes <= 36 words; with SHOW the pass covers the whole
# picture and each pixel loops over the live prints (a test view; cost not measured, about 0.1 ms at 1080p
# for 8 prints by arithmetic).
#
# Files edited (the text r111e left; each old text found exactly once): renderer_vulkan/footprints.h,
# vk_footprints.h, vk_footprints.cpp, host_shaders/footprints_layout.h, host_shaders/footprints_flat.comp,
# engine/tests/test_footprints.cpp, README.md (the BB_FOOTPRINTS_SHOW row).
#
# Order: needs r111 to r111e applied (refused otherwise). To take r111e out, revert r111f first.
# Use: python -I -X utf8 r111f_prints-on-screen.py check | apply | revert
# Root: R111F_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r111f_backup next to this script; revert puts each old text back (each new text found by itself, exactly
# once).
import os, re, sys

ROOT = os.environ.get("R111F_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r111f_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RULES = RV + "footprints.h"
VKH = RV + "vk_footprints.h"
VKC = RV + "vk_footprints.cpp"
LAYOUT = HS + "footprints_layout.h"
FLAT = HS + "footprints_flat.comp"
TEST = "engine/tests/test_footprints.cpp"
README = "README.md"
ORDER = [LAYOUT, RULES, VKH, VKC, FLAT, TEST, README]

# (old, new): `old` found exactly once and `new` not at all (clean), or `new` exactly once (applied).
EDITS = {
    LAYOUT: [
        (r'''#define FOOTPRINTS_FLAT_WORDS 2u
#define FOOTPRINTS_FLAT_WORD_RED_PX 0u
#define FOOTPRINTS_FLAT_WORD_POST_PX 1u
''',
         r'''// (r111f) The counters grew: the pass's own proof that it ran (workgroups executed, the stamp of the frame it
// ran in) and, for the first FLAT_PROBES prints, where the shader finds the print's centre on the screen and
// the scene's depth there: per probe FLAT_PROBE_WORDS words (pixel x + 1, pixel y, the depth's bits, the view
// z's bits; word 0 = 0: no result). FLAT_MARK_HALF: half the side of the test view's hollow marker square
// (2 * half + 1 pixels); FLAT_BEACON: the side of the solid corner square drawn whenever the pass ran.
#define FOOTPRINTS_FLAT_WORD_RED_PX 0u
#define FOOTPRINTS_FLAT_WORD_POST_PX 1u
#define FOOTPRINTS_FLAT_WORD_GROUPS 2u
#define FOOTPRINTS_FLAT_WORD_STAMP 3u
#define FOOTPRINTS_FLAT_WORD_PROBE 4u
#define FOOTPRINTS_FLAT_PROBES 8u
#define FOOTPRINTS_FLAT_PROBE_WORDS 4u
#define FOOTPRINTS_FLAT_WORDS 36u
#define FOOTPRINTS_FLAT_MARK_HALF 7
#define FOOTPRINTS_FLAT_BEACON 24
'''),
    ],
    RULES: [
        (r'''// (r111e) the draw over the picture: its counter words
inline constexpr std::uint32_t FlatWords = FOOTPRINTS_FLAT_WORDS;
inline constexpr std::uint32_t WordFlatRedPx = FOOTPRINTS_FLAT_WORD_RED_PX;
inline constexpr std::uint32_t WordFlatPostPx = FOOTPRINTS_FLAT_WORD_POST_PX;
static_assert(FlatWords == 2u && WordFlatRedPx == 0u && WordFlatPostPx == 1u);
''',
         r'''// (r111e, r111f) the draw over the picture: its counter words
inline constexpr std::uint32_t FlatWords = FOOTPRINTS_FLAT_WORDS;
inline constexpr std::uint32_t WordFlatRedPx = FOOTPRINTS_FLAT_WORD_RED_PX;
inline constexpr std::uint32_t WordFlatPostPx = FOOTPRINTS_FLAT_WORD_POST_PX;
inline constexpr std::uint32_t WordFlatGroups = FOOTPRINTS_FLAT_WORD_GROUPS;
inline constexpr std::uint32_t WordFlatStamp = FOOTPRINTS_FLAT_WORD_STAMP;
inline constexpr std::uint32_t WordFlatProbe = FOOTPRINTS_FLAT_WORD_PROBE;
inline constexpr std::uint32_t FlatProbes = FOOTPRINTS_FLAT_PROBES;
inline constexpr std::uint32_t FlatProbeWords = FOOTPRINTS_FLAT_PROBE_WORDS;
static_assert(WordFlatRedPx == 0u && WordFlatPostPx == 1u && WordFlatGroups == 2u && WordFlatStamp == 3u &&
              WordFlatProbe == 4u && FlatWords == WordFlatProbe + FlatProbes * FlatProbeWords);
'''),
        (r'''/// The push block, word for word as footprints.comp declares it (112 bytes).
''',
         r'''/// (r111f) Where one world point lands on a pass's screen, by the rule of Project and of the shaders: `view`
/// world to view (3x4 rows, view +z in front), `proj` the x and y scales (signed), `size` pixels, `jitter`
/// render pixels. `state`: 1 inside the picture, 0 outside it, 2 behind the camera (view z at or under
/// NearZ, or not a number: x and y are then 0). (x, y) is the pixel as the shaders' `p` (centres at integers).
struct ScreenPoint {
    float x = 0.0f, y = 0.0f, z = 0.0f; ///< the pixel, the view z in metres
    std::int32_t state = 2;
};

inline ScreenPoint ProjectPoint(const std::array<float, 12>& view, const std::array<float, 4>& proj, float width,
                                float height, const std::array<float, 2>& jitter, float wx, float wy, float wz) {
    ScreenPoint s;
    s.z = view[8] * wx + view[9] * wy + view[10] * wz + view[11];
    if (!(s.z > NearZ)) {
        return s;
    }
    const float vx = view[0] * wx + view[1] * wy + view[2] * wz + view[3];
    const float vy = view[4] * wx + view[5] * wy + view[6] * wz + view[7];
    s.x = (vx * proj[0] / s.z * 0.5f + 0.5f) * width + jitter[0] - 0.5f;
    s.y = (vy * proj[1] / s.z * 0.5f + 0.5f) * height + jitter[1] - 0.5f;
    if (!std::isfinite(s.x) || !std::isfinite(s.y)) {
        s.x = s.y = 0.0f;
        s.state = 2;
        return s;
    }
    s.state = (s.x >= 0.0f && s.y >= 0.0f && s.x <= width - 1.0f && s.y <= height - 1.0f) ? 1 : 0;
    return s;
}

/// The push block, word for word as footprints.comp declares it (112 bytes).
'''),
    ],
    VKH: [
        (r'''        u64 rect_px = 0;
    } flat;
''',
         r'''        u64 rect_px = 0;
        u32 read_back = 0, groups_ok = 0; ///< (r111f) passes whose counters came back, with every group run
    } flat;
    // (r111f) The proof that the pass ran, and where the prints are on the screen: a snapshot of each pass
    // (the CPU's numbers) is kept for 4 frames and matched by the frame's stamp to the counters the pass
    // wrote (the GPU's numbers).
    struct FlatSnap {
        u32 stamp = 0, show = 0, count = 0, groups = 0, mode_pass = 0, episode = 0;
        std::int32_t rect_w = 0, rect_h = 0;
        std::array<float, 3> camera{};
        struct Point {
            float x = 0.0f, y = 0.0f, z = 0.0f; ///< the print's world position
            FootprintRules::ScreenPoint screen;
        };
        std::array<Point, FootprintRules::FlatProbes> points{};
    };
    struct FlatProbe {
        u32 last_stamp = 0;   ///< the last pass whose counters were taken
        u32 episode = 0;      ///< counts the changes of mode (post stamp / flat view)
        bool show = false;    ///< the mode of this episode
        u32 mode_passes = 0;  ///< passes recorded in this episode
        u32 next_pass = 6;    ///< the pass of this episode to tell next
        u32 told = 0;         ///< probes told, at most FlatProbeMax
    } flat_probe;
    std::array<FlatSnap, 4> flat_snaps{};
    void FlatProbeRead(const std::array<u32, FootprintRules::FlatWords>& counts);
    void LogProbe(const FlatSnap& snap, const std::array<u32, FootprintRules::FlatWords>& counts) const;
    void LogFlat() const;
'''),
    ],
    VKC: [
        (r'''                     R::ShowFlat() ? "on" : "off");
    if (!camera_motion.Enabled()) {
''',
         r'''                     R::ShowFlat() ? "on" : "off");
    { // (r111f) one copy of each new line with zeros, so the kinds come early in the log (the slot runner
      // keeps the first 30 feature lines by first appearance, the first and last of each kind)
        FlatSnap none{};
        none.count = 1;
        LogProbe(none, std::array<u32, R::FlatWords>{});
        LogFlat();
    }
    if (!camera_motion.Enabled()) {
'''),
        (r'''void Footprints::DrawOver(VideoCore::ImageId color_id, std::array<float, 2> jitter) {
''',
         r'''/// (r111f) The probes are told from this pass of a mode on and every FlatProbeEvery passes after it, at most
/// FlatProbeMax times.
constexpr u32 FlatProbeFirst = 6, FlatProbeEvery = 120, FlatProbeMax = 20;

void Footprints::LogFlat() const {
    BbReport::Printf("Footprints (r111f): over the picture: %u frames, %u passes (view %u), %u read back, %u all "
                     "run, %u prints, %.0f px a pass; last %u red px (max %u), %u stamped (max %u); skipped "
                     "%u off, %u no camera, %u cannot; post %.2f\n",
                     flat.frames, flat.passes, R::ShowFlat() ? 1u : 0u, flat.read_back, flat.groups_ok,
                     flat.sent, flat.passes ? double(flat.rect_px) / double(flat.passes) : 0.0, flat.red_last,
                     flat.red_max, flat.post_last, flat.post_max, flat.off_screen, flat.no_camera, flat.cannot,
                     double(R::Post()));
}

void Footprints::LogProbe(const FlatSnap& snap, const std::array<u32, R::FlatWords>& counts) const {
    BbReport::Printf("Footprints (r111f): pass %u of view %u (1 flat red, 0 stamp): camera %.1f %.1f %.1f, %u "
                     "prints, rect %d x %d, groups run %u of %u, red px %u, stamped px %u\n",
                     snap.mode_pass, snap.show, double(snap.camera[0]), double(snap.camera[1]),
                     double(snap.camera[2]), snap.count, int(snap.rect_w), int(snap.rect_h),
                     counts[R::WordFlatGroups], snap.groups, counts[R::WordFlatRedPx],
                     counts[R::WordFlatPostPx]);
    const u32 n = std::min(snap.count, R::FlatProbes);
    for (u32 i = 0; i < n; ++i) { // oldest first: the line the runner keeps last is the last print's
        const u32* w = counts.data() + R::WordFlatProbe + std::size_t(i) * R::FlatProbeWords;
        float depth = 0.0f, view_z = 0.0f;
        std::memcpy(&depth, &w[2], sizeof(depth));
        std::memcpy(&view_z, &w[3], sizeof(view_z));
        const auto& pt = snap.points[i];
        BbReport::Printf("Footprints (r111f): print %u of %u at %.1f %.1f %.1f: pixel %.0f %.0f state %d (1 in, "
                         "0 out, 2 behind; GPU %d %d), view z %.2f, scene z %.2f, depth %.4f\n",
                         i, n, double(pt.x), double(pt.y), double(pt.z), double(pt.screen.x),
                         double(pt.screen.y), int(pt.screen.state), w[0] != 0u ? int(w[0]) - 1 : -1,
                         w[0] != 0u ? int(w[1]) : -1, double(pt.screen.z), double(view_z), double(depth));
    }
}

void Footprints::FlatProbeRead(const std::array<u32, R::FlatWords>& counts) {
    const u32 stamp = counts[R::WordFlatStamp];
    if (stamp == 0u || stamp == flat_probe.last_stamp) {
        return;
    }
    const FlatSnap& snap = flat_snaps[stamp % flat_snaps.size()];
    if (snap.stamp != stamp) {
        return; // the snapshot was taken over by a later pass
    }
    flat_probe.last_stamp = stamp;
    ++flat.read_back;
    flat.groups_ok += counts[R::WordFlatGroups] == snap.groups ? 1u : 0u;
    if (snap.episode != flat_probe.episode || snap.mode_pass < flat_probe.next_pass ||
        flat_probe.told >= FlatProbeMax) {
        return;
    }
    flat_probe.next_pass = snap.mode_pass + FlatProbeEvery;
    ++flat_probe.told;
    LogProbe(snap, counts);
}

void Footprints::DrawOver(VideoCore::ImageId color_id, std::array<float, 2> jitter) {
'''),
        (r'''        flat.post_max = std::max(flat.post_max, flat.post_last);
''',
         r'''        flat.post_max = std::max(flat.post_max, flat.post_last);
        FlatProbeRead(c); // (r111f)
'''),
        (r'''        if (r.Empty()) {
            continue;
        }
        rect = R::Union(rect, r);
        R::Pack(p.x, p.y, p.z, p.now, p.dir_x, p.dir_z, p.side, p.kind,
''',
         r'''        if (r.Empty() && !show) { // (r111f) the test view sends every print, on the screen or not
            continue;
        }
        rect = R::Union(rect, r);
        R::Pack(p.x, p.y, p.z, p.now, p.dir_x, p.dir_z, p.side, p.kind,
'''),
        (r'''    if (count == 0 || rect.Empty()) {
        ++flat.off_screen;
        return;
    }
    if (!FlatReady()) {
''',
         r'''    if (show && count != 0) { // (r111f) the test view covers the whole picture (markers, corner beacon)
        rect = R::Rect{0, 0, std::int32_t(width), std::int32_t(height)};
    }
    if (count == 0 || rect.Empty()) {
        ++flat.off_screen;
        return;
    }
    if (!FlatReady()) {
'''),
        (r'''    flat.rect_px += u64(rect.x1 - rect.x0) * u64(rect.y1 - rect.y0);
''',
         r'''    flat.rect_px += u64(rect.x1 - rect.x0) * u64(rect.y1 - rect.y0);
    { // (r111f) the snapshot of this pass for the probe: the CPU's numbers, matched to the GPU's by the stamp
        if (flat_probe.episode == 0 || flat_probe.show != show) {
            flat_probe.show = show;
            flat_probe.mode_passes = 0;
            flat_probe.next_pass = FlatProbeFirst;
            ++flat_probe.episode;
        }
        ++flat_probe.mode_passes;
        FlatSnap& snap = flat_snaps[push.stamp % flat_snaps.size()];
        snap = {};
        snap.stamp = push.stamp;
        snap.show = show ? 1u : 0u;
        snap.count = count;
        snap.groups = (gx1 - gx0) * (gy1 - gy0);
        snap.mode_pass = flat_probe.mode_passes;
        snap.episode = flat_probe.episode;
        snap.rect_w = rect.x1 - rect.x0;
        snap.rect_h = rect.y1 - rect.y0;
        snap.camera = {cam_x, cam_y, cam_z};
        for (u32 i = 0; i < std::min(count, R::FlatProbes); ++i) {
            const float* q = packed.data() + std::size_t(i) * R::PrintFloats;
            snap.points[i].x = q[0];
            snap.points[i].y = q[1];
            snap.points[i].z = q[2];
            snap.points[i].screen = R::ProjectPoint(camera.view, camera.proj, fw, fh, jitter, q[0], q[1], q[2]);
        }
    }
'''),
        (r'''    BbReport::Printf("Footprints (r111e): over the picture: %u frames, %u passes (%s), %u prints sent, "
                     "%.0f px a pass; the last pass drew %u flat red px (most %u) and %u stamped px (most "
                     "%u); skipped %u off screen, %u no camera, %u cannot; post %.2f\n",
                     flat.frames, flat.passes, R::ShowFlat() ? "flat red view" : "post stamp", flat.sent,
                     flat.passes ? double(flat.rect_px) / double(flat.passes) : 0.0, flat.red_last,
                     flat.red_max, flat.post_last, flat.post_max, flat.off_screen, flat.no_camera,
                     flat.cannot, double(R::Post()));
''',
         r'''    LogFlat(); // (r111f) the line of r111e, in numbers only, with the read-back count
'''),
    ],
    FLAT: [
        (r'''// Counters (FOOTPRINTS_FLAT_WORDS words, one atomic a drawn pixel): red pixels, stamped pixels.
''',
         r'''// Counters (FOOTPRINTS_FLAT_WORDS words, one atomic a drawn pixel): red pixels, stamped pixels.
// (r111f) Also one thread a workgroup: the groups that ran, the frame's stamp, and for the first
// FOOTPRINTS_FLAT_PROBES prints the pixel where this shader finds the print's centre (from the pushed inverse
// view) and the scene's depth and view z there. In the flat view every print also gets a hollow marker square
// at its projected centre (magenta: on the screen; cyan: off it, clamped to the edge; yellow: behind the
// camera, clamped) and the pass draws a solid green corner square (the beacon: the pass reached the picture).
'''),
        (r'''// 0..1: the sole's shape at (u along the step, v across it), as footprints.comp.
''',
         r'''// (r111f) A world point in view space (view z in front, positive), by the pushed inverse view (rigid: the
// transpose of its rotation), and the pixel of a view point with positive z, as the shaders' `p`.
vec3 ViewOf(vec3 c) {
    const vec3 d = c - vec3(inv_view[0].w, inv_view[1].w, inv_view[2].w);
    return mat3(inv_view[0].xyz, inv_view[1].xyz, inv_view[2].xyz) * d;
}
vec2 PixelOf(vec3 v) {
    return (vec2(v.x * proj.x, v.y * proj.y) / v.z * 0.5 + 0.5) * size + jitter - 0.5;
}

// (r111f) One thread of each workgroup (`tile` is its pixel, the group's corner): the proof that the pass
// ran, and the probes of the prints whose centre falls into this group's tile.
void GroupWork(ivec2 tile) {
    atomicAdd(counts[FOOTPRINTS_FLAT_WORD_GROUPS], 1u);
    atomicMax(counts[FOOTPRINTS_FLAT_WORD_STAMP], stamp);
    const uint n = min(min(print_count, FOOTPRINTS_MAX_PRINTS), FOOTPRINTS_FLAT_PROBES);
    for (uint i = 0u; i < n; ++i) {
        const vec3 v = ViewOf(prints[i].a.xyz);
        if (!(v.z > 0.05)) {
            continue;
        }
        const ivec2 q = ivec2(floor(PixelOf(v) + 0.5));
        if (q.x < tile.x || q.y < tile.y || q.x >= tile.x + int(FOOTPRINTS_GROUP) ||
            q.y >= tile.y + int(FOOTPRINTS_GROUP) || q.x >= int(size.x) || q.y >= int(size.y)) {
            continue;
        }
        const float d = texelFetch(depth_tex, q, 0).x;
        const uint w = FOOTPRINTS_FLAT_WORD_PROBE + i * FOOTPRINTS_FLAT_PROBE_WORDS;
        counts[w] = uint(q.x) + 1u;
        counts[w + 1u] = uint(q.y);
        counts[w + 2u] = floatBitsToUint(d);
        counts[w + 3u] = floatBitsToUint(ViewZ(d));
    }
}

// 0..1: the sole's shape at (u along the step, v across it), as footprints.comp.
'''),
        (r'''    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    if (p.x >= int(size.x) || p.y >= int(size.y)) {
''',
         r'''    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    if (gl_LocalInvocationIndex == 0u) {
        GroupWork(p);
    }
    if (p.x >= int(size.x) || p.y >= int(size.y)) {
'''),
        (r'''        bool red = false;
        bool centre = false;
        for (uint i = 0u; i < count; ++i) {
            const Print pr = prints[i];
            if (abs(dir.y) < 1e-6) {
''',
         r'''        bool red = false;
        bool centre = false;
        int ring = 0; // (r111f) 1 marker on the screen, 2 off it (clamped), 3 behind the camera (clamped)
        for (uint i = 0u; i < count; ++i) {
            const Print pr = prints[i];
            { // (r111f) the print's marker: a hollow square 3 pixels thick at its projected centre
                const vec3 pv = ViewOf(pr.a.xyz);
                const bool behind = !(pv.z > 0.05);
                const vec2 pc = PixelOf(vec3(pv.xy, max(abs(pv.z), 0.05)));
                const float half_side = float(FOOTPRINTS_FLAT_MARK_HALF);
                const vec2 mc = floor(clamp(pc, vec2(half_side), size - 1.0 - vec2(half_side)) + 0.5);
                const vec2 dm = abs(vec2(p) - mc);
                const float ring_d = max(dm.x, dm.y);
                if (ring_d <= half_side && ring_d >= half_side - 2.0) {
                    const bool on_screen = pc.x >= 0.0 && pc.y >= 0.0 && pc.x <= size.x - 1.0 && pc.y <= size.y - 1.0;
                    ring = behind ? 3 : (on_screen ? 1 : 2);
                }
            }
            if (abs(dir.y) < 1e-6) {
'''),
        (r'''        if (red) {
            imageStore(color_img,''',
         r'''        if (p.x < FOOTPRINTS_FLAT_BEACON && p.y < FOOTPRINTS_FLAT_BEACON) { // (r111f) the pass reached the picture
            imageStore(color_img, p, vec4(0.0, 3.0, 0.0, 1.0));
            return;
        }
        if (ring != 0) { // (r111f)
            const vec3 ring_colour = ring == 1 ? vec3(3.0, 0.0, 3.0) : (ring == 2 ? vec3(0.0, 3.0, 3.0) : vec3(3.0, 3.0, 0.0));
            imageStore(color_img, p, vec4(ring_colour, 1.0));
            return;
        }
        if (red) {
            imageStore(color_img,'''),
    ],
    TEST: [
        (r'''        assert(FlatWords == 2u && WordFlatRedPx != WordFlatPostPx);
''',
         r'''        assert(FlatWords == 36u && WordFlatRedPx != WordFlatPostPx);
'''),
        (r'''        assert(Near(lum, 1.0, 2e-3));
    }
''',
         r'''        assert(Near(lum, 1.0, 2e-3));
    }
    // (r111f) ProjectPoint: the rule of Project and of the shaders, for one point.
    {
        const std::array<float, 12> view{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const std::array<float, 4> proj{1.0f, 2.0f, 1.0f, 0.0f};
        const std::array<float, 2> none{0.0f, 0.0f};
        // on the axis, 2 m in front: the middle of a 100 x 50 picture (pixel centres at integers)
        ScreenPoint a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 0.0f, 0.0f, 2.0f);
        assert(a.state == 1 && Near(a.x, 49.5) && Near(a.y, 24.5) && Near(a.z, 2.0));
        // 1 m to the right at 2 m: ndc 0.5, pixel 75 - 0.5; 0.5 m down with y scale 2: ndc 0.5, 37
        a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 1.0f, 0.0f, 2.0f);
        assert(a.state == 1 && Near(a.x, 74.5));
        a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 0.0f, 0.5f, 2.0f);
        assert(a.state == 1 && Near(a.y, 37.0));
        // outside the picture (state 0), behind the camera and on the near plane (state 2, x and y 0)
        a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 10.0f, 0.0f, 1.0f);
        assert(a.state == 0 && a.x > 99.0f);
        a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 0.0f, 0.0f, -3.0f);
        assert(a.state == 2 && a.x == 0.0f && a.y == 0.0f && Near(a.z, -3.0));
        a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 0.0f, 0.0f, NearZ);
        assert(a.state == 2);
        // the jitter moves the pixel
        a = ProjectPoint(view, proj, 100.0f, 50.0f, {0.5f, -0.5f}, 0.0f, 0.0f, 2.0f);
        assert(Near(a.x, 50.0) && Near(a.y, 24.0));
        // the box of Project around a point holds the point's pixel
        const float lo[3] = {-0.1f, -0.1f, 1.9f}, hi[3] = {0.1f, 0.1f, 2.1f};
        const Rect r = Project(view, proj, 100.0f, 50.0f, none, lo, hi);
        a = ProjectPoint(view, proj, 100.0f, 50.0f, none, 0.0f, 0.0f, 2.0f);
        assert(!r.Empty() && a.x >= float(r.x0) && a.x <= float(r.x1) && a.y >= float(r.y0) && a.y <= float(r.y1));
    }
'''),
    ],
    README: [
        (r'''the post stamp is not drawn then (the G-buffer change still is). Unset,''',
         r'''the post stamp is not drawn then (the G-buffer change still is). (r111f) Each print also gets a hollow 15 pixel marker square at its projected centre: magenta where the centre is on the screen, cyan clamped to the edge where it is off the screen, yellow where it is behind the camera, and a solid green 24 pixel square sits in the picture's top left corner whenever the pass ran (so a print without a marker is told from a pass that does not reach the picture); the pass then covers the whole picture. The log lines `Footprints (r111f)` give the pass's counters, each probed print's world position, projected pixel (CPU and GPU) and the scene's depth there. Unset,'''),
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
                             "and 1; are r111 to r111e applied, and is this patch's own earlier version "
                             "reverted?): %r" % (path, co, cn, old[:70]))
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


def text_checks(texts):
    """Ties a compiler cannot check, on the full result."""
    cpp = texts[VKC]
    n_new = 0
    for m in re.finditer(r'BbReport::Printf\(((?:\s*"(?:[^"\\]|\\.)*")+)(.*?)\);\n', cpp, re.S):
        fmt = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))).replace("\\n", "")
        if not fmt.startswith("Footprints (r111"):
            raise SystemExit("text check: a log line without its prefix: %r" % fmt[:60])
        if "(r111f)" not in fmt:
            continue
        n_new += 1
        convs = re.findall(r"%(?!%)[-+ 0-9.]*(?:ll)?[udfs]", fmt.replace("%%", ""))
        args = split_args(m.group(2).lstrip().lstrip(",")) if m.group(2).strip() else []
        if len(convs) != len(args):
            raise SystemExit("text check: %d conversions, %d arguments: %r" % (len(convs), len(args), fmt[:70]))
        if "%s" in fmt:
            raise SystemExit("text check: a %%s in an r111f line (kinds fold on digits only): %r" % fmt[:60])
        wide = re.sub(r"%[-+]?[0-9]*\.[0-9]+f", "X" * 9, fmt)
        wide = re.sub(r"%(?:ll)?[ud]", "X" * 7, wide)
        wide = wide.replace("%%", "%")
        print("  r111f log line (wide %d, %d conversions): %s..." % (len(wide), len(convs), fmt[:50]))
        if len(wide) > 300:
            raise SystemExit("text check: a log line may pass 300 characters (%d): %r" % (len(wide), fmt[:60]))
    if n_new != 3:
        raise SystemExit("text check: %d r111f log lines (3 expected)" % n_new)
    if "Footprints (r111e): over the picture" in cpp:
        raise SystemExit("text check: the r111e periodic line is still there")
    flat = texts[FLAT]
    for need in ("GroupWork(p);", "FOOTPRINTS_FLAT_WORD_GROUPS", "FOOTPRINTS_FLAT_BEACON", "FOOTPRINTS_FLAT_MARK_HALF",
                 "floatBitsToUint(ViewZ(d))"):
        if need not in flat:
            raise SystemExit("text check: the shader lacks %r" % need)
    lay = texts[LAYOUT]
    for name in ("FOOTPRINTS_FLAT_WORDS", "FOOTPRINTS_FLAT_WORD_GROUPS", "FOOTPRINTS_FLAT_WORD_STAMP",
                 "FOOTPRINTS_FLAT_WORD_PROBE", "FOOTPRINTS_FLAT_PROBES", "FOOTPRINTS_FLAT_PROBE_WORDS",
                 "FOOTPRINTS_FLAT_MARK_HALF", "FOOTPRINTS_FLAT_BEACON", "FOOTPRINTS_FLAT_WORD_RED_PX"):
        if lay.count("#define " + name + " ") != 1:
            raise SystemExit("text check: layout does not define %s once" % name)
    words = {m.group(1): m.group(2) for m in re.finditer(r"#define (FOOTPRINTS_FLAT_\w+) (\d+)u?\n", lay)}
    if int(words["FOOTPRINTS_FLAT_WORDS"]) != int(words["FOOTPRINTS_FLAT_WORD_PROBE"]) + \
            int(words["FOOTPRINTS_FLAT_PROBES"]) * int(words["FOOTPRINTS_FLAT_PROBE_WORDS"]):
        raise SystemExit("text check: FLAT_WORDS is not the probes' end")
    if "FlatWords == 36u" not in texts[TEST]:
        raise SystemExit("text check: the unit test still pins the old word count")
    if texts[README].count("(r111f) Each print also gets a hollow 15 pixel marker square") != 1:
        raise SystemExit("text check: README lacks the r111f text once")
    for path, eds in EDITS.items():
        for old, new in eds:
            if "\t" in new or "\r" in new:
                raise SystemExit("text check: an edit of %s has a tab or a CR" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 r111f_prints-on-screen.py check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R111F_ROOT)" % ROOT)
    if not os.path.exists(os.path.join(ROOT, FLAT)):
        raise SystemExit("REFUSED: r111e is not applied (%s is missing)" % FLAT)
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
            tmp = full + ".r111ftmp"
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
        tmp = full + ".r111ftmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted (%d files edited back)" % len(plan))


main()
