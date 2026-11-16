# r101_lamp-moving-edge (FEATURE, lamp work; off by default): half-resolution lamp shadows
# (graphics_lamp_shadow_half=1) share a 2x2 block's answer only once it has settled.
#
# Fault (owner 2026-11-15: "the blocky edges of moving shadows still is there"): behind a moving
# shadow the first pass's guards (reject, clamp, trail) give up a block pixel's history, so its
# answer is one frame's ray, 0 or 1. Nine such answers agree by chance on the dark or lit side of a
# penumbra, HalfAnswer passes them as "agree within 1/64", and the block's other three pixels take
# the bare answer and copy the block's young history: 2x2 internal pixels (4x4 output pixels at
# DLSS Performance) that restart in step on the moving edge. With BB_LAMP_SHADOW_MOVING_EDGE=1 a
# block's answer is taken only when its pixel held history before this frame and its mean of the
# last few frames lies within 0.125 of its ratio (2 = show: within 1/64); else the pixel casts its
# own ray and keeps its own history (HALF_YOUNG, counted in half_counts word 14).
#
# Files: host_shaders/point_shadow_ray.comp (only inside #ifdef HALF: the full, centred, resolve and
# cards builds without HALF are byte-identical), renderer_vulkan/vk_point_shadow.cpp (one include,
# one OR into tuning word 0, one log call), README.md (one row), NEW renderer_vulkan/lamp_moving_edge.h.
# Word 0 bits 3 (on) and 2 (show): free before r91-r93; check their bits against these.
#
# usage: python -I -X utf8 r101_lamp-moving-edge.py check|apply|revert
# root: env R101_ROOT, else <tree>. Backups of the originals: r101_backup next to this script.
# Every edit is "anchor found exactly once"; revert undoes each edit the same way (so patches
# applied after this one keep their lines) and removes the new header.
import io, os, sys

ROOT = os.environ.get('R101_ROOT', '<tree>').rstrip('/\\') + '/'
BK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'r101_backup')
SH = 'engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp'
PS = 'engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp'
RD = 'README.md'
NEW = 'engine/gpu/shadps4/video_core/renderer_vulkan/lamp_moving_edge.h'

HEADER = r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r101_lamp-moving-edge): BB_LAMP_SHADOW_MOVING_EDGE, the half-resolution lamp shadows
// (graphics_lamp_shadow_half=1) share a 2x2 block's answer only once it has settled. Behind a
// moving shadow the first pass's guards (reject, clamp, trail) give up a block pixel's history, and
// its answer is then one frame's ray, 0 or 1; nine such answers can agree by chance on the dark or
// lit side of a penumbra, and the block's other three pixels took that bare answer and the block's
// young history with it (point_shadow_ray.comp HalfAnswer, HALF_YOUNG): squares of 2x2 pixels on a
// moving edge. 0 (the default): as before. 1: a block's answer is taken only where its pixel held
// history before this frame and its last few frames agree with its ratio within 0.125. 2 (show):
// within 1/64, so nearly every pixel whose block is not wholly settled casts its own ray (for
// tests). Read once, at the first lamp pass. No Vulkan here.

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "video_core/renderer_vulkan/lamp_shadow_tune.h"

