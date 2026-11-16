"""r95b: halation's glow gain at strength 1 from 0.06 to 0.40 (0.06 was invisible in every test picture;
0.48 gave a visible warm halo at the alley lamp, slot batch hal4, 2026-11-15).
usage: r95b_halation-gain.py check|apply|revert      root: R95_ROOT or <tree>
Needs r95 applied. Changes one constant and the README's wording; the feature stays off by default."""
import os, sys

ROOT = os.environ.get('R95_ROOT', '<tree>')
EDITS = [
    ('engine/gpu/shadps4/video_core/renderer_vulkan/halation_params.h',
     b'inline constexpr float Gain = 0.06f;', b'inline constexpr float Gain = 0.40f;'),
    ('README.md',
     b"0.06 of the blurred excess at strength 1", b"0.40 of the blurred excess at strength 1"),
]


def state():
    old = new = 0
    for rel, a, b in EDITS:
        data = open(os.path.join(ROOT, rel), 'rb').read()
        na, nb = data.count(a), data.count(b)
        if na == 1 and nb == 0:
            old += 1
        elif na == 0 and nb == 1:
            new += 1
        else:
            return 'REFUSED: %s holds the old text %d times and the new text %d times' % (rel, na, nb)
    if old == len(EDITS):
        return 'not applied; would apply (%d edits in %d files)' % (len(EDITS), len(EDITS))
    if new == len(EDITS):
        return 'applied'
    return 'REFUSED: mixed state (%d of %d edits applied)' % (new, len(EDITS))


def swap(forward):
    for rel, a, b in EDITS:
        path = os.path.join(ROOT, rel)
        data = open(path, 'rb').read()
        src, dst = (a, b) if forward else (b, a)
        open(path, 'wb').write(data.replace(src, dst))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('check', 'apply', 'revert'):
        print(__doc__)
        return 2
    st = state()
    if sys.argv[1] == 'check':
        print(st)
        return 0 if not st.startswith('REFUSED') else 1
    if st.startswith('REFUSED'):
        print(st)
        return 1
    if sys.argv[1] == 'apply':
        if st == 'applied':
            print('already applied')
            return 0
        swap(True)
        print('applied')
        return 0
    if st != 'applied':
        print('nothing to revert')
        return 0
    swap(False)
    print('reverted')
    return 0


sys.exit(main())
