#!/usr/bin/env python3
"""Apply the clear-film blood normal levelling fallback to exact b102 sources.

Set R133F_ROOT or pass --root TREE. Run check, apply, or revert.
The payload changes two blood host files. Revert restores their exact b102 bytes.
"""

import argparse
import hashlib
import os
from pathlib import Path
import stat
import tempfile


SOURCES = [['engine/gpu/shadps4/video_core/renderer_vulkan/blood_sheen.h',
  '04d711ba332c39ee66b0f1190e39fba1664f288be1dbe914fcd0b61fed8447ec',
  '106cfea1102baf8bf34ebaf76849cf4ecd7a8a60d1aec9309516a99fec8e9ef1',
  [[61,
    61,
    '//   BB_BLOOD_SHEEN_LEVEL  bbport (r130a): a live test knob, 0..1, default 1: scales the normal '
    "levelling (0: the ground's\r\n"
    '//                         own relief)\r\n',
    "//   BB_BLOOD_SHEEN_LEVEL  0..1: normal levelling (0 keeps the ground's relief). Defaults to 0.25 in "
    'clear film and 1\r\n'
    '//                         in the other tint modes. A valid startup or live value overrides the '
    'default.\r\n'],
   [547,
    547,
    "/// bbport (r130a_sheen-colour): BB_BLOOD_SHEEN_GLOSS and BB_BLOOD_SHEEN_LEVEL's text: a number into "
    '0..1; unset, empty or other\r\n'
    '/// text: 1 (as ReadDarken, with the default 1).\r\n'
    'inline float ReadShare(const char* text) {\r\n',
    '/// A finite share clamped to 0..1, or fallback if the text is absent or invalid.\r\n'
    'inline float ReadShareOr(const char* text, float fallback) {\r\n'],
   [551, 550, '        return 1.0f;\r\n', '        return fallback;\r\n'],
   [556, 555, '        return 1.0f;\r\n', '        return fallback;\r\n'],
   [561,
    560,
    "    return *end == '\\0' ? std::clamp(value, 0.0f, 1.0f) : 1.0f;\r\n",
    "    return *end == '\\0' ? std::clamp(value, 0.0f, 1.0f) : fallback;\r\n"
    '}\r\n'
    '\r\n'
    '/// BB_BLOOD_SHEEN_GLOSS has the same default in every mode.\r\n'
    'inline float ReadShare(const char* text) {\r\n'
    '    return ReadShareOr(text, 1.0f);\r\n'
    '}\r\n'
    '\r\n'
    'constexpr float LevelOf(int tint, float override_share) {\r\n'
    '    return override_share >= 0.0f ? override_share : (tint == 2 ? 0.25f : 1.0f);\r\n']]],
 ['engine/gpu/shadps4/video_core/renderer_vulkan/vk_blood_sheen.cpp',
  '1812564892f7011950e6f2dc72f3a4085ccbe1674a83585c54d26da2722dcc35',
  'd514ac6bb6b759f3404195d97e65c8b5558cc3d60a7b4fb843093e3a9e9ca45b',
  [[103,
    103,
    '/// BB_BLOOD_SHEEN_TINT, _GLOSS, _LEVEL and _DARKEN (r130a_sheen-colour, live, test knobs): the film '
    'colour probes. Each is the\r\n'
    "/// default (TINT 1, GLOSS 1, LEVEL 1, DARKEN the setting's) in a build without the live knobs header; "
    'each says its change in\r\n'
    "/// the log. Their calls keep the string on the line after the call (r129b's text check wants it "
    'so).\r\n',
    '/// Film colour controls. TINT and LEVEL also read startup overrides without the live knobs '
    'header.\r\n'],
   [153,
    151,
    'float LevelShare() {\r\n',
    'float LevelShare(int tint) {\r\n'
    '    constexpr auto parse = [](const char* text) { return R::ReadShareOr(text, -1.0f); };\r\n'],
   [155,
    154,
    '    static BbLiveKnobs::Knob<float> knob{"BB_BLOOD_SHEEN_LEVEL", R::ReadShare};\r\n',
    '    static BbLiveKnobs::Knob<float> knob{"BB_BLOOD_SHEEN_LEVEL", parse};\r\n'
    '    const float level = knob.Get();\r\n'
    '#else\r\n'
    '    static const float level = parse(std::getenv("BB_BLOOD_SHEEN_LEVEL"));\r\n'
    '#endif\r\n'
    '    const float now = R::LevelOf(tint, level);\r\n'
    '    const bool overridden = level >= 0.0f;\r\n'],
   [157,
    162,
    '    const float now = knob.Get();\r\n    if (now != last) {\r\n',
    '    static bool last_overridden = false;\r\n'
    '    if (now != last || overridden != last_overridden) {\r\n'],
   [160, 165, '', '        last_overridden = overridden;\r\n'],
   [161,
    167,
    '            "Blood sheen (r130a): level share %.2f (BB_BLOOD_SHEEN_LEVEL)\\n", double(now));\r\n',
    '            "Blood sheen (r130a): level share %.2f (BB_BLOOD_SHEEN_LEVEL, %s)\\n",\r\n'
    '            double(now), overridden ? "override" : "tint default");\r\n'],
   [164, 171, '#else\r\n    return 1.0f;\r\n#endif\r\n', ''],
   [355,
    359,
    '        "BB_BLOOD_SHEEN_LEVEL shares (1 = as r129b); BB_BLOOD_SHEEN_DARKEN now live\\n");\r\n',
    '        "BB_BLOOD_SHEEN_LEVEL shares (1 = as r129b; level defaults to 0.25 for tint 2, 1 otherwise); '
    '"\r\n'
    '        "BB_BLOOD_SHEEN_DARKEN now live\\n");\r\n'],
   [850,
    855,
    '        push.darken = std::bit_cast<float>(R::PackScales(GlossShare(), LevelShare()));\r\n',
    '        push.darken = std::bit_cast<float>(R::PackScales(GlossShare(), LevelShare(tint)));\r\n'],
   [1013,
    1018,
    '            double(GlossShare()), double(LevelShare()), double(DarkenNow(R::Load())), tint == 2 ? ", by '
    'redness" : "");\r\n',
    '            double(GlossShare()), double(LevelShare(tint)), double(DarkenNow(R::Load())), tint == 2 ? '
    '", by redness" : "");\r\n']]]]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    if any(part.is_symlink() or getattr(part, 'is_junction', lambda: False)() for part in (path, *path.parents)):
        raise ValueError(f"linked path {path.name}")
    return path.read_bytes()


