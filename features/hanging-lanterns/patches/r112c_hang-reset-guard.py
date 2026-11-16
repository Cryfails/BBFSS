"""r112c_hang-reset-guard (FEATURE fix on top of r112_wind-more-things.fixed): the slot reset wrote the
hanging top key (TopAt + slot) even when BB_WIND_HANG is off, where the sway region is only r89's 8192
bytes and TopAt = 2048 words lies past its end: 4 bytes written past the params buffer per slot reset.
Now the top key is written only when BB_WIND_HANG is on (the region then has AllBytes).
Modes: check | apply | revert. Root from R112C_ROOT, else <tree>. CRLF kept."""
import io, os, sys

ROOT = os.environ.get('R112C_ROOT', '<tree>')
F = 'engine/gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer_effects.cpp'
OLD = '        words[BbWindHang::TopAt + taken.slot] = BbWindSway::ResetKey; // bbport (r112)\r\n'
NEW = ('        if (BbWindHang::KnobOnce().on) { // bbport (r112c): the top keys exist only with BB_WIND_HANG\r\n'
       '            words[BbWindHang::TopAt + taken.slot] = BbWindSway::ResetKey; // bbport (r112)\r\n'
       '        }\r\n')


def read():
    with io.open(os.path.join(ROOT, F), 'r', encoding='utf-8', newline='') as f:
        return f.read()


def write(t):
    with io.open(os.path.join(ROOT, F), 'w', encoding='utf-8', newline='') as f:
        f.write(t)


def state(t):
    n_old, n_new = t.count(OLD), t.count(NEW)
    if n_new == 1:
        return 'applied'
    if n_old == 1 and n_new == 0:
        return 'clean'
    return 'refused (old %d, new %d)' % (n_old, n_new)


mode = sys.argv[1] if len(sys.argv) > 1 else 'check'
t = read()
s = state(t)
if mode == 'check':
    print({'applied': 'applied (text checks pass)', 'clean': 'not applied; would apply (1 file, 1 edit; text checks on the result pass)'}.get(s, 'REFUSED: ' + s))
    sys.exit(0 if s in ('applied', 'clean') else 1)
if mode == 'apply':
    if s == 'applied':
        print('already applied'); sys.exit(0)
    if s != 'clean':
        print('REFUSED: ' + s); sys.exit(1)
    write(t.replace(OLD, NEW, 1)); print('applied'); sys.exit(0)
if mode == 'revert':
    if s == 'clean':
        print('nothing to revert'); sys.exit(0)
    if s != 'applied':
        print('REFUSED: ' + s); sys.exit(1)
    write(t.replace(NEW, OLD, 1)); print('reverted'); sys.exit(0)
print('mode must be check, apply or revert'); sys.exit(2)
