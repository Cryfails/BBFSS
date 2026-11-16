# r101b_lamp-moving-edge-fix (FEATURE follow-up to r101_lamp-moving-edge; review 2026-11-15). Text and a
# compile-time check only: no rule, no constant, no picture and no cost changes (the 10 point_shadow_ray
# builds compile to the same SPIR-V words with and without it: only a shader comment changes).
#
# What it fixes (maintainer rules 7 and 10):
# 1. Rule 7: r101's comment, header, README row and once-line say a block is shared only where its
#    pixel "held history before this frame". The code tests the history the first pass has just
#    written for that pixel (history_cur b = frames + 1 > 1.5, frames being what this frame's guards
#    left), so a pixel that held nine frames before this frame and lost them to the clamp this frame is
#    YOUNG (that is the case r101 is for), and one frame after a cut two equal rays pass again. The
#    texts now say that. The README and header also said that the show setting 2 sends "nearly every
#    pixel whose block is not wholly settled" to its own ray; 2 only narrows the last-frames test to
#    1/64 and keeps the frames test, so that claim is replaced by what it does. The README row now
#    also says what an un-shared pixel shows (its own rays: finer noise in place of 2x2 steps) and
#    that a camera cut or a newly seen area costs one frame of full-resolution rays there, and it
#    marks its cost figure as an estimate (rule 8: it was not measured).
# 2. Rule 10: r101's static_assert that word 0 bits 2 and 3 are free left out the two word-0 bits
#    added since (r91 LampTuneDiscEach bit 24, r93 LampTuneSpatial bit 26) and r92's pending bit 25.
#    It now names r91's and r93's constants and bit 25.
# 3. The once-line was 301 characters (307 with 2), past the 300 the slot worker keeps of a log line
#    (Test-BBFSSSlot.ps1 evidence); its new text is 289 (295 with 2).
#
# Needs: r101 applied as published (its own texts are the anchors), r91 and r93 applied (their
# constants in lamp_shadow_tune.h; checked). Every edit replaces r101's own text, so r101's check
# reports a mixed state while r101b is in: revert r101b BEFORE r101. Lines other patches put next to
# r101's lines are not touched.
#
# Files: renderer_vulkan/lamp_moving_edge.h (r101's own file: a comment, the static_assert, the
# once-line's text), host_shaders/point_shadow_ray.comp (two lines of r101's comment, inside #ifdef
# HALF), README.md (r101's row, replaced in place).
#
# usage: python -I -X utf8 r101b_lamp-moving-edge-fix.py check|apply|revert
# root: env R101B_ROOT, else <tree>. Backups of the originals: r101b_backup next to this script.
# Every edit refuses unless its old text (apply) or new text (revert) is found exactly once.
import io, os, sys

ROOT = os.environ.get('R101B_ROOT', '<tree>').rstrip('/\\') + '/'
BK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'r101b_backup')
SH = 'engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp'
HD = 'engine/gpu/shadps4/video_core/renderer_vulkan/lamp_moving_edge.h'
TU = 'engine/gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h'
RD = 'README.md'

OLD_ROW = ('| `BB_LAMP_SHADOW_MOVING_EDGE` | Half-resolution lamp shadows only (`graphics_lamp_shadow_half=1`, '
           'soft or softer): `1` shares a 2x2 block\'s answer with its other three pixels only once that '
           'answer has settled (its pixel held history before this frame and its last few frames agree '
           'with it within 0.125), so behind a moving shadow a block whose history was just given up does '
           'not hand its bare one-ray answer and young history to all four pixels; `2` (show) the same '
           'within 1/64; `0` off. Nothing is made for it; on, about 0.01 ms plus the rays of the pixels it '
           'sends to their own rays (moving edges only). Log: "(r101)" lines | `0` |\n')
