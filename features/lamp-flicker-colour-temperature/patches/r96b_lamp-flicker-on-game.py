"""r96b: BB_LAMP_FLICKER_ON_GAME=1 lets the r96 flicker also act on flame lamps the game changes itself
(without it those lamps are left alone, so near candles and torches show only the game's own flicker).
For the owner's side by side demo (2026-11-15): the game's own flicker against r96 added on top of it.
usage: r96b_lamp-flicker-on-game.py check|apply|revert      root: R96_ROOT or <tree>
Needs r96 applied. One line of logic in lamp_flicker.h and one README row; off unless the knob is 1."""
import os, sys

ROOT = os.environ.get('R96_ROOT', '<tree>')
H = 'engine/gpu/shadps4/video_core/renderer_vulkan/lamp_flicker.h'
OLD_H = b'        const bool steady = now - lamp.changed_at >= SteadySeconds;\r\n'
NEW_H = (b'        // r96b: BB_LAMP_FLICKER_ON_GAME=1 (read once) also flickers lamps the game changes itself.\r\n'
         b'        static const bool on_game = [] {\r\n'
         b'            const char* text = std::getenv("BB_LAMP_FLICKER_ON_GAME");\r\n'
         b"            return text != nullptr && text[0] == '1' && text[1] == '\\0';\r\n"
         b'        }();\r\n'
         b'        const bool steady = on_game || now - lamp.changed_at >= SteadySeconds;\r\n')
ROW_ANCHOR = b' the nearest flame lamps every 120 frames (`Lamp flicker (r96 show):`) | off |\r\n'
ROW = (b'| `BB_LAMP_FLICKER_ON_GAME` | `1`: the flicker also acts on flame lamps whose colour or reach the game '
       b'changes itself (its own flicker stays, this one is multiplied on top); such lamps are otherwise left alone | off |\r\n')
EDITS = [(H, OLD_H, NEW_H), ('README.md', ROW_ANCHOR, ROW_ANCHOR + ROW)]


def state():
    new = 0
    for rel, a, b in EDITS:
        data = open(os.path.join(ROOT, rel), 'rb').read()
        if data.count(b) == 1:
            new += 1
        elif data.count(a) != 1 or data.count(b) != 0:
            return 'REFUSED: %s: anchor found %d times, new text %d times' % (rel, data.count(a), data.count(b))
    if new == 0:
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
