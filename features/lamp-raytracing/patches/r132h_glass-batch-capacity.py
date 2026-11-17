"""r132h reserve the glass tail before accepting another lamp draw.

Set R132H_ROOT to the source tree, then run check, apply, or revert.
Use a separate script copy for a private trial to keep the backup separate.
"""
import argparse
import os
from pathlib import Path
import sys
import tempfile

SOURCE = Path("engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp")
BEFORE = b"""        const bool room = data.size() + words + TileWords * (tiles.size() + 1) +
                              (apart || merged ? HistoryWords + LampTuneWordCount : 0) <=
                          DataWords; // bbport (r41_lamp-shadows): and the tuning words
"""
AFTER = b"""        const bool room = data.size() + words + TileWords * (tiles.size() + 1) +
                              (apart || merged
                                   ? HistoryWords + LampTuneWordCount +
                                         (glass_mode ? GlassLight::WordCount : 0u)
                                   : 0u) <=
                          DataWords; // Reserve the glass tail whenever Flush serializes it.
"""


def write_atomic(path, data):
    fd, name = tempfile.mkstemp(prefix=".r132h-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def run(mode):
    root_env = os.environ.get("R132H_ROOT")
    if not root_env:
        raise ValueError("set R132H_ROOT to the target source tree")
    root = Path(root_env).resolve()
    path = root / SOURCE
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError("R132H_ROOT is not a source tree containing vk_point_shadow.cpp")
    original = path.read_bytes()
    text = original.replace(b"\r\n", b"\n")
    crlf = text != original
    if b"\r" in text or (crlf and text.count(b"\n") != original.count(b"\r\n")):
        raise ValueError("vk_point_shadow.cpp has mixed or unsupported line endings")
    counts = text.count(BEFORE), text.count(AFTER)
    if counts not in ((1, 0), (0, 1)):
        raise ValueError("lamp batch room check missing, duplicated or modified")
    applied = counts == (0, 1)
    if mode == "check":
        print(f"r132h: {'applied' if applied else 'would apply'} (vk_point_shadow.cpp, anchor verified)")
        return
    if mode == "apply" and applied:
        print("r132h: already applied")
        return
    if mode == "revert" and not applied:
        print("r132h: nothing to revert")
        return
    if mode == "apply":
        backup = Path(__file__).resolve().parent / "r132h_backup"
        backup.mkdir(exist_ok=True)
        saved = backup / path.name
        if saved.exists():
            if saved.read_bytes() != original:
                raise ValueError("backup belongs to a different snapshot; use a separate script copy")
        else:
            write_atomic(saved, original)
    target = text.replace(AFTER, BEFORE, 1) if mode == "revert" else text.replace(BEFORE, AFTER, 1)
    if crlf:
        target = target.replace(b"\n", b"\r\n")
    if path.read_bytes() != original:
        raise ValueError("vk_point_shadow.cpp changed during patch")
    write_atomic(path, target)
    print(f"r132h: {'applied' if mode == 'apply' else 'reverted'} (vk_point_shadow.cpp)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("check", "apply", "revert"))
    try:
        run(parser.parse_args().mode)
    except (OSError, ValueError) as error:
        print(f"r132h refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