def transform(data, changes, revert):
    lines = data.decode().splitlines(keepends=True)
    for old_at, new_at, old_text, new_text in reversed(changes):
        index, old, new = (new_at, new_text, old_text) if revert else (old_at, old_text, new_text)
        expected = old.splitlines(keepends=True)
        stop = index + len(expected)
        if lines[index:stop] != expected:
            raise ValueError("source hunk mismatch")
        lines[index:stop] = new.splitlines(keepends=True)
    return "".join(lines).encode()


def write_exact(path, previous, data):
    if read(path) != previous:
        raise ValueError(f"{path.name} changed during r133f")
    permissions = stat.S_IMODE(path.stat().st_mode)
    fd, name = tempfile.mkstemp(prefix=".r133f-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        temporary.chmod(permissions)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def run(root, mode):
    sources = [(root / path, before, after, changes, read(root / path))
               for path, before, after, changes in SOURCES]
    states = set()
    for path, before, after, _, data in sources:
        source_sha = digest(data)
        if source_sha == before:
            states.add("base")
        elif source_sha == after:
            states.add("applied")
        else:
            raise ValueError(f"{path.name} differs from its exact b102 or r133f SHA")
    if len(states) != 1:
        raise ValueError("partial r133f state")
    applied = states == {"applied"}
    count = len(sources)
    if mode == "check":
        print(f"r133f: {'applied' if applied else 'would apply'} ({count} files)")
        return
    if (mode == "apply") == applied:
        print(f"r133f: {'applied' if applied else 'already reverted'} ({count} files)")
        return

    updates = []
    for path, before, after, changes, data in sources:
        result = transform(data, changes, applied)
        if digest(result) != (before if applied else after):
            raise ValueError(f"{path.name} transformed SHA mismatch")
        updates.append((path, data, result))
    if applied:
        updates.reverse()
    completed = []
    try:
        for path, previous, result in updates:
            write_exact(path, previous, result)
            completed.append((path, previous, result))
    except (OSError, ValueError):
        for path, previous, result in reversed(completed):
            write_exact(path, result, previous)
        raise
    print(f"r133f: {'reverted' if applied else 'applied'} ({count} files)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "apply", "revert"))
    parser.add_argument("--root", type=Path, default=os.environ.get("R133F_ROOT"))
    args = parser.parse_args()
    if args.root is None:
        parser.exit(1, "r133f refused: set R133F_ROOT or pass --root TREE\n")
    try:
        run(args.root.resolve(), args.mode)
    except (OSError, ValueError) as error:
        parser.exit(1, f"r133f refused: {error}\n")