namespace Vulkan {

/// Word 0 of the lamp pass's tuning words, read only by the HALF builds of point_shadow_ray.comp
/// (MOVING_EDGE_ON, MOVING_EDGE_SHOW): bit 3 on, bit 2 the show setting. LampTuneWords leaves both
/// clear; PointShadow::Flush ORs them in after it (LampMovingEdgeBits).
inline constexpr std::uint32_t LampTuneMovingEdge = 1u << 3, LampTuneMovingEdgeShow = 1u << 2;
static_assert(((LampTuneMovingEdge | LampTuneMovingEdgeShow) &
               (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft | LampTuneWindow |
                LampTuneCentred | (7u << LampTuneViewShift) |
                (LampTuneCardCapMask << LampTuneCardCapShift))) == 0,
              "bbport (r101_lamp-moving-edge): word 0 bits 2 and 3 must be free");

/// BB_LAMP_SHADOW_MOVING_EDGE as a whole number 0 to 2 (3 or more: 2; below 0: 0); text that is not
/// a whole number, or nothing: 0.
inline std::uint32_t LampMovingEdgeParse(const char* text) {
    if (!text || !text[0]) {
        return 0;
    }
    char* end = nullptr;
    const long value = std::strtol(text, &end, 10);
    if (end == text || !LampTuneDetail::Ends(end)) {
        return 0;
    }
    return std::uint32_t(std::clamp(value, 0l, 2l));
}

/// The knob, read once (the first call), with its line in the log when it is on.
inline std::uint32_t LampMovingEdgeValue() {
    static const std::uint32_t value = [] {
        const std::uint32_t v = LampMovingEdgeParse(std::getenv("BB_LAMP_SHADOW_MOVING_EDGE"));
        if (v != 0) {
            std::printf("Ray traced lamps (r101): moving edge %u (BB_LAMP_SHADOW_MOVING_EDGE): at half "
                        "resolution a 2x2 block's answer is shared only once it has settled (history "
                        "before this frame, its last frames within %s of it); else the pixel casts its "
                        "own ray. Only graphics_lamp_shadow_half=1 with soft or softer lamps\n",
                        unsigned(v), v == 1 ? "0.125" : "1/64 (show)");
        }
        return v;
    }();
    return value;
}

/// What PointShadow::Flush ORs into tuning word 0: 0 when the knob is off (the words as before).
inline std::uint32_t LampMovingEdgeBits() {
    const std::uint32_t v = LampMovingEdgeValue();
    return v == 0 ? 0u : v == 1 ? LampTuneMovingEdge : (LampTuneMovingEdge | LampTuneMovingEdgeShow);
}

/// PointShadow::OnFrameEnd's half-resolution line (every 600 frames), when the knob is on: young =
/// second-pass pixels a counted pass sent to their own rays by this rule (half_counts word 14, mean
/// per counted pass), traced = all second-pass pixels it traced (word 5).
inline void LampMovingEdgeLine(double young, double traced) {
    if (LampMovingEdgeValue() == 0) {
        return;
    }
    std::printf("Ray traced lamps (r101): a counted half-resolution pass sent %.0f second-pass pixels to "
                "their own rays because their block's answer was young (of %.0f it traced; "
                "BB_LAMP_SHADOW_MOVING_EDGE=%u)\n",
                young, traced, unsigned(LampMovingEdgeValue()));
}

} // namespace Vulkan
'''

E = {
 SH: [
  ('after', 'const float HALF_AGREE = 1.0 / 64.0;\n',
   '// bbport (r101_lamp-moving-edge): BB_LAMP_SHADOW_MOVING_EDGE (word 0 bit 3, bit 2 its show setting;\n'
   '// renderer_vulkan/lamp_moving_edge.h; off by default). Where a shadow moves, the first pass\'s guards\n'
   '// (the reject, the clamp, the trail) give up a block pixel\'s history, and its answer is then one\n'
   '// frame\'s ray, 0 or 1. Nine of them can agree by chance (on the dark or the lit side of a\n'
   '// penumbra), and the block\'s other three pixels then took that bare answer and the block\'s young\n'
   '// history with it: 2x2 pixels that start again in step, a square on the moving edge. With the knob\n'
   '// a block\'s answer is taken only once it has settled: its pixel held history before this frame\n'
   '// (history_cur b, the frames + 1, over 1.5) and its mean of the last few frames (a) lies within\n'
   '// MOVING_EDGE_SETTLED of its ratio (HALF_AGREE with the show setting); else HALF_YOUNG, and the\n'
   '// pixel casts its own ray and keeps its own history. Only where the pass averages (HISTORY_BLEND).\n'
   'const uint HALF_YOUNG = 5u;\n'
   'const uint MOVING_EDGE_ON = 8u, MOVING_EDGE_SHOW = 4u;\n'
   'const float MOVING_EDGE_SETTLED = 0.125;\n'),
  ('before', '    v = own.x;\n    return HALF_TAKEN;\n}',
   '    // bbport (r101_lamp-moving-edge): a young block answer is not shared (HALF_YOUNG)\n'
   '    if ((mode & MODE_REPAIR) != 0u) {\n'
   '        const uint edge = data.d[mode >> 8u] & (MOVING_EDGE_ON | MOVING_EDGE_SHOW);\n'
   '        const uint blend_at = floatBitsToUint(length_m);\n'
   '        if ((edge & MOVING_EDGE_ON) != 0u && blend_at != 0u && (data.d[blend_at] & HISTORY_BLEND) != 0u) {\n'
   '            const vec4 h = imageLoad(history_cur, block * 2);\n'
   '            const float settled = (edge & MOVING_EDGE_SHOW) != 0u ? HALF_AGREE : MOVING_EDGE_SETTLED;\n'
   '            if (!(h.b > 1.5) || !(abs(h.a - own.x) <= settled)) {\n'
   '                return HALF_YOUNG;\n'
   '            }\n'
   '        }\n'
   '    }\n'),
  ('replace', 'const uint HALF_SLOTS = 13u;\n',
   'const uint HALF_SLOTS = 15u; // bbport (r101_lamp-moving-edge): 13 unused, 14 HALF_YOUNG (13 slots before)\n'),
  ('replace', '    if (!first && why >= HALF_NO_ANSWER && why <= HALF_SURFACE) {\n',
   '    if (!first && why >= HALF_NO_ANSWER && (why <= HALF_SURFACE || why == HALF_YOUNG)) { // r101: 14\n'),
 ],
 PS: [
  ('before', '#include "video_core/renderer_vulkan/vk_camera_motion.h"\n',
   '#include "video_core/renderer_vulkan/lamp_moving_edge.h" // bbport (r101_lamp-moving-edge)\n'),
  ('after', '            data.insert(data.end(), tune_words.begin(), tune_words.end());\n',
   '            data[tune_at] |= LampMovingEdgeBits(); // bbport (r101_lamp-moving-edge): 0 when off\n'),
  ('before', '        half_frames = 0;\n',
   '        LampMovingEdgeLine(d[14], d[5]); // bbport (r101_lamp-moving-edge): only with the knob on\n'),
 ],
 RD: [],  # README_ROW goes after the row that starts with '| `BB_LAMP_SHADOW_CLAMP` |' (edits)
}
README_ROW = ('| `BB_LAMP_SHADOW_MOVING_EDGE` | Half-resolution lamp shadows only (`graphics_lamp_shadow_half=1`, '
              'soft or softer): `1` shares a 2x2 block\'s answer with its other three pixels only once that '
              'answer has settled (its pixel held history before this frame and its last few frames agree '
              'with it within 0.125), so behind a moving shadow a block whose history was just given up does '
              'not hand its bare one-ray answer and young history to all four pixels; `2` (show) the same '
              'within 1/64; `0` off. Nothing is made for it; on, about 0.01 ms plus the rays of the pixels it '
              'sends to their own rays (moving edges only). Log: "(r101)" lines | `0` |')


def rd(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        return f.read()


def wr(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


def nl_of(s):
    return '\r\n' if '\r\n' in s else '\n'


def edits(f, s):
    """(kind, anchor, text) in the file's own line ends. 'after'/'before': text is inserted next to
    the anchor; 'replace': the anchor line becomes text. None: the README anchor row is not there
    exactly once."""
    nl = nl_of(s)
    if f == RD:
        rows = [l for l in s.split(nl) if l.startswith('| `BB_LAMP_SHADOW_CLAMP` |')]
        if len(rows) != 1:
            return None
        return [('after', rows[0] + nl, README_ROW + nl)]
    return [(k, a.replace('\n', nl), t.replace('\n', nl)) for k, a, t in E[f]]


def state(f, s):
    """'original', 'applied' or a refusal text. An edit is there when its own text (it names r101)
    is there once; it is not when that text is absent and its anchor is there exactly once."""
    es = edits(f, s)
    if es is None:
        return 'REFUSED: README anchor row not found exactly once'
    done = []
    for k, a, t in es:
        if s.count(t) == 1:
            done.append(True)
        elif s.count(t) == 0 and s.count(a) == 1:
            done.append(False)
        else:
            return 'REFUSED: anchor found %d times, own text %d times: %r' % (s.count(a), s.count(t), a[:70])
    if all(done):
        return 'applied'
    if any(done):
        return 'REFUSED: mixed state (some edits present, some not)'
    return 'original'


def do(f, s):
    for k, a, t in edits(f, s):
        s = s.replace(a, a + t if k == 'after' else t + a if k == 'before' else t, 1)
    return s


def undo(f, s):
    # Only this patch's own text is taken out (an insert) or put back (a replace), so lines that a
    # later patch put next to the same anchors stay where they are.
    for k, a, t in edits(f, s):
        s = s.replace(t, a if k == 'replace' else '', 1)
    return s


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'check'
    if mode not in ('check', 'apply', 'revert'):
        print('usage: check|apply|revert'); return 2
    src = {f: rd(ROOT + f) for f in (SH, PS, RD)}
    st = {f: state(f, s) for f, s in src.items()}
    new_there = os.path.exists(ROOT + NEW)
    new_ours = new_there and rd(ROOT + NEW) == HEADER.replace('\n', '\r\n')
    for f in (SH, PS, RD):
        print('%-80s %s' % (f, st[f]))
    print('%-80s %s' % (NEW, 'present (ours)' if new_ours else 'present (NOT ours)' if new_there else 'absent'))
    bad = [f for f in st if st[f].startswith('REFUSED')]
    if bad:
        print('refused: nothing changed'); return 1
    if mode == 'check':
        if all(v == 'original' for v in st.values()) and not new_there:
            print('check: all original, applies cleanly')
        elif all(v == 'applied' for v in st.values()) and new_ours:
            print('check: applied')
        else:
            print('check: mixed state'); return 1
        return 0
    if mode == 'apply':
        if all(v == 'applied' for v in st.values()) and new_ours:
            print('already applied'); return 0
        if not all(v == 'original' for v in st.values()) or new_there:
            print('refused: not all original'); return 1
        os.makedirs(BK, exist_ok=True)
        out = {f: do(f, s) for f, s in src.items()}
        for f in out:
            wr(os.path.join(BK, f.replace('/', '__')), src[f])
        for f, t in out.items():
            wr(ROOT + f, t)
        wr(ROOT + NEW, HEADER.replace('\n', '\r\n'))
        print('applied in', ROOT); return 0
    # revert
    if all(v == 'original' for v in st.values()) and not new_there:
        print('already reverted'); return 0
    if not all(v == 'applied' for v in st.values()) or not new_ours:
        print('refused: not all applied (or the new header is not ours)'); return 1
    out = {f: undo(f, s) for f, s in src.items()}
    for f, t in out.items():
        wr(ROOT + f, t)
    os.remove(ROOT + NEW)
    print('reverted in', ROOT); return 0


if __name__ == '__main__':
    sys.exit(main())