NEW_ROW = ('| `BB_LAMP_SHADOW_MOVING_EDGE` | Half-resolution lamp shadows only (`graphics_lamp_shadow_half=1`, '
           'soft or softer, in the pass that averages): `1` shares a 2x2 block\'s answer with its other three '
           'pixels only where the block\'s pixel kept more than half a frame of history through this frame\'s '
           'guards (the reject, the clamp, the trail) and the mean of its last few frames lies within 0.125 '
           'of its ratio; elsewhere each of the three casts its own ray and keeps its own history. So behind '
           'a moving shadow a block whose history was just given up does not hand its bare one-ray answer '
           'and young history to all four pixels; they show their own rays instead (finer noise in place of '
           '2x2 steps, which `BB_LAMP_SHADOW_SPATIAL=1` smooths at `BB_LAMP_SHADOW_WINDOW=2`). A block whose '
           'pixel kept one frame or more (two equal rays after a cut) is shared again. `2` (show) the same '
           'with 1/64 in place of 0.125 (the frames test stays); `0` off. Nothing is made for it; on, an '
           'estimate, not measured: about 0.01 ms plus the rays of the pixels it sends to their own rays '
           '(moving edges, and for one frame the blocks of a camera cut or of a newly seen area). Log: '
           '"(r101)" lines | `0` |\n')

E = {
 HD: [
  ("// moving edge. 0 (the default): as before. 1: a block's answer is taken only where its pixel held\n"
   "// history before this frame and its last few frames agree with its ratio within 0.125. 2 (show):\n"
   "// within 1/64, so nearly every pixel whose block is not wholly settled casts its own ray (for\n"
   "// tests). Read once, at the first lamp pass. No Vulkan here.\n",
   "// moving edge. 0 (the default): as before. 1: a block's answer is taken only where its pixel kept\n"
   "// more than half a frame of history through this frame's guards (history_cur b = frames + 1 > 1.5,\n"
   "// as the first pass just wrote it) and the mean of its last few frames (a) lies within 0.125 of its\n"
   "// ratio. 2 (show): the same with 1/64 (the frames test stays: two equal rays after a cut pass it).\n"
   "// An un-shared pixel shows its own rays (finer noise in place of 2x2 steps). Read once, at the\n"
   "// first lamp pass. No Vulkan here.\n"),
  ("               (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft | LampTuneWindow |\n"
   "                LampTuneCentred | (7u << LampTuneViewShift) |\n"
   "                (LampTuneCardCapMask << LampTuneCardCapShift))) == 0,\n",
   "               (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft | LampTuneWindow |\n"
   "                LampTuneCentred | (7u << LampTuneViewShift) |\n"
   "                (LampTuneCardCapMask << LampTuneCardCapShift) |\n"
   "                LampTuneDiscEach | (1u << 25) | LampTuneSpatial)) == 0, // r101b: r91, r92 (pending), r93\n"),
  ('                        "resolution a 2x2 block\'s answer is shared only once it has settled (history "\n'
   '                        "before this frame, its last frames within %s of it); else the pixel casts its "\n',
   '                        "resolution a 2x2 block\'s answer is shared only once it has settled (history "\n'
   '                        "kept this frame, last frames within %s); else the pixel casts its "\n'),
 ],
 SH: [
  ("// a block's answer is taken only once it has settled: its pixel held history before this frame\n"
   "// (history_cur b, the frames + 1, over 1.5) and its mean of the last few frames (a) lies within\n",
   "// a block's answer is taken only once it has settled: its pixel kept history through this frame's\n"
   "// guards (history_cur b = frames + 1 > 1.5) and its mean of the last few frames (a) lies within\n"),
 ],
 RD: [(OLD_ROW, NEW_ROW)],
}
# What must be there (and stay) for the result to compile and mean what it says.
NEEDS = {
 TU: ['inline constexpr std::uint32_t LampTuneDiscEach = 1u << 24;',
      'inline constexpr std::uint32_t LampTuneSpatial = 1u << 26;'],
 HD: ['#include "video_core/renderer_vulkan/lamp_shadow_tune.h"', 'static_assert(((LampTuneMovingEdge | LampTuneMovingEdgeShow) &'],
 SH: ['            if (!(h.b > 1.5) || !(abs(h.a - own.x) <= settled)) {',
      'const float MOVING_EDGE_SETTLED = 0.125;'],
}
FILES = (SH, HD, RD)


