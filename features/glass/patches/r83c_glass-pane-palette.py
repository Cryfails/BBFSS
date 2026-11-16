# r83c_glass-pane-palette (FEATURE, part of r83; needs r83 and r83b): a window pane draw is no longer
# refused for carrying a small palette. The r83b probe showed at dream-house: 287 pane keys, 279 at
# the hook, 272 dropped as "pal", 7 as "skin", none captured: the pane vertex shader takes its world
# matrix from a 96-byte table (2 matrices of 48 bytes), which Motion::ClassifyBuffer counts as a
# palette. PrepareDraw's palette path (an instance entry per mesh and palette) takes such draws.
# usage: python r83c_glass-pane-palette.py apply|revert|check
import io, os, sys
ROOT = '<tree>/engine/gpu/shadps4/video_core/'
BK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'r83c_backup')
E = {
 'renderer_vulkan/vk_rasterizer_effects.cpp': [
  ('        if (ps && RtGlassMatch(vs.pgm_hash, ps->pgm_hash) && !draw.skinned && draw.palette == 0) {\n',
   '        // bbport (r83c_glass-pane-palette): a pane with a small palette (its world matrix comes from\n'
   '        // a table of 48-byte matrices, 96 bytes at the dream house) is taken: PrepareDraw gives a\n'
   '        // palette draw an entry per mesh and palette. A skinned draw (a larger table) is still left.\n'
   '        if (ps && RtGlassMatch(vs.pgm_hash, ps->pgm_hash) && !draw.skinned) {\n'),
 ],
}
def rd(p): return io.open(p, encoding='utf-8', newline='').read()
def wr(p, s): io.open(p, 'w', encoding='utf-8', newline='').write(s)
mode = sys.argv[1]
if mode == 'revert':
    for f in E:
        wr(ROOT + f, rd(os.path.join(BK, f.replace('/', '__')))); print('restored', f)
    sys.exit(0)
out = {}
for f, eds in E.items():
    s = rd(ROOT + f); crlf = '\r\n' in s; t = s.replace('\r\n', '\n')
    for a, b in eds:
        if b in t: continue
        if t.count(a) != 1: print('REFUSED', f, 'anchor count', t.count(a), a[:70]); sys.exit(1)
        t = t.replace(a, b)
    out[f] = (s, t.replace('\n', '\r\n') if crlf else t)
if mode == 'check': print('would apply' if any(a != b for a, b in out.values()) else 'applied'); sys.exit(0)
os.makedirs(BK, exist_ok=True)
for f, (s, t) in out.items():
    if s != t:
        b = os.path.join(BK, f.replace('/', '__'))
        if not os.path.exists(b): wr(b, s)
        wr(ROOT + f, t)
print('applied')
