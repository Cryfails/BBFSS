# r90_lamp-clearance-default (FEATURE, lamp work): the blind sphere at a ray traced lamp shrinks from
# 0.35 m to 0.18 m by default (BB_LAMP_SHADOW_CLEARANCE still sets it). Owner's look in play,
# 2026-11-15: with 0.18 the hand lantern shadows the legs, and a torch near a wall no longer lights
# through it. A pass never uses less than its lamp's radius plus 0.05 m (LampPassClearance), so the
# lamp's own centre stays blind at the wider "softer" disc (0.25 m there).
# usage: python r90_lamp-clearance-default.py apply|revert|check
import io, os, sys
ROOT = '<tree>/'
BK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'r90_backup')
T = 'engine/gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h'
E = {
 T: [
  ('    float clearance_m = 0.35f;   ///< BB_LAMP_SHADOW_CLEARANCE, 0.05..2: blind sphere at the lamp',
   '    float clearance_m = 0.18f;   ///< BB_LAMP_SHADOW_CLEARANCE, 0.05..2: blind sphere at the lamp\n'
   '                                 ///< (bbport r90_lamp-clearance-default: 0.18, 0.35 before;\n'
   '                                 ///< what a pass uses: LampPassClearance)'),
  ('///    clearance_m (0.35 m) of its target, a point of the disc at most the radius from the',
   '///    its pass\'s clearance (LampPassClearance: 0.25 m here) of its target, a point of the disc at\n'
   '///    most the radius from the'),
  ('(0.15 m at\n///    0.2 m), where', '(0.05 m at\n///    0.2 m), where'),
  ('(0.55 m at 0.2 m)', '(0.45 m at 0.2 m)'),
  ('/// What the shader reads at the place the mode word names.',
   '/// bbport (r90_lamp-clearance-default): the blind distance at a ray\'s target that a pass uses:\n'
   '/// clearance_m, but at least the lamp\'s radius plus LampClearanceOverRadius, so the lamp\'s centre\n'
   '/// (where its own model sits) is blind to every ray to its disc. 0.18 m for a point lamp and the\n'
   '/// soft disc (0.1 m), 0.25 m for the softer one (0.2 m).\n'
   'inline constexpr float LampClearanceOverRadius = 0.05f;\n'
   'inline float LampPassClearance(const LampShadowTune& tune) {\n'
   '    return std::max(tune.clearance_m, tune.radius_m + LampClearanceOverRadius);\n'
   '}\n\n'
   '/// What the shader reads at the place the mode word names.'),
  ('            bits(tune.clearance_m),', '            bits(LampPassClearance(tune)), // bbport (r90_lamp-clearance-default)'),
 ],
 'engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp': [
  ('const float LAMP_CLEARANCE = 0.35;', 'const float LAMP_CLEARANCE = 0.18; // bbport (r90_lamp-clearance-default): 0.35 before'),
 ],
 'engine/tests/test_lamp_shadow_tune.cpp': [
  ('        assert(t.clearance_m == 0.35f && t.bias_m == 0.03f);',
   '        assert(t.clearance_m == 0.18f && t.bias_m == 0.03f); // bbport (r90): 0.35 before'),
  ('        assert(LampSoftnessRadii[2] > LampSoftnessRadii[1] && LampSoftnessRadii[2] < d.clearance_m);',
   '        assert(LampSoftnessRadii[2] > LampSoftnessRadii[1]);\n'
   '        // bbport (r90_lamp-clearance-default): the pass\'s clearance keeps it so at every radius\n'
   '        for (const float r : LampSoftnessRadii) {\n'
   '            LampShadowTune p = d;\n'
   '            p.radius_m = r;\n'
   '            assert(LampPassClearance(p) > r && LampPassClearance(p) >= d.clearance_m);\n'
   '        }\n'
   '        {\n'
   '            LampShadowTune p = d;\n'
   '            p.radius_m = 0.1f;\n'
   '            assert(LampPassClearance(p) == 0.18f);\n'
   '            p.radius_m = 0.2f;\n'
   '            assert(std::abs(LampPassClearance(p) - 0.25f) < 1e-6f);\n'
   '        }'),
  ('        assert(F(words[1]) == 0.35f && F(words[2]) == 0.1f && words[3] == 0u);',
   '        assert(F(words[1]) == 0.18f && F(words[2]) == 0.1f && words[3] == 0u); // bbport (r90)'),
 ],
 'README.md': [
  ('| `BB_LAMP_SHADOW_CLEARANCE` | A ray is blind within this distance of its target, in metres, 0.05 to 2 | `0.35` |',
   '| `BB_LAMP_SHADOW_CLEARANCE` | A ray is blind within this distance of its target, in metres, 0.05 to 2; a pass never uses less than its lamp\'s radius plus 0.05 | `0.18` |'),
 ],
}
def rd(p): return io.open(p, encoding='utf-8', newline='').read()
def wr(p, s): io.open(p, 'w', encoding='utf-8', newline='').write(s)
mode = sys.argv[1]
if mode == 'revert':
    for f in E:
        b = os.path.join(BK, f.replace('/', '__'))
        wr(ROOT + f, rd(b)); print('restored', f)
    sys.exit(0)
out = {}
for f, eds in E.items():
    s = rd(ROOT + f); crlf = '\r\n' in s; t = s.replace('\r\n', '\n')
    for a, b in eds:
        if b in t: continue
        if t.count(a) != 1: print('REFUSED', f, 'anchor count', t.count(a), a[:60]); sys.exit(1)
        t = t.replace(a, b)
    out[f] = (s, t.replace('\n', '\r\n') if crlf else t)
if mode == 'check': print('would apply' if any(a != b for a, b in out.values()) else 'applied'); sys.exit(0)
os.makedirs(BK, exist_ok=True)
for f, (s, t) in out.items():
    if s != t:
        b = os.path.join(BK, f.replace('/', '__'))
        wr(b, s)
        wr(ROOT + f, t)
print('applied')