def rd(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        return f.read()


def wr(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


def nl_of(s):
    return '\r\n' if '\r\n' in s else '\n'


def edits(f, s):
    nl = nl_of(s)
    return [(a.replace('\n', nl), b.replace('\n', nl)) for a, b in E[f]]


def state(f, s):
    """'original', 'applied' or a refusal text."""
    done = []
    for a, b in edits(f, s):
        na, nb = s.count(a), s.count(b)
        if na == 1 and nb == 0:
            done.append(False)
        elif na == 0 and nb == 1:
            done.append(True)
        else:
            return 'REFUSED: old text %d times, new text %d times: %r' % (na, nb, a.strip()[:70])
    if all(done):
        return 'applied'
    if any(done):
        return 'REFUSED: mixed state (some edits present, some not)'
    return 'original'


def needs(texts):
    miss = []
    for f, items in NEEDS.items():
        for t in items:
            if texts[f].count(t.replace('\n', nl_of(texts[f]))) != 1:
                miss.append('%s: %r' % (f, t[:70]))
    return miss


def line_ends_ok(s):
    return s.count('\n') == s.count('\r\n') or '\r\n' not in s


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'check'
    if mode not in ('check', 'apply', 'revert'):
        print('usage: check|apply|revert'); return 2
    if not os.path.isfile(ROOT + SH):
        print(ROOT, 'is not a source tree root (set R101B_ROOT)'); return 2
    src = {f: rd(ROOT + f) for f in FILES + (TU,)}
    st = {f: state(f, src[f]) for f in FILES}
    for f in FILES:
        print('%-80s %s' % (f, st[f]))
    miss = needs(src)
    if miss:
        print('needs (r101, r91, r93 applied) not met:', *miss, sep='\n  ')
    if any(v.startswith('REFUSED') for v in st.values()) or miss:
        print('refused: nothing changed'); return 1
    if mode == 'check':
        if all(v == 'original' for v in st.values()):
            print('check: not applied, applies cleanly (5 edits in 3 files)')
        elif all(v == 'applied' for v in st.values()):
            print('check: applied (r101\'s own check reports a mixed state until this is reverted)')
        else:
            print('check: mixed state'); return 1
        return 0
    if mode == 'apply':
        if all(v == 'applied' for v in st.values()):
            print('already applied'); return 0
        if not all(v == 'original' for v in st.values()):
            print('refused: not all original'); return 1
        out = {}
        for f in FILES:
            t = src[f]
            for a, b in edits(f, t):
                t = t.replace(a, b, 1)
            out[f] = t
        if any(state(f, out[f]) != 'applied' for f in FILES) or needs({**src, **out}) or \
                not all(line_ends_ok(t) for t in out.values()):
            print('refused: the result does not check'); return 1
        os.makedirs(BK, exist_ok=True)
        for f in FILES:
            wr(os.path.join(BK, f.replace('/', '__')), src[f])
        for f in FILES:
            wr(ROOT + f, out[f])
        print('applied in', ROOT); return 0
    if all(v == 'original' for v in st.values()):
        print('already reverted'); return 0
    if not all(v == 'applied' for v in st.values()):
        print('refused: not all applied'); return 1
    out = {}
    for f in FILES:
        t = src[f]
        for a, b in edits(f, t):
            t = t.replace(b, a, 1)
        out[f] = t
    if any(state(f, out[f]) != 'original' for f in FILES):
        print('refused: the result does not check'); return 1
    for f in FILES:
        wr(ROOT + f, out[f])
    print('reverted in', ROOT); return 0


if __name__ == '__main__':
    sys.exit(main())
